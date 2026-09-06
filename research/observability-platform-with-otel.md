# PEK2026 book 技術調査メモ（2026-08-25時点）

book「セルフサービスのオブザーバビリティ基盤をOpenTelemetryで作る」
（books/observability-platform-with-otel/）の執筆前調査。
各節の情報は2026年8月25日時点のスナップショット。出典URLを併記する。
本文執筆時には、引用する箇所を改めて一次情報で確認する。

## Zennのbook制約（確認済み）

- config.yaml の必須項目は title、summary、published、chapters。topics、price、toc_depth も指定できる
- topics は5つまで。title と summary の文字数制限は明記なし
- チャプターは1冊あたり最大100個
- 価格は無料（0）または200〜5000円の100円単位
- カバー画像は幅500px×高さ700px推奨、PNGまたはJPEG
- トピック `platformengineering` と `platform-engineering` は存在しない（404）。
  **`platformengineer` が実在する（HTTP 200）** ため、config.yaml はこちらを採用済み
- 出典: https://zenn.dev/zenn/articles/zenn-cli-guide

## Collector・OCB・OpAMP

### Collectorのバージョンとstability

- core最新は **v1.65.0 / v0.159.0**（2026-08-17）のデュアルバージョン体制。
  contrib最新は v0.159.0（同日）。リリースは実績ベースで隔週
- **1.x（stable）に達しているのはAPI・ライブラリ層のみ**（pdata、component、confmap、
  consumer、receiver、processor、exporter、extension、configtls等）。
  service、otelcol、otlpreceiver、otlpexporter、batchprocessor などは今もbeta。
  **実行バイナリと個別コンポーネントで1.0に達したものはまだ存在しない**
- 配布物（otelcol、otelcol-contrib、otelcol-k8s、otelcol-otlp、otelcol-ebpf-profiler）は
  opentelemetry-collector-releases から v0.159.0 として提供
- 出典: https://github.com/open-telemetry/opentelemetry-collector/blob/main/versions.yaml

### OCBのmanifest.yaml（30章の核）

- **dist セクションに必須フィールドはない**。全フィールドにデフォルトがある。
  フィールドは module、name、go、description、output_path、version、build_tags、
  debug_compilation、cgo_enabled（デフォルトfalse）、use_absolute_replace_paths
- **`otelcol_version` はv1.19.0/v0.113.0（2024-11）で削除済み。書いてはいけない**。
  代わりにビルド時のstrict versioning checkでコンポーネントバージョンの整合を検査する
  （builder READMEに古い言及が残っているので注意）
- モジュール列挙は receivers / processors / exporters / extensions / connectors /
  providers / converters。各エントリは `gomod` が必須
- **providers は省略可能**。省略時は env / file / http / https / yaml の5 providerが
  stableバージョン（v1.65.0）で自動付与される。明示する場合はv1.x系を指定
- OCB最新は cmd/builder/v0.159.0（2026-08-18）。推奨インストールは公式Dockerイメージ
  （otel/opentelemetry-collector-builder）または公式バイナリ。go install は非推奨
- **公式ドキュメントURLは https://opentelemetry.io/docs/collector/extend/ocb/ に移動**
  （旧 /docs/collector/custom-collector/ は404）

### OCBのCI/CDとコンテナ化

- 専用の公式CI/CDガイドはない。公式に提供されているのは次の3つ
  - ocbページの「Containerize your Collector Distribution」節（docker buildxのマルチアーキ例）
  - builder READMEのCI分割手順。`--skip-compilation` でコード生成のみ→コミット→CIで
    `--skip-generate --skip-get-modules` でコンパイル、という3ステップ分離
  - opentelemetry-collector-releases のGoReleaser + GitHub Actions構成が事実上のリファレンス実装

### OpAMP仕様とopamp-go

- OpAMP仕様は**今もStatus: Beta**。最新リリースは v0.20.0（2026-08-12、
  AgentConfigFile→AgentConfigObjectのリネームを含む）
- opamp-go最新は v0.23.0（2026-02-18）で約半年リリースなし。README自身は
  work-in-progressを名乗るが、Supervisor側はproduction-readyと記述しており矛盾がある。
  「仕様Beta・実装v0.xだが、Supervisorやベンダー製品が実運用で利用」という表現が安全

### OpAMP Supervisor（40章の核）

- **Stability: alpha**。最新は cmd/opampsupervisor/v0.159.0（2026-08-18）。
  バイナリとコンテナイメージが collector-releases から配布されている
- capabilities実装状況
  - 実装済み: AcceptsRemoteConfig、ReportsEffectiveConfig、ReportsRemoteConfig、
    ReportsOwn{Traces,Metrics,Logs}、Accepts{OpAMP,Other}ConnectionSettings、
    AcceptsRestartCommand、ReportsAvailableComponents
  - 注意付き: ReportsHealth（READMEにcaveat表記。言及するなら内容の深掘りが必要）
  - **未実装: AcceptsPackages / ReportsPackageStatuses（パッケージ管理）、
    Collectorバイナリの更新（issue #33947）**
  - →「OpAMPでバイナリ更新できる」と書くと誤り。仕様上は定義されているが参照実装が未対応
- supervisor.yaml の構造: server（endpoint、headers、tls）、capabilities（bool群）、
  agent（executable、config_files、args、env、startup_fallback_configs、
  automatic_config_rollback 等）、storage、healthcheck、telemetry
- 比較的新しい機能: 起動時フォールバック設定、**リモート設定の自動ロールバック**
  （automatic_config_rollback、デフォルト無効）、クラッシュログ断片の報告
  → 40章の「ヘルス報告に基づく自動ロールバック」はこの実機能に接続できる
- 出典: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/cmd/opampsupervisor

### OpAMPサーバー側の選択肢

- open-telemetry組織に**プロダクション用途のスタンドアロンOpAMPサーバーは存在しない**。
  opamp-goのserverパッケージ（ライブラリ）とexample serverのみ
- opamp-spec公式が挙げる実用プラットフォームはBindplaneとGrafana Fleet Management
  （いずれも商用・SaaS）。旧OSS版bindplane-opリポジトリは404（削除・非公開化）
- OSS路線は「opamp-goのserverライブラリで自前実装」が現状の答え。
  サンプルリポジトリのopamp/serverはこの前提で作る

### Collector管理の公式推奨

- https://opentelemetry.io/docs/collector/management/ はOpAMP採用を推奨。
  実装パターンとしてSupervisor（プロセス外制御）とopampextension（Collector内蔵）を紹介
- 管理タスク: 設定の照会・適用、アップグレード、ヘルス監視、接続管理（TLS証明書）

### 執筆時の要注意（誤りやすい点）

- OCBのドキュメントURLは /docs/collector/extend/ocb/（旧URLは404）
- manifest に otelcol_version を書かない（削除済み）
- Collectorに「1.0」のバイナリ・コンポーネントはまだない
- OpAMP仕様はBeta、Supervisorはalpha、パッケージ管理は未実装

## Weaver

### バージョンとstability

- 最新リリースは v0.25.1（2026-07-28）。1.0には未達で0.xのまま
- v0.24〜v0.25系で「semantic conventions v2」対応が進行中。多くのコマンドに `--v2` フラグが
  あるがデフォルトオフの移行期
- 公式semconvレジストリの運用ツールとして本番利用されている
- 出典: https://github.com/open-telemetry/weaver/releases

### コマンド体系（docs/usage.md 原文確認済み）

- すべて `weaver registry` のサブコマンド
- `check`（構文・参照解決・Regoポリシー検証）、`generate`（テンプレート生成。生成前にポリシー
  検証を自動実行）、`stats`、`update-markdown`、`json-schema`、
  `diff`（`--baseline-registry` 必須。ansi/JSON/markdown出力）、
  `emit`（レジストリ定義からサンプルシグナルをOTLPで送出）、`live-check`、
  `mcp`（**レジストリをLLMに公開するMCPサーバー**。stdio JSON-RPC）、
  `infer`（OTLPメッセージからスキーマを逆生成）、
  `package`（自己完結アーティファクトへのパッケージング）
- **`resolve` と `search` は非推奨（DEPRECATED）**。書籍で主要コマンドとして扱わない
- `weaver emit` ではなく `weaver registry emit` が正
- `-r/--registry` のデフォルトは公式semconvのGit URL。`@refspec` と `[sub-folder]` 構文対応
- `weaver registry mcp` は70章（AIがスキーマを読む）の実例としてそのまま使える

### 社内registryの定義

- **マニフェストのファイル名は `manifest.yaml` が現行名**（`registry_manifest.yaml` は
  deprecatedなレガシー名。読み込みは可能）
- 現行構造（原文の例）

  ```yaml
  name: acme
  description: This registry contains the semantic conventions for the Acme vendor.
  schema_url: https://acme.com/schemas/0.1.0
  dependencies:
    - schema_url: https://opentelemetry.io/schemas/1.40.0
      registry_path: https://github.com/open-telemetry/semantic-conventions@v1.40.0[model]
  ```

- 依存の `schema_url` は必須（v0.25.1で必須化）。旧形式（schema_base_url + semconv_version）は
  レガシーで `registry package` では拒否される
- semconvファイル側では `- ref: host.name` で公式属性を参照して requirement_level を
  ローカル上書きできる。`imports:` セクション（`metrics: [db.*]` 等）はグループ取り込みの別機構
- マルチregistryは**最大10階層**の依存に対応（「2階層まで」とする2025年の記事は古い）
- 出典: https://github.com/open-telemetry/weaver/blob/main/docs/define-your-own-telemetry-schema.md

### ポリシー機構

- OPAのRegoで記述。ステージは before_resolution / after_resolution /
  comparison_after_resolution（後方互換検査用）
- `weaver registry check --policy ./my-policies`。`-p` はGit URLも指定できる
- **公式ポリシー集は [opentelemetry-weaver-packages](https://github.com/open-telemetry/opentelemetry-weaver-packages)
  に集約**。policies/check/ 配下に naming_conventions、stability、backwards-compatibility 等
- 公式semconvリポジトリ自体がCIでこれらのポリシーを使用しており、ガバナンスの実運用例そのもの

### コード生成

- テンプレートエンジンは minijinja（Jinja2互換）、データ加工は jaq（jq互換）
- weaver.yaml の templates: に template / filter / application_mode / file_name。
  v0.25.0で条件分岐の `when` 句が追加
- **公式Go semconvパッケージ（go.opentelemetry.io/otel/semconv）はWeaverで生成されている**。
  opentelemetry-goの `make semconv-generate` がweaver Dockerイメージで registry generate を実行。
  テンプレートは同リポジトリの semconv/templates にあり、社内registryからのGo生成の手本になる
- 動作するサンプル集: [opentelemetry-weaver-examples](https://github.com/open-telemetry/opentelemetry-weaver-examples)
- weaver-packagesにGoコード生成テンプレートはまだ収録されていない

### live-check（50章の検証パートに直結）

- 入力は `--input-source` で **otlp（gRPCでOTLP直接受信、デフォルト）**/ ファイル / stdin
- 対応シグナルは**スパン、メトリクス、ログ、リソース**の4種＋個別属性・スパンイベント
- builtin advisor（missing_attribute、type_mismatch等）＋OTel標準advisor＋
  カスタムRegoポリシー（`--advice-policies`）。findingは violation / improvement / information
- violationがあれば終了コード非ゼロ。`--fail-on` で閾値設定。**CI/CDパイプラインでの利用が
  公式に想定されている**（テスト実行中のテレメトリを受けて品質評価）
- OTLPリスナーはデフォルト4317、adminポート4320の /stop で停止、`--inactivity-timeout` あり
- 出典: https://github.com/open-telemetry/weaver/blob/main/crates/weaver_live_check/README.md

### 活用事例

- 公式ブログ [Observability by Design (2025)](https://opentelemetry.io/blog/2025/otel-weaver/)。
  公式レジストリ900以上の属性をWeaverでCI検証・ドキュメント生成・コード生成
- [Semantic Conventions 2026 Roadmap](https://github.com/open-telemetry/semantic-conventions/issues/3330)。
  Federated Semconv（V2スキーマ、依存、公開）とcontribへのlive-check導入が2026年の柱
- サードパーティ: Honeycomb、OneUptime（2026-02）、Adriana Villela（2026-05）等の解説記事あり

### 執筆時の要注意（誤りやすい点）

- マニフェストは `manifest.yaml`（`registry_manifest.yaml` は旧名）
- `resolve` / `search` は非推奨。`generate` / `package` を使う
- 依存宣言はマニフェストの `dependencies`（schema_url必須）。`imports` は別機構
- マルチregistryは最大10階層
- semconv v2スキーマ（--v2）は移行期でデフォルトオフ

## GenAIセマンティック規約とAI計装

### 最重要: 専用リポジトリへの分離（60章の前提）

- GenAI semconvは2026年6月に本体リポジトリから専用リポジトリ
  [open-telemetry/semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai)
  へ分離された。本体のv1.42.0（2026-06-12）で全 `gen_ai.*`（および `mcp.*`、`openai.*`）が
  deprecated化され、v1.43.0（2026-07-03）で定義本体が削除された
- opentelemetry.io の gen-ai ページは移転告知のみ。本体最新はv1.44.0（2026-08-04）
- **新リポジトリにはまだ一つもリリース・タグがない**（2026-08-25時点）。
  versioned schema URLが存在しないため「semconv vX.Y準拠」という書き方が新リポジトリには使えない

### stability

- **全てDevelopment。stableになった部分は一つもない**。「stable」と書くと誤り
- 共有属性（error.type、server.address等）のみ本体側でstable
- 出典: [gen-ai-spans.md](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md)

### 属性の現行名と改名履歴

- 現行: `gen_ai.provider.name`（Required。openai / anthropic / aws.bedrock / gcp.vertex_ai 等）、
  `gen_ai.operation.name`（Required）、`gen_ai.request.model`、`gen_ai.response.model`、
  `gen_ai.usage.input_tokens` / `output_tokens`、`gen_ai.conversation.id`
- 改名履歴（確定3点）
  - v1.27.0（2024-08）: `gen_ai.usage.prompt_tokens`→`input_tokens`、`completion_tokens`→`output_tokens`
  - v1.37.0（2025-08）: `gen_ai.system`→`gen_ai.provider.name`
  - v1.37.0: メッセージ毎イベント方式→スパン属性方式へ転換（下記）
- 出典: [registry deprecated一覧](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)

### スパン規約

- Model spans と Agent spans に分かれる。スパン名は `{gen_ai.operation.name} {gen_ai.request.model}`（例: `chat gpt-4`）
- `gen_ai.operation.name` の値は `chat`、`text_completion`、`generate_content`、`embeddings`、
  `create_agent`、`invoke_agent`、`execute_tool`、`invoke_workflow`、`plan`、`retrieval`、
  メモリ操作系（`create_memory` 等）まで拡張されている（完全な列挙は原文の表を執筆時に転記）
- エージェントスパン: `invoke_agent` はリモートがCLIENT、インプロセスがINTERNAL（v1.41.0、2026-04で分割）
- 出典: [gen-ai-agent-spans.md](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)

### プロンプト・補完内容の記録方式

- 現行設計は**スパン属性方式が主、イベントは補完**
- `gen_ai.input.messages` / `gen_ai.output.messages` / `gen_ai.system_instructions` /
  `gen_ai.tool.definitions`（いずれも **Opt-In**、JSONスキーマ準拠、機密情報警告つき）
- イベントは `gen_ai.client.inference.operation.details`（MAY）と `gen_ai.evaluation.result` の2つに整理
- opt-in制御（Python公式計装）: `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` =
  `no_content`（デフォルト）/ `span_only` / `event_only` / `span_and_event`
- 注意: この環境変数はsemconv文書ではなく計装ライブラリ側の規定。言語間で統一されているかは未確認
- 出典: [OTelブログ Inside the LLM Call](https://opentelemetry.io/blog/2026/genai-observability/)
  （デフォルトではプロンプト内容・ツール引数を記録しないと明記）

### メトリクス規約

- クライアント: `gen_ai.client.token.usage`（単位 {token}、`gen_ai.token.type`=input/output、
  推奨バケットは1,4,16,…,67108864の4倍刻み）、`gen_ai.client.operation.duration`、
  `time_to_first_chunk`、`time_per_output_chunk`
- サーバー: `gen_ai.server.request.duration`、`time_per_output_token`、`time_to_first_token`
- エージェント系: `gen_ai.invoke_agent.duration`、`invoke_agent.inference_calls`、
  `invoke_agent.tool_calls`、`execute_tool.duration`、`invoke_workflow.duration`
- 出典: [gen-ai-metrics.md](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md)

### 計装ライブラリ

- Python公式: [opentelemetry-python-genai](https://github.com/open-telemetry/opentelemetry-python-genai)
  リポジトリに移転（`opentelemetry-instrumentation-genai-*`、ベータ1.1b系）。
  OpenAI / Anthropic / LangChain / Google GenAI / OpenAI Agents / Agno 等がリリース済み
- JS: `@opentelemetry/instrumentation-openai`（semconv v1.36.0世代で最新規約より一世代古い）
- **Go: OTel公式のGenAI計装は存在しない**（GenAI SIGのスコープはPython/JSのみ）。
  選択肢はOpenInference Go（openai-go / anthropic-sdk-go対応、要Go 1.25+）か手動計装
  → 60章のGo計装例は手動計装で書くのが正解
- OpenLLMetry: 2026年3月にTraceloopがServiceNowに買収された。OTel semconvへの収斂路線
- OpenInference (Arize): OTelと併存する別の属性体系
- 実装間で規約世代が混在しているため、「計装が出力する実際のスパンを確認せよ」という注意書きが実態に即す

### MCPのテレメトリー（70章に直結）

- **MCP専用semconvが存在する**。semantic-conventions-genai 内の
  [docs/gen-ai/mcp.md](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/mcp.md)
  で管理（Status: Development、`mcp.*` 名前空間）
- スパン名 `{mcp.method.name} {target}`、属性 `mcp.method.name`（Required）、
  `mcp.session.id` 等。メトリクスは client/server の operation.duration と session.duration
- **コンテキスト伝播: MCPの `params._meta` にW3C Trace Contextキーを載せる方式が規定済み**。
  エージェントとMCPサーバー間のトレース分断への回答になっている
  （MCP仕様本体側が規定しているかは未確認。OTel側の規約として確認）

### AIがテレメトリーを読む側の動き（70章）

- 「AIを観測する」側はGenAI SIG・公式ブログ
  （[AI Agent Observability 2025](https://opentelemetry.io/blog/2025/ai-agent-observability/)、
  [Inside the LLM Call 2026](https://opentelemetry.io/blog/2026/genai-observability/)）が活発
- 「AIが読む」側の公式SIGは見つからず。
  [entity eventsのブログ（2026）](https://opentelemetry.io/blog/2026/consuming-opentelemetry-entity-events/)
  がエンティティグラフをMCPサーバー経由でAIに照会させる構成に言及
- エコシステム側: [traceloop/opentelemetry-mcp-server](https://github.com/traceloop/opentelemetry-mcp-server)
  （複数バックエンド横断のトレース分析MCP）、各ベンダーのオブザーバビリティMCPサーバー
- 70章では「標準化は未着手でベンダー実装が先行」という書き方が2026年8月時点の実態

## Go SDKと自動計装

### opentelemetry-go本体

- 最新は v1.45.0 / v0.67.0 / v0.21.0（2026-08-03）。次リリースからGo 1.26必須
- Traces: Stable、Metrics: Stable、**Logs: Beta（API・SDKともv0.21.0）**。
  ディストロにログブリッジを含めるかは設計判断になる
- 出典: https://github.com/open-telemetry/opentelemetry-go/blob/main/versions.yaml

### declarative configuration（otelconf）

- パッケージは `go.opentelemetry.io/contrib/otelconf`（旧 contrib/config から改名）。
  最新 v0.25.0 で **experimental（v0.x）**
- スキーマ側（opentelemetry-configuration）は **v1.0.0 が2026-02-27に初のstable**、
  最新 v1.1.0（2026-06-05）。otelconfが v1.0.0 final / v1.1.0 に完全追従済みかは未確認
  （rc.3追従までCHANGELOGで確認）。執筆前にotelconfの参照スキーマを直接確認する
- → 10章では「仕様はstable、Go実装は実験的。中核は環境変数+コード既定値で組み、
  otelconfは移行先候補」という書き方が2026年8月時点の実態

### 環境変数対応（10章の優先順位設計に直結）

- Go SDK単体で対応: OTEL_SERVICE_NAME、OTEL_RESOURCE_ATTRIBUTES、OTEL_TRACES_SAMPLER(_ARG)、
  OTEL_EXPORTER_OTLP_*、OTEL_BSP_*、attribute limits系
- **Go SDK単体で非対応: OTEL_PROPAGATORS、OTEL_{TRACES,METRICS,LOGS}_EXPORTER、OTEL_SDK_DISABLED**
- 補完: `contrib/exporters/autoexport` v0.70.0（OTEL_*_EXPORTER対応）、
  `contrib/propagators/autoprop` v0.70.0（OTEL_PROPAGATORS対応）。いずれもexperimental
- 出典: https://github.com/open-telemetry/opentelemetry-specification/blob/main/spec-compliance-matrix.md

### resource detectionとサンプラー

- detectors: gcp、aws/ecs、aws/eks等はstable-v1（v1.45.0）。aws/ec2はv2系（v2.5.2）。
  azure、k8sapi等はexperimental（v0.17.0）。
  **`detectors/autodetect`（v0.17.0）が新設**。ID文字列でdetectorを登録・名前引きする仕組みで
  otelconf連携を想定した作り
- SDKデフォルトsamplerは ParentBased(root=AlwaysSample)
- **CPSのGo実装 `contrib/samplers/probability/consistent` は v0.37.2 でexperimental。
  しかも旧ドラフト（p値・r値）ベースで、現行仕様のth値ベースに追従した新実装は未確認**。
  10章で扱うなら「実験的かつ旧ドラフト準拠」の注記が必須。既定はParentBasedに置くのが安全

### 計装ライブラリ

- otelhttp v0.70.0、otelgrpc v0.70.0（2026-08-03）。**いずれもv0.xで非stable**
- otelgrpcはinterceptor方式が非推奨になり**stats handler方式が現行**
  → 「破壊的変更をディストロ層で吸収する」の実例として10章で使える
- レジストリ（opentelemetry.io/ecosystem/registry）は1,100件超

### eBPF自動計装（20章）

- **opentelemetry-go-instrumentation はアーカイブされていない**（最新 v0.24.0、2026-04-27）が、
  公式なOBI移行宣言はなく、メンテナの個人記事が「事実上メンテナンスモード、
  コントリビュータはOBIへ移った」と記述（非公式）
- **OBI（opentelemetry-ebpf-instrumentation）**: Beyla寄贈（2025）起源、モジュールパス
  `go.opentelemetry.io/obi`。最新 **v0.12.2（2026-08-21）**。
  **v0.11.0（2026-08-17）で「Go Trace APIの自動計装」が入り**、go-instrumentationの
  守備範囲を取り込みつつある。v0でbreaking changes前提、2026年の目標はstable 1.0
- OBI対応範囲: HTTP/S、HTTP/2・gRPC、各種DB、メッセージング、**GenAI API
  （OpenAI/Claude/Gemini/Bedrock等）**、TLS内可視化。多言語対応
- 出典: https://opentelemetry.io/docs/zero-code/obi/ 、
  https://opentelemetry.io/blog/2026/obi-goals/

### compile-time計装（20章の大きな更新点）

- **otelc が2026-07-14にv1.0.0でstable到達**（v1.0.0はretract済みでv1.0.1を使う）。
  **最新はv1.1.0（2026-08-24）**。モジュールは `go.opentelemetry.io/otelc`
- `go build` を `otelc go build` に置き換えるだけ。-toolexec機構でコンパイル時に書き換え
- 対応: net/http、database/sql、gRPC、Redis、MongoDB、Gin、Kafka、OpenAI SDK、
  Anthropic Go SDK（v1.1）、log/slog/logrusへのtrace context注入。シグナルはtraces+metrics
- 経緯: Alibaba（loongsuite）+ Datadog（Orchestrion）+ Quesma が2025-02にSIG発足、統合
- → 20章の「ビルド時計装の動向」は「動向」ではなく**stable v1として実用可能**と書ける。
  eBPF（OBI、v0）とビルド時（otelc、v1 stable）の対比が2026年8月の構図
- 出典: https://opentelemetry.io/blog/2026/go-compile-time-instrumentation-v1/

### Operator の Instrumentation CRD によるGo注入（20章）

- Goの自動計装注入はデフォルト無効。operatorに `--enable-go-instrumentation=true` が必要
- Pod annotation `instrumentation.opentelemetry.io/inject-go: "true"` に加え、
  **対象実行ファイルを指す `otel-go-auto-target-exe` annotationが必須**
- エージェントは privileged: true、runAsUser: 0 で動く。マルチコンテナPod非対応
- **Operator（v0.158.0系）のGo注入は現時点でもOBIではなくgo-instrumentation（v0.24.0）ベース**。
  OBIへの切り替え計画は未確認
- 出典: https://opentelemetry.io/docs/platforms/kubernetes/operator/automatic/

### 執筆時の要注意（誤りやすい点）

- contrib計装系（otelhttp、otelgrpc、autoexport、autoprop）は同一実験セットv0.70.0、
  本体はv1.45.0系（logのみv0.21.0）という対応関係
- eBPFは「go-instrumentation（公式には現役だが実質停滞）→ OBI（主戦場、v0）」、
  ビルド時は「otelc v1（stable）」が2026年8月の構図
- CPS実装は旧ドラフト準拠。現行仕様との乖離に注意
