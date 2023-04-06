---
title: "計装からSLOの設定までを素朴に行ってみる"
emoji: "🌡️"
type: "tech" # tech: 技術記事 / idea: アイデア
topics: ["SLO", "SLI", "SRE", "Observability"]
published: true
---

## はじめに

直近の記事で「サービスレベル目標をもっとカジュアルに使いませんか」という話を書きました。

@[card](https://zenn.dev/ymotongpoo/articles/20230329-slo-without-sre)

今回は、それに続く話として、じゃあどこから計装したらいいのか、という話を書こうと思います。

## サービスレベル指標の選択

前回の記事でユーザーの信頼性を表すための代替指標としてサービスレベル指標（SLI）というものを使いますという話をしました。そしてサービスレベル指標をどのように選ぶかに悩んだ時に、いくつか代表的なものが経験的に知られているという話もしました。

* [The Art of SLOの資料にあるSLIメニュー](https://docs.google.com/document/d/1WWQ9asDFlgr7f4jTh2xgxm8XIMLK_244-sDBMIvqVtw/edit#heading=h.kxvma8d1jy9j)
* [The Four Golden Signals](https://sre.google/sre-book/monitoring-distributed-systems/#xref_monitoring_golden-signals)
* [USE](https://www.brendangregg.com/usemethod.html)
* [RED](https://grafana.com/files/grafanacon_eu_2018/Tom_Wilkie_GrafanaCon_EU_2018.pdf)

個人的にはサービスの種類とそれぞれにおいての代表的な指標を紹介している点でThe Art of SLOのSLIメニューが使いやすいと思うので、ここでもそれを参考にします。

![SLIメニュー](/images/20230404000612.png)

データ処理パイプラインやストレージシステムに関するSLIはすこし発展的な内容かなと思うので、ここではリクエスト／レスポンス型のサービス（例：APIエンドポイント）を考えてみます。上の図は英語になっていますが、以下の3つのメトリクスがSLIの候補として挙げられています。

* 可用性（Availability）
* レイテンシー（Latency）
* 品質（Quality）

このうち、可用性のメトリクスはもしかするとSLOに関係なくすでに取得されていることが多いでしょう。ですので、ここではレイテンシーのメトリクスを考えたいと思います。「サービスのレイテンシーのメトリクスを取得する」というときにどこで計測を行なうのでしょうか。

## プローブを考える

この文脈ではプローブは計装を行なう場所を指します。レイテンシーを計測するということは物理的にどこからリクエストを投げたときのレイテンシーなのかを明確にする必要があります。少し考えただけでも次の図のように複数の候補が浮かんできます。

![SLIメニュー](/images/20230404095000.png)

1. システム外のネットワークでユーザーにもっとも近い場所
2. システム内のネットワークでロードバランサーのすぐ外
3. ロードバランサーとサービスの間
4. サービスのエンドポイント

SLIの主旨を考えると1番がもっともユーザーの観点でのレイテンシーを反映していそうです。しかしながら、ユーザーがいるネットワークは千差万別でユーザーがいる末端からシステムがあるネットワークの間にどれだけ距離があるかわかりませんし、ユーザーのネットワーク状況もわかりません。地球の裏側にいるユーザーが非常に電波の悪い山奥からリクエストしている場合と、システムのネットワークと同じ国にいる有線接続の10Gb回線を利用するユーザーがリクエストする場合では大きな差があります。ばらつきが多いということはノイズも多いということです。もちろん意図して1番で計測する場合もあります（たとえばリアルユーザーモニタリング《RUM》や、プローブを全世界に分散させた合成モニタリングなど）。本記事の話題からは少し発展的になってしまうので、その話はまた別にするとします。

2〜4番のどれかを選択することにします。2番や3番の場合には専用のクライアントを用意するか、合成モニタリングツールなどで定期的にリクエストを生成することになります[^intercept]。また3番はロードバランサーの機能としてルーティングの部分から対象のサービスまでのレイテンシーを取得できるなら、それも1つの案でしょう。4番はサービス開発側にもっとも近く裁量がある方法です。1〜3番と違ってプローブの挿入箇所を自由に設定できます。今回は4番で考えてみます。

[^intercept]: もしユーザーからのリクエストをインターセプトして、その地点からのレイテンシーを取得できるような仕組みを持っているのであればそれでも可能です。

## 計装する

「計装（インツルメンテーション）」をする、と聞くと構えてしまうかもしれませんが、分散トレースやメトリクスをまったく計装したことがなくても、ひとまずログとして出すだけでも有益です[^logging-metric]。

[^logging-metric]: もちろんモニタリングバックエンドを持っている方は、この部分をログでの実装ではなくメトリクスでの実装で考えてください。

たとえば次のようなエンドポイントがあったとします（まったくの想像上のサンプルです）。

```python
@app.route("/profile")
def profile_handler():
    if "token" not in session:
        return redirect(url_for("signin"))
    user = get_user(token)
    profile = get_user_profile(user)
    history = get_user_history(user)
    return response_builder(profile, history)
```

なにかしらのサービスでセッション情報にもとづいてユーザープロファイルとサービス上での履歴情報をまとめて返すエンドポイントになっています。このエンドポイントに対するリクエストのレイテンシーを計測します。

```python
import logging
from datetime import datetime

@app.route("/profile")
def profile_handler():
    start = datetime.now() # 処理の開始時刻を計時
    if "token" not in session:
        return redirect(url_for("signin"))
    user = get_user(token)
    profile = get_user_profile(user)
    history = get_user_history(user)
    d = datetime.now() - start # 処理時間を計算
    s = start.isoformat()
    logging.info(f"profile_handler:{s},{d.microseconds/1000.0}") # ログに処理時間を出力
    return response_builder(profile, history)
```

サンプルのためだけの実装で、さまざまな機能はありませんが、これを実行すると次のようにログが出力されます。

```text
INFO:root:profile_handler:2023-04-04T17:36:00.223759,107.212
INFO:root:profile_handler:2023-04-04T17:36:14.900533,72.51
INFO:root:profile_handler:2023-04-04T17:36:30.022853,93.26
INFO:root:profile_handler:2023-04-04T17:36:42.896968,94.617
INFO:root:profile_handler:2023-04-04T17:37:11.302539,93.93
INFO:root:profile_handler:2023-04-04T17:37:37.873491,60.107
INFO:root:profile_handler:2023-04-04T17:37:45.925861,112.936
```

ひとまずこれでメトリクスが取得できたので、これを分析してみます。

## 分析する

メトリクスの分析方法さまざまにありますが、もっとも典型的な方法ということでチャートにしてみます。10分ごとにアグリゲートして区間内のデータの最大値を取ります。他のアグリゲーション方法（最小値、中央値）などにしてしまうと外れ値（最悪値）が消えてしまうためです。

```python
import pandas  # pandas==2.0.0

raw = open("log.txt", "r")
data = []
for line in raw:
    line = line.strip()
    sep = line.split(":", 3)
    timestamp, latency = sep[3].split(",")
    data.append({"timestamp": timestamp, "latency": float(latency)})

df = pandas.DataFrame(data)
df["timestamp"] = pandas.to_datetime(df["timestamp"])
result = df.query('"2023-03-31T12:00:00" < timestamp < "2023-04-05T12:00:00"') \
    .set_index("timestamp") \
    .resample('10min') \
    .max() \
    .reset_index()

fig = result.plot(
    title="latency ms",
    kind="line",
    x="timestamp",
    y="latency",
    ylabel="latency (ms)",
    figsize=(25, 10)).get_figure()
fig.savefig("chart.png")
```

表示をするためにDataFrameの区間を短く（5日間）してますが、最悪でも40msはかかっていない事がわかります。

![チャート](/images/20230405112400.png)

ためしに、計測した全期間（6ヶ月間）でP99、P90、P50をそれぞれ出してみたいと思います。（ここではアグリゲーションはせずに、全データポイントを使ってパーセンタイルを計算しています。）

```python
df.set_index("timestamp")
p99 = df.quantile(q=0.99)
p90 = df.quantile(q=0.9)
p50 = df.quantile(q=0.5)
print(f"p99: {p99.latency}, p90: {p90.latency}, p50: {p50.latency}")
```

結果は次のとおりでした。

```text
p99: 31.0, p90: 27.0, p50: 23.0
```

ここまで非常に素朴な処理をしてきましたが、これだけでも半年間のデータを使って大まかに傾向が見えたように思います。上のグラフでの表示では「40ms未満」程度しかわかりませんでしたが、きちんとP99とP90を見たことで精度が上がりました。

## SLIとSLOを設定する

分析を行って、SLIに使うメトリクスおおよその傾向が見えたところで、いよいよ実際にその目標値であるSLOを設定してみます。目標値は、各組織の状況に応じて設定するため一概にいくつに設定するとは言えません。上の分析で見た結果が、すでにまったく信頼性がない状況かもしれませんし、逆に過剰な品質になっているかもしれません。

仮にいまがちょうどいい品質を提供しているとして、今の状態を維持したいと思った場合にはどうしたら良いでしょうか。まず1回のリクエストで妥当と思われるレイテンシーを決める必要があります。概ね30msで処理されれば良いと経験的に分かっているため、関係部署との話し合いの結果、SLIは次のように設定することに決めました。

> **サービスレベル指標**: `profile_handler` のレスポンスのレイテンシーが30ms以下となるものの割合

このSLIの目標値を考えるわけですが、まず割合を決めるためには計測期間を決めなければいけません。現在、このサービスは1ヶ月のスプリントを繰り返してリリースしていると仮定して、28日のローリングウィンドウで考慮したいと思います。ふたたび過去データを使って考慮するとどうなるでしょうか。

```python
threshold=30.0
def good_event(series):
    return series[series <= threshold].count() / float(series.count())

result = df.sort_index()\
    .rolling("28D", on="timestamp", min_periods=1).apply(good_event)

fig = result.plot(
    title="SLI rate",
    kind="line",
    x="timestamp",
    y="latency",
    figsize=(25, 10)).get_figure()
fig.savefig("sli_rate.png")
```

生成されたグラフを見てみましょう。

![SLIの履歴](/images/20230405151000.png)

コードには出していませんが、結果を別途数値として表にしてみると、おおよそ98%程度で安定していることがわかりました。したがって、現状を維持するだけを考えるのであれば次のようなSLOが設定できることになります。

> **サービスレベル目標**: `profile_handler` のレスポンスのレイテンシーが30ms以下となるものの割合が28日のローリングウィンドウで98%となる。

上記のSLOはイベントベースで設定しました。その理由は28日のローリングウィンドウ内で十分な数のリクエストがあるため、リクエストイベント1つがSLOに与える影響が少ないためです。たとえば、国内向けにしか展開しておらず、深夜の時間帯にはアクセス数が極端に少ないなどの場合、別途合成モニタリングでリクエストを生成する、あるいはその時間は除外する、さまざまに条件が考えられると思います。

## 継続的に監視する

SLOを設定したあとは継続的な監視が必要になります。ところでSLOを見ると28日のローリングウィンドウで98%という目標を立てています。裏を返せば2%がSLO違反になっても良いという状況です。SLOの計算はイベントベースで計算しましたが、この2%を時間換算してみるとどれくらいになるでしょうか。

$$ 28日 \times 24時間 \times 60分 \times 60秒 \times 2\% = 48,384秒 \approx 13時間26分 $$

ここから、10分単位で28日ローリングウィンドウでのSLIを追いかけておけば、ひとまずはSLI上の悪いイベントが発生したとしても、SLO違反になるまでは十分に時間があることがわかります。したがって、10分単位のバッチ処理で先ほどのようなチャートを作ればよいでしょう。

## おわりに

ここまでモニタリングツール等のソリューションを使わずに、ログデータとPythonだけでSLOの設定をする素朴な例を行ってきました。SLO自体は簡単な計算を行なうだけですので、ちょっとした計算ツールがあれば自力でも十分に導き出せることが伝わったかと思います。

しかし、いちいちログを持ってくるのも面倒ですし、さらにメタデータが増えた場合（例：サービスのバージョンやインスタンスのリージョンなど）は、上のようなコードを都度書き換えなければいけません。昨今の各種ソリューションは、こうした用途にも十分に対応してくれています。

次の記事では、ソリューションを使った場合に、この手動のプロセスがどれほど変わるかを確認したいと思います。
