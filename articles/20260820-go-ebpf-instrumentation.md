---
title: "なぜGoバイナリへのeBPF計装は難しいのか"
emoji: "🐝"
type: "tech"
topics: ["go", "ebpf", "opentelemetry", "observability", "grafana"]
published: false
---

## はじめに

eBPFを使うと、アプリケーションのソースコードを一切変更せずに、HTTPやgRPCの分散トレースを取得できます。いわゆる**ゼロコード計装**（zero-code instrumentation）です。再ビルドも再デプロイも不要で、言語を問わず動きます。製品の説明ではしばしばそう語られます。

しかし、その仕組みの中身は言語ごとにまったく違います。eBPFで関数レベルまで踏み込んで計装されているのは、実のところGoだけです。他の言語では、通信のバイト列をプロトコルとして解釈する汎用の経路が主になります。Goに対してだけ深く踏み込めるのは、静的にリンクされたバイナリに関数のアドレスが固定で並んでいるからです。そして踏み込んだ先で、他の言語では出てこない難所に次々とぶつかります。

難所の正体は、**Goを高速かつ書きやすい言語にしている設計そのもの**です。一般的なeBPF計装の定石は、スタックがOSに管理されて動かないこと、呼び出し規約がプラットフォームの標準に従うことを前提にしています。CやJavaのスレッドはこの前提を満たします。一方Goは、goroutineのスタックを実行中に動かし、独自の呼び出し規約を持ち、スケジューリングもメモリ管理もランタイムが自前で抱えています。定石の前提が、ここでまとめて成り立たなくなります。

題材にするのは、Grafana BeylaがOpenTelemetryプロジェクトに寄贈されて生まれた**OpenTelemetry eBPF Instrumentation**（OBI）です。4つの難所それぞれに、Goの手元の環境で実行して確かめられるコードを添えました。そのうえで、同じことをOBIが実際にどう書いているかを見ます。本記事に載せた実行結果はすべて go1.26.0 linux/amd64 での実測値で、OBIのコードはリリース v0.11.0 時点のものです。

### 分散トレースと traceparent

先に言葉を決めておきます。**計装**（instrumentation）とは、処理時間や呼び出し関係を記録するために、プログラムに観測点を加えることです。本記事で**バイナリ**と呼ぶのは、0と1の列一般ではなく、コンパイルしてできた実行ファイルを指します。

**分散トレース**は、複数のサービスにまたがる1つの処理を、1本の流れとして見るための記録です。サービスAがサービスBを呼ぶとき、Aでの処理とBでの処理に同じ**トレースID**を持たせておけば、別々に届いた2つの記録を後からつなげて表示できます。区間ひとつひとつは**スパン**と呼び、Bのスパンは親としてAのスパンIDを持ちます。

この識別情報をHTTPで運ぶヘッダが `traceparent` です。W3C Trace Contextで形式が決まっていて、`00-<トレースID>-<スパンID>-01` のように書きます。SDKを使う計装では、アプリが自分でこのヘッダを付けます。アプリのコードを変えずに外から付けるのが、本記事でいうゼロコード計装です。

![分散トレースの基本](/images/20260820-distributed-trace-basics.png)
*図1: 実線の矢印はリクエストの流れ、破線は記録がバックエンドへ送られることを表す。トレースIDが同じなので2つのスパンは1本のトレースとして表示でき、Bのスパンは親としてAのスパンIDを持つ。*

eBPFでこれを実現する経路は2つあります。通信を見る計装は、ソケットを流れる `GET /items` のようなバイト列からHTTPだと判断し、リクエストとレスポンスの対応から所要時間を測ります。関数を見る計装は、`net/http` の特定の関数が呼ばれた瞬間に、その引数を読みます。前者は言語を問いませんが、後者は言語ごとに実装が要ります。本記事が扱う4つの難所は、すべて後者で起きるものです。

### この記事の読み方

難所の中身に入る前に、プログラムがLinuxの上でどう動いているのか、Goランタイムが何を抱えているのかを2つの章で押さえます。スタックがどこにあり、引数がどこに置かれ、関数のアドレスがどう決まるか。ここが分かっていれば、4つの難所はどれも「たしかにそれは難しい」と納得できる話になります。

前提としているのはGoのコードが読めることだけです。OS、アセンブリ、eBPF、分散トレースの知識は要りません。必要なぶんは出てくるたびに補います。

逆に、Goの内部やLinuxの実行モデルに慣れている読者は、この2章を飛ばして「eBPFとは何か」から読んでも困りません。

難所の節ではOBIの実装コードも引用しますが、コードを読まなくても筋は追えるように書きました。長い抜粋は折りたたんであり、各難所の末尾には実装を読まなくても残る一文を置いています。

## プログラムはどう動いているのか

eBPF計装の難しさは、プログラムが動く仕組みの細部から出てきます。この章では、あとで必要になる分だけをまとめて見ておきます。Goのコードを書いたことがあれば追える範囲にとどめました。

個々の用語を別々に覚える必要はありません。書いたソースが動き出すまでの流れの、どこの話なのかが分かれば足ります。

![ソースから実行までの流れ](/images/20260820-source-to-execution.png)
*図2: 矢印は時間と変換の流れを表す。各段の下に、その話を扱う節の名前を添えた。以降の節はこの流れを上から順にたどる。*

### ユーザー空間とカーネル空間

CPUには実行の特権レベルがあり、アプリケーションのコードは制限された側で動きます。この側を**ユーザー空間**、制限のない側を**カーネル空間**と呼びます。ユーザー空間のプログラムは、ディスクやネットワークカードに直接命令を出せません。

触りたいときはカーネルに頼みます。この頼み方が**システムコール**です。ファイルを読む `read`、書く `write`、通信の口を開く `socket` などが用意されていて、Goの `os.ReadFile` も内側ではシステムコールを呼んでいます。頼まれたカーネルがハードウェアを操作し、結果を返します。

見た目は関数呼び出しですが、通常のGoの関数呼び出しとは中身が違います。普通の呼び出しは同じ特権レベルのまま次の命令へジャンプするだけです。システムコールでは専用の命令でカーネル側へ切り替わり、カーネルが処理を終えてから戻ってきます。切り替えの分だけ、普通の関数呼び出しより高くつきます。

eBPFは、このカーネル側で動くプログラムです。ユーザーが書いたコードをカーネルの中に置くのですから、そのままでは危険です。何が危険で、どう防いでいるのかは、あとのeBPFの章で見ます。

![ユーザー空間とカーネル空間](/images/20260820-user-kernel-space.png)
*図3: 矢印はお願いの向きを表す。実線はアプリからカーネルへの依頼、破線は結果が返ること、赤い破線はできないことを示す。*

### プロセスに与えられるメモリ

プログラムを起動するとプロセスができて、そのプロセス専用のアドレス空間が与えられます。連続した番地の列が見えていて、他のプロセスの同じ番地とは無関係です。この見えているアドレスは仮想アドレスと呼ばれ、実際の物理メモリのどこに載っているかはカーネルが管理します。

アドレス空間は用途ごとの領域に分かれます。機械語が置かれるテキスト領域、グローバル変数のデータ領域、そして**ヒープ**と**スタック**です。

ヒープとスタックの違いは、寿命と管理者です。スタックは関数を呼ぶと伸び、抜けると縮みます。片付けを気にしなくていい代わりに、関数を抜けたあとまで値を残せません。ヒープは明示的に確保する領域で、関数を抜けても残ります。その代わり、誰かが解放するか、Goのように回収する仕組みが要ります。Goではどちらに置くかをコンパイラが判断し、ローカル変数のアドレスを返す関数を書けば、その変数はヒープに移ります。

![プロセスに与えられるメモリ](/images/20260820-process-memory.png)
*図4: この図に矢印はない。上下はアドレスの高低を表し、スタックは高いほうから低いほうへ、ヒープは低いほうから高いほうへ向かって伸びる。*

### CPUとレジスタ

CPUはメモリの中の値をその場で計算しているのではありません。値をいったんCPUの中の小さな入れ物に読み込み、そこで計算し、必要なら書き戻します。この入れ物が**レジスタ**です。数は数十個で、1つの大きさは64ビット。メモリより桁違いに速い代わりに、桁違いに少ないです。

amd64では、計算に使う汎用レジスタに `RAX`、`RBX`、`RCX` などの名前が付いています。ほかに、スタックの先端を指す `SP` と、次に実行する命令のアドレスを持つ `PC` があります。

「関数の引数をレジスタで渡す」という話が2つ目の難所で出てきます。それは、呼び出し元が値を `RAX` や `RBX` に入れ、呼び出し先がそこから読む、という取り決めのことです。メモリを経由しないので速く、外から覗く側には見つけにくくなります。

![CPUとレジスタ](/images/20260820-cpu-registers.png)
*図5: 矢印はデータの移動方向を表す。計算はレジスタの上で行われ、メモリは必要なときだけ読み書きされる。*

### 関数呼び出しとスタックフレーム

関数を呼ぶと、スタックにその関数の作業領域が積まれます。これを**スタックフレーム**と呼びます。フレームにはローカル変数や、あとで使う値を退避したものが置かれ、関数を抜けると捨てられます。

引数の置き場所は、フレームの中とはかぎりません。どこに置くかは呼び出し規約という取り決めで決まり、あとで見るように、現在のGoは先頭のいくつかの引数をレジスタで渡します。戻りアドレスはスタックにあり、引数はレジスタにもある。この違いは2つ目の難所でそのまま問題になります。

積まれるものはもう1つあります。**戻りアドレス**です。amd64では `CALL` 命令が、呼び出しの次の命令のアドレスをスタックに積んでからジャンプします。関数末尾の `RET` 命令は、積まれたその値を取り出してそこへジャンプします。つまり「どこへ戻るか」は、スタック上の1つのスロットに書かれたただの数値です。

この数値をカーネルが書き換えるのが、1つ目の難所で扱う `uretprobe` の仕組みです。書き換える相手がスタックの上にある、という点を覚えておいてください。

![関数呼び出しとスタックフレーム](/images/20260820-stack-frame.png)
*図6: 実線の矢印は制御の流れ（呼び出しと復帰）を表す。点線はフレームが積まれる関係で、制御の流れではない。*

### 機械語、命令アドレス、シンボル

Goのソースをビルドすると、機械語の命令が並んだバイナリができます。命令は先頭から順に置かれ、1つずつにアドレスがあります。実行とは、`PC` が指すアドレスの命令を取り出して実行し、`PC` を進める、という繰り返しです。

バイナリには、名前とアドレスの対応表も入っています。**シンボルテーブル**です。`main.Lookup` という関数がアドレス `0x49df80` から始まる、という情報がここにあります。`go tool nm` で覗けます。

逆に、機械語のバイト列を人が読める命令に戻す作業が**逆アセンブル**です。`go tool objdump` がそれをします。バイト列には「ここからここまでが1つの命令」という区切りが書かれていないので、先頭から順に解釈していくしかありません。この性質は1つ目の難所でOBIのコードとして現れます。

uprobeは「バイナリの特定の命令アドレスにフックを置く」仕組みです。この節の言葉でいえば、アドレスを1つ選び、そこにCPUが到達したらeBPFプログラムを走らせる、という指定になります。

![ソースから機械語へ、そしてシンボル](/images/20260820-source-to-machine.png)
*図7: 実線の矢印は変換の向きを表す。破線はシンボルテーブルが名前からアドレスを引く参照で、変換ではない。*

### 構造体はメモリ上でどう並ぶか

構造体は、フィールドが宣言順にメモリへ並んだものです。ただし詰めて並ぶとは限りません。8バイトの値は8バイト境界から始まる、といった制約があるので、あいだに詰め物（パディング）が入ります。

大事なのは、コンパイルしたあとにフィールド名が残らないことです。実行中のメモリにあるのはバイト列とアドレスだけです。`req.Method` と書けるのはソースの世界の話で、外から同じ値を読むには「構造体の先頭から何バイト目か」を知っていなければなりません。

この「何バイト目か」が**フィールドオフセット**です。Goからは `unsafe.Offsetof` で取り出せます。3つ目の難所は、この数値をどうやって知るかという話になります。

![構造体はメモリ上でどう並ぶか](/images/20260820-struct-layout.png)
*図8: 矢印は変換の向きを表す。左のソースにあるフィールド名は右のメモリには残らず、バイト位置だけが残る。*

### ELFバイナリの中身

Linuxの実行ファイルはELFという形式です。中はセクションに分かれていて、機械語は `.text`、定数は `.rodata` に入ります。

実行に要らない情報も入っています。シンボルテーブルの `.symtab` と、型やフィールドや行番号を記述した**DWARF**（`.debug_*`）です。Goのバイナリには、さらにGo固有の `.gopclntab` と、ビルド情報のブロブが入ります。前者はアドレスから関数名と行番号を引くための表で、後者はGoの版と依存モジュールの一覧です。

これらを読む側は複数います。Goランタイムはパニック時のスタックトレースを組み立てるために `.gopclntab` を読みます。デバッガはDWARFを読んで変数を表示します。そして計装ツールは、関数の位置を知るために `.gopclntab` を、フィールドの位置を知るためにDWARFを、版を知るためにビルド情報を読みます。

どれが削れるかも重要です。ビルド時に `-ldflags="-s -w"` を付けると `.symtab` とDWARFが落ちます。それで何が起きるかは記事の後半で確かめます。

![ELFバイナリの中身と、それを読む側](/images/20260820-elf-sections.png)
*図9: 矢印は読む側から読まれるセクションへ向かう。誰が何を必要とするかを表しており、データの流れではない。*

---

## Goランタイムは何を抱えているのか

Goのバイナリには、書いたコードのほかにランタイムが入っています。ランタイムはスケジューリングとメモリ管理を自前で行い、OSに任せません。この「自前でやっている」ことが、外から観測する側の難しさに直結します。

### 静的リンクされた1つのバイナリ

Goは既定で静的リンクします。標準ライブラリもランタイムも1つの実行ファイルに同梱され、cgoを使わなければ共有ライブラリを必要としません。`ldd` にかけても `not a dynamic executable` と返ってきます。

これは計装する側から見ると好都合です。Cのプログラムは実行時に共有ライブラリを結び付けるので、`libc` の関数がどのアドレスに来るかは環境によって変わります。Goのバイナリでは、アプリのコードもランタイムも標準ライブラリも、同じファイルの中に固定の位置で並んでいます。

冒頭で「Goに対してだけ深く踏み込める」と書いたのは、この性質があるからです。関数のアドレスがファイルの中で決まっていれば、そこにuprobeを置けます。

![静的リンクされたGoバイナリと動的リンク](/images/20260820-static-link.png)
*図10: 矢印は依存の向きを表す。Cのプロセスは実行時に共有ライブラリへの依存を解決するが、Goのバイナリはその段を持たない。*

### OSスレッドとgoroutine

goroutineはOSスレッドではありません。ランタイムが管理する実行単位で、`go f()` と書くたびに数KBの小さな作業領域とともに作られます。数万個作っても構いません。

ランタイムの中では、3つの構造体が役割を分けています。`g` がgoroutine1つ、`m` がOSスレッド1つ、`p` はGoコードを動かすための実行権と待ち行列です。多数の `g` が、`p` を通じて少数の `m` の上で順番に動きます。切り替えを決めるのはカーネルではなくGoランタイムです。この記事で以降も出てくるのは `g` だけなので、`m` と `p` は名前だけ覚えておけば足ります。

帰結が2つあります。1つは、OSから見るとgoroutineが見えないこと。カーネルが知っているのはスレッドまでです。もう1つは、同じOSスレッドの上で別のリクエストのgoroutineが動きうること。スレッドIDを見ても「同じリクエストの処理か」は分かりません。4つ目の難所はここから始まります。

![OSスレッドとgoroutine](/images/20260820-goroutine-scheduling.png)
*図11: 矢印は載る関係を表す（上のものが下のものの上で動く）。どのgoroutineをいつ動かすかを決めるのは、カーネルではなくGoランタイムである。*

### goroutineスタックの伸長

OSスレッドのスタックは、起動時にまとまった大きさで確保され、動きません。goroutineのスタックは違います。小さく始めて、足りなくなったら大きくします。

手順はこうです。関数の入口に「スタックの残りが足りるか」を調べる命令が入っていて、足りなければ `runtime.morestack` へ飛びます。そこでより大きい領域を確保し、いまの内容を丸ごとコピーし、スタックを指していたポインタを新しいアドレスへ書き換えます。

つまり、あるgoroutineのローカル変数のアドレスは実行中に変わります。ランタイムは自分が置いたポインタを補正するので、Goのコードから見ればこの引っ越しは見えません。外から覗く側には見えます。1つ目の難所はこれが原因です。

![goroutineのスタックが引っ越す手順](/images/20260820-stack-move.png)
*図12: 矢印は時間の前後を表し、上から下へ進む。ランタイムが補正するのは、ランタイム自身が置いたポインタだけである。*

### 独自の呼び出し規約

関数の引数をどこに置くかという取り決めも、Goは自前で決めています。Go 1.17以降、引数はスタックではなくレジスタで渡ります。

もう1つ、amd64ではR14レジスタが特別扱いされ、いま実行中のgoroutineの `g` 構造体を指し続けます。Goのコードをコンパイルした機械語には、このR14があちこちに現れます。

詳細は2つ目の難所で扱います。ここでは「Goの関数呼び出しはプラットフォームの標準的な取り決めに従っていない」ことだけ押さえておけば足ります。

---

## eBPFとは何か

### カーネルの中で動く小さなプログラム

eBPFは、ユーザーが書いた小さなプログラムをLinuxカーネルの中にロードして、特定のイベントが起きたときに実行させる仕組みです。イベントとは、システムコールが呼ばれた、パケットが届いた、ある命令アドレスに到達した、といったものを指します。カーネルを再ビルドしたり、カーネルモジュールを書いたりする必要はありません。

たとえば「`openat` システムコールが呼ばれたら、そのファイル名を記録する」「ある命令アドレスに到達したら、その時刻を控える」といった処理を書けます。本記事で扱うのは後者、つまりユーザー空間のプログラムの特定のアドレスにフックを置く使い方です。

ユーザー空間とカーネル空間の節で見たとおり、カーネル空間は制限のない側です。そこで任意のコードを走らせるのですから、そのままでは危険です。

### 検証器が課す制約

危険を防いでいるのは**検証器**（verifier）です。ロード時にプログラム全体を静的に解析し、通らなければロード自体が失敗します。検証器が保証するのは、プログラムが必ず停止すること、未初期化のメモリやポインタを読まないこと、許可されたメモリ以外に触らないことです。振る舞いはコンパイラの型検査に近いものです。Goのコンパイラが型の合わない代入をコンパイルエラーにするように、検証器は安全性を証明できないプログラムをロードエラーにします。走らせてから落ちるのではなく、載せる前に断られます。

この検証を成立させるために、eBPFプログラムにはいくつもの制約が課されます。命令数に上限があり、ループは回数の上界がコンパイル時に決まる形でしか書けません。「リストを終端まで辿る」ような、素直でありながら停止性を証明しにくいコードは書けません。この制約は4つ目の難所で具体的な形をとって現れます。

![検証器が課す制約](/images/20260820-verifier.png)
*図13: 矢印はロードの試行とその結果を表す。検証は実行前に一度だけ行われ、通らなければプログラムはカーネルに載らない。*

### イベントをまたいで状態を持つマップ

カーネル側で動くeBPFプログラムは、イベントごとに呼ばれてすぐ終わります。関数のローカル変数に相当するものは、次のイベントには残りません。イベントをまたいで状態を持つには、**マップ**（map）と呼ばれるカーネル管理のキーバリューストアを使います。役割はGoの `map` と似ています。違うのは、実体がカーネル側にあり、eBPFプログラムからもユーザー空間のプロセスからも読み書きできる点です。

「関数の入口で開始時刻を記録し、出口でそれを取り出して所要時間を計算する」という計装の基本パターンは、このマップの上で成り立っています。4つ目の難所で登場する `ongoing_goroutines` も、goroutineの親子関係を保持するマップです。

![マップで入口と出口をつなぐ](/images/20260820-map-pattern.png)
*図14: 矢印は時間の前後を表す。入口のフックと出口のフックは別々のイベントで、両者をつないでいるのはマップのキーである。*

### uprobeとuretprobe

eBPFでユーザー空間のプログラムにフックを仕掛ける主な仕組みは2つあります。

- **uprobe**：ユーザー空間バイナリの「特定の命令アドレス」に置くプローブ。関数の先頭アドレスに置くことが多いため「入口のフック」と呼ばれがちだが、仕組み上は入口専用ではなく、バイナリ中の任意の命令アドレスに置ける。
- **uretprobe**：関数から「戻るタイミング」を捕捉するための特別な仕組み。

一般的な計装では、関数の入口にuprobe、出口にuretprobeを置き、「入口で開始時刻を記録、出口で所要時間を計算」というパターンを取ります。多くの言語ではこれで素直に動きます。Goでは、この素直な形が最初の一歩から使えません。

### Goで書かれたローダー

eBPFプログラム自体は制限されたCで書き、専用のコンパイラでバイトコードに落とします。しかし、そのバイトコードをカーネルにロードし、プローブを実際のアドレスに結びつけ、マップを読み出す側は、普通のユーザー空間のプログラムです。そしてこのローダー側は、多くの場合Goで書かれています。デファクトのライブラリが [`github.com/cilium/ebpf`](https://github.com/cilium/ebpf) で、OBIもこれを使っています。

uprobeを1つ仕掛けるコードを見ておきます。

```go
// コンパイル済みeBPFプログラム objs は事前にロード済みとする
exe, err := link.OpenExecutable("/proc/12345/exe")
if err != nil {
	return err
}

// シンボル名を指定して関数の先頭に置く
up, err := exe.Uprobe("main.handleRequest", objs.OnEntry, nil)
if err != nil {
	return err
}
defer up.Close()
```

第1引数にシンボル名を渡すと、そのシンボルの先頭アドレスにプローブが置かれます。シンボル名の代わりに、アドレスを直接指定する形もあります。

```go
up, err := exe.Uprobe("", objs.OnReturn, &link.UprobeOptions{
	Address: 0x49e050, // 関数先頭からのオフセット
})
```

シンボル名を空文字列にして `Address` を渡すこの形が、1つ目の難所の回避策そのものになります。なお、ここに挙げた2つのコードは動かすのにroot権限とLinuxが要るので、読むだけでかまいません。手元で実行して確かめるのは、これ以降に出てくるGoのサンプルのほうです。

![eBPFの全体像](/images/20260820-ebpf-overview.png)
*図15: 実線の矢印は処理の流れ、破線は補助的な流れ（uprobeの設置とマップの読み出し）を表す。ローダーがeBPFプログラムをカーネルへ載せ、検証器を通ったものだけが常駐する。uprobeを置いた命令アドレスに到達すると発火し、イベントをまたぐ状態はマップを介してユーザー空間から読み出せる。*

### OBIとは何か

OBIは、もともとGrafanaが開発していたeBPFベースの自動計装ツール**Beyla**を前身とします。2025年5月にOpenTelemetryプロジェクトへの寄贈が発表され、同年10月30日に最初のリリース `v0.1.0` が出ました。2026年3月のKubeCon EUでbetaに到達し、その後もおよそ月1回のペースでリリースが続いています。本記事執筆時点の最新は2026年8月17日の `v0.11.0` で、`1.0` GAを目標にしています。

参照するソースは、リポジトリ [`open-telemetry/opentelemetry-ebpf-instrumentation`](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation) です。カーネル側のCコードが `bpf/` 配下、Goで書かれたローダーと解析処理が `pkg/` 配下にあります。Goを扱う部分は主に `bpf/gotracer/` と `pkg/internal/goexec/` です。

OBIの計装は、`SUPPORT_MATRIX.md` にあるとおり2つのカテゴリに分かれます。一つはネットワークレベルのプロトコル計装で、こちらは言語に依存しません。ソケットを流れるバイト列を、HTTP/1.1、HTTP/2、gRPC、MySQL、PostgreSQL、Redis、Kafkaなどとして解釈します。もう一つがランタイムやライブラリのレベルの計装で、こちらは対象の環境ごとに個別の実装が要ります。そしてライブラリレベルの関数計装を持つのはGoだけです。`net/http` は1.17以降、`google.golang.org/grpc` は1.40以降、`database/sql` は1.17以降、というようにサポート範囲がバージョン単位で決まっています。本記事が扱う4つの難所は、すべてこの後者の経路で起きるものです。

![OBIの2つの計装経路](/images/20260820-obi-two-paths.png)
*図16: 矢印は分類の枝分かれを表す。プロトコル計装は言語に依存しない。関数レベルまで踏み込む計装はランタイムとライブラリごとの実装が要り、それを持つのはGoだけである。*

---

## 1つ目の難所：`uretprobe` が使えない

### 症状

関数の入口と出口にプローブを置くだけなら、Goでも同じようにできそうに見えます。ところが、Goのバイナリに対してuretprobeを使うと、最悪の場合、計装対象のGoプログラムが次のエラーでクラッシュします。

```
fatal error: unknown caller pc
```

観測していただけのはずが、観測対象を道連れに落ちます。計装はあくまで観測が目的であり、これは許されない挙動です。なぜ観測しただけで対象が落ちるのでしょうか。原因はuretprobeの実装にあります。

### uretprobeの仕組み

関数呼び出しとスタックフレームの節で見たとおり、戻りアドレスはスタックに積まれ、関数末尾の `RET` 命令がそれを取り出してジャンプします。

uretprobeは、関数に入った瞬間に、スタック上の戻りアドレスを自身の「トランポリン」のアドレスに書き換えます。こうすると関数がreturnする際、本来の呼び出し元ではなく一度カーネルのフックに制御が戻り、そこで処理を行ってから本物の戻りアドレスへジャンプし直します。

つまりuretprobeは「スタック上の戻りアドレスは、書き換えた後も同じ場所に留まり続ける」という前提に立っています。

![uretprobe による戻りアドレスの書き換え](/images/20260820-uretprobe-rewrite.png)
*図17: 実線の矢印は制御の流れ、破線は書き換えられた戻りアドレスが導く先を表す。uretprobeは関数に入った瞬間に、スタック上の戻りアドレスをトランポリンのアドレスへ書き換える。この方式は「戻りアドレスを置いたスタック上の場所は、その後も動かない」ことを前提にしている。*

### Goの可動スタックとの衝突

この前提が、Goでは成り立ちません。goroutineのスタックが伸長のたびに別の領域へ引っ越すことは、goroutineスタックの伸長の節で見ました。

ここで問題になるのは、ポインタの補正そのものではありません。補正するために、ランタイムがスタックを**辿らなければならない**ことです。

スタックを移すとき、ランタイムはフレームを1つずつ辿ります。次のフレームへ進むには、いま見ているフレームに積まれた戻りアドレスを読み、それがどのGo関数の中のアドレスなのかを引きます。この検索に使うのが、ELFバイナリの中身の節で見た `.gopclntab`（命令アドレスからGoの関数名を引く表）です。関数が分かってはじめて、そのフレームの大きさと、フレーム内のどこにポインタがあるかが分かり、補正できます。

uretprobeが書き換えた戻りアドレスは、Goバイナリの関数ではなくカーネルが用意したトランポリンを指しています。表を引いても該当する関数がありません。スタックのコピーやGCの走査は途中でやめられない処理なので、ランタイムは `fatal error: unknown caller pc` で落ちます。go1.26では `runtime/traceback.go` の `unwinder.next` が、戻りアドレスを `findfunc` に渡して失敗したときにこのエラーを投げています。これがGoとuretprobeが相容れない理由です（[golang/go#22008](https://github.com/golang/go/issues/22008)、[#27077](https://github.com/golang/go/issues/27077)）。

![戻りアドレスから関数を引けないと、スタックを辿れない](/images/20260820-unwind-failure.png)
*図18: 実線の矢印は処理の流れ、破線はスタックから読み取る値を表す。ランタイムは戻りアドレスを手がかりに「どの関数のフレームか」を引く。トランポリンのアドレスは表に無いので、そこで辿れなくなる。*

### 動くスタックの実測

「スタックが動く」というのは、日常のGo開発ではまず意識しない挙動です。実際に動くところを見ておくと、以降の話が具体的になります。

次のコードには、結果を見やすくするための仕掛けが3つ入っています。`//go:noinline` は、コンパイラに関数を展開させず呼び出しとして残させる指示です。`grow` の中の `pad` と深い再帰は、スタックを確実に使い切らせるためにあります。`unsafe.Pointer` と `uintptr` は、変数のアドレスを数値として取り出して前後で比べるためだけに使っています。どれも通常のアプリケーションで書く必要のあるものではありません。

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
before = 0x7f82f922ee8
after  = 0x7f82fb5fee8
moved  = true
```

具体的なアドレスは実行ごとに変わります。`moved` は、この記事で使った go1.26.0 linux/amd64 では毎回 `true` になりました。再帰で `main` のフレームより深いところまでスタックを消費した結果、ランタイムがより大きな領域を確保して、`main` のフレームごと引っ越したのです。このとき `anchor` を指すポインタがあれば、ランタイムはそれも新しいアドレスに書き換えます。

uretprobeが書き込んだ偽の戻りアドレスは、このコピーには巻き込まれますが、補正の対象にはなりません。ランタイムから見れば、それは自分が置いた覚えのないビット列だからです。

### 全 `RET` 命令へのuprobe

OBIは、出口専用のuretprobeが使えない以上、通常のuprobeを出口に相当する命令へ直接置くことで対処します。

前述のとおりuprobeは任意の命令アドレスに置けるため、関数の先頭ではなく、関数末尾の `RET` 命令のアドレスに置くこともできます。手順は次のとおりです。

1. 対象の関数を逆アセンブルする。
2. 機械語中のすべての `RET` 命令のアドレスを洗い出す。
3. その一つひとつに通常のuprobeを仕掛ける。

これにより、CPUが `RET` を実行して呼び出し元へ戻る直前にeBPFプログラムが発火します。この方式はスタック上の戻りアドレスを書き換えないため、Goの可動スタックと衝突しません。

![全 RET 命令へのuprobe](/images/20260820-ret-uprobes.png)
*図19: 矢印は処理の順序を表す。出口フックは、逆アセンブルして見つけた `RET` の一つひとつに通常のuprobeを置く。ソース上の `return` が1つでも、`defer` があれば `RET` は2つになる。*

### 1つの `return` から出る2つの `RET`

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

`go build` したうえで `go tool objdump` にかけると、`RET` が2つ出てきます。左の列はソースの行番号、次がアドレス、その右が命令です。ここで見るべきなのは `RET` と書かれた2行だけで、ほかの命令は読み飛ばしてかまいません。

```
$ go tool objdump -s 'main\.Lookup$' s2_ret
  s2_ret.go:14  0x49df80   CMPQ SP, 0x10(R14)
  s2_ret.go:14  0x49df84   JBE 0x49e061
  ...
  s2_ret.go:17  0x49e04f   POPQ BP
  s2_ret.go:17  0x49e050   RET                                   ← 通常の経路
  s2_ret.go:17  0x49e051   CALL runtime.deferreturn(SB)
  s2_ret.go:17  0x49e056   MOVQ 0x28(SP), AX
  s2_ret.go:17  0x49e05b   ADDQ $0x50, SP
  s2_ret.go:17  0x49e05f   POPQ BP
  s2_ret.go:17  0x49e060   RET                                   ← defer 経由の経路
  s2_ret.go:14  0x49e06b   CALL runtime.morestack_noctxt.abi0(SB)
```

`0x49e050` は通常どおり関数を抜ける経路、`0x49e060` は `runtime.deferreturn` を通ってから抜ける経路です。どちらも `s2_ret.go:17`、つまりソース上の同じ `return` に対応しています。

2つ目の経路がいつ選ばれるのかも押さえておきます。`defer` に登録した処理は、通常ならコンパイラが関数の末尾に展開してそのまま実行します。パニックが起きて `recover` で復帰したときは、`runtime.deferreturn` を通って残りの処理を片付けてから関数を抜けます。ループの中の `defer` のようにコンパイラが展開できない場合も、同じ経路を通ります。したがって `0x49e050` にしかuprobeを置かないと、パニックが起きた呼び出しだけ出口を捕まえられません。所要時間の記録が落ちるのはエラー時にかぎられ、平常時のテストでは気付けない抜けになります。

ついでに、この出力には後の節で扱う要素が2つ写り込んでいます。1行目の `CMPQ SP, 0x10(R14)` は、いま説明したスタック伸長の判定です。`R14` の指す構造体の16バイト目に入っている値とスタックポインタを比べ、足りなければ最終行の `runtime.morestack_noctxt` へ飛びます。その `R14` が何なのかは、2つ目の難所で扱います。

### OBIの実装

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

`exe.Uprobe` の第1引数が空文字列で、`Address` にオフセットを渡している点が、eBPF入門の節で見た「アドレス直指定」の形です。エラーメッセージには `uretprobe` と書かれていますが、実際に呼んでいるのは通常のuprobeです。出口フックという役割の名前だけが残っていて、中身は `RET` の位置に置いた入口フックと同じものになっています。

1つ目の難所は、可動スタックというGoの効率を支える仕組みが、そのまま計装の難しさになっている例です。実装を読まない場合、ここで残るのは1文です。戻りアドレスを書き換えず、機械語中のすべての `RET` に通常のuprobeを置く。

---

## 2つ目の難所：レジスタベースの呼び出し規約（ABIInternal）

フックは仕掛けられるようになりました。次の問題は、フックが発火した瞬間に関数の引数がどこにあるかです。

### ABIとは

**ABI**（Application Binary Interface）とは、関数呼び出しの際に「引数をどこに置くか」「戻り値をどこに置くか」「どのレジスタを誰が保存し、どのレジスタを破壊してよいか」といった低レベルの取り決めです。CPUとレジスタの節で見たレジスタが、ここで役割を割り当てられます。同じGoソースコードでも、コンパイル後の機械語ではこの取り決めに従って値が受け渡されます。

### Go 1.17の転換

Go 1.17より前は、引数をすべてスタックに積んで渡していました。これは外部から読むのは容易でした。関数の入口でスタックポインタからの固定オフセットを見れば、何番目の引数かが分かったからです。

Go 1.17以降は、性能向上のため引数をCPUレジスタで渡すようになりました。これが**ABIInternal**と呼ばれる規約です。amd64では、整数引数は次の順序でレジスタに割り当てられます。

```
RAX, RBX, RCX, RDI, RSI, R8, R9, R10, R11
```

名前の書き方に2通りあることを先に断っておきます。CPUのマニュアルやeBPF側の文書では64ビットのレジスタを `RAX` と書き、Goのアセンブリでは同じレジスタを `AX` と書きます。以降で `AX` と `RAX` が混ざって出てきますが、指しているものは同じです。

Goプログラムは高速化しましたが、外部から計装する側にとっては難物になりました。汎用のeBPFツールは「引数はスタックにある」と仮定するため、Goの引数を正しく取得できません。

![Go 1.17 の呼び出し規約の転換](/images/20260820-abi-shift.png)
*図20: 矢印は、引数の置き場所から、それを外から読む側へ向かう（何が手がかりになるか）。引数の受け渡しがスタックからレジスタに変わった。呼び出しは速くなり、外から引数を読む側はアーキテクチャ別のレジスタ対応表を持つことになった。*

### レジスタに乗る引数

引数3つの関数を書いて、コンパイル結果を見てみます。`//go:noinline` を付けるのは、この関数がインライン展開されると呼び出しの機械語ごと消えてしまい、引数の受け渡しが観察できなくなるからです。

```go
package main

import "fmt"

//go:noinline
func Add3(a, b, c int) int {
	return a + b + c
}

func main() {
	fmt.Println(Add3(1, 2, 3))
}
```

`go build -gcflags=-S` でアセンブリを出力すると、関数本体は3命令しかありません。

```
$ go build -gcflags=-S -o /dev/null s3_abi.go
main.Add3 STEXT nosplit size=9 args=0x18 locals=0x0 funcid=0x0 align=0x0
	TEXT	main.Add3(SB), NOSPLIT|NOFRAME|ABIInternal, $0-24
	LEAQ	(BX)(AX*1), DX
	LEAQ	(CX)(DX*1), AX
	RET
```

見るべきなのは中の3行です。1行目の `TEXT` は関数の宣言で、`(SB)` や `NOSPLIT` は生成条件の注記なので飛ばしてかまいません。`ABIInternal` だけが、この記事に関係する印です。

`a` が `AX`、`b` が `BX`、`c` が `CX` に入って渡され、結果は `AX` に置いて返ります。`LEAQ` は名前のとおりアドレスを計算する命令ですが、`(BX)(AX*1)` は「`BX` に `AX` を1倍して足した値」を意味するので、ここでは足し算の道具として使われています。関数全体が9バイトで、スタックには一度も触っていません。Go 1.17より前なら、この関数は引数をスタックから読み、結果をスタックに書いていました。

引数がどこにあるかを外から知るには、この対応表を持っている必要があります。

### OBIがレジスタを読むコード

OBIでこの対応表にあたるのが、`bpf/bpfcore/utils.h` のマクロ定義です。

```c
#if defined(__TARGET_ARCH_x86)

#define GO_PARAM1(x) ((void *)(x)->ax)
#define GO_PARAM2(x) ((void *)(x)->bx)
#define GO_PARAM3(x) ((void *)(x)->cx)
#define GO_PARAM4(x) ((void *)(x)->di)
#define GO_PARAM5(x) ((void *)(x)->si)
#define GO_PARAM6(x) ((void *)(x)->r8)
#define GO_PARAM7(x) ((void *)(x)->r9)
#define GO_PARAM8(x) ((void *)(x)->r10)
#define GO_PARAM9(x) ((void *)(x)->r11)

// In x86, current goroutine is pointed by r14, according to
// https://go.googlesource.com/go/+/refs/heads/dev.regabi/src/cmd/compile/internal-abi.md#amd64-architecture
#define GOROUTINE_PTR(x) ((void *)(x)->r14)

#elif defined(__TARGET_ARCH_arm64)
// arm64版は下に折りたたんだ
#endif
```

:::details arm64側のマクロ
```c
#define GO_PARAM1(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[0])
#define GO_PARAM2(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[1])
#define GO_PARAM3(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[2])
#define GO_PARAM4(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[3])
#define GO_PARAM5(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[4])
#define GO_PARAM6(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[5])
#define GO_PARAM7(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[6])
#define GO_PARAM8(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[7])
#define GO_PARAM9(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[8])

// In arm64, current goroutine is pointed by R28 according to
// https://github.com/golang/go/blob/master/src/cmd/compile/abi-internal.md#arm64-architecture
#define GOROUTINE_PTR(x) ((void *)((PT_REGS_ARM64 *)(x))->regs[28])
```
:::

`ax, bx, cx, di, si, r8, r9, r10, r11` という並びが、先ほどのレジスタ列 `RAX, RBX, RCX, RDI, RSI, R8, R9, R10, R11` とそのまま対応しています。`x` はuprobeが発火した時点のCPUレジスタの写しで、そこから該当のレジスタを取り出しているだけです。Goの公開APIは介在しません。プロセスが停止した瞬間のレジスタを、そのまま読んでいます。

### 現在のgoroutineをどう識別するか

引数以上に重要なのが、いまどのgoroutineが実行中かを知ることです。分散トレースでは1つのリクエストの処理が複数の関数をまたぐため、それらを「同じgoroutineで動いている」として紐づける必要があります。

OSスレッドとgoroutineの節で見たとおり、Goランタイムには `g`、`m`、`p` という構造体があります。本記事で必要なのは `g`（goroutine1つを表すランタイム内部の構造体）だけです。ある時点でCPU上を流れているGoコードは、「現在実行中のgoroutine」を表す `g` 構造体に紐づいています。

Goランタイムは、この `g` 構造体へのポインタを専用のレジスタに常駐させています。

| アーキテクチャ | `g` ポインタを保持するレジスタ |
|---|---|
| amd64 (x86_64) | R14 |
| arm64 | R28 |

先ほどの `GOROUTINE_PTR` マクロが読んでいるのが、まさにこのレジスタです。1つ目の難所で見た `CMPQ SP, 0x10(R14)` も、同じ `R14` から `g` 構造体の16バイト目（`stackguard0`）を読んで、スタックの残量を判定していました。Goで書かれたプログラムの機械語には、この `R14` があちこちに現れます。

ここでOBIは、素朴に予想されるのとは違う選び方をしています。`g` 構造体の中には `goid` というgoroutineの通し番号があり、これを読めば識別子になりそうです。しかしOBIは `goid` を読みません。リポジトリ全体を検索しても `goid` という語は1箇所も出てきません。

代わりに使っているのは、`g` 構造体そのもののアドレスです。`GOROUTINE_PTR` が返したポインタ値と、プロセスIDの組をキーにします。

```c
typedef struct go_addr_key {
    u64 pid;  // PID of the process
    u64 addr; // Address of the goroutine
} go_addr_key_t;
```

`addr` に入るのが `GOROUTINE_PTR(ctx)` の値そのものです。

必要なのは「あのときのgoroutineと、いまのgoroutineが同じか」という判定であって、人間が読む番号ではありません。アドレスはその判定に十分で、しかも構造体の中身を一切読まずに済みます。

この選び方が意味を持つのは、次の節との関係です。`goid` を読むには「`g` 構造体の先頭から何バイト目か」を知らなければならず、それはGoのバージョンごとに変わりえます。アドレスを使うかぎり、その追従が要りません。実際、OBIのオフセット表に `runtime.g` のエントリは存在しません。

![uprobe 発火時に OBI が読むもの](/images/20260820-goroutine-key.png)
*図21: 実線の矢印はデータの流れ、丸印の付いた破線は「読まない」ことを表す。OBIはR14（arm64ではR28）の値をそのまま goroutine の識別子に使い、ポインタの先にある `g` 構造体の中身は読まない。フィールドの並びがバージョンで変わっても壊れない。*

### 動くスタックと、動かない `g` 構造体

ここまでで「動く」と「動かない」が両方出てきたので、混同しないように整理しておきます。

1つ目の難所で「動く」と言ったのは、goroutineの**スタック**です。伸長のたびに新しい領域へコピーされ、アドレスが変わります。

いま「アドレスを識別子にできる」と言っているのは、`g` **構造体**のほうです。これはヒープ上に確保されていて、goroutineが生きているあいだ移動しません。`g` は自分が使っているスタック領域の範囲を `stack.lo` と `stack.hi` として保持しており、スタックが引っ越したときに書き換わるのはその中身です。容器のほうは動かず、容器が指している先が動きます。

![動かない g 構造体と、動くスタック](/images/20260820-g-vs-stack.png)
*図22: 矢印は参照を表す。`g` 構造体そのもののアドレスは変わらず、`stack.lo` と `stack.hi` が指す先だけが変わる。OBIが識別子に使うのは、変わらないほうのアドレスである。*

したがって、uretprobeがスタック上の戻りアドレスを書き換える方式は壊れ、`g` のアドレスをキーにする方式は壊れません。同じ「Goのスタックは動く」という一つの性質が、片方では障害になり、もう片方では問題になりません。

ただし、アドレスを識別子にする以上、goroutineが終わったあとのことは自分で面倒を見ることになります。時間の流れで並べると、利点と代償が同時に見えます。

![g のアドレスが再利用されるまで](/images/20260820-g-reuse-timeline.png)
*図23: 矢印は時間の前後を表す。処理が続いているあいだは同じアドレスが同じgoroutineを指すが、終了後は別のgoroutineに割り当てられる。破線は、古い記録を消していないときに起きることを示す。この後始末は4つ目の難所で実際のコードとして出てくる。*

なお、Goのアプリケーションコードから現在のgoroutineを識別する公式な手段はありません。`runtime.Stack` の出力から `goid` を文字列として取り出す既知の手法はありますが、Goチームは `goid` を意図的に公開していません。goroutineローカルな値を持ちたければ `context.Context` を引き回す、という設計です。外から見るOBIがアドレスを識別子にしているのは、その方針とも矛盾しない選び方だといえます。

2つ目の難所は、Goの値がメモリ上の分かりやすい場所ではなく、レジスタやその先の構造体の奥にあること、そしてそれをアーキテクチャ別、バージョン別に正確に読み解く必要があることです。ここで残るのは1文です。引数はアーキテクチャごとのレジスタ対応表から読み、goroutineは `g` のアドレスをそのまま識別子として使う。`g` については「読まない」という判断で回避できました。しかし他の構造体では、そうはいきません。

---

## 3つ目の難所：バージョン依存のフィールドオフセット

`g` 構造体は中身を読まずに済みました。しかし、HTTPリクエストのメソッド名やgRPCの呼び出し先を取ろうとすれば、構造体の中身を読むしかありません。外部の計装ツールは、どのフィールドがどこにあるかをどうやって知るのでしょうか。ここが4つの中で最も厄介な難所です。

### フィールドオフセットとは

構造体はメモリ上でどう並ぶかの節で見たとおり、外から見えるのはバイト位置だけです。構造体の先頭から何バイト目か、というこのバイト数を**フィールドオフセット**と呼びます。

言い換えると、構造体の先頭を0番地としたときに、そのフィールドの先頭までに何バイトあるかという数です。`unsafe.Offsetof` が返すのもこの数です。

Goのソース上では `req.Method` のようにフィールド名でアクセスできますが、外部から見るeBPFにその名前は見えません。コンパイル済みバイナリの実行中メモリにあるのは、基本的にバイト列とアドレスだけです。したがって外部から読む側は、「`http.Request` の先頭アドレスに56を足した位置に `Header` がある」というように、バイト単位の位置を知っていなければなりません。

### 自分のGoとOBIの表の突き合わせ

このオフセットは、Goからも `unsafe.Offsetof` で取り出せます。

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
go1.26.0
Method        = 0
URL           = 16
Header        = 56
ContentLength = 88
```

この4つの数値は、OBIが持っているオフセット表 `pkg/internal/goexec/offsets.json` の中身と一致します。

```json
"net/http.Request": {
  "Method":        { "versions": {"oldest": "1.17.0", "newest": "1.26.4"},
                     "offsets": [{"offset": 0,  "since": "1.17.0"}] },
  "URL":           { "versions": {"oldest": "1.17.0", "newest": "1.26.4"},
                     "offsets": [{"offset": 16, "since": "1.17.0"}] },
  "Header":        { "versions": {"oldest": "1.17.0", "newest": "1.26.4"},
                     "offsets": [{"offset": 56, "since": "1.17.0"}] },
  "ContentLength": { "versions": {"oldest": "1.17.0", "newest": "1.26.4"},
                     "offsets": [{"offset": 88, "since": "1.17.0"}] }
}
```

`versions` が「このエントリが何から何までのバージョンで検証済みか」、`offsets` が「いつからその位置になったか」です。

手元のGoで印字した値と、OBIが事前に用意した表の値は同じです。外から構造体を読むというのは、要するにこの表を信じて `+56` バイト目を読むということです。

`net/http.Request` は運のいい例で、`offsets` の配列が要素1つしかありません。Go 1.17から1.26までのあいだ、一度も動いていません。

### フィールドが1つ増えたときのずれ

構造体の途中にフィールドを1つ足して、前後を比べます。

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

追加したフィールドより後ろにあるものが、まとめてずれました。なぜこの数になるのかを、バイトの並びで見ておきます。`any` は型へのポインタとデータへのポインタの2つで16バイト、`func()` はポインタ1つで8バイト、`string` はポインタと長さで16バイトです。`uint32` は4バイトですが、次の16バイト境界まで詰め物が入ります。

![フィールドを1つ足すと後ろがずれる](/images/20260820-struct-byte-band.png)
*図24: 矢印はフィールドを1つ足したという変更を表す。詰め物の位置と大きさも変わるので、後ろのフィールドは足した分と同じ8バイトだけずれる。*

`method` の位置に24をハードコードしていたコードは、`v2` に対しては `id` と詰め物をまたいだ中途半端な位置を読みます。

### 予告なく変わるオフセット

いま作ってみせた `streamV1` と `streamV2` は、架空の例ではありません。gRPCの `internal/transport.Stream` は、OBIがメソッド名を取り出すために読んでいる構造体で、`method` の位置は実際に4回動いています。

| gRPCのバージョン | `Stream.method` のオフセット |
|---|---|
| 1.40.0 以降 | 80 |
| 1.66.0 以降 | 88 |
| 1.69.0 以降 | 24 |
| 1.77.0 以降 | 16 |

内部パッケージ `internal/transport` の型なので、互換性の約束は及びません。Goでは `internal` を含むパスのパッケージを外部から参照できず、この型はライブラリの利用者に見せるものではありません。だから開発者は、更新のときにフィールドの並びを自由に変えられます。その自由さの代償を、メモリ位置で外から読むOBIが引き受けています。同じ表の中では `golang.org/x/net/http2.ClientConn.fr` がさらに動いていて、その回数は8回にのぼります。`offsets.json` 全体では70個の構造体を追跡しており、そのうち42個のフィールドが「過去に一度以上動いた」記録を持っています。

![バージョン間でオフセットがずれる](/images/20260820-offset-shift.png)
*図25: 矢印は計装コードがどの位置を読むかを表す。ハードコードした `+88` は grpc 1.66 では `method` を指すが、1.69 では別のフィールドを指す。クラッシュせずに「それらしく動いてしまう」のが最悪の結果になる。*

仮にオフセットをコードにハードコードすると、あるバージョンでは完璧に動きますが、ユーザーが依存ライブラリを上げてビルドし直したアプリに対して使うと、見当違いの位置を読みます。最悪なのは、**クラッシュせずに「それらしく動いてしまう」**ことです。トレースは出るのに、中身が誤っています。オブザーバビリティツールとして、観測対象への信頼を最も損なう挙動です。

### DWARFを先に読み、欠けた分を表で補う

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

最初に試すのは、計装対象のバイナリ自身に埋め込まれたDWARF（型とフィールド位置を含むデバッグ情報）です。ELFバイナリの中身の節で挙げた `.debug_*` がそれです。

DWARFが正解を持っているのは、コンパイラがデバッガのために「この型のこのフィールドは先頭から何バイト目か」を書き残しているからです。デバッガが `req.Method` を名前で表示できるのも同じ情報のおかげです。したがってDWARFを読めるかぎり、OBIは目の前のバイナリに合った値を得られます。バージョン追従の問題はありません。

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

この抜粋の末尾にある `IoWriterBufPtrPos`、`IoWriterNPos`、`IoWriterWrPos` の3つは、`bufio.Writer` の `buf`、`n`、`wr` に対応します。標準ライブラリの非公開フィールドがオフセット追従の対象に入っているわけですが、これが何のために要るのかは4つ目の難所で分かります。

### バイナリから版を割り出す

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
./myapp: go1.26.0
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

`go.sum` に並んでいるのと同じハッシュです。バージョン文字列だけでなく中身の同一性まで確認したうえで、その版に固有の処理を有効にしています。

![オフセットを2つの情報源から集める](/images/20260820-offset-resolution.png)
*図26: 矢印は処理の流れで、上から下へ進む。DWARFから読めたフィールドはそのまま使い、読めなかったフィールドだけを `offsets.json` で補う。両者は合流して1つのオフセット表になる。表から補う分だけが、バイナリの版に依存する。*

3つ目の難所への対処は、壊れやすさをなくすことではありません。バイナリ自身に書いてある分はそれを読み、書いていない分だけを自動更新される表で補います。ここで残るのは1文です。フィールドの位置はDWARFから読み、読めなかった分だけ版ごとの表から補う。壊れやすさを仕組みで吸収し続けることに行き着きます。

---

## 4つ目の難所：プロセスをまたぐコンテキスト伝搬

ここまでで、1つのプロセス内の話は扱えるようになりました。最後に残るのは、プロセスをまたぐ**コンテキスト伝搬**です。

分散トレースと traceparent の節で見たとおり、サービスAの処理とサービスBの処理は、同じトレースIDを持たせることで1本のトレースになります。通常これは、HTTPリクエストに `traceparent` ヘッダを付けて、トレースIDと自分のスパンIDを下流へ渡すことで実現します。下流はそのスパンIDを親として、新しいスパンで処理を続けます。

### SDK計装での1行

普通のGo開発者が書く計装は、次の数行で済みます。OpenTelemetryのSDKを使うなら、HTTPクライアントのTransportを差し替えるだけです。

```go
client := &http.Client{
	Transport: otelhttp.NewTransport(http.DefaultTransport),
}
```

この内側で起きているのは、実質的には次の1行です。

```go
otel.GetTextMapPropagator().Inject(ctx, propagation.HeaderCarrier(req.Header))
```

`ctx` が持っているトレースIDとスパンIDを `traceparent` の形式に整えて、`req.Header` に書き込みます。アプリが `ctx` と `req` の両方を手元に持っているから書ける1行です。

ゼロコード計装では、この1行を外から代行しなければなりません。アプリは `traceparent` の存在すら知らないので、誰かが代わりに書き込む必要があります。課題は2つに分かれます。`ctx` にあたるものを外からどう再現するかと、`req.Header` にどう書き込むかです。

![誰が traceparent を書き込むのか](/images/20260820-sdk-vs-zerocode.png)
*図27: 矢印は誰がヘッダに書き込むかを表す。SDK計装ではアプリ自身が書き、ゼロコード計装では外にいるOBIが代わりに書く。*

### goroutineをまたいだ追跡

1プロセス内でも、処理はgoroutineをまたいで流れます。受信を担当するgoroutineと、下流へ送信するgoroutineが別であることは珍しくありません。`context.Context` を引数で引き回すのがGoの流儀です。

ここで、2つ目の難所と食い違うように見える話をしておきます。あちらでは「レジスタから引数を読める」と書きました。それなら `ctx` も読めるはずですが、話が別なのは、この2つが違う作業だからです。

レジスタを読むのは、uprobeが発火したその瞬間に、決まった場所にある値を1つ取り出す作業です。一方で `ctx` を役立てるには、値が関数からgoroutineへ渡っていくあいだ、それが同じ処理の文脈だと分かり続けなければなりません。`ctx` はインターフェース値なので、レジスタにあるのは中身そのものではなく、別の場所にあるオブジェクトへの参照です。中身の構造は `context.WithValue` の入れ子で変わり、引数の位置も関数ごとに違います。一度ポインタを読めば追跡できる、という性質のものではありません。

OSスレッドとgoroutineの節で見たとおり、カーネルが知っているのはスレッドまでです。スレッドIDを見れば同じ処理だと分かる、という話にもなりません。同じOSスレッド上で別リクエストのgoroutineが動くこともあれば、同一リクエストの処理が別goroutineへ引き継がれることもあります。

そこでOBIは、`ctx` の値を解読することをやめ、goroutineの生成関係を代わりの手がかりにします。

![レジスタは読めるが、文脈は追えない](/images/20260820-context-not-traceable.png)
*図28: 矢印はOBIにできることとできないことを表す。丸で止まっている破線が、できないほうである。点線はその理由を並べたもので、処理の流れではない。*

OBIがフックを置くのは、goroutineの生成そのものです。`go f()` と書いたときに最終的に呼ばれるランタイム関数が `runtime.newproc1` で、その簡略化したシグネチャは次のようになっています。

```go
// 新しい goroutine を作って返す。callergp は作成元の goroutine
func newproc1(fn *funcval, callergp *g, callerpc uintptr, parked bool, waitreason waitReason) *g
```

第2引数が作成元のgoroutine、戻り値が新しく作られたgoroutineです。だからOBIは、入口と出口の両方を捕まえます。やることは次の2行に尽きます。

```text
goroutineを作り始めたとき:
    作成元goroutineを一時保存する

goroutineを作り終えたとき:
    戻り値から新しいgoroutineを得る
    新しいgoroutine -> 親goroutine をマップへ保存する
```

以下のコードは、この2行に対応する部分だけを追えば足ります。

```c
SEC("uprobe/runtime_newproc1")
int obi_uprobe_runtime_newproc1(struct pt_regs *ctx) {
    void *creator_goroutine_addr = GOROUTINE_PTR(ctx);

    new_func_invocation_t invocation = {.parent = (u64)GO_PARAM2(ctx)};
    go_addr_key_t g_key = {};
    go_addr_key_from_id(&g_key, creator_goroutine_addr);

    // Save the registers on invocation to be able to fetch the arguments at return of newproc1
    if (bpf_map_update_elem(&newproc1, &g_key, &invocation, BPF_ANY)) {
        bpf_dbg_printk("can't update map element");
    }

    return 0;
}
```

入口では、第2引数（`GO_PARAM2`、つまり `BX`）に入っている親goroutineを控えておきます。新しいgoroutineはまだ存在しないので、この時点では記録できません。

```c
// 出口のフック。骨格だけを抜き出したもの
int obi_uprobe_runtime_newproc1_return(struct pt_regs *ctx) {
    void *creator_goroutine_addr = GOROUTINE_PTR(ctx);      // 呼び出した側のgoroutine
    void *goroutine_addr = (void *)GO_PARAM1(ctx);          // 戻り値。新しいgoroutine

    // 入口で控えておいた親を取り出す
    new_func_invocation_t *invocation = bpf_map_lookup_elem(&newproc1, &c_key);
    void *parent_goroutine = (void *)invocation->parent;

    // 「子 -> 親」をマップに記録する
    goroutine_metadata metadata = {.timestamp = bpf_ktime_get_ns(), .parent = p_key};
    bpf_map_update_elem(&ongoing_goroutines, &g_key, &metadata, BPF_ANY);
    return 0;
}
```

戻りでは、戻り値（`GO_PARAM1`、つまり `AX`）に新しい `g` のアドレスが入っています。入口で控えた親と組にして、`ongoing_goroutines` マップに親子関係を記録します。これで「このgoroutineは、あのリクエストを処理しているgoroutineの子だ」と辿れるようになります。

![newproc1 の入口と出口で親子を記録する](/images/20260820-newproc1-map.png)
*図29: 矢印は時間の前後を表す。入口では親しか分からないので一時的に控え、出口で新しいgoroutineのアドレスが判明してから、親子の組として記録する。*

:::details 実装の全文（PIDの組み立て、循環の回避、古いエントリの削除を含む）
```c
SEC("uprobe/runtime_newproc1_return")
int obi_uprobe_runtime_newproc1_return(struct pt_regs *ctx) {
    bpf_dbg_printk("=== uprobe/runtime_newproc1_return ===");
    void *creator_goroutine_addr = GOROUTINE_PTR(ctx);
    const u64 pid_tid = bpf_get_current_pid_tgid();
    const u32 pid = pid_from_pid_tgid(pid_tid);
    go_addr_key_t c_key = {.addr = (u64)creator_goroutine_addr, .pid = pid};

    // The result of newproc1 is the new goroutine
    void *goroutine_addr = (void *)GO_PARAM1(ctx);
    go_addr_key_t g_key = {.addr = (u64)goroutine_addr, .pid = pid};

    // Lookup the newproc1 invocation metadata
    new_func_invocation_t *invocation = bpf_map_lookup_elem(&newproc1, &c_key);
    if (invocation == NULL) {
        bpf_dbg_printk("can't read newproc1 invocation metadata");
        goto done;
    }

    // The parent goroutine is the second argument of newproc1
    void *parent_goroutine = (void *)invocation->parent;
    go_addr_key_t p_key = {.addr = (u64)parent_goroutine, .pid = pid};

    goroutine_metadata *g_metadata =
        (goroutine_metadata *)bpf_map_lookup_elem(&ongoing_goroutines, &p_key);

    if (g_metadata) {
        // Don't create cycles at one level on immediate goroutine reuse
        if (g_metadata->parent.addr == (u64)goroutine_addr) {
            bpf_dbg_printk("avoiding cycle %llx -> %llx", parent_goroutine, goroutine_addr);
            goto done;
        }
    }

    goroutine_metadata metadata = {
        .timestamp = bpf_ktime_get_ns(),
        .parent = p_key,
    };

    if (bpf_map_update_elem(&ongoing_goroutines, &g_key, &metadata, BPF_ANY)) {
        bpf_dbg_printk("can't update active goroutine");
    }

done:
    // Delete any stale info on go_trace_map
    bpf_map_delete_elem(&go_trace_map, &g_key);
    bpf_map_delete_elem(&newproc1, &c_key);

    return 0;
}
```
:::

全文の途中にある `Don't create cycles at one level on immediate goroutine reuse` という分岐は、2つ目の難所で選んだ識別子の代償です。`g` 構造体のアドレスを識別子にするということは、goroutineが終了して `g` が再利用されたとき、同じアドレスが別のgoroutineとして戻ってくるということでもあります。親として記録したアドレスが、そのまま子として現れる状況がありえます。放置すれば親子関係が輪になり、次の節で見る遡りが無限に回ります。最後の `done:` ラベルで `go_trace_map` の古いエントリを消しているのも同じ理由で、再利用されたアドレスに前の持ち主の情報が残らないようにしています。

通し番号ではなくアドレスを使うと、バージョン追従からは解放される代わりに、寿命の管理が自分の仕事になります。どちらを選んでも何かは引き受けることになります。

名前に `_return` と付いていますが、これはuretprobeではありません。1つ目の難所で見たとおり、`runtime.newproc1` を逆アセンブルして全 `RET` を洗い出し、その一つひとつに通常のuprobeを置いています。入口と出口をペアで使うという当たり前のことをするために、あの回りくどい手順が要ります。1つ目の難所の回避策が、ここで使われています。

### 遡れるのは6段まで

記録した親子関係は、リクエストの起点にあたるgoroutineが見つかるまで遡ります。やることは、マップを1段ずつ引いて「この親はトレースを持っているか」を確かめる繰り返しです。

:::details 遡りのコード（find_parent_goroutine）
```c
static __always_inline u64 find_parent_goroutine(go_addr_key_t *current) {
    // ...
    int attempts = 0;
    do {
        tp_info_t *p_inv = bpf_map_lookup_elem(&go_trace_map, parent);
        if (!p_inv) { // not this goroutine running the server request processing
            // Let's find the parent scope
            goroutine_metadata *g_metadata =
                (goroutine_metadata *)bpf_map_lookup_elem(&ongoing_goroutines, parent);
            if (g_metadata) {
                // Lookup now to see if the parent was a request
                // Debug here commented out on purpose to avoid prints in loops.
                // bpf_printk("lookup %llx -> %llx", r_addr, g_metadata->parent.addr);
                r_addr = g_metadata->parent.addr;
                parent = &g_metadata->parent;
            } else {
                break;
            }
        } else {
            bpf_dbg_printk("Found parent, r_addr=%lx", r_addr);
            return r_addr;
        }

        attempts++;
        // We loop far back because some clients, e.g. Kafka Franz-Go really nest the
        // client calls.
    } while (attempts < 6); // Up to 6 levels of goroutine nesting allowed

    return 0;
}
```
:::

ループの中でコメントアウトされている `bpf_printk` に、`Debug here commented out on purpose to avoid prints in loops.` と理由が添えられています。デバッグ出力1行の重さすら気にする場所だということです。

上限が決め打ちされているのは、実装の手抜きではありません。検証器が課す制約の節で見たとおり、検証器はループの回数に上界がなければプログラムをロードしません。「親が見つかるまで辿る」と素直に書くことはできず、「何回まで辿る」と書くしかありません。

ただし、6という数字そのものは安全性から導かれた値ではありません。上界がありさえすれば検証器は通るので、6は「命令数の重さと、実際のライブラリで必要な深さ」を見て決めた実装上の選択です。その根拠もコメントに残っています。Kafkaクライアントの franz-go が深くネストするから、というものです。

漏れたときに何が起きるかも押さえておきます。トレース情報を持つ祖先までの距離が6段を超えると、`find_parent_goroutine` は0を返します。このとき送信側の処理は計装されないのではなく、`client_trace_parent` が新しいトレースIDを乱数で作ります。つまり下流のリクエストは、上流とつながらない別のトレースとして記録されます。トレースが消えるより厄介で、1本のはずの流れが2本に見えます。

![親を6段まで遡る](/images/20260820-parent-walk.png)
*図30: 矢印は子から親への参照をたどる向きを表す。上界が必要なのは検証器の制約だが、6という値は実装上の選択である。打ち切られた送信処理は計装されないのではなく、新しいトレースIDを振られて別のトレースになる。*

### 送信リクエストへのヘッダ注入

追跡できたトレースコンテキストを、実際に送信するHTTPリクエストへ書き込みます。

素直に考えれば、書き込み先は `http.Request` の `Header` フィールドです。しかしOBIはそこを狙いません。`http.Header` は `map[string][]string` なので、外部から新しいキーを追加するには、対象プロセスの中でmapの内部構造を操作しなければなりません。キーのハッシュを計算し、バケットを探し、必要なら領域の拡張まで外から代行することになります。無理があります。

OBIが狙うのは、リクエストがバイト列に直列化される直前です。ここで、送信直前のHTTP/1.1リクエストが実際にどんなバイト列なのかを見ておきます。

```http
GET /items HTTP/1.1
Host: service-b
Traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01

```

ヘッダは1行1つで、行の区切りは `\r\n`、空行が来たらヘッダの終わりです。`traceparent` を足すというのは、この文字列の途中に1行を挿し込むことにほかなりません。

`net/http` はヘッダを書き出すときに `Header.writeSubset` を通り、その先の `bufio.Writer` のバッファに、いま見たような文字列を積んでいきます。`bufio.Writer` は書き込みをためておくための入れ物で、`buf` がバイト列の置き場、`n` が「そのうち何バイトまで使っているか」を持ちます。OBIはこの関数の入口と戻りの両方にフックを置き、戻りのほうで、ためられた文字列の末尾に1行を書き足します。プローブの登録はGo側の `pkg/internal/ebpf/gotracer/gotracer.go` にあります。

![traceparent をどこへ書き込むか](/images/20260820-header-injection.png)
*図31: 縦に並ぶ矢印は書き出しの経路、OBIから伸びる矢印は書き込み先を表し、丸印の付いた破線は書き込めない相手を指す。`http.Header` のmapには外から書き込めないため、直列化の直前にある `bufio.Writer` のバッファへ `Traceparent` を書き、`n` を進める。*

```go
	if p.headerPropagationEnabled() {
		m["net/http.Header.writeSubset"] = []*ebpfcommon.ProbeDesc{{
			Start: p.bpfObjects.ObiUprobeWriteSubset,        // http 1.x context propagation
			End:   p.bpfObjects.ObiUprobeWriteSubsetReturns, // inject only if no traceparent present
		}}
		m["golang.org/x/net/http2.(*Framer).WriteHeaders"] = []*ebpfcommon.ProbeDesc{
			{ // http2 context propagation
				Start: p.bpfObjects.ObiUprobeGolangHttp2FramerWriteHeaders,
				End:   p.bpfObjects.ObiUprobeHttp2FramerWriteHeadersReturns,
			},
```

キーが計装対象のシンボル名、`Start` が入口、`End` が出口のeBPFプログラムです。この `End` が指定されていると、1つ目の難所で見た「全 `RET` を洗い出して一つひとつにuprobeを置く」処理が走ります。

戻りのフックがすることは、`bufio.Writer` のバッファの末尾に直接書き足すことです。

```c
    unsigned char buf[k_traceparent_len];
    make_tp_string(buf, &inv->tp);

    if (len <
        (size - TP_MAX_VAL_LENGTH - TP_MAX_KEY_LENGTH - 4)) { // 4 = strlen(":_")+strlen("\r\n")
        char key[TP_MAX_KEY_LENGTH + 2] = "Traceparent: ";
        char end[2] = "\r\n";
        bpf_probe_write_user(buf_ptr + (len & 0x0ffff), key, sizeof(key));
        len += TP_MAX_KEY_LENGTH + 2;
        bpf_probe_write_user(buf_ptr + (len & 0x0ffff), buf, sizeof(buf));
        len += TP_MAX_VAL_LENGTH;
        bpf_probe_write_user(buf_ptr + (len & 0x0ffff), end, sizeof(end));
        len += 2;
        bpf_probe_write_user((void *)(io_writer_addr + io_writer_n_pos), &len, sizeof(len));
```

`bpf_probe_write_user` は、対象プロセスのユーザー空間メモリを書き換えるeBPFのヘルパーです。`Traceparent: `、値、`\r\n` の3回でバッファに文字列を積み、4回目で `bufio.Writer` の `n` を書き換えています。`n` を増やさなければ、書き足したバイトはバッファの使用範囲の外に置かれたままで、送信されません。逆に言えば、この4回目の書き込みが「1行足した」ことをGoのコードに認めさせている部分です。

3つ目の難所で見た `offsets.json` に `bufio.Writer` の `buf`、`n`、`wr` が入っているのは、このためです。Goの標準ライブラリの非公開フィールドを、外から書き換えています。`io_writer_n_pos` という変数名が、そのオフセットを指しています。

![HTTPのバイト列と、traceparent を差し込む2つの位置](/images/20260820-http-bytes-injection.png)
*図32: 矢印は書き込みの向きと、バイト列が出ていく向きを表す。経路1はアプリのメモリにあるバッファへ書き、経路2はソケットへ出ていくバイト列に差し込む。どちらも足すのは同じ1行である。*

### 書き込みが許されない環境と、もう一つの経路

`bpf_probe_write_user` は、OSのセキュリティ機構と衝突します。OBIのサポートマトリクスには、次のように書かれています。

> On Linux 5.10 and later, OBI requires effective `CAP_SYS_ADMIN` and kernel lockdown mode `[none]` to use `bpf_probe_write_user`.

kernel lockdownが有効な環境やSecure Bootの下では、このヘルパーが使えません。コード側にも `g_bpf_probe_write_user_enabled` というフラグがあり、使えない環境では上記の処理ごと素通りします。

ただし、そこでコンテキスト伝搬が消えるわけではありません。OBIには第2の経路があります。同じ関数のすぐ下にあるコメントが、それを説明しています。

```c
        // For Go we support two types of HTTP context propagation for now.
        //   1. The one that this code does, which uses the locked down bpf_probe_write_user.
        //   2. By using a sock_msg program that will extend the packet.
        // If this code ran, we should ensure that the second part doesn't run, therefore
        // we remove the metadata setup in uprobe_persistConnRoundTrip(struct pt_regs *ctx), so
        // that approach 2. skips this packet.
```

2つ目は `sk_msg` プログラムです。これは、アプリのメモリではなく、カーネルがソケットへ送り出すデータを扱う位置で動くeBPFプログラムの種類で、送信されるバイト列を伸ばしてヘッダを差し込めます。アプリのメモリには触りません。

ここで扱っている単位は、TCPが運ぶバイトの列です。どこで区切ってパケットにするかはカーネルが決めるので、「HTTPの1リクエストが1パケット」とはかぎりません。`sk_msg` が差し込むのは、その区切りが決まる前のバイト列に対してです。

1つ目が動いたときは、同じヘッダが二重に入らないよう、2つ目が対象を飛ばすようにマップの登録を消しています。2つの経路が同じ送信に対して走らないための調停が要るわけです。

なお、コンテキスト伝搬は既定では無効です。`OTEL_EBPF_BPF_CONTEXT_PROPAGATION` の既定値は `disabled` で、`headers`、`tcp`、`all` から明示的に選びます。プロセスのメモリを書き換える、あるいは送信されるバイト列を書き換える機能である以上、有効化は利用者の判断に委ねられています。

4つ目の難所で残るのは2文です。goroutineの生成にフックを置いて親子関係をマップに記録し、送信の直前にその関係を6段まで遡ってトレースを見つける。見つけたトレースIDは、直列化直前のバッファか、ソケットへ出ていくバイト列のどちらかに書き足す。

![goroutine の親子追跡と traceparent 注入](/images/20260820-context-propagation.png)
*図33: 実線の矢印は処理の流れ、破線は無効化を表す。goroutine の親子追跡（プロセス内）と traceparent 注入（プロセス間）を示している。追跡は6段まで、注入は2経路あり、カーネルのセキュリティ機構が有効だと経路1だけが落ちる。*

---

## 観測される側のGo開発者が知っておくこと

ここまではOBIを書く側の話でした。多くのGo開発者にとって現実的なのは、自分のアプリが観測される側に立つ場面です。どこまで計装されるかは、どのようにビルドしたバイナリかで決まります。4つの難所の内訳が分かっていれば、その線引きは自分で説明できます。

### Go 1.17以降でビルドされていること

OBIのサポートマトリクスは、ライブラリレベルの計装について `Go 1.17+` と明記しています。ABIInternal（Go関数が引数を受け渡す内部規約）に切り替わった版が境目です。`offsets.json` に載っている標準ライブラリのエントリも、すべて `oldest` が `1.17.0` です。

2つ目の難所で見たレジスタABIが、まさにGo 1.17の変更でした。それ以前のスタック渡しのバイナリに対応するには、別の読み取り経路を丸ごと持つ必要があります。Go 1.17は2021年8月のリリースなので、実務でこれが問題になることはほぼありません。

### シンボルを落としたバイナリで何が起きるか

配布サイズを削るために `-ldflags="-s -w"` を付けるのは、よくあるビルド設定です。ELFバイナリの中身の節で挙げたセクションのうち、どれが落ちてどれが残るかを実際に確かめます。

```
$ go build -o app main.go
$ go build -ldflags="-s -w" -o app_stripped main.go

$ ls -l app app_stripped | awk '{print $5, $9}'
2396845 app
1589410 app_stripped

$ readelf -S app         | grep -c debug_    # DWARFセクションの数
8
$ readelf -S app_stripped | grep -c debug_
0

$ go tool nm app_stripped
reading app_stripped: no symbol section

$ readelf -S app_stripped | grep -o gopclntab
gopclntab
```

DWARF（型とフィールドの位置を含むデバッグ情報）とシンボルテーブルは消えましたが、`.gopclntab`（命令アドレスからGoの関数名を引く表）は残っています。Goランタイム自身がパニック時のスタックトレースを組み立てるために必要とするので、`-s -w` では落ちません。ビルド情報のブロブも同様に残り、`go version -m` は引き続き動きます。

関数のアドレスは、これでも引き続き特定できます。`go tool nm` や `go tool objdump` はシンボルテーブルが無いと動きませんが、OBIはそれらに依存していません。`pkg/internal/goexec/instructions.go` は `.gopclntab` を自前で解析します。`runtime.moduledata` にはシンボルも固定アドレスも無いため、そのコメントによれば「`.gopclntab` を指す8バイト境界の値をバイナリ中から探し、周囲のデータがmoduledataの並びに合致するかを確認する」という探し方をしています。シンボルが無くても関数の位置は割り出せる、という作りになっています。

変わるのはオフセットの解決経路です。3つ目の難所で見たとおり、OBIはまずバイナリのDWARFからフィールドオフセットを読もうとします。`-w` でDWARFを落とすと、読める分がゼロになるので、全項目を `offsets.json` の表から引くことになります。つまり「目の前のバイナリに書いてある正解を読む」状態から「事前に用意された表が自分のバージョンを網羅していることを期待する」状態へ移ります。表に載っていないバージョンのライブラリを使っていれば、その項目の計装は静かに欠けます。

DWARFを残しておくと計装は堅くなります。`-w` を付けるかどうかは、配布サイズと計装の確実性のどちらを取るかという判断になります。

![ビルド設定と計装の関係](/images/20260820-build-flags.png)
*図34: 矢印は、バイナリに何が残るかが計装のどこに影響するかを表す（原因から結果へ）。`-s -w` を付けるとDWARFとシンボルテーブルが落ちる。`.gopclntab` は残るので関数のアドレスは特定できるが、オフセットの解決は `offsets.json` 頼みになる。*

### インライン展開で消える計装点

uprobeは命令アドレスに置くものなので、対象の関数がインライン展開されて呼び出しごと消えていれば、置く場所がありません。小さなアクセサやラッパーほど、計装からは見えなくなります。

![インライン展開で消える計装点](/images/20260820-inlining.png)
*図35: 矢印は変換の向きを表す。インライン展開は呼び出しの命令そのものを消すので、フックを置くアドレスがなくなる。*

OBIが計装点として選んでいるのは `net/http.(*conn).serve` や `google.golang.org/grpc.(*Server).handleStream` といった、インライン展開の対象にならない大きさの関数です。とはいえ、自分でeBPFツールを書いて特定の関数を狙うときには、`-gcflags=-m` でインライン化の有無を確認する価値があります。

### 使っているライブラリのバージョン

3つ目の難所の裏返しとして、依存ライブラリのバージョンが計装の可否を左右します。gRPCを最新に上げた直後にメソッド名が取れなくなったなら、それはアプリの問題ではなく、`offsets.json` の追従が間に合っていない可能性があります。

トレースが出ないときの切り分けは、おおむね次の順序になります。

- プロセスが検出されているか
- 検出されているなら、関数のアドレスが解決できているか
- 解決できているなら、読んだフィールドの値が妥当か

最後の段階まで来て値がおかしいなら、オフセットの追従漏れを疑うことになります。

---

## Go本体はこの問題にどう向き合っているか

ここまで見た4つの難所は、いずれもGoの外部から内部を覗き込むことの困難でした。

### eBPF計装への直接支援

結論として、eBPF計装を直接助ける機能はGo本体にほぼ入っていません。1つ目の難所であるuretprobe問題（[#22008](https://github.com/golang/go/issues/22008)）は2017年から提起されていますが、長く「Unplanned」のまま棚上げされています。goroutineの起動にフックを差せるようにする提案（[#73798](https://github.com/golang/go/issues/73798)）は、2025年に「not planned」でクローズされました。

Goチームの姿勢は一貫しています。**ランタイムの内部構造は公開APIではなく、外部から依存すべきでない**というものです。eBPF計装はまさにその非公開な内部に依存しているため、支援は得にくい状況です。3つ目の難所で見たオフセット追従のコストは、この設計思想の裏返しでもあります。

`goid` を公開しないという判断も、同じ線の上にあります。2つ目の難所でOBIが `g` のアドレスを識別子に選んだのは、公開されない値を無理に読むより、読まずに済ませるほうが壊れにくいという判断でした。外部ツール側が「読まない設計」に寄せることで折り合いをつけている、と言ってもいいでしょう。

### 「内からの」オブザーバビリティの進化

ただし、Goがオブザーバビリティに無関心なわけではありません。むしろ「内からの」オブザーバビリティは着実に進化しています。

- **Flight recording**（[#63185](https://github.com/golang/go/issues/63185)、Go 1.25で `runtime/trace.FlightRecorder` として実装）：直近の実行トレースをリングバッファに保持し、問題が起きた瞬間にその手前を取り出せる。
- **goroutine leak profile**：Go 1.26の `runtime/pprof` に `goroutineleak` という名前で追加された、到達不能になってブロックし続けるgoroutineのプロファイル。
- **Compile-Time Instrumentation SIG**（2025年1月発足）：eBPFとは別のやり方として、コンパイル時に計装コードを埋め込む取り組み。

要するに、eBPFは「外から」観測し、Goは「内から」の観測手段を増やしています。外からの観測は、アプリを変更せずに済む反面、ランタイムの内部構造を追いかけ続ける宿命を負います。内からの観測は、正確で壊れにくい反面、コードやビルドへの関与を必要とします。

![外からの観測と内からの観測](/images/20260820-outside-inside.png)
*図36: 矢印は観測する側から観測される側へ向かう。ラベルはそれぞれのやり方の利点とコストを示す。*

---

## おわりに

4つの難所を、衝突するGoの性質とOBIの対処で並べます。

| 難所 | 衝突するGoの性質 | OBIの対処 |
|---|---|---|
| 1. uretprobeが使えない | 可動スタック | 全 `RET` 命令への通常uprobe |
| 2. レジスタABI | ABIInternal（引数の受け渡し規約、Go 1.17〜） | アーキテクチャ別のレジスタ対応表。goroutineは `g` のアドレスで識別し、中身は読まない |
| 3. バージョン依存オフセット | 非公開なランタイム内部構造 | バイナリのDWARFを読み、欠けた分だけ自動更新される `offsets.json` で補う |
| 4. コンテキスト伝搬 | goroutine（≠スレッド） | `newproc1` での親子追跡（6段まで）と、`bufio.Writer` への直接書き込みまたは `sk_msg` |

これら4つはばらばらに生じた問題ではなく、すべて「Goらしさ」の裏返しです。動くスタック、独自のレジスタABI、非公開なランタイム内部構造、そしてgoroutineです。Goを高速で書きやすくしている設計が、そのまま外部から覗く側の障害になっています。

この知識は、自分でeBPFツールを書く人だけのものではありません。Goでアプリを書く立場でも、これらの難所を知っておくと、なぜ自分のアプリはゼロコード計装でトレースが取れたり取れなかったりするのか、どのGoバージョンやビルド形態を選べば計装が安定するのかを、自分で説明できるようになります。DWARFを落とすかどうかがオフセット解決の経路を変える、という話がその一例でした。

冒頭の「言語を問わず動く」という宣伝文句に戻りましょう。プロトコルを解釈する汎用の経路にかぎれば、その一文は誇張ではありません。しかしGoの関数まで踏み込んだ経路の裏では、全 `RET` 命令の走査、レジスタの直読み、DWARFとオフセット表の二段構え、そして `bufio.Writer` のバッファへの書き込みが動いています。それでも「コードを変えずに観測できる」体験が成り立っているのは、難所の一つひとつに対処し続ける実装があるからです。

外からの観測と内からの観測の分担がどこに落ち着くのかは、まだ動いている最中です。

---

## 参考リンク

### OBI

- OpenTelemetry eBPF Instrumentation（OBI）: <https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation>
- OBI 分散トレースのドキュメント: <https://opentelemetry.io/docs/zero-code/obi/distributed-traces/>
- サポート状況の一覧（`SUPPORT_MATRIX.md`）: <https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/main/SUPPORT_MATRIX.md>
- コンテキスト伝搬の設計メモ（`devdocs/context-propagation.md`）: <https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/main/devdocs/context-propagation.md>

本記事で引用したソースの位置は次のとおりです。

| 内容 | ファイル |
|---|---|
| `RET` 命令の探索 | `pkg/internal/goexec/instructions_amd64.go` |
| ELFの解析とmoduledataの探索 | `pkg/internal/goexec/instructions.go` |
| uprobeのアタッチ | `pkg/ebpf/instrumenter.go` |
| 引数レジスタと `g` ポインタのマクロ | `bpf/bpfcore/utils.h` |
| goroutineの識別子 | `bpf/common/go_addr_key.h` |
| goroutineの親子追跡 | `bpf/gotracer/go_runtime.c`、`bpf/gotracer/go_common.h` |
| ヘッダ注入 | `bpf/gotracer/go_nethttp.c` |
| オフセットの解決とビルド情報の読み取り | `pkg/internal/goexec/structmembers.go`、`pkg/internal/goexec/gofile.go` |
| オフセット表 | `pkg/internal/goexec/offsets.json` |
| 計装対象シンボルの一覧 | `pkg/internal/ebpf/gotracer/gotracer.go` |

### Go本体

- golang/go#22008 — runtime: ebpf uretprobe support: <https://github.com/golang/go/issues/22008>
- golang/go#27077 — uretprobe関連のクラッシュ議論: <https://github.com/golang/go/issues/27077>
- golang/go#73798 — goroutine起動フックの提案（not planned）: <https://github.com/golang/go/issues/73798>
- golang/go#63185 — runtime/trace flight recorder（Go 1.25）: <https://github.com/golang/go/issues/63185>
- Go 1.17 Release Notes（レジスタベース呼び出し規約）: <https://go.dev/doc/go1.17>
- Go internal ABI 仕様: <https://github.com/golang/go/blob/master/src/cmd/compile/abi-internal.md>

### eBPF

- cilium/ebpf（Goのローダーライブラリ）: <https://github.com/cilium/ebpf>

> 本記事の実行結果は go1.26.0 linux/amd64 で確認したもので、アドレス値のように実行ごとに変わるものを含みます。OBIのコードはリリース `v0.11.0`（2026年8月17日）時点のものです。レジスタ割り当て、フィールドオフセット、ネスト上限といった値は、GoのバージョンやOBIのリリースにより変化しえます。実装の詳細を引用する際は、対象バージョンのソースで再確認してください。
