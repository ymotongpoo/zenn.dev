---
title: "Collector層の設計とカスタムビルド"
---

SDKディストリビューションとゼロコード計装は、どちらも各環境のCollectorへテレメトリーを送ります。アプリケーションからバックエンドへ直接送れば、Collectorを運用する必要はありません。それでも中継層を置くのは、転送経路に関する判断をアプリケーションから分離するためです。

直接送信する構成では、バックエンドに関する決定がアプリケーション側へ入ります。バックエンドを変更するには全サービスの設定変更と再デプロイが必要になり、認証トークンも全サービスへ配ります。保存前に属性を削除する場合も、各チームへ変更を依頼します。**Collector層**は、こうした転送経路の判断を集約します。

## Collector層の役割

[**OpenTelemetry Collector**](https://opentelemetry.io/docs/collector/)は、テレメトリーの受信、加工、送信を行うパイプラインです。**receiver**で受け、**processor**で加工し、exporterで送る構成をYAMLで宣言します。プラットフォームがCollectorへ持たせる役割は次のとおりです。

- 送信先の抽象化。アプリはOTLPでCollectorに送るだけで、バックエンドがどこかを知らない。バックエンドの変更や併用はCollectorの設定変更で完結する
- テレメトリーの加工。属性の追加と削除、変換、フィルタ、サンプリングを、アプリのコードに触れず一律に適用する
- 認証情報の分離。バックエンドのAPIキーはCollectorだけが持ち、アプリには配らない
- 送信の平準化。バッチ化、リトライ、バックプレッシャーをアプリの代わりに引き受ける

送信の平準化は、データが失われないことを保証しません。Collectorのキューは既定ではメモリ上にあり、プロセスやノードが停止すればキューの内容を失います。永続キューを使えば再起動後に再送できますが、ディスクが必要です。容量を超えた場合にdropするかバックプレッシャーをかけるかも設定によって変わります。Collectorを挟むことで、損失が起きる条件と範囲をアプリケーションの外で設計できます。

## 配置の設計パターン

Collectorには、主に三つの配置があります。

**agentパターン**では、アプリケーションと同じホストやノードでCollectorを動かします。KubernetesではDaemonSetとして配置し、アプリケーションから近い送信先を提供します。ノード名やPod情報など、ホストのメタデータをresource属性として付加する処理も担います。

**gatewayパターン**は、組織やクラスタ単位の集約層としてCollectorのクラスタを置く形です。Deploymentとして水平スケールさせ、バックエンドへの出口をここに一本化します。

**サイドカーパターン**では、Pod単位でCollectorを併走させます。テナントごとの分離に使えますが、Podの数だけCollectorが増えるため、必要な分離をagentやgatewayで実現できない場合に限って採用します。

本書は、複数チームがKubernetes上でサービスを運用し、組織で送信先を管理する環境に、**agentとgatewayの二段構成**を推奨します。OpenTelemetry仕様が定めた標準構成ではなく、本書の前提に対する判断です。単一チームの小規模な環境ではgatewayだけでも運用でき、ノードのメタデータが不要ならagentを省けます。二段構成では、アプリケーションがノード上のagentへ送り、agentがgatewayへ転送し、gatewayがバックエンドへ送ります。

組織の方針はgatewayへ集めます。個人情報や機密情報の削除規則と送信先は変更される一方、agentの設定変更は全ノードへ影響するためです。agentはホスト由来のメタデータ付加とアプリケーションからの受信に限定し、全ノードで同じ設定を使います。gatewayはサンプリング、属性の統制、ルーティング、バックエンドの認証を担います。

agentはアプリケーションと同じノードで動くため、ノード障害の影響をともに受けます。二段構成にしても損失条件はなくなりません。各層のキューと再送を設計し、どの障害でどこまで失うかを決めます。

![agentとgatewayの2段トポロジー](/images/20260926-agent-gateway.png)
*図1　矢印はテレメトリーの流れを表します。agentは各ノードで同じ最小限の処理を行い、組織の方針はgatewayへ集約します。tail samplingを水平スケールさせる場合は、振り分け層を追加します。*

## gateway層の処理設計

gateway層には、組織単位で判断する処理を置きます。

**tail sampling**は、トレースが完結した後に、エラーの有無やレイテンシから保存するかを決めます。たとえば、エラーになったトレースをすべて残し、正常なトレースの1%を残す方針を実装できます。判定には一つのトレースを構成する全スパンが必要なため、gatewayへ配置します。

gatewayを水平スケールさせる場合は、同じtrace IDのスパンを同じgatewayインスタンスへ送るload-balancing exporterが前段に必要です。tail samplingを使う二段構成は、実際には振り分け層を含みます。また、tail samplingは保存量を減らしますが、gatewayまでの流量は減らしません。流量はSDK側のhead samplingと分担して制御します。

**属性の統制**にはtransform processorを使います。メールアドレスなどの個人を特定できる情報（PII）や、トークンなどの機密情報を削除する**redaction**と、非推奨になった属性名の変換を、テレメトリーの転送中に適用します。

ただし、属性名の変換は単独の文字列置換として扱えません。SDKは、準拠する規約のバージョンを**schema URL**としてテレメトリーへ付けます。バックエンドや変換ツールがこの宣言を使って新旧の属性名を変換するため、属性だけを新しい名前へ変えて古いschema URLを残すと、変換が重複したり、必要な変換を適用できなかったりします。入力のschema URL、適用する変換、出力のschema URLを一組として設計します。50章では、この関係を規約側から説明します。

**ルーティング**ではresource属性を参照し、テナントや環境ごとに送信先を変えます。たとえば、開発環境のテレメトリーを低コストの保存先へ送り、特定チームのデータを専用テナントへ送ります。

**負荷制御**にはmemory_limiter processorとbatch processorを使います。パイプラインの先頭と末尾へ配置し、流量の急増によるCollectorの停止を防ぎます。この二つはagentにも配置します。

## カスタムビルドの理由

Collectorにはcoreとcontribの公式配布物があり、contribにはコミュニティのコンポーネントがまとめて入っています。本書では、必要なコンポーネントを選んだカスタムビルドを使います。

contribには100を超えるコンポーネントが含まれ、その多くは一つの組織では使いません。未使用のコンポーネントも脆弱性対応の確認対象になり、設定を誤れば意図しないreceiverを開く可能性があります。必要な部品だけを含むバイナリは攻撃対象面を狭め、組織で利用を認めるコンポーネントの一覧にもなります。

カスタムビルドは、社内の認証機構と連携するextensionや、独自プロトコルのreceiverを追加する場合にも必要です。

## OCBによるビルド

カスタムビルドの公式ツールが**OCB**（OpenTelemetry Collector Builder）です[^ocb]。使う部品をmanifest.yamlに列挙すると、OCBがGoのコードを生成してビルドします。

[^ocb]: 公式ドキュメントは[Building a custom Collector](https://opentelemetry.io/docs/collector/extend/ocb/)にあります。以前の「custom-collector」というURLからは移動しているので、古いリンクに注意してください。

```yaml
dist:
  module: github.com/example/otelcol-internal
  name: otelcol-internal
  description: 社内標準ビルドのOpenTelemetry Collector
  output_path: ./build

receivers:
  - gomod: go.opentelemetry.io/collector/receiver/otlpreceiver v0.159.0

processors:
  - gomod: go.opentelemetry.io/collector/processor/batchprocessor v0.159.0
  - gomod: go.opentelemetry.io/collector/processor/memorylimiterprocessor v0.159.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/processor/transformprocessor v0.159.0
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/processor/tailsamplingprocessor v0.159.0

exporters:
  - gomod: go.opentelemetry.io/collector/exporter/otlpexporter v0.159.0

extensions:
  - gomod: github.com/open-telemetry/opentelemetry-collector-contrib/extension/healthcheckextension v0.159.0
```

2026年8月時点のmanifestには、バージョンと設定項目に注意が必要です。

Collectorのcoreリポジトリは、v1.65.0とv0.159.0の二つのバージョンを同時にリリースしています。stableに達しているのはpdataやconfmapなどのAPI層です。receiverやprocessorなどのコンポーネントはv0系なので、manifestにはv0.159.0のようなバージョンを書きます。

`otelcol_version` フィールドは、2024年11月のOCBで削除されました。古い記事にはdistセクションへ指定する例が残っていますが、現在は使いません。コンポーネント間のバージョン整合はビルド時に検査されます。

設定値を環境変数などから展開するconfmap providerの `providers` セクションは省略できます。省略時はenv、file、http、https、yamlが組み込まれます。

OCBの公式Dockerイメージを使うと、CIでも同じビルド環境を再現できます。`--skip-compilation` を指定すればコード生成だけを、`--skip-generate --skip-get-modules` を指定すればコンパイルだけを実行できます。生成コードをリポジトリへコミットし、レビュー対象にする運用も可能です。コンテナ化まで含む構成は、公式配布物をビルドする[opentelemetry-collector-releases](https://github.com/open-telemetry/opentelemetry-collector-releases)リポジトリを参照できます。

![OCBによるビルドパイプライン](/images/20260926-ocb-pipeline.png)
*図2　矢印は成果物が次の工程へ渡る流れを表します。manifestを起点に、ビルド、設定の検証、コンテナ化までをCIで実行します。*

Collectorは隔週でリリースされ、contribのコンポーネントには破壊的変更も入ります。manifestのバージョン更新をRenovateなどでPRにし、CIでビルドと設定を検証します。更新作業をプラットフォーム側へ集約することで、各チームが個別に追従する必要はなくなります。

## 設定ファイルの配布設計

カスタムバイナリとともに、事前定義したconfig.yamlを配ります。開発チームは任意のCollector設定を書くのではなく、許可された項目だけを指定します。

環境差分の注入には、confmap providerによる展開を使います。

```yaml
exporters:
  otlp:
    endpoint: ${env:GATEWAY_ENDPOINT}
    headers:
      authorization: ${env:GATEWAY_TOKEN}
```

`${env:VAR}` は環境変数を、`${file:PATH}` はファイルの内容を展開します。設定テンプレートは全環境で共通にし、環境差分は環境変数とシークレット管理へ移します。環境ごとの設定ファイルを複製せずに済みます。

Collectorは `--config` フラグを複数回指定でき、後から読んだ設定を先の設定へマージします。base.yamlへチームのファイルを重ねる構成は作れますが、このマージは権限の境界にはなりません。後から読んだ値が優先されるため、チームのファイルが `service.pipelines.traces.processors` を再定義すれば、共通のmemory_limiterやPIIの削除をリストごと置き換えられます。processorの定義が残っていても、パイプラインから参照されなければ実行されません。

この置き換えは実測で確認できます。必須のPII削除processorを含むbase.yamlに、`processors: [memory_limiter]` だけを書いたチームのファイルを重ねて `print-config` を実行すると、実効設定のパイプラインからPII削除が消えます。しかも `otelcol validate` はこの設定を正常と判定します（終了コード0）。構文としては妥当な設定であり、検証コマンドは組織の方針を知らないためです。

したがって、統制の検査には実効設定を使います。`validate` の合否だけを見るCIは、必須processorが外された設定を通します。

統制対象を守るには、チームが書ける項目を制限します。本書では、チームが追加できるのを自チーム専用の別名パイプライン（たとえば `traces/team-checkout`）に限定し、基盤側のCIで設定を合成します。CIは `otelcol validate` と実効設定の出力を使い、すべてのパイプラインに必須processorがあることと、exporterの接続先が許可リストに含まれることを検査します。ファイルの形ではなく、Collectorが実際に使う設定を検査対象にします。

チームへパイプライン定義を任せる場合は、信頼境界ごとにCollectorを分けます。チーム管理のCollectorから基盤管理のgatewayへ送り、PIIの削除や認証はチームが変更できないgatewayで実行します。運用するCollectorは増えますが、設定上の規則ではなくプロセスの分離で境界を作れます。

プラットフォームはCollectorのバイナリ、パイプライン、更新経路を配り、開発チームには許可した設定項目を公開します。任意の設定が必要なチームには、分離したパイプラインか、別のCollectorを用意します。
