---
title: "テスト結果から調べる処理を絞る"
---

修正前のバージョンに毎秒100件をかけると、[k6](https://grafana.com/docs/k6/v2.3.x/)から見た応答時間は2.6秒でした。この2.6秒を`catalog-api`と`inventory`のどちらが使っていたのでしょうか。2章の計算では`catalog-api`の同時実行数の制限が疑わしいのですが、計算は仮説であって観測ではありません。5章で集めたテレメトリーから、調べる処理を絞っていきましょう。

## 同じ時間範囲のメトリクス

最初に見るのは、テストと同じ時間範囲のメトリクスです。k6のメトリクスは`testid`でテストを選び、アプリケーションのメトリクスはテストの開始と終了の時刻で範囲を選びます。次の[PromQL](https://prometheus.io/docs/prometheus/latest/querying/basics/)で、同じ時間範囲のp(95)を求めます[^metric-window]。

[^metric-window]: テストの終了の10秒前を基準に、直前40秒の値を集計しました。

```promql
# k6から見た応答時間のp(95)（ミリ秒）
histogram_quantile(0.95,
  sum by (le)(rate(http_req_duration_milliseconds_bucket{testid="e2-open-l4-r100"}[40s])))

# サービスごとのサーバー側の処理時間のp(95)（秒）
histogram_quantile(0.95,
  sum by (le, job)(rate(http_server_request_duration_seconds_bucket[40s])))

# catalog-apiがinventoryを呼んだ時間のp(95)（秒）
histogram_quantile(0.95,
  sum by (le, job)(rate(http_client_request_duration_seconds_bucket[40s])))
```

修正前のバージョンに毎秒100件、修正後のバージョンに毎秒150件をかけたテストの結果が次の表です。

| 値 | 修正前、毎秒100件 | 修正後、毎秒150件 |
| --- | --- | --- |
| k6から見たp(95) | 4,844ms | 240ms |
| `catalog-api`のサーバー側のp(95) | 4,875ms | 240ms |
| `catalog-api`が`inventory`を呼んだ時間のp(95) | 73ms | 239ms |
| `inventory`のサーバー側のp(95) | 73ms | 239ms |
| `inventory`が503を返した頻度 | 0件/秒 | 31.9件/秒 |
| `inventory`の待ち行列の最大 | 0件 | 8件 |

最初に目につくのは、k6から見たp(95)の4,844msです。3章で示したk6の要約では、同じテストのp(95)は2,612msでした。値が違う理由は、[Mimir](https://grafana.com/docs/mimir/v3.2.x/)に入ったヒストグラムが決まった境界のバケットで件数を数えていることにあります。バケットが粗いため、補間したp(95)が要約の値から大きく離れました[^buckets]。

[^buckets]: この時間範囲では応答の約8割が2,500msから5,000msのバケットに入り、p(95)もこのバケットの中です。`histogram_quantile`はバケット内の値を一様に分布するとみなして補間するので、p(95)の推定値はこの2,500msの幅の中で決まります（[Prometheusの関数リファレンス](https://prometheus.io/docs/prometheus/latest/querying/functions/#histogram_quantile)）。k6の出力も[otelhttp](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp@v0.72.0)も、バケットの境界は5、10、25、50、75、100、250、500、750、1,000、2,500、5,000ms…の並びでした。境界は計装の側で細かくできます。OpenTelemetryには境界を自動で決める指数ヒストグラムもありますが、サンプルでは扱っていません。

それでも、同じ境界で数えた値どうしなら比べられます。修正前のバージョンでは、`catalog-api`のサーバー側の時間が4.9秒前後なのに、`catalog-api`が`inventory`を呼んだ時間と`inventory`自身の時間は73msでした。`inventory`は普段どおりに応答しています。時間を使っているのは`catalog-api`の中で、`inventory`を呼んでいる時間の外です。修正後のバージョンに毎秒150件をかけたときは、`catalog-api`と`inventory`の時間がほぼ同じで、時間は`inventory`の中で使われています。`inventory`は待ち行列の上限の8件まで詰まり、毎秒32件を断っています。

![catalog-apiのサーバー側のp(95)は、修正前のバージョンに開いたモデルで負荷をかけた2つのテストの間だけ約4.9秒に上がり、inventoryは0秒近くのまま。右端の修正後のバージョンに毎秒150件をかけた時間帯では、2つのサービスがともに約240msに並ぶ](/images/20261118-grafana-server-p95.png)
*図1: 3章のテストを続けて流した時間帯の、サービスごとのサーバー側の処理時間のp(95)をGrafanaで表示した画面。左の山が修正前のバージョンに毎秒100件と150件をかけた時間帯、右端が修正後のバージョンに毎秒150件をかけた時間帯*

図1で2本の線が離れているのは、`catalog-api`の中で時間を使っている時間帯です。2本が重なっていれば、時間は`inventory`の中で使われています。

## 時間範囲の一致とリクエストの対応

ここまでの読み取りには1つ飛躍があります。メトリクスが示しているのは、同じ40秒の間にk6から見た応答時間が伸び、`catalog-api`のサーバー側の時間も伸びたという事実です。k6のどの遅いリクエストが`catalog-api`のどの遅い処理に当たるのかまでは示していません。

この飛躍がサンプルで問題にならないのは、`catalog-api`を呼ぶのがk6だけだからです。本番の環境では、テストの時間帯にも別の利用者や定期処理が同じサービスを呼びます。`inventory`の時間が伸びたとしても、伸ばしたのはテストのリクエストではなく、別の呼び出し元かもしれません。同じ時間範囲のメトリクスは調べる候補を絞る材料で、1件ずつの対応を確かめるのはトレースの役割です。

## トレースで1件ずつ確かめる

[Tempo](https://grafana.com/docs/tempo/v3.1.x/)では、[TraceQL](https://grafana.com/docs/tempo/v3.1.x/traceql/)でスパンの条件を書いてトレースを探します。修正前のバージョンに毎秒100件をかけたテストの時間範囲で、1秒を超えた`catalog-api`のサーバースパンを探すと、4,421件見つかりました。同じ条件で`inventory`を探すと0件です。

```traceql
{ resource.service.name = "catalog-api" && kind = server && duration > 1s }
```

テストの時間範囲のトレースを300件取り出し、スパンごとの時間を集計しました[^analyze]。表の行は、どれも同じリクエストの集合から求めた値です[^accepted]。

[^analyze]: 集計に使ったスクリプトは、サンプルのリポジトリの[`analyze_traces.py`](https://github.com/ymotongpoo/k6-otel-perf-review/blob/f86b6ed88a1dbb34050897a984f9997e67f78d4a/analyze_traces.py)です。TempoのHTTP APIでトレースを検索し、1件ずつ取得してスパンの時間を集めます。トレースは、テストの時間範囲を30に分け、それぞれから同じ件数ずつ取り出します。`--same-set`を付けると、すべての行を、両方のサービスのスパンがそろったトレースだけで集計します。区間の差（サーバースパンとクライアントスパンの差など）は、同じトレースの中で引き算してから中央値を求めた値です。

[^accepted]: 修正後のバージョンの毎秒150件のテストでは、300件のうち66件が`inventory`に503で断られており、断られたリクエストには`lookup stock`のスパンがありません。そこで、この列は`inventory`が受け付けた234件だけで集計しています。修正前のバージョンの列は、300件すべてが受け付けられています。

| スパン | 修正前、毎秒100件 中央値 | p(95) | 修正後、毎秒150件 中央値 | p(95) |
| --- | --- | --- | --- | --- |
| `catalog-api`のサーバースパン | 2,569.9ms | 2,612.2ms | 118.6ms | 133.7ms |
| `catalog-api`のクライアントスパン | 51.5ms | 60.7ms | 112.8ms | 127.9ms |
| `inventory`のサーバースパン | 50.6ms | 59.9ms | 112.0ms | 127.1ms |
| `inventory`の`lookup stock` | 50.5ms | 59.7ms | 50.8ms | 60.4ms |

トレースの値はメトリクスのようにヒストグラム化による補間の影響を受けないので、k6の要約とほぼ一致します。修正前のバージョンでは、サーバースパンの2,570msのうちクライアントスパンは51.5msだけです。クライアントスパンは、サーバースパンが始まってから中央値で約2,519ms後に始まり、サーバースパンとほぼ同時に終わっていました。この約2,519msは、`catalog-api`が`inventory`を呼ぶ前に使った時間です。修正後のバージョンでは、`inventory`のサーバースパンの112.0msのうち在庫を調べていたのは50.8msでした。残りの約60msは、`inventory`の中で処理枠の空きを待っていた時間にあたります。

## トレースからログへ

修正後のバージョンに毎秒150件をかけたテストでは、21.2%のリクエストが502でした。エラーになったトレースを1件選び、5章で設定した「トレースからログへ」の移動を使ってみましょう[^events]。図2の右は、`inventory`のスパンの詳細で「Logs for this trace」を押し、`inventory`のサービス名とこのトレースのトレースIDで検索したLokiの画面です。

![左のTempoの画面でcatalog-apiのGET /items/{id}が502を返したトレースを開き、inventoryのGET /stock/{id}のスパンの詳細にLogs for this traceのボタンがある。右のLokiの画面には、inventoryのサービス名とトレースIDで検索した結果として、WARNのqueue fullが1行表示されている](/images/20261118-grafana-trace-to-logs.png)
*図2: `inventory`が503で断ったリクエストのトレースをGrafanaのExploreで開き、`inventory`のスパンの「Logs for this trace」からLokiのログを右に表示した画面*

[^events]: スパンイベントは、スパンの中のある時点に名前と属性を付けて記録する出来事です。トレースの画面にスパンイベントが表示されるのは、アプリケーションがスパンにイベントを記録したとき（Goなら`span.AddEvent`）だけです。サンプルはログをOpenTelemetryのログとして送っているので、ログはスパンイベントになりません。OpenTelemetryはスパンイベントを記録するAPIを非推奨にし、新しいコードではイベントを現在のスパンと関連づけたログとして書くよう求めています。[Deprecating Span Events API](https://opentelemetry.io/blog/2026/deprecating-span-events/)の "New code should write events as logs that are correlated with the current span." による。

検索の条件にはスパンのサービス名も入るので、`inventory`のスパンから開くと、見つかるのは`inventory`の「queue full」の1行だけです。2つのサービスのログを1つの一覧で見たいときは、検索の条件を次のように広げます。

```logql
{service_name=~"catalog-api|inventory"} | trace_id="<同じトレースID>"
```

同じトレースIDで見つかったログは、2つのサービスで1件ずつでした。

![LogQLの検索の結果、13:00:44.092にWARNのqueue full、1ms後にWARNのbackend returned errorの2行が表示されている](/images/20261118-grafana-logs-by-trace-id.png)
*図3: 503で断られたリクエストのトレースIDで2つのサービスのログをLokiから検索し、GrafanaのExploreで表示した画面*

先に書かれたのは`inventory`の「queue full」で、属性に待ち行列の上限の`queue_limit=8`が付いています。1ms後に、`catalog-api`が`status=503`を付けた「backend returned error」を書きました。

`inventory`が待ち行列の上限で断り、`catalog-api`がその503を受け取って502を返したことが、1件のリクエストの中でつながりました。メトリクスで見えていた「毎秒32件の503」と「毎秒32件の502」は、同じリクエストの両端でした。

修正後のバージョンで起きていたことは、トレースとログでほぼ説明がつきました。修正前のバージョンはそうではありません。分かったのは、約2,519msが`inventory`を呼ぶ前に使われていたことまでです。その時間が同時実行数の制限の前で待っていた時間なのか、`catalog-api`の別の処理なのかは、いまのスパンでは区別できません。
