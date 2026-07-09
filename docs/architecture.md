# Architecture

- `config.py`: 定数・モード設定・出力先管理
- `data_loader.py`: 取得、リターン生成、結合カレンダー、欠損補完
- `prior.py`: 事前部分空間 (`V0`) とターゲット行列 (`C0`)
- `model.py`: 部分空間正則化付きPCAの計算コア
- `signal.py`: 履歴シグナル・当日シグナル生成
- `portfolio.py`: quantileベースのロングショート構築
- `metrics.py`: 年率指標・MDD
- `report.py`: 表示専用

`run_backtest.py` は reproduction mode、`run_daily_signal.py` は daily mode を利用します。
