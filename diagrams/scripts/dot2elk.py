#!/usr/bin/env python3
"""dot2elk: Graphviz の .dot を ELK でレイアウトして SVG を書き出す。

Graphviz は「ラベルの組版」にだけ使う（HTML-like ラベル、フォント切り替え、
左揃え、テーブルはすべて dot にやらせ、SVG のスパンをそのまま再利用する）。
ノードの配置と辺の直交配線は ELK（elkjs）が決める。枠・塗り・辺・矢じりは自前で描く。
"""
import json, subprocess, sys, os, re, math, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PT = 72.0
TEE_GAP = 14.0       # 進入禁止記号の中心を到達先の枠から離す距離
LABEL_OFFSET = 10.0  # 横に走る辺で、ラベルを経路から離す距離
LABEL_GAP = 5.0      # 縦に走る辺で、ラベルの端と経路のあいだに残す余白


def run(cmd, inp=None):
    p = subprocess.run(cmd, input=inp, text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd}: {p.stderr}")
    return p.stdout


def parse_dot(path):
    src = open(path).read()
    j = json.loads(run(["dot", "-Tjson", path]))
    svg = run(["dot", "-Tsvg", path])
    return src, j, svg


def extract_groups(svg, cls):
    """<g class="node"> などを (title, inner_xml) の dict で返す。"""
    out = {}
    for m in re.finditer(
        r'<g id="[^"]*" class="' + cls + r'">\s*<title>(.*?)</title>(.*?)</g>',
        svg, re.S):
        out[m.group(1)] = m.group(2)
    return out


def unescape_title(t):
    """dot のSVGの <title> は &#45;&gt; などでエスケープされている。"""
    return (t.replace("&#45;&gt;", "->").replace("&#45;", "-")
             .replace("&gt;", ">").replace("&lt;", "<")
             .replace("&quot;", '"').replace("&amp;", "&"))


def edge_label_spans(svg):
    """辺ごとのラベル（<text>）を dot のSVGから取る。

    dot は辺ラベル（label/xlabel/headlabel/taillabel）も実フォント・
    実座標のスパンとして組んでくれるので、ノードと同じ方法で移植できる。
    返す座標は「そのラベル群の中心」で、ELK の経路上に置き直すのに使う。
    """
    out = {}
    for title, inner in extract_groups(svg, "edge").items():
        texts = re.findall(r'<text.*?</text>', inner, re.S)
        if not texts:
            continue
        xs, ys = [], []
        for m in re.finditer(r'<text[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"',
                             inner):
            xs.append(float(m.group(1)))
            ys.append(float(m.group(2)))
        if not xs:
            continue
        # ラベルの実寸。dot は文字幅を持っていないので、最も長い行の
        # 文字数とフォントサイズから見積もる。全角は2文字ぶんで数える。
        fs = 11.0
        fm = re.search(r'font-size="([\d.]+)"', inner)
        if fm:
            fs = float(fm.group(1))
        maxw = 0.0
        nlines = 0
        for t in texts:
            body = re.sub(r"<[^>]+>", "", t)
            units = sum(2 if ord(ch) > 0x2000 else 1 for ch in body)
            maxw = max(maxw, units * fs * 0.5)
            nlines += 1
        out[unescape_title(title)] = {
            "texts": "".join(texts),
            "cx": (min(xs) + max(xs)) / 2,
            "cy": (min(ys) + max(ys)) / 2,
            "w": maxw,
            "h": max(nlines, 1) * fs * 1.25,
            # dot の text-anchor が middle なら中心、start なら左端が基準
            "anchor_mid": 'text-anchor="middle"' in inner,
        }
    return out


def edge_dash_styles(svg):
    """辺ごとの stroke-dasharray を dot のSVGから取る。

    `.dot` の `style=dashed` を自前で「6,5」などと決め打ちすると
    dot の出力と見た目が変わる。dot が実際に使った値を引き継ぐ。
    """
    out = {}
    for title, inner in extract_groups(svg, "edge").items():
        m = re.search(r'<path[^>]*stroke-dasharray="([^"]+)"', inner)
        if m:
            out[unescape_title(title)] = m.group(1)
    return out


def text_extent(inner):
    """グループ内の <text> の x 範囲と行数から、ラベルの実寸を推定する。"""
    xs, ys = [], []
    for m in re.finditer(r'<text[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', inner):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))
    if not xs:
        return 0.0, 0.0
    return max(xs) - min(xs), max(ys) - min(ys)


def build_elk_graph(j, opts):
    """Graphviz JSON から ELK のグラフ記述を組む。"""
    objs = j["objects"]
    by_gvid = {o["_gvid"]: o for o in objs}

    # cluster_* という名前の subgraph だけを容器として扱う。
    clusters = [o for o in objs
                if o.get("name", "").startswith("cluster_") and o.get("bb")]
    cluster_members = {}
    for c in clusters:
        for nid in c.get("nodes", []):
            cluster_members[nid] = c["name"]

    nodes = [o for o in objs if o.get("pos") and o.get("width")]

    # dot が解決したランク・順序を ELK へ「座標ヒント」として渡す。
    #
    # dot のランク付け（ネットワークシンプレックス）は rank=same・minlen・
    # constraint=false・newrank をすべて織り込んだ結果をノードの座標に出す。
    # ELK の INTERACTIVE 層決定／順序決定はノードの x/y だけを見て層と
    # 段内順序を決めるので、dot の結果をそのまま引き継げる。
    # ELK が担当するのは「実際の座標と直交配線」だけになる。
    #
    # partitioning は使えない。ELK の partition は「層の前後関係」の制約で
    # あって「同じ層に置く」ではないため、rank=same のノード間に辺があると
    # （run -> score -> find）同じ層にならず縦に積まれてしまう。
    axis = 1 if j.get("rankdir", "TB") in ("TB", "BT") else 0
    flip_y = j.get("rankdir", "TB") == "TB"
    gy_max = max(float(o["pos"].split(",")[1]) for o in nodes) if nodes else 0.0

    def mknode(o):
        gx, gy = map(float, o["pos"].split(","))
        n = {
            "id": o["name"],
            "width": round(float(o["width"]) * PT, 2),
            "height": round(float(o["height"]) * PT, 2),
            # dot が決めた配置を「ヒント」として渡す。ELK の INTERACTIVE
            # 層決定・順序決定はこの座標だけを見て層と段内順序を決めるので、
            # dot のランク付け（rank=same, minlen, constraint=false, newrank を
            # すべて織り込んだ結果）がそのまま保たれる。
            # dot は y-up なので TB のときは y を反転する。
            "x": round(gx, 2),
            "y": round((gy_max - gy) if flip_y else gy, 2),
        }
        return n

    children_of = {c["name"]: [] for c in clusters}
    root_children = []
    for o in nodes:
        cid = cluster_members.get(o["_gvid"])
        (children_of[cid] if cid else root_children).append(mknode(o))

    for c in clusters:
        pad_top = opts["cluster_label_h"] + opts["cluster_pad"]
        # タイトルが枠より広いと、ELK は子だけを見て枠幅を決めるためタイトルが
        # はみ出す。dot の lwidth（タイトルの実測幅）を下限として渡す。
        lw = float(c.get("lwidth", 0) or 0) * PT
        min_w = lw + 2 * opts["cluster_pad"]
        root_children.append({
            "id": c["name"],
            "children": children_of[c["name"]],
            "layoutOptions": {
                "elk.padding": f"[top={pad_top},left={opts['cluster_pad']},"
                               f"bottom={opts['cluster_pad']},right={opts['cluster_pad']}]",
                "elk.direction": opts["direction"],
                # 層決定は各階層で指定しないと子に効かない
                "elk.layered.layering.strategy": "INTERACTIVE",
                "elk.layered.crossingMinimization.semiInteractive": "true",
            },
        })

    edges = []
    for i, e in enumerate(j.get("edges", [])):
        edges.append({
            "id": f"e{i}",
            "sources": [by_gvid[e["tail"]]["name"]],
            "targets": [by_gvid[e["head"]]["name"]],
        })

    return {
        "id": "root",
        "layoutOptions": {
            "elk.algorithm": "layered",
            "elk.direction": opts["direction"],
            "elk.edgeRouting": "ORTHOGONAL",
            "elk.hierarchyHandling": "INCLUDE_CHILDREN",
            "elk.layered.spacing.nodeNodeBetweenLayers": str(opts["ranksep"]),
            "elk.spacing.nodeNode": str(opts["nodesep"]),
            "elk.spacing.edgeNode": str(opts["edgenode"]),
            "elk.spacing.edgeEdge": str(opts["edgeedge"]),
            "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
            # dot が決めたランクを座標ヒントから引き継ぐ。
            # 段内順序は semiInteractive（座標を尊重しつつ交差を減らす）。
            # crossingMinimization.strategy=INTERACTIVE は
            # nodePlacement=NETWORK_SIMPLEX と併用すると
            # "NEdge must have a source and target NNode specified" で落ちる。
            "elk.layered.layering.strategy": "INTERACTIVE",
            "elk.layered.crossingMinimization.semiInteractive": "true",
        },
        "children": root_children,
        "edges": edges,
    }, clusters, nodes


ELK_JS = r"""
const ELK = require('elkjs');
let buf = '';
process.stdin.on('data', d => buf += d);
process.stdin.on('end', async () => {
  const elk = new ELK();
  try {
    const res = await elk.layout(JSON.parse(buf));
    process.stdout.write(JSON.stringify(res));
  } catch (e) {
    process.stderr.write(String(e && e.stack || e));
    process.exit(1);
  }
});
"""


def ensure_elkjs(nodedir):
    """elkjs が require できるか確かめ、無ければ入れる（初回だけ）。

    node の解決は親ディレクトリを辿るので、リポジトリのルートに
    node_modules があればそこで足りる。ディレクトリの有無で判定すると
    「入っているのに入っていない」と誤判定するため、実際に require する。
    """
    probe = subprocess.run(
        ["node", "-e", "require.resolve('elkjs')"],
        cwd=nodedir, capture_output=True, text=True)
    if probe.returncode == 0:
        return
    print("elkjs が見つからないので npm install します（初回のみ）...",
          file=sys.stderr)
    p = subprocess.run(["npm", "install", "--silent", "--no-fund",
                        "--no-audit", "elkjs"],
                       cwd=nodedir, capture_output=True, text=True)
    probe = subprocess.run(
        ["node", "-e", "require.resolve('elkjs')"],
        cwd=nodedir, capture_output=True, text=True)
    if probe.returncode != 0:
        raise RuntimeError(
            "elkjs の導入に失敗した。手動で入れること:\n"
            f"  cd {nodedir} && npm install elkjs\n" + (p.stderr or "")[-500:])


def elk_layout(graph, nodedir):
    ensure_elkjs(nodedir)
    js = os.path.join(nodedir, "_elk_run.js")
    open(js, "w").write(ELK_JS)
    p = subprocess.run(["node", js], input=json.dumps(graph), text=True,
                       capture_output=True, cwd=nodedir)
    if p.returncode != 0:
        raise RuntimeError("elk failed: " + p.stderr)
    return json.loads(p.stdout)


def flatten(res):
    """ELK の結果を絶対座標に展開する。

    辺は階層のどこに置かれていても root の edges 配列に入り、`container` で
    どのノードの座標系かが示される。だから辺は「格納場所」ではなく
    container の絶対原点でオフセットしなければならない。
    """
    pos, boxes, origin = {}, {}, {"root": (0.0, 0.0)}
    raw_edges = []

    def walk(node, ox, oy):
        for ch in node.get("children", []):
            x, y = ox + ch.get("x", 0), oy + ch.get("y", 0)
            w, h = ch.get("width", 0), ch.get("height", 0)
            if ch.get("children"):
                boxes[ch["id"]] = (x, y, w, h)
                origin[ch["id"]] = (x, y)
                walk(ch, x, y)
            else:
                pos[ch["id"]] = (x + w / 2, y + h / 2, w, h)
        raw_edges.extend(node.get("edges", []))

    walk(res, 0, 0)

    edges = []
    for e in raw_edges:
        ox, oy = origin.get(e.get("container", "root"), (0.0, 0.0))
        for s in e.get("sections", []):
            pts = [(s["startPoint"]["x"] + ox, s["startPoint"]["y"] + oy)]
            for b in s.get("bendPoints", []):
                pts.append((b["x"] + ox, b["y"] + oy))
            pts.append((s["endPoint"]["x"] + ox, s["endPoint"]["y"] + oy))
            edges.append((e["id"], pts))
    return pos, boxes, edges


def rounded_path(pts, r=8.0):
    """折れ線を、折れ角だけ角丸にした path の d 属性にする。"""
    if len(pts) < 2:
        return ""
    d = [f"M{pts[0][0]:.2f},{pts[0][1]:.2f}"]
    for i in range(1, len(pts) - 1):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        d1 = math.hypot(x1 - x0, y1 - y0)
        d2 = math.hypot(x2 - x1, y2 - y1)
        rr = min(r, d1 / 2, d2 / 2)
        if rr < 0.5:
            d.append(f"L{x1:.2f},{y1:.2f}")
            continue
        ax = x1 - (x1 - x0) / d1 * rr
        ay = y1 - (y1 - y0) / d1 * rr
        bx = x1 + (x2 - x1) / d2 * rr
        by = y1 + (y2 - y1) / d2 * rr
        d.append(f"L{ax:.2f},{ay:.2f}")
        d.append(f"Q{x1:.2f},{y1:.2f} {bx:.2f},{by:.2f}")
    d.append(f"L{pts[-1][0]:.2f},{pts[-1][1]:.2f}")
    return " ".join(d)


def arrowhead(pts, size=9.0, color="#343434"):
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    ang = math.atan2(y1 - y0, x1 - x0)
    w = size * 0.42
    p = [(x1, y1),
         (x1 - size * math.cos(ang) + w * math.sin(ang),
          y1 - size * math.sin(ang) - w * math.cos(ang)),
         (x1 - size * math.cos(ang) - w * math.sin(ang),
          y1 - size * math.sin(ang) + w * math.cos(ang))]
    pstr = " ".join(f"{a:.2f},{b:.2f}" for a, b in p)
    return f'<polygon points="{pstr}" fill="{color}" stroke="none"/>'


def no_entry(pts, r=7.0, gap=14.0, color="#343434"):
    """arrowhead=tee を「進入禁止」記号（丸＋右下がり45度の斜線）で描く。

    dot の tee は進行方向に垂直な横棒1本で、三角の矢じりを期待する読者には
    「矢印の先が壊れている」と読まれる。丸に斜線なら「禁止・不可」と伝わる。
    斜線は経路の向きに関わらず常に右下がり45度で統一する（回転させると
    同じ記号だと認識しにくくなる）。
    """
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    L = math.hypot(x1 - x0, y1 - y0) or 1.0
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    cx, cy = x1 - ux * gap, y1 - uy * gap
    d = r / math.sqrt(2)
    return (f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="none" '
            f'stroke="{color}" stroke-width="1.8"/>'
            f'<line x1="{cx - d:.2f}" y1="{cy - d:.2f}" '
            f'x2="{cx + d:.2f}" y2="{cy + d:.2f}" '
            f'stroke="{color}" stroke-width="1.8"/>'), (cx, cy, r)


def label_anchor_on_path(pts):
    """ラベルを置く点と、経路のその地点での向きを返す。

    経路の全長の中点に置く。`splines=ortho` の dot は中央ラベルを捨てるので
    xlabel に逃がす必要があったが、ELK では経路が確定しているので中点に
    置ける（規範「ラベルは自分の辺がいちばん近い位置に置く」を構造的に満たす）。
    """
    if len(pts) < 2:
        return pts[0], (1.0, 0.0)
    segs = []
    total = 0.0
    for i in range(len(pts) - 1):
        d = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        segs.append(d)
        total += d
    half = total / 2
    acc = 0.0
    for i, d in enumerate(segs):
        if acc + d >= half:
            t = (half - acc) / d if d else 0.0
            x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t
            y = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t
            ux = (pts[i + 1][0] - pts[i][0]) / (d or 1)
            uy = (pts[i + 1][1] - pts[i][1]) / (d or 1)
            return (x, y), (ux, uy)
        acc += d
    return pts[-1], (1.0, 0.0)


def shorten_tip(pts, d):
    """最終区間を d だけ手前で止める（矢じりの底に線の先端を合わせる）。"""
    if len(pts) < 2 or d <= 0:
        return pts
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    L = math.hypot(x1 - x0, y1 - y0)
    if L <= d + 0.5:
        return pts[:-1] + [(x0, y0)]
    t = (L - d) / L
    out = list(pts)
    out[-1] = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
    return out


def clip_to_border(pts, box, which, gap=0.0):
    """端点をノードの矩形の縁に合わせる。

    ELK は辺の端点をノードの境界に置くが、角丸ノードでは角の近くで
    枠の内側に入る。また矢じりの長さぶんノードに食い込むため、
    矢じりの底が縁にちょうど来るよう終点を手前へ引く。
    """
    if not box or len(pts) < 2:
        return pts
    cx, cy, w, h = box
    x0, y0 = cx - w / 2, cy - h / 2
    x1, y1 = cx + w / 2, cy + h / 2
    i, j = (-1, -2) if which == "head" else (0, 1)
    px, py = pts[i]
    qx, qy = pts[j]
    dx, dy = px - qx, py - qy
    if abs(dx) < 0.01 and abs(dy) < 0.01:
        return pts
    # 縁に乗せる（進入方向の軸だけを動かす。直交配線なので片方は0）
    if abs(dx) > abs(dy):
        nx = x1 + gap if dx < 0 else x0 - gap
        ny = py
    else:
        nx = px
        ny = y1 + gap if dy < 0 else y0 - gap
    out = list(pts)
    out[i] = (nx, ny)
    return out


def main():
    if len(sys.argv) < 3:
        print("usage: dot2elk.py in.dot out.svg [--dir DOWN|RIGHT]")
        return 1
    inp, outp = sys.argv[1], sys.argv[2]
    direction = "DOWN"
    if "--dir" in sys.argv:
        direction = sys.argv[sys.argv.index("--dir") + 1]

    src, j, svg = parse_dot(inp)
    if "rankdir" in j and "--dir" not in sys.argv:
        direction = {"TB": "DOWN", "LR": "RIGHT",
                     "BT": "UP", "RL": "LEFT"}.get(j["rankdir"], "DOWN")

    node_g = extract_groups(svg, "node")
    clus_g = extract_groups(svg, "cluster")

    # クラスタのタイトルの高さを dot の lheight から取る（実測値）
    clabel_h = 0.0
    for c in j["objects"]:
        if c.get("name", "").startswith("cluster_") and c.get("lheight"):
            clabel_h = max(clabel_h, float(c["lheight"]) * PT)
    if clabel_h == 0.0:
        clabel_h = 22.0

    opts = {
        "direction": direction,
        "nodesep": int(float(j.get("nodesep", 0.45)) * PT),
        "ranksep": int(float(j.get("ranksep", 0.7)) * PT),
        "edgenode": 24, "edgeedge": 16,
        "cluster_pad": 16, "cluster_label_h": clabel_h + 10,
    }

    graph, clusters, nodes = build_elk_graph(j, opts)
    res = elk_layout(graph, HERE)
    pos, boxes, edges = flatten(res)

    # 元の dot の座標（y-up）と ELK の座標（y-down）を突き合わせる
    gv_center = {}
    for o in nodes:
        gx, gy = map(float, o["pos"].split(","))
        gv_center[o["name"]] = (gx, gy)

    # 辺の端点をノードの縁へクリップする
    by_gvid = {o["_gvid"]: o for o in j["objects"]}
    etail, ehead = {}, {}
    for i, e in enumerate(j.get("edges", [])):
        etail[f"e{i}"] = by_gvid[e["tail"]]["name"]
        ehead[f"e{i}"] = by_gvid[e["head"]]["name"]
    clipped = []
    for eid, pts in edges:
        p = clip_to_border(pts, pos.get(ehead.get(eid)), "head")
        p = clip_to_border(p, pos.get(etail.get(eid)), "tail")
        clipped.append((eid, p))
    edges = clipped

    # クラスタ枠は、タイトルが枠より広い場合に右へ伸びる。外接矩形の計算は
    # 伸ばした後の幅で行う必要があるので、先に確定させておく。
    cinfo = {c["name"]: c for c in clusters}
    frames = {}
    for cid, (x, y, w, h) in boxes.items():
        c = cinfo[cid]
        need = float(c.get("lwidth", 0) or 0) * PT + 2 * opts["cluster_pad"]
        frames[cid] = (x, y, max(w, need), h)

    # 辺のラベルは、経路と枠が確定してから位置を決める。外接矩形の計算に
    # 入れないとラベルが描画領域の外へ出て切れるので、先に全部求めておく。
    elabels = edge_label_spans(svg)
    edashes = edge_dash_styles(svg)
    ecolor, estyle, ehead_sym, ekey = {}, {}, {}, {}
    for i, e in enumerate(j.get("edges", [])):
        ecolor[f"e{i}"] = e.get("color", "#343434") or "#343434"
        estyle[f"e{i}"] = e.get("style") or ""
        ehead_sym[f"e{i}"] = e.get("arrowhead") or "normal"
        ekey[f"e{i}"] = (by_gvid[e["tail"]]["name"] + "->"
                         + by_gvid[e["head"]]["name"])

    placed_labels = []      # (eid, texts, dx, dy, 矩形)
    for eid, pts in edges:
        lab = elabels.get(ekey.get(eid, ""))
        if not lab or len(pts) < 2:
            continue
        (ax, ay), (ux, uy) = label_anchor_on_path(pts)
        nx, ny = -uy, ux
        if abs(uy) > abs(ux):
            # 縦に走る辺。ラベルは左右へ出す（上下だと行が経路に乗る）。
            # 距離は「ラベルの半幅 + 余白」で決める。固定値だと短いラベルが
            # 宙に浮き、長いラベルは経路に触る。
            d = lab["w"] / 2 + LABEL_GAP
            tx, ty = ax + (d if nx >= 0 else -d), ay
        else:
            tx, ty = ax + nx * LABEL_OFFSET, ay + ny * LABEL_OFFSET
        rect = (tx - lab["w"] / 2, ty - lab["h"] / 2,
                tx + lab["w"] / 2, ty + lab["h"] / 2)
        placed_labels.append((eid, lab, tx - lab["cx"], ty - lab["cy"], rect))

    pad = float(j.get("pad", 0.25)) * PT
    xs, ys = [], []
    for x, y, w, h in frames.values():
        xs += [x, x + w]; ys += [y, y + h]
    for cx, cy, w, h in pos.values():
        xs += [cx - w / 2, cx + w / 2]; ys += [cy - h / 2, cy + h / 2]
    for _, pts in edges:
        for x, y in pts:
            xs.append(x); ys.append(y)
    for _, _, _, _, r in placed_labels:
        xs += [r[0], r[2]]; ys += [r[1], r[3]]
    X0 = min(xs) if xs else 0
    Y0 = min(ys) if ys else 0
    W = (max(xs) if xs else 0)
    H = (max(ys) if ys else 0)
    # ラベルが左や上へ出た場合は原点が負になる。viewBox をそこまで広げる。
    ox = min(0.0, X0)
    oy = min(0.0, Y0)

    bg = j.get("bgcolor", "white")
    vx = ox - pad
    vy = oy - pad
    vw = (W - ox) + 2 * pad
    vh = (H - oy) + 2 * pad
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{vw:.0f}pt" height="{vh:.0f}pt" '
           f'viewBox="{vx:.2f} {vy:.2f} {vw:.2f} {vh:.2f}">',
           f'<rect x="{vx:.2f}" y="{vy:.2f}" width="{vw:.2f}" '
           f'height="{vh:.2f}" fill="{bg}"/>']

    # クラスタ枠（塗り → 枠線 → タイトル）
    for cid, (x, y, w, h) in frames.items():
        c = cinfo[cid]
        fill = c.get("bgcolor", "none") or "none"
        stroke = c.get("color", "#4A4A4A") or "#4A4A4A"
        pw = c.get("penwidth", "1.6")
        out.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
                   f'rx="10" ry="10" fill="{fill}" stroke="{stroke}" stroke-width="{pw}"/>')
        inner = clus_g.get(cid, "")
        tm = re.search(r'<text[^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"', inner)
        if tm:
            # タイトルは枠の左上へ（labeljust="l" 相当）。
            # ベースラインは枠上端 + ラベル高 なので、上端から見て
            # ちょうどラベル領域に収まる。
            tx = x + opts["cluster_pad"]
            ty = y + clabel_h
            texts = "".join(re.findall(r'<text.*?</text>', inner, re.S))
            dx = tx - float(tm.group(1))
            dy = ty - float(tm.group(2))
            out.append(f'<g transform="translate({dx:.2f},{dy:.2f})">{texts}</g>')

    # 辺
    label_layer = [
        f'<g transform="translate({dx:.2f},{dy:.2f})">{lab["texts"]}</g>'
        for _, lab, dx, dy, _ in placed_labels]
    for eid, pts in edges:
        col = ecolor.get(eid, "#343434")
        # 破線の刻みは dot の出力から引き継ぐ（自前で決め打ちしない）
        da = edashes.get(ekey.get(eid, ""))
        if da is None and "dashed" in estyle.get(eid, ""):
            da = "5,2"
        dash = f' stroke-dasharray="{da}"' if da else ""
        sym = ehead_sym.get(eid, "normal")
        if sym == "tee":
            # 進入禁止記号。線は丸の縁でちょうど止める
            glyph, (cx, cy, r) = no_entry(pts, color=col)
            body = shorten_tip(pts, TEE_GAP + r)
            out.append(f'<path d="{rounded_path(body)}" fill="none" stroke="{col}" '
                       f'stroke-width="1.4" stroke-linecap="round"{dash}/>')
            out.append(glyph)
        elif sym == "odot":
            body = shorten_tip(pts, 12.0)
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
            L = math.hypot(x1 - x0, y1 - y0) or 1.0
            cx = x1 - (x1 - x0) / L * 6.0
            cy = y1 - (y1 - y0) / L * 6.0
            out.append(f'<path d="{rounded_path(body)}" fill="none" stroke="{col}" '
                       f'stroke-width="1.4" stroke-linecap="round"{dash}/>')
            out.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="5" fill="none" '
                       f'stroke="{col}" stroke-width="1.6"/>')
        else:
            # 線は矢じりの底で止め、矢じりが縁にちょうど接するようにする
            body = shorten_tip(pts, 8.0)
            out.append(f'<path d="{rounded_path(body)}" fill="none" stroke="{col}" '
                       f'stroke-width="1.4" stroke-linecap="round"{dash}/>')
            out.append(arrowhead(pts, color=col))


    # ノード（dot が組んだラベル SVG をそのまま平行移動して置く）
    for o in nodes:
        name = o["name"]
        if name not in pos:
            continue
        cx, cy, _, _ = pos[name]
        gx, gy = gv_center[name]
        inner = node_g.get(name, "")
        out.append(f'<g transform="translate({cx - gx:.2f},{cy + gy:.2f})">{inner}</g>')

    # 辺のラベルは最後に置く（辺やノードの線に隠れないように）
    out.extend(label_layer)

    out.append("</svg>")
    open(outp, "w").write("\n".join(out))
    print(f"wrote {outp}  ({W:.0f}x{H:.0f}pt, {len(pos)} nodes, "
          f"{len(boxes)} clusters, {len(edges)} edges, dir={direction})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
