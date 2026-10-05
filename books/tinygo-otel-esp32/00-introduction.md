---
title: "はじめに"
---

本書は、TinyGo Conference 2026（2026年10月10日）での筆者の登壇「TinyGoでオブザーバビリティ？OpenTelemetryはTinyGoで使えるのか」の解説資料です。

[TinyGo](https://tinygo.org/)は、マイコンやWebAssemblyのような小さな環境に向けてGoのプログラムをビルドするコンパイラです。[OpenTelemetry](https://opentelemetry.io/ja/)は、アプリケーションを外から観測するためのデータ（**テレメトリー**）の形式と収集の仕組みを定めるオープンソースのプロジェクトです。サーバーのアプリケーションでは、すでに事実上の標準になっています。テレメトリーには、数値の時系列であるメトリクス、出来事の記録であるログ、処理の流れを区間（スパン）の木で表すトレースの3種類があります。OpenTelemetryでは、この3種類をそれぞれ**シグナル**と呼びます。

本書が扱う問いは、TinyGoで書いたWi-Fiマイコンのプログラムから、[**OTLP**](https://opentelemetry.io/ja/docs/specs/otlp/)（OpenTelemetry Protocol）でテレメトリーを送れるのか、です。OTLPはOpenTelemetryが定める通信プロトコルです。サーバーなら、OpenTelemetryのGo SDKを組み込めば送れます。ところがマイコン向けには、そのSDKがビルドできないのが現状です。それでも、プロトコルであれば自分で実装できます。

本書では、[M5Stack CoreS3](https://docs.m5stack.com/ja/core/CoreS3)からメトリクス、ログ、トレースの3つのシグナルを送り、[Grafana](https://grafana.com/oss/grafana/)のダッシュボードで見られるところまで進みます。CoreS3は、Espressif社のマイコン[ESP32-S3](https://www.espressif.com/en/products/socs/esp32-s3)を載せた開発ボードです。送り先は[OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/)で、テレメトリーを受け取って加工し、保存先へ転送するサーバープログラムです。デバイス側では公式のSDKを使わず、公式の部品から借りたのはOTLPのスキーマ（メッセージの構造とフィールド番号）だけで、エンコーダ、HTTPクライアント、時刻同期は自分で書きました。どこで公式の部品が使えなくなり、かわりに何を書いたのかを、実機で測った値とともに示します。

:::message
本書のコードと測定した値は、次の環境で確かめたものです。

- TinyGo 0.42.0（LLVM 22.1.4）、Go 1.26.0
- M5Stack CoreS3（ESP32-S3 rev v0.2、16MB Flash）、TinyGoのターゲットは `esp32s3-generic`
- espradio v0.3.0（TinyGoのESP32向けWi-Fiパッケージ）
- opentelemetry-proto v1.11.0のフィールド番号
- otel/opentelemetry-collector-contrib 0.160.0、grafana/otel-lgtm 0.32.1

TinyGoとespradioは開発が速く、本書で扱う未実装の機能や非公開のAPIは、新しいリリースで変わっている可能性があります。
:::

## 本書の読み方

想定する読者は、Goは書けるものの、マイコンとOpenTelemetryの両方には詳しくない人です。TinyGoでマイコンを触ったことがあるか、サーバーでOpenTelemetryを使ったことがあるか、どちらか一方の経験があれば読み進められます。もう一方の用語は、出てくるたびに補います。

2章では、本論に入る前に、どんな制約の中で作ったのかを一覧にします。OpenTelemetryが組み込み機器を想定していないこと、マイコンのメモリ、TinyGoの未実装の機能、ネットワークスタックの事情を並べ、それぞれを扱う章を示します。3章は、同じことに挑んだ先行事例3つと本書との違いです。

4章から8章では、OTLPでデータを送るまでに通る層を順に見ていきます。4章は公式のGo SDKがなぜ載らないのか、5章はprotobufのエンコード、6章はもう一つのエンコーディングであるOTLP/JSONです。7章でHTTPクライアントと送信の失敗の扱いを、8章で時刻の同期を扱います。

9章では、動くようになったプログラムのメモリ、GC、スタックを測ります。10章は3つのシグナルそれぞれの設計、11章はCollectorの構成と連続稼働の結果で、12章で全体を締めます。巻末の付録は参考文献の一覧です。

2章の制約を先に読んでおくと、4章以降の選択の理由を追いやすくなります。ただし4章以降の各章は、扱う層の話として単独でも読めるように書きました。
