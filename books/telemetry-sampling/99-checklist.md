---
title: "付録：チェックリスト"
---

## サンプリング導入の判断フロー

サンプリングを導入すべきかどうか迷った際は、以下の項目を確認してください。

1.  **データ量は予算内に収まっているか？**
    *   Yes: まだ全量保存（サンプリングなし）で問題ありません。
    *   No: サンプリングの検討を開始しましょう。
2.  **大半のデータが「正常」なリクエストか？**
    *   Yes: ヘッドサンプリングまたはテイルサンプリングの導入効果が高いです。
    *   No: （常にエラーが多い場合）サンプリングよりも先にシステム改善が必要です。
3.  **特定の顧客やエンドポイントだけを詳細に見る必要があるか？**
    *   Yes: 動的サンプリング（Adaptive Sampling）によるきめ細かな制御が必要です。

## 推奨されるリテンションとストレージ設計

サンプリングと組み合わせて検討すべきなのが、データの保存期間（リテンション）です。

*   **トレース (Traces)**: 
    *   詳細な調査用のため、通常は短期的（7〜14日間）な保持で十分です。
    *   長期的なトレンド分析には、スパンから生成したメトリクスを使用します。
*   **メトリクス (Metrics)**:
    *   リソース使用量やサービスレベルの推移を見るため、長期的（12〜15ヶ月）な保持を検討します。
    *   Prometheusなどの時系列データベースでは、古いデータをダウンサンプリング（精度を落として保存）することで容量を節約します。

## 参考文献

*   [OpenTelemetry: Sampling Concepts](https://opentelemetry.io/docs/concepts/sampling/)
*   [Google SRE Book: Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)
*   [Prometheus: Storage](https://prometheus.io/docs/prometheus/latest/storage/)
*   [Honeycomb: The New Rules of Sampling](https://www.honeycomb.io/blog/the-new-rules-of-sampling)
*   [Honeycomb: Sampling Observability at Slack](https://www.honeycomb.io/blog/sampling-observability-slack)
