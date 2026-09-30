"""TREND v1.1(참고) 전체 기간 무작위 기준선 테스트 (backtest/random_fair.py)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from backtest import config as C
from backtest import random_fair as RF
from backtest import trend as TR
from backtest import types as T
from backtest.tests.conftest import make_market


def _fake_trade(n, side, entry_ns, r=0.0):
    return T.TradeResult(plan_id=f"x{n}{side}{entry_ns}", scenario=f"N{n}", side=side, order_type="market",
                         signal_time=entry_ns, approval_time=entry_ns, active_from=entry_ns, plan_entry=1.0,
                         stop=0.9, target=float("inf"), status="filled", busy_until=entry_ns + 1,
                         risk_per_unit=0.1, entry_time=entry_ns, entry_price=1.0, exit_time=entry_ns + 1,
                         exit_price=1.0, exit_reason="trend", r_multiple=r, meta={"n": n})


def _table(n, side, r, rm=None, filled=None, months=None):
    r = np.asarray(r, float)
    days = np.arange(r.size)
    return TR.RandomTable(n=n, side=side, days=days,
                          months=np.asarray(months if months is not None else [2024 * 12] * r.size),
                          filled=np.ones(r.size, bool) if filled is None else np.asarray(filled, bool),
                          r=r, r_maker=r if rm is None else np.asarray(rm, float))


def _cfg(entry="E0"):
    return TR.TrendConfig(entry, "LS", periods=(4, 6))


JAN = C.ts_ns("2024-01-15")


def test_ignores_month_uses_whole_pool():
    # 1월 30일 = 1, 2월 30일 = 5 → 1월 거래라도 전체(평균 3)에서 뽑는다 (공식 기준선이면 1.0)
    tabs = {(4, 1): _table(4, 1, [1.0] * 30 + [5.0] * 30, months=[2024 * 12] * 30 + [2024 * 12 + 1] * 30)}
    trades = [_fake_trade(4, 1, JAN)] * 20
    fair = RF.fair_random_baseline(trades, tabs, _cfg(), n_reps=2000)
    assert fair["mean"] == pytest.approx(3.0, abs=0.05)
    assert fair["p05"] < 3.0 < fair["p95"]
    official = TR.run_trend_random_baseline(trades, tabs, _cfg(), n_reps=50)
    assert official["mean"] == 1.0


def test_keeps_side_and_system():
    tabs = {(4, 1): _table(4, 1, [2.0] * 10), (4, -1): _table(4, -1, [-4.0] * 10), (6, 1): _table(6, 1, [7.0] * 5)}
    assert RF.fair_random_baseline([_fake_trade(4, 1, JAN)], tabs, _cfg(), n_reps=20)["mean"] == 2.0
    two = RF.fair_random_baseline([_fake_trade(4, 1, JAN), _fake_trade(4, -1, JAN)], tabs, _cfg(), n_reps=20)
    assert two["mean"] == pytest.approx(-1.0) and two["p95"] == pytest.approx(-1.0)
    assert RF.fair_random_baseline([_fake_trade(6, 1, JAN)], tabs, _cfg(), n_reps=5)["mean"] == 7.0
    assert two["pool_sizes"] == {"N4L": 10, "N4S": 10}


def test_only_filled_days_drawn_same_trade_count():
    # 미체결 일봉(r = NaN)은 풀에서 빠져 모든 반복이 거래 수를 그대로 유지 (F-1)
    r = [np.nan] * 5 + [1.0] * 5
    tabs = {(4, 1): _table(4, 1, r, filled=[False] * 5 + [True] * 5)}
    fair = RF.fair_random_baseline([_fake_trade(4, 1, JAN)] * 3, tabs, _cfg(), n_reps=100)
    assert np.all(fair["means"] == 1.0)
    assert fair["n_excluded_unfilled"] == {"N4L": 5}
    with pytest.raises(ValueError):
        RF.fair_random_baseline([_fake_trade(4, 1, JAN)], {(4, 1): _table(4, 1, [np.nan], filled=[False])},
                                _cfg(), n_reps=5)


def test_deterministic_and_e1_threshold():
    rng = np.random.default_rng(0)
    r = rng.normal(size=50)
    tabs = {(4, 1): _table(4, 1, r, r + 0.5)}
    trades = [_fake_trade(4, 1, JAN)] * 8
    a = RF.fair_random_baseline(trades, tabs, _cfg("E0"), n_reps=300)
    b = RF.fair_random_baseline(trades, tabs, _cfg("E0"), n_reps=300)
    assert np.array_equal(a["means"], b["means"]) and a["seed_parts"] == ["trend_random_fair", _cfg().key]
    assert a["threshold"] == a["p95"]
    e1 = RF.fair_random_baseline(trades, tabs, _cfg("E1"), n_reps=300)
    assert e1["maker"]["p95"] > e1["p95"]
    assert e1["threshold"] == e1["maker"]["p95"]
    # 같은 추출 → 메이커 분포 = 시장가 분포 + 0.5
    assert e1["maker"]["mean"] == pytest.approx(e1["mean"] + 0.5)


def test_empty_trades():
    out = RF.fair_random_baseline([], {}, _cfg(), n_reps=10)
    assert out["n_trades"] == 0 and np.isnan(out["mean"]) and out["means"].size == 0
    assert RF.compare(1.0, out)["beats_p95"] is None


def test_compare():
    fair = {"means": np.arange(100, dtype=float) / 100, "threshold": 0.9405}
    c = RF.compare(0.95, fair)
    assert c["beats_p95"] is True and c["frac_ge_actual"] == pytest.approx(0.05)
    assert c["p_value"] == pytest.approx(6 / 101)
    assert RF.compare(0.94, fair)["beats_p95"] is False
    assert RF.compare(0.9405, fair)["beats_p95"] is False           # 엄격 (F-5)


def test_trials_line_format():
    res = {"params": {"reps": 1000}, "summary": {"n_combos": 2, "n_beat_fair_p95": 1},
           "combos": [{"key": "E0-L-ENS", "actual_mean_r": 1.3, "fair": {"threshold": 0.4}},
                      {"key": "E0-L-N55", "actual_mean_r": 0.1, "fair": {"threshold": 0.9}}]}
    line = RF.trials_line(res | {"created_utc": "2026-09-30T13:57:09Z"})
    cells = [c.strip() for c in line.strip("|").split("|")]
    assert cells[0] == "2026-09-30" and cells[1] == "TREND v1.1(참고)"      # R-5: 실제 실행일(결과 JSON)
    import re
    from datetime import datetime, timezone
    today = RF.trials_line(res).strip("|").split("|")[0].strip()          # created_utc 없으면 오늘(UTC)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today) and today == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert "판정에 쓰지 않음" in cells[2] and cells[3] == "2"
    assert "1/2" in cells[4] and "E0-L-ENS +1.30/+0.40" in cells[4]


def test_run_fair_synthetic(tmp_path):
    mkt = make_market(days=200, seed=5, start="2023-07-01", one_minute_from="2023-10-01", tfs=("1d",))
    res = RF.run_fair(market=mkt, out_dir=tmp_path, n_reps=50, only=["E0-L-ENS", "E1-LS-N55"], quiet=True)
    assert res["source"] == "synthetic" and res["summary"]["n_combos"] == 2
    data = json.loads((tmp_path / RF.RESULTS_JSON).read_text(encoding="utf-8"))
    assert data["schema"] == RF.SCHEMA and "쓰지 않음" in data["note"]
    daily = TR.DailyData.from_frame(mkt.bars["1d"])
    xb, fa = mkt.exec_arrays(), mkt.funding_arrays()
    for b in data["combos"]:
        cfg = next(c for c in TR.trend_combos() if c.key == b["key"])
        trades, _ = TR.run_trend_combo(daily, cfg, xb, fa)
        f = TR.filled(trades)
        assert b["n_trades"] == len(f)                                # 같은 거래 수
        if f:
            assert b["actual_mean_r"] == pytest.approx(float(np.mean([t.r_multiple for t in f])))
            assert b["fair"]["reps"] == 50 and b["compare"]["beats_p95"] in (True, False)
        assert b["month_matched"] is None                             # 합성 데이터는 공식 결과와 비교 안 함
    with pytest.raises(ValueError):
        RF.run_fair(market=mkt, out_dir=tmp_path, n_reps=5, only=["없음"], quiet=True)
