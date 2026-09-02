---
title: "melangeでAPKパッケージをビルドする"
---

前章で確認した仕組みを、実際にコマンドを動かしながら確認します。melangeはGoの単一バイナリですが、ビルドにはLinuxの名前空間分離機能を使うため、Docker上で実行する`cgr.dev/chainguard/melange`イメージを使うのが最も手軽です。以降の手順は、[melangeリポジトリのREADME](https://github.com/chainguard-dev/melange)が示すクイックスタートに沿っています。

## 署名鍵を用意する

melangeでビルドしたAPKは署名が必須です。まず作業ディレクトリで鍵ペアを生成します。

```shell
docker run --rm -v "${PWD}":/work cgr.dev/chainguard/melange keygen
```

実行すると、カレントディレクトリに秘密鍵`melange.rsa`と公開鍵`melange.rsa.pub`が作られます。この鍵は以降のビルドすべてで再利用します。

## ビルド定義を用意する

melangeの[README](https://github.com/chainguard-dev/melange)に載っているquickstart例は、4章で見たとおりビルド環境にAlpine Linuxの公式リポジトリを使っています。ただし本書では、この後の7章で組み立てるAPKをWolfiベースのapkoイメージに組み込むため、ビルド環境もWolfi自身のリポジトリに揃えます。3章で確認したとおり、Alpine Linuxは標準Cライブラリに`musl`を、Wolfiは`glibc`を使っており、Alpine環境でビルドしたバイナリはWolfiのイメージにそのまま乗せられません。READMEの例をWolfi向けに書き換えると、次のようになります。

```yaml
package:
  name: hello
  version: 2.12
  epoch: 0
  description: "the GNU hello world program"
  copyright:
    - license: GPL-3.0-or-later

environment:
  contents:
    keyring:
      - https://packages.wolfi.dev/os/wolfi-signing.rsa.pub
    repositories:
      - https://packages.wolfi.dev/os
    packages:
      - wolfi-base
      - build-base
      - ca-certificates-bundle

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

`environment.contents`でビルド環境自体をWolfiのパッケージ（3章で見た最小構成の`wolfi-base`と、ビルドツール一式の`build-base`、HTTPS通信に使う`ca-certificates-bundle`）から組み立て、`pipeline`でソース取得からビルド、インストール、デバッグシンボルの除去までを順に実行しています。`autoconf/configure`や`autoconf/make`は、`./configure && make`に相当する処理を共通化した組み込みアクションです。`ca-certificates-bundle`を外すと、`fetch`アクションが`https://ftp.gnu.org`との通信でTLS証明書を検証できずに失敗するため、必須のパッケージです。

## ビルドを実行する

用意した鍵と定義ファイルを使ってビルドします。

```shell
docker run --privileged --rm -v "${PWD}":/work \
  cgr.dev/chainguard/melange build hello.yaml \
  --arch x86_64 --signing-key melange.rsa
```

`--privileged`はコンテナ内でmelangeがサンドボックス（既定では`bubblewrap`）を構成するために必要です。ビルドが成功すると、カレントディレクトリの`packages/x86_64/`以下に、署名済みの`hello-2.12-r0.apk`と、リポジトリの索引ファイルである`APKINDEX.tar.gz`が生成されます。

## 生成物を確認する

生成された`.apk`は、実体としては署名情報、メタデータ、実際のファイル一式を含むtarアーカイブです。`tar`コマンドで中身を確認できます。

```shell
tar tzf packages/x86_64/hello-2.12-r0.apk
```

パッケージの中には、実行ファイルに加えて`var/lib/db/sbom/`配下にSPDX形式のSBOMファイルが含まれています。このSBOMは4章で触れたとおり、ビルドプロセスの内部で生成されたものです。melangeのテストデータに含まれる[実際のSBOM](https://github.com/chainguard-dev/melange/blob/main/pkg/build/testdata/goldenfiles/sboms/sed-4.9-r8.spdx.json)（`sed`パッケージのもの）を抜粋すると、次のような構造をしています。

```json
{
  "SPDXID": "SPDXRef-DOCUMENT",
  "name": "apk-sed-4.9-r8",
  "spdxVersion": "SPDX-2.3",
  "creationInfo": {
    "creators": ["Tool: melange (devel)", "Organization: Chainguard, Inc"]
  },
  "documentDescribes": ["SPDXRef-Package-apk-sed-4.9-r8"],
  "packages": [
    { "SPDXID": "SPDXRef-OperatingSystem", "name": "wolfi", "primaryPackagePurpose": "OPERATING-SYSTEM" },
    {
      "SPDXID": "SPDXRef-Package-apk-sed-4.9-r8",
      "name": "sed",
      "versionInfo": "4.9-r8",
      "licenseDeclared": "GPL-3.0-or-later",
      "primaryPackagePurpose": "APPLICATION"
    },
    { "SPDXID": "SPDXRef-Package-Melange-testdata-buildC95configs-sed.yaml-c0ffee", "primaryPackagePurpose": "INSTALL" },
    { "SPDXID": "SPDXRef-Package-Source-git.savannah.gnu.org...", "primaryPackagePurpose": "SOURCE" }
  ]
}
```

`packages`配列が4種類のエントリで構成されている点に注目してください。パッケージそのもの（`APPLICATION`）、それを生成したビルド定義（`INSTALL`）、取得元のソースコード（`SOURCE`）、そしてOSとしてのコンテキスト（`OPERATING-SYSTEM`）です。ビルドプロセスの内部で何を取得し何をインストールしたかがそのまま記録されるため、後からファイルシステムをスキャンして推測する方式より正確な情報になります。

`--generate-provenance`フラグを追加すると、ビルドと同時にSLSA形式のprovenanceファイルが出力されます。CI環境で自動ビルドする場合は、この来歴情報を保存しておくことで、後から特定のパッケージがどの入力からビルドされたかを追跡できます。

## サブパッケージとテスト

`melange.yaml`に`subpackages`を追加すると、本体とは別のAPKを同じビルドから作れます。たとえばドキュメントだけを含む`hello-doc`を分離する場合、次のように書きます。

```yaml
subpackages:
  - name: hello-doc
    pipeline:
      - uses: split/manpages
```

また`test`フィールドに動作確認のパイプラインを書いておくと、`melange test`コマンドでビルド結果を検証できます。melangeのexamplesにある`crane`パッケージのテスト定義（抜粋）が[分かりやすい例](https://github.com/chainguard-dev/melange/blob/main/examples/test-xcover.yaml)です。

```yaml
test:
  environment:
    contents:
      packages:
        - jq
  pipeline:
    - name: Verify Crane installation
      runs: |
        crane version || exit 1
        crane --help
    - name: Fetch and verify manifest
      runs: |
        crane manifest chainguard/static | jq '.schemaVersion' | grep '2' || exit 1
```

ビルドした`crane`コマンドが実際に動くか、さらにレジストリと通信してマニフェストを正しく取得できるかまで検証しています。このパターンは、大規模なパッケージ定義集であるWolfiのリポジトリでも広く使われています。

次章では、ここで作った`hello`のAPKと、Wolfiが公開しているAPKを組み合わせて、実際にコンテナイメージを組み立てます。
