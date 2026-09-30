"""검증 2차 — V-2 수정(HALTED 보유 매 바퀴 재보호)의 남은 틈: 손절 단건 조회(get_conditional)만 계속 실패할 때 (독립 검증관).

장면: 손절 등록이 계속 사라지고(STOP_MISSING) 청산 f1~f3가 0 체결 → HALTED, 손절 없음. 그 뒤 거래소가 주문은 받지만
아래 조회가 실패한다. 매 바퀴 확인(quick_unprotected_check)은 조회 실패를 '판단 보류(False)'로 보므로, 다음 대조까지
기다리는지 잰다(가짜 시계, 2초 바퀴). 제품 코드는 바꾸지 않는다.

실행: .venv/bin/python -m bot.orders.verify.halted_query_fail_probe → results/halted_query_fail.json
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

from bot import db
from bot.orders import queue
from bot.orders.fake_exchange import Fault, FaultKind, FakeExchange
from bot.orders.tests.conftest import MARK, T_APPROVED_MS, TEST_MODE, make_approved_intent, make_orders_config
from bot.orders.tests.review_chaos_test import Monitor, make_worker, protected
from bot.tests.conftest import T_MS
from bot.types import FakeClock, NS_PER_MS

OUT = Path(__file__).resolve().parent / "results" / "halted_query_fail.json"


def run(name: str, faults: list[Fault], interval: int) -> dict:
    with tempfile.TemporaryDirectory() as d:
        clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
        conn = db.connect(Path(d) / "x.sqlite3", mode=TEST_MODE, now_ms=T_MS)
        queue.ensure_schema(conn)
        fx = FakeExchange(clock, mark=MARK)
        w = make_worker(conn, make_orders_config(reconcile_interval_s=interval), Monitor(fx, clock), clock)
        w.startup()
        _, iid = make_approved_intent(conn, approved_ms=clock.now_ns() // NS_PER_MS)
        fx.inject(Fault(FaultKind.STOP_MISSING, times=-1))
        fx.inject(Fault(FaultKind.NO_FILL, method="place_order", times=3, after_calls=1))
        w.run_once()
        st0 = queue.get_intent(conn, iid)["state"]
        unprot0 = fx.position_qty > 0 and not protected(fx)
        fx.clear_faults()
        for f in faults:
            fx.inject(f)
        t0 = clock.now_ns() // NS_PER_MS
        t_safe = None
        for _ in range(40):
            fx.tick(2_000)
            try:
                w.run_once()
            except Exception:  # noqa: BLE001
                pass
            if protected(fx):
                t_safe = clock.now_ns() // NS_PER_MS - t0
                break
        out = dict(name=name, reconcile_interval_s=interval, state_at_halt=st0, unprotected_at_halt=unprot0,
                   end_state=queue.get_intent(conn, iid)["state"], protected_after_ms=t_safe,
                   end_position=fx.position_qty)
        conn.close()
        return out


def main() -> int:
    logging.disable(logging.CRITICAL)
    gc503 = lambda: Fault(FaultKind.HTTP_STATUS, method="get_conditional", http_status=503, times=-1)  # noqa: E731
    oc503 = lambda: Fault(FaultKind.HTTP_STATUS, method="open_conditional_orders", http_status=503, times=-1)  # noqa: E731
    res = [
        run("exchange_recovers_fully", [], 30),
        run("get_conditional_503", [gc503()], 30),
        run("get_conditional_503", [gc503()], 10),
        run("get_and_open_conditional_503", [gc503(), oc503()], 30),
        run("get_and_open_conditional_503", [gc503(), oc503()], 10),
        run("stop_placement_still_lost", [Fault(FaultKind.STOP_MISSING, times=-1)], 30),
        run("position_503_x5", [Fault(FaultKind.HTTP_STATUS, method="position", http_status=503, times=5)], 30),
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res:
        print(json.dumps(r, ensure_ascii=False))
    over = [r["name"] for r in res if r["protected_after_ms"] is None or r["protected_after_ms"] > 5_000]
    print("OVER_5S:", over)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
