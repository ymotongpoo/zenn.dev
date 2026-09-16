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
# レイアウトエンジンは図ごとに選べる（RENDER_LAYOUT）。
#   RENDER_LAYOUT=auto ./render.sh     # 両方で組んで測り、良い方を採る（推奨）
#   RENDER_LAYOUT=elk  ./render.sh     # ELK を試す（組めない図は dot に落ちる）
#   RENDER_LAYOUT=dot  ./render.sh     # 既定。dot だけを使う
#
# auto は pick_layout.py が交差数・折れ数・辺長・縦横比・占有面積・
# ラベルの破綻を両エンジンで測り、点数の良い方を選ぶ。差がわずかなら
# dot を採る（後処理パイプラインが使えるぶん dot に下駄を履かせている）。
# スライド用に横長へ寄せたいときは RENDER_ASPECT=3.3 のように渡す。
#
# ELK を使うとき dot はラベルの組版だけを担当し、ノードの配置と直交配線は
# dot2elk.py（ELK/elkjs）が決める。下のSVG後処理は通らない（dot2elk.py が
# 角丸・進入禁止記号・端点クリップ・辺ラベルの再配置を自前で行う）。
# **rank=same のメンバー間に辺がある図は ELK では組めない**（ELK layered は
# 同一層内の辺をサポートしないため、横一列が縦に崩れる）。
# 詳細はSKILL.mdの「レイアウトエンジンを ELK に替える」を参照。
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
#   - RENDER_LAYOUT=elk / auto のときだけ node と elkjs（初回に dot2elk.py が
#     scripts/ へ npm install する）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATTERN="${1:-}"
DPI="${2:-${RENDER_DPI:-160}}"
BGCOLOR="${RENDER_BGCOLOR:-}"
LAYOUT="${RENDER_LAYOUT:-dot}"
ASPECT="${RENDER_ASPECT:-}"
NODE_RADIUS=6
EDGE_RADIUS=6
XLABEL_MARGIN=6
PARALLEL_GAP=16
TEE_GAP=14

render_with_dot() {
    dot -Tsvg ${BGCOLOR:+-Gbgcolor="$1"} "$2" \
        | python3 "$SCRIPT_DIR/round.py" "$NODE_RADIUS" \
        | python3 "$SCRIPT_DIR/round_edges.py" "$EDGE_RADIUS" \
        | python3 "$SCRIPT_DIR/elbow.py" \
        | python3 "$SCRIPT_DIR/nudge_xlabel_from_edge.py" "$XLABEL_MARGIN" \
        | python3 "$SCRIPT_DIR/spread_parallel_edges.py" "$PARALLEL_GAP" \
        | python3 "$SCRIPT_DIR/fix_tee_gap.py" "$TEE_GAP" \
        | rsvg-convert --dpi-x "$DPI" --dpi-y "$DPI" -o "$3"
}

render_with_elk() {
    local tmpsvg
    tmpsvg="$(mktemp --suffix=.svg)"
    python3 "$SCRIPT_DIR/dot2elk.py" "$1" "$tmpsvg" >/dev/null
    rsvg-convert --dpi-x "$DPI" --dpi-y "$DPI" -o "$2" "$tmpsvg"
    rm -f "$tmpsvg"
}

shopt -s nullglob
for dotfile in diagrams/*/*.dot; do
    name="$(basename "$dotfile" .dot)"
    if [[ -n "$PATTERN" && "$name" != *"$PATTERN"* ]]; then
        continue
    fi

    engine="$LAYOUT"
    if [[ "$LAYOUT" == "auto" ]]; then
        # 両方で組んで測り、良い方を選ぶ。1行目に dot か elk が出る。
        engine="$(python3 "$SCRIPT_DIR/pick_layout.py" \
                    ${ASPECT:+--target-aspect "$ASPECT"} "$dotfile" \
                    2>/dev/null | head -1)"
        [[ "$engine" == "elk" ]] || engine="dot"
    elif [[ "$LAYOUT" == "elk" ]]; then
        # ELK で組めない図（rank=same 内に辺がある）は dot に落とす
        if python3 "$SCRIPT_DIR/check_flat_edges.py" "$dotfile" \
                | grep -q '^FLAT-EDGE'; then
            echo "    警告: rank=same 内に辺があるため ELK では組めない。dot で描画する" >&2
            engine="dot"
        fi
    fi

    echo "  ${dotfile} → images/${name}.png (dpi=${DPI}, layout=${engine}${BGCOLOR:+, bgcolor=$BGCOLOR})"
    if [[ "$engine" == "elk" ]]; then
        render_with_elk "$dotfile" "images/${name}.png"
    else
        render_with_dot "$BGCOLOR" "$dotfile" "images/${name}.png"
    fi
done
