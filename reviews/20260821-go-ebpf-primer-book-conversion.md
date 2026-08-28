# book化の記録: OpenTelemetry eBPF Instrumentationの舞台裏

記事 `articles/20260820-go-ebpf-instrumentation.md` を、Go Conference 2026登壇「[OpenTelemetry eBPF Instrumentationの舞台裏](https://gocon.jp/2026/timetable/1263399/)」の解説資料として `books/go-ebpf-primer/`（15チャプター）へ全面移行した。記事ファイルは削除した（内容はすべてbookに吸収済み。履歴はgitに残る）。

## 方針

- 想定読者を「計算機科学を学び始めた人」まで広げ、前提知識パートをCPUとメモリの仕組みから積み上げる4章構成（2〜5章）に拡張した。2進数の算術や電子回路には立ち入らず、Goの基本文法が読めることは引き続き前提とする。
- 前回の指導者レビューで削除した初歩的な図3枚（ユーザー空間とカーネル空間、CPUとレジスタ、プロセスのメモリ）は、この読者設定では必要なため復活させた。
- 各節に手元で確かめられる実験を1つ置く方針を前提章にも適用し、新規実験（Sizeofと%p、ポインタの数値化、PID、再帰でフレームのアドレスが下がる観察、traceparentの直列化など）はすべて go1.26.5 linux/amd64（docker --platform linux/amd64）で実測してから本文に載せた。
- 8章「OBIとは何か」を独立章に昇格し、処理パイプライン（発見→ELF解析→ロードとアタッチ→イベント収集→エクスポート）、Dockerでの最小実行例と主要環境変数、リポジトリの地図を加筆した。パイプラインの記述はOBI v0.11.0のソース（pkg/appolly/discover、pkg/ebpf、pkg/export ほか）と公式ドキュメントで裏取りした。
- 難所1〜4の章は記事の内容をほぼ無改変で移し、節参照を章参照（「N章で見た」、1始まりの通し番号）へ張り替えた。

## 構成の要点

- チャプター命名は `{2桁番号}-{snake_case}.md`。挿入余地のためストライド5で採番（00, 05, 10, …, 65, 99）。
- 図版は `diagrams/go-ebpf-primer/`（旧 `diagrams/20260820-go-ebpf-instrumentation/` をgit mv）。既存の `20260820-` プレフィクスのファイル名は維持し、新図12枚も同じ形式で追加した。合計49枚で、各章のキャプションで図1から振り直した。
- 前提章（2〜5章）には章末に「この章から難所へ持っていくもの」と確認問題（解答は `:::details`）を置いた。付録（99）に用語集約60語と参考リンクを置いた。

## 新規追加した図

memory-byte-band、fetch-execute-loop、pointer-and-address、struct-padding（以上2章）、program-vs-process、virtual-to-physical、process-threads（以上3章）、disassemble-boundaries、dwarf-field-mapping（以上4章）、call-ret-timeline、convention-stack-vs-register（以上5章）、obi-pipeline（8章）。source-to-executionは注記を章名に更新して1章の地図とした。
