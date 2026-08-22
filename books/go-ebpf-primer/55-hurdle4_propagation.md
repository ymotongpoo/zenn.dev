---
title: "難所4　プロセスをまたぐコンテキスト伝搬"
---

ここまでで、1つのプロセス内の話は扱えるようになりました。最後に残るのは、プロセスをまたぐ**コンテキスト伝搬**です。これがうまくいかないときの症状は、1本のはずのトレースが、サービスの境界で無関係な2本に千切れて見えることです。

1章で見たとおり、サービスAの処理とサービスBの処理は、同じトレースIDを持たせることで1本のトレースになります。通常これは、HTTPリクエストに `traceparent` ヘッダを付けて、トレースIDと自分のスパンIDを下流へ渡すことで実現します。下流はそのスパンIDを親として、新しいスパンで処理を続けます。

## SDK計装での1行

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
*図1: 矢印は誰がヘッダに書き込むかを表す。SDK計装ではアプリ自身が書き、ゼロコード計装では外にいるOBIが代わりに書く。*

## goroutineをまたいだ追跡

1プロセス内でも、処理はgoroutineをまたいで流れます。受信を担当するgoroutineと、下流へ送信するgoroutineが別であることは珍しくありません。`context.Context` を引数で引き回すのがGoの流儀です。

ここで、難所2と食い違うように見える話をしておきます。あちらでは「レジスタから引数を読める」と書きました。それなら `ctx` も読めるはずですが、話が別なのは、この2つが違う作業だからです。

レジスタを読むのは、uprobeが発火したその瞬間に、決まった場所にある値を1つ取り出す作業です。一方で `ctx` を役立てるには、値が関数からgoroutineへ渡っていくあいだ、それが同じ処理の文脈だと分かり続けなければなりません。`ctx` はインターフェース値なので、レジスタにあるのは中身そのものではなく、別の場所にあるオブジェクトへの参照です。中身の構造は `context.WithValue` の入れ子で変わり、引数の位置も関数ごとに違います。一度ポインタを読めば追跡できる、という性質のものではありません。

6章で見たとおり、カーネルが知っているのはスレッドまでです。スレッドIDを見れば同じ処理だと分かる、という話にもなりません。同じOSスレッド上で別リクエストのgoroutineが動くこともあれば、同一リクエストの処理が別goroutineへ引き継がれることもあります。

そこでOBIは、`ctx` の値を解読することをやめ、goroutineの生成関係を代わりの手がかりにします。

![レジスタは読めるが、文脈は追えない](/images/20260820-context-not-traceable.png)
*図2: 矢印はOBIにできることとできないことを表す。丸で止まっている破線が、できないほうである。点線はその理由を並べたもので、処理の流れではない。*

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
*図3: 矢印は時間の前後を表す。入口では親しか分からないので一時的に控え、出口で新しいgoroutineのアドレスが判明してから、親子の組として記録する。*

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

さきほどの骨格には出てきませんが、実装にはもう1つ分岐があります。

```c
    // Don't create cycles at one level on immediate goroutine reuse
    if (g_metadata->parent.addr == (u64)goroutine_addr) {
        bpf_dbg_printk("avoiding cycle %llx -> %llx", parent_goroutine, goroutine_addr);
        goto done;
    }
```

これは、goroutineの識別子に `g` 構造体のアドレスを使うと決めたこと（難所2）の代償です。アドレスを識別子にするということは、goroutineが終了して `g` が再利用されたとき、同じアドレスが別のgoroutineとして戻ってくるということでもあります。親として記録したアドレスが、そのまま子として現れる状況がありえます。放置すれば親子関係が輪になり、次の節で見る遡りが無限に回ります。

同じ理由で、この関数は最後に古いエントリを消します。

```c
done:
    // Delete any stale info on go_trace_map
    bpf_map_delete_elem(&go_trace_map, &g_key);
    bpf_map_delete_elem(&newproc1, &c_key);
```

再利用されたアドレスに、前の持ち主の情報が残らないようにするためです。

通し番号ではなくアドレスを使うと、バージョン追従からは解放される代わりに、寿命の管理が自分の仕事になります。どちらを選んでも何かは引き受けることになります。

関数名の接尾辞に `_return` と付いていますが、これはuretprobeではありません。難所1で見たとおり、`runtime.newproc1` を逆アセンブルして全 `RET` を洗い出し、その一つひとつに通常のuprobeを置いています。入口と出口をペアで使うという当たり前のことをするために、あの回りくどい手順が要ります。難所1の回避策が、ここで使われています。

## 遡れるのは6段まで

記録した親子関係を実際に使うのは、下流へリクエストを送る側のフックです。`net/http.(*Transport).roundTrip` やgRPCクライアントの入口が発火した時点で、いま動いているgoroutineから親の方向へ順にたどります。探しているのは「この処理はどのサーバー受信から始まったのか」で、それが分かればトレースIDを引き継げます。

たどる先の目印になるのが `go_trace_map` です。OBIはサーバー側の受信もフックしていて、HTTPなら `net/http.serverHandler.ServeHTTP`、gRPCなら `google.golang.org/grpc.(*Server).handleStream` の入口で、受け取ったリクエストのトレース情報を、処理中のgoroutineをキーにしてこのマップへ書き込みます。受信側がするのは書き込みだけで、遡るのは送信側です。

やることは、マップを1段ずつ引いて「このgoroutineはトレースを持っているか」を確かめる繰り返しです。最初に確かめるのは自分自身なので、受信と送信が同じgoroutineで起きていれば1回で当たります。持っていなければ、親子関係のマップから親を引いて、同じことを繰り返します。

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

上限が決め打ちされているのは、実装の手抜きではありません。7章で見たとおり、検証器はループの回数に上界がなければプログラムをロードしません。「親が見つかるまで辿る」と素直に書くことはできず、「何回まで辿る」と書くしかありません。

ただし、6という数字そのものは安全性から導かれた値ではありません。上界がありさえすれば検証器は通るので、6は「命令数の重さと、実際のライブラリで必要な深さ」を見て決めた実装上の選択です。その根拠もコメントに残っています。Kafkaクライアントの franz-go が深くネストするから、というものです。

漏れたときに何が起きるかも押さえておきます。トレース情報を持つ祖先までの距離が6段を超えると、`find_parent_goroutine` は0を返します。このとき送信側の処理は計装されないのではなく、`client_trace_parent` が新しいトレースIDを乱数で作ります。つまり下流のリクエストは、上流とつながらない別のトレースとして記録されます。トレースが消えるより厄介で、1本のはずの流れが2本に見えます。

![親を6段まで遡る](/images/20260820-parent-walk.png)
*図4: 矢印は子から親への参照をたどる向きを表す。上界が必要なのは検証器の制約だが、6という値は実装上の選択である。打ち切られた送信処理は計装されないのではなく、新しいトレースIDを振られて別のトレースになる。*

## 送信リクエストへのヘッダ注入

追跡できたトレースコンテキストを、実際に送信するHTTPリクエストへ書き込みます。

素直に考えれば、書き込み先は `http.Request` の `Header` フィールドです。しかしOBIはそこを狙いません。`http.Header` は `map[string][]string` なので、外部から新しいキーを追加するには、対象プロセスの中でmapの内部構造を操作しなければなりません。キーのハッシュを計算し、バケットを探し、必要なら領域の拡張まで外から代行することになります。無理があります。

OBIが狙うのは、リクエストがバイト列に直列化される直前です。送信直前のHTTP/1.1リクエストがどんなバイト列なのかは、標準ライブラリだけで手元でも確かめられます。

* [Go Playgroundで実行する](https://go.dev/play/p/oo1fSXUKumn)

```go
package main

import (
	"fmt"
	"net/http"
	"net/http/httputil"
)

func main() {
	req, _ := http.NewRequest("GET", "http://service-b/items", nil)
	req.Header.Set("Traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
	dump, _ := httputil.DumpRequestOut(req, false)
	fmt.Printf("%q\n", dump)
}
```

```
"GET /items HTTP/1.1\r\nHost: service-b\r\nUser-Agent: Go-http-client/1.1\r\nTraceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01\r\nAccept-Encoding: gzip\r\n\r\n"
```

HTTP/1.1のリクエストは、ただの1本の文字列です。ヘッダは1行1つで、行の区切りは `\r\n`、空行が来たらヘッダの終わりです。SDK計装が最終的にやっているのは、この `Traceparent: ` の1行を書き足すことです。ゼロコード計装で `traceparent` を足すときも、この文字列の途中に1行を挿し込む点は変わりません。

`net/http` はヘッダを書き出すときに `Header.writeSubset` を通り、その先の `bufio.Writer` のバッファに、いま見たような文字列を積んでいきます。`bufio.Writer` は書き込みをためておくための入れ物で、`buf` がバイト列の置き場、`n` が「そのうち何バイトまで使っているか」を持ちます。OBIはこの関数の入口と戻りの両方にフックを置き、戻りのほうで、ためられた文字列の末尾に1行を書き足します。プローブの登録はGo側の `pkg/internal/ebpf/gotracer/gotracer.go` にあります。

![traceparent をどこへ書き込むか](/images/20260820-header-injection.png)
*図5: 縦に並ぶ矢印は書き出しの経路、OBIから伸びる矢印は書き込み先を表し、丸印の付いた破線は書き込めない相手を指す。`http.Header` のmapには外から書き込めないため、直列化の直前にある `bufio.Writer` のバッファへ `Traceparent` を書き、`n` を進める。*

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

キーが計装対象のシンボル名、`Start` が入口、`End` が出口のeBPFプログラムです。この `End` が指定されていると、難所1で見た「全 `RET` を洗い出して一つひとつにuprobeを置く」処理が走ります。抜粋のコメント `inject only if no traceparent present` のとおり、アプリがSDK計装で自分の `traceparent` をすでに付けている場合、OBIは書き込みません。SDK計装との同居でヘッダが二重になることはありません。

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

`bpf_probe_write_user` は、対象プロセスのユーザー空間メモリを書き換えるeBPFのヘルパーです。`Traceparent: `、値、`\r\n` の3回でバッファに文字列を積み、4回目で `bufio.Writer` の `n` を書き換えています。`n` を増やさなければ、書き足したバイトはバッファの使用範囲の外に置かれたままで、送信されません。逆に言えば、この4回目の書き込みが「1行足した」ことをGoのコードに認めさせている部分です。もうひとつ、コードに3回現れる `(len & 0x0ffff)` は、加算を重ねた `len` が一定範囲に収まることを検証器に示すための書き方です。検証器の制約は、遡りのループの上界だけでなく、こうした添字のひとつひとつにまで及んでいます。

難所3で見た `offsets.json` に `bufio.Writer` の `buf`、`n`、`wr` が入っているのは、このためです。Goの標準ライブラリの非公開フィールドを、外から書き換えています。`io_writer_n_pos` という変数名が、そのオフセットを指しています。

![HTTPのバイト列と、traceparent を差し込む2つの位置](/images/20260820-http-bytes-injection.png)
*図6: 矢印は書き込みの向きと、バイト列が出ていく向きを表す。経路1はアプリのメモリにあるバッファへ書き、経路2はソケットへ出ていくバイト列に差し込む。どちらも足すのは同じ1行である。*

## 書き込みが許されない環境と、もう一つの経路

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

難所4でOBIがしているのは、goroutineの生成にフックを置いて親子関係を記録し、送信の直前に6段まで遡ってトレースIDを見つけ、直列化直前のバッファか、ソケットへ出ていくバイト列にそれを書き足すことです。

![goroutine の親子追跡と traceparent 注入](/images/20260820-context-propagation.png)
*図7: 実線の矢印は処理の流れ、破線は無効化を表す。goroutine の親子追跡（プロセス内）と traceparent 注入（プロセス間）を示している。追跡は6段まで、注入は2経路あり、カーネルのセキュリティ機構が有効だと経路1だけが落ちる。*
