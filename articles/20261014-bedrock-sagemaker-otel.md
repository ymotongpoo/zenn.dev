---
title: "Amazon BedrockとSageMakerのAIエージェントでOpenTelemetryの自動計装が行われる範囲"
emoji: "🛰️"
type: "tech"
topics: ["OpenTelemetry", "AWS", "Bedrock", "SageMaker", "Observability"]
published: true
published_at: 2026-10-14 09:00
---

:::message
一次情報は2026年10月13日の時点のものを確認しました。AWSのサービス側の仕様もOpenTelemetry側の規約も動いている最中なので、採用前に同じページを読み直してください。本文のうち実際に動かして確かめた部分も同じ日に実施したもので、リージョンとバージョンを該当箇所か脚注に書いています。対象にした一次情報と検証環境は次のとおりです。

- GenAI規約のBedrock関連: [semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai) のコミット `5293eff` の `docs/gen-ai/aws-bedrock.md` で、安定度は Development
- 計装: [`opentelemetry-instrumentation-botocore`](https://pypi.org/project/opentelemetry-instrumentation-botocore/) 0.66b1のBedrock Runtime拡張と、[opentelemetry-python-genai](https://github.com/open-telemetry/opentelemetry-python-genai) の [`opentelemetry-instrumentation-genai-bedrock`](https://pypi.org/project/opentelemetry-instrumentation-genai-bedrock/) 1.2b0
- AWS側: [AWS Distro for OpenTelemetry](https://aws-otel.github.io/)（ADOT）Python `aws-opentelemetry-distro` 0.18.0以降と、[CloudWatchのOTLPエンドポイント](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPEndpoint.html)
- Collector: [OpenTelemetry Collector Contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib) の `otelcol-contrib` v0.161.0で動作を確認（執筆時点の最新はv0.162.0）
:::

## はじめに

AWS上で生成AIを使う構成を「Bedrockのエージェント」と一括りに呼んでしまうと、計装の話がかみ合わなくなります。モデルを1回呼ぶだけの [Amazon Bedrock](https://aws.amazon.com/jp/bedrock/) のRuntime API、自分で用意したモデルをホストする [Amazon SageMaker AI](https://aws.amazon.com/jp/sagemaker/) のエンドポイント、そしてエージェントの実行そのものをAWS側が受け持つ [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/) は、自動で計装できる範囲もトレースの切れ目も違います。どのスパンや属性が自動計装で付き、どれを自分のコードで書き足す必要があるのかを、一次情報と実際の呼び出しで確かめたのが本記事です。

本記事では、Pythonのアプリケーションから [AWS SDK for Python（boto3）](https://aws.amazon.com/jp/sdk-for-python/) でこれらを呼ぶ場合を扱います。基準にするのは [OpenTelemetry](https://opentelemetry.io/ja/)[^otel] の生成AI向けのセマンティック規約（以下、GenAI規約）[^genai] です。規約の共通部分の説明は最小限にとどめ、AWS固有の部分、とくにサービスをまたぐトレースコンテキストの伝播と、プロンプトの本文をどこに置くかに紙幅を割きます。

[^otel]: OpenTelemetryは、トレース、メトリクス、ログといったテレメトリーを生成して送るためのAPI、SDK、ツール群を定めるCNCFのプロジェクトです。処理の1区間の記録を**スパン**、リクエストを起点にしたスパンのつながりを**トレース**と呼びます。スパンを親子でつなぐための識別子（トレースIDと親のスパンID）を**トレースコンテキスト**と呼び、サービスをまたいでトレースをつなぐには、これを呼び出し先へ渡す必要があります。ライブラリーにフックを入れて、アプリケーションのコードを書き換えずにテレメトリーを出すことを**自動計装**と呼びます。

[^genai]: セマンティック規約は、テレメトリーに付ける属性やメトリクスの名前と値を定めたOpenTelemetryの仕様です。生成AIの呼び出しを扱う部分は、[semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai) という専用のリポジトリで策定されています。

## TL;DR

Bedrockのモデル呼び出しは、自動計装でスパンとメトリクスが出ます。ただしPython向けの計装ライブラリーは2つあり、広く使われてきたboto3向けのものが出すのは旧規約の属性名です。SageMaker AIのエンドポイントは自動計装の対象外で、HTTPヘッダーで送ったトレースコンテキストもコンテナに届かないので、`CustomAttributes` というパラメーターに載せて渡します。AgentCoreでは、AWSのドキュメントがADOT Collectorに対応しないとしているので、Collector[^collector]を経由せずSDKから直接送る構成になります。

[^collector]: [OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/)は、アプリケーションからテレメトリーを受け取り、加工してから送信先へ転送するプログラムです。ADOT（AWS Distro for OpenTelemetry）は、AWSが配布するOpenTelemetryのSDKとCollectorのディストリビューションです。

## 3つの呼び出しを区別する

PythonのアプリケーションからAWSの生成AI関連のサービスを呼ぶ場合、呼び出しはBedrockのモデル呼び出し、SageMaker AIのエンドポイント、AgentCoreのエージェントの3種類に分かれます。呼び出しの種類ごとに、計装の性質が変わります。

| 呼び出し | 対象API | 自動計装の範囲 | 手で書く部分 |
| --- | --- | --- | --- |
| Bedrockのモデル呼び出し | `Converse`、`ConverseStream`、`InvokeModel`、`InvokeModelWithResponseStream` | スパン、イベント、メトリクス。InvokeModel系は対応モデルが限られる | 会話単位の識別子、費用 |
| SageMaker AIのエンドポイント | `InvokeEndpoint` | AWS SDKの汎用クライアントスパンのみ | モデルの識別、トークン数、コンテナ内部の処理、コンテキストの伝播 |
| AgentCoreのエージェント | `InvokeAgentRuntime` ほか | AgentCore側が組み込みのメトリクスとスパンを出す。アプリ側はADOT SDKで追加 | フレームワーク固有のツール実行、セッションの紐付け |

Bedrockについては、GenAI規約に専用のページがあります。`docs/gen-ai/aws-bedrock.md` は共通のスパン規約を拡張する形で、`gen_ai.provider.name` を `"aws.bedrock"` に固定し、しかも「スパンの生成時に設定すべき」と指定しています。属性としてはガードレールの識別子 `aws.bedrock.guardrail.id` とナレッジベースの識別子 `aws.bedrock.knowledge_base.id` が追加されています。共通規約側の `gen_ai.conversation.id` の注記には、バックエンドで会話を保持するライブラリの例として [Bedrockのエージェントセッション](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-session-state.html)が挙げられています。

Bedrockのモデル呼び出しに使うBedrock Runtime APIには、4つのAPIがあります。モデルの違いを吸収した共通の形式でメッセージを送る [Converse](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html) と、その応答をストリームで受け取る [ConverseStream](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html)、モデルごとの形式のJSONをそのまま送る [InvokeModel](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html) と、そのストリーム版の [InvokeModelWithResponseStream](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModelWithResponseStream.html) です。

これらを計装するPythonのライブラリーは、現在2つあります。1つ目は、OpenTelemetryのPython向け計装ライブラリーを集めた [opentelemetry-python-contrib](https://github.com/open-telemetry/opentelemetry-python-contrib) リポジトリにある `opentelemetry-instrumentation-botocore` です。boto3とその下層のbotocoreの呼び出しを計装するライブラリーで、Bedrock Runtime用の拡張を持ち、READMEによると4つのAPIについてGenAI規約を実装しています。ただしInvokeModelとInvokeModelWithResponseStreamについては、トレースとイベントとメトリクスが実装されているのがAmazon Titan、Amazon Nova、Anthropic Claudeに限られます。他のモデルをInvokeModelで呼んでいる場合は、属性が埋まらない前提での見積もりが必要です。

ここで、規約の定義と実装の出力を分けて見る必要があります。上で挙げた `gen_ai.provider.name` は、専用リポジトリへ分離された新しい規約の属性です。一方、2026年10月13日の時点で最新の `opentelemetry-instrumentation-botocore` 0.66b1（2026年10月6日リリース）のBedrock拡張が設定するのは、旧規約の `gen_ai.system` で、値は `aws.bedrock` です。同じタグのソースで、スパンとメトリクスの両方がこの属性を使っていることと、新旧を切り替えるオプトインの処理が入っていないことを確認しました[^botocore]。この部分は0.65b0（2026年7月16日リリース）から変わっていません。2026年10月13日に、us-east-1でAmazon Nova Micro（`amazon.nova-micro-v1:0`）を4つのAPIで実際に呼んだところ、0.65b0と0.66b1のどちらでも、4つのスパンすべてに `gen_ai.system` の `aws.bedrock` が付き、`gen_ai.provider.name` は出ませんでした。

[^botocore]: 確認したのはタグ `v0.65b0` と `v0.66b1` の `instrumentation/opentelemetry-instrumentation-botocore/src/opentelemetry/instrumentation/botocore/extensions/bedrock.py` です。バージョンを上げるときは同じファイルを読み直してください。

このライブラリーが設定する `gen_ai.*` の属性は次の10個です。

- `gen_ai.system`
- `gen_ai.operation.name`
- `gen_ai.request.model`
- `gen_ai.request.max_tokens`
- `gen_ai.request.temperature`
- `gen_ai.request.top_p`
- `gen_ai.request.stop_sequences`
- `gen_ai.response.finish_reasons`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`

メトリクスは `gen_ai.client.operation.duration` と `gen_ai.client.token.usage` の2つです。どちらも、2026年9月下旬に規約が推論のメトリクスを `gen_ai.client.inference.duration` と `gen_ai.client.inference.usage.*` のカウンター群へ置き換える前の名前です（トークンのメトリクスの変更は後述の「本文と費用の扱い」で扱います）。規約側にある `gen_ai.response.model` と `gen_ai.response.id`、そしてBedrock専用のページが定義するガードレールとナレッジベースの属性は、この一覧に含まれません。実際の呼び出しでも、この一覧にない `gen_ai.*` の属性は出ませんでした。生成パラメーターの属性のうち付いたのは、リクエストで指定した `gen_ai.request.max_tokens` だけです。イベントとしては `gen_ai.user.message` と `gen_ai.choice` が出ました。新しい規約に揃えたクエリを書くなら、その差はCollectorの側か自分の計装で埋めることになります。

![GrafanaのトレースでBedrockのConverseのスパンを開いた画面。ライブラリーの版は0.65b0で、属性にgen_ai.system=aws.bedrockがあり、gen_ai.provider.nameはない](/images/20261014-bedrock-botocore-span.png)
*0.65b0が出したConverseのスパンをGrafanaで確認した画面。`gen_ai.provider.name` はなく、`gen_ai.system` が付いている*

2つ目は、GenAI関連の計装ライブラリーを集約している `opentelemetry-python-genai` リポジトリの `opentelemetry-instrumentation-genai-bedrock` です。こちらも4つのAPIを対象にしていて、本文の取得を `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` で切り替えられる作りです。2026年9月24日に1.2b0がPyPIで公開され、`pip install` で入れられるようになりました。1.2b0のソースでは、スパンのプロバイダーの識別に新しい規約の `gen_ai.provider.name`（値は `aws.bedrock`）を使っていて、ガードレールの識別子の属性も扱っていることを確認できます[^genai-bedrock]。ただしメトリクスの名前は `gen_ai.client.operation.duration` と `gen_ai.client.token.usage` で、botocoreの計装と同じく規約の変更前のままです。このライブラリーは実際の呼び出しでは試していません。

[^genai-bedrock]: 確認したのは `opentelemetry-instrumentation-genai-bedrock` 1.2b0の `patch.py` と、メトリクスを記録する `opentelemetry-util-genai` 1.2b0の `_instruments.py` です。

スパンの属性を新しい規約に揃えたいなら、genai-bedrockが候補になります。ただし、どちらのライブラリーもbotocoreの `BaseClient._make_api_call` を包んで計装する作りなので、両方を有効にするとBedrockの呼び出しが二重に計装される可能性があります（同時に有効にした場合の動作は確認していません）。使うのはどちらか一方にしてください。以降のコード例は、実際に動かして確かめたbotocoreの計装で示します。genai-bedrockを使う場合は、`opentelemetry.instrumentation.genai.bedrock` の `BedrockInstrumentor` に置き換えます。

計装を有効にするコードは1行です。ただしこの1行はboto3のクライアントにフックを入れるだけで[^sso]、`TracerProvider` と `MeterProvider` とエクスポーターを設定するわけではありません。これらを初期化しないまま動かすと、スパンもメトリクスも生成されないまま捨てられます。次のコードは、SDKとエクスポーターの初期化が済んだ環境に足す部分の抜粋です[^model-id]。ADOTを使う場合は後述の `opentelemetry-instrument` コマンド経由で起動すると、初期化を環境変数で済ませられます。

```python
import boto3
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor

BotocoreInstrumentor().instrument()

client = boto3.client("bedrock-runtime", region_name="us-east-1")
response = client.converse(
    modelId="amazon.nova-micro-v1:0",
    messages=[{"role": "user", "content": [{"text": "Hello, Bedrock!"}]}],
)
```

[^model-id]: このモデルIDをそのまま使えるかはリージョンによります。us-east-1ではこのコードのまま動きましたが、us-east-2ではNova MicroをモデルIDで直接呼べず、推論プロファイルの `us.amazon.nova-micro-v1:0` を指定する必要がありました。

[^sso]: フックはBedrock以外のboto3のクライアントにも入ります。手元のマシンからAWS IAM Identity Center（SSO）のプロファイルで試すと、認証情報を取得する `SSO OIDC.CreateToken` と `SSO.GetRoleCredentials` の呼び出しもスパンになり、最初のBedrockの呼び出しのトレースに子として入りました。属性に秘密情報は載りませんが、トレースが見づらくなります。`instrument()` の前に `boto3.setup_default_session()` を呼んでから `boto3.DEFAULT_SESSION.get_credentials().get_frozen_credentials()` で認証情報を取得しておくと、これらのスパンは出なくなります。

## SageMakerのエンドポイントでのトレースの切れ目

SageMaker AIのリアルタイムエンドポイントは、Bedrockと違って推論の中身がAWSから見えないので、GenAI規約の拡張がありません。`opentelemetry-instrumentation-botocore` の拡張はBedrock Runtime、DynamoDB、Lambda、SNS、SQSの5つで、SageMakerは含まれていません。したがって `InvokeEndpoint` の呼び出しには、AWS SDKとしての汎用スパンだけが付きます。モデルの識別子、入出力のトークン数、生成パラメーターは、アプリケーション側で属性として足すことになります。

そしてコンテキストの伝播に制約があります。[InvokeEndpointのAPIリファレンス](https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_runtime_InvokeEndpoint.html)には次のように書かれています。

> Amazon SageMaker AI strips all POST headers except those supported by the API. Amazon SageMaker AI might add additional headers. You should not rely on the behavior of headers outside those enumerated in the request syntax.
>
> （Amazon SageMaker AIは、APIが対応しているものを除いてPOSTヘッダーをすべて取り除きます。Amazon SageMaker AIが追加のヘッダーを足すこともあります。リクエスト構文に列挙されていないヘッダーの挙動に依存すべきではありません。）

サービス間でトレースコンテキストを受け渡すために [W3C Trace Context](https://www.w3.org/TR/trace-context/) が定めるHTTPヘッダーの `traceparent` は、この列挙に含まれません。実際に、botocoreのイベントフックでHTTPヘッダーに `traceparent` を足して呼ぶと[^sm-test]、ヘッダーはモデルコンテナに届かず、コンテナの中で作ったスパンは呼び出し側とは別のトレースのルートになりました。コンテナが受け取ったヘッダーは `Accept`、`Content-Length`、`Content-Type`、`Host`、`User-Agent`、`X-Amzn-SageMaker-Custom-Attributes`、`X-Amzn-SageMaker-Inference-Id` の7つです。同じboto3をローカルのHTTPサーバーに向けたときには届いていた `Authorization` や `X-Amz-Date` は取り除かれ、boto3が送っていない `Accept` が加わっていました。

![SageMaker AIのコンソールでエンドポイントの概要を開いた画面。種類はReal-timeで、状態はInService](/images/20261014-sagemaker-endpoint-inservice.png)
*検証に使ったリアルタイムのエンドポイントをSageMaker AIのコンソールで確認した画面（ARNは塗りつぶしている）*

[^sm-test]: 2026年10月13日、us-east-2のリアルタイムエンドポイント（ml.t2.medium）で確認。

ワークアラウンドとして `CustomAttributes` が使えます。APIリファレンスは「推論のリクエストに関する追加情報を提供する。この情報は不透明な値としてそのまま転送される。たとえばリクエストを追跡するためのIDを渡す用途に使える」と説明していて、実際に「リクエストの `CustomAttributes` ヘッダーでトレースIDを渡し、レスポンスの `CustomAttributes` ヘッダーで返す」という例をそのまま載せています。リクエスト構文では `X-Amzn-SageMaker-Custom-Attributes` というヘッダーに対応します。制約は、値が1024文字以内の印字可能なUS-ASCIIであること、そしてレスポンスに載せ返すかどうかはモデル側のコードの責任であることです。

W3C Trace Contextのバージョン `00` の形式では、`traceparent` の値は55文字です。この1項目だけを渡すなら1024文字の枠に十分収まります。ただし汎用の `inject()` は、トレースコンテキストを辞書などへ書き出す部品であるプロパゲーターを、設定されたぶんだけまとめて呼びます。デフォルトの `tracecontext,baggage` のままだと、`tracestate` と `baggage` も同じ辞書へ入る可能性があります。`tracestate` とバゲッジの値そのものにカンマが含まれるため、辞書をカンマで連結すると受信側で項目の境界が判別できなくなり、しかも合計が1024文字を超える可能性が出てきます。最小の構成では、トレースコンテキストのプロパゲーターだけを明示して呼び、`traceparent` の1項目を渡します。

```python
import boto3
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)

tracer = trace.get_tracer(__name__)
client = boto3.client("sagemaker-runtime", region_name="us-east-1")

# payload と request_id は呼び出し側で用意する値のプレースホルダー。
payload = b'{"inputs": "Hello, SageMaker!"}'
request_id = "req-0001"

with tracer.start_as_current_span(
    "invoke_endpoint my-llm-endpoint",
    kind=trace.SpanKind.CLIENT,
    attributes={
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "aws.sagemaker",  # 規約の列挙に無い独自の値
        "gen_ai.request.model": "my-llm-endpoint",
    },
) as span:
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    response = client.invoke_endpoint(
        EndpointName="my-llm-endpoint",
        ContentType="application/json",
        Body=payload,
        # ヘッダーでは通らないので CustomAttributes に載せ替える。
        # 1項目だけなので区切り文字の曖昧さが起きない。
        CustomAttributes=carrier.get("traceparent", ""),
        InferenceId=request_id,
    )
    span.set_attribute(
        "aws.sagemaker.invoked_production_variant",
        response["InvokedProductionVariant"],
    )
```

`gen_ai.provider.name` に独自の値を入れている点は意図的です。規約の列挙には `aws.bedrock` はあっても SageMaker に対応する値がなく、規約自身が「いずれかが該当する場合はその値を使わなければならないが、該当しない場合は独自の値を使ってよい」としています。独自の値を入れたことは記録に残しておく必要があります。あとで規約側に値が追加されたら、揃える対象になります。

コンテナ側では、`X-Amzn-SageMaker-Custom-Attributes` ヘッダーの値を辞書へ戻して `extract` に渡し、取り出したコンテキストをスパンの親にします。

```python
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)

tracer = trace.get_tracer(__name__)


def handle(request):
    traceparent = request.headers.get("X-Amzn-SageMaker-Custom-Attributes", "")
    ctx = TraceContextTextMapPropagator().extract({"traceparent": traceparent})
    with tracer.start_as_current_span(
        "infer", context=ctx, kind=trace.SpanKind.SERVER
    ):
        # run_inference はコンテナ側の推論処理のプレースホルダー。
        return run_inference(request)
```

前述のエンドポイントで、呼び出し側とコンテナ側のこの2つのコードを動かすと、コンテナ側のスパンは呼び出し側と同じトレースIDになり、呼び出し側のスパンが親になりました。`traceparent` をHTTPヘッダーと `CustomAttributes` の両方で送った場合も、届いたのは `CustomAttributes` のほうだけで、結果は同じです。

![CloudWatch Logsでコンテナのログを開いた画面。traceparent_headerはnullで、custom_attributesの値とコンテナ側のスパンのtrace IDと親のスパンIDが一致している](/images/20261014-sagemaker-customattributes-log.png)
*ヘッダーと `CustomAttributes` の両方で送ったときにコンテナが記録したログを、CloudWatch Logsで確認したところ。`traceparent` ヘッダーは届かず（`null`）、`CustomAttributes` の値から親を復元している*

値が空だったり形式が合わなかったりした場合、`extract` は無効なコンテキストを返すので、スパンは親を持たない新しいトレースのルートになります。呼び出し側とつながらなかったこと自体は、トレースのルートが2つに分かれる形で後から分かります。

複数の項目を渡す必要があるなら、区切り文字で連ねるのではなくJSONへ符号化します。`json.dumps(carrier)` の結果は印字可能なUS-ASCIIに収まるので `CustomAttributes` の文字種の制約を満たしますが、長さは自分で検査する必要があります。バゲッジに業務上のキーを詰めると1024文字を超える可能性があるので、送信前に長さを確かめて、超える場合は渡す項目を削るか別の経路へ回します。受信側は `json.loads` で辞書へ戻してから `extract` に渡します。`CustomAttributes` は不透明な値としてそのまま転送されるだけなので、符号化と復号の取り決めは呼び出し側とコンテナ側で揃えておくものになります。

レスポンスの `CustomAttributes` に載せ返すかどうかは別の判断です。呼び出し側でコンテナ内のスパンIDを知りたい場合だけ必要になります。

モデルのバージョンについては、レスポンスの `InvokedProductionVariant` ヘッダーがどのプロダクションバリアントで処理されたかを返します。バリアントが1つのエンドポイントでは、エンドポイント設定で付けたバリアント名がそのまま返りました。A/Bテストのために2つのバリアントに重みを付けている場合、この値を属性にしておくとバリアント別にレイテンシーを比べられます。データキャプチャを有効にしているなら `InferenceId`（64文字以内）が記録されたデータに付くので、テレメトリー側の識別子と揃えておくと、あとから両者を照合できます。

## AgentCoreを使うときのCollectorの位置

AgentCoreは、エージェントの実行環境そのものをAWSが提供します。[オブザーバビリティのドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability.html)は「AgentCoreは標準化されたOpenTelemetry（OTEL）互換の形式でテレメトリーを出力する」としていて、デフォルトでセッション数、レイテンシー、実行時間、トークン使用量、エラー率といったメトリクスが出ます。これらはCloudWatchに入ります。

アプリケーションのコード側でスパンを足すには、[設定のドキュメント](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)が案内するとおりADOTのSDKを入れます。

```
aws-opentelemetry-distro>=0.18.0
boto3
```

起動はOpenTelemetryの自動計装コマンド経由になります。

```dockerfile
CMD ["opentelemetry-instrument", "python", "main.py"]
```

Collectorの扱いには制約があります。ドキュメントには「ADOT Collectorはエージェントのオブザーバビリティには対応していません。AgentCoreランタイムの外でホストしたエージェントからテレメトリーを送るには、ADOT SDKかAWS Lambda Layer for OpenTelemetryのどちらかを使う必要があります」という注意書きがあります。この記述が定めているのは、AgentCoreのAgent Observabilityへテレメトリーを届ける公式の手順としてADOT Collectorが対象外だということです。CloudWatchのGenAI Observabilityの画面で見る構成を採るなら、Collectorをゲートウェイとして立ててサンプリングや属性の整形を一箇所に集める形は選べず、整形はSDK側のプロセッサーで行うことになります[^agentcore-otlp]。

[^agentcore-otlp]: この記述から、独自のOTLPの経路が技術的に成り立たないことまでは導けません。同じドキュメントは、ランタイム内で動くエージェントを別のオブザーバビリティのプラットフォームへつなぐ場合に `DISABLE_ADOT_OBSERVABILITY=true` を設定する手順も示していて、これを設定するとランタイムがデフォルトで入れるADOTの環境変数が外れます。送信先を自分で組む余地はそこにあります。ただしその構成でCollectorを挟んだときに何が届くかは、本記事では検証していません。AgentCoreの組み込みのメトリクスとスパンはCloudWatchへ入る前提の仕組みなので、そちらが使えなくなる可能性も含めて、採用前に自分の環境で確かめる部分になります。

ランタイム外のエージェントでは、環境変数でログ先とヘッダーを組み立てます。ドキュメントが挙げている一覧から抜粋します。

```text
AGENT_OBSERVABILITY_ENABLED=true
OTEL_PYTHON_DISTRO=aws_distro
OTEL_PYTHON_CONFIGURATOR=aws_configurator
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_TRACES_EXPORTER=otlp
OTEL_RESOURCE_ATTRIBUTES=service.name=<agent-name>,aws.log.group.names=/aws/bedrock-agentcore/runtimes/<agent-id>
OTEL_EXPORTER_OTLP_TRACES_HEADERS=x-aws-log-group=/aws/bedrock-agentcore/runtimes/<agent-id>,x-aws-log-stream=spans
```

サービスをまたぐコンテキストの伝播については、AgentCoreのランタイムを呼ぶときに付けられるヘッダーが一覧で示されています。`traceparent` と `tracestate` と `baggage` のW3C系、X-Ray形式の `X-Amzn-Trace-Id`、そしてセッションを識別する `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` です。ドキュメントは「OTELはトレースIDが与えられなければ自動生成する」と注記しているので、呼び出し側がW3Cの `traceparent` を送れば上流のトレースにつながります。セッションIDをスパンに載せるには、バゲッジに `session.id` を入れる形が案内されています。

```python
from opentelemetry import baggage, context

token = context.attach(baggage.set_baggage("session.id", session_id))
try:
    # エージェントの処理をここで呼ぶ。
    invoke_agent()
finally:
    context.detach(token)
```

ドキュメントの例は `attach` までで止まっていますが、`detach` を省くと差し替えたコンテキストがそのスレッドに残ります。リクエストごとにワーカーを使い回す構成では、前のリクエストの `session.id` が次のリクエストのスパンに付くので、`attach` が返すトークンを保持して `finally` で戻します。

X-Ray形式とW3C形式が混在する構成では、OpenTelemetryのプロパゲーターを両方登録します。SDKの仕様では `OTEL_PROPAGATORS` のデフォルト値が `tracecontext,baggage` で、サードパーティの値として `xray` が定義されています。

```bash
export OTEL_PROPAGATORS=tracecontext,baggage,xray
```

## 本文と費用の扱い

ADOTには、GenAIの本文をスパンから抜き出す仕組みがあります。`AGENT_OBSERVABILITY_ENABLED` が有効で、かつオプトアウトしていないとき、ADOTのスパンエクスポーターは大きな本文をスパンから取り出してログとして送ります。この動作を止める環境変数が `AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT` です。

```bash
# 本文をスパンに残したいときだけ true にする。
export AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT=true
```

変数名が opt out なので方向を混同しやすいのですが、抜き出しをやめるという意味です。ADOT Pythonの実装では `is_genai_content_extraction_opted_out()` がこの変数を読み、スパンエクスポーターの `export` の中で、有効かつオプトアウトしていない場合にだけ `LLOHandler` がスパンを加工します[^adot]。デフォルトでは本文はログ側に移るので、スパンを見る権限とログを見る権限を分けられます。逆に `true` を設定すると本文がスパンに残るので、トレースの保管先のアクセス制御を確認してから設定する必要があります。

[^adot]: `aws-opentelemetry-distro` の `exporter/otlp/aws/traces/otlp_aws_span_exporter.py` で確認できます。同じファイルから、トレースの送信先が `https://xray.[AWSRegion].amazonaws.com/v1/traces` でSigV4署名を直接注入する形になっていることも読み取れます。

CloudWatchのOTLPエンドポイントを直接使う場合の送信先は、トレースが `https://xray.{リージョン}.amazonaws.com/v1/traces`、ログが `https://logs.{リージョン}.amazonaws.com/v1/logs`、メトリクスが `https://monitoring.{リージョン}.amazonaws.com/v1/metrics` です。3つともHTTPのみでgRPCに対応せず、Collectorから送る場合は [Sigv4 Authエクステンション](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/extension/sigv4authextension)が必要です（ログとメトリクスはBearerトークンでも認証できます）。

トレースのエンドポイントを使うには、先にTransaction Searchを有効にしておく必要があります。[OTLPエンドポイントの手引き](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPGettingStarted.html)には次の注記があります。

> Make sure Transaction Search is enabled before you use the OTLP Endpoint for traces.
>
> （トレースにOTLPエンドポイントを使う前に、Transaction Searchが有効になっていることを確かめてください。）

[Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search.html)はアカウントとリージョン単位の設定です。有効にすると、そのリージョンでX-Rayが受け取るスパンはすべて `aws/spans` というロググループに取り込まれ、料金はCloudWatchの体系になります。X-Rayのトレースサマリーとして検索や分析の対象になるのは、インデックスする割合（デフォルトは1%）のぶんだけです。すでにX-Rayを使っているアカウントでは、他のサービスのトレースの扱いも一緒に変わるので、有効にする前にその利用者と調整することになります。

インデックスの割合が1%のままだと、少数のトレースはX-Rayの画面に出ません。試しに2件のトレースを送ったところ、X-Rayのトレース詳細でも `BatchGetTraces` でも見つからず、`aws/spans` を直接検索するTransaction Searchの画面でだけ確認できました。しかも送ってから検索できるようになるまで約10分かかり、その間は送信に失敗した場合と見分けがつきません。Collectorから送るなら、送信の成否はCollectorの内部メトリクス（`otelcol_exporter_sent_spans` と `otelcol_exporter_send_failed_spans`）で先に確かめておくと切り分けられます。

プロンプトの本文を属性に載せる方針を採るなら、次の上限も先に確かめておく必要があります。

| 上限 | 値 |
| --- | --- |
| トレースの1リクエストあたりの非圧縮サイズ | 5MB |
| トレースの1スパンの最大サイズ | 200KB |
| トレースの1リクエストあたりのスパン数 | 10,000 |
| トレースのリソースとスコープ1組の最大サイズ | 16KB |
| メトリクスの属性の文字列値の最大長 | 1,024文字 |
| メトリクスの1データポイントあたりのラベル数 | 150 |
| ログの1リクエストあたりの非圧縮サイズ | 1MB（一部リージョンで20MB） |

1スパン200KBという制限があるので、長い会話履歴をそのままスパン属性に載せる設計は成り立ちません。本文を残すなら、S3などへ逃してスパンには参照だけを置く形になります。GenAI規約も同じ方針を示していて、外部ストレージへのアップロードをフックで扱うやり方を第3の選択肢として挙げています。

費用については、GenAI規約に属性もメトリクスもありません。Bedrockの単価はモデルとリージョンで変わり、プロビジョンドスループットを契約しているかどうかでも変わります。使用量を捨てて金額だけを残すと単価の改定に追従できなくなるので、トークン数のメトリクスをそのまま送り、単価表はダッシュボードの側に置いて、そちらで計算するのが良いでしょう。

この計算で出せる金額の細かさは、どのトークン数のメトリクスがあるかで変わります。2026年10月13日の時点で、botocoreの計装とgenai-bedrockの1.2b0が出すのは `gen_ai.client.token.usage` というヒストグラムで、属性の `gen_ai.token.type` が区別するのは入力（`input`）と出力（`output`）だけです。プロバイダー側のキャッシュに当たった入力トークンは `gen_ai.usage.cache_read.input_tokens` というスパンの属性にあるだけで、メトリクスへ自動で引き継がれるわけではありません。入出力の2区分へ集約したあとで、キャッシュの読み出しぶんを別の単価で計算し直すことはできないので、このメトリクスから出せるのは通常の入出力単価による概算です。

規約の側では、2026年9月22日の変更で `gen_ai.client.token.usage` と `gen_ai.token.type` が廃止され、トークンの種類ごとのカウンターに置き換わりました[^token-metrics]。入力と出力の `gen_ai.client.inference.usage.input_tokens` と `gen_ai.client.inference.usage.output_tokens` に加えて、キャッシュの読み出し（`cache_read.input_tokens`）、キャッシュの書き込み（`cache_write.input_tokens`）、推論に使った出力（`reasoning.output_tokens`）のカウンターがあり、規約の中では、費用の近似にも使える計器という位置づけです。計装がこれらのカウンターを出すようになれば、キャッシュの読み出しぶんを別の単価で計算できます。それまでの間にキャッシュの効果を金額として見たいなら、料金区分ごとの独自メトリクスを足すか、利用明細と照合する手順を別に用意します。

[^token-metrics]: semantic-conventions-genaiのコミット `8ffdf56`（[#374](https://github.com/open-telemetry/semantic-conventions-genai/pull/374)）です。続く `4f85037`（[#521](https://github.com/open-telemetry/semantic-conventions-genai/pull/521)）では、推論の所要時間のメトリクスも `gen_ai.client.operation.duration` から `gen_ai.client.inference.duration` に変わりました。

## 構成の全体像

Bedrockのモデル呼び出しとSageMakerのエンドポイントを使うアプリケーションを、EKSまたはECS上に置く場合の構成を整理します。AgentCoreのランタイム内で動くエージェントはこの経路に乗らないので、そちらはADOT SDKから直接送る別系統になります。

アプリケーションはOTLPでノード上のCollectorへ送り、Collectorがゲートウェイへ集約して、そこから送信先へ分岐させます。ゲートウェイ側で本文のリダクションと属性の長さの調整をかけ、CloudWatchとGrafanaスタックの両方へ送る形です。

```yaml
extensions:
  sigv4auth:
    region: us-east-1
    service: xray

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  # スパンに本文が載っていた場合の関門。列挙したキーだけが対象になる。
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
  # 巨大な文字列属性を抑える補助策。スパン全体のサイズは保証しない。
  transform:
    error_mode: ignore
    trace_statements:
      - truncate_all(span.attributes, 4096)
  batch:
    send_batch_size: 512

exporters:
  otlphttp/xray:
    endpoint: https://xray.us-east-1.amazonaws.com
    auth:
      authenticator: sigv4auth
  otlphttp/grafana:
    endpoint: ${env:GRAFANA_OTLP_ENDPOINT}
    headers:
      Authorization: ${env:GRAFANA_OTLP_AUTH}

service:
  extensions: [sigv4auth]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [redaction, transform, batch]
      exporters: [otlphttp/xray, otlphttp/grafana]
```

Transformプロセッサーの設定には2つの書き方があります。上で使ったのは、OTTLのステートメントを文字列としてそのまま並べる形です。`span.attributes` のように接頭辞の付いたパスを書くと、プロセッサーがコンテキストを推論します。v0.162.0のREADMEはこちらを基本の設定として示していて、`truncate_all(span.attributes, 4096)` という例をそのまま載せています。

もう1つが、`context` と `statements` を入れ子にする書き方です。上の設定は次のように書いても同じ動作になります。

```yaml
  transform:
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          - truncate_all(attributes, 4096)
```

入れ子の形では、`context` で宣言したスコープが基準になるので、属性の参照は `attributes` と書きます。READMEはこちらを、グループ全体に条件を掛けたい場合やエラーモードを分けたい場合のための上級の設定としています。ステートメントを1つ足すだけなら前者で足ります。

`truncate_all` について、1スパン200KBの上限を守る手段だと考えるわけにはいきません。この関数が制限するのは対象のマップに入っている各文字列の値のバイト数で、文字列でない値は対象外です。4096バイトに切っても、文字列の属性が50個あれば合計で200KBに届く可能性がありますし、スパンのイベント、リンク、リソースとスコープの属性はこの1文では触れません。メトリクス側の1,024文字という上限も、この設定では満たせません。CloudWatchのトレースのエンドポイントは200KBを超えるスパンを切り詰めるのではなく拒否するので、上限に収まっているかどうかは、シリアライズしたあとのサイズで確かめる必要があります。

`batch` の `send_batch_size` も上限ではありません。この値はバッチを送る契機で、READMEは「この数に達した時点でタイムアウトを待たずに送る」設定だとしています。個数の上限を決めたいなら `send_batch_max_size` を使いますが、これはスパンの個数の上限であり、1リクエスト5MBという非圧縮サイズの上限を保証するものではありません。エンドポイントが拒否したときに気付けるよう、Collectorが出す送信失敗の内部メトリクスを監視の対象に入れておきます。

Redactionプロセッサーの側にも限界があります。止まるのは列挙したキーだけで、規約に Opt-In の属性が追加されれば、その分を足すまで通ります。対象になるのはスパンとログレコードとメトリクスのデータポイントの属性で、スパンのイベントは対象外です。ADOTの設定で本文をログ側へ移している場合、そちらの本文はこのプロセッサーではマスクされません。何も通さないことを保証したいなら、`allow_all_keys` を `false` にして `allowed_keys` に通す属性を列挙する許可リスト方式にしますが、`gen_ai.*` 以外も含めて一覧を保守し続けることになります。

同じトレースでも送り先によって形が変わることがあります。Bedrockを呼んだクライアントスパンがルートになっているトレースを送ったところ、CloudWatch側では、その親として `InternalOperation` というSERVERのスパン（`aws.local.service` などの属性を持つ）が足されていました。Grafana側には、送ったとおりクライアントスパンが1つだけあり、それがルートです。両方へ送る構成では、トレースあたりのスパン数やルートスパンの名前で集計すると、送り先ごとに値が食い違います。

![CloudWatchのTransaction Searchで、2件のトレースそれぞれにchatのスパンとInternalOperationのスパンが並んでいる](/images/20261014-cloudwatch-transaction-search-spans.png)
*CloudWatchのTransaction Search。送った `chat` のスパンごとに、CloudWatchが足した `InternalOperation` が並ぶ*

![Grafanaで同じトレースを開いた画面。スパンは1つで、chatのスパンがルートになっている](/images/20261014-grafana-same-trace-one-span.png)
*同じトレースをGrafanaで開いたところ。スパンは送った1つだけ*

この構成で自動的に埋まらないものは、次の4つです。

- SageMakerのエンドポイントのモデル識別子とトークン数
- アプリケーション側のループで書いたツール実行のスパン
- 業務上の会話単位の識別子
- 費用

前の3つはコードを書けば埋まりますが、費用はテレメトリーの外に単価表を持つ設計になります。

## おわりに

自動計装が行われる範囲はBedrockのRuntime APIまでで、SageMakerのエンドポイントとアプリケーション側のエージェントループは手で書く領域だということを確認しました。とくにSageMakerは、APIが列挙していないPOSTヘッダーを取り除くと明記していて、実際に `traceparent` のヘッダーはコンテナに届きませんでした。ヘッダーで流す前提の構成は、そのままでは通りません。

GenAIの計装ライブラリーは `opentelemetry-python-genai` へ集約されつつあり、Bedrock向けのgenai-bedrockも2026年9月にPyPIで公開されました。スパンの属性はgenai-bedrockのほうが新しい規約に沿っていますが、メトリクスの名前は2つのライブラリーのどちらも、9月に置き換わる前の規約のままです。現時点では、どちらを選んでも、規約の変更に合わせてダッシュボードのクエリを書き換える前提で組んでおく、という認識で良さそうです。

## 出典

- [Semantic conventions for AWS Bedrock operations](https://github.com/open-telemetry/semantic-conventions-genai/blob/cc07f722069974139dab497d80d145144b19daca/docs/gen-ai/aws-bedrock.md)
- [OpenTelemetry Botocore Tracing](https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation/opentelemetry-instrumentation-botocore)
- [InvokeEndpoint - Amazon SageMaker AI API Reference](https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_runtime_InvokeEndpoint.html)
- [Add observability to your Amazon Bedrock AgentCore resources](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- [OTLP Endpoints - Amazon CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPEndpoint.html)
- [Getting started - Amazon CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPGettingStarted.html)
- [Transaction Search - Amazon CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search.html)
