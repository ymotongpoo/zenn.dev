---
title: "セマンティック規約のガバナンスとWeaver"
---

OpenTelemetryでは、HTTPステータスコードの属性名が `http.status_code` から `http.response.status_code` へ変わりました。HTTP関連のセマンティック規約が安定化したときの改名です。移行期間に複数のSDKバージョンを使っていた組織では、ステータスコード別のエラー率を調べるために、新旧の属性名を使ったクエリが必要でした。片方だけを検索すると、ダッシュボードとアラートは一部のサービスを見落とします。

公式規約にも移行があるため、各チームが独自に付ける属性では、さらに多くの表記揺れが生じます。たとえば `user_id`、`userId`、`user.id` や、`env`、`environment`、`deployment.environment.name` です。計装とCollectorを共通化しても、属性の意味が揃っていなければ、サービスを横断して検索できません。三本目の柱では、この意味を統制します。

## 統制されないスキーマ

属性名の揺れがもたらす被害は、クエリが書きにくいという不便に留まりません。

- ダッシュボードとアラートが暗黙にスキーマへ依存する。属性名を変更すると、条件に一致せずアラートが発火しなくなる
- チーム間で属性の意味が衝突する。あるチームの `status` は注文の状態で、別のチームの `status` はHTTPステータス。集計すると意味のない数字が出る
- 高カーディナリティを制御できない。メトリクスはラベル値の組み合わせごとに時系列が増えるため、ユーザーIDのように値の種類が多い属性をラベルにすると保存量が急増する
- gatewayの属性処理に共通の根拠を持てない。削除する属性の一覧が、規約ではなく個別の障害対応だけで増えていく

これらの問題は、属性の名前、意味、型がコードとダッシュボードに散在し、共通の定義がないために起きます。一つの定義からコード、ドキュメント、検査規則を生成する方法を、**schema-as-code**と呼びます。

## 公式セマンティック規約の構造

OpenTelemetryは、属性の名前と意味を[**セマンティック規約**](https://opentelemetry.io/docs/specs/semconv/)（semantic conventions）として定義します。`http.response.status_code` や `service.name` などの定義をYAMLの**レジストリ**で管理し、ドキュメントと各言語の定数パッケージを生成しています。

レジストリの構成単位はグループです。属性の集合を定義するattribute_group、スパンの規約を定義するspan、メトリクスを定義するmetricといった種類があり、個々の属性は型と説明と安定性（stabilityがstableかdevelopmentか）を持ちます。規約全体にはバージョンがあり、テレメトリー自体にschema URLとして埋め込まれます。

公式規約も継続して変更されています。2026年8月時点では、領域ごとに安定性が異なります。OpenTelemetryプロジェクトは、規約の検査、生成、差分検出にWeaverを使っており、公式レジストリにある900を超える属性もCIで検査されています[^weaverblog]。

[^weaverblog]: 公式ブログ[Observability by Design](https://opentelemetry.io/blog/2025/otel-weaver/)が、公式semconv自体の運用にWeaverを使っていることを説明しています。

## 社内名前空間の設計

社内規約は、公式規約にない組織固有の概念だけを追加します。

公式規約にある概念には公式の属性を使います。たとえば、HTTPステータスに独自の属性名は追加しません。社内固有の概念には、公式規約と衝突しないよう、逆ドメイン形式の名前空間を使います。本書では `com.example.*` とし、配送IDを `com.example.delivery.id` と定義します。

この規則を検査できる形で記述したものが社内レジストリです。**OpenTelemetry Weaver**のレジストリは、YAMLのグループ定義とマニフェストからなります。マニフェスト（manifest.yaml）には、レジストリの名前、バージョン、依存する公式レジストリを宣言します[^manifestname]。

[^manifestname]: 古い資料ではマニフェストのファイル名が registry_manifest.yaml となっていますが、これは旧名で、現在の名前は manifest.yaml です（2026年8月時点、Weaver v0.25系）。

```yaml
name: example
description: 社内セマンティック規約レジストリ
schema_url: https://schemas.example.com/1.0.0
dependencies:
  - schema_url: https://opentelemetry.io/schemas/1.44.0
    registry_path: https://github.com/open-telemetry/semantic-conventions@v1.44.0[model]
```

依存に公式レジストリをバージョン付きで宣言することで、社内レジストリは「公式のv1.44.0の上に社内定義を重ねたもの」として解決されます。属性の定義はグループのYAMLに書きます。

```yaml
groups:
  - id: registry.com.example.delivery
    type: attribute_group
    display_name: Delivery Attributes
    brief: 配送ドメインの属性
    attributes:
      - id: com.example.delivery.id
        type: string
        stability: development
        brief: 配送を一意に識別するID
        examples: ["dlv-2026-000123"]
      - id: com.example.delivery.carrier
        type: string
        stability: development
        brief: 配送事業者の識別子
        examples: ["carrier-a"]
```

公式属性を社内の文脈で参照することもできます。`ref` で公式の属性を取り込み、requirement levelだけを社内向けに上書きする、といった使い方です。依存は多段にでき（2026年8月時点で最大10階層）、たとえば「全社レジストリの上に事業部レジストリ」という構成も組めます。

![レジストリの参照関係](/images/20260825-registry-deps.png)
*図1　矢印は、依存するレジストリから依存先を指します。社内レジストリは公式レジストリへ依存し、GenAI規約のようなDevelopment段階の規約はコミットSHAで固定します（60章）。*

## Weaverによるスキーマ管理

Weaverのサブコマンドは、規約の変更前、マージ後、実行時に分けて使います。変更前はcheckとdiff、マージ後はgenerate、実行時はlive-checkを使います[^weaverversion]。

[^weaverversion]: Weaverは2026年8月時点でv0.25.1、まだ1.0前です。かつて存在した `weaver registry resolve` と `search` は非推奨になっているので、古い記事のコマンド例に注意してください。

`weaver registry check` は、構文と参照を検査し、OPAのRego言語で書いたポリシーも適用します。たとえば、「`com.example.` 以外の名前空間で属性を新設しない」「stableな属性の型を変更しない」という規則を検査できます。公式の[opentelemetry-weaver-packages](https://github.com/open-telemetry/opentelemetry-weaver-packages)リポジトリには、命名規則、stability制約、後方互換性のポリシーが公開されており、Git URLで指定できます。

```console
$ weaver registry check -r ./registry \
    -p https://github.com/open-telemetry/opentelemetry-weaver-packages.git[policies/check/naming_conventions]
```

`weaver registry diff` は、PRのレジストリをmainブランチなどの基準と比較し、属性の追加、改名、削除、型変更を構造化された差分として出力します。破壊的変更を機械的に検出し、明示的な承認へ回せます。

`weaver registry generate` は、minijinjaテンプレートとjq形式のフィルタを使い、レジストリから成果物を生成します。本書では社内属性のGo定数パッケージを生成し、10章のディストリビューションへ含めます。開発チームは `attribute.String("com.example.delivery.id", id)` と文字列を手書きせず、生成された定数を使います。

ただし、Goの `attribute.String` は任意の文字列を受け取るため、生成定数があっても文字列の手書きを禁止できず、誤記もコンパイルエラーにはなりません。生成定数は手書きの機会を減らし、IDEの補完から利用可能な属性を選べるようにします。手書きを禁止するには、文字列を受け取らない社内ラッパーAPIか静的解析が必要です。残った違反はlive-checkで実測データから検出します。

テンプレートは自作できます。[opentelemetry-goのsemconv/templates](https://github.com/open-telemetry/opentelemetry-go/tree/main/semconv/templates)では、公式のGo semconvパッケージをWeaverで生成しています。同じレジストリからMarkdownのドキュメントも生成すれば、定義と説明を一緒に更新できます。

![Weaverによるスキーマ管理の循環](/images/20260825-weaver-loop.png)
*図2　矢印は工程の流れを表します。変更前はcheckとdiff、マージ後はgenerate、実測時はlive-checkを使い、検出した違反をレジストリの変更へ反映します。*

## live-checkによる実測検査

定義と生成物を揃えても、実際のテレメトリーが規約に従うとは限りません。ゼロコード計装が古い属性名を出す場合や、生成定数を使わずに属性名を手書きするコードが残る場合があります。`weaver registry live-check` は、定義と実測データを照合します。

live-checkはそれ自体がOTLPの受信口になります。gRPCでテレメトリーを受け取り、スパン、メトリクス、ログ、リソースの属性をレジストリと突き合わせて、未登録の属性、型の不一致、非推奨属性の使用などを報告します。判定にはRegoポリシーを追加でき、違反があれば終了コードが非ゼロになるため、CIに組み込めます。

サービスの結合テストでは、テレメトリーの送信先を一時的にlive-checkへ向けます。テスト中に生成されたテレメトリーを検査し、規約違反があればテストを失敗させます。これにより、本番のダッシュボードで気付く前に、CIで計装の違反を検出できます。

## CIへの組み込み

レジストリのCIでは、検査と生成を次の順で実行します。

- レジストリ変更のPRで、checkをポリシー付きで実行する。命名と構造の違反はここで止まる
- 併せてdiffをベースライン（mainブランチのレジストリ）に対して実行し、破壊的変更を検出したらPRにラベルを付けて明示の承認を要求する
- マージされたら、generateで各言語の定数パッケージとドキュメントを再生成し、ディストリビューション（10章）への更新PRを自動で作る
- 必要に応じて、gateway（30章）の属性変換設定も同じレジストリから生成する。非推奨になった属性を新しい名前へ書き換えるtransform設定は、改名の情報から機械的に導出できる。このとき30章で述べたとおり、変換は入力のschema URLと出力のschema URLを一組にして生成し、属性だけを書き換えて宣言が古いまま、という不整合を作らない

SDKの定数、ドキュメント、Collectorの変換設定を一つのレジストリから生成すれば、同じ変更を別々の場所へ手作業で反映せずに済みます。生成物は、SDKディストリビューションとCollector設定の配布経路で各環境へ届けます。

## 組織プロセスとしてのガバナンス

検査を自動化しても、追加する属性の意味と粒度は人間が決めます。

開発チームはレジストリへPRを出し、CIのcheckとdiffで構造と互換性を検査します。レビューでは、既存属性との意味の重複と、値の粒度を確認します。プラットフォームチームに全属性のレビューを集めないよう、確認事項を文書化し、各ドメインの担当者へ委譲します。

属性を廃止する場合は、レジストリでdeprecatedにして代替を示します。移行期間にはgatewayで旧属性を新属性へ変換し、ダッシュボードの移行後に旧定義を削除します。旧属性と新属性を併記する場合は、どちらを正とするか、ダッシュボードの切り替え日、旧属性の削除日を移行計画に含めます。

Weaverの `weaver registry mcp` サブコマンドは、レジストリをMCP（Model Context Protocol）経由でLLMへ公開します。MCPは、LLMへ外部データや操作を提供する接続規格です。70章では、この接続を使ってAIエージェントへ属性の定義を渡します。

プラットフォームはレジストリ、生成物、検査を提供し、開発チームはドメイン属性の意味を決めます。新しい属性が必要な場合は、レジストリへのPRを通じて定義を変更します。
