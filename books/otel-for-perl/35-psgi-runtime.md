---
title: "PSGIサーバーの実行方式とSDK"
---

## Perlのスパンが届かない

最初に `app_otel.psgi` を動かしたときは、4章のSimpleプロセッサーの構成ではなく、SDKが組むデフォルトの構成でした。起動には `plackup` のデフォルトのサーバーであるHTTP::Server::PSGIを使いました。2章の3種類のリクエストを1回ずつ送り、60秒待ちました。Collectorに届いていたのは、Goの `rates` のスパン3件だけです。

Goのスパンには親のスパンIDが入っていて、Perlから `traceparent` が渡っていたことは確かでした。Perlのプロセスの中ではスパンが作られ、計装はヘッダーを書いています。作られたスパンが、Collectorに送られていないということです。エクスポーターの設定を誤ったのだろうと考えましたが、送信先の設定はGoのサービスと同じでした。

## Batchプロセッサーが送る契機

原因は、SDKが `otlp` のエクスポーターと組み合わせるBatchプロセッサーの実装にありました。仕様の[Batching processor](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/trace/sdk.md#batching-processor)は、送信する契機として次の4つを挙げています。

> - `scheduledDelayMillis` after the processor is constructed OR the first span
>   is received by the span processor.
> - `scheduledDelayMillis` after the previous export timer ends, OR the previous
>   export completes, OR the first span is added to the queue after the previous
>   export timer ends or previous batch completes.
> - The queue contains `maxExportBatchSize` or more spans.
> - `ForceFlush` is called.
>
> （プロセッサーの作成か最初のスパンの受信から `scheduledDelayMillis` 後。前回の送信のタイマーの終了か送信の完了から、またはその後に最初のスパンがキューに入ってから `scheduledDelayMillis` 後。キューのスパンが `maxExportBatchSize` 件以上のとき。`ForceFlush` が呼ばれたとき）

`scheduledDelayMillis` のデフォルト値は5,000ミリ秒です。仕様どおりの実装なら、リクエストが少なくても5秒ごとに送られます。ところが、SDK 0.028の[Batchプロセッサー](https://github.com/jjatria/perl-opentelemetry-sdk/blob/0.028/lib/OpenTelemetry/SDK/Trace/Span/Processor/Batch.pm)は、環境変数 `OTEL_BSP_SCHEDULE_DELAY` の値を `$schedule_delay` に入れるだけです。その値は、どこでも使われていません。スパンを受け取る `process` メソッドは、キューが512件（`OTEL_BSP_MAX_EXPORT_BATCH_SIZE` のデフォルト値）に満たなければ、何もせずに戻ります。

```perl:OpenTelemetry/SDK/Trace/Span/Processor/Batch.pm（0.028、抜粋）
    method process ( @items ) {
        my $batch = $lock->enter(
            sub {
                ...
                push @queue, @items;
                return [] if @queue < $batch_size;
                ...
                [ splice @queue, 0, $batch_size ];
            }
        );
        return unless @$batch;
        $function->call(
            args => [ $exporter, $batch, $exporter_timeout ],
            on_result => sub ( $type, $result ) { ... },
        );
        return;
    }
```

200回のリクエストを送ると、Perlのスパンは1回につき3件で計600件になります。そのうち届いたのは、ちょうど512件でした。残りの88件は、次に512件たまるまでキューに残ります。2026年10月3日の0.029-TRIALでは、Batchプロセッサーの本体がトレースとログに共通の `OpenTelemetry::Processor::Batch` に移りました。ただし、`$schedule_delay` を使わない作りは同じです。

## 送信が8回で止まる

キューが512件に達したときの送信にも、もう1つ条件があります。上のコードの `$function` は[IO::Async::Function](https://metacpan.org/pod/IO::Async::Function)のオブジェクトです。渡したコードを別のワーカープロセスで実行し、結果をイベントループ経由で受け取る仕組みです。SDKはエクスポーターの呼び出しをワーカープロセスに任せ、アプリケーションのプロセスが送信を待たないようにしています。

アプリケーションのプロセスは、ワーカーから結果を受け取るまでそのワーカーに次の仕事を渡しません。結果を受け取る処理が動くのは、IO::Asyncのイベントループが回っているときだけです。HTTP::Server::PSGIもStarmanも、IO::Asyncのループを回しません。そのため結果は誰にも受け取られず、ワーカーは使用中のまま残ります。IO::Async::Functionのワーカーの上限はデフォルトで8つです。

![Batchプロセッサーとワーカープロセス](/images/20261128-batch-processor-fork.png)
*図1: Batchプロセッサーの送信の流れ。実線はスパンの流れ、ピンクの破線はPSGIサーバーでは完了しない結果の受け取りを表す。アプリケーションのプロセスは、キューが512件に達するとIO::Async::Functionのワーカーに送信を依頼する。ワーカーは送信を終えると結果をパイプで返すが、アプリケーションのプロセスがIO::Asyncのループを回さない限り、その結果は読まれず、ワーカーは次の依頼を受けない*

2,000回のリクエスト（Perlのスパン6,000件）を送ると、届いたのは4,096件、つまり512件の8回分でした。そこで送信は止まり、コンテナの中にはワーカープロセスが8つ残っていました。

同じ現象は、APIのリポジトリの[issue #23](https://github.com/jjatria/perl-opentelemetry/issues/23)「Telemetry output stops being sent」で2025年9月に報告されています。報告者が突き止めた原因は、IO::Asyncを使わないプロセスでは誰もループを回さないことです。報告には、ループを回すコードも添えられていました。2026年4月に、作者のjjatriaが[次のように返しています](https://github.com/jjatria/perl-opentelemetry/issues/23#issuecomment-4199416444)。

> This is correct. I've used a similar solution (by calling `loop_once` with a small enough timeout at the end of a loop) in some of my own code. I had the feeling this might have been mentioned in one of the OpenTelemetry::Guides, but it seems to be missing.
>
> （そのとおりです。私も自分のコードで、ループの最後に十分短いタイムアウトで `loop_once` を呼ぶ似た方法を使っています。OpenTelemetry::Guidesのどれかで触れられていた気がしていましたが、抜けているようです）

PerlのWebアプリケーションの多くは、IO::Async以外の仕組みで動いています。PlackのサーバーやMojoliciousがその例です。Mojoliciousについては、APIのGuidesのExportersの章に方法が載っています。[IO::Async::Loop::Mojo](https://metacpan.org/pod/IO::Async::Loop::Mojo)を入れて環境変数 `IO_ASYNC_LOOP` を `Mojo` にすれば、IO::AsyncのループがMojoliciousのイベントループの上で回ります（本書では未検証）。PlackのPSGIサーバーについての同じような説明は、Guidesにありません。

## PSGIのミドルウェアで回避する

次のミドルウェアは、issue #23の方法をPSGIに当てはめて書いたものです。リクエストごとにIO::Asyncのループを1回だけ進めてワーカーの結果を受け取り、送信が8回で止まらないようにします。それだけでは5秒ごとの送信にはならないので、指定した秒数が経っていれば `force_flush` でキューを送り出す処理も加えました。

```perl:lib/Demo/OTelPump.pm
package Demo::OTelPump;
# IO::Asyncのループを回さないPSGIサーバーのための回避策。
# リクエストのたびにループを1回だけ進めて送信プロセスの結果を受け取り、
# intervalを設定した場合は、その秒数ごとにforce_flushでキューを送り出す。
use v5.40;
use parent 'Plack::Middleware';
use Plack::Util::Accessor qw( interval );
use IO::Async::Loop;
use OpenTelemetry 'otel_tracer_provider';
use Time::HiRes ();

my $last_flush = Time::HiRes::time;

sub call ( $self, $env ) {
    my $res = $self->app->($env);

    IO::Async::Loop->new->loop_once(0);    # SDKと同じループ（IO::Asyncの既定のループ）

    if ( my $interval = $self->interval ) {
        if ( Time::HiRes::time - $last_flush >= $interval ) {
            otel_tracer_provider->force_flush->get;
            $last_flush = Time::HiRes::time;
        }
    }
    return $res;
}

1;
```

`IO::Async::Loop->new` はプロセスで最初に作ったループを返し続けるので、返ってくるのはSDKがワーカーを登録したループそのものです。このミドルウェアを `enable 'OpenTelemetry'` の外側に置けば、サーバーのスパンが終わった後にループが進みます。

HTTP::Server::PSGIで、4つの構成に同じ2,000回のリクエストを順番に送りました。`days=0` で集計の待ち時間を無くし、送信の費用が目立つようにしています。

| 構成 | 届いたPerlのスパン（6,000件中） | 平均応答時間 |
| --- | --- | --- |
| デフォルトのBatch | 4,096 | 26.9ms |
| Batch＋ループを進めるだけ | 5,632 | 26.8ms |
| Batch＋ループ＋5秒ごとの `force_flush` | 5,703 | 27.1ms |
| Simple（4章の構成） | 6,000 | 32.2ms |

ループを進めるだけで、送信は止まらなくなりました。5,632件は512件の11回分で、残りはキューの中です。5秒ごとの `force_flush` を足しても、最後のflushの後に終わったリクエストのスパンは残ります。このflushはリクエストを契機に動くので、リクエストが来ない間はキューが送られないままです。Simpleプロセッサーだけが6,000件すべてを届けましたが、平均の応答時間はBatchより5ms余り長くなりました。

## 終了時に失われるスパン

キューに残ったスパンは、プロセスが終わるときに送るのが仕様の想定です。仕様では、プロバイダーの `Shutdown` はすべてのプロセッサーの `Shutdown` を呼び、プロセッサーの `Shutdown` は `ForceFlush` の効果を含まなければなりません。CPANのSDKでは、この経路にも2つの問題がありました。

1つ目は、SDKがプロセスの終了時に `shutdown` を自動では呼ばないことです。`END` ブロックやシグナルのハンドラーを登録していないので、アプリケーションが自分で呼ばない限りキューは終了とともに消えます。

2つ目は、`shutdown` を呼んでもキューが送られないことです。Batchプロセッサーの `shutdown` は、終了済みを表すフラグを立ててから `force_flush` を呼びます。ところが `force_flush` の先頭は、そのフラグが立っていれば何もせずに成功を返す作りです。

```perl:OpenTelemetry/SDK/Trace/Span/Processor/Batch.pm（0.028、抜粋）
    async method shutdown ( $timeout = undef ) {
        return TRACE_EXPORT_SUCCESS if $done;

        $done = 1;
        ...
        await $self->force_flush( maybe_timeout $timeout, $start );

        $self->$report_dropped_spans( terminating => scalar @queue )
            if @queue;
        @queue = ();
        ...
    }

    async method force_flush ( $timeout = undef ) {
        return TRACE_EXPORT_SUCCESS if $done;
        ...
```

結果として、`shutdown` はキューを送らずに「終了時に捨てた」と数えて空にします。4章で見た、`force_flush` の行を消すと3件とも届かない現象は、これが原因です。0.029-TRIALの `OpenTelemetry::Processor::Batch` も同じ順序で書かれていました。

PSGIのサーバーで終了時にキューを送る処理は、アプリケーションの側に書きます。SIGTERMを受けたら通常の終了処理を通し、`END` ブロックで `force_flush` を呼びます。

```perl:app_otel_pump.psgi（抜粋）
if ( $ENV{SHUTDOWN_HOOK} ) {
    $SIG{TERM} = sub { exit 0 };
    END { otel_tracer_provider->force_flush(3)->get if $ENV{SHUTDOWN_HOOK} }
}
```

`END` で `shutdown(3)` を呼ぶ版も試しましたが、HTTP::Server::PSGIでは3秒のタイムアウトを過ぎても戻りませんでした。プロセスは、10秒後にDockerがSIGKILLで止めるまで終わりませんでした。`force_flush(3)` だけにすると0.4秒で終了し、最後のリクエストのスパンも届きました。`shutdown` が戻らない原因は特定できていません[^init]。

[^init]: コンテナでこの確認をするには、Composeで `init: true` を指定する必要がありました。指定しないとplackupがコンテナのPID 1になります。PID 1はシグナルのデフォルトの動作を持たないので、`docker compose stop` のSIGTERMを無視します。

## Starmanのprefork

本番のPSGIアプリケーションでは、[Starman](https://metacpan.org/pod/Starman)のようなpreforkのサーバーがよく使われます。preforkは、起動時に複数のワーカープロセスを作ってリクエストを各ワーカーに振り分ける方式です。Starmanを4ワーカーで起動し、8並列で2,000回のリクエストを送りました。最後にコンテナを止めてから、届いたスパンを数えています。

| 構成 | 届いたPerlのスパン（6,000件中） | 親子がそろったトレース（2,000本中） | 平均応答時間 | 停止にかかった時間 |
| --- | --- | --- | --- | --- |
| 未計装（`app.psgi`） | － | － | 37.5ms | 0.7秒 |
| デフォルトのBatch | 1,536 | 510 | 42.6ms | 0.7秒 |
| Batch＋ループ＋5秒ごとの `force_flush`＋終了時の `force_flush` | 3,955 | 1,316 | 42.9ms | 10.7秒 |
| Simple | 6,000 | 2,000 | 51.7ms | 0.7秒 |

デフォルトのBatchでは、6,000件のうち1,536件しか届きませんでした。Starmanのワーカーは、それぞれが自分のキューとIO::Asyncのワーカーを持ちます。キューは512件ずつしか送られず、残りは停止とともに消えます。ただ、1ワーカーあたり約1,500件のスパンが作られた計算なので、512件ずつでもこれより多く届くはずです。1,536件にとどまった理由は確かめられていません。

ループを進める回避策を入れても、停止に10.7秒かかり、届いたのは3,955件でした。ワーカーの終了処理が完了せずSIGKILLで止められたものと見ていますが、原因は特定できていません。

Starmanの `--preload-app` は、アプリケーションをマスタープロセスで読み込んでからワーカーをforkするオプションです。SDKを読み込んだ後にforkすると、ワーカーとIO::Asyncの状態が不整合になるのではないかと考えました。そこで、このオプションを付けた場合も測りました。送信が止まることはなく、届いたスパンはデフォルトのBatchで1,024件、回避策で4,376件、Simpleで6,000件でした[^preload]。付けない場合と比べると、デフォルトのBatchは1,536件から減り、回避策は3,955件から増えています。この差の原因は確かめていません。

[^latency]: 応答時間は、`curl` の `time_total` を2,000回分平均した値です。分布やCPU使用率は測っていません。
[^preload]: plackupに `--preload-app app_otel.psgi` の順で渡すと、`app_otel.psgi` が `--preload-app` の値として扱われ、PSGIファイルの指定が消えます。plackupは、自分が知らないオプションの次の引数をそのオプションの値とみなすからです。このとき起動するのは、カレントディレクトリのデフォルトのファイル `app.psgi` です。`--preload-app=1` と書くと正しく渡せます。

## Simpleプロセッサーの費用

ここまでの測定で、どのサーバーでもすべてのスパンを届けたのはSimpleプロセッサーだけでした。その代わり、Simpleプロセッサーはスパンが終わるたびにその場でCollectorへHTTPのリクエストを送ります。題材のアプリケーションでは、1回のリクエストで3回送ることになります。

費用は応答時間に表れました。HTTP::Server::PSGIへの直列のリクエストでは、平均の応答時間がデフォルトのBatchより5ms余り長くなりました[^latency]。Starmanで8並列にした場合は、未計装の37.5msに対して51.7msと、14ms余り長い値でした。6章では、サーバーのスパンと子のスパンの和との間に約10msの差がありました。この差も、Simpleプロセッサーがリクエストの処理の途中で送信していることによるものです。ループを進める回避策で同じ3種類のリクエストを測ったときは、この差は3ms前後（2.7〜3.9ms）でした。

Simpleプロセッサーで計装したサーバーのスパンは、送信にかかった時間の分だけ長く記録されます。トレースで遅い区間を探すために計装したのに、区間の長さに計装の費用が含まれてしまいます。確実に届くこととアプリケーションの応答時間を乱さないことは、いまのCPANのSDKでは同時に満たせない条件です。

最後に、本書で試していない実行方式があります。TwiggyやMojoliciousのようなイベントループのサーバーでは、別の問題が加わります。コールバックをまたいでSDKのコンテキストが引き継がれるかどうかです。IO::Asyncのループで動くサーバーなら、ループが回るのでワーカーの結果は受け取られるはずです。ただ、この点も確かめていません。
