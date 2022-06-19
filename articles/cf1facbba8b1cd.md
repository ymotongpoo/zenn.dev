---
title: "Hypothesisで固定値のiterableからexampleを生成するストラテジー"
emoji: "🐞"
type: "tech" # tech: 技術記事 / idea: アイデア
topics: ["Hypothesis", "PropertyBasedTesting", "test"]
published: true
---

:::message
バージョン情報

* Hypothesis: v6.47.2
* Python: 3.10.5
:::

Hypothesisで特定のiterable（たとえばリスト）からexampleを生成するストラテジーを作りたい場合は `sampled_from` を使う。

https://hypothesis.readthedocs.io/en/latest/data.html#hypothesis.strategies.sampled_from

たとえば次のようにできる。

```python
from hypothesis import given
from hypothesis.strategy import sampled_from

@given(sampled_from([range(1, 11)]))
def test_foo(x):
    assert x < 11
```
