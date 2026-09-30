"""추세추종 미래 참조 금지 테스트 (TREND_SPEC §1·§2, DESIGN §4 C-1·C-6·C-12).

절단 불변: 시각 T까지 마감된 봉·펀딩만 남긴 데이터(truncate_market)로 돌린 신호·거래가 전체 데이터 결과의
'T까지 정해진 부분'과 같아야 한다.
- 신호 기록: 판단 시각(마감 + 60초) ≤ T 인 기록 전부 동일.
- 거래: 승인(판단) 시각 ≤ T 인 계획 수 동일. T까지 끝난 거래(청산 봉 끝 ≤ T, 미체결은 busy_until ≤ T)는 모든 필드 동일
  (meta의 청산 신호 시각만 T 뒤면 절단 쪽은 모름). T에 걸친 거래는 진입 필드 동일, 절단 쪽은 'eod'.
- 미래 변경: T 뒤 가격을 바꿔도 위와 같은 부분이 같다.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from backtest import config as C
from backtest import trend as TR
from backtest import types as T
from backtest.tests.conftest import make_market, truncate_market


def _inputs(m: T.MarketData):
    return TR.DailyData.from_frame(m.bars["1d"]), m.exec_arrays(), m.funding_arrays()


@pytest.fixture(scope="module")
def market_trend() -> T.MarketData:
    """260일 합성 시장(5분 실행 봉 + 2023-10-01부터 1분봉, 펀딩 0.01%)."""
    return make_market(days=260, seed=11, start="2023-06-01", one_minute_from="2023-10-01", tfs=("1d",))


CFGS = [TR.TrendConfig(e, d, p) for e in TR.ENTRY_TYPES for d in TR.DIRECTIONS for p in ((20, 55), (10,), (5,))]


def _strip(t: T.TradeResult, cut: int) -> T.TradeResult:
    meta = dict(t.meta)
    es = meta.get("exit_signal_time")
    if es and C.ts_ns(es) > cut:
        meta["exit_signal_time"] = ""
    return dataclasses.replace(t, meta=meta)


def _check_prefix(full, part, cut: int, truncated: bool = True) -> int:
    ft, fl = full
    pt, pl = part
    # 판단 시각(마감 + 60초) ≤ T 인 결정만 비교: 판단은 그 시각까지의 실행 봉(예: 마감 직후 1분봉 손절)을 쓸 수 있다
    assert [g for g in fl if g.time <= cut] == [g for g in pl if g.time <= cut]
    ft = [t for t in ft if t.approval_time <= cut]
    assert len(ft) == len([t for t in pt if t.approval_time <= cut])
    by_id = {t.plan_id: t for t in pt}
    checked = 0
    for t in ft:
        p = by_id[t.plan_id]
        done = (t.exit_bar_close_ns is not None and t.exit_bar_close_ns <= cut) or \
               (t.status != "filled" and t.busy_until <= cut)
        if done:
            assert _strip(t, cut) == _strip(p, cut), t.plan_id
            checked += 1
        elif t.status == "filled" and t.entry_time is not None and t.entry_time < cut \
                and int(t.entry_time) + 1 <= cut:
            # T에 걸친 거래: 진입은 같고, 절단 쪽은 데이터 끝 청산
            if p.status == "filled":
                assert (p.entry_time, p.entry_price, p.stop, p.plan_entry) == \
                       (t.entry_time, t.entry_price, t.stop, t.plan_entry)
                if truncated:
                    assert p.exit_reason == "eod" 
    return checked


@pytest.mark.parametrize("cfg", CFGS, ids=lambda c: c.key)
def test_truncation_invariance(market_trend, cfg):
    full = TR.run_trend_combo(*_inputs(market_trend)[:1], cfg, *_inputs(market_trend)[1:])
    assert TR.filled(full[0]), "합성 데이터에 체결 거래가 있어야 의미 있는 시험"
    closes = market_trend.bars["1d"]["close_ns"].to_numpy()
    total = 0
    for k in (80, 140, 200):
        for off in (0, 3 * C.NS_PER_HOUR + 17 * C.NS_PER_MIN):
            cut = int(closes[k]) + off
            part_m = truncate_market(market_trend, cut)
            d, xb, fa = _inputs(part_m)
            part = TR.run_trend_combo(d, cfg, xb, fa)
            total += _check_prefix(full, part, cut)
    assert total > 0


def test_future_change_invariance(market_trend):
    """T 뒤 실행 봉·일봉 가격을 크게 바꿔도 T까지 정해진 거래·신호는 같다."""
    cfg = TR.TrendConfig("E1", "LS", (20, 55))
    base = TR.run_trend_combo(*_inputs(market_trend)[:1], cfg, *_inputs(market_trend)[1:])
    closes = market_trend.bars["1d"]["close_ns"].to_numpy()
    cut = int(closes[170])
    m2 = dataclasses.replace(market_trend)
    bars = {k: v.copy() for k, v in market_trend.bars.items()}
    xbf = market_trend.exec_bars.copy()
    for df in (bars["1d"], xbf):
        after = df["open_ns"].to_numpy() >= cut
        for c in ("open", "high", "low", "close"):
            v = df[c].to_numpy(copy=True)
            v[after] = v[after] * 0.7 + 1000.0               # T 뒤 경로를 완전히 바꿈(모양 유지)
            df[c] = v
    m2 = T.MarketData(bars=bars, exec_bars=xbf, funding=market_trend.funding, events_ns=None)
    changed = TR.run_trend_combo(*_inputs(m2)[:1], cfg, *_inputs(m2)[1:])
    assert _check_prefix(base, changed, cut, truncated=False) > 0


def test_signals_use_only_closed_daily_bars(market_trend):
    """신호 기록의 판단 시각 = 일봉 마감 + 60초, 진입은 활성 시각 이후 시작하는 실행 봉."""
    cfg = TR.TrendConfig("E0", "LS", (20, 55))
    d, xb, fa = _inputs(market_trend)
    trades, logs = TR.run_trend_combo(d, cfg, xb, fa)
    for g in logs:
        assert g.time == g.signal_time + C.AVAIL_DELAY_NS
        assert g.signal_time in set(d.close_ns.tolist())
    for t in TR.filled(trades):
        assert t.entry_time >= t.active_from == t.approval_time + cfg.latency_ns
        j = int(np.searchsorted(xb.open_ns, t.entry_time))
        assert j == 0 or xb.open_ns[j - 1] < t.active_from           # 활성 뒤 '첫' 실행 봉
