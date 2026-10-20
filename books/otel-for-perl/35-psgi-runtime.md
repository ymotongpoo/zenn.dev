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

`scheduledDelayMillis` のデフォルト値は5,000ミリ秒です。仕様どおりの実装なら、リクエストが少なくても5秒ごとに送られます。ところが、SDK 0.100の[Batchプロセッサー](https://github.com/jjatria/perl-opentelemetry-sdk/blob/0.100/lib/OpenTelemetry/Processor/Batch.pm)は、環境変数 `OTEL_BSP_SCHEDULE_DELAY` の値を `$schedule_delay` に入れるだけです。その値は、どこでも使われていません。スパンを受け取る `process` メソッドは、キューが512件（`OTEL_BSP_MAX_EXPORT_BATCH_SIZE` のデフォルト値）に満たなければ、何もせずに戻ります。

```perl:OpenTelemetry/Processor/Batch.pm（0.100、抜粋）
    method process ( @items ) {
        try {
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
        ...
    }
```

200回のリクエストを送ると、Perlのスパンは1回につき3件で計600件になります。そのうち届いたのは、ちょうど512件でした。残りの88件は、次に512件たまるまでキューに残ります。0.100のBatchプロセッサーは、トレースとログに共通の実装です。ログも、同じ条件がそろうまで送られません[^bsp-0028]。

[^bsp-0028]: 0.028までは、トレース専用の `OpenTelemetry::SDK::Trace::Span::Processor::Batch` が同じ処理を持っていました。試験版の0.029-TRIALで共通の実装に移り、`$schedule_delay` を使わない作りもそのまま引き継がれています。

## ワーカーの上限と送信の停止

キューが512件に達したときの送信にも、もう1つ条件があります。上のコードの `$function` は[IO::Async::Function](https://metacpan.org/pod/IO::Async::Function)のオブジェクトです。渡したコードを別のワーカープロセスで実行し、結果をイベントループ経由で受け取る仕組みです。SDKはエクスポーターの呼び出しをワーカープロセスに任せ、アプリケーションのプロセスが送信を待たないようにしています。

アプリケーションのプロセスは、ワーカーから結果を受け取るまでそのワーカーに次の仕事を渡しません。結果を受け取る処理が動くのは、IO::Asyncのイベントループが回っているときだけです。HTTP::Server::PSGIもStarmanも、IO::Asyncのループを回さないサーバーです。そのため結果は誰にも受け取られず、ワーカーは使用中のまま残ります。IO::Async::Functionのワーカーの上限はデフォルトで8つで、SDKでは環境変数 `OTEL_PERL_BSP_MAX_WORKERS` で変えられます。

![Batchプロセッサーとワーカープロセス](/images/20261128-batch-processor-fork.png)
*図1: Batchプロセッサーの送信の流れ。実線はスパンの流れ、ピンクの破線はPSGIサーバーでは完了しない結果の受け取りを表す。アプリケーションのプロセスは、キューが512件に達するとIO::Async::Functionのワーカーに送信を依頼する。ワーカーは送信を終えると結果をパイプで返すが、アプリケーションのプロセスがIO::Asyncのループを回さない限り、その結果は読まれず、ワーカーは次の依頼を受けない*

2,000回のリクエスト（Perlのスパン6,000件）を送ると、届いたのは3,584件、つまり512件の7回分でした。本書の構成ではそこで送信が止まり、コンテナの中にはトレースのワーカープロセスが8つ残っていました。ワーカーが8つあるのに7回分しか届かなかった理由は、確かめていません。止まるまでの回数は一定ではなく、0.028では8回分（4,096件）、0.100でログのエクスポーターを `none` にした構成では6回分（3,072件）でした。

同じ現象は、APIのリポジトリの[issue #23](https://github.com/jjatria/perl-opentelemetry/issues/23)「Telemetry output stops being sent」で2025年9月に報告されています。報告者が突き止めた原因は、IO::Asyncを使わないプロセスでは誰もループを回さないことです。報告には、ループを回すコードも添えられていました。2026年4月に、作者のjjatriaが[次のように返しています](https://github.com/jjatria/perl-opentelemetry/issues/23#issuecomment-4199416444)。

> This is correct. I've used a similar solution (by calling `loop_once` with a small enough timeout at the end of a loop) in some of my own code. I had the feeling this might have been mentioned in one of the OpenTelemetry::Guides, but it seems to be missing.
>
> （そのとおりです。私も自分のコードで、ループの最後に十分短いタイムアウトで `loop_once` を呼ぶ似た方法を使っています。OpenTelemetry::Guidesのどれかで触れられていた気がしていましたが、抜けているようです）

PerlのWebアプリケーションの多くは、IO::Async以外の仕組みで動いています。PlackのサーバーやMojoliciousがその例です。Mojoliciousについては、APIのGuidesのExportersの章に方法が載っています。[IO::Async::Loop::Mojo](https://metacpan.org/pod/IO::Async::Loop::Mojo)を入れて環境変数 `IO_ASYNC_LOOP` を `Mojo` にすれば、IO::AsyncのループがMojoliciousのイベントループの上で回ります（本書では未検証）。PlackのPSGIサーバーについての同じような説明は、Guidesにありません。

作者の考えは、2026年10月にSDKの[issue #27](https://github.com/jjatria/perl-opentelemetry-sdk/issues/27)への[返答](https://github.com/jjatria/perl-opentelemetry-sdk/issues/27#issuecomment-6150204783)で、さらにはっきりしました。筆者が `OTEL_BSP_SCHEDULE_DELAY` を使わない作りを報告したのに対し、作者はIO::Asyncのタイマーを使う実装を歓迎したうえで、次のように書いています。

> An application that does not run an IO::Async loop should not be using the batch processor, and this configuration option only makes sense for the batch processor ...
>
> （IO::Asyncのループを回さないアプリケーションは、Batchプロセッサーを使うべきではありません。この設定も、Batchプロセッサーでしか意味を持ちません）

ループを回さないPSGIのアプリケーションについて、作者が勧めるのはSimpleプロセッサーへの切り替えではありません。筆者がSimpleプロセッサーを中心にした説明をGuidesに足す案を[示す](https://github.com/jjatria/perl-opentelemetry/issues/23#issuecomment-6260523869)と、作者は、Simpleが役立つのは限られた場合だけで、ほとんどの場合は回すループを見つけるべきだと[返しました](https://github.com/jjatria/perl-opentelemetry/issues/23#issuecomment-6268297103)。PSGIのアプリケーションなら、IO::Asyncのループで動くPSGIサーバーの[Plack::Handler::Net::Async::HTTP::Server](https://metacpan.org/pod/Plack::Handler::Net::Async::HTTP::Server)を使う、という提案です。この構成は、章の最後の節で測ります。

ただ、SDKはエクスポーターを `otlp` にすると、ループの有無によらずBatchプロセッサーを組みます。一方で、よく使われるHTTP::Server::PSGIやStarmanは、ループを回さないサーバーです。何も設定しなければ、そうしたサーバーの上のアプリケーションは、作者が使うべきでないとする構成で動くことになります。次の節の回避策は、いまのサーバーのままBatchプロセッサーを使う場合の方法です。

## PSGIのミドルウェアで回避する

次のミドルウェアは、issue #23の方法をPSGIに当てはめて書いたものです。リクエストごとにIO::Asyncのループを1回だけ進めてワーカーの結果を受け取り、送信が止まらないようにします。それだけでは5秒ごとの送信にはならないので、指定した秒数が経っていれば `force_flush` でキューを送り出す処理も加えました。

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
| デフォルトのBatch | 3,584 | 26.7ms |
| Batch＋ループを進めるだけ | 5,632 | 26.7ms |
| Batch＋ループ＋5秒ごとの `force_flush` | 5,709 | 27.2ms |
| Simple（4章の構成） | 6,000 | 32.4ms |

ループを進めるだけで、送信は止まらなくなりました。5,632件は512件の11回分で、残りはキューの中です。5秒ごとの `force_flush` を足しても、最後のflushの後に終わったリクエストのスパンは残ります。このflushはリクエストを契機に動くので、リクエストが来ない間はキューが送られないままです。Simpleプロセッサーだけが6,000件すべてを届けましたが、平均の応答時間はBatchより5ms余り長くなりました。

## 終了時に失われるスパン

仕様では、プロバイダーの `Shutdown` はすべてのプロセッサーの `Shutdown` を呼び、プロセッサーの `Shutdown` は `ForceFlush` の効果を含まなければなりません。キューに残ったスパンは、`Shutdown` が呼ばれれば送られるはずです。CPANのSDKでは、この経路に2つの問題がありました。

1つ目は、SDKがプロセスの終了時に `shutdown` を自動では呼ばないことです。`END` ブロックやシグナルのハンドラーを登録していないので、アプリケーションが自分で呼ばない限りキューは終了とともに消えます。仕様が求めるのは呼ばれたときの後処理で、プロセスの終了時に自動で呼ぶことまでは求めていないので、こちらは仕様の違反ではありません。

2つ目は、`shutdown` を呼んでもキューが送られないことで、こちらは仕様の要求を満たしていません。Batchプロセッサーの `shutdown` は、終了済みを表すフラグを立ててから `force_flush` を呼びます。ところが `force_flush` の先頭は、そのフラグが立っていれば何もせずに成功を返す作りです。

```perl:OpenTelemetry/Processor/Batch.pm（0.100、抜粋）
    async method shutdown ( $timeout = undef ) {
        return EXPORT_RESULT_SUCCESS if $done;

        $done = 1;
        ...
        await $self->force_flush( maybe_timeout $timeout, $start );

        $self->report_dropped( 'terminating', scalar @queue ) if @queue;
        @queue = ();
        ...
    }

    async method force_flush ( $timeout = undef ) {
        return EXPORT_RESULT_SUCCESS if $done;
        ...
```

結果として、`shutdown` はキューを送らずに「終了時に捨てた」と数えて空にします。4章で見た、`force_flush` の行を消すと3件とも届かない現象は、これが原因です。0.028までのトレース専用のBatchプロセッサーも、同じ順序で書かれていました[^shutdown-fix]。

PSGIのサーバーで終了時にキューを送る処理は、アプリケーションの側に書きます。SIGTERMを受けたら通常の終了処理を通し、`END` ブロックで `force_flush` を呼びます。

```perl:app_otel_pump.psgi（抜粋）
if ( $ENV{SHUTDOWN_HOOK} ) {
    $SIG{TERM} = sub { exit 0 };
    END { otel_tracer_provider->force_flush(3)->get if $ENV{SHUTDOWN_HOOK} }
}
```

HTTP::Server::PSGIに3回のリクエストを送ってからコンテナを止め、終了時に呼ぶものを変えて比べました。Perlのスパンは、起動を確かめる1回のリクエストを含めて12件です。

| 終了時に呼ぶもの | ログのエクスポーター | 届いたPerlのスパン（12件中） | 停止にかかった時間 |
| --- | --- | --- | --- |
| トレースの `force_flush` | デフォルト（`otlp`） | 12 | 10.5秒 |
| トレースの `force_flush` | `none` | 12 | 0.4秒 |
| トレースの `shutdown` | デフォルト（`otlp`） | 6 | 10.5秒 |
| トレースの `shutdown` | `none` | 6 | 10.6秒 |
| トレースの `force_flush` とログの `shutdown` | デフォルト（`otlp`） | 12 | 10.6秒 |

トレースの `force_flush` を呼べば、12件すべてが届きます。ただ、0.100ではそれだけだと、停止に10.5秒かかりました。DockerがSIGTERMから10秒待ってSIGKILLで止めた時間です。`END` の `force_flush` はすぐに終わっていて、止まっていたのはその後のプロセスの終了の途中でした。4章で見た現象で、ログのエクスポーターを `none` にすると0.4秒で終了しました。ログのBatchプロセッサーが無い0.028では、`force_flush` だけで0.4秒でした。

`shutdown` を呼ぶ版は、ログのエクスポーターの設定によらず、3秒のタイムアウトを過ぎても戻りませんでした。0.028でも同じです。届いたのは止める前に送られていた6件で、最後のリクエストのスパンは失われました。4章のスクリプトでは有効だった、ログのプロバイダーの `shutdown` を足す方法も、PSGIサーバーの終了処理の中では戻りませんでした。`shutdown` が戻らない原因は特定できていません[^init]。いまのSDKでPSGIサーバーを速く止めながらキューを送り切れたのは、ログのエクスポーターを `none` にして、終了時にトレースの `force_flush` だけを呼ぶ構成です。

[^shutdown-fix]: 作者は2026年10月19日に、終了済みの印を立てる時点を `force_flush` の後に遅らせる変更（[49f3453](https://github.com/jjatria/perl-opentelemetry-sdk/commit/49f3453adddf1b8661cc565a6371bc4f2287decb)）をSDKのmainに入れました。筆者の再現手順でも、`shutdown` だけで3件届くようになりました。執筆時点では、この変更を含むリリースはありません。
[^init]: この確認では、Composeで `init: true` を指定しました。TERMのハンドラーを登録していない `app_otel.psgi` を `init: true` なしで動かすと、plackupがコンテナのPID 1になり、`docker compose stop` の10秒後にSIGKILLされるまで終了しませんでした。PID名前空間のinitは、ハンドラーを登録していないシグナルではデフォルトの動作（終了）を取らないからです（[pid_namespaces(7)](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html)）。上のように `$SIG{TERM}` を登録した場合は、PID 1でもハンドラーが呼ばれます。

## Starmanのprefork

本番のPSGIアプリケーションでは、[Starman](https://metacpan.org/pod/Starman)のようなpreforkのサーバーがよく使われます。preforkは、起動時に複数のワーカープロセスを作ってリクエストを各ワーカーに振り分ける方式です。Starmanを4ワーカーで起動し、8並列で2,000回のリクエストを送りました。最後にコンテナを止めてから、届いたスパンを数えています。

| 構成 | 届いたPerlのスパン（6,000件中） | 親子がそろったトレース（2,000本中） | 平均応答時間 | 停止にかかった時間 |
| --- | --- | --- | --- | --- |
| 未計装（`app.psgi`） | － | － | 37.3ms | 0.8秒 |
| デフォルトのBatch | 1,536 | 510 | 42.5ms | 10.8秒 |
| Batch＋ループ＋5秒ごとの `force_flush`＋終了時の `force_flush` | 3,955 | 1,316 | 42.9ms | 11.0秒 |
| Simple | 6,000 | 2,000 | 51.8ms | 0.6秒 |

デフォルトのBatchでは、6,000件のうち1,536件しか届きませんでした。Starmanのワーカーは、マスタープロセスで作られたBatchプロセッサーをforkで受け継ぎ、それぞれが自分のキューを持ちます。キューは512件ずつしか送られず、残りは停止とともに消えます。ただ、1ワーカーあたり約1,500件のスパンが作られた計算なので、512件ずつでもこれより多く届くはずです。1,536件にとどまった理由は確かめられていません。

ループを進める回避策を入れると、届いたスパンは3,955件に増えました。

停止には、デフォルトのBatchでも回避策でも11秒前後かかりました。0.028では、デフォルトのBatchの停止は0.7秒でした。停止の途中のコンテナの中を見ると、Starmanの4つのワーカーはどれもプロセスの終了の途中で待っていて、ログのBatchプロセッサーのワーカーはすでに終了していました。4章で見た現象と同じ形です。ログのエクスポーターを `none` にすると、停止は1秒以内に収まりました[^stm-nologs]。

| 構成 | 停止（ログのエクスポーターがデフォルト） | 停止（ログのエクスポーターが `none`） |
| --- | --- | --- |
| デフォルトのBatch | 10.8秒 | 0.7秒 |
| Batch＋ループ＋5秒ごとの `force_flush`＋終了時の `force_flush` | 11.0秒 | 0.9秒 |
| Simple | 0.6秒 | 0.6秒 |

[^stm-nologs]: ログのエクスポーターを `none` にした構成で届いたPerlのスパンは、デフォルトのBatchで2,048件、回避策で3,646件、Simpleで6,000件でした。0.028では、回避策の構成の停止に10.7秒かかり、原因を特定できていませんでした。

Starmanには、アプリケーションをマスタープロセスで読み込んでからワーカーをforkする `--preload-app` のオプションがあります。SDKを読み込んだ後にforkすると、ワーカーとIO::Asyncの状態が不整合になるのではないかと考え、このオプションを付けた場合も測りました。届いたスパンはデフォルトのBatchで1,536件、回避策で4,467件[^preload-err]、Simpleで6,000件で、停止にかかった時間も付けない場合と同じ傾向でした[^preload]。

ところが、plackupで起動したStarmanは、このオプションを付けなくてもマスタープロセスでアプリケーションを読み込みます。[Plack::Handler::Starman](https://metacpan.org/pod/Plack::Handler::Starman)のPODによれば、`plackup -s Starman` は `starman --preload-app` と同じです。上の表の測定も、forkの前にSDKを読み込んで行ったことになります。停止の途中に見たSDKのワーカーのプロセスも、Starmanのワーカーではなくマスタープロセスの子でした。forkの後にSDKを読み込む構成は、本書では測っていません。

[^latency]: 応答時間は、`curl` の `time_total` を2,000回分平均した値です。分布やCPU使用率は測っていません。
[^preload]: plackupに `--preload-app app_otel.psgi` の順で渡すと、`app_otel.psgi` が `--preload-app` の値として扱われ、PSGIファイルの指定が消えます。plackupは、自分が知らないオプションの次の引数をそのオプションの値とみなすからです。このとき起動するのは、カレントディレクトリのデフォルトのファイル `app.psgi` です。`--preload-app=1` と書くと正しく渡せます。
[^preload-err]: この測定では、2,000回のうち1回のリクエストがエラーになりました。

## Simpleプロセッサーの費用

ここまでの測定で、どのサーバーでもすべてのスパンを届けたのはSimpleプロセッサーだけでした。その代わり、Simpleプロセッサーはスパンが終わるたびにその場でCollectorへHTTPのリクエストを送ります。題材のアプリケーションでは、1回のリクエストで3回送ることになります。

費用は応答時間に表れました。HTTP::Server::PSGIへの直列のリクエストでは、平均の応答時間がデフォルトのBatchより5ms余り長くなりました[^latency]。Starmanで8並列にした場合は、未計装の37.3msに対して51.8msと、14ms余り長い値でした。6章では、サーバーのスパンと子のスパンの和との間に5〜12msの差がありました。この差にも、Simpleプロセッサーがリクエストの処理の途中で送信する費用が含まれます。ループを進める回避策で同じ3種類のリクエストを測ったときは、この差は2ms前後（1.8〜2.3ms）でした。

Simpleプロセッサーで計装したサーバーのスパンは、送信にかかった時間の分だけ長く記録されます。トレースで遅い区間を探すために計装したのに、区間の長さに計装の費用が含まれてしまいます。ループを回さないPSGIサーバーの上では、確実に届くこととアプリケーションの応答時間を乱さないことは、いまのCPANのSDKでは同時に満たせない条件です。

## ループを回すPSGIサーバー

作者が勧める構成も、HTTP::Server::PSGIと同じ手順で測りました。plackupに `-s Net::Async::HTTP::Server` を渡すと、PSGIのアプリケーションがIO::Asyncのループの中で動きます。SDKがワーカーを登録したループを回すのは、サーバー自身です[^nahs]。

| 段階 | SDK 0.100 | 定期送信を加えた版 |
| --- | --- | --- |
| 4回のリクエストの後に8秒待つ（Perlのスパン12件） | 0 | 12 |
| さらに2,000回の後に8秒待つ（Perlのスパン計6,012件） | 5,632 | 6,012 |
| 停止にかかった時間 | 0.6秒 | 0.5秒 |

0.100でも、2,000回の後まで送信は止まりませんでした。5,632件は512件の11回分にあたります。ループがワーカーの結果を読むので、ワーカーが使用中のまま残らないからです。平均の応答時間は27.7msで、HTTP::Server::PSGIのデフォルトのBatch（26.7ms）と同じ程度でした。その代わり、512件に満たない分は送られません。リクエストが4回だけの段階では、Perlのスパンは1件も届きませんでした。

この不足は、`OTEL_BSP_SCHEDULE_DELAY` の間隔で送る機能が無いことによるものです。11章で述べるとおり、筆者はこの機能をIO::Asyncのタイマーで実装する変更を作者に提案しています。その変更を加えたSDKでは、4回の段階でも2,000回の後でも、すべてのスパンが届きました[^branch]。ループを回すサーバーに移り、この機能が入れば、Simpleプロセッサーの応答時間の費用は無くなり、この章のミドルウェアでループを進める必要もなくなるはずです。ただ、止める直前に終わったリクエストのスパンは、終了時に送る処理が無ければ失われます。

最後に、本書で試していない実行方式があります。TwiggyやMojoliciousのようなイベントループのサーバーでは、別の問題が加わります。コールバックをまたいでSDKのコンテキストが引き継がれるかどうかです。上の測定の題材のアプリケーションは、リクエストを1つずつ同期的に処理するので、コールバックをまたぐ処理を含みません。

[^nahs]: Net-Async-HTTP-Server 0.15をデモの `cpanfile` に加えて測りました。ログのエクスポーターを `none` にしても、件数と停止の時間は変わりませんでした。このサーバーにはSIGTERMのハンドラーが無く、シグナルでそのまま終了するので、4章で見たプロセスの終了処理を通りません。
[^branch]: 筆者のブランチ（`batch-schedule-delay`）のSDKを、デモのイメージに重ねて読み込ませて測りました。2026年10月20日の時点で、この変更はSDKにマージされていません。
