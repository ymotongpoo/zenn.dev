---
title: "難所1　uretprobeが使えない"
---

### 症状

関数の入口と出口にプローブを置くだけなら、Goでも同じようにできそうに見えます。ところが、Goのバイナリに対してuretprobeを使うと、最悪の場合、計装対象のGoプログラムが `fatal error: unknown caller pc` でクラッシュします。1章に掲げたエラーの正体がこれです。

計装はあくまで観測が目的であり、観測対象を道連れにするのは許されない挙動です。なぜ観測しただけで対象が落ちるのでしょうか。原因はuretprobeの実装にあります。

## uretprobeの仕組み

5章で見たとおり、戻りアドレスはスタックに積まれ、関数末尾の `RET` 命令がそれを取り出してジャンプします。

uretprobeは、関数に入った瞬間に、スタック上の戻りアドレスを自身の「トランポリン」のアドレスに書き換えます。こうすると関数がreturnする際、本来の呼び出し元ではなく一度カーネルのフックに制御が戻り、そこで処理を行ってから本物の戻りアドレスへジャンプし直します。

つまりuretprobeは「スタック上の戻りアドレスは、書き換えた後も同じ場所に留まり続ける」という前提に立っています。

![uretprobe による戻りアドレスの書き換え](/images/20260820-uretprobe-rewrite.png)
*図1: 実線の矢印は制御の流れ、破線は書き換えられた戻りアドレスが導く先を表す。uretprobeは関数に入った瞬間に、スタック上の戻りアドレスをトランポリンのアドレスへ書き換える。この方式は「戻りアドレスを置いたスタック上の場所は、その後も動かない」ことを前提にしている。*

## Goの可動スタックとの衝突

この前提が、Goでは成り立ちません。goroutineのスタックが伸長のたびに別の領域へ引っ越すことは、6章で見ました。

ここで問題になるのは、ポインタの補正そのものではありません。補正するために、ランタイムがスタックを**辿らなければならない**ことです。

スタックを移すとき、ランタイムはフレームを1つずつ辿ります。次のフレームへ進むには、いま見ているフレームに積まれた戻りアドレスを読み、それがどのGo関数の中のアドレスなのかを引きます。この検索に使うのが、4章で見た `.gopclntab`（命令アドレスからGoの関数名を引く表）です。関数が分かってはじめて、そのフレームの大きさと、フレーム内のどこにポインタがあるかが分かり、補正できます。

uretprobeが書き換えた戻りアドレスは、Goバイナリの関数ではなくカーネルが用意したトランポリンを指しています。表を引いても該当する関数がありません。スタックのコピーやGCの走査は途中でやめられない処理なので、ランタイムは `fatal error: unknown caller pc` で落ちます。go1.26では `runtime/traceback.go` の `unwinder.next` が、戻りアドレスを `findfunc` に渡して失敗したときにこのエラーを投げています。これがGoとuretprobeが相容れない理由です（[golang/go#22008](https://github.com/golang/go/issues/22008)、[#27077](https://github.com/golang/go/issues/27077)）。

![戻りアドレスから関数を引けないと、スタックを辿れない](/images/20260820-unwind-failure.png)
*図2: 実線の矢印は処理の流れ、破線はスタックから読み取る値を表す。ランタイムは戻りアドレスを手がかりに「どの関数のフレームか」を引く。トランポリンのアドレスは表に無いので、そこで辿れなくなる。*

## 動くスタックの実測

「スタックが動く」というのは、日常のGo開発ではまず意識しない挙動です。実際に動くところを見ておくと、以降の話が具体的になります。

次のコードには、結果を見やすくするための仕掛けが3つ入っています。`//go:noinline` は、コンパイラに関数を展開させず呼び出しとして残させる指示です。`grow` の中の `pad` と深い再帰は、スタックを確実に使い切らせるためにあります。`unsafe.Pointer` と `uintptr` は、変数のアドレスを数値として取り出して前後で比べるためだけに使っています。どれも通常のアプリケーションで書く必要のあるものではありません。なお、このコードはOSを問わず動きます。本書の実測はlinux/amd64のものですが、macOSで実行してもアドレスの値が違うだけで、結果の見え方は同じです。

```go
package main

import (
	"fmt"
	"unsafe"
)

//go:noinline
func grow(n int) int {
	var pad [256]byte
	if n == 0 {
		return int(pad[0])
	}
	return grow(n-1) + int(pad[1])
}

func main() {
	var anchor [16]byte
	before := uintptr(unsafe.Pointer(&anchor[0]))
	grow(3000) // 深い再帰で goroutine のスタックを伸ばす
	after := uintptr(unsafe.Pointer(&anchor[0]))

	fmt.Printf("before = %#x\n", before)
	fmt.Printf("after  = %#x\n", after)
	fmt.Printf("moved  = %v\n", before != after)
}
```

`anchor` は `main` のローカル変数で、`grow` の再帰の前後で一度も触っていません。それでも実行するとアドレスが変わります。

```
before = 0x2522317acee8
after  = 0x2522319dfee8
moved  = true
```

具体的なアドレスは実行ごとに変わります。`moved` は、本書で使った go1.26.5 linux/amd64 では毎回 `true` になりました。再帰で `main` のフレームより深いところまでスタックを消費した結果、ランタイムがより大きな領域を確保して、`main` のフレームごと引っ越したのです。このとき `anchor` を指すポインタがあれば、ランタイムはそれも新しいアドレスに書き換えます。

uretprobeが偽の戻りアドレスを書き込んでいた場合、この引っ越しは最後まで進みません。コピーのためにフレームを辿る途中、その値からどの関数のフレームかを引こうとした時点で表に該当がなく、ランタイムはそこで止まるしかないからです。

## 全 `RET` 命令へのuprobe

OBIは、出口専用のuretprobeが使えない以上、通常のuprobeを出口に相当する命令へ直接置くことで対処します。

7章で見たとおりuprobeは任意の命令アドレスに置けるため、関数の先頭ではなく、関数末尾の `RET` 命令のアドレスに置くこともできます。手順は次のとおりです。

1. 対象の関数を逆アセンブルする。
2. 機械語中のすべての `RET` 命令のアドレスを洗い出す。
3. その一つひとつに通常のuprobeを仕掛ける。

これにより、CPUが `RET` を実行して呼び出し元へ戻る直前にeBPFプログラムが発火します。この方式はスタック上の戻りアドレスを書き換えないため、Goの可動スタックと衝突しません。

この方式にも捕まえられない出口が1つだけあります。`recover` されないパニックで終わる場合です。このとき関数は `RET` を実行せずgoroutineごと終わるので、出口のフックは発火しません。もっともその場合はリクエスト自体が失敗しているので、所要時間の記録が残らないことの実害は限られます。

![全 RET 命令へのuprobe](/images/20260820-ret-uprobes.png)
*図3: 矢印は処理の順序を表す。出口フックは、逆アセンブルして見つけた `RET` の一つひとつに通常のuprobeを置く。ソース上の `return` が1つでも、`defer` があれば `RET` は2つになる。*

## 1つの `return` から出る2つの `RET`

「すべての」と書いたのには理由があります。Goのソース上で `return` が1箇所しかなくても、機械語では `RET` が複数生成されるからです。`defer` を1つ書くだけで、この状況になります。

`defer` は「この関数を抜けるときに実行する処理」を登録する構文です。関数の出口が1つに見えても、登録された処理を通ってから抜ける経路が別に必要になります。次のコードの `//go:noinline` は、さきほどと同じく関数を展開させないための指示です。

```go
package main

import (
	"fmt"
	"sync"
)

var (
	mu    sync.Mutex
	cache = map[string]int{}
)

//go:noinline
func Lookup(key string) int {
	mu.Lock()
	defer mu.Unlock()
	return cache[key]
}

func main() {
	fmt.Println(Lookup("go"))
}
```

`go build` したうえで `go tool objdump` にかけると、`RET` が2つ出てきます。以下は `GOOS=linux GOARCH=amd64` でビルドしたバイナリの出力です。手元がmacやWindowsでも、この2つの環境変数を付けてビルドすれば同じものを観察できます（`go tool objdump` はクロスコンパイルしたバイナリも読めます）。左の列はソースの行番号、次がアドレス、その右が命令です。ここで見るべきなのは `RET` と書かれた2行だけで、ほかの命令は読み飛ばしてかまいません。

```
$ go tool objdump -s 'main\.Lookup$' s2_ret
  s2_ret.go:14  0x49e1c0   CMPQ SP, 0x10(R14)
  s2_ret.go:14  0x49e1c4   JBE 0x49e2a1
  ...
  s2_ret.go:17  0x49e28f   POPQ BP
  s2_ret.go:17  0x49e290   RET                                   ← 通常の経路
  s2_ret.go:17  0x49e291   CALL runtime.deferreturn(SB)
  s2_ret.go:17  0x49e296   MOVQ 0x28(SP), AX
  s2_ret.go:17  0x49e29b   ADDQ $0x50, SP
  s2_ret.go:17  0x49e29f   POPQ BP
  s2_ret.go:17  0x49e2a0   RET                                   ← defer 経由の経路
  s2_ret.go:14  0x49e2ab   CALL runtime.morestack_noctxt.abi0(SB)
```

`0x49e290` は通常どおり関数を抜ける経路、`0x49e2a0` は `runtime.deferreturn` を通ってから抜ける経路です。どちらも `s2_ret.go:17`、つまりソース上の同じ `return` に対応しています。

2つ目の経路がいつ選ばれるのかも押さえておきます。`defer` に登録した処理は、通常ならコンパイラが関数の末尾に展開してそのまま実行します。パニックが起きて `recover` で復帰したときは、`runtime.deferreturn` を通って残りの処理を片付けてから関数を抜けます。ループの中の `defer` のようにコンパイラが展開できない場合も、同じ経路を通ります。したがって `0x49e290` にしかuprobeを置かないと、パニックが起きた呼び出しだけ出口を捕まえられません。所要時間の記録が落ちるのはエラー時にかぎられ、平常時のテストでは気付けない抜けになります。

ついでに、この出力には後の節で扱う要素が2つ写り込んでいます。1行目の `CMPQ SP, 0x10(R14)` は、いま説明したスタック伸長の判定です。`R14` の指す構造体の16バイト目に入っている値とスタックポインタを比べ、足りなければ最終行の `runtime.morestack_noctxt` へ飛びます。その `R14` が何なのかは、2つ目の難所で扱います。

## OBIの実装

OBIで `RET` を探しているのは、`pkg/internal/goexec/instructions_amd64.go` の次の関数です。eBPFのCコードではなく、普通のGoで書かれています。

```go
func FindReturnOffsets(baseOffset uint64, data []byte) ([]uint64, error) {
	var returnOffsets []uint64
	index := 0
	for index < len(data) {
		// FIXME remove this once x86asm is able to recognize and decode
		// ENDBR64
		if isENDBRXX(data[index:]) {
			index += endbrSize
			continue
		}

		instruction, err := x86asm.Decode(data[index:], 64)
		if err != nil {
			return nil, fmt.Errorf("failed to decode x64 instruction at offset %d: %w", index, err)
		}

		if instruction.Op == x86asm.RET {
			returnOffsets = append(returnOffsets, baseOffset+uint64(index))
		}

		index += instruction.Len
	}

	return returnOffsets, nil
}
```

`golang.org/x/arch/x86/x86asm` で関数の機械語を先頭から1命令ずつデコードし、`x86asm.RET` だったらその位置を控えます。それだけです。分岐やジャンプを追ってはおらず、バイト列を頭から舐めています。

`isENDBRXX` の分岐は、CPUの間接分岐対策命令 `ENDBR64` をx86asmがまだデコードできないため、4バイト読み飛ばす回避策です。`// FIXME remove this once ...` というコメントが付いたまま残っています。ゼロコード計装が地道な処理の積み重ねであることが、この数行によく表れています。

そして、こうして集めたオフセットの一つひとつにuprobeを結びつけるのが `pkg/ebpf/instrumenter.go` です。

```go
	if probe.End != nil {
		if len(probe.ReturnOffsets) == 0 {
			// ...
			return closers, errors.New("setting uretprobe (attaching to offset): missing return offsets")
		}

		for _, offset := range probe.ReturnOffsets {
			up, err := exe.Uprobe("", probe.End, &link.UprobeOptions{
				Address: offset,
			})
			// ...
			closers = append(closers, up)
		}
	}
```

`exe.Uprobe` の第1引数が空文字列で、`Address` にオフセットを渡している点が、7章で見た「アドレス直指定」の形です。エラーメッセージには `uretprobe` と書かれていますが、実際に呼んでいるのは通常のuprobeです。出口フックという役割の名前だけが残っていて、中身は `RET` の位置に置いた入口フックと同じものになっています。

1つ目の難所は、可動スタックというGoの効率を支える仕組みが、そのまま計装の難しさになっている例です。実装を読まない場合、ここで残るのは1文です。戻りアドレスを書き換えず、機械語中のすべての `RET` に通常のuprobeを置く。
