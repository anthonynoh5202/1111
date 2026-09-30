"""독립 검증용 최소 구현 — backtest 패키지를 import 하지 않는다.

원자료(data/binance/*.csv.gz)와 docs/RULES_SPEC.md v1.0 만으로 봉·지표·스윙·기준봉·마디·허리·체결을 다시 계산한다.
엔진 코드와 공유하는 것은 없다(설계서 DESIGN.md §7 의 해석 확정 I-번호는 '명세가 애매한 곳의 기준'으로만 참고).
명세 §12 가 최종 기준이다.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "binance"

MIN_NS = 60 * 10**9
TF_NS = {"1m": MIN_NS, "5m": 5 * MIN_NS, "15m": 15 * MIN_NS, "1h": 60 * MIN_NS, "4h": 240 * MIN_NS,
         "1d": 1440 * MIN_NS}
AVAIL_NS = 60 * 10**9                                    # RULES_SPEC §1·§12.1 봉 마감 + 60초에 판단
SWITCH_NS = pd.Timestamp("2023-10-01", tz="UTC").value   # §12.1 실행 봉 5분 → 1분 전환
SETTINGS = {"P1": ("1h", "4h", "15m"), "P2": ("4h", "1d", "1h")}   # §2 (S, D, C)

# §8.2·§12.2 비용
MAKER = 0.0002
TAKER = 0.0005
SLIP = 0.0002
FUNDING_FALLBACK = 0.0001
FUNDING_FALLBACK_FROM = pd.Timestamp("2026-09-01", tz="UTC").value


def rnd(x: float) -> float:
    """§7 공통: 0.1 USDT 반올림."""
    return float(np.round(x, 1))


# ---------------------------------------------------------------------------
# 데이터
# ---------------------------------------------------------------------------


@dataclass
class Bars:
    tf: str
    open_ns: np.ndarray
    close_ns: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    ind: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.o)


def _read(tf: str) -> pd.DataFrame:
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    if tf == "1m":
        files = sorted(DATA.glob("BTCUSDT_1m_*.csv.gz"))
        return pd.concat([pd.read_csv(f, usecols=cols) for f in files], ignore_index=True)
    return pd.read_csv(DATA / f"BTCUSDT_{tf}.csv.gz", usecols=cols)


def load_bars(tf: str) -> Bars:
    """캔들 파일 하나 → Bars (시각 = 시작 시각, 마감 = 시작 + 봉 길이, §1)."""
    df = _read(tf).sort_values("open_time", kind="stable").reset_index(drop=True)
    o_ns = df["open_time"].to_numpy(np.int64) * 1_000_000
    d = np.diff(o_ns)
    if not (d == TF_NS[tf]).all():
        raise ValueError(f"{tf}: 빈 구간 또는 중복 {int((d != TF_NS[tf]).sum())}곳")
    f = lambda k: df[k].to_numpy(np.float64, copy=True)
    return Bars(tf, o_ns, o_ns + TF_NS[tf], f("open"), f("high"), f("low"), f("close"), f("volume"))


def load_exec() -> Bars:
    """§12.1 실행 봉: 2023-10-01 전 5분봉, 이후 1분봉."""
    a, b = load_bars("5m"), load_bars("1m")
    ma, mb = a.open_ns < SWITCH_NS, b.open_ns >= SWITCH_NS
    cat = lambda x, y: np.concatenate([x[ma], y[mb]])
    ex = Bars("exec", cat(a.open_ns, b.open_ns), cat(a.close_ns, b.close_ns), cat(a.o, b.o), cat(a.h, b.h),
              cat(a.l, b.l), cat(a.c, b.c), cat(a.v, b.v))
    if not (ex.close_ns[:-1] == ex.open_ns[1:]).all():
        raise ValueError("실행 봉이 이어지지 않음")
    return ex


def load_funding(until_ns: int) -> tuple[np.ndarray, np.ndarray, int]:
    """펀딩 (시각 ns 정분 반올림, 비율). 마지막 실제 기록 뒤 2026-09-01부터 8시간 격자에 0.01% (§12.2)."""
    df = pd.read_csv(DATA / "BTCUSDT_fundingRate.csv.gz")
    t = df["calc_time"].to_numpy(np.int64) * 1_000_000
    t = ((t + MIN_NS // 2) // MIN_NS) * MIN_NS
    r = df["last_funding_rate"].to_numpy(np.float64)
    last = int(t.max())
    start = max(FUNDING_FALLBACK_FROM, last + 1)
    grid = np.arange(FUNDING_FALLBACK_FROM, until_ns + 1, 8 * 3600 * 10**9, dtype=np.int64)
    grid = grid[grid >= start]
    return np.concatenate([t, grid]), np.concatenate([r, np.full(len(grid), FUNDING_FALLBACK)]), len(grid)


# ---------------------------------------------------------------------------
# 지표 (§3). "최근 n개 평균"은 현재 봉 제외 [t−n, t−1]
# ---------------------------------------------------------------------------


def compute_indicators(b: Bars) -> dict:
    o, h, l, c, v = (pd.Series(x) for x in (b.o, b.h, b.l, b.c, b.v))
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1, skipna=False)
    tr.iloc[0] = np.nan
    atr = tr.rolling(14).mean().shift(1)                       # §3 ATR 직전 14개 TR 평균
    vol_avg = v.rolling(20).mean().shift(1)                    # §3 VR 분모
    body = (c - o).abs()
    rng = h - l
    body_avg = body.rolling(20).mean().shift(1)
    upper = ((h - np.maximum(o, c)) / rng).where(rng > 0, 0.0)
    lower = ((np.minimum(o, c) - l) / rng).where(rng > 0, 0.0)
    ma = {n: c.rolling(n).mean().shift(1) for n in (20, 60, 120)}
    mx = pd.concat(ma.values(), axis=1).max(axis=1, skipna=False)
    mn = pd.concat(ma.values(), axis=1).min(axis=1, skipna=False)
    spread = (mx - mn) / c                                     # §3 이평 확산
    spread_q80 = spread.rolling(500).quantile(0.8, interpolation="linear").shift(1)
    atr_q20 = atr.rolling(100).quantile(0.2, interpolation="linear").shift(1)
    slope = {n: np.sign(c - c.shift(n)) for n in (20, 60, 120)}
    ind = dict(tr=tr, atr=atr, vol_avg=vol_avg, vr=v / vol_avg, body=body, body_avg=body_avg,
               long_bar=(body >= 2 * body_avg) & body_avg.notna(), upper=upper, lower=lower,
               spread=spread, spread_q80=spread_q80, spread_on=(spread >= spread_q80) & spread_q80.notna(),
               atr_q20=atr_q20, surge=(rng >= 3 * atr) & atr.notna(),
               slope20=slope[20], slope60=slope[60], slope120=slope[120])
    valid = pd.Series(True, index=c.index)
    for k in ("atr", "vr", "body_avg", "spread_q80", "slope120", "atr_q20"):
        valid &= ind[k].notna()
    ind["valid"] = valid
    return {k: np.asarray(x.to_numpy(), dtype=np.float64 if x.dtype != bool else bool) for k, x in ind.items()}


def naive_quantile_prev(x: np.ndarray, t: int, n: int, q: float) -> float:
    """점검용: 직전 n개(현재 제외)의 numpy linear 분위."""
    if t - n < 0:
        return np.nan
    w = x[t - n:t]
    return np.nan if np.isnan(w).any() else float(np.quantile(w, q))


# ---------------------------------------------------------------------------
# 스윙 (§3, k=3, 엄격한 부등호, i+3 마감에 확정)
# ---------------------------------------------------------------------------


def swings(b: Bars, k: int = 3) -> dict:
    n = b.n
    is_sh = np.zeros(n, bool)
    is_sl = np.zeros(n, bool)
    for i in range(k, n - k):
        hi, lo = b.h[i], b.l[i]
        if hi > b.h[i - k:i].max() and hi > b.h[i + 1:i + k + 1].max():
            is_sh[i] = True
        if lo < b.l[i - k:i].min() and lo < b.l[i + 1:i + k + 1].min():
            is_sl[i] = True

    def last_conf(is_sw):
        last = np.full(n, -1, np.int64)
        cur = -1
        idx = set(np.flatnonzero(is_sw).tolist())
        for t in range(n):
            if (t - k) in idx:
                cur = t - k                                    # 봉 t 마감 시 스윙 t−3 확정
            last[t] = cur
        return last

    return dict(is_sh=is_sh, is_sl=is_sl, last_sh=last_conf(is_sh), last_sl=last_conf(is_sl),
                sh_idx=np.flatnonzero(is_sh), sl_idx=np.flatnonzero(is_sl))


# ---------------------------------------------------------------------------
# 기준봉 (§4.1)
# ---------------------------------------------------------------------------


def kijun_flags(b: Bars, ind: dict, sw: dict, vr_min: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    valid = ind["valid"]
    lsh, lsl = sw["last_sh"], sw["last_sl"]
    ref_hi = np.where(lsh >= 0, b.h[np.maximum(lsh, 0)], np.nan)
    ref_lo = np.where(lsl >= 0, b.l[np.maximum(lsl, 0)], np.nan)
    with np.errstate(invalid="ignore"):
        up = (valid & (b.c > b.o) & ind["long_bar"] & (ind["vr"] >= vr_min) & (ind["slope20"] > 0)
              & (ind["slope60"] > 0) & (lsh >= 0) & (b.c > ref_hi) & ~(ind["upper"] >= 0.5) & ~ind["spread_on"])
        dn = (valid & (b.c < b.o) & ind["long_bar"] & (ind["vr"] >= vr_min) & (ind["slope20"] < 0)
              & (ind["slope60"] < 0) & (lsl >= 0) & (b.c < ref_lo) & ~(ind["lower"] >= 0.5) & ~ind["spread_on"])
    return up, dn


# ---------------------------------------------------------------------------
# 허리 (§4.3)
# ---------------------------------------------------------------------------


def waist(b: Bars, a: int, bb: int, A: float, W: float, direction: int, width_mode: str = "a_end") -> tuple[float, bool]:
    """최빈 칸 허리. 칸은 A 쪽 구간 끝에서 시작, 폭 = 그 끝 가격 × 0.001 (마지막 칸은 잘림).
    동점 → 칸과 [low, high]가 겹치는 봉 거래량 합이 큰 칸 → A 쪽 칸. width_mode='mid'는 민감도용(폭 = 구간 가운데 × 0.001)."""
    if direction > 0:
        start, end = A + 0.35 * W, A + 0.65 * W                  # start = A 쪽 끝
    else:
        start, end = A - 0.35 * W, A - 0.65 * W
    width = (abs(start) if width_mode == "a_end" else abs(A + direction * 0.5 * W)) * 0.001
    span = abs(end - start)
    K = int(np.ceil(span / width - 1e-12))
    vals = np.concatenate([b.o[a:bb + 1], b.h[a:bb + 1], b.l[a:bb + 1], b.c[a:bb + 1]])
    dist = (vals - start) * direction                            # A 쪽 끝에서의 거리
    inside = (dist >= 0) & (dist <= span)
    if not inside.any():
        return rnd(A + direction * 0.5 * W), True
    kidx = np.minimum((dist[inside] // width).astype(int), K - 1)
    counts = np.bincount(kidx, minlength=K)
    best = np.flatnonzero(counts == counts.max())

    def edges(kk):
        d0, d1 = kk * width, min((kk + 1) * width, span)
        p0, p1 = start + direction * d0, start + direction * d1
        return min(p0, p1), max(p0, p1)

    if len(best) > 1:
        vols = []
        for kk in best:
            lo, hi = edges(kk)
            m = (b.l[a:bb + 1] <= hi) & (b.h[a:bb + 1] >= lo)
            vols.append(b.v[a:bb + 1][m].sum())
        vols = np.array(vols)
        best = best[vols == vols.max()]
    kk = int(best.min())                                         # A 쪽(작은 번호) 칸
    lo, hi = edges(kk)
    return rnd((lo + hi) / 2), False


# ---------------------------------------------------------------------------
# 마디 (§4.2·§4.4)
# ---------------------------------------------------------------------------


def detect_madis(b: Bars, ind: dict, sw: dict, vr_min: float = 2.0) -> pd.DataFrame:
    up, dn = kijun_flags(b, ind, sw, vr_min)
    rows = []
    n = b.n
    for direction, flags in ((1, up), (-1, dn)):
        seen = set()
        ends = sw["sh_idx"] if direction > 0 else sw["sl_idx"]
        for t in np.flatnonzero(flags):
            t = int(t)
            a = int(sw["last_sl"][t] if direction > 0 else sw["last_sh"][t])
            if a < 0:
                continue
            A = b.l[a] if direction > 0 else b.h[a]
            pos = np.searchsorted(ends, t, "left")                # B 봉 번호 ≥ t (기준봉 이후)
            if pos >= len(ends):
                continue
            bb = int(ends[pos])
            tb = bb + 3
            if tb > t + 60 or tb > n - 1:
                continue
            B = b.h[bb] if direction > 0 else b.l[bb]
            W = (B - A) * direction
            if W <= 0:
                continue
            seg = b.c[a:tb + 1]
            if (direction > 0 and (seg < A).any()) or (direction < 0 and (seg > A).any()):
                continue
            if a < 20 or b.v[a:bb + 1].mean() < b.v[a - 20:a].mean():
                continue
            if bb in seen:
                continue
            seen.add(bb)
            H, fb = waist(b, a, bb, A, W, direction)
            Hm = rnd(A + direction * 0.5 * W)
            after = b.c[tb + 1:]
            death = np.flatnonzero(after < A if direction > 0 else after > A)
            death_idx = tb + 1 + int(death[0]) if len(death) else n
            end_idx = min(death_idx - 1, tb + 300, n - 1)
            prev_b = sw["sh_idx"] if direction > 0 else sw["sl_idx"]
            # 애매함 점검: 기준봉 직전(t−2, t−1) 스윙이 기준봉 뒤에 확정되는가
            early = [int(i) for i in prev_b if t - 2 <= i <= t - 1]
            rows.append(dict(direction=direction, kijun=t, a=a, b=bb, tb=tb, A=float(A), B=float(B), W=float(W),
                             H=H, H_mid=Hm, fallback=fb, vol_ab=float(b.v[a:bb + 1].mean()), death=death_idx,
                             end=end_idx, tb_close_ns=int(b.close_ns[tb]),
                             madi_id=f"{b.tf}{'U' if direction > 0 else 'D'}-"
                                     f"{pd.Timestamp(int(b.open_ns[bb]), tz='UTC').strftime('%Y%m%d%H%M')}",
                             early_swing_before_b=early))
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["tb", "kijun"], kind="stable").reset_index(drop=True)
    return df


def most_recent_alive(madis: pd.DataFrame, t: int, direction: int, strict: bool = False) -> int:
    """봉 t에서 살아 있는 같은 방향 마디 중 tb가 가장 큰 행 번호(없으면 −1). strict면 tb < t."""
    if not len(madis):
        return -1
    m = madis[(madis.direction == direction) & (madis.tb <= t) & (t <= madis.end)]
    if strict:
        m = m[m.tb < t]
    return -1 if not len(m) else int(m.index[-1])


# ---------------------------------------------------------------------------
# 필터 (§6)
# ---------------------------------------------------------------------------


def trap_completions(b: Bars, sw: dict) -> np.ndarray:
    """F6 트랩 완성 봉 번호 목록(지지 + 저항). 기준 = j−1 시점 확정 스윙, 이탈 = 종가가 기준을 넘어가는 봉,
    이탈 뒤 5봉 안 첫 복귀 봉 = 완성."""
    out = []
    n = b.n
    for side in (1, -1):
        last = sw["last_sl"] if side > 0 else sw["last_sh"]
        lev_arr = b.l if side > 0 else b.h
        for j in range(1, n):
            r = last[j - 1]
            if r < 0:
                continue
            L = lev_arr[r]
            if side > 0:
                brk = b.c[j] < L and b.c[j - 1] >= L
            else:
                brk = b.c[j] > L and b.c[j - 1] <= L
            if not brk:
                continue
            seg = b.c[j + 1:j + 6]
            back = np.flatnonzero(seg > L if side > 0 else seg < L)
            if len(back):
                out.append(j + 1 + int(back[0]))
    return np.sort(np.array(out, dtype=np.int64))


# ---------------------------------------------------------------------------
# 체결·청산 (§8.2·§12.1·§12.2)
# ---------------------------------------------------------------------------


@dataclass
class Sim:
    status: str
    entry_j: int = -1
    entry_price: float = np.nan
    exit_j: int = -1
    exit_price: float = np.nan
    exit_reason: str = ""
    fees: float = np.nan
    slippage: float = np.nan
    funding: float = np.nan
    funding_paid: float = 0.0
    funding_recv: float = 0.0
    gross: float = np.nan
    net: float = np.nan
    r: float = np.nan
    r_cost2: float = np.nan
    risk: float = np.nan
    busy_until: int = 0
    n_funding: int = 0


def funding_cost(X: Bars, F_ns, F_rate, side: int, start_ns: int, end_ns: int) -> tuple[float, float, int]:
    """start < f ≤ end 인 펀딩마다 side × 비율 × (f 를 포함하는 실행 봉 시가). (지불 합, 수취 합(음수), 개수)."""
    m = (F_ns > start_ns) & (F_ns <= end_ns)
    paid = recv = 0.0
    for f, r in zip(F_ns[m], F_rate[m]):
        j = int(np.searchsorted(X.open_ns, f, "right") - 1)
        x = side * r * X.o[j]
        if x > 0:
            paid += x
        else:
            recv += x
    return paid, recv, int(m.sum())


def simulate(X: Bars, F_ns, F_rate, side: int, order_type: str, entry: float, stop: float, target: float,
             active_from: int, order_end: int, cancelled_if_unfilled: bool, max_hold_ns: int,
             funding_start_mode: str = "engine") -> Sim:
    """계획 하나를 실행 봉으로 시뮬레이션. order_type ∈ limit / ioc_cap / market."""
    n = X.n
    j0 = int(np.searchsorted(X.open_ns, active_from, "left"))   # 활성 시각 이후 시작하는 첫 실행 봉
    if j0 >= n:
        return Sim("not_filled", busy_until=active_from)
    if order_type == "limit":
        j1 = int(np.searchsorted(X.close_ns, order_end, "right"))  # 봉 끝 ≤ 주문 끝
        seg = X.l[j0:j1] < entry if side > 0 else X.h[j0:j1] > entry  # §12.1 관통
        hit = np.flatnonzero(seg)
        if not len(hit):
            return Sim("cancelled" if cancelled_if_unfilled else "expired", busy_until=order_end)
        je, px, fee_in = j0 + int(hit[0]), entry, MAKER
    elif order_type == "ioc_cap":
        if (side > 0 and X.o[j0] <= entry) or (side < 0 and X.o[j0] >= entry):
            je, px, fee_in = j0, float(X.o[j0]), TAKER
        else:
            return Sim("not_filled", busy_until=int(X.close_ns[j0]))
    else:  # market
        je, px, fee_in = j0, float(X.o[j0]), TAKER
    t_limit = int(X.open_ns[je]) + max_hold_ns
    jt = int(np.searchsorted(X.open_ns, t_limit, "left"))       # 시간 청산 봉
    jt = max(jt, je + 1)
    seg = slice(je, min(jt, n))
    if side > 0:
        s_hit = X.l[seg] <= stop
        t_hit = X.h[seg] > target
    else:
        s_hit = X.h[seg] >= stop
        t_hit = X.l[seg] < target
    t_hit = t_hit.copy()
    t_hit[0] = False                                           # §12.1 목표는 다음 실행 봉부터
    ks = np.flatnonzero(s_hit)
    kt = np.flatnonzero(t_hit)
    k_s = int(ks[0]) if len(ks) else 10**12
    k_t = int(kt[0]) if len(kt) else 10**12
    if k_s <= k_t and len(ks):                                 # 같은 봉이면 손절 먼저
        jx = je + k_s
        gap_ok = jx > je or order_type != "limit"
        op = X.o[jx]
        beyond = (op <= stop) if side > 0 else (op >= stop)
        xp = float(op) if (gap_ok and beyond) else stop
        reason, fee_out, slip_rate = "stop", TAKER, SLIP
    elif len(kt):
        jx = je + k_t
        xp, reason, fee_out, slip_rate = target, "target", MAKER, 0.0
    elif jt < n:
        jx = jt
        xp, reason, fee_out, slip_rate = float(X.o[jt]), "time", TAKER, SLIP
    else:
        jx = n - 1
        xp, reason, fee_out, slip_rate = float(X.c[n - 1]), "eod", TAKER, SLIP
    fees = fee_in * px + fee_out * xp
    slip = slip_rate * xp
    if order_type == "limit":
        f_start = int(X.open_ns[je])
    else:
        f_start = int(X.open_ns[je]) if funding_start_mode == "spec" else min(int(X.open_ns[je]), active_from)
    paid, recv, nf = funding_cost(X, F_ns, F_rate, side, f_start, int(X.open_ns[jx]))
    gross = side * (xp - px)
    net = gross - fees - slip - (paid + recv)
    risk = abs(px - stop) + fee_in * px + (TAKER + SLIP) * stop    # §12.2 d + c_stop (실제 진입가)
    net2 = gross - 2 * fees - 2 * slip - (2 * paid + recv)
    return Sim("filled", je, px, jx, xp, reason, fees, slip, paid + recv, paid, recv, gross, net, net / risk,
               net2 / risk, risk, int(X.close_ns[jx]), nf)


# ---------------------------------------------------------------------------
# 시각 도우미
# ---------------------------------------------------------------------------


def iso_ns(s: str) -> int:
    return pd.Timestamp(s).as_unit("ns").value


def ns_iso(ns: int) -> str:
    return pd.Timestamp(int(ns), tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def asof(close_ns: np.ndarray, t_ns: int) -> int:
    """close + 60초 ≤ t 인 마지막 봉 번호(없으면 −1). §1 상위 봉은 마감된 것만."""
    return int(np.searchsorted(close_ns + AVAIL_NS, t_ns, "right") - 1)


def kst_minute(ns: int) -> int:
    t = pd.Timestamp(int(ns), tz="UTC").tz_convert("Asia/Seoul")
    return t.hour * 60 + t.minute


def kst_day(ns: int) -> str:
    return pd.Timestamp(int(ns), tz="UTC").tz_convert("Asia/Seoul").strftime("%Y-%m-%d")


def in_dnd(ns: int) -> bool:
    m = kst_minute(ns)
    return 30 <= m < 7 * 60 + 30                                # §12.3 KST [00:30, 07:30)
