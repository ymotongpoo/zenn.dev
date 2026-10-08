---
title: "Perl実装にいま必要なもの"
---

## 実験で残った課題

「Perlに足りないのは公式のSIGだ」と考えたくなります。しかし、この本の実験で見つかった課題の多くは、SIGが無いことではなく具体的なコードと文書の不足から来ていました。次の表は、それらの課題を修正先ごとに並べたものです。

| 課題 | 種類 | 確かめた章 | 修正先 |
| --- | --- | --- | --- |
| Batchプロセッサーが `OTEL_BSP_SCHEDULE_DELAY` の間隔で送らず、キューが512件に達するまで送らない | SDKの未実装 | 8章 | [perl-opentelemetry-sdk](https://github.com/jjatria/perl-opentelemetry-sdk) |
| IO::Asyncのループを回さないアプリケーションでは、送信が止まる（本書の構成では8回）。Mojoliciousでの方法はGuidesにあるが、PSGIサーバーでの回避策は無い | SDKの設計と文書 | 8章 | perl-opentelemetryのGuides |
| `shutdown` がキューを送らずに捨てる | SDKの不具合 | 4章、8章 | perl-opentelemetry-sdk |
| SIGTERMで終了するとき、`shutdown` がタイムアウトを過ぎても戻らない | SDKの不具合の可能性（原因は未特定） | 8章 | perl-opentelemetry-sdk |
| プロセスの終了時に、SDKが `shutdown` も `force_flush` も呼ばない | ライフサイクルの改善提案（仕様の要求ではない） | 8章 | perl-opentelemetry-sdk |
| `in_span` が、例外が無ければステータスをOKにし、ブロックの中で設定したERRORも上書きする | APIの振る舞い（仕様はステータスを通常は未設定のままにするよう求めている） | 5章 | [perl-opentelemetry](https://github.com/jjatria/perl-opentelemetry) |
| OTLP/JSONで送ると、数値の属性も文字列になる | OTLPエクスポーターのJSONエンコーダー | 5章、6章 | [perl-opentelemetry-exporter-otlp](https://github.com/jjatria/perl-opentelemetry-exporter-otlp) |
| Plackのミドルウェアのスパン名と `server.address`、`server.port` がセマンティック規約と食い違い、SDKに依存している | 計装ライブラリ | 5章 | [Plack-Middleware-OpenTelemetry](https://github.com/abh/Plack-Middleware-OpenTelemetry) |
| ログは試験版のSDKでしか送れず、メトリクスはAPIも無い | 未実装 | 7章 | perl-opentelemetry、perl-opentelemetry-sdk |
| 0.029-TRIALのSDKを読み込んだプログラムが、トレースとログの両方にBatchプロセッサーがあると終了しない | 試験版の不具合（原因は未調査） | 7章 | perl-opentelemetry-sdk（[#24に報告済み](https://github.com/jjatria/perl-opentelemetry-sdk/issues/24#issuecomment-6048489586)） |
| READMEやPODが実装より古い、または実装と食い違う | 文書 | 3章、6章、7章 | 各リポジトリ |
| OBIの伝搬に必要なマウントが、Dockerのセットアップの説明からたどれない | OBIの文書 | 9章 | [opentelemetry.io](https://github.com/open-telemetry/opentelemetry.io)のOBIのドキュメント |
| OBIがPerlのイベントループで並行するリクエストの親子を誤って対応づける。ドキュメントのLimitationsが述べる制約の範囲で、Perl向けのランタイム固有の仕組みが無い | OBIの未実装 | 9章 | [opentelemetry-ebpf-instrumentation](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation) |
| 本書の構成では、OBIがPerlのプロセスの `OTEL_SERVICE_NAME` を使わなかった | 原因は未調査（v0.14.0には環境変数を読むコードとテストがある） | 9章 | opentelemetry-ebpf-instrumentation |

READMEの古さは、たとえば次のような記述です。APIのREADMEには、APIの具体的な実装は「None exists at the moment」とあり、SDKの存在と食い違っています。SDKのREADMEは「Currently only distributed traces are supported」のままで、0.029-TRIALのログには触れていません。7章で見た、`Log::Any` のアダプターのPODが説明する環境変数の読み順とコードの違いも、同じ種類の課題です。

## 最初に着手できる作業

表の中で、いちばん小さく始められるのは `shutdown` の不具合です。再現は、4章で示した6行のスクリプトで済みます。`shutdown` だけを呼ぶとCollectorに1件も届かず、先に `force_flush` を呼ぶと届きます。原因は、8章で見た終了済みのフラグを立てる順序なので、修正の範囲も狭いはずです。SDKのテストには、モックのエクスポーターでBatchプロセッサーを検査するテストがすでにあります。そこに「`shutdown` の後にキューのスパンがエクスポーターに渡されたか」を確かめるテストを足せば、修正が正しいことを示せます。0.029-TRIALでも同じ順序なので、ログのBatchプロセッサーにも同じ修正が有効です。

IO::Asyncのループの問題については、作者がissue #23で文書化の必要を認めています。最初の作業は、Guidesに説明を足すことです。GuidesにはMojoliciousでの方法がすでにあるので、足すのはPSGIのアプリケーションの場合です。ミドルウェアでループを進めればよいことと、終了時に `force_flush` を呼ぶ必要があることを書きます。Guidesにこの2点があれば、利用者は8章の回避策を探し当てずに済みます。

`OTEL_BSP_SCHEDULE_DELAY` で送る機能を作るのは、それより大きな作業です。IO::Asyncのループを回さないプロセスで、5秒ごとに何かを動かす仕組みそのものが無いからです。アプリケーションのプロセスの中で送信できるようにする変更は、2023年11月にSDKの[pull request #7](https://github.com/jjatria/perl-opentelemetry-sdk/pull/7)として出され、デバッグ用の提案としてdraftのまま残っています。作者の返答は、この形でマージするものではないとしつつ「it must not block the main process」というものでした。メインのプロセスを止めずに定期的に送る仕組みをどう作るかは、作者と相談しながら決めることになります。

Plackのミドルウェアは、APIとSDKとは別の作者のリポジトリです。スパン名を `{method}` に、`server.address` と `server.port` を分けて入れる修正は、セマンティック規約の該当箇所を示せば説明できます。SDKへの依存を外すには、`resource_attributes` のオプションをどう扱うかを決める必要があります。

OBIの側の課題は性質が違います。マウントの説明について必要なのは、Dockerのセットアップのページから参照できるようにする修正です。この修正は、opentelemetry.ioのドキュメントへのpull requestで済みます。Perlのイベントループでの親子の対応づけは、AnyEventやMojoliciousに固有の仕組みをOBIに足す作業です。9章で見たNode.jsやPythonのasyncioと同じ規模の対応が必要になります。

## 参加する場所

CPANの実装を議論する場は、作者のGitHubのリポジトリにあるissueとpull requestです。APIとSDKのREADMEは、`irc.perl.org` の `#io-async` チャンネルも案内しています。チャンネルでいまどれだけ会話があるかは、筆者は確かめていません。

公式のSIGへの関心を示す場所は、3章で見たcommunityの[issue #828](https://github.com/open-telemetry/community/issues/828)です。SIGは、言語の実装を長く保守する人が集まって初めて成立します。その他の言語のページは、SIGの設立が要望されている言語の一覧です。PerlがSIGとともに公式のプロジェクトになれば、Perlの名前は言語別のページのほうへ移るはずです。

SIGの成立と、表の課題が片づくことは別の話です。表の課題のほとんどは、CPANの配布物とOBIのリポジトリへのissueとpull requestで進められます。SIGが無くても実装は直せますが、SIGができても、誰かが直さない限りBatchプロセッサーは5秒ごとには送りません。

## 結び

最初に `app_otel.psgi` を動かしたとき、Collectorに届いたのはGoのスパンだけでした。ただ、そのGoのスパンにはPerlのスパンを指す親のIDが入っていました。PerlとGoの間でトレースコンテキストを渡す部分は、最初から動いていたことになります。Perlのスパンが届かなかった理由は、SDKの中の送信の契機と終了処理、そしてそれを説明する文書でした。

言語の違うサービスを1本のトレースにつなぐための部品は、CPANとPlack/PSGIの上にほとんどそろっています。残っているのは本書の表に並んだ作業で、どれも再現の手順と修正先が分かっています。そのうちのいくつかは、文書を直すかテストを1つ足せば正しさを示せる大きさです。それを誰が直し、誰が保守し続けるのかは、まだ決まっていません。
