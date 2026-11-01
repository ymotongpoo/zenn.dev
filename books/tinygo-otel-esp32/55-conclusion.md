---
title: "おわりに"
---

OpenTelemetryのGo SDKは、TinyGoで動くマイコンには載りません。SDKとエクスポーターは、ホストOSがある前提で書かれています。一方で、OTLPというプロトコルは標準ライブラリと小さな自作のコードだけで実装できる、ということを本書の実装で確認しました。M5Stack CoreS3から送ったメトリクス、ログ、トレースは、Collectorを経由してGrafanaに並び、30分の連続稼働とCollectorの再起動にも耐えました。Collectorに届いた時点で、そこから先はサーバーで使うOpenTelemetryと同じパイプラインです。

この結果から、マイコンでOpenTelemetryを使うには、SDKをそのまま載せるのではなく、デバイスに必要な部分を独自に実装する判断になります。デバイスの上で書く必要があるのは、OTLPのエンコード、HTTPの送信、時刻合わせ、上限付きのバッファです。残りの属性の付与やTLS、認証、バックエンドへの再送は、Collectorに任せられます。デバイスに何かを足したくなったら、それがデバイスの上でしか分からない情報かどうかを先に確かめてください。デバイスの外で決まる情報なら、Collectorの設定で足せます。

本書の数値は、TinyGo 0.42.0とespradio v0.3.0、1台のM5Stack CoreS3で測ったものです。TinyGoの `reflect` やespradioのAPIが変われば、自作のコードが要る範囲も変わります[^espradio-update]。現時点では、OTLPの仕様と自分の手元の実機で測った値を判断の根拠にするのが確実です。

[^espradio-update]: 2026年10月28日追記。[espradio v0.4.0](https://github.com/tinygo-org/espradio/releases/tag/v0.4.0)では、[PR #96](https://github.com/tinygo-org/espradio/pull/96)の`Esplink.NTP()`と[PR #97](https://github.com/tinygo-org/espradio/pull/97)の`espradio.RSSI()`が使えます。サンプルコードでは独自のSNTP通信とRSSI用cgoラッパーを外しました。時刻同期を呼び出して時計の差分を反映する処理は、引き続きデバイス側に必要です。本書の測定値は更新前の実装によるものです。
