"""체결 엔진 테스트 (DESIGN §9 T-EXE, RULES_SPEC §8.1·§8.2·§12.1~§12.3).

손으로 계산한 작은 사례 + 문장 그대로 옮긴 느린 참조 구현과의 무작위 대조.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from backtest import config as C
from backtest import execution as X
from backtest import types as T
from backtest.tests.conftest import make_bars, make_exec_bars, make_funding, ns

# 자주 쓰는 1분봉 모양 (시가, 고가, 저가, 종가) — 기본 계획: 롱 지정가 100, 손절 99, 목표 102
FLAT = (100.3, 100.4, 100.2, 100.3)      # 아무것도 안 닿음
PIERCE = (100.3, 100.4, 99.95, 100.3)    # 저가 99.95 < 100 → 매수 체결, 손절(99)은 안 닿음
TOUCH = (100.3, 100.4, 100.0, 100.3)     # 저가 == 100 → 닿기만 함(미체결)
STOP_BAR = (100.2, 100.3, 98.9, 99.2)    # 손절 99 닿음(시가는 손절 위)

NO_FUNDING = T.FundingArrays(time_ns=np.array([], dtype=np.int64), rate=np.array([], dtype=np.float64))
P1_HOLD = 72 * C.NS_PER_HOUR
P2_HOLD = 72 * 4 * C.NS_PER_HOUR
RISK_100_99_LIMIT = 1.0 + 0.0002 * 100 + 0.0007 * 99   # d + c_stop = 1.0893 (§12.2)


def xb_rows(rows, start="2024-01-01 10:11", tf="1m") -> T.ExecArrays:
    return T.ExecArrays.from_frame(make_bars(list(rows), start=start, tf=tf))


def mk_plan(**kw) -> T.Plan:
    base = dict(plan_id="L1a_test", scenario="L1a", side=1, signal_time=ns("2024-01-01 10:00"),
                approval_time=ns("2024-01-01 10:01"), active_from=ns("2024-01-01 10:11"), order_type="limit",
                entry_price=100.0, stop=99.0, target=102.0, valid_until=ns("2024-01-02 10:00"),
                max_hold_ns=P1_HOLD, atr_at_signal=0.5)
    base.update(kw)
    return T.Plan(**base)


def mk_cand(plan: T.Plan, reasons=()) -> T.Candidate:
    log = T.SignalLog(time=plan.approval_time, signal_time=plan.signal_time, scenario=plan.scenario,
                      side=plan.side, status="discarded" if reasons else "passed",
                      reasons=T.sort_reasons(reasons), plan_id=plan.plan_id, madi_id=plan.madi_id,
                      meta={"tb_close_ns": 0})
    return T.Candidate(log=log, plan=plan)


def hourly_plan(hour: str, **kw) -> T.Plan:
    """정시 신호 봉 마감 hour → 승인 +1분, 활성 +11분, 1시간 유효."""
    t = ns(hour)
    base = dict(plan_id=f"L1a_{hour}", signal_time=t, approval_time=t + C.NS_PER_MIN,
                active_from=t + 11 * C.NS_PER_MIN, valid_until=t + C.NS_PER_HOUR)
    base.update(kw)
    return mk_plan(**base)


# ---------------------------------------------------------------------------
# 진입: 관통·활성 시각·수명 경계 (§12.1, I-30, I-31)
# ---------------------------------------------------------------------------


def test_limit_long_needs_pierce_not_touch():
    xb = xb_rows([TOUCH, PIERCE, FLAT])
    assert X.find_entry(mk_plan(), xb) == (1, 100.0)            # 저가 == 100 봉은 건너뛰고 99.95 봉에서 100에 체결
    only_touch = xb_rows([TOUCH, TOUCH, FLAT])
    assert X.find_entry(mk_plan(), only_touch) is None
    tr = X.simulate_plan(mk_plan(valid_until=ns("2024-01-01 10:14")), only_touch, NO_FUNDING)
    assert tr.status == T.Status.EXPIRED and tr.busy_until == ns("2024-01-01 10:14")


def test_limit_short_needs_pierce_not_touch():
    short = mk_plan(side=-1, scenario="S2", entry_price=100.0, stop=101.0, target=98.0)
    xb = xb_rows([(99.5, 100.0, 99.2, 99.6), (99.6, 100.1, 99.5, 99.8), (99.8, 99.9, 99.7, 99.8)])
    assert X.find_entry(short, xb) == (1, 100.0)                # 고가 == 100 봉은 미체결, 100.1 봉에서 체결


def test_activation_1m_ignores_bars_before_active_from():
    xb = xb_rows([PIERCE] * 20, start="2024-01-01 10:00")       # 10:00~10:19 모두 관통하는 봉
    j0, j1 = X.entry_window(mk_plan(), xb)
    assert xb.open_ns[j0] == ns("2024-01-01 10:11")             # 10:10 봉(10:11 마감)도 안 본다
    tr = X.simulate_plan(mk_plan(), xb, NO_FUNDING)
    assert tr.entry_time == ns("2024-01-01 10:11")


def test_activation_5m_waits_for_next_bar_start():
    xb = xb_rows([PIERCE] * 8, start="2024-01-01 10:00", tf="5m")
    tr = X.simulate_plan(mk_plan(), xb, NO_FUNDING)             # 10:01 + 10분 = 10:11 → 10:15 봉부터
    assert tr.entry_time == ns("2024-01-01 10:15")
    exact = X.simulate_plan(mk_plan(active_from=ns("2024-01-01 10:15")), xb, NO_FUNDING)
    assert exact.entry_time == ns("2024-01-01 10:15")           # 활성 시각에 시작하는 봉은 포함


def test_fill_before_cancel_effective_time_is_valid_1m():
    rows = [FLAT] * 120                                         # 10:11 ~ 12:10
    k_ok = 109                                                  # 12:00 봉 (12:01 마감 = 취소 효력 시각)
    plan = mk_plan(cancel_effective_time=ns("2024-01-01 12:01"), cancel_reason="close_below")
    rows_ok = list(rows)
    rows_ok[k_ok] = PIERCE
    tr = X.simulate_plan(plan, xb_rows(rows_ok), NO_FUNDING)
    assert tr.status == T.Status.FILLED and tr.entry_time == ns("2024-01-01 12:00")
    rows_late = list(rows)
    rows_late[k_ok + 1] = PIERCE                                # 12:01 봉 → 효력 뒤
    tr = X.simulate_plan(plan, xb_rows(rows_late), NO_FUNDING)
    assert tr.status == T.Status.CANCELLED and tr.busy_until == ns("2024-01-01 12:01")
    assert tr.meta["cancel_reason"] == "close_below" and np.isnan(tr.r_multiple)


def test_5m_bar_straddling_cancel_effective_time_not_accepted():
    rows = [FLAT] * 30                                          # 5분봉 10:10 ~ 12:35
    rows[22] = PIERCE                                           # 12:00~12:05 봉: 끝이 12:01을 넘는다
    plan = mk_plan(cancel_effective_time=ns("2024-01-01 12:01"))
    tr = X.simulate_plan(plan, xb_rows(rows, start="2024-01-01 10:10", tf="5m"), NO_FUNDING)
    assert tr.status == T.Status.CANCELLED and tr.entry_time is None


def test_bar_ending_at_valid_until_accepted_then_expired():
    rows = [FLAT] * (24 * 60)                                   # 10:11 ~ 다음 날 10:10
    k_last = (24 * 60 - 11) - 1                                 # 다음 날 09:59 봉 (10:00 마감 = 만료 시각)
    ok = list(rows)
    ok[k_last] = PIERCE
    assert X.simulate_plan(mk_plan(), xb_rows(ok), NO_FUNDING).entry_time == ns("2024-01-02 09:59")
    late = list(rows)
    late[k_last + 1] = PIERCE                                   # 10:00 봉 → 만료 뒤
    tr = X.simulate_plan(mk_plan(), xb_rows(late), NO_FUNDING)
    assert tr.status == T.Status.EXPIRED and tr.busy_until == ns("2024-01-02 10:00")


def test_cancelled_vs_expired_and_busy_until():
    xb = xb_rows([FLAT] * 60)
    vu = ns("2024-01-01 11:00")
    assert X.simulate_plan(mk_plan(valid_until=vu), xb, NO_FUNDING).status == T.Status.EXPIRED
    same = X.simulate_plan(mk_plan(valid_until=vu, cancel_effective_time=vu), xb, NO_FUNDING)
    assert same.status == T.Status.EXPIRED and same.busy_until == vu                     # 효력 = 만료 → 만료
    tr = X.simulate_plan(mk_plan(valid_until=vu, cancel_effective_time=ns("2024-01-01 10:31")), xb, NO_FUNDING)
    assert tr.status == T.Status.CANCELLED and tr.busy_until == ns("2024-01-01 10:31")  # order_end
    none = X.simulate_plan(mk_plan(active_from=ns("2024-01-01 12:00")), xb, NO_FUNDING)  # 활성 뒤 봉 없음
    assert none.status == T.Status.NOT_FILLED and none.busy_until == ns("2024-01-01 12:00")
    assert X.entry_window(mk_plan(active_from=ns("2024-01-01 12:00")), xb) == (60, 60)


def test_ioc_cap_fills_at_open_or_not_at_all():
    ioc = mk_plan(scenario="L1b", order_type="ioc_cap", entry_price=100.1, valid_until=ns("2024-01-01 10:11"))
    at_cap = xb_rows([(100.1, 100.2, 100.0, 100.1), (100.1, 102.5, 100.0, 102.2)])
    tr = X.simulate_plan(ioc, at_cap, NO_FUNDING)
    assert tr.status == T.Status.FILLED and tr.entry_price == 100.1                     # 시가 == 상한 → 체결
    assert tr.exit_reason == T.Exit.TARGET and tr.exit_price == 102.0
    assert tr.fees == pytest.approx(0.0005 * 100.1 + 0.0002 * 102.0, abs=1e-12)         # 진입 테이커
    risk = abs(100.1 - 99.0) + 0.0005 * 100.1 + 0.0007 * 99.0                           # 실제 체결가(= 상한) 기준 (I-29)
    assert tr.risk_per_unit == pytest.approx(risk, abs=1e-12)
    below = xb_rows([(100.05, 100.2, 100.0, 100.1), FLAT])
    tb = X.simulate_plan(ioc, below, NO_FUNDING)
    assert tb.entry_price == 100.05                                                      # 시가 체결
    assert tb.risk_per_unit == pytest.approx(1.05 + 0.0005 * 100.05 + 0.0007 * 99.0, abs=1e-12)   # 체결가 기준
    over = xb_rows([(100.2, 100.3, 99.5, 100.0), (99.6, 99.7, 99.5, 99.6)])             # 시가 > 상한
    tr = X.simulate_plan(ioc, over, NO_FUNDING)
    assert tr.status == T.Status.NOT_FILLED and tr.busy_until == ns("2024-01-01 10:12")  # 시도 봉 close_ns
    assert X.entry_window(ioc, over) == (0, 1)                                           # 첫 봉 하나만


def test_market_order_fills_at_first_open():
    mkt = mk_plan(order_type="market", entry_price=100.3, stop=99.0, target=102.0)
    j, px = X.find_entry(mkt, xb_rows([FLAT, PIERCE], start="2024-01-01 10:11"))
    assert (j, px) == (0, 100.3)


# ---------------------------------------------------------------------------
# 청산: 체결 봉 손절, 손절 우선, 관통·닿음, 갭, 시간, 데이터 끝 (§12.1~12.2, I-30~I-36)
# ---------------------------------------------------------------------------


def test_stop_in_fill_bar_and_target_ignored_in_fill_bar():
    both = xb_rows([(100.5, 102.5, 98.9, 100.0), FLAT, FLAT])
    tr = X.simulate_plan(mk_plan(), both, NO_FUNDING)
    assert (tr.exit_reason, tr.exit_price, tr.exit_time) == (T.Exit.STOP, 99.0, tr.entry_time)
    tgt_only = xb_rows([(100.5, 102.5, 99.5, 101.0), (101.0, 101.5, 100.5, 101.0), (101.0, 102.1, 100.9, 102.0)])
    tr = X.simulate_plan(mk_plan(), tgt_only, NO_FUNDING)
    assert tr.exit_reason == T.Exit.TARGET and tr.exit_time == ns("2024-01-01 10:13")   # 다음 봉부터


def test_stop_first_when_bar_touches_both():
    xb = xb_rows([PIERCE, (100.2, 102.5, 98.9, 100.0), FLAT])
    tr = X.simulate_plan(mk_plan(), xb, NO_FUNDING)
    assert (tr.exit_reason, tr.exit_price) == (T.Exit.STOP, 99.0)


def test_target_needs_pierce_stop_needs_touch():
    xb = xb_rows([PIERCE, (100.2, 102.0, 100.1, 101.9), (101.9, 101.95, 99.0, 99.5), FLAT])
    tr = X.simulate_plan(mk_plan(), xb, NO_FUNDING)
    assert (tr.exit_reason, tr.exit_price, tr.exit_time) == (T.Exit.STOP, 99.0, ns("2024-01-01 10:13"))
    short = mk_plan(side=-1, scenario="S3", entry_price=100.0, stop=101.0, target=98.0)
    xs = xb_rows([(99.7, 100.1, 99.6, 99.8), (99.8, 99.9, 98.0, 98.1), (98.1, 101.0, 98.05, 100.5)])
    tr = X.simulate_plan(short, xs, NO_FUNDING)
    assert (tr.exit_reason, tr.exit_price) == (T.Exit.STOP, 101.0)                     # 저가 == 98은 목표 아님


def test_gap_through_stop_exits_at_open():
    tr = X.simulate_plan(mk_plan(), xb_rows([PIERCE, (98.5, 98.7, 98.2, 98.4), FLAT]), NO_FUNDING)
    assert (tr.exit_reason, tr.exit_price) == (T.Exit.STOP, 98.5)
    short = mk_plan(side=-1, scenario="S2", entry_price=100.0, stop=101.0, target=98.0)
    tr = X.simulate_plan(short, xb_rows([(99.8, 100.1, 99.7, 99.9), (101.4, 101.6, 101.2, 101.5)]), NO_FUNDING)
    assert (tr.exit_reason, tr.exit_price) == (T.Exit.STOP, 101.4)
    # 지정가 체결 봉 안에서는 손절가 (시가가 손절 아래여도 보수적으로 지정가 체결 → 손절가)
    tr = X.simulate_plan(mk_plan(), xb_rows([(98.5, 98.8, 98.2, 98.6), FLAT]), NO_FUNDING)
    assert (tr.entry_price, tr.exit_price) == (100.0, 99.0) and tr.r_multiple == pytest.approx(-1.0, abs=1e-12)


def test_ioc_fill_bar_open_beyond_stop_exits_at_open():
    ioc = mk_plan(scenario="L1b", order_type="ioc_cap", entry_price=100.1, valid_until=ns("2024-01-01 10:11"))
    tr = X.simulate_plan(ioc, xb_rows([(98.9, 99.2, 98.5, 99.0), FLAT]), NO_FUNDING)
    assert (tr.entry_price, tr.exit_reason, tr.exit_price) == (98.9, T.Exit.STOP, 98.9)
    assert tr.gross_pnl == 0.0                                  # 갭 손절이 이익이 되지 않는다 (I-33)


def test_time_exit_p1_72h_at_open_with_taker_and_slippage():
    n = 72 * 60 + 10
    rows = [PIERCE] + [FLAT] * n
    rows[72 * 60] = (100.35, 100.4, 100.2, 100.3)               # 진입 + 72시간에 시작하는 봉
    tr = X.simulate_plan(mk_plan(), xb_rows(rows), NO_FUNDING)
    assert tr.exit_reason == T.Exit.TIME and tr.exit_time == tr.entry_time + P1_HOLD
    assert tr.exit_price == 100.35
    assert tr.fees == pytest.approx(0.0002 * 100 + 0.0005 * 100.35, abs=1e-12)
    assert tr.slippage == pytest.approx(0.0002 * 100.35, abs=1e-12)
    assert tr.busy_until == tr.exit_time + C.NS_PER_MIN


def test_time_exit_p2_288h_across_5m_to_1m_switch():
    five = make_bars([PIERCE] + [FLAT] * (12 * 100 - 1), start="2023-09-26 00:00", tf="5m")   # 100시간
    one = make_bars([FLAT] * (190 * 60), start="2023-09-30 04:00", tf="1m")
    xb = T.ExecArrays.from_frame(make_exec_bars(five, one))
    plan = mk_plan(signal_time=ns("2023-09-26 00:00"), approval_time=ns("2023-09-26 00:00"),
                   active_from=ns("2023-09-26 00:00"), valid_until=ns("2023-09-27 00:00"), max_hold_ns=P2_HOLD)
    tr = X.simulate_plan(plan, xb, NO_FUNDING)
    assert tr.entry_time == ns("2023-09-26 00:00") and tr.exit_reason == T.Exit.TIME
    assert tr.exit_time == ns("2023-09-26 00:00") + P2_HOLD                           # 1분봉 구간 시가
    assert tr.busy_until == tr.exit_time + C.NS_PER_MIN


def test_eod_exit_at_last_close():
    xb = xb_rows([PIERCE, FLAT, (100.3, 100.6, 100.25, 100.5)])
    tr = X.simulate_plan(mk_plan(), xb, NO_FUNDING)
    assert (tr.exit_reason, tr.exit_price, tr.exit_time) == (T.Exit.EOD, 100.5, ns("2024-01-01 10:13"))
    assert tr.slippage == pytest.approx(0.0002 * 100.5, abs=1e-12)
    assert tr.busy_until == ns("2024-01-01 10:14")


# ---------------------------------------------------------------------------
# 펀딩·R·비용 배수 (§12.2, I-27, I-29, I-35)
# ---------------------------------------------------------------------------


def _funding_xb():
    rows = [FLAT] * 40                                          # 07:50 ~ 08:29
    rows[10] = (100.5, 100.6, 100.4, 100.5)                     # 08:00 봉 시가 100.5 = 펀딩 가격
    return xb_rows(rows, start="2024-01-01 07:50")


def test_funding_window_sign_and_multiplier():
    xb = _funding_xb()
    fa = T.FundingArrays.from_frame(make_funding("2024-01-01 00:00", "2024-01-01 16:00", rate=0.0001))
    t = ns
    pay = 0.0001 * 100.5
    assert X.funding_cost(+1, t("2024-01-01 07:59"), t("2024-01-01 08:10"), xb, fa) == pytest.approx(pay)
    assert X.funding_cost(+1, t("2024-01-01 07:59"), t("2024-01-01 08:00"), xb, fa) == pytest.approx(pay)
    assert X.funding_cost(+1, t("2024-01-01 08:00"), t("2024-01-01 08:10"), xb, fa) == 0.0   # 08:00 봉 진입 → 없음
    assert X.funding_cost(+1, t("2024-01-01 07:50"), t("2024-01-01 07:59"), xb, fa) == 0.0
    assert X.funding_cost(-1, t("2024-01-01 07:59"), t("2024-01-01 08:10"), xb, fa) == pytest.approx(-pay)
    assert X.funding_cost(+1, t("2024-01-01 07:59"), t("2024-01-01 08:10"), xb, fa, 2.0) == pytest.approx(2 * pay)
    assert X.funding_cost(-1, t("2024-01-01 07:59"), t("2024-01-01 08:10"), xb, fa, 2.0) == pytest.approx(-pay)
    neg = T.FundingArrays.from_frame(make_funding("2024-01-01 00:00", "2024-01-01 16:00", rate=-0.0003))
    assert X.funding_cost(+1, t("2024-01-01 07:59"), t("2024-01-01 08:10"), xb, neg, 2.0) == pytest.approx(-0.0003 * 100.5)
    assert X.funding_cost(-1, t("2024-01-01 07:59"), t("2024-01-01 08:10"), xb, neg, 2.0) == pytest.approx(2 * 0.0003 * 100.5)


def test_funding_in_simulate_plan_and_r():
    fa = T.FundingArrays.from_frame(make_funding("2024-01-01 00:00", "2024-01-01 16:00", rate=0.0001))
    rows_stop = xb_rows([PIERCE if i == 9 else STOP_BAR if i == 20 else ((100.5, 100.6, 100.4, 100.5) if i == 10 else FLAT)
                         for i in range(40)], start="2024-01-01 07:50")
    plan = mk_plan(active_from=ns("2024-01-01 07:59"))
    tr = X.simulate_plan(plan, rows_stop, fa)
    assert tr.entry_time == ns("2024-01-01 07:59") and tr.exit_time == ns("2024-01-01 08:10")
    assert tr.funding == pytest.approx(0.0001 * 100.5, abs=1e-15)
    assert tr.r_multiple == pytest.approx(-1.0 - tr.funding / RISK_100_99_LIMIT, abs=1e-12)
    late = X.simulate_plan(mk_plan(active_from=ns("2024-01-01 08:00")), xb_rows(
        [FLAT] * 10 + [(100.3, 100.4, 99.95, 100.3)] + [STOP_BAR] * 3, start="2024-01-01 07:50"), fa)
    assert late.entry_time == ns("2024-01-01 08:00") and late.funding == 0.0


def test_r_multiple_hand_computed_and_cost_multiplier():
    xb_stop = xb_rows([PIERCE, STOP_BAR, FLAT])
    tr = X.simulate_plan(mk_plan(), xb_stop, NO_FUNDING)
    assert tr.risk_per_unit == pytest.approx(RISK_100_99_LIMIT, abs=1e-12)
    assert tr.fees == pytest.approx(0.02 + 0.0495, abs=1e-12) and tr.slippage == pytest.approx(0.0198, abs=1e-12)
    assert tr.net_pnl == pytest.approx(-1.0893, abs=1e-12)
    assert tr.r_multiple == pytest.approx(-1.0, abs=1e-12)                      # 기본 비용 손절 = −1R
    tr2 = X.simulate_plan(mk_plan(), xb_stop, NO_FUNDING, cost_multiplier=2.0)
    assert tr2.risk_per_unit == tr.risk_per_unit                               # 분모는 기본 비용 (I-29)
    assert tr2.r_multiple == pytest.approx((-1.0 - 2 * 0.0893) / 1.0893, abs=1e-12)
    xb_tgt = xb_rows([PIERCE, (100.3, 102.2, 100.2, 102.1), FLAT])
    tr = X.simulate_plan(mk_plan(), xb_tgt, NO_FUNDING)
    assert tr.fees == pytest.approx(0.0002 * 100 + 0.0002 * 102, abs=1e-12) and tr.slippage == 0.0
    assert tr.r_multiple == pytest.approx((2 - 0.0404) / 1.0893, abs=1e-12)   # = 1.79895… = 순손익비
    assert tr.r_multiple == pytest.approx(C.net_rr(1, 100.0, 99.0, 102.0, C.FEE_MAKER), abs=1e-12)
    tr2 = X.simulate_plan(mk_plan(), xb_tgt, NO_FUNDING, cost_multiplier=2.0)
    assert tr2.r_multiple == pytest.approx((2 - 0.0808) / 1.0893, abs=1e-12)
    assert tr2.cost_multiplier == 2.0 and tr.cost_multiplier == 1.0


def test_size_fraction():
    tr = X.simulate_plan(mk_plan(stop=99.6, target=101.0), xb_rows([PIERCE, FLAT]), NO_FUNDING)
    assert tr.risk_per_unit == pytest.approx(0.4 + 0.02 + 0.0007 * 99.6, abs=1e-12)   # 0.48972
    assert tr.size_fraction == pytest.approx(0.6 * 0.48972 / (0.005 * 100), abs=1e-12)  # 0.587664
    wide = X.simulate_plan(mk_plan(stop=95.0, target=110.0), xb_rows([PIERCE, FLAT]), NO_FUNDING)
    assert wide.size_fraction == 1.0
    assert tr.r_account == pytest.approx(tr.size_fraction * tr.r_multiple)


def test_ioc_r_denominator_uses_actual_fill_stop_is_minus_one_r():
    """검토 F1 회귀: L1b 상한 IOC가 상한보다 낮은 시가에 체결되면 R 분모는 실제 체결가 기준 → 갭 없는 손절 = 정확히 −1R.
    (수정 전: 상한가 기준 분모라 −0.72R처럼 손실이 작게 기록됐다.) 수량(size_fraction)은 계획(상한가) 기준 그대로."""
    ioc = mk_plan(scenario="L1b", order_type="ioc_cap", entry_price=100.6, stop=99.0, target=103.0,
                  valid_until=ns("2024-01-01 10:11"))
    xb = xb_rows([(100.2, 100.3, 100.1, 100.2), (100.2, 100.25, 98.9, 99.1), FLAT])   # 시가 100.2 체결 → 다음 봉 손절
    tr = X.simulate_plan(ioc, xb, NO_FUNDING)
    assert (tr.entry_price, tr.exit_reason, tr.exit_price) == (100.2, T.Exit.STOP, 99.0)
    risk = 1.2 + 0.0005 * 100.2 + 0.0007 * 99.0
    assert tr.risk_per_unit == pytest.approx(risk, abs=1e-12)
    assert tr.r_multiple == pytest.approx(-1.0, abs=1e-12)
    plan_risk = 1.6 + 0.0005 * 100.6 + 0.0007 * 99.0
    assert tr.size_fraction == pytest.approx(min(1.0, 0.6 * plan_risk / (0.005 * 100.6)), abs=1e-12)
    tr2 = X.simulate_plan(ioc, xb, NO_FUNDING, cost_multiplier=2.0)
    assert tr2.risk_per_unit == tr.risk_per_unit                                  # 분모는 기본 비용 (I-27)
    assert tr2.r_multiple == pytest.approx(-(1.2 + 2 * (risk - 1.2)) / risk, abs=1e-12)
    miss = X.simulate_plan(ioc, xb_rows([(100.7, 100.8, 100.6, 100.7)]), NO_FUNDING)
    assert miss.status == T.Status.NOT_FILLED and miss.risk_per_unit == pytest.approx(plan_risk, abs=1e-12)


def test_open_fill_funding_counts_from_activation_in_5m_era():
    """검토 F3 회귀: 5분봉 구간에서 활성 07:56 → 08:00 봉 시가 체결인 IOC·시장가는 08:00 펀딩을 낸다(활성 < f ≤ 청산).
    지정가는 08:00 봉에서 관통 체결돼도 08:00 전에 포지션이 없으므로 내지 않는다(진입 봉 시작 < f). 1분봉 구간은 활성 = 진입."""
    rows = [FLAT] * 30
    rows[1] = (100.3, 100.4, 99.95, 100.3)                       # 08:00 봉 (시가 100.3 = 펀딩 가격)
    xb = xb_rows(rows, start="2023-06-01 07:55", tf="5m")
    fa = T.FundingArrays(time_ns=np.array([ns("2023-06-01 08:00")], dtype=np.int64), rate=np.array([0.0003]))
    common = dict(signal_time=ns("2023-06-01 07:45"), approval_time=ns("2023-06-01 07:46"),
                  active_from=ns("2023-06-01 07:56"))
    ioc = X.simulate_plan(mk_plan(scenario="L1b", order_type="ioc_cap", entry_price=100.4,
                                  valid_until=ns("2023-06-01 07:56"), **common), xb, fa)
    mkt = X.simulate_plan(mk_plan(order_type="market", entry_price=100.3, valid_until=ns("2023-06-01 07:56"),
                                  **common), xb, fa)
    lim = X.simulate_plan(mk_plan(valid_until=ns("2023-06-01 10:00"), **common), xb, fa)
    for tr in (ioc, mkt, lim):
        assert tr.entry_time == ns("2023-06-01 08:00") and tr.exit_reason == T.Exit.EOD
    assert ioc.funding == pytest.approx(0.0003 * 100.3, abs=1e-15)
    assert mkt.funding == pytest.approx(0.0003 * 100.3, abs=1e-15)
    assert lim.funding == 0.0
    assert X.funding_start("ioc_cap", ns("2023-06-01 08:00"), ns("2023-06-01 07:56")) == ns("2023-06-01 07:56")
    assert X.funding_start("limit", ns("2023-06-01 08:00"), ns("2023-06-01 07:56")) == ns("2023-06-01 08:00")


def test_marketable_limit_is_flagged_but_filled_per_spec():
    """검토 LA-2·F4: 활성 뒤 첫 봉 시가가 이미 지정가 너머인 지정가는 §12.1대로 지정가·메이커로 체결하고(동작 불변),
    meta에 첫 봉 시가와 원가 차이(R, 양수 = 엔진이 유리)를 남긴다. 둘째 봉 이후의 관통 체결은 표시하지 않는다."""
    near = X.simulate_plan(mk_plan(), xb_rows([(99.99, 100.2, 99.9, 100.1), FLAT]), NO_FUNDING)   # 0.01 아래 시가
    assert near.entry_price == 100.0 and near.fees == pytest.approx(0.0002 * 100.0 + 0.0005 * 100.3, abs=1e-12)
    edge = 99.99 * 1.0005 - 100.0 * 1.0002                        # 테이커 즉시 체결 원가 − 엔진 원가 = +0.019995
    assert near.meta["marketable_open"] == 99.99
    assert near.meta["marketable_edge_r"] == pytest.approx(edge / RISK_100_99_LIMIT, abs=1e-12)
    far = X.simulate_plan(mk_plan(), xb_rows([(99.5, 100.2, 99.4, 100.1), FLAT]), NO_FUNDING)      # 크게 아래 → 엔진 불리
    assert far.meta["marketable_edge_r"] < 0
    short = X.simulate_plan(mk_plan(side=-1, scenario="S2", entry_price=100.0, stop=101.0, target=98.0),
                            xb_rows([(100.02, 100.1, 99.9, 100.0), FLAT]), NO_FUNDING)
    assert short.meta["marketable_edge_r"] == pytest.approx(
        (100.0 * 0.9998 - 100.02 * 0.9995) / (1.0 + 0.0002 * 100.0 + 0.0007 * 101.0), abs=1e-12)
    later = X.simulate_plan(mk_plan(), xb_rows([FLAT, PIERCE, FLAT]), NO_FUNDING)
    assert later.is_filled and "marketable_open" not in later.meta


# ---------------------------------------------------------------------------
# 리스크 검사 (§8.1, §12.2)
# ---------------------------------------------------------------------------


def test_stop_band_boundaries():
    assert X.stop_band_ok(100.0, 99.6, 0.3)          # d 0.4 = max(0.4%, ATR 0.3) → 통과(경계 포함)
    assert not X.stop_band_ok(100.0, 99.61, 0.3)     # d 0.39
    assert X.stop_band_ok(100.0, 99.1, 0.3)          # d 0.9 = min(2%, 3 × 0.3) → 통과
    assert not X.stop_band_ok(100.0, 99.09, 0.3)     # d 0.91
    assert X.stop_band_ok(100.0, 100.4, 0.3)         # 숏 방향도 |d|
    assert not X.stop_band_ok(100.0, 99.0, float("nan"))
    ok = X.stop_band_ok(np.array([100.0, 100.0]), np.array([99.6, 99.61]), np.array([0.3, 0.3]))
    np.testing.assert_array_equal(ok, [True, False])
    assert X.stop_band_ok(100.0, 98.0, 1.0) and not X.stop_band_ok(100.0, 97.9, 1.0)   # 2% 상한


def test_risk_reasons_codes():
    assert X.risk_reasons(1, 100.0, 99.0, 102.0, 0.5, "limit") == ()                      # 순손익비 1.79895
    assert X.risk_reasons(1, 100.0, 99.0, 101.5, 0.5, "limit") == (T.Reason.RISK_RR,)     # 1.34003
    assert X.risk_reasons(1, 100.0, 99.61, 101.5, 0.3, "limit") == (T.Reason.RISK_STOP_BAND,)
    assert X.risk_reasons(1, 100.0, 99.61, 100.2, 0.3, "limit") == (T.Reason.RISK_STOP_BAND, T.Reason.RISK_RR)
    assert X.risk_reasons(-1, 100.0, 101.0, 98.0, 0.5, "limit") == ()
    assert X.risk_reasons(-1, 100.0, 101.0, 102.0, 0.5, "limit") == (T.Reason.RISK_RR,)  # 목표가 반대편
    # IOC는 테이커 진입 수수료로 계산 → 같은 가격에서 순손익비가 더 낮다
    rr_ioc = C.net_rr(1, 100.0, 99.0, 101.7, C.FEE_TAKER)   # 1.4560
    rr_lim = C.net_rr(1, 100.0, 99.0, 101.7, C.FEE_MAKER)   # 1.5236
    assert rr_ioc < 1.5 <= rr_lim
    assert X.risk_reasons(1, 100.0, 99.0, 101.7, 0.5, "limit") == ()
    assert X.risk_reasons(1, 100.0, 99.0, 101.7, 0.5, "ioc_cap") == (T.Reason.RISK_RR,)


# ---------------------------------------------------------------------------
# 순차 처리: F9·F8·가용성 마스크 (§12.3, I-19, I-20, I-38)
# ---------------------------------------------------------------------------


def _hourly_market(hours: int, start="2024-01-01 10:00", pierce_min=11, stop_min=20) -> T.ExecArrays:
    """매시 pierce_min분 봉은 매수 체결, stop_min분 봉은 손절(99)에 닿는 1분봉."""
    rows = []
    for _ in range(hours):
        for minute in range(60):
            rows.append(PIERCE if minute == pierce_min else STOP_BAR if minute == stop_min else FLAT)
    return xb_rows(rows, start=start)


CFG_EXEC = C.ComboConfig("L1a", "DA", "P1")
CFG_ALL = CFG_EXEC.replace(apply_availability_mask=False)


def test_f9_blocks_while_position_open_allows_at_busy_until():
    xb = _hourly_market(4)
    a = hourly_plan("2024-01-01 10:00")                              # 10:11 체결 → 10:20 손절, 봉 끝 10:21
    b = hourly_plan("2024-01-01 10:00", plan_id="b", approval_time=ns("2024-01-01 10:20"),
                    active_from=ns("2024-01-01 10:30"))
    c = hourly_plan("2024-01-01 10:00", plan_id="c", approval_time=ns("2024-01-01 10:21"),
                    active_from=ns("2024-01-01 10:31"))
    trades, logs = X.run_sequence([mk_cand(a), mk_cand(b), mk_cand(c)], xb, NO_FUNDING, CFG_ALL)
    assert trades[0].busy_until == ns("2024-01-01 10:21") and trades[0].exit_reason == T.Exit.STOP
    assert [lg.status for lg in logs] == ["passed", "discarded", "passed"]
    assert logs[1].reasons == (T.Reason.F9,) and logs[1].plan_id == "b"
    assert [t.plan_id for t in trades] == ["L1a_2024-01-01 10:00", "c"]


def test_f9_pending_order_blocks_until_expiry():
    xb = xb_rows([FLAT] * 180, start="2024-01-01 10:00")
    a = hourly_plan("2024-01-01 10:00", valid_until=ns("2024-01-01 12:00"))  # 체결 없음 → 12:00 만료
    b = hourly_plan("2024-01-01 11:00", plan_id="b")
    c = hourly_plan("2024-01-01 11:59", plan_id="c", approval_time=ns("2024-01-01 12:00"))  # 만료와 같은 시각
    trades, logs = X.run_sequence([mk_cand(a), mk_cand(b), mk_cand(c)], xb, NO_FUNDING, CFG_ALL)
    assert trades[0].status == T.Status.EXPIRED and trades[0].busy_until == ns("2024-01-01 12:00")
    assert logs[1].reasons == (T.Reason.F9,) and logs[2].status == "passed"


def test_f8_after_two_stops_of_same_madi():
    xb = _hourly_market(6)
    m = "1hU-202401010500"
    a = hourly_plan("2024-01-01 10:00", plan_id="a", madi_id=m)       # 손절 (봉 끝 10:21)
    b = hourly_plan("2024-01-01 11:00", plan_id="b", madi_id=m)       # 손절 (봉 끝 11:21)
    c = hourly_plan("2024-01-01 11:00", plan_id="c", madi_id=m, approval_time=ns("2024-01-01 11:15"),
                    active_from=ns("2024-01-01 11:25"))               # 11:21 손절은 아직 안 셈 → F9만
    d = hourly_plan("2024-01-01 12:00", plan_id="d", madi_id=m)       # 손절 2회 → F8
    e = hourly_plan("2024-01-01 13:00", plan_id="e", madi_id=None)    # 마디 없음 → F8 없음
    f = hourly_plan("2024-01-01 14:00", plan_id="f", madi_id="1hU-OTHER")
    trades, logs = X.run_sequence([mk_cand(p) for p in (a, b, c, d, e, f)], xb, NO_FUNDING, CFG_ALL)
    assert [lg.reasons for lg in logs] == [(), (), (T.Reason.F9,), (T.Reason.F8,), (), ()]
    assert [t.plan_id for t in trades] == ["a", "b", "e", "f"]
    assert all(t.exit_reason == T.Exit.STOP for t in trades)


def _mask_plan(hhmm: str, pid: str) -> T.Plan:
    t = ns(hhmm)
    return mk_plan(plan_id=pid, signal_time=t - C.NS_PER_MIN, approval_time=t, active_from=t + C.NS_PER_MIN,
                   valid_until=t + 2 * C.NS_PER_MIN)          # 체결 없이 2분 뒤 만료 → 서로 막지 않음


def test_availability_mask_dnd_and_daily_cap():
    xb = xb_rows([FLAT] * (26 * 60), start="2024-01-01 15:00")
    times = ["2024-01-01 15:30", "2024-01-01 16:01", "2024-01-01 22:20",   # KST 00:30, 01:01, 07:20 → 방해 금지
             "2024-01-01 22:30",                                              # KST 07:30 → 통과
             "2024-01-01 23:01", "2024-01-02 00:01", "2024-01-02 01:01", "2024-01-02 02:01", "2024-01-02 03:01",
             "2024-01-02 04:01",                                              # 그날 7번째 요청 → 초과
             "2024-01-02 14:59",                                              # KST 23:59 같은 날 → 초과
             "2024-01-02 15:05"]                                              # KST 다음 날 00:05 → 통과
    cands = [mk_cand(_mask_plan(t, f"p{i}")) for i, t in enumerate(times)]
    trades, logs = X.run_sequence(cands, xb, NO_FUNDING, CFG_EXEC)
    dnd, cap = (T.Reason.MASK_DND,), (T.Reason.MASK_DAILY_CAP,)
    assert [lg.reasons for lg in logs] == [dnd, dnd, dnd] + [()] * 6 + [cap, cap, ()]
    assert len(trades) == 7
    trades_all, logs_all = X.run_sequence(cands, xb, NO_FUNDING, CFG_ALL)   # 전체 모드: 마스크 무시
    assert all(lg.status == "passed" for lg in logs_all) and len(trades_all) == len(times)


def test_daily_cap_counts_only_sent_requests():
    xb = xb_rows([FLAT] * (12 * 60), start="2024-01-01 22:00")
    first = _mask_plan("2024-01-01 22:30", "p0")
    first = dataclasses.replace(first, valid_until=ns("2024-01-02 00:40"))  # 대기 주문이 00:40까지 자리 차지
    times = ["2024-01-01 23:01", "2024-01-01 23:31", "2024-01-02 00:01",     # F9 (요청 안 보냄)
             "2024-01-02 01:01", "2024-01-02 02:01", "2024-01-02 03:01", "2024-01-02 04:01", "2024-01-02 05:01",
             "2024-01-02 06:01"]
    cands = [mk_cand(first)] + [mk_cand(_mask_plan(t, f"p{i + 1}")) for i, t in enumerate(times)]
    _, logs = X.run_sequence(cands, xb, NO_FUNDING, CFG_EXEC)
    f9 = (T.Reason.F9,)
    assert [lg.reasons for lg in logs] == [()] + [f9] * 3 + [()] * 5 + [(T.Reason.MASK_DAILY_CAP,)]


def test_multiple_sequential_reasons_are_all_recorded():
    xb = xb_rows([FLAT] * (4 * 60), start="2024-01-01 15:00")
    a = _mask_plan("2024-01-01 15:10", "a")                      # KST 00:10 → 통과, 17:10까지 대기
    a = dataclasses.replace(a, valid_until=ns("2024-01-01 17:10"))
    b = _mask_plan("2024-01-01 15:40", "b")                      # 대기 중 + 방해 금지
    _, logs = X.run_sequence([mk_cand(a), mk_cand(b)], xb, NO_FUNDING, CFG_EXEC)
    assert logs[1].reasons == (T.Reason.F9, T.Reason.MASK_DND) and logs[1].reason == T.Reason.F9


def test_precomputed_reasons_logged_unchanged_and_order_kept():
    xb = _hourly_market(3)
    p_ok = hourly_plan("2024-01-01 10:00", plan_id="ok")
    p_f1 = hourly_plan("2024-01-01 10:00", plan_id="f1")
    warm = T.Candidate(log=T.SignalLog(time=ns("2024-01-01 09:01"), signal_time=ns("2024-01-01 09:00"),
                                       scenario="L1a", side=1, status="discarded", reasons=("WARMUP",)))
    c_f1 = mk_cand(p_f1, reasons=("F1", "RISK_RR"))
    cands = [warm, c_f1, mk_cand(p_ok)]
    trades, logs = X.run_sequence(cands, xb, NO_FUNDING, CFG_EXEC)
    assert logs[0] is warm.log and logs[1] is c_f1.log                      # 그대로 기록
    assert logs[2].status == "passed" and [t.plan_id for t in trades] == ["ok"]
    assert len(logs) == len(cands)


def test_unsorted_candidates_raise():
    xb = _hourly_market(3)
    late = hourly_plan("2024-01-01 11:00", plan_id="late")
    early = hourly_plan("2024-01-01 10:00", plan_id="early")
    with pytest.raises(ValueError):
        X.run_sequence([mk_cand(late), mk_cand(early)], xb, NO_FUNDING, CFG_ALL)


def test_cost_multiplier_keeps_trade_set():
    xb = _hourly_market(5)
    cands = [mk_cand(hourly_plan(f"2024-01-01 {h}:00", plan_id=f"h{h}")) for h in (10, 11, 12, 13)]
    base, _ = X.run_sequence(cands, xb, NO_FUNDING, CFG_EXEC)
    dbl, _ = X.run_sequence(cands, xb, NO_FUNDING, CFG_EXEC.replace(cost_multiplier=2.0))
    assert [(t.entry_time, t.exit_time, t.exit_reason) for t in base] == \
           [(t.entry_time, t.exit_time, t.exit_reason) for t in dbl]
    assert all(d.r_multiple < b.r_multiple for b, d in zip(base, dbl))


# ---------------------------------------------------------------------------
# 문장 그대로의 느린 참조 구현과 무작위 대조 (경계 동률이 자주 나는 정수 격자 가격)
# ---------------------------------------------------------------------------


def _grid_bars(n, seed, start, tf):
    rng = np.random.default_rng(seed)
    c = 1000 + np.cumsum(rng.integers(-3, 4, n))
    o = np.r_[1000, c[:-1]] + rng.integers(-2, 3, n)            # 가끔 갭
    h = np.maximum(o, c) + rng.integers(0, 3, n)
    lo = np.minimum(o, c) - rng.integers(0, 3, n)
    return make_bars(np.c_[o, h, lo, c].astype(np.float64), start=start, tf=tf)


def _ref_exit(side, e, stop, target, tl, otype, xb):
    n = len(xb)
    for j in range(e, n):
        if j > e and xb.open_ns[j] >= tl:
            return j, xb.open[j], "time"
        o, hi, lo = xb.open[j], xb.high[j], xb.low[j]
        if (lo <= stop) if side > 0 else (hi >= stop):
            px = stop
            if j > e or otype in ("ioc_cap", "market"):
                px = min(stop, o) if side > 0 else max(stop, o)
            return j, px, "stop"
        if j > e and ((hi > target) if side > 0 else (lo < target)):
            return j, target, "target"
    return n - 1, xb.close[n - 1], "eod"


def _ref_simulate(p: T.Plan, xb: T.ExecArrays, fa: T.FundingArrays, m: float) -> dict:
    n = len(xb)
    starts = [j for j in range(n) if xb.open_ns[j] >= p.active_from]
    if not starts:
        return dict(status="not_filled", busy=p.active_from)
    j0 = starts[0]
    fill = None
    if p.order_type == "limit":
        end = p.valid_until if p.cancel_effective_time is None else min(p.valid_until, p.cancel_effective_time)
        for j in range(j0, n):
            if xb.close_ns[j] > end:
                break
            if (xb.low[j] < p.entry_price) if p.side > 0 else (xb.high[j] > p.entry_price):
                fill = (j, p.entry_price)
                break
        if fill is None:
            cancelled = p.cancel_effective_time is not None and p.cancel_effective_time < p.valid_until
            return dict(status="cancelled" if cancelled else "expired", busy=end)
    elif p.order_type == "ioc_cap":
        o = xb.open[j0]
        if (o <= p.entry_price) if p.side > 0 else (o >= p.entry_price):
            fill = (j0, o)
        else:
            return dict(status="not_filled", busy=xb.close_ns[j0])
    else:
        fill = (j0, xb.open[j0])
    ej, ep = fill
    et = xb.open_ns[ej]
    xj, xp, why = _ref_exit(p.side, ej, p.stop, p.target, et + p.max_hold_ns, p.order_type, xb)
    xt = xb.open_ns[xj]
    er = C.FEE_MAKER if p.order_type == "limit" else C.FEE_TAKER
    xr = C.FEE_MAKER if why == "target" else C.FEE_TAKER
    fees = (er * ep + xr * xp) * m
    slip = 0.0 if why == "target" else C.SLIPPAGE * xp * m
    fund = 0.0
    f_lo = et if p.order_type == "limit" else min(et, p.active_from)   # 시가 체결 주문은 활성 시각부터 (I-35)
    for f, rate in zip(fa.time_ns, fa.rate):
        if f_lo < f <= xt:
            jf = max(j for j in range(n) if xb.open_ns[j] <= f)
            x = p.side * rate * xb.open[jf]
            fund += x * m if x > 0 else x
    net = p.side * (xp - ep) - fees - slip - fund
    risk = abs(ep - p.stop) + er * ep + (C.FEE_TAKER + C.SLIPPAGE) * p.stop     # §12.2 진입가 = 실제 체결가 (I-29)
    return dict(status="filled", busy=xb.close_ns[xj], entry_time=et, entry_price=ep, exit_time=xt,
                exit_price=xp, exit_reason=why, r=net / risk, funding=fund)


def _random_plans(xb: T.ExecArrays, rng: np.random.Generator, k: int) -> list[T.Plan]:
    plans = []
    n = len(xb)
    for i in range(k):
        side = int(rng.choice([1, -1]))
        otype = str(rng.choice(["limit", "limit", "ioc_cap", "market"]))
        j = int(rng.integers(0, n - 50))
        ref = float(xb.close[j])
        entry = ref - side * float(rng.integers(0, 6)) if otype == "limit" else ref + side * float(rng.integers(0, 3))
        wide = rng.random() < 0.3                               # 넓은 손절·목표 → 512봉을 넘는 보유·데이터 끝
        stop = entry - side * float(rng.integers(40, 120) if wide else rng.integers(2, 15))
        target = entry + side * float(rng.integers(60, 250) if wide else rng.integers(2, 40))
        active = int(xb.open_ns[j]) + int(rng.integers(-3, 400)) * C.NS_PER_MIN
        valid = active + int(rng.integers(0, 600)) * C.NS_PER_MIN if otype == "limit" else active
        cet = None
        if otype == "limit" and rng.random() < 0.4:
            cet = active + int(rng.integers(0, 700)) * C.NS_PER_MIN
        plans.append(T.Plan(plan_id=f"r{i}", scenario="L1a", side=side, signal_time=active - 11 * C.NS_PER_MIN,
                            approval_time=active - 10 * C.NS_PER_MIN, active_from=active, order_type=otype,
                            entry_price=entry, stop=stop, target=target, valid_until=valid,
                            max_hold_ns=int(rng.integers(1, 3000)) * C.NS_PER_MIN, atr_at_signal=1.0,
                            cancel_effective_time=cet, cancel_reason="close_below" if cet else None))
    return plans


@pytest.fixture(scope="module")
def mixed_market():
    five = _grid_bars(1500, 1, "2023-09-25 19:00", "5m")          # 5분봉 → 2023-10-01 00:00에 1분봉으로
    one = _grid_bars(2500, 2, "2023-10-01 00:00", "1m")
    xb = T.ExecArrays.from_frame(make_exec_bars(five, one))
    rng = np.random.default_rng(3)
    ft = make_funding("2023-09-25 19:00", "2023-10-03 00:00")
    fa = T.FundingArrays(time_ns=ft["time_ns"].to_numpy(), rate=rng.normal(0.0, 0.0005, len(ft)))
    return xb, fa


@pytest.mark.parametrize("window,growth", [(X.SCAN_WINDOW, X.SCAN_GROWTH), (2, 2)])
def test_simulate_plan_matches_literal_reference(mixed_market, monkeypatch, window, growth):
    monkeypatch.setattr(X, "SCAN_WINDOW", window)          # 작은 창으로 여러 창에 걸친 탐색도 검사
    monkeypatch.setattr(X, "SCAN_GROWTH", growth)
    xb, fa = mixed_market
    rng = np.random.default_rng(11)
    counts = {}
    for p in _random_plans(xb, rng, 250):
        for m in (1.0, 2.0):
            got = X.simulate_plan(p, xb, fa, m)
            ref = _ref_simulate(p, xb, fa, m)
            assert got.status == ref["status"], p
            assert got.busy_until == ref["busy"], p
            counts[got.exit_reason or got.status] = counts.get(got.exit_reason or got.status, 0) + 1
            if ref["status"] != "filled":
                continue
            assert (got.entry_time, got.exit_time, got.exit_reason) == \
                   (ref["entry_time"], ref["exit_time"], ref["exit_reason"]), p
            assert got.entry_price == ref["entry_price"] and got.exit_price == ref["exit_price"]
            assert got.funding == pytest.approx(ref["funding"], abs=1e-9)
            assert got.r_multiple == pytest.approx(ref["r"], abs=1e-9)
    for key in ("stop", "target", "time", "eod", "expired", "cancelled", "not_filled"):   # 모든 갈래가 나왔는지
        assert counts.get(key, 0) > 0, counts


def test_funding_cost_many_matches_single(mixed_market):
    xb, fa = mixed_market
    rng = np.random.default_rng(5)
    k = 300
    side = rng.choice([1, -1], k)
    a = rng.integers(0, len(xb) - 1, k)
    b = np.minimum(a + rng.integers(0, 2000, k), len(xb) - 1)
    et, xt = xb.open_ns[a], xb.open_ns[b]
    for m in (1.0, 2.0):
        many = X.funding_cost_many(side, et, xt, xb, fa, m)
        single = [X.funding_cost(int(s), int(e), int(x), xb, fa, m) for s, e, x in zip(side, et, xt)]
        np.testing.assert_allclose(many, single, rtol=0, atol=1e-9)


def test_deterministic_same_input_same_output(mixed_market):
    xb, fa = mixed_market
    plans = sorted(_random_plans(xb, np.random.default_rng(21), 120), key=lambda p: (p.approval_time, p.plan_id))
    cands = [mk_cand(p) for p in plans]
    r1 = X.run_sequence(cands, xb, fa, CFG_ALL)
    r2 = X.run_sequence(cands, xb, fa, CFG_ALL)
    assert T.records_frame(r1[0]).equals(T.records_frame(r2[0]))
    assert T.records_frame(r1[1]).equals(T.records_frame(r2[1]))
    assert any(lg.reasons == (T.Reason.F9,) for lg in r1[1])       # 겹침이 실제로 일어난 사례


def _scramble(xb: T.ExecArrays, lo: int, hi: int, rng: np.random.Generator) -> T.ExecArrays:
    """봉 [lo, hi)의 가격을 무작위로 바꾼 복사본 (OHLC 논리는 유지)."""
    arrs = {f: getattr(xb, f).copy() for f in ("open", "high", "low", "close")}
    k = hi - lo
    if k > 0:
        o, c = rng.uniform(900, 1100, k), rng.uniform(900, 1100, k)
        arrs["open"][lo:hi], arrs["close"][lo:hi] = o, c
        arrs["high"][lo:hi] = np.maximum(o, c) + rng.uniform(0, 20, k)
        arrs["low"][lo:hi] = np.minimum(o, c) - rng.uniform(0, 20, k)
    return T.ExecArrays(open_ns=xb.open_ns, close_ns=xb.close_ns, **arrs)


def test_no_lookahead_bars_after_exit_or_before_activation_irrelevant(mixed_market):
    """청산 봉(미체결이면 주문 끝) 뒤의 봉과 활성 시각 전에 시작한 봉을 바꿔도 결과가 같다 (C-7, C-8, T-NLA 5)."""
    xb, fa = mixed_market
    rng = np.random.default_rng(31)
    n_filled = 0
    for p in _random_plans(xb, rng, 150):
        base = X.simulate_plan(p, xb, fa)
        if base.is_filled:
            cut = int(np.searchsorted(xb.open_ns, base.exit_time)) + 1
            n_filled += 1
        else:
            cut = int(np.searchsorted(xb.close_ns, base.busy_until, side="right"))
        j0 = int(np.searchsorted(xb.open_ns, p.active_from))
        changed = _scramble(_scramble(xb, cut, len(xb), rng), 0, min(j0, len(xb)), rng)
        again = X.simulate_plan(p, changed, fa)
        assert T.records_frame([base]).equals(T.records_frame([again])), p
    assert n_filled > 50


def test_empty_limit_window_expires_at_order_end():
    xb = xb_rows([PIERCE] * 5)                                  # 10:11~ 1분봉, 모두 관통
    p = mk_plan(valid_until=ns("2024-01-01 10:11") + 30 * C.NS_PER_SEC)   # 첫 봉(10:12 마감)도 수명 밖
    assert X.entry_window(p, xb) == (0, 0)
    tr = X.simulate_plan(p, xb, NO_FUNDING)
    assert tr.status == T.Status.EXPIRED and tr.busy_until == p.valid_until


def test_invalid_plan_rejected():
    xb = xb_rows([FLAT])
    with pytest.raises(ValueError):
        X.simulate_plan(mk_plan(order_type="stop"), xb, NO_FUNDING)
    with pytest.raises(ValueError):
        X.simulate_plan(mk_plan(side=0), xb, NO_FUNDING)
