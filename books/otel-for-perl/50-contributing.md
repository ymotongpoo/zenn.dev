---
title: "Perl実装にいま必要なもの"
---

## 実験で残った課題

「Perlに足りないのは公式のSIGだ」と考えたくなります。しかし、この本の実験で見つかった課題の多くは、SIGが無いことではなく具体的なコードと文書の不足から来ていました。次の表は、それらの課題を修正先ごとに並べたものです。

| 課題 | 種類 | 確かめた章 | 修正先 |
| --- | --- | --- | --- |
| Batchプロセッサーが `OTEL_BSP_SCHEDULE_DELAY` の間隔で送らず、キューが512件に達するまで送らない | SDKの未実装 | 8章 | [perl-opentelemetry-sdk](https://github.com/jjatria/perl-opentelemetry-sdk)（[#27に報告済み](https://github.com/jjatria/perl-opentelemetry-sdk/issues/27)、実装を[PR #30](https://github.com/jjatria/perl-opentelemetry-sdk/pull/30)で提案） |
| Batchプロセッサーが最大8つの送信を同時に走らせ、送信のたびに接続を作り直す。仕様は `Export` を同時に呼ばないことを求めている | SDKの仕様違反と設計 | 8章 | perl-opentelemetry-sdk（PR #30で設計を議論中） |
| IO::Asyncのループを回さないアプリケーションでは、送信が止まる（本書の構成では512件の6〜8回分）。Batchプロセッサーにはループが必要という原則が、Guidesに書かれていない | SDKの設計と文書 | 8章 | perl-opentelemetryのGuides（[#23](https://github.com/jjatria/perl-opentelemetry/issues/23)で相談。作者はFAQの形の文書を検討中） |
| ループを回さないアプリケーションに向くSimpleプロセッサーを、環境変数で選べない | SDKの設定 | 4章、8章 | perl-opentelemetry-sdk |
| `shutdown` がキューを送らずに捨てる | SDKの不具合 | 4章、8章 | perl-opentelemetry-sdk（[#25](https://github.com/jjatria/perl-opentelemetry-sdk/issues/25)に報告。作者が[49f3453](https://github.com/jjatria/perl-opentelemetry-sdk/commit/49f3453adddf1b8661cc565a6371bc4f2287decb)で修正、未リリース） |
| SIGTERMで終了するとき、`shutdown` がタイムアウトを過ぎても戻らない | SDKの不具合の可能性（原因は未特定） | 8章 | perl-opentelemetry-sdk |
| `shutdown` や `force_flush` のFutureを待ち時間の途中で取り消すと、perlがセグメンテーション違反で落ちる | SDKの `defer` とFuture::AsyncAwaitの組み合わせ | 11章 | perl-opentelemetry-sdk（[#31に報告済み](https://github.com/jjatria/perl-opentelemetry-sdk/issues/31)） |
| プロセスの終了時に、SDKが `shutdown` も `force_flush` も呼ばない | ライフサイクルの改善提案（仕様の要求ではない） | 8章 | perl-opentelemetry-sdk |
| `in_span` が、例外が無ければステータスをOKにし、ブロックの中で設定したERRORも上書きする | APIの振る舞い（仕様はステータスを通常は未設定のままにするよう求めている） | 5章 | [perl-opentelemetry](https://github.com/jjatria/perl-opentelemetry)（[#35に報告済み](https://github.com/jjatria/perl-opentelemetry/issues/35)） |
| OTLP/JSONで送ると、数値の属性も文字列になる | OTLPエクスポーターのJSONエンコーダー | 5章、6章 | [perl-opentelemetry-exporter-otlp](https://github.com/jjatria/perl-opentelemetry-exporter-otlp)（[#15に報告済み](https://github.com/jjatria/perl-opentelemetry-exporter-otlp/issues/15)） |
| Plackのミドルウェアのスパン名と `server.address`、`server.port` がセマンティック規約と食い違い、SDKに依存している | 計装ライブラリ | 5章 | [Plack-Middleware-OpenTelemetry](https://github.com/abh/Plack-Middleware-OpenTelemetry)（[#10にコメント](https://github.com/abh/Plack-Middleware-OpenTelemetry/issues/10#issuecomment-6049918698)、[#11に報告](https://github.com/abh/Plack-Middleware-OpenTelemetry/issues/11)） |
| メトリクスはAPIもSDKも無い | 未実装 | 7章 | perl-opentelemetry、perl-opentelemetry-sdk |
| SDK 0.100を読み込んだプログラムが、何も設定しないと終了せず、PSGIサーバーの停止にも10秒以上かかる。ログのBatchプロセッサーの破棄で、ワーカーの終了を待つ処理が戻らない | SDKの不具合（起きる条件は未特定） | 4章、8章 | perl-opentelemetry-sdk（[#24に報告済み](https://github.com/jjatria/perl-opentelemetry-sdk/issues/24#issuecomment-6260524108)。作者がmainで待ちをやめ、筆者が待ちを残す修正を[PR #32](https://github.com/jjatria/perl-opentelemetry-sdk/pull/32)で提案） |
| READMEやPODが実装より古い、または実装と食い違う | 文書 | 3章、6章、7章 | 各リポジトリ（`Log::Any` のアダプターの件は[#34に報告済み](https://github.com/jjatria/perl-opentelemetry/issues/34)） |
| OBIの伝搬に必要なマウントが、Dockerのセットアップの説明からたどれない | OBIの文書 | 9章 | [opentelemetry.io](https://github.com/open-telemetry/opentelemetry.io)のOBIのドキュメント（[PR #12006](https://github.com/open-telemetry/opentelemetry.io/pull/12006)） |
| OBIがPerlのイベントループで並行するリクエストの親子を誤って対応づける。ドキュメントのLimitationsが述べる制約の範囲で、Perl向けのランタイム固有の仕組みが無い | OBIの未実装 | 9章 | [opentelemetry-ebpf-instrumentation](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation) |
| 本書の構成では、OBIがPerlのプロセスの `OTEL_SERVICE_NAME` を使わなかった | 原因は未調査（v0.14.0には環境変数を読むコードとテストがある） | 9章 | opentelemetry-ebpf-instrumentation |

READMEの古さは、たとえば次のような記述です。APIのREADMEには、APIの具体的な実装は「None exists at the moment」とあり、SDKの存在と食い違っています。SDKのREADMEは「Currently only distributed traces are supported」のままで、0.100で入ったログには触れていません。7章で見た、`Log::Any` のアダプターのPODが説明する環境変数の読み順とコードの違いも、同じ種類の課題です。

## 最初に着手できる作業

表の中で、いちばん小さく始められるのは `shutdown` の不具合です。再現は、4章で示した短いスクリプトで済みます。`shutdown` だけを呼ぶとCollectorに1件も届かず、先に `force_flush` を呼ぶと届きます。原因は、8章で見た終了済みのフラグを立てる順序なので、修正の範囲も狭いはずです。SDKのテストには、モックのエクスポーターでBatchプロセッサーを検査するテストがすでにあります。そこに「`shutdown` の後にキューのスパンがエクスポーターに渡されたか」を確かめるテストを足せば、修正が正しいことを示せます。0.100のBatchプロセッサーはトレースとログに共通なので、同じ修正でログの `shutdown` も直るはずです。筆者は2026年10月8日に、修正と回帰テストを[pull request #26](https://github.com/jjatria/perl-opentelemetry-sdk/pull/26)として送りました。作者は、同じ問題をもっと短い変更で直すコミットをmainに入れ、#26を閉じました。終了済みの印を立てる時点を、`force_flush` の後に遅らせる1行の変更です。筆者はそのmainで再現手順を試し、`shutdown` だけでも3件届くことを作者に伝えました。

0.100で終了しなくなった不具合は、作者と見方が分かれています。作者の見方では、ループを回さないプログラムでSDKを読み込むこと自体が誤った使い方です。筆者は、ループを回し、トレースのプロバイダーを正しく止めるスクリプトでも止まることを[返信](https://github.com/jjatria/perl-opentelemetry-sdk/issues/24#issuecomment-6279831126)しました。直す場所の見当は付いています。Batchプロセッサーは、破棄されるときにワーカーの停止を `get` で待つ作りです。この待ちを、プロセスの終了の途中でPerlがオブジェクトを破棄しているとき（`${^GLOBAL_PHASE}` が `DESTRUCT` のとき）だけ省くと、4章の再現手順を5回試して5回ともプロセスが終了し、Starmanの停止も10.5秒から1秒未満になりました。作者は、プロセスの終了の途中で起きる別の不具合を[#29](https://github.com/jjatria/perl-opentelemetry-sdk/issues/29)として分けていて、この2つが関係するかどうかはまだ分かっていません。

作者はこの案を「a fine solution」と[返し](https://github.com/jjatria/perl-opentelemetry-sdk/issues/24#issuecomment-6286777768)、10月22日に、破棄のときに待つ処理そのものをやめる変更（コミット[02e92dd](https://github.com/jjatria/perl-opentelemetry-sdk/commit/02e92dd0cc8c3bd3345862de6140e17ca0b1e1f1)）をmainに入れました。mainでプログラムが終了することは、4章で見たとおりです。代わりに、SDKのCIのテストが、すべてのPerlのバージョンで失敗するようになりました。原因は、止められたワーカーの後始末です。ワーカーは終了コード255で終わり、待たなくなったので誰もそれを回収しません。テストの最後にTest2がそのワーカーを回収し、「did not exit cleanly」と報告していました。

筆者は、グローバルデストラクションの中と、forkで受け継いだプロセッサーのときだけ待たない変更を[pull request #32](https://github.com/jjatria/perl-opentelemetry-sdk/pull/32)として送りました。forkした子のプロセスにとって、ワーカーは親の子なので、待っても終了を受け取れません。待つときの単位は、1秒のタイムアウトを渡したループの1回分です。ワーカーの終了を知らせるSIGCHLDがループの待ちの直前に届くと、PerlはループのI/Oの待ちが戻るまでハンドラーを動かしません。タイムアウトの無い待ちでは、そのまま待ち続けることがあるからです[^sigchld]。

[^sigchld]: IO::Async::Loopのソースのコメントが、この競合を説明しています。対策として待ちを最長1秒にする仕組みは、シグナルの代理（sigproxy）を使うループだけのもので、`IO::Async::Loop::Poll` は使いません。自然には再現できなかったので、SIGCHLDを遅らせて届けるテストで確かめました。`shutdown` もワーカーの停止を同じように待つので、同じ競合が起こりえます。8章で `shutdown` が戻らなかった原因かどうかは確かめていません。

IO::Asyncのループの問題については、作者がissue #23で文書化の必要を認めています。PSGIサーバーでの測定結果と回避策は、同じissueに[コメント](https://github.com/jjatria/perl-opentelemetry/issues/23#issuecomment-6049916551)しました。作者の[返答](https://github.com/jjatria/perl-opentelemetry/issues/23#issuecomment-6150108237)は、フレームワークごとの手順よりも、「an event loop is needed if you are using the batch processor」（Batchプロセッサーを使うならイベントループが必要）という原則を説明したい、というものでした。筆者が、ループの無いアプリケーションにはSimpleプロセッサーを勧める節を足す案を示すと、作者は8章で紹介したとおり、回すループを見つけるほうを勧めるべきだと返しました。8章で測ったNet::Async::HTTP::Serverは、その具体例です。作者は#24で、FAQの形の文書を検討しているとも書いています。筆者は文書の形を作者に任せ、作者が勧めたサーバーで測った結果を伝えることにしました。

`OTEL_BSP_SCHEDULE_DELAY` で送る機能は、当初はそれより大きな作業だと考えていました。IO::Asyncのループを回さないプロセスには、5秒ごとに何かを動かす仕組みそのものが無いからです。定期的に送られないことを[issue #27](https://github.com/jjatria/perl-opentelemetry-sdk/issues/27)として報告すると、作者はこの機能を実装するpull requestを歓迎し、IO::Asyncのタイマーを使う方法を望むと返しました[^pr7]。8章で引用したとおり、ループを回さないアプリケーションはそもそもBatchプロセッサーを使わない前提です。タイマーは、IO::Asyncのループの中で動けば十分です。筆者が `IO::Async::Timer::Countdown` で実装する設計を[返信](https://github.com/jjatria/perl-opentelemetry-sdk/issues/27#issuecomment-6260523597)すると、作者は設計を妥当とし、送信の最中にタイマーが次の送信を始める競合に気を付けるよう求めました。筆者は、どの経路の送信でも、送信中はタイマーで送らない形で実装し、2026年10月20日に[pull request #30](https://github.com/jjatria/perl-opentelemetry-sdk/pull/30)として送りました。8章のNet::Async::HTTP::Serverの測定で、すべてのスパンが届いた版です。

作者は10月22日に、PR #30へ12件の行ごとのコメントを付けました。なぜ `force_flush` が実行中の送信を待つのか、定期送信の最中に満杯になったバッチをなぜ待たせるのか、という問いが中心です。筆者は満杯のバッチを待たせる仕組みをやめ、記録に受け取った順の番号を付ける形に書き直しました。`force_flush` が待つのは、呼ばれる前に受け取った記録を含む送信のすべてです。`shutdown` は、ワーカーを止める前に、ワーカーの空きを待っている呼び出しも含めてすべての送信を待ちます。IO::Async::Functionの `stop` は、その時点で動いているワーカーしか待たないからです。

書き直す途中で、SDKの外に原因がある不具合も見つかりました。asyncのメソッドが `defer` のブロックに入った後で、そのFutureを取り消すと、perlが落ちます。落ちる条件は、`defer` のブロックがメソッド自身の変数を使うことです。OpenTelemetryのコードが無くても再現します。SDKの `shutdown` を時間切れのFutureと `Future->wait_any` で競わせるだけで起きるのは、`wait_any` が先に終わらなかったFutureを取り消すからです。この件は[issue #31](https://github.com/jjatria/perl-opentelemetry-sdk/issues/31)として報告しました。

10月23日には、APIのリポジトリにpull requestを送っているabraxxa[^abraxxa]が、PR #30に設計の文書が要ると書きました。forkを使う今の作りでは動かなくなる箇所が何か所もあること、送信を同時に走らせる理由が無いこと、TLSの接続は1本にしたいことを挙げています。abraxxa自身が使っているのは、1つの子プロセスにすべての記録を送る方式で、2週間ほどでSDKに入れたいとのことです。8章で測ったとおり、0.100の送り方は、送信を同時に走らせないという仕様の要求を満たしていません。筆者はその測定結果を返し、合意した設計に合わせてPR #30を直すか閉じると[伝えました](https://github.com/jjatria/perl-opentelemetry-sdk/pull/30#issuecomment-6381564808)。定期送信をどこで動かすかは、Batchプロセッサーの送り方の設計が決まってからになります。

[^abraxxa]: [abraxxa](https://github.com/abraxxa)は、APIのリポジトリに[Log4perlのアペンダー](https://github.com/jjatria/perl-opentelemetry/pull/20)や[DBIの接続のスパン](https://github.com/jjatria/perl-opentelemetry/pull/30)のpull requestを送っているコントリビューターです（2026年10月28日の時点）。

[^pr7]: アプリケーションのプロセスの中で送信できるようにする変更は、2023年11月にSDKの[pull request #7](https://github.com/jjatria/perl-opentelemetry-sdk/pull/7)として出され、デバッグ用の提案としてdraftのまま残っています。作者の返答は、この形でマージするものではないとしつつ「it must not block the main process」というものでした。

Plackのミドルウェアは、APIとSDKとは別の作者のリポジトリです。スパン名については、スパン名の付け方を話し合っていた既存のissue #10に規約の該当箇所を[コメント](https://github.com/abh/Plack-Middleware-OpenTelemetry/issues/10#issuecomment-6049918698)し、`server.address` とSDKへの依存は[issue #11](https://github.com/abh/Plack-Middleware-OpenTelemetry/issues/11)で提案しました。スパン名を `{method}` にする修正と、`server.address` と `server.port` を分けて入れる修正は、セマンティック規約の該当箇所を根拠に説明できる内容です。SDKへの依存を外すには、`resource_attributes` のオプションをどう扱うかを決める必要があります。

OBIの側の課題は性質が違います。マウントの説明について必要なのは、Dockerのセットアップのページから参照できるようにする修正です。この修正は、opentelemetry.ioのドキュメントへのpull requestで済みます（[#12006](https://github.com/open-telemetry/opentelemetry.io/pull/12006)として送りました）。Perlのイベントループでの親子の対応づけは、AnyEventやMojoliciousに固有の仕組みをOBIに足す作業です。9章で見たNode.jsやPythonのasyncioと同じ規模の対応が必要になります。

## 参加する場所

CPANの実装を議論する場は、作者のGitHubのリポジトリにあるissueとpull requestです。APIとSDKのREADMEは、`irc.perl.org` の `#io-async` チャンネルも案内しています。チャンネルでいまどれだけ会話があるかは、筆者は確かめていません。

公式のSIGへの関心を示す場所は、3章で見たcommunityの[issue #828](https://github.com/open-telemetry/community/issues/828)です。SIGは、言語の実装を長く保守する人が集まって初めて成立します。その他の言語のページは、SIGの設立が要望されている言語の一覧です。PerlがSIGとともに公式のプロジェクトになれば、Perlの名前は言語別のページのほうへ移るはずです。

SIGの成立と、表の課題が片づくことは別の話です。表の課題のほとんどは、CPANの配布物とOBIのリポジトリへのissueとpull requestで進められます。SIGが無くても実装は直せますが、SIGができても、誰かが直さない限りBatchプロセッサーは5秒ごとには送りません。

## 結び

最初に `app_otel.psgi` を動かしたとき、Collectorに届いたのはGoのスパンだけでした。ただ、そのGoのスパンにはPerlのスパンを指す親のIDが入っていました。PerlとGoの間でトレースコンテキストを渡す部分は、最初から動いていたことになります。Perlのスパンが届かなかった理由は、SDKの中の送信の契機と終了処理、そしてそれを説明する文書でした。

言語の違うサービスを1本のトレースにつなぐための部品は、CPANとPlack/PSGIの上にほとんどそろっています。残っているのは本書の表に並んだ作業で、どれも再現の手順と修正先が分かっています。そのうちのいくつかは、文書を直すかテストを1つ足せば正しさを示せる大きさです。Batchプロセッサーの送り方のように、直す前に設計の合意が要る作業もあります。これらを誰が直し、誰が保守し続けるのかは、まだ決まっていません。
