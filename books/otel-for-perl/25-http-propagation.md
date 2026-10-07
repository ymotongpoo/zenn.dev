---
title: "HTTP呼び出しでサービスをまたぐ"
---

## HTTP::Tinyの計装

5章の木には、まだ説明していないスパンが2つありました。`report` の `GET` と、`rates` の `GET /rates` です。`report` の `GET` は、`app_otel.psgi` に足した次の1行が作っています。

```perl
use OpenTelemetry::Instrumentation 'HTTP::Tiny';
```

[OpenTelemetry::Instrumentation](https://metacpan.org/pod/OpenTelemetry::Instrumentation)は、CPANのモジュールごとの計装をまとめて読み込むモジュールです。モジュール名を渡すと、そのモジュールを読み込んだうえで対応する計装を有効にします。APIの配布物に入っている計装は、`HTTP::Tiny`、`LWP::UserAgent`、`DBI`向けです。`-all` を渡すと、インストール済みの計装をすべて有効にします。ただし対象は、`use` の時点ですでに読み込まれているモジュールだけです。`use OpenTelemetry::Instrumentation -all;` を `use HTTP::Tiny;` より前に書くと、`HTTP::Tiny` は計装されません。モジュール名を明示しておけば、`use` の順序を気にせずに済みます[^legacy]。

`HTTP::Tiny` の計装は、`HTTP::Tiny::request` メソッドの周りに処理を差し込みます。差し込んだ処理は、リクエストのたびに種類がCLIENTのスパンを作り、現在のコンテキストに入れます。続いてリクエストのヘッダーに `traceparent` を書き込み、元のメソッドを呼ぶ流れです。`Demo::Report` は、計装の前に `HTTP::Tiny` のオブジェクトを作っています。それでも差し込みはメソッドそのものに対して行われるので、作成済みのオブジェクトからの呼び出しも計装されます。

[^legacy]: 0.026より前は、計装は `OpenTelemetry::Integration` の名前空間にありました。いまのバージョンでも古い名前空間を探しますが、新しいコードでは `OpenTelemetry::Instrumentation` を使います。SDKのPOD（0.028）のSYNOPSISには、古い `OpenTelemetry::Integration` の書き方が残っています。

クライアントのスパンには、次の属性が付いていました。

| 属性 | 値の例 |
| --- | --- |
| `http.request.method` | `GET` |
| `http.response.status_code` | `200` |
| `url.full` | `http://backend:8080/rates?currency=USD` |
| `server.address` | `backend` |
| `server.port` | `8080` |
| `network.protocol.version` | `1.1` |
| `user_agent.original` | `HTTP-Tiny/0.096` |

スパン名の `GET` は、セマンティック規約どおりの名前です。規約は、クライアントのスパンでURLの型を表す `url.template` が無ければ、スパン名を `{method}` にすると定めています。`server.address` と `server.port` も、5章のサーバーのスパンと違って分けて入っています。

## Goのサービスで受け取る

`rates` はGoの公式SDKと、`net/http` のハンドラーを計装する[otelhttp](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp)で書きました。トレースに関係する部分を抜き出します。

```go:main.go（抜粋）
func main() {
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
	defer tp.Shutdown(ctx)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.TraceContext{})

	mux := http.NewServeMux()
	mux.HandleFunc("GET /rates", rates)
	log.Fatal(http.ListenAndServe(":8080", otelhttp.NewHandler(mux, "rates")))
}
```

`otelhttp.NewHandler` は、リクエストのヘッダーから取り出したトレースコンテキストを親にして、サーバーのスパンを作ります。ヘッダーを読む形式を決めるのが `SetTextMapPropagator` です。Goのグローバルなプロパゲーターは、設定しなければ何もしない実装のままです。そのため、W3C Trace Contextを読む `propagation.TraceContext` を明示しています。

PerlのSDKは、`OTEL_PROPAGATORS` のデフォルト値に従ってW3C Trace ContextとBaggageのプロパゲーターを組みます。PerlのSDKが書いた `traceparent` を、GoのSDKが読む関係です。2つのSDKは別々の人が別々の言語で書いたものですが、間にあるのはW3Cが定めたヘッダーの形式だけです。

## 3種類のリクエストの比較

Collectorに届いた `rates` のスパンの親は、すべてPerlのクライアントのスパンでした。2章の3種類のリクエストのトレースから、スパンごとの所要時間を並べます。

| リクエスト | サーバー（Perl） | aggregate | HTTPクライアント | `GET /rates`（Go） |
| --- | --- | --- | --- | --- |
| `days=7&currency=USD` | 53.9ms | 21.3ms | 21.8ms | 20.4ms |
| `days=180&currency=USD` | 576.7ms | 540.4ms | 22.8ms | 20.5ms |
| `days=7&currency=BRL` | 634.0ms | 21.3ms | 602.7ms | 600.7ms |

`currency=BRL` のリクエストでは、Perlのクライアントのスパンが602.7msで、その子であるGoのスパンが600.7msです。待ち時間のほとんどは、Goのサービスの中で使われています。HTTPクライアントとGoのスパンの差の2msは、通信と、Goのハンドラーにリクエストが届くまでの時間です。2章で同じ0.6秒前後に見えた2つのリクエストは、トレースでは直す場所が別だと分かりました。

![サービスをまたぐトレース](/images/20261128-plack-request-spans.png)
*図1: 受け取ったトレースの構造。矢印は1つのリクエストの処理の中での呼び出しの向きを表す。ミドルウェアがSERVERのスパンを作ってから `app_otel.psgi` を呼び、その中で `in_span` が集計処理のスパンを、`HTTP::Tiny` の計装がCLIENTのスパンを作る。計装はリクエストに `traceparent` を書き込み、Goの `otelhttp` がそれを読んで自分のスパンの親にする*

表を見直すと、Perlのサーバーのスパンは集計とHTTPクライアントの和より10ms前後長くなっていました。`days=7&currency=USD` なら、21.3msと21.8msの和は43.1msで、サーバーのスパンは53.9msです。この差は、5章と6章で使ったSimpleプロセッサーの性質によるものです。Simpleプロセッサーは子のスパンが終わるたびに、リクエストの処理の途中でCollectorへの送信を済ませます。送信にかかった時間も、親であるサーバーのスパンの所要時間の一部です。8章で、この差を含めてプロセッサーごとの費用を比べます。
