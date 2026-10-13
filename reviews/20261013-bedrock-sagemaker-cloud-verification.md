# 2026-10-13 Bedrock / SageMaker記事のクラウド検証結果

対象記事: [`articles/20261014-bedrock-sagemaker-otel.md`](../articles/20261014-bedrock-sagemaker-otel.md)

`reviews/20260922-cloud-verification-plan.md` のWケースとW-S番号を引き継ぎます。9月22日の時点でWケースは未実施でした。今回は共有のAWSサンドボックスとGrafana Cloudのスタックで実施し、記事本文は変更していません。非公開の記録は `~/audit-work/1014-bedrock-sm/` と `~/audit-work/1014-sm-xray/` にあります（台帳 `resources.json`、コマンドの記録 `commands.jsonl`、結果 `cases/`）。作成したAWSのリソースはすべて削除し、読み取り専用の検索で残りがないことを確かめました。

## 結果

| Case | 判定 | 原稿の節・行 | 実測・確認結果 | 環境 |
| --- | --- | --- | --- | --- |
| W-02 | PASS | 3つの呼び出しを区別する（26, 40–46行） | `opentelemetry-instrumentation-botocore` 0.65b0（SDK 1.44.0）でConverse、ConverseStream、InvokeModel、InvokeModelWithResponseStreamを実際に呼び、4つともスパンに `gen_ai.system=aws.bedrock` が付き、`gen_ai.provider.name` は出なかった。`gen_ai.*` の属性は46行目の一覧の範囲に収まった。メトリクスは `gen_ai.client.operation.duration` と `gen_ai.client.token.usage`、イベントは `gen_ai.user.message` と `gen_ai.choice`。9月22日以降に出た0.66b1（SDK 1.45.1）でも同じ結果 | us-east-1、`amazon.nova-micro-v1:0`、boto3 1.43.112 |
| W-03 | PASS（ローカル） | SageMakerのエンドポイントでのトレースの切れ目（81–146行） | 原稿の呼び出し側とコンテナ側のコードを、SageMakerの代わりのローカルのHTTPサーバーに向けて実行。boto3は `CustomAttributes` を `X-Amzn-SageMaker-Custom-Attributes` ヘッダーで送り、コンテナ側で同じtrace IDに戻って呼び出し側のスパンが親になった。空や不正な値では親のない新しいトレースになった（146行目）。`traceparent` は55文字（81行目）。既定のプロパゲーターでは `baggage` も同じ辞書に入った（81行目）。JSONに符号化すると印字可能なASCIIで105文字（148行目） | ローカル |
| W-04 | PASS | 同上（73–79行、152行） | リアルタイムのエンドポイント（ml.t2.medium×1）を実際に呼んだ。`traceparent` をHTTPヘッダーだけで送るとコンテナに届かず、コンテナ側のスパンは別のトレースの根になった。`CustomAttributes` で送ると、同じtrace IDで呼び出し側のスパンが親になった（両方送っても同じ）。コンテナが受け取ったヘッダーは `Accept`、`Content-Length`、`Content-Type`、`Host`、`User-Agent`、`X-Amzn-SageMaker-Custom-Attributes`、`X-Amzn-SageMaker-Inference-Id` の7つ。`InvokedProductionVariant` は `AllTraffic` を返した | us-east-2 |
| W-06 | PASS | 構成の全体像（247–297行） | 原稿のCollectorの設定（otelcol-contrib 0.161.0）で、X-RayのOTLPエンドポイント（SigV4）とGrafana Cloudの両方にBedrockのスパンが届いた。原稿との差はリージョン（us-east-2）と受信アドレス（127.0.0.1）だけ。送信失敗は0件 | us-east-2 |
| W-09 | BLOCKED | AgentCoreを使うときのCollectorの位置（154–206行） | AgentCoreのランタイムとGenAI Observabilityの画面は今回の範囲外 | — |

W-01、W-05、W-07（ローカル）とW-08（一次資料）は今回実施していません。

## 原稿に関係する発見

1. **77行目の推論は実測で裏付けられた。** 「コンテナの中で作ったスパンは、呼び出し側のトレースの子にならず、別のトレースとして記録されると考えられます（ヘッダーが届かないことからの推論です）」の部分です。W-04で、HTTPヘッダーの `traceparent` がコンテナに届かず、コンテナ側のスパンが別のトレースの根になることを確かめました。範囲（2026年10月13日、us-east-2、リアルタイムのエンドポイント）を添えれば「確認した」と書けます。
2. **X-RayのOTLPエンドポイントにはTransaction Searchの有効化が前提になる。** 221行目以降はエンドポイントと上限を説明していますが、この前提に触れていません。公式文書（[Getting started](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPGettingStarted.html)）には「Make sure Transaction Search is enabled before you use the OTLP Endpoint for traces.」とあります。Transaction Searchはアカウントとリージョン単位の設定で、有効にするとX-Rayが受け取るスパンはすべて `aws/spans` に取り込まれ、トレースサマリーになるのはインデックスする割合（既定は1%）のぶんだけになります。
3. **同じトレースがCloudWatchとGrafanaで違う形になる。** 根として送ったクライアントスパンに対して、CloudWatch側（`aws/spans`）では親のSERVERスパン `InternalOperation`（`aws.local.service` などの属性）が足されていました。同じCollectorからGrafanaに送ったほうは、送ったとおりクライアントスパンが根でした。両方へ送る構成（243行目）を採る場合、スパン数や根のスパンの数え方が送り先で食い違います。
4. **少数のトレースはX-Rayのトレース詳細に出ない。** インデックスが1%のため、検証用の2件はX-Rayの `BatchGetTraces` でもコンソールのトレース詳細でも見えませんでした。CloudWatchのTransaction Searchの画面（`aws/spans` を直接検索する）には出ます。取り込みから検索できるまでに約10分かかりました。
5. **0.66b1でも `gen_ai.system` のまま。** TL;DRの「現行の0.65b0」は9月22日時点の記述として正しいままです。公開日の時点では0.66b1が最新なので、版を更新するなら「0.66b1でも同じ」と書けます。
6. **SSOのプロファイルで手元から動かすと、認証情報の取得もトレースに入る。** `BotocoreInstrumentor` は `SSO OIDC.CreateToken` と `SSO.GetRoleCredentials` もスパンにし、最初の呼び出しのトレースに子として入れました。記事の範囲外ですが、手元で試す読者が見かける可能性があります。
7. **us-east-2のNova Microは推論プロファイル経由になる。** `us.amazon.nova-micro-v1:0` で呼ぶ必要がありました。記事のコード例はus-east-1でモデルIDを直接指定しており、そのままで正しく動きました（W-02）。
8. **Bedrock版の計装は9月24日にPyPIに公開されていた。** 記事は9月22日の時点で「PyPIに公開されておらず `pip install` はできない」と書いていましたが、`opentelemetry-instrumentation-genai-bedrock` は2026年9月24日に1.2b0として公開されています。配布物のソースでは `gen_ai.provider.name` の列挙値 `aws.bedrock` を使っています。実際の呼び出しは未実施で、記事にもそう書きました（DOCUMENTED）。

## 画像

検査（識別子のOCRを含む）を通したものを `images/` に置きました。本文にはまだ入れていません。

| Shot ID | 対応Case | ファイル | 読者が画像から読み取ること |
| --- | --- | --- | --- |
| W-S1′ | W-02 | `images/20261014-bedrock-botocore-span.png` | Grafanaのトレース詳細で、ライブラリーの版0.65b0のConverseのスパンに `gen_ai.system=aws.bedrock` が付き、`gen_ai.provider.name` はない |
| W-S1 | W-06 | `images/20261014-cloudwatch-transaction-search-spans.png` | CollectorからSigV4で送ったBedrockのスパンがCloudWatchのTransaction Searchに入り、CloudWatchが `InternalOperation` のスパンを足している |
| W-S5 | W-06 | `images/20261014-grafana-same-trace-one-span.png` | W-S1と同じトレースをGrafanaで開くとスパンは1つで、送ったクライアントスパンが根のまま（CloudWatch側の `InternalOperation` はない） |
| W-S2 | W-04 | `images/20261014-sagemaker-endpoint-inservice.png`（本文に追加） | リアルタイムのエンドポイントが `InService`（ARNは塗りつぶし） |
| W-S3 | W-04 | `images/20261014-sagemaker-customattributes-log.png` | ヘッダーと `CustomAttributes` の両方で送ったとき、コンテナには `traceparent` ヘッダーが届かず（`null`）、`CustomAttributes` の値から呼び出し側のスパンを親に復元した |

画像にはサービス名やエンドポイント名として検証用の名前（`ymo-1014-...`）が写っています。

## 費用と後片付け

- 費用の見込みは合計$0.10未満です。主なものは、SageMakerのエンドポイント約9分（ml.t2.medium、$0.056/時間）と、Bedrockの呼び出し18回です
- AWSに作ったもの（ECRリポジトリ、IAMロール、SageMakerのモデル・エンドポイント設定・エンドポイント、ロググループ、SageMakerが自動で作った系統追跡の項目）は削除済みです
- 削除できないものは2つあります
  - `aws/spans` に入ったスパン4件。保持期間の30日で消えます
  - Grafana Cloudに送ったテレメトリー。スタックの保持期間で消えます
- アカウント全体の設定は変更していません。us-east-1のTransaction Searchは、他チームが常時X-Rayを使っているため変えず、すでに有効なus-east-2を使いました
