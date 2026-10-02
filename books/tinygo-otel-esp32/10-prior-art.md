---
title: "先行事例"
---

ESP32からOpenTelemetryのテレメトリーを送る試みは、本書が最初ではありません。この章では3つの事例を取り上げ、それぞれが何をして、どこで本書と同じ制約にぶつかったのかを確かめます。3つともCやC++の環境での話です。

## ClickHouseのエスプレッソマシン

[ClickHouse](https://clickhouse.com/)社のブログ記事「[Instrumenting my espresso machine with OpenTelemetry](https://clickhouse.com/blog/espresso-machine-observability-with-otel)」（2026年7月）は、エスプレッソマシンの制御基板をOpenTelemetryで計装した事例です。マシンには、ESP32で動くオープンソースの制御基板[GaggiMate](https://gaggimate.eu/)が入っています。抽出1回を親スパン、抽出の段階を子スパンとするトレースと、ボイラーの温度や圧力のメトリクスを、OTLPでClickHouse Cloudへ送っています。

記事が挙げる最初の壁は、OTLPのprotobufのスキーマが大きすぎることです。マイコン向けのprotobufライブラリ[nanopb](https://github.com/nanopb/nanopb)に公式のOTLPの定義をそのまま与えると、64kBを超えるメッセージがあるというエラーでコンパイルが止まったと書かれています。著者は必要な部分だけを1つの`otlp.proto`に抜き出し、フィールド番号を公式の定義と同じに保つことで、Collectorが通常のOTLPとして読めるようにしました。本書でも、公式のprotobufランタイムが動かないので、フィールド番号だけを公式の定義から借りてエンコーダを手で書いています（5章）。

2つ目の壁はスタックです。記事によると、送信のタスクに割り当てた12KBのスタックは、CA証明書の束を検証するmbedTLSのハンドシェイクで足りなくなることがありました。そこで16KBに増やしています。原因は違いますが、本書でもgoroutineのスタックを8KBから16KBへ広げることになりました（9章）。

3つ目は時刻です。起動直後のESP32は時計が1970年を指していて、そのまま送るとバックエンドで見つけられないデータになると記事は述べています。そこで、NTPで時計が2020年より後になるまで送信を止めています。本書でも、時刻を合わせてから送る点は同じです（8章）。

## base14 Scout

[base14](https://base14.io/)のドキュメント「[ESP32 Firmware to OpenTelemetry](https://docs.base14.io/instrument/iot/esp32/)」は、デバイスにOTLPを話させない構成を採っています。ドキュメントは冒頭で、OpenTelemetryにはC言語のSDKもマイコン向けの手段も無いとしています。C++のSDKはPOSIX専用でESP32には重すぎ、OTLP/HTTPとprotobufとTLSを一式載せるとデフォルトのファームウェアのビルドに収まらない、という理由です。

そのため、ファームウェアは独自の小さなJSON（SME-v1と呼ぶ版付きの形式）を[MQTT](https://mqtt.org/)で送り、ブリッジのサービスがそれを受け取ってOpenTelemetryのシグナルに変換します。OTLPへの変換はデバイスの外です。ドキュメントは、nanopbでOTLPのprotobufをデバイス上でエンコードする道も示していますが、例としては実装していないと明記しています。

ドキュメントに載っているフラッシュの内訳では、大半をWi-FiとTCP/IPとTLSのライブラリが占め、テレメトリーのエンコードと送信のループは数KBでした。ドキュメントはこれを、ネットワークにつながったデバイスに構造化されたテレメトリーを足す費用はほとんど無い、という根拠にしています。本書でも、フラッシュの大きさを左右したのはエンコーダの選択ではなく、HTTPクライアントが引き込むTLSのコードでした（7章）。

## opentelemetry-cppへの要望

[opentelemetry-cpp](https://github.com/open-telemetry/opentelemetry-cpp)は、OpenTelemetryのC++向けの公式実装です。その[issue #2483](https://github.com/open-telemetry/opentelemetry-cpp/issues/2483)「Add support for embedded devices?」は、2024年1月に、ArduinoやIoT機器のようにC++で動く組み込み機器への対応を求めて立てられました。

プロジェクトのメンバーの返答は、対象のアーキテクチャ向けにコードがビルドでき、デバイスがデータを送り出すネットワークにつながっているなら、通常の環境と根本的に違うところは無いのではないか、というものでした。そのうえで、デバイス、プラットフォーム、コンパイラ、使えるライブラリが分からない限り、「support embedded devices」という要望は一般的すぎて手が打てない、と述べています。issueはその後、利用者がESP-IDF向けのコンポーネントを公開したという報告を受けてクローズされました。

返答の前提である「ビルドできるなら」の部分は、TinyGoでは成り立ちません。4章で見るとおり、Go SDKはメモリが足りないからではなく、ホストOSの機能を前提にしているためにTinyGoではビルドできません。

## 本書の立ち位置

本書は3つの事例と次の点で異なります。デバイスのプログラムをGoで書いてTinyGoでビルドし、デバイスはブリッジを介さずOTLP/HTTPを直接話します。送り先は同じLANにあるCollectorで、デバイスにTLSを載せず、外部への暗号化はCollectorに任せます。

デバイスがOTLPを直接話す点はClickHouseの事例と同じで、重い処理をデバイスの外へ出す点はbase14の事例と同じです。本書は、OTLPの形式まではデバイスで作り、TLSと認証だけをCollectorに預けます。ClickHouseの事例とbase14の事例の中間にあたる構成です。
