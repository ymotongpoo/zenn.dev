# 2026-10-14 GKE Prometheus→OTLP記事の検証結果

対象記事: [`articles/20261015-gke-prometheus-to-otlp-metrics.md`](../articles/20261015-gke-prometheus-to-otlp-metrics.md)

`reviews/20260922-cloud-verification-plan.md` のGケースとG-S番号を引き継ぎ、新しいケースはG-11から番号を振りました。9月22日以降に Prometheus 3.15.0（9月25日）、collector-contrib v0.162.0（9月29日）、Mimir 3.2.2（10月7日）が出たので、版に依存するケースをローカルで再実行し、GMPに依存するケースを共有のGoogle Cloudのデモ用プロジェクトで実施しました。同日、下の発見と一次資料の再確認の結果を記事本文に反映し、G-S2′、G-S3′、G-S6′ の画像を差し込みました。非公開の記録は `~/audit-work/1015-gke-otlp/` にあります（台帳 `resources.json`、コマンドの記録 `commands.jsonl`、結果 `cases/`、証拠 `evidence/` と `work/`）。

使った版は次のとおりです。いずれも公式リリースを取得し、チェックサムを照合しました。

| 対象 | 版 |
| --- | --- |
| Prometheus | 3.15.0（darwin-arm64） |
| OpenTelemetry Collector Contrib | 0.162.0（ローカルは darwin_arm64、クラスターは `ghcr.io` のイメージをダイジェストで固定） |
| OpenTelemetry Python SDK | 1.45.1（`opentelemetry-exporter-otlp-proto-http` 1.45.1） |
| Grafana | 13.2.4（撮影用、ローカル） |
| GKE | デモ用プロジェクトの共有クラスター（us-central1-a、1.35.8-gke.1380001）の自分の Namespace |

## 結果

| Case | 判定 | 環境 | 原稿の節・行 | 実測・確認結果 |
| --- | --- | --- | --- | --- |
| G-02 | PASS | LOCAL | メトリクス名、リソース属性とtarget_info（46–103行） | 翻訳戦略の4つの値は設定として受理され、不正な値は拒否された。scopeのラベルはデフォルトで付かず、`promote_scope_metadata: true` で付いた。`job` は `shop/checkout`、単位 `{order}` は落ちて `_total` が付いた。昇格させていない属性を変えると、生の結合は `found duplicate series` で失敗し、`info()` は最新の値を返した。昇格させた属性はメトリクスにも `target_info` にも残る |
| G-03 | FAIL | LOCAL | Collectorにスクレイプを任せる（145–147行） | 147行目の差分（受信側のscopeラベルの付与、`target_info` への `server_port` と `url_scheme` の追加、`le="1.0"` が `"1"` になる、`legacy_jobs` が `legacy_jobs_total` になる）は再現した。145行目は不一致で、`otel_scope_info` は特別扱いされず、普通の系列として出口に出た |
| G-05 | PASS | LOCAL | 集計の時間性とヒストグラム（111–122行） | デルタで送ったカウンターとヒストグラムは、リモートライトのエクスポーターで落とされた（infoレベルのログは出ない）。Remote Write 1.0 で、NHCBと古典的な `_bucket`、`_sum`、`_count` が併存し、`histogram_quantile(0.5)` はどちらも 2.5 |
| G-06 | FAIL | LOCAL | Collectorにスクレイプを任せる（130–132行） | 未対応の5項目はすべて `unsupported features` として拒否された（132行目PASS）。130行目は不一致で、リラベルの `replacement: '$1'` と `'$$1'` は同じ値になり、`'${1}'` だけが環境変数の参照として起動に失敗した |
| G-07 | PASS | CLOUD | いま並んでいる経路（38行） | `PodMonitoring` のマネージド収集で、合成のメトリクスが `namespace`、`pod`、`container`、`top_level_controller_*` 付きでGMPに入った |
| G-11 | PASS | CLOUD | 38、165行 | Prometheusレシーバーと `googlemanagedprometheus` エクスポーターの経路でも、同じメトリクス名で `prometheus_target` に入った。ただし `legacy_jobs` は `legacy_jobs_total` になり、`k8s.namespace.name` を付けないと `namespace` が空になる |
| G-12 | FAIL | CLOUD | 165行 | 予約ラベル `namespace` を持つ系列は拒否されず、メトリクスのラベル `namespace` として保存された（リソースの `namespace` が空でも設定済みでも同じ）。PromQLのAPIでは `metric_namespace` として見える。INTとDOUBLEの衝突は実際に起き、`exporter.googlemanagedprometheus.intToDouble` で解消した（この部分はPASS） |
| G-13 | PASS | CLOUD | 38行 | `otlp_http` と `googleclientauth` で Telemetry API（`telemetry.googleapis.com`）へ送った系列が、`prometheus.googleapis.com` の系列として取得できた。ただし `metric_start_time` プロセッサーを入れないと、累積の系列が開始時刻なしとして拒否される |

記事に設定例を載せたあと、ユーザーの指示で G-13b を追加しました（run `1015-telemetry-min`）。

| Case | 判定 | 環境 | 原稿の節 | 実測・確認結果 |
| --- | --- | --- | --- | --- |
| G-13b | PASS | CLOUD | Telemetry API の設定例 | 設定例から `gcp.project_id` とリソース検出を外すと動かないことを確かめた。どちらも無し、またはリソース検出だけでは `Resource is missing required attribute "gcp.project_id"`、`gcp.project_id` だけでは `Unrecognized region or location` で、すべての点が拒否された。`gcp.project_id` と手で付けた `cloud.region` の組み合わせなら届き、`location` は `us-central1`、`cluster` は空になった |

G-01、G-04、G-09、G-10は9月22日の結果を引き継ぎ、今回は再実行していません。G-08（一次資料）は下の「一次資料の再確認」で置き換えます。

## 原稿に関係する発見

1. **`otel_scope_info` は素通しになった（145行目）。** v0.162.0 のレシーバーのREADMEは「The `otel_scope_info` metric is not treated specially and is converted like any other metric.」としています。フィーチャーゲート `receiver.prometheusreceiver.IgnoreScopeInfoMetric` は v0.156.0 で beta になってデフォルトで有効になり、v0.162.0 で stable になって無効にできなくなりました。v0.161.0 のREADMEは古い記述のままだったので、9月22日の確認では見落としていました。
2. **`$` の書き換えが必要なのは `${...}` の形だけ（130行目）。** collector の confmap は v0.107.0 から裸の `$VAR` を展開しません。READMEは今も `$` を `$$` へ書き換えるよう案内していますが、それに従わなくても `$1` は動きます。
3. **設定例のコンポーネント名と書き方が非推奨（149–163行目）。** `prometheusremotewrite` は v0.154.0 から非推奨の別名で、起動時に警告が出ます（新しい名前は `prometheus_remote_write`）。トップレベルの `endpoint` と `headers` も v0.158.0 から非推奨で、`http:` ブロックの下に書きます。クラスターでは `resourcedetection` も非推奨の別名だと警告されました。
4. **クエリの例が、昇格済みの属性を結合している（85–101行目）。** 昇格した `k8s.cluster.name` はメトリクスのラベルにもなるので、「昇格させなかった属性は `target_info` と結合して参照する」という説明の例になっていません。`deployment_environment_name` のように、昇格させていない属性に替える必要があります。
5. **Collectorでスクレイプして OTLP で GMP に送るには、開始時刻を補う必要がある。** レシーバーは v0.142.0 から開始時刻を補わなくなり（`metricstarttime` プロセッサーへ移した）、Telemetry API は累積の系列に開始時刻がないと `metric kind CUMULATIVE must specify start time` で拒否します。`metric_start_time`（`true_reset_point`）を入れると、最初の1点だけが拒否され、以後は届きました。GMPエクスポーターの経路では、プロセッサーなしでも届きました。
6. **GMPエクスポーターが生成する `otel_scope_info` と、スクレイプされた `otel_scope_info` がぶつかる。** エクスポーターはデフォルト（`extra_metrics_config.enable_scope_info: true`）で INT の `otel_scope_info` を生成します。発見1で素通しになったスクレイプ側の DOUBLE の `otel_scope_info` が同じ名前で届き、`inconsistent value types specified for metric` で書き込みが部分的に失敗しました。165行目のフィーチャーゲート `intToDouble` を有効にすると解消しました。
7. **予約ラベルは拒否されなかった（165行目）。** 発見の範囲は、2026年10月14日、contrib v0.162.0（opentelemetry-operations-go v0.62.0）、us-central1-a のゾーンクラスターです。READMEの記述（「will be rejected」）と実測が食い違っています。
8. **Telemetry API の経路では、`target_info` のラベル名がドットのまま保存される。** `cloud.account.id` のように、GMPエクスポーターの経路（`cloud_account_id`）とは名前が違いました。

## 一次資料の再確認

確認日は2026年10月14日です。Prometheus のガイドは prometheus/docs のコミット `87b389880d`（2026-04-01 が最終変更）、設定リファレンスは prometheus/prometheus の v3.15.0、collector-contrib は v0.162.0、Operator は v0.161.0、OpenTelemetry 仕様は v1.61.0、セマンティック規約は v1.44.0、Mimir は mimir-3.2.2 に固定しました。GMPのドキュメントは版を固定できないので、2026-10-09 UTC の最終更新を記録しています。

| 行 | 判定 | 内容 |
| --- | --- | --- |
| 11, 13, 14, 16 | 要更新 | 確認日と版。Prometheus 3.15.0（2026年9月25日）、collector-contrib v0.162.0（2026年9月29日）、Mimir 3.2.2（2026年10月7日） |
| 36 | 補足 | Remote Write 2.0 の送信はREADME上「In Development」 |
| 38 | 補足 | GMP は Telemetry API で OTLP を受け、Prometheus の時系列として保存する。課金はGMPと同じ「Prometheus Samples Ingested」 |
| 46 | 補足 | 推奨されない文字は `_` に置き換わり、連続する `_` は1つになる（「そのまま」は不正確） |
| 48 | 補足 | 仕様はscopeのラベル（スコープ属性を含む）をデフォルトで付けることを求めている。Prometheus は互換性のためにデフォルトで無効 |
| 57 | 補足 | 設定リファレンスは `NoTranslation` を EXPERIMENTAL としている |
| 109 | 要修正 | 原文は「The team is still working on a more efficient way of handling OTLP deltas.」。フラグがなければ Prometheus の OTLP 受信もデルタを捨てる |
| 111 | 補足 | ゲージとサマリーは通り、累積でないSum、ヒストグラム、指数ヒストグラムが落ちる。検知は `exporter_prometheusremotewrite_failed_translations` |
| 113 | 補足 | 指数ヒストグラムの変換規則は仕様上 Development |
| 118 | 一致 | READMEは Remote Write 1.0 と 2.0 の両方で動くとし、実測でも 1.0 で動いた（G-05）。仕様（Development）は NHCB の出力を 2.0 以降に限るとしている |
| 195 | 一致 | Prometheus のガイドは今も、シグナル固有の環境変数にベースURLを渡す例を載せている |
| 201 | 要修正 | 「リソース属性が変わるたびに生成」「起動ごとにUUID」は Prometheus のガイドの記述。規約が推奨するのは UUID v1 か v4 で、固有のIDから作る v5 も認めている。Kubernetes 向けの非規範ガイドは、Podのアノテーション、または `<k8s.namespace.name>.<k8s.pod.name>.<k8s.container.name>` を挙げている。「PodのUID」を裏付ける一次資料はない |
| 257 | 補足 | エクスポーターで `NoUTF8EscapingWithSuffixes` か `NoTranslation` を選ぶと、Remote Write 1.0 では起動時にエラーになる |
| 263 | 補足 | ドットを含む名前は、引用符で囲んで中括弧の中に入れる（`{"http.server.request.duration"}`） |

これ以外の Prometheus、Collector、仕様、GMP、Mimir に関する記述は、上の版で一致しました。v0.162.0 では PermissiveLabelSanitization がデフォルトで有効になり、壊れた古典的ヒストグラムが捨てられるようになったので、段階1の前後の比較では Collector の版を固定する必要があります。

## 画像

| Shot ID | Case | 撮り方 | 画面 | 公開用 | 原本 |
| --- | --- | --- | --- | --- | --- |
| G-S6′ | G-07, G-11, G-13 | B（Cloud Console、`--channel chrome`） | Metrics Explorer の表で、`temperature_celsius` が3つの経路（`col-gmp`、`col-otlp`、`pm`）で同じ名前と値で並ぶ。左のメニューと上のバーは切り落とした | `images/20261015-gmp-three-paths.png` | `~/audit-work/1015-gke-otlp/screenshots-private/G-S6-raw.png` |
| G-S2′ | G-02 | A（ローカルのGrafana 13.2.4） | `info()` で、昇格させていない `deployment_environment_name` が付いた表 | `images/20261015-info-target-info.png` | `~/audit-work/1015-gke-otlp/screenshots-private/G-S2-raw.png` |
| G-S3′ | G-04 | A（ローカルのGrafana 13.2.4） | 2つのインスタンスのうち `pod-b` を 11:04 ごろに止めても `absent_over_time` は発火せず、`pod-a` を 11:07 ごろに止めた約5分後に値1になる | `images/20261015-absent-over-time.png` | `~/audit-work/1015-gke-otlp/screenshots-private/G-S3-raw.png` |

G-04 は、G-S3′ の撮影に使った送信の筋書き（Prometheus 3.15.0、SDK 1.45.1）で、9月22日の結果を版を上げて確かめ直しました（PASS、LOCAL）。公開用の画像は `scan_identifiers.py` で識別子のエラーが0件であることを確かめています。

## 片付け

作成したのは共有クラスター上の Namespace `ymo-1015-gke-otlp` と、その中の ConfigMap、Deployment、Service、`PodMonitoring` だけです。ServiceAccount、キー、IAM、クラスター全体に効く設定は作っていません。2026年10月14日に Namespace ごと削除し、kubectl での直接の確認と、読み取り専用の sweep（Cloud Asset のラベルと名前での検索）で残りがないことを確かめました。Cloud Monitoring に入った合成の系列は削除できず、保持期間で消えます。
