---
title: "Grafana BeylaとOpenTelemetry eBPF Instrumentation（OBI）の差分は何か"
emoji: "🔬"
type: "tech"
topics: ["OpenTelemetry", "eBPF", "grafana", "Observability", "Beyla"]
published: true
---

:::message
検証環境

- ホスト: Ubuntu、カーネル7.0.0-31-generic、`/sys/kernel/btf/vmlinux` あり
- 計装対象: `nginx:1.27-alpine`（ポート80をホストへ公開）
- エージェント: `otel/ebpf-instrument:v0.13.0`（2026-09-04リリース）、`grafana/beyla:3.35.0`（2026-09-09リリース、OBIサブモジュールは `861d907`）
- 起動方法: `docker run --privileged --pid=host --network=host`、Prometheusエンドポイントを `curl` でスクレイプ
:::

## はじめに

先日のGo Conferenceで[OpenTelemetry eBPF Instrumentation](https://opentelemetry.io/ja/docs/zero-code/obi/)（以下OBI）について発表し、その詳細を[Zennの本](https://zenn.dev/ymotongpoo/books/go-ebpf-primer)として公開しましたが、そもそもOBIがGrafana Labsが開発していたBeylaが元になっていることはあまり触れていませんでした。

[Grafana Beyla](https://github.com/grafana/beyla) は2025年にOpenTelemetryへ[寄贈され](https://grafana.com/blog/opentelemetry-ebpf-instrumentation-beyla-donation/)、OpenTelemetry eBPF Instrumentationという名前でCNCF側の開発が進んでいます。その後、Beylaは廃止されたのではなく、OBIのダウンストリーム配布物として残りました。では今、両者を入れ替えると何が変わるのでしょうか。

手元のLinuxで、記事執筆時点の最新版のOBIとBeylaの両コンテナイメージを同じ条件で動かし、出力されたメトリクスと設定の受け付け方を比較しました。

## TL;DR

テレメトリーの本体（HTTPサーバーメトリクス、ルート推定、プロトコル解析、eBPFプローブ）はすべてOBI由来で差がなく、差分はメトリクス名の接頭辞、Grafanaの製品と接続するための出力経路、いくつかの追加機能、そして設定ファイルの世代に集中しています。

## リポジトリの関係

Beylaのリポジトリは、OBIのリポジトリをgitのサブモジュール `.obi-src` として取り込み、`go.mod` で `replace go.opentelemetry.io/obi => ./.obi-src` と差し替えています。つまりBeylaはOBIをライブラリとしてvendorした薄いラッパーです。分量にもそれが表れています。

| 項目 | OBI | Beyla | 差 |
| --- | --- | --- | --- |
| Goのコード行数（テスト、vendor、生成コードを除く） | 153,939 | 10,275 | Beylaは6.7% |
| バイナリのサイズ（バイト） | 127,759,366 | 129,898,523 | 1.7%増 |

Beyla 3.35.0が固定しているOBIのコミットは `861d907` で、OBIのタグ `v0.13.0` の2コミット後にあたります。リリースは常にOBIが上流で、Beylaのリリースノートは「Update OBI submodule to ...」というOBIの更新が大半です。

Beyla側にしか存在しないGoパッケージを並べると、追加機能の概要が見えてきます。

| パッケージ | 役割 |
| --- | --- |
| `pkg/webhook` | OpenTelemetry SDKをPodへ注入するKubernetesのmutating webhook（実験的機能） |
| `pkg/export/otel` | Grafana Cloud向けのOTLP設定、GenAIスパンの別経路出力、survey用メトリクス |
| `cmd` | `beyla`、`beyla-schema`、`k8s-cache` の各エントリポイント |
| `pkg/internal/infraolly` | プロセスのCPU、メモリ、ディスク、ネットワークの収集 |
| `pkg/beyla` | Beyla設定型とOBI設定型の相互変換 |
| `pkg/export/prom` | プロセスメトリクスのPrometheus出力 |
| `pkg/services` | Beyla固有の除外規則とsurvey選択条件 |
| `pkg/export/alloy` | Grafana Alloyのトレースレシーバー連携 |

## メトリクス名と識別子の違い

同じnginxに対して `features: [application]` だけを有効にし、Prometheus形式で出てくるメトリクスを比べました。セマンティック規約に沿ったメトリクスは名前が一致し、規約の外にある独自メトリクスだけが接頭辞で分かれます。

| メトリクス・属性 | OBI | Beyla |
| --- | --- | --- |
| HTTPサーバーメトリクス | `http_server_request_duration_seconds` 他 | 同一 |
| ビルド情報 | `obi_build_info` | `beyla_build_info` |
| ネットワークフロー | `obi_network_flow_bytes_total` | `beyla_network_flow_bytes_total` |
| フロー属性 | `obi.ip` | `beyla.ip` |
| `target_info` の `source` | `obi` | `beyla` |
| `target_info` の `telemetry_sdk_name` | `opentelemetry` | `beyla` |
| `target_info` の `telemetry_distro_version` | `v0.13.0` | `unset` |

接頭辞はOBIが `attr.VendorPrefix` などの変数として外部から差し替えられるように公開しているもので、Beylaは起動時に `beyla` へ上書きします [^version-info] 。

[^version-info]: 最後の行だけは意図した差ではなさそうです。`telemetry_distro_version` がBeylaでは `unset` になる一方、`beyla_build_info` は `version="v3.35.0"` を正しく持っているので、ビルド時のバージョン埋め込み自体は有効です。OBI側の `TelemetryDistroVersion` がパッケージ変数の初期化時にOBIの `buildinfo.Version` を写し取る一方、Beylaがその値を上書きするのは初期化より後の `OverrideOBIGlobalConfig` の中なので、写し取られた初期値の `unset` が残ります。ダッシュボードやアラートでこの属性を使っている場合は、Beylaでは値が入らないものとして扱う必要があります。この件は[修正](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/pull/3434)がOBI本体にマージされましたが、執筆時点ではリリース済みのOBIにも、Beylaが取り込んでいるOBIにも入っていません。


## Beylaだけが持つ機能

### プロセスメトリクス

`application_process` 機能はBeylaにしかありません。OBIに同じ値を渡すと、有効な機能名の一覧を添えて起動を拒否されます。

```
$ docker run --rm ... -e OTEL_EBPF_PROMETHEUS_FEATURES=application,application_process \
    otel/ebpf-instrument:v0.13.0
level=ERROR msg="wrong configuration" error="... unknown metrics feature \"application_process\"
  (valid features: all, application, application_host, application_runtime,
  application_service_graph, application_span, application_span_otel, application_span_sizes,
  ebpf, network, network_flow_packets, network_inter_zone, stats,
  stats_tcp_failed_connections, stats_tcp_io, stats_tcp_retransmits, stats_tcp_rtt)"
```

Beylaで有効にすると、計装対象プロセスごとに6本のメトリクスが増えました。

```
process_cpu_time_seconds_total
process_cpu_utilization_ratio
process_disk_io_bytes_total
process_memory_usage_bytes
process_memory_virtual_bytes
process_network_io_bytes_total
```

名前のとおり、eBPFで取得したものではなくOS上のプロセスのシステムメトリクスです。計装対象として選ばれたサービスのPIDだけにスコープが絞られる点で、ホスト全体のエージェントとは異なります。`process_network_io_bytes_total` だけは扱いに注意が必要です。取得元の `/proc/<pid>/net/dev` はnetwork namespace単位のインタフェース統計なので、同じnamespaceに複数のプロセスがいると全員が同じ値を報告します。

### surveyモード

`discovery.survey` は、プロセスを発見して言語を判定するだけで計装はせず、`survey_info` メトリクスとして対象の一覧を出す機能です。外部の自動計装基盤に「計装できる対象の台帳」を渡す用途を想定しています。同じYAMLを両者に読ませると、Beylaは `survey_info` を出し、OBIはこのキーを無視して通常の計装だけを行いました。

```
# Beyla
survey_info{...,job="nginx",service_name="nginx",source="beyla",...} 1
```

### Grafana製品への出力経路

Beylaの設定には `grafana.otlp` セクションがあり、`cloud_zone` と `cloud_instance_id` と `cloud_api_key` を書くだけでGrafana CloudのOTLPエンドポイントとヘッダーが組み立てられます。OBIは汎用のeBPF計装ツールとして公開されているので、OTLPエンドポイントやその認証は標準の方式（OTLPエンドポイントURLを指定し、ヘッダーを組み立てた状態で設定に渡す）で行う必要があります。

このほか、[Grafana Alloy](https://grafana.com/docs/alloy/latest/) にスパンを直接渡すレシーバー連携（`pkg/export/alloy`）、クラスターをまたぐサービスグラフを[Tempo](https://grafana.com/docs/tempo/latest/)側で組み立てるための接続スパン（`BEYLA_TOPOLOGY_SPANS=inter_cluster`）、GenAIのスパンだけを抽出して別のOTLP宛先へ送る経路（`BEYLA_GRAFANA_AI_*`）がBeyla側にあります。いずれもOBIのパイプラインの出力キューを購読する追加ノードとして実装されており、OBI本体には手を入れていません。

### Kubernetes向けのSDK注入

`pkg/webhook` はBeyla固有パッケージで最大の分量を占めます。mutating webhookとしてPodの作成を受け取り、言語を判定してOpenTelemetry SDKを注入する仕組みで、Beyla自身のドキュメントにも記載がなく、コード中でも実験的機能として将来の削除があり得ると明示されています。現時点では評価対象というより、eBPFとSDKを併用する運用をGrafanaがどう実装しようとしているかを読む材料です。

## デフォルト値の違い

同じ入力でも結果が変わる箇所があります。HTTPパスからルートを推定するときのモードです。OBIのデフォルトは `heuristic`、Beylaのデフォルトは `low-cardinality` で、後者は推定後のルートをプロセスごとに木構造で覚えておき、同じ階層に現れるセグメントの種類がデフォルト10を超えた時点で、その階層をまとめてワイルドカードにします。

`/shop/<英単語>` を26種類叩いて、`http_server_request_duration_seconds_count` に現れた `http_route` を数えました。

```
# OBI: 26種類がそのまま残る
/shop/alpha /shop/bravo /shop/charlie ... /shop/zulu

# Beyla: 上限を超えたプロセスでは /shop/* にまとめられる
/shop/*
/shop/alpha /shop/bravo ...
```

どちらも `/users/12345/orders/98` は `/users/*/orders/*` へ正しくまとめていました。数値やハッシュらしいセグメントをワイルドカードにするヒューリスティクスは共通で、差は「見たことのない文字列セグメントが増え続けたときに打ち切るか」だけです。カーディナリティの上限を気にする環境ではBeylaのデフォルトのほうが安全側に寄っており、OBIで同じ挙動を得たい場合は `routes.unmatch: low-cardinality` を明示します。

自己計装を避けるためのデフォルトの除外パターンも異なります。OBIは `obi` と `otelcol*` を除外し、BeylaはこれにGrafana由来のプロセス名（`*beyla`、`*alloy`、`*prometheus-config-reloader`）とKubernetesの名前空間（`grafana-alloy`、`monitoring` など）、コンテナ名を加えます。

環境変数の接頭辞も違います。OBIは `OTEL_EBPF_*`、Beylaは `BEYLA_*` です。ただしBeylaは起動時に `BEYLA_` で始まる変数を `OTEL_EBPF_` に読み替えた同名の変数を補うので、上流のドキュメントに載っている変数名もそのまま使えます。

## 設定ファイルの世代差

いま両者の差がもっとも大きいのは設定ファイルのバージョンです。OBIはOpenTelemetryの宣言的設定に合わせたConfig v2（`file_format` と `extensions.obi` を持つ文書）をv0.11.0から読めます。検証と移行のサブコマンドも入っています。

```
$ docker run --rm -v /tmp/v2.yaml:/cfg.yaml otel/ebpf-instrument:v0.13.0 config validate /cfg.yaml
configuration is valid

$ docker run -d ... -e OTEL_EBPF_CONFIG_PATH=/cfg.yaml otel/ebpf-instrument:v0.13.0
level=INFO msg="configuration loaded" version=v2
```

実際に通したv2の設定は次のものです。

```yaml
file_format: "1.0"
meter_provider:
  readers:
    - pull:
        exporter:
          prometheus/development:
            port: 9414
extensions:
  obi:
    version: "2.0"
    capture:
      policy:
        default_action: exclude
      rules:
        - action: include
          match:
            process:
              open_ports: "80"
```

同じファイルをBeylaに渡すと、v1として解釈しようとして失敗します。

```
$ docker run --rm ... -e BEYLA_CONFIG_PATH=/cfg.yaml grafana/beyla:3.35.0
level=ERROR msg="wrong Beyla configuration"
  error="missing application discovery section or network metrics configuration."
```

理由はBeylaの `cmd/beyla/main.go` で確認できます。v2のローダーがOBIの `internal/config/{schema,convert}` にあり、Goのinternalパッケージ規則はローカルの `replace` では回避できないため、OBI側が `pkg/` 以下に公開ローダーを出すまでBeylaはv1しか読めません。`beyla config validate` のようなサブコマンドも存在しません。

## 埋め込み先としてのOBI

OBIには `collector/` パッケージがあり、コンポーネント型 `obi` のレシーバーファクトリを公開しています。OpenTelemetry Collectorのパイプラインに組み込む形でトレースとメトリクスを受け取れるため、独立プロセスとしてのエージェントではなくCollectorの一部として動かせます。Beylaの対応する経路はAlloyのレシーバー連携です。

テレメトリーの契約の扱いにも差があります。OBIは自身が出すメトリクスとスパンをWeaver互換のスキーマレジストリとして `site/schemas/obi/<version>` に公開し、リソースの `schema_url` にそのURLを載せます。リネームや削除はスキーマの変換として記録する運用になっています。属性名やメトリクス名の変更を機械的に追跡したい場合は、この仕組みがあるOBI側が扱いやすくなっています。

安定性の宣言も明文化されています。OBIの `VERSIONING.md` は現状をDevelopmentと位置付け、`v0` のマイナーリリース間で設定、デフォルト値、挙動、出力テレメトリーの破壊的変更があり得る、`latest` を安定タグとして扱うな、と書いています。2026年の目標としては1.0、プロトコル拡充、.NET対応、SDKとの併用が挙げられています。

## どちらを選ぶか

計装エンジンは同一なので、選択の基準は接続先と運用の制約になります。

Grafana CloudやAlloy、Tempoのサービスグラフと繋ぐなら、そのための設定経路とプロセスメトリクスが揃っているBeylaを使う方が素直です。OpenTelemetry Collectorのレシーバーとして組み込みたい、宣言的設定（Config v2）に寄せたい、テレメトリースキーマで出力の変更を追跡したい、という場合はOBIを直接使うことになります。

どちらを選んでも、不具合の報告と修正の宛先はOBIのリポジトリです。Beyla側のREADMEも、ドキュメント以外のPRは上流へ出すよう求めています。Beylaで踏んだ問題を調べるときは、まず `.obi-src` が指しているコミットを確認してから上流のissueを探すのが早道です。

## おわりに

Beylaは、OBIをライブラリとして取り込み、Grafanaの製品に繋ぐための出力経路といくつかの追加機能を足したディストリビューションだということを確認しました。計装の中身はOBIそのもので、独自に持っているのはGrafana CloudやAlloyへの接続、プロセスメトリクス、surveyモード、Kubernetes向けのSDK注入といった周辺部分に限られます。

開発はOBIが上流で、Beylaはサブモジュールを更新して追いかけています。OBIは2026年に1.0を目指して宣言的設定への移行やプロトコルの拡充を進める一方、Beylaはv1しか読めない設定ローダーのように追いついていない箇所を残しています。当面は、eBPF計装そのものに関心があるならOBIを見ておけば足り、Grafanaの製品と組み合わせるときにBeylaを選ぶ、という認識で良さそうです。
