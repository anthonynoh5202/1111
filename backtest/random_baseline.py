"""무작위 진입 기준선 (§8.4, §12.4).

담당: 체결 엔진. 설계: backtest/DESIGN.md §6.9, 해석 확정 I-40.

조합별 "실행 가능" 모드의 체결된 거래를 기준으로, 거래마다
- 같은 달(UTC, 진입 시각 기준)·같은 방향·같은 손절/목표 거리(%, 실제 진입가 대비)를 유지하고
- 진입 시각만 그 달의 신호 봉 마감 시각 중 하나를 균등하게 뽑아
- 시장가(테이커)로 진입: 판단 = 마감 + 60초, 체결 = active_from(= 판단 + 지연 L) 이후 첫 실행 봉 시가
- 같은 청산 엔진(execution.scan_exit·funding_cost, 같은 비용 규칙)으로 처리한다.
거래끼리 겹침(F9)은 보지 않는다(각자 독립). 반복마다 평균 R을 모아 분포를 만든다.
난수: config.make_rng('random_baseline', cfg.key) 하나로 전부 뽑는다 (결정적).

보고용 비교(판정에는 쓰지 않음, 검토 F2): 같은 추출·같은 청산으로 진입 수수료만 조합의 주문 형태
(config.entry_fee_rate(cfg.order_type): L1a·S2·S3 지정가 = 메이커)로 바꾼 '같은 진입 수수료' 분포의 분위도 낸다.
(추출 시각에는 방해 금지 시간의 신호 봉 마감도 들어간다 — §12.4 문자 그대로, 검토 LA-3: 보수적, 보고서에 명시.)

성능: 반복 × 거래 전체의 추출·진입·손절/목표·비용·펀딩은 배열로 한 번에 계산하고, 청산 봉 찾기만
거래마다 execution.scan_exit를 부른다(청산 규칙의 단일 출처). 1,000회가 너무 느리면 n_reps를 줄인다
(C.RANDOM_REPS_REDUCED = 300, 보고서에 명시 — 호출하는 쪽이 정한다).
"""
from __future__ import annotations

import numpy as np

from backtest import config as C
from backtest import execution as X
from backtest.config import ComboConfig
from backtest.types import Exit, ExecArrays, FundingArrays, Plan, TradeResult

_EPOCH_YEAR = 1970


def month_index(ns: np.ndarray) -> np.ndarray:
    """UTC 달 번호 = 연도 × 12 + (월 − 1) (int64)."""
    months = np.asarray(ns, dtype=np.int64).astype("datetime64[ns]").astype("datetime64[M]").astype(np.int64)
    return months + _EPOCH_YEAR * 12  # datetime64[M]은 1970-01부터 센 달 수


def draw_signal_closes(months: np.ndarray, signal_close_ns: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """거래마다 같은 달의 신호 봉 마감 시각 하나를 균등하게 뽑는다 (int64 ns). 그 달에 봉이 없으면 ValueError.

    months의 모양 그대로 돌려준다(예: (반복 수, 거래 수)). 봉 마감의 달 = month_index(close_ns).
    """
    closes = np.sort(np.asarray(signal_close_ns, dtype=np.int64))
    months = np.asarray(months, dtype=np.int64)
    close_months = month_index(closes)
    lo = np.searchsorted(close_months, months, side="left")
    hi = np.searchsorted(close_months, months, side="right")
    empty = hi <= lo
    if np.any(empty):
        bad = sorted({f"{m // 12}-{m % 12 + 1:02d}" for m in np.unique(months[empty]).tolist()})
        raise ValueError(f"신호 봉 마감이 없는 달: {bad[:5]}")
    return closes[rng.integers(lo, hi)]  # §12.4 그 달의 신호 봉 마감 중 균등 추출


def simulate_market_trade(side: int, signal_close_ns: int, stop_pct: float, target_pct: float,
                          xb: ExecArrays, fa: FundingArrays, cfg: ComboConfig) -> TradeResult:
    """무작위 거래 하나: order_type='market' Plan을 만들어 execution.simulate_plan으로 처리한다.

    approval = signal_close_ns + 60초, active_from = approval + cfg.latency_ns, 진입가 = 그 뒤 첫 실행 봉 open.
    stop = round(진입가 × (1 − side × stop_pct)), target = round(진입가 × (1 + side × target_pct)),
    max_hold_ns = cfg.max_hold_ns, 비용 배수 = cfg.cost_multiplier. 진입 봉이 없으면 status not_filled.
    """
    signal_close_ns = int(signal_close_ns)
    approval = signal_close_ns + C.AVAIL_DELAY_NS                   # §12.1 마감 + 60초에 판단
    active_from = approval + cfg.latency_ns                         # + 지연 L
    j0 = int(np.searchsorted(xb.open_ns, active_from, side="left"))
    entry = float(xb.open[j0]) if j0 < len(xb) else float("nan")    # 시장가 = 첫 실행 봉 시가 (I-40)
    plan = Plan(plan_id=f"RND_{cfg.key}_{C.ns_to_iso(signal_close_ns)}", scenario=cfg.scenario, side=int(side),
                signal_time=signal_close_ns, approval_time=approval, active_from=active_from,
                order_type="market", entry_price=entry,
                stop=C.round_price(entry * (1.0 - side * stop_pct)),       # §12.4 같은 손절 거리(%)
                target=C.round_price(entry * (1.0 + side * target_pct)),   # §12.4 같은 목표 거리(%)
                valid_until=active_from, max_hold_ns=cfg.max_hold_ns, atr_at_signal=float("nan"),
                meta={"random_baseline": True})
    return X.simulate_plan(plan, xb, fa, cfg.cost_multiplier)


def simulate_market_batch(side, signal_close_ns, stop_pct, target_pct, xb: ExecArrays, fa: FundingArrays,
                          cfg: ComboConfig) -> dict[str, np.ndarray]:
    """simulate_market_trade의 배열판: 무작위 거래 여러 개를 같은 규칙·같은 비용 식으로 한 번에 처리한다.

    입력은 같은 길이의 1차원 배열(또는 스칼라). 반환 dict의 배열(길이 = 거래 수):
    filled(bool), entry_j, entry_time, entry_price, stop, target, exit_j, exit_time, exit_price,
    exit_reason(str), fees, slippage, funding, gross, net, risk, r, r_same_fee. 미체결 거래는 가격·금액·r이 NaN, 번호 −1.
    r_same_fee = 진입 수수료율만 config.entry_fee_rate(cfg.order_type)로 바꾼 R (분자·분모 모두, 보고용, 검토 F2).
    펀딩 창은 활성 시각 < f ≤ 청산 (시가 체결 주문, execution.funding_start).
    """
    closes = np.atleast_1d(np.asarray(signal_close_ns, dtype=np.int64))
    k = closes.shape[0]
    side = np.broadcast_to(np.asarray(side, dtype=np.int64), (k,))
    stop_pct = np.broadcast_to(np.asarray(stop_pct, dtype=np.float64), (k,))
    target_pct = np.broadcast_to(np.asarray(target_pct, dtype=np.float64), (k,))
    n_bars = len(xb)

    active_from = closes + C.AVAIL_DELAY_NS + cfg.latency_ns        # §12.1 마감 + 60초 + L (I-40)
    j0 = np.searchsorted(xb.open_ns, active_from, side="left")
    filled = j0 < n_bars
    jf = np.minimum(j0, max(n_bars - 1, 0))
    entry = np.where(filled, xb.open[jf], np.nan) if n_bars else np.full(k, np.nan)
    stop = C.round_price(entry * (1.0 - side * stop_pct))
    target = C.round_price(entry * (1.0 + side * target_pct))
    entry_time = np.where(filled, xb.open_ns[jf], -1) if n_bars else np.full(k, -1, dtype=np.int64)

    exit_j = np.full(k, -1, dtype=np.int64)
    exit_price = np.full(k, np.nan)
    exit_reason = np.full(k, "", dtype=object)
    idx = np.flatnonzero(filled)
    time_limit = entry_time + int(cfg.max_hold_ns)                  # §12.2 신호 봉 72개 (I-34)
    for i, s, j, st, tg, tl in zip(idx.tolist(), side[idx].tolist(), j0[idx].tolist(), stop[idx].tolist(),
                                   target[idx].tolist(), time_limit[idx].tolist()):
        exit_j[i], exit_price[i], exit_reason[i] = X.scan_exit(s, j, st, tg, tl, "market", xb)

    ej = np.maximum(exit_j, 0)
    exit_time = np.where(filled, xb.open_ns[ej], -1) if n_bars else np.full(k, -1, dtype=np.int64)
    rate = C.entry_fee_rate("market")                               # 시장가 진입 = 테이커 (§12.4)
    is_target = exit_reason == Exit.TARGET
    fees, slippage = X.trade_costs(rate, entry, exit_price, is_target, cfg.cost_multiplier)
    funding = np.full(k, np.nan)
    if idx.size:
        f_start = X.funding_start("market", entry_time[idx], active_from[idx])   # 활성 < f ≤ 청산 (I-35, 검토 F3)
        funding[idx] = X.funding_cost_many(side[idx], f_start, exit_time[idx], xb, fa, cfg.cost_multiplier)
    gross = side * (exit_price - entry)
    net = gross - fees - slippage - funding
    risk = C.risk_per_unit(entry, stop, rate)                       # §12.2 R 분모 (계획가 = 실제 시가)
    # 보고용: 진입 수수료만 조합의 주문 형태 요율로 (분자 수수료·분모 c_stop 모두, 검토 F2)
    rate_same = C.entry_fee_rate(cfg.order_type)
    fees_same, _ = X.trade_costs(rate_same, entry, exit_price, is_target, cfg.cost_multiplier)
    risk_same = C.risk_per_unit(entry, stop, rate_same)
    with np.errstate(invalid="ignore"):
        r = net / risk
        r_same = (gross - fees_same - slippage - funding) / risk_same
    return dict(filled=filled, entry_j=np.where(filled, j0, -1), entry_time=entry_time, entry_price=entry,
                stop=stop, target=target, exit_j=exit_j, exit_time=exit_time, exit_price=exit_price,
                exit_reason=exit_reason, fees=fees, slippage=slippage, funding=funding, gross=gross, net=net,
                risk=risk, r=r, r_same_fee=r_same)


def run_random_baseline(trades: list[TradeResult], signal_close_ns: np.ndarray, xb: ExecArrays,
                        fa: FundingArrays, cfg: ComboConfig, *, n_reps: int = C.RANDOM_REPS,
                        rng: np.random.Generator | None = None) -> dict:
    """무작위 기준선 분포.

    trades: 실행 가능 모드의 TradeResult (체결된 것만 기준으로 쓴다). signal_close_ns: 이 조합 S 봉 close_ns 전체.
    반환 dict: reps, n_trades, means(np.ndarray, 길이 reps), mean, p05, p50, p95(np.quantile 'linear'),
    n_not_filled(진입 못 한 무작위 거래 수 합계; 평균에서 뺀다), seed_parts(['random_baseline', cfg.key]),
    same_fee = {entry_fee_rate, mean, p05, p50, p95}: 같은 추출·청산에서 진입 수수료만 조합의 주문 형태 요율로 바꾼
    반복 평균 R의 분포 요약(보고용, 판정은 §12.4 그대로 테이커 분포의 p95, 검토 F2).
    체결 거래가 0건이면 means는 빈 배열, 분위 값은 NaN.
    한 반복의 무작위 거래가 전부 진입하지 못하면 그 반복 평균은 NaN이고, mean·분위는 NaN을 뺀 값으로 낸다.
    """
    seed_parts = ["random_baseline", cfg.key]
    rng = C.make_rng(*seed_parts) if rng is None else rng
    base = [t for t in trades if t.is_filled]
    n_reps = int(n_reps)
    out = dict(reps=n_reps, n_trades=len(base), seed_parts=seed_parts)
    nan = float("nan")
    same_rate = C.entry_fee_rate(cfg.order_type)
    if not base or n_reps <= 0:
        return out | dict(means=np.array([], dtype=np.float64), mean=nan, p05=nan, p50=nan, p95=nan,
                          n_not_filled=0, same_fee=dict(entry_fee_rate=same_rate, mean=nan, p05=nan, p50=nan,
                                                        p95=nan))

    side = np.array([t.side for t in base], dtype=np.int64)
    entry = np.array([t.entry_price for t in base], dtype=np.float64)
    stop_pct = np.abs(entry - np.array([t.stop for t in base], dtype=np.float64)) / entry      # I-40 실제 진입가 대비
    target_pct = np.abs(np.array([t.target for t in base], dtype=np.float64) - entry) / entry
    months = month_index(np.array([t.entry_time for t in base], dtype=np.int64))              # 진입 시각의 UTC 달

    n = len(base)
    closes = draw_signal_closes(np.broadcast_to(months, (n_reps, n)), signal_close_ns, rng)   # (반복, 거래)
    sim = simulate_market_batch(np.tile(side, n_reps), closes.ravel(), np.tile(stop_pct, n_reps),
                                np.tile(target_pct, n_reps), xb, fa, cfg)
    ok = sim["filled"].reshape(n_reps, n)
    cnt = ok.sum(axis=1)

    def rep_means(r_flat: np.ndarray) -> np.ndarray:
        sums = np.where(ok, r_flat.reshape(n_reps, n), 0.0).sum(axis=1)
        return np.divide(sums, cnt, out=np.full(n_reps, np.nan), where=cnt > 0)             # 반복별 평균 R

    def dist(means: np.ndarray) -> dict:
        finite = means[np.isfinite(means)]
        if not finite.size:
            return dict(mean=nan, p05=nan, p50=nan, p95=nan)
        p05, p50, p95 = (float(v) for v in np.quantile(finite, [0.05, 0.50, C.G1_RANDOM_QUANTILE]))
        return dict(mean=float(finite.mean()), p05=p05, p50=p50, p95=p95)

    means = rep_means(sim["r"])
    same = dict(entry_fee_rate=same_rate) | dist(rep_means(sim["r_same_fee"]))               # 보고용 (검토 F2)
    return out | dict(means=means, **dist(means), n_not_filled=int((~ok).sum()), same_fee=same)
