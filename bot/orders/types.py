"""주문 프로세스(B) 공용 자료형·상태·상수·인터페이스 — 설계 담당 소유 (bot/orders/DESIGN.md).

원칙
- 이 파일은 거래소 호출·DB·시계를 모른다(순수 자료형과 규칙). 바이낸스 실제 클라이언트(binance_client)와
  가짜 거래소(fake_exchange)는 둘 다 ``ExchangeClient`` Protocol 모양을 따른다. 게이트웨이·대조기는 Protocol에만 의존한다.
- 주문 의도(order intent) 상태 머신의 허용 전이는 ``INTENT_TRANSITIONS`` 하나만이 기준이다(queue.transition이 검사).
- 값의 단위: 시각 int ms(UTC), 가격 USDT float, 수량 BTC float. 거래소로 보내는 숫자 문자열 변환은 클라이언트의 책임
  (``format_decimal``로 지수 표기 없이).
- 확인하지 못한 거래소 동작은 'PoC 확인 필요(K 항목)'로 표시하고 설정으로 두 경로를 모두 지원한다(DESIGN §9).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, fields
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from bot.types import SIGNAL_ID_RE

# ---------------------------------------------------------------------------
# 코드 상수 (설정 ① 층: 설정으로는 조이는 방향만 — ARCHITECTURE §7.1)
# ---------------------------------------------------------------------------
SYMBOL = "BTCUSDT"                      # I3: 심볼은 이것 하나
QUOTE_ASSET = "USDT"
MAX_LEVERAGE = 3                        # I4
RECV_WINDOW_MS = 5000                   # 고정(늘리지 않는다, PLAN D12). 서명 timestamp + 이 값이 '도착 기한'
MAX_CLOCK_SKEW_MS = 1000                # |서버 − 로컬| 상한(T0)
STOP_DEADLINE_MS = 5000                 # I2: 진입 체결 → 손절 '조회로 확인'까지 상한(손절 없이 열린 시간)
STOP_PLACE_ATTEMPTS = 3                 # 손절 등록 시도 횟수 상한(같은 clientAlgoId, 매 시도 전 조회)
FLATTEN_ATTEMPTS = 3                    # 비상 청산 한 번의 호출(주기)에서 쓰는 시도 수(f1~f3). 평생 한도가 아니다:
                                        # 다음 대조·보호 주기에 f1~f3을 다시 돈다(끝난 주문의 ID 재사용 — K15)
EXIT_ATTEMPTS = 3                       # 추세 청산 한 번의 호출에서 쓰는 시도 수(x1~x3, 위와 같은 규칙)
UNKNOWN_GRACE_MS = 2000                 # 도착 기한 뒤 여유(이 뒤에도 조회에 없으면 '접수 안 됨' 확정)
RECONCILE_MAX_INTERVAL_S = 30           # 대조 주기 상한
RECONCILE_FAILS_TO_HALT = 3             # 연속 대조 실패(조회 불가) 이 횟수면 T0
CLAIM_MAX_AGE_MS = 5 * 60 * 1000        # 승인([확인]) 뒤 이 시간 안에 B가 가져가지 못하면 낡은 승인(REJECTED)
IOC_CAP_BPS_MAX = 30                    # IOC 상한 지정가 폭 상한(0.30%). 기본 10bp(ARCHITECTURE §3.4 제안값 0.1%)
MAX_PRICE_DEVIATION = 0.01              # 주문가 ↔ 마크 가격 괴리 상한 ±1% (PV-16 #3)
ABS_MAX_QTY_BTC = 0.2                   # 절대 수량 상한(코드 상수, D20 잔고 상한과 함께 재검토)
ABS_MAX_NOTIONAL_USDT = 10_000.0        # 절대 명목 상한(코드 상수)
MAX_RISK_FRACTION = 0.01                # 1회 위험 상한(R 자본의 1%, PLAN D8). 기본은 backtest.trend.RISK_R(0.5%)
MIN_STOP_DISTANCE_FRAC = 0.002          # 손절 거리 하한(진입가 대비 0.2%) — 비정상 ATR(위조·데이터 오류) 방어
MAX_STOP_DISTANCE_FRAC = 0.25           # 손절 거리 상한(25%) — 3배 격리 청산가(약 −33%)보다 가까워야 한다
# 누적 한도(B가 B 전용 원장 + 거래소 사실로 계산, A가 쓴 값에 기대지 않는다 — ARCHITECTURE §2.3, SEC-04)
MAX_ENTRIES_PER_UTC_DAY = 3             # UTC 하루 진입 전송 상한(코드 상수). 넘으면 다음 UTC 00:00까지 신규 차단
T1_STOPS = 3                            # T1: 24시간 안 손절(stop·stop_immediate) 이 횟수 → 다음 UTC 00:00까지 신규 차단
T1_WINDOW_MS = 24 * 60 * 60 * 1000
T2_LOSS_R = 3.0                         # T2: UTC 하루 실현 손실 −3R 또는 −3%(R 자본) 중 먼저 → 다음 UTC 00:00까지
T2_LOSS_FRAC = 0.03
UTC_DAY_MS = 24 * 60 * 60 * 1000
PRICE_TICK = 0.1                        # BTCUSDT 가격 단위(거래소 exchangeInfo로 시작 때 대조, 다르면 T0)
QTY_STEP = 0.001                        # BTCUSDT 수량 단위(같음)

CLIENT_ID_PREFIX = "sig-"
CLIENT_ID_MAX_LEN = 36                  # 바이낸스 ^[.A-Z:/a-z0-9_-]{1,36}$
BINANCE_CLIENT_ID_RE = re.compile(r"[.A-Z:/a-z0-9_-]{1,36}")


class ExchangeEnv(str, Enum):
    """모의 환경 종류. 호스트는 코드 상수표(ENV_HOSTS)로만 정한다(설정에서 호스트를 받지 않는다 — 실서버 오지정 차단).

    K3: 바이낸스 선물 테스트넷(testnet.binancefuture.com)과 데모 트레이딩(demo-fapi.binance.com)의 관계·지속 여부.
    ccxt master는 선물 sandbox를 '더 이상 지원하지 않음, demo trading 사용'으로 표시한다(binance.py sign()) → 기본 DEMO.
    """

    DEMO = "demo"          # https://demo-fapi.binance.com  (기본)
    TESTNET = "testnet"    # https://testnet.binancefuture.com (구 테스트넷, K3 확인 후에만)


ENV_HOSTS: dict[ExchangeEnv, str] = {
    ExchangeEnv.DEMO: "demo-fapi.binance.com",
    ExchangeEnv.TESTNET: "testnet.binancefuture.com",
}
LIVE_HOSTS = frozenset({"fapi.binance.com", "api.binance.com", "dapi.binance.com", "papi.binance.com"})


def env_base_url(env: ExchangeEnv | str) -> str:
    return f"https://{ENV_HOSTS[ExchangeEnv(env)]}"


# ---------------------------------------------------------------------------
# 주문 의도(order intent) 상태 머신 (DESIGN §3)
# ---------------------------------------------------------------------------


class IntentState(str, Enum):
    QUEUED = "QUEUED"                        # A가 APPROVED 신호와 같은 트랜잭션으로 넣음. 아직 B가 가져가지 않음
    SUBMITTING = "SUBMITTING"                # B가 원자적으로 가져감. 사전 점검 → (entry_sent_ms 기록) → 진입 전송·결과 확정 중
    ENTRY_FILLED = "ENTRY_FILLED"            # 진입 체결 수량 > 0 확정(부분 체결 포함). 손절 아직 없음(노출 시작)
    STOP_PLACED = "STOP_PLACED"              # 손절 등록 요청이 거래소에 접수됨(응답 또는 조회로 확인)
    STOP_VERIFIED = "STOP_VERIFIED"          # 손절 존재·트리거·방향·closePosition·workingType을 조회로 대조 완료(보유 중)
    EXITING = "EXITING"                      # 추세 청산(reduceOnly 시장가) 전송·확정 중
    CLOSED = "CLOSED"                        # 포지션 0 확인 + 남은 손절 취소 완료(손절 발동 또는 추세 청산)
    REJECTED = "REJECTED"                    # 진입 주문을 보내기 전에 거부(사전 점검·방화벽·낡은 승인·정지) — 노출 없음
    NOT_FILLED = "NOT_FILLED"                # 진입을 보냈으나 체결 0 확정(IOC 만료·거래소 거부·도착 기한 경과) — 노출 없음
    FAILED_FLATTENED = "FAILED_FLATTENED"    # 노출 뒤 실패(손절 등록·확인 실패 등) → reduceOnly 시장가로 청산 확인 + T0
    HALTED = "HALTED"                        # 결과를 확정할 수 없음(청산 실패·조회 불가 지속) — 사람만 푼다 + T0


I = IntentState
INTENT_TRANSITIONS: dict[IntentState, frozenset[IntentState]] = {
    # QUEUED → REJECTED: 낡은 승인·정지 중·신호 상태 불일치·A의 /pause(cancel_queued)
    I.QUEUED: frozenset({I.SUBMITTING, I.REJECTED}),
    # SUBMITTING: 진입 전 거부(REJECTED) / 진입 결과(체결>0 ENTRY_FILLED, 0 NOT_FILLED) / 확정 불가(HALTED)
    # 손절 선배치 경로(K1=가능)에서는 진입 전 손절이 이미 있으므로 체결 즉시 STOP_PLACED로 갈 수 있다.
    I.SUBMITTING: frozenset({I.REJECTED, I.ENTRY_FILLED, I.STOP_PLACED, I.NOT_FILLED, I.FAILED_FLATTENED, I.HALTED}),
    I.ENTRY_FILLED: frozenset({I.STOP_PLACED, I.STOP_VERIFIED, I.FAILED_FLATTENED, I.CLOSED, I.HALTED}),
    I.STOP_PLACED: frozenset({I.STOP_VERIFIED, I.FAILED_FLATTENED, I.CLOSED, I.HALTED}),
    # 보유 중: 추세 청산(EXITING), 손절 발동(CLOSED), 대조에서 손절 누락(FAILED_FLATTENED), 확정 불가(HALTED)
    I.STOP_VERIFIED: frozenset({I.EXITING, I.CLOSED, I.FAILED_FLATTENED, I.HALTED}),
    I.EXITING: frozenset({I.CLOSED, I.FAILED_FLATTENED, I.HALTED}),
    # HALTED는 사람이 서버에서 원인을 해소한 뒤(제어 파일) 대조기가 거래소 사실로 종료 상태를 기록한다.
    I.HALTED: frozenset({I.CLOSED, I.FAILED_FLATTENED}),
    I.CLOSED: frozenset(),
    I.REJECTED: frozenset(),
    I.NOT_FILLED: frozenset(),
    I.FAILED_FLATTENED: frozenset(),
}
del I

INTENT_TERMINAL = frozenset({IntentState.CLOSED, IntentState.REJECTED, IntentState.NOT_FILLED,
                             IntentState.FAILED_FLATTENED})
# 거래소 노출이 있을 수 있는 상태(동시에 1개만 — queue의 부분 고유 인덱스). QUEUED는 노출 없음.
INTENT_LIVE = frozenset({IntentState.SUBMITTING, IntentState.ENTRY_FILLED, IntentState.STOP_PLACED,
                         IntentState.STOP_VERIFIED, IntentState.EXITING, IntentState.HALTED})
# 포지션이 있다고 확정된 상태(대조 대상)
INTENT_HOLDING = frozenset({IntentState.ENTRY_FILLED, IntentState.STOP_PLACED, IntentState.STOP_VERIFIED,
                            IntentState.EXITING})


def can_intent_transition(src: IntentState | str, dst: IntentState | str) -> bool:
    return IntentState(dst) in INTENT_TRANSITIONS[IntentState(src)]


class IntentExitReason(str, Enum):
    STOP = "stop"                          # 거래소 손절 발동(bot.types.ExitReason.STOP과 같은 값)
    TREND = "trend"                        # 추세 청산(bot.types.ExitReason.TREND와 같은 값)
    FLATTEN = "flatten"                    # 비상 청산(실패 처리)
    STOP_IMMEDIATE = "stop_immediate"      # 손절 등록 시 '즉시 발동'(-2021) → 곧바로 시장가 청산(시장이 이미 손절가 아래)
    EXTERNAL = "external"                  # 거래소에서 포지션이 우리 주문 없이 사라짐(청산·사람) — T0


# 신호(bot.types.SignalState) 쪽 대응 (B가 같은 트랜잭션에서 전이, actor=ORDER_ACTOR)
ORDER_ACTOR = "ORDER_GATEWAY"


# ---------------------------------------------------------------------------
# 멱등 clientOrderId: sig-<신호ID 16자>-<용도>
# ---------------------------------------------------------------------------


class IdPurpose(str, Enum):
    ENTRY = "e1"          # 진입(신호당 한 번뿐, 재전송 금지)
    STOP = "sl"           # 보호 손절(clientAlgoId). 재시도는 같은 ID(조회 먼저)
    EXIT1 = "x1"          # 추세 청산 reduceOnly 시장가 1~3차
    EXIT2 = "x2"
    EXIT3 = "x3"
    FLAT1 = "f1"          # 비상 청산 reduceOnly 시장가 1~3차
    FLAT2 = "f2"
    FLAT3 = "f3"


EXIT_PURPOSES = (IdPurpose.EXIT1, IdPurpose.EXIT2, IdPurpose.EXIT3)
FLAT_PURPOSES = (IdPurpose.FLAT1, IdPurpose.FLAT2, IdPurpose.FLAT3)
_CLIENT_ID_RE = re.compile(r"sig-([A-Z2-7]{16})-(e1|sl|x[1-3]|f[1-3])")


def make_client_id(signal_id: str, purpose: IdPurpose | str) -> str:
    """'sig-<ID>-<용도>' (23자 ≤ 36). 신호 ID 형식이 아니면 ValueError."""
    if not isinstance(signal_id, str) or not SIGNAL_ID_RE.fullmatch(signal_id):
        raise ValueError("신호 ID 형식이 아님")
    cid = f"{CLIENT_ID_PREFIX}{signal_id}-{IdPurpose(purpose).value}"
    if len(cid) > CLIENT_ID_MAX_LEN or not BINANCE_CLIENT_ID_RE.fullmatch(cid):  # 구조상 23자 — 방어적 검사
        raise ValueError("clientOrderId 형식 위반")
    return cid


@dataclass(frozen=True)
class ParsedClientId:
    signal_id: str
    purpose: IdPurpose


def parse_client_id(cid: object) -> ParsedClientId | None:
    """우리 주문 ID면 (신호ID, 용도), 아니면 None(= '모르는 주문', 대조기가 T0)."""
    if not isinstance(cid, str):
        return None
    m = _CLIENT_ID_RE.fullmatch(cid)
    if m is None:
        return None
    return ParsedClientId(m.group(1), IdPurpose(m.group(2)))


# ---------------------------------------------------------------------------
# 거래소 자료형
# ---------------------------------------------------------------------------


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_MARKET = "STOP_MARKET"              # 조건부(algo) — 손절 전용


class TimeInForce(str, Enum):
    IOC = "IOC"
    GTC = "GTC"
    GTX = "GTX"                              # post-only (이 단계에서 쓰지 않음)
    GTD = "GTD"                              # (이 단계에서 쓰지 않음)


class WorkingType(str, Enum):
    MARK_PRICE = "MARK_PRICE"
    CONTRACT_PRICE = "CONTRACT_PRICE"


class OrderStatus(str, Enum):
    """일반 주문 상태(바이낸스 fapi 값)."""

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"                      # IOC 미체결분 만료
    EXPIRED_IN_MATCH = "EXPIRED_IN_MATCH"    # 자기 체결 방지로 만료
    REJECTED = "REJECTED"


ORDER_FINAL_STATUSES = frozenset({OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.EXPIRED,
                                  OrderStatus.EXPIRED_IN_MATCH, OrderStatus.REJECTED})


class ConditionalStatus(str, Enum):
    """조건부(algo) 주문 상태. 값 목록은 ccxt parse_order_status 기준 — K5(실제 값·전이) PoC 확인 필요."""

    NEW = "NEW"                  # 대기 중(= 손절이 걸려 있음)
    TRIGGERING = "TRIGGERING"    # 발동 중
    TRIGGERED = "TRIGGERED"      # 발동됨(시장가 주문 생성)
    FINISHED = "FINISHED"        # 발동 뒤 완료
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


CONDITIONAL_ACTIVE_STATUSES = frozenset({ConditionalStatus.NEW})
CONDITIONAL_FIRED_STATUSES = frozenset({ConditionalStatus.TRIGGERING, ConditionalStatus.TRIGGERED,
                                        ConditionalStatus.FINISHED})


@dataclass(frozen=True)
class SymbolRules:
    """exchangeInfo의 BTCUSDT 필터. 코드 상수(PRICE_TICK·QTY_STEP)와 다르면 T0(규칙이 바뀐 것)."""

    symbol: str
    tick_size: float
    step_size: float
    min_qty: float
    min_notional: float                      # K11: 최소 주문 명목(현재 문서상 5~20 USDT, 실측 필요)
    status: str = "TRADING"


@dataclass(frozen=True)
class AccountConfig:
    """계정·심볼 모드(조회값). 봇은 이것을 **바꾸지 않고 검사만** 한다(ARCHITECTURE §5.1.1, 08 §2.5-4).

    - dual_side_position: GET /fapi/v1/positionSide/dual → dualSidePosition (False = One-way)
    - multi_assets_margin: GET /fapi/v1/multiAssetsMargin → multiAssetsMargin (False = Single-Asset)
    - leverage·margin_type: 심볼 설정(GET /fapi/v1/symbolConfig 또는 positionRisk) — K9: 어느 엔드포인트가 데모에서 되는지
    - can_withdraw: 키 권한(출금). 선물 데모에서 조회 불가하면 None(모름) — K10. LIVE 전에는 반드시 False 확인.
    """

    dual_side_position: bool
    multi_assets_margin: bool
    leverage: int
    margin_type: str                         # 'isolated' | 'cross' (소문자 정규화)
    can_trade: bool = True
    can_withdraw: bool | None = None


@dataclass(frozen=True)
class Balance:
    asset: str
    wallet_balance: float
    available_balance: float


@dataclass(frozen=True)
class PositionInfo:
    """One-way 모드의 BTCUSDT 순포지션. qty는 부호 있는 수량(롱 +). 포지션 없음이면 qty == 0."""

    symbol: str
    qty: float
    entry_price: float
    leverage: int
    margin_type: str
    update_ms: int = 0


@dataclass(frozen=True)
class OrderRequest:
    """일반 주문(진입 IOC 지정가 / 청산 reduceOnly 시장가). 조건부 주문은 ConditionalRequest."""

    symbol: str
    side: Side
    type: OrderType
    qty: float
    client_id: str
    price: float | None = None               # LIMIT만
    time_in_force: TimeInForce | None = None  # LIMIT만(이 단계: IOC)
    reduce_only: bool = False


@dataclass(frozen=True)
class ConditionalRequest:
    """보호 손절(algo STOP_MARKET). closePosition=True면 quantity·reduceOnly를 보내지 않는다(바이낸스 규칙)."""

    symbol: str
    side: Side
    type: OrderType
    trigger_price: float
    client_algo_id: str
    close_position: bool = True
    working_type: WorkingType = WorkingType.MARK_PRICE
    price_protect: bool = False              # 08 §2.5: 급변 때 손절이 안 나가는 쪽이 더 위험 → false (K7 확인)


@dataclass(frozen=True)
class OrderInfo:
    """일반 주문 조회·응답(newOrderRespType=RESULT)."""

    client_id: str
    exchange_order_id: str
    symbol: str
    side: Side
    type: OrderType
    status: OrderStatus
    orig_qty: float
    executed_qty: float
    avg_price: float                         # 체결 없으면 0.0
    price: float = 0.0
    reduce_only: bool = False
    close_position: bool = False
    time_in_force: str | None = None
    update_ms: int = 0


@dataclass(frozen=True)
class ConditionalInfo:
    client_algo_id: str
    algo_id: str
    symbol: str
    side: Side
    type: OrderType
    status: ConditionalStatus
    trigger_price: float
    close_position: bool
    working_type: WorkingType
    price_protect: bool
    reduce_only: bool = False
    qty: float = 0.0
    update_ms: int = 0


# ---------------------------------------------------------------------------
# 오류 분류 (단일 기준표 — binance_client·fake_exchange가 같은 표를 쓴다)
# ---------------------------------------------------------------------------


class ErrorKind(str, Enum):
    CLOCK_SKEW = "CLOCK_SKEW"                        # -1021
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"      # -2019
    ALGO_ENDPOINT_REQUIRED = "ALGO_ENDPOINT_REQUIRED"  # -4120 (조건부 주문을 옛 창구로 보냄)
    MIN_NOTIONAL = "MIN_NOTIONAL"                    # -4164
    WOULD_TRIGGER = "WOULD_TRIGGER"                  # -2021 (손절이 즉시 발동할 가격)
    REDUCE_ONLY_REJECTED = "REDUCE_ONLY_REJECTED"    # -2022 (줄일 포지션 없음 등)
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"              # -2013
    CANCEL_REJECTED = "CANCEL_REJECTED"              # -2011
    DUPLICATE_CLIENT_ID = "DUPLICATE_CLIENT_ID"      # -4116 (같은 ID의 미체결 주문이 이미 있음)
    ACCOUNT_MODE = "ACCOUNT_MODE"                    # -4061 (positionSide 불일치 = Hedge 모드)
    TRADING_RESTRICTED = "TRADING_RESTRICTED"        # -4400 (정량 규칙 위반: reduceOnly만 허용)
    RATE_LIMITED = "RATE_LIMITED"                    # 429, -1003
    IP_BANNED = "IP_BANNED"                          # 418
    REGION_BLOCKED = "REGION_BLOCKED"                # 451, 403(WAF)
    AUTH = "AUTH"                                    # 401, -2014, -2015, -1022
    BAD_REQUEST = "BAD_REQUEST"                      # 그 밖의 확정 거부(매개변수·필터 -1100대·-4000대 등)
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"              # -1007, 5xx, 타임아웃·연결 끊김(보낸 뒤) — 체결됐을 수도 있다
    UNKNOWN = "UNKNOWN"                              # 표에 없는 오류(결과 모름으로 취급)


@dataclass(frozen=True)
class ErrorPolicy:
    outcome_unknown: bool    # True: 주문 요청이 거래소에서 실행됐을 수 있음 → clientOrderId로 조회해 판단(I15)
    halt: bool               # True: 킬 스위치 T0(신규 진입 차단, 기존 손절 유지)
    retry_read: bool         # True: 조회(GET) 요청이면 백오프 뒤 재시도 가능(주문 요청은 절대 자동 재전송 안 함)


ERROR_POLICY: dict[ErrorKind, ErrorPolicy] = {
    ErrorKind.CLOCK_SKEW: ErrorPolicy(False, True, True),
    ErrorKind.INSUFFICIENT_MARGIN: ErrorPolicy(False, True, False),
    ErrorKind.ALGO_ENDPOINT_REQUIRED: ErrorPolicy(False, True, False),
    ErrorKind.MIN_NOTIONAL: ErrorPolicy(False, False, False),
    ErrorKind.WOULD_TRIGGER: ErrorPolicy(False, False, False),
    ErrorKind.REDUCE_ONLY_REJECTED: ErrorPolicy(False, False, False),
    ErrorKind.ORDER_NOT_FOUND: ErrorPolicy(False, False, False),
    ErrorKind.CANCEL_REJECTED: ErrorPolicy(False, False, False),
    ErrorKind.DUPLICATE_CLIENT_ID: ErrorPolicy(True, False, False),
    ErrorKind.ACCOUNT_MODE: ErrorPolicy(False, True, False),
    ErrorKind.TRADING_RESTRICTED: ErrorPolicy(False, True, False),
    ErrorKind.RATE_LIMITED: ErrorPolicy(False, False, True),
    ErrorKind.IP_BANNED: ErrorPolicy(False, True, False),
    ErrorKind.REGION_BLOCKED: ErrorPolicy(False, True, False),
    ErrorKind.AUTH: ErrorPolicy(False, True, False),
    ErrorKind.BAD_REQUEST: ErrorPolicy(False, True, False),
    ErrorKind.OUTCOME_UNKNOWN: ErrorPolicy(True, False, True),
    ErrorKind.UNKNOWN: ErrorPolicy(True, True, False),
}

BINANCE_CODE_KIND: dict[int, ErrorKind] = {
    -1021: ErrorKind.CLOCK_SKEW,
    -2019: ErrorKind.INSUFFICIENT_MARGIN,
    -4120: ErrorKind.ALGO_ENDPOINT_REQUIRED,
    -4164: ErrorKind.MIN_NOTIONAL,
    -2021: ErrorKind.WOULD_TRIGGER,
    -2022: ErrorKind.REDUCE_ONLY_REJECTED,
    -2013: ErrorKind.ORDER_NOT_FOUND,
    -2011: ErrorKind.CANCEL_REJECTED,
    -4116: ErrorKind.DUPLICATE_CLIENT_ID,
    -4061: ErrorKind.ACCOUNT_MODE,
    -4400: ErrorKind.TRADING_RESTRICTED,
    -1003: ErrorKind.RATE_LIMITED,
    -2014: ErrorKind.AUTH,
    -2015: ErrorKind.AUTH,
    -1022: ErrorKind.AUTH,
    -1007: ErrorKind.OUTCOME_UNKNOWN,
    -1001: ErrorKind.OUTCOME_UNKNOWN,       # DISCONNECTED(내부 오류) — 결과 모름
}


def classify_error(http_status: int | None, code: int | None) -> ErrorKind:
    """(HTTP 상태, 바이낸스 code) → ErrorKind. http_status None = 응답 없음(타임아웃·연결 끊김) → OUTCOME_UNKNOWN.

    우선순위: 418·429·451·403·401(상태 코드가 뜻을 정함) → 5xx(결과 모름) → code 표 → 그 밖 4xx(BAD_REQUEST) → UNKNOWN.
    """
    if http_status is None:
        return ErrorKind.OUTCOME_UNKNOWN
    s = int(http_status)
    if s == 418:
        return ErrorKind.IP_BANNED
    if s == 429:
        return ErrorKind.RATE_LIMITED
    if s in (451, 403):
        return ErrorKind.REGION_BLOCKED
    if s == 401:
        return ErrorKind.AUTH
    if 500 <= s <= 599:
        return ErrorKind.OUTCOME_UNKNOWN
    if code is not None and int(code) in BINANCE_CODE_KIND:
        return BINANCE_CODE_KIND[int(code)]
    if 400 <= s <= 499:
        return ErrorKind.BAD_REQUEST
    return ErrorKind.UNKNOWN


class ExchangeError(RuntimeError):
    """거래소 호출 실패. 메시지에 서명·키·전체 URL 쿼리를 넣지 않는다(클라이언트 책임)."""

    def __init__(self, kind: ErrorKind, *, http_status: int | None = None, code: int | None = None,
                 msg: str = "", retry_after_s: float | None = None) -> None:
        self.kind = ErrorKind(kind)
        self.http_status = http_status
        self.code = code
        self.msg = str(msg)[:200]
        self.retry_after_s = retry_after_s
        super().__init__(f"{self.kind.value} http={http_status} code={code} {self.msg}")

    @property
    def policy(self) -> ErrorPolicy:
        return ERROR_POLICY[self.kind]

    @property
    def outcome_unknown(self) -> bool:
        return self.policy.outcome_unknown

    @property
    def halts(self) -> bool:
        return self.policy.halt


# ---------------------------------------------------------------------------
# 킬 스위치 T0 사유 (DESIGN §7)
# ---------------------------------------------------------------------------


class HaltReason(str, Enum):
    STOP_NOT_VERIFIED = "stop_not_verified"          # 손절 등록·확인 실패(I2)
    UNPROTECTED_TIMEOUT = "unprotected_timeout"      # 체결 뒤 STOP_DEADLINE_MS 안에 확인 못 함
    STOP_MISSING = "stop_missing"                    # 보유 중 대조에서 손절 없음·불일치
    ALGO_ENDPOINT = "algo_endpoint"                  # -4120
    ACCOUNT_MODE = "account_mode"                    # One-way·Single-Asset 아님
    LEVERAGE_MARGIN = "leverage_margin"              # 레버리지 > 3 또는 격리 아님
    SYMBOL_RULES = "symbol_rules"                    # tick·step이 코드 상수와 다름
    CLOCK_SKEW = "clock_skew"                        # |오차| > 1000ms 또는 -1021
    EXCHANGE_BLOCK = "exchange_block"                # 418·451·403
    AUTH = "auth"                                    # 키 거부
    TRADING_RESTRICTED = "trading_restricted"        # -4400
    UNKNOWN_ORDER = "unknown_order"                  # sig- 가 아니거나 활성 의도와 맞지 않는 주문
    UNKNOWN_POSITION = "unknown_position"            # DB에 없는 포지션
    POSITION_MISMATCH = "position_mismatch"          # 수량·방향 불일치(롱 아님 포함)
    BALANCE_MISMATCH = "balance_mismatch"            # 잔고 부족·불일치
    FLATTEN_FAILED = "flatten_failed"                # 비상 청산 실패(HALTED)
    OUTCOME_UNRESOLVED = "outcome_unresolved"        # 결과 모름을 기한 안에 확정 못 함
    RECONCILE_UNAVAILABLE = "reconcile_unavailable"  # 연속 대조 실패
    RESTART_UNPROTECTED = "restart_unprotected"      # 재시작 때 손절 확인 안 된 포지션 발견
    POSITION_VANISHED = "position_vanished"          # 우리 청산 없이 포지션이 사라짐(손절 발동 기록도 없음)
    FIREWALL = "firewall"                            # 방화벽 거부(정상 운영에서는 생기지 않아야 함)
    ORDER_ERROR = "order_error"                      # 그 밖의 halt=True 오류(ERROR_POLICY)
    OPERATOR = "operator"                            # 제어 파일의 수동 정지


# ---------------------------------------------------------------------------
# 설정 (B 전용 [orders] 절) — 엄격 검증, 조이는 방향만
# ---------------------------------------------------------------------------


class ConditionalApi(str, Enum):
    """K2: 조건부(손절) 주문 창구. 2025-12-09 이후 algo 창구(POST /fapi/v1/algoOrder, algoType=CONDITIONAL)가 기본.
    옛 창구(POST /fapi/v1/order type=STOP_MARKET)는 -4120으로 거부되는 것으로 알려짐 — 데모에서 확인 후에만 LEGACY."""

    ALGO = "algo"
    LEGACY = "legacy"


class StopPlacement(str, Enum):
    """K1: 포지션이 없을 때 closePosition 손절을 미리 걸 수 있는가.
    POST_FILL(기본, 확인 전): 진입 체결 → 손절 등록 → 확인. PRE_ENTRY(K1=가능 확인 뒤): 손절 선배치·확인 → 진입."""

    POST_FILL = "post_fill"
    PRE_ENTRY = "pre_entry"


class OrdersConfigError(ValueError):
    pass


@dataclass(frozen=True)
class OrdersConfig:
    """프로세스 B 설정. TOML [orders] 절을 ``from_mapping``으로 읽는다(모르는 키·느슨한 값 → OrdersConfigError).

    비밀(키 ID·개인키)은 **파일 경로**로만 받는다(값 금지). 경로는 절대 경로. 파일 읽기는 bot.config.read_secret.
    """

    env: ExchangeEnv = ExchangeEnv.DEMO
    api_key_file: str = "/run/secrets/binance_api_key"
    private_key_file: str = "/run/secrets/binance_ed25519_private_key"
    control_file: str = "/control/orders_control.toml"
    ledger_file: str = "/state/orders_ledger.json"   # B 전용 원장(B만 마운트하는 볼륨, A는 못 쓴다 — SEC-02·04)
    r_capital_usdt: float = 1000.0             # R 자본(설정 상수, 서버에서 사람이 갱신)
    risk_fraction: float = 0.005               # ≤ backtest.trend.RISK_R (백테스트와 같은 1회 위험 이하)
    max_notional_usdt: float = ABS_MAX_NOTIONAL_USDT
    expected_leverage: int = MAX_LEVERAGE      # 거래소 설정 레버리지가 이 값이어야 한다(1..3)
    ioc_cap_bps: int = 10
    conditional_api: ConditionalApi = ConditionalApi.ALGO
    stop_placement: StopPlacement = StopPlacement.POST_FILL
    reconcile_interval_s: int = RECONCILE_MAX_INTERVAL_S
    stop_deadline_ms: int = STOP_DEADLINE_MS
    claim_max_age_ms: int = CLAIM_MAX_AGE_MS
    max_clock_skew_ms: int = MAX_CLOCK_SKEW_MS
    recv_window_ms: int = RECV_WINDOW_MS
    loop_interval_s: float = 2.0               # worker 폴링 주기(큐 확인)
    http_timeout_s: float = 10.0

    def __post_init__(self) -> None:
        self.validate()

    # --- 검증 ---
    def validate(self) -> None:
        from backtest.trend import RISK_R  # 지역 import: 상수 하나만

        def bad(msg: str) -> None:
            raise OrdersConfigError(msg)

        if not isinstance(self.env, ExchangeEnv):
            bad("orders.env는 'demo'|'testnet'")
        for name in ("api_key_file", "private_key_file", "control_file", "ledger_file"):
            v = getattr(self, name)
            if not isinstance(v, str) or not Path(v).is_absolute():
                bad(f"orders.{name}는 절대 경로 문자열")
        for name in ("r_capital_usdt", "risk_fraction", "max_notional_usdt", "loop_interval_s", "http_timeout_s"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or float(v) <= 0:
                bad(f"orders.{name}는 양의 유한수")
        if float(self.risk_fraction) > min(RISK_R, MAX_RISK_FRACTION):
            bad(f"orders.risk_fraction은 {RISK_R} 이하(조이는 방향만)")
        if float(self.max_notional_usdt) > ABS_MAX_NOTIONAL_USDT:
            bad(f"orders.max_notional_usdt는 {ABS_MAX_NOTIONAL_USDT} 이하")
        ints = {"expected_leverage": (1, MAX_LEVERAGE), "ioc_cap_bps": (1, IOC_CAP_BPS_MAX),
                "reconcile_interval_s": (5, RECONCILE_MAX_INTERVAL_S), "stop_deadline_ms": (1000, STOP_DEADLINE_MS),
                "claim_max_age_ms": (30_000, CLAIM_MAX_AGE_MS), "max_clock_skew_ms": (100, MAX_CLOCK_SKEW_MS),
                "recv_window_ms": (RECV_WINDOW_MS, RECV_WINDOW_MS)}
        for name, (lo, hi) in ints.items():
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                bad(f"orders.{name}는 정수 {lo}..{hi}")
        if not isinstance(self.conditional_api, ConditionalApi):
            bad("orders.conditional_api는 'algo'|'legacy'")
        if not isinstance(self.stop_placement, StopPlacement):
            bad("orders.stop_placement는 'post_fill'|'pre_entry'")
        if float(self.loop_interval_s) > 10 or float(self.http_timeout_s) > 30:
            bad("orders.loop_interval_s ≤ 10, http_timeout_s ≤ 30")

    @property
    def base_url(self) -> str:
        return env_base_url(self.env)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "OrdersConfig":
        if not isinstance(raw, Mapping):
            raise OrdersConfigError("[orders]는 표(table)여야 한다")
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            # host·base_url·api_key(값) 같은 키는 일부러 없다: 호스트는 코드 상수, 비밀은 파일 경로만.
            raise OrdersConfigError(f"[orders] 모르는 키: {sorted(unknown)}")
        kw: dict[str, Any] = dict(raw)
        try:
            if "env" in kw:
                kw["env"] = ExchangeEnv(kw["env"])
            if "conditional_api" in kw:
                kw["conditional_api"] = ConditionalApi(kw["conditional_api"])
            if "stop_placement" in kw:
                kw["stop_placement"] = StopPlacement(kw["stop_placement"])
        except ValueError as exc:
            raise OrdersConfigError(str(exc)) from None
        return cls(**kw)


# ---------------------------------------------------------------------------
# 숫자 도우미 (tick·step 맞춤 — Decimal로 이진 부동소수 오차 제거)
# ---------------------------------------------------------------------------


def _dec(x: float) -> Decimal:
    return Decimal(repr(float(x)))


def floor_to_step(x: float, step: float) -> float:
    """x 이하인 step의 배수(수량 내림, 가격 내림)."""
    s = _dec(step)
    return float((_dec(x) / s).to_integral_value(rounding=ROUND_FLOOR) * s)


def ceil_to_step(x: float, step: float) -> float:
    """x 이상인 step의 배수(매수 상한가 올림)."""
    s = _dec(step)
    return float((_dec(x) / s).to_integral_value(rounding=ROUND_CEILING) * s)


def is_multiple(x: float, step: float) -> bool:
    q = _dec(x) / _dec(step)
    return q == q.to_integral_value()


def format_decimal(x: float) -> str:
    """거래소로 보낼 숫자 문자열(지수 표기 없음, 불필요한 0 제거). 예: 0.001 → '0.001', 65000.0 → '65000'."""
    if not math.isfinite(float(x)):
        raise ValueError("유한수가 아님")
    d = _dec(x).normalize()
    s = format(d, "f")
    return s


# ---------------------------------------------------------------------------
# 거래소 인터페이스 (binance_client.BinanceFuturesClient / fake_exchange.FakeExchange)
# ---------------------------------------------------------------------------


@runtime_checkable
class ExchangeClient(Protocol):
    """게이트웨이·대조기가 쓰는 거래소 동작. 모든 메서드는 실패 시 ``ExchangeError``만 던진다.

    규칙(구현 공통)
    - 조회(GET)는 ErrorPolicy.retry_read인 오류에 한해 구현 안에서 짧게 재시도할 수 있다(최대 2회, 429는 Retry-After 준수).
    - 주문(POST order/algoOrder)은 **절대 자동 재전송하지 않는다**(I15). 결과를 모르면 OUTCOME_UNKNOWN을 던지고,
      호출자가 clientOrderId로 조회해 판단한다.
    - 취소(DELETE)는 멱등이라 재시도 가능하지만 ORDER_NOT_FOUND는 '이미 없음'으로 성공 취급해도 된다(호출자 선택).
    - symbol 인자는 받지 않는다: 이 인터페이스는 SYMBOL(BTCUSDT) 전용이다.
    """

    env: ExchangeEnv

    def server_time_ms(self) -> int: ...

    def symbol_rules(self) -> SymbolRules: ...

    def account_config(self) -> AccountConfig: ...

    def balance(self) -> Balance: ...

    def mark_price(self) -> float: ...

    def position(self) -> PositionInfo: ...

    def open_orders(self) -> list[OrderInfo]: ...

    def open_conditional_orders(self) -> list[ConditionalInfo]: ...

    def place_order(self, req: OrderRequest) -> OrderInfo:
        """POST /fapi/v1/order (newOrderRespType=RESULT). 반환은 접수 직후 상태(IOC면 최종 상태)."""
        ...

    def get_order(self, client_id: str) -> OrderInfo | None:
        """GET /fapi/v1/order?origClientOrderId=… 없으면 None(-2013)."""
        ...

    def cancel_order(self, client_id: str) -> OrderInfo | None: ...

    def place_conditional(self, req: ConditionalRequest) -> ConditionalInfo:
        """ALGO: POST /fapi/v1/algoOrder (algoType=CONDITIONAL, triggerPrice, clientAlgoId).
        LEGACY: POST /fapi/v1/order (type=STOP_MARKET, stopPrice, newClientOrderId). 경로는 설정 ConditionalApi."""
        ...

    def get_conditional(self, client_algo_id: str) -> ConditionalInfo | None:
        """ALGO: GET /fapi/v1/algoOrder?clientAlgoId=… (K5: 종료된 algo 주문도 조회되는 기간)."""
        ...

    def cancel_conditional(self, client_algo_id: str) -> ConditionalInfo | None: ...


@dataclass(frozen=True)
class ExchangeSnapshot:
    """대조·사전 점검용 한 번의 조회 묶음(같은 루프 안의 값)."""

    server_time_ms: int
    local_time_ms: int
    position: PositionInfo
    open_orders: tuple[OrderInfo, ...]
    open_conditionals: tuple[ConditionalInfo, ...]
    mark_price: float | None = None
    balance: Balance | None = None
    account: AccountConfig | None = None
    rules: SymbolRules | None = None

    @property
    def clock_offset_ms(self) -> int:
        return int(self.server_time_ms) - int(self.local_time_ms)


@dataclass
class GatewayResult:
    """gateway.process_intent 한 번의 결과(테스트·로그용). 알림은 queue.outbox로 이미 기록돼 있다."""

    intent_id: int
    final_state: IntentState
    reason: str | None = None
    halt_ids: list[int] = field(default_factory=list)
    unprotected_ms: int | None = None
