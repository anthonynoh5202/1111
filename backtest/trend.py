"""추세추종(돈치안 돌파) 신호·거래 시뮬레이션 — docs/TREND_SPEC.md v1.0.

담당: 추세추종 구현. 체결·비용·통계 규칙은 RULES_SPEC §12와 backtest/DESIGN.md의 해석을 그대로 쓰고
(execution.scan_exit·trade_costs·funding_cost·funding_start, config.risk_per_unit 재사용), TREND_SPEC에 따로 적힌 것만 다르다.
baselines.py의 돈치안(G1 비교 기준선)과는 별개 구현이다(교차 확인용으로만 비교).

신호 (TREND_SPEC §1, 일봉 UTC 00:00 마감)
- U_N[t] = max(close[t−N..t−1]), D_N[t] = min(close[t−N..t−1]) (당일 제외, baselines.trailing_extremes).
- 롱 진입: close[t] > U_N[t], 숏 진입: close[t] < D_N[t] (하위 시스템이 그 방향 포지션이 아닐 때).
- 롱 청산: close[t] < D_M[t], 숏 청산: close[t] > U_M[t], M = round_half_up(N/2) (20→10, 55→28, 100→50).
- 반대 신호: 청산 후 같은 시각 반대 진입(롱 보유 중 숏 진입 조건 ⇒ 롱 청산 조건이 항상 성립하므로 청산 날의 진입 검사로 처리).
- 판단 시각 = close_ns[t] + 60초, 활성 = 판단 + L (기본 30분).

실행 (TREND_SPEC §2)
- E0: 활성 뒤 첫 실행 봉 시가에 시장가(테이커 0.05% + 진입 슬리피지 0.02%).
- E1: 돌파 레벨(롱 U_N, 숏 D_N, 0.1 반올림) 지정가, 유효 = 신호 마감 + 5일, 관통 체결(롱 low < 지정가), 메이커 0.02%.
  대기 중 청산 신호(신호 봉 k)가 나오면 close_ns[k] + 60초부터 취소 (RULES §12.1, DESIGN C-6).
- 보호 손절 = 진입가 ∓ 2 × ATR20[t] (0.1 반올림). ATR20[t] = 직전 20개 일봉 TR 평균(현재 봉 제외, indicators 방식).
  체결 봉부터 활성. 손절 청산 = 손절가(갭이면 시가) + 테이커 + 슬리피지 (execution.scan_exit, I-33).
- 추세 청산: 청산 신호 봉 k의 판단 + L 뒤 첫 실행 봉 시가, 테이커 + 슬리피지 (exit_reason 'trend').
- 데이터 끝: 마지막 실행 봉 종가 'eod'(테이커 + 슬리피지, I-36). 펀딩 = RULES §12.2 (execution.funding_cost).
- R = 단위당 순손익 ÷ (d + c_stop). c_stop = 진입 수수료 + (E0이면 진입 슬리피지) + 손절 테이커 + 손절 슬리피지.

해석 확정 (T-번호, 보수적 선택)
- T-1 하위 시스템당 포지션·대기 주문 최대 1개. E1 대기 중 같은 방향 진입 조건은 새 신호로 보지 않는다(기록 F9).
- T-2 보호 손절로 빠진 뒤에는 판단 시각이 손절 청산 봉 끝 이후인 첫 일봉부터 다시 진입 신호를 본다
  ("그 방향 포지션이 아님"을 문자 그대로 → 여전히 close > U_N이면 재진입).
  경계: 손절이 일봉 마감 직후 첫 실행 봉(00:00, 봉 끝 = 판단 시각 00:01)에서 나면 그날 판단 때 이미 포지션이 없으므로,
  보유 중에 마감된 그 일봉의 신호로 같은 날 00:31에 재진입한다(명세 문자 그대로, 00:01까지의 정보만 써서 미래 참조 아님; 검토 TX-2).
- T-3 청산 신호 날 k에는 (포지션이 그 전에 손절로 끝났든, 손절이 판단 뒤 지연 구간에서 났든) 진입 검사를 한다(반대 신호).
- T-4 E1 만료·취소 뒤에는 order_end(만료 = 신호 마감 + 5일, 취소 = 청산 신호 판단 시각) 이후 첫 판단부터 다시 본다.
- T-5 가용성 마스크(방해 금지·하루 6건)는 적용하지 않는다: 판단 시각이 항상 KST 09:01(방해 금지 밖)이고
  하루 진입 요청은 최대 3건(하위 시스템 수)이라 마스크가 걸릴 수 없다.
- T-6 E0 진입 슬리피지(0.02%)는 비용(슬리피지 항)으로 넣고 R 분모 c_stop에도 넣는다(손절 = 정확히 −1R, 양의 평균 R을
  부풀리지 않는 쪽). 비용 2배는 수수료·슬리피지·지불 펀딩에만 곱한다(RULES I-27).
- T-7 신호는 U_N·D_N·D_M·U_M·ATR20이 모두 계산 가능한 봉부터(첫 유효 t = max(N, 20 + 1)).
- T-8 무작위 기준선(§5): 실제 체결 거래의 (진입 달 UTC, 방향, 하위 시스템 N)을 유지하고 그 달의 유효 일봉을 균등 추출,
  그 일봉 마감 + 60초 + L 뒤 첫 실행 봉 시가에 시장가(테이커 + 슬리피지) 진입, 손절 = 진입가 ∓ k × ATR20(그날),
  청산 = 그 방향 첫 M일 반대 돌파(같은 추세 청산 규칙). 재진입·반대 진입 없음, 거래끼리 겹침 무시(RULES I-40과 같은 방식).
  E1 조합의 판정 기준은 시장가 분포 p95와 '진입만 메이커·슬리피지 없음' 분포 p95 중 큰 값(비용 차이로 기준선이 약해져
  E1이 쉽게 이기는 것을 막는 보수적 선택).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from backtest import config as C
from backtest import execution as X
from backtest.baselines import performance, trailing_extremes
from backtest.indicators import trailing_mean, true_range
from backtest.types import Exit, ExecArrays, FundingArrays, Reason, SignalLog, Status, TradeResult

# ---------------------------------------------------------------------------
# TREND_SPEC 숫자
# ---------------------------------------------------------------------------
TREND_SPEC_VERSION = "TREND v1.0"
PERIODS = (20, 55, 100)            # §1 하위 시스템 N
SINGLE_PERIOD = 55                 # §4 55일 단독
LATENCY_MIN = 30                   # §2 승인 지연 L
LATENCY_SENSITIVITY = (10, 120)    # §4 민감도
STOP_ATR_MULT = 2.0                # §2 보호 손절 2 × ATR20
STOP_ATR_SENSITIVITY = 3.0         # §4 민감도 3 × ATR
ATR_N = 20                         # §2 ATR20 (일봉)
E1_VALID_DAYS = 5                  # §2 E1 유효 5일
ENTRY_TYPES = ("E0", "E1")
DIRECTIONS = ("LS", "L")           # 롱·숏 모두 / 롱만
RISK_R = 0.005                     # §3 1회 위험 r = 0.5%
NOTIONAL_CAP_PER_SYSTEM = 0.2      # §3 하위 시스템당 명목 ≤ 0.2배 (합계 ≤ 0.6배)
EXIT_TREND = "trend"               # 추세 청산 사유 (TradeResult.exit_reason)
TREND_EXIT_REASONS = (Exit.STOP, EXIT_TREND, Exit.EOD)
_NO_LIMIT = np.iinfo(np.int64).max


def exit_period(n: int) -> int:
    """청산 기간 M = N/2 반올림(0.5는 올림): 20→10, 55→28, 100→50 (§1)."""
    return int(math.floor(int(n) / 2 + 0.5))


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrendConfig:
    """조합 하나(진입 E0/E1 × 방향 LS/L × 하위 시스템 묶음)와 민감도 옵션."""

    entry: str                          # 'E0' | 'E1'
    direction: str                      # 'LS'(롱·숏) | 'L'(롱만)
    periods: tuple[int, ...] = PERIODS  # (20, 55, 100) 앙상블 | (55,) 단독
    latency_min: int = LATENCY_MIN
    stop_atr_mult: float = STOP_ATR_MULT
    cost_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.entry not in ENTRY_TYPES:
            raise ValueError(f"entry는 {ENTRY_TYPES} 중 하나: {self.entry!r}")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction은 {DIRECTIONS} 중 하나: {self.direction!r}")
        if not self.periods or any(int(p) < 2 for p in self.periods):
            raise ValueError(f"periods는 2 이상 정수들: {self.periods!r}")
        object.__setattr__(self, "periods", tuple(int(p) for p in self.periods))
        if int(self.latency_min) != self.latency_min or self.latency_min < 0:
            raise ValueError(f"latency_min은 0 이상 정수: {self.latency_min!r}")
        if not self.stop_atr_mult > 0:
            raise ValueError(f"stop_atr_mult는 양수: {self.stop_atr_mult!r}")
        if not self.cost_multiplier >= 0:
            raise ValueError(f"cost_multiplier는 0 이상: {self.cost_multiplier!r}")

    @property
    def allow_short(self) -> bool:
        return self.direction == "LS"

    @property
    def order_type(self) -> str:
        """E0 = 'market'(시가 체결, 테이커), E1 = 'limit'(메이커)."""
        return "market" if self.entry == "E0" else "limit"

    @property
    def entry_rate(self) -> float:
        return C.entry_fee_rate(self.order_type)

    @property
    def entry_slip_rate(self) -> float:
        """진입 슬리피지율: E0 0.02%, E1 0 (§2)."""
        return C.SLIPPAGE if self.entry == "E0" else 0.0

    @property
    def latency_ns(self) -> int:
        return int(self.latency_min) * C.NS_PER_MIN

    @property
    def systems(self) -> str:
        if self.periods == PERIODS:
            return "ENS"
        return "N" + "-".join(str(p) for p in self.periods)

    @property
    def base_key(self) -> str:
        """예: 'E0-LS-ENS', 'E1-L-N55'."""
        return f"{self.entry}-{self.direction}-{self.systems}"

    @property
    def variant(self) -> str:
        parts = []
        if self.latency_min != LATENCY_MIN:
            parts.append(f"lat{int(self.latency_min)}")
        if self.stop_atr_mult != STOP_ATR_MULT:
            parts.append(f"stop{self.stop_atr_mult:g}")
        if self.cost_multiplier != 1.0:
            parts.append(f"cost{self.cost_multiplier:g}")
        return "_".join(parts)

    @property
    def key(self) -> str:
        v = self.variant
        return f"{self.base_key}_{v}" if v else self.base_key

    def replace(self, **changes) -> "TrendConfig":
        return replace(self, **changes)

    def as_dict(self) -> dict:
        return dict(entry=self.entry, direction=self.direction, periods=list(self.periods),
                    latency_min=int(self.latency_min), stop_atr_mult=float(self.stop_atr_mult),
                    cost_multiplier=float(self.cost_multiplier), order_type=self.order_type,
                    key=self.key, base_key=self.base_key, variant=self.variant)


def trend_combos() -> list[TrendConfig]:
    """§4의 8개 조합 (순서 고정: 진입 → 방향 → 하위 시스템)."""
    return [TrendConfig(entry=e, direction=d, periods=p)
            for e in ENTRY_TYPES for d in DIRECTIONS for p in (PERIODS, (SINGLE_PERIOD,))]


SENSITIVITY_VARIANTS = (
    ("lat10", {"latency_min": 10}),
    ("lat120", {"latency_min": 120}),
    ("stop3", {"stop_atr_mult": STOP_ATR_SENSITIVITY}),
    ("cost2", {"cost_multiplier": C.G1_COST_STRESS_MULT}),
)


# ---------------------------------------------------------------------------
# 일봉 신호 재료
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyData:
    """일봉 배열 + ATR20. 봉 t의 판단 시각 = decision_ns[t] = close_ns[t] + 60초."""

    open_ns: np.ndarray
    close_ns: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    atr: np.ndarray
    decision_ns: np.ndarray

    @classmethod
    def from_frame(cls, daily: pd.DataFrame, atr_n: int = ATR_N) -> "DailyData":
        o = daily["open"].to_numpy(dtype=np.float64)
        h = daily["high"].to_numpy(dtype=np.float64)
        l = daily["low"].to_numpy(dtype=np.float64)
        c = daily["close"].to_numpy(dtype=np.float64)
        close_ns = daily["close_ns"].to_numpy(dtype=np.int64)
        atr = trailing_mean(true_range(h, l, c), atr_n)   # §2 ATR20: RULES §3 방식(직전 n개 TR 평균, 현재 제외)
        return cls(open_ns=daily["open_ns"].to_numpy(dtype=np.int64), close_ns=close_ns, open=o, high=h, low=l,
                   close=c, atr=atr, decision_ns=close_ns + C.AVAIL_DELAY_NS)

    def __len__(self) -> int:
        return int(self.close.shape[0])


@dataclass(frozen=True)
class ChannelSignals:
    """하위 시스템 N 하나의 일봉 신호 (모두 봉 t 마감까지의 종가만 사용)."""

    n: int
    m: int
    up: np.ndarray          # U_N
    dn: np.ndarray          # D_N
    ex_hi: np.ndarray       # U_M
    ex_lo: np.ndarray       # D_M
    valid: np.ndarray       # bool: 모든 값 계산 가능 (T-7)
    long_entry: np.ndarray
    short_entry: np.ndarray
    long_exit: np.ndarray
    short_exit: np.ndarray

    @property
    def first_valid(self) -> int:
        idx = np.flatnonzero(self.valid)
        return int(idx[0]) if idx.size else len(self.valid)


def channel_signals(daily: DailyData, n: int) -> ChannelSignals:
    """U_N·D_N·U_M·D_M과 진입·청산 조건 (§1). NaN 봉은 신호 없음."""
    m = exit_period(n)
    up, dn = trailing_extremes(daily.close, n)       # §1 직전 N개 종가(당일 제외)
    ex_hi, ex_lo = trailing_extremes(daily.close, m)
    valid = ~(np.isnan(up) | np.isnan(dn) | np.isnan(ex_hi) | np.isnan(ex_lo) | np.isnan(daily.atr))
    c = daily.close
    with np.errstate(invalid="ignore"):
        return ChannelSignals(n=int(n), m=m, up=up, dn=dn, ex_hi=ex_hi, ex_lo=ex_lo, valid=valid,
                              long_entry=valid & (c > up), short_entry=valid & (c < dn),
                              long_exit=valid & (c < ex_lo), short_exit=valid & (c > ex_hi))


def next_exit_day(sig: ChannelSignals, side: int, t: int) -> int | None:
    """봉 t 뒤(> t) 처음 나오는 side 방향 청산 신호 봉 번호, 없으면 None."""
    arr = sig.long_exit if side > 0 else sig.short_exit
    rest = np.flatnonzero(arr[t + 1:])
    return int(t + 1 + rest[0]) if rest.size else None


# ---------------------------------------------------------------------------
# 거래 하나
# ---------------------------------------------------------------------------


@dataclass
class TradeOutcome:
    """simulate_trend_trade 결과: 거래 + 다음에 볼 일봉 번호(None = 데이터 끝)."""

    trade: TradeResult
    next_day: int | None
    exit_day: int | None = None
    extra: dict = field(default_factory=dict)


def _first_day_at_or_after(daily: DailyData, t_ns: int) -> int:
    """판단 시각 ≥ t_ns 인 첫 일봉 번호 (없으면 len)."""
    return int(np.searchsorted(daily.decision_ns, int(t_ns), side="left"))


def simulate_trend_trade(daily: DailyData, sig: ChannelSignals, t: int, side: int, cfg: TrendConfig,
                         xb: ExecArrays, fa: FundingArrays, *, entry_mode: str | None = None) -> TradeOutcome:
    """신호 봉 t의 side 방향 진입 → 체결·보호 손절·추세 청산 (§2). 반환 TradeOutcome.

    entry_mode: None이면 cfg.entry. 'E0'(시가 시장가) 또는 'E1'(돌파 레벨 지정가).
    """
    mode = cfg.entry if entry_mode is None else entry_mode
    order_type = "market" if mode == "E0" else "limit"
    entry_rate = C.entry_fee_rate(order_type)
    entry_slip = C.SLIPPAGE if mode == "E0" else 0.0
    m = float(cfg.cost_multiplier)
    n_x = len(xb)
    signal_time = int(daily.close_ns[t])
    approval = int(daily.decision_ns[t])               # §1 마감 + 60초
    active_from = approval + cfg.latency_ns            # §2 활성 = 판단 + L
    atr = float(daily.atr[t])                          # §2 신호 일의 ATR20
    dist = cfg.stop_atr_mult * atr
    k = next_exit_day(sig, side, t)                    # 첫 청산 신호 봉 (없으면 None)
    exit_signal_ns = int(daily.decision_ns[k]) if k is not None else None
    level = float(sig.up[t] if side > 0 else sig.dn[t])
    meta = dict(n=sig.n, m=sig.m, atr20=atr, level=level, entry_mode=mode,
                exit_signal_time=C.ns_to_iso(exit_signal_ns) if exit_signal_ns is not None else "")
    base = dict(plan_id=f"{cfg.base_key}_N{sig.n}_{C.ns_to_iso(signal_time)[:10]}_{'L' if side > 0 else 'S'}",
                scenario=f"N{sig.n}", side=int(side), order_type=order_type, signal_time=signal_time,
                approval_time=approval, active_from=active_from, target=math.inf * side, madi_id=None,
                cost_multiplier=m)

    j0 = int(np.searchsorted(xb.open_ns, active_from, side="left"))   # §12.1 활성 이후 시작하는 실행 봉
    if mode == "E0":
        if j0 >= n_x:
            tr = TradeResult(status=Status.NOT_FILLED, busy_until=active_from, plan_entry=float("nan"),
                             stop=float("nan"), risk_per_unit=float("nan"), meta=meta, **base)
            return TradeOutcome(tr, None, k)
        entry_j, entry_price = j0, float(xb.open[j0])                 # §2 E0 첫 실행 봉 시가
        plan_entry = entry_price
    else:
        limit = C.round_price(level)                                  # §2 E1 돌파 레벨 지정가
        plan_entry = limit
        valid_until = signal_time + E1_VALID_DAYS * C.NS_PER_DAY      # §2 유효 5일 (RULES §12.1 만료 규칙)
        cancel = exit_signal_ns if (exit_signal_ns is not None and exit_signal_ns < valid_until) else None
        order_end = valid_until if cancel is None else cancel         # 대기 중 청산 신호 → 취소 (§2)
        meta.update(valid_until=C.ns_to_iso(valid_until))
        fill = None
        if j0 < n_x:
            j1 = max(j0, int(np.searchsorted(xb.close_ns, order_end, side="right")))  # I-31 봉 끝 ≤ 수명
            hit = xb.low[j0:j1] < limit if side > 0 else xb.high[j0:j1] > limit       # §12.1 관통 체결
            if hit.size and hit.any():
                fill = j0 + int(np.argmax(hit))
        if fill is None:
            plan_stop = C.round_price(limit - side * dist)
            risk = float(C.risk_per_unit(limit, plan_stop, entry_rate))
            if j0 >= n_x or order_end > int(xb.close_ns[-1]):
                status = Status.NOT_FILLED                            # 데이터 끝까지 주문이 살아 있음
            else:
                status = Status.CANCELLED if cancel is not None else Status.EXPIRED
            if status == Status.CANCELLED:
                meta["cancel_reason"] = "exit_signal"
            tr = TradeResult(status=status, busy_until=int(order_end), plan_entry=limit, stop=plan_stop,
                             risk_per_unit=risk, meta=meta, **base)
            nd = _first_day_at_or_after(daily, order_end)             # T-4
            return TradeOutcome(tr, nd if nd < len(daily) else None, k)
        entry_j, entry_price = fill, limit
        o = float(xb.open[entry_j])
        if entry_j == j0 and (o < limit if side > 0 else o > limit):
            meta["marketable_open"] = o                               # 즉시 체결될 지정가(보고용, 검토 LA-2)

    stop = C.round_price(entry_price - side * dist)                   # §2 보호 손절 = 진입가 ∓ 2 × ATR20
    entry_time = int(xb.open_ns[entry_j])
    # §2 R 분모 = d + c_stop (T-6: E0은 진입 슬리피지 포함)
    risk = float(C.risk_per_unit(entry_price, stop, entry_rate)) + entry_slip * entry_price
    if "marketable_open" in meta:                                    # 엔진 유리분 ÷ R (metrics.marketable_limit_summary)
        meta["marketable_edge_r"] = X.marketable_edge(side, entry_price, meta["marketable_open"]) / risk
    time_limit = int(exit_signal_ns + cfg.latency_ns) if exit_signal_ns is not None else _NO_LIMIT
    exit_j, exit_price, reason = X.scan_exit(side, entry_j, stop, math.inf * side, time_limit, order_type, xb)
    if reason == Exit.TIME:
        reason = EXIT_TREND                                           # §2 추세 청산 = 활성 뒤 첫 실행 봉 시가
    exit_time = int(xb.open_ns[exit_j])
    exit_close = int(xb.close_ns[exit_j])
    fees, slip_exit = X.trade_costs(entry_rate, entry_price, exit_price, False, m)
    slippage = float(slip_exit) + entry_slip * entry_price * m        # §2 E0 진입 슬리피지
    f_start = int(X.funding_start(order_type, entry_time, active_from))
    funding = X.funding_cost(side, f_start, exit_time, xb, fa, m)     # RULES §12.2, I-35
    gross = side * (exit_price - entry_price)
    net = gross - float(fees) - slippage - funding
    size_fraction = min(1.0, NOTIONAL_CAP_PER_SYSTEM * risk / (RISK_R * entry_price))  # §3 r 기반 명목 ÷ 상한
    tr = TradeResult(status=Status.FILLED, busy_until=exit_close, plan_entry=float(plan_entry), stop=float(stop),
                     risk_per_unit=risk, entry_time=entry_time, entry_price=float(entry_price), exit_time=exit_time,
                     exit_price=float(exit_price), exit_reason=reason, exit_bar_close_ns=exit_close,
                     fees=float(fees), slippage=slippage, funding=float(funding), gross_pnl=float(gross),
                     net_pnl=float(net), r_multiple=float(net / risk), size_fraction=float(size_fraction),
                     meta=meta, **base)
    if reason == Exit.EOD:
        return TradeOutcome(tr, None, k)
    if reason == EXIT_TREND:
        return TradeOutcome(tr, k, k)                                  # 청산 날 k에 반대 진입 검사 (§1)
    nd = _first_day_at_or_after(daily, exit_close)                     # T-2 손절 뒤 첫 판단
    if k is not None:
        nd = min(nd, k)                                                # T-3 청산 신호 날은 진입 검사
    return TradeOutcome(tr, nd if nd < len(daily) else None, k)


# ---------------------------------------------------------------------------
# 하위 시스템·조합
# ---------------------------------------------------------------------------


def _signal_log(daily: DailyData, sig: ChannelSignals, t: int, side: int, status: str,
                reasons: tuple[str, ...] = (), plan_id: str | None = None) -> SignalLog:
    return SignalLog(time=int(daily.decision_ns[t]), signal_time=int(daily.close_ns[t]), scenario=f"N{sig.n}",
                     side=int(side), status=status, reasons=reasons, plan_id=plan_id,
                     meta=dict(n=sig.n, close=float(daily.close[t]),
                               level=float(sig.up[t] if side > 0 else sig.dn[t])))


def run_subsystem(daily: DailyData, n: int, cfg: TrendConfig, xb: ExecArrays,
                  fa: FundingArrays) -> tuple[list[TradeResult], list[SignalLog]]:
    """하위 시스템 N 하나를 시간순으로 처리한다 (독립 포지션, 최대 1개). 반환 (거래, 신호 기록)."""
    sig = channel_signals(daily, n)
    trades: list[TradeResult] = []
    logs: list[SignalLog] = []
    d = sig.first_valid
    n_days = len(daily)
    while d is not None and d < n_days:
        side = 0
        if sig.long_entry[d]:
            side = 1                                   # §1 롱 진입 (포지션 없음 = 루프 불변식)
        elif sig.short_entry[d] and cfg.allow_short:
            side = -1                                  # §1 숏 진입 (롱만 모드는 무시)
        if side == 0:
            d += 1
            continue
        out = simulate_trend_trade(daily, sig, d, side, cfg, xb, fa)
        trades.append(out.trade)
        logs.append(_signal_log(daily, sig, d, side, "passed", plan_id=out.trade.plan_id))
        nd = out.next_day
        if cfg.entry == "E1" and out.trade.status != Status.FILLED:
            # T-1 대기 중 같은 방향 진입 조건은 새 신호가 아니다(기록만 F9)
            stop_at = n_days if nd is None else nd
            same = sig.long_entry if side > 0 else sig.short_entry
            for dd in np.flatnonzero(same[d + 1:stop_at]) + d + 1:
                logs.append(_signal_log(daily, sig, int(dd), side, "discarded", (Reason.F9,)))
        elif cfg.entry == "E1" and out.trade.entry_time is not None:
            stop_at = _first_day_at_or_after(daily, out.trade.entry_time)
            same = sig.long_entry if side > 0 else sig.short_entry
            for dd in np.flatnonzero(same[d + 1:stop_at]) + d + 1:
                logs.append(_signal_log(daily, sig, int(dd), side, "discarded", (Reason.F9,)))
        if nd is not None and nd <= d:
            raise AssertionError(f"진행하지 않음: N={n}, d={d}, next={nd}")
        d = nd
    return trades, logs


def run_trend_combo(daily: DailyData, cfg: TrendConfig, xb: ExecArrays,
                    fa: FundingArrays) -> tuple[list[TradeResult], list[SignalLog]]:
    """조합 하나: 하위 시스템마다 독립으로 돌려 합친다. 거래는 (진입 시각, N) 순, 기록은 (판단 시각, N) 순."""
    trades: list[TradeResult] = []
    logs: list[SignalLog] = []
    for n in cfg.periods:
        tr, lg = run_subsystem(daily, n, cfg, xb, fa)
        trades.extend(tr)
        logs.extend(lg)
    big = np.iinfo(np.int64).max
    trades.sort(key=lambda t: (t.entry_time if t.entry_time is not None else t.approval_time,
                               t.approval_time, int(t.scenario[1:])))
    logs.sort(key=lambda g: (g.time, int(g.scenario[1:]), big if g.plan_id is None else 0))
    return trades, logs


def filled(trades: list[TradeResult]) -> list[TradeResult]:
    return [t for t in trades if t.status == Status.FILLED]


def exit_counts(trades: list[TradeResult]) -> dict:
    """체결 거래의 청산 사유 수 (stop, trend, eod)."""
    f = filled(trades)
    return {r: sum(1 for t in f if t.exit_reason == r) for r in TREND_EXIT_REASONS}


def status_counts(trades: list[TradeResult]) -> dict:
    return {s: sum(1 for t in trades if t.status == s) for s in
            (Status.FILLED, Status.CANCELLED, Status.EXPIRED, Status.NOT_FILLED)}


# ---------------------------------------------------------------------------
# 무작위 기준선 (TREND_SPEC §5)
# ---------------------------------------------------------------------------


@dataclass
class RandomTable:
    """하위 시스템 N·방향마다 '일봉 d 마감에 시장가 진입'한 무작위 거래의 결과 (모든 유효 일봉)."""

    n: int
    side: int
    days: np.ndarray        # 일봉 번호 (오름차순, 유효 봉만)
    months: np.ndarray      # UTC 달 번호 (일봉 마감 시각 기준)
    filled: np.ndarray      # bool
    r: np.ndarray           # 시장가(테이커 + 진입 슬리피지) R
    r_maker: np.ndarray     # 진입만 메이커·슬리피지 없음으로 바꾼 R (E1 조합 비교용)


def _month_index(ns) -> np.ndarray:
    m = np.asarray(ns, dtype=np.int64).astype("datetime64[ns]").astype("datetime64[M]").astype(np.int64)
    return m + 1970 * 12


def random_table(daily: DailyData, n: int, side: int, cfg: TrendConfig, xb: ExecArrays,
                 fa: FundingArrays) -> RandomTable:
    """§5: 유효 일봉 d마다 d 마감 + 60초 + L 뒤 첫 실행 봉 시가 진입, 손절 = 진입가 ∓ k × ATR20[d],
    청산 = 그 방향의 첫 M일 반대 돌파(추세 청산 규칙 그대로). 거래끼리 독립(겹침 무시)."""
    sig = channel_signals(daily, n)
    days = np.flatnonzero(sig.valid)
    ok = np.zeros(days.size, dtype=bool)
    r = np.full(days.size, np.nan)
    r_mk = np.full(days.size, np.nan)
    m = float(cfg.cost_multiplier)
    for i, d in enumerate(days.tolist()):
        out = simulate_trend_trade(daily, sig, d, side, cfg, xb, fa, entry_mode="E0")
        t = out.trade
        if t.status != Status.FILLED:
            continue
        ok[i] = True
        r[i] = t.r_multiple
        # 같은 추출·같은 청산에서 진입 비용만 메이커(슬리피지 없음)로 (E1 조합의 c5 비교용, T-8)
        fee_mk = (C.FEE_MAKER * t.entry_price + C.FEE_TAKER * t.exit_price) * m
        slip_mk = C.SLIPPAGE * t.exit_price * m
        net_mk = t.gross_pnl - fee_mk - slip_mk - t.funding
        risk_mk = float(C.risk_per_unit(t.entry_price, t.stop, C.FEE_MAKER))
        r_mk[i] = net_mk / risk_mk
    return RandomTable(n=int(n), side=int(side), days=days, months=_month_index(daily.close_ns[days]),
                       filled=ok, r=r, r_maker=r_mk)


def run_trend_random_baseline(trades: list[TradeResult], tables: dict, cfg: TrendConfig, *,
                              n_reps: int = C.RANDOM_REPS, rng: np.random.Generator | None = None) -> dict:
    """§5 무작위 기준선. 실제 체결 거래마다 (진입 달(UTC), 방향, 하위 시스템 N)을 유지하고
    그 달의 유효 일봉 하나를 균등 추출해 tables[(N, side)]의 결과를 쓴다. 반복 평균 R의 분포.

    반환: reps, n_trades, means, mean, p05, p50, p95 (시장가 진입) + maker = {mean, p05, p50, p95}(진입만 메이커),
    threshold = 판정에 쓰는 95% 분위 (E0: 시장가 p95, E1: max(시장가 p95, 메이커 p95) — T-8 보수적).
    """
    seed_parts = ["trend_random", cfg.key]
    rng = C.make_rng(*seed_parts) if rng is None else rng
    base = filled(trades)
    nan = float("nan")
    n_reps = int(n_reps)
    out = dict(reps=n_reps, n_trades=len(base), seed_parts=seed_parts)
    if not base or n_reps <= 0:
        return out | dict(means=np.array([]), mean=nan, p05=nan, p50=nan, p95=nan, n_not_filled=0,
                          maker=dict(mean=nan, p05=nan, p50=nan, p95=nan), threshold=nan)
    keys = sorted({(int(t.meta["n"]), int(t.side)) for t in base})
    # 결합 풀: 키마다 (달 오름차순) 일봉을 이어 붙이고, 거래마다 [lo, hi) 범위에서 균등 추출
    offsets, pool_r, pool_rm, pool_ok, pool_m = {}, [], [], [], []
    off = 0
    for key in keys:
        tb = tables[key]
        offsets[key] = off
        pool_r.append(tb.r)
        pool_rm.append(tb.r_maker)
        pool_ok.append(tb.filled)
        pool_m.append(tb.months)
        off += tb.days.size
    pool_r, pool_rm = np.concatenate(pool_r), np.concatenate(pool_rm)
    pool_ok = np.concatenate(pool_ok)
    lo = np.empty(len(base), dtype=np.int64)
    hi = np.empty(len(base), dtype=np.int64)
    for i, t in enumerate(base):
        key = (int(t.meta["n"]), int(t.side))
        tb = tables[key]
        mth = int(_month_index(t.entry_time))            # 진입 시각의 UTC 달 (RULES I-40과 같은 기준)
        a = int(np.searchsorted(tb.months, mth, side="left"))
        b = int(np.searchsorted(tb.months, mth, side="right"))
        if b <= a:
            raise ValueError(f"무작위 기준선: {key} 달 {mth // 12}-{mth % 12 + 1:02d}에 유효 일봉 없음")
        lo[i], hi[i] = offsets[key] + a, offsets[key] + b
    idx = rng.integers(np.broadcast_to(lo, (n_reps, len(base))), np.broadcast_to(hi, (n_reps, len(base))))
    ok = pool_ok[idx]
    cnt = ok.sum(axis=1)

    def rep_means(vals: np.ndarray) -> np.ndarray:
        s = np.where(ok, vals[idx], 0.0).sum(axis=1)
        return np.divide(s, cnt, out=np.full(n_reps, np.nan), where=cnt > 0)

    def dist(means: np.ndarray) -> dict:
        f = means[np.isfinite(means)]
        if not f.size:
            return dict(mean=nan, p05=nan, p50=nan, p95=nan)
        p05, p50, p95 = (float(v) for v in np.quantile(f, [0.05, 0.5, C.G1_RANDOM_QUANTILE]))
        return dict(mean=float(f.mean()), p05=p05, p50=p50, p95=p95)

    means = rep_means(pool_r)
    d_mk = dist(rep_means(pool_rm))
    d = dist(means)
    thr = d["p95"] if cfg.entry == "E0" else float(np.nanmax([d["p95"], d_mk["p95"]]))
    return out | dict(means=means, **d, n_not_filled=int((~ok).sum()), maker=d_mk, threshold=thr)


def random_tables_for(daily: DailyData, cfg: TrendConfig, xb: ExecArrays, fa: FundingArrays,
                      cache: dict | None = None) -> dict:
    """cfg에 필요한 (N, 방향) 표. cache 키 = (N, side, latency, stop_mult, cost)."""
    cache = {} if cache is None else cache
    out = {}
    sides = (1, -1) if cfg.allow_short else (1,)
    for n in cfg.periods:
        for s in sides:
            ck = (n, s, int(cfg.latency_min), float(cfg.stop_atr_mult), float(cfg.cost_multiplier))
            if ck not in cache:
                cache[ck] = random_table(daily, n, s, cfg, xb, fa)
            out[(n, s)] = cache[ck]
    return out


# ---------------------------------------------------------------------------
# 통계 보조
# ---------------------------------------------------------------------------


def bootstrap_mean_diff_ci(r1, r0, *, n_boot: int = C.BOOTSTRAP_N, rng: np.random.Generator | None = None,
                           lower_q: float = C.BOOTSTRAP_LOWER_Q) -> dict:
    """평균 R 차이(r1 − r0)의 부트스트랩 95% 구간 (두 표본을 각각 복원 추출, §5 차트프로 보조 판정).

    반환 {diff, lo, hi, n1, n0}. 한쪽이 비면 값은 NaN.
    """
    a = np.asarray(r1, dtype=np.float64).ravel()
    b = np.asarray(r0, dtype=np.float64).ravel()
    nan = float("nan")
    if a.size == 0 or b.size == 0:
        return dict(diff=nan, lo=nan, hi=nan, n1=int(a.size), n0=int(b.size))
    rng = C.make_rng("trend_diff") if rng is None else rng
    n_boot = int(n_boot)
    diffs = np.empty(n_boot)
    rows = max(1, 2_000_000 // max(a.size, b.size))
    for s in range(0, n_boot, rows):
        e = min(n_boot, s + rows)
        ia = rng.integers(0, a.size, size=(e - s, a.size))
        ib = rng.integers(0, b.size, size=(e - s, b.size))
        diffs[s:e] = a[ia].mean(axis=1) - b[ib].mean(axis=1)
    lo, hi = np.quantile(diffs, [lower_q, 1.0 - lower_q])
    return dict(diff=float(a.mean() - b.mean()), lo=float(lo), hi=float(hi), n1=int(a.size), n0=int(b.size))


# ---------------------------------------------------------------------------
# 계좌 곡선 (TREND_SPEC §3, 보고용)
# ---------------------------------------------------------------------------

SIZING_MODES = ("risk", "fixed")


def _entry_cost_per_unit(t: TradeResult) -> float:
    """단위당 진입 비용(수수료 + E0 진입 슬리피지) × 비용 배수."""
    slip = C.SLIPPAGE if t.order_type == "market" else 0.0
    return (C.entry_fee_rate(t.order_type) + slip) * float(t.entry_price) * float(t.cost_multiplier)


def equity_curve(trades: list[TradeResult], daily: DailyData, start_day: int, *, sizing: str = "risk",
                 risk_r: float = RISK_R, cap: float = NOTIONAL_CAP_PER_SYSTEM, trim: bool = True) -> dict:
    """일봉 종가 기준 계좌 곡선 (시작 1.0 = 봉 start_day 마감).

    sizing='risk': 명목 = min(자산 × r ÷ (R 분모 ÷ 진입가), cap × 자산) (§3, 하위 시스템당 ≤ 0.2배, 합 ≤ 0.6배).
    sizing='fixed': 명목 = cap × 자산 (G1 기준선과 같은 '하위 시스템당 0.2배').
    자산 = 진입 직전 일봉 마감의 평가 자산(as-of). 수량은 청산까지 고정하되, trim=True면 매일 시가(= 전날 마감 뒤 첫 순간)에
    거래 하나의 명목이 cap × 전날 마감 자산을 넘으면 넘는 만큼만 줄인다(G1 돈치안 기준선 'trim'과 같은 방식, 늘리지는 않음).
    줄인 수량의 실현 손익 = 방향 × (그날 시가 − 진입가) − 진입 비용 − (테이커 + 슬리피지) × 시가 − 그때까지의 펀딩(기간 비례 근사).
    청산 때 남은 수량 × 단위당 순손익(수수료·슬리피지·펀딩 포함)을 현금에 더하고, 보유 중에는 수량 × 방향 × (종가 − 진입가)로
    평가한다(비용은 청산 때 반영).
    반환: equity(np.ndarray, 길이 = 일수), dates_ns, cagr, max_drawdown, sharpe, final_equity,
    max_notional_ratio(Σ 명목 ÷ 전날 자산의 최댓값. 매일 시가(줄인 뒤)와 각 진입 순간에 잰다. 진입 순간에는 그 시각에
    아직 열린 포지션만 센다(청산 시각 ≤ 진입 시각이면 이미 닫힘 → 반대 진입·손절 뒤 재진입이 두 번 세지지 않는다).
    전날부터 이어진 포지션은 그날 시가, 그날 진입한 포지션은 진입가로 평가 — 일봉 자료의 근사), n_trims.
    """
    if sizing not in SIZING_MODES:
        raise ValueError(f"sizing은 {SIZING_MODES} 중 하나: {sizing!r}")
    f = sorted(filled(trades), key=lambda t: (t.entry_time, t.plan_id))
    n = len(daily)
    start_day = int(start_day)
    close_ns = daily.close_ns
    days = max(n - start_day, 0)
    eq = np.empty(days)
    if days == 0:
        return dict(equity=eq, dates_ns=close_ns[start_day:], cagr=float("nan"), max_drawdown=float("nan"),
                    sharpe=float("nan"), final_equity=float("nan"), max_notional_ratio=float("nan"), n_trims=0)
    # 날 i = 진입·청산 시각이 [close[i−1], close[i]) 안에 드는 일봉
    ent_day = np.searchsorted(close_ns, np.array([t.entry_time for t in f], dtype=np.int64), side="right")
    ex_day = np.searchsorted(close_ns, np.array([t.exit_time for t in f], dtype=np.int64), side="right")
    order = np.argsort(ex_day, kind="stable")
    cash, eq_prev, max_ratio, n_trims = 1.0, 1.0, 0.0, 0
    open_pos: dict[int, float] = {}   # 거래 번호 → 남은 수량
    ptr = eptr = 0
    for i in range(start_day, n):
        if i == start_day:            # 시작 전 진입·청산은 곡선에 넣지 않는다
            while ptr < len(f) and ent_day[ptr] <= i:
                ptr += 1
            while eptr < len(f) and ex_day[order[eptr]] <= i:
                eptr += 1
        else:
            o = float(daily.open[i])
            if trim and eq_prev > 0:  # ① 시가: 기존 포지션의 명목 상한 초과분 줄이기
                for j in sorted(open_pos):
                    q = open_pos[j]
                    t = f[j]
                    if q * o > cap * eq_prev * (1.0 + 1e-9):
                        new_q = cap * eq_prev / o
                        cut = q - new_q
                        span = max(int(t.exit_time) - int(t.entry_time), 1)
                        frac = min(max((int(daily.open_ns[i]) - int(t.entry_time)) / span, 0.0), 1.0)
                        pnl = (t.side * (o - t.entry_price) - _entry_cost_per_unit(t)
                               - (C.FEE_TAKER + C.SLIPPAGE) * o * t.cost_multiplier - t.funding * frac)
                        cash += cut * pnl
                        open_pos[j] = new_q
                        n_trims += 1
            carried = set(open_pos)
            if open_pos and eq_prev > 0:  # 명목 비율 ⓐ 시가(줄인 뒤): 전날부터 이어진 포지션 전부, 시가 평가
                max_ratio = max(max_ratio, sum(q * o for q in open_pos.values()) / eq_prev)
            while ptr < len(f) and ent_day[ptr] <= i:   # ② 진입 (크기 = 전날 마감 자산)
                t = f[ptr]
                e = eq_prev
                if sizing == "risk":
                    notional = min(e * risk_r / (t.risk_per_unit / t.entry_price), cap * e)
                else:
                    notional = cap * e
                open_pos[ptr] = max(notional, 0.0) / t.entry_price
                if eq_prev > 0:           # 명목 비율 ⓑ 진입 순간: 그 시각에 아직 열린 포지션만(같은 시각 청산은 먼저 뺌)
                    tn = int(t.entry_time)
                    tot = 0.0
                    for j, q in open_pos.items():
                        if j != ptr and int(f[j].exit_time) <= tn:
                            continue
                        tot += q * (o if j in carried else f[j].entry_price)   # 이어진 것 = 시가, 오늘 진입 = 진입가
                    max_ratio = max(max_ratio, tot / eq_prev)
                ptr += 1
            while eptr < len(f) and ex_day[order[eptr]] <= i:   # ③ 청산
                j = int(order[eptr])
                if j in open_pos:
                    cash += open_pos.pop(j) * f[j].net_pnl
                eptr += 1
        c = daily.close[i]
        unreal = sum(q * f[j].side * (c - f[j].entry_price) for j, q in open_pos.items())
        eq[i - start_day] = cash + unreal
        eq_prev = eq[i - start_day]
    span_days = (close_ns[-1] - close_ns[start_day]) / C.NS_PER_DAY
    perf = performance(eq, span_days)
    return dict(equity=eq, dates_ns=close_ns[start_day:], cagr=perf["cagr"], max_drawdown=perf["max_drawdown"],
                sharpe=perf["sharpe"], final_equity=float(eq[-1]), max_notional_ratio=float(max_ratio),
                n_trims=int(n_trims))


def combo_start_day(daily: DailyData, cfg: TrendConfig) -> int:
    """계좌 곡선 시작 봉 = 조합의 하위 시스템 중 가장 이른 첫 유효 봉."""
    return min(channel_signals(daily, n).first_valid for n in cfg.periods)
