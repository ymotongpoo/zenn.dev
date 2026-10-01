# Go/eBPF Primer 独立技術検証

検証日: 2026-09-11。対象は `books/go-ebpf-primer/` の全16章。章番号は `config.yaml` の並び順で数えた。過去の `reviews/` のレポートは参照していない。

**指摘は10件。重大1件、要修正6件、軽微3件。** 同じ誤りの複数章への波及は1件にまとめた。未検証事項はこの件数に含めていない。

## 検証範囲と環境

全16 Markdownファイル、約12.1万文字を読み、章間参照、コード、本文、キャプションを照合した。参照画像59点を表示して確認し、食い違いが疑われた図は対応するDOTのラベルも確認した。公開HTTPS URLは重複を除いて57件あり、HTTP GETで最終到達先まで確認した。すべて200応答だった。Go Playgroundの13件は掲載ソースも取得し、原稿のコードと一致した。

実験場所は `/tmp/go-ebpf-independent-20260911/`。主な環境は Linux `7.0.0-31-generic`、linux/amd64、Go `go1.26.5`、Docker `29.0.0`、Compose `v2.40.3`。Goの実験は `GOTOOLCHAIN=go1.26.5` を指定し、Goのキャッシュもこの一時ディレクトリに置いた。第9章の掲載Dockerfileをそのまま試す段階だけは、原稿の前提どおりChainguardの `go:latest`、Go 1.27.1を使用した。

- 原稿の完全な `package main` のコード15本を抽出し、すべてGo 1.26.5でビルドした。HTTPサーバー2本以外の13本を実行した。サーバー2本は第9章のCompose環境で実行した。
- `go tool objdump`、`go tool nm`、`readelf`、`-gcflags=-m`、`-gcflags=-S`、`strace` を使った。再帰配列を128バイトに変えた場合、インライン展開を許した場合、cgo有無、strip有無も追加検証した。
- [OBI v0.13.0のタグアーカイブ](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/tree/v0.13.0)を取得し、引用されるC/Goコード、マップ、アタッチ処理、オフセット表、サポート表を確認した。Git操作は使っていない。リリースコンテナの実行ログでもコミット `3cc1986` を確認した。
- OBIの `pkg/internal/goexec` にあるDWARF読取、strip済みバイナリ、既存オフセットの保持、gRPCの表、版別オフセットに関する5テストを実行し、通過した。
- 第9章のfrontend、backend、OBI、LGTMを独立したComposeプロジェクトで起動した。Grafana経由のTempo/Prometheus APIで7スパンの親子関係、REDメトリクス、サービスグラフの系列を確認した。伝搬を有効にした場合と無効の場合も比較した。
- OBIとは別に、原稿の再帰サンプルへbpftraceでuretprobeを付け、Go 1.26.5の `unknown caller pc` を再現した。引数3個のサンプルには通常のuprobeを付け、レジスタ値も確認した。
- [otelc v1.1.0](https://github.com/open-telemetry/opentelemetry-go-compile-instrumentation/tree/v1.1.0)をタグアーカイブからビルドした。Gitを呼ぶMakefile変数は `make build VERSION=v1.1.0 COMMIT_HASH=archive` で指定した。掲載のHTTPクライアントを `otelc go build` でビルドし、残った `roundtrip.go` を読んだ。
- Go公式のABI文書とランタイム実装、ELF仕様、DWARF 5、RFC 7541、RFC 9110、W3C Trace Context、Linuxのタグ・コミット・stable ChangeLogを確認した。

原稿に固定のアドレスやサイズがある場合、変動する値と命令・レイアウトの違いを区別した。たとえばPID、ヒープのアドレス、hostnameは環境で変わるため、その値の違い自体は指摘していない。

## 重大

### 1. 既存のtraceparentがあっても、OBIが二重注入する場合がある

**場所**: 第13章 `55-hurdle4_propagation.md:294`。

> アプリがSDK計装で自分の `traceparent` をすでに付けている場合、OBIは書き込みません。SDK計装との同居でヘッダが二重になることはありません。

**何が誤りか**: v0.13.0には既存ヘッダを検出する処理があるが、その探索範囲には上限がある。「二重になることはない」という保証にはならない。既存の `traceparent` より前に大きなヘッダがあると見落とし、別のトレースIDを持つ2個目の `Traceparent` を追加することを実機で再現した。SDKと同居させる際の判断に直接影響する。

**根拠**:

- [`client_request_has_traceparent`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/bpf/gotracer/go_nethttp.c#L969-L1008)は、`writeSubset` が書いた範囲を `TRACE_BUF_SIZE - 1` に切り詰めて探索する。[`TRACE_BUF_SIZE` は1024](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/bpf/common/http_buf_size.h#L10)なので、先頭1023バイトより後ろのヘッダはこの検査から外れる。
- [呼出側](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/bpf/gotracer/go_nethttp.c#L1067-L1088)は、検査がfalseなら、バッファに空きがある場合にヘッダを追加する。
- 第9章の一時コピーに検証用エンドポイントを追加した。frontendからbackendへ送るリクエストを次のように作り、backendで `r.Header.Values("Traceparent")` をJSON出力した。実際のSDKは組み込まず、SDKが生成するものと同形式の既存ヘッダを設定して検査を切り分けた。

```go
req, _ := http.NewRequest("GET", backend+"/headers", nil)
req.Header.Set("Traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
req.Header.Set("A-Pad", strings.Repeat("a", n))
resp, err := http.DefaultClient.Do(req)
```

frontend/backendを `GOTOOLCHAIN=go1.26.5 CGO_ENABLED=0 go build` でビルドし、OBI v0.13.0、`OTEL_EBPF_BPF_CONTEXT_PROPAGATION=all` で測定した。

```console
$ curl -fsS 'http://localhost:8080/verify?pad=0'
["00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"]
$ curl -fsS 'http://localhost:8080/verify?pad=1200'
["00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01","00-8e0bc4994a569227df51b75d7105013b-0021d8210fdbbd8b-01"]
```

この環境では `tpinjector` がFIONREAD検査で停止している。したがって、2経路が同時に注入した結果ではなく、Goのバッファ書換経路だけで発生した。Go 1.27.1でも同じ結果だった。ソースとログは一時ディレクトリの `handson/frontend/main.go`、`handson/backend/main.go`、`handson/duplicate-go126.log` にある。

**修正案**:

> アプリが書いた `traceparent` を検出すると、OBIは追加の書き込みを見送ります。ただしv0.13.0の検査には探索範囲の上限があります。大きなヘッダが先に並ぶと既存の `traceparent` を見落とし、二重に注入する場合があります。SDK計装との同居で常に重複を防げるわけではありません。

**確信度**: 高。**重要度**: 重大。

## 要修正

### 2. 「ライブラリ関数の計装はGoだけ」はJavaの実装と一致しない

**場所**: 第1章 `00-introduction.md:19`、第6章 `25-go_runtime.md:13`、第8章 `35-obi.md:42`・`:45`・`:70`。第8章の図2 `/images/20260911-obi-two-paths.png` も対象。

> 他の言語でもランタイム内部の関数にはフックを置きますが、その上で動くライブラリには届きません。

> 届かないのは、その上で動くライブラリの関数です。

**何が誤りか**: OBI v0.13.0には、Javaの第三者ライブラリNettyのメソッドを計装する実装もある。GoのELFにuprobeを置く方式と、Javaエージェントによるクラスの変換を区別する必要がある。固定アドレスの解析をJIT上のコードにそのまま適用できないことから、OBI全体として「ライブラリに届かない」とは言えない。

**根拠**: [`NettySSLHandlerInst.java:15–34`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/internal/java/agent/src/main/java/io/opentelemetry/obi/java/instrumentations/NettySSLHandlerInst.java#L15-L34)は `io.netty.handler.ssl.SslHandler` を指定し、`unwrap` と `wrap` にByte BuddyのAdviceを付ける。[`Agent.java`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/internal/java/agent/src/main/java/io/opentelemetry/obi/java/Agent.java#L150-L174)がこの変換を登録し、[ロード済みクラスにも再変換を行う](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/internal/java/agent/src/main/java/io/opentelemetry/obi/java/Agent.java#L195-L225)。この実装はTLS処理の文脈を追うためのもので、GoのHTTP/gRPC計装と同一の機能範囲だという意味ではない。

**修正案**:

> 本書で扱うのは、Goの実行ファイルに含まれる `net/http` やgRPCの関数へuprobeを置く計装です。OBIには、Javaエージェントを使ってNettyのTLS処理を補助する実装もあります。Goでは、ライブラリを含む機械語の位置を実行ファイルから割り出せるため、このアドレスを使った計装を組み立てられます。

図2の「ライブラリ関数まで届くのはGoだけ」というラベルも、「本書の対象: Goのライブラリ関数へのuprobe計装」などへ変更する。第1・6・8章の同じ断定をまとめて直す。

**確信度**: 高。**重要度**: 要修正。

### 3. スタック走査で現在のフレームを解釈する順序が逆になっている

**場所**: 第10章 `40-hurdle1_uretprobe.md:26–32`、`:57–58`。図2 `20260911-stack-walk.png`、図3 `20260911-unwind-failure.png`。

> 出発点は、いま実行中の関数のフレームです。ランタイムはそこに積まれた戻りアドレスを読みます。……関数が分かると、そのフレームの大きさと、フレームのどこにポインタがあるかも分かります。

> フレームの大きさとポインタの位置は、戻りアドレスから引いた関数の情報として得られる。

**何が誤りか**: 現在のフレームに保存された戻りアドレスが指すのは呼び出し元であり、現在の関数ではない。通常のamd64の走査では、まず現在のPCから現在の関数を特定し、その関数のSP差分情報を使って戻りアドレスの位置を求める。戻りアドレスから特定する関数は次に処理する呼び出し元である。原稿と図2は、この対応を省いたため、戻りアドレスを読まないとその保存位置も求まらない循環した説明になっている。

**根拠**: Go 1.26.5の [`unwinder.initAt`](https://github.com/golang/go/blob/go1.26.5/src/runtime/traceback.go#L151-L215)は保存PC/SPを取り、`findfunc(frame.pc)` で初期フレームを特定する。[`resolveInternal`](https://github.com/golang/go/blob/go1.26.5/src/runtime/traceback.go#L327-L379)は `frame.sp + funcspdelta(f, frame.pc) + PtrSize` を計算し、そこから8バイト戻った位置に保存された戻りアドレスを読む。[`next`](https://github.com/golang/go/blob/go1.26.5/src/runtime/traceback.go#L441-L498)で `findfunc(frame.lr)` を呼び、成功したら `frame.fn = flr`、`frame.pc = frame.lr`、`frame.sp = frame.fp` として呼び出し元へ進む。

図3にも関連する不整合がある。DOTの `20260911-unwind-failure.dot:23–25` は上から「いま見ているフレーム→戻りアドレス→呼び出し元」と並ぶが、同章の図2は「上が高いアドレス」と明記して、呼び出し元を上、現在のフレームを下に描く。図3だけ低アドレスを上にする説明はない。同じ走査を説明する図なので向きを統一したい。

**修正案**:

> 出発点は、停止しているgoroutineのPCとSPです。ランタイムはPCから現在の関数を特定し、その関数の情報を使ってフレームの大きさとポインタの位置を調べます。フレームの大きさが分かると、呼び出し元へ戻るアドレスが保存されている位置も分かります。その戻りアドレスから呼び出し元の関数を引き、SPを進めて次のフレームを処理します。uretprobeのトランポリンに置き換わった値では呼び出し元を特定できず、走査がそこで止まります。

図2は「現在のPCから関数を特定→現在フレームの情報を取得・補正→戻りアドレスを取得→呼び出し元へ」とする。図3は高アドレス側から「呼び出し元→戻りアドレス→現在のフレーム」に並べ、戻りアドレスから引く対象を「呼び出し元の関数」と明記する。

なお、uretprobeでクラッシュするという結論自体は正しい。掲載サンプルへのプローブで `runtime.(*unwinder).next → runtime.copystack → runtime.newstack` の経路を実測した。

**確信度**: 高。**重要度**: 要修正。

### 4. 引数3個の例で、RDIに「別の引数」があるとは限らない

**場所**: 第5章 `20-function_call.md:106–107`、第11章 `45-hurdle2_abi.md:25`。図 `20260911-convention-stack-vs-register.png`。

> エラーにはならず、別の引数の値が読めてしまう。

> 空でもゼロでもなく、別の引数の値がそこにあります。

**何が誤りか**: 図の `f(a, b, c)` は、AX/BX/CXへそれぞれ1値を渡す例である。この呼出しはRDIに引数を割り当てないので、RDIの値はこの関数の引数としては未規定である。たまたま別の引数と同じ数値になっても、その引数をRDIで渡したことにはならない。ゼロの可能性も排除できない。文字列などの分解で4本目まで使う場合の説明は、原稿の後半が正しい。

**根拠**: [Go 1.26.5 ABIInternalの引数割当規則](https://github.com/golang/go/blob/go1.26.5/src/cmd/compile/abi-internal.md#function-call-argument-and-result-passing)。掲載の `Add3(1, 2, 3)` をビルドして確認した。

```console
$ GOTOOLCHAIN=go1.26.5 go tool objdump -s 'main.main$' demo
...
0x49e1ae  b801000000  MOVL $0x1, AX
0x49e1b3  bb02000000  MOVL $0x2, BX
0x49e1b8  b903000000  MOVL $0x3, CX
0x49e1bd  0f1f00      NOPL 0(AX)
0x49e1c0  e8bbffffff  CALL main.Add3(SB)
```

呼出し準備でDIは設定されていない。uprobeで入口を読むと、この実行では `AX=1 BX=2 CX=3 DI=1` だった。DI=1はABIによる引数の割当ではなく、残っていた値である。

**修正案**:

> Cの規約を前提に第1引数として `RDI` を読むと、Goの第1引数とは違う場所を読んでしまいます。Goが4本目の整数レジスタまで使う呼び出しなら別の引数成分が入り、この例のように3本で足りる呼び出しなら、その値は引数としては未規定です。読み取り自体は成功するため、取り違えに気づきにくい点は同じです。

図のDI欄も「この例では引数を割り当てない」とする。

**確信度**: 高。**重要度**: 要修正。

### 5. double(21)のインライン展開後には「2倍の計算」も残らない

**場所**: 第5章 `20-function_call.md:128–129`、`:145`。図 `20260911-inlining.png`、DOT `20260911-inlining.dot:33`。

> `main.main` の中に `double` の中身（2倍の計算）が直接埋め込まれています。

**何が誤りか**: インライン展開の一般説明としては分かるが、直前に指定した `double(21)` の実験結果の説明としては一致しない。Go 1.26.5では定数畳み込みも行われ、42という値をロードする。図は実際の命令アドレスを使いながら、展開後も同じ位置に2倍の計算が残るように描いている。

**根拠**: 第4章のコードから `//go:noinline` の行だけを除いてビルドした。`-gcflags=-m` では `inlining call to double`、`go tool nm` では `main.double` が存在しないことを確認した。`main.main` の逆アセンブルは次のとおりだった。

```console
$ GOTOOLCHAIN=go1.26.5 go tool objdump -s 'main.main$' demo
...
0x49e194  b82a000000  MOVL $0x2a, AX
0x49e199  e8629cfdff  CALL runtime.convT64(SB)
...
```

`0x2a` は42。`double` の `ADDQ AX, AX` は残らない。保存した全出力は `samples/inline/objdump.log`。

**修正案**:

> `double` がインライン展開され、`CALL main.double` が残っていないからです。この例では引数が定数21なので、展開された計算もコンパイル時に42へ畳み込まれます。`main.main` には42を読み込む命令が残り、シンボル `main.double` は消えます。

図も「42をロード」に変更し、展開後のアドレスは実測に合わせるか省略する。

**確信度**: 高。**重要度**: 要修正。

### 6. HPACKの索引は、必ず接続の先頭から観測しないと復元できないものではない

**場所**: 第12章 `50-hurdle3_offsets.md:9`。

> 2回目以降のリクエストの `:path` は索引だけになるので、その接続を最初のバイトから見ていなければ元の文字列に戻せません。

**何が誤りか**: `:path` が2回目以降必ず索引になるわけではない。さらに、索引には静的テーブルと動的テーブルがある。静的テーブルの `:path: /` などは過去の通信がなくても解釈できる。過去の状態が必要なのは、観測できていない動的テーブル項目への参照などの場合である。

**根拠**: [RFC 7541 §2.3](https://www.rfc-editor.org/rfc/rfc7541.html#section-2.3)、[§6.2](https://www.rfc-editor.org/rfc/rfc7541.html#section-6.2)、[付録A](https://www.rfc-editor.org/rfc/rfc7541.html#appendix-A)。静的テーブルの4番は `:path: /`、5番は `:path: /index.html`。索引追加を行わないリテラル形式も規定されている。

Go 1.26.5、`golang.org/x/net v0.58.0` の `http2/hpack` で、同じEncoderに各ヘッダを2回ずつ渡し、各出力を**毎回新しいDecoder**で読み取った。

```text
84 -> [header field ":path" = "/"] error=<nil>
84 -> [header field ":path" = "/"] error=<nil>
158362a2f8 -> [header field ":path" = "/new" (sensitive)] error=<nil>
158362a2f8 -> [header field ":path" = "/new" (sensitive)] error=<nil>
```

`/new` は `Sensitive: true` でnever-indexedの例とした。コードと実行環境は一時ディレクトリの `hpack/` にある。

**修正案**:

> HTTP/2はヘッダをHPACKで圧縮し、名前や値を静的テーブルや接続ごとの動的テーブルの索引で表すことがあります。観測を始める前に登録された動的テーブルの項目が参照されると、元の文字列を復元できない場合があります。一方、静的テーブルの項目や、その場で文字列が送られる形式なら、過去の通信を見ていなくても読めます。

続くOBIの `*` へのフォールバック説明は、「必要なヘッダを復元できない場合」に限定してつなぐ。

**確信度**: 高。**重要度**: 要修正。

### 7. 親goroutineを遡る処理は送信側専用ではない

**場所**: 第13章 `55-hurdle4_propagation.md:193`。

> 受信側がするのは書き込みだけで、遡るのは送信側です。

**何が誤りか**: サーバー側の処理にも `find_parent_goroutine` の呼出しがある。リクエスト受信時の記録と、クライアント送信時の検索という代表経路は説明できているが、それをOBI全体の排他的な役割分担として断定している。

**根拠**:

- [`go_nethttp.c:529–548`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/bpf/gotracer/go_nethttp.c#L529-L548): `serve_http_returns` は自分のキーでサーバー要求が見つからないと親を探索する。
- [`go_nethttp.c:1136–1160`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/bpf/gotracer/go_nethttp.c#L1136-L1160): HTTP/2サーバーのヘッダ処理にも同様の経路がある。
- [`go_grpc.c:221–243`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/bpf/gotracer/go_grpc.c#L221-L243): `serverHandlerTransport_HandleStreams` で親を探し、サーバー接続情報を取得する。

**修正案**:

> ここで追っている経路では、受信時に記録した情報を送信時に検索します。同じ親子関係の探索は、HTTP/2の応答処理など、サーバー側で別のgoroutineに引き継がれた処理を結び付ける場面にも使われています。

**確信度**: 高。**重要度**: 要修正。

## 軽微

### 8. オフセット表の「89個の構造体」は、除外条件と数え方が一致していない

**場所**: 第12章 `50-hurdle3_offsets.md:134`。

> 89個の構造体、154個のフィールドを追跡しており……構造体のサイズや定数のエントリは除いています。

**何が誤りか**: 154フィールド、変化した43フィールドは再計算と一致する。89は、90個のトップレベルキーから定数群の `internal/abi` だけを除いた数であり、`$size` しか持たない10個の型キーが残っている。またキーにはスライス型 `[]internal/abi.Imethod` も含まれるので、そのまま構造体数とは呼べない。

**根拠**: [v0.13.0のoffsets.json](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/internal/goexec/offsets.json)を次のコードで集計した。

```python
import json
D = json.load(open("pkg/internal/goexec/offsets.json"))["data"]
fields = [(typ, name, item)
          for typ, members in D.items() if typ != "internal/abi"
          for name, item in members.items() if name != "$size"]
print(len(D), len({typ for typ, _, _ in fields}), len(fields))
print(sum(len(item["offsets"]) > 1 for _, _, item in fields))
# 90 79 154
# 43
```

**修正案**:

> `offsets.json` 全体では、構造体のサイズや定数を除いて154項目のフィールド位置を追跡しており、うち43項目に「過去に一度以上動いた」記録があります（v0.13.0時点）。

**確信度**: 高。**重要度**: 軽微。

### 9. otelcの「実際に書き換えた後の姿」は、識別子変更と省略が未注記

**場所**: 第15章 `65-conclusion.md:76–124`。

> net/http/roundtrip.go（otelcが実際に書き換えた後の姿。実機で確認）

```go
func (t *Transport) RoundTrip(req *Request) (_r0 *Response, _r1 error)
```

**何が誤りか**: v1.1.0、Go 1.26.5で再生成したコードの意味は説明と合っていた。ただし「実際」のコードとされる引用は逐語ではない。戻り値名は `_r0` / `_r1` ではなく `_unnamedRetVal_3038199408_0` / `_unnamedRetVal_3038199408_1`。`recover` 内にあるエラー詳細・スタックの出力処理と `//line` 指示も省かれている。省略の注記はgetter/setterにしか付いていない。

**根拠**: 実行したコマンドは次のとおり。すべて取得したタグアーカイブの一時コピー内で実行した。生成前のGo 1.26.5の `net/http/roundtrip.go` も引用と照合した。

```console
$ GOTOOLCHAIN=go1.26.5 make build VERSION=v1.1.0 COMMIT_HASH=archive
$ cd demo/app/http/client
$ GOTOOLCHAIN=go1.26.5 ../../../../otelc go build -o client .
WORK=/tmp/go-build1902348119
```

生成された `/tmp/go-build1902348119/b078/roundtrip.go:29` は次のシグネチャだった。before/afterフックのハッシュ `3038199408` は一致した。

```go
func (t *Transport) RoundTrip(req *Request) (_unnamedRetVal_3038199408_0 *Response, _unnamedRetVal_3038199408_1 error)
```

**修正案**: コードを逐語へ戻すか、冒頭コメントと省略注記を次のようにする。

> 以下は実際の生成コードからの抜粋です。読みやすくするため、戻り値の長い識別子を `_r0` と `_r1` に置き換えています。`//line` 指示、getter/setter、フック失敗時のエラー詳細とスタックを表示する部分は省略しました。

**確信度**: 高。**重要度**: 軽微。

### 10. ebpf.ioの日本語版に差し替えられる

**場所**: 第1章 `00-introduction.md:7`、第7章 `30-ebpf.md:7` の `https://ebpf.io/`。

> [eBPF](https://ebpf.io/)

**何が誤りか**: リンク切れでも技術的な誤りでもないが、指定された日本語版優先の確認基準では差し替え対象になる。

**根拠**: [https://ebpf.io/ja/](https://ebpf.io/ja/) はHTTP 200で、最終URLも `/ja/` のまま。本文に「eBPFとは？」「eBPFを始める」などの日本語コンテンツがある。英語版へのリダイレクトではなかった。

**修正案**: 表示文言は維持してリンク先を `https://ebpf.io/ja/` に変更する。

**確信度**: 高。**重要度**: 軽微。

## 確かめて問題がなかった重要な主張

| 章 | 検証した主張と結果 | 主な根拠・記録 |
|---|---|---|
| 2 | `byte` 1バイト、`int` 8バイト、recordのオフセット0/8/16とサイズ24が一致。ポインタの16進表示と整数値も一致 | `samples/ch02-*` の実行ログ。Go 1.26.5 linux/amd64 |
| 3 | `os.ReadFile` がopen/readへ進むこと、別実行のPID・メモリアドレスが変わることを確認 | `strace` と `samples/ch03-*`。hostname、FD番号は実行環境依存 |
| 4 | 非インラインの `double` は `ADDQ AX, AX` と `RET`。原稿のアドレス `0x49e180` / `0x49e183` も一致 | `samples/ch04-block0/`、`detail_samples.log` |
| 4・6 | 掲載前提のLinuxで `net/http` はcgo有効なら動的リンク、`CGO_ENABLED=0` なら静的リンク | `extra/app0` と `extra/app1` の `file` 出力。Goのコードが実行ファイルに含まれるという説明は維持できる |
| 5 | 64バイト配列で再帰フレーム間隔176バイト、128バイトに変えると240バイト | `samples/ch05-block0/` と `samples/descend128/` |
| 7・10 | amd64 uretprobeがユーザースタックの戻りアドレスを書き換えること | [Linux v7.0の実装](https://github.com/torvalds/linux/blob/v7.0/arch/x86/kernel/uprobes.c#L1755-L1784)。arm64ではx30を書き換えるため、本書のamd64前提が必要 |
| 7・10 | x86の新しいuretprobeトランポリンが `syscall` を使う経路はv6.11にあり、v6.10にはない | `sources/linux6.10-uprobes` と `sources/linux6.11-uprobes` の比較 |
| 8 | OBIのDevelopment状態、v0の互換性保証、Goライブラリ計装のサポート下限 | [VERSIONING.md](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/VERSIONING.md)、[SUPPORT_MATRIX.md](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/SUPPORT_MATRIX.md)。下限は機能・環境別に読む必要がある |
| 9 | SDKも明示的な `context.Context` 受渡しもないfrontend→backendで親子トレースが取れる | `handson/full-trace.json`。frontend側4、backend側3の計7スパンを確認 |
| 9 | メトリクスにfrontend/backendのサービス名、200/500/502のステータス系列がある | `handson/metrics.json`。本文のPromQLに必要な `service_name` ラベルも今回のLGTM構成では存在 |
| 9 | 伝搬無効ではbackendのtraceparentが空、有効なら値が届く | `handson/obi-disabled.log` と `handson/obi-all.log`。FIONREAD警告と経路2停止のログも再現 |
| 9 | FIONREAD変更の6.19系列への導入は6.19.4 | [ChangeLog-6.19.4](https://cdn.kernel.org/pub/linux/kernel/v6.x/ChangeLog-6.19.4)に `929e30f9312514902133c45e51c79088421ab084` を確認。6.19.1〜3にはない。6.6.128、6.12.75、6.18.14にも同コミットを確認 |
| 10 | `grow(3000)` の前後でスタック上のanchorのアドレスが変わる | 掲載コードを実行して `moved=true` |
| 10 | uretprobeによる `unknown caller pc` は現行の指定Goでも再現する | `uretprobe-crash.log`。トランポリン `0x7fffffffe000`、`unwinder.next`、`copystack`、`newstack` が記録された |
| 10 | `Lookup` の2個のRETと、OBIが通常のuprobeを全RETへ置く対処 | 掲載コードのRETは `0x49e290` と `0x49e2a0`。[`instructions_amd64.go`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/internal/goexec/instructions_amd64.go#L26-L50)と[`instrumenter.go`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/ebpf/instrumenter.go#L848-L883)を照合 |
| 11 | Goの整数レジスタ順、文字列・interface・sliceの複数成分、amd64のR14とarm64のx28 | [Go 1.26.5 ABIInternal](https://github.com/golang/go/blob/go1.26.5/src/cmd/compile/abi-internal.md)、OBIの `bpf/bpfcore/utils.h`。`Add3` の逆アセンブルと入口レジスタも測定 |
| 11・13 | goroutine識別にgoidの値を読まず、gのアドレスとPIDをキーにする | OBIの `go_addr_key_t`、`go_addr_key_from_id`、`GOROUTINE_PTR`、goroutine関連マップの定義・使用箇所を照合 |
| 12 | `http.Request` のMethod=0、URL=16、Header=56、ContentLength=88 | `unsafe.Offsetof` の実行結果とv0.13.0の表が一致 |
| 12 | サンプルstreamV1のid=16/method=24、V2のid=24/method=32 | 掲載コードのビルド・実行で一致 |
| 12 | gRPC Stream.methodの80→88→24→16という表の履歴 | OBIの `offsets.json` と取得したgrpc-go v1.66.0、v1.69.0、v1.77.0の `internal/transport/transport.go` を照合。v1.69の+88はmethodではなく別フィールド側になるという図の趣旨も一致 |
| 12 | DWARFで得たオフセットは保持され、足りない分だけ表で補われる | `TestPrefetchedOffsetsPreserveResolvedOffsets` 等が通過。`obi-goexec-test.log` に `ok .../pkg/internal/goexec 39.690s` |
| 12・15 | 表で変化履歴がある43フィールドのうちruntime系は20 | `offsets.json` を直接集計。「半分近く」という説明は一致 |
| 13 | 親検索の6回は自分自身と親5世代。見つからないと新しいtrace IDを作る | `find_parent_goroutine` と `client_trace_parent` の分岐を照合。深い階層の実通信実験は未実施 |
| 13 | ヘッダを `http.Header` のmapへ追加するのでなく、writeSubset後のbufio.Writerへ書く | `DumpRequestOut` の掲載出力が一致。Cの追記処理、`n` 更新、経路2を抑制するマップ削除もソースと一致。ただし指摘1の例外がある |
| 13 | `GUARDED_PROG` と専用スタックの問題には該当するカーネル変更がある | [8c7dcb84e3b7](https://github.com/torvalds/linux/commit/8c7dcb84e3b744b2b70baa7a44a9b1881c33a9c9)、[a76ab5731e32](https://github.com/torvalds/linux/commit/a76ab5731e32d50ff5b1ae97e9dc4b23f41c23f5)を取得。v5.19/v6.0、v6.12/v6.13のソースでも導入を確認。カーネルクラッシュの誘発実験はしていない |
| 14 | stripでDWARF8セクションとsymtabが消え、gopclntabとビルド情報は残る | `extra/app1.sections`、`extra/app_stripped.sections`、`go tool nm`、`go version -m`。元コード未掲載のためバイト単位のファイルサイズは照合対象外 |
| 14 | `net/http.serverHandler.ServeHTTP` はGo 1.26.5でインライン化されない | `-gcflags=net/http=-m=2` の出力は `function too complex: cost 96 exceeds budget 80` |
| 15 | goroutineleak profileはGo 1.26.5で実験フラグが必要。FlightRecorderのAPIも利用できる | `leakprofile/main.go` を通常ビルドと `GOEXPERIMENT=goroutineleakprofile` で実行。`pprof.Lookup("goroutineleak")` はそれぞれnil/non-nil、FlightRecorderのStartは両方成功 |
| 15 | otelcは `-work -toolexec` を使い、ライブラリ側の関数にフックを挿入する | otelcをビルドして生成ソースを確認。before/afterと `SetParam` の説明は一致。逐語引用には指摘9の差異がある |
| 16 | 用語集の章番号と本文の対応 | `config.yaml` の順序を使って照合。明白な章番号のずれは見つからなかった |

uretprobe再現に使ったコマンドは次のとおり。対象は一時ディレクトリのサンプルだけである。

```console
$ docker run --rm --privileged --pid=host \
  -v /tmp/go-ebpf-independent-20260911:/tmp/go-ebpf-independent-20260911 \
  quay.io/iovisor/bpftrace:latest bpftrace \
  -e 'uretprobe:/tmp/go-ebpf-independent-20260911/samples/ch10-block1/demo:main.grow { }' \
  -c /tmp/go-ebpf-independent-20260911/samples/ch10-block1/demo
Attaching 1 probe...
runtime: g 1: unexpected return pc for main.grow called from 0x7fffffffe000
...
fatal error: unknown caller pc
...
runtime.(*unwinder).next(...)
runtime.copystack(...)
runtime.newstack()
runtime.morestack()
```

このbpftraceコンテナは終了時にtracefsパスに関するdetach警告を出した。終了後に別コンテナでtracefsの `uprobe_events` を読み、残留エントリがないことを確認した。

## リンク・図版・章間整合性

公開リンク57件の最終HTTPステータスはすべて200。リンク先の内容も、引用される実装、仕様、導入記事、issue、リリース情報と照合した。外部URLの原記録は `link_results.json`、取得本文は `links/` にある。サンプル用の `localhost`、`backend`、`lgtm`、`service-b` は公開リンクとしては数えていない。第9章のサービスURLはCompose環境で検証し、`service-b` は `DumpRequestOut` 内の例示ホストとして扱った。

HTTPメトリクスの英語版リンクについては `/ja/docs/specs/semconv/http/http-metrics/` にアクセスしたが、英語版へリダイレクトされた。指定の基準に従い、日本語版への変更は求めない。`docs.kernel.org` のBPF章について試した日本語対応パスは404だった。英語の一次ソースすべてについて翻訳の不存在を証明したわけではない。

図版59点にファイル欠落はなかった。技術内容に関係する修正対象は指摘2〜5にまとめた。第9章のスクリーンショットは今回のAPI取得データと、サービス・スパン・メトリクスの意味を照合した。画像のピクセル一致や時刻・IDの一致は求めていない。章の前方・後方参照はconfig順で確認し、章番号の誤参照は見つからなかった。

## 未検証・判断を限定した事項

1. **他アーキテクチャと別OS**: arm64のレジスタ・uretprobeの違いは一次ソースで確認したが、arm64機での実行はしていない。第10章の「macOSでも同じ見え方」という主張もmacOS上では未実行。
2. **カーネル・権限の全組合せ**: lockdown、各capability、BTFなし、古いカーネル、ディストリビューション独自バックポートの各組合せは未実行。`GUARDED_PROG` を外してカーネルクラッシュを起こす実験はしていない。第8章の起動条件はサポートマトリクスに照らした確認であり、全環境での実証ではない。
3. **第13章のすべての伝搬経路**: HTTP/1.1のGoバッファ注入は実測した。TLS、HTTP/2、gRPC、TCPオプション、L7プロキシ、channel・worker pool・探索上限を組み合わせた網羅実験はしていない。この部分はv0.13.0のC/Goコードと設計文書による確認。FIONREAD検査で停止した経路2を強制的に有効化することもしていない。
4. **すべての引用コードの独立コンパイル**: 完全なGoプログラム15本はビルドしたが、説明用の関数・型・Cマクロの断片は、それぞれ独立プログラムに作り直してはいない。OBIのeBPFオブジェクトをローカルのclangから全再生成する検証もしていない。タグソースとの照合と、公式リリースイメージによる動作確認を区別した。
5. **第14章の実行ファイルサイズの完全一致**: 比較対象の `main.go` 全文が掲載されていないため、5444719/3748002バイトという数値は再現条件が不足する。自作の最小net/httpサーバーではセクション数・stripの効果を確認したが、そのサイズの正誤は判断しない。
6. **第12章の「対応を検査する仕組みもテストもない」**: 列挙順のコメントと、関連するGo/Cの定義、goexecのテストを確認した範囲では、両言語のenum全体を突き合わせる専用検査は発見できなかった。ただし全CI・生成ツールを実行して不存在まで証明してはいない。これを誤りとは判定しない。
7. **将来や設計者の意図に関する断定**: Goチームの姿勢や、OBIがある方式を選んだ「理由」は、issue・実装・設計文書で裏付けられる範囲を確認した。公開資料に明記されていない個々の設計者の動機まで確定したものではない。

一時ディレクトリには再現コード、取得した一次ソース、実行ログを残した。これらは再検査用の作業ファイルであり、リポジトリ内の納品物はこのレポートだけである。

## 作業後の確認

原稿、`config.yaml`、表紙、対象のDOT、参照PNGの計134ファイルを、開始時のSHA-256と照合し、変更がないことを確認した。検証用Composeプロジェクトのコンテナとネットワークは停止・削除した。Git操作は行っていない。
