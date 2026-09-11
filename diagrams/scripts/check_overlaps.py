#!/usr/bin/env python3
"""矢印が無関係な図形を貫通していないか、矢印の先端が別の図形に埋もれて
いないか、ラベルが矢印・図形に近すぎないかを機械的に見つける。

`dot -Tjson` の出力（ノードの座標・サイズ、辺の折れ線・xlabel座標）を解析し、
以下の3種類を advisory（自動修正なし）で警告する:

  1. 経路の貫通（PASS-THROUGH）: エッジの折れ線が、自分の始点・終点ではない
     ノードの矩形の内側を通っている。
  2. 先端の埋没（ARROWHEAD-HIDDEN）: エッジの矢じり（終点）が、到達先ノード
     ではない別のノードの矩形の内側にある。
  3. ラベルの誤帰属（LABEL-MISATTRIBUTED）: ラベルの位置から、自分が説明して
     いる辺よりも別の辺のほうが近い。重なっていなくても、読者は近いほうの辺の
     説明だと読むため、これは実害のある欠陥である。
  4. ラベルの近接（LABEL-TOO-CLOSE）: ラベル座標が、自分以外の
     エッジの経路や無関係なノードの矩形に近すぎる。
  5. ラベルの枠跨ぎ（LABEL-ON-CLUSTER-FRAME）: ラベルの文字範囲がクラスタの
     枠線を跨いでいる。

検査するラベルは `xlabel`（`xlp`）だけでなく、`label`/`headlabel`/`taillabel`
（`_ldraw_`/`_hldraw_`/`_tldraw_` の T 命令）も含む。

これは助言のためのチェックであり、自動修正はしない。書き出したPNGの
目視確認の前段として使う。誤検知がある: 図形どうしが意図して隣接している
場合や、クラスタの枠線ぎりぎりを通ることが避けられない場合は無視してよい。
長い複数行ラベルの幅は dot の報告値と実描画がずれるため、枠跨ぎの判定が
過剰に出ることがある。

使い方:
    python3 check_overlaps.py diagrams/**/*.dot
    python3 check_overlaps.py --margin 10 diagrams/some.dot
"""

import argparse
import json
import subprocess
import sys

IN_TO_PT = 72.0
SAMPLES_PER_SEGMENT = 24
# 横書き1行の高さの半分（fontsize 11〜13 を想定）。横の枠線への張り出し量。
# dot は横の枠線から 9pt 程度離してラベルを置くことがあり、それは視覚的に
# 問題ないので、実際に文字が枠を跨ぐ範囲（中心が 6pt 以内）だけを検出する。
LABEL_LINE_HALF_HEIGHT = 6.0
SELF_CROSS_THRESHOLD = 15.0


def run_dot_json(path):
    proc = subprocess.run(["dot", "-Tjson", path], capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  [skip] dot -Tjson が失敗しました: {path}\n{proc.stderr.strip()}", file=sys.stderr)
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"  [skip] JSON解析に失敗しました: {path} ({e})", file=sys.stderr)
        return None


def parse_pos_points(pos):
    """辺の `pos` 文字列から幾何学的に正しい順序の頂点列を返す。"""
    start = None
    end = None
    ctrl = []
    for token in pos.split():
        parts = token.split(",")
        if len(parts) == 3 and parts[0] in ("s", "e"):
            pt = (float(parts[1]), float(parts[2]))
            if parts[0] == "s":
                start = pt
            else:
                end = pt
        elif len(parts) == 2:
            ctrl.append((float(parts[0]), float(parts[1])))
    return ([start] if start else []) + ctrl + ([end] if end else [])


def node_bbox(node, shrink=1.5):
    """ノードの矩形 (x0, y0, x1, y1)。境界そのものへの接触を誤検知しないよう
    わずかに内側へ縮める。"""
    cx, cy = node["_pos"]
    w = float(node.get("width", 0)) * IN_TO_PT
    h = float(node.get("height", 0)) * IN_TO_PT
    return (cx - w / 2 + shrink, cy - h / 2 + shrink, cx + w / 2 - shrink, cy + h / 2 - shrink)


def point_in_bbox(pt, bbox):
    x, y = pt
    x0, y0, x1, y1 = bbox
    return x0 <= x <= x1 and y0 <= y <= y1


def sample_segment(p0, p1, n=SAMPLES_PER_SEGMENT):
    x0, y0 = p0
    x1, y1 = p1
    for i in range(n + 1):
        t = i / n
        yield (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)


def path_hits_bbox(path, bbox):
    for p0, p1 in zip(path, path[1:]):
        for pt in sample_segment(p0, p1):
            if point_in_bbox(pt, bbox):
                return True
    return False


def internal_travel_from_start(path, bbox):
    """path[0]から、bboxの外に出るまでの経路長。ポート指定でノードの内部
    （テーブルの途中の行など）から出た辺が、自分自身の他の行を横切って
    外縁まで進む距離を測る。"""
    if not point_in_bbox(path[0], bbox):
        return 0.0
    total = 0.0
    prev = path[0]
    for p0, p1 in zip(path, path[1:]):
        for pt in list(sample_segment(p0, p1))[1:]:
            if not point_in_bbox(pt, bbox):
                return total
            total += ((pt[0] - prev[0]) ** 2 + (pt[1] - prev[1]) ** 2) ** 0.5
            prev = pt
    return total


def is_waypoint(node):
    style = node.get("style") or ""
    w_pt = float(node.get("width", 0)) * IN_TO_PT
    h_pt = float(node.get("height", 0)) * IN_TO_PT
    return "invis" in style or max(w_pt, h_pt) <= 5.0


def dist_point_to_segment(pt, p0, p1):
    px, py = pt
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)))
    cx, cy = x0 + t * dx, y0 + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def dist_point_to_path(pt, path):
    return min(dist_point_to_segment(pt, p0, p1) for p0, p1 in zip(path, path[1:]))


def dist_point_to_bbox(pt, bbox):
    x, y = pt
    x0, y0, x1, y1 = bbox
    dx = max(x0 - x, 0, x - x1)
    dy = max(y0 - y, 0, y - y1)
    return (dx * dx + dy * dy) ** 0.5


def check_file(path, margin):
    data = run_dot_json(path)
    if data is None:
        return 0

    nodes = {}
    for obj in data.get("objects", []):
        gvid = obj.get("_gvid")
        pos = obj.get("pos")
        if gvid is None or not pos or "," not in pos:
            continue
        try:
            x, y = (float(v) for v in pos.split(","))
        except ValueError:
            continue
        obj["_pos"] = (x, y)
        nodes[gvid] = obj

    # クラスタの枠線。`check_overlaps.py` は当初これを見ていなかったため、
    # 枠に乗り上げたラベルを検出できなかった。枠を4辺の線分として扱う。
    cluster_frames = []
    for obj in data.get("objects", []):
        bb = obj.get("bb")
        if not bb or "," not in bb:
            continue
        try:
            x0, y0, x1, y1 = (float(v) for v in bb.split(","))
        except ValueError:
            continue
        cluster_frames.append((obj.get("name", "cluster"),
                               [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]))

    edges = []
    for e in data.get("edges", []):
        tail, head, pos = e.get("tail"), e.get("head"), e.get("pos")
        if tail not in nodes or head not in nodes or not pos:
            continue
        epath = parse_pos_points(pos)
        if len(epath) < 2:
            continue
        # xlabel は `xlp`、head/tail ラベルは `_hldraw_`/`_tldraw_` の T 命令に
        # 描画座標が入る。後者を拾わないと headlabel の近接を見落とす。
        extra_labels = []
        for grp in ("_hldraw_", "_tldraw_", "_ldraw_"):
            for op in e.get(grp, []):
                if op.get("op") == "T" and op.get("pt"):
                    extra_labels.append((op["pt"][0], op["pt"][1],
                                         float(op.get("width") or 0.0)))
        edges.append({"tail": tail, "head": head, "path": epath,
                      "xlp": e.get("xlp"), "labels": extra_labels})

    warnings = 0

    # 1. 経路の貫通 / 2. 先端の埋没
    for e in edges:
        tail_name = nodes[e["tail"]].get("name", e["tail"])
        head_name = nodes[e["head"]].get("name", e["head"])
        arrow_tip = e["path"][-1]
        for gvid, node in nodes.items():
            if gvid in (e["tail"], e["head"]) or is_waypoint(node):
                continue
            bbox = node_bbox(node)
            if point_in_bbox(arrow_tip, bbox):
                print(f"  [{path}] {tail_name} -> {head_name}: "
                      f"矢印の先端が '{node.get('name')}' の中に埋もれている（ARROWHEAD-HIDDEN）")
                warnings += 1
            elif path_hits_bbox(e["path"], bbox):
                print(f"  [{path}] {tail_name} -> {head_name}: "
                      f"経路が '{node.get('name')}' を貫通している（PASS-THROUGH）")
                warnings += 1

        # 内部ポート（テーブルの途中の行など）から出た辺が、
        # 同じノードの他の行を横切って外縁まで進んでいないか
        tail_bbox = node_bbox(nodes[e["tail"]], shrink=0.0)
        head_bbox = node_bbox(nodes[e["head"]], shrink=0.0)
        t = internal_travel_from_start(e["path"], tail_bbox)
        if t > SELF_CROSS_THRESHOLD:
            print(f"  [{path}] {tail_name} -> {head_name}: "
                  f"始点側が自ノード内部を{t:.0f}pt横切ってから出ている"
                  f"（SELF-PASS-THROUGH、ポートの向きを確認）")
            warnings += 1
        h = internal_travel_from_start(list(reversed(e["path"])), head_bbox)
        if h > SELF_CROSS_THRESHOLD:
            print(f"  [{path}] {tail_name} -> {head_name}: "
                  f"終点側が自ノード内部を{h:.0f}pt横切ってから到達している"
                  f"（SELF-PASS-THROUGH、ポートの向きを確認）")
            warnings += 1

    # 3. ラベルの近接
    for i, e in enumerate(edges):
        tail_name = nodes[e["tail"]].get("name", e["tail"])
        head_name = nodes[e["head"]].get("name", e["head"])

        # 検査する点: xlabel の座標と、head/tail ラベルの描画座標
        points = []
        if e["xlp"]:
            try:
                lx, ly = (float(v) for v in e["xlp"].split(","))
                points.append((lx, ly, 0.0))
            except ValueError:
                pass
        points.extend(e["labels"])

        for lx, ly, lw in points:
            own = dist_point_to_path((lx, ly), e["path"])
            # 3a. 他の辺のほうが自分の辺より近い → どの辺の説明か誤読される
            for j, other in enumerate(edges):
                if i == j:
                    continue
                d = dist_point_to_path((lx, ly), other["path"])
                other_tail = nodes[other["tail"]].get("name", other["tail"])
                other_head = nodes[other["head"]].get("name", other["head"])
                if d < own:
                    print(f"  [{path}] {tail_name} -> {head_name} のラベルは "
                          f"{other_tail} -> {other_head} のほうが近い"
                          f"（自分{own:.0f}pt / 他{d:.0f}pt, LABEL-MISATTRIBUTED）")
                    warnings += 1
                elif d < margin:
                    print(f"  [{path}] {tail_name} -> {head_name} のラベルが "
                          f"{other_tail} -> {other_head} の経路に近すぎる（{d:.0f}pt, LABEL-TOO-CLOSE）")
                    warnings += 1
            # 3b. 無関係なノードの矩形に近すぎる
            for gvid, node in nodes.items():
                if gvid in (e["tail"], e["head"]) or is_waypoint(node):
                    continue
                d = dist_point_to_bbox((lx, ly), node_bbox(node))
                if d < margin:
                    print(f"  [{path}] {tail_name} -> {head_name} のラベルが "
                          f"'{node.get('name')}' に近すぎる（{d:.0f}pt, LABEL-TOO-CLOSE）")
                    warnings += 1
            # 3c. クラスタの枠線に乗り上げている。文字は横書きなので、縦の枠線
            # には半幅、横の枠線には行高の半分しか張り出さない。さらに、枠の
            # 「反対の軸では内側にある」ことも条件にする（y範囲内にあるだけで
            # 横方向には枠の外、という位置を枠に乗っていると誤判定しないため）。
            for cname, frame in cluster_frames:
                x0, y0 = frame[0]
                x1, y1 = frame[2]
                half_w = lw / 2
                # 縦の枠線: ラベルの文字範囲が枠線を跨ぐか
                crosses_left = abs(lx - x0) < half_w and y0 <= ly <= y1
                crosses_right = abs(lx - x1) < half_w and y0 <= ly <= y1
                # 横の枠線: ラベルの行が枠線を跨ぐか
                crosses_bottom = (abs(ly - y0) < LABEL_LINE_HALF_HEIGHT
                                  and x0 <= lx <= x1)
                crosses_top = (abs(ly - y1) < LABEL_LINE_HALF_HEIGHT
                               and x0 <= lx <= x1)
                if crosses_left or crosses_right or crosses_bottom or crosses_top:
                    which = ("左" if crosses_left else "右" if crosses_right
                             else "下" if crosses_bottom else "上")
                    print(f"  [{path}] {tail_name} -> {head_name} のラベルが "
                          f"クラスタ '{cname}' の{which}の枠線を跨いでいる"
                          f"（文字半幅{half_w:.0f}pt, LABEL-ON-CLUSTER-FRAME）")
                    warnings += 1

    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help=".dot ファイル（複数可）")
    parser.add_argument("--margin", type=float, default=12.0, help="ラベル近接の許容距離pt（既定12）")
    args = parser.parse_args()

    total = 0
    for path in args.files:
        total += check_file(path, args.margin)

    if total == 0:
        print("矢印の貫通・先端の埋没・ラベルの近接は見つかりませんでした。")
    else:
        print(f"\n{total} 件の警告。書き出したPNGを目視確認する前に、"
              f"ポート指定・nodesep/ranksepを見直してください。")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
