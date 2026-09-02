---
title: "おわりに"
---

本書は、Dockerfileベースのイメージビルドが抱える再現性とSBOMの課題（2章）から始まり、Wolfi（3章）、melange（4章と5章）、apko（6章と7章）というChaiguardスタックの解説、Chainguard Imagesの実運用（9章）まで辿ってきました。

## どこから始めるか

本書で扱ったすべてを一度に導入する必要はありません。既存のDockerfileをすぐに置き換えるのが難しい場合、まずはapkoだけを試すところから始められます。既存のベースイメージをChainguard Imagesに切り替えるだけでも、2章で挙げた攻撃対象領域の課題には対処できます。

自社で独自にビルドしているソフトウェアがあり、そのビルドプロセスの再現性やSBOMの正確さに課題を感じている場合は、そのビルドの一部をmelangeの`melange.yaml`として書き直すところから着手できます。既存のDockerfileの`RUN`命令をそのままmelangeの`pipeline`に移植することは難しくありませんし、組み込みアクションを使えば、複数のプロジェクトでビルド手順を共通化しやすくなります。

すでにGitHub Actionsのようなパイプラインでコンテナイメージをビルドしているチームであれば、9章で見たとおり、`melange build`と`apko build`（または`apko publish`）をワークフローの中に組み込むだけで、Chainguard自身が行っているのとほぼ同じ構成に近づけます。

## 本書の範囲を超えて

本書では扱いませんでしたが、Chainguardはmelangeとapkoに加えて、脆弱性情報を追跡する[Grype](https://github.com/anchore/grype)やSBOMの生成や検証を行うツールなど、周辺のOSSも公開しています。またBazelモノレポでアプリケーションを管理しているチーム向けには、9章で触れた[rules_apko](https://github.com/chainguard-dev/rules_apko)というBazel rulesも存在します。Wolfiのパッケージ定義自体も[wolfi-dev/os](https://github.com/wolfi-dev/os)で公開されており、実際のパッケージ定義がどう書かれているかを読むことは、melangeの`pipeline`をより実践的に理解する近道になります。本書がその入り口として役立てば幸いです。
