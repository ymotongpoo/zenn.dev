---
title: "時刻"
---

TinyGoで書いたESP32-S3のプログラムが起動直後に読む時刻は、Unix時間の起点である1970年1月1日です。サーバーではOSが時刻を合わせてくれるので意識しませんが、[OTLP](https://opentelemetry.io/ja/docs/specs/otlp/)で送るデータには実際の時刻が必要です。この章では、なぜ時刻が必要なのかを確かめたあと、デバイスで時刻を合わせるために書いたSNTPクライアントを見ていきます。

## OTLPが時刻を要求する理由

OTLPのデータポイントには、観測した時刻を表す`time_unix_nano`があります。1970年1月1日からのナノ秒をuint64で表したもので、OTLP/JSONでは文字列で書きます（6章）。この値が1970年のままだと、Grafanaのようなバックエンドはデータを56年前のものとして認識するので、ダッシュボードの時間範囲には何も表示されません。

累積カウンターの場合は、もう1つの時刻`start_time_unix_nano`も必要です。累積カウンターは起動からの合計値を毎回送るメトリクスで、本書のデバイスでは送信の成功回数や失敗回数がこれにあたり、`start_time_unix_nano`はその合計を数え始めた時刻です。[OpenTelemetryのメトリクスのデータモデル](https://opentelemetry.io/ja/docs/specs/otel/metrics/data-model/)では、バックエンドはこの値を手がかりにして、カウンターのリセットとデータの欠損を見分けます。

デバイスが再起動すると、カウンターは0から数え直します。再起動のあとに届いたデータポイントの開始時刻が前のものと違っていれば、バックエンドは値が減った理由をリセットと判断し、増加量を正しく計算できます。一方、開始時刻が同じまま値の間隔が空いていれば、その間のデータは届かなかったという扱いです。開始時刻がどれも1970年1月1日の近くに貼り付いていると、リセットと欠損を区別する材料がなくなってしまいます。

本書のデバイスは、起動して時刻を合わせた直後の時刻を開始時刻として保持し、累積カウンターのデータポイントに毎回付けます。ゲージ（その時点の値を送るメトリクス）には区間がないので、開始時刻を付けません。

```go
// A cumulative counter needs a real start time or the backend cannot tell
// a reset from a gap. espradio does not sync the clock on its own, so ask
// an SNTP server directly. See sntp.go for why.
start := syncClockOrWarn(l)
startNanos := uint64(start.UnixNano())
```

## espradioが時刻を合わせない理由

Wi-Fiドライバの[espradio](https://github.com/tinygo-org/espradio)が使うTCP/IPスタックの[lneto](https://github.com/soypat/lneto)は、時刻を合わせるプロトコルであるNTPを実装しています。それでも、espradio v0.3.0の公開APIを使って接続しただけでは、時刻は1970年のままです。

原因はespradioの`netlink`パッケージにあります。Wi-Fiに接続する`netlink.NetConnect`は、スタックの設定を作るときにNTPサーバーのアドレス（`StackConfig.NTPServer`）を設定しません。アドレスがゼロ値なので、スタックはNTPによる同期を一度も始めません。NTPを実行する`DoNTP`メソッドを呼ぶには内部のスタックへ届く必要がありますが、そこへ辿り着く`rstack()`は非公開の関数です。espradioの[サンプル](https://github.com/tinygo-org/espradio/tree/main/examples/http-no-allocs)で時刻が合うのは、`netlink`を使わずにスタックを直接作り、`DoNTP`を自分で呼んでいるからです。

実機で`netlink`を使って接続し、30秒待っても、時刻は1970年のままでした。

```
warning: clock never synchronised; timestamps will be wrong
clock ready: 1970-01-01 00:00:33.0411515 +0000 UTC
```

時刻を合わせる実装はライブラリの中にあっても、外から呼べないわけです。そこで、espradioには手を入れず、時刻を問い合わせるプロトコルを自分で実装することにしました。

## SNTPのパケット

NTPのうち、時刻を一度問い合わせて受け取るだけの部分を切り出したものが**SNTP**（Simple Network Time Protocol）で、[RFC 4330](https://www.rfc-editor.org/rfc/rfc4330)が定めています[^rfc5905]。NTPは複数のサーバーの応答を統計的に扱って誤差を抑えますが、テレメトリーに付ける時刻が秒の単位で合っていれば十分なデバイスには、SNTPで間に合います。

[^rfc5905]: RFC 4330は、NTPv4を定めた[RFC 5905](https://www.rfc-editor.org/rfc/rfc5905)によって廃止されています。パケットの形式は変わっておらず、本書の実装の検証規則はRFC 4330の記述に従っています。

SNTPの要求と応答はどちらも48バイトのUDPパケットで、サーバーの123番ポートとやりとりします。クライアントが要求に書き込むのは先頭の1バイトだけで、残りは0のままです。先頭の1バイトには、上位から2ビットのLI（閏秒の予告）、3ビットのバージョン番号、3ビットのモードが詰めてあります。クライアントの要求はLIが0、バージョンが4、モードが3（クライアント）なので、値は0x23になります。

```go
// ClientV4 is the first byte of a client request: LI=0, VN=4, Mode=3.
//
// It is built from its fields rather than written as a literal. The obvious
// literal 0x1B is version *3*; writing it and calling it v4 in a comment is
// exactly the mistake this constant prevents.
const ClientV4 = byte(0<<6 | 4<<3 | 3)
```

SNTPの実装例でよく見かける0x1Bは、バージョン3の要求です。どちらでも多くのサーバーは応答しますが、値をリテラルで書いてコメントにバージョン4と書くと、コメントと値が食い違っていても気づけません。本書の実装では値をフィールドから組み立て、バージョンが4であることをテストで確認しています。

応答のうちデバイスが使うのは、サーバーが応答を送り出した時刻（Transmit Timestamp）だけです。40バイト目からの4バイトが1900年1月1日からの秒数、44バイト目からの4バイトが1秒未満の端数（2の32乗分の1秒単位）で、どちらもビッグエンディアンです。往復にかかる時間の補正はしていません。そのぶん時計は往復時間の半分ほど遅れますが、10秒ごとに送るテレメトリーの時刻としては許容できると判断しました。

## 応答の検証

UDPのソケットに届いたパケットを検証せずに使うと、破損したパケットや無関係なパケットがそのまま時計を動かしてしまい、以後に送るすべてのテレメトリーの時刻がずれます。そこで`sntp.Parse`は、RFC 4330の5節が挙げるクライアントの検証規則に沿って、次の応答を捨てます。

| 条件 | 捨てる理由 |
| --- | --- |
| 48バイトに満たない | SNTPのヘッダーとして読めない |
| モードが4（サーバー）でも5（ブロードキャスト）でもない | サーバーからの応答ではない |
| バージョンが3でも4でもない | 時刻の形式が同じだと言えない |
| LIが3 | サーバーの時計が同期していない |
| stratumが0 | Kiss-o'-Deathで、時刻の代わりにエラーを伝えている |
| Transmit Timestampが0 | サーバーが時刻を持っていない |

stratumは、サーバーが基準の時計から何段離れているかを表す1バイトの値です。値が0の応答は**Kiss-o'-Death**と呼ばれ、サーバーがクライアントに問い合わせの頻度を下げるよう求めるときなどに使います。このとき応答の時刻のフィールドは意味を持たないので、時計を合わせる材料にはできません。LIは1と2なら閏秒の予告にすぎず時刻は有効ですが、3は、サーバー自身の時計がまだ同期していないことを表すので捨てます。

バージョン3を受け付けるのは、バージョン4の要求に対してバージョン3で答えるサーバーがあるからです。時刻の形式はどちらも同じなので、拒否すると使える時刻源を1つ失うだけになります。

```go
mode := p[offsetLIVNMode] & 0x7
if mode != modeServer && mode != modeBroadcast {
	return 0, 0, ErrNotServer
}
// Accept 3 and 4: a v3 server may answer a v4 request, and the timestamp
// format is identical.
if v := (p[offsetLIVNMode] >> 3) & 0x7; v != 3 && v != 4 {
	return 0, 0, ErrWrongVersion
}
if p[offsetLIVNMode]>>6 == 3 {
	return 0, 0, ErrUnsynchronized
}
// Stratum 0 is a kiss-of-death: the packet carries an error code in the
// reference identifier, not a usable time.
if p[offsetStratum] == 0 {
	return 0, 0, ErrKissOfDeath
}
```

検証の規則は、正しい応答をテストの中で1バイトずつ書き換えて、それぞれが拒否されることで確かめます。とくに、要求をそのまま送り返してくるパケット（モードが3のまま）を拒否するテストは、無関係なパケットで時計が動かないことを固定するためのものです。

## 2036年の桁あふれ

SNTPの秒数は32ビットの符号なし整数なので、1900年から数えて約136年で一周します。一周するのは2036年2月7日です。秒数をそのまま1900年起点として読むと、2036年2月7日以降の時刻は1900年に戻ってしまいます。

RFC 4330の3節は、この曖昧さを最上位ビットで解決する方法を示しています。最上位ビットが立っていれば1968年から2036年まで、立っていなければ2036年から2104年までの時刻として読む規則です。1968年以前の時刻を扱う必要はないので、2104年までは時刻が一意に決まります。

```go
// toUnix converts an era-aware NTP timestamp to Unix time.
func toUnix(secs, frac uint32) (int64, int64) {
	s := int64(secs) - epochOffset
	if secs&0x80000000 == 0 {
		// Era 1: 2036-02-07 onwards.
		s = int64(secs) + era1Offset - epochOffset
	}
	// The fraction is in units of 2^-32 seconds.
	return s, int64(frac) * 1e9 >> 32
}
```

`epochOffset`は1900年と1970年の差の2,208,988,800秒、`era1Offset`は32ビットの一周分の2の32乗秒です。テストでは2036年2月7日の桁あふれから1時間後の時刻を作り、1900年ではなく2036年として読めることを確かめています。本書のデバイスが2036年まで動き続けるとは考えにくいものの、パケットの解析をホストでテストできる形にしておけば、このような桁あふれの条件を実機なしで固定できます。

## 時計を合わせる

デバイス側では、DNSでNTPサーバーの名前を解決し、UDPで要求を送って応答を`sntp.Parse`に渡します。名前の解決にはespradioの公開APIである`GetHostByName`を使い、問い合わせ先には特定のサーバーに依存しないように[NTP Pool Project](https://www.ntppool.org/ja/)の`pool.ntp.org`を指定しました。タイムアウトは5秒、試行は3回までです。

TinyGoのマイコン向けのランタイムには、時刻を直接設定する関数がありません。かわりにあるのが、起動からの経過時間に足すオフセットを調整する`runtime.AdjustTimeOffset`なので、受け取った時刻といまの時計との差を計算して渡します。

```go
// applyClock moves the runtime clock to t.
//
// TinyGo has no settimeofday. runtime.AdjustTimeOffset shifts the monotonic
// clock's mapping to wall time by a delta, so the delta is computed against
// what the clock currently reads.
func applyClock(t time.Time) {
	runtime.AdjustTimeOffset(int64(t.Sub(time.Now())))
}
```

実機では、起動してWi-Fiにつながった直後に時刻が合います。

```
sntp: resolved pool.ntp.org to 167.179.119.205
sntp: clock set to 2026-09-15 06:33:52.876544886 +0000 UTC
```

3回とも失敗した場合、デバイスは警告を出したうえで、合っていない時計のまま送信を始めます。時刻を合わせられるまで待ち続ける作りにすると、デバイスが何も送らなくなり、原因の切り分けが難しくなるからです。明らかに誤った時刻のデータが届いていれば、少なくとも通信路は動いていて、問題は時刻の同期にあると分かります。

パケットの組み立てと解析は`sntp`パッケージに切り出し、デバイスに残したのはソケットの操作だけです。`cmd/device`はTinyGoのビルドタグでしかコンパイルされないので、そこにパケットの処理を置くと、ホストのテストが一切届かなくなります。
