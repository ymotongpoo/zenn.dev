# 技術監査: 「テレメトリを「契約」として扱う — OpenTelemetry Weaverで試すTelemetry Contract」

- 対象: https://febc-yamamoto.hatenablog.jp/entry/2026/09/26/182900 （2026-09-26公開）
- 監査日: 2026-09-28
- 照合先: Weaver v0.26.1 のリリースバイナリ（`weaver-x86_64-unknown-linux-gnu`、`weaver --version` = 0.26.1）と、タグ `v0.26.1` のソース

## 1. 前提

記事の全7節について、主張を一次ソースと照らし合わせ、記事に載っているコマンド、Rego、テンプレートを v0.26.1 で実際に実行した。記事で使われた fixture そのものは公開されていないため、記事に載っている断片から同じものを組み直した。storage service 用の fixture（`my.attr`、`attr2`、`my.span`、`my.metric`）は、Weaver リポジトリの `tests/v2_forge/model/test.yaml` と一致したので、これを baseline に使った。

区分は次のとおり。誤りや読者を誤らせる記述は修正提案、表現や省略は報告のみとする。

## 2. 修正を提案するもの

### 2-1. §5「registry diff がフィールド単位の変更を出さないのは一般的な性質ではない」は、ドキュメントに書かれた仕様と逆

記事の記述:

> これは「Weaverの registry diff はフィールド単位の変更を検出できない」という一般的な性質を示したものではありません。Weaver v0.26.1と、今回試したfixture・変更内容では、この結果になったという観測です。

v0.26.1 の `docs/schema-changes.md` の記述:

> Note: The current implementation of the diffing process focuses on the top-level telemetry object attributes, metrics, events, spans, resources and does not compare the fields of those top-level items.

フィールドを比較しないのは、現在の実装の仕様として明記されている。記事の予防線は実態より弱く、「たまたまそうなった」とも読める。提案: 「v0.26.1 の registry diff はトップレベル要素の追加・削除・改名・廃止を扱い、フィールドは比較しない仕様です（docs/schema-changes.md）」と言い切り、ドキュメントへリンクする。

再現結果（instrument counter→gauge、attribute type int→string、unit {1}→ms、stability stable→development）は、4件とも `changes` の全配列が空だった。記事の観測自体は正しい。

### 2-2. §5 rename が「追加と削除」になるのは `deprecated` を書いていないため

記事では、名前変更は追加と削除として観測されたと書かれていて、それで話が終わっている。一方、同じドキュメントには `deprecated: {reason: renamed, renamed_to: ...}` を書くと `renamed` として出力されると明記されている。実際に試した結果は次のとおり。

```json
[{"type": "renamed", "old_name": "attr2", "new_name": "my.attr2", "note": "Replaced by `my.attr2`."},
 {"type": "added", "name": "my.attr2"}]
```

記事の主題（互換性を保った変更の管理）にとっては、この仕組みがいちばん関係の深い機能のはず。rename を追跡できないように読めてしまうので、一文補うことを提案する。

### 2-3. §6 互換性ポリシーの断片に、動かすための条件が2つ欠けている

記事の断片には、package 宣言と CLI オプションが書かれていない。v0.26.1 で baseline と比較するには、次の2つが必要になる。

- ポリシーの package を `comparison_after_resolution` にする（Weaver のテスト `tests/v2_check_baseline` もこの名前）
- `registry check` に `--baseline-registry <baseline>` を渡す

同じ Rego を §3 と同じ `package after_resolution` のまま置くと、「No `after_resolution` policy violation」と出るだけで、違反は1件も出ない（実際に試して確認した）。§3 の Rego を読んだ読者はそのまま流用しやすいので、この2点を本文に書くことを提案する。

2点をそろえて試すと、記事どおりのメッセージが出て exit code は1になった。

```
Attribute attr2 type changed from int to string.
Metric my.metric unit changed from {1} to ms.
Metric my.metric instrument changed from counter to gauge.
```

## 3. 報告のみ（著者の判断）

### 3-1. §7 span の結果は、観測にとどまらず実装上の仕様

記事は「今回の検証では」「今回確認した範囲では」と限定しているが、v0.26.1 のソースでは次のことを確認できる。

- `LiveChecker` にある定義の検索は `find_attribute`、`find_metric`、`find_event`、`find_entity`、`find_template` だけで、span 用のものはない（`crates/weaver_live_check/src/live_checker.rs:154-195`）
- `TypeAdvisor::advise` が扱うのは Attribute、Metric、データポイント、Log だけで、Span は扱わない（`advice/type_advisor.rs:610-`）

span をレジストリの定義と対応づける処理がないため、span の required 属性の欠落も未定義の span 名も検出されない。記事の観測はいずれも正しく、限定を外して仕様として書ける。

### 3-2. 出力例が手で整形されている

- §2 のエラーに出てくる Provenance は、実際には `Provenance: Some(Provenance { schema_url: SchemaUrl { ... }, path: "badref/model/payment.yaml" })` という Rust の Debug 表記で出力される。記事では `.../model/payment.yaml` に整えられている
- §5 の diff の JSON は、実際にはトップレベルの `"changes": { ... }` の下に入る。記事では `registry_attributes` がトップレベルにあるように見える

どちらも主張への影響はない。`jq` などで処理しようとする読者が戸惑うかもしれない程度。

### 3-3. 「Telemetry Contract は正式な用語ではない」の補足

Versioning and Stability には "Semantic conventions define a contract between the signals that instrumentation will provide and analysis tools that consumes the instrumentation (e.g. dashboards, alerts, queries, etc.)" とあり、contract という語がそのまま使われている。記事の「producer と consumer の間で互換性を扱う考え方がある」は誤りではないが、この一文を引けば根拠がより強くなる。なお、ページ内に producer という語はない。

## 4. 問題がなかった範囲

| 節 | 主張 | 確認方法 | 結果 |
| --- | --- | --- | --- |
| 前提 | v0.26.1 が存在する | `gh release view` | 2026-09-03 公開の Latest |
| 1 | definition/2 で `File format definition/2 is not yet stable` の警告が出る | 実行、`weaver_semconv/src/lib.rs:340` | 一致（実際の文言は末尾に `: <path>` が付く） |
| 2 | 存在しない属性への参照でエラーになり、exit 1 | 実行 | 文言と exit code が一致 |
| 2 | type を消すと `Missing required property: "type".` | 実行 | 一致。この診断にはファイル名も行番号も出ない |
| 3 | 記事の Rego で違反が出て、exit 1 | 記事のコードのまま実行 | メッセージと exit code が一致 |
| 4 | Markdown と JSON の生成、enum が内部構造のまま出る | 記事のテンプレートで実行 | 出力がバイト単位で一致 |
| 4 | 再生成しても、属性の順序を入れ替えても出力が変わらない | 2回生成して diff、順序を逆にして diff | 差分なし |
| 5 | 追加・削除が検出され、rename は added＋removed になる | 実行 | JSON の中身が一致 |
| 6 | フィールド変更をポリシーで違反にできる | 2-3 の条件をそろえて実行 | 一致 |
| 7 | span の型不一致が type_mismatch になる、registry を string に変えると消える | JSON 入力で live-check | 一致 |
| 7 | metric と event_name を持つ log では required の欠落が検出され、span では検出されない | 同上 | 一致 |
| 7 | 未定義の span 名は検出されない、span matcher のオプションはない | 同上、`live-check --help` | 一致 |
| 7 | live-check は V2 schema に対応している | CHANGELOG（#1022） | 一致 |
| 引用 | README の "Treat your telemetry like a public API" | タグ v0.26.1 の README.md:9 | 一致 |
| 引用 | 公式ブログがメトリクス名の変更でアラートやダッシュボードが壊れる例を挙げている | ブログ本文 | "A deployment that breaks existing alerts or dashboards because a metric name changed?" で一致 |
| 参照 | OBI #1759、SIG End User #332 のタイトル | `gh issue view` | どちらも一致（open） |
| URL | 本文のリンク8本 | curl | すべて 200。Weaver 関連のリンクは v0.26.1 に固定されている |

## 5. 検証していない範囲

- §7 の OTLP/gRPC 経由での受信。今回は `--input-source <file> --input-format json` で同じ種類のサンプルを入力した。判定ロジックは入力元によらず共通だが、OTLP 経路そのものは試していない
- 記事が §7 で使った legacy v1 形式のレジストリの細部。組み直した v1 定義で試している
- 大規模なレジストリでの診断の使いやすさ（記事自身も未検証と書いている）
