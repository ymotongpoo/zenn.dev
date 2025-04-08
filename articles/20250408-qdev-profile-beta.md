---
title: "Amazon Q Developer for CLIでプロファイルとコンテキストの管理機能がベータになった"
emoji: "🤖"
type: "tech" # tech: 技術記事 / idea: アイデア
topics: ["amazonq", "awscli", "AWS", "AI"]
published: false
---

## はじめに

こんにちは、AWSでデベロッパーアドボケイトをしているものです。[Amazon Q Developer for CLI](https://aws.amazon.com/jp/blogs/news/effortlessly-execute-aws-cli-commands-using-natural-language-with-amazon-q-developer/)（以下、Q Dev for CLI）をここ最近重点的に触っていますが、使用している中でコンテキストの管理をもう少し柔軟にしたいなあと思っていました。

他のAIコーディングエージェントでは例えば次のような形でコンテキスト管理を行っています。

* Cline: `.clinerules`, `.clinerules/**`
* Roo Code: `.clinerules-[mode]`
* Cursor: `.cursor/rules/**.mdc`
* GitHub Copilot: `.github/copilot-instructions.md`

このような機能をもっとQ Dev for CLIでも使いたいと思っていたところ、コンテキスト管理とプロファイル管理の機能が[v1.7.2でベータとして追加され](https://github.com/aws/amazon-q-developer-cli/releases/tag/v1.7.2)ました。

@[card](https://github.com/aws/amazon-q-developer-cli/pull/834)

実際に `q chat` で起動してみるとコマンドに `/profile` と `/context` が追加されているのがわかります。

![alt text](/images/20250408-1.png)

## 事前準備: アカウント

Q Dev for CLIを試すにはAWS Builder IDもしくはAWSアカウントが必要です。AWS Builder IDであればクレジットカード情報を登録したりすることがなく、安心して無料枠分でのみ試せるのでおすすめです。

@[card](https://community.aws/builderid?trk=dccd318a-a012-40c6-bffb-bd0a6216646d&sc_channel=el)

詳細な手順は[沼口さんの記事](https://note.com/s_numaguchi/n/nd5126833389b)にまとめられています。Q Dev for CLIのmacOSやLinuxでのアカウント設定方法は以下の記事を参照してください。

* [macOS](https://zenn.dev/ymotongpoo/articles/20250310-q-for-cli)
* [Linux](https://zenn.dev/ymotongpoo/articles/20250327-q-for-cli-linux)

## コンテキスト管理

この機能は他のAIコーディングエージェントと同様に特定のファイルにコンテキストを書いておくと、Q Dev for CLIがよしなに読み取ってくれるというものです。コンテキストの設定ファイルはグローバルのものとプロファイル固有のものがあります（プロファイルについては後述）。グローバルのものはどのセッションでも必ず参照されるファイルで、次のものが該当します。

* `README.md`: いわゆるREADMEファイル。プロジェクトの説明や仕様が書いてあることが想定される。
* `AmazonQ.md`: Q Dev for CLIを動作させる際に必要なコンテキスト。Q Dev for CLIの動作全般に関わることを書いておく。
* `.amazonq/rules/**/*.md`: 細かなコンテキスト（各言語向けの所作など）を分割して記述する。

プロファイル向けのコンテキストは次に説明するプロファイルごとに任意に設定できるコンテキストです。

## プロファイル管理

プロファイルはプロジェクト全体（グローバル）とは別に個別の事情に関して設定したいコンテキストなどを追加したい場合に作成します。たとえば、この機能を追加したpull requestには次のような例が書いてあります。

* 個別の開発チーム特有の規約などを追加する
* 作業リポジトリに対して新たな機能を追加したいときに、それに必要なタスクや情報などを追加する

プロファイルを作成する場合は `/profile create <profile name>` コマンドで作成します。そして作成したプロファイルに新たなコンテキストを追加するには `/context add <path1> [path2...]` という具合に、追加したいコンテキストファイルのパスを指定します。

```shell-session
> /profile create my-team

Created profile: my-team

[my-team] > /context add "~/.aws/qcli/my-team/**/*.md"

Added 1 path(s) to profile context.
```

現在のプロファイルで読み込まれるコンテキストを確認する場合には `/context show` で確認します。

```shell-session
[my-team] > /context show

current profile: my-team

global:
    .amazonq/rules/**/*.md
    README.md
    AmazonQ.md

profile:
    "~/.aws/qcli/my-team/**/*.md"
```

このようにプロファイルを使うことでその時々だけ必要なコンテキストを柔軟に指定できます。

## デモ

次のデモはプロファイル `my-team` のときだけ、チームのタスクリストがコンテキストに含まれることを確認しています。たとえばこのタスクリストをプロジェクトに見えないところでGit管理などをしておけば、チーム内でタスクが共有されコンテキストに必ず含まれるようになるという具合です。

![デモ](/images/20250408-2.gif)

## おわりに

Q Dev for CLIをはじめAmazon Q DeveloperはAWS系の開発や運用を行う際の強力なだけでなく、一般的な開発用途でもかなり使えるツールになってきています（裏でClaude 3.7 Sonnetも使っているので納得）。ぜひ色々な機能を試してみてください！
