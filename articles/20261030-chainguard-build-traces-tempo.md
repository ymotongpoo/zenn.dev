---
title: "melangeとapkoのビルドをGrafana Tempoのトレースで調べる"
emoji: "📦"
type: "tech"
topics: ["chainguard", "opentelemetry", "grafana", "tempo", "container"]
published: false
published_at: 2026-10-30 09:00
---

:::message
- Ubuntu 26.04.1、Docker Engine 29.0.0
- melange v0.63.2、apko v1.4.13のソースから作った実験用バイナリ
- Go 1.27.0、OpenTelemetry Go SDKとOTLP/gRPC exporter v1.47.0
- [grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm) 0.37.0（Grafana 13.2.3、Tempo 3.1.0）

記事中のOTLP送信は、CLIに初期化処理を追加した結果です。標準CLIに環境変数を渡すだけで送れる手順ではありません。Wolfiのパッケージ索引は固定していないため、再実行時には依存パッケージや所要時間が変わります。
:::

## はじめに

先日の[「Dockerのビルドを遅くしたコミットをGrafana Tempoのトレースで見つける」](https://zenn.dev/ymotongpoo/articles/20261027-buildkit-traces-tempo)では、BuildKitのトレースを調べました。[Chainguardのイメージ作成ツールについての本](https://zenn.dev/ymotongpoo/books/chainguard-image-toolchain)も書いているので、今回はDockerfileを使わないビルドツールのmelangeとapkoでのトレースを調べました。

## TL;DR

melangeとapkoには、すでに[OpenTelemetry](https://opentelemetry.io/ja/)の計装があります。SDK[^sdk]と送信処理を初期化する実験用の変更で、ビルド内部のスパン[^span]を[Grafana Tempo](https://grafana.com/oss/tempo/)へ送れました。melangeの内部でビルド環境を作るapkoの処理も、同じトレースの一部です。ただし、今回確認したmelangeでは、`configure`や`make`の各工程は個別のスパンになりません。

[^sdk]: SDKは、スパンの記録、サンプリング、まとめて送る処理などを提供するライブラリです。

[^span]: スパンは、開始時刻と終了時刻を持つ処理の記録です。親子関係を持つスパンの集まりをトレースと呼びます。ビルド全体だけでなく、その内部で何に時間がかかったかを調べるために使います。

## melangeとapkoの分担

[melange](https://github.com/chainguard-dev/melange/tree/v0.63.2)はソースコードからAPKパッケージを作り、[apko](https://github.com/chainguard-dev/apko/tree/v1.4.13)はAPKパッケージを組み合わせてOCIコンテナイメージを作ります。今回も[本](https://zenn.dev/ymotongpoo/books/chainguard-image-toolchain)と同様にGNU Helloを使い、melangeで`hello-2.12-r0.apk`を作ってから、apkoで実行用イメージにしました。

ここで、melange自身のビルド環境にもapkoが使われています。melangeの[ビルド環境を準備する処理](https://github.com/chainguard-dev/melange/blob/402004649f817966440662612d0ea7302b95a858/pkg/build/build.go#L345)は、必要なAPKパッケージをapkoのライブラリでインストールし、ビルド用のコンテナを用意します。今回はコンパイラーや`make`などが入った環境です。

そのため、トレースに現れるapkoには2つの役割があります。melangeの内部でビルド環境を作る処理と、完成したHelloのAPKから最終イメージを作る別のCLIです。前者はmelangeのトレースに含まれ、後者は独立したトレースとして取得しました[^apko-version]。

[^apko-version]: melange v0.63.2が依存するapkoライブラリはv1.4.11です。[go.mod](https://github.com/chainguard-dev/melange/blob/402004649f817966440662612d0ea7302b95a858/go.mod#L6)で確認できます。別途ビルドしたapko CLIはv1.4.13で、同じバージョンではありません。

## 標準のトレース出力

melangeには、トレースをファイルに保存する`--trace`があります。設定ファイルと署名鍵を用意した環境では、次のように指定できます。

```sh
melange build hello.yaml --arch x86_64 --signing-key melange.rsa \
  --trace melange-trace.json
```

このファイルに入るのは、OpenTelemetry Goの`stdouttrace` exporter[^exporter]が書き出すJSONです。[CLIの実装](https://github.com/chainguard-dev/melange/blob/402004649f817966440662612d0ea7302b95a858/pkg/cli/build.go#L305)では、ファイルを開き、それを出力先にしたexporterとTracerProviderを作っています。TracerProviderは、アプリケーション内のスパンを記録するSDKの設定を管理します。

[^exporter]: exporterは、SDKが記録したスパンをファイルや外部のサービスへ書き出す部品です。

標準melangeの公式コンテナでHelloをビルドすると、このファイルから546スパンを取得できました。計装ライブラリごとの内訳は次のとおりです。

| 計装ライブラリ | 主な処理 | スパン数 |
| --- | --- | ---: |
| melange | ビルド全体、環境準備、APK生成 | 10 |
| apko | ビルド環境のイメージ作成 | 9 |
| go-apk | APKの取得、検証、インストール | 527 |

この時点で、melange自身の処理だけでなく、依存ライブラリの内部まで記録されていることがわかります。ただし、ファイルのJSONはOTLP[^otlp]とは別の形式です。TempoのOTLPエンドポイントにそのまま送るには形式が合わないため、今回はSDKの出力先をOTLP exporterに変えました。

[^otlp]: OTLP（OpenTelemetry Protocol）は、トレースなどのテレメトリーを転送するプロトコルです。今回はgRPCで送信します。

apkoにも、たとえば[`BuildImage`](https://github.com/chainguard-dev/apko/blob/217f25a71fd6f18f00fb1024f9b251dc7127bfd5/pkg/build/build.go)や[`GenerateImageSBOM`](https://github.com/chainguard-dev/apko/blob/217f25a71fd6f18f00fb1024f9b251dc7127bfd5/pkg/build/sbom.go)のスパンがあります。確認したバージョンの[起動処理](https://github.com/chainguard-dev/apko/blob/217f25a71fd6f18f00fb1024f9b251dc7127bfd5/main.go)と[CLIの初期化](https://github.com/chainguard-dev/apko/blob/217f25a71fd6f18f00fb1024f9b251dc7127bfd5/internal/cli/commands.go)にはSDKとexporterを設定する処理がないため、こちらも初期化処理を追加しました。

## OTLP exporterの追加

ここからは、melangeとapkoのソースをローカルで改変し、独自のCLIをビルドする実験です。既存の計装からどのようなトレースを得られるかを確かめるため、両CLIに共通の`runTraced`関数を追加しました。OpenTelemetryのSDKとOTLP/gRPC exporterを初期化し、CLIの処理にスパンを持つ`context.Context`を渡す関数です。CLI全体を表す親スパンも1つ追加しているので、今回のルートスパンは独自の計装になります。

melangeの`main.go`では、CLIの呼び出しを次のように変更します。

```diff
- if err := cli.New().ExecuteContext(ctx); err != nil {
+ if err := runTraced(ctx, "melange", cli.New().ExecuteContext); err != nil {
```

apkoの`main.go`では、`mainE`内の戻り値を変更します。

```diff
- return cli.New().ExecuteContext(ctx)
+ return runTraced(ctx, "apko", cli.New().ExecuteContext)
```

この変更で、既存の内部計装が親のコンテキストを引き継ぎます。ビルドを実行する処理や、工程ごとの計装は変更していません。

`runTraced`では、CLIが戻ったときに親スパンを終了し、SDKの`Shutdown`を呼びます。送信待ちのスパンを残したままプロセスが終了するのを避けるためです。melangeは[エラー時に`os.Exit`する実装](https://github.com/chainguard-dev/melange/blob/402004649f817966440662612d0ea7302b95a858/main.go#L31)なので、`main`の`defer`だけに頼らず、その手前で送信を終えます。

:::details 実験用のtelemetry.go全文
次のファイルを、両ツールのソースの`main.go`と同じディレクトリに置きます。`OTEL_TRACES_EXPORTER=otlp`のときだけ初期化する実験用の実装です。標準の`--trace`と併用するとグローバルなTracerProviderが置き換わるため、併用をエラーにしています。

```go
// Experimental entrypoint support, copied into each pinned upstream source tree.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// runTraced enables the upstream instrumentation without changing build logic.
// The first experiment deliberately starts an independent trace for each CLI.
func runTraced(ctx context.Context, service string, run func(context.Context) error) (err error) {
	if os.Getenv("OTEL_TRACES_EXPORTER") != "otlp" {
		return run(ctx)
	}
	for _, arg := range os.Args[1:] {
		if arg == "--trace" || strings.HasPrefix(arg, "--trace=") {
			return errors.New("this experiment cannot combine OTLP with melange --trace (it replaces the global provider)")
		}
	}

	exporter, err := otlptracegrpc.New(ctx)
	if err != nil {
		return fmt.Errorf("initialize OTLP exporter: %w", err)
	}
	res, err := resource.New(ctx,
		resource.WithAttributes(attribute.String("service.name", service)),
		resource.WithFromEnv(), resource.WithTelemetrySDK(),
	)
	if err != nil {
		_ = exporter.Shutdown(context.Background())
		return fmt.Errorf("initialize trace resource: %w", err)
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithResource(res),
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
		sdktrace.WithBatcher(exporter, sdktrace.WithMaxQueueSize(8192)),
	)
	otel.SetTracerProvider(tp)
	name := service
	if len(os.Args) > 1 {
		name += " " + os.Args[1]
	}
	ctx, span := tp.Tracer("chainguard-build-traces/experiment").Start(ctx, name)
	fmt.Fprintf(os.Stderr, "TRACE service=%s trace_id=%s\n", service, span.SpanContext().TraceID())
	defer func() {
		if err != nil {
			span.RecordError(err)
			span.SetStatus(codes.Error, err.Error())
		}
		span.End()
		// A failed/interrupted command must also drain the batch processor.
		flushCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if flushErr := tp.Shutdown(flushCtx); flushErr != nil {
			err = errors.Join(err, fmt.Errorf("flush traces: %w", flushErr))
		}
	}()
	return run(ctx)
}
```
:::

:::details ソースの取得と実験用バイナリのビルド
作業用ディレクトリに`telemetry.go`を保存したうえで、次のコマンドでソースを取得します。

```sh
mkdir -p .work
curl -fL https://codeload.github.com/chainguard-dev/melange/tar.gz/refs/tags/v0.63.2 \
  -o .work/melange-v0.63.2.tar.gz
curl -fL https://codeload.github.com/chainguard-dev/apko/tar.gz/refs/tags/v1.4.13 \
  -o .work/apko-v1.4.13.tar.gz
tar -xzf .work/melange-v0.63.2.tar.gz -C .work
tar -xzf .work/apko-v1.4.13.tar.gz -C .work
cp telemetry.go .work/melange-0.63.2/
cp telemetry.go .work/apko-1.4.13/
```

先ほどの差分を両ツールの`main.go`に適用してから、ビルドします。

```sh
for spec in melange:0.63.2 apko:1.4.13; do
  tool=${spec%%:*}
  version=${spec#*:}
  (
    cd ".work/$tool-$version"
    go get go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc@v1.47.0 \
      go.opentelemetry.io/otel/sdk@v1.47.0
    CGO_ENABLED=0 GOMAXPROCS=2 go build -p=2 -trimpath -buildvcs=false \
      -o "../$tool-otel" .
  )
done
```

`.work/melange-otel`と`.work/apko-otel`が、以降の手順で使うバイナリです。
:::

## HelloのビルドをTempoへ送る

送り先には、GrafanaとTempo、OpenTelemetry Collectorなどをまとめたotel-lgtmを使います。ほかの検証環境と競合しないよう、OTLP/gRPCを14317、Grafanaを14300で公開しました。

```sh
docker run -d --name chainguard-traces-lgtm \
  -p 127.0.0.1:14300:3000 -p 127.0.0.1:14317:4317 \
  grafana/otel-lgtm:0.37.0
```

次のコマンドで状態が`healthy`になったことを確認してから、ビルドへ進みます。

```sh
docker inspect --format '{{.State.Health.Status}}' chainguard-traces-lgtm
```

[本](https://zenn.dev/ymotongpoo/books/chainguard-image-toolchain)と同様に、GNU Helloの設定を用意します。melangeでWolfiのビルド環境を作り、生成したローカルのAPKをapkoに渡します。

:::details hello.yamlとapko.yaml
`hello.yaml`は、ソースの取得からコンパイル、インストールまでを定義します。

```yaml
package:
  name: hello
  version: 2.12
  epoch: 0
  description: "the GNU hello world program"
  copyright:
    - license: GPL-3.0-or-later

environment:
  contents:
    keyring:
      - https://packages.wolfi.dev/os/wolfi-signing.rsa.pub
    repositories:
      - https://packages.wolfi.dev/os
    packages:
      - wolfi-base
      - build-base
      - ca-certificates-bundle

pipeline:
  - uses: fetch
    with:
      uri: https://ftp.gnu.org/gnu/hello/hello-${{package.version}}.tar.gz
      expected-sha256: cf04af86dc085268c5f4470fbae49b18afbc221b78096aab842d934a76bad0ab
  - uses: autoconf/configure
  - uses: autoconf/make
  - uses: autoconf/make-install
  - uses: strip
```

`apko.yaml`は、生成した`hello`をローカルのAPKリポジトリから読み込みます。

```yaml
contents:
  keyring:
    - https://packages.wolfi.dev/os/wolfi-signing.rsa.pub
    - melange.rsa.pub
  repositories:
    - https://packages.wolfi.dev/os
    - "@local ./packages"
  packages:
    - wolfi-baselayout
    - hello@local

entrypoint:
  command: /usr/bin/hello

accounts:
  run-as: 65532

archs:
  - x86_64
```
:::

実行には、digestで固定したmelangeの公式イメージを使いました。作業用のディレクトリを用意し、APK署名用の鍵を生成します。

```sh
cg_runtime=cgr.dev/chainguard/melange@sha256:4bcc9f5ce0a97e333b9440473952126dd71e9f50b7800b92124c3a98496be7d8
mkdir -p .work/build .work/source
cp hello.yaml apko.yaml .work/build/
docker run --rm -v "$PWD/.work/build:/work" "$cg_runtime" keygen
```

続いて、実験用のmelangeをマウントしてビルドします。`OTEL_RESOURCE_ATTRIBUTES`は、トレースを検索するときに使うリソース属性[^resource]を追加するための設定です。

```sh
docker run --privileged --rm --network host \
  -v "$PWD/.work/build:/work" -v "$PWD/.work/source:/source:ro" \
  -v "$PWD/.work/melange-otel:/experiment/melange:ro" \
  --entrypoint /experiment/melange \
  -e OTEL_TRACES_EXPORTER=otlp \
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14317 \
  -e OTEL_SERVICE_NAME=melange \
  -e OTEL_RESOURCE_ATTRIBUTES=experiment.case=melange-first,service.version=0.63.2 \
  "$cg_runtime" build hello.yaml --arch x86_64 --signing-key melange.rsa \
  --source-dir /source --cache-dir /work/cache/melange-sources \
  --apk-cache-dir /work/cache/melange-apk
```

[^resource]: リソース属性は、そのスパンを出したサービスなどを識別する情報です。今回は`service.name`でツールを、独自属性`experiment.case`で初回と再実行を区別します。

`--privileged`は、melangeがコンテナ内にビルド用のサンドボックスを用意するために指定しています。`--network host`は、Linuxのビルド用コンテナからホストのOTLPポートへ接続するためです[^network]。ソースを配置する`/source`は空の別ディレクトリとし、署名鍵や出力済みAPKをビルド環境にコピーしない構成にしました。

[^network]: Docker Desktopでは、hostネットワークの利用条件や設定が異なります。この記事の手順では検証していません。

APKができたら、実験用apkoで最終イメージを作ります。同じ公式イメージにapkoのバイナリをマウントするので、ここでも実行されるのは独自にビルドしたCLIです。

```sh
docker run --rm --network host \
  -v "$PWD/.work/build:/work" \
  -v "$PWD/.work/apko-otel:/experiment/apko:ro" \
  --entrypoint /experiment/apko \
  -e OTEL_TRACES_EXPORTER=otlp \
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14317 \
  -e OTEL_SERVICE_NAME=apko \
  -e OTEL_RESOURCE_ATTRIBUTES=experiment.case=apko-first,service.version=1.4.13 \
  "$cg_runtime" build apko.yaml hello:otel-experiment hello.tar \
  --cache-dir /work/cache/apko
```

生成したイメージを読み込み、Helloが動くことも確かめました。

```sh
docker load -i .work/build/hello.tar
docker run --rm hello:otel-experiment-amd64
# Hello, world!
```

## 取得できたトレース

Tempoから取得したmelangeのトレースは546スパン、apkoは130スパンでした。melange側の親子関係を、主要な処理に絞って示すと次のようになります。括弧内は計装ライブラリの名前です。

```text
melange build                  41.819秒  今回追加した親スパン
└─ BuildCmd                    (melange)
   └─ BuildPackage             (melange)
      ├─ buildGuest            23.217秒  (melange)
      │  ├─ New                         (apko)
      │  ├─ BuildImage         15.350秒  (apko)
      │  ├─ ImageLayoutToLayer  4.122秒  (apko)
      │  └─ bubblewrap.LoadImage        (melange)
      ├─ bubblewrap.StartPod           (melange)
      └─ EmitPackage                   (melange)
```

全体の約42秒のうち、約23秒をビルド環境の準備に使っていました。その中のapkoの`BuildImage`から、APKパッケージのインストールなどにかかった時間をたどれます。

これに対し、最終イメージを作るapkoのルートは、別の`apko build`です。こちらには、イメージのレイヤーを作る処理や、SBOM[^sbom]の生成が含まれていました。melangeで作ったAPKを入力として使っていても、その事実だけで2つのCLIのトレースがつながるわけではありません。

[^sbom]: SBOM（Software Bill of Materials）は、ソフトウェアに含まれる部品を記録した一覧です。apkoは、インストールしたパッケージなどの情報からイメージのSBOMを作ります。

GrafanaのURLは`http://127.0.0.1:14300`です。ExploreでTempoを選び、たとえば次のTraceQLでmelangeの初回ビルドを検索します。今回のスパン数や親子関係は、TempoのHTTP APIから取得したデータで確認しました。

```traceql
{ resource.service.name = "melange" && resource.experiment.case = "melange-first" }
```

存在しない設定ファイルを渡す失敗ケースでも、両CLIは終了コード1を返し、親スパンがTempoへ届きました。親のエラーステータスは、今回の補助コードがCLIの戻り値をもとに設定したものです。内部の既存スパンすべてにエラーが付くことを確かめたわけではありません。

## 再実行で変わるスパン

キャッシュを残して再実行すると、内部で生成されるスパンの数も変わりました。各CLIを初回と再実行で1回ずつ動かした観測値です。再実行では、先ほどのコマンドの`experiment.case`を`melange-repeat`と`apko-repeat`に変えています。

| ツール | 実行 | 全体の所要時間 | スパン数 |
| --- | --- | ---: | ---: |
| melange | 初回 | 41.819秒 | 546 |
| melange | 再実行 | 26.071秒 | 254 |
| apko | 初回 | 3.807秒 | 130 |
| apko | 再実行 | 1.731秒 | 86 |

melangeでは、パッケージ取得を表す`fetchPackage`が48件から0件に減りました。一方、インストールを表す`installPackage`は48件のままです。キャッシュを残した再実行でも、ビルド環境へのインストールは行われていました。

melangeの`buildGuest`も約23秒から約9秒に変わっています。同じ設定ファイルのビルドでも、内部で実行された処理が初回と同じではないことを観察できます。

この表だけから、キャッシュによる速度改善率は判断できません。実行回数が少なく、同じホストのほかの処理や、再実行ケースの一部を並行して動かした影響もあります。継続的に調べるには、実行ケースやソースのコミットを属性に付け、条件を揃えた複数回の比較が必要です。

## 個別に見えない工程

melange v0.63.2の既存計装では、ビルドのすべての工程が分かれるわけではありません。今回のトレースには、`autoconf/configure`や`autoconf/make`の実行をそれぞれ表すスパンがありませんでした。[pipelineを実行する処理](https://github.com/chainguard-dev/melange/blob/402004649f817966440662612d0ea7302b95a858/pkg/build/pipeline.go#L214)にも、ステップごとにスパンを開始する実装はありません。

そのため、`BuildPackage`の中で子スパンがない時間を、すべてコンパイル時間と解釈することはできません。ソース取得や`configure`を含め、個別には計装されていない処理が残っているからです。「ビルド環境の準備が遅い」までは調べられても、「`make`のこの部分が遅い」には、別の計装が必要になります。

また、今回は両CLIの実行ごとに新しい親スパンを作っています。melangeとapkoを1本のトレースにまとめるには、共通の親を作り、CLIにコンテキストを伝える仕組みが必要です。今回の補助コードには、その処理を入れていません。

## おわりに

今回の実験で、melangeとapkoには、ビルド環境の準備やAPKのインストールを調べるための計装がすでにあると確認できました。標準CLIからOTLPで送信できれば、利用者がソースを改変せずに、この計装を使えます。

そこで、CLIからのOTLP出力を[melangeのissue](https://github.com/chainguard-dev/melange/issues/2724)と[apkoのissue](https://github.com/chainguard-dev/apko/issues/2609)で提案しました。有効化の設定方法や既存機能との関係を相談し、まずはメンテナーの反応を待ちます。この記事のコードは、提案の根拠にした実験用の実装です。
