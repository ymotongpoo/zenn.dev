---
title: "Plack/PSGIアプリケーションに組み込む"
---

## 計装の差分

2章の `app.psgi` にCPANの実装を組み込んだものが `app_otel.psgi` です。業務処理の `Demo::Report` には手を入れていません。2つのファイルの差分は次のとおりです。

```diff
 use v5.40;
+use OpenTelemetry::SDK;
+use OpenTelemetry 'otel_tracer_provider';
+use OpenTelemetry::Instrumentation 'HTTP::Tiny';
+use Plack::Builder;
 use Plack::Request;
 use JSON::PP;
 use Demo::Report;
 
-my $json = JSON::PP->new->canonical;
+my $json   = JSON::PP->new->canonical;
+my $tracer = otel_tracer_provider->tracer( name => 'demo-report' );
 
 my $app = sub ($env) {
     my $req = Plack::Request->new($env);
@@ -13,11 +18,20 @@
     my $days     = $req->query_parameters->{days}     // 7;
     my $currency = $req->query_parameters->{currency} // 'USD';
 
-    my $totals = Demo::Report::aggregate($days);
-    my $rate   = Demo::Report::fetch_rate($currency);
+    my $totals = $tracer->in_span(
+        aggregate => ( attributes => { 'report.days' => $days } ) => sub ( $span, $context ) {
+            Demo::Report::aggregate($days);
+        },
+    );
+    my $rate = Demo::Report::fetch_rate($currency);
 
     return [
         200, [ 'Content-Type' => 'application/json' ],
         [ $json->encode( { %$totals, currency => $currency, rate => $rate } ) ],
     ];
 };
+
+builder {
+    enable 'OpenTelemetry';
+    $app;
+};
```

足したのは4つです。SDKを読み込む1行、トレーサーを取得する1行、HTTPクライアントの計装を有効にする1行、そしてミドルウェアと子スパンです。このうちHTTPクライアントの計装は6章で扱います。

実行には、4章の `app_otel_simple.psgi` を使いました。

```shell
FRONTEND_CMD="plackup -E deployment -s HTTP::Server::PSGI -p 5000 app_otel_simple.psgi" \
  docker compose up -d
```

## ミドルウェアが作るサーバースパン

[Plack::Middleware::OpenTelemetry](https://metacpan.org/release/ABH/Plack-Middleware-OpenTelemetry-0.262410)は、`enable 'OpenTelemetry'` で有効になるミドルウェアです。PSGIのリクエストごとにスパンを1つ作ります。種類（kind）は、外からのリクエストを受けた区間を表すSERVERです。ソースから、リクエストを受けてからアプリケーションを呼ぶまでの部分を抜き出します。

```perl:Plack/Middleware/OpenTelemetry.pm（0.262410、抜粋）
    my $context = otel_propagator->extract(
        $env, undef,
        sub ($carrier, $key) {
            $carrier->{'HTTP_' . uc $key};
        },
    );
    ...
    my $span = $tracer->create_span(
        name       => "$method request",
        ...
        parent     => $context,
        kind       => SPAN_KIND_SERVER,
        attributes => { ... },
    );

    my $previous_context = otel_current_context;
    $context = otel_context_with_span($span, $context);
    otel_current_context = $context;
```

最初の `extract` は、PSGIの環境変数 `$env` から `HTTP_TRACEPARENT` を読みます。呼び出し元が `traceparent` ヘッダーを付けていれば、ミドルウェアはそのトレースの続きとしてスパンを作ります。アプリケーションを呼ぶのは、作ったスパンを現在のコンテキストに入れた後です。そのためアプリケーションの中で作るスパンは、ミドルウェアのスパンを親にします。アプリケーションが応答を返すと、ミドルウェアはステータスコードと応答の大きさを属性に入れてスパンを終えます。

## 集計処理の子スパン

集計処理の区間は、トレーサーの `in_span` で作りました。`in_span` は名前と属性とコードブロックを受け取り、スパンを開始して現在のコンテキストに入れてからブロックを実行します。ブロックの戻り値は、そのまま `in_span` の戻り値です。そのため `$totals` には集計結果が入ります。ブロックが例外を投げると、`in_span` は例外をスパンに記録し、ステータスをERRORにしてから例外を投げ直します。

ブロックが例外なく終わったとき、`in_span` はステータスを自動でOKにします。一方、PerlのInstrumentation Guideは「By default, all spans are Unset」と書いています。ガイドの説明では、OKは明示的に成功を記録したいときのためのものです。仕様は計装ライブラリにOKを設定しないよう求めていますが、アプリケーションの開発者がOKを設定することは認めています[^status]。`in_span` はアプリケーションのコードから呼ぶAPIなので、仕様に反するわけではありません。ただ、ミドルウェアが作るスパンのステータスは未設定のままです。そのため同じトレースの中に、OKのスパンと未設定のスパンが混在します。

[^status]: 仕様の[Set Status](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/trace/api.md#set-status)の節にあります。

## 受け取ったトレース

2章の3種類のリクエストを送り、Collectorが保存したデータからトレースの木を組み立てました。スパンごとに名前、種類、所要時間を示しています。

```
# days=7&currency=USD
report: 'GET request'   SERVER    53.9ms
  report: 'aggregate'   INTERNAL  21.3ms  report.days=7
  report: 'GET'         CLIENT    21.8ms
    rates: 'GET /rates' SERVER    20.4ms

# days=180&currency=USD
report: 'GET request'   SERVER   576.7ms
  report: 'aggregate'   INTERNAL 540.4ms  report.days=180
  report: 'GET'         CLIENT    22.8ms
    rates: 'GET /rates' SERVER    20.5ms
```

`days=180` のリクエストでは、576.7msのうち540.4msが集計処理の時間です。2章では外から見て「遅い」としか言えなかったリクエストを、Perlのプロセスの中の区間に分けられました。`report.days` の属性からは、遅い処理が入力の日数に比例することも読み取れます。

## サーバースパンの属性とセマンティック規約

ミドルウェアのサーバースパンには、次の属性が付いていました。

| 属性 | 値の例 |
| --- | --- |
| `http.request.method` | `GET` |
| `http.response.status_code` | `200` |
| `url.full` | `http://localhost:5000/report?days=7&currency=USD` |
| `url.path` | `/report` |
| `url.query` | `days=7&currency=USD` |
| `url.scheme` | `http` |
| `server.address` | `localhost:5000` |
| `client.address` | `172.20.0.1` |
| `user_agent.original` | `curl/8.18.0` |
| `http.response.body.size` | `49` |
| `plack.version` | `1.0054` |

属性の名前は、OpenTelemetryの**セマンティック規約**に沿っています。セマンティック規約は、スパンの名前と属性を決めた取り決めです。対象は、HTTPのリクエストやデータベースの呼び出しのような共通の処理です。規約に揃っていれば、言語の違うサービスのスパンを同じクエリで集計できます。

ただし、スパンの名前と一部の属性は規約と食い違っています。[HTTPのスパンの規約](https://github.com/open-telemetry/semantic-conventions/blob/v1.44.0/docs/http/http-spans.md)は、スパン名を次のように定めています。

> HTTP span names SHOULD be `{method} {target}` if there is a (low-cardinality) `target` available. If there is no (low-cardinality) `{target}` available, HTTP span names SHOULD be `{method}`.
>
> （HTTPのスパン名は、カーディナリティの低い `target` があれば `{method} {target}` にするべきです。カーディナリティの低い `{target}` が無ければ、HTTPのスパン名は `{method}` にするべきです）

サーバーのスパンで `{target}` に入るのは、`/users/{id}` のようなルートの型を表す `http.route` です。PSGIのアプリケーションは、環境変数を受け取るコードリファレンスにすぎません。ルーティングはアプリケーションの内側でフレームワークが行うので、ミドルウェアからはルートが分かりません。この場合の規約どおりのスパン名は `GET` です。ミドルウェアは `GET request` という名前を付けていました。HTTPのスパンの規約は、サーバーのスパンでは `server.address` と `server.port` をHostヘッダーなどから分けて入れることも求めています。ミドルウェアの `server.address` は、Hostヘッダーの値そのままの `localhost:5000` です。値にはポートまで入り、`server.port` はありません。

もう1つ、ミドルウェアの依存関係も3章の指針と食い違います。0.262410のメタデータは、実行時の依存として `OpenTelemetry::SDK` を宣言しています。ミドルウェアの `resource_attributes` オプションを指定したときに、SDKのResourceのクラスを使うためです。そのため、ミドルウェアを入れるとSDKとIO::Asyncなどの依存も入ります。計装ライブラリはAPIにだけ依存してSDKの選択をアプリケーションに任せる、という分担がここでは成り立っていません。
