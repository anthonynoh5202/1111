"""모의 체결·보호 손절·추세 청산·펀딩·일일 리포트 — 모의 매매 담당 구현 (bot/DESIGN.md §3.3~3.4, §6, §9.5).

결과가 백테스트(backtest.trend.simulate_trend_trade, order_type='market')와 같도록 같은 식·같은 함수를 쓴다:
- 체결가 = 확인 시각 이후 시작하는 첫 1분봉 시가 (open_ns ≥ approved_ns 인 첫 봉). 그 봉이 마감된 뒤 처리.
- 보호 손절 = strategy.protective_stop(체결가, 신호 ATR20), R 분모 = strategy.risk_per_unit (둘 다 backtest 식 호출)
- 봉 j마다(체결 봉 포함, 시간순): (j가 체결 봉이 아니고 open_ns ≥ exit_due) → 그 봉 시가에 'trend' 청산,
  아니면 low ≤ stop → 'stop' 청산가 = min(stop, open[j]) (backtest.execution.scan_exit의 market 규칙)
- 비용 = backtest.execution.trade_costs(cfg.entry_rate, entry, exit, False, m) + E0 진입 슬리피지 0.02% × entry × m
- 펀딩 = X.funding_start('market', 체결 봉 시작, 확인 시각) < f ≤ 청산 봉 시작 인 f마다
  side × rate × (f를 포함하는 1분봉 시가), 지불(양수)만 × m (X.funding_cost와 같은 규칙)
- 결과는 감시 주기(1분·하루 한 번)와 무관하다: 커서(last_bar_close_ms) 기반 일괄 처리이고, 펀딩도
  '봉 j를 판정하기 직전에 f ≤ open_ns[j]인 것'을 넣으므로 어떤 묶음으로 나눠 불러도 같은 결과가 나온다.

쓰기 규칙: 시세 조회(HTTP일 수 있음)는 트랜잭션 밖에서 먼저 하고, 한 포지션의 펀딩·청산·커서는
한 트랜잭션(db.transaction, 중첩 합류)으로 쓴다 — 중간에 죽어도 반쯤 쓴 상태가 남지 않는다.
실제 돈이 움직이는 코드는 없다(주문·키 없음).
"""
from __future__ import annotations

import logging
import math
import sqlite3
import statistics
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest import execution as X
from backtest import trend as TR
from bot import db
from bot import strategy as ST
from bot.config import BotConfig
from bot.types import (
    MS_PER_DAY,
    NS_PER_MIN,
    Actor,
    ExitReason,
    MarketData,
    OutgoingMessage,
    PositionState,
    SignalState,
    ceil_minute_ns,
    kst_str,
    ms_to_ns,
    ns_to_ms,
)

log = logging.getLogger(__name__)

# 확인 뒤 체결 봉이 마감됐는데도 시세에 봉이 하나도 없으면 이만큼 더 기다린 뒤 SKIPPED('fill_failed').
# (백테스트는 빈 구간이면 다음 봉에 체결하므로, 그 사이에 봉이 나타나면 그대로 체결한다.)
FILL_DATA_GRACE_NS = 60 * NS_PER_MIN
# 펀딩 시각이 이번 묶음 앞에 있을 때(체결 전 펀딩, 분 경계가 아닌 펀딩) 가격 봉을 찾아볼 범위.
FUNDING_PRICE_LOOKBACK_NS = 60 * NS_PER_MIN

_REASON_KO = {ExitReason.STOP.value: "보호 손절", ExitReason.TREND.value: "추세 청산"}


def _tc(cfg: BotConfig) -> TR.TrendConfig:
    return cfg.trend_config()


# ---------------------------------------------------------------------------
# 크기
# ---------------------------------------------------------------------------


def position_size(equity_usdt: float, entry_price: float, risk_per_unit: float) -> float:
    """수량(BTC) = min(equity × 0.005 ÷ risk_per_unit, equity × 0.2 ÷ entry) (TREND_SPEC §3, trend.RISK_R·NOTIONAL_CAP).

    보고용 크기(판정은 R 단위라 크기와 무관). 입력이 양의 유한수가 아니면 ValueError.
    """
    vals = (float(equity_usdt), float(entry_price), float(risk_per_unit))
    if not all(math.isfinite(v) and v > 0 for v in vals):
        raise ValueError("equity·entry·risk_per_unit은 양의 유한수여야 한다")
    equity, entry, risk = vals
    return min(equity * TR.RISK_R / risk, equity * TR.NOTIONAL_CAP_PER_SYSTEM / entry)


# ---------------------------------------------------------------------------
# 체결
# ---------------------------------------------------------------------------


def fill_approved(conn: sqlite3.Connection, cfg: BotConfig, market: MarketData, now_ns: int) -> list[OutgoingMessage]:
    """APPROVED 신호마다 체결 봉(open_ns ≥ approved)이 마감됐으면 db.open_position. 체결 메시지 목록.

    - 체결 봉 = minute_bars(approved_ns, now_ns)의 첫 봉(마감된 봉만 오므로 '마감 뒤 처리'가 자동으로 지켜진다).
    - 봉이 아직 없으면 대기. ceil_minute(approved) + 1분 + FILL_DATA_GRACE_NS가 지나도 없으면 SKIPPED('fill_failed').
    - 그 하위 시스템에 이미 열린 포지션이 있으면(생기면 안 됨) SKIPPED('subsystem_busy') + 경고.
    """
    tc = _tc(cfg)
    now_ns = int(now_ns)
    now_ms = ns_to_ms(now_ns)
    out: list[OutgoingMessage] = []
    for sig in db.signals_in_states(conn, [SignalState.APPROVED]):
        sid = sig["signal_id"]
        if sig["approved_ms"] is None:  # 불변식 위반(확인 없이 APPROVED) — 체결하지 않는다
            if db.transition_signal(conn, sid, SignalState.APPROVED, SignalState.SKIPPED, now_ms=now_ms,
                                    actor=Actor.PAPER, reason="fill_failed", payload=dict(detail="no_approved_ms")):
                out.append(_alert(cfg, f"{int(sig['subsystem_n'])}일 신호 체결 불가(확인 시각 없음) — 건너뜀"))
            continue
        approved_ns = ms_to_ns(int(sig["approved_ms"]))
        first_close_ns = ceil_minute_ns(approved_ns) + NS_PER_MIN
        if now_ns < first_close_ns:
            continue  # 체결 봉이 아직 마감되지 않음
        bars = market.minute_bars(approved_ns, now_ns)
        if len(bars) == 0:
            if now_ns >= first_close_ns + FILL_DATA_GRACE_NS:
                if db.transition_signal(conn, sid, SignalState.APPROVED, SignalState.SKIPPED, now_ms=now_ms,
                                        actor=Actor.PAPER, reason="fill_failed", payload=dict(detail="no_bars")):
                    out.append(_alert(cfg, f"{int(sig['subsystem_n'])}일 신호 체결 불가(1분봉 없음) — 건너뜀"))
            continue
        entry_ns = int(bars["open_ns"].iloc[0])
        entry_price = float(bars["open"].iloc[0])
        side = int(sig["side"])
        stop = ST.protective_stop(entry_price, float(sig["atr20"]), side, tc)
        risk = ST.risk_per_unit(entry_price, stop, tc)
        if not (math.isfinite(risk) and risk > 0 and stop > 0):
            if db.transition_signal(conn, sid, SignalState.APPROVED, SignalState.SKIPPED, now_ms=now_ms,
                                    actor=Actor.PAPER, reason="fill_failed",
                                    payload=dict(detail="bad_stop", entry_price=entry_price, stop=stop)):
                out.append(_alert(cfg, f"{int(sig['subsystem_n'])}일 신호 체결 불가(손절 계산 이상) — 건너뜀"))
            continue
        qty = position_size(cfg.paper.equity_usdt, entry_price, risk)
        entry_fee = tc.entry_rate * entry_price * tc.cost_multiplier
        entry_slip = tc.entry_slip_rate * entry_price * tc.cost_multiplier
        pid = db.open_position(conn, signal_id=sid, entry_ms=ns_to_ms(entry_ns), entry_price=entry_price, qty=qty,
                               stop=stop, risk_per_unit=risk, entry_fee=entry_fee, entry_slippage=entry_slip,
                               active_from_ms=int(sig["approved_ms"]), now_ms=now_ms)
        if pid is None:
            cur = db.get_signal(conn, sid)
            if cur is not None and cur["state"] == SignalState.APPROVED.value \
                    and db.open_position_for_subsystem(conn, int(sig["subsystem_n"])) is not None:
                if db.transition_signal(conn, sid, SignalState.APPROVED, SignalState.SKIPPED, now_ms=now_ms,
                                        actor=Actor.PAPER, reason="subsystem_busy"):
                    out.append(_alert(cfg, f"{int(sig['subsystem_n'])}일 하위 시스템에 이미 열린 포지션 — 신호 건너뜀"))
            continue  # 그 밖(동시에 /pause 등으로 상태가 바뀜): 아무것도 하지 않음
        lat = sig["approval_latency_ms"]
        lat_txt = f" · 승인 지연 {int(lat) / 60000:.1f}분" if lat is not None else ""
        out.append(OutgoingMessage(
            text=(f"{cfg.mode_tag} 모의 체결: {int(sig['subsystem_n'])}일 돌파 롱\n"
                  f"진입 {entry_price:,.1f} ({kst_str(ns_to_ms(entry_ns))}) · 수량 {qty:.4f} BTC\n"
                  f"보호 손절 {stop:,.1f} (−{(entry_price - stop) / entry_price * 100:.2f}%) · 1R = {risk:,.1f}"
                  f"{lat_txt}"),
            signal_id=sid, kind="fill"))
    return out


# ---------------------------------------------------------------------------
# 감시 (손절·추세 청산·펀딩)
# ---------------------------------------------------------------------------


@dataclass
class _Plan:
    """한 포지션의 이번 묶음 처리 결과(순수 계산). _apply가 한 트랜잭션으로 쓴다."""

    fundings: list[tuple[int, float, float, float]] = field(default_factory=list)  # (f_ns, rate, price, 단위당 금액)
    exit: tuple[int, int, float, str] | None = None     # (open_ns, close_ns, price, reason)
    cursor_ns: int | None = None                         # 처리한 마지막 봉의 close_ns


def _last_funding_ns(conn: sqlite3.Connection, position_id: int) -> int | None:
    row = conn.execute("SELECT MAX(ts_ms) AS m FROM paper_trades WHERE position_id = ? AND kind = 'FUNDING'",
                       (int(position_id),)).fetchone()
    return None if row is None or row["m"] is None else ms_to_ns(int(row["m"]))


def _funding_price(market: MarketData, f_ns: int, open_ns: np.ndarray, open_: np.ndarray) -> float:
    """f를 포함하는 1분봉 시가(X.funding_prices와 같은 뜻: open_ns ≤ f 인 마지막 봉).

    이번 묶음 안에 그런 봉이 없으면(f가 묶음 시작보다 앞) 시세에서 f 직전 구간을 따로 조회한다.
    그래도 없으면 백테스트의 clip(0)처럼 묶음 첫 봉 시가.
    """
    j = int(np.searchsorted(open_ns, f_ns, side="right")) - 1
    if j >= 0:
        return float(open_[j])
    start = (int(f_ns) // NS_PER_MIN) * NS_PER_MIN - FUNDING_PRICE_LOOKBACK_NS
    prev = market.minute_bars(start, int(open_ns[0]) if len(open_ns) else int(f_ns))
    if len(prev):
        po = prev["open_ns"].to_numpy(dtype=np.int64)
        k = int(np.searchsorted(po, f_ns, side="right")) - 1
        if k >= 0:
            return float(prev["open"].iloc[k])
    return float(open_[0])


def _scan(pos: sqlite3.Row, bars: pd.DataFrame, funding: pd.DataFrame, market: MarketData,
          tc: TR.TrendConfig) -> _Plan:
    """커서 뒤 마감 봉들을 시간순으로 판정(DESIGN §3.4). DB는 건드리지 않는다."""
    plan = _Plan()
    side = int(pos["side"])
    stop = float(pos["stop"])
    entry_ns = ms_to_ns(int(pos["entry_ms"]))
    due_ns = ms_to_ns(int(pos["exit_due_ms"])) if pos["exit_due_ms"] is not None else None
    o_ns = bars["open_ns"].to_numpy(dtype=np.int64)
    c_ns = bars["close_ns"].to_numpy(dtype=np.int64)
    op = bars["open"].to_numpy(dtype=np.float64)
    hi = bars["high"].to_numpy(dtype=np.float64)
    lo = bars["low"].to_numpy(dtype=np.float64)
    f_t = funding["time_ns"].to_numpy(dtype=np.int64) if len(funding) else np.empty(0, dtype=np.int64)
    f_r = funding["rate"].to_numpy(dtype=np.float64) if len(funding) else np.empty(0, dtype=np.float64)
    k = 0
    m = float(tc.cost_multiplier)
    for j in range(len(o_ns)):
        # 1) 봉 j 판정 직전: f ≤ open_ns[j] 인 펀딩 (청산 봉 시작과 같은 시각 포함, 봉 안쪽은 제외)
        while k < len(f_t) and f_t[k] <= o_ns[j]:
            price = _funding_price(market, int(f_t[k]), o_ns, op)
            x = side * float(f_r[k]) * price
            plan.fundings.append((int(f_t[k]), float(f_r[k]), price, x * m if x > 0 else x))
            k += 1
        # 2) 추세 청산: 체결 봉 제외, open ≥ due
        if due_ns is not None and o_ns[j] > entry_ns and o_ns[j] >= due_ns:
            plan.exit = (int(o_ns[j]), int(c_ns[j]), float(op[j]), ExitReason.TREND.value)
            return plan
        # 3) 보호 손절: 닿으면(롱 low ≤ stop), 시장가 주문이라 체결 봉에서도 갭이면 시가
        if (lo[j] <= stop) if side > 0 else (hi[j] >= stop):
            px = min(stop, float(op[j])) if side > 0 else max(stop, float(op[j]))
            plan.exit = (int(o_ns[j]), int(c_ns[j]), px, ExitReason.STOP.value)
            return plan
        plan.cursor_ns = int(c_ns[j])
    return plan


def _apply(conn: sqlite3.Connection, cfg: BotConfig, pos: sqlite3.Row, plan: _Plan, tc: TR.TrendConfig,
           now_ms: int) -> OutgoingMessage | None:
    """계획을 한 트랜잭션으로 쓴다: 펀딩 → (청산 | 커서 전진). 청산이면 알림 메시지."""
    pid = int(pos["position_id"])
    with db.transaction(conn):
        for f_ns, rate, price, amount in plan.fundings:
            db.add_funding(conn, pid, ts_ms=ns_to_ms(f_ns), rate=rate, price=price, amount_per_unit=amount,
                           now_ms=now_ms)
        if plan.exit is None:
            if plan.cursor_ns is not None:
                db.advance_cursor(conn, pid, ns_to_ms(plan.cursor_ns), now_ms=now_ms)
            return None
        cur = db.get_position(conn, pid)
        if cur is None or cur["state"] != PositionState.OPEN.value:
            return None
        exit_ns, exit_close_ns, exit_price, reason = plan.exit
        side = int(cur["side"])
        entry = float(cur["entry_price"])
        m = float(tc.cost_multiplier)
        fees, slip_exit = X.trade_costs(tc.entry_rate, entry, exit_price, False, m)
        fees = float(fees)
        slippage = float(slip_exit) + tc.entry_slip_rate * entry * m
        funding = float(cur["funding"])
        gross = side * (exit_price - entry)
        net = gross - fees - slippage - funding
        risk = float(cur["risk_per_unit"])
        r_mult = net / risk
        ok = db.close_position(conn, pid, exit_ms=ns_to_ms(exit_ns), exit_bar_close_ms=ns_to_ms(exit_close_ns),
                               exit_price=exit_price, exit_reason=reason, fees=fees, slippage=slippage,
                               gross_pnl=gross, net_pnl=net, r_multiple=r_mult, now_ms=now_ms,
                               exit_fee=fees - float(cur["entry_fee"]), exit_slippage=float(slip_exit))
        if not ok:
            return None
    qty = float(cur["qty"])
    return OutgoingMessage(
        text=(f"{cfg.mode_tag} 모의 청산({_REASON_KO.get(reason, reason)}): {int(cur['subsystem_n'])}일 롱\n"
              f"진입 {entry:,.1f} → 청산 {exit_price:,.1f} ({kst_str(ns_to_ms(exit_ns))})\n"
              f"순손익 {r_mult:+.2f}R · {net * qty:+,.2f} USDT (수수료·슬리피지·펀딩 {(fees + slippage + funding) * qty:,.2f})"),
        signal_id=cur["signal_id"], kind="exit")


def monitor(conn: sqlite3.Connection, cfg: BotConfig, market: MarketData, now_ns: int) -> list[OutgoingMessage]:
    """열린 포지션마다 커서 뒤 ~ now까지 마감된 1분봉을 시간순으로 훑어 청산·펀딩 처리. 커서 전진."""
    tc = _tc(cfg)
    now_ns = int(now_ns)
    now_ms = ns_to_ms(now_ns)
    out: list[OutgoingMessage] = []
    for pos in db.open_positions(conn):
        start_ns = ms_to_ns(int(pos["last_bar_close_ms"])) if pos["last_bar_close_ms"] is not None \
            else ms_to_ns(int(pos["entry_ms"]))
        if start_ns >= now_ns:
            continue
        bars = market.minute_bars(start_ns, now_ns)
        if len(bars) == 0:
            continue
        entry_ns = ms_to_ns(int(pos["entry_ms"]))
        f_start = int(X.funding_start(tc.order_type, entry_ns, ms_to_ns(int(pos["active_from_ms"]))))
        last_f = _last_funding_ns(conn, int(pos["position_id"]))
        f_lo = f_start if last_f is None else max(f_start, last_f)
        f_hi = int(bars["open_ns"].iloc[-1])
        funding = market.funding(f_lo, f_hi) if f_hi > f_lo else pd.DataFrame({"time_ns": [], "rate": []})
        plan = _scan(pos, bars, funding, market, tc)
        msg = _apply(conn, cfg, pos, plan, tc, now_ms)
        if msg is not None:
            out.append(msg)
    return out


def catch_up(conn: sqlite3.Connection, cfg: BotConfig, market: MarketData, until_ns: int) -> list[OutgoingMessage]:
    """fill_approved + monitor (until_ns까지). 일일 사이클이 신호 계산 전에 부른다."""
    out = fill_approved(conn, cfg, market, until_ns)
    out.extend(monitor(conn, cfg, market, until_ns))
    return out


# ---------------------------------------------------------------------------
# 일일 리포트
# ---------------------------------------------------------------------------


def _fmt_r(x: float | None) -> str:
    return "-" if x is None or not math.isfinite(float(x)) else f"{float(x):+.2f}R"


def daily_report(conn: sqlite3.Connection, cfg: BotConfig, now_ns: int, *,
                 mark_price: float | None = None) -> OutgoingMessage:
    """하루 요약: 열린 포지션·미실현 R, 지난 24시간 체결·청산, 누적 R·거래 수, 승인·패스·만료 통계, 승인 지연.

    mark_price(선택): 미실현 R 계산용 현재가(예: 방금 마감된 일봉 종가). 없으면 미실현 R은 '-'.
    지난 24시간 = [now − 24시간, now). 시각은 UTC로 비교하고 KST로 표시한다.
    """
    now_ms = ns_to_ms(int(now_ns))
    since_ms = now_ms - MS_PER_DAY
    tag = cfg.mode_tag
    lines = [f"{tag} 일일 리포트 · {kst_str(now_ms)}"]

    # 열린 포지션
    opens = db.open_positions(conn)
    lines.append(f"■ 열린 포지션 {len(opens)}개")
    for p in opens:
        rpu = float(p["risk_per_unit"])
        ur = None
        if mark_price is not None and rpu > 0:
            ur = (int(p["side"]) * (float(mark_price) - float(p["entry_price"])) - float(p["funding"])) / rpu
        days = (now_ms - int(p["entry_ms"])) / MS_PER_DAY
        due = f" · 추세 청산 예정 {kst_str(p['exit_due_ms'])}" if p["exit_due_ms"] is not None else ""
        lines.append(f"- {int(p['subsystem_n'])}일: 진입 {float(p['entry_price']):,.1f} · 손절 {float(p['stop']):,.1f}"
                     f" · 미실현 {_fmt_r(ur)} · 보유 {days:.1f}일{due}")

    # 지난 24시간 체결·청산
    fills = list(conn.execute(
        "SELECT subsystem_n, entry_ms, entry_price FROM paper_positions WHERE entry_ms >= ? AND entry_ms < ?"
        " ORDER BY entry_ms", (since_ms, now_ms)))
    exits = list(conn.execute(
        "SELECT subsystem_n, exit_ms, exit_price, exit_reason, r_multiple FROM paper_positions"
        " WHERE state = 'CLOSED' AND exit_ms >= ? AND exit_ms < ? ORDER BY exit_ms", (since_ms, now_ms)))
    lines.append(f"■ 지난 24시간: 체결 {len(fills)}건 · 청산 {len(exits)}건")
    for f in fills:
        lines.append(f"- 체결 {int(f['subsystem_n'])}일 {float(f['entry_price']):,.1f} ({kst_str(f['entry_ms'])})")
    for e in exits:
        lines.append(f"- 청산 {int(e['subsystem_n'])}일 {_REASON_KO.get(e['exit_reason'], e['exit_reason'])}"
                     f" {float(e['exit_price']):,.1f} ({kst_str(e['exit_ms'])}) {_fmt_r(e['r_multiple'])}")

    # 누적
    rs = [float(r["r_multiple"]) for r in conn.execute(
        "SELECT r_multiple FROM paper_positions WHERE state = 'CLOSED' ORDER BY exit_ms")]
    if rs:
        wins = sum(1 for r in rs if r > 0)
        lines.append(f"■ 누적: 청산 {len(rs)}건 · 합계 {sum(rs):+.2f}R · 평균 {sum(rs) / len(rs):+.2f}R"
                     f" · 승률 {wins / len(rs) * 100:.0f}%")
    else:
        lines.append("■ 누적: 청산 거래 없음")

    # 승인·패스·만료 통계 (전체 신호 기준)
    counts = {r["state"]: int(r["c"]) for r in conn.execute("SELECT state, COUNT(*) AS c FROM signals GROUP BY state")}
    approved = sum(counts.get(s.value, 0) for s in (SignalState.APPROVED, SignalState.FILLED, SignalState.CLOSED))
    lines.append(f"■ 신호: 승인 {approved} · 패스 {counts.get('PASSED', 0)} · 만료 {counts.get('EXPIRED', 0)}"
                 f" · 건너뜀 {counts.get('SKIPPED', 0)} · 대기 "
                 f"{sum(counts.get(s, 0) for s in ('NEW', 'CARD_SENT', 'CONFIRM_PENDING'))}")
    lats = [int(r["approval_latency_ms"]) / 60000 for r in conn.execute(
        "SELECT approval_latency_ms FROM signals WHERE approval_latency_ms IS NOT NULL")]
    if lats:
        lines.append(f"■ 승인 지연: 평균 {sum(lats) / len(lats):.1f}분 · 중앙값 {statistics.median(lats):.1f}분"
                     f" ({len(lats)}건)")
    else:
        lines.append("■ 승인 지연: 기록 없음")

    # Claude 의견 vs 사람 결정
    rows = list(conn.execute(
        "SELECT a.opinion AS opinion, s.state AS state, s.approved_ms AS approved_ms FROM signals s"
        " JOIN analyses a ON a.analysis_id = s.analysis_id WHERE a.ok = 1 AND a.opinion IS NOT NULL"))
    if rows:
        table: dict[tuple[str, str], int] = {}
        for r in rows:
            if r["approved_ms"] is not None:
                human = "승인"
            elif r["state"] == SignalState.PASSED.value:
                human = "패스"
            elif r["state"] == SignalState.EXPIRED.value:
                human = "만료"
            else:
                continue
            key = ("승인" if r["opinion"] == "approve" else "패스", human)
            table[key] = table.get(key, 0) + 1
        if table:
            parts = [f"Claude {c}/사람 {h} {n}" for (c, h), n in sorted(table.items())]
            lines.append("■ Claude 의견 vs 사람: " + " · ".join(parts))
    return OutgoingMessage(text="\n".join(lines), kind="report")


def _alert(cfg: BotConfig, text: str) -> OutgoingMessage:
    return OutgoingMessage(text=f"{cfg.mode_tag} 경고: {text}", kind="alert")


__all__ = ["position_size", "fill_approved", "monitor", "catch_up", "daily_report", "FILL_DATA_GRACE_NS"]
