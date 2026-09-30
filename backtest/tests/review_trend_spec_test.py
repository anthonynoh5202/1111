"""적대적 검토: 명세 일치 감사 — TREND_SPEC v1.0 §1~§5 문장 ↔ 코드 1:1 대조 (검토자 전용, 제품 코드는 고치지 않는다).

기준: docs/TREND_SPEC.md v1.0. 따로 적지 않은 체결·비용·통계는 RULES_SPEC §12 / backtest/DESIGN.md.

구성
A. test_spec_*   : 명세 숫자·목록(M 반올림, 8개 조합, 민감도 4종, 7개 기준 경계)을 손으로 다시 적어 코드와 대조.
B. test_ref_*    : 명세 문장에서 따로 짠 참조 상태 기계(_ref_run, backtest.trend 안 씀) vs 제품 — 실데이터 전수(@slow).
                   E0·E1 × 롱숏·롱만 × N20·55·100 + 민감도(지연 10·120분, 손절 3 × ATR). 거래 목록·가격·사유·R이 모두 같아야 한다.
C. test_hand_*   : 실데이터 거래 3건을 원본 CSV(backtest.data 안 씀)에서 명세대로 한 줄씩 따라가 손으로 확인.
                   손으로 읽은 값(진입가·손절가·청산 시각·청산가)은 숫자로 박아 둔다.
D. test_random_* : 무작위 기준선 표(일봉 d 진입 결과)를 참조 구현으로 표본 확인 + 독립 추출로 p95 재현.
E. test_trunc_*  : 실데이터를 잘라도 자른 시각 전의 거래가 그대로(미래 참조 없음).
F. test_run_*    : run_g1t 산출물 구조(8조합·민감도 32개·E1 vs E0 4쌍·우선순위·오염 고지).
G. xfail(strict) : 발견한 결함. 고치면 XPASS → strict 실패로 알려 준다.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import metrics as M
from backtest import trend as TR
from backtest.types import ExecArrays

DATA = Path(__file__).resolve().parents[2] / "data" / "binance"
HAVE_DATA = (DATA / "BTCUSDT_1d.csv.gz").exists() and (DATA / "BTCUSDT_5m.csv.gz").exists() \
    and (DATA / "BTCUSDT_1m_2024.csv.gz").exists()
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="실데이터 없음 (data/binance)")

# 명세 값 (손으로 다시 적음)
MAKER, TAKER, SLIP = 0.0002, 0.0005, 0.0002
NS_MIN = 60 * 10**9
NS_DAY = 86_400 * 10**9
MS_MIN, MS_DAY = 60_000, 86_400_000
SWITCH_MS = 1_696_118_400_000        # 2023-10-01 00:00 UTC (실행 봉 5분 → 1분)


# ===========================================================================
# A. 명세 숫자·목록
# ===========================================================================


def test_spec_exit_period_rounding():
    """§1: M = N/2 반올림 20→10, 55→28, 100→50."""
    assert [TR.exit_period(n) for n in (20, 55, 100)] == [10, 28, 50]
    assert TR.PERIODS == (20, 55, 100) and TR.SINGLE_PERIOD == 55


def test_spec_execution_numbers():
    """§2: L = 30분(민감도 10·120), 손절 2 × ATR20(민감도 3), E1 유효 5일, E0 테이커+슬리피지, E1 메이커."""
    assert TR.LATENCY_MIN == 30 and TR.LATENCY_SENSITIVITY == (10, 120)
    assert TR.STOP_ATR_MULT == 2.0 and TR.STOP_ATR_SENSITIVITY == 3.0 and TR.ATR_N == 20
    assert TR.E1_VALID_DAYS == 5
    e0, e1 = TR.TrendConfig("E0", "LS"), TR.TrendConfig("E1", "LS")
    assert (e0.entry_rate, e0.entry_slip_rate) == (TAKER, SLIP)
    assert (e1.entry_rate, e1.entry_slip_rate) == (MAKER, 0.0)
    assert C.AVAIL_DELAY_NS == 60 * 10**9                     # §1 판단 = 마감 + 60초
    assert TR.RISK_R == 0.005 and TR.NOTIONAL_CAP_PER_SYSTEM == 0.2   # §3


def test_spec_eight_combos_and_sensitivity():
    """§4: 진입 2 × 방향 2 × 하위 시스템 2 = 8, 민감도 = 지연 10·120분, 손절 3 × ATR, 비용 2배."""
    keys = [c.key for c in TR.trend_combos()]
    expect = {f"{e}-{d}-{s}" for e in ("E0", "E1") for d in ("LS", "L") for s in ("ENS", "N55")}
    assert len(keys) == 8 and set(keys) == expect
    for c in TR.trend_combos():
        assert c.periods in ((20, 55, 100), (55,))
        assert c.allow_short == (c.direction == "LS")
    v = dict(TR.SENSITIVITY_VARIANTS)
    assert v == {"lat10": {"latency_min": 10}, "lat120": {"latency_min": 120},
                 "stop3": {"stop_atr_mult": 3.0}, "cost2": {"cost_multiplier": 2.0}}


def test_spec_g1_criteria_boundaries():
    """§5 = RULES §8.3: 평균 R ≥ 0.15, 하한 > 0, PF ≥ 1.2, 비용 2배 > 0, 무작위 p95 초과, 7개 연도 중 ≥ 4, 거래 ≥ 30."""
    assert C.G1_MIN_MEAN_R == 0.15 and C.G1_MIN_PF == 1.2 and C.G1_MIN_TRADES == 30
    assert C.G1_MIN_POSITIVE_YEARS == 4 and len(C.G1_YEARS) == 7
    assert C.RANDOM_REPS == 1000 and C.BOOTSTRAP_N == 10_000 and C.G1_RANDOM_QUANTILE == 0.95
    base = dict(mean_r=0.15, boot_lo=1e-9, pf=1.2, positive_years=4, n=30)
    assert M.g1_verdict(base, 1e-9, 0.1499)["result"] == "pass"
    assert M.g1_verdict(base, 1e-9, 0.15)["result"] == "fail"             # 초과(>)여야
    assert M.g1_verdict(base | dict(n=29), 1e-9, 0.0)["result"] == "pending"
    assert M.g1_verdict(base | dict(boot_lo=0.0), 1e-9, 0.0)["result"] == "fail"
    assert M.g1_verdict(base, 0.0, 0.0)["result"] == "fail"


def test_spec_priority_order():
    """§5 단순한 것 우선: 단독 < 앙상블, 롱만 < 롱·숏, E0 < E1 · 최대 낙폭 30% 초과 후순위 · E1은 구간 하한 > 0일 때만."""
    from backtest.run_g1t import selection

    def blk(res, mdd):
        return {"verdict": {"result": res}, "equity": {"risk": {"max_drawdown": mdd}}}

    blocks = {"E0-LS-ENS": blk("pass", 0.1), "E0-L-N55": blk("pass", 0.31), "E0-L-ENS": blk("pass", 0.2),
              "E1-L-N55": blk("pass", 0.05), "E0-LS-N55": blk("pass", 0.1)}
    s = selection(blocks, [{"e1": "E1-L-N55", "e1_better": False}])
    assert s["ranked"] == ["E0-LS-N55", "E0-L-ENS", "E0-LS-ENS", "E0-L-N55"]
    assert "E1-L-N55" not in s["ranked"]
    s2 = selection(blocks, [{"e1": "E1-L-N55", "e1_better": True}])
    assert s2["ranked"][0] == "E1-L-N55"          # 단독·롱만이라 가장 단순 (E1 < E0 축보다 앞선 축)


def test_spec_e1_random_threshold_is_conservative():
    """T-8: E1 조합의 c5 기준 = max(시장가 p95, 메이커 p95)."""
    tb = TR.RandomTable(n=55, side=1, days=np.arange(40), months=np.repeat([24300, 24301], 20),
                        filled=np.ones(40, bool), r=np.linspace(-1, 1, 40), r_maker=np.linspace(-1, 1, 40) + 0.5)
    from backtest.types import Status, TradeResult
    trades = [TradeResult(plan_id="x", scenario="N55", side=1, order_type="limit", signal_time=0, approval_time=0,
                          active_from=0, target=math.inf, madi_id=None, status=Status.FILLED, busy_until=0,
                          plan_entry=1.0, stop=0.5, risk_per_unit=0.5, entry_time=int(C.ts_ns("2025-01-15")),
                          entry_price=1.0, exit_time=int(C.ts_ns("2025-01-20")), exit_price=1.0, r_multiple=0.0,
                          meta={"n": 55})]
    m0 = int(TR._month_index(C.ts_ns("2025-01-15")))
    tb.months = np.repeat([m0, m0 + 1], 20)
    rb1 = TR.run_trend_random_baseline(trades, {(55, 1): tb}, TR.TrendConfig("E1", "L", (55,)), n_reps=200)
    rb0 = TR.run_trend_random_baseline(trades, {(55, 1): tb}, TR.TrendConfig("E0", "L", (55,)), n_reps=200)
    assert rb1["threshold"] == max(rb1["p95"], rb1["maker"]["p95"]) and rb1["threshold"] > rb1["p95"]
    assert rb0["threshold"] == rb0["p95"]


# ===========================================================================
# 실데이터 공용
# ===========================================================================


@pytest.fixture(scope="module")
def real():
    if not HAVE_DATA:
        pytest.skip("실데이터 없음")
    from backtest import data as D
    mk = D.load_market(tfs=("1d",), with_events=False)
    daily = mk.bars["1d"]
    return dict(mk=mk, daily=daily, dd=TR.DailyData.from_frame(daily), xb=mk.exec_arrays(), fa=mk.funding_arrays())


# ===========================================================================
# B. 참조 상태 기계 (명세 문장 그대로, backtest.trend 안 씀)
# ===========================================================================


def _rnd(x):
    return float(np.round(x, 1))


def _ref_ind(daily):
    c = daily["close"].to_numpy(float)
    h = daily["high"].to_numpy(float)
    lo = daily["low"].to_numpy(float)
    n = len(c)
    tr = np.full(n, np.nan)
    for i in range(1, n):
        tr[i] = max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
    atr = np.full(n, np.nan)
    for t in range(21, n):
        atr[t] = tr[t - 20:t].mean()       # RULES §3: 직전 20개 TR 평균(현재 제외)
    return c, atr


def _ref_chan(c, n):
    up = np.full(len(c), np.nan)
    dn = np.full(len(c), np.nan)
    for t in range(n, len(c)):
        up[t] = c[t - n:t].max()
        dn[t] = c[t - n:t].min()
    return up, dn


def _ref_funding(side, t0, t1, xb, fa):
    k0 = np.searchsorted(fa.time_ns, t0, "right")
    k1 = np.searchsorted(fa.time_ns, t1, "right")
    tot = 0.0
    for k in range(k0, k1):
        j = np.searchsorted(xb.open_ns, fa.time_ns[k], "right") - 1
        x = side * fa.rate[k] * xb.open[j]
        tot += x
    return tot


def _ref_scan_stop(side, j0, jend, stop, open_fill, xb):
    seg = xb.low[j0:jend] <= stop if side > 0 else xb.high[j0:jend] >= stop
    if not seg.any():
        return None
    j = j0 + int(np.argmax(seg))
    p = stop
    if j > j0 or open_fill:
        o = xb.open[j]
        p = min(p, o) if side > 0 else max(p, o)
    return j, p


def _ref_run(daily, xb, fa, n, entry="E0", allow_short=True, lat=30, k_atr=2.0):
    """하위 시스템 하나: 매 일봉 판단 시각에 (대기 주문 → 보유 포지션 → 진입) 순서로 상태를 갱신한다."""
    c, atr = _ref_ind(daily)
    close_ns = daily["close_ns"].to_numpy(np.int64)
    dec = close_ns + 60 * 10**9
    m = int(math.floor(n / 2 + 0.5))
    up, dn = _ref_chan(c, n)
    uhi, dlo = _ref_chan(c, m)
    nx = len(xb.open_ns)
    valid = ~(np.isnan(up) | np.isnan(uhi) | np.isnan(atr))
    out, pos, pend = [], None, None

    def close_pos(p, j, price, reason):
        side, e = p["side"], p["entry"]
        fees = (TAKER if p["mkt"] else MAKER) * e + TAKER * price
        slip = SLIP * price + (SLIP * e if p["mkt"] else 0.0)
        f0 = min(int(xb.open_ns[p["j"]]), p["active"]) if p["mkt"] else int(xb.open_ns[p["j"]])
        fund = _ref_funding(side, f0, int(xb.open_ns[j]), xb, fa)
        net = side * (price - e) - fees - slip - fund
        out.append(dict(side=side, entry_time=int(xb.open_ns[p["j"]]), entry=e, stop=p["stop"],
                        exit_time=int(xb.open_ns[j]), exit=price, reason=reason, r=net / p["risk"]))

    for d in range(len(c)):
        if not valid[d]:
            continue
        if pend is not None:                                   # E1 대기 주문
            ps = pend["side"]
            exit_now = (c[d] < dlo[d]) if ps > 0 else (c[d] > uhi[d])
            end = pend["valid_until"]
            if exit_now and dec[d] < end:
                end = int(dec[d])                              # 청산 신호 → 판단 시각부터 취소
            upto = min(end, int(dec[d]))
            j0 = pend["j0"]
            j1 = int(np.searchsorted(xb.close_ns, upto, "right"))
            fill = None
            if j1 > j0:
                seg = xb.low[j0:j1] < pend["limit"] if ps > 0 else xb.high[j0:j1] > pend["limit"]
                if seg.any():
                    fill = j0 + int(np.argmax(seg))
                pend["j0"] = j1
            if fill is not None:
                e = pend["limit"]
                stop = _rnd(e - ps * pend["dist"])
                pos = dict(side=ps, j=fill, entry=e, stop=stop, mkt=False, active=pend["active"],
                           risk=abs(e - stop) + MAKER * e + (TAKER + SLIP) * stop)
                pend = None
            elif upto >= end:
                pend = None
            else:
                continue                                       # 아직 대기: 새 신호 없음
        if pos is not None:                                    # 보유 포지션
            side = pos["side"]
            exit_sig = (c[d] < dlo[d]) if side > 0 else (c[d] > uhi[d])
            if exit_sig:
                jt = max(int(np.searchsorted(xb.open_ns, dec[d] + lat * NS_MIN, "left")), pos["j"] + 1)
                s = _ref_scan_stop(side, pos["j"], min(jt, nx), pos["stop"], pos["mkt"], xb)
                if s is not None:
                    close_pos(pos, s[0], s[1], "stop")
                elif jt < nx:
                    close_pos(pos, jt, float(xb.open[jt]), "trend")
                else:
                    close_pos(pos, nx - 1, float(xb.close[nx - 1]), "eod")
                pos = None
            else:
                jcap = int(np.searchsorted(xb.close_ns, dec[d], "right"))
                s = _ref_scan_stop(side, pos["j"], min(jcap, nx), pos["stop"], pos["mkt"], xb)
                if s is None:
                    continue
                close_pos(pos, s[0], s[1], "stop")
                pos = None
        side = 1 if c[d] > up[d] else (-1 if (c[d] < dn[d] and allow_short) else 0)
        if side == 0:
            continue
        active = int(dec[d]) + lat * NS_MIN
        j0 = int(np.searchsorted(xb.open_ns, active, "left"))
        if j0 >= nx:
            break
        dist = k_atr * atr[d]
        if entry == "E0":
            e = float(xb.open[j0])
            stop = _rnd(e - side * dist)
            pos = dict(side=side, j=j0, entry=e, stop=stop, mkt=True, active=active,
                       risk=abs(e - stop) + TAKER * e + (TAKER + SLIP) * stop + SLIP * e)
        else:
            pend = dict(side=side, limit=_rnd(up[d] if side > 0 else dn[d]), active=active, j0=j0,
                        valid_until=int(close_ns[d]) + 5 * NS_DAY, dist=dist)
    if pos is not None:
        s = _ref_scan_stop(pos["side"], pos["j"], nx, pos["stop"], pos["mkt"], xb)
        if s is not None:
            close_pos(pos, s[0], s[1], "stop")
        else:
            close_pos(pos, nx - 1, float(xb.close[nx - 1]), "eod")
    return out


REF_CASES = [(e, d, n, {}) for e in ("E0", "E1") for d in ("LS", "L") for n in (20, 55, 100)] + [
    ("E0", "LS", 55, dict(latency_min=120)), ("E1", "LS", 20, dict(latency_min=10)),
    ("E0", "LS", 20, dict(stop_atr_mult=3.0)), ("E1", "LS", 55, dict(stop_atr_mult=3.0))]


@needs_data
@pytest.mark.slow
@pytest.mark.parametrize("entry,direction,n,kw", REF_CASES, ids=lambda x: str(x))
def test_ref_subsystem_matches_spec_state_machine(real, entry, direction, n, kw):
    cfg = TR.TrendConfig(entry, direction, (n,), **kw)
    got = TR.filled(TR.run_subsystem(real["dd"], n, cfg, real["xb"], real["fa"])[0])
    ref = _ref_run(real["daily"], real["xb"], real["fa"], n, entry=entry, allow_short=(direction == "LS"),
                   lat=kw.get("latency_min", 30), k_atr=kw.get("stop_atr_mult", 2.0))
    assert len(got) == len(ref) > 10
    for a, b in zip(got, ref):
        assert (a.side, a.entry_time, a.exit_time, a.exit_reason) == (b["side"], b["entry_time"], b["exit_time"],
                                                                        b["reason"]), a.plan_id
        assert a.entry_price == pytest.approx(b["entry"], abs=1e-9)
        assert a.stop == pytest.approx(b["stop"], abs=1e-9)
        assert a.exit_price == pytest.approx(b["exit"], abs=1e-9)
        assert a.r_multiple == pytest.approx(b["r"], abs=1e-9), a.plan_id


@needs_data
@pytest.mark.slow
def test_ref_ensemble_is_union_of_subsystems(real):
    """§4: 조합 R 통계 = 조합 안 모든 하위 시스템 거래를 합친 것."""
    for cfg in TR.trend_combos():
        tr = TR.filled(TR.run_trend_combo(real["dd"], cfg, real["xb"], real["fa"])[0])
        parts = [TR.filled(TR.run_subsystem(real["dd"], n, cfg, real["xb"], real["fa"])[0]) for n in cfg.periods]
        assert sorted(t.r_multiple for t in tr) == sorted(t.r_multiple for p in parts for t in p)
        assert len({t.meta["n"] for t in tr}) == len(cfg.periods)


# ===========================================================================
# C. 손 추적 — 원본 CSV에서 (backtest.data 안 씀)
# ===========================================================================


class _Raw:
    _cache: dict = {}

    @classmethod
    def daily(cls):
        if "1d" not in cls._cache:
            cls._cache["1d"] = pd.read_csv(DATA / "BTCUSDT_1d.csv.gz", usecols=range(6), float_precision="round_trip")
        return cls._cache["1d"]

    @classmethod
    def exec_bars(cls, year):
        if year not in cls._cache:
            if year < 2023:
                f = pd.read_csv(DATA / "BTCUSDT_5m.csv.gz", usecols=range(6), float_precision="round_trip")
                f = f[f.open_time < SWITCH_MS]
            else:
                f = pd.read_csv(DATA / f"BTCUSDT_1m_{year}.csv.gz", usecols=range(6), float_precision="round_trip")
            cls._cache[year] = f.sort_values("open_time", ignore_index=True)
        return cls._cache[year]

    @classmethod
    def funding(cls):
        if "f" not in cls._cache:
            f = pd.read_csv(DATA / "BTCUSDT_fundingRate.csv.gz")
            cls._cache["f"] = f.assign(t=(f.calc_time // 3_600_000) * 3_600_000)
        return cls._cache["f"]


def _hand(signal_open, n, side, entry_kind, year):
    """신호 일봉(open_time = signal_open, UTC 날짜)의 거래를 명세 문장대로 손 계산."""
    d = _Raw.daily()
    c, h, lo = d.close.to_numpy(), d.high.to_numpy(), d.low.to_numpy()
    t = int(np.flatnonzero(d.open_time.to_numpy() == int(pd.Timestamp(signal_open, tz="UTC").value // 10**6))[0])
    m = int(math.floor(n / 2 + 0.5))
    up, dn = c[t - n:t].max(), c[t - n:t].min()                      # §1 직전 N개 종가
    assert (c[t] > up) if side > 0 else (c[t] < dn)
    trs = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(t - 20, t)]
    atr = float(np.mean(trs))                                        # §2 ATR20 (RULES §3)
    close_ms = int(d.open_time[t]) + MS_DAY
    active = close_ms + MS_MIN + 30 * MS_MIN                         # 마감 + 60초 + L
    x = _Raw.exec_bars(year)
    ot, o, xh, xl, xc = (x[k].to_numpy() for k in ("open_time", "open", "high", "low", "close"))
    dur = 5 * MS_MIN if year < 2023 else MS_MIN
    j = int(np.searchsorted(ot, active))
    if entry_kind == "E0":
        e, je = float(o[j]), j
    else:
        limit = _rnd(up if side > 0 else dn)
        valid_until = close_ms + 5 * MS_DAY
        je = j
        while ot[je] + dur <= valid_until and not ((xl[je] < limit) if side > 0 else (xh[je] > limit)):
            je += 1
        assert ot[je] + dur <= valid_until
        e = limit
    stop = _rnd(e - side * 2 * atr)
    k = t + 1                                                        # 첫 청산 신호 봉
    while not ((c[k] < c[k - m:k].min()) if side > 0 else (c[k] > c[k - m:k].max())):
        k += 1
    t_lim = int(d.open_time[k]) + MS_DAY + MS_MIN + 30 * MS_MIN
    jj, reason, px = je, None, None
    while ot[jj] < t_lim or jj == je:
        if (xl[jj] <= stop) if side > 0 else (xh[jj] >= stop):
            px = stop
            if jj > je or entry_kind == "E0":
                px = min(stop, o[jj]) if side > 0 else max(stop, o[jj])
            reason = "stop"
            break
        jj += 1
    if reason is None:
        reason, px = "trend", float(o[jj])
    ent_rate = TAKER if entry_kind == "E0" else MAKER
    fees = ent_rate * e + TAKER * px
    slip = SLIP * px + (SLIP * e if entry_kind == "E0" else 0.0)
    f = _Raw.funding()
    f0 = min(int(ot[je]), active) if entry_kind == "E0" else int(ot[je])
    sel = f[(f.t > f0) & (f.t <= int(ot[jj]))]
    fund = 0.0
    for tf, rate in zip(sel.t, sel.last_funding_rate):
        fund += side * rate * float(o[int(np.searchsorted(ot, tf, "right")) - 1])
    risk = abs(e - stop) + ent_rate * e + (TAKER + SLIP) * stop + (SLIP * e if entry_kind == "E0" else 0.0)
    r = (side * (px - e) - fees - slip - fund) / risk
    iso = lambda ms: pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M")  # noqa: E731
    return dict(up=up, dn=dn, atr=atr, entry=e, entry_time=iso(ot[je]), stop=stop, exit_day=iso(d.open_time[k]),
                exit_time=iso(ot[jj]), exit=float(px), reason=reason, funding=fund, r=r)


def _engine_trade(real, cfg, plan_id):
    tr = TR.run_trend_combo(real["dd"], cfg, real["xb"], real["fa"])[0]
    return next(t for t in tr if t.plan_id == plan_id)


@needs_data
@pytest.mark.slow
def test_hand_e0_n20_long_trend_exit_2020(real):
    """E0 N20 롱: 2020-01-28 봉 종가 9398.98 > U_20 → 01-29 00:35(5분봉, 활성 00:31 뒤 첫 봉) 시가 진입.
    02-17 봉 종가 9716 < D_10 = 9821.52 → 02-18 00:35 시가 9666.0에 추세 청산. 손절 8651.2는 안 닿음.
    2020년 2월 펀딩이 높아(합 ≈ 4%) 가격 이익(+291)에도 R은 음수."""
    h = _hand("2020-01-28", 20, 1, "E0", 2020)
    assert h["entry_time"] == "2020-01-29T00:35" and h["entry"] == 9375.01 and h["stop"] == 8651.2
    assert h["exit_day"].startswith("2020-02-17") and h["exit_time"] == "2020-02-18T00:35"
    assert h["exit"] == 9666.0 and h["reason"] == "trend"
    t = _engine_trade(real, TR.TrendConfig("E0", "LS"), "E0-LS-ENS_N20_2020-01-29_L")
    assert (t.entry_price, t.stop, t.exit_price, t.exit_reason) == (9375.01, 8651.2, 9666.0, "trend")
    assert t.funding == pytest.approx(h["funding"], rel=1e-9)
    assert t.r_multiple == pytest.approx(h["r"], abs=1e-9) and t.r_multiple < 0


@needs_data
@pytest.mark.slow
def test_hand_e0_n55_long_stop_2020(real):
    """E0 N55 롱 2020-08-10 봉 신호 → 08-11 00:35 시가 11888.41, 손절 10789.3(2 × ATR20 = 1099.1) → 09-03 12:25 손절."""
    h = _hand("2020-08-10", 55, 1, "E0", 2020)
    assert h["entry_time"] == "2020-08-11T00:35" and h["entry"] == 11888.41 and h["stop"] == 10789.3
    assert h["reason"] == "stop" and h["exit_time"] == "2020-09-03T12:25" and h["exit"] == 10789.3
    t = _engine_trade(real, TR.TrendConfig("E0", "LS", (55,)), "E0-LS-N55_N55_2020-08-11_L")
    assert (t.entry_price, t.stop, t.exit_price, t.exit_reason) == (11888.41, 10789.3, 10789.3, "stop")
    assert t.r_multiple == pytest.approx(h["r"], abs=1e-9)
    assert t.r_multiple < -1.0                                        # 펀딩 지불로 −1R보다 나쁨(정상)


@needs_data
@pytest.mark.slow
def test_hand_e1_n55_long_limit_fill_2024(real):
    """E1 N55 롱 2024-02-09 봉 신호: 지정가 = U_55 = 46972.7(0.1 반올림) → 02-10 10:48 1분봉 저가 < 지정가 관통 체결.
    손절 = 46972.7 − 2 × ATR20 = 44547.2, 04-17 봉 청산 신호 → 04-18 00:31 시가 61039.8 추세 청산."""
    h = _hand("2024-02-09", 55, 1, "E1", 2024)
    assert h["entry"] == 46972.7 and h["entry_time"] == "2024-02-10T10:48" and h["stop"] == 44547.2
    assert h["reason"] == "trend" and h["exit_time"] == "2024-04-18T00:31" and h["exit"] == 61039.8
    t = _engine_trade(real, TR.TrendConfig("E1", "LS", (55,)), "E1-LS-N55_N55_2024-02-10_L")
    assert (t.entry_price, t.stop, t.exit_price, t.exit_reason) == (46972.7, 44547.2, 61039.8, "trend")
    assert t.order_type == "limit" and t.slippage == pytest.approx(SLIP * 61039.8)   # 진입 슬리피지 없음
    assert t.r_multiple == pytest.approx(h["r"], abs=1e-9)


# ===========================================================================
# D. 무작위 기준선 (§5)
# ===========================================================================


def _ref_random_trade(daily, xb, fa, n, side, d):
    c, atr = _ref_ind(daily)
    close_ns = daily["close_ns"].to_numpy(np.int64)
    m = int(math.floor(n / 2 + 0.5))
    uhi, dlo = _ref_chan(c, m)
    active = int(close_ns[d]) + 60 * 10**9 + 30 * NS_MIN
    j0 = int(np.searchsorted(xb.open_ns, active))
    e = float(xb.open[j0])
    stop = _rnd(e - side * 2 * atr[d])
    risk = abs(e - stop) + TAKER * e + (TAKER + SLIP) * stop + SLIP * e
    ex = np.flatnonzero((c < dlo) if side > 0 else (c > uhi))
    ex = ex[ex > d]
    nx = len(xb.open_ns)
    jt = max(int(np.searchsorted(xb.open_ns, close_ns[ex[0]] + 60 * 10**9 + 30 * NS_MIN)), j0 + 1) if ex.size else nx
    s = _ref_scan_stop(side, j0, min(jt, nx), stop, True, xb)
    if s:
        j, p = s
    elif jt < nx:
        j, p = jt, float(xb.open[jt])
    else:
        j, p = nx - 1, float(xb.close[nx - 1])
    fund = _ref_funding(side, min(int(xb.open_ns[j0]), active), int(xb.open_ns[j]), xb, fa)
    return (side * (p - e) - TAKER * (e + p) - SLIP * (p + e) - fund) / risk


@needs_data
@pytest.mark.slow
@pytest.mark.parametrize("n,side", [(55, 1), (20, -1), (100, 1)])
def test_random_table_matches_reference(real, n, side):
    """§5: 무작위 일봉 마감 진입(+60초 +L), 손절 = 그날 2 × ATR20, 청산 = 그 방향 M일 반대 돌파."""
    cfg = TR.TrendConfig("E0", "LS", (n,))
    tb = TR.random_table(real["dd"], n, side, cfg, real["xb"], real["fa"])
    rng = np.random.default_rng(7)
    ok = np.flatnonzero(tb.filled)
    for i in rng.choice(ok, 20, replace=False):
        assert tb.r[i] == pytest.approx(_ref_random_trade(real["daily"], real["xb"], real["fa"], n, side,
                                                          int(tb.days[i])), abs=1e-9)


@needs_data
@pytest.mark.slow
def test_random_baseline_p95_independent_resample(real):
    """거래마다 (진입 UTC 달, 방향, N) 유지 → 그 달 일봉 균등 추출. 독립 추출(다른 난수)로 p95가 ±0.1R 안."""
    cfg = TR.TrendConfig("E0", "L", (55,))
    tr = TR.run_trend_combo(real["dd"], cfg, real["xb"], real["fa"])[0]
    tb = TR.random_table(real["dd"], 55, 1, cfg, real["xb"], real["fa"])
    eng = TR.run_trend_random_baseline(tr, {(55, 1): tb}, cfg)
    months = pd.to_datetime(real["dd"].close_ns[tb.days]).to_period("M")
    rng = np.random.default_rng(123)
    pools = [np.flatnonzero(months == pd.Timestamp(t.entry_time).to_period("M")) for t in TR.filled(tr)]
    means = [np.nanmean([tb.r[p[rng.integers(p.size)]] for p in pools]) for _ in range(2000)]
    assert abs(np.quantile(means, 0.95) - eng["p95"]) < 0.1
    assert eng["reps"] == 1000 and eng["n_trades"] == len(TR.filled(tr))


# ===========================================================================
# E. 미래 참조 — 실데이터 자르기
# ===========================================================================


@needs_data
@pytest.mark.slow
@pytest.mark.parametrize("cut", ["2021-07-01", "2023-10-15", "2025-03-03"])
def test_trunc_real_data_no_lookahead(real, cut):
    cn = C.ts_ns(cut)
    daily, xb = real["daily"], real["xb"]
    d2 = TR.DailyData.from_frame(daily[daily.close_ns <= cn])
    m = xb.close_ns <= cn
    x2 = ExecArrays(*(a[m] for a in (xb.open_ns, xb.close_ns, xb.open, xb.high, xb.low, xb.close)))
    lim = cn - NS_DAY
    for cfg in TR.trend_combos():
        a = TR.run_trend_combo(real["dd"], cfg, xb, real["fa"])[0]
        b = TR.run_trend_combo(d2, cfg, x2, real["fa"])[0]

        def done(ts):
            return [(t.plan_id, t.entry_time, t.exit_time, t.exit_price, round(t.r_multiple, 10)) for t in ts
                    if t.status == "filled" and t.exit_time < lim and t.exit_reason != "eod"]

        def entered(ts):
            return [(t.plan_id, t.entry_time) for t in ts if t.entry_time is not None and t.entry_time < lim]

        assert done(a) == done(b), cfg.key
        assert entered(a) == entered(b), cfg.key


# ===========================================================================
# F. run_g1t 산출물 (구조·E1 vs E0·오염 고지)
# ===========================================================================


@pytest.fixture(scope="module")
def run_out(real, tmp_path_factory):
    from backtest.run_g1t import run_g1t
    out = tmp_path_factory.mktemp("g1t_review")
    res = run_g1t(market=real["mk"], out_dir=out, n_reps=50, trials=False, quiet=True)
    return res, out


@needs_data
@pytest.mark.slow
def test_run_structure_matches_spec(run_out):
    res, out = run_out
    keys = [b["key"] for b in res["combos"]]
    assert set(keys) == {c.key for c in TR.trend_combos()}
    assert len(res["sensitivity"]) == 32
    assert {(s["key"], s["variant"]) for s in res["sensitivity"]} == \
        {(k, v) for k in keys for v in ("lat10", "lat120", "stop3", "cost2")}
    for b in res["combos"]:
        assert b["cost2"]["same_trades"] is True                   # 비용은 체결 시점에 영향 없음
        assert set(b["verdict"]) >= {"c1_mean_r", "c2_boot_lo", "c3_pf", "c4_cost2", "c5_random", "c6_years",
                                     "c7_enough_trades", "result"}
    pairs = {(c["e1"], c["e0"]) for c in res["e1_vs_e0"]}
    assert pairs == {(f"E1-{d}-{s}", f"E0-{d}-{s}") for d in ("LS", "L") for s in ("ENS", "N55")}
    assert res["params"]["n_trials"] == 8
    rep = (out / "G1T_REPORT.md").read_text(encoding="utf-8")
    assert "오염" in rep and "14.5%" in rep and "26.9%" in rep and "G3" in rep     # TREND_SPEC 오염 고지
    assert "E1" in rep and "95% 구간" in rep


@needs_data
@pytest.mark.slow
def test_run_e1_vs_e0_uses_same_direction_system_trades(real, run_out):
    """§5 보조 판정: 차이 = mean(E1 R) − mean(E0 R), 같은 방향·하위 시스템 묶음의 체결 거래."""
    res, _ = run_out
    cfgs = {x.key: x for x in TR.trend_combos()}
    for c in res["e1_vs_e0"]:
        e = {}
        for k in ("e1", "e0"):
            tr = TR.run_trend_combo(real["dd"], cfgs[c[k]], real["xb"], real["fa"])[0]
            e[k] = [t.r_multiple for t in TR.filled(tr)]
        assert c["diff"] == pytest.approx(np.mean(e["e1"]) - np.mean(e["e0"]), abs=1e-12)
        assert c["n1"] == len(e["e1"]) and c["n0"] == len(e["e0"])
        assert c["lo"] < c["diff"] < c["hi"]
        assert c["e1_better"] == (c["lo"] > 0)


# ===========================================================================
# G. 발견 사항
# ===========================================================================


@needs_data
@pytest.mark.slow
def test_finding_notional_ratio_counts_reversal_twice(real):
    """(TS-1 회귀, 고침) 반대 신호 날 청산·진입을 두 번 세지 않는다 → trim 곡선의 최대 명목 ≤ 0.6배."""
    cfg = TR.TrendConfig("E0", "LS")
    tr = TR.run_trend_combo(real["dd"], cfg, real["xb"], real["fa"])[0]
    f = TR.filled(tr)
    ev = sorted([(t.entry_time, 1) for t in f] + [(t.exit_time, -1) for t in f])   # 같은 시각: 청산(−1) 먼저
    cur = mx = 0
    for _, e in ev:
        cur += e
        mx = max(mx, cur)
    assert mx == 3                                                      # 실제 동시 보유 최대 3 (하위 시스템당 1)
    e = TR.equity_curve(tr, real["dd"], TR.combo_start_day(real["dd"], cfg), sizing="fixed", trim=True)
    assert e["max_notional_ratio"] <= 0.6 * 1.01


@needs_data
@pytest.mark.slow
def test_finding_random_baseline_month_pool_includes_pre_breakout_days(real):
    """기록(판정 아님): 무작위 기준선은 실제 거래가 있던 달 안의 모든 일봉에서 뽑는다(§5 '같은 월별 거래 수').
    그 달은 '뒤에 돌파가 나온 달'이라 돌파 전 날짜의 진입도 포함 → 기준선이 무조건 추출보다 크게 높다
    (N100 롱: 전체 평균 < 거래 달 평균). 전략을 부풀리지 않는 방향(합격이 더 어려움)이라 결함은 아니지만
    c5 불합격의 주된 원인이므로 보고서 해석에 적어야 한다."""
    cfg = TR.TrendConfig("E0", "L")
    tr = TR.filled(TR.run_trend_combo(real["dd"], cfg, real["xb"], real["fa"])[0])
    tb = TR.random_table(real["dd"], 100, 1, cfg, real["xb"], real["fa"])
    months = {int(TR._month_index(t.entry_time)) for t in tr if t.meta["n"] == 100}
    inm = np.isin(tb.months, list(months))
    assert np.nanmean(tb.r[inm]) > 2 * np.nanmean(tb.r)
