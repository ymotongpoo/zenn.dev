---
title: "HTTPクライアントと送信の失敗"
---

[OTLP](https://opentelemetry.io/ja/docs/specs/otlp/)のHTTP版（OTLP/HTTP）でデータを送る処理は、HTTP/1.1のPOSTを1本送って応答を読むだけです。Goなら標準ライブラリの[`net/http`](https://pkg.go.dev/net/http)を使うのが普通ですが、本書のデバイスでは`net/http`を使わず、HTTPクライアントを手で書きました。この章では、その理由になったバイナリサイズの差を確かめたうえで、手書きのクライアントが満たすべき要件と、送信に失敗したときに何を送り直して何を送り直さないかを見ていきます。

## net/httpが依存するもの

TinyGoはビルドの際に到達しないコードを削ります。それでも、`net/http`を使うビルドと手書きのクライアントを使うビルドとでは、flashの使用量に大きな差が出ました。次の表は、メトリクスのエンコーダに`encoding/json`を使い、Wi-Fi接続、時刻同期、3つのシグナルの送信を含むファームウェア全体を`-stack-size=16KB`でビルドしたときの値です[^size-measure]。

| 項目 | `net/http` | 手書き | 差 |
| --- | ---: | ---: | ---: |
| flash（バイト） | 1,067,175 | 748,691 | 318,484 |
| 静的RAM（バイト） | 147,636 | 114,796 | 32,840 |

`net/http`をやめるとflashが約32万バイト（30%）減ります[^size-protobuf]。`net/http`を使うと`crypto/tls`が依存関係に入り、さらに`crypto/x509`、`encoding/asn1`、`math/big`が付いてきます。デバイスが話すのは平文のHTTPだけなので、この32万バイトは一度も実行されないコードの分です。

本書ではデバイス上でTLSの通信を試していません。TinyGoの`crypto/tls`は4章で見たとおり一部の関数が未実装で、Wi-Fiドライバの[espradio](https://github.com/tinygo-org/espradio) v0.3.0もTLSクライアントを提供していません。そこで本書の構成では、デバイスは同じLANにあるCollectorへ平文で送り、外部へのTLSはCollectorに任せました。この分担は11章で改めて説明します。

[^size-measure]: サイズを測るときは、Wi-FiのSSIDと送信先のエンドポイントの両方を`-ldflags -X`で埋めておく必要があります。どちらかが空だと、ファームウェアは起動直後にエラーで止まる作りなので、TinyGoがネットワーク処理か送信ループを到達不能と判断して削除し、実際の約6分の1のサイズを報告します。
[^size-protobuf]: エンコーダを手書きのprotobufにした場合も差はほぼ同じで、flashは1,067,327バイトから748,907バイトへ減ります。

## 手書きのHTTPクライアント

手書きのクライアントがするのは、TCPの接続にリクエストのバイト列を書き込み、応答を読むことだけです。リクエストは、送信のたびに確保し直さないように、使い回すバッファへ組み立てます。

```go
r := e.req[:0]
r = append(r, "POST "...)
r = append(r, path...)
r = append(r, " HTTP/1.1\r\nHost: "...)
r = append(r, e.host...)
r = append(r, "\r\nContent-Type: "...)
r = append(r, contentType...)
r = append(r, "\r\nContent-Length: "...)
r = strconv.AppendInt(r, int64(len(body)), 10)
r = append(r, "\r\n\r\n"...)
r = append(r, body...)
```

書く側の処理はこれで全部です。手間がかかるのは読む側で、その理由は接続を使い回すことにあります。[espradio](https://github.com/tinygo-org/espradio)が使うTCP/IPスタックの[lneto](https://github.com/soypat/lneto)は、接続を張るたびに送受信のバッファを確保するので、送信ごとに接続を張り直すとヒープを使い捨てる量が増えます。その測定は9章に回し、ここでは接続を使い回すと決めたときにクライアントが守らなければならない要件を見ていきます。

1つ目は、応答を最後まで読み切ることです。HTTP/1.1の応答は、ステータス行とヘッダーが空行（CRLFを2つ続けたバイト列）で終わり、その後に`Content-Length`が示す長さの本文が続きます（[RFC 9112](https://www.rfc-editor.org/rfc/rfc9112)）。TCPはこの応答を任意の位置で分割して届けるので、`Read`を1回呼んで届いた分だけを解析するやり方は成り立ちません。本文を読み残すと、次の送信のときに前回の本文の残りをステータス行として読んでしまいます。そこで、ヘッダーはCRLFが2回連続する箇所が見つかるまで、本文は`Content-Length`のバイト数に達するまで、それぞれ読み足すようにしました。

```go
for headerEnd < 0 {
	if len(e.resp) == cap(e.resp) {
		// Refusing is safer than parsing a truncated header block.
		e.closeConn()
		return out, errors.New("otlpmini: response header exceeds " +
			strconv.Itoa(maxHeaderBytes) + " bytes")
	}
	n, err := e.conn.Read(e.resp[len(e.resp):cap(e.resp)])
	if n > 0 {
		e.resp = e.resp[:len(e.resp)+n]
		headerEnd = indexCRLFCRLF(e.resp)
	}
	// ...
}
```

2つ目は、ヘッダーの大きさに上限を設けることです。HTTPの仕様はヘッダーの大きさに上限を定めていないので、上限を決めずに読み足すと、ヒープをいくらでも使ってしまいます。本書のクライアントは上限を2KBにしました。Collectorの応答のヘッダーは数百バイトなので、数倍の余裕があります。上限を超えた場合は、途中までのヘッダーを解析せず、エラーを返して接続を閉じる作りです。

3つ目は、サーバーが接続を閉じると言ったら従うことです。応答に`Connection: close`があれば、その応答を読んだあとで接続を閉じます。ヘッダー名も`close`という値も大文字と小文字を区別しない（[RFC 9110](https://www.rfc-editor.org/rfc/rfc9110)）ため、比較の関数も大文字と小文字を同一視する作りにしました。本文の長さが分からない応答（`Transfer-Encoding: chunked`か、`Content-Length`がない応答）も、次の応答との境目が決められないので接続を閉じます[^chunked]。

[^chunked]: chunked形式の本文の解析は実装していません。Collectorの応答には`Content-Length`が付くので、デバイスの用途では必要になりませんでした。

4つ目は、使い回している接続が切れていたら張り直すことです。Collectorの再起動やアクセスポイントとの切断があると、保持している接続は使えなくなります。ところが、接続が切れたことは次に書き込むか読み出すまで分からないので、使い回した接続で書き込みか読み出しが失敗したときに限り、接続を閉じて一度だけ張り直し、同じリクエストを送ります。

これらの要件は、ホストで動くテストによって満たしていることを検査しています。テストは、応答を決まった位置で分割して返す偽のサーバーを立て、クライアントがそれを正しく読めるかを確かめます。

| 要件 | 守らないと起きること | テスト |
| --- | --- | --- |
| 分割された応答を読み足す | 正しい応答を壊れた応答と判定する | ステータス行の途中で分割して返す |
| 本文を読み切る | 次の送信で前回の本文をステータス行として読む | 本文付きの応答のあとに2回目の送信をする |
| ヘッダーの上限 | 上限を超えたヘッダーを途中まで解析する | 4KBのヘッダーを返す |
| `Connection: close` | 閉じられる接続に次のリクエストを書く | `CONNECTION: Close`を返す |
| 切れた接続の張り直し | Collectorの再起動のあと送信が失敗し続ける | 1回目の応答のあとでサーバー側から接続を切る |

最後の要件が実機で機能することは、30分の連続稼働の途中でCollectorを再起動する試験で確かめました。この結果は11章で扱います。

## 再送するものとしないもの

送信が失敗したとき、同じデータを送り直してよいかどうかは失敗の種類で決まります。OTLPの仕様は、OTLP/HTTPで再試行すべき応答コードを429、502、503、504の4つに限っています（[Retryable Response Codes](https://opentelemetry.io/ja/docs/specs/otlp/#retryable-response-codes)）。

> All other `4xx` or `5xx` response status codes MUST NOT be retried.
>
> （これ以外の`4xx`と`5xx`の応答コードは再試行してはならない。）

4つに限る理由は、応答コードの意味にあります。400はリクエストの中身が不正だという応答なので、同じバイト列を送り直しても結果は同じで、仕様も400については再試行してはならないと明記しています。500も4つのコードに入っていないので、送り直しの対象外です。一方、429と503はサーバーが一時的に受け付けられない状態を、502と504は途中の中継が失敗したことを表すので、時間を置けば通る見込みがあります。

手書きのクライアントは、応答コードを仕様の表どおりに振り分けます。

```go
// OTLP names 429, 502, 503 and 504 as retryable. Other 5xx are not on that
// list, so they are reported as permanent rather than retried forever.
case resp.status == 429, resp.status == 502, resp.status == 503, resp.status == 504:
	return 0, errors.Join(ErrRetryable, errStatus(resp.status))
default:
	return 0, errStatus(resp.status)
```

接続が張れない、書き込めない、応答が途中で切れた、といった通信路の失敗も再試行できる失敗として扱います。応答が返ってこない以上、リクエストがCollectorに届いたかどうかが分からないからです。

ここで、前節の張り直しと再試行は別の判断である点に注意が必要です。クライアントの内部で同じリクエストを自動で送り直すのは、使い回した接続が通信路の段階で失敗したときだけです。Collectorが応答を返したのであれば、それが503であってもリクエストは届いています。そのため、クライアントの内部では送り直さず、再試行できる失敗かどうかを`IsRetryable`で呼び出し側に伝えます。

```go
var status errStatus
var partial *PartialSuccess
if errors.As(err, &status) || errors.As(err, &partial) {
	return n, err
}
e.closeConn()
return e.export(path, body, contentType)
```

再試行の扱いも、応答コードごとの動作をテストで検査しています。400、404、413、500を返すサーバーに対しては、ペイロードがちょうど1回だけ送られることを確かめ、429、502、503、504だけが再試行できる失敗として報告されることを別のテストで確かめます。

デバイスの呼び出し側は、再試行できる失敗でもペイロードを保持して送り直すことはせず、失敗を数えて10秒後の次の周期を待ちます[^retry-after]。次の周期では、その時点の値で新しくエンコードし直したペイロードを送ります。累積カウンターは起動からの合計を毎回送るので、1周期の送信を失っても、その間の増分は次の周期の値に含まれます。失われるのは、その周期のゲージの値だけで済みます。

[^retry-after]: OTLPの仕様は、429と503の応答に`Retry-After`ヘッダーが付いていればその値に従うことも求めています（SHOULD）。本書のクライアントはこのヘッダーを解析しておらず、送信の間隔は常に10秒です。

## HTTP 200でも欠けるデータ

HTTP 200の応答が、送ったデータがすべて受け入れられたことを意味するとは限りません。OTLPでは、Collectorがリクエストの一部だけを受け入れたときも200を返し、拒否した件数を応答の本文で伝えます（[Partial Success](https://opentelemetry.io/ja/docs/specs/otlp/#partial-success-1)）。メトリクスの場合、本文は`ExportMetricsServiceResponse`というメッセージで、その`partial_success`フィールドに拒否したデータポイントの数（`rejected_data_points`）と理由（`error_message`）が入ります。

応答の本文は、リクエストと同じエンコーディングで返ってきます。protobufで送ればprotobufで、JSONで送ればOTLP/JSONで返ってくるので、クライアントは本文の先頭が`{`かどうかでエンコーディングを見分けて、どちらも解析します。JSONの`rejectedDataPoints`はint64なので、OTLP/JSONでは文字列でも数値でも書けます（6章）。解析はどちらの書き方も受け付けます。protobuf版のビルドが`encoding/json`に依存しないように、JSONの解析も必要なキーを探すだけの小さな関数を手で書きました。

```go
case resp.status == 200:
	// HTTP 200 does not mean every point was stored. OTLP reports rejected
	// points in the body, and treating that as success hides data loss.
	if p := parsePartialSuccess(resp.body); p != nil {
		return len(body), errors.Join(ErrPartialSuccess, p)
	}
	return len(body), nil
```

本文が空の応答、`{}`、中身が空の`partialSuccess`は、すべて完全な成功として扱います。正常なCollectorが返すのはこれらの形なので、ここで失敗と判定すると、すべての送信が失敗に見えてしまいます[^warning]。

[^warning]: 仕様では、拒否件数を0にしたまま`error_message`だけを入れて警告を伝えることも許されています。本書のクライアントは、拒否件数が0でもエラーメッセージが入っていれば部分的な拒否として数えます。

部分的な拒否は、成功とも失敗とも別に数えます。デバイスは送信の結果を`device.export.attempts`というカウンターで送っていて、`outcome`属性で`success`、`failure`、`partial_rejection`を区別します。部分的な拒否を成功に含めると、データが欠けていることが成功率の数字に隠れてしまい、失敗に含めると、通信路やCollectorの障害と見分けがつかなくなります。

部分的な拒否は、再試行できる失敗にも入れていません。仕様は部分的な成功を受け取ったリクエストを再試行してはならないとしていて、実際、同じペイロードを送り直しても同じデータポイントが同じ理由で拒否されるだけです。拒否の理由はログとしても送るので、ダッシュボードでCollectorが何を拒否したのかを読めます。
