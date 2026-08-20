---
title: "v2構想の始まり"
---

## 2020年後半の草案

mvdanが[修正パッチ](https://go-review.googlesource.com/c/go/+/224079)を書いて断念したのが2020年3月でした。その年の後半、mvdanがv2の構想を書き始めます。

現行パッケージの問題を直せないことがそのきっかけだったと、[Go公式ブログ](https://go.dev/blog/jsonv2-exp)は書いています。その草案は [encoding/json v2 draft](https://docs.google.com/document/d/1WQGoM44HLinH4NGBEv5drGlw5_RNW-GP7DdGEpm7Y3o) という題で公開されています。冒頭に次の断り書きがあります。

> Please note that these are mostly my personal opinions as one of the maintainers of encoding/json. In no way are they a formal proposal (yet) or endorsed by the Go project.
>
> （これらは大部分が、encoding/json のメンテナの一人としての私個人の意見であることに留意してください。決して（まだ）正式な提案ではなく、Goプロジェクトが承認したものでもありません。）

個人の意見だと断りつつ、謝辞には Philip Pearl、Matt Layher、Dave Cheney、Chris Hines、Roger Peppe、Joe Tsai 等の名が並んでいます。`encoding/json` の遅さを連載で解剖した人、高速なJSONトークナイザを書いた人、Goが公開された日からのコントリビュータ、標準ライブラリの外側でシリアライズと性能の改善を続けてきた人という錚々たる面々です。そのうちの一人、GoチームのメンバーであるJoe Tsaiが、この数週間後にv2のプロトタイプの最初のコミットをすることになります。

このブログ記事の中身は、修正したい点を以下の4つの節に整理したものです。

* バッファリングを避けられないこと
* `Marshaler` と `Unmarshaler` がオプションを受け取れないこと
* `MarshalJSON` が必ずメモリを確保すること
* `Decoder.Decode` が誤用を招くこと

修正できなかった問題が、issue番号付きで並んでいますが、注目したいのは、その前に置かれた設計の前提です。

> We want to stick to the design principles of the standard library: correctness over performance by default, no `unsafe`, and no extra steps such as code generation. These rule out the majority of third-party JSON library designs.
>
> （標準ライブラリの設計原則は守りたい。既定では性能より正しさを取り、`unsafe` を使わず、コード生成のような追加の手順も要求しない。これらが、サードパーティのJSONライブラリの設計の大半を除外します。）

そうしたサードパーティライブラリからも学びもあります。「Previous work」という節に、[`json-iterator/go`](https://github.com/json-iterator/go) のアロケーションを減らすAPI設計、Phil Pearl による `Marshaler` の性能限界の分析、Dave Cheney による高速なトークナイザの実装が挙げられています。設計原則としては採用しないが、問題の捉え方としては参照する、というスタンスになっています。

そして、この文書には[コメント](https://docs.google.com/document/d/1WQGoM44HLinH4NGBEv5drGlw5_RNW-GP7DdGEpm7Y3o/edit?disco=AAAAKW8Yr2s)が残っています。

> another: make a list of v1 semantics that we want to bury/hide from the new API, and only keep working from the old API entrypoints
>
> （新しいAPIから隠したいv1のセマンティクスの一覧を作り、古いAPIのエントリーポイントからだけ動き続けるようにする）

あとで紹介する `AllArshalV1Flags` は、この一行が実装された姿です。

序文には、もう一つ書かれていることがあります。

> This document does not intend to encourage yet another competitor to `encoding/json`. However, a fork is likely to happen in the future to allow experimenting with these changes.
>
> （この文書は、`encoding/json` の競合をもう一つ増やすことを意図していません。ただし、これらの変更を実験できるようにするため、いずれフォークが作られる見込みが高いです。）

## 構文層から始まった実装

草案から数週間後、実装が始まります。

[`github.com/go-json-experiment/json`](https://github.com/go-json-experiment/json) の[最初のコミット](https://github.com/go-json-experiment/json/commit/e1c1885bc2b1700df6da562e1e20e1abe25f8e4d)は2020年10月23日、Joe Tsai によるものです。当時の所属はGoogleで、Protocol BuffersのGo実装を担当していました。ただしリポジトリは個人アカウントに置かれ、コミットも個人のメールアドレスで、業務としてではなく始まっています。その後のコミットの並びに、設計の順序が残っています。

```
2020-10-23  Initial commit of base files
2020-10-29  Add README.md (#1)
2020-11-21  Add initial API for syntactic JSON serialization (#2)
2020-11-23  Add error types and functionality (#7)
2020-11-23  Add "Design overview" section to the readme (#10)
2020-12-03  Add state machine for validating token sequences (#8)
2020-12-13  Add basic serialization functionality (#11)
2021-01-26  Implement Token (#22)
2021-02-05  Implement Encoder (#32)
2021-02-20  Implement Decoder (#33)
```

API として最初に足されたのが["syntactic JSON serialization"](https://github.com/go-json-experiment/json/commit/ce75d2946eaa5f1c6367e6a58eaca5ff237c9dad)、つまり構文層です。GoとJSONの対応づけ、つまり意味層が入るのはその3週間後です。

構文と意味を分ける設計は、後から性能のために切り出されたものではなく、最初のAPIコミットからそうなっていました。なぜそうなったのかは、Joe Tsai がこの仕事に来た経緯と結びついています。

## protojsonの制約

Joe Tsai は Protocol Buffers のGo実装に関わっていました。そのなかに [`protojson`](https://pkg.go.dev/google.golang.org/protobuf/encoding/protojson) という、protobufのメッセージとJSONを相互変換するパッケージがあります。

Go公式ブログ["A new experimental Go API for JSON"](https://go.dev/blog/jsonv2-exp)の記述です。

> After previous work on the Go API for Protocol Buffers, Joe Tsai was disappointed that the `protojson` package needed to use a custom JSON implementation because `encoding/json` was neither capable of adhering to the stricter JSON standard that the Protocol Buffer specification required, nor of efficiently serializing JSON in a streaming manner.
>
> （Protocol Buffers のGo APIでの以前の仕事のあと、Joe Tsai は `protojson` パッケージが独自のJSON実装を使わなければならないことに落胆していました。`encoding/json` は、Protocol Buffers の仕様が要求する、より厳格なJSON標準に従うこともできず、ストリーミングでJSONを効率よく直列化することもできなかったからです。）

厳格さとストリーミングはどちらも、GoとJSONの対応づけではなく、JSONの構文をどう読み書きするかの話です。`protojson` が自前で持っていたのは、まさにその構文層でした。最初のコミットが構文層から始まっているのもおそらくそうした理由からでしょう。層が分かれているのも、速くするためではなく、JSONの規格に厳密に従い、値全体を組み立てずに読み書きしたい実装が、標準ライブラリの外に先にあったからだと思われます。`jsontext` の原型は、protobufの内部にあったJSON処理でした。

## READMEに書かれた6つの目標

`go-json-experiment/json` の[最初のREADME](https://github.com/go-json-experiment/json/blob/10e1c1dd5a0849500339d90175566ebb98e1c245/README.md)には、6つの目標が並んでいました。このうち2つが、その後の開発方針を決めています。

1つは互換性の扱いです。

> Behaviorally, we should aim for 95% to 99% backwards compatibility. We do not aim for 100% compatibility since we want the freedom to break certain behaviors that are now considered to have been a mistake.
>
> （挙動としては、95%から99%の後方互換を目指すべきです。100%の互換は目指しません。なぜなら、いまでは誤りだったと考えられている一部の挙動を壊す自由が欲しいからです。）

v1で修正できなかったものを、ここで初めて「誤り」と呼んでいます。もう1つが、最終的な形を予見していました。

> Since the v1 implementation must stay forever, it would be beneficial if v1 could be implemented under the hood with v2
>
> （v1の実装は永久に残さなければならないのですから、v1がv2を使って内部的に実装できるなら好都合でしょう。）

2020年10月の時点で、6年後に実際に採用される形が書かれています（あとで解説します）。当時のREADMEには「Expectations」という節もあり[^expectations]、想定される結果が5つ並んでいて、その第1案は「この試みを断念する」でした。うまくいく前提で書かれた文書ではないことがわかります。

[^expectations]: 現在は削除されています。

## Tailscaleでの実証

構想と実装があっても、それだけでは標準ライブラリに入る根拠になりません。このプロトタイプは実際に使われました。

Joe Tsai は2021年7月にTailscaleへ転職し、2022年10月に[自分の手でこのモジュールを依存に加えています](https://github.com/tailscale/tailscale/pull/6108/changes)。外部の誰かが評価して本番採用したのではなく、作者が転職先で使い始めたわけです。

[Discussion #63397](https://github.com/golang/go/discussions/63397) のStability という節に、次の記述があります。

> We have confidence in the correctness and performance of the module as it has been used internally at Tailscale in various production services. However, the module is an experiment and breaking changes are expected to occur based on feedback in this discussion, it should not be depended upon by publicly available code, otherwise we can run into situations where large programs fail to build.
>
> （このモジュールは Tailscale の様々な本番サービスで内部的に使われてきたので、正しさと性能には自信があります。ただしこのモジュールは実験であり、この議論でのフィードバックに応じて破壊的変更が起きると見込まれます。公開されているコードから依存されるべきではありません。さもなければ、大きなプログラムがビルドできなくなる状況に陥りえます。）

ここで言う本番サービスはTailscaleの非公開のコードです。公開されているリポジトリでこのモジュールを使っていたのは、この時点ではログ整形用のコマンド1つだけでした。

後半の但し書きは、公開ライブラリが実験的モジュールに依存したときに起きる問題を避けるためのものです。プログラムPがモジュールAとBに依存し、AとBが `go-json-experiment` の別々のバージョンを要求すると、ビルドできなくなります。

Go公式ブログはもう一つ別の実例を挙げています。[KubernetesのOpenAPI仕様の読み込み](https://github.com/kubernetes/kube-openapi/issues/315)で、入れ子になった `UnmarshalJSON` が繰り返しパースを行い、処理時間が二次的に増えていた件です。設計に根ざした性能の限界が、実際の規模で問題になった例です。
