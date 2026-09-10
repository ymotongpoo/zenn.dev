#!/usr/bin/env python3
"""tee矢印（`arrowhead=tee`）を、枠から離れた「進入禁止」記号（丸に斜線）に
置き換える後処理。

Graphviz の `arrowhead=tee` は、禁止・無効化を表すためによく使われるが、
描画されるのは矢じり（三角形）ではなく、進行方向に垂直な小さな横棒
1本だけである。これがノードの枠のごく近傍（1pt未満）に描かれるため、
(1) 枠線の太さと視覚的に融合して「矢印の先が箱に埋まっている」ように
見える、(2) 見る側には「矢じりの三角が壊れている・消えている」ように
誤読される、という2つの問題があった（横棒を単に枠から遠ざける対処だけ
では(2)は解決しない。そもそも見る側は「三角の矢じりがあるはず」という
前提で見ているため、三角ではない横棒がぽつんと離れて浮いていると、
今度は「矢印の先そのものが消えた」ように見える）。

このスクリプトは tee矢印特有のSVG構造 --- `<path>`（本体の線）+
`<polygon>`（横棒本体）+ もう1つの `<polyline>`（軸に沿った短い芯線）
の組 --- を検出し、`<polygon>` と `<polyline>` を、国際的な「進入禁止」
標識と同じ見た目（丸＋斜線）の `<circle>` + `<line>` に置き換える。
本体の `<path>` は、線がこの丸の縁（ノード側の端）にちょうど届くまで
延長する。斜線は経路の向きに関わらず常に右下がり45度で統一する
（回転させると同じ記号だと認識しにくくなるため）。

    使い方: ... | fix_tee_gap.py [枠からの距離pt] [半径pt] > out.svg

round_edges.py の後（パイプラインの最後）に置く。round_edges.py は
`fill="none"` の `<path>` だけを書き換えるため、このスクリプトが処理する
`<polygon>` / `<polyline>` とは競合しない。
"""

import re
import sys

EDGE_GROUP = re.compile(r'(<g[^>]*class="edge"[^>]*>.*?</g>)', re.S)
PATH = re.compile(r'<path\b([^>]*?)/>')
POLYGON = re.compile(r'<polygon\b([^>]*?)/>')
POLYLINE = re.compile(r'<polyline\b([^>]*?)/>')
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
NUM = re.compile(r'-?\d+(?:\.\d+)?')
COORD_PAIR = re.compile(r'(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)')
DIAG = 0.70710678  # cos45 = sin45


def process_group(group, gap, radius):
    polyline_matches = list(POLYLINE.finditer(group))
    polygon_matches = list(POLYGON.finditer(group))
    if len(polyline_matches) != 1 or len(polygon_matches) != 1:
        return group  # tee矢印特有の構造（芯線1本+横棒1つ）でなければ何もしない

    pl_attrs = dict(ATTR.findall(polyline_matches[0].group(1)))
    nums = [float(n) for n in NUM.findall(pl_attrs.get('points', ''))]
    if len(nums) != 4:
        return group
    x0, y0, x1, y1 = nums  # (x0,y0)=元の枠側の点、(x1,y1)=元の芯線の遠い側の点
    dx, dy = x1 - x0, y1 - y0
    length = (dx ** 2 + dy ** 2) ** 0.5
    if length < 0.01:
        return group
    ux, uy = dx / length, dy / length  # ノードから離れる向きの単位ベクトル

    poly_attrs = dict(ATTR.findall(polygon_matches[0].group(1)))
    color = poly_attrs.get('stroke') or poly_attrs.get('fill') or '#000000'
    stroke_width = poly_attrs.get('stroke-width', '1.4')

    # 記号（丸）の中心 = 元の芯線の遠い側の点を、指定距離だけさらに離した位置
    cx = x1 + ux * gap
    cy = y1 + uy * gap
    # 線の終点 = 丸のノード側の縁（丸の中まで線を突っ込ませない）
    path_end_x = cx + ux * radius
    path_end_y = cy + uy * radius

    circle = (f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{radius:.2f}" '
              f'fill="none" stroke="{color}" stroke-width="{stroke_width}"/>')
    lx0, ly0 = cx - radius * DIAG, cy - radius * DIAG
    lx1, ly1 = cx + radius * DIAG, cy + radius * DIAG
    diagonal = (f'<line x1="{lx0:.2f}" y1="{ly0:.2f}" x2="{lx1:.2f}" y2="{ly1:.2f}" '
                f'stroke="{color}" stroke-width="{stroke_width}"/>')

    def repl_path(m):
        attrs = dict(ATTR.findall(m.group(1)))
        if attrs.get('fill') != 'none':
            return m.group(0)
        d = attrs.get('d', '')
        matches = list(COORD_PAIR.finditer(d))
        if not matches:
            return m.group(0)
        last = matches[-1]
        new_coord = f'{path_end_x:.2f},{path_end_y:.2f}'
        attrs['d'] = d[:last.start()] + new_coord + d[last.end():]
        keep = ' '.join(f'{k}="{v}"' for k, v in attrs.items())
        return f'<path {keep}/>'

    group = PATH.sub(repl_path, group, count=1)
    group = POLYLINE.sub('', group, count=1)
    group = POLYGON.sub(circle + diagonal, group, count=1)
    return group


def main():
    gap = float(sys.argv[1]) if len(sys.argv) > 1 else 14.0
    radius = float(sys.argv[2]) if len(sys.argv) > 2 else 7.0
    svg = sys.stdin.read()
    sys.stdout.write(EDGE_GROUP.sub(lambda m: process_group(m.group(1), gap, radius), svg))


if __name__ == '__main__':
    main()
