#!/usr/bin/env python3
"""矢印が「無駄に長い」図を機械的に見つける。

`dot -Tjson` の出力（ノードの座標・サイズ、辺のベジェ制御点列）を解析し、
各辺の実際の描画長を、その辺が実質的につないでいる「実ノード」（見えない
中継点=`shape=point, style=invis` の類ではない、内容のあるノード）のサイズと
比較する。描画長が実ノードサイズの `--ratio` 倍（既定1.5）を超える辺を警告する。

`layout=neato` で `pos="x,y!"` を手で置く図によくある失敗——中継用の透明な
点ノードの座標を、隣接ノードの実際の大きさと無関係な「きりのいい数値」で
決めてしまい、結果として素の直線区間が不必要に長くなる——を検出するために作った。
`layout=dot` の自動配置（`nodesep`/`ranksep`）はノードサイズに応じて間隔を
決めるためこの失敗は起きにくいが、`splines=ortho` 起因の妙に長い迂回なども
このチェックで一緒に拾える。

これは助言のためのチェックであり、自動修正はしない。書き出したPNGの
目視確認の前段として使う。

**誤検知がある。** ループバックの矢印や、離れたノード同士を意図的につなぐ
参照線（例: 図全体を回り込むフィードバック線、遠く離れた2点を直接結ぶ禁止線）は、
近くの小さなノードを基準にすると簡単に閾値を超える。これは失敗ではなく意図した
配置なので、警告が出ても機械的に間隔を詰めようとせず、まず目視で「本当に
不必要に長いか」を判断すること。

使い方:
    python3 check_gaps.py diagrams/**/*.dot
    python3 check_gaps.py --ratio 1.5 diagrams/some.dot
"""

import argparse
import json
import math
import subprocess
import sys

WAYPOINT_MAX_PT = 5.0  # このpt数以下の幅・高さの invis ノードを「見えない中継点」とみなす
IN_TO_PT = 72.0


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
    """辺の `pos` 文字列（例: 'e,92.4,44.79 92.4,173.11 ...'）から
    幾何学的に正しい順序の頂点列を返す。"""
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
    pts = ([start] if start else []) + ctrl + ([end] if end else [])
    return pts


def path_length(pts):
    total = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        total += math.hypot(x1 - x0, y1 - y0)
    return total


def is_waypoint(node):
    style = node.get("style") or ""
    w_pt = float(node.get("width", 0)) * IN_TO_PT
    h_pt = float(node.get("height", 0)) * IN_TO_PT
    return "invis" in style and max(w_pt, h_pt) <= WAYPOINT_MAX_PT


def node_dim(node, vertical):
    h = float(node.get("height", 0)) * IN_TO_PT
    w = float(node.get("width", 0)) * IN_TO_PT
    return h if vertical else w


def nearest_real_size(gvid, exclude_gvid, nodes, adjacency, vertical, max_hops=6):
    """gvid から exclude_gvid 方向を除いて中継点をたどり、最初に見つかった
    実ノードのサイズ（進行方向に応じて高さ or 幅）を返す。見つからなければ None。"""
    seen = {gvid, exclude_gvid}
    frontier = [gvid]
    for _ in range(max_hops):
        next_frontier = []
        for cur in frontier:
            for nbr in adjacency.get(cur, []):
                if nbr in seen:
                    continue
                node = nodes[nbr]
                if not is_waypoint(node):
                    return node_dim(node, vertical)
                seen.add(nbr)
                next_frontier.append(nbr)
        frontier = next_frontier
        if not frontier:
            break
    return None


def check_file(path, ratio):
    data = run_dot_json(path)
    if data is None:
        return 0
    nodes = {}
    for obj in data.get("objects", []):
        gvid = obj.get("_gvid")
        if gvid is None or "pos" not in obj:
            continue
        nodes[gvid] = obj

    adjacency = {}
    edges = []
    for e in data.get("edges", []):
        tail, head, pos = e.get("tail"), e.get("head"), e.get("pos")
        if tail not in nodes or head not in nodes or not pos:
            continue
        adjacency.setdefault(tail, []).append(head)
        adjacency.setdefault(head, []).append(tail)
        edges.append((tail, head, pos))

    warnings = 0
    for tail, head, pos in edges:
        pts = parse_pos_points(pos)
        if len(pts) < 2:
            continue
        length = path_length(pts)
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        vertical = abs(y1 - y0) >= abs(x1 - x0)

        tail_node, head_node = nodes[tail], nodes[head]
        refs = []
        for gvid, node, other in ((tail, tail_node, head), (head, head_node, tail)):
            if is_waypoint(node):
                r = nearest_real_size(gvid, other, nodes, adjacency, vertical)
            else:
                r = node_dim(node, vertical)
            if r:
                refs.append(r)
        if not refs:
            continue
        reference = max(refs)
        if reference <= 0:
            continue
        if length > ratio * reference:
            tail_name = tail_node.get("name", tail)
            head_name = head_node.get("name", head)
            print(
                f"  [{path}] {tail_name} -> {head_name}: "
                f"長さ {length:.0f}pt は参照サイズ {reference:.0f}pt の "
                f"{length / reference:.1f}倍（閾値 {ratio}倍）"
            )
            warnings += 1
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help=".dot ファイル（複数可）")
    parser.add_argument("--ratio", type=float, default=1.5, help="警告する長さの倍率（既定1.5）")
    args = parser.parse_args()

    total = 0
    for path in args.files:
        total += check_file(path, args.ratio)

    if total == 0:
        print("矢印が無駄に長い箇所は見つかりませんでした。")
    else:
        print(f"\n{total} 件の警告。書き出したPNGを目視確認する前に、ノードの配置間隔を見直してください。")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
