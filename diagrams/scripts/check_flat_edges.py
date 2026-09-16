#!/usr/bin/env python3
"""rank=same のメンバー間に辺がある図（ELK layered で表現できない図）を数える。

ELK layered は同一層内の辺（Graphviz の flat edge）をサポートしないため、
このパターンを持つ図は ELK では意図どおりに組めない。
"""
import json, subprocess, sys, glob


def analyze(path):
    try:
        j = json.loads(subprocess.run(["dot", "-Tjson", path],
                                      capture_output=True, text=True,
                                      timeout=60).stdout)
    except Exception as e:
        return ("ERROR", str(e)[:60], 0)

    objs = j.get("objects", [])
    nodes = {o["_gvid"] for o in objs if o.get("pos") and o.get("width")}
    same = [set(o["nodes"]) for o in objs
            if o.get("rank") == "same" and o.get("nodes")]
    if not same:
        return ("no-rank-same", "", 0)

    flat = 0
    for e in j.get("edges", []):
        for grp in same:
            if e["tail"] in grp and e["head"] in grp:
                flat += 1
                break
    if flat:
        return ("FLAT-EDGE", f"{flat} flat edge(s)", flat)
    return ("rank-same-only", "", 0)


def main():
    paths = []
    for a in sys.argv[1:]:
        paths.extend(glob.glob(a, recursive=True))
    if not paths:
        print("usage: check_flat_edges.py 'diagrams/**/*.dot'")
        return 1
    tally = {}
    rows = []
    for p in sorted(set(paths)):
        kind, note, n = analyze(p)
        tally[kind] = tally.get(kind, 0) + 1
        if kind in ("FLAT-EDGE", "ERROR"):
            rows.append((kind, p, note))
    for kind, p, note in rows:
        print(f"{kind}: {p}  {note}")
    print("\n--- summary ---")
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"{v:5d}  {k}")
    print(f"{sum(tally.values()):5d}  total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
