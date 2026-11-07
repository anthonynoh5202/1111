"""Shared data loading, backtest engine, metrics and bootstrap helpers.

Conventions (see PREREGISTRATION.md):
  * signal from bar t (close) -> target weight for bar t+1 (filled at open of t+1)
  * bar P&L open-to-open; last bar open-to-close
  * funding at tau charged to position held at tau, bar interval (open_i, open_i+len]
"""
import os
import numpy as np
import pandas as pd

DATA = '/home/user/1111/data/binance'
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'out_rt')
os.makedirs(OUT, exist_ok=True)

COSTS = {'base': 0.0007, 'maker': 0.0002, 'stress': 0.0010}
BAND = 0.10
IS_START, IS_END = pd.Timestamp('2020-07-20', tz='UTC'), pd.Timestamp('2023-12-31', tz='UTC')
OOS_START, OOS_END = pd.Timestamp('2024-01-01', tz='UTC'), pd.Timestamp('2026-09-28', tz='UTC')
FULL_START = IS_START
BAR_LEN = {'1d': pd.Timedelta(days=1), '4h': pd.Timedelta(hours=4), '1h': pd.Timedelta(hours=1)}

_cache = {}


def load_klines(tf):
    if tf in _cache:
        return _cache[tf]
    df = pd.read_csv(f'{DATA}/BTCUSDT_{tf}.csv.gz',
                     usecols=['open_time', 'open', 'high', 'low', 'close', 'volume'])
    df.index = pd.to_datetime(df.open_time, unit='ms', utc=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    # sanity: regular grid
    d = df.index.to_series().diff().dropna().unique()
    assert len(d) == 1, (tf, d)
    _cache[tf] = df
    return df


def load_funding():
    if 'fund' in _cache:
        return _cache['fund']
    f = pd.read_csv(f'{DATA}/BTCUSDT_fundingRate.csv.gz')
    t = pd.to_datetime(f.calc_time, unit='ms', utc=True).dt.round('h')
    s = pd.Series(f.last_funding_rate.values.astype(float), index=pd.DatetimeIndex(t))
    assert str(s.index.tz) == 'UTC'
    s = s[~s.index.duplicated()].sort_index()
    ext = pd.date_range(s.index[-1] + pd.Timedelta(hours=8),
                        pd.Timestamp('2026-09-29 00:00', tz='UTC'), freq='8h')
    s = pd.concat([s, pd.Series(0.0001, index=ext)])
    s.attrs['n_assumed'] = len(ext)
    _cache['fund'] = s
    return s


def bar_inputs(tf, with_funding=True):
    """open-to-open return and funding factor per bar."""
    df = load_klines(tf)
    o = df.open.values
    ret = np.empty(len(df))
    ret[:-1] = o[1:] / o[:-1] - 1.0
    ret[-1] = df.close.values[-1] / o[-1] - 1.0
    F = np.zeros(len(df))
    if with_funding:
        fund = load_funding()
        h1 = load_klines('1h')
        p = h1['open'].reindex(fund.index)
        p = p.fillna(h1['close'].iloc[-1]).values
        T = df.index.values
        tau = fund.index.values
        idx = np.searchsorted(T, tau, side='left') - 1
        ok = idx >= 0
        ok &= tau <= (T[np.clip(idx, 0, None)] + BAR_LEN[tf].to_timedelta64())
        np.add.at(F, idx[ok], fund.values[ok] * p[ok] / o[idx[ok]])
    return ret, F


def run_engine(target, ret, F, cost, band=BAND, lev=1.0, op=None, lo=None, hi=None,
               mmr=0.005, liq=False):
    """Path-dependent simulation with a no-trade band.

    Returns dict of per-bar arrays: r (net), w (held weight), trade (|dw|), tc (trading cost),
    fund (funding paid, + = paid), gross (w*ret), liq (bool flag).
    """
    n = len(target)
    r_out = np.zeros(n); w_out = np.zeros(n); tr_out = np.zeros(n)
    tc_out = np.zeros(n); f_out = np.zeros(n); g_out = np.zeros(n)
    liq_flag = np.zeros(n, dtype=bool)
    wd = 0.0
    dead = False
    for i in range(n):
        if dead:
            continue
        tgt = target[i] * lev
        if tgt == 0.0 or wd == 0.0 or (tgt > 0) != (wd > 0) or abs(tgt - wd) > band * abs(tgt):
            w = tgt
        else:
            w = wd
        tr = abs(w - wd)
        c = tr * cost
        g = w * ret[i]
        f = w * F[i]
        r = g - f - c
        if liq and w != 0.0:
            x = (lo[i] / op[i] - 1.0) if w > 0 else (hi[i] / op[i] - 1.0)
            eq_worst = 1.0 - c + w * x
            maint = mmr * abs(w) * (1.0 + x)
            if eq_worst <= maint:
                r = -1.0
                liq_flag[i] = True
        if r <= -1.0:
            r = -1.0
            dead = True
        r_out[i] = r; w_out[i] = w; tr_out[i] = tr; tc_out[i] = c; f_out[i] = f; g_out[i] = g
        wd = 0.0 if dead else w * (1.0 + ret[i]) / (1.0 + r)
    return dict(r=r_out, w=w_out, trade=tr_out, tc=tc_out, fund=f_out, gross=g_out, liq=liq_flag)


def to_daily(index, res):
    """Aggregate per-bar results to UTC days (compounded net return, summed components)."""
    day = index.floor('D')
    df = pd.DataFrame({k: v for k, v in res.items() if k != 'liq'}, index=index)
    out = pd.DataFrame({
        'r': (1.0 + df['r']).groupby(day).prod() - 1.0,
        'gross': df['gross'].groupby(day).sum(),
        'tc': df['tc'].groupby(day).sum(),
        'fund': df['fund'].groupby(day).sum(),
        'trade': df['trade'].groupby(day).sum(),
        'absw': df['w'].abs().groupby(day).mean(),
        'inmkt': (df['w'] != 0).astype(float).groupby(day).mean(),
        'w0': df['w'].groupby(day).first(),
    })
    out['liq'] = pd.Series(res['liq'], index=index).groupby(day).any()
    return out


# ----------------------------------------------------------------- metrics
def max_dd(r):
    eq = np.cumprod(1.0 + np.asarray(r))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return (eq / peak - 1.0).min()


def metrics(d):
    """d: daily DataFrame slice from to_daily."""
    r = d['r'].values
    n = len(r)
    yrs = n / 365.25
    tot = np.prod(1.0 + r)
    cagr = tot ** (1.0 / yrs) - 1.0 if tot > 0 else -1.0
    sd = r.std(ddof=1)
    vol = sd * np.sqrt(365)
    sh = r.mean() / sd * np.sqrt(365) if sd > 0 else np.nan
    mdd = max_dd(r)
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    gross = d['gross'].sum()
    tc = d['tc'].sum(); fu = d['fund'].sum()
    share = (tc + fu) / gross if gross > 0 else np.nan
    return dict(CAGR=cagr, Vol=vol, Sharpe=sh, MaxDD=mdd, Calmar=calmar,
                Turnover=d['trade'].sum() / yrs, InMkt=d['inmkt'].mean(), AvgExp=d['absw'].mean(),
                GrossYr=gross / yrs, TCYr=tc / yrs, FundYr=fu / yrs, CostShare=share,
                TotRet=tot - 1.0, Days=n)


def sl(d, a, b):
    return d.loc[(d.index >= a) & (d.index <= b)]


# ----------------------------------------------------------------- bootstrap
def cbb_idx(n, block, nboot, rng):
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(nboot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return idx.reshape(nboot, -1)[:, :n]


def sharpe_rows(x):
    m = x.mean(axis=-1)
    s = x.std(axis=-1, ddof=1)
    return m / s * np.sqrt(365)
