"""대조기(C13) — 게이트웨이 담당 (DESIGN §8, §9).

거래소가 진실의 원천이다. 거래소 포지션·미체결·조건부 주문 vs DB(order_intents)를 주기(≤30초)로 대조하고,
불일치는 §9 표대로 처리한다(손절 누락 → 청산 + T0, 모르는 주문 → 일반은 취소 + T0, 모르는 포지션 → T0 + 경보,
연속 3회 조회 실패 → T0). 재시작 복구(recover)는 새 의도를 가져가기 전에 반드시 한 번 돈다.
청산·취소는 반드시 Gateway 메서드를 거친다(방화벽 통과).

- 같은 사유·의도의 T0는 풀리기 전까지 한 번만 건다(``Gateway.halt_once``) — 정지 중 매 대조마다 경보하지 않는다(§7.2).
- 대조 결과는 ``order_runtime``(last_reconcile_ms·last_reconcile_ok·reconcile_fail_count·clock_offset_ms)에 남는다.

수정 담당(검토 지적 반영)
- 포지션이 0이 아니면 어떤 보호 손절도 취소하지 않는다(SEC-01: A가 의도를 CLOSED로 위조해 B가 살아 있는 손절을 '고아'로
  지우게 하는 공격). 끝난 의도의 손절이 포지션과 함께 남아 있으면 그대로 두고 T0.
- 노출 의도 없이 롱 포지션: 최근 NOT_FILLED 의도의 e1이 실제로 체결됐는지 조회해, 우리 것이면 청산(안 되면 손절) + T0(F5).
- 공개 마크 가격 조회 하나가 실패해도 대조·복구를 멈추지 않는다(mark=None, F9). 조회가 통째로 실패해도 노출 의도의
  손절 확인·보호는 자체 조회로 시도한다.
- HALTED 보유: 손절이 없으면 다시 걸고(사람 판단 대기), 안 되면 새 청산 주기(F3b·F3c).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from bot.orders import queue
from bot.orders.control import ControlState
from bot.orders.gateway import Gateway, halt_reason_for, stop_mismatches
from bot.orders.types import (
    CONDITIONAL_FIRED_STATUSES,
    INTENT_LIVE,
    INTENT_TERMINAL,
    QTY_STEP,
    RECONCILE_FAILS_TO_HALT,
    ExchangeClient,
    ExchangeError,
    ExchangeSnapshot,
    HaltReason,
    IdPurpose,
    IntentState,
    Side,
    make_client_id,
    parse_client_id,
)
from bot.types import Clock, NS_PER_MS

S = IntentState
_OWN_REDUCE_PURPOSES = frozenset({IdPurpose.EXIT1, IdPurpose.EXIT2, IdPurpose.EXIT3,
                                  IdPurpose.FLAT1, IdPurpose.FLAT2, IdPurpose.FLAT3})


@dataclass
class ReconcileReport:
    ok: bool
    snapshot: ExchangeSnapshot | None = None
    issues: list[str] = field(default_factory=list)      # 불일치 코드(예: 'stop_missing', 'unknown_order')
    actions: list[str] = field(default_factory=list)     # 한 조치(예: 'flatten', 'cancel:<id>', 'close:stop')
    halt_ids: list[int] = field(default_factory=list)


def take_snapshot(ex: ExchangeClient, clock: Clock, *, with_balance: bool = False) -> ExchangeSnapshot:
    """서버 시각·포지션·미체결·조건부 주문(·잔고)을 한 번에 조회. 실패는 ExchangeError 그대로."""
    local = int(clock.now_ns()) // NS_PER_MS
    server = int(ex.server_time_ms())
    pos = ex.position()
    oo = tuple(ex.open_orders())
    oc = tuple(ex.open_conditional_orders())
    try:
        mark: float | None = float(ex.mark_price())
    except ExchangeError:
        mark = None                                   # 공개 시세 하나 때문에 대조 전체를 멈추지 않는다(F9)
    bal = ex.balance() if with_balance else None
    return ExchangeSnapshot(server_time_ms=server, local_time_ms=local, position=pos, open_orders=oo,
                            open_conditionals=oc, mark_price=mark, balance=bal)


def _runtime_int(conn: sqlite3.Connection, key: str) -> int:
    r = queue.get_runtime(conn, key)
    try:
        return int(r["value"]) if r is not None else 0
    except (TypeError, ValueError):
        return 0


def _note(gw: Gateway, report: ReconcileReport, issue: str, detail: dict | None = None,
          intent_id: int | None = None) -> None:
    report.issues.append(issue)
    gw._event(intent_id, "RECONCILE", payload={"issue": issue, **(detail or {})})


def _halt(gw: Gateway, report: ReconcileReport, reason: HaltReason, *, intent_id: int | None,
          detail: dict | None = None) -> int:
    hid = gw.halt_once(reason, intent_id=intent_id, detail=detail)
    if hid not in report.halt_ids:
        report.halt_ids.append(hid)
    return hid


def _collect_halts(gw: Gateway, report: ReconcileReport) -> None:
    for h in gw.halt_ids:
        if h not in report.halt_ids:
            report.halt_ids.append(h)
    gw.halt_ids = []


def _check_foreign(conn: sqlite3.Connection, gw: Gateway, snap: ExchangeSnapshot, live: sqlite3.Row | None,
                   report: ReconcileReport) -> None:
    """§9: sig-가 아닌 주문·다른 신호의 주문. 일반 주문은 취소 + T0, 줄이기 전용 조건부 매도는 두고 T0,
    끝난 의도의 우리 sl(고아)은 조용히 취소."""
    live_sid = live["signal_id"] if live is not None else None
    live_id = int(live["intent_id"]) if live is not None else None
    for o in snap.open_orders:
        p = parse_client_id(o.client_id)
        ours = p is not None and p.signal_id == live_sid and p.purpose in _OWN_REDUCE_PURPOSES \
            and o.side is Side.SELL and o.reduce_only
        if ours:
            continue
        _note(gw, report, "unknown_order", {"client_id": o.client_id, "conditional": False}, live_id)
        if gw.cancel_foreign(o.client_id, conditional=False, intent_id=live_id):
            report.actions.append(f"cancel:{o.client_id}")
        _halt(gw, report, HaltReason.UNKNOWN_ORDER, intent_id=None,
              detail={"client_id": o.client_id, "conditional": False})
    for c in snap.open_conditionals:
        p = parse_client_id(c.client_algo_id)
        if p is not None and p.signal_id == live_sid and p.purpose is IdPurpose.STOP:
            continue                                 # 보유 의도의 손절(아래에서 대조)
        if p is not None and p.purpose is IdPurpose.STOP:
            other = queue.intent_for_signal(conn, p.signal_id)
            if other is not None and IntentState(other["state"]) in INTENT_TERMINAL:
                if float(snap.position.qty) == 0.0:
                    # 끝난 의도의 남은 손절(고아): 포지션 0이면 무해하지만 정리한다 — 경보 없음, 기록만
                    _note(gw, report, "orphan_stop", {"client_id": c.client_algo_id}, int(other["intent_id"]))
                    if gw.cancel_foreign(c.client_algo_id, conditional=True, intent_id=int(other["intent_id"])):
                        report.actions.append(f"cancel_orphan:{c.client_algo_id}")
                    continue
                # 포지션이 있는데 '끝난' 의도의 손절이 살아 있다 → DB가 거래소와 다르다(A의 위조 가능). 보호를 지우지 않는다(SEC-01)
                _note(gw, report, "terminal_intent_stop_with_position",
                      {"client_id": c.client_algo_id, "intent_state": other["state"],
                       "position_qty": float(snap.position.qty)}, int(other["intent_id"]))
                report.actions.append(f"keep_stop:{c.client_algo_id}")
                _halt(gw, report, HaltReason.POSITION_MISMATCH, intent_id=int(other["intent_id"]),
                      detail={"why": "terminal_intent_stop_with_position", "client_id": c.client_algo_id,
                              "intent_state": other["state"], "position_qty": float(snap.position.qty)})
                continue
        _note(gw, report, "unknown_order", {"client_id": c.client_algo_id, "conditional": True}, live_id)
        reduce_only_sell = c.side is Side.SELL and (c.close_position or c.reduce_only)
        if not reduce_only_sell:
            if gw.cancel_foreign(c.client_algo_id, conditional=True, intent_id=live_id):
                report.actions.append(f"cancel:{c.client_algo_id}")
        _halt(gw, report, HaltReason.UNKNOWN_ORDER, intent_id=None,
              detail={"client_id": c.client_algo_id, "conditional": True, "kept": reduce_only_sell})


def _check_live(conn: sqlite3.Connection, gw: Gateway, snap: ExchangeSnapshot, row: sqlite3.Row,
                control: ControlState, report: ReconcileReport, *, restart: bool) -> None:
    iid = int(row["intent_id"])
    st = IntentState(row["state"])
    pos_qty = float(snap.position.qty)
    sl = make_client_id(row["signal_id"], IdPurpose.STOP)

    if st is S.SUBMITTING:
        if row["entry_sent_ms"] is None:
            # 아무것도 보내지 않았다(선배치 손절만 있을 수 있음) → 취소 → REJECTED
            gw.cancel_own_stop(row)
            queue.transition(conn, iid, S.SUBMITTING, S.REJECTED, now_ms=gw.now_ms(),
                             reason="restart_before_send")
            report.actions.append("reject:restart_before_send")
            return
        new = gw.resolve_entry(row)
        report.actions.append(f"resolve_entry:{new.value}")
        if new in (S.ENTRY_FILLED, S.STOP_PLACED):
            new = gw.ensure_stop(gw._row(iid), restart=True)
            report.actions.append(f"restart_stop_check:{new.value}")
        return

    if st in (S.ENTRY_FILLED, S.STOP_PLACED):
        # 손절이 확인되지 않은 보유: 대조 통과면 STOP_VERIFIED, 아니면 청산 + T0 (O-6)
        new = gw.ensure_stop(row, restart=True)
        report.actions.append(f"restart_stop_check:{new.value}")
        if new is S.FAILED_FLATTENED:
            report.issues.append("restart_unprotected")
        return

    if st is S.EXITING:
        if pos_qty > 0:
            c = next((x for x in snap.open_conditionals if x.client_algo_id == sl), None)
            if stop_mismatches(c, client_algo_id=sl, stop_price=row["stop_price"]):
                _note(gw, report, "stop_missing", {"state": st.value}, iid)
        new = gw.run_trend_exit(row)
        report.actions.append(f"trend_exit:{new.value}")
        return

    if st is S.HALTED:
        halt_released = row["halt_id"] is not None and int(row["halt_id"]) in gw.released
        if pos_qty == 0.0:
            if halt_released:
                # 사람이 서버에서 처리(제어 파일 해제)한 뒤: 거래소 사실(포지션 0)을 기록
                gw.cancel_own_stop(row)
                gw.transition(row, S.FAILED_FLATTENED, reason="halt_resolved_flat",
                              fields={"exit_reason": "flatten" if row["flatten_attempts"] else "external",
                                      "closed_ms": gw.now_ms()}, expected=S.HALTED)
                report.actions.append("close:halt_resolved")
            return
        if pos_qty < 0:
            _note(gw, report, "position_mismatch", {"position_qty": pos_qty}, iid)
            _halt(gw, report, HaltReason.POSITION_MISMATCH, intent_id=iid, detail={"position_qty": pos_qty})
            return
        c = next((x for x in snap.open_conditionals if x.client_algo_id == sl), None)
        stop_price = row["stop_price"]
        if stop_price is not None and not stop_mismatches(c, client_algo_id=sl, stop_price=stop_price):
            return                                    # 손절이 보호 중 — 사람 판단을 기다린다
        _note(gw, report, "stop_missing", {"state": st.value}, iid)
        # 손절을 다시 걸고(사람 판단 대기), 안 되면 새 청산 주기 — 같은 사유 T0는 반복하지 않는다(F3a·F3b·F3c)
        new = gw.secure_halted(row)
        report.actions.append(f"secure_halted:{new.value}")
        return

    if st is S.STOP_VERIFIED:
        if pos_qty == 0.0:
            # §4.7 손절 발동 감지
            fired = False
            try:
                one = gw._x(iid, "get_conditional", sl, client_id=sl, log_query=True)
                fired = one is not None and one.status in CONDITIONAL_FIRED_STATUSES
            except ExchangeError:
                _note(gw, report, "stop_status_unavailable", None, iid)
                return                                # 다음 대조에서 다시(조회 불가 상태로 결론 내지 않는다)
            new = gw._closed_without_us(row, sl_fired=fired)
            report.actions.append("close:stop" if fired else "close:external")
            if not fired:
                report.issues.append("position_vanished")
            return
        if pos_qty < 0:
            _note(gw, report, "position_mismatch", {"position_qty": pos_qty}, iid)
            _halt(gw, report, HaltReason.POSITION_MISMATCH, intent_id=iid, detail={"position_qty": pos_qty})
            return
        filled = float(row["filled_qty"])
        if abs(pos_qty - filled) > QTY_STEP * 1.0001:
            # closePosition 손절이 전체를 덮으므로 청산은 손절 누락일 때만
            _note(gw, report, "position_mismatch", {"position_qty": pos_qty, "filled_qty": filled}, iid)
            _halt(gw, report, HaltReason.POSITION_MISMATCH, intent_id=iid,
                  detail={"position_qty": pos_qty, "filled_qty": filled})
        c = next((x for x in snap.open_conditionals if x.client_algo_id == sl), None)
        mism = stop_mismatches(c, client_algo_id=sl, stop_price=row["stop_price"])
        if mism:
            _note(gw, report, "stop_missing", {"mismatch": mism}, iid)
            new = gw.flatten(row, reason=HaltReason.STOP_MISSING, detail={"stop_mismatch": mism})
            report.actions.append(f"flatten:{new.value}")
        return


ORPHAN_LOOKBACK_MS = 24 * 60 * 60 * 1000
ORPHAN_MAX_INTENTS = 3


def _find_orphan_fill(conn: sqlite3.Connection, gw: Gateway):
    """최근 NOT_FILLED 의도 중 e1이 실제로 체결된 것(늦게 보인 체결). (row, OrderInfo) 또는 None."""
    rows = conn.execute(
        "SELECT * FROM order_intents WHERE state = 'NOT_FILLED' AND entry_sent_ms IS NOT NULL AND entry_sent_ms >= ?"
        " ORDER BY intent_id DESC LIMIT ?", (gw.now_ms() - ORPHAN_LOOKBACK_MS, ORPHAN_MAX_INTENTS)).fetchall()
    for row in rows:
        e1 = row["entry_client_id"] or make_client_id(row["signal_id"], IdPurpose.ENTRY)
        try:
            o = gw._x(int(row["intent_id"]), "get_order", e1, client_id=e1, log_query=True)
        except ExchangeError:
            continue
        if o is not None and float(o.executed_qty) > 0:
            return row, o
    return None


def _protect_without_snapshot(gw: Gateway, live: sqlite3.Row) -> list[str]:
    """묶음 조회 실패 중에도 노출 의도의 보호를 시도(각 게이트웨이 함수는 자체 조회로 판단)."""
    st = IntentState(live["state"])
    iid = int(live["intent_id"])
    out: list[str] = []
    if st is S.SUBMITTING and live["entry_sent_ms"] is not None:
        new = gw.resolve_entry(live)
        out.append(f"resolve_entry:{new.value}")
        if new in (S.ENTRY_FILLED, S.STOP_PLACED):
            new = gw.ensure_stop(gw._row(iid), restart=True)
            out.append(f"restart_stop_check:{new.value}")
    elif st in (S.ENTRY_FILLED, S.STOP_PLACED):
        new = gw.ensure_stop(live, restart=True)
        out.append(f"restart_stop_check:{new.value}")
    elif st is S.HALTED:
        new = gw.secure_halted(live)
        out.append(f"secure_halted:{new.value}")
    elif st is S.STOP_VERIFIED:
        new = gw.verify_held_stop(live)
        if new is not S.STOP_VERIFIED:
            out.append(f"verify_held_stop:{new.value}")
    return out


def reconcile_once(conn: sqlite3.Connection, gw: Gateway, ex: ExchangeClient, clock: Clock,
                   control: ControlState, *, restart: bool = False) -> ReconcileReport:
    """거래소 ↔ DB 대조 한 번(§9)."""
    gw.set_control(control)
    gw.halt_ids = []
    now = gw.now_ms()
    try:
        gw.rate_wait()
        snap = take_snapshot(ex, clock)
    except ExchangeError as exc:
        gw.note_exchange_error(exc)
        fails = _runtime_int(conn, "reconcile_fail_count") + 1
        queue.set_runtime(conn, "reconcile_fail_count", fails, now_ms=now)
        queue.set_runtime(conn, "last_reconcile_ok", 0, now_ms=now)
        report = ReconcileReport(ok=False, issues=[f"snapshot_failed:{exc.kind.value}"])
        gw._event(None, "RECONCILE", payload={"issue": "snapshot_failed", "kind": exc.kind.value, "fails": fails})
        if fails >= RECONCILE_FAILS_TO_HALT:
            # 보유 중이어도 청산은 시도하지 않는다(조회도 안 되는 상태의 주문은 결과를 알 수 없다 — 손절은 거래소에 있다)
            _halt(gw, report, HaltReason.RECONCILE_UNAVAILABLE, intent_id=None,
                  detail={"fails": fails, "kind": exc.kind.value})
        elif exc.halts:
            _halt(gw, report, halt_reason_for(exc), intent_id=None, detail={"kind": exc.kind.value})
        # 묶음 조회가 안 돼도 노출 의도의 보호는 자체 조회로 시도한다(F9)
        live = queue.live_intent(conn)
        if live is not None:
            report.actions.extend(_protect_without_snapshot(gw, live))
        _collect_halts(gw, report)
        return report

    queue.set_runtime(conn, "reconcile_fail_count", 0, now_ms=now)
    queue.set_runtime(conn, "clock_offset_ms", snap.clock_offset_ms, now_ms=now)
    report = ReconcileReport(ok=True, snapshot=snap)

    if abs(snap.clock_offset_ms) > gw.cfg.max_clock_skew_ms:
        _note(gw, report, "clock_skew", {"offset_ms": snap.clock_offset_ms})
        _halt(gw, report, HaltReason.CLOCK_SKEW, intent_id=None, detail={"offset_ms": snap.clock_offset_ms})

    live = queue.live_intent(conn)
    _check_foreign(conn, gw, snap, live, report)
    if live is None:
        if float(snap.position.qty) != 0.0:
            orphan = _find_orphan_fill(conn, gw) if float(snap.position.qty) > 0 else None
            if orphan is not None:
                # 우리 진입(e1)이 늦게 체결된 것으로 확인됨 → 청산(안 되면 손절) + T0 (F5)
                row, o = orphan
                _note(gw, report, "late_entry_fill", {"position_qty": float(snap.position.qty),
                                                      "e1_qty": float(o.executed_qty)}, int(row["intent_id"]))
                ok = gw.handle_orphan_fill(row, avg=float(o.avg_price) if o.avg_price else None,
                                           why="late_entry_fill")
                report.actions.append(f"orphan_fill:{'secured' if ok else 'failed'}")
            else:
                # O-11: 모르는 포지션은 청산하지 않고 T0 + 경보(사람이 거래소 웹에서 확인·정리)
                _note(gw, report, "unknown_position", {"position_qty": float(snap.position.qty)})
                _halt(gw, report, HaltReason.UNKNOWN_POSITION, intent_id=None,
                      detail={"position_qty": float(snap.position.qty)})
    else:
        _check_live(conn, gw, snap, live, control, report, restart=restart)

    _collect_halts(gw, report)
    report.ok = not report.issues
    done = gw.now_ms()
    queue.set_runtime(conn, "last_reconcile_ms", done, now_ms=done)
    queue.set_runtime(conn, "last_reconcile_ok", 1 if report.ok else 0, now_ms=done)
    return report


def recover(conn: sqlite3.Connection, gw: Gateway, ex: ExchangeClient, clock: Clock,
            control: ControlState) -> ReconcileReport:
    """재시작 복구(DESIGN §8 표). 새 의도를 가져가기 전에 반드시 한 번."""
    gw.set_control(control)
    gw.halt_ids = []
    report = ReconcileReport(ok=True)
    now = gw.now_ms()
    queue.set_runtime(conn, "b_started_ms", now, now_ms=now)

    # 1) 시계(오차 > 한도면 T0, 복구는 조회만 계속)
    try:
        gw.rate_wait()
        offset = int(ex.server_time_ms()) - gw.now_ms()
        gw.clock_offset_ms = offset
        if abs(offset) > gw.cfg.max_clock_skew_ms:
            report.issues.append("clock_skew")
            _halt(gw, report, HaltReason.CLOCK_SKEW, intent_id=None, detail={"offset_ms": offset, "at": "recover"})
    except ExchangeError as exc:
        report.issues.append(f"time_unavailable:{exc.kind.value}")

    # 2) 노출 가능 의도마다 거래소 사실로 판정(SUBMITTING·ENTRY_FILLED·STOP_PLACED·EXITING은 여기서 처리)
    for row in queue.intents_in_states(conn, INTENT_LIVE):
        st = IntentState(row["state"])
        if st in (S.STOP_VERIFIED, S.HALTED):
            continue                                  # 3)의 대조가 처리
        try:
            gw.rate_wait()
            snap = take_snapshot(ex, clock)
        except ExchangeError as exc:
            gw.note_exchange_error(exc)
            report.issues.append(f"snapshot_failed:{exc.kind.value}")
            # 조회가 안 돼도 결과 모름 절차·손절 확인은 자체 조회로 확정하거나 청산·HALTED로 끝낸다(F9: ENTRY_FILLED·
            # STOP_PLACED를 건너뛰면 손절 없는 포지션이 남는다)
            report.actions.extend(_protect_without_snapshot(gw, row))
            continue
        _check_live(conn, gw, snap, row, control, report, restart=True)
        if IntentState(gw._row(int(row["intent_id"]))["state"]) is S.FAILED_FLATTENED \
                and "restart_unprotected" not in report.issues and st is not S.EXITING:
            report.issues.append("restart_unprotected")

    # 4) 낡은 승인(재시작이 길었으면 낡은 승인으로 진입하지 않는다)
    n = gw.reject_stale_queued()
    if n:
        report.actions.append(f"reject_stale:{n}")

    # 3) 전체 대조(모르는 포지션·주문, 보유 의도의 손절)
    _collect_halts(gw, report)
    rec = reconcile_once(conn, gw, ex, clock, control, restart=True)
    report.snapshot = rec.snapshot
    report.issues.extend(rec.issues)
    report.actions.extend(rec.actions)
    for h in rec.halt_ids:
        if h not in report.halt_ids:
            report.halt_ids.append(h)
    _collect_halts(gw, report)
    report.ok = not report.issues and rec.ok

    # 5) 요약 알림
    live = queue.live_intent(conn)
    summary = (f"주문 프로세스(B) 재시작 복구: "
               f"{'이상 없음' if report.ok else '문제 ' + ', '.join(sorted(set(report.issues)))}"
               f"; 보유 의도 {'없음' if live is None else live['state']}"
               f"{'; 킬 스위치 T0 ' + ','.join(map(str, report.halt_ids)) if report.halt_ids else ''}")
    queue.notify(conn, summary, now_ms=gw.now_ms(), kind="info" if report.ok else "alert")
    return report
