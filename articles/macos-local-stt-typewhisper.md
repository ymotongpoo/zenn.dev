---
title: "TypeWhisperで構成するmacOSの無料日本語音声入力"
emoji: "🎙️"
type: "tech"
topics: ["macos", "whisper", "音声認識", "typewhisper"]
published: false
---

## はじめに

文章を打つ手間を減らすために、macOSで音声入力を使える構成を探しました。条件は、音声認識を無料で使えることと、日本語の認識精度が高いことです。IT系の仕事では、日本語の説明文に英語の製品名やコマンド名が混在します。音声入力では製品名がカタカナになったり、コマンドの空白や記号が欠けたりして、結果をそのまま使えないことがあります。聞き取りの誤りに加えて、必要な表記へ直す手間も減らしたいところです。

この記事では、Mac向けのオープンソースの音声入力アプリ[TypeWhisper](https://github.com/TypeWhisper/typewhisper-mac)で、音声認識、用語の補正、コマンドの定型文展開を組み合わせた構成を設定します。音声を文字に変える処理を**STT**（Speech-to-Text）と呼びます。

:::message
対象はApple Silicon搭載Mac、メモリ16GB以上、macOS 14以降です。2026年10月15日時点の公式資料とTypeWhisper v1.7.1の公開ソースに基づく設定手順です。著者の声による認識精度や実機の操作を検証したレポートではありません。画面名は英語表記を併記します。
:::

## TL;DR

基本構成はTypeWhisperとWhisperKitのLarge v3 Turboです。頻出するIT用語を辞書へ登録し、認識結果の表記を補正します。頻用するコマンドは、短いフレーズから定型文へ展開します。クラウドの認識サービスや文章整形サービス、履歴の同期を使わずに動く構成です。

## 構成と無料の範囲

[Whisper](https://github.com/openai/whisper)はOpenAIが公開している音声認識モデルで、[WhisperKit](https://github.com/argmaxinc/WhisperKit)はAppleのデバイス上でモデルを動かすためのライブラリです。TypeWhisperは録音、モデルの管理、辞書処理、入力先への貼り付けを担当します。

最初は次の表の設定に揃えます。表中の**LLM**は大規模言語モデル（Large Language Model）の略です。認識結果の文章を整える用途に使えますが、基本構成では使いません。

| 項目 | 最初の設定 | 目的 |
| --- | --- | --- |
| アプリ | TypeWhisperの安定版 | 録音から貼り付けまでを操作する |
| 認識エンジン | WhisperKit | Mac上でWhisperを実行する |
| モデル | Large v3 Turbo | 日常の音声入力に使う |
| 発話言語 | Japanese | 日本語を中心に認識する |
| 録音 | Push-to-Talk | キーを押している間だけ録音する |
| 用語の認識 | DictionaryのTerms | 固有名詞の綴りを認識のヒントにする |
| 表記の補正 | DictionaryのCorrections | 繰り返す誤表記を置換する |
| コマンド入力 | Snippets | 短いフレーズを定型文へ展開する |
| LLMによる整形 | オフ | 元の認識結果と辞書の動作を確認する |
| 入力後のEnter | Never | 貼り付け後に内容を確認する |

[TypeWhisperの料金説明](https://www.typewhisper.com/en/pricing/)では、基本の音声入力、ローカルエンジン、ワークフロー、スニペットを無料の対象としています。通常の業務でアプリをそのまま使う場合も、無料範囲に含まれるとされています。辞書へ手動で登録すれば、Premiumの修正自動学習機能は不要です。

初回のアプリ取得とモデルのダウンロードにはインターネット接続が必要です。この記事の構成は、準備が済んだ後の音声認識をMac内で処理するものです。アプリの更新確認を含むすべての通信を止める設定ではありません。入力先のチャットや文書が同期されるかどうかは、入力先のアプリの設定に従います。

## アプリのインストール

アップルメニューの「このMacについて」で、チップ、メモリ、macOSのバージョンを確認します。[公式の導入手順](https://www.typewhisper.com/en/docs/mac/installation/)では、macOS 14以降を必須とし、大きいモデルには16GB以上のメモリを推奨しています。

[Homebrew](https://brew.sh/ja/)を導入済みなら、ターミナルで次を実行します。

```sh
brew install --cask typewhisper/tap/typewhisper
```

Homebrewを使っていない場合の入手先は、[TypeWhisperのリリースページ](https://github.com/TypeWhisper/typewhisper-mac/releases)です。最新の安定版DMGを取得して開き、TypeWhisperをApplicationsフォルダーへ移動します。Release CandidateやDailyの表記があるプレビュー版は、この手順では選びません。

インストール後はApplicationsフォルダーからTypeWhisperを起動します。ターミナルから起動する場合は次のコマンドを使います。

```sh
open -a TypeWhisper
```

## 権限と録音操作

### マイクとアクセシビリティ

初回起動時に、マイクとアクセシビリティへのアクセスを許可します。マイクの権限は録音に、アクセシビリティの権限は入力先への文字列の貼り付けに使います。

1. macOSの「システム設定」を開きます。
2. 「プライバシーとセキュリティ」のマイク設定でTypeWhisperをオンにします。
3. 同じ画面のアクセシビリティ設定でTypeWhisperをオンにします。
4. 再起動を求められた場合は、TypeWhisperを終了して起動し直します。

macOSのバージョンによって設定名が異なる場合は、「プライバシーとセキュリティ」内で該当する権限を探します。

### 録音用のショートカット

TypeWhisperのSettingsを開き、HotkeysのPush-to-Talkへ未使用のキーの組み合わせを登録します。例えばOption＋Shift＋Spaceを候補にし、普段使うエディタや入力ソース切り替えと衝突しないことを確認します。

Push-to-Talkはキーを押している間だけ録音します。長文でキーを押し続けるのが負担になる場合は、Toggleへ別のショートカットを割り当てます。Toggleは1回押すと開始し、もう1回押すと停止する方式です。[録音操作の実装](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisper/Views/HotkeySettingsView.swift)でも両方を確認できます。

### 使用するマイク

SettingsのDictationを開き、MicrophoneのInput Deviceで使うマイクを選びます。MacBookなら、まず内蔵マイクで試せます。内蔵マイクのないMacでは、ディスプレイやヘッドセットなど、接続した機器のマイクが必要です。

最初はマイクを1つに固定し、同じ位置から話します。ヘッドセットの着脱などで入力機器が変わると、モデルの違いと録音条件の違いを区別しにくくなるためです。声が入らないときは、マイクの選択とmacOSの入力レベルを先に確認します。[入力機器の設定項目](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisper/Views/SettingsView.swift)は公開ソースでも確認できます。

## 認識モデルの設定

### WhisperKitの準備

WhisperKitの設定場所はSettingsのIntegrationsです。未導入なら追加し、モデル一覧から`Large v3 Turbo`をダウンロードします。ダウンロード後は読み込みまで完了させます。

似た名前の`Distil Large v3 Turbo`や英語専用モデルと混同しないようにします。今回使うモデルの識別子は`openai_whisper-large-v3_turbo`です。取得サイズは配布形式によって異なるため、アプリに表示される容量と空き容量を確認します。[v1.7.1のモデル定義](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisperPluginSDK/Plugins/WhisperKitPlugin/WhisperKitPlugin.swift)では、Large v3 TurboとDistil版が別項目になっています。

読み込みが完了したら、SettingsのDictationでDefault EngineをWhisperKitにします。使用モデルがLarge v3 Turboになっていることも、WhisperKit側の設定で確認します。

### 日本語と文章加工

SettingsのGeneralまたはDictationにあるSpoken LanguageでJapaneseを選び、GeneralのEnable translationはオフにします。英語の製品名が混在する文でも発話言語はJapaneseのままにし、製品名の表記は後の節で辞書を使って補正します。

最初はDictationのApp-aware formattingとNormalize spoken numbers to digitsもオフにします。これらは認識後の文字列を加工する機能です。STTが返した文字列を確認してから、必要な項目だけオンにします。

### 入力専用のワークフロー

**ワークフロー**は、言語、モデル、文章加工、起動条件をまとめたTypeWhisperの設定です。SettingsのWorkflowsから`Dictation Only`のワークフローを作り、名前を「日本語入力」にします。[ワークフローの公式説明](https://www.typewhisper.com/en/docs/mac/workflows/)に従い、次の値を設定します。

| 項目 | 設定値 |
| --- | --- |
| Spoken Language | Japanese |
| Transcription Engine | WhisperKit |
| Model | Large v3 Turbo |
| Task | Transcribe |
| Inline Commands | オフ |
| Output Format | None |
| Press Enter after inserting | Never |
| 起動条件 | Always |

Alwaysは、より具体的な条件のワークフローが一致しないときに使う設定です。既にアプリ別やWebサイト別のワークフローを登録している場合は、初回テストに使う入力先へ別の設定が適用されていないか確認します。文章をLLMへ渡すワークフローは、この段階では使いません。

## Mac内で処理する設定

TypeWhisperには[履歴と音声を同期する設定](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisper/Views/HistorySettingsView.swift)もあります。そのため、ローカルエンジンを選ぶだけでなく、文章加工と同期の設定も確認します。

1. IntegrationsではローカルのWhisperKitを使い、クラウド認識サービスを設定しません。
2. WorkflowsのGlobal LLM Fallbacksは空にします。既存設定がある場合は、今回使うワークフローがその一覧を使わないことを確認します。
3. History & SyncのSync History & Inboxをオフにします。
4. Sync Audio for New Entriesが表示される場合はオフにします。
5. Premiumの同期設定やCloud Folder Syncを有効にしません。既に有効な場合は、今回のローカル運用ではオフにします。
6. AdvancedのMemoryでEnable Memoryをオフにします。[Memory機能](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisper/Views/AdvancedSettingsView.swift)は文字起こしからLLMで情報を抽出するため、ワークフローの文章加工とは別に確認します。

Save audio with transcriptionsは、音声を履歴に保存する設定です。クラウド同期とは別の設定なので、録音を残したくない場合はオフにします。ただし、オフにしても一時音声や復旧用の録音が残る場合があり、その保存先と保持期間はHistory & SyncとRecoveryの設定で確認します。

モデルの準備が終わったら、ネットワークを切断して入力を試します。Wi-Fiだけでなく有線接続も使っている場合は、両方の切断が必要です。この操作で確かめられるのはオフラインで処理が完了するかどうかで、通信をすべて監査するものではありません。

## 最初の音声入力

最初の入力先にはローカルのテキストエディタを使います。macOSのテキストエディットで新規書類を開き、標準テキストにしてからカーソルを置きます。

1. Push-to-Talkのキーを押し続けます。
2. 録音開始の表示または音を確認してから話します。
3. 「今日は日本語の音声入力を設定します」と発話します。
4. キーを離し、入力結果を待ちます。
5. 文字列が挿入され、勝手にEnterが押されないことを確認します。

続いて「グラファナでメトリクスを確認します」のように製品名を含む文を試します。製品名がカタカナで入力されても、この時点では直さずに、実際に出た表記を記録します。辞書登録前の結果は、登録後と比べるための基準です。

ネットワークを切断した状態でも同じ操作を行います。成功したらTypeWhisperを一度終了し、切断したまま起動し直して再試行します。モデルの読み込みから入力まで完了すれば、オフラインでの確認は終わりです。

## IT用語の辞書登録

### 認識のヒントの登録

DictionaryのTermsには、認識してほしい単語を正しい綴りで登録します。[辞書機能の公式説明](https://www.typewhisper.com/en/docs/mac/features/#dictionary)では、Termsを認識時のヒント、Correctionsを認識後の置換として区別しています。

SettingsのDictionaryでTermsを選び、Add Termから期待する綴りを1語ずつ入力して保存します。保存した項目が有効になっていることも確認し、よく使う語から順に追加します。

例えば、次の20語から自分の仕事に関係するものを選びます。これは一括インポート用のファイル形式ではなく、登録する文字列の例です。

```text
Grafana
OpenTelemetry
Prometheus
PromQL
LogQL
TraceQL
Kubernetes
kubectl
Helm
Docker
Terraform
GitHub
GitHub Actions
Cloud Run
CloudWatch
Alloy
Loki
Tempo
Mimir
OTLP
```

WhisperKitへ渡す用語ヒントには長さの上限があります。v1.7.1の実装では、プロンプト全体の上限は500文字です。辞書へ大量に追加してもすべてが毎回渡るとは限らないため、最初は20〜30語程度から始め、使わない用語を減らします。Termsへの登録はモデルの再学習ではなく、正しい出力を保証するものでもありません。

### 誤表記の置換

Correctionsには、自分の発話で実際に出た誤表記と、置換先を登録します。次の表は登録例です。左側の文字列は、自分の認識結果に合わせます。

| Wrong Textに登録する表記の例 | Correct Textに登録する表記 |
| --- | --- |
| グラファナ | Grafana |
| オープンテレメトリー | OpenTelemetry |
| クバネティス | Kubernetes |
| キューブシーティーエル | kubectl |
| プロムキューエル | PromQL |

DictionaryのCorrectionsでAdd Correctionを選び、Wrong Textに認識結果の文字列を、Correct Textに正しい表記を入力して保存します。同じ文をもう一度話し、置換されることを確認します。

一般語と区別できない短い読みを登録すると、文中の別の語まで置換されるおそれがあります。例えば「ごー」を常にプログラミング言語のGoへ変えるような登録は避け、実際の誤表記に対象を絞ります。

### 助詞を含む文での確認

単語だけでなく、「グラファナで確認します」「グラファナの設定を変更します」のように助詞を付けて試します。TypeWhisperの補正は、単純な全箇所置換ではありません。[補正処理の実装](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisper/Services/DictionaryService.swift)は日本語の語の境界を扱っており、登録語と前後の文字の種類から一致を判断する仕組みです。

期待どおりに置換されない場合は、履歴で実際の文字列を確認します。長音符、空白、カタカナの表記など、登録語との差を調べてから辞書を修正します。

## コマンドの定型文展開

Snippetsは、**トリガー**と呼ぶ短い文字列を、登録した定型文へ展開する機能です。処理の対象は、発音そのものではなく、STTが返す文字列です。[スニペットの仕様](https://www.typewhisper.com/en/docs/mac/features/#snippets)に従い、まず1件だけ登録します。

1. テキストエディタで「ポッド一覧コマンド」と単独で発話します。
2. 実際に入力された文字列を確認します。
3. SettingsのSnippetsでAdd Snippetを選びます。
4. Triggerへ、その文字列を入力します。
5. Replacementへ`kubectl get pods`を入力します。末尾に改行は入れません。
6. 保存して有効にし、同じフレーズを再度発話します。

トリガーの例は次のとおりです。句点の有無は、前の操作で確認した結果に合わせます。

| Triggerの例 | Replacement |
| --- | --- |
| ポッド一覧コマンド | `kubectl get pods` |
| ギット状態コマンド | `git status` |
| ドッカー一覧コマンド | `docker ps` |

認識結果に句点が付く場合、句点なしのトリガーだけでは展開後のコマンドにも句点が残ることがあります。その場合は、句点を含む文字列をTriggerへ登録します。句点ありと句点なしの両方を登録するなら、それぞれで期待する結果になるかの確認が必要です。

日本語の前後に続けて話すと、一致しない場合もあります。[Snippetsの照合処理](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisper/Services/SnippetService.swift)では前後の文字を確認するため、「ポッド一覧コマンドを入力して」のような文に埋め込まず、トリガーだけを単独で発話します。

テキストエディタで空白、記号、句点、改行を確認してから、普段の入力先で使います。Press Enter after insertingはNeverのままです。コマンドの引数が毎回変わる場合は、固定部分だけを展開し、変数名やファイルパスをキーボードで補う方法もあります。

## 20文での入力比較

設定の評価には、普段の仕事に近い文を使います。次の例文は、日本語、英語の製品名、略語、コマンド名を混ぜたものです。10番の`kubectl`は普段の読み方で話します。

| 番号 | 発話する文 |
| --- | --- |
| 1 | Grafanaでメトリクスを確認します。 |
| 2 | OpenTelemetry Collectorの設定を変更します。 |
| 3 | Prometheusのスクレイプ間隔を確認します。 |
| 4 | PromQLのクエリを修正します。 |
| 5 | LokiのログをLogQLで検索します。 |
| 6 | TempoのトレースをTraceQLで調べます。 |
| 7 | Mimirへのリモートライトを確認します。 |
| 8 | AlloyでOTLPのデータを受信します。 |
| 9 | KubernetesのDeploymentを更新します。 |
| 10 | `kubectl`でPodの状態を確認します。 |
| 11 | Helmのvaluesファイルを変更します。 |
| 12 | Dockerのコンテナイメージをビルドします。 |
| 13 | Terraformのplanを確認します。 |
| 14 | GitHub Actionsのワークフローを修正します。 |
| 15 | Cloud Runのサービスをデプロイします。 |
| 16 | CloudWatchのロググループを確認します。 |
| 17 | リクエストのタイムアウトを30秒に変更します。 |
| 18 | バージョン1.2.3の動作を確認します。 |
| 19 | エラー率は0.5パーセントです。 |
| 20 | ポッド一覧コマンド。 |

1〜19は文章の入力テスト、20はスニペット展開のテストです。20の期待する出力は`kubectl get pods`です。文章としての認識精度と、定型文の展開が成功したかを分けて記録します。

辞書をまだ登録していない状態と、調整後の状態を比較します。初回のモデル読み込み時間は、2回目以降の待ち時間と分けて記録します。測定の条件は、2つの状態とも同じマイク、同じ距離、同じ入力先です。

| 設定 | 専門用語の正答数／対象数 | 反映待ち時間の中央値 | 20文の合計修正時間 | 意図しない置換 |
| --- | --- | --- | --- | --- |
| Turboと辞書登録前 | 未測定 | 未測定 | 未測定 | 未測定 |
| Turboと調整後の辞書 | 未測定 | 未測定 | 未測定 | 未測定 |
| Large v3と同じ辞書 | 未測定 | 未測定 | 未測定 | 未測定 |

専門用語は、期待する綴りと大文字、小文字まで一致した出現数を数えます。反映待ち時間は、録音を止めてから入力が終わるまでの時間です。修正時間には、入力結果を期待する文章へ直すのにかかった時間を記録します。表の値は記入欄であり、測定結果ではありません。

認識だけを同一音声で比べたい場合は、20文を録音した音声ファイルをFile Transcriptionに読み込み、モデルを切り替えて処理します。ファイル文字起こしと普段の音声入力では、貼り付けやスニペットなどの処理範囲が異なるため、日常操作の待ち時間は別に測ります。

## 認識モデルの変更

Turboで修正が多い場合は、IntegrationsのWhisperKitでLarge v3をダウンロードして読み込みます。辞書と例文はTurboと共通です。ワークフローのモデルもLarge v3へ変更し、普段使うエディタやブラウザを開いた状態で、認識結果、待ち時間、メモリ使用量を確認します。

英語の文章をまとまって話す場合は、Workflowsに英語用のDictation Onlyを追加し、Spoken LanguageをEnglishにします。起動操作は専用のStart Dictationホットキーです。日本語と英語で別のキーを使えば、既存の日本語設定を保ったまま切り替えられます。

Qwenチームが公開している音声認識モデルの[Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)も、日本語と英語に対応するローカル認識の候補です。ただしTypeWhisper v1.7.1では、Qwen3へのTermsの自動注入を無効にしています。長い用語一覧が認識結果に混入する問題を受けた[変更](https://github.com/TypeWhisper/typewhisper-mac/pull/683)です。認識後に置換するCorrectionsは、Qwen3でも引き続き使えます。

Qwen3-ASRを比較する場合は、IntegrationsでQwen3 ASRを追加します。[Qwen3のモデル定義](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisperPluginSDK/Plugins/Qwen3Plugin/Qwen3Plugin.swift)で、メモリ16GB以上向けの候補は`Qwen3 1.7B (6-bit)`です。このモデルを読み込み、専用のDictation Onlyワークフローでエンジンとモデルを指定します。

ここでのWhisperとの比較は、辞書ヒントの有無も含めた構成全体の比較です。モデル単体の性能差と混同せず、自分の発話で修正時間が減るかを基準にします。

## ローカルLLMの追加

日本語の文章を整えたい場合だけ、ローカルLLMを追加します。音声認識の後にもう一度推論するため、基本構成より入力までの時間が延び、メモリ使用量も増えます。

TypeWhisperには[Local LLM (MLX)プラグイン](https://github.com/TypeWhisper/typewhisper-mac/tree/v1.7.1/TypeWhisperPluginSDK/Plugins/LocalLLMPlugin)があります。[MLX](https://github.com/ml-explore/mlx)はApple Silicon向けの機械学習フレームワークです。v1.7.1のプラグインはApple SiliconとmacOS 14以降に対応し、APIキーを必要としません。モデルはアプリが推奨する小さい側の`Gemma 4 E2B (4-bit)`から試します。

1. IntegrationsでLocal LLM (MLX)を追加します。
2. モデルをダウンロードし、読み込みを完了します。
3. Workflowsで文章整形用のCustom Workflowを作ります。
4. LLMを使う処理を選び、LLM OverrideのProviderでLocal LLM (MLX)を明示的に指定します。
5. 起動条件をManualにします。
6. Press Enter after insertingはNeverにします。
7. HotkeysでWorkflow Paletteのキーを登録します。

最初は音声入力の結果を選択し、Workflow Paletteから手動で整形します。認識結果と整形結果を比較するためです。LLM Overrideでプロバイダーを明示したワークフローは、[グローバルのフォールバック一覧を経由せず](https://www.typewhisper.com/en/docs/mac/workflows/#global-llm-fallback-list)、指定したプロバイダーだけを使います。

文章整形の指示には、例えば次を設定します。

```text
入力された日本語の文章について、句読点と明らかな言いよどみだけを整えてください。
情報を追加したり、要約したりしないでください。
製品名、識別子、コマンド、コード、URL、数値は変更しないでください。
判断できない表記は、そのまま残してください。
整形した本文だけを返してください。
```

この指示を与えても、LLMが製品名やコマンドを書き換えないとは限りません。整形の対象は文章だけとし、コマンド入力には元の日本語入力ワークフローを使います。

追加したら、整形結果と待ち時間を確認し、ネットワークを切断した状態でも同じ整形ができることを確かめます。待ち時間が長い場合は、この追加処理を外して基本構成に戻します。

## 困ったときの確認

| 症状 | 最初に確認する内容 |
| --- | --- |
| 録音が始まらない | Hotkeysの衝突と、マイク権限を確認します。 |
| 録音できるが音声が入らない | DictationのInput Deviceと、macOSの入力レベルを確認します。 |
| 履歴には文字があるが貼り付かない | アクセシビリティ権限を確認し、テキストエディットで再試行します。 |
| 出力が英訳される | Enable translationと、適用されたワークフローのTaskを確認します。 |
| 製品名がカタカナになる | Termsの対応状況と、実際の表記に対応するCorrectionsを確認します。 |
| スニペットが展開されない | 実際の認識結果とTriggerを比べ、単独の発話で試します。 |
| コマンドの末尾に句点が残る | 句点を含むトリガーで照合できるか確認します。 |
| 関係のない語へ置換される | 該当するCorrectionを無効にし、登録前の結果を確認します。 |
| 初回だけ待ち時間が長い | モデルの読み込みと、その後の認識時間を分けて確認します。 |
| オフラインで失敗する | モデルの取得状況、読み込み、適用された認識エンジンとLLMを確認します。 |

入力先によって結果が違う場合は、Workflowsのアプリ条件やWebサイト条件も確認します。Alwaysより具体的なワークフローが適用されている可能性があるためです。問題を切り分ける間は、入力先とワークフローを固定します。

## 設定の保存と更新

辞書とスニペットを調整したら、SettingsのAdvancedにあるBackup & RestoreからExport Settingsを実行します。[エクスポートの実装](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisper/Views/AdvancedSettingsView.swift)を見ると、書き出す対象は辞書やワークフローのほか、文字起こし履歴も含みます。保存先には、クラウド同期の対象外のローカルフォルダーを選んでください。

モデル本体や、選択したエンジンとモデルなどの機器固有設定は、設定バックアップに含まれません。移行や再インストールに備えて、アプリのバージョン、使用モデル、マイク、測定条件を別のメモに残します。

Homebrewで導入した場合は、更新前にバックアップを作り、次を実行します。

```sh
brew update
brew upgrade --cask typewhisper
```

公式DMGから導入した場合は、アプリの更新機能を使います。更新チャンネルは安定版のままです。更新後は辞書の動作、スニペットの句点、オフライン入力を再確認します。

## おわりに

公式資料とv1.7.1のソースを読む限り、TypeWhisperは音声認識、用語の補正、定型文の展開を無料の範囲で、Mac内で処理できる構成だということを確認しました。IT用語を含む音声入力では、認識結果を正しい表記とコマンドの文字列まで揃える必要があり、TypeWhisperではこの3つの機能をそれぞれ調整できます。

認識精度は話し方やマイクで変わります。日常の入力に近い20文で修正時間と反映待ち時間を測り、記録した誤りに合わせて辞書を調整してください。それでも修正が残る場合に、Large v3やQwen3-ASRとの比較へ進みます。

## 出典

- [TypeWhisper v1.7.1のリリース](https://github.com/TypeWhisper/typewhisper-mac/releases/tag/v1.7.1)
- [TypeWhisperのインストール手順](https://www.typewhisper.com/en/docs/mac/installation/)
- [TypeWhisperの料金と無料範囲](https://www.typewhisper.com/en/pricing/)
- [TypeWhisperの機能説明](https://www.typewhisper.com/en/docs/mac/features/)
- [TypeWhisperのワークフロー](https://www.typewhisper.com/en/docs/mac/workflows/)
- [WhisperKitプラグインの実装](https://github.com/TypeWhisper/typewhisper-mac/blob/v1.7.1/TypeWhisperPluginSDK/Plugins/WhisperKitPlugin/WhisperKitPlugin.swift)
- [Qwen3で辞書ヒントを無効にした変更](https://github.com/TypeWhisper/typewhisper-mac/pull/683)

TypeWhisperのソースはGPLv3で公開されています。実装への参照はv1.7.1に固定しています。公式サイトの手順と料金は、冒頭に記した参照時点の内容です。
