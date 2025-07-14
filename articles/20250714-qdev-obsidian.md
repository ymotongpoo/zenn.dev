---
title: "Amazon Q Developer CLIでObsidian MCPサーバーを使う"
emoji: "🤖"
type: "tech"
topics: ["amazonq", "obsidian", "mcp"]
published: true
---

## はじめに

こんにちは、AWSでデベロッパーアドボケイトをしているものです。
気がつけばすっかりAIコーディングエージェントが普及し、さらにMCPを通じてさまざまなリソースと連携して作業をすることも増えてきました。
自分は普段遣いのAIコーディングエージェントとして[Amazon Q Developer CLI](https://docs.aws.amazon.com/ja_jp/amazonq/latest/qdeveloper-ug/command-line.html)をメインで使っていますが、これまでObsidianとの連携をしていなかったので設定してみました。

なお以下はmacOS版のObsidian (v1.8.10)での設定です。

## 必要なObsidianプラグインのインストール

ObisidianをMCPサーバーして使うにはいくつか方法がありますが、Obisidianのコミュニティプラグインの[MCP Tools](https://github.com/jacksteamdev/obsidian-mcp-tools)を使うのが簡単です。（直接ObisidianのプラグインIDはmcp-tools）

これをインストールするための準備として、まず以下の3つのコミュニティプラグインをインストールします。

* [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api)　（id: obsidian-local-rest-api）
* [Smart Connections](https://github.com/brianpetro/obsidian-smart-connections) （id: smart-connections）
* [Templater（オプション）](https://github.com/SilentVoid13/Templater)（id: templater-obsidian）

これらをインストールして、有効化します。Templaterはインストールしなくても使えます。
これらのインストールが完了したら、次に"MCP Tools" (id: mcp-tools)をインストールして、有効化します。

![MCP Toolsの設定画面](/images/20250714-1.png)

このように緑のチェックマークが3つ（少なくともTemplator以外の2つ）についていれば大丈夫です。

## Amazon Q Developer CLIでのMCPサーバーの設定

これでObsidian側のMCPサーバー化の設定は終わったので、次はAmazon Q Developer CLIから呼び出します。
上のMCP Toolsの設定のスクリーンショットにある、Resourcesセクションの「Server install folder」をクリックすると、FinderでMCPサーバーの実行用ツールのパスを開いてくれるのでこれをメモしておきます（おそらく `/path/to/vault/.obsidian/plugins/mcp-tools/bin/mcp-server` となっている）。

次にLocal REST APIのプラグインの設定画面にあるAPIキーをコピーします（下のスクリーンショットの中の赤くマスクしたところの値です）。
![Local REST APIの設定画面](/images/20250714-2.png)

この値を使って他のMCPサーバーの追加と同様に `~/.aws/amazonq/mcp.json` に書き加えます。

```json
{
  "mcpServers": {
    "mcp-obsidian": {
      "command": "/Users/yoshiyyy/obsidian/main/.obsidian/plugins/mcp-tools/bin/mcp-server",
      "env": {
        "OBSIDIAN_API_KEY": "YOUR_LOCAL_REST_API_KEY"
      }
    }
  }
}
```

これでObsidianがAmazon Qからも使えます。

## 使ってみる

これで早速起動してみます。

```shell-session
$ q chat
✓ github loaded in 0.01 s
✓ mcp_obsidian loaded in 0.11 s
⚠ 2 of 4 mcp servers initialized. Servers still loading:
 - awslabsaws_documentation_mcp_server
 - playwright

    ⢠⣶⣶⣦⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣤⣶⣿⣿⣿⣶⣦⡀⠀
 ⠀⠀⠀⣾⡿⢻⣿⡆⠀⠀⠀⢀⣄⡄⢀⣠⣤⣤⡀⢀⣠⣤⣤⡀⠀⠀⢀⣠⣤⣤⣤⣄⠀⠀⢀⣤⣤⣤⣤⣤⣤⡀⠀⠀⣀⣤⣤⣤⣀⠀⠀⠀⢠⣤⡀⣀⣤⣤⣄⡀⠀⠀⠀⠀⠀⠀⢠⣿⣿⠋⠀⠀⠀⠙⣿⣿⡆
 ⠀⠀⣼⣿⠇⠀⣿⣿⡄⠀⠀⢸⣿⣿⠛⠉⠻⣿⣿⠛⠉⠛⣿⣿⠀⠀⠘⠛⠉⠉⠻⣿⣧⠀⠈⠛⠛⠛⣻⣿⡿⠀⢀⣾⣿⠛⠉⠻⣿⣷⡀⠀⢸⣿⡟⠛⠉⢻⣿⣷⠀⠀⠀⠀⠀⠀⣼⣿⡏⠀⠀⠀⠀⠀⢸⣿⣿
 ⠀⢰⣿⣿⣤⣤⣼⣿⣷⠀⠀⢸⣿⣿⠀⠀⠀⣿⣿⠀⠀⠀⣿⣿⠀⠀⢀⣴⣶⣶⣶⣿⣿⠀⠀⠀⣠⣾⡿⠋⠀⠀⢸⣿⣿⠀⠀⠀⣿⣿⡇⠀⢸⣿⡇⠀⠀⢸⣿⣿⠀⠀⠀⠀⠀⠀⢹⣿⣇⠀⠀⠀⠀⠀⢸⣿⡿
 ⢀⣿⣿⠋⠉⠉⠉⢻⣿⣇⠀⢸⣿⣿⠀⠀⠀⣿⣿⠀⠀⠀⣿⣿⠀⠀⣿⣿⡀⠀⣠⣿⣿⠀⢀⣴⣿⣋⣀⣀⣀⡀⠘⣿⣿⣄⣀⣠⣿⣿⠃⠀⢸⣿⡇⠀⠀⢸⣿⣿⠀⠀⠀⠀⠀⠀⠈⢿⣿⣦⣀⣀⣀⣴⣿⡿⠃
 ⠚⠛⠋⠀⠀⠀⠀⠘⠛⠛⠀⠘⠛⠛⠀⠀⠀⠛⠛⠀⠀⠀⠛⠛⠀⠀⠙⠻⠿⠟⠋⠛⠛⠀⠘⠛⠛⠛⠛⠛⠛⠃⠀⠈⠛⠿⠿⠿⠛⠁⠀⠀⠘⠛⠃⠀⠀⠘⠛⠛⠀⠀⠀⠀⠀⠀⠀⠀⠙⠛⠿⢿⣿⣿⣋⠀⠀
 ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠛⠿⢿⡧

╭─────────────────────────────── Did you know? ────────────────────────────────╮
│                                                                              │
│         Use /model to select the model to use for this conversation          │
│                                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯

/help all commands  •  ctrl + j new lines  •  ctrl + s fuzzy search
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 You are chatting with claude-4-sonnet
```

![MCPサーバーの設定後にAmazon Q Developer CLI起動](/images/20250714-3.png)

ちゃんと `mcp_obsidian` が読み込まれているのがわかります。これでObisidian内にメモしておいた内容を確認してみましょう。

```shell-session
> Obisidianにメモした2025年8月中の海外出張に関する情報を要約してください

> I'll help you summarize information about overseas business trips in August 2025 from your Obsidian notes. Let me search through your vault
for relevant information.


🛠️  Using tool: search_vault_simple from mcp server mcp_obsidian
 ⋮
 ● Running search_vault_simple with the param:
 ⋮  {
 ⋮    "arguments": {
 ⋮      "query": "海外出張 2025年8月"
 ⋮    },
 ⋮    "name": "search_vault_simple"

Allow this action? Use 't' to trust (always allow) this tool for the session. [y/n/t]:

> t

 ⋮  }
 ⋮
 ● Completed in 0.105s


> Let me try a broader search for business trip information in 2025:
...(中略)...

> Based on your Obsidian notes, here's a summary of your overseas business trip information for August 2025:

## 2025年8月の海外出張情報まとめ

### AWS Heroes Summit出張
• **イベント日程**: 8月26日〜28日
• **出張期間**: 8月24日出発、8月29日帰国
• **手配状況**:
  • 飛行機とホテルの予約済み
  • 航空券発券時に問題が発生
  • 旅行代理店に連絡して発券対応を依頼済み

### 注意事項
• 航空券の発券に関して何らかの問題があったため、旅行代理店経由での対応が必要となった状況

現在のところ、あなたのObsidianメモには8月のAWS Heroes Summit出張に関する情報のみが記録されています。他に8月の海外出張予定がある場合は、まだメモに記録されていない可能性があります。
```

という具合にしっかりと記録が見つかりました。
雑に記録を取っていただけですが、整理された形で提示してくれるのはとても助かります。
これでますますObsidianを便利に使えますね！
