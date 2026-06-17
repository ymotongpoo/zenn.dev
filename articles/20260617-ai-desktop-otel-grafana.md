---
title: "Claude DesktopとCodex AppのテレメトリーをGrafana Cloudで見る (2026年6月)"
emoji: "🖥️"
type: "tech"
topics: ["OpenTelemetry", "grafana", "ClaudeCode", "Codex", "Alloy"]
published: true
published_at: 2026-06-17 16:30
---

## はじめに

[前回の記事](https://zenn.dev/ymotongpoo/articles/20260616-ai-cli-otel-grafana)でLinux上のClaude Code CLIとCodex CLIのOpenTelemetry形式のテレメトリーをGrafana Alloy経由でGrafana Cloudに送る方法を書きました。今回は同じことをmacOS上のGUIアプリ（Claude DesktopとCodex App）でやろうとして調べた結果をまとめます。

## TL;DR

Codex Appは前回とほぼ同じ手順で対応できますが、Claude Desktopは限定的です。GUIのチャット部分にはOpenTelemetryの設定項目が確認できませんでしたが、「ローカルコードセッション」として起動するClaude Code CLIは前回の設定がそのまま効きます。

## 各アプリのOTel対応状況

| アプリ | OTel対応 | 設定場所 |
|---|---|---|
| Claude Desktop（チャット画面） | 設定項目なし | — |
| Claude Desktopのローカルコードセッション（内部のClaude Code CLI） | 対応 | `~/.claude/settings.json` の `env` ブロック |
| Codex App（`app-server`） | 対応 | `~/.codex/config.toml`（ユーザーレベルのみ） |

## Claude Desktopについて

Claude Desktopの設定ファイルは `~/Library/Application Support/Claude/claude_desktop_config.json` に置かれていて、主な設定項目は `mcpServers`（MCPサーバーの定義）と `preferences`（表示設定等）のみで、OTelに関連する設定項目は見当たりません。公式のOpenTelemetry向け設定ドキュメント（[Monitoring usage | Claude Code](https://code.claude.com/docs/en/monitoring-usage)）はCLIツールを対象として書かれていて、Claude Desktopアプリに向けた設定手順は記載されていません。

一方、Claude Desktopには「ローカルコードセッション」という機能があって、デスクトップアプリの画面上でClaude Code CLIを実行できます。このモードではClaude Code CLIが起動し、`~/.claude/settings.json` の `env` ブロックを読み込むため、前回の記事で設定したOTel環境変数がそのまま機能します。デスクトップアプリ内でコードセッションを使っている場合は、追加の設定は不要です。

## Codex Appの設定

### ~/.codex/config.toml にOTelを設定する

Codex Appは内部的に `codex app-server` として動作し、ユーザーレベルの `~/.codex/config.toml` を読みます。前回の記事で書いたCodex CLI向けの `[otel]` セクションと同一の設定がそのままアプリにも効きます。

```toml
[otel]
environment = "production"
log_user_prompt = false
exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "binary" } }
metrics_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/metrics", protocol = "binary" } }
trace_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/traces", protocol = "binary" } }
```

設定後はCodex Appを再起動してください。

### ユーザーレベルの設定のみが有効

プロジェクト内の `.codex/config.toml` に `[otel]` セクションを書いても、`app-server` では無視されます（[openai/codex#17110](https://github.com/openai/codex/issues/17110)）。`app-server` が読むのはユーザーレベルの `~/.codex/config.toml` のみです。CLIと設定ファイルを共有しているため二重管理にはなりませんが、置き場所を間違えると無効になる点は注意が必要です。

### モードによる制限

既知の制限として、`codex mcp-server` はテレメトリーを出力しません。`codex exec` はメトリクスを出力しないという報告もあります（[openai/codex#12913](https://github.com/openai/codex/issues/12913)）。Codex Appの通常の対話セッションは `app-server` として動くため対象になります。動作確認は次節の方法でできます。

## macOS上のAlloyへの設定追加

Alloyをインストールしてない場合には、まずインストール。手軽なのでHomebrewでインストールします。

```console
brew install grafana/grafana/alloy
```

macOSでHomebrewからインストールしたAlloyの設定は `/opt/homebrew/etc/alloy/config.alloy` にあります。Linux（`/etc/alloy/config.alloy`）とパスが違いますが、設定の書き方は同じです。設定ファイルは[先日のもの](https://zenn.dev/ymotongpoo/articles/20260616-ai-cli-otel-grafana#alloy%E5%81%B4%E3%81%AE%E8%A8%AD%E5%AE%9A)と同じです。唯一変えてるのはAPIキーの設定を変えてるくらいです。

```hcl
otelcol.auth.basic "ai_grafana_cloud" {
    username = "<OTLP_INSTANCE_ID>"
    password = sys.env("GCLOUD_RW_API_KEY")
}
```

`GCLOUD_RW_API_KEY` はすでに `/opt/homebrew/etc/alloy/config.env` に設定してあります。エンドポイントのゾーンとOTLPインスタンスIDはGrafana CloudのConnectionsページから確認できます。

また `deltatocumulative` はAlloyでexperimental扱いのため、起動オプションに `--stability.level=experimental` が必要です。Linuxでは `/etc/default/alloy` の `CUSTOM_ARGS` に書きましたが、macOSのHomebrew版では次のように `/opt/homebrew/etc/alloy/extra-args.txt` に書きます。このファイルの内容が起動スクリプト（`alloy-wrapper`）によってそのままコマンド引数として渡されます。

```
--stability.level=experimental
```

`extra-args.txt` を保存後、Alloyを再起動します。

```sh
brew services restart grafana/grafana/alloy
```

## 動作確認

Codex Appでやり取りをしてから、AlloyのHTTPエンドポイントでOTLPの受信を確認します。

```console
$ curl -s http://localhost:12345/metrics | grep otelcol_receiver_accepted
otelcol_receiver_accepted_log_records_total{...} 42
otelcol_receiver_accepted_metric_points_total{...} 8
otelcol_receiver_accepted_spans_total{...} 15
```

カウンタが増えていればAlloyがデータを受信しています。送信側のカウンタ（`otelcol_exporter_sent_*`）も同様に増えていることを確認します。Grafana Cloud側は `gcx` で確認できます。

```console
$ gcx metrics series '{__name__=~"codex.*"}' --since 30m
```

## AppとCLIのメトリクスの違いを gcx で確認する

同じ `[otel]` 設定を使っていても、App（`codex app-server`）とCLI（`codex exec`）では送信されるメトリクスが異なります。`job` ラベルが送信元を示すので、まずこれで区別できます。

```console
$ gcx metrics series '{__name__="codex_turn_e2e_duration_ms_milliseconds_count"}' --since 24h --to now
{"__name__":"codex_turn_e2e_duration_ms_milliseconds_count","app_version":"0.139.0",
 "job":"codex_exec","model":"gpt-5.5","service_name":"codex_exec",...}
```

`job="codex_exec"` がCLI、`job="codex-app-server"` がAppです。

CLIは `codex_turn_*`（ターンのレイテンシーやトークン使用量）、`codex_conversation_turn_count_total`、`codex_websocket_*` など、ターンレベルの詳細なネイティブメトリクスを出力します。AppはこれらのネイティブCLIメトリクスをほとんど出力しない代わりに、トレース（スパン）を送信します。Grafana Cloudのメトリクス生成機能がスパンを元に `traces_spanmetrics_*` 系のメトリクスを生成するため、ターン単位の内部処理を別の形で観察できます。

```console
$ gcx metrics query 'sum by (span_name) (increase(traces_spanmetrics_calls_total[1h]))'
{"metric":{"span_name":"generateText claude-opus-4-6"},"value":[...,"15"]}
{"metric":{"span_name":"plugin/list"},"value":[...,"57.2"]}
{"metric":{"span_name":"config/read"},"value":[...,"4.4"]}
{"metric":{"span_name":"thread/list"},"value":[...,"1.1"]}
...
```

`generateText claude-opus-4-6` が実際のLLM呼び出し回数に相当します。`plugin/list` の回数が多いのはAppがバックグラウンドで定期的にプラグイン一覧を取得しているためです。

各ソースが出しているメトリクス一覧は `gcx metrics series` で絞り込んで確認できます。

```console
$ gcx metrics series '{job="codex-app-server"}' --since 24h --to now
$ gcx metrics series '{job="codex_exec"}' --since 24h --to now
```

実際にGrafanaのExploreでも確認できました。

![メトリクスがラベルで区別できる](/images/20260617-codex.png)

## まとめ

Codexは意外とすんなりテレメトリーデータが取れましたが、Claude Desktopの場合はセッションのテレメトリーが取れないとわかりました。Codexの場合、 `job` ラベルを使えばアプリとCLIの区別がつくので、クエリをする際にも楽に絞り込みができて良さそうです。
