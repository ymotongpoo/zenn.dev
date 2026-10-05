---
title: "メトリクス、ログ、トレース"
---

ここまでの章で、デバイスから[OTLP](https://opentelemetry.io/ja/docs/specs/otlp/)のメトリクスを送る経路はそろいました。この章で決めていくのは、その経路に乗せる中身です。OpenTelemetryが扱うテレメトリーの種類を**シグナル**と呼びます。本書の実装が送るのはメトリクス、ログ、トレースの3つのシグナルで、メトリクスは10秒ごと、ログとトレースはメトリクスの送信が成功した直後に送ります。

SDKを使わない以上、何を測り、どこまでをデバイスで持つのかは自分で決めることになります。判断の基準は一貫していて、デバイスの外からは知りようがないことだけをデバイスで記録し、溜める量には上限を置きます。

## メトリクスの選び方

メトリクスは12本のタイムシリーズ（名前と属性の組み合わせごとの時系列）です。起動からの経過時間、Wi-Fiの電波強度、メモリ、送信の結果、ログとスパンの取りこぼしの件数を送っています。名前から中身が推測できるものは説明を省き、ここでは選び方に理由のある3つを見てみましょう。

### 2種類のメモリ

メモリは `device.memory.usage` と `device.memory.limit` の組を、`device.memory.pool` 属性を変えて2組送ります。1組は `runtime.ReadMemStats` で読んだGoのヒープで、もう1組はWi-Fiドライバのアリーナ（ドライバが起動時に確保して自分で管理する固定長の領域）です。

```go
runtime.ReadMemStats(&ms)
heapInuse.Set(float64(ms.HeapInuse))
heapTotal.Set(float64(ms.HeapSys))

used, capacity := espradio.ArenaStats()
arenaUsed.Set(float64(used))
arenaCap.Set(float64(capacity))
```

アリーナは9章で見たとおり、GoのGCからは見えません。`runtime.MemStats` だけを送っていると、メモリが足りなくなったときに、それがGoのヒープの問題なのか[espradio](https://github.com/tinygo-org/espradio)（TinyGoからESP32のWi-Fiを使うためのドライバ）の問題なのかを区別できなくなります。実機で読んだアリーナの使用量は、容量49,144バイトに対して31,312バイトで一定でした。`ms` はループの外で宣言して使い回しています。メモリを読む処理そのものが、読む対象のヒープを増やさないようにするためです。

### 接続中のAPのRSSI

**RSSI**（Received Signal Strength Indicator）は受信した電波の強さで、単位はdBmです。送信の失敗が続いたとき、電波が弱いのかCollectorが落ちているのかを切り分けるために送っています。

espradio v0.3.0には、接続中のアクセスポイント（AP）のRSSIを返すGoの関数がありません。`espradio.Scan()` が列挙するのは周辺のAPで、接続中のリンクの値の代わりにはなりません。一方、Espressifが提供するWi-Fiのバイナリライブラリ（以下ブロブ）には[`esp_wifi_sta_get_rssi`](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/network/esp_wifi.html)があり、espradioはこのブロブをリンクしています。シンボルはすでにバイナリの中にあるので、cgoのプリアンブルでプロトタイプを宣言すれば呼び出しは成立します。

```go
/*
int esp_wifi_sta_get_rssi(int *rssi);
*/
import "C"

func stationRSSI() (int, error) {
	var v C.int
	if code := C.esp_wifi_sta_get_rssi(&v); code != 0 {
		return 0, errRSSI
	}
	return int(v), nil
}
```

espradio自体には手を入れていません。ドライバにラッパーが無くても、リンク済みのCの関数ならこの方法で値を取り出せます。プロトタイプの宣言は、espradioが同梱しているブロブのヘッダー（`esp_wifi.h`）と同じ形です。

### 送信の結果を3つに分ける

`device.export.attempts` はカウンターで、`outcome` 属性に `success`、`failure`、`partial_rejection` の3つの値を持ちます。`partial_rejection` は、HTTPでは200が返ったものの、応答の `partialSuccess` でCollectorが一部のデータポイントを拒否したと伝えてきた場合です（7章を参照）。これを成功に数えると、データが欠けていても成功率は100%のままになります。かといって接続断と同じ失敗に数えても、送り直せば同じ理由でまた拒否されるので、別の値として数えています。

カウンターと `device.export.payload` は前回の送信の結果を表します。今回の送信で値が変わる前に、エンコードの段階で読み取るからです。

## ログの記録と上限

ログは、デバイスで起きた出来事をOTLPのログレコードとして `/v1/logs` に送ります。記録するのは、起動、送信の失敗の始まり、失敗からの回復、Collectorによる部分的な拒否の4種類です。失敗は連続していても最初の1件だけを記録し、回復のログに失敗の回数を属性として持たせます。失敗のたびに記録すると、障害が続く間に同じ内容のレコードがバッファを埋めてしまうからです。

ログの形式はメトリクスのエンコーディングにかかわらず常にJSONで、OTLP/HTTPはリクエストごとに `Content-Type` を選べます。ログのためだけに手書きのprotobufエンコーダを増やしても、Collectorが受け取る内容は同じです。接続はメトリクスの送信に使ったTCP接続をそのまま使い回すので、ログを足しても接続は増えません。

Collectorに届かない間も出来事は起き続けるので、バッファに上限が無いと、通信障害がそのままメモリ不足によるリセットにつながってしまいます。そこでログは16件の固定長のリングバッファに溜め、満杯なら最も古いレコードを上書きして、その件数を数えます。

```go
} else {
	// Full: overwrite the oldest.
	i = b.head
	b.head = (b.head + 1) % len(b.records)
	b.Dropped++
}
```

数えた件数は `device.logs.dropped` メトリクスとして送ります。ログを失ったという事実は、ログ自身では伝えられません。失ったレコードは手元に無いからです。この件数をメトリクス側に持たせておけば、ダッシュボードで欠損の有無を確かめられます。

レコードのタイムスタンプには、送った時刻ではなく出来事が起きた時刻を入れています。実機でCollectorを25秒止めたところ、`export failed` はCollectorが止まっていた07:04:54の時刻で、`export recovered`（`failed_attempts=2`）は復帰後の07:05:17の時刻でLokiに届きました。障害中に記録したログも、届いた時点で正しい順序に並ぶということです。

## 送信周期のトレース

トレースの単位は、10秒ごとの送信の1周期です。周期全体を表すルートの**スパン**（処理1つぶんの開始時刻と終了時刻を持つ記録）の下に、値の読み取り（`collect`）、エンコード（`encode`）、Collectorへの `POST /v1/metrics` の3つの子スパンを置きます。HTTPのスパンだけは種類がCLIENTで、送信に失敗するとステータスがERRORになります。

サーバーであれば、SDKと計装ライブラリが作るものです。ここでは、開始と終了の時刻を記録してIDを振るだけのコードで済んでいます。

```go
cycle := spans.start(trace, otlpjson.SpanID{}, "export cycle", otlpjson.SpanKindInternal)

collect := spans.start(trace, cycle.s.SpanID, "collect", otlpjson.SpanKindInternal)
```

トレースIDとスパンIDは `crypto/rand` で作っています。TinyGoはESP32-S3の `crypto/rand` を、チップに内蔵されたハードウェアの乱数生成器（`machine.GetRNG`）で実装しているので、IDのために疑似乱数の種を管理する必要はありません[^rng]。OTLP/JSONではIDを16進文字列で書く点は、6章で触れたとおりです。

[^rng]: コードのコメントでは、この乱数生成器が無線のノイズを源にしているため、IDはWi-Fiの接続後に作ると記録しています。ESP32-S3の乱数生成器の仕様は[テクニカルリファレンスマニュアル](https://www.espressif.com/sites/default/files/documentation/esp32-s3_technical_reference_manual_en.pdf)にあります。

スパンもログと同じく常にJSONで送り、16件の固定長のバッファに溜めます。送る順番はメトリクスが先です。HTTPのスパンは送信が終わるまで閉じられないので、トレースはメトリクスの送信が終わってからでないと送れません。送信に失敗した周期のスパンはバッファに残り、回復後の最初の成功でまとめて届きます。1周期で4本のスパンを作るので、16件のバッファに収まるのは4周期ぶんです。それを超えたぶんは古いものから押し出され、件数が `device.spans.dropped` に加わります。

実機で記録した1周期の例では、全体が14.5ms、`collect` が0.47ms、`encode` が2.31ms、`POST /v1/metrics` が11.34msでした。この例では、周期の8割近くをCollectorへのHTTPリクエストが占め、エンコードは2割に届きません。どこに時間がかかっているのかを、デバイスの上で推測せずにトレースから読み取れます。Tempoがスパンから所要時間のメトリクスを作るので、ダッシュボードでは周期ごとの値の推移も見られます（次章）。

## 3シグナルのコスト

ログとトレースを足すと、送信の1周期でPOSTが3回になり、4本のスパンのIDの16進化と文字列の組み立てが加わります。その結果、1周期あたりのヒープの使い捨ての確保は、メトリクスだけのときの800バイトから2,992バイトに増えました。

増えたのは確保の量であって、保持しているメモリではありません。30分の連続試験では180回の送信がすべて成功し、GCは7回（約5分おき）走りました。GC後のヒープは7回とも約204KBにとどまりました。途中でCollectorを再起動したときも、9.1秒後に送信が再開しました。試験の手順と、メトリクスだけを送る版との比較は次章にあります。
