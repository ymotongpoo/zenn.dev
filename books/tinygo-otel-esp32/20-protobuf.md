---
title: "protobufとreflect"
---

## 生成型を使う構成

OTLPのメッセージは[Protocol Buffers](https://protobuf.dev/)（以下protobuf）のスキーマで定義されていて、スキーマは[opentelemetry-proto](https://github.com/open-telemetry/opentelemetry-proto)リポジトリにあります。そこからGoの型を生成したものが [`go.opentelemetry.io/proto/otlp`](https://pkg.go.dev/go.opentelemetry.io/proto/otlp) です。SDKを使わなくても、この生成型でメッセージを組み立て、[protobuf-go](https://github.com/protocolbuffers/protobuf-go)の `proto.Marshal` でバイト列にすれば、OTLP/HTTPのリクエストの本文ができます。

この構成は、[TinyGo](https://tinygo.org/)でのクロスコンパイルが通ります。ホストで動かすテストも通り、ホストから同じコードでCollectorへ送れば、Collectorは正しくデコードします。検証に使ったのは `go.opentelemetry.io/proto/otlp` v1.11.0と `google.golang.org/protobuf` v1.36.11です。

## 実機でのpanic

ところが実機に書き込むと、Wi-Fiにつながった直後の最初の送信で止まります。

```
wifi connected, address: 192.168.0.102
warning: clock never synchronised; timestamps will be wrong
panic: unimplemented: (reflect.Type).MethodByName()
abort called
```

protobuf-goは、メッセージ型を初めてマーシャルするときに、その型の情報を `reflect` で調べて内部の表を作ります。この処理を行う `makeStructInfo`（`internal/impl/message.go`）が、古い生成コードとの互換のために、次の2つのメソッドを無条件に探します。

```go
	if m, ok := reflect.PtrTo(t).MethodByName("XXX_OneofFuncs"); ok {
		methods = append(methods, m)
	}
	if m, ok := reflect.PtrTo(t).MethodByName("XXX_OneofWrappers"); ok {
		methods = append(methods, m)
	}
```

TinyGoの `reflect` は `MethodByName` を宣言していますが、中身は次の1行だけです（TinyGo 0.42.0の `src/reflect/type.go`）。

```go
	panic("unimplemented: (reflect.Type).MethodByName()")
```

メソッドの宣言があるので、コンパイルもリンクも通ります。panicするのは実行して `MethodByName` に到達したときだけです。ホストのテストはGo本体の `reflect` の上で動くので、この経路を通っても問題は起きません。

この呼び出しは、メッセージがoneof（複数のフィールドのうち1つだけを持つprotobufの構文）を使うかどうかに関係なく実行されます。メモリの不足とも無関係です。**ビルドが通ることは動くことを意味しません。** TinyGoの `reflect` には、宣言だけがあって実行するとpanicするメソッドがあり、その欠落はリンクの時点では検出できず、実機で実際にその経路を通すまで分かりません。

## dynamicpbという経路

panicするのは、生成されたGoの構造体をマーシャルするときに型の情報を作る経路です。protobuf-goには、生成型を使わずにメッセージを扱う [`dynamicpb`](https://pkg.go.dev/google.golang.org/protobuf/types/dynamicpb) もあります。`dynamicpb` は、メッセージの構造を記述したdescriptorだけを手がかりに、フィールドを名前で引いて値を詰めるパッケージです。

同じバイナリの中で段階を分けて実機で試した結果が、次の出力です。

```
step 1: OTLPのdescriptorを生成型から取得        -> 成功
step 2: dynamicpb.NewMessage(desc)              -> 成功
step 3: ネストしたフィールドを設定              -> 成功
step 4: proto.Marshal(dynamicMessage)           -> 成功 18バイト
step 5: proto.Marshal(&mpb.MetricsData{})       -> panic
```

生成型からdescriptorを取り出すだけなら安全で、`dynamicpb` のメッセージは実機でもマーシャルできます。落ちるのは、生成型そのものを `proto.Marshal` に渡した最後の段階だけです。

それなら `dynamicpb` でOTLPのペイロードを組み立てればよいように見えます。そこで、8ストリームのメトリクスとリソース属性3件を持つペイロードを `dynamicpb` だけで組み立てるプログラムを書き、1回の組み立てで確保されるメモリを実機で測りました。組み立ての冒頭はこうです。

```go
	desc := (&mpb.MetricsData{}).ProtoReflect().Descriptor()
	m := dynamicpb.NewMessage(desc)

	rmF := desc.Fields().ByName("resource_metrics")
	rmL := m.Mutable(rmF).List()
	rm := rmL.NewElement().Message()
	// ...
	b, err := proto.Marshal(m)
```

結果は、1回の組み立てとマーシャルで29,277バイトの確保でした。本書の手書きエンコーダの確保は、同じ処理で0バイトです。`dynamicpb` は呼ぶたびにdescriptorをたどってメッセージの木を作り直すので、この確保は避けようがありません。10秒ごとに送り続けるデバイスで1回あたり約29KBを使い捨てれば、GCが頻繁に走ることになります。本書の実装が1回の送信で使い捨てるメモリは3,000バイトに満たない量です（抑え方は9章で扱います）。`dynamicpb` は動くものの、この用途では選べません。

## protobufのワイヤフォーマット

本書の実装は、protobufのランタイムを使わず、バイト列を直接書く `wire` パッケージを持っています。手で書けるのは、[protobufのワイヤフォーマット](https://protobuf.dev/programming-guides/encoding/)が単純だからです。

protobufのメッセージは、フィールドを1つずつ並べたバイト列です。各フィールドは、フィールド番号とワイヤタイプ（値の形式）を組み合わせたタグで始まり、その後に値が続きます。タグはフィールド番号を3ビット左にずらし、下位3ビットにワイヤタイプを入れた整数です。整数はvarintで書きます。varintは、1バイトの下位7ビットに値を入れ、続きがあれば最上位ビットを立てる可変長の符号化で、小さい値ほど短くなります。

OTLPのメトリクスで使うワイヤタイプは、3つに限られます。varint（列挙値や真偽値）、8バイト固定長のfixed64（タイムスタンプとdouble）、長さを前に置くlength-delimited（文字列と入れ子のメッセージ）です。`wire` パッケージのタグとvarintの書き込みは、次のとおりです。

```go
func (w *Buffer) tag(field, wireType int) {
	w.varint(uint64(field)<<3 | uint64(wireType))
}

func (w *Buffer) varint(v uint64) {
	for v >= 0x80 {
		w.b = append(w.b, byte(v)|0x80)
		v >>= 7
	}
	w.b = append(w.b, byte(v))
}
```

フィールド番号はopentelemetry-proto v1.11.0から写し、定数として名前を付けました。`reflect` も生成コードも使わないので、TinyGoの `reflect` の欠落には触れません。

## 入れ子の長さの予約

手で書くときにいちばん工夫が要るのは、入れ子のメッセージです。length-delimitedのフィールドは中身の長さを先頭に置きますが、中身を書き終えるまで長さは分かりません。長さを先に計算するには、メッセージの木を一度たどって大きさを求め、もう一度たどって書く必要があります。

`wire` の `Nested` は、二度たどる代わりに、長さを書く場所を先に空けておきます。中身を書き終えたら長さを計算し、それが空けた幅より短いvarintで済むなら、中身を前に詰めます。

```go
const maxLenPlaceholder = 5

// Nested writes a nested message field. The callback appends the contents.
func (w *Buffer) Nested(field int, fn func()) {
	w.tag(field, wireBytes)
	start := len(w.b)
	w.b = append(w.b, 0, 0, 0, 0, 0)
	fn()
	size := len(w.b) - start - maxLenPlaceholder

	n := varintLen(uint64(size))
	if n < maxLenPlaceholder {
		copy(w.b[start+n:], w.b[start+maxLenPlaceholder:])
		w.b = w.b[:len(w.b)-(maxLenPlaceholder-n)]
	}
	putVarint(w.b[start:start+n], uint64(size))
}
```

ペイロードは小さい（10ストリームで1,379バイト）ので、詰めるためのコピーは木をもう一度たどるより安く済む、という判断です。

予約する幅は、varintが取りうる長さの上限に合わせなければなりません。varintは1バイトに7ビットずつ入るので、3バイトで表せる長さは2,097,151までです。予約を3バイトにすると、中身が2,097,152バイトに達したときに長さのvarintが4バイトになり、予約した幅からあふれます。そのとき中身を詰める処理の前提が崩れ、失われるのは中身の末尾の1バイトです。エラーは返らないので、末尾の欠けたバイト列がそのまま送られてしまいます[^placeholder]。5バイトあれば、uint32で表せるすべての長さが収まり、コピーは常に詰める方向になります。

この境界を確かめるテストでは、中身を位置に依存するバイト列で埋めています。

```go
		// Position-dependent content. All-zero filler is invariant under an
		// off-by-one shift, so it would hide exactly the bug this checks.
		content := make([]byte, size)
		for i := range content {
			content[i] = byte(i%251 + 1)
		}
```

中身をすべて0で埋めると、1バイトずれても同じ内容に見えるので、ずれによる破損を検出できません。テストは、varintの長さが1バイトから2バイト、2バイトから3バイト、3バイトから4バイトへ変わる前後の大きさを並べて、宣言された長さと中身の両方を1バイトずつ比べています。

## 空文字列とoneof

protobufのproto3では、値がゼロ値のフィールドは送らないのが原則です。受け取る側は、届かなかったフィールドをゼロ値として読みます。`wire` の書き込み関数も、空文字列や0を受け取ったら何も書きません。

この原則には例外があります。OTLPの属性値 `AnyValue` はoneofで、文字列、整数、doubleなどのどれか1つを持ちます。oneofでは、届いたフィールドがどれかによって値の種類が決まる仕組みです。空文字列の属性値を省くと、受け取る側には「値の種類が決まっていない属性」として届き、「値が空文字列の属性」とは区別できなくなります。そのため `wire` には、空文字列でも必ず書く `StringAlways` を用意し、属性値の書き込みに使っています。

```go
func (r *Registry) encodeAttr(a *Attr, field int) {
	w := r.buf
	w.Nested(field, func() {
		w.String(wire.FieldKeyValueKey, a.Key)
		w.Nested(wire.FieldKeyValueValue, func() {
			// AnyValue is a oneof: an empty string still has to be written,
			// or the value reads as unset instead of empty.
			w.StringAlways(wire.FieldAnyValueStringValue, a.Value)
		})
	})
}
```

データポイントの値を書く `Double` も同じ理由で0を省きません。0という測定値には意味があり、OTLPではこの値もoneofの中にあるからです。

## 公式実装との往復

手書きのエンコーダが正しいかどうかは、デバイスの上では確かめられません。デバイスではprotobuf-goが動かないからです。そこで、ホストで動くテストの中で、手書きのバイト列を公式の `proto.Unmarshal` で生成型に読み込み、フィールドの値を期待値と比べます。

```go
func decode(t *testing.T, b []byte) *mpb.MetricsData {
	t.Helper()
	var md mpb.MetricsData
	if err := proto.Unmarshal(b, &md); err != nil {
		t.Fatalf("reference protobuf runtime rejected our bytes: %v", err)
	}
	return &md
}
```

デバイスでは動かない生成型が、ホストでは手書きエンコーダの検証に使えます。テストは、リソース属性、メトリクスの名前と単位、集計の種類、値、タイムスタンプを1つずつ確かめるほか、2MBを超えるペイロードでも公式実装が読めることを確認しています。

生成型の `proto.Marshal` は、ビルドもホストのテストも通ったうえで、実機でだけ落ちました。どの部品が動くかを決めるのはビルドの成否ではなく、実機でその経路を通したときの結果です。次の章では、protobufのバイナリ形式とは別の、もう1つのOTLPのエンコーディングを見ていきます。

[^placeholder]: 長さのvarintが予約より1バイト長いと、中身を動かす `copy` は、コピー先がコピー元より1バイト短くなります。`copy` は短いほうに合わせるので、中身の最後の1バイトがコピーされません。そのあとのスライスの切り直しは、長さを超えて予備の容量の領域まで伸び、そこにある無関係なバイトが中身の末尾として扱われます。
