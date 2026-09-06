---
title: "ゼロコード計装の配布"
---

SDKディストリビューションを用意しても、`Setup` を呼び出せないサービスは残ります。保守が難しいレガシーサービス、ソースコードを変更できないサードパーティ製のバイナリ、計装の改修に着手できないチームのサービスです。こうしたサービスからも、基盤側の作業で最低限のテレメトリーを生成できるようにします。

## 計装の最低保証ライン

コードを変更せずに計装する手法を、OpenTelemetryでは[**ゼロコード計装**](https://opentelemetry.io/docs/zero-code/)と呼びます。セルフサービス基盤では、ゼロコード計装を手動計装の代替ではなく、**計装の最低保証**として使います。開発チームが作業しなくてもHTTPやgRPCの入出力をトレースとメトリクスとして記録し、業務固有の情報が必要なサービスには手動計装を追加します。

最低限のトレースが先にあれば、開発チームは不足している業務情報を具体的に判断できます。何も記録されていない状態では、どの計装から追加すべきかも判断できません。

![計装の注入ポイント比較](/images/20260825-injection-points.png)
*図1　縦軸は、ソースコードからカーネルまで、計装を挿入できる位置を表します。実線は実行までの関係、点線は各計装方式が介入する位置です。変更できる位置によって、選択できる方式が決まります。*

## 言語別の選択肢

ゼロコード計装の方式は言語のランタイム特性で決まります。主要言語の選択肢を整理します。

| 言語 | 方式 | 特記事項 |
|---|---|---|
| Java | javaagentによるバイトコード書き換え | 対応ライブラリが多い |
| Python | opentelemetry-instrumentコマンドによる実行時パッチ | distroの差し替え機構もある |
| Node.js | requireフックによる実行時パッチ | auto-instrumentations-nodeに集約 |
| .NET | CLRプロファイラAPIによる注入 | 公式の自動計装が提供されている |
| Go | eBPF（実行時）またはビルド時のコード書き換え | 動的なランタイムを持つ言語とは注入方法が異なる |

JavaやPythonのように動的なランタイムを持つ言語では、実行時にコードを差し替えられます。静的にコンパイルされたGoの単一バイナリには、実行時にエージェントを読み込む機構がありません。そのため、Goではカーネル側から観測するeBPF方式か、コンパイル時に計装コードを加えるビルド時方式を使います。

## GoのeBPF自動計装

GoのeBPF計装は、**OBI**（OpenTelemetry eBPF Instrumentation）で開発されています。Grafana LabsがBeylaを寄贈して始まったプロジェクトで、2026年8月時点の最新版はv0.12.2です。v0系のため、破壊的変更の可能性が残っています[^obi]。対象プロセスの外からeBPFでシステムコールや関数呼び出しを観測するため、バイナリを変更しません。HTTP、gRPC、主要なデータベースやメッセージングのプロトコル、OpenAIやAnthropicなどのGenAI API呼び出しを捕捉できます。

[^obi]: 2026年8月17日のv0.11.0ではGoのトレースAPIの自動計装が入り、従来 opentelemetry-go-instrumentation が担っていた領域を取り込みつつあります。プロジェクトの2026年の目標はstable 1.0です（[公式ブログ](https://opentelemetry.io/blog/2026/obi-goals/)）。

ただし、eBPFによるGoバイナリの関数レベル計装には制約があります。goroutineとOSスレッドが一対一に対応しないため、リクエストの文脈を追跡しにくくなります。コンパイラの最適化で関数の構造が変わり、コンテキスト伝播のために実行中のプロセスのメモリへ書き込む操作にも危険が伴います。詳細は別の本「OpenTelemetry eBPF Instrumentationの舞台裏」で、CPUとメモリの仕組みから説明しています。本書では、GoのeBPF計装には取得できる情報の粒度と安定性に制約があることを前提に、配布方法を考えます。

<!-- 公開後に books/go-ebpf-primer へのリンクをここに入れる -->

## ビルド時計装

Goでは、コンパイル時に計装コードを組み込むこともできます。DatadogのOrchestrionとAlibabaの計装ツールを統合して開発された公式ツール**otelc**は、2026年7月にv1.0でstableへ達しました。2026年8月時点の最新版はv1.1.0です[^otelc]。

[^otelc]: 経緯は[公式ブログのv1発表](https://opentelemetry.io/blog/2026/go-compile-time-instrumentation-v1/)にまとまっています。v1.0.0は不具合でretractされているため、使うならv1.0.1以降です。

最初に計装用の依存を固定し、以降のビルドコマンドを置き換えます。

```console
$ otelc pin
$ otelc go build ./...
```

`otelc` はGoの `-toolexec` 機構を使い、コンパイルの過程で対象ライブラリの呼び出しに計装コードを差し込みます。2026年8月時点で `net/http` や `database/sql`、gRPC、Redis、Kafkaといった主要ライブラリに対応し、トレースとメトリクスを生成します。ログへのtrace context注入にも対応しています。

Goでは、eBPF、ビルド時、手動計装を選べます。次の表で、変更箇所と運用上の違いを比較します。

| 観点 | eBPF（OBI） | ビルド時（otelc） | 手動計装（ディストリビューション） |
|---|---|---|---|
| コード変更 | 不要 | 不要 | 必要 |
| ビルドの変更 | 不要 | ビルドコマンドの差し替え | 依存の追加 |
| 実行時の特権 | 必要 | 不要 | 不要 |
| 対応範囲 | 対応プロトコルの入出力 | 対応ライブラリの呼び出し | コードで書ける範囲すべて |
| 得られる属性 | プロトコルから観測できる情報 | ライブラリ呼び出しの引数まで | 業務の文脈を含めて自由 |
| 重複の回避 | 対象プロセスの除外設定 | ビルド対象から外す | 手動計装を基準の側とする |
| 計装の更新単位 | ホストのエージェント更新 | サービスの再ビルドと再デプロイ | ディストリビューション更新と再デプロイ |

既定の方式は、プラットフォームが変更できる場所によって決まります。本書は、共通のCIテンプレートを持ち、Kubernetesを中心に使う組織では、Goのゼロコード計装にotelcを推奨します。ビルドコマンドの差し替えで展開でき、特権が不要で、計装の更新を通常のデプロイに含められるためです。

これはOpenTelemetryが定めた優先順位ではなく、本書が置く前提に対する判断です。バイナリを再ビルドできず、CIも変更できない場合はeBPF方式を選びます。複数の言語をホスト単位でまとめて計装する場合も、言語を問わず動作するOBIが候補になります。

## Kubernetesでの配布

Kubernetesでは、[OpenTelemetry Operator](https://opentelemetry.io/docs/platforms/kubernetes/operator/automatic/)が `Instrumentation` カスタムリソースを提供します。プラットフォームチームがクラスタに用意すれば、開発チームはPodにannotationを一つ付けて自動計装を有効化できます。

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: default-instrumentation
spec:
  exporter:
    endpoint: http://otel-agent.observability:4317
  propagators:
    - tracecontext
    - baggage
```

開発チームは、Podへ次のannotationを追加します。

```yaml
metadata:
  annotations:
    instrumentation.opentelemetry.io/inject-java: "true"
```

Operatorのadmission webhookがPodの作成を検知し、言語に応じたエージェントと環境変数を注入します。設定には `OTEL_*` 環境変数を使うため、SDKディストリビューションとゼロコード計装で同じ設定方法を使えます。

![Operatorによる自動計装の注入](/images/20260825-operator-injection.png)
*図2　矢印は処理の時間順を表します。開発チームはannotationを指定し、Operatorのadmission webhookがPod作成時に計装を注入します。*

Goの注入は既定で無効です。Operatorへ `--enable-go-instrumentation=true` フラグを指定し、対象の実行ファイルパスを示すannotationも追加します。

```yaml
metadata:
  annotations:
    instrumentation.opentelemetry.io/inject-go: "true"
    instrumentation.opentelemetry.io/otel-go-auto-target-exe: "/app/server"
```

注入されるエージェントはeBPFを使うため、特権コンテナとして動作し、マルチコンテナPodには対応していません。2026年8月時点でOperatorが注入するのはOBIではなく、開発が停滞している従来のopentelemetry-go-instrumentationです。これらの制約があるため、共通CIを変更できる環境ではotelcを先に検討します。

## Kubernetes以外での配布

Operatorを使えない環境では、ビルドとデプロイのどこを変更できるかに応じて注入方法を選びます。

- ベースイメージにエージェントを同梱する。Javaのjavaagentのようにファイルを置いて環境変数で有効化する方式と相性がよい
- CIテンプレートに組み込む。Goのotelcはこの方式。ビルドコマンドを差し替えるため、共通CIを持つ組織では展開しやすい
- ホスト単位でeBPFエージェントを動かす。OBIをホストのデーモンとして動かし、そのホスト上の全プロセスを観測する

どの方式でも、送信先には各環境のagent Collector（30章）を指定します。ゼロコード計装だけがバックエンドへ直接送信すると、Collectorで行う変換や制御を適用できません。

## 手動計装への段階設計

ゼロコード計装でHTTPの入出力を記録しても、内部のどの処理に時間がかかったのか、どの顧客に関する処理だったのかまでは分かりません。こうした業務固有の情報には手動計装が必要です。基盤は、ゼロコード計装で最低限の情報を記録し、必要なサービスに手動計装を追加する段階を用意します。

ゼロコード計装と手動計装を併用すると、計装が重複する場合があります。たとえば、ゼロコード計装とディストリビューションのotelhttpが同じHTTPリクエストのスパンを作れば、同じ処理を二重に記録します。本書では手動計装を基準とし、SDKによる計装が入ったサービスをゼロコード計装の対象から外します。Operatorではannotationを外し、ホスト単位のOBIでは対象プロセスの選択条件から除外します。

SDKディストリビューションは変更できるコードへ組織の既定値を配り、ゼロコード計装はコードを変更できないサービスへ最低限の計装を配ります。どちらを先に導入するかではなく、変更できる位置に応じて使い分けます。
