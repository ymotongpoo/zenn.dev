---
title: "GitHub ActionsとDockerのビルドを1本のトレースにしてGrafana Cloudで見る"
emoji: "🐳"
type: "tech"
topics: ["githubactions", "Docker", "OpenTelemetry", "grafana", "BuildKit"]
published: true
published_at: 2026-10-28 09:30
---

:::message
2026年10月27日に、GitHubホストランナーのUbuntu 24.04で確認した内容です。Docker Engine 28.0.4、Buildx v0.29.1、BuildKit v0.33.1、OpenTelemetry Collector contrib v0.164.0を使いました。送信するシグナルはトレースだけです。

GitHubレシーバーのトレース機能は、このバージョンではalphaです。後述する親スパンのID計算もレシーバーの実装に依存します。
:::

## はじめに

先日書いた[Dockerのビルドを遅くしたコミットをGrafana Tempoのトレースで見つける](https://zenn.dev/ymotongpoo/articles/20261027-buildkit-traces-tempo)では、手元のビルドをトレースにして、遅くなったコミットやDockerfileの手順を調べました。次のステップはCIです。GitHub Actionsの画面で「Dockerのビルドが遅い」とわかっても、そのステップの中で何に時間がかかったかを調べるには、ビルドのログや記録を別に開く必要があります。ワークフロー全体からDockerfileの手順まで、同じトレースの中でたどれるようにしてみました。

## TL;DR

[BuildKit](https://docs.docker.com/build/buildkit/)から[Grafana CloudのOTLPエンドポイント](https://grafana.com/docs/grafana-cloud/send-data/otlp/send-data-otlp/)へトレースを送信できることを確認しました。CIのステップにつなぐには、OpenTelemetry CollectorのGitHubレシーバーがステップに付けるIDをビルドの前に計算し、`TRACEPARENT`でBuildxへ渡します。CI側のスパンを送るのは、完了した実行の情報をGitHub APIで取得し、Actionsの中で一時的に動かすCollectorです。その結果、ワークフローと2つのジョブが1本のトレースにまとまり、`build`ジョブのビルドステップの下にBuildKitのスパンがつながりました。

## 2つの送信経路

今回の構成では、ビルドのトレースとGitHub Actionsのトレースを別々に送ります。両方でトレースIDと親スパンIDを合わせると、Grafana Cloudで1本に表示できます。

ビルド側の送信元は、OpenTelemetryでトレースを送る機能を持つBuildKitです。Dockerfileの各手順のスパンに加えて、クライアントであるBuildxのスパンも、[BuildKitへ転送してまとめて送ります](https://github.com/docker/buildx/blob/v0.29.1/util/tracing/trace.go#L15-L24)。

GitHub Actions側のスパンを作るのは、OpenTelemetry Collectorの[GitHubレシーバー](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.164.0/receiver/githubreceiver/README.md)です。GitHubレシーバーは、GitHubから届く`workflow_run`と`workflow_job`のWebhookのイベントを受け取り、ワークフロー、ジョブ、ステップのスパンに変換します。Collectorは、そのスパンをエクスポーターでGrafana Cloudへ送ります。

今回は、CI側のイベントの取得から送信までをActionsの中で実行する構成を選びました。ワークフローの完了後に別のワークフローを起動し、そのランナーで一時的にCollectorを動かします。補助スクリプトが完了した実行の情報をGitHub APIで取得し、Webhookと同じ形式のイベントに組み立てて、ランナー内のGitHubレシーバーへ渡す構成です。BuildKitからの送信だけを試す段階では、このCollectorは使いません。

![左列は親IDを計算してBuildxへ渡し、BuildKit経由で送信する。右列は完了したCI情報を補助スクリプトでイベントへ変換してOpenTelemetry Collectorへ渡す。両方がGrafana Cloudの同じOTLPエンドポイントへ届く構成図](/images/20261028-github-actions-buildkit-otel-flow.png)
*図1: 矢印はデータの移動を表します。左側では計算したTRACEPARENTをBuildxへ渡します。右側は完了後の別ワークフローで、補助スクリプトがGitHub APIの情報をイベント形式へ変換し、OpenTelemetry Collectorへ渡します。Collector内のGitHubレシーバーでCIスパンを生成して送信します。*

題材はBusyBox 1.37.0の小さなイメージです。ファイルをコピーして`RUN`で別ファイルへ書き出し、ビルドしたイメージを実行して出力も確かめました。実証用の[ファイル一式](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/tree/174eacdf9765bbc516b38de8a09eedc709cef8eb)を公開しています。

## BuildKitからGrafana Cloudへ

まず、Actionsの親スパンを付けず、BuildKitからの送信だけを確認しました。Grafana Cloudで取得した接続情報を、リポジトリのActionsシークレットに次の名前で登録します。

| シークレット | 設定する値 |
| --- | --- |
| `GRAFANA_CLOUD_OTLP_ENDPOINT` | `/otlp`までを含むOTLPのベースURL |
| `GRAFANA_CLOUD_OTLP_HEADERS` | Grafana Cloudの接続画面から取得した`Authorization=...`の認証ヘッダー |

Actionsのステップでは、これらを`OTEL_EXPORTER_OTLP_ENDPOINT`と`OTEL_EXPORTER_OTLP_HEADERS`という環境変数に渡しています。[`scripts/setup-builder.sh`](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/scripts/setup-builder.sh)の内容は次のとおりです。

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${OTEL_EXPORTER_OTLP_ENDPOINT:?Missing OTLP endpoint}"
: "${OTEL_EXPORTER_OTLP_HEADERS:?Missing OTLP authentication headers}"
docker buildx create --name ci-otel --driver docker-container \
  --driver-opt image=moby/buildkit:v0.33.1 \
  --driver-opt env.OTEL_TRACES_EXPORTER=otlp \
  --driver-opt env.OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf \
  --driver-opt "env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT%/}/v1/traces" \
  --driver-opt "env.OTEL_EXPORTER_OTLP_TRACES_HEADERS=${OTEL_EXPORTER_OTLP_HEADERS}" \
  --bootstrap >/dev/null
```

`docker-container`ドライバーではBuildKitが専用のコンテナで動くので、[BuildKitのOTLP設定](https://github.com/moby/buildkit/blob/v0.33.1/README.md#opentelemetry-support)は`--driver-opt env.…`でそのコンテナの環境変数として渡します。プロトコルは[`http/protobuf`](https://github.com/moby/buildkit/blob/v0.33.1/util/tracing/detect/otlp.go#L26-L53)で、OTLP/HTTPを使います。トレース専用のエンドポイントは、ベースURLの末尾に`/v1/traces`を足したURLです。

このbuilderを選んで`docker buildx build --builder ci-otel --load …`を実行すると、BuildxとBuildKitの両方のスパンがGrafana Cloudへ届きました。[ベースラインの実行](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40436429094)から取得したのは、`build .`をルートにした87スパンのトレースです。イメージのビルドと実行テストも成功しました。

![Grafana CloudのExploreで表示したベースラインのトレース。ルートはbuild .で、サービス数は2、スパン数は87、所要時間は約1.35秒](/images/20261028-github-actions-buildkit-otel-baseline.png)
*図2: Grafana Cloudで取得したベースラインのトレース。BuildxとBuildKitの87スパンを確認できます。[^registry-auth]*

## Actionsのステップを親にする

ここまでのトレースのルートは`build .`です。GitHub Actionsのビルドステップを親にするには、Buildxを実行するステップに環境変数`TRACEPARENT`を設定します。Buildxは[環境変数からトレースコンテキストを読み込む処理](https://github.com/docker/buildx/blob/v0.29.1/vendor/github.com/moby/buildkit/util/tracing/env/traceenv.go#L20-L28)でこの値を取り込み、`build .`を指定された親の子にします。`TRACEPARENT`に入れるのは、接続先のトレースIDと、親になるステップのスパンIDです。

ただし、ビルドの時点では親になるステップのスパンはまだありません。CI側のスパンは、ワークフローの完了後に作るからです。それでも親のIDを指定できるのは、GitHubレシーバーがトレースIDとスパンIDを乱数ではなく実行IDやジョブIDから決まった規則で計算するためです。ビルドの前に同じ規則で計算すれば、あとで届くステップのスパンと同じIDが得られます。

補助スクリプト[`scripts/ci-parent.py`](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/scripts/ci-parent.py)は、今回の実行ID、再実行回数、ジョブIDから、レシーバーの[ID生成の実装](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.164.0/receiver/githubreceiver/trace_event_handling.go)と同じ規則でIDを計算します。計算部分を抜粋すると次のとおりです。[^job-lookup]

```python
trace_id = hashlib.sha256(f"{run}{attempt}t".encode()).hexdigest()[:32]
step_id = hashlib.sha256(f"{job_id}-Build Docker image-s".encode()).hexdigest()[16:32]
traceparent = f"00-{trace_id}-{step_id}-01"
```

`TRACEPARENT`の値は、[W3C Trace Context](https://www.w3.org/TR/2021/REC-trace-context-1-20211123/#traceparent-header)の`traceparent`ヘッダーと同じ`00-トレースID-親スパンID-01`の形式です。スクリプトは、この値を`GITHUB_OUTPUT`へ書き出します。

ワークフローでは、このスクリプトの出力をビルドステップだけに渡します。[`build.yml`](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/.github/workflows/build.yml)から該当部分を抜粋すると、次のようになります。

```yaml
      - name: Calculate build step parent
        id: build_context
        env:
          GH_TOKEN: ${{ github.token }}
        run: python3 scripts/ci-parent.py
      - name: Build Docker image
        env:
          TRACEPARENT: ${{ steps.build_context.outputs.traceparent }}
          OTEL_RESOURCE_ATTRIBUTES: vcs.ref.head.revision=${{ github.sha }},ci.run.id=${{ github.run_id }},ci.run.attempt=${{ github.run_attempt }},ci.repository=${{ github.repository }},experiment.mode=linked
        run: docker buildx build --builder ci-otel --load --tag buildkit-otel-spike:ci .
```

ステップのスパンIDはジョブIDとステップ名から決まるので、ステップ名はスクリプトの計算に使った`Build Docker image`と一致させます。また、ステップ名はジョブ内で一意にしておきます。同じジョブに同名のステップが2つあると、レシーバーが両方に同じスパンIDを付けてしまうからです。

`OTEL_RESOURCE_ATTRIBUTES`では、検索に使う実行IDやコミットを付けています。この属性が付くのはBuildxのスパンだけで、BuildKitのスパンには付きません。

## CI側のスパンの送信

ビルドステップが終わっても、ワークフロー全体はまだ実行中です。CI側のスパンは、`workflow_run`の`completed`で起動する[送信用のワークフロー](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/174eacdf9765bbc516b38de8a09eedc709cef8eb/.github/workflows/export-workflow.yml)が作ります。

送信用のワークフローは、完了通知に含まれる実行IDと再実行回数を環境変数で補助スクリプトへ渡します。

```yaml
          OBSERVED_RUN_ID: ${{ github.event.workflow_run.id }}
          OBSERVED_RUN_ATTEMPT: ${{ github.event.workflow_run.run_attempt }}
```

再実行回数を指定するのは、取得した時点で最新の再実行ではなく、通知された回のジョブを読むためです。補助スクリプトは、その回のジョブとステップの情報をGitHub APIで取得し、Webhookと同じ形式のイベントに組み立ててランナー内のCollectorへPOSTします。変換の処理は[`scripts/export-workflow.py`](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/174eacdf9765bbc516b38de8a09eedc709cef8eb/scripts/export-workflow.py)で確認できます。

[`collector.yaml`](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/174eacdf9765bbc516b38de8a09eedc709cef8eb/collector.yaml)の内容は次のとおりです。[^scrapers]

```yaml
receivers:
  github:
    webhook:
      endpoint: 0.0.0.0:19418
      path: /events
      health_path: /health
      service_name: github-actions
    scrapers:
      scraper:
        github_org: ymotongpoo
processors:
  batch:
    timeout: 1s
exporters:
  otlp_http/cloud:
    endpoint: ${env:OTEL_EXPORTER_OTLP_ENDPOINT}
    headers:
      Authorization: ${env:GRAFANA_AUTHORIZATION}
    timeout: 10s
    sending_queue:
      enabled: false
    retry_on_failure:
      enabled: false
service:
  telemetry:
    logs:
      encoding: json
  pipelines:
    traces:
      receivers: [github]
      processors: [batch]
      exporters: [otlp_http/cloud]
```

エクスポーターの`endpoint`はベースURLのままです。`otlp_http`のエクスポーターが`/v1/traces`を付けるので、BuildKitにトレース専用のURLを渡したのとは指定方法が違います。認証ヘッダーには、BuildKitと同じシークレットから`Authorization=`の後ろの値を取り出して渡します。

このCollectorは送信のたびに起動して停止する実証用の設定で、送信キューと再試行を無効にしています。[^export-check]

自分の環境で試すには、2つのシークレットを登録し、ビルド用と送信用のワークフローをデフォルトブランチに置きます。そのうえで`BuildKit linked trace`を手動で実行し、ビルドと`Export completed workflow trace`の両方の完了を待ちます。APIの呼び出しに使うのは`contents: read`と`actions: read`の権限を付けた`GITHUB_TOKEN`で、GitHub AppやPATは不要です。

## 1本につながった結果

[ビルド側の実行](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40437818776)と[CI側のスパンの送信](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40437872708)は、どちらも成功しました。ワークフロー全体とビルドの内部が1本のトレースにつながっています。

![Grafana CloudのExploreで表示した108スパンのトレース。ワークフローを親に、buildジョブの全ステップとverify-sourceジョブが表示され、Build Docker imageの子にBuildxのbuild .がつながっている](/images/20261028-github-actions-buildkit-otel-linked.png)
*図3: 同じ実行のワークフロー、2つのジョブ、各ステップが1本のトレースになりました。Build Docker imageの下にbuild .が接続しており、ビルド内部は折りたたんでいます。*

サービスごとの内訳は次のとおりでした。

| `service.name` | スパン数 | 記録している処理 |
| --- | ---: | --- |
| `github-actions` | 21 | ワークフロー、ジョブ、待ち時間、ステップ |
| `buildx` | 33 | ビルドクライアントの処理 |
| `buildkitd` | 54 | ビルドデーモンとDockerfileの手順 |
| 合計 | 108 | 同一トレースIDのスパン |

ビルド用の`build`と、その完了後に別のランナーで実行する`verify-source`の2ジョブが、同じルートにつながっています。CIの待ち時間やビルド内部の細部を省くと、親子関係は次のようになります。

```text
BuildKit linked trace
├── build
│   └── Build Docker image
│       └── build .
│           └── …
│               └── [4/4] RUN cat message.txt > result.txt
└── verify-source
    └── Verify source fixture
```

`build .`の親IDは`Build Docker image`のスパンIDと一致し、取得した108スパンはすべて同じワークフローのルートへつながっていました。[^verification]

GrafanaのExploreでTempoのデータソースを選び、実行した時間帯に絞って、次の[TraceQL](https://grafana.com/docs/tempo/latest/traceql/)で検索します。`ci.run.id`は、`OTEL_RESOURCE_ATTRIBUTES`でBuildxのスパンに付けた属性です。

```traceql
{ resource.ci.run.id = "40437818776" && name = "build ." }
```

前回の記事では、ルートのスパンだけを選ぶ条件（`span:parentID = ""`）でビルドの所要時間を集計しました。今回のビルドは`build .`にActionsの親があるので、この条件では選べません。手元のビルドとCIのビルドをまとめて選ぶ条件は、`{ resource.service.name = "buildx" && name = "build ." }`です。ベースラインとCIの両方のトレースが、この条件の検索結果に入ることを確認しました。

CI側のスパンは、送信用のワークフローが完了してから届きます。トレースを開くのは、両方のワークフローが完了してからにしてください。[^search-delay]

## 今回確認した範囲

BuildKitからGrafana Cloudへの送信と、2ジョブのワークフローへのビルド内部の接続までを確認しました。ただし、IDの生成規則はOpenTelemetryの共通の仕様ではなく、GitHubレシーバー v0.164.0の実装です。Collectorのバージョンやレシーバーのfeature gateを変えるときは、取得したトレースで`build .`が親のステップにつながっているかを確かめ直してください。

CI側の時刻はGitHub APIが秒単位で記録した値です。そのため、親子の接続が正しくても、BuildKitのスパンが親の時間範囲からわずかにはみ出すことがあります。今回の実行では、`build .`の終了が親の`Build Docker image`の終了を約0.84秒超えていました。

今回は信頼できるリポジトリでの手動実行だけで、matrix、reusable workflow、forkからのPR、実際の再実行、実行間でのキャッシュ再利用は検証していません。[^workflow-security]

## おわりに

GitHub Actionsのワークフローとステップから、Dockerfileのどの手順やレジストリへの通信に時間を使ったかまで、1本のトレースでたどれるようになりました。自分のCIへ取り込むときには、まずBuildKitの送信だけを確認し、必要に応じてCIの親スパンを追加する順で試せます。

[^registry-auth]: 図の上部に赤く表示されている`HEAD HTTP HEAD`のエラーは、[Docker Registryのトークン認証](https://docs.docker.com/reference/api/registry/auth/)で最初に返る401の認証要求です。今回の実行では、トークン取得後の再試行が200となり、ビルドも成功しています。

[^job-lookup]: ジョブの数値IDは、GitHub APIで今回の実行のジョブの一覧を取得し、名前が`GITHUB_JOB`と一致するジョブから取り出します。ジョブの表示名を変えたりmatrixを使ったりする場合は、別の方法でジョブを特定する必要があります。

[^scrapers]: v0.164.0のGitHubレシーバーは、トレースだけを使う場合でも、[`scrapers`を1つ以上設定することを求めます](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.164.0/receiver/githubreceiver/config.go#L70-L78)。パイプラインはトレースだけなので、`github_org`を使ったメトリクスの収集は動きません。

[^export-check]: Collectorはbatchプロセッサーを通して送るので、レシーバーがHTTP 200を返しても、Grafana Cloudへの送信が成功したとは限りません。そこで補助スクリプトは、停止後のCollectorがJSON形式で出力したログを読み、`level`がエラーを示していれば失敗として扱います。

[^verification]: [検証時のスクリプト](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/scripts/verify-trace.py)と[検証記録](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/evidence/linked-verification.json)を公開しています。取得した108スパンは、スパンIDがすべて一意で、ルートが1つ、親が見つからないスパンは0でした。この検査では、送信したすべてのスパンがGrafana Cloudに届いたかまでは判定できません。

[^search-delay]: Tempoの最初の検索結果では、ルートのサービス名が`<root span not yet received>`と表示されました。その後にトレースIDで取得すると、CI側を含む108スパンがそろっていました。

[^workflow-security]: 送信用のワークフローは、元の実行のコミットにある補助スクリプトを実行します。外部のPRが起点になる構成へ広げるときは、[GitHubが説明する`workflow_run`の権限と注意点](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)を確認してください。
