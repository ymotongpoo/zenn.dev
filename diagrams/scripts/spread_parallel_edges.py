#!/usr/bin/env python3
"""同じ2ノード間を往復する2本の直線エッジを、互いに一定距離離す後処理。

`dot`（`splines=ortho`）は、同じ2ノードを結ぶ複数のエッジ（例えば行きと
戻りを別エッジで描く場合）を、内部の固定オフセット（数pt程度）だけ
ずらして描く。ノードの大きさやnodesep/ranksepを変えてもこのオフセットは
変わらないため、実線と破線のような対になる矢印が窮屈に見えることがある。

このスクリプトは、SVG上でタイトルが `A->B` / `B->A` の関係にあり、
かつ経路が軸並行な直線（曲がりなし）で互いに平行なエッジの組を見つけ、
その間隔が閾値未満なら、経路（`<path>`）と矢じり（`<polygon>`）を
進行方向に垂直な方向へ押し広げる。

**ノードの実際の大きさを超えて押し広げない。** 両端のノード（`class="node"`
グループ内の全図形の座標から外形bboxを求める）が実際に重なっている範囲から、
角丸のカット領域を避ける安全マージン（既定8pt）を引いた範囲だけを
「安全に押し広げられる範囲」とし、シフト量をこの範囲にクランプする。
安全な範囲が確保できない（＝ノード同士の重なりがそもそも狭い）場合は、
何もしない。目標間隔に届かないとしても、矢印がノードの外にはみ出すよりは
近いままの方がよい。

    使い方: ... | spread_parallel_edges.py [目標間隔pt] > out.svg

round_edges.py の後（パイプラインの最後、fix_tee_gap.py の前でも後でも良い）
に置く。
"""

import re
import sys
from collections import defaultdict

NODE_GROUP = re.compile(r'<g[^>]*class="node"[^>]*>.*?</g>', re.S)
EDGE_GROUP = re.compile(r'<g[^>]*class="edge"[^>]*>.*?</g>', re.S)
TITLE = re.compile(r'<title>(.*?)</title>')
PATH = re.compile(r'<path\b([^>]*?)/>')
SHAPE = re.compile(r'<(?:path|polygon|polyline)\b([^>]*?)/>')
POLYGON = re.compile(r'<polygon\b([^>]*?)/>')
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
NUM = re.compile(r'-?\d+(?:\.\d+)?')
TOLERANCE = 0.5
CORNER_MARGIN = 8.0


def pair_key(title):
    t = title.replace('&#45;&gt;', '\x00').replace('->', '\x00')
    if '\x00' not in t:
        return None, None
    a, b = t.split('\x00', 1)
    return a.strip(), b.strip()


def node_bboxes(svg):
    """ノード名 -> (minx, maxx, miny, maxy) のdict。"""
    boxes = {}
    for m in NODE_GROUP.finditer(svg):
        group = m.group(0)
        title_m = TITLE.search(group)
        if not title_m:
            continue
        name = title_m.group(1).strip()
        xs, ys = [], []
        for shape_m in SHAPE.finditer(group):
            attrs = dict(ATTR.findall(shape_m.group(1)))
            coord_str = attrs.get('d') or attrs.get('points') or ''
            nums = [float(n) for n in NUM.findall(coord_str)]
            xs.extend(nums[0::2])
            ys.extend(nums[1::2])
        if xs and ys:
            boxes[name] = (min(xs), max(xs), min(ys), max(ys))
    return boxes


def get_path_points(group):
    m = PATH.search(group)
    if not m:
        return None
    attrs = dict(ATTR.findall(m.group(1)))
    d = attrs.get('d', '')
    nums = [float(n) for n in NUM.findall(d)]
    if len(nums) % 2 or len(nums) < 4:
        return None
    pts = list(zip(nums[0::2], nums[1::2]))
    dedup = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - dedup[-1][0]) > 0.01 or abs(p[1] - dedup[-1][1]) > 0.01:
            dedup.append(p)
    return dedup


def orientation(pts):
    """全区間が縦直線なら'v'、横直線なら'h'、それ以外はNone。"""
    xs = {round(x, 1) for x, _ in pts}
    ys = {round(y, 1) for _, y in pts}
    if len(xs) == 1 and len(ys) > 1:
        return 'v', pts[0][0]
    if len(ys) == 1 and len(xs) > 1:
        return 'h', pts[0][1]
    return None, None


def safe_range(bbox_a, bbox_b, axis):
    """2ノードのbboxが重なる範囲から、角丸を避ける安全マージンを引いた範囲。"""
    idx = 0 if axis == 'v' else 2  # v: x範囲(0,1)を見る、h: y範囲(2,3)を見る
    a_lo, a_hi = bbox_a[idx], bbox_a[idx + 1]
    b_lo, b_hi = bbox_b[idx], bbox_b[idx + 1]
    lo = max(a_lo, b_lo) + CORNER_MARGIN
    hi = min(a_hi, b_hi) - CORNER_MARGIN
    return lo, hi


def shift_group(group, axis, delta):
    if abs(delta) < 1e-6:
        return group

    def shift_path(m):
        attrs = dict(ATTR.findall(m.group(1)))
        d = attrs.get('d', '')

        def repl(mm):
            nums = [float(n) for n in NUM.findall(mm.group(0))]
            pairs = []
            for i in range(0, len(nums) - 1, 2):
                x, y = nums[i], nums[i + 1]
                if axis == 'v':
                    x += delta
                else:
                    y += delta
                pairs.append(f'{x:.2f},{y:.2f}')
            return ' '.join(pairs)

        new_d = re.sub(r'(?:-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?\s*)+', repl, d)
        attrs['d'] = new_d
        keep = ' '.join(f'{k}="{v}"' for k, v in attrs.items())
        return f'<path {keep}/>'

    def shift_poly(m):
        attrs = dict(ATTR.findall(m.group(1)))
        nums = [float(n) for n in NUM.findall(attrs.get('points', ''))]
        pairs = []
        for i in range(0, len(nums) - 1, 2):
            x, y = nums[i], nums[i + 1]
            if axis == 'v':
                x += delta
            else:
                y += delta
            pairs.append(f'{x:.2f},{y:.2f}')
        attrs['points'] = ' '.join(pairs)
        keep = ' '.join(f'{k}="{v}"' for k, v in attrs.items())
        return f'<polygon {keep}/>'

    group = PATH.sub(shift_path, group, count=1)
    group = POLYGON.sub(shift_poly, group)
    return group


def main():
    target = float(sys.argv[1]) if len(sys.argv) > 1 else 16.0
    svg = sys.stdin.read()

    boxes = node_bboxes(svg)

    groups = list(EDGE_GROUP.finditer(svg))
    by_pair = defaultdict(list)
    for m in groups:
        group = m.group(0)
        title_m = TITLE.search(group)
        if not title_m:
            continue
        a, b = pair_key(title_m.group(1))
        if a is None:
            continue
        key = frozenset((a, b))
        pts = get_path_points(group)
        if pts is None:
            continue
        axis, coord = orientation(pts)
        if axis is None:
            continue
        by_pair[key].append({
            'span': m.span(),
            'group': group,
            'axis': axis,
            'coord': coord,
            'pts': pts,
            'node_a': a,
            'node_b': b,
        })

    replacements = {}
    for key, edges in by_pair.items():
        if len(edges) != 2:
            continue
        e0, e1 = edges
        if e0['axis'] != e1['axis']:
            continue
        # 経路の範囲が重なっている（平行に並走している）ことを確認する
        axis_idx = 1 if e0['axis'] == 'v' else 0
        r0 = sorted(p[axis_idx] for p in e0['pts'])
        r1 = sorted(p[axis_idx] for p in e1['pts'])
        if r0[-1] < r1[0] - TOLERANCE or r1[-1] < r0[0] - TOLERANCE:
            continue
        gap = abs(e1['coord'] - e0['coord'])
        if gap >= target:
            continue

        a_name, b_name = sorted(key)
        if a_name not in boxes or b_name not in boxes:
            continue
        lo, hi = safe_range(boxes[a_name], boxes[b_name], e0['axis'])
        if hi <= lo:
            continue  # 重なりが狭すぎて安全に押し広げられない

        if e0['coord'] <= e1['coord']:
            e_lo, e_hi = e0, e1
        else:
            e_lo, e_hi = e1, e0
        center = (e_lo['coord'] + e_hi['coord']) / 2
        want_lo = center - target / 2
        want_hi = center + target / 2
        new_lo = max(want_lo, lo)
        new_hi = min(want_hi, hi)
        if new_hi - new_lo <= gap + TOLERANCE:
            continue  # クランプした結果、現状より広がらないなら何もしない

        delta_lo = new_lo - e_lo['coord']
        delta_hi = new_hi - e_hi['coord']
        replacements[e_lo['span']] = shift_group(e_lo['group'], e_lo['axis'], delta_lo)
        replacements[e_hi['span']] = shift_group(e_hi['group'], e_hi['axis'], delta_hi)

    if not replacements:
        sys.stdout.write(svg)
        return

    out = []
    last = 0
    for span, _ in sorted(replacements.items()):
        start, end = span
        out.append(svg[last:start])
        out.append(replacements[span])
        last = end
    out.append(svg[last:])
    sys.stdout.write(''.join(out))


if __name__ == '__main__':
    main()
