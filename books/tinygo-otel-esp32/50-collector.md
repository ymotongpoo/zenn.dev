---
title: "Collectorと運用"
---

デバイスがOTLPを話せるようになっても、送り先が無ければテレメトリーは誰にも読まれません。この章では、デバイスの送り先として同じLANに置く[OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/)（テレメトリーを受け取り、加工して別の送り先へ転送するサーバープログラム、以下Collector）の構成と、デバイスとCollectorを組み合わせて30分動かした結果を見ていきます。

## デバイスからGrafanaまでの経路

構成は、デバイス、Collector、可視化用のバックエンドの3段です。デバイスはLAN内のCollectorに平文のOTLP/HTTPで送り、Collectorは属性を足してからバックエンドへ転送します。

バックエンドには[grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm)を使います。OTLPを受け付ける口と、メトリクスを保存する[Prometheus](https://prometheus.io/)、ログを保存する[Loki](https://grafana.com/oss/loki/)、トレースを保存する[Tempo](https://grafana.com/oss/tempo/)、それらを表示する[Grafana](https://grafana.com/oss/grafana/)を1つのコンテナにまとめた、開発と検証のためのイメージです。

Collectorとotel-lgtmは[Docker Compose](https://docs.docker.com/compose/)で一緒に立ち上げます。otel-lgtmもOTLPを直接受け付けるので、デバイスから直接送ることもできます。それでもCollectorを間に挟むのは、デバイスから外へ出す仕事を引き受ける場所が必要だからです。

```sh
make stack     # edge collector (:4319) + grafana/otel-lgtm (:3000)
```

ホスト側のポートは4318ではなく4319にしています。ローカルで別のCollectorや[Grafana Alloy](https://grafana.com/docs/alloy/latest/)が4318番を使っていることが多いためです[^port]。デバイスに書き込むエンドポイントには、Collectorを動かしているマシンのLANアドレスを指定します。デバイスから見た `localhost` はデバイス自身なので、Collectorには届きません。

[^port]: ポートは環境変数 `COLLECTOR_PORT` で変えられます。コンテナの中のCollectorは4318番で待ち受けています。

## Collectorの設定

Collectorの設定は、受信（receivers）、加工（processors）、送信（exporters）の部品を定義し、シグナルごとのパイプラインでつなぐ形で書きます。本書の設定から、メトリクスのパイプラインに関係する部分を抜き出すと次のようになります。

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

processors:
  resource:
    attributes:
      - key: deployment.environment.name
        value: demo
        action: upsert
  batch:
    timeout: 5s

exporters:
  otlphttp/lgtm:
    endpoint: http://lgtm:4318
    tls:
      insecure: true

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [resource, batch]
      exporters: [otlphttp/lgtm]
```

受信側は `0.0.0.0` で待ち受けます。Collectorのデフォルトはlocalhostだけで待ち受ける設定ですが、デバイスはLANの別のマシンから平文で送ってくるので、LAN側のインターフェースでも受け付ける必要があります[^listen]。

[^listen]: 待ち受けを広げると、同じネットワークにいる誰からでもテレメトリーを受け付けることになります。本書の構成は、家庭や会場のように範囲の限られたLANを前提にしています。

[`resource` プロセッサー](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/resourceprocessor)は、受け取ったデータのリソース属性（送り元を表す属性）を書き換えます。抜き出した設定で付けているのは[`deployment.environment.name`](https://opentelemetry.io/docs/specs/semconv/resource/deployment-environment/)で、実際の設定では `telemetry.sdk.language` と `telemetry.sdk.name` も同じ場所で付けます。デバイスが自分で送るリソース属性は、`service.name`、`service.version`、`device.id`、`device.model.identifier` の4つだけです。

`deployment.environment.name` をCollectorで付けるのは、デバイスには自分がどの環境で動いているのかが分からないからです。同じファームウェアを検証用のLANに置くか本番の設備に置くかは、置いた側が知っています。デバイスに持たせると、送信のたびに同じバイト列をWi-Fiで送ることにもなります。

[`batch` プロセッサー](https://github.com/open-telemetry/opentelemetry-collector/tree/main/processor/batchprocessor)は、受け取ったデータを最大5秒まで溜めてからまとめて送ります。ログとトレースのパイプラインも同じ部品の組み合わせで、受信と加工と送信の設定はシグナルの間で共有しています。

設定にはもう1つ、受け取ったデータの概要をCollector自身のログに出す `debug` エクスポーターも入れています。Grafanaに何も表示されないとき、Collectorまでは届いているのかを最初に確かめる手段になります。

## ダッシュボード

Grafanaには、デバイス用のダッシュボードをプロビジョニング（起動時に設定ファイルから自動で読み込むこと）しています。メトリクスのパネルが8枚、ログのパネルが1枚、トレースのパネルが2枚です。

![TinyGo ESP32 deviceダッシュボード](/images/tinygo-otel-grafana-dashboard.png)
*図1: デバイスから届いた3シグナルを1枚に並べたダッシュボード。上段がメトリクス、中段の左がLokiに届いたログ、右がTempoに届いた送信周期のトレース、下段がスパンごとの所要時間の推移である。*

Goのヒープのパネルは、GCのたびに使用量が落ちるのこぎり形になります。その右にWi-Fiドライバのアリーナのパネルを並べているのは、前章で触れたとおり、Goのヒープとドライバのメモリを見比べるためです。ログのパネルには、Collectorを止めたときの `export failed` と、復帰後の `export recovered` が、出来事の起きた時刻の順に並んでいます。

下段の所要時間は、Tempoの[span metrics generator](https://grafana.com/docs/tempo/latest/metrics-generator/span_metrics/)がスパンから作ったメトリクスです。デバイスは所要時間のメトリクスを送っていません。トレースを送っておけば、所要時間の集計はバックエンドに任せられます。

## Collector再起動からの回復

デバイスとCollectorの組み合わせが長く動き続けるかは、連続稼働の試験で確かめました。条件はJSONと手書きHTTPクライアントの組み合わせ、スタック16KB、送信間隔10秒、時間は30分です。試験の途中、15分の時点でCollectorのコンテナを再起動します。

試験を回すのは、ホストで動くPythonのスクリプトです。シリアルポートからデバイスの出力を読み、送信の成功を表す行からペイロードの大きさとヒープの使用量を取り出します。ヒープの使用量が前回より減った箇所がGCです。指定した時刻に `docker restart` でCollectorを再起動し、再起動後の最初の送信の成功までの時間を測ります。失敗やpanicを表す行が1行でも出れば、その試験は不合格です。

この試験を、メトリクスだけを送る版と、3シグナルを送る現行の版で行いました。

| 項目 | メトリクスのみ | 3シグナル |
| --- | --- | --- |
| 送信 | 180回 | 180回 |
| 失敗 | 0回 | 0回 |
| 1送信あたりのヒープの増加 | 800バイト | 2,992バイト |
| GC | 1回 | 7回 |
| GC後のヒープ | 178,704バイト | 203,776〜206,128バイト |
| 再起動からの回復 | 6.1秒 | 9.1秒 |

どちらの版も、30分の間に失敗は1回もありませんでした。3シグナル版は使い捨ての確保が増えたぶんGCの回数が増えていますが、GC後のヒープは7回とも約204KBにとどまっていて、メモリは増え続けていません。

回復までの時間は、再起動から次の送信周期までの待ち時間で決まります。Collectorの再起動が送信の間隔の10秒より早く終われば、デバイスは次の周期で送信に成功します。6.1秒と9.1秒の差は、周期の中のどこで再起動が起きたかの違いです。デバイスは接続を使い回していますが、Collectorが落ちて接続が切れても、次の周期で張り直して送信を再開します。

## デバイスとCollectorの役割分担

ここまでの構成では、デバイスとCollectorの間で仕事を分けています。分け方の基準は、その情報や処理がデバイスの上でしか得られないかどうかです。

デバイスに残したのは、デバイスの上でしか分からないことだけです。ヒープとアリーナの使用量、RSSI、送信の結果、出来事が起きた時刻は、どれもデバイスの外からは測れません。そのうえで、溜めておくバッファには上限を置き、溢れた件数をメトリクスで送ります。送り先は同じLANのCollectorで、通信は平文です。

Collectorに任せたのは、デバイスが知らないことと、デバイスに載せられないことです。環境名のような、置いた側が決める属性はCollectorで付けます。インターネットの向こうのバックエンドに送るなら、TLSと認証情報もCollectorに置きます。espradio v0.3.0には動作するTLSクライアントが無く、仮にあっても、証明書と秘密鍵をすべてのデバイスに配って更新し続けることになります。バックエンドが一時的に応答しないときの再送や、送る前のデータの溜め込みもCollectorの役割です。サーバーで動くCollectorなら、416KBのSRAMに収める必要はありません。

デバイスからCollectorまでの区間さえOTLPで話せれば、そこから先はサーバーでOpenTelemetryを使うときと同じ構成になります。本書の構成では、Collectorより先の設定にマイコン固有のものは何もありません。
