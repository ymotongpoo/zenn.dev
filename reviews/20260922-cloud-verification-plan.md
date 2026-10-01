# 2026-09-22 Cloud検証と原稿の対応表

3本のZenn記事に書かれた主張と、実行する検証、取得する証拠を対応付けるための記録です。


## 2026-09-22 最終検証結果

対象20 Case。今回の実行は15 Case、既存クラウド証拠の継承のみが3 Case、一次資料確認のみが2 Case。最終判定は **PASS 13 / FAIL 4 / BLOCKED 1 / DOCUMENTED 2**。

公開判定はVertex・GKEとも **公開保留（原稿修正が必要）**。記事本文は変更していません。最終報告は `/home/ymotongpoo/audit-work/codex-final-verification-report.md`、非公開の機械可読結果は `/home/ymotongpoo/audit-work/gcp-vertex-20260922/final-run/results.json`、コマンド・終了コードは `/home/ymotongpoo/audit-work/gcp-vertex-20260922/final-run/commands.jsonl` です。以下の結果を以前のLOCAL/CLOUD表記より優先します。過去のLOCAL/CLOUDは検証環境の履歴であり、最終合否ではありません。

- PASS: 明示した範囲の実行・証拠確認に合格。
- FAIL: 原稿の主張または移行条件と実測が不一致。
- BLOCKED: 必要な主体や認証条件がなく、未実施の条件が残る。
- DOCUMENTED: 一次資料の確認。実行成功とはしない。

V-09はconfigとprompt/conversation、V-10はcardinality/exemplar、G-09はrecording rule/rollback、G-10は個別instanceとCollector停止として追加定義しました。AWSのW Caseは今回対象外です。

| Case | 判定 | 原稿の節・行 | 実測・確認結果 | コマンドラベル / 主な証拠 |
|---|---|---|---|---|
| V-01 | PASS | 20260922-vertex-ai-genai-otel.md:83–147 計装の実装 | SDKからCollectorへSpan/Metricを送り、終了コード0と受信OTLPを確認。 | `v01-v02-followup` / `cases/V-01/assertions.json` |
| V-02 | FAIL | 20260922-vertex-ai-genai-otel.md:181–238 収集の設計 | 実測handler Spanが変換対象外。キーは削除されずマスク。イベント属性とmap bodyもマスクされ、本文の対象外という説明と不一致。別置き修正候補は9組のSpan正負例で成功。 | `v02; v01-v02-followup; redaction-boundaries` / `cases/V-02/assertions.json` |
| V-03 | FAIL | 20260922-vertex-ai-genai-otel.md:59–81,147,238 プロンプトとレスポンスの扱い | 基本16条件は期待どおり。NO_CONTENTでもtool definitionsの説明文字列がSpanに残る負例あり。LoggerProviderなしではイベントが出ないことも実測。 | `vertex-matrix; tool-privacy; logger-absent` / `vertex-matrix.json` |
| V-04 | PASS | 20260922-vertex-ai-genai-otel.md:135–149 計装の実装 | 既存Gemini 3.8 Flash実リクエストの証拠を継承。今回モデルへの再リクエストはなし。別名gemini-flash-latestの実呼び出しは未実施。 | `final-supplement` / `inherited-evidence.json` |
| V-05 | PASS | 20260922-vertex-ai-genai-otel.md:155–230 収集の設計 | 過去のCollector経路とMonitoring系列を継承。今回Cloud Traceをサービス名・時間帯限定のread-only APIで再取得、HTTP 200で1 Traceを確認。Span providerの未変換はV-02のFAIL。 | `cloud-trace-readonly` / `cases/V-05/trace-readonly.json` |
| V-06 | BLOCKED | 20260922-vertex-ai-genai-otel.md:69–79 プロンプトとレスポンスの扱い | 既存upload、messages_ref、generation/size、専用バケット削除証拠は継承。独立した許可主体・拒否主体によるIAM実証は認証主体が用意されていないため未実施。既存IAMは変更しない。 | `final-supplement` / `inherited-evidence.json` |
| V-07 | DOCUMENTED | 20260922-vertex-ai-genai-otel.md:9–59,85–87,149–151 規約・製品名・対応範囲 | cc07f72、google-genai v2.24.0、計装1.1b1の一次資料とインストール実装を確認。規約の記述と固定実装の挙動は区別。 | `sources; sources3; sources4; documented-sources` / `sources/index.json` |
| V-08 | PASS | 20260922-vertex-ai-genai-otel.md:41,149–151 計装の実装 | 固定SDKをhttpx MockTransportで実行。4 APIのSpan、streaming時間メトリクス、自動toolの親子Span、手動toolで子Spanが無いことを確認。クラウド側API利用資格の証拠にはしない。 | `vertex-matrix; tool-privacy` / `cases/V-08/NO_CONTENT-off-on-embedding/spans.json` |
| V-09 | PASS | 20260922-vertex-ai-genai-otel.md:49–53 アプリケーション側に残る部分 | デフォルト・includes・excludesのみ・競合を実行。完全修飾config属性名で選別、競合は除外優先。context未指定ではprompt/conversationなし、明示設定するとSpanに出力。 | `vertex-config-refined` / `cases/V-09/refined-includes/spans.json` |
| V-10 | PASS | 20260922-vertex-ai-genai-otel.md:240 収集の設計 | 4リクエスト・2モデル版でtoken 4系列、duration 2系列。conversation/response IDはメトリクス属性に入らず、全保存exemplarのTrace/Span IDが出力Spanに一致。Cloud UI遷移は未実施。 | `vertex-matrix; evidence-assertions-final` / `cases/V-10/NO_CONTENT-off-on-cardinality/metrics.json` |
| G-01 | PASS | 20260922-gke-prometheus-to-otlp-metrics.md:168–210 OTLPの経路を並行して立てる | 共通base URLと固有完全URLで200、固有base URLとreceiver無効で404。SDK実送信の系列も取得。 | `g01-g02` / `cases/G-01/results.json` |
| G-02 | FAIL | 20260922-gke-prometheus-to-otlp-metrics.md:43–102 メトリクス名・リソース属性とtarget_info | 4戦略、識別属性の4組、job/instance、keep、join競合とinfoによる解消は成功。scopeラベルはデフォルトで欠落し、promote_scope_metadata=trueが必要。 | `g01-g02; scope-metadata` / `cases/G-02/results.json` |
| G-03 | FAIL | 20260922-gke-prometheus-to-otlp-metrics.md:144–162,246–262 Collectorにスクレイプを任せる・移行条件 | 名前集合とCounter/Histogram値は保持。scopeラベル追加、target_info属性追加、le="1.0"→"1"等で完全なラベル集合一致の移行条件は不合格。 | `remote-fixtures2; evidence-assertions-final` / `cases/G-03/otlp.jsonl` |
| G-04 | PASS | 20260922-gke-prometheus-to-otlp-metrics.md:218–240 ダッシュボードとアラートの書き換え | Prometheus 3.14.0 promtoolの仮想時計で一部停止時の非発火、全停止後の発火、初回前の誤検知、push-onlyでupなしを確認。 | `prom-rules` / `cases/G-04/tests.yaml` |
| G-05 | PASS | 20260922-gke-prometheus-to-otlp-metrics.md:106–123,202–210 集計の時間性とヒストグラム | SDK6組、deltaフラグ、RWでdelta破棄、explicit/NHCB併記、exponential native、count/sum/quantileを実行。30分windowで1分逆順は受理、31分逆順は拒否。RW2実運用適性はDOCUMENTED。 | `g05; remote-fixtures2; temporality-sdk` / `cases/G-05/results.json` |
| G-06 | PASS | 20260922-gke-prometheus-to-otlp-metrics.md:127–142,246–262 Collectorにスクレイプを任せる・引き返し方 | 未対応5設定を実際に拒否。$$1リラベル成功。Collector二重scrapeを実測。専用kind上のTAとローカルCollector2個で8対象を分割、片方停止後に残りで8対象up=1。Operator CRD経由の導入は対象外。 | `migration; ta-run; ta-receiver-retry` / `cases/G-06/validation.json` |
| G-07 | PASS | 20260922-gke-prometheus-to-otlp-metrics.md:30–39,164 GMP経路 | 既存専用NamespaceのGMP系列3点と削除記録を継承。今回はGKEに接続しない。GMP専用Exporterの予約ラベル/INT・DOUBLE拒否は一次資料のみで実測とはしない。 | `final-supplement` / `inherited-evidence.json` |
| G-08 | DOCUMENTED | 20260922-gke-prometheus-to-otlp-metrics.md:9–15,30–39,112–121,164 対応範囲・安定度 | Prometheus/Collectorの固定版実行に加え、v0.161.0のExporter文書、Mimir 3.2.1リリース・3.2.x HTTP API、GMP文書を確認。Mimir実サーバーのtenant分離、GMP専用Exporter拒否は未実行。 | `sources; documented-sources` / `sources/index.json` |
| G-09 | PASS | 20260922-gke-prometheus-to-otlp-metrics.md:216,246–262 段階と引き返し方 | 旧名recording ruleをpromtoolで評価。実Prometheusでscrape設定を停止・再ロード・復元しactiveTargetsとup=1の復旧を確認。全実アプリ/全ダッシュボードの互換性は対象外。G-03の移行条件不合格は未解消。 | `migration; prom-rules` / `cases/G-09/rollback.json` |
| G-10 | PASS | 20260922-gke-prometheus-to-otlp-metrics.md:236–240 個別PodとCollector障害 | promtoolで期待Pod集合との差分とCollector heartbeat消失を評価。実Collectorを停止し送信接続拒否を確認、+6分の仮想評価時刻でabsence発火。Kubernetes Probe/restartの本番監視は未実行。 | `prom-rules; g10-stop` / `cases/G-04/tests.yaml` |


ローカルスクリーンショットはtarget_infoとnative histogramの2枚を保存しました。Cloud UIの認証済みブラウザーセッションはなく、Trace/Monitoring/GCSの機械可読証拠で代替しています。専用kindクラスターと一時kubeconfigは削除済み。今回は既存GKEへ接続せず、GCPの変更も行っていません。

## 過去の検証状態

| 状態 | 意味 |
| --- | --- |
| `PLANNED` | 検証計画のみ。コード実行とクラウド接続は未実施 |
| `LOCAL` | ローカルまたはコンテナで検証済み |
| `CLOUD` | 指定したクラウド環境で実リクエストと受信結果を確認済み |
| `DOCUMENTED` | バージョン付き一次資料で確認済み。実行成功の証拠にはしない |
| `BLOCKED` | 認証、権限、リージョン、モデル利用資格などが不足して停止 |

計画作成時点では全項目が計画段階でした。2026年9月22日に、ユーザー指定のGCPプロジェクト `dev-advocacy-380120` でVertex/Geminiの一部検証を実施しました。この時点の記述は初回Vertex検証の範囲です。その後の専用GKE Namespaceと専用GCSバケットの作成・検証・削除は下の履歴に記録しています。AWSへの接続は行っていません。

## 執筆候補1〜3番目とGoogle Cloudの範囲

候補1〜3番目のうち、Google Cloudを扱う記事は2本です。

1. `gcp-10.md` #10 — Vertex AI / Geminiアプリのオブザバビリティ
2. `aws-10.md` #4 — Amazon Bedrock / SageMakerのAIエージェント監視（AWS記事）
3. `gcp-10.md` #9 — GKE上のPrometheusからOpenTelemetry Metricsへの移行

したがって、GCPで必要な検証対象はVertex AI記事とGKE/Prometheus記事の2本です。Bedrock/SageMaker記事はGCP検証の対象外で、AWS検証が別途必要です。

## GPT-6-Astra最終監査後の反映

GPT-6-Astra / highの20 Case監査で見つかったP1/P2のうち、原稿の技術説明に反映できるものを更新し、VertexのCollector YAMLをv0.161.0で再検証しました。`V-02`の47 assertionも、実測どおりscope変換とRedactionのマスク結果を期待値にして再実行し、終了コード0です。

反映した内容:

- Vertex: `opentelemetry.util.genai.handler` のSpan/Metric scopeをTransform対象へ追加
- Vertex: Redactionは削除ではなくマスクであり、Spanイベントとmap bodyも対象になることを明記
- Vertex: `NO_CONTENT`でもtool definitionの説明文字列が残る実装上の例外を明記
- GKE: `promote_scope_metadata` の既定値と有効化時のラベル差分を明記
- GKE: `target_info`、scope metadata、`le` 表記の差分を移行判定に含めるよう明記

なお、GCSを異なる主体で読むIAM分離は、既存IAMを変更しない制約のため `BLOCKED` のままです。Cloud Consoleのスクリーンショットも認証済みブラウザーがないため、API JSONを代替証拠としています。

## 2026年9月22日の実施結果

| Case ID | 状態 | 実施内容 | 証拠 |
| --- | --- | --- | --- |
| `V-01` | `LOCAL` | `google-genai 2.24.0`、`opentelemetry-sdk 1.44.0`、`opentelemetry-instrumentation-google-genai 1.1b1`、`opentelemetry-util-genai 1.1b0`でProvider初期化、計装、終了処理を実行 | `~/audit-work/gcp-vertex-20260922/spans.jsonl`、`metrics.jsonl` |
| `V-04` | `CLOUD` | `dev-advocacy-380120` の `global` で `gemini-3.8-flash` に合成プロンプトを送信。RESTとPython計装の両方で実行 | `response-gemini-3-8-flash.json`、`run-output-gemini-3-8-flash.json`、`spans-gemini-3-8-flash.jsonl`、`metrics-gemini-3-8-flash.jsonl` |
| `V-05` | `CLOUD` | v0.161.0 Collectorの原稿経路（OTLP/gRPC Receiver → `resource/gcp` → Transform/Redaction/Batch → `otlphttp` + `googleclientauth` → Telemetry API）を実行。`gcp.project_id`、`cloud.region=us-central1`、実測されたメトリクススコープ `opentelemetry.util.genai.handler` に対応後、トレース・メトリクスとも取り込みを確認 | `vertex-collector.yaml`、`collector-app-output-2.json`、`collector-genai-timeseries.json`、`collector`実行ログ |
| `V-06` | `CLOUD` | 専用バケットを新規作成し、`NO_CONTENT`＋upload hook＋`gs://` JSONLで合成プロンプトを保存。Spanには本文ではなく `gen_ai.input.messages_ref` が入り、Cloud Storage Objectのgeneration/sizeと本文マーカーを確認。専用バケットとObjectは検証後に削除。別主体によるIAM閲覧可否は未検証 | `gcs-app-output.json`、`gcs-object-describe.yaml`、`gcs-object-content.jsonl`、`bucket-cleanup.log` |
| `G-07` | `CLOUD` | 既存 `spice-runner-cluster`（`us-central1-a`）に自作Namespace `hermes-otel-verify-20260922`、Deployment、PodMonitoringだけを作成。GMPの `process_cpu_seconds_total/counter` をCloud Monitoring APIで取得し、検証PodのNamespace、Pod、Location、Cluster、Instanceラベルと3点を確認。検証後にNamespaceを削除 | `gke-apply.log`、`gke-timeseries.json`、`gke-cleanup.log` |

`V-04`では、HTTP 200とVertexのusage metadataを確認しました。Python計装では、`generate_content gemini-3.8-flash` のSpanと、`gen_ai.operation.name`、`gen_ai.request.model`、`gen_ai.provider.name`、`gen_ai.usage.input_tokens`、`gen_ai.usage.output_tokens`、`gen_ai.response.finish_reasons`などを確認しました。応答本文は合否判定に使わず、合成プロンプトだけを使用しています。

Python計装の実測値ではprovider属性が `vertex_ai` でした。Spanのscopeは計装パッケージ側、メトリクスのscopeは `opentelemetry.util.genai.handler` でした。そのため、記事のCollector設定はメトリクスについて両方のscopeを対象にし、元のprovider値を `gcp.vertex_ai` へ読み替えるよう更新しました。Telemetry APIへの初回メトリクス送信は `cloud.region` が無かったためHTTP 400になりましたが、`gcp.project_id`、`cloud.region=us-central1`、`googleclientauth.project` を設定した原稿相当のCollector経路を再実行し、GenAI token usage系列をCloud Monitoring APIから確認しました。

実行証拠はローカルの非公開ディレクトリに保存しています。アクセストークン、プロジェクト認証情報、共有プロジェクト内の他サービス情報は記録していません。

## 検証成果物の規約

検証ごとに次のディレクトリを作成します。`<run-id>` は実行日と短い識別子を組み合わせ、原稿のSHA-256と使用バージョンを `manifest.json` に記録します。

```text
<非公開の検証ディレクトリ>/<run-id>/
  manifest.json
  cases/<case-id>/
    source.md       # 対象記事の該当節と主張
    harness.*       # 検証用コードまたは設定
    result.json      # PASS / FAIL / BLOCKED / DOCUMENTED
    evidence/        # ログ、OTLP、HTTP結果、クエリ結果
    screenshots-private/
    screenshots-public/
  resources.json     # 作成した一時リソース、TTL、削除結果
```

記事へ反映する証拠は `screenshots-public/` と、機密情報を除いた `evidence/` だけです。原本画像、プロンプト本文、Authorizationヘッダー、Cookie、SigV4署名、GCPトークン、署名付きURLは公開リポジトリへ持ち込みません。

## Vertex AI / Gemini記事

対象記事: [`articles/20260922-vertex-ai-genai-otel.md`](../articles/20260922-vertex-ai-genai-otel.md)

| Case ID | 原稿の節 | 原稿で確認する主張 | 検証 | 必要環境 | 成功時の証拠 |
| --- | --- | --- | --- | --- | --- |
| `V-01` | `計装の実装` | Provider初期化、Exporter、終了処理でスパンとメトリクスを送信できる | ローカル | 固定版Python、OTLP受信Collector | `result.json`、依存ロック、受信OTLP、終了コード |
| `V-02` | `収集の設計` | Transformが対象スコープと元の属性値だけを書き換え、Redactionの範囲が説明と一致する | ローカル | Collector v0.161.0 | 変換前後OTLP、起動ログ、本文属性の残存結果 |
| `V-03` | `プロンプトとレスポンスの扱い` | `NO_CONTENT`、`SPAN_ONLY`、`EVENT_ONLY`、`SPAN_AND_EVENT`とアップロードフックの関係 | ローカル | Python計装固定版、ローカル保存先 | モード別OTLP、イベント、JSONL、本文マーカー検索 |
| `V-04` | `計装の実装` | Geminiの実呼び出しでGenAI属性とトークンメトリクスが得られる | GCP | 既存GCPプロジェクト、許可リージョン、Gemini利用資格 | 応答のusage、変換前OTLP、モデル名、Trace/Monitoring検索結果 |
| `V-05` | `収集の設計` | 原稿のCollector経路でGoogle Cloudへトレースとメトリクスが届く | GCP | Telemetry API、既存の認証主体 | Exporter結果、partial success、Trace Explorer、Metrics Explorer |
| `V-06` | `プロンプトとレスポンスの扱い` | `NO_CONTENT`とCloud Storage保存を併用でき、本文の閲覧権限を分離できる | GCP | 既存検証バケット、専用prefix、既存IAM | GCS object generation/size、JSONL、参照ログ、Trace詳細 |
| `V-07` | `製品名の改称と属性値のずれ`、`規約が決めていること` | 規約、製品名、SDK、計装の対応範囲と安定度 | 一次資料 | 規約コミット、SDKタグ、計装タグ | 確認日時付きの対応表 |
| `V-08` | `計装の実装` | ストリーミング、embedding、ツール実行などの追加機能 | GCP | `V-04`と同じ。必要時のみ追加 | API別OTLP、子スパン、メトリクス、実行ログ |

### Vertexのスクリーンショット対応

| Screenshot ID | 対応Case | 撮影対象 | 記事で使える確認 |
| --- | --- | --- | --- |
| `V-S1` | `V-05` | Google Cloud Trace Explorerの対象Trace/Span | モデル、provider、operation、usage、duration |
| `V-S2` | `V-05` | Monitoring Metrics Explorer | トークン使用量、入力/出力、単位、時間範囲 |
| `V-S3` | `V-06` | Cloud Storageの検証Object詳細 | JSONL保存、サイズ、作成時刻 |
| `V-S4` | `V-06` | Logs ExplorerとTrace詳細 | 参照ログとTraceの対応。本文そのものはマスク |

## Bedrock / SageMaker記事

対象記事: [`articles/20260922-bedrock-sagemaker-otel.md`](../articles/20260922-bedrock-sagemaker-otel.md)

| Case ID | 原稿の節 | 原稿で確認する主張 | 検証 | 必要環境 | 成功時の証拠 |
| --- | --- | --- | --- | --- | --- |
| `W-01` | `3つの呼び出しを区別する`、`SageMakerのエンドポイントでのトレースの切れ目` | botocoreの4 API計装、旧属性、Provider初期化 | ローカル | botocore固定版、疑似応答fixture | API別OTLP、属性一覧、依存ロック |
| `W-02` | `3つの呼び出しを区別する` | Converse、InvokeModel、両ストリームAPIが実モデルで計装される | AWS | 既存AWSアカウント、許可モデル、許可リージョン | HTTP status、RequestId、本文を除いた応答、OTLP |
| `W-03` | `SageMakerのエンドポイントでのトレースの切れ目` | `CustomAttributes`の符号化とコンテナ側extractで親を復元できる | ローカル | 検証用HTTPサーバー | 送信値、受信値、trace ID、parent IDの比較 |
| `W-04` | `SageMakerのエンドポイントでのトレースの切れ目` | SageMakerサービス経由でもCustomAttributesと親子関係が保たれる | AWS | 一時CPU endpoint、検証用image | InvokeEndpoint応答、コンテナログ、双方のSpan |
| `W-05` | `構成の全体像` | Redaction、`truncate_all`、Batch、複数Exporterの挙動 | ローカル | Collector v0.161.0、疑似受信先 | 変換結果、シリアライズ後サイズ、拒否ログ |
| `W-06` | `構成の全体像` | SigV4付きOTLP/HTTPでX-Rayへ送信できる | AWS | 既存AWSアカウント、X-Ray権限 | 送信結果、X-Ray Trace、属性 |
| `W-07` | `本文と費用の扱い` | ADOT本文抽出、環境変数、baggageの後処理 | ローカル | 固定版ADOT、テストtransport | 加工前後Span/Log、環境変数、連続リクエスト比較 |
| `W-08` | `AgentCoreを使うときのCollectorの位置` | 公式サポート範囲と技術的な未検証範囲の区別 | 一次資料 | AgentCore公式文書、ADOT実装 | URL、確認日時、主張対応表 |
| `W-09` | `AgentCoreを使うときのCollectorの位置` | AgentCoreの実画面、セッション連携、独自送信経路 | AWS | 既存または許可済み検証runtime | CloudWatch GenAI Observability画面、Trace、Session分離 |

### AWSのスクリーンショット対応

| Screenshot ID | 対応Case | 撮影対象 | 記事で使える確認 |
| --- | --- | --- | --- |
| `W-S1` | `W-06` | CloudWatch/X-RayのTrace詳細 | API、リージョン、Span構造、duration |
| `W-S2` | `W-04` | SageMaker AIの検証Endpoint | `InService`、variant、試験時間帯 |
| `W-S3` | `W-04` | CloudWatch Logsのコンテナログ | CustomAttributes受信、親子ID対応 |
| `W-S4` | `W-09` | CloudWatch GenAI Observability | Session分離、Span、メトリクス |

## GKE / Prometheus記事

対象記事: [`articles/20260922-gke-prometheus-to-otlp-metrics.md`](../articles/20260922-gke-prometheus-to-otlp-metrics.md)

| Case ID | 原稿の節 | 原稿で確認する主張 | 検証 | 必要環境 | 成功時の証拠 |
| --- | --- | --- | --- | --- | --- |
| `G-01` | `OTLPの経路を並行して立てる` | OTLP ReceiverとSDK endpointのパスが正しい | ローカル | Prometheus 3.14.0、検証用HTTPログ | POST path、status、query JSON |
| `G-02` | `メトリクス名がどう変わるか`、`リソース属性とtarget_info` | 翻訳戦略、target_info、属性昇格、`info()` | ローカル | Prometheus固定版 | Series一覧、Query結果、ラベル集合 |
| `G-03` | `Collectorにスクレイプを任せる` | Prometheus ReceiverからOTLP/Remote Writeへの変換で情報が保たれる | ローカル | Collector v0.161.0、Prometheus/Mimir | 入力、OTLP中間表現、受信JSON、差分表 |
| `G-04` | `ダッシュボードとアラートの書き換え` | `up`と`absent_over_time`の検知対象が異なる | ローカル | 2インスタンスのfixture | 一部停止、全停止、初回リクエスト前の時系列結果 |
| `G-05` | `集計の時間性とヒストグラム` | temporality、各ヒストグラム形式、順不同取り込み | ローカル | Prometheus、Collector、Remote Write fixture | 型、count/sum、quantile、拒否ログ |
| `G-06` | `Collectorにスクレイプを任せる`、`段階と引き返し方` | Target Allocator、設定移植、ロールバック | ローカルKubernetes | 固定版Operator/Allocator | 重複スクレイプ、再割当、復旧後の`up` |
| `G-07` | `OTLPの経路を並行して立てる` | 既存GKEからGMPへ送り、検索できる | GCP | 既存GKE、検証用Namespace、Workload Identity | `spice-runner-cluster` の検証用Namespaceに自作DeploymentとPodMonitoringだけを作成。`process_cpu_seconds_total` のGMP系列をCloud Monitoring APIで確認 |
| `G-08` | 全体 | Prometheus、Collector、Mimir、GMPの安定度と対応範囲 | 一次資料 | 固定版公式資料 | バージョン付き対応表 |

### GCP/GKEのスクリーンショット対応

| Screenshot ID | 対応Case | 撮影対象 | 記事で使える確認 |
| --- | --- | --- | --- |
| `G-S1` | `G-01` | Prometheus Queryと検証用HTTPログ | `/api/v1/otlp/v1/metrics`、status、系列 |
| `G-S2` | `G-02` | Prometheus Queryのtarget_info/join | resource属性とラベルの対応 |
| `G-S3` | `G-04` | Prometheus Query/Graph | 一部停止、全停止、5分窓 |
| `G-S4` | `G-05` | PrometheusまたはGrafanaのQuery | classic/native、count/sum、quantile |
| `G-S5` | `G-07` | GKE Workloadsの検証Deployment | Namespace、replica、稼働状態 |
| `G-S6` | `G-07` | Google Cloud Monitoring Metrics Explorer | PromQL、対象系列、resource対応 |

## 実施前の停止条件

次の条件を満たさない場合、該当するクラウド検証を開始しません。

- GCPプロジェクトID、quota project、実行主体、許可リージョンが未指定
- AWSアカウントID、profileまたは引受ロール、リージョン、許可モデルが未指定
- 費用上限と最大実行時間が未承認
- API利用資格、既存ロール、削除権限を確認できない
- 既存GKEを変更せずに検証用Namespaceを限定できない
- 証拠の非公開保存先と公開用スクリーンショットの確認担当者が未定

認証失敗や権限不足を解消するために、Owner、Editor、AdministratorAccess、長期アクセスキーを追加しません。新規プロジェクト、AWSアカウント、GKEクラスター、Provisioned Throughput、Marketplace契約も作成しません。

## 実施順序

1. 依存バージョンと一次資料を固定し、`C`項目を記録する
2. `V-01`、`W-01`、`W-03`、`W-05`、`W-07`、`G-01`から`G-06`をローカルで実施する
3. ローカル検証が通った項目だけ、認証と費用上限を確認する
4. 最小セットとして`V-04`、`V-05`、`V-06`、`W-02`、`W-04`、`W-06`、`G-07`を実施する
5. 必要な記事だけ追加項目として`V-08`、`W-09`を実施する
6. 証拠とスクリーンショットをマスキングし、Case IDと記事の該当節を対応付ける
7. 一時リソース、ログ、GCSオブジェクト、コンテナimage、保持設定を確認して削除する
8. `CLOUD`になった主張だけ、記事本文の検証済み表現とスクリーンショットを追加する

## 計画時点の注記テンプレート（現行結果ではない）

以下は計画時点の文例です。現在の検証状態として転記せず、冒頭の最終結果と各Caseの範囲を優先してください。

- Vertex AI: 「この例は固定版SDKとローカル受信先で確認しています。Vertex AIへの実リクエストとGoogle Cloudへの送信は未検証です。」
- Cloud Storage: 「ローカル保存先でフックの動作を確認しています。Cloud Storageへの保存、IAM、Trace画面での本文表示は未検証です。」
- Bedrock: 「実行確認した範囲はモデル、リージョン、APIを明記します。それ以外は固定版の実装と公式資料に基づきます。」
- SageMaker: 「送受信コードはローカルで確認しています。SageMakerを通したCustomAttributesの転送と親子Spanの接続は未検証です。」
- AgentCore: 「ADOT Collectorの記述はAWSの公式サポート範囲に関するものです。独自OTLP経路と組み込みテレメトリーへの影響は未検証です。」
- GKE/GMP: 「変換とPromQLはローカルの固定版構成で確認しています。GKEの認証、GMPへの取り込み、既存ダッシュボードとの互換性は未検証です。」
