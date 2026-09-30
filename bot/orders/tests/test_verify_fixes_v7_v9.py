"""수정 담당(3차) 회귀 시험 — 독립 검증 V-7·V-8·V-9 (bot/orders/verify/VERIFY_REPORT.md §9.4).

V-7: protect_without_db가 주문 POST '결과 모름'(5xx·연결 끊김) 뒤 잠 없이 곧바로 다시 보냈다.
     수정: 결과 모름 뒤 백오프(0.5 → 1 → 2초, 주입한 sleep_ms로), 다음 재전송 전에 그 주문을 clientOrderId로 조회해
     거래소에 살아 있으면(NEW·부분 체결) 새로 보내지 않는다(중복 청산 방지).
V-8: quick_unprotected_check가 손절 단건 조회 실패를 '판단 보류'로 봐서 HALTED 무방비가 다음 대조까지 남았다.
     수정: HALTED에서 조회가 실패하면 fail-closed('보호 안 됨') → 포지션 > 0이면 secure_halted → 방화벽을 거친 reduceOnly 청산.
V-9: DESIGN.md §16.1 표 끊김, RUNBOOK T8 종료 코드 1 누락.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from bot.orders import gateway as G
from bot.orders import queue
from bot.orders.fake_exchange import FakeExchange, Fault, FaultKind
from bot.orders.firewall import FirewallRejected, FirewallVerdict, OrderPurpose
from bot.orders.gateway import RESCUE_UNKNOWN_BACKOFF_MS, protect_without_db
from bot.orders.tests.conftest import MARK, T_APPROVED_MS, make_approved_intent, make_orders_config
from bot.orders.tests.review_chaos_test import Monitor, make_worker, protected
from bot.orders.types import IntentState, OrderInfo, OrderStatus, OrderType, Side, parse_client_id
from bot.types import FakeClock, NS_PER_MS

S = IntentState
ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# V-7
# ---------------------------------------------------------------------------


def _rescue_setup(qty: float = 0.016):
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    fx = FakeExchange(clock, mark=MARK)
    fx.plant_foreign_position(qty=qty)
    sleeps: list[int] = []
    log: list[tuple[str, object]] = []                  # 호출·잠 순서

    def sleep(ms: int) -> None:
        sleeps.append(int(ms))
        log.append(("sleep", int(ms)))
        fx.tick(int(ms))
    return clock, fx, sleeps, log, sleep


class _Spy:
    """호출 순서를 log에 남기고, get_order 응답을 바꿀 수 있는 감싸개."""

    def __init__(self, fx: FakeExchange, log: list, get_order_override=None) -> None:
        self._fx, self._log, self._go = fx, log, get_order_override

    def __getattr__(self, name):
        a = getattr(self._fx, name)
        if not callable(a):
            return a

        def w(*x, **k):
            arg = x[0] if x else None
            self._log.append((name, getattr(arg, "client_id", arg)))   # place_order는 요청의 clientOrderId
            if name == "get_order" and self._go is not None:
                r = self._go(*x)
                if r is not NotImplemented:
                    return r
            return a(*x, **k)
        return w


@pytest.mark.parametrize("kind", ["timeout_before", "http_503"])
def test_v7_outcome_unknown_backs_off_and_queries_before_resend(kind):
    clock, fx, sleeps, log, sleep = _rescue_setup()
    f = (Fault(FaultKind.TIMEOUT_BEFORE, method="place_order", times=-1) if kind == "timeout_before"
         else Fault(FaultKind.HTTP_STATUS, method="place_order", http_status=503, times=-1))
    fx.inject(f)
    t0 = clock.now_ns() // NS_PER_MS
    res = protect_without_db(_Spy(fx, log), make_orders_config(), clock, base_url=fx.base_url, sleep_ms=sleep)
    assert res == "failed" and fx.position_qty > 0
    assert clock.now_ns() // NS_PER_MS - t0 <= G.RESCUE_DEADLINE_MS
    posts = [i for i, e in enumerate(log) if e[0] == "place_order"]
    # 수정 전: 60초 동안 호출 상한(2,000)을 넘는 폭주. 지금은 최대 2초 간격이라 약 30건.
    assert 2 <= len(posts) <= G.RESCUE_DEADLINE_MS // RESCUE_UNKNOWN_BACKOFF_MS[-1] + 3
    # 백오프: 0.5 → 1 → 2 → 2 …
    unk = [s for s in sleeps if s in RESCUE_UNKNOWN_BACKOFF_MS]
    assert unk[:4] == [500, 1000, 2000, 2000]
    # 재전송마다: 앞 POST 뒤에 잠이 있고, 앞 주문을 clientOrderId로 조회한 다음에 보낸다
    for a, b in zip(posts, posts[1:]):
        between = log[a + 1:b]
        assert any(e[0] == "sleep" and e[1] >= 500 for e in between), between
        assert ("get_order", log[a][1]) in between, between
    ids = [c.client_id for c in fx.calls if c.method == "place_order"]
    assert len(ids) == len(set(ids))


def test_v7_pending_live_order_is_not_resent():
    """결과를 모르는 청산 주문이 조회상 살아 있으면(NEW) 새로 보내지 않는다. 사라지면(없음) 그때 다시 보낸다."""
    clock, fx, sleeps, log, sleep = _rescue_setup()
    fx.inject(Fault(FaultKind.TIMEOUT_BEFORE, method="place_order", times=1))
    live_left = [2]

    def go(cid):
        if live_left[0] > 0:
            live_left[0] -= 1
            return OrderInfo(client_id=cid, exchange_order_id="1", symbol="BTCUSDT", side=Side.SELL,
                             type=OrderType.MARKET, status=OrderStatus.NEW, orig_qty=0.016, executed_qty=0.0,
                             avg_price=0.0, reduce_only=True)
        return NotImplemented

    res = protect_without_db(_Spy(fx, log, go), make_orders_config(), clock, base_url=fx.base_url, sleep_ms=sleep)
    assert res == "flattened" and fx.position_qty == 0.0
    posts = [e for e in log if e[0] == "place_order"]
    assert len(posts) == 2                                     # 살아 있는 동안 재전송 없음
    first = posts[0][1]
    assert sum(1 for e in log if e == ("get_order", first)) == 3   # NEW 2회 + 없음 1회 확인 뒤 재전송
    for c in fx.calls:
        if c.method == "place_order":
            assert c.request.reduce_only and c.request.side is Side.SELL and parse_client_id(c.client_id)


def test_v7_timeout_after_filled_is_not_resent():
    """처리됐는데 응답만 잃은 경우: 백오프 뒤 포지션 0 → 두 번째 주문 없음."""
    clock, fx, sleeps, log, sleep = _rescue_setup()
    fx.inject(Fault(FaultKind.TIMEOUT_AFTER, method="place_order", times=1))
    res = protect_without_db(fx, make_orders_config(), clock, base_url=fx.base_url, sleep_ms=sleep)
    assert res == "flattened" and fx.position_qty == 0.0
    assert len(fx.calls_for("place_order")) == 1
    assert sleeps[0] == RESCUE_UNKNOWN_BACKOFF_MS[0]


def test_v7_verifier_probe_no_runaway():
    from bot.orders.verify import rescue_edge_probe as P

    for name, f in [("post_503_forever", Fault(FaultKind.HTTP_STATUS, method="place_order", http_status=503, times=-1)),
                    ("post_timeout_before_forever", Fault(FaultKind.TIMEOUT_BEFORE, method="place_order", times=-1))]:
        r = P.run(name, lambda fx, f=f: fx.inject(f))
        assert not str(r["result"]).startswith("RUNAWAY"), r
        assert r["orders"] <= 40 and r["unique_ids"] and r["shapes_ok"] and r["end_position"] >= 0


# ---------------------------------------------------------------------------
# V-8
# ---------------------------------------------------------------------------


def _halted_unprotected(oconn, oclock, **cfg_kw):
    cfg = make_orders_config(**cfg_kw)
    fx = FakeExchange(oclock, mark=MARK)
    w = make_worker(oconn, cfg, Monitor(fx, oclock), oclock)
    w.startup()
    sid, iid = make_approved_intent(oconn)
    fx.inject(Fault(FaultKind.STOP_MISSING, times=-1))
    fx.inject(Fault(FaultKind.NO_FILL, method="place_order", times=3, after_calls=1))
    w.run_once()
    assert queue.get_intent(oconn, iid)["state"] == S.HALTED.value
    assert fx.position_qty > 0 and not protected(fx)
    fx.clear_faults()
    return fx, w, iid


def test_v8_quick_check_fail_closed_on_query_failure(oconn, oclock):
    fx, w, iid = _halted_unprotected(oconn, oclock)
    fx.inject(Fault(FaultKind.HTTP_STATUS, method="get_conditional", http_status=503, times=-1))
    row = queue.get_intent(oconn, iid)
    assert w.gw.quick_unprotected_check(row) is True           # 수정 전: False(판단 보류)
    # 포지션 조회까지 실패하면 청산 수량을 모른다 → False
    fx.inject(Fault(FaultKind.HTTP_STATUS, method="position", http_status=503, times=1))
    assert w.gw.quick_unprotected_check(row) is False
    # EXITING은 판단 보류 그대로
    ex_row = dict(row)
    ex_row["state"] = S.EXITING.value
    assert w.gw.quick_unprotected_check(ex_row) is False


def test_v8_quick_check_respects_rate_limit_window(oconn, oclock):
    fx, w, iid = _halted_unprotected(oconn, oclock)
    fx.inject(Fault(FaultKind.RATE_LIMIT, method="get_conditional", times=1, params={"retry_after_s": 5}))
    n = len(fx.calls)
    assert w.gw.quick_unprotected_check(queue.get_intent(oconn, iid)) is False
    assert [c.method for c in fx.calls[n:]] == ["get_conditional"]       # 429 뒤 포지션 조회도 보내지 않는다


@pytest.mark.parametrize("interval", [10, 30])
def test_v8_halted_get_conditional_failure_flattens_within_loop_via_firewall(oconn, oclock, monkeypatch, interval):
    fx, w, iid = _halted_unprotected(oconn, oclock, reconcile_interval_s=interval)
    fx.inject(Fault(FaultKind.HTTP_STATUS, method="get_conditional", http_status=503, times=-1))
    seen: list[OrderPurpose] = []
    real = G.enforce_order

    def spy(req, purpose, ctx):
        seen.append(purpose)
        return real(req, purpose, ctx)
    monkeypatch.setattr(G, "enforce_order", spy)
    t0 = oclock.now_ns() // NS_PER_MS
    n = len(fx.calls)
    t_safe = None
    for _ in range(15):
        fx.tick(2_000)
        w.run_once()
        if protected(fx):
            t_safe = oclock.now_ns() // NS_PER_MS - t0
            break
    assert t_safe is not None and t_safe <= 5_000                         # 수정 전 8.3초(10초 주기)·28.3초(30초 주기)
    assert fx.position_qty == 0.0
    posts = [c for c in fx.calls[n:] if c.method == "place_order"]
    assert posts and len(seen) >= len(posts) and set(seen) == {OrderPurpose.FLATTEN}
    for c in posts:
        assert c.request.reduce_only and c.request.side is Side.SELL and c.request.type is OrderType.MARKET


def test_v8_fail_closed_flatten_still_blocked_by_firewall(oconn, oclock, monkeypatch):
    fx, w, iid = _halted_unprotected(oconn, oclock)
    fx.inject(Fault(FaultKind.HTTP_STATUS, method="get_conditional", http_status=503, times=-1))

    def deny(req, purpose, ctx):
        raise FirewallRejected(FirewallVerdict(ok=False, purpose=purpose, violations=("test_deny",), detail={}))
    monkeypatch.setattr(G, "enforce_order", deny)
    n = len(fx.calls)
    for _ in range(3):
        fx.tick(2_000)
        w.run_once()
    assert not [c for c in fx.calls[n:] if c.method == "place_order"]    # 방화벽이 막으면 보내지 않는다
    assert fx.position_qty > 0


def test_v8_verifier_probe_query_failure_cases_within_5s():
    from bot.orders.verify import halted_query_fail_probe as P

    gc = lambda: Fault(FaultKind.HTTP_STATUS, method="get_conditional", http_status=503, times=-1)  # noqa: E731
    oc = lambda: Fault(FaultKind.HTTP_STATUS, method="open_conditional_orders", http_status=503, times=-1)  # noqa: E731
    for faults, iv in [([gc()], 30), ([gc()], 10), ([gc(), oc()], 30)]:
        r = P.run("x", faults, iv)
        assert r["protected_after_ms"] is not None and r["protected_after_ms"] <= 5_000, r


# ---------------------------------------------------------------------------
# V-9
# ---------------------------------------------------------------------------


def test_v9_design_16_1_table_is_contiguous():
    text = (ROOT / "bot" / "orders" / "DESIGN.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    idx = {m: i for i, l in enumerate(lines) for m in re.findall(r"^\| (R-\d+) \|", l)}
    assert "R-14" in idx and "R-15" in idx and "R-16" in idx
    first = min(idx.values())
    last = max(idx.values())
    block = lines[first:last + 1]
    assert all(l.startswith("|") for l in block), "§16.1 표 안에 빈 줄·표 아닌 줄이 있다"
    # 머리글 구분선이 표 첫 행 바로 위에 있다
    j = first - 1
    while lines[j].startswith("| R-") or lines[j].startswith("| "):
        if re.match(r"^\|[\s:-]+\|", lines[j]):
            break
        j -= 1
    assert re.match(r"^\|[\s:|-]+$", lines[j])


def test_v9_runbook_t8_mentions_exit_code_1():
    text = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    sec = text[text.index("### T8."):text.index("### T9.")]
    rows = [l for l in sec.splitlines() if l.startswith("| `orders`가 종료 코드")]
    assert len(rows) == 1, "RUNBOOK T8 시작 거부 행을 찾지 못함"
    row = rows[0]
    assert "1·2·3" in row and "종료 1" in row and "startup:" in row, row
