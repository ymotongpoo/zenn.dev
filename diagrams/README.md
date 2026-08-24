# 記事の図版（Graphviz）

記事中の図はGraphviz（`dot`）のソースで管理し、PNGに書き出して `images/` に置く。
Zennの本文からは `![説明](/images/{名前}.png)` で参照し、直後の行に `*図N: キャプション*` を置く。

```
diagrams/{記事のスラッグ}/{記事の日付}-{内容}.dot   # ソース（Git管理）
images/{同じ名前}.png                              # 出力（Git管理、Zennが配信する）
```

ファイル名に図番号を入れない。番号は記事のキャプションだけで持つ。
図を1枚差し込むたびに以降の番号が繰り上がるため、番号をファイル名に入れると
そのたびにファイルと画像のリネームが必要になる。

## レンダリング

```bash
./diagrams/render.sh            # すべての .dot を再レンダリング
./diagrams/render.sh 20260820   # 名前に 20260820 を含むものだけ
```

必要なのは `dot`（graphviz）、`rsvg-convert`（librsvg）、`python3`、そして日本語の
ゴシック体フォント。`.dot` の `fontname` は
`"Harano Aji Gothic,Noto Sans CJK JP,IPAGothic"` の順にフォールバックする。
書き出したPNGは必ず目視して、はみ出し・重なり・不自然な折り返しがないことを確認する。

`render.sh` はPNGを直接書き出さず、いったんSVGに出してから `round.py` と `elbow.py` に通し、
`rsvg-convert` でPNGにしている。graphvizの角丸半径は12pt固定で属性からは変えられず、
そのままでは角が大きすぎるため、`round.py` がノードとクラスタの角丸矩形を検出して
`<rect rx>` に描き直している。半径は `render.sh` の `RADIUS`（既定4pt）で決まる。
`elbow.py` は経由点方式の折れ線を仕上げる後処理で、経由点ノードの手前で約1pt切れる
エッジ端点を交点にスナップし、同じ見た目の2本が突き合う角は1本のパスに結合して
角を丸め（半径6pt）、3本以上が集まるT字は丸い線端で隙間を埋める。角が切れて
見えるときは .dot 側をいじる前に、この後処理を通した結果を確認する。

## 図の役割

図は関係性と流れを見せるための補助である。文章で説明すべき内容は本文に書き、図には入れない。

- ノード内のテキストは「名前＋1〜2行の要点」まで。それを超える説明はキャプションか本文へ
- 注記だけの浮きノードは作らない
- すべてのノードは線か矢印で他のノードとつながっていること
- Zennの本文幅は700px程度しかない。横長になりすぎたら `rankdir` をTBに変えて縦に組む

## テキストの揃え

文になっているテキストは左揃え、単語・名前だけのテキストは中央揃えにする。
左揃えはHTML-likeラベルで実現する。

```dot
Node [label=<<b>ノード名</b><br align="left"/>説明の1行目<br align="left"/>>];
```

構造体やスタックの内訳を並べるときはHTML-likeのテーブルを使う（`shape=plain, style=""` が必要）。

```dot
Node [shape=plain, style="", label=<
  <table border="0" cellborder="1" cellspacing="0" cellpadding="7" color="#38638F">
    <tr><td align="left" bgcolor="#EFF5FB"><b>見出し</b></td></tr>
    <tr><td align="left" bgcolor="#D9E7F4" port="ra">行の内容</td></tr>
  </table>>];
```

エッジラベルの左揃えは各行末の `\l`（行頭に半角スペースを1つ入れて線から離す）。

## 共通設定（全 .dot の冒頭に置く）

```dot
graph [
  fontname="Harano Aji Gothic,Noto Sans CJK JP,IPAGothic", fontsize=13,
  rankdir=TB,  // 図に応じてLR
  compound=true, splines=true,
  nodesep=0.45, ranksep=0.7, pad=0.25,
  bgcolor="white", newrank=true
];
node [
  fontname="Harano Aji Gothic,Noto Sans CJK JP,IPAGothic", fontsize=12,
  shape=box, style="rounded,filled",
  fillcolor="#F1F5F9", color="#475569", penwidth=1.6,
  margin="0.2,0.14"
];
edge [
  fontname="Harano Aji Gothic,Noto Sans CJK JP,IPAGothic", fontsize=11,
  color="#334155", penwidth=1.4, arrowsize=0.9,
  fontcolor="#1E293B"
];
```

## カラーパレット

役割ごとに色を使い分ける。1つの図に使う色は3系統までを目安にする。

| カテゴリ | ノード塗り | 枠・強調 | グループ枠背景 | グループタイトル文字 |
|---|---|---|---|---|
| 中立・外部システム | `#EDF1F5` | `#475569` | `#F4F6F8` | `#334155` |
| 主系列（データの流れ、計装の本線） | `#D9E7F4` | `#38638F` | `#EFF5FB` | `#2E4D6E` |
| 正しい状態・期待どおりの値 | `#D6E8D6` | `#3F6E3F` | `#F0F7F0` | `#2C4F2C` |
| ストレージ・バッファ・表 | `#F3E8CE` | `#96742E` | `#FAF4E4` | `#6B5321` |
| 補助的な仕組み・代替経路 | `#E9DFF2` | `#75589C` | `#F5F1F9` | `#5B4370` |
| 障害・警告・危険な状態 | `#F5DEDE` | `#A04848` | `#FBEFEF` | `#7A3030` |

グループ枠（cluster）は `style="rounded"`、`labeljust="l"`、`penwidth=1.6`、`margin=14`、
タイトルは `label=<<b>タイトル</b>>` で太字にする。

## 線の引き方

矢印や線は直線を基本とし、水平と垂直の組み合わせで引く。斜め線や曲線を使わない。エッジのラベルは、線にも図形にも重ねない。

縦一列のチェーンは既定の dot レイアウトのままで直線になる。分岐、合流、横接続、側注を含む図は `graph [layout=neato, inputscale=72, splines=line]` にして全ノードを `pos="x,y!"` で固定し、折れ位置は `shape=point, style=invis, width=0.01` の経由点で組む（矢頭は最終区間だけに付け、途中区間は `dir=none`）。ラベルは `shape=plaintext, style=""` のノードとして線の横の空白に置く（線の座標とラベル中心の座標をずらす）。`dpi` は付けない（render.sh がSVG経由で処理する）。neatoはクラスタを描けないので、枠が要るときは `fixedsize=true` の背景ノードを先に定義し、タイトルはplaintextノードを枠の左上に置く。

## 矢印の意味

1つの図で矢印の意味を1種類に絞る。混ぜるときは線種で分け、**キャプションの冒頭で矢印の意味を宣言する**。

- 制御の流れ、データの移動、時間の前後、依存、参照、変換、分類のどれなのかを決めてから描く
- 依存は「依存する側から、される側へ」、因果は「原因から結果へ」で統一する
- 凡例だけの浮きノードは作らない。凡例はキャプションで述べる
- 矢印を持たない図（レイアウト図や対比表）なら、キャプションで「この図に矢印はない」と書く

## 線の使い分け

- 順方向のデータフロー: 実線 `#334155`、`penwidth=1.4`（主要フローは1.6〜1.8）
- 従属・非同期・成立しない経路: `style=dashed`、`color="#7C8DA3"`
- 障害や無効化を示す線: `style=dashed`、`color="#A04848"`（無効化は `arrowhead=tee`、読まないことを示すなら `arrowhead=odot`）
- レイアウト調整用: `style=invis`（`{ rank=same; a -> b [style=invis]; }` で左右の順序を固定できる）

## 既知の注意点

- HTML-likeラベル内では `&` `<` `>` をエスケープする（`&amp;` 等）
- cluster間を直接つなぐときは `compound=true` と `lhead=` / `ltail=` を使う
- エッジラベルが線に重なるときは、ラベルを短くして説明をキャプションへ移すのが早い
