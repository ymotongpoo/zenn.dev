---
title: "リファレンス実装で動かす"
---

[otel-platform-blueprint](https://github.com/ymotongpoo/otel-platform-blueprint)は、SDKディストリビューション、ゼロコード計装、Collector、OpAMP、Weaverを組み合わせたリファレンス実装です。本章の挙動と数値は、次の環境で測定しました。

| 項目 | 測定時の値 |
|---|---|
| 測定日 | 2026年9月10日 |
| OS | Linux（x86_64、4コア） |
| Docker Engine | 29.0.0 |
| Go | 1.26.0 |
| Collector | v0.159.0 |
| opentelemetry-go | v1.45.0 |
| Weaver | v0.25.1 |
| OpAMP Supervisor | 0.159.0 |
| otelc | v1.1.0 |

詳細はリポジトリの `docs/measurements.md` に記録しています。他章が示す最新版とは差がありますが、数値を再現できる組み合わせを残すため、測定時のバージョンをそのまま記載します。同じシナリオを2026年8月25日にmacOSでも実施しており、結果が分かれた箇所は本章で明示します。

本章で行う検証と、それぞれが確かめている設計は次のとおりです。

![リファレンス実装で行う検証の流れ](/images/20260926-blueprint-verification.png)
*図1　上から順に実行します。箱の色は確かめている柱を表し、1つ目が橙、2つ目が黄、3つ目が紫、AIワークロードが緑です。ゼロコード計装は1つ目の柱に属しますが、環境を起動してから試すほうが差分を確認しやすいため、後半に置いています。*

## リポジトリの全体構成

各ディレクトリは、本書の章に対応します。

```text
otel-platform-blueprint/
├── sdk/              # 社内SDKディストリビューション（2章）
│   ├── otelinit/     #   Setup一発の初期化
│   └── semconv/      #   Weaverが生成した社内属性の定数
├── autoinstrument/   # ゼロコード計装（3章）。otelcのビルド例
├── collector/        # Collectorのビルドと設定（4章）
│   ├── builder/      #   OCBのmanifest.yaml
│   └── configs/      #   agent用とgateway用の事前定義設定
├── opamp/            # フリート管理（5章）
│   ├── server/       #   opamp-goベースの最小OpAMPサーバー（学習用）
│   ├── supervisor/   #   supervisor.yamlとagent基底設定
│   └── remote-configs/ # フリートへ配るリモート設定
├── registry/         # セマンティック規約レジストリ（6章）
│   ├── model/        #   manifest.yamlと社内属性の定義YAML
│   ├── policies/     #   Regoポリシー
│   └── templates/    #   Go定数生成テンプレート
├── services/         # デモ用のGoサービス群
│   ├── frontend/     #   ディストリビューション組み込み済み
│   ├── backend/      #   同上。otelslogでログも出す
│   ├── uninstrumented/ # 計装コードなし（ゼロコード計装のデモ用）
│   └── ai-app/       #   LLM呼び出しを含むエージェント風アプリ（7章）
├── ai-ops/           # AIにテレメトリーを読ませる構成例（8章）
├── deploy/           # docker composeとバックエンド設定
└── docs/             # 測定記録
```

![リファレンス実装の全体構成](/images/20260926-blueprint-overview.png)
*図2　実線はテレメトリーの流れ、点線は設定と生成物の配布先を表します。1章の図2に実装上のコンポーネント名を加えています。*

## 検証環境の起動

検証用のバックエンドにはOSSのGrafanaスタックを使います。トレースはTempo、メトリクスはMimir、ログはLokiへ保存し、GrafanaのUIから確認します。計装からOTLP送信までの構成は特定のバックエンドに依存しませんが、保存後の検索とAIエージェントからのアクセスはバックエンド固有です。この実装では、手元で起動できるOSSの組み合わせとしてGrafanaスタックを選びました。

```console
$ git clone https://github.com/ymotongpoo/otel-platform-blueprint
$ cd otel-platform-blueprint/deploy
$ docker compose build gateway
$ docker compose up -d --build
```

`gateway` を先にビルドします。Supervisor管理のエージェントイメージは、`gateway` のビルド成果物である `otelcol-internal:dev` をベースイメージとして参照しますが、composeはサービス間のビルド順序を保証しません。一括ビルドだけでは、エージェントのビルドが `pull access denied` で失敗することがあります。

初回は、OCBによるCollectorとGoサービスのビルドを実行します。4コアの環境では10分ほどかかりました。Grafanaスタック、OCBでビルドした社内Collector（gatewayとSupervisor管理のエージェント）、OpAMPサーバー、4つのデモサービスからなる10コンテナが起動します。

ポートの衝突とTempoの起動待ちでつまずくことがあります。対処はリポジトリのREADMEにまとめてあります。

## 計装から保存までの検証

計装から保存までの経路を確認するため、ディストリビューションを組み込んだfrontendへリクエストを送ります。

```console
$ for i in $(seq 30); do curl -s localhost:8080/checkout > /dev/null; done
```

30リクエストのうち、Tempoへ保存されたのは7トレースでした。ゲートウェイのテイルサンプリングは、エラーをすべて残し、正常系の10%を残す設定です。判定は確率的なので、保存されるトレース数は同じ条件でも回ごとに変わります。別の回では6トレース、macOSでの初回は2トレースでした。送信したリクエスト数と保存されたトレース数は一致しません。保存されたトレースから、次の項目を確認できます。

- frontendとbackendのスパンが1本のトレースにつながっている。アプリケーション側の計装コードは `otelinit.Setup(ctx)` だけで、プロパゲーターの設定はどこにも書かれていない（2章）
- リソース属性に、エージェントのリソース detectionが付けた `host.name` と、標準環境変数 `OTEL_RESOURCE_ATTRIBUTES` 経由の `deployment.environment.name` や `team.name` が入っている（2章、4章）
- スパンに `com.example.delivery.id` が付いていて、ソースコードではWeaver生成の定数で書かれている。`sdk/semconv/` に手書きの属性名文字列はない（6章）

ゲートウェイの属性処理も確認しました。frontendは意図的に `user.email` をスパンへ付けますが、Tempoに保存されたトレースにはこの属性がなく、`com.example.delivery.id` は残っています。Transformプロセッサーが `user.email` を転送中に削除しました。

メトリクスとログも同じ経路で送ります。otelhttp由来の `http_server_request_duration` はMimirへ、backendがotelslogで出したログはLokiへ届きました。ログのエントリには `trace_id` と `span_id` が付き、トレースから関連するログを検索できます。

## レジストリの検査と生成

6章のガバナンスのループを回します。

```console
$ ./registry/weaver.sh check
$ ./registry/weaver.sh generate
```

checkは、公式semconvへの依存をGit URLで解決して約3秒で成功しました。違反を検出できることも確認します。`com.example.` 以外の名前空間として `myteam.custom.flag` を定義すると、checkはRegoポリシーの `internal_namespace_only` violationで失敗しました。この定義を削除すると成功します。generateは `sdk/semconv/semconv.go` を生成し、`com.example.delivery.id` を `ComExampleDeliveryId` 定数に変換しました。生成結果はコミット済みのファイルと一致し、差分は出ません。CIはこの差分の有無を検査します。

実際のテレメトリーはlive-checkで検査します。live-checkをOTLPの受信口として起動し、テレメトリーを生成する公式のテストツール[telemetrygen](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/cmd/telemetrygen)から、レジストリにない属性を含むスパンを送りました。`myteam.rogue.attr` はviolationとして報告され、`com.example.delivery.id` はviolationになりませんでした。ただし、`com.example.delivery.id` には安定度がdevelopmentであるという改善提案が付きます。

live-checkをコンテナで動かす場合は、リッスンアドレスとポートを明示します。測定した際は、指定なしで起動したところコンテナ外から送ったテレメトリーが届かず、検査対象が0件のまま終了しました。`registry/weaver.sh` では `--otlp-grpc-address 0.0.0.0 --otlp-grpc-port 4317` を指定して解決しています。ただしv0.25.1のデフォルト値はこの指定と同じ `0.0.0.0:4317` なので、0件になった原因はデフォルトのリッスンアドレスではありません。ポート公開の状態や、デフォルトで10秒の無通信タイムアウトが関わった可能性があり、原因は特定していません。なお、v0.26.0でデフォルトのリッスンアドレスは `127.0.0.1` に変更されたため、このバージョン以降はコンテナで動かすときに明示指定が必要になります。

一方、依存先である公式レジストリの `service.name` や `network.peer.address` などもviolationになりました。live-checkが依存先を解決する範囲は追加調査が必要です。CIの合否に使う場合は、検出された違反を種類に応じて扱う必要があります。

## フリートに設定を配る

エージェントはSupervisorから起動し、`opamp/remote-configs/remote.yaml` の変更をOpAMPサーバーが接続中のSupervisorへ配布します。正常な設定、起動できない設定、起動できるがテレメトリーを止める設定を試しました。

スパンへ属性を追加するプロセッサーをリモート設定へ書いて保存すると、2秒以内にAPPLIEDになり、以降のスパンに新しい `fleet.config.version` が付きました。Collectorは再デプロイしていません。この実装のOpAMPサーバーは設定ファイルを2秒間隔でポーリングするため、検知の遅延はその間隔で決まります。

存在しないプロセッサーを参照する設定を配ると、Supervisorは約1秒で起動失敗を検知し、FAILEDを報告しました。しかし、サーバーが適用済みハッシュと配布中のハッシュの違いだけを見て再送すると、FAILEDの後も同じ設定を送り続けます。そこで、FAILEDと報告されたハッシュを再送しない制御を `opamp/server/main.go` に実装しました。

Supervisor側でも、`automatic_config_rollback` を有効にしていたにもかかわらず、0.159.0では前の設定へ自己復旧しませんでした。起動に失敗した設定を「最後に動作した設定」として `last_working_remote_config.dat` へ永続化する挙動を、macOSとLinuxの両方で確認しています。FAILEDのまま30秒観測しても状態は変わりませんでした。サーバーから修正済みの設定を配り直すと復旧しました。

filterで全スパンをdropする設定は起動に成功し、ステータスもAPPLIEDかつhealthyのままでした。50リクエストを送ってもTempoへ到達したトレースは0件で、ロールバックも発生しません。正常な設定を再配布すると復旧し、25リクエストから6トレースが到達しました。

この測定では、自動ロールバックだけでフリートを保護できませんでした。カナリア、テレメトリー到達の監視、FAILEDになった設定の再送防止、修正版の再配布を組み合わせる必要があります。

## ゼロコード計装を試す

3章のコンパイル時計装を、計装コードを一切含まない `services/uninstrumented` で試します。

```console
$ cd autoinstrument/otelc
$ go tool otelc go build -o legacy-instrumented .
$ docker compose -f ../../deploy/docker-compose.yaml stop uninstrumented
$ OTEL_SERVICE_NAME=legacy-otelc OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 ./legacy-instrumented
```

`otelc go build` は、ビルドの間だけ計装の構成を生成します。生成されたバイナリは26,022,431バイトで、計装ランタイムを含みます。起動ログには「trace provider initialized with auto-export」「runtime metrics enabled」と出力され、100リクエストから、テイルサンプリングを通過した11トレースがTempoへ届きました。

構成をリポジトリへ固定する `otelc pin` は使いません。pinが書き出す `go.mod` の `replace` は作業ディレクトリ配下の絶対パスを指すため、**生成物をコミットすると別のマシンで失敗します**（`package ... is not part of a module`）。最初の測定をmacOSで行い、その生成物がコミットされていたため、Linuxでの再測定はここで止まりました。upstreamも3章の脚注のとおり、pinの生成物をコミットする使い方を未対応としています。CIでは、素の `go.mod` から `otelc go build` が通ることを検査します。

`services/uninstrumented` は `:8082` で待ち受けます。composeの同名サービスと衝突するため、手元で動かす前に停止します。

設定にはSDKディストリビューションと同じ標準の `OTEL_*` 環境変数を使いました。Kubernetes OperatorによるInstrumentation CRDの注入は、このリポジトリでは検証していません。

## AIにテレメトリーを読ませる

`services/ai-app` は、LLM呼び出しとツール実行をスタブで再現するデモアプリケーションです。`/ask` へリクエストを送り、Tempoでトレースを開くと、次の構造を確認できます。

```text
GET /ask
└── invoke_agent support-agent      gen_ai.agent.name, gen_ai.conversation.id
    ├── chat stub-model-1           gen_ai.request.model, gen_ai.usage.input_tokens ...
    ├── execute_tool search_orders   gen_ai.tool.name
    │   └── HTTP GET
    │       └── GET /inventory     （backendの通常のスパン）
    └── chat stub-model-1
```

`invoke_agent` の子としてLLM呼び出しとツール実行が並び、ツールから呼び出した社内APIの分散トレースがその下へつながっています。トークン使用量はリクエストごとに変わるスタブ値です。ai-appのトレースもテイルサンプリングの対象なので、30リクエストで3トレースの到達でした。

`ai-ops/` には、レジストリを読むregistry MCPと、実データを読むtelemetry MCPの構成例があります。registry MCPは `weaver registry mcp` を標準入出力で起動し、telemetry MCPはGrafanaスタック向けのMCPサーバーを使います。

MCP経由でAIエージェントに調査させる一連の実験は、このリポジトリでは行っていません。構成例を試す場合も、レジストリと実データに別々の権限を設定します。

## 章とディレクトリの対応

| 章 | 主題 | 対応ディレクトリ |
|---|---|---|
| 2章 | SDKディストリビューション | sdk/ |
| 3章 | ゼロコード計装 | autoinstrument/、services/uninstrumented/ |
| 4章 | Collectorのビルドと設定 | collector/、deploy/ |
| 5章 | フリート管理 | opamp/ |
| 6章 | レジストリとWeaver | registry/、sdk/semconv/ |
| 7章 | AIワークロードの観測 | services/ai-app/ |
| 8章 | AIによる読み取り | ai-ops/ |

`.github/workflows/` には、レジストリ変更時のcheckとdiff、生成コードが最新であることの検査、OCBビルド、`validate` による設定検証、素の `go.mod` からの `otelc go build` を実装しています。

## 段階導入のチェックリスト

リファレンス実装は各章の部品をまとめて起動しますが、実際の組織では段階的に導入できます。本書では次の順序を推奨します。

1. エージェント Collectorを立て、既存の計装からのテレメトリーをCollector経由に変える。後続の共通処理はこの経路へ追加する
2. SDKディストリビューションを作り、新規サービスから採用を始める。既存サービスは更新のタイミングで移行する
3. ゼロコード計装で未計装サービスの最低保証を作る。共通CIを変更できるならGoはotelcから始める
4. ゲートウェイ層を立て、サンプリングと属性統制を集約する
5. レジストリを定義し、まず新しい社内属性の追加だけをレジストリ経由に限定する。生成とlive-checkはその後で足す
6. フリートが大きくなり設定変更が頻繁になったら、OpAMPを導入する
7. AI拡張はgen_ai属性の取り込みから。エージェントへのアクセス提供はread権限から始める

各段階で導入した配布物と検査は、後続の段階を待たずに利用できます。
