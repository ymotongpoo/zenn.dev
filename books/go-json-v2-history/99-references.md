---
title: "付録：参考リンク"
---

## Go公式

* Go 1.27 Release Notes: <https://go.dev/doc/go1.27>
* Go 1.25 Release Notes（実験的導入）: <https://go.dev/doc/go1.25>
* A new experimental Go API for JSON（2025-09-09）: <https://go.dev/blog/jsonv2-exp>
* Evolving the Go Standard Library with math/rand/v2（2024-05-01）: <https://go.dev/blog/randv2>
* Go 1 and the Future of Go Programs（互換性保証）: <https://go.dev/doc/go1compat>
* The Future of JSON in Go（GopherCon 2023、Joe Tsai）: <https://www.youtube.com/watch?v=avilmOcHKHE>

## issue と discussion

| 番号 | 内容 |
|---|---|
| [#14750](https://github.com/golang/go/issues/14750) | 大文字小文字を無視するマッチ（2016-03-10〜2025-06-27） |
| [#4712](https://github.com/golang/go/issues/4712) | `time.Duration` の表現（2017-02-17にクローズ） |
| [#63397](https://github.com/golang/go/discussions/63397) | encoding/json/v2 の Discussion（2023-10-05） |
| [#71497](https://github.com/golang/go/issues/71497) | 正式提案（2025-01-31、2026-05-13受理） |
| [#71631](https://github.com/golang/go/issues/71631) | `time.Duration` の既定表現（2025-12-18クローズ） |
| [#79071](https://github.com/golang/go/issues/79071) | `format` タグの取り下げ（2026-04-30） |
| [#74472](https://github.com/golang/go/issues/74472) | 型付き構造体タグの提案（保留中） |
| [#76406](https://github.com/golang/go/issues/76406) | json/v2 ワーキンググループ議事録 |
| [#61716](https://github.com/golang/go/issues/61716) | math/rand/v2 の提案（2023-10-03受理） |
| [#60751](https://github.com/golang/go/discussions/60751) | 標準ライブラリで最初のv2という位置づけ |
| [#67401](https://github.com/golang/go/issues/67401) | linkname のロックダウン |

## プロトタイプとベンチマーク

* go-json-experiment/json: <https://github.com/go-json-experiment/json>
* go-json-experiment/jsonbench: <https://github.com/go-json-experiment/jsonbench>

## サードパーティ

* goccy/go-json: <https://github.com/goccy/go-json>
* goccy/go-json#568（17フィールド以上で大文字小文字マッチが効かない）: <https://github.com/goccy/go-json/issues/568>
* bytedance/sonic の Go 1.27 互換性カタログ: <https://github.com/bytedance/sonic/blob/main/docs/sonic-go127-compatibility.md>
* json-iterator/go（アーカイブ済み）: <https://github.com/json-iterator/go>
* golang/protobuf#1673（protojson と jsontext）: <https://github.com/golang/protobuf/issues/1673>

## 本書が引用した標準ライブラリのソース

| 内容 | ファイル |
|---|---|
| v1のレガシー挙動フラグ一覧 | `src/encoding/json/internal/jsonflags/flags.go` |
| `DefaultOptionsV1` と移行ドキュメント | `src/encoding/json/v2_options.go` |
| v1とv2のエラー型の橋渡し | `src/encoding/json/v2_inject.go` |
| `format` タグの実装と有効化スイッチ | `src/encoding/json/v2/arshal_time.go`、`src/encoding/json/internal/jsonopts/options_format.go` |
| エラー文言のHyrum対策 | `src/encoding/json/v2/errors.go` |
| `any` へのデコードの最適化経路 | `src/encoding/json/v2/arshal_default.go` |
| `GOEXPERIMENT` の既定値 | `src/internal/buildcfg/exp.go` |

> 本書の実行結果は go1.27 darwin/arm64（Apple M5 Pro）で確認したものです。
> ベンチマークの値は環境とデータの形に強く依存するので、判断に使う際は自分のデータで測り直してください。
> 引用したソースコードは同バージョンのものです。オプション名やフラグの構成は、今後のリリースで変わりえます。
