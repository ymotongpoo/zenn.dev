#!/usr/bin/env python3
"""折れ線エッジの角の隙間をふさぐ。

neato の固定座標レイアウトでは、折れ位置を不可視の経由点ノードで表すため、
各区間のエッジが経由点の手前（約1pt）で切れて、角に隙間が見える。この後処理は

1. 近接するエッジ端点（3pt以内）を1つの交点座標にスナップし、
2. 同じ見た目（色・太さ・線種）の2本が突き合う角は1本のパスに結合して角を丸め、
3. 3本以上が集まるT字などの交点は、丸い線端（stroke-linecap）で notch を埋める。

    使い方: dot -Tsvg foo.dot | round.py | elbow.py > foo.svg
"""

import math
import re
import sys

EPS = 3.0        # この距離以内の端点は同じ交点とみなす
CORNER_R = 6.0   # 角丸の半径（pt）

EDGE_G = re.compile(r'<g id="[^"]*" class="edge">.*?</g>', re.S)
PATH = re.compile(r'<path fill="none"([^>]*?)\bd="([^"]+)"([^>]*)/>')
NUM = re.compile(r"-?\d+(?:\.\d+)?")


class Seg:
    def __init__(self, gid, attrs_pre, attrs_post, d):
        self.gid = gid
        self.attrs_pre = attrs_pre
        self.attrs_post = attrs_post
        nums = [float(n) for n in NUM.findall(d)]
        pts = list(zip(nums[0::2], nums[1::2]))
        self.p0 = pts[0]
        self.p1 = pts[-1]
        self.dead = False

    def style_key(self):
        s = self.attrs_pre + self.attrs_post
        stroke = re.search(r'stroke="([^"]*)"', s)
        width = re.search(r'stroke-width="([^"]*)"', s)
        dash = re.search(r'stroke-dasharray="([^"]*)"', s)
        return (
            stroke.group(1) if stroke else "",
            width.group(1) if width else "",
            dash.group(1) if dash else "",
        )


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def main():
    svg = sys.stdin.read()

    # エッジグループからパス（直線区間）を集める
    segs = []
    groups = list(EDGE_G.finditer(svg))
    for gi, g in enumerate(groups):
        m = PATH.search(g.group(0))
        if not m:
            continue
        segs.append(Seg(gi, m.group(1), m.group(3), m.group(2)))

    # 端点をクラスタリング（総当たりでよい規模）
    ends = []  # (seg, which) which: 0=p0, 1=p1
    for s in segs:
        ends.append([s, 0])
        ends.append([s, 1])
    parent = list(range(len(ends)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def pt(e):
        return e[0].p0 if e[1] == 0 else e[0].p1

    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            if ends[i][0] is ends[j][0]:
                continue
            if dist(pt(ends[i]), pt(ends[j])) <= EPS:
                parent[find(i)] = find(j)

    clusters = {}
    for i in range(len(ends)):
        clusters.setdefault(find(i), []).append(ends[i])

    # 交点座標を決めて端点をスナップする。
    # 各区間は水平か垂直なので、垂直な区間のx・水平な区間のyを信じる。
    for members in clusters.values():
        if len(members) < 2:
            continue
        xs, ys = [], []
        for seg, which in members:
            vertical = abs(seg.p0[0] - seg.p1[0]) < 0.5
            horizontal = abs(seg.p0[1] - seg.p1[1]) < 0.5
            p = seg.p0 if which == 0 else seg.p1
            if vertical:
                xs.append(p[0])
            if horizontal:
                ys.append(p[1])
        allpts = [pt(e) for e in members]
        jx = sum(xs) / len(xs) if xs else sum(p[0] for p in allpts) / len(allpts)
        jy = sum(ys) / len(ys) if ys else sum(p[1] for p in allpts) / len(allpts)
        for seg, which in members:
            if which == 0:
                seg.p0 = (jx, jy)
            else:
                seg.p1 = (jx, jy)

    # 次数2かつ同スタイルの角は連結して1本の折れ線にする
    joins = {}  # id(seg) -> {0: other, 1: other}
    for members in clusters.values():
        if len(members) != 2:
            continue
        (sa, wa), (sb, wb) = members
        if sa.style_key() != sb.style_key():
            continue
        joins.setdefault(id(sa), {})[wa] = (sb, wb)
        joins.setdefault(id(sb), {})[wb] = (sa, wa)

    chains = []
    visited = set()
    for s in segs:
        if id(s) in visited:
            continue
        # 端(片側が連結されていない区間)から鎖をたどる
        con = joins.get(id(s), {})
        if len(con) == 2:
            continue  # 中間区間。端から始めるときに拾う
        visited.add(id(s))
        if not con:
            continue  # 連結なし
        (start_end,) = con.keys()
        pts = [s.p1, s.p0] if start_end == 0 else [s.p0, s.p1]
        chain = [s]
        cur, cur_end = s, start_end
        while True:
            nxt = joins.get(id(cur), {}).get(cur_end)
            if nxt is None:
                break
            nseg, nwhich = nxt
            if id(nseg) in visited:
                break
            visited.add(id(nseg))
            chain.append(nseg)
            far = 1 - nwhich
            pts.append(nseg.p1 if far == 1 else nseg.p0)
            cur, cur_end = nseg, far
        if len(chain) >= 2:
            chains.append((chain, pts))

    # 鎖を1本のパスにして角を丸める
    replacements = {}  # seg id -> new path string ('' なら削除)
    for chain, pts in chains:
        d = [f"M{pts[0][0]:.2f},{pts[0][1]:.2f}"]
        for k in range(1, len(pts) - 1):
            prev, corner, nxt = pts[k - 1], pts[k], pts[k + 1]
            lin = dist(prev, corner)
            lout = dist(corner, nxt)
            r = min(CORNER_R, lin / 2, lout / 2)
            vin = ((corner[0] - prev[0]) / lin, (corner[1] - prev[1]) / lin)
            vout = ((nxt[0] - corner[0]) / lout, (nxt[1] - corner[1]) / lout)
            a = (corner[0] - vin[0] * r, corner[1] - vin[1] * r)
            b = (corner[0] + vout[0] * r, corner[1] + vout[1] * r)
            d.append(f"L{a[0]:.2f},{a[1]:.2f}")
            d.append(f"Q{corner[0]:.2f},{corner[1]:.2f} {b[0]:.2f},{b[1]:.2f}")
        d.append(f"L{pts[-1][0]:.2f},{pts[-1][1]:.2f}")
        first = chain[0]
        merged = (
            f'<path fill="none"{first.attrs_pre}d="{" ".join(d)}"'
            f'{first.attrs_post} stroke-linecap="round" stroke-linejoin="round"/>'
        )
        replacements[id(first)] = merged
        for s in chain[1:]:
            replacements[id(s)] = ""

    # 出力を組み立てる（スナップ済み座標・結合・丸い線端を反映）
    out = []
    last = 0
    seg_by_gid = {s.gid: s for s in segs}
    for gi, g in enumerate(groups):
        out.append(svg[last:g.start()])
        text = g.group(0)
        s = seg_by_gid.get(gi)
        if s is not None:
            m = PATH.search(text)
            if id(s) in replacements:
                text = text[:m.start()] + replacements[id(s)] + text[m.end():]
            else:
                d = f"M{s.p0[0]:.2f},{s.p0[1]:.2f} L{s.p1[0]:.2f},{s.p1[1]:.2f}"
                newpath = (
                    f'<path fill="none"{m.group(1)}d="{d}"{m.group(3)}'
                    f' stroke-linecap="round"/>'
                )
                text = text[:m.start()] + newpath + text[m.end():]
        out.append(text)
        last = g.end()
    out.append(svg[last:])
    sys.stdout.write("".join(out))


if __name__ == "__main__":
    main()
