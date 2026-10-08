---
title: "想定した負荷をかけられたか"
---

修正前の版に毎秒100件を指定した試験では、60秒間に始まるはずだった6,001回の反復のうち実際に始まったのは4,825回でした。残りの1,176回は[k6](https://grafana.com/docs/k6/v2.3.x/)の要約の`dropped_iterations`という行に数えられていました。

## 始められなかった反復

`dropped_iterations`は、k6が始めるはずだった反復のうち始められなかった回数を数えるカウンターです[^dropped]。開いたモデルでは、反復を始める時刻が来たときに空いているVUがなければ、その反復は待たずに捨てられ、`dropped_iterations`に1が足されます。k6はそのうえで、`maxVUs`に達していなければ新しいVUを裏で1つずつ用意します[^unplanned]。VUを用意している間にも反復は捨てられるので、`dropped_iterations`が`maxVUs`に達する前から増えることがある点に注意が必要です。

[^unplanned]: k6 v2.3.0の[`lib/executor/constant_arrival_rate.go`](https://github.com/grafana/k6/blob/v2.3.0/lib/executor/constant_arrival_rate.go)。空いているVUがなければ`dropped_iterations`に記録し、`maxVUs`に余裕があれば追加のVUの初期化を1つ要求します。ドキュメントの[Constant arrival rate](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/executors/constant-arrival-rate/)は、`preAllocatedVUs`が少なすぎると指定した頻度で試験できる時間が短くなると注意しています。

[^dropped]: [Dropped iterations](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/concepts/dropped-iterations/)。メトリクスの定義は[Built-in metrics](https://grafana.com/docs/k6/v2.3.x/using-k6/metrics/reference/)にあります。

修正前の版に毎秒100件をかけると、`catalog-api`は毎秒77件しかさばけないので、到着と完了の差の毎秒23件ずつ、応答待ちのVUが増えていきます。200VUがすべて応答待ちになった時点で、k6は新しい反復を始められなくなりました。そこから先の動作は、200VUが応答を待っては次を送る閉じたモデルと同じです。

この見方で、3章の表に残っていたもう1つの数字も説明できます。修正前の版の応答時間は毎秒100件でも150件でも約2.6秒で、ほとんど変わりませんでした。200件÷毎秒77件は約2.6秒です。指定した頻度ではなく、`maxVUs`の200が応答時間を決めていました。`maxVUs`を1,000にして同じ試験を流すと、p(95)は8,728ms、最大は9,204msまで伸びました。初期化したVUは最大704で、`dropped_iterations`は673です。VUを1つずつ用意している間に、反復が捨てられていました。この2.6秒は「毎秒100件のときの応答時間」ではなく、「200VUで頭打ちになったときの応答時間」です。

## 合格と判定される不足

VUが足りなくなるのは、アプリケーションが遅いときだけではありません。アプリケーションが速くても、VUの数が小さすぎれば指定した頻度は出ません。修正後の版に毎秒100件を指定し、事前に用意するVU（`preAllocatedVUs`）を2、上限の`maxVUs`を4に絞った結果が次の表です。`maxVUs`を`preAllocatedVUs`より小さくすると、k6は設定の誤りとして試験を始めないので、2つの値を一緒に変えています[^vusconfig]。

[^vusconfig]: k6 v2.3.0の[`lib/executor/constant_arrival_rate.go`](https://github.com/grafana/k6/blob/v2.3.0/lib/executor/constant_arrival_rate.go)の設定の検証が、`maxVUs can't be less than preAllocatedVUs`というエラーを返します。

| `preAllocatedVUs` | `maxVUs` | `dropped_iterations`の閾値 | 完了の頻度 | p(95) | `dropped_iterations` | 終了コード |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | 4 | なし | 60.9件/秒 | 67.2ms | 2,344 | 0 |
| 2 | 4 | `count==0` | 61.0件/秒 | 67.3ms | 2,337 | 99 |
| 50 | 200 | `count==0` | 99.9件/秒 | 67.3ms | 0 | 0 |

VUを4に絞ると、始まった反復は6,001回のうち3,657回で、完了の頻度は指定の6割に落ちました。それでも応答時間とエラー率の基準だけで判定すると、この試験は合格で、終了コードも0です。k6は標準エラーに次の警告を出していましたが、試験の結果は変えません。

```text
level=warning msg="Insufficient VUs, reached 4 active VUs and cannot initialize more" executor=constant-arrival-rate scenario=open
```

CIで終了コードだけを見ていると、毎秒61件の試験を「毎秒100件で合格」として記録してしまいます。`dropped_iterations`を閾値に使う方法は、k6のドキュメントにも書かれています[^threshold]。題材の試験では、環境変数`CHECK_DROPPED`を`true`にすると、次の`dropped_iterations`の行が閾値に加わる作りです。

[^threshold]: [Dropped iterations](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/concepts/dropped-iterations/)の "To assert that the SUT responds within this error budget, you can use the dropped_iterations metric in a Threshold." による。

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

閾値を満たさない試験の終了コードは、k6のソースで`ThresholdsHaveFailed`として定義された99です[^exit]。不足のない試験では、`dropped_iterations`は0として要約に現れ、閾値も満たされました。

[^exit]: k6 v2.3.0の[`errext/exitcodes/codes.go`](https://github.com/grafana/k6/blob/v2.3.0/errext/exitcodes/codes.go)。ドキュメントの[Thresholds](https://grafana.com/docs/k6/v2.3.x/using-k6/thresholds/)は "non-zero exit code" とだけ書いています。

## 負荷を生成する側の資源

`dropped_iterations`が0なら、指定した負荷はかかっていたと言ってよいのでしょうか。k6自身が使えるCPUが足りない場合を試しました。修正後の版に毎秒100件を指定し、k6を動かすコンテナに割り当てるCPUだけを変えています。

| k6のCPU | 完了の頻度 | p(95) | p(99) | エラー率 | `dropped_iterations` |
| --- | --- | --- | --- | --- | --- |
| 1 | 99.9件/秒 | 67.3ms | 68.7ms | 0% | 0 |
| 0.2 | 99.8件/秒 | 112.5ms | 200.3ms | 1.45% | 0 |
| 0.1 | 95.3件/秒 | 397.1ms | 599.2ms | 9.21% | 228 |
| 0.05 | 63.9件/秒 | 1,398.7ms | 2,497.1ms | 13.72% | 2,144 |

被試験系は同じなのに、k6のCPUを絞るだけで応答時間が伸び、エラーが出ました。0.2コアのときは完了の頻度が指定どおりで、`dropped_iterations`も0です。k6の要約からは、負荷を生成する側に問題があったとは読み取れません。

それなのに、エラーは実際に`inventory`で起きていました。k6が数えた502は0.2コアで87件、0.1コアで530件で、いずれも`inventory`の待ち行列があふれた503を`catalog-api`が変換したものです。k6側のタイムアウトは0件でした。

原因を探るため、リクエストが届いた時刻を`catalog-api`の側で数えました。k6が記録するリクエストの時刻は応答を受け取った時刻なので[^endtime]、送った時刻の偏りは見えません。集計の対象は、同じ条件で20秒間流したときに[Tempo](https://grafana.com/docs/tempo/v3.1.x/)に残った`catalog-api`のサーバースパン2,001件の開始時刻です。

[^endtime]: k6 v2.3.0の[`lib/netext/httpext/tracer.go`](https://github.com/grafana/k6/blob/v2.3.0/lib/netext/httpext/tracer.go)で、`http_reqs`などのサンプルの時刻に`tr.EndTime`を使っています。

| k6のCPU | 100msごとの到着数の標準偏差 | 10msに届いた最大の件数 | 到着の間隔の最大 |
| --- | --- | --- | --- |
| 1 | 0.6件 | 2件 | 23ms |
| 0.2 | 2.6件 | 19件 | 195ms |

1コアのk6は、ほぼ10msおきに1件ずつ送っていました。0.2コアのk6は、最大で195ms送らない時間を挟み、10msの間に19件をまとめて送っています。`inventory`の処理枠は6件、待ち行列は8件なので、19件が一度に届くとあふれる計算です。平均の頻度は同じでも、届き方が偏ると被試験系の振る舞いが変わりました。この20秒の試験中のk6のCPU使用率は平均19.1%で、割り当てた0.2コア（20%）の上限近くに張り付いた状態でした。CPUを割り当てられない間に送れなかったリクエストを、割り当てられた時点でまとめて送ったと考えると、この結果と整合します。ただし、k6の内部のスケジューリングまでは確かめていません。

負荷を生成する側の不足は、負荷を減らすだけでなく、負荷の形を変えます。k6の要約に問題が出ていなくても、試験中のk6のCPU使用率は記録に残すべき値です。題材の構成では、1コアを割り当てたk6の使用率は、毎秒100〜150件の開いたモデルの試験で平均13.4〜25.4%でした。

## 合否の基準

ここまでの試験では、合否の基準をp(95)が200ms未満、エラー率が1%未満としてきました。この値は題材のために決めたもので、根拠は「利用者が商品の一覧を開いたときに待たされたと感じない程度」という想定だけです。

基準の数値は組織のSLOをそのまま負荷試験の閾値に写すのではなく、試験が確かめる利用条件から決めます。SLOは本番の利用が混在する状態と長い集計期間を前提にした目標で、60秒の合成された負荷とは前提が違うからです。試験の閾値とSLOを関連づけたいなら、どの利用条件を再現した試験なのかを閾値と一緒に記録します。

基準と並んで、試験のたびに残すものもここで決まりました。指定した頻度と完了の頻度、始まった反復の回数と`dropped_iterations`、VUの数、k6の終了コードと標準エラーの警告、k6のCPU使用率です。VUの数は2つを分けて残します。`vus_max`は初期化したVUの数で、用意しただけで反復を実行していないVUも数えます。反復を実行中のVUの数は`vus`です。この章の`maxVUs`を200にした試験では、`vus_max`が50のまま、`vus`の最大は7でした。これらがそろってはじめて、「毎秒120件をかけた結果」と言えます。
