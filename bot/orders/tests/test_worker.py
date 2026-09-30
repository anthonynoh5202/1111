"""프로세스 B 루프(worker)·TESTNET 연동(config·db·engine)·selftest 시험 — 통합 담당.

거래소는 전부 FakeExchange. 전 과정(A 엔진 → 큐 → B → 거래소)·강제 종료·재시작은 test_e2e_testnet_sim.py.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from bot import db
from bot.config import ConfigError, check_no_trading_keys, load_secrets
from bot.engine import Engine
from bot.orders import queue
from bot.orders import worker as W
from bot.orders.control import ControlState
from bot.orders.fake_exchange import FakeExchange, Fault, FaultKind
from bot.orders.tests.conftest import ATR, MARK, T_APPROVED_MS, make_approved_intent, write_control
from bot.orders.types import IdPurpose, IntentState, make_client_id
from bot.tests.conftest import ALLOWED_CHAT_ID, ALLOWED_USER_ID, T_DECISION_NS, T_MS, insert_test_signal, make_config
from bot.tests.conftest import secret_dir  # noqa: F401 — fixture 재사용
from bot.types import FakeClock, Mode, NS_PER_MS, SignalState

S = IntentState
CTL = ControlState(manual_halt=False)


def now_ms(clock) -> int:
    return clock.now_ns() // NS_PER_MS


def tn_config(tmp_path: Path, **kw):
    """testnet BotConfig(A·B 공용). 거래 키·제어 파일 경로는 tmp 아래(기본은 파일 없음)."""
    base = {
        "mode": "testnet", "db_path": str(tmp_path / "data" / "testnet.sqlite3"),
        "claude.enabled": False,
        "orders.api_key_file": str(tmp_path / "b" / "binance_api_key"),
        "orders.private_key_file": str(tmp_path / "b" / "binance_ed25519_private_key"),
        "orders.control_file": str(tmp_path / "b" / "orders_control.toml"),
        "orders.r_capital_usdt": 10_000.0,
    }
    base.update(kw)
    return make_config(tmp_path, **base)


def mk_worker(conn, cfg, fx, clock, control=CTL, **kw) -> W.Worker:
    loader = control if callable(control) else (lambda: control)
    return W.Worker(conn, cfg, fx, clock, control_loader=loader, **kw)


@pytest.fixture
def fx(oclock) -> FakeExchange:
    return FakeExchange(oclock, mark=MARK)


# ---------------------------------------------------------------------------
# 설정(config): testnet 허용·[orders] 검증·A에 거래 키 금지
# ---------------------------------------------------------------------------


def test_config_testnet_accepts_orders_and_tags(tmp_path):
    cfg = tn_config(tmp_path)
    assert cfg.mode is Mode.TESTNET and cfg.mode_tag == "[TESTNET]"
    assert cfg.orders is not None and cfg.orders.r_capital_usdt == 10_000.0
    assert cfg.orders.base_url == "https://demo-fapi.binance.com"
    d = cfg.redacted_dict()
    assert d["orders"]["env"] == "demo" and isinstance(cfg.fingerprint(), str)


def test_config_paper_fingerprint_has_no_orders_key(tmp_path):
    cfg = make_config(tmp_path)
    assert cfg.orders is None and "orders" not in cfg.redacted_dict()


@pytest.mark.parametrize("override, match", [
    ({"mode": "live"}, "live"),
    ({"orders.expected_leverage": 5}, "orders"),
    ({"orders.base_url": "https://fapi.binance.com"}, "모르는 키"),
    ({"orders.api_key": "abc"}, "모르는 키"),
    ({"orders.risk_fraction": 0.02}, "risk_fraction"),
    ({"orders.env": "live"}, "orders"),
    ({"orders.api_key_file": "secrets/k"}, "절대 경로"),
])
def test_config_testnet_rejects(tmp_path, override, match):
    with pytest.raises(ConfigError, match=match):
        tn_config(tmp_path, **override)


def test_config_orders_section_rules(tmp_path):
    with pytest.raises(ConfigError, match=r"\[orders\] 절이 필요"):
        make_config(tmp_path, mode="testnet")
    with pytest.raises(ConfigError, match="testnet"):
        make_config(tmp_path, **{"orders.r_capital_usdt": 1000.0})          # paper에 [orders]
    with pytest.raises(ConfigError, match="겹친다"):
        tn_config(tmp_path, **{"orders.api_key_file": str(tmp_path / "telegram_bot_token")})


def test_a_process_refuses_visible_trading_keys(tmp_path, secret_dir):
    cfg = tn_config(secret_dir.parent, **{"telegram.bot_token_file": str(secret_dir / "telegram_bot_token")})
    check_no_trading_keys(cfg)                                # 없으면 통과
    s = load_secrets(cfg)
    assert s.telegram_token is not None and s.anthropic_api_key is None
    for attr in ("api_key_file", "private_key_file", "control_file"):
        p = Path(getattr(cfg.orders, attr))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        os.chmod(p, 0o600)
        with pytest.raises(ConfigError, match="프로세스 A"):
            load_secrets(cfg)
        p.unlink()


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


def test_db_testnet_creates_queue_schema_and_mode_guard(tmp_path):
    p = tmp_path / "t.sqlite3"
    c = db.connect(p, mode=Mode.TESTNET, now_ms=T_MS)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"order_intents", "order_events", "order_halts", "order_halt_releases", "order_runtime"} <= names
    sid = insert_test_signal(c, mode=Mode.TESTNET)
    assert db.get_signal(c, sid)["mode"] == "testnet"
    c.close()
    with pytest.raises(db.DbError, match="testnet"):
        db.connect(p, mode=Mode.PAPER, now_ms=T_MS)
    c2 = db.connect(p, mode=Mode.TESTNET, now_ms=T_MS)          # 다시 열기(멱등)
    c2.execute("DROP TRIGGER order_events_no_delete")
    c2.close()
    with pytest.raises(db.DbError, match="변조"):
        db.connect(p, mode=Mode.TESTNET, now_ms=T_MS)


# ---------------------------------------------------------------------------
# 엔진(A) TESTNET
# ---------------------------------------------------------------------------


class NoMarket:
    """엔진 tick·버튼이 시세를 부르지 않는지 확인(TESTNET: 모의 체결 없음)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def daily_bars(self, until_ns):
        self.calls.append("daily")
        raise AssertionError("부르면 안 됨")

    def minute_bars(self, start_ns, until_ns):
        self.calls.append("minute")
        raise AssertionError("TESTNET에서 모의 체결용 1분봉을 부르면 안 됨")

    def funding(self, start_ns, until_ns):
        self.calls.append("funding")
        raise AssertionError("부르면 안 됨")

    def server_time_ns(self):
        return None


@pytest.fixture
def tn_engine(tmp_path, oconn):
    cfg = tn_config(tmp_path)
    clock = FakeClock(T_DECISION_NS + 5 * 60 * 1_000_000_000)
    return Engine(oconn, cfg, NoMarket(), None, clock), clock


def _card_and_approve(engine, clock, n=20):
    sid = insert_test_signal(engine.conn, n=n, mode=Mode.TESTNET)
    assert engine.mark_card_sent(sid, 77)
    assert engine.request_confirm(sid)
    assert engine.confirm(sid)
    return sid


def test_engine_confirm_enqueues_in_same_transaction(tn_engine):
    engine, clock = tn_engine
    sid = _card_and_approve(engine, clock)
    row = queue.intent_for_signal(engine.conn, sid)
    assert row is not None and row["state"] == "QUEUED"
    assert row["approved_ms"] == db.get_signal(engine.conn, sid)["approved_ms"]
    # tick은 모의 체결을 하지 않는다(시세 호출 없음), 신호는 APPROVED로 남는다(B가 끝낸다)
    engine.tick()
    assert engine.market.calls == [] and db.get_signal(engine.conn, sid)["state"] == "APPROVED"
    assert engine.conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0] == 0


def test_engine_confirm_rolls_back_if_enqueue_fails(tn_engine, monkeypatch):
    engine, clock = tn_engine
    sid = insert_test_signal(engine.conn, mode=Mode.TESTNET)
    engine.mark_card_sent(sid, 1)
    engine.request_confirm(sid)

    def boom(*a, **k):
        raise RuntimeError("enqueue 실패")

    monkeypatch.setattr(queue, "enqueue", boom)
    with pytest.raises(RuntimeError):
        engine.confirm(sid)
    assert db.get_signal(engine.conn, sid)["state"] == "CONFIRM_PENDING"      # APPROVED만 남는 일 없음
    assert queue.intent_for_signal(engine.conn, sid) is None


def test_engine_pause_cancels_only_unclaimed(tn_engine):
    engine, clock = tn_engine
    s1 = _card_and_approve(engine, clock, n=20)
    s2 = _card_and_approve(engine, clock, n=55)
    claimed = queue.claim_next(engine.conn, now_ms=now_ms(clock))           # B가 s1을 가져감
    assert claimed["signal_id"] == s1
    skipped = engine.pause("TELEGRAM_USER")
    assert skipped == [s2]
    assert db.get_signal(engine.conn, s2)["state"] == "SKIPPED"
    assert queue.intent_for_signal(engine.conn, s2)["state"] == "REJECTED"
    assert db.get_signal(engine.conn, s1)["state"] == "APPROVED"             # 가져간 것은 B가 끝낸다
    assert queue.intent_for_signal(engine.conn, s1)["state"] == "SUBMITTING"


def test_engine_card_note_and_status_when_holding(tn_engine, fx, oclock):
    engine, clock = tn_engine
    s1 = _card_and_approve(engine, clock)
    row = queue.claim_next(engine.conn, now_ms=now_ms(clock))
    fx2 = FakeExchange(clock, mark=MARK)
    from bot.orders.gateway import Gateway

    res = Gateway(engine.conn, engine.cfg.orders, fx2, clock, base_url=fx2.base_url).process_intent(row, CTL)
    assert res.final_state is S.STOP_VERIFIED
    s2 = insert_test_signal(engine.conn, n=55, mode=Mode.TESTNET)
    card = engine._card(db.get_signal(engine.conn, s2))
    assert "보유 중(1포지션)" in card.text and "position_exists" in card.text
    st = engine.status_text()
    assert "[TESTNET]" in st and "거래소(데모) 보유 1개" in st and "심장 박동: 없음" in st
    assert "20일" in engine.positions_text() and "STOP_VERIFIED" in engine.positions_text()
    # B 심장 박동 없음 경고: 시작 유예(5분) 뒤, 끊길 때 한 번
    assert engine._orders_alerts() == []
    clock.advance((5 * 60_000 + 1_000) * NS_PER_MS)
    msgs = engine._orders_alerts()
    assert len(msgs) == 1 and "심장 박동" in msgs[0].text and engine._orders_alerts() == []
    queue.set_runtime(engine.conn, "b_heartbeat_ms", now_ms(clock), now_ms=now_ms(clock))
    assert engine._orders_alerts() == [] and engine._b_down_alerted is False
    rep = engine._testnet_daily_report()
    assert rep.kind == "report" and "거래소(데모) 보유 1개" in rep.text


# ---------------------------------------------------------------------------
# 워커(B) 루프
# ---------------------------------------------------------------------------


def test_worker_requires_startup_and_base_url(oconn, ocfg, fx, oclock):
    w = mk_worker(oconn, ocfg, fx, oclock)
    with pytest.raises(RuntimeError, match="startup"):
        w.run_once()

    class NoUrl:
        env = fx.env

    with pytest.raises(ValueError, match="base_url"):
        W.Worker(oconn, ocfg, NoUrl(), oclock)


def test_worker_happy_path_heartbeat_and_runtime(oconn, ocfg, fx, oclock, tmp_path):
    hb = tmp_path / "hb"
    sid, iid = make_approved_intent(oconn)
    w = mk_worker(oconn, ocfg, fx, oclock, heartbeat_path=str(hb))
    rep = w.startup()
    assert rep.ok, rep.issues
    res = w.run_once()
    assert res is not None and res.final_state is S.STOP_VERIFIED
    assert hb.exists() and queue.get_runtime(oconn, "b_heartbeat_ms") is not None
    assert queue.get_runtime(oconn, "last_reconcile_ok")["value"] == "1"
    assert fx.post_count("place_order") == 1 and fx.post_count("place_conditional") == 1
    # 다음 바퀴: 할 일 없음, 추가 주문 없음
    oclock.advance(31_000 * NS_PER_MS)
    assert w.run_once() is None
    assert fx.post_count("place_order") == 1


def test_worker_rejects_other_queued_immediately_when_holding(oconn, ocfg, fx, oclock):
    s1, i1 = make_approved_intent(oconn, n=20)
    s2, i2 = make_approved_intent(oconn, n=55)
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    res = w.run_once()
    assert res.intent_id == i1 and res.final_state is S.STOP_VERIFIED
    r2 = queue.get_intent(oconn, i2)
    assert r2["state"] == "REJECTED" and r2["state_reason"] == "position_exists"
    assert db.get_signal(oconn, s2)["state"] == "SKIPPED"


def test_worker_control_file_missing_is_manual_halt(oconn, ocfg, fx, oclock, tmp_path):
    sid, iid = make_approved_intent(oconn)
    from bot.orders.control import load_control

    path = tmp_path / "ctl.toml"
    w = mk_worker(oconn, ocfg, fx, oclock, control=lambda: load_control(path))
    w.startup()
    w.run_once()
    row = queue.get_intent(oconn, iid)
    assert row["state"] == "REJECTED" and row["state_reason"] == "halted"
    assert fx.post_count("place_order") == 0
    alerts = [r["text"] for r in oconn.execute("SELECT text FROM outbox WHERE text LIKE '%제어 파일 문제%'")]
    assert len(alerts) == 1                                   # 같은 문제는 한 번만 알림
    w.run_once()
    assert len(list(oconn.execute("SELECT 1 FROM outbox WHERE text LIKE '%제어 파일 문제%'"))) == 1
    # 제어 파일을 만들면 풀린다(T0가 없으므로)
    write_control(path, "halt = false\n")
    sid2, iid2 = make_approved_intent(oconn, n=55, approved_ms=now_ms(oclock))
    w.run_once()
    assert queue.get_intent(oconn, iid2)["state"] == "STOP_VERIFIED"


def test_worker_control_loader_exception_is_fail_closed(oconn, ocfg, fx, oclock):
    sid, iid = make_approved_intent(oconn)

    def bad():
        raise PermissionError("no")

    w = mk_worker(oconn, ocfg, fx, oclock, control=bad)
    w.startup()
    assert w.control.manual_halt and w.control.error == "loader:PermissionError"
    w.run_once()
    assert queue.get_intent(oconn, iid)["state"] == "REJECTED" and fx.post_count("place_order") == 0


def test_worker_t0_blocks_until_control_release_and_records_it(oconn, ocfg, fx, oclock):
    fx.set_account(dual_side_position=True)                  # Hedge → REJECTED + T0
    s1, i1 = make_approved_intent(oconn)
    ctl = {"c": CTL}
    w = mk_worker(oconn, ocfg, fx, oclock, control=lambda: ctl["c"])
    w.startup()
    res = w.run_once()
    assert res.final_state is S.REJECTED and res.halt_ids
    hid = res.halt_ids[0]
    fx.set_account(dual_side_position=False)
    s2, i2 = make_approved_intent(oconn, n=55, approved_ms=now_ms(oclock))
    w.run_once()
    assert queue.get_intent(oconn, i2)["state_reason"] == "halted"
    # A가 DB에 해제 행을 위조해도 소용없다(판정은 제어 파일만)
    oconn.execute("INSERT INTO order_halt_releases(halt_id, ts_ms, control_ref) VALUES (?,?,?)",
                  (hid, now_ms(oclock), "forged"))
    s3, i3 = make_approved_intent(oconn, n=100, approved_ms=now_ms(oclock))
    w.run_once()
    assert queue.get_intent(oconn, i3)["state_reason"] == "halted"
    # 서버 제어 파일에서 해제
    ctl["c"] = ControlState(manual_halt=False, released=frozenset({hid}), ref="ctl@1")
    from bot.tests.conftest import T_DECISION_NS as TD

    s4, i4 = make_approved_intent(oconn, n=20, approved_ms=now_ms(oclock), decision_ns=TD + 86_400 * 10**9)
    w.run_once()
    assert queue.get_intent(oconn, i4)["state"] == "STOP_VERIFIED"


def test_worker_trend_exit_runs_even_when_halted(oconn, ocfg, fx, oclock):
    sid, iid = make_approved_intent(oconn)
    ctl = {"c": CTL}
    w = mk_worker(oconn, ocfg, fx, oclock, control=lambda: ctl["c"])
    w.startup()
    assert w.run_once().final_state is S.STOP_VERIFIED
    ctl["c"] = ControlState(manual_halt=True, ref="manual")       # 수동 정지(O-15: 청산은 계속)
    t = now_ms(oclock)
    assert queue.request_exit(oconn, sid, exit_signal_close_ms=t, exit_due_ms=t + 60_000, now_ms=t)
    w.run_once()
    assert queue.get_intent(oconn, iid)["state"] == "STOP_VERIFIED"          # 기한 전: 아무것도 안 함
    oclock.advance(61_000 * NS_PER_MS)
    w.run_once()
    row = queue.get_intent(oconn, iid)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "trend"
    assert fx.position_qty == 0 and not [c for c in fx.all_conditionals() if c.status.value == "NEW"]
    assert db.get_signal(oconn, sid)["state"] == "CLOSED"


def test_worker_exiting_after_three_failures_sends_no_more(oconn, ocfg, fx, oclock):
    sid, iid = make_approved_intent(oconn)
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    w.run_once()
    t = now_ms(oclock)
    queue.request_exit(oconn, sid, exit_signal_close_ms=t, exit_due_ms=t, now_ms=t)
    fx.inject(Fault(FaultKind.REJECT, method="place_order", code=-1111, times=-1))
    w.run_once()
    row = queue.get_intent(oconn, iid)
    assert row["state"] == "EXITING" and row["exit_attempts"] == 3
    n = fx.post_count("place_order")
    for _ in range(3):
        oclock.advance(5_000 * NS_PER_MS)
        w.run_once()
    assert fx.post_count("place_order") == n                   # 3회 소진 뒤 더 보내지 않음
    assert "flatten_failed" in [r["reason"] for r in queue.halts(oconn)]


def test_worker_run_forever_survives_loop_errors(oconn, fx, oclock, monkeypatch):
    from bot.orders.tests.conftest import make_orders_config

    w = mk_worker(oconn, make_orders_config(loop_interval_s=0.001), fx, oclock)
    w.startup()
    stop = threading.Event()
    n = {"k": 0}

    def flaky():
        n["k"] += 1
        if n["k"] >= 3:
            stop.set()
        raise RuntimeError("일시 오류")

    monkeypatch.setattr(w, "run_once", flaky)
    w.run_forever(stop)
    assert w.loop_errors == 3


# ---------------------------------------------------------------------------
# selftest (조회만) · 왕복 시험
# ---------------------------------------------------------------------------


def test_selftest_checks_pass_and_fail(ocfg, fx, oclock):
    rep = W.selftest_checks(fx, ocfg, oclock)
    assert rep.ok, rep.text()
    assert rep.mark == MARK and "K10" not in rep.text()      # 가짜는 can_withdraw=False
    assert fx.post_count("place_order") == 0 and fx.post_count("place_conditional") == 0
    fx.set_account(multi_assets_margin=True, leverage=5, can_withdraw=None)
    fx.inject(Fault(FaultKind.HTTP_STATUS, method="balance", http_status=451))
    rep = W.selftest_checks(fx, ocfg, oclock)
    bad = {c.name for c in rep.lines if not c.ok}
    assert {"계정 모드", "레버리지·마진", "잔고"} <= bad and not rep.ok
    assert "모름(K10" in rep.text()


def test_selftest_roundtrip_through_running_worker(oconn, ocfg, fx, oclock):
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    out: list[str] = []
    res = W.run_roundtrip(oconn, mark=fx.mark, clock=oclock, wait_step=w.run_once, echo=out.append)
    assert res.ok, res.lines
    row = queue.get_intent(oconn, res.intent_id)
    assert row["state"] == "CLOSED" and row["exit_reason"] == "trend"
    sig = db.get_signal(oconn, res.signal_id)
    assert sig["spec_version"] == W.SELFTEST_SPEC and sig["state"] == "CLOSED"
    assert fx.position_qty == 0
    assert fx.post_count("place_order", client_id=make_client_id(res.signal_id, IdPurpose.ENTRY)) == 1
    assert fx.post_count("place_conditional") == 1
    assert any("e1×1" in line for line in out) and any("STOP_VERIFIED" in line for line in out)
    assert not queue.halts(oconn)


def test_selftest_roundtrip_refusals(oconn, ocfg, fx, oclock):
    with pytest.raises(W.SelftestRefused, match="심장 박동"):
        W.run_roundtrip(oconn, mark=MARK, clock=oclock, wait_step=lambda: None)
    with pytest.raises(W.SelftestRefused, match="수동 정지"):
        W.run_roundtrip(oconn, mark=MARK, clock=oclock, wait_step=lambda: None,
                        control=ControlState(manual_halt=True, error="missing"))
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    make_approved_intent(oconn)
    with pytest.raises(W.SelftestRefused, match="QUEUED"):
        W.run_roundtrip(oconn, mark=MARK, clock=oclock, wait_step=lambda: None)
    w.run_once()
    with pytest.raises(W.SelftestRefused, match="노출"):
        W.create_selftest_intent(oconn, mark=MARK, now_ms=now_ms(oclock))
    with pytest.raises(W.SelftestRefused, match="마크"):
        W.create_selftest_intent(oconn, mark=0.0, now_ms=now_ms(oclock))
    hid = queue.raise_halt(oconn, reason="auth", now_ms=now_ms(oclock))
    with pytest.raises(W.SelftestRefused, match="T0"):
        W.run_roundtrip(oconn, mark=MARK, clock=oclock, wait_step=lambda: None, control=CTL)


def test_selftest_roundtrip_reports_failure(oconn, ocfg, fx, oclock):
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    fx.inject(Fault(FaultKind.NO_FILL, method="place_order"))
    res = W.run_roundtrip(oconn, mark=fx.mark, clock=oclock, wait_step=w.run_once, echo=lambda s: None)
    assert not res.ok and res.final_state == "NOT_FILLED"


# ---------------------------------------------------------------------------
# main (설정·비밀·DB 오류 → 종료 코드, 실제 루프는 주입한 가짜 거래소로)
# ---------------------------------------------------------------------------


def _write_toml(tmp_path: Path, mode: str = "testnet", *, extra: str = "") -> Path:
    b = tmp_path / "b"
    state = tmp_path / "state"                                   # B 전용 원장 볼륨(/state) 대신
    state.mkdir(exist_ok=True)
    orders = (f'[orders]\napi_key_file = "{b / "binance_api_key"}"\n'
              f'private_key_file = "{b / "binance_ed25519_private_key"}"\n'
              f'control_file = "{b / "orders_control.toml"}"\nledger_file = "{state / "orders_ledger.json"}"\n'
              f'r_capital_usdt = 10000.0\n') if mode == "testnet" else ""
    p = tmp_path / "bot.toml"
    p.write_text(f'mode = "{mode}"\ndb_path = "{tmp_path / "data" / "testnet.sqlite3"}"\n'
                 f"[telegram]\nenabled = true\nallowed_user_id = {ALLOWED_USER_ID}\n"
                 f'allowed_chat_id = {ALLOWED_CHAT_ID}\nbot_token_file = "{tmp_path / "a" / "telegram_bot_token"}"\n'
                 f'[claude]\nenabled = false\napi_key_file = "{tmp_path / "a" / "anthropic_api_key"}"\n'
                 + orders + extra, encoding="utf-8")
    return p


@pytest.fixture
def restore_umask():
    old = os.umask(0o022)
    os.umask(old)
    yield
    os.umask(old)


def test_main_config_errors(tmp_path, capsys, restore_umask):
    p = _write_toml(tmp_path, "paper")
    assert W.main(["--config", str(p)], environ={}) == W.EXIT_CONFIG
    assert "testnet" in capsys.readouterr().err
    p = _write_toml(tmp_path)
    assert W.main(["--config", str(p)], environ={"BINANCE_API_KEY": "x"}) == W.EXIT_CONFIG
    live = tmp_path / "live.toml"
    live.write_text(f'mode = "live"\ndb_path = "{tmp_path / "x.sqlite3"}"\n')
    assert W.main(["--config", str(live)], environ={}) == W.EXIT_CONFIG
    # A 쪽 비밀이 B에 보이면 거부
    a = tmp_path / "a"
    a.mkdir()
    (a / "telegram_bot_token").write_text("1:x")
    assert W.main(["--config", str(p)], environ={}) == W.EXIT_CONFIG
    assert "A 프로세스 비밀" in capsys.readouterr().err
    (a / "telegram_bot_token").unlink()
    # 키 파일 없음(실제 클라이언트) → 설정 오류
    assert W.main(["--config", str(p)], environ={}) == W.EXIT_CONFIG
    assert "비밀 파일이 없다" in capsys.readouterr().err


def test_main_db_mode_mismatch(tmp_path, restore_umask):
    p = _write_toml(tmp_path)
    dbp = tmp_path / "data" / "testnet.sqlite3"
    db.connect(dbp, mode=Mode.PAPER, now_ms=T_MS).close()
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    code = W.main(["--config", str(p)], environ={}, clock=clock,
                  client_factory=lambda c, k: FakeExchange(k, mark=MARK))
    assert code == W.EXIT_DB


def test_main_run_and_selftest_with_injected_exchange(tmp_path, capsys, restore_umask):
    p = _write_toml(tmp_path)
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    fx = FakeExchange(clock, mark=MARK)
    stop = threading.Event()
    stop.set()                                                   # startup(복구)만 하고 바로 정지
    code = W.main(["--config", str(p), "run"], environ={}, clock=clock, client_factory=lambda c, k: fx, stop=stop)
    assert code == W.EXIT_OK
    c = db.connect(tmp_path / "data" / "testnet.sqlite3", mode=Mode.TESTNET, now_ms=T_MS)
    assert queue.get_runtime(c, "b_started_ms") is not None and queue.get_runtime(c, "b_heartbeat_ms") is not None
    c.close()
    assert W.main(["--config", str(p), "selftest"], environ={}, clock=clock,
                  client_factory=lambda c, k: fx) == W.EXIT_OK
    out = capsys.readouterr().out
    assert "점검 통과" in out and "[실패]" not in out
    fx.set_account(dual_side_position=True)
    assert W.main(["--config", str(p), "selftest"], environ={}, clock=clock,
                  client_factory=lambda c, k: fx) == W.EXIT_ERROR
    # 왕복 시험: 제어 파일이 없으면(수동 정지) 시작하지 않는다
    fx.set_account(dual_side_position=False)
    assert W.main(["--config", str(p), "selftest", "--roundtrip"], environ={}, clock=clock,
                  client_factory=lambda c, k: fx) == W.EXIT_ERROR
    assert "수동 정지" in capsys.readouterr().err
    # 워커 심장 박동이 오래됐으면 시작하지 않는다
    (tmp_path / "b").mkdir()
    write_control(tmp_path / "b" / "orders_control.toml", "halt = false\n")
    clock.advance(10 * 60 * 1000 * NS_PER_MS)
    assert W.main(["--config", str(p), "selftest", "--roundtrip"], environ={}, clock=clock,
                  client_factory=lambda c, k: fx) == W.EXIT_ERROR
    assert "심장 박동" in capsys.readouterr().err
    assert fx.post_count("place_order") == 0


def test_main_key_files_via_real_client(tmp_path, capsys, restore_umask):
    """실제 BinanceFuturesClient.from_files: 권한 넓은 키 파일 → 설정 오류, 올바른 Ed25519 PEM → 생성 성공(네트워크 없음)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    p = _write_toml(tmp_path)
    b = tmp_path / "b"
    b.mkdir()
    (b / "binance_api_key").write_text("testkeyid123\n")
    os.chmod(b / "binance_api_key", 0o644)
    pem = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption())
    (b / "binance_ed25519_private_key").write_bytes(pem)
    os.chmod(b / "binance_ed25519_private_key", 0o600)
    assert W.main(["--config", str(p)], environ={}) == W.EXIT_CONFIG
    assert "권한" in capsys.readouterr().err
    os.chmod(b / "binance_api_key", 0o400)
    from bot.orders.binance_client import BinanceFuturesClient
    from bot.config import load_config

    cfg = load_config(p)
    cl = BinanceFuturesClient.from_files(cfg.orders, clock=FakeClock(0))
    try:
        assert cl.base_url == "https://demo-fapi.binance.com" and "testkeyid123" not in repr(cl)
    finally:
        cl.close()


def test_main_status_reads_db_only(tmp_path, capsys, restore_umask):
    p = _write_toml(tmp_path)
    clock = FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS)
    c = db.connect(tmp_path / "data" / "testnet.sqlite3", mode=Mode.TESTNET, now_ms=T_MS)
    hid = queue.raise_halt(c, reason="auth", now_ms=T_MS)
    c.close()

    def no_client(cfg, k):
        raise AssertionError("status는 거래소 클라이언트를 만들지 않는다")

    assert W.main(["--config", str(p), "status"], environ={}, clock=clock, client_factory=no_client) == W.EXIT_OK
    out = capsys.readouterr().out
    assert f"T0 #{hid}" in out and "정지 중" in out and "수동 정지" in out and "(문제: missing)" in out
    (tmp_path / "b").mkdir()
    write_control(tmp_path / "b" / "orders_control.toml",
                  f'halt = false\n[[release]]\nhalt_id = {hid}\nreason = "확인함"\n')
    assert W.main(["--config", str(p), "status"], environ={}, clock=clock, client_factory=no_client) == W.EXIT_OK
    out = capsys.readouterr().out
    assert "해제됨" in out and "풀리지 않은 T0 없음" in out
