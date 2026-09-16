#!/usr/bin/env python3
"""用語の表記を本文と図の中で統一する。

コードブロック、インラインコード、URL、モジュールパスを退避してから
置換するので、識別子や YAML のキーを壊さない。

置換対象は TERMS に書く。左辺は正規表現で、英数字の境界は呼び出し側で
付けずにこのスクリプトが付ける（部分一致で別の語を壊さないため）。

使い方:
    python3 unify_terms.py books/foo/*.md diagrams/foo/*.dot

注意:
  - 全ファイルを変換して検証してから書き込む。途中で失敗しても
    一部だけ変換された状態を残さない。
  - 退避の目印には私用領域の文字だけを使う。NUL を使うとファイルが
    バイナリ扱いになり、grep や diff が中身を見せなくなる。目印に
    英数字を混ぜると、置換対象の語の境界判定にすり抜けて壊れる。
"""
import re
import sys

# 置換する語。順序に意味がある（長い語を先に置く）。
TERMS = [
    # 4章レビュー: Collector のコンポーネント名
    (r"receiver", "レシーバー"),
    (r"processor", "プロセッサー"),
    (r"exporter", "エクスポーター"),
    (r"trace ID", "トレースID"),
    (r"manifest", "マニフェスト"),
    (r"schema URL", "スキーマURL"),
    # 2章・3章レビュー
    (r"tail sampling", "テイルサンプリング"),
    (r"head sampling", "ヘッドサンプリング"),
    (r"trace context", "トレースコンテキスト"),
    (r"annotation", "アノテーション"),
    (r"Baggage", "バゲッジ"),
]

# 退避に使う目印。私用領域の文字だけで組み、英数字を含めない。
# 個数は「1文字＋区切り」を繰り返して表現する。
MARK = "\ue000"
SEP = "\ue001"


def _encode(n: int) -> str:
    return MARK + SEP * n + MARK


def protect(s: str):
    """置換してはいけない範囲を目印へ退避する。"""
    saved = []

    def stash(m):
        saved.append(m.group(0))
        return _encode(len(saved) - 1)

    # 順序が重要。コードブロックを先に退避しないと、
    # 中の URL やインラインコードを個別に拾ってしまう。
    patterns = [
        r"```.*?```",                      # コードブロック
        r"`[^`\n]+`",                      # インラインコード
        r"https?://[^\s)\ue000\ue001]+",   # URL（目印文字は含めない）
        r"\[\^[^\]]+\]",                   # 脚注の参照と定義
    ]
    for pat in patterns:
        s = re.sub(pat, stash, s, flags=re.S)
    return s, saved


def restore(s: str, saved) -> str:
    """退避した範囲を戻す。入れ子があるので変化しなくなるまで繰り返す。"""
    for _ in range(10):
        before = s
        for i, orig in enumerate(saved):
            s = s.replace(_encode(i), orig)
        if s == before:
            break
    return s


def convert(s: str):
    s, saved = protect(s)
    hits = []
    for pat, rep in TERMS:
        # 英数字に挟まれた出現は別の語の一部なので触らない。
        # 「レシーバー」のようなカタカナ語の直後に s が残る形も避ける。
        regex = re.compile(r"(?<![0-9A-Za-z_])" + pat + r"(s)?(?![0-9A-Za-z_])")

        def sub(m):
            hits.append(m.group(0))
            return rep

        s = regex.sub(sub, s)
    s = restore(s, saved)
    return s, hits


def main(paths):
    results = {}
    total = 0
    for path in paths:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        out, hits = convert(src)
        if MARK in out or SEP in out:
            raise SystemExit(f"目印が残った: {path}（復元漏れ）")
        if out != src:
            results[path] = out
            total += len(hits)
            print(f"{path}: {len(hits)}件 {sorted(set(hits))}")

    # 全ファイルを検証し終えてから書き込む。
    for path, out in results.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
    print(f"--- {len(results)}ファイル / {total}件を置換した")


if __name__ == "__main__":
    main(sys.argv[1:])
