---
title: "修正できなかったもの"
---

## 最初のissue

2016年3月10日に ["encoding/json: parser ignores the case of member names"](https://github.com/golang/go/issues/14750) というissueが立てられました。これはJSONのパーサーがメンバー名の大文字小文字を無視する、という指摘をするものです。

同日に、[Russ Cox が返信しています](https://github.com/golang/go/issues/14750#issuecomment-194911844)。

> This has been the behavior at least as far back as Go 1.2 … The docs also seem to state quite clearly that this is what happens … I understand there are security implications if JSON is used in security contexts, and I was a little surprised too, but the docs are very clear[.]
>
> （この挙動は少なくとも Go 1.2 まで遡る。ドキュメントにも、そうなることがかなり明確に書かれているように見える。JSONがセキュリティの文脈で使われるならセキュリティ上の影響があることは理解しているし、自分も少し驚いた。しかしドキュメントは非常に明確だ）

「ドキュメントに書いてある」ことを理由に、変更はしない、という判断でした。なぜそれが決定的なのかは、Goの後方互換性保証の中身を見ると分かります。

## 後方互換性保証の内容

[Goの後方互換性](https://go.dev/doc/go1compat) は次の一文に要約されます。

> It is intended that programs written to the Go 1 specification will continue to compile and run correctly, unchanged, over the lifetime of that specification.
>
> （Go 1の仕様に沿って書かれたプログラムが、その仕様の存続期間にわたって、変更なしにコンパイルでき、正しく動き続けることを意図しています。）

これがGoというプロジェクトの根幹です。

ただし例外はあります。セキュリティ上の問題、仕様が定めていない挙動、仕様自体の誤り、明白なバグ。こうしたものは変更されうると明記されています。

大文字小文字を無視するマッチは、このどれにも当てはまりません。ドキュメントに書かれている以上、「仕様が定めていない挙動」ではありません。明記されている以上、「バグ」でもありません。セキュリティ上の懸念は指摘されましたが、脆弱性そのものではなく、危険なデフォルト値という位置づけでした。

つまりこの挙動は、例外の網から漏れたところにありました。修正すれば、その挙動に依存しているプログラムが壊れます。どれだけ望ましくなくても、約束のほうが優先されました。

## Go 2への先送り

同じ判断は他の issue でも繰り返されました。

[`golang/go#4712`](https://github.com/golang/go/issues/4712) は `time.Duration` のJSON表現についての issue です。`encoding/json` は `time.Duration` をナノ秒の整数として出力します。`90 * time.Second` は `90000000000` になります。単位がどこにも書かれていないので、受け取った側は桁を数えるしかありません。

2017年2月17日、この issue は閉じられました。以下は[Russ Cox のコメント](https://github.com/golang/go/issues/4712#issuecomment-280777128)です。

> If you want a custom duration marshaling, define a type that implements json.Marshaler/json.Unmarshaler. At this point we're not going to change this fundamental detail of the json package.
>
> （独自の duration のマーシャリングが欲しいなら、`json.Marshaler` と `json.Unmarshaler` を実装する型を定義してください。現時点で、jsonパッケージのこの根本的な部分を変えるつもりはありません。）

また、[Brad Fitzpatrick が短く付け加えています](https://github.com/golang/go/issues/4712#issuecomment-280779075)。

> Everything will be considered anew for any Go 2.
>
> （すべてはGo 2で改めて検討されます。）

2017年の時点で、この種の問題は「いまのGoでは扱えないもの」として、将来の何かに預けられていました。

## 修正の試みと断念

ここで話は「Goチームが修正しなかった」では終わりません。直そうとした人がいました。

2020年2月26日、`encoding/json` のメンテナである Daniel Martí（mvdan）が[このissueに書き込みます](https://github.com/golang/go/issues/14750#issuecomment-591522083)。

> I've come to realise that pretty much all of my previous comments in this thread were wrong :) … I do think that many parts of the json package could be designed better, and I think the edge cases concerning missing, repeated, or case-insensitive-matching keys are some of them.
>
> （このスレッドでの自分の以前のコメントは、ほぼ全部が間違っていたと気付きました。jsonパッケージの多くの部分はもっとうまく設計できたはずで、キーの欠落や重複、大文字小文字を無視するマッチにまつわる際どい部分は、その一部だと思います。）

そして実際に修正を書きました。[3月19日のコメント](https://github.com/golang/go/issues/14750#issuecomment-601230870)です。

> Decoding structs is ~1% slower, but we get the benefit we want. … 1% performance loss is unfortunate, but I can't figure out a way around it.
>
> （構造体のデコードは約1%遅くなるが、欲しい結果は得られます。1%の性能劣化は残念ですが、回避する方法が見つかりません。）

動作するパッチがあり、性能の代償についても、1%という具体的な数字まで測られていました。それでも、既存の挙動に依存したプログラムを壊す問題は残ります。1%の劣化を全ユーザーに負わせたうえで、一部のユーザーのコードを壊す、ということで、この提案は承認しませんでした。

このときのパッチ [CL224079](https://go-review.googlesource.com/c/go/+/224079) は、マージされないまま2024年に放棄されました。

ここが転換点でした。「直せない」は諦めではなく、書いて、動かして、測ったうえでの結論でした。そしてこの結論が出た年の後半に、v2の構想が書かれ始めます。

## v1とv2に同じ入力を与える

go1.27では `encoding/json` と `encoding/json/v2` の両方が使えます。同じ入力を、両方に渡してみます。

* https://go.dev/play/p/vtzRCS8x2iP?v=gotip

```go
package main

import (
	jsonv1 "encoding/json"
	jsonv2 "encoding/json/v2"
	"fmt"
)

type User struct {
	Name string `json:"name"`
}

func main() {
	in := []byte(`{"NAME":"gopher"}`)

	var a User
	err1 := jsonv1.Unmarshal(in, &a)
	fmt.Printf("v1: %+v  err=%v\n", a, err1)

	var b User
	err2 := jsonv2.Unmarshal(in, &b)
	fmt.Printf("v2: %+v  err=%v\n", b, err2)
}
```

```text
v1: {Name:gopher}  err=<nil>
v2: {Name:}  err=<nil>
```

v2はマッチしません。注意したいのは、v2が**エラーを返しているわけではない**ことです。`NAME` は単に知らないメンバー名として無視され、`Name` フィールドは空のまま残ります。エラーにしたい場合は `RejectUnknownMembers` を指定します。

## 重複キーと不正なUTF-8

大文字小文字だけではありません。重複キーと不正なUTF-8も見ておきます。

```go
dup := []byte(`{"name":"alice","role":"user","role":"admin"}`)
bad := []byte("{\"name\":\"go\xffpher\"}")
```

`dup` は `role` というキーが2回出てくるJSONです。`bad` は文字列の中にUTF-8として不正なバイト `0xff` が混ざっています。

```
v1 dup: {Name:alice Role:admin}  err=<nil>
v2 dup: err=jsontext: duplicate object member name "role"
v1 utf8: err=<nil> -> "go�pher"
v2 utf8: err=jsontext: invalid UTF-8 within "/name" after offset 11
```

v1はどちらも黙って受け入れます。重複キーは後勝ちで上書きし、不正なUTF-8はUnicodeの置換文字に差し替えます。呼び出し側は、入力が壊れていたことを知る手段を持ちません。

重複キーが問題になるのは、JSONを読む主体が複数あるときです。認証プロキシが `"role":"user"` を見て通し、その後ろのアプリケーションが `"role":"admin"` を読む。両者が同じ仕様に従っていても、片方が先勝ち、もう片方が後勝ちなら、判定が食い違います。2023年に起票された[Discussion #63397](https://github.com/golang/go/discussions/63397)はこれを「攻撃者に悪用されうるし、実際に深刻な結果を伴って悪用されてきた」と書いています。

エラーメッセージの先頭に `jsontext:` と付いています。`encoding/json/jsontext` という別のパッケージが出したエラーです。v2ではJSONの構文を扱う層と、JSONとGoの値の対応づけを扱う層が分かれています。重複キーも不正なUTF-8も、Goの型に触れる前の、構文の段階で弾かれています。ではなぜ、JSONを読み書きする層がわざわざ別パッケージに切り出されているのか。性能のためだと考えるのが自然に思えますが、そうではありませんでした。

## v1の問題の4分類

Discussion #63397は、冒頭でv1の問題を4つに分類しています。当時の issue 番号が添えられているので、14年分の記録としても有用な議論です。

機能不足として挙げられているのは、`time.Time` の書式を指定する手段（[#21990](https://github.com/golang/go/issues/21990)）、特定の値を出力から省く方法（[#22480](https://github.com/golang/go/issues/22480)、[#50480](https://github.com/golang/go/issues/50480) ほか）、nilのスライスやマップを `null` ではなく `[]` や `{}` として出す方法（[#37711](https://github.com/golang/go/issues/37711)、[#27589](https://github.com/golang/go/issues/27589)）、埋め込みを使わずに構造体を展開する `inline` タグ（[#6213](https://github.com/golang/go/issues/6213)）です。

APIの欠陥として挙げられているのは、`json.NewDecoder(r).Decode(v)` が入力の末尾にゴミが残っていても黙って成功すること（[#36225](https://github.com/golang/go/issues/36225)）、オプションを `Marshal` や `Unmarshal` に渡せず、ネストした型の奥まで伝えられないこと（[#41144](https://github.com/golang/go/issues/41144)）です。

性能の限界は、設計に根ざしたものです。`MarshalJSON` は `[]byte` を返す形なので、実装は必ず一度バイト列を確保します。呼び出す側は返ってきたバイト列を再度パースして、妥当性を検査し、インデントを付け直します。`UnmarshalJSON` はさらに厄介で、完全な値を渡す必要があるため、呼ぶ前に値全体をパースし、メソッドの中でもう一度パースすることになります。入れ子になった型がそれぞれ `UnmarshalJSON` を持っていると、この二度手間が階層の分だけ掛け算になります。実際に、[Kubernetes の OpenAPI 仕様の読み込みで実際に問題になった例](https://github.com/kubernetes/kube-openapi/issues/315)が挙げられています。

そして挙動の欠陥がありました。不正なUTF-8を受け入れること、重複キーを受け入れること（[#43664](https://github.com/golang/go/issues/43664)）、大文字小文字を無視するマッチ（#14750）に加えて、値がアドレス可能かどうかで `MarshalJSON` が呼ばれたり呼ばれなかったりすること（[#22967](https://github.com/golang/go/issues/22967) ほか）が挙がっています。

最後の項目は、短いコードで再現できます。

* https://go.dev/play/p/PDbqd1aQCcC?v=gotip

```go
package main

import (
	jsonv1 "encoding/json"
	jsonv2 "encoding/json/v2"
	"fmt"
	"strings"
)

type Tag struct {
	Name string
}

// ポインタレシーバで定義する
func (t *Tag) MarshalJSON() ([]byte, error) {
	return []byte(`"` + strings.ToUpper(t.Name) + `"`), nil
}

func main() {
	slice := []Tag{{Name: "go"}}              // 要素はアドレス可能
	m := map[string]Tag{"lang": {Name: "go"}} // 値はアドレス不可

	b1, _ := jsonv1.Marshal(slice)
	b2, _ := jsonv1.Marshal(m)
	fmt.Printf("v1 スライス: %s\n", b1)
	fmt.Printf("v1 マップ  : %s\n", b2)

	b3, _ := jsonv2.Marshal(slice)
	b4, _ := jsonv2.Marshal(m)
	fmt.Printf("v2 スライス: %s\n", b3)
	fmt.Printf("v2 マップ  : %s\n", b4)
}
```

```
v1 スライス: ["GO"]
v1 マップ  : {"lang":{"Name":"go"}}
v2 スライス: ["GO"]
v2 マップ  : {"lang":"GO"}
```

v1では、スライスの要素なら `MarshalJSON` が呼ばれて `"GO"` になり、マップの値なら呼ばれずに既定の構造体表現へ落ちます。同じ型の同じ値でも、置かれた場所によって結果が変わります。v2はどちらでも呼びます。

この最後の項目には、注目すべき但し書きが付いています。

> This could arguably be considered a bug and be fixed in the current 'json' package. However, previous attempts at fixing this resulted in the changes being reverted because it broke too many targets implicitly depending on the inconsistent calling behavior.
>
> （これはバグと見なして現行のjsonパッケージで直せると論じる余地はあります。しかし過去に直そうとした結果、その一貫性のない呼び出し挙動に暗黙に依存していた対象が多すぎて、変更は差し戻されました。）

例外規定に当てはまる「バグ」でさえ、依存が積み上がった後では直せなくなっていました。

> These behavioral flaws of 'json' cannot be changed without being a breaking change. Options could be added to specify different behavior, but that would be unfortunate since the desired behavior is not the default behavior. Changing the default behavior suggests the need for a v2 'json' package.
>
> （jsonのこれらの挙動上の欠陥は、破壊的変更なしには変えられません。オプションを足して別の挙動を指定できるようにはできますが、望ましい挙動が既定でないという状態が残るので、それは不本意です。既定の挙動を変えるということは、v2のjsonパッケージが必要だということを示しています。）
