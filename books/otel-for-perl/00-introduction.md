---
title: "はじめに"
---

本書は、YAPC::Tokyo 2026（2026年11月28日）での筆者の登壇の解説資料です。登壇のタイトルは「OpenTelemetryのPerl実装にいまこそ必要なもの」です。

[OpenTelemetry](https://opentelemetry.io/ja/)は、アプリケーションを外から観測するためのデータ（**テレメトリー**）を扱うオープンソースのプロジェクトです。テレメトリーの形式と、それを生成して送る仕組みを定めています。テレメトリーは、処理の流れを区間の木で表すトレース、数値の時系列であるメトリクス、出来事の記録であるログの3種類です。OpenTelemetryはそれぞれを**シグナル**と呼びます。Java、Go、Python、Rubyなどには、プロジェクトが保守する公式の実装があります。

Perlは、その公式の実装を持たない言語の1つです。公式ドキュメントの[その他の言語](https://opentelemetry.io/ja/docs/languages/other/)のページでは、Lua、Juliaと並んでPerlが挙がっています。いずれも、SIG（言語ごとの実装を保守する作業グループ）の設立が要望されている言語です。一方、CPANにはサードパーティの実装があります。APIの[OpenTelemetry](https://metacpan.org/dist/OpenTelemetry)と、SDKの[OpenTelemetry::SDK](https://metacpan.org/dist/OpenTelemetry-SDK)です。

本書の問いは、このCPANの実装を実際のPerlのWebアプリケーションに組み込んだとき、何が動いて何が足りないのかです。READMEや機能の一覧を読むだけでは、この問いに答えられません。トレースの生成と送信は動くと書かれていても、PSGIサーバーの上で送信がどう振る舞うかまでは書かれていないからです。計装のもう1つの方法として、[OpenTelemetry eBPF Instrumentation](https://opentelemetry.io/ja/docs/zero-code/obi/)（以下OBI）も同じアプリケーションで試します。OBIは、コードを変えずにLinuxのeBPFでアプリケーションを観測します。

素材は、筆者が用意した小さな2つのサービスです。集計結果を返すPerlのPSGIアプリケーションが、為替レートを返すGoのサービスを呼ぶ構成です。このPerlのアプリケーションに、CPANの実装を組み込んだ場合と、OBIで外から観測した場合を比べます。届いたテレメトリーは、[OpenTelemetry Collector](https://opentelemetry.io/ja/docs/collector/)で受け取ったまま保存して確かめました。最初に組み込んだとき、CollectorにはGoのサービスのスパンだけが届き、Perlのスパンは1件もありませんでした。本書の後半の多くは、その理由と対処に充てています。

:::message
本書のコードと測定値は、2026年10月7日と19日に次の環境で確かめたものです。SDKを使う測定は、19日にSDK 0.100で取り直しました。

- ホスト：Linux 7.0.0（Ubuntu、x86_64、4コア）、Docker 29.0.0
- Perl 5.44.0（Docker公式イメージ `perl:5.44.0`）、Carton 1.0.35
- CPAN：OpenTelemetry 0.039、OpenTelemetry::SDK 0.100、OpenTelemetry::Exporter::OTLP 0.021、Plack::Middleware::OpenTelemetry 0.262410、Plack 1.0054、Starman 0.4018、Twiggy 0.1026、IO::Async 0.805
- Go 1.27.1、OpenTelemetry Go v1.47.0、otelhttp v0.72.0
- OBI v0.14.0（伝搬の確認だけv1.0.0-rc.1も使用）
- otel/opentelemetry-collector-contrib 0.162.0、grafana/otel-lgtm 0.32.1

コードと実験のスクリプトは[ymotongpoo/otel-for-perl](https://github.com/ymotongpoo/otel-for-perl)にあります。

CPANの実装はいまも活発に開発されています。SDKの0.100は、ログに対応して本書の執筆中にリリースされた安定版です。本書で扱う不具合や未実装の機能は、新しいリリースで変わっている可能性があります。
:::

## 本書の読み方

想定する読者は、PerlでWebアプリケーションを書いたり運用したりしている人と、OpenTelemetryの実装に参加したい人です。OpenTelemetryを使った経験は前提にしません。PlackとPSGIの基本は知っているものとします。

2章では、題材のアプリケーションを動かし、外から測った応答時間だけでは遅い原因を見分けられないことを確かめます。そのうえで、トレース、スパン、トレースコンテキストを定義します。3章は、Perlの実装の公式な位置づけと、CPANにある配布物の関係です。

4章から6章では、CPANの実装を組み込んでいきます。4章はSDKを有効にしてスパンを送る方法で、5章はPlackのミドルウェアと子スパンです。6章ではHTTPクライアントの計装と、Goのサービスへの伝搬を扱います。7章では、トレース以外のシグナルであるログとメトリクスの実装状況を確かめます。

8章は、Perlのスパンが届かなかった理由です。SDKの送信の仕組みとPSGIサーバーの実行方式の組み合わせを、2種類のPSGIサーバーで測りました。9章ではOBIで同じアプリケーションを観測します。10章はSDKとOBIの比較です。11章で、実験で見つかった課題を修正先ごとに整理し、着手できる作業を示します。巻末の付録は参考文献の一覧です。

4章から6章の手順は、8章で扱う問題を避ける構成で書いています。その構成を選んだ理由は8章で説明するので、手順だけを先に追っても動かせます。
