"""bot/orders 시험 공용 도우미 — 설계 담당 소유 (bot/orders/DESIGN.md §15).

제공
- 상수: T_MS(판단 시각 ms), T_APPROVED_MS(판단 + 30분), MARK(기본 마크 60,000), ATR(기본 ATR20 1,500)
- 모드: TEST_MODE(Mode.TESTNET이 생기면 그것, 아니면 PAPER — 통합 전에도 시험이 돌게)
- fixture: oconn(메모리 DB + queue 스키마), oclock(FakeClock = 승인 + 5초), ocfg(OrdersConfig 기본), control_ok,
  fake_exchange(FakeExchange — 구현 전이면 skip)
- 함수: make_orders_config(**kw), approve_signal(conn, sid, approved_ms), make_approved_intent(conn, …),
  good_account(**kw), good_rules(**kw), good_balance(avail), position(qty, price), fw_ctx(…), write_control(path, text)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from bot import db
from bot.orders import queue
from bot.orders.control import ControlState
from bot.orders.firewall import FirewallContext
from bot.orders.types import (
    MAX_LEVERAGE,
    PRICE_TICK,
    QTY_STEP,
    SYMBOL,
    AccountConfig,
    Balance,
    ExchangeEnv,
    OrdersConfig,
    PositionInfo,
    SymbolRules,
    env_base_url,
)
from bot.tests.conftest import T_DECISION_NS, T_MS, insert_test_signal
from bot.types import FakeClock, Mode, NS_PER_MS, SignalState

TEST_MODE: Mode = getattr(Mode, "TESTNET", Mode.PAPER)
T_APPROVED_MS = T_MS + 30 * 60 * 1000
MARK = 60_000.0
ATR = 1_500.0
DEMO_URL = env_base_url(ExchangeEnv.DEMO)


def make_orders_config(**kw: Any) -> OrdersConfig:
    base: dict[str, Any] = dict(r_capital_usdt=10_000.0)
    base.update(kw)
    return OrdersConfig(**base)


@pytest.fixture
def ocfg() -> OrdersConfig:
    return make_orders_config()


@pytest.fixture
def oconn():
    c = db.connect(":memory:", mode=TEST_MODE, now_ms=T_MS)
    queue.ensure_schema(c)
    yield c
    c.close()


@pytest.fixture
def oclock() -> FakeClock:
    return FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)


@pytest.fixture
def control_ok() -> ControlState:
    return ControlState(manual_halt=False, released=frozenset(), error=None, ref="test")


def approve_signal(conn, signal_id: str, approved_ms: int = T_APPROVED_MS) -> None:
    """NEW → CARD_SENT → CONFIRM_PENDING → APPROVED (엔진 없이 전이만)."""
    S = SignalState
    assert db.transition_signal(conn, signal_id, S.NEW, S.CARD_SENT, now_ms=approved_ms - 2000, actor="TEST",
                                fields={"card_sent_ms": approved_ms - 2000, "tg_message_id": 1})
    assert db.transition_signal(conn, signal_id, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=approved_ms - 1000,
                                actor="TEST", fields={"confirm_requested_ms": approved_ms - 1000,
                                                      "confirm_expires_ms": approved_ms + 59_000})
    assert db.transition_signal(conn, signal_id, S.CONFIRM_PENDING, S.APPROVED, now_ms=approved_ms, actor="TEST",
                                fields={"approved_ms": approved_ms,
                                        "approval_latency_ms": approved_ms - T_DECISION_NS // NS_PER_MS})


def make_approved_intent(conn, *, n: int = 20, atr20: float = ATR, approved_ms: int = T_APPROVED_MS,
                         decision_ns: int = T_DECISION_NS) -> tuple[str, int]:
    """APPROVED 신호 + QUEUED 의도. (signal_id, intent_id)."""
    sid = insert_test_signal(conn, n=n, atr20=atr20, decision_ns=decision_ns, mode=TEST_MODE)
    with db.transaction(conn):
        approve_signal(conn, sid, approved_ms)
        iid = queue.enqueue(conn, signal_id=sid, now_ms=approved_ms)
    assert iid is not None
    return sid, iid


def good_account(**kw: Any) -> AccountConfig:
    base: dict[str, Any] = dict(dual_side_position=False, multi_assets_margin=False, leverage=MAX_LEVERAGE,
                                margin_type="isolated", can_trade=True, can_withdraw=False)
    base.update(kw)
    return AccountConfig(**base)


def good_rules(**kw: Any) -> SymbolRules:
    base: dict[str, Any] = dict(symbol=SYMBOL, tick_size=PRICE_TICK, step_size=QTY_STEP, min_qty=QTY_STEP,
                                min_notional=5.0, status="TRADING")
    base.update(kw)
    return SymbolRules(**base)


def good_balance(available: float = 10_000.0) -> Balance:
    return Balance(asset="USDT", wallet_balance=available, available_balance=available)


def position(qty: float = 0.0, price: float = 0.0) -> PositionInfo:
    return PositionInfo(symbol=SYMBOL, qty=qty, entry_price=price, leverage=MAX_LEVERAGE, margin_type="isolated")


def fw_ctx(cfg: OrdersConfig, signal_id: str, **kw: Any) -> FirewallContext:
    base: dict[str, Any] = dict(cfg=cfg, client_base_url=DEMO_URL, signal_id=signal_id, mark_price=MARK,
                                position_qty=0.0, account=good_account(), rules=good_rules(),
                                balance=good_balance())
    base.update(kw)
    return FirewallContext(**base)


def write_control(path: Path, text: str, mode: int = 0o600) -> Path:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)
    return path


@pytest.fixture
def fake_exchange(oclock):
    """FakeExchange(구현 전이면 이 fixture를 쓰는 시험은 skip)."""
    from bot.orders.fake_exchange import FakeExchange

    try:
        return FakeExchange(oclock, mark=MARK)
    except NotImplementedError:
        pytest.skip("fake_exchange 미구현")
