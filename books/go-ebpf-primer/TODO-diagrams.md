# 図版の要修正一覧（本文修正 2026-09-09 に伴うもの）

2026-09-09の技術検証（`reviews/20260909-go-ebpf-primer-technical-verification.md`）を受けて本文を修正した結果、図版の内容と食い違う可能性がある箇所。図版PNGを開いて該当する描写があれば直す。

- `/images/20260911-elf-sections.png`（15-source_to_binary.md 図4）: 「実行に要るのは `.text` だけ」という対応になっていれば、`.rodata` / `.data` / `.bss` / `.gopclntab` も実行側に含める。読む側のためだけにあるのは `.symtab` とDWARF。
- `/images/20260911-obi-two-paths.png`（35-obi.md 図2）: 「関数レベルの計装を持つのはGoだけ」と描いていれば、「ライブラリの関数を狙う経路を持つのはGoだけ」に直す。ランタイム内部へのフックはRuby、Python、Node.js、Javaにもある。
- `/images/20260911-handson-topology.png`（37-handson.md 図1）: `grafana/otel-lgtm` のコンテナにLokiとPyroscopeも含まれる。本章で使う4つに限る旨が図中で読み取れるようにする。
- `/images/20260911-abi-shift.png`（45-hurdle2_abi.md 図1）: 「Cの規約で読むと第4引数が返る」という表現があれば、「4本目のレジスタで渡される値が返る」に直す。引数の型（文字列は2本、スライスは3本）によって何番目の引数がそこに来るかは変わる。
