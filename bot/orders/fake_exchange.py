"""가짜 바이낸스 USDⓈ-M(BTCUSDT) 시뮬레이터 + 장애 주입 — 가짜 거래소 담당 (DESIGN §12).

``types.ExchangeClient``를 구현한다(시험 전용: 게이트웨이·대조·E2E 시험이 실제 클라이언트 대신 쓴다).
이 객체는 '클라이언트 + 거래소'를 한 몸으로 흉내 낸다. 즉 호출 = 요청 전송, 반환 = 응답 수신이다.
프로세스 B를 강제 종료·재시작하는 시험에서도 같은 FakeExchange 객체를 계속 쓴다(거래소 상태는 봇과 무관하게 남는다).

흉내 내는 바이낸스 규칙 (근거: ccxt master ``python/ccxt/binance.py`` 오류 표·algo 응답 예시, 08 §2.5, DESIGN §4·§10·§11)
- One-way 순포지션(부호 있는 수량, 롱 +). 체결마다 평균가·실현 손익·수수료(taker)를 지갑에 반영, 격리 증거금 = |수량|×진입가÷레버리지.
- 일반 주문(POST /fapi/v1/order)
  · LIMIT+IOC: 호가(asks/bids)를 상한가까지 훑어 전량/부분/0 체결, 남은 수량은 만료 → 상태 FILLED 또는 EXPIRED
    (부분 체결도 EXPIRED + executedQty > 0 — K6, 호출자는 executedQty만 믿어야 한다).
  · MARKET: 호가를 가격 제한 없이 훑는다. LIMIT GTC/GTD는 남은 수량이 걸려 있다가 호가가 닿으면 체결(모르는 주문 심기용).
    GTX(post-only)가 즉시 체결될 가격이면 0 체결 EXPIRED.
  · reduceOnly: 줄일 포지션이 없거나 수량이 포지션보다 크면 -2022.
  · 검사 순서: 형식(-1102·-1106·-1116·-1117) → 심볼(-1121) → clientOrderId 문자(-1100) → Hedge 모드(-4061) → 거래 권한(-2015)
    → 심볼 상태(-1013) → 조건부 유형을 일반 창구로(-4120) → 가격 틱(-4014)·가격 배수 한도(-4016) → 수량(-4003·-1111·-4004)
    → 미체결 사이 clientOrderId 중복(-4116) → reduceOnly(-2022) → 최소 명목(-4164, reduceOnly 제외) → 증거금(-2019).
  · clientOrderId 중복 방지는 **미체결 주문 사이에서만**(ARCHITECTURE §5.1.3). 끝난 IOC와 같은 ID로 다시 보내면 **새 주문으로
    체결된다** — 실제 거래소와 같이 '재전송하면 두 번 체결'되는 위험을 그대로 드러낸다. get_order(같은 ID)는 가장 최근 주문.
- 조건부 주문(ALGO: POST /fapi/v1/algoOrder, LEGACY: /fapi/v1/order type=STOP_MARKET)
  · 클라이언트가 LEGACY 창구로 보내고 거래소가 옛 창구를 지원하지 않으면(``legacy_conditional_supported=False``, 기본) -4120.
  · STOP_MARKET만(그 밖 -1116). closePosition=True만 지원(False면 수량이 없어 -1102). 트리거 틱(-4014).
  · 즉시 발동할 가격(SELL: 트리거 ≥ 기준가, BUY: 트리거 ≤ 기준가)이면 -2021. 기준가 = workingType(MARK_PRICE=마크, CONTRACT=최근가=마크).
  · 미체결(NEW) algo 주문 사이 clientAlgoId 중복 -4116(K: algo에도 같은 규칙이라고 가정).
  · 같은 방향 closePosition 조건부 주문이 이미 있으면 -4130(ccxt 오류 표 '-4130': 'An open stop or take profit order with GTE
    and closePosition in the direction is existing').
  · K1 ``prearm_close_position_allowed``: 포지션 0일 때 closePosition 손절 선배치 허용 여부(기본 True, False면 -2022).
  · K7 ``price_protect_false_allowed``: priceProtect=false 허용 여부(기본 True, False면 -1106).
  · 발동: 기준가가 트리거를 넘으면 TRIGGERED → 포지션 전량 시장가(bids/asks) → ``fired_status``(기본 FINISHED, K5).
    포지션이 없을 때 발동하면 EXPIRED(K5·K14 미확인). 발동으로 생긴 실제 주문은 clientOrderId ``algo-<algoId>``(K5 미확인)
    으로 기록된다(``triggered_orders()``).
  · K14 ``auto_cancel_close_position_on_flat``: 포지션이 0이 되면 closePosition algo 주문을 거래소가 자동 취소하는가(기본 False).
  · K5 ``algo_query_retention_ms``: 끝난 algo 주문을 get_conditional로 조회할 수 있는 기간(None = 계속).
- 서명 요청(조회·주문·취소, 공개 시세·서버 시각·exchangeInfo 제외)은 timestamp(= 로컬 시계 + ``client_offset_ms``)가
  서버 시각보다 1000ms 넘게 앞서거나 서버 시각 − timestamp > recvWindow(5000)이면 -1021. **늦게 도착한 요청**(장애
  DELAYED_ARRIVAL)은 도착 시각 기준으로 같은 규칙을 적용해 기한이 지났으면 거래소가 버린다(O-5의 근거를 시험으로 재현).
- 취소: 없는 ID → None(-2013), 이미 끝난 주문 → ExchangeError CANCEL_REJECTED(-2011). 조회: 없으면 None.
- open_orders()는 일반 주문만(LEGACY 창구로 넣은 조건부 주문도 open_conditional_orders()에만 나온다).
- 호가 모형: 기본은 마크를 따라가는 자동 호가(ask = ceil_tick(마크), bid = ask − 1틱, 각 ``depth_btc``). ``set_book``으로
  고정 호가(여러 단계)를 지정할 수 있다. 호가 수량은 체결로 줄지 않는다(주문마다 같은 유동성 — 단순화).
- 조회 재시도: 실제 클라이언트는 조회를 최대 2회 재시도한다(DESIGN §11). 가짜는 기본 0회(장애 횟수를 결정적으로 세기 위해),
  ``read_retries``로 흉내 낼 수 있다(429는 Retry-After만큼 FakeClock을 진행). 주문 POST는 어떤 경우에도 재전송하지 않는다.

장애 주입: ``inject(Fault(...))`` — 종류별 동작은 ``FaultKind`` 주석. 모든 호출(시도)은 ``calls``에 기록된다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable

from bot.orders.types import (
    MAX_LEVERAGE,
    PRICE_TICK,
    QTY_STEP,
    RECV_WINDOW_MS,
    SYMBOL,
    BINANCE_CLIENT_ID_RE,
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
    OrderStatus,
    OrderType,
    PositionInfo,
    Side,
    SymbolRules,
    TimeInForce,
    WorkingType,
    ceil_to_step,
    classify_error,
    env_base_url,
    floor_to_step,
    is_multiple,
)
from bot.types import Clock

NS_PER_MS = 1_000_000
SERVER_AHEAD_LIMIT_MS = 1000          # 바이낸스: timestamp가 서버보다 1000ms 넘게 앞서면 -1021
PERCENT_PRICE_UP = 1.05               # BTCUSDT PERCENT_PRICE multiplierUp(근사) — 넘으면 -4016
PERCENT_PRICE_DOWN = 0.95
_EPS = 1e-12

ORDER_POST_METHODS = ("place_order", "place_conditional")
READ_METHODS = frozenset({"server_time_ms", "symbol_rules", "account_config", "balance", "mark_price", "position",
                          "open_orders", "open_conditional_orders", "get_order", "get_conditional"})
PUBLIC_METHODS = frozenset({"server_time_ms", "symbol_rules", "mark_price"})   # 서명 없음(-1021 검사 없음)
ALL_METHODS = READ_METHODS | {"place_order", "place_conditional", "cancel_order", "cancel_conditional"}


class FaultKind(str, Enum):
    TIMEOUT_BEFORE = "timeout_before"          # 요청이 거래소에 닿지 않음 + OUTCOME_UNKNOWN
    TIMEOUT_AFTER = "timeout_after"            # 처리됨 + 응답 유실(OUTCOME_UNKNOWN)
    DUPLICATE_RESPONSE = "duplicate_response"  # 같은 응답 두 번(params mode='replay' 기본 | 'resend' 요청 두 번 도착)
    PARTIAL_FILL = "partial_fill"              # IOC 일부만 체결(fill_ratio)
    NO_FILL = "no_fill"                        # IOC 체결 0
    REJECT = "reject"                          # code로 확정 거부
    STOP_MISSING = "stop_missing"              # 조건부 주문 접수 응답은 오지만 목록·조회에 없음
    STOP_VANISH = "stop_vanish"                # 이미 있는 조건부 주문이 사라짐(거래소 측 취소)
    STOP_FIELD_IGNORED = "stop_field_ignored"  # triggerPrice가 다른 값으로 저장됨(K4)
    CLOCK_SKEW = "clock_skew"                  # 서버 시각 = 로컬 + offset_ms
    RATE_LIMIT = "rate_limit"                  # 429(Retry-After) → 계속이면 418
    DISCONNECT = "disconnect"                  # 이후 모든 호출 OUTCOME_UNKNOWN
    FILL_DELAY = "fill_delay"                  # 접수됐지만 조회에 delay_ms 뒤에 보임
    ACCOUNT_MODE = "account_mode"              # Hedge·Multi-Asset·cross·레버리지(account로 지정)
    FOREIGN_ORDER = "foreign_order"            # 우리 ID가 아닌 주문을 심음
    FOREIGN_POSITION = "foreign_position"      # 우리 주문 없이 포지션을 심음
    HTTP_STATUS = "http_status"                # 451·403·401·418 등 상태 코드로 거부
    DELAYED_ARRIVAL = "delayed_arrival"        # 요청이 delay_ms 뒤에 거래소에 도착(호출자는 즉시 OUTCOME_UNKNOWN)


# 종류별 적용 대상 메서드(Fault.method가 None일 때). None = 모든 메서드.
_KIND_METHODS: dict[FaultKind, frozenset[str] | None] = {
    FaultKind.PARTIAL_FILL: frozenset({"place_order"}),
    FaultKind.NO_FILL: frozenset({"place_order"}),
    FaultKind.STOP_MISSING: frozenset({"place_conditional"}),
    FaultKind.STOP_FIELD_IGNORED: frozenset({"place_conditional"}),
    FaultKind.FILL_DELAY: frozenset({"place_order", "place_conditional"}),
    FaultKind.DUPLICATE_RESPONSE: frozenset({"place_order", "place_conditional"}),
    FaultKind.DELAYED_ARRIVAL: frozenset({"place_order", "place_conditional", "cancel_order", "cancel_conditional"}),
}
# inject 즉시 상태를 바꾸는 종류(호출에 걸리지 않는다)
_IMMEDIATE_KINDS = frozenset({FaultKind.CLOCK_SKEW, FaultKind.ACCOUNT_MODE, FaultKind.FOREIGN_ORDER,
                              FaultKind.FOREIGN_POSITION, FaultKind.DISCONNECT})


@dataclass
class Fault:
    """장애 하나.

    공통: ``method``(None = 종류가 뜻 있는 모든 메서드), ``times``(적용 횟수, -1 = 계속), ``after_calls``(맞는 호출을 이만큼
    흘려보낸 뒤부터 적용). ``params['client_id']``(정확히) 또는 ``params['client_id_suffix']``(예: '-sl', '-f1')로 주문 ID를
    좁힐 수 있다(주문·조회·취소 호출에만 뜻이 있다).

    종류별
    - TIMEOUT_BEFORE / TIMEOUT_AFTER: 도달 안 함 / 처리 후 응답 유실. 둘 다 ExchangeError(OUTCOME_UNKNOWN, http None).
    - DUPLICATE_RESPONSE: params mode='replay'(기본) — 응답을 그대로 돌려주고 같은 응답을 ``duplicates``에도 넣는다(시험이
      호출자에게 두 번째로 먹여 '한 번 효과'를 확인). mode='resend' — 같은 요청이 거래소에 두 번 도착(두 번째 결과는 버려짐,
      기록은 method '<m>#dup'): 조건부는 -4116으로 막히고, 끝난 IOC는 **다시 체결된다**(실제 규칙).
    - PARTIAL_FILL(fill_ratio) / NO_FILL: IOC·시장가 체결 수량 제한.
    - REJECT: ``code``(필수), ``http_status``(기본 400)로 확정 거부. 요청은 도달했지만 상태 변화 없음.
    - STOP_MISSING: 조건부 주문이 NEW 응답을 돌려주지만 저장되지 않는다(목록·조회에 없음, 발동도 없음).
    - STOP_VANISH: 이 장애가 걸리는 호출 **직전에** 걸려 있던 조건부 주문(params client_id·client_id_suffix로 좁힘)이
      거래소 측에서 CANCELED(params remove=True면 조회에도 없음). method None이면 다음 아무 호출에서.
    - STOP_FIELD_IGNORED: 저장된 트리거 = params 'trigger_price' 또는 요청값 + params 'trigger_offset'(기본 −100.0).
      params 'working_type'·'price_protect'·'close_position'으로 다른 필드도 바꿔 저장할 수 있다.
    - CLOCK_SKEW(즉시·지속): 서버 시각 = 로컬 + offset_ms. 해제는 offset_ms=0으로 다시 주입.
    - RATE_LIMIT: 걸린 호출이 429(Retry-After = params retry_after_s, 기본 1초). 그 창 안에서 다시 호출하면 위반으로 세고,
      위반이 params ban_after(기본 2)회면 418(params ban_ms 동안 모든 호출 418).
    - DISCONNECT(지속): after_calls번의 호출 뒤부터 모든 호출 OUTCOME_UNKNOWN(조회 포함), ``reconnect()``까지. times 무시.
      params reached=True면 주문·취소가 처리된 뒤 응답만 유실(기본 False: 도달 안 함).
    - FILL_DELAY: 주문은 처리되지만 get_order·open_orders·get_conditional·open_conditional_orders에 delay_ms 뒤에 보인다.
      응답은 params respond=True가 아니면 유실(OUTCOME_UNKNOWN) — '결과 모름 → 조회 → GRACE 안 발견' 시나리오.
      params hide_position=True면 포지션 조회도 같은 시간 동안 체결 전 값을 보인다.
    - ACCOUNT_MODE(즉시·지속): params = AccountConfig 필드(dual_side_position·multi_assets_margin·leverage·margin_type·
      can_trade·can_withdraw)를 덮어쓴다.
    - FOREIGN_ORDER(즉시): params conditional=False(기본)면 일반 주문(client_id 'web_foreign1', LIMIT BUY GTC, qty 0.01,
      price 마크×0.9) / True면 조건부(client_id 'web_foreign_sl', SELL STOP_MARKET closePosition, trigger 마크×0.9).
    - FOREIGN_POSITION(즉시): params qty(기본 0.01, 부호 있음)·price(기본 마크)만큼 포지션을 더한다.
    - HTTP_STATUS: ``http_status``(필수)·``code``로 거부(451·403·401·418·5xx 등). 도달 안 함(5xx는 OUTCOME_UNKNOWN 분류).
    - DELAYED_ARRIVAL: 호출자는 즉시 OUTCOME_UNKNOWN. 요청은 delay_ms 뒤 도착해 그때 처리된다. 도착 시각이
      timestamp + recvWindow를 넘었으면 거래소가 -1021로 버린다(기록 method '<m>#late').
    """

    kind: FaultKind
    method: str | None = None        # None = 모든 메서드. 예: 'place_order', 'place_conditional', 'get_order'
    times: int = 1                   # 적용 횟수(-1 = 계속)
    code: int | None = None          # REJECT의 바이낸스 code
    http_status: int | None = None   # HTTP_STATUS·REJECT의 상태 코드(기본 400)
    fill_ratio: float = 0.5          # PARTIAL_FILL
    delay_ms: int = 0                # FILL_DELAY · DELAYED_ARRIVAL
    offset_ms: int = 0               # CLOCK_SKEW
    after_calls: int = 0             # 이 횟수의 호출 뒤부터 적용(DISCONNECT 등)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallRecord:
    ts_ms: int
    method: str
    request: Any
    outcome: str                     # 'ok' | 'error:<ErrorKind>' | 'fault:<FaultKind>'
    reached_exchange: bool           # 요청이 거래소에 도착했나(TIMEOUT_BEFORE·HTTP_STATUS·429면 False)
    client_id: str | None = None     # 주문·조회·취소의 clientOrderId/clientAlgoId


# ---------------------------------------------------------------------------
# 내부 상태
# ---------------------------------------------------------------------------


@dataclass
class _ActiveFault:
    fault: Fault
    remaining: int                   # -1 = 계속
    seen: int = 0                    # 맞는 호출 수(after_calls 비교)


@dataclass
class _Order:
    client_id: str
    order_id: int
    side: Side
    type: OrderType
    status: OrderStatus
    orig_qty: float
    executed_qty: float = 0.0
    cum_quote: float = 0.0
    price: float = 0.0
    reduce_only: bool = False
    close_position: bool = False
    time_in_force: str | None = None
    create_ms: int = 0
    update_ms: int = 0
    visible_ms: int = 0
    origin: str = "api"              # 'api' | 'foreign' | 'algo'

    @property
    def avg_price(self) -> float:
        return round(self.cum_quote / self.executed_qty, 8) if self.executed_qty > _EPS else 0.0

    @property
    def is_open(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)

    def info(self) -> OrderInfo:
        return OrderInfo(client_id=self.client_id, exchange_order_id=str(self.order_id), symbol=SYMBOL,
                         side=self.side, type=self.type, status=self.status, orig_qty=self.orig_qty,
                         executed_qty=_rq(self.executed_qty), avg_price=self.avg_price, price=self.price,
                         reduce_only=self.reduce_only, close_position=self.close_position,
                         time_in_force=self.time_in_force, update_ms=self.update_ms)


@dataclass
class _Algo:
    client_algo_id: str
    algo_id: int
    side: Side
    type: OrderType
    status: ConditionalStatus
    trigger_price: float
    close_position: bool
    working_type: WorkingType
    price_protect: bool
    api: ConditionalApi
    reduce_only: bool = False
    qty: float = 0.0
    create_ms: int = 0
    update_ms: int = 0
    visible_ms: int = 0
    removed: bool = False            # STOP_VANISH remove=True: 조회에도 없음
    actual_order_id: int | None = None
    origin: str = "api"

    def info(self) -> ConditionalInfo:
        return ConditionalInfo(client_algo_id=self.client_algo_id, algo_id=str(self.algo_id), symbol=SYMBOL,
                               side=self.side, type=self.type, status=self.status, trigger_price=self.trigger_price,
                               close_position=self.close_position, working_type=self.working_type,
                               price_protect=self.price_protect, reduce_only=self.reduce_only, qty=self.qty,
                               update_ms=self.update_ms)


@dataclass
class _Pending:
    arrive_ms: int                   # 로컬 시계 기준 도착 시각
    ts_ms: int                       # 서명 timestamp(보낸 시각의 로컬 + client_offset)
    method: str
    request: Any
    client_id: str | None


@dataclass
class _Mods:
    """이번 호출에 걸린 수정형 장애."""

    fill_cap_ratio: float | None = None       # PARTIAL_FILL(0<r<1) / NO_FILL(0)
    stop_missing: bool = False
    field_ignored: Fault | None = None
    fill_delay: Fault | None = None


def _rq(x: float) -> float:
    """수량 정규화(부동소수 잔차 제거)."""
    v = round(float(x), 9)
    return 0.0 if abs(v) < 1e-9 else v


def _fail(code: int, msg: str = "", *, http_status: int = 400) -> ExchangeError:
    return ExchangeError(classify_error(http_status, code), http_status=http_status, code=code, msg=msg)


def _unknown(msg: str) -> ExchangeError:
    return ExchangeError(ErrorKind.OUTCOME_UNKNOWN, http_status=None, code=None, msg=msg)


class FakeExchange:
    """``types.ExchangeClient`` 구현(시험용). 규칙은 모듈 설명 참고."""

    env: ExchangeEnv
    calls: list[CallRecord]

    def __init__(self, clock: Clock, *, env: ExchangeEnv = ExchangeEnv.DEMO, mark: float = 60_000.0,
                 rules: SymbolRules | None = None, account: AccountConfig | None = None,
                 balance: Balance | None = None, conditional_api: ConditionalApi = ConditionalApi.ALGO,
                 base_url: str | None = None,
                 legacy_conditional_supported: bool = False,          # K2
                 prearm_close_position_allowed: bool = True,          # K1
                 price_protect_false_allowed: bool = True,            # K7
                 auto_cancel_close_position_on_flat: bool = False,    # K14
                 fired_status: ConditionalStatus = ConditionalStatus.FINISHED,  # K5
                 algo_query_retention_ms: int | None = None,          # K5
                 depth_btc: float = 100.0, taker_fee: float = 0.0005, maker_fee: float = 0.0002,
                 read_retries: int = 0) -> None:
        self._clock = clock
        self.env = ExchangeEnv(env)
        self._base_url = base_url if base_url is not None else env_base_url(self.env)
        self.conditional_api = ConditionalApi(conditional_api)
        self._rules = rules or SymbolRules(symbol=SYMBOL, tick_size=PRICE_TICK, step_size=QTY_STEP,
                                           min_qty=QTY_STEP, min_notional=5.0, status="TRADING")
        self._account = account or AccountConfig(dual_side_position=False, multi_assets_margin=False,
                                                 leverage=MAX_LEVERAGE, margin_type="isolated", can_trade=True,
                                                 can_withdraw=False)
        bal = balance or Balance(asset="USDT", wallet_balance=10_000.0, available_balance=10_000.0)
        self._wallet = float(bal.wallet_balance)
        self._avail_adjust = float(bal.available_balance) - float(bal.wallet_balance)
        self.legacy_conditional_supported = bool(legacy_conditional_supported)
        self.prearm_close_position_allowed = bool(prearm_close_position_allowed)
        self.price_protect_false_allowed = bool(price_protect_false_allowed)
        self.auto_cancel_close_position_on_flat = bool(auto_cancel_close_position_on_flat)
        self.fired_status = ConditionalStatus(fired_status)
        self.algo_query_retention_ms = algo_query_retention_ms
        self._depth = float(depth_btc)
        self._taker_fee = float(taker_fee)
        self._maker_fee = float(maker_fee)
        self.read_retries = int(read_retries)

        self._mark = self._check_price(mark)
        self._book_asks: list[tuple[float, float]] | None = None   # None = 마크를 따라가는 자동 호가
        self._book_bids: list[tuple[float, float]] | None = None

        self._pos_qty = 0.0
        self._pos_entry = 0.0
        self._pos_update_ms = 0
        self._pos_hidden: list[tuple[int, float, float]] = []       # (보일 시각, 그 전에 보일 qty, entry)
        self.realized_pnl = 0.0
        self.fees_paid = 0.0

        self._orders: list[_Order] = []
        self._algos: list[_Algo] = []
        self._next_order_id = 8_000_000_001
        self._next_algo_id = 3_000_001
        self._pending: list[_Pending] = []

        self._server_offset_ms = 0          # CLOCK_SKEW: 서버 = 로컬 + 이 값
        self.client_offset_ms = 0           # 서명 timestamp = 로컬 + 이 값(실제 클라이언트의 측정 오프셋 흉내)
        self._faults: list[_ActiveFault] = []
        self._disconnect: Fault | None = None
        self._disconnect_countdown = 0
        self._rate_until_ms = 0
        self._rate_violations = 0
        self._rate_fault: Fault | None = None
        self._ban_until_ms = 0

        self.calls = []
        self.duplicates: list[Any] = []     # DUPLICATE_RESPONSE(replay)로 한 번 더 전달될 응답들

    # ------------------------------------------------------------------
    # 시계
    # ------------------------------------------------------------------
    def _local_ms(self) -> int:
        return int(self._clock.now_ns()) // NS_PER_MS

    def _server_ms(self, local_ms: int | None = None) -> int:
        return (self._local_ms() if local_ms is None else local_ms) + self._server_offset_ms

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------
    # 시장·장애 조작 (시험 도우미)
    # ------------------------------------------------------------------
    @staticmethod
    def _check_price(price: float) -> float:
        p = float(price)
        if not math.isfinite(p) or p <= 0:
            raise ValueError("가격은 양의 유한수")
        return p

    def set_mark(self, price: float) -> None:
        """마크 가격 변경 + 걸린 주문 체결·조건부 주문 발동 검사."""
        self._mark = self._check_price(price)
        self._process()

    def set_book(self, asks: list[tuple[float, float]] | None = None,
                 bids: list[tuple[float, float]] | None = None) -> None:
        """고정 호가 지정. 둘 다 None이면 자동 호가(마크 추종)로 되돌린다. 한쪽만 주면 다른 쪽은 자동."""
        def norm(levels: list[tuple[float, float]] | None, reverse: bool) -> list[tuple[float, float]] | None:
            if levels is None:
                return None
            out = [(self._check_price(p), float(q)) for p, q in levels if float(q) > 0]
            return sorted(out, key=lambda x: x[0], reverse=reverse)

        self._book_asks = norm(asks, False)
        self._book_bids = norm(bids, True)
        self._process()

    def tick(self, dt_ms: int = 0) -> None:
        """시계 진행(FakeClock이면) 뒤 늦게 도착한 요청·지연 표시·체결·발동 처리."""
        if dt_ms < 0:
            raise ValueError("dt_ms ≥ 0")
        if dt_ms:
            adv = getattr(self._clock, "advance", None)
            if adv is None:
                raise TypeError("시계를 진행할 수 없다(FakeClock 필요)")
            adv(int(dt_ms) * NS_PER_MS)
        self._process()

    def inject(self, fault: Fault) -> None:
        if not isinstance(fault, Fault):
            raise TypeError("Fault 필요")
        kind = FaultKind(fault.kind)
        if fault.method is not None and fault.method not in ALL_METHODS:
            raise ValueError(f"모르는 메서드: {fault.method}")
        if kind is FaultKind.CLOCK_SKEW:
            self._server_offset_ms = int(fault.offset_ms)
        elif kind is FaultKind.ACCOUNT_MODE:
            self.set_account(**fault.params)
        elif kind is FaultKind.FOREIGN_ORDER:
            self.plant_foreign_order(**fault.params)
        elif kind is FaultKind.FOREIGN_POSITION:
            self.plant_foreign_position(**fault.params)
        elif kind is FaultKind.DISCONNECT:
            self._disconnect = fault
            self._disconnect_countdown = int(fault.after_calls)
        else:
            if kind is FaultKind.REJECT and fault.code is None:
                raise ValueError("REJECT에는 code가 필요")
            if kind is FaultKind.HTTP_STATUS and fault.http_status is None:
                raise ValueError("HTTP_STATUS에는 http_status가 필요")
            if kind is FaultKind.PARTIAL_FILL and not 0.0 <= float(fault.fill_ratio) <= 1.0:
                raise ValueError("fill_ratio는 0..1")
            if fault.times == 0 or fault.times < -1:
                raise ValueError("times는 양수 또는 -1")
            self._faults.append(_ActiveFault(fault=fault, remaining=int(fault.times)))

    def clear_faults(self) -> None:
        """호출형 장애·연결 끊김·레이트 리밋 상태를 모두 푼다(시계 오차·계정 모드는 그대로)."""
        self._faults.clear()
        self.reconnect()
        self._rate_until_ms = 0
        self._rate_violations = 0
        self._ban_until_ms = 0

    def reconnect(self) -> None:
        self._disconnect = None
        self._disconnect_countdown = 0

    def set_clock_skew(self, offset_ms: int) -> None:
        self._server_offset_ms = int(offset_ms)

    def set_account(self, **kw: Any) -> None:
        self._account = replace(self._account, **kw)

    def set_rules(self, **kw: Any) -> None:
        self._rules = replace(self._rules, **kw)

    def set_balance(self, wallet: float, available: float | None = None) -> None:
        self._wallet = float(wallet)
        self._avail_adjust = 0.0 if available is None else float(available) - self._available_raw()

    def plant_foreign_order(self, *, conditional: bool = False, client_id: str | None = None,
                            side: str | Side | None = None, type: str | OrderType | None = None,
                            qty: float = 0.01, price: float | None = None, trigger_price: float | None = None,
                            reduce_only: bool = False, close_position: bool | None = None,
                            time_in_force: str = "GTC") -> None:
        """우리 ID가 아닌 주문을 거래소에 직접 심는다(사람이 웹에서 넣은 주문 흉내). 검사 없이 저장."""
        now = self._local_ms()
        tick = self._rules.tick_size
        if conditional:
            a = _Algo(client_algo_id=client_id or "web_foreign_sl", algo_id=self._new_algo_id(),
                      side=Side(side or Side.SELL), type=OrderType(type or OrderType.STOP_MARKET),
                      status=ConditionalStatus.NEW,
                      trigger_price=trigger_price if trigger_price is not None
                      else floor_to_step(self._mark * 0.9, tick),
                      close_position=True if close_position is None else bool(close_position),
                      working_type=WorkingType.MARK_PRICE, price_protect=False, api=self.conditional_api,
                      reduce_only=bool(reduce_only), qty=0.0 if close_position in (None, True) else float(qty),
                      create_ms=now, update_ms=now, visible_ms=now, origin="foreign")
            self._algos.append(a)
        else:
            o = _Order(client_id=client_id or "web_foreign1", order_id=self._new_order_id(),
                       side=Side(side or Side.BUY), type=OrderType(type or OrderType.LIMIT), status=OrderStatus.NEW,
                       orig_qty=float(qty),
                       price=price if price is not None else floor_to_step(self._mark * 0.9, tick),
                       reduce_only=bool(reduce_only), time_in_force=time_in_force, create_ms=now, update_ms=now,
                       visible_ms=now, origin="foreign")
            self._orders.append(o)
        self._process()

    def plant_foreign_position(self, *, qty: float = 0.01, price: float | None = None) -> None:
        """우리 주문 없이 포지션을 더한다(수수료 없음)."""
        self._apply_fill(Side.BUY if qty > 0 else Side.SELL, abs(float(qty)),
                         self._mark if price is None else float(price), fee_rate=0.0)
        self._after_position_change()

    def vanish_conditional(self, client_algo_id: str | None = None, *, suffix: str | None = None,
                           remove: bool = False) -> int:
        """걸려 있는 조건부 주문을 거래소 측에서 취소(remove=True면 조회에도 없음). 바꾼 수."""
        n = 0
        now = self._local_ms()
        for a in self._algos:
            if a.status is not ConditionalStatus.NEW or a.removed:
                continue
            if client_algo_id is not None and a.client_algo_id != client_algo_id:
                continue
            if suffix is not None and not a.client_algo_id.endswith(suffix):
                continue
            a.status = ConditionalStatus.CANCELED
            a.update_ms = now
            a.removed = bool(remove)
            n += 1
        return n

    # --- 조회 도우미(시험용, 기록되지 않음) ---
    def post_count(self, method: str, *, reached_only: bool = False, client_id: str | None = None) -> int:
        """주문 POST(place_order·place_conditional) 호출 수(시험 도우미). '#dup'·'#late'는 세지 않는다."""
        return sum(1 for c in self.calls
                   if c.method == method and (not reached_only or c.reached_exchange)
                   and (client_id is None or c.client_id == client_id))

    def calls_for(self, method: str) -> list[CallRecord]:
        return [c for c in self.calls if c.method == method]

    @property
    def mark(self) -> float:
        return self._mark

    @property
    def position_qty(self) -> float:
        """숨김 없는 실제 포지션(시험 단언용)."""
        return _rq(self._pos_qty)

    @property
    def server_offset_ms(self) -> int:
        return self._server_offset_ms

    def all_orders(self) -> list[OrderInfo]:
        return [o.info() for o in self._orders]

    def all_conditionals(self) -> list[ConditionalInfo]:
        return [a.info() for a in self._algos]

    def active_conditionals(self) -> list[ConditionalInfo]:
        """숨김(FILL_DELAY) 무시한 실제 NEW 조건부 주문."""
        return [a.info() for a in self._algos if a.status is ConditionalStatus.NEW and not a.removed]

    def triggered_orders(self) -> list[OrderInfo]:
        """조건부 주문 발동으로 생긴 시장가 주문(K5: 실제 연결 방법은 PoC 확인)."""
        return [o.info() for o in self._orders if o.origin == "algo"]

    def pending_count(self) -> int:
        return len(self._pending)

    # ------------------------------------------------------------------
    # 호출 공통 처리
    # ------------------------------------------------------------------
    def _record(self, method: str, request: Any, outcome: str, reached: bool, client_id: str | None,
                ts_ms: int | None = None) -> None:
        self.calls.append(CallRecord(ts_ms=self._local_ms() if ts_ms is None else ts_ms, method=method,
                                     request=request, outcome=outcome, reached_exchange=reached,
                                     client_id=client_id))

    @staticmethod
    def _fault_matches(af: _ActiveFault, method: str, client_id: str | None) -> bool:
        f = af.fault
        kind = FaultKind(f.kind)
        if f.method is not None:
            if f.method != method:
                return False
        else:
            allowed = _KIND_METHODS.get(kind)
            if allowed is not None and method not in allowed:
                return False
        cid = f.params.get("client_id")
        if cid is not None and cid != client_id:
            return False
        suf = f.params.get("client_id_suffix")
        if suf is not None and (client_id is None or not client_id.endswith(suf)):
            return False
        return True

    def _take_faults(self, method: str, client_id: str | None) -> list[Fault]:
        """이번 호출에 걸리는 장애(종류당 최대 1개). 횟수 차감."""
        taken: list[Fault] = []
        kinds: set[FaultKind] = set()
        for af in list(self._faults):
            if not self._fault_matches(af, method, client_id):
                continue
            af.seen += 1
            if af.seen <= af.fault.after_calls:
                continue
            kind = FaultKind(af.fault.kind)
            if kind in kinds:
                continue
            kinds.add(kind)
            taken.append(af.fault)
            if af.remaining > 0:
                af.remaining -= 1
                if af.remaining == 0:
                    self._faults.remove(af)
        return taken

    def _signed_check(self, ts_ms: int, arrive_local_ms: int) -> None:
        server = self._server_ms(arrive_local_ms)
        if ts_ms - server > SERVER_AHEAD_LIMIT_MS or server - ts_ms > RECV_WINDOW_MS:
            raise _fail(-1021, "Timestamp for this request is outside of the recvWindow.")

    def _call(self, method: str, request: Any, fn: Callable[[_Mods], Any], *, client_id: str | None = None) -> Any:
        attempts = 1 + (self.read_retries if method in READ_METHODS else 0)
        for i in range(attempts):
            try:
                return self._call_once(method, request, fn, client_id)
            except ExchangeError as exc:
                last = i == attempts - 1
                if last or not exc.policy.retry_read or exc.kind is ErrorKind.IP_BANNED:
                    raise
                if exc.kind is ErrorKind.RATE_LIMITED and exc.retry_after_s:
                    adv = getattr(self._clock, "advance", None)
                    if adv is not None:
                        adv(int(exc.retry_after_s * 1000) * NS_PER_MS)
        raise AssertionError("도달 불가")  # pragma: no cover

    def _call_once(self, method: str, request: Any, fn: Callable[[_Mods], Any], client_id: str | None) -> Any:
        self._process()
        now = self._local_ms()
        ts = now + self.client_offset_ms

        def fault_out(kind: FaultKind | str, exc: ExchangeError, reached: bool = False) -> ExchangeError:
            self._record(method, request, f"fault:{FaultKind(kind).value}", reached, client_id)
            return exc

        # 1) 418 금지 중 / 429 창 안의 재호출
        if now < self._ban_until_ms:
            raise fault_out(FaultKind.RATE_LIMIT, _fail(-1003, "IP banned", http_status=418))
        if now < self._rate_until_ms:
            self._rate_violations += 1
            rf = self._rate_fault
            ban_after = int(rf.params.get("ban_after", 2)) if rf else 2
            if self._rate_violations >= ban_after:
                ban_ms = int(rf.params.get("ban_ms", 120_000)) if rf else 120_000
                self._ban_until_ms = now + ban_ms
                raise fault_out(FaultKind.RATE_LIMIT, _fail(-1003, "IP banned (418)", http_status=418))
            raise fault_out(FaultKind.RATE_LIMIT, self._rate_error(now))

        # 2) 연결 끊김
        if self._disconnect is not None:
            if self._disconnect_countdown > 0:
                self._disconnect_countdown -= 1
            else:
                reached = bool(self._disconnect.params.get("reached", False)) and method not in READ_METHODS
                if reached:
                    try:
                        fn(_Mods())
                    except ExchangeError:
                        pass
                raise fault_out(FaultKind.DISCONNECT, _unknown("connection reset"), reached)

        faults = self._take_faults(method, client_id)
        by_kind = {FaultKind(f.kind): f for f in faults}

        # 3) 도달 전 장애
        if FaultKind.HTTP_STATUS in by_kind:
            f = by_kind[FaultKind.HTTP_STATUS]
            status = int(f.http_status)  # type: ignore[arg-type]
            exc = ExchangeError(classify_error(status, f.code), http_status=status, code=f.code,
                                msg=f"HTTP {status}")
            raise fault_out(FaultKind.HTTP_STATUS, exc)
        if FaultKind.RATE_LIMIT in by_kind:
            self._rate_fault = by_kind[FaultKind.RATE_LIMIT]
            self._rate_violations = 0
            retry_s = float(self._rate_fault.params.get("retry_after_s", 1.0))
            self._rate_until_ms = now + int(retry_s * 1000)
            raise fault_out(FaultKind.RATE_LIMIT, self._rate_error(now))
        if FaultKind.TIMEOUT_BEFORE in by_kind:
            raise fault_out(FaultKind.TIMEOUT_BEFORE, _unknown("read timeout (not delivered)"))
        if FaultKind.DELAYED_ARRIVAL in by_kind:
            f = by_kind[FaultKind.DELAYED_ARRIVAL]
            self._pending.append(_Pending(arrive_ms=now + int(f.delay_ms), ts_ms=ts, method=method,
                                          request=request, client_id=client_id))
            raise fault_out(FaultKind.DELAYED_ARRIVAL, _unknown("read timeout (in flight)"))
        if FaultKind.REJECT in by_kind:
            f = by_kind[FaultKind.REJECT]
            raise fault_out(FaultKind.REJECT, _fail(int(f.code), "injected reject",  # type: ignore[arg-type]
                                                    http_status=int(f.http_status or 400)), reached=True)
        if FaultKind.STOP_VANISH in by_kind:
            f = by_kind[FaultKind.STOP_VANISH]
            self.vanish_conditional(f.params.get("client_id"), suffix=f.params.get("client_id_suffix"),
                                    remove=bool(f.params.get("remove", False)))

        # 4) 서명 시각 검사(도착 = 지금)
        if method not in PUBLIC_METHODS:
            try:
                self._signed_check(ts, now)
            except ExchangeError as exc:
                self._record(method, request, f"error:{exc.kind.value}", True, client_id)
                raise

        # 5) 처리
        mods = _Mods()
        if FaultKind.NO_FILL in by_kind:
            mods.fill_cap_ratio = 0.0
        elif FaultKind.PARTIAL_FILL in by_kind:
            mods.fill_cap_ratio = float(by_kind[FaultKind.PARTIAL_FILL].fill_ratio)
        mods.stop_missing = FaultKind.STOP_MISSING in by_kind
        mods.field_ignored = by_kind.get(FaultKind.STOP_FIELD_IGNORED)
        mods.fill_delay = by_kind.get(FaultKind.FILL_DELAY)
        try:
            result = fn(mods)
        except ExchangeError as exc:
            self._record(method, request, f"error:{exc.kind.value}", True, client_id)
            raise

        dup = by_kind.get(FaultKind.DUPLICATE_RESPONSE)
        if dup is not None and dup.params.get("mode", "replay") == "resend":
            try:
                fn(_Mods())
                self._record(f"{method}#dup", request, "ok", True, client_id)
            except ExchangeError as exc:
                self._record(f"{method}#dup", request, f"error:{exc.kind.value}", True, client_id)

        # 6) 응답 유실
        if FaultKind.TIMEOUT_AFTER in by_kind:
            raise fault_out(FaultKind.TIMEOUT_AFTER, _unknown("read timeout (processed)"), reached=True)
        if mods.fill_delay is not None and not mods.fill_delay.params.get("respond", False):
            raise fault_out(FaultKind.FILL_DELAY, _unknown("read timeout (processed, delayed)"), reached=True)

        if dup is not None:
            self._record(method, request, f"fault:{FaultKind.DUPLICATE_RESPONSE.value}", True, client_id)
            if dup.params.get("mode", "replay") == "replay":
                self.duplicates.append(result)
        else:
            self._record(method, request, "ok", True, client_id)
        return result

    def _rate_error(self, now: int) -> ExchangeError:
        retry_s = max(0.0, (self._rate_until_ms - now) / 1000.0)
        return ExchangeError(ErrorKind.RATE_LIMITED, http_status=429, code=-1003, msg="Too many requests",
                             retry_after_s=retry_s)

    # ------------------------------------------------------------------
    # 시간 경과 처리: 늦게 도착한 요청 → 걸린 주문 체결 → 조건부 발동
    # ------------------------------------------------------------------
    def _process(self) -> None:
        now = self._local_ms()
        due = sorted((p for p in self._pending if p.arrive_ms <= now), key=lambda p: p.arrive_ms)
        for p in due:
            self._pending.remove(p)
            self._deliver_late(p)
        self._pos_hidden = [h for h in self._pos_hidden if h[0] > now]
        self._match_resting()
        self._check_triggers()

    def _deliver_late(self, p: _Pending) -> None:
        name = f"{p.method}#late"
        try:
            self._signed_check(p.ts_ms, p.arrive_ms)
            handler = {"place_order": self._do_place_order, "place_conditional": self._do_place_conditional,
                       "cancel_order": self._do_cancel_order,
                       "cancel_conditional": self._do_cancel_conditional}[p.method]
            handler(p.request, _Mods(), p.arrive_ms)  # type: ignore[operator]
            self._record(name, p.request, "ok", True, p.client_id, ts_ms=p.arrive_ms)
        except ExchangeError as exc:
            self._record(name, p.request, f"error:{exc.kind.value}", True, p.client_id, ts_ms=p.arrive_ms)

    # ------------------------------------------------------------------
    # 호가·체결
    # ------------------------------------------------------------------
    def _asks(self) -> list[tuple[float, float]]:
        if self._book_asks is not None:
            return self._book_asks
        return [(ceil_to_step(self._mark, self._rules.tick_size), self._depth)]

    def _bids(self) -> list[tuple[float, float]]:
        if self._book_bids is not None:
            return self._book_bids
        ask = ceil_to_step(self._mark, self._rules.tick_size)
        return [(round(ask - self._rules.tick_size, 8), self._depth)]

    def _sweep(self, side: Side, qty: float, limit: float | None) -> list[tuple[float, float]]:
        """호가를 훑어 (가격, 수량) 체결 목록. 호가 수량은 줄이지 않는다."""
        levels = self._asks() if side is Side.BUY else self._bids()
        fills: list[tuple[float, float]] = []
        left = qty
        for price, avail in levels:
            if left <= _EPS:
                break
            if limit is not None and ((side is Side.BUY and price > limit + _EPS)
                                      or (side is Side.SELL and price < limit - _EPS)):
                break
            q = _rq(min(left, avail))
            if q > 0:
                fills.append((price, q))
                left = _rq(left - q)
        return fills

    def _apply_fill(self, side: Side, qty: float, price: float, *, fee_rate: float) -> None:
        signed = qty if side is Side.BUY else -qty
        pos = self._pos_qty
        if pos == 0 or (pos > 0) == (signed > 0):
            new = pos + signed
            self._pos_entry = (abs(pos) * self._pos_entry + qty * price) / abs(new)
            self._pos_qty = _rq(new)
        else:
            closing = min(abs(pos), qty)
            pnl = closing * (price - self._pos_entry) * (1 if pos > 0 else -1)
            self.realized_pnl += pnl
            self._wallet += pnl
            new = _rq(pos + signed)
            if new == 0:
                self._pos_entry = 0.0
            elif (new > 0) != (pos > 0):
                self._pos_entry = price          # 반대로 뒤집힘: 남은 수량은 이번 가격
            self._pos_qty = new
        fee = qty * price * fee_rate
        self.fees_paid += fee
        self._wallet -= fee
        self._pos_update_ms = self._local_ms()

    def _after_position_change(self) -> None:
        if self.auto_cancel_close_position_on_flat and _rq(self._pos_qty) == 0:
            now = self._local_ms()
            for a in self._algos:
                if a.status is ConditionalStatus.NEW and a.close_position:
                    a.status = ConditionalStatus.CANCELED
                    a.update_ms = now

    def _execute(self, o: _Order, fills: list[tuple[float, float]], *, maker: bool = False) -> None:
        for price, q in fills:
            self._apply_fill(o.side, q, price, fee_rate=self._maker_fee if maker else self._taker_fee)
            o.executed_qty = _rq(o.executed_qty + q)
            o.cum_quote += q * price
        if fills:
            self._after_position_change()

    def _match_resting(self) -> None:
        now = self._local_ms()
        for o in self._orders:
            if not o.is_open or o.type is not OrderType.LIMIT:
                continue
            left = _rq(o.orig_qty - o.executed_qty)
            if o.reduce_only:
                left = min(left, self._reducible(o.side))
            if left <= 0:
                continue
            fills = self._sweep(o.side, left, o.price)
            if not fills:
                continue
            self._execute(o, fills, maker=True)
            o.status = OrderStatus.FILLED if _rq(o.orig_qty - o.executed_qty) == 0 else OrderStatus.PARTIALLY_FILLED
            o.update_ms = now

    def _ref_price(self, wt: WorkingType) -> float:
        return self._mark  # 가짜: 최근 체결가 = 마크(CONTRACT_PRICE도 마크로 근사)

    def _check_triggers(self) -> None:
        for a in self._algos:
            if a.status is not ConditionalStatus.NEW or a.removed:
                continue
            ref = self._ref_price(a.working_type)
            hit = ref <= a.trigger_price + _EPS if a.side is Side.SELL else ref >= a.trigger_price - _EPS
            if hit:
                self._fire(a)

    def _reducible(self, side: Side) -> float:
        """side 방향 주문이 줄일 수 있는 포지션 수량."""
        if side is Side.SELL:
            return max(0.0, _rq(self._pos_qty))
        return max(0.0, _rq(-self._pos_qty))

    def _fire(self, a: _Algo) -> None:
        now = self._local_ms()
        a.status = ConditionalStatus.TRIGGERED
        a.update_ms = now
        if a.close_position:
            qty = self._reducible(a.side)
        else:
            qty = min(a.qty, self._reducible(a.side)) if a.reduce_only else a.qty
        if qty <= 0:
            a.status = ConditionalStatus.EXPIRED       # K5·K14: 포지션 없이 발동 → 실제 동작 PoC 확인
            return
        o = _Order(client_id=f"algo-{a.algo_id}", order_id=self._new_order_id(), side=a.side,
                   type=OrderType.MARKET, status=OrderStatus.NEW, orig_qty=_rq(qty),
                   reduce_only=a.reduce_only or a.close_position, close_position=a.close_position,
                   create_ms=now, update_ms=now, visible_ms=now, origin="algo")
        self._orders.append(o)
        self._execute(o, self._sweep(a.side, qty, None))
        o.status = OrderStatus.FILLED if _rq(o.orig_qty - o.executed_qty) == 0 else OrderStatus.EXPIRED
        a.actual_order_id = o.order_id
        a.status = self.fired_status

    def _new_order_id(self) -> int:
        self._next_order_id += 1
        return self._next_order_id

    def _new_algo_id(self) -> int:
        self._next_algo_id += 1
        return self._next_algo_id

    def _available_raw(self) -> float:
        lev = max(1, int(self._account.leverage))
        margin = abs(self._pos_qty) * self._pos_entry / lev
        return self._wallet - margin

    # ------------------------------------------------------------------
    # 주문 처리 본체(검사 순서는 모듈 설명)
    # ------------------------------------------------------------------
    def _common_order_checks(self, symbol: str, client_id: str) -> None:
        if symbol != SYMBOL:
            raise _fail(-1121, "Invalid symbol.")
        if not isinstance(client_id, str) or not BINANCE_CLIENT_ID_RE.fullmatch(client_id):
            raise _fail(-1100, "Illegal characters found in parameter 'newClientOrderId'.")
        if self._account.dual_side_position:
            raise _fail(-4061, "Order's position side does not match user's setting.")
        if not self._account.can_trade:
            raise _fail(-2015, "Invalid API-key, IP, or permissions for action.", http_status=401)
        if self._rules.status != "TRADING":
            raise _fail(-1013, "Symbol is not trading.")

    def _do_place_order(self, req: OrderRequest, mods: _Mods, now: int | None = None) -> OrderInfo:
        now = self._local_ms() if now is None else now
        if not isinstance(req, OrderRequest):
            raise _fail(-1102, "Mandatory parameter was not sent.")
        try:
            side = Side(req.side)
            otype = OrderType(req.type)
        except ValueError:
            raise _fail(-1116, "Invalid orderType or side.") from None
        self._common_order_checks(req.symbol, req.client_id)
        if otype is OrderType.STOP_MARKET:
            raise _fail(-4120, "Order type not supported for this endpoint. Please use the Algo Order API endpoints "
                               "instead.")
        rules = self._rules
        tif: TimeInForce | None = None
        if otype is OrderType.LIMIT:
            if req.price is None or req.time_in_force is None:
                raise _fail(-1102, "Mandatory parameter 'price'/'timeInForce' was not sent.")
            tif = TimeInForce(req.time_in_force)
            price = float(req.price)
            if not math.isfinite(price) or price <= 0 or not is_multiple(price, rules.tick_size):
                raise _fail(-4014, "Price not increased by tick size.")
            if (side is Side.BUY and price > self._mark * PERCENT_PRICE_UP) or \
                    (side is Side.SELL and price < self._mark * PERCENT_PRICE_DOWN):
                raise _fail(-4016, "Limit price can't be higher/lower than mark multiplier cap.")
        else:
            if req.price is not None:
                raise _fail(-1106, "Parameter 'price' sent when not required.")
            price = 0.0
        qty = float(req.qty)
        if not math.isfinite(qty) or qty <= 0:
            raise _fail(-4003, "Quantity less than or equal to zero.")
        if not is_multiple(qty, rules.step_size):
            raise _fail(-1111, "Precision is over the maximum defined for this asset.")
        if qty < rules.min_qty - _EPS:
            raise _fail(-4004, "Quantity less than min quantity.")
        if any(o.is_open and o.client_id == req.client_id for o in self._orders):
            raise _fail(-4116, "ClientOrderId is duplicated.")
        reducible = self._reducible(side)
        if req.reduce_only:
            if reducible <= 0 or qty > reducible + _EPS:
                raise _fail(-2022, "ReduceOnly Order is rejected.")
        else:
            ref = price if otype is OrderType.LIMIT else (self._asks()[0][0] if side is Side.BUY
                                                           else self._bids()[0][0])
            if qty * ref < rules.min_notional - _EPS:
                raise _fail(-4164, f"Order's notional must be no smaller than {rules.min_notional} "
                                   "(unless you choose reduce only).")
            increase = max(0.0, qty - reducible)
            need = increase * ref / max(1, int(self._account.leverage)) + increase * ref * self._taker_fee
            if need > self._available_raw() + self._avail_adjust + _EPS:
                raise _fail(-2019, "Margin is insufficient.")

        o = _Order(client_id=req.client_id, order_id=self._new_order_id(), side=side, type=otype,
                   status=OrderStatus.NEW, orig_qty=_rq(qty), price=price if otype is OrderType.LIMIT else 0.0,
                   reduce_only=bool(req.reduce_only), time_in_force=tif.value if tif else None,
                   create_ms=now, update_ms=now, visible_ms=now)
        if mods.fill_delay is not None:
            o.visible_ms = now + int(mods.fill_delay.delay_ms)
            if mods.fill_delay.params.get("hide_position", False):
                self._pos_hidden.append((o.visible_ms, self._pos_qty, self._pos_entry))
        self._orders.append(o)

        cap = qty
        if mods.fill_cap_ratio is not None:
            cap = floor_to_step(qty * mods.fill_cap_ratio, rules.step_size)
            if mods.fill_cap_ratio > 0 and cap <= 0:
                cap = rules.step_size
        if tif is TimeInForce.GTX and self._sweep(side, qty, price):
            o.status = OrderStatus.EXPIRED            # post-only가 즉시 체결될 가격 → 거절(만료)
            return o.info()
        fills = self._sweep(side, cap, price if otype is OrderType.LIMIT else None) if cap > 0 else []
        self._execute(o, fills)
        filled_all = _rq(o.orig_qty - o.executed_qty) == 0
        if otype is OrderType.MARKET or tif is TimeInForce.IOC:
            o.status = OrderStatus.FILLED if filled_all else OrderStatus.EXPIRED
        else:
            o.status = OrderStatus.FILLED if filled_all else (
                OrderStatus.PARTIALLY_FILLED if o.executed_qty > 0 else OrderStatus.NEW)
        o.update_ms = now
        self._check_triggers()
        return o.info()

    def _do_place_conditional(self, req: ConditionalRequest, mods: _Mods, now: int | None = None) -> ConditionalInfo:
        now = self._local_ms() if now is None else now
        if not isinstance(req, ConditionalRequest):
            raise _fail(-1102, "Mandatory parameter was not sent.")
        if self.conditional_api is ConditionalApi.LEGACY and not self.legacy_conditional_supported:
            raise _fail(-4120, "Order type not supported for this endpoint. Please use the Algo Order API "
                               "endpoints instead.")
        try:
            side = Side(req.side)
            otype = OrderType(req.type)
            wt = WorkingType(req.working_type)
        except ValueError:
            raise _fail(-1116, "Invalid orderType/side/workingType.") from None
        self._common_order_checks(req.symbol, req.client_algo_id)
        if otype is not OrderType.STOP_MARKET:
            raise _fail(-1116, "Invalid orderType.")
        if not req.close_position:
            raise _fail(-1102, "Mandatory parameter 'quantity' was not sent.")
        trig = float(req.trigger_price)
        if not math.isfinite(trig) or trig <= 0 or not is_multiple(trig, self._rules.tick_size):
            raise _fail(-4014, "Price not increased by tick size.")
        if not req.price_protect and not self.price_protect_false_allowed:
            raise _fail(-1106, "Parameter 'priceProtect' sent when not required.")
        ref = self._ref_price(wt)
        if (side is Side.SELL and trig >= ref - _EPS) or (side is Side.BUY and trig <= ref + _EPS):
            raise _fail(-2021, "Order would immediately trigger.")
        active = [a for a in self._algos if a.status is ConditionalStatus.NEW and not a.removed]
        if any(a.client_algo_id == req.client_algo_id for a in active):
            raise _fail(-4116, "ClientOrderId is duplicated.")
        if any(a.close_position and a.side is side for a in active):
            raise _fail(-4130, "An open stop or take profit order with GTE and closePosition in the direction "
                               "is existing.")
        if self._reducible(side) <= 0 and not self.prearm_close_position_allowed:
            raise _fail(-2022, "ReduceOnly Order is rejected.")   # K1 불가 경로의 거부 코드는 PoC 확인 필요

        a = _Algo(client_algo_id=req.client_algo_id, algo_id=self._new_algo_id(), side=side, type=otype,
                  status=ConditionalStatus.NEW, trigger_price=trig, close_position=True, working_type=wt,
                  price_protect=bool(req.price_protect), api=self.conditional_api, create_ms=now, update_ms=now,
                  visible_ms=now)
        response = a.info()                           # 응답은 요청대로(무시된 필드는 조회해야 드러난다)
        if mods.field_ignored is not None:
            p = mods.field_ignored.params
            if "trigger_price" in p:
                a.trigger_price = float(p["trigger_price"])
            else:
                a.trigger_price = round(trig + float(p.get("trigger_offset", -100.0)), 8)
            if "working_type" in p:
                a.working_type = WorkingType(p["working_type"])
            if "price_protect" in p:
                a.price_protect = bool(p["price_protect"])
            if "close_position" in p:
                a.close_position = bool(p["close_position"])
            if p.get("echo", False):
                response = a.info()                   # 응답에도 저장된 값이 드러나는 변형
        if mods.fill_delay is not None:
            a.visible_ms = now + int(mods.fill_delay.delay_ms)
        if mods.stop_missing:
            return response                           # 저장하지 않는다(목록·조회·발동 없음)
        self._algos.append(a)
        self._check_triggers()
        return response

    def _do_cancel_order(self, client_id: str, mods: _Mods | None = None, now: int | None = None) -> OrderInfo | None:
        now = self._local_ms() if now is None else now
        found = [o for o in self._orders if o.client_id == client_id and o.visible_ms <= now]
        if not found:
            return None
        o = next((x for x in reversed(found) if x.is_open), found[-1])
        if not o.is_open:
            raise _fail(-2011, "Unknown order sent.")
        o.status = OrderStatus.CANCELED
        o.update_ms = now
        return o.info()

    def _do_cancel_conditional(self, client_algo_id: str, mods: _Mods | None = None,
                               now: int | None = None) -> ConditionalInfo | None:
        now = self._local_ms() if now is None else now
        found = [a for a in self._algos if a.client_algo_id == client_algo_id and not a.removed]
        if not found:
            return None
        a = next((x for x in reversed(found) if x.status is ConditionalStatus.NEW), found[-1])
        if a.status is not ConditionalStatus.NEW:
            raise _fail(-2011, "Unknown order sent.")
        a.status = ConditionalStatus.CANCELED
        a.update_ms = now
        return a.info()

    # ------------------------------------------------------------------
    # ExchangeClient
    # ------------------------------------------------------------------
    def server_time_ms(self) -> int:
        return self._call("server_time_ms", None, lambda m: self._server_ms())

    def symbol_rules(self) -> SymbolRules:
        return self._call("symbol_rules", None, lambda m: self._rules)

    def account_config(self) -> AccountConfig:
        return self._call("account_config", None, lambda m: self._account)

    def balance(self) -> Balance:
        def f(m: _Mods) -> Balance:
            avail = self._available_raw() + self._avail_adjust
            return Balance(asset="USDT", wallet_balance=round(self._wallet, 8), available_balance=round(avail, 8))
        return self._call("balance", None, f)

    def mark_price(self) -> float:
        return self._call("mark_price", None, lambda m: self._mark)

    def position(self) -> PositionInfo:
        def f(m: _Mods) -> PositionInfo:
            qty, entry = self._pos_qty, self._pos_entry
            now = self._local_ms()
            hidden = [h for h in self._pos_hidden if h[0] > now]
            if hidden:
                _, qty, entry = min(hidden, key=lambda h: h[0])
            return PositionInfo(symbol=SYMBOL, qty=_rq(qty), entry_price=round(entry, 8) if _rq(qty) else 0.0,
                                leverage=int(self._account.leverage), margin_type=self._account.margin_type,
                                update_ms=self._pos_update_ms)
        return self._call("position", None, f)

    def open_orders(self) -> list[OrderInfo]:
        def f(m: _Mods) -> list[OrderInfo]:
            now = self._local_ms()
            return [o.info() for o in self._orders if o.is_open and o.visible_ms <= now]
        return self._call("open_orders", None, f)

    def open_conditional_orders(self) -> list[ConditionalInfo]:
        def f(m: _Mods) -> list[ConditionalInfo]:
            now = self._local_ms()
            return [a.info() for a in self._algos
                    if a.status is ConditionalStatus.NEW and not a.removed and a.visible_ms <= now]
        return self._call("open_conditional_orders", None, f)

    def place_order(self, req: OrderRequest) -> OrderInfo:
        cid = getattr(req, "client_id", None)
        return self._call("place_order", req, lambda m: self._do_place_order(req, m), client_id=cid)

    def get_order(self, client_id: str) -> OrderInfo | None:
        def f(m: _Mods) -> OrderInfo | None:
            now = self._local_ms()
            found = [o for o in self._orders if o.client_id == client_id and o.visible_ms <= now]
            return found[-1].info() if found else None
        return self._call("get_order", client_id, f, client_id=client_id)

    def cancel_order(self, client_id: str) -> OrderInfo | None:
        return self._call("cancel_order", client_id, lambda m: self._do_cancel_order(client_id, m),
                          client_id=client_id)

    def place_conditional(self, req: ConditionalRequest) -> ConditionalInfo:
        cid = getattr(req, "client_algo_id", None)
        return self._call("place_conditional", req, lambda m: self._do_place_conditional(req, m), client_id=cid)

    def get_conditional(self, client_algo_id: str) -> ConditionalInfo | None:
        def f(m: _Mods) -> ConditionalInfo | None:
            now = self._local_ms()
            found = [a for a in self._algos
                     if a.client_algo_id == client_algo_id and not a.removed and a.visible_ms <= now]
            if not found:
                return None
            a = found[-1]
            if (self.algo_query_retention_ms is not None and a.status is not ConditionalStatus.NEW
                    and now - a.update_ms > self.algo_query_retention_ms):
                return None
            return a.info()
        return self._call("get_conditional", client_algo_id, f, client_id=client_algo_id)

    def cancel_conditional(self, client_algo_id: str) -> ConditionalInfo | None:
        return self._call("cancel_conditional", client_algo_id,
                          lambda m: self._do_cancel_conditional(client_algo_id, m), client_id=client_algo_id)
