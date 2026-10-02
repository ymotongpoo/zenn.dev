---
title: "OTLP/JSONで話す"
---

## JSONというエンコーディング

前の章で扱ったのは、OTLPのメッセージをprotobufのバイナリ形式で書く手書きのエンコーダでした。OTLPには、もう1つの書き方が用意されています。[OTLPの仕様](https://opentelemetry.io/docs/specs/otlp/)は、OTLP/HTTPの本文のエンコーディングとして、バイナリのprotobufとJSONの2つを定めています。どちらも同じprotobufのスキーマに従い、違いはバイト列への書き方だけです。リクエストの `Content-Type` が `application/x-protobuf` ならバイナリ、`application/json` ならJSONです。

[OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/)のOTLPレシーバーは、どちらのエンコーディングも受け付けます。つまりJSONで送ることは、protobufが使えないときの回避策ではなく、仕様が定めるOTLPそのものです。

そして、JSONを書くための部品はGoの標準ライブラリにあります。[TinyGo](https://tinygo.org/)の `encoding/json` は実機で動くので、エンコーダを自分で書かなくても、構造体にタグを付けるだけでOTLPを話せます。

## 仕様が定めるJSONの書き方

OTLPのJSONは、protobufの標準の[JSONマッピング](https://protobuf.dev/programming-guides/json/)に従います。JSONマッピングは、protobufのメッセージとJSONを相互に変換する規則で、protobuf-goでの実装は `protojson` パッケージです。OTLPの仕様は、この規則にいくつかの変更を加えました。デバイスから送る側として気をつける必要があるのは、次の4点です。

| 項目 | OTLP/JSONでの書き方 | 標準のJSONマッピングとの関係 |
| --- | --- | --- |
| オブジェクトのキー | lowerCamelCaseのフィールド名（`timeUnixNano`） | 標準では元のフィールド名（`time_unix_nano`）も読めるが、OTLPでは使えない |
| 64ビット整数 | 10進の文字列 | 標準の規則のまま |
| `traceId` と `spanId` | 16進の文字列 | 標準ではbase64 |
| 列挙値 | 整数 | 標準では名前の文字列も使える |

64ビット整数の扱いは、OTLPが独自に決めたものではなく、protobufの標準の規則に従っています。仕様は、`timeUnixNano` や `startTimeUnixNano` のようなタイムスタンプも `fixed64` なので文字列で書く、と注記しています。JSONの数値をfloat64として扱う実装では、ナノ秒単位のUNIX時刻（19桁）を正確に保てないからです。受け取る側には数値と文字列の両方を受け付けることが求められていますが、送る側は文字列で書いておけば、受け取る実装の数値の扱いに左右されません。

残りの3点は、OTLPが標準の規則から外れている箇所です。トレースIDとスパンIDは、標準ならbase64で書くバイト列ですが、OTLPでは16進の文字列です。列挙値は整数に限られ、`SPAN_KIND_SERVER` のような名前の文字列は使えません。このほか仕様は、受け取る側が知らないフィールドを無視することも求めています。

## 構造体のタグで書くメッセージ

本書の `otlpjson` パッケージは、OTLPのメッセージの形をそのままGoの構造体で書き、JSONのキーをタグで指定しています。メトリクスのデータポイントは次のとおりです。

```go
type numberDataPoint struct {
	// Timestamps are strings: they are uint64 nanoseconds, and a JSON number
	// is a float64, which cannot represent them exactly.
	StartTimeUnixNano string     `json:"startTimeUnixNano,omitempty"`
	TimeUnixNano      string     `json:"timeUnixNano"`
	AsDouble          float64    `json:"asDouble"`
	Attributes        []keyValue `json:"attributes,omitempty"`
}
```

タイムスタンプは `uint64` ではなく `string` で持ち、送る直前に `strconv.FormatUint` で10進の文字列にします。キーはlowerCamelCaseで、`AsDouble` には `omitempty` を付けていません。前の章で見たとおり、データポイントの値はoneofで、0という値も省かずに送る必要があるからです。

累積のカウンターを表す `sum` は、集計の種類を列挙値で持ちます。

```go
// aggregationTemporalityCumulative is AGGREGATION_TEMPORALITY_CUMULATIVE.
const aggregationTemporalityCumulative = 2

type sum struct {
	DataPoints             []numberDataPoint `json:"dataPoints"`
	AggregationTemporality int               `json:"aggregationTemporality"`
	IsMonotonic            bool              `json:"isMonotonic"`
}
```

`AggregationTemporality` は `int` で、`AGGREGATION_TEMPORALITY_CUMULATIVE` という名前ではなく、その値の2を書きます。トレースのスパンでは、IDを16進の文字列で持ちます。

```go
type span struct {
	// OTLP/JSON writes trace and span IDs as hex strings, not base64: this is
	// one of the places where the OTLP JSON mapping departs from protobuf's
	// canonical JSON.
	TraceID           string     `json:"traceId"`
	SpanID            string     `json:"spanId"`
	ParentSpanID      string     `json:"parentSpanId,omitempty"`
	Name              string     `json:"name"`
	Kind              int        `json:"kind"`
	// ...
}
```

16バイトのトレースIDと8バイトのスパンIDは、`encoding/hex` の `hex.EncodeToString` で文字列にします。Goの `encoding/json` は `[]byte` をbase64で書くので、IDをバイト列のまま構造体に入れると、仕様と違う形で送られてしまいます。

メトリクス、ログ、トレースのどれも、作るのはこうした構造体と、値を詰める処理だけです。バイト列の書き方は `encoding/json` に任せています。

## protojsonで確かめる

手書きのprotobufと同じく、JSONの正しさもホストのテストで確かめます。基準にするのは、protobufのJSONマッピングを実装した `protojson` です。テストでは、エンコーダが出力したJSONを `protojson.Unmarshal` で生成型に読み込みます。

```go
func decode(t *testing.T, b []byte) *mpb.MetricsData {
	t.Helper()
	var md mpb.MetricsData
	// DiscardUnknown stays false: an unknown or misspelled field must fail
	// here rather than be silently dropped by the collector.
	if err := protojson.Unmarshal(b, &md); err != nil {
		t.Fatalf("protojson rejected our payload: %v\npayload: %s", err, b)
	}
	return &md
}
```

`protojson.Unmarshal` は、デフォルトでは知らないフィールドをエラーにします。一方でOTLPの仕様が受け取る側に求めているのは知らないフィールドの無視なので、キーの綴りを間違えても、Collectorはエラーを返さず、そのフィールドを捨てるだけです。テストで知らないフィールドを拒否させておけば、`timeUnixNano` を `timeUnixNanos` と書くような誤りを、Collectorに届く前に見つけられます。タイムスタンプが数値ではなく文字列で出ていることも、別のテストで固定しました。

トレースのIDだけは、`protojson` を基準にできません。`protojson` は標準のマッピングに従ってIDをbase64として読むからです。16進の文字列はbase64の文字の範囲に収まるので、エラーにはならず、違うバイト列として読まれてしまいます。そこでトレースのテストでは、IDをbase64に書き換えてから `protojson` に渡して構造を確かめ、IDが16進で出ていることは別のテストの役目です。Collectorが16進のIDを正しく読むことは、実際のCollectorと、トレースのバックエンドである[Grafana Tempo](https://grafana.com/oss/tempo/)に送って確認しました。

## ペイロードの大きさ

JSONの代償は、ペイロードが大きくなることです。キーを毎回文字列で書き、数値も10進の文字列になるので、同じ内容でもバイナリのprotobufより長くなります。10ストリームのメトリクスを送ったときのペイロードを、実機のシリアル出力で比べました。

| エンコーディング | バイト数 |
| --- | --- |
| バイナリprotobuf | 1,379 |
| JSON | 3,016（2.19倍） |

本書のデモがメトリクスを送るのは10秒ごとです。JSONでも1秒あたり約300バイトで、同じLANにあるCollectorへ送る分には、この差は問題になりません。電池で動かす機器や、LPWAN（低消費電力の広域無線）のように帯域の狭い回線で送る機器なら、protobufを選ぶ理由があります。

バイナリの大きさは、エンコーダの選び方ではほとんど変わりません。手書きのHTTPクライアントと組み合わせたとき、flashの差は216バイトで、全体の0.1%に届きません[^size]。

## JSONをデフォルトにした理由

本書のデモは、エンコーダとして `encoding/json` をデフォルトにしています。ビルドタグで手書きのprotobufに切り替えることもできますが、デフォルトにしたのは、自分で書くコードがいちばん少ない組み合わせだからです[^tags]。

手書きのprotobufでは、フィールド番号を写し、ワイヤフォーマットを書き、入れ子の長さやoneofの扱いを自分で正しく実装する必要がありました。JSONでは、OTLPのメッセージの形を構造体で写せば、あとは標準ライブラリが書きます。ログとトレースは、メトリクスのエンコーディングにかかわらず常にJSONです。OTLP/HTTPはリクエストごとに `Content-Type` を選べるので、シグナルごとに手書きのエンコーダを増やす理由がありません。

ペイロードが2倍あまりになることを除けば、JSONを選んで失うものはこの用途ではありません。帯域の限られた環境でprotobufが必要になったときのために、手書きのエンコーダも同じインターフェースで残してあります。

## encoding/jsonとスタック

`encoding/json` には、1つだけ条件があります。`encoding/json` は入れ子のメッセージを再帰的にたどって書くので、goroutineのスタックを多く使います。OTLPのメトリクスは、`resourceMetrics` の中に `scopeMetrics`、その中に `metrics`、さらに `gauge` や `sum` を経て `dataPoints` と、何段にも入れ子になったメッセージです。

ESP32-S3のターゲットのデフォルトのスタックは8KBで、このままでは実機で落ちます。本書のデモは、ビルド時にスタックを16KBに広げています。単発の小さな構造体を `json.Marshal` に渡すだけでは再現せず、OTLPのメッセージを丸ごと渡したときにだけ落ちるという点で、前の章の `MethodByName` と同じく実機で本物のペイロードを通すまで分からない問題でした。スタックの大きさと落ち方の関係は、9章で測った結果を示します。

[^size]: バイナリの大きさは、Wi-Fi接続、時刻の同期、OTLPの送信を含むデバイスのプログラム全体を、スタック16KBでビルドして測りました。メトリクスを手書きのprotobufで送る組み合わせで748,907バイト、`encoding/json` で送る組み合わせで748,691バイトです。ログとトレースはどちらの場合も `encoding/json` で送るので、差はメトリクスのエンコーダの分だけです。
[^tags]: エンコーダとHTTPクライアントは、ビルドタグでそれぞれ独立に選べます。デフォルトは `socket otlpjson` で、`encoding/json` と手書きのHTTPクライアントの組み合わせです。HTTPクライアントは7章で扱います。
