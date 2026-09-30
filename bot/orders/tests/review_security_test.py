"""적대적 보안 검토(보안 감사관) — 실행으로 확인한 항목.

범위: 키 격리, 서명, 주문 방화벽 우회, 큐 테이블 위조(A 침해 시 B의 최대 피해), 텔레그램 주문 경로, LIVE 전환,
컨테이너 시크릿 마운트. 거래소는 전부 FakeExchange(이 컨테이너는 바이낸스 접속 불가).

표기
- 일반 시험: 방어가 **지켜지는 것**을 확인(통과해야 정상).
- ``xfail(strict=True)`` 시험: 검토에서 찾은 **취약점을 재현**한다. 지금은 공격이 성공하므로 '안전 기대' 단언이 실패한다.
  고치면 XPASS → strict라 실패로 드러나니 그때 xfail 표시를 지운다. 사유 문자열의 SEC-xx가 검토 보고서 항목이다.
- 수정 담당: SEC-01~05는 고쳐져 xfail을 지웠다(회귀 시험). SEC-06(B 독립 경보 경로)은 남은 과제(DESIGN §16 R-13).

실행: .venv/bin/python -m pytest bot/orders/tests/review_security_test.py -q
(pytest 기본 규칙 *_test.py로 `pytest bot`에도 수집된다. 취약점 재현만 보려면 --runxfail.)
"""
from __future__ import annotations

import base64
import logging
import math
import random
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bot import db
from bot.config import ConfigError, Secret, config_from_dict
from bot.orders import queue
from bot.orders import worker as W
from bot.orders.control import ControlState, load_control
from bot.orders.fake_exchange import FakeExchange
from bot.orders.firewall import FirewallContext, OrderPurpose, check_conditional, check_order
from bot.orders.gateway import Gateway
from bot.orders.reconcile import reconcile_once
from bot.orders.tests.conftest import (
    DEMO_URL,
    MARK,
    T_APPROVED_MS,
    good_account,
    good_balance,
    good_rules,
    make_approved_intent,
    make_orders_config,
    write_control,
)
from bot.orders.tests.test_gateway import Hooked, halt_reasons, intent, make_gw, now_ms, to_verified
from bot.orders.types import (
    ABS_MAX_NOTIONAL_USDT,
    ABS_MAX_QTY_BTC,
    ENV_HOSTS,
    LIVE_HOSTS,
    MAX_RISK_FRACTION,
    SYMBOL,
    ConditionalRequest,
    ExchangeEnv,
    IdPurpose,
    IntentState,
    OrderRequest,
    OrdersConfig,
    OrdersConfigError,
    OrderType,
    Side,
    TimeInForce,
    WorkingType,
    make_client_id,
)
from bot.tests.conftest import T_DECISION_NS, T_MS
from bot.types import FakeClock, Mode, NS_PER_MS

S = IntentState
CTL = ControlState(manual_halt=False)
ROOT = Path(__file__).resolve().parents[3]
DAY_NS = 86_400 * 10**9


@pytest.fixture
def fx(oclock) -> FakeExchange:
    return FakeExchange(oclock, mark=MARK)


def mk_worker(conn, cfg, ex, clock, control=CTL) -> W.Worker:
    return W.Worker(conn, cfg, ex, clock, control_loader=lambda: control)


# ===========================================================================
# 1. 키 격리
# ===========================================================================


def test_a_process_modules_never_load_signing_client_or_crypto_key_loader():
    """A(bot.main·engine·telegram_ui)를 import해도 서명 클라이언트·키 로더가 메모리에 올라오지 않는다."""
    code = ("import sys; import bot.main, bot.engine, bot.telegram_ui, bot.config, bot.db;"
            "bad=[m for m in ('bot.orders.binance_client','bot.orders.gateway','bot.orders.worker') if m in sys.modules];"
            "print(','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "", f"A가 주문 경로 모듈을 import함: {out.stdout}"


def test_a_sources_have_no_exchange_order_calls():
    """A 쪽 소스에 거래소 주문·서명 호출이 없다(주문은 B의 gateway만)."""
    for name in ("engine.py", "telegram_ui.py", "main.py", "paper.py", "analyst.py"):
        src = (ROOT / "bot" / name).read_text(encoding="utf-8")
        for needle in ("place_order", "place_conditional", "binance_client", "BinanceFuturesClient",
                       "X-MBX-APIKEY", "Ed25519", "cancel_order", "cancel_conditional"):
            assert needle not in src, f"{name}에 {needle}"


def _pem_and_key() -> tuple[str, Ed25519PrivateKey]:
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()).decode()
    return pem, k


API_KEY = "SECAPIKEYxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"


def _client(handler, clock, **cfgkw):
    from bot.orders.binance_client import BinanceFuturesClient

    pem, k = _pem_and_key()
    cfg = make_orders_config(**cfgkw)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    c = BinanceFuturesClient(cfg, Secret(API_KEY), Secret(pem), clock=clock, http_client=http,
                             sleep=lambda s: None)
    return c, pem, k


def test_secret_and_client_repr_do_not_leak(oclock):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"serverTime": now_ms(oclock)})

    c, pem, _ = _client(handler, oclock)
    body_line = pem.strip().splitlines()[1]
    for text in (repr(c), str(c), repr(Secret(API_KEY)), str(Secret(API_KEY)), repr(Secret(pem))):
        assert API_KEY not in text and body_line not in text


def test_transport_error_and_http_error_messages_and_logs_have_no_key_or_signature(oclock, caplog):
    """전송 실패·HTTP 오류의 예외 메시지·예외 사슬·로그(httpx DEBUG로 낮춰도)에 키·서명·쿼리가 없다."""
    from bot.orders.types import ExchangeError

    mode = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": now_ms(oclock)})
        mode["n"] += 1
        if mode["n"] == 1:
            raise httpx.ConnectTimeout("boom " + str(req.url), request=req)
        return httpx.Response(400, json={"code": -1102, "msg": "bad param " + str(req.url)[:30]})

    c, pem, _ = _client(handler, oclock)
    for lg in ("httpx", "httpcore"):
        logging.getLogger(lg).setLevel(logging.DEBUG)          # 누군가 수준을 내려도
    caplog.set_level(logging.DEBUG)
    req = OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.LIMIT, qty=0.001,
                       client_id=make_client_id("ABCDEFGHIJKLMNOP", IdPurpose.ENTRY), price=60_000.0,
                       time_in_force=TimeInForce.IOC)
    errs = []
    for _ in range(2):
        with pytest.raises(ExchangeError) as ei:
            c.place_order(req)
        errs.append(ei.value)
    for e in errs:
        chain = [e]
        while chain[-1].__cause__ is not None or chain[-1].__context__ is not None:
            nxt = chain[-1].__cause__ or chain[-1].__context__
            if nxt in chain or e.__suppress_context__ and chain[-1] is e:
                break
            chain.append(nxt)
        for x in chain:
            s = str(x)
            assert "signature" not in s and API_KEY not in s and "timestamp=" not in s, s
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert API_KEY not in blob
    assert not re.search(r"signature=(?!<redacted>)", blob), blob[-800:]


def test_signature_verifies_over_exact_sent_body_and_tamper_breaks(oclock):
    """보낸 본문 그대로(signature 앞까지)가 공개키로 검증되고, 한 글자만 바꿔도 검증이 깨진다. recvWindow=5000."""
    from cryptography.exceptions import InvalidSignature

    sent: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": now_ms(oclock)})
        sent.append(req)
        return httpx.Response(200, json={
            "clientOrderId": make_client_id("ABCDEFGHIJKLMNOP", IdPurpose.ENTRY), "orderId": 1, "symbol": SYMBOL,
            "side": "BUY", "type": "LIMIT", "status": "EXPIRED", "origQty": "0.001", "executedQty": "0",
            "avgPrice": "0", "price": "60000", "timeInForce": "IOC", "updateTime": now_ms(oclock)})

    c, _, key = _client(handler, oclock)
    c.place_order(OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.LIMIT, qty=0.001,
                               client_id=make_client_id("ABCDEFGHIJKLMNOP", IdPurpose.ENTRY), price=60_000.0,
                               time_in_force=TimeInForce.IOC))
    assert len(sent) == 1
    r = sent[0]
    assert r.method == "POST" and r.url.host == ENV_HOSTS[ExchangeEnv.DEMO] and r.url.scheme == "https"
    assert r.headers["X-MBX-APIKEY"] == API_KEY
    body = r.content.decode()
    payload, sig = body.rsplit("&signature=", 1)
    assert payload.startswith("timestamp=") and payload.endswith("&recvWindow=5000")
    pub = key.public_key()
    pub.verify(base64.b64decode(unquote(sig)), payload.encode())
    with pytest.raises(InvalidSignature):
        pub.verify(base64.b64decode(unquote(sig)), payload.replace("quantity=0.001", "quantity=0.002").encode())


def test_client_refuses_to_sign_when_clock_skewed(oclock):
    """|오프셋| > 1초면 서명 요청 자체를 보내지 않는다(요청 수 0)."""
    from bot.orders.types import ErrorKind, ExchangeError

    signed: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": now_ms(oclock) + 5_000})
        signed.append(req)
        return httpx.Response(200, json={})

    c, _, _ = _client(handler, oclock)
    with pytest.raises(ExchangeError) as ei:
        c.position()
    assert ei.value.kind is ErrorKind.CLOCK_SKEW and signed == []


# ===========================================================================
# 2. LIVE 전환 불가(설정·호스트)
# ===========================================================================


@pytest.mark.parametrize("mode", ["live", "LIVE", "Live", " live", "mainnet", "prod"])
def test_config_never_accepts_live_mode(mode):
    with pytest.raises(ConfigError):
        config_from_dict({"mode": mode, "db_path": "/data/x.sqlite3"})


@pytest.mark.parametrize("raw", [
    {"env": "live"}, {"env": "mainnet"}, {"env": "prod"},
    {"base_url": "https://fapi.binance.com"}, {"host": "fapi.binance.com"}, {"api_key": "x"},
    {"recv_window_ms": 60_000}, {"expected_leverage": 4}, {"risk_fraction": 0.02},
    {"max_notional_usdt": 1e9}, {"ioc_cap_bps": 500}, {"max_clock_skew_ms": 10_000},
    {"api_key_file": "relative/path"},
])
def test_orders_config_rejects_loosening_and_host_injection(raw):
    with pytest.raises(OrdersConfigError):
        OrdersConfig.from_mapping(raw)


def test_env_host_table_never_contains_live_hosts():
    assert not set(ENV_HOSTS.values()) & set(LIVE_HOSTS)
    for env in ExchangeEnv:
        assert OrdersConfig(env=env).base_url.startswith("https://")


def test_client_constructor_rejects_live_host_even_if_config_object_is_tampered(oclock):
    """OrdersConfig.base_url을 몰래 바꾼 객체(메모리 변조)도 생성자에서 거부된다."""
    from bot.orders.binance_client import BinanceFuturesClient

    class Evil(OrdersConfig):
        @property
        def base_url(self) -> str:  # type: ignore[override]
            return "https://fapi.binance.com"

    pem, _ = _pem_and_key()
    with pytest.raises(ValueError):
        BinanceFuturesClient(Evil(r_capital_usdt=1000.0), Secret(API_KEY), Secret(pem), clock=oclock,
                             http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))


def test_firewall_rejects_every_order_kind_to_live_host(ocfg):
    sid = "ABCDEFGHIJKLMNOP"
    for url in ("https://fapi.binance.com", "http://demo-fapi.binance.com", "https://testnet.binancefuture.com",
                "https://demo-fapi.binance.com.evil.com"):
        ctx = FirewallContext(cfg=ocfg, client_base_url=url, signal_id=sid, mark_price=MARK, position_qty=0.01,
                              planned_stop=57_000.0, position_entry_price=60_000.0)
        req = OrderRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.MARKET, qty=0.01,
                           client_id=make_client_id(sid, IdPurpose.FLAT1), reduce_only=True)
        assert "FW-ENV" in check_order(req, OrderPurpose.FLATTEN, ctx).violations
        creq = ConditionalRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.STOP_MARKET, trigger_price=57_000.0,
                                  client_algo_id=make_client_id(sid, IdPurpose.STOP))
        assert "FW-ENV" in check_conditional(creq, ctx).violations


# ===========================================================================
# 3. 주문 방화벽 — 무작위 입력으로 '통과하면 반드시 한도 안' 확인
# ===========================================================================


def test_firewall_fuzz_any_passing_entry_is_within_hard_limits():
    rng = random.Random(20260930)
    sid = "ABCDEFGHIJKLMNOP"
    passed = 0

    def pick(good, *bad, p=0.85):
        return good if rng.random() < p or not bad else rng.choice(bad)

    for _ in range(20_000):
        cfg = make_orders_config(r_capital_usdt=rng.choice([100.0, 1_000.0, 10_000.0, 1e6, 1e9]),
                                 risk_fraction=rng.choice([0.001, 0.005]), expected_leverage=3)
        mark = rng.choice([100.0, 60_000.0, 250_000.0])
        price = round(mark * pick(rng.uniform(1.0, 1.001), rng.uniform(0.95, 1.05)) + 0.05, 1)
        qty = round(rng.choice([0.001, 0.002, 0.005, 0.01, 0.05, 0.2, 0.3, 1.0]) * rng.uniform(0.5, 1.5), 3)
        stop = round(price * (1 - pick(rng.uniform(0.003, 0.2), rng.uniform(-0.01, 0.5))), 1)
        acc = good_account(leverage=pick(3, 1, 2, 4, 20), margin_type=pick("isolated", "cross"),
                           dual_side_position=pick(False, True), multi_assets_margin=pick(False, True),
                           can_withdraw=pick(False, None, True))
        ctx = FirewallContext(cfg=cfg, client_base_url=pick(DEMO_URL, "https://fapi.binance.com"),
                              signal_id=sid, mark_price=mark, position_qty=pick(0.0, 0.001),
                              account=acc, rules=good_rules(), balance=good_balance(pick(1e9, 1e2, 1e5)),
                              halted=pick(False, True), entry_already_sent=pick(False, True),
                              planned_stop=stop)
        req = OrderRequest(symbol=pick(SYMBOL, "ETHUSDT"), side=pick(Side.BUY, Side.SELL),
                           type=pick(OrderType.LIMIT, OrderType.MARKET), qty=qty,
                           client_id=pick(make_client_id(sid, IdPurpose.ENTRY), make_client_id(sid, "x1"),
                                          "sig-BBBBBBBBBBBBBBBB-e1", "web123"),
                           price=price, time_in_force=pick(TimeInForce.IOC, TimeInForce.GTC, None),
                           reduce_only=pick(False, True))
        v = check_order(req, OrderPurpose.ENTRY, ctx)
        if not v.ok:
            continue
        passed += 1
        notional = qty * price
        assert req.symbol == SYMBOL and req.side is Side.BUY and req.type is OrderType.LIMIT
        assert req.time_in_force is TimeInForce.IOC and not req.reduce_only
        assert ctx.client_base_url == DEMO_URL and acc.leverage <= 3 and acc.margin_type == "isolated"
        assert acc.can_withdraw is not True and not ctx.halted and not ctx.entry_already_sent
        assert qty <= ABS_MAX_QTY_BTC + 1e-12
        assert notional <= min(ABS_MAX_NOTIONAL_USDT, cfg.max_notional_usdt, cfg.r_capital_usdt * 0.2) * (1 + 1e-9)
        assert qty * (price - stop) <= cfg.r_capital_usdt * min(cfg.risk_fraction, MAX_RISK_FRACTION) * (1 + 1e-6)
        assert price <= mark * 1.01 + 1e-9
    assert passed > 50                    # 퍼즈가 통과 영역도 실제로 탐색했는지


@pytest.mark.parametrize("atr", [0.01, 1.0, 50.0, 60.0, 5_000.0, 7_400.0, 1e9])
def test_forged_signal_atr_cannot_push_entry_past_limits(oconn, fx, oclock, atr):
    """A가 신호의 ATR20을 극단값으로 위조해도: 진입했다면 위험·명목·수량 한도 안, 아니면 주문 없음."""
    cfg = make_orders_config(r_capital_usdt=1e9)             # R 자본을 크게 잡아도(설정은 B 쪽 서버 파일)
    sid, iid = make_approved_intent(oconn, atr20=atr)
    row = queue.claim_next(oconn, now_ms=now_ms(oclock))
    res = Gateway(oconn, cfg, fx, oclock, base_url=DEMO_URL).process_intent(row, CTL)
    r = intent(oconn, iid)
    if fx.post_count("place_order") == 0:
        assert res.final_state is S.REJECTED
        return
    e1 = [c for c in fx.calls_for("place_order")][0]
    req = e1.request
    assert req.qty <= ABS_MAX_QTY_BTC and req.qty * req.price <= ABS_MAX_NOTIONAL_USDT + 1e-6
    assert req.qty * (req.price - r["planned_stop"]) <= 1e9 * 0.005 * (1 + 1e-6)
    assert res.final_state in (S.STOP_VERIFIED, S.FAILED_FLATTENED, S.NOT_FILLED)


def test_nothing_outside_gateway_calls_exchange_order_methods():
    """주문·취소 메서드 호출은 gateway.py(방화벽 경유)에만 있다. reconcile·worker는 게이트웨이 메서드를 부른다."""
    pat = re.compile(r"\.(place_order|place_conditional|cancel_order|cancel_conditional)\(")
    for p in (ROOT / "bot").rglob("*.py"):
        if "tests" in p.parts or p.name in ("gateway.py", "fake_exchange.py", "binance_client.py", "types.py"):
            continue
        assert not pat.search(p.read_text(encoding="utf-8")), p
    gsrc = (ROOT / "bot" / "orders" / "gateway.py").read_text(encoding="utf-8")
    # gateway 안의 주문 전송은 _x(…, "place_order"|"place_conditional") 뿐 — 직접 self.ex.place_* 호출 없음
    assert not re.search(r"self\.ex\.(place_order|place_conditional)\(", gsrc)


# ===========================================================================
# 4. 텔레그램에서 주문 경로 없음 / T0 해제는 제어 파일만
# ===========================================================================


def test_telegram_commands_have_no_order_or_release_commands():
    from bot import telegram_ui as tu

    assert set(tu.COMMANDS) == {"status", "positions", "pause", "resume", "help"}
    src = (ROOT / "bot" / "telegram_ui.py").read_text(encoding="utf-8")
    assert "record_release" not in src and "order_halt_releases" not in src and "request_exit" not in src


def test_forged_db_release_row_and_runtime_rows_do_not_release_t0(oconn, ocfg, fx, oclock):
    gw = make_gw(oconn, ocfg, fx, oclock)
    hid = queue.raise_halt(oconn, reason="stop_missing", now_ms=now_ms(oclock))
    # A가 해제 행을 위조
    oconn.execute("INSERT INTO order_halt_releases(halt_id, ts_ms, control_ref) VALUES (?,?,?)",
                  (hid, now_ms(oclock), "forged"))
    assert gw.is_halted(CTL) is True
    make_approved_intent(oconn)
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    w.run_once()
    assert fx.post_count("place_order") == 0


def test_control_file_fail_closed(tmp_path):
    assert load_control(tmp_path / "missing.toml").manual_halt
    p = write_control(tmp_path / "c.toml", "halt = false\n", mode=0o666)
    assert load_control(p).manual_halt and load_control(p).error == "writable_by_others"
    p = write_control(tmp_path / "d.toml", "halt = false\n[[release]]\nhalt_id = 1\n", mode=0o600)
    assert load_control(p).manual_halt                               # reason 누락
    p = write_control(tmp_path / "e.toml", "halt = false\nrelease_all = true\n", mode=0o600)
    assert load_control(p).manual_halt


# ===========================================================================
# 5. 컨테이너 시크릿 마운트 범위
# ===========================================================================


def _services(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cur = None
    in_services = False
    for line in text.splitlines():
        if re.match(r"^services:\s*$", line):
            in_services = True
            continue
        if in_services and re.match(r"^\S", line):
            in_services = False
            cur = None
        if in_services:
            m = re.match(r"^  ([a-z_]+):\s*$", line)
            if m:
                cur = m.group(1)
                out[cur] = ""
                continue
            if cur is not None:
                out[cur] += re.sub(r"\s+#.*$", "", line) + "\n" if not line.strip().startswith("#") else ""
    return out


def test_compose_trading_secrets_and_control_only_in_orders_and_read_only():
    svc = _services((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert {"bot", "orders"} <= set(svc)
    for name, body in svc.items():
        has_keys = "binance_api_key" in body or "binance_ed25519_private_key" in body
        has_ctl = "orders_control" in body
        assert (has_keys or has_ctl) == (name == "orders"), name
        assert "environment" not in body or not re.search(r"(?i)(key|secret|token)\s*:", body.split("volumes")[0]), name
        assert "ports:" not in body and "privileged" not in body and "/var/run/docker.sock" not in body, name
        assert "./secrets" not in body, f"{name}: 비밀 폴더를 볼륨으로 직접 마운트"
    orders = svc["orders"]
    assert re.search(r"orders_control\.toml:/control/orders_control\.toml:ro", orders)
    assert re.search(r"bot\.toml:/config/bot\.toml:ro", orders)
    assert "telegram_bot_token" not in orders and "anthropic_api_key" not in orders
    assert "read_only: true" in orders and "cap_drop: [ALL]" in orders


def test_dockerfile_code_is_read_only_and_tests_removed():
    df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "chmod -R a-w /app" in df and "/app/bot/orders/tests" in df and "USER 10001" in df


# ===========================================================================
# 6. 큐 위조(A 침해) — B의 최대 피해가 방화벽 한도 안인가
# ===========================================================================


# 회귀(수정됨): SEC-01 — bot/orders/DESIGN.md §16 R 표
def test_sec01_forged_closed_intent_makes_b_cancel_live_stop(oconn, ocfg, fx, oclock):
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    assert fx.position_qty > 0 and len(fx.active_conditionals()) == 1
    # --- 침해된 A: DB만으로(키 없이) 보유 의도를 끝난 것처럼 바꾼다 ---
    oconn.execute("UPDATE order_intents SET state='CLOSED', exit_reason='trend', closed_ms=? WHERE intent_id=?",
                  (now_ms(oclock), iid))
    reconcile_once(oconn, gw, fx, oclock, CTL)
    # 안전 기대: 포지션이 남아 있으면 손절도 남아 있어야 한다(아니면 청산돼 있어야 한다)
    assert fx.position_qty == 0 or len(fx.active_conditionals()) == 1, \
        f"손절 없는 포지션 {fx.position_qty} BTC, 경보만: {halt_reasons(oconn)}"


# 회귀(수정됨): SEC-02 — bot/orders/DESIGN.md §16 R 표
def test_sec02_a_can_erase_t0_by_recreating_protect_triggers(tmp_path, ocfg, fx, oclock):
    path = tmp_path / "t.sqlite3"
    conn_b = db.connect(path, mode=Mode.TESTNET, now_ms=T_MS)
    queue.ensure_schema(conn_b)
    queue.raise_halt(conn_b, reason="stop_missing", now_ms=now_ms(oclock))
    conn_a = db.connect(path, mode=Mode.TESTNET, now_ms=T_MS)
    body = conn_a.execute("SELECT sql FROM sqlite_master WHERE name='order_halts_no_delete'").fetchone()[0]
    conn_a.execute("DROP TRIGGER order_halts_no_delete")
    conn_a.execute("DELETE FROM order_halts")
    conn_a.execute(body)                                          # 같은 이름·같은 본문으로 되돌려 흔적 제거
    make_approved_intent(conn_a, approved_ms=now_ms(oclock))
    w = mk_worker(conn_b, ocfg, fx, oclock)
    w.startup()                                                   # ensure_schema 트리거 이름 검사 통과
    w.run_once()
    assert fx.post_count("place_order") == 0, "T0가 제어 파일 해제 없이 사라지고 진입이 나갔다"


# 회귀(수정됨): SEC-03 — bot/orders/DESIGN.md §16 R 표
def test_sec03_a_db_write_lock_after_entry_leaves_position_unprotected(tmp_path, ocfg, oclock):
    path = tmp_path / "lock.sqlite3"
    conn_b = db.connect(path, mode=Mode.TESTNET, now_ms=T_MS)
    queue.ensure_schema(conn_b)
    conn_b.execute("PRAGMA busy_timeout = 50")                   # 시험 시간 단축(실제 10초 — 결과는 같다)
    conn_a = db.connect(path, mode=Mode.TESTNET, now_ms=T_MS)
    conn_a.execute("PRAGMA busy_timeout = 50")
    inner = FakeExchange(oclock, mark=MARK)

    def a_grabs_lock(res, *args):                                # 진입 POST 응답 직후(B가 RESPONSE를 쓰기 전)
        conn_a.execute("BEGIN IMMEDIATE")

    ex = Hooked(inner, after={"place_order": a_grabs_lock})
    ex.base_url = inner.base_url  # type: ignore[attr-defined]
    make_approved_intent(conn_a, approved_ms=now_ms(oclock))
    w = W.Worker(conn_b, ocfg, ex, oclock, control_loader=lambda: CTL)
    w.startup()
    try:
        w.run_once()
    except sqlite3.OperationalError:
        pass
    for _ in range(20):                                          # 40초 이상 B 루프가 돌아도(잠금 유지)
        oclock.advance(2_000 * NS_PER_MS)
        try:
            w.run_once()
        except sqlite3.OperationalError:
            pass
    unprotected = inner.position_qty > 0 and not inner.active_conditionals()
    conn_a.execute("ROLLBACK")
    assert not unprotected, "잠금이 잡힌 동안 손절 없는 포지션이 유지됐다"


# 회귀(수정됨): SEC-04 — bot/orders/DESIGN.md §16 R 표
def test_sec04_no_aggregate_loss_limit_against_forged_approvals(oconn, ocfg, fx, oclock):
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    entries = 0
    for k in range(6):
        # 침해된 A: 신선한 APPROVED 신호를 위조(하위 시스템·판단 시각만 바꿔 고유 제약 회피)
        make_approved_intent(oconn, n=(20, 55, 100)[k % 3], approved_ms=now_ms(oclock),
                             decision_ns=T_DECISION_NS + (k + 1) * DAY_NS)
        before = fx.post_count("place_order")
        w.run_once()
        if fx.post_count("place_order") > before:
            entries += 1
        live = queue.live_intent(oconn)
        if live is not None and live["stop_price"] is not None:
            fx.set_mark(float(live["stop_price"]) - 10.0)        # 손절 발동(1R 손실)
        oclock.advance(31_000 * NS_PER_MS)
        w.run_once()                                             # 대조 → CLOSED(stop)
        fx.set_mark(MARK)
    assert entries <= 3, f"한 시간 안에 위조 승인으로 {entries}번 진입·손절(누적 손실 한도 없음)"


# 회귀(수정됨): SEC-05 — bot/orders/DESIGN.md §16 R 표
def test_sec05_future_approved_ms_is_accepted(oconn, ocfg, fx, oclock):
    future = now_ms(oclock) + 7 * 86_400_000
    make_approved_intent(oconn, approved_ms=future)
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    w.run_once()
    assert fx.post_count("place_order") == 0, "일주일 뒤 시각의 승인으로 지금 진입했다"


def test_forged_exit_request_only_reduces_risk(oconn, ocfg, fx, oclock):
    """A가 exit 요청을 위조하면 청산만 일어난다(노출 증가 없음)."""
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    oconn.execute("UPDATE order_intents SET exit_due_ms=? WHERE intent_id=?", (now_ms(oclock), iid))
    w = mk_worker(oconn, ocfg, fx, oclock)
    w.startup()
    w.run_once()
    assert fx.position_qty == 0 and intent(oconn, iid)["state"] == "CLOSED"
    assert all(c.request.side is Side.SELL and c.request.reduce_only for c in fx.calls_for("place_order")[1:])


def test_forged_state_to_requeue_filled_intent_is_blocked_by_exchange_facts(oconn, ocfg, fx, oclock):
    """A가 보유 의도를 QUEUED로 되돌려도(재진입 시도) B는 거래소 포지션을 보고 거부 + T0(추가 진입 없음)."""
    sid, iid, gw = to_verified(oconn, ocfg, fx, oclock)
    oconn.execute("UPDATE signals SET state='APPROVED', approved_ms=? WHERE signal_id=?", (now_ms(oclock), sid))
    oconn.execute("UPDATE order_intents SET state='QUEUED', claimed_ms=NULL, entry_sent_ms=NULL, approved_ms=?,"
                  " filled_qty=NULL, avg_fill_price=NULL, stop_verified_ms=NULL WHERE intent_id=?",
                  (now_ms(oclock), iid))
    row = queue.claim_next(oconn, now_ms=now_ms(oclock))
    assert row is not None
    before = fx.post_count("place_order")
    gw.process_intent(row, CTL)
    assert fx.post_count("place_order") == before and "unknown_position" in halt_reasons(oconn)
    assert len(fx.active_conditionals()) == 1                   # 기존 손절 유지
