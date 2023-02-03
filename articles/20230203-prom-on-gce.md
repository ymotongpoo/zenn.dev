---
title: "Google Compute EngineでPrometheus指標を簡単に収集する"
emoji: "📰"
type: "tech" # tech: 技術記事 / idea: アイデア
topics: ["GoogleCloud", "GCP", "Prometheus", "GCE", "CloudMonitoring"]
published: true
publication_name: google_cloud_jp
---

こんにちは！Google Cloudでオブザーバビリティを担当しているものです！今日はメトリクスの収集に関して便利な機能がでたのでそのお知らせをしに来ました。

## TL;DR

日本標準時間2023年2月3日でGoogle Compute Engine上でもOpsAgent経由でPrometheus形式（OpenMetrics形式）の指標を簡単に取得できるようになりました。

@[card](https://cloud.google.com/blog/products/devops-sre/monitor-gce-instances-with-prometheus-and-ops-agent)

@[card](https://cloud.google.com/monitoring/agent/ops-agent/prometheus)

## OpsAgentとは

OpsAgentというのはGoogle Compute Engine上でのログやメトリクスを収集するためのエージェントです。これは、過去Cloud LoggingエージェントとCloud Monitoringエージェントとして別々に配布され、管理する必要があったものを、統一的に管理できるようにしたエージェントです。

@[card](https://cloud.google.com/stackdriver/docs/solutions/agents/ops-agent)

内部的にはログに関しては[Fluent Bit](https://fluentbit.io/)、メトリクスに関しては[OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)が使われています。

今回のアップデートは、このOpenTelemetry Collectorの[Prometheus receiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/receiver/prometheusreceiver/README.md)が、OpsAgentからでも使えるようになりました、というお知らせとなります。

## 普通に試してみる

実際にどのようになるのか、[Prometheusが公開しているサンプルコード](https://github.com/prometheus/client_golang/blob/main/examples/simple/main.go)を動かして見てみましょう。このGoアプリケーションをビルドしてGoogle Compute Engineで実行してみます。

まずGoプログラムを作成します。上のリンクにあるサンプルコードをちょっとだけ書き換えました。

```go
package main

import (
 "log"
 "net/http"

 "github.com/prometheus/client_golang/prometheus"
 "github.com/prometheus/client_golang/prometheus/collectors"
 "github.com/prometheus/client_golang/prometheus/promhttp"
)

func main() {
 log.Println("start app")
 reg := prometheus.NewRegistry()
 reg.MustRegister(
  collectors.NewGoCollector(),
  collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
 )

 http.Handle("/metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{Registry: reg}))
 if err := http.ListenAndServe(":8080", nil); err != nil {
  log.Fatalf("failed to keep running HTTP server: %v", err)
 }
}
```

これをローカルの環境でビルドして実行バイナリを作成します。

```console
GOOS=linux GOARCH=amd64 go build -o promgcetest
```

実行するためのGCEインスタンスを作って、OpsAgentをインストールします。詳細は次のドキュメントに譲りますが、今回は `e2-small` でDebian 11のインスタンスを作成して、OpsAgentをインストールしました。

@[card](https://cloud.google.com/stackdriver/docs/solutions/agents/ops-agent/installation)

無事にOpsAgentがインストールされました。

![無事にOpsAgentがインストールされた](/images/20230203145057.png)

次にプログラムをこのインスタンスにコピーします。

```console
gcloud compute scp ./promgcetest demo@prom-opsagent-test:~/
```

次にこのプログラムをインスタンス内で実行します。

```console
nohup $HOME/promgcetest &
```

そしてOpsAgentの設定ファイルを変更します。設定方法についてはこちらのドキュメントを参考にしてください。

@[card](https://cloud.google.com/monitoring/agent/ops-agent/configuration#metrics-config)

上のサンプルアプリでは `localhost:8080/metrics` で指標を公開しているので次のような設定になります。これで10秒ごとに指標を取得することになります。

```yaml
metrics:
  receivers:
    prometheus:
        type: prometheus
        config:
          scrape_configs:
            - job_name: 'sample_go_app'
              scrape_interval: 10s
              metrics_path: /metrics
              static_configs:
                - targets: ['localhost:8080']
  service:
    pipelines:
      prometheus_pipeline:
        receivers:
          - prometheus
```

これでOpsAgentサービスを再起動します。

```console
sudo service google-cloud-ops-agent restart
```

数分時間をおいてから、Cloud MonitoringのMetrics Explorerに行って、実際に値が取れているか確認してみます。取得したデータは `prometheus.googleapis.com` というMonitored Resourceとして記録されているので、それで検索してみましょう。

![](/images/20230203150539.png)

お、どうやら取得できてるようです！早速グラフを見てみましょう！

![](/images/20230203151403.png)

これは `prometheus.googleapis.com/go_memstats_alloc_bytes/gauge` という指標ですが、サンプルアプリのGoランタイムのメモリアロケーションの様子が見て取れます。

以上、OpsAgentでPrometheus指標が取得できていることが確認できました！

## おわりに

今回は単純にデモを動かしてみるだけでしたので、素朴にインスタンスを立ててから、OpsAgentのインストール、起動後の設定ファイルの編集、エージェントの再起動をすべて手動で行いました。

もし本格的に活用される場合には、次のドキュメントにもありますように、ポリシーやプロビジョニングツール等を使った設定を推奨しています。ぜひ一度ご確認ください。

@[card](https://cloud.google.com/monitoring/agent/ops-agent/managing-agent-policies)

@[card](https://cloud.google.com/monitoring/agent/ops-agent/fleet-installation)
