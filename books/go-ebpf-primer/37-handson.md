---
title: "OBIを動かしてGrafanaで見る"
---

前章でOBIの生い立ちとパイプラインを見ました。ここで一度、実際に動かします。Goで書いた2つのHTTPサービスをOBIに計装させ、取れたトレースとメトリクスをGrafanaで見るところまでを通します。アプリのソースコードは1行も変えませんし、OpenTelemetryのSDKも入れません。10章から13章で扱う4つの難所は、ここで見えるもの一つひとつを、OBIがどうやって実現しているのかという話です。

## 用意するもの

OBIはLinux専用です。カーネル5.8以降でBTFが有効になっていること、CPUが `amd64` か `arm64` であること、そしてeBPFプログラムをロードできる権限が要ります。本章の実行結果は、Linux 7.0.0-31-generic（x86_64）、Docker 29.0.0、Docker Compose v2.40.3、OBI `v0.13.0`、`grafana/otel-lgtm:0.32.1` で確かめたものです。

難所4のコンテキスト伝搬まで試すなら、もう1つ条件があります。カーネルのlockdownモードが無効であることです。OBIのサポートマトリクスは次のように書いています。

> On Linux 5.10 and later, OBI requires effective `CAP_SYS_ADMIN` and kernel lockdown mode `[none]` to use `bpf_probe_write_user`.
>
> （Linux 5.10以降で `bpf_probe_write_user` を使うには、実効的な `CAP_SYS_ADMIN` とカーネルのlockdownモード `[none]` が必要である。）

手元の状態は次で確かめられます。

```console
$ cat /sys/kernel/security/lockdown
[none] integrity confidentiality
```

角括弧が `[none]` に付いていれば使えます。Secure Bootが有効な環境では `[integrity]` になっていることがあり、その場合は後述するヘッダ注入が動きません。

macOSやWindowsのDocker DesktopはLinuxのVMの上でコンテナを動かすので、`pid: host` が指すのはそのVMのプロセス空間になります。本章の構成なら計装対象もそのVMの中にいるため原理的には動きますが、筆者が確かめたのはLinuxホストだけです。

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

`backend` は在庫を返すふりをします。数十ミリ秒眠り、10回に1回は500を返します。レイテンシとエラー率に幅を持たせて、あとで見るメトリクスに変化が出るようにするためです。

受け取ったリクエストの `Traceparent` ヘッダを、そのままレスポンスに載せているところが要点です。アプリ自身は何も設定していないので、ここが空でなくなったら、それはOBIが外から書き込んだことになります。

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

`Dockerfile` は2つとも同じ形です。`frontend` のものを示します。`backend` は3か所の名前を差し替えるだけです。

```dockerfile
FROM golang:1.26 AS build
WORKDIR /src
COPY go.mod main.go ./
RUN CGO_ENABLED=0 go build -o /out/frontend .

FROM scratch
COPY --from=build /out/frontend /frontend
ENTRYPOINT ["/frontend"]
```

`-ldflags="-s -w"` を付けていないのは意図的です。付けるとどうなるかは14章で扱います。

## composeにOBIとGrafanaを足す

バックエンドには `grafana/otel-lgtm` を使います。Grafana、Prometheus、Tempo、Loki、Pyroscope、そしてOpenTelemetry Collectorが1つのイメージに入っていて、設定ファイルなしで起動します。OBIはここへOTLPで送るだけで済みます。

![ハンズオンの構成](/images/20260820-handson-topology.png)
*図1: 実線の矢印はリクエストとテレメトリの流れ、破線はOBIが計装対象を観測して書き込む関係を表す。OBIは `pid: host` でホストのプロセス空間を見ているので、アプリのコンテナの中に何かを入れる必要はない。*

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

`privileged: true` と `pid: host` は避けて通れません。前者はeBPFプログラムのロードに要る権限、後者はホストのプロセスを見えるようにする指定です。`/sys/kernel/security` はlockdownの状態を読むため、`/sys/fs/bpf` はeBPFマップをピン留めするために渡します。後者を渡さないと警告が出て、プロファイルとの相関のようにピン留めしたマップを前提とする機能が無効になります。

OBI側の環境変数を順に見ます。

| 環境変数 | 意味 |
|---|---|
| `OTEL_EBPF_AUTO_TARGET_EXE` | 実行ファイルのパスをグロブで指定して計装対象を選ぶ |
| `OTEL_EBPF_TRACE_PRINTER` | 取れたスパンを標準出力に印字する。デフォルトは `disabled` |
| `OTEL_EBPF_BPF_CONTEXT_PROPAGATION` | 難所4のコンテキスト伝搬。デフォルトは `disabled` で、`headers`、`tcp`、`all` から選ぶ |
| `OTEL_EBPF_METRICS_FEATURES` | 出すメトリクスの種類。`application` がHTTPやgRPCのRED |
| `OTEL_EBPF_METRICS_INTERVAL` | メトリクスの送信間隔。デフォルトは60秒 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 送信先。OpenTelemetry標準の変数をそのまま使う |

`OTEL_SERVICE_NAME` を計装対象のコンテナのほうに置いているのは、OBIが対象プロセスの環境変数からサービス名を読むからです。設定するのはOBIではなく、観測される側です。

計装対象の選び方には、ポート番号で選ぶ `OTEL_EBPF_OPEN_PORT` もあります。ただしポート `8080` をホストに公開していると、そのポートを開いているのはアプリのプロセスだけではありません。Dockerがポート転送に使う `docker-proxy` も条件に合ってしまい、計装対象に混ざります。ここで実行ファイルのパスを使っているのはそのためです。

## まずログで確かめる

起動します。

```console
$ docker compose up -d --build
```

OBIのログを見ます。行頭のコンテナ名を省くため `--no-log-prefix` を付けます。

```console
$ docker compose logs --no-log-prefix obi
```

```
level=INFO msg="OpenTelemetry eBPF Instrumentation" Version=v0.13.0 Revision=3cc1986 "OpenTelemetry SDK Version"=1.46.0
level=INFO msg="configuration loaded" version=v1
level=WARN msg="timed out while waiting for Cloud metadata. Ignoring" component=meta.NodeMeta.otelNodeFetcher detector=azurevm.ResourceDetector
level=WARN msg="timed out while waiting for Cloud metadata. Ignoring" component=meta.NodeMeta.otelNodeFetcher detector=ec2.resourceDetector
level=INFO msg="starting Application Observability mode"
level=INFO msg="using hostname" component=traces.ReadDecorator function=instance_ID_hostNamePIDDecorator hostname=7f2840dcc841
level=INFO msg="using hostname" component=traces.ReadDecorator function=instance_ID_hostNamePIDDecorator hostname=7f2840dcc841
level=INFO msg="Starting main node" component=obi.Instrumenter
level=INFO msg="instrumenting process" component=discover.traceAttacher cmd=/backend pid=48946 ino=2244762 type=go service=backend logenricher=false
level=INFO msg="instrumenting process" component=discover.traceAttacher cmd=/frontend pid=48953 ino=2241281 type=go service=frontend logenricher=false
```

行頭のタイムスタンプは省いてあります。クラウドのメタデータに関する2つの警告は、AWSやAzureの上ではないので取得できなかったというだけで、無視して問題ありません。`instrumenting process` の行が、8章で見たパイプラインの1段目と2段目が終わった印です。`type=go` は、ELFを解析した結果このバイナリがGoだと判定されたことを意味します。ここで `type=generic` になっていたら、8章で見た2つの経路のうち言語非依存のほうへ回されていて、関数レベルの計装は動いていません。

リクエストを1つ投げます。

```console
$ curl -s localhost:8080/order
{"inventory":{"sku":"sku-42","stock":7,"traceparent":""},"order":"accepted"}
```

そしてもう一度ログを見ると、`TRACE_PRINTER` が印字したスパンが並んでいます。以下は読みやすさのために、行頭のタイムスタンプと `contentLen` / `responseLen` の欄を落としてあります。

```
(56.724239ms[56.654508ms]) HTTP(subType=0) 200 GET /inventory(/inventory) [172.18.0.3 as 172.18.0.3:53270]->[172.18.0.4 as backend:8081] svc=[backend go] traceparent=[00-a15a17ffc2c7318a249a63dba8492257-7169c1e682171601[2e1050c650e79e22]-01]
(57.501556ms[57.501556ms]) HTTPClient(subType=0) 200 GET /inventory(/inventory) [172.18.0.3 as frontend:53270]->[172.18.0.4 as backend:8081:8081] svc=[frontend go] traceparent=[00-a15a17ffc2c7318a249a63dba8492257-2e1050c650e79e22[011c6819a3629b9c]-01]
(58.296225ms[58.208121ms]) HTTP(subType=0) 200 GET /order(/order) [172.18.0.1 as 172.18.0.1:34374]->[172.18.0.3 as frontend:8080] svc=[frontend go] traceparent=[00-a15a17ffc2c7318a249a63dba8492257-011c6819a3629b9c[0000000000000000]-01]
```

行末の `traceparent=[00-<トレースID>-<スパンID>[<親スパンID>]-01]` を縦に読むと、3行とも同じトレースID `a15a17ff...` を持っています。いちばん下の `/order` の親が全ゼロ、つまりこれが根です。その根のスパンID `011c6819a3629b9c` が真ん中の `HTTPClient` の親になり、`HTTPClient` のスパンID `2e1050c650e79e22` がいちばん上の `backend` の `/inventory` の親になっています。2つのプロセスにまたがって、親子関係がつながっています。

アプリは再ビルドも再起動もしていません。これが1章で述べたゼロコード計装です。

## Grafanaでトレースを見る

`http://localhost:3000` を開きます。`grafana/otel-lgtm` はデータソースを設定済みなので、ExploreでTempoを選べばすぐ検索できます。TraceQLに `{ resource.service.name = "frontend" }` と入れて、出てきたトレースを1つ開きます。

![Tempoに届いたトレース](/images/20260820-handson-trace.png)
*図2: この図に矢印はない。横棒の長さが各スパンの所要時間を表す。7つのスパンが1本のトレースになり、`frontend` と `backend` の2サービスにまたがっている。*

7つのスパンのうち、`in queue` と `processing` はOBIが足したものです。リクエストを受け付けてからハンドラが動き出すまでの待ち時間と、ハンドラの中で過ごした時間を分けています。ソケットを流れるバイト列だけを見ていてはこの区別は付きません。`net/http` の内部の関数にフックを置いているからこそ出てくる情報で、8章で見た2つの経路のうち、Goだけが持つ関数レベルの計装の成果です。

`GET /inventory` が2回現れているのも見どころです。上が `frontend` のクライアント側、下が `backend` のサーバー側で、両者の差が通信にかかった時間になります。

スパンに付いている属性も見ておきます。`backend` のサーバースパンには `http.route=/inventory`、`http.request.method=GET`、`http.response.status_code=200`、`server.address=backend`、`server.port=8081` が並びます。`frontend` のクライアントスパンには `url.full=http://backend:8081/inventory` が入っています。どれも `http.Request` 構造体のフィールドから読み出した値で、その位置をどうやって知ったのかが難所3の話になります。

## traceparentが書き込まれる条件

さきほどの `curl` の結果に戻ります。トレースは1本につながっていたのに、`backend` が受け取った `Traceparent` ヘッダは空でした。

```console
$ curl -s localhost:8080/order
{"inventory":{"sku":"sku-42","stock":7,"traceparent":""},"order":"accepted"}
```

つまりこのとき、ネットワークには `traceparent` が一切流れていません。ではなぜトレースがつながったのかというと、`frontend` と `backend` を同じOBIが観測していたからです。OBIは自分が見ている送信と受信を内部で突き合わせて、ヘッダを書かずに親子関係を復元できます。OBIはこれをブラックボックス伝搬と呼んでいて、設定にはテスト用に無効化する `OTEL_EBPF_BPF_DISABLE_BLACK_BOX_CP` が用意されています。ただしこの経路は、相手も同じOBIの視野に入っているあいだしか働きません。別のホストにいるサービスや、SDKで計装された相手には届かないわけです。

そこで `compose.yaml` を書き換えます。

```yaml
      OTEL_EBPF_BPF_CONTEXT_PROPAGATION: all
```

OBIだけ入れ替えて、同じリクエストをもう一度投げます。

```console
$ docker compose up -d obi
$ curl -s localhost:8080/order
{"inventory":{"sku":"sku-42","stock":7,"traceparent":"00-205724b9afb126a7cfdfcb294b6fc49b-3a2b51c99497a120-01"},"order":"accepted"}
```

`backend` のハンドラが `r.Header.Get("Traceparent")` で読んだ値です。`frontend` のコードは、このヘッダをどこにも設定していません。`http.Get` を呼んだだけです。にもかかわらず `backend` に届いている。あいだで誰かが、`frontend` のプロセスのメモリを書き換えて、送信直前のバッファに1行を挿し込んだことになります。

それをやっているのが、13章で扱う難所4です。`bufio.Writer` の非公開フィールドを外から書き換える話が、この16進数の並びの正体です。

なお、この機能がデフォルトで無効なのは、プロセスのメモリを書き換える以上、有効化を利用者の判断に委ねているからです。

## メトリクスを見る

トレースだけでなく、RED（リクエストの流量、エラー率、所要時間）のメトリクスも出ています。負荷をかけ続けてから見ると分かりやすいので、しばらく回します。

```console
$ while true; do curl -s -o /dev/null localhost:8080/order; sleep 0.25; done
```

ExploreでPrometheusを選び、次のクエリを実行します。

```
sum by (service_name, http_route, http_response_status_code) (rate(http_server_request_duration_seconds_count[1m]))
```

![OBIが出したREDメトリクス](/images/20260820-handson-red-metrics.png)
*図3: 縦軸は毎秒あたりのリクエスト数を表す。サービス名、ルート、ステータスコードごとに4つの系列が出ているが、`frontend` と `backend` は同じ回数だけ呼ばれるので、上下2本ずつがほぼ重なっている。下側が500と502である。*

`backend` が10回に1回返している500と、それを受けた `frontend` の502が、別々の系列として出ています。`frontend` の線と `backend` の線がほぼ重なっているのは、`/order` 1回につき `/inventory` をちょうど1回呼んでいるからです。ラベルが `http_route` として付いているのも見ておいてください。URLのパスをそのままラベルにすると、IDを含むパスでは系列の数が際限なく増えます。OBIはこれを避けるための仕組みを別に持っていて、設定でルートのパターンを与えればそれに合わせ、与えなければヒューリスティックが働きます。デフォルトのヒューリスティックは、サービスごとに同じ位置のセグメントの種類が10を超えると、そこをワイルドカードに置き換えます。今回は静的なパスしかないので、`/inventory` と `/order` がそのままの形で出ています。

出ているメトリクスの名前は、OpenTelemetryのセマンティック規約に沿ったものです。

| メトリクス名 | 内容 |
|---|---|
| `http_server_request_duration_seconds` | サーバー側の所要時間のヒストグラム |
| `http_client_request_duration_seconds` | クライアント側の所要時間のヒストグラム |
| `http_server_request_body_size_bytes` | サーバーが受け取った本文のサイズ |
| `http_client_response_body_size_bytes` | クライアントが受け取った本文のサイズ |

サービス間の呼び出し関係も見られます。ExploreのTempoでQuery typeを「Service Graph」に切り替えます。

![サービスグラフ](/images/20260820-handson-service-graph.png)
*図4: 矢印は呼び出しの向き（呼ぶ側から呼ばれる側へ）を表す。円を囲む線の色は成功と失敗の比率、円の中の数値は所要時間と毎秒のリクエスト数を示す。*

`user` から `frontend` へ、`frontend` から `backend` への呼び出しが出ています。この図はTempoがスパンの親子関係から組み立てたもので、OBI自身に `application_service_graph` を有効にして同じ内容のメトリクスを出させることもできます。ここでは二重になるので使っていません。

## つまずいたときに見るところ

本章の構成を組む過程で実際に出会ったものを中心に挙げます。

`instrumenting process` の行が出ないなら、対象の選び方が合っていません。`OTEL_EBPF_AUTO_TARGET_EXE` に渡すのは実行ファイルのフルパスに対するグロブです。`scratch` イメージにバイナリを1つだけ置く構成なら、パスは `/frontend` になります。ここに `*/frontend` のようなパターンを書くと、先頭の `*` が空文字列に合わず、何も選ばれないまま静かに終わります。

`type=generic` と出ているなら、Goバイナリだと判定されていません。`.gopclntab` が読めていない可能性があります。

メトリクスがPrometheusに現れないときは、まず時間を置いてください。`OTEL_EBPF_METRICS_INTERVAL` を指定しないとデフォルトの60秒間隔になるので、起動直後に見ても何もありません。

コンテキスト伝搬を有効にすると、環境によっては次のようなログが出ます。

```
level=WARN msg="kernel misreports ioctl(FIONREAD) for sockets in a sockhash (kernel commit 929e30f93125, present in 6.6.128+, 6.12.75+, 6.18.14+ and 6.19+); enabling BPF compensation for tracked sockets" component=tpinjector
level=ERROR msg="context propagation is disabled: the BPF compensation is ineffective (attach failed or blocked?). This kernel misreports ioctl(FIONREAD) for sockets in a sockhash (kernel commit 929e30f93125), or could not be verified to report it correctly, so keeping propagation enabled would risk making applications sizing reads via FIONREAD stall or truncate transfers" component=tpinjector
```

これは13章で扱う2つの伝搬経路のうち、`sk_msg` を使う第2の経路が無効になったという意味です。第1の経路（`bpf_probe_write_user` でアプリのバッファに書き込むほう）は動き続けるので、`backend` の側で `Traceparent` が読めているなら伝搬自体は成立しています。ERRORという語感に反して、Goのアプリだけを相手にしているかぎり実害はありません。実際、本章の実行結果はこのログが出ている環境で取ったものです。

lockdownが `[integrity]` の環境では、第1の経路のほうが使えません。`sk_msg` を使う第2の経路が動く環境ならそちらが引き継ぎますが、両方とも無効なら `Traceparent` は空のままになり、同じOBIが両側を見ている範囲でしかトレースはつながりません。

## この章から難所へ持っていくもの

ここまでで見えたものを、この先の章に割り当てておきます。

| この章で見えたもの | 対応する難所 |
|---|---|
| 関数の入口と出口の時刻から所要時間が取れている | 難所1（10章）。Goでは関数の出口を捕まえる定石が使えない |
| メソッドやURL、ステータスコードが引数から読めている | 難所2（11章）。引数はスタックではなくレジスタに乗っている |
| 構造体のどこにそのフィールドがあるかをOBIが知っている | 難所3（12章）。位置はGoとライブラリのバージョンで変わる |
| `Traceparent` がアプリの知らないうちに書き込まれた | 難所4（13章）。プロセスをまたいで文脈を運ぶ |

- OBIは対象プロセスの外側にいる独立したプログラムであり、アプリのコードにもビルドにも手を入れない。
- 同じOBIが両側を見ているあいだは、ヘッダを書かなくてもトレースはつながる。プロセスの外へ文脈を運ぶには、コンテキスト伝搬を明示的に有効にする。
- `in queue` と `processing` の分離や、ルートのパターンの取得は、ソケットのバイト列からは得られない。関数レベルの計装だから出てくる情報である。
