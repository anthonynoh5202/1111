"""바이낸스 USDⓈ-M 모의 환경(데모·구 테스트넷) 서명 클라이언트 — 거래소 클라이언트 담당 (DESIGN §11).

규칙 요약(DESIGN §11이 기준)
- Ed25519 서명만. 서명 대상 = 쿼리 문자열(보낸 순서 그대로), signature = urlquote(base64(sig)).
  매개변수 순서는 ccxt ``binance.sign()``과 같다: ``timestamp`` 먼저 → 요청 매개변수 → ``recvWindow`` 끝.
  헤더 X-MBX-APIKEY. GET·DELETE는 쿼리, POST는 form 본문. (시험이 ccxt 참조 구현과 바이트 단위로 대조)
- recvWindow = 5000 고정. timestamp = 로컬 + 측정 오프셋. |오프셋| > max_clock_skew_ms면 서명 요청 금지(CLOCK_SKEW).
- 재시도는 조회(GET)만. 주문 POST·취소 DELETE는 이 클래스 안에서 재전송하지 않는다
  (주문은 결과 모름 → OUTCOME_UNKNOWN, 호출자가 clientOrderId로 조회).
- 오류 분류는 ``types.classify_error`` 하나. 단, 결과 모름 쪽으로만 넓히는 로컬 보정 2개(408, -1006)가 있다(아래 _classify).
- 호스트는 ``OrdersConfig.base_url``(코드 상수표)만, 실서버 호스트·http·리다이렉트 거부.
- 키·서명·전체 쿼리는 로그·예외 어디에도 남기지 않는다. httpx 예외는 ``from None``으로 끊는다(예외 사슬에 URL이 남지 않게).
- ``Secret.reveal()``은 키 로드 줄(생성자)에서만.

PoC 확인 필요(K 항목) — 확인 전에는 두 경로를 모두 받는다
- K2: 조건부 창구 ALGO(/fapi/v1/algoOrder) / LEGACY(/fapi/v1/order type=STOP_MARKET) — 설정 ``conditional_api``.
- K4: algo 응답 필드 이름(type·orderType, algoStatus·status, triggerPrice·stopPrice), priceProtect 값 대소문자
  ('TRUE'/'true'/bool 모두 해석). 요청은 ccxt처럼 ``type``·``triggerPrice``·``priceProtect=false``(소문자).
- K5: algo 주문 '없음' 오류 코드 — -2013만 None 처리, 그 밖 코드는 오류로 올린다(보수적).
- K8: 레버리지·마진 조회 — symbolConfig 먼저, 실패하면 positionRisk v2, 둘 다 실패면 오류.
- K9: positionSide/dual·multiAssetsMargin 조회 실패 = 오류(호출자가 REJECTED + T0).
- K10: 키 출금 권한은 선물 데모 호스트에서 조회할 수 없다 → can_withdraw=None(모름). LIVE 전 필수 확인.
"""
from __future__ import annotations

import base64
import logging
import math
import os
import re
import stat
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import quote, urlencode, urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bot.orders.types import (
    BINANCE_CLIENT_ID_RE,
    ENV_HOSTS,
    ERROR_POLICY,
    LIVE_HOSTS,
    QUOTE_ASSET,
    RECV_WINDOW_MS,
    SYMBOL,
    AccountConfig,
    Balance,
    ConditionalApi,
    ConditionalInfo,
    ConditionalRequest,
    ConditionalStatus,
    ErrorKind,
    ExchangeEnv,
    ExchangeError,
    OrderInfo,
    OrderRequest,
    OrdersConfig,
    OrderStatus,
    OrderType,
    PositionInfo,
    Side,
    SymbolRules,
    TimeInForce,
    WorkingType,
    classify_error,
    format_decimal,
)

if TYPE_CHECKING:  # pragma: no cover
    from bot.config import Secret
    from bot.types import Clock

log = logging.getLogger(__name__)

TIME_RESYNC_MS = 60_000                 # 서버 시각 오프셋 갱신 주기(DESIGN §11)
READ_RETRIES = 2                        # 조회 재시도 횟수(첫 시도 + 2)
READ_BACKOFF_S = (0.25, 1.0)            # 재시도 전 대기(429는 Retry-After 우선)
RETRY_AFTER_MAX_S = 10.0                # Retry-After가 이보다 길면 재시도하지 않고 올린다(루프를 오래 막지 않게)
API_KEY_MAX_LEN = 128
# classify_error 표 밖이지만 '결과 모름'이 분명한 경우(결과 모름 쪽으로만 보정 — fail-closed). types.py 반영 요청(open issue).
_LOCAL_UNKNOWN_HTTP = frozenset({408})          # 요청 시간 초과(게이트웨이) — 처리됐을 수 있음
_LOCAL_UNKNOWN_CODES = frozenset({-1006})       # "Execution status unknown"
_PEM_ARMOR_RE = re.compile(r"-----(BEGIN|END) [A-Z0-9 ]{1,40}-----")
_PEM_BODY_RE = re.compile(r"[A-Za-z0-9+/=]{1,80}")
# 조건부(트리거) 주문 유형 — 일반 주문 목록과 섞이지 않게 분리한다(LEGACY 창구).
_CONDITIONAL_TYPES = frozenset({"STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET"})


# ---------------------------------------------------------------------------
# 키 로드
# ---------------------------------------------------------------------------


def read_pem_secret(path: str | os.PathLike[str]) -> "Secret":
    """개인키 PEM 파일 하나를 읽는다. ``bot.config.read_secret``과 같은 검사(절대 경로·일반 파일·그룹/다른 사용자
    권한 없음·크기 1~4096바이트·UTF-8)를 하되, PEM은 여러 줄이므로 줄마다 'PEM 머리/꼬리 줄' 또는 'base64 줄'이어야 한다(그 밖 공백·제어 문자 거부).
    오류 메시지에는 경로만 쓴다."""
    from bot.config import SECRET_MAX_BYTES, ConfigError, Secret

    p = Path(path)
    if not p.is_absolute():
        raise ConfigError(f"비밀 파일 경로는 절대 경로여야 한다: {p}")
    try:
        st = os.stat(p)
    except FileNotFoundError:
        raise ConfigError(f"비밀 파일이 없다: {p}") from None
    except PermissionError:
        raise ConfigError(f"비밀 파일을 읽을 권한이 없다: {p}") from None
    if not stat.S_ISREG(st.st_mode):
        raise ConfigError(f"비밀 파일이 일반 파일이 아니다: {p}")
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(f"비밀 파일 권한이 너무 넓다(chmod 400 필요, 그룹·다른 사용자 권한 금지): {p}")
    if st.st_size == 0 or st.st_size > SECRET_MAX_BYTES:
        raise ConfigError(f"비밀 파일 크기가 이상하다(1~{SECRET_MAX_BYTES}바이트): {p}")
    try:
        raw = p.read_bytes()
    except PermissionError:
        raise ConfigError(f"비밀 파일을 읽을 권한이 없다: {p}") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigError(f"비밀 파일이 UTF-8이 아니다: {p}") from None
    text = text.replace("\r\n", "\n").strip("\n")
    if not text:
        raise ConfigError(f"비밀 파일이 비어 있다: {p}")
    if not all(_PEM_ARMOR_RE.fullmatch(line) or _PEM_BODY_RE.fullmatch(line) for line in text.split("\n")):
        raise ConfigError(f"비밀 값 안에 공백·제어 문자가 있다(PEM 줄 형식 아님): {p}")
    return Secret(text + "\n")


def load_private_key(pem: "Secret") -> Ed25519PrivateKey:
    """PKCS#8 PEM → Ed25519 개인키. Ed25519가 아니면 ValueError(값을 메시지에 넣지 않는다). 암호 걸린 키도 거부."""
    try:
        data = pem.reveal().encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        raise ValueError("개인키 형식 오류(PEM 텍스트가 아님)") from None
    if b"-----BEGIN PRIVATE KEY-----" not in data:
        raise ValueError("개인키 형식 오류(PKCS#8 'PRIVATE KEY' PEM만 허용)")
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except Exception:  # noqa: BLE001 — 원인 메시지에 키 바이트가 섞일 수 있어 버린다
        raise ValueError("개인키를 읽을 수 없다(PEM·PKCS#8·암호 없음 확인)") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Ed25519 개인키가 아니다(HMAC·RSA·EC 미지원)")
    return key


# ---------------------------------------------------------------------------
# 응답 해석 도우미 (형식이 이상하면 _BadResponse → 호출 종류에 맞는 ExchangeError)
# ---------------------------------------------------------------------------


class _BadResponse(Exception):
    pass


class _HedgeMode(_BadResponse):
    """One-way가 아닌 포지션 행(positionSide LONG/SHORT) — ACCOUNT_MODE로 올린다."""


def _get(d: Any, *keys: str) -> Any:
    if not isinstance(d, dict):
        raise _BadResponse("객체가 아님")
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    raise _BadResponse(f"필드 없음: {keys[0]}")


def _opt(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _num(v: Any) -> float:
    if isinstance(v, bool):
        raise _BadResponse("숫자 아님")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise _BadResponse("숫자 아님") from None
    if not math.isfinite(x):
        raise _BadResponse("유한수 아님")
    return x


def _int(v: Any) -> int:
    if isinstance(v, bool):
        raise _BadResponse("정수 아님")
    try:
        return int(v)
    except (TypeError, ValueError):
        raise _BadResponse("정수 아님") from None


def _bool(v: Any) -> bool:
    """bool 또는 'true'/'false'(대소문자 무관, K4). 그 밖은 형식 오류(느슨하게 참으로 보지 않는다)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    raise _BadResponse("bool 아님")


def _enum(cls: type, v: Any) -> Any:
    try:
        return cls(v)
    except ValueError:
        raise _BadResponse(f"알 수 없는 {cls.__name__} 값") from None


def _margin_type(v: Any) -> str:
    s = str(v).lower()
    if s in ("isolated",):
        return "isolated"
    if s in ("cross", "crossed"):
        return "cross"
    raise _BadResponse("알 수 없는 마진 유형")


def _order_info(d: Any) -> OrderInfo:
    otype = str(_get(d, "type"))
    if otype not in ("LIMIT", "MARKET", "STOP_MARKET"):
        raise _BadResponse("지원하지 않는 주문 유형")
    tif = _opt(d, "timeInForce")
    return OrderInfo(
        client_id=str(_get(d, "clientOrderId")),
        exchange_order_id=str(_get(d, "orderId")),
        symbol=str(_get(d, "symbol")),
        side=_enum(Side, _get(d, "side")),
        type=OrderType(otype),
        status=_enum(OrderStatus, _get(d, "status")),
        orig_qty=_num(_get(d, "origQty")),
        executed_qty=_num(_get(d, "executedQty")),
        avg_price=_num(_opt(d, "avgPrice", default=0.0)),
        price=_num(_opt(d, "price", default=0.0)),
        reduce_only=_bool(_opt(d, "reduceOnly", default=False)),
        close_position=_bool(_opt(d, "closePosition", default=False)),
        time_in_force=None if tif is None else str(tif),
        update_ms=_int(_opt(d, "updateTime", "time", default=0)),
    )


_ALGO_STATUS = {s.value: s for s in ConditionalStatus}
_ALGO_STATUS["CANCELLED"] = ConditionalStatus.CANCELED
# LEGACY(일반 주문 창구의 STOP_MARKET) 상태 → 조건부 상태
_LEGACY_STATUS = {
    "NEW": ConditionalStatus.NEW,
    "PARTIALLY_FILLED": ConditionalStatus.TRIGGERED,
    "FILLED": ConditionalStatus.FINISHED,
    "CANCELED": ConditionalStatus.CANCELED,
    "EXPIRED": ConditionalStatus.EXPIRED,
    "EXPIRED_IN_MATCH": ConditionalStatus.EXPIRED,
    "REJECTED": ConditionalStatus.REJECTED,
}


def _conditional_from_algo(d: Any) -> ConditionalInfo:
    otype = str(_get(d, "orderType", "type"))
    if otype != "STOP_MARKET":
        raise _BadResponse("지원하지 않는 조건부 유형")
    st = str(_get(d, "algoStatus", "status"))
    if st not in _ALGO_STATUS:
        raise _BadResponse("알 수 없는 algo 상태")
    return ConditionalInfo(
        client_algo_id=str(_get(d, "clientAlgoId")),
        algo_id=str(_get(d, "algoId")),
        symbol=str(_get(d, "symbol")),
        side=_enum(Side, _get(d, "side")),
        type=OrderType.STOP_MARKET,
        status=_ALGO_STATUS[st],
        trigger_price=_num(_get(d, "triggerPrice", "stopPrice")),
        close_position=_bool(_get(d, "closePosition")),
        working_type=_enum(WorkingType, _get(d, "workingType")),
        price_protect=_bool(_get(d, "priceProtect")),
        reduce_only=_bool(_opt(d, "reduceOnly", default=False)),
        qty=_num(_opt(d, "quantity", "origQty", default=0.0)),
        update_ms=_int(_opt(d, "updateTime", "createTime", default=0)),
    )


def _conditional_from_legacy(d: Any) -> ConditionalInfo:
    otype = str(_get(d, "type"))
    if otype != "STOP_MARKET":
        raise _BadResponse("지원하지 않는 조건부 유형")
    st = str(_get(d, "status"))
    if st not in _LEGACY_STATUS:
        raise _BadResponse("알 수 없는 주문 상태")
    return ConditionalInfo(
        client_algo_id=str(_get(d, "clientOrderId")),
        algo_id=str(_get(d, "orderId")),
        symbol=str(_get(d, "symbol")),
        side=_enum(Side, _get(d, "side")),
        type=OrderType.STOP_MARKET,
        status=_LEGACY_STATUS[st],
        trigger_price=_num(_get(d, "stopPrice")),
        close_position=_bool(_get(d, "closePosition")),
        working_type=_enum(WorkingType, _get(d, "workingType")),
        price_protect=_bool(_get(d, "priceProtect")),
        reduce_only=_bool(_opt(d, "reduceOnly", default=False)),
        qty=_num(_opt(d, "origQty", default=0.0)),
        update_ms=_int(_opt(d, "updateTime", "time", default=0)),
    )


def _bool_param(v: bool) -> str:
    return "true" if v else "false"      # ccxt urlencode의 bool 변환과 같다


# ---------------------------------------------------------------------------
# 로그 가림 (2중 방어: 로거 수준을 WARNING으로 올리고, 누가 다시 내려도 서명 쿼리를 지운다)
# ---------------------------------------------------------------------------
_SIGNED_QUERY_RE = re.compile(r"\?[^\s\"'<>]*signature=[^\s\"'<>]*")
_HTTP_LOGGERS = ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy")


class _RedactSignedQuery(logging.Filter):
    """서명된 요청 URL의 쿼리(timestamp·signature 포함)를 '?<redacted>'로 바꾼다."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:  # noqa: BLE001 — 형식 오류 기록은 그대로 둔다
            return True
        if "signature=" in text:
            record.msg = _SIGNED_QUERY_RE.sub("?<redacted>", text).replace("signature=", "signature=<redacted>")
            record.args = None
        return True


_REDACT_FILTER = _RedactSignedQuery()


def install_log_redaction() -> None:
    """httpx·httpcore 로거: 수준을 WARNING 이상으로 올리고(요청 URL은 INFO) 서명 가림 필터를 단다(멱등)."""
    for name in _HTTP_LOGGERS:
        lg = logging.getLogger(name)
        if lg.level < logging.WARNING:
            lg.setLevel(logging.WARNING)
        if _REDACT_FILTER not in lg.filters:
            lg.addFilter(_REDACT_FILTER)


# ---------------------------------------------------------------------------
# 클라이언트
# ---------------------------------------------------------------------------


class BinanceFuturesClient:
    """``types.ExchangeClient`` 구현(BTCUSDT 전용). 동기(httpx.Client)."""

    env: ExchangeEnv

    def __init__(self, cfg: OrdersConfig, api_key: "Secret", private_key_pem: "Secret", *, clock: "Clock",
                 http_client: "httpx.Client | None" = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        base = str(cfg.base_url)
        parts = urlsplit(base)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https":
            raise ValueError("거래소 호스트는 https만 허용")
        if host in LIVE_HOSTS or host.endswith(".binance.com") and host not in ENV_HOSTS.values():
            raise ValueError("실서버 호스트 거부(TESTNET은 모의 환경 호스트만)")
        env = ExchangeEnv(cfg.env)
        if host != ENV_HOSTS[env] or parts.port not in (None, 443) or parts.path not in ("", "/") \
                or parts.query or parts.username or parts.password:
            raise ValueError("거래소 호스트는 코드 상수표(ENV_HOSTS)의 값만 허용")
        self.env = env
        self._cfg = cfg
        self._base_url = f"https://{host}"
        self._conditional_api = ConditionalApi(cfg.conditional_api)
        if int(cfg.recv_window_ms) != RECV_WINDOW_MS:
            raise ValueError("recvWindow는 5000 고정")
        self._recv_window = RECV_WINDOW_MS
        self._max_skew_ms = int(cfg.max_clock_skew_ms)
        self._clock = clock
        self._sleep = sleep
        # --- 비밀: 이 두 줄에서만 reveal ---
        key_id = api_key.reveal()
        self._key = load_private_key(private_key_pem)
        if (not isinstance(key_id, str) or not 1 <= len(key_id) <= API_KEY_MAX_LEN
                or not all(0x21 <= ord(c) <= 0x7E for c in key_id)):
            raise ValueError("API 키 형식 오류(인쇄 가능한 ASCII, 공백 없음)")
        self._auth_headers = {"X-MBX-APIKEY": key_id}
        del key_id
        self._http = http_client if http_client is not None else httpx.Client(timeout=float(cfg.http_timeout_s),
                                                                            follow_redirects=False)
        self._owns_http = http_client is None
        self._offset_ms: int | None = None
        self._synced_local_ms: int | None = None
        self.last_rtt_ms: int | None = None
        self.last_signed_ts_ms: int | None = None      # 가장 최근 서명 요청의 timestamp(O-5 도착 기한 계산용)
        install_log_redaction()

    @classmethod
    def from_files(cls, cfg: OrdersConfig, *, clock: "Clock", http_client: "httpx.Client | None" = None,
                   ) -> "BinanceFuturesClient":
        """프로세스 B 시작용: 키 ID는 ``read_secret``, 개인키 PEM은 ``read_pem_secret``으로 읽는다."""
        from bot.config import read_secret

        return cls(cfg, read_secret(cfg.api_key_file), read_pem_secret(cfg.private_key_file), clock=clock,
                   http_client=http_client)

    def __repr__(self) -> str:
        return f"BinanceFuturesClient(env={self.env.value}, base_url={self._base_url})"

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def clock_offset_ms(self) -> int | None:
        return self._offset_ms

    # ------------------------------------------------------------------
    # 시각
    # ------------------------------------------------------------------
    def _local_ms(self) -> int:
        return int(self._clock.now_ns()) // 1_000_000

    def _measure_time(self) -> tuple[int, int]:
        """(serverTime, offset). 왕복 중간값 기준 오프셋 = serverTime − (t0 + t1)/2."""
        t0 = self._local_ms()
        data = self._request("GET", "/fapi/v1/time", [], signed=False)
        t1 = self._local_ms()
        try:
            server = _int(_get(data, "serverTime"))
        except _BadResponse:
            raise ExchangeError(ErrorKind.OUTCOME_UNKNOWN, msg="GET /fapi/v1/time 응답 형식 오류") from None
        offset = server - (t0 + t1) // 2
        self.last_rtt_ms = t1 - t0
        self._offset_ms = offset
        self._synced_local_ms = t1
        return server, offset

    def sync_time(self) -> int:
        """GET /fapi/v1/time 왕복 중간값으로 오프셋(ms) 갱신. |오프셋| > 한도면 ExchangeError(CLOCK_SKEW)."""
        _, offset = self._measure_time()
        if self.last_rtt_ms is not None and self.last_rtt_ms > 2 * self._max_skew_ms:
            # 왕복이 길면 중간값 오프셋의 불확실성(±rtt/2)이 한도를 넘는다 → 측정 무효(조회 실패로 취급, 재시도 가능)
            self._offset_ms = None
            raise ExchangeError(ErrorKind.OUTCOME_UNKNOWN, msg=f"time sync rtt {self.last_rtt_ms}ms too large")
        if abs(offset) > self._max_skew_ms:
            log.warning("서버 시각 오차 %d ms > %d ms — 서명 요청 차단", offset, self._max_skew_ms)
            raise ExchangeError(ErrorKind.CLOCK_SKEW, msg=f"clock offset {offset}ms > {self._max_skew_ms}ms")
        return offset

    def _ensure_time(self) -> int:
        now = self._local_ms()
        if self._offset_ms is None or self._synced_local_ms is None or now - self._synced_local_ms >= TIME_RESYNC_MS \
                or now < self._synced_local_ms:
            self.sync_time()
        assert self._offset_ms is not None
        if abs(self._offset_ms) > self._max_skew_ms:
            raise ExchangeError(ErrorKind.CLOCK_SKEW, msg=f"clock offset {self._offset_ms}ms > {self._max_skew_ms}ms")
        return self._local_ms() + self._offset_ms

    # ------------------------------------------------------------------
    # 서명
    # ------------------------------------------------------------------
    def sign_query(self, params: list[tuple[str, str]]) -> str:
        """'k=v&…&signature=…' (시험용으로 공개). timestamp·recvWindow는 호출자가 넣은 그대로 서명.

        인코딩은 ccxt ``Exchange.urlencode``(urllib ``urlencode(quote_via=quote)``)와 같고, 서명은
        ``encode_uri_component(base64(ed25519(query)), safe="~()*!.'")``와 같다."""
        query = urlencode([(str(k), str(v)) for k, v in params], quote_via=quote)
        sig = base64.b64encode(self._key.sign(query.encode("utf-8"))).decode("ascii")
        return f"{query}&signature={quote(sig, safe='~()*!.' + chr(39))}"

    # ------------------------------------------------------------------
    # 전송
    # ------------------------------------------------------------------
    @staticmethod
    def _classify(http_status: int | None, code: int | None) -> ErrorKind:
        if http_status in _LOCAL_UNKNOWN_HTTP or (code is not None and code in _LOCAL_UNKNOWN_CODES):
            return ErrorKind.OUTCOME_UNKNOWN
        return classify_error(http_status, code)

    def _request(self, method: str, path: str, params: list[tuple[str, str]], *, signed: bool) -> Any:
        """한 요청(조회면 재시도 포함). 성공 JSON을 돌려주거나 ExchangeError를 던진다."""
        is_read = method == "GET"
        attempts = 1 + (READ_RETRIES if is_read else 0)
        last: ExchangeError | None = None
        for i in range(attempts):
            try:
                return self._send_once(method, path, params, signed=signed)
            except ExchangeError as e:
                last = e
                if not is_read or i == attempts - 1 or not ERROR_POLICY[e.kind].retry_read:
                    raise
                if e.kind == ErrorKind.CLOCK_SKEW and e.code != -1021:
                    raise                     # 로컬 오차 차단(전송 안 함)은 재시도해도 같다
                delay = READ_BACKOFF_S[min(i, len(READ_BACKOFF_S) - 1)]
                if e.kind == ErrorKind.RATE_LIMITED and e.retry_after_s is not None:
                    if e.retry_after_s > RETRY_AFTER_MAX_S:
                        raise
                    delay = max(delay, float(e.retry_after_s))
                if e.kind == ErrorKind.CLOCK_SKEW and signed:
                    # -1021: 오프셋을 다시 재고(한도 넘으면 여기서 CLOCK_SKEW) 새 timestamp로 조회 재시도
                    self._offset_ms = None
                log.info("조회 재시도 %s %s (%s) %d/%d", method, path, e.kind.value, i + 1, READ_RETRIES)
                self._sleep(delay)
        assert last is not None  # pragma: no cover
        raise last  # pragma: no cover

    def _send_once(self, method: str, path: str, params: list[tuple[str, str]], *, signed: bool) -> Any:
        headers: dict[str, str] = {}
        body: str | None = None
        if signed:
            ts = self._ensure_time()          # 여기서 실패하면 요청은 나가지 않는다
            full = [("timestamp", str(ts))] + list(params) + [("recvWindow", str(self._recv_window))]
            query = self.sign_query(full)
            self.last_signed_ts_ms = ts
            headers.update(self._auth_headers)
        else:
            query = urlencode(params, quote_via=quote) if params else ""
        url = self._base_url + path
        if method in ("GET", "DELETE"):
            if query:
                url = f"{url}?{query}"
        else:
            body = query
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            resp = self._http.request(method, url, content=body, headers=headers, follow_redirects=False)
        except httpx.HTTPError as exc:
            # 전송 중 실패(타임아웃·연결 끊김): 거래소가 처리했을 수 있다. 예외 사슬을 끊어 URL·서명이 남지 않게.
            kind = type(exc).__name__
            log.warning("%s %s 응답 없음(%s)", method, path, kind)
            raise ExchangeError(ErrorKind.OUTCOME_UNKNOWN, msg=f"{method} {path} no response ({kind})") from None
        return self._handle_response(method, path, resp)

    def _handle_response(self, method: str, path: str, resp: httpx.Response) -> Any:
        status = resp.status_code
        data: Any = None
        parse_ok = True
        try:
            data = resp.json()
        except ValueError:
            parse_ok = False
        code: int | None = None
        msg = ""
        if isinstance(data, dict) and "code" in data:
            try:
                c = int(data["code"])
            except (TypeError, ValueError):
                c = None
            if c is not None and c < 0:
                code = c
                msg = str(data.get("msg", ""))[:120]
        if 200 <= status < 300 and code is None:
            if not parse_ok:
                # 성공 상태인데 본문을 읽을 수 없음: 주문이면 처리됐을 수 있다 → 결과 모름
                raise ExchangeError(ErrorKind.OUTCOME_UNKNOWN, http_status=status, msg=f"{method} {path} bad json")
            return data
        kind = self._classify(status, code)
        retry_after: float | None = None
        ra = resp.headers.get("Retry-After")
        if ra is not None:
            try:
                retry_after = max(0.0, float(ra))
            except ValueError:
                retry_after = None
        log.warning("%s %s 실패 http=%s code=%s kind=%s", method, path, status, code, kind.value)
        raise ExchangeError(kind, http_status=status, code=code, msg=f"{method} {path} {msg}".strip(),
                            retry_after_s=retry_after)

    def _parse(self, fn: Callable[[Any], Any], data: Any, *, what: str, write: bool = False) -> Any:
        """응답 해석. 형식 오류: 주문(쓰기) 응답이면 OUTCOME_UNKNOWN(처리됐을 수 있음), 조회면 UNKNOWN(T0 쪽)."""
        try:
            return fn(data)
        except _BadResponse as e:
            kind = ErrorKind.OUTCOME_UNKNOWN if write else ErrorKind.UNKNOWN
            raise ExchangeError(kind, msg=f"{what} 응답 해석 실패: {e}") from None

    # ------------------------------------------------------------------
    # ExchangeClient — 조회
    # ------------------------------------------------------------------
    def server_time_ms(self) -> int:
        """서버 시각(ms). 오프셋도 갱신하지만 오차가 커도 여기서는 던지지 않는다(호출자가 스냅샷으로 판단)."""
        server, _ = self._measure_time()
        return server

    def symbol_rules(self) -> SymbolRules:
        data = self._request("GET", "/fapi/v1/exchangeInfo", [], signed=False)

        def parse(d: Any) -> SymbolRules:
            syms = _get(d, "symbols")
            if not isinstance(syms, list):
                raise _BadResponse("symbols 목록 아님")
            for s in syms:
                if isinstance(s, dict) and s.get("symbol") == SYMBOL:
                    filters = {f.get("filterType"): f for f in _get(s, "filters") if isinstance(f, dict)}
                    pf, lot, mn = filters.get("PRICE_FILTER"), filters.get("LOT_SIZE"), filters.get("MIN_NOTIONAL")
                    if pf is None or lot is None or mn is None:
                        raise _BadResponse("필터 누락")
                    return SymbolRules(symbol=SYMBOL, tick_size=_num(_get(pf, "tickSize")),
                                       step_size=_num(_get(lot, "stepSize")), min_qty=_num(_get(lot, "minQty")),
                                       min_notional=_num(_get(mn, "notional", "minNotional")),
                                       status=str(_get(s, "status")))
            raise _BadResponse("BTCUSDT 없음")

        return self._parse(parse, data, what="exchangeInfo")

    def _symbol_config(self) -> tuple[int, str]:
        """(레버리지, 마진 유형). K8: symbolConfig → 실패 시 positionRisk v2 → 둘 다 실패면 마지막 오류."""
        first: ExchangeError | None = None
        try:
            data = self._request("GET", "/fapi/v1/symbolConfig", [("symbol", SYMBOL)], signed=True)

            def parse(d: Any) -> tuple[int, str]:
                rows = d if isinstance(d, list) else [d]
                for r in rows:
                    if isinstance(r, dict) and r.get("symbol") == SYMBOL:
                        return _int(_get(r, "leverage")), _margin_type(_get(r, "marginType"))
                raise _BadResponse("BTCUSDT 설정 없음")

            return self._parse(parse, data, what="symbolConfig")
        except ExchangeError as e:
            if e.kind in (ErrorKind.IP_BANNED, ErrorKind.REGION_BLOCKED, ErrorKind.AUTH, ErrorKind.CLOCK_SKEW):
                raise
            first = e
            log.info("symbolConfig 실패(%s) — positionRisk v2로 대체(K8)", e.kind.value)
        data = self._request("GET", "/fapi/v2/positionRisk", [("symbol", SYMBOL)], signed=True)

        def parse2(d: Any) -> tuple[int, str]:
            if not isinstance(d, list):
                raise _BadResponse("목록 아님")
            for r in d:
                if isinstance(r, dict) and r.get("symbol") == SYMBOL:
                    return _int(_get(r, "leverage")), _margin_type(_get(r, "marginType"))
            raise _BadResponse("BTCUSDT 없음")

        try:
            return self._parse(parse2, data, what="positionRisk v2")
        except ExchangeError:
            raise first if first is not None else ExchangeError(ErrorKind.UNKNOWN, msg="레버리지 조회 실패")

    def account_config(self) -> AccountConfig:
        dual = self._request("GET", "/fapi/v1/positionSide/dual", [], signed=True)
        multi = self._request("GET", "/fapi/v1/multiAssetsMargin", [], signed=True)
        lev, mtype = self._symbol_config()
        acct = self._request("GET", "/fapi/v2/account", [], signed=True)

        def parse(_: Any) -> AccountConfig:
            return AccountConfig(
                dual_side_position=_bool(_get(dual, "dualSidePosition")),
                multi_assets_margin=_bool(_get(multi, "multiAssetsMargin")),
                leverage=lev,
                margin_type=mtype,
                can_trade=_bool(_get(acct, "canTrade")),
                # K10: /fapi 계정의 canWithdraw는 '계정' 권한이지 'API 키' 권한이 아니다 → 모름(None)
                can_withdraw=None,
            )

        return self._parse(parse, None, what="account")

    def balance(self) -> Balance:
        data = self._request("GET", "/fapi/v2/balance", [], signed=True)

        def parse(d: Any) -> Balance:
            if not isinstance(d, list):
                raise _BadResponse("목록 아님")
            for r in d:
                if isinstance(r, dict) and r.get("asset") == QUOTE_ASSET:
                    return Balance(asset=QUOTE_ASSET, wallet_balance=_num(_get(r, "balance", "walletBalance")),
                                   available_balance=_num(_get(r, "availableBalance")))
            return Balance(asset=QUOTE_ASSET, wallet_balance=0.0, available_balance=0.0)   # 없음 = 0(방화벽이 거부)

        return self._parse(parse, data, what="balance")

    def mark_price(self) -> float:
        data = self._request("GET", "/fapi/v1/premiumIndex", [("symbol", SYMBOL)], signed=False)

        def parse(d: Any) -> float:
            if isinstance(d, list):
                d = next((r for r in d if isinstance(r, dict) and r.get("symbol") == SYMBOL), None)
            if _get(d, "symbol") != SYMBOL:
                raise _BadResponse("다른 심볼")
            p = _num(_get(d, "markPrice"))
            if p <= 0:
                raise _BadResponse("마크 가격 ≤ 0")
            return p

        return self._parse(parse, data, what="premiumIndex")

    def position(self) -> PositionInfo:
        data = self._request("GET", "/fapi/v3/positionRisk", [("symbol", SYMBOL)], signed=True)

        def parse(d: Any) -> tuple[float, float, int | None, str | None, int]:
            if not isinstance(d, list):
                raise _BadResponse("목록 아님")
            rows = [r for r in d if isinstance(r, dict) and r.get("symbol") == SYMBOL]
            qty, entry, lev, mt, upd = 0.0, 0.0, None, None, 0
            for r in rows:
                side = str(_opt(r, "positionSide", default="BOTH"))
                amt = _num(_get(r, "positionAmt"))
                if side != "BOTH":
                    raise _HedgeMode()
                qty, entry = amt, _num(_opt(r, "entryPrice", default=0.0))
                lev = None if _opt(r, "leverage") is None else _int(r["leverage"])
                mt = None if _opt(r, "marginType") is None else _margin_type(r["marginType"])
                upd = _int(_opt(r, "updateTime", default=0))
            return qty, entry, lev, mt, upd

        try:
            qty, entry, lev, mt, upd = parse(data)
        except _HedgeMode:
            raise ExchangeError(ErrorKind.ACCOUNT_MODE, msg="positionSide != BOTH (Hedge 모드)") from None
        except _BadResponse as e:
            raise ExchangeError(ErrorKind.UNKNOWN, msg=f"positionRisk 응답 해석 실패: {e}") from None
        if lev is None or mt is None:
            lev, mt = self._symbol_config()     # v3는 leverage·marginType을 빼고 줄 수 있다(K8)
        return PositionInfo(symbol=SYMBOL, qty=qty, entry_price=entry, leverage=lev, margin_type=mt, update_ms=upd)

    def _raw_open_orders(self) -> list[Any]:
        data = self._request("GET", "/fapi/v1/openOrders", [("symbol", SYMBOL)], signed=True)
        if not isinstance(data, list):
            raise ExchangeError(ErrorKind.UNKNOWN, msg="openOrders 응답 해석 실패: 목록 아님")
        return data

    def open_orders(self) -> list[OrderInfo]:
        """일반 주문만. LEGACY 창구의 조건부 주문(STOP_MARKET 등)은 ``open_conditional_orders``로 간다
        (대조기가 우리 손절을 '모르는 일반 주문'으로 취소하지 않게). ALGO 모드에서 일반 창구에 STOP_MARKET이
        보이면(있어서는 안 됨) 일반 주문으로 그대로 돌려 대조기가 판단하게 한다."""
        rows = self._raw_open_orders()
        out: list[OrderInfo] = []
        for r in rows:
            t = r.get("type") if isinstance(r, dict) else None
            if self._conditional_api == ConditionalApi.LEGACY and t in _CONDITIONAL_TYPES:
                continue
            out.append(self._parse(_order_info, r, what="openOrders"))
        return out

    def open_conditional_orders(self) -> list[ConditionalInfo]:
        if self._conditional_api == ConditionalApi.ALGO:
            data = self._request("GET", "/fapi/v1/openAlgoOrders", [("symbol", SYMBOL)], signed=True)
            if isinstance(data, dict):          # K4: 목록이 {"orders": [...]}로 싸여 올 수도 있다
                data = _opt(data, "orders", "rows", default=data)
            if not isinstance(data, list):
                raise ExchangeError(ErrorKind.UNKNOWN, msg="openAlgoOrders 응답 해석 실패: 목록 아님")
            return [self._parse(_conditional_from_algo, r, what="openAlgoOrders") for r in data]
        rows = self._raw_open_orders()
        return [self._parse(_conditional_from_legacy, r, what="openOrders(stop)")
                for r in rows if isinstance(r, dict) and r.get("type") in _CONDITIONAL_TYPES]

    # ------------------------------------------------------------------
    # ExchangeClient — 일반 주문
    # ------------------------------------------------------------------
    @staticmethod
    def _check_client_id(cid: str) -> None:
        if not isinstance(cid, str) or not BINANCE_CLIENT_ID_RE.fullmatch(cid):
            raise ExchangeError(ErrorKind.BAD_REQUEST, msg="clientOrderId 형식 위반(로컬 검사, 전송 안 함)")

    @staticmethod
    def order_params(req: OrderRequest) -> list[tuple[str, str]]:
        """POST /fapi/v1/order 매개변수(ccxt create_order_request 순서: symbol, side, newClientOrderId,
        newOrderRespType, type, quantity, price, 그 뒤 timeInForce·reduceOnly). 로컬 형식 검사 포함."""
        def bad(m: str) -> ExchangeError:
            return ExchangeError(ErrorKind.BAD_REQUEST, msg=f"{m}(로컬 검사, 전송 안 함)")

        if req.symbol != SYMBOL:
            raise bad("심볼은 BTCUSDT만")
        BinanceFuturesClient._check_client_id(req.client_id)
        side, otype = Side(req.side), OrderType(req.type)
        if otype not in (OrderType.LIMIT, OrderType.MARKET):
            raise bad("일반 창구는 LIMIT·MARKET만(조건부는 place_conditional)")
        if not (isinstance(req.qty, (int, float)) and not isinstance(req.qty, bool) and math.isfinite(req.qty)
                and req.qty > 0):
            raise bad("수량은 양의 유한수")
        p: list[tuple[str, str]] = [("symbol", SYMBOL), ("side", side.value), ("newClientOrderId", req.client_id),
                                    ("newOrderRespType", "RESULT"), ("type", otype.value),
                                    ("quantity", format_decimal(req.qty))]
        if otype == OrderType.LIMIT:
            if req.price is None or not math.isfinite(float(req.price)) or float(req.price) <= 0 \
                    or req.time_in_force is None:
                raise bad("LIMIT은 가격·timeInForce 필요")
            p.append(("price", format_decimal(float(req.price))))
            p.append(("timeInForce", TimeInForce(req.time_in_force).value))
        elif req.price is not None or req.time_in_force is not None:
            raise bad("MARKET에는 가격·timeInForce 없음")
        if req.reduce_only:
            p.append(("reduceOnly", "true"))
        return p

    def place_order(self, req: OrderRequest) -> OrderInfo:
        """POST /fapi/v1/order (newOrderRespType=RESULT). **재전송하지 않는다**(I15)."""
        params = self.order_params(req)
        data = self._request("POST", "/fapi/v1/order", params, signed=True)
        return self._parse(_order_info, data, what="POST order", write=True)

    def get_order(self, client_id: str) -> OrderInfo | None:
        self._check_client_id(client_id)
        try:
            data = self._request("GET", "/fapi/v1/order", [("symbol", SYMBOL), ("origClientOrderId", client_id)],
                                 signed=True)
        except ExchangeError as e:
            if e.kind == ErrorKind.ORDER_NOT_FOUND:
                return None
            raise
        return self._parse(_order_info, data, what="GET order")

    def cancel_order(self, client_id: str) -> OrderInfo | None:
        """DELETE /fapi/v1/order. -2013 → None. -2011(취소 거부: 없거나 이미 종료) → 조회로 확인해 돌려준다."""
        self._check_client_id(client_id)
        try:
            data = self._request("DELETE", "/fapi/v1/order",
                                 [("symbol", SYMBOL), ("origClientOrderId", client_id)], signed=True)
        except ExchangeError as e:
            if e.kind == ErrorKind.ORDER_NOT_FOUND:
                return None
            if e.kind == ErrorKind.CANCEL_REJECTED:
                return self.get_order(client_id)
            raise
        return self._parse(_order_info, data, what="DELETE order", write=True)

    # ------------------------------------------------------------------
    # ExchangeClient — 조건부(손절)
    # ------------------------------------------------------------------
    def conditional_params(self, req: ConditionalRequest) -> tuple[str, list[tuple[str, str]]]:
        """(경로, 매개변수). ALGO는 ccxt와 같은 순서(symbol, side, clientAlgoId, newOrderRespType, type,
        triggerPrice, closePosition, workingType, priceProtect, algoType). closePosition=true면 quantity·reduceOnly 없음."""
        def bad(m: str) -> ExchangeError:
            return ExchangeError(ErrorKind.BAD_REQUEST, msg=f"{m}(로컬 검사, 전송 안 함)")

        if req.symbol != SYMBOL:
            raise bad("심볼은 BTCUSDT만")
        self._check_client_id(req.client_algo_id)
        if OrderType(req.type) != OrderType.STOP_MARKET:
            raise bad("조건부는 STOP_MARKET만")
        if req.close_position is not True:
            raise bad("손절은 closePosition=true만")
        tp = float(req.trigger_price)
        if not math.isfinite(tp) or tp <= 0:
            raise bad("트리거 가격은 양의 유한수")
        side = Side(req.side).value
        wt = WorkingType(req.working_type).value
        pp = _bool_param(bool(req.price_protect))
        if self._conditional_api == ConditionalApi.ALGO:
            return "/fapi/v1/algoOrder", [
                ("symbol", SYMBOL), ("side", side), ("clientAlgoId", req.client_algo_id),
                ("newOrderRespType", "RESULT"), ("type", "STOP_MARKET"), ("triggerPrice", format_decimal(tp)),
                ("closePosition", "true"), ("workingType", wt), ("priceProtect", pp), ("algoType", "CONDITIONAL"),
            ]
        return "/fapi/v1/order", [
            ("symbol", SYMBOL), ("side", side), ("newClientOrderId", req.client_algo_id),
            ("newOrderRespType", "RESULT"), ("type", "STOP_MARKET"), ("stopPrice", format_decimal(tp)),
            ("closePosition", "true"), ("workingType", wt), ("priceProtect", pp),
        ]

    def _parse_conditional(self, data: Any, *, what: str, write: bool = False) -> ConditionalInfo:
        fn = _conditional_from_algo if self._conditional_api == ConditionalApi.ALGO else _conditional_from_legacy
        return self._parse(fn, data, what=what, write=write)

    def place_conditional(self, req: ConditionalRequest) -> ConditionalInfo:
        """ALGO: POST /fapi/v1/algoOrder / LEGACY: POST /fapi/v1/order. **재전송하지 않는다**(호출자가 같은 ID로 조회 먼저)."""
        path, params = self.conditional_params(req)
        data = self._request("POST", path, params, signed=True)
        return self._parse_conditional(data, what=f"POST {path}", write=True)

    def _conditional_id_param(self, cid: str) -> tuple[str, list[tuple[str, str]]]:
        self._check_client_id(cid)
        if self._conditional_api == ConditionalApi.ALGO:
            return "/fapi/v1/algoOrder", [("symbol", SYMBOL), ("clientAlgoId", cid)]
        return "/fapi/v1/order", [("symbol", SYMBOL), ("origClientOrderId", cid)]

    def get_conditional(self, client_algo_id: str) -> ConditionalInfo | None:
        path, params = self._conditional_id_param(client_algo_id)
        try:
            data = self._request("GET", path, params, signed=True)
        except ExchangeError as e:
            if e.kind == ErrorKind.ORDER_NOT_FOUND:      # K5: algo '없음' 코드 확인 필요 — 다른 코드는 오류로 둔다
                return None
            raise
        return self._parse_conditional(data, what=f"GET {path}")

    def cancel_conditional(self, client_algo_id: str) -> ConditionalInfo | None:
        """DELETE. -2013 → None. ALGO 취소 응답은 {algoId, clientAlgoId, code:"200"}뿐이라 조회로 상태를 돌려준다."""
        path, params = self._conditional_id_param(client_algo_id)
        try:
            data = self._request("DELETE", path, params, signed=True)
        except ExchangeError as e:
            if e.kind == ErrorKind.ORDER_NOT_FOUND:
                return None
            if e.kind == ErrorKind.CANCEL_REJECTED:
                return self.get_conditional(client_algo_id)
            raise
        if self._conditional_api == ConditionalApi.ALGO:
            return self.get_conditional(client_algo_id)
        return self._parse_conditional(data, what=f"DELETE {path}", write=True)
