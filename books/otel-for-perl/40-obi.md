---
title: "OBIで同じアプリケーションを観測する"
---

## コードを変えずに観測する

4章から8章では、Perlのアプリケーションに計装のコードを足してきました。8章で見たとおり、いまのCPANのSDKでは送信を確実にするためにアプリケーションの側で回避策を書く必要があります。それなら、コードに触れずにトレースを取れる方法はないのでしょうか。

[OpenTelemetry eBPF Instrumentation](https://opentelemetry.io/ja/docs/zero-code/obi/)（OBI）は、eBPFを使ってトレースとメトリクスを作るツールです。eBPFは、Linuxのカーネルの中で小さなプログラムを安全に動かす仕組みです。OBIはこの仕組みで、アプリケーションのプロセスやネットワークの動作をカーネルの側から観測します。OBI自身はアプリケーションとは別のプロセスとして動き、アプリケーションのコードにもライブラリにも手を入れません。もとになったのは、Grafana Labsが2025年に寄贈したBeylaです[^beyla]。いまはOpenTelemetryのプロジェクトが開発しています。2026年10月2日にv0.14.0が、10月7日にv1.0.0-rc.1がリリースされました。

[^beyla]: 経緯は[OBIの最初のリリースの告知](https://opentelemetry.io/blog/2025/obi-announcing-first-release/)にあります。

ドキュメントの対応言語の一覧には、Java、.NET、Go、Python、Ruby、Node.js、C、C++、Rustが並び、Perlはありません。ただし、OBIがHTTPやgRPCの通信を読み取る場所はカーネルの側です。そのため言語ごとの対応が無くても、HTTPのリクエストを受けて返す区間はスパンにできます。ログに表示されるこの方式の名前は `type=generic` です。この方式で、Perlのアプリケーションのどこまでを取れるのかを確かめました。

## OBIの起動に必要な条件

OBIのドキュメントは、Linuxカーネル5.8以降とカーネルの型情報である[BTF](https://docs.kernel.org/bpf/btf.html)を要件に挙げています。RHEL系では、4.18以降でeBPFの機能がバックポートされたカーネルが対象です。本書のホストはLinux 7.0.0で、BTFもありました。

Composeには、OBIをもう1つのサービスとして足しました。計装していない `app.psgi` は同じコンテナで起動します。OBIが選ぶ対象は、「ポート5000を開いている」かつ「実行ファイルが `perl`」のプロセスです。ポートだけで選ぶと、ホストのポート5000をコンテナへ中継する `docker-proxy` というGoのプロセスも対象になってしまうからです。

```yaml:compose.yaml（抜粋）
  obi:
    image: otel/ebpf-instrument:v0.14.0
    privileged: true
    pid: host
    volumes:
      # このカーネル（7.0.0）ではFIONREADの補正にtracefsが要る。無いとOBIは伝搬を自動で無効にする
      - /sys/kernel/tracing:/sys/kernel/tracing
      # OBIの起動後に張られた接続にtraceparentを書き込むには、ホストのcgroupが見えている必要がある
      - /sys/fs/cgroup:/sys/fs/cgroup
    environment:
      OTEL_EBPF_OPEN_PORT: "5000"
      OTEL_EBPF_AUTO_TARGET_EXE: "*/perl"
      OTEL_EBPF_BPF_CONTEXT_PROPAGATION: headers
      OTEL_EXPORTER_OTLP_ENDPOINT: http://collector:4318
```

`privileged: true` はeBPFのプログラムを読み込む権限のため、`pid: host` はホストのプロセスを見えるようにするための指定です。`OTEL_EBPF_BPF_CONTEXT_PROPAGATION` は、Perlから `rates` へのリクエストに `traceparent` を書き込ませる設定で、デフォルトは `disabled` です。2つの `volumes` は最初は付けておらず、付けるまでの経緯はこの章の後半で扱います。

## OBIが作ったスパン

3種類のリクエストを送ると、OBIはPerlのプロセスについて次のトレースを作りました。

```
# days=180&currency=USD
perl: 'GET /report'        SERVER   563.8ms  http.route=/report
  perl: 'in queue'         INTERNAL   0.3ms
  perl: 'processing'       INTERNAL 563.5ms
    perl: 'GET /rates'     CLIENT    21.1ms
      rates: 'GET /rates'  SERVER    20.5ms
```

サーバーのスパンの名前は `GET /report` で、属性には `http.route`、`url.path`、`url.query`、`server.port`、`network.protocol.version` が入っていました。5章のミドルウェアのスパンに無かった属性がそろっています。ただし、`server.address` はHostヘッダーの値ではなくプロセスの名前の `perl` でした。クライアントのスパンの `url.full` も `http://backend/rates?currency=USD` で、ポートが抜けています。`in queue` はリクエストが届いてから処理が始まるまでの待ち時間、`processing` は処理を始めてから応答を返すまでの時間を表す区間です。

`processing` の563.5msのうち、HTTPクライアントの区間は21.1msです。残りの540ms余りがPerlのプロセスの中で使われたことまでは分かります。ただし、それが集計処理だったことは分かりません。OBIはプロセスの外から通信を見ているので、5章の `aggregate` のようなプロセスの中の区間は作れないからです。

OBIのスパンのリソースは、`service.name` が `perl`、`telemetry.sdk.language` が `generic` でした。コンテナのプロセスには `OTEL_SERVICE_NAME=report` を設定してあり、`/proc` から読むとその値が入っていました。OBIのドキュメントの[サービス名の決め方](https://opentelemetry.io/docs/zero-code/obi/configure/service-discovery/#override-service-name-and-namespace)では、計装対象のプロセスやコンテナの `OTEL_SERVICE_NAME` を最初の手がかりにするとしています。今回はそうなりませんでした。原因は調べていません。このままでは、同じホストで動くPerlのサービスはすべて `perl` という名前になります。

応答時間は、計装していないときとほとんど変わりませんでした。3種類のリクエストを3回ずつ送ると、45〜48ms、565ms、627〜628msかかりました。2章の43〜45ms、562ms、623〜626msとの差は数ミリ秒です。

## 伝搬が無効になる条件

最初は `volumes` を付けずに起動しました。Perlの中のスパンは作られたのに、`rates` のスパンはどれもトレースの根になり、Perlのスパンとつながりませんでした。OBIのログには、次のWARNとERRORが出ていました。

```
level=WARN msg="kernel misreports ioctl(FIONREAD) for sockets in a sockhash (kernel commit 929e30f93125, present in 6.6.128+, 6.12.75+, 6.18.14+ and 6.19+); enabling BPF compensation for tracked sockets" component=tpinjector
level=ERROR msg="context propagation is disabled: the BPF compensation is ineffective (attach failed or blocked?). ..." component=tpinjector
```

OBIは、ソケットの受信済みバイト数を返す `ioctl(FIONREAD)` についてLinuxカーネルの不具合を検出していました。一部のカーネルでは、OBIがソケットをeBPFの仕組み（sockhash）に登録すると、この値が正しく返らなくなります。sockhashは、OBIがヘッダーの書き込みに使う仕組みです。OBIは補正のためのeBPFプログラムを読み込み、補正が有効だと確かめられないときは伝搬そのものを止めます。アプリケーションの読み込みを壊さないようにするためです。ソースのコメントによれば、カーネルの不具合は2026年7月に報告され、数週間で修正されました[^fionread]。ただし、不具合は6.x系へのバックポートを通じて本番の環境に入り込んでいるとのことです。v1.0.0-rc.1でも同じERRORが出ました。

[^fionread]: OBIのv0.14.0の[`pkg/internal/ebpf/tpinjector/fionread_check.go`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.14.0/pkg/internal/ebpf/tpinjector/fionread_check.go)の冒頭のコメントにあります。2026年10月7日時点の状態です。

補正のプログラムは、`ioctl` のシステムコールのトレースポイントにアタッチされます。トレースポイントを使うにはtracefs（`/sys/kernel/tracing`）が必要です。ところが、コンテナの中からはホストのtracefsが見えていませんでした。`/sys/kernel/tracing` をマウントすると、ログは `FIONREAD compensation verified` に変わり、伝搬が有効になりました。

それでも、伝搬したのは一部のリクエストだけでした。HTTP::TinyのKeep-Aliveを切り（2章の `RATES_KEEP_ALIVE=0`）、リクエストのたびに新しい接続を張るようにしました。すると、103回のリクエストのうち伝搬したのは0回でした。Keep-Aliveを有効にしたままだと、103回すべてが伝搬しました。この場合は、OBIを起動する前に張られていた接続を使い続けていました。新しく作られたソケットを捕まえるのは、OBIがcgroupにアタッチしたeBPFのプログラム（sock_ops）です。コンテナの中からはホストのcgroupが見えていなかったので、新しい接続を捕まえられなかったと考えられます。`/sys/fs/cgroup` もマウントすると、新しい接続でも100回すべてが伝搬しました。

2つのマウントは、どちらもOBIのドキュメントに記載がありました。tracefsは[Securityのページ](https://opentelemetry.io/docs/zero-code/obi/security/#required-host-mount-for-context-propagation)にあり、影響を受けるカーネルで伝搬を使うための必須条件という扱いです。cgroupは[Distributed tracesのページ](https://opentelemetry.io/docs/zero-code/obi/distributed-traces/)の、KubernetesのDaemonSetの構成の説明にあります。マウントしないと一部のリクエストでコンテキストが伝搬されない、という注意書きです。筆者はどちらのマウントも付けずに、[Dockerでのセットアップ](https://opentelemetry.io/docs/zero-code/obi/setup/docker/)にあるComposeの例をもとに構成を作りました。この例は伝搬を有効にしておらず、マウントも含んでいません。伝搬を止めたOBIも、トレースそのものは作り続けるので要注意です。そのため、ログのERRORに気づかなければサービスをまたぐトレースが切れていることを見落としてしまいます。

## 同時リクエストでの親子の対応づけ

Perlのクライアントのスパンがサーバーのスパンの子になったのは、両方の通信が同じOSのスレッドで行われていたからです。OBIが親子を対応づける方法は、ドキュメントの[Trace context association](https://opentelemetry.io/docs/zero-code/obi/context-propagation/)で説明されています。Go、Node.js、Java（仮想スレッドを含む）、uvloopで動くPythonのasyncio、RubyのPuma、NGINXには、それぞれのランタイムに合わせた仕組みがあります。それ以外の言語で頼るのは、言語に依存しない手がかりです。同じOSのスレッドが受信と送信をしているか、子のスレッドやプロセスから送信しているか、リクエストのスレッドが接続の準備をしてから別のワーカースレッドが送信を終えたかを見ます。同じページのLimitationsは、イベントループのフレームワークがこれらの仕組みの外で処理を受け渡すと、親子の対応づけを逃すことがあると書いています。

この手がかりは、1つのスレッドが1つのリクエストを最後まで処理するサーバーでは正しく働くはずです。逆に、1つのスレッドが複数のリクエストを並行して進めるイベントループのサーバーでは、親子の対応づけを誤るはずです。そこで3種類のPSGIサーバーにそれぞれ8並列で400回のリクエストを送り、OBIのスパンの親子関係を数えました。イベントループの[Twiggy](https://metacpan.org/pod/Twiggy)では、[AnyEvent::HTTP](https://metacpan.org/pod/AnyEvent::HTTP)で `rates` を呼ぶ非同期版のアプリケーションを使っています。

| サーバー | 子のクライアントが1つだけのサーバースパン | 親のないクライアントスパン | `rates` への伝搬 |
| --- | --- | --- | --- |
| HTTP::Server::PSGI（単一プロセス） | 403/403 | 0 | 400/400 |
| Starman（4ワーカー） | 403/403 | 0 | 400/400 |
| Twiggy（イベントループ） | 69/403 | 193 | 403/403 |
| Twiggy（イベントループ、1並列） | 103/103 | 0 | 103/103 |

件数には、測定の直前に送った確認用の3回のリクエストを含む場合があり、400と403が混在しています[^count]。

[^count]: Collectorが保存したデータから数えました。数えたのは、Perlのサーバースパンごとの子孫にあるクライアントスパンの数、どのサーバースパンの子孫にもないクライアントスパンの数、親がPerlのクライアントスパンになっている `rates` のスパンの数です。

予想どおりの結果でした。単一プロセスのサーバーとpreforkのStarmanでは、どのサーバースパンも子のクライアントスパンがちょうど1つでした。Twiggyでは、子のクライアントスパンを持たないサーバースパンが296本、2本以上持つものが38本ありました。どのサーバースパンにもつながらないクライアントスパンは193本でした。同じTwiggyでも、1並列で送るとすべて正しく対応づきました。対応づけを誤る原因は、イベントループで複数のリクエストを並行して処理していることです。

![OBIが観測する位置](/images/20261128-obi-observation-points.png)
*図1: OBIが観測する位置。実線はHTTPのリクエスト、紫の破線はeBPFのプログラムが読み書きする箇所、灰の破線はOBIへのデータの受け渡しを表す。OBIはPerlのプロセスが受けるHTTPと送るHTTPをカーネルの側で読み、同じOSのスレッドで起きた受信と送信を親子にする。送信には `traceparent` を書き込む。イベントループでは1つのスレッドが複数のリクエストの受信と送信を交互に行うので、どの受信がどの送信の親なのかを決められない*

Twiggyでも、`rates` への伝搬そのものは403件すべてで成立していました。Goのスパンの親は、Perlのクライアントのスパンです。ただし、そのクライアントのスパンが正しいサーバーのスパンの下にあるとは限りません。OBIで観測したTwiggyのトレースは、Perlのところで切れるか、別のリクエストのトレースにつながります。
