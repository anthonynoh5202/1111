"""A3 공통 함수: 데이터 읽기, 순위 상관(IC), Newey-West t, 월별 IC t, 다중 검정 보정.

원칙
- 시각은 모두 UTC 내부 처리, 보고만 KST(+9h).
- 결정 시각 T = 봉 마감 시각(open_time + 봉 길이). T에서는 마감된 봉과 T 이전에 공개된 값만 쓴다.
- metrics(5분)는 시각 규칙이 2024-03에 바뀌었다(전: 구간 끝 표시, 후: 구간 시작 표시. a0b 확인).
  → 결정 시각 T에서는 create_time <= T - 5분인 행만 쓴다(두 규칙 모두에서 미래 정보 없음).
- 펀딩: calc_time <= T 인 정산값만 쓴다(정산 시각 ms 오차 때문에 실제로는 1시간 늦게 반영될 수 있음 = 보수적).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

D = "/home/user/1111/data/binance/"
OUT = "/tmp/claude-0/-home-user-1111/25e0663c-3dd5-5112-98b0-d8d31ac17dd0/scratchpad/team/A3/"

IS_START = pd.Timestamp("2021-12-01", tz="UTC")
IS_END = pd.Timestamp("2024-01-01", tz="UTC")      # IS: [IS_START, IS_END)
OOS_START = pd.Timestamp("2024-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-09-29", tz="UTC")     # 데이터 끝 (2026-09-28 23:59)
FUND_END = pd.Timestamp("2026-08-31 16:00", tz="UTC")
KST = pd.Timedelta(hours=9)


def load_klines(tf: str, cols=None) -> pd.DataFrame:
    df = pd.read_csv(D + f"BTCUSDT_{tf}.csv.gz", usecols=cols)
    df["t"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.set_index("t").sort_index()


def load_metrics() -> pd.DataFrame:
    m = pd.read_csv(D + "BTCUSDT_metrics.csv.gz")
    m["t"] = pd.to_datetime(m["create_time"], utc=True)
    m = m.drop_duplicates("t").set_index("t").sort_index()
    for c in ["sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
              "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]:
        m[c] = pd.to_numeric(m[c], errors="coerce")
        m[c] = m[c].where(m[c] > 0)          # 0 이하 = 결측 (2022-03-07 OI 0 덩어리 등)
    return m.drop(columns=["create_time", "symbol"])


def load_funding() -> pd.Series:
    f = pd.read_csv(D + "BTCUSDT_fundingRate.csv.gz")
    f["t"] = pd.to_datetime(f["calc_time"], unit="ms", utc=True)
    return f.set_index("t").sort_index()["last_funding_rate"].astype(float)


def asof_on_grid(src: pd.DataFrame | pd.Series, grid: pd.DatetimeIndex, lag: pd.Timedelta,
                 tolerance: pd.Timedelta) -> pd.DataFrame:
    """grid의 각 T에 대해 src 중 index <= T - lag 인 마지막 행. 그 행이 tolerance보다 오래됐으면 NaN."""
    if isinstance(src, pd.Series):
        src = src.to_frame()
    ns = "datetime64[ns, UTC]"
    left = pd.DataFrame({"T": grid, "key": (grid - lag).astype(ns)})
    right = src.copy()
    right["src_t"] = right.index.astype(ns)
    right = right.reset_index(drop=True)
    out = pd.merge_asof(left.sort_values("key"), right.sort_values("src_t"), left_on="key", right_on="src_t",
                        direction="backward", tolerance=tolerance)
    return out.set_index("T").drop(columns=["key", "src_t"])


# ---------------------------------------------------------------------------
# 통계
# ---------------------------------------------------------------------------

def norm_p_two_sided(t: float) -> float:
    if t is None or not np.isfinite(t):
        return float("nan")
    return math.erfc(abs(t) / math.sqrt(2.0))


def _std_rank(a: np.ndarray) -> np.ndarray:
    r = pd.Series(a).rank(method="average").to_numpy()
    r = r - r.mean()
    s = r.std()
    return r / s if s > 0 else r * np.nan


def nw_lrv(g: np.ndarray, L: int) -> float:
    """Bartlett 커널 Newey-West 장기 분산 (평균 0 가정 아님 → 평균 제거)."""
    g = g - g.mean()
    n = len(g)
    v = g @ g / n
    for l in range(1, min(L, n - 1) + 1):
        w = 1.0 - l / (L + 1.0)
        v += 2.0 * w * (g[l:] @ g[:-l]) / n
    return v


def ic_stats(x: pd.Series, y: pd.Series, L: int, min_month_n: int = 300) -> dict:
    """순위 상관(IC)·Newey-West t·월별 IC t. x, y는 같은 시간 index."""
    d = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    n = len(d)
    if n < 500:
        return dict(n=n, ic=np.nan, t_nw=np.nan, p_nw=np.nan, ic_m=np.nan, t_m=np.nan, months=0, pos_m=np.nan)
    rx = _std_rank(d["x"].to_numpy())
    ry = _std_rank(d["y"].to_numpy())
    ic = float(np.mean(rx * ry))
    e = ry - ic * rx
    lrv = nw_lrv(rx * e, L)
    se = math.sqrt(max(lrv, 1e-18) / n)
    t_nw = ic / se
    # 월별 IC
    mon = d.index.strftime("%Y-%m")
    ics = []
    for _, g in d.groupby(mon):
        if len(g) < min_month_n or g["x"].nunique() < 3:
            continue
        a = _std_rank(g["x"].to_numpy()); b = _std_rank(g["y"].to_numpy())
        ics.append(float(np.mean(a * b)))
    ics = np.array(ics)
    if len(ics) >= 6:
        ic_m = ics.mean(); t_m = ic_m / (ics.std(ddof=1) / math.sqrt(len(ics)))
        pos_m = float((np.sign(ics) == np.sign(ic)).mean())
    else:
        ic_m = t_m = pos_m = np.nan
    return dict(n=n, ic=ic, t_nw=t_nw, p_nw=norm_p_two_sided(t_nw), ic_m=ic_m, t_m=t_m, months=len(ics), pos_m=pos_m)


def ols_nw(y: np.ndarray, X: np.ndarray, L: int) -> tuple[np.ndarray, np.ndarray]:
    """OLS 계수와 Newey-West t. X에 상수항 포함해서 넘길 것."""
    XtX_inv = np.linalg.pinv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    n, k = X.shape
    G = X * e[:, None]
    S = G.T @ G / n
    for l in range(1, min(L, n - 1) + 1):
        w = 1.0 - l / (L + 1.0)
        Gl = G[l:].T @ G[:-l] / n
        S += w * (Gl + Gl.T)
    V = n * XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(V), 1e-30))
    return b, b / se


def holm(pvals: list[float]) -> list[float]:
    """Holm 보정 p값 (NaN은 NaN 유지)."""
    p = np.array(pvals, dtype=float)
    idx = np.where(np.isfinite(p))[0]
    m = len(idx)
    adj = np.full_like(p, np.nan)
    order = idx[np.argsort(p[idx])]
    run = 0.0
    for i, j in enumerate(order):
        val = min(1.0, (m - i) * p[j])
        run = max(run, val)
        adj[j] = run
    return adj.tolist()


def bh(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg q값."""
    p = np.array(pvals, dtype=float)
    idx = np.where(np.isfinite(p))[0]
    m = len(idx)
    q = np.full_like(p, np.nan)
    order = idx[np.argsort(p[idx])]
    prev = 1.0
    for rank in range(m, 0, -1):
        j = order[rank - 1]
        prev = min(prev, p[j] * m / rank)
        q[j] = prev
    return q.tolist()


def period_mask(idx: pd.DatetimeIndex, which: str, horizon_h: int = 24) -> np.ndarray:
    """IS/OOS 구간 마스크. 목표 구간이 다음 표본으로 넘어가지 않게 끝에 horizon만큼 엠바고."""
    emb = pd.Timedelta(hours=horizon_h)
    if which == "IS":
        return (idx >= IS_START) & (idx <= IS_END - emb)
    if which == "OOS":
        return (idx >= OOS_START) & (idx <= OOS_END - emb)
    raise ValueError(which)


def add_vol_residuals(df: pd.DataFrame, eps: float = 1e-5) -> pd.DataFrame:
    """rvres_n = log(다음 n시간 실현 변동성) - [log 과거 4h·24h·168h 실현 변동성 + 요일·시간 168칸] (IS 적합). a2_ic.py와 같은 식."""
    how = (df.index.dayofweek * 24 + df.index.hour).to_numpy()
    Dm = np.zeros((len(df), 168)); Dm[np.arange(len(df)), how] = 1.0
    base = np.column_stack([np.log(df[c].to_numpy() + eps) for c in ["rv_past_4", "rv_past_24", "rv_past_168"]])
    X = np.column_stack([base, Dm])
    for n in (4, 24):
        y = np.log(df[f"rv_next_{n}"].to_numpy() + eps)
        ism = period_mask(df.index, "IS", n) & np.isfinite(y) & np.isfinite(X).all(axis=1)
        b = np.linalg.lstsq(X[ism], y[ism], rcond=None)[0]
        df[f"rvres_{n}"] = y - X @ b
        df[f"rvhat_{n}"] = np.exp(X @ b) - eps
    return df
