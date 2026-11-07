"""Pre-registered strategy definitions. Each returns a *decision* series s_t (known at close of bar t);
run_all shifts by one bar to obtain the weight held during bar t+1 (filled at its open)."""
import numpy as np
import pandas as pd
from common import load_klines

TARGET_VOL, VT_CAP = 0.30, 2.0


def _d():
    return load_klines('1d')


def tsmom(L, ls):
    C = _d().close
    mom = C / C.shift(L) - 1.0
    s = np.where(mom > 0, 1.0, -1.0 if ls else 0.0)
    s[mom.isna().values] = 0.0
    return pd.Series(s, index=C.index)


def sma(N, ls):
    C = _d().close
    m = C.rolling(N).mean()
    s = np.where(C > m, 1.0, -1.0 if ls else 0.0)
    s[m.isna().values] = 0.0
    return pd.Series(s, index=C.index)


def xover(a, b):
    C = _d().close
    ma, mb = C.rolling(a).mean(), C.rolling(b).mean()
    s = (ma > mb).astype(float).to_numpy(copy=True)
    s[mb.isna().values] = 0.0
    return pd.Series(s, index=C.index)


def donchian(N, M, ls, atr_mult=2.0, atr_n=20, return_trades=False):
    df = _d()
    H, L, C, O = df.high.values, df.low.values, df.close.values, df.open.values
    n = len(C)
    hhN = pd.Series(H).rolling(N).max().shift(1).values
    llN = pd.Series(L).rolling(N).min().shift(1).values
    hhM = pd.Series(H).rolling(M).max().shift(1).values
    llM = pd.Series(L).rolling(M).min().shift(1).values
    prevC = np.r_[np.nan, C[:-1]]
    tr = np.nanmax(np.vstack([H - L, np.abs(H - prevC), np.abs(L - prevC)]), axis=0)
    atr = pd.Series(tr).rolling(atr_n).mean().values
    sig = np.zeros(n)
    pos, stop, pend_dir, pend_atr = 0, np.nan, 0, np.nan
    for t in range(n):
        if pend_dir != 0:               # entry filled at today's open -> fix stop
            stop = O[t] - pend_dir * atr_mult * pend_atr
            pend_dir = 0
        if np.isnan(hhN[t]) or np.isnan(atr[t]) or np.isnan(hhM[t]):
            sig[t] = 0.0
            continue
        new = pos
        if pos == 1:
            if C[t] < llM[t] or C[t] <= stop:
                new = -1 if (ls and C[t] < llN[t]) else 0
        elif pos == -1:
            if C[t] > hhM[t] or C[t] >= stop:
                new = 1 if C[t] > hhN[t] else 0
        else:
            if C[t] > hhN[t]:
                new = 1
            elif ls and C[t] < llN[t]:
                new = -1
        if new != 0 and new != pos:
            pend_dir, pend_atr = new, atr[t]
        pos = new
        sig[t] = float(pos)
    return pd.Series(sig, index=df.index)


def vol_mult():
    C = _d().close
    sig = np.log(C).diff().rolling(30).std() * np.sqrt(365)
    m = np.minimum(TARGET_VOL / sig, VT_CAP)
    return m.fillna(0.0)


def reversal(tf, lookback, zthr, hold, ls):
    df = load_klines(tf)
    C = df.close
    r = C / C.shift(1) - 1.0
    sd = r.rolling(lookback).std().shift(1)
    z = (r / sd).values
    n = len(C)
    sig = np.zeros(n)
    pos, left = 0, 0
    for t in range(n):
        zt = z[t]
        if not np.isnan(zt):
            if zt <= -zthr:
                pos, left = 1, hold
            elif ls and zt >= zthr:
                pos, left = -1, hold
        sig[t] = float(pos) if left > 0 else 0.0
        if left > 0:
            left -= 1
            if left == 0:
                pos = 0
    return pd.Series(sig, index=df.index)


def build_all():
    """name -> (timeframe, family, decision series)."""
    m = vol_mult()
    S = {}
    S['A1 TSMOM7-LS'] = ('1d', 'A', tsmom(7, True))
    S['A2 TSMOM30-LS'] = ('1d', 'A', tsmom(30, True))
    S['A3 TSMOM90-LS'] = ('1d', 'A', tsmom(90, True))
    S['A4 TSMOM30-LO'] = ('1d', 'A', tsmom(30, False))
    S['A5 TSMOM90-LO'] = ('1d', 'A', tsmom(90, False))
    S['B1 SMA50-LO'] = ('1d', 'B', sma(50, False))
    S['B2 SMA100-LO'] = ('1d', 'B', sma(100, False))
    S['B3 SMA200-LO'] = ('1d', 'B', sma(200, False))
    S['B4 SMA100-LS'] = ('1d', 'B', sma(100, True))
    S['B5 X50/200-LO'] = ('1d', 'B', xover(50, 200))
    S['C1 DON20/10-LS'] = ('1d', 'C', donchian(20, 10, True))
    S['C2 DON55/20-LO'] = ('1d', 'C', donchian(55, 20, False))
    S['C3 DON55/20-LS'] = ('1d', 'C', donchian(55, 20, True))
    S['D1 VT-BH'] = ('1d', 'D', pd.Series(1.0, index=m.index) * m)
    S['D2 VT-TSMOM30-LS'] = ('1d', 'D', S['A2 TSMOM30-LS'][2] * m)
    S['D3 VT-SMA100-LO'] = ('1d', 'D', S['B2 SMA100-LO'][2] * m)
    S['E1 REV4h-LS'] = ('4h', 'E', reversal('4h', 180, 2.5, 6, True))
    S['E2 REV4h-LO'] = ('4h', 'E', reversal('4h', 180, 2.5, 6, False))
    S['E3 REV1h-LS'] = ('1h', 'E', reversal('1h', 720, 3.0, 12, True))
    lo = pd.concat([S[k][2] for k in ['A4 TSMOM30-LO', 'A5 TSMOM90-LO', 'B2 SMA100-LO', 'C2 DON55/20-LO']], axis=1).mean(axis=1)
    ls = pd.concat([S[k][2] for k in ['A2 TSMOM30-LS', 'A3 TSMOM90-LS', 'B4 SMA100-LS', 'C3 DON55/20-LS']], axis=1).mean(axis=1)
    S['F1 COMBO-LO'] = ('1d', 'F', lo * m)
    S['F2 COMBO-LS'] = ('1d', 'F', ls * m)
    return S
