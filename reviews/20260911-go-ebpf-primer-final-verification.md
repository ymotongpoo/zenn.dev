# 最終技術検証

検証日：2026-09-10〜11 UTC。検証対象のコミットは `1618c23`。最初に前回レポート `reviews/20260909-go-ebpf-primer-technical-verification.md` を読み、修正後の `books/go-ebpf-primer/*.md` **全16ファイル、2,741行、120,290文字**を通読しました。`config.yaml` の章順、修正コミット、図のキャプションも照合しています。文字数はUTF-8のバイト数ではなく文字数です。

検証環境はLinux `7.0.0-31-generic`、x86_64。既定のGoは1.26.0ですが、今回の実測には `GOTOOLCHAIN=go1.26.5` を使いました。照合対象はOBI v0.13.0（`3cc19862cef1abdaaeaa2a6387b462d31822010e`）、cilium/ebpf v0.22.0、go-offsets-tracker v0.1.7、OTel Go v1.46.0、otelc v1.1.0です。歴史的な主張にはGo 1.12、OpenJDK 21、Linuxの該当タグとstable変更履歴も使いました。

**判定：公開前修正12件、任意の補足4件、計16件です。** クラッシュや通信破壊を直接引き起こす掲載コードの誤りは今回新たには確認されませんでした。ただし、重複ヘッダの扱い、復帰経路、図中のスタック位置、修正漏れを含む下記の「公開前修正」は直すべきです。「任意」は公開を止める理由にはしません。異なる節で同じ問題を再掲する場合はIDを参照し、重複計上していません。

前回「問題なし」の項目は原則として再検証せず、変更箇所と判断保留に集中しました。9章のコードブロックは修正前後で一致したため、前回成功済みのCompose一式は再起動していません。Go 1.26.5固有の保留を解くため、ハンズオン以外の実行可能なGoサンプル13個は今回実行しました。

外部参照は、前回確認済みのPlayground 13件、説明用のローカルURL、clone用URLを除く43個の異なるURLをHTTP GETで確認しました。日本語版候補も別途確認しています。画像参照59件はすべて実在し、うち修正関連を中心とするPNG 8枚を表示して確認しました。全画像の内容を検証済みとはしていません。

原稿、`config.yaml`、図版は編集していません。実験用コードと取得した一次資料は `/tmp/go-ebpf-final-20260911/` に保存しました。行番号は今回読んだ原稿のものです。

## 公開前に直すべき誤り（重大）

今回の確認範囲で、掲載コードが対象アプリのクラッシュや通信破壊を直接起こす重大な誤りの追加指摘はありません。これは本書全体の動作保証ではありません。説明の正確性については、次節以降の12件が公開前修正対象です。

## 修正の副作用として入り込んだ問題

### S01：traceparentの重複が必ず結合・無効化されるという新しい説明も誤り

- **公開前修正。** [`55-hurdle4_propagation.md:351`]「同じ名前のヘッダが2つあると、受信側ではHTTPの規則に従って `traceparent: A,B` という1つの値に結合され」「二重注入は『余分』ではなく『破壊』です」。前回B1への対応（`1540294`）で入った説明です。
- **誤りと正しい挙動：** RFC 9110 §5.3の結合は許容であり、必須ではありません。そもそも送信側が同名フィールドを複数行生成できる条件もあります。Go 1.26.5の `http.ReadRequest` は2行を `[]string` の2要素として保持し、`Header.Get` は最初の値を返します。OTel Go v1.46.0のTraceContext propagatorはその `Get` を使うため、2行があるだけでは無効化されません。結合されたversion 00の値を渡すと無効になる、という条件付きの説明は正しいです。
- **実測：** 有効な異なる値A/Bを持つHTTP/1.1リクエストを読み、`propagation.TraceContext{}.Extract` に渡すと、`Values` は2要素、`Get` はA、抽出結果は `valid=true` でAのtrace IDになりました。手動で `A,B` に結合した場合は `valid=false` でした。
- **修正案：** 「重複すると、受信実装によって最初の値の採用や無効化が起き、意図した文脈が伝わる保証がなくなる。たとえばカンマで結合されたversion 00の値は形式不正となる。そのためOBIは二重注入を避ける」とします。二重注入を避ける設計の説明自体は残せます。前回レポートの修正文案も『結合される場合』という条件を落としていたため、そのまま採用しないでください。
- **根拠：** [RFC 9110 §5.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-5.3)、[W3C Trace Context](https://www.w3.org/TR/trace-context/#traceparent-header)、[GoのHeader.Get](https://github.com/golang/go/blob/go1.26.5/src/net/http/header.go#L43-L51)、[OTel GoのHeaderCarrier.Get](https://github.com/open-telemetry/opentelemetry-go/blob/v1.46.0/propagation/propagation.go#L80-L83)、[TraceContext.extract](https://github.com/open-telemetry/opentelemetry-go/blob/v1.46.0/propagation/trace_context.go#L80-L112)。再現コードは `/tmp/go-ebpf-final-20260911/duplicate/main.go`。
- **確信度：高。**

### S02：オフセット検索の「欠けるのはこの2場合だけ」は例外を落としている

- **任意の補足。** [`60-for_go_developers.md:42`]「項目が解決できずに欠けるのは、そのバージョンが最初の記録より古い場合か、フィールドがそもそも追跡の対象でない場合です」。前回A1への対応（`4f1e517`）で追加された限定です。
- **正しい範囲：** 通常の `Field.GetOffset` が、表より新しい版に最後の値を返す説明は正しく直っています。ただしOBIには `runtime.gcControllerState.heapGoal` の専用処理があり、`versions.newest` を超えると意図的に解決を拒否します。一般のフィールド検索とOBI全体を区別すれば正確です。
- **修正案：** 最後の文を「通常の表検索で項目が見つからないのは……」と限定し、必要ならheapGoalの例外を脚注にします。本書のHTTP/gRPCフィールドについて述べる中心的な結論は変更不要です。
- **根拠：** [go-offsets-tracker v0.1.7 schema.go](https://github.com/grafana/go-offsets-tracker/blob/v0.1.7/pkg/offsets/schema.go)、[OBIの通常検索と例外](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/internal/goexec/structmembers.go#L950-L986)。前回A1もこの例外を挙げていました。
- **確信度：高。**

## 章をまたいだ不整合・前方参照のズレ

`config.yaml` の章順は次のとおりです。ファイル名の数字は章番号ではありません。

| 章 | ファイル | 章 | ファイル |
|---|---|---|---|
| 1 | `00-introduction.md` | 9 | `37-handson.md` |
| 2 | `05-computer.md` | 10 | `40-hurdle1_uretprobe.md` |
| 3 | `10-os_kernel.md` | 11 | `45-hurdle2_abi.md` |
| 4 | `15-source_to_binary.md` | 12 | `50-hurdle3_offsets.md` |
| 5 | `20-function_call.md` | 13 | `55-hurdle4_propagation.md` |
| 6 | `25-go_runtime.md` | 14 | `60-for_go_developers.md` |
| 7 | `30-ebpf.md` | 15 | `65-conclusion.md` |
| 8 | `35-obi.md` | 16 | `99-glossary_references.md` |

### C01：ファイル内オフセットへの変換を扱う参照先は12章ではなく10章

- **公開前修正。** [`30-ebpf.md:88`]「OBIがこの変換をどこで行っているかは12章で見ます」。前回C1への修正（`bccc412`）で入った参照です。
- **誤り／修正案：** 12章は構造体フィールドのオフセットを扱い、`instructionVA - p_vaddr + p_offset` の変換実装を説明していません。実際に `instructions.go` の変換を説明するのは10章245行なので「10章」に直します。ファイル内オフセットと構造体フィールドオフセットを混同させる参照になっています。
- **根拠：** `config.yaml:chapters`、`40-hurdle1_uretprobe.md:245`、`50-hurdle3_offsets.md` 全文、[OBI findFuncOffset](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/internal/goexec/instructions.go#L216-L249)。
- **確信度：高。**

### C02：最終まとめ表にABIInternalの導入時期の修正漏れ

- **公開前修正。** [`65-conclusion.md:208`]「ABIInternal（引数の受け渡し規約、Go 1.17〜）」は、修正済みの11章17行と付録63行の「名前はGo 1.12から」と食い違います。前回C7への修正漏れです。
- **修正案：** 「amd64のレジスタABI（Go 1.17〜）」にします。11章図1（`20260911-abi-shift.png`）も右側だけを「Go 1.17以降（ABIInternal）」とラベル付けしているため、「Go 1.17以降（レジスタ渡し）」にすると同じ誤解を避けられます。Go 1.16以前のABIInternalも存在します。
- **根拠：** [Go 1.12のABI0/ABIInternal定義](https://github.com/golang/go/blob/go1.12/src/cmd/internal/obj/link.go#L433-L451)、[Go 1.17リリースノート](https://go.dev/doc/go1.17#compiler)、`45-hurdle2_abi.md:17`、`99-glossary_references.md:63-64`。
- **確信度：高。**

### C03：ヘッダ注入の図のキャプションだけ「直列化の直前」が残存

- **公開前修正。** [`55-hurdle4_propagation.md:279`]「直列化の直前にある `bufio.Writer` のバッファへ `Traceparent` を書き」。前回C10への修正は249行と355行には反映されていますが、このキャプションには残っていません。
- **修正案：** 「ヘッダの直列化後、終端の空行が書かれる前に、`bufio.Writer` のバッファへ……」とします。PNGの表示は `writeSubset` → `bufio.Writer` の順で、今回は画像の経路自体に逆転は見つかりませんでした。
- **根拠：** 同章249、276、285、355行、[Go Request.write](https://github.com/golang/go/blob/go1.26.5/src/net/http/request.go#L715-L727)、[OBI writeSubsetの戻り処理](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/bpf/gotracer/go_nethttp.c)。
- **確信度：高。**

### C04：静的リンクの条件が図のキャプションから落ちている

- **公開前修正。** [`15-source_to_binary.md:80`]「Cのプロセスは実行時に共有ライブラリへの依存を解決するが、Goのバイナリはその段を持たない」。直前77行と6章9行は、Linuxの `net/http` がcgo経由で動的リンクになりうる、と修正されています。前回B3の修正漏れです。
- **修正案：** 「この図のGo側は `CGO_ENABLED=0` でビルドした場合を示す」と条件を加えます。図のGoノードにもこの条件を付ければ、図だけを見た読者にも通じます。Goコードが1ファイルに入るという本論は変更不要です。
- **根拠：** `15-source_to_binary.md:77`、`25-go_runtime.md:9`、[Go netパッケージの名前解決とビルド条件](https://pkg.go.dev/net#hdr-Name_Resolution)。今回のGo 1.26.5による `net/http` を含む通常ビルドでも `.interp`、`.dynsym` が存在しました。
- **確信度：高。**

### C05：ABIの比較図でSPの基準時点が8バイトずれている

- **公開前修正。** [`45-hurdle2_abi.md:31` の図1] 左表の「`SP+0` 引数a」「`SP+8` 引数b」「`SP+16` 引数c」。同じ入口での観測を説明する5章図3とキャプション107行では、正しく「`SP+0` 戻りアドレス」「`SP+8` a」「`SP+16` b」「`SP+24` c」になっています。
- **誤り／修正案：** 前者の配置は呼び出し元のCALL直前のSPなら成立します。しかし11章15行は関数入口のSPから読む説明であり、図にも時点の切り替えがありません。関数入口に統一して戻りアドレスの行を加え、a/b/cを8/16/24に直すべきです。CALL前を示す意図なら、呼び出し元であることと入口ではSPが8バイト変わることを明記してください。
- **根拠：** `20-function_call.md:56,82,107`、画像 `20260911-convention-stack-vs-register.png` と `20260911-abi-shift.png` の現物。Go 1.26.5のABI0アセンブリ関数で `a+0(FP)`／`b+8(FP)`／`c+16(FP)` を使い、逆アセンブルするとそれぞれ `0x8(SP)`／`0x10(SP)`／`0x18(SP)` でした。[GoのアセンブリにおけるFP/SPの区別](https://go.dev/doc/asm#symbols)。再現コードは `/tmp/go-ebpf-final-20260911/abi0/`。
- **確信度：高。**

### C06：panic時に必ず2つ目のRETへ進むように読める説明が残存

- **公開前修正。** [`40-hurdle1_uretprobe.md:186`]「したがって `0x49e290` にしかuprobeを置かないと、パニックが起きた呼び出しだけ出口を取れません」。129行では、外側でrecoverされた場合、飛ばされた内側の関数はRETを通らない、と正しく修正されています。前回C5の訂正と既存の例の結び付きに問題が残りました。
- **誤りと正しい条件：** 2つ目のRETで捕捉できるのは、計装対象関数自身が登録したdeferでrecoverされ、その関数の復帰経路に戻る場合です。掲載された `Lookup` のdeferは `mu.Unlock()` で、recoverを行いません。外側がrecoverしても `Lookup` の2つ目のRETには戻りません。また、ループ内のdeferを持つ別の関数では、通常終了も `deferreturn` を通りえます。「取り逃すのはエラー時に限られる」という一般化もできません。
- **修正案：** 「この出力には復帰用のRETも生成されている。一般に、その関数のdeferがpanicをrecoverする場合にはこちらを通るため、通常経路だけへの設置では足りない。ただしこの `Lookup` の `mu.Unlock` 自体はrecoverしない」と区別します。RETが2個あるという実測と、全RETに設置するOBIの説明は維持できます。
- **根拠：** 同章129、156-159、184-186行、[Goのpanic/recover仕様](https://go.dev/ref/spec#Handling_panics)、[Go 1.26.5 runtime.recovery](https://github.com/golang/go/blob/go1.26.5/src/runtime/panic.go#L1286-L1308)。今回も掲載 `Lookup` のRETが `0x49e290` と `0x49e2a0` にあることを確認しました。
- **確信度：高。**

### C07：「次の節」「後の節」が実際には次章を指す

- **任意の修正。** [`45-hurdle2_abi.md:150`]「この選び方が意味を持つのは、次の節との関係です」。説明しているのはフィールドオフセットへの追従ですが、直後の節は「動くスタックと、動かないg構造体」です。フィールドオフセットを本格的に扱うのは次章です。`40-hurdle1_uretprobe.md:188` の「後の節で扱う要素」も、R14の説明先は11章です。
- **修正案：** 前者は「次章のフィールドオフセットの問題との関係です」、後者は「ここまでの説明と次章に関係する要素」にします。
- **根拠：** `45-hurdle2_abi.md:155` の節見出し、`50-hurdle3_offsets.md:13`、`45-hurdle2_abi.md:118-131`。章番号全体がずれているわけではありません。
- **確信度：高。**

## リンクの問題

### L01：日本語版があるOBI文書・otelc紹介記事が英語版を指す

- **公開前修正（今回指定された日本語版優先の観点）。** 次の6箇所には、英語版へのリンクがあります。対応する日本語版はHTTP 200、最終URLも日本語パス、HTMLの `lang=ja` と日本語タイトルを確認しました。

| 原稿の箇所・引用 | 差し替え先 |
|---|---|
| `35-obi.md:34`「公式ドキュメント」 | [OBI日本語トップ](https://opentelemetry.io/ja/docs/zero-code/obi/) |
| `37-handson.md:177`「権限のドキュメント」 | [OBIのセキュリティ、権限、ケーパビリティ](https://opentelemetry.io/ja/docs/zero-code/obi/security/) |
| `37-handson.md:181`「設定リファレンス」 | [OBIグローバル設定プロパティ](https://opentelemetry.io/ja/docs/zero-code/obi/configure/options/) |
| `99-glossary_references.md:96`「OBI 公式ドキュメント」 | [OBI日本語トップ](https://opentelemetry.io/ja/docs/zero-code/obi/) |
| `99-glossary_references.md:97`「OBI 分散トレースのドキュメント」 | [OBIによる分散トレース](https://opentelemetry.io/ja/docs/zero-code/obi/distributed-traces/) |
| `99-glossary_references.md:125`「Announcing v1 of OpenTelemetry Go Compile-Time Instrumentation」 | [日本語版の同記事](https://opentelemetry.io/ja/blog/2026/go-compile-time-instrumentation-v1/) |

- **判断：** リンク切れや根拠違いではありません。日本語版も同じ主題を扱うため差し替えられます。43URLのHTTP確認ではリンク切れは0件でした。OTLP仕様とHTTPメトリクス仕様は、日本語パスが英語版へリダイレクトされました。そこは日本語版があると判断せず、英語版の利用を誤りにはしません。引用した上流コード中のURLも書き換え不要です。
- **根拠：** 表中の日本語版各ページ、HTTP応答と最終URLの記録 `/tmp/go-ebpf-final-20260911/http-results.json`。
- **確信度：高。**

## 軽微な誤り・不正確な表現

### T01：noinlineを外さないままインライン化の出力を示している

- **公開前修正。** [`20-function_call.md:116-118`] `go build -gcflags=-m main.go` に続く `can inline double`／`inlining call to double`。前回A3が未修正です。
- **実測と修正案：** 4章の `main.go` には `//go:noinline` があり、Go 1.26.5でもその2行は出ません。`fmt.Println` のインライン化等だけが出ます。この出力の前にpragmaを外す手順を置き、実際の出力に合わせます。行そのものを削除するなら `double` は5行目、呼び出しは10行目です。行番号を維持するならpragma行を空行にし、出力が抜粋であることも添えます。章末の確認問題に外す指示があっても、先に登場するこのコマンドの条件にはなりません。
- **根拠：** `15-source_to_binary.md:28-40`、[Goコンパイラのnoinline指示](https://pkg.go.dev/cmd/compile#hdr-Compiler_Directives)、実測 `/tmp/go-ebpf-final-20260911/noinline.txt`。
- **確信度：高。**

### T02：FIONREADのログにある「6.19+」は正確な導入版ではない

- **公開前修正。ただしログは変更せず注記を追加。** [`37-handson.md:341`]「`present in 6.6.128+, 6.12.75+, 6.18.14+ and 6.19+`」。これはOBI v0.13.0が出す実際のログですが、カーネルの版の説明としては6.19系列の下限が広すぎます。
- **正しくは：** upstreamコミット `929e30f9312514902133c45e51c79088421ab084` はLinux v6.19には含まれず、v7.0には含まれます。6.19系列へのバックポートは **6.19.4** です。6.19.1〜6.19.3の変更履歴に当該コミットはなく、6.19.4には `edc9eb0ec8048106d6ef472ecc556217e40850e2` として記録されています。他の3系列の下限は掲載どおりでした。
- **修正案：** 「ログの6.19+はOBI側の表記。upstream stableでは6.19.4以降に当該変更が入る。ディストリビューション独自のバックポートもあるため、実際の有効化はOBIの実行時検査に従う」と補足します。『この版以降では将来も必ず故障する』という意味には広げません。
- **根拠：** [upstreamコミット](https://github.com/torvalds/linux/commit/929e30f9312514902133c45e51c79088421ab084)、[v6.19との履歴比較](https://api.github.com/repos/torvalds/linux/compare/929e30f9312514902133c45e51c79088421ab084...v6.19)、[v7.0との履歴比較](https://api.github.com/repos/torvalds/linux/compare/929e30f9312514902133c45e51c79088421ab084...v7.0)、[ChangeLog-6.19.4](https://cdn.kernel.org/pub/linux/kernel/v6.x/ChangeLog-6.19.4)。前回Eの保留項目から今回確定した指摘です。
- **確信度：高。**

### T03：親子関係に循環があっても掲載の探索は無限ループしない

- **公開前修正。** [`55-hurdle4_propagation.md:172`]「放置すれば親子関係が輪になり、次の節で見る遡りが無限に回ります」。実装と同章の説明には `attempts < 6` という打ち切りがあります。
- **修正案：** 「同じ関係を繰り返し辿って6回の探索枠を使い切り、有効な祖先を見つけられなくなるおそれがある」とします。循環を避ける必要性は正しいですが、停止性の説明としては誤りです。
- **根拠：** 同章199-228行、[OBI find_parent_goroutine](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/bpf/gotracer/go_common.h)。
- **確信度：高。**

### T04：JavaのプラットフォームスレッドでもCの呼び出し規約にはならない

- **公開前修正。** [`00-introduction.md:17`]「スタックがOSに管理されて動かないこと、呼び出し規約がプラットフォームの標準に従うことを前提にしています。Cのスレッドや、Javaのプラットフォームスレッドはこの前提を満たします」。前回C14に対応して仮想スレッドを除外しましたが、呼び出し規約まで含めるとまだ誤りです。
- **正しくは／修正案：** HotSpotのコンパイル済みJavaコードはJava用の呼び出し規約を使います。OpenJDK 21のLinux/amd64では、整数引数レジスタはC側の `rdi,rsi,rdx,rcx,r8,r9` に対し、Java側は `rsi,rdx,rcx,r8,r9,rdi` です。OSスレッドの種類を限定してもこの違いは消えません。「Javaのプラットフォームスレッドは、OSスレッドのスタックを使う点では前者を満たす」と分けるか、2条件を満たす例はCだけにします。
- **根拠：** [OpenJDK 21 assembler_x86.hppのC/Javaレジスタ定義](https://github.com/openjdk/jdk/blob/jdk-21-ga/src/hotspot/cpu/x86/assembler_x86.hpp#L78-L123)、[java_calling_convention](https://github.com/openjdk/jdk/blob/jdk-21-ga/src/hotspot/cpu/x86/sharedRuntime_x86_64.cpp#L483-L491)。
- **確信度：高。**

### T05：otelcが-workで残す場所はビルドキャッシュではなく作業ディレクトリ

- **任意の用語修正。** [`65-conclusion.md:76`]「Goのビルドキャッシュに書き換え後のソースが残ります」。`-work` が削除を止めるのは一時作業ディレクトリです。後段191行の `WORK=/tmp/go-build...` は正しく、手順の目的は伝わります。
- **修正案：** 「ビルドの一時作業ディレクトリに書き換え後のソースが残ります」とします。`GOCACHE` と混同させないための修正です。
- **根拠：** [go buildの-workフラグ](https://pkg.go.dev/cmd/go#hdr-Compile_packages_and_dependencies)、Go 1.26.5 `src/cmd/go/internal/work/build.go:115-117`。
- **確信度：高。**

### T06：構造体の比較例ではパディングの大きさは変わらない

- **任意の修正。** [`50-hurdle3_offsets.md:119`]「詰め物の位置と大きさも変わるので」。掲載された `streamV1` と `streamV2` では、`id` と `method` の間のパディングはどちらも4バイトです。
- **修正案：** 「8バイトのフィールドが途中に加わるので、その後ろの `id` と `method` は8バイトずれる。`id` 後の4バイトのパディングは変わらない」とします。一般にパディングが変わる場合はありますが、この例の説明とは分けます。
- **根拠：** 同章90-116行の型定義、今回のGo 1.26.5実測の `id=16, method=24` と `id=24, method=32`。それぞれ `24-(16+4)=4`、`32-(24+4)=4` です。
- **確信度：高。**

## 前回「判断保留」の決着

1. **Go 1.26.5固有の挙動：決着。** `GOTOOLCHAIN=go1.26.5` で13サンプルを実行しました。`http.Request` の0/16/56/88、`descend` の176バイト間隔、スタック移動の `moved=true`、構造体比較、`DumpRequestOut` のバイト列は一致しました。追加のビルドでは `Lookup` のRETが2個でアドレスも掲載どおり、`Add3` は9バイトのLEAQ/LEAQ/RETでした。noinlineの出力不一致はT01として確定しました。実行時アドレスやPIDの一致は要求していません。
2. **カーネルコミットとバックポート：決着。** コミットは実在します。[6.6.128](https://cdn.kernel.org/pub/linux/kernel/v6.x/ChangeLog-6.6.128) では `9681044e45c95c4e59f19f6316291d2b91eed3d2`、[6.12.75](https://cdn.kernel.org/pub/linux/kernel/v6.x/ChangeLog-6.12.75) では `c2681ce178a26100ceea94dc8dad5501f90d63a8`、[6.18.14](https://cdn.kernel.org/pub/linux/kernel/v6.x/ChangeLog-6.18.14) では `4b8d1424b32c4e01b8d6f48d748f550dc230a254` としてupstreamハッシュ付きで記録されています。6.19系列の訂正はT02です。バックポートの存在と、各ディストリビューションで実害が出ることは別の検証事項です。
3. **14章のバイナリサイズ：完全再現は保留、公開を止める理由なし。** 当該 `main.go` の全文が章内になく、元のファイル、ビルド環境、cgo設定まで特定できません。同じ主旨の別プログラムのサイズが違うだけでは誤りと断定できません。`-s -w` による削減という主張は維持できます。再現性を高めるなら元コードと条件を掲載する補足は任意です。
4. **図版：一部決着。** 現在の作業ツリーには全59参照先が存在します。前回の「画像が存在しない」という制約は解消しています。ABI、ビルド設定、ヘッダ注入、静的リンク、ELF、呼び出し規約比較、ハンズオンのトレース、ソースから実行までの8枚を目視確認しました。ABI比較の問題はC02/C05、キャプションとの食い違いはC03/C04です。ハンズオンのトレース画像には実際に7スパンと2サービスが表示されています。残る51枚の内容の全面検証はしていません。
5. **sk_msg単独・TLS・HTTP/2・遠隔ホスト間の注入：実機成功確認は保留。** 本環境で新しいカーネルや別ホストを用意しての実験はしていません。HTTP/2/gRPCにTCPオプションを使わないこと、Go TLSでは暗号化前のuprobe経路を使うことはv0.13.0の設計・実装で確認しました。本文は機能条件の説明として維持でき、今回の実機成功例とは扱いません。
6. **arm64実機・旧カーネル各版・lockdown有効時：実機検証は保留。** 今回利用した実機はamd64、Linux 7.0です。これらの環境で実測したとは判定していません。前回検証済みの仕様上の条件を取り消す根拠はありません。
7. **goid利用やC/Go定数整合性テストの不在：絶対的な不在証明は保留。** 前回確認済みの検索を繰り返して不在を強く断定することはしていません。厳密さを上げるなら「v0.13.0の関連実装・テストを検索した範囲では見当たらない」と表現する補足は任意です。これは新しい実装上の誤りの指摘には数えません。
8. **golang.org/x/arch v0.30.0：決着、修正不要。** `go mod download -json golang.org/x/arch@v0.30.0` が成功し、掲載ハッシュ `h1:sB9h+1gRGa2+LauFSV0tm8bK1J2yo1bx6/Uyi/P6DTU=` と完全一致しました。タグの元コミットは `11c82a522798f87f892513ba23069e7f5b2f549a` です。[公式モジュールプロキシの版情報](https://proxy.golang.org/golang.org/x/arch/@v/v0.30.0.info)でも照合できます。

## 検証して問題なかった箇所（今回新たに確認した分のみ）

- **Addressの修正自体は正しい。** cilium/ebpfは明示AddressをVA変換せず使い、OBIの `findFuncOffset` は実行可能なPT_LOADを選んで変換しています。今回Go 1.26.5で作った `Lookup` でも `p_vaddr=0x400000`、`p_offset=0`、RETのVA `0x49e290` に対するファイル位置 `0x9e290` のバイトは `c3` でした。残る問題はC01の参照先です。[cilium/ebpf v0.22.0](https://github.com/cilium/ebpf/blob/v0.22.0/link/uprobe.go)、[OBIの変換](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/internal/goexec/instructions.go#L216-L249)。
- **reflection情報の訂正は正しい。** Go 1.26.5で `net/http.Request` をreflectionで調べるプログラムを `-s -w` 付きでビルドしました。`.symtab`／`.debug_*` がない状態でもフィールド名と0/16/56/88が取得できました。2章の「値そのものには名前がない」と4章末の「型情報側には残る」は両立します。[Goの型メタデータ](https://github.com/golang/go/blob/go1.26.5/src/internal/abi/type.go)。
- **ELFの実行範囲の訂正は妥当。** 図とキャプションに `.rodata`、`.data`、`.bss`、`.gopclntab` が加わり、「.textだけで実行できる」という説明は解消しています。`readelf -lW` でも各データを含むPT_LOADを確認しました。セクション名の列挙は代表例として読めます。[ELF仕様](https://refspecs.linuxfoundation.org/elf/elf.pdf)。
- **ヒープ乱択の訂正はGo 1.26.5で再現。** 同じサンプルを `setarch x86_64 -R` で3回実行してもアドレスは大きく変わりました。`GOEXPERIMENT=norandomizedheapbase64` で再ビルドした場合は `0xc000...` の近い範囲となり、本文の「変動幅が小さくなる」と一致しました。完全固定になるとは書いていない点も正確です。[Go runtime/malloc.go](https://github.com/golang/go/blob/go1.26.5/src/runtime/malloc.go)、[実験の既定値](https://github.com/golang/go/blob/go1.26.5/src/internal/buildcfg/exp.go)。
- **ABIInternal／ABI0の本文修正は正しい。** Go 1.12の定義に両者が存在します。11章のスカラーとstring/interface/sliceの成分数の区別、RETによるスタック読取りへの注記も妥当です。残るのはC02/C05です。[Go内部ABI](https://github.com/golang/go/blob/go1.26.5/src/cmd/compile/abi-internal.md)。
- **関数の異常終了の修正は129行単体では正しい。** 未回復panicで全体が終了すること、外側でrecoverしても内側の関数のRETは通らないこと、Goexit/Exitも通常のRET捕捉から外れることを区別しています。後続例との接続だけがC06です。[panic/recover仕様](https://go.dev/ref/spec#Handling_panics)、[runtime.Goexit](https://pkg.go.dev/runtime#Goexit)、[os.Exit](https://pkg.go.dev/os#Exit)。
- **HTTP/2/gRPCのTCPオプション除外は正しい。** 接続に複数のストリームが載るため、OBIはHPACKのストリーム単位の経路を使います。HTTP/1のTCPオプション代替経路との区別は修正後の説明で成立します。[OBI v0.13.0設計](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/devdocs/grpc-context-propagation.md#why-not-tcp-options)。
- **OBIのDevelopmentへの統一は正しい。** v0.13.0のVERSIONING.mdと一致し、alpha/betaの混同は解消しています。確認時点の最新リリースもOBI v0.13.0、otelc v1.1.0で、本文が新しい公開済みリリースを取り逃している証拠はありません。[OBIの安定性方針](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/VERSIONING.md)、[OBIリリース](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/releases)、[otelcリリース](https://github.com/open-telemetry/opentelemetry-go-compile-instrumentation/releases)。
- **9章の修正は実装条件と整合。** heuristicとlow-cardinalityを分けた説明、待ち時間が測れた場合のサブスパン、privilegedの条件付け、経路1の成功条件への留保は、v0.13.0の該当分岐と一致します。前回動作確認済みのハンズオンのコードブロックも変更されていません。[routes.go](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/transform/routes.go)、[tracesgen.go](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/pkg/export/otel/tracesgen/tracesgen.go)、[Go HTTPの注入条件](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/v0.13.0/bpf/gotracer/go_nethttp.c)。
- **otelcの注入対象と-workの訂正は妥当。** 対応ライブラリの関数本体へ注入する説明が掲載変換例と一致し、コマンドの重複 `-work` も削除されています。リンク先の `buildWithToolexec` は指定行範囲に存在します。[otelc v1.1.0 setup.go](https://github.com/open-telemetry/opentelemetry-go-compile-instrumentation/blob/v1.1.0/tool/internal/setup/setup.go#L536-L596)。
- **追加リンクの主題は一致。** eBPF、BTF、ELF、DWARF、strace、OpenSSL、HPACK、OTLP、TraceQLへのリンクは、導入している概念を扱う公式資料に到達しました。L01以外に今回確定したリンク上の問題はありません。これはリンク先の全主張が本書の全実装説明を保証するという意味ではありません。

## 検証できなかった／判断保留

- 14章のサイズの完全再現には、元の `main.go` とビルド条件が足りません。値の不一致を誤りとする根拠はありません。
- arm64、旧カーネル、lockdown有効環境、sk_msg単独、遠隔ホスト間のTLS／HTTP/2について、新しい実機成功確認は行っていません。仕様・実装の確認と区別しています。
- 図59枚の存在と全キャプションは確認しましたが、画像内容を表示して検証したのは8枚です。残り51枚の技術的内容・画面属性の全面検証は保留です。
- 不在の絶対的な証明、`latest` イメージの将来の再現性、将来のGoやOBIリリースの互換性は保証できません。固定版について確認できた内容を越えて「必ず動く」とは判断していません。

これらの保留を根拠に原稿の断定を新たに誤りと認定することはしません。公開前に必要な修正はS01、C01〜C06、L01、T01〜T04の12件です。S02、C07、T05、T06は任意の補足です。
