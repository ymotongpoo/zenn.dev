---
title: "apkoの設計"
---

apkoは、APKパッケージの組み合わせだけからOCIコンテナイメージを組み立てるツールです。Dockerfileが持つ`RUN`のような任意コマンド実行の手段を一切持たず、YAMLに書かれた宣言だけでイメージの中身が決まります。この制約こそがapkoの核心です。

## 命令型を排除する理由

2章で確認したように、Dockerfileの`RUN`は自由度が高い分、イメージの中で何が起きたかを機械的に検証しづらくします。apkoは`contents.packages`に列挙したAPKパッケージをインストールする以外の手段を提供しません。任意コマンドを実行できないということは、逆に言えば「このイメージに含まれるファイルは、指定したAPKパッケージ由来のものだけである」という保証を機械的に導けるということです。これがapkoのSBOMが正確である理由であり、同じ`apko.yaml`から同じ結果が再現できる理由でもあります。

## apko.yamlの構造

apkoの設定ファイルも1つのYAMLで完結します。主要なフィールドは次のとおりです。

| フィールド | 役割 |
|---|---|
| `contents.repositories` | 参照するAPKリポジトリのURL（WolfiやAlpineなど） |
| `contents.packages` | イメージにインストールするパッケージの一覧 |
| `contents.keyring` | パッケージ検証に使う公開鍵 |
| `entrypoint.command` / `cmd` | コンテナのENTRYPOINTやCMDに相当する起動コマンド |
| `accounts.users` / `accounts.groups` / `accounts.run-as` | 実行ユーザーの定義。非rootでの実行を明示できる |
| `environment` | コンテナに設定する環境変数 |
| `archs` | ビルド対象のアーキテクチャ（`x86_64`、`aarch64`など） |
| `paths` | ファイルの所有権やパーミッションを後から調整する設定 |

最小構成の例を見てみます。[apkoのREADME](https://github.com/chainguard-dev/apko)に載っている例です。

```yaml
contents:
  repositories:
    - https://dl-cdn.alpinelinux.org/alpine/v3.22/main
  packages:
    - alpine-base

entrypoint:
  command: /bin/sh -l

environment:
  PATH: /usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/sbin:/bin
```

`contents`にAlpine公式リポジトリと`alpine-base`パッケージを指定し、`entrypoint.command`でシェルを起動するだけの、数行で完結する定義です。次章では、これをWolfiベースの構成に置き換えて実際にビルドします。

`entrypoint`には、単一プロセスを直接起動する形式のほかに、`type: service-bundle`を指定してs6監視スイート[^s6]で複数プロセスを管理させる形式もあります。

## イメージ生成の流れ

apkoのビルドは、指定したパッケージ群の依存関係を解決し、それぞれのAPKからファイルをレイヤーとして展開し、SBOMを生成してOCIイメージとして出力するという流れで進みます。レイヤーに含まれるファイルのタイムスタンプや所有者、パーミッションは、実行環境の状態ではなく`apko.yaml`の宣言値から決定的に決まります。ビルドを実行するホストの時刻や乱数に依存する要素を排除することで、同じ入力から常に同じバイトのイメージが得られます。

マルチアーキテクチャ対応は、Docker Buildxのようなクロスビルドの仕組みに頼らず、指定した各アーキテクチャごとに独立してパッケージの依存解決を行い、その結果をOCI Image Indexとして1つのタグの下にまとめる形で実現されています。あるアーキテクチャにしか存在しないパッケージが混ざっている場合は、そのアーキテクチャの解決対象から外すことで一貫性を保ちます。

## SBOMの合成

apkoが生成するSBOMは、単にインストールしたAPKパッケージの一覧を並べたものではありません。各パッケージのメタデータやチェックサム、ライセンス情報を集約するのに加えて、パッケージの内部に同梱された情報（[SBOM composition](https://github.com/chainguard-dev/apko/blob/main/docs/sbom-composition.md)のドキュメントによれば`/var/lib/db/sbom/`配下のSPDXファイル）を検出した場合は、それを統合してより詳細な合成SBOMを作ります。

前章で見たmelangeは、ビルドしたAPKパッケージの内部にまさにこの形式でSBOM断片を埋め込んでいました。つまりapkoは、melangeが仕込んだ情報を取りこぼさずに引き継いでいます。apkoの方針として、パッケージから推測してデータを補完することはせず、確認できた情報だけを記録します。

## apkoが「消費専用」であること

apkoにはソースコードをコンパイルする手段がありません。独自のアプリケーションや、パッチを当てたパッケージが必要な場合は、前章までのmelangeでAPKパッケージとしてビルドしておき、それをapkoの`contents.packages`から参照できるローカルまたはリモートのAPKリポジトリに配置しておく必要があります。melangeが「作る」役割、apkoが「組み立てる」役割という分業は、この制約から生まれています。

次章では、実際に`apko.yaml`を書いてイメージを組み立てます。

[^s6]: [s6](https://skarnet.org/software/s6/index.html)は、Linuxコンテナ内でPID 1として動作し、複数プロセスの起動、監視、シグナル処理を担う軽量なプロセス監視ツール群です。[apkoのREADME](https://github.com/chainguard-dev/apko)は「apko supports using the s6 supervision suite to run multiple processes in a container without reaping or signalling issues」（apkoはs6監視スイートを使うことで、ゾンビプロセスの回収やシグナル処理の問題を起こさずにコンテナ内で複数プロセスを実行できる）と説明しています。コンテナ向けの配布形態としては[s6-overlay](https://github.com/just-containers/s6-overlay)が広く使われています。
