---
title: Amazon CloudWatch Application Signalsを使ってバーンレートアラームを設定しよう
emoji: 🤖
type: tech
topics:
  - AWS
  - CloudWatch
  - SRE
  - Observability
published: true
published_at: 2025-04-23 17:30
---
## はじめに
こんにちは、AWSでデベロッパーアドボケイトをしているものです。4/16にAWS Startup Loftで開催された「[春のObservavility祭り 2025](https://aws.amazon.com/startups/events/%E6%98%A5%E3%81%AE-observability-%E7%A5%AD%E3%82%8A-2025-%E3%80%9C%E9%80%B2%E5%8C%96%E3%81%99%E3%82%8B-amazon-cloudwatch-%E5%9F%BA%E7%A4%8E%E3%81%8B%E3%82%89%E6%9C%80%E6%96%B0%E6%A9%9F%E8%83%BD%E3%81%BE%E3%81%A7%E5%AE%8C%E5%85%A8%E8%A7%A3%E8%AA%AC%E3%80%9C)」というイベントで、オブザーバビリティが好きな同僚と一緒に登壇してきました。

私は Application Signals を使ってバーンレートアラームの設定が簡単にできます、という話をしました。また、そもそもバーンレートアラームがなぜ重要なのかというところから解説しました。録画がなかったのと、15分という短い時間での説明で咀嚼しづらいところもあったと思うので、この記事で登壇の内容をあらためて解説します。なお当日のスライドはこちらです。

@[speakerdeck](000b7d23ad9f4d78ab538a72ab99daa8)

## バーンレート計測の重要性

### サービスレベル指標 (SLI) とサービスレベル目標 (SLO)

バーンレートの解説をするためには、SLIとSLOの解説が必要です。SREはサービスの信頼性（ユーザーの満足度）を中心に据える開発運用手法ですが、別にSREに限らずサービスの信頼性をリアルタイムに知ることは良いことです。

SLIはサービスの特性を考えて「ユーザーの満足度に寄与していそうな指標」を擬似的に信頼性の指標として捉えるということをしています。たとえば、ECサイトであればチェックアウトにかかる時間（レイテンシー）であったり、バッチ処理のシステムであればレポートの鮮度であったり、とサービスによって変わります。

SLIは、次のような式で求められる百分率です。

$$ \text{SLI} = \frac{\text{良いイベント}}{\text{イベント全体}} $$

たとえば、良いイベントは「500ms以下のレイテンシーのレスポンスの数」で、イベント全体が「過去28日間でのレスポンスの総数」です。で、その目標値がSLOです。たとえば「レイテンシーが500ms以下のレスポンスが全体の90%」という目標値を設定できます[^slo100]（SLOはサービスの信頼性が保たれつつ、無理のない値を設定することが肝心です）

[^slo100]: SLOの説明をすると「目標値は100%です」という人が必ずいるのですが、自分のシステムの現実がどうなっているか確認するために、まずは目標値は設定せずにSLIを四半期〜半年程度追跡するのがおすすめです。100%を達成できないことを認めた上で、目標達成のためのコストと現状を鑑みて、良い目標値を決めるのが良いでしょう。

SLIとSLOに関しては以前に詳細に書いたので、こちらも参照してください。

@[card](https://zenn.dev/ymotongpoo/articles/20230329-slo-without-sre)

SLIがSLOに沿っているかどうかを監視すれば、ユーザーが満足してサービスを使えてるかどうかがわかるから、これを追跡してしきい値でアラートを出せばいいじゃん！と思いますが、そう簡単にはいきません。

SLIが下のグラフのように推移していたら、しきい値をまたぐたびにアラートが鳴り、過剰に鳴ってしまう状況になることは容易に想像できるでしょう。

![SLIのグラフ](/images/20250417153315.png)

## アラートは行動できる場合のみ発報

みなさんも経験があると思いますが、アラートが多くなりすぎると、そのうち発報されたアラートの中でも無意識に心のフィルターを作るようになり、何かいつもと違うと感じるときだけ対応するといったような状況になります。これではアラートの意味がありませんし、いくら心のフィルターを作ったとしても、アラートを都度確認することは精神的に良くありません。この状況は「アラーム疲れ（alarm fatigue）」として知られています。

「アラーム疲れ」はIT業界だけでなく、医療業界や航空業界でも長らく問題になっています[^meghan][^psnet][^randall2021]。

[^meghan]: https://www.ncbi.nlm.nih.gov/books/NBK555522/
[^psnet]: https://psnet.ahrq.gov/primer/alert-fatigue
[^randall2021]: https://pmc.ncbi.nlm.nih.gov/articles/PMC8641425/

ベストプラクティスとして「アラームはアクションが可能な状況でのみ発報すべき」とされています。Well-architected Frameworkでは「OPS08-BP04  実践的なアラートを作成する」として解説されています。

@[card](https://docs.aws.amazon.com/ja_jp/wellarchitected/latest/framework/ops_workload_observability_create_alerts.html)

W-Aではそのための対策としてAmazon CloudWatchの異常検出機能やAmazon DevOps Guru、またCloudWatchの複合アラームの設定を勧めています。しかし、ここに書かれていない対策として「エラーバジェットの追跡」、さらには「バーンレートによるアラーム」を紹介します。

## エラーバジェット
エラーバジェットは名前の通り「予算」です。なんの予算かというと悪いイベントが発生したときに消費される予算です。

エラーバジェットは次のように定義されています。

$$ \text{エラーバジェット} = \text{100\%} - \text{SLO} $$

つまりSLOの逆となる概念がエラーバジェットです。たとえば「可用性の目標値が90%」となっている場合、「10%は可用性がなかったとしても許容される」ということになります。この10%分のエラーが「予算」となるわけです。

SLOに対するSLIの現状を追跡するということは、必然的にエラーバジェットの残りを確認し続けるということになります。

![エラーバジェット](/images/20250423115040.png)

しかしエラーバジェットに置き換えたからと言って、それが枯渇したとき（SLIがSLOを割り込んだとき）に都度アラームを鳴らしていたのでは先の場合と変わりません。また、ユーザーがシステムに不満を持つ前に早めに手を打ちたいものです。そこでバーンレートという考え方を導入します。

## バーンレート
スタートアップ界隈では「バーンレート」と聞いて胃を痛める人もいるのではないかと思います。スタートアップ界隈で語られるバーンレートにはいくつかの種類がありますが、概ね「1ヶ月あたりにかかるコスト」を指します。手元資金をそのコストで割れば「ランウェイ」、つまり会社の生存期間が計算できます。

それと同じことをエラーバジェットを使って行うのがSREの文脈でのバーンレートです。エラーバジェットが減る速度がバーンレートとなります。エラーバジェットを計算するときに、そもそもその予算というのはSLIの計算をするウィンドウがあるので、ランウェイはすなわちそのウィンドウになります。最初のSLIの例で言えば28日です。28日でエラーバジェットを使い切る消費速度はバーンレート1となります。

![バーンレート](/images/20250423115355.png)

このバーンレートの大きさで緊急度が変わってきます。バーンレート2の場合は、予想の半分の期間でエラーバジェットを使い切ってしまうということになります。このときもともと28日で計算していたのであれば、半分でも14日（2週間）あるので、状況としてはよくないですが、問題修正のほうを優先して対応すれば、業務時間に余裕を持って解決できる可能性が十分あります。

一方でバーンレート10の場合は2.8日しかありません。これは週末を挟んだ場合、月曜に出社してきてみたらもうエラーバジェットは枯渇寸前、ユーザーに影響がある問題が発生することが目に見えた状態になります。したがって、バーンレート10は緊急対応に備えた体制を敷く必要がある値となります。

肝心なのは、バーンレートを使うことでエラーバジェットが枯渇する前に状況の把握ができるということです。ここまで SLI → SLO → エラーバジェット → バーンレート と一本道でつながっていることがわかるかと思います。これが私がAIモデルを使ったり複雑な条件を組み合わせたアラートよりも、バーンレートを使ったアラートを好む理由です。

## バーンレートの計算は少し手間

いますぐにバーンレートを使った計算をしたいところですが、ここで少し問題があるのは、バーンレートの計算までに2段階、ローリングウィンドウでの計算が必要になるということです。

1つめはSLIの計算で、計算式は本記事の最初の方ですでに書いています。

2つめのバーンレートの計算は、エラーバジェットとルックバックウィンドウで計算します[^burnrate]。

$$ \text{バーンレート} = \frac{\text{エラーバジェットの差分}}{\text{ルックバックウィンドウのSLO期間に対する割合}} $$

[^burnrate]: 概念としては上記ですが、実際に計算する場合にはエラーバジェットの差分は直接取れないので、ルックバックウィンドウ内でのエラー率とSLOで許容されるエラー率での比を計算します。

これを計算するのは手間ですが、多くのオブザーバビリティSaaSでは、SLIに使うメトリクスだけ入れていればバーンレートの計算まで全部自動で行ってくれるものが多いです。

## Application Signalsでのバーンレートアラーム

Application Signals は名前の通りアプリケーションに関するテレメトリーシグナルを扱う多くの機能があって、その中にSLOモニタリングがあります。これはこれまで説明してきたようなSLOに対するSLIの状況、エラーバジェットの状況、バーンレートをひと目で確認できるダッシュボードを提供しています。

![SLOダッシュボード](/images/20250423135355.png)

また、SLOを設定する際に、それに必要なバーンレートアラームの設定を同時にできるようになっています。（バーンレートアラーム自体はCloudWatchアラーム自体の機能です）

まずSLIを設定します。
![SLIの設定](/images/20250423140213.png)

次にSLOを設定します。
![SLOの設定](/images/20250423140245.png)

そしてバーンレートを設定します。
![バーンレートの設定](/images/20250423140311.png)

最後にそのアラーム条件となるバーンレート値を設定して完了です。
![バーンレート値の設定](/images/20250423140317.png)

設定したアラームはCloudWatchアラームで確認できます。
![CloudWatchアラーム](/images/20250423140547.png)
## まとめ

バーンレートアラームの意味について解説しました。まだまだバーンレートアラームの活用は一般的ではないと思うので、それが当たり前のものとして認識されるまで、これからもこういった記事を書き続けたいと思います。

