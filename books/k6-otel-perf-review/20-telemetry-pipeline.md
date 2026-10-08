---
title: "試験とアプリのテレメトリーを集める"
---

ここまでの数字はすべて[k6](https://grafana.com/docs/k6/v2.3.x/)の側から見たものでした。k6が測るのは、リクエストを送ってから応答を受け取るまでの時間です。その時間のうち、`catalog-api`の中でどれだけ使い、`inventory`でどれだけ使ったのかは、k6には見えません。修正前の版が毎秒100件で2.6秒かかった理由も、修正後の版が毎秒150件で502を返した理由も、ここまでは2章で決めた構成の数字から逆算したにすぎません。

アプリケーションの中で起きたことを確かめるには、アプリケーション自身が出すテレメトリーが必要です。この章では、`catalog-api`と`inventory`のテレメトリーと、k6の試験のメトリクスを1か所に集める構成を組みます。

## アプリケーションの計装

OpenTelemetryではテレメトリーをトレース、メトリクス、ログの3種類の**シグナル**に分けます。**トレース**は、1件のリクエストの処理を、区間を表す**スパン**の木で表したものです。スパンは名前と開始と終了の時刻を持ち、親のスパンの中に子のスパンが入ります。`catalog-api`のスパンの子として`inventory`のスパンを記録するには、HTTPのヘッダーでトレースの識別子を受け渡します。この受け渡しを**伝搬**（propagation）と呼び、ヘッダーの形式は[W3C Trace Context](https://www.w3.org/TR/trace-context/)の`traceparent`です。

題材の2つのサービスは、同じ初期化のコードでSDKを設定しています。送信のプロトコルは3つのシグナルともOTLP/HTTPです。送り先とサービス名は、標準の環境変数`OTEL_EXPORTER_OTLP_ENDPOINT`と`OTEL_SERVICE_NAME`で渡します。

```go
tp := sdktrace.NewTracerProvider(sdktrace.WithResource(res), sdktrace.WithBatcher(te))
otel.SetTracerProvider(tp)
otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
	propagation.TraceContext{}, propagation.Baggage{}))

mp := sdkmetric.NewMeterProvider(sdkmetric.WithResource(res),
	sdkmetric.WithReader(sdkmetric.NewPeriodicReader(me, sdkmetric.WithInterval(5*time.Second))))
otel.SetMeterProvider(mp)

lp := sdklog.NewLoggerProvider(sdklog.WithResource(res), sdklog.WithProcessor(sdklog.NewBatchProcessor(le)))
otel.SetLoggerProvider(lp)
logger := slog.New(otelslog.NewHandler(scope, otelslog.WithLoggerProvider(lp)))
```

最後の`logger`は抜粋のために簡略化しており、題材のコードでは同じログを標準出力にも書いています。

HTTPの計装には[otelhttp](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp@v0.72.0)を使います。サーバー側はハンドラーを`otelhttp.NewHandler`で包み、クライアント側は`http.Client`のトランスポートを`otelhttp.NewTransport`で包む形です。`traceparent`は、クライアント側の計装がリクエストに付けます。

```go
client := &http.Client{
	Transport: otelhttp.NewTransport(&http.Transport{MaxIdleConnsPerHost: 256}),
	Timeout:   2 * time.Second,
}
srv := &http.Server{Addr: ":8080", Handler: otelhttp.NewHandler(mux, "catalog")}
```

これで1件のリクエストに対して3つのスパンが記録されます。`catalog-api`のサーバースパン`GET /items/{id}`、その子で`inventory`を呼ぶクライアントスパン`HTTP GET`、さらにその子で`inventory`のサーバースパン`GET /stock/{id}`です。`inventory`では、在庫を調べる処理を`lookup stock`という子のスパンで囲みました。

メトリクスは、otelhttpがサーバーとクライアントの処理時間のヒストグラム（`http.server.request.duration`と`http.client.request.duration`）を記録します。処理中のリクエストの数を表す`http.server.active_requests`は、otelhttp v0.72.0の記録の対象外です。`inventory`では、同じ名前のメトリクスを増減するカウンター（UpDownCounter）として自分で記録しました。増減するカウンターは、加算と減算で現在の件数を表す計器です。あわせて、現在待ち行列で待っている件数（`inventory.queue.waiting`、増減するカウンター）と、あふれて断った件数の累計（`inventory.queue.rejected`、増えるだけのカウンター）も足しています。

ログは、[Go](https://go.dev/)の標準の`log/slog`を[otelslog](https://pkg.go.dev/go.opentelemetry.io/contrib/bridges/otelslog@v0.21.0)でOpenTelemetryのログに変換して送ります。`logger.WarnContext(ctx, ...)`のようにコンテキストを渡して書くと、そのとき実行中のスパンのトレースIDとスパンIDがログに付きます。

## k6のOpenTelemetry出力

k6のOpenTelemetry出力は、試験のメトリクスをOTLPで送る機能です[^otelout]。`k6 run -o opentelemetry`で有効にし、送り先は`K6_OTEL_`で始まる環境変数で設定します。プロトコルのデフォルトはgRPCなので、Alloyの受け口に合わせてHTTPに変えました。

[^otelout]: [OpenTelemetry output](https://grafana.com/docs/k6/v2.3.x/results-output/real-time/opentelemetry/)。k6 v2.3.0のソースでは、この出力は`opentelemetry`と`experimental-opentelemetry`の2つの名前で登録されています。

```yaml
environment:
  K6_OTEL_EXPORTER_PROTOCOL: http/protobuf
  K6_OTEL_HTTP_EXPORTER_ENDPOINT: alloy:4318
  K6_OTEL_HTTP_EXPORTER_INSECURE: "true"
  K6_OTEL_SERVICE_NAME: k6
```

この出力が送るのはメトリクスだけです。k6の試験のあとで、Tempoに記録されたサービスは`catalog-api`と`inventory`の2つだけで、`service.name`が`k6`のトレースは0件でした。Lokiのログにも同じ2つのサービスのものしかありません。k6の出力を有効にしても、アプリケーションの分散トレースが生成されるわけではありません。トレースは、アプリケーション側の計装と伝搬で作るものです。

Mimirに届いたk6のメトリクスは、`http_req_duration_milliseconds`のヒストグラムや`http_reqs_total`、`dropped_iterations_total`のような名前です。k6のタグはOpenTelemetryの属性に変換され、Mimirではラベルになります。題材の試験では、試験ごとに`testid`タグを付けているので、試験を`testid`のラベルで選べます。

```javascript
const label = __ENV.LABEL || model;

export const options = {
  tags: { testid: label },
};
```

一方、アプリケーションのメトリクスには`testid`のラベルがありません。`catalog-api`は、どの試験から届いたリクエストなのかを知らないからです。k6のメトリクスとアプリケーションのメトリクスは、同じ時間範囲を選ぶことでしか比べられません。

## 収集と保存

3つのサービスのテレメトリーは、いったん[Grafana Alloy](https://grafana.com/docs/alloy/v1.20/)に集めます。AlloyはGrafana Labsが開発するテレメトリーのコレクターで、OpenTelemetry Collectorの部品を組み合わせて設定を書けます。題材の設定は、OTLPを受けてシグナルごとに保存先へ振り分けるだけです。

```alloy
otelcol.receiver.otlp "default" {
  grpc { endpoint = "0.0.0.0:4317" }
  http { endpoint = "0.0.0.0:4318" }

  output {
    metrics = [otelcol.processor.batch.default.input]
    traces  = [otelcol.processor.batch.default.input]
    logs    = [otelcol.processor.batch.default.input]
  }
}

otelcol.processor.batch "default" {
  output {
    metrics = [otelcol.exporter.otlphttp.mimir.input]
    traces  = [otelcol.exporter.otlp.tempo.input]
    logs    = [otelcol.exporter.otlphttp.loki.input]
  }
}

otelcol.exporter.otlphttp "mimir" {
  client { endpoint = "http://mimir:9009/otlp" }
}

otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo:4317"
    tls { insecure = true }
  }
}

otelcol.exporter.otlphttp "loki" {
  client { endpoint = "http://loki:3100/otlp" }
}
```

保存先は3つです。メトリクスは[Grafana Mimir](https://grafana.com/docs/mimir/v3.2.x/)、トレースは[Grafana Tempo](https://grafana.com/docs/tempo/v3.1.x/)、ログは[Grafana Loki](https://grafana.com/docs/loki/v3.7.x/)に入れ、[Grafana](https://grafana.com/docs/grafana/v13.2/)から3つを横断して調べます。いずれもOTLPを直接受け付けるので、Alloyの側での形式の変換は不要です。題材ではどれも単一のプロセスで動かし、データはローカルのファイルシステムに置いています。

保存先によって、OpenTelemetryのリソース属性の扱いが違います。Mimirでは、`service.name`が`job`ラベルになります。選ぶ条件は、`catalog-api`のメトリクスなら`job="catalog-api"`、k6のメトリクスなら`job="k6"`です。Lokiでは、`service.name`が`service_name`というラベルになり、ログに付いたトレースIDとスパンIDは構造化メタデータの`trace_id`と`span_id`に入ります。

Grafanaでは、Tempoのデータソースにトレースからログへ移る設定を入れました。トレースの画面でスパンを選ぶと、そのスパンのサービス名とトレースIDでLokiを検索します。

```yaml
- name: Tempo
  type: tempo
  uid: tempo
  url: http://tempo:3200
  jsonData:
    tracesToLogsV2:
      datasourceUid: loki
      spanStartTimeShift: -1m
      spanEndTimeShift: 1m
      filterByTraceID: true
      customQuery: true
      query: '{service_name="$${__span.tags["service.name"]}"} | trace_id="$${__span.traceId}"'
```

`inventory`があふれて503を返した回のトレースを1件選び、このクエリと同じ条件でLokiを検索すると、`catalog-api`が書いた「backend returned error」のログが1件返りました。トレースとログは、トレースIDで1件ずつ対応しています。

これでk6のメトリクス、アプリケーションのメトリクス、トレース、ログの4種類が同じGrafanaから引けるようになりました。ただし、4種類のつながり方は同じではありません。トレースとログはトレースIDでつながり、k6のメトリクスとアプリケーションのメトリクスをつなぐものは時刻だけです。
