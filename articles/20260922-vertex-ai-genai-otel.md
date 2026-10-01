---
title: "Vertex AIとGeminiを呼ぶアプリケーションをOpenTelemetryのGenAI規約で計装する"
emoji: "🔭"
type: "tech"
topics: ["OpenTelemetry", "GoogleCloud", "Observability", "Gemini", "LLM"]
published: false
---

:::message
一次情報を確認した日付は2026年9月22日です。以降に変わる可能性が高い箇所には、本文でその都度断りを入れています。

- GenAIセマンティック規約: [open-telemetry/semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai) のコミット `cc07f72`。リポジトリの作成は2026年5月5日で、この日付の時点でタグもリリースも切られていません
- 計装ライブラリ: [`opentelemetry-instrumentation-google-genai`](https://pypi.org/project/opentelemetry-instrumentation-google-genai/) 1.1b1（2026年8月21日リリース）と [`opentelemetry-util-genai`](https://pypi.org/project/opentelemetry-util-genai/) 1.1b0。属性名と属性値についての記述は、この2つのタグのソースを読んで確認したものです
- 送信先: Google Cloudの [Telemetry (OTLP) API](https://docs.cloud.google.com/stackdriver/docs/reference/telemetry/overview)、および[OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/) v0.161.0
:::

## はじめに

以前、[Claude CodeとCodex CLIのテレメトリーをGrafana Cloudで見る](https://zenn.dev/ymotongpoo/articles/20260616-ai-cli-otel-grafana)という記事を書きました。あのときは計装済みのツールが吐き出すテレメトリーを受けて見るだけの話で、自分でLLMを呼ぶアプリケーションに何をどう仕込むかは扱っていません。Google CloudでGeminiを呼ぶアプリケーションを組むとき、OpenTelemetryのGenAIセマンティック規約[^semconv]はどこまでを決めてくれて、どこから先は自分で決める必要があるのか。その境目を一次情報で確かめたのが本記事です。

[^semconv]: セマンティック規約（semantic conventions）は、スパンやメトリクスに付ける属性の名前と意味をOpenTelemetryが定めた辞書です。同じ意味のデータに同じ属性名を使うことで、バックエンド側がベンダーやライブラリを問わず同じクエリで扱えるようになります。逆に、規約が定めていない項目を独自の名前で付けると、ダッシュボードやアラートが自分の組織の中でしか通用しなくなります。

## TL;DR

GenAI規約は、レイテンシー、トークン数、モデルの識別子、エラーの分類、そして操作の種別までを属性とメトリクスの名前として決めています。属性名ごと規約の外にあるのは費用と、プロバイダー固有の生成パラメーターです。一方でプロンプトのテンプレート名やバージョン、業務上の会話単位の識別子は、属性名としては規約にあります。ただし値を用意して計装へ渡すのはアプリケーション側の責任なので、何もしなければ空のままになります。そして規約の安定度はすべて Development で、専用リポジトリへ分離された直後でリリースも切られていないため、属性名の変更に追従できる構成にしておく必要があります。プロンプトとレスポンスの本文は規約自身が Opt-In に分類していて、デフォルトでは取得されません。

## 製品名の改称と属性値のずれ

なお、Google Cloudは2026年に入ってVertex AIを [Gemini Enterprise Agent Platform](https://cloud.google.com/products/gemini-enterprise-agent-platform)（formerly Vertex AI）へ改称し、[名称の対応表](https://docs.cloud.google.com/gemini-enterprise-agent-platform/vertex-ai-name-changes)を公開しています。[Python用のGenAI SDK](https://github.com/googleapis/python-genai) も、クライアント生成のフラグが `enterprise=True` と環境変数 `GOOGLE_GENAI_USE_ENTERPRISE` になり、従来の `vertexai` は旧来のフラグとして残っています。一方でOpenTelemetry側の属性値は `gcp.vertex_ai` のままで、規約の脚注には `aiplatform.googleapis.com` のエンドポイントへアクセスするときに使うと書かれています。本記事は、読者が現在のGoogle Cloudのドキュメントを探せるようにタイトルと本文で「Vertex AI」を使い、改称の事実はここで示すだけにします。

属性値のずれはもう一段あります。規約が `gen_ai.provider.name` の値として列挙しているのは `gcp.vertex_ai` ですが、`opentelemetry-instrumentation-google-genai` 1.1b1 が実際に設定する値は `vertex_ai` です。この計装は `GenAiSystemValues.VERTEX_AI` という列挙子の名前を小文字にした文字列を組み立てていて、Geminiの公開エンドポイントを叩いている場合は `gemini` になります。規約の列挙とは接頭辞の `gcp.` の分だけ食い違うので、規約どおりの値でクエリを書くつもりなら、どこかで揃える必要があります。本記事では後述のCollectorの設定でこれを揃えます。

## 規約が決めていること

GenAI規約は2026年5月に [semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai) という専用のリポジトリへ分離されました。従来 `opentelemetry.io` にあった `gen-ai` 配下のページは移動の告知だけになっています。移行の途中にあるため、この日付の時点ではタグもリリースも作られていません。ドキュメントの `Status` はいずれも Development で、`gen_ai.*` の属性はすべて Development の表示が付いています。安定しているのは `error.type`、`server.address`、`server.port` のように、GenAI以外の規約から借りてきた属性だけです。

推論を1回行うスパンは、スパン名を `{gen_ai.operation.name} {gen_ai.request.model}` にし、スパンの種別を `CLIENT` にします。必須の属性は2つだけです。`gen_ai.operation.name` は操作の種別で、`chat`、`generate_content`、`text_completion`、`embeddings`、`create_agent`、`invoke_agent`、`execute_tool` などの値が列挙されています。Geminiの `generateContent` を呼ぶなら `generate_content` にあたります。`gen_ai.provider.name` はプロバイダーの識別子で、Googleに関する値は2つあります。`gcp.vertex_ai` は `aiplatform.googleapis.com` へアクセスするとき、`gcp.gen_ai` はどのバックエンドかが分からないときに使うと規約の脚注が定めています。

残りは条件付き必須か推奨です。よく使うものを挙げると、モデルの識別に `gen_ai.request.model` と `gen_ai.response.model`、トークン数に `gen_ai.usage.input_tokens` と `gen_ai.usage.output_tokens`、打ち切られたかどうかの判定に `gen_ai.response.finish_reasons`、プロバイダー側のIDと照合するための `gen_ai.response.id` があります。推論を強めたときに消費される分は `gen_ai.usage.reasoning.output_tokens`、プロバイダー側のキャッシュに当たった分は `gen_ai.usage.cache_read.input_tokens` と `gen_ai.usage.cache_write.input_tokens` で、それぞれ別の属性です。エラーは `error.type` で分類し、規約は「プロバイダーまたはクライアントライブラリが返したエラーコード、例外の正式名、あるいは別の低カーディナリティな識別子と一致させるべき」としています。

メトリクスは2つを押さえておけば大半の用途に足ります。`gen_ai.client.token.usage` は単位 `{token}` のヒストグラムで、`gen_ai.token.type` 属性に `input` か `output` を入れて入出力を区別します。`gen_ai.client.operation.duration` は単位 `s` のヒストグラムです。ストリーミングを使うなら `gen_ai.client.operation.time_to_first_chunk` と `gen_ai.client.operation.time_per_output_chunk` が別に定義されていて、最初のチャンクまでの待ち時間と、そのあとの1チャンクあたりの時間を分けて見られます。体感の遅さが生成の開始待ちなのか生成そのものなのかは、この2つを分けないと判別できません。

## アプリケーション側に残る部分

費用が規約に含まれていません。トークン単価はモデル、リージョン、契約形態で変わり、しかも時間とともに改定されるので、使用量を捨てて金額だけをテレメトリーに残すと、単価が改定されたあとで過去の分を再計算できなくなります。使用量をそのまま送り、単価表はダッシュボードやクエリの側に置いて後段で掛ける形にすれば、単価の改定に追従できます。

ただし、この掛け算で出るのは通常の入出力単価による概算です。`gen_ai.client.token.usage` の属性は `gen_ai.token.type` で入出力を区別するだけで、規約が値として列挙しているのは `input` と `output` の2つだけです。プロバイダー側のキャッシュに当たった分はスパンの `gen_ai.usage.cache_read.input_tokens` と `gen_ai.usage.cache_write.input_tokens` に入りますが、これらがメトリクスの属性へ自動で引き継がれるわけではありません。入出力の2区分へ集約したあとで、キャッシュの読み出しと書き込みという別の料金区分を取り出すことはできません。キャッシュの効果を金額として見たいなら、料金区分ごとの独自メトリクスを足すか、請求明細と照合する手順を別に用意します。金額をアプリケーション側で出す場合は、規約に無い属性だと分かる名前空間を自分で切ります。

プロンプトテンプレートの管理は、属性名は規約にあるものの値が埋まらないことが多い部分です。`gen_ai.prompt.name` と `gen_ai.prompt.version` は名前付きのテンプレートを使っているときの条件付き必須で、後者はさらに前者が設定済みでバージョンが取れる場合に限られます。テンプレートをどこで管理し、その名前とバージョンを計装へどう渡すかはアプリケーション側で決めることなので、規約に属性があるだけでは埋まりません。

業務上の会話単位も同様です。`gen_ai.conversation.id` の条件付き必須の条件は「計装対象のライブラリが識別子をすぐに用意できる場合、またはアプリケーションがOpenTelemetryのコンテキスト経由で渡した場合」に限られます。規約は「識別子が無いときに新しいUUIDやトレースIDやリクエスト内容のハッシュを代替値として使うべきではない」と明記しているので、無い場合は空にしておくのが規約に沿った振る舞いです。計装が識別子を持っていない構成では、アプリケーションがコンテキストへ載せるまでこの属性は埋まりません。

生成パラメーターのうちプロバイダー固有のものは、計装ライブラリが独自の名前空間に置きます。`opentelemetry-instrumentation-google-genai` は `GenerateContentConfig` の項目を `gcp.gen_ai.operation.config.*` に記録し、`OTEL_GOOGLE_GENAI_GENERATE_CONTENT_CONFIG_INCLUDES` と `OTEL_GOOGLE_GENAI_GENERATE_CONTENT_CONFIG_EXCLUDES` で取得対象を選ばせます。デフォルトではどの項目も記録されません。

ここを整理しておくと、規約が変わったときに直す範囲が分かります。`gen_ai.*` の属性名は上流の変更に追従する対象で、その値を用意する処理と、自分で決めた名前空間は自分で管理する対象です。

## プロンプトとレスポンスの扱い

規約は、システム指示、入力メッセージ、出力メッセージを機微なデータとして扱っています。ただし本文を含み得る属性はこの3つに限りません。確認したコミットで要求レベルが `Opt-In` になっている属性は11個あります。会話の本文にあたる `gen_ai.system_instructions`、`gen_ai.input.messages`、`gen_ai.output.messages`、テンプレートの変数が入る `gen_ai.prompt.variable.<key>`、ツールに関する `gen_ai.tool.definitions`、`gen_ai.tool.call.arguments`、`gen_ai.tool.call.result`、検索と記憶に関する `gen_ai.retrieval.query.text`、`gen_ai.retrieval.documents`、`gen_ai.memory.query.text`、`gen_ai.memory.records` です。ユーザーの入力がツールの引数として渡る構成では、メッセージの属性を止めても `gen_ai.tool.call.arguments` から同じ内容が出ていきます。規約の本文は「OpenTelemetryの計装はこれらをデフォルトでは取得すべきではないが、利用者が明示的に有効化する手段を提供すべき」としています。そして取りうるやり方を3つ示しています。なお、固定版のPython計装では `NO_CONTENT` にしてもツール定義の説明文字列が残るケースを実測したため、ツール定義を本文と同じ機微情報として扱う場合は、ツール定義へ機微情報を入れないか、Collector側の追加処理を併用してください。

1. 取得しない（デフォルト）
2. スパンの属性として記録する。テレメトリーの量が扱える範囲にあり、プライバシー上の規制が適用されないか、テレメトリーの保管先が規制を満たしている場合に向く。規約は本番前の環境を例に挙げています
3. 本文を外部のストレージに保存し、スパンには参照だけを記録する。テレメトリーの量が問題になる本番環境、または機微なデータを分離したアクセス制御の下に置く必要がある場合に向く

3番目のやり方について、規約は計装がアップロード用のフックを提供してよいとしていて、そのフックは属性の取得を制御するOpt-Inのフラグとは独立に動くべきだとしています。加えて「フックが設定されている場合、スパンのサンプリングの判定に関わらず呼び出すべき」とも書かれています。サンプリングで捨てられたリクエストの本文も保存されるという意味なので、監査目的で本文を残したい場合には都合がよく、逆にサンプリングで保存量を抑えたい場合には想定と違う動きになります。

Pythonの実装はこのやり方をそのまま環境変数に落としています。本文の取得は `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` で切り替え、値は `NO_CONTENT`（デフォルト）、`SPAN_ONLY`、`EVENT_ONLY`、`SPAN_AND_EVENT` の4つです。外部ストレージへのアップロードは `OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK` にフックの名前を入れて有効にし、保存先は [fsspec](https://filesystem-spec.readthedocs.io/) 互換のURIで `OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH` に指定します。

Google Cloudのドキュメントは、この組み合わせをCloud Storageへの保存として案内しています。[マルチモーダルなプロンプトとレスポンスを収集して表示する](https://docs.cloud.google.com/stackdriver/docs/instrumentation/collect-view-multimodal-prompts-responses)では、GenAI規約のバージョン1.37.0に沿った形式で保存するとして、次の環境変数を挙げています。同じページは、プロンプトとレスポンスの全文が収集されることを明記したうえで、機微なデータの扱いには [Model Armor](https://docs.cloud.google.com/security-command-center/docs/model-armor-overview) と [Sensitive Data Protection](https://docs.cloud.google.com/sensitive-data-protection) を使うよう案内しています。

```bash
export OTEL_SEMCONV_STABILITY_OPT_IN='gen_ai_latest_experimental'
export OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK='upload'
export OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH='gs://BUCKET/PATH'
export OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT='jsonl'
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT='NO_CONTENT'
```

注目してほしいのは最後の1行です。アップロードのフックを有効にしたうえで、スパンとイベントへの本文の埋め込みは `NO_CONTENT` で止めています。本文はCloud Storageのバケットにだけ置かれ、トレースの保管先には流れません。バケットのIAMで閲覧者を絞れるので、テレメトリーを見る権限と会話の本文を見る権限を分けられます。

もう1点、規約が注記していることがあります。入出力メッセージの属性は構造を持つ値ですが、構造付きの属性はイベントやログでは扱えてもスパンではまだ扱えない言語があります。規約は「スパンで構造付き属性がまだ使えない言語では、スパン上ではJSON文字列に直列化し、イベント上では構造のまま記録すべき」としています。バックエンドでJSON文字列として届くのか構造として届くのかが言語によって変わるので、ダッシュボードを組む前にどちらで届いているかを確かめておく必要があります。

## 計装の実装

Python用の計装パッケージは、2026年に入ってから配置が変わっています。従来 `opentelemetry-python-contrib` にあったGenAI関連のパッケージは [opentelemetry-python-genai](https://github.com/open-telemetry/opentelemetry-python-genai) へ移り、Gemini向けには `opentelemetry-instrumentation-google-genai` が置かれています。一方、旧来の `opentelemetry-instrumentation-vertexai` はcontrib側に残ったまま非推奨になり、READMEに「このパッケージはGenAIパッケージの移行に伴い非推奨です。`opentelemetry-python-genai` リポジトリへは移行されず、そちらに代替パッケージを作る予定もありません」と書かれています。

ここで注意が要ります。Google Cloudの [ADKアプリケーションをOpenTelemetryで計装する](https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk) は、導入するパッケージとして `opentelemetry-instrumentation-vertexai>=2.0b0` を挙げています。上流が非推奨としたパッケージが、Google Cloud側の手順にはまだ残っている状態です。どちらが自分の環境で必要かは、呼び出しに使っているSDKで決まります。`google-genai` を使うなら `opentelemetry-instrumentation-google-genai`、旧来の `google-cloud-aiplatform` の `vertexai` モジュールを使うならcontrib側になりますが、後者は非推奨なので新規に組むなら前者に寄せる判断になります。

計装を有効にする呼び出しは1行ですが、それだけではテレメトリーは出ていきません。`GoogleGenAiSdkInstrumentor().instrument()` はSDKのメソッドにフックを入れるだけで、`TracerProvider`、`MeterProvider`、`LoggerProvider` とエクスポーターを設定するわけではありません。プロバイダーを設定しないまま動かすと、計装はデフォルトのNo-opのプロバイダーを引き当てるので、スパンもメトリクスも生成されないまま捨てられます。

短く済ませるなら `opentelemetry-instrument` コマンド経由で起動する形で、送信先とプロトコルを環境変数で渡せます。

```bash
export OTEL_SERVICE_NAME=poem-app
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
opentelemetry-instrument python app.py
```

スクリプトの中で初期化するなら、プロバイダーとエクスポーターを組んでから計装を有効にし、プロセスが終わる前にフラッシュします。

```python
from google import genai
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.google_genai import (
    GoogleGenAiSdkInstrumentor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

resource = Resource.create({"service.name": "poem-app"})

# エクスポーターの送信先は OTEL_EXPORTER_OTLP_ENDPOINT から読む。
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(tracer_provider)

meter_provider = MeterProvider(
    resource=resource,
    metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
)
metrics.set_meter_provider(meter_provider)

GoogleGenAiSdkInstrumentor().instrument()

client = genai.Client(enterprise=True, project="PROJECT_ID", location="global")
response = client.models.generate_content(
    model="gemini-flash-latest",
    contents="OpenTelemetryについて短い詩を書いてください。",
)
print(response.text)

# 終了前に送信を完了させる。
tracer_provider.shutdown()
meter_provider.shutdown()
```

本文をイベントとして出す設定（後述の `EVENT_ONLY` と `SPAN_AND_EVENT`）を使うなら、`LoggerProvider` の初期化も同じように足します。この例はトレースとメトリクスだけを送る構成なので、イベントの送信先がありません。

これで `generate_content` と `embed_content`、`interactions.create` の呼び出しにスパンが付き、メトリクスが出ます。ただしREADMEが挙げている制限を把握しておく必要があります。`generate_content` で自動関数呼び出しを有効にしている場合、SDKが実行したツール呼び出しごとに `execute_tool` スパンが作られ、`generate_content` スパンの子になります。逆に自動関数呼び出しを切ってアプリケーション側で関数を呼ぶ形にすると、この計装からは追跡できません。また `interactions` と `embed_content` は計装されたのが新しく、READMEが実験的な扱いだと明示しています。`interactions` APIは自動関数呼び出しに対応していないため、`execute_tool` スパンは作られません。

つまり、エージェント的な処理をアプリケーション側のループで書いている場合、ツール実行のスパンは自分で作ることになります。規約側には材料が揃っています。ツール実行には `execute_tool` スパンと `gen_ai.execute_tool.duration` メトリクスがあります。エージェント呼び出しには `gen_ai.invoke_agent.duration`、`gen_ai.invoke_agent.inference_calls`、`gen_ai.invoke_agent.tool_calls` の3つが、ワークフロー単位には `gen_ai.invoke_workflow.duration` が定義されています。1回のエージェント呼び出しが何回モデルを叩いて何回ツールを呼んだかは、この2つのヒストグラムで分布として見られます。

## 収集の設計

送信経路は2つに分かれます。トレースとメトリクスはOTLPで Telemetry (OTLP) API へ送れます。エンドポイントは `telemetry.googleapis.com` で、リージョン別の `telemetry.REGION.rep.googleapis.com` もあります。`otlphttp` で送る場合はベースURLだけ指定すれば `/v1/traces` などが自動で付きます。ログについては、ADKの手順が [`opentelemetry-exporter-gcp-logging`](https://pypi.org/project/opentelemetry-exporter-gcp-logging/) を使ってCloud Logging APIを直接呼ぶ構成を案内しています。

アプリケーションから直接送るのではなく、Collectorを1段挟む構成を採ると、規約が Development である間の逃げ道が確保できます。属性名や属性値が変わったときにアプリケーションを再デプロイせずに [Transformプロセッサー](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/transformprocessor)で読み替えられますし、本文が混入したときの最後の関門を [Redactionプロセッサー](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/redactionprocessor)で作れます。

```yaml
extensions:
  googleclientauth:
    project: PROJECT_ID

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  # Telemetry APIのメトリクスにプロジェクトとロケーションを渡す。
  # REGIONは、送信するアプリケーションのリージョンへ置き換える。
  resource/gcp:
    attributes:
      - key: gcp.project_id
        value: PROJECT_ID
        action: upsert
      - key: cloud.region
        value: REGION
        action: upsert
  # 計装が出す値を規約の列挙へ揃える。対象は計装スコープと元の値で絞る。
  transform:
    error_mode: ignore
    trace_statements:
      - set(span.attributes["gen_ai.provider.name"], "gcp.vertex_ai")
          where instrumentation_scope.name == "opentelemetry.instrumentation.google_genai"
          and span.attributes["gen_ai.provider.name"] == "vertex_ai"
      - set(span.attributes["gen_ai.provider.name"], "gcp.vertex_ai")
          where instrumentation_scope.name == "opentelemetry.util.genai.handler"
          and span.attributes["gen_ai.provider.name"] == "vertex_ai"
    metric_statements:
      - set(datapoint.attributes["gen_ai.provider.name"], "gcp.vertex_ai")
          where instrumentation_scope.name == "opentelemetry.instrumentation.google_genai"
          and datapoint.attributes["gen_ai.provider.name"] == "vertex_ai"
      # opentelemetry-util-genai 1.1b0が作るメトリクスの実測スコープ。
      - set(datapoint.attributes["gen_ai.provider.name"], "gcp.vertex_ai")
          where instrumentation_scope.name == "opentelemetry.util.genai.handler"
          and datapoint.attributes["gen_ai.provider.name"] == "vertex_ai"
  # 本文を含み得る属性を遮断する。SDK側の設定をすり抜けたときの関門。
  redaction:
    allow_all_keys: true
    blocked_key_patterns:
      - '^gen_ai\.system_instructions$'
      - '^gen_ai\.input\.messages$'
      - '^gen_ai\.output\.messages$'
      - '^gen_ai\.prompt\.variable\..+$'
      - '^gen_ai\.tool\.definitions$'
      - '^gen_ai\.tool\.call\.(arguments|result)$'
      - '^gen_ai\.retrieval\.(query\.text|documents)$'
      - '^gen_ai\.memory\.(query\.text|records)$'
  batch:
    send_batch_size: 512

exporters:
  otlphttp/gcp:
    endpoint: https://telemetry.googleapis.com
    auth:
      authenticator: googleclientauth

service:
  extensions: [googleclientauth]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [resource/gcp, transform, redaction, batch]
      exporters: [otlphttp/gcp]
    metrics:
      receivers: [otlp]
      processors: [resource/gcp, transform, batch]
      exporters: [otlphttp/gcp]
```

Telemetry APIへメトリクスを送るときは、プロジェクトIDだけでなくロケーションもリソース属性から解決できるようにします。OTLPメトリクスはCloud Monitoringの `prometheus_target` として格納され、`location` は `cloud.availability_zone`、`cloud.region` などから決まります。`location` を解決できないと、今回の実測では `Unrecognized region or location` のHTTP 400になりました。`REGION` はアプリケーションを動かすリージョンへ置き換え、`service.instance.id` などのインスタンス識別子も失わないようにしてください。トレースだけを送る場合、このロケーション要件はメトリクスほど直接的には現れません。

Transformプロセッサーの書き方は、OTTLのステートメントを文字列として並べる形です。`span.attributes` や `datapoint.attributes` のように接頭辞の付いたパスを書くと、プロセッサーがコンテキストを推論します。`context` と `statements` を入れ子にする書き方も残っていますが、READMEはそちらを複雑な場合向けの上級の設定としています。

条件を計装スコープと元の値の2つで絞っているのは、属性が無いことだけを条件にすると、HTTPやプロセスのメトリクスにも、別のプロバイダーを使っている経路のデータにも当たってしまうためです。ここでやっているのは値の推定ではなく、確認済みの値を確認済みの別の値へ読み替える処理だけです。計装を替えたりバージョンを上げたりしたときは、スコープ名と実際に出ている値を確認し直す必要があります。

Redactionプロセッサーは、書いた分だけを処理するという限界に加えて、既定では一致した値を削除せずマスクします。v0.161.0で確認した設定では、上に列挙したキーのスパン属性だけでなく、イベント属性とmap形式のログボディも対象になりました。一方、未知のキーやscalar形式のボディはこの設定では通ります。削除が要件なら、RedactionだけでなくOTTLの `delete_matching_keys` などを追加し、削除結果を別途テストしてください。ログパイプラインを構成していない場合、ログレコードについての設定は実際には適用されません。
したがって、本文を保存しない方針を実現する主たる手段はSDK側の `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT` であり、このプロセッサーはその設定を取りこぼしたときの補助です。何も通さないことを保証したいなら、`allow_all_keys` を `false` にして `allowed_keys` に通す属性を列挙する許可リスト方式にします。この方式なら未知の属性はデフォルトで落ちますが、`gen_ai.*` 以外の属性も含めて一覧を保守し続けることになります。

カーディナリティの見積もりも収集の設計に含まれます。`gen_ai.client.token.usage` の必須属性は `gen_ai.operation.name`、`gen_ai.provider.name`、`gen_ai.token.type` の3つです。ここに条件付き必須の `gen_ai.request.model` が加わり、さらに推奨として `gen_ai.response.model` と `server.address` と `server.port` が乗ります。`gen_ai.response.model` はスナップショット付きのモデル名が入るので、モデルが更新されるたびに系列が増えます。増えること自体は望ましくて、更新の前後でレイテンシーやトークン消費が変わったかを比べられるようになります。一方、`gen_ai.conversation.id` や `gen_ai.response.id` のような1リクエストごとに異なる値を、メトリクスの属性に足してはいけません。これらはスパンの属性として持たせ、メトリクスからはエグゼンプラー経由でトレースへ辿る形にします。

## おわりに

GenAI規約は、LLMの呼び出しを観測するための語彙のうちレイテンシー、トークン、モデルの識別、エラーの分類までを埋めていて、費用については属性もメトリクスも持たないことを確認しました。プロンプトのテンプレート名や業務上の会話単位の識別子は属性名だけが用意されていて、値を供給するのはアプリケーション側の仕事です。

規約の開発は、専用リポジトリへの分離とPythonパッケージの移設が同時に進んでいる状態です。`gen_ai.provider.name` の値が規約の列挙と計装の実装でずれていたように、この時期は属性名だけでなく属性値も動きます。当面は `gen_ai.*` をアプリケーションのコードに直接書くのではなく、計装ライブラリに任せてCollectorで読み替える余地を残しておく、という認識で良さそうです。

## 出典

- [Semantic conventions for generative client AI spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/cc07f722069974139dab497d80d145144b19daca/docs/gen-ai/gen-ai-spans.md)
- [Semantic conventions for generative AI metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/cc07f722069974139dab497d80d145144b19daca/docs/gen-ai/gen-ai-metrics.md)
- [Semantic Conventions for GenAI agent and framework spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/cc07f722069974139dab497d80d145144b19daca/docs/gen-ai/gen-ai-agent-spans.md)
- [OpenTelemetry Google GenAI SDK Instrumentation](https://github.com/open-telemetry/opentelemetry-python-genai/tree/main/instrumentation/opentelemetry-instrumentation-google-genai)
- [Instrument generative AI applications](https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-overview)
