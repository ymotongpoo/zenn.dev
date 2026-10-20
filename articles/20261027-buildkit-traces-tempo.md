---
title: "Dockerのビルドを遅くしたコミットをGrafana Tempoのトレースで見つける"
emoji: "🐳"
type: "tech"
topics: ["Docker", "OpenTelemetry", "grafana", "Tempo", "BuildKit"]
published: false
---

:::message
2026年10月20日に確認した内容です。動作確認には次のバージョンを使いました。

- Docker Engine 29.0.0、buildx v0.29.1（Ubuntu 26.04.1）
- BuildKit v0.33.1（builderのイメージを`moby/buildkit:v0.33.1`に固定）
- [grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm) 0.37.0（Grafana 13.2.3、Tempo 3.1.0を含む）
- [mcp-grafana](https://github.com/grafana/mcp-grafana) 2.0.2
- [Claude Code](https://code.claude.com/docs/en/overview) 2.1.303
- [gcx](https://grafana.com/docs/grafana/latest/as-code/observability-as-code/grafana-cli/gcx/) 0.3.0

記事中のコマンドは、手元で使ったポート番号をotel-lgtmのデフォルトに戻して書いています。
:::

## はじめに

こんにちは、Grafana Labsでデベロッパーアドボケイトをしているものです。

2026年11月3日にシンガポールで開かれる[Grafana & Friends Singapore x Docker](https://www.meetup.com/grafana-and-friends-singapore/events/316976705/)で話すことになりました。[Docker](https://www.docker.com/)との共催というせっかくの機会なので、題材には以前から話そうと思っていたDockerのビルドのトレースを選んでいます。Docker自身もビルドのトレースを画面に出せますが、[Grafana Tempo](https://grafana.com/oss/tempo/)に送って溜めておくと、ビルドをまたいだ調査が可能です。この記事は、その手順と、溜めたトレースをAIに調べさせた結果のまとめです。

## TL;DR

Dockerのビルドを実行する[BuildKit](https://docs.docker.com/build/buildkit/)は、ビルドごとにOpenTelemetryのトレースを出しています。そのトレースは`docker buildx history trace`でJaeger UIに開けるので、ビルドを1回調べるならその画面で十分です。ただし、BuildKitが残す履歴はデフォルトで48時間か50回分までです。同じトレースをGrafana Tempoに送ってコミットのIDを付けておけば、どのコミットからビルドが遅くなったのかをグラフで特定できます。コーディングエージェントやGrafana Assistantにトレースを読ませれば、遅くしたコミットと手順を見つけるところまで任せられます。

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

トレースには、buildx（サービス名`buildx`）とBuildKit（サービス名`buildkitd`）のスパンが1本につながって入ります。ルートのスパンは`build .`です[^traceparent]。クライアント側のbuildxには環境変数を渡していませんが、buildxのスパンもTempoに届きます[^client-env]。

![GrafanaのExploreでTempoのトレースを開いた画面。buildx: build .の全体が20.87秒で、[build 4/4] RUN go mod download && go build -o /out/hello .のスパンが19.36秒になっている](/images/20261027-tempo-build-regressed.png)
*同じ種類のビルドのトレースをGrafanaのExploreで開いた画面。上部はトレースの概要で、下はDockerfileの手順のスパンのあたりを切り出した*

## ビルドを溜めると見えるもの

ここまでなら、Dockerの画面で十分です。Tempoへ送る価値が出てくるのは、ビルドが1回ではなく、CI/CDのように継続的に多数行われるときです。

[BuildKitの設定](https://github.com/moby/buildkit/blob/v0.33.1/docs/buildkitd.toml.md)では、ビルドの履歴はデフォルトで`maxAge = 172800`（48時間）、`maxEntries = 50`です。`docker buildx history trace`で開けるのは、この履歴に残っているビルドだけで、`--compare`で2回分を並べて比べる場合も同じ制約がかかります。

使い捨てのCIのrunnerでは、ジョブが終わればbuilderごと履歴も消えます。DockerはGitHub Actions向けに、[ビルドの記録をZIPのアーティファクトとして残す](https://docs.docker.com/build/ci/github-actions/build-summary/)機能を持っています。ただ、それをDocker Desktopに取り込んで見るのは、CIの実行1回分ずつです。「どのコミットからビルドが遅くなったのか」を答えるには、何十回分ものビルドを取得して比較しなければなりません。

そこで、コミットを重ねながら何度もビルドし、全部のトレースをTempoに溜めました。題材は、Prometheusのクライアントライブラリに依存する小さなGoのHTTPサーバーです。はじめは、依存のダウンロードとビルドのキャッシュをキャッシュマウントで再利用するDockerfileでビルドしました。

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

途中で、Dockerfileを「整理した」コミットを入れて、キャッシュマウントをわざと外しました。あわせて`COPY . .`も依存のダウンロードより前に移した状態です。この順序だと、ソースを1行変えるたびに依存のダウンロードと全パッケージのコンパイルがやり直しになります。変わったのはビルドのステージだけなので、示すのもその部分だけです。

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

ここまでの各ビルドの所要時間を、[TraceQL](https://grafana.com/docs/tempo/latest/traceql/)[^traceql]のメトリクスのクエリでグラフにしました。ルートのスパンだけを選んで、30秒ごとの最大値を取っています[^quantile]。

```traceql
{ resource.service.name = "buildx" && span:parentID = "" } | max_over_time(duration)
```

![GrafanaのExploreでTraceQLのメトリクスのクエリを実行した折れ線グラフ。05:23:00までは約2秒で推移し、05:23:30の点から約20秒に上がったまま戻らない](/images/20261027-tempo-build-duration.png)
*各ビルドの所要時間をTraceQLのmax_over_timeでGrafanaに描いた画面。点の時刻は30秒の区間の終わりを表す*

トレースで見ると、キャッシュマウントを外す前のビルドは1.9〜2.5秒で終わり、外した後は20.3〜21.7秒に延びて戻りません[^cold]。跳ねた直後のトレースを開けば、`vcs.ref.head.revision`からコミットがわかります。このデモでは「整理した」コミットでした。遅くなる前後のトレースを並べると、どの手順が延びたのかもわかります。

![GrafanaのExploreで遅くなる前のビルドのトレースを開いた画面。全体は2.5秒で、go mod downloadの手順はload cacheになり、[build 6/6] RUN go buildのスパンが904.78ミリ秒になっている](/images/20261027-tempo-build-good.png)
*遅くなる前のビルドのトレースをGrafanaのExploreで開いた画面。依存のダウンロードはキャッシュから読まれ、go buildは約0.9秒で終わっている*

遅くなる前は、依存のダウンロードの手順が`load cache:`で始まるスパンになり、キャッシュから読まれています。遅くなった後は、手順が`RUN go mod download && go build`の1つにまとまり、その手順だけで19.36秒かかっています。

手順のスパン名には、`RUN`のコマンドがそのまま入ります。Dockerfileを変えるとスパン名も変わるので、変更の前後を1本の系列で比べるなら、ルートのスパンの所要時間を使ってください。

## エージェントに直させる

Tempoに溜めたトレースは、人だけでなくプログラムからも問い合わせられます。[mcp-grafana](https://github.com/grafana/mcp-grafana)は、GrafanaをMCP[^mcp]のサーバーとして公開するツールです。Tempo向けには次のようなツールを持っています。

- `search_tempo_traces`：TraceQLでトレースを検索する
- `query_tempo_metrics`：TraceQLのメトリクスを計算する
- `diff_tempo_traces`：2本のトレースを比べる

これをコーディングエージェントにつなぎ、ビルドが遅くなった原因を調べさせました。mcp-grafanaの起動方法とMCPのクライアントへの登録方法は、[mcp-grafanaの公式ドキュメント](https://github.com/grafana/mcp-grafana)を参照してください。書き込み系のツールは`--disable-write`で外せるので、調査に使うだけなら外しておくと安心です。

今回は[Claude Code](https://code.claude.com/docs/en/overview)を使いましたが、MCPのサーバーを使えるほかのコーディングエージェント（Codexなど）でも同じようにできるでしょう。Gitの履歴の参照や`docker buildx build`の実行など、必要なツールは適宜許可してください。頼んだ内容は次のとおりです。

```text
コンテナのビルドが最近遅くなりました。ビルドのトレースはTempo（Grafanaのデータソース UID "tempo"）に送っています。各ビルドにはサービス buildx の "build ." という名前のスパンがあり、そのスパンのリソース属性 vcs.ref.head.revision にビルドしたコミットが入っています。Tempoのトレースを使って、どのコミットでなぜビルドが遅くなったのかを調べ、このディレクトリのDockerfileを直してください。直したら

    docker buildx build --builder gf-demo --output type=cacheonly .

で再ビルドし、新しいビルドが速くなったことをTempoで確かめてください。新しいトレースが検索できるようになるまで1〜2分かかることがあります。
```

エージェントは、まずGitの履歴を読み、`search_tempo_traces`でコミットごとの所要時間を並べました。そこから導いた結論は、所要時間が約2秒から約21秒に跳ねたのは「整理した」コミットだというものです。遅くなる前と後のトレースを`diff_tempo_traces`で比べ、`RUN go mod download && go build`の手順に約19.9秒かかるようになったことと、以前は依存のダウンロードがキャッシュから読まれていたことも確かめました。

修正では、`go.mod`と`go.sum`を先にコピーする順序とキャッシュマウントを元に戻し、後から足されたラベルは残しました。再ビルドのあとは新しいトレースが検索できるようになるのを待ち、所要時間が2.31秒に戻ったことをTempoで確かめています。全体で約3分かかり、そのうち約1分半は新しいトレースを待つ時間でした[^cost]。

## オブザーバビリティのSaaSに送る利点

ここまでは、手元のotel-lgtmにトレースを送ってきました。otel-lgtmは、イメージの説明にあるとおり開発、デモ、テストのための環境で、コンテナを消せばトレースも消えます。ビルドをまたいで問いを立てるには、トレースを長く残せて、CIのrunnerからも送れる場所が必要です。[Grafana Cloud](https://grafana.com/products/cloud/)のようなオブザーバビリティのSaaSに送ると、その場所を自分で運用せずに済みます。

保持期間は、Grafana CloudのTracesではFreeプランで14日、Proプランで30日です[^pricing]。BuildKitの履歴の48時間か50回分より長く、手元の開発機のビルドとCIのビルドを同じTempoに入れて、同じクエリで比べられます。

Grafana Cloudへ送るときも、builderに渡す環境変数を変えるだけです。Grafana Cloudの[ドキュメント](https://grafana.com/docs/grafana-cloud/send-data/otlp/send-data-otlp/)が示すOTLPの送り方はHTTPなので、BuildKitのデフォルトのgRPCから`http/protobuf`に切り替えました。エンドポイントと認証のヘッダーは、Grafana CloudのポータルのOpenTelemetryのタイルで生成した値をそのまま使いました。

```sh
docker buildx create --name gf-cloud --driver docker-container \
  --driver-opt image=moby/buildkit:v0.33.1 \
  --driver-opt env.OTEL_TRACES_EXPORTER=otlp \
  --driver-opt env.OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf \
  --driver-opt "env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces" \
  --driver-opt "env.OTEL_EXPORTER_OTLP_TRACES_HEADERS=${OTEL_EXPORTER_OTLP_HEADERS}" \
  --bootstrap
```

トレース専用の変数（名前に`TRACES`が入るもの）だけを渡しているのは、BuildKitが`OTEL_EXPORTER_OTLP_ENDPOINT`を見るとメトリクスの送信も始めるためです[^detect]。このbuilderで手元と同じ20回のビルドを流すと、21本（動作確認の1回を含む）のトレースが全部Grafana CloudのTempoに届きました[^cloud-search]。トークンはbuilderのコンテナの環境変数とbuildxの設定ファイルに残るので、使い終わったら`docker buildx rm gf-cloud`でbuilderを消してください。

### Grafana Assistantに調べさせる

SaaSの側には、溜めたトレースを調べる機能も最初から用意されています。その例が、Grafana Cloudに組み込まれたAIアシスタントの[Grafana Assistant](https://grafana.com/docs/grafana-cloud/machine-learning/assistant/)です。[ドキュメント](https://grafana.com/docs/grafana-cloud/platform/grafana-assistant/guides/querying/)によると、AssistantはTempoを含むデータソースに問い合わせ、TraceQLのクエリを書いて実行できます。トレースのIDを渡せば1本のトレースをウォーターフォールで表示でき、実験的な機能として、あるトレースと比べる候補のトレースを探すこともできます。

前の節でエージェントに調べさせたときは、mcp-grafanaを起動してエージェントに登録する準備が必要でした。Assistantは最初からスタックのデータソースにつながっているので、この準備は要らないのが利点です。ビルドが遅くなったことに気づいた人が、Grafanaの画面からそのまま「ビルドの所要時間はいつから延びたか」と聞けば済みます。原因の調査まではAssistantに任せ、Dockerfileを直して再ビルドするところはリポジトリを編集できるコーディングエージェントに任せる、という分担です。

実際に、Grafana Cloudへ送った20回分のビルドについてAssistantに聞きました。AssistantはGrafanaの画面のほか、Grafanaのコマンドラインツールの`gcx`からも呼べるので、今回は`gcx`を使いました。伝えたのは、コーディングエージェントに渡したのと同じ前提だけです。

```sh
gcx assistant prompt 'コンテナのビルドが最近遅くなりました。ビルドのトレースはTempo（データソース grafanacloud-shophub-traces）に送っています。各ビルドにはサービス buildx の "build ." という名前のスパンがあり、そのスパンのリソース属性 vcs.ref.head.revision にビルドしたコミットが入っています。過去1時間のトレースから、ビルドの所要時間がいつから延びたのか、どのコミットからなのか、ビルドのどの手順が遅くなったのかを調べてください。'
```

Assistantはデータソースへの問い合わせを17回行い、132秒で答えを返しました。答えの冒頭は次のとおりです。

> **結論:** ビルド時間は、およそ 07:09 UTC に約2秒から約20秒へ延びました。最初に遅くなったコミットは `9eac8b9` です。遅くなった手順は Dockerfile の `RUN go mod download && go build -o /out/hello .` です。

`9eac8b9`は「整理した」コミットで、答えは正しいものでした。手順についても、速いビルドの6ステップと遅いビルドの4ステップを比べた結果、遅いほうでは`RUN go mod download && go build`の1つの手順が約19.4秒、全体の約95%を占めるという答えです。依存の取得のキャッシュが効かなくなったことを原因として推測しつつ、「このデータにはコミットの親子順がありません」と書き、時間の順で最初に遅くなったコミットだという限定も付けていました。動作確認のために送った30.2秒のビルドも、コミットの属性がないことに気づいて、ほかのビルドとは別に扱っていました。

Assistantは、自前で運用しているGrafanaからGrafana CloudのAssistantにつないで使うこともできます。ただし、複数のデータソースを調べてレポートにまとめるInvestigationsと、Grafana CloudのMCPへの接続は、Grafana Cloudに限られた機能です[^assistant-self]。

## 次に書きたいこと

この記事では、長くなるので、ビルドのトレースをGrafanaに送り、溜めたトレースをAIに調べさせるところまでにしました。次は、これを踏まえてCIの設定も含めて書きたいと考えています。CIのジョブが`TRACEPARENT`を渡せば、ビルドのスパンをジョブのスパンの下に入れて、パイプライン全体の中でビルドを見られるはずです。

## おわりに

Dockerは、ビルドのトレースを出す仕組みも、それを確認する画面も持っています。ビルドを1回調べるならDockerの画面で十分で、Tempoに送る意味が出てくるのはビルドをまたいだ問いを立てるときだと確認しました。

ビルドが遅くなったと感じたことがあるなら、まず手元のbuilderに環境変数を2つ足して、トレースを溜めるところから始めてみてください。コンテナビルドでもオブザーバビリティを高めていきましょう。

[^otel]: アプリケーションやインフラからトレース、メトリクス、ログを集めるための、ベンダーに依存しない仕様とSDKの集まりです。CNCFのプロジェクトです。
[^trace]: 1つの処理の流れを、処理の単位であるスパンの木として記録したものです。スパンには開始時刻、所要時間、親のスパン、属性が付きます。
[^otlp]: OpenTelemetry Protocolの略で、OpenTelemetryのデータを送るためのプロトコルです。[gRPC](https://grpc.io/)（ポート4317）とHTTP（ポート4318）で送れます。
[^history-trace-tty]: 標準出力が端末でないときは、Jaeger UIを起動せずに、トレースをJaegerの形式のJSONとして標準出力に書き出しました。
[^docker-desktop]: 確認したのはLinuxのDocker Engineだけです。Docker Desktopでは`network=host`の意味が変わるので、この設定のままでは届かない可能性があります。
[^client-env]: buildx v0.29.1は、BuildKitに接続するときに`client.WithTracerDelegate`を指定しています（[`driver/manager.go`](https://github.com/docker/buildx/blob/v0.29.1/driver/manager.go)）。buildxは自分のスパンをBuildKitに渡し、BuildKitがまとめて送ります。BuildKitのREADMEにも、`buildctl`はスパンを`buildkitd`に転送するので、exporterはデーモン側だけに設定すればよいとあります。また、docker-containerドライバーでは`buildctl dial-stdio`というトレースがビルドとは別に毎回届くので、検索するときは`resource.service.name = "buildx"`で絞ると見やすくなります。
[^traceql]: Grafana Tempoのクエリ言語です。スパンの属性や所要時間でトレースを選び、`| max_over_time(duration)`のように続けると、選んだスパンから時系列のメトリクスを計算できます。
[^quantile]: `quantile_over_time(duration, .5)`で中央値を取ると、約20秒のビルドが、区間を60秒にすると24.3秒、30秒にすると34.4秒になります。`quantile_over_time`は所要時間を2のべき乗の幅のバケットに入れて近似するので、値がバケットの境目に寄ります。`max_over_time`は、区間に入ったトレースの所要時間の最大値をそのまま返します。
[^cold]: グラフの範囲から外した最初のビルドは、キャッシュが空だったので38.1秒かかりました。
[^traceparent]: buildxは、環境変数`TRACEPARENT`があると、それを親のトレースコンテキストとして扱います。この変数が設定されたシェルからビルドすると、ビルドがその親のトレースに入り、`build .`がルートになりません。ビルドを1回ずつ別のトレースにしたいなら、`TRACEPARENT`を外してから実行してください。buildx v0.29.1は、[`cmd/buildx/tracing.go`](https://github.com/docker/buildx/blob/v0.29.1/cmd/buildx/tracing.go)でBuildKit v0.25.0の[`util/tracing/env`](https://github.com/moby/buildkit/blob/v0.25.0/util/tracing/env/traceenv.go)を読み込んでいます。このパッケージが`TRACEPARENT`と`TRACESTATE`を読みます。buildxのもっと新しいバージョンでは、同じ役割のパッケージが`util/tracing/childprocess`に変わっています。
[^detect]: BuildKit v0.33.1の[`util/tracing/detect/otlp.go`](https://github.com/moby/buildkit/blob/v0.33.1/util/tracing/detect/otlp.go)は、OTLPのクライアントをオプションなしで作っています。OpenTelemetryのGoのexporterは、送り先、プロトコル、ヘッダーを環境変数から読みます。
[^mcp]: [Model Context Protocol](https://modelcontextprotocol.io/)の略で、AIエージェントが外部のツールやデータにアクセスするためのプロトコルです。
[^cost]: Claude Codeの表示では18ターンで、費用は0.33ドルでした。
[^pricing]: 2026年10月20日に[Grafana Cloudの料金のページ](https://grafana.com/pricing/)で確認した値です。同じページによると、Grafana AssistantはFreeプランでも使え、1か月あたり3人のアクティブなAIユーザーまで（1人あたり月4,000万トークン）が含まれます。
[^assistant-self]: [Grafana Assistantの紹介のページ](https://grafana.com/docs/grafana-cloud/machine-learning/assistant/introduction/)によると、自前で運用しているGrafanaから使う場合も、チャット、ダッシュボードの作成、クエリ、ナビゲーションは使えます。
[^cloud-search]: Grafana CloudのTempoでビルドのトレースを検索するときは、`name = "build ."`で絞ると確実に見つかります。
