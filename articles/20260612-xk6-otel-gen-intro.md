---
title: "OpenTelemetry形式でテレメトリーデータを自動生成するk6拡張を作った"
emoji: "⛰️"
type: "tech"
topics: ["k6", "OpenTelemetry", "Grafana"]
published: false
---

## はじめに
こんにちは、Grafana Labsでデベロッパーアドボケイトをしているものです。

オブザーバビリティ基盤の検証をしたいとき、いつも悩ましいのが「それらしいテレメトリーをどう用意するか」です。
ダッシュボードの開発、Collectorパイプラインの設定確認、バックエンドの負荷試験、社内トレーニングなど、どれも本物のマイクロサービス群を動かすのは大変です。

これは半分愚痴なんですが、オブザーバビリティ製品のデモは

1. まあまあ複雑なシステム（監視対象）を用意する
2. システムを計装する
3. しばらく動かし続けてテレメトリーをある程度生成する

ということをすべてやって初めて実施できます。これがランタイム系（サーバーレス製品やLLMモデルのAPIなど）であれば

1. コンテナを作ってデプロイする

で終わったりするので「うらやましいなー」と思うことが多々ありました。

そこでどうせならということで、そういったオブザーバビリティSaaSのデモを簡単に作れるようにテレメトリー生成器を作ろうと考えて `xk6-otel-gen` を作りました。

@[card](https://ymotongpoo.github.io/xk6-otel-gen/ja/)

これは名前からわかるようにk6拡張です。リポジトリを見れば一目瞭然でAIコーディングエージェントに全部実装してもらいました。
サービス間の呼び出し関係をYAMLで宣言すると、それに沿った擬似的なトレース、メトリクス、ログをOpenTelemetry形式で合成し、OTLPエンドポイントに送信します。
実際のサービスは1つも必要ありません。

この記事ではどういうツールなのか、インストールから最初のシミュレーション、障害注入までを一通り紹介します。

## 仕組み

xk6-otel-genの入力は「トポロジーYAML」と呼ぶ1つのファイルです。3つのセクションで構成されます。

| セクション | 役割 |
|---|---|
| `services` | サービスとその操作(operation)、操作間の呼び出しエッジを定義 |
| `journeys` | ユーザー視点の一連のフロー。1回実行すると1本のトレースになる |
| `faults` | エラー率の上書きやレイテンシー増幅などの障害シナリオ(省略可) |

k6スクリプトからジャーニーを実行するたびに、エンジンがエッジを再帰的にたどり、レイテンシー分布(対数正規分布など)とエラー率に従ってスパンを合成します。スパンに対応するメトリクス（レイテンシーヒストグラムやリクエストカウント）とログも同時に生成され、すべて同じトレースコンテキストで関連付けられます。
負荷の量や同時実行数の制御は、k6本来のVU/duration/executorの仕組みをそのまま使えます。

## 前提条件

| ツール | バージョン | 用途 |
|---|---|---|
| Go | 1.25以上 | 拡張入りk6バイナリのビルド |
| xk6 | 最新 | カスタムk6バイナリのビルドツール |
| Docker | 最新安定版 | 受信側のOpenTelemetry Collectorの実行 |

## インストール

k6の拡張は、xk6というツールで拡張を組み込んだk6バイナリをビルドして使います。

```bash
go install go.k6.io/xk6/cmd/xk6@latest
xk6 build --with github.com/ymotongpoo/xk6-otel-gen
```

カレントディレクトリに`k6`バイナリが生成されます。拡張が組み込まれているか確認しましょう。

```console
$ ./k6 version
k6 v1.8.0 (go1.25.0, linux/amd64)
Extensions:
  github.com/ymotongpoo/xk6-otel-gen (devel), k6/x/otel-gen [js]
  github.com/ymotongpoo/xk6-otel-gen (devel), otel-gen [output]
```

JavaScript API(`k6/x/otel-gen`)とk6 output(`otel-gen`)の2つが登録されていれば成功です。

## 受信側のCollectorを用意する

最初の動作確認として、受信した内容を標準出力に表示するだけのOpenTelemetry Collectorを使います。
次の設定を`collector-config.yaml`として保存します。

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

exporters:
  debug:
    verbosity: normal

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug]
    metrics:
      receivers: [otlp]
      exporters: [debug]
    logs:
      receivers: [otlp]
      exporters: [debug]
```

Dockerで起動します。

```bash
docker run --rm --name otel-collector -p 4317:4317 \
  -v "$PWD/collector-config.yaml:/etc/otelcol/config.yaml" \
  otel/opentelemetry-collector:latest
```

## トポロジーを書く

古典的な3層構成(frontend → backend → database)をモデル化してみます。`topology.yaml`として保存してください。

```yaml
namespace: demo
services:
  frontend:
    kind: application
    replicas: 2
    language: go
    framework: net/http
    version: 1.0.0
    operations:
      - name: get_index
        calls:
          - to:
              service: backend
              operation: get_user
            protocol: http
            latency:
              distribution: lognormal
              p50: 50ms
              p95: 150ms
            error_rate: 0.01

  backend:
    kind: application
    replicas: 3
    language: java
    framework: spring-boot
    version: 2.5.0
    operations:
      - name: get_user
        calls:
          - to:
              service: database
              operation: select_user
            protocol: grpc
            latency:
              distribution: lognormal
              p50: 20ms
              p95: 80ms
            error_rate: 0.005

  database:
    kind: database
    replicas: 1
    language: c
    framework: postgresql
    version: "16.4"
    operations:
      - name: select_user

journeys:
  checkout:
    weight: 1.0
    steps:
      - service: frontend
        operation: get_index
```

ポイントは次のとおりです。

- `calls`が呼び出しエッジです。`latency`でp50/p95を指定すると、その分布に従ったスパン長が生成されます
- `error_rate`はそのエッジが失敗する基礎確率です
- `journeys.checkout`は`frontend.get_index`を起点とし、エンジンがそこから`calls`を再帰的にたどります

## k6スクリプトを書く

`script.js`として保存します。

```javascript
import { sleep } from "k6";
import otelgen from "k6/x/otel-gen";

export const options = {
  vus: 5,
  duration: "30s",
};

export function setup() {
  otelgen.configure({
    endpoint: "localhost:4317",
    protocol: "grpc",
    insecure: true,
  });
}

export default function () {
  const topology = otelgen.load("./topology.yaml");
  topology.runJourney("checkout");
  sleep(1);
}

export function teardown() {
  const stats = otelgen.stats();
  console.log(`traces exported: ${stats.tracesExported}, failed: ${stats.tracesFailed}`);
}
```

構成には1つ注意点があります。`otelgen.load()`は**`default`関数の中で呼びます**。k6では`setup()`の戻り値がJSONシリアライズされて各VUに渡されるため、`load()`が返すハンドルを`setup()`から返すとメソッドが失われてしまいます。`load()`はファイルの読み込みと検証をテスト全体で1回だけ行い、2回目以降はキャッシュ済みハンドルを返すだけなので、毎イテレーションで呼んでもオーバーヘッドはありません。一方`otelgen.configure()`はテスト全体で1回しか呼べないため、`setup()`に置くのが定石です。

## 実行する

```bash
./k6 run script.js
```

実行が終わると、k6のサマリーに拡張のネイティブメトリクスが表示されます。

```text
  █ TOTAL RESULTS

    CUSTOM
    otel_gen_logs_exported......: 2175 72.439099/s
    otel_gen_metrics_exported...: 790  26.311213/s
    otel_gen_queue_drops........: 0    min=0       max=0
    otel_gen_traces_exported....: 2175 72.439099/s

    EXECUTION
    iteration_duration..........: avg=1s min=1s med=1s max=1s p(90)=1s p(95)=1s
    iterations..................: 150  4.9958/s
```

5 VU × `sleep(1)`なので毎秒約5ジャーニー、30秒で150本のトレースが送信されました。`otel_gen_traces_failed`や`otel_gen_queue_drops`が増えていなければ、エクスポートはすべて成功しています。

Collector側のログを見ると、合成されたスパンが届いているのがわかります。同じトレースIDを持つ3つのスパンが、frontend → backend → databaseの呼び出し階層を構成しています。

```text
frontend.get_index 6c9c90ecbfaf5145e11cc1ddcb0ad833 f4481f2b827b88a7
  http.request.method=GET http.route=/get_index service.name=frontend
  http.response.status_code=200
backend.get_user 6c9c90ecbfaf5145e11cc1ddcb0ad833 63bd3f571b5a2707
  http.request.method=GET http.route=/get_user service.name=backend
  http.response.status_code=200
database.select_user 6c9c90ecbfaf5145e11cc1ddcb0ad833 c269c33853246e6b
  db.operation.name=select_user db.system=postgresql server.address=database
  server.port=5432 service.name=database
```

`http.*`や`db.*`などの属性はOpenTelemetryセマンティック規約に沿って付与されるため、Grafana TempoやJaegerなどのバックエンドでもサービスグラフやスパンメトリクスが自然に機能します。

## 障害を注入する

オブザーバビリティ基盤の検証で本当に見たいのは「異常時の見え方」です。`topology.yaml`の末尾に`faults`セクションを追加してみましょう。

```yaml
faults:
  # backend.get_user のレイテンシーを30%の確率で5倍にする
  - target: operation:backend.get_user
    kind: latency_inflation
    severity:
      probability: 0.3
      multiplier: 5.0
  # frontend→backend のエッジのエラー率を20%に上書きする
  - target: edge:frontend.get_index->backend.get_user
    kind: error_rate_override
    severity:
      probability: 1.0
      value: 0.2
```

ターゲットは`node:<サービス>`(サービス全体)、`operation:<サービス>.<操作>`(1操作)、`edge:<from>.<op>-><to>.<op>`(1エッジ)の3粒度で指定でき、`latency_inflation`、`error_rate_override`、`disconnect`、`crash`の4種類の障害が使えます。

同じコマンドで再実行すると、Collectorにエラーを示すスパンとログが流れ始めます。

```text
backend.get_user 3aa55a50cad0d8034dd74a72813b9cf2 a603a448031baf6c
  http.request.method=GET http.route=/get_user service.name=backend
  http.response.status_code=500 error.type=http.500
```

```text
get_user failure exception.type=ServerError
  exception.message=simulated failure: http.500 on get_user
  outcome=failure error.type=http.500 service.name=backend
```

エラースパンには`http.response.status_code=500`と`error.type`が、対応するログには`exception.type`/`exception.message`が付与されます。アラートルールやエラー率ダッシュボードの動作確認が、YAMLを数行書き換えるだけでできるわけです。

## 設定の優先順位とoutput拡張

OTLPの接続設定はJS API以外からも与えられます。優先順位は次のとおりです(上が優先)。

| 優先度 | ソース | 例 |
|---|---|---|
| 1 | JS API | `otelgen.configure({ endpoint: "localhost:4317" })` |
| 2 | `--out`引数 | `--out otel-gen=endpoint=localhost:4317,protocol=grpc` |
| 3 | 環境変数 | `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` |
| 4 | デフォルト | `localhost:4317`、gRPC |

`--out otel-gen=...`を使うと、合成テレメトリーに加えてk6自身の実行メトリクスも同じOTLPエンドポイントに転送されます。スクリプト側の`configure()`を省略して、接続先をコマンドラインだけで切り替える運用も可能です。

```bash
./k6 run script.js \
  --out otel-gen=endpoint=localhost:4317,protocol=grpc,insecure=true
```

TLS(`caCert`/`clientCert`/`clientKey`)、認証ヘッダー、サンプラー(`always_on`/`always_off`/`traceidratio`)、バッチサイズなども`configure()`で指定できます。Grafana CloudのようなマネージドOTLPエンドポイントへの送信例は[examples/saas-endpoints.md](../examples/saas-endpoints.md)にまとまっています。

## 可視化まで試したい場合

debugエクスポーターの代わりに、リポジトリ同梱のKubernetesマニフェストでCollector + Tempo + Prometheus + Loki + Grafanaのスタックを立ち上げられます。

```bash
kind create cluster --name xk6-otel-gen
kubectl apply -k examples/minimal/k8s/
kubectl -n xk6-otel-gen-demo port-forward svc/otel-collector 4317:4317 &
kubectl -n xk6-otel-gen-demo port-forward svc/grafana 3000:3000 &
./k6 run script.js
```

`http://localhost:3000`のGrafanaにオーバービューダッシュボードが事前設定されており、トレース・メトリクス・ログを横断して確認できます。

## 次のステップ

- **大規模なトポロジー**: [examples/astroshop](../examples/astroshop/)には、OpenTelemetry Demoを模した18サービスのECサイトトポロジーがあります。複数ジャーニーの`weight`による重み付き選択(`runRandomJourney()`)やリトライ・タイムアウトの設定例も含まれています
- **エディター補完**: `go run ./cmd/xk6-otel-gen-schema > topology.schema.json`でJSON Schemaを出力すると、エディターでトポロジーYAMLの補完と検証が効くようになります
- **YAMLリファレンス**: レイテンシー分布、リトライ(`retries`/`retry_backoff`)、タイムアウト、各障害の詳細は[READMEのTopology YAML Reference](../README.md#topology-yaml-reference)を参照してください

実サービスを1つも書かずに、それらしいマイクロサービスのテレメトリーが手に入りました。オブザーバビリティ基盤の検証やデモづくりのお供にどうぞ。
