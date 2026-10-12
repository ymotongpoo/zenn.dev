---
title: "OTLPログの本文に入ったJSON文字列をAlloyのOTTLで属性に展開する"
emoji: "🧹"
type: "tech"
topics: ["OpenTelemetry", "grafana", "Loki", "Alloy", "OTTL"]
published: true
published_at: 2026-10-13 09:00
---

## はじめに

こんにちは、Grafana Labsでデベロッパーアドボケイトをしているものです。

最近、コーディングエージェントのGUIとして[T3 Code](https://github.com/pingdotgg/t3code)を試しています。T3 CodeはOTLPでトレース、メトリクス、ログを送れるので、手元で動かしているGrafana Alloy（OpenTelemetry Collector）を経由してGrafana Cloudに集め、ダッシュボードを作って眺めていました。

ところが、Grafana CloudのLogs（Loki）でT3 Codeのログを開くと、本文に `\"` とエスケープが大量に入った文字列が並んでいました。中身はJSONのように見えるのに、フィールドとして検索も集計もできません。この記事では、このログをAlloyの `otelcol.processor.transform` で書き換え、Lokiに届いた時点で構造化ログになっている状態にした作業をまとめます。

## Lokiに届いていたログ

まず、Lokiに保存されている生の行を確認しました。`gcx logs query -o json` で取り出したログ行の一例です。

```json
["httpReadiness.timedOut","{\"baseUrl\":\"http://127.0.0.1:52288/\",\"requestUrl\":\"http://127.0.0.1:52288/\",\"timeoutMs\":2000,\"intervalMs\":100,\"probeTimeoutMs\":1000,\"attempts\":19,\"lastFailure\":{\"attempt\":19,\"cause\":{\"_tag\":\"SshReadinessError\",\"message\":\"Backend readiness probe failed at http://127.0.0.1:52288/.\",\"cause\":{\"_tag\":\"HttpClientError\",\"message\":\"Transport error (GET http://127.0.0.1:52288/)\",\"cause\":{\"name\":\"Error\",\"message\":\"read ECONNRESET\"}}}}}"]
```

外側はJSONの配列で、要素は2つの文字列です。1つ目はイベント名、2つ目はJSONを文字列化したものです。内側の引用符が `\"` になっているのは、外側の配列の中で文字列としてエスケープされているからで、GrafanaやLokiのせいではありません。

このフォーマットは、T3 Codeのログの出し方が原因です。T3 Codeは[Effect](https://effect.website/)で書かれていて、ログは次のようにイベント名とオブジェクトの2引数で出しています（[SSHトンネルの実装](https://github.com/pingdotgg/t3code/blob/main/packages/ssh/src/tunnel.ts)より）。

```ts
yield* Effect.logWarning("ssh.environment.tunnel.create.failed", {
  ...sshTargetLogFields(resolvedTarget),
  key,
  cause,
});
```

デスクトップアプリはEffectの `OtlpLogger` でログを送っていて（[DesktopObservability.ts](https://github.com/pingdotgg/t3code/blob/main/apps/desktop/src/app/DesktopObservability.ts)）、実データを見る限り、2つの引数がOTLPのログ本文（body）の配列になり、オブジェクトは文字列化されてから入っています。OpenTelemetryの[ログデータモデル](https://opentelemetry.io/docs/specs/otel/logs/data-model/)ではbodyにマップも入れられるので、オブジェクトをマップのまま送るか、ログ属性として送ってくれれば、この問題は起きませんでした。

## 実データの内訳

変換を書く前に、どんな形のログがどれだけあるのかを数えました。直近24時間のwarnとerrorのログ1,030件を分類すると、次のようになりました。

| 本文の形 | 件数 | 2要素目の中身 |
|---|---|---|
| `[イベント名, JSON文字列]` | 790 | JSONとして読める |
| `[イベント名, Cause(...)を含む文字列]` | 16 | JSONとして読めない |
| ただの文字列 | 224 | なし |

厄介なのは2行目です。SSHトンネルの `ssh.environment.tunnel.existing.stale` と `ssh.environment.tunnel.create.failed` の2イベントでは、`cause` の値がEffectの `Cause` の文字列表現のまま、引用符なしで埋め込まれていました（ホスト名などは伏せています）。

```text
{"alias":"devbox.local","hostname":"devbox.local","username":"me","port":22,"key":"...","localPort":64275,"remotePort":3774,"cause":Cause([Fail(SshReadinessError: Timed out waiting 2000ms for backend readiness at http://127.0.0.1:64275/. ...)])}
```

`{` で始まるのでJSONに見えますが、`"cause":` の後ろが文字列にもオブジェクトにもなっていないので、JSONパーサーは失敗します。この2イベントだけは、JSONとしてではなく正規表現で項目を拾う必要があります。

## LogQLで頑張る方法とAlloyで直す方法

対応の選択肢は以下の3つが考えられました。

1. Grafana Cloud側のクエリでエスケープされた文字列をパースする方法
2. Alloyの中で変換する方法
3. T3 Code本体を直す方法
 
本体の修正はPull Requestを出してリリースを待つことになるので、手元でできる2つを先に試しました。

LogQLでも処理はできます。Lokiの `| json` はトップレベルの配列を展開しないので、[テンプレート関数](https://grafana.com/docs/loki/latest/query/template_functions/)の `fromJson` で配列を開き、2要素目を行に置き直してから `| json` に渡します。JSONとして読めるログ向けのクエリはこうなりました。

```logql
{service_namespace="t3code"} | detected_level=~"warn|error" |~ `^\[`
  | label_format event="{{ index (fromJson __line__) 0 }}"
  | event!~`ssh\.environment\.tunnel\.(existing\.stale|create\.failed)`
  | line_format "{{ index (fromJson __line__) 1 }}"
  | json
```

これに加えて、`Cause(...)` を含む2イベント向けに `regexp` で項目を抜き出すクエリと、配列ではない通常のログ向けのクエリが必要で、ダッシュボードのログパネルは3本のクエリを並べる形になりました。上の表の1,030件を3本で漏れなく拾え、パーサーエラーも0件だったので、表示としては動きます。

しかし、この方法ではLokiに保存されているログ自体は配列のままです。Exploreで調べるたびに同じ前処理を書く必要があり、アラートや別のダッシュボードを作るときも同じです。クエリは素直なままにしておきたかったので、取り込み前にAlloyで変換する方法を選びました。

## 変換の方針

Alloyでは、OpenTelemetry Collectorのtransform processorにあたる [`otelcol.processor.transform`](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.transform/) を使い、OTTL（OpenTelemetry Transformation Language）で書き換えます。方針は次のとおりです。

- 本文が「2つの文字列からなる配列」のログだけを対象にし、それ以外のログ、メトリクス、トレースには触らない
- イベント名を `event.name` 属性にし、本文もイベント名だけにする
- 2要素目がJSONとして読めるなら、そのフィールドをログ属性に展開する
- `Cause(...)` を含む2イベントは、元の文字列を `t3.context.raw` 属性に残したうえで、接続先の項目だけを正規表現で属性にする

Grafana CloudのOTLPエンドポイントでは、ログの本文がLokiのログ行に、ログ属性がstructured metadataになります（[OTLPの形式に関する説明](https://grafana.com/docs/grafana-cloud/send-data/otlp/otlp-format-considerations/)）。属性に展開しておけば、Loki側では `| json` なしでフィルタできます。

## Alloyの設定

もともとAlloyには、手元のアプリからOTLPを受けてGrafana Cloudへ転送するパイプラインがありました。ここにログだけを通すtransformを挟みます。receiverの `output` は、ログの行き先だけを差し替えました。

```alloy
otelcol.receiver.otlp "ai_apps" {
	grpc { endpoint = "127.0.0.1:4317" }
	http { endpoint = "127.0.0.1:4318" }

	output {
		metrics = [otelcol.processor.deltatocumulative.ai_apps.input]
		logs    = [otelcol.processor.transform.ai_apps_logs.input]
		traces  = [otelcol.exporter.otlphttp.ai_grafana_cloud.input]
	}
}
```

transformの本体は次のとおりです。条件式が長いので、同じ条件が何度も出てくる点は力業で頑張った結果だとご理解ください。

```alloy
// T3 Codeのログは [イベント名, JSONコンテキスト文字列] の形で届くため、
// Grafana Cloudへ送る前にイベント名を本文、コンテキストを属性へ展開する。
otelcol.processor.transform "ai_apps_logs" {
	error_mode = "ignore"

	log_statements {
		context = "log"
		statements = [
			// (1) イベント名を属性に残す
			`set(attributes["event.name"], body[0]) where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1])`,

			// (2) Cause(...) を含む2イベントは、元の文字列を残して項目を正規表現で拾う
			`set(attributes["t3.context.raw"], body[1]) where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1]) and (body[0] == "ssh.environment.tunnel.existing.stale" or body[0] == "ssh.environment.tunnel.create.failed")`,
			`merge_maps(cache, ExtractPatterns(body[1], "\"alias\":\"(?P<alias>[^\"]+)\""), "upsert") where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1]) and (body[0] == "ssh.environment.tunnel.existing.stale" or body[0] == "ssh.environment.tunnel.create.failed")`,
			`merge_maps(cache, ExtractPatterns(body[1], "\"hostname\":\"(?P<hostname>[^\"]+)\""), "upsert") where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1]) and (body[0] == "ssh.environment.tunnel.existing.stale" or body[0] == "ssh.environment.tunnel.create.failed")`,
			`merge_maps(cache, ExtractPatterns(body[1], "\"username\":\"(?P<username>[^\"]+)\""), "upsert") where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1]) and (body[0] == "ssh.environment.tunnel.existing.stale" or body[0] == "ssh.environment.tunnel.create.failed")`,
			`merge_maps(cache, ExtractPatterns(body[1], "\"port\":(?P<port>[0-9]+)"), "upsert") where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1]) and (body[0] == "ssh.environment.tunnel.existing.stale" or body[0] == "ssh.environment.tunnel.create.failed")`,
			`merge_maps(cache, ExtractPatterns(body[1], "\"localPort\":(?P<localPort>[0-9]+)"), "upsert") where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1]) and (body[0] == "ssh.environment.tunnel.existing.stale" or body[0] == "ssh.environment.tunnel.create.failed")`,
			`merge_maps(cache, ExtractPatterns(body[1], "\"remotePort\":(?P<remotePort>[0-9]+)"), "upsert") where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1]) and (body[0] == "ssh.environment.tunnel.existing.stale" or body[0] == "ssh.environment.tunnel.create.failed")`,
			`merge_maps(attributes, cache, "upsert") where (attributes["event.name"] == "ssh.environment.tunnel.existing.stale" or attributes["event.name"] == "ssh.environment.tunnel.create.failed") and IsMap(cache)`,

			// (3) それ以外で { から始まるものはJSONとしてパースし、属性に展開する
			`merge_maps(cache, ParseJSON(body[1]), "upsert") where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1]) and body[0] != "ssh.environment.tunnel.existing.stale" and body[0] != "ssh.environment.tunnel.create.failed" and IsMatch(body[1], "^\\s*\\{")`,
			`merge_maps(attributes, cache, "upsert") where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1]) and body[0] != "ssh.environment.tunnel.existing.stale" and body[0] != "ssh.environment.tunnel.create.failed" and IsMap(cache)`,

			// (4) 最後に本文をイベント名だけにする
			`set(body, body[0]) where IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1])`,
		]
	}

	output {
		logs = [otelcol.exporter.otlphttp.ai_grafana_cloud.input]
	}
}
```

## OTTLを書くときに気にした点

ほぼすべての文に `IsList(body) and Len(body) == 2 and IsString(body[0]) and IsString(body[1])` を付けています（例外は、（1）で設定した `event.name` を条件にしている1文だけです）。この条件を満たさないログ（表の224件のような通常の文字列ログや、他のアプリから同じreceiverに届くログ）は、どの文にも当てはまらず、そのまま素通りします。同じreceiverでClaude CodeやCodexのログも受けているので、T3 Codeの形に一致するものだけを書き換えるようにしました。

本文の書き換え（4）を最後に置いているのは、それまでの文がすべて `body[0]` と `body[1]` を読むからです。先に `set(body, body[0])` を実行すると、以降の文の条件 `IsList(body)` が偽になり、属性の展開が一切行われません。OTTLの文は上から順に評価されるので、元の値を読む文を先に、上書きする文を後に並べます。

`cache` は、ログレコードごとに用意される一時的なマップです。`ParseJSON` や `ExtractPatterns` の結果をいったん `cache` に集め、最後に `merge_maps(attributes, cache, "upsert")` で属性へまとめて移しています。`Cause(...)` のイベントでは、正規表現をフィールドごとに分けました。`create.failed` には `localPort` と `remotePort` がないので、1つの正規表現で全項目を拾おうとすると、項目の有無に応じた任意グループを組む必要があります。LogQL版ではそうしていて、パターンが読みにくくなっていました。

`error_mode = "ignore"` にしているので、ある文がエラーを返しても、そのログを捨てずに次の文へ進みます。とはいえ、エラーに頼って分岐するとAlloyのログにエラーが出続けるので、`Cause(...)` の2イベントは名前で除外し、`ParseJSON` には `{` で始まる文字列だけを渡しています。

もうひとつ、Alloyの設定では文をバッククォートの文字列で書いています。Alloyのバッククォート文字列はエスケープを解釈しないので、`\"` はそのままOTTLに渡ります。考えるべきエスケープがOTTLの文字列リテラルの1段だけになり、正規表現を書くときに混乱せずに済みました[^prefix]。

[^prefix]: Alloy v1.20.1でこの設定を読み込むと、`one or more paths were modified to include their context prefix` という情報ログが出ます。最近のOTTLでは `body` を `log.body`、`attributes` を `log.attributes` のようにコンテキスト名付きで書くことが推奨されていて、省略した書き方は読み込み時に補われます。動作は変わりませんが、新しく書くならプレフィックス付きにしておくとよいでしょう。

## 本番に入れる前の確認

いきなり稼働中のAlloyを書き換えず、まず一時ディレクトリに検証用の設定を置き、別ポートでAlloyを起動しました。receiverの出力先を `otelcol.exporter.debug` にしておけば、変換後のログレコードがAlloyの標準出力に出ます。

```shell
alloy run --stability.level=experimental \
  --server.http.listen-addr=127.0.0.1:12346 \
  /tmp/t3code-alloy-test/config.alloy
```

そこへ、実データと同じ形の合成ログをOTLP/HTTPのJSONで送りました。JSON contextの配列、`Cause(...)` を含む配列、通常の文字列の3種類を1回で送れるようにしています。

```json
{
  "resourceLogs": [{
    "resource": {"attributes": [
      {"key": "service.name", "value": {"stringValue": "t3code-desktop"}},
      {"key": "service.namespace", "value": {"stringValue": "t3code"}}
    ]},
    "scopeLogs": [{
      "scope": {"name": "t3code-test"},
      "logRecords": [
        {
          "timeUnixNano": "1791513000000000000",
          "severityText": "WARN",
          "body": {"arrayValue": {"values": [
            {"stringValue": "Relay client reported a transport warning"},
            {"stringValue": "{\"pid\":123,\"tunnelId\":\"synthetic-id\",\"tunnelName\":\"test-tunnel\",\"output\":\"sample output\"}"}
          ]}}
        },
        {
          "timeUnixNano": "1791513001000000000",
          "severityText": "WARN",
          "body": {"arrayValue": {"values": [
            {"stringValue": "ssh.environment.tunnel.existing.stale"},
            {"stringValue": "{\"alias\":\"sample-alias\",\"hostname\":\"sample-host\",\"username\":\"sample-user\",\"port\":22,\"key\":\"sample-key\",\"localPort\":64275,\"remotePort\":3774,\"cause\":Cause(SshCommandError: sample error)}"}
          ]}}
        },
        {
          "timeUnixNano": "1791513002000000000",
          "severityText": "WARN",
          "body": {"stringValue": "plain log stays unchanged"}
        }
      ]
    }]
  }]
}
```

```shell
curl -H 'Content-Type: application/json' \
  --data-binary @sample.json \
  http://127.0.0.1:14318/v1/logs
```

debug exporterの出力で、1件目はフィールドが属性に展開され、2件目は `t3.context.raw` と接続先の項目が属性になり、3件目は本文がそのまま残っていることを確認しました。

あとは稼働中の設定に組み込むだけです。`alloy validate` で構文を確認してから設定を再読み込みし、ヘルスチェックを確認しました。

```shell
alloy validate --stability.level=experimental config.alloy
curl -fsS http://127.0.0.1:12345/-/healthy
```

コンポーネントのつながりは、AlloyのHTTP APIの `/api/v0/web/components` で確かめられます。receiverの参照先に新しいtransformが入り、transformからexporterへつながっていて、どのコンポーネントもhealthyでした。同じ変換は、別のLinuxマシンでsystemdから動かしているAlloyにもそのまま入れています。

## Lokiでの見え方

変換後に届いたログをLokiで見ると、ログ行はイベント名だけになり、JSONの各フィールドはstructured metadataに入っていました。`httpReadiness.timedOut` の例です（一部のメタデータは省略しています）。

```json
{
  "line": "httpReadiness.timedOut",
  "structuredMetadata": {
    "event_name": "httpReadiness.timedOut",
    "attempts": "20",
    "baseUrl": "http://127.0.0.1:55590/",
    "intervalMs": "100",
    "probeTimeoutMs": "1000",
    "timeoutMs": "2000",
    "lastFailure_attempt": "20",
    "lastFailure_cause_tag": "SshReadinessError",
    "lastFailure_cause_message": "Backend readiness probe failed at http://127.0.0.1:55590/.",
    "lastFailure_cause_cause_tag": "HttpClientError",
    "lastFailure_cause_cause_message": "Transport error (GET http://127.0.0.1:55590/)",
    "lastFailure_cause_cause_cause_name": "Error",
    "lastFailure_cause_cause_cause_message": "connect ECONNREFUSED 127.0.0.1:55590",
    "detected_level": "warn"
  }
}
```

属性名の `.` は `_` に置き換わり、`lastFailure` のような入れ子のマップは `_` でつないだキーにフラット化されています。`_tag` のキーは、アンダースコアが重ならずに `lastFailure_cause_tag` となっていました。OTTLの側でフラット化を書かなくても、Grafana Cloudの取り込みで扱いやすい形になります。

これで、LogQLから前処理が消えました。イベント名で絞るなら次の1行で済みます。

```logql
{service_namespace="t3code"} | event_name="httpReadiness.timedOut"
```

イベント名ごとの件数も、structured metadataでそのまま集計できます。

```logql
sum by (event_name) (
  count_over_time({service_namespace="t3code"} | detected_level="warn" | event_name!="" [24h])
)
```

## 残っている課題

この変換は、Alloyに設定を入れた後に届いたログにだけ有効です。それ以前にLokiへ保存されたログは配列のままなので、過去のログを調べるときはLogQL版の前処理が必要です（もっとも今回はOTTLの変換の記事を書くためだけに行ってるので特に実施しませんが）。

また、`Cause(...)` を含むイベントを名前で列挙しているので、T3 Codeが同じ書き方のイベントを増やすと、その分はJSONとしてのパースに回って失敗します。その場合、属性は展開されず、最後の文で本文がイベント名に置き換わるので、2要素目の文字列はLokiに残りません。対策としては、`ParseJSON` が使えなかったときにも `t3.context.raw` に元の文字列を残す文を足すのがよさそうです。

根本的には、T3 Code側でオブジェクトをマップのbodyか属性として送れば、この変換は必要ありません。Alloyでの変換は、本体が直るまでのつなぎとして使い、直ったら外すつもりです。

## おわりに

送信元のログ形式に手を出せないときでも、Collectorを経由していれば、取り込み前に形を整えられます。OTTLの文は長くなりがちですが、対象を厳しく絞る条件を全文に付け、元の値を読む文を先に、上書きする文を最後に並べれば、他のログを巻き込まずに書き換えられます。手元のAlloyにOTLPを集めている人は、クエリで頑張る前にtransformを1段挟むことを検討してみてください。
