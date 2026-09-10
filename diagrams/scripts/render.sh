#!/usr/bin/env bash
# Graphviz（.dot）→ 技術書・記事用 PNG のレンダリング。
#
#   使い方: リポジトリのルート（diagrams/ と images/ がある場所）で実行する
#           ./path/to/scripts/render.sh [名前のパターン] [DPI]
#
# diagrams/**/ にある *.dot をすべて images/<同名>.png に書き出す。
# 引数1を渡すとファイル名にその文字列を含む .dot だけを対象にする。
# 引数2でDPIを指定できる（省略時は160、または RENDER_DPI 環境変数）。
# 本文幅より狭いカラムに埋め込む図だけ、個別に低いDPIで呼び直して
# 幅を詰める（例: ./render.sh some-wide-diagram 90）。`-Gsize=` によるPNG後の
# 引き伸ばし・圧縮はしない（ぼやける）。DPIを直接落として書き出し直すこと。
#
# 背景を透明にしたい場合（白背景でない場所に埋め込む図など）は
# RENDER_BGCOLOR=transparent を指定する。
#   RENDER_BGCOLOR=transparent ./render.sh
# `.dot` 内の `bgcolor="white"` は書き換えなくてよい。CLI側の `-Gbgcolor`
# が優先されるため上書きされる。
#
# パイプライン: dot -Tsvg → round.py（ノード・クラスタの角丸半径を統一）
#             → round_edges.py（splines=ortho の折れ線矢印の角を丸める）
#             → elbow.py（layout=neato で不可視の経由点ノードを挟んで折り曲げた
#               経路の、角に残る隙間をふさぐ。それ以外の辺は素通しする）
#             → nudge_xlabel_from_edge.py（xlabelが自分の経路に近すぎる／
#               触れている場合に押し出す）
#             → spread_parallel_edges.py（同じ2ノード間を往復する2本の
#               エッジが近すぎる場合に押し広げる）
#             → fix_tee_gap.py（arrowhead=tee の横棒を到達先の枠から離す）
#             → rsvg-convert（PNG化）
#
# 前提:
#   - graphviz（dot）。`layout=neato`（絶対座標指定）を使う図があるなら、
#     `neato -V` で実際にneatoレイアウトが使えるか確認すること。
#     Debian/Ubuntuの`graphviz`パッケージは最小構成だと neato/fdp/circo/twopi
#     のレイアウトプラグインを含まないことがあり、その場合 dot が
#     `Layout type: "neato" not recognized` / `no layout engine support for
#     "neato"` を出す。`sudo apt-get install libgvplugin-neato-layout8` で
#     入る（依存で `libgts-0.7-5t64` も入る）。sudoが使えない環境では
#     `apt-get download libgvplugin-neato-layout8 libgts-0.7-5t64` で
#     .deb を取得し `dpkg-deb -x` で展開、`GVBINDIR`/`LD_LIBRARY_PATH` に
#     展開先を指定して `dot -c` でプラグイン設定を再生成すれば、
#     システムにインストールせずに使える。
#   - rsvg-convert（librsvg2-bin。Debian/Ubuntu なら `sudo apt-get install librsvg2-bin`）
#   - 日本語のゴシック体フォント（Harano Aji Gothic / Noto Sans CJK JP / IPAGothic のいずれか）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATTERN="${1:-}"
DPI="${2:-${RENDER_DPI:-160}}"
BGCOLOR="${RENDER_BGCOLOR:-}"
NODE_RADIUS=6
EDGE_RADIUS=6
XLABEL_MARGIN=6
PARALLEL_GAP=16
TEE_GAP=14

shopt -s nullglob
for dotfile in diagrams/*/*.dot; do
    name="$(basename "$dotfile" .dot)"
    if [[ -n "$PATTERN" && "$name" != *"$PATTERN"* ]]; then
        continue
    fi
    echo "  ${dotfile} → images/${name}.png (dpi=${DPI}${BGCOLOR:+, bgcolor=$BGCOLOR})"
    dot -Tsvg ${BGCOLOR:+-Gbgcolor="$BGCOLOR"} "$dotfile" \
        | python3 "$SCRIPT_DIR/round.py" "$NODE_RADIUS" \
        | python3 "$SCRIPT_DIR/round_edges.py" "$EDGE_RADIUS" \
        | python3 "$SCRIPT_DIR/elbow.py" \
        | python3 "$SCRIPT_DIR/nudge_xlabel_from_edge.py" "$XLABEL_MARGIN" \
        | python3 "$SCRIPT_DIR/spread_parallel_edges.py" "$PARALLEL_GAP" \
        | python3 "$SCRIPT_DIR/fix_tee_gap.py" "$TEE_GAP" \
        | rsvg-convert --dpi-x "$DPI" --dpi-y "$DPI" -o "images/${name}.png"
done
