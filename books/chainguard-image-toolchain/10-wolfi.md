---
title: "Wolfi OSとAPKパッケージ"
---

melangeとapkoの説明に入る前に、両ツールが共通の材料として扱う**Wolfi**を確認します。Wolfiは、Chainguardが開発するLinuxディストリビューションです。パッケージ管理には、Alpine Linuxが採用しているAPK形式を使っています。

## 「undistro」という位置付け

WolfiのGitHubリポジトリ[wolfi-dev/os](https://github.com/wolfi-dev/os)は、自身を「Linux undistro」と説明しています。一般的なディストリビューションが特定のカーネルバージョンやinit方式、デスクトップ環境まで含めた完結したOSを提供するのに対し、Wolfiはコンテナイメージの材料として使われることを前提にした、パッケージ群とビルド基盤だけを提供する存在です。

Alpine Linuxは軽量さを理由にコンテナのベースイメージとして広く使われてきましたが、標準Cライブラリに`musl`を採用しているため、`glibc`を前提にビルドされたバイナリがそのままでは動かないことがあります[^musl]。Wolfiは`glibc`ベースであるため、既存のLinuxバイナリとの互換性を保ちながら、Alpine由来のAPKパッケージ管理の仕組みを利用できます。

[^musl]: https://aws.amazon.com/jp/builders-flash/202502/base-img-for-container-minimization/ も参照のこと。

## なぜAlpineやUbuntuをそのまま使わなかったのか

1章で触れたように、ChainguardはAlpine LinuxやUbuntu、Debianを使うのではなく、Wolfiという新しいディストリビューションを作りました。この判断の理由を、Chainguardの公式ブログ記事「[Reimagining the Linux distro with Wolfi](https://www.chainguard.dev/unchained/reimagining-the-linux-distro-with-wolfi)」から引用します。

> Linux distributions — such as Red Hat and Ubuntu — haven't changed much in the past couple of decades. They were originally designed for running on servers in a physical rack.
>
> （Red HatやUbuntuのようなLinuxディストリビューションは、この十数年ほとんど変わっていません。それらはもともと物理ラック上のサーバーで動かすために設計されたものです。）

この記事は続けて、コンテナという実行環境が、その設計前提とそもそも噛み合わないと指摘します。

> In a container, you're generally only running a single application, so you need much less "stuff." Static binaries are often a better solution than shared libraries. ... Both of these things are contrary to the founding principles of many Linux distributions.
>
> （コンテナでは通常、単一のアプリケーションしか動かさないため、必要な「もの」ははるかに少なくて済みます。共有ライブラリより静的バイナリの方が優れた選択であることも多い。……このどちらもが、多くのLinuxディストリビューションの設計原則とは相容れません。）

汎用ディストリビューションのパッケージは、サーバー上で複数のアプリケーションが共存し、ライブラリを共有することを前提に構成されています。コンテナでは1つのイメージに1つのアプリケーションしか載せないことが多く、この前提に沿う理由がありません。既存のディストリビューションのパッケージをそのまま流用すると、コンテナでは使わない機能や依存関係まで持ち込むことになり、2章で触れた攻撃対象領域の課題につながります。

もう1つの理由として、この記事は独自のディストリビューションを持つことの実務上の利点も挙げています。

> Having a distro like Wolfi also meant that we could issue security advisories, which are used by scanners and similar when identifying vulnerabilities in containers.
>
> （Wolfiのようなディストリビューションを持つことは、コンテナ内の脆弱性を特定する際にスキャナーなどが利用するセキュリティ勧告を、自ら発行できることも意味しました。）

既存のディストリビューションのパッケージをそのまま使う場合、脆弱性情報の発行元もそのディストリビューションに依存します。Wolfi自身がディストリビューションとしてセキュリティ勧告を発行できることは、apkoが生成するSBOMやスキャンツールが、脆弱性の有無をWolfiという単一の情報源に基づいて正確に判断できることにつながります。

## カーネルとビルド環境の起点

ここまでで「Wolfiとは何を提供するディストリビューションか」を見てきましたが、そもそもコンテナにOSカーネルは含まれません。コンテナはLinuxカーネルの`namespaces`（プロセス空間やネットワークなどの分離）と`cgroups`（リソース制限）を使って、ホストのカーネルを共有したままプロセスを隔離実行する仕組みです。Wolfiベースのイメージも例外ではなく、コンテナの中で`uname -a`を実行すると、返ってくるのはWolfiのカーネルではなく、実行しているホスト（やホストと同じカーネルを積んだVM）のカーネルバージョンです。つまり「Wolfiのカーネル」という概念自体が存在しません。

では、Wolfiにおける「これ以上分解できない最小の土台」は何かというと、`wolfi-base`というパッケージです。[wolfi-base.yaml](https://github.com/wolfi-dev/os/blob/main/wolfi-base.yaml)の定義を見ると、このパッケージ自体はファイルを1つも持たない空のメタパッケージで、実体は`dependencies.runtime`に列挙された3つのパッケージだけです。

```yaml
package:
  name: wolfi-base
  dependencies:
    runtime:
      - apk-tools
      - busybox
      - wolfi-keys
```

`apk-tools`がAPKパッケージマネージャー本体、`busybox`がシェルやcoreutils相当のコマンド一式、`wolfi-keys`が署名検証用の公開鍵です。この3つさえあれば、あとは`apk`コマンドで必要なパッケージを追加していける状態になります。

ここでもう1つ、素朴な疑問が残ります。パッケージをビルドするmelange自体、ビルド環境をAPKパッケージから組み立てます（4章で扱う`environment.contents`です）。では、その最初のビルド環境はどうやって用意するのでしょうか。これは「ビルドするための環境自体もパッケージからビルドする」という、鶏と卵のような問題です。

この点について、公式にまとまった解説文書があるわけではありませんが、実装からは次の2段構えで解決していることが読み取れます。1つは、Alpine Linuxがすでに持っている既存のAPKエコシステムを種として使う方法です。実際、melangeのREADMEに載っている例のビルド環境は、Wolfiではなく`https://dl-cdn.alpinelinux.org/alpine/edge/main`というAlpine公式リポジトリを直接指定しています。もう1つは、[wolfi-dev/os](https://github.com/wolfi-dev/os)リポジトリに`git-bootstrap.yaml`や`cmake-bootstrap.yaml`のような`*-bootstrap.yaml`が複数存在する仕組みです。コンパイラやツールチェーンのように複雑なパッケージは、まず簡易版をビルドし、その簡易版を使って本番版をビルドするという段階的な自己ホスト化で、この鶏と卵の問題を避けています。

## パッケージはすべてmelangeでビルドされている

Wolfiのパッケージ定義は[wolfi-dev/os](https://github.com/wolfi-dev/os)リポジトリに置かれており、`curl.yaml`や`openssl.yaml`のように、パッケージごとに1つの`melange.yaml`が対応します。つまりWolfiは、汎用ディストリビューションのように既存パッケージを取り込んで再パッケージングしているのではなく、必要なソフトウェアをソースコードからmelangeで都度ビルドして提供しています。ビルド済みのAPKは署名され、`https://packages.wolfi.dev/os`のAPKリポジトリとして公開されます[^repo]。

[^repo]: このURLをブラウザで直接開くと、`NoSuchKey`というエラーが返ってきます。これは設定の誤りではなく、GCS（Google Cloud Storage）バケットの仕様上の挙動です。`https://packages.wolfi.dev/os`は「os」という名前の1つのオブジェクトを指しているわけではなく、`https://packages.wolfi.dev/os/x86_64/APKINDEX.tar.gz`のように、apkやapko、melangeが具体的なファイルへアクセスするための接頭辞（プレフィックス）です。バケットの中身を一覧したい場合は、末尾を付けない`https://packages.wolfi.dev/`にアクセスすると、パッケージ一覧を含むXMLが返ってきます。

melangeの詳しい仕組みは4章で扱いますが、この時点で押さえておきたいのは「Wolfiのパッケージ = melangeのビルド成果物」という関係です。次章以降でmelangeを学ぶことは、そのままWolfiのパッケージがどう作られているかを学ぶことに繋がります。

## apkoから見たWolfi

apkoは`apko.yaml`の`contents.repositories`にAPKリポジトリのURLを指定することで、そこからパッケージを取得してイメージを組み立てます。Chainguard Imagesの多くは、この`repositories`にWolfiの公開リポジトリを指定し、`contents.packages`に必要なパッケージ（`wolfi-base`や個別のランタイムなど）を並べる形で定義されています。apkoの詳しい設定は6章で扱います。

まとめると、WolfiはAPKパッケージの供給元であり、melangeがその供給を担うビルドツール、apkoがその供給されたパッケージを消費してイメージを組み立てるツールという関係になります。次章からは、この関係の出発点であるmelangeを見ていきます。
