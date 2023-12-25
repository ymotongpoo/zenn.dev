---
title: "OpenTelemetry Collectorのメトリクスのレシーバーを自作してみる"
emoji: "🔭"
type: "tech" # tech: 技術記事 / idea: アイデア
topics: ["OpenTelemetry", "Metrics"]
published: true
---

## はじめに

こんにちは！Google Cloudでオブザーバビリティを担当しているものです！この記事は[OpenTelemetry Advent Calender 2023](https://qiita.com/advent-calendar/2023/otel)の25日目の記事です。いよいよアドベントカレンダーも最終日！今年も勢いでOpenTelemetry Advent Calendarを立ち上げましたが、去年と違って割と早く全日程予約が埋まって、やはりOpenTelemetryの勢いを感じました！

【宣伝】来年2月にOpenTelemetry meetupの第2回が企画されていますので、今から興味ある人はぜひDiscordサーバーへどうぞ！（`#otel-meetup-2024-02` というチャンネルでイベントの話をしています。）

@[card](https://discord.gg/y2TeykbxaD)

で、アドベントカレンダーを立ち上げたときに、とりあえず需要がありそうなコレクターに関する記事を書こうかなとなんとなくで宣言したのですが、何も考えないまま当日を迎えてしまったので、最近遊んでいたOpenTelemetry Collectorのコンポーネント自作周りの話を書くことにします。

全部書くと1記事では当然足りないので、今回はメトリクス用のレシーバーに限定して概要を解説します。

## TL;DR

メトリクス用のレシーバーはOpenTelemetry Collectorが提供しているフレームワークに乗っかれば割と簡単に自作できます。次のステップが概要です。

0. パッケージレポジトリを作成する
1. `metadata.yaml` を書く
2. `mdatagen` で実装に必要な便利パッケージを自動生成する
3. `config.go` で設定の読み込みに関する実装を書く
4. `factory.go` でOpenTelemetry Collector builderがビルドする際のエントリーポイントを書く
5. `receiver.go` か `scaper.go` か、タイプに合わせて実装を書く
  a. `receiver.go`: 監視対象がプッシュ型の場合
  b. `scraper.go`: 監視対象がプル型の場合
6. 実体を実装する
7. OpenTelemetry Collector builder（ocb）を使ってビルドする

本記事では各ステップごとに簡単な解説をしていきます。

## （復習）OpenTelmetry Collectorのアーキテクチャ

詳細は公式ドキュメントを読んでください。

@[card](https://opentelemetry.io/docs/collector/)

OpenTelemetry Collectorには重要なコンポーネントが3つあって、それぞれレシーバー（receiver）、プロセッサー（processor）、エクスポーター（exporter）となっています。

その中でレシーバーは、監視対象から出されるメトリクスのデータをコレクター内部で処理できるようにOTLP形式に変換するためのコンポーネントです。

## メトリクス用レシーバーを自作する意義

「いまどき監視対象はOpenMetricsフォーマットなりOTLPなりでメトリクスを出すようにしてるだろうし、わざわざ独自レシーバーを書く必要は無いのでは？」という疑問を持たれる方はごもっともですし、私もそう思います。

しかしながら、世の中にはすでに長らく運用されている独自アプリケーションがたくさんあって、それらが独自のフォーマットでメトリクスを吐いているなんていうこともしばしばあります。

そういったアプリケーションをコレクター経由で監視対象にする場合に、このようなレシーバーの自作が役に立つわけです。

## 実装手順

### パッケージレポジトリを作成する

レシーバーを1つ作るだけなら特に階層を作らなくてもよいのですが、パッケージ名のみやすさのために次のような形でディレクトリを切る慣例となっています。

`github.com/<ユーザー|組織名>/レポジトリ名/コンポーネント名/パッケージ名`

たとえば本体の例ではPrometheusのレシーバーは次のようなディレクトリ名になっています。

`github.com/open-telemetry/opentelemetry-collector-contrib/receiver/prometheusreceiver`

同様にGoogle Cloud向けのエクスポーターであれば次のとおりです。

`github.com/open-telemetry/opentelemetry-collector-contrib/exporter/googlecloudexporter`

最後のパッケージ名は `対象名+コンポーネント名` とするのが慣例です。理由としては、通常GoのパッケージはFQDNでなく最後のディレクトリ名がパッケージ名として扱われるため、同じ対象に対して複数のコンポーネント（例: レシーバーとエクスポーター）を使う事になった場合の名前の衝突を避けるためと思われます。

### `metadata.yaml` を書く

「え、またYAMLファイル書くの？」と思ったかもしれませんが、私もうんざりしています。しかし、コレクターのコンポーネントを書くというのはときに単調な実装をしなければならず、非常に退屈なこともあるので、自動生成ツールによってなるべく楽に実装できるように自動生成ツールである `mdatagen` が提供されています。そのツールに与えるパッケージのメタデータが `metadata.yaml` です。

スキーマは次のファイルに書いてあります。

@[card](https://github.com/open-telemetry/opentelemetry-collector/blob/main/cmd/mdatagen/metadata-schema.yaml)

たとえばこれは遊びで作ったDiscordのチャンネルアクティビティを計測するためのレシーバーでのメタデータです。

@[card](https://github.com/ymotongpoo/opentelemetry-collector-extra/blob/main/receiver/discordreceiver/metadata.yaml)

一部を省略して転載します。

```yaml
type: discord

status:
  class: receiver
  stability:
    development: [metrics]
  codeowners:
    active: [ymotongpoo]

attributes:
  discord.channel.id:
    description: "The ID of the channel"
    type: string

metrics:
  discord.messages.count:
    description: "The number of messages sent to the channel"
    unit: "{messages}"
    sum:
      monotonic: true
      aggregation_temporality: cumulative
      value_type: int
    enabled: true
    attributes: [discord.channel.id]
```

`type` はコンポーネント名です。慣例で対象名になっています。これが、 `otel-config.yaml` で宣言に使うコンポーネント名になります。

パッケージの種類を決めるために重要なのが `status.class` です。ここでどのコンポーネントを作るのかが決まります。

メトリクス自体の宣言で重要なのは `attributes` と `metrics` です。`attributes` はメトリクスで指定する属性を宣言するためのセクションです。そして `metrics` で実際にこのレシーバーが収集して以降のプロセスに渡すメトリクスを宣言します。メトリクスの説明、単位、型、属性などを指定します。

今回はメトリクスのレシーバーだけ書いてますが、トレースやログに関する他の種類のコンポーネントでも同様に、この `metadata.yaml` で宣言します。

### `mdatagen` で `internal` のファイルを生成する

無事 `metadata.yaml` が書けたら `mdatagen` を実行します。まず `mdatagen` をインストールします。

```console
go install go.opentelemetry.io/collector/cmd/mdatagen@latest
```

インストールが終わったらただ実行するだけです。

```console
mdatagen metadata.yaml
```

これで `internal` パッケージ内にメトリクスの処理を実装する際の便利な関数や型などが用意されます。

### `config.go` を実装を書く

`config.go` というファイル名は慣例です。このファイルの中に `otel-config.yaml` に書くべき設定用の構造体を宣言します。

たとえば上のdiscordのメトリクスレシーバーを実装している場合に、対象のDiscordサーバーを知るためのトークンを `otel-config.yaml` の設定ファイルに書きたいとします。

```yaml
receivers:
  discord:
    token: USE_YOUR_TOKEN_HERE
```

この場合 `config.go` では次のように、`otel-config.yaml` の `receiver.discord` 以下をパースするための構造体を用意します。

```go
type Config struct {
    // Token is the Discord bot token.
    Token string `mapstructure:"token"`
}
```

これで設定ファイルの値を読み込む準備ができました。

### `factory.go` を書く

`config.go` と同様に `factory.go` というファイル名も慣例です。この中で `NewFactory()` という名前で [`receiver.Factory`](https://pkg.go.dev/go.opentelemetry.io/collector/receiver#Factory) を返す関数を用意しておきます。

実態としては [`receiver.NewFactory`](https://pkg.go.dev/go.opentelemetry.io/collector/receiver#NewFactory) を呼んで、その戻り値を返すだけなのですが、その引数としてどのテレメトリーシグナルを扱うかを指定します。

今回の例ではこんな感じです。

```go
// NewFactory returns a new factory for the Discord receiver.
func NewFactory() receiver.Factory {
    return receiver.NewFactory(
        metadata.Type,
        createDefaultConfig,
        receiver.WithMetrics(createMetricsReceiver, metadata.MetricsStability),
    )
}
```

ここで指定している `createMetricsReceiver()` の中で、実体となるメインのレシーバーの構造体を返すようにします。

### `receiver.go` を書く

いよいよ中心となる機能の実装です。監視対象がメトリクスの元データを公開しているかでファイル名を変える慣例になっていて、プッシュ型なら `receiver.go` 、プル型なら `scraper.go` になります。Discordの場合はWebSocket経由でイベント発生ごとにデータが送られてくるプッシュ型になるため、`receiver.go`とします。

`receiver.go` でやることは単純で「外部から送られてきたデータをいい感じに処理して、コレクター内部で扱えるフォーマットである `pmetrics` 形式に変換する」というだけです。

レシーバーの実装の本体となる構造体は [`receiver.Metrics`](https://pkg.go.dev/go.opentelemetry.io/collector/receiver#Metrics) インターフェイスを実装する必要がありますが、このインターフェイスは型合わせのためだけのものです。実際はそこに合成されている、すべてのテレメトリータイプ＆コンポーネントタイプで共通の[`component.Component`](https://pkg.go.dev/go.opentelemetry.io/collector/component#Component)インターフェイスを実装します。これは `Start` と `Shutdown` というメソッドを実装さえすれば良いというとても単純なインターフェイスです。

それぞれのメソッドの役割は以下の通りとても単純です。

* `Start`: コレクター起動時にレシーバーの実体を開始する
* `Shutdown`: コレクター終了時にレシーバーの実体を終了する

特に `Start` でちゃんと実体を起動できてしまえば良いので、今回のDiscord用のレシーバーは雑にこういった流れの実装になります。

```go
func (r *discordReceiver) Start(ctx context.Context, _ component.Host) error {
    ...(略)...
    r.dh, err = newDiscordHandler(r.consumer, r.config, r.settings, r.obsrecv)
    ...(略)...
    if err := r.dh.run(ctx); err != nil {
        return err
    }
    return nil
}
```

ここで `discordReceiver` はこのような構造体になっています。

```go
type discordReceiver struct {
    consumer consumer.Metrics
    settings receiver.CreateSettings
    cancel   context.CancelFunc
    config   *Config
    dh       *discordHandler
    obsrecv  *receiverhelper.ObsReport
}
```

ここで、大事なフィールドは次のとおりです。

* `consumer`: コレクター内部のメトリクスの管理を行うもの
* `settings`: このコンポーネントのコレクター内部でのメタデータ
* `config`: `otel-config.yaml` から渡ってきた設定
* `dh`: Diccord APIのクライアントを実装するハンドラー

### 実体を実装する

コンポーネントによっては `receiver.go` 内で直接実装してしまっていますが、自分は `discord.go` というファイルの中で実装しました。

このハンドラーの実装の中で忘れかけていた `mdatagen` で生成した `internal` パッケージ内の関数が大活躍します。

`metadata.MetricsBuilder` という構造体が作られていますが、これは名前の通り `metadata.yaml` で宣言したメトリクスを作成するためのヘルパーメソッドと、それで生成したメトリクスを `consumer.Metrics` に渡すまでのバッファを用意してくれます。

実際に呼び出している例は次のようになります。

```go
dh.mb.RecordDiscordMessagesCountDataPoint(now, 1, channelID)
```

メトリクスを記録する時刻、メトリクスの値、属性を記録するための専用のメソッドがわかりやすいメソッド名で用意されているのがわかります。

このメソッドを使ってある程度記録したあと、定期的にバッファからフラッシュするために、`mb.Emit()` を呼んで、その戻り値を[`consumer.ConsumeMetrics`](https://pkg.go.dev/go.opentelemetry.io/collector/consumer#ConsumeMetricsFunc.ConsumeMetrics) に与えてあげます。

### ocbを使ってビルドする

一通り実装が終わったら実際にコレクターに組み込んで試してみます。ocbの設定ファイルである `otelcol-builder.yaml` の書き方は非常に簡単で、使うコレクターのパッケージを指定するだけです。

設定ファイルの書き方はここに説明があります。

@[card](https://github.com/open-telemetry/opentelemetry-collector/tree/main/cmd/builder#configuration)

ocbの使い方については[逆井さんの記事](https://zenn.dev/k6s4i53rx/articles/df59cb65b34ef8)が日本語で読めて便利です。インストールとビルドはこちらのとおりです。

```console
go install go.opentelemetry.io/collector/cmd/builder@latest
builder --config=otelcol-builder.yaml
```

ここで、通常は次のようにして、リリース済みのコンポーネントを指定するわけですが、今作っているコンポーネントはリリースしていないため、このような形で指定できません。

```yaml
receivers:
  - gomod: go.opentelemetry.io/collector/receiver/otlpreceiver v0.88.0
```

そのため、`go.mod`と同様の`replaces`を追記してあげる必要があります。

```yaml
receivers:
  - gomod: go.opentelemetry.io/collector/receiver/otlpreceiver v0.88.0
  - gomod: github.com/ymotongpoo/opentelemetry-collector-extra/receiver/discordreceiver v0.0.0

replaces:
  - github.com/ymotongpoo/opentelemetry-collector-extra/receiver/discordreceiver => ./receiver/discordreceiver
```

これで、ローカルの開発版を参照してくれます。

以上、駆け足でメトリクスのレシーバーの実装方法について解説しました。

## サンプル

今回の解説に使ったサンプルコードはこちらのレポジトリでPoCで書いたものを用いました。実装がおかしいなどの指摘があれば、issueで登録いただけるとありがたいです。

@[card](https://github.com/ymotongpoo/opentelemetry-collector-extra/tree/main/receiver/discordreceiver)

これだけでは分かりづらいと思いますので、本体の実装なども見ながら、本記事を上から読んでいくと、理解が深まるのではないかと思います。

@[card](https://github.com/open-telemetry/opentelemetry-collector-contrib)
@[card](https://github.com/open-telemetry/opentelemetry-collector)
