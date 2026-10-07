---
title: "参考文献"
---

本書で参照した一次資料です。リンク先の内容は執筆時点（2026年10月）のものです。

## OpenTelemetryの仕様

- [OTLP Specification](https://opentelemetry.io/ja/docs/specs/otlp/)：OTLPの転送方式、protobufとJSONのエンコーディング、再試行の対象となる応答、partialSuccessを定める仕様
- [opentelemetry-proto](https://github.com/open-telemetry/opentelemetry-proto)：OTLPのprotobufスキーマ。本書の手書きエンコーダはv1.11.0のフィールド番号に従っている
- [Metrics Data Model](https://opentelemetry.io/docs/specs/otel/metrics/data-model/)：gaugeとcumulative sum、`StartTimeUnixNano` の扱い
- [Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)：ログレコードのタイムスタンプと重要度
- [Deployment environment](https://opentelemetry.io/docs/specs/semconv/resource/deployment-environment/)：リソース属性 `deployment.environment.name` のセマンティック規約

## OpenTelemetryの実装

- [OpenTelemetry Go](https://opentelemetry.io/ja/docs/languages/go/)：Go向けのAPIとSDKの公式ドキュメント
- [opentelemetry-go](https://github.com/open-telemetry/opentelemetry-go)：Go SDKのリポジトリ
- [go.opentelemetry.io/otel/sdk/metric](https://pkg.go.dev/go.opentelemetry.io/otel/sdk/metric)：メトリクスのSDK
- [otlpmetrichttp](https://pkg.go.dev/go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp)：OTLP/HTTPのメトリクスエクスポーター
- [go.opentelemetry.io/proto/otlp](https://pkg.go.dev/go.opentelemetry.io/proto/otlp)：OTLPのprotobufから生成されたGoの型
- [OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/)：Collectorの公式ドキュメント
- [opentelemetry-collector-contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib)：本書で使ったCollectorのディストリビューションと追加の部品
- [resource processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/resourceprocessor)：リソース属性を書き換えるプロセッサー
- [batch processor](https://github.com/open-telemetry/opentelemetry-collector/tree/main/processor/batchprocessor)：データをまとめて送るプロセッサー

## OpenTelemetryと組み込み機器

- [open-telemetry/community#2160](https://github.com/open-telemetry/community/issues/2160)：組み込み機器向けの実装を作る作業グループの設立を提案したissue
- [open-telemetry/community#2160 へのTed Youngのコメント](https://github.com/open-telemetry/community/issues/2160#issuecomment-2182361878)：OpenTelemetryが組み込み機器向けに設計されていないことへの言及
- [opentelemetry-cpp#2483](https://github.com/open-telemetry/opentelemetry-cpp/issues/2483)：opentelemetry-cppに組み込み機器への対応を求めたissue「Add support for embedded devices?」
- [Instrumenting my espresso machine with OpenTelemetry](https://clickhouse.com/blog/espresso-machine-observability-with-otel)：ClickHouse社のブログ記事。ESP32で動くエスプレッソマシンの制御基板からOTLPを送った事例
- [GaggiMate](https://gaggimate.eu/)：ClickHouseの事例で使われた、ESP32で動くエスプレッソマシン用のオープンソースの制御基板
- [nanopb](https://github.com/nanopb/nanopb)：組み込み機器向けのC言語のprotobuf実装
- [ESP32 Firmware to OpenTelemetry](https://docs.base14.io/instrument/iot/esp32/)：base14のドキュメント。MQTTとブリッジを介してESP32のテレメトリーを集める構成

## TinyGoとドライバ

- [TinyGo](https://tinygo.org/)：マイコンとWebAssembly向けのGoコンパイラ
- [tinygo-org/tinygo](https://github.com/tinygo-org/tinygo)：TinyGoのリポジトリ
- [tinygo-otel-esp32](https://github.com/ymotongpoo/tinygo-otel-esp32)：本書で使った独立した公開ブループリント
- [tinygo-org/tinygo#5554](https://github.com/tinygo-org/tinygo/pull/5554)：ESP32-S3のPSRAM対応のプルリクエスト
- [espradio](https://github.com/tinygo-org/espradio)：TinyGoからESP32のWi-Fiを使うドライバ
- [lneto](https://github.com/soypat/lneto)：espradioが使うTCP/IPスタック

## Goとprotobuf

- [protobuf-go](https://github.com/protocolbuffers/protobuf-go)：Go向けのprotobufランタイム
- [dynamicpb](https://pkg.go.dev/google.golang.org/protobuf/types/dynamicpb)：スキーマを実行時に扱うprotobufのメッセージ型
- [protojson](https://pkg.go.dev/google.golang.org/protobuf/encoding/protojson)：protobufのJSONマッピングの実装
- [Protocol Buffers](https://protobuf.dev/)：protobufの公式ドキュメント
- [Encoding](https://protobuf.dev/programming-guides/encoding/)：protobufのワイヤーフォーマットの解説
- [encoding/json](https://pkg.go.dev/encoding/json)：Goの標準ライブラリのJSONパッケージ
- [crypto/rand](https://pkg.go.dev/crypto/rand)：Goの標準ライブラリの暗号用乱数パッケージ
- [golang.org/x/sys/unix](https://pkg.go.dev/golang.org/x/sys/unix)：UnixのシステムコールのGoバインディング

## プロトコル

- [RFC 4330](https://www.rfc-editor.org/rfc/rfc4330)：Simple Network Time Protocol (SNTP) Version 4
- [MQTT](https://mqtt.org/)：base14の事例でデバイスとブリッジの間に使われているメッセージングプロトコル

## ハードウェア

- [M5Stack CoreS3](https://docs.m5stack.com/ja/core/CoreS3)：本書の実機の製品ドキュメント
- [ESP32-S3](https://www.espressif.com/en/products/socs/esp32-s3)：Espressifの製品ページ
- [ESP32-S3 Datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf)：ESP32-S3のデータシート
- [ESP32-S3 Technical Reference Manual](https://www.espressif.com/sites/default/files/documentation/esp32-s3_technical_reference_manual_en.pdf)：ESP32-S3のテクニカルリファレンスマニュアル
- [Wi-Fi API（ESP-IDF）](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/network/esp_wifi.html)：`esp_wifi_sta_get_rssi` を含むWi-FiのAPIリファレンス

## バックエンドとツール

- [grafana/docker-otel-lgtm](https://github.com/grafana/docker-otel-lgtm)：OTLPの受信口とPrometheus、Loki、Tempo、Grafanaをまとめたコンテナイメージ
- [Grafana](https://grafana.com/oss/grafana/)
- [Prometheus](https://prometheus.io/)
- [Loki](https://grafana.com/oss/loki/)
- [Tempo](https://grafana.com/oss/tempo/)
- [Span metrics](https://grafana.com/docs/tempo/latest/metrics-generator/span_metrics/)：Tempoがスパンからメトリクスを作る機能
- [Docker Compose](https://docs.docker.com/compose/)

## 本書の調査から報告したissue

本書の調査で見つけた制約のうち、次の5件を2026年10月7日に各プロジェクトへ報告しました。

- [tinygo-org/espradio#75](https://github.com/tinygo-org/espradio/issues/75)：`netlink`で接続したプログラムから時刻を合わせる手段がないことの報告（8章）
- [tinygo-org/espradio#76](https://github.com/tinygo-org/espradio/issues/76)：接続中のアクセスポイントのRSSIを返す関数の提案（10章）
- [tinygo-org/tinygo#5839](https://github.com/tinygo-org/tinygo/issues/5839)：ESP32-S3でgoroutineのスタックがあふれても`goroutine stack overflow`と報告されず、無言で止まるか別のエラーで落ちることの報告（9章）
- [tinygo-org/tinygo#5204へのコメント](https://github.com/tinygo-org/tinygo/issues/5204#issuecomment-6036833704)：`tls.X509KeyPair`が無いために`otlpmetrichttp`がビルドできない事例（4章）
- [tinygo-org/tinygo#3862へのコメント](https://github.com/tinygo-org/tinygo/issues/3862#issuecomment-6036834071)：`(reflect.Type).MethodByName`が未実装のために、protobuf-goの`proto.Marshal`がpanicする事例（5章）
