"""프로세스 B 진입점·루프 — 통합 담당 (DESIGN §1, §8, §13).

사용 (서비스 orders 컨테이너 안에서)
    python -m bot.orders.worker --config /config/bot.toml                  # 루프 실행(기본 = run)
    python -m bot.orders.worker --config /config/bot.toml status           # DB만: 보유 의도·T0(해제 여부)·대조·심장 박동
    python -m bot.orders.worker --config /config/bot.toml selftest         # 조회만 하는 거래소 점검(주문 없음)
    python -m bot.orders.worker --config /config/bot.toml selftest --roundtrip
        # 왕복 시험: 점검 통과 뒤 시험 신호 1건을 큐에 넣고, **돌고 있는 워커**가 진입 → 손절 → 확인 → 추세 청산 →
        # 손절 취소까지 끝내는 것을 지켜본다. 텔레그램 /selftest는 없다(텔레그램으로는 주문 명령 불가 — 서버 명령만).

시작 순서(run): umask 077 → 환경 변수 비밀 금지 검사 → 설정(mode == testnet 아니면 종료 코드 2, [orders] 검증)
  → A 쪽 비밀(텔레그램·Claude)이 보이면 거부 → 키 파일 2개 읽기(read_secret / read_pem_secret, 0400/0600)
  → 클라이언트(호스트 = 코드 상수표) → DB 연결(mode 일치, queue.ensure_schema) → Worker.startup(): 제어 파일 → recover()
루프(loop_interval_s): 제어 파일 → 해제 기록 → (주기면) 대조 → 추세 청산 기한 → 정지면 QUEUED 거부 → 낡은 승인·
  보유 중(O-3) QUEUED 거부 → claim_next → Gateway.process_intent → order_runtime.b_heartbeat_ms·심장 박동 파일.
예외는 종류만 기록(비밀 누출 방지). 알 수 없는 예외로 루프가 죽으면 compose가 재시작 → recover가 거래소 사실로 복구.
심장 박동은 한 바퀴가 **성공**했을 때만 갱신한다(계속 실패하면 A의 경고·compose healthcheck가 알아챈다).

종료 코드: 0 정상, 1 그 밖의 오류(selftest 실패 포함), 2 설정·비밀 오류·이미 다른 B가 실행 중, 3 DB 오류(모드 불일치·변조).

수정 담당(검토 지적 반영)
- B는 하나만 돈다: run은 DB 옆 잠금 파일에 배타 flock을 잡고, 잡혀 있으면 종료 코드 2(F6).
- B 전용 원장(orders.ledger_file, B만 마운트하는 /state 볼륨): T0·진입·청산·해제 첫 확인 시각(SEC-02·SEC-04·F8).
- 매 바퀴 DB 무결성(보호 트리거 본문·추가 전용 표의 빈 번호) 검사 → 문제면 T0(SEC-02).
- 한 바퀴가 거래소 밖 예외로 끝나면 DB 없이 보호(emergency_protect)하고 다음 바퀴에 recover()를 먼저 돈다(F4·SEC-03).
- STOP_VERIFIED 보유 중에는 대조 주기 사이에도 매 바퀴 손절 존재를 가볍게 조회해, 없으면 대조를 앞당긴다(F7).
- 시작을 거부해야 할 때(설정·A 비밀·DB·시작 복구 예외)도 거부 **전에** DB 없이 보호한다(V-1, R-15): 우리 손절이
  없으면 reduceOnly 청산. 잠금은 DB 연결보다 먼저 잡는다(다른 B가 있으면 보호에 끼어들지 않는다).
- HALTED·EXITING 보유도 매 바퀴 손절 없음을 가볍게 조회한다: HALTED면 곧바로 secure_halted, EXITING이면 대조(V-2, R-16).
"""
from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from bot import db
from bot.orders import queue
from bot.orders.control import ControlState, load_control
from bot.orders.gateway import RELEASE_AT_TOLERANCE_MS, Gateway, protect_without_db
from bot.orders.ledger import Ledger
from bot.orders.reconcile import ReconcileReport, reconcile_once, recover
from bot.orders.types import (
    EXIT_ATTEMPTS,
    INTENT_TERMINAL,
    MAX_LEVERAGE,
    PRICE_TICK,
    QTY_STEP,
    SYMBOL,
    ExchangeClient,
    ExchangeError,
    GatewayResult,
    IntentState,
    OrdersConfig,
)
from bot.types import AuditEvent, Clock, Mode, NS_PER_MS, SignalState, SystemClock, new_signal_id, utc_iso_ms

log = logging.getLogger("bot.orders.worker")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2
EXIT_DB = 3

HEARTBEAT_PATH = "/tmp/orders-heartbeat"     # compose healthcheck가 이 파일의 나이를 본다
S = IntentState

# 왕복 시험(selftest --roundtrip)
SELFTEST_SPEC = "SELFTEST"                   # signals.spec_version 표시(진짜 전략 신호와 구분)
SELFTEST_ATR_FRAC = 0.01                     # 시험 ATR20 = 마크 × 1% → 손절 거리 약 2%(방화벽 0.2~25% 안)
SELFTEST_HEARTBEAT_MAX_AGE_MS = 30_000       # 워커 심장 박동이 이보다 오래되면 왕복 시험을 시작하지 않는다
SELFTEST_TIMEOUT_S = 180


def _now_ms(clock: Clock) -> int:
    return int(clock.now_ns()) // NS_PER_MS


def _clock_sleeper(clock: Clock) -> Callable[[int], None]:
    """FakeClock(시험)이면 시계만 진행, 아니면 실제로 잔다."""
    adv = getattr(clock, "advance", None)
    if adv is not None:
        return lambda ms: adv(int(ms) * NS_PER_MS)
    return lambda ms: time.sleep(max(0, int(ms)) / 1000.0)


def _touch(path: str | None) -> None:
    if not path:
        return
    try:
        p = Path(path)
        p.touch(mode=0o600, exist_ok=True)
        os.utime(p, None)
    except OSError as exc:
        log.warning("심장 박동 파일 갱신 실패: %s", type(exc).__name__)


# ---------------------------------------------------------------------------
# 워커
# ---------------------------------------------------------------------------


class Worker:
    """프로세스 B의 한 바퀴 단위 루프. 거래소 주문·취소는 전부 Gateway(방화벽)를 거친다."""

    def __init__(self, conn: sqlite3.Connection, cfg: OrdersConfig, ex: ExchangeClient, clock: Clock, *,
                 control_loader: Callable[[], ControlState] | None = None,
                 sleep_ms: Callable[[int], None] | None = None, heartbeat_path: str | None = None,
                 ledger: Ledger | None = None) -> None:
        self.conn = conn
        self.cfg = cfg
        self.ex = ex
        self.clock = clock
        # 방화벽 FW-ENV는 **클라이언트가 실제로 쓰는** 주소를 본다(설정 값으로 대신하지 않는다).
        base_url = getattr(ex, "base_url", None)
        if not isinstance(base_url, str) or not base_url:
            raise ValueError("거래소 클라이언트에 base_url이 없다")
        self.ledger = ledger if ledger is not None else Ledger(None)
        self.gw = Gateway(conn, cfg, ex, clock, base_url=base_url, sleep_ms=sleep_ms, ledger=self.ledger)
        self._control_loader = control_loader or (lambda: load_control(cfg.control_file))
        self.heartbeat_path = heartbeat_path
        self.control = ControlState(manual_halt=True, error="not_loaded")
        self.started = False
        self.last_reconcile_ms: int | None = None
        self.last_reconcile: ReconcileReport | None = None
        self.results: list[GatewayResult] = []       # 이번 프로세스가 처리한 의도(시험·로그용)
        self._control_error_notified: str | None = None
        self.loop_errors = 0
        self.needs_recover = False                   # 직전 바퀴가 예외로 끝남 → 다음 바퀴에 recover() 먼저

    def now_ms(self) -> int:
        return _now_ms(self.clock)

    # --- 제어 파일 --------------------------------------------------------------------
    def _load_control(self) -> ControlState:
        try:
            c = self._control_loader()
        except Exception as exc:  # noqa: BLE001 — 읽기 실패 = 수동 정지(fail-closed)
            c = ControlState(manual_halt=True, error=f"loader:{type(exc).__name__}")
        now = self.now_ms()
        if c.error is not None and c.error != self._control_error_notified:
            self._control_error_notified = c.error
            log.warning("제어 파일 문제(%s) — 수동 정지로 간주(신규 진입 차단)", c.error)
            queue.notify(self.conn, f"주문 제어 파일 문제({c.error}) — 수동 정지로 간주, 신규 진입 차단"
                                    "(보유 손절·추세 청산은 계속). 서버에서 제어 파일 확인(RUNBOOK 테스트넷 §T5)",
                         now_ms=now, kind="alert")
        elif c.error is None:
            self._control_error_notified = None
        # 해제 판정은 게이트웨이(그 T0 뒤에 처음 본 해제만 — F8). 인정된 것만 기록한다.
        self.gw.set_control(c)
        for hid in sorted(self.gw.released):
            if queue.record_release(self.conn, hid, control_ref=c.ref or "control", now_ms=now):
                log.info("T0 #%d 해제 기록(제어 파일)", hid)
                queue.notify(self.conn, f"킬 스위치 T0 #{hid} 해제(서버 제어 파일)", now_ms=now)
        ignored = sorted(set(c.released) - set(self.gw.released))
        if ignored:
            log.info("제어 파일 해제 중 인정하지 않은 id(그 T0 전에 적힘·T0 없음): %s", ignored)
        self.control = c
        return c

    # --- 시작·복구 ----------------------------------------------------------------------
    def startup(self) -> ReconcileReport:
        """ensure_schema(보호 트리거 검사) → 제어 파일 → recover(DESIGN §8). 새 의도를 가져가기 전에 반드시."""
        queue.ensure_schema(self.conn)
        control = self._load_control()
        self.gw.check_integrity()
        report = recover(self.conn, self.gw, self.ex, self.clock, control)
        self.last_reconcile_ms = self.now_ms()
        self.last_reconcile = report
        self.started = True
        self.needs_recover = False
        self._heartbeat()
        log.info("주문 프로세스 시작 복구: ok=%s issues=%s", report.ok, sorted(set(report.issues)))
        return report

    # --- 한 바퀴 -----------------------------------------------------------------------
    def run_once(self) -> GatewayResult | None:
        """한 바퀴. 처리한 의도의 결과(없으면 None)."""
        if not self.started:
            raise RuntimeError("startup()을 먼저 불러야 한다(재시작 복구 없이 새 의도를 가져가지 않는다)")
        try:
            return self._run_once()
        except Exception:
            # 거래소 밖 예외(DB 잠김 등): DB 없이 보호하고, 다음 바퀴에 거래소 사실로 복구한다(F4·SEC-03)
            self.needs_recover = True
            try:
                self.gw.emergency_protect("loop_error")
            except Exception as exc2:  # noqa: BLE001
                log.error("비상 보호 실패: %s", type(exc2).__name__)
            raise

    def _run_once(self) -> GatewayResult | None:
        control = self._load_control()
        if self.needs_recover:
            self.last_reconcile = recover(self.conn, self.gw, self.ex, self.clock, control)
            self.last_reconcile_ms = self.now_ms()
            self.needs_recover = False
        self.gw.check_integrity()
        now = self.now_ms()
        due = self.last_reconcile_ms is None or now - self.last_reconcile_ms >= int(self.cfg.reconcile_interval_s) * 1000
        if not due:
            live = queue.live_intent(self.conn)
            lst = None if live is None else IntentState(live["state"])
            if lst is S.STOP_VERIFIED and not self.gw.quick_stop_check(live):
                log.warning("보유 손절이 조회에 없다 — 대조를 앞당긴다")
                due = True
            elif lst is S.HALTED and self.gw.quick_unprotected_check(live):
                # V-2: 청산·손절 재등록이 실패한 HALTED 보유를 대조 주기(30초)까지 두지 않는다 — 매 바퀴 다시 보호
                log.warning("HALTED 보유에 손절이 없다 — 매 바퀴 보호 재시도(secure_halted)")
                self.gw.secure_halted(live)
            elif lst is S.EXITING and self.gw.quick_unprotected_check(live):
                log.warning("EXITING 보유에 손절이 없다 — 대조를 앞당긴다")
                due = True
        if due:
            self.last_reconcile = reconcile_once(self.conn, self.gw, self.ex, self.clock, control)
            self.last_reconcile_ms = self.now_ms()
        self._trend_exits()
        # 정지(T0·수동) 중이면 QUEUED 전부 거부. 아니어도 낡은 승인·보유 중(O-3)이면 거부.
        self.gw.reject_queued_if_halted(control)
        self.gw.reject_stale_queued()
        self.gw.reject_queued_if_position_exists()
        result = None
        if not self.gw.is_halted(control):
            row = queue.claim_next(self.conn, now_ms=self.now_ms())
            if row is not None:
                result = self.gw.process_intent(row, control)
                self.results.append(result)
                log.info("의도 #%d → %s (%s)", result.intent_id, result.final_state.value, result.reason)
                # 같은 날 함께 승인된 다른 신호는 바로 알린다(O-3: 다음 바퀴의 낡은 승인 판정을 기다리지 않게)
                self.gw.reject_queued_if_position_exists()
        self._heartbeat()
        return result

    def _trend_exits(self) -> None:
        """추세 청산 기한이 지난 STOP_VERIFIED·EXITING(정지 중에도 — 위험을 줄이는 방향, O-15).
        EXITING이 3회를 다 쓴 뒤에는 새 주문을 보내지 않는다(T0가 이미 걸렸고 대조가 손절을 계속 본다)."""
        now = self.now_ms()
        for row in queue.intents_in_states(self.conn, [S.STOP_VERIFIED, S.EXITING]):
            due = row["exit_due_ms"]
            if due is None or now < int(due):
                continue
            if IntentState(row["state"]) is S.EXITING and int(row["exit_attempts"] or 0) >= EXIT_ATTEMPTS:
                continue
            self.gw.run_trend_exit(row)

    def _heartbeat(self) -> None:
        now = self.now_ms()
        queue.set_runtime(self.conn, "b_heartbeat_ms", now, now_ms=now)
        _touch(self.heartbeat_path)

    def run_forever(self, stop: threading.Event) -> None:
        """stop이 켜질 때까지 loop_interval_s마다 run_once. 예외는 종류만 기록하고 다음 바퀴에 다시."""
        if not self.started:
            self.startup()
        while not stop.is_set():
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 — 루프는 죽지 않는다(심장 박동이 멈춰 경고가 간다)
                self.loop_errors += 1
                log.error("주문 루프 오류: %s", type(exc).__name__)
            stop.wait(float(self.cfg.loop_interval_s))


# ---------------------------------------------------------------------------
# 점검(selftest) — 조회만
# ---------------------------------------------------------------------------


@dataclass
class CheckLine:
    name: str
    ok: bool
    detail: str


@dataclass
class SelftestReport:
    lines: list[CheckLine] = field(default_factory=list)
    mark: float | None = None

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.lines)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.lines.append(CheckLine(name, bool(ok), detail))

    def text(self) -> str:
        return "\n".join(f"[{'통과' if c.ok else '실패'}] {c.name}: {c.detail}" for c in self.lines)


def selftest_checks(ex: ExchangeClient, cfg: OrdersConfig, clock: Clock) -> SelftestReport:
    """조회만 하는 거래소 점검(주문·취소 없음). 결과는 사람이 RUNBOOK의 PoC 기록표(K3·K8·K9·K10·K11)에 옮긴다."""
    rep = SelftestReport()
    rep.add("환경", getattr(ex, "base_url", "") == cfg.base_url,
            f"env={cfg.env.value} · 호스트 {getattr(ex, 'base_url', '?')} (K3)")

    def q(name: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except ExchangeError as exc:
            rep.add(name, False, f"조회 실패 {exc.kind.value} http={exc.http_status} code={exc.code}")
            return None

    t0 = _now_ms(clock)
    server = q("서버 시각", ex.server_time_ms)
    if server is not None:
        off = int(server) - (t0 + _now_ms(clock)) // 2
        rep.add("서버 시각", abs(off) <= cfg.max_clock_skew_ms, f"오차 {off} ms (한도 ±{cfg.max_clock_skew_ms})")
    rules = q("심볼 규칙", ex.symbol_rules)
    if rules is not None:
        ok = (rules.symbol == SYMBOL and abs(rules.tick_size - PRICE_TICK) < 1e-12
              and abs(rules.step_size - QTY_STEP) < 1e-12 and rules.status == "TRADING")
        rep.add("심볼 규칙", ok, f"{rules.symbol} tick {rules.tick_size} step {rules.step_size} minQty {rules.min_qty}"
                                 f" minNotional {rules.min_notional} {rules.status} (K11)")
    acct = q("계정 모드", ex.account_config)
    if acct is not None:
        rep.add("계정 모드", not acct.dual_side_position and not acct.multi_assets_margin and acct.can_trade,
                f"One-way={not acct.dual_side_position} · Single-Asset={not acct.multi_assets_margin}"
                f" · canTrade={acct.can_trade} (K9)")
        rep.add("레버리지·마진", acct.leverage == cfg.expected_leverage and acct.leverage <= MAX_LEVERAGE
                and acct.margin_type == "isolated",
                f"레버리지 {acct.leverage}(설정 {cfg.expected_leverage}) · {acct.margin_type} (K8)")
        rep.add("출금 권한", acct.can_withdraw is not True,
                "모름(K10 — LIVE 전 반드시 확인)" if acct.can_withdraw is None else f"canWithdraw={acct.can_withdraw}")
    bal = q("잔고", ex.balance)
    if bal is not None:
        rep.add("잔고", bal.available_balance > 0, f"{bal.asset} 가용 {bal.available_balance:,.2f}")
    mark = q("마크 가격", ex.mark_price)
    if mark is not None:
        rep.mark = float(mark)
        rep.add("마크 가격", float(mark) > 0, f"{float(mark):,.1f}")
    pos = q("포지션", ex.position)
    if pos is not None:
        rep.add("포지션", True, f"{pos.qty:g} BTC (0이 아니면 대조기가 T0 — 왕복 시험 불가)")
    oo = q("미체결 주문", ex.open_orders)
    if oo is not None:
        rep.add("미체결 주문", True, f"{len(oo)}건")
    oc = q("조건부 주문", ex.open_conditional_orders)
    if oc is not None:
        rep.add("조건부 주문", True, f"{len(oc)}건 (창구 {cfg.conditional_api.value}, K2)")
    return rep


# ---------------------------------------------------------------------------
# 왕복 시험(selftest --roundtrip) — 주문은 돌고 있는 워커가 한다(이 함수는 DB만 쓴다)
# ---------------------------------------------------------------------------


class SelftestRefused(RuntimeError):
    pass


def create_selftest_intent(conn: sqlite3.Connection, *, mark: float, now_ms: int) -> tuple[str, int]:
    """시험 신호(APPROVED, actor OPERATOR, spec SELFTEST) + QUEUED 의도를 한 트랜잭션으로. (signal_id, intent_id).

    거부(SelftestRefused): 노출 의도·QUEUED가 있음, 모든 하위 시스템에 진행 중 신호가 있음, 마크 가격 이상.
    ATR20 = 마크 × 1%(손절 거리 약 2%). 크기는 진짜 신호와 같은 규칙(plan_entry — R 자본 × r)."""
    if not (isinstance(mark, (int, float)) and mark > 0):
        raise SelftestRefused("마크 가격 이상")
    if queue.live_intent(conn) is not None:
        raise SelftestRefused("노출 중인 주문 의도가 있다(보유·처리 중) — 끝난 뒤에 시험")
    if queue.intents_in_states(conn, [S.QUEUED]):
        raise SelftestRefused("대기 중(QUEUED) 의도가 있다 — 처리된 뒤에 시험")
    n = next((k for k in (100, 55, 20) if db.active_signal_for_subsystem(conn, k) is None), None)
    if n is None:
        raise SelftestRefused("모든 하위 시스템에 진행 중 신호가 있다")
    atr = round(float(mark) * SELFTEST_ATR_FRAC, 1)
    sid = new_signal_id()
    Sg = SignalState
    with db.transaction(conn):
        ok = db.insert_signal(conn, signal_id=sid, mode=Mode.TESTNET, strategy_key="E0-L-ENS",
                              spec_version=SELFTEST_SPEC, subsystem_n=n, side=1, signal_day=utc_iso_ms(now_ms)[:10],
                              signal_close_ms=int(now_ms), decision_ms=int(now_ms), expires_ms=int(now_ms) + 600_000,
                              close=float(mark), entry_level=float(mark), exit_level=float(mark), atr20=atr,
                              now_ms=int(now_ms))
        if not ok:
            raise SelftestRefused("시험 신호를 만들 수 없다(같은 시각 신호 있음) — 잠시 뒤 다시")
        for src, dst, fields in (
                (Sg.NEW, Sg.CARD_SENT, {"card_sent_ms": int(now_ms)}),
                (Sg.CARD_SENT, Sg.CONFIRM_PENDING, {"confirm_requested_ms": int(now_ms),
                                                    "confirm_expires_ms": int(now_ms) + 60_000}),
                (Sg.CONFIRM_PENDING, Sg.APPROVED, {"approved_ms": int(now_ms), "approval_latency_ms": 0})):
            if not db.transition_signal(conn, sid, src, dst, now_ms=int(now_ms), actor="OPERATOR",
                                        reason="selftest", fields=fields):
                raise SelftestRefused("시험 신호 전이 실패")
        db.audit(conn, ts_ms=int(now_ms), actor="OPERATOR", event=AuditEvent.COMMAND, entity_type="signal",
                 entity_id=sid, payload={"command": "orders_selftest_roundtrip", "subsystem_n": n})
        iid = queue.enqueue(conn, signal_id=sid, now_ms=int(now_ms))
    if iid is None:
        raise SelftestRefused("큐에 넣지 못했다")
    return sid, int(iid)


@dataclass
class RoundtripResult:
    ok: bool
    signal_id: str
    intent_id: int
    final_state: str
    lines: list[str] = field(default_factory=list)


def run_roundtrip(conn: sqlite3.Connection, *, mark: float, clock: Clock, wait_step: Callable[[], None],
                  timeout_s: float = SELFTEST_TIMEOUT_S, echo: Callable[[str], None] = print,
                  control: ControlState | None = None) -> RoundtripResult:
    """시험 의도를 넣고 워커가 STOP_VERIFIED까지 가면 즉시 추세 청산을 요청해 CLOSED까지 지켜본다.

    wait_step: 한 번 기다리기(실제 = 1초 sleep, 시험 = 워커 run_once). 워커의 심장 박동이 오래됐으면 시작하지 않는다."""
    now = _now_ms(clock)
    if control is not None:
        if control.manual_halt:
            raise SelftestRefused(f"제어 파일 수동 정지 중({control.error or 'halt = true'})")
        active = queue.active_halt_ids(conn, control.released)
        if active:
            raise SelftestRefused(f"풀리지 않은 킬 스위치 T0 {active} — 원인 확인·해제 뒤 시험")
    hb = queue.get_runtime(conn, "b_heartbeat_ms")
    if hb is None or now - int(hb["value"]) > SELFTEST_HEARTBEAT_MAX_AGE_MS:
        raise SelftestRefused("주문 워커가 돌고 있지 않다(심장 박동 없음) — `docker compose --profile testnet up -d` 먼저")
    sid, iid = create_selftest_intent(conn, mark=mark, now_ms=now)
    echo(f"시험 신호 {sid} · 의도 #{iid} 큐에 넣음 — 워커 처리 대기")
    res = RoundtripResult(False, sid, iid, S.QUEUED.value)
    deadline = time.monotonic() + float(timeout_s)
    t_clock_start = now
    exit_requested = False
    last = None

    def expired() -> bool:
        return time.monotonic() > deadline or _now_ms(clock) - t_clock_start > timeout_s * 1000

    while not expired():
        row = queue.get_intent(conn, iid)
        st = IntentState(row["state"])
        if st.value != last:
            last = st.value
            line = f"의도 상태: {st.value}" + (f" ({row['state_reason']})" if row["state_reason"] else "")
            res.lines.append(line)
            echo(line)
        if st is S.STOP_VERIFIED and not exit_requested:
            echo(f"진입 체결 {float(row['filled_qty']):g} BTC @ {float(row['avg_fill_price']):,.1f} · 손절"
                 f" {float(row['stop_price']):,.1f} 확인(무방비 {row['unprotected_ms']} ms) → 추세 청산 요청")
            exit_requested = queue.request_exit(conn, sid, exit_signal_close_ms=_now_ms(clock),
                                                exit_due_ms=_now_ms(clock), now_ms=_now_ms(clock))
        if st in INTENT_TERMINAL or st is S.HALTED:
            break
        wait_step()
    row = queue.get_intent(conn, iid)
    res.final_state = row["state"]
    posts: dict[str, int] = {}
    for ev in queue.events_for(conn, iid):
        if ev["kind"] == "REQUEST" and ev["client_id"]:
            posts[ev["client_id"]] = posts.get(ev["client_id"], 0) + 1
    res.lines.append("주문 요청: " + (", ".join(f"{k}×{v}" for k, v in sorted(posts.items())) or "없음"))
    res.ok = row["state"] == S.CLOSED.value and row["exit_reason"] == "trend"
    tail = (f"결과: {row['state']} exit_reason={row['exit_reason']} halt_id={row['halt_id']}"
            + ("" if res.ok else " — 실패. `docker compose --profile testnet logs orders`·order_events 확인(RUNBOOK §T7)"))
    res.lines.append(tail)
    echo(res.lines[-2])
    echo(tail)
    return res


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def _err(msg: str) -> None:
    print(f"오류: {msg}", file=sys.stderr)


def _install_excepthook() -> None:
    """잡히지 않은 예외: 종류만 쓴다(메시지·트레이스백에 서명·경로·응답이 섞일 수 있다)."""

    def _hook(exc_type, exc, tb) -> None:
        sys.stderr.write(f"처리되지 않은 예외: {getattr(exc_type, '__name__', '?')}\n")

    sys.excepthook = _hook
    threading.excepthook = lambda args: _hook(args.exc_type, args.exc_value, args.exc_traceback)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m bot.orders.worker",
                                description="TESTNET 주문 프로세스(B) — 바이낸스 모의 환경 전용")
    p.add_argument("--config", required=True, help="설정 TOML 경로(mode = \"testnet\", [orders] 절)")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = p.add_subparsers(dest="command")
    sub.add_parser("run", help="주문 루프(기본)")
    sub.add_parser("status", help="DB 상태만 출력(거래소 호출·키 읽기 없음): 보유 의도, T0와 해제 여부, 대조·심장 박동")
    st = sub.add_parser("selftest", help="거래소 점검(조회만). --roundtrip이면 왕복 주문 시험")
    st.add_argument("--roundtrip", action="store_true",
                    help="점검 통과 뒤 시험 신호 1건으로 진입·손절·청산 왕복(돌고 있는 워커가 처리)")
    st.add_argument("--timeout-s", type=float, default=SELFTEST_TIMEOUT_S)
    return p.parse_args(argv)


def status_text(conn: sqlite3.Connection, control: ControlState, *, now_ms: int) -> str:
    """서버 운영자용 상태(RUNBOOK 테스트넷 §T6): T0 해제 판정은 제어 파일의 released만 쓴다."""
    lines = [f"제어 파일: {'수동 정지' if control.manual_halt else '정상'}"
             + (f" (문제: {control.error})" if control.error else "") + f" · {control.ref}"]
    for key in ("b_heartbeat_ms", "last_reconcile_ms", "last_reconcile_ok", "reconcile_fail_count", "clock_offset_ms"):
        r = queue.get_runtime(conn, key)
        val = "-" if r is None else r["value"]
        if r is not None and key.endswith("_ms") and key != "clock_offset_ms":
            val = f"{utc_iso_ms(int(r['value']))} ({max(0, now_ms - int(r['value'])) // 1000}초 전)"
        lines.append(f"{key}: {val}")
    live = queue.live_intent(conn)
    lines.append("노출 의도: 없음" if live is None else
                 f"노출 의도 #{int(live['intent_id'])} 신호 {live['signal_id']} {live['state']}"
                 f" 체결 {live['filled_qty']} @ {live['avg_fill_price']} 손절 {live['stop_price']}")
    # 해제 표시: 제어 파일에 있고, at을 적었다면 T0 시각보다 이르지 않을 때(B의 '처음 본 시각' 규칙은 B 로그로 확인 — R-8)
    at = dict(control.release_at)
    ts = {int(h["halt_id"]): int(h["ts_ms"]) for h in queue.halts(conn)}
    released = {hid for hid in control.released
                if hid in ts and (at.get(hid) is None or at[hid] >= ts[hid] - RELEASE_AT_TOLERANCE_MS)}
    active = set(queue.active_halt_ids(conn, released))
    for h in queue.halts(conn)[-20:]:
        hid = int(h["halt_id"])
        lines.append(f"T0 #{hid} {utc_iso_ms(int(h['ts_ms']))} {h['reason']} 의도 {h['intent_id']} — "
                     + ("**정지 중**(제어 파일에 [[release]] halt_id = %d, at = 지금 필요)" % hid if hid in active
                        else "해제됨"))
    if not active:
        lines.append("풀리지 않은 T0 없음")
    return "\n".join(lines)


def _check_no_a_secrets(cfg) -> str | None:
    """B에 A의 비밀(텔레그램 토큰·Claude 키·핑 URL)이 보이면 compose 설정 실수 — 시작 거부(분리 원칙)."""
    for path in (cfg.telegram.bot_token_file, cfg.claude.api_key_file, cfg.health.ping_url_file):
        if path and os.path.lexists(path):
            return path
    return None


def _acquire_single_instance_lock(db_path: str | os.PathLike[str]) -> int | None:
    """DB 옆 '<db>.orders.lock'에 배타 flock(비차단). 잡으면 fd, 이미 잡혀 있으면 None(F6: B는 하나만).
    메모리 DB(시험)는 잠그지 않는다(-1)."""
    if str(db_path) == ":memory:":
        return -1
    path = f"{db_path}.orders.lock"
    Path(path).parent.mkdir(parents=True, exist_ok=True)     # DB 연결보다 먼저 잡는다(db.connect와 같은 폴더 생성)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def main(argv: list[str] | None = None, *, environ=None, clock: Clock | None = None,
         client_factory: Callable[[OrdersConfig, Clock], Any] | None = None,
         stop: threading.Event | None = None) -> int:
    """종료 코드: 0 정상, 1 오류·selftest 실패, 2 설정·비밀 오류, 3 DB 모드 불일치·변조.
    client_factory·clock·stop은 시험용 주입(기본 = 실제 클라이언트·시스템 시계·SIGTERM)."""
    from bot.config import ConfigError, check_env_no_secrets, load_config, setup_logging

    os.umask(0o077)
    args = parse_args(argv)
    bad_env = check_env_no_secrets(environ)
    if bad_env:
        _err("비밀로 보이는 환경 변수가 있어 시작하지 않는다(값은 보지 않음): " + ", ".join(bad_env))
        return EXIT_CONFIG
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        _err(str(exc))
        return EXIT_CONFIG
    if cfg.mode != Mode.TESTNET or cfg.orders is None:
        _err("주문 프로세스는 mode = \"testnet\" 설정에서만 돈다(live는 없음)")
        return EXIT_CONFIG
    visible = _check_no_a_secrets(cfg)
    command = args.command or "run"
    if visible is not None:
        _err(f"주문 프로세스(B)에 A 프로세스 비밀 파일이 보인다(compose 분리 확인): {visible}")
        if command != "run":
            return EXIT_CONFIG
    ocfg = cfg.orders
    handler = setup_logging(None, level=getattr(logging, args.log_level))
    prev_hooks = (sys.excepthook, threading.excepthook)
    _install_excepthook()
    clock = clock or SystemClock()
    ex = None
    conn = None
    held_locks: list[int] = []

    def refuse(code: int, why: str) -> int:
        """시작 거부(V-1): recover() 전에 멈추더라도 손절 없는 포지션을 남기지 않는다 — DB 없이 보호한 뒤 종료.
        다른 B가 잠금을 쥐고 있으면(그 B가 보호 중) 아무것도 하지 않는다."""
        if command != "run" or ex is None:
            return code
        if not held_locks:
            fd = _acquire_single_instance_lock(cfg.db_path)
            if fd is None:
                return code
            held_locks.append(fd)
        try:
            res = protect_without_db(ex, ocfg, clock, base_url=str(getattr(ex, "base_url", "")),
                                     sleep_ms=_clock_sleeper(clock))
        except Exception as exc:  # noqa: BLE001 — 종류만
            res = f"error:{type(exc).__name__}"
        log.error("시작 거부(%s) 전 DB 없는 보호: %s", why, res)
        _err(f"시작 거부({why}) — 거래소 포지션 보호 결과: {res}. "
             + ("거래소 웹에서 포지션·손절을 즉시 확인할 것(RUNBOOK 테스트넷 §T8)" if res not in ("flat", "flattened")
                else "포지션 0 확인"))
        if conn is not None:
            try:
                queue.notify(conn, f"[TESTNET] P1 주문 프로세스 시작 거부({why}) — DB 없는 보호 결과: {res}. "
                                   "서버에서 원인을 고치고 거래소 웹에서 포지션·손절 확인(RUNBOOK §T8)",
                             now_ms=_now_ms(clock), kind="alert")
            except Exception:  # noqa: BLE001 — DB가 문제라서 거부하는 중일 수 있다
                pass
        return code

    try:
        if command == "status":
            try:
                conn = db.connect(cfg.db_path, mode=Mode.TESTNET, now_ms=_now_ms(clock))
            except db.DbError as exc:
                _err(f"DB: {exc}")
                return EXIT_DB
            print(status_text(conn, load_control(ocfg.control_file), now_ms=_now_ms(clock)))
            return EXIT_OK
        try:
            if client_factory is not None:
                ex = client_factory(ocfg, clock)
            else:
                from bot.orders.binance_client import BinanceFuturesClient

                ex = BinanceFuturesClient.from_files(ocfg, clock=clock)
        except (ConfigError, ValueError) as exc:
            _err(f"거래소 키·클라이언트: {exc}")
            return EXIT_CONFIG
        if visible is not None:
            return refuse(EXIT_CONFIG, "a_secrets_visible")
        if command == "run":
            # 잠금을 DB 연결보다 먼저: DB 문제로 거부할 때도 두 번째 B가 보호(청산)에 끼어들지 않게
            lock_fd = _acquire_single_instance_lock(cfg.db_path)
            if lock_fd is None:
                _err("다른 주문 프로세스(B)가 이미 돌고 있다(잠금 파일) — 두 번째 B는 진입 중인 의도를 망가뜨린다. 시작하지 않는다")
                return EXIT_CONFIG
            held_locks.append(lock_fd)
        try:
            conn = db.connect(cfg.db_path, mode=Mode.TESTNET, now_ms=_now_ms(clock))
        except db.DbError as exc:
            _err(f"DB: {exc}")
            return refuse(EXIT_DB, "db_connect")
        if command == "selftest":
            rep = selftest_checks(ex, ocfg, clock)
            print(rep.text())
            if not rep.ok:
                print("점검 실패 — RUNBOOK 테스트넷 §T4 표를 보고 거래소 웹 설정을 고친 뒤 다시")
                return EXIT_ERROR
            print("점검 통과(조회만, 주문 없음)")
            if not args.roundtrip:
                return EXIT_OK
            try:
                rt = run_roundtrip(conn, mark=float(rep.mark or 0.0), clock=clock, wait_step=lambda: time.sleep(1.0),
                                   timeout_s=float(args.timeout_s), control=load_control(ocfg.control_file))
            except SelftestRefused as exc:
                _err(f"왕복 시험 시작 안 함: {exc}")
                return EXIT_ERROR
            return EXIT_OK if rt.ok else EXIT_ERROR
        ledger = Ledger(ocfg.ledger_file)
        if ledger.error is not None:
            log.error("B 전용 원장(%s) 문제: %s — 신규 진입 차단 상태로 시작(보유 보호는 계속)",
                      ocfg.ledger_file, ledger.error)
        stop = stop or threading.Event()
        try:
            worker = Worker(conn, ocfg, ex, clock, heartbeat_path=HEARTBEAT_PATH, ledger=ledger)
            worker.startup()
        except db.DbError as exc:
            _err(f"DB: {exc}")
            return refuse(EXIT_DB, "startup_db")
        except Exception as exc:  # noqa: BLE001 — 시작 복구가 죽어도 포지션은 보호하고 종료
            log.error("시작 복구 실패: %s", type(exc).__name__)
            _err(f"시작 복구 실패({type(exc).__name__})")
            return refuse(EXIT_ERROR, f"startup:{type(exc).__name__}")
        prev_handlers = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                prev_handlers[sig] = signal.signal(sig, lambda *_: stop.set())
            except (ValueError, OSError):  # pragma: no cover - 메인 스레드가 아닐 때
                pass
        try:
            worker.run_forever(stop)
        finally:
            for sig, h in prev_handlers.items():
                signal.signal(sig, h)
        log.info("주문 프로세스 정지(신호)")
        return EXIT_OK
    except db.DbError as exc:
        _err(f"DB: {exc}")
        return EXIT_DB
    except Exception as exc:  # noqa: BLE001 — 마지막 방어선: 종류만
        log.error("처리되지 않은 오류로 종료: %s", type(exc).__name__)
        _err(f"처리되지 않은 오류로 종료({type(exc).__name__}) — compose가 재시작하면 recover가 거래소 사실로 복구")
        return EXIT_ERROR
    finally:
        for fd in held_locks:
            try:
                os.close(fd)                     # 잠금 해제
            except OSError:
                pass
        if ex is not None and callable(getattr(ex, "close", None)):
            ex.close()
        if conn is not None:
            conn.close()
        logging.getLogger().removeHandler(handler)
        sys.excepthook, threading.excepthook = prev_hooks


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
