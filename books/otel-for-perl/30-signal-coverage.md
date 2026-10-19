---
title: "トレース、ログ、メトリクスの実装状況"
---

## 「動く」を4つの段階に分ける

CPANの実装について「トレースは動く」「ログは開発中」と言うとき、何がどこまでできるのかは人によってまちまちです。APIにクラスがあるだけなのか、SDKがデータを処理するのか、エクスポーターが送れるのかは配布物を読めば分かります。送ったデータが実際にCollectorに届くかどうかは、動かしてみないと分かりません。

そこで、シグナルごとに4つの段階を分けて確かめました。最初の3つは、APIのプロバイダー、SDKの処理、OTLPエクスポーターの送信がそれぞれ実装されているかです。4つ目は、本書の構成でCollectorに届いたかです。

| シグナル | API（0.039） | SDK（0.100） | エクスポーター（0.021） | Collectorへの到達 |
| --- | --- | --- | --- | --- |
| トレース | あり | あり | あり | 確認 |
| ログ | あり | あり | あり | 確認 |
| メトリクス | なし | なし | なし | 該当なし |

トレースは4つの段階がすべてそろっていて、4章から6章で見たとおり届きます。ログも、SDK 0.100で4つの段階がそろいました。SDKのログの実装は、2026年10月3日の試験版0.029-TRIALで加わり、10月11日の0.100で初めて安定版に入ったものです[^logs-0028]。メトリクスは、APIの段階から未実装です。

## ログ

OpenTelemetryのログは、トレースやメトリクスとは考え方が違います。ログ専用の新しいAPIをアプリケーションの作者に使わせる代わりに、既存のロギングのライブラリからログを流す設計です[^logs-spec]。CPANのAPIのInstrumentation Guideも、ログのAPIは利用者が直接呼ぶものではないとしています。このGuideによれば、ログのAPIは既存のロガーとつなぐアダプターのためのものです。APIの配布物には、[Log::Any::Adapter::OpenTelemetry](https://metacpan.org/pod/Log::Any::Adapter::OpenTelemetry)が入っています。[Log::Any](https://metacpan.org/pod/Log::Any)からOpenTelemetryへログを流すアダプターです。

[^loglevel]: これは0.039のコードの動作です。アダプターのPODは、`OTEL_LOG_LEVEL` を先に読み、次に `PERL_OTEL_LOG_LEVEL` を読むと説明していて、コードと食い違っています。
[^logs-spec]: 仕様の[Logs](https://opentelemetry.io/docs/specs/otel/logs/)の概要で、この方針を確認できます。
[^logs-0028]: 0.028までの安定版で次の `e5_logs.pl` を実行すると、ログを出す行ではエラーが出ないまま、ログは1件も送られませんでした。SDKがログのプロバイダーを差し替えないので、`otel_logger_provider` はAPIの何もしない `OpenTelemetry::Logs::LoggerProvider` を返します。このプロバイダーには `force_flush` のメソッドも無く、スクリプトはその行で止まります。

次のスクリプトで、スパンの中と外でログを出しました。

```perl:e5_logs.pl
use v5.40;
use OpenTelemetry::SDK;
use OpenTelemetry qw( otel_tracer_provider otel_logger_provider );
use Log::Any '$log';
use Log::Any::Adapter 'OpenTelemetry';

my $tracer = otel_tracer_provider->tracer( name => 'e5' );
$tracer->in_span( report => sub ( $span, $context ) {
    $log->warn('rates service is slow');
});
$log->info('outside of any span');
$log->debugf( 'formatted %s', 'message' );

# ログもBatchプロセッサーなので、明示的に送り出す
otel_logger_provider->force_flush(3)->get;
otel_tracer_provider->force_flush(3)->get;
```

SDK 0.100で実行すると、ログがOTLPでCollectorに届きました。届いたログレコードのうち、スパンの中で出した `warn` は次のとおりです。

```json
{
  "severityNumber": 13,
  "severityText": "warning",
  "body": { "stringValue": "rates service is slow" },
  "traceId": "dacb7c4725e3632ffe78af55d58357d2",
  "spanId": "49ec4cf2e0140124"
}
```

`traceId` と `spanId` は、`in_span` で作った `report` のスパンのものと一致しました。スパンの外で出した `info` には、どちらも付いていませんでした。トレースのビューアーで遅いスパンを見つけて、そのスパンの最中に出たログへ移る使い方ができます。

`debugf` のログは届きませんでした。アダプターは送るログのレベルを環境変数 `OTEL_PERL_LOG_LEVEL` で決め、未設定なら `OTEL_LOG_LEVEL` を読み、どちらも無ければ `info` 以上だけを送ります[^loglevel]。ログのSDKもBatchプロセッサーを使うので、トレースと同じくスクリプトの最後で `force_flush` を呼ぶ必要がありました。

このスクリプトは3回とも最後まで進んで終了し、4章で見た、0.100のSDKを読み込んだプログラムが終了しない現象は起きませんでした。ただ、この現象が起きる条件は分かっていません。ログを送るプログラムで使えるのは、4章で挙げた2つの方法のうち、終了する前にログのプロバイダーの `shutdown` を呼ぶ方法だけです。スクリプトなら、これで避けられます。PSGIサーバーの終了処理の中では、この方法でも停止が遅くなりました（8章）。

## メトリクス

メトリクスは、APIの段階から存在しません。APIの配布物にメトリクスのモジュールは無く、`OpenTelemetry->meter_provider` のようなメソッドもありません。APIのInstrumentation GuideのMETRICSの節は、次の1文だけです。

> The metrics API & SDK are currently under development.
>
> （メトリクスのAPIとSDKは現在開発中です）

SDKを動かすと `otel_bsp_buffer_utilization` のようなメトリクスの名前を目にしますが、OpenTelemetryのメトリクスではありません。SDKが自分の状態を記録するために使っている、[Metrics::Any](https://metacpan.org/pod/Metrics::Any)という別のライブラリのメトリクスです。Metrics::Anyのアダプターを設定すれば値を読めますが、OTLPで送られることはありません。

## 未実装と設定不足と実行環境の条件

ここまでの「動かない」には、性質の違う原因が混在しています。メトリクスは**未実装**で、利用者の側では対処できません。一方、Goのプロパゲーターを設定しないと伝搬が切れることや、`debugf` のログが送られないことは**設定不足**です。どちらも設定を変えれば済みます。

3つ目は、SDKの実装も設定も正しいのに、アプリケーションを動かす環境によって送れなくなる場合です。本書ではこれを**実行環境の条件**と呼びます。4章で書いた、PSGIのアプリケーションでBatchプロセッサーのままだとスパンが期待どおりに届かない現象がその例です。8章では、この現象をPSGIサーバーの種類ごとに測ります。
