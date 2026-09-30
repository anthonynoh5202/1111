"""수정 담당(2차) 회귀 시험 — 독립 검증 V-1·V-2 (bot/orders/verify/VERIFY_REPORT.md).

V-1: 체결 뒤·손절 전에 B가 죽고, 재시작이 설정·DB 문제로 **recover() 전에 거부**되면 손절 없는 포지션이 무기한 남았다.
     수정: worker.main()이 시작을 거부하기 전에 DB 없이 보호(gateway.protect_without_db)한 뒤 종료한다
     — 우리 보호 손절이 살아 있으면 그대로, 없으면 reduceOnly 시장가 전량 청산(방화벽 통과, sig-<새 ID>-f1..f3).
     다른 B가 잠금을 쥐고 있으면(그 B가 보호 중) 아무것도 하지 않는다.
V-2: HALTED 보유(청산 f1~f3 실패 + 손절 재등록 실패)가 대조 주기(30초)까지 손절 없이 남았다(퍼징 seed 9531·4253, 30.8초).
     수정: 매 바퀴 HALTED·EXITING 보유의 손절 없음을 가볍게 조회해, HALTED면 secure_halted를 바로, EXITING이면 대조를 앞당긴다.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

import pytest

from bot import db
from bot.orders import queue
from bot.orders import worker as W
from bot.orders.control import ControlState
from bot.orders.fake_exchange import FakeExchange, Fault, FaultKind
from bot.orders.gateway import protect_without_db
from bot.orders.ledger import Ledger
from bot.orders.tests.conftest import MARK, T_APPROVED_MS, TEST_MODE, make_approved_intent, make_orders_config
from bot.orders.tests.review_chaos_test import Monitor, _fuzz_once, make_worker, protected
from bot.orders.tests.test_worker import _write_toml
from bot.orders.types import IntentState, OrderType, Side, parse_client_id
from bot.tests.conftest import T_MS
from bot.types import FakeClock, Mode, NS_PER_MS

S = IntentState


class Kill(BaseException):
    """SIGKILL 흉내."""


@pytest.fixture
def restore_umask():
    old = os.umask(0o022)
    os.umask(old)
    yield
    os.umask(old)


def _crash_after_fill(tmp_path: Path, *, kill_on: str = "place_conditional") -> tuple[Path, FakeClock, FakeExchange]:
    """설정 파일의 DB에 진입이 체결된 의도를 만들고, kill_on 호출 직전에 B를 죽인다. (설정 경로, 시계, 거래소)."""
    p = _write_toml(tmp_path)
    dbp = tmp_path / "data" / "testnet.sqlite3"
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    conn = db.connect(dbp, mode=Mode.TESTNET, now_ms=T_MS)
    queue.ensure_schema(conn)
    fx = FakeExchange(clock, mark=MARK)
    w = W.Worker(conn, make_orders_config(), fx, clock, control_loader=lambda: ControlState(manual_halt=False),
                 ledger=Ledger(None))
    w.startup()
    make_approved_intent(conn)
    real = getattr(fx, kill_on)

    def boom(*a, **k):
        raise Kill()

    setattr(fx, kill_on, boom)
    try:
        w.run_once()
    except Kill:
        pass
    setattr(fx, kill_on, real)
    conn.close()
    clock.advance(3_000 * NS_PER_MS)
    return p, clock, fx


def _drop_trigger(tmp_path: Path) -> None:
    c = sqlite3.connect(tmp_path / "data" / "testnet.sqlite3")
    c.execute("DROP TRIGGER order_events_no_delete")
    c.commit()
    c.close()


def _run_main(p: Path, clock: FakeClock, fx: FakeExchange) -> int:
    stop = threading.Event()
    stop.set()
    return W.main(["--config", str(p), "run"], environ={}, clock=clock, client_factory=lambda c, k: fx, stop=stop)


# ---------------------------------------------------------------------------
# V-1
# ---------------------------------------------------------------------------


def test_v1_restart_refused_by_db_tamper_still_flattens_unprotected_position(tmp_path, restore_umask, capsys):
    p, clock, fx = _crash_after_fill(tmp_path)
    assert fx.position_qty > 0 and not fx.active_conditionals()          # 체결 + 손절 없음(수정 전 재현 상태)
    _drop_trigger(tmp_path)
    code = _run_main(p, clock, fx)
    assert code == W.EXIT_DB                                              # 여전히 시작은 거부한다(fail-closed)
    assert fx.position_qty == 0.0                                         # 그러나 포지션은 청산됐다
    posts = [r for r in fx.calls if r.method == "place_order" and r.client_id and r.client_id.endswith("-f1")]
    assert posts, "비상 청산 f1이 있어야 한다"
    assert parse_client_id(posts[-1].client_id) is not None               # sig- 접두사·형식
    err = capsys.readouterr().err
    assert "시작 거부" in err and "flattened" in err
    # 다음 재시작(compose)도 같은 이유로 거부 — 이번엔 포지션 0이라 아무 주문도 없다
    n = len(fx.calls)
    assert _run_main(p, clock, fx) == W.EXIT_DB
    assert not [r for r in fx.calls[n:] if r.method in ("place_order", "place_conditional")]


def test_v1_restart_refused_keeps_verified_stop_and_position(tmp_path, restore_umask):
    """우리 보호 손절이 살아 있으면 청산하지 않는다(사람이 DB를 고친 뒤 recover가 판단)."""
    p = _write_toml(tmp_path)
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    conn = db.connect(tmp_path / "data" / "testnet.sqlite3", mode=Mode.TESTNET, now_ms=T_MS)
    queue.ensure_schema(conn)
    fx = FakeExchange(clock, mark=MARK)
    w = W.Worker(conn, make_orders_config(), fx, clock, control_loader=lambda: ControlState(manual_halt=False),
                 ledger=Ledger(None))
    w.startup()
    make_approved_intent(conn)
    w.run_once()
    live = queue.live_intent(conn)
    conn.close()
    assert live is not None and live["state"] == S.STOP_VERIFIED.value
    q0 = fx.position_qty
    assert q0 > 0 and protected(fx)
    _drop_trigger(tmp_path)
    n = len(fx.calls)
    assert _run_main(p, clock, fx) == W.EXIT_DB
    assert fx.position_qty == q0 and protected(fx)
    assert not [r for r in fx.calls[n:] if r.method in ("place_order", "place_conditional", "cancel_conditional")]


def test_v1_db_mode_mismatch_refusal_also_protects(tmp_path, restore_umask):
    p, clock, fx = _crash_after_fill(tmp_path)
    dbp = tmp_path / "data" / "testnet.sqlite3"
    dbp.unlink()
    db.connect(dbp, mode=Mode.PAPER, now_ms=T_MS).close()                  # 잘못된 DB(모드 불일치)
    assert _run_main(p, clock, fx) == W.EXIT_DB
    assert fx.position_qty == 0.0


def test_v1_a_secret_visible_refusal_also_protects(tmp_path, restore_umask, capsys):
    p, clock, fx = _crash_after_fill(tmp_path)
    a = tmp_path / "a"
    a.mkdir()
    (a / "telegram_bot_token").write_text("1:x")
    assert _run_main(p, clock, fx) == W.EXIT_CONFIG
    assert "A 프로세스 비밀" in capsys.readouterr().err
    assert fx.position_qty == 0.0


def test_v1_no_rescue_when_another_b_holds_the_lock(tmp_path, restore_umask):
    p, clock, fx = _crash_after_fill(tmp_path)
    _drop_trigger(tmp_path)
    fd = W._acquire_single_instance_lock(tmp_path / "data" / "testnet.sqlite3")
    assert fd is not None and fd >= 0
    try:
        n = len(fx.calls)
        assert _run_main(p, clock, fx) == W.EXIT_CONFIG
        assert fx.position_qty > 0                                        # 다른 B의 일 — 끼어들지 않는다
        assert not [r for r in fx.calls[n:] if r.method == "place_order"]
    finally:
        os.close(fd)


def test_v1_startup_unexpected_exception_also_protects(tmp_path, restore_umask, monkeypatch):
    p, clock, fx = _crash_after_fill(tmp_path)

    def bad_recover(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(W, "recover", bad_recover)
    assert _run_main(p, clock, fx) == W.EXIT_ERROR
    assert fx.position_qty == 0.0


def test_protect_without_db_rate_limit_and_firewall(tmp_path):
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    fx = FakeExchange(clock, mark=MARK)
    fx.plant_foreign_position(qty=0.01)
    fx.inject(Fault(FaultKind.RATE_LIMIT, method="position", times=1, params={"retry_after_s": 2}))
    fx.inject(Fault(FaultKind.NO_FILL, method="place_order", times=4))    # f1~f3 + 다음 주기 f1 0 체결
    sleep = lambda ms: clock.advance(int(ms) * NS_PER_MS)                   # noqa: E731
    res = protect_without_db(fx, make_orders_config(), clock, base_url=fx.base_url, sleep_ms=sleep)
    assert res == "flattened" and fx.position_qty == 0.0
    orders = [r for r in fx.calls if r.method == "place_order"]
    ids = [r.client_id for r in orders]
    assert len(set(ids)) == len(ids)                                      # clientOrderId 재사용 없음(K15)
    for r in orders:
        pc = parse_client_id(r.client_id)
        assert pc is not None and pc.purpose.value.startswith("f")
        assert r.request.reduce_only is True and r.request.side is Side.SELL and r.request.type is OrderType.MARKET
    # 대기 창 안에서 다시 보낸 호출이 없다(429는 주입한 1건뿐, 418 없음)
    assert sum(1 for c in fx.calls if c.outcome == "fault:rate_limit") == 1


def test_protect_without_db_short_and_flat_do_nothing():
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    fx = FakeExchange(clock, mark=MARK)
    sleep = lambda ms: clock.advance(int(ms) * NS_PER_MS)                   # noqa: E731
    assert protect_without_db(fx, make_orders_config(), clock, base_url=fx.base_url, sleep_ms=sleep) == "flat"
    assert not [r for r in fx.calls if r.method == "place_order"]


def test_v1_verifier_probe_via_main_is_safe(tmp_path, restore_umask):
    from bot.orders.verify import startup_refusal_probe as P

    r = P.run_via_main("drop_trigger")
    assert r["after_crash"]["position"] > 0 and r["after_crash"]["stops"] == 0
    assert r["exit_code"] == W.EXIT_DB and r["after_restart"]["position"] == 0


# ---------------------------------------------------------------------------
# V-2
# ---------------------------------------------------------------------------


def test_v2_halted_unprotected_is_resecured_within_loop_not_reconcile(oconn, oclock):
    cfg = make_orders_config()
    fx = FakeExchange(oclock, mark=MARK)
    mon = Monitor(fx, oclock)
    w = make_worker(oconn, cfg, mon, oclock)
    w.startup()
    sid, iid = make_approved_intent(oconn)
    fx.inject(Fault(FaultKind.STOP_MISSING, times=-1))                    # 손절 등록·재등록 모두 실패
    fx.inject(Fault(FaultKind.NO_FILL, method="place_order", times=3, after_calls=1))   # f1~f3 0 체결
    w.run_once()
    assert queue.get_intent(oconn, iid)["state"] == S.HALTED.value
    assert fx.position_qty > 0 and not protected(fx)
    t_halted = oclock.now_ns() // NS_PER_MS
    fx.clear_faults()                                                     # 거래소 회복
    t_safe = None
    for _ in range(15):                                                   # 30초(수정 전: 다음 대조까지 무방비)
        fx.tick(2_000)
        w.run_once()
        if protected(fx):
            t_safe = oclock.now_ns() // NS_PER_MS
            break
    assert t_safe is not None and t_safe - t_halted <= 5_000, "HALTED 무방비가 루프 주기 안에 보호돼야 한다"
    assert w.last_reconcile_ms is not None and w.last_reconcile_ms < t_halted  # 대조가 아니라 매 바퀴 경로로


def test_v2_halted_protected_is_not_touched_every_loop(oconn, oclock):
    """손절이 살아 있는 HALTED는 매 바퀴 조회 1건만(주문 없음)."""
    cfg = make_orders_config()
    fx = FakeExchange(oclock, mark=MARK)
    mon = Monitor(fx, oclock)
    w = make_worker(oconn, cfg, mon, oclock)
    w.startup()
    sid, iid = make_approved_intent(oconn)
    fx.inject(Fault(FaultKind.STOP_MISSING, times=1))                     # 첫 손절만 실패 → 청산 f1~f3 실패 → 재등록 성공
    fx.inject(Fault(FaultKind.NO_FILL, method="place_order", times=3, after_calls=1))
    w.run_once()
    assert queue.get_intent(oconn, iid)["state"] == S.HALTED.value and protected(fx)
    n = len(fx.calls)
    fx.tick(2_000)
    w.run_once()
    assert not [r for r in fx.calls[n:] if r.method in ("place_order", "place_conditional", "cancel_conditional")]


@pytest.mark.parametrize("seed", [9531, 4253])
def test_v2_fuzz_seeds_bounded_by_loop(seed, tmp_path):
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    o = _fuzz_once(seed, tmp_path, clock)
    assert o["protected"] and o["pos"] >= 0
    assert o["worst"] <= 5_000, o                                         # 수정 전 30.8초(검증 V-2)
