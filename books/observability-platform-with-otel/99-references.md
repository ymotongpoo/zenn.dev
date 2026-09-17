---
title: "参考リンク"
---

本書で参照した一次情報を章別に示します。本文中の安定度とバージョンは、2026年9月16日に確認した値です。9章の測定条件と、過去のリリース履歴については、記載した当時の版を示しています。利用時には各リンク先で最新の状態を確認してください。

## 全体

- [OpenTelemetry公式ドキュメント](https://opentelemetry.io/ja/docs/)
- [Platform Engineering Kaigi 2026 セッション概要](https://www.cnia.io/pek2026/sessions/eba4a57f-e4f0-4201-b731-0a37d6a53f7a/)
- 『[OpenTelemetryではじめるテレメトリーサンプリング](https://amzn.to/4cQG9i6)』（自著。ヘッドサンプリングとテイルサンプリングの設計、量とコストの見積もりを扱った本。2章のサンプリングの節から参照しています）
- サンプルリポジトリ [otel-platform-blueprint](https://github.com/ymotongpoo/otel-platform-blueprint)
- 登壇スライド <!-- 公開後にURLを入れる -->

## 2章 SDKディストリビューション

- [Distributions（概念の定義）](https://opentelemetry.io/ja/docs/concepts/distributions/)
- [opentelemetry-go](https://github.com/open-telemetry/opentelemetry-go) と [versions.yaml（モジュール別の安定度）](https://github.com/open-telemetry/opentelemetry-go/blob/main/versions.yaml)
- [仕様のコンプライアンス表（環境変数対応状況）](https://github.com/open-telemetry/opentelemetry-specification/blob/main/spec-compliance-matrix.md)
- [autoexport](https://pkg.go.dev/go.opentelemetry.io/contrib/exporters/autoexport) と [autoprop](https://pkg.go.dev/go.opentelemetry.io/contrib/propagators/autoprop)
- [otelconf（declarative configurationのGo実装）](https://pkg.go.dev/go.opentelemetry.io/contrib/otelconf) と [opentelemetry-configuration（設定スキーマ）](https://github.com/open-telemetry/opentelemetry-configuration)
- [計装ライブラリのレジストリ](https://opentelemetry.io/ja/ecosystem/registry/)
- [OpenTelemetryのConsistent Probability Samplingを理解する（自著）](https://zenn.dev/ymotongpoo/articles/20260717-cps)

## 3章 ゼロコード計装

- [Zero-code instrumentation](https://opentelemetry.io/ja/docs/zero-code/)
- [OBI（OpenTelemetry eBPF Instrumentation）](https://opentelemetry.io/ja/docs/zero-code/obi/) と [2026年の目標を述べた公式ブログ](https://opentelemetry.io/blog/2026/obi-goals/)
- [otelc v1の発表（Goのコンパイル時計装）](https://opentelemetry.io/blog/2026/go-compile-time-instrumentation-v1/)
- [OpenTelemetry OperatorによるKubernetesでの自動計装](https://opentelemetry.io/ja/docs/platforms/kubernetes/operator/automatic/)
- 『[OpenTelemetry eBPF Instrumentationの舞台裏](https://zenn.dev/ymotongpoo/books/go-ebpf-primer)』（自著。GoバイナリへのeBPF計装の制約を扱った本）

## 4章 Collector層

- [OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/)
- [Building a custom Collector（OCB）](https://opentelemetry.io/ja/docs/collector/extend/ocb/)
- [opentelemetry-collector](https://github.com/open-telemetry/opentelemetry-collector) と [opentelemetry-collector-contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib)
- [opentelemetry-collector-releases（公式配布物のビルドパイプライン）](https://github.com/open-telemetry/opentelemetry-collector-releases)

## 5章 フリート管理

- [Management（Collector管理の公式ドキュメント）](https://opentelemetry.io/ja/docs/collector/management/)
- [OpAMP仕様](https://github.com/open-telemetry/opamp-spec/blob/main/specification.md)
- [opamp-go](https://github.com/open-telemetry/opamp-go)
- [OpAMP Supervisor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/cmd/opampsupervisor)

## 6章 セマンティック規約とWeaver

- [Semantic conventions](https://opentelemetry.io/docs/specs/semconv/) と [semantic-conventionsリポジトリ](https://github.com/open-telemetry/semantic-conventions)
- [OpenTelemetry Weaver](https://github.com/open-telemetry/weaver) と [カスタムレジストリ定義のガイド](https://github.com/open-telemetry/weaver/blob/main/docs/define-your-own-telemetry-schema.md)
- [opentelemetry-weaver-packages（公式ポリシー集）](https://github.com/open-telemetry/opentelemetry-weaver-packages)
- [opentelemetry-weaver-examples（動作するサンプル集）](https://github.com/open-telemetry/opentelemetry-weaver-examples)
- [公式Go semconvパッケージの生成テンプレート](https://github.com/open-telemetry/opentelemetry-go/tree/main/semconv/templates)
- [Observability by Design（公式ブログ。semconv運用へのWeaver適用）](https://opentelemetry.io/blog/2025/otel-weaver/)

## 7章 AIワークロードのテレメトリー

- [semantic-conventions-genai（GenAI規約の専用リポジトリ）](https://github.com/open-telemetry/semantic-conventions-genai)
- [Inside the LLM Call（公式ブログ）](https://opentelemetry.io/blog/2026/genai-observability/)
- [opentelemetry-python-genai（Python公式のGenAI計装）](https://github.com/open-telemetry/opentelemetry-python-genai)
- [Claude CodeとCodex CLIのテレメトリーをGrafana Cloudで見る（自著）](https://zenn.dev/ymotongpoo/articles/20260616-ai-cli-otel-grafana)

## 8章 AIによる読み取り

- [MCPのセマンティック規約](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/mcp.md)
- [AI エージェント Observability（公式ブログ）](https://opentelemetry.io/blog/2025/ai-agent-observability/)
- [Model Context Protocol](https://modelcontextprotocol.io/)

## Platform Engineering関連

- Matthew Skelton, Manuel Pais 著『[Team Topologies](https://teamtopologies.com/)』（邦訳『[チームトポロジー](https://amzn.to/4rhgFAt)』）
- [Platform Engineering（CNCF Platforms White Paper）](https://tag-app-delivery.cncf.io/whitepapers/platforms/)
