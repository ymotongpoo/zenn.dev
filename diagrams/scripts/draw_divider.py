#!/usr/bin/env python3
# 対比図の2つのクラスタの間に、図の全幅に渡る区切り線を引く後処理。
#
# なぜ後処理なのか: Graphviz には「図の全幅に渡る線」を引く手段がない。
# 不可視ノード2つを rank=same で並べて実線で結ぶ方法は、線が中央に短く
# 浮くだけでなく、両端をクラスタの端へ揃えようと不可視辺を足した時点で
# ランク制約がノードの並び順を崩す（A B C が B A C になる）。ランクを
# 跨ぐ「装飾としての線」は dot のレイアウトモデルの外にある。
#
# 使い方: `.dot` の冒頭に次のコメントを置くと、上下に隣接する2つの
# クラスタの隙間の中央へ線を引く。
#
#     // @divider: between-clusters
#
# 線は両クラスタのうち広い方の幅に揃え、灰の細線（モデル内の矢印と
# 読み違えないため）で描く。クラスタが2つでない図、マーカーの無い図は
# 何もせずに素通しする。
#
#   使い方: render.sh のパイプラインに挟む
#     python3 draw_divider.py <dotfile> < in.svg > out.svg

import re
import sys

STROKE = "#B4B4B4"
WIDTH = 1.2


def main():
    if len(sys.argv) < 2:
        sys.stdout.write(sys.stdin.read())
        return
    try:
        src = open(sys.argv[1], encoding="utf-8").read()
    except OSError:
        sys.stdout.write(sys.stdin.read())
        return

    svg = sys.stdin.read()
    if "@divider: between-clusters" not in src:
        sys.stdout.write(svg)
        return

    # クラスタの枠は、round.py が角丸を統一する過程で <path> から <rect> へ
    # 書き換えられている（パイプラインの後段で動くこのスクリプトが見るのは
    # 常に <rect>）。<path> のままの場合にも備えて両方を読む。
    frames = []
    for m in re.finditer(r'<g id="[^"]*" class="cluster"[^>]*>(.*?)</g>', svg, re.S):
        inner = m.group(1)
        rect = re.search(r'<rect[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"'
                         r'[^>]*\bwidth="([\d.]+)"[^>]*\bheight="([\d.]+)"', inner)
        if rect:
            x, y, w, h = (float(v) for v in rect.groups())
            frames.append((x, y, x + w, y + h))
            continue
        pts = [tuple(map(float, p.split(",")))
               for p in re.findall(r'([-\d.]+,[-\d.]+)', inner)]
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        frames.append((min(xs), min(ys), max(xs), max(ys)))

    if len(frames) != 2:
        sys.stdout.write(svg)
        return

    # SVG の y は下向き。上下の並びで上になるのは y の小さい方。
    frames.sort(key=lambda f: f[1])
    top, bottom = frames
    gap_top, gap_bottom = top[3], bottom[1]
    if gap_bottom <= gap_top:
        sys.stdout.write(svg)          # 左右に並んでいる図。何もしない
        return

    y = (gap_top + gap_bottom) / 2.0
    x0 = min(top[0], bottom[0])
    x1 = max(top[2], bottom[2])
    line = (f'<line x1="{x0:.2f}" y1="{y:.2f}" x2="{x1:.2f}" y2="{y:.2f}" '
            f'stroke="{STROKE}" stroke-width="{WIDTH}"/>\n')

    # 最後の </g></svg> の直前に差し込む（座標系は graph の <g> の中）。
    idx = svg.rfind("</g>")
    if idx < 0:
        sys.stdout.write(svg)
        return
    sys.stdout.write(svg[:idx] + line + svg[idx:])


if __name__ == "__main__":
    main()
