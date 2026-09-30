"""시나리오 테스트 (DESIGN §9 T-SCN, RULES_SPEC §7·§12.1).

- 손으로 만든 문맥(make_ctx)에서 L1a·L1b·S2·S3의 가격·시각·사유·취소를 손 계산값과 비교한다.
- 실데이터 전체로 16조합(+ 민감도 변형)의 계약(정렬·ID·0.1 격자·시각 규칙·알게 된 시각·사유 일관성)을 검사한다.
"""
from __future__ import annotations

import collections
import time

import numpy as np
import pytest

from backtest import config as C
from backtest import filters as F
from backtest import scenarios as SC
from backtest.config import ComboConfig
from backtest.types import REASON_ORDER, Candidate, Plan, Reason, SignalLog
from backtest.tests.conftest import aggregate_bars, make_bars, ns
from backtest.tests.test_structure import flat_rows, madi_frame, make_ctx, make_ind, mask

MIN, HOUR = C.NS_PER_MIN, C.NS_PER_HOUR
AVAIL = C.AVAIL_DELAY_NS


def cands_of(ctx, scenario, direction_filter="DB", **kw):
    return SC.generate_candidates(ctx, ComboConfig(scenario, direction_filter, ctx.setting, **kw))


def on_grid(x: float) -> bool:
    return abs(x * 10 - round(x * 10)) < 1e-6


# ---------------------------------------------------------------------------
# L1a (§7.1, I-21, I-46)
# ---------------------------------------------------------------------------

L1A_MADI = dict(direction=1, a_idx=3, b_idx=7, a_price=100.0, b_price=102.0, h_cluster=101.0, vol_ab_mean=1000.0)


def l1a_ctx(edit=None, ind_kw=None, madi=None, **ctx_kw):
    rows = flat_rows(60, 101.5)                                    # 종가 101.5 > H, A 위, B + 0.5W(103) 아래
    if edit:
        edit(rows)
    bars = make_bars(rows)
    ind = make_ind(bars, **(ind_kw or {}))                         # ATR 0.6 → b 0.06
    madis = madi_frame([dict(L1A_MADI, **(madi or {}))], bars)
    return make_ctx(bars, ind, madis, **ctx_kw)


def test_l1a_prices_times_and_id():
    ctx = l1a_ctx()
    cs = cands_of(ctx, "L1a")
    assert len(cs) == 1
    c = cs[0]
    p = c.plan
    t_close = ns("2024-01-01 11:00")                               # T_B = 봉 10 마감
    assert c.log.reasons == () and c.log.status == "passed"
    assert (p.side, p.order_type, p.scenario) == (1, "limit", "L1a")
    assert (p.entry_price, p.stop, p.target) == (101.0, 99.9, 103.0)   # H, round(A − 0.1·ATR), round(H + W)
    assert p.signal_time == t_close and p.approval_time == t_close + AVAIL
    assert p.active_from == t_close + AVAIL + 10 * MIN
    assert p.valid_until == t_close + 24 * HOUR                    # §12.1 만료 = 신호 봉 마감 + 24 × 1h
    assert p.max_hold_ns == 72 * HOUR and p.atr_at_signal == 0.6
    assert p.cancel_effective_time is None and p.cancel_reason is None
    assert [r.kind for r in p.cancel_rules] == ["close_below", "high_above", "unhealthy_volume"]
    assert p.madi_id == "1hU-202401010700" and p.plan_id == "L1a_202401011100_1hU-202401010700"
    assert c.log.plan_id == p.plan_id and c.log.madi_id == p.madi_id and c.log.time == p.approval_time
    m = p.meta
    assert (m["A"], m["B"], m["W"], m["H"], m["s_idx"], m["tb_close_ns"]) == (100.0, 102.0, 2.0, 101.0, 10, t_close)
    assert m["net_rr"] == pytest.approx((2 - 0.0002 * 101 - 0.0002 * 103) / (1.1 + 0.0002 * 101 + 0.0007 * 99.9))
    assert m["d_pct"] == pytest.approx(1.1 / 101) and m["known_ns"] <= p.signal_time
    lat5 = cands_of(ctx, "L1a", latency_min=5)[0].plan
    assert lat5.active_from == t_close + AVAIL + 5 * MIN and lat5.valid_until == p.valid_until


@pytest.mark.parametrize("case,reason", [("close_eq_h", Reason.SC_CLOSE_VS_WAIST), ("slope60", Reason.SC_SLOPE60),
                                         ("unhealthy", Reason.SC_UNHEALTHY)])
def test_l1a_scenario_reasons(case, reason):
    edit, ind_kw = None, None
    if case == "close_eq_h":
        def edit(rows):
            rows[10] = [101.5, 101.5, 101.0, 101.0, 100.0]        # T_B 종가 == H → 조건(종가 > H) 실패
    elif case == "slope60":
        ind_kw = {"slope60": np.r_[np.ones(10), -1.0, np.ones(49)]}
    else:
        def edit(rows):
            rows[9][4] = 2900.0                                    # mean(vol[8..10]) = 1033 ≥ 1000 (I-21)
    c = cands_of(l1a_ctx(edit, ind_kw), "L1a")[0]
    assert c.log.reasons == (reason,) and c.log.status == "discarded"
    assert c.plan is not None                                      # 가격은 계산 가능 → 진단용 plan (DESIGN §6.7)


@pytest.mark.parametrize("k,field,value,kind", [(14, 3, 99.5, "close_below"), (13, 1, 103.5, "high_above"),
                                                (12, 4, 4600.0, "unhealthy_volume"), (34, 3, 99.5, "close_below"),
                                                (35, 3, 99.5, None)])
def test_l1a_cancel_first_bar_and_kind(k, field, value, kind):
    def edit(rows):
        rows[k][field] = value
        if field == 3:
            rows[k][2] = min(rows[k][2], value)
        if field == 1:
            rows[k][1] = value
    p = cands_of(l1a_ctx(edit), "L1a")[0].plan
    if kind is None:                                               # t+25 → 검사 범위(t+1..t+24) 밖
        assert p.cancel_effective_time is None
        return
    assert p.cancel_reason == kind
    assert p.cancel_effective_time == ns("2024-01-01 00:00") + (k + 1) * HOUR + AVAIL   # close_ns[k] + 60초
    assert p.order_end == min(p.valid_until, p.cancel_effective_time)


def test_l1a_cancel_same_bar_dict_order_and_warmup():
    def edit(rows):
        rows[13] = [101.5, 103.5, 99.0, 99.5, 100.0]              # 같은 봉: 종가 < A 그리고 고가 > B + 0.5W
    assert cands_of(l1a_ctx(edit), "L1a")[0].plan.cancel_reason == "close_below"
    c = cands_of(l1a_ctx(ind_kw={"valid": np.r_[np.ones(10), 0, np.ones(49)].astype(bool)}), "L1a")[0]
    assert c.log.reasons == (Reason.WARMUP,) and c.plan is None      # I-50
    assert c.log.meta["cand_id"] == "L1a_202401011100_1hU-202401010700"


def test_l1a_filters_and_risk_are_recorded():
    ctx = l1a_ctx(flags={"F6": mask(60, [10])}, d_slope=-1.0)
    c = cands_of(ctx, "L1a")[0]
    assert c.log.reasons == (Reason.F1, Reason.F6)                  # DB 롱 불허 + 박스
    wide = l1a_ctx(madi={"a_price": 99.0, "w": 3.0})               # d = 101 − 98.9 = 2.1 > 2% → 손절 폭
    assert Reason.RISK_STOP_BAND in cands_of(wide, "L1a")[0].log.reasons
    assert cands_of(l1a_ctx(), "L1a", "DA")[0].log.reasons == (Reason.F1,)   # D에 살아 있는 상승 마디 없음


# ---------------------------------------------------------------------------
# L1b (§7.2, I-15, I-22, I-23, I-44)
# ---------------------------------------------------------------------------

L1B_MADI = dict(direction=1, a_idx=3, b_idx=7, a_price=100.0, b_price=104.0, h_cluster=102.0, vol_ab_mean=1000.0)
FLAT_C = 103.2                                                     # 준비 구간 [102, 103] 위


def c_rows(n=160, price=FLAT_C):
    return [[price, price, price, price, 25.0] for _ in range(n)]


def arm_at_12(rows):
    """S 봉 12(C 48~51)의 저가 102.1 → 준비. 그 뒤 C 봉은 102.2."""
    rows[49] = [FLAT_C, FLAT_C, 102.1, 102.2, 25.0]
    for j in range(50, len(rows)):
        rows[j] = [102.2, 102.2, 102.2, 102.2, 25.0]


def l1b_ctx(rows, madi=None, ind_kw=None, **kw):
    c_bars = make_bars(rows, tf="15m")
    s_bars = aggregate_bars(c_bars, "1h")
    ind = make_ind(s_bars, **(ind_kw or {}))
    madis = madi_frame([dict(L1B_MADI, **(madi or {}))], s_bars)
    return make_ctx(s_bars, ind, madis, c_bars=c_bars, **kw)


def base_l1b_rows():
    rows = c_rows()
    arm_at_12(rows)
    rows[52] = [102.2, 102.5, 102.15, 102.45, 25.0]              # 확인: 양봉, 102.45 > 직전 고가 102.2, > H
    for j in range(53, len(rows)):
        rows[j] = [102.45, 102.45, 102.45, 102.45, 25.0]
    return rows


def test_l1b_confirm_prices_and_times():
    cs = cands_of(l1b_ctx(base_l1b_rows()), "L1b")
    assert len(cs) == 1
    c = cs[0]
    p = c.plan
    t_c = ns("2024-01-01 13:15")                                   # 확인 C 봉(13:00~13:15) 마감
    assert c.log.reasons == ()
    assert (p.side, p.order_type) == (1, "ioc_cap")
    assert p.entry_price == 102.6                                  # round(102.45 × 1.001)
    assert p.stop == 101.9                                         # round(min(102.1, 102.0) − 0.06)
    assert p.target == 106.1                                       # round(102.1 + 4)
    assert p.signal_time == t_c and p.approval_time == t_c + AVAIL
    assert p.valid_until == p.active_from == t_c + AVAIL + 10 * MIN   # IOC: 첫 실행 봉만 (I-44)
    assert p.cancel_effective_time is None and p.cancel_rules == ()
    m = p.meta
    assert (m["k_last"], m["arm_idx"], m["s_idx"], m["lowest"]) == (12, 12, 12, 102.1)
    assert m["arm_known_ns"] == ns("2024-01-01 13:00") and m["known_ns"] <= p.signal_time
    assert p.atr_at_signal == 0.6 and p.plan_id == "L1b_202401011315_1hU-202401010700"


def test_l1b_c_bar_closing_with_arm_bar_cannot_confirm():
    rows = c_rows()
    arm_at_12(rows)
    rows[51] = [102.2, 102.5, 102.15, 102.45, 25.0]              # 12:45~13:00 봉 = 준비 봉과 같은 시각에 마감
    for j in range(52, len(rows)):
        rows[j] = [102.45, 102.45, 102.45, 102.45, 25.0]
    assert cands_of(l1b_ctx(rows), "L1b") == []                    # 확인은 준비 봉 마감 "뒤" (I-22)


@pytest.mark.parametrize("n_below,expect", [(1, 1), (2, 0)])
def test_l1b_second_close_below_h_discards(n_below, expect):
    rows = c_rows()
    arm_at_12(rows)
    for j in range(52, 60):                                        # S 봉 13·14
        px = 101.8 if (j < 56 or n_below == 2) else 102.45
        rows[j] = [px, px, px, px, 25.0]
    prev = rows[59][3]
    rows[60] = [prev, 102.7, prev, 102.6, 25.0]                    # S 봉 15의 첫 C 봉: 확인 모양
    for j in range(61, len(rows)):
        rows[j] = [102.6, 102.6, 102.6, 102.6, 25.0]
    cs = cands_of(l1b_ctx(rows), "L1b")
    assert len(cs) == expect                                       # 첫 이탈은 버팀, 두 번째 이탈 뒤 확인은 무시
    if expect:
        assert cs[0].log.signal_time == ns("2024-01-01 15:15")


@pytest.mark.parametrize("c_idx,expect", [(147, 1), (148, 0)])
def test_l1b_24_bar_window(c_idx, expect):
    rows = c_rows()
    arm_at_12(rows)
    for j in range(50, len(rows)):
        rows[j] = [FLAT_C, FLAT_C, FLAT_C, FLAT_C, 25.0]           # 준비 뒤 구간 위에 머묾
    rows[c_idx] = [FLAT_C, 103.6, 103.1, 103.5, 25.0]              # 147: 창 끝(준비 + 24h)에 마감, 148: 넘음
    cs = cands_of(l1b_ctx(rows), "L1b")
    assert len(cs) == expect
    if expect:
        assert cs[0].log.signal_time == ns("2024-01-01 13:00") + 24 * HOUR


def test_l1b_one_setup_per_madi_rearm_diagnostic_health_and_death():
    """§7.2 마디당 준비 1회(I-22, 검토 SPEC-L1B-REARM): 확인 뒤 같은 마디에서 다시 준비하지 않는다.
    l1b_rearm=True(보고용 진단)는 검토 전 구현(옛 I-22) 해석대로 재준비한다."""
    rows = base_l1b_rows()
    rows[57] = [102.45, 102.8, 102.4, 102.7, 25.0]                # S 봉 13의 두 번째 준비 모양 → S 봉 14 안에서 확인 모양
    cs = cands_of(l1b_ctx(rows), "L1b")
    assert [c.log.meta["arm_idx"] for c in cs] == [12]            # 기본: 첫 준비 에피소드의 신호 하나뿐
    diag = cands_of(l1b_ctx(rows), "L1b", l1b_rearm=True)
    assert [c.log.meta["arm_idx"] for c in diag] == [12, 13]      # 진단: 재준비
    assert diag[1].log.signal_time == ns("2024-01-01 14:30") and diag[1].log.meta["k_last"] == 13
    assert diag[0].plan.plan_id == cs[0].plan.plan_id and diag[0].log.reasons == cs[0].log.reasons
    unhealthy = cands_of(l1b_ctx(base_l1b_rows(), madi={"vol_ab_mean": 100.0}), "L1b")
    assert unhealthy[0].log.reasons == (Reason.SC_UNHEALTHY,)      # mean(vol[8..12]) = 100 ≥ 100
    assert cands_of(l1b_ctx(base_l1b_rows(), madi={"end_idx": 11}), "L1b") == []    # 준비 전에 마디 사망
    assert len(cands_of(l1b_ctx(base_l1b_rows(), madi={"end_idx": 12}), "L1b")) == 1
    assert cands_of(l1b_ctx(rows, madi={"end_idx": 12}), "L1b", l1b_rearm=True)[-1].log.meta["arm_idx"] == 12  # k_last 13 > end
    with pytest.raises(ValueError):
        ComboConfig("L1a", "DB", "P1", l1b_rearm=True)            # L1b 전용 진단


def test_l1b_discarded_setup_is_not_rearmed():
    """§7.2 폐기(종가가 H 아래로 두 번째 마감) 뒤에는 같은 마디에서 다시 준비하지 않는다. 진단(l1b_rearm)만 재준비한다."""
    rows = c_rows()
    arm_at_12(rows)
    for j in range(52, 60):                                        # S 봉 13·14 종가 101.8 < H → 두 번째 이탈에서 폐기
        rows[j] = [101.8, 101.8, 101.8, 101.8, 25.0]
    for j in range(60, len(rows)):                                 # S 봉 15부터 저가 102.3 = 준비 구간 안
        rows[j] = [102.3, 102.3, 102.3, 102.3, 25.0]
    rows[64] = [102.3, 102.8, 102.3, 102.7, 25.0]                  # S 봉 16의 첫 C 봉: 확인 모양
    for j in range(65, len(rows)):
        rows[j] = [102.7, 102.7, 102.7, 102.7, 25.0]
    assert cands_of(l1b_ctx(rows), "L1b") == []
    diag = cands_of(l1b_ctx(rows), "L1b", l1b_rearm=True)
    assert [c.log.meta["arm_idx"] for c in diag] == [15] and diag[0].log.signal_time == ns("2024-01-01 16:15")


def test_l1b_filters_use_k_last():
    flags12 = {"F5": mask(40, [12])}
    assert cands_of(l1b_ctx(base_l1b_rows(), flags=flags12), "L1b")[0].log.reasons == (Reason.F5,)
    flags13 = {"F5": mask(40, [13])}                               # 확인 시각에 진행 중인 S 봉 13은 안 봄
    assert cands_of(l1b_ctx(base_l1b_rows(), flags=flags13), "L1b")[0].log.reasons == ()
    valid = np.ones(40, dtype=bool)
    valid[12] = False
    c = cands_of(l1b_ctx(base_l1b_rows(), ind_kw={"valid": valid}), "L1b")[0]
    assert c.log.reasons == (Reason.WARMUP,) and c.plan is None


# ---------------------------------------------------------------------------
# S2 (§7.3, I-24, I-47)
# ---------------------------------------------------------------------------

S2_MADI = dict(direction=1, a_idx=3, b_idx=7, a_price=99.0, b_price=104.0, h_cluster=102.0)


def s2_ctx(edit=None, madi=None, vr_at=(20,), **kw):
    rows = flat_rows(60, 103.0)
    rows[20] = [103.0, 103.2, 101.3, 101.5, 100.0]                # 음봉, 종가 < H
    rows[10] = [103.0, 103.2, 101.3, 101.5, 100.0]                # T_B 봉 자신도 같은 모양
    if edit:
        edit(rows)
    bars = make_bars(rows)
    vr = np.ones(60)
    vr[list(vr_at) + [10]] = 2.5
    ind = make_ind(bars, atr=0.8, vr=vr)
    kw.setdefault("d_slope", -1.0)                                 # DB 숏 허용
    return make_ctx(bars, ind, madi_frame([dict(S2_MADI, **(madi or {}))], bars), **kw)


def test_s2_plan_and_no_candidate_on_tb_bar():
    cs = cands_of(s2_ctx(), "S2")
    assert [c.log.meta["s_idx"] for c in cs] == [20]               # T_B(10) 봉은 후보 아님 (확정 "후", I-24)
    c = cs[0]
    p = c.plan
    assert c.log.reasons == ()                                     # 살아 있는 상승 마디가 있어도 F7 없음 (§7.3)
    assert (p.side, p.order_type, p.entry_price, p.target) == (-1, "limit", 102.0, 99.0)
    assert p.stop == 103.3                                         # round(max(103.2, 102 + 0.4) + 0.08)
    assert p.valid_until == ns("2024-01-01 21:00") + 12 * HOUR
    assert p.cancel_effective_time is None and p.madi_id == "1hU-202401010700"
    assert p.plan_id == "S2_202401012100_1hU-202401010700"


def test_s2_conditions_and_cancel():
    assert cands_of(s2_ctx(vr_at=()), "S2") == []                  # VR < 2
    def bullish(rows):
        rows[20] = [101.3, 103.2, 101.3, 101.5, 100.0]
    assert cands_of(s2_ctx(bullish), "S2") == []                   # 음봉 아님
    def above_h(rows):
        rows[20] = [103.0, 103.2, 102.0, 102.0, 100.0]
    assert cands_of(s2_ctx(above_h), "S2") == []                   # 종가 == H → 종가 < H 아님
    assert cands_of(s2_ctx(madi={"end_idx": 15}), "S2") == []      # 마디가 죽은 뒤
    def cancel(rows):
        rows[25] = [103.0, 104.5, 103.0, 104.2, 100.0]            # 종가 > B → 취소
    p = cands_of(s2_ctx(cancel), "S2")[0].plan
    assert p.cancel_reason == "close_above" and p.cancel_effective_time == ns("2024-01-02 02:00") + AVAIL
    assert cands_of(s2_ctx(d_slope=1.0), "S2")[0].log.reasons == (Reason.F1,)


# ---------------------------------------------------------------------------
# S3 (§7.4, I-25, I-47)
# ---------------------------------------------------------------------------


def s3_ctx(edit=None, swings=(10, 20), vr_at=(40,), madis=None, **kw):
    rows = flat_rows(70, 101.0)
    rows[10] = [101.0, 101.0, 97.0, 101.0, 100.0]                 # 더 아래 스윙 저점 (목표)
    rows[20] = [101.0, 101.0, 100.0, 101.0, 100.0]                # 지지선 스윙 저점 S = 100
    rows[30] = [101.0, 101.0, 100.05, 101.0, 100.0]               # 두 번째 터치 (±0.1%)
    rows[40] = [101.0, 101.0, 99.4, 99.5, 100.0]                  # 이탈 봉
    if edit:
        edit(rows)
    bars = make_bars(rows)
    vr = np.ones(70)
    vr[list(vr_at)] = 2.5
    ind = make_ind(bars, atr=0.8, vr=vr)
    kw.setdefault("d_slope", -1.0)
    return make_ctx(bars, ind, madi_frame(madis or [], bars), is_sl=mask(70, swings), **kw)


def test_s3_support_break_plan():
    ctx = s3_ctx()
    sup = SC.s3_support(ctx)
    assert sup[30] == -1 and sup[31] == 20 and sup[40] == 20 and sup[69] == 20   # 두 번째 터치(30) 뒤부터
    cs = cands_of(ctx, "S3")
    assert [c.log.meta["s_idx"] for c in cs] == [40]
    c = cs[0]
    p = c.plan
    assert c.log.reasons == () and p.madi_id is None and c.log.madi_id is None
    assert (p.side, p.entry_price, p.stop, p.target) == (-1, 100.0, 100.8, 97.0)   # S, S + ATR, 아래 스윙 저점
    assert p.meta["support_idx"] == 20 and p.meta["target_idx"] == 10 and p.meta["tb_close_ns"] == 0
    assert p.meta["support_known_ns"] == ns("2024-01-01 00:00") + 24 * HOUR       # 스윙 20 확정 = 봉 23 마감
    assert p.plan_id == "S3_202401021700_sup20"
    assert p.cancel_reason == "close_above"                         # 봉 41 종가 101 > S
    assert p.cancel_effective_time == ns("2024-01-02 18:00") + AVAIL


def test_s3_second_close_break_rule():
    def edit(rows):
        rows[41] = [99.5, 101.0, 99.5, 101.0, 100.0]               # 다시 위로
        rows[43] = [101.0, 101.0, 99.5, 99.6, 100.0]               # 두 번째 종가 이탈 (VR 1)
        rows[44] = [99.6, 99.8, 99.5, 99.7, 100.0]                 # 세 번째 → 아님
    cs = cands_of(s3_ctx(edit, vr_at=()), "S3")                    # 봉 40은 VR 1이고 첫 이탈 → 후보 아님
    assert [c.log.meta["s_idx"] for c in cs] == [43]
    assert cs[0].log.meta["n_prev"] == 1


def test_s3_no_target_waist_condition_and_touches():
    c = cands_of(s3_ctx(swings=(20,)), "S3")[0]
    assert Reason.SC_NO_TARGET in c.log.reasons and c.plan is None   # §7.4 목표 없으면 폐기
    below = dict(direction=1, a_idx=2, b_idx=5, a_price=90.0, b_price=110.0, end_idx=12)  # 확정(8)·죽음(13)
    c = cands_of(s3_ctx(madis=[dict(below, h_cluster=99.0)]), "S3")[0]
    assert c.log.reasons == (Reason.SC_CLOSE_VS_WAIST,)              # 종가 99.5 ≥ 가장 최근 상승 마디 허리 99
    assert c.log.meta["waist_madi_known_ns"] <= c.log.signal_time
    assert cands_of(s3_ctx(madis=[dict(below, h_cluster=101.0)]), "S3")[0].log.reasons == ()
    def one_touch(rows):
        rows[30] = [101.0, 101.0, 100.2, 101.0, 100.0]             # 0.2% 떨어짐 → 터치 아님
    assert cands_of(s3_ctx(one_touch), "S3") == []
    c = cands_of(s3_ctx(madis=[dict(below, end_idx=60)]), "S3")[0]  # 살아 있는 상승 마디 → F7
    assert Reason.F7 in c.log.reasons


# ---------------------------------------------------------------------------
# 공용 도우미 (I-37, I-45)
# ---------------------------------------------------------------------------


def test_first_cancel_index_and_geometry():
    conds = {"a": np.array([0, 0, 1, 1], bool), "b": np.array([0, 1, 1, 0], bool)}
    assert SC.first_cancel_index(conds, 0, 3) == (1, "b")
    assert SC.first_cancel_index(conds, 2, 3) == (2, "a")          # 같은 봉이면 dict 순서
    assert SC.first_cancel_index(conds, 3, 10) == (3, "a")         # 끝은 데이터 안으로 자름
    assert SC.first_cancel_index({"a": np.zeros(3, bool)}, 0, 2) == (None, None)
    assert SC.first_cancel_index(conds, 5, 9) == (None, None)
    base = dict(plan_id="x", scenario="L1a", side=1, signal_time=0, approval_time=0, active_from=0,
                order_type="limit", entry_price=100.0, stop=99.0, target=102.0, valid_until=0, max_hold_ns=0,
                atr_at_signal=1.0)
    assert SC.plan_geometry_ok(Plan(**base))
    assert not SC.plan_geometry_ok(Plan(**dict(base, target=100.0)))
    assert SC.plan_geometry_ok(Plan(**dict(base, side=-1, stop=101.0, target=98.0)))
    assert not SC.plan_geometry_ok(Plan(**dict(base, side=-1, stop=101.0, target=102.0)))
    assert SC.make_plan_id("S3", ns("2024-03-01 10:00"), "sup12") == "S3_202403011000_sup12"


def test_sort_candidates_i37():
    def cand(t, tb, pid):
        log = SignalLog(time=t, signal_time=t - AVAIL, scenario="L1b", side=1, status="discarded",
                        reasons=(Reason.F1,), plan_id=pid, meta={"tb_close_ns": tb})
        return Candidate(log=log)
    cs = [cand(200, 5, "b"), cand(100, 1, "z"), cand(200, 9, "c"), cand(200, 9, "a"), cand(200, 0, None)]
    got = [(c.log.time, c.log.meta["tb_close_ns"], c.log.plan_id) for c in SC.sort_candidates(cs)]
    assert got == [(100, 1, "z"), (200, 9, "a"), (200, 9, "c"), (200, 5, "b"), (200, 0, None)]


def test_generate_candidates_checks_context():
    ctx = l1a_ctx()
    with pytest.raises(ValueError):
        SC.generate_candidates(ctx, ComboConfig("L1a", "DB", "P2"))
    with pytest.raises(ValueError):
        SC.generate_candidates(ctx, ComboConfig("L1a", "DB", "P1", vr_threshold=3.0))


# ---------------------------------------------------------------------------
# 실데이터 전체: 16조합 + 민감도 변형의 계약
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_contexts():
    from backtest import data as D
    from backtest.types import MarketData
    try:
        bars = {tf: D.load_klines(tf) for tf in ("15m", "1h", "4h", "1d")}
    except FileNotFoundError as exc:                               # 데이터가 없는 환경
        pytest.skip(f"실데이터 없음: {exc}")
    market = MarketData(bars=bars, exec_bars=bars["1h"], funding=None, events_ns=None)
    return {p: SC.build_context(market, p) for p in C.SETTING_NAMES}


def _check_contract(ctx, cfg, cands):
    s_close = ctx.s_bars["close_ns"].to_numpy()
    c_close = ctx.c_bars["close_ns"].to_numpy()
    keys = [(c.log.time, -int(c.log.meta.get("tb_close_ns", 0)), c.log.plan_id or "") for c in cands]
    assert keys == sorted(keys)                                                     # I-37
    ids = [c.log.meta["cand_id"] for c in cands]
    assert len(set(ids)) == len(ids)
    n_valid = {"L1a": C.L1A_VALID_BARS, "S2": C.S2_VALID_BARS, "S3": C.S3_VALID_BARS}.get(cfg.scenario)
    for c in cands:
        log, p = c.log, c.plan
        assert log.scenario == cfg.scenario and log.side == cfg.side
        assert log.time == log.signal_time + AVAIL
        assert list(log.reasons) == [r for r in REASON_ORDER if r in log.reasons]
        assert log.status == ("discarded" if log.reasons else "passed")
        assert (log.madi_id is None) == (cfg.scenario == "S3")
        known = [v for k, v in log.meta.items() if k.endswith("known_ns") and v is not None]
        assert all(v <= log.signal_time for v in known)                            # 알게 된 시각 ≤ 신호 시각
        if Reason.WARMUP in log.reasons:
            assert log.reasons == (Reason.WARMUP,) and p is None
            continue
        if p is None:
            assert log.reasons and log.plan_id is None
            continue
        assert p.plan_id == log.plan_id == log.meta["cand_id"] and p.madi_id == log.madi_id
        assert all(on_grid(x) for x in (p.entry_price, p.stop, p.target))          # §7 0.1 USDT
        assert p.approval_time == p.signal_time + AVAIL and p.active_from == p.approval_time + cfg.latency_ns
        assert p.max_hold_ns == cfg.max_hold_ns and p.order_type == cfg.order_type
        s_idx = log.meta["s_idx"]
        if cfg.scenario == "L1b":
            assert p.valid_until == p.active_from and p.cancel_effective_time is None
            assert p.signal_time in c_close
            assert s_close[s_idx] <= p.signal_time and (s_idx + 1 == len(s_close) or s_close[s_idx + 1] > p.signal_time)
            assert p.atr_at_signal == ctx.s_ind["atr"].iloc[s_idx]
        else:
            assert p.signal_time == s_close[s_idx]
            assert p.valid_until == p.signal_time + n_valid * cfg.s_dur_ns
            if p.cancel_effective_time is not None:
                k = int(np.searchsorted(s_close, p.cancel_effective_time - AVAIL))
                assert s_close[k] + AVAIL == p.cancel_effective_time and s_idx < k <= s_idx + n_valid
        rr = F.risk_reasons(p.side, p.entry_price, p.stop, p.target, p.atr_at_signal, p.order_type)
        assert set(rr) == {r for r in log.reasons if r.startswith("RISK_")}
        assert (Reason.SC_BAD_GEOMETRY in log.reasons) == (not SC.plan_geometry_ok(p))
        if not log.reasons:
            assert SC.plan_geometry_ok(p) and p.meta["net_rr"] >= C.MIN_NET_RR - 1e-9
            assert 0 < p.meta["d_pct"] <= C.STOP_MAX_PCT + 1e-9


def test_real_data_contracts_all_combos(real_contexts):
    counts = collections.Counter()
    per_madi = collections.Counter()
    configs = C.g1_combos() + [c.replace(**C.L1B_REARM_VARIANT[1]) for c in C.g1_combos() if c.scenario == "L1b"]
    for cfg in configs:
        ctx = real_contexts[cfg.setting]
        t0 = time.perf_counter()
        cands = SC.generate_candidates(ctx, cfg)
        assert time.perf_counter() - t0 < 10.0                                     # DESIGN §10
        _check_contract(ctx, cfg, cands)
        name = cfg.base_key + ("_rearm" if cfg.l1b_rearm else "")
        counts[name] = sum(1 for c in cands if not c.log.reasons)
        if cfg.scenario == "L1b":
            per_madi[name] = max(collections.Counter(c.log.madi_id for c in cands).values())
        # F1 표본 대조: 기록된 F1~F7 사유 = filter_reasons 재계산
        sample = [c for c in cands if Reason.WARMUP not in c.log.reasons][::97]
        if sample:
            s_idx = np.array([c.log.meta["s_idx"] for c in sample])
            again = F.filter_reasons(ctx, cfg, s_idx, np.array([c.log.time for c in sample]))
            for c, fr in zip(sample, again):
                assert tuple(r for r in c.log.reasons if r.startswith("F")) == fr
    for key in ("L1a-DB-P1", "L1b-DB-P1", "L1b-DA-P1", "S2-DA-P1", "L1b-DA-P2_rearm"):
        assert counts[key] > 0, key                                                # 실데이터에서 통과 신호가 나온다
    for key in ("L1b-DA-P1", "L1b-DB-P1", "L1b-DA-P2", "L1b-DB-P2"):
        assert per_madi[key] == 1, key                                              # §7.2 마디당 준비 1회 (I-22)
        assert per_madi[key + "_rearm"] > 1, key                                    # 진단은 재준비


def test_real_data_da_db_same_candidates_and_variants(real_contexts):
    ctx = real_contexts["P2"]
    for scen in C.SCENARIOS:
        da = cands_of(ctx, scen, "DA")
        db = cands_of(ctx, scen, "DB")
        assert [c.log.meta["cand_id"] for c in da] == [c.log.meta["cand_id"] for c in db]   # 방향 필터는 F1만 바꿈
        for a, b in zip(da, db):
            strip = lambda rs: tuple(r for r in rs if r != Reason.F1)
            assert strip(a.log.reasons) == strip(b.log.reasons)
        mid = cands_of(ctx, scen, "DB", waist_method="midpoint")
        _check_contract(ctx, ComboConfig(scen, "DB", "P2", waist_method="midpoint"), mid)
        if scen == "L1a":
            assert [c.log.madi_id for c in mid] == [c.log.madi_id for c in db]
            madis = ctx.s_struct.madis.set_index("madi_id")
            for c in mid:
                if c.plan is not None:
                    assert c.plan.entry_price == madis.loc[c.log.madi_id, "h_mid"]      # 민감도: (고+저)÷2
    from backtest import data as D
    from backtest.types import MarketData
    bars = {tf: D.load_klines(tf) for tf in ("1h", "4h", "1d")}
    ctx3 = SC.build_context(MarketData(bars=bars, exec_bars=bars["1h"], funding=None), "P2", C.KIJUN_VR_SENSITIVITY)
    assert len(ctx3.s_struct.madis) < len(ctx.s_struct.madis)                       # VR 3 → 기준봉이 줄어듦
    cfg3 = ComboConfig("L1a", "DB", "P2", vr_threshold=C.KIJUN_VR_SENSITIVITY)
    _check_contract(ctx3, cfg3, SC.generate_candidates(ctx3, cfg3))
