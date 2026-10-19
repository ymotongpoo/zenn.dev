---
title: "SDKを有効にしてスパンを送る"
---

## 依存の固定

CPANの実装は開発が速く、本書の執筆中にも、APIの新しいバージョンと、SDKの試験版と安定版が出ました。手元で試すときに配布物のバージョンを固定しておかないと、昨日動いた構成が今日は別のバージョンで動くことになります。[Carton](https://metacpan.org/pod/Carton)は、`cpanfile` に書いた依存をアプリケーションのディレクトリに入れ、解決した全バージョンを `cpanfile.snapshot` に記録するツールです。本書ではCartonを使い、直接の依存を `cpanfile` で固定しました。

```perl:cpanfile
requires 'OpenTelemetry', '== 0.039';
requires 'OpenTelemetry::SDK', '== 0.100';
requires 'OpenTelemetry::Exporter::OTLP', '== 0.021';
requires 'Plack::Middleware::OpenTelemetry', '== 0.262410';
requires 'Plack';
requires 'Starman';
requires 'Twiggy';
requires 'AnyEvent::HTTP';
requires 'JSON::PP';
```

`carton install` で入った配布物は、推移的な依存を含めて81個でした。SDKが非同期処理に使うモジュールは、[IO::Async](https://metacpan.org/pod/IO::Async)と[Future::AsyncAwait](https://metacpan.org/pod/Future::AsyncAwait)です。クラスの定義には[Object::Pad](https://metacpan.org/pod/Object::Pad)を使っています。依存の中にはXSのモジュールもあるので、コンパイラの入った `perl:5.44.0` のイメージでビルドしました。

```dockerfile:Dockerfile
FROM perl:5.44.0
RUN cpanm -nq Carton@1.0.35
WORKDIR /app
COPY cpanfile cpanfile.snapshot ./
RUN carton install --deployment
COPY lib lib
COPY *.psgi ./
ENV PERL5LIB=/app/local/lib/perl5:/app/lib PATH=/app/local/bin:$PATH
EXPOSE 5000
CMD ["plackup", "-E", "deployment", "-s", "HTTP::Server::PSGI", "-p", "5000", "app_otel.psgi"]
```

## SDKの初期化と環境変数

SDKを有効にするには、アプリケーションの最初で `use OpenTelemetry::SDK;` と書きます。`use` で読み込むと、SDKはコンパイル時に環境変数から設定を読みます。その設定でトレースとログのプロバイダーを作り、APIのグローバルなプロバイダーと差し替える仕組みです。初期化の途中で例外が起きると（エクスポーターのモジュールを読み込めないときなど）、その場でプログラムを止めます。知らないエクスポーターやプロパゲーターの名前は、警告を出して読み飛ばします。SDKのドキュメントによれば、初期化で止まる動作の根拠は仕様の規定です。仕様は、実行時に未処理の例外を投げないことをSDKに求める一方で、初期化の時点で止まることは認めています。

設定は、OpenTelemetryの仕様が定める環境変数で渡します。本書で使ったのは次の変数です。

| 環境変数 | 本書での値 | 意味 |
| --- | --- | --- |
| `OTEL_SERVICE_NAME` | `report` | スパンのリソース属性 `service.name` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://collector:4318` | OTLPの送信先。トレースは `/v1/traces`、ログは `/v1/logs` に送られる |
| `OTEL_TRACES_EXPORTER` | 未設定（`otlp`） | エクスポーターの種類。`otlp`、`console`、`none` など |
| `OTEL_LOGS_EXPORTER` | 未設定（`otlp`）。8章の一部の測定では `none` | ログのエクスポーターの種類。値は `OTEL_TRACES_EXPORTER` と同じ |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | 未設定 | `http/json` か `http/protobuf`。未設定なら、protobufのモジュールの有無で決まる |
| `OTEL_PROPAGATORS` | 未設定（`tracecontext,baggage`） | トレースコンテキストの形式 |

まずエクスポーターを `console` にして、3章の実験と同じスクリプトを動かしました。SDKを読み込んだ版のスクリプトを `OTEL_TRACES_EXPORTER=console` で実行すると、スパンが終わった時点で標準エラーに1行で出力されます。整形して一部を抜き出すと次のとおりです。

```perl
{
  'name' => 'work',
  'kind' => 1,
  'trace_id' => '6b775821c61aab22990644ed806de17c',
  'span_id' => '6efa2315849d0f8f',
  'parent_span_id' => '0000000000000000',
  'status' => { 'code' => 1, 'description' => '' },
  'instrumentation_scope' => { 'name' => 'e2', 'version' => '' },
  'resource' => {
    'process.runtime.name' => 'perl',
    'process.runtime.version' => 'v5.44.0',
    'telemetry.sdk.language' => 'perl',
    'telemetry.sdk.name' => 'opentelemetry',
    'telemetry.sdk.version' => '0.100',
    ...
  },
  ...
}
```

リソースには、Perlのバージョンやプロセスの情報をSDKが自動で入れています。なお、この実行では、出力の後にプロセスが終了しませんでした。0.100のSDKで起きるこの現象は、章の最後で扱います。

## Collectorで受け取る

本番に近い構成では、スパンをOTLPでCollectorに送ります。本書のCollectorは受け取ったデータをそのままファイルに保存し、[grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm)にも転送します。otel-lgtmは、GrafanaとTempoなどのバックエンドを1つにまとめた開発用のコンテナです。本書の数値と木の形は、すべて保存したファイルから数えました。

```yaml:collector/config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch: {}

exporters:
  # 受け取ったOTLPをそのままJSON Linesで保存する。検証はこのファイルで行う
  file:
    path: /data/otlp.jsonl
  otlphttp/lgtm:
    endpoint: http://lgtm:4318

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [file, otlphttp/lgtm]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [file, otlphttp/lgtm]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [file, otlphttp/lgtm]
```

ComposeではPerlのアプリケーションに環境変数を渡し、起動するコマンドを外から差し替えられるようにしました。`init: true` は8章で説明します。

```yaml:compose.yaml（抜粋）
services:
  frontend:
    build: ./frontend
    init: true
    command: ${FRONTEND_CMD:-plackup -E deployment -s HTTP::Server::PSGI -p 5000 app_otel.psgi}
    environment:
      OTEL_SERVICE_NAME: report
      OTEL_EXPORTER_OTLP_ENDPOINT: http://collector:4318
      RATES_URL: http://backend:8080
    ports:
      - "5000:5000"

  collector:
    image: otel/opentelemetry-collector-contrib:0.162.0
    volumes:
      - ./collector/config.yaml:/etc/otelcol-contrib/config.yaml:ro
      - ./out:/data

  lgtm:
    image: grafana/otel-lgtm:0.32.1
    ports:
      - "3300:3000"
```

## SDKが組むプロセッサー

エクスポーターを `otlp` にしたとき、SDKはスパンをすぐには送りません。終わったスパンを**プロセッサー**に渡し、エクスポーターの呼び出しはプロセッサーに任せます。仕様が定めるプロセッサーは、スパンをその場で1つずつ送るSimpleと、キューに貯めてまとめて送るBatchの2つです。CPANのSDKは、`console` にはSimpleを、`otlp` にはBatchを組み合わせます。環境変数でプロセッサーを選ぶ方法はありません。ログのプロバイダーを組む規則も、0.100では同じです。`OTEL_LOGS_EXPORTER` のデフォルトも `otlp` なので、ログを送らないアプリケーションにもログのBatchプロセッサーができます。

Batchプロセッサーを使うと、短いスクリプトでは送る前にプログラムが終わってしまいます。スクリプトの最後でプロバイダーの `force_flush` を呼び、キューを送り出す必要があります。

```perl
use OpenTelemetry::SDK;
use OpenTelemetry qw( otel_tracer_provider otel_logger_provider );

otel_tracer_provider->tracer( name => 'e6' )->in_span( "span-$_" => sub { } ) for 1 .. 3;

otel_tracer_provider->force_flush(3)->get;    # 3秒を上限にキューを送る
otel_tracer_provider->shutdown(3)->get;
otel_logger_provider->shutdown(3)->get;       # 0.100では、これが無いと終了しない
```

`force_flush` と `shutdown` は、非同期処理の結果を表す[Future](https://metacpan.org/pod/Future)のオブジェクトを返します。`get` を呼ぶと、送信が終わるまでそこで待ちます。このスクリプトから `force_flush` の行を消すと、`shutdown` は成功を返すのに3つのスパンは1つもCollectorに届きませんでした。`shutdown` だけでは送られない理由は、8章で扱います。

PSGIのアプリケーションでも、Batchプロセッサーのままでは期待どおりにスパンが届きません。その原因と測定結果は8章にまとめ、5章と6章では確実に届くSimpleプロセッサーを使います。`OTEL_TRACES_EXPORTER` を `none` にしてSDKにプロセッサーを組ませず、Simpleプロセッサーとエクスポーターを自分で追加する構成です。

```perl:app_otel_simple.psgi
# Batchの代わりにSimpleプロセッサーで、スパンが終わるたびに同期で送る
use v5.40;
use Plack::Util;
use OpenTelemetry 'otel_tracer_provider';
use OpenTelemetry::SDK::Trace::Span::Processor::Simple;
use OpenTelemetry::Exporter::OTLP;

BEGIN { $ENV{OTEL_TRACES_EXPORTER} = 'none' }    # SDKにBatchを組ませない
my $app = Plack::Util::load_psgi('app_otel.psgi');

otel_tracer_provider->add_span_processor(
    OpenTelemetry::SDK::Trace::Span::Processor::Simple->new(
        exporter => OpenTelemetry::Exporter::OTLP->new,
    ),
);

$app;
```

このファイルは、5章で作る `app_otel.psgi` を読み込んでそのまま返すだけです。`app_otel.psgi` の中の `use OpenTelemetry::SDK;` が実行されるのは、`load_psgi` の時点です。そのときには環境変数が `none` になっているので、SDKはプロセッサーを持たないプロバイダーを作ります。`app_otel_simple.psgi` は、読み込みが終わった後でそのプロバイダーにSimpleプロセッサーを足しています。

## 終了しないプログラム

0.100のSDKでは、前の節の `force_flush` のスクリプトから最後の行を消すと、プログラムが終了しませんでした。`shutdown` の結果が返った後も、プロセスが動いたまま残ります。SDKを読み込むだけの `perl -MOpenTelemetry::SDK -e 1` でも同じで、0.028では起きなかった現象です。本書の構成で試した範囲では、何も設定しなければ毎回起きました[^hang-count]。

止まる場所は、プロセスの終了の最後にPerlがオブジェクトをまとめて破棄する処理（グローバルデストラクション）の中です。Batchプロセッサーは、破棄されるときにIO::Async::Functionのワーカーを止め、その終了を待ちます。止まったプロセスでは、ログのBatchプロセッサーの破棄が始まったまま戻っていませんでした。ワーカーのプロセスはすでに終了していて、アプリケーションのプロセスは、その終了を受け取れないまま待ち続けています。トレースかログのどちらかのエクスポーターを `none` にした構成では、破棄の処理が戻り、プロセスは終了しました。

終了させる方法は2つあります。ログを送らないアプリケーションなら、`OTEL_LOGS_EXPORTER` を `none` にして、ログのプロセッサーを作らせないことです。ログも送るなら、そのスクリプトの最後の行のように、終了する前にログのプロバイダーの `shutdown` も呼びます。破棄が始まる前にワーカーを止めておけば、破棄の処理で待つことはありません。試した回数すべてでプロセスが終了したのは、どちらの方法でも同じです。PSGIサーバーの停止への影響は、8章で測ります。

[^hang-count]: `perl -MOpenTelemetry::SDK -e 1` を8回、`force_flush` のスクリプトから最後の行を消した版を4回試し、いずれも12秒以上経っても終了しませんでした。試験版の0.029-TRIALでも同じでした。0.028で終了しないことがあるという既存の[issue #24](https://github.com/jjatria/perl-opentelemetry-sdk/issues/24)に、0.029-TRIALでの再現手順（2026年10月7日）と、0.100でも再現すること（10月19日）をコメントしました。起きる条件は特定できていません。トレースのエクスポーターを `console` にしてトレースをSimpleプロセッサーにした場合も、`OTEL_EXPORTER_OTLP_ENDPOINT` を設定しないと終了せず、設定すると終了しました。
