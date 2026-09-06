---
title: "難所3　バージョン依存のフィールドオフセット"
---

`g` 構造体は中身を読まずに済みました。他の値はそうはいきません。HTTPリクエストのメソッド名やgRPCの呼び出し先は、OBIが構造体の中身を読んで取っています。

8章で見たプロトコル計装なら、ソケットを流れるバイト列から同じものが取れそうに思えます。平文のHTTP/1.1なら実際に取れていて、OBIは `GET /items HTTP/1.1` という先頭のバイト列からメソッドとパスを読み出しています。それでもGoに対して構造体を読むのは、バイト列では届かない場合があるからです。

1つはTLSです。Goは `crypto/tls` を自前で持っていて静的リンクするので、6章で触れたOpenSSLの共有ライブラリの関数にuprobeを置くという手が使えません。ソケットに現れるのは暗号化された後のバイト列だけです。OBIはGoのプロセスに対しては `crypto/tls.(*Conn).Read` と `Write` にuprobeを置き、暗号化される前と復号された後の平文をそこで読んでいます。もう1つはHTTP/2とgRPCです。HTTP/2はヘッダの名前と値をHPACKという仕組みで圧縮し、接続ごとに作る表の索引に置き換えます。2回目以降のリクエストの `:path` は索引だけになるので、その接続を最初のバイトから見ていなければ元の文字列に戻せません。OBIはこの場合、スパン名を `*` に落とします。加えて、ソケットから拾えるのはリクエストの先頭256バイトだけで、ルーティングのテンプレートのように、そもそもバイト列に現れない値もあります。

だからGoに対する計装は、直列化される前の構造体を読みます。`http.Request` の `Method` や `URL`、gRPCの `transport.Stream` の `method` を、バイト位置で読み出します。外部の計装ツールは、どのフィールドがどこにあるかをどうやって知るのでしょうか。ここが4つの中で最も対処が難しい難所です。しくじったときの症状は難所2と同型で、クラッシュではなく、中身の誤ったトレースとして現れます。

## フィールドオフセットとは

2章で見たとおり、外から見えるのはバイト位置だけです。構造体の先頭から何バイト目か、というこのバイト数を**フィールドオフセット**と呼びます。

言い換えると、構造体の先頭を0番地としたときに、そのフィールドの先頭までに何バイトあるかという数です。`unsafe.Offsetof` が返すのもこの数です。

Goのソース上では `req.Method` のようにフィールド名でアクセスできますが、外部から見るeBPFにその名前は見えません。コンパイル済みバイナリの実行中メモリにあるのは、基本的にバイト列とアドレスだけです。したがって外部から読む側は、「`http.Request` の先頭アドレスに56を足した位置に `Header` がある」というように、バイト単位の位置を知っていなければなりません。

## 自分のGoとOBIの表の突き合わせ

このオフセットは、Goからも `unsafe.Offsetof` で取り出せます。

* [Go Playgroundで実行する](https://go.dev/play/p/WkccXeBRibC)

```go
package main

import (
	"fmt"
	"net/http"
	"runtime"
	"unsafe"
)

func main() {
	var r http.Request
	fmt.Println(runtime.Version())
	fmt.Printf("Method        = %d\n", unsafe.Offsetof(r.Method))
	fmt.Printf("URL           = %d\n", unsafe.Offsetof(r.URL))
	fmt.Printf("Header        = %d\n", unsafe.Offsetof(r.Header))
	fmt.Printf("ContentLength = %d\n", unsafe.Offsetof(r.ContentLength))
}
```

```
go1.26.5
Method        = 0
URL           = 16
Header        = 56
ContentLength = 88
```

この4つの数値は、OBIが持っているオフセット表 `pkg/internal/goexec/offsets.json` の中身と一致します。

```json
"net/http.Request": {
  "Method":        { "versions": {"oldest": "1.17.0", "newest": "1.27.1"},
                     "offsets": [{"offset": 0,  "since": "1.17.0"}] },
  "URL":           { "versions": {"oldest": "1.17.0", "newest": "1.27.1"},
                     "offsets": [{"offset": 16, "since": "1.17.0"}] },
  "Header":        { "versions": {"oldest": "1.17.0", "newest": "1.27.1"},
                     "offsets": [{"offset": 56, "since": "1.17.0"}] },
  "ContentLength": { "versions": {"oldest": "1.17.0", "newest": "1.27.1"},
                     "offsets": [{"offset": 88, "since": "1.17.0"}] }
}
```

`versions` が「このエントリが何から何までのバージョンで検証済みか」、`offsets` が「いつからその位置になったか」です。

手元のGoで印字した値と、OBIが事前に用意した表の値は同じです。外から構造体を読むというのは、要するにこの表を信じて `+56` バイト目を読むということです。

`net/http.Request` は運のいい例で、`offsets` の配列が要素1つしかありません。Go 1.17から1.27までのあいだ、一度も動いていません。

## フィールドが1つ増えたときのずれ

構造体の途中にフィールドを1つ足して、前後を比べます。

* [Go Playgroundで実行する](https://go.dev/play/p/HDiUH0QUv3Q)

```go
package main

import (
	"fmt"
	"unsafe"
)

type streamV1 struct {
	ctx    any
	id     uint32
	method string
}

type streamV2 struct { // 内部フィールドが1つ増えただけ
	ctx    any
	cancel func()
	id     uint32
	method string
}

func main() {
	var v1 streamV1
	var v2 streamV2
	fmt.Printf("v1: id=%2d  method=%2d\n", unsafe.Offsetof(v1.id), unsafe.Offsetof(v1.method))
	fmt.Printf("v2: id=%2d  method=%2d\n", unsafe.Offsetof(v2.id), unsafe.Offsetof(v2.method))
}
```

```
v1: id=16  method=24
v2: id=24  method=32
```

追加したフィールドより後ろにあるものが、まとめてずれました。なぜこの数になるのかを、バイトの並びで見ておきます。`any` は型へのポインタとデータへのポインタの2つで16バイト、`func()` はポインタ1つで8バイト、`string` はポインタと長さで16バイトです。`uint32` は4バイトですが、直後の `string` の先頭はポインタなので8バイト境界から始まる必要があり、次の8バイト境界まで詰め物が入ります。

![フィールドを1つ足すと後ろがずれる](/images/20260820-struct-byte-band.png)
*図1: 矢印はフィールドを1つ足したという変更を表す。詰め物の位置と大きさも変わるので、後ろのフィールドは足した分と同じ8バイトだけずれる。*

`method` の位置に24をハードコードしていたコードは、`v2` に対しては `id` と詰め物をまたいだ中途半端な位置を読みます。

## 予告なく変わるオフセット

いま作ってみせた `streamV1` と `streamV2` は、架空の例ではありません。gRPCの `internal/transport.Stream` は、OBIがメソッド名を取り出すために読んでいる構造体で、`method` の位置には4つの値が記録されています。つまり3回変わっています。

| gRPCのバージョン | `Stream.method` のオフセット |
|---|---|
| 1.40.0 以降 | 80 |
| 1.66.0 以降 | 88 |
| 1.69.0 以降 | 24 |
| 1.77.0 以降 | 16 |

内部パッケージ `internal/transport` の型なので、互換性の約束は及びません。Goでは `internal` を含むパスのパッケージを外部から参照できず、この型はライブラリの利用者に見せるものではありません。だから開発者は、更新のときにフィールドの並びを自由に変えられます。その自由さの代償を、メモリ位置で外から読むOBIが引き受けています。同じ表の中では `golang.org/x/net/http2.ClientConn.fr` がさらに動いていて、記録された区間は8つ、位置の変化は7回にのぼります（うち一度は、以前の位置に戻っています）。`offsets.json` 全体では89個の構造体、154個のフィールドを追跡しており、うち43個のフィールドが「過去に一度以上動いた」記録を持っています（v0.13.0時点の数で、構造体のサイズや定数のエントリは除いています）。

![バージョン間でオフセットがずれる](/images/20260820-offset-shift.png)
*図2: 矢印は計装コードがどの位置を読むかを表す。ハードコードした `+88` は grpc 1.66 では `method` を指すが、1.69 では別のフィールドを指す。クラッシュせずに「それらしく動いてしまう」のが最悪の結果になる。*

仮にオフセットをコードにハードコードすると、あるバージョンでは完璧に動きますが、ユーザーが依存ライブラリを上げてビルドし直したアプリに対して使うと、見当違いの位置を読みます。最悪なのは、**クラッシュせずに「それらしく動いてしまう」**ことです。トレースは出るのに、中身が誤っています。オブザーバビリティツールとして、観測対象への信頼を最も損なう挙動です。

## DWARFを先に読み、欠けた分を表で補う

OBIはこれを2つの情報源の併用で解いています。`pkg/internal/goexec/structmembers.go` の入口が、その分かれ目です。

```go
func structMemberOffsets(elfFile *elf.File) (FieldOffsets, error) {
	// first, try to read offsets from DWARF debug info
	var offs FieldOffsets
	var expected map[GoOffset]struct{}
	dwarfData, err := elfFile.DWARF()
	if err == nil {
		offs, expected = structMemberOffsetsFromDwarf(dwarfData)
		if len(expected) > 0 {
			log().Debug("Fields not found in the DWARF file", "fields", expected)
		} else {
			libVersions, err := findLibraryVersions(elfFile)
			if err != nil {
				return nil, fmt.Errorf("searching for library versions: %w", err)
			}
			offs = offsetsForLibVersions(offs, libVersions.versions, log())
			setGoAutoSDKActivationSupport(offs, libVersions, elfFile)
			return offs, nil
		}
	} else {
		// initialize empty offsets
		offs = FieldOffsets{}
	}

	log().Debug("Can't read all offsets from DWARF info. Checking in prefetched database")

	// if it is not possible, query from prefetched offsets
	return structMemberPreFetchedOffsets(elfFile, offs)
}
```

最初に試すのは、計装対象のバイナリ自身に埋め込まれたDWARF（型とフィールド位置を含むデバッグ情報）です。4章で挙げた `.debug_*` がそれです。

DWARFが正解を持っているのは、コンパイラがデバッガのために「この型のこのフィールドは先頭から何バイト目か」を書き残しているからです。デバッガが `req.Method` を名前で表示できるのも同じ情報のおかげです。したがってDWARFを読めるかぎり、OBIは目の前のバイナリに合った値を得られます。バージョン追従の問題はありません。

後述するオフセット表は自動生成されているので、「表が自動で作れるなら、最初から表だけでよいのでは」と思うかもしれません。DWARFが先なのは、この「目の前のバイナリに書かれた正解」という性質のためです。表に載せられるのは、事前にビルドできた既知のバージョンだけです。リリースされたばかりのバージョンや、フォーク、プライベートなモジュールは載っていません。だから正解を先に読み、読めなかった分だけ表で補う、という順序になっています。

コード中の `expected` は「DWARFから読めなかったフィールドの集合」です。これが空なら、DWARFだけで足りたということでそのまま返します。1つでも残っていれば `structMemberPreFetchedOffsets` へ進みますが、ここで取得済みの `offs` を引数として渡している点が大事です。DWARFで読めた値は捨てません。渡された先では `if _, found := fieldOffsets[constantName]; found { continue }` という判定があり、すでに値のあるフィールドは飛ばして、欠けた分だけを表から補います。`TestPrefetchedOffsetsPreserveResolvedOffsets` というテストが、この振る舞いを固定しています。

補う先が、事前に用意した表です。それが `offsets.json` で、`//go:embed` でバイナリに埋め込まれています。

```go
//go:embed offsets.json
var prefetchedOffsets string
```

この表は人手で書くのではなく、`go-offsets-tracker` というツールが、新しいGoや主要ライブラリのリリースのたびにオフセットを自動抽出して更新します。つまりOBIの開発の一部は、Goと主要ライブラリの内部構造を追いかけ続ける作業に費やされています。これがゼロコード計装の隠れたコストです。

C側とGo側の対応づけは、手作業のままです。`structmembers.go` の定数列には、次のコメントが付いています。

```go
// this const table must match what's in go_offsets.h
type GoOffset uint32

const (
	// go common
	ConnFdPos GoOffset = iota + 1
	FdLaddrPos
	FdRaddrPos
	TCPAddrPortPtrPos
	TCPAddrIPPtrPos
	// http
	URLPtrPos
	PathPtrPos
	RawQueryPtrPos
	HostPtrPos
	SchemePtrPos
	MethodPtrPos
	StatusCodePtrPos
	ResponseLengthPtrPos
	ContentLengthPtrPos
	ReqHeaderPtrPos
	IoWriterBufPtrPos
	IoWriterNPos
	IoWriterWrPos
	// ...
)
```

Go側の `iota` の並びと、eBPFのCコード側のヘッダの並びが一致していないと、まったく別のフィールドを読むことになります。この対応を検査する仕組みはありません。C側のヘッダにも `// start at 1, must match what's in structmembers.go` と書かれていて、両側のコメントで実装者が並びを保っています。コンパイラは何も言わず、テストもありません。

この抜粋の末尾にある `IoWriterBufPtrPos`、`IoWriterNPos`、`IoWriterWrPos` の3つは、`bufio.Writer` の `buf`、`n`、`wr` に対応します。標準ライブラリの非公開フィールドがオフセット追従の対象に入っています。これが何のために要るのかは難所4で分かります。

## バイナリからバージョンを割り出す

表を引くには、まず「このバイナリはどのバージョンでビルドされたか」を知らなければなりません。OBIは、Goのリンカがバイナリに残すビルド情報のブロブを直接パースします。

```go
// The build info blob left by the linker is identified by
// a 16-byte header, consisting of buildInfoMagic (14 bytes),
// the binary's pointer size (1 byte),
// and whether the binary is big endian (1 byte).
var buildInfoMagic = []byte("\xff Go buildinf:")
```

ここから `runtime.buildVersion` と `runtime.modinfo` を取り出します。これは `go version -m` が読んでいるものと同じで、Goのバージョンだけでなく、依存モジュールのパスとバージョンとハッシュが並んでいます。

```
$ go version -m ./myapp
./myapp: go1.26.5
	path	example.com/myapp
	mod	example.com/myapp	(devel)
	dep	golang.org/x/arch	v0.30.0	h1:sB9h+1gRGa2+LauFSV0tm8bK1J2yo1bx6/Uyi/P6DTU=
	build	-buildmode=exe
	build	-compiler=gc
	...
```

依存モジュールのバージョンが分かれば、先ほどの `Stream.method` の表から正しい行を選べます。OBIはさらに踏み込んで、モジュールのハッシュ値そのものを持っている箇所もあります。

```go
var goAutoSDKActivationModules = [...]activationModule{
	{
		path: "go.opentelemetry.io/auto/sdk",
		sums: map[string]string{
			"v1.1.0": "h1:cH53jehLUN6UFLY71z+NDOiNJqDdPRaXzTel0sJySYA=",
			"v1.2.0": "h1:YpRtUFjvhSymycLS2T81lT6IGhcUP+LUPtv0iv1N8bM=",
			"v1.2.1": "h1:jXsnJ4Lmnqd11kwkBV2LgLoFMZKizbCi5fNZ/ipaZ64=",
		},
	},
	// ...
}
```

`go.sum` に並んでいるのと同じハッシュです。バージョン文字列だけでなく中身の同一性まで確認したうえで、そのバージョンに固有の処理を有効にしています。

![オフセットを2つの情報源から集める](/images/20260820-offset-resolution.png)
*図3: 矢印は処理の流れで、上から下へ進む。DWARFから読めたフィールドはそのまま使い、読めなかったフィールドだけを `offsets.json` で補う。両者は合流して1つのオフセット表になる。表から補う分だけが、バイナリのバージョンに依存する。*

難所3への対処は、壊れやすさをなくすことではなく、壊れやすさを仕組みで吸収し続けることです。フィールドの位置は、バイナリ自身に書いてある分はDWARFから読み、書いていない分だけを自動更新される表から補う。OBIはこの分担で、Goとライブラリの変化に追いつき続けています。
