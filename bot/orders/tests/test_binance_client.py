"""binance_client 시험 — 거래소 클라이언트 담당 (DESIGN §11, §15.2).

전송 계층은 httpx.MockTransport(네트워크 없음). 요청 형태는 ccxt master ``python/ccxt/binance.py``의
``sign()``(12425행 부근, 2026-09-30 조회)·``create_order_request``·``create_order``와 ``base/exchange.py``의
``urlencode``·``encode_uri_component``·``eddsa``를 옮긴 참조 구현(아래 ccxt_*)과 바이트 단위로 대조한다.
"""
from __future__ import annotations

import base64
import logging
import os
import urllib.parse as _urlencode
from typing import Any, Callable

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import SECP256K1, generate_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from bot.config import ConfigError, Secret
from bot.orders import binance_client as bc
from bot.orders.binance_client import BinanceFuturesClient, load_private_key, read_pem_secret
from bot.orders.types import (
    ConditionalApi,
    ConditionalRequest,
    ConditionalStatus,
    ErrorKind,
    ExchangeClient,
    ExchangeEnv,
    ExchangeError,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
    WorkingType,
    make_client_id,
)
from bot.orders.tests.conftest import make_orders_config
from bot.types import FakeClock

# RFC 8032 §7.1 TEST 1 (고정 Ed25519 키)
RFC_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
RFC_PUB = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
RFC_SIG_EMPTY = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
KEY = Ed25519PrivateKey.from_private_bytes(RFC_SEED)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption()).decode()
API_KEY = "TESTAPIKEY0123456789abcdefGHIJKLMNOPqrstuvwxyz"
LOCAL_MS = 1_780_000_000_000
SID = "ABCDEFGHIJKLMNOP"
CID_E = make_client_id(SID, "e1")
CID_SL = make_client_id(SID, "sl")
CID_X = make_client_id(SID, "x1")
DEMO_HOST = "demo-fapi.binance.com"


# ---------------------------------------------------------------------------
# ccxt 참조 구현 (ccxt/base/exchange.py · ccxt/binance.py에서 옮김)
# ---------------------------------------------------------------------------
def ccxt_urlencode(params: dict) -> str:
    newParams = params.copy()
    for key, value in params.items():
        if isinstance(value, bool):
            newParams[key] = 'true' if value else 'false'
    return _urlencode.urlencode(newParams, False, quote_via=_urlencode.quote)


def ccxt_encode_uri_component(uri: str, safe: str = "~()*!.'") -> str:
    return _urlencode.quote(uri, safe=safe)


def ccxt_eddsa(request: bytes, secret: str) -> str:
    private_key = serialization.load_pem_private_key(secret.encode(), None)
    return base64.b64encode(private_key.sign(request)).decode()


def ccxt_sign_query(params: dict, secret: str, timestamp: int, recv_window: int) -> str:
    """binance.sign(): extend({'timestamp': nonce}, params) + recvWindow → urlencode → eddsa → &signature="""
    extended = {'timestamp': timestamp}
    extended.update(params)
    extended['recvWindow'] = recv_window
    query = ccxt_urlencode(extended)
    signature = ccxt_encode_uri_component(ccxt_eddsa(query.encode(), secret))
    return query + '&signature=' + signature


def ccxt_order_request(*, type_: str, side: str, qty: str | None, price: str | None, cid: str,
                       user_params: dict, trigger: str | None = None, algo: bool = False) -> dict:
    """create_order_request(선물·비 PM) + create_order의 algoType 추가를 우리 경우에 맞춰 옮김."""
    request: dict[str, Any] = {'symbol': 'BTCUSDT', 'side': side}
    request['clientAlgoId' if algo else 'newClientOrderId'] = cid
    request['newOrderRespType'] = 'RESULT'
    request['type'] = type_
    if qty is not None:
        request['quantity'] = qty
    if price is not None:
        request['price'] = price
    if trigger is not None:
        request['triggerPrice' if algo else 'stopPrice'] = trigger
    omit = ['type', 'newClientOrderId', 'clientOrderId', 'postOnly', 'stopLossPrice', 'takeProfitPrice',
            'stopPrice', 'triggerPrice']
    request.update({k: v for k, v in user_params.items() if k not in omit})
    if algo:
        request['algoType'] = 'CONDITIONAL'
    return request


# ---------------------------------------------------------------------------
# 가짜 전송
# ---------------------------------------------------------------------------
class Router:
    """(메서드, 경로) → 응답 함수 목록(차례로 소비, 마지막은 반복). 모든 요청을 기록."""

    def __init__(self, clock: FakeClock, server_offset_ms: int = 0) -> None:
        self.clock = clock
        self.server_offset_ms = server_offset_ms
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], list[Callable[[httpx.Request], httpx.Response]]] = {}

    def on(self, method: str, path: str, *handlers: Any) -> "Router":
        hs = []
        for h in handlers:
            if callable(h) and not isinstance(h, httpx.Response):
                hs.append(h)
            else:
                hs.append(lambda req, _r=h: _clone(_r))
        self.routes[(method, path)] = hs
        return self

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key == ("GET", "/fapi/v1/time") and key not in self.routes:
            return httpx.Response(200, json={"serverTime": self.clock.now_ns() // 1_000_000 + self.server_offset_ms})
        hs = self.routes.get(key)
        if not hs:
            return httpx.Response(404, json={"code": -5000, "msg": "no route"})
        h = hs.pop(0) if len(hs) > 1 else hs[0]
        return h(request)

    def calls(self, method: str | None = None, path: str | None = None) -> list[httpx.Request]:
        return [r for r in self.requests if (method is None or r.method == method)
                and (path is None or r.url.path == path)]


def _clone(r: httpx.Response) -> httpx.Response:
    return httpx.Response(r.status_code, headers=r.headers, content=r.content)


def ok(obj: Any) -> httpx.Response:
    return httpx.Response(200, json=obj)


def err(status: int, code: int | None = None, headers: dict | None = None) -> httpx.Response:
    if code is None:
        return httpx.Response(status, headers=headers, text="<html>error</html>")
    return httpx.Response(status, headers=headers, json={"code": code, "msg": f"err {code}"})


def raise_(exc: type[Exception]) -> Callable[[httpx.Request], httpx.Response]:
    def h(req: httpx.Request) -> httpx.Response:
        raise exc("boom " + str(req.url), request=req)  # type: ignore[call-arg]
    return h


class Env:
    def __init__(self, *, offset: int = 0, conditional_api: ConditionalApi = ConditionalApi.ALGO,
                 env: ExchangeEnv = ExchangeEnv.DEMO) -> None:
        self.clock = FakeClock(LOCAL_MS * 1_000_000)
        self.router = Router(self.clock, offset)
        self.sleeps: list[float] = []
        self.cfg = make_orders_config(conditional_api=conditional_api, env=env)
        self.client = BinanceFuturesClient(self.cfg, Secret(API_KEY), Secret(PEM), clock=self.clock,
                                           http_client=httpx.Client(transport=httpx.MockTransport(self.router)),
                                           sleep=self.sleeps.append)


@pytest.fixture
def env() -> Env:
    return Env()


def order_resp(cid: str = CID_E, *, status: str = "FILLED", type_: str = "LIMIT", side: str = "BUY",
               qty: str = "0.010", executed: str = "0.010", avg: str = "60010.0", reduce_only: bool = False,
               **extra: Any) -> dict:
    d = {"orderId": 123456, "symbol": "BTCUSDT", "status": status, "clientOrderId": cid, "price": "60060.0",
         "avgPrice": avg, "origQty": qty, "executedQty": executed, "cumQuote": "600.1", "timeInForce": "IOC",
         "type": type_, "origType": type_, "reduceOnly": reduce_only, "closePosition": False, "side": side,
         "positionSide": "BOTH", "stopPrice": "0", "workingType": "CONTRACT_PRICE", "priceProtect": False,
         "updateTime": LOCAL_MS}
    d.update(extra)
    return d


def algo_resp(cid: str = CID_SL, *, status: str = "NEW", trigger: str = "57000.0", **extra: Any) -> dict:
    d = {"algoId": 3358, "clientAlgoId": cid, "algoType": "CONDITIONAL", "orderType": "STOP_MARKET",
         "symbol": "BTCUSDT", "side": "SELL", "positionSide": "BOTH", "timeInForce": "GTC", "quantity": "0",
         "algoStatus": status, "triggerPrice": trigger, "price": "0", "workingType": "MARK_PRICE",
         "priceMatch": "NONE", "closePosition": True, "priceProtect": False, "reduceOnly": False,
         "createTime": LOCAL_MS, "updateTime": LOCAL_MS, "triggerTime": 0, "goodTillDate": 0}
    d.update(extra)
    return d


ENTRY = OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id=CID_E,
                     price=60060.1, time_in_force=TimeInForce.IOC)
EXIT = OrderRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.MARKET, qty=0.01, client_id=CID_X,
                    reduce_only=True)
STOP = ConditionalRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET, trigger_price=57000.0,
                          client_algo_id=CID_SL)


def split_signed(query: str) -> tuple[str, str]:
    payload, _, sig = query.rpartition("&signature=")
    return payload, sig


def verify(query: str) -> None:
    payload, sig = split_signed(query)
    Ed25519PublicKey.from_public_bytes(RFC_PUB).verify(base64.b64decode(_urlencode.unquote(sig)), payload.encode())


def body_of(r: httpx.Request) -> str:
    return r.content.decode()


# ---------------------------------------------------------------------------
# 키 로드
# ---------------------------------------------------------------------------
def test_load_private_key_rfc8032_vector():
    key = load_private_key(Secret(PEM))
    assert key.sign(b"") == RFC_SIG_EMPTY
    assert key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw) == RFC_PUB


def test_load_private_key_rejects_non_ed25519_and_garbage():
    ec = generate_private_key(SECP256K1()).private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                         serialization.NoEncryption()).decode()
    with pytest.raises(ValueError) as ei:
        load_private_key(Secret(ec))
    assert "BEGIN" not in str(ei.value) and ec[40:80] not in str(ei.value)
    garbage = "-----BEGIN PRIVATE KEY-----\nAAAAsecretbytes\n-----END PRIVATE KEY-----\n"
    with pytest.raises(ValueError) as ei:
        load_private_key(Secret(garbage))
    assert "secretbytes" not in str(ei.value) and ei.value.__cause__ is None
    with pytest.raises(ValueError):
        load_private_key(Secret(RFC_SEED.hex()))       # 날 hex·HMAC 비밀 같은 것 거부
    enc = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.BestAvailableEncryption(b"pw")).decode()
    with pytest.raises(ValueError):
        load_private_key(Secret(enc))


def test_read_pem_secret_checks(tmp_path):
    p = tmp_path / "k.pem"
    p.write_text(PEM)
    os.chmod(p, 0o644)
    with pytest.raises(ConfigError, match="권한"):
        read_pem_secret(p)
    os.chmod(p, 0o400)
    s = read_pem_secret(p)
    assert load_private_key(s).sign(b"") == RFC_SIG_EMPTY
    assert "PRIVATE" not in repr(s)
    with pytest.raises(ConfigError, match="절대"):
        read_pem_secret("k.pem")
    q = tmp_path / "bad.pem"
    q.write_text(PEM.replace("\n-----END", " \t-----END"))
    os.chmod(q, 0o600)
    with pytest.raises(ConfigError, match="공백"):
        read_pem_secret(q)


def test_from_files(tmp_path):
    k = tmp_path / "api"
    k.write_text(API_KEY + "\n")
    p = tmp_path / "pem"
    p.write_text(PEM)
    os.chmod(k, 0o400)
    os.chmod(p, 0o400)
    cfg = make_orders_config(api_key_file=str(k), private_key_file=str(p))
    c = BinanceFuturesClient.from_files(cfg, clock=FakeClock(LOCAL_MS * 1_000_000),
                                        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: ok({}))))
    assert c.base_url == f"https://{DEMO_HOST}"


# ---------------------------------------------------------------------------
# 호스트
# ---------------------------------------------------------------------------
class _Cfg:
    """base_url만 바꾼 설정 대역(OrdersConfig는 호스트를 받지 않으므로 우회 시도를 흉내)."""

    def __init__(self, url: str, env: ExchangeEnv = ExchangeEnv.DEMO) -> None:
        real = make_orders_config(env=env)
        self.__dict__.update({f: getattr(real, f) for f in real.__dataclass_fields__})
        self.base_url = url


@pytest.mark.parametrize("url", ["https://fapi.binance.com", "https://api.binance.com", "https://papi.binance.com",
                                 "https://dapi.binance.com", "https://fapi1.binance.com", "http://demo-fapi.binance.com",
                                 "https://demo-fapi.binance.com.evil.io", "https://testnet.binancefuture.com",
                                 "https://demo-fapi.binance.com:8443", "https://demo-fapi.binance.com/x",
                                 "https://user@demo-fapi.binance.com"])
def test_live_or_foreign_host_rejected(url):
    with pytest.raises(ValueError):
        BinanceFuturesClient(_Cfg(url), Secret(API_KEY), Secret(PEM), clock=FakeClock(0),
                             http_client=httpx.Client(transport=httpx.MockTransport(lambda r: ok({}))))


def test_env_hosts_accepted():
    for e, host in ((ExchangeEnv.DEMO, DEMO_HOST), (ExchangeEnv.TESTNET, "testnet.binancefuture.com")):
        c = Env(env=e).client
        assert c.base_url == f"https://{host}" and c.env == e


def test_bad_api_key_rejected():
    for bad in ("", "has space", "a\r\nX-Evil: 1", "x" * 200):
        with pytest.raises(ValueError):
            BinanceFuturesClient(make_orders_config(), Secret(bad), Secret(PEM), clock=FakeClock(0),
                                 http_client=httpx.Client(transport=httpx.MockTransport(lambda r: ok({}))))


def test_is_exchange_client(env):
    assert isinstance(env.client, ExchangeClient)
    assert API_KEY not in repr(env.client)


def test_redirect_not_followed(env):
    env.router.on("GET", "/fapi/v1/premiumIndex",
                  httpx.Response(302, headers={"Location": "https://fapi.binance.com/fapi/v1/premiumIndex"}))
    with pytest.raises(ExchangeError):
        env.client.mark_price()
    assert all(r.url.host == DEMO_HOST for r in env.router.requests)


# ---------------------------------------------------------------------------
# 서명 벡터 · ccxt 대조
# ---------------------------------------------------------------------------
def test_sign_query_vector_matches_ccxt_and_verifies(env):
    params = [("timestamp", "1780000000000"), ("symbol", "BTCUSDT"), ("side", "BUY"), ("recvWindow", "5000")]
    q = env.client.sign_query(params)
    ref = ccxt_sign_query({"symbol": "BTCUSDT", "side": "BUY"}, PEM, 1780000000000, 5000)
    assert q == ref
    assert q.startswith("timestamp=1780000000000&symbol=BTCUSDT&side=BUY&recvWindow=5000&signature=")
    verify(q)
    assert env.client.sign_query(params) == q                      # 결정적(같은 쿼리 → 같은 서명)
    # 회귀 벡터(RFC 8032 TEST 1 키로 고정)
    _, sig = split_signed(q)
    assert base64.b64decode(_urlencode.unquote(sig)) == KEY.sign(
        b"timestamp=1780000000000&symbol=BTCUSDT&side=BUY&recvWindow=5000")
    assert "+" not in sig and "/" not in sig and "=" not in sig   # encode_uri_component 적용


def test_sign_query_quotes_like_ccxt(env):
    params = [("timestamp", "1"), ("note", "a b/c:d+e"), ("recvWindow", "5000")]
    assert env.client.sign_query(params) == ccxt_sign_query({"note": "a b/c:d+e"}, PEM, 1, 5000)


def _signed_parts(r: httpx.Request) -> tuple[str, list[tuple[str, str]]]:
    q = body_of(r) if r.method == "POST" else r.url.query.decode()
    payload, _ = split_signed(q)
    return q, _urlencode.parse_qsl(payload, keep_blank_values=True)


def test_place_entry_request_shape_matches_ccxt(env):
    env.router.on("POST", "/fapi/v1/order", ok(order_resp()))
    info = env.client.place_order(ENTRY)
    assert info.status == OrderStatus.FILLED and info.executed_qty == pytest.approx(0.01)
    [r] = env.router.calls("POST")
    assert r.url.host == DEMO_HOST and r.url.path == "/fapi/v1/order" and r.url.query == b""
    assert r.headers["X-MBX-APIKEY"] == API_KEY
    assert r.headers["Content-Type"] == "application/x-www-form-urlencoded"
    q, pairs = _signed_parts(r)
    verify(q)
    ts = int(pairs[0][1])
    ref = ccxt_order_request(type_="LIMIT", side="BUY", qty="0.01", price="60060.1", cid=CID_E,
                             user_params={"timeInForce": "IOC"})
    assert q == ccxt_sign_query(ref, PEM, ts, 5000)
    assert [k for k, _ in pairs] == ["timestamp", "symbol", "side", "newClientOrderId", "newOrderRespType", "type",
                                     "quantity", "price", "timeInForce", "recvWindow"]
    assert dict(pairs)["recvWindow"] == "5000" and ts == LOCAL_MS


def test_place_exit_reduce_only_shape(env):
    env.router.on("POST", "/fapi/v1/order", ok(order_resp(CID_X, type_="MARKET", side="SELL", reduce_only=True)))
    info = env.client.place_order(EXIT)
    assert info.reduce_only and info.side == Side.SELL
    q, pairs = _signed_parts(env.router.calls("POST")[0])
    ref = ccxt_order_request(type_="MARKET", side="SELL", qty="0.01", price=None, cid=CID_X,
                             user_params={"reduceOnly": True})
    assert q == ccxt_sign_query(ref, PEM, int(pairs[0][1]), 5000)
    assert "price" not in dict(pairs) and "timeInForce" not in dict(pairs)


def test_place_algo_stop_shape_matches_ccxt(env):
    env.router.on("POST", "/fapi/v1/algoOrder", ok(algo_resp()))
    ci = env.client.place_conditional(STOP)
    assert ci.status == ConditionalStatus.NEW and ci.close_position and ci.trigger_price == 57000.0
    assert ci.working_type == WorkingType.MARK_PRICE and ci.price_protect is False
    [r] = env.router.calls("POST")
    assert r.url.path == "/fapi/v1/algoOrder"
    q, pairs = _signed_parts(r)
    verify(q)
    ref = ccxt_order_request(type_="STOP_MARKET", side="SELL", qty=None, price=None, cid=CID_SL, algo=True,
                             trigger="57000",
                             user_params={"clientAlgoId": CID_SL, "closePosition": True, "workingType": "MARK_PRICE",
                                          "priceProtect": False})
    assert q == ccxt_sign_query(ref, PEM, int(pairs[0][1]), 5000)
    d = dict(pairs)
    assert "quantity" not in d and "reduceOnly" not in d and d["algoType"] == "CONDITIONAL"
    assert d["closePosition"] == "true" and d["priceProtect"] == "false"


def test_place_legacy_stop_shape():
    e = Env(conditional_api=ConditionalApi.LEGACY)
    legacy = order_resp(CID_SL, status="NEW", type_="STOP_MARKET", side="SELL", qty="0", executed="0", avg="0",
                        closePosition=True, stopPrice="57000.0", workingType="MARK_PRICE", priceProtect=False)
    e.router.on("POST", "/fapi/v1/order", ok(legacy))
    ci = e.client.place_conditional(STOP)
    assert ci.status == ConditionalStatus.NEW and ci.trigger_price == 57000.0 and ci.client_algo_id == CID_SL
    q, pairs = _signed_parts(e.router.calls("POST")[0])
    ref = ccxt_order_request(type_="STOP_MARKET", side="SELL", qty=None, price=None, cid=CID_SL, trigger="57000",
                             user_params={"closePosition": True, "workingType": "MARK_PRICE", "priceProtect": False})
    assert q == ccxt_sign_query(ref, PEM, int(pairs[0][1]), 5000)
    assert e.router.calls(path="/fapi/v1/algoOrder") == []


def test_get_and_delete_use_query_not_body(env):
    env.router.on("GET", "/fapi/v1/order", ok(order_resp()))
    env.router.on("DELETE", "/fapi/v1/order", ok(order_resp(status="CANCELED")))
    env.client.get_order(CID_E)
    env.client.cancel_order(CID_E)
    for r in env.router.calls("GET", "/fapi/v1/order") + env.router.calls("DELETE"):
        assert r.content == b"" and "signature=" in r.url.query.decode()
        q, pairs = _signed_parts(r)
        verify(q)
        assert pairs[1:3] == [("symbol", "BTCUSDT"), ("origClientOrderId", CID_E)]
        assert r.headers["X-MBX-APIKEY"] == API_KEY


def test_algo_get_cancel_open_paths(env):
    env.router.on("GET", "/fapi/v1/algoOrder", ok(algo_resp(status="CANCELED")))
    env.router.on("DELETE", "/fapi/v1/algoOrder",
                  ok({"algoId": 3358, "clientAlgoId": CID_SL, "code": "200", "msg": "success"}))
    env.router.on("GET", "/fapi/v1/openAlgoOrders", ok([algo_resp()]))
    assert env.client.cancel_conditional(CID_SL).status == ConditionalStatus.CANCELED
    [d] = env.router.calls("DELETE")
    assert _signed_parts(d)[1][1:3] == [("symbol", "BTCUSDT"), ("clientAlgoId", CID_SL)]
    [o] = env.client.open_conditional_orders()
    assert o.client_algo_id == CID_SL
    assert env.router.calls("GET", "/fapi/v1/openAlgoOrders")[0].url.params["symbol"] == "BTCUSDT"


def test_unsigned_public_endpoints_have_no_key(env):
    env.router.on("GET", "/fapi/v1/premiumIndex", ok({"symbol": "BTCUSDT", "markPrice": "60001.5"}))
    assert env.client.mark_price() == 60001.5
    r = env.router.calls("GET", "/fapi/v1/premiumIndex")[0]
    assert "X-MBX-APIKEY" not in r.headers and "signature" not in r.url.query.decode()


# ---------------------------------------------------------------------------
# 오류 분류
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status,code,kind", [
    (400, -1021, ErrorKind.CLOCK_SKEW),
    (400, -2019, ErrorKind.INSUFFICIENT_MARGIN),
    (400, -4120, ErrorKind.ALGO_ENDPOINT_REQUIRED),
    (400, -4164, ErrorKind.MIN_NOTIONAL),
    (400, -2021, ErrorKind.WOULD_TRIGGER),
    (400, -2022, ErrorKind.REDUCE_ONLY_REJECTED),
    (400, -4116, ErrorKind.DUPLICATE_CLIENT_ID),
    (400, -4061, ErrorKind.ACCOUNT_MODE),
    (400, -4400, ErrorKind.TRADING_RESTRICTED),
    (400, -1003, ErrorKind.RATE_LIMITED),
    (429, -1003, ErrorKind.RATE_LIMITED),
    (418, -1003, ErrorKind.IP_BANNED),
    (451, None, ErrorKind.REGION_BLOCKED),
    (403, None, ErrorKind.REGION_BLOCKED),
    (401, -2015, ErrorKind.AUTH),
    (400, -2014, ErrorKind.AUTH),
    (400, -1022, ErrorKind.AUTH),
    (500, None, ErrorKind.OUTCOME_UNKNOWN),
    (503, -1007, ErrorKind.OUTCOME_UNKNOWN),
    (400, -1007, ErrorKind.OUTCOME_UNKNOWN),
    (400, -1001, ErrorKind.OUTCOME_UNKNOWN),
    (400, -1006, ErrorKind.OUTCOME_UNKNOWN),   # 로컬 보정(결과 모름 쪽)
    (408, None, ErrorKind.OUTCOME_UNKNOWN),    # 로컬 보정
    (400, -1111, ErrorKind.BAD_REQUEST),
    (400, -2010, ErrorKind.BAD_REQUEST),
])
def test_order_post_error_classification_and_no_resend(env, status, code, kind):
    env.router.on("POST", "/fapi/v1/order", err(status, code))
    with pytest.raises(ExchangeError) as ei:
        env.client.place_order(ENTRY)
    assert ei.value.kind == kind and ei.value.http_status == status
    assert len(env.router.calls("POST")) == 1           # 주문 POST는 어떤 오류에도 한 번뿐
    assert env.sleeps == []


def test_error_200_with_negative_code(env):
    env.router.on("POST", "/fapi/v1/order", ok({"code": -2019, "msg": "Margin is insufficient."}))
    with pytest.raises(ExchangeError) as ei:
        env.client.place_order(ENTRY)
    assert ei.value.kind == ErrorKind.INSUFFICIENT_MARGIN


@pytest.mark.parametrize("exc", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError,
                                 httpx.WriteTimeout])
def test_post_transport_failure_is_outcome_unknown_once(env, exc):
    env.router.on("POST", "/fapi/v1/order", raise_(exc))
    with pytest.raises(ExchangeError) as ei:
        env.client.place_order(ENTRY)
    e = ei.value
    assert e.kind == ErrorKind.OUTCOME_UNKNOWN and e.outcome_unknown
    assert e.__cause__ is None and e.__suppress_context__           # 예외 사슬에 URL 없음
    assert "signature" not in str(e) and API_KEY not in str(e)
    assert len(env.router.calls("POST")) == 1


def test_post_bad_json_and_bad_shape_are_outcome_unknown(env):
    env.router.on("POST", "/fapi/v1/order", httpx.Response(200, text="not json"),
                  ok({"orderId": 1}))
    for _ in range(2):
        with pytest.raises(ExchangeError) as ei:
            env.client.place_order(ENTRY)
        assert ei.value.kind == ErrorKind.OUTCOME_UNKNOWN
    assert len(env.router.calls("POST")) == 2   # 호출 2번에 요청 2번(각 1회)


def test_conditional_post_not_resent(env):
    env.router.on("POST", "/fapi/v1/algoOrder", err(502))
    with pytest.raises(ExchangeError) as ei:
        env.client.place_conditional(STOP)
    assert ei.value.kind == ErrorKind.OUTCOME_UNKNOWN
    assert len(env.router.calls("POST")) == 1


def test_legacy_endpoint_minus_4120(env):
    e = Env(conditional_api=ConditionalApi.LEGACY)
    e.router.on("POST", "/fapi/v1/order", err(400, -4120))
    with pytest.raises(ExchangeError) as ei:
        e.client.place_conditional(STOP)
    assert ei.value.kind == ErrorKind.ALGO_ENDPOINT_REQUIRED and ei.value.halts


def test_delete_not_retried(env):
    env.router.on("DELETE", "/fapi/v1/order", err(503))
    with pytest.raises(ExchangeError):
        env.client.cancel_order(CID_E)
    assert len(env.router.calls("DELETE")) == 1


def test_local_validation_sends_nothing(env):
    bads = [
        OrderRequest(symbol="ETHUSDT", side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id=CID_E, price=1.0,
                     time_in_force=TimeInForce.IOC),
        OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id="bad id!", price=1.0,
                     time_in_force=TimeInForce.IOC),
        OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT, qty=0.01, client_id=CID_E),
        OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.STOP_MARKET, qty=0.01, client_id=CID_E),
        OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, qty=float("nan"), client_id=CID_E),
        OrderRequest(symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET, qty=0.01, client_id=CID_E, price=1.0),
    ]
    for b in bads:
        with pytest.raises(ExchangeError) as ei:
            env.client.place_order(b)
        assert ei.value.kind == ErrorKind.BAD_REQUEST
    for c in (ConditionalRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET, trigger_price=1.0,
                                 client_algo_id=CID_SL, close_position=False),
              ConditionalRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.MARKET, trigger_price=1.0,
                                 client_algo_id=CID_SL),
              ConditionalRequest(symbol="BTCUSDT", side=Side.SELL, type=OrderType.STOP_MARKET,
                                 trigger_price=float("inf"), client_algo_id=CID_SL)):
        with pytest.raises(ExchangeError):
            env.client.place_conditional(c)
    assert env.router.requests == []


# ---------------------------------------------------------------------------
# 조회 재시도
# ---------------------------------------------------------------------------
def test_read_retries_5xx_then_succeeds(env):
    env.router.on("GET", "/fapi/v1/order", err(503), err(504), ok(order_resp()))
    assert env.client.get_order(CID_E).client_id == CID_E
    assert len(env.router.calls("GET", "/fapi/v1/order")) == 3
    assert len(env.sleeps) == 2


def test_read_retries_exhausted(env):
    env.router.on("GET", "/fapi/v1/order", raise_(httpx.ReadTimeout))
    with pytest.raises(ExchangeError) as ei:
        env.client.get_order(CID_E)
    assert ei.value.kind == ErrorKind.OUTCOME_UNKNOWN
    assert len(env.router.calls("GET", "/fapi/v1/order")) == 3


def test_read_429_respects_retry_after(env):
    env.router.on("GET", "/fapi/v1/premiumIndex", err(429, -1003, {"Retry-After": "3"}),
                  ok({"symbol": "BTCUSDT", "markPrice": "60000"}))
    assert env.client.mark_price() == 60000.0
    assert env.sleeps == [3.0]


def test_read_429_long_retry_after_not_waited(env):
    env.router.on("GET", "/fapi/v1/premiumIndex", err(429, -1003, {"Retry-After": "120"}))
    with pytest.raises(ExchangeError) as ei:
        env.client.mark_price()
    assert ei.value.kind == ErrorKind.RATE_LIMITED and ei.value.retry_after_s == 120.0
    assert len(env.router.calls("GET", "/fapi/v1/premiumIndex")) == 1 and env.sleeps == []


@pytest.mark.parametrize("status,code", [(418, None), (451, None), (401, -2015), (400, -1111)])
def test_read_no_retry_on_final_errors(env, status, code):
    env.router.on("GET", "/fapi/v1/order", err(status, code, {"Retry-After": "1"}))
    with pytest.raises(ExchangeError):
        env.client.get_order(CID_E)
    assert len(env.router.calls("GET", "/fapi/v1/order")) == 1 and env.sleeps == []


def test_read_minus_1021_resyncs_then_retries(env):
    env.router.on("GET", "/fapi/v1/order", err(400, -1021), ok(order_resp()))
    assert env.client.get_order(CID_E) is not None
    assert len(env.router.calls("GET", "/fapi/v1/time")) == 2       # 처음 동기화 + -1021 뒤 재동기화


def test_post_minus_1021_not_resent(env):
    env.router.on("POST", "/fapi/v1/order", err(400, -1021))
    with pytest.raises(ExchangeError) as ei:
        env.client.place_order(ENTRY)
    assert ei.value.kind == ErrorKind.CLOCK_SKEW and not ei.value.outcome_unknown
    assert len(env.router.calls("POST")) == 1


def test_not_found_returns_none(env):
    env.router.on("GET", "/fapi/v1/order", err(400, -2013))
    env.router.on("DELETE", "/fapi/v1/order", err(400, -2011))
    env.router.on("GET", "/fapi/v1/algoOrder", err(400, -2013))
    env.router.on("DELETE", "/fapi/v1/algoOrder", err(400, -2013))
    assert env.client.get_order(CID_E) is None
    assert env.client.cancel_order(CID_E) is None          # -2011 → 조회 → 없음
    assert env.client.get_conditional(CID_SL) is None
    assert env.client.cancel_conditional(CID_SL) is None
    # get 1번 + cancel(-2011)의 확인 조회 1번 — -2013은 재시도하지 않는다
    assert len(env.router.calls("GET", "/fapi/v1/order")) == 2


def test_cancel_rejected_returns_final_state(env):
    env.router.on("DELETE", "/fapi/v1/order", err(400, -2011))
    env.router.on("GET", "/fapi/v1/order", ok(order_resp(status="FILLED")))
    assert env.client.cancel_order(CID_E).status == OrderStatus.FILLED


# ---------------------------------------------------------------------------
# 시계
# ---------------------------------------------------------------------------
def test_clock_skew_blocks_signed_requests():
    e = Env(offset=1500)
    with pytest.raises(ExchangeError) as ei:
        e.client.sync_time()
    assert ei.value.kind == ErrorKind.CLOCK_SKEW
    with pytest.raises(ExchangeError) as ei:
        e.client.place_order(ENTRY)
    assert ei.value.kind == ErrorKind.CLOCK_SKEW and not ei.value.outcome_unknown
    assert e.router.calls("POST") == []
    assert {r.url.path for r in e.router.requests} == {"/fapi/v1/time"}
    # 조회도 서명 요청은 막힌다
    with pytest.raises(ExchangeError):
        e.client.position()
    assert all(r.url.path == "/fapi/v1/time" for r in e.router.requests)
    # server_time_ms는 던지지 않고 서버 시각을 준다(스냅샷 판단용)
    assert e.client.server_time_ms() == LOCAL_MS + 1500


def test_negative_skew_blocked():
    e = Env(offset=-1200)
    with pytest.raises(ExchangeError) as ei:
        e.client.get_order(CID_E)
    assert ei.value.kind == ErrorKind.CLOCK_SKEW


def test_small_offset_applied_to_timestamp():
    e = Env(offset=300)
    e.router.on("POST", "/fapi/v1/order", ok(order_resp()))
    e.client.place_order(ENTRY)
    _, pairs = _signed_parts(e.router.calls("POST")[0])
    assert int(dict(pairs)["timestamp"]) == LOCAL_MS + 300
    assert e.client.last_signed_ts_ms == LOCAL_MS + 300
    assert e.client.clock_offset_ms == 300


def test_rtt_midpoint_offset():
    e = Env()

    def slow_time(req: httpx.Request) -> httpx.Response:
        e.clock.advance(400 * 1_000_000)        # 왕복 400ms, 서버는 중간(+200ms) 시각을 보고
        return ok({"serverTime": LOCAL_MS + 200})

    e.router.on("GET", "/fapi/v1/time", slow_time)
    assert e.client.sync_time() == 0
    assert e.client.last_rtt_ms == 400


def test_rtt_too_large_invalidates_sync():
    e = Env()

    def slow_time(req: httpx.Request) -> httpx.Response:
        e.clock.advance(3_000 * 1_000_000)
        return ok({"serverTime": e.clock.now_ns() // 1_000_000 - 1_500})

    e.router.on("GET", "/fapi/v1/time", slow_time)
    with pytest.raises(ExchangeError) as ei:
        e.client.place_order(ENTRY)
    assert ei.value.kind == ErrorKind.OUTCOME_UNKNOWN and e.router.calls("POST") == []
    assert e.client.clock_offset_ms is None


def test_local_skew_block_not_retried():
    e = Env(offset=1500)
    with pytest.raises(ExchangeError):
        e.client.get_order(CID_E)
    assert len(e.router.calls("GET", "/fapi/v1/time")) == 1 and e.sleeps == []


def test_time_resync_every_60s(env):
    env.router.on("GET", "/fapi/v1/order", ok(order_resp()))
    env.client.get_order(CID_E)
    env.client.get_order(CID_E)
    assert len(env.router.calls("GET", "/fapi/v1/time")) == 1
    env.clock.advance(61_000 * 1_000_000)
    env.client.get_order(CID_E)
    assert len(env.router.calls("GET", "/fapi/v1/time")) == 2


def test_skew_appearing_later_blocks(env):
    env.router.on("GET", "/fapi/v1/order", ok(order_resp()))
    env.client.get_order(CID_E)
    env.router.server_offset_ms = 5000
    env.clock.advance(60_000 * 1_000_000)
    with pytest.raises(ExchangeError) as ei:
        env.client.place_order(ENTRY)
    assert ei.value.kind == ErrorKind.CLOCK_SKEW and env.router.calls("POST") == []


# ---------------------------------------------------------------------------
# 비밀이 로그·예외에 남지 않음
# ---------------------------------------------------------------------------
def test_no_secrets_in_logs_or_errors(env, caplog):
    caplog.set_level(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.DEBUG)   # 누가 수준을 내려도 필터가 가린다
    env.router.on("POST", "/fapi/v1/order", err(400, -2019), raise_(httpx.ReadTimeout))
    env.router.on("GET", "/fapi/v1/order", err(503))
    errors = []
    for fn in (lambda: env.client.place_order(ENTRY), lambda: env.client.place_order(ENTRY),
               lambda: env.client.get_order(CID_E)):
        with pytest.raises(ExchangeError) as ei:
            fn()
        errors.append(ei.value)
    sigs = [split_signed(_signed_parts(r)[0])[1] for r in env.router.requests if r.url.path != "/fapi/v1/time"]
    text = caplog.text + " ".join(f"{e!s} {e!r} {e.msg}" for e in errors)
    assert sigs
    for s in sigs:
        assert s not in text and _urlencode.unquote(s) not in text
    assert API_KEY not in text and "PRIVATE KEY" not in text and "timestamp=" not in text
    request_logged = [r for r in caplog.records if r.name == "httpx"]
    assert request_logged and any("<redacted>" in r.getMessage() for r in request_logged)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def test_httpx_logger_raised_to_warning():
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    Env()
    assert logging.getLogger("httpx").level >= logging.WARNING


# ---------------------------------------------------------------------------
# 응답 해석
# ---------------------------------------------------------------------------
def test_symbol_rules(env):
    env.router.on("GET", "/fapi/v1/exchangeInfo", ok({"symbols": [
        {"symbol": "ETHUSDT", "status": "TRADING", "filters": []},
        {"symbol": "BTCUSDT", "status": "TRADING", "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10", "minPrice": "556.80"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "100"}]}]}))
    r = env.client.symbol_rules()
    assert (r.symbol, r.tick_size, r.step_size, r.min_qty, r.min_notional, r.status) == \
        ("BTCUSDT", 0.1, 0.001, 0.001, 100.0, "TRADING")


def test_symbol_rules_missing_is_error(env):
    env.router.on("GET", "/fapi/v1/exchangeInfo", ok({"symbols": []}))
    with pytest.raises(ExchangeError) as ei:
        env.client.symbol_rules()
    assert ei.value.kind == ErrorKind.UNKNOWN and ei.value.halts


def _account_routes(env: Env, *, dual: Any = False, multi: Any = False, sym_cfg: Any = None) -> None:
    env.router.on("GET", "/fapi/v1/positionSide/dual", ok({"dualSidePosition": dual}))
    env.router.on("GET", "/fapi/v1/multiAssetsMargin", ok({"multiAssetsMargin": multi}))
    env.router.on("GET", "/fapi/v1/symbolConfig", sym_cfg if sym_cfg is not None else ok(
        [{"symbol": "BTCUSDT", "marginType": "ISOLATED", "isAutoAddMargin": "false", "leverage": 3,
          "maxNotionalValue": "1000000"}]))
    env.router.on("GET", "/fapi/v2/account", ok({"canTrade": True, "canWithdraw": True, "assets": []}))


def test_account_config(env):
    _account_routes(env)
    a = env.client.account_config()
    assert (a.dual_side_position, a.multi_assets_margin, a.leverage, a.margin_type, a.can_trade, a.can_withdraw) == \
        (False, False, 3, "isolated", True, None)


def test_account_config_crossed_and_string_bools(env):
    _account_routes(env, dual="true", sym_cfg=ok([{"symbol": "BTCUSDT", "marginType": "CROSSED", "leverage": 20}]))
    a = env.client.account_config()
    assert a.dual_side_position is True and a.margin_type == "cross" and a.leverage == 20


def test_account_config_symbolconfig_fallback_to_position_risk(env):
    _account_routes(env, sym_cfg=err(400, -5000))
    env.router.on("GET", "/fapi/v2/positionRisk", ok([{"symbol": "BTCUSDT", "positionAmt": "0", "leverage": "3",
                                                       "marginType": "isolated", "positionSide": "BOTH"}]))
    a = env.client.account_config()
    assert a.leverage == 3 and a.margin_type == "isolated"


def test_account_config_both_fail(env):
    _account_routes(env, sym_cfg=err(400, -5000))
    env.router.on("GET", "/fapi/v2/positionRisk", err(400, -5000))
    with pytest.raises(ExchangeError):
        env.client.account_config()


def test_account_config_bad_bool_is_error(env):
    _account_routes(env, dual="maybe")
    with pytest.raises(ExchangeError) as ei:
        env.client.account_config()
    assert ei.value.halts


def test_balance(env):
    env.router.on("GET", "/fapi/v2/balance", ok([{"asset": "BNB", "balance": "1", "availableBalance": "1"},
                                                 {"asset": "USDT", "balance": "1000.5",
                                                  "availableBalance": "900.25"}]))
    b = env.client.balance()
    assert (b.asset, b.wallet_balance, b.available_balance) == ("USDT", 1000.5, 900.25)
    env.router.on("GET", "/fapi/v2/balance", ok([]))
    assert env.client.balance().available_balance == 0.0


def test_mark_price_invalid(env):
    for body in ({"symbol": "BTCUSDT", "markPrice": "0"}, {"symbol": "BTCUSDT", "markPrice": "NaN"},
                 {"symbol": "ETHUSDT", "markPrice": "3000"}):
        env.router.on("GET", "/fapi/v1/premiumIndex", ok(body))
        with pytest.raises(ExchangeError):
            env.client.mark_price()


def test_position_one_way(env):
    env.router.on("GET", "/fapi/v3/positionRisk", ok([{"symbol": "BTCUSDT", "positionSide": "BOTH",
                                                       "positionAmt": "0.010", "entryPrice": "60010.0",
                                                       "updateTime": 5}]))
    env.router.on("GET", "/fapi/v1/symbolConfig", ok([{"symbol": "BTCUSDT", "marginType": "ISOLATED",
                                                       "leverage": 3}]))
    p = env.client.position()
    assert (p.qty, p.entry_price, p.leverage, p.margin_type, p.update_ms) == (0.01, 60010.0, 3, "isolated", 5)


def test_position_empty_is_flat(env):
    env.router.on("GET", "/fapi/v3/positionRisk", ok([]))
    env.router.on("GET", "/fapi/v1/symbolConfig", ok([{"symbol": "BTCUSDT", "marginType": "ISOLATED",
                                                       "leverage": 3}]))
    assert env.client.position().qty == 0.0


def test_position_uses_inline_leverage_when_present(env):
    env.router.on("GET", "/fapi/v3/positionRisk", ok([{"symbol": "BTCUSDT", "positionSide": "BOTH",
                                                       "positionAmt": "-0.002", "entryPrice": "1",
                                                       "leverage": "5", "marginType": "cross"}]))
    p = env.client.position()
    assert p.qty == -0.002 and p.leverage == 5 and p.margin_type == "cross"
    assert env.router.calls(path="/fapi/v1/symbolConfig") == []


def test_position_hedge_mode_is_account_mode_error(env):
    env.router.on("GET", "/fapi/v3/positionRisk", ok([
        {"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.01", "entryPrice": "1"},
        {"symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": "0", "entryPrice": "0"}]))
    with pytest.raises(ExchangeError) as ei:
        env.client.position()
    assert ei.value.kind == ErrorKind.ACCOUNT_MODE


def test_open_orders_algo_mode(env):
    env.router.on("GET", "/fapi/v1/openOrders", ok([order_resp(status="NEW", executed="0")]))
    [o] = env.client.open_orders()
    assert o.status == OrderStatus.NEW and o.executed_qty == 0.0


def test_open_orders_legacy_splits_stops():
    e = Env(conditional_api=ConditionalApi.LEGACY)
    stop = order_resp(CID_SL, status="NEW", type_="STOP_MARKET", side="SELL", qty="0", executed="0", avg="0",
                      closePosition=True, stopPrice="57000", workingType="MARK_PRICE", priceProtect="FALSE")
    e.router.on("GET", "/fapi/v1/openOrders", ok([order_resp("foreign-1", status="NEW", executed="0"), stop]))
    orders = e.client.open_orders()
    assert [o.client_id for o in orders] == ["foreign-1"]
    [c] = e.client.open_conditional_orders()
    assert c.client_algo_id == CID_SL and c.status == ConditionalStatus.NEW and c.price_protect is False


def test_unsupported_order_type_is_error(env):
    env.router.on("GET", "/fapi/v1/openOrders", ok([order_resp("x", status="NEW", type_="TRAILING_STOP_MARKET")]))
    with pytest.raises(ExchangeError) as ei:
        env.client.open_orders()
    assert ei.value.halts


def test_algo_status_and_field_variants(env):
    # K4·K5: status/type 필드 이름 변형과 priceProtect 대문자 문자열
    alt = algo_resp(status="TRIGGERED", priceProtect="TRUE")
    alt["type"] = alt.pop("orderType")
    alt["status"] = alt.pop("algoStatus")
    env.router.on("GET", "/fapi/v1/algoOrder", ok(alt))
    c = env.client.get_conditional(CID_SL)
    assert c.status == ConditionalStatus.TRIGGERED and c.price_protect is True


def test_algo_response_field_mismatch_parsed_faithfully(env):
    # 거래소가 triggerPrice를 다르게 저장(K4) — 클라이언트는 받은 값을 그대로 돌려줘 게이트웨이가 대조하게
    env.router.on("POST", "/fapi/v1/algoOrder", ok(algo_resp(trigger="56000.0")))
    assert env.client.place_conditional(STOP).trigger_price == 56000.0


def test_algo_post_unparseable_is_outcome_unknown(env):
    env.router.on("POST", "/fapi/v1/algoOrder", ok({"algoId": 1, "clientAlgoId": CID_SL}))
    with pytest.raises(ExchangeError) as ei:
        env.client.place_conditional(STOP)
    assert ei.value.kind == ErrorKind.OUTCOME_UNKNOWN


def test_ioc_partial_fill_executed_qty(env):
    env.router.on("POST", "/fapi/v1/order", ok(order_resp(status="EXPIRED", executed="0.004")))
    info = env.client.place_order(ENTRY)
    assert info.status == OrderStatus.EXPIRED and info.executed_qty == pytest.approx(0.004)


def test_get_order_non_object_response_is_unknown(env):
    # 응답 JSON이 아닌 형식(리스트)이면 조회는 UNKNOWN(T0 쪽)
    env.router.on("GET", "/fapi/v1/order", ok([1, 2]))
    with pytest.raises(ExchangeError) as ei:
        env.client.get_order(CID_E)
    assert ei.value.kind == ErrorKind.UNKNOWN


def test_module_constants():
    assert bc.READ_RETRIES == 2 and bc.TIME_RESYNC_MS == 60_000
