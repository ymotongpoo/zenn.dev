# go-ebpf-primer 技術検証（2エージェント統合）

検証日: 2026-09-09
対象: `books/go-ebpf-primer/` 全16ファイル（2,739行）
検証者: Claude Code (claude-opus-5, effort high) / Codex (gpt-6-astra, reasoning high)
照合対象: OBI v0.13.0 (3cc1986)、cilium/ebpf v0.22.0、go-offsets-tracker v0.1.7、otelc v1.1.0、Go 1.26.0 linux/amd64、Linux 7.0.0-31
個別レポート: `/tmp/verify-claude.md`、`/tmp/verify-codex.md`

指摘総数 32件（重複統合後）。文章表現・構成・誤字は検証対象外。

---

## A. 両エージェントが独立に一致した指摘（最優先・確信度最高）

### A1. 【重大】オフセット表の「載っていないバージョン」の挙動が逆
`60-for_go_developers.md:41`「表に載っていないバージョンのライブラリを使っていれば、その項目の計装は静かに欠けます」

`Field.GetOffset` は新しい記録から降順に走査し `since <= 対象バージョン` の最初の記録を返す。`versions.newest` を上限として拒否しない。したがって表より新しいライブラリでは **古いオフセットが静かに返り、それらしく動いてしまう**。欠落するのは対象版が全記録より古い場合か、そのフィールドが追跡対象でない場合のみ。

同章図1のキャプション（「表に載っていないバージョンでも検索は拒否されず、そのバージョン以下で最新の記録が返る」）および12章図3のキャプションが正しく、**本文と自己矛盾している**。12章が繰り返す「最悪なのはクラッシュせずにそれらしく動くこと」がまさにこのケースなので、危険の方向を逆に伝えている。

根拠: go-offsets-tracker v0.1.7 `pkg/offsets/schema.go` の `GetOffset`、OBI `pkg/internal/goexec/structmembers.go:949`。`target > newest` を明示的に拒否するのは `prefetchedGoRuntimeGCGoalOffset` だけ。

### A2. 【重大】「関数レベルの計装を持つのはGoだけ」が v0.13.0 の実装と不一致
`00-introduction.md:19`、`25-go_runtime.md:13`、`35-obi.md:42/45/70`

他言語にも専用フックがある。Ruby は `rb_obj_call_init_kw`/`rb_ary_shift`、Python は `_asyncio` の `task_step` と CPython GC 完了点、Node.js は async-hooks＋`uv_fs_access` サイドチャネル、Java は `libjvm.so` の HotSpot USDT、nginx (>= 1.27.3)、`libcuda` uprobe。「他の言語は通信バイト列をプロトコルとして解釈する汎用経路で扱われる」も広すぎる。

ただし `35-obi.md:42` の「**ライブラリ**レベルの関数計装を持つのはGoだけ」という限定は `SUPPORT_MATRIX.md` の "Go Library Instrumentation" 表と正確に一致しており問題ない。1章・6章の言い方だけが過剰。Go固有の4難所を論じる本書の構成自体は妥当。

根拠: OBI v0.13.0 `bpf/generictracer/{ruby,python,nodejs}.c`、`SUPPORT_MATRIX.md` の Runtime / Context Propagation Frameworks。

### A3. `-gcflags=-m` の出力例が掲載コードと対応しない
`20-function_call.md:116-119`

直前の `main.go` には `//go:noinline` が付いており、`go build -gcflags=-m main.go` では `can inline double` / `inlining call to double` は出ない（`-m -m` で `cannot inline double: marked go:noinline` が出る）。加えて行番号が「pragma 有りの配置」（6行目/11行目）なのに内容が「pragma 無しの結果」になっている。pragma を外すと `double` は5行目、呼び出しは10行目。実際の出力には `inlining call to fmt.Println` 等も混ざる。

このコマンド例の前に pragma を外す手順を明示するか、行番号を pragma 無しの配置に合わせるかのどちらか。4章の `objdump` 出力の行番号（`main.go:7`/`main.go:11`）は pragma 有りで正しい。

### A4. regabi 移行アーキテクチャの記述が過大
`45-hurdle2_abi.md:29`「arm64を含む他のアーキテクチャは、Go 1.18で切り替わりました」

Go 1.18 は arm64・ppc64・ppc64le。riscv64 は Go 1.19、loong64・s390x はさらに後。386 は対象外。go1.26 の `abi-internal.md` は amd64/arm64/loong64/ppc64/riscv64/s390x の6アーキテクチャを規定。amd64 前提の本書なら arm64 の時期だけ明示すれば足りる。

### A5. 【要確認】OBI の "beta 到達" の出典
`35-obi.md:9`「2026年3月のKubeCon EUでbetaに到達し」

日付自体は正しい（v0.1.0 = 2025-10-30、KubeCon EU 2026 = 3月）。ただし beta は Splunk のベンダー発表（2026-03-20/23）由来で、上流 v0.13.0 の `README.md`/`VERSIONING.md` は「OBI is currently in **Development**」「v0 の minor 間の破壊的変更を許す」としている。alpha/beta という段階呼称は OBI 自身のドキュメントに存在しない。ベンダーの提供段階と上流の安定性契約を区別して出典を付ける必要がある。

### A6. アドレスが実行ごとに変わる理由の因果
`10-os_kernel.md:47/53`、`99-glossary_references.md:32`

- `:47`「2つの実行でアドレスが違ったのも、それぞれが自分専用の空間を持っているから」→ 独立した仮想アドレス空間があることから値が異なることは導けない。別プロセスは同じ仮想アドレスを使える。
- `:53`「ASLRが……本書の実験でアドレスの値が毎回変わるのは主にこのため」→ **主因ではない**。Go 1.26 は `GOEXPERIMENT=randomizedheapbase64` が既定ON で、ランタイム自身がヒープのベースアドレスを起動ごとに乱択する。goroutine スタックも `stackalloc`（Goヒープ）由来。

検証（Hermes 側で再現）: `setarch -R`（カーネルASLR無効）でも値が毎回変わる。
```
0x35eb33f7e088 / 0x8a27259c008 / 0x23a89c372088
```
根拠: `internal/buildcfg/exp.go:87 RandomizedHeapBase64: true`、`runtime/malloc.go:353-355, 568-618`、`runtime/proc.go` の `malg`。

「ASLRという機構がある」自体は正しいので、因果の断定だけを直せばよい。

---

## B. Claude のみが検出（Hermes 側で追検証済み／根拠強）

### B1. 【重大】W3C仕様に「traceparent が2つあれば両方を捨てる」という規定は存在しない
`55-hurdle4_propagation.md:351`

Trace Context Level 1 (REC)・Level 2・editor's draft を全文検索しても、`traceparent` が複数現れた場合の受信側の義務は規定されていない。複数値の結合を規定しているのは `tracestate` のみ（"multiple tracestate headers … MUST be combined per RFC7230"）。

実務上は HTTP のフィールド値結合で `traceparent: A,B` となり ABNF に合わないため、§3.2.4 の versioning ルールで受信側は **トレースを restart する**（新しい trace-id を振る）。結論（トレースが切れる）は原稿どおりだが、根拠の帰属が誤り。「結合された値がパースできず受信側がトレースを作り直す」に寄せると正確。

### B2. 【重大】`MaxPathSegmentCardinality`（既定10）は heuristic の挙動ではない
`37-handson.md:310`「デフォルトのヒューリスティックは、サービスごとに同じ位置のセグメントの種類が10を超えると、そこをワイルドカードに置き換えます」

`MaxPathSegmentCardinality: 10` が効くのは `unmatched: low-cardinality` を明示したときだけ。既定の `heuristic` は各パスセグメントを n-gram (gibberish) 分類器にかけてID的な文字列を判定・置換する仕組み。

根拠: `pkg/transform/routes.go:24-38, 76`、`pkg/appolly/app/svc/svc.go:248-259`（`config.Unmatch != services.UnmatchLowCardinality` なら `nil` を返す）、`pkg/obi/config.go:318`、`pkg/internal/transform/route/clusterurl/cluster.go:17-24`。

### B3. 静的リンクの記述が本書の主題（`net/http`）で成り立たない
`15-source_to_binary.md:77`「Goのリンカはデフォルトで静的リンクを選びます」／`25-go_runtime.md:9`「`ldd` にかけても `not a dynamic executable` と返ってきます」

Cツールチェーンがある Linux で `go build` すると `net`（および `os/user`）が既定で cgo リゾルバを使うため**動的リンク**になる。検証（Hermes 側、go1.26.0、`CC=x86_64-linux-gnu-gcc`）:
```
$ go build -o app m.go && file app
app: ELF 64-bit ... dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2
$ CGO_ENABLED=0 go build -o app0 m.go && ldd app0
        not a dynamic executable
```
`net` を import しない4章の `demo` は `not a dynamic executable`。9章の Dockerfile は正しく `CGO_ENABLED=0` を付けているので9章とは矛盾しない。6章の本質（Goコードは全部1ファイル内にあり `/proc/<PID>/exe` の解析で足りる）は動的リンクでも崩れないので、`ldd` の一文に条件を付けるだけでよい。

### B4. amd64 の `RSP` は汎用レジスタ16本のうちの1本
`05-computer.md:72-74`「計算に使う汎用レジスタは16本」「ほかに特別な役割のレジスタが2つあります。ひとつはPC、もうひとつは `SP`」

RSP は16本（RAX, RCX, RDX, RBX, RSP, RBP, RSI, RDI, R8–R15）に含まれる。16本の外なのは `RIP` だけ。

### B5. Linux 6.13 の private stack は条件付き
`55-hurdle4_propagation.md:81`「Linux 6.13以降はこの種のプログラムをCPUごとの専用スタックで走らせるため」

原典 `bpf/common/preempt_guard.h` は「kprobe-type program **with at least 64 bytes of stack**」（verifier の PRIV_STACK_ADAPTIVE モード、opt-out 不可、commit a76ab5731e32）と条件を付けている。同ヘッダは kfunc `bpf_preempt_disable/enable` が 6.10 以降で、それ以前ではガードが消えることも書いている。

### B6. `in queue` / `processing` の生成条件
`37-handson.md:250`「サーバースパンごとにOBIが作る」

実装条件は `hasSubSpans := t.Start.After(spanStartTime(t))`（キュー時間が測れたとき）。Go のサーバースパンでは実質常に真なので結果は同じだが、規則としては不正確。根拠: `pkg/export/otel/tracesgen/tracesgen.go:199, 208-209, 315-340`。

### B7. otelc の説明と直後の実演が食い違う
`65-conclusion.md:49`「対応ライブラリを呼んでいる箇所を見つけ、その呼び出しに計装コードを注入して」

直後に自分で示している実物は `net/http` の `(*Transport).RoundTrip` **本体**の先頭に before トランポリン、`defer` で after トランポリンを入れる書き換え。「呼び出し側の呼び出し箇所」ではなくライブラリ側の関数本体。

### B8. `-work` が二重に渡る
`65-conclusion.md:190`「`$ ../../../../otelc go build -work -o client .`」

`otelc` は内部で必ず `-work` を付ける（`tool/internal/setup/setup.go` の `buildWithToolexec`）。Go の flag パーサは同名 bool フラグの反復を許すので動作はするが、本文 `65-conclusion.md:76`「内部で `-work` フラグを付けているため」と手順が食い違って見える。

### B9. `go tool nm` の出力は2行
`60-for_go_developers.md:30-31`

```
$ go tool nm app_stripped
reading app_stripped: no symbol section
reading app_stripped: no symbols
```

---

## C. Codex のみが検出（Hermes 側で追検証済み／根拠強）

### C1. 【重大・実害あり】`UprobeOptions.Address` は ELF 仮想アドレスではなくファイル内オフセット
`30-ebpf.md:84`「`Address: 0x49e290, // バイナリ中の命令アドレス`」

cilium/ebpf v0.22.0 の `Executable.address()` は `address > 0` ならそのまま返し、**シンボル解決経路と同じ VA→ファイルオフセット変換を一切通さない**。シンボル経由の場合は `address = s.Value - prog.Vaddr + prog.Off` を適用しているのに、明示 `Address` はこの変換を経ないので、`go tool objdump` の VA をそのまま渡すと目的の RET には置かれない。`40-hurdle1_uretprobe.md` の「アドレス直指定」の説明にもこの区別が必要。

正しくは `fileOffset = instructionVA - p_vaddr + p_offset`。検証（Hermes 側、`CGO_ENABLED=0` の非PIE Goバイナリ）:
```
$ readelf -lW app0 | grep LOAD
LOAD 0x000000 0x0000000000400000 ... R E
```
→ 実行セグメントは `p_vaddr=0x400000`, `p_offset=0` なので `0x49e290` は `0x9e290`。ただし**一般解として 0x400000 を固定減算してはいけない**（PIE、セグメント配置が異なる場合に破綻する）。OBI は `pkg/internal/goexec/instructions.go` の `findFuncOffset` でこの変換を実装済み。

根拠: cilium/ebpf v0.22.0 `link/uprobe.go:136-167`（シンボル経路の変換）と `:196-199`（明示 Address の素通し）。

### C2. 【重大】フィールド名とオフセットは DWARF にだけ残るわけではない
`15-source_to_binary.md:134`「フィールド名とオフセットの対応はDWARFにだけ残っていて、`-s -w` で消せる」（`05-computer.md:161/177` の「フィールド名は消える」も同様）

reflection 用の型メタデータ（`internal/abi.StructField` の Name/Typ/Offset）にフィールド名とオフセットが残り、これは `-s -w` では削除できない実行時情報。検証（Hermes 側で再現）:
```
$ go build -ldflags="-s -w" -o r r.go && ./r
Method=0 URL=16 Header=56 ContentLength=88
$ readelf -S r | grep -c debug_   # 0
$ readelf -S r | grep -c symtab   # 0
```
「OBI のこの解決処理が DWARF を優先する」と「名前と位置は DWARF にしかない」は別の主張。構造体の値インスタンス内に名前がない、という限定なら正しい。

### C3. 【重大】「実行に要るのは `.text` だけ」は誤り
`15-source_to_binary.md:89`

`.rodata`（定数・文字列）、`.data`/`.bss`（グローバル変数）、`.gopclntab`（PCテーブル）、Goの型情報はいずれも実行時に使われる。`.text` だけでは通常のGoプログラムは動かない。ローダーが配置する単位は PT_LOAD セグメント。

### C4. 【重大】`RDI` = 第4引数はスカラー限定
`45-hurdle2_abi.md:25`「Goが `RDI` に入れているのは第4引数です」

regabi は受信者を含む各引数を基本成分へ分解してレジスタに割り当てる。string と interface は2成分、slice は3成分、収まらない値はスタックへ回る。`F(a string, b, c int)` では RDI は第3引数 `c`。`GO_PARAMn` も一般には「第n引数」ではない（OBI 自身も `ServeHTTP` の Request を `GO_PARAM4` で読む=receiver+ResponseWriter の2ワードの後）。整数スカラーだけの例に限れば原稿どおり。

### C5. 【重大】RET を通らない出口は未回復 panic だけではない
`40-hurdle1_uretprobe.md:129`「この方式でも取れない出口が1つだけあります。`recover` されないパニックで終わる場合です」

- 呼び出し元の defer で recover された場合でも、巻き戻しで飛ばされた内側の関数は RET を実行しない。recover 後に RET 経路へ戻るのは recover を実行した defer を登録した関数だけ。
- `runtime.Goexit`、`os.Exit` も同様。
- 同段落の「goroutine ごと終わる」も、未回復 panic では**プログラム全体が終了する**点で誤り。

HTTP サーバーは `conn.serve` の外側で recover するので、この区別は本書の主題に直接関わる。

### C6. 【重大】eBPF のループ制約が現代の実装より強い
`30-ebpf.md:17`「ループは回数の上界がコンパイル時に決まる形でしか書けません」／`55-hurdle4_propagation.md:236`「上界がありさえすれば検証器は通る」

`bpf_loop`（ユーザー空間が実行時に `nr_loops` を設定）や open-coded iterator（next が最終的に NULL を返す契約）がある。逆に有限ループでも状態探索の複雑さやメモリ安全性で拒否されうるので、「上界があれば通る」は十分条件ではない。親ポインタ探索を6回で打ち切る実装上の説明は正しいが、eBPF 全体へ一般化しない。

### C7. ABIInternal の導入時期と regabi 導入時期の混同
`60-for_go_developers.md:9`、`45-hurdle2_abi.md:17`、`99-glossary_references.md`

ABIInternal/ABI0 の区別は Go 1.12 時点で既に存在した。Go 1.17 は **amd64 の ABIInternal に regabi を導入した版**。ABI0 はアセンブリ向けの安定したスタック規約として残り、ABI wrapper を介して相互呼び出しする。「ABIInternal に切り替わったバージョンが境目」という書き方は誤解を招く。

### C8. goroutine 伝搬の最低バージョンは 1.18+
`60-for_go_developers.md:9`

一般の Go ライブラリ計装は 1.17+ で正しいが、`SUPPORT_MATRIX.md` が goroutine 伝搬に宣言しているのは **1.18+**。Go 1.17 の `newproc1` では `callergp` が第4引数であり、55章の `GO_PARAM2` による解読と一致しない。機能別最低版の補足が必要。

### C9. OTel SDK は Transport 差し替えだけでは traceparent を付けない
`55-hurdle4_propagation.md:11`

グローバル Propagator は SDK 導入だけでは TraceContext にならない。`otel.SetTextMapPropagator(propagation.TraceContext{})` または `otelhttp.WithPropagators` が必要。「SDK の TracerProvider と TraceContext propagator を設定済みなら」と条件を加える。Codex 側で有効な SpanContext を持たせた実験でも、default では空、TraceContext 設定後に55文字の値が入ることを確認。

### C10. 「直列化される直前」は逆
`55-hurdle4_propagation.md:249`（図5・章末も同じ対象）

本文後半のコードは `writeSubset` の**戻り**で、すでにバイト列になったヘッダへ追記している。正しくは「ヘッダの直列化後、終端の空行が書かれる前に、`bufio.Writer` の送信バッファへ追記する」。この時点までに一部データが flush される場合もあるので「リクエスト全体が未送信」という保証とも分ける。

### C11. TCP option 伝搬は HTTP/2・gRPC では使われない
`55-hurdle4_propagation.md:345`

v0.13.0 では HTTP/2/gRPC に TCP option を使わない。1接続で並行する複数 stream の文脈を接続単位の option で表せないため。generic TLS の HTTP/2 にはこの代替注入経路がない。根拠: `devdocs/grpc-context-propagation.md` の "Why not TCP options"。

### C12. 256バイトは普遍的な上限ではない
`50-hurdle3_offsets.md:9`「ソケットから拾えるのはリクエストの先頭256バイトだけ」

既定の固定長キャプチャ（`FULL_BUF_SIZE 256`）の話。v0.13.0 にはオプションの payload capture があり、HTTP/1 では generic tracer でも方向ごとに最大 256KiB を扱う。構造体を直接読む利点は残るので、既定値の話に限定すればよい。

### C13. `privileged: true` は OBI の必須条件ではない
`37-handson.md:177`「`privileged: true` と `pid: host` の2つは外せません」

このハンズオンで権限をまとめて与えるための選択。OBI には必要な capability を個別付与する構成があり、対象 PID 名前空間の共有方法も配置で異なる。根拠: OBI security/permissions ドキュメント、`SUPPORT_MATRIX.md` の Privileges。

### C14. Java を一律に固定OSスタックとするのは現在の実装に合わない
`00-introduction.md:17`「CやJavaのスレッドはこの前提を満たします」／`25-go_runtime.md:28`

JDK 21 で正式導入された仮想スレッドのスタックは GC ヒープの stack chunk として保持され、OSスレッドへ mount/unmount される。プラットフォームスレッドと仮想スレッドを区別する必要がある。根拠: OpenJDK JEP 444。

### C15. 「スタックには一度も触っていない」は RET を見落としている
`45-hurdle2_abi.md:68`

`Add3` はローカルフレームを確保せず引数・結果をレジスタだけで扱うが、amd64 の `RET` はスタックから戻りアドレスを読み SP を進める。

### C16. 「Goのアプリだけを相手にしているかぎり実害はありません」の一般化
`37-handson.md:345`

経路1（`bpf_probe_write_user`）が常に成功するとは限らない。`on_writeSubset_returns` にはバッファ容量、オフセット取得、書き込み可否の条件がある。経路1で注入できなければ sk_msg 無効化の影響が出る。「本章の2サービスでは経路1が成功した」と限定する。

---

## D. 両エージェントが検証して問題なかった主要な主張

Go 実測（go1.26.0 で再現）:
- 2章 `record` のオフセット 0/8/16・サイズ24、確認問題の `pair` 8/16
- 3章 `strace` の形と `512`/`502` の算術
- 4章 `main.double` = `ADDQ AX, AX` + `RET` の2命令、`go tool nm` の `T main.double`
- 5章 `CALL` 周辺の機械語と `e8c8ffffff` の rel32 = −56 が `main.double` 先頭に厳密一致
- 5章 `descend` フレーム176バイト、`[128]byte` で240バイト
- 10章 `main.Lookup` の逆アセンブル（`CMPQ SP, 0x10(R14)` / `JBE` / RET 2つ / `morestack_noctxt`）と掲載アドレスの相対関係
- 10章 `g.stackguard0` = オフセット16、`grow(3000)` で `moved = true`
- 11章 `main.Add3` の `-gcflags=-S` 出力が**完全一致**
- 12章 `http.Request` の 0/16/56/88、`streamV1`（16/24）/`streamV2`（24/32）とパディング説明
- 13章 `DumpRequestOut` の出力が一字一句一致
- 14章 `readelf -S | grep -c debug_` 8→0、`.symtab` 消失、`.gopclntab`/`.go.buildinfo` 残存
- 4章脚注「`-s` は `-w` を含意」= `cmd/link/internal/ld/main.go:272`
- 13章 `runtime.newproc1` のシグネチャ（第2引数が親、戻り値が子）
- 15章 flight recorder（Go 1.25）、goroutine leak profile（Go 1.26、既定OFF）、公開 `goid` API 不在
- **Go Playground 13リンク全部**が有効で内容が本文と一致

OBI v0.13.0 逐語照合（コミット 3cc1986）:
- `FindReturnOffsets` / `isENDBRXX` / `endbrSize = 4` / FIXME コメント
- `pkg/ebpf/instrumenter.go:861-882` の `probe.End`（エラー文言は uretprobe だが実体は通常 uprobe。実際の `link.Uretprobe` は CPython 用1箇所だけ）
- `GO_PARAM1..9`（ax, bx, cx, di, si, r8, r9, r10, r11）、`GOROUTINE_PTR`（x86: r14 / arm64: regs[28]）、浮動小数点レジスタ読取マクロは存在しない
- `go_addr_key_t{pid, addr}`、リポジトリ全体で `goid` が goroutine 識別子として1箇所も出てこない（`sched_goidle` のみヒット）
- `offsets.json` に `runtime.g` エントリなし
- `obi_uprobe_runtime_newproc1` / `_return`（循環回避、マップ削除まで）
- `find_parent_goroutine` の `while (attempts < 6)`（自身＋親5世代＝6回）、見つからなければ `urand_bytes` で新 trace ID
- `go_nethttp.c:1075-1095` のヘッダ注入（`"Traceparent: "`、`(len & 0x0ffff)`、4回目の `bpf_probe_write_user` で `n` 更新）
- `structMemberOffsets` の DWARF 優先ロジック、`//go:embed offsets.json`、`TestPrefetchedOffsetsPreserveResolvedOffsets`
- `GoOffset` の `iota + 1` 定数列と `go_offsets.h` の `_conn_fd_pos = 1`。**両側を突き合わせるテストは存在しない**（原稿の主張どおり）
- `offsets.json` 統計: 89構造体・154フィールド・うち43が変化 —— 原稿と**完全一致**。`runtime.*` は43件中20件
- gRPC `transport.Stream.method` = 80@1.40.0 / 88@1.66.0 / 24@1.69.0 / 16@1.77.0 —— 表と完全一致
- `x/net/http2.ClientConn.fr` = 8区間（304→296→304→328→336→360→352→368）、1回は以前の位置に戻る —— 原稿どおり
- FIONREAD の WARN/ERROR ログが逐語一致。無効化されるのは tpinjector（経路2）だけで gotracer（経路1）は生き続ける —— 9章の解釈は正しい
- v0.13.0 の tpinjector 修正3件（#3257 / #3298 / #3304）の番号・内容・マージ時期
- 環境変数の型と既定値（`OTEL_EBPF_AUTO_TARGET_EXE` の glob 挙動、`TRACE_PRINTER` 既定 disabled、`METRICS_INTERVAL` 60s、`BPF_CONTEXT_PROPAGATION` = disabled/headers/tcp/all で Beyla 時代の `ip` から変更済み）
- リポジトリ構成表・巻末引用ファイル一覧9件すべて実在、外部URL全て HTTP 200

ハンズオン章（Codex が原稿からコードを抽出して実際に Compose 起動）:
- frontend/backend、go.mod、Dockerfile、compose.yaml がそのまま動作
- グロブ、`OTEL_SERVICE_NAME`、OTLP gRPC、TRACE_PRINTER、15秒メトリクス周期すべて機能
- 伝搬 disabled で受信ヘッダ空でも共通 trace ID を持つ7スパンが Tempo に入り、`all` で受信ヘッダが非空になる
- 掲載 PromQL が 200・500・502 の4系列を返す、サービスグラフ user→frontend→backend
- **Compose の基本動作を妨げるコード誤りは見つからなかった**
- otelc v1.1.0 の `make build` と `otelc go build -work` が成功、WORK 配下の `roundtrip.go` で before/after hook 挿入を確認

カーネル/eBPF・年表:
- uprobe の `int3` 置換と XOL、uretprobe のトランポリン（`0x7fffffffe000`、issue #27077 のダンプに `!00007fffffffe000` として実在）、arm64 の x30/LR 書き換え
- Linux 6.11 の uretprobe syscall 高速化、`bpf_probe_write_user` の lockdown/`CAP_SYS_ADMIN` 制約
- golang/go#22008（2017-09-25、open、milestone Unplanned）、#27077（go1.10.3、bcc funclatency で再現、掲載トレース行が issue 本文に実在）、#73798（2025-05-20 not planned）
- Beyla 寄贈発表 2025-05-07、OBI v0.1.0 = 2025-10-30、v0.13.0 = 2026-09-04
- otelc: リポジトリ作成 2025-01-13、v1.0.0/v1.0.1 = 2026-07-14、v1.1.0 = 2026-08-24、`retract v1.0.0` の理由が逐語で残存

---

## E. 両者共通の判断保留

- **Go 1.26.5 固有の挙動**: 両者とも手元は go1.26.0。ただし 1.26.5 の出力として掲げた値（`http.Request` の 0/16/56/88、`descend` の176バイト、`Add3` のアセンブリ、RET 2つ等）はすべて 1.26.0 で一致したのでパッチ差の影響はないと見られる。
- **カーネルコミット `929e30f93125` とバックポート範囲**（6.6.128+/6.12.75+/6.18.14+/6.19+）: OBI のソース文字列との一字一句一致は確認したが、カーネルツリー側は未確認。
- **14章のバイナリサイズ**（5,444,719 / 3,748,002）: Claude の環境では 8,420,920 / 3,748,002 相当のプログラムで 8,420,920 / 5,824,777。比（0.69）はほぼ同じなので測り方は妥当だが、数値そのものは再現しない。主張自体は成立。
- **図版の内容**: 画像ファイルがリポジトリに存在しないためキャプションのみ検証。ただし Codex は Grafana API 経由で対応する実データを確認済み。
- **sk_msg 経路単独・TLS・HTTP/2・遠隔ホスト間の注入成功**: 今回のカーネルでは原稿どおり FIONREAD 補償失敗で無効化。経路1の受信成功は確認済み。
- **arm64 実機、Linux 5.8/5.10/6.11/6.13、lockdown 有効時**: 未検証。
- **不在の証明**（`goid` 利用、C/Go 定数列の整合性テスト）: 関連名で検索して見つからなかったが、間接的な検査の不在は証明できない。
- **`golang.org/x/arch v0.30.0`** の実在性（`50-hurdle3_offsets.md:247` の `go version -m` 出力例）。
