#!/usr/bin/env python3
"""splines=ortho で出力した Graphviz SVG の、エッジの折れ角を丸める。

dot -Tsvg (splines=ortho) は各エッジを水平・垂直線分だけの折れ線として
Bezier コマンド (`C`) の羅列で出力する（制御点が端点に一致する退化した
Bezier で、実質は直線）。このスクリプトは各エッジの `<path fill="none" .../>`
から頂点列を復元し、直線が90度に曲がる頂点だけを二次 Bezier
（曲がる手前・先の2点を端点、頂点そのものを制御点とする `Q`）に置き換える。

    使い方: dot -Tsvg -Gsplines=ortho foo.dot | round_edges.py [半径] > foo.svg
"""

import re
import sys

TOLERANCE = 0.01

EDGE_GROUP = re.compile(r'(<g[^>]*class="edge"[^>]*>.*?</g>)', re.S)
PATH = re.compile(r'<path\b([^>]*?)/>', re.S)
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
NUM = re.compile(r'-?\d+(?:\.\d+)?')


def parse_path_points(d):
    """折れ線の d 属性から、重複する端点を除いた頂点列を取り出す。"""
    nums = [float(n) for n in NUM.findall(d)]
    if len(nums) % 2 or len(nums) < 4:
        return None
    pts = list(zip(nums[0::2], nums[1::2]))
    dedup = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - dedup[-1][0]) > TOLERANCE or abs(p[1] - dedup[-1][1]) > TOLERANCE:
            dedup.append(p)
    return dedup if len(dedup) >= 2 else None


def is_axis_aligned(pts):
    """すべての線分が水平か垂直かを確認する。"""
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if abs(x0 - x1) > TOLERANCE and abs(y0 - y1) > TOLERANCE:
            return False
    return True


def round_polyline(pts, radius):
    """頂点列から、折れ角を Q コマンドで丸めた path d を組み立てる。"""
    if len(pts) < 3:
        x0, y0 = pts[0]
        x1, y1 = pts[-1]
        return f'M{x0:.2f},{y0:.2f} L{x1:.2f},{y1:.2f}'

    segs = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        segs.append(((x1 - x0), (y1 - y0)))
    lens = [ (dx ** 2 + dy ** 2) ** 0.5 for dx, dy in segs ]

    out = [f'M{pts[0][0]:.2f},{pts[0][1]:.2f}']
    for i in range(1, len(pts) - 1):
        vx, vy = pts[i]
        dx0, dy0 = segs[i - 1]
        dx1, dy1 = segs[i]
        l0, l1 = lens[i - 1], lens[i]
        r = min(radius, l0 / 2, l1 / 2)
        if r < TOLERANCE:
            out.append(f'L{vx:.2f},{vy:.2f}')
            continue
        ax = vx - dx0 / l0 * r
        ay = vy - dy0 / l0 * r
        bx = vx + dx1 / l1 * r
        by = vy + dy1 / l1 * r
        out.append(f'L{ax:.2f},{ay:.2f}')
        out.append(f'Q{vx:.2f},{vy:.2f} {bx:.2f},{by:.2f}')
    ex, ey = pts[-1]
    out.append(f'L{ex:.2f},{ey:.2f}')
    return ' '.join(out)


def convert_edge_group(group, radius):
    def repl(m):
        attrs = dict(ATTR.findall(m.group(1)))
        if attrs.get('fill') != 'none':
            return m.group(0)
        d = attrs.get('d', '')
        pts = parse_path_points(d)
        if pts is None or not is_axis_aligned(pts):
            return m.group(0)
        new_d = round_polyline(pts, radius)
        attrs['d'] = new_d
        keep = ' '.join(f'{k}="{v}"' for k, v in attrs.items())
        return f'<path {keep}/>'

    return PATH.sub(repl, group)


def main():
    radius = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    svg = sys.stdin.read()
    sys.stdout.write(EDGE_GROUP.sub(lambda m: convert_edge_group(m.group(1), radius), svg))


if __name__ == '__main__':
    main()
