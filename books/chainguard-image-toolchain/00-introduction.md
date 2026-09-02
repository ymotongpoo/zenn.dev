---
title: "はじめに"
---

Chainguardは、コンテナイメージの脆弱性を減らすことに特化したセキュリティ企業です。同社が公開している[Chainguard Images](https://images.chainguard.dev/)は、既知のCVEをほぼ含まない**distroless**なイメージ群として知られており、Grafana Labsを含む多くの企業がベースイメージとして採用しています。たとえばGrafana Labsの[xk6](https://github.com/grafana/xk6/blob/3b5a796179b8f5e714fe25d9806e6ab44ea75e50/Dockerfile#L3)は、CVE対策のためにビルドイメージを`cgr.dev/chainguard/go`に切り替えています。

distrolessという言葉自体は目新しいものではありません。Googleの[distroless](https://github.com/GoogleContainerTools/distroless)プロジェクトが先行しており、シェルやパッケージマネージャーを含まない最小限のイメージという考え方はすでに広く知られています。Chainguardが独自なのは、その最小イメージを人手で都度削って作るのではなく、**melange**と**apko**という2つのOSSツールの組み合わせによって、ソースコードから機械的かつ再現可能に生成している点です。

本書はこの2ツールを順に追いながら、Chainguardのイメージビルドパイプラインがどう組み立てられているかを手元で確かめていきます。対象読者は、コンテナイメージを普段Dockerfileでビルドしていて、その再現性やSBOMの正確さに疑問を持ったことがあるエンジニアを想定しています。Alpine Linuxの経験は前提にしませんが、コンテナの基本的な仕組み（レイヤー、OCIイメージ形式）は既知として進めます。

## Chainguardがゼロからツールを作った理由

Chainguardは2021年10月に、Dan Lorenc、Matt Moore、Kim Lewandowski、Ville Aikas、Scott Nicholsの5名によって設立されました。全員がGoogleでKubernetesやSigstore、distrolessといったプロジェクトに携わってきた出身者です。設立を告知する[ブログ記事](https://www.chainguard.dev/unchained/introducing-chainguard-inc)は、会社のミッションを次のように述べています。

> Security in software supply-chains must be holistic; it cannot be bolted on. The easy way must be the secure way.
>
> （サプライチェーンにおけるセキュリティは全体的であるべきで、後付けであってはならない。簡単な方法が、そのまま安全な方法でなければならない。）

この記事は根拠として、[サプライチェーン攻撃が2021年に650%増加したというSonatypeの調査](https://www.sonatype.com/blog/2021-state-of-the-software-supply-chain)と、米国の[大統領令14028](https://www.federalregister.gov/documents/2021/05/17/2021-10460/improving-the-nations-cybersecurity)がサプライチェーンセキュリティを国家インフラへの脅威と位置付けた動きを挙げています。この時期には、[SolarWinds社の製品に対するサプライチェーン攻撃](https://www.cisa.gov/news-events/directives/ed-21-01-mitigate-solarwinds-orion-code-compromise-closed)や、[Apache Log4jの脆弱性Log4Shell](https://logging.apache.org/log4j/2.x/security.html)（CVE-2021-44228）が相次いで表面化しており、ソフトウェアの構成要素を後から正確に把握できないこと自体がリスクだという認識が業界に広がっていました。

顧客企業がdistrolessなイメージやSBOM、低CVEを重視する理由も、この延長線上にあります。[Chainguardのウェブサイト](https://www.chainguard.dev/about-us)では、FedRAMPやPCI DSS、CMMC 2.0、SOC 2といった規制枠組みへの対応を挙げ、自社イメージの導入によって平均97.6%のCVE削減と85%の攻撃対象領域削減が見込めるとしています。監査や規制対応の場面では、イメージの中身を「後から正確に説明できる」ことそのものが価値を持ちます。

この目的のために、Chainguardは既存のAlpine LinuxやUbuntu、Debianをそのまま使うのではなく、Wolfiという新しいディストリビューションを作りました。その理由は3章で改めて扱います。

## 本書で扱う2つのツールとその役割

2ツールはそれぞれ独立したGitHubリポジトリを持ちますが、お互いに強く連携しています。

- **melange**（[chainguard-dev/melange](https://github.com/chainguard-dev/melange)）：ソースコードをビルドし、Alpine Linux由来のパッケージ形式であるAPKを生成するツールです。
- **apko**（[chainguard-dev/apko](https://github.com/chainguard-dev/apko)）：APKパッケージだけをつかって、Dockerfileを使わずにOCIコンテナイメージを組み立てるツールです。

これに加えて、[**Wolfi**](https://github.com/wolfi-dev/os)というChainguardが管理するLinuxディストリビューションが土台となります。Wolfiのパッケージ群はすべてmelangeでビルドされており、apkoはこのWolfiのAPKリポジトリを主要な材料として使います。

図1に、ソースコードからコンテナイメージが公開されるまでの流れを示します。

![melangeとapkoの連携](/images/20260901-toolchain-overview.png)
*図1: ソースコードはmelangeによってAPKパッケージへとビルドされる。apkoはWolfiの公開パッケージと合わせてAPKだけからOCIイメージを組み立て、レジストリへ配布する。*

## 本書の構成

本書は概念の説明とハンズオンを交互に進めます。まず2章で、従来のDockerfileベースのイメージビルドが抱える課題を具体的に確認します。3章でWolfiというディストリビューションの位置付けを押さえたうえで、4章と5章でmelangeの設計とハンズオンを、6章と7章でapkoの設計とハンズオンを扱います。8章でこの2ツールがどう連携しているかを整理し、9章では、ここまで学んだ要素がChainguard Imagesの実運用でどう組み合わさっているかを確認します。10章で全体を振り返ります。

各ハンズオン章のコマンド例は、可能な範囲で実際に実行して確認したものです。実行できなかった箇所は、公式リポジトリのexamplesやドキュメントの記載である旨を明記します。
