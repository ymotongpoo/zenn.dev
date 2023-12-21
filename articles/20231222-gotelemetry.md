---
title: "Goを改善するためのGo Telemetry"
emoji: "📊"
type: "tech" # tech: 技術記事 / idea: アイデア
topics: ["Go", "Observability", "Telemetry"]
published: true
published_at: 2023-12-22 12:30
---

## はじめに

こんにちは！Google CloudでオブザーバビリティやSRE関連の担当をしているエンジニアです。この記事は[Goアドベントカレンダー](https://qiita.com/advent-calendar/2023/go)の22日目の記事です。

## Goとオブザーバビリティ

私は業務でオブザーバビリティを中心として啓蒙活動や開発を行っているわけですが、その中で常に「改善にはまず計測が必要です」というメッセージをさまざまな方々にお伝えしています。

Goでは計測のための仕組みとして（ `testing.B` あるいは `go test -bench` として知られる）ベンチマーク[^bench]や `pprof` が最初期から[^pprof]用意されていて、パフォーマンス計測はかなり標準が充実した言語になっています。

[^bench]: [ベンチマークが追加されたCL](https://codereview.appspot.com/154173)は[Goがオープンソースとして公開された日](https://opensource.googleblog.com/2009/11/hey-ho-lets-go.html)の直後です。

[^pprof]: [pprofが追加されたCL](https://codereview.appspot.com/719041)も、まだweekly releaseの最初期に行われています。

そして近年もそれに満足せず、Goを改善するための計測の仕組みがいくつも提案されています。

たとえば[`runtime/metrics`](https://pkg.go.dev/runtime/metrics)は[design #37112](https://github.com/golang/proposal/blob/master/design/37112-unstable-runtime-metrics.md)で提案されてGo 1.16から導入されました。これによってランタイムのメトリクスにもとづいたプログラムの制御などが少しやりやすくなりました。

そして計測というのはパフォーマンスやシステムのメトリクスだけではありません。Goには様々な標準ツールがあり、そういったツールの改善を効率よく行うためには、各ツールがどういったユーザーにどれくらい使われているかを統計的に取得する必要があります。
今日は、そうした目的に対して、新しく追加されたGo Telemetryというパッケージについて紹介します。

## Go Telemetry

Go Telemetryというパッケージをご存知でしょうか。

@[card](https://pkg.go.dev/golang.org/x/telemetry)

これはGo teamが管理するレポジトリー内で開発している各種ツールの利用状況を可視化したり、専用サーバーにアップロードしたりするための各種ツールのパッケージです。

専用サーバーにアップロードされた結果は次のサイトで確認できます。

@[card](https://telemetry.go.dev/)

これはRuss Coxが2023年2月に投稿した ["Transparent Telemetry for Open-Source Projects"](https://research.swtch.com/telemetry-intro) という記事[^rsc]にあるように、OSSを改善していくためにはバグレポートだけでなく、テレメトリーが有効で必要であるという思想から[推進された](https://github.com/golang/go/issues/58894)パッケージです。

[^rsc]: [日本語で解説された記事](https://zenn.dev/a2not/articles/transparent-telemetry)があるので、興味がある人はぜひこちらも参照してください。

Go Telemetryは現在、GoのLanguage Serverである[gopls](https://github.com/golang/tools/tree/master/gopls)で[計装されています](https://github.com/golang/tools/blob/gopls/v0.14.2/gopls/main.go#L27)。`gopls` v0.14.0からこのテレメトリーの収集は自動で行われていて、もし使っていれば皆さんのローカルストレージにすでにテレメトリーデータが収集されているはずです。デフォルトのテレメトリーの保存先は `os.UserConfigDir()/go/telemetry/local` なので、各環境でアクセスしてみてください。ちなみに、 [`os.UserConfigDir()`](https://pkg.go.dev/os#UserConfigDir) は次のとおりです。

* Linux: `$XDG_CONFIG_HOME` あるいは `$HOME/.config`
* macOS: `$HOME/Library/Application Support`
* Windows: `%AppData%`

Visual Studio Codeでアップデートの際にREADMEを注意深く読んでいる人であれば、すでに気がついているかもしれません。

@[card](https://github.com/golang/vscode-go/tree/v0.40.0?tab=readme-ov-file#telemetry)

該当箇所を引用すると

> VS Code Go extension relies on the [Go Telemetry](https://telemetry.go.dev/) to learn insights about the performance and stability of the extension and the language server (`gopls`). **Go Telemetry data uploading is disabled by default** and can be enabled with the following command:

というわけで、記録はされているけれど、Go teamにはまだ共有されていないことになります。ここまで読んだみなさんであれば「え、自分も協力したい！どうやったら共有できるの？」と思ったことでしょう[^prompt]！

[^prompt]: すでに[goplsから出されるプロンプト](https://github.com/golang/go/issues/62576)にしたがってopt-inしている方は以下の節をすでに実施しているかもしれません。

というわけで、本原稿執筆時点でのその方法をご紹介します。

## `gotelemetry` コマンド

上のVisual Studio Code用Go拡張のREADMEの続きを読めば良いだけなのですが、`gotelemetry`というツールを用いて設定を変更します。インストールは普通のコマンドと同様に行います。

```console
go install golang.org/x/telemetry/cmd/gotelemetry@latest
```

このツールをインストールしたあと、次のようにしてテレメトリーの共有（送信）を有効にします。

```console
gotelemetry on
```

すると次のようなメッセージが表示されます。

```
Telemetry uploading is now enabled and data will be periodically sent to https://telemetry.go.dev/. Uploaded data is used to help improve the Go toolchain and related tools, and it will be published as part of a public dataset.

For more details, see https://telemetry.go.dev/privacy.
This data is collected in accordance with the Google Privacy Policy (https://policies.google.com/privacy).

To disable telemetry uploading, run “gotelemetry off”.
```

実際に送信されるデータは、直接先に確認した `os.UserConfigDir()/go/telemetry/local` の中身を確認しても良いですが、Go Telemetryのウェブサイトと同様のUIで可視化したい場合には次のコマンドでウェブサーバーを起動して、ブラウザでアクセスしてみましょう。

```console
gotelemetry view
```

すると、`telemetry`パッケージが数えているカウンターの指標が棒グラフの形で見れます。

![ローカルで起動したGo Telemetry](/images/20231221-1.png)

何が送信されているか心配な人もこれで安心です。

## 今後の展開

Go teamが開発しているツールはさまざまにあります。たとえばGoのコンパイラ自体もそうですし、 `go doc` を始めとする `go` ツールや [`govulncheck`](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck) などもそうです。

今後、こういったツールでも計装が行われるようになることでしょう。ただRuss Coxが記事でも書いている通り、コミュニティではopt-inが好まれていて、これはプライバシーに関する懸念の表れでもあります。

Go teamが課題のトリアージをしやすくしたり、バグレポートに現れない情報を得やすくするためにも、これらのテレメトリーが広く認知されて使われるようになることを期待しています。
