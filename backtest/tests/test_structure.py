"""구조 테스트 (DESIGN §9 T-STR, RULES_SPEC §3 스윙·§4 기준봉·마디·허리).

손 계산 사례 + 명세 문장을 그대로 옮긴 느린 참조 구현과의 무작위 대조.
이 파일의 도우미(make_ind, madi_frame, make_struct)는 test_filters·test_scenarios도 가져다 쓴다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import indicators as IND
from backtest import structure as S
from backtest.types import MADI_COLUMNS, ScenarioContext, Structure
from backtest.tests.conftest import make_bars, random_walk_bars

# ---------------------------------------------------------------------------
# 공용 도우미 (다른 테스트 파일도 쓴다)
# ---------------------------------------------------------------------------

IND_DEFAULTS = dict(body=1.0, range=1.0, tr=1.0, atr=0.6, vol_avg=100.0, vr=1.0, body_avg=1.0, long_bar=False,
                    upper_wick=0.1, lower_wick=0.1, ma20=100.0, ma60=100.0, ma120=100.0, spread=0.0,
                    spread_q80=1.0, spread_on=False, slope20=1.0, slope60=1.0, slope120=1.0, atr_q20=0.0,
                    surge=False, buffer=0.06, valid=True)


def make_ind(bars: pd.DataFrame, **cols) -> pd.DataFrame:
    """손으로 정한 지표 프레임 (열 = INDICATOR_COLUMNS). cols 값은 스칼라 또는 봉 수 길이 배열.

    atr만 주고 buffer를 안 주면 buffer = 0.1 × atr.
    """
    n = len(bars)
    vals = dict(IND_DEFAULTS)
    vals.update(cols)
    if "atr" in cols and "buffer" not in cols:
        vals["buffer"] = C.BUFFER_ATR_MULT * np.asarray(cols["atr"], dtype=np.float64)
    data = {}
    for name in IND.INDICATOR_COLUMNS:
        dtype = bool if name in IND.BOOL_INDICATOR_COLUMNS else np.float64
        data[name] = np.array(np.broadcast_to(np.asarray(vals[name], dtype=dtype), (n,)))
    return pd.DataFrame(data, index=bars.index)


def madi_frame(rows: list[dict], bars: pd.DataFrame | None = None) -> pd.DataFrame:
    """손으로 정한 마디 표 (열 = MADI_COLUMNS). 빠진 값은 채운다: w = |B − A|, h_mid, end_idx, tb_close_ns 등."""
    if not rows:
        return S.empty_madis()
    out = []
    n = len(bars) if bars is not None else 10**9
    for r in rows:
        r = dict(r)
        r.setdefault("direction", 1)
        r.setdefault("kijun_idx", r["b_idx"])
        r.setdefault("tb_idx", r["b_idx"] + 3)
        r.setdefault("w", abs(r["b_price"] - r["a_price"]))
        r.setdefault("h_mid", S.waist_midpoint(r["a_price"], r["b_price"]))
        r.setdefault("h_cluster", r["h_mid"])
        r.setdefault("waist_fallback", False)
        r.setdefault("vol_ab_mean", 1000.0)
        r.setdefault("vol_pre_mean", 100.0)
        r.setdefault("death_idx", n)
        r.setdefault("end_idx", min(r["death_idx"] - 1, r["tb_idx"] + C.MADI_ALIVE_BARS))
        if bars is not None:
            r.setdefault("tb_close_ns", int(bars["close_ns"].iloc[r["tb_idx"]]))
            tag = "U" if r["direction"] > 0 else "D"
            r.setdefault("madi_id", f"1h{tag}-{S.fmt_minute(int(bars['open_ns'].iloc[r['b_idx']]))}")
        r.setdefault("tb_close_ns", 0)
        r.setdefault("madi_id", f"m{len(out)}")
        out.append(r)
    df = pd.DataFrame(out, columns=list(MADI_COLUMNS))
    df = df.sort_values(["tb_idx", "kijun_idx", "direction"], kind="stable").reset_index(drop=True)
    return df.astype(S._MADI_DTYPES)


def make_struct(bars: pd.DataFrame, madis: pd.DataFrame | None = None, *, is_sh=None, is_sl=None,
                tf: str = "1h") -> Structure:
    """손으로 정한 스윙·마디로 Structure를 만든다 (alive는 paint_alive로)."""
    n = len(bars)
    is_sh = np.zeros(n, dtype=bool) if is_sh is None else np.asarray(is_sh, dtype=bool)
    is_sl = np.zeros(n, dtype=bool) if is_sl is None else np.asarray(is_sl, dtype=bool)
    madis = S.empty_madis() if madis is None else madis
    return Structure(tf=tf, is_sh=is_sh, is_sl=is_sl, last_sh=S.last_confirmed(is_sh), last_sl=S.last_confirmed(is_sl),
                     kijun_up=np.zeros(n, dtype=bool), kijun_dn=np.zeros(n, dtype=bool), madis=madis,
                     alive_up=S.paint_alive(madis, n, 1), alive_dn=S.paint_alive(madis, n, -1))


def make_ctx(s_bars: pd.DataFrame, s_ind: pd.DataFrame | None = None, s_madis: pd.DataFrame | None = None, *,
             is_sh=None, is_sl=None, c_bars: pd.DataFrame | None = None, d_bars: pd.DataFrame | None = None,
             d_slope: float = 1.0, d_madis: pd.DataFrame | None = None, flags: dict | None = None,
             setting: str = "P1", vr_threshold: float = C.KIJUN_VR_MIN, events_ns=None) -> ScenarioContext:
    """손으로 정한 재료로 ScenarioContext를 만든다 (시나리오·필터 단위 테스트용).

    - D 봉: 없으면 S 봉을 합쳐 만든다(P1 4h, P2 1d). D 지표는 기울기 60·120 = d_slope (DB 허용 방향).
    - C 봉: 없으면 S 봉을 쪼갠다(P1 15m, P2 1h). s_flags: flags {열: bool 배열} 외에는 모두 False.
    """
    from backtest.tests.conftest import aggregate_bars, split_bars
    bs = C.SETTINGS[setting]
    s_ind = make_ind(s_bars) if s_ind is None else s_ind
    d_bars = aggregate_bars(s_bars, bs.direction) if d_bars is None else d_bars
    c_bars = split_bars(s_bars, bs.confirm) if c_bars is None else c_bars
    fl = {k: np.zeros(len(s_bars), dtype=bool) for k in ("F2", "F4", "F5", "F6")}
    fl.update({k: np.asarray(v, dtype=bool) for k, v in (flags or {}).items()})
    return ScenarioContext(
        setting=setting, vr_threshold=float(vr_threshold), s_tf=bs.signal, d_tf=bs.direction, c_tf=bs.confirm,
        s_bars=s_bars, s_ind=s_ind, s_struct=make_struct(s_bars, s_madis, is_sh=is_sh, is_sl=is_sl, tf=bs.signal),
        d_bars=d_bars, d_ind=make_ind(d_bars, slope60=d_slope, slope120=d_slope),
        d_struct=make_struct(d_bars, d_madis, tf=bs.direction), c_bars=c_bars,
        s_flags=pd.DataFrame(fl, index=s_bars.index), events_ns=events_ns)


def flat_rows(n: int, price: float = 101.0) -> list[list[float]]:
    """(o, h, l, c, v) 평평한 봉 n개 (수정해서 쓰는 바탕)."""
    return [[price, price, price, price, 100.0] for _ in range(n)]


def mask(n: int, idx) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    m[list(idx)] = True
    return m


# ---------------------------------------------------------------------------
# 느린 참조 구현 (명세 문장 그대로, 파이썬 반복)
# ---------------------------------------------------------------------------


def ref_swings(high, low, k=3):
    n = len(high)
    sh = [False] * n
    sl = [False] * n
    for i in range(k, n - k):
        nb = [j for j in range(i - k, i + k + 1) if j != i]
        sh[i] = all(high[i] > high[j] for j in nb)
        sl[i] = all(low[i] < low[j] for j in nb)
    return np.array(sh), np.array(sl)


def ref_kijun(bars, ind, last_sh, last_sl, vr_th):
    o, h, l, c = (bars[k].to_numpy() for k in ("open", "high", "low", "close"))
    up, dn = [], []
    for t in range(len(c)):
        g = ind.iloc[t]
        base = bool(g.valid) and bool(g.long_bar) and g.vr >= vr_th and not bool(g.spread_on)
        up.append(base and c[t] > o[t] and g.slope20 > 0 and g.slope60 > 0 and last_sh[t] >= 0
                  and c[t] > h[last_sh[t]] and g.upper_wick < 0.5)
        dn.append(base and c[t] < o[t] and g.slope20 < 0 and g.slope60 < 0 and last_sl[t] >= 0
                  and c[t] < l[last_sl[t]] and g.lower_wick < 0.5)
    return np.array(up), np.array(dn)


def ref_waist(o, h, l, c, v, a, b, A, B):
    """§4.3 허리를 칸 목록으로 직접 세는 참조 구현 (I-13 해석)."""
    d = 1.0 if B > A else -1.0
    W = abs(B - A)
    start = A + d * 0.35 * W
    bw = start * 0.001
    umax = (0.65 - 0.35) * W / bw
    K = max(1, math.ceil(umax - 1e-9))
    counts = [0] * K
    for j in range(a, b + 1):
        for x in (o[j], h[j], l[j], c[j]):
            u = d * (x - start) / bw
            if -1e-9 <= u <= umax + 1e-9:
                counts[min(max(int(math.floor(u + 1e-9)), 0), K - 1)] += 1
    if sum(counts) == 0:
        return C.round_price(A + d * 0.5 * W), True
    best = max(counts)
    tied = [i for i in range(K) if counts[i] == best]
    if len(tied) > 1:
        vols = {}
        for i in tied:
            lo_u, hi_u = float(i), min(i + 1.0, umax)
            tot = 0.0
            for j in range(a, b + 1):
                ul, uh = d * (l[j] - start) / bw, d * (h[j] - start) / bw
                if min(ul, uh) <= hi_u + 1e-9 and max(ul, uh) >= lo_u - 1e-9:
                    tot += v[j]
            vols[i] = tot
        top = max(vols.values())
        tied = [i for i in tied if abs(vols[i] - top) <= 1e-9 * max(1.0, abs(top))]
    i = min(tied)
    return C.round_price(start + d * (i + min(i + 1.0, umax)) / 2.0 * bw), False


def ref_madis(bars, is_sh, is_sl, last_sh, last_sl, kijun_up, kijun_dn):
    o, h, l, c, v = (bars[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    n = len(c)
    out = []
    for direction in (1, -1):
        up = direction > 0
        kij, last_a, is_b = (kijun_up, last_sl, is_sh) if up else (kijun_dn, last_sh, is_sl)
        seen = set()
        for t in range(n):
            if not kij[t] or last_a[t] < 0:
                continue
            a = int(last_a[t])
            b = next((i for i in range(t, n) if is_b[i]), None)
            if b is None:
                continue
            tb = b + 3
            if tb > t + 60 or tb > n - 1:
                continue
            A = l[a] if up else h[a]
            B = h[b] if up else l[b]
            W = (B - A) if up else (A - B)
            if W <= 0 or a < 20:
                continue
            if any((c[j] < A) if up else (c[j] > A) for j in range(a, tb + 1)):
                continue
            if np.mean(v[a:b + 1]) < np.mean(v[a - 20:a]):
                continue
            if b in seen:
                continue
            seen.add(b)
            death = next((j for j in range(tb + 1, n) if ((c[j] < A) if up else (c[j] > A))), n)
            H, fb = ref_waist(o, h, l, c, v, a, b, A, B)
            out.append((direction, t, a, b, tb, A, B, W, H, fb, death, min(death - 1, tb + 300)))
    out.sort(key=lambda x: (x[4], x[1], x[0]))
    return out


# ---------------------------------------------------------------------------
# T-STR-1·2 스윙
# ---------------------------------------------------------------------------


def test_swing_strict_inequality():
    h = np.array([1, 2, 3, 5, 3, 2, 1], dtype=float)
    sh, sl = S.find_swings(h, h - 0.5)
    assert sh.tolist() == [False, False, False, True, False, False, False]
    h2 = np.array([1, 2, 5, 5, 3, 2, 1, 0], dtype=float)          # 동률이면 스윙 아님 (I-6)
    assert not S.find_swings(h2, h2 - 0.5)[0].any()
    low = np.array([5, 4, 3, 1, 3, 4, 5], dtype=float)            # 저점 대칭
    assert S.find_swings(low + 0.5, low)[1].tolist() == [False, False, False, True, False, False, False]
    assert not S.find_swings(h[:6], h[:6] - 0.5)[0].any()          # 뒤 3봉이 없으면 아직 스윙 아님


def test_swings_match_reference_random(rng):
    for _ in range(5):
        high = np.round(rng.normal(0, 1, 400).cumsum() * 2, 0) / 2 + 100   # 0.5 격자 → 동률이 자주 생김
        low = high - np.round(rng.uniform(0, 2, 400), 0) / 2
        sh, sl = S.find_swings(high, low)
        rsh, rsl = ref_swings(high, low)
        np.testing.assert_array_equal(sh, rsh)
        np.testing.assert_array_equal(sl, rsl)


def test_last_confirmed_waits_three_bars():
    is_sw = mask(20, [5, 11])
    last = S.last_confirmed(is_sw)
    assert last[7] == -1 and last[8] == 5                           # i+2 시점은 모름, i+3 마감에 확정 (C-4)
    assert last[13] == 5 and last[14] == 11 and last[19] == 11
    bars = make_bars(closes=np.arange(20) + 100.0)
    known = S.swing_known_ns(bars["close_ns"].to_numpy(), is_sw)
    assert known[5] == bars["close_ns"].iloc[8] and known[11] == bars["close_ns"].iloc[14]
    assert (np.delete(known, [5, 11]) == -1).all()


# ---------------------------------------------------------------------------
# T-STR-3 기준봉
# ---------------------------------------------------------------------------


def _kijun_case():
    rows = flat_rows(12, 100.0)
    rows[3] = [100, 105, 99.5, 100.5, 100]            # 스윙 고점 역할(고가 105)
    rows[8] = [100, 110.5, 99.5, 110, 100]            # 양봉 기준봉 후보: 종가 110 > 105
    rows[9] = [100, 100.5, 89.5, 90, 100]             # 음봉 기준봉 후보: 종가 90 < 95
    rows[4] = [100, 100.5, 95, 99.5, 100]             # 스윙 저점 역할(저가 95)
    bars = make_bars(rows)
    n = len(bars)
    last_sh = np.full(n, -1)
    last_sh[6:] = 3
    last_sl = np.full(n, -1)
    last_sl[7:] = 4
    ind = make_ind(bars, long_bar=True, vr=2.5, slope20=np.r_[np.ones(9), -np.ones(3)],
                   slope60=np.r_[np.ones(9), -np.ones(3)], upper_wick=0.05, lower_wick=0.05)
    return bars, ind, last_sh, last_sl


def test_kijun_positive_up_and_down():
    bars, ind, last_sh, last_sl = _kijun_case()
    up, dn = S.detect_kijun(bars, ind, last_sh, last_sl)
    assert np.flatnonzero(up).tolist() == [8]
    assert np.flatnonzero(dn).tolist() == [9]


@pytest.mark.parametrize("change", ["bearish", "not_long", "vr", "slope20_zero", "slope20_neg", "slope60_zero",
                                    "close_eq_swing_high", "no_swing", "upper_wick", "spread", "invalid"])
def test_kijun_each_condition_breaks(change):
    bars, ind, last_sh, last_sl = _kijun_case()
    t = 8
    ind = ind.copy()
    if change == "bearish":
        bars = bars.copy()
        bars.loc[bars.index[t], ["open", "close"]] = [110.0, 100.0]
    elif change == "not_long":
        ind.loc[ind.index[t], "long_bar"] = False
    elif change == "vr":
        ind.loc[ind.index[t], "vr"] = 1.99
    elif change == "slope20_zero":
        ind.loc[ind.index[t], "slope20"] = 0.0
    elif change == "slope20_neg":
        ind.loc[ind.index[t], "slope20"] = -1.0
    elif change == "slope60_zero":
        ind.loc[ind.index[t], "slope60"] = 0.0
    elif change == "close_eq_swing_high":
        bars = bars.copy()
        bars.loc[bars.index[3], "high"] = 110.0           # close == 최근 확정 스윙 고점 → 아님 (엄격)
    elif change == "no_swing":
        last_sh = last_sh.copy()
        last_sh[t] = -1
    elif change == "upper_wick":
        ind.loc[ind.index[t], "upper_wick"] = 0.5          # §4.1-5 ≥ 0.5 제외
    elif change == "spread":
        ind.loc[ind.index[t], "spread_on"] = True
    elif change == "invalid":
        ind.loc[ind.index[t], "valid"] = False
    up, _ = S.detect_kijun(bars, ind, last_sh, last_sl)
    assert not up[t]


def test_kijun_vr_threshold_3():
    bars, ind, last_sh, last_sl = _kijun_case()
    assert S.detect_kijun(bars, ind, last_sh, last_sl, vr_threshold=2.0)[0][8]
    assert not S.detect_kijun(bars, ind, last_sh, last_sl, vr_threshold=3.0)[0][8]   # vr 2.5 탈락 (I-26)
    ind.loc[ind.index[8], "vr"] = 3.0
    assert S.detect_kijun(bars, ind, last_sh, last_sl, vr_threshold=3.0)[0][8]


def test_kijun_matches_reference_random():
    for seed in range(3):
        bars = random_walk_bars(1500, seed=seed)
        ind = IND.compute_indicators(bars)
        sh, sl = S.find_swings(bars["high"].to_numpy(), bars["low"].to_numpy())
        lsh, lsl = S.last_confirmed(sh), S.last_confirmed(sl)
        for vr_th in (1.0, 2.0):
            up, dn = S.detect_kijun(bars, ind, lsh, lsl, vr_th)
            rup, rdn = ref_kijun(bars, ind, lsh, lsl, vr_th)
            np.testing.assert_array_equal(up, rup)
            np.testing.assert_array_equal(dn, rdn)


# ---------------------------------------------------------------------------
# T-STR-4 기준마디
# ---------------------------------------------------------------------------


def _madi_case(n: int = 120):
    """A = 95 (봉 25 스윙 저점), 기준봉 30, B = 110 (봉 33 스윙 고점) → T_B = 36."""
    rows = flat_rows(n, 100.0)
    for j in range(25, n):
        rows[j] = [104.0, 104.5, 103.5, 104.0, 100.0]
    rows[25] = [100.0, 100.5, 95.0, 99.0, 300.0]
    for j, px in zip(range(26, 33), (99, 100, 101, 102, 106, 107, 108)):
        rows[j] = [px - 0.5, px + 0.5, px - 1.0, px, 300.0]
    rows[33] = [108.0, 110.0, 107.5, 109.0, 300.0]
    for j, px in zip(range(34, 37), (107.0, 106.0, 105.0)):
        rows[j] = [px + 0.5, px + 1.0, px - 0.5, px, 100.0]
    bars = make_bars(rows)
    is_sh, is_sl = mask(n, [33]), mask(n, [25])
    kup = mask(n, [30])
    return bars, is_sh, is_sl, kup


def _detect(bars, is_sh, is_sl, kup, kdn=None):
    n = len(bars)
    kdn = np.zeros(n, dtype=bool) if kdn is None else kdn
    return S.detect_madis(bars, make_ind(bars), is_sh, is_sl, S.last_confirmed(is_sh), S.last_confirmed(is_sl),
                          kup, kdn, "1h")


def test_madi_basic_values():
    bars, is_sh, is_sl, kup = _madi_case()
    m = _detect(bars, is_sh, is_sl, kup)
    assert list(m.columns) == list(MADI_COLUMNS) and len(m) == 1
    r = m.iloc[0]
    assert (r.direction, r.kijun_idx, r.a_idx, r.b_idx, r.tb_idx) == (1, 30, 25, 33, 36)
    assert (r.a_price, r.b_price, r.w) == (95.0, 110.0, 15.0)
    assert r.tb_close_ns == bars["close_ns"].iloc[36]                 # 알게 된 시각 = T_B 봉 마감
    assert r.madi_id == "1hU-" + bars.index[33].strftime("%Y%m%d%H%M")
    assert r.vol_ab_mean == pytest.approx(300.0) and r.vol_pre_mean == pytest.approx(100.0)
    assert r.death_idx == len(bars) and r.end_idx == len(bars) - 1   # 데이터 끝까지 살아 있음 (n = 120 < tb + 300)
    assert r.h_mid == 102.5
    assert m.dtypes["direction"] == np.int8 and m.dtypes["waist_fallback"] == bool


def test_madi_invalid_close_below_a_before_tb():
    for j in (34, 36):                                                # T_B 전, T_B 봉 자신 (I-9)
        bars, is_sh, is_sl, kup = _madi_case()
        bars.loc[bars.index[j], ["low", "close"]] = [94.0, 94.9]
        assert len(_detect(bars, is_sh, is_sl, kup)) == 0


def test_madi_invalid_b_not_within_60_bars():
    bars, is_sh, is_sl, kup = _madi_case()
    far = mask(len(bars), [88])                                      # tb = 91 > 30 + 60
    assert len(_detect(bars, far, is_sl, kup)) == 0
    near = mask(len(bars), [87])                                     # tb = 90 = 30 + 60 → 유효
    assert _detect(bars, near, is_sl, kup)["tb_idx"].tolist() == [90]


def test_madi_invalid_volume_condition_and_a_before_20():
    bars, is_sh, is_sl, kup = _madi_case()
    bars.loc[bars.index[5:25], "volume"] = 400.0                    # A 직전 20봉 평균 > A~B 평균
    assert len(_detect(bars, is_sh, is_sl, kup)) == 0
    bars, is_sh, is_sl, kup = _madi_case()
    bars.loc[bars.index[5:25], "volume"] = 300.0                    # 같으면 유효 (≥)
    assert len(_detect(bars, is_sh, is_sl, kup)) == 1
    for a_idx, expect in ((19, 0), (20, 1)):                          # a_idx < 20 → 무효 (I-10), 20이면 유효
        bars, is_sh, _, kup = _madi_case()
        bars.loc[bars.index[a_idx], "low"] = 90.0                     # 그 봉만 A 후보(종가는 모두 A 위)
        assert len(_detect(bars, is_sh, mask(len(bars), [a_idx]), kup)) == expect


def test_madi_same_b_keeps_earliest_kijun_and_tb_beyond_data():
    bars, is_sh, is_sl, kup = _madi_case()
    kup2 = mask(len(bars), [30, 31, 32])
    m = _detect(bars, is_sh, is_sl, kup2)
    assert m["kijun_idx"].tolist() == [30]                            # I-11
    short = bars.iloc[:36]                                            # T_B 봉이 데이터에 없음 → 아직 마디 없음
    assert len(_detect(short, is_sh[:36], is_sl[:36], kup[:36])) == 0
    assert len(_detect(bars.iloc[:37], is_sh[:37], is_sl[:37], kup[:37])) == 1


def test_madi_matches_reference_random():
    total = 0
    for seed in range(4):
        bars = random_walk_bars(2500, seed=seed)
        ind = IND.compute_indicators(bars)
        sh, sl = S.find_swings(bars["high"].to_numpy(), bars["low"].to_numpy())
        lsh, lsl = S.last_confirmed(sh), S.last_confirmed(sl)
        up, dn = S.detect_kijun(bars, ind, lsh, lsl, 1.0)             # VR 1 → 마디가 많아지게
        got = S.detect_madis(bars, ind, sh, sl, lsh, lsl, up, dn, "1h")
        ref = ref_madis(bars, sh, sl, lsh, lsl, up, dn)
        assert len(got) == len(ref)
        total += len(ref)
        for (_, row), exp in zip(got.iterrows(), ref):
            d, t, a, b, tb, A, B, W, H, fb, death, end = exp
            assert (row.direction, row.kijun_idx, row.a_idx, row.b_idx, row.tb_idx) == (d, t, a, b, tb)
            assert (row.a_price, row.b_price) == (A, B) and row.w == pytest.approx(W, abs=1e-9)
            assert row.h_cluster == H and row.waist_fallback == fb
            assert (row.death_idx, row.end_idx) == (death, end)
            assert row.tb_close_ns == bars["close_ns"].iloc[tb]
    assert total >= 20


# ---------------------------------------------------------------------------
# T-STR-5~8 허리
# ---------------------------------------------------------------------------


def _waist_bars(rows):
    return make_bars([list(r[:4]) + [r[4] if len(r) > 4 else 100.0] for r in rows])


def test_waist_design_example():
    rows = [(101, 101, 100, 101)] + [(105.0, 105.0, 105.0, 105.0)] * 5 + [(109, 110, 108, 109)]
    H, fb = S.waist_cluster(_waist_bars(rows), 0, 6, 100.0, 110.0)
    assert (H, fb) == (105.0, False)                                  # DESIGN §6.5 예시 (칸 14 가운데 105.00075)
    assert S.waist_midpoint(100.0, 110.0) == 105.0


def test_waist_tie_breaks_by_volume_then_nearest_to_a():
    # 칸 4 (104.0)와 칸 24 (106.0)가 4표씩 동점
    up_rows = [(101, 101, 100, 101), (104.0, 104.0, 104.0, 104.0, 10.0), (106.0, 106.0, 106.0, 106.0, 20.0),
               (109, 110, 108, 109)]
    assert S.waist_cluster(_waist_bars(up_rows), 0, 3, 100.0, 110.0) == (106.0, False)   # 거래량 큰 칸
    up_rows[1] = (104.0, 104.0, 104.0, 104.0, 20.0)
    assert S.waist_cluster(_waist_bars(up_rows), 0, 3, 100.0, 110.0) == (104.0, False)   # 같으면 낮은 칸 (A 쪽)
    # 하락 마디(A = 110 스윙 고점, B = 100): 같으면 높은 칸 (A 쪽)
    dn_rows = [(109, 110, 108, 109), (104.0, 104.0, 104.0, 104.0, 20.0), (106.0, 106.0, 106.0, 106.0, 20.0),
               (101, 101, 100, 101)]
    assert S.waist_cluster(_waist_bars(dn_rows), 0, 3, 110.0, 100.0) == (106.0, False)
    dn_rows[1] = (104.0, 104.0, 104.0, 104.0, 30.0)
    assert S.waist_cluster(_waist_bars(dn_rows), 0, 3, 110.0, 100.0) == (104.0, False)


def test_waist_fallback_when_band_empty():
    rows = [(101, 101, 100, 101), (102, 103, 101.5, 102.5), (108, 109, 107, 108), (109, 110, 108, 109)]
    assert S.waist_cluster(_waist_bars(rows), 0, 3, 100.0, 110.0) == (105.0, True)
    rows_dn = [(109, 110, 108, 109), (108, 109, 107, 108), (102, 103, 101.5, 102.5), (101, 101, 100, 101)]
    assert S.waist_cluster(_waist_bars(rows_dn), 0, 3, 110.0, 100.0) == (105.0, True)
    assert S.waist_cluster(_waist_bars(rows), 0, 3, 100.0, 110.4) == (105.2, True)


def test_waist_band_ends_inclusive_and_last_bin_truncated():
    # 구간 끝값 103.5·106.5만 있으면: 칸 0 (4표) vs 마지막 칸(잘린 칸 28, 4표) → 동점, 거래량 같음 → A 쪽 칸 0
    rows = [(103.5, 103.5, 103.5, 103.5), (106.5, 106.5, 106.5, 106.5)]
    H, fb = S.waist_cluster(_waist_bars(rows), 0, 1, 100.0, 110.0)
    assert (H, fb) == (C.round_price(103.5 + 0.5 * 0.1035), False)
    rows = [(106.5, 106.5, 106.5, 106.5)] * 2 + [(103.5, 103.5, 103.5, 103.5)]
    H, _ = S.waist_cluster(_waist_bars(rows), 0, 2, 100.0, 110.0)
    last_lo = 103.5 + 28 * 0.1035                                     # 잘린 마지막 칸 [106.398, 106.5]
    assert H == C.round_price((last_lo + 106.5) / 2)


def test_waist_matches_reference_random(rng):
    for _ in range(300):
        n = int(rng.integers(2, 25))
        A = float(np.round(rng.uniform(90, 110), 1))
        W = float(np.round(rng.uniform(0.5, 20), 1))
        d = 1.0 if rng.random() < 0.5 else -1.0
        B = A + d * W
        lo, hi = min(A, B), max(A, B)
        grid = rng.choice([0.1, 0.5, 1.0])                            # 거친 격자 → 동점이 자주 생김
        pts = np.round(rng.uniform(lo, hi, (n, 4)) / grid) * grid
        o, c = pts[:, 0], pts[:, 3]
        h = np.maximum.reduce([pts[:, 1], o, c])
        l = np.minimum.reduce([pts[:, 2], o, c])
        v = rng.choice([10.0, 20.0, 30.0], n)
        got = S._waist_cluster_core(o, h, l, c, v, 0, n - 1, A, B)
        assert got == ref_waist(o, h, l, c, v, 0, n - 1, A, B)


def test_down_madi_mirrors_up_madi():
    bars, is_sh, is_sl, kup = _madi_case()
    up = _detect(bars, is_sh, is_sl, kup).iloc[0]
    K = 2 * (up.a_price + 0.35 * up.w)                                # 반전 뒤에도 칸 시작·폭이 같게 (103.5 → 103.5)
    mir = bars.copy()
    mir["open"], mir["close"] = K - bars["open"], K - bars["close"]
    mir["high"], mir["low"] = K - bars["low"], K - bars["high"]
    n = len(bars)
    dn = S.detect_madis(mir, make_ind(mir), is_sl, is_sh, S.last_confirmed(is_sl), S.last_confirmed(is_sh),
                        np.zeros(n, dtype=bool), kup, "1h")
    assert len(dn) == 1
    d = dn.iloc[0]
    assert (d.direction, d.kijun_idx, d.a_idx, d.b_idx, d.tb_idx) == (-1, 30, 25, 33, 36)
    assert d.a_price == pytest.approx(K - up.a_price) and d.b_price == pytest.approx(K - up.b_price)
    assert d.w == pytest.approx(up.w)
    assert abs(d.h_cluster - (K - up.h_cluster)) <= 0.1 + 1e-9          # 반올림 안에서 대칭
    assert d.madi_id.startswith("1hD-")


# ---------------------------------------------------------------------------
# T-STR-9·10 살아 있는 마디
# ---------------------------------------------------------------------------


def test_alive_boundaries_and_death():
    bars, is_sh, is_sl, kup = _madi_case(n=400)
    m = _detect(bars, is_sh, is_sl, kup)
    r = m.iloc[0]
    assert r.end_idx == 36 + 300 and r.death_idx == 400
    alive = S.paint_alive(m, len(bars), 1)
    assert alive[36] == 0 and alive[336] == 0 and alive[337] == -1 and alive[35] == -1   # tb ≤ t ≤ tb+300
    assert S.paint_alive(m, len(bars), 1, start_offset=1)[36] == -1                       # 확정 "후"만 (I-24)
    assert (S.paint_alive(m, len(bars), -1) == -1).all()
    bars.loc[bars.index[50], ["low", "close"]] = [94.0, 94.5]                             # 첫 close < A 봉부터 죽음
    m2 = _detect(bars, is_sh, is_sl, kup)
    assert m2.iloc[0].death_idx == 50 and m2.iloc[0].end_idx == 49
    a2 = S.paint_alive(m2, len(bars), 1)
    assert a2[49] == 0 and a2[50] == -1


def test_paint_alive_most_recent_and_most_recent_confirmed():
    bars = make_bars(closes=np.full(100, 100.0))
    m = madi_frame([dict(a_idx=20, b_idx=27, a_price=90.0, b_price=110.0, end_idx=80),     # tb 30
                    dict(a_idx=35, b_idx=37, a_price=95.0, b_price=105.0, end_idx=50),     # tb 40, 일찍 죽음
                    dict(direction=-1, a_idx=40, b_idx=42, a_price=120.0, b_price=100.0, end_idx=70)], bars)
    alive = S.paint_alive(m, 100, 1)
    assert alive[29] == -1 and alive[30] == 0 and alive[39] == 0
    assert alive[40] == 1 and alive[50] == 1                          # 더 최근(큰 tb) 마디
    assert alive[51] == 0 and alive[80] == 0 and alive[81] == -1       # 최근 것이 죽으면 이전 것이 다시 보임
    assert S.paint_alive(m, 100, -1)[45] == 2
    mrc = S.most_recent_confirmed(m, 100, 1)
    assert mrc[29] == -1 and mrc[30] == 0 and mrc[40] == 1 and mrc[99] == 1                # 죽은 마디도 (I-25)
    assert S.most_recent_confirmed(m, 100, -1)[44] == -1 and S.most_recent_confirmed(m, 100, -1)[45] == 2
    np.testing.assert_array_equal(S.madi_waist(m, "midpoint"), m["h_mid"].to_numpy())
    np.testing.assert_array_equal(S.madi_waist(m, "cluster"), m["h_cluster"].to_numpy())
    with pytest.raises(ValueError):
        S.madi_waist(m, "median")


def test_build_structure_contracts_on_random_walk():
    bars = random_walk_bars(3000, seed=4)
    ind = IND.compute_indicators(bars)
    st = S.build_structure(bars, ind, "1h")
    n = len(bars)
    for arr in (st.is_sh, st.is_sl, st.kijun_up, st.kijun_dn):
        assert arr.dtype == bool and arr.shape == (n,)
    for arr in (st.last_sh, st.last_sl, st.alive_up, st.alive_dn):
        assert arr.dtype == np.int64 and arr.shape == (n,)
    m = st.madis
    assert len(m) > 0 and list(m.columns) == list(MADI_COLUMNS)
    assert (m["tb_idx"] == m["b_idx"] + 3).all() and m["madi_id"].is_unique
    assert (np.diff(m["tb_idx"].to_numpy()) >= 0).all()
    close_ns = bars["close_ns"].to_numpy()
    for _, r in m.iterrows():
        last_a = st.last_sl if r.direction > 0 else st.last_sh
        assert last_a[r.kijun_idx] == r.a_idx and r.a_idx + 3 <= r.kijun_idx            # A는 기준봉 시점에 확정
        assert (st.kijun_up if r.direction > 0 else st.kijun_dn)[r.kijun_idx]
        assert r.kijun_idx <= r.b_idx and r.tb_idx <= r.kijun_idx + 60
        assert r.tb_close_ns == close_ns[r.tb_idx]
        lo, hi = sorted((r.a_price, r.b_price))
        assert lo + 0.35 * r.w - 0.05 - 1e-9 <= r.h_cluster <= lo + 0.65 * r.w + 0.05 + 1e-9
    empty = S.build_structure(bars.iloc[:50], ind.iloc[:50], "1h")
    assert len(empty.madis) == 0 and list(empty.madis.columns) == list(MADI_COLUMNS)
