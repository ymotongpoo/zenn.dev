# melangeとapkoのビルドトレース検証

本のGNU Helloの例を使い、melangeとapkoの既存スパンをGrafana Tempoへ送りました。melangeはAPKパッケージ、apkoはOCIイメージを作るツールです。2026年10月27日に、UbuntuのDocker環境で実行しました。

検証対象はCLIの実験用ビルドです。標準CLIに環境変数を渡すだけでOTLP送信できる手順ではありません。公開済みの本の本文は変更していません。

## 実験用ビルドの変更

[melange v0.63.2](https://github.com/chainguard-dev/melange/tree/v0.63.2)と[apko v1.4.13](https://github.com/chainguard-dev/apko/tree/v1.4.13)のソースを固定しました。[prepare.py](prepare.py)はアーカイブのSHA-256を確認し、各CLIのエントリーポイントを変更します。

Goの依存関係では、OTLP/gRPC exporterとSDKをv1.47.0に揃えます。

[telemetry.go](telemetry.go)でSDKとexporterを初期化し、CLI全体を表す親スパンを1つ追加しました。ビルド内部の計装は既存のままです。成功時も失敗時も、CLIから戻る際に親スパンを終了し、SDKの`Shutdown`で送信します。実験用のサンプリングは全件取得です。

melangeの標準の`--trace`は、OTelの`stdouttrace` exporterでファイルに出力します。このファイルのJSONとOTLP JSONは別の形式です。また、`--trace`はグローバルなTracerProviderを置き換えるため、実験用のOTLP出力とは併用しません。[標準の出力処理](https://github.com/chainguard-dev/melange/blob/402004649f817966440662612d0ea7302b95a858/pkg/cli/build.go)で確認できます。

melangeとapkoをそれぞれ独立したトレースとして記録します。外部の`traceparent`を読む処理は追加していません。melange内部で使われるapkoのライブラリはv1.4.11です。別途起動するapko CLIのv1.4.13とは区別します。

## 再現手順

Go 1.27、Python 3.12以降、Docker EngineとComposeが必要です。Go 1.26環境でも、Goの自動ツールチェーン取得が有効ならビルド時に1.27を取得します。確認時に使ったGoは1.27.0です。コマンドはこのディレクトリから実行します。

まず、標準melangeのファイル出力を取得し、実験用バイナリをビルドします。ソース、バイナリ、署名鍵、生成物と生の検証ログの保存先は、Gitで無視する`.work/`です。Wolfiのパッケージ索引とパッケージのバージョンは固定していないため、再実行時の依存関係やスパン数は変わります。

```sh
bash native.sh
bash build.sh
```

検証専用のotel-lgtmを起動します。既存のスタックとポートを分け、ホストのループバックアドレスに公開します。

```sh
docker compose -p chainguard-build-traces up -d
curl -fsS http://127.0.0.1:14320/ready
curl -fsS http://127.0.0.1:14300/api/health
```

`ready`とGrafanaの正常応答を確認したら、HelloのAPKとイメージを順にビルドします。実行環境はdigestで固定したmelangeの公式イメージです。実験用バイナリを読み取り専用でマウントし、melangeではビルド環境のために`--privileged`を指定します。

```sh
bash run.sh melange melange-first
python3 summarize.py melange-first
bash run.sh apko apko-first
python3 summarize.py apko-first
```

`run.sh`は次の環境変数を渡します。通信はOTLP/gRPCです。サービス名と実行ケースをリソース属性に付け、トレースIDを各CLIのログと`.work/results/<case>.json`に残します。

```sh
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14317
OTEL_SERVICE_NAME=melange  # apkoではapko
OTEL_RESOURCE_ATTRIBUTES=experiment.case=melange-first,service.version=0.63.2
```

ビルド用コンテナはLinuxのhostネットワークを使い、同じホストのOTLPポートへ送ります。Docker Desktopではネットワーク設定の調整が必要です。この構成では検証していません。

続けてキャッシュを残したまま同じビルドを再実行します。melangeのソースとAPKのキャッシュ、apkoのAPKのキャッシュは、それぞれ`.work/build/`配下に保存しています。

```sh
bash run.sh melange melange-repeat
python3 summarize.py melange-repeat
bash run.sh apko apko-repeat
python3 summarize.py apko-repeat
```

最後にイメージの動作と、失敗時のトレース送信を確認します。

```sh
docker load -i .work/build/hello.tar
docker run --rm hello:otel-experiment-amd64 | tee .work/hello-output.txt
python3 probe_failure.py
python3 summarize.py melange-failure
python3 summarize.py apko-failure
python3 verify.py
```

[verify.py](verify.py)は、各ケースの終了コード、親スパンの存在、所要時間の符号、リソース属性、Trace IDの独立性を検査します。失敗ケースでは、追加した親スパンのエラーステータスも検査対象です。検査に成功すると、共有用の[results.json](results.json)を生成します。

標準CLIのファイル出力は`.work/native/native-trace.json`、Tempoの生の応答は`.work/results/<case>.tempo.json`に保存します。

## 観測結果

標準melangeのファイル出力では546スパンを取得しました。計装ライブラリごとの内訳は、melangeが10、apkoが9、APK操作を担うgo-apkが527です。実験用melangeでは標準のファイル出力用の親スパンを作らず、実験用の親スパンを1つ作ります。

| ケース | 親スパンの所要時間 | スパン数 | Trace ID |
| --- | ---: | ---: | --- |
| melange初回 | 41.819秒 | 546 | `df03ef6dd9ba8b240e6bde81b107fef1` |
| melange再実行 | 26.071秒 | 254 | `3f0cb763357f5bd41d289078afe07df3` |
| apko初回 | 3.807秒 | 130 | `7ab9f824e88c4740e8960781bb448322` |
| apko再実行 | 1.731秒 | 86 | `cd4464f6be5f7906ec60dff2f2da30e5` |

各ケース1回ずつの観測値です。同じホストではほかの処理も動作しており、再実行ケースの一部は並行して実行しました。この表を速度改善のベンチマークには使いません。初回と再実行で、キャッシュに関する内部スパンがどう変わるかを調べるための記録です。

初回のmelangeでは、`BuildPackage`が41.672秒、ビルド環境を作る`buildGuest`が23.217秒でした。その内部でapkoの`BuildImage`が15.350秒を占めています。melangeのトレース内にあるapkoのスパンは、ビルド環境の準備を表します。完成したHelloのAPKから最終イメージを作るapko CLIは、別のトレースです。

両CLIの成功ケースと失敗ケースを合わせた6トレースで、親スパンの欠落と負の所要時間はありませんでした。存在しないYAMLを渡した失敗ケースでも、終了コード1と親スパンの`STATUS_CODE_ERROR`を確認しています。Helloのイメージは`Hello, world!`を出力しました。検証にはTempoのHTTP APIを使い、Grafanaのブラウザー画面は未検証です。

## 既存計装の粒度

このバージョンのmelangeでは、`configure`や`make`をそれぞれ表すスパンを確認できませんでした。[pipelineの実行処理](https://github.com/chainguard-dev/melange/blob/402004649f817966440662612d0ea7302b95a858/pkg/build/pipeline.go)にも、ステップごとにスパンを開始する処理はありません。`BuildPackage`内にある子スパンのない時間を、すべてコンパイル時間と解釈することはできません。

工程ごとの遅延を特定するためには、pipelineの実行処理へスパンを追加する検証が必要です。外部のmelangeとapkoを1本のトレースにする場合も、共通の親スパンとプロセス間のコンテキスト伝搬を別途実装します。

## トレースの確認と終了

Grafanaは<http://127.0.0.1:14300>です。ExploreでTempoを選び、表のTrace IDで検索できます。TraceQLでは、たとえば次の条件を使います。

```traceql
{ resource.service.name = "melange" && resource.experiment.case = "melange-first" }
```

検証用スタックを停止する場合は、次のコマンドを使います。Composeには永続ボリュームを設定していないため、コンテナを削除するとTempo内のトレースも消えます。保存したJSONと生成物は`.work/`に残る構成です。

```sh
docker compose -p chainguard-build-traces down
```
