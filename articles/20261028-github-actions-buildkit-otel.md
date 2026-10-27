---
title: "GitHub ActionsとDockerのビルドを1本のトレースにしてGrafana Cloudで見る"
emoji: "🐳"
type: "tech"
topics: ["githubactions", "Docker", "OpenTelemetry", "grafana", "BuildKit"]
published: false
---

:::message
2026年10月27日に、GitHub-hosted runnerのUbuntu 24.04で確認した内容です。Docker Engine 28.0.4、Buildx v0.29.1、BuildKit v0.33.1、OpenTelemetry Collector contrib v0.164.0を使いました。送信するシグナルはトレースだけです。

GitHub receiverのトレース機能は、このバージョンではalphaです。後述する親スパンのID計算もreceiverの実装に依存します。

掲載コードには、実証後の送信エラー検知とattempt固定の訂正を反映しています。Cloudの108スパンは元のrunで確認し、訂正後のコードはローカルで検査しています。
:::

## はじめに

先日書いた[Dockerのビルドを遅くしたコミットをGrafana Tempoのトレースで見つける](https://zenn.dev/ymotongpoo/articles/20261027-buildkit-traces-tempo)では、手元のビルドをトレースにして、遅くなったコミットやDockerfileの手順を調べました。次に試したかったのはCIです。GitHub Actionsの画面で「Dockerのビルドが遅い」とわかっても、そのステップの中で何に時間がかかったかを調べるには、ビルドのログや記録を別に開く必要があります。ワークフロー全体からDockerfileの手順まで、同じトレースの中でたどれるようにしてみました。

## TL;DR

[BuildKit](https://docs.docker.com/build/buildkit/)から[Grafana CloudのOTLPエンドポイント](https://grafana.com/docs/grafana-cloud/send-data/otlp/send-data-otlp/)へトレースを送信できました。CIのステップへの接続に使ったのは、OpenTelemetry CollectorのGitHub receiverが生成するIDと、Buildxへ渡す`TRACEPARENT`です。ワークフローと2つのジョブが1本のトレースにまとまり、`build`ジョブのビルドステップの下にBuildKitのスパンがつながりました。CI側には、完了した実行の情報をAPIで取得してreceiverへ渡す補助処理を追加しています。

## 2つの送信経路

今回の構成では、ビルドのトレースとGitHub Actionsのトレースを別々に送ります。両方でトレースIDと親スパンIDを合わせると、Grafana Cloudで1本に表示できます。**スパン**は、個々の処理の開始時刻と終了時刻などを記録する単位です。**トレースID**は処理のまとまりを識別するID、**スパンID**はその中の個々の処理を識別するIDです。各スパンが親のスパンIDを持つことで、処理の親子関係を表します。

ビルド側の送信元は、OpenTelemetryの機能を持つBuildKitです。Dockerfileの各手順に加えて、クライアントであるBuildxのスパンも[BuildKitへ転送して送信する実装](https://github.com/docker/buildx/blob/v0.29.1/util/tracing/trace.go#L15-L24)になっています。CI側で使うのは、[OpenTelemetry Collector contribのGitHub receiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.164.0/receiver/githubreceiver/README.md)です。このreceiverは、GitHubの`workflow_run`と`workflow_job`のイベントを受け取り、ワークフローやジョブ、その中のステップをスパンへ変換します。

![左列は親IDを計算してBuildxへ渡し、BuildKit経由で送信する。右列は完了したCI情報を補助スクリプトでイベントへ変換してreceiverへ渡す。両方がGrafana Cloudの同じOTLPエンドポイントへ届く構成図](/images/20261028-github-actions-buildkit-otel-flow.png)
*図1: 矢印はデータの移動を表します。左側では計算したTRACEPARENTをBuildxへ渡します。右側は完了後の別ワークフローで、補助スクリプトがGitHub APIの情報をイベント形式へ変換します。*

receiverにはWebhookの受信口がありますが、今回そのサーバーをインターネットには公開していません。ワークフローの完了をきっかけに別のワークフローを起動し、そのrunnerの中だけでCollectorを動かします。GitHub APIで取得した完了情報をイベント形式に組み直し、ローカルの受信口へ渡す構成です。

実証時の[ファイル一式](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/tree/8937d28af8ddcdb5fddace81c0a4815e5a31f51a)とコードの固定リンクは、訂正前の実装を指します。題材はBusyBox 1.37.0の小さなイメージです。ファイルをコピーして`RUN`で別ファイルへ書き出し、イメージの実行結果も確認しました。

## BuildKitからCloudへ

まず、Actionsの親スパンを付けず、BuildKitからの送信だけを確認しました。Grafana Cloudで取得した接続情報を、リポジトリのActions secretsに次の名前で登録します。

| Secret | 設定する値 |
| --- | --- |
| `GRAFANA_CLOUD_OTLP_ENDPOINT` | `/otlp`までを含むOTLPのベースURL |
| `GRAFANA_CLOUD_OTLP_HEADERS` | Cloudの接続画面から取得した`Authorization=...`の認証ヘッダー |

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

`docker-container`ドライバーでは、BuildKitは専用のコンテナで動きます。[BuildKitのOTLP設定](https://github.com/moby/buildkit/blob/v0.33.1/README.md#opentelemetry-support)を、そのコンテナ内のBuildKitへ`--driver-opt env.…`で渡します。[HTTP/Protobufを選ぶ実装](https://github.com/moby/buildkit/blob/v0.33.1/util/tracing/detect/otlp.go#L26-L53)による通信で、データ形式はProtobufです。トレース専用のエンドポイントには、ベースURLの末尾に`/v1/traces`を追加して指定します。Cloudの公開エンドポイントへの送信なので、ローカル環境向けの`network=host`は不要です。

このbuilderを選んで`docker buildx build --builder ci-otel --load …`を実行すると、BuildxとBuildKitの両方のスパンがCloudへ届きました。[ベースラインの実行](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40436429094)から取得したのは、`build .`をルートにした87スパンのトレースです。イメージのビルドと実行テストも成功しました。

## Actionsのステップを親にする

ここまでのトレースのルートは、`build .`です。GitHub Actionsのビルドステップを親にするため、Buildxを起動するシェルに`TRACEPARENT`を設定します。Buildxに組み込まれた[環境変数からのコンテキストの読み込み処理](https://github.com/docker/buildx/blob/v0.29.1/vendor/github.com/moby/buildkit/util/tracing/env/traceenv.go#L20-L28)が、この値を取り込みます。設定するのは、接続先のトレースIDと、親になるステップのスパンIDです。

ここで、親スパンはまだ送られていません。今回使うGitHub receiverは、実行IDやジョブのIDから毎回同じトレースIDとスパンIDを生成するため、ビルド前にもその規則で親になるステップのIDを計算できます。

v0.164.0の[ID生成の実装](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.164.0/receiver/githubreceiver/trace_event_handling.go)では、デフォルトで有効な`receiver.githubreceiver.UseCheckRunID`により、ステップのIDにジョブのIDとステップ名を使います。今回の`Build Docker image`ステップに対応する計算は、次の2つです。SHA-256の結果を16進文字列にしたうえで、それぞれ必要な部分を取り出します。

| ID | ハッシュに渡す文字列 | 取り出す範囲 |
| --- | --- | --- |
| トレースID | `{run_id}{run_attempt}t` | 先頭32文字 |
| 親になるステップのスパンID | `{job_id}-Build Docker image-s` | 17文字目から32文字目 |

これを実装した[`scripts/ci-parent.py`](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/scripts/ci-parent.py)は、次の内容です。

```python
#!/usr/bin/env python3
"""Match githubreceiver v0.164.0's deterministic trace and step span IDs."""
import hashlib
import json
import os
import subprocess

run = os.environ["GITHUB_RUN_ID"]
attempt = os.environ["GITHUB_RUN_ATTEMPT"]
repository = os.environ["GITHUB_REPOSITORY"]
jobs = json.loads(subprocess.check_output([
    "gh", "api", f"repos/{repository}/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100"
]))["jobs"]
matches = [job for job in jobs if job["name"] == os.environ["GITHUB_JOB"]]
assert len(matches) == 1, "Expected one job matching GITHUB_JOB; matrix jobs need explicit resolution"
job_id = matches[0]["id"]
trace_id = hashlib.sha256(f"{run}{attempt}t".encode()).hexdigest()[:32]
step_id = hashlib.sha256(f"{job_id}-Build Docker image-s".encode()).hexdigest()[16:32]
traceparent = f"00-{trace_id}-{step_id}-01"
with open(os.environ["GITHUB_OUTPUT"], "a") as output:
    output.write(f"traceparent={traceparent}\n")
print(f"TRACEPARENT={traceparent}")
```

`TRACEPARENT`は[W3C Trace Context](https://www.w3.org/TR/2021/REC-trace-context-1-20211123/#traceparent-header)の形式で、`00-トレースID-親スパンID-01`と並べます。先頭はバージョン、末尾の`01`はサンプリングの対象であることを示すフラグです。

`GITHUB_JOB`はワークフロー内のジョブを識別する文字列です。スクリプトではGitHub APIから今回の実行に属するジョブを取得し、その数値IDを調べています。この実証ではジョブの表示名を指定せず、`build`という名前で一致させています。探索は最初の100ジョブに限られ、ジョブ名を変えたりmatrixを使ったりする場合にも別の特定方法が必要です。

receiverのREADMEには、`${{ job.check_run_id }}`を使ってAPIを呼ばずに同じIDを計算する例もあります。こちらなら名前による探索を省けますが、今回runnerで動作を確認したのは上記のAPIを使う実装です。

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

ステップ名の`Build Docker image`は、Pythonの計算に入れた名前と同じです。同じジョブ内で同名のステップを作ると、このreceiverのID規則ではスパンIDが衝突するため、名前も一意にしています。`OTEL_RESOURCE_ATTRIBUTES`には、検索用の実行IDやコミットを付けています。この設定の対象はBuildx側のスパンだけです。

## 完了したCI情報の送信

ビルドステップが終わっても、ワークフロー全体はまだ実行中です。CI側のスパンは、[送信用のワークフロー](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/.github/workflows/export-workflow.yml)が`workflow_run`の`completed`を受けてから作ります。

送信処理は、元のrunとそのattemptに属する全ジョブを取得します。再実行の回数を区別するattemptには、完了通知の値を使う必要があります。取得時点の最新attemptを読むと、通知と別の実行を参照するおそれがあるためです。ワークフローから次の2つを渡します。

```yaml
          OBSERVED_RUN_ID: ${{ github.event.workflow_run.id }}
          OBSERVED_RUN_ATTEMPT: ${{ github.event.workflow_run.run_attempt }}
```

補助コードは`GET /repos/{owner}/{repo}/actions/runs/{run_id}/attempts/{attempt}`で[通知されたattemptのrun](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run-attempt)を取得し、そのattemptのjobsを全ページ取得します。返ってきたrunとjobのID、attempt、完了状態も検査します。別attemptの応答が返る場合は、送信を始める前に停止する処理です。

APIのレコードを`action`、`repository`、`workflow_run`または`workflow_job`の外枠に入れ、`X-GitHub-Event`で種類を指定して、一時的なCollectorの`http://127.0.0.1:19418/events`へPOSTします。[検証時の補助コード](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/scripts/export-workflow.py)では、この変換を確認できます。

次は、[検証時のCollector設定](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/collector.yaml)にJSONログの指定を加えた設定です。

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

Collectorコンテナ内では`0.0.0.0:19418`で待ち受けますが、ホストへの公開は`127.0.0.1:19418:19418`に限定しています。v0.164.0は、トレースだけを使う場合でも[`scrapers`を1つ以上要求する設定検証](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.164.0/receiver/githubreceiver/config.go#L70-L78)になっています。起動するのはtracesのパイプラインだけなので、`github_org`の値を使ったメトリクスの収集は対象外です。

exporterの`endpoint`はベースURLのままです。`otlp_http`が`/v1/traces`を付けるため、BuildKitのトレース専用URLとは指定方法が異なります。認証ヘッダーはBuildKitと同じsecretから取り出して渡します。

このCollectorは送信ごとに起動して停止する実証用の設定です。送信キューと再試行も無効にしており、配送を継続する常設構成にはしていません。

batch processorがあるため、受信口のHTTP 200はCloudへの送信成功を保証しません。補助コードが検査するのは、JSONに揃えた停止後のログの`level`です。閉じたローカルポートへの送信で、エラーログを検出して失敗扱いになることも確認しました。

自分の環境で試す場合は、実証用のファイル一式に上記の訂正を反映し、2つのsecretを登録します。ビルド用と送信用の両ワークフローをデフォルトブランチに置く必要があります。そこから`BuildKit linked trace`を手動実行し、ビルドと`Export completed workflow trace`の両方の完了を待つ手順です。到着の確認は、続けてトレースを取得し、CI側のスパンもあることを確かめます。APIの権限は通常の`GITHUB_TOKEN`の`contents: read`と`actions: read`を使い、GitHub AppやPATは追加しませんでした。

## 1本につながった結果

[ビルド側の実行](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40437818776)と[CI情報の送信](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/actions/runs/40437872708)は、どちらも成功しました。Grafana Cloudから取得したトレースのIDは`d186f60d435cbf0d2af27d385e372d12`です。サービスごとの内訳は次のとおりでした。

| `service.name` | スパン数 | 記録している処理 |
| --- | ---: | --- |
| `github-actions` | 21 | ワークフロー、ジョブ、待ち時間、ステップ |
| `buildx` | 33 | ビルドクライアントの処理 |
| `buildkitd` | 54 | ビルドデーモンとDockerfileの手順 |
| 合計 | 108 | 同一トレースIDのスパン |

ビルド用の`build`と、その完了後に別のrunnerで実行する`verify-source`の2ジョブが同じルートに接続しています。CIの待ち時間やビルド内部の細部を省くと、親子関係は次のようになります。

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

同じ画面に並ぶことだけでなく、実際のIDも確認しました。`build .`の親IDは、先に計算した`Build Docker image`のスパンIDに一致しています。

| スパン | スパンID | 親スパンID |
| --- | --- | --- |
| `BuildKit linked trace` | `e7c711bbe520e84f` | なし |
| `build` | `4b166f01927696a4` | `e7c711bbe520e84f` |
| `Build Docker image` | `108544af50978be0` | `4b166f01927696a4` |
| `build .` | `5da8c9af160b108b` | `108544af50978be0` |

取得したJSONを[検証時のスクリプト](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/scripts/verify-trace.py)に渡し、出力の総数と一意なIDの件数がともに108で、ルートが1つ、親の欠落が0であることを確認しました。Dockerfileの`RUN`から親をたどった結果も、BuildKit、Buildx、ビルドステップ、ジョブ、ワークフローの順です。結果は[公開した検証記録](https://github.com/ymotongpoo/buildkit-github-actions-otel-spike-20261027/blob/8937d28af8ddcdb5fddace81c0a4815e5a31f51a/evidence/linked-verification.json)でも確認できます。

訂正後の検証スクリプトは、IDの重複と、全スパンが循環せず唯一のルートへ到達することも検査します。重複や独立した循環を加えた反例が失敗し、元の108スパンは通りました。この検査の対象は取得したデータの整合性で、配送の完全性には別の確認が必要です。

GrafanaのExploreでは、Tempoのデータソースを選び、実行した時間帯に絞って次の[TraceQL](https://grafana.com/docs/tempo/latest/traceql/)で検索します。`ci.run.id`は、今回Buildxへ付けた属性です。

```traceql
{ resource.ci.run.id = "40437818776" && name = "build ." }
```

今回は`build .`にActionsの親を付けたので、ルートだけを選ぶクエリでは、このビルドを選べません。単体とCIのビルドを選ぶ共通の条件は、`{ resource.service.name = "buildx" && name = "build ." }`です。この条件で両方のトレースがCloudの検索に含まれることを確認しました。

初回のTempoの検索応答では、ルートのサービス名が`<root span not yet received>`でした。後のトレースIDでの取得ではCI側も含む108スパンを確認しました。CI側はワークフロー完了後に生成され、検索への反映には時間差があります。ビルド実行中の検索可能性は未確認です。

## 赤い401スパンの読み方

トレースを開くと、BusyBoxの取得で`HTTP HEAD`が赤くなっていました。送信先は`registry-1.docker.io`で、HTTPステータスは401です。ただし、この実行ではその後にトークン取得と再試行が続いています。

| 順序 | リクエスト | HTTPステータス |
| --- | --- | --- |
| 1 | Docker HubへBusyBoxのマニフェストを`HEAD`で要求 | 401 |
| 2 | Buildxが`auth.docker.io/token`へ`POST`してトークンを取得 | 200 |
| 3 | 同じマニフェストを再度`HEAD`で要求 | 200 |

これは、[Docker Registryのトークン認証](https://docs.docker.com/reference/api/registry/auth/)の手順と一致します。[OpenTelemetryのHTTPスパンの規約](https://opentelemetry.io/docs/specs/semconv/http/http-spans/)では、クライアント側の4xxは原則としてErrorにするため、後続の再試行が成功しても最初の401は赤いまま残ります。`remotes.docker.resolver.HTTPRequest`と、その子の`HTTP HEAD`も同じリクエストを異なる層で記録したスパンです。

今回の401は、後続の200と、イメージの実行テストの成功まで確認できたケースです。401の後でトークン取得や再試行にも失敗している場合は、認証エラーとして調べる対象になります。

## 今回確認した範囲

BuildKitからのCloud送信と、2ジョブのワークフローにビルド内部を接続するところまで確認できました。ただし、ID生成の規則はOpenTelemetry共通の仕様ではなく、GitHub receiver v0.164.0の実装です。Collectorのバージョンやfeature gateを変えるときには、親IDの計算と取得したトレースを照合する必要があります。

CI側の開始時刻や終了時刻はGitHub APIの記録です。この実行では秒単位であり、BuildKit側の細かな時刻と同じ精度にはなりません。`build .`の終了が親の`Build Docker image`の終了を超えた差は、約0.84秒でした。親子の接続はIDで確認できますが、時間的に完全に内包されるとは限りません。

今回は信頼できるリポジトリでの手動実行で、matrix、reusable workflow、forkからのPR、実際の再実行、実行間でのキャッシュ再利用は未検証です。attempt固定の訂正は、API応答を差し替えたローカル検査で確認しました。送信用ワークフローの実行対象は、元のrunのコミットにあるスクリプトです。外部のPRが起点になる構成へ広げる場合は、[GitHubが説明する`workflow_run`の権限と注意点](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)を踏まえる必要があります。

## おわりに

GitHub Actionsのワークフローとステップから、Dockerfileのどの手順やレジストリへの通信に時間を使ったかまで、1本のトレースでたどれるようになりました。自分のCIへ取り込むときには、まずBuildKitの送信だけを確認し、必要に応じてCIの親スパンを追加する順で試せます。
