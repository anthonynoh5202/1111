"""Shared loaders for the BTC cash-and-carry study (read-only use of local Binance data).

All timestamps are UTC. Funding rate r_k is paid at settlement time t_k (00/08/16 UTC) on
position notional (qty x mark price). A short perp RECEIVES r_k x notional when r_k > 0.
"""
import numpy as np
import pandas as pd

DATA = "/home/user/1111/data/binance"
OUT = "/tmp/claude-0/-home-user-1111/25e0663c-3dd5-5112-98b0-d8d31ac17dd0/scratchpad/qteam/carry/out"
BASE = 0.0001          # Binance "interest" component: 0.01% per 8h  (= 10.95% APR)
CLAMP = 0.0005         # funding formula clamp +-0.05%
PER_YEAR = 3 * 365     # 8h intervals per year (simple annualisation)
TOL = 1e-9


def load_funding() -> pd.DataFrame:
    f = pd.read_csv(f"{DATA}/BTCUSDT_fundingRate.csv.gz")
    f["t"] = pd.to_datetime(f.calc_time, unit="ms", utc=True).dt.round("h")
    f = f.rename(columns={"last_funding_rate": "rate"})[["t", "rate", "funding_interval_hours"]]
    assert f.t.is_unique and (f.funding_interval_hours == 8).all()
    f = f.set_index("t").sort_index()
    gaps = f.index.to_series().diff().dropna()
    assert (gaps == pd.Timedelta(hours=8)).all(), "funding gaps present"
    return f


def implied_premium(rate: pd.Series) -> pd.Series:
    """Invert Binance F = P + clamp(I - P, -0.05%, +0.05%), I = 0.01%.

    F > I  -> P = F + 0.05%;  F < I -> P = F - 0.05%;  F == I -> P in [-0.04%, +0.06%] -> midpoint 0.01%.
    P is the (time-weighted) average premium of the perp over the spot index during the interval,
    used here as the basis proxy (perp/spot - 1). It is an 8h average: instantaneous spikes are NOT captured.
    """
    p = np.where(rate > BASE + TOL, rate + CLAMP, np.where(rate < BASE - TOL, rate - CLAMP, BASE))
    return pd.Series(p, index=rate.index, name="prem")


def load_klines(interval: str) -> pd.DataFrame:
    k = pd.read_csv(f"{DATA}/BTCUSDT_{interval}.csv.gz",
                    usecols=["open_time", "open", "high", "low", "close", "volume"])
    k["t"] = pd.to_datetime(k.open_time, unit="ms", utc=True)
    return k.set_index("t").drop(columns="open_time").sort_index()


def mark_proxy_hourly() -> pd.DataFrame:
    """Hourly max/min of 5-minute CLOSES = proxy for mark-price extremes.

    Binance liquidates on mark price (index-based, smoothed), not on last-trade wicks such as the
    2021-07-26 01:00 print of 48,168 on the perp (spot never traded there). 5m closes remove
    single-print wicks but keep genuine moves.
    """
    m = pd.read_csv(f"{DATA}/BTCUSDT_5m.csv.gz", usecols=["open_time", "close"])
    m["t"] = pd.to_datetime(m.open_time, unit="ms", utc=True)
    g = m.groupby(m.t.dt.floor("h")).close.agg(["max", "min"])
    g.columns = ["mhi", "mlo"]
    return g


def daily_regime() -> pd.Series:
    """Bull (True) if the previous daily close is above its 200-day SMA (known at the start of the day)."""
    d = load_klines("1d")
    sma = d.close.rolling(200).mean()
    bull = (d.close > sma).where(sma.notna())
    return bull.shift(1)  # value for day D uses close/SMA of day D-1 -> no lookahead


def pct(x, nd=2):
    return f"{100 * x:.{nd}f}%"
