---
title: "SDKディストリビューションの設計"
---

「サービスにOpenTelemetryを入れてください」と依頼された開発チームは、公式ドキュメントの初期化コードを自分のリポジトリに写すことから始めます。

本章はコード例にGoを使います。Goは静的にコンパイルされ、実行時にエージェントを差し込めないため、ディストリビューションを配る設計が分かりやすく現れます。ただし本章の論点はGo固有ではありません。どの言語でも、初期化の判断をライブラリ側へ移し、開発チームが書く量を減らす設計は同じです。言語ごとの違いは本章の最後で扱います。

Goの初期化コードは、次のようになります。

```go
func initTracer(ctx context.Context) (func(context.Context) error, error) {
	// エクスポーター（テレメトリーの送信部品）の組み立て
	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint("collector.internal.example.com:4317"),
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return nil, err
	}
	// リソース属性の設定
	res, err := resource.New(ctx,
		resource.WithAttributes(semconv.ServiceName("payment")),
	)
	if err != nil {
		return nil, err
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)
	// プロパゲーターの設定
	otel.SetTextMapPropagator(propagation.TraceContext{})
	return tp.Shutdown, nil
}
```

このコード自体は動きます。しかし、各チームが個別に書けば、初期化方法もチームごとに分かれます。

## 素のSDKで起きること

上のコードでは、Collectorのエンドポイントを直接指定しているため、環境ごとの変更方法を各チームが決めます。リソース属性は `service.name` しか設定しておらず、`deployment.environment.name` や `service.namespace` を追加するかどうかも統一されません。

プロパゲーターにはバゲッジを含めていません。**バゲッジ**（Baggage）は、トレースの文脈とともに任意のキーと値をリクエストへ載せて運ぶ仕組みです。後からバゲッジを使う設計を導入しても、このサービスでは属性を引き継げません。`SetTextMapPropagator` の呼び出し自体を忘れれば、トレースはこのサービスで分断されます。

メトリクスとログの初期化が実装されず、トレースだけを設定して「OpenTelemetryは導入済み」と判断されることもあります。

個々の差は小さくても、サービスを横断してテレメトリーを検索すると影響が現れます。リソース属性が欠ければ、どの環境のどのサービスが出したデータかを特定できません。プロパゲーターの違いはトレースを分断し、SDKバージョンの違いは、一部のサービスだけが修正済みの不具合を残す原因になります。

中央チームによる全サービスのレビューは、依頼の待ち時間を増やします。そこで、組織のデフォルト値を組み込んだ**SDKディストリビューション**を配り、初期化方法を配布物として統一します。

## ディストリビューションの役割

OpenTelemetryでは、SDKにデフォルト値やカスタマイズを加えて再パッケージしたものを[ディストリビューション](https://opentelemetry.io/ja/docs/concepts/distributions/)と呼びます。SDK本体を変更するフォークとは異なり、SDKの上に設定と部品の選択を重ねます。

オブザーバビリティベンダーが提供するSDKもディストリビューションの一例です。OTel SDKへ、自社バックエンド向けのデフォルト値、推奨する計装ライブラリとプロパゲーター、共通の初期化処理を追加しています。

社内プラットフォームでも、組織の環境に合わせたデフォルト値を組み込んだディストリビューションを配れます。

## 社内ディストリビューションの設計

社内ディストリビューションは、エクスポーター、リソース、プロパゲーター、サンプラーに関する共通の判断をアプリケーションコードから取り除きます。**サンプラー（sampler）** は、トレースを記録するかどうかを決める部品です。冒頭のコードにサンプラーがない場合も、SDKのデフォルト値を選んだことになります。開発チームが書くのは、社内ディストリビューション `otelinit` の呼び出しと、初期化に失敗した場合の処理です。

```go
shutdown, err := otelinit.Setup(ctx)
if err != nil {
	return fmt.Errorf("initialize telemetry: %w", err)
}
defer func() {
	_ = shutdown(context.Background())
}()
```

初期化に失敗したときにアプリケーションを停止するか、テレメトリーなしで続行するかは組織が決めます。上の例は、初期化に失敗したら起動しない方針です。続行を認める場合は、`Setup` がエラー時にも安全なno-opのshutdown関数を返すことと、初期化失敗をログなどで確認できることを、ディストリビューションの契約として文書化します。

`Setup` の中では次のことを行います。

- OTLP エクスポーターを構築する。エンドポイントのデフォルト値は各環境のエージェント Collector（4章）に向ける
- プロパゲーターをW3C TraceContext（トレースの文脈を運ぶ標準のヘッダ形式）とバゲッジの組み合わせに設定する
- サンプラーのデフォルトを `ParentBased(AlwaysSample)` にする。間引きの主体はゲートウェイ側（4章）に寄せる
- 実行環境（Kubernetesやクラウドプロバイダー）のメタデータからリソース属性を自動検出する
- トレース、メトリクス、ログのプロバイダー（計装のためのインスタンスを返すもの）を構築してグローバルに登録する

ログの組み込みでは、APIの安定性を考慮します。2026年9月時点で、Goのログ関連モジュール（`otel/log` と `otel/sdk/log`）の正式版はv0.22.0のベータであり、stableに達しているのはトレースとメトリクスです[^golog]。安定化に向けたv1.47.0-rc.1も公開されていますが、リリース候補の段階です。各チームがv0のAPIに直接依存すると、破壊的変更のたびに複数のサービスを修正することになります。ディストリビューションだけがv0のAPIに依存すれば、変更への対応箇所を1つに集約できます。

[^golog]: opentelemetry-goのモジュール構成とバージョンは[v1.46.0のversions.yaml](https://github.com/open-telemetry/opentelemetry-go/blob/v1.46.0/versions.yaml)で確認できます。mainブランチはリリース候補を含むため、採用する版のタグで確認してください。

サンプリングのデフォルト値には、処理できる流量の前提が必要です。SDKがトレースの開始時に記録の可否を決める方式を**ヘッドサンプリング**、Collectorがトレースの完結後に決める方式を**テイルサンプリング**と呼びます。ParentBasedは、親スパンの決定に従い、親がない場合にどう判定するかを別のサンプラーに委ねる仕組みです。Go SDKのデフォルトは `ParentBased(AlwaysSample)` で、親のないトレースは記録します。このデフォルトのまま、上流から未サンプリングの親が渡ってこない限り、SDKはスパンを間引きません。外部からのリクエストを受けるサービスや、ヘッドサンプリングを併用する場合は、上流の判定が伝搬してくることを前提に確認します。

テイルサンプリングへ判断を集約すると、エラーの有無やレイテンシを見て保存対象を選べます。ただし、すべてのスパンがアプリケーションからゲートウェイまで流れるため、SDK、エージェント、ネットワーク、ゲートウェイの負荷は減りません。この構成を使えるのは、各区間が全スパンの流量を処理できる場合です。高流量のサービスでは、SDKのヘッドサンプリングで先に量を減らします。プラットフォームは、`OTEL_TRACES_SAMPLER` 環境変数を調整して、どの段階で量を減らすかを決めます。

ヘッドサンプリングの確率をトレース全体で一貫させるConsistent Probability Samplingには、contribの[Go実装](https://pkg.go.dev/go.opentelemetry.io/contrib/samplers/probability/consistent)があります。ただし2026年9月時点では実験的で、現行の仕様草案との差分も残っています[^cps]。この段階では、ディストリビューションのデフォルト値には採用しません。Consistent Probability Samplingの詳細は、[別の記事](https://zenn.dev/ymotongpoo/articles/20260717-cps)で解説しています[^sampling-book]。

[^cps]: 実装はtracestateにp値とr値を書く旧ドラフトに準拠しており、現行仕様のth値ベースの方式とは互換がありません。

[^sampling-book]: テレメトリーのサンプリングは慎重に扱わないと、いざ原因分析を行いたいときに必要なデータが欠損してしまう可能性があります。詳細はこちらの書籍を参照してください。 https://amzn.to/4rgVYVe

## 設定の優先順位

社内のデフォルト値は、設定を追加しなくても組織の標準構成で動かすために用意します。ただし、サービス固有の要件まで固定しないよう、明示的なコード指定、`OTEL_*` 標準環境変数、社内のデフォルト値の順に優先します。

社内独自の環境変数は設けません。OTel標準の環境変数を使えば、公式ドキュメントを参照でき、ゼロコード計装（3章）やほかの言語のSDKとも設定方法を揃えられます。

ただしGo SDKの環境変数対応には穴があります。仕様が定める環境変数のうち、Go SDK単体が解釈するものとしないものがあるからです。

| 環境変数 | Go SDK単体で解釈するか | ディストリビューションでの補完 |
|---|---|---|
| `OTEL_SERVICE_NAME`、`OTEL_RESOURCE_ATTRIBUTES` | 対応 | 不要 |
| `OTEL_TRACES_SAMPLER`、`OTEL_TRACES_SAMPLER_ARG` | 対応 | 不要 |
| `OTEL_EXPORTER_OTLP_*`（endpoint、headers、protocolなど） | 対応 | 不要 |
| `OTEL_TRACES_EXPORTER`、`OTEL_METRICS_EXPORTER`、`OTEL_LOGS_EXPORTER` | 非対応 | contribのautoexportで解釈する |
| `OTEL_PROPAGATORS` | 非対応 | contribのautopropで解釈する |
| `OTEL_SDK_DISABLED` | 非対応 | ディストリビューションで実装する |

対応状況は仕様リポジトリの[コンプライアンス表](https://github.com/open-telemetry/opentelemetry-specification/blob/main/spec-compliance-matrix.md)にまとまっています。非対応分を埋めるのがcontribの[autoexport](https://pkg.go.dev/go.opentelemetry.io/contrib/exporters/autoexport)と[autoprop](https://pkg.go.dev/go.opentelemetry.io/contrib/propagators/autoprop)で、ディストリビューションはこの2つを組み込むことで標準環境変数のサポートを完成させます。

```go
// OTEL_TRACES_EXPORTER と OTEL_EXPORTER_OTLP_* を解釈する
exp, err := autoexport.NewSpanExporter(ctx)

// OTEL_PROPAGATORS を解釈する。未設定なら tracecontext と baggage
otel.SetTextMapPropagator(autoprop.NewTextMapPropagator())
```

YAMLファイルでSDKを構成するdeclarative configurationも仕様化されています。設定スキーマは2026年2月に[v1.0.0](https://github.com/open-telemetry/opentelemetry-configuration/releases)へ達しましたが、Go実装の[otelconf](https://pkg.go.dev/go.opentelemetry.io/contrib/otelconf)はv0.26.0の実験的段階です。現時点では環境変数とコードのデフォルト値を使い、otelconfが安定した後に移行を判断します。

## 配布とバージョン追従

Goの場合、社内ディストリビューションは社内Goモジュールとして配布します。社内のバージョン管理システムとGOPRIVATE、またはmodule proxyがあれば配布できます。言語ごとの配布方法は「多言語展開の課題」で扱います。

バージョン運用はsemverに従い、ディストリビューションと、同梱するSDKや計装ライブラリのバージョン対応表をリリースノートに載せます。各チームのリポジトリにはRenovateやDependabotで更新PRを送ります。SDKの更新作業は、ディストリビューションのリリースと各サービスへの自動PRに分けられます。

otelgrpcではinterceptorベースの計装が非推奨になり、stats handlerベースへ移行しました。どちらもgRPCへ計装を組み込む方式です。各サービスがotelgrpcを直接使っていれば、それぞれのコードを変更します。gRPCサーバーをディストリビューションのヘルパーで組み立てていれば、変更箇所をディストリビューション内に限定できます。

## 計装ライブラリの推奨リスト

SDK本体はv1.46.0系のstableですが、otelhttpやotelgrpcなどの計装ライブラリはv0.71.0であり、2026年9月時点ではv0系です。利用する計装ライブラリとバージョンはディストリビューションのgo.modで固定し、サービス間の差を防ぎます。

HTTPやgRPCのように多くのチームが使う計装ライブラリは、ヘルパーとともにディストリビューションへ含めます。データベースドライバやメッセージングクライアントのようにチームごとに異なるものは、動作確認済みのバージョンを推奨リストで示します。候補は公式の[レジストリ](https://opentelemetry.io/ja/ecosystem/registry/)から探せます。

## 多言語展開の課題

ほかの主要言語には、ディストリビューションを作るための機構があります。Javaではjavaagentの拡張機構を使って、jarとしてデフォルト値や独自処理を注入できます。Pythonではopentelemetry-distroとconfiguratorをentry pointで差し替えます。Node.jsでは、auto-instrumentations-nodeを組織のデフォルト値でラップしたセットアップモジュールを配ります。

Goには、これらに相当する機構がありません。エージェントや動的ロードを使えないため、ラッパーモジュールとして配ります。`otelinit` で定めたデフォルト値と失敗時の契約は、ほかの言語のディストリビューションにも適用できます。

多言語間では実装方法ではなく、リソース属性の内訳、プロパゲーターの構成、サンプリング、属性の名前と意味を揃えます。属性の名前と意味は、6章で扱うセマンティック規約のレジストリとWeaverで管理し、生成した属性定数パッケージを各言語のディストリビューションへ含めます。

ディストリビューションは、プラットフォームが管理するデフォルト値と、開発チームが記録する業務固有のスパンや属性を分離します。標準環境変数と明示的なコード指定を残すことで、サービス固有の要件にも対応できます。
