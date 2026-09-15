---
title: "Grafana BeylaとOpenTelemetry eBPF Instrumentation（OBI）の差分を実機で確かめる"
emoji: "🔬"
type: "tech"
topics: ["OpenTelemetry", "eBPF", "grafana", "Observability", "beyla"]
published: false
---

## この記事で確かめること

[Grafana Beyla](https://github.com/grafana/beyla) は2025年にOpenTelemetryへ寄贈され、[OpenTelemetry eBPF Instrumentation](https://opentelemetry.io/ja/docs/zero-code/obi/)（以下OBI）という名前でCNCF側の開発が進んでいます。Beylaは廃止されたのではなく、OBIのダウンストリーム配布物として残りました。では今、両者を入れ替えると何が変わるのでしょうか。

手元のLinux（カーネル7.0.0、BTF有効）で、記事執筆時点の最新である `otel/ebpf-instrument:v0.13.0` と `grafana/beyla:3.35.0` の両コンテナイメージを同じ条件で動かし、出力されたメトリクスと設定の受け付け方を比較しました。計測対象は[nginx](https://nginx.org/) 1.27（`nginx:1.27-alpine`、ポート80）で、どちらのエージェントも `--privileged --pid=host --network=host` で起動し、Prometheusエンドポイントをスクレイプしています。

結論を先に置きます。テレメトリの本体（HTTPサーバーメトリクス、ルート推定、プロトコル解析、eBPFプローブ）はすべてOBI由来で差がなく、差分はメトリクス名の接頭辞、Grafanaの製品と接続するための出力経路、いくつかの追加機能、そして設定ファイルの世代に集中しています。

## リポジトリの関係

Beylaのリポジトリは、OBIのリポジトリをgitのサブモジュール `.obi-src` として取り込み、`go.mod` で `replace go.opentelemetry.io/obi => ./.obi-src` と差し替えています。つまりBeylaはOBIをライブラリとしてvendorした薄いラッパーです。

分量にも出ます。テストとvendorと生成コードを除いたGoのコード行数は、OBI側が153,939行、Beyla側が10,275行でした。バイナリのサイズはOBIが127,759,366バイト、Beylaが129,898,523バイトで、差は2%未満です。

```
$ find . -name '*.go' -not -path './vendor/*' -not -path './.obi-src/*' \
    -not -name '*_test.go' -not -path './internal/test/*' | xargs wc -l | tail -1
 10275 total
```

Beyla 3.35.0が固定しているOBIのコミットは `861d907` で、OBIのタグ `v0.13.0` の2コミット後にあたります。リリースの向きは常に上流から下流で、Beylaのリリースノートは「Update OBI submodule to ...」という行の集まりが大半を占めます。

Beyla側にしか存在しないGoパッケージを行数順に並べると、追加機能の重心が見えます。

| パッケージ | 行数 | 役割 |
| --- | --- | --- |
| `pkg/webhook` | 2708 | OpenTelemetry SDKをPodへ注入するKubernetesのmutating webhook（実験的機能） |
| `pkg/export/otel` | 1349 | Grafana Cloud向けのOTLP設定、GenAIスパンの別経路出力、survey用メトリクス |
| `cmd` | 1057 | `beyla`、`beyla-schema`、`k8s-cache` の各エントリポイント |
| `pkg/internal/infraolly` | 952 | プロセスのCPU、メモリ、ディスク、ネットワークの収集 |
| `pkg/beyla` | 794 | Beyla設定型とOBI設定型の相互変換 |
| `pkg/export/prom` | 681 | プロセスメトリクスのPrometheus出力 |
| `pkg/services` | 220 | Beyla固有の除外規則とsurvey選択条件 |
| `pkg/export/alloy` | 194 | Grafana Alloyのトレースレシーバ連携 |

## メトリクス名と識別子の違い

同じnginxに対して `features: [application]` だけを有効にし、Prometheus形式で出てくるメトリクスの一覧を比べます。

OBI側。

```
http_server_request_body_size_bytes
http_server_request_duration_seconds
http_server_response_body_size_bytes
obi_build_info
target_info
traces_host_info
```

Beyla側は `obi_build_info` が `beyla_build_info` になります。セマンティック規約に沿ったメトリクス（`http_server_*`）は名前が一致し、規約の外にある独自メトリクスだけが接頭辞で分かれます。

この接頭辞はOBIが `attr.VendorPrefix` などの変数として外部から差し替えられるように公開しているもので、Beylaは起動時に `beyla` へ上書きします。ネットワークメトリクスでも同じ差が出ました。`network` 機能を有効にすると、OBIは `obi_network_flow_bytes_total`、Beylaは `beyla_network_flow_bytes_total` を出します。コード上ではフロー属性の `obi.ip` も `beyla.ip` へ置き換えられます。

`target_info` の属性にも違いが現れます。

```
# OBI
target_info{...,source="obi",telemetry_distro_name="opentelemetry-ebpf-instrumentation",
  telemetry_distro_version="v0.13.0",telemetry_sdk_name="opentelemetry",...}

# Beyla
target_info{...,source="beyla",telemetry_distro_name="opentelemetry-ebpf-instrumentation",
  telemetry_distro_version="unset",telemetry_sdk_name="beyla",...}
```

`telemetry_distro_version` がBeylaでは `unset` になっています。`beyla_build_info` は `version="v3.35.0"` を正しく持っているので、ビルド時のバージョン埋め込み自体は効いています。OBI側の `TelemetryDistroVersion` がパッケージ変数の初期化時にOBIの `buildinfo.Version` を写し取る一方、Beylaがその値を上書きするのは初期化より後の `OverrideOBIGlobalConfig` の中なので、写し取られた初期値の `unset` が残ります。ダッシュボードやアラートでこの属性を使っている場合は、Beylaでは値が入らないものとして扱う必要があります。

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

Beylaで有効にすると、計測対象プロセスごとに6本のメトリクスが増えました。

```
process_cpu_time_seconds_total
process_cpu_utilization_ratio
process_disk_io_bytes_total
process_memory_usage_bytes
process_memory_virtual_bytes
process_network_io_bytes_total
```

### surveyモード

`discovery.survey` は、プロセスを発見して言語を判定するだけで計測はせず、`survey_info` メトリクスとして対象の一覧を出す機能です。外部の自動計測基盤に「計測できる対象の台帳」を渡す用途を想定しています。同じYAMLを両者に読ませると、Beylaは `survey_info` を出し、OBIはこのキーを無視して通常の計測だけを行いました。

```
# Beyla
survey_info{...,job="nginx",service_name="nginx",source="beyla",...} 1
```

### Grafana製品への出力経路

Beylaの設定には `grafana.otlp` セクションがあり、`cloud_zone` と `cloud_instance_id` と `cloud_api_key` を書くだけでGrafana CloudのOTLPエンドポイントとヘッダーが組み立てられます。OBIに同じセクションを含むYAMLを渡しても、未知のキーとして黙って捨てられ、エンドポイントは既定値のままでした。

このほか、[Grafana Alloy](https://grafana.com/docs/alloy/latest/) にスパンを直接渡すレシーバ連携（`pkg/export/alloy`）、クラスタをまたぐサービスグラフを[Tempo](https://grafana.com/docs/tempo/latest/)側で組み立てるための接続スパン（`BEYLA_TOPOLOGY_SPANS=inter_cluster`）、GenAIのスパンだけを抽出して別のOTLP宛先へ送る経路（`BEYLA_GRAFANA_AI_*`）がBeyla側にあります。いずれもOBIのパイプラインの出力キューを購読する追加ノードとして実装されており、OBI本体には手を入れていません。

### Kubernetes向けのSDK注入

`pkg/webhook` はBeyla固有パッケージで最大の2708行を占めます。mutating webhookとしてPodの作成を受け取り、言語を判定してOpenTelemetry SDKを注入する仕組みで、Beyla自身のドキュメントにも記載がなく、コード中でも実験的機能として将来の削除があり得ると明示されています。現時点では評価対象というより、eBPFとSDKを併用する運用をGrafanaがどう実装しようとしているかを読む材料です。

## 既定値の違い

同じ入力でも結果が変わる箇所があります。HTTPパスからルートを推定するときの既定モードです。OBIの既定は `heuristic`、Beylaの既定は `low-cardinality` で、後者は推定後のルートをプロセス単位のtrieに入れ、同じ位置に現れるセグメントの種類が上限（既定10）を超えた時点でワイルドカードへ畳みます。

`/shop/<英単語>` を26種類叩いて、`http_server_request_duration_seconds_count` に現れた `http_route` を数えました。

```
# OBI: 26種類がそのまま残る
/shop/alpha /shop/bravo /shop/charlie ... /shop/zulu

# Beyla: 上限を超えたプロセスでは /shop/* に畳まれる
/shop/*
/shop/alpha /shop/bravo ...
```

どちらも `/users/12345/orders/98` は `/users/*/orders/*` へ正しく縮約しました。数値やハッシュらしいセグメントを潰すヒューリスティクスは共通で、差は「見たことのない文字列セグメントが増え続けたときに打ち切るか」だけです。カーディナリティの上限を気にする環境ではBeylaの既定のほうが安全側に寄っており、OBIで同じ挙動を得たい場合は `routes.unmatch: low-cardinality` を明示します。

自己計測を避けるための既定の除外パターンも異なります。OBIは `obi` と `otelcol*` を除外し、BeylaはこれにGrafana由来のプロセス名（`*beyla`、`*alloy`、`*prometheus-config-reloader`）とKubernetesの名前空間（`grafana-alloy`、`monitoring` など）、コンテナ名を加えます。

環境変数の接頭辞も違います。OBIは `OTEL_EBPF_*`、Beylaは `BEYLA_*` です。ただしBeylaは起動時に `BEYLA_` で始まる変数を `OTEL_EBPF_` に読み替えた同名の変数を補うので、上流のドキュメントに載っている変数名もそのまま使えます。

## 設定ファイルの世代差

いま両者の差がもっとも大きいのは設定ファイルの読み込みです。OBIはOpenTelemetryの宣言的設定に合わせたConfig v2（`file_format` と `extensions.obi` を持つ文書）をv0.11.0から読めます。検証と移行のサブコマンドも入っています。

```
$ docker run --rm -v /tmp/v2.yaml:/cfg.yaml otel/ebpf-instrument:v0.13.0 config validate /cfg.yaml
configuration is valid

$ docker run -d ... -e OTEL_EBPF_CONFIG_PATH=/cfg.yaml otel/ebpf-instrument:v0.13.0
level=INFO msg="configuration loaded" version=v2
```

同じファイルをBeylaに渡すと、v1として解釈しようとして失敗します。

```
$ docker run --rm ... -e BEYLA_CONFIG_PATH=/cfg.yaml grafana/beyla:3.35.0
level=ERROR msg="wrong Beyla configuration"
  error="missing application discovery section or network metrics configuration."
```

理由はBeylaの `cmd/beyla/main.go` に書かれています。v2のローダーがOBIの `internal/config/{schema,convert}` にあり、Goのinternalパッケージ規則はローカルの `replace` では回避できないため、OBI側が `pkg/` 以下に公開ローダーを出すまでBeylaはv1しか読めません。`beyla config validate` のようなサブコマンドも存在しません。

v2文書を書く際の注意も一つ見つかりました。ポート指定のルールは `match.network.open_ports` ではなく `match.process.open_ports` で、前者を書くと `config validate` が「ランタイムの変換器が対応していない」と拒否します。またPrometheusのpullエクスポータで `host` を指定すると同様に拒否され、`port` のみが通ります。

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

## 埋め込み先としてのOBI

OBIには `collector/` パッケージがあり、コンポーネント型 `obi` のレシーバファクトリを公開しています。OpenTelemetry Collectorのパイプラインに組み込む形でトレースとメトリクスを受け取れるため、独立プロセスとしてのエージェントではなくCollectorの一部として動かせます。Beylaの対応する経路はAlloyのレシーバ連携です。

テレメトリの契約の扱いにも差があります。OBIは自身が出すメトリクスとスパンをWeaver互換のスキーマレジストリとして `site/schemas/obi/<version>` に公開し、リソースの `schema_url` にそのURLを載せます。リネームや削除はスキーマの変換として記録する運用になっています。属性名やメトリクス名の変更を機械的に追跡したい場合は、この仕組みがあるOBI側が扱いやすくなっています。

安定性の宣言も明文化されています。OBIの `VERSIONING.md` は現状をDevelopmentと位置付け、`v0` のマイナーリリース間で設定・既定値・挙動・出力テレメトリの破壊的変更があり得る、`latest` を安定タグとして扱うな、と書いています。2026年の目標としては1.0、プロトコル拡充、.NET対応、SDKとの併用が挙げられています。

## どちらを選ぶか

計測エンジンは同一なので、選択の基準は接続先と運用の制約になります。

Grafana CloudやAlloy、Tempoのサービスグラフと繋ぐなら、そのための設定経路とプロセスメトリクスが揃っているBeylaが素直です。OpenTelemetry Collectorのレシーバとして組み込みたい、宣言的設定（Config v2）に寄せたい、テレメトリスキーマで出力の変更を追跡したい、という場合はOBIを直接使うことになります。

どちらを選んでも、不具合の報告と修正の宛先はOBIのリポジトリです。Beyla側のREADMEも、ドキュメント以外のPRは上流へ出すよう求めています。Beylaで踏んだ問題を調べるときは、まず `.obi-src` が指しているコミットを確認してから上流のissueを探すのが早道です。

## 検証環境

- ホスト: Ubuntu、カーネル7.0.0-31-generic、`/sys/kernel/btf/vmlinux` あり
- 計測対象: `nginx:1.27-alpine`（ポート80をホストへ公開）
- エージェント: `otel/ebpf-instrument:v0.13.0`（2026-09-04リリース）、`grafana/beyla:3.35.0`（2026-09-09リリース、OBIサブモジュールは `861d907`）
- 起動方法: `docker run --privileged --pid=host --network=host`、Prometheusエンドポイントを `curl` でスクレイプ
