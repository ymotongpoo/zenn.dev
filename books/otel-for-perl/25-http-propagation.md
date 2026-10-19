---
title: "HTTP呼び出しでサービスをまたぐ"
---

## HTTP::Tinyの計装

5章の木には、まだ説明していないスパンが2つありました。`report` の `GET` と、`rates` の `GET /rates` です。`report` の `GET` は、`app_otel.psgi` に足した次の1行が作っています。

```perl
use OpenTelemetry::Instrumentation 'HTTP::Tiny';
```

[OpenTelemetry::Instrumentation](https://metacpan.org/pod/OpenTelemetry::Instrumentation)は、CPANのモジュールごとの計装をまとめて読み込むモジュールです。モジュール名を渡すと、そのモジュールを読み込んだうえで対応する計装を有効にします。APIの配布物に入っている計装は、`HTTP::Tiny`、`LWP::UserAgent`、`DBI`向けです。`-all` を渡すと、インストール済みの計装をすべて有効にします。ただし対象は、`use` の時点ですでに読み込まれているモジュールだけです。`use OpenTelemetry::Instrumentation -all;` を `use HTTP::Tiny;` より前に書くと、`HTTP::Tiny` は計装されません。モジュール名を明示しておけば、`use` の順序を気にせずに済みます[^legacy]。

`HTTP::Tiny` の計装は、`HTTP::Tiny::request` メソッドの周りに処理を差し込みます。差し込んだ処理は、リクエストのたびに種類がCLIENTのスパンを作り、現在のコンテキストに入れます。続いてリクエストのヘッダーに `traceparent` を書き込み、元のメソッドを呼ぶ流れです。`app_otel.psgi` では計装を有効にする `use` が `use Demo::Report` より前にあるので、`Demo::Report` は計装の後で `HTTP::Tiny` のオブジェクトを作ります。差し込みはメソッドそのものに対して行われるため、計装の前に作ったオブジェクトからの呼び出しでも計装されます。

[^legacy]: 0.026より前は、計装は `OpenTelemetry::Integration` の名前空間にありました。いまのバージョンでも古い名前空間を探しますが、新しいコードでは `OpenTelemetry::Instrumentation` を使います。SDKのPODのSYNOPSISには、0.028まで古い `OpenTelemetry::Integration` の書き方が残っていました。0.100では直っています（[SDKのissue #23](https://github.com/jjatria/perl-opentelemetry-sdk/issues/23)）。

クライアントのスパンには、次の属性が付いていました。

| 属性 | 値の例 | 受信時の型 |
| --- | --- | --- |
| `http.request.method` | `GET` | 文字列 |
| `http.response.status_code` | `200` | 文字列（規約では整数） |
| `url.full` | `http://backend:8080/rates?currency=USD` | 文字列 |
| `server.address` | `backend` | 文字列 |
| `server.port` | `8080` | 文字列（規約では整数） |
| `network.protocol.version` | `1.1` | 文字列 |
| `user_agent.original` | `HTTP-Tiny/0.096` | 文字列 |

スパン名の `GET` は、セマンティック規約どおりの名前です。規約は、クライアントのスパンでURLの型を表す `url.template` が無ければ、スパン名を `{method}` にすると定めています。`server.address` と `server.port` が分かれて入っている点も、5章のサーバーのスパンとの違いです。ただし数値の `server.port` も、5章で見たとおり文字列で届いていました。

## Goのサービスで受け取る

`rates` はGoの公式SDKと、`net/http` のハンドラーを計装する[otelhttp](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp)で書きました。トレースに関係する部分を抜き出します。

```go:main.go（抜粋）
func main() {
	// SIGTERMとCtrl-Cで終了処理に入る
	sigCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	ctx := context.Background()
	exp, err := otlptracehttp.New(ctx) // OTEL_EXPORTER_OTLP_ENDPOINTを読む
	if err != nil {
		log.Fatal(err)
	}
	res, err := resource.New(ctx, resource.WithFromEnv(), resource.WithTelemetrySDK())
	if err != nil {
		log.Fatal(err)
	}
	tp := sdktrace.NewTracerProvider(sdktrace.WithBatcher(exp), sdktrace.WithResource(res))
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.TraceContext{})

	mux := http.NewServeMux()
	mux.HandleFunc("GET /rates", rates)
	srv := &http.Server{Addr: ":8080", Handler: otelhttp.NewHandler(mux, "rates")}
	go func() {
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatal(err)
		}
	}()

	<-sigCtx.Done()

	// 取り消し済みのsigCtxではなく、上限付きの新しいコンテキストで後片付けする
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil { // 処理中のリクエストを待つ
		log.Print(err)
	}
	if err := tp.Shutdown(shutdownCtx); err != nil { // キューに残ったスパンを送る
		log.Print(err)
	}
}
```

`otelhttp.NewHandler` は、リクエストのヘッダーから取り出したトレースコンテキストを親にして、サーバーのスパンを作ります。ヘッダーを読む形式を決めるのが `SetTextMapPropagator` です。Goのグローバルなプロパゲーターは、設定しなければ何もしない実装のままです。そのため、W3C Trace Contextを読む `propagation.TraceContext` を明示しています。

後半はGo側の終了処理です。GoのSDKもBatchプロセッサーでスパンを送るので、止める前に `tp.Shutdown` でキューを送り出します。最初は `log.Fatal(http.ListenAndServe(...))` と書いていましたが、この形では `log.Fatal` が `os.Exit` を呼び、`defer` に書いた `tp.Shutdown` が実行されません。リクエストの直後にサービスを止めると、`rates` のスパンが届きませんでした。上の形に直すと、同じ操作でも届きました[^go-shutdown]。

[^go-shutdown]: どちらも、リクエストを1回送った直後に `docker compose stop` で止めました。修正前は `rates` のスパンが0件、修正後は2回とも1件届きました。

PerlのSDKは、`OTEL_PROPAGATORS` のデフォルト値に従ってW3C Trace ContextとBaggageのプロパゲーターを組みます。PerlのSDKが書いた `traceparent` を、GoのSDKが読む関係です。2つのSDKは別々の人が別々の言語で書いたものですが、間にあるのはW3Cが定めたヘッダーの形式だけです。

## 3種類のリクエストの比較

Collectorに届いた `rates` のスパンの親は、すべてPerlのクライアントのスパンでした。2章の3種類のリクエストのトレースから、スパンごとの所要時間を並べます。

| リクエスト | サーバー（Perl） | aggregate | HTTPクライアント | `GET /rates`（Go） |
| --- | --- | --- | --- | --- |
| `days=7&currency=USD` | 47.3ms | 21.3ms | 21.1ms | 20.3ms |
| `days=180&currency=USD` | 574.8ms | 540.4ms | 22.8ms | 20.5ms |
| `days=7&currency=BRL` | 632.5ms | 21.3ms | 602.0ms | 600.5ms |

`currency=BRL` のリクエストでは、Perlのクライアントのスパンが602.0msで、その子であるGoのスパンが600.5msです。待ち時間のほとんどは、Goのサービスの中の時間です。HTTPクライアントとGoのスパンの差の1.5msには、通信のほか、HTTP::Tinyとotelhttpの処理や応答の読み取りにかかった時間が含まれます。2章で同じ0.6秒前後に見えた2つのリクエストは、トレースでは直す場所が別だと分かりました。

![サービスをまたぐトレース](/images/20261128-plack-request-spans.png)
*図1: 受け取ったトレースの構造。矢印は1つのリクエストの処理の中での呼び出しの向きを表す。ミドルウェアがSERVERのスパンを作ってから `app_otel.psgi` を呼び、その中で `in_span` が集計処理のスパンを、`HTTP::Tiny` の計装がCLIENTのスパンを作る。計装はリクエストに `traceparent` を書き込み、Goの `otelhttp` がそれを読んで自分のスパンの親にする*

表を見直すと、Perlのサーバーのスパンは集計とHTTPクライアントの和より5〜12ms長くなっていました。`days=7&currency=USD` なら、21.3msと21.1msの和は42.4msで、サーバーのスパンは47.3msです。この差には、5章と6章で使ったSimpleプロセッサーの同期送信の費用が含まれます。Simpleプロセッサーは子のスパンが終わるたびに、リクエストの処理の途中でCollectorへの送信を済ませるからです。8章で、この差を含めてプロセッサーごとの費用を比べます。
