---
title: "melangeの設計"
---

[melange](https://github.com/chainguard-dev/melange)は、宣言的なパイプラインの定義からAPKパッケージをビルドするGo製のCLIツールです。[README](https://github.com/chainguard-dev/melange)ではこのツールを「secure software factory」の実現手段と位置付けています。ビルドの各手順を宣言として書き下し、実行環境をサンドボックス化することで、パッケージがどう作られたかを機械的に検証できる状態を保つという考え方です。

## melange.yamlの構造

melangeのビルド定義は1つのYAMLファイル（慣習的に`melange.yaml`という名前が使われますが、任意のファイル名を指定できます）に書きます。主要なトップレベルフィールドは次のとおりです。

| フィールド | 役割 |
|---|---|
| `package` | パッケージ名、バージョン、epoch、説明、ライセンス、実行時の依存関係などのメタデータ |
| `environment` | ビルド環境の定義。`contents.repositories`と`contents.packages`で、ビルド時に使うAPKリポジトリとパッケージを指定する |
| `pipeline` | ビルド手順の並び。組み込みの`uses`アクション、または生のシェルコマンドを書く`runs`で構成する |
| `subpackages` | 本体とは別にビルドする派生パッケージ（`-doc`や`-dev`など）。個別に`pipeline`や`dependencies`を持てる |
| `test` | ビルドしたパッケージを検証するためのパイプライン |

`pipeline`の各ステップは、`uses: fetch`のようにあらかじめ用意されたアクションを呼び出すか、`runs: |`で任意のシェルコマンドを書くかのどちらかです。組み込みアクションの実体は、[pkg/build/pipelines](https://github.com/chainguard-dev/melange/tree/main/pkg/build/pipelines)ディレクトリに1アクション1YAMLファイルとして定義されています。ソース取得の`fetch`、`autoconf/configure`と`autoconf/make`のようなビルドシステムのラッパー、Go向けの`go/build`、パッチ適用の`patch`、デバッグシンボルを取り除く`strip`などがあります。組み込みアクションを使うことで、同じ種類のビルド作業を複数のパッケージ定義の間で共通化できます。

変数展開には`${{package.version}}`や`${{targets.destdir}}`、`${{build.arch}}`のような記法を使います。これにより、バージョン番号やビルド先ディレクトリをパイプラインの中で直接参照できます。

表だけではわかりづらいので、[melangeのREADME](https://github.com/chainguard-dev/melange)に載っているquickstart例の骨格を見てみます。

```yaml
package:
  name: hello
  version: 2.12
  epoch: 0
  description: "the GNU hello world program"

environment:
  contents:
    repositories:
      - https://dl-cdn.alpinelinux.org/alpine/edge/main
    packages:
      - alpine-baselayout-data
      - busybox
      - build-base

pipeline:
  - uses: fetch
    with:
      uri: https://ftp.gnu.org/gnu/hello/hello-${{package.version}}.tar.gz
      expected-sha256: cf04af86dc085268c5f4470fbae49b18afbc221b78096aab842d934a76bad0ab
  - uses: autoconf/configure
  - uses: autoconf/make
  - uses: autoconf/make-install
  - uses: strip
```

`package`に名前とバージョンを、`environment.contents`にビルド環境として使うAlpineのリポジトリとパッケージを、`pipeline`にソース取得からインストールまでの手順を書いています。この例を実際に動かすところは、次章のハンズオンで扱います。

## ビルドのサンドボックス化

melangeは、パイプラインを実行するたびにクリーンなAPKルート環境を用意し、その中でビルドを行います。実行環境（ランナー）は`--runner`フラグで`bubblewrap`、`docker`、`qemu`から選択でき、既定値はプラットフォームによって変わります。`bubblewrap`はLinuxの名前空間分離機能を使った軽量なサンドボックスで、コンテナの中で実行する場合はLinux capabilityの要求上、`--privileged`フラグが必要になります。

マルチアーキテクチャ対応は、QEMUのユーザーモードエミュレーションによって実現されています。クロスコンパイル環境を個別に用意しなくても、x86_64やarm64、ppc64leなど異なるアーキテクチャ向けのビルドを同じホスト上で実行できます。

## SBOMと来歴の記録

melangeはビルドのたびにSPDX形式のSBOMを生成し、成果物のパッケージ内に埋め込みます。ビルドプロセスの内部で生成するため、後からファイルシステムをスキャンして推測する方式（2章で触れた課題）とは異なり、パイプラインが実際に何を取得し何をインストールしたかに基づいた記録になります。

さらに`--generate-provenance`フラグを指定すると、[SLSA](https://slsa.dev/)形式のprovenance情報を`.attest.tar.gz`として別途出力できます。provenanceには、どのビルド定義から、どの環境で、いつビルドされたかという来歴情報が記録されます。

## 署名という前提

melangeでビルドしたAPKは、そのままでは信頼できるパッケージとして扱われません。`melange keygen`で生成した鍵ペアを使って署名することで、そのパッケージが特定のビルド主体によって作られたことを検証可能にします。この署名の仕組みは、Wolfiのような公開APKリポジトリを構成するうえで欠かせない要素です。実際の鍵生成と署名の手順は、次章のハンズオンで確認します。
