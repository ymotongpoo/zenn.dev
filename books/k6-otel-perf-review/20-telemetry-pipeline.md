---
title: "テストとアプリのテレメトリーを集める"
---

ここまでの数字はすべて[k6](https://grafana.com/docs/k6/v2.3.x/)の側から見たものでした。k6が測るのは、リクエストを送ってから応答を受け取るまでの時間です。その時間のうち、`catalog-api`や`inventory`での処理時間は、k6には見えません。修正前のバージョンが毎秒100件で2.6秒かかった理由も、修正後のバージョンが毎秒150件で502を返した理由も、ここまでは2章で決めた構成の数字から逆算したにすぎません。

アプリケーション内部での動作を確かめるには、アプリケーション自身が出すテレメトリーが必要です。`catalog-api`と`inventory`のテレメトリーと、k6のテストのメトリクスを1か所に集めてみましょう。

## アプリケーションの計装

OpenTelemetryではテレメトリーをトレース、メトリクス、ログの3種類の**シグナル**に分けます。**トレース**は、1件のリクエストの処理を、区間を表す**スパン**の木で表したものです。スパンは名前と開始と終了の時刻を持ち、親のスパンの中に子のスパンが入ります。`catalog-api`のスパンの子として`inventory`のスパンを記録するには、HTTPのヘッダーでトレースの識別子を受け渡します。この受け渡しを**伝搬**（propagation）と呼び、ヘッダーの形式は[W3C Trace Context](https://www.w3.org/TR/trace-context/)の`traceparent`です。

サンプルの2つのサービスは、同じ初期化のコードでSDKを設定しています。送信のプロトコルは3つのシグナルともOTLP/HTTPです[^otlp]。送り先とサービス名は、標準の環境変数`OTEL_EXPORTER_OTLP_ENDPOINT`と`OTEL_SERVICE_NAME`で渡します[^logger]。

[^otlp]: OTLP（OpenTelemetry Protocol）は、テレメトリーを送受信するためのプロトコルです。OTLP/HTTPは、HTTPを使ってテレメトリーを送信します（[OTLP仕様](https://opentelemetry.io/docs/specs/otlp/)）。

[^logger]: 抜粋の最後の`logger`は簡略化したもので、サンプルのコードでは同じログを標準出力にも書いています。

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

HTTPの計装には[otelhttp](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp@v0.72.0)を使います。サーバー側はハンドラーを`otelhttp.NewHandler`で包み、クライアント側は`http.Client`のトランスポートを`otelhttp.NewTransport`で包む形です。`traceparent`は、クライアント側の計装がリクエストに付けます。

```go
client := &http.Client{
	Transport: otelhttp.NewTransport(&http.Transport{MaxIdleConnsPerHost: 256}),
	Timeout:   2 * time.Second,
}
srv := &http.Server{Addr: ":8080", Handler: otelhttp.NewHandler(mux, "catalog")}
```

これで1件のリクエストに対して3つのスパンが記録されます。`catalog-api`のサーバースパン`GET /items/{id}`、その子で`inventory`を呼ぶクライアントスパン`HTTP GET`、さらにその子で`inventory`のサーバースパン`GET /stock/{id}`です。`inventory`では、在庫を調べる処理を`lookup stock`という子のスパンで囲みました。

メトリクスは、otelhttpがサーバーとクライアントの処理時間のヒストグラム（`http.server.request.duration`と`http.client.request.duration`）を記録します。処理中のリクエストの数を表す`http.server.active_requests`は、otelhttp v0.72.0の記録の対象外です。`inventory`では、同じ名前のメトリクスを、加算と減算で現在の件数を表す増減するカウンター（UpDownCounter）として自分で記録しました。あわせて、待ち行列で待っている件数（`inventory.queue.waiting`、増減するカウンター）と、あふれて断った件数の累計（`inventory.queue.rejected`、増えるだけのカウンター）も記録しています。

ログは、[Go](https://go.dev/)の標準の`log/slog`を[otelslog](https://pkg.go.dev/go.opentelemetry.io/contrib/bridges/otelslog@v0.21.0)でOpenTelemetryのログに変換して送ります。`logger.WarnContext(ctx, ...)`のようにコンテキストを渡して書くと、そのとき実行中のスパンのトレースIDとスパンIDがログに付きます。

## k6のOpenTelemetry出力

k6のOpenTelemetry出力は、テストのメトリクスをOTLPで送る機能です[^otelout]。`k6 run -o opentelemetry`で有効にし、送り先は`K6_OTEL_`で始まる環境変数で設定します。プロトコルのデフォルトはgRPCですが、サンプルではAlloyのHTTPの受信エンドポイントに送るので、HTTPに変えました。

[^otelout]: [OpenTelemetry output](https://grafana.com/docs/k6/v2.3.x/results-output/real-time/opentelemetry/)。k6 v2.3.0のソースでは、この出力は`opentelemetry`と`experimental-opentelemetry`の2つの名前で登録されています。

```yaml
environment:
  K6_OTEL_EXPORTER_PROTOCOL: http/protobuf
  K6_OTEL_HTTP_EXPORTER_ENDPOINT: alloy:4318
  K6_OTEL_HTTP_EXPORTER_INSECURE: "true"
  K6_OTEL_SERVICE_NAME: k6
```

この出力が送るのはメトリクスだけです[^output-check]。トレースは、k6の出力ではなく、アプリケーション側の計装と伝搬で作られます。

[^output-check]: k6のテストのあと、Tempoに記録されたサービスは`catalog-api`と`inventory`の2つだけで、`service.name`が`k6`のトレースは0件でした。Lokiに入ったログも、同じ2つのサービスのものしかありません。

Mimirに届いたk6のメトリクスは、`http_req_duration_milliseconds`のヒストグラムや`http_reqs_total`、`dropped_iterations_total`のような名前です[^naming]。k6のタグはOpenTelemetryの属性に変換され、Mimirではラベルになります。サンプルではテストごとに`testid`タグを付けているので、Mimirでも`testid`のラベルでテストを選べます。

[^naming]: k6 v2.3.0のOpenTelemetry出力は、k6自身のメトリクス名（`http_req_duration`のようにアンダースコアで区切る）をそのまま送り、時間のメトリクスには単位`ms`を付けます（[`internal/output/opentelemetry/output.go`](https://github.com/grafana/k6/blob/v2.3.0/internal/output/opentelemetry/output.go)の`normalizeUnit`）。アプリケーションのメトリクスは、OpenTelemetryのセマンティック規約（メトリクスや属性の名前と単位を定めた規約）の名前で、`http.server.request.duration`のようにドットで区切り、単位は`s`です。MimirはOTLPで受けたメトリクス名をPrometheusの形式に変換して保存します。今回の構成では、ドットをアンダースコアに置き換え、単位（`_seconds`、`_milliseconds`）とカウンターの`_total`を末尾に付けました。変換の方式はMimirの`-distributor.otel-translation-strategy`で決まります（[Mimir 3.2の設定のリファレンス](https://grafana.com/docs/mimir/v3.2.x/configure/configuration-parameters/)）。その結果、Mimirの中では`http_req_duration_milliseconds`と`http_server_request_duration_seconds`のように、どちらもアンダースコアで区切った名前になります。

```javascript
const label = __ENV.LABEL || model;

export const options = {
  tags: { testid: label },
};
```

一方、アプリケーションのメトリクスには`testid`のラベルがありません。`catalog-api`は、どのテストから届いたリクエストなのかを知らないからです。

## 収集と保存

3つのサービスのテレメトリーは、いったん[Grafana Alloy](https://grafana.com/docs/alloy/v1.20/)に集めます[^alloy]。設定の中心は、バッチ処理のあとでシグナルごとに保存先へ振り分ける部分です。

```alloy
otelcol.processor.batch "default" {
  output {
    metrics = [otelcol.exporter.otlphttp.mimir.input]
    traces  = [otelcol.exporter.otlp.tempo.input]
    logs    = [otelcol.exporter.otlphttp.loki.input]
  }
}
```

[^alloy]: AlloyはGrafana Labsが開発するテレメトリーのコレクターで、OpenTelemetry Collectorのコンポーネントを組み合わせて設定を書けます。サンプルの設定は、OTLPを受けてシグナルごとに保存先へ振り分けるだけです。設定の全体は、サンプルのリポジトリの[`config/config.alloy`](https://github.com/ymotongpoo/k6-otel-perf-review/blob/f86b6ed88a1dbb34050897a984f9997e67f78d4a/config/config.alloy)にあります。OTLPのレシーバー（gRPCの4317番とHTTPの4318番）、バッチ処理、3つの保存先への送信からなります。

メトリクスは[Grafana Mimir](https://grafana.com/docs/mimir/v3.2.x/)、トレースは[Grafana Tempo](https://grafana.com/docs/tempo/v3.1.x/)、ログは[Grafana Loki](https://grafana.com/docs/loki/v3.7.x/)に入れ、[Grafana](https://grafana.com/docs/grafana/v13.2/)から3つを横断して調べます[^storage-layout]。いずれもOTLPを直接受け付けるので、Alloyの側での形式の変換は不要です。

[^storage-layout]: サンプルでは、各保存先を単一のプロセスで動かし、データはローカルのファイルシステムに置いています。

テレメトリーの発生元を表す[リソース属性](https://opentelemetry.io/docs/concepts/resources/)は、保存先によって扱いが違います。Mimirでは、`service.name`が`job`ラベルになります。選ぶ条件は、`catalog-api`のメトリクスなら`job="catalog-api"`、k6のメトリクスなら`job="k6"`です。Lokiでは、`service.name`が`service_name`というラベルになり、ログに付いたトレースIDとスパンIDは構造化メタデータの`trace_id`と`span_id`に入ります。

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

これで、k6のメトリクス、アプリケーションのメトリクス、トレース、ログの4種類を同じGrafanaから調べられます。サンプルのリポジトリには、k6とアプリケーションのメトリクスを並べたダッシュボードも入れてあります。図1は、3章の修正前のバージョンに毎秒100件をかけたテストを選んだ画面です。

![k6の完了したリクエストの頻度は毎秒77件前後、k6から見たp(95)は約4.8秒、VUの数は200で頭打ち、catalog-apiのサーバー側のp(95)は約4.9秒、inventoryは0秒近くのまま](/images/20261118-grafana-dashboard-open-l4-r100.png)
*図1: 修正前のバージョンに毎秒100件をかけたテストを、サンプルのダッシュボードでGrafanaに表示した画面。上の2段がk6のメトリクス、下の段がアプリケーションのメトリクス*

同じ画面に並んでいても、4種類のつながり方は同じではありません。トレースとログはトレースIDでつながり、k6のメトリクスとアプリケーションのメトリクスをつなぐものは時刻だけです。図1の上の2段は`testid`でテストを選べますが、下の段は同じ時間範囲を表示しているにすぎません。
