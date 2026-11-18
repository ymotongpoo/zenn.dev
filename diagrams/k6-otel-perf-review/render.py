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
# 2. 20261118-closed-vs-open (3章: 次のリクエストをいつ送るかの違い)
# ---------------------------------------------------------------------------
def build_closed_vs_open() -> Scene:
    s=Scene(920,360)
    s.text(0,12,'閉じたモデル',size=18,weight=700,color='yellow')
    s.text(150,12,'constant-vus',font='mono',size=15,color='n2')
    for x,label in [(0,'リクエストを送る'),(330,'応答が返る')]:
        s.box(x,40,250,56,label,stroke='yellow',size=17)
    s.arrow(256,68,324,68)
    s.route([[455,101],[455,133],[125,133],[125,101]],stroke='yellow',head=10)
    s.text(620,63,'VUごとに応答を待つ',size=16,weight=600,color='yellow')
    s.text(620,88,'遅くなると、送る頻度も下がる',size=14.5,color='n1')
    s.line(0,158,920,158,stroke='n4')
    s.text(0,185,'開いたモデル',size=18,weight=700,color='lightblue')
    s.text(150,185,'constant-arrival-rate',font='mono',size=15,color='n2')
    for x,w,label in [(0,250,'反復の開始時刻が来る'),(330,250,'使えるVUを確保する'),(680,240,'リクエストを送る')]:
        s.box(x,211,w,56,label,stroke='lightblue',size=16)
    s.arrow(256,239,324,239)
    s.arrow(586,239,674,239)
    s.text(630,218,'確保できる',size=14,color='n2',anchor='middle')
    s.line(10,301,240,301,stroke='lightblue')
    for x in range(10,241,46): s.line(x,294,x,308,stroke='lightblue')
    s.text(0,333,'応答と無関係に、一定間隔で予定',size=14,color='n1')
    s.arrow(455,272,455,305,stroke='pink',dash=[6,5],head=9)
    s.text(474,291,'確保できない',size=14.5,color='pink')
    s.box(330,310,250,50,[dict(text='dropped_iterations',font='mono',size=15.5,color='pink',weight=600),dict(text='反復を開始せず、件数に数える',size=14,color='n1')],stroke='pink',row_gap=21)
    return s


# ---------------------------------------------------------------------------
# 3. 20261118-request-path (7章: 1件のリクエストが通る区間とスパン)
# ---------------------------------------------------------------------------
def build_request_path() -> Scene:
    s=Scene(920,310)
    s.rect(0,0,920,310,stroke='n2',radius=14,role='frame')
    s.rich_text(18,25,[[dict(text='catalog-api',font='mono',size=16,weight=600),dict(text=' のサーバースパン',font='heading',size=16,weight=600)]])
    s.text(18,49,'GET /items/{id}',font='mono',size=14.5,color='n2')
    s.rect(478,64,424,228,stroke='n2',radius=12,role='frame')
    s.text(492,86,'クライアントスパン',size=16,weight=600)
    s.text(492,108,'HTTP GET',font='mono',size=14.5,color='n2')
    s.rect(492,121,396,157,stroke='n2',radius=10,role='frame')
    s.rich_text(506,143,[[dict(text='inventory',font='mono',size=15.5,weight=600),dict(text=' のサーバースパン',size=15.5,weight=600)]])
    s.text(506,165,'GET /stock/{id}',font='mono',size=14.5,color='n2')
    y=185; h=72; cy=y+h/2
    s.box(18,y,192,h,[[dict(text='catalog-api',font='mono',size=14.5,weight=600),dict(text='内の処理',size=15,weight=600)],dict(text='約5ms・スパンなし',size=14.5)],fill='n3',stroke='n3',row_gap=23)
    s.box(244,y,204,h,[dict(text='空きを待つ',size=17,weight=700),dict(text='wait for backend slot',font='mono',size=14.5,weight=600)],fill='orange',stroke='orange',row_gap=24)
    s.line(244,y-10,244,y+h+12,stroke='orange',width=2.5)
    s.line(448,y-10,448,y+h+12,stroke='orange',width=2.5)
    s.text(244,289,'始まり：空きを要求',size=14.5,weight=600,color='orange-80')
    s.text(448,159,'終わり：空きを得た',size=14.5,weight=600,color='orange-80',anchor='end')
    s.box(506,y,166,h,[dict(text='処理枠の空きを待つ',size=15,weight=600),dict(text='スパンなし',size=14.5)],fill='n3',stroke='n3',row_gap=23)
    s.box(704,y,170,h,[dict(text='在庫を調べる',size=15,weight=600),dict(text='lookup stock',font='mono',size=14.5),dict(text='約50ms',size=14,color='n2')],row_gap=20)
    for x1,x2 in [(215,239),(453,473),(677,699)]: s.arrow(x1,cy,x2,cy,head=8)
    return s


# ---------------------------------------------------------------------------
# 4. 20261118-retest-flow (9章: 変更を評価する手順)
# ---------------------------------------------------------------------------
def build_retest_flow() -> Scene:
    s=Scene(920,152)
    steps=[(0,166,'仮説を立てる','測る区間を決める','yellow'),(190,154,'計装を足す','その区間だけ','blue'),(368,140,'変更する','1つずつ','purple'),(532,166,'再テストする','同じ負荷と条件で','purple'),(722,198,'記録を残す','コードと設定に紐付けて','green')]
    for i,(x,w,a,b,c) in enumerate(steps):
        s.card_band(x,8,w,80,a,b,band=c,title_size=16,sub_size=14)
        if i<4: s.arrow(x+w+4,48,steps[i+1][0]-(10 if i==3 else 4),48,head=8)
    s.rect(717,3,208,90,stroke='orange',width=2.8,radius=13,role='frame')
    s.route([[821,98],[821,145],[83,145],[83,94]],stroke='orange',width=2.4,head=10)
    s.text(460,126,'記録を次の仮説に使う',anchor='middle',size=15,weight=600,color='orange-80')
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
