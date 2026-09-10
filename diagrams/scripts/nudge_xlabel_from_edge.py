#!/usr/bin/env python3
"""エッジの `xlabel` が、そのエッジ自身の経路に近すぎる／触れている場合に
外側へ押し出す後処理。

Graphviz の `xlabel` 自動配置は、ラベルの中心からエッジの経路までの
オフセットを決めるが、日本語（全角文字）を含むテキストの実際の描画幅を
過小評価するため、特に縦線の脇に置かれた長いラベルが線に触れる／
めり込むことがある（英数字と全角文字が混在する `xlabel` で起きやすい）。

このスクリプトは `text-anchor="middle"` の `<text>` を持つエッジを見つけ、
文字幅を（全角=1.0em、半角英数=0.6em として）概算し、テキストの
自陣営（エッジに近い側）の端が経路から最低 `margin` pt 離れるように、
必要な分だけ `x`（経路が縦線の場合）または `y`（経路が横線の場合）を
外側へずらす。ラベルの中心位置しか動かさないため、他ノードとの新たな
重なりを生む可能性はあるが、それは check_overlaps.py で検出できる。

    使い方: ... | nudge_xlabel_from_edge.py [余白pt] > out.svg
"""

import re
import sys

EDGE_GROUP = re.compile(r'(<g[^>]*class="edge"[^>]*>.*?</g>)', re.S)
PATH = re.compile(r'<path\b([^>]*?)/>')
TEXT = re.compile(r'(<text\b([^>]*?)>)(.*?)(</text>)', re.S)
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
NUM = re.compile(r'-?\d+(?:\.\d+)?')

FULLWIDTH_EM = 1.0
HALFWIDTH_EM = 0.6
# 縦方向の文字の広がり: ベースラインから上に ascent、下に descent
ASCENT_EM = 0.8
DESCENT_EM = 0.2


def text_width(s, font_size):
    em = 0.0
    for ch in s:
        em += FULLWIDTH_EM if ord(ch) > 0x2E00 else HALFWIDTH_EM
    return em * font_size


def path_axis(d):
    nums = [float(n) for n in NUM.findall(d)]
    if len(nums) < 4:
        return None, None
    xs = {round(x, 1) for x in nums[0::2]}
    ys = {round(y, 1) for y in nums[1::2]}
    if len(xs) == 1 and len(ys) > 1:
        return 'v', nums[0]
    if len(ys) == 1 and len(xs) > 1:
        return 'h', nums[1]
    return None, None


def process_group(group, margin):
    path_m = PATH.search(group)
    text_m = TEXT.search(group)
    if not path_m or not text_m:
        return group
    path_attrs = dict(ATTR.findall(path_m.group(1)))
    axis, coord = path_axis(path_attrs.get('d', ''))
    if axis is None:
        return group

    open_tag, attrs_str, body, close_tag = text_m.groups()
    text_attrs = dict(ATTR.findall(attrs_str))
    if text_attrs.get('text-anchor') != 'middle':
        return group
    font_size = float(text_attrs.get('font-size', '11'))
    half_w = text_width(body, font_size) / 2.0

    if axis == 'v':
        tx = float(text_attrs['x'])
        # 経路(coord)とラベルの近い側の端の距離が margin 未満なら押し出す
        dist = coord - (tx + half_w) if tx <= coord else (tx - half_w) - coord
        if dist < margin:
            shift = margin - dist
            new_tx = tx - shift if tx <= coord else tx + shift
            text_attrs['x'] = f'{new_tx:.2f}'
    else:
        # 横線の場合、縦方向の広がりはテキストの幅ではなく高さで測る。
        # y はベースライン: 線より上のラベルは下端 (descent) が、
        # 線より下のラベルは上端 (ascent) が線に近い側になる。
        ty = float(text_attrs['y'])
        if ty <= coord:
            dist = coord - (ty + DESCENT_EM * font_size)
        else:
            dist = (ty - ASCENT_EM * font_size) - coord
        if dist < margin:
            shift = margin - dist
            new_ty = ty - shift if ty <= coord else ty + shift
            text_attrs['y'] = f'{new_ty:.2f}'

    new_attrs = ' '.join(f'{k}="{v}"' for k, v in text_attrs.items())
    new_text = f'<text {new_attrs}>{body}</text>'
    return group[:text_m.start()] + new_text + group[text_m.end():]


def main():
    margin = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    svg = sys.stdin.read()
    sys.stdout.write(EDGE_GROUP.sub(lambda m: process_group(m.group(1), margin), svg))


if __name__ == '__main__':
    main()
