---
title: "議論から提案へ"
---

## math/rand/v2という先例

2023年10月5日、Joe Tsai が GitHub の [Discussion #63397](https://github.com/golang/go/discussions/63397)（"encoding/json/v2"）を起票します。プロトタイプの最初のコミットから、ほぼ3年が経っていました。

なぜこのタイミングだったのでしょうか。2日前の10月3日に `math/rand/v2` の提案 [`golang/go#61716`](https://github.com/golang/go/issues/61716) が受理されています。

`math/rand/v2` の提案を出した Russ Cox は、同年6月に [Discussion #60751](https://github.com/golang/go/discussions/60751) を "math/rand/v2: a new API for math/rand **and a first v2 for std**" というタイトルで起票していました。標準ライブラリで最初のv2である、と自ら位置づけたものです。

そもそも標準ライブラリにv2を置いてよいのか、という問い自体が、そこまで決まっていませんでした。それが可能であること確認された2日後に、　`encoding/json/v2` の議論が始まっています。

## 何が論点になったか

Discussion #63397 には多くのコメントやThumb upが集まりました。文中には、mvdan、johanbrandhorst、rogpeppe、chrishines、rsc の意見を取り入れて書かれたと明記されています。

主な論点は次の4つです。

| 論点 | v1 | v2 | 議論 |
|---|---|---|---|
| マップの出力順序 | キーをソートして決定的な順序 | 非決定的な順序 | テストや差分の取りやすさを重視する立場から反対が多く出た。ソートのコストをデフォルトで全員に負わせない判断になり、必要な人は `Deterministic` オプションを指定する形に落ち着いた |
| nilのスライスとマップ | `null` | `[]` と `{}` | 往復変換が崩れる、Goのnilという情報が消える、という反対があった |
| `omitempty` の判定基準 | Goの値として空か（`false`、`0`、nilポインタ、空文字列など） | JSONとして空の値になるか | 判定の基準が、Goの型システムからJSONの型システムへ移った |
| `null` をnullableでないGoの型に入れたとき | エラーにしない | エラーにしない | 拒否すべきだという意見が出たが、「妥当なJSONを、Goの型システムの都合で拒否すべきではない」として退けられた |

## v1の永久サポート

議論のなかで繰り返し出た懸念が、v1が非推奨になるのではないかというものでした。

これに対する回答は明確でした。現在の `encoding/json` のドキュメントには、次の一文が入っています。

> All new usages of "json" in Go should use the v2 package, but the v1 package will forever remain supported.
>
> （Goで新しくjsonを使う場合はすべてv2パッケージを使うべきですが、v1パッケージは永久にサポートされ続けます。）

同じ2023年10月、GopherCon 2023 で Joe Tsai が["The Future of JSON in Go" という講演](https://www.youtube.com/watch?v=avilmOcHKHE)を行っています。Discussion が開かれたのと同じ週です[^gophercon2023]。

[^gophercon2023]: GopherConでは会期前日にContributor Summitと呼ばれる、Goのコアチームと、Goへの高い貢献を行っている開発者との会合が行われることが通例です。おそらくその場でオフラインの会話がされたのだと筆者は推測しています。（Russ Coxによる[Contributor Summitの案内](https://groups.google.com/g/golang-dev/c/kjQtT1Dyqeg)）

## 提案と機能の凍結

議論から提案までは1年3ヶ月かかりました。2025年1月31日、[`golang/go#71497`](https://github.com/golang/go/issues/71497) が起票されます。`encoding/json/v2` と `encoding/json/jsontext` の2本立てです。Joe Tsai は[提案の本文](https://github.com/golang/go/issues/71497#issue-2830866440)で、これを「標準Goパッケージのこれまでで最大の改訂」（the largest major revision of a standard Go package to date）と呼んでいます。

議論から提案にかけて、名前がいくつか変わりました。プロトタイプの `MarshalWriter` / `MarshalNext` は `MarshalWrite` / `MarshalEncode` になり、Discussion 段階の `MarshalerV2` / `UnmarshalerV2` は `MarshalerTo` / `UnmarshalerFrom` になりました。

レビューが進むなかで、機能を追加しない姿勢が明示されます。2026年4月10日の [Damien Neil のコメント](https://github.com/golang/go/issues/71497#issuecomment-4224664008)です。

> We're trying to get the already huge existing proposal over the line, and really want to avoid additional feature creep at this point. We're much more likely to temporarily withdraw features from the v2 for the initial release so we can consider them in isolation than we are to add new ones.
>
> （すでに巨大になっている既存の提案を通しきろうとしているところで、この段階でこれ以上の機能追加は本当に避けたいところです。新しいものを足すより、初回リリースではv2から機能を一時的に取り下げて、切り離して検討できるようにするほうがずっとありそうです。）

これが姿勢の表明で終わらなかったことは、リリースの直前になって分かります。

## GOEXPERIMENTでの試験導入

提案が出た2025年の8月、[Go 1.25](https://go.dev/doc/go1.25) が `GOEXPERIMENT=jsonv2` としてv2を同梱します。環境変数を設定してビルドしたときだけ、`encoding/json/v2` と `encoding/json/jsontext` が使えます。指定しなければ、同梱されません。

2025年9月9日、Go公式ブログに["A new experimental Go API for JSON"](https://go.dev/blog/jsonv2-exp)が掲載されます。

> [The effort] has been largely developed and promoted by people not employed by Google, demonstrating that the Go project is a collaborative endeavor.
>
> （この取り組みの多くは、Googleに雇用されていない人たちによって開発され、推進されてきました。それはGoプロジェクトが共同の営みであることを示しています。）

2025年11月20日には json/v2 のワーキンググループが設けられ、週次の会議と議事録の公開が始まります。

## time.Durationの決着

この期間に決まったことの一つに、`time.Duration` の扱いがあります。プロジェクト全体の考え方が、ここに凝縮されています。

v1は `time.Duration` をナノ秒の整数で出します。[`golang/go#71631`](https://github.com/golang/go/issues/71631) は、v2でどうするかを決めるための sub-proposal でした。

2025年12月11日、ワーキンググループでの議論を受けて [Damien Neil が結論を書きます](https://github.com/golang/go/issues/71631#issuecomment-3644080918)。

> JSONv1 marshals durations as integer nanoseconds. We feel that this was a clear mistake: There's no indication of what the unit is, making unit conversion errors too easy. Also, nanoseconds overflow float64 in only 104 days.
>
> （JSONv1 は duration をナノ秒の整数としてマーシャルします。これは明白な誤りだったと我々は考えています。単位が何であるかの表示がなく、単位換算の誤りが起きやすいです。加えて、ナノ秒はわずか104日でfloat64を溢れさせます。）

JSONを受け取る側がJavaScriptなら、104日を超える期間は精度を失います。では何に変えるのでしょうか。

> The world seems to be converging on ISO 8601 … If we were starting from scratch, then this seems like the right choice.
> However, changing representations silently is hazardous. If we change the default representation of `time.Duration`, then users switching from `encoding/json.Marshal` to `encoding/json/v2.Marshal` may be unexpectedly broken by the change.
>
> （世の中はISO 8601に収束しつつあるようです。ゼロから始めるなら、これが正しい選択に見えます。しかし表現を黙って変えるのは危険です。`time.Duration` のデフォルトの表現を変えれば、`encoding/json.Marshal` から `encoding/json/v2.Marshal` に切り替えたユーザーが、その変更で予期せず壊れるかもしれません。）

そして結論はこうあります。

> Our conclusion is that we don't want to keep the old default (nanoseconds), but we also don't want to silently change the representation of durations. Therefore, `encoding/json/v2` should require the user to specify a format.
>
> （私たちの結論は、古いデフォルト値であるナノ秒を保ちたくはないが、duration の表現を黙って変えたくもない、というものです。したがって `encoding/json/v2` は、利用者に形式の指定を要求すべきです。）

新たな提案が出ました。v2で `time.Duration` をそのまま `Marshal` するとエラーになります。形式を明示したときだけ通ります。「間違ったデフォルトを引き継ぐ」でも「黙って正しいデフォルトに変える」でもなく、「デフォルトを持たないことにして、書き手に選ばせる」という結果になりました。

## 提案の受理

2026年4月16日、提案 #71497 が active へと変更されます[^proposal-process]。

[^proposal-process]: Goの提案は issue として起票され、[proposal review](https://github.com/golang/proposal) のボード上を Incoming → Active → Likely Accept → Accepted と進みます。起票直後は Incoming に積まれ、レビューする側の余力ができたときに Active へ移ります。Active になった提案は週次の proposal review meeting で扱われ、議事録は <https://go.dev/s/proposal-minutes> に投稿されます。合意ができたと見えた時点で Likely Accept に移り、そこから1週間、合意を覆すような議論が出なければ Accepted になります（否決側は Likely Decline → Declined、設計の改訂待ちなどは Hold）。つまりこの日付は、受理が決まった日ではなく、レビューの俎上に載った日です。

4月29日、Austin Clements が期限を切ります。凍結までにレビューするには、1.26のGOEXPERIMENT版からの変更を反映した更新版が1週間以内に必要だ、と。

翌4月30日、Joe Tsai が提案を更新します。初回の安定リリースとして出す予定のもの、暫定的にGo 1.27を目標とする、という説明が添えられました。

そして同じ日、Joe Tsai 自身の手で、機能が1つ取り下げられます。

5月6日、提案レビューが開かれます。[議事録](https://github.com/golang/go/issues/71497#issuecomment-4390598447)が残っていて、受理された設計の要点がよくまとまっています。

> @dsnet joined us for a walk through of the whole API.
> **jsontext** — Leans into performance over absolute safety. API tends to prefer aliasing over allocating. The intent is that this package isn't widely used, and is only for doing really custom things and really high-performance things.
> **Options** — Shared across encoding and decoding and between the syntax and semantic layers. The WG spent a lot of time exploring alternatives, and ultimately came back to this design.
> **json/v2** — UnmarshalRead will always read to EOF. This is in contrast to v1, where it was a common mistake to call `Decode(io.Reader)` and not check that the reader had reached EOF.
> **Struct tags** — `omitempty` is now defined in terms of the JSON type system instead of the Go type system.
> 👍 all around the room.
>
> @dsnet が参加し、API全体を通して説明しました。
> **jsontext** は絶対的な安全性より性能に寄せています。APIはメモリ確保よりエイリアシングを好む傾向があります。このパッケージが広く使われることは想定しておらず、本当に特殊なことや、本当に高性能が要ることをするためだけのものです。
> **Options** はエンコードとデコードの両方で、また構文層と意味層のあいだでも共有されます。ワーキンググループは代案の検討に多くの時間を費やし、最終的にこの設計に戻ってきました。
> **json/v2** の UnmarshalRead は常にEOFまで読みます。これはv1とは対照的で、v1では `Decode(io.Reader)` を呼んでリーダーがEOFに達したか確認しないのがよくある誤りでした。
> **構造体タグ** の `omitempty` は、Goの型システムではなくJSONの型システムで定義されるようになりました。会議参加者全員 👍 でした。

同日中に「likely accept」となり、**2026年5月13日**に受理されます。[Austin Clements のコメント](https://github.com/golang/go/issues/71497#issuecomment-4444825716)は短いものでした。

> No change in consensus, so accepted. 🎉
>
> （合意に変化がないので、受理します🎉）

5月22日にマイルストーンがGo1.27に設定され、6月9日に実装完了として issue が閉じられます。

2016年3月に「これはおかしいのではないか」とissueが立てられてから、10年2ヶ月後のことです。
