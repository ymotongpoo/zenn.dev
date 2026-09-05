---
title: "OBIを動かしてGrafanaで見る"
---

前章でOBIの生い立ちとパイプラインを見ました。ここで一度、実際に動かします。Goで書いた2つのHTTPサービスをOBIに計装させ、取れたトレースとメトリクスをGrafanaで見るところまでを通します。アプリのソースコードは1行も変えませんし、OpenTelemetryのSDKも入れません。10章から13章で扱う4つの難所は、ここで見えるもの一つひとつを、OBIがどうやって実現しているのかという話です。

## 用意するもの

OBIはLinux専用です。カーネル5.8以降でBTFが有効になっていること、CPUが `amd64` か `arm64` であること、そしてeBPFプログラムをロードできる権限が要ります。手元にDockerとDocker Composeがあれば、ほかに用意するものはありません。

難所4のコンテキスト伝搬まで試すなら、もう1つ条件があります。カーネルのlockdownモードが無効であることです。OBIリポジトリの [`SUPPORT_MATRIX.md`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/main/SUPPORT_MATRIX.md) は、この条件を次のように書いています。

> On Linux 5.10 and later, OBI requires effective `CAP_SYS_ADMIN` and kernel lockdown mode `[none]` to use `bpf_probe_write_user`.
>
> （Linux 5.10以降で `bpf_probe_write_user` を使うには、実効セットに `CAP_SYS_ADMIN` があること、そしてカーネルのlockdownモードが `[none]` であることが必要である。）

手元の状態は次で確かめられます。

```console
$ cat /sys/kernel/security/lockdown
[none] integrity confidentiality
```

角括弧が `[none]` に付いていれば使えます。Secure Bootが有効な環境では `[integrity]` になっていることがあり、その場合はOBIがアプリのメモリに書き込む経路が塞がれます。何が塞がれるのかは、この章の後半で実際に動かしてから見ます。

## 計装対象のGoアプリ

`frontend` と `backend` の2つを作ります。`frontend` は `/order` を受けると `backend` の `/inventory` を呼び、その結果を返します。

```go
package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
)

func main() {
	backend := os.Getenv("BACKEND_URL")

	http.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		io.WriteString(w, "ok\n")
	})

	http.HandleFunc("/order", func(w http.ResponseWriter, _ *http.Request) {
		resp, err := http.Get(backend + "/inventory")
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()

		body, err := io.ReadAll(resp.Body)
		if err != nil || resp.StatusCode != http.StatusOK {
			http.Error(w, "inventory lookup failed", http.StatusBadGateway)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"order":     "accepted",
			"inventory": json.RawMessage(body),
		})
	})

	log.Fatal(http.ListenAndServe(":8080", nil))
}
```

`backend` は在庫を返すふりをします。数十ミリ秒眠り、10回に1回は500を返す。所要時間とエラー率に幅を持たせて、あとで見るメトリクスに変化が出るようにするためです。受け取ったリクエストの `Traceparent` ヘッダは、そのままレスポンスに載せます。`frontend` も `backend` も、このヘッダを自分では設定しません。

```go
package main

import (
	"encoding/json"
	"log"
	"math/rand"
	"net/http"
	"time"
)

func main() {
	http.HandleFunc("/inventory", func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(time.Duration(20+rand.Intn(80)) * time.Millisecond)

		if rand.Intn(10) == 0 {
			http.Error(w, "inventory unavailable", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"sku":         "sku-42",
			"stock":       7,
			"traceparent": r.Header.Get("Traceparent"),
		})
	})

	log.Fatal(http.ListenAndServe(":8081", nil))
}
```

どちらの `go.mod` も標準ライブラリしか要求しません。

```
module example.com/frontend

go 1.26
```

`Dockerfile` は2つとも同じ形です。`frontend` のものを示します。`backend` のほうは `frontend` という語を4か所置き換えるだけです。

```dockerfile
FROM cgr.dev/chainguard/go:latest AS build
WORKDIR /src
COPY go.mod main.go ./
RUN CGO_ENABLED=0 go build -o /out/frontend .

FROM cgr.dev/chainguard/static:latest
COPY --from=build /out/frontend /frontend
ENTRYPOINT ["/frontend"]
```

ビルドには[Chainguardのgoイメージ](https://images.chainguard.dev/directory/image/go/overview)を使いました。公開カタログから引けるタグは `latest` だけで、バージョンを固定したいならダイジェストを指定します。この `latest` は今日の時点でGo 1.27.1です。

`-ldflags="-s -w"` を付けていないのは意図的です。付けるとどうなるかは14章で扱います。

## composeの組み立て

テレメトリの送り先には [`grafana/otel-lgtm`](https://github.com/grafana/docker-otel-lgtm) を使います。Grafana、Prometheus、Tempo、OpenTelemetry Collectorが1つのイメージに入っていて、設定ファイルなしで起動します。OBIはここへOTLPで送るだけで済みます。

![ハンズオンの構成](/images/20260820-handson-topology.png)
*図1: 実線の矢印はリクエストとテレメトリの流れ、破線はOBIが計装対象を観測して書き込む関係を表す。OBIは2つのサービスをそれぞれ直接見ている。`pid: host` でホストのプロセス空間を見ているので、アプリのコンテナには何も入れない。Grafanaスタックの4つは `grafana/otel-lgtm` という1つのコンテナに入っている。*

```yaml
services:
  frontend:
    build: ./frontend
    environment:
      OTEL_SERVICE_NAME: frontend
      BACKEND_URL: http://backend:8081
    ports:
      - "8080:8080"

  backend:
    build: ./backend
    environment:
      OTEL_SERVICE_NAME: backend

  obi:
    image: otel/ebpf-instrument:v0.13.0
    privileged: true
    pid: host
    environment:
      OTEL_EBPF_AUTO_TARGET_EXE: "/{frontend,backend}"
      OTEL_EBPF_TRACE_PRINTER: text
      OTEL_EBPF_BPF_CONTEXT_PROPAGATION: disabled
      OTEL_EBPF_METRICS_FEATURES: application
      OTEL_EBPF_METRICS_INTERVAL: 15s
      OTEL_EXPORTER_OTLP_ENDPOINT: http://lgtm:4317
      OTEL_EXPORTER_OTLP_PROTOCOL: grpc
    volumes:
      - /sys/kernel/security:/sys/kernel/security:ro
      - /sys/fs/bpf:/sys/fs/bpf:rw
    depends_on: [frontend, backend, lgtm]

  lgtm:
    image: grafana/otel-lgtm:0.32.1
    ports:
      - "3000:3000"
```

`privileged: true` と `pid: host` の2つは外せません。前者はeBPFプログラムのロードに要る権限で、後者はホストのプロセスを見えるようにする指定です。

マウントしている2つのパスにも役割があります。`/sys/kernel/security` はlockdownの状態を読むため、`/sys/fs/bpf` はeBPFマップをピン留めするためです。`/sys/fs/bpf` を渡さないと警告が出て、ピン留めしたマップを前提とする機能が無効になります。

OBI側の環境変数は7つあり、うち2つはOpenTelemetry標準の変数をそのまま使っています。網羅的な一覧は[設定リファレンス](https://opentelemetry.io/docs/zero-code/obi/configure/options/)にあります。

| 環境変数 | 意味 |
|---|---|
| `OTEL_EBPF_AUTO_TARGET_EXE` | 実行ファイルのパスをグロブで指定して計装対象を選ぶ |
| `OTEL_EBPF_TRACE_PRINTER` | 取れたスパンを標準出力に印字する。デフォルトは `disabled` |
| `OTEL_EBPF_BPF_CONTEXT_PROPAGATION` | 難所4のコンテキスト伝搬。デフォルトは `disabled` で、`headers`、`tcp`、`all` から選ぶ |
| `OTEL_EBPF_METRICS_FEATURES` | 出すメトリクスの種類。`application` がHTTPやgRPCのリクエスト数、エラー、所要時間 |
| `OTEL_EBPF_METRICS_INTERVAL` | メトリクスの送信間隔。デフォルトは60秒 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 送信先 |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | 送信に使うプロトコル。ここではgRPC |

`OTEL_SERVICE_NAME` を計装対象のコンテナのほうに置いているのは、OBIが対象プロセスの環境変数からサービス名を読むからです。設定するのはOBIではなく、観測される側になります。

計装対象のグロブに使った波括弧は、複数のパスを1つのパターンにまとめる記法です。実行ファイルは `scratch` に近い最小のイメージへ1つだけ置いているので、パスは `/frontend` と `/backend` になります。

対象の選び方には、ポート番号で選ぶ `OTEL_EBPF_OPEN_PORT` もあります。ただしポート `8080` をホストに公開していると、そのポートを開いているのはアプリのプロセスだけではありません。Dockerがポート転送に使う `docker-proxy` も条件に合ってしまい、計装対象に混ざります。実行ファイルのパスを使っているのはそのためです。

## 計装が始まった印

`docker compose up -d --build` で起動します。ビルドが終わってOBIが対象を見つけるまで数秒かかるので、まずOBIのログを見ます。行頭のコンテナ名を省くため `--no-log-prefix` を付けます。なお、以降のログはいずれも行頭のタイムスタンプを落として示します。

```console
$ docker compose logs --no-log-prefix obi
```

```
level=INFO msg="OpenTelemetry eBPF Instrumentation" Version=v0.13.0 Revision=3cc1986 "OpenTelemetry SDK Version"=1.46.0
level=INFO msg="configuration loaded" version=v1
level=WARN msg="timed out while waiting for Cloud metadata. Ignoring" component=meta.NodeMeta.otelNodeFetcher detector=azurevm.ResourceDetector
level=WARN msg="timed out while waiting for Cloud metadata. Ignoring" component=meta.NodeMeta.otelNodeFetcher detector=ec2.resourceDetector
level=INFO msg="starting Application Observability mode"
level=INFO msg="using hostname" component=traces.ReadDecorator function=instance_ID_hostNamePIDDecorator hostname=edb90d2694f5
level=INFO msg="using hostname" component=traces.ReadDecorator function=instance_ID_hostNamePIDDecorator hostname=edb90d2694f5
level=INFO msg="Starting main node" component=obi.Instrumenter
level=INFO msg="instrumenting process" component=discover.traceAttacher cmd=/backend pid=74712 ino=2261228 type=go service=backend logenricher=false
level=INFO msg="instrumenting process" component=discover.traceAttacher cmd=/frontend pid=74719 ino=2261238 type=go service=frontend logenricher=false
```

クラウドのメタデータに関する2つの警告は、AWSやAzureの上ではないので取得できなかったというだけで、無視して問題ありません。

読みたいのは最後の2行です。`instrumenting process` が、8章で見たパイプラインの1段目と2段目が終わった印になります。`type=go` は、ELFを解析した結果このバイナリがGoだと判定されたことを意味します。

ここでリクエストを1つ投げると、`backend` が受け取った `Traceparent` ヘッダが空のまま返ってきます。

```console
$ curl -s localhost:8080/order
{"inventory":{"sku":"sku-42","stock":7,"traceparent":""},"order":"accepted"}
```

このリクエストが通ったあと、OBIのログには `OTEL_EBPF_TRACE_PRINTER` が印字したスパンが並びます。以下では `contentLen` と `responseLen` の欄も落としてあります。

```
(83.742346ms[83.678157ms]) HTTP(subType=0) 200 GET /inventory(/inventory) [172.18.0.3 as 172.18.0.3:39986]->[172.18.0.4 as backend:8081] svc=[backend go] traceparent=[00-96b553ab888fe7c26bd049ac81064eea-43d84c631513a950[998c4a1edfbd832f]-01]
(84.319112ms[84.319112ms]) HTTPClient(subType=0) 200 GET /inventory(/inventory) [172.18.0.3 as frontend:39986]->[172.18.0.4 as backend:8081:8081] svc=[frontend go] traceparent=[00-96b553ab888fe7c26bd049ac81064eea-998c4a1edfbd832f[f8198df6160ef2f4]-01]
(84.978321ms[84.928271ms]) HTTP(subType=0) 200 GET /order(/order) [172.18.0.1 as 172.18.0.1:57560]->[172.18.0.3 as frontend:8080] svc=[frontend go] traceparent=[00-96b553ab888fe7c26bd049ac81064eea-f8198df6160ef2f4[0000000000000000]-01]
```

見るのは行末の `traceparent=[00-<トレースID>-<スパンID>[<親スパンID>]-01]` だけで足ります。3行とも同じトレースID `96b553ab...` を持っています。いちばん下の `/order` の親が全ゼロ。これがルートスパンです。そのスパンID `f8198df6160ef2f4` が真ん中の `HTTPClient` の親になり、`HTTPClient` のスパンID `998c4a1edfbd832f` がいちばん上の `backend` の `/inventory` の親になっています。

2つのプロセスにまたがった親子関係が、どちらのアプリにも一行も書かずに出ています。再ビルドも再起動もしていません。

## Tempoに届いたトレース

`http://localhost:3000` を開きます。`grafana/otel-lgtm` はデータソースを設定済みなので、ExploreでTempoを選べばすぐ検索できます。[TraceQL](https://grafana.com/docs/tempo/latest/traceql/) に `{ resource.service.name = "frontend" }` と入れて、出てきたトレースを1つ開きます。

![Tempoに届いたトレース](/images/20260820-handson-trace.png)
*図2: この図に矢印はない。横棒の長さが各スパンの所要時間を表す。7つのスパンが1本のトレースになり、`frontend` と `backend` の2サービスにまたがっている。*

さきほどログで見たのは3つのスパンでしたが、ここでは7つに増えています。足されたのは、サーバースパンごとにOBIが作る `in queue` と `processing` です。リクエストを受け付けてからハンドラが動き出すまでの待ち時間と、ハンドラの中で過ごした時間を分けています。ソケットを流れるバイト列だけを見ていてはこの区別は付きません。`net/http` の内部の関数にフックを置いているから取れる区別です。

`GET /inventory` は2回現れます。上が `frontend` のクライアント側、下が `backend` のサーバー側で、その差がネットワークの往復とクライアント側の処理にかかった時間です。

スパンに付いている属性のほうが、この章では大事です。`backend` のサーバースパンには `http.route=/inventory`、`http.request.method=GET`、`http.response.status_code=200`、`server.address=backend`、`server.port=8081` が並び、`frontend` のクライアントスパンには `url.full=http://backend:8081/inventory` が入っています。

これらの出どころは1つではありません。メソッドとURLは `http.Request` から、ステータスコードはレスポンスを書き出す側の構造体から、アドレスとポートは接続のファイル記述子から読み出しています。どれも構造体のどこにその値があるかを知っていなければ取れない値で、その位置をどうやって知るのかが難所3（12章）の話になります。

## traceparentが書き込まれる条件

トレースは1本につながっていたのに、`backend` が受け取った `Traceparent` ヘッダは空でした。

```console
$ curl -s localhost:8080/order
{"inventory":{"sku":"sku-42","stock":7,"traceparent":""},"order":"accepted"}
```

つまりこのとき、ネットワークには `traceparent` が一切流れていません。トレースがつながったのは、`frontend` と `backend` を同じOBIが観測していたからです。OBIは自分が見ている送信と受信を内部で突き合わせて、ヘッダを書かずに親子関係を復元できます。

OBIはこれを**ブラックボックス伝搬**と呼んでいます。ただしこの経路は、相手も同じOBIの視野に入っているあいだしか働きません。別のホストにいるサービスや、SDKで計装された相手には届かないわけです。

そこで `compose.yaml` を書き換えます。

```yaml
      OTEL_EBPF_BPF_CONTEXT_PROPAGATION: all
```

OBIだけ入れ替えて、同じリクエストをもう一度投げます。

```console
$ docker compose up -d obi
$ curl -s localhost:8080/order
{"inventory":{"sku":"sku-42","stock":7,"traceparent":"00-5e259659c14e5b49c67b5375b2016329-47f01333666f0e07-01"},"order":"accepted"}
```

`backend` のハンドラが `r.Header.Get("Traceparent")` で読んだ値です。`frontend` のコードは、このヘッダをどこにも設定していません。`http.Get` を呼んだだけです。にもかかわらず `backend` に届いている。あいだで誰かが、`frontend` のプロセスのメモリを書き換えて、送信直前のバッファに1行を挿し込んだことになります。

この文字列を書き込んでいるのは、`bufio.Writer` の非公開フィールドを外から書き換えるコードです[^cp-default]。それが13章で扱う難所4です。

[^cp-default]: この機能がデフォルトで無効なのは、他人のプロセスのメモリを書き換える以上、有効化を利用者の判断に委ねているからです。

## REDメトリクスとサービスグラフ

トレースだけでなく、リクエストの流量とエラー率と所要時間、いわゆる**RED**のメトリクスも届いています。負荷をかけ続けてから見ると分かりやすいので、しばらく回します。

```console
$ while true; do curl -s -o /dev/null localhost:8080/order; sleep 0.25; done
```

ExploreでPrometheusを選び、次のクエリを実行します。

```
sum by (service_name, http_route, http_response_status_code) (rate(http_server_request_duration_seconds_count[1m]))
```

![OBIが出したREDメトリクス](/images/20260820-handson-red-metrics.png)
*図3: 縦軸は毎秒あたりのリクエスト数を表す。系列はサービス名、ルート、ステータスコードの組で分かれる。*

`backend` が10回に1回返している500と、それを受けた `frontend` の502が、別々の系列として出ています。`frontend` の線と `backend` の線がほぼ重なっているのは、`/order` 1回につき `/inventory` をちょうど1回呼んでいるからです。

ラベルはパスそのものではなく `http_route` です。URLのパスをそのままラベルにすれば、IDを含むパスでは系列が際限なく増える。OBIはこれを避けるための仕組みを別に持っていて、設定でルートのパターンを与えればそれに合わせ、与えなければヒューリスティックが働きます。デフォルトのヒューリスティックは、サービスごとに同じ位置のセグメントの種類が10を超えると、そこをワイルドカードに置き換えます。今回は静的なパスしかないので、`/inventory` と `/order` がそのままの形で出ています。

メトリクスの名前は、[OpenTelemetryのセマンティック規約](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/)にある名前をPrometheus形式に変換したものです。

| メトリクス名 | 内容 |
|---|---|
| `http_server_request_duration_seconds` | サーバー側の所要時間のヒストグラム |
| `http_client_request_duration_seconds` | クライアント側の所要時間のヒストグラム |
| `http_server_request_body_size_bytes` | サーバーが受け取った本文のサイズ |
| `http_client_response_body_size_bytes` | クライアントが受け取った本文のサイズ |

同じトレースのデータから、サービス間の呼び出し関係も組み立てられます。ExploreのTempoでQuery typeを「Service Graph」に切り替えます。

![サービスグラフ](/images/20260820-handson-service-graph.png)
*図4: 矢印は呼び出しの向き（呼ぶ側から呼ばれる側へ）を表す。円を囲む線の色は成功と失敗の比率、円の中の数値は所要時間と毎秒のリクエスト数を示す。*

`user` から `frontend` へ、`frontend` から `backend` への呼び出しが出ています。計装されていない呼び出し元は `user` としてまとめられます。この図はTempoがスパンの親子関係から組み立てたもので、`OTEL_EBPF_METRICS_FEATURES` に `application_service_graph` を足せばOBI自身にもほぼ同じメトリクスを出させられますが、ここでは二重になるので使っていません。

## よくあるつまずき

この構成を手元で動かしたときに実際に出会ったものを挙げます。

`instrumenting process` の行が出ないときに、まず疑うのは対象の選び方です。`OTEL_EBPF_AUTO_TARGET_EXE` が取るのはグロブ1つだけで、カンマで区切って2つ書いても、その全体が1つのパターンとして扱われます。`"*/frontend,*/backend"` と書くとどちらのパスにも一致せず、エラーも出ないまま何も計装されません。複数の実行ファイルを選ぶなら、`"/{frontend,backend}"` のように波括弧で並べます。なお、先頭のワイルドカード自体は問題になりません。`"*/frontend"` は `/frontend` に一致します。

`type=generic` と出ているなら、Goバイナリだと判定されていません。`go version -m` がそのバイナリを読めるか、`readelf -S` に `.gopclntab` があるかを確かめます。8章で見た2つの経路のうち言語非依存のほうへ回されているので、関数レベルの計装は動いていない。

メトリクスがPrometheusに現れないときは、送信間隔を疑います。ここでは `OTEL_EBPF_METRICS_INTERVAL` を15秒にしているので最初の系列が出るまで15秒かかり、この指定を外すとデフォルトの60秒になります。

コンテキスト伝搬を有効にすると、環境によっては次のようなログが出ます。

```
level=WARN msg="kernel misreports ioctl(FIONREAD) for sockets in a sockhash (kernel commit 929e30f93125, present in 6.6.128+, 6.12.75+, 6.18.14+ and 6.19+); enabling BPF compensation for tracked sockets" component=tpinjector
level=ERROR msg="context propagation is disabled: the BPF compensation is ineffective (attach failed or blocked?). This kernel misreports ioctl(FIONREAD) for sockets in a sockhash (kernel commit 929e30f93125), or could not be verified to report it correctly, so keeping propagation enabled would risk making applications sizing reads via FIONREAD stall or truncate transfers" component=tpinjector
```

これは13章で扱う2つの伝搬経路のうち、`sk_msg` を使う経路2が無効になったという意味です。アプリのバッファに `bpf_probe_write_user` で書き込む経路1は動き続けるので、`backend` の側で `Traceparent` が読めているなら伝搬自体は成立しています。ERRORという語感に反して、Goのアプリだけを相手にしているかぎり実害はありません。実際、本章の実行結果はこのログが出ている環境で取ったものです。

lockdownが `[integrity]` の環境では、逆に経路1のほうが使えません。経路2が動く環境ならそちらが引き継ぎますが、両方とも無効なら `Traceparent` は空のまま。同じOBIが両側を見ている範囲でしかトレースはつながりません。

## この章から難所へ持っていくもの

| この章で見えたもの | 対応する難所 |
|---|---|
| 関数の入口と出口の時刻から所要時間が取れている | 難所1（10章）。Goでは関数の出口を捕まえる定石が使えない |
| メソッドやURL、ステータスコードが引数から読めている | 難所2（11章）。引数はスタックではなくレジスタに乗っている |
| 構造体のどこにそのフィールドがあるかをOBIが知っている | 難所3（12章）。位置はGoとライブラリのバージョンで変わる |
| `Traceparent` がアプリの知らないうちに書き込まれた | 難所4（13章）。プロセスをまたいで文脈を運ぶ |

- OBIは対象プロセスの外側にいる独立したプログラムであり、アプリのコードにもビルドにも手を入れない。
- 同じOBIが両側を見ているあいだは、ヘッダを書かなくてもトレースはつながる。プロセスの外へ文脈を運ぶには、コンテキスト伝搬を明示的に有効にする。
