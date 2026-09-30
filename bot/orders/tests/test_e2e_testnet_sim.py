"""TESTNET 전 과정 시뮬레이션(E2E) — 통합 담당 (bot/orders/DESIGN.md §15.5).

A(엔진·텔레그램 버튼)와 B(워커·게이트웨이)가 **같은 DB 파일을 각자 연결**로 쓰고, 거래소는 FakeExchange다.
- 신호 → 카드 → [승인]·[확인](telegram_ui.handle_callback) → QUEUED → B → STOP_VERIFIED → 손절 발동 → CLOSED(stop)
  → B의 알림이 outbox를 거쳐 A의 텔레그램 전송으로 나간다.
- 강제 종료(객체 폐기 + 연결 닫기)·재시작(새 Worker + 같은 DB 파일): 전송 기록 전 / 전송 후 응답 전 / 체결 후 손절 전 /
  손절 접수 후 확인 전 / 손절 확인 후 / EXITING 중(청산 전송 전·후). 매번 최종 거래소 상태가
  '포지션 0 또는 손절 있는 포지션'이고 진입 POST ≤ 1.
- 합성 시장 260일을 A의 일일 사이클(진입·EXIT 판단)과 B로 끝까지 돌린다(추세 청산·손절 모두 발생, T0 없음).
- A에 거래 키 없음(설정·compose), T0 해제는 텔레그램으로 안 됨.
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

import numpy as np
import pytest

from bot import db
from bot import telegram_ui as tu
from bot.config import ConfigError, load_secrets
from bot.engine import Engine
from bot.orders import queue
from bot.orders import worker as W
from bot.orders.control import ControlState
from bot.orders.fake_exchange import FakeExchange
from bot.orders.tests.test_gateway import Crash, Hooked
from bot.orders.types import (
    CONDITIONAL_ACTIVE_STATUSES,
    INTENT_LIVE,
    IdPurpose,
    IntentState,
    OrderType,
    Side,
    make_client_id,
)
from bot.tests.conftest import (
    ALLOWED_CHAT_ID,
    ALLOWED_USER_ID,
    T_DECISION_NS,
    FakeTransport,
    frame_market_from,
    insert_test_signal,
    make_config,
    run_async,
    trend_market,
)
from bot.types import NS_PER_MIN, NS_PER_MS, CallbackAction, FakeClock, Mode, make_callback_data

S = IntentState
CTL = ControlState(manual_halt=False)
MARK = 60_000.0
REPO = Path(__file__).resolve().parents[3]


def now_ms(clock) -> int:
    return clock.now_ns() // NS_PER_MS


# ---------------------------------------------------------------------------
# 시스템 도우미: A(엔진) + B(워커) + 거래소(가짜)
# ---------------------------------------------------------------------------


class NoMarket:
    def daily_bars(self, until_ns):
        raise AssertionError("이 시험에서는 사이클을 돌리지 않는다")

    minute_bars = funding = daily_bars

    def server_time_ns(self):
        return None


class System:
    """테스트넷 서버 한 대 흉내: A·B 프로세스(각자 DB 연결), 거래소, 텔레그램 가짜 전송."""

    def __init__(self, tmp_path: Path, clock: FakeClock, *, market=None, fx: FakeExchange | None = None) -> None:
        self.tmp = tmp_path
        self.clock = clock
        self.cfg = make_config(tmp_path, mode="testnet", **{
            "db_path": str(tmp_path / "data" / "testnet.sqlite3"), "claude.enabled": False,
            "orders.api_key_file": str(tmp_path / "b" / "binance_api_key"),
            "orders.private_key_file": str(tmp_path / "b" / "binance_ed25519_private_key"),
            "orders.control_file": str(tmp_path / "b" / "orders_control.toml"),
            "orders.r_capital_usdt": 10_000.0})
        self.db_path = Path(self.cfg.db_path)
        self.conn_a = db.connect(self.db_path, mode=Mode.TESTNET, now_ms=now_ms(clock))
        self.engine = Engine(self.conn_a, self.cfg, market or NoMarket(), None, clock)
        self.transport = FakeTransport()
        self.fx = fx or FakeExchange(clock, mark=MARK)
        self.control = CTL
        self.conn_b: object | None = None
        self.worker: W.Worker | None = None
        self.restarts = 0

    # --- B 프로세스 ---
    def start_b(self, *, before: dict | None = None, after: dict | None = None,
                crash_in_startup: bool = False) -> W.Worker:
        """B 시작(새 연결 + 새 Worker + recover). before/after = 거래소 호출 훅(Hooked) — 기본은 복구가 끝난 뒤 켠다
        (crash_in_startup=True면 복구 중에도)."""
        self.conn_b = db.connect(self.db_path, mode=Mode.TESTNET, now_ms=now_ms(self.clock))
        ex = Hooked(self.fx)
        self.worker = W.Worker(self.conn_b, self.cfg.orders, ex, self.clock, control_loader=lambda: self.control)
        if crash_in_startup:
            ex.before, ex.after = dict(before or {}), dict(after or {})
        self.worker.startup()
        ex.before, ex.after = dict(before or {}), dict(after or {})
        return self.worker

    def kill_b(self) -> None:
        """강제 종료: 객체 폐기 + 연결 닫기(커밋되지 않은 것은 사라진다)."""
        if self.conn_b is not None:
            self.conn_b.close()
        self.conn_b = None
        self.worker = None

    def restart_b(self, *, after_ms: int = 10_000) -> W.Worker:
        self.kill_b()
        self.clock.advance(after_ms * NS_PER_MS)        # compose 재시작까지
        self.restarts += 1
        return self.start_b()

    # --- A 프로세스(텔레그램 버튼) ---
    def press(self, action: CallbackAction, sid: str, mid: int) -> tu.CallbackOutcome:
        ctx = tu.CallbackContext(callback_query_id=f"q{sid}{action.value}", update_id=1, from_user_id=ALLOWED_USER_ID,
                                 chat_id=ALLOWED_CHAT_ID, chat_type="private", message_id=mid,
                                 data=make_callback_data(action, sid))
        with self.engine.lock:
            return tu.handle_callback(self.engine, self.conn_a, self.cfg, ctx, now_ms(self.clock))

    def card_approve_confirm(self, *, n: int = 20, decision_ns: int | None = None) -> str:
        """카드 전송 → [승인] → [확인]. A가 QUEUED를 같은 트랜잭션으로 넣는다."""
        dec = decision_ns if decision_ns is not None else (self.clock.now_ns() // (86_400 * 10**9)) * 86_400 * 10**9 + 60 * 10**9
        sid = insert_test_signal(self.conn_a, n=n, decision_ns=dec, mode=Mode.TESTNET)
        run_async(tu.send_outgoing(self.transport, self.engine, self.engine.unsent_cards()))
        mid = self.transport.sent[-1].message_id
        assert db.get_signal(self.conn_a, sid)["state"] == "CARD_SENT"
        assert self.press(CallbackAction.APPROVE, sid, mid).result
        self.press(CallbackAction.CONFIRM, sid, mid)
        assert db.get_signal(self.conn_a, sid)["state"] == "APPROVED"
        assert queue.intent_for_signal(self.conn_a, sid)["state"] == "QUEUED"
        return sid

    def a_deliver(self) -> list[str]:
        """A의 텔레그램 전송(outbox 포함) — B의 알림이 여기로 나간다."""
        before = len(self.transport.sent)
        run_async(tu.send_outgoing(self.transport, self.engine, []))
        return [m.text for m in self.transport.sent[before:]]

    # --- 단언 ---
    def intent(self, sid: str):
        return queue.intent_for_signal(self.conn_a, sid)

    def e1_posts(self, sid: str) -> int:
        return self.fx.post_count("place_order", client_id=make_client_id(sid, IdPurpose.ENTRY))

    def assert_safe(self, sid: str | None = None) -> None:
        """거래소 최종 상태: 포지션 0, 또는 롱 포지션 + 우리 closePosition 손절(SELL STOP_MARKET, NEW, 트리거 < 마크)."""
        q = self.fx.position_qty
        active = [c for c in self.fx.all_conditionals() if c.status in CONDITIONAL_ACTIVE_STATUSES]
        if q != 0:
            assert q > 0, "숏 포지션"
            ok = [c for c in active if c.side is Side.SELL and c.type is OrderType.STOP_MARKET and c.close_position
                  and c.trigger_price < self.fx.mark and c.client_algo_id.startswith("sig-")]
            assert ok, f"손절 없는 포지션 qty={q}"
        live = queue.intents_in_states(self.conn_a, INTENT_LIVE)
        assert len(live) <= 1
        if sid is not None:
            assert self.e1_posts(sid) <= 1


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T_DECISION_NS + 20 * NS_PER_MIN)


@pytest.fixture
def system(tmp_path, clock) -> System:
    return System(tmp_path, clock)


# ---------------------------------------------------------------------------
# 1. 전 과정: 승인 → 주문 → 손절 → 손절 발동 → CLOSED, 알림 왕복
# ---------------------------------------------------------------------------


def test_full_path_stop_fires(system: System, clock):
    system.start_b()
    sid = system.card_approve_confirm()
    res = system.worker.run_once()
    assert res.final_state is S.STOP_VERIFIED and res.unprotected_ms is not None and res.unprotected_ms <= 5000
    row = system.intent(sid)
    assert db.get_signal(system.conn_a, sid)["state"] == "FILLED"
    assert system.fx.post_count("place_order") == 1 and system.fx.post_count("place_conditional") == 1
    system.assert_safe(sid)
    # A가 보유를 안다(/status, /positions)
    assert "거래소(데모) 보유 1개" in system.engine.status_text()
    # 가격 하락 → 거래소 손절 발동 → 대조기가 CLOSED(stop)
    system.fx.set_mark(float(row["stop_price"]) - 50.0)
    assert system.fx.position_qty == 0
    clock.advance(31_000 * NS_PER_MS)
    system.worker.run_once()
    row = system.intent(sid)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "stop"
    assert db.get_signal(system.conn_a, sid)["state"] == "CLOSED"
    assert not queue.halts(system.conn_a)
    # B의 알림(체결·청산)이 A의 텔레그램 전송으로 나간다
    texts = system.a_deliver()
    assert texts and all(t.startswith("[TESTNET]") for t in texts)
    system.assert_safe(sid)


def test_full_path_trend_exit_and_second_signal(system: System, clock):
    system.start_b()
    sid = system.card_approve_confirm(n=55)
    assert system.worker.run_once().final_state is S.STOP_VERIFIED
    # 보유 중 다른 하위 시스템 신호: 카드에 '보유 중(1포지션)' 표시, 승인해도 B가 position_exists로 거부
    s2 = system.card_approve_confirm(n=20)
    assert "보유 중(1포지션)" in system.transport.sent[-3].text or any(
        "보유 중(1포지션)" in m.text for m in system.transport.sent)
    system.worker.run_once()
    assert system.intent(s2)["state_reason"] == "position_exists"
    assert db.get_signal(system.conn_a, s2)["state"] == "SKIPPED" and system.e1_posts(s2) == 0
    # A의 EXIT 판단이 하는 일(queue.request_exit, due = 판단 + 30분)
    t = now_ms(clock)
    assert queue.request_exit(system.conn_a, sid, exit_signal_close_ms=t, exit_due_ms=t + 30 * 60_000, now_ms=t)
    system.worker.run_once()
    assert system.intent(sid)["state"] == "STOP_VERIFIED"
    clock.advance(30 * 60_000 * NS_PER_MS)
    system.worker.run_once()
    row = system.intent(sid)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "trend" and row["exit_price"] > 0
    assert system.fx.position_qty == 0
    assert not [c for c in system.fx.all_conditionals() if c.status in CONDITIONAL_ACTIVE_STATUSES]  # sl 취소됨
    assert db.get_signal(system.conn_a, sid)["state"] == "CLOSED"
    assert not queue.halts(system.conn_a)


# ---------------------------------------------------------------------------
# 2. 강제 종료·재시작 지점별
# ---------------------------------------------------------------------------


def _crash_before(method: str, *, suffix: str | None = None):
    def hook(*args):
        if suffix is None or (args and getattr(args[0], "client_id", getattr(args[0], "client_algo_id", "")).endswith(suffix)):
            raise Crash(method)
    return hook


def _crash_after(method: str, *, suffix: str | None = None):
    def hook(res, *args):
        if suffix is None or (args and getattr(args[0], "client_id", getattr(args[0], "client_algo_id", "")).endswith(suffix)):
            raise Crash(method)
    return hook


# (이름, before 훅, after 훅, 재시작 뒤 기대 상태, T0 사유(있으면), 진입 POST 수)
CRASH_POINTS = [
    ("before_send_record", {"mark_price": _crash_before("mark_price")}, {},
     S.REJECTED, None, 0),
    ("after_send_before_response", {}, {"place_order": _crash_after("place_order", suffix="-e1")},
     S.FAILED_FLATTENED, "restart_unprotected", 1),
    ("after_fill_before_stop", {"place_conditional": _crash_before("place_conditional")}, {},
     S.FAILED_FLATTENED, "restart_unprotected", 1),
    ("after_stop_placed_before_verify", {}, {"place_conditional": _crash_after("place_conditional")},
     S.STOP_VERIFIED, None, 1),
]


@pytest.mark.parametrize("name, before, after, expect, halt, e1", CRASH_POINTS, ids=[c[0] for c in CRASH_POINTS])
def test_crash_restart_during_entry(system: System, clock, name, before, after, expect, halt, e1):
    system.start_b(before=before, after=after)
    sid = system.card_approve_confirm()
    with pytest.raises(Crash):
        system.worker.run_once()
    system.restart_b()                                  # 훅 없는 새 B(같은 DB 파일)
    row = system.intent(sid)
    assert row["state"] == expect.value, (name, row["state"], row["state_reason"])
    reasons = [r["reason"] for r in queue.halts(system.conn_a)]
    if halt is None:
        assert not reasons, reasons
    else:
        assert halt in reasons
    assert system.e1_posts(sid) == e1
    system.assert_safe(sid)
    # 재시작 뒤 몇 바퀴 더: 주문이 더 나가지 않고 안전 유지
    for _ in range(3):
        clock.advance(31_000 * NS_PER_MS)
        system.worker.run_once()
        system.assert_safe(sid)
    assert system.e1_posts(sid) == e1
    if expect is S.REJECTED:
        assert row["state_reason"] == "restart_before_send" and system.fx.position_qty == 0
        assert db.get_signal(system.conn_a, sid)["state"] == "SKIPPED"
    if expect is S.FAILED_FLATTENED:
        assert system.fx.position_qty == 0 and db.get_signal(system.conn_a, sid)["state"] == "CLOSED"
    if expect is S.STOP_VERIFIED:
        assert system.fx.position_qty > 0


def test_crash_after_stop_verified_keeps_protected_position(system: System, clock):
    system.start_b()
    sid = system.card_approve_confirm()
    assert system.worker.run_once().final_state is S.STOP_VERIFIED
    posts = (system.fx.post_count("place_order"), system.fx.post_count("place_conditional"))
    system.restart_b(after_ms=60_000)
    assert system.intent(sid)["state"] == "STOP_VERIFIED"
    assert (system.fx.post_count("place_order"), system.fx.post_count("place_conditional")) == posts
    assert not queue.halts(system.conn_a)
    system.assert_safe(sid)
    # 꺼져 있는 동안 손절이 발동했다면 재시작 뒤 대조가 CLOSED(stop)
    system.kill_b()
    system.fx.set_mark(float(system.intent(sid)["stop_price"]) - 10.0)
    clock.advance(60_000 * NS_PER_MS)
    system.start_b()
    row = system.intent(sid)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "stop" and not queue.halts(system.conn_a)


@pytest.mark.parametrize("when", ["before_x1", "after_x1"])
def test_crash_restart_during_exiting(system: System, clock, when):
    system.start_b()
    sid = system.card_approve_confirm()
    assert system.worker.run_once().final_state is S.STOP_VERIFIED
    system.kill_b()
    hook = ({"place_order": _crash_before("place_order", suffix="-x1")}, {}) if when == "before_x1" else \
        ({}, {"place_order": _crash_after("place_order", suffix="-x1")})
    system.start_b(before=hook[0], after=hook[1])
    t = now_ms(clock)
    queue.request_exit(system.conn_a, sid, exit_signal_close_ms=t, exit_due_ms=t, now_ms=t)
    with pytest.raises(Crash):
        system.worker.run_once()
    assert system.intent(sid)["state"] == "EXITING"
    system.restart_b()
    row = system.intent(sid)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "trend", (row["state"], row["state_reason"])
    assert system.fx.position_qty == 0
    assert not [c for c in system.fx.all_conditionals() if c.status in CONDITIONAL_ACTIVE_STATUSES]
    assert system.e1_posts(sid) == 1 and not queue.halts(system.conn_a)
    system.assert_safe(sid)


def test_crash_during_restart_recovery_is_still_safe(system: System, clock):
    """복구(recover) 중 다시 죽어도: 체결 후 손절 전 → 재시작 중 청산 전송 직전 죽음 → 다시 재시작 → 청산 + T0."""
    system.start_b(before={"place_conditional": _crash_before("place_conditional")})
    sid = system.card_approve_confirm()
    with pytest.raises(Crash):
        system.worker.run_once()
    system.kill_b()
    clock.advance(5_000 * NS_PER_MS)
    with pytest.raises(Crash):
        system.start_b(before={"place_order": _crash_before("place_order", suffix="-f1")}, crash_in_startup=True)
    assert system.fx.position_qty > 0                   # 아직 무방비(다음 재시작이 청산)
    system.restart_b()
    row = system.intent(sid)
    assert row["state"] == "FAILED_FLATTENED" and system.fx.position_qty == 0
    assert "restart_unprotected" in [r["reason"] for r in queue.halts(system.conn_a)]
    assert system.e1_posts(sid) == 1
    system.assert_safe(sid)


# ---------------------------------------------------------------------------
# 3. T0 해제는 텔레그램으로 안 됨 / A에 거래 키 없음
# ---------------------------------------------------------------------------


def test_t0_release_only_via_server_control_file(system: System, clock):
    system.start_b(before={"place_conditional": _crash_before("place_conditional")})
    s1 = system.card_approve_confirm()
    with pytest.raises(Crash):
        system.worker.run_once()
    system.restart_b()                                    # 청산 + T0 restart_unprotected
    hid = [int(r["halt_id"]) for r in queue.halts(system.conn_a)][0]
    # 텔레그램: /resume·/status는 T0에 영향이 없다. 해제 명령은 없다.
    assert set(tu.COMMANDS) == {"status", "positions", "pause", "resume", "help"}
    for text in ("/resume", "/release", f"/release {hid}", "/unhalt"):
        with system.engine.lock:
            tu.handle_command(system.engine, system.conn_a, system.cfg, from_user_id=ALLOWED_USER_ID,
                              chat_id=ALLOWED_CHAT_ID, chat_type="private", text=text, now_ms=now_ms(clock))
    st = system.engine.status_text()
    assert f"#{hid}" in st and "제어 파일" in st
    clock.advance(24 * 3600_000 * NS_PER_MS)
    s2 = system.card_approve_confirm(n=55)
    system.worker.run_once()
    assert system.intent(s2)["state_reason"] == "halted" and system.e1_posts(s2) == 0
    # 서버 제어 파일에서 해제 → 다음 신호 정상
    system.control = ControlState(manual_halt=False, released=frozenset({hid}), ref="orders_control.toml@1")
    s3 = system.card_approve_confirm(n=100)
    system.worker.run_once()
    assert system.intent(s3)["state"] == "STOP_VERIFIED"
    rel = system.conn_a.execute("SELECT * FROM order_halt_releases").fetchall()
    assert [int(r["halt_id"]) for r in rel] == [hid]


def test_a_process_has_no_trading_keys(system: System, tmp_path):
    # 설정: A의 load_secrets는 거래 키가 보이면 거부
    b = tmp_path / "b"
    b.mkdir(exist_ok=True)
    (b / "binance_ed25519_private_key").write_text("x")
    with pytest.raises(ConfigError, match="프로세스 A"):
        load_secrets(system.cfg)
    # 코드: A 쪽 모듈은 거래소 클라이언트를 import하지 않는다
    pat = re.compile(r"^\s*(from\s+bot\.orders(\.binance_client|\.worker|\.gateway)?\s+import\s+(.*)|"
                     r"import\s+bot\.orders\.(binance_client|worker|gateway))", re.M)
    for mod in ("bot/engine.py", "bot/main.py", "bot/telegram_ui.py", "bot/config.py", "bot/db.py"):
        text = (REPO / mod).read_text(encoding="utf-8")
        for m in pat.finditer(text):
            # A가 쓰는 것은 queue·types뿐(키를 읽는 binance_client·worker·gateway는 B 전용)
            assert m.group(2) is None and m.group(4) is None, (mod, m.group(0))
            assert set(x.strip().split(" as ")[0] for x in (m.group(3) or "").split(",")) <= {"queue", "types"}, \
                (mod, m.group(0))


def _compose_services(text: str) -> dict[str, str]:
    """docker-compose.yml의 services 블록을 서비스별 원문으로(PyYAML 없이, 들여쓰기 2칸 기준)."""
    body = text.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    out: dict[str, list[str]] = {}
    cur = None
    for line in body.splitlines():
        m = re.match(r"^  ([a-z_]+):\s*$", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def _active(block: str) -> str:
    return "\n".join(l for l in block.splitlines() if not l.strip().startswith("#"))


def test_compose_trading_keys_only_in_orders_service():
    text = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    svc = _compose_services(text)
    assert {"bot", "orders", "replay"} <= set(svc)
    bot, orders = _active(svc["bot"]), _active(svc["orders"])
    for name in ("binance_api_key", "binance_ed25519_private_key", "orders_control", "/control"):
        assert name not in bot and name not in _active(svc["replay"])
    assert "- binance_api_key" in orders and "- binance_ed25519_private_key" in orders
    assert "orders_control.toml:/control/orders_control.toml:ro" in orders
    assert "telegram_bot_token" not in orders and "anthropic_api_key" not in orders
    assert 'profiles: ["testnet"]' in orders and "bot.orders.worker" in orders
    for block in (bot, orders):
        assert "ports:" not in block and "read_only: true" in block and "cap_drop: [ALL]" in block
        assert "no-new-privileges:true" in block
    env_lines = orders.split("environment:", 1)[1].split("volumes:", 1)[0]
    assert "KEY" not in env_lines and "SECRET" not in env_lines
    top = text.split("\nsecrets:\n")[-1]
    assert "./secrets/binance_api_key" in top and "./secrets/binance_ed25519_private_key" in top


def test_example_configs_load(tmp_path):
    from bot.config import config_from_dict
    import tomllib

    raw = tomllib.loads((REPO / "config" / "bot.testnet.example.toml").read_text(encoding="utf-8"))
    raw["telegram"]["allowed_user_id"] = ALLOWED_USER_ID
    raw["telegram"]["allowed_chat_id"] = ALLOWED_CHAT_ID
    cfg = config_from_dict(raw)
    assert cfg.mode is Mode.TESTNET and cfg.orders.env.value == "demo"
    assert cfg.orders.control_file == "/control/orders_control.toml"
    from bot.orders.control import parse_control

    c = parse_control((REPO / "config" / "orders_control.example.toml").read_text(encoding="utf-8"))
    assert c.error is None and c.manual_halt is False and not c.released


# ---------------------------------------------------------------------------
# 4. 합성 시장 260일: A의 일일 사이클(진입·EXIT) + 승인 + B + 거래소 손절
# ---------------------------------------------------------------------------


def test_long_simulation_engine_cycles_with_orders(tmp_path):
    m = trend_market()
    daily = m.bars["1d"]
    ex_close_ns = m.exec_bars["close_ns"].to_numpy()
    ex_close = m.exec_bars["close"].to_numpy()

    def mark_at(t_ns: int) -> float:
        i = int(np.searchsorted(ex_close_ns, t_ns, side="right")) - 1
        return float(ex_close[max(i, 0)])

    clock = FakeClock(int(daily["close_ns"].iloc[0]))
    fx = FakeExchange(clock, mark=float(ex_close[0]))
    system = System(tmp_path, clock, market=frame_market_from(m, clock), fx=fx)
    engine = system.engine
    system.start_b()
    decisions = daily["close_ns"].to_numpy()[1:] + 60 * 10**9
    restart_days = set(range(40, len(decisions), 45))       # 가끔 B를 강제 재시작(보유 중일 수도 있음)
    for day, dec in enumerate(decisions):
        clock.set(max(clock.now_ns(), int(dec)))
        fx.set_mark(mark_at(clock.now_ns()))
        run_async(tu.send_outgoing(system.transport, engine, engine.tick()))
        rep = engine.run_daily_cycle()
        run_async(tu.send_outgoing(system.transport, engine, rep.outgoing))
        clock.set(max(clock.now_ns(), int(dec) + 30 * NS_PER_MIN))
        for sid in rep.created_signal_ids:
            if engine.request_confirm(sid):
                engine.confirm(sid)
        if day in restart_days:
            system.restart_b(after_ms=5_000)
        for h in range(0, 23 * 60, 60):
            clock.set(max(clock.now_ns(), int(dec) + 30 * NS_PER_MIN + h * NS_PER_MIN))
            fx.set_mark(mark_at(clock.now_ns()))
            system.worker.run_once()
            system.assert_safe()
    c = system.conn_a
    rows = list(c.execute("SELECT * FROM order_intents"))
    outcome = collections.Counter((r["state"], r["exit_reason"] or r["state_reason"]) for r in rows)
    assert outcome[("CLOSED", "trend")] >= 1 and outcome[("CLOSED", "stop")] >= 1, outcome
    assert not queue.halts(c), [(r["reason"], r["detail_json"]) for r in queue.halts(c)]
    assert set(s for s, _ in outcome) <= {"CLOSED", "REJECTED", "STOP_VERIFIED", "EXITING", "NOT_FILLED"}
    for r in rows:                                          # 신호당 진입 POST ≤ 1, 체결된 것만 CLOSED
        assert system.e1_posts(r["signal_id"]) <= 1
        sig = db.get_signal(c, r["signal_id"])
        want = {"CLOSED": "CLOSED", "REJECTED": "SKIPPED", "NOT_FILLED": "SKIPPED",
                "STOP_VERIFIED": "FILLED", "EXITING": "FILLED"}[r["state"]]
        assert sig["state"] == want
    # 거래소 사실과 DB가 맞다
    live = queue.live_intent(c)
    if live is None:
        assert fx.position_qty == 0
    else:
        assert abs(fx.position_qty - float(live["filled_qty"])) < 1e-9
    # TESTNET은 모의 체결을 쓰지 않는다
    assert c.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0] == 0
    # B 알림이 A 텔레그램으로 나갔다(outbox 비어 있음)
    system.a_deliver()
    assert c.execute("SELECT COUNT(*) FROM outbox WHERE sent_ms IS NULL AND dropped_ms IS NULL").fetchone()[0] == 0
    assert any("[TESTNET]" in m.text and "추세 청산" in m.text for m in system.transport.sent)
