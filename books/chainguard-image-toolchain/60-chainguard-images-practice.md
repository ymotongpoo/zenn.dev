---
title: "Chainguard Imagesの実運用"
---

ここまでの章で、melangeとapkoをそれぞれ動かしてきました。この章では、この2ツールがChainguard自身のイメージ配布でどのように組み合わさっているかを確認します。

## ビルドの実体はMakefileとCLI呼び出し

Wolfiのパッケージ定義を管理する[wolfi-dev/os](https://github.com/wolfi-dev/os)リポジトリを実際に確認すると、ビルドを駆動しているのはリポジトリ直下の`Makefile`です。`melange`と`apko`のコマンドラインツールを直接呼び出す形でビルドが進み、BazelのBUILDファイルやWORKSPACEファイルは存在しません。`.github/`配下にも、GitHub Actionsのワークフロー定義はなく、Chainguard社内の自動化ツールがOIDC経由でこのリポジトリへ書き込むための信頼設定が置かれているだけです。つまりBazelはもちろん、公開されたGitHub Actionsのワークフローにも依存していません。

つまり本書で確認してきた「melange.yamlを書いて`melange build`を実行し、apko.yamlを書いて`apko build`（または`apko publish`）を実行する」という手順は、簡略化した例え話ではなく、Chainguardが実際に行っていることとほぼ同じです。規模の違いはあっても、パイプラインの骨格は5章と7章のハンズオンで手を動かしたものと変わりません。

## 自分のGoアプリケーションに応用する

ここまではGNU Helloという既存のCプログラムを題材にしてきましたが、自分のアプリケーションに応用する場合を考えます。典型的なGoアプリケーションのDockerfileは、次のようなマルチステージビルドで書かれることが多いはずです。

```dockerfile
FROM golang:1.23 AS builder
WORKDIR /src
COPY . .
RUN go build -o /out/app .

FROM scratch
COPY --from=builder /out/app /app
ENTRYPOINT ["/app"]
```

これをmelangeとapkoに置き換えると、ビルド段階はmelangeの`go/build`アクションが、`FROM scratch`以降はapkoが、それぞれ担当します。melangeの[examples/go-build.yaml](https://github.com/chainguard-dev/melange/blob/main/examples/go-build.yaml)を土台にすると、`melange.yaml`は次のようになります。

```yaml
package:
  name: hello-go
  version: 0.0.1
  epoch: 0
  description: "A project that will greet the world infinitely"

environment:
  contents:
    keyring:
      - https://packages.wolfi.dev/os/wolfi-signing.rsa.pub
    repositories:
      - https://packages.wolfi.dev/os

pipeline:
  - uses: git-checkout
    with:
      repository: https://github.com/puerco/hello.git
      expected-commit: a73c4feb284dc6ed1e5758740f717f99dcd4c9d7
      tag: v${{package.version}}

  - uses: go/build
    with:
      packages: .
      output: hello-go
```

`git-checkout`でソースを取得し、`go/build`にビルド対象のパッケージ（`packages: .`）と出力するバイナリ名（`output: hello-go`）を渡すだけです。Dockerfileの`RUN go build`に相当する処理は、この`go/build`アクション1つに集約されています。ビルドコマンドは5章と同じです。

```shell
docker run --privileged --rm -v "${PWD}":/work \
  cgr.dev/chainguard/melange build hello-go.yaml \
  --arch x86_64 --signing-key melange.rsa
```

できあがった`hello-go`のAPKパッケージを、apkoでイメージに組み立てます。`apko.yaml`は7章の例とほぼ同じ形です。

```yaml
contents:
  keyring:
    - https://packages.wolfi.dev/os/wolfi-signing.rsa.pub
    - melange.rsa.pub
  repositories:
    - https://packages.wolfi.dev/os
    - "@local ./packages"
  packages:
    - wolfi-baselayout
    - hello-go@local

entrypoint:
  command: /usr/bin/hello-go

accounts:
  run-as: 65532

archs:
  - x86_64
```

`FROM scratch`で最小限のファイルだけを積んでいたDockerfileの後半部分が、`wolfi-baselayout`と自分のバイナリだけを列挙する`contents.packages`に置き換わっています。Goのバイナリは静的リンクされることが多いため、実行に必要なランタイムライブラリを個別に指定する必要はほとんどありません。あとは7章と同じ`apko build`（または`apko publish`）で、Dockerfileを1行も書かずにイメージが完成します。

## 毎日ソースから再ビルドされる仕組み

Chainguard Images（[chainguard-images](https://github.com/chainguard-images)組織で公開されているイメージ群）は、Wolfiのパッケージ定義とapkoの設定ファイルを起点に、[毎日ソースから再ビルドされる](https://www.chainguard.dev/containers)運用がとられています。3章で確認したとおり、Wolfiのパッケージはすべてmelangeでビルドされているため、上流のソフトウェアに脆弱性修正が入れば、Wolfi側のパッケージ定義を更新してmelangeで再ビルドするだけで、その修正を反映したAPKパッケージが手に入ります。apkoはそのAPKパッケージ群を組み合わせてイメージを再構成するだけなので、ビルドのたびに最新のパッケージ状態を反映した、CVEの少ないイメージを配布し続けられます。

この運用が成立する背景には、2章で確認した課題の裏返しがあります。Dockerfileベースのアプローチでは、ベースイメージの中身がどう構成されているか外部から機械的に把握しづらく、脆弱性の有無を正確に追跡するにはスキャンに頼らざるを得ませんでした。melangeとapkoの組み合わせでは、イメージの中身がAPKパッケージの列挙として宣言されており、SBOMもビルドプロセスの内部情報から生成されるため、どのバージョンのどのパッケージが含まれているかを常に正確に把握できます。

## Bazelモノレポで使う場合の選択肢

ここまで見てきたとおり、Chainguard自身のビルドパイプラインにBazelは登場しません。一方で、自社のアプリケーションをBazelモノレポで管理しているチームが、Chainguard Imagesをベースイメージとして取り込みたい場合の選択肢として、Chainguardは[rules_apko](https://github.com/chainguard-dev/rules_apko)というBazel rulesを公開しています。これはapkoの実行をBazelのビルドグラフに統合するためのラッパーであり、Chainguard自身の内部ビルドとは別に、Bazelを使う外部の利用者向けに用意された統合レイヤーです。Bazelモノレポでアプリケーションを管理していない読者にとっては、本書で扱った範囲の外にある話になります。

## エコシステム全体を俯瞰する

本書で扱った要素の関係を改めて整理すると、次のようになります。

| 要素 | 役割 |
|---|---|
| Wolfi | APKパッケージの供給元となるLinuxディストリビューション |
| melange | ソースコードからAPKパッケージをビルドするツール。Wolfiのパッケージもすべてこれでビルドされる |
| apko | APKパッケージだけからOCIイメージを組み立てるツール |

これらは別々のGitHubリポジトリとして開発されていますが、APKパッケージという共通のフォーマットと、SBOMやチェックサムという共通の検証手段によって、1つの一貫したパイプラインとして機能しています。次章では、本書全体を振り返り、自分のプロジェクトに導入するとしたらどこから手を付けるべきかを考えます。
