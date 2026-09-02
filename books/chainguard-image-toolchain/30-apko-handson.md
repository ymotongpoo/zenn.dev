---
title: "apkoでコンテナイメージを組み立てる"
---

5章で`hello`のAPKパッケージをビルドしました。この章では、そのAPKとWolfiの公開パッケージを組み合わせて、実際に動くコンテナイメージを組み立てます。

## apko.yamlを書く

作業ディレクトリに、次の内容で`apko.yaml`を作成します。

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
    - hello@local

entrypoint:
  command: /usr/bin/hello

accounts:
  run-as: 65532

archs:
  - x86_64
```

`repositories`にはWolfiの公開リポジトリと、5章でmelangeが出力したローカルの`./packages`ディレクトリの両方を指定しています。ローカルリポジトリには`@local`という名前を付け、`packages`欄では`hello@local`のように名前付きリポジトリを明示してパッケージを指定します。`keyring`にはWolfi公式の署名鍵と、5章で自分が生成した`melange.rsa.pub`の両方を並べます。ローカルでビルドしたAPKも、Wolfiの公開パッケージと同様に署名検証の対象になるためです。

`accounts.run-as`にUIDを指定すると、コンテナはrootではなくそのUIDで実行されます。多くのChainguard Imagesも、既定の実行ユーザーを非rootに設定しています。

## イメージをビルドする

apkoも`cgr.dev/chainguard/apko`のDockerイメージとして配布されています。次のコマンドでOCIイメージをtarballとして書き出します。

```shell
docker run --rm -v "${PWD}":/work cgr.dev/chainguard/apko \
  build apko.yaml hello:latest hello.tar
```

引数は順に、設定ファイル、イメージに付けるタグ、出力先のtarballファイル名です。生成された`hello.tar`は、`docker load`でローカルのDockerデーモンに読み込めます。apkoはアーキテクチャを1つしか指定していなくても常にOCI Image Indexとして出力するため、`docker load`はタグの末尾にアーキテクチャ名を付けます。今回は`hello:latest-amd64`という名前で読み込まれます。

```shell
docker load < hello.tar
docker run --rm hello:latest-amd64
```

実行すると、GNU Helloが標準の挨拶文を出力します。Dockerfileを一切書かずに、宣言だけからここまで到達したことになります。

## レジストリに直接publishする

`apko build`はローカルのtarballを経由しますが、CI環境ではDockerデーモンを介さずレジストリへ直接pushしたいことがよくあります。この場合は`apko publish`を使います。

```shell
docker run --rm -v "${PWD}":/work cgr.dev/chainguard/apko \
  publish apko.yaml registry.example.com/hello:latest
```

`publish`はOCIイメージをレジストリのAPIで直接送信するため、ビルドとpushを1コマンドで完結できます。

認証情報は、`apko publish`自体には`--username`のような専用フラグがなく、[go-containerregistry](https://github.com/google/go-containerregistry)の`authn.DefaultKeychain`という標準的な仕組みをそのまま利用します。これは`docker login`が書き込む`~/.docker/config.json`（や各クラウドのcredential helper）を読み取る仕組みで、[apkoのREADME](https://github.com/chainguard-dev/apko)も「事前に`docker login`で認証情報をキーチェーンに保存しておくことを前提とする」と説明しています。加えてpush先が`ghcr.io`の場合は、GitHub Actions上で環境変数`GITHUB_TOKEN`が設定されていれば、`docker login`なしでも自動的に認証されます。

## SBOMを確認する

apkoはビルドと同時にSBOMを生成します。ビルド時に`--sbom-path`のようなオプションで出力先を指定できるほか、生成済みのイメージからSBOMを取り出して確認することもできます。6章で説明したとおり、このSBOMには5章でmelangeが`hello`パッケージに埋め込んだSBOM断片の情報が引き継がれています。実際にSBOMの中身を`jq`などで開いてみると、`hello`パッケージのバージョンやライセンス情報が、Wolfi由来の他のパッケージと並んで記録されていることが確認できます。

## Dockerfileとの違いを振り返る

ここまでの手順を振り返ると、Dockerfileとの違いは次の3点に集約されます。

- パッケージのインストールが`apk`の依存解決に固定されているため、ビルドのたびにリポジトリの索引を参照しても、バージョンが宣言（またはロックファイル）に従って決まること
- 任意コマンドを実行する手段がないため、イメージの中身がAPKパッケージの組み合わせだけで説明できること
- SBOMがビルドプロセスの内部情報から合成されるため、後付けのスキャンより正確であること

次章では、melangeとapkoの連携について、SBOMの引き継ぎと再現性の関係を整理します。
