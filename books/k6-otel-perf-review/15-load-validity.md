---
title: "想定した負荷をかけられたか"
---

修正前のバージョンに毎秒100件を指定したテストでは、60秒間に始まるはずだった6,001回の反復のうち実際に始まったのは4,823回でした。残りの1,178回は[k6](https://grafana.com/docs/k6/v2.3.x/)の要約の`dropped_iterations`という行に数えられていました。

## 始められなかった反復

`dropped_iterations`は、k6が始めるはずだった反復のうち始められなかった回数を数えるカウンターです[^dropped]。開いたモデルでは、反復を始める時刻が来たときに空いているVUがなければ、その反復は待たずに捨てられ、`dropped_iterations`に1が足されます。k6はそのうえで、`maxVUs`に達していなければ新しいVUを裏で1つずつ用意します[^unplanned]。`maxVUs`に達する前から`dropped_iterations`が増えることがあるのは、VUの用意に時間がかかり[^vucost]、その間にも反復が捨てられるからです。

[^unplanned]: k6 v2.3.0の[`lib/executor/constant_arrival_rate.go`](https://github.com/grafana/k6/blob/v2.3.0/lib/executor/constant_arrival_rate.go)。空いているVUがなければ`dropped_iterations`に記録し、`maxVUs`に余裕があれば追加のVUの初期化を1つ要求します。ドキュメントの[Constant arrival rate](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/executors/constant-arrival-rate/)は、`preAllocatedVUs`が少なすぎると指定した頻度でテストできる時間が短くなると注意しています。

[^vucost]: VUはそれぞれ独立したJavaScriptの実行環境で、k6はVUを1つ足すたびに、モジュールの読み込みやオプションの評価といったスクリプトの初期化を実行します。[Test lifecycle](https://grafana.com/docs/k6/v2.3.x/using-k6/test-lifecycle/)の "code in the init context runs once per VU" と、[Arrival-rate VU allocation](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/concepts/arrival-rate-vu-allocation/)の "Allocating VUs has CPU and memory costs" による。

[^dropped]: [Dropped iterations](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/concepts/dropped-iterations/)。メトリクスの定義は[Built-in metrics](https://grafana.com/docs/k6/v2.3.x/using-k6/metrics/reference/)にあります。

修正前のバージョンに毎秒100件をかけると、`catalog-api`は毎秒77件しかさばけないので、到着と完了の差の毎秒23件ずつ、応答待ちのVUが増えていきます。200VUがすべて応答待ちになった時点で、k6は新しい反復を始められなくなりました。そこから先の動作は、200VUが応答を待っては次を送る閉じたモデルと同じです。

3章の表では、修正前のバージョンの応答時間が毎秒100件でも150件でも約2.6秒で、ほとんど変わりませんでした。200件を毎秒77件で割ると約2.6秒になります。この2.6秒は「毎秒100件のときの応答時間」ではなく、「200VUで頭打ちになったときの応答時間」です。`maxVUs`を増やすと、待つVUが増える分だけ応答時間も伸びます[^maxvus]。

[^maxvus]: `maxVUs`を1,000にして同じテストを流すと、p(95)は8,607ms、最大は9,037msまで伸びました。初期化したVUは最大701で、`maxVUs`に届く前から`dropped_iterations`が674回ありました。

## 合格と判定される不足

VUが足りなくなるのは、アプリケーションが遅いときだけではありません。アプリケーションが速くても、VUが少なすぎれば指定した頻度は出ません。試したのは、修正後のバージョンに毎秒100件を指定し、`preAllocatedVUs`を2、`maxVUs`を4に絞った設定です[^vusconfig]。

[^vusconfig]: `maxVUs`を`preAllocatedVUs`より小さくするとk6は設定の誤りとしてテストを始めないので、2つの値を一緒に変えています。k6 v2.3.0の[`lib/executor/constant_arrival_rate.go`](https://github.com/grafana/k6/blob/v2.3.0/lib/executor/constant_arrival_rate.go)の設定の検証が、`maxVUs can't be less than preAllocatedVUs`というエラーを返します。

応答時間とエラー率の閾値だけでは、反復を始められなかったことは合否に表れません。`dropped_iterations`に`count==0`の閾値を足すと[^threshold]、始められなかった反復が1回でもあればテストは不合格になり、k6は終了コード99で終わります[^exit]。サンプルのテストスクリプトは、環境変数`CHECK_DROPPED`を`true`にすると、この閾値を加える作りです。

[^threshold]: [Dropped iterations](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/concepts/dropped-iterations/)の "To assert that the SUT responds within this error budget, you can use the dropped_iterations metric in a Threshold." による。

[^exit]: 終了コード99は、ソースでは`ThresholdsHaveFailed`として定義されています。k6 v2.3.0の[`errext/exitcodes/codes.go`](https://github.com/grafana/k6/blob/v2.3.0/errext/exitcodes/codes.go)。ドキュメントの[Thresholds](https://grafana.com/docs/k6/v2.3.x/using-k6/thresholds/)は "non-zero exit code" とだけ書いています。

```javascript
const thresholds = {
  http_req_duration: [`p(95)<${__ENV.P95_MS || 200}`],
  http_req_failed: ['rate<0.01'],
};
// CHECK_DROPPED=true fails the test when any iteration could not start.
if (__ENV.CHECK_DROPPED === 'true') {
  thresholds.dropped_iterations = ['count==0'];
}
```

VUを絞った設定で、この閾値を足さない場合と足した場合を比べ、VUを十分に用意した場合も並べたのが次の表です。

| `preAllocatedVUs` | `maxVUs` | `dropped_iterations`の閾値 | 完了の頻度 | p(95) | `dropped_iterations` | 終了コード |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | 4 | なし | 61.1件/秒 | 67.1ms | 2,328 | 0 |
| 2 | 4 | `count==0` | 60.7件/秒 | 67.2ms | 2,354 | 99 |
| 50 | 200 | `count==0` | 99.9件/秒 | 67.2ms | 0 | 0 |

VUを4に絞ると、始まった反復は3,672回で、完了の頻度は指定の6割に落ちました。それでも、閾値がなければ応答時間とエラー率の基準だけで判定されるので、このテストは合格で、終了コードも0です。閾値を足すと、同じ設定のテストは不合格になりました。不足のないテストでは、`dropped_iterations`は0として要約に表れ、閾値も満たされました。

k6は不足に気づいていて、警告も出しますが、ターミナルで見ると見落としてしまうかもしれません。同じ設定を20秒に縮めて実行すると、ターミナルには次のように表示されました。

![k6のバナーとシナリオの設定の下に、Insufficient VUsの警告が1行あり、最後の進行表示は0/4 VUs、20s、100.00 iters/sで、1220 complete](/images/20261118-k6-insufficient-vus.png)
*図1: `preAllocatedVUs`を2、`maxVUs`を4にしたk6をターミナルで実行し、終了した時点の画面*

警告は開始直後に1行出るだけで、テストの結果は変えません。進行表示の右端に出続けるのは、指定した頻度の`100.00 iters/s`です。20秒で完了した反復は1,220回、毎秒61件でした。`dropped_iterations`の閾値を入れずにCIで終了コードだけを見ていると、毎秒61件のテストを「毎秒100件で合格」として記録してしまいます。

## 負荷を生成する側の資源

`dropped_iterations`が0なら、指定した負荷はかかっていたと言ってよいのでしょうか。k6自身が使えるCPUが足りない場合を試しました。修正後のバージョンに毎秒100件を指定し、k6を動かすコンテナに割り当てるCPUだけを変えています。

| k6のCPU | 完了の頻度 | p(95) | p(99) | エラー率 | `dropped_iterations` |
| --- | --- | --- | --- | --- | --- |
| 1 | 99.9件/秒 | 67.2ms | 68.4ms | 0% | 0 |
| 0.2 | 99.7件/秒 | 111.6ms | 199.9ms | 1.17% | 0 |
| 0.1 | 95.0件/秒 | 304.0ms | 596.5ms | 8.07% | 260 |
| 0.05 | 61.7件/秒 | 1,403.2ms | 2,200.8ms | 11.49% | 2,217 |

テスト対象のサービスは同じなのに、k6のCPUを絞るだけで応答時間が伸び、エラーが出ました。0.2コアのときは完了の頻度が指定どおりで、`dropped_iterations`も0です。k6の要約からは、負荷を生成する側に問題があったとは読み取れません。

それなのに、エラーは実際に`inventory`で起きていました。k6が数えた502は0.2コアで70件、0.1コアで463件で、いずれも`inventory`の待ち行列があふれた503を`catalog-api`が変換したものです。k6側のタイムアウトは0件でした。

原因を探るため、リクエストが届いた時刻を`catalog-api`の側で集計しました[^arrival-sample]。k6が記録するリクエストの時刻は応答を受け取った時刻なので[^endtime]、送った時刻の偏りは見えません。

[^arrival-sample]: 同じ条件で20秒間流したときに[Tempo](https://grafana.com/docs/tempo/v3.1.x/)に残った、`catalog-api`のサーバースパン2,001件の開始時刻を集計しました。サーバースパンは、受け取ったリクエストの処理区間を表す記録です（[OpenTelemetryの説明](https://opentelemetry.io/docs/concepts/signals/traces/#server)）。

[^endtime]: k6 v2.3.0の[`lib/netext/httpext/tracer.go`](https://github.com/grafana/k6/blob/v2.3.0/lib/netext/httpext/tracer.go)で、`http_reqs`などのサンプルの時刻に`tr.EndTime`を使っています。

| k6のCPU | 100msごとの到着数の標準偏差 | 10msに届いた最大の件数 | 到着の間隔の最大 |
| --- | --- | --- | --- |
| 1 | 0.4件 | 2件 | 16ms |
| 0.2 | 2.5件 | 15件 | 198ms |

1コアのk6は、ほぼ10msおきに1件ずつ送っていました。0.2コアのk6は、最大で198ms送らない時間を挟み、10msの間に15件をまとめて送っています。`inventory`の処理枠は6件、待ち行列は8件なので、15件が一度に届けば、合わせて14件を超えた分があふれる計算です。平均の頻度は同じでも、届き方が偏るとテスト対象のサービスの振る舞いが変わります。この20秒のテストの間、k6のCPU使用率は平均18.7%で、割り当てた0.2コア（20%）の上限近くに張り付いていました[^cfs]。

[^cfs]: CPUを割り当てられない間に送れなかったリクエストを、割り当てられた時点でまとめて送ったと考えると、この結果と整合します。ただし、k6の内部のスケジューリングまでは確かめていません。

負荷を生成する側の不足は、負荷の量だけでなく形を変えます。k6の要約に問題が表れていなくても、k6のCPU使用率は記録に残すべき値です。サンプルの構成では、1コアを割り当てたk6の使用率は、毎秒100〜150件の開いたモデルのテストで平均13.8〜23.7%でした。

## 合否の基準

ここまでのテストでは、合否の基準をp(95)が200ms未満、エラー率が1%未満としてきました。この値はサンプルのために決めたもので、根拠は「利用者が商品の一覧を開いたときに待たされたと感じない程度」という想定だけです。

基準の数値は、組織のSLO[^slo]をそのまま負荷テストの閾値に写さず、テストが確かめる利用条件から決めます。SLOは本番の利用が混在する状態と長い集計期間を前提にした目標で、60秒の合成された負荷とは前提が違うからです。テストの閾値とSLOを関連づけたいなら、どの利用条件を再現したテストなのかを閾値と一緒に記録します。

[^slo]: SLO（service level objective、サービスレベル目標）は、応答時間やエラー率などで測るサービス水準に対して定める目標値や範囲です（[Google SRE Bookの説明](https://sre.google/sre-book/service-level-objectives/)）。

テストごとに、次の項目を記録します。

- 指定した頻度と完了の頻度
- 始まった反復の回数と`dropped_iterations`
- VUの数
- k6の終了コードと標準エラーの警告
- k6のCPU使用率

VUの数は2つを分けて記録します。`vus_max`は初期化したVUの数で、用意しただけで反復を実行していないVUも数えます。反復を実行中のVUの数は`vus`です。この章の`maxVUs`を200にしたテストでは、`vus_max`が50のまま、`vus`の最大は7でした。これらがそろってはじめて、「毎秒120件をかけた結果」と言えます。
