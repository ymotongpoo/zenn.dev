---
title: "GKEのPrometheusメトリクスをOTLPへ寄せていく段階的な移行計画"
emoji: "📊"
type: "tech"
topics: ["OpenTelemetry", "Prometheus", "GoogleCloud", "Kubernetes", "grafana"]
published: false
published_at: 2026-10-15 09:00
---

:::message
一次情報を確認した日付は2026年10月14日です。翻訳戦略のオプションやフィーチャーフラグの名前は変わりうるので、採用前に同じドキュメントを読み直してください。

- Prometheus 3.15.0（2026年9月25日リリース）の [OpenTelemetryバックエンドとしての利用ガイド](https://prometheus.io/docs/guides/opentelemetry/)
- [OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/) と [collector-contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib) v0.162.0（2026年9月29日リリース）
- OpenTelemetry仕様 v1.61.0 の [Prometheus and OpenMetrics Compatibility](https://opentelemetry.io/docs/specs/otel/compatibility/prometheus_and_openmetrics/)
- [Google Cloud Managed Service for Prometheus](https://docs.cloud.google.com/stackdriver/docs/managed-prometheus)、[Grafana Mimir](https://grafana.com/docs/mimir/latest/) 3.2.2

本文中で「実測」と書いた結果は、同じ日にPrometheus 3.15.0、otelcol-contrib 0.162.0、OpenTelemetry Python SDK 1.45.1を手元で動かしたものと、GKE（us-central1-a）上でGoogle Cloud Managed Service for Prometheusへ送ったものです。
:::

## はじめに

以前 [Compute EngineでPrometheus指標を収集する記事](https://zenn.dev/google_cloud_jp/articles/20230203-prom-on-gce)を書いたころは、メトリクスの収集経路を考えるときにOTLPは選択肢に入っていませんでした。いまは [Prometheus](https://prometheus.io/) 自身がOTLPを受け付け、OpenTelemetry Collectorがスクレイプもできるので、[Google Kubernetes Engine](https://cloud.google.com/kubernetes-engine)（GKE）上のメトリクス収集には複数の経路が並んでいます。どちらか一方に置き換える話ではなく、両方が同時に動いている期間をどう設計するかという話になりました。移行の各段階で何が変わり、どこで引き返せるのかを一次情報で整理したのが本記事です。

## TL;DR

Prometheus 3.xとOpenTelemetry Collectorは、スクレイプとOTLPの双方向の変換を規約として持っているので、収集の経路とアプリケーション側の計装は別々のタイミングで移せます。移行で実際に困るのはメトリクス名の変換規則（`otlp.translation_strategy`）、デルタ集計の扱い、そしてスクレイプを廃止した経路で `up` が作られなくなることによる死活監視の書き換えです。`up` が消えるのはスクレイプをやめたときで、CollectorのPrometheusレシーバーでスクレイプを続ける経路では残ります。この3つを段階ごとに確定させてから進めれば、各段階で前の構成へ戻せます。

## いま並んでいる経路

GKE上でメトリクスを集める経路は4つあります。それぞれの入口と出口を確定させておかないと、移行の議論がかみ合いません。

| 経路 | 収集する側 | プロトコル | 出口の例 |
| --- | --- | --- | --- |
| Prometheusがスクレイプ | Prometheusサーバー、またはGoogle Cloud Managed Service for Prometheusのマネージド収集 | HTTPでのスクレイプ | Prometheusのローカルストレージ、Monarch、Mimir |
| Collectorがスクレイプ | Collectorの [Prometheusレシーバー](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/prometheusreceiver) | HTTPでのスクレイプ | OTLP、リモートライト |
| アプリがOTLPで押し込む | OpenTelemetry SDK | OTLP | Collector、Prometheusの `/api/v1/otlp/v1/metrics`、Mimirの `/otlp/v1/metrics` |
| Collectorがリモートライトで押し込む | [Prometheus Remote Writeエクスポーター](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/prometheusremotewriteexporter) | Remote Write 1.0（2.0は開発中） | Mimirの `/api/v1/push`、Managed Service for Prometheus |

Google Cloud Managed Service for Prometheus（以下GMP）は、収集のやり方を4つ提示しています。Kubernetes環境で推奨されているマネージド収集、上流のPrometheusバイナリを差し替える形の自己デプロイ収集、OpenTelemetry Collector、そしてCompute Engine向けのOps Agentです。GMPのドキュメントは自身を「PrometheusとOpenTelemetryのメトリクスのためのフルマネージドな解決策」と位置づけていて、OTLPのメトリクスも受け付けます。OTLPの受け口は [Telemetry API](https://docs.cloud.google.com/stackdriver/docs/otlp/overview)（`telemetry.googleapis.com`）で、届いたメトリクスはCloud MonitoringにPrometheusの時系列として保存され、課金もGMPと同じ「Prometheus Samples Ingested」の単位になります。GKE上でOTLPへ寄せていく場合、収集の器をPrometheusからCollectorへ替えても、出口としてGMPを使い続けられます。

Grafana Mimirも両方を受けます。リモートライトが `POST /api/v1/push`、OTLPが `POST /otlp/v1/metrics` で、どちらもテナントを `X-Scope-OrgID` ヘッダーで指定します。移行の期間中に2つの経路を並行して動かす場合、テナントを分けておくと後段のダッシュボードを切り替えやすくなります。

## メトリクス名がどう変わるか

OTLPとPrometheusのあいだには変換の規約があります。OpenTelemetry仕様の Prometheus and OpenMetrics Compatibility が正となる定義で、OTLPからPrometheusへの向きでは次のように定めています。

名前については、OTLPのメトリクス名がPrometheusのメトリクス名になります。Prometheusの命名規則で推奨されない文字（`.` など）はデフォルトで `_` に置き換えられ、連続する `_` は1つにまとめられます。単調増加するSumには `_total` の接尾辞が付きます（すでに付いている場合を除く）。単位はUCUMからPrometheusの語形へ変換され、`s` は `seconds`、`By` は `bytes` になります。`{packet}` のように波括弧で囲まれた部分は落ちます。単位の接尾辞は型の接尾辞より前に置かれます。

ラベルについては、仕様は計装スコープの名前、バージョン、スキーマURL、スコープ属性を、`otel_scope_name`、`otel_scope_version`、`otel_scope_schema_url`、`otel_scope_<属性名>` としてデフォルトで付けることを求めています。ただしPrometheus 3.15.0のOTLP受信は、後方互換のためにデフォルトではこれらのラベルを生成しません。必要な場合は `otlp.promote_scope_metadata: true` を明示し、ラベルが増えることを移行差分として受け入れます。実測でも、デフォルトの設定では付かず、この設定を有効にすると付きました。リソース属性のうち `service.name` と `service.namespace` は `job` ラベルに、`service.instance.id` は `instance` ラベルになり、残りは `target_info` という情報メトリクスのラベルに移ります。

つまり、OpenTelemetryのセマンティック規約に沿って `http.server.request.duration`（単位 `s`）というメトリクスを出すと、Prometheus側では `http_server_request_duration_seconds` になります。既存のダッシュボードが `http_request_duration_seconds` のような自前の名前を参照している場合、そこは書き換えになります。

Prometheus側は、この変換をどこまで行うかを設定で選べます。`otlp.translation_strategy` に4つの値があり、デフォルトは `UnderscoreEscapingWithSuffixes` です。

- **`UnderscoreEscapingWithSuffixes`**：メトリクス名を従来のPrometheusの命名規則に合わせて完全にエスケープし、型と単位の接尾辞を付ける。デフォルト値
- **`UnderscoreEscapingWithoutSuffixes`**：エスケープは同じだが接尾辞を付けない。Prometheusのドキュメント自身が「いくつもの観点から望ましくなく、接尾辞が無いことでメトリクス名の衝突が起きうる点を利用者は把握しておくべき」として、慎重なテストと合わせてのみ有効にするよう注意しています
- **`NoUTF8EscapingWithSuffixes`**：特殊文字を `_` に変える処理をやめ、OpenTelemetryのメトリクス形式をそのまま使えるようにする。ただし単位や `_total` の接尾辞は衝突を防ぐために付く。UTF-8の有効化が前提
- **`NoTranslation`**：メトリクス名とラベル名の変換をすべて行わず、そのまま通す。UTF-8の有効化が前提で、設定リファレンスでは実験的（EXPERIMENTAL）とされている

Prometheus 3.xはメトリクス名とラベル名のUTF-8をストレージとUIでデフォルトで有効にしていますが、OTLPレシーバーの翻訳戦略はデフォルトのまま古い正規化になっています。移行の途中で `NoTranslation` に切り替えると、その時点から先の系列名が変わります。ダッシュボードとアラートの書き換えが済むまではデフォルトのままにしておく判断になります。

## リソース属性とtarget_info

押し込み型の経路では、Kubernetes上のラベルの扱いが変わります。スクレイプの場合はリラベルでPodやNamespaceの情報をラベルに載せていましたが、OTLPの場合はリソース属性として届き、デフォルトではメトリクスのラベルにはなりません。

Prometheusの動作は次のとおりです。OTLPの書き込みリクエストを処理するとき、リソースに `service.instance.id` または `service.name` が含まれていれば、リソースごとに `target_info` を生成します。`instance` ラベルに `service.instance.id` の値、`job` ラベルに `service.name` の値が入り、`service.namespace` があれば `<service.namespace>/<service.name>` の形で `job` に前置されます。残りのリソース属性は `target_info` のラベルになります。両方が欠けているリソースについては `target_info` が生成されません。

よく使う属性はラベルへ昇格させられます。Prometheusのガイドが推奨の一覧を示しているので、そこから必要なものを選びます。

```yaml
otlp:
  promote_resource_attributes:
    - service.instance.id
    - service.name
    - service.namespace
    - service.version
    - cloud.region
    - k8s.cluster.name
    - k8s.namespace.name
    - k8s.deployment.name
    - k8s.pod.name
  # job と instance へ変換される3つの属性を、target_info にも残す。
  keep_identifying_resource_attributes: true
```

昇格させた属性はメトリクスのラベルになり、`target_info` にも残ります。上の一覧から外した属性、たとえば `deployment.environment.name` は、メトリクスのラベルにはならず `target_info` にだけ入るので、クエリ時に `target_info` と結合して参照します。生の結合クエリでも書けますが、Prometheusのガイドは実験的なPromQL関数 `info` を有効にして使うことを推奨しています。

```bash
prometheus --enable-feature=promql-experimental-functions
```

```promql
info(rate(http_server_request_duration_seconds_count[2m]), {deployment_environment_name=~".+"})
```

生の結合で書くと次のようになります。

```promql
rate(http_server_request_duration_seconds_count[2m])
* on (job, instance) group_left (deployment_environment_name)
target_info
```

ガイドは、生の結合には古い問題があると説明しています。結合に使わないラベル（識別用のラベル以外）の値が入れ替わったとき、古い `target_info` が失効として印を付けられない限り、PromQLの参照の遡り時間（デフォルトで5分）のあいだ新旧2つの `target_info` が重なります。この期間、結合クエリは一致する系列が2つあるために失敗します。`info` 関数は常に最新のサンプルを持つ系列を選ぶので、この問題を避けられます。実測でも、同じインスタンスの `deployment.environment.name` を書き換えて送り直すと、生の結合は `found duplicate series for the match group` のエラーで失敗し、`info` 関数は新しい値を返しました。ラベルの昇格を絞って `target_info` に寄せる設計を採るなら、`info` 関数の有効化を前提にしておく必要があります。

![Grafanaの表で、info関数の結果にtarget_infoから取ったdeployment_environment_nameの列が付き、pod-aとpod-bの2行が並んでいる](/images/20261015-info-target-info.png)

`info` 関数に空文字列と一致しない条件（`=~".+"`）を渡すと、該当する属性を持たないリソースの系列は結果から落ちます。また、サービスによって `service.instance.id` の有無が混ざる構成では、Prometheus 3.14.0までの `info` 関数は一部の `target_info` を取りこぼす不具合があり、3.15.0で修正されました。

## 集計の時間性とヒストグラム

OTLPには累積（cumulative）と差分（delta）の両方の集計の時間性があり、Prometheusは累積が前提です。OpenTelemetry SDKのデフォルトは累積で、環境変数 `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE` のデフォルト値が `cumulative` であることが仕様に書かれています。差分を選ぶ値は `Delta` と `LowMemory` の2つで、前者はCounterと非同期Counterとヒストグラムを差分にし、後者は同期Counterと同期ヒストグラムだけを差分にします。

差分で送られてきたものをPrometheusが受ける場合、Prometheusはcollector-contribの [Delta to Cumulativeプロセッサー](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/deltatocumulativeprocessor)を内部に取り込んでいて、TSDBへ保存する前に累積へ変換します。ただしこの機能は実験的で、フィーチャーフラグ `otlp-deltatocumulative` を有効にして起動する必要があります。フラグを有効にしなければ、Prometheusは差分のメトリクスを保存せずに捨てます。ガイドには「チームはOTLPの差分をより効率的に扱う方法にまだ取り組んでいる」とも書かれています。移行の期間中にわざわざ差分を選ぶ理由は薄く、累積のままにしておくのが素直です。

Collectorのリモートライトエクスポーターを使う場合は、より強い制約があります。READMEに「累積でない単調増加のメトリクス、ヒストグラム、サマリーのOTLPメトリクスは、このエクスポーターによって破棄される」と明記されています。ソースで判定を確かめると、落とされるのは累積でないSum、ヒストグラム、指数ヒストグラムで、ゲージとサマリーは通ります。実測でも、SDKを差分の設定にして送ったカウンターとヒストグラムは届かず、`target_info` だけが届きました。変換の失敗はデバッグレベルのログにしか出ないので、差分で送っていることに気付かないままダッシュボードが空になります。検知するには、Collectorの内部メトリクス `exporter_prometheusremotewrite_failed_translations` を見ます。

ヒストグラムの対応は仕様に定められています。累積の明示的バケットのヒストグラムは、Prometheusの古典的なヒストグラム（明示的な境界と暗黙の `+Inf`）になります。累積の指数ヒストグラムは、Prometheusのネイティブヒストグラム（スキーマ -4 から 8、整数のカウンター種）になります。ただし指数ヒストグラムの変換規則は、仕様上まだDevelopmentの扱いです。

ここから先を「ネイティブヒストグラムは開発中」と一括りにすると、それぞれの現状を混同します。関わる部分を4つに分けます。

- **Prometheus本体のネイティブヒストグラム**：[仕様のページ](https://prometheus.io/docs/specs/native_histograms/)が v3.8.0 以降は安定した機能だとしています。ただしスクレイプで取り込むには `scrape_native_histograms` の設定で明示的に有効にする必要があります
- **カスタムバケットのネイティブヒストグラム（NHCB、スキーマ -53）への変換**：リモートライトエクスポーターの `convert_explicit_histograms_to_nhcb`（デフォルト `false`）で行います。READMEはこのオプションがRemote Write 1.0と2.0のどちらの経路でも動くとしています。仕様のほうはNHCBの出力をRemote Write 2.0以降に限るとしていますが（Development）、実測ではRemote Write 1.0でPrometheus 3.15.0へ送って動きました。併用する `keep_classic_histograms`（デフォルト `false`）は前者が有効なときにだけ効き、古典的な `_bucket`、`_sum`、`_count` の系列をNHCBと並べて出します
- **CollectorのRemote Write 2.0の送信実装**：READMEが「PRW 2.0への対応は現在 In Development で、部分的な実装にとどまるため利用できる状態ではない」と明記しています。メッセージを切り替える `protobuf_message` は、フィーチャーゲート `exporter.prometheusremotewritexporter.enableSendingRW2` を有効にしない限り無視されます
- **受信先の対応**：READMEは、Remote Write 2.0のメッセージを使うにはリモートストレージ側がそれに対応している必要があるとしています

つまり移行の期間中に採れるのは、Remote Write 1.0の経路でNHCBへの変換と古典的な表現の併記を試す形までです。両方を出しておけば、既存の `histogram_quantile` を使ったダッシュボードを動かしたまま、ネイティブヒストグラムのクエリを試せます。実測では、古典的な系列とネイティブヒストグラムのどちらで `histogram_quantile(0.5, ...)` を計算しても同じ値になりました。

なお、既存のダッシュボードが特定のバケット境界に依存している場合、OpenTelemetry SDK側のデフォルトのバケット境界と揃っているかを確認する必要があります。境界が変わると `histogram_quantile` の結果が変わります。SDKのヒストグラムのデフォルトの集計は環境変数 `OTEL_EXPORTER_OTLP_METRICS_DEFAULT_HISTOGRAM_AGGREGATION` で選べ、デフォルト値が `explicit_bucket_histogram`、指数ヒストグラムに切り替える値が `base2_exponential_bucket_histogram` です。

## Collectorにスクレイプを任せる

移行の最初の段階として採りやすいのが、スクレイプの器をPrometheusからCollectorへ替えることです。Prometheusレシーバーは「`scrape_config` におけるPrometheusの設定の全体」に対応していて、サービスディスカバリーとリラベルも含みます。既存の `scrape_config` をほぼそのまま持ち込めるので、この段階でメトリクス名を変える理由はありません。

書き写しで手が入るのは `${...}` の形です。Collectorの設定ファイルは `${VAR}` と `${env:VAR}` を環境変数の参照として展開し、展開のあとで `$$` を `$` 1文字へ戻します。裸の `$VAR` はv0.107.0から展開されなくなったので、リラベルの `replacement: $1` はそのままでも、`$$1` と書いても同じ値になります。一方 `${1}` は名前が `1` の環境変数への参照と解釈され、Collectorは起動時にエラーで止まります。実測でも3通りの書き方がこのとおりの結果になりました。Prometheusの設定で `${1}` を使っている箇所は、`$${1}` へ書き換えるか `$1` の形に直します。レシーバーのREADMEは `$` を一律に `$$` へ書き換えるよう案内していて、それに従っても結果は変わりません。

対応していない項目はエラーになります。`alert_config.alertmanagers`、`alert_config.relabel_configs`、`remote_read`、`remote_write`、`rule_files` の5つです。アラートルールとレコーディングルールはPrometheus側かMimir側に残すことになります。

もう1点、レシーバーは複数のレプリカにまたがってスクレイプを自動で分散できません。同じ設定で複数のレプリカを立てると、手でシャーディングしない限り同じターゲットを何度もスクレイプします。分散が必要なら [OpenTelemetry Operator](https://github.com/open-telemetry/opentelemetry-operator) のTarget Allocatorを使い、レシーバーの `target_allocator` セクションで指し示します。

```yaml
receivers:
  prometheus:
    target_allocator:
      endpoint: http://otel-targetallocator:80
      interval: 30s
      collector_id: ${env:POD_NAME}
```

レシーバーはスクレイプ結果を受けるとき、`target_info` を破棄してその属性をOpenTelemetryのリソースへ移します。メトリクスに付いた `otel_scope_name`、`otel_scope_version`、`otel_scope_schema_url` のラベルはスコープの名前、バージョン、スキーマURLへ移り、それ以外の `otel_scope_` で始まるラベルは接頭辞を外してスコープ属性になります。一方で `otel_scope_info` メトリクスは特別扱いされず、ほかのメトリクスと同じように変換されて下流へ流れます。この挙動はv0.156.0からデフォルトになり、v0.162.0で元に戻せなくなりました。つまり、いったんOTLPへ変換してからまたPrometheusへ戻す経路では、リソース属性とスコープの名前とバージョンは往復して保たれますが、ターゲットが `otel_scope_info` を出していれば、その系列は出口にもそのまま現れます。スキーマURLはリモートライトのエクスポーターがラベルに戻さないので、往復しません。

出口をリモートライトにしておけば、この段階では既存のダッシュボードとアラートを書き換えずに済みます。ただしこれは、スクレイプで得た名前とラベルと型が、OTLPへの変換とリモートライトへの変換を往復して同じ形で出ていく場合に限った話です。実測では、scope metadataを有効にした場合の `otel_scope_*` ラベル、`target_info` 由来の属性、明示的バケットの `le="1.0"` と `le="1"` のような表記差が完全一致の比較を不合格にしました。出口の `translation_strategy` は名前の正規化と接尾辞の追加を行うので、たとえば `_total` を持たないCounterには接尾辞が付きえます。リソースとスコープの情報の扱いも変換の対象です。名前が変わらない見込みを前提にせず、変換の前後で系列を比べて確認します。この確認を段階1の通過条件として次の節に置きます。比べるときはCollectorの版を固定します。v0.162.0では、`_` で始まるラベル名に `key_` を前置しなくなる変更（PermissiveLabelSanitization）がデフォルトで有効になり、バケットの数え方が壊れた古典的ヒストグラムを捨てるようになりました。版を上げるだけで、ラベル名や系列の有無が変わりえます。

エクスポーターの名前は、v0.154.0で `prometheusremotewrite` から `prometheus_remote_write` に変わりました。古い名前も別名として使えますが、起動時に非推奨の警告が出ます。送信先の `endpoint` と `headers` も、v0.158.0から `http` ブロックの下に書く形が推奨です。

```yaml
exporters:
  prometheus_remote_write:
    http:
      endpoint: https://mimir.example.com/api/v1/push
      headers:
        X-Scope-OrgID: production
    # 既存の名前と揃える。移行が済むまでデフォルトのままにする。
    translation_strategy: UnderscoreEscapingWithSuffixes
    target_info:
      enabled: true
    send_metadata: true
    remote_write_queue:
      queue_size: 10000
      num_consumers: 5
```

GMPを出口にする場合は [Google Managed Prometheusエクスポーター](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/googlemanagedprometheusexporter)を使います。メトリクスについて Beta の安定度で、`prometheus_target` というモニタリング対象リソースへマッピングします。リソースのラベルになる `location`、`cluster`、`namespace`、`job`、`instance`、`project_id` は予約されていて、READMEはこれらをメトリクスのラベルとして持つ系列は `exported_` を前置しないと拒否されると説明しています。ただし実測では、`namespace` ラベルを持つ系列は拒否されず、メトリクスのラベル `namespace` として保存されました。GMPのPromQLのAPIでは、リソースの `namespace` と区別するために `metric_namespace` という名前で見えます。どちらの扱いになっても、既存のダッシュボードが参照するラベル名とはずれるので、アプリケーション側で予約ラベルを使っているなら、移す前にリラベルで名前を変えておきます。また、Collectorの経路では `k8s.namespace.name` のリソース属性を付けないと、リソースの `namespace` が空になります。

加えて、同じメトリクスをINTとDOUBLEの両方で書き込むとエラーになるので、衝突を避けるためにすべてDOUBLEへ変換するフィーチャーゲート `exporter.googlemanagedprometheus.intToDouble` が用意されています。この衝突は、前に書いた `otel_scope_info` の変更と組み合わさって起きます。エクスポーターはデフォルト（`extra_metrics_config.enable_scope_info: true`）でINTの `otel_scope_info` を自分で生成します。そこへ、スクレイプ先が出したDOUBLEの `otel_scope_info` がレシーバーから素通しで届くと、実測では `inconsistent value types specified for metric` のエラーで書き込みの一部が失敗しました。フィーチャーゲートを有効にすると解消しました。

```bash
otelcol-contrib --config=config.yaml --feature-gates=exporter.googlemanagedprometheus.intToDouble
```

出口をGMPのエクスポーターではなくTelemetry APIにして、OTLPのまま送ることもできます。この場合は、開始時刻の扱いに注意が要ります。Prometheusレシーバーはv0.142.0から累積の系列の開始時刻を補わなくなり、その役割は [Metric Start Timeプロセッサー](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/metricstarttimeprocessor)に移りました。Telemetry APIは開始時刻の無い累積の系列を `metric kind CUMULATIVE must specify start time` として拒否するので、実測ではカウンターがすべて届きませんでした。プロセッサーを入れると、最初の1点だけが拒否され、以後の点は届きました。GMPのエクスポーターの経路は、プロセッサーを入れなくても届きました。

実測で使った設定のうち、Telemetry APIへ送る部分は次のとおりです。

```yaml
extensions:
  googleclientauth: {}
processors:
  metric_start_time:
    strategy: true_reset_point
  resource_detection:
    detectors: [gcp]
  resource/gcp:
    attributes:
      - {key: gcp.project_id, value: PROJECT_ID, action: upsert}
      - {key: k8s.namespace.name, value: "${env:POD_NAMESPACE}", action: upsert}
  batch: {}
exporters:
  otlp_http/telemetry:
    endpoint: https://telemetry.googleapis.com
    encoding: proto
    auth:
      authenticator: googleclientauth
service:
  extensions: [googleclientauth]
  pipelines:
    metrics:
      receivers: [prometheus]
      processors: [metric_start_time, resource_detection, resource/gcp, batch]
      exporters: [otlp_http/telemetry]
```

`POD_NAMESPACE` はDownward APIでPodのNamespaceを渡す環境変数です。認証は、`googleclientauth` がノードのサービスアカウントの認証情報を使いました（このクラスターはWorkload Identityを有効にしていません）。Workload Identityを有効にしたクラスターでは、Kubernetesのサービスアカウントに書き込みの権限を付ける必要があります。

GKE上で同じアプリケーションを3つの経路で収集し、GMPで並べたのが次の画像です。`pm` がマネージド収集、`col-gmp` がCollectorとGMPのエクスポーター、`col-otlp` がCollectorとTelemetry APIの経路で、同じメトリクス名と値の系列が同じ場所に入っています。

![Cloud MonitoringのMetrics Explorerの表で、temperature_celsiusをjobごとに集計した3行が並び、いずれも値が21.5になっている](/images/20261015-gmp-three-paths.png)

ただし3つの経路は、名前もラベルも同じになるわけではありません。実測では、`_total` の付いていないCounterは、マネージド収集では元の名前のまま、GMPのエクスポーターの経路では `_total` 付きの名前になりました。またTelemetry APIの経路では `target_info` のラベル名がドットを含んだまま（`cloud.account.id`）保存されました。経路を替えるときも、段階1と同じように系列を比べて確かめます。

## OTLPの経路を並行して立てる

次の段階で、アプリケーションからOTLPで押し込む経路を追加します。Prometheusを直接の受け口にするなら、OTLPレシーバーの有効化が必要です。デフォルトでは無効で、Prometheusのガイドは「Prometheusは認証なしでも動作しうるので、明示的に設定しない限り受信トラフィックを受け付けるのは安全ではない」という理由を挙げています。

```bash
prometheus --web.enable-otlp-receiver
```

有効にすると `/api/v1/otlp/v1/metrics` のパスでOTLPのメトリクスを受けます。SDK側は、このパスと噛み合う形で送信先を指定する必要があります。ここで環境変数を混同すると送信がすべて失敗するので、仕様の定めを確認しておきます。

OTLPエクスポーターの仕様では、シグナル共通の `OTEL_EXPORTER_OTLP_ENDPOINT` を指定した場合だけベースURLとして扱われ、シグナルごとのパス（メトリクスなら `v1/metrics`）が後ろに付きます。シグナル固有の `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` については「そのURLを加工せずそのまま使わなければならない」と定めているので、パスの補完は行われません。つまり後者にベースURLを渡すと、SDKは `/api/v1/otlp` へ直接POSTしようとして、Prometheusの受信パスには届きません。

共通の環境変数を使うなら、ベースURLを渡します。

```bash
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=http://prometheus:9090/api/v1/otlp
export OTEL_METRIC_EXPORT_INTERVAL=15000
export OTEL_SERVICE_NAME=checkout
export OTEL_RESOURCE_ATTRIBUTES="service.instance.id=$(uuidgen)"
```

トレースとメトリクスで送信先が違うなどの理由でシグナル固有の環境変数を使うなら、`/v1/metrics` まで含めた完全なURLを渡します。

```bash
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://prometheus:9090/api/v1/otlp/v1/metrics
```

Prometheusのガイドは、シグナル固有の環境変数にベースURLを渡す例を載せたうえで、仕様がこのエンドポイントをベースURLとして扱ってシグナルのパスを付けると説明しています。エクスポーターの仕様の記述と食い違っているので、ガイドの例をそのまま写さずに上のどちらかの形にします。

設定したら、ダッシュボードに系列が現れるのを待つ前に到達を確かめます。系列の有無だけを見る方法では、送信の失敗と計装そのものの漏れを区別できません。Prometheus側のアクセスログで `/api/v1/otlp/v1/metrics` へのPOSTに 200 が返っているかを見るか、アプリケーション側でエクスポーターが出すエラーログを確認します。

`OTEL_METRIC_EXPORT_INTERVAL` を指定しているのは、OpenTelemetryの押し込みのデフォルトが60秒で、Prometheusのスクレイプ間隔として一般的な15秒や30秒と噛み合わないためです。ガイドも15秒への変更例を載せています。

`service.instance.id` は、`service.namespace` と `service.name` との3つ組で一意でなければなりません。[セマンティック規約](https://opentelemetry.io/docs/specs/semconv/registry/attributes/service/)はランダムなUUID（v1またはv4）の生成を推奨し、安定した値が欲しい場合は固有のIDからUUIDv5を作る方法も認めています。Prometheusのガイドはさらに、リソース属性が変わるたびに新しい値を生成すること、具体的にはインスタンスの起動ごとに新しいUUIDを生成することを求めています。Kubernetesについては、規約の非規範のガイドが、Podのアノテーション `resource.opentelemetry.io/service.instance.id`、それが無ければ `<k8s.namespace.name>.<k8s.pod.name>.<k8s.container.name>` を使う方法を示しています。

Collectorのレプリカを複数立ててPrometheusへ押し込む場合、順序の前後が起きます。ガイドは「OpenTelemetry Collectorはバッチ処理を推奨していて、複数のレプリカがPrometheusへ送ることがありうる。それらのサンプルを順序付ける仕組みが無いので、順序が前後しうる」と説明し、順不同の取り込みを有効にすることを挙げています。

```yaml
storage:
  tsdb:
    out_of_order_time_window: 30m
```

ガイドは「ほとんどの場合30分の順不同で足りているが、必要に応じて調整してほしい」としています。

## ダッシュボードとアラートの書き換え

書き換えが必要になるものを分けて考えます。

メトリクス名が確実に変わるのは、アプリケーション側の計装をPrometheusのクライアントライブラリからOpenTelemetry SDKへ移したときです。収集の器をCollectorへ替えただけの段階では、名前が変わらない見込みを前提にはできません。既存の命名規則とラベルと型が、OTLPへの変換とリモートライトへの変換を往復して同じ形で出ていくことを確かめたときに限り、書き換えずに済みます。この確認は段階1の通過条件として次の節に置いています。そのうえで名前が変わる範囲を確定させ、その範囲だけをレコーディングルールで受けるやり方が取れます。旧名を新名から導出するルールを置いておけば、ダッシュボードを一斉に書き換えずに済みます。移行が完了したらルールを外します。

死活監視は、経路によって書き換えが要るかどうかが変わります。Prometheusは各スクレイプに対して `up{job="...", instance="..."}` を自動生成し、成功なら `1`、失敗なら `0` を入れます。ドキュメントは「`up` の時系列はインスタンスの可用性の監視に有用である」としています。この系列を作るのはスクレイプなので、生成されるかどうかを決めるのは送信プロトコルではなくスクレイプの有無です。

前に挙げた4つの経路のうち、CollectorのPrometheusレシーバーでスクレイプする経路にはスクレイプがあります。レシーバーはスクレイプのメタデータのメトリクスを生成して下流へ流すので、`up` や `scrape_duration_seconds` はOTLPへ変換したあとも残ります。この経路では既存の `up` のアラートを書き換える必要がありません。ただし名前とラベルが往復の変換を通ったあとで同じ形になっているかは、次の節に挙げる段階1の通過条件として確認します。

`up` が無くなるのは、アプリケーションがSDKから直接OTLPで押し込み、そのターゲットへのスクレイプを廃止した場合です。この構成では、押し込みが止まったことを別の形で検知します。

```promql
# スクレイプが残っている経路
up{job="checkout"} == 0

# SDKから直接押し込む経路。job 単位で系列が全て絶えたときだけ発火する
absent_over_time(http_server_request_duration_seconds_count{job="checkout"}[5m])
```

この2つは同じものを検知しません。`absent_over_time` は、渡した範囲ベクトルに要素が1つも無いときだけ値 `1` の1要素を返す関数です。`job="checkout"` のPodが10個あって1個だけ止まっても、残りの9個が系列を送っている限り入力は空にならないので、このアラートは発火しません。検知できるのは、そのラベルの組み合わせに一致する系列がサービス全体で絶えた場合だけです。2つのインスタンスからOTLPで送り、1つずつ止めた実測が次の画像です。`pod-b` を11時4分ごろに止めても `absent_over_time` は値を返さず、`pod-a` も11時7分ごろに止めてから約5分後に、初めて値 `1` を返しました。

![上のパネルでpod-aとpod-bの送信レートが順に0へ落ち、下のパネルのabsent_over_timeはpod-bが止まった時点では空のまま、pod-aが止まった約5分後から値1になっている](/images/20261015-absent-over-time.png)

さらに、ここで使っているのがリクエスト数のメトリクスである点にも制約があります。`http_server_request_duration_seconds_count` はリクエストが来て初めて作られるので、夜間や初回リクエストの前には系列が存在しません。障害ではないのに発火する一方、この時間帯を評価の対象から外すと、その間に本当に止まった場合を見逃します。死活監視に使うメトリクスは、トラフィックに依存せず一定の間隔で出続けるものを選びます。プロセスの稼働時間のように、リクエストが無くても値が更新されるものが該当します。

個別のPodが止まったことを検知するには、別の仕組みが要ります。1つは、`service.instance.id` を `instance` ラベルへ昇格させたうえで、期待するPodの一覧とハートビートの系列を比べる形です。もう1つは、Kubernetes側の監視を一次の切り分けに使う形で、Liveness ProbeとPodの再起動回数、[kube-state-metrics](https://github.com/kubernetes/kube-state-metrics) が出すレプリカ数の差が材料になります。どちらも `absent_over_time` の式とは別に用意するもので、押し込み経路へ移したからといって不要になるわけではありません。

評価の窓は押し込みの間隔より十分に長く取ります。`OTEL_METRIC_EXPORT_INTERVAL` を15秒にしている場合、5分の窓は20回ぶんの送信が連続して欠けた状態にあたります。実際の値は、どれだけ早く気付きたいかと、一時的な送信失敗で発火させたくないかの兼ね合いで決めます。

もう1つ、Collectorを経路に挟むと、Collector自身の健全性が監視対象に加わります。Collectorが落ちればメトリクスは届かないため、上の `absent_over_time` のアラートはCollectorの障害でも発火すると考えられます（押し込み経路とアラート条件の関係からの推論です）。切り分けのために、Collector自身が出す内部メトリクスを別のアラートにしておく必要があります。

## 段階と引き返し方

以上を移行の段階として並べます。各段階で、次へ進まずに前へ戻せることを確認してから進めます。

| 段階 | やること | 名前の変化 | 引き返し方 |
| --- | --- | --- | --- |
| 0 | 棚卸し。どのメトリクスがどのダッシュボードとアラートから参照されているかを一覧にする | なし | 該当なし |
| 1 | スクレイプをCollectorへ移す。出口はリモートライトのまま | 変わらないことを確認する | Prometheusのスクレイプ設定を戻す |
| 2 | OTLPの受け口を並行して立てる。テナントまたはラベルで区別する | なし（既存の経路は不変） | OTLPの受け口を止める |
| 3 | サービス単位で計装をOpenTelemetry SDKへ移す。旧名を導出するレコーディングルールを置く | 変わる。ルールで吸収 | 該当サービスの計装を戻す |
| 4 | 死活監視を書き換える。スクレイプを廃止したサービスだけを対象にする | なし | 旧いスクレイプ設定とアラート定義を一組で退避しておく |
| 5 | 翻訳戦略を決める。`NoTranslation` へ寄せるなら全ダッシュボードの書き換え後 | 変わる | 翻訳戦略をデフォルトへ戻す |
| 6 | レコーディングルールと旧経路を外す | なし | 旧経路の設定をリポジトリに残しておく |

段階1の通過条件は、名前とラベルと型が変わっていないことを機械的に確かめることです。移行の前後で同じ時間帯を切り出し、対象のジョブについて4つを比べます。系列名の一覧、ラベル名とラベル値の集合、メトリクスの型、そしてダッシュボードとアラートで使っている主要なPromQLの結果です。名前の一覧は `count by (__name__) ({job="checkout"})` のような形で取り、前後の差分が空になることを確認します。差分が出たら、出口の `translation_strategy` と昇格させるリソース属性の設定で吸収できるかを先に調べ、吸収できない分だけをダッシュボードの書き換えに回します。リモートライトのエクスポーターで選べる翻訳戦略は、Remote Write 1.0のあいだは `UnderscoreEscapingWithSuffixes` と `UnderscoreEscapingWithoutSuffixes` の2つです。`NoUTF8EscapingWithSuffixes` と `NoTranslation` はRemote Write 2.0を前提にしていて、1.0のまま指定するとCollectorは起動時にエラーで止まります。

段階4の引き返し方を「旧いアラートを並行して評価する」にしていないのは、段階3でSDKへ移したサービスはスクレイプが止まっていて `up` の系列そのものが無くなっているためです。存在しない系列に対する `up{job="..."} == 0` は評価できないので、並行評価は成立しません。旧いスクレイプの設定とアラート定義を一組で退避しておき、戻すときは両方を同時に戻します。

段階3をサービス単位にしているのは、名前の変化がサービスごとに閉じるようにするためです。全サービスを一度に移すと、どのダッシュボードが動かなくなったのかを特定できなくなります。

段階5を最後に置いているのは、翻訳戦略の変更がクラスター全体の系列名に影響するためです。`NoTranslation` にすると `http.server.request.duration` のようなドット入りの名前がそのまま入り、PromQLでは名前を引用符で囲んで中括弧の中に入れる記法（`{"http.server.request.duration"}`）で参照することになります。移行の途中でこれを切り替える理由はほとんどありません。

## おわりに

PrometheusとOpenTelemetryのメトリクスは、置き換えではなく並行運用が前提の作りになっていることを確認しました。だからこそ、収集の器を替える段階とアプリケーション側の計装を替える段階を分けられます。

ヒストグラムの周辺は、層ごとに成熟度が違うことを確認しました。Prometheus本体のネイティブヒストグラムは v3.8.0 以降 Stable として扱われる一方、CollectorのRemote Write 2.0の送信実装はREADME上 In Development で利用できる状態にありません。NHCBへの変換はRemote Write 1.0の経路でも動くエクスポーターのオプションとして提供されていて、これらとはまた別の位置にあります。受信先がRemote Write 2.0のメッセージに対応しているかは、そのどれとも独立に確認する項目です。

当面は累積とRemote Write 1.0を前提に組み、差分の取り込みは本番の外で試し、ネイティブヒストグラムはNHCBへの変換と古典的な表現の併記を有効にしたうえで移行の対象に入れる、という認識で良さそうです。Remote Write 2.0への切り替えだけは、送信実装が利用できる状態になるまで待つ判断になります。

## 出典

- [Using Prometheus as your OpenTelemetry backend](https://prometheus.io/docs/guides/opentelemetry/)
- [Prometheus and OpenMetrics Compatibility](https://opentelemetry.io/docs/specs/otel/compatibility/prometheus_and_openmetrics/)
- [OTLP Metric Exporter - OpenTelemetry Specification](https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/metrics/sdk_exporters/otlp.md)
- [Prometheus Remote Write Exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/prometheusremotewriteexporter)
- [Prometheus Receiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/prometheusreceiver)
- [Google Managed Prometheus Exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/googlemanagedprometheusexporter)
- [Metric Start Time Processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/metricstarttimeprocessor)
- [OTLP support in Google Cloud Observability](https://docs.cloud.google.com/stackdriver/docs/otlp/overview)
- [Service attributes - OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/registry/attributes/service/)
- [Jobs and instances - Prometheus](https://prometheus.io/docs/concepts/jobs_instances/)
