---
title: "手元での検証"
---

## ソースに残る2つの実装

Go 1.27のソースを覗くと、もう一つ分かることがあります。

```
$ ls $(go env GOROOT)/src/encoding/json/
decode.go       encode.go       ...
v2_decode.go    v2_encode.go    v2_inject.go   v2_options.go   ...
```

`encode.go` と `v2_encode.go` が並んでいます。それぞれの先頭を見ると、こうなっています。

```go
// encode.go
// Copyright 2010 The Go Authors. All rights reserved.
//go:build !goexperiment.jsonv2

// v2_encode.go
// Copyright 2010 The Go Authors. All rights reserved.
//go:build goexperiment.jsonv2
```

ビルドタグで排他になっています。`GOEXPERIMENT` のデフォルト値がオンになっているため、`v2_encode.go` のほうが使われます。

```
$ grep -n "JSONv2" $(go env GOROOT)/src/internal/buildcfg/exp.go
		JSONv2:                true,
```

Go 1.25と1.26では、これを `GOEXPERIMENT=jsonv2` で明示的にオンにする必要がありました。Go 1.27ではデフォルトでオンになり、`GOEXPERIMENT=nojsonv2` でオフにする、オプトアウト[^optout]に変わりました。

[^optout]: Goでは新しい機能を入れるときにはだいたいこのパターンで、実験フラグは最初オプトインで、正式リリース後にオプトアウトに切り替わります。

そしてオフにしたとき動くのが、2010年に書かれた実装です。[リリースノート](https://go.dev/doc/go1.27#jsonv2)は、このオプトアウトについて「将来のリリースで削除される見込み」と書いています。

このディレクトリは、著作権表記の年号を見るだけでも、その歴史がわかって面白いです。

```
$ head -1 $(go env GOROOT)/src/encoding/json/encode.go
// Copyright 2010 The Go Authors. All rights reserved.

$ head -1 $(go env GOROOT)/src/encoding/json/v2/arshal.go
// Copyright 2020 The Go Authors. All rights reserved.

$ head -1 $(go env GOROOT)/src/encoding/json/jsontext/doc.go
// Copyright 2023 The Go Authors. All rights reserved.
```

2010年がv1、2020年がv2の意味層、2023年が `jsontext` です。v2のプロトタイプの最初のコミットは2020年10月でした。`jsontext` という名前が付いたのは、[Discussion #63397](https://github.com/golang/go/discussions/63397) で2パッケージ構成が提案された2023年です。16年分の判断が、1つのディレクトリに積み重なっています。

## nojsonv2での比較

このオプトアウトは、本当に等価なのでしょうか。

* https://go.dev/play/p/LU764Er5F_G （Playgroundでは `GOEXPERIMENT` を指定できないため、デフォルト側の出力だけが得られます）

```go
package main

import (
	"encoding/json"
	"fmt"
)

type User struct {
	Name string `json:"name"`
}

func main() {
	cases := []string{
		`{"name":}`,
		`{"name":"a"`,
		`{"name":"a"} extra`,
		`[1,2,3]`,
	}
	for _, in := range cases {
		var u User
		fmt.Printf("%-22s -> %v\n", in, json.Unmarshal([]byte(in), &u))
	}
	var ch chan int
	_, err := json.Marshal(ch)
	fmt.Printf("%-22s -> %v\n", "chan int", err)
}
```

```
--- デフォルト（v2バックエンド）---
{"name":}              -> invalid character '}' looking for beginning of value
{"name":"a"            -> unexpected end of JSON input
{"name":"a"} extra     -> invalid character 'e' after top-level value
[1,2,3]                -> json: cannot unmarshal array into Go value of type main.User
chan int               -> json: unsupported type: chan int

--- GOEXPERIMENT=nojsonv2 ---
{"name":}              -> invalid character '}' looking for beginning of value
{"name":"a"            -> unexpected end of JSON input
{"name":"a"} extra     -> invalid character 'e' after top-level value
[1,2,3]                -> json: cannot unmarshal array into Go value of type main.User
chan int               -> json: unsupported type: chan int
```

エラーの文言まで一致しました。リリースノートは「エラーメッセージの正確な文言は異なりうる」と断っていますが、ここで試した範囲では差が出ませんでした。これは全ケースで一致することの証明ではありません。ただ、まったく別の実装に載せ替えたにしては、ここまで揃っているという事実は書いておく価値があります。

なお、この一致は `v2_inject.go` のような橋渡しのコードが支えています。v1が返していた `*MarshalerError` のようなエラー型を、v2側から作り直す処理がそこに入っています。

## エラー文言のランダム化

エラーの文言を比べていて、おかしなことに気付きました。

`time.Duration` のエラーを繰り返し出していたら、同じコードなのに文言が変わるのです。同じバイナリを12回動かした結果です。

```
$ for i in $(seq 1 12); do ./exp6bin; done | sort | uniq -c
  11 json: cannot marshal from Go time.Duration within "/d": no default representation
   1 json: unable to marshal from Go time.Duration within "/d": no default representation
```

`cannot` と `unable to` が入れ替わります。バグではありません。`v2/errors.go` にこう書かれています。

```go
// errorModalVerb is a modal verb like "cannot" or "unable to".
//
// Once per process, Hyrum-proof the error message by deliberately
// switching between equivalent renderings of the same error message.
// The randomization is tied to the Hyrum-proofing already applied
// on map iteration in Go.
var errorModalVerb = sync.OnceValue(func() string {
	for phrase := range map[string]struct{}{"cannot": {}, "unable to": {}} {
		return phrase // use whichever phrase we get in the first iteration
	}
	return ""
})
```

同じ意味の言い回しを意図的に切り替えることで、エラー文言に依存されるのを防いでいます。実装はGoのマップの反復順序がすでにランダム化されていることに乗せていて、プロセスごとに1回だけ決まります。

Hyrumの法則は、利用者が十分に多ければ、仕様に書いたかどうかに関係なく、観測可能な挙動のすべてが誰かに依存される、というものです[^hyrum]。

[^hyrum]: Hyrum Wrightの名前から、Hyrumの法則と呼ばれます。<https://www.hyrumslaw.com/>

ここまででもHyrumの法則の結果、修正したくても弊害が出てしまう例を見てきました。大文字小文字を無視するマッチは、ドキュメントに書かれていたから直せませんでした。アドレス可能性で呼ばれたり呼ばれなかったりする挙動は、バグと呼べるものでさえ、依存が多すぎて差し戻されました。重複キーを受け入れる仕様は、いまも `any` へのデコードから最適化された経路を奪っています。

だからv2は、エラー文言が安定しているという観測可能な事実を、自分から壊しにいきました。これは`map`のイテレーションをわざとランダムにするのと似ています。14年かけて学んだことが、新しいパッケージの一行目から適用されています。

したがって、エラーメッセージの文字列一致でテストを書いている場合は、v2に移るときに壊れます。これは意図されたものなのです。

## 性能の実測

では、v2に移ると実際どれくらい速くなるのでしょうか。次はリリースノートの記述です。

> Marshal performance is broadly at parity with the previous implementation, while unmarshal performance is significantly faster.
>
> （Marshalの性能は以前の実装とおおむね同等で、Unmarshalの性能は著しく速い）

[公式ブログ](https://go.dev/blog/jsonv2-exp)はもう少し踏み込んで、unmarshalは最大10倍という表現を使っています。実際にどうなのかを手元で計測しました。1000件の要素を持つJSON配列を、具体的な構造体のスライスに読み込む場合です。

```
goos: darwin
goarch: arm64
cpu: Apple M5 Pro
BenchmarkUnmarshalV1-18    2295   523371 ns/op   121.66 MB/s   242924 B/op   4012 allocs/op
BenchmarkUnmarshalV2-18    2716   446989 ns/op   142.44 MB/s   242924 B/op   4012 allocs/op
BenchmarkMarshalV1-18      5594   213990 ns/op                  66148 B/op      3 allocs/op
BenchmarkMarshalV2-18      5516   217250 ns/op                  66467 B/op      3 allocs/op
```

unmarshalで1.18倍、marshalはほぼ同じです。「最大10倍」からは遠い数字です。

10倍という数字が出るのは別の状況です。同じデータを `any` に読み込むと、こうなります。

```
BenchmarkAnyV1-18    921   1306860 ns/op    48.72 MB/s   739932 B/op   23014 allocs/op
BenchmarkAnyV2-18   2091    581713 ns/op   109.45 MB/s   626968 B/op   17012 allocs/op
```

2.25倍の差が付き、アロケーション回数も23014回から17012回に減っています。

ここで注意したいのは、`BenchmarkAnyV1` が呼んでいるのが `encoding/json` の `Unmarshal` だという点です。Go 1.27では、これもv2の実装の上で動いています。それでもv2を直接呼ぶより2倍以上遅いですね。

原因は、v1の挙動を保つためのオプションの1つにあります。`any` へのデコードには最適化された専用の経路があるのですが、その入口に条件が付いています。

* [src/encoding/json/v2/arshal_default.go#1904](https://go.googlesource.com/go/+/refs/tags/go1.27.0/src/encoding/json/v2/arshal_default.go#1904)（go1.27.0）

```go
if optimizeCommon &&
	t == anyType && !uo.Flags.Get(jsonflags.AllowDuplicateNames|jsonflags.FormatTag) &&
	(uo.Unmarshalers == nil || !uo.Unmarshalers.(*Unmarshalers).fromAny) {
	v, err := unmarshalValueAny(dec, uo)
```

`AllowDuplicateNames` が立っていると、この経路に入れません。最適化された実装は重複キーの検査を行わないので、重複を許す設定では使えないからです。

そしてv1は、重複キーを受け入れる仕様でした。つまりv1のAPIを呼ぶかぎり、このフラグは必ず立っています。

本当にそれが効いているのかは、切り分けて測れます。v2を直接呼びつつ、重複キーの扱いだけをv1に合わせてみます。

```go
jsonv2.Unmarshal(data, &v, jsontext.AllowDuplicateNames(true))
```

```
BenchmarkAnyV1-18            890   1306831 ns/op   48.72 MB/s   739952 B/op   23014 allocs/op
BenchmarkAnyV2-18           2060    584852 ns/op  108.87 MB/s   626969 B/op   17012 allocs/op
BenchmarkAnyV2AllowDup-18    994   1219219 ns/op   52.22 MB/s   739925 B/op   23014 allocs/op
```

オプションを1つ倒しただけで、v1とほぼ同じところまで落ちました。アロケーション回数は23014回で、v1と完全に一致しています。

14年前に「重複キーを黙って受け入れる」と決めたことのツケが、こういう形で残っています。挙動の互換性を守るために、最適化された経路を捨てています。

v1がv2の上に載ったのだから、何もしなくても速くなる、と言える範囲は、確かにありますが、いちばん差が出るところはその恩恵は得られません。v1のAPIを呼び続けるかぎり、v1の挙動を再現するための負担は残ります。性能を上げたいのであれば、v2のAPIを明示的に呼ぶ必要があります。

なお、この測定は特定の形のデータに対する一例です。JSONの構造、フィールド数、型の組み合わせによって結果は変わります。本番環境に関係する場合は自分のデータでベンチマークを取ってください。

## v1とv2の16の差分

`encoding/json` のドキュメントには[「Migrating to v2」](https://pkg.go.dev/encoding/json#hdr-Migrating_to_v2)という節があり、v1とv2の挙動差が16項目挙げられています。移行の手引きとして書かれたものです。ただ、左の列だけを続けて読むと、別のものに見えてきます。14年のあいだに何が誤りだったと判断されたのか、というリストになっています。

| v1の挙動 | v2の挙動 |
|---|---|
| フィールド名を大文字小文字を区別せずマッチ | 大文字小文字を区別して厳密にマッチ |
| `omitempty` はGoの値が空かで判定 | `omitempty` はJSONとして空になるかで判定 |
| `string` タグは文字列、真偽値、数値に効き、再帰しない | 数値だけに効き、複合型の内側まで再帰する |
| nilスライスとnilマップを `null` に | 空のJSON配列と空のJSONオブジェクトに |
| Go配列は任意長のJSON配列から読める | 長さが一致しなければエラー |
| `[N]byte` はJSONの数値配列 | Base64エンコードされたJSON文字列 |
| ポインタレシーバのメソッドはアドレス可能なときだけ呼ばれる | 常に呼ばれる |
| マップのキーに対してはメソッドを呼ばない | 呼ぶ |
| マップは決定的な順序で出力 | 非決定的な順序 |
| HTMLやJavaScript向けの文字をエスケープ | 文法上必要なときだけエスケープ |
| 不正なUTF-8を置換文字に差し替え | エラー |
| 重複キーを受け入れる | エラー |
| `null` を非空の値に入れると、ゼロ化したりしなかったり | 常にゼロ化する |
| 非ゼロの値へのマージ規則が一貫しない | JSONオブジェクトならマージ、そうでなければ置換 |
| `time.Duration` はナノ秒の数値 | デフォルトの表現を持たず、エラー |
| 構造上おかしな型でも実行時エラーにならない | 実行時エラーになる |

v1の挙動には「一貫しない」「したりしなかったり」という記述が複数あります。アドレス可能性によって呼ばれたり呼ばれなかったりする問題がその一例です。バグと呼べるものでさえ、依存が積み上がった後では直せなくなっていました。
