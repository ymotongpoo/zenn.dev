---
title: "参考文献"
---

本書で参照した一次情報の一覧です。いずれも2026年10月21日に確認しました。ドキュメントはバージョンを固定したURLを優先しています。

## 検証環境

| 対象 | バージョン | 入手先 |
| --- | --- | --- |
| k6 | v2.3.0（`grafana/k6:2.3.0@sha256:9c2dee7f8ed74d317e4027c06a10f169b625638189de8d4555d0b3486a5aeb34`） | [grafana/k6](https://github.com/grafana/k6/releases/tag/v2.3.0) |
| Go | 1.27.3（`golang:1.27.3`） | [go.dev](https://go.dev/dl/) |
| OpenTelemetry Go | v1.47.0 | [open-telemetry/opentelemetry-go](https://github.com/open-telemetry/opentelemetry-go/releases/tag/v1.47.0) |
| otelhttp | v0.72.0 | [opentelemetry-go-contrib](https://github.com/open-telemetry/opentelemetry-go-contrib/releases/tag/v1.47.0) |
| otelslog | v0.21.0 | 同上 |
| Grafana Alloy | v1.20.1 | [grafana/alloy](https://github.com/grafana/alloy/releases/tag/v1.20.1) |
| Grafana Mimir | 3.2.2 | [grafana/mimir](https://github.com/grafana/mimir/releases/tag/mimir-3.2.2) |
| Grafana Tempo | 3.1.0 | [grafana/tempo](https://github.com/grafana/tempo/releases/tag/v3.1.0) |
| Grafana Loki | 3.7.8 | [grafana/loki](https://github.com/grafana/loki/releases/tag/v3.7.8) |
| Grafana | 13.2.3 | [grafana/grafana](https://github.com/grafana/grafana/releases/tag/v13.2.3) |

サンプルのコードと実験のスクリプトは[ymotongpoo/k6-otel-perf-review](https://github.com/ymotongpoo/k6-otel-perf-review)にあります。コンテナイメージのダイジェストは、このリポジトリの`compose.yaml`と`Dockerfile`に固定してあります。

## k6

- [Open and closed models](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/concepts/open-vs-closed/)：閉じたモデルと開いたモデルの定義、coordinated omission（3章）
- [Dropped iterations](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/concepts/dropped-iterations/)：始められなかった反復と閾値での扱い（4章）
- [Constant arrival rate](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/executors/constant-arrival-rate/)：`preAllocatedVUs`と`maxVUs`（3章、4章）
- [Arrival-rate VU allocation](https://grafana.com/docs/k6/v2.3.x/using-k6/scenarios/concepts/arrival-rate-vu-allocation/)：VUを前もって用意する理由（3章、4章）
- [Test lifecycle](https://grafana.com/docs/k6/v2.3.x/using-k6/test-lifecycle/)：VUと反復の定義、VUごとの初期化（2章、4章）
- [Thresholds](https://grafana.com/docs/k6/v2.3.x/using-k6/thresholds/)：合否の条件と終了コード（4章）
- [Built-in metrics](https://grafana.com/docs/k6/v2.3.x/using-k6/metrics/reference/)：`http_req_duration`、`http_req_failed`、`dropped_iterations`の定義（2章、4章）
- [OpenTelemetry output](https://grafana.com/docs/k6/v2.3.x/results-output/real-time/opentelemetry/)：OTLPでのメトリクスの出力（5章）
- k6 v2.3.0の[`errext/exitcodes/codes.go`](https://github.com/grafana/k6/blob/v2.3.0/errext/exitcodes/codes.go)：終了コード99（4章）
- k6 v2.3.0の[`lib/netext/httpext/tracer.go`](https://github.com/grafana/k6/blob/v2.3.0/lib/netext/httpext/tracer.go)：サンプルの時刻（4章）
- k6 v2.3.0の[`lib/executor/constant_arrival_rate.go`](https://github.com/grafana/k6/blob/v2.3.0/lib/executor/constant_arrival_rate.go)：反復を捨てる条件とVUの追加（4章）
- k6 v2.3.0の[`internal/output/opentelemetry/output.go`](https://github.com/grafana/k6/blob/v2.3.0/internal/output/opentelemetry/output.go)：メトリクスの単位（5章）

## OpenTelemetry

- [OpenTelemetry Go](https://opentelemetry.io/ja/docs/languages/go/)（2章、5章）
- [otelhttp v0.72.0](https://pkg.go.dev/go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp@v0.72.0)（5章）
- [otelslog v0.21.0](https://pkg.go.dev/go.opentelemetry.io/contrib/bridges/otelslog@v0.21.0)（5章）
- [Tracing API（v1.61.0）](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/trace/api.md#spankind)：スパンの種別（7章）
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)（5章）
- [Deprecating Span Events API](https://opentelemetry.io/blog/2026/deprecating-span-events/)：スパンイベントとログ（6章）

## Grafanaのスタック

- [Grafana Alloy v1.20](https://grafana.com/docs/alloy/v1.20/)（5章）
- [Grafana Mimir v3.2.x](https://grafana.com/docs/mimir/v3.2.x/)と[設定のリファレンス](https://grafana.com/docs/mimir/v3.2.x/configure/configuration-parameters/)：OTLPのメトリクス名の変換（5章）
- [Grafana Tempo v3.1.x](https://grafana.com/docs/tempo/v3.1.x/)と[TraceQL](https://grafana.com/docs/tempo/v3.1.x/traceql/)（5章、6章）
- [Grafana Loki v3.7.x](https://grafana.com/docs/loki/v3.7.x/)（5章）

## その他

- [Little's law](https://en.wikipedia.org/wiki/Little%27s_law)（3章）
