#!/usr/bin/env python3
"""pick_layout: 1枚の .dot を dot と ELK の両方でレイアウトして測り、良い方を選ぶ。

「どちらが良いか」を主観で決めずに済むよう、同じ指標で両者を採点する。
指標は両エンジンの**レイアウト結果**（座標）から直接取る。最終SVGを
パースして比べると、後処理の有無の差が混ざって公平に比べられない。

  crossings   辺の交差数。図の読みにくさに最も直結する
  bends       折れ角の総数。少ないほど目で追いやすい
  edgelen     辺の総長（図の対角線で正規化）。短いほど関係が近く見える
  aspect      縦横比が目標から外れる度合い。本文は縦長、スライドは横長が要る
  sprawl      占有面積 / ノードの面積合計。余白だらけの図を罰する

使い方:
    python3 pick_layout.py diagrams/x/y.dot            # 1枚の判定と内訳
    python3 pick_layout.py --quiet diagrams/**/*.dot   # 全部の判定だけ
    python3 pick_layout.py --target-aspect 3.3 a.dot   # スライド用（横長）
    python3 pick_layout.py --write-choice a.dot        # .dot に選択を書き込む

終了コード 0。判定は標準出力の1行目に "dot" か "elk" を出す。
"""
import json
import math
import os
import subprocess
import sys
import glob
import re

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dot2elk  # noqa: E402

PT = 72.0

# 重み。crossings を最重視する。読みにくさへの効き方が他と桁違いなため。
W = {
    "crossings": 10.0,
    "bends": 1.0,
    "edgelen": 3.0,
    "aspect": 4.0,
    "sprawl": 2.0,
    # ラベルの破綻は規範違反なので交差と同格に重くする。配置が綺麗でも
    # ラベルが枠線に乗る図は採らない。
    "labels": 10.0,
}

# 本文に入れる図の目標縦横比。本文幅は環境によって700px程度しかないので、
# 横長よりやや縦長を良しとする。スライド用は --target-aspect 3.3 を渡す。
TARGET_ASPECT = 1.3


def seg_intersect(p1, p2, p3, p4):
    """2本の線分が交差するか（端点の共有は交差と数えない）。"""
    def cross(o, a, b):
        return ((a[0] - o[0]) * (b[1] - o[1])
                - (a[1] - o[1]) * (b[0] - o[0]))

    for a in (p1, p2):
        for b in (p3, p4):
            if abs(a[0] - b[0]) < 0.5 and abs(a[1] - b[1]) < 0.5:
                return False
    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def count_crossings(polylines):
    """辺どうしの交差数。同じ辺の内部は数えない。"""
    segs = []
    for i, pts in enumerate(polylines):
        for k in range(len(pts) - 1):
            segs.append((i, pts[k], pts[k + 1]))
    n = 0
    for i in range(len(segs)):
        ei, a1, a2 = segs[i]
        for k in range(i + 1, len(segs)):
            ek, b1, b2 = segs[k]
            if ei == ek:
                continue
            if seg_intersect(a1, a2, b1, b2):
                n += 1
    return n


def count_bends(polylines, tol=2.0):
    """折れ角の総数。ほぼ一直線の頂点は数えない。"""
    n = 0
    for pts in polylines:
        for i in range(1, len(pts) - 1):
            x0, y0 = pts[i - 1]
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            v1 = (x1 - x0, y1 - y0)
            v2 = (x2 - x1, y2 - y1)
            l1 = math.hypot(*v1)
            l2 = math.hypot(*v2)
            if l1 < tol or l2 < tol:
                continue
            cosang = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
            if cosang < 0.995:      # 約5度以上曲がっていれば折れ
                n += 1
    return n


def total_len(polylines):
    s = 0.0
    for pts in polylines:
        for i in range(len(pts) - 1):
            s += math.hypot(pts[i + 1][0] - pts[i][0],
                            pts[i + 1][1] - pts[i][1])
    return s


def label_penalty(polylines, node_boxes, cluster_frames, labels, bbox):
    """辺ラベルが置けるかを罰点にする。

    配置の綺麗さ（交差・折れ）だけで engine を選ぶと、ラベルが枠線に乗る図や
    枠の外へ出る図を「良い」と判定してしまう。規範（矢印の描き方3.）は
    ラベルのオーバーレイを禁じているので、破綻の数を明示的に数える。

    数えるもの:
      枠跨ぎ   ラベルの矩形がクラスタの枠線と交差する
      枠外     ラベルの矩形が図の外接矩形から出る
      誤帰属   自分の辺より他の辺のほうが近い
    """
    if not labels:
        return 0.0
    x0, y0, x1, y1 = bbox
    pen = 0

    for own_idx, (lx, ly, lw, lh) in labels:
        l = (lx - lw / 2, ly - lh / 2, lx + lw / 2, ly + lh / 2)

        # クラスタの枠線を跨いでいないか（4辺の線分と交差判定）
        for cx0, cy0, cx1, cy1 in cluster_frames:
            edges4 = [((cx0, cy0), (cx1, cy0)), ((cx1, cy0), (cx1, cy1)),
                      ((cx1, cy1), (cx0, cy1)), ((cx0, cy1), (cx0, cy0))]
            for a, b in edges4:
                if _seg_rect_hit(a, b, l):
                    pen += 1
                    break

        # 図の外接矩形から出ていないか
        if l[0] < x0 - 1 or l[2] > x1 + 1 or l[1] < y0 - 1 or l[3] > y1 + 1:
            pen += 1

        # 自分の辺がいちばん近いか
        if 0 <= own_idx < len(polylines):
            dmine = _dist_to_poly((lx, ly), polylines[own_idx])
            for k, pts in enumerate(polylines):
                if k == own_idx:
                    continue
                if _dist_to_poly((lx, ly), pts) < dmine - 1.0:
                    pen += 1
                    break

        # 無関係なノードの矩形に乗っていないか
        for nb in node_boxes:
            if (l[0] < nb[2] and l[2] > nb[0]
                    and l[1] < nb[3] and l[3] > nb[1]):
                pen += 1
                break

        # 辺の線がラベルの矩形の内側を通っていないか。自分の辺を含めて
        # 数える——ELK は経路を決めた後にラベルを置くので「自分の辺の
        # 近く」は正常だが、線がラベルの上を通れば文字は読めなくなる。
        # これを数えないと、縦の矢印に横から文字が乗る図（線がラベルを
        # 縦に貫く形）が罰点0で ELK 側の勝ちと判定される。
        for pts in polylines:
            hit = False
            for i in range(len(pts) - 1):
                if _seg_rect_hit(pts[i], pts[i + 1], l):
                    hit = True
                    break
            if hit:
                pen += 1
                break

    return float(pen)


def _seg_rect_hit(a, b, rect):
    """線分が矩形と交差するか（矩形の内側を通る場合も含む）。

    範囲の重なりだけで判定すると、線分の延長線上にあるだけの矩形まで
    「当たり」にしてしまう。軸平行な線分（クラスタの枠の辺、直交配線の
    直線区間）は、走っている軸の範囲と垂直な軸の座標が矩形に入るかで
    判定する。斜めの区間（角丸の曲線部分など）は、その上を細かく刻んで
    矩形の内側に入る点があるかを見る——ここを False で捨てていた頃は、
    折れ角の近くに置かれたラベルへの被りを取りこぼしていた。
    """
    rx0, ry0, rx1, ry1 = rect
    ax, ay = a
    bx, by = b
    if abs(ay - by) < 0.01:                 # 水平な辺
        if not (ry0 <= ay <= ry1):
            return False
        return max(ax, bx) >= rx0 and min(ax, bx) <= rx1
    if abs(ax - bx) < 0.01:                 # 垂直な辺
        if not (rx0 <= ax <= rx1):
            return False
        return max(ay, by) >= ry0 and min(ay, by) <= ry1
    for t in [i / 16.0 for i in range(17)]:
        px, py = ax + (bx - ax) * t, ay + (by - ay) * t
        if rx0 <= px <= rx1 and ry0 <= py <= ry1:
            return True
    return False


def _dist_to_poly(p, pts):
    best = float("inf")
    for i in range(len(pts) - 1):
        best = min(best, _dist_to_seg(p, pts[i], pts[i + 1]))
    return best


def _dist_to_seg(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def measure(polylines, node_boxes, bbox, target_aspect,
            cluster_frames=(), labels=()):
    """共通の指標を返す。値はすべて「小さいほど良い」向きに揃える。"""
    x0, y0, x1, y1 = bbox
    w, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    diag = math.hypot(w, h)
    node_area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in node_boxes) or 1.0

    aspect = w / h
    # 目標比からのずれを対数で測る（2倍広い と 2倍狭い を同じ罰にする）
    aspect_pen = abs(math.log(aspect / target_aspect))

    return {
        "crossings": float(count_crossings(polylines)),
        "bends": count_bends(polylines) / max(len(polylines), 1),
        "edgelen": total_len(polylines) / diag,
        "aspect": aspect_pen,
        "sprawl": (w * h) / node_area,
        "labels": label_penalty(polylines, node_boxes, cluster_frames,
                                labels, bbox),
        "_w": w, "_h": h,
    }


def score(m):
    return sum(W[k] * m[k] for k in W)


def layout_dot(path):
    """dot のレイアウト結果から指標の材料を取る。"""
    j = json.loads(subprocess.run(["dot", "-Tjson", path],
                                  capture_output=True, text=True,
                                  check=True).stdout)
    boxes = []
    for o in j["objects"]:
        if not (o.get("pos") and o.get("width")):
            continue
        cx, cy = map(float, o["pos"].split(","))
        w = float(o["width"]) * PT
        h = float(o["height"]) * PT
        boxes.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))

    frames = []
    for o in j["objects"]:
        if o.get("name", "").startswith("cluster_") and o.get("bb"):
            frames.append(tuple(map(float, o["bb"].split(","))))

    polys = []
    for e in j.get("edges", []):
        pts = [tuple(p) for op in e.get("_draw_", [])
               if op.get("points") for p in op["points"]]
        if len(pts) >= 2:
            polys.append(pts)

    # 辺ラベルの位置と大きさ。dot -Tjson の _ldraw_/_hldraw_/_tldraw_ に
    # 描画済みのテキストが入っている（width は dot が実測した文字幅）。
    # align は "l"/"c"/"r" で、pt がその基準点になる。中心に直して扱う。
    labels = []
    idx = 0
    for e in j.get("edges", []):
        pts = [tuple(p) for op in e.get("_draw_", [])
               if op.get("points") for p in op["points"]]
        own = idx if len(pts) >= 2 else -1
        if len(pts) >= 2:
            idx += 1
        fs = 11.0
        for grp in ("_ldraw_", "_hldraw_", "_tldraw_"):
            for op in e.get(grp, []):
                if op.get("op") == "F":
                    fs = float(op.get("size", 11) or 11)
                elif op.get("op") == "T":
                    px, py = op["pt"]
                    w = float(op.get("width", 0) or 0)
                    al = op.get("align", "c")
                    if al == "l":
                        px += w / 2
                    elif al == "r":
                        px -= w / 2
                    labels.append((own, (px, py, w, fs * 1.25)))

    if j.get("bb"):
        bx = tuple(map(float, j["bb"].split(",")))
    else:
        xs = [v for b in boxes for v in (b[0], b[2])] or [0, 1]
        ys = [v for b in boxes for v in (b[1], b[3])] or [0, 1]
        bx = (min(xs), min(ys), max(xs), max(ys))
    return polys, boxes, bx, j, frames, labels


def layout_elk(path, j):
    """ELK のレイアウト結果から指標の材料を取る。"""
    svg = subprocess.run(["dot", "-Tsvg", path],
                         capture_output=True, text=True, check=True).stdout
    clabel_h = 0.0
    for c in j["objects"]:
        if c.get("name", "").startswith("cluster_") and c.get("lheight"):
            clabel_h = max(clabel_h, float(c["lheight"]) * PT)
    clabel_h = clabel_h or 22.0

    direction = {"TB": "DOWN", "LR": "RIGHT", "BT": "UP",
                 "RL": "LEFT"}.get(j.get("rankdir", "TB"), "DOWN")
    opts = {
        "direction": direction,
        "nodesep": int(float(j.get("nodesep", 0.45)) * PT),
        "ranksep": int(float(j.get("ranksep", 0.7)) * PT),
        "edgenode": 24, "edgeedge": 16,
        "cluster_pad": 16, "cluster_label_h": clabel_h + 10,
    }
    graph, clusters, nodes = dot2elk.build_elk_graph(j, opts)
    res = dot2elk.elk_layout(graph, HERE)
    pos, cboxes, edges = dot2elk.flatten(res)

    boxes = [(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
             for cx, cy, w, h in pos.values()]
    polys = [pts for _, pts in edges if len(pts) >= 2]
    frames = [(x, y, x + w, y + h) for x, y, w, h in cboxes.values()]

    # ELK 側でラベルが実際にどこへ置かれるかを、dot2elk と同じ規則で求める。
    # dot2elk.py が経路の中点の脇へ置くので、その位置で評価する。
    by_gvid = {o["_gvid"]: o for o in j["objects"]}
    spans = dot2elk.edge_label_spans(svg)
    labels = []
    for i, (eid, pts) in enumerate(edges):
        gi = int(eid[1:]) if eid[1:].isdigit() else -1
        if gi < 0 or gi >= len(j.get("edges", [])):
            continue
        e = j["edges"][gi]
        key = by_gvid[e["tail"]]["name"] + "->" + by_gvid[e["head"]]["name"]
        lab = spans.get(key)
        if not lab or len(pts) < 2:
            continue
        (ax, ay), (ux, uy) = dot2elk.label_anchor_on_path(pts)
        nx, ny = -uy, ux
        off = dot2elk.LABEL_OFFSET
        if abs(uy) > abs(ux):
            tx, ty = ax + (off if nx >= 0 else -off), ay
        else:
            tx, ty = ax + nx * off, ay + ny * off
        labels.append((i, (tx, ty, lab["w"], lab["h"])))

    xs = [v for b in boxes for v in (b[0], b[2])]
    ys = [v for b in boxes for v in (b[1], b[3])]
    for x0, y0, x1, y1 in frames:
        xs += [x0, x1]
        ys += [y0, y1]
    for pts in polys:
        for x, y in pts:
            xs.append(x)
            ys.append(y)
    bx = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 1, 1)
    return polys, boxes, bx, frames, labels


def has_flat_edge(j):
    """rank=same のメンバー間に辺があるか（ELK では組めない図）。"""
    same = [set(o["nodes"]) for o in j["objects"]
            if o.get("rank") == "same" and o.get("nodes")]
    for e in j.get("edges", []):
        for grp in same:
            if e["tail"] in grp and e["head"] in grp:
                return True
    return False


def uses_neato(path):
    src = open(path, encoding="utf-8", errors="replace").read()
    return bool(re.search(r'layout\s*=\s*"?neato"?', src))


def decide(path, target_aspect=TARGET_ASPECT, quiet=False):
    polys_d, boxes_d, bbox_d, j, frames_d, labels_d = layout_dot(path)

    # ELK が構造的に使えない図は測らずに dot に決める
    if has_flat_edge(j):
        return "dot", "rank=same 内に辺がある（ELK は同一層内の辺を扱えない）", None
    if uses_neato(path):
        return "dot", "layout=neato の絶対座標指定（ELK は座標を上書きする）", None
    if not polys_d:
        return "dot", "辺がない図（配置の優劣が出ない。後処理を通す dot でよい）", None

    md = measure(polys_d, boxes_d, bbox_d, target_aspect,
                 frames_d, labels_d)
    try:
        polys_e, boxes_e, bbox_e, frames_e, labels_e = layout_elk(path, j)
    except Exception as exc:
        return "dot", f"ELK が失敗した: {str(exc)[:80]}", None
    me = measure(polys_e, boxes_e, bbox_e, target_aspect,
                 frames_e, labels_e)

    sd, se = score(md), score(me)
    # 差がわずかなら dot を採る。engine を変える手間と、後処理パイプライン
    # （xlabel の押し出し、平行辺の分離）が使える利点のぶん、dot に下駄を履かせる。
    margin = 0.08 * max(sd, se, 1.0)
    winner = "elk" if se < sd - margin else "dot"
    reason = f"score dot={sd:.1f} elk={se:.1f}"
    return winner, reason, (md, me, sd, se)


def fmt_detail(md, me, sd, se):
    rows = [f"{'指標':<11}{'dot':>10}{'elk':>10}{'重み':>7}"]
    for k in W:
        rows.append(f"{k:<10}{md[k]:>10.2f}{me[k]:>10.2f}{W[k]:>7.1f}")
    rows.append(f"{'size':<10}{md['_w']:>5.0f}x{md['_h']:<4.0f}"
                f"{me['_w']:>6.0f}x{me['_h']:<4.0f}")
    rows.append(f"{'SCORE':<10}{sd:>10.1f}{se:>10.1f}")
    return "\n".join(rows)


def main():
    args = [a for a in sys.argv[1:]]
    quiet = "--quiet" in args
    write_choice = "--write-choice" in args
    target = TARGET_ASPECT
    if "--target-aspect" in args:
        i = args.index("--target-aspect")
        target = float(args[i + 1])
        del args[i:i + 2]
    args = [a for a in args
            if a not in ("--quiet", "--write-choice")]

    paths = []
    for a in args:
        paths.extend(glob.glob(a, recursive=True))
    paths = sorted(set(p for p in paths if p.endswith(".dot")))
    if not paths:
        print(__doc__)
        return 1

    tally = {"dot": 0, "elk": 0}
    for p in paths:
        try:
            winner, reason, detail = decide(p, target, quiet)
        except Exception as exc:
            print(f"ERROR {p}: {str(exc)[:100]}", file=sys.stderr)
            tally["dot"] += 1
            continue
        tally[winner] += 1
        if len(paths) == 1:
            print(winner)
            print(f"# {reason}")
            if detail:
                print(fmt_detail(*detail))
        elif not quiet:
            print(f"{winner:4} {os.path.basename(p):<46} {reason}")
        else:
            print(f"{winner}\t{p}")

        if write_choice and winner == "elk":
            src = open(p, encoding="utf-8").read()
            if "render-layout:" not in src:
                open(p, "w", encoding="utf-8").write(
                    "// render-layout: elk\n" + src)

    if len(paths) > 1:
        print(f"\n--- dot={tally['dot']} elk={tally['elk']} "
              f"(target aspect {target})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
