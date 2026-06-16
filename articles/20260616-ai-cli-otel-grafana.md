---
title: "Claude CodeとCodex CLIのテレメトリーをGrafana Cloudで見る"
emoji: "🤖"
type: "tech"
topics: ["OpenTelemetry", "grafana", "ClaudeCode", "Codex", "Alloy"]
published: true
published_at: 2026-06-16 17:00
---

## はじめに

こんにちは、Grafana Labsでデベロッパーアドボケイトをしているものです。

最近は手元のマシンで Claude Code と Codex CLI を毎日のように動かしています。これだけ使っていると、「自分はどのモデルをどれくらい使っていて、トークンとコストはどうなっているのか」「ターンのレイテンシーや最初のトークンまでの時間（TTFT）はどれくらいか」が気になってきます。

幸い、最近のAIコーディングエージェントCLIは[OpenTelemetry](https://opentelemetry.io/) に対応しているものが増えてきました。そこで「3つのCLI（Claude Code / Codex / Cursor CLI）のテレメトリーを Grafana Cloud に送って可視化する」というのを実際にやってみました。

結論から言うと、Claude Code と Codex は最終的にメトリクス・ログ・トレースのすべてを Grafana Cloud に送れました。ただし途中で「delta temporality でメトリクスが全部弾かれる」という罠があったので、その辺の実際のハマりどころも含めて記録しておきます。

## 各CLIのOpenTelemetry対応状況

まず調査した結果がこちらです（2026年6月時点）。

| CLI | ネイティブOTel対応 | 設定方法 | gen_ai.* 準拠 |
|---|---|---|---|
| **Claude Code** | あり | 環境変数 / `settings.json` の `env` ブロック。メトリクス、ログ、トレース (beta) | `claude_code.llm_request` スパンに `gen_ai.system` / `gen_ai.request.model` などが付く |
| **Codex CLI** | あり | `~/.codex/config.toml` の `[otel]` セクション。メトリクス、ログ、トレース | 現状は `codex.*` 独自命名でOpenTelemetryのGen AIセマンティック規約に未準拠 |
| **Cursor CLI** | なし | 一次対応なし（サードパーティのhook/MCPのみ） | - |

Cursor CLI はネイティブのOTel対応がなく、サードパーティのラッパーもIDE向けで非公式なので、今回は見送りました。これ以降は Claude Code と Codex の話を書きます。

## アーキテクチャ

Grafana Cloud は OTLP gateway（`https://otlp-gateway-<zone>.grafana.net/otlp`）で OTLP/HTTP を受け付けます。なので各CLIから直接そこへ送ることもできます。

ただ今回はこういう構成にしました。

```text
Claude Code ─┐
             ├─→ 127.0.0.1:4318 (OTLP) ─→ Grafana Alloy ─(Basic auth)→ Grafana Cloud OTLP gateway
Codex ───────┘                            (トークンはAlloyだけが持つ)
```

理由はシンプルで、「認証トークンを各CLIの設定ファイルに平文で置きたくなかった」からです。Alloy [^alloy] を1段挟めば、トークンは Alloy の設定にだけ存在し、CLI側の設定はすべて `localhost` 宛て・認証なしで済みます。また、このマシンには元々 Grafana Alloy でLinuxホストの諸々のテレメトリーを送っていたので、そういった都合もあります。そうした都合から、新しいCollectorを立てるのではなく、既存のAlloyにOTLPの受信口を1つ足すだけで対応できました。

[^alloy]: ここでは Grafana Alloyを使っていますが、OTLPレシーバーとOTLPエクスポーターがあるOpenTelemetry Collectorディストリビューションであればなんでも良いです。

:::message
ちょうどよい機会だったので手元の Alloy を `v1.11.3 → v1.17.0` に上げました。後述する `deltatocumulative` を使うのに新しめのバージョンがあると安心です。
:::

## CLI側の設定

### Claude Code

`~/.claude/settings.json` の `env` ブロックに書きます。同じホストで動いてるAlloyに送るので、エンドポイントは `localhost`、トークンは無しです。

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_TRACES_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
    "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": "cumulative"
  }
}
```

`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` を付けると、メトリクスとログに加えてトレース（beta）も出せます。`claude_code.interaction → claude_code.llm_request → claude_code.tool` というスパンツリーで、`llm_request` スパンには `gen_ai.system` や `input_tokens` / `output_tokens` / `ttft_ms` などが付与されます。

最後の `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=cumulative` が後述の罠への対策です。

### Codex CLI

`~/.codex/config.toml` の `[otel]` セクションです。

```toml
[otel]
environment = "production"
log_user_prompt = false
exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "binary" } }
metrics_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/metrics", protocol = "binary" } }
trace_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/traces", protocol = "binary" } }
```

## Alloy側の設定

既存の `/etc/alloy/config.alloy` に、OTLPの受信口と Grafana Cloud への送信口を追記します。

```hcl
// ローカルのCLI（Claude Code / Codex）からOTLPを受ける
otelcol.receiver.otlp "ai_clis" {
	grpc { endpoint = "127.0.0.1:4317" }
	http { endpoint = "127.0.0.1:4318" }

	output {
		metrics = [otelcol.processor.deltatocumulative.ai_clis.input]
		logs    = [otelcol.exporter.otlphttp.ai_grafana_cloud.input]
		traces  = [otelcol.exporter.otlphttp.ai_grafana_cloud.input]
	}
}

// delta temporality を cumulative に変換する（後述）
otelcol.processor.deltatocumulative "ai_clis" {
	output {
		metrics = [otelcol.exporter.otlphttp.ai_grafana_cloud.input]
	}
}

// Grafana Cloud OTLP gateway へ転送
otelcol.exporter.otlphttp "ai_grafana_cloud" {
	client {
		endpoint = "https://otlp-gateway-<zone>.grafana.net/otlp"
		auth     = otelcol.auth.basic.ai_grafana_cloud.handler
	}
}

otelcol.auth.basic "ai_grafana_cloud" {
	username = "<OTLP_INSTANCE_ID>"
	password = "<GRAFANA_CLOUD_TOKEN>"
}
```

トークンはこの Alloy の設定の中だけに存在します。`metrics:write` / `logs:write` / `traces:write` のスコープを持つアクセスポリシートークンを使ってください。

## はまったポイント
### Codexのconfig.tomlは環境変数を展開しない

Codexの公式ドキュメント [Advanced Configuration](https://developers.openai.com/codex/config-advanced) の「Observability and telemetry」のセクションには、`headers = { "x-otlp-api-key" = "${OTLP_TOKEN}" }` のように `[otel]` の `headers` で `${VAR}` を使って環境変数を参照する例が載っています。これを信じてトークンを環境変数経由にしようとしたのですが、実際には（少なくとも検証した `codex-cli 0.139.0` では）展開されませんでした。

ローカルのキャプチャ用Collectorに向けて検証したところ、送られてきた認証ヘッダーは文字どおり `Basic ${GRAFANA_OTLP_BASIC}` でした。`${...}` がそのまま文字列として飛んでいます。エンドポイント側でも `invalid URI ${...}` というエラーになりました。

幸い今回は「トークンは Alloy 側にだけ置く」設計だったので、Codex の config には `localhost` 宛て・認証なしで書けばよく、この件は問題になりませんでした。CLI設定にトークンを書かない構成にしておいて結果的に正解だった、という話でもあります。

### メトリクスだけ全部 HTTP 400 で弾かれる

設定して動かしてみると、トレースとログは Grafana Cloud に届くのに、メトリクスだけがすべて拒否されるという状態になりました。Alloy のログにはこう出ています。

```text
Exporting failed. Dropping data.
... rpc error: code = InvalidArgument desc = error exporting items,
request to .../otlp/v1/metrics responded with HTTP Status Code 400,
Message=otlp parse error: invalid temporality and type combination
for metric "codex.process.start"
... for metric "claude_code.cost.usage"
... for metric "claude_code.token.usage"
```

`invalid temporality and type combination` とあります。原因を切り分けるために、ローカルAlloyに `otelcol.exporter.debug` の設定を追加して、実際のメトリクスを覗いてみると、こうなっていました。

```text
-> Name: claude_code.cost.usage
-> DataType: Sum
-> IsMonotonic: true
-> AggregationTemporality: Delta
```

両方のCLIとも、メトリクスを delta temporality で送っていました。Grafana Cloud のメトリクスバックエンド（Mimir）はデフォルトで cumulative を期待するため、delta の Sum を弾いていました。そして厄介なことに、1つの不正なメトリクスがバッチに混ざるとそのリクエスト全体が400になるので、 `claude_code.cost.usage` や `claude_code.token.usage` といった他のメトリクスまで巻き添えで落ちていました。

これを踏まえて次のような対応を行いました。

- **Claude Code**：標準のOTel環境変数 `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=cumulative` に対応しているので、これを `settings.json` に足して cumulative で吐かせる。
- **Codex**：Claude Codeのような設定が無く、config.tomlにも temporality の設定が無いので、仕方なくAlloy側で `otelcol.processor.deltatocumulative` を挟んで delta → cumulative に変換する。

`deltatocumulative` は Alloy では experimental 扱いなので、サービス起動時に experimental を許可する必要があります。`/etc/default/alloy` でこう設定しました。

```sh
CUSTOM_ARGS="--stability.level=experimental"
```

これで Alloy を再起動すると、メトリクスが受理されるようになりました。Alloy の自己メトリクスで確認すると、`otelcol_exporter_sent_metric_points_total` が増え、`send_failed` は0、`otelcol_deltatocumulative_datapoints_total` がデータポイントを変換しているのが見えます。

:::message
`deltatocumulative` は Alloy のプロセス内で各系列の累積状態を保持します。Alloy を再起動すると基点が一旦リセットされますが、`increase()` はカウンタリセットを検知するので集計上は問題ありません。
:::

### AI Observability ではまだ確認できない

Grafana Cloud には[AI Observability](https://grafana.com/docs/grafana-cloud/monitor-applications/ai-observability/)という機能があります。これはAIエージェント専用のダッシュボードや分析機能が追加されているのですが、ここにはClaude CodeやCodex CLIのデータは2026年6月現在は表示されません。

AI Observability の作り込み済みダッシュボードはOpenTelemetry の GenAIセマンティック規約（`gen_ai.*`）を前提にしています。スパン名が `chat {model}` のような規約命名で、メトリクスが `gen_ai.client.token.usage` のような規約名で来ることを期待しています。

一方で今回CLIが送ってくるのは:

- **Claude Code**：スパンに `gen_ai.system` などの属性は付くものの、スパン名は `claude_code.*`、メトリクス名は `claude_code.*` で規約名ではない
- **Codex**：`session_loop` や `codex.*` で、そもそも `gen_ai.*` 規約に準拠していない

つまり、データ自体は Grafana Cloud のストア（Mimir / Loki / Tempo）にちゃんと入っていて Explore からは普通に引けるのですが、AI Observability の専用パネルにはそのままでは載りません。

そこで今回は「現実解」として、`claude_code.*` / `codex.*` をそのまま使ったCLIごとの専用ダッシュボードを作ることにしました。
コスト・トークン・セッション・TTFT・ターンのレイテンシーなどは、こちらの方が素直に可視化できます。

## ダッシュボードを gcx で作る

Grafana Cloud には[`gcx`](https://grafana.com/docs/grafana/latest/as-code/observability-as-code/grafana-cli/gcx/)という統合CLIがあります。これを使うと、まずメトリクスの「実際に保存されている名前」を確認できます。OTLP→Prometheus変換でサフィックスが付くため、`claude_code.cost.usage` は最終的に次のようになっていました。

```console
$ gcx metrics series '{__name__=~"claude_code.*|codex.*"}' --since 3h
claude_code_active_time_seconds_total
claude_code_cost_usage_USD_total
claude_code_session_count_total
claude_code_token_usage_tokens_total
codex_conversation_turn_count_total
codex_turn_token_usage_sum         # ヒストグラム(_sum/_count/_bucket)
codex_turn_ttft_duration_ms_milliseconds_bucket
codex_turn_e2e_duration_ms_milliseconds_bucket
...
```

`_USD` や `_tokens`、`_seconds`、`_total` のサフィックスが付くのが見えます。ダッシュボードのクエリは、こうしたサフィックスの揺れに強くしておくために `__name__` の正規表現マッチを使いました。

```promql
# トークン使用量（type別）
sum by (type) (rate({__name__=~"claude_code_token_usage.*"}[$__rate_interval]))

# コスト（model別、USD/s）
sum by (model) (rate({__name__=~"claude_code_cost_usage.*"}[$__rate_interval]))
```

面白かったのは Codex で、短い `codex exec` では出てこないものの、対話セッションだとヒストグラムで token usage / TTFT / ツール呼び出し回数 / ターンのレイテンシーをちゃんと出していた点です。これらはヒストグラムなので、こう書けます。

```promql
# TTFT p95
histogram_quantile(0.95,
  sum by (le) (rate(codex_turn_ttft_duration_ms_milliseconds_bucket[$__rate_interval])))

# トークン使用量（token_type別）
sum by (token_type) (rate(codex_turn_token_usage_sum[$__rate_interval]))
```

ダッシュボードのJSONは、`gcx` で直接アップロードできます。クラシックなインポートエンドポイントだと確実にアップロードできます。

```console
$ gcx api /api/folders -d '{"title":"AI Coding Agents"}'
$ gcx api /api/dashboards/db -d @claude-code-cli.json
$ gcx api /api/dashboards/db -d @codex-cli.json
```

これで Claude Code と Codex の専用ダッシュボードが Grafana Cloud に並びました。

![Claude Code CLI用ダッシュボード](/images/20260616-claude-code-dash)

:::message
`rate()` / `increase()` は窓の中に2点以上のサンプルが必要です。単発実行直後はパネルが空に見えることがありますが、使い続けてサンプルが溜まれば埋まります。
:::

## まとめ

手元のAIコーディングエージェントCLIのテレメトリーを Grafana Cloud に送る、という作業のポイントは次の通りでした。

- **Claude Code / Codex はネイティブでOTel対応**。Cursor CLI は現状ネイティブ非対応。
- 認証トークンをCLI設定に置かないために、**ローカルのGrafana Alloyを1段挟む**構成が便利。既存のAlloyにOTLP受信口を足すだけでよい。
- **両CLIともメトリクスは delta temporality** で送信。Mimirは cumulative を期待するので、Claude Codeは `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=cumulative`、Codexは Alloyの `deltatocumulative` プロセッサで変換する。
- **AI Observability アプリは `gen_ai.*` 規約前提**なので、`claude_code.*` / `codex.*` の独自テレメトリーはそのままでは載らない。現実解はCLIごとの専用ダッシュボードを作るか、ラベルの変換プロセスを挟んで規約に準拠するようにする。

「OTel対応」と書いてあっても、temporality やセマンティック規約の細かいところで一手間かかる、というのが実感でした。とはいえ一度パイプラインを通してしまえば、自分のAI利用のコストやレイテンシーが Grafana で眺められるのはなかなか楽しいです。同じことをやってみたい人の参考になれば幸いです。
