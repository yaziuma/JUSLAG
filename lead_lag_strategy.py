"""
部分空間正則化付き主成分分析を用いた日米業種リードラグ投資戦略
Lead-Lag Strategy using Subspace Regularized PCA

論文: 中川慧, 竹本悠城, 久保健治, 加藤真大 (SIG-FIN-036-13)
概要:
  - 米国S&P500の11業種ETF（当日Close-to-Close）でシグナルを生成
  - 日本TOPIX-17業種ETF（翌営業日Open-to-Close）で執行
  - 部分空間正則化付きPCAで共通ファクターを抽出し、日本側への伝播を予測
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from scipy.linalg import eigh

# ─────────────────────────────────────────────
# 定数設定
# ─────────────────────────────────────────────

# 米国業種ETF (Select Sector SPDR, 11業種)
US_TICKERS = {
    "XLB":  "Materials",
    "XLE":  "Energy",
    "XLF":  "Financials",
    "XLI":  "Industrials",
    "XLK":  "Information Technology",
    "XLP":  "Consumer Staples",
    "XLU":  "Utilities",
    "XLV":  "Health Care",
    "XLY":  "Consumer Discretionary",
    "XLC":  "Communication Services",
    "XLRE": "Real Estate",
}

# 日本業種ETF (NEXT FUNDS TOPIX-17業種別ETF, 17業種)
JP_TICKERS = {
    "1617.T": "食品",
    "1618.T": "エネルギー資源",
    "1619.T": "建設・資材",
    "1620.T": "素材・化学",
    "1621.T": "医薬品",
    "1622.T": "自動車・輸送機",
    "1623.T": "鉄鋼・非鉄",
    "1624.T": "機械",
    "1625.T": "電機・精密",
    "1626.T": "情報通信・サービスその他",
    "1627.T": "電力・ガス",
    "1628.T": "運輸・物流",
    "1629.T": "商社・卸売",
    "1630.T": "小売",
    "1631.T": "銀行",
    "1632.T": "金融（除く銀行）",
    "1633.T": "不動産",
}

# 業種分類: シクリカル(+1) / ディフェンシブ(-1)
US_CYCLICAL = {
    "XLB": 1, "XLE": 1, "XLF": 1, "XLI": 1, "XLK": 1,
    "XLP": -1, "XLU": -1, "XLV": -1, "XLY": 1, "XLC": 1, "XLRE": -1,
}
JP_CYCLICAL = {
    "1617.T": -1,  # 食品: ディフェンシブ
    "1618.T": 1,   # エネルギー資源: シクリカル
    "1619.T": 1,   # 建設・資材: シクリカル
    "1620.T": 1,   # 素材・化学: シクリカル
    "1621.T": -1,  # 医薬品: ディフェンシブ
    "1622.T": 1,   # 自動車・輸送機: シクリカル
    "1623.T": 1,   # 鉄鋼・非鉄: シクリカル
    "1624.T": 1,   # 機械: シクリカル
    "1625.T": 1,   # 電機・精密: シクリカル
    "1626.T": -1,  # 情報通信・サービスその他: ディフェンシブ
    "1627.T": -1,  # 電力・ガス: ディフェンシブ
    "1628.T": -1,  # 運輸・物流: ディフェンシブ
    "1629.T": 1,   # 商社・卸売: シクリカル
    "1630.T": -1,  # 小売: ディフェンシブ
    "1631.T": 1,   # 銀行: シクリカル
    "1632.T": 1,   # 金融（除く銀行）: シクリカル
    "1633.T": 1,   # 不動産: シクリカル
}

# ハイパーパラメータ
WINDOW_L = 60          # ローリングウィンドウ（営業日）
K_FACTORS = 3          # 抽出する主成分数
LAMBDA = 0.9           # 正則化強度 (0=正則化なし, 1=完全事前情報)
QUANTILE_Q = 0.3       # ロング/ショート上下分位点
# XLC (通信サービスETF) は 2018-06-18 上場のため 2018-07-01 以降を使用
PRETRAIN_END = "2021-12-31"  # C_full推定用期間終了日
SAMPLE_START = "2018-07-01"
SAMPLE_END = "2026-04-07"   # 当日より1日後を指定することで最新データを取得


# ─────────────────────────────────────────────
# データ取得
# ─────────────────────────────────────────────

def fetch_data(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """yfinanceで日次Open/Closeを取得する (US/JPを別々にフェッチしてカレンダー問題を回避)"""
    us_tickers = list(US_TICKERS.keys())
    jp_tickers = list(JP_TICKERS.keys())
    print(f"データ取得中: US {len(us_tickers)}銘柄 + JP {len(jp_tickers)}銘柄 ({start} - {end})")

    us_raw = yf.download(us_tickers, start=start, end=end, auto_adjust=True, progress=False)
    jp_raw = yf.download(jp_tickers, start=start, end=end, auto_adjust=True, progress=False)

    us_close = us_raw["Close"][us_tickers].dropna(how="all")
    jp_close = jp_raw["Close"][jp_tickers].dropna(how="all")
    jp_open  = jp_raw["Open"][jp_tickers].dropna(how="all")

    # 取得失敗した列を除去
    us_close = us_close.dropna(axis=1, how="all")
    jp_close = jp_close.dropna(axis=1, how="all")
    jp_open  = jp_open.dropna(axis=1, how="all")

    print(f"  US close shape : {us_close.shape}")
    print(f"  JP close shape : {jp_close.shape}")
    return us_close, jp_close, jp_open


def compute_returns(us_close: pd.DataFrame, jp_close: pd.DataFrame,
                    jp_open: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    US: Close-to-Close リターン (r^cc_{i,t})
    JP: Open-to-Close リターン (r^oc_{j,t}) — 戦略評価用
    """
    us_cc = us_close.pct_change()          # 米国CTC
    jp_oc = jp_close / jp_open - 1.0       # 日本OTC
    jp_cc = jp_close.pct_change()          # 日本CTC (相関推定用)
    return us_cc, jp_oc, jp_cc


# ─────────────────────────────────────────────
# 事前部分空間の構築
# ─────────────────────────────────────────────

def build_prior_eigenvectors(us_tickers: list, jp_tickers: list) -> np.ndarray:
    """
    3本の事前固有ベクトル V0 ∈ R^{N×3} を構築する
      v1: グローバルファクター (全銘柄等ウェイト)
      v2: 国スプレッドファクター (US+, JP-)
      v3: シクリカル・ディフェンシブファクター
    """
    N_U = len(us_tickers)
    N_J = len(jp_tickers)
    N = N_U + N_J

    def normalize(v):
        return v / np.linalg.norm(v)

    def gram_schmidt(v, basis):
        for b in basis:
            v = v - np.dot(v, b) * b
        return normalize(v)

    # v1: グローバルファクター
    v1 = normalize(np.ones(N))

    # v2: 国スプレッド (US+1, JP-1)
    v2_raw = np.array([1.0] * N_U + [-1.0] * N_J)
    v2 = gram_schmidt(v2_raw, [v1])

    # v3: シクリカル・ディフェンシブ
    cyc = np.array(
        [US_CYCLICAL[t] for t in us_tickers] +
        [JP_CYCLICAL[t] for t in jp_tickers],
        dtype=float
    )
    v3 = gram_schmidt(cyc, [v1, v2])

    V0 = np.column_stack([v1, v2, v3])  # shape (N, 3)
    return V0


def build_prior_exposure(cc_full: pd.DataFrame, V0: np.ndarray) -> np.ndarray:
    """
    C_full (長期相関行列) からターゲット行列 C0 を構築
      D0 = diag(V0^T C_full V0)
      C0_raw = V0 D0 V0^T
      C0 = (対角を1に正規化)
    """
    R = cc_full.values
    # 標準化リターン
    mu = R.mean(axis=0, keepdims=True)
    sig = R.std(axis=0, keepdims=True) + 1e-10
    Z = (R - mu) / sig

    C_full = Z.T @ Z / len(Z)

    D0 = np.diag(np.diag(V0.T @ C_full @ V0))  # K0×K0 対角行列
    C0_raw = V0 @ D0 @ V0.T                      # N×N

    # 対角1に正規化
    diag_vals = np.diag(C0_raw)
    diag_vals = np.where(np.abs(diag_vals) < 1e-12, 1.0, diag_vals)
    D_inv_sqrt = np.diag(1.0 / np.sqrt(diag_vals))
    C0 = D_inv_sqrt @ C0_raw @ D_inv_sqrt
    np.fill_diagonal(C0, 1.0)
    return C0


# ─────────────────────────────────────────────
# 部分空間正則化PCA + シグナル生成
# ─────────────────────────────────────────────

def compute_signal_at_t(
    z_window: np.ndarray,     # shape (L, N)  — ウィンドウ内の結合標準化リターン
    z_us_t: np.ndarray,       # shape (N_U,)  — 当日米国標準化リターン
    C0: np.ndarray,           # shape (N, N)  — ターゲット行列
    N_U: int,
    K: int = K_FACTORS,
    lam: float = LAMBDA,
) -> np.ndarray:
    """
    部分空間正則化PCAで日本翌日シグナルを計算
    Returns: z_hat_J_{t+1} shape (N_J,)
    """
    N = z_window.shape[1]

    # NaN/inf のクリーンアップ
    z_window = np.nan_to_num(z_window, nan=0.0, posinf=0.0, neginf=0.0)
    z_us_t   = np.nan_to_num(z_us_t,   nan=0.0, posinf=0.0, neginf=0.0)

    # ウィンドウ内相関行列
    C_t = z_window.T @ z_window / max(len(z_window), 1)
    np.fill_diagonal(C_t, 1.0)

    # 正則化相関行列
    C_reg = (1.0 - lam) * C_t + lam * C0
    C_reg = np.nan_to_num(C_reg, nan=0.0)
    np.fill_diagonal(C_reg, 1.0)

    # 上位K固有ベクトル (scipy.eigh は昇順なので末尾K個)
    eigvals, eigvecs = eigh(C_reg, check_finite=False)
    V_K = eigvecs[:, -K:]  # shape (N, K)

    # 米国/日本ブロックに分割
    V_U = V_K[:N_U, :]    # (N_U, K)
    V_J = V_K[N_U:, :]    # (N_J, K)

    # シグナル: z_hat_J = V_J * (V_U^T * z_U)
    f_t = V_U.T @ z_us_t              # (K,) ファクタースコア
    z_hat_J = V_J @ f_t               # (N_J,)
    return z_hat_J


def generate_signals(
    us_cc: pd.DataFrame,
    jp_cc: pd.DataFrame,
    C0: np.ndarray,
    L: int = WINDOW_L,
    K: int = K_FACTORS,
    lam: float = LAMBDA,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, np.ndarray, np.ndarray]:
    """全期間のシグナルを生成する"""
    us_tickers = us_cc.columns.tolist()
    jp_tickers = jp_cc.columns.tolist()
    N_U = len(us_tickers)
    N_J = len(jp_tickers)

    # 共通取引日のみ使用 (行ごとに欠損がない日を採用)
    common_idx = us_cc.index.intersection(jp_cc.index)
    us_cc_c = us_cc.loc[common_idx]
    jp_cc_c = jp_cc.loc[common_idx]

    # 結合リターン: 各列で欠損が多い日を除去
    joint_cc = pd.concat([us_cc_c, jp_cc_c], axis=1)
    # US列・JP列それぞれで過半数が有効な行のみ残す
    us_valid = joint_cc[us_tickers].notna().sum(axis=1) >= len(us_tickers) * 0.8
    jp_valid = joint_cc[jp_tickers].notna().sum(axis=1) >= len(jp_tickers) * 0.8
    joint_cc = joint_cc[us_valid & jp_valid]
    # 残った欠損は列平均で補完 (ごく少数)
    joint_cc = joint_cc.apply(lambda col: col.fillna(col.rolling(5, min_periods=1).mean()))
    joint_cc = joint_cc.dropna()

    signals = {}
    dates = joint_cc.index

    for i in range(L, len(dates)):
        t = dates[i]
        window_dates = dates[i - L: i]

        # ウィンドウ内標準化
        R_win = joint_cc.loc[window_dates].values  # (L, N)
        mu_w = R_win.mean(axis=0)
        sig_w = R_win.std(axis=0) + 1e-10
        Z_win = (R_win - mu_w) / sig_w             # (L, N)

        # 当日米国リターン標準化
        r_us_t = joint_cc.loc[t, us_tickers].values
        z_us_t = (r_us_t - mu_w[:N_U]) / sig_w[:N_U]

        sig_vec = compute_signal_at_t(Z_win, z_us_t, C0, N_U, K, lam)
        signals[t] = dict(zip(jp_tickers, sig_vec))

    signal_df = pd.DataFrame(signals).T
    signal_df.index.name = "date"
    return signal_df


# ─────────────────────────────────────────────
# ポートフォリオ構築
# ─────────────────────────────────────────────

def build_portfolio(signal_df: pd.DataFrame, jp_oc: pd.DataFrame,
                    q: float = QUANTILE_Q) -> pd.Series:
    """
    シグナルに基づくロングショートポートフォリオのリターンを計算
    - シグナル日 t のシグナルで翌日 t+1 の Open-to-Close に投資
    - 上位q分位: ロング, 下位q分位: ショート
    """
    # 翌営業日のOTCリターン (shift -1 でシグナル日に揃える)
    jp_oc_aligned = jp_oc.shift(-1)

    portfolio_returns = []
    for t in signal_df.index:
        if t not in jp_oc_aligned.index:
            continue
        sig = signal_df.loc[t].dropna()
        ret = jp_oc_aligned.loc[t, sig.index].dropna()
        common = sig.index.intersection(ret.index)
        if len(common) < 3:
            continue

        sig_c = sig[common]
        ret_c = ret[common]

        # 分位点
        lo = sig_c.quantile(q)
        hi = sig_c.quantile(1.0 - q)

        long_mask  = sig_c >= hi
        short_mask = sig_c <= lo

        if long_mask.sum() == 0 or short_mask.sum() == 0:
            continue

        w_long  =  1.0 / long_mask.sum()
        w_short = -1.0 / short_mask.sum()

        port_ret = (ret_c[long_mask] * w_long).sum() + (ret_c[short_mask] * w_short).sum()
        portfolio_returns.append({"date": t, "return": port_ret})

    if not portfolio_returns:
        return pd.Series(dtype=float)

    df = pd.DataFrame(portfolio_returns).set_index("date")["return"]
    return df


# ─────────────────────────────────────────────
# パフォーマンス評価
# ─────────────────────────────────────────────

def compute_performance(returns: pd.Series, label: str = "Strategy") -> dict:
    """年率リターン / リスク / R/R / 最大ドローダウン"""
    r = returns.dropna()
    if len(r) == 0:
        return {}

    ann_ret  = r.mean() * 252            # 日次→年率 (252営業日換算)
    ann_risk = r.std() * np.sqrt(252)
    rr       = ann_ret / ann_risk if ann_risk > 0 else np.nan

    # 最大ドローダウン
    cumret = (1 + r).cumprod()
    roll_max = cumret.cummax()
    drawdown = (cumret / roll_max - 1)
    mdd = drawdown.min()

    result = {
        "Strategy": label,
        "AR(%)":    round(ann_ret * 100, 2),
        "Risk(%)":  round(ann_risk * 100, 2),
        "R/R":      round(rr, 3),
        "MDD(%)":   round(mdd * 100, 2),
        "N_days":   len(r),
    }
    return result


# ─────────────────────────────────────────────
# ベースライン戦略
# ─────────────────────────────────────────────

def momentum_signal(jp_cc: pd.DataFrame, L: int = WINDOW_L) -> pd.DataFrame:
    """単純モメンタム: ウィンドウ内平均Close-to-Closeリターン"""
    return jp_cc.rolling(L).mean().shift(1)


def plain_pca_signal(us_cc: pd.DataFrame, jp_cc: pd.DataFrame,
                     C0: np.ndarray, L: int = WINDOW_L, K: int = K_FACTORS) -> pd.DataFrame:
    """λ=0 (正則化なし) のPCA"""
    return generate_signals(us_cc, jp_cc, C0, L=L, K=K, lam=0.0)


# ─────────────────────────────────────────────
# 今日のシグナル（リアルタイム予測）
# ─────────────────────────────────────────────

def get_todays_signal(
    us_cc: pd.DataFrame,
    jp_cc: pd.DataFrame,
    C0: np.ndarray,
    L: int = WINDOW_L,
    K: int = K_FACTORS,
    lam: float = LAMBDA,
    q: float = QUANTILE_Q,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, np.ndarray, np.ndarray]:
    """
    最新日（today）の米国リターンを使い、明日の日本市場向けシグナルを生成する
    Returns: (signal_df, us_return_df, today, B_mat, r_us_t)
    """
    jp_tickers = jp_cc.columns.tolist()
    us_tickers = us_cc.columns.tolist()
    N_U = len(us_tickers)

    common_idx = us_cc.index.intersection(jp_cc.index)
    joint_cc = pd.concat([us_cc.loc[common_idx], jp_cc.loc[common_idx]], axis=1)
    joint_cc = joint_cc.apply(lambda col: col.fillna(col.rolling(5, min_periods=1).mean()))
    joint_cc = joint_cc.dropna()
    dates = joint_cc.index

    if len(dates) < L + 1:
        print("データが不足しています")
        return pd.DataFrame(), pd.DataFrame(), pd.NaT, np.array([]), np.array([])

    # 最新ウィンドウ
    window_dates = dates[-(L + 1): -1]
    today = dates[-1]
    R_win = joint_cc.loc[window_dates].values
    mu_w  = R_win.mean(axis=0)
    sig_w = R_win.std(axis=0) + 1e-10
    Z_win = (R_win - mu_w) / sig_w

    r_us_t = joint_cc.loc[today, us_tickers].values
    z_us_t = (r_us_t - mu_w[:N_U]) / sig_w[:N_U]

    sig_vec = compute_signal_at_t(Z_win, z_us_t, C0, N_U, K, lam)

    result = pd.DataFrame({
        "ticker": jp_tickers,
        "sector": [JP_TICKERS.get(t, t) for t in jp_tickers],
        "signal": sig_vec,
    }).set_index("ticker")

    # 米国リターンも追加表示
    us_ret_df = pd.DataFrame({
        "ticker": us_tickers,
        "sector": [US_TICKERS.get(t, t) for t in us_tickers],
        "us_return(%)": r_us_t * 100,
    }).set_index("ticker")

    lo = result["signal"].quantile(q)
    hi = result["signal"].quantile(1.0 - q)
    result["position"] = "neutral"
    result.loc[result["signal"] >= hi, "position"] = "LONG"
    result.loc[result["signal"] <= lo, "position"] = "SHORT"

    # 伝播行列 B と固有ベクトル (分析用に返す)
    C_t = Z_win.T @ Z_win / max(len(Z_win), 1)
    np.fill_diagonal(C_t, 1.0)
    C_reg = (1.0 - lam) * C_t + lam * C0
    np.fill_diagonal(C_reg, 1.0)
    _, evec = eigh(C_reg, check_finite=False)
    VK = evec[:, -K:]
    VU_mat = VK[:N_U, :]
    VJ_mat = VK[N_U:, :]
    B_mat = VJ_mat @ VU_mat.T   # shape (N_J, N_U)

    result = result.sort_values("signal", ascending=False)
    return result, us_ret_df, today, B_mat, r_us_t


# ─────────────────────────────────────────────
# 追加分析: ランク・一致度・ETF詳細・執行フロー
# ─────────────────────────────────────────────

def print_full_ranking(signal_df: pd.DataFrame, jp_tickers: list, q: float = QUANTILE_Q):
    """JP業種 全17銘柄シグナルランキング"""
    n = len(signal_df)
    top_n = int(n * q)

    print("【JP業種 全ランキング】")
    print("  Rank  Ticker      業種            タイプ          Signal    Position")
    print("  " + "-" * 68)
    for i, (ticker, row) in enumerate(signal_df.iterrows()):
        cyc_label = "シクリカル" if JP_CYCLICAL.get(ticker, 0) == 1 else "ディフェンシブ"
        if i < top_n:
            pos = "LONG  ▲"
        elif i >= n - top_n:
            pos = "SHORT ▼"
        else:
            pos = "neutral"
        print("  %-4d  %-10s  %-14s  %-14s  %+8.4f  %s" % (
            i + 1, ticker, row["sector"], cyc_label, row["signal"], pos))


def print_sector_agreement(signal_df: pd.DataFrame, r_us_t: np.ndarray, us_tickers: list):
    """シクリカル/ディフェンシブ スプレッドと方向一致度"""
    from scipy.stats import spearmanr

    jp_tickers = signal_df.index.tolist()
    sig = signal_df["signal"].values

    cyc_sig = np.mean([s for t, s in zip(jp_tickers, sig) if JP_CYCLICAL.get(t, 0) == 1])
    def_sig = np.mean([s for t, s in zip(jp_tickers, sig) if JP_CYCLICAL.get(t, 0) == -1])
    cyc_us  = np.mean([r_us_t[i] for i, t in enumerate(us_tickers) if US_CYCLICAL.get(t, 0) == 1])
    def_us  = np.mean([r_us_t[i] for i, t in enumerate(us_tickers) if US_CYCLICAL.get(t, 0) == -1])

    spread_us = cyc_us - def_us
    spread_jp = cyc_sig - def_sig
    direction = "一致 (US→JP 伝播一貫)" if (spread_us > 0) == (spread_jp > 0) else "不一致"

    print("【シクリカル vs ディフェンシブ スプレッド】")
    print("  US  シクリカル平均: %+.2f%%  ディフェンシブ平均: %+.2f%%  スプレッド: %+.2f%%" % (
        cyc_us * 100, def_us * 100, spread_us * 100))
    print("  JP  シクリカル平均: %+.4f  ディフェンシブ平均: %+.4f  スプレッド: %+.4f" % (
        cyc_sig, def_sig, spread_jp))
    print("  方向性: %s" % direction)

    jp_cyc_vec = np.array([JP_CYCLICAL.get(t, 0) for t in jp_tickers], dtype=float)
    rho, pval = spearmanr(sig, jp_cyc_vec)
    print()
    print("【シグナルとシクリカル分類のスピアマン順位相関】")
    sig_str = "有意" if pval < 0.05 else "非有意"
    print("  rho = %+.4f  p = %.4f  → %s" % (rho, pval, sig_str))


def print_propagation_matrix(B_mat: np.ndarray, jp_tickers: list, us_tickers: list, top_n: int = 10):
    """伝播行列 B の上位影響ペア"""
    pairs = []
    for ji, jt in enumerate(jp_tickers):
        for ui, ut in enumerate(us_tickers):
            pairs.append((abs(B_mat[ji, ui]), B_mat[ji, ui],
                          JP_TICKERS.get(jt, jt), US_TICKERS.get(ut, ut)))
    pairs.sort(reverse=True)

    print("【伝播行列 B の上位影響ペア (|B_ji| 降順 Top%d)】" % top_n)
    print("  JP業種              <- US業種            係数")
    print("  " + "-" * 48)
    for _, b, jn, un in pairs[:top_n]:
        print("  %-18s  <- %-18s  %+.4f" % (jn, un, b))


def print_etf_details(signal_df: pd.DataFrame):
    """LONG対象ETFの詳細情報をyfinanceから取得して表示"""
    long_tickers = signal_df[signal_df["position"] == "LONG"].index.tolist()
    if not long_tickers:
        print("  LONG候補なし")
        return

    print("【LONG対象 ETF 詳細】")
    print("  %-10s  %-40s  %10s  %7s  %10s  %10s" % (
        "Ticker", "正式名称", "直近終値", "前日比", "出来高(口)", "純資産"))
    print("  " + "-" * 95)

    for ticker in long_tickers:
        try:
            t_obj = yf.Ticker(ticker)
            info  = t_obj.info
            hist  = t_obj.history(period="5d")
            name  = (info.get("longName") or info.get("shortName") or "N/A")[:38]
            price = hist["Close"].iloc[-1] if len(hist) > 0 else None
            prev  = hist["Close"].iloc[-2] if len(hist) > 1 else None
            vol   = hist["Volume"].iloc[-1] if len(hist) > 0 else None
            chg   = (price / prev - 1) * 100 if price and prev else None
            assets = info.get("totalAssets", None)

            price_s  = "%10s円" % "{:,.0f}".format(price)     if price       else "       N/A"
            chg_s    = "%+6.2f%%" % chg                        if chg is not None else "    N/A"
            vol_s    = "%12s口" % "{:,.0f}".format(vol)        if vol         else "       N/A"
            assets_s = "%8.1f億円" % (assets / 1e8)            if assets      else "     N/A"
            print("  %-10s  %-40s  %s  %s  %s  %s" % (
                ticker, name, price_s, chg_s, vol_s, assets_s))
        except Exception as e:
            print("  %-10s  取得失敗: %s" % (ticker, e))

    print()
    print("  ※ 流動性目安: 出来高が多い順に執行優先度が高い")


def print_execution_flow(today_date, signal_df: pd.DataFrame):
    """1日の執行フロー (論文Section 2準拠)"""
    import datetime
    next_day = today_date + datetime.timedelta(days=1)
    next_day_str = next_day.strftime("%Y-%m-%d")

    long_list  = signal_df[signal_df["position"] == "LONG"].index.tolist()
    short_list = signal_df[signal_df["position"] == "SHORT"].index.tolist()

    long_sectors  = [signal_df.loc[t, "sector"] for t in long_list]
    short_sectors = [signal_df.loc[t, "sector"] for t in short_list]

    print("【本日の執行フロー (論文 Section 2 準拠)】")
    print()
    print("  ◆ 基準日 %s (米国市場終値)" % today_date.date())
    print("    → 米国11業種 Close-to-Close リターンでシグナル計算済み")
    print()
    print("  ◆ 執行日 %s (日本市場)" % next_day_str)
    print("    09:00  寄付き【執行】")
    print("           LONG  買い: %s" % " / ".join(long_sectors))
    for t in long_list:
        print("             %s  %s  (等ウェイト +1/%d)" % (
            t, signal_df.loc[t, "sector"], len(long_list)))
    print()
    print("           SHORT 売り: %s" % " / ".join(short_sectors))
    for t in short_list:
        print("             %s  %s  (等ウェイト -1/%d)" % (
            t, signal_df.loc[t, "sector"], len(short_list)))
    print()
    print("    15:30  引け【決済】")
    print("           LONG  売り決済 / SHORT 買戻し")
    print("           利益 = Σ w_j × (Close / Open - 1)  [Open-to-Close リターン]")
    print()
    print("  ◆ 注意事項")
    print("    - 保有は当日中のみ (翌日持越しなし)")
    print("    - 等ウェイト配分: LONG %d銘柄 × +%.1f%% / SHORT %d銘柄 × -%.1f%%" % (
        len(long_list), 100/len(long_list) if long_list else 0,
        len(short_list), 100/len(short_list) if short_list else 0))
    print("    - 論文パフォーマンスは売買コスト・借株料未控除")
    print("    - SHORT実行には制度信用売りまたは先物が必要")


# ─────────────────────────────────────────────
# ファクター回帰 (FF3 / Carhart4)
# ─────────────────────────────────────────────

_FACTOR_PATH = Path(__file__).resolve().parent / "data" / "external" / "factors" / "normalized"


def load_factor_data() -> "pd.DataFrame | None":
    c4_path = _FACTOR_PATH / "carhart4_japan_daily.csv"
    ff3_path = _FACTOR_PATH / "ff3_japan_daily.csv"
    if c4_path.exists():
        df = pd.read_csv(c4_path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    if ff3_path.exists():
        df = pd.read_csv(ff3_path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    return None


def run_factor_regression(returns: pd.Series, factors: pd.DataFrame) -> dict:
    def _to_date_index(idx: pd.Index) -> pd.Index:
        # tz-aware の場合は時刻成分を切り捨てて日付のみに正規化（tz_localize(None) は時刻を残す）
        if hasattr(idx, "tz") and idx.tz is not None:
            idx = idx.normalize().tz_localize(None)
        return idx

    returns_clean = pd.Series(
        returns.values, index=_to_date_index(returns.index)
    ).dropna()
    factors_clean = pd.DataFrame(
        factors.values, index=_to_date_index(factors.index), columns=factors.columns
    )

    # returns・factors を inner join してから NaN を一括除去
    combined = returns_clean.rename("_ret").to_frame().join(factors_clean, how="inner").dropna()
    if combined.empty:
        return {"error": "alignment result is empty after dropping NaN"}

    ret_aligned = combined["_ret"]
    fac_aligned = combined.drop(columns=["_ret"])

    # "rf" は無リスク金利列（完全一致）。"mkt_rf" はファクター列として残す
    rf_col = next((c for c in fac_aligned.columns if c.lower() == "rf"), None)
    factor_cols = [c for c in fac_aligned.columns if c != rf_col]

    if rf_col:
        y = (ret_aligned - fac_aligned[rf_col]).values
    else:
        y = ret_aligned.values

    X = fac_aligned[factor_cols].values
    n, k_factors = X.shape
    k = k_factors + 1

    if n <= k:
        return {"error": f"insufficient observations: n={n}, k={k}"}

    X_with_const = np.column_stack([np.ones(n), X])

    try:
        beta, _, _, _ = np.linalg.lstsq(X_with_const, y, rcond=None)
        resid = y - X_with_const @ beta
        s2 = np.sum(resid ** 2) / (n - k)
        cov = s2 * np.linalg.inv(X_with_const.T @ X_with_const)
        se = np.sqrt(np.diag(cov))
        t_stats = beta / se
    except np.linalg.LinAlgError as e:
        return {"error": str(e)}

    ss_tot = np.sum((y - y.mean()) ** 2)
    ss_res = np.sum(resid ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return {
        "n_obs": int(n),
        "alpha_annual": float(beta[0] * 252),
        "t_alpha": float(t_stats[0]),
        "r2": float(r2),
        "betas": {col: float(beta[i + 1]) for i, col in enumerate(factor_cols)},
        "t_stats": {col: float(t_stats[i + 1]) for i, col in enumerate(factor_cols)},
    }


def print_factor_regression(returns_df: pd.DataFrame, factor_df: pd.DataFrame) -> dict:
    has_wml = "wml" in factor_df.columns
    model_name = "Carhart4 (FF3+WML)" if has_wml else "FF3"
    print(f"\n{'=' * 60}")
    print(f"ファクター回帰 ({model_name})")
    print(f"{'=' * 60}")
    print(f"  ファクター期間: {factor_df.index.min().date()} – {factor_df.index.max().date()}")

    results = {}
    for col in ["MOM", "PCA_PLAIN", "PCA_SUB"]:
        if col not in returns_df.columns:
            continue
        res = run_factor_regression(returns_df[col].dropna(), factor_df)
        results[col] = res
        if "error" in res:
            print(f"  {col}: ERROR {res['error']}")
            continue
        stars = "**" if abs(res["t_alpha"]) >= 2.0 else "*" if abs(res["t_alpha"]) >= 1.65 else ""
        print(f"  {col:12s}  α={res['alpha_annual']:+.2%}/yr  t(α)={res['t_alpha']:+.2f}{stars}  "
              f"R²={res['r2']:.3f}  N={res['n_obs']}")
        for fname, beta_val in res["betas"].items():
            t_val = res["t_stats"][fname]
            print(f"              β({fname})={beta_val:+.3f}  t={t_val:+.2f}")
    return results


# ─────────────────────────────────────────────
# レポート JSON 保存 (Web UI 用)
# ─────────────────────────────────────────────

def save_report_json(
    perf: list[dict],
    returns_df: pd.DataFrame,
    factor_df: "pd.DataFrame | None",
    factor_reg: dict,
    today_result: pd.DataFrame,
    today_date,
    eval_start: str,
    out_path: Path,
) -> None:
    from datetime import datetime, timezone

    key_map = {"MOM (Momentum)": "MOM", "PCA PLAIN": "PCA_PLAIN", "PCA SUB (提案手法)": "PCA_SUB"}
    perf_map: dict = {}
    for p in perf:
        k = key_map.get(p.get("Strategy", ""), p.get("Strategy", ""))
        perf_map[k] = {
            "annual_return": round(float(p.get("AR(%)") or 0), 4),
            "annual_risk":   round(float(p.get("Risk(%)") or 0), 4),
            "sharpe":        round(float(p.get("R/R") or 0), 4),
            "max_dd":        round(float(p.get("MDD(%)") or 0), 4),
            "n_days":        int(p.get("N_days") or 0),
        }

    factor_meta: dict = {}
    if factor_df is not None:
        has_wml = "wml" in factor_df.columns
        factor_meta = {
            "model": "Carhart4 (FF3+WML)" if has_wml else "FF3",
            "factor_start": str(factor_df.index.min().date()),
            "factor_end":   str(factor_df.index.max().date()),
        }

    signals = []
    for ticker, row in today_result.iterrows():
        signals.append({
            "ticker":   ticker,
            "sector":   row.get("sector", ""),
            "signal":   round(float(row.get("signal", 0)), 6),
            "position": row.get("position", "neutral"),
        })

    actions_meta: dict = {}
    actions_meta_path = (
        Path(__file__).resolve().parent
        / "data" / "external" / "actions" / "normalized" / "actions_metadata.json"
    )
    if actions_meta_path.exists():
        am = json.loads(actions_meta_path.read_text())
        actions_meta = {
            "updated_at": am.get("updated_at", ""),
            "dividends":  am.get("dividends", 0),
            "splits":     am.get("splits", 0),
        }

    ret_idx = returns_df.index
    if hasattr(ret_idx, "tz") and ret_idx.tz is not None:
        ret_idx = ret_idx.normalize().tz_localize(None)
    eval_end = str(pd.DatetimeIndex(ret_idx).max().date())

    report = {
        "updated_at":        datetime.now(timezone.utc).isoformat(),
        "eval_start":        eval_start,
        "eval_end":          eval_end,
        "signal_date":       str(today_date.date()),
        "performance":       perf_map,
        "factor_meta":       factor_meta,
        "factor_regression": factor_reg,
        "signals":           signals,
        "actions_meta":      actions_meta,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nレポート JSON を保存: {out_path}")


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("日米業種リードラグ戦略 (部分空間正則化PCA)")
    print("=" * 60)

    # 1. データ取得
    us_close, jp_close, jp_open = fetch_data(SAMPLE_START, SAMPLE_END)
    us_cc, jp_oc, jp_cc = compute_returns(us_close, jp_close, jp_open)

    # 取得できた銘柄リスト (失敗した列は除外済み)
    us_tickers = us_close.columns.tolist()
    jp_tickers = jp_close.columns.tolist()
    print(f"  有効US銘柄: {us_tickers}")
    print(f"  有効JP銘柄数: {len(jp_tickers)}")

    # 2. 事前固有ベクトル
    print("\n事前部分空間を構築中...")
    V0 = build_prior_eigenvectors(us_tickers, jp_tickers)

    # 3. C_full (学習期間)
    print(f"C_full を推定中 (~{PRETRAIN_END})...")
    common_idx = us_cc.index.intersection(jp_cc.index)
    joint_cc_raw = pd.concat([us_cc.loc[common_idx], jp_cc.loc[common_idx]], axis=1)
    joint_cc_raw = joint_cc_raw.apply(lambda col: col.fillna(col.rolling(5, min_periods=1).mean()))
    joint_cc_raw = joint_cc_raw.dropna()
    pretrain_data = joint_cc_raw.loc[:PRETRAIN_END]
    print(f"  学習データ: {len(pretrain_data)} 日")
    C0 = build_prior_exposure(pretrain_data, V0)

    # 4. 本戦略シグナル (PCA SUB)
    print(f"\nPCA SUB シグナルを生成中 (L={WINDOW_L}, K={K_FACTORS}, λ={LAMBDA})...")
    signal_sub = generate_signals(us_cc, jp_cc, C0)

    # 5. ベースライン: モメンタム
    print("Momentum シグナルを生成中...")
    signal_mom = momentum_signal(jp_cc)

    # 6. ベースライン: Plain PCA (λ=0)
    print("PCA PLAIN シグナルを生成中...")
    signal_plain = generate_signals(us_cc, jp_cc, C0, lam=0.0)

    # 7. ポートフォリオリターン
    print("\nポートフォリオリターンを計算中...")
    # 戦略評価期間: 学習期間終了翌年から
    eval_start = str(int(PRETRAIN_END[:4]) + 1) + "-01-01"

    ret_sub   = build_portfolio(signal_sub[eval_start:],   jp_oc[eval_start:])
    ret_mom   = build_portfolio(signal_mom[eval_start:],   jp_oc[eval_start:])
    ret_plain = build_portfolio(signal_plain[eval_start:], jp_oc[eval_start:])

    # 8. パフォーマンス比較
    perf = [
        compute_performance(ret_mom,   "MOM (Momentum)"),
        compute_performance(ret_plain, "PCA PLAIN"),
        compute_performance(ret_sub,   "PCA SUB (提案手法)"),
    ]
    print("\n" + "=" * 60)
    print(f"パフォーマンス比較 (評価期間: {eval_start}–{SAMPLE_END})")
    print("=" * 60)
    perf_df = pd.DataFrame(perf).set_index("Strategy")
    print(perf_df.to_string())

    # 9. リターン系列を保存
    result_dir = Path("outputs")
    result_dir.mkdir(parents=True, exist_ok=True)
    returns_df = pd.DataFrame({
        "MOM":       ret_mom,
        "PCA_PLAIN": ret_plain,
        "PCA_SUB":   ret_sub,
    })
    out_path = result_dir / "lead_lag_returns.csv"
    returns_df.to_csv(out_path)
    print(f"\nリターン系列を保存: {out_path}")

    # 10. 今日のシグナル (明日の日本市場向け)
    sep = "=" * 70
    print("\n" + sep)
    print("本日の投資シグナル (明日の日本市場向け)")
    print(sep)
    today_result, us_ret_df, today_date, B_mat, r_us_t = get_todays_signal(us_cc, jp_cc, C0)
    print("基準日 (米国市場終値): %s\n" % today_date.date())

    # (A) 米国業種リターン
    print("【米国業種リターン (当日)】")
    print("-" * 50)
    for ticker, row in us_ret_df.sort_values("us_return(%)").iterrows():
        bar = "▲" if row["us_return(%)"] >= 0 else "▼"
        print("  %s %-6s %-30s  %+.2f%%" % (
            bar, ticker, row["sector"], row["us_return(%)"]))
    print()

    # (B) JP全ランキング
    print_full_ranking(today_result, jp_tickers)
    print()

    # (C) シクリカル/ディフェンシブ一致度
    print_sector_agreement(today_result, r_us_t, us_tickers)
    print()

    # (D) 伝播行列
    print_propagation_matrix(B_mat, jp_tickers, us_tickers)
    print()

    # (E) LONG対象ETF詳細
    print_etf_details(today_result)

    # (F) 執行フロー
    print_execution_flow(today_date, today_result)

    # 保存
    signal_out = result_dir / "todays_signal.csv"
    today_result.to_csv(signal_out, encoding="utf-8-sig")
    print("\nシグナルを保存: %s" % signal_out)

    # 11. ファクター回帰
    factor_df = load_factor_data()
    factor_reg: dict = {}
    if factor_df is not None:
        factor_reg = print_factor_regression(returns_df, factor_df)
    else:
        print("\n[INFO] ファクターデータ未取得。scripts/fetch_factor_data.py を実行してください。")

    # 12. レポート JSON 保存 (Web UI 用)
    save_report_json(
        perf=perf,
        returns_df=returns_df,
        factor_df=factor_df,
        factor_reg=factor_reg,
        today_result=today_result,
        today_date=today_date,
        eval_start=eval_start,
        out_path=result_dir / "juslag_report.json",
    )

    return returns_df, today_result


if __name__ == "__main__":
    returns_df, today_signal = main()
