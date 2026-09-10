---
title: "リファレンス実装で動かす"
---

[otel-platform-blueprint](https://github.com/ymotongpoo/otel-platform-blueprint)は、SDKディストリビューション、ゼロコード計装、Collector、OpAMP、Weaverを組み合わせたリファレンス実装です。本章の挙動と数値は、2026年9月10日にLinux（x86_64、4コア）、Docker Engine 29.0.0、Go 1.26.0の環境で実測しました。Collector v0.159.0、opentelemetry-go v1.45.0、Weaver v0.25.1、OpAMP Supervisor 0.159.0、otelc v1.1.0を使い、詳細をリポジトリの `docs/measurements.md` に記録しています。同じシナリオを2026年8月25日にmacOSでも実施しており、結果が分かれた箇所は本章で明示します。

## リポジトリの全体構成

各ディレクトリは、本書の章に対応します。

```text
otel-platform-blueprint/
├── sdk/              # 社内SDKディストリビューション（10章）
│   ├── otelinit/     #   Setup一発の初期化
│   └── semconv/      #   Weaverが生成した社内属性の定数
├── autoinstrument/   # ゼロコード計装（20章）。otelcのビルド例
├── collector/        # Collectorのビルドと設定（30章）
│   ├── builder/      #   OCBのmanifest.yaml
│   └── configs/      #   agent用とgateway用の事前定義設定
├── opamp/            # フリート管理（40章）
│   ├── server/       #   opamp-goベースの最小OpAMPサーバー（学習用）
│   ├── supervisor/   #   supervisor.yamlとagent基底設定
│   └── remote-configs/ # フリートへ配るリモート設定
├── registry/         # セマンティック規約レジストリ（50章）
│   ├── model/        #   manifest.yamlと社内属性の定義YAML
│   ├── policies/     #   Regoポリシー
│   └── templates/    #   Go定数生成テンプレート
├── services/         # デモ用のGoサービス群
│   ├── frontend/     #   ディストリビューション組み込み済み
│   ├── backend/      #   同上。otelslogでログも出す
│   ├── uninstrumented/ # 計装コードなし（ゼロコード計装のデモ用）
│   └── ai-app/       #   LLM呼び出しを含むエージェント風アプリ（60章）
├── ai-ops/           # AIにテレメトリーを読ませる構成例（70章）
├── deploy/           # docker composeとバックエンド設定
└── docs/             # 実測記録
```

![リファレンス実装の全体構成](/images/20260926-blueprint-overview.png)
*図1　実線はテレメトリーの流れ、点線は設定と生成物の配布先を表します。00章の図2に実装上のコンポーネント名を加えています。*

## 検証環境の起動

検証用のバックエンドにはOSSのGrafanaスタックを使います。トレースはTempo、メトリクスはMimir、ログはLokiへ保存し、GrafanaのUIから確認します。計装からOTLP送信までの構成は特定のバックエンドに依存しませんが、保存後の検索とAIエージェントからのアクセスはバックエンド固有です。この実装では、手元で起動できるOSSの組み合わせとしてGrafanaスタックを選びました。

```console
$ git clone https://github.com/ymotongpoo/otel-platform-blueprint
$ cd otel-platform-blueprint/deploy
$ docker compose build gateway
$ docker compose up -d --build
```

`gateway` を先にビルドします。Supervisor管理のagentイメージは、`gateway` のビルド成果物である `otelcol-internal:dev` をベースイメージとして参照しますが、composeはサービス間のビルド順序を保証しません。一括ビルドだけでは、agentのビルドが `pull access denied` で失敗することがあります。

初回は、OCBによるCollectorとGoサービスのビルドを実行します。4コアの環境では10分ほどかかりました。Grafanaスタック、OCBでビルドした社内Collector（gatewayとSupervisor管理のagent）、OpAMPサーバー、四つのデモサービスからなる10コンテナが起動します。

手元で別のCollectorやGrafana Alloyが動いている場合、agentのポート公開が `address already in use` で失敗します。実測環境でもこれが起きたため、`deploy/docker-compose.override.yaml` で公開ポートをずらしました。

Tempoは起動後15秒から20秒ほど `/ready` を返さず、その間に届いたテレメトリーを保存しません。実測でも、起動直後に送ったトレースは保存されませんでした。Tempoの準備完了を確認してから、検証用のリクエストを送ります。

## 計装から保存までの検証

計装から保存までの経路を確認するため、ディストリビューションを組み込んだfrontendへリクエストを送ります。

```console
$ for i in $(seq 30); do curl -s localhost:8080/checkout > /dev/null; done
```

30リクエストのうち、Tempoへ保存されたのは7トレースでした。gatewayのtail samplingは、エラーをすべて残し、正常系の10%を残す設定です。判定は確率的なので、保存されるトレース数は同じ条件でも回ごとに変わります。別の回では6トレース、macOSでの初回は2トレースでした。送信したリクエスト数と保存されたトレース数は一致しません。保存されたトレースから、次の項目を確認できます。

- frontendとbackendのスパンが1本のトレースにつながっている。アプリケーション側の計装コードは `otelinit.Setup(ctx)` だけで、propagatorの設定はどこにも書かれていない（10章）
- resource属性に、agentのresource detectionが付けた `host.name` と、標準環境変数 `OTEL_RESOURCE_ATTRIBUTES` 経由の `deployment.environment.name` や `team.name` が入っている（10章、30章）
- スパンに `com.example.delivery.id` が付いていて、ソースコードではWeaver生成の定数で書かれている。`sdk/semconv/` に手書きの属性名文字列はない（50章）

gatewayの属性処理も確認しました。frontendは意図的に `user.email` をスパンへ付けますが、Tempoに保存されたトレースにはこの属性がなく、`com.example.delivery.id` は残っています。transform processorが `user.email` を転送中に削除しました。

メトリクスとログも同じ経路で送ります。otelhttp由来の `http_server_request_duration` はMimirへ、backendがotelslogで出したログはLokiへ届きました。ログのエントリには `trace_id` と `span_id` が付き、トレースから関連するログを検索できます。

## レジストリの検査と生成

50章のガバナンスのループを回します。

```console
$ ./registry/weaver.sh check
$ ./registry/weaver.sh generate
```

checkは、公式semconvへの依存をGit URLで解決して約3秒で成功しました。違反を検出できることも確認します。`com.example.` 以外の名前空間として `myteam.custom.flag` を定義すると、checkはRegoポリシーの `internal_namespace_only` violationで失敗しました。この定義を削除すると成功します。generateは `sdk/semconv/semconv.go` を生成し、`com.example.delivery.id` を `ComExampleDeliveryId` 定数に変換しました。生成結果はコミット済みのファイルと一致し、差分は出ません。CIはこの差分の有無を検査します。

実測データはlive-checkで検査します。live-checkをOTLPの受信口として起動し、テレメトリーを生成する公式のテストツールtelemetrygenから、レジストリにない属性を含むスパンを送りました。`myteam.rogue.attr` はviolationとして報告され、`com.example.delivery.id` はviolationになりませんでした。ただし、`com.example.delivery.id` にはstabilityがdevelopmentであるという改善提案が付きます。

live-checkをコンテナで動かす場合は、リスンアドレスを明示します。既定のままではコンテナ外から送ったテレメトリーが届かず、検査対象が0件のまま終了します。実測でも最初はこれに気付かず、違反0件の結果を得ていました。`registry/weaver.sh` は `--otlp-grpc-address 0.0.0.0` を指定しています。

一方、依存先である公式レジストリの `service.name` や `network.peer.address` などもviolationになりました。live-checkが依存先を解決する範囲は追加調査が必要です。CIの合否に使う場合は、検出された違反を種類に応じて扱う必要があります。

## フリートに設定を配る

agentはSupervisorから起動し、`opamp/remote-configs/remote.yaml` の変更をOpAMPサーバーが接続中のSupervisorへ配布します。正常な設定、起動できない設定、起動できるがテレメトリーを止める設定を試しました。

スパンへ属性を追加するprocessorをリモート設定へ書いて保存すると、2秒以内にAPPLIEDになり、以降のスパンに新しい `fleet.config.version` が付きました。Collectorは再デプロイしていません。この実装のOpAMPサーバーは設定ファイルを2秒間隔でポーリングするため、検知の遅延はその間隔で決まります。

存在しないprocessorを参照する設定を配ると、Supervisorは約1秒で起動失敗を検知し、FAILEDを報告しました。しかし、サーバーが適用済みハッシュと配布中のハッシュの違いだけを見て再送すると、FAILEDの後も同じ設定を送り続けます。そこで、FAILEDと報告されたハッシュを再送しない制御を `opamp/server/main.go` に実装しました。

Supervisor側でも、`automatic_config_rollback` を有効にしていたにもかかわらず、0.159.0では前の設定へ自己復旧しませんでした。壊れた設定を「最後に動作した設定」として `last_working_remote_config.dat` へ永続化する挙動を、macOSとLinuxの両方で確認しています。FAILEDのまま30秒観測しても状態は変わりませんでした。サーバーから修正済みの設定を配り直すと復旧しました。

filterで全スパンをdropする設定は起動に成功し、ステータスもAPPLIEDかつhealthyのままでした。50リクエストを送ってもTempoへ到達したトレースは0件で、ロールバックも発生しません。正常な設定を再配布すると復旧し、25リクエストから6トレースが到達しました。

この実測では、自動ロールバックだけでフリートを保護できませんでした。canary、テレメトリー到達の監視、FAILEDになった設定の再送防止、修正版の再配布を組み合わせる必要があります。

## ゼロコード計装を試す

20章のビルド時計装を、計装コードを一切含まない `services/uninstrumented` で試します。

```console
$ cd autoinstrument/otelc
$ go run go.opentelemetry.io/otelc/tool/cmd/otelc pin
$ go run go.opentelemetry.io/otelc/tool/cmd/otelc go build -o legacy-instrumented .
$ docker compose -f ../../deploy/docker-compose.yaml stop uninstrumented
$ OTEL_SERVICE_NAME=legacy-otelc OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 ./legacy-instrumented
```

`otelc pin` は初回に実行し、計装用の依存を `otel.instrumentation.go` と `go.mod` へ書き出します。以降は `go build` を `otelc go build` に置き換えます。生成されたバイナリは約25MBで、計装ランタイムを含みます。起動ログには「trace provider initialized with auto-export」「runtime metrics enabled」と出力され、100リクエストから、tail samplingを通過した11トレースがTempoへ届きました。

pinが書き出す `go.mod` の `replace` は、作業ディレクトリ配下の絶対パスを指します。このため、**pinの生成物をリポジトリへコミットすると、別のマシンでpinが失敗します**（`package ... is not part of a module`）。最初の実測をmacOSで行い、その生成物がコミットされていたため、Linuxでの再実測はここで止まりました。生成物を `.gitignore` へ入れ、素の `go.mod` からpinを実行してビルドが通ることをCIで検査する構成へ変更しています。

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

`invoke_agent` の子としてLLM呼び出しとツール実行が並び、ツールから呼び出した社内APIの分散トレースがその下へつながっています。トークン使用量はリクエストごとに変わるスタブ値です。ai-appのトレースもtail samplingの対象なので、30リクエストで3トレースの到達でした。

`ai-ops/` には、レジストリを読むregistry MCPと、実データを読むtelemetry MCPの構成例があります。registry MCPは `weaver registry mcp` を標準入出力で起動し、telemetry MCPはGrafanaスタック向けのMCPサーバーを使います。

MCP経由でAIエージェントに調査させる一連の実験は、このリポジトリでは実測していません。構成例を試す場合も、レジストリと実データに別々の権限を設定します。

## 章とディレクトリの対応

| 章 | 主題 | 対応ディレクトリ |
|---|---|---|
| 10章 | SDKディストリビューション | sdk/ |
| 20章 | ゼロコード計装 | autoinstrument/、services/uninstrumented/ |
| 30章 | Collectorのビルドと設定 | collector/、deploy/ |
| 40章 | フリート管理 | opamp/ |
| 50章 | レジストリとWeaver | registry/、sdk/semconv/ |
| 60章 | AIワークロードの観測 | services/ai-app/ |
| 70章 | AIによる読み取り | ai-ops/ |

`.github/workflows/` には、レジストリ変更時のcheckとdiff、生成コードが最新であることの検査、OCBビルド、`validate` による設定検証、素の状態からのotelc pinとビルドを実装しています。

## 段階導入のチェックリスト

リファレンス実装は各章の部品をまとめて起動しますが、実際の組織では段階的に導入できます。本書では次の順序を推奨します。

1. agent Collectorを立て、既存の計装からのテレメトリーをCollector経由に変える。後続の共通処理はこの経路へ追加する
2. SDKディストリビューションを作り、新規サービスから採用を始める。既存サービスは更新のタイミングで移行する
3. ゼロコード計装で未計装サービスの最低保証を作る。共通CIを変更できるならGoはotelcから始める
4. gateway層を立て、サンプリングと属性統制を集約する
5. レジストリを定義し、まず新しい社内属性の追加だけをレジストリ経由に限定する。生成とlive-checkはその後で足す
6. フリートが大きくなり設定変更が頻繁になったら、OpAMPを導入する
7. AI拡張はgen_ai属性の取り込みから。エージェントへのアクセス提供はread権限から始める

各段階で導入した配布物と検査は、後続の段階を待たずに利用できます。
