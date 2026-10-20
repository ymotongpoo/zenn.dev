---
title: "Dockerのビルドを遅くしたコミットをGrafana Tempoのトレースで見つける"
emoji: "🐳"
type: "tech"
topics: ["Docker", "OpenTelemetry", "grafana", "Tempo", "BuildKit"]
published: false
---

:::message
2026年10月20日に確認した内容です。動作確認には次の版を使いました。

- Docker Engine 29.0.0、buildx v0.29.1（Ubuntu 26.04.1）
- BuildKit v0.33.1（builderのイメージを`moby/buildkit:v0.33.1`に固定）
- [grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm) 0.37.0（Grafana 13.2.3、Tempo 3.1.0を含む）
- [mcp-grafana](https://github.com/grafana/mcp-grafana) 2.0.2
- [Claude Code](https://code.claude.com/docs/en/overview) 2.1.303

記事中のコマンドは、手元で使ったポート番号をotel-lgtmのデフォルトに戻して書いています。
:::

## はじめに

こんにちは、Grafana Labsでデベロッパーアドボケイトをしているものです。

2026年11月3日にシンガポールで開かれる[Grafana & Friends Singapore x Docker](https://www.meetup.com/grafana-and-friends-singapore/events/316976705/)で、[Docker](https://www.docker.com/)のビルドの話をすることになりました。Dockerとの共催なので、ビルドの各手順を[Grafana Tempo](https://grafana.com/oss/tempo/)で見るデモを考えていたところ、Docker自身もビルドのトレースを画面に出せるとわかりました。それならTempoに送る意味はどこにあるのか。この記事は、実際にビルドを溜めてそれを確かめた記録です。

## TL;DR

Dockerのビルドを実行する[BuildKit](https://docs.docker.com/build/buildkit/)は、ビルドごとにOpenTelemetryのトレースを出しています。そのトレースは`docker buildx history trace`でJaeger UIに開けるので、ビルドを1回調べるならその画面で十分です。ただし、BuildKitが残す履歴はデフォルトで48時間か50回分までです。同じトレースをGrafana Tempoに送ってコミットのIDを付けておくと、どのコミットからビルドが遅くなったのかをグラフで特定できました。コーディングエージェントにMCPサーバー経由でトレースを読ませたところ、遅くしたコミットを見つけてDockerfileを直し、直ったこともTempoで確かめました。

## BuildKitが出すトレース

`docker build`の実体は、[buildx](https://docs.docker.com/reference/cli/docker/buildx/)というCLIのプラグインと、ビルドを実行するデーモンのBuildKitです。BuildKitは[OpenTelemetry](https://opentelemetry.io/ja/)[^otel]でトレース[^trace]を出す機能を持っていて、Dockerfileの手順ひとつひとつがスパンになります。計装を足す必要はありません。

Dockerの[公式ドキュメント](https://docs.docker.com/build/debug/opentelemetry/)が示しているのは、環境変数`JAEGER_TRACE`でJaegerへ送る方法だけです。一方、[BuildKitのREADME](https://github.com/moby/buildkit/blob/v0.33.1/README.md)には、OTLP[^otlp]で送る方法が載っています。環境変数`OTEL_TRACES_EXPORTER=otlp`と`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`を使う方法で、後でTempoへ送るときにもこちらを使います。

トレースをどこにも送っていなくても、BuildKitはビルドの履歴にトレースを残しています。[`docker buildx history trace`](https://docs.docker.com/reference/cli/docker/buildx/history/trace/)は、その履歴からトレースを取り出し、一時的に立ち上げたJaeger UIで開くコマンドです[^history-trace-tty]。

```sh
docker buildx history trace --builder gf-demo --addr 127.0.0.1:16686
```

![Jaeger UIでbuildx: build .のトレースを開いた画面。全体は20.27秒で、buildkitdの[build 4/4] RUN go mod download && go buildのスパンが19.24秒を占めている](/images/20261027-jaeger-build-steps.png)
*`docker buildx history trace`で開いたJaeger UIの画面。上部はトレースの概要で、下はDockerfileの手順のスパンのあたりを切り出した*

この画面では、全体の20.27秒のうち19.24秒を`[build 4/4] RUN go mod download && go build`の手順が占めていることがわかります。ビルドが遅いと感じたときに、どの手順を疑えばよいかは、この画面だけで判断できます。

## Tempoへ送る

同じトレースをGrafana Tempoへ送るには、buildxのbuilderを作るときに環境変数を2つ渡すだけです。送り先には[grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm)を使いました。[Grafana](https://grafana.com/oss/grafana/)とTempoに加えてPrometheusとOpenTelemetry Collectorも1つにまとめたコンテナで、そのOTLPのポートへ送ります。

```sh
docker run -d --name lgtm -p 3000:3000 -p 4317:4317 -p 4318:4318 grafana/otel-lgtm:0.37.0

docker buildx create --name gf-demo --driver docker-container \
  --driver-opt image=moby/buildkit:v0.33.1 \
  --driver-opt network=host \
  --driver-opt env.OTEL_TRACES_EXPORTER=otlp \
  --driver-opt env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4317 \
  --bootstrap

docker buildx build --builder gf-demo --load .
```

`docker-container`ドライバーのbuilderでは、BuildKitはコンテナの中で動きます。`network=host`を付けたのは、そのBuildKitからホストのループバックアドレスに公開したOTLPのポートへ届かせるためです[^docker-desktop]。

トレースには、buildx（サービス名`buildx`）とBuildKit（サービス名`buildkitd`）のスパンが1本につながって入ります。ルートのスパンは`build .`です。クライアント側のbuildxには環境変数を渡していませんが、buildxのスパンもTempoに届いていました[^client-env]。

![GrafanaのExploreでTempoのトレースを開いた画面。buildx: build .の全体が20.87秒で、[build 4/4] RUN go mod download && go build -o /out/hello .のスパンが19.36秒になっている](/images/20261027-tempo-build-regressed.png)
*同じ種類のビルドのトレースをGrafanaのExploreで開いた画面。上部はトレースの概要で、下はDockerfileの手順のスパンのあたりを切り出した*

1つ気をつける点があります。buildxは、環境変数`TRACEPARENT`があると、それを親のトレースコンテキストとして扱います[^childprocess]。最初に試したときは、作業に使ったシェルにこの変数が設定されていた状態でした。そのせいで2回のビルドが1本のトレースにまとまり、ルートのスパンが届かない状態になりました。ビルドを1回ずつ別のトレースにしたいなら、`TRACEPARENT`を外してから実行してください。

## ビルドを溜めると見えるもの

ここまでなら、Dockerの画面で十分です。Tempoへ送る理由になるのは、ビルドが1回ではなく、たくさんあるときです。

[BuildKitの設定](https://github.com/moby/buildkit/blob/v0.33.1/docs/buildkitd.toml.md)では、ビルドの履歴はデフォルトで`maxAge = 172800`（48時間）、`maxEntries = 50`です。`docker buildx history trace`で開けるのは、この履歴に残っているビルドだけで、`--compare`で2回分を並べて比べる場合も同じ制約がかかります。

使い捨てのCIのrunnerでは、ジョブが終わればbuilderごと履歴も消えます。DockerはGitHub Actions向けに、[ビルドの記録をZIPのアーティファクトとして残す](https://docs.docker.com/build/ci/github-actions/build-summary/)機能を持っています。ただ、それをDocker Desktopに取り込んで見るのは、CIの実行1回分ずつです。「どのコミットからビルドが遅くなったのか」を答えるには、何十回分ものビルドを並べなければなりません。

そこで、コミットを重ねながら20回ビルドし、全部のトレースをTempoに溜めました。題材は、Prometheusのクライアントライブラリに依存する小さなGoのHTTPサーバーです。前半の10回は、依存のダウンロードとビルドのキャッシュをキャッシュマウントで再利用するDockerfileでビルドしました。

```dockerfile
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go build -o /out/hello .

FROM gcr.io/distroless/static-debian13
COPY --from=build /out/hello /hello
ENTRYPOINT ["/hello"]
```

11回目に、Dockerfileを「整理した」コミットを入れました。このコミットはキャッシュマウントを外し、`COPY . .`を依存のダウンロードより前に移すものです。この順序だと、ソースを1行変えるたびに依存のダウンロードと全パッケージのコンパイルがやり直しになります。変わったのはビルドのステージだけなので、そこだけを示します。

```dockerfile
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY . .
RUN go mod download && go build -o /out/hello .
```

前後には、Dockerfileにラベルを足すだけのコミットを1つずつ混ぜました。git logにはDockerfileを変えたコミットが3つ並ぶので、どれでビルドが遅くなったのかはトレースを見ないとわかりません。

各ビルドには、そのときのコミットのIDを付けました。buildxは[`OTEL_RESOURCE_ATTRIBUTES`](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)を読むので、ここにリソース属性`vcs.ref.head.revision`として入れて渡せば済みます。ただし、この属性が付くのは`buildx`のスパンだけで、`buildkitd`のスパンは対象外です。

```sh
OTEL_RESOURCE_ATTRIBUTES="vcs.ref.head.revision=$(git rev-parse --short HEAD)" \
  docker buildx build --builder gf-demo .
```

2〜20回目のビルド（19回分）の所要時間を、[TraceQL](https://grafana.com/docs/tempo/latest/traceql/)[^traceql]のメトリクスのクエリでグラフにしました。ルートのスパンだけを選んで、30秒ごとの最大値を取っています[^quantile]。

```traceql
{ resource.service.name = "buildx" && span:parentID = "" } | max_over_time(duration)
```

![GrafanaのExploreでTraceQLのメトリクスのクエリを実行した折れ線グラフ。05:23:00までは約2秒で推移し、05:23:30の点から約20秒に上がったまま戻らない](/images/20261027-tempo-build-duration.png)
*2〜20回目のビルドの所要時間をTraceQLのmax_over_timeでGrafanaに描いた画面。点の時刻は30秒の区間の終わりを表す*

トレースで見ると、前半のビルドは1.9〜2.5秒で終わり、11回目から20.3〜21.7秒に延びて戻りません[^cold]。跳ねた直後のトレースを開けば、`vcs.ref.head.revision`からコミットがわかります。このデモでは「整理した」コミットでした。遅くなる前後のトレースを並べると、どの手順が延びたのかもわかります。

![GrafanaのExploreで遅くなる前のビルドのトレースを開いた画面。全体は2.5秒で、go mod downloadの手順はload cacheになり、[build 6/6] RUN go buildのスパンが904.78ミリ秒になっている](/images/20261027-tempo-build-good.png)
*遅くなる前のビルドのトレースをGrafanaのExploreで開いた画面。依存のダウンロードはキャッシュから読まれ、go buildは約0.9秒で終わっている*

遅くなる前は、依存のダウンロードの手順が`load cache:`で始まるスパンになり、キャッシュから読まれています。遅くなった後は、手順が`RUN go mod download && go build`の1つにまとまり、その手順だけで19.36秒かかっています。

手順のスパン名には、`RUN`のコマンドがそのまま入ります。Dockerfileを変えるとスパン名も変わるので、変更の前後を1本の系列で比べるなら、ルートのスパンの所要時間を使ってください。

## エージェントに直させる

Tempoに溜めたトレースは、人だけでなくプログラムからも問い合わせられます。[mcp-grafana](https://github.com/grafana/mcp-grafana)は、GrafanaをMCP[^mcp]のサーバーとして公開するツールです。Tempo向けには次のようなツールを持っています。

- `search_tempo_traces`：TraceQLでトレースを検索する
- `query_tempo_metrics`：TraceQLのメトリクスを計算する
- `diff_tempo_traces`：2本のトレースを比べる

これをコーディングエージェントのClaude Codeにつなぎ、ビルドが遅くなった原因を調べさせました。

mcp-grafanaはコンテナで起動し、`--disable-write`で書き込み系のツールを外しました。手元のotel-lgtmのGrafanaは匿名でアクセスできるので、トークンは渡していません。

```json
{
  "mcpServers": {
    "grafana": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "--network", "host",
               "-e", "GRAFANA_URL=http://127.0.0.1:3000",
               "grafana/mcp-grafana:2.0.2", "-t", "stdio", "--disable-write"]
    }
  }
}
```

Claude Codeは`--permission-mode acceptEdits`で起動しました。このモードでは、作業ディレクトリの中でのファイルの編集と一般的なファイル操作のコマンドが確認なしで通ります。そのほかに許可したのは、このMCPのツールと、`git log`、`git show`、`git diff`、`docker buildx build`、`sleep`のコマンドです。頼んだ内容は次のとおりです。

```text
Our container build got slow recently. Builds are traced: every build sends
its trace to Tempo (Grafana datasource UID "tempo"). Each build has a span
named "build ." from the service "buildx", and that span's resource carries
the commit it was built from as vcs.ref.head.revision. Use the Tempo traces
to find which commit made the build slow and why, then fix the Dockerfile in
this directory. After the fix, rebuild with

    docker buildx build --builder gf-demo --output type=cacheonly .

and confirm in Tempo that the new build is fast again. New traces can take
about 30 seconds to become searchable.
```

エージェントは、まず`git log`でコミットの一覧を読み、`search_tempo_traces`でコミットごとの所要時間を並べました。そこから出した結論は、約2秒から約21秒に跳ねたのは「整理した」コミットだというものです。そのコミットの差分を`git show`で読んだうえで、キャッシュマウントと`COPY`の順序を元に戻しています。後から足されたラベルは残したままです。再ビルドしたあとは新しいトレースが検索できるようになるまで待ち、2.98秒と0.79秒で終わったことをTempoで確かめました。ここまでの所要時間は18ターン、52.6秒です[^cost]。

最初に試したときは、劣化させたコミットのメッセージを「Simplify the Dockerfile」にしていました。エージェントはトレースを見る前に`git log`を読み、そのメッセージで原因の見当をつけてしまいました。ラベルを足すだけのコミットを前後に混ぜたのは、この試行の後です。実際のリポジトリでは、遅くした変更がわかりやすいメッセージで入っているとは限りません。2回目の試行では、メッセージからは判断できないコミットの中から、エージェントがトレースを使って正しいコミットを選びました。試したのはこの1回だけです。

## エージェントの操作も同じトレースに入る

最初の試行では、エージェントが再ビルドしたトレースをTempoで見つけられませんでした。手元のClaude Codeは、[テレメトリーの設定](https://code.claude.com/docs/en/monitoring-usage)で自分のトレースを別の場所へ送っていました[^enhanced]。同じドキュメントにあるとおり、トレースを有効にしたClaude Codeは、Bashで実行するコマンドに`TRACEPARENT`を渡します[^propagate]。中身は、実行中のツールのスパンのトレースコンテキストです。そのため、ビルドのトレースはClaude Codeのトレースの子になり、親のスパンはデモのTempoに届いていなかったのです。

そこで、Claude Code自身のトレースもデモのTempoへ送るようにしました。Claude Codeの`--settings`に次の値を渡しています。

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_SERVICE_NAME": "claude-code",
    "OTEL_TRACES_EXPORTER": "otlp",
    "OTEL_METRICS_EXPORTER": "none",
    "OTEL_LOGS_EXPORTER": "none",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318"
  }
}
```

すると、エージェントのセッションと、エージェントが実行したビルドが1本のトレースにつながりました。

![GrafanaのExploreでclaude-code: claude_code.interactionのトレースを開いた画面。全体は52.56秒で、claude_code.llm_requestとclaude_code.toolのスパンが並び、claude_code.tool.executionの下にbuildx build .のスパンが2.98秒で入っている](/images/20261027-tempo-agent-trace.png)
*エージェントのセッションのトレースをGrafanaのExploreで開いた画面。ツールの実行のスパンの下に、エージェントが実行したビルドのスパンが入っている*

ルートは`claude_code.interaction`です。その下に、LLMへの問い合わせの`claude_code.llm_request`と、ツールの呼び出しの`claude_code.tool`が並びます。`docker buildx build`を実行したツールの呼び出しの下には`build .`があり、さらにその下にBuildKitの手順のスパンが続く構造です。エージェントが何を調べ、何を実行し、その結果ビルドの中で何が起きたのかを、1本のトレースで追えます。

## 残っている課題

CIで使う方法は試していません。CIのジョブが`TRACEPARENT`を渡せば、ビルドのスパンをジョブのスパンの下に入れられるはずです。ただ、確認したのはbuildxのコードと手元の動作だけで、CIのジョブのスパンを作る側の仕組みも別に必要になります。

Grafana Cloudへ直接送る方法も試していません。BuildKit v0.33.1はOTLPのクライアントをオプションなしで作っており（[`util/tracing/detect/otlp.go`](https://github.com/moby/buildkit/blob/v0.33.1/util/tracing/detect/otlp.go)）、OpenTelemetryのGoのexporterは送り先とヘッダーを環境変数から読みます。そのため、`OTEL_EXPORTER_OTLP_HEADERS`で認証のヘッダーを渡せるはずです。うまくいかない場合は、BuildKitとGrafana Cloudの間にCollectorを置くことになります。

## おわりに

Dockerは、ビルドのトレースを出す仕組みも、それを見る画面も持っています。ビルドを1回調べるならDockerの画面で十分で、Tempoに送る意味が出てくるのはビルドをまたいだ問いを立てるときだと確認しました。

ビルドが遅くなったと感じたことがあるなら、まず手元のbuilderに環境変数を2つ足して、トレースを溜めるところから始められます。コミットのIDを付けておけば、遅くなった時点を後から探せます。

[^otel]: アプリケーションやインフラからトレース、メトリクス、ログを集めるための、ベンダーに依存しない仕様とSDKの集まりです。CNCFのプロジェクトです。
[^trace]: 1つの処理の流れを、処理の単位であるスパンの木として記録したものです。スパンには開始時刻、所要時間、親のスパン、属性が付きます。
[^otlp]: OpenTelemetry Protocolの略で、OpenTelemetryのデータを送るためのプロトコルです。[gRPC](https://grpc.io/)（ポート4317）とHTTP（ポート4318）で送れます。
[^history-trace-tty]: 標準出力が端末でないときは、Jaeger UIを起動せずに、トレースをJaegerの形式のJSONとして標準出力に書き出しました。
[^docker-desktop]: 確認したのはLinuxのDocker Engineだけです。Docker Desktopでは`network=host`の意味が変わるので、この設定のままでは届かない可能性があります。
[^client-env]: buildx v0.29.1は、BuildKitに接続するときに`client.WithTracerDelegate`を指定しています（[`driver/manager.go`](https://github.com/docker/buildx/blob/v0.29.1/driver/manager.go)）。buildxは自分のスパンをBuildKitに渡し、BuildKitがまとめて送ります。BuildKitのREADMEにも、`buildctl`はスパンを`buildkitd`に転送するので、exporterはデーモン側だけに設定すればよいとあります。また、docker-containerドライバーでは`buildctl dial-stdio`というトレースがビルドとは別に毎回届くので、検索するときは`resource.service.name = "buildx"`で絞ると見やすくなります。
[^traceql]: Grafana Tempoのクエリ言語です。スパンの属性や所要時間でトレースを選び、`| max_over_time(duration)`のように続けると、選んだスパンから時系列のメトリクスを計算できます。
[^quantile]: 最初は`quantile_over_time(duration, .5)`で中央値を取りましたが、劣化後の約20秒のビルドが、区間を60秒にすると24.3秒、30秒にすると34.4秒になりました。`quantile_over_time`は所要時間を2のべき乗の幅のバケットに入れて近似するので、値がバケットの境目に寄ります。`max_over_time`は、区間に入ったトレースの所要時間の最大値をそのまま返しました。
[^cold]: グラフの範囲から外した1回目のビルドは、キャッシュが空だったので38.1秒かかりました。
[^childprocess]: buildx v0.29.1は、[`cmd/buildx/tracing.go`](https://github.com/docker/buildx/blob/v0.29.1/cmd/buildx/tracing.go)でBuildKit v0.25.0の[`util/tracing/env`](https://github.com/moby/buildkit/blob/v0.25.0/util/tracing/env/traceenv.go)を読み込んでいます。このパッケージが環境変数`TRACEPARENT`と`TRACESTATE`を読みます。buildxのもっと新しい版では、同じ役割のパッケージが`util/tracing/childprocess`に変わっています。
[^mcp]: [Model Context Protocol](https://modelcontextprotocol.io/)の略で、AIエージェントが外部のツールやデータにアクセスするためのプロトコルです。
[^cost]: このときのClaude Codeの表示では、費用は0.28ドルでした。1回目の試行は15ターン、40秒、0.36ドルです。
[^propagate]: ドキュメントによると、`ANTHROPIC_BASE_URL`で独自のプロキシを指定している場合は、`CLAUDE_CODE_PROPAGATE_TRACEPARENT=1`を設定しない限り`TRACEPARENT`を渡しません。
[^enhanced]: トレースを出すには`CLAUDE_CODE_ENABLE_TELEMETRY`に加えて`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA`を有効にする必要があり、2026年10月20日の時点ではbetaの機能です。
