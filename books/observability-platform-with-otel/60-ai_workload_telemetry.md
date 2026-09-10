---
title: "AIワークロードのテレメトリー"
---

あるチームが、LLMを使った要約機能をプロダクトへ追加したとします。一か月後、経理からAPI利用料の機能別内訳を、SREから要約機能のレイテンシSLOを求められました。既存のダッシュボードではHTTPメトリクスを確認できますが、トークン使用量とモデルごとのレイテンシは記録していません。

AIワークロードも、SDKディストリビューション、Collector、セマンティック規約で観測できます。ただし、従来のWebサービスとは記録する情報が異なるため、規約と計装を拡張します。

## AIワークロードの観測対象

LLMを使うワークロードには、従来のWebサービスと異なる性質があります。

- 出力が非決定的である。同じ入力でも結果が変わるため、「正しく動いているか」を再現テストだけでは保証できず、本番のテレメトリーで品質を監視し続ける必要がある
- コストの単位がトークンである。リクエスト数ではなく入出力のトークン数が請求額を決めるため、コスト管理はトークン使用量の計測を前提にする
- レイテンシの支配要因がLLM呼び出しである。数十ミリ秒の世界に数秒から数十秒の呼び出しが混ざり、ストリーミング応答では「最初のトークンまでの時間」という新しい指標が意味を持つ
- 品質がエラーレートで測れない。HTTP 200で返ってきた見当違いの要約は、従来のゴールデンシグナルでは検出できない

これらを計測するには、モデル、トークン数、処理段階、品質評価などの記録方法を定義します。50章のレジストリで、属性の名前、型、記録条件を管理します。

## GenAIセマンティック規約の現状

OpenTelemetryには、生成AI向けのセマンティック規約（`gen_ai.*`）があります。採用時には、2026年8月時点の安定性と配布方法を確認します。

GenAI規約は2026年6月に、semantic conventions本体から専用の[semantic-conventions-genai](https://github.com/open-telemetry/semantic-conventions-genai)リポジトリへ分離されました。`gen_ai.*` に加えて、MCP関連の `mcp.*` もこのリポジトリで管理されています。2026年8月時点では、すべてのGenAI規約がDevelopment段階であり、stableの定義はありません。専用リポジトリにはバージョン付きリリースもないため、特定バージョンへの準拠を宣言できない状態です。

実際、属性名はこれまでに何度も変わってきました。主要な改名だけでも次のとおりです。

| 旧 | 現行 | 変更時期 |
|---|---|---|
| `gen_ai.usage.prompt_tokens` | `gen_ai.usage.input_tokens` | v1.27.0（2024年8月） |
| `gen_ai.usage.completion_tokens` | `gen_ai.usage.output_tokens` | v1.27.0（2024年8月） |
| `gen_ai.system` | `gen_ai.provider.name` | v1.37.0（2025年8月） |
| メッセージ毎のイベント（`gen_ai.user.message` など） | スパン属性 `gen_ai.input.messages` ほか | v1.37.0（2025年8月） |

この変更頻度を前提に、gen_ai属性を社内レジストリの依存として取り込みます。上流で属性名が変わった場合は、diffで差分を検出し、生成コードとgatewayの変換設定を同じ変更として更新します。

リリースのないリポジトリの `main` を依存先にすると、同じ社内レジストリを後日解決した結果が変わります。依存はコミットSHAで固定し、採用したSHA、採用日、上流のschema_urlを社内レジストリへ記録します。更新は定期的なPRで取り込み、diffを確認します。上流でリリースが始まった後は、タグによる固定へ移行します。

現行の規約では、スパンをモデル呼び出しとエージェント処理に分けます。スパン名には `chat gpt-4` のように操作名とモデル名を使います。操作の種類は `gen_ai.operation.name`、プロバイダーは `gen_ai.provider.name`、要求と応答のモデルは `gen_ai.request.model` と `gen_ai.response.model`、トークン使用量は `gen_ai.usage.input_tokens` と `gen_ai.usage.output_tokens` で記録します。

メトリクスには、トークン使用量のヒストグラム `gen_ai.client.token.usage`、操作レイテンシの `gen_ai.client.operation.duration`、ストリーミングで最初のチャンクを受け取るまでの時間などがあります。これらを機能名などの社内属性と組み合わせることで、冒頭の費用内訳とレイテンシSLOを計算できます。

## プロンプト記録のトレードオフ

GenAI観測では、プロンプトと応答の本文を記録するかどうかを決めます。

本文を記録できれば、「なぜこの要約が出たのか」を入力から直接調べられ、品質評価の材料にもなります。一方で本文は、個人情報や機密情報を含み得る高リスクなデータであり、サイズも大きいためテレメトリーのコストを押し上げます。

規約では、本文を運ぶ `gen_ai.input.messages` や `gen_ai.output.messages` などを**Opt-In**としています。既定では記録せず、計装側の設定で明示的に有効化します[^capture]。

[^capture]: たとえば公式のPython計装では環境変数 `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` で記録先（記録しない、スパンのみ、イベントのみ、両方）を制御します。これは規約ではなく計装ライブラリ側の仕様なので、言語やライブラリごとの差に注意が必要です。

本文には自然言語のメッセージ、ツールの引数、外部リソースへの参照が含まれるため、gatewayの変換規則だけでは個人を特定できる情報（PII）や機密情報をすべて識別できません。複数の段階で保護します。

1. 既定では本文を記録しない
2. 有効化するサービスは、扱うデータの分類と利用目的を登録したうえで、SDK側で許可したフィールドだけを記録する
3. gatewayのredaction（30章）は、既知のパターンに対する追加の防御として使う
4. 本文を含むテレメトリーは専用のパイプラインに分け、短い保持期間と限定した閲覧権限で扱う
5. 記録してはならない既知のデータが流れていないかを、live-check（50章）や結合テストで検査する

基盤が管理できる範囲は、保存先、権限、保持期間、既知パターンの削除です。任意の自然言語から機密情報を完全に除くことは保証できません。開発チームはこの制約を踏まえて本文記録を有効化します。

## GoでのLLM呼び出し計装

2026年8月時点では、Python向けの公式計装が先行し、専用リポジトリでOpenAI、Anthropic、LangChainなどの計装パッケージを提供しています。GenAI計装の公式プロジェクトが対象とするのはPythonとJavaScriptで、Goには公式のGenAI計装ライブラリがありません。Goではサードパーティ製ライブラリか手動計装を使います。

10章のディストリビューションでSDKを初期化していれば、手動計装ではLLM呼び出しを囲むスパンを追加します。次の例はトレースだけの抜粋であり、トークン使用量のヒストグラムなどのメトリクスは省略しています。属性名には、レジストリから生成した `semconv` パッケージの定数を使います。

```go
func (c *SummaryClient) Summarize(ctx context.Context, doc string) (string, error) {
	ctx, span := c.tracer.Start(ctx, "chat "+c.model,
		// SpanKind: 外部サービスを呼び出す側のスパンであることを示す種別
		trace.WithSpanKind(trace.SpanKindClient),
		trace.WithAttributes(
			semconv.GenAIOperationNameChat,
			semconv.GenAIProviderNameKey.String(c.provider),
			semconv.GenAIRequestModelKey.String(c.model),
		),
	)
	defer span.End()

	resp, err := c.llm.Chat(ctx, buildPrompt(doc))
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, err.Error())
		span.SetAttributes(semconv.ErrorTypeKey.String(errType(err)))
		return "", err
	}
	span.SetAttributes(
		semconv.GenAIResponseModelKey.String(resp.Model),
		semconv.GenAIUsageInputTokensKey.Int(resp.Usage.InputTokens),
		semconv.GenAIUsageOutputTokensKey.Int(resp.Usage.OutputTokens),
	)
	return resp.Text, nil
}
```

現行の規約では、エラーで終わった呼び出しに `error.type` 属性を付けることが条件付きで要求されています。この例では、ステータスに加えて例外と属性を記録します。`errType` は、エラー種別の文字列を返すディストリビューションのヘルパーです。実際のディストリビューションでは、この定型処理全体をヘルパーとして提供します。属性定数を再生成して名前が変われば、コンパイルエラーから移行が必要な箇所を見つけられます。

## エージェントのトレース構造

ツールを使って複数段の処理を行うエージェント型アプリケーションでは、各処理を親子関係のあるスパンとして記録します。規約は、エージェント実行の `invoke_agent`、ツール実行の `execute_tool` などを定義しています。

![AIエージェントアプリのトレース構造](/images/20260926-agent-trace.png)
*図1　矢印はスパンの親子関係を表します。エージェント実行の子スパンは左から時間順に並び、gen_ai属性は紫色のスパンに付きます。*

ツールが社内APIを呼び出す場合、その下には通常の分散トレースが続きます。エージェントの処理とマイクロサービスの処理を一つのトレースとして追跡できるため、既存のオブザーバビリティ基盤を利用できます。会話をまたぐ相関には `gen_ai.conversation.id` 属性を使います。

Claude CodeやCodexなどのAI開発ツールは、自身のテレメトリーをOpenTelemetry形式で出力します。AIツールの利用状況を収集する方法は、[別の記事](https://zenn.dev/ymotongpoo/articles/20260616-ai-cli-otel-grafana)で解説しています。

## 三本柱への変更

AIワークロード向けの変更は、三本柱へ分けて実装します。

- セマンティック規約のガバナンス（50章）には、gen_ai属性群をSHA固定の依存として取り込み、AI固有の社内属性（機能名やプロンプトのバージョンなど）を `com.example.*` に定義する。規約がDevelopment段階だからこそ、改名への追従をレジストリのdiffと生成で機械化しておく
- SDKディストリビューション（10章）には、LLM呼び出し計装のヘルパーと、トークン使用量メトリクスの既定の計測を足す。Goに公式計装がない今、ディストリビューションがその穴を埋める
- Collector層（30章）には、AI向けの統制を足す。本文を含むテレメトリーの分離パイプライン、既知パターンのredaction、トークン使用量からのコスト集計、大きなスパンへのサイズ制限はgatewayの仕事になる

開発チームは本文記録を有効化するか判断し、基盤は本文を含むテレメトリーの保存先、権限、保持期間を管理します。AIワークロード専用の基盤を増やさず、既存の配布と統制を拡張します。
