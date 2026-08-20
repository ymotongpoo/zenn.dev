---
title: "v2以後のエコシステム"
---

## 取り下げられたformatタグ

2026年4月30日、提案を更新したのと同じ日に、Joe Tsai はもう一つ issue を立てています。[`golang/go#79071`](https://github.com/golang/go/issues/79071) です。タイトルは "encoding/json/v2: remove `format` tag option" です。

`format` タグは、フィールドごとに表現の形式を指定する仕組みでした。`time.Time` に `format:RFC1123` を付けて書式を選ぶ、`[]byte` に `format:base64url` を付けて符号化方式を選ぶ、そして `time.Duration` に `format:iso8601` や `format:units` を付けるという具合です。`time.Duration` の議論の結論、つまり「デフォルト値を設定せず、書き手に形式を選ばせる」は、この仕組みを前提にしていました。

`format`タグ取り下げの理由はこう書かれています。

> With Go 1.28 prospectively having typed struct tags in some form or another, the json/v2 working group decided to remove support for the `format` tag option since this would be more naturally expressed as a typed struct tag.
>
> （Go 1.28 で何らかの形で型付き構造体タグが入る見込みであることから、json/v2 ワーキンググループは `format` タグオプションのサポートを削除することを決めました。これは型付き構造体タグとして表現するほうが自然だからです。）

**型付き構造体タグ**という言語機能が入るのを待つ、という判断です。

型付き構造体タグは [`golang/go#74472`](https://github.com/golang/go/issues/74472) で Axel Wagner が2025年7月に提案したもので、現在の文字列タグに加えて、型の付いた定数式を書けるようにする言語変更です。`time.Time \`json:",format:RFC3339"\`` が `time.Time {json.Format(time.RFC3339)}` のように書けるようになります。文字列の中に小さな独自言語を作り込むのをやめて、コンパイラに検査させる方向です。

この提案は2025年11月に「調査する価値はあるが、いま追う余力がない」として保留になりました。ところが2026年4月20日、[Austin Clements が次のように書きます](https://github.com/golang/go/issues/74472#issuecomment-4284572415)。

> I've started meeting with @rsc, @griesemer, @adonovan, and @neild to 'jump start' and prioritize this proposal. Partly this is because the likelihood and timeline of this proposal affects decisions on `json/v2`.
>
> （この提案を起動させ、優先度を上げるために、@rsc、@griesemer、@adonovan、@neild とミーティングを始めました。理由の一部は、この提案の見込みと時期が `json/v2` の決定に影響するからです。）

その10日後に `#79071` が立ち、`format` タグが取り下げられます。言語側の未確定な提案が、標準ライブラリの提案から機能を1つ削る形で作用しました。

4章で引いた [Damien Neil のコメント](https://github.com/golang/go/issues/71497#issuecomment-4224664008)、「新しいものを足すより、初回リリースから機能を一時的に取り下げるほうがずっとありそうだ」は、比喩ではありませんでした。

## time.Durationに残された問題

ここで妙なことが起きています。

`time.Duration` の決着は「形式を明示させる」でした。その形式を明示する手段が `format` タグでした。そして `format` タグは取り下げられました。

実際に試すと、こうなります。

```go
type Config struct {
	Timeout time.Duration `json:"timeout"`
}

type ConfigTagged struct {
	Timeout time.Duration `json:"timeout,format:units"`
}
```

```
v1             : {"timeout":90000000000}  err=<nil>
v2             : {"timeout"  err=json: cannot marshal from Go time.Duration within "/timeout": no default representation
v2 format:units:   err=json: cannot marshal from Go main.ConfigTagged: Go struct field Timeout has unsupported `format` tag option
```

タグなしはエラー、タグありもエラーです。Go 1.27の標準ライブラリの中に、v2で `time.Duration` をシリアライズする手段がありません。自前で `Marshaler` を実装するか、v1を使うことになります。

2017年に Russ Cox が [`#4712`](https://github.com/golang/go/issues/4712) を閉じたときの回答を思い出します。自前で `Marshaler` を実装してくれ、というものでした。`time.Duration` については、9年かけて同じ場所に戻ってきたことになります。

実装そのものは残っています。`arshal_time.go` には `units`、`sec`、`milli`、`micro`、`nano`、`iso8601` を解釈するコードがそのまま入っていて、[有効化のスイッチ](https://go-review.googlesource.com/c/go/+/788420)だけが内部パッケージに隠されています。

そのスイッチを公開しているのが、[`github.com/go-json-experiment/json`](https://pkg.go.dev/github.com/go-json-experiment/json#ExperimentalSupportFormatTag) です。標準ライブラリ側のコメントにこう書かれています。

> NOTE: While [ExperimentalSupportFormatTag] is exported, it is in an internal package and thus inaccessible for public use.
> The [github.com/go-json-experiment/json] module is kept in sync with the Go standard standard library and will expose this option in a way that public code can now directly reference.
>
> （注意: `ExperimentalSupportFormatTag` はエクスポートされていますが、内部パッケージにあるため公開利用はできません。`github.com/go-json-experiment/json` モジュールはGo標準ライブラリと同期が保たれており、公開コードから直接参照できる形でこのオプションを公開します。）

構図が一周しました。標準ライブラリが動けないから外部にプロトタイプが作られ、それが標準に取り込まれ、そして標準から外された機能に触るために、また同じ外部モジュールを使うことになっています。

なお、この `format` タグの取り下げも、`time.Duration` がエラーになることも、[Go 1.27のリリースノート](https://go.dev/doc/go1.27)には書かれていません。リリースノートが `encoding/json` そのものを扱っているのは、["New encoding/json/v2 and encoding/json/jsontext packages"の節](https://go.dev/doc/go1.27#jsonv2)にある、5章で引いた「v2の実装に支えられるようになった」の段落だけです。

## サードパーティの対応

`encoding/json` がv2に載り替えたことは、差し替え可能を売りにしてきたライブラリ群にとって前提の変更です。反応は分かれました。

もっとも真剣に向き合ったのは [`bytedance/sonic`](https://github.com/bytedance/sonic) です。["feat: support Go 1.27" というプルリクエスト](https://github.com/bytedance/sonic/pull/957)で、2500行を超える変更が入っています。そこで作られたのが[互換性の対照表](https://github.com/bytedance/sonic/blob/main/docs/sonic-go127-compatibility.md)で、リポジトリに `docs/sonic-go127-compatibility.md` として置かれています。

対照表が比較しているのは3つです。sonic自身の標準互換モード、Go 1.27のv1（v2の上に載ったもの）、そして `GOEXPERIMENT=nojsonv2` で戻る旧v1。そこに直接のv2を加えた4者の差を記録しています。

CIはGo 1.27をデフォルトと `nojsonv2` の両方で回すようになりました。「`encoding/json` と同じ結果を返す」という約束を維持するために、追いかける対象が増えています。

対照表に記録されている差のいくつかを挙げます。

* float64の範囲を超える数値を読んだとき、Go 1.27はエラーを返したうえで代入先を `+Inf` にしますが、sonicはエラーを返して代入先を `0` のまま残します。
* `map[float64]string` を、sonicは拒否しますがGo 1.27は符号化できます。
* `AppendText` と `MarshalText` の両方がある型で、Go 1.27は `AppendText` を優先します。

[`goccy/go-json`](https://github.com/goccy/go-json) については、GitHub上でv2に関する反応を見つけられませんでした。issueにもREADMEにも言及がなく、ロードマップの記述も以前のままです[^x-goccy54]。

[^x-goccy54]: Xにおいても[特に言及はなさそう](https://x.com/search?q=from%3A%40goccy54%20json%2Fv2%20until%3A2026-08-20&src=typed_query&f=live)です

[`json-iterator/go`](https://github.com/json-iterator/go) はアーカイブされました。最終更新は2024年5月で、リポジトリは読み取り専用になっています。星の数がもっとも多かった置換可能なサードパーティが止まり、その役割が標準に入ったことになります。このライブラリには「100%互換のdrop-in置き換え」を掲げるREADMEと、[「100%互換のdrop-in置き換えではない」というタイトルの未解決issue](https://github.com/json-iterator/go/issues/229)が、8年間並んで残っていました。

## protojsonとjsontextの現状

`jsontext` を生んだのは、`encoding/json` が使えなかった [`protojson`](https://pkg.go.dev/google.golang.org/protobuf/encoding/protojson) でした。その `protojson` は、いま `jsontext` を使っているのでしょうか。

確認してみましたが、まだ使っていませんでした。

[`golang/protobuf#1673`](https://github.com/golang/protobuf/issues/1673) は「protojson に `io.Writer` を渡せるようにする」という issue で、現在も未解決です。2025年1月、Joe Tsai がそこに[設計を書いています](https://github.com/golang/protobuf/issues/1673#issuecomment-2605580160)。

```go
func MarshalWrite(io.Writer, proto.Message) error
func MarshalEncode(*jsontext.Encoder, proto.Message) error
func UnmarshalRead(io.Reader, proto.Message) error
func UnmarshalDecode(*jsontext.Decoder, proto.Message) error
```

そして次のように書いています。

> The entirety of the `internal/encoding/json` package can be removed and replaced with the prospective `encoding/json/jsontext` package. In fact, `internal/encoding/json` can be thought of as an early prototype for what eventually became `jsontext`.
>
> （`internal/encoding/json` パッケージ全体を削除し、将来の `encoding/json/jsontext` パッケージで置き換えられます。実のところ `internal/encoding/json` は、最終的に `jsontext` になったものの初期プロトタイプと考えてよいでしょう。）

乗り換えれば、こういうことも書けるようになります。

```go
json.Marshal(v,
    json.WithMarshalers(json.MarshalToFunc(protojson.MarshalEncode)),
)
```

`proto.Message` をフィールドに含む大きなGoの値を、その部分だけ `protojson` に任せながら一度にシリアライズする形です。

Go Protobuf のメンテナである Michael Stapelberg は、当時「依存を増やしたくないし、vendoringも面倒なので、標準ライブラリに入るのを待つ」という選択をしました。[2026年7月20日のコメント](https://github.com/golang/protobuf/issues/1673#issuecomment-5020103523)には「json/v2 が今月リリースされます。待つという判断は報われたと思う」とあります。

ただし現時点で、protobuf-goのソースに `jsontext` への参照はありません。`internal/encoding/json` も手書きのまま残っています。Go Protobuf は複数の古いGoバージョンを支える方針なので、実際に乗り換えられるのはもう少し先になります。

`jsontext` を生んだJoeが、今度はそれを使うタイミングを待っています。
