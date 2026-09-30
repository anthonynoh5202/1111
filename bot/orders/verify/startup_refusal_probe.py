"""검증 V5 — 체결 직후(손절 전) 강제 종료 + 재시작 때 B가 '시작 거부'하면 포지션이 무방비로 남는가 (독립 검증관).

worker.main(run)은 설정·비밀·DB 모드·보호 트리거 검사(queue.ensure_schema) 중 하나라도 실패하면 **recover() 전에** 종료한다
(EXIT_CONFIG·EXIT_DB). compose의 restart: unless-stopped는 같은 이유로 계속 거부되므로, 그 사이 손절 없는 포지션을 아무도
보호·청산하지 않는다. 여기서는 가장 짧은 경로(보호 트리거 1개 삭제)로 재현한다.

실행: .venv/bin/python -m bot.orders.verify.startup_refusal_probe  → results/startup_refusal.json

수정 담당(2차, V-1 수정 뒤): 거부 전 보호는 진입점 worker.main()에 있다(Worker.startup()은 설계상 거부만 한다).
그래서 실제 재시작 경로(main(run), 가짜 거래소 주입)로 같은 장면을 재현하는 ``run_via_main``을 더했다.
판정(종료 코드)은 main 경로 결과로 한다. 직접 startup() 변형은 참고용으로 계속 기록한다.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

from bot import db
from bot.orders import queue
from bot.orders import worker as W
from bot.orders.control import ControlState
from bot.orders.fake_exchange import FakeExchange
from bot.orders.ledger import Ledger
from bot.orders.tests.conftest import MARK, T_APPROVED_MS, TEST_MODE, make_approved_intent, make_orders_config
from bot.tests.conftest import T_MS
from bot.types import FakeClock, NS_PER_MS

OUT = Path(__file__).resolve().parent / "results" / "startup_refusal.json"


class Kill(BaseException):
    """SIGKILL 흉내(손절 등록 요청 직전)."""


def run(variant: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
        dbp = Path(d) / "t.sqlite3"
        conn = db.connect(dbp, mode=TEST_MODE, now_ms=T_MS)
        queue.ensure_schema(conn)
        fx = FakeExchange(clock, mark=MARK)
        ctl = ControlState(manual_halt=False)
        led = Ledger(Path(d) / "l.json")
        mk = lambda c: W.Worker(c, make_orders_config(), fx, clock, control_loader=lambda: ctl, ledger=led,  # noqa: E731
                                sleep_ms=lambda ms: clock.advance(ms * NS_PER_MS))
        w = mk(conn)
        w.startup()
        make_approved_intent(conn)
        real = fx.place_conditional

        def boom(*a, **k):
            raise Kill()

        fx.place_conditional = boom
        try:
            w.run_once()
        except Kill:
            pass
        fx.place_conditional = real
        conn.close()
        after_crash = dict(position=fx.position_qty, stops=len(fx.active_conditionals()))
        c2 = db.connect(dbp, mode=TEST_MODE, now_ms=T_MS)
        if variant == "drop_trigger":
            c2.execute("DROP TRIGGER order_events_no_delete")
            c2.commit()
        c2.close()
        clock.advance(3_000 * NS_PER_MS)
        refused = None
        try:
            conn = db.connect(dbp, mode=TEST_MODE, now_ms=T_MS)
            mk(conn).startup()
        except Exception as exc:  # noqa: BLE001
            refused = f"{type(exc).__name__}: {str(exc)[:100]}"
        return dict(variant=variant, after_crash=after_crash, restart_refused=refused,
                    after_restart=dict(position=fx.position_qty, stops=len(fx.active_conditionals())))


def run_via_main(variant: str) -> dict:
    """compose 재시작과 같은 경로: worker.main(run)에 같은 가짜 거래소를 주입. 거부되더라도 포지션이 보호돼야 한다."""
    import os
    import threading

    from bot.orders.tests.test_worker import _write_toml
    from bot.types import Mode

    old_umask = os.umask(0o022)
    os.umask(old_umask)
    try:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            p = _write_toml(tmp)
            dbp = tmp / "data" / "testnet.sqlite3"
            clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
            conn = db.connect(dbp, mode=Mode.TESTNET, now_ms=T_MS)
            queue.ensure_schema(conn)
            fx = FakeExchange(clock, mark=MARK)
            ctl = ControlState(manual_halt=False)
            w = W.Worker(conn, make_orders_config(), fx, clock, control_loader=lambda: ctl, ledger=Ledger(None),
                         sleep_ms=lambda ms: clock.advance(ms * NS_PER_MS))
            w.startup()
            make_approved_intent(conn)
            real = fx.place_conditional

            def boom(*a, **k):
                raise Kill()

            fx.place_conditional = boom
            try:
                w.run_once()
            except Kill:
                pass
            fx.place_conditional = real
            conn.close()
            after_crash = dict(position=fx.position_qty, stops=len(fx.active_conditionals()))
            if variant == "drop_trigger":
                c2 = db.connect(dbp, mode=Mode.TESTNET, now_ms=T_MS)
                c2.execute("DROP TRIGGER order_events_no_delete")
                c2.commit()
                c2.close()
            clock.advance(3_000 * NS_PER_MS)
            stop = threading.Event()
            stop.set()
            code = W.main(["--config", str(p), "run"], environ={}, clock=clock, client_factory=lambda c, k: fx,
                          stop=stop)
            return dict(variant=f"{variant}(main)", after_crash=after_crash, exit_code=code,
                        after_restart=dict(position=fx.position_qty, stops=len(fx.active_conditionals())))
    finally:
        os.umask(old_umask)


def main() -> int:
    logging.disable(logging.CRITICAL)
    direct = [run("control"), run("drop_trigger")]
    via_main = [run_via_main("control"), run_via_main("drop_trigger")]
    res = direct + via_main
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        print(json.dumps(r, ensure_ascii=False))
    exposed = [r for r in via_main if r["after_restart"]["position"] > 0 and r["after_restart"]["stops"] == 0]
    return 1 if exposed else 0


if __name__ == "__main__":
    sys.exit(main())
