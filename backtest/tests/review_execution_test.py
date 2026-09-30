"""적대적 리뷰 테스트 — 체결·비용·통계 감사 (리뷰어 작성, 제품 코드는 고치지 않음).

기준: docs/RULES_SPEC.md v1.0 §8·§12 (특히 §12.1~§12.4). 설계 해석 번호(I-n)는 backtest/DESIGN.md §7.

구성
- test_hand_*    : 손으로 계산한 작은 사례. 명세와 같아야 하는 동작 → 통과해야 한다.
- test_finding_* : 성과를 부풀릴 수 있는 가정을 숫자로 고정한 "기록" 테스트(현재 동작을 문서화, 통과).
- xfail(strict)  : 가장 보수적인 해석과 다른 곳. 고치면 XPASS → strict 실패로 알려 준다(그때 표시를 지운다).
- test_real_*    : 실데이터 전체(16조합 × 전체/실행 가능/비용 2배)를 명세 문장에서 따로 짠 참조 구현으로
                   다시 계산해 한 건도 어긋나지 않는지 본다(@slow). 성과 숫자(평균 R 등)는 보지 않는다.

숫자는 일부러 config를 거치지 않고 명세 값을 손으로 다시 적었다(MAKER·TAKER·SLIP) — config가 틀려도 잡히게.
"""
from __future__ import annotations

import collections
import dataclasses

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import execution as X
from backtest import random_baseline as RB
from backtest import types as T
from backtest.tests.conftest import make_bars, make_exec_bars, ns

# §8.2·§12.2 명세 값 (손으로 다시 적음)
MAKER = 0.0002
TAKER = 0.0005
SLIP = 0.0002
H72 = 72 * 3600 * 10**9                     # P1 시간 청산: 1시간봉 72개
NO_FUNDING = T.FundingArrays(time_ns=np.array([], dtype=np.int64), rate=np.array([], dtype=np.float64))

# 기본 롱 계획 값: 진입 30000.0, 손절 29850.0(d = 150), 목표 30400.0
# 손 계산: c_stop = 0.0002×30000 + (0.0005 + 0.0002)×29850 = 6.0 + 20.895 = 26.895 → R 분모 = 176.895
RISK_LONG_LIMIT = 150.0 + 6.0 + 20.895


def xb_of(rows, start, tf="1m") -> T.ExecArrays:
    """(시가, 고가, 저가, 종가) 목록 → 실행 봉 배열."""
    return T.ExecArrays.from_frame(make_bars([tuple(r) for r in rows], start=start, tf=tf))


def fund(pairs) -> T.FundingArrays:
    """[(시각, 비율), …] → 펀딩 배열."""
    return T.FundingArrays(time_ns=np.array([ns(a) for a, _ in pairs], dtype=np.int64),
                           rate=np.array([b for _, b in pairs], dtype=np.float64))


def plan(**kw) -> T.Plan:
    """기본: L1a 롱 지정가 30000 / 손절 29850 / 목표 30400, 07:56부터 활성(1분봉 구간)."""
    base = dict(plan_id="REV", scenario="L1a", side=1, signal_time=ns("2024-01-01 07:45"),
                approval_time=ns("2024-01-01 07:46"), active_from=ns("2024-01-01 07:56"), order_type="limit",
                entry_price=30000.0, stop=29850.0, target=30400.0, valid_until=ns("2024-01-02 07:45"),
                max_hold_ns=H72, atr_at_signal=100.0)
    base.update(kw)
    return T.Plan(**base)


def cand(p: T.Plan) -> T.Candidate:
    log = T.SignalLog(time=p.approval_time, signal_time=p.signal_time, scenario=p.scenario, side=p.side,
                      status="passed", plan_id=p.plan_id, madi_id=p.madi_id, meta={"tb_close_ns": 0})
    return T.Candidate(log=log, plan=p)


# ---------------------------------------------------------------------------
# 0. 명세 숫자 (§8.1, §8.2, §8.3, §12.2, §12.3)
# ---------------------------------------------------------------------------


def test_hand_spec_constants():
    assert (C.FEE_MAKER, C.FEE_TAKER, C.SLIPPAGE) == (MAKER, TAKER, SLIP)
    assert (C.MIN_NET_RR, C.STOP_MIN_PCT, C.STOP_MAX_PCT, C.STOP_MIN_ATR, C.STOP_MAX_ATR) == (1.5, 0.004, 0.02, 1.0, 3.0)
    assert (C.MAX_HOLD_BARS, C.LATENCY_DEFAULT_MIN, C.AVAIL_DELAY_NS) == (72, 10, 60 * 10**9)
    assert (C.DND_START_MIN_KST, C.DND_END_MIN_KST, C.DAILY_APPROVAL_CAP, C.KST_OFFSET_NS) == (30, 450, 6, 9 * 3600 * 10**9)
    assert (C.G1_MIN_MEAN_R, C.G1_MIN_PF, C.G1_COST_STRESS_MULT, C.G1_RANDOM_QUANTILE) == (0.15, 1.2, 2.0, 0.95)
    assert (C.G1_MIN_POSITIVE_YEARS, C.G1_MIN_TRADES, C.BOOTSTRAP_N, C.RANDOM_REPS, C.DSR_N_TRIALS) == (4, 30, 10_000, 1_000, 16)
    assert C.FUNDING_FALLBACK_RATE == 0.0001 and C.FUNDING_FALLBACK_FROM_NS == ns("2026-09-01 00:00")
    assert C.EXEC_SWITCH_NS == ns("2023-10-01 00:00")


# ---------------------------------------------------------------------------
# 1. 체결·청산·비용 손 계산 (§12.1, §12.2)
# ---------------------------------------------------------------------------


def test_hand_long_limit_target_with_funding_full_arithmetic():
    """관통 체결 → 목표 닿기(==)는 무시 → 관통 봉에서 목표 체결. 펀딩 1회. 모든 금액 손 계산."""
    xb = xb_of([(30010.0, 30020.0, 30000.0, 30005.0),   # 07:56 저가 == 지정가 → 미체결(닿기만)
                (30005.0, 30010.0, 29999.9, 30003.0),   # 07:57 관통 → 30000.0 체결(메이커)
                (30003.0, 30100.0, 29990.0, 30090.0),   # 07:58
                (30090.0, 30200.0, 30080.0, 30150.0),   # 07:59
                (30150.0, 30300.0, 30140.0, 30250.0),   # 08:00 펀딩 시각 → 가격 = 시가 30150
                (30250.0, 30400.0, 30240.0, 30390.0),   # 08:01 고가 == 목표 → 청산 아님
                (30390.0, 30400.1, 30380.0, 30395.0),   # 08:02 목표 관통 → 30400.0 (메이커)
                (30395.0, 30500.0, 30390.0, 30450.0)],  # 08:03
               start="2024-01-01 07:56")
    fa = fund([("2024-01-01 08:00", 0.0001), ("2024-01-01 16:00", 0.0003)])  # 16:00은 청산 뒤 → 제외
    tr = X.simulate_plan(plan(), xb, fa, 1.0)
    assert tr.status == T.Status.FILLED and tr.exit_reason == T.Exit.TARGET
    assert (tr.entry_time, tr.exit_time) == (ns("2024-01-01 07:57"), ns("2024-01-01 08:02"))
    assert (tr.entry_price, tr.exit_price) == (30000.0, 30400.0)
    fees = MAKER * 30000.0 + MAKER * 30400.0          # 6.0 + 6.08 = 12.08
    funding = 0.0001 * 30150.0                        # 3.015 (롱이 양수 비율 → 지불)
    net = 400.0 - fees - funding                      # 384.905
    assert tr.fees == pytest.approx(12.08, abs=1e-9) and tr.slippage == 0.0
    assert tr.funding == pytest.approx(funding, abs=1e-9) and tr.net_pnl == pytest.approx(384.905, abs=1e-9)
    assert tr.risk_per_unit == pytest.approx(RISK_LONG_LIMIT, abs=1e-9)
    assert tr.r_multiple == pytest.approx(net / RISK_LONG_LIMIT, abs=1e-12)
    assert tr.busy_until == tr.exit_bar_close_ns == ns("2024-01-01 08:03")
    # 비용 2배: 수수료·지불 펀딩만 2배, 분모는 그대로 (I-27, I-29)
    tr2 = X.simulate_plan(plan(), xb, fa, 2.0)
    assert tr2.net_pnl == pytest.approx(400.0 - 24.16 - 6.03, abs=1e-9)
    assert tr2.r_multiple == pytest.approx(369.81 / RISK_LONG_LIMIT, abs=1e-12)


def test_hand_stop_is_exactly_minus_one_r_and_cost2():
    """갭 없는 손절(저가 == 손절가, 닿기 인정) → 정확히 −1R. 비용 2배 → −(d + 2c)/(d + c)."""
    xb = xb_of([(30005.0, 30010.0, 29999.9, 30002.0),   # 07:56 체결
                (30002.0, 30004.0, 29900.0, 29910.0),
                (29900.0, 29910.0, 29850.0, 29860.0),   # 07:58 저가 == 손절 → 손절가 29850 (시가는 손절 위)
                (29860.0, 29870.0, 29800.0, 29820.0)], start="2024-01-01 07:56")
    tr = X.simulate_plan(plan(), xb, NO_FUNDING, 1.0)
    assert tr.exit_reason == T.Exit.STOP and tr.exit_price == 29850.0
    assert tr.fees == pytest.approx(6.0 + 14.925, abs=1e-9) and tr.slippage == pytest.approx(5.97, abs=1e-9)
    assert tr.net_pnl == pytest.approx(-176.895, abs=1e-9)
    assert tr.r_multiple == pytest.approx(-1.0, abs=1e-12)
    tr2 = X.simulate_plan(plan(), xb, NO_FUNDING, 2.0)
    assert tr2.r_multiple == pytest.approx(-(150.0 + 2 * 26.895) / RISK_LONG_LIMIT, abs=1e-12)  # −1.15204…


def test_hand_gap_through_stop_exits_at_worse_open():
    """체결 다음 봉이 손절 아래에서 시작 → 시가(더 불리)에 청산, 수수료·슬리피지도 그 가격 기준 (I-33)."""
    xb = xb_of([(30005.0, 30010.0, 29999.9, 30002.0),
                (29800.0, 29810.0, 29790.0, 29805.0)], start="2024-01-01 07:56")
    tr = X.simulate_plan(plan(), xb, NO_FUNDING, 1.0)
    assert tr.exit_reason == T.Exit.STOP and tr.exit_price == 29800.0
    net = -200.0 - (6.0 + TAKER * 29800.0) - SLIP * 29800.0     # −226.86
    assert tr.r_multiple == pytest.approx(net / RISK_LONG_LIMIT, abs=1e-12)
    assert tr.r_multiple < -1.28


def test_hand_same_bar_order_fill_bar_target_ignored_then_stop_first():
    """체결 봉의 목표 관통은 무시, 다음 봉에서 손절·목표 둘 다 → 손절 (§12.1)."""
    xb = xb_of([(30005.0, 30400.5, 29999.9, 30002.0),   # 체결 봉: 목표도 관통하지만 인정 안 함
                (30002.0, 30400.5, 29850.0, 30100.0)],  # 둘 다 → 손절 먼저
               start="2024-01-01 07:56")
    tr = X.simulate_plan(plan(), xb, NO_FUNDING, 1.0)
    assert tr.exit_reason == T.Exit.STOP and tr.exit_time == ns("2024-01-01 07:57") and tr.exit_price == 29850.0


def test_hand_target_gap_is_not_given_better_price():
    """목표 너머에서 시작하는 봉(유리한 갭)이어도 목표가에 체결 — 유리한 체결을 주지 않는다 (I-33)."""
    xb = xb_of([(30005.0, 30010.0, 29999.9, 30002.0),
                (30500.0, 30600.0, 30450.0, 30550.0)], start="2024-01-01 07:56")
    tr = X.simulate_plan(plan(), xb, NO_FUNDING, 1.0)
    assert tr.exit_reason == T.Exit.TARGET and tr.exit_price == 30400.0


def test_hand_short_funding_sign_and_cost2_only_doubles_payments():
    """숏(5분봉 구간): 양수 비율은 수취(2배 안 함), 음수 비율은 지불(2배). 손 계산."""
    flat = (29990.0, 29995.0, 29985.0, 29990.0)
    rows = [(29990.0, 30000.1, 29980.0, 29995.0)] + [flat] * 98 + [(29990.0, 29995.0, 29599.9, 29700.0)]
    xb = xb_of(rows, start="2023-06-01 07:50", tf="5m")          # 07:50 체결 … 16:05 목표
    short = plan(scenario="S2", side=-1, entry_price=30000.0, stop=30150.0, target=29600.0,
                 signal_time=ns("2023-06-01 07:39"), approval_time=ns("2023-06-01 07:40"),
                 active_from=ns("2023-06-01 07:50"), valid_until=ns("2023-06-01 19:00"))
    fa = fund([("2023-06-01 08:00", 0.0002), ("2023-06-01 16:00", -0.0001), ("2023-06-02 00:00", 0.0005)])
    risk = 150.0 + MAKER * 30000.0 + (TAKER + SLIP) * 30150.0     # 177.105
    tr = X.simulate_plan(short, xb, fa, 1.0)
    assert tr.exit_reason == T.Exit.TARGET and tr.exit_time == ns("2023-06-01 16:05")
    received, paid = -0.0002 * 29990.0, 0.0001 * 29990.0          # −5.998 (수취), +2.999 (지불)
    assert tr.funding == pytest.approx(received + paid, abs=1e-9)
    assert tr.r_multiple == pytest.approx((400.0 - 11.92 - (received + paid)) / risk, abs=1e-12)
    tr2 = X.simulate_plan(short, xb, fa, 2.0)
    assert tr2.funding == pytest.approx(received + 2 * paid, abs=1e-9)   # = 0.0
    assert tr2.r_multiple == pytest.approx((400.0 - 23.84 - 0.0) / risk, abs=1e-12)


def test_hand_funding_window_edges():
    """진입 < f ≤ 청산 (각 실행 봉 시작 시각): 08:00에 시작한 봉에서 체결 → 08:00 없음, 16:00 봉에서 청산 → 16:00 있음."""
    flat = (30002.0, 30005.0, 29990.0, 30002.0)
    rows = [(30005.0, 30010.0, 29999.9, 30002.0)] + [flat] * 479 + [(30002.0, 30003.0, 29850.0, 29860.0)]
    xb = xb_of(rows, start="2024-01-01 08:00")
    fa = fund([("2024-01-01 08:00", 0.0001), ("2024-01-01 16:00", 0.0001)])
    tr = X.simulate_plan(plan(active_from=ns("2024-01-01 08:00")), xb, fa, 1.0)
    assert (tr.entry_time, tr.exit_time, tr.exit_reason) == (ns("2024-01-01 08:00"), ns("2024-01-01 16:00"), "stop")
    assert tr.funding == pytest.approx(0.0001 * 30002.0, abs=1e-12)
    assert tr.r_multiple == pytest.approx((-176.895 - 3.0002) / RISK_LONG_LIMIT, abs=1e-12)


def test_hand_time_exit_across_5m_to_1m_switch():
    """P1 72시간: 5분봉(2023-09-30 20:00 체결) → 1분봉 구간 2023-10-03 20:00 시작 봉 시가에 청산(테이커+슬리피지)."""
    five = make_bars([(30005.0, 30010.0, 29999.9, 30002.0)] + [(30002.0, 30005.0, 29990.0, 30002.0)] * 47,
                     start="2023-09-30 20:00", tf="5m")                      # 20:00 ~ 23:55
    one = make_bars([(30002.0, 30005.0, 29990.0, 30002.0)] * (72 * 60 - 4 * 60 + 3), start="2023-10-01 00:00")
    xb = T.ExecArrays.from_frame(make_exec_bars(five, one))
    p = plan(signal_time=ns("2023-09-30 19:00"), approval_time=ns("2023-09-30 19:01"),
             active_from=ns("2023-09-30 19:11"), valid_until=ns("2023-10-01 19:00"))
    tr = X.simulate_plan(p, xb, NO_FUNDING, 1.0)
    assert tr.entry_time == ns("2023-09-30 20:00")                        # 실행 봉이 20:00부터 → 첫 봉 체결
    assert tr.exit_reason == T.Exit.TIME and tr.exit_time == ns("2023-10-03 20:00") and tr.exit_price == 30002.0
    net = 2.0 - (MAKER * 30000.0 + TAKER * 30002.0) - SLIP * 30002.0
    assert tr.r_multiple == pytest.approx(net / RISK_LONG_LIMIT, abs=1e-12)


def test_hand_activation_and_cancel_boundaries_5m():
    """5분봉 구간: active_from 10:11 → 10:10 봉(관통해도) 제외, 10:15 봉부터. 취소 효력 12:01 → 12:00 봉(끝 12:05) 불인정."""
    pierce = (30005.0, 30010.0, 29999.9, 30002.0)
    flat = (30002.0, 30005.0, 30001.0, 30002.0)
    p = plan(signal_time=ns("2023-06-01 10:00"), approval_time=ns("2023-06-01 10:01"),
             active_from=ns("2023-06-01 10:11"), valid_until=ns("2023-06-02 10:00"))
    xb = xb_of([pierce, pierce, flat], start="2023-06-01 10:10", tf="5m")
    assert X.simulate_plan(p, xb, NO_FUNDING).entry_time == ns("2023-06-01 10:15")
    rows = [flat] * 22 + [pierce] + [flat] * 3                         # 10:10 … 12:00 봉이 관통
    xb2 = xb_of(rows, start="2023-06-01 10:10", tf="5m")
    tr = X.simulate_plan(dataclasses.replace(p, cancel_effective_time=ns("2023-06-01 12:01"),
                                             cancel_reason="close_below"), xb2, NO_FUNDING)
    assert tr.status == T.Status.CANCELLED and tr.busy_until == ns("2023-06-01 12:01")


def test_hand_ioc_cap_boundaries_and_fill_below_stop():
    """IOC: 시가 == 상한 → 시가 체결(테이커), 상한 + 0.1 → 미체결(자리 = 그 봉 끝). 시가가 손절 아래면 그 봉 시가에 바로 손절."""
    ioc = plan(scenario="L1b", order_type="ioc_cap", entry_price=30030.0, valid_until=ns("2024-01-01 07:56"))
    ok = X.simulate_plan(ioc, xb_of([(30030.0, 30040.0, 30020.0, 30035.0)], start="2024-01-01 07:56"), NO_FUNDING)
    assert ok.status == T.Status.FILLED and ok.entry_price == 30030.0
    no = X.simulate_plan(ioc, xb_of([(30030.1, 30040.0, 30020.0, 30035.0)], start="2024-01-01 07:56"), NO_FUNDING)
    assert no.status == T.Status.NOT_FILLED and no.busy_until == ns("2024-01-01 07:57")
    gap = X.simulate_plan(ioc, xb_of([(29840.0, 29900.0, 29830.0, 29880.0)], start="2024-01-01 07:56"), NO_FUNDING)
    assert gap.exit_reason == T.Exit.STOP and gap.entry_price == gap.exit_price == 29840.0
    # R 분모 = 실제 체결가 기준 (I-29, 검토 F1 수정): d = |29840 − 29850| = 10 → 10 + 14.92 + 20.895 = 45.815
    risk = 10.0 + TAKER * 29840.0 + (TAKER + SLIP) * 29850.0
    assert gap.risk_per_unit == pytest.approx(45.815, abs=1e-9)
    assert gap.r_multiple == pytest.approx(-(2 * TAKER * 29840.0 + SLIP * 29840.0) / risk, abs=1e-12)   # −0.7816


# ---------------------------------------------------------------------------
# 2. 리스크 검사 손 계산 (§8.1, §12.2)
# ---------------------------------------------------------------------------


def test_hand_net_rr_formula_and_boundary():
    """순손익비 = (|목표 − 진입| − 진입 수수료 − 목표 메이커) ÷ (d + c_stop)."""
    assert C.net_rr(1, 30000.0, 29850.0, 30400.0, MAKER) == pytest.approx(387.92 / 176.895, abs=1e-12)
    assert C.net_rr(1, 30000.0, 29850.0, 30280.0, MAKER) == pytest.approx(267.944 / 176.895, abs=1e-12)  # 1.5147 통과
    assert C.net_rr(1, 30000.0, 29850.0, 30270.0, MAKER) == pytest.approx(257.946 / 176.895, abs=1e-12)  # 1.4582 실패
    assert X.risk_reasons(1, 30000.0, 29850.0, 30280.0, 100.0, "limit") == ()
    assert X.risk_reasons(1, 30000.0, 29850.0, 30270.0, 100.0, "limit") == (T.Reason.RISK_RR,)
    assert C.net_rr(-1, 30000.0, 30150.0, 29600.0, MAKER) == pytest.approx(388.08 / 177.105, abs=1e-12)
    # L1b(IOC 상한) = 테이커 진입 수수료로 계산
    assert C.net_rr(1, 30030.0, 29850.0, 30400.0, TAKER) == pytest.approx(348.905 / 215.91, abs=1e-12)
    assert C.net_rr(1, 30000.0, 29850.0, 29900.0, MAKER) < 0                       # 목표가 반대편 → 실패


@pytest.mark.parametrize("stop,atr,ok", [
    (29880.1, 100.0, False),   # d 119.9 < max(0.4%·30000 = 120, 1·ATR = 100)
    (29880.0, 100.0, True),    # d 120 (하한 포함)
    (29700.0, 100.0, True),    # d 300 = min(2% = 600, 3·ATR = 300) (상한 포함)
    (29699.9, 100.0, False),   # d 300.1
    (29880.0, 40.0, True),     # 하한 = 상한 = 120
    (29879.9, 40.0, False),
    (29750.1, 250.0, False),   # d 249.9 < 1·ATR 250
    (29400.0, 250.0, True),    # d 600 = 2% 상한 (3·ATR = 750)
    (29399.9, 250.0, False),
])
def test_hand_stop_band(stop, atr, ok):
    assert X.stop_band_ok(30000.0, stop, atr) is ok


# ---------------------------------------------------------------------------
# 3. 순차 처리: KST 마스크·하루 6건·F8·F9 (§12.3)
# ---------------------------------------------------------------------------


def _unfilled_plan(t: str, pid: str) -> T.Plan:
    """실행 봉이 없는 시각의 계획: not_filled, 자리 = active_from = 승인 시각(지연 0) → 서로 막지 않는다."""
    a = ns(t)
    return plan(plan_id=pid, signal_time=a - C.NS_PER_MIN, approval_time=a, active_from=a, valid_until=a + 60 * 10**9)


def test_hand_kst_mask_boundaries_and_daily_cap_day_edge():
    """KST = UTC+9. 방해 금지 [00:30, 07:30) = UTC [15:30, 22:30). KST 날짜 경계 = UTC 15:00."""
    xb = xb_of([(1.0, 1.0, 1.0, 1.0)], start="2023-12-31 00:00")            # 계획 시각에는 실행 봉 없음
    times = ["2024-01-01 15:29", "2024-01-01 15:30", "2024-01-01 22:29", "2024-01-01 22:30",
             "2024-01-02 01:00", "2024-01-02 02:00", "2024-01-02 03:00", "2024-01-02 04:00",
             "2024-01-02 14:59", "2024-01-02 15:00"]
    cands = [cand(_unfilled_plan(t, f"p{i}")) for i, t in enumerate(times)]
    trades, logs = X.run_sequence(cands, xb, NO_FUNDING, C.ComboConfig("L1a", "DA", "P1"))
    dnd, cap = (T.Reason.MASK_DND,), (T.Reason.MASK_DAILY_CAP,)
    # 15:29(KST 00:29) 통과 · 15:30/22:29 방해 금지(요청 수에 안 셈) · 22:30~04:00 = 그날 2~6번째 · 14:59 = 7번째 · 15:00 = 다음 날
    assert [lg.reasons for lg in logs] == [(), dnd, dnd, (), (), (), (), (), cap, ()]
    assert len(trades) == 7 and all(t.status == T.Status.NOT_FILLED for t in trades)
    _, logs_all = X.run_sequence(cands, xb, NO_FUNDING, C.ComboConfig("L1a", "DA", "P1", apply_availability_mask=False))
    assert all(lg.status == "passed" for lg in logs_all)


def test_hand_f8_counts_only_stop_exits_and_f9_equal_time_allowed():
    """같은 마디: 손절 → 시간 청산(손실) → 손절 → 네 번째는 F8 (시간 청산 손실은 '손절'로 세지 않음, I-19).
    F9는 승인 시각 < 자리 끝이면 폐기, 같으면 허용."""
    fill = (30005.0, 30010.0, 29999.9, 30002.0)
    stop = (29900.0, 29910.0, 29850.0, 29860.0)
    rows = [fill, stop,                                          # 10:00 체결, 10:01 손절 → 자리 10:02
            (30005.0, 30010.0, 29985.0, 29990.0),                # 10:02 체결(p2)
            (29990.0, 29995.0, 29950.0, 29960.0), (29960.0, 29970.0, 29950.0, 29960.0),
            (29960.0, 29970.0, 29950.0, 29960.0),                # 10:05 시간 청산(손실) → 자리 10:06
            fill, stop,                                          # 10:06 체결, 10:07 손절 → 자리 10:08
            (29860.0, 29870.0, 29855.0, 29860.0), (29860.0, 29870.0, 29855.0, 29860.0)]
    xb = xb_of(rows, start="2024-01-01 10:00")
    m = "1hU-TEST"

    def p(t, pid, **kw):
        a = ns(t)
        return plan(plan_id=pid, madi_id=m, signal_time=a - C.NS_PER_MIN, approval_time=a, active_from=a,
                    valid_until=a + 3 * C.NS_PER_MIN, **kw)

    plans = [p("2024-01-01 10:00", "p1"), p("2024-01-01 10:02", "p2", max_hold_ns=3 * C.NS_PER_MIN),
             p("2024-01-01 10:06", "p3")]
    early = dataclasses.replace(p("2024-01-01 10:06", "p3"), plan_id="early", madi_id=None,
                                approval_time=ns("2024-01-01 10:08") - 1, active_from=ns("2024-01-01 10:08"))
    last = p("2024-01-01 10:08", "p4")
    trades, logs = X.run_sequence([cand(x) for x in plans + [early, last]], xb, NO_FUNDING,
                                  C.ComboConfig("L1a", "DA", "P1", apply_availability_mask=False))
    assert [t.exit_reason for t in trades] == ["stop", "time", "stop"]
    assert trades[1].r_multiple < 0                               # 시간 청산은 손실이지만 F8에 안 셈
    assert [lg.reasons for lg in logs] == [(), (), (), (T.Reason.F9,), (T.Reason.F8,)]


# ---------------------------------------------------------------------------
# 4. 무작위 기준선 손 계산 (§12.4)
# ---------------------------------------------------------------------------


def _base_trade() -> T.TradeResult:
    """기준 '실제' 거래: 롱, 실제 진입 30000, 손절 29850(0.5%), 목표 30400(1.333…%), 2024-01 진입."""
    t = ns("2024-01-10 12:00")
    return T.TradeResult(plan_id="base", scenario="L1a", side=1, order_type="limit", signal_time=t,
                         approval_time=t, active_from=t, plan_entry=30000.0, stop=29850.0, target=30400.0,
                         status=T.Status.FILLED, busy_until=t, risk_per_unit=RISK_LONG_LIMIT, entry_time=t,
                         entry_price=30000.0)


def _random_xb():
    flat = (30000.0, 30005.0, 29995.0, 30000.0)
    rows = [flat] * 11 + [(30100.0, 30110.0, 30090.0, 30105.0),   # 01:11 = 01:00 마감 + 60초 + 10분 → 시가 30100 진입
                          (30105.0, 30501.4, 30100.0, 30500.0)] + [flat] * 5   # 01:12 목표 30501.3 관통
    return xb_of(rows, start="2024-01-01 01:00")


def test_hand_random_baseline_trade():
    """시장가(테이커) 진입, 손절·목표 % 유지(실제 진입가 대비), 같은 청산 엔진. 1월 신호 봉 마감이 하나뿐 → 모든 반복이 같은 값."""
    xb = _random_xb()
    cfg = C.ComboConfig("L1a", "DA", "P1")
    out = RB.run_random_baseline([_base_trade()], np.array([ns("2024-01-01 01:00")]), xb, NO_FUNDING, cfg, n_reps=3)
    stop, target = 29949.5, 30501.3                     # round(30100 × 0.995), round(30100 × 1.01333…)
    net = (target - 30100.0) - (TAKER * 30100.0 + MAKER * target)
    risk = (30100.0 - stop) + TAKER * 30100.0 + (TAKER + SLIP) * stop
    assert out["n_trades"] == 1 and out["n_not_filled"] == 0
    assert np.allclose(out["means"], net / risk, rtol=0, atol=1e-12)
    assert out["p95"] == pytest.approx(net / risk, abs=1e-12)


def test_finding_random_baseline_taker_entry_handicap_vs_limit_combos():
    """[발견 F2, 명세 §12.4 그대로] 무작위 기준선은 모든 조합에서 테이커 진입이다. L1a·S2·S3(지정가 = 메이커) 조합과
    비교하면 같은 가격 경로에서도 무작위 쪽 이긴 거래 R이 낮아진다(분자 수수료 +0.03%, 분모도 커짐).
    손절 거래는 둘 다 정확히 −1R이라 차이가 없다 → 차이는 이긴 거래·시간 청산에서만 생긴다.
    이 사례(손절 폭 0.5%, 목표 R ≈ 2): 0.15R 넘게 차이 → 무작위 95% 분위(조건 5)가 그만큼 쉬워진다."""
    xb = _random_xb()
    cfg = C.ComboConfig("L1a", "DA", "P1")
    r_rand = RB.run_random_baseline([_base_trade()], np.array([ns("2024-01-01 01:00")]), xb, NO_FUNDING, cfg,
                                    n_reps=1)["mean"]
    stop, target = 29949.5, 30501.3
    r_same_fee = ((target - 30100.0) - (MAKER * 30100.0 + MAKER * target)) / \
                 ((30100.0 - stop) + MAKER * 30100.0 + (TAKER + SLIP) * stop)
    assert r_same_fee - r_rand == pytest.approx(0.1545, abs=5e-4)
    # 수정(보고용): 같은 진입 수수료 분포를 함께 낸다 — 판정 p95는 그대로 테이커 분포
    out = RB.run_random_baseline([_base_trade()], np.array([ns("2024-01-01 01:00")]), xb, NO_FUNDING, cfg, n_reps=2)
    assert out["p95"] == pytest.approx(r_rand, abs=1e-12)
    assert out["same_fee"]["entry_fee_rate"] == MAKER
    assert out["same_fee"]["p95"] == pytest.approx(r_same_fee, abs=1e-12)


def test_hand_random_baseline_same_exit_rules_as_signals():
    """무작위 거래도 진입 봉의 목표 관통은 무시하고(다음 봉부터), 같은 봉 손절·목표면 손절 → 정확히 −1R."""
    flat = (30000.0, 30005.0, 29995.0, 30000.0)
    rows = [flat] * 11 + [(30100.0, 30600.0, 30090.0, 30105.0),     # 01:11 진입 봉: 목표 30501.3 관통 → 무시
                          (30105.0, 30600.0, 29949.5, 30000.0)]     # 01:12 손절(닿기)·목표 둘 다 → 손절
    xb = xb_of(rows, start="2024-01-01 01:00")
    cfg = C.ComboConfig("L1a", "DA", "P1")
    out = RB.run_random_baseline([_base_trade()], np.array([ns("2024-01-01 01:00")]), xb, NO_FUNDING, cfg, n_reps=1)
    assert out["mean"] == pytest.approx(-1.0, abs=1e-12)


# ---------------------------------------------------------------------------
# 4b. 통계 손 계산 (§8.3, §12.4)
# ---------------------------------------------------------------------------


def test_hand_metrics_pf_bootstrap_and_verdict_boundaries():
    from statistics import NormalDist
    from backtest import metrics as M
    assert M.profit_factor(np.array([2.0, -1.0, -1.0, 0.5, 0.0])) == pytest.approx(1.25)
    lo, hi = M.bootstrap_mean_ci(np.array([-1.0, 2.0]), rng=np.random.default_rng(0))  # 평균 −1(1/4)·0.5·2(1/4)
    assert (lo, hi) == (-1.0, 2.0)
    base = {"n": 30, "mean_r": 0.15, "boot_lo": 1e-9, "pf": 1.2, "positive_years": 4}
    v = M.g1_verdict(base, cost2_mean_r=1e-9, random_p95=0.1499)
    assert v["result"] == "pass"                                              # ≥ 0.15, ≥ 1.2, ≥ 4, n ≥ 30 포함
    assert M.g1_verdict({**base, "boot_lo": 0.0}, 1e-9, 0.1)["c2_boot_lo"] is False      # 하한 > 0 (엄격)
    assert M.g1_verdict(base, 0.0, 0.1)["c4_cost2"] is False                              # 비용 2배 > 0 (엄격)
    assert M.g1_verdict(base, 1e-9, 0.15)["c5_random"] is False                           # p95보다 "높음" (엄격)
    assert M.g1_verdict({**base, "n": 29}, 1e-9, 0.1)["result"] == "pending"
    # DSR 직접 계산 (Bailey·López de Prado 2014): sr 0.3, T 40, 왜도 0.8, 첨도 3.5, V 0.04, N 16
    g, nd = 0.5772156649015329, NormalDist()
    sr0 = 0.2 * ((1 - g) * nd.inv_cdf(1 - 1 / 16) + g * nd.inv_cdf(1 - 1 / (16 * np.e)))
    z = (0.3 - sr0) * np.sqrt(39) / np.sqrt(1 - 0.8 * 0.3 + (3.5 - 1) / 4 * 0.09)
    assert M.deflated_sharpe(0.3, 40, 0.8, 3.5, 0.04, 16) == pytest.approx(nd.cdf(z), abs=1e-12)


# ---------------------------------------------------------------------------
# 5. 발견 사항 — 성과를 부풀릴 수 있는 가정 (현재 동작을 숫자로 고정)
# ---------------------------------------------------------------------------

# 손 계산 공통 (발견 F1 → 수정됨): L1b 상한 30030.0, 실제 체결 = 첫 실행 봉 시가 29970.0, 손절 29850.0 (갭 없음)
#   순손익 = −120 − (0.0005×29970 + 0.0005×29850) − 0.0002×29850 = −120 − 29.91 − 5.97 = −155.88
#   분모(상한가 기준, 수정 전 I-29)  = 180 + 0.0005×30030 + 0.0007×29850 = 215.91 → R = −0.72197
#   분모(실제 체결가 기준, 수정 후)  = 120 + 0.0005×29970 + 0.0007×29850 = 155.88 → R = −1.00000
_IOC_ROWS = [(29970.0, 29980.0, 29960.0, 29975.0),   # 07:56 시가 29970 ≤ 상한 → 체결
             (29975.0, 29980.0, 29900.0, 29910.0),
             (29900.0, 29905.0, 29850.0, 29860.0)]   # 07:58 손절 29850 (시가는 손절 위 → 갭 아님)


def _ioc_plan() -> T.Plan:
    return plan(scenario="L1b", order_type="ioc_cap", entry_price=30030.0, valid_until=ns("2024-01-01 07:56"))


def test_fixed_f1_l1b_stop_is_minus_one_r_same_unit_as_random_baseline():
    """[발견 F1 → 수정됨] 수정 전에는 L1b 손절 거래가 −1R이 아니라 −0.722R로 기록됐다(R 분모가 상한가 기준, 옛 I-29).
    이제 분모 = 실제 체결가 기준 → 정확히 −1R이고, 같은 경로를 무작위 기준선 엔진으로 돌린 값과 같다(같은 R 단위).
    수량(size_fraction)은 계획 시점(상한가) 기준 그대로다."""
    xb = xb_of(_IOC_ROWS, start="2024-01-01 07:56")
    tr = X.simulate_plan(_ioc_plan(), xb, NO_FUNDING, 1.0)
    assert (tr.entry_price, tr.exit_price, tr.exit_reason) == (29970.0, 29850.0, "stop")
    assert tr.net_pnl == pytest.approx(-155.88, abs=1e-9)
    assert tr.risk_per_unit == pytest.approx(155.88, abs=1e-9)
    assert tr.r_multiple == pytest.approx(-1.0, abs=1e-12)
    assert tr.size_fraction == pytest.approx(min(1.0, 0.6 * 215.91 / (0.005 * 30030.0)), abs=1e-12)
    # 같은 경로·같은 손절 거리(실제 진입가 대비)를 무작위 기준선 엔진으로: 정확히 −1R
    cfg = C.ComboConfig("L1b", "DA", "P1")
    rnd = RB.simulate_market_trade(1, ns("2024-01-01 07:45"), 120.0 / 29970.0, 400.0 / 29970.0, xb, NO_FUNDING, cfg)
    assert rnd.entry_price == 29970.0 and rnd.stop == 29850.0 and rnd.exit_reason == "stop"
    assert rnd.r_multiple == pytest.approx(tr.r_multiple, abs=1e-12)


def test_finding_l1b_stop_should_be_minus_one_r_with_actual_fill_denominator():
    """(검토 xfail 테스트 — 수정 뒤 통과하므로 표시를 지웠다)"""
    xb = xb_of(_IOC_ROWS, start="2024-01-01 07:56")
    tr = X.simulate_plan(_ioc_plan(), xb, NO_FUNDING, 1.0)
    assert tr.r_multiple == pytest.approx(-1.0, abs=1e-9)


def test_fixed_f3_5m_era_open_fill_pays_funding_after_activation():
    """[발견 F3 → 수정됨] 5분봉 구간(2023-10 전)에서 IOC·시장가는 active_from 뒤 첫 5분봉 시가에 체결된다.
    active_from 07:56 → 08:00 봉 시가 체결(entry_time = 08:00). 수정 전에는 '진입 < f' 규칙으로 08:00 펀딩이 빠졌다
    (실제로는 07:56에 들어가 08:00 펀딩을 냈을 거래, 롱·양수 비율이면 비용 누락 = 유리). 이제 시가 체결 주문의 펀딩 창은
    활성 시각 < f ≤ 청산이다(execution.funding_start). 지정가는 그대로 진입 봉 시작 < f."""
    rows = [(30000.0, 30010.0, 29990.0, 30000.0),        # 07:55 (active_from 전 시작 → 제외)
            (30000.0, 30010.0, 29990.0, 30000.0),        # 08:00 시가 30000 ≤ 상한 → 체결
            (30000.0, 30400.1, 29990.0, 30300.0)]        # 08:05 목표 관통
    xb = xb_of(rows, start="2023-06-01 07:55", tf="5m")
    ioc = plan(scenario="L1b", order_type="ioc_cap", entry_price=30030.0, signal_time=ns("2023-06-01 07:45"),
               approval_time=ns("2023-06-01 07:46"), active_from=ns("2023-06-01 07:56"),
               valid_until=ns("2023-06-01 07:56"))
    fa = fund([("2023-06-01 08:00", 0.0003)])
    tr = X.simulate_plan(ioc, xb, fa, 1.0)
    assert tr.entry_time == ns("2023-06-01 08:00") and ioc.active_from < ns("2023-06-01 08:00")
    assert tr.funding == pytest.approx(0.0003 * 30000.0, abs=1e-12)  # 08:00 펀딩 9.0 (08:00 봉 시가 기준)
    risk = 150.0 + TAKER * 30000.0 + (TAKER + SLIP) * 29850.0         # 실제 체결가 30000 기준 분모 (F1)
    assert tr.risk_per_unit == pytest.approx(risk, abs=1e-9)
    net = 400.0 - (TAKER * 30000.0 + MAKER * 30400.0) - 9.0
    assert tr.exit_reason == T.Exit.TARGET and tr.r_multiple == pytest.approx(net / risk, abs=1e-12)
    # 같은 모양의 지정가(08:00 봉에서 관통 체결)는 08:00 전에 포지션이 없으므로 펀딩 없음
    lim = dataclasses.replace(ioc, scenario="L1a", order_type="limit", entry_price=29995.0,
                              valid_until=ns("2023-06-01 09:00"))
    tl = X.simulate_plan(lim, xb, fa, 1.0)
    assert tl.entry_time == ns("2023-06-01 08:00") and tl.funding == 0.0


def test_finding_marketable_limit_gets_maker_fee():
    """[발견 F4] 지정가가 활성 시각에 이미 시장가보다 유리한 쪽(롱: 시가 < 지정가)이면 실제로는 즉시 체결되는
    테이커 주문이다. 엔진은 지정가(더 나쁜 가격)에 메이커 수수료로 체결한다. 가격 차이가 수수료 차이(0.03%)보다 작으면
    엔진이 유리하다: 시가 29995 → 엔진 진입 원가 30000×1.0002 = 30006.0, 테이커 즉시 체결 29995×1.0005 = 30009.9975."""
    xb = xb_of([(29995.0, 30002.0, 29990.0, 29998.0), (29998.0, 30000.0, 29996.0, 29999.0)], start="2024-01-01 07:56")
    tr = X.simulate_plan(plan(), xb, NO_FUNDING, 1.0)
    assert tr.entry_time == ns("2024-01-01 07:56") and tr.entry_price == 30000.0
    engine_cost = 30000.0 * (1 + MAKER)
    taker_cost = 29995.0 * (1 + TAKER)
    assert taker_cost - engine_cost == pytest.approx(3.9975, abs=1e-9)    # 단위당 3.9975 유리 ≈ 0.0226R
    # 수정: 체결은 명세 그대로 두되 표시하고 원가 차이(R)를 남겨 결과 JSON(marketable_limit)에 보고한다
    assert tr.meta["marketable_open"] == 29995.0
    assert tr.meta["marketable_edge_r"] == pytest.approx(3.9975 / RISK_LONG_LIMIT, abs=1e-12)
    normal = X.simulate_plan(plan(), xb_of([(30005.0, 30010.0, 29999.9, 30002.0)], start="2024-01-01 07:56"),
                             NO_FUNDING)
    assert normal.is_filled and "marketable_open" not in normal.meta    # 시가가 지정가 위 → 관통 체결(표시 없음)


# ---------------------------------------------------------------------------
# 6. 실데이터 전체 감사 (@slow) — 명세 문장에서 따로 짠 참조 구현과 한 건씩 대조
# ---------------------------------------------------------------------------


def _ref_simulate(p: T.Plan, xb: T.ExecArrays, fa: T.FundingArrays, m: float) -> dict:
    """§12.1~§12.2를 문장 그대로 옮긴 참조 구현(엔진 코드를 쓰지 않는다)."""
    on, cn, o, h, lo, cl = xb.open_ns, xb.close_ns, xb.open, xb.high, xb.low, xb.close
    n, side = len(on), p.side
    j0 = int(np.searchsorted(on, p.active_from, "left"))                 # 활성 이후 "시작하는" 봉부터
    if j0 >= n:
        return {"status": "not_filled", "busy": p.active_from}
    if p.order_type == "limit":
        end = p.valid_until if p.cancel_effective_time is None else min(p.valid_until, p.cancel_effective_time)
        je = None
        for j in range(j0, n):
            if cn[j] > end:                                              # 봉 전체가 수명 안이어야
                break
            if (side > 0 and lo[j] < p.entry_price) or (side < 0 and h[j] > p.entry_price):   # 관통
                je = j
                break
        if je is None:
            cancelled = p.cancel_effective_time is not None and p.cancel_effective_time < p.valid_until
            return {"status": "cancelled" if cancelled else "expired", "busy": end}
        ep, erate = p.entry_price, MAKER
    else:
        ok = p.order_type == "market" or (o[j0] <= p.entry_price if side > 0 else o[j0] >= p.entry_price)
        if not ok:
            return {"status": "not_filled", "busy": int(cn[j0])}
        je, ep, erate = j0, float(o[j0]), TAKER
    limit_t = on[je] + p.max_hold_ns
    jx = why = xp = None
    j = je
    while j < n:
        if j > je and on[j] >= limit_t:
            jx, xp, why = j, float(o[j]), "time"
            break
        s_hit = lo[j] <= p.stop if side > 0 else h[j] >= p.stop
        t_hit = j > je and (h[j] > p.target if side > 0 else lo[j] < p.target)
        if s_hit:
            xp = p.stop
            if j > je or p.order_type != "limit":
                xp = min(xp, float(o[j])) if side > 0 else max(xp, float(o[j]))
            jx, why = j, "stop"
            break
        if t_hit:
            jx, xp, why = j, p.target, "target"
            break
        j += 1
    if jx is None:
        jx, xp, why = n - 1, float(cl[n - 1]), "eod"
    fees = (erate * ep + (MAKER if why == "target" else TAKER) * xp) * m
    slip = 0.0 if why == "target" else SLIP * xp * m
    fund_cost = 0.0
    f_lo = on[je] if p.order_type == "limit" else min(on[je], p.active_from)   # 시가 체결은 활성 시각부터 (F3 수정)
    for f, r in zip(fa.time_ns, fa.rate):
        if f_lo < f <= on[jx]:
            x = side * r * float(o[int(np.searchsorted(on, f, "right")) - 1])
            fund_cost += x * m if x > 0 else x
    net = side * (xp - ep) - fees - slip - fund_cost
    risk = abs(ep - p.stop) + erate * ep + (TAKER + SLIP) * p.stop       # §12.2 진입가 = 실제 체결가 (F1 수정)
    return {"status": "filled", "entry_time": int(on[je]), "exit_time": int(on[jx]), "entry_price": ep,
            "exit_price": xp, "why": why, "net": net, "r": net / risk, "busy": int(cn[jx]), "fund": fund_cost}


def _kst_minutes_and_day(t_ns: int):
    k = pd.Timestamp(int(t_ns), unit="ns", tz="UTC").tz_convert("Asia/Seoul")   # 표준 라이브러리 시간대로 따로 계산
    return k.hour * 60 + k.minute, k.date()


@pytest.fixture(scope="module")
def real_runs():
    from backtest import data as D
    from backtest import scenarios as SC
    market = D.load_market()
    xb, fa = market.exec_arrays(), market.funding_arrays()
    ctx = {s: SC.build_context(market, s, C.KIJUN_VR_MIN) for s in C.SETTING_NAMES}
    out = {}
    # [수정 담당] L1b가 마디당 준비 1회가 되어(검토 SPEC-L1B-REARM) 실행 계획이 줄었으므로, 검정력을 위해
    # L1b 재준비 진단(수정 전 후보 집합) 실행도 같이 대조한다. 체결 엔진 규칙은 둘 다 같다.
    diag = [c.replace(**C.L1B_REARM_VARIANT[1]) for c in C.g1_combos() if c.scenario == "L1b"]
    for cfg in C.g1_combos() + diag:
        cands = SC.generate_candidates(ctx[cfg.setting], cfg)
        cfgs = {"all": cfg.replace(apply_availability_mask=False), "exec": cfg,
                "cost2": cfg.replace(cost_multiplier=C.G1_COST_STRESS_MULT)}
        name = cfg.base_key + ("_rearm" if cfg.l1b_rearm else "")
        out[name] = (cands, {k: (c, X.run_sequence(cands, xb, fa, c)) for k, c in cfgs.items()})
    return market, xb, fa, out


@pytest.mark.slow
def test_real_every_plan_matches_literal_reference(real_runs):
    """실데이터 16조합 × 전체/실행 가능/비용 2배의 모든 실행 계획을 참조 구현과 대조 (체결·청산·수수료·펀딩·R·자리)."""
    _, xb, fa, out = real_runs
    bad, n_plans = [], 0
    for key, (cands, runs) in out.items():
        plans = {c.plan.plan_id: c.plan for c in cands if c.plan is not None}
        for mode, (cfg, (trades, _)) in runs.items():
            for tr in trades:
                n_plans += 1
                ref = _ref_simulate(plans[tr.plan_id], xb, fa, cfg.cost_multiplier)
                if ref["status"] != tr.status or ref["busy"] != tr.busy_until:
                    bad.append((key, mode, tr.plan_id, "status/busy"))
                    continue
                if tr.status != T.Status.FILLED:
                    continue
                same = (ref["entry_time"] == tr.entry_time and ref["exit_time"] == tr.exit_time
                        and ref["why"] == tr.exit_reason and ref["entry_price"] == tr.entry_price
                        and ref["exit_price"] == tr.exit_price
                        and np.isclose(ref["net"], tr.net_pnl, rtol=0, atol=1e-8)
                        and np.isclose(ref["fund"], tr.funding, rtol=0, atol=1e-8)
                        and np.isclose(ref["r"], tr.r_multiple, rtol=0, atol=1e-10))
                if not same:
                    bad.append((key, mode, tr.plan_id, "fill/exit/cost"))
    assert n_plans > 300
    assert bad == []


@pytest.mark.slow
def test_real_sequence_rules_and_time_contracts(real_runs):
    """F8·F9·방해 금지(KST, pandas 시간대로 따로 계산)·하루 6건을 후보 순서대로 다시 적용해 사유가 같은지,
    실행한 계획끼리 자리가 겹치지 않는지, 체결이 active_from 전에 시작한 봉에서 나지 않았는지 본다."""
    _, xb, _, out = real_runs
    bad = collections.Counter()
    for key, (cands, runs) in out.items():
        for mode in ("all", "exec"):
            cfg, (trades, logs) = runs[mode]
            by_id = {t.plan_id: t for t in trades}
            busy, stops, per_day = None, collections.defaultdict(list), collections.Counter()
            for c, lg in zip(cands, logs):
                if c.log.reasons:
                    bad["precomputed_changed"] += lg.reasons != c.log.reasons
                    continue
                p = c.plan
                t = p.approval_time
                minute, day = _kst_minutes_and_day(t)
                exp = []
                if p.madi_id is not None and sum(e <= t for e in stops[p.madi_id]) >= 2:
                    exp.append(T.Reason.F8)
                if busy is not None and t < busy:
                    exp.append(T.Reason.F9)
                if cfg.apply_availability_mask and 30 <= minute < 450:
                    exp.append(T.Reason.MASK_DND)
                if cfg.apply_availability_mask and not exp and per_day[day] >= 6:
                    exp.append(T.Reason.MASK_DAILY_CAP)
                bad["reasons"] += tuple(exp) != lg.reasons
                if exp:
                    continue
                per_day[day] += cfg.apply_availability_mask
                tr = by_id[p.plan_id]
                bad["entry_before_active"] += tr.entry_time is not None and tr.entry_time < p.active_from
                bad["busy_before_approval"] += tr.busy_until < t
                busy = tr.busy_until if busy is None else max(busy, tr.busy_until)
                if tr.exit_reason == T.Exit.STOP and p.madi_id is not None:
                    stops[p.madi_id].append(tr.exit_bar_close_ns)
            ex = sorted(trades, key=lambda x: x.approval_time)
            bad["overlap"] += sum(b.approval_time < a.busy_until for a, b in zip(ex[:-1], ex[1:]))
    assert sum(bad.values()) == 0, dict(bad)


@pytest.mark.slow
def test_real_exec_bar_merge_boundary(real_runs):
    """5분봉 → 1분봉 전환: 마지막 5분봉 2023-09-30 23:55의 끝 = 첫 1분봉 시작, 겹침·빈 구간 없음 (§12.1)."""
    market, xb, _, _ = real_runs
    dur = xb.close_ns - xb.open_ns
    sw = int(np.searchsorted(xb.open_ns, C.EXEC_SWITCH_NS))
    assert xb.open_ns[sw] == C.EXEC_SWITCH_NS and xb.open_ns[sw - 1] == ns("2023-09-30 23:55")
    assert np.all(dur[:sw] == 5 * C.NS_PER_MIN) and np.all(dur[sw:] == C.NS_PER_MIN)
    assert np.all(xb.close_ns[:-1] == xb.open_ns[1:])
