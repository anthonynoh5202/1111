"""backtest.trend 재사용 어댑터 — 핵심 담당 구현 (bot/DESIGN.md §3).

규칙: 신호 계산 코드를 복사하지 않는다. 아래 함수는 backtest.trend의 함수를 **그대로 호출**하고
결과 배열의 마지막 봉(t = len − 1)만 읽어 SubsystemSignal로 옮긴다. 백테스트와 실운영이 같은 코드 경로를 쓴다.

호출 경로 (DESIGN §3.2)
    frame = market.daily_bars(until_ns=decision_ns)            # close_ns ≤ 판단 시각인 마감 일봉만
    daily = backtest.trend.DailyData.from_frame(frame)          # ATR20 = trailing_mean(true_range, 20)
    sig_n = backtest.trend.channel_signals(daily, n)            # n ∈ cfg.periods = (20, 55, 100)
    t = len(daily) − 1; 읽는 값: sig_n.valid[t], long_entry[t], long_exit[t], up[t], ex_lo[t], m, daily.atr[t]
"""
from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backtest import config as C
from backtest import trend as TR
from backtest import types as BT
from bot.config import STRATEGY_KEY
from bot.types import NS_PER_DAY, SubsystemAction, SubsystemSignal, ns_to_ms, utc_iso_ms

ANALYST_INPUT_SCHEMA = "analyst_input_v1"
RECENT_DAILY_N = 30
SMA_WINDOWS = (20, 50, 100, 200)


def trend_config() -> TR.TrendConfig:
    """E0-L-ENS = TrendConfig(entry='E0', direction='L', periods=(20, 55, 100)). latency 30분, 2×ATR20, 비용 1배."""
    cfg = TR.TrendConfig(entry="E0", direction="L", periods=TR.PERIODS)
    if cfg.base_key != STRATEGY_KEY:  # pragma: no cover - 상수 불일치는 코드 버그
        raise ValueError(f"전략 키 불일치: {cfg.base_key} != {STRATEGY_KEY}")
    return cfg


def _cfg(cfg: TR.TrendConfig | None) -> TR.TrendConfig:
    return trend_config() if cfg is None else cfg


def daily_data(frame: pd.DataFrame) -> TR.DailyData:
    """TR.DailyData.from_frame(frame) 그대로. 입력 검사: 표준 일봉 프레임(1일 길이, 빈 구간 없음), 비어 있지 않음,
    마지막 봉의 close_ns가 UTC 00:00 경계(= 판단 날 00:00)여야 한다. 아니면 ValueError."""
    if frame is None or len(frame) == 0:
        raise ValueError("일봉이 비어 있다")
    BT.check_bars_frame(frame, dur_ns=NS_PER_DAY, contiguous=True)
    last_close = int(frame["close_ns"].iloc[-1])
    if last_close % NS_PER_DAY != 0:
        raise ValueError(f"마지막 일봉 마감이 UTC 00:00이 아니다: {utc_iso_ms(ns_to_ms(last_close))}")
    return TR.DailyData.from_frame(frame)


def evaluate_day(frame: pd.DataFrame, *, decision_ns: int, open_subsystems: Mapping[int, bool],
                 busy_subsystems: set[int], cfg: TR.TrendConfig | None = None) -> list[SubsystemSignal]:
    """판단 날의 하위 시스템별 판단(N 오름차순).

    t = len(frame) − 1 (그날 마감된 일봉). N마다 sig = TR.channel_signals(daily, N):
    - open_subsystems[N] 참(포지션 보유): sig.long_exit[t] → EXIT, 아니면 HOLD
    - busy_subsystems에 N(승인 절차 중 신호): BUSY
    - 그 밖: sig.long_entry[t] → ENTRY(side=+1), 아니면 NONE. 롱만 조합이라 short_entry는 보지 않는다.
    - valid[t]가 거짓(워밍업)이면 NONE, valid=False (보유 중이면 HOLD — 보유 중 워밍업은 생기지 않지만 보수적으로 청산하지 않음).
    decision_ns ≠ daily.decision_ns[t]이면 ValueError(데이터가 오래됐거나 미래 봉이 섞임).
    """
    cfg = _cfg(cfg)
    if cfg.allow_short or cfg.entry != "E0":
        raise ValueError(f"이 봇은 E0 롱만 조합만 지원: {cfg.key}")
    daily = daily_data(frame)
    t = len(daily) - 1
    if int(daily.decision_ns[t]) != int(decision_ns):
        raise ValueError(f"판단 시각 불일치: 마지막 일봉 판단 {utc_iso_ms(ns_to_ms(int(daily.decision_ns[t])))}"
                         f" != 요청 {utc_iso_ms(ns_to_ms(int(decision_ns)))} (오래된 데이터 또는 미래 봉)")
    out: list[SubsystemSignal] = []
    for n in sorted(int(p) for p in cfg.periods):
        sig = TR.channel_signals(daily, n)
        valid = bool(sig.valid[t])
        if open_subsystems.get(n, False):
            action = SubsystemAction.EXIT if bool(sig.long_exit[t]) else SubsystemAction.HOLD
        elif n in busy_subsystems:
            action = SubsystemAction.BUSY
        elif bool(sig.long_entry[t]):          # valid[t] & close[t] > U_N[t] (backtest 식 그대로)
            action = SubsystemAction.ENTRY
        else:
            action = SubsystemAction.NONE
        side = 1 if action in (SubsystemAction.ENTRY, SubsystemAction.EXIT, SubsystemAction.HOLD) else 0
        out.append(SubsystemSignal(
            n=n, m=int(sig.m), action=action, side=side,
            signal_close_ns=int(daily.close_ns[t]), decision_ns=int(daily.decision_ns[t]),
            close=float(daily.close[t]), entry_level=float(sig.up[t]), exit_level=float(sig.ex_lo[t]),
            atr20=float(daily.atr[t]), valid=valid))
    return out


def protective_stop(entry_price: float, atr20: float, side: int = 1, cfg: TR.TrendConfig | None = None) -> float:
    """보호 손절 = C.round_price(entry_price − side × cfg.stop_atr_mult × atr20) (trend.simulate_trend_trade와 같은 식)."""
    cfg = _cfg(cfg)
    dist = cfg.stop_atr_mult * float(atr20)
    return float(C.round_price(float(entry_price) - int(side) * dist))


def risk_per_unit(entry_price: float, stop: float, cfg: TR.TrendConfig | None = None) -> float:
    """R 분모 = C.risk_per_unit(entry, stop, cfg.entry_rate) + cfg.entry_slip_rate × entry (T-6, 백테스트와 같은 식)."""
    cfg = _cfg(cfg)
    entry_price = float(entry_price)
    return float(C.risk_per_unit(entry_price, float(stop), cfg.entry_rate)) + cfg.entry_slip_rate * entry_price


def trend_exit_due_ns(exit_decision_ns: int, cfg: TR.TrendConfig | None = None) -> int:
    """추세 청산 시각 = 청산 신호 판단 시각 + cfg.latency_ns(30분). 이 시각 이후 시작하는 첫 1분봉 시가에 청산."""
    return int(exit_decision_ns) + int(_cfg(cfg).latency_ns)


# ---------------------------------------------------------------------------
# Claude 입력 (DESIGN §9.4) — 코드가 계산한 수치만
# ---------------------------------------------------------------------------


def _num(x: Any, nd: int = 2) -> float | None:
    """소수 nd자리 반올림. NaN·inf·None은 None(JSON에 NaN을 넣지 않는다)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, nd)


def _pct(a: float, b: float) -> float | None:
    """(a ÷ b − 1) × 100. b가 0·NaN이면 None."""
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(a) and math.isfinite(b)) or b == 0:
        return None
    return _num((a / b - 1.0) * 100.0)


def analysis_input(frame: pd.DataFrame, signals: list[SubsystemSignal], *,
                   open_positions: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Claude 입력용 수치 JSON(코드가 계산한 값만, 외부 텍스트 없음). DESIGN §9.4의 키를 따른다.

    - 이평(sma*)은 그날 종가 포함 단순 평균(표시·분석 전용, 결정에 쓰지 않음). 데이터가 모자라면 null.
    - dist_from_100d_high_pct = 종가 ÷ (그날 포함 최근 100개 고가 최댓값) − 1.
    - open_positions 항목에서 n, entry_price, stop, unrealized_r, days_held만 꺼낸다(다른 키는 버림).
    """
    cfg = trend_config()
    daily = daily_data(frame)
    t = len(daily) - 1
    close = pd.Series(daily.close)
    c_t = float(daily.close[t])
    atr_t = float(daily.atr[t])

    def sma(w: int) -> float | None:
        return _num(close.iloc[-w:].mean()) if len(close) >= w else None

    def ret(k: int) -> float | None:
        return _pct(c_t, daily.close[t - k]) if t - k >= 0 else None

    hi100 = float(np.max(daily.high[max(0, t - 99):]))
    indicators = {f"sma{w}": sma(w) for w in SMA_WINDOWS}
    indicators.update(atr20=_num(atr_t), atr20_pct=_num(atr_t / c_t * 100.0) if c_t else None,
                      ret_7d_pct=ret(7), ret_30d_pct=ret(30), dist_from_100d_high_pct=_pct(c_t, hi100))

    recent = []
    for i in range(max(0, t - RECENT_DAILY_N + 1), t + 1):
        recent.append({"date": utc_iso_ms(ns_to_ms(int(daily.open_ns[i])))[:10],
                       "open": _num(daily.open[i]), "high": _num(daily.high[i]), "low": _num(daily.low[i]),
                       "close": _num(daily.close[i]), "volume": _num(frame["volume"].iloc[i])})

    subs = []
    for s in signals:
        stop = protective_stop(s.close, s.atr20, 1, cfg) if math.isfinite(s.atr20) else float("nan")
        subs.append({"n": int(s.n), "m": int(s.m), "action": SubsystemAction(s.action).value,
                     "close": _num(s.close), "entry_level": _num(s.entry_level), "exit_level": _num(s.exit_level),
                     "breakout_pct": _pct(s.close, s.entry_level), "stop_if_filled_at_close": _num(stop),
                     "stop_distance_pct": _num((s.close - stop) / s.close * 100.0) if s.close else None})

    positions = []
    for p in open_positions:
        positions.append({"n": int(p["n"]), "entry_price": _num(p.get("entry_price")), "stop": _num(p.get("stop")),
                          "unrealized_r": _num(p.get("unrealized_r")), "days_held": _num(p.get("days_held"), 1)})

    return {
        "schema": ANALYST_INPUT_SCHEMA,
        "symbol": "BTCUSDT",
        "timeframe": "1d",
        "decision_time_utc": utc_iso_ms(ns_to_ms(int(daily.decision_ns[t]))),
        "strategy": {"key": cfg.base_key, "spec": TR.TREND_SPEC_VERSION, "periods": [int(p) for p in cfg.periods],
                     "stop_atr_mult": float(cfg.stop_atr_mult)},
        "recent_daily": recent,
        "indicators": indicators,
        "subsystems": subs,
        "open_positions": positions,
    }
