---
title: "OpAMPによるCollectorフリート管理"
---

gateway層のtail sampling条件は、設定リポジトリへのPRをマージし、GitOpsで数台のgatewayへ反映できます。

一方、数百ノードのDaemonSetで動くagentを変更する場合は、ConfigMapを更新して全Podをローリング再起動します。変更が少なければ運用できますが、フィルタの追加や一部ノードのデバッグログ有効化が増えると、設定変更のたびに全Podを再起動する負担が大きくなります。多数のCollectorへ設定を配り、状態を管理することを**フリート管理**と呼びます。

## フリート管理の課題

フリート管理では、次の処理が必要です。

- 設定の配布。数百のCollectorに新しい設定を届け、適用されたことを確認する
- 状態の把握。どのCollectorがどの設定で動いていて、健康かどうかを一覧できる
- 失敗への備え。壊れた設定を配ってしまったとき、テレメトリーが止まる範囲を最小にし、自動で戻す

イメージの再配布とローリング再起動だけを使うと、設定変更のたびに全Collectorが再起動し、適用状態はデプロイツールのログから調べます。設定変更の頻度が上がる場合は、設定の配布をデプロイから分離します。

## OpAMPの概要

**OpAMP**（Open Agent Management Protocol）は、複数のエージェントをサーバーから遠隔管理するためのプロトコルです。本書ではCollectorを管理対象とします。仕様には、設定の配布、ヘルスの報告、接続情報の管理、パッケージの更新が含まれます。

各エージェントは管理サーバーへWebSocketまたはHTTPで接続し、AgentToServerとServerToAgentのメッセージを交換します。エージェントは識別情報、実効設定、ヘルスを報告し、サーバーは設定や指示を返します。利用する機能は接続時にcapabilitiesとして交渉するため、設定配布だけを使うこともできます。

2026年8月時点で、[OpAMP仕様](https://github.com/open-telemetry/opamp-spec/blob/main/specification.md)はBetaです。v0.20.0までリリースされていますが、破壊的変更を含み、1.0には達していません。参照実装の[opamp-go](https://github.com/open-telemetry/opamp-go)もv0.23.0です。一方、Supervisorは公式配布物として提供され、複数のベンダー製品がOpAMPを実装しています。実運用は始まっていますが、仕様変更への追従を前提に採用する段階です。

![OpAMPによるフリート管理の構成](/images/20260825-opamp-topology.png)
*図1　実線は設定の配布、点線はエージェントからの報告を表します。設定の正本はGitに置き、OpAMPは管理サーバーからエージェントまでの配布を担います。*

## OpAMP Supervisor

Collector側には、Collector自体へOpAMPクライアントを組み込むopampextension方式と、Collectorの外へ監督プロセスを置く方式があります。後者が**OpAMP Supervisor**です。Supervisor方式でも、opampextensionはSupervisorとCollectorの通信に使います。

SupervisorはOpAMPサーバーとの接続を保ち、Collectorを子プロセスとして起動します。サーバーから受け取った設定をローカル設定と合成して適用し、必要に応じてCollectorを再起動します。Collectorの外側で動くため、Collectorが不調な場合もSupervisorは状態を報告し、復旧を試みられます。

設定は次のような形です。

```yaml
server:
  endpoint: wss://opamp.internal.example.com/v1/opamp

capabilities:
  accepts_remote_config: true
  reports_effective_config: true
  reports_health: true

agent:
  executable: /usr/local/bin/otelcol-internal
  config_files:
    - /etc/otelcol/base.yaml

storage:
  directory: /var/lib/otelcol/supervisor
```

`agent.executable` には、30章でビルドした社内Collectorを指定します。OCBのmanifestには、opampextensionと、起動確認用のnopreceiverおよびnopexporterを含めます。含めずにSupervisorの管理下で起動すると、ブートストラップに失敗しました。これはリファレンス実装で確認した挙動です。

OpAMPサーバーとの接続と設定管理はSupervisorが担当し、opampextensionはSupervisorがCollectorの状態を取得するためのローカルな通信に使います。監督プロセスを外へ置く方式でも、Collector内のextensionは必要です。

`config_files` には、ローカル設定とリモート設定（`$REMOTE_CONFIG`）を並べられます。後から読んだ設定が優先されるため、基盤管理の設定をリモート設定より後へ置けば、必須の設定を最後に重ねられます。ただし、並び順は権限の境界になりません。配布前のCIで、実効設定に必須processorが含まれることと、接続先が許可されていることを検査します。配布後はSupervisorが報告する実効設定と照合します。

Supervisorは[contribのcmd/opampsupervisor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/cmd/opampsupervisor)で開発され、公式のバイナリとコンテナイメージが配布されています。2026年8月時点のstabilityはalphaです。リモート設定の受信と適用、実効設定とヘルスの報告、再起動指示、接続情報の更新は実装されています。

一方、Collectorバイナリを更新するパッケージ管理は未実装です。OpAMP仕様には定義されていますが、Supervisor経由でバイナリを配ることはできません。バイナリはイメージとして再配布し、OpAMPは設定の配布に使います。

## リモート設定の運用設計

OpAMPを導入すると、設定の管理にはGitOpsを、配布にはOpAMPを使います。両方に個別の設定を持つと、Git上の設定と配布済みの設定が一致しません。そこで、Gitを設定の正本とし、設定リポジトリへのマージを契機にOpAMPサーバーが設定を読み込み、Collectorへ配ります。OpAMPはGitOpsを置き換えず、管理サーバーからCollectorまでの配布を担当します。

OpAMPサーバーはエージェントごとに異なる設定を返せるため、属性でグループを分け、段階的に適用できます。たとえば、一台、一つのクラスタ、全体の順に対象を広げます。

Supervisorは、設定適用後にCollectorが起動できない場合に前の設定へ戻す `automatic_config_rollback` と、起動時にサーバーへ接続できない場合に使う `startup_fallback_configs` を備えています。自動ロールバックは既定で無効なため、明示的に有効化します。

自動ロールバックが検出するのは、Collectorが起動できない失敗です。構文上は正しくても、全データをfilterで捨てる設定、誤った宛先、認証に失敗する設定、処理容量を超える設定は、Collectorが起動するため検出されません。リファレンス実装（80章）で全スパンをdropする設定を配ったところ、ステータスはAPPLIEDでhealthyのまま、テレメトリーだけが停止しました。

起動失敗についても、alpha実装を運用上の保証にはできません。実測したv0.159.0のSupervisorは、`automatic_config_rollback` を有効にしていても自己復旧できず、修正済み設定の再配布で復旧しました。サーバー側には、エージェントがFAILEDを報告した設定を再送しない制御も必要でした。実験の経緯と数値は80章に記載します。

設定配布の被害は、canaryから始める段階展開、Collectorの送受信件数とexporter失敗率の監視、合成テレメトリーの到着確認、展開の停止条件、修正版を再配布する手順で抑えます。自動ロールバックが動作しても、これらの検査と復旧手順を置き換えるものではありません。

![段階的ロールアウトの状態遷移](/images/20260825-staged-rollout.png)
*図2　実線は検査を通過した場合、点線は異常を検知した場合の状態遷移を表します。どの段階でも、修正版の再配布によって復旧します。*

## OpAMPサーバーの選択肢

2026年8月時点で、公式のスタンドアロンOpAMPサーバー製品はありません。opamp-goが提供するのは、サーバー実装用のライブラリとデモ用のexample serverです。本番の管理プレーンとして必要な機能は、利用する側が実装します。

リファレンス実装（80章）には、opamp-goのserverライブラリを使った最小サーバーがあります。プロトコルを確認するための学習用実装であり、本番向けの参照実装ではありません。

本番の管理プレーンには、エージェントの認証と識別、テナント分離、対象グループの管理、状態の永続化、変更監査、サーバーの冗長化とアップグレード、段階展開、競合する更新の処理が必要です。設定を送信する処理だけで工数を見積もると、これらの運用機能が抜けます。

本番環境では、フリートの変更頻度と必要な機能から次の方式を選びます。

| 選択肢 | 向いている状況 |
|---|---|
| GitOpsを継続する | 変更頻度が低く、全体一括の適用で足りる |
| OpAMP対応の管理製品を使う | 個別配信、段階展開、フリートの可視化までを早く揃えたい |
| 既存の社内管理プレーンにOpAMPを実装する | 構成管理基盤がすでにあり、Collectorだけ別系統にしたくない |
| 専用の管理プレーンを構築する | フリートが大規模で、配布制御が競争領域になっている |

## GitOpsだけで管理する条件

フリートが小さい間は、ConfigMapの更新とローリング再起動を使うGitOpsだけでも管理できます。判断には、Collectorの台数より設定変更の頻度と対象範囲を使います。

- 設定変更が月に数回で、全体一括の適用で困っていないなら、GitOps単独で足ります
- 変更が週に何度もあり、一部のノードだけ変える必要があれば、OpAMPを検討します
- ヘルスと実効設定の一覧が欲しいだけなら、まずSupervisorを報告専用（accepts_remote_configをfalse）で入れる手もあります

数百ノードのagentを管理する構成では、Gitを設定の正本とし、CIで実効設定を検査してから、OpAMPで各Collectorへ配布します。canaryと監視が異常な設定の展開を止め、失敗時には修正版を再配布します。OpAMPは、レビューと検査を終えた設定をフリートへ反映する経路を、Collectorのデプロイから分離します。
