---
title: "SDKディストリビューションの設計"
---

「サービスにOpenTelemetryを入れてください」と依頼された開発チームは、公式ドキュメントの初期化コードを自分のリポジトリに写すことから始めます。Goでは、次のようなコードになります。

```go
func initTracer(ctx context.Context) (func(context.Context) error, error) {
	// exporter（テレメトリーの送信部品）の組み立て
	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint("collector.internal.example.com:4317"),
		otlptracegrpc.WithInsecure(),
	)
	if err != nil {
		return nil, err
	}
	// resource属性の設定
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
	// propagatorの設定
	otel.SetTextMapPropagator(propagation.TraceContext{})
	return tp.Shutdown, nil
}
```

このコード自体は動きます。しかし、各チームが個別に書けば、初期化方法もチームごとに分かれます。

## 素のSDKで起きること

上のコードでは、Collectorのエンドポイントを直接指定しているため、環境ごとの変更方法を各チームが決めます。resource属性は `service.name` しか設定しておらず、`deployment.environment.name` や `service.namespace` を追加するかどうかも統一されません。

propagatorにはBaggageを含めていません。**Baggage**は、トレースの文脈とともに任意のキーと値をリクエストへ載せて運ぶ仕組みです。後からBaggageを使う設計を導入しても、このサービスでは属性を引き継げません。`SetTextMapPropagator` の呼び出し自体を忘れれば、トレースはこのサービスで分断されます。

メトリクスとログの初期化が実装されず、トレースだけを設定して「OpenTelemetryは導入済み」と判断されることもあります。

個々の差は小さくても、サービスを横断してテレメトリーを検索すると影響が現れます。resource属性が欠ければ、どの環境のどのサービスが出したデータかを特定できません。propagatorの違いはトレースを分断し、SDKバージョンの違いは、一部のサービスだけが修正済みの不具合を残す原因になります。

中央チームによる全サービスのレビューは、依頼の待ち時間を増やします。そこで、組織の既定値を組み込んだ**SDKディストリビューション**を配り、初期化方法を配布物として統一します。

## ディストリビューションの役割

OpenTelemetryでは、SDKに既定値やカスタマイズを加えて再パッケージしたものを[ディストリビューション](https://opentelemetry.io/docs/concepts/distributions/)と呼びます。SDK本体を変更するフォークとは異なり、SDKの上に設定と部品の選択を重ねます。

オブザーバビリティベンダーが提供するSDKもディストリビューションの一例です。OTel SDKへ、自社バックエンド向けの既定値、推奨する計装ライブラリとpropagator、共通の初期化処理を追加しています。

社内プラットフォームでも、組織の環境に合わせた既定値を組み込んだディストリビューションを配れます。

## 社内ディストリビューションの設計

社内ディストリビューションは、exporter、resource、propagator、samplerに関する共通の判断をアプリケーションコードから取り除きます。冒頭のコードにsamplerがない場合も、SDKの既定値を選んだことになります。開発チームが書くのは、社内ディストリビューション `otelinit` の呼び出しと、初期化に失敗した場合の処理です。

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

- OTLP exporterを構築する。エンドポイントの既定値は各環境のagent Collector（30章）に向ける
- propagatorをW3C TraceContext（トレースの文脈を運ぶ標準のヘッダ形式）とBaggageの組み合わせに設定する
- sampler（トレースを記録するかどうかを決める部品）の既定をParentBasedにする。間引きの主体はgateway側のtail sampling（30章）に寄せる
- 実行環境（Kubernetesやクラウドプロバイダー）のメタデータからresource属性を自動検出する
- トレース、メトリクス、ログのproviderを構築してグローバルに登録する

ログの組み込みでは、APIの安定性を考慮します。2026年8月時点で、Goのログ関連モジュール（`otel/log` と `otel/sdk/log`）はv0.21.0のベータであり、stableに達しているのはトレースとメトリクスです[^golog]。各チームがv0のAPIに直接依存すると、破壊的変更のたびに複数のサービスを修正することになります。ディストリビューションだけがv0のAPIに依存すれば、変更への対応箇所を一つに集約できます。

[^golog]: opentelemetry-goのモジュール構成とバージョンは[versions.yaml](https://github.com/open-telemetry/opentelemetry-go/blob/main/versions.yaml)で確認できます。

サンプリングの既定値には、処理できる流量の前提が必要です。SDKがトレースの開始時に記録の可否を決める方式を**head sampling**、Collectorがトレースの完結後に決める方式を**tail sampling**と呼びます。ParentBasedは親スパンの決定に従い、親のないトレースは記録する設定です。この設定では、SDKはスパンを間引きません。

tail samplingへ判断を集約すると、エラーの有無やレイテンシを見て保存対象を選べます。ただし、すべてのスパンがアプリケーションからgatewayまで流れるため、SDK、agent、ネットワーク、gatewayの負荷は減りません。この構成を使えるのは、各区間が全スパンの流量を処理できる場合です。高流量のサービスでは、SDKのhead samplingで先に量を減らします。プラットフォームは、`OTEL_TRACES_SAMPLER` 環境変数を調整点として、どの段階で量を減らすかを決めます。

head samplingの確率をトレース全体で一貫させるConsistent Probability Samplingには、contribの[Go実装](https://pkg.go.dev/go.opentelemetry.io/contrib/samplers/probability/consistent)があります。ただし2026年8月時点では実験的で、現行の仕様草案との差分も残っています[^cps]。この段階では、ディストリビューションの既定値には採用しません。Consistent Probability Samplingの詳細は、[別の記事](https://zenn.dev/ymotongpoo/articles/20260717-cps)で解説しています。

[^cps]: 実装はtracestateにp値とr値を書く旧ドラフトに準拠しており、現行仕様のth値ベースの方式とは互換がありません。

## 設定の優先順位

社内既定値は、設定を追加しなくても組織の標準構成で動かすために用意します。ただし、サービス固有の要件まで固定しないよう、明示的なコード指定、`OTEL_*` 標準環境変数、社内既定値の順に優先します。

社内独自の環境変数は設けません。OTel標準の環境変数を使えば、公式ドキュメントを参照でき、ゼロコード計装（20章）やほかの言語のSDKとも設定方法を揃えられます。

ただしGo SDKの環境変数対応には穴があります。仕様が定める環境変数のうち、Go SDK単体が解釈するものとしないものがあるからです。

| 環境変数 | Go SDK単体で解釈するか | ディストリビューションでの補完 |
|---|---|---|
| `OTEL_SERVICE_NAME`、`OTEL_RESOURCE_ATTRIBUTES` | 対応 | 不要 |
| `OTEL_TRACES_SAMPLER`、`OTEL_TRACES_SAMPLER_ARG` | 対応 | 不要 |
| `OTEL_EXPORTER_OTLP_*`（endpoint、headers、protocolなど） | 対応 | 不要 |
| `OTEL_TRACES_EXPORTER`、`OTEL_METRICS_EXPORTER`、`OTEL_LOGS_EXPORTER` | 非対応 | contribのautoexportで解釈する |
| `OTEL_PROPAGATORS` | 非対応 | contribのautopropで解釈する |
| `OTEL_SDK_DISABLED` | 非対応 | ディストリビューションで実装する |

対応状況は仕様リポジトリの[コンプライアンス表](https://github.com/open-telemetry/opentelemetry-specification/blob/main/spec-compliance-matrix.md)にまとまっています。非対応分を埋めるのがcontribの[autoexport](https://pkg.go.dev/go.opentelemetry.io/contrib/exporters/autoexport)と[autoprop](https://pkg.go.dev/go.opentelemetry.io/contrib/propagators/autoprop)で、ディストリビューションはこの二つを組み込むことで標準環境変数のサポートを完成させます。

```go
// OTEL_TRACES_EXPORTER と OTEL_EXPORTER_OTLP_* を解釈する
exp, err := autoexport.NewSpanExporter(ctx)

// OTEL_PROPAGATORS を解釈する。未設定なら tracecontext と baggage
otel.SetTextMapPropagator(autoprop.NewTextMapPropagator())
```

YAMLファイルでSDKを構成するdeclarative configurationも仕様化されています。設定スキーマは2026年2月に[v1.0.0](https://github.com/open-telemetry/opentelemetry-configuration/releases)へ達しましたが、Go実装の[otelconf](https://pkg.go.dev/go.opentelemetry.io/contrib/otelconf)はv0.25.0の実験的段階です。現時点では環境変数とコードの既定値を使い、otelconfが安定した後に移行を判断します。

## 配布とバージョン追従

社内ディストリビューションは、社内Goモジュールとして配布します。社内のバージョン管理システムとGOPRIVATE、またはmodule proxyがあれば配布できます。

バージョン運用はsemverに従い、ディストリビューションと、同梱するSDKや計装ライブラリのバージョン対応表をリリースノートに載せます。各チームのリポジトリにはRenovateやDependabotで更新PRを送ります。SDKの更新作業は、ディストリビューションのリリースと各サービスへの自動PRに分けられます。

otelgrpcではinterceptorベースの計装が非推奨になり、stats handlerベースへ移行しました。どちらもgRPCへ計装を組み込む方式です。各サービスがotelgrpcを直接使っていれば、それぞれのコードを変更します。gRPCサーバーをディストリビューションのヘルパーで組み立てていれば、変更箇所をディストリビューション内に限定できます。

## 計装ライブラリの推奨リスト

SDK本体はv1.45.0系のstableですが、otelhttpやotelgrpcなどの計装ライブラリはv0.70.0であり、2026年8月時点ではv0系です。利用する計装ライブラリとバージョンはディストリビューションのgo.modで固定し、サービス間の差を防ぎます。

HTTPやgRPCのように多くのチームが使う計装ライブラリは、ヘルパーとともにディストリビューションへ含めます。データベースドライバやメッセージングクライアントのようにチームごとに異なるものは、動作確認済みのバージョンを推奨リストで示します。候補は公式の[レジストリ](https://opentelemetry.io/ecosystem/registry/)から探せます。

## 多言語展開の課題

ほかの主要言語には、ディストリビューションを作るための機構があります。Javaではjavaagentの拡張機構を使って、jarとして既定値や独自処理を注入できます。Pythonではopentelemetry-distroとconfiguratorをentry pointで差し替えます。Node.jsでは、auto-instrumentations-nodeを組織の既定値でラップしたセットアップモジュールを配ります。

Goには、これらに相当する機構がありません。エージェントや動的ロードを使えないため、ラッパーモジュールとして配ります。`otelinit` で定めた既定値と失敗時の契約は、ほかの言語のディストリビューションにも適用できます。

多言語間では実装方法ではなく、resource属性の内訳、propagatorの構成、サンプリング、属性の名前と意味を揃えます。属性の名前と意味は、50章で扱うセマンティック規約のレジストリとWeaverで管理し、生成した属性定数パッケージを各言語のディストリビューションへ含めます。

ディストリビューションは、プラットフォームが管理する既定値と、開発チームが記録する業務固有のスパンや属性を分離します。標準環境変数と明示的なコード指定を残すことで、サービス固有の要件にも対応できます。
