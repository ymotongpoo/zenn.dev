---
title: "PerlのOpenTelemetry実装の現在地"
---

## 公式プロジェクトとしての位置づけ

PerlでOpenTelemetryを使おうと公式ドキュメントを開くと、言語別のページにPerlが無いことに気づきます。言語別のページに並ぶのは、プロジェクトが実装を保守している言語です。それ以外の言語は、[その他の言語](https://opentelemetry.io/ja/docs/languages/other/)のページにまとめられています。

このページによれば、OpenTelemetryの仕様はどの言語でも実装できるように作られています。公式でない実装は、レジストリに載せられます。新しい言語の実装を公式のものにする手順は、issueを立ててSIGの設立への関心を集めることです。SIGは、言語ごとの実装を保守するOpenTelemetryの作業グループです。2026年10月7日の時点で、SIGの設立が要望されている言語にはLua、Perl、Juliaの3つが挙がっていました。

Perlの要望は、communityリポジトリの[issue #828](https://github.com/open-telemetry/community/issues/828)「Perl SIG: current level of interest?」です。2021年9月7日に立てられたこのissueは、いまも開いたままになっています。最後の書き込みは2026年3月でした。2025年12月には、Perlのアプリケーションを.NET Aspireのダッシュボードにつなぐ統合を試していた参加者に、Severin Neumann[^svrnm]が[次のように返信しています](https://github.com/open-telemetry/community/issues/828#issuecomment-3611281576)。

> note that the existing perl implementations are not part of the opentelemetry project but provided by 3rd parties (which we are absolutely fine with)
>
> （既存のPerlの実装はOpenTelemetryプロジェクトの一部ではなく、サードパーティが提供しているものです。それで何も問題はありません）

公式の対応言語ではないからといって、CPANの実装が使えないわけではありません。OpenTelemetryの[レジストリ](https://opentelemetry.io/ja/ecosystem/registry/?language=perl)は、公式でない実装も含めてOpenTelemetryの部品を探すための一覧です。レジストリには、CPANのAPI、SDK、OTLPエクスポーター、Plackのミドルウェア、Mojoliciousのプラグインが登録されています。

[^svrnm]: [Severin Neumann](https://github.com/svrnm)は、OpenTelemetryのドキュメントサイトのメンテナーの1人です。執筆時点でBronto所属です（[opentelemetry.ioのREADME](https://github.com/open-telemetry/opentelemetry.io#maintainers)）。

## CPANにある配布物

CPANの実装の中心は、API、SDK、OTLPエクスポーターの3つの配布物です。いずれもJosé Joaquín Atria[^jjatria]が書いています。その周りに、フレームワークやライブラリごとの計装を提供する配布物があります。2026年10月19日にMetaCPANで確認した最新版は次のとおりです。

| 配布物 | 作者のID | 最新版（リリース日） | 役割 |
| --- | --- | --- | --- |
| [OpenTelemetry](https://metacpan.org/release/JJATRIA/OpenTelemetry-0.039) | JJATRIA | 0.039（2026-10-03） | API。トレースとログのAPI、トレースコンテキストのプロパゲーター、`HTTP::Tiny`、`LWP::UserAgent`、`DBI`の計装、`Log::Any`のアダプターを含む |
| [OpenTelemetry::SDK](https://metacpan.org/release/JJATRIA/OpenTelemetry-SDK-0.100) | JJATRIA | 0.100（2026-10-11） | SDK。トレースとログの処理と送信。ログに対応した最初の安定版 |
| [OpenTelemetry::Exporter::OTLP](https://metacpan.org/release/JJATRIA/OpenTelemetry-Exporter-OTLP-0.022) | JJATRIA | 0.022（2026-10-15） | OTLPエクスポーター。トレースとログをHTTPで送る[^otlp-0022] |
| [Plack::Middleware::OpenTelemetry](https://metacpan.org/release/ABH/Plack-Middleware-OpenTelemetry-0.262410) | ABH | 0.262410（2026-08-29） | PSGIのリクエストごとにスパンを作るミドルウェア |
| [Mojolicious::Plugin::OpenTelemetry](https://metacpan.org/dist/Mojolicious-Plugin-OpenTelemetry) | JJATRIA | 0.006（2026-03-11） | Mojoliciousのプラグイン |
| [Dancer2::Plugin::OpenTelemetry](https://metacpan.org/dist/Dancer2-Plugin-OpenTelemetry) | JJATRIA | 0.003（2024-05-09） | Dancer2のプラグイン |

このほかに、2026年9月以降だけでも、[`Mojo::UserAgent`](https://metacpan.org/dist/OpenTelemetry-Instrumentation-Mojo-UserAgent)とMongoDBクライアントの[Mango](https://metacpan.org/dist/OpenTelemetry-Instrumentation-Mango)の計装（JAVIER）が新しくリリースされています。Log4perlからOpenTelemetryへログを送る[アペンダー](https://metacpan.org/dist/Log-Log4perl-Appender-OpenTelemetry)（ABRAXXA）も、同じ期間の新しいリリースです。Plackのミドルウェアを書いているのはSDKとは別の作者で、APIとSDKの作者以外の人が計装を書き始めています。

OTLPは、OpenTelemetryが定めるテレメトリーの送信プロトコルです[^otlp]。エクスポーターはHTTPの上でJSONまたはprotobufを送れますが、gRPCには対応していません。protobufで送るには `Google::ProtocolBuffers::Dynamic` が必要で、入っていなければJSONで送ります。本書の環境ではこのモジュールを入れていないので、送信の形式はJSONです。

[^jjatria]: [José Joaquín Atria](https://github.com/jjatria)は、CPANのOpenTelemetry、OpenTelemetry::SDK、OpenTelemetry::Exporter::OTLPの作者です。CPANのIDはJJATRIAです。
[^otlp]: 仕様は[OTLP Specification](https://opentelemetry.io/ja/docs/specs/otlp/)にあります。
[^otlp-0022]: 本書の測定には0.021を使いました。0.022の変更は、未定義の値をエンコードするときに警告を出さなくなったことなどで、本書で扱う動作は変わりません。

## APIとSDKを分ける理由

配布物がAPIとSDKに分かれているのは、OpenTelemetryの仕様がそう求めているからです。仕様の[Library Guidelines](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/library-guidelines.md)は、計装を組み込むライブラリが何に依存するかを次のように定めています。

> Libraries, frameworks, and applications that want to be instrumented with OpenTelemetry take a dependency only on the API packages.
>
> （OpenTelemetryで計装したいライブラリ、フレームワーク、アプリケーションは、APIのパッケージにだけ依存します）

APIは、SDKが無くても動く最小限の実装を持ちます。ライブラリの作者は、APIを呼んでスパンを作るコードを書きます。SDKを読み込むかどうかとデータをどこへ送るかを決めるのは、そのライブラリを使うアプリケーションの作者です。SDKを読み込まないアプリケーションでは、ライブラリのAPI呼び出しは何もせずに戻ります。

![APIとSDKとエクスポーターの関係](/images/20261128-api-sdk-exporter.png)
*図1: CPANの配布物の関係。矢印は呼び出しの向きで、破線はSDKを読み込んだときだけ通る経路を表す。アプリケーションと計装ライブラリはAPI（OpenTelemetry）だけを呼ぶ。SDK（OpenTelemetry::SDK）を読み込むと、APIの呼び出しがSDKの実装に置き換わり、SDKがスパンをプロセッサーとエクスポーター（OpenTelemetry::Exporter::OTLP）に渡す*

CPANの実装でも、APIだけを読み込んだ状態では何も記録されないことを確かめました。次のスクリプトはAPIだけを読み込んでスパンを1つ作り、そのスパンの状態を表示します。

```perl:e2_api_only.pl
use v5.40;
use OpenTelemetry 'otel_tracer_provider';

my $provider = otel_tracer_provider;
my $tracer   = $provider->tracer( name => 'e2' );
$tracer->in_span( work => sub ( $span, $context ) {
    say 'provider:     ', ref $provider;
    say 'span:         ', ref $span;
    say 'is_recording: ', $span->recording ? 'true' : 'false';
    say 'trace_id:     ', $span->context->hex_trace_id;
});
```

```
provider:     OpenTelemetry::Trace::TracerProvider
span:         OpenTelemetry::Trace::Span
is_recording: false
trace_id:     00000000000000000000000000000000
```

スパンは作られますが、記録されないスパンで、トレースIDはすべて0です。2行目の `use OpenTelemetry` の前に `use OpenTelemetry::SDK;` を1行足して実行すると、プロバイダーは `OpenTelemetry::SDK::Trace::TracerProvider` に、スパンは `OpenTelemetry::SDK::Trace::Span` に変わり、`is_recording` が `true` になりました。トレースIDにも値が入ります。

アプリケーションのコードを書き換えずに、SDKを読み込む1行で振る舞いが切り替わります。CPANのモジュールの作者がAPIの `OpenTelemetry` にだけ依存して計装を書く利点は、利用側のアプリケーションの選択を縛らないことです。この性質は、5章でPlackのミドルウェアを読むときにもう一度確かめます。
