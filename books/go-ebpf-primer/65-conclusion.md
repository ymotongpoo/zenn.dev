---
title: "Go本体の動向とおわりに"
---

ここまで見た4つの難所は、いずれもGoの外部から内部を覗き込むことの困難でした。

## eBPF計装への直接支援

結論として、eBPF計装を直接助ける機能はGo本体にほぼ入っていません。難所1のuretprobe問題（[#22008](https://github.com/golang/go/issues/22008)）は2017年から提起されていますが、長く「Unplanned」のまま棚上げされています。goroutineの起動にフックを差せるようにする提案（[#73798](https://github.com/golang/go/issues/73798)）は、2025年に「not planned」でクローズされました。

Goチームの姿勢は一貫しています。**ランタイムの内部構造は公開APIではなく、外部から依存すべきでない**というものです。eBPF計装はまさにその非公開な内部に依存しているため、支援は得にくい状況です。難所3で見たオフセット追従のコストは、この設計思想の裏返しでもあります。追従の相手はランタイム自身にも及びます。`offsets.json` には `runtime.hchan` や `runtime.moduledata` のようなランタイムの構造体も載っていて、動いた記録の半分近くを占めています。本書で見た `net/http` やgRPCのフィールドは標準ライブラリとサードパーティのものでしたが、内部構造を安定したAPIにしないという方針は、ランタイムにもライブラリにも共通しています。

`goid` を公開しないという判断も、この考え方に基づいています。難所2でOBIが `g` のアドレスを識別子に選んだのは、公開されない値を無理に読むより、読まずに済ませるほうが壊れにくいという判断でした。外部ツール側が「読まない設計」に寄せることで折り合いをつけている、と言ってもいいでしょう。

## 「内からの」オブザーバビリティの進化

ただし、Goがオブザーバビリティに無関心なわけではありません。むしろ「内からの」オブザーバビリティは着実に進化しています。

- **Flight recording**（[#63185](https://github.com/golang/go/issues/63185)、Go 1.25で `runtime/trace.FlightRecorder` として実装）：直近の実行トレースをリングバッファに保持し、問題が起きた瞬間にその手前を取り出せる。飛行機のフライトレコーダーと同じ発想である。

![flight recordingの仕組み](/images/20260911-flight-recording.png)
*図1: 矢印は記録と取り出しの流れを表す。ランタイムは直近ぶんだけをリングバッファに残しながら記録し続け、古い記録は上書きされる。問題が起きた瞬間の合図で、その時点の「直前」の記録だけが書き出される。*

- **goroutine leak profile**：Go 1.26の `runtime/pprof` に `goroutineleak` という名前で入った、到達不能になってブロックし続けるgoroutineのプロファイル。ビルド時に `GOEXPERIMENT=goroutineleakprofile` を指定して使う実験的機能。外からeBPFで覗いても、あるgoroutineがリークしているのか、単に待っているだけなのかは区別できない。到達可能性の判定はヒープとスタックの全体を知っているランタイムの内側にしかできない仕事で、「内からだからこそ出せる答え」の実例である。
- **Compile-Time Instrumentation SIG**（2025年1月発足）：eBPFとは別のやり方として、コンパイル時に計装コードを埋め込む取り組み。ツール名は `otelc`。ソースコードの変更は要らない。仕組みと、実際にコンパイラへ渡る中身がどう変わるのかは、次の節で詳しく見る。

### Compile-Time Instrumentation SIG

[Compile-Time Instrumentation SIG](https://github.com/open-telemetry/opentelemetry-go-compile-instrumentation)は2025年1月に発足し、2026年7月14日に最初の安定版v1.0.0に到達しました。もっとも、このv1.0.0は公開から間もなくretractされています。`otelc pin` というコマンドがユーザーの `go.mod` に誤ったモジュールパスを書き込むバグがあり、同日中に修正版のv1.0.1が公開されました。実際、リポジトリの `go.mod` には次の一行が残っています。

```
retract v1.0.0 // otelc pin generates incorrect module paths in user go.mod files; use v1.0.1
```

直近の最新版は2026年8月24日公開のv1.1.0です（[リリース一覧](https://github.com/open-telemetry/opentelemetry-go-compile-instrumentation/releases)）。

使い方はシンプルです。

```console
$ otelc go build -o myapp .
```

`go build` の前に `otelc` を付けるだけで、ソースコードは1行も変更しません。ただし「`-toolexec` を使う」というのは比喩ではありません。`otelc go build` は内部で実際に `go build` を次のように組み立てて実行しています（`tool/internal/setup/setup.go` の `buildWithToolexec` 関数、[GitHub上のソース](https://github.com/open-telemetry/opentelemetry-go-compile-instrumentation/blob/v1.1.0/tool/internal/setup/setup.go#L536-L596)）。

```console
$ go build -work -toolexec="<otelcの実行パス> toolexec" -o myapp .
```

`-toolexec` はGoツールチェーンが公式に提供する、「コンパイラの前段に自分のプログラムを挟む」仕組みです。otelcはこれを使って、コンパイル対象が `net/http` やgRPC、`database/sql` といった対応ライブラリであれば、その中の対象の関数の本体に計装コードを差し込んでからコンパイラに渡します。書き換わるのは呼び出し側ではなくライブラリ側です。

![otelcのビルド時割り込み](/images/20260911-otelc-toolexec.png)
*図2: 矢印はビルドの処理順序を表す。ふつうのビルドではソースコードがそのままバイナリになるのに対し、otelc経由のビルドでは `go build` の前段に `-toolexec` でotelc自身が割り込み、対応ライブラリの関数の本体に計装コードを差し込んでからコンパイルする。*

#### 実際に何が書き換わるのか

「ソースコードは変わらない」と言いましたが、コンパイラに渡る中身は変わります。実際に `otelc go build` を動かして確認してみます。

まず、アプリ側のコードです。これはビルドの前後で1文字も変わりません。

```go
resp, err := http.Get("http://localhost:8080/greet?name=world")
```

`http.Get` が最終的に呼ぶ `net/http` 自身の `RoundTrip` の、ビルド前の姿はGo標準ライブラリのソースそのままです。

```go
// net/http/roundtrip.go（otelcビルド前。Go標準ライブラリそのまま）
func (t *Transport) RoundTrip(req *Request) (*Response, error) {
	if t == nil {
		panic("transport is nil")
	}
	return t.roundTrip(req)
}
```

`otelc go build` は前述のとおり内部で `-work` フラグを付けているため、ビルドが終わったあともGoのビルドキャッシュに書き換え後のソースが残ります。そこを覗くと、次のようになっていました。

```go
// net/http/roundtrip.go（otelcが実際に書き換えた後の姿。実機で確認）
func (t *Transport) RoundTrip(req *Request) (_r0 *Response, _r1 error) {
	if hookContext3038199408, _ := OtelBeforeTrampoline_RoundTrip3038199408(&t, &req); false {
	} else {
		defer OtelAfterTrampoline_RoundTrip3038199408(hookContext3038199408, &_r0, &_r1)
	}
	if t == nil {
		panic("transport is nil")
	}
	return t.roundTrip(req)
}

// Trampoline Template
func OtelBeforeTrampoline_RoundTrip3038199408(recv0 **Transport, param0 **Request) (hookContext *HookContextImpl3038199408, skipCall bool) {
	defer func() {
		if err := recover(); err != nil {
			println("failed to exec Before hook", "BeforeRoundTrip")
		}
	}()
	hookContext = &HookContextImpl3038199408{}
	hookContext.params = []interface{}{recv0, param0}
	hookContext.funcName = "RoundTrip"
	hookContext.packageName = "http"
	if BeforeRoundTrip != nil {
		BeforeRoundTrip(hookContext, *recv0, *param0)
	}
	return hookContext, hookContext.skipCall
}

func OtelAfterTrampoline_RoundTrip3038199408(hookContext HookContext, arg0 **Response, arg1 *error) {
	defer func() {
		if err := recover(); err != nil {
			println("failed to exec After hook", "AfterRoundTrip")
		}
	}()
	hookContext.(*HookContextImpl3038199408).returnVals = []interface{}{arg0, arg1}
	if AfterRoundTrip != nil {
		AfterRoundTrip(hookContext, *arg0, *arg1)
	}
}

//go:linkname BeforeRoundTrip go.opentelemetry.io/otelc/instrumentation/net/http/client.BeforeRoundTrip
func BeforeRoundTrip(hookContext HookContext, recv0 *Transport, param0 *Request)

//go:linkname AfterRoundTrip go.opentelemetry.io/otelc/instrumentation/net/http/client.AfterRoundTrip
func AfterRoundTrip(hookContext HookContext, arg0 *Response, arg1 error)
```

（`HookContextImpl3038199408` の `GetParam`/`SetParam` など、値の出し入れをするだけの機械的なgetter/setterは省略しました。関数名の末尾に付く `3038199408` という数字は、複数のフックが衝突しないようコード生成時に振られる一意なハッシュです。）

やっていることは3つです。関数の先頭でbeforeフックを呼び、`defer` でafterフックを仕込み、`recover` でフック自体の失敗を握りつぶして本来の処理には影響させない。`RoundTrip` の本体——`t == nil` のチェックとreturn文——は一切変わっていません。

`BeforeRoundTrip` と `AfterRoundTrip` は `//go:linkname` で名前だけが宣言されていて、実体は別のパッケージにあります。それが実際にOpenTelemetryのスパンを作っている場所です。

```go
// instrumentation/net/http/client/client_hook.go（実際のフック実装。抜粋）
func BeforeRoundTrip(ictx hook.HookContext, transport *http.Transport, req *http.Request) {
	ctx := req.Context()
	attrs := semconv.HTTPClientRequestTraceAttrs(req)

	ctx, span := tracer.Start(ctx,
		req.Method,
		trace.WithSpanKind(trace.SpanKindClient),
		trace.WithAttributes(attrs...),
	)

	// トレースコンテキストをリクエストヘッダに注入する
	propagator.Inject(ctx, propagation.HeaderCarrier(req.Header))

	newReq := req.WithContext(ctx)
	ictx.SetParam(requestParamIndex, newReq)

	ictx.SetData(map[string]interface{}{
		"ctx": ctx, "span": span, "req": req, "start": time.Now(),
	})
}

func AfterRoundTrip(ictx hook.HookContext, res *http.Response, err error) {
	span, ok := ictx.GetKeyData("span").(trace.Span)
	if !ok || span == nil {
		return
	}
	defer span.End()

	if res != nil {
		attrs := semconv.HTTPClientResponseTraceAttrs(res)
		span.SetAttributes(attrs...)
		if code, desc := semconv.HTTPClientStatus(res.StatusCode); code != codes.Unset {
			span.SetStatus(code, desc)
		}
	}
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
	}
}
```

（OTelエクスポータ自身のリクエストを無限ループさせないためのUser-Agentフィルタなど、本筋と関係の薄い防御的なコードは省略しました。）

これで一巡します。`BeforeRoundTrip` がスパンを開始してヘッダにtraceparentを注入し、`ictx.SetParam` でリクエストを差し替える——これは `hookContext` の `GetParam`/`SetParam` が `RoundTrip` の引数そのもの（`**Request`）を指しているからこそ可能です。`AfterRoundTrip` がレスポンスの内容でスパンを完成させて閉じます。難所2で見た「引数はレジスタにあってスタックには無い」という話と違い、こちらはコンパイラ自身が計装コードを書いているので、レジスタかスタックかを気にする必要すらありません。難所1〜4がeBPFという「外から」の制約から生まれていたのに対し、コンパイル時計装が難所を作らずに済むのは、まさにこの位置にいるからです。

#### 手元で確かめる

ここまでの内容は、次の手順で実機で確認できます（`go1.26.5 linux/amd64` で確認済み）。

```console
$ git clone https://github.com/open-telemetry/opentelemetry-go-compile-instrumentation.git
$ cd opentelemetry-go-compile-instrumentation
$ make build
$ cd demo/app/http/client   # net/httpを使う適当なコードでもよい
$ ../../../../otelc go build -o client .
# 出力される WORK=/tmp/go-buildXXXXXXXXX を控えて、
# その下の net/http パッケージのビルドディレクトリを探すと
# 書き換え後の roundtrip.go が残っている
```

要するに、eBPFは「外から」観測し、Goは「内から」の観測手段を増やしています。外からの観測は、アプリを変更せずに済む反面、ランタイムの内部構造を追いかけ続ける必要があります。内からの観測は、正確で壊れにくい反面、コードやビルドへの関与を必要とします。

![外からの観測と内からの観測](/images/20260911-outside-inside.png)
*図3: 矢印は観測する側から観測される側へ向かう。ラベルはそれぞれのやり方の利点とコストを示す。*

## おわりに

4つの難所を、問題になるGoの性質とOBIの対処で並べます。

| 難所 | 問題になるGoの性質 | OBIの対処 |
|---|---|---|
| 1. uretprobeが使えない | 可動スタック | 全 `RET` 命令への通常uprobe |
| 2. レジスタABI | ABIInternal（引数の受け渡し規約、Go 1.17〜） | アーキテクチャ別のレジスタ対応表。goroutineは `g` のアドレスで識別し、中身は読まない |
| 3. バージョン依存オフセット | 非公開なライブラリとランタイムの内部構造 | バイナリのDWARFを読み、欠けた分だけ自動更新される `offsets.json` で補う |
| 4. コンテキスト伝搬 | goroutine（≠スレッド） | `newproc1` での親子追跡（6段まで）と、`bufio.Writer` への直接書き込みまたは `sk_msg` |

これら4つはばらばらに生じた問題ではなく、すべて「Goらしさ」の裏返しです。動くスタック、独自のレジスタABI、非公開な内部構造、そしてgoroutineです。Goを高速で書きやすくしている設計が、そのまま外部から覗く側の障害になっています。

この知識は、自分でeBPFツールを書く人だけのものではありません。Goでアプリを書く立場でも、これらの難所を知っておくと、なぜ自分のアプリはゼロコード計装でトレースが取れたり取れなかったりするのか、どのGoバージョンやビルド形態を選べば計装が安定するのかを、自分で説明できるようになります。DWARFを落とすかどうかがオフセット解決の経路を変える、という話がその一例でした。

1章の「言語を問わず動く」という宣伝文句に戻りましょう。プロトコルを解釈する汎用の経路にかぎれば、その一文は誇張ではありません。しかしGoの関数まで踏み込んだ経路の裏では、全 `RET` 命令の走査、レジスタの直読み、DWARFとオフセット表の二段構え、そして `bufio.Writer` のバッファへの書き込みが動いています。それでも「コードを変えずに観測できる」体験が成り立っているのは、難所の一つひとつに対処し続ける実装があるからです。

外からの観測と内からの観測の分担がどこに落ち着くのかは、まだ動いている最中です。
