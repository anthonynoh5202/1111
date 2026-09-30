"""통계 — 거래 R 요약, 부트스트랩, PF, 연도별, DSR, 순열 검정, G1 판정 (§8.3, §12.4).

담당: 통계·기준선. 설계: backtest/DESIGN.md §6.10, 해석 확정 I-39, I-41, I-42.

- 입력 R은 TradeResult.r_multiple(체결된 거래만). scipy가 없으므로 정규분포는 statistics.NormalDist를 쓴다.
- 난수는 config.make_rng(...)로 만든다(결정적). 분위는 numpy 'linear'.
- 값을 계산할 수 없으면(거래 0건 등) None/NaN을 돌려주고 예외를 내지 않는다.
  (단, 체결된 거래의 R이 NaN·inf면 체결 엔진 오류이므로 filled_r가 ValueError를 낸다 — 조용히 빼면 결과가 왜곡된다.)
- R 배열 함수는 유한한 값을 전제한다. NaN이 섞이면 실수형 결과는 NaN이다(성과를 부풀리지 않는 쪽).

공개 함수
- 배열 → 통계: bootstrap_mean_ci, profit_factor, yearly_mean_r, yearly_counts, positive_year_count,
  sharpe_per_trade, skew_kurtosis, max_consecutive_losses, max_drawdown_r, sign_flip_pvalue, r_stats
- 다중 시험 보정: expected_max_sharpe(SR₀), deflated_sharpe, sharpe_trials_variance, dsr_from_summary
- 실행 요약·판정: filled_r, summarize_run(§8.2 RunSummary), marketable_limit_summary(즉시 체결될 지정가 보고),
  summarize_cost_stress(비용 2배 비교), g1_verdict
"""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from statistics import NormalDist

import numpy as np

from backtest import config as C
from backtest.types import (EXIT_REASONS, PLAN_STATUSES, REASON_ORDER, SignalLog, Status, TradeResult)

EULER_GAMMA = 0.5772156649015329  # I-41 오일러-마스케로니 상수 γ
_NORMAL = NormalDist()            # 표준정규 Φ, Φ⁻¹ (scipy 없음)
_CHUNK_ELEMS = 2_000_000          # 부트스트랩·순열에서 한 번에 만드는 난수 원소 수 (메모리 약 16MB)
_NAN = float("nan")

# DESIGN §8.2 RunSummary 키 (이 순서로 만든다)
RUN_SUMMARY_KEYS = (
    "n_candidates", "n_passed", "discard_first_reason", "discard_any_reason", "status_counts", "exit_counts",
    "n", "n_long", "n_short", "mean_r", "median_r", "std_r", "win_rate", "pf", "boot_lo", "boot_hi",
    "sharpe", "skew", "kurt", "yearly", "positive_years", "perm_p", "mean_r_account", "mean_size_fraction",
    "by_session", "by_side", "waist_fallback_rate", "span_weeks", "passed_per_week", "g3_weeks_to_150",
)
# §8.2 목록 뒤에 덧붙이는 보조 키 (리드 요구: 연도별 거래 수, 최대 연속 손실, R 곡선 최대 낙폭 등,
# 검토 LA-2·F4: 즉시 체결될 지정가를 지정가·메이커로 체결한 건수와 원가 차이)
RUN_SUMMARY_EXTRA_KEYS = ("yearly_n", "total_r", "sqn", "max_consec_losses", "max_drawdown_r", "marketable_limit")

# g1_verdict 반환 키 (DESIGN §8.1 verdict)
VERDICT_KEYS = ("c1_mean_r", "c2_boot_lo", "c3_pf", "c4_cost2", "c5_random", "c6_years", "c7_enough_trades",
                "result")


# ---------------------------------------------------------------------------
# 작은 도우미
# ---------------------------------------------------------------------------


def _as_r(r) -> np.ndarray:
    """R 값 → 1차원 float64 배열."""
    return np.asarray(r, dtype=np.float64).ravel()


def _all_finite(r: np.ndarray) -> bool:
    return bool(np.all(np.isfinite(r)))


def _num(x) -> float:
    """None·문자열('inf', '-inf')·숫자 → float. 해석할 수 없으면 NaN (JSON으로 돌아온 값도 받는다)."""
    if x is None:
        return _NAN
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("inf", "+inf", "infinity"):
            return math.inf
        if s in ("-inf", "-infinity"):
            return -math.inf
        try:
            return float(s)
        except ValueError:
            return _NAN
    try:
        return float(x)
    except (TypeError, ValueError):
        return _NAN


def _ge(a: float, b: float) -> bool:
    """a ≥ b. 어느 쪽이든 NaN이면 False(계산 불가 = 실패)."""
    return bool(a >= b) if not (math.isnan(a) or math.isnan(b)) else False


def _gt(a: float, b: float) -> bool:
    """a > b. 어느 쪽이든 NaN이면 False."""
    return bool(a > b) if not (math.isnan(a) or math.isnan(b)) else False


def _mean_or_nan(x) -> float:
    x = _as_r(x)
    return float(x.mean()) if x.size else _NAN


def utc_year(ns) -> np.ndarray:
    """int64 ns 시각 → UTC 연도 (int64 배열, I-39)."""
    a = np.asarray(ns, dtype=np.int64)
    return a.astype("datetime64[ns]").astype("datetime64[Y]").astype(np.int64) + 1970


def _filled(trades: Iterable[TradeResult]) -> list[TradeResult]:
    """체결된 거래만 (입력 순서)."""
    return [t for t in trades if t.status == Status.FILLED]


def _chronological(filled: list[TradeResult]) -> list[TradeResult]:
    """체결 거래를 실현 순서(청산 시각, 같으면 진입 시각)로 안정 정렬. run_sequence 결과는 이미 이 순서다(F9)."""
    if any(t.entry_time is None or t.exit_time is None for t in filled):
        raise ValueError("체결 거래에 entry_time/exit_time이 없음")
    return sorted(filled, key=lambda t: (int(t.exit_time), int(t.entry_time)))


# ---------------------------------------------------------------------------
# 체결 거래 → R 배열
# ---------------------------------------------------------------------------


def filled_r(trades: list[TradeResult]) -> tuple[np.ndarray, np.ndarray]:
    """체결된 거래의 (r_multiple 배열, 진입 시각 UTC 연도 배열). 순서는 입력 순서.

    체결 거래의 R이 NaN·inf이거나 진입 시각이 없으면 ValueError (체결 엔진 오류를 조용히 넘기지 않는다).
    """
    filled = _filled(trades)
    r = np.array([t.r_multiple for t in filled], dtype=np.float64)
    if not _all_finite(r):
        bad = [t.plan_id for t in filled if not math.isfinite(t.r_multiple)][:5]
        raise ValueError(f"체결 거래의 r_multiple이 유한하지 않음: {bad}")
    if any(t.entry_time is None for t in filled):
        raise ValueError("체결 거래에 entry_time이 없음")
    years = utc_year(np.array([t.entry_time for t in filled], dtype=np.int64))  # I-39 진입 시각의 UTC 연도
    return r, years


# ---------------------------------------------------------------------------
# 기본 통계
# ---------------------------------------------------------------------------


def bootstrap_mean_ci(r: np.ndarray, *, n_boot: int = C.BOOTSTRAP_N, rng: np.random.Generator | None = None,
                      lower_q: float = C.BOOTSTRAP_LOWER_Q) -> tuple[float, float]:
    """복원 추출 평균의 (lower_q, 1 − lower_q) 분위 = (하한, 상한) (§12.4). 빈 배열이면 (nan, nan).

    rng가 None이면 config.make_rng('bootstrap').
    반복마다 n개를 복원 추출해 평균을 내고(퍼센타일 부트스트랩), 분위는 numpy 'linear'.
    메모리를 아끼려고 반복을 묶음으로 나눠 뽑는다(같은 생성기에서 순서대로 뽑으므로 결과는 결정적).
    """
    r = _as_r(r)
    n = r.size
    if n == 0 or not _all_finite(r):
        return _NAN, _NAN
    if int(n_boot) < 1:
        raise ValueError(f"n_boot는 1 이상: {n_boot!r}")
    if not 0.0 < lower_q < 0.5:
        raise ValueError(f"lower_q는 (0, 0.5) 안: {lower_q!r}")
    rng = C.make_rng("bootstrap") if rng is None else rng
    n_boot = int(n_boot)
    means = np.empty(n_boot, dtype=np.float64)
    rows = max(1, _CHUNK_ELEMS // n)
    for s in range(0, n_boot, rows):
        e = min(n_boot, s + rows)
        idx = rng.integers(0, n, size=(e - s, n))    # §12.4 거래 R을 복원 추출
        means[s:e] = r[idx].mean(axis=1)
    lo, hi = np.quantile(means, [lower_q, 1.0 - lower_q])  # §12.4 평균의 2.5% 분위 = 하한
    return float(lo), float(hi)


def profit_factor(r: np.ndarray) -> float:
    """PF = 양수 R 합 ÷ |음수 R 합|. 손실이 없고 이익이 있으면 inf, 둘 다 없으면 nan."""
    r = _as_r(r)
    if r.size == 0 or np.isnan(r).any():
        return _NAN
    gain = float(r[r > 0].sum())
    loss = float(-r[r < 0].sum())
    if loss > 0:
        return gain / loss                           # §8.3-3 총이익 R ÷ 총손실 R
    return math.inf if gain > 0 else _NAN


def yearly_mean_r(r: np.ndarray, years: np.ndarray, all_years: tuple[int, ...] = C.G1_YEARS) -> dict[int, float | None]:
    """연도별 평균 R. 거래가 없는 해는 None (양수 연도로 세지 않는다, I-39).

    키는 all_years만(순서 그대로). all_years 밖의 연도 거래는 이 표에 넣지 않는다.
    """
    r = _as_r(r)
    years = np.asarray(years, dtype=np.int64).ravel()
    if r.shape != years.shape:
        raise ValueError(f"r과 years 길이가 다름: {r.shape} vs {years.shape}")
    out: dict[int, float | None] = {}
    for y in all_years:
        m = years == int(y)
        out[int(y)] = float(r[m].mean()) if m.any() else None
    return out


def yearly_counts(years: np.ndarray, all_years: tuple[int, ...] = C.G1_YEARS) -> dict[int, int]:
    """연도별 거래 수 (all_years 순서, 없는 해는 0)."""
    years = np.asarray(years, dtype=np.int64).ravel()
    return {int(y): int(np.count_nonzero(years == int(y))) for y in all_years}


def positive_year_count(yearly: dict) -> int:
    """평균 R이 0보다 큰 연도 수 (§8.3-6). None(거래 없음)·0·NaN은 양수가 아니다 (I-39)."""
    return sum(1 for v in yearly.values() if _gt(_num(v), 0.0))


def sharpe_per_trade(r: np.ndarray) -> float:
    """거래당 샤프 = mean ÷ std(ddof=1). 2건 미만이거나 std = 0이면 nan."""
    r = _as_r(r)
    if r.size < 2 or not _all_finite(r) or np.all(r == r[0]):
        return _NAN  # 모든 값이 같으면 std = 0 (반올림 오차로 생기는 아주 작은 std를 믿지 않는다)
    sd = float(r.std(ddof=1))
    return float(r.mean()) / sd if sd > 0 else _NAN


def skew_kurtosis(r: np.ndarray) -> tuple[float, float]:
    """(왜도, 첨도) — 모멘트 방식(ddof=0), 첨도는 초과 첨도가 아닌 값(정규 = 3). 3건 미만이면 (nan, nan).

    m_k = mean((r − r̄)^k), 왜도 = m3 ÷ m2^1.5, 첨도 = m4 ÷ m2² (I-41). 모든 값이 같으면 (nan, nan).
    """
    r = _as_r(r)
    if r.size < 3 or not _all_finite(r) or np.all(r == r[0]):
        return _NAN, _NAN
    d = r - r.mean()
    m2 = float(np.mean(d * d))
    if not m2 > 0:
        return _NAN, _NAN
    m3 = float(np.mean(d ** 3))
    m4 = float(np.mean(d ** 4))
    return m3 / m2 ** 1.5, m4 / m2 ** 2


def max_consecutive_losses(r: np.ndarray) -> int:
    """가장 긴 연속 손실(R < 0) 거래 수. R = 0은 손실이 아니다(연속을 끊는다). 순서는 입력 순서(시간순으로 줄 것)."""
    loss = _as_r(r) < 0
    if not loss.any():
        return 0
    edge = np.diff(np.r_[0, loss.astype(np.int8), 0])
    starts = np.flatnonzero(edge == 1)
    ends = np.flatnonzero(edge == -1)
    return int((ends - starts).max())


def max_drawdown_r(r: np.ndarray) -> float:
    """R 누적 곡선(0에서 시작, 거래마다 R을 더함)의 최대 낙폭 (R 단위, 양수). 빈 배열이면 nan.

    곡선 = [0, r₁, r₁+r₂, …], 낙폭 = max(지금까지 최고점 − 현재). 순서는 입력 순서(시간순으로 줄 것).
    """
    r = _as_r(r)
    if r.size == 0 or not _all_finite(r):
        return _NAN
    curve = np.r_[0.0, np.cumsum(r)]
    peak = np.maximum.accumulate(curve)
    return float(np.max(peak - curve))


def sign_flip_pvalue(r: np.ndarray, *, n_perm: int = C.PERM_N, rng: np.random.Generator | None = None) -> float:
    """부호 뒤집기 순열 검정 (한쪽, 귀무: 평균 ≤ 0, I-42).

    p = (1 + #{무작위 부호 평균 ≥ 관측 평균}) ÷ (1 + n_perm). rng None이면 config.make_rng('perm'). 빈 배열이면 nan.
    귀무가설(R 분포가 0에 대해 대칭)에서는 각 R의 부호가 ± 반반이므로 부호를 무작위로 바꾼 평균의 분포와 비교한다.
    평균 대신 합을 비교한다(n이 같으므로 동치). 합산 순서 차이의 부동소수 오차는 '같음'으로 본다(p가 커지는 쪽).
    """
    r = _as_r(r)
    n = r.size
    if n == 0 or not _all_finite(r):
        return _NAN
    if int(n_perm) < 1:
        raise ValueError(f"n_perm은 1 이상: {n_perm!r}")
    rng = C.make_rng("perm") if rng is None else rng
    n_perm = int(n_perm)
    obs = float(np.sum(r))
    tol = 1e-12 * max(1.0, float(np.sum(np.abs(r))))
    count = 0
    rows = max(1, _CHUNK_ELEMS // n)
    for s in range(0, n_perm, rows):
        k = min(rows, n_perm - s)
        flip = rng.integers(0, 2, size=(k, n), dtype=np.int8).astype(bool)   # I-42 부호 무작위화
        sums = np.where(flip, -r, r).sum(axis=1)
        count += int(np.count_nonzero(sums >= obs - tol))
    return (1 + count) / (1 + n_perm)                                         # I-42 p = (1 + #≥관측) ÷ (1 + N)


def r_stats(r: np.ndarray) -> dict:
    """R 배열 하나의 기본 요약 (순서 = 시간순으로 줄 것: 연속 손실·낙폭이 순서에 의존).

    반환 키: n, mean_r, median_r, std_r(ddof=1), win_rate(R > 0 비율), pf, sharpe, skew, kurt,
    sqn(√n × 샤프), total_r, max_consec_losses, max_drawdown_r. 계산할 수 없으면 NaN.
    """
    r = _as_r(r)
    n = int(r.size)
    ok = n > 0 and _all_finite(r)
    sharpe = sharpe_per_trade(r)
    skew, kurt = skew_kurtosis(r)
    return {
        "n": n,
        "mean_r": float(r.mean()) if ok else _NAN,
        "median_r": float(np.median(r)) if ok else _NAN,
        "std_r": float(r.std(ddof=1)) if ok and n >= 2 else _NAN,
        "win_rate": float(np.mean(r > 0)) if ok else _NAN,
        "pf": profit_factor(r),
        "sharpe": sharpe,
        "skew": skew,
        "kurt": kurt,
        "sqn": sharpe * math.sqrt(n) if math.isfinite(sharpe) else _NAN,
        "total_r": float(r.sum()) if (ok or n == 0) else _NAN,
        "max_consec_losses": max_consecutive_losses(r),
        "max_drawdown_r": max_drawdown_r(r),
    }


# ---------------------------------------------------------------------------
# 다중 시험 보정 샤프 (DSR, Bailey·López de Prado 2014)
# ---------------------------------------------------------------------------


def expected_max_sharpe(sr_trials_var: float, n_trials: int = C.DSR_N_TRIALS) -> float:
    """SR₀ = √V · ((1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))) — 참 샤프 0인 시도 N개 중 최댓값의 기대치 근사.

    V = 시도들의 샤프 분산, γ = 오일러-마스케로니 상수. N = 1이면 0(보정할 선택이 없다).
    V가 NaN·음수이거나 N < 1이면 nan.
    """
    v = _num(sr_trials_var)
    if not (math.isfinite(v) and v >= 0):
        return _NAN
    n = int(n_trials)
    if n < 1:
        return _NAN
    if n == 1:
        return 0.0
    z1 = _NORMAL.inv_cdf(1.0 - 1.0 / n)
    z2 = _NORMAL.inv_cdf(1.0 - 1.0 / (n * math.e))
    return math.sqrt(v) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(sr: float, n_obs: int, skew: float, kurt: float, sr_trials_var: float,
                    n_trials: int = C.DSR_N_TRIALS) -> float:
    """DSR (Bailey·López de Prado 2014, I-41). 확률(0~1)을 돌려준다.

    SR0 = sqrt(sr_trials_var) × ((1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))), γ = 0.5772156649 (오일러-마스케로니)
    DSR = Φ((sr − SR0) √(n_obs − 1) ÷ √(1 − skew·sr + (kurt − 1)/4 · sr²))
    sr_trials_var = 16개 조합(실행 가능 모드, 거래 2건 이상)의 거래당 샤프 분산(ddof=1). 계산 불가면 nan.

    - sr·SR0는 같은 단위(여기서는 거래당, 연율화하지 않음)여야 한다. kurt는 비초과 첨도(정규 = 3).
    - 논문 수치 예(N = 100, V = 0.5/250, sr = 2.5/√250, T = 1250, 왜도 −3, 첨도 10) → SR0 ≈ 0.1132, DSR ≈ 0.9004.
    - sr = SR0이면 0.5. 분모 안이 0 이하이거나 입력이 NaN이거나 n_obs < 2이면 nan.
    """
    sr, skew, kurt = _num(sr), _num(skew), _num(kurt)
    n_obs_f = _num(n_obs)
    if not all(math.isfinite(x) for x in (sr, skew, kurt, n_obs_f)) or n_obs_f < 2:
        return _NAN
    sr0 = expected_max_sharpe(sr_trials_var, n_trials)
    if math.isnan(sr0):
        return _NAN
    var_term = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr   # 샤프 추정량 분산 × (T − 1) (비정규 보정)
    if not var_term > 0:
        return _NAN
    z = (sr - sr0) * math.sqrt(n_obs_f - 1.0) / math.sqrt(var_term)
    return _NORMAL.cdf(z)


def sharpe_trials_variance(sharpes: Iterable) -> float:
    """시도(조합)들의 거래당 샤프 분산 (ddof=1, I-41). NaN·None(거래 2건 미만 등)은 뺀다. 2개 미만이면 nan."""
    vals = np.array([_num(s) for s in sharpes], dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    return float(np.var(vals, ddof=1)) if vals.size >= 2 else _NAN


def dsr_from_summary(summary: dict, sr_trials_var: float, n_trials: int = C.DSR_N_TRIALS) -> float:
    """RunSummary(sharpe, n, skew, kurt) → DSR. 값이 없으면 nan."""
    return deflated_sharpe(summary.get("sharpe"), summary.get("n", 0), summary.get("skew"), summary.get("kurt"),
                           sr_trials_var, n_trials)


# ---------------------------------------------------------------------------
# 실행 요약 (DESIGN §8.2)
# ---------------------------------------------------------------------------


def _reason_counts(logs: Sequence[SignalLog]) -> tuple[dict, dict]:
    """(대표 사유별 수, 사유가 하나라도 포함된 후보 수) — 키 순서는 REASON_ORDER(0 포함)."""
    first = Counter()
    any_ = Counter()
    for g in logs:
        if g.reasons:
            first[g.reasons[0]] += 1
            any_.update(set(g.reasons))
    order = list(REASON_ORDER) + sorted(set(any_).difference(REASON_ORDER))
    return ({k: int(first.get(k, 0)) for k in order}, {k: int(any_.get(k, 0)) for k in order})


def _group_mean(r: np.ndarray, mask: np.ndarray) -> dict:
    return {"n": int(np.count_nonzero(mask)), "mean_r": _mean_or_nan(r[mask])}


def marketable_limit_summary(filled: Sequence[TradeResult]) -> dict:
    """즉시 체결될 지정가(활성 뒤 첫 봉 시가가 이미 지정가 너머)를 §12.1대로 지정가·메이커로 체결한 거래 요약 (검토 LA-2·F4).

    execution.simulate_plan이 meta['marketable_edge_r'](= 엔진 진입 원가 − 첫 봉 시가 테이커 체결 원가의 차이 ÷ R,
    양수 = 엔진이 유리)를 남긴 체결 거래만 센다. 반환: n, n_engine_favorable(edge > 0), favorable_r_sum
    (유리한 것의 합, R), mean_edge_r(평균, 음수면 엔진이 보수적). 해당 거래가 없으면 n = 0, 나머지 0/NaN.
    """
    edge = np.array([float(t.meta["marketable_edge_r"]) for t in filled if "marketable_edge_r" in t.meta],
                    dtype=np.float64)
    fav = edge[edge > 0]
    return {"n": int(edge.size), "n_engine_favorable": int(fav.size), "favorable_r_sum": float(fav.sum()),
            "mean_edge_r": _mean_or_nan(edge)}


def summarize_run(trades: list[TradeResult], logs: list[SignalLog], *, span_weeks: float,
                  rng_key: str) -> dict:
    """한 실행(조합 × 모드)의 요약 = DESIGN §8.2 'RunSummary' 스키마의 dict.

    rng_key는 부트스트랩·순열 난수 시드용 문자열(보통 cfg.key).
    - 키 순서: RUN_SUMMARY_KEYS(§8.2) 다음 RUN_SUMMARY_EXTRA_KEYS(연도별 거래 수 yearly_n, total_r, sqn,
      최대 연속 손실 max_consec_losses, R 누적 곡선 최대 낙폭 max_drawdown_r,
      즉시 체결될 지정가 요약 marketable_limit — marketable_limit_summary).
    - 통계 표본 = 체결 거래(status filled), 실현 순서(청산 시각)로 정렬해서 쓴다.
    - 부트스트랩 make_rng('bootstrap', rng_key), 순열 make_rng('perm', rng_key) (DESIGN §3.5).
    - passed_per_week = n_passed ÷ span_weeks, g3_weeks_to_150 = 150 ÷ passed_per_week (0이면 inf).
    """
    filled = _chronological(_filled(trades))
    r, years = filled_r(filled)
    st = r_stats(r)
    boot_lo, boot_hi = bootstrap_mean_ci(r, rng=C.make_rng("bootstrap", rng_key))  # §12.4
    perm_p = sign_flip_pvalue(r, rng=C.make_rng("perm", rng_key))                  # I-42
    yearly = yearly_mean_r(r, years)                                                # §8.3-6, I-39
    first, any_ = _reason_counts(logs)

    status = Counter(t.status for t in trades)
    exits = Counter(t.exit_reason for t in filled)
    sides = np.array([t.side for t in filled], dtype=np.int64)
    sessions = np.array([C.kst_session(t.approval_time) for t in filled], dtype=object)
    r_acc = np.array([t.r_account for t in filled], dtype=np.float64)
    size_frac = np.array([t.size_fraction for t in filled], dtype=np.float64)
    wf = [bool(t.meta["waist_fallback"]) for t in filled if "waist_fallback" in t.meta]

    n_passed = sum(1 for g in logs if g.status == "passed")
    span = _num(span_weeks)
    per_week = n_passed / span if math.isfinite(span) and span > 0 else _NAN
    if math.isnan(per_week):
        weeks_150 = _NAN
    else:
        weeks_150 = C.G3_TARGET_SIGNALS / per_week if per_week > 0 else math.inf

    out = {
        "n_candidates": len(logs),
        "n_passed": int(n_passed),
        "discard_first_reason": first,
        "discard_any_reason": any_,
        "status_counts": {k: int(status.get(k, 0)) for k in PLAN_STATUSES},
        "exit_counts": {k: int(exits.get(k, 0)) for k in EXIT_REASONS},
        "n": st["n"],
        "n_long": int(np.count_nonzero(sides > 0)),
        "n_short": int(np.count_nonzero(sides < 0)),
        "mean_r": st["mean_r"],
        "median_r": st["median_r"],
        "std_r": st["std_r"],
        "win_rate": st["win_rate"],
        "pf": st["pf"],
        "boot_lo": boot_lo,
        "boot_hi": boot_hi,
        "sharpe": st["sharpe"],
        "skew": st["skew"],
        "kurt": st["kurt"],
        "yearly": yearly,
        "positive_years": positive_year_count(yearly),
        "perm_p": perm_p,
        "mean_r_account": _mean_or_nan(r_acc),
        "mean_size_fraction": _mean_or_nan(size_frac),
        "by_session": {name: _group_mean(r, sessions == name) for name in C.KST_SESSIONS},
        "by_side": {"long": _group_mean(r, sides > 0), "short": _group_mean(r, sides < 0)},
        "waist_fallback_rate": float(np.mean(wf)) if wf else None,
        "span_weeks": span,
        "passed_per_week": per_week,
        "g3_weeks_to_150": weeks_150,
        # --- 보조 키 ---
        "yearly_n": yearly_counts(years),
        "total_r": st["total_r"],
        "sqn": st["sqn"],
        "max_consec_losses": st["max_consec_losses"],
        "max_drawdown_r": st["max_drawdown_r"],
        "marketable_limit": marketable_limit_summary(filled),
    }
    return out


def summarize_cost_stress(base_trades: list[TradeResult], stress_trades: list[TradeResult], *,
                          rng_key: str) -> dict:
    """비용 2배(§8.3-4) 결과 비교: 같은 후보를 비용 배수만 바꿔 돌린 두 실행의 체결 거래를 비교한다 (I-27).

    반환: DESIGN §8.1 'exec_cost2' 키(n, mean_r, pf, boot_lo) + boot_hi, cost_multiplier,
    mean_r_base(기본 비용 평균 R), delta_mean_r(비용 2배 − 기본), same_trades(두 실행의 체결 거래가
    plan_id·진입·청산 시각·청산 사유까지 같은가 — 비용은 체결 시점에 영향이 없어야 하므로 False면 엔진 오류 신호).
    rng_key는 부트스트랩 시드용(보통 비용 2배 설정의 cfg.key).
    """
    base = _chronological(_filled(base_trades))
    stress = _chronological(_filled(stress_trades))
    r_b, _ = filled_r(base)
    r_s, _ = filled_r(stress)
    lo, hi = bootstrap_mean_ci(r_s, rng=C.make_rng("bootstrap", rng_key))

    def key(t: TradeResult):
        return (t.plan_id, t.entry_time, t.exit_time, t.exit_reason)

    mults = sorted({float(t.cost_multiplier) for t in stress})
    mean_b, mean_s = _mean_or_nan(r_b), _mean_or_nan(r_s)
    return {
        "n": int(r_s.size),
        "mean_r": mean_s,
        "pf": profit_factor(r_s),
        "boot_lo": lo,
        "boot_hi": hi,
        "cost_multiplier": mults[0] if len(mults) == 1 else None,
        "mean_r_base": mean_b,
        "delta_mean_r": mean_s - mean_b,
        "same_trades": [key(t) for t in base] == [key(t) for t in stress],
    }


# ---------------------------------------------------------------------------
# G1 판정 (§8.3)
# ---------------------------------------------------------------------------


def g1_verdict(exec_summary: dict, cost2_mean_r: float | None, random_p95: float | None) -> dict:
    """§8.3 판정. 반환: c1_mean_r … c6_years(bool|None), c7_enough_trades(bool), result('pass'|'fail'|'pending').

    c1 mean_r ≥ 0.15 / c2 boot_lo > 0 / c3 pf ≥ 1.2 / c4 cost2_mean_r > 0 / c5 mean_r > random_p95 /
    c6 양수 연도 수 ≥ 4 / c7 n ≥ 30. n < 30이면 result = 'pending'(판정 보류). 값이 None이면 그 조건은 실패로 본다.

    구현: c1~c7은 항상 bool이다(None·NaN 입력 → False). pending이어도 c1~c6은 참고로 계산한다.
    'pass'는 c7이 참이고 c1~c6이 모두 참일 때만. exec_summary는 summarize_run 결과(또는 JSON으로 읽은 같은 dict:
    'inf' 문자열 PF도 받는다).
    """
    s = exec_summary or {}
    mean_r = _num(s.get("mean_r"))
    out = {
        "c1_mean_r": _ge(mean_r, C.G1_MIN_MEAN_R),                             # §8.3-1 평균 R ≥ +0.15
        "c2_boot_lo": _gt(_num(s.get("boot_lo")), 0.0),                        # §8.3-2 부트스트랩 하한 > 0
        "c3_pf": _ge(_num(s.get("pf")), C.G1_MIN_PF),                          # §8.3-3 PF ≥ 1.2
        "c4_cost2": _gt(_num(cost2_mean_r), 0.0),                              # §8.3-4 비용 2배 평균 R > 0
        "c5_random": _gt(mean_r, _num(random_p95)),                            # §8.3-5 무작위 95% 분위 초과
        "c6_years": _ge(_num(s.get("positive_years")), C.G1_MIN_POSITIVE_YEARS),  # §8.3-6 양수 연도 ≥ 4
        "c7_enough_trades": _ge(_num(s.get("n")), C.G1_MIN_TRADES),            # §8.3-7 30건 이상
    }
    if not out["c7_enough_trades"]:
        out["result"] = "pending"                                              # §8.3-7 판정 보류
    elif all(out[k] for k in VERDICT_KEYS[:6]):
        out["result"] = "pass"
    else:
        out["result"] = "fail"
    return out
