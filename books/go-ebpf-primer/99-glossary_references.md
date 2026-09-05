---
title: "付録：用語集と参考リンク"
---

## 用語集

本書に登場した用語の早引きです。丸括弧は主に扱った章を示します。難所の章から読み始めて分からない語に出会ったら、ここから初出の章へ戻れます。

### 計算機の基礎

- **ビットとバイト**：情報の最小単位が0か1のビットで、8ビットが1バイト。1バイトは0〜255を表せる（2章）。
- **メモリ**：番地（アドレス）の付いたバイトの列。名前ではなく番号で読み書きする（2章）。
- **アドレス**：メモリのマスに振られた通し番号。ただの数値であり、16進数で表記されることが多い（2章）。
- **16進数**：`0x` で始まる数の表記。2桁がちょうど1バイトに対応する（2章）。
- **命令と機械語**：CPUにできる最小単位の指示と、それをバイト列で表したもの。命令もメモリに置かれ、アドレスを持つ（2章、4章）。
- **PC（プログラムカウンタ）**：次に実行する命令のアドレスを保持するレジスタ。正式名はRIP（2章）。
- **レジスタ**：CPU内部の高速な記憶場所。amd64の汎用レジスタは16本、各64ビット（2章）。
- **SP（スタックポインタ）**：スタックの先端を指すレジスタ。正式名はRSP（2章、5章）。
- **ポインタ**：アドレスを値として持つ変数（2章）。
- **フィールドオフセット**：構造体の先頭からフィールドまでのバイト数。`unsafe.Offsetof` で取れる（2章、難所3）。
- **パディング（詰め物）**：フィールドの整列のために構造体へ挿入される未使用のバイト（2章）。

### OSとカーネル

- **カーネル**：OSの中核。ハードウェアの操作、プロセスの隔離、スケジューリングを担う（3章）。
- **プロセス**：実行中のプログラム1つぶんの実体。PIDで区別され、専用の仮想アドレス空間を持つ（3章）。
- **仮想アドレスと仮想メモリ**：プロセスごとに用意された専用の番地の列。物理メモリとの対応はカーネルが管理する（3章）。
- **テキスト領域、データ領域、ヒープ、スタック**：アドレス空間の区分。機械語、グローバル変数、動的確保、関数呼び出しの作業領域にそれぞれ使われる（3章）。
- **ユーザー空間とカーネル空間**：CPUの特権レベルによる区分。アプリは制限された側（ユーザー空間）で動く（3章）。
- **システムコール**：ユーザー空間からカーネルへの頼みごと。特権レベルの切り替えを伴う（3章）。
- **スレッド**：カーネルが管理する実行の単位。同じプロセス内でアドレス空間を共有し、スタックだけ個別に持つ（3章）。
- **ASLR**：スタックやヒープの配置を起動ごとにランダム化するセキュリティ機構（3章）。
- **エスケープ解析**：値をスタックとヒープのどちらに置くかをGoコンパイラが決める解析（3章）。

### 実行ファイル

- **コンパイルとリンク**：ソースを機械語に変換する工程と、部品を1つの実行ファイルに結合してアドレスを確定する工程（4章）。
- **静的リンクと動的リンク**：ライブラリを実行ファイルに取り込む方式と、共有ライブラリとして実行時に結び付ける方式（4章）。
- **逆アセンブル**：機械語のバイト列を人が読める命令表記に戻すこと。`go tool objdump` が行う（4章）。
- **シンボルテーブル**：名前とアドレスの対応表。`go tool nm` で覗ける。ELFの `.symtab` に入る（4章）。
- **ELFとセクション**：Linuxの実行ファイル形式と、その中の区分（`.text`、`.rodata` など）（4章）。
- **`.gopclntab`**：命令アドレスから関数名と行番号を引くGo固有の表。パニック時のスタックトレースに使われ、`-s -w` でも消えない（4章、14章）。
- **DWARF**：型、フィールドオフセット、行番号を記録したデバッグ情報。`.debug_*` セクションに入り、`-w` で消える（4章、難所3）。
- **ビルド情報**：Goのバージョンと依存モジュール一覧を記録したブロブ。`go version -m` が読む（4章、難所3）。
- **ページ**：仮想メモリの対応表が使う固定サイズ（通常4KB）の管理単位。物理メモリへの読み込みや差し替えはページごとに行われる（4章）。
- **コピーオンライト**：読み取り専用の共有ページを書き換えたいとき、そのプロセス専用のコピーを作って対応表の指す先を差し替えるカーネルの仕組み（4章、7章）。

### 関数呼び出し

- **スタックフレーム**：関数1回の呼び出しごとにスタックへ積まれる作業領域（5章）。
- **戻りアドレス**：`CALL` がスタックに積む「呼び出しの次の命令のアドレス」。`RET` がそれを取り出してジャンプする（5章、難所1）。
- **呼び出し規約**：引数と戻り値をどこに置くかの取り決め。スタック渡しとレジスタ渡しがある（5章、難所2）。
- **インライン展開**：小さな関数の呼び出しを、中身の埋め込みに置き換えるコンパイラ最適化。`CALL` ごと消える（5章）。
- **`//go:noinline`**：インライン展開を禁止するコンパイラ指示。本書の実験で観察対象を残すために使う（5章）。

### Goランタイム

- **ランタイム**：Goバイナリに同梱される実行支援機構。スケジューリングとメモリ管理を自前で行う（6章）。
- **goroutine**：Goランタイムが管理する実行単位。カーネルからは見えない（6章）。
- **g、m、p**：goroutine、OSスレッド、実行権をそれぞれ表すランタイム内部の構造体（6章）。
- **可動スタック**：goroutineのスタックが伸長時に別領域へ引っ越す性質（6章、難所1）。
- **ABIInternal**：Go 1.17以降の内部呼び出し規約。引数をレジスタで渡す（難所2）。
- **R14**：amd64で現在のgoroutineの `g` 構造体を指し続けるレジスタ（難所2）。

### eBPFとOBI

- **eBPF**：ユーザーが書いた小さなプログラムをカーネル内で安全に動かすLinuxの仕組み（7章）。
- **検証器（verifier）**：eBPFプログラムをロード前に静的解析し、停止性とメモリ安全を保証する機構（7章）。
- **マップ**：eBPFプログラムとユーザー空間が共有するカーネル管理のキーバリューストア（7章）。
- **uprobeとuretprobe**：命令アドレスの1バイトをブレークポイント命令に差し替えて置くフックと、関数の入口でスタック上の戻りアドレスを書き換えて復帰を捕まえる仕組み（7章、難所1）。
- **トランポリン**：uretprobeが戻りアドレスの書き換え先に使うカーネル側のコード（難所1）。
- **cilium/ebpf**：eBPFプログラムのロードとアタッチを行うGoのデファクトライブラリ（7章）。
- **リングバッファ**：カーネルからユーザー空間へイベントを渡す共有バッファ（8章）。
- **OBI**：OpenTelemetry eBPF Instrumentation。Beylaを前身とするeBPF自動計装ツール（8章）。
- **ゼロコード計装**：アプリのコードを変更せずに外から観測点を加えること（1章）。
- **プロトコル計装**：ソケットを流れるバイト列をプロトコルとして解釈する言語非依存の計装経路（8章）。
- **`offsets.json`**：OBIが持つ、Goとライブラリのバージョンごとのフィールドオフセット表（難所3）。
- **`bpf_probe_write_user`**：対象プロセスのユーザー空間メモリを書き換えるeBPFヘルパー（難所4）。

### 分散トレース

- **計装（instrumentation）**：処理時間や呼び出し関係を記録するために観測点を加えること（1章）。
- **分散トレース、トレースID、スパン**：複数サービスにまたがる1つの処理の記録と、その識別子、区間（1章）。
- **traceparent**：トレースIDとスパンIDをHTTPで運ぶW3C標準のヘッダ（1章、難所4）。
- **バックエンド**：テレメトリーの記録を集めて表示するサーバー（1章）。
- **コンテキスト伝搬**：トレースの識別情報をプロセスやサービスの境界を越えて引き継ぐこと（難所4）。
- **OTLP**：OpenTelemetryの標準テレメトリー転送プロトコル（8章）。

## 参考リンク

### OBI

- OpenTelemetry eBPF Instrumentation（OBI）: <https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation>
- OBI 公式ドキュメント: <https://opentelemetry.io/docs/zero-code/obi/>
- OBI 分散トレースのドキュメント: <https://opentelemetry.io/docs/zero-code/obi/distributed-traces/>
- サポート状況の一覧（`SUPPORT_MATRIX.md`）: <https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/main/SUPPORT_MATRIX.md>
- コンテキスト伝搬の設計メモ（`devdocs/context-propagation.md`）: <https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/blob/main/devdocs/context-propagation.md>

本書で引用したソースの位置は次のとおりです。

| 内容 | ファイル |
|---|---|
| `RET` 命令の探索 | `pkg/internal/goexec/instructions_amd64.go` |
| ELFの解析とmoduledataの探索 | `pkg/internal/goexec/instructions.go` |
| uprobeのアタッチ | `pkg/ebpf/instrumenter.go` |
| 引数レジスタと `g` ポインタのマクロ | `bpf/bpfcore/utils.h` |
| goroutineの識別子 | `bpf/common/go_addr_key.h` |
| goroutineの親子追跡 | `bpf/gotracer/go_runtime.c`、`bpf/gotracer/go_common.h` |
| ヘッダ注入 | `bpf/gotracer/go_nethttp.c` |
| オフセットの解決とビルド情報の読み取り | `pkg/internal/goexec/structmembers.go`、`pkg/internal/goexec/gofile.go` |
| オフセット表 | `pkg/internal/goexec/offsets.json` |
| 計装対象シンボルの一覧 | `pkg/internal/ebpf/gotracer/gotracer.go` |

### Go本体

- golang/go#22008（runtime: ebpf uretprobe support）: <https://github.com/golang/go/issues/22008>
- golang/go#27077（uprobeアタッチ時の `fatal error: unknown caller pc` の報告、クローズ済み）: <https://github.com/golang/go/issues/27077>
- golang/go#73798（goroutine起動フックの提案、not planned）: <https://github.com/golang/go/issues/73798>
- golang/go#63185（runtime/trace flight recorder、Go 1.25）: <https://github.com/golang/go/issues/63185>
- Go 1.17 Release Notes（レジスタベース呼び出し規約）: <https://go.dev/doc/go1.17>
- Go internal ABI 仕様: <https://github.com/golang/go/blob/master/src/cmd/compile/abi-internal.md>
- open-telemetry/opentelemetry-go-compile-instrumentation（Compile-Time Instrumentation SIG、`otelc`）: <https://github.com/open-telemetry/opentelemetry-go-compile-instrumentation>
- Announcing v1 of OpenTelemetry Go Compile-Time Instrumentation: <https://opentelemetry.io/blog/2026/go-compile-time-instrumentation-v1/>

### eBPF

- cilium/ebpf（Goのローダーライブラリ）: <https://github.com/cilium/ebpf>

### 登壇

- Go Conference 2026「OpenTelemetry eBPF Instrumentationの舞台裏」: <https://gocon.jp/2026/timetable/1263399/>

> 本書の実行結果は go1.26.5 linux/amd64 で確認したもので（9章のハンズオンのみ Linux 7.0.0-31-generic / Docker 29.0.0 上での実測）、アドレス値のように実行ごとに変わるものを含みます。OBIのコードはリリース `v0.13.0`（2026年9月4日）時点のものです。レジスタ割り当て、フィールドオフセット、ネスト上限といった値は、GoのバージョンやOBIのリリースにより変化しえます。実装の詳細を引用する際は、対象バージョンのソースで再確認してください。
