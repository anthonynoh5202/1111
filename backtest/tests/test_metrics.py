"""통계 테스트 (DESIGN §9 T-MET, RULES_SPEC §8.3·§12.4).

알려진 값(논문 수치 예)·손 계산·완전 열거와 비교한다. 모두 합성 입력이라 빠르다.
"""
from __future__ import annotations

import itertools
import json
import math
from statistics import NormalDist

import numpy as np
import pytest

from backtest import config as C
from backtest import metrics as M
from backtest import types as T
from backtest.tests.conftest import ns

NAN = float("nan")


# ---------------------------------------------------------------------------
# 도우미: 거래·신호 기록 만들기
# ---------------------------------------------------------------------------


def mk_trade(pid: str, *, status: str = T.Status.FILLED, side: int = 1, approval: str = "2024-01-10 01:01",
             entry: str | None = "2024-01-10 01:20", exit_: str | None = "2024-01-10 05:00",
             exit_reason: str | None = "target", r: float = 1.0, size_fraction: float = 1.0,
             cost_multiplier: float = 1.0, meta: dict | None = None) -> T.TradeResult:
    filled = status == T.Status.FILLED
    a = ns(approval)
    return T.TradeResult(
        plan_id=pid, scenario="L1a" if side > 0 else "S2", side=side, order_type="limit",
        signal_time=a - C.NS_PER_MIN, approval_time=a, active_from=a + 10 * C.NS_PER_MIN,
        plan_entry=100.0, stop=99.0, target=102.0, status=status, busy_until=a + C.NS_PER_HOUR,
        risk_per_unit=1.0893,
        entry_time=ns(entry) if filled and entry else None, entry_price=100.0 if filled else None,
        exit_time=ns(exit_) if filled and exit_ else None, exit_price=101.0 if filled else None,
        exit_reason=exit_reason if filled else None, r_multiple=r if filled else NAN,
        size_fraction=size_fraction, cost_multiplier=cost_multiplier, meta=dict(meta or {}))


def mk_log(pid: str | None, reasons=(), status: str | None = None) -> T.SignalLog:
    st = status or ("discarded" if reasons else "passed")
    return T.SignalLog(time=ns("2024-01-10 01:01"), signal_time=ns("2024-01-10 01:00"), scenario="L1a", side=1,
                       status=st, reasons=T.sort_reasons(reasons), plan_id=pid)


def example_run():
    """손 계산용 실행: 체결 3건(롱 2, 숏 1) + 미체결 2건 + 폐기 3건."""
    trades = [
        # KST 10:01 승인 → day, 2024년, 목표 +1.5R
        mk_trade("t1", approval="2024-01-10 01:01", entry="2024-01-10 01:20", exit_="2024-01-10 09:00",
                 exit_reason="target", r=1.5, meta={"waist_fallback": False}),
        # KST 01:00 승인 → night, 2024년, 손절 −1R, 명목 상한으로 절반 크기
        mk_trade("t2", approval="2024-01-31 16:00", entry="2024-01-31 16:15", exit_="2024-02-01 03:00",
                 exit_reason="stop", r=-1.0, size_fraction=0.5, meta={"waist_fallback": True}),
        # KST 19:00 승인 → evening, 2025년, 숏 시간 청산 +0.4R, 마디 근거 아님(S3)
        mk_trade("t3", side=-1, approval="2025-03-01 10:00", entry="2025-03-01 10:15", exit_="2025-03-04 10:15",
                 exit_reason="time", r=0.4),
        mk_trade("t4", status=T.Status.CANCELLED),
        mk_trade("t5", status=T.Status.EXPIRED),
    ]
    logs = [mk_log(f"t{i}") for i in range(1, 6)] + [
        mk_log("x6", ("F4", "F1")), mk_log("x7", ("F9",)), mk_log(None, ("WARMUP",))]
    return trades, logs


# ---------------------------------------------------------------------------
# 1. 부트스트랩 (§12.4)
# ---------------------------------------------------------------------------


def test_bootstrap_constant_and_deterministic():
    assert M.bootstrap_mean_ci(np.full(25, 0.5)) == (0.5, 0.5)
    lo, hi = M.bootstrap_mean_ci(np.full(7, 0.1))
    assert lo == pytest.approx(0.1, abs=1e-15) and hi == pytest.approx(0.1, abs=1e-15)
    r = np.random.default_rng(3).normal(0.2, 1.0, 60)
    a = M.bootstrap_mean_ci(r, rng=C.make_rng("bootstrap", "k1"))
    b = M.bootstrap_mean_ci(r, rng=C.make_rng("bootstrap", "k1"))
    c = M.bootstrap_mean_ci(r, rng=C.make_rng("bootstrap", "k2"))
    assert a == b and a != c
    assert M.bootstrap_mean_ci(r) == M.bootstrap_mean_ci(r, rng=C.make_rng("bootstrap"))  # 기본 시드
    assert a[0] < r.mean() < a[1]


def test_bootstrap_hand_case_two_values():
    # [0, 1] 복원 추출 평균 ∈ {0, 0.5, 1} 확률 1/4·1/2·1/4 → 2.5% 분위 0, 97.5% 분위 1
    assert M.bootstrap_mean_ci(np.array([0.0, 1.0])) == (0.0, 1.0)


def test_bootstrap_matches_normal_approximation():
    # 큰 표본: 퍼센타일 CI ≈ 평균 ± 1.96·s/√n (중심극한정리)
    r = np.random.default_rng(11).standard_normal(400)
    lo, hi = M.bootstrap_mean_ci(r, rng=C.make_rng("bootstrap", "normal"))
    half = 1.959964 * r.std(ddof=1) / math.sqrt(r.size)
    assert (hi - lo) / 2 == pytest.approx(half, rel=0.06)
    assert (hi + lo) / 2 == pytest.approx(r.mean(), abs=0.1 * half)


def test_bootstrap_empty_and_nan():
    assert all(math.isnan(x) for x in M.bootstrap_mean_ci(np.array([])))
    assert all(math.isnan(x) for x in M.bootstrap_mean_ci(np.array([1.0, np.nan])))


def test_bootstrap_chunking_gives_same_result_as_one_block(monkeypatch):
    # 묶음 크기와 무관하게 같은 난수 순서 → 같은 결과 (결정성)
    r = np.random.default_rng(5).normal(0.1, 1.0, 37)
    a = M.bootstrap_mean_ci(r, n_boot=500, rng=C.make_rng("bootstrap", "chunk"))
    monkeypatch.setattr(M, "_CHUNK_ELEMS", 37 * 7)
    b = M.bootstrap_mean_ci(r, n_boot=500, rng=C.make_rng("bootstrap", "chunk"))
    assert a == b


# ---------------------------------------------------------------------------
# 2. PF (§8.3-3)
# ---------------------------------------------------------------------------


def test_profit_factor_hand_values():
    assert M.profit_factor(np.array([1.0, -0.5, 2.0])) == 6.0
    assert M.profit_factor(np.array([1.0, 0.0, 2.0])) == math.inf   # 손실 없음
    assert M.profit_factor(np.array([-1.0, -0.5])) == 0.0           # 이익 없음
    assert math.isnan(M.profit_factor(np.array([])))
    assert math.isnan(M.profit_factor(np.array([0.0, 0.0])))         # 둘 다 없음
    assert math.isnan(M.profit_factor(np.array([1.0, np.nan])))


# ---------------------------------------------------------------------------
# 3. 연도별 (§8.3-6, I-39)
# ---------------------------------------------------------------------------


def test_yearly_mean_none_for_empty_year_and_positive_count():
    r = np.array([1.0, -0.5, 0.2, -0.3, 0.0, 0.5])
    y = np.array([2020, 2020, 2021, 2022, 2023, 2026])
    ym = M.yearly_mean_r(r, y)
    assert list(ym) == list(C.G1_YEARS)
    assert ym[2020] == pytest.approx(0.25) and ym[2021] == pytest.approx(0.2)
    assert ym[2022] == pytest.approx(-0.3) and ym[2023] == 0.0 and ym[2026] == pytest.approx(0.5)
    assert ym[2024] is None and ym[2025] is None                    # 거래 없는 해
    assert M.positive_year_count(ym) == 3                           # 0.0·None은 양수 아님
    assert M.yearly_counts(y) == {2020: 2, 2021: 1, 2022: 1, 2023: 1, 2024: 0, 2025: 0, 2026: 1}
    with pytest.raises(ValueError):
        M.yearly_mean_r(r, y[:-1])


def test_utc_year_uses_utc_not_kst():
    # 2024-12-31 23:30 UTC = KST 2025-01-01 08:30 → UTC 연도 2024 (I-39)
    assert M.utc_year(np.array([ns("2024-12-31 23:30"), ns("2025-01-01 00:00")])).tolist() == [2024, 2025]


def test_positive_year_count_accepts_json_values():
    assert M.positive_year_count({"2020": 0.1, "2021": None, "2022": -0.2, "2023": 0.3}) == 2


# ---------------------------------------------------------------------------
# 샤프·왜도·첨도·연속 손실·낙폭
# ---------------------------------------------------------------------------


def test_sharpe_skew_kurt_hand_values():
    assert M.sharpe_per_trade(np.array([1.0, 2.0, 3.0])) == pytest.approx(2.0)  # 평균 2, 표본 표준편차 1
    assert math.isnan(M.sharpe_per_trade(np.array([1.0])))
    assert math.isnan(M.sharpe_per_trade(np.full(5, 0.1)))                  # std 0
    # 베르누이(p = 1/4): 왜도 (1 − 2p)/√(p(1−p)) = 2/√3, 비초과 첨도 3 + (1 − 6p(1−p))/(p(1−p)) = 7/3
    s, k = M.skew_kurtosis(np.array([0.0, 0.0, 0.0, 1.0]))
    assert s == pytest.approx(2 / math.sqrt(3), rel=1e-12) and k == pytest.approx(7 / 3, rel=1e-12)
    s, k = M.skew_kurtosis(np.array([-1.0, 0.0, 1.0]))
    assert s == pytest.approx(0.0, abs=1e-15) and k == pytest.approx(1.5)   # m2 = 2/3, m4 = 2/3 → 1.5
    assert all(math.isnan(x) for x in M.skew_kurtosis(np.array([1.0, 2.0])))
    assert all(math.isnan(x) for x in M.skew_kurtosis(np.full(4, 0.3)))


def test_consecutive_losses_and_drawdown_hand_values():
    r = np.array([1.0, -1.0, -1.0, 0.0, -1.0, -0.5, -0.2, 2.0, -1.0])
    assert M.max_consecutive_losses(r) == 3                # 0.0이 연속을 끊는다
    assert M.max_consecutive_losses(np.array([0.5, 0.0])) == 0
    assert M.max_consecutive_losses(np.array([])) == 0
    # 곡선 0, 1, 0, −1, −1, −2, −2.5, −2.7, −0.7, −1.7 → 최고 1에서 −2.7까지 3.7
    assert M.max_drawdown_r(r) == pytest.approx(3.7)
    assert M.max_drawdown_r(np.array([-1.0, 2.0])) == pytest.approx(1.0)   # 시작점 0에서 내려간 것도 낙폭
    assert M.max_drawdown_r(np.array([0.5, 1.0])) == 0.0
    assert math.isnan(M.max_drawdown_r(np.array([])))


def test_r_stats_keys_and_values():
    st = M.r_stats(np.array([1.5, -1.0, 0.4]))
    assert set(st) == {"n", "mean_r", "median_r", "std_r", "win_rate", "pf", "sharpe", "skew", "kurt", "sqn",
                       "total_r", "max_consec_losses", "max_drawdown_r"}
    assert st["n"] == 3 and st["mean_r"] == pytest.approx(0.3) and st["median_r"] == pytest.approx(0.4)
    assert st["win_rate"] == pytest.approx(2 / 3) and st["pf"] == pytest.approx(1.9)
    assert st["std_r"] == pytest.approx(np.std([1.5, -1.0, 0.4], ddof=1))
    assert st["sqn"] == pytest.approx(math.sqrt(3) * st["sharpe"]) and st["total_r"] == pytest.approx(0.9)
    empty = M.r_stats(np.array([]))
    assert empty["n"] == 0 and math.isnan(empty["mean_r"]) and empty["total_r"] == 0.0


# ---------------------------------------------------------------------------
# 4. DSR (Bailey·López de Prado 2014, I-41)
# ---------------------------------------------------------------------------


def test_dsr_paper_numerical_example():
    # 논문 수치 예: N = 100, 연율 샤프 분산 1/2, 최고 연율 샤프 2.5, 일간 T = 1250, 왜도 −3, 첨도 10
    # → 일간 기대 최대 샤프 SR0 ≈ 0.1132, DSR ≈ 0.9004 (연 250일로 일간 환산)
    sr0 = M.expected_max_sharpe(0.5 / 250, n_trials=100)
    assert sr0 == pytest.approx(0.1132, abs=5e-5)
    dsr = M.deflated_sharpe(2.5 / math.sqrt(250), 1250, -3.0, 10.0, 0.5 / 250, n_trials=100)
    assert dsr == pytest.approx(0.9004, abs=5e-5)


def test_dsr_matches_direct_formula():
    nd = NormalDist()
    g = 0.5772156649
    sr, n_obs, sk, ku, v, n_tr = 0.21, 80, -0.4, 4.2, 0.012, 16
    sr0 = math.sqrt(v) * ((1 - g) * nd.inv_cdf(1 - 1 / n_tr) + g * nd.inv_cdf(1 - 1 / (n_tr * math.e)))
    z = (sr - sr0) * math.sqrt(n_obs - 1) / math.sqrt(1 - sk * sr + (ku - 1) / 4 * sr ** 2)
    assert M.deflated_sharpe(sr, n_obs, sk, ku, v, n_tr) == pytest.approx(nd.cdf(z), rel=1e-9)
    assert M.deflated_sharpe(sr, n_obs, sk, ku, v) == M.deflated_sharpe(sr, n_obs, sk, ku, v, C.DSR_N_TRIALS)


def test_dsr_edge_cases():
    v = 0.02
    sr0 = M.expected_max_sharpe(v, 16)
    assert M.deflated_sharpe(sr0, 50, 0.0, 3.0, v) == pytest.approx(0.5, abs=1e-12)   # sr = SR0 → 0.5
    # 분산 0 → SR0 = 0 → PSR(0): 정규(왜도 0, 첨도 3)면 Φ(sr √(T−1) / √(1 + sr²/2))
    assert M.deflated_sharpe(0.1, 101, 0.0, 3.0, 0.0) == pytest.approx(
        NormalDist().cdf(0.1 * 10 / math.sqrt(1.005)), rel=1e-12)
    assert M.expected_max_sharpe(v, 1) == 0.0                                          # 시도 1개 → 보정 없음
    assert math.isnan(M.deflated_sharpe(0.1, 1, 0.0, 3.0, v))                          # n_obs < 2
    assert math.isnan(M.deflated_sharpe(NAN, 50, 0.0, 3.0, v))
    assert math.isnan(M.deflated_sharpe(0.1, 50, 0.0, 3.0, NAN))
    assert math.isnan(M.deflated_sharpe(0.1, 50, 0.0, 3.0, None))
    assert math.isnan(M.deflated_sharpe(2.0, 50, 5.0, 3.0, v))                         # 분모 안 1 − 10 + 2 < 0
    assert math.isnan(M.expected_max_sharpe(-0.1, 16)) and math.isnan(M.expected_max_sharpe(v, 0))


def test_sharpe_trials_variance_and_dsr_from_summary():
    assert M.sharpe_trials_variance([0.1, 0.2, None, NAN, 0.3]) == pytest.approx(0.01)
    assert math.isnan(M.sharpe_trials_variance([0.1, None]))
    summ = {"sharpe": 0.25, "n": 60, "skew": -0.2, "kurt": 3.5}
    assert M.dsr_from_summary(summ, 0.01) == M.deflated_sharpe(0.25, 60, -0.2, 3.5, 0.01, 16)
    assert math.isnan(M.dsr_from_summary({"sharpe": None, "n": 0, "skew": None, "kurt": None}, 0.01))


# ---------------------------------------------------------------------------
# 5. 부호 뒤집기 순열 검정 (I-42)
# ---------------------------------------------------------------------------


def test_sign_flip_all_positive_near_one_over_1024():
    p = M.sign_flip_pvalue(np.arange(1.0, 11.0))
    assert 0.3 / 1024 < p < 2.5 / 1024          # 부호가 모두 +일 때만 ≥ 관측 → 참 p = 1/1024
    k = p * (1 + C.PERM_N) - 1
    assert k == pytest.approx(round(k), abs=1e-9)   # p = (1 + 개수) ÷ (1 + 10,000) 격자


def test_sign_flip_symmetric_near_half():
    x = np.random.default_rng(2).standard_normal(50)
    p = M.sign_flip_pvalue(np.r_[x, -x], rng=C.make_rng("perm", "sym"))
    assert 0.45 < p < 0.56


def test_sign_flip_matches_exact_enumeration():
    r = np.array([0.5, -1.0, 2.0, 1.5, -0.3, 0.8, 1.2, -0.7])
    obs = r.sum()
    sums = [np.dot(s, r) for s in itertools.product((-1.0, 1.0), repeat=r.size)]
    p_exact = np.mean(np.array(sums) >= obs - 1e-12)          # 2^8 = 256가지 전부
    p = M.sign_flip_pvalue(r, rng=C.make_rng("perm", "exact"))
    assert p == pytest.approx(p_exact, abs=0.015)             # 몬테카를로 표준오차 ≤ 0.005
    assert p == M.sign_flip_pvalue(r, rng=C.make_rng("perm", "exact"))   # 결정적


def test_sign_flip_edge_cases():
    assert math.isnan(M.sign_flip_pvalue(np.array([])))
    assert math.isnan(M.sign_flip_pvalue(np.array([1.0, np.nan])))
    assert M.sign_flip_pvalue(np.zeros(5), n_perm=99) == 1.0      # 모든 부호 조합이 관측(0)과 같음
    assert M.sign_flip_pvalue(np.array([-1.0, -2.0, -3.0]), n_perm=1000) > 0.8


# ---------------------------------------------------------------------------
# 6. G1 판정 (§8.3)
# ---------------------------------------------------------------------------

GOOD = {"n": 40, "mean_r": 0.3, "boot_lo": 0.05, "pf": 1.5, "positive_years": 5}


def test_verdict_pass_and_keys():
    v = M.g1_verdict(GOOD, cost2_mean_r=0.1, random_p95=0.2)
    assert tuple(v) == M.VERDICT_KEYS
    assert all(v[k] is True for k in M.VERDICT_KEYS[:7]) and v["result"] == "pass"


def test_verdict_pending_below_30_trades():
    v = M.g1_verdict({**GOOD, "n": 29}, 0.1, 0.2)
    assert v["c7_enough_trades"] is False and v["result"] == "pending"
    assert v["c1_mean_r"] is True                            # 보류여도 나머지 조건은 참고로 계산
    assert M.g1_verdict({**GOOD, "n": 30}, 0.1, 0.2)["result"] == "pass"


@pytest.mark.parametrize("change, cost2, p95, broken", [
    ({"mean_r": 0.149}, 0.1, 0.1, "c1_mean_r"),
    ({"boot_lo": 0.0}, 0.1, 0.2, "c2_boot_lo"),
    ({"pf": 1.19}, 0.1, 0.2, "c3_pf"),
    ({}, 0.0, 0.2, "c4_cost2"),
    ({}, 0.1, 0.3, "c5_random"),                            # mean_r == p95 → 초과 아님
    ({"positive_years": 3}, 0.1, 0.2, "c6_years"),
])
def test_verdict_each_condition_breaks(change, cost2, p95, broken):
    v = M.g1_verdict({**GOOD, **change}, cost2, p95)
    assert v[broken] is False and v["result"] == "fail"
    assert all(v[k] for k in M.VERDICT_KEYS[:7] if k != broken)


def test_verdict_boundaries_inclusive_where_spec_says():
    v = M.g1_verdict({"n": 30, "mean_r": 0.15, "boot_lo": 1e-9, "pf": 1.2, "positive_years": 4}, 1e-9, 0.1499)
    assert v["result"] == "pass"                             # ≥ 0.15, ≥ 1.2, ≥ 4, ≥ 30 은 경계 포함


def test_verdict_none_and_nan_inputs_fail():
    v = M.g1_verdict({**GOOD, "boot_lo": None, "pf": NAN}, None, NAN)
    assert v["c2_boot_lo"] is False and v["c3_pf"] is False
    assert v["c4_cost2"] is False and v["c5_random"] is False and v["result"] == "fail"
    v = M.g1_verdict({}, None, None)
    assert v["result"] == "pending" and not any(v[k] for k in M.VERDICT_KEYS[:7])
    # JSON에서 읽은 값: PF "inf"(손실 없음)은 통과
    assert M.g1_verdict({**GOOD, "pf": "inf"}, 0.1, 0.2)["c3_pf"] is True


# ---------------------------------------------------------------------------
# 7. summarize_run (DESIGN §8.2)
# ---------------------------------------------------------------------------


def test_summarize_run_keys_follow_design_order():
    trades, logs = example_run()
    s = M.summarize_run(trades, logs, span_weeks=10.0, rng_key="L1a-DA-P1_exec")
    assert tuple(s) == M.RUN_SUMMARY_KEYS + M.RUN_SUMMARY_EXTRA_KEYS
    assert set(M.RUN_SUMMARY_KEYS) == {
        "n_candidates", "n_passed", "discard_first_reason", "discard_any_reason", "status_counts", "exit_counts",
        "n", "n_long", "n_short", "mean_r", "median_r", "std_r", "win_rate", "pf", "boot_lo", "boot_hi",
        "sharpe", "skew", "kurt", "yearly", "positive_years", "perm_p", "mean_r_account", "mean_size_fraction",
        "by_session", "by_side", "waist_fallback_rate", "span_weeks", "passed_per_week", "g3_weeks_to_150"}


def test_summarize_run_hand_values():
    trades, logs = example_run()
    s = M.summarize_run(trades, logs, span_weeks=10.0, rng_key="L1a-DA-P1_exec")
    assert (s["n_candidates"], s["n_passed"]) == (8, 5)
    assert s["discard_first_reason"]["F1"] == 1 and s["discard_first_reason"]["F4"] == 0
    assert s["discard_first_reason"]["F9"] == 1 and s["discard_first_reason"]["WARMUP"] == 1
    assert s["discard_any_reason"]["F4"] == 1 and s["discard_any_reason"]["F1"] == 1
    assert list(s["discard_first_reason"]) == list(T.REASON_ORDER)
    assert s["status_counts"] == {"filled": 3, "cancelled": 1, "expired": 1, "not_filled": 0}
    assert s["exit_counts"] == {"stop": 1, "target": 1, "time": 1, "eod": 0}
    assert (s["n"], s["n_long"], s["n_short"]) == (3, 2, 1)
    assert s["mean_r"] == pytest.approx(0.3) and s["median_r"] == pytest.approx(0.4)
    assert s["win_rate"] == pytest.approx(2 / 3) and s["pf"] == pytest.approx(1.9)
    assert s["yearly"][2024] == pytest.approx(0.25) and s["yearly"][2025] == pytest.approx(0.4)
    assert s["yearly"][2020] is None and s["positive_years"] == 2
    assert s["yearly_n"][2024] == 2 and s["yearly_n"][2025] == 1 and s["yearly_n"][2023] == 0
    assert s["by_session"]["day"] == {"n": 1, "mean_r": 1.5}
    assert s["by_session"]["night"] == {"n": 1, "mean_r": -1.0}
    assert s["by_session"]["evening"]["n"] == 1 and s["by_session"]["evening"]["mean_r"] == pytest.approx(0.4)
    assert s["by_side"]["long"]["n"] == 2 and s["by_side"]["long"]["mean_r"] == pytest.approx(0.25)
    assert s["by_side"]["short"]["n"] == 1 and s["by_side"]["short"]["mean_r"] == pytest.approx(0.4)
    assert s["waist_fallback_rate"] == 0.5
    assert s["mean_r_account"] == pytest.approx((1.5 - 0.5 + 0.4) / 3)
    assert s["mean_size_fraction"] == pytest.approx(2.5 / 3)
    assert s["passed_per_week"] == pytest.approx(0.5) and s["g3_weeks_to_150"] == pytest.approx(300.0)
    assert s["max_consec_losses"] == 1 and s["max_drawdown_r"] == pytest.approx(1.0)
    r_sorted = np.array([1.5, -1.0, 0.4])
    assert (s["boot_lo"], s["boot_hi"]) == M.bootstrap_mean_ci(
        r_sorted, rng=C.make_rng("bootstrap", "L1a-DA-P1_exec"))
    assert s["perm_p"] == M.sign_flip_pvalue(r_sorted, rng=C.make_rng("perm", "L1a-DA-P1_exec"))


def test_summarize_run_orders_by_realization_time():
    # 입력 순서가 뒤섞여도 청산 시각 순으로 연속 손실·낙폭을 계산한다
    a = mk_trade("a", entry="2024-03-01 00:00", exit_="2024-03-01 05:00", r=-1.0)
    b = mk_trade("b", entry="2024-03-02 00:00", exit_="2024-03-02 05:00", r=2.0)
    c = mk_trade("c", entry="2024-03-03 00:00", exit_="2024-03-03 05:00", r=-1.0)
    s = M.summarize_run([c, a, b], [], span_weeks=1.0, rng_key="order")
    assert s["max_consec_losses"] == 1 and s["max_drawdown_r"] == pytest.approx(1.0)
    assert s == M.summarize_run([a, b, c], [], span_weeks=1.0, rng_key="order")


def test_summarize_run_empty_is_jsonable_without_errors():
    s = M.summarize_run([], [], span_weeks=0.0, rng_key="empty")
    assert s["n"] == 0 and math.isnan(s["mean_r"]) and math.isnan(s["pf"]) and math.isnan(s["boot_lo"])
    assert math.isnan(s["perm_p"]) and s["positive_years"] == 0 and s["waist_fallback_rate"] is None
    assert math.isnan(s["passed_per_week"]) and math.isnan(s["g3_weeks_to_150"])
    assert s["max_consec_losses"] == 0 and math.isnan(s["max_drawdown_r"])
    json.dumps(T.to_jsonable(s), allow_nan=False)                     # NaN 토큰 없음
    assert M.g1_verdict(s, None, None)["result"] == "pending"
    s2 = M.summarize_run([], [mk_log("p")], span_weeks=2.0, rng_key="empty")
    assert s2["passed_per_week"] == 0.5
    s3 = M.summarize_run([], [], span_weeks=2.0, rng_key="empty")
    assert s3["g3_weeks_to_150"] == math.inf                         # 신호 0건 → 끝나지 않음


def test_summarize_run_deterministic_and_rejects_bad_r():
    trades, logs = example_run()
    a = json.dumps(T.to_jsonable(M.summarize_run(trades, logs, span_weeks=3.0, rng_key="k")))
    b = json.dumps(T.to_jsonable(M.summarize_run(trades, logs, span_weeks=3.0, rng_key="k")))
    assert a == b
    bad = [mk_trade("bad", r=NAN)]
    with pytest.raises(ValueError):
        M.summarize_run(bad, [], span_weeks=1.0, rng_key="k")


def test_filled_r_filters_and_years():
    trades, _ = example_run()
    r, y = M.filled_r(trades)
    assert r.tolist() == [1.5, -1.0, 0.4] and y.tolist() == [2024, 2024, 2025]
    r0, y0 = M.filled_r([])
    assert r0.shape == (0,) and y0.shape == (0,)


# ---------------------------------------------------------------------------
# 비용 2배 비교 (§8.3-4, I-27)
# ---------------------------------------------------------------------------


def test_cost_stress_summary_same_trades():
    base, _ = example_run()
    stress = [mk_trade(t.plan_id, status=t.status, side=t.side, r=t.r_multiple - 0.1, cost_multiplier=2.0,
                       approval=C.ns_to_iso(t.approval_time),
                       entry=C.ns_to_iso(t.entry_time) if t.entry_time else None,
                       exit_=C.ns_to_iso(t.exit_time) if t.exit_time else None, exit_reason=t.exit_reason)
              for t in base]
    out = M.summarize_cost_stress(base, stress, rng_key="L1a-DA-P1_cost2_exec")
    assert {"n", "mean_r", "pf", "boot_lo"} <= set(out)              # DESIGN §8.1 exec_cost2 키
    assert out["n"] == 3 and out["mean_r"] == pytest.approx(0.2) and out["mean_r_base"] == pytest.approx(0.3)
    assert out["delta_mean_r"] == pytest.approx(-0.1) and out["same_trades"] is True
    assert out["cost_multiplier"] == 2.0 and out["pf"] == pytest.approx(1.7 / 1.1)
    moved = list(stress)
    moved[0] = mk_trade("t1", r=1.4, entry="2024-01-10 01:20", exit_="2024-01-10 10:00", cost_multiplier=2.0)
    assert M.summarize_cost_stress(base, moved, rng_key="x")["same_trades"] is False


def test_marketable_limit_summary_counts_flagged_fills():
    """검토 LA-2·F4: 즉시 체결될 지정가(meta['marketable_edge_r'])의 건수·엔진 유리 건수·합·평균을 요약한다."""
    trades = [mk_trade("a", meta={"marketable_open": 99.9, "marketable_edge_r": -0.2}),
              mk_trade("b", meta={"marketable_open": 99.99, "marketable_edge_r": 0.05}),
              mk_trade("c", meta={"marketable_open": 99.995, "marketable_edge_r": 0.01}),
              mk_trade("d"), mk_trade("e", status=T.Status.EXPIRED, meta={"marketable_edge_r": 9.0})]
    s = M.summarize_run(trades, [], span_weeks=1.0, rng_key="mk")
    ml = s["marketable_limit"]
    assert ml["n"] == 3 and ml["n_engine_favorable"] == 2                      # 미체결은 세지 않는다
    assert ml["favorable_r_sum"] == pytest.approx(0.06) and ml["mean_edge_r"] == pytest.approx(-0.14 / 3)
    none = M.marketable_limit_summary([mk_trade("d")])
    assert none["n"] == 0 and none["n_engine_favorable"] == 0 and math.isnan(none["mean_edge_r"])
    json.dumps(T.to_jsonable(s), allow_nan=False)
