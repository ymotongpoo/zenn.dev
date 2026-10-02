---
title: "公式のGo SDKを載せてみる"
---

## 最初に試す構成

OTLPを話すいちばん素直な方法は、公式の[OpenTelemetry Go](https://opentelemetry.io/ja/docs/languages/go/)をそのまま使うことです。サーバーで書くときと同じように、APIで**計装器**（カウンターやゲージのように値を記録するオブジェクト）を作り、SDKで値を集め、エクスポーターでCollectorへ送ります。この章では、その3層を1つずつ[TinyGo](https://tinygo.org/)でビルドして、どこで止まるのかを確かめます。

OpenTelemetry Goは3つの層に分かれています。**API**は計装のためのインターフェースで、ライブラリの作者が依存する層です。**SDK**はAPIの実装で、計装器が記録した値を集計し、リソース属性（どのサービスのどのホストから来たデータかを表す属性）を付けます。**エクスポーター**はSDKが集めたデータをOTLPに変換して送る部品で、メトリクスをOTLP/HTTPで送るものが `otlpmetrichttp` です。アプリケーションはこの3つを組み合わせて使いますが、ライブラリはAPIにだけ依存し、SDKを選ぶのはアプリケーションの側です。

検証にはTinyGo 0.42.0とOpenTelemetry Go v1.46.0を使い、ターゲットはESP32-S3にしました[^target]。

## APIと何もしない実装

最初に、APIと、その何もしない実装である `metric/noop` だけを使うプログラムをビルドしました。`noop` はAPIのインターフェースを満たしつつ、記録された値をすべて捨てる実装です。SDKを組み込まずにAPIを呼ぶコードを動かすときに使います。

このビルドは通り、バイナリは6,400バイトでした。APIの層は、TinyGoの上でもそのまま使えます。

この結果は、計装を持つライブラリを書く人に関係します。OpenTelemetryのAPIにだけ依存するライブラリなら、TinyGoのプログラムに組み込んでもビルドは通るからです。SDKを載せられない環境では、そのライブラリの計装は `noop` を通して何もしないだけで、ライブラリ自体は動きます。逆に、ライブラリがSDKやエクスポーターに直接依存していると、TinyGoから使う道はそこで閉じてしまいます。

## SDKとx/sys/unix

次にエクスポーターを外し、SDKの `sdk/metric` だけを組み込みました。このビルドは失敗し、次のエラーが40件以上出ました。

```
system calls are not supported: target emulates a linux/arm system on xtensa
```

依存をたどると、`sdk/metric` から `sdk/resource` を経て [`golang.org/x/sys/unix`](https://pkg.go.dev/golang.org/x/sys/unix) に行き着きます[^go-mod-why]。`sdk/resource` は、プロセス名、OSの種類、ホスト名のように、データの出どころを表すリソース属性を自動で集めるパッケージです。そのためにホストのOSへ問い合わせます。たとえばOSの情報を取る `os_unix.go` は、次のビルド制約と依存を持っています。

```go
//go:build aix || darwin || dragonfly || freebsd || linux || netbsd || openbsd || solaris || zos

package resource

import (
	"fmt"
	"os"

	"golang.org/x/sys/unix"
)
// ...
var defaultUnameProvider unameProvider = unix.Uname
```

エラーの文面にあるとおり、TinyGoにとってXtensaのターゲットは、システムコールを持たない `linux/arm` です。ビルド制約の `linux` に一致するので、このファイルがビルドに入り、`unix.Uname` のようなシステムコールの呼び出しを引き込みます。マイコンの上には、システムコールを受け付けるカーネルがありません。TinyGoがこの呼び出しをコンパイルできないのはそのためです。

ここで落ちているのは、メトリクスを集計する部分ではありません。SDKは起動時に「自分がどのホストで動いているか」を調べに行き、その手段がOSに尋ねることだけだったためにビルドできなくなっています。

## エクスポーターとtls.X509KeyPair

エクスポーターの `otlpmetrichttp` も、別の理由でビルドに失敗しました。

```
.../otlpmetrichttp@v1.46.0/internal/envconfig/envconfig.go:143:19: undefined: tls.X509KeyPair
```

`envconfig` は、`OTEL_EXPORTER_OTLP_*` のような環境変数からエクスポーターの設定を読むパッケージです。クライアント証明書のファイルを指す環境変数が設定されていれば、その証明書と鍵を読み込んでTLSの設定に使います。該当する箇所は次のとおりです。

```go
		key, err := e.ReadFile(vk)
		// ...
		crt, err := tls.X509KeyPair(cert, key)
		if err != nil {
			global.Error(err, "create tls client key pair")
			return
		}
```

TinyGo 0.42.0の `crypto/tls` には `X509KeyPair` がありません[^tinygo-tls]。この関数があるのは、環境変数が設定されていなければ実行されない分岐の中です。それでも参照そのものはコンパイル時に解決する必要があり、TLSを使わずに平文で送る構成でもビルドが通りません。

## ホストOSという前提

ここまでの失敗を並べると、次のようになります。

| 構成 | 結果 | 止まった箇所 |
| --- | --- | --- |
| `otel/metric` と `metric/noop` | 成功（6,400バイト） | なし |
| `otel/sdk/metric` | 失敗 | `sdk/resource` から `golang.org/x/sys/unix` |
| `otlpmetrichttp` | 失敗 | `envconfig` の `tls.X509KeyPair` |

2つの失敗は、どちらもビルドの段階で起きています。バイナリが大きすぎてフラッシュに入らなかったのでも、実行してメモリが足りなくなったわけでもありません。SDKはOSに尋ねればホストの情報が分かることを、エクスポーターは証明書を扱える完全な `crypto/tls` があることを、それぞれ前提にしたコードです。サーバーやPCではどちらも当たり前に成り立つので、コードの側でその前提を意識する必要はありません。

**SDKがマイコンに載らない理由は、メモリの量ではなく、ホストOSを前提にした依存にあります。** 2章で見たとおり、OpenTelemetryは組み込み向けに設計されていません。その設計の前提が、具体的な形をとったものがこの2つのビルドエラーです。

失敗の原因が分かれば、デバイスの側で自分で書く必要があるものも決まります。OSに尋ねて集めていたリソース属性の代わりになるのは、デバイスが自分について知っていること（サービス名、バージョン、デバイスのIDや機種）をコードに書いた値です。本書の実装では、`deployment.environment.name` のように環境で決まる属性はデバイスに持たせず、Collectorで付け足しています[^collector]。エクスポーターの設定は環境変数から読まず、ビルド時に埋め込みます。TLSはデバイスに載せず、同じネットワークにあるCollectorへの送信は平文です。

残るのは、計装器が記録した値を保持し、OTLPのメッセージに組み立て、HTTPで送る部分です。SDKが担っていたこの部分は、本書の実装では小さく書き直してあります。中身は、計装器の登録と値の保持だけを持ち、集計の仕組みを持たない型です。次の章では、そのメッセージをバイト列にするための公式の部品、protobufのランタイムを試してみましょう。

[^target]: 正確には、この章のビルドは `xiao-esp32s3` ターゲットで行いました。`xiao-esp32s3` と、本書の実機で使う `esp32s3-generic` は、どちらもTinyGoの `esp32s3` を継承していて、違いはビルドタグだけです。
[^go-mod-why]: 依存の経路は `go mod why` で確認しました。
[^tinygo-tls]: TinyGo 0.42.0の `src/crypto/tls/tls.go` には、ファイルから読む `LoadX509KeyPair` が「未実装」というエラーを返すだけの関数として置かれています。メモリ上のPEMを受け取る `X509KeyPair` は宣言されていません。
[^collector]: Collectorでの属性の付け足しは11章で扱います。
