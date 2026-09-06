#!/usr/bin/env python3
"""Graphviz が出力した SVG の角丸を、指定した半径に描き直す。

Graphviz の角丸半径は 12pt 固定で、属性からは変えられない。ノードとクラスタの
角丸矩形は SVG では 8 つのコーナーを持つ <path> として出力されるため、これを
検出して <rect rx> に置き換える。

    使い方: dot -Tsvg foo.dot | round.py [半径] > foo.svg
"""

import re
import sys

GRAPHVIZ_RADIUS = 12.0  # Graphviz が使う固定の角丸半径（pt）
TOLERANCE = 0.05

# <g ...class="node|cluster"...> ... </g> の中の <path .../>
GROUP = re.compile(r'<g[^>]*class="(?:node|cluster)"[^>]*>.*?</g>', re.S)
PATH = re.compile(r"<path\b([^>]*?)/>", re.S)
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def parse_points(d):
    """パスの d 属性から座標の列を取り出す。"""
    nums = [float(n) for n in NUM.findall(d)]
    if len(nums) % 2:
        return None
    return list(zip(nums[0::2], nums[1::2]))


def rounded_rect_bbox(d):
    """d が Graphviz の角丸矩形なら (x, y, w, h) を返す。違えば None。"""
    if "C" not in d:
        return None
    pts = parse_points(d)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    r = GRAPHVIZ_RADIUS
    if x1 - x0 <= 2 * r or y1 - y0 <= 2 * r:
        return None
    # 角丸矩形なら、すべての点が辺上（コーナーの制御点を含む）に載る
    edges_x = (x0, x0 + r / 2, x0 + r, x1 - r, x1 - r / 2, x1)
    edges_y = (y0, y0 + r / 2, y0 + r, y1 - r, y1 - r / 2, y1)
    for x, y in pts:
        on_x = any(abs(x - e) < TOLERANCE for e in edges_x)
        on_y = any(abs(y - e) < TOLERANCE for e in edges_y)
        if not (on_x and on_y):
            return None
    return x0, y0, x1 - x0, y1 - y0


def convert_group(group, radius):
    def repl(m):
        attrs = dict(ATTR.findall(m.group(1)))
        d = attrs.pop("d", "")
        box = rounded_rect_bbox(d)
        if box is None:
            return m.group(0)
        x, y, w, h = box
        keep = " ".join(f'{k}="{v}"' for k, v in attrs.items())
        return (
            f'<rect {keep} x="{x:.2f}" y="{y:.2f}" '
            f'width="{w:.2f}" height="{h:.2f}" rx="{radius}" ry="{radius}"/>'
        )

    return PATH.sub(repl, group)


def main():
    radius = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
    svg = sys.stdin.read()
    sys.stdout.write(GROUP.sub(lambda m: convert_group(m.group(0), radius), svg))


if __name__ == "__main__":
    main()
