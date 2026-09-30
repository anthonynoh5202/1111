"""검증 2차 — V-1 수정(시작 거부 전 DB 없는 보호, gateway.protect_without_db)의 경계 사례 (독립 검증관).

수정 담당의 시험(test_verify_fixes.py)이 다루지 않은 장면을 가짜 거래소로 확인한다. 제품 코드는 고치지 않는다.
판정: 끝에 포지션 ≥ 0(숏 없음), 롱이 남으면 우리 보호 손절이 살아 있어야 한다(아니면 결과 문자열이 운영자에게
'웹에서 확인'을 알리는 값이어야 한다), 모든 주문은 sig- 접두사·reduceOnly·SELL·MARKET, clientOrderId 재사용 없음,
호출 수가 폭주하지 않음(가짜 시계는 호출마다 흐르지 않으므로 호출 상한으로 무한 반복을 잡는다).

실행: .venv/bin/python -m bot.orders.verify.rescue_edge_probe → results/rescue_edge.json (종료 코드 1 = 문제 있음)
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from bot.orders.fake_exchange import Fault, FaultKind, FakeExchange
from bot.orders.gateway import protect_without_db
from bot.orders.tests.conftest import MARK, T_APPROVED_MS, make_orders_config
from bot.orders.types import OrderType, Side, parse_client_id
from bot.types import FakeClock, NS_PER_MS

OUT = Path(__file__).resolve().parent / "results" / "rescue_edge.json"
CALL_CAP = 2_000


class Runaway(BaseException):
    pass


class Capped:
    """호출 수 상한을 두는 얇은 감싸개(무한 반복 탐지)."""

    def __init__(self, fx: FakeExchange, cap: int = CALL_CAP) -> None:
        self._fx, self._cap, self.n = fx, cap, 0

    def __getattr__(self, name: str) -> Any:
        a = getattr(self._fx, name)
        if callable(a) and name in {"position", "mark_price", "open_conditional_orders", "place_order",
                                    "get_conditional", "open_orders", "get_order"}:
            def w(*x, **k):
                self.n += 1
                if self.n > self._cap:
                    raise Runaway(name)
                return a(*x, **k)
            return w
        return a


def _stop(fx: FakeExchange, sid: str = "BGFLP4PQWMTD62PH", trig: float | None = None) -> None:
    """우리 형식(sig-…-sl)의 보호 손절을 거래소에 직접 심는다(주문 메서드 직접 호출 없이 — 보안 시험 규칙)."""
    from bot.orders.types import IdPurpose, make_client_id
    fx.plant_foreign_order(conditional=True, client_id=make_client_id(sid, IdPurpose.STOP),
                           trigger_price=trig if trig is not None else round(MARK * 0.95, 1))


def run(name: str, setup: Callable[[FakeExchange], None], *, deadline_ms: int = 60_000,
        tick_on_sleep: bool = True) -> dict:
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    fx = FakeExchange(clock, mark=MARK)
    fx.plant_foreign_position(qty=0.016)
    setup(fx)
    cx = Capped(fx)
    t0 = clock.now_ns() // NS_PER_MS

    def sleep(ms: int) -> None:
        fx.tick(int(ms)) if tick_on_sleep else clock.advance(int(ms) * NS_PER_MS)

    try:
        res = protect_without_db(cx, make_orders_config(), clock, base_url=fx.base_url, sleep_ms=sleep,
                                 deadline_ms=deadline_ms)
    except Runaway as r:
        res = f"RUNAWAY({r})"
    # 늦게 도착하는 요청까지 처리한 뒤의 끝 상태
    fx.tick(30_000)
    orders = [c for c in fx.calls if c.method.startswith("place_order")]
    ids = [c.client_id for c in fx.calls if c.method == "place_order"]
    shapes_ok = all(c.request.reduce_only and c.request.side is Side.SELL and c.request.type is OrderType.MARKET
                    and parse_client_id(c.client_id) is not None for c in orders)
    pos = fx.position_qty
    ours = [c for c in fx.active_conditionals() if parse_client_id(c.client_algo_id) is not None]
    return dict(name=name, result=res, elapsed_ms=clock.now_ns() // NS_PER_MS - t0 - 30_000, calls=cx.n,
                orders=len(ids), unique_ids=len(set(ids)) == len(ids), shapes_ok=shapes_ok,
                end_position=pos, our_stops=len(ours))


def main() -> int:
    logging.disable(logging.CRITICAL)
    cases: list[tuple[str, Callable[[FakeExchange], None], dict]] = [
        ("baseline_unprotected", lambda fx: None, {}),
        ("our_stop_active", lambda fx: _stop(fx), {}),
        ("foreign_web_stop_only", lambda fx: fx.plant_foreign_order(conditional=True), {}),
        ("our_stop_fired_before_rescue", lambda fx: (_stop(fx, trig=round(MARK * 0.95, 1)), fx.set_mark(MARK * 0.9)), {}),
        ("open_cond_query_fails", lambda fx: (_stop(fx), fx.inject(Fault(FaultKind.HTTP_STATUS, method="open_conditional_orders", http_status=503, times=-1))), {}),
        ("f1_delayed_arrival_3s", lambda fx: fx.inject(Fault(FaultKind.DELAYED_ARRIVAL, method="place_order", times=1, delay_ms=3_000)), {}),
        ("f1_timeout_after", lambda fx: fx.inject(Fault(FaultKind.TIMEOUT_AFTER, method="place_order", times=1)), {}),
        ("fill_delay_hide_position", lambda fx: fx.inject(Fault(FaultKind.FILL_DELAY, method="place_order", times=1, delay_ms=2_500, params={"hide_position": True})), {}),
        ("partial_fills", lambda fx: fx.inject(Fault(FaultKind.PARTIAL_FILL, method="place_order", times=5, fill_ratio=0.3)), {}),
        ("reject_4164_x5", lambda fx: fx.inject(Fault(FaultKind.REJECT, method="place_order", times=5, code=-4164)), {}),
        ("reject_forever", lambda fx: fx.inject(Fault(FaultKind.REJECT, method="place_order", times=-1, code=-2019)), {}),
        ("position_5xx_forever", lambda fx: fx.inject(Fault(FaultKind.HTTP_STATUS, method="position", http_status=503, times=-1)), {}),
        ("disconnect_all", lambda fx: fx.inject(Fault(FaultKind.DISCONNECT)), {}),
        ("rate_limit_429_then_ok", lambda fx: fx.inject(Fault(FaultKind.RATE_LIMIT, method="position", times=1, params={"retry_after_s": 5})), {}),
        ("ban_418_long", lambda fx: fx.inject(Fault(FaultKind.HTTP_STATUS, method="position", http_status=418, times=-1)), {}),
        ("auth_401", lambda fx: fx.inject(Fault(FaultKind.HTTP_STATUS, method="position", http_status=401, times=-1)), {}),
        # 주문만 즉시 '결과 모름'(도달 안 함), 조회는 정상 — 잠 없이 반복하는가?
        ("post_timeout_before_forever", lambda fx: fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="place_order", times=-1)), {}),
        ("post_503_forever", lambda fx: fx.inject(Fault(FaultKind.HTTP_STATUS, method="place_order", http_status=503, times=-1)), {}),
        ("post_timeout_before_x4", lambda fx: fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="place_order", times=4)), {}),
    ]
    res = [run(n, s, **kw) for n, s, kw in cases]
    # 숏 포지션: 아무것도 안 해야 한다
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    fx = FakeExchange(clock, mark=MARK)
    fx.plant_foreign_position(qty=-0.01)
    r = protect_without_db(fx, make_orders_config(), clock, base_url=fx.base_url,
                           sleep_ms=lambda ms: fx.tick(int(ms)))
    res.append(dict(name="short_position", result=r, orders=len(fx.calls_for("place_order")),
                    end_position=fx.position_qty))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    bad = []
    for x in res:
        print(json.dumps(x, ensure_ascii=False, default=str))
        if x["name"] == "short_position":
            if x["orders"] or x["result"] != "short":
                bad.append(x["name"])
            continue
        unsafe_end = x["end_position"] < 0 or (x["end_position"] > 0 and not x["our_stops"]
                                               and x["result"] in ("flat", "flattened", "protected"))
        if unsafe_end or not x["unique_ids"] or not x["shapes_ok"] or str(x["result"]).startswith("RUNAWAY"):
            bad.append(x["name"])
    print("BAD:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
