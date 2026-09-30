"""적대적 장애 감사(chaos) — 검토자 전용 시험. 소스는 바꾸지 않는다.

가짜 거래소(FakeExchange) 장애 주입 + 워커(프로세스 B) 루프를 돌리며 '손절 없는 포지션이 거래소에 남아 있는 시간'을
**모든 거래소 호출 경계와 루프 틱마다** 표본으로 잰다(Monitor). 기준: DESIGN I2 — 체결 → 손절 확인 ≤ STOP_DEADLINE_MS(5초).

- ``xfail(strict=True)``인 시험 = 검토자가 찾은 결함(안전 불변식이 깨지는 것을 실행으로 확인). 고쳐지면 XPASS로 실패하므로
  그때 xfail 표시를 지우면 회귀 시험이 된다.
- 표시 없는 시험 = 공격했지만 버틴 경로(회귀 방지용).
- 수정 담당: F1·F3a·F3b·F3c·F4·F5·F6·F8·F9는 고쳐져 xfail을 지웠다(회귀 시험). F2는 '429 창 안에서는 어떤 호출도
  보내지 않는다(418로 번지지 않는다), 무방비는 Retry-After로 묶인다'로 기대를 바꿨다(I2 5초는 429가 손절 경로에 걸리면
  원리상 지킬 수 없다 — DESIGN §16 R-6). F7은 매 바퀴 손절 존재 조회를 더해 루프 주기로 묶였다.

실행: .venv/bin/python -m pytest bot/orders/tests/review_chaos_test.py -q -rxX
"""
from __future__ import annotations

import random
import sqlite3
from typing import Any

import pytest

from bot import db
from bot.orders import queue
from bot.orders import worker as W
from bot.orders.control import ControlState
from bot.orders.fake_exchange import FakeExchange, Fault, FaultKind
from bot.orders.tests.conftest import MARK, TEST_MODE, make_approved_intent, make_orders_config
from bot.orders.tests.test_gateway import EX_METHODS, Crash
from bot.orders.types import (
    CONDITIONAL_ACTIVE_STATUSES,
    INTENT_LIVE,
    IdPurpose,
    IntentState,
    OrderType,
    Side,
    make_client_id,
)
from bot.tests.conftest import T_MS
from bot.types import NS_PER_MS

S = IntentState
CTL = ControlState(manual_halt=False)
DEADLINE_SLACK_MS = 1_000


# ---------------------------------------------------------------------------
# 계측: 모든 호출 경계에서 '무방비(롱 포지션 + 우리 closePosition 손절 없음)'를 표본
# ---------------------------------------------------------------------------


def protected(fx: FakeExchange) -> bool:
    q = fx.position_qty
    if q == 0:
        return True
    if q < 0:
        return False
    return any(c.side is Side.SELL and c.type is OrderType.STOP_MARKET and c.close_position
               and c.status in CONDITIONAL_ACTIVE_STATUSES and c.client_algo_id.startswith("sig-")
               and c.trigger_price < fx.mark for c in fx.active_conditionals())


class Monitor:
    """ExchangeClient 프록시. 호출 전후로 무방비 여부를 기록. ``before``: 메서드별 훅(Crash·동시 실행 흉내)."""

    def __init__(self, fx: FakeExchange, clock) -> None:
        self.fx = fx
        self.clock = clock
        self.samples: list[tuple[int, bool]] = []
        self.before: dict[str, Any] = {}
        self.after: dict[str, Any] = {}
        self.exceptions: list[str] = []

    def now_ms(self) -> int:
        return self.clock.now_ns() // NS_PER_MS

    def sample(self) -> None:
        self.samples.append((self.now_ms(), protected(self.fx)))

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.fx, name)
        if name not in EX_METHODS:
            return attr

        def wrapped(*args: Any) -> Any:
            self.sample()
            if name in self.before:
                self.before[name](*args)
            try:
                return attr(*args)
            finally:
                self.sample()
                if name in self.after:
                    self.after[name](*args)

        return wrapped

    def max_unprotected_ms(self) -> int:
        worst = 0
        start: int | None = None
        for t, ok in self.samples:
            if not ok and start is None:
                start = t
            elif ok and start is not None:
                worst = max(worst, t - start)
                start = None
        if start is not None:
            worst = max(worst, self.now_ms() - start)
        return worst


def make_worker(conn, cfg, ex, clock) -> W.Worker:
    return W.Worker(conn, cfg, ex, clock, control_loader=lambda: CTL)


def drive(w: W.Worker, fx: FakeExchange, mon: Monitor, total_ms: int, step_ms: int = 2_000) -> None:
    """워커 루프(run_forever 흉내: 예외는 삼키고 다음 바퀴) + 시장 시간 경과."""
    end = mon.now_ms() + total_ms
    while mon.now_ms() < end:
        try:
            w.run_once()
        except Exception as exc:  # noqa: BLE001 — run_forever와 같이 삼킨다
            mon.exceptions.append(type(exc).__name__)
        mon.sample()
        fx.tick(step_ms)
        mon.sample()


def halt_reasons(conn) -> list[str]:
    return [r["reason"] for r in queue.halts(conn)]


def setup(oconn, oclock, **cfg_kw):
    cfg = make_orders_config(**cfg_kw)
    fx = FakeExchange(oclock, mark=MARK)
    mon = Monitor(fx, oclock)
    w = make_worker(oconn, cfg, mon, oclock)
    w.startup()
    return cfg, fx, mon, w


# ---------------------------------------------------------------------------
# F1. 진입 결과 모름 + get_order만 계속 실패 → 포지션 조회를 안 해 30초+ 무방비
# ---------------------------------------------------------------------------


# 회귀(수정됨): F1 — bot/orders/DESIGN.md §16 R 표
def test_f1_entry_unknown_get_order_failing_leaves_fill_unprotected(oconn, oclock):
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)
    fx.inject(Fault(FaultKind.TIMEOUT_AFTER, method="place_order", params={"client_id_suffix": "-e1"}))
    fx.inject(Fault(FaultKind.HTTP_STATUS, method="get_order", http_status=503, times=-1))
    drive(w, fx, mon, 120_000)
    worst = mon.max_unprotected_ms()
    print("F1 worst unprotected ms:", worst, "state:", queue.get_intent(oconn, iid)["state"],
          "halts:", halt_reasons(oconn))
    assert worst <= cfg.stop_deadline_ms + DEADLINE_SLACK_MS


# ---------------------------------------------------------------------------
# F2. 손절 POST에 429 한 번 → 재시도가 Retry-After를 무시 → 418 금지 → 손절·청산 모두 불가
# ---------------------------------------------------------------------------


# 회귀(수정됨): F2 — bot/orders/DESIGN.md §16 R 표
def test_f2_rate_limit_on_stop_escalates_to_ban(oconn, oclock):
    cfg, fx, mon, w = setup(oconn, oclock)
    # 실제 클라이언트(binance_client._request)는 Retry-After > RETRY_AFTER_MAX_S(10s)면 기다리지 않고 바로 올린다
    # → 가짜의 조회 재시도 0회와 같다. 게이트웨이는 STOP_RETRY_SLEEP_MS(300ms) 뒤 다시 부른다.
    fx.read_retries = 0
    sid, iid = make_approved_intent(oconn)
    fx.inject(Fault(FaultKind.RATE_LIMIT, method="place_conditional", params={"retry_after_s": 15.0}))
    drive(w, fx, mon, 300_000)
    worst = mon.max_unprotected_ms()
    limited = [c for c in fx.calls if c.outcome == "fault:rate_limit"]
    print("F2 worst unprotected ms:", worst, "state:", queue.get_intent(oconn, iid)["state"],
          "halts:", halt_reasons(oconn), "rate-limited calls:", len(limited))
    # 429 창 안에서는 어떤 호출도 보내지 않는다 → 위반·418 금지로 번지지 않는다(처음 429 한 번뿐)
    assert len(limited) == 1
    assert "exchange_block" not in halt_reasons(oconn)
    # 무방비는 Retry-After(15초)로 묶이고(I2 5초는 원리상 불가 — 손절 요청 자체가 거부됨), 끝은 포지션 0 + T0
    assert worst <= 15_000 + cfg.stop_deadline_ms
    assert fx.position_qty == 0 and "unprotected_timeout" in halt_reasons(oconn)


# ---------------------------------------------------------------------------
# F3. 비상 청산 부분 체결 3회 → HALTED 잔여 포지션(손절 없음) + 대조마다 T0·경보가 새로 쌓인다
# ---------------------------------------------------------------------------


def _halted_with_residual(oconn, oclock):
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)
    # 손절 3회 확정 거부 → 비상 청산, 청산은 매번 절반만 체결
    fx.inject(Fault(FaultKind.REJECT, method="place_conditional", code=-1111, times=3))
    fx.inject(Fault(FaultKind.PARTIAL_FILL, method="place_order", fill_ratio=0.5, times=-1, after_calls=1))
    w.run_once()
    return cfg, fx, mon, w, sid, iid


def test_f3_setup_reaches_halted_residual(oconn, oclock):
    cfg, fx, mon, w, sid, iid = _halted_with_residual(oconn, oclock)
    assert queue.get_intent(oconn, iid)["state"] == S.HALTED.value
    # 수정 뒤: 청산이 실패하면 보호 손절을 다시 건다(잔여 포지션이 손절 없이 남지 않는다)
    assert fx.position_qty > 0 and protected(fx)
    assert "flatten_failed" in halt_reasons(oconn)


# 회귀(수정됨): F3a — bot/orders/DESIGN.md §16 R 표
def test_f3a_halted_residual_t0_spam(oconn, oclock):
    cfg, fx, mon, w, sid, iid = _halted_with_residual(oconn, oclock)
    n0 = len(queue.halts(oconn))
    for _ in range(5):
        fx.tick(31_000)
        w.run_once()
    n1 = len(queue.halts(oconn))
    alerts = oconn.execute("SELECT COUNT(*) FROM outbox WHERE kind = 'alert'").fetchone()[0]
    print("F3a halts before/after 5 reconciles:", n0, n1, "alerts:", alerts)
    assert n1 == n0


# 회귀(수정됨): F3b — bot/orders/DESIGN.md §16 R 표
def test_f3b_halted_residual_never_reprotected(oconn, oclock):
    cfg, fx, mon, w, sid, iid = _halted_with_residual(oconn, oclock)
    fx.clear_faults()                                    # 거래소는 이제 정상
    drive(w, fx, mon, 300_000)
    print("F3b pos:", fx.position_qty, "protected:", protected(fx), "worst:", mon.max_unprotected_ms())
    assert protected(fx)


# ---------------------------------------------------------------------------
# F4. 체결 직후 거래소 밖 예외(SQLite 'database is locked' 등) → 루프가 삼키고 다음 대조(30s)까지 무방비
# ---------------------------------------------------------------------------


# 회귀(수정됨): F4 — bot/orders/DESIGN.md §16 R 표
def test_f4_db_error_after_fill_waits_for_reconcile(oconn, oclock, monkeypatch):
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)
    real = queue.add_event
    state = {"done": False}

    def flaky(conn, **kw):
        p = kw.get("payload") or {}
        if not state["done"] and kw.get("kind") == "RESPONSE" and p.get("method") == "place_order":
            state["done"] = True
            raise sqlite3.OperationalError("database is locked")
        return real(conn, **kw)

    monkeypatch.setattr(queue, "add_event", flaky)
    drive(w, fx, mon, 90_000)
    worst = mon.max_unprotected_ms()
    print("F4 worst:", worst, "exceptions:", mon.exceptions, "state:", queue.get_intent(oconn, iid)["state"],
          "halts:", halt_reasons(oconn))
    # 수정 뒤: 이벤트 기록 실패는 주문 흐름을 멈추지 않는다(메모리에 모았다가 나중에 기록) → 예외 자체가 없다
    assert mon.exceptions in ([], ["OperationalError"])
    assert worst <= cfg.stop_deadline_ms + DEADLINE_SLACK_MS
    assert queue.get_intent(oconn, iid)["state"] == S.STOP_VERIFIED.value
    kinds = [r["kind"] for r in queue.events_for(oconn, iid)]
    assert "RESPONSE" in kinds                           # 못 쓴 RESPONSE도 나중에 기록됐다


def test_f4b_db_error_on_fill_transition_protects_without_db(oconn, oclock, monkeypatch):
    """체결 기록 전이 자체가 DB 예외로 실패해도(거래소 밖 예외가 process_intent를 빠져나감) DB 없이 손절을 걸고,
    다음 바퀴에 recover가 거래소 사실로 STOP_VERIFIED를 기록한다."""
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)
    real = queue.transition
    state = {"done": False}

    def flaky(conn, intent_id, expected, new, **kw):
        if not state["done"] and S(new) is S.ENTRY_FILLED:
            state["done"] = True
            raise sqlite3.OperationalError("database is locked")
        return real(conn, intent_id, expected, new, **kw)

    monkeypatch.setattr(queue, "transition", flaky)
    drive(w, fx, mon, 20_000)
    worst = mon.max_unprotected_ms()
    print("F4b worst:", worst, "exceptions:", mon.exceptions, "state:", queue.get_intent(oconn, iid)["state"],
          "halts:", halt_reasons(oconn))
    assert mon.exceptions == ["OperationalError"]
    assert worst <= cfg.stop_deadline_ms + DEADLINE_SLACK_MS
    assert queue.get_intent(oconn, iid)["state"] == S.STOP_VERIFIED.value and protected(fx)
    assert fx.post_count("place_order") == 1 and fx.post_count("place_conditional") == 1


# ---------------------------------------------------------------------------
# F5. 체결이 조회에 늦게 보임(> 도착 기한 + GRACE) → NOT_FILLED 확정 → 우리 포지션이 '모르는 포지션'으로 무기한 무방비
# ---------------------------------------------------------------------------


# 회귀(수정됨): F5 — bot/orders/DESIGN.md §16 R 표
def test_f5_late_visible_fill_becomes_unknown_position(oconn, oclock):
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)
    fx.inject(Fault(FaultKind.FILL_DELAY, method="place_order", delay_ms=15_000,
                    params={"hide_position": True, "client_id_suffix": "-e1"}))
    drive(w, fx, mon, 180_000)
    e1 = fx.get_order(make_client_id(sid, IdPurpose.ENTRY))
    print("F5 intent:", queue.get_intent(oconn, iid)["state"], "e1:", e1 and (e1.status, e1.executed_qty),
          "pos:", fx.position_qty, "halts:", halt_reasons(oconn), "worst:", mon.max_unprotected_ms())
    assert protected(fx)


# ---------------------------------------------------------------------------
# F6. 프로세스 B 단일 실행 보장 없음 — 두 번째 B의 recover가 첫 B의 진입 중 의도를 NOT_FILLED로 확정
# ---------------------------------------------------------------------------


# 회귀(수정됨): F6 — bot/orders/DESIGN.md §16 R 표
def test_f6_second_worker_races_first(tmp_path, oclock):
    path = tmp_path / "b.sqlite3"
    c1 = db.connect(path, mode=TEST_MODE, now_ms=T_MS)
    queue.ensure_schema(c1)
    c2 = db.connect(path, mode=TEST_MODE, now_ms=T_MS)
    cfg = make_orders_config()
    fx = FakeExchange(oclock, mark=MARK)
    mon1 = Monitor(fx, oclock)
    w1 = make_worker(c1, cfg, mon1, oclock)
    w1.startup()
    sid, iid = make_approved_intent(c1)
    mon2 = Monitor(fx, oclock)
    w2 = make_worker(c2, cfg, mon2, oclock)
    fired = {"n": 0}

    def second_b_starts(req):
        # 첫 B가 entry_sent_ms를 커밋하고 e1을 보내려는 순간 두 번째 B가 뜬다(수동 `docker compose run orders` 등)
        if req.client_id.endswith("-e1") and not fired["n"]:
            fired["n"] = 1
            w2.startup()

    mon1.before["place_order"] = second_b_starts
    w1.run_once()
    for _ in range(40):
        fx.tick(2_000)
        w1.run_once()
        w2.run_once()
        mon1.sample()
    row = queue.get_intent(c1, iid)
    print("F6 intent:", row["state"], row["state_reason"], "pos:", fx.position_qty, "halts:", halt_reasons(c1))
    assert protected(fx)


# ---------------------------------------------------------------------------
# F7. 확인된 손절이 거래소에서 사라짐 → 감지는 대조 주기에만(최대 30s 무방비) — 설계상 한도 확인(통과 시험)
# ---------------------------------------------------------------------------


def test_f7_vanished_stop_detected_within_reconcile_interval(oconn, oclock):
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)
    w.run_once()
    assert queue.get_intent(oconn, iid)["state"] == S.STOP_VERIFIED.value
    fx.tick(1_000)
    w.last_reconcile_ms = mon.now_ms()                  # 방금 대조가 끝난 직후 사라지는 최악 시점
    fx.vanish_conditional(suffix="-sl")
    mon.sample()
    drive(w, fx, mon, 60_000)
    worst = mon.max_unprotected_ms()
    print("F7 worst:", worst, "state:", queue.get_intent(oconn, iid)["state"], "halts:", halt_reasons(oconn))
    assert fx.position_qty == 0 and "stop_missing" in halt_reasons(oconn)
    # 수정 뒤: 매 바퀴 손절 존재를 가볍게 조회(quick_stop_check) → 루프 주기 + 청산 시간으로 묶인다(대조 주기 30초가 아니라)
    assert worst <= int(cfg.loop_interval_s * 1000) + cfg.stop_deadline_ms


# ---------------------------------------------------------------------------
# 버틴 경로(회귀 방지)
# ---------------------------------------------------------------------------


def _verified(oconn, oclock):
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)
    w.run_once()
    assert queue.get_intent(oconn, iid)["state"] == S.STOP_VERIFIED.value
    return cfg, fx, mon, w, sid, iid


def _request_exit_now(conn, sid, clock):
    n = clock.now_ns() // NS_PER_MS
    assert queue.request_exit(conn, sid, exit_signal_close_ms=n, exit_due_ms=n, now_ms=n)


def test_ok_exit_resend_duplicate_never_goes_short(oconn, oclock):
    cfg, fx, mon, w, sid, iid = _verified(oconn, oclock)
    fx.inject(Fault(FaultKind.DUPLICATE_RESPONSE, method="place_order", params={"mode": "resend"}))
    _request_exit_now(oconn, sid, oclock)
    drive(w, fx, mon, 20_000)
    assert fx.position_qty == 0 and queue.get_intent(oconn, iid)["state"] == S.CLOSED.value
    assert not fx.active_conditionals()


def test_ok_flatten_delayed_arrival_then_retry_no_short(oconn, oclock):
    cfg, fx, mon, w, sid, iid = _verified(oconn, oclock)
    fx.inject(Fault(FaultKind.DELAYED_ARRIVAL, method="place_order", delay_ms=3_000,
                    params={"client_id_suffix": "-x1"}))
    _request_exit_now(oconn, sid, oclock)
    drive(w, fx, mon, 30_000)
    assert fx.position_qty == 0
    assert queue.get_intent(oconn, iid)["state"] in (S.CLOSED.value, S.FAILED_FLATTENED.value)


def test_ok_disconnect_after_fill_then_reconnect_flattens(oconn, oclock):
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)

    def cut(*_):
        fx.inject(Fault(FaultKind.DISCONNECT))

    mon.after["place_order"] = cut
    w.run_once()
    mon.after.clear()
    assert queue.get_intent(oconn, iid)["state"] == S.HALTED.value
    fx.tick(20_000)
    fx.reconnect()
    drive(w, fx, mon, 60_000)
    assert fx.position_qty == 0 and protected(fx)
    assert "flatten_failed" in halt_reasons(oconn)


def test_ok_t0_blocks_new_entry_but_trend_exit_runs(oconn, oclock):
    cfg, fx, mon, w, sid, iid = _verified(oconn, oclock)
    fx.plant_foreign_order()                        # 모르는 주문 → 대조가 취소 + T0
    fx.tick(31_000)
    w.run_once()
    assert "unknown_order" in halt_reasons(oconn)
    _request_exit_now(oconn, sid, oclock)
    w.run_once()
    assert queue.get_intent(oconn, iid)["state"] == S.CLOSED.value and fx.position_qty == 0
    sid2, iid2 = make_approved_intent(oconn, n=55, approved_ms=oclock.now_ns() // NS_PER_MS)
    w.run_once()
    assert queue.get_intent(oconn, iid2)["state"] == S.REJECTED.value
    assert fx.post_count("place_order", client_id=make_client_id(sid2, IdPurpose.ENTRY)) == 0


# ---------------------------------------------------------------------------
# 무작위 장애 + 강제 종료 퍼징: 끝에 장애를 모두 걷고 충분히 돌린 뒤 불변식 검사
# ---------------------------------------------------------------------------

_FAULT_MENU = [
    lambda r: Fault(FaultKind.TIMEOUT_BEFORE, method=r.choice(sorted(EX_METHODS))),
    lambda r: Fault(FaultKind.TIMEOUT_AFTER, method=r.choice(["place_order", "place_conditional", "cancel_conditional"])),
    lambda r: Fault(FaultKind.DUPLICATE_RESPONSE, params={"mode": "resend"}),
    lambda r: Fault(FaultKind.PARTIAL_FILL, fill_ratio=r.choice([0.3, 0.5, 0.9])),
    lambda r: Fault(FaultKind.NO_FILL),
    lambda r: Fault(FaultKind.REJECT, method=r.choice(["place_order", "place_conditional"]),
                    code=r.choice([-1111, -2019, -4164, -1001])),
    lambda r: Fault(FaultKind.STOP_MISSING),
    lambda r: Fault(FaultKind.STOP_FIELD_IGNORED),
    lambda r: Fault(FaultKind.FILL_DELAY, delay_ms=r.choice([500, 1500, 4000]), params={"respond": r.random() < .5}),
    lambda r: Fault(FaultKind.DELAYED_ARRIVAL, delay_ms=r.choice([1000, 3000, 9000])),
    lambda r: Fault(FaultKind.HTTP_STATUS, method=r.choice(sorted(EX_METHODS)), http_status=r.choice([500, 503])),
    lambda r: Fault(FaultKind.STOP_VANISH, params={"client_id_suffix": "-sl"}),
]


def _fuzz_once(seed: int, tmp_path, oclock) -> dict:
    r = random.Random(seed)
    path = tmp_path / f"fz{seed}.sqlite3"
    conn = db.connect(path, mode=TEST_MODE, now_ms=T_MS)
    queue.ensure_schema(conn)
    cfg = make_orders_config()
    fx = FakeExchange(oclock, mark=MARK)
    mon = Monitor(fx, oclock)
    w = make_worker(conn, cfg, mon, oclock)
    w.startup()
    sid, iid = make_approved_intent(conn, approved_ms=oclock.now_ns() // NS_PER_MS)
    for _ in range(r.randint(1, 4)):
        f = r.choice(_FAULT_MENU)(r)
        f.after_calls = r.randint(0, 12)
        f.times = r.choice([1, 1, 2, 3, 5])
        fx.inject(f)
    crash_at = r.randint(5, 40) if r.random() < 0.6 else None
    calls = {"n": 0}

    def maybe_crash(*_):
        calls["n"] += 1
        if crash_at is not None and calls["n"] == crash_at:
            raise Crash()

    for m in EX_METHODS:
        mon.before[m] = maybe_crash
    exit_asked = False
    for step in range(40):
        try:
            w.run_once()
        except Crash:
            conn.close()
            fx.tick(5_000)
            conn = db.connect(path, mode=TEST_MODE, now_ms=T_MS)
            w = make_worker(conn, cfg, mon, oclock)
            try:
                w.startup()
            except Crash:
                pass
        except Exception as exc:  # noqa: BLE001
            mon.exceptions.append(type(exc).__name__)
        if step == 10 and r.random() < 0.5:
            row = queue.get_intent(conn, iid)
            if row["state"] in ("ENTRY_FILLED", "STOP_PLACED", "STOP_VERIFIED"):
                n = oclock.now_ns() // NS_PER_MS
                exit_asked = queue.request_exit(conn, sid, exit_signal_close_ms=n, exit_due_ms=n, now_ms=n)
        if step == 20 and r.random() < 0.3:
            fx.set_mark(MARK * 0.9)                 # 손절 발동 유도
        fx.tick(2_000)
    # 정리: 장애 제거 후 충분히(대조 여러 번)
    mon.before.clear()
    fx.clear_faults()
    fx.tick(10_000)
    if not w.started:
        w = make_worker(conn, cfg, mon, oclock)
        w.startup()
    for _ in range(60):
        try:
            w.run_once()
        except Exception as exc:  # noqa: BLE001
            mon.exceptions.append(type(exc).__name__)
        fx.tick(2_000)
    row = queue.get_intent(conn, iid)
    live = queue.intents_in_states(conn, INTENT_LIVE)
    out = dict(seed=seed, state=row["state"], reason=row["state_reason"], pos=fx.position_qty,
               protected=protected(fx), e1=fx.post_count("place_order", client_id=make_client_id(sid, IdPurpose.ENTRY)),
               live=len(live), halts=halt_reasons(conn), worst=mon.max_unprotected_ms(), exc=mon.exceptions,
               crash=crash_at, exit=exit_asked,
               db_says_flat=(row["state"] not in {s.value for s in INTENT_LIVE}))
    conn.close()
    return out


FUZZ_SEEDS = range(60)


@pytest.mark.parametrize("seed", FUZZ_SEEDS)
def test_fuzz_end_state_safe(seed, tmp_path, oclock):
    o = _fuzz_once(seed, tmp_path, oclock)
    print(o)
    assert o["pos"] >= 0, o
    assert o["e1"] <= 1, o                     # 진입 POST는 신호당 1회
    assert o["live"] <= 1, o
    # 끝 상태: 포지션 0이거나 손절로 보호(F3·F5 수정 뒤 엄격 — 수정 전 xfail로 넘기던 것)
    assert o["protected"], o
    # DB가 '끝남'이라는데 거래소에 포지션이 있으면 대조 누락
    assert not (o["db_says_flat"] and o["pos"] > 0), o


# ---------------------------------------------------------------------------
# F8. 킬 스위치 해제가 halt_id 숫자만으로 묶임 — DB 복원·재생성 뒤 옛 제어 파일이 새 T0를 즉시 '해제'
# ---------------------------------------------------------------------------


# 회귀(수정됨): F8 — bot/orders/DESIGN.md §16 R 표
def test_f8_stale_release_disarms_new_t0(oconn, oclock):
    cfg = make_orders_config()
    fx = FakeExchange(oclock, mark=MARK)
    mon = Monitor(fx, oclock)
    # 복원 전 DB에서 T0 #1을 해제했던 제어 파일이 그대로 남아 있다
    stale = ControlState(manual_halt=False, released=frozenset({1}), error=None, ref="old")
    w = W.Worker(oconn, cfg, mon, oclock, control_loader=lambda: stale)
    w.startup()
    fx.plant_foreign_order()                         # 새 사건: 모르는 주문 → 대조가 취소 + T0 #1(새 DB)
    fx.tick(31_000)
    w.run_once()
    assert [int(r["halt_id"]) for r in queue.halts(oconn)] == [1]
    sid, iid = make_approved_intent(oconn, approved_ms=oclock.now_ns() // NS_PER_MS)
    w.run_once()
    row = queue.get_intent(oconn, iid)
    print("F8 intent after fresh T0 #1:", row["state"], row["state_reason"],
          "e1 posts:", fx.post_count("place_order", client_id=make_client_id(sid, IdPurpose.ENTRY)))
    assert fx.post_count("place_order", client_id=make_client_id(sid, IdPurpose.ENTRY)) == 0


# ---------------------------------------------------------------------------
# F3c. (퍼징 seed 192에서 발견) 비상 청산 시장가 3번이 0 체결 → 3회 한도가 1초 안에 평생 소진 → 전량 포지션 무기한 무방비
# ---------------------------------------------------------------------------


# 회귀(수정됨): F3c — bot/orders/DESIGN.md §16 R 표
def test_f3c_flatten_budget_burned_full_position_unprotected_forever(oconn, oclock):
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)
    fx.inject(Fault(FaultKind.STOP_MISSING, times=1))                       # 손절 확인 실패 → 비상 청산
    fx.inject(Fault(FaultKind.NO_FILL, method="place_order", times=3, after_calls=1))   # f1~f3 0 체결
    w.run_once()
    assert queue.get_intent(oconn, iid)["state"] == S.HALTED.value
    drive(w, fx, mon, 600_000)                                              # 이후 거래소 정상, 10분
    print("F3c pos:", fx.position_qty, "protected:", protected(fx), "worst:", mon.max_unprotected_ms(),
          "halts:", len(queue.halts(oconn)))
    assert protected(fx)


# ---------------------------------------------------------------------------
# F9. (퍼징 seed 65에서 발견) take_snapshot이 공개 mark_price 하나에 묶여 있다 → 마크 조회만 실패해도 재시작 복구·대조가
#     손절 없는 ENTRY_FILLED 포지션에 아무 조치도 하지 않는다(포지션·주문 조회와 주문은 되는데도)
# ---------------------------------------------------------------------------


# 회귀(수정됨): F9 — bot/orders/DESIGN.md §16 R 표
def test_f9_mark_price_outage_blocks_restart_recovery(oconn, oclock):
    cfg, fx, mon, w = setup(oconn, oclock)
    sid, iid = make_approved_intent(oconn)

    def crash(*_):
        raise Crash()

    mon.before["place_conditional"] = crash                 # 체결 직후, 손절 전송 전에 B 강제 종료
    with pytest.raises(Crash):
        w.run_once()
    mon.before.clear()
    assert queue.get_intent(oconn, iid)["state"] == S.ENTRY_FILLED.value
    fx.inject(Fault(FaultKind.HTTP_STATUS, method="mark_price", http_status=503, times=-1))
    fx.tick(5_000)
    w2 = make_worker(oconn, cfg, mon, oclock)
    w2.startup()
    drive(w2, fx, mon, 180_000)
    print("F9 state:", queue.get_intent(oconn, iid)["state"], "pos:", fx.position_qty, "protected:", protected(fx),
          "worst:", mon.max_unprotected_ms(), "halts:", halt_reasons(oconn))
    assert protected(fx)
