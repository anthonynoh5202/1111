"""일일 사이클·신호 상태 머신 운영 — 핵심 담당 구현 (bot/DESIGN.md §2, §4, §9.3).

엔진은 동기 코드다(DB·계산). 텔레그램 전송은 하지 않고 보낼 메시지(OutgoingMessage)를 돌려준다.
전송 성공 뒤 main/telegram_ui가 mark_card_sent를 부른다. 모든 상태 변경은 bot.db의 원자적 함수로만 한다.
현재 시각은 반드시 주입된 Clock에서만 읽는다(재생 모드에서 가짜 시계로 과거를 흘려보낼 수 있게).

TESTNET 모드(bot/orders/DESIGN.md §14): 모의 체결(paper)을 쓰지 않는다. [확인]의 APPROVED 전이와 같은 트랜잭션에서
주문 의도를 큐에 넣고(queue.enqueue), 보유 판정은 order_intents, 추세 청산은 queue.request_exit로 B에 요청한다.
거래소 호출·거래 키는 이 프로세스(A)에 없다. B의 체결·청산·경고는 outbox로 들어와 A가 텔레그램으로 보낸다.

스레드 규칙: 한 sqlite3 연결을 여러 스레드가 쓰면 db.transaction의 '중첩 합류'가 다른 스레드의 트랜잭션에
잘못 합류할 수 있다. 그래서 엔진의 모든 DB 작업은 self.lock(RLock) 안에서 한다. Claude 호출(최대 120초)만
락 밖에서 하므로 그동안에도 버튼·tick이 돈다. 같은 연결을 쓰는 다른 모듈(telegram_ui 등)도 engine.lock을 잡고 써야 한다.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from bot import db, paper
from bot import strategy as ST
from bot.config import BotConfig
from bot.types import (
    MS_PER_DAY,
    NS_PER_DAY,
    NS_PER_MIN,
    NS_PER_SEC,
    Actor,
    AnalystClient,
    AnalystResult,
    AuditEvent,
    Button,
    CallbackAction,
    Clock,
    CycleReport,
    MarketData,
    Mode,
    OutgoingMessage,
    PENDING_APPROVAL_STATES,
    SignalState,
    SubsystemAction,
    kst_str,
    make_callback_data,
    ms_to_ns,
    new_signal_id,
    ns_to_ms,
    utc_day_start_ns,
    utc_iso_ms,
)

log = logging.getLogger(__name__)

S = SignalState
CardRenderer = Callable[[sqlite3.Row, "sqlite3.Row | None", BotConfig], OutgoingMessage]
# /pause가 건너뛰는 상태(B-3): 승인 절차 중 + 승인됐지만 아직 체결 전
PAUSE_SKIP_STATES = (S.NEW, S.CARD_SENT, S.CONFIRM_PENDING, S.APPROVED)
# 놓친 판단일(봇 정지·하루 종일 사이클 실패)을 다음 사이클에서 다시 계산하는 최대 일수(R-1)
MAX_RECOVER_DAYS = 30
# 버튼 누른 시각을 인정하는 최대 과거 폭(OPS-4: 락 대기로 늦게 처리돼도 누른 시각으로 창 판정)
MAX_PRESS_LAG_MS = 300_000
# 모의 체결·감시 한 번에 가져오는 1분봉 범위(긴 정지 뒤 바이낸스 100쪽 한도에 걸리지 않게 나눠 따라잡음)
CATCHUP_WINDOW_NS = 30 * NS_PER_DAY
CATCHUP_MAX_CHUNKS = 16
DISK_FREE_WARN_BYTES = 1 << 30          # 1 GiB 미만이면 경고(OPS-7)
ORDERS_HEARTBEAT_STALE_MS = 5 * 60 * 1000   # TESTNET: B 심장 박동이 이보다 오래되면 경고

SKIP_REASON_KO = {
    "late_start": "늦은 시작(판단 뒤 승인 창 2시간이 이미 지남)",
    "paused": "일시정지 중(/pause)",
    "missed_cycle": "놓친 판단일(봇 정지·사이클 실패 뒤 복구 계산)",
}


def _day_str(ms: int) -> str:
    return utc_iso_ms(ms)[:10]


def _actor(actor: Actor | str) -> Actor | str:
    try:
        return Actor(actor)
    except ValueError:
        return str(actor)


def fallback_card(signal: sqlite3.Row, analysis: sqlite3.Row | None, cfg: BotConfig) -> OutgoingMessage:
    """telegram_ui.render_card를 쓸 수 없을 때의 최소 평문 카드(버튼 포함). 숫자는 전부 DB 값."""
    sid = signal["signal_id"]
    n = int(signal["subsystem_n"])
    lines = [
        f"{cfg.mode_tag} 롱 신호 · {n}일 돌파 ({cfg.strategy_key})",
        f"신호 일봉 {signal['signal_day']} 마감 · 판단 {kst_str(signal['decision_ms'])}",
        f"종가 {signal['close']:,.1f} > {n}일 최고 {signal['entry_level']:,.1f}",
        f"ATR20 {signal['atr20']:,.1f} · 예상 손절(종가 기준) {ST.protective_stop(signal['close'], signal['atr20']):,.1f}",
        f"승인 마감 {kst_str(signal['expires_ms'], '%H:%M KST')} · 승인 → {cfg.schedule.confirm_window_s}초 안에 [확인]",
    ]
    if analysis is None or not analysis["ok"]:
        status = "없음" if analysis is None else str(analysis["status"])
        lines.append(f"Claude 분석 없음 ({status})")
    else:
        lines.append(f"Claude 의견(참고, 관문 아님): {'승인' if analysis['opinion'] == 'approve' else '패스'}")
    buttons = ((Button("승인", make_callback_data(CallbackAction.APPROVE, sid)),
                Button("패스", make_callback_data(CallbackAction.PASS, sid)),
                Button("상세", make_callback_data(CallbackAction.DETAIL, sid))),)
    return OutgoingMessage(text="\n".join(lines), buttons=buttons, signal_id=sid, kind="card")


def default_card_renderer(signal: sqlite3.Row, analysis: sqlite3.Row | None, cfg: BotConfig) -> OutgoingMessage:
    """telegram_ui.render_card(담당: 텔레그램). 아직 구현 전이면 fallback_card."""
    try:
        from bot import telegram_ui

        return telegram_ui.render_card(signal, analysis, cfg)
    except NotImplementedError:
        return fallback_card(signal, analysis, cfg)


class _Prefetched:
    """락 밖에서 미리 가져온 1분봉·펀딩으로 paper 함수의 조회에 답하는 MarketData 감싸개(OPS-4).

    요청 범위가 미리 가져온 범위 안이면 잘라서 주고(네트워크 없음), 밖이면 원래 시세에 묻는다(드문 예외 경로).
    반환 규칙은 MarketData와 같다: minute_bars = open ≥ start 이고 close ≤ until 인 봉, funding = start < t ≤ until.
    """

    def __init__(self, market: MarketData, start_ns: int, until_ns: int, bars: pd.DataFrame,
                 f_start_ns: int, funding: pd.DataFrame) -> None:
        self._m = market
        self._b_start, self._b_until = int(start_ns), int(until_ns)
        self._bars = bars
        self._b_open = bars["open_ns"].to_numpy(dtype=np.int64)
        self._b_close = bars["close_ns"].to_numpy(dtype=np.int64)
        self._f_start = int(f_start_ns)
        self._funding = funding.reset_index(drop=True)
        self._f_time = self._funding["time_ns"].to_numpy(dtype=np.int64) if len(funding) else np.empty(0, np.int64)

    def minute_bars(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        start_ns, until_ns = int(start_ns), int(until_ns)
        if start_ns >= self._b_start and until_ns <= self._b_until:
            a = int(np.searchsorted(self._b_open, start_ns, side="left"))
            b = int(np.searchsorted(self._b_close, until_ns, side="right"))
            return self._bars.iloc[a:max(a, b)]
        return self._m.minute_bars(start_ns, until_ns)

    def funding(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        start_ns, until_ns = int(start_ns), int(until_ns)
        if start_ns >= self._f_start and until_ns <= self._b_until:
            a = int(np.searchsorted(self._f_time, start_ns, side="right"))
            b = int(np.searchsorted(self._f_time, until_ns, side="right"))
            return self._funding.iloc[a:max(a, b)].reset_index(drop=True)
        return self._m.funding(start_ns, until_ns)

    def daily_bars(self, until_ns: int) -> pd.DataFrame:
        return self._m.daily_bars(until_ns)

    def server_time_ns(self) -> int | None:
        return self._m.server_time_ns()


class Engine:
    def __init__(self, conn: sqlite3.Connection, cfg: BotConfig, market: MarketData,
                 analyst: AnalystClient | None, clock: Clock, *,
                 card_renderer: CardRenderer | None = None) -> None:
        if db.db_mode(conn) != cfg.mode:
            raise ValueError(f"DB 모드({db.db_mode(conn).value})와 설정 모드({cfg.mode.value})가 다르다")
        self.conn = conn
        self.cfg = cfg
        self.market = market
        if analyst is None:
            from bot.analyst import DisabledAnalyst

            analyst = DisabledAnalyst(cfg.claude.prompt_version, cfg.claude.model)
        self.analyst = analyst
        self.clock = clock
        self.trend = cfg.trend_config()
        self.render_card = card_renderer or default_card_renderer
        self.lock = threading.RLock()
        self._last_tick_error: str | None = None
        self._last_cycle_alert: tuple[str, str] | None = None   # (날짜, 오류 종류) — 같은 실패 경고 반복 방지(R-3)
        self._disk_warned_day: str | None = None
        self.unauthorized = None            # telegram_ui.UnauthorizedTracker(처음 쓸 때 만든다)
        self._testnet = cfg.mode == Mode.TESTNET
        self._b_down_alerted = False        # TESTNET: 주문 프로세스(B) 심장 박동 끊김 경고(끊길 때 한 번)
        self._started_ms = self.now_ms()    # 시작 직후(B가 아직 복구 중) 경고를 피하는 유예의 기준

    # --- 시간 ----------------------------------------------------------------------------
    def now_ns(self) -> int:
        return int(self.clock.now_ns())

    def now_ms(self) -> int:
        return ns_to_ms(self.now_ns())

    def decision_ns_for(self, t_ns: int) -> int:
        """t_ns가 속한 UTC 날짜의 판단 시각(00:00 + 60초)."""
        return utc_day_start_ns(t_ns) + int(self.cfg.schedule.decision_delay_s) * NS_PER_SEC

    def _alert(self, text: str) -> OutgoingMessage:
        return OutgoingMessage(text=f"{self.cfg.mode_tag} 경고: {text}", kind="alert")

    def _cycle_alert(self, cycle_day: str, kind: str, text: str) -> list[OutgoingMessage]:
        """사이클 실패 경고: 같은 날 같은 종류면 첫 번째만(재시도는 1분마다지만 경고는 한 번, R-3)."""
        key = (cycle_day, kind)
        if self._last_cycle_alert == key:
            return []
        self._last_cycle_alert = key
        return [self._alert(text)]

    def _press_ms(self, at_ms: int | None) -> int:
        """버튼 판정 시각: 누른 시각(at_ms)을 쓰되 지금보다 늦을 수 없고, MAX_PRESS_LAG_MS보다 오래될 수 없다."""
        now = self.now_ms()
        if at_ms is None:
            return now
        return max(min(int(at_ms), now), now - MAX_PRESS_LAG_MS)

    # --- 전송 보관함(OPS-3) ------------------------------------------------------------------
    def outbox_add(self, msg: OutgoingMessage) -> int:
        with self.lock:
            return db.outbox_add(self.conn, kind=msg.kind, text=msg.text, signal_id=msg.signal_id,
                                 edit_message_id=msg.edit_message_id, now_ms=self.now_ms())

    def outbox_pending(self) -> list[sqlite3.Row]:
        with self.lock:
            return db.outbox_pending(self.conn, now_ms=self.now_ms())

    def outbox_mark(self, outbox_id: int, *, sent: bool) -> None:
        with self.lock:
            db.outbox_mark(self.conn, outbox_id, sent=sent, now_ms=self.now_ms())

    # --- 디스크 ------------------------------------------------------------------------------
    def disk_free_bytes(self) -> int | None:
        if str(self.cfg.db_path) == ":memory:":
            return None
        try:
            return int(shutil.disk_usage(Path(self.cfg.db_path).parent).free)
        except OSError:
            return None

    # --- 분석·카드 도우미 ------------------------------------------------------------------
    def _analysis_for(self, signal: sqlite3.Row) -> sqlite3.Row | None:
        """신호에 연결된 분석, 없으면 같은 신호 날의 가장 최근 분석."""
        if signal["analysis_id"] is not None:
            return self.conn.execute("SELECT * FROM analyses WHERE analysis_id = ?",
                                     (signal["analysis_id"],)).fetchone()
        return self.conn.execute("SELECT * FROM analyses WHERE signal_day = ? ORDER BY analysis_id DESC LIMIT 1",
                                 (signal["signal_day"],)).fetchone()

    def _card(self, signal: sqlite3.Row, *, edit_message_id: int | None = None) -> OutgoingMessage:
        analysis = self._analysis_for(signal)
        try:
            msg = self.render_card(signal, analysis, self.cfg)
        except Exception:  # 렌더러 오류로 카드가 안 나가면 안 된다 — 최소 카드로
            log.exception("카드 렌더링 실패, 최소 카드 사용")
            msg = fallback_card(signal, analysis, self.cfg)
        text = msg.text
        if self._testnet and signal["state"] in (S.NEW.value, S.CARD_SENT.value, S.CONFIRM_PENDING.value):
            from bot.orders import queue as oq

            live = oq.live_intent(self.conn)
            if live is not None and live["signal_id"] != signal["signal_id"]:
                # O-3: 거래소 포지션은 동시에 1개. 승인해도 주문 프로세스가 REJECTED('position_exists')로 끝낸다.
                text += (f"\n※ 보유 중(1포지션): {int(live['subsystem_n'])}일 신호의 주문이 {live['state']} 상태 — "
                         "승인해도 주문하지 않는다(position_exists)")
        return OutgoingMessage(text=text, buttons=msg.buttons, signal_id=signal["signal_id"], kind="card",
                               edit_message_id=edit_message_id)

    def _open_position_dicts(self, frame, decision_ms: int) -> list[dict[str, Any]]:
        close = float(frame["close"].iloc[-1])
        out = []
        if self._testnet:
            for r in self._holding_intents():
                out.append(dict(n=int(r["subsystem_n"]), entry_price=float(r["avg_fill_price"]),
                                stop=None if r["stop_price"] is None else float(r["stop_price"]), unrealized_r=None,
                                days_held=(int(decision_ms) - int(r["entry_fill_ms"] or decision_ms)) / MS_PER_DAY))
            return out
        for p in db.open_positions(self.conn):
            rpu = float(p["risk_per_unit"])
            out.append(dict(n=int(p["subsystem_n"]), entry_price=float(p["entry_price"]), stop=float(p["stop"]),
                            unrealized_r=int(p["side"]) * (close - float(p["entry_price"])) / rpu if rpu > 0 else None,
                            days_held=(int(decision_ms) - int(p["entry_ms"])) / MS_PER_DAY))
        return out

    def _safe_analyze(self, payload: dict[str, Any]) -> AnalystResult:
        """analyze는 예외를 던지지 않는 계약이지만, 어겨도 사이클은 계속한다(Claude는 관문이 아님)."""
        try:
            res = self.analyst.analyze(payload)
            if not isinstance(res, AnalystResult):
                raise TypeError("AnalystResult가 아님")
            return res
        except Exception as exc:
            log.warning("Claude 분석 실패(예외): %s", type(exc).__name__)
            return AnalystResult(ok=False, status="error", prompt_version=self.cfg.claude.prompt_version,
                                 model=self.cfg.claude.model,
                                 input_json=json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
                                 error=type(exc).__name__)

    # --- 일일 사이클 (00:00 UTC + 60초) -------------------------------------------------
    def run_daily_cycle(self) -> CycleReport:
        """DESIGN §2.1 순서(검토 반영):
        1) now ≥ 오늘 판단 시각(00:00:60 UTC)인지 확인(아니면 skipped_reason='too_early', DB 변경 없음)
        2) db.begin_cycle(날짜) — 이미 DONE이면 빈 보고(skipped_reason='already_done')
        3) 시계 오차 검사(paper, market에 check_clock이 있을 때) — 실패면 사이클 FAILED + 경고(같은 날 한 번)
        4) daily = market.daily_bars(판단 시각) — 네트워크는 락 밖(OPS-4)
        5) 놓친 판단일(마지막 DONE 사이클 다음 날 ~ 어제, 최대 30일)을 날짜순으로 다시 계산(R-1):
           그날 판단 시각까지 모의 체결·감시 → 청산 신호면 청산 예약(늦었으면 감사 기록) → 진입 신호는 SKIPPED('missed_cycle')
        6) 오늘: 판단 시각까지 모의 체결·감시(T-2) → strategy.evaluate_day. 포지션 보유 여부는 '판단 시각 기준'
           (판단 뒤에 닫힌 포지션은 보유로 본다, R-2). EXIT → 청산 예약(due = 판단 + 30분). ENTRY → 신호 NEW
           (일시정지면 SKIPPED 'paused', 승인 창이 이미 지났으면 SKIPPED 'late_start' — 사용자에게 알림, OPS-9)
        7) 이 판단의 NEW 신호가 있고 그날 분석이 아직 없으면 Claude 분석 1회(락 밖, 실패해도 계속) → 저장
        8) 카드 메시지 생성, 일일 리포트, db.finish_cycle(DONE)
        시세 이상(MarketDataError)·데이터 불일치(ValueError)는 사이클 FAILED + 경고(다음 호출 때 재시도, 경고는 그날 한 번).
        """
        from bot.marketdata import MarketDataError

        now_ns = self.now_ns()
        decision_ns = self.decision_ns_for(now_ns)
        report = CycleReport(decision_ns=decision_ns)
        if now_ns < decision_ns:
            report.skipped_reason = "too_early"
            return report
        decision_ms = ns_to_ms(decision_ns)
        cycle_day = _day_str(decision_ms)
        with self.lock:
            if not db.begin_cycle(self.conn, cycle_day, decision_ms=decision_ms, now_ms=self.now_ms()):
                report.skipped_reason = "already_done"
                return report
        try:
            frame = self._cycle_prepare(report, decision_ns)
            if frame is None:
                return report
            self._cycle_analyze(report, frame, decision_ns)
            with self.lock:
                for row in self._new_signals_for(decision_ms):
                    report.outgoing.append(self._card(row))
                db.finish_cycle(self.conn, cycle_day, ok=True, now_ms=self.now_ms(),
                                note=f"new={len(report.created_signal_ids)} exits={len(report.exit_position_ids)}")
            self._last_cycle_alert = None
            report.outgoing.extend(self._daily_report())
            report.outgoing.extend(self._disk_check(cycle_day))
            return report
        except (MarketDataError, ValueError) as exc:
            with self.lock:
                note = f"{type(exc).__name__}: {str(exc)[:200]}"
                db.audit(self.conn, ts_ms=self.now_ms(), actor=Actor.ENGINE, event=AuditEvent.DATA_CHECK,
                         entity_type="cycle", entity_id=cycle_day, payload=dict(error=note))
                db.finish_cycle(self.conn, cycle_day, ok=False, now_ms=self.now_ms(), note=note)
            report.skipped_reason = "data_error"
            report.outgoing.extend(self._cycle_alert(
                cycle_day, "data_error",
                f"{cycle_day} 사이클 보류 — 시세 이상({type(exc).__name__}). 1분마다 재시도(이 경고는 그날 한 번만)"))
            log.warning("사이클 보류: %s", note)
            return report
        except BaseException:
            with self.lock:
                db.finish_cycle(self.conn, cycle_day, ok=False, now_ms=self.now_ms(), note="exception")
            raise

    # --- 모의 체결·감시(시세는 락 밖에서 가져온다) -------------------------------------------
    def _paper_starts(self) -> list[int]:
        """모의 체결·감시가 1분봉을 필요로 하는 가장 이른 시각들(ns): 체결 대기 신호의 확인 시각, 열린 포지션 커서."""
        starts = [ms_to_ns(int(r["approved_ms"])) for r in db.signals_in_states(self.conn, [S.APPROVED])
                  if r["approved_ms"] is not None]
        for p in db.open_positions(self.conn):
            c = p["last_bar_close_ms"] if p["last_bar_close_ms"] is not None else p["entry_ms"]
            starts.append(ms_to_ns(int(c)))
        return starts

    def _prefetch(self, start_ns: int, until_ns: int) -> _Prefetched:
        """락 밖: [start − 60분, until] 1분봉과 [start − 9시간, until] 펀딩을 한 번에 가져온다."""
        b_start = int(start_ns) - paper.FUNDING_PRICE_LOOKBACK_NS
        f_start = int(start_ns) - 9 * 3600 * NS_PER_SEC
        bars = self.market.minute_bars(b_start, until_ns)
        funding = self.market.funding(f_start, until_ns)
        return _Prefetched(self.market, b_start, until_ns, bars, f_start, funding)

    def _paper_apply(self, market, until_ns: int, *, cycle: bool) -> list[OutgoingMessage]:
        """락 안에서 부른다. 사이클은 paper.catch_up(체결+감시), tick은 fill_approved → monitor."""
        if cycle:
            return list(paper.catch_up(self.conn, self.cfg, market, until_ns))
        out = list(paper.fill_approved(self.conn, self.cfg, market, until_ns))
        out.extend(paper.monitor(self.conn, self.cfg, market, until_ns))
        return out

    def _paper_catch_up(self, until_ns: int, *, cycle: bool = False) -> list[OutgoingMessage]:
        """until_ns까지 모의 체결(fill_approved)·감시(monitor). 시세 조회는 락 밖, DB 반영은 락 안(OPS-4).
        결과는 한 번에 부른 것과 같다(paper는 커서 기반). 오래 멈췄다 켜지면 30일씩 나눠 따라잡는다.
        할 일(체결 대기·열린 포지션)이 없으면 시세를 조회하지 않는다."""
        if self._testnet:
            return []                              # TESTNET: 체결·손절·청산은 거래소(프로세스 B)가 한다
        out: list[OutgoingMessage] = []
        until_ns = int(until_ns)
        prev_lo: int | None = None
        for _ in range(CATCHUP_MAX_CHUNKS):
            with self.lock:
                starts = self._paper_starts()
                if not starts:                       # 할 일 없음: 네트워크 없이 그대로(빈 목록 순회)
                    out.extend(self._paper_apply(self.market, until_ns, cycle=cycle))
                    return out
            lo = min(starts)
            if prev_lo is not None and lo <= prev_lo:  # 한 조각을 처리했는데 커서가 그대로(30일 넘는 빈 시세): 다음 호출에
                log.warning("모의 감시 따라잡기 진전 없음(시세 빈 구간이 너무 김) — 다음 주기에 재시도")
                return out
            prev_lo = lo
            eff = min(until_ns, lo + CATCHUP_WINDOW_NS)
            pf = self._prefetch(lo, eff) if eff > lo else self.market
            with self.lock:
                out.extend(self._paper_apply(pf, eff, cycle=cycle))
            if eff >= until_ns:
                return out
        return out

    # --- 사이클 본문 ----------------------------------------------------------------------
    def _cycle_prepare(self, report: CycleReport, decision_ns: int):
        """3)~6). 반환 = 일봉 프레임, 시계 오차로 보류하면 None."""
        from bot.marketdata import MarketDataError

        decision_ms = ns_to_ms(decision_ns)
        cycle_day = _day_str(decision_ms)
        check = getattr(self.market, "check_clock", None)
        if self.cfg.mode in (Mode.PAPER, Mode.TESTNET) and callable(check):
            try:
                skew = check()
            except MarketDataError as exc:
                with self.lock:
                    db.audit(self.conn, ts_ms=self.now_ms(), actor=Actor.ENGINE, event=AuditEvent.DATA_CHECK,
                             entity_type="cycle", entity_id=cycle_day, payload=dict(clock_error=str(exc)[:200]))
                    db.finish_cycle(self.conn, cycle_day, ok=False, now_ms=self.now_ms(), note="clock_skew")
                report.skipped_reason = "clock_skew"
                report.outgoing.extend(self._cycle_alert(
                    cycle_day, "clock_skew",
                    f"시계 오차 초과 또는 서버 시각 확인 실패 — {cycle_day} 사이클 보류, 1분마다 재시도(경고는 그날 한 번)"))
                return None
            log.info("시계 오차 %s ms", skew)
        frame = self.market.daily_bars(decision_ns)                  # 네트워크: 락 밖
        skipped: list[tuple[sqlite3.Row, str]] = []
        for d_ns in self._missed_decisions(decision_ns, frame):
            report.outgoing.extend(self._paper_catch_up(d_ns, cycle=True))
            sub = frame[frame["close_ns"].to_numpy() <= d_ns]
            with self.lock:
                self._evaluate_and_apply(report, sub, d_ns, missed=True, skipped=skipped)
        # 판단 시각까지 마감된 1분봉 먼저(T-2: 00:00 봉 손절 → 같은 날 재진입 검사 가능)
        report.outgoing.extend(self._paper_catch_up(decision_ns, cycle=True))
        with self.lock:
            report.signals = self._evaluate_and_apply(report, frame, decision_ns, missed=False, skipped=skipped)
        report.outgoing.extend(self._skip_notices(skipped))
        return frame

    def _missed_decisions(self, decision_ns: int, frame) -> list[int]:
        """마지막 DONE 사이클과 오늘 사이의 판단 시각들(날짜순, 최대 MAX_RECOVER_DAYS). 처음 실행이면 없음."""
        with self.lock:
            row = self.conn.execute("SELECT MAX(decision_ms) AS m FROM cycles WHERE status = 'DONE' AND decision_ms < ?",
                                    (ns_to_ms(decision_ns),)).fetchone()
        if row is None or row["m"] is None:
            return []
        last = ms_to_ns(int(row["m"]))
        delay = int(self.cfg.schedule.decision_delay_s) * NS_PER_SEC
        have = {int(c) + delay for c in frame["close_ns"].to_numpy()}
        days = [d for d in range(last + NS_PER_DAY, int(decision_ns), NS_PER_DAY) if d in have]
        if len(days) > MAX_RECOVER_DAYS:
            with self.lock:
                db.audit(self.conn, ts_ms=self.now_ms(), actor=Actor.ENGINE, event=AuditEvent.ALERT,
                         entity_type="cycle", entity_id=_day_str(ns_to_ms(decision_ns)),
                         payload=dict(reason="missed_cycles_truncated", missed=len(days), recovered=MAX_RECOVER_DAYS))
            days = days[-MAX_RECOVER_DAYS:]
        return days

    def _open_at(self, decision_ms: int) -> dict[int, bool]:
        """판단 시각에 보유 중이던 하위 시스템: 판단 전에 진입했고 (아직 열림 또는 청산 봉 마감이 판단 뒤).
        tick이 사이클보다 먼저 판단 뒤 손절을 반영했어도 백테스트(T-2)와 같은 판단을 하게 한다(R-2).
        TESTNET: order_intents 기준 — 판단 전에 체결됐고 (아직 보유·정지(HALTED) 또는 판단 뒤 종료)."""
        if self._testnet:
            rows = self.conn.execute(
                "SELECT subsystem_n FROM order_intents WHERE filled_qty > 0 AND entry_fill_ms < ? AND"
                " (state IN ('ENTRY_FILLED', 'STOP_PLACED', 'STOP_VERIFIED', 'EXITING', 'HALTED')"
                "  OR closed_ms > ?)", (int(decision_ms), int(decision_ms))).fetchall()
            return {int(r["subsystem_n"]): True for r in rows}
        rows = self.conn.execute(
            "SELECT subsystem_n FROM paper_positions WHERE entry_ms < ? AND"
            " (state = 'OPEN' OR exit_bar_close_ms > ?)", (int(decision_ms), int(decision_ms))).fetchall()
        return {int(r["subsystem_n"]): True for r in rows}

    def _evaluate_and_apply(self, report: CycleReport, frame, d_ns: int, *, missed: bool,
                            skipped: list[tuple[sqlite3.Row, str]]):
        """판단 시각 d_ns의 신호 계산과 반영(락 안에서 부른다). missed=True면 놓친 날 복구."""
        d_ms = ns_to_ms(d_ns)
        day = _day_str(d_ms)
        open_n = self._open_at(d_ms)
        busy = {int(r["subsystem_n"]) for r in
                db.signals_in_states(self.conn, list(PENDING_APPROVAL_STATES) + [S.APPROVED])}
        sigs = ST.evaluate_day(frame, decision_ns=d_ns, open_subsystems=open_n, busy_subsystems=busy, cfg=self.trend)
        paused = db.is_paused(self.conn)
        now_ms = self.now_ms()
        expires_ms = d_ms + int(self.cfg.schedule.approval_window_s) * 1000
        if missed:
            db.begin_cycle(self.conn, day, decision_ms=d_ms, now_ms=now_ms)
        for s in sigs:
            if s.action == SubsystemAction.EXIT and self._testnet:
                self._request_exit_testnet(report, s, d_ms, now_ms=now_ms, missed=missed)
            elif s.action == SubsystemAction.EXIT:
                pos = db.open_position_for_subsystem(self.conn, s.n)
                if pos is None or int(pos["entry_ms"]) >= d_ms:
                    continue                                   # 판단 뒤 이미 닫힘(손절) 또는 판단 뒤 진입
                due_ms = ns_to_ms(ST.trend_exit_due_ns(s.decision_ns, self.trend))
                if db.set_exit_plan(self.conn, int(pos["position_id"]), exit_signal_close_ms=ns_to_ms(s.signal_close_ns),
                                    exit_due_ms=due_ms, now_ms=now_ms):
                    report.exit_position_ids.append(int(pos["position_id"]))
                    cursor = pos["last_bar_close_ms"]
                    if missed or (cursor is not None and int(cursor) > due_ms):
                        # 청산 예정 시각이 이미 지남(놓친 날·늦은 사이클): 커서 뒤 첫 봉에 청산 — 백테스트와 차이 기록
                        db.audit(self.conn, ts_ms=now_ms, actor=Actor.ENGINE, event=AuditEvent.ALERT,
                                 entity_type="position", entity_id=int(pos["position_id"]),
                                 payload=dict(reason="exit_plan_late", exit_due_ms=due_ms,
                                              cursor_ms=None if cursor is None else int(cursor), missed_day=missed))
            elif s.action == SubsystemAction.ENTRY:
                sid = new_signal_id()
                close_ms = ns_to_ms(s.signal_close_ns)
                with db.transaction(self.conn):
                    created = db.insert_signal(
                        self.conn, signal_id=sid, mode=self.cfg.mode, strategy_key=self.cfg.strategy_key,
                        spec_version="TREND v1.0", subsystem_n=s.n, side=s.side,
                        signal_day=_day_str(close_ms - MS_PER_DAY), signal_close_ms=close_ms,
                        decision_ms=d_ms, expires_ms=expires_ms, close=s.close,
                        entry_level=s.entry_level, exit_level=s.exit_level, atr20=s.atr20, now_ms=now_ms)
                    if not created:
                        continue
                    report.created_signal_ids.append(sid)
                    reason = None
                    if missed:
                        reason = "missed_cycle"
                    elif paused:
                        reason = "paused"
                    elif now_ms >= expires_ms:
                        reason = "late_start"
                    if reason is not None and db.transition_signal(self.conn, sid, S.NEW, S.SKIPPED, now_ms=now_ms,
                                                                   actor=Actor.ENGINE, reason=reason):
                        skipped.append((db.get_signal(self.conn, sid), reason))
        if missed:
            db.finish_cycle(self.conn, day, ok=True, now_ms=now_ms, note="recovered_missed")
        return sigs

    # --- TESTNET: 주문 의도(order_intents) 쪽 ------------------------------------------------
    _HOLDING_SQL = "('ENTRY_FILLED', 'STOP_PLACED', 'STOP_VERIFIED', 'EXITING')"

    def _holding_intents(self) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            f"SELECT * FROM order_intents WHERE state IN {self._HOLDING_SQL} ORDER BY intent_id"))

    def _request_exit_testnet(self, report: CycleReport, s, d_ms: int, *, now_ms: int, missed: bool) -> None:
        """EXIT 판단 → B에 추세 청산 요청(queue.request_exit, due = 판단 + L분). 판단 전에 체결된 보유 의도만.
        HALTED 등 요청을 받을 수 없는 상태면 감사 기록만(손절은 거래소에 있고, 사람이 처리한다)."""
        from bot.orders import queue as oq

        row = self.conn.execute(
            "SELECT * FROM order_intents WHERE subsystem_n = ? AND filled_qty > 0 AND entry_fill_ms < ?"
            " AND state IN ('ENTRY_FILLED', 'STOP_PLACED', 'STOP_VERIFIED', 'EXITING', 'HALTED')"
            " ORDER BY intent_id DESC LIMIT 1", (int(s.n), int(d_ms))).fetchone()
        if row is None:
            return                                         # 판단 뒤 이미 닫힘(손절) 또는 판단 뒤 진입
        due_ms = ns_to_ms(ST.trend_exit_due_ns(s.decision_ns, self.trend))
        if oq.request_exit(self.conn, row["signal_id"], exit_signal_close_ms=ns_to_ms(s.signal_close_ns),
                           exit_due_ms=due_ms, now_ms=now_ms):
            report.exit_position_ids.append(int(row["intent_id"]))
            if missed or now_ms > due_ms:
                db.audit(self.conn, ts_ms=now_ms, actor=Actor.ENGINE, event=AuditEvent.ALERT,
                         entity_type="order_intent", entity_id=int(row["intent_id"]),
                         payload=dict(reason="exit_plan_late", exit_due_ms=due_ms, missed_day=missed))
        elif row["exit_due_ms"] is None:
            db.audit(self.conn, ts_ms=now_ms, actor=Actor.ENGINE, event=AuditEvent.ALERT,
                     entity_type="order_intent", entity_id=int(row["intent_id"]),
                     payload=dict(reason="exit_request_refused", intent_state=row["state"]))

    def _orders_alerts(self) -> list[OutgoingMessage]:
        """TESTNET: 주문 프로세스(B)의 심장 박동이 끊기면 경고(끊길 때 한 번, 돌아오면 다시 무장)."""
        if not self._testnet:
            return []
        from bot.orders import queue as oq

        with self.lock:
            hb = oq.get_runtime(self.conn, "b_heartbeat_ms")
            now_ms = self.now_ms()
        ref = int(hb["value"]) if hb is not None else self._started_ms   # 기록이 없으면 A 시작부터 잰다
        stale = now_ms - ref > ORDERS_HEARTBEAT_STALE_MS
        if not stale:
            self._b_down_alerted = False
            return []
        if self._b_down_alerted:
            return []
        self._b_down_alerted = True
        return [self._alert("주문 프로세스(B) 심장 박동 없음 — 승인해도 주문되지 않는다. 서버에서"
                            " `docker compose --profile testnet ps orders`·로그 확인(RUNBOOK 테스트넷 §T8)")]

    def _orders_status_lines(self) -> list[str]:
        from bot.orders import queue as oq

        now_ms = self.now_ms()
        hb = oq.get_runtime(self.conn, "b_heartbeat_ms")
        rec = oq.get_runtime(self.conn, "last_reconcile_ms")
        rec_ok = oq.get_runtime(self.conn, "last_reconcile_ok")
        released = {int(r["halt_id"]) for r in self.conn.execute("SELECT halt_id FROM order_halt_releases")}
        open_halts = [r for r in oq.halts(self.conn) if int(r["halt_id"]) not in released]
        live = oq.live_intent(self.conn)
        age = "없음" if hb is None else f"{max(0, now_ms - int(hb['value'])) // 1000}초 전"
        lines = [f"주문 프로세스(B) 심장 박동: {age}"
                 + ("" if rec is None else f" · 마지막 대조 {kst_str(int(rec['value']), '%H:%M:%S KST')}"
                    f" {'정상' if rec_ok is not None and rec_ok['value'] == '1' else '문제'}"),
                 f"보유 주문 의도: {'없음' if live is None else str(int(live['subsystem_n'])) + '일 ' + live['state']}"]
        if open_halts:
            lines.append("킬 스위치 T0(해제 기록 없음): " + ", ".join(f"#{int(r['halt_id'])} {r['reason']}"
                                                            for r in open_halts[-5:])
                         + " — 해제는 서버 제어 파일에서만(/resume은 T0에 영향 없음)")
        return lines

    def _skip_notices(self, skipped: list[tuple[sqlite3.Row, str]]) -> list[OutgoingMessage]:
        """생성 즉시 건너뛴 신호 알림(OPS-9): 어느 하위 시스템이 왜 건너뛰어졌는지."""
        if not skipped:
            return []
        lines = [f"{self.cfg.mode_tag} 알림: 신호 {len(skipped)}건을 카드 없이 건너뜀(진입 안 함)"]
        for sig, reason in skipped:
            lines.append(f"- {int(sig['subsystem_n'])}일 돌파 ({sig['signal_day']} 일봉, 판단 {kst_str(sig['decision_ms'])})"
                         f" — 사유: {SKIP_REASON_KO.get(reason, reason)} [{reason}]")
        return [OutgoingMessage(text="\n".join(lines), kind="alert")]

    def _disk_check(self, cycle_day: str) -> list[OutgoingMessage]:
        free = self.disk_free_bytes()
        if free is None or free >= DISK_FREE_WARN_BYTES or self._disk_warned_day == cycle_day:
            return []
        self._disk_warned_day = cycle_day
        with self.lock:
            db.audit(self.conn, ts_ms=self.now_ms(), actor=Actor.ENGINE, event=AuditEvent.ALERT,
                     payload=dict(reason="disk_low", free_bytes=free))
        return [self._alert(f"디스크 여유 공간 부족: {free / (1 << 20):,.0f} MB 남음 — RUNBOOK '백업'의 오래된 백업 정리 참고")]

    def _new_signals_for(self, decision_ms: int) -> list[sqlite3.Row]:
        return [r for r in db.signals_in_states(self.conn, [S.NEW]) if int(r["decision_ms"]) == int(decision_ms)]

    def _cycle_analyze(self, report: CycleReport, frame, decision_ns: int) -> None:
        """7) NEW 신호가 있고 그날 분석이 아직 없으면 Claude 1회. 호출 자체는 락 밖(최대 120초)."""
        decision_ms = ns_to_ms(decision_ns)
        with self.lock:
            new = self._new_signals_for(decision_ms)
            if not new:
                return
            signal_day = new[0]["signal_day"]
            done = self.conn.execute("SELECT 1 FROM analyses WHERE signal_day = ? LIMIT 1", (signal_day,)).fetchone()
            if done is not None:
                return
            payload = ST.analysis_input(frame, report.signals,
                                        open_positions=self._open_position_dicts(frame, decision_ms))
        result = self._safe_analyze(payload)
        with self.lock:
            db.insert_analysis(self.conn, result, signal_day=signal_day, now_ms=self.now_ms())

    def _daily_report(self) -> list[OutgoingMessage]:
        """일일 리포트(모의 매매 담당). 실패해도 사이클은 성공(보고용)."""
        try:
            if self._testnet:
                return [self._testnet_daily_report()]
            with self.lock:
                return [paper.daily_report(self.conn, self.cfg, self.now_ns())]
        except NotImplementedError:
            return []
        except Exception:
            log.exception("일일 리포트 실패")
            return []

    def _testnet_daily_report(self) -> OutgoingMessage:
        """TESTNET 일일 리포트: 거래소(데모) 보유·지난 24시간 주문 의도 결과·B 상태(값은 order_intents 기록)."""
        with self.lock:
            now_ms = self.now_ms()
            since = now_ms - MS_PER_DAY
            done = list(self.conn.execute(
                "SELECT subsystem_n, state, state_reason, exit_reason, avg_fill_price, exit_price FROM order_intents"
                " WHERE updated_ms >= ? AND state IN ('CLOSED', 'FAILED_FLATTENED', 'NOT_FILLED', 'REJECTED', 'HALTED')"
                " ORDER BY intent_id", (since,)))
            status = self._orders_status_lines()
        lines = [f"{self.cfg.mode_tag} 일일 리포트 · {kst_str(now_ms)}", self.positions_text(),
                 f"■ 지난 24시간 끝난 주문 의도 {len(done)}건"]
        for r in done:
            px = "" if r["exit_price"] is None else f" · 청산 {float(r['exit_price']):,.1f}"
            fill = "" if r["avg_fill_price"] is None else f" · 체결 {float(r['avg_fill_price']):,.1f}"
            lines.append(f"- {int(r['subsystem_n'])}일 {r['state']}({r['exit_reason'] or r['state_reason'] or '-'})"
                         f"{fill}{px}")
        lines.extend(status)
        return OutgoingMessage(text="\n".join(lines), kind="report")

    def mark_card_sent(self, signal_id: str, message_id: int) -> bool:
        """NEW → CARD_SENT (card_sent_ms, tg_message_id, analysis_id 기록). 만료 뒤면 False(tick이 만료 처리)."""
        with self.lock, db.transaction(self.conn):
            sig = db.get_signal(self.conn, signal_id)
            now_ms = self.now_ms()
            if sig is None or sig["state"] != S.NEW.value or now_ms >= int(sig["expires_ms"]):
                return False
            fields: dict[str, Any] = dict(card_sent_ms=now_ms, tg_message_id=int(message_id))
            analysis = self._analysis_for(sig)
            if sig["analysis_id"] is None and analysis is not None:
                fields["analysis_id"] = int(analysis["analysis_id"])
            return db.transition_signal(self.conn, signal_id, S.NEW, S.CARD_SENT, now_ms=now_ms,
                                        actor=Actor.ENGINE, reason="card_sent", fields=fields)

    # --- 버튼 (telegram_ui가 권한·형식·중복 검사를 마친 뒤 부른다) -------------------------
    def _expire_if_due(self, sig: sqlite3.Row, now_ms: int) -> bool:
        """승인 창이 지났으면 EXPIRED로 바꾸고 True."""
        if sig["state"] in {s.value for s in PENDING_APPROVAL_STATES} and now_ms >= int(sig["expires_ms"]):
            db.transition_signal(self.conn, sig["signal_id"], sig["state"], S.EXPIRED, now_ms=now_ms,
                                 actor=Actor.ENGINE, reason="approval_window")
            return True
        return False

    def request_confirm(self, signal_id: str, *, at_ms: int | None = None) -> bool:
        """[승인]: CARD_SENT → CONFIRM_PENDING (confirm_expires = 누른 시각 + 60초). 만료·일시정지·상태 불일치면 False.
        at_ms = 버튼을 누른 시각(락 대기 전, OPS-4). 없으면 지금."""
        with self.lock, db.transaction(self.conn):
            sig = db.get_signal(self.conn, signal_id)
            now_ms = self._press_ms(at_ms)
            if sig is None or self._expire_if_due(sig, now_ms) or db.is_paused(self.conn):
                return False
            return db.transition_signal(
                self.conn, signal_id, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=now_ms, actor=Actor.TELEGRAM_USER,
                reason="approve", fields=dict(confirm_requested_ms=now_ms,
                                              confirm_expires_ms=now_ms + int(self.cfg.schedule.confirm_window_s) * 1000))

    def confirm(self, signal_id: str, *, at_ms: int | None = None) -> bool:
        """[확인]: CONFIRM_PENDING → APPROVED (approved_ms = 누른 시각, approval_latency_ms = 누른 시각 − 판단).
        확인 창(60초) 또는 승인 창(2시간)이 지났으면 전이하지 않고 False(확인 창 초과는 CARD_SENT로 되돌림).
        at_ms = 버튼을 누른 시각(락 대기 전, OPS-4). 모의 체결은 이 시각 이후 첫 1분봉 시가."""
        with self.lock, db.transaction(self.conn):
            sig = db.get_signal(self.conn, signal_id)
            now_ms = self._press_ms(at_ms)
            if sig is None or sig["state"] != S.CONFIRM_PENDING.value:
                return False
            if self._expire_if_due(sig, now_ms):
                return False
            if sig["confirm_expires_ms"] is None or now_ms > int(sig["confirm_expires_ms"]):
                db.transition_signal(self.conn, signal_id, S.CONFIRM_PENDING, S.CARD_SENT, now_ms=now_ms,
                                     actor=Actor.ENGINE, reason="confirm_timeout")
                return False
            if db.is_paused(self.conn):
                return False
            ok = db.transition_signal(
                self.conn, signal_id, S.CONFIRM_PENDING, S.APPROVED, now_ms=now_ms, actor=Actor.TELEGRAM_USER,
                reason="confirm", fields=dict(approved_ms=now_ms,
                                              approval_latency_ms=now_ms - int(sig["decision_ms"])))
            if ok and self._testnet:
                # 같은 트랜잭션: APPROVED와 QUEUED가 함께 생기거나 함께 없다(B는 이 행만 가져간다)
                from bot.orders import queue as oq

                oq.enqueue(self.conn, signal_id=signal_id, now_ms=now_ms)
            return ok

    def cancel_confirm(self, signal_id: str, *, at_ms: int | None = None) -> bool:
        """확인 화면 [취소]: CONFIRM_PENDING → CARD_SENT (승인 창 안이면 다시 [승인] 가능)."""
        with self.lock, db.transaction(self.conn):
            sig = db.get_signal(self.conn, signal_id)
            now_ms = self._press_ms(at_ms)
            if sig is None or self._expire_if_due(sig, now_ms):
                return False
            return db.transition_signal(self.conn, signal_id, S.CONFIRM_PENDING, S.CARD_SENT, now_ms=now_ms,
                                        actor=Actor.TELEGRAM_USER, reason="cancel")

    def pass_signal(self, signal_id: str, *, at_ms: int | None = None) -> bool:
        """[패스]: CARD_SENT|CONFIRM_PENDING → PASSED. 승인 창이 지났으면 EXPIRED로 두고 False."""
        with self.lock, db.transaction(self.conn):
            sig = db.get_signal(self.conn, signal_id)
            now_ms = self._press_ms(at_ms)
            if sig is None or self._expire_if_due(sig, now_ms):
                return False
            return db.transition_signal(self.conn, signal_id, (S.CARD_SENT, S.CONFIRM_PENDING), S.PASSED,
                                        now_ms=now_ms, actor=Actor.TELEGRAM_USER, reason="pass")

    # --- 1분 주기 -----------------------------------------------------------------------
    def tick(self) -> list[OutgoingMessage]:
        """만료 처리(승인 창·확인 창) → paper.fill_approved → paper.monitor → 미전송 카드 재전송 목록.
        시세 이상이면 체결·감시만 건너뛰고(다음 tick에 커서로 따라잡음) 경고는 오류가 바뀔 때 한 번만."""
        from bot.marketdata import MarketDataError

        out: list[OutgoingMessage] = []
        now_ms = self.now_ms()
        with self.lock:
            # a. 승인 창 만료
            for sig in db.signals_in_states(self.conn, PENDING_APPROVAL_STATES):
                if now_ms >= int(sig["expires_ms"]):
                    if db.transition_signal(self.conn, sig["signal_id"], sig["state"], S.EXPIRED, now_ms=now_ms,
                                            actor=Actor.ENGINE, reason="approval_window") \
                            and sig["tg_message_id"] is not None:
                        out.append(OutgoingMessage(
                            text=f"{self.cfg.mode_tag} 만료: {int(sig['subsystem_n'])}일 돌파 신호"
                                 f" ({sig['signal_day']}) — 승인 마감 {kst_str(sig['expires_ms'])} 지남",
                            signal_id=sig["signal_id"], kind="expired", edit_message_id=int(sig["tg_message_id"])))
            # b. 확인 창 초과 → CARD_SENT로 되돌리고 카드 버튼 원복
            for sig in db.signals_in_states(self.conn, [S.CONFIRM_PENDING]):
                ce = sig["confirm_expires_ms"]
                if ce is None or now_ms > int(ce):
                    if db.transition_signal(self.conn, sig["signal_id"], S.CONFIRM_PENDING, S.CARD_SENT,
                                            now_ms=now_ms, actor=Actor.ENGINE, reason="confirm_timeout") \
                            and sig["tg_message_id"] is not None:
                        row = db.get_signal(self.conn, sig["signal_id"])
                        out.append(self._card(row, edit_message_id=int(sig["tg_message_id"])))
        # c·d. 모의 체결·감시 — 시세 조회는 락 밖(OPS-4: 버튼 처리가 네트워크 재시도를 기다리지 않게)
        now_ns = self.now_ns()
        try:
            out.extend(self._paper_catch_up(now_ns))
            self._last_tick_error = None
        except MarketDataError as exc:
            err = str(exc)[:200]
            log.warning("tick 시세 이상: %s", err)
            if err != self._last_tick_error:
                self._last_tick_error = err
                with self.lock:
                    db.audit(self.conn, ts_ms=now_ms, actor=Actor.ENGINE, event=AuditEvent.DATA_CHECK,
                             entity_type="tick", payload=dict(error=err))
                out.append(self._alert("1분 감시 중 시세 이상 — 체결·손절 감시 보류, 다음 주기에 재시도"))
        out.extend(self._gap_alerts())
        out.extend(self._orders_alerts())
        # e. 미전송 카드
        out.extend(self.unsent_cards())
        return out

    def _gap_alerts(self) -> list[OutgoingMessage]:
        """거래소 1분봉 빈 구간(점검 등) — 감사 + 경고 한 번씩(R-4). 체결·감시는 다음 봉으로 계속한다(백테스트와 같음)."""
        take = getattr(self.market, "take_gaps", None)
        if not callable(take):
            return []
        gaps = take()
        if not gaps:
            return []
        with self.lock:
            for g0, g1 in gaps:
                db.audit(self.conn, ts_ms=self.now_ms(), actor=Actor.ENGINE, event=AuditEvent.DATA_CHECK,
                         entity_type="minute_gap", payload=dict(gap_from_ms=ns_to_ms(g0), gap_to_ms=ns_to_ms(g1),
                                                                missing_bars=int((g1 - g0) // NS_PER_MIN)))
        spans = ", ".join(f"{kst_str(ns_to_ms(a), '%m-%d %H:%M')}~{kst_str(ns_to_ms(b), '%H:%M KST')}" for a, b in gaps[:5])
        return [self._alert(f"거래소 1분봉 빈 구간 {len(gaps)}곳({spans}) — 다음 봉으로 체결·감시 계속(백테스트와 같은 규칙)")]

    def unsent_cards(self) -> list[OutgoingMessage]:
        """NEW 상태이고 아직 만료 전인 신호의 카드(전송 실패 재시도용).
        그 날 사이클이 아직 RUNNING(Claude 분석 중)이면 빼서, 분석 전에 카드가 먼저 나가지 않게 한다."""
        with self.lock:
            now_ms = self.now_ms()
            out = []
            for sig in db.signals_in_states(self.conn, [S.NEW]):
                if now_ms >= int(sig["expires_ms"]):
                    continue
                cyc = self.conn.execute("SELECT status FROM cycles WHERE cycle_day = ?",
                                        (_day_str(int(sig["decision_ms"])),)).fetchone()
                if cyc is not None and cyc["status"] == "RUNNING":
                    continue
                out.append(self._card(sig))
            return out

    # --- 명령 ---------------------------------------------------------------------------
    def pause(self, actor: str) -> list[str]:
        """신규 진입 중지: 플래그 설정 + NEW/CARD_SENT/CONFIRM_PENDING/APPROVED → SKIPPED('paused'). 반환 = 건너뛴 신호 ID.
        열린 포지션의 보호 손절·추세 청산은 계속 돈다(위험을 줄이는 방향)."""
        act = _actor(actor)
        skipped: list[str] = []
        with self.lock, db.transaction(self.conn):
            now_ms = self.now_ms()
            db.set_paused(self.conn, True, now_ms=now_ms, actor=act)
            for sig in db.signals_in_states(self.conn, PAUSE_SKIP_STATES):
                if self._testnet and sig["state"] == S.APPROVED.value:
                    from bot.orders import queue as oq

                    if oq.intent_for_signal(self.conn, sig["signal_id"]) is not None:
                        # B가 이미 가져갔으면(False) 신호를 건드리지 않는다 — B가 거래소 사실로 끝낸다.
                        # 아직 QUEUED면 REJECTED('paused')와 신호 SKIPPED가 같은 트랜잭션에서 된다(queue._sync_signal).
                        if oq.cancel_queued(self.conn, sig["signal_id"], now_ms=now_ms, reason="paused",
                                            actor=str(getattr(act, "value", act))):
                            skipped.append(sig["signal_id"])
                        continue
                if db.transition_signal(self.conn, sig["signal_id"], sig["state"], S.SKIPPED, now_ms=now_ms,
                                        actor=act, reason="paused"):
                    skipped.append(sig["signal_id"])
        return skipped

    def resume(self, actor: str) -> bool:
        """신규 신호 다시 받기(건너뛴 신호는 되살리지 않는다). 값이 바뀌면 True."""
        with self.lock:
            return db.set_paused(self.conn, False, now_ms=self.now_ms(), actor=_actor(actor))

    def status_text(self) -> str:
        with self.lock:
            now_ms = self.now_ms()
            last = self.conn.execute("SELECT * FROM cycles ORDER BY cycle_day DESC LIMIT 1").fetchone()
            counts = {r["state"]: int(r["c"]) for r in
                      self.conn.execute("SELECT state, COUNT(*) AS c FROM signals GROUP BY state")}
            n_open = len(self._holding_intents()) if self._testnet else len(db.open_positions(self.conn))
            paused = db.is_paused(self.conn)
            orders_lines = self._orders_status_lines() if self._testnet else []
        pending = sum(counts.get(s.value, 0) for s in PENDING_APPROVAL_STATES) + counts.get(S.APPROVED.value, 0)
        next_dec = self.decision_ns_for(ms_to_ns(now_ms))
        if ms_to_ns(now_ms) >= next_dec:
            next_dec += 24 * 3600 * NS_PER_SEC
        lines = [
            f"{self.cfg.mode_tag} 상태 · {kst_str(now_ms)}",
            f"전략 {self.cfg.strategy_key} · 신규 진입 {'일시정지' if paused else '받는 중'}",
            f"마지막 사이클: " + (f"{last['cycle_day']} {last['status']}" if last is not None else "없음"),
            f"다음 판단: {kst_str(ns_to_ms(next_dec))}",
            f"승인 대기·체결 대기 신호 {pending}건 · "
            + (f"거래소(데모) 보유 {n_open}개" if self._testnet else f"열린 모의 포지션 {n_open}개"),
            "누적: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) if counts else "누적: 신호 없음",
            *orders_lines,
        ]
        return "\n".join(lines)

    def positions_text(self) -> str:
        if self._testnet:
            with self.lock:
                rows = self._holding_intents()
            if not rows:
                return f"{self.cfg.mode_tag} 거래소(데모) 보유 포지션 없음"
            lines = [f"{self.cfg.mode_tag} 거래소(데모) 보유 {len(rows)}개 (값은 주문 프로세스 기록)"]
            for r in rows:
                due = f" · 추세 청산 예정 {kst_str(r['exit_due_ms'])}" if r["exit_due_ms"] is not None else ""
                stop = "-" if r["stop_price"] is None else f"{float(r['stop_price']):,.1f}"
                lines.append(f"- {int(r['subsystem_n'])}일: 체결 {float(r['avg_fill_price']):,.1f}"
                             f" ({kst_str(r['entry_fill_ms'])}) · 손절 {stop} · 수량 {float(r['filled_qty']):.3f} BTC"
                             f" · {r['state']}{due}")
            return "\n".join(lines)
        with self.lock:
            rows = db.open_positions(self.conn)
        if not rows:
            return f"{self.cfg.mode_tag} 열린 모의 포지션 없음"
        lines = [f"{self.cfg.mode_tag} 열린 모의 포지션 {len(rows)}개"]
        for p in rows:
            due = f" · 추세 청산 예정 {kst_str(p['exit_due_ms'])}" if p["exit_due_ms"] is not None else ""
            lines.append(f"- {int(p['subsystem_n'])}일: 진입 {p['entry_price']:,.1f} ({kst_str(p['entry_ms'])})"
                         f" · 손절 {p['stop']:,.1f} · 수량 {p['qty']:.4f} BTC{due}")
        return "\n".join(lines)
