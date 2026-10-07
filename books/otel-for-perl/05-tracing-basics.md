---
title: "遅いリクエストをトレースで追う"
---

## 題材のアプリケーション

PerlのWebアプリケーションで、あるリクエストだけが遅いという報告を受けたとします。アクセスログには応答時間が残っていますが、その時間がアプリケーションの中のどこで使われたのかは分かりません。本書の題材は、この状況を小さく再現したアプリケーションです。

アプリケーションは2つのサービスでできています。Perlの `report` は `GET /report` を受け取り、指定された日数分の注文を集計して、為替レートを掛けた結果をJSONで返します。為替レートの問い合わせ先は、Goで書いた別のHTTPサービス `rates` です。`report` は[PSGI](https://metacpan.org/pod/PSGI)のアプリケーションとして書き、[Plack](https://metacpan.org/pod/Plack)の `plackup` で起動します。PSGIはPerlのWebアプリケーションとWebサーバーの間のインターフェースで、Plackはその実装とツール群です。

![題材のアプリケーションの構成](/images/20261128-demo-topology.png)
*図1: 題材のアプリケーションの構成。実線はリクエスト、灰の破線はテレメトリーの送信、紫の破線はOBIによる観測を表す。利用者のリクエストは `report` が受け、`report` が `rates` を呼ぶ。テレメトリーは両方のサービスからCollectorへ送られ、CollectorはGrafanaのスタックへ転送する。OBIは9章でだけ使う*

遅さの原因を仕込んだ箇所は2つです。1つは集計処理で、1日分あたり3ミリ秒かかる処理の代わりに、その分だけ眠ります。もう1つは `rates` で、キャッシュにある通貨（USD、EUR、JPY）なら応答は20ミリ秒です。それ以外の通貨では、上流への問い合わせを模して600ミリ秒かけて応答します。

業務処理は `Demo::Report` というモジュールにまとめました。

```perl:lib/Demo/Report.pm
package Demo::Report;
use v5.40;
use HTTP::Tiny;
use JSON::PP;
use Time::HiRes ();

# 9章の実験で、RATES_KEEP_ALIVE=0 にしてKeep-Aliveを切れるようにしてある
my $http = HTTP::Tiny->new( timeout => 5, keep_alive => $ENV{RATES_KEEP_ALIVE} // 1 );
my $json = JSON::PP->new->canonical;

# 1日分の注文を集計するのに3ミリ秒かかる処理の代わり
sub aggregate ($days) {
    Time::HiRes::sleep( 0.003 * $days );
    return { days => $days, orders => 120 * $days };
}

# 下流のratesサービスから為替レートを取得する
sub fetch_rate ($currency) {
    my $base = $ENV{RATES_URL} // 'http://backend:8080';
    my $res  = $http->get("$base/rates?currency=$currency");
    die "rates: $res->{status} $res->{reason}\n" unless $res->{success};
    return $json->decode( $res->{content} )->{rate};
}

1;
```

PSGIのアプリケーションは、このモジュールの2つの関数を順に呼ぶだけです。

```perl:app.psgi
use v5.40;
use Plack::Request;
use JSON::PP;
use Demo::Report;

my $json = JSON::PP->new->canonical;

my $app = sub ($env) {
    my $req = Plack::Request->new($env);
    return [ 404, [ 'Content-Type' => 'text/plain' ], ['not found'] ]
        unless $req->path_info eq '/report';

    my $days     = $req->query_parameters->{days}     // 7;
    my $currency = $req->query_parameters->{currency} // 'USD';

    my $totals = Demo::Report::aggregate($days);
    my $rate   = Demo::Report::fetch_rate($currency);

    return [
        200, [ 'Content-Type' => 'application/json' ],
        [ $json->encode( { %$totals, currency => $currency, rate => $rate } ) ],
    ];
};
```

2つのサービスとCollectorは、[Docker Compose](https://docs.docker.com/compose/)で1つの構成にまとめています。Composeの設定とGoのサービスのコードは、それぞれ4章と6章で示します。本書で使ったコードと実験のスクリプトの置き場所は、[ymotongpoo/otel-for-perl](https://github.com/ymotongpoo/otel-for-perl)です。

## 外から測った応答時間

まず、何も計装していない状態で3種類のリクエストを送り、`curl` で応答時間を測りました。それぞれ3回ずつ送った結果です。

| リクエスト | 遅い箇所 | 応答時間 |
| --- | --- | --- |
| `days=7&currency=USD` | なし | 43〜45ms |
| `days=180&currency=USD` | 集計処理 | 562ms |
| `days=7&currency=BRL` | `rates` | 623〜626ms |

遅い2つのリクエストは、どちらも0.6秒前後です。アクセスログに残る数字だけを見ると、2つは同じ「遅いリクエスト」に見えます。ところが、`days=180` のリクエストはPerlの中の集計で、`currency=BRL` のリクエストはGoのサービスの応答で時間を使っています。直す場所は別々です。

この例でパラメーターから原因が分かるのは、原因を仕込んだのが筆者だからです。実際の運用では、どの入力でどこが遅くなるのかは事前に分かりません。リクエストの処理を区間に分け、区間ごとの時間をサービスをまたいで1本の記録として残す必要があります。その記録がトレースです。

## トレースとスパン

OpenTelemetryでは、1つの処理の区間を**スパン**と呼びます。スパンは名前、開始時刻と終了時刻、属性（キーと値の組）を持ち、自分を呼び出した区間である親のスパンを1つ指します。1回のリクエストの処理で作られたスパンをすべて集め、親子関係でつないだ木が**トレース**です[^concepts]。

今回のアプリケーションなら、`report` がリクエストを受けた区間をトレースの根にしたいところです。その子には、集計処理の区間と `rates` を呼ぶ区間を置きます。`rates` を呼ぶ区間のさらに子が、`rates` がリクエストを処理した区間です。この木があれば、`days=180` のリクエストでは集計の区間が長く、`currency=BRL` のリクエストでは `rates` の区間が長いことが一目で分かります。

![目指すトレースの形](/images/20261128-distributed-trace-basics.png)
*図2: 目指すトレースの形。矢印は親のスパンから子のスパンへ向かう。`report` のサーバーの区間を根にして、集計処理と `rates` の呼び出しが子になる。`rates` の中の区間は別のプロセスで作られるが、HTTPのヘッダー `traceparent` で渡されたトレースIDと親のスパンIDによって同じ木につながる*

スパンは、所属するトレースを表す16バイトの**トレースID**と、自分を表す8バイトの**スパンID**を持ちます。同じプロセスの中なら、親のスパンを変数やコンテキストで渡せます。プロセスをまたぐときは、トレースIDと親のスパンIDを通信に載せて相手に渡すことが必要です。この受け渡しを**コンテキストの伝搬**、渡す情報をトレースコンテキストと呼びます[^propagation]。

HTTPでのトレースコンテキストの形式は、W3Cの[Trace Context](https://www.w3.org/TR/trace-context/)が定めています。リクエストのヘッダー `traceparent` に、バージョン、トレースID、親のスパンID、フラグをハイフンでつないで入れます。

```
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

2つのサービスのスパンを同じトレースに入れるには、`report` から `rates` を呼ぶときにこのヘッダーを付けます。`rates` の側では、受け取ったヘッダーを読んで自分のスパンの親にする処理が必要です。`traceparent` はHTTPのヘッダーにすぎないので、送る側と受け取る側の言語が違っても構いません。今回はPerlからGoへ渡します。

[^concepts]: OpenTelemetryのドキュメントの[トレース](https://opentelemetry.io/ja/docs/concepts/signals/traces/)の説明に、スパンが持つ情報の一覧があります。
[^propagation]: [コンテキスト伝搬](https://opentelemetry.io/ja/docs/concepts/context-propagation/)の説明を参照してください。OpenTelemetryはW3C Trace Contextをデフォルトの形式にしています。
