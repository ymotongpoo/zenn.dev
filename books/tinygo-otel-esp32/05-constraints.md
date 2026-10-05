---
title: "前提と制約"
---

この章では、本論に入る前に、どんな制約の中で実装を作ったのかをそれぞれ説明します。後の章で下す判断の多くは、ここに挙げる制約のどれかから出てきます。

## 組み込み機器を想定しない仕様

最初の前提は、[OpenTelemetry](https://opentelemetry.io/ja/)の仕様が組み込み機器を想定して作られていないことです。2024年、ESP32のようなCで動く組み込み機器向けの実装を作る作業グループを提案する[issue #2160](https://github.com/open-telemetry/community/issues/2160)が立てられました。OpenTelemetryの共同創設者であるTed Young（tedsuo）[^tedsuo]は、これに[次のようにコメント](https://github.com/open-telemetry/community/issues/2160#issuecomment-2182361878)しています。

> In general, the OTel spec is not designed for the limited resources present in embedded systems. I don't think that the client design represents the right trade-offs best suited for those environments.
>
> （一般に、OTelの仕様は組み込みシステムにある限られた資源に合わせて設計されていません。クライアントの設計が、そうした環境に最も適したトレードオフになっているとは思いません。）

同じコメントは、OTLPがネットワークにとって重すぎることも挙げています。128ビットのトレースIDは組み込み機器で使われる多くのメッセージングプロトコルには大きすぎ、W3Cのトレーシングヘッダー全体はなおさら収まらない、という指摘です。そのうえで、組み込み機器向けの汎用のテレメトリー実装の出発点として、OpenTelemetryのどの部分も適しているとは考えにくい、と結んでいます。

この指摘が否定しているのは、組み込み機器全般に通用する汎用の実装です。本書の対象はずっと狭く、Wi-FiでTCP/IPを話せるマイコン1台と、同じLANにある[OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/)だけです。この範囲なら、OTLPのメッセージはWi-Fiで十分に送れる大きさで、128ビットのトレースIDも負担になりません。一方、クライアントの設計がマイコンに合わないという指摘は、そのまま当てはまり、その中身は4章で確かめます。

## ハードウェアの制約

本書で使う[M5Stack CoreS3](https://docs.m5stack.com/ja/core/CoreS3)は、Espressif社の[ESP32-S3](https://www.espressif.com/en/products/socs/esp32-s3)を載せたボードです。ESP32-S3は最大240MHzで動くデュアルコアのマイコンで、Wi-Fiを内蔵しています[^s3ds]。ボードの仕様には、16MBのフラッシュメモリと8MBの**PSRAM**が並んでいます。フラッシュメモリはプログラムを書き込んでおく不揮発の記憶領域、PSRAMはチップの外に付けた追加のRAMです。

ただし、TinyGo 0.42.0が扱えるのはチップに内蔵されたSRAMだけです。リンカースクリプトがデータ用に割り当てるRAM（DRAM）は416KB、つまり425,984バイトで、そのうちヒープの上限は298,287バイトでした。PSRAMの8MBは、TinyGoからはまだ使えません[^psram]。

ボードの仕様よりずっと小さいメモリで動かすことになりますが、測定してみると、この用途の作業セットは内蔵のSRAMに収まりました。問題になったのは量よりも、送信のたびに確保して捨てるメモリのほうです。これは9章で扱います。

フラッシュメモリの16MBは、プログラムの大きさの上限としては十分です。それでも、使う標準パッケージによってバイナリは数百KB単位で変わります。その差は7章で見ます。

## TinyGoの制約

[TinyGo](https://tinygo.org/)の標準ライブラリとランタイムには、小さな環境に合わせて省かれた部分があります。本書で実際に問題になったものは3つです。

1つ目は`reflect`パッケージです。TinyGoの`reflect`には、宣言はあっても呼ぶと`panic`するメソッドがあります。`(reflect.Type).MethodByName`がその一つで、ビルドもリンクも通るのに、実機で呼ばれた時点で落ちます。Goの公式のprotobufランタイムは、メッセージを最初にエンコードするときにこのメソッドを呼ぶので、そのままでは使えません。回避の方法は5章の話題です。

2つ目は`crypto/tls`です。TinyGoの`crypto/tls`には、Goの標準ライブラリにある関数のうちいくつかが欠けています。OpenTelemetryのGo向けOTLPエクスポーターは、TLSを使わない設定でもそうした関数を参照します。そのためビルドの時点で失敗し、実際のエラーは4章に載せました。

3つ目はgoroutineのスタックです。Goのgoroutineのスタックは必要に応じて伸びますが、TinyGoではビルド時に決めた大きさに固定されます。ESP32-S3のデフォルトは8KBで、`-stack-size`オプションで変えられます。入れ子の深いOTLPのメッセージを`encoding/json`でエンコードするには、8KBでは足りません。必要な大きさは実機で測るしかなく、その結果は6章と9章に置きました。

## ネットワークの制約

Wi-Fiの接続には[espradio](https://github.com/tinygo-org/espradio)を使います。espradioはTinyGoのプロジェクトが開発しているESP32向けの無線通信パッケージです。TCP/IPの処理には、Goだけで書かれたネットワークスタック[lneto](https://github.com/soypat/lneto)を使っています。OSの無いマイコンの上でDHCP、DNS、TCP、UDPがGoのコードとして動き、Goの`net`パッケージも使えます。

困ったのは、ライブラリが機能を持っていても、外から呼べるAPIになっていないものがあったことです。lnetoはNTPを実装しています。ところがespradio v0.3.0の標準の接続手順ではNTPサーバーが設定されず、NTPを実行する関数にも外から届きません。OTLPのデータには時刻が必要なので、時刻の同期は自分で書きました（8章）。

接続中のアクセスポイントの電波強度（RSSI）を返すGoの関数もありませんでした。10章では、Wi-Fiドライバのバイナリにある関数を直接呼んでいます。

## TLSを載せないという前提

最後の制約は、デバイスにTLSを載せないことです。espradio v0.3.0はTLSクライアントを提供しておらず、TinyGoの`crypto/tls`にも足りない関数があります。そこで本書では、デバイスから同じLANにあるCollectorへ、平文のHTTPでOTLPを送ります。外部のバックエンドへの暗号化と認証は、Collectorの役割です。

この分け方には利点もあります。バックエンドの認証情報や証明書をマイコンに持たせずに済み、バックエンドを変えるときもファームウェアを書き換えずに済みます。その代わり、デバイスとCollectorの間の通信は暗号化されないので、信頼できるネットワークの中に置くことが条件です。Collectorの構成は11章で扱います。

[^tedsuo]: Ted YoungはOpenTelemetryの共同創設者の一人です。執筆時点で、[GitHubのプロフィール](https://github.com/tedsuo)にはGrafana Labsで働いていると書かれています。引用したコメントは2024年6月21日のものです。
[^s3ds]: Espressif社の[ESP32-S3のデータシート](https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf)による値です。
[^psram]: ESP32-S3のPSRAMへの対応は、執筆時点でTinyGoの[PR #5554](https://github.com/tinygo-org/tinygo/pull/5554)として進行中です。
