#!/usr/bin/env python3
"""k6-otel-perf-review の図定義（book-diagram-svg スキル）。

再生成:
    python3 ~/.agents/skills/book-diagram-svg/scripts/render.py \
      diagrams/k6-otel-perf-review/render.py --out-images images
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_SCRIPTS = Path.home() / ".agents" / "skills" / "book-diagram-svg" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from gf_scene import Scene  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 20261118-demo-topology (2章: サンプルの構成)
# ---------------------------------------------------------------------------
def build_demo_topology() -> Scene:
    s = Scene(920, 258)
    row = [0, 98, 196]
    h = 62
    mid = lambda r: row[r] + h / 2

    node = {"stroke": "n2", "fill": "n4", "width": 1.8, "radius": 10}
    stack = {"stroke": "indigo", "fill": "indigo", "width": 1.8, "radius": 10}

    s.box(0, row[0], 224, h, [
        {"text": "k6", "font": "heading", "size": 17, "weight": 700, "color": "white"},
        {"text": "負荷を生成する", "font": "body", "size": 14.5, "weight": 500, "color": "n2"},
    ], **node, row_gap=23)

    s.box(0, row[1], 224, h, [
        {"text": "catalog-api", "font": "mono", "size": 16.5, "weight": 600, "color": "white"},
        {"text": "同時実行数を制限して呼ぶ", "font": "body", "size": 14.5, "weight": 500, "color": "n2"},
    ], **node, row_gap=23)

    s.box(0, row[2], 224, h, [
        {"text": "inventory", "font": "mono", "size": 16.5, "weight": 600, "color": "white"},
        {"text": "6件ずつ処理する", "font": "body", "size": 14.5, "weight": 500, "color": "n2"},
    ], **node, row_gap=23)

    # 実線: HTTPリクエスト
    s.arrow(112, row[0] + h + 4, 112, row[1] - 4, stroke="n1", width=2, head=10)
    s.arrow(112, row[1] + h + 4, 112, row[2] - 4, stroke="n1", width=2, head=10)

    # テレメトリーの経路（Grafana スタック: indigo の面に白文字）
    s.box(292, row[1], 204, h, [
        {"text": "Grafana Alloy", "font": "heading", "size": 17, "weight": 700, "color": "white"},
        {"text": "テレメトリーを振り分ける", "font": "body", "size": 14.5, "weight": 500, "color": "white"},
    ], **stack, row_gap=23)

    s.box(558, row[0], 154, h, [
        {"text": "Mimir", "font": "heading", "size": 17, "weight": 700, "color": "white"},
        {"text": "メトリクス", "font": "body", "size": 14.5, "weight": 500, "color": "white"},
    ], **stack, row_gap=23)

    s.box(558, row[1], 154, h, [
        {"text": "Tempo", "font": "heading", "size": 17, "weight": 700, "color": "white"},
        {"text": "トレース", "font": "body", "size": 14.5, "weight": 500, "color": "white"},
    ], **stack, row_gap=23)

    s.box(558, row[2], 154, h, [
        {"text": "Loki", "font": "heading", "size": 17, "weight": 700, "color": "white"},
        {"text": "ログ", "font": "body", "size": 14.5, "weight": 500, "color": "white"},
    ], **stack, row_gap=23)

    s.box(764, row[1], 156, h, [
        {"text": "Grafana", "font": "heading", "size": 17, "weight": 700, "color": "white"},
        {"text": "3つを横断して調べる", "font": "body", "size": 14.5, "weight": 500, "color": "white"},
    ], **stack, row_gap=23)

    # 灰色の破線: テレメトリーの流れ
    dash = {"stroke": "n2", "width": 1.6, "dash": [6, 5]}
    s.route([[228, mid(0)], [394, mid(0)], [394, row[1] - 5]], **dash, head=10)
    s.route([[228, mid(1)], [287, mid(1)]], **dash, head=10)
    s.route([[228, mid(2)], [394, mid(2)], [394, row[1] + h + 5]], **dash, head=10)

    s.route([[500, mid(1)], [528, mid(1)], [528, mid(0)], [553, mid(0)]], **dash, head=10)
    s.route([[500, mid(1)], [553, mid(1)]], **dash, head=10)
    s.route([[528, mid(1)], [528, mid(2)], [553, mid(2)]], **dash, head=10)

    s.route([[716, mid(0)], [842, mid(0)], [842, row[1] - 5]], **dash, head=10)
    s.route([[716, mid(1)], [759, mid(1)]], **dash, head=10)
    s.route([[716, mid(2)], [842, mid(2)], [842, row[1] + h + 5]], **dash, head=10)
    return s


# ---------------------------------------------------------------------------
# 2. 20261118-closed-vs-open (3章: 次のリクエストを送る契機の違い)
# ---------------------------------------------------------------------------
def build_closed_vs_open() -> Scene:
    s = Scene(920, 356)

    # 閉じたモデル (yellow)
    s.text(0, 12, "閉じたモデル", font="heading", size=18, weight=700, color="yellow")
    s.text(132, 12, "constant-vus", font="mono", size=15, weight=500, color="n2")

    s.box(0, 36, 212, 56, "前の応答が返る", fill="n4", stroke="yellow", width=2, font="body", size=17, weight=600, color="n1")
    s.arrow(218, 64, 274, 64, stroke="n2", width=2, head=11)
    s.box(280, 36, 248, 56, "次のリクエストを送る", fill="n4", stroke="yellow", width=2, font="body", size=17, weight=600, color="n1")

    s.route([[404, 96], [404, 120], [106, 120], [106, 97]], stroke="yellow", width=1.8, head=10)
    s.text(556, 64, "前の応答が返ってから次を送る", font="body", size=15.5, weight=700, color="yellow")

    # 区切り線
    s.line(0, 148, 920, 148, stroke="n4", width=1.5)

    # 開いたモデル (lightblue) + dropped_iterations (pink 破線)
    s.text(0, 178, "開いたモデル", font="heading", size=18, weight=700, color="lightblue")
    s.text(132, 178, "constant-arrival-rate", font="mono", size=15, weight=500, color="n2")

    s.box(0, 202, 212, 56, "決めた間隔が経つ", fill="n4", stroke="lightblue", width=2, font="body", size=17, weight=600, color="n1")
    s.arrow(218, 230, 274, 230, stroke="n2", width=2, head=11)
    s.box(280, 202, 236, 56, "空いているVUに渡す", fill="n4", stroke="lightblue", width=2, font="body", size=17, weight=600, color="n1")
    s.arrow(522, 230, 578, 230, stroke="n2", width=2, head=11)
    s.box(584, 202, 216, 56, "リクエストを送る", fill="n4", stroke="lightblue", width=2, font="body", size=17, weight=600, color="n1")

    # 一定間隔の目盛り
    for i in range(6):
        s.line(24 + i * 33, 276, 24 + i * 33, 290, stroke="lightblue", width=2)
    s.line(12, 283, 201, 283, stroke="lightblue", width=1.5)
    s.text(0, 309, "応答と関係なく、決めた頻度で送る", font="body", size=14.5, weight=700, color="orange")

    # ピンクの破線: 反復を始められない経路
    s.arrow(398, 262, 398, 293, stroke="pink", width=2, dash=[6, 5], head=10)
    s.text(412, 277, "空いているVUがない", font="body", size=14.5, weight=600, color="pink")
    s.box(280, 298, 236, 58, [
        {"text": "dropped_iterations", "font": "mono", "size": 15.5, "weight": 600, "color": "pink"},
        {"text": "に数える", "font": "body", "size": 14.5, "weight": 500, "color": "n1"},
    ], fill="n4", stroke="pink", width=2, row_gap=22)
    return s


# ---------------------------------------------------------------------------
# 3. 20261118-request-path (7章: 1件のリクエストが通る区間とスパン)
# ---------------------------------------------------------------------------
def build_request_path() -> Scene:
    s = Scene(920, 268)
    y = 134
    h = 78
    m = y + h / 2

    # catalog-api のサーバースパン（外枠）
    s.rect(0, 0, 920, 268, stroke="n2", width=1.8, radius=16, role="frame")
    s.rich_text(20, 25, [[
        {"text": "catalog-api", "font": "mono", "size": 16, "weight": 600, "color": "n1"},
        {"text": " のサーバースパン  ", "font": "heading", "size": 16, "weight": 600, "color": "n1"},
        {"text": "GET /items/{id}", "font": "mono", "size": 14.5, "weight": 500, "color": "n2"},
    ]])

    # クライアントスパン（入れ子1）
    s.rect(480, 48, 422, 192, stroke="n2", width=1.6, radius=14, role="frame")
    s.rich_text(498, 70, [[
        {"text": "クライアントスパン  ", "font": "heading", "size": 15.5, "weight": 600, "color": "n1"},
        {"text": "HTTP GET", "font": "mono", "size": 14.5, "weight": 500, "color": "n2"},
    ]])

    # inventory のサーバースパン（入れ子2）
    s.rect(494, 92, 394, 134, stroke="n2", width=1.6, radius=12, role="frame")
    s.rich_text(512, 113, [[
        {"text": "inventory", "font": "mono", "size": 15.5, "weight": 600, "color": "n1"},
        {"text": " のサーバースパン  ", "font": "heading", "size": 15.5, "weight": 600, "color": "n1"},
        {"text": "GET /stock/{id}", "font": "mono", "size": 14.5, "weight": 500, "color": "n2"},
    ]])

    # 区間1: catalog-api内の処理（スパンなし: n3 灰色）
    s.box(20, y, 190, h, [
        [
            {"text": "catalog-api", "font": "mono", "size": 14.5, "weight": 600, "color": "white"},
            {"text": "内の処理", "font": "body", "size": 15, "weight": 600, "color": "white"},
        ],
        {"text": "約5ms・スパンなし", "font": "body", "size": 14.5, "weight": 500, "color": "white"},
    ], fill="n3", stroke="n3", width=1.6, row_gap=23)

    s.arrow(214, m, 242, m, stroke="n2", width=2, head=9)

    # 区間2: 空きを待つ（7章で足すスパン: orange 焦点）
    s.box(246, y, 200, h, [
        {"text": "空きを待つ", "font": "heading", "size": 16, "weight": 700, "color": "white"},
        {"text": "wait for backend slot", "font": "mono", "size": 14.5, "weight": 600, "color": "white"},
    ], fill="orange", stroke="orange", width=2.2, row_gap=23)

    s.line(246, y - 10, 246, y + h + 10, stroke="orange", width=2.5)
    s.line(446, y - 10, 446, y + h + 10, stroke="orange", width=2.5)
    s.text(246, y + h + 28, "始まり：空きを要求", font="body", size=14.5, weight=600, color="orange", anchor="start")
    s.text(446, y - 26, "終わり：空きを得た", font="body", size=14.5, weight=600, color="orange", anchor="end")

    s.arrow(450, m, 476, m, stroke="n2", width=2, head=9)

    # 区間3: inventory の処理枠の空きを待つ（スパンなし: n3 灰色）
    s.box(508, y, 166, h, [
        {"text": "処理枠の空きを待つ", "font": "body", "size": 15, "weight": 600, "color": "white"},
        {"text": "スパンなし", "font": "body", "size": 14.5, "weight": 500, "color": "white"},
    ], fill="n3", stroke="n3", width=1.6, row_gap=23)

    s.arrow(678, m, 698, m, stroke="n2", width=2, head=9)

    # 区間4: 在庫を調べる (lookup stock)
    s.box(702, y, 172, h, [
        {"text": "在庫を調べる", "font": "body", "size": 15, "weight": 600, "color": "n1"},
        {"text": "lookup stock", "font": "mono", "size": 14.5, "weight": 500, "color": "n1"},
        {"text": "約50ms", "font": "body", "size": 14, "weight": 500, "color": "n2"},
    ], fill="n4", stroke="n1", width=1.8, row_gap=21)
    return s


# ---------------------------------------------------------------------------
# 4. 20261118-retest-flow (9章: 変更を評価する手順)
# ---------------------------------------------------------------------------
def build_retest_flow() -> Scene:
    s = Scene(920, 138)
    steps = [
        ("仮説を立てる", "測る区間を決める", "yellow", 162),
        ("計装を足す", "その区間だけ", "blue", 151),
        ("変更する", "1つずつ", "purple", 139),
        ("再テストする", "同じ負荷と条件で", "purple", 163),
        ("記録を残す", "改善しなかった結果も", "green", 196),
    ]
    gap = 26
    y = 8
    h = 80

    xs: list[int] = []
    cur = 0
    for _, _, _, w in steps:
        xs.append(cur)
        cur += w + gap

    for i, (label, sub, band, w) in enumerate(steps):
        x = xs[i]
        s.card_band(x, y, w, h, label, sub, band=band)
        if i < len(steps) - 1:
            s.arrow(x + w + 4, y + h / 2, xs[i + 1] - 4, y + h / 2, stroke="n2", width=2, head=9)

    last_x = xs[4]
    last_w = steps[4][3]
    s.rect(last_x - 5, y - 5, last_w + 10, h + 10, stroke="orange", width=2.8, radius=13, role="frame")

    from_x = last_x + last_w / 2
    to_x = xs[0] + steps[0][3] / 2
    s.route(
        [[from_x, y + h + 7], [from_x, 128], [to_x, 128], [to_x, y + h + 5]],
        stroke="orange",
        width=2.6,
        head=10,
    )
    return s


DIAGRAMS = {
    "20261118-demo-topology": build_demo_topology,
    "20261118-closed-vs-open": build_closed_vs_open,
    "20261118-request-path": build_request_path,
    "20261118-retest-flow": build_retest_flow,
}


if __name__ == "__main__":
    import render

    sys.exit(render.main([str(Path(__file__).resolve()), *sys.argv[1:]]))
