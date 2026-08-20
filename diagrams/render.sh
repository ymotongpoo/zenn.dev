#!/usr/bin/env bash
# Graphviz（.dot）→ Zenn 記事用 PNG のレンダリング。
#
#   使い方: ./diagrams/render.sh [名前のパターン]
#
# diagrams/**/ にある *.dot をすべて images/<同名>.png に書き出す。
# 引数を渡すとファイル名にその文字列を含む .dot だけを対象にする。
#
# 前提: graphviz（dot）と、日本語のゴシック体フォント
#       （Harano Aji Gothic / Noto Sans CJK JP / IPAGothic のいずれか）
set -euo pipefail

cd "$(dirname "$0")/.."
DPI=160
PATTERN="${1:-}"

shopt -s nullglob
for dotfile in diagrams/*/*.dot; do
    name="$(basename "$dotfile" .dot)"
    if [[ -n "$PATTERN" && "$name" != *"$PATTERN"* ]]; then
        continue
    fi
    echo "  ${dotfile} → images/${name}.png"
    dot -Tpng -Gdpi="$DPI" "$dotfile" -o "images/${name}.png"
done
