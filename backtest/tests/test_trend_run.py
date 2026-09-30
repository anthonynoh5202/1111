"""추세추종 무작위 기준선·계좌 곡선·통계·실행 스크립트 테스트 (TREND_SPEC §3·§5, run_g1t, report_trend)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from backtest import config as C
from backtest import run_g1t as RG
from backtest import trend as TR
from backtest import types as T
from backtest.tests.conftest import make_market
from backtest.tests.test_trend import NO_FUNDING, TREND_UP, WARM, build, cfg4, day_ns, run


@pytest.fixture(scope="module")
def mkt() -> T.MarketData:
    return make_market(days=200, seed=5, start="2023-07-01", one_minute_from="2023-10-01", tfs=("1d",))


# ---------------------------------------------------------------------------
# 무작위 기준선
# ---------------------------------------------------------------------------


def _fake_trade(n, side, entry_ns, r=0.0):
    return T.TradeResult(plan_id=f"x{n}{side}{entry_ns}", scenario=f"N{n}", side=side, order_type="market",
                         signal_time=entry_ns, approval_time=entry_ns, active_from=entry_ns, plan_entry=1.0,
                         stop=0.9, target=float("inf"), status="filled", busy_until=entry_ns + 1,
                         risk_per_unit=0.1, entry_time=entry_ns, entry_price=1.0, exit_time=entry_ns + 1,
                         exit_price=1.0, exit_reason="trend", r_multiple=r, meta={"n": n})


def _table(n, side, days, months, r, rm=None):
    days = np.asarray(days)
    return TR.RandomTable(n=n, side=side, days=days, months=np.asarray(months), filled=np.ones(days.size, bool),
                          r=np.asarray(r, float), r_maker=np.asarray(r if rm is None else rm, float))


def test_random_baseline_keeps_month_side_and_system():
    ma, mb = 2024 * 12 + 0, 2024 * 12 + 1                               # 2024-01, 2024-02
    tabs = {(4, 1): _table(4, 1, range(60), [ma] * 30 + [mb] * 30, [1.0] * 30 + [5.0] * 30),
            (4, -1): _table(4, -1, range(60), [ma] * 30 + [mb] * 30, [-3.0] * 60),
            (6, 1): _table(6, 1, range(60), [ma] * 30 + [mb] * 30, [7.0] * 60)}
    jan, feb = C.ts_ns("2024-01-15"), C.ts_ns("2024-02-10")
    cfg = cfg4()
    one = TR.run_trend_random_baseline([_fake_trade(4, 1, jan)], tabs, cfg, n_reps=50)
    assert one["mean"] == 1.0 and one["p95"] == 1.0                    # 1월 롱 → 1월 표만
    two = TR.run_trend_random_baseline([_fake_trade(4, 1, feb), _fake_trade(4, -1, jan)], tabs, cfg, n_reps=50)
    assert two["mean"] == pytest.approx((5.0 - 3.0) / 2)                 # 방향 유지
    three = TR.run_trend_random_baseline([_fake_trade(6, 1, jan)], tabs, cfg, n_reps=10)
    assert three["mean"] == 7.0                                         # 하위 시스템 유지


def test_random_baseline_deterministic_and_threshold():
    ma = 2024 * 12
    rng = np.random.default_rng(0)
    r = rng.normal(size=40)
    tabs = {(4, 1): _table(4, 1, range(40), [ma] * 40, r, r + 0.5)}
    tr = [_fake_trade(4, 1, C.ts_ns("2024-01-10")) for _ in range(5)]
    a = TR.run_trend_random_baseline(tr, tabs, cfg4(), n_reps=200)
    b = TR.run_trend_random_baseline(tr, tabs, cfg4(), n_reps=200)
    np.testing.assert_array_equal(a["means"], b["means"])
    assert a["p95"] == pytest.approx(float(np.quantile(a["means"], 0.95)))
    assert a["threshold"] == a["p95"]                                   # E0: 시장가 분포
    e1 = TR.run_trend_random_baseline(tr, tabs, cfg4(entry="E1"), n_reps=200)
    assert e1["threshold"] == pytest.approx(max(e1["p95"], e1["maker"]["p95"]))
    assert e1["maker"]["p95"] > e1["p95"]                               # 메이커 쪽이 더 높아 기준이 됨
    other = TR.run_trend_random_baseline(tr, tabs, cfg4(direction="L"), n_reps=200)
    assert not np.array_equal(other["means"], a["means"])               # 시드 = 조합 키
    empty = TR.run_trend_random_baseline([], tabs, cfg4(), n_reps=10)
    assert empty["means"].size == 0 and np.isnan(empty["p95"])


def test_random_table_matches_real_e0_trades(mkt):
    """무작위 표의 '일봉 d 진입' 결과 = 같은 날 신호의 실제 E0 거래 (같은 진입·손절·청산 규칙, §5)."""
    daily, xb, fa = TR.DailyData.from_frame(mkt.bars["1d"]), mkt.exec_arrays(), mkt.funding_arrays()
    cfg = TR.TrendConfig("E0", "LS", (10, 20))
    trades, _ = TR.run_trend_combo(daily, cfg, xb, fa)
    tabs = TR.random_tables_for(daily, cfg, xb, fa)
    f = TR.filled(trades)
    assert f
    for t in f:
        tb = tabs[(t.meta["n"], t.side)]
        d = int(np.searchsorted(daily.close_ns, t.signal_time))
        i = int(np.searchsorted(tb.days, d))
        assert tb.days[i] == d and tb.filled[i]
        assert tb.r[i] == pytest.approx(t.r_multiple, abs=1e-12)
    # 진입 비용만 메이커(슬리피지 없음)로 바꾼 R = 같은 거래의 가격·펀딩으로 손 계산
    t = f[0]
    tb = tabs[(t.meta["n"], t.side)]
    i = int(np.searchsorted(tb.days, int(np.searchsorted(daily.close_ns, t.signal_time))))
    net = t.gross_pnl - (C.FEE_MAKER * t.entry_price + C.FEE_TAKER * t.exit_price) - C.SLIPPAGE * t.exit_price \
        - t.funding
    assert tb.r_maker[i] == pytest.approx(net / float(C.risk_per_unit(t.entry_price, t.stop, C.FEE_MAKER)))
    rb = TR.run_trend_random_baseline(trades, tabs, cfg, n_reps=30)
    assert rb["n_trades"] == len(f) and np.isfinite(rb["p95"])


# ---------------------------------------------------------------------------
# 통계·계좌 곡선
# ---------------------------------------------------------------------------


def test_bootstrap_mean_diff_ci():
    out = TR.bootstrap_mean_diff_ci([2.0] * 5, [0.5] * 7, n_boot=500)
    assert out["diff"] == 1.5 and out["lo"] == pytest.approx(1.5) and out["hi"] == pytest.approx(1.5)
    rng = np.random.default_rng(1)
    a, b = rng.normal(1.0, 1.0, 200), rng.normal(0.0, 1.0, 200)
    x = TR.bootstrap_mean_diff_ci(a, b, rng=C.make_rng("t"))
    y = TR.bootstrap_mean_diff_ci(a, b, rng=C.make_rng("t"))
    assert x == y and x["lo"] < x["diff"] < x["hi"] and x["lo"] > 0
    assert np.isnan(TR.bootstrap_mean_diff_ci([], [1.0])["lo"])


def test_equity_curve_single_trade_hand_calc():
    trades, _, daily, _ = run(TREND_UP, cfg4(stop_atr_mult=20.0))   # 손절이 멀어 명목 상한(0.2배)이 걸리지 않음
    t = trades[0]
    assert t.exit_reason == TR.EXIT_TREND
    start = 21
    risk = TR.equity_curve(trades, daily, start, sizing="risk")
    qty = 1.0 * TR.RISK_R / (t.risk_per_unit / t.entry_price) / t.entry_price   # 자산 1 × 0.5% ÷ 손절 거리 비율
    assert risk["final_equity"] == pytest.approx(1.0 + qty * t.net_pnl)
    # 보유 중(28일 종가 108) 평가 = 1 + 수량 × (108 − 106)
    assert risk["equity"][28 - start] == pytest.approx(1.0 + qty * 2.0)
    assert risk["n_trims"] == 0 and risk["max_notional_ratio"] < 0.2
    fixed = TR.equity_curve(trades, daily, start, sizing="fixed", trim=False)
    assert fixed["final_equity"] == pytest.approx(1.0 + 0.2 / t.entry_price * t.net_pnl)
    assert len(risk["equity"]) == len(daily) - start and risk["equity"][0] == 1.0


def test_equity_curve_trim_caps_notional():
    closes = WARM + [105, 106] + list(np.linspace(110, 300, 20)) + [300] * 3
    trades, _, daily, _ = run(closes, cfg4(direction="L"))
    assert len(trades) == 1 and trades[0].exit_reason == "eod"
    hold = TR.equity_curve(trades, daily, 21, sizing="fixed", trim=False)
    trim = TR.equity_curve(trades, daily, 21, sizing="fixed", trim=True)
    assert hold["max_notional_ratio"] > 0.3 and hold["n_trims"] == 0
    assert trim["n_trims"] > 0 and trim["max_notional_ratio"] <= 0.2 * (1 + 1e-6)
    assert trim["final_equity"] < hold["final_equity"]                  # 상승 추세에서 줄이면 덜 번다


# ---------------------------------------------------------------------------
# 실행 스크립트·보고서
# ---------------------------------------------------------------------------


def _strip_run(res: dict) -> dict:
    return {k: v for k, v in res.items() if k not in ("created_utc", "runtime_sec")}


def test_run_g1t_outputs_and_determinism(mkt, tmp_path):
    a = RG.run_g1t(market=mkt, out_dir=tmp_path / "a", n_reps=20, quiet=True)
    b = RG.run_g1t(market=mkt, out_dir=tmp_path / "b", n_reps=20, quiet=True, sensitivity=True)
    ja = json.loads((tmp_path / "a" / RG.RESULTS_JSON).read_text(encoding="utf-8"))
    jb = json.loads((tmp_path / "b" / RG.RESULTS_JSON).read_text(encoding="utf-8"))
    assert _strip_run(ja) == _strip_run(jb)
    assert ja["schema"] == RG.SCHEMA and len(ja["combos"]) == 8
    keys = [c["key"] for c in ja["combos"]]
    assert keys == [c.key for c in TR.trend_combos()]
    for c in ja["combos"]:
        assert set(c) >= {"summary", "cost2", "random", "verdict", "equity", "by_system", "dsr"}
        assert set(c["verdict"]) >= {"c1_mean_r", "c5_random", "c7_enough_trades", "result"}
        assert set(c["equity"]) >= {"risk", "fixed", "risk_hold", "fixed_hold"}
        assert (tmp_path / "a" / "trades" / f"{c['key']}.csv").exists()
        assert (tmp_path / "a" / "equity" / f"{c['key']}.csv").exists()
        assert c["cost2"]["same_trades"] is True                          # 비용은 체결 시점과 무관
    assert len(ja["e1_vs_e0"]) == 4
    assert len(ja["sensitivity"]) == 8 * 4
    assert {s["variant"] for s in ja["sensitivity"]} == {"lat10", "lat120", "stop3", "cost2"}
    assert ja["summary"]["official"] is False
    rep = (tmp_path / "a" / RG.REPORT_MD).read_text(encoding="utf-8")
    for head in ("한눈에 보기", "7개 기준", "E1(눌림 대기) vs E0", "계좌 곡선", "무작위 기준선", "민감도", "오염"):
        assert head in rep
    assert a["summary"]["decision"]


def test_selection_prefers_simple_and_penalizes_drawdown():
    def blk(res, mdd):
        return {"verdict": {"result": res}, "equity": {"risk": {"max_drawdown": mdd}}}
    blocks = {"E0-LS-ENS": blk("pass", 0.2), "E0-L-N55": blk("pass", 0.35), "E0-L-ENS": blk("pass", 0.1),
              "E1-L-N55": blk("pass", 0.1), "E0-LS-N55": blk("fail", 0.1), "E1-LS-N55": blk("pending", 0.1)}
    cmp = [{"e1": "E1-L-N55", "e1_better": False}]
    s = RG.selection(blocks, cmp)
    assert s["ranked"] == ["E0-L-ENS", "E0-LS-ENS", "E0-L-N55"]         # 낙폭 30% 초과는 후순위
    assert "E1-L-N55" not in s["ranked"] and "E1-L-N55" in s["notes"]
    assert s["n_pass"] == 4 and s["pending"] == ["E1-LS-N55"] and s["fail"] == ["E0-LS-N55"]
    s2 = RG.selection(blocks, [{"e1": "E1-L-N55", "e1_better": True}])
    assert s2["ranked"][0] == "E1-L-N55" or s2["ranked"][0] == "E0-L-ENS"
    assert s2["ranked"].index("E1-L-N55") < s2["ranked"].index("E0-L-N55")
