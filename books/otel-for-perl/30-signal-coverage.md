---
title: "トレース、ログ、メトリクスの実装状況"
---

## 「動く」を4つの段階に分ける

CPANの実装について「トレースは動く」「ログは開発中」と言うとき、何がどこまでできるのかは人によってまちまちです。APIにクラスがあるだけなのか、SDKがデータを処理するのか、エクスポーターが送れるのかは配布物を読めば分かります。送ったデータが実際にCollectorに届くかどうかは、動かしてみないと分かりません。

そこで、シグナルごとに4つの段階を分けて確かめました。最初の3つは、APIのプロバイダー、SDKの処理、OTLPエクスポーターの送信がそれぞれ実装されているかです。4つ目は、本書の構成でCollectorに届いたかです。

| シグナル | API（0.039） | SDK 0.028 | SDK 0.029-TRIAL | エクスポーター（0.021） | Collectorへの到達 |
| --- | --- | --- | --- | --- | --- |
| トレース | あり | あり | あり | あり | 0.028で確認 |
| ログ | あり | なし | あり（実験的） | あり | 0.029-TRIALで確認 |
| メトリクス | なし | なし | なし | なし | 該当なし |

トレースは4つの段階がすべてそろっていて、4章から6章で見たとおり届きます。ログは、APIとエクスポーターにはあるのに、安定版のSDKに実装がありません。メトリクスは、APIの段階から未実装です。

## ログ

OpenTelemetryのログは、トレースやメトリクスとは考え方が違います。ログ専用の新しいAPIをアプリケーションの作者に使わせる代わりに、既存のロギングのライブラリからログを流す設計です[^logs-spec]。CPANのAPIのInstrumentation Guideも、ログのAPIは利用者が直接呼ぶものではないとしています。このGuideによれば、ログのAPIは既存のロガーとつなぐアダプターのためのものです。APIの配布物には、[Log::Any::Adapter::OpenTelemetry](https://metacpan.org/pod/Log::Any::Adapter::OpenTelemetry)が入っています。[Log::Any](https://metacpan.org/pod/Log::Any)からOpenTelemetryへログを流すアダプターです。

[^loglevel]: これは0.039のコードの動作です。アダプターのPODは、`OTEL_LOG_LEVEL` を先に読み、次に `PERL_OTEL_LOG_LEVEL` を読むと説明していて、コードと食い違っています。
[^logs-spec]: 仕様の[Logs](https://opentelemetry.io/docs/specs/otel/logs/)の概要で、この方針を確認できます。

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

# 0.029-TRIALのログもBatchプロセッサーなので、明示的に送り出す
otel_logger_provider->force_flush(3)->get;
otel_tracer_provider->force_flush(3)->get;
```

安定版のSDK 0.028で実行すると、ログを出す行ではエラーが出ないまま、ログは1件も送られませんでした。`otel_logger_provider` が返すのはAPIの何もしない `OpenTelemetry::Logs::LoggerProvider` のままで、SDKがログのプロバイダーを差し替えないからです。このプロバイダーには `force_flush` のメソッドも無いので、上のスクリプトはその行で止まります。

SDKを0.029-TRIALにすると、ログがOTLPでCollectorに届きました。試験版はCPANのクライアントがデフォルトでは入れないので、Cartonでは配布物のパスを指定して固定しました。

```perl:cpanfile
requires 'OpenTelemetry::SDK', '== 0.029',
    dist => 'JJATRIA/OpenTelemetry-SDK-0.029-TRIAL.tar.gz';
```

Collectorに届いたログレコードのうち、スパンの中で出した `warn` は次のとおりです。

```json
{
  "severityNumber": 13,
  "severityText": "warning",
  "body": { "stringValue": "rates service is slow" },
  "traceId": "be6000d516dc61cdc9fe1fed504d94cb",
  "spanId": "b38025b690396592"
}
```

`traceId` と `spanId` は、`in_span` で作った `report` のスパンのものと一致しました。スパンの外で出した `info` には、どちらも付いていませんでした。トレースのビューアーで遅いスパンを見つけて、そのスパンの最中に出たログへ移る使い方ができます。

`debugf` のログは届きませんでした。アダプターは送るログのレベルを環境変数 `OTEL_PERL_LOG_LEVEL` で決め、未設定なら `OTEL_LOG_LEVEL` を読み、どちらも無ければ `info` 以上だけを送ります[^loglevel]。ログのSDKもBatchプロセッサーを使うので、トレースと同じくスクリプトの最後で `force_flush` を呼ぶ必要がありました。

試験版には、もう1つ注意点があります。0.029-TRIALのSDKを読み込んだプログラムは、何もせずに終わろうとしても終了しませんでした。`perl -MOpenTelemetry::SDK -e 1` だけで再現します。プロセスは `END` ブロックの後で止まったままで、0.028では起きません。`OTEL_TRACES_EXPORTER` か `OTEL_LOGS_EXPORTER` のどちらかを `none` にすると終了するので、トレースとログの両方にBatchプロセッサーが組まれることが条件です。上の `e5_logs.pl` は両方の `force_flush` を呼んでいて、この現象には当たりませんでした。原因は調べていません。

ログには、CPANのクライアントがデフォルトで入れる安定版では送れないという制約があります。いまPerlのアプリケーションのログをOpenTelemetryで扱うなら、方法は2つあります。試験版のSDKを使うか、ファイルに書いたログをCollectorに読ませるかです。ファイルを読ませる方法は、本書では試していません。

## メトリクス

メトリクスは、APIの段階から存在しません。APIの配布物にメトリクスのモジュールは無く、`OpenTelemetry->meter_provider` のようなメソッドもありません。APIのInstrumentation GuideのMETRICSの節は、次の1文だけです。

> The metrics API & SDK are currently under development.
>
> （メトリクスのAPIとSDKは現在開発中です）

SDKを動かすと `otel_bsp_buffer_utilization` のようなメトリクスの名前を目にしますが、OpenTelemetryのメトリクスではありません。SDKが自分の状態を記録するために使っている、[Metrics::Any](https://metacpan.org/pod/Metrics::Any)という別のライブラリのメトリクスです。Metrics::Anyのアダプターを設定すれば値を読めますが、OTLPで送られることはありません。

## 未実装と設定不足と実行環境の条件

ここまでの「動かない」には、性質の違う原因が混在しています。メトリクスと安定版のログは**未実装**で、利用者の側では対処できません。一方、Goのプロパゲーターを設定しないと伝搬が切れることや、`debugf` のログが送られないことは**設定不足**です。どちらも設定を変えれば済みます。

3つ目は、SDKの実装も設定も正しいのに、アプリケーションを動かす環境によって送れなくなる場合です。本書ではこれを**実行環境の条件**と呼びます。4章で書いた、PSGIのアプリケーションでBatchプロセッサーのままだとスパンが期待どおりに届かない現象がその例です。8章では、この現象をPSGIサーバーの種類ごとに測ります。
