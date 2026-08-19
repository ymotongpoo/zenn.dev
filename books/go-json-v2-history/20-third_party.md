---
title: "サードパーティの回避策"
---

## 速度を追求したライブラリ

標準ライブラリが動けない14年のあいだ、JSONを扱うGoユーザーが黙って待っていたわけではありません。とくに性能については、外部ライブラリが次々に生まれました。アプローチはさまざまに分かれました。

* [`mailru/easyjson`](https://github.com/mailru/easyjson) はコード生成をしました。`easyjson -all foo.go` を走らせて、型ごとに専用のエンコーダとデコーダを吐かせます。リフレクションを一切使わないので速い代わりに、ビルド手順に生成ステップが増え、`encoding/json` の差し替えとしては使えません。
* [`json-iterator/go`](https://github.com/json-iterator/go) は、リフレクションを使いつつ型ごとの処理をキャッシュして高速化し、importパスを差し替えるだけで使える形を取りました。
* [`goccy/go-json`](https://github.com/goccy/go-json) は、その方向をさらに押し進めました。型を解析してオペコードの列にコンパイルし、それをループで実行します。再帰呼び出しではなくジャンプで処理を回し、コンパイル結果は型のポインタをキーにしたスライスに載せて引きます。フィールド数が16以下の構造体では、ビットマップを使ってマップ引きなしにフィールドを特定します。
* [`bytedance/sonic`](https://github.com/bytedance/sonic) はさらに踏み込んで、実行時に型ごとの機械語をJITで生成し、走査にSIMDを使います。

これらのライブラリの動機は、README を読むと明確です。[`segmentio/encoding`](https://github.com/segmentio/encoding) は「我々が扱う規模では、プログラムを組み立てる道具の選択がシステム全体の効率に大きく影響する」と書いています。[`buger/jsonparser`](https://github.com/buger/jsonparser) は違う不満から出発していて、構造が事前に分からないJSONを扱うとき、`encoding/json` は構造体を用意することを要求し、`map[string]interface{}` で受けると非常に遅い、と書いています。

## drop-inであるための制約

ここで、`goccy/go-json` の README にある一文を引用します。

> It's easier to implement by using automatic code generation for performance or by using a dedicated interface, but `go-json` dares to stick to compatibility with `encoding/json` and is the simple interface. Despite this, we are developing with the aim of being the fastest library.
>
> （性能のために自動コード生成を使ったり専用のインターフェースを使ったりすれば実装は楽になる。それでも `go-json` はあえて `encoding/json` との互換性にこだわり、単純なインターフェースを保つ。それにもかかわらず、最速のライブラリになることを目指して開発している）

この「あえて」が、外部ライブラリ群が背負った制約です。importパスを差し替えるだけで動く、という価値を提供する以上、v1と同じ結果を返さなければなりません。そしてv1と同じ結果には、前章で見た欠陥が全部含まれます。

大文字小文字を無視するマッチも、再現しなければならない仕様の一部です。重複キーを黙って後勝ちにするのも、nilのスライスを `null` にするのも同じです。速くしたい人たちが、直したいと思っていたはずの挙動を、忠実に写し取る作業をしていました。

## 最適化とv1互換の衝突

この制約が具体的なバグとして表に出た例があります。

[`goccy/go-json#568`](https://github.com/goccy/go-json/issues/568) は2026年2月12日に起票され、本書の執筆時点で未解決です。内容は、対象の構造体が可視のJSONフィールドを17個以上持つとき、`goccy/go-json` は大文字小文字を無視するマッチを行わず、16個以下なら正しく動く、というものです。

境界の16は、先ほど触れたビットマップ最適化の上限です。フィールド数が16以下ならビットマップでフィールドを特定でき、マップ引きが要りません。17個目からは別の経路に落ちます。そしてその別の経路が、v1の大文字小文字を無視するマッチを落としていました。

最適化とv1への忠実さが同じコードの中で衝突しています。しかも壊れ方が、フィールドを1つ足した瞬間に切り替わるという分かりにくい形です。同じリポジトリには、入れ子の構造体で大文字小文字マッチが効かない [`#470`](https://github.com/goccy/go-json/issues/470) も未解決で残っています。

## ランタイム内部への依存

速度の代償は、別の点にも及びました。

2024年、Goチームは [`golang/go#67401`](https://github.com/golang/go/issues/67401) で `linkname` の使い方を制限する作業を進めます。`linkname` は、本来アクセスできないパッケージの内部シンボルに外から結びつくための仕組みです。その issue の中に、次の記述があります。

> For example, https://go.dev/cl/583756 broke github.com/goccy/go-json because it turns out that package copied most of the runtime's internal type API. Now we can't change _anything_ in that list, despite that being an ostensibly internal package, without breaking goccy/go-json. And goccy is used by many packages, including Kubernetes... This situation is unsustainable.
>
> （たとえば https://go.dev/cl/583756 は github.com/goccy/go-json を壊した。そのパッケージがランタイムの内部型APIのほとんどをコピーしていたことが分かったからだ。いまや、名目上は内部のパッケージであるにもかかわらず、goccy/go-json を壊さずにはその一覧の何一つ変えられない。しかも goccy はKubernetesを含む多くのパッケージから使われている。この状況は維持できない）

ここで名指しされているのは、[ランタイム内部の小さな整理をしたCL](https://go-review.googlesource.com/c/go/+/583756)です。

構図が反転しています。標準ライブラリのほうでは後方互換性保証が `encoding/json` を修正から妨げていました。ここでは、外部ライブラリの内部依存が、ランタイムの変更の自由を縛っています。速度のために借りていたのは、v1の欠陥への忠実さだけではなく、ランタイム内部が動かないという前提でもありました。

## なぜ標準に取り込まなかったのか

これだけ速い実装が外にあるのなら、そのどれかを標準に取り込めばよかったと思いますが、[Discussion #63397](https://github.com/golang/go/discussions/63397) は、この問いに答えています。

> There are many community forks or reimplementations of v1 'json'. While they provide impressive performance gains, they cannot be adopted into the standard library on the basis of their extensive use of package 'unsafe'. The 2021 Go Developer Survey shows that the assurance of reliability and security is a higher priority than CPU or memory performance.
>
> （v1のjsonには、コミュニティによるフォークや再実装が多数ある。目を見張る性能向上を提供している一方で、`unsafe` パッケージを多用しているという理由から、標準ライブラリには採用できない。2021年の Go Developer Survey は、信頼性と安全性の保証がCPUやメモリの性能より優先度が高いことを示している）

判断の根拠が[2021年の Go Developer Survey](https://go.dev/blog/survey2021-results#prioritization)に置かれているのが、個人的にGoの特徴をよく表していると思います。速さと安全性のどちらを取るかを、設計者の好みではなく、利用者に聞いた結果として扱っています。

なお、v2の作者である Joe Tsai が公開しているベンチマークリポジトリ [`go-json-experiment/jsonbench`](https://github.com/go-json-experiment/jsonbench) には、`goccy/go-json` について「再現可能なデータ競合とメモリ破壊に至るバグがあり、本番利用には安全でない」という趣旨の記述があります。Joeはv2の作者自身なので、中立な第三者の評価ではないとは思います。ただ、`goccy/go-json` のissue一覧にデータ競合やクラッシュの報告が複数残っているのは事実で、直近のコミットもエンコーダとデコーダのコンパイル部分のデータ競合修正です。

同じリポジトリの数値も、引くなら前提を添える必要があります。v2の unmarshal は具体的な型に対してv1の2.7倍から10.2倍、marshal は1.4倍速いところから1.2倍遅いところまで、と報告されています。ただしこの測定は2025年1月時点、Go 1.23.5 上のもので、標準ライブラリに入る前のプロトタイプに対するものです。
