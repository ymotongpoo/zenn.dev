---
title: "アグリゲーションとモニタリング"
---

## アグリゲーション（集約）

サンプリングは「データを捨てる」行為ですが、**アグリゲーション（集約）** は「詳細を捨てる代わりに、傾向（統計量）を残す」行為です。

### 生トレースを捨てる代わりにメトリクス化する

すべてのトレースを保存するのはコスト的に不可能でも、すべてのリクエストのレイテンシーやエラーの有無をカウントすることは可能です。OpenTelemetry Collectorの `spanmetrics` コネクターや各種プロセッサーを使用して、スパンからメトリクス（リクエスト数、レイテンシーのヒストグラムなど）を事前生成します。
これにより、サンプリングでトレースを0.1%まで絞り込んだとしても、サービス全体の正確な成功率やP99レイテンシーをメトリクスとして維持し続けることができます。

### spanmetrics コネクターの設定例

`spanmetric`コネクター [^spanmetricsconnector]は、OpenTelemetry Collectorのconnectorコンポーネントで、トレースパイプラインからスパンデータを受け取り、メトリクスパイプラインにメトリクスを出力します。
サンプリング前の全量トレースからメトリクスを生成することで、サンプリングによる情報損失を補完する役割を果たします。

#### 生成されるメトリクス

`spanmetrics` コネクターは以下のメトリクスを自動生成します。

| メトリクス名 | 種類 | 説明 |
| --- | --- | --- |
| `duration` | ヒストグラム | スパンの処理時間の分布。デフォルトのメトリクス名は `duration`（`namespace` 設定で接頭辞を付与可能） |
| `calls` | カウンター | スパンの呼び出し回数。成功・失敗を `status.code` ラベルで区別 |
| `events` | カウンター | スパンイベントの発生回数（オプション、`events` 設定で有効化） |

これらのメトリクスには、サービス名（`service.name`）、スパン名（`span.name`）、スパン種別（`span.kind`）、ステータスコード（`status.code`）がデフォルトのディメンション（ラベル）として付与されます。

#### 基本設定例

以下は、`spanmetrics` コネクターの基本的な設定例です。

```yaml
# OpenTelemetry Collector設定例: spanmetricsconnector
connectors:
  spanmetrics:
    # メトリクス名の接頭辞（例: traces.duration, traces.calls）
    namespace: traces
    # ヒストグラムの設定
    histogram:
      # 明示的バケット境界（ミリ秒単位）
      explicit:
        buckets: [2, 4, 6, 8, 10, 50, 100, 200, 400, 800, 1000, 5000, 10000]
    # 追加ディメンション（ラベル）の設定
    dimensions:
      - name: http.request.method
      - name: http.response.status_code
      - name: http.route
      - name: rpc.method
      - name: rpc.service
    # メトリクスの有効期限（この期間スパンが到着しないディメンションの
    # 時系列はメトリクス出力から除外される）
    metrics_expiration: 5m
    # リソース属性をメトリクスのラベルに含めるかどうか
    resource_metrics_key_attributes:
      - service.name
      - deployment.environment

service:
  pipelines:
    # トレースパイプライン: spanmetricsconnectorを経由してメトリクスを生成
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [spanmetrics, otlp/backend]
    # メトリクスパイプライン: spanmetricsconnectorからメトリクスを受信
    metrics:
      receivers: [spanmetrics]
      processors: [batch]
      exporters: [prometheus]
```

この設定では、トレースパイプラインの `exporters` に `spanmetrics` を含めることで、すべてのスパンデータが `spanmetricsconnector` に渡されます。`spanmetricsconnector` はスパンからメトリクスを生成し、メトリクスパイプラインの `receivers` として機能します。

#### ヒストグラムバケットの設定

ヒストグラムバケットの設定は、レイテンシー分布の精度に直接影響します。

`spanmetrics` コネクターは、明示的バケット（explicit）と指数ヒストグラム（exponential）の2つのモードをサポートしています。
明示的バケットはバケット境界を手動で定義するモードで、レイテンシー分布が既知の場合に精度を最適化できます。
一方、指数ヒストグラムはバケット境界を自動的に決定するため、分布が不明な場合や広範囲のレイテンシーをカバーしたい場合に適しています。

以下は明示的バケットの設定例です。
サービスのレイテンシー分布が既知で、特定のパーセンタイル（P50、P95、P99）の精度を重視する場合に、バケット境界を手動で最適化できる利点があります。

```yaml
connectors:
  spanmetrics:
    histogram:
      # 明示的バケット: 任意の境界値を指定
      explicit:
        buckets: [2, 4, 6, 8, 10, 50, 100, 200, 400, 800, 1000, 5000, 10000]
```

指数ヒストグラムを使用する場合は、以下のように設定します。

```yaml
connectors:
  spanmetrics:
    histogram:
      # 指数ヒストグラム: バケット境界を自動決定
      exponential:
        max_size: 160
```

バケット境界の設計指針は以下のとおりです。

* 低レイテンシー帯（2〜10 ms）を細かく区切ることで、P50付近の精度を確保する
* 中レイテンシー帯（50〜1,000 ms）はP95/P99の計算に重要
* 高レイテンシー帯（5,000〜10,000 ms）はタイムアウトに近い異常値の検出に使用する
* バケット数が多すぎるとカーディナリティが増加し、メトリクスストレージのコストが上がる。通常10〜15個程度が適切
* レイテンシー分布が不明な場合や、多様なサービスを一括で計測する場合は指数ヒストグラムの利用を検討する

#### ディメンション（ラベル）の設定

追加ディメンションを設定することで、メトリクスの分析粒度を制御できます。

```yaml
connectors:
  spanmetrics:
    dimensions:
      # スパン属性からディメンションを追加
      - name: http.request.method
      - name: http.response.status_code
      - name: http.route
      # デフォルト値を指定（属性が存在しない場合に使用）
      - name: deployment.environment
        default: unknown
    # リソース属性からディメンションを追加
    resource_metrics_key_attributes:
      - service.name
      - service.version
```

ディメンション設定の注意点は以下のとおりです。

* ディメンションを追加するほどメトリクスのカーディナリティが増加する。カーディナリティの高い属性（ユーザーIDやリクエストIDなど）は避ける
* `http.route`（正規化されたURLパス）は `http.url`（完全なURL）よりもカーディナリティが低く、ディメンションとして適している
* `default` を指定すると、属性が存在しないスパンでもメトリクスが生成される

[^spanmetricsconnector]: OpenTelemetry, "Span Metrics Connector", <https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/spanmetricsconnector>

## 統計量復元の数式と計算例

サンプリングされたデータから元の統計量を復元することは、サンプリング導入後の分析精度を維持するために不可欠です。ここでは、サンプリング率に基づく重み付け計算の数式と、具体的な計算例を示します。

### 基本原理: 重み付けによる復元

サンプリングされたデータから母集団の統計量を推定するには、各サンプルにサンプリング率の逆数を重みとして掛けます。サンプリング率 $r$ でサンプリングされたデータの場合、各サンプルは元の $1/r$ 個のデータを代表しています。

#### 合計値の復元

サンプリングされたデータから元の合計値を推定する式は以下のとおりです。

$$
\hat{T} = \sum_{i=1}^{n} \frac{x_i}{r_i}
$$

ここで、$\hat{T}$ は推定合計値、$x_i$ はサンプリングされた $i$ 番目の観測値、$r_i$ はその観測値に適用されたサンプリング率、$n$ はサンプル数です。

均一なサンプリング率 $r$ の場合、これは以下のように簡略化されます。

$$
\hat{T} = \frac{1}{r} \sum_{i=1}^{n} x_i
$$

#### 平均値の復元

重み付き平均の推定式は以下のとおりです。

$$
\hat{\mu} = \frac{\sum_{i=1}^{n} \frac{x_i}{r_i}}{\sum_{i=1}^{n} \frac{1}{r_i}}
$$

均一なサンプリング率の場合、重みが相殺されるため、サンプルの単純平均がそのまま母集団の平均の推定値になります。

$$
\hat{\mu} = \frac{1}{n} \sum_{i=1}^{n} x_i
$$

#### パーセンタイルの復元

パーセンタイルの復元は、合計値や平均値と比べて複雑です。サンプリングされたデータから正確なパーセンタイルを復元するには、各サンプルの重みを考慮した重み付きパーセンタイルを計算します。

手順は以下のとおりです。

1. サンプルを値の昇順にソートする
2. 各サンプルの重み $w_i = 1/r_i$ を計算する
3. 重みの累積和を計算する
4. 累積重みが全体の重みの $p$% に達する点の値が、$p$ パーセンタイルの推定値となる

ただし、サンプル数が少ない場合、パーセンタイルの推定精度は低下します。特にP99のような極端なパーセンタイルでは、サンプリング率が低いと信頼性のある推定が困難になります。このため、パーセンタイルの正確な計算が必要な場合は、サンプリング前の全量データから `spanmetrics` コネクターでヒストグラムメトリクスを生成しておくことが推奨されます。

### 具体的な計算例

あるAPIエンドポイントのレイテンシーデータを10%（$r = 0.1$）でサンプリングした場合の復元計算を示します。

サンプリングで保持された5件のリクエストのレイテンシーが以下のとおりだったとします。

| サンプル | レイテンシー (ms) | サンプリング率 | 重み (1/r) |
| --- | --- | --- | --- |
| 1 | 45 | 0.1 | 10 |
| 2 | 120 | 0.1 | 10 |
| 3 | 80 | 0.1 | 10 |
| 4 | 200 | 0.1 | 10 |
| 5 | 95 | 0.1 | 10 |

#### 合計リクエスト数の復元

サンプルとして5件が保持されたので、元のリクエスト数の推定値は以下のとおりです。

$$
\hat{N} = \frac{5}{0.1} = 50 \text{ 件}
$$

#### レイテンシー合計の復元

$$
\hat{T} = \frac{1}{0.1} \times (45 + 120 + 80 + 200 + 95) = 10 \times 540 = 5{,}400 \text{ ms}
$$

#### 平均レイテンシーの復元

均一なサンプリング率の場合、サンプルの単純平均がそのまま推定値になります。

$$
\hat{\mu} = \frac{45 + 120 + 80 + 200 + 95}{5} = \frac{540}{5} = 108 \text{ ms}
$$

### 動的サンプリング環境での復元

動的サンプリングでは、キーごとにサンプリング率が異なるため、各サンプルの重みも異なります。以下の例では、正常リクエストとエラーリクエストで異なるサンプリング率が適用されています。

| サンプル | レイテンシー (ms) | ステータス | サンプリング率 | 重み (1/r) |
| --- | --- | --- | --- | --- |
| 1 | 45 | 200 | 0.02 | 50 |
| 2 | 120 | 200 | 0.02 | 50 |
| 3 | 80 | 200 | 0.02 | 50 |
| 4 | 500 | 500 | 1.0 | 1 |
| 5 | 95 | 200 | 0.02 | 50 |

この場合の推定リクエスト数は以下のとおりです。

$$
\hat{N} = 50 + 50 + 50 + 1 + 50 = 201 \text{ 件}
$$

重み付き平均レイテンシーは以下のとおりです。

$$
\hat{\mu} = \frac{45 \times 50 + 120 \times 50 + 80 \times 50 + 500 \times 1 + 95 \times 50}{50 + 50 + 50 + 1 + 50} = \frac{17{,}500}{201} \approx 87.1 \text{ ms}
$$

エラーリクエスト（ステータス500）はサンプリング率1.0（全量保持）のため重みが1であり、正常リクエストは2%サンプリングのため重みが50です。この重み付けにより、正常リクエストの寄与が適切に復元されます。

### サンプリング前後の統計量比較

以下の表は、あるサービスの1時間分のデータについて、サンプリング前の実測値とサンプリング後の復元値を比較したものです。

| 統計量 | サンプリング前（実測値） | 10%サンプリング後（復元値） | 誤差 |
| --- | --- | --- | --- |
| 総リクエスト数 | 100,000 | 99,800 | -0.2% |
| 平均レイテンシー | 85 ms | 87 ms | +2.4% |
| P50レイテンシー | 62 ms | 60 ms | -3.2% |
| P95レイテンシー | 245 ms | 252 ms | +2.9% |
| P99レイテンシー | 890 ms | 920 ms | +3.4% |
| エラー率 | 0.5% | 0.48% | -4.0% |

合計値や平均値は比較的正確に復元できますが、P99のような極端なパーセンタイルやエラー率のような低頻度イベントの統計量は、サンプル数の減少により誤差が大きくなる傾向があります。これが、テイルサンプリングでエラートレースを優先的に保持する理由の一つです。

## Four Golden Signals（4つの黄金シグナル）の維持

サンプリング導入下でも、GoogleのSRE Bookで提唱されている **Four Golden Signals（4つの黄金シグナル）**[^sre-book] を正しく監視し続けるにはコツが必要です。ここでは、各シグナルについてサンプリング環境下での対応方法を詳しく解説します。

### レイテンシー (Latency)

レイテンシーは、リクエストの処理にかかった時間を示すシグナルです。サンプリング環境下では、サンプリングされたトレースだけからレイテンシーを計算すると、サンプリングバイアスの影響を受ける可能性があります。

#### 対応方法

レイテンシーの正確な計測には、サンプリング前の全量データから生成したメトリクスを使用します。`spanmetrics` コネクターでヒストグラムメトリクスを生成しておけば、サンプリング率に関係なく正確なレイテンシー分布を把握できます。

サンプリングされたトレースは、レイテンシーの統計量を計算するためではなく、個別のリクエストの詳細な分析（どのスパンがボトルネックか、どのサービス間の呼び出しが遅いか）に使用します。

#### モニタリングクエリ例

```promql
# P50レイテンシー（spanmetricsconnectorで生成したヒストグラムから算出）
histogram_quantile(0.50,
  sum(rate(traces_duration_bucket{service_name="api-gateway"}[5m])) by (le)
)

# P99レイテンシー
histogram_quantile(0.99,
  sum(rate(traces_duration_bucket{service_name="api-gateway"}[5m])) by (le)
)

# エンドポイント別の平均レイテンシー
sum(rate(traces_duration_sum{service_name="api-gateway"}[5m])) by (http_route)
/
sum(rate(traces_duration_count{service_name="api-gateway"}[5m])) by (http_route)
```

### トラフィック (Traffic)

トラフィックは、システムに対するリクエスト量を示すシグナルです。サンプリングされたトレースのみからトラフィック量を把握するには、サンプリング率を考慮した復元が必要です。

#### 対応方法

トラフィック量の把握には2つのアプローチがあります。

1つ目は、`spanmetrics` コネクターで生成したカウンターメトリクスを使用する方法です。サンプリング前の全量データからリクエスト数のカウンターが生成されるため、正確なトラフィック量を把握できます。

2つ目は、サンプリングされたトレースからサンプリング率の逆数を用いて復元する方法です。前節の統計量復元の手法を適用します。

#### モニタリングクエリ例

```promql
# 秒あたりのリクエスト数（spanmetricsconnectorのカウンターから算出）
sum(rate(traces_calls_total{service_name="api-gateway"}[5m]))

# エンドポイント別のリクエスト数
sum(rate(traces_calls_total{service_name="api-gateway"}[5m])) by (http_route)

# ステータスコード別のリクエスト数
sum(rate(traces_calls_total{service_name="api-gateway"}[5m])) by (http_response_status_code)
```

### エラー (Errors)

エラーは、リクエストの失敗率を示すシグナルです。エラーは通常、全トラフィックに対して低い割合で発生するため、サンプリングによる影響を最も受けやすいシグナルです。

#### 対応方法

エラートレースの保持には、テイルサンプリングを活用します。エラーを含むトレースは100%保持するポリシーを設定することで、エラーの詳細な分析に必要なトレースデータを確保します。

エラー率の計算には、`spanmetricsconnector` で生成したメトリクスを使用します。`status.code` ラベルでエラーと成功を区別できるため、正確なエラー率を算出できます。

#### モニタリングクエリ例

```promql
# エラー率（spanmetricsconnectorのカウンターから算出）
sum(rate(traces_calls_total{service_name="api-gateway", status_code="STATUS_CODE_ERROR"}[5m]))
/
sum(rate(traces_calls_total{service_name="api-gateway"}[5m]))

# エンドポイント別のエラー率
sum(rate(traces_calls_total{status_code="STATUS_CODE_ERROR"}[5m])) by (http_route)
/
sum(rate(traces_calls_total[5m])) by (http_route)

# HTTPステータスコード別のエラー数
sum(rate(traces_calls_total{http_response_status_code=~"5.."}[5m])) by (http_response_status_code)
```

### サチュレーション (Saturation)

サチュレーションは、システムのキャパシティに対する使用率を示すシグナルです。CPU使用率、メモリ使用量、コネクション数などのシステムメトリクスで計測します。

#### 対応方法

サチュレーションは、トレースデータではなくシステムメトリクスから計測するため、サンプリングの影響を直接受けません。ただし、サンプリング処理自体がシステムリソースを消費するため、Collector自体のサチュレーションも監視対象に含める必要があります。

特にテイルサンプリングの判定層では、`decision_wait` の間トレースデータをメモリに保持するため、メモリ使用量の監視が重要です。

#### モニタリングクエリ例

```promql
# Collectorのメモリ使用率
process_resident_memory_bytes{job="otel-collector"}
/
node_memory_MemTotal_bytes

# Collectorのスパン受信レート
sum(rate(otelcol_receiver_accepted_spans_total[5m])) by (receiver)

# Collectorのスパンドロップレート（キャパシティ超過の指標）
sum(rate(otelcol_processor_dropped_spans_total[5m])) by (processor)
```

### サンプリング導入前後のダッシュボード設定の違い

サンプリング導入前後で、ダッシュボードのデータソースと計算方法を変更する必要があります。

| シグナル | サンプリング導入前 | サンプリング導入後 |
| --- | --- | --- |
| レイテンシー | トレースバックエンドから直接クエリ | `spanmetrics` コネクターのヒストグラムメトリクスから算出 |
| トラフィック | トレースバックエンドのスパン数をカウント | `spanmetrics` コネクターのカウンターメトリクスから算出 |
| エラー | トレースバックエンドでエラースパンをフィルタ | `spanmetrics` コネクターのカウンターメトリクス（`status_code` ラベル）から算出。詳細分析はテイルサンプリングで保持したトレースを使用 |
| サチュレーション | システムメトリクスから算出 | システムメトリクスから算出（変更なし）。Collectorのリソース使用量を追加で監視 |

サンプリング導入の核心は、統計的な集計（レイテンシーの分布、リクエスト数、エラー率）はサンプリング前の全量メトリクスから算出し、個別のリクエストの詳細分析（ボトルネックの特定、エラーの根本原因調査）にはサンプリングされたトレースを使用するという、メトリクスとトレースの役割分担にあります。

[^sre-book]: Betsy Beyer et al., "Site Reliability Engineering: How Google Runs Production Systems", O'Reilly Media, 2016, Chapter 6 "Monitoring Distributed Systems"

## オブザーバビリティSaaSベンダーのサンプリング機能

ここまで、OpenTelemetry CollectorやHoneycomb Refineryを用いた自前のサンプリング実装について解説してきました。一方で、主要なオブザーバビリティSaaSベンダーは、それぞれ独自のサンプリング機能を提供しています。ここでは、各ベンダーのアプローチと特徴を紹介し、自前実装との使い分けの判断基準を示します。

### AWS X-Ray Sampling Rules

AWS X-Ray[^xray-sampling]は、Reservoir（リザーバー）と固定レートの2段階サンプリングを採用しています。

* **アプローチ**: ヘッドサンプリング（2段階: Reservoir + 固定レート）
* **OpenTelemetry連携**: AWS Distro for OpenTelemetry（ADOT）SDKおよびCollectorがX-Rayのリモートサンプリングルールに対応。SDKがX-Rayサービスからサンプリングルールを定期的に取得し、ローカルでサンプリング判定を行う
* **差別化ポイント**: Reservoirは秒あたりの固定数のトレースを確実に保持し、それを超えるトラフィックには固定レート（例: 5%）を適用する。これにより、低トラフィック時でも一定数のトレースが確保される。サンプリングルールはAWSコンソールやAPIから動的に変更可能で、アプリケーションの再デプロイなしにサンプリング戦略を調整できる
* **簡素化される運用**: サンプリングルールの一元管理（AWSコンソール/API）。アプリケーション側のコード変更なしにサンプリング戦略を変更可能

### Grafana Cloud Adaptive Traces / Adaptive Metrics

Grafana CloudのAdaptive Telemetryスイート[^grafana-adaptive]は、バックエンド側でテレメトリーデータを最適化する機能群です。

* **アプローチ**: バックエンド側テイルサンプリング（Adaptive Traces）、カーディナリティ最適化（Adaptive Metrics）
* **OpenTelemetry連携**: OpenTelemetry CollectorからOTLPでGrafana Cloudに送信し、バックエンド側でサンプリング判定を行う。Collector側でのサンプリング設定は不要
* **差別化ポイント**: エラーや高レイテンシーなどの重要なトレースを自動的に識別して保持する。ユーザーがサンプリングポリシーを細かく設定する必要がなく、バックエンド側で最適化が行われる。Adaptive Metricsはメトリクスのカーディナリティを自動的に最適化し、未使用の時系列を削減する
* **簡素化される運用**: Collector側のサンプリング設定が不要。バッファ管理やスケーリングをバックエンド側で処理

### Honeycomb Refinery

Honeycomb Refinery[^refinery]は、Honeycombが開発・公開しているOSSのテイルサンプリングプロキシです。前節で解説したEMAアルゴリズムを含む複数の動的サンプリング手法を提供します。

* **アプローチ**: テイルサンプリング + 動的サンプリング
* **OpenTelemetry連携**: OTLPを受信し、サンプリング後にHoneycombへ転送する。OpenTelemetry SDKやCollectorからOTLPで送信可能
* **差別化ポイント**: キーフィールドベースの動的サンプリングにより、頻出トラフィックを効率的に削減しつつ、希少なイベント（エラー、異常レイテンシー）を高い確率で保持する。OSSとして公開されているため、Honeycomb以外のバックエンドとも組み合わせ可能
* **簡素化される運用**: テイルサンプリングのバッファ管理、ピア間のトレース分散、動的サンプリング率の自動調整

### Datadog Ingestion Controls

Datadog[^datadog-ingestion]は、SDK側のヘッドサンプリングとバックエンド側のインテリジェントな保持を組み合わせたアプローチを採用しています。

* **アプローチ**: ヘッドサンプリング（SDK/Agent側）+ バックエンド側のインテリジェント保持
* **OpenTelemetry連携**: Datadog AgentがOTLPを受信可能。OpenTelemetry SDKからDatadog Agentに送信し、Agent側でサンプリング判定を行う
* **差別化ポイント**: Datadog Agentがデフォルトで秒あたり一定数のトレースを保持し、エラーやレアなエンドポイントのトレースを自動的に優先保持する。バックエンド側でも追加の保持ロジック（エラートレースの自動保持など）が動作する
* **簡素化される運用**: デフォルト設定で合理的なサンプリングが行われるため、初期設定の負荷が低い。エラートレースの保持ポリシーが組み込み済み

### Dynatrace Adaptive Traffic Management

Dynatrace[^dynatrace-atm]は、OneAgentによる動的サンプリング機能を提供しています。

* **アプローチ**: 動的サンプリング（Agent側）
* **OpenTelemetry連携**: OpenTelemetry SDKからのデータをDynatrace OneAgentまたはActiveGate経由で受信可能。OTLPエンドポイントも提供
* **差別化ポイント**: Adaptive Traffic Managementは、ライセンスに含まれるトレースボリュームに収まるよう、サンプリング率を自動的に調整する。トラフィック量の増減に応じてリアルタイムにサンプリング率が変動し、統計的に有効なデータセットを維持する
* **簡素化される運用**: サンプリング率の手動設定が不要。ライセンスボリュームに基づく自動調整により、コスト超過を防止

### New Relic Infinite Tracing

New Relic[^newrelic-infinite]は、Infinite Tracingとしてバックエンド側のテイルサンプリング機能を提供しています。

* **アプローチ**: バックエンド側テイルサンプリング
* **OpenTelemetry連携**: OpenTelemetry SDKからNew RelicのOTLPエンドポイントに直接送信可能。Infinite Tracingを有効にすると、トレースオブザーバー（Trace Observer）がバックエンド側でテイルサンプリングを実行する
* **差別化ポイント**: トレースオブザーバーがすべてのスパンを受信し、トレース完了後にサンプリング判定を行う。エラーや異常なレイテンシーを含むトレースを優先的に保持する
* **簡素化される運用**: Collector側でのテイルサンプリング設定が不要。バッファ管理とスケーリングをNew Relic側で処理

### Elastic APM Server Tail-based Sampling

Elastic[^elastic-tail]は、APM Server内蔵のテイルサンプリング機能を提供しています。

* **アプローチ**: テイルサンプリング（APM Server内蔵）
* **OpenTelemetry連携**: Elastic Distribution of OpenTelemetry（EDOT）CollectorまたはElastic APM Agentからデータを受信。OTLPプロトコルをサポート
* **差別化ポイント**: APM Server自体にテイルサンプリング機能が内蔵されており、別途サンプリングプロキシを構築する必要がない。サンプリングポリシーはAPM Serverの設定で定義する。複数のAPM Serverインスタンス間でのトレース分散にも対応
* **簡素化される運用**: 既存のElastic APM構成にサンプリング機能を追加するだけで利用可能。別途Collectorやプロキシの構築が不要

### 自前実装 vs ベンダーソリューションの判断基準

OpenTelemetry Collectorによる自前実装と、ベンダーが提供するサンプリングソリューションのどちらを選択するかは、以下の観点で判断します。

#### 自前実装が適するケース

* **マルチベンダー構成**: 複数のバックエンド（例: トレースはJaeger、メトリクスはPrometheus）にデータを送信する場合、ベンダー固有のサンプリング機能は使えない
* **細かいポリシー制御**: サンプリングポリシーを細かくカスタマイズしたい場合（特定の属性値の組み合わせに基づく複雑な条件など）
* **ベンダーロックイン回避**: 特定のベンダーに依存せず、バックエンドを将来的に変更する可能性がある場合
* **コスト最適化**: ベンダーのサンプリング機能が有料オプションの場合、OSSのCollectorで同等の機能を実現できる

#### ベンダーソリューションが適するケース

* **運用工数の削減**: テイルサンプリングの3層構造の構築・運用は複雑であり、バックエンド側で処理してもらえるなら運用負荷が大幅に軽減される
* **マネージドなスケーリング**: トラフィック量の増減に応じたCollectorのスケーリングをベンダー側で処理してもらえる
* **バックエンドとの統合的な最適化**: ベンダーのバックエンドと密に連携したサンプリング（例: クエリパターンに基づく最適化）は、自前実装では実現が難しい
* **迅速な導入**: サンプリングの設計・構築に時間をかけられない場合、ベンダーのデフォルト設定で合理的なサンプリングが得られる

以下の表に、各ベンダーのアプローチを比較します。

| ベンダー | アプローチ | サンプリング実行場所 | OTel連携 | 主な特徴 |
| --- | --- | --- | --- | --- |
| Honeycomb Refinery | テイル + 動的 | プロキシ（OSS） | OTLP受信 | キーベース動的サンプリング、OSS |
| Grafana Cloud | テイル | バックエンド | OTLP送信 | 自動的な重要トレース保持 |
| Datadog | ヘッド + 保持 | Agent + バックエンド | OTLP受信（Agent） | デフォルトで合理的なサンプリング |
| Dynatrace | 動的 | Agent | OTLP受信 | ライセンスボリュームに基づく自動調整 |
| New Relic | テイル | バックエンド | OTLP送信 | トレースオブザーバーによる判定 |
| Elastic | テイル | APM Server | OTLP受信 | APM Server内蔵、追加構築不要 |
| AWS X-Ray | ヘッド（2段階） | SDK/Agent | ADOT SDK/Collector | Reservoir + 固定レート、リモートルール |

[^grafana-adaptive]: Grafana Labs, "Maximize data value and cut costs: Adaptive Telemetry for metrics, logs, traces, and profiles in Grafana Cloud", 2025, <https://grafana.com/blog/2025/10/08/adaptive-telemetry-suite-in-grafana-cloud/>
[^datadog-ingestion]: Datadog, "Ingestion Controls", <https://docs.datadoghq.com/tracing/trace_pipeline/ingestion_controls/>
[^dynatrace-atm]: Dynatrace, "Adaptive Traffic Management concepts", <https://docs.dynatrace.com/docs/ingest-from/dynatrace-oneagent/adaptive-traffic-management/adaptive-traffic-management-concepts>
[^newrelic-infinite]: New Relic, "Infinite Tracing", <https://docs.newrelic.com/docs/distributed-tracing/infinite-tracing/introduction-infinite-tracing/>
[^elastic-tail]: Elastic, "Tail-based sampling", <https://www.elastic.co/guide/en/observability/current/tail-based-samling-config.html>
[^xray-sampling]: AWS, "Configuring sampling rules", <https://docs.aws.amazon.com/xray/latest/devguide/xray-console-sampling.html>

サンプリングは単なるデータ削減手段ではなく、モニタリングのニーズに合わせて「情報の密度」を最適化する戦略なのです。

## まとめ

本章では、固定サンプリング率を超えた高度なサンプリング戦略について解説しました。本章で取り上げた主要な概念とスキルを振り返ります。

**動的サンプリング** では、EMA（指数移動平均）アルゴリズムとHoneycomb Refineryのキーベースサンプリングを取り上げ、トラフィック量の変動に応じてサンプリング率を自動調整する仕組みを示しました。トークンバケットアルゴリズムによるレートリミッティングベースのサンプリングも紹介し、ユースケースに応じた使い分けの指針を提供しました。

**コンテキストベースサンプリング** では、トレースに付与された属性に基づくサンプリング判定の手法を3つの分類で解説しました。リクエストコンテキスト（HTTPメソッド、パス、ステータスコード）、ユーザーコンテキスト（ユーザーID、セッションID、顧客セグメント）、ビジネスコンテキスト（取引金額、重要度フラグ、SLAティア）のそれぞれについて、OpenTelemetry Collectorの `tail_sampling` プロセッサーを使用した具体的な設定例を示しました。

**複数段階サンプリング** では、ヘッドサンプリングとテイルサンプリングを組み合わせることで、テイルサンプリング層のリソース消費を抑えつつ重要なトレースを高精度で保持する手法を解説しました。第1段階（ヘッド）でトラフィックを粗くフィルタリングし、第2段階（テイル）で詳細な判定を行う2層構造のアーキテクチャと、そのパフォーマンス特性・トレードオフを示しました。

**統合サンプリング戦略** では、動的サンプリング、コンテキストベースサンプリング、複数段階サンプリングの3つの手法を組み合わせた実践的な戦略を解説しました。トラフィックパターン、ビジネス要件、コスト制約に基づく戦略選択のガイドラインと、段階的な導入手順を提供しました。

**アグリゲーション** では、`spanmetrics` コネクターを用いてサンプリング前の全量データからメトリクスを生成し、サンプリングによる情報損失を補完する方法を解説しました。

**統計量の復元** では、サンプリング率の逆数を重みとして使用する基本原理と、合計値・平均値・パーセンタイルの具体的な復元計算を示しました。

**Four Golden Signals（4つの黄金シグナル）の維持** では、各シグナルについてサンプリング環境下での対応方法とPromQLクエリ例を提示し、メトリクスとトレースの役割分担を明確にしました。

また、主要な **オブザーバビリティSaaSベンダーのサンプリング機能** を比較し、自前実装との使い分けの判断基準を示しました。

本章を通じて、読者は以下の概念とスキルを習得できます。

* トラフィック変動に追従する動的サンプリングの設計と設定
* ビジネス要件に即したコンテキストベースサンプリングポリシーの設計
* リソース効率を考慮した複数段階サンプリングアーキテクチャの構築
* 複数の手法を統合した実践的なサンプリング戦略の選択と段階的導入
* サンプリング環境下でのメトリクス精度の維持と統計量の復元
* サンプリングパイプラインの運用とトラブルシューティング

次章では、これらの戦略を実際の組織でどのように適用するかを事例として紹介します。Uber、Canva、DoorDashなどの企業がサンプリングをどのように導入し、テレメトリーパイプラインの構成、PII除去の実装方法、運用メトリクスの監視項目など、実運用で必要となる具体的なプラクティスを取り上げます。
