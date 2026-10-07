---
title: "参考文献"
---

本書で参照した一次資料です。リンク先の内容は、2026年10月7日に確認したものです。

## OpenTelemetryの仕様とドキュメント

- [その他の言語](https://opentelemetry.io/ja/docs/languages/other/)：公式の実装を持たない言語と、SIGの設立が要望されている言語の一覧
- [open-telemetry/community#828](https://github.com/open-telemetry/community/issues/828)：Perl SIGへの関心を集めるissue
- [レジストリ（Perl）](https://opentelemetry.io/ja/ecosystem/registry/?language=perl)：CPANのAPI、SDK、エクスポーター、計装ライブラリの登録
- [Library Guidelines（v1.61.0）](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/library-guidelines.md)：APIとSDKの分離と、ライブラリがAPIにだけ依存すること
- [Tracing API（v1.61.0）](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/trace/api.md#set-status)：スパンのステータスを誰が設定するか
- [Tracing SDK（v1.61.0）](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/trace/sdk.md#batching-processor)：Batchプロセッサーの送信の契機と、`Shutdown` と `ForceFlush` の関係
- [HTTP spans（Semantic Conventions v1.44.0）](https://github.com/open-telemetry/semantic-conventions/blob/v1.44.0/docs/http/http-spans.md)：HTTPのスパン名と、`server.address` と `server.port` の決め方
- [OTLP Specification](https://opentelemetry.io/ja/docs/specs/otlp/)：OTLPの転送方式とエンコーディング
- [Logs](https://opentelemetry.io/docs/specs/otel/logs/)：既存のロギングライブラリからログを流すという、ログの仕様の方針
- [トレース](https://opentelemetry.io/ja/docs/concepts/signals/traces/)と[コンテキスト伝搬](https://opentelemetry.io/ja/docs/concepts/context-propagation/)：スパン、トレース、トレースコンテキストの説明
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)：`traceparent` ヘッダーの形式

## CPANの実装

- [OpenTelemetry 0.039](https://metacpan.org/release/JJATRIA/OpenTelemetry-0.039)と[リポジトリ](https://github.com/jjatria/perl-opentelemetry)（タグ `0.039`）：API、計装、`Log::Any` のアダプター、Guides
- [OpenTelemetry::SDK 0.028](https://metacpan.org/release/JJATRIA/OpenTelemetry-SDK-0.028)と[0.029-TRIAL](https://metacpan.org/release/JJATRIA/OpenTelemetry-SDK-0.029-TRIAL)、[リポジトリ](https://github.com/jjatria/perl-opentelemetry-sdk)（タグ `0.028`、`0.029`）：SDK
- [0.028のBatchプロセッサー](https://github.com/jjatria/perl-opentelemetry-sdk/blob/0.028/lib/OpenTelemetry/SDK/Trace/Span/Processor/Batch.pm)と[0.029の共通のBatchプロセッサー](https://github.com/jjatria/perl-opentelemetry-sdk/blob/0.029/lib/OpenTelemetry/Processor/Batch.pm)
- [OpenTelemetry::Exporter::OTLP 0.021](https://metacpan.org/release/JJATRIA/OpenTelemetry-Exporter-OTLP-0.021)と[リポジトリ](https://github.com/jjatria/perl-opentelemetry-exporter-otlp)：OTLPエクスポーター
- [Plack::Middleware::OpenTelemetry 0.262410](https://metacpan.org/release/ABH/Plack-Middleware-OpenTelemetry-0.262410)と[リポジトリ](https://github.com/abh/Plack-Middleware-OpenTelemetry)（タグ `v0.262410`）：PSGIのミドルウェア
- [jjatria/perl-opentelemetry#23](https://github.com/jjatria/perl-opentelemetry/issues/23)：IO::Asyncのループを回さないプロセスで送信が止まる報告と、作者の返答
- [jjatria/perl-opentelemetry-sdk#7](https://github.com/jjatria/perl-opentelemetry-sdk/pull/7)：送信をプロセスの中で行うための提案
- [IO::Async::Function](https://metacpan.org/pod/IO::Async::Function)：SDKが送信に使うワーカープロセスの仕組み
- [OpenTelemetry::Guides::Exporters](https://metacpan.org/pod/OpenTelemetry::Guides::Exporters)と[IO::Async::Loop::Mojo](https://metacpan.org/pod/IO::Async::Loop::Mojo)：MojoliciousのイベントループでSDKの送信を動かす方法

## OBI

- [OpenTelemetry eBPF Instrumentation](https://opentelemetry.io/ja/docs/zero-code/obi/)：概要、対応言語、カーネルの要件
- [Distributed traces](https://opentelemetry.io/docs/zero-code/obi/distributed-traces/)：ネットワークレベルの伝搬と、`/sys/fs/cgroup` のマウント
- [Trace context association](https://opentelemetry.io/docs/zero-code/obi/context-propagation/)：受信と送信の親子を決める仕組み
- [Security](https://opentelemetry.io/docs/zero-code/obi/security/#required-host-mount-for-context-propagation)：影響を受けるカーネルで必要な `/sys/kernel/tracing` のマウント
- [Service discovery](https://opentelemetry.io/docs/zero-code/obi/configure/service-discovery/)：計装対象の選び方、サービス名の決め方、計装済みのサービスの除外
- [Docker setup](https://opentelemetry.io/docs/zero-code/obi/setup/docker/)：DockerでOBIを動かす手順
- [opentelemetry-ebpf-instrumentation v0.14.0](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/tree/v0.14.0)：本書で使ったOBIのソース。FIONREADの補正は `pkg/internal/ebpf/tpinjector/` にある
- [OBIの最初のリリースの告知](https://opentelemetry.io/blog/2025/obi-announcing-first-release/)：Beylaの寄贈からの経緯

## Goのサービス

- [OpenTelemetry Go](https://opentelemetry.io/ja/docs/languages/go/)：Go向けのAPIとSDK
- [otelhttp](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp)：`net/http` のハンドラーの計装

## 実験の環境

- [otel/opentelemetry-collector-contrib](https://hub.docker.com/r/otel/opentelemetry-collector-contrib)：本書ではタグ `0.162.0` を使用
- [grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm)：本書ではタグ `0.32.1` を使用
- [Docker公式のperlイメージ](https://hub.docker.com/_/perl)：本書ではタグ `5.44.0` を使用
- [Carton](https://metacpan.org/pod/Carton)：CPANの依存の固定に使用

## 本書のデモ

- [ymotongpoo/otel-for-perl](https://github.com/ymotongpoo/otel-for-perl)：題材のアプリケーション、Composeの構成、計装のバリエーション、実験に使ったスクリプト
