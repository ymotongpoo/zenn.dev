#!/usr/bin/env python3
"""dot2elk の出力を機械検査する。

検査項目:
  CLUSTER-OVERFLOW       ノードがクラスタ枠の外に出ている
  CLUSTER-OVERLAP        クラスタの枠同士が重なっている（タイトルが隠れる）
  NODE-OVERLAP           ノード同士が重なっている
  ARROW-BURIED           矢じりが到達先ノードの内部に埋もれている
  LABEL-ON-CLUSTER-FRAME 辺のラベルがクラスタの枠線に乗っている
  LABEL-ON-NODE          辺のラベルがノードに重なっている
  LABEL-ON-EDGE          辺のラベルが矢印の線に被っている
  OUT-OF-VIEW            描画がviewBoxの外に出ている
"""
import re, sys, glob, math, unicodedata

RE_G = re.compile(r'<g transform="translate\(([-\d.]+),([-\d.]+)\)">(.*?)</g>', re.S)
RE_RECT = re.compile(r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)" rx="10"')
RE_PATH_D = re.compile(r'<path[^>]*\bd="([^"]+)"')
RE_EDGE = re.compile(r'<path d="(M[^"]+)" fill="none"')
RE_POLY = re.compile(r'<polygon points="([^"]+)"')
RE_TEXT = re.compile(r'<text[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"[^>]*font-size="([\d.]+)"[^>]*>(.*?)</text>', re.S)


def text_width(txt, fs):
    """文字列の描画幅をフォントサイズから推定する。

    全角（CJK・全角記号）は1.0em、半角は約0.55emで数える。厳密な組版幅では
    ないが、ラベルが線や枠に被っているかの判定には足りる。過小評価すると
    被りを見逃すので、半角の係数はやや大きめに取っている。
    """
    w = 0.0
    for ch in re.sub(r'<[^>]+>', '', txt):
        w += 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.55
    return w * fs


def seg_point_dist(p, a, b):
    """線分 ab と点 p の距離。"""
    (px, py), (x0, y0), (x1, y1) = p, a, b
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)))
    cx, cy = x0 + t * dx, y0 + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def rect_seg_overlap(lb, a, b):
    """矩形 lb と線分 ab が交差しているか（線分の内側に入っているか）。"""
    x0, y0, x1, y1 = lb
    for t in [i / 24.0 for i in range(25)]:
        px, py = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        if x0 < px < x1 and y0 < py < y1:
            return True
    return False


def bbox_of(dstr, gx, gy):
    xs = [float(v) + gx for v in re.findall(r'([-\d.]+),[-\d.]+', dstr)]
    ys = [float(v) + gy for v in re.findall(r'[-\d.]+,([-\d.]+)', dstr)]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def check(path, margin=1.5):
    s = open(path).read()
    vb = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', s)
    vx, vy, vw, vh = (float(g) for g in vb.groups())

    clusters = [(float(a), float(b), float(a) + float(c), float(b) + float(d))
                for a, b, c, d in RE_RECT.findall(s)]

    nodes = []
    for m in RE_G.finditer(s):
        gx, gy, inner = float(m.group(1)), float(m.group(2)), m.group(3)
        pm = RE_PATH_D.search(inner)
        if not pm:
            continue  # クラスタのタイトル（text だけ）はノードでない
        bb = bbox_of(pm.group(1), gx, gy)
        if bb:
            nodes.append(bb)

    issues = []

    # ノードがクラスタ枠の外に出ていないか（枠に属するかは内包で判定）
    for nb in nodes:
        for cb in clusters:
            # ノードの中心が枠の中にあるなら、その枠に属するとみなす
            ncx, ncy = (nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2
            if cb[0] < ncx < cb[2] and cb[1] < ncy < cb[3]:
                if (nb[0] < cb[0] - margin or nb[2] > cb[2] + margin
                        or nb[1] < cb[1] - margin or nb[3] > cb[3] + margin):
                    issues.append(("CLUSTER-OVERFLOW",
                                   f"node({nb[0]:.0f},{nb[1]:.0f},{nb[2]:.0f},{nb[3]:.0f}) "
                                   f"vs frame({cb[0]:.0f},{cb[1]:.0f},{cb[2]:.0f},{cb[3]:.0f})"))

    # ノード同士の重なり
    for i in range(len(nodes)):
        for k in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[k]
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox > margin and oy > margin:
                issues.append(("NODE-OVERLAP", f"{ox:.0f}x{oy:.0f}pt"))

    # クラスタ同士の重なり。ELK は兄弟のサブグラフの枠が重なる配置を
    # 出すことがあり、そうなると後ろのクラスタのタイトルが前の枠の塗りで
    # 隠れて途中から読めなくなる（ノードは重なっていないので
    # NODE-OVERLAP には出ない）。
    for i in range(len(clusters)):
        for k in range(i + 1, len(clusters)):
            a, b = clusters[i], clusters[k]
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox > margin and oy > margin:
                issues.append(("CLUSTER-OVERLAP", f"{ox:.0f}x{oy:.0f}pt"))

    # 矢じりがノードの内部に埋もれていないか
    for pts in RE_POLY.findall(s):
        p = [tuple(map(float, q.split(","))) for q in pts.split()]
        tip = p[0]
        for nb in nodes:
            if nb[0] + margin < tip[0] < nb[2] - margin and \
               nb[1] + margin < tip[1] < nb[3] - margin:
                issues.append(("ARROW-BURIED", f"tip({tip[0]:.0f},{tip[1]:.0f})"))

    # 辺のラベルが枠線に乗っていないか、ノードに重なっていないか。
    # ノードのラベルは <g> の中に <path> と同居しているので、
    # <path> を持たない <g>（= 辺のラベルとクラスタのタイトル）だけを見る。
    edge_paths = [[tuple(map(float, q.split(",")))
                   for q in re.findall(r'([-\d.]+,[-\d.]+)', d)]
                  for d in RE_EDGE.findall(s)]
    for m in RE_G.finditer(s):
        gx, gy, inner = float(m.group(1)), float(m.group(2)), m.group(3)
        if RE_PATH_D.search(inner):
            continue                      # ノード
        xs, ys, fss, txts = [], [], [], []
        for t in RE_TEXT.finditer(inner):
            xs.append(float(t.group(1)) + gx)
            ys.append(float(t.group(2)) + gy)
            fss.append(float(t.group(3)))
            txts.append(t.group(4))
        if not xs:
            continue
        fs = max(fss)
        anchor_mid = 'text-anchor="middle"' in inner
        # 文字幅を推定して矩形を作る。幅を無視して高さだけで見ていた頃は、
        # 縦の矢印に横から被るラベル（線の左右に文字が乗る形）を
        # 一切検出できなかった。
        wmax = max((text_width(t, f) for t, f in zip(txts, fss)), default=0.0)
        x0 = min(xs) - (wmax / 2 if anchor_mid else 0.0)
        lb = (x0, min(ys) - fs, x0 + wmax, max(ys) + fs * 0.3)
        # クラスタのタイトルは枠の上端に置かれる。辺のラベルではないので
        # 以降の検査すべてから除く（枠線にも自分の枠の線にも必ず接する）。
        if any(abs(lb[1] - cb[1]) < fs * 2.5 and cb[0] <= lb[0] <= cb[2]
               for cb in clusters):
            continue
        for cb in clusters:
            for ey in (cb[1], cb[3]):
                if lb[1] - margin < ey < lb[3] + margin and \
                   cb[0] < lb[2] and cb[2] > lb[0]:
                    issues.append(("LABEL-ON-CLUSTER-FRAME",
                                   f"y={ey:.0f} label({lb[0]:.0f},{lb[1]:.0f})"))
                    break
            for ex in (cb[0], cb[2]):
                if lb[0] - margin < ex < lb[2] + margin and \
                   cb[1] < lb[3] and cb[3] > lb[1]:
                    issues.append(("LABEL-ON-CLUSTER-FRAME",
                                   f"x={ex:.0f} label({lb[0]:.0f},{lb[1]:.0f})"))
                    break
        for nb in nodes:
            # 実害のある重なりだけを数える。文字の外接矩形は行送りを含めて
            # 広めに取ってあるので、少し触れただけで違反にすると誤検出になる。
            # 面積の重なりがラベルの矩形の3割を超えたときだけ違反とする。
            ox = min(lb[2], nb[2]) - max(lb[0], nb[0])
            oy = min(lb[3], nb[3]) - max(lb[1], nb[1])
            if ox <= 0 or oy <= 0:
                continue
            la = max((lb[2] - lb[0]) * (lb[3] - lb[1]), 1.0)
            if (ox * oy) / la > 0.3:
                issues.append(("LABEL-ON-NODE",
                               f"label({lb[0]:.0f},{lb[1]:.0f}) "
                               f"{ox * oy / la:.0%}"))
                break

        # 辺の線に被っていないか。自分の辺か他の辺かは区別しない——
        # どちらでも読みづらさは同じで、ELK は経路確定後にラベルを置くので
        # 「自分の辺の近く」は正常な配置であり、被り（線がラベルの矩形の
        # 内側を通る）だけが問題になる。
        for pts in edge_paths:
            hit = False
            for i in range(len(pts) - 1):
                if rect_seg_overlap(lb, pts[i], pts[i + 1]):
                    hit = True
                    break
            if hit:
                issues.append(("LABEL-ON-EDGE",
                               f"label({lb[0]:.0f},{lb[1]:.0f},"
                               f"{lb[2]:.0f},{lb[3]:.0f})"))
                break

    # viewBox 外
    for nb in nodes:
        if nb[0] < vx - margin or nb[2] > vx + vw + margin or \
           nb[1] < vy - margin or nb[3] > vy + vh + margin:
            issues.append(("OUT-OF-VIEW", f"node({nb[0]:.0f},{nb[1]:.0f})"))

    return issues


def main():
    paths = []
    for a in sys.argv[1:]:
        paths.extend(glob.glob(a, recursive=True))
    tally = {}
    clean = 0
    for p in sorted(set(paths)):
        iss = check(p)
        if not iss:
            clean += 1
            continue
        kinds = sorted({k for k, _ in iss})
        for k in kinds:
            tally[k] = tally.get(k, 0) + 1
        print(f"{p.split('/')[-1]}: " +
              ", ".join(f"{k}x{sum(1 for a, _ in iss if a == k)}" for k in kinds))
    print("\n--- summary ---")
    print(f"{clean:5d}  clean")
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"{v:5d}  files with {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
