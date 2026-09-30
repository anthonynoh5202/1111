"""공용 자료형·상태·시간 규칙·인터페이스(Protocol) — 설계 담당 소유 (bot/DESIGN.md §3, §5).

원칙
- 시각: 내부 계산은 int ns(UTC, backtest와 같은 단위), DB 저장은 int ms(UTC, 열 이름 *_ms), 표시는 KST 문자열.
- 신호 상태 머신의 허용 전이는 SIGNAL_TRANSITIONS 하나만이 기준이다(db.transition_signal이 이것으로 검사한다).
- 외부 연동(시세·텔레그램·Claude·시계)은 Protocol로만 의존한다. 실제 구현과 가짜 구현(테스트) 둘 다 이 모양을 따른다.
"""
from __future__ import annotations

import base64
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import pandas as pd

# ---------------------------------------------------------------------------
# 시간 단위와 변환 (§5 시간 규칙)
# ---------------------------------------------------------------------------
NS_PER_MS = 1_000_000
NS_PER_SEC = 1_000_000_000
NS_PER_MIN = 60 * NS_PER_SEC
NS_PER_DAY = 24 * 60 * NS_PER_MIN
MS_PER_SEC = 1_000
MS_PER_MIN = 60 * MS_PER_SEC
MS_PER_DAY = 24 * 60 * MS_PER_MIN
KST = timezone(timedelta(hours=9), name="KST")


def ns_to_ms(ns: int) -> int:
    """ns → ms (내림). DB 저장용."""
    return int(ns) // NS_PER_MS


def ms_to_ns(ms: int) -> int:
    return int(ms) * NS_PER_MS


def utc_iso_ms(ms: int | None) -> str:
    """ms → 'YYYY-MM-DDTHH:MM:SSZ' (UTC). None이면 ''."""
    if ms is None:
        return ""
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def kst_str(ms: int | None, fmt: str = "%Y-%m-%d %H:%M KST") -> str:
    """ms(UTC) → KST 표시 문자열. 표시 전용(저장·비교에 쓰지 않는다)."""
    if ms is None:
        return "-"
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).astimezone(KST).strftime(fmt)


def utc_day_start_ns(t_ns: int) -> int:
    """t_ns가 속한 UTC 날짜의 00:00 (ns)."""
    return int(t_ns) - int(t_ns) % NS_PER_DAY


def ceil_minute_ns(t_ns: int) -> int:
    """t_ns 이상인 첫 분 경계 (ns). 정확히 분 경계면 그대로."""
    t = int(t_ns)
    return -(-t // NS_PER_MIN) * NS_PER_MIN


# ---------------------------------------------------------------------------
# 모드
# ---------------------------------------------------------------------------


class Mode(str, Enum):
    """운영 모드. LIVE는 이 단계에 없다(설정 로더가 거부한다)."""

    REPLAY = "replay"   # 과거 데이터를 하루씩 흘려보내는 재생 (가짜 시계 + Replay 시세)
    PAPER = "paper"     # 실시간 공개 시세 + 모의 체결


# ---------------------------------------------------------------------------
# 신호 상태 머신 (DESIGN §4)
# ---------------------------------------------------------------------------


class SignalState(str, Enum):
    NEW = "NEW"                        # 엔진이 신호를 만들고 DB에 넣었다(카드 전송 전)
    CARD_SENT = "CARD_SENT"            # 텔레그램 카드 전송 성공, [승인]/[패스] 대기 (만료 = 판단 + 2시간)
    CONFIRM_PENDING = "CONFIRM_PENDING"  # [승인] 눌림, 60초 안에 [확인] 대기
    APPROVED = "APPROVED"              # [확인] 눌림. 확인 시각 이후 첫 1분봉 시가에 모의 체결 대기
    FILLED = "FILLED"                  # 모의 체결됨(paper_positions OPEN)
    CLOSED = "CLOSED"                  # 포지션 종료(보호 손절 또는 추세 청산)
    PASSED = "PASSED"                  # 사람이 [패스]
    EXPIRED = "EXPIRED"                # 승인 유효 2시간 초과
    SKIPPED = "SKIPPED"                # 시스템이 건너뜀(일시정지, 전송 실패로 만료 전 미전송, 체결 불가 등. 사유 기록)


TERMINAL_STATES = frozenset({SignalState.CLOSED, SignalState.PASSED, SignalState.EXPIRED, SignalState.SKIPPED})
# 하위 시스템이 "그 신호로 바쁜" 상태: 새 진입 신호를 만들지 않는다(보유 중 또는 승인 절차 중).
ACTIVE_STATES = frozenset({SignalState.NEW, SignalState.CARD_SENT, SignalState.CONFIRM_PENDING,
                           SignalState.APPROVED, SignalState.FILLED})
# 승인 창이 열려 있는 상태: 만료 검사 대상.
PENDING_APPROVAL_STATES = frozenset({SignalState.NEW, SignalState.CARD_SENT, SignalState.CONFIRM_PENDING})

S = SignalState
SIGNAL_TRANSITIONS: dict[SignalState, frozenset[SignalState]] = {
    S.NEW: frozenset({S.CARD_SENT, S.EXPIRED, S.SKIPPED}),
    # CARD_SENT → CARD_SENT 는 없다(재전송은 상태를 바꾸지 않는다).
    S.CARD_SENT: frozenset({S.CONFIRM_PENDING, S.PASSED, S.EXPIRED, S.SKIPPED}),
    # 확인 화면 [취소] 또는 60초 초과 → CARD_SENT로 되돌림(승인 창 2시간 안이면 다시 [승인] 가능).
    S.CONFIRM_PENDING: frozenset({S.APPROVED, S.CARD_SENT, S.PASSED, S.EXPIRED, S.SKIPPED}),
    # APPROVED에서 체결 전 /pause 또는 체결 불가(데이터 없음 등) → SKIPPED.
    S.APPROVED: frozenset({S.FILLED, S.SKIPPED}),
    S.FILLED: frozenset({S.CLOSED}),
    S.CLOSED: frozenset(),
    S.PASSED: frozenset(),
    S.EXPIRED: frozenset(),
    S.SKIPPED: frozenset(),
}
del S


def can_transition(src: SignalState | str, dst: SignalState | str) -> bool:
    return SignalState(dst) in SIGNAL_TRANSITIONS[SignalState(src)]


class PositionState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(str, Enum):
    STOP = "stop"      # 보호 손절 (backtest Exit.STOP 값과 같다)
    TREND = "trend"    # 추세 청산 (backtest.trend.EXIT_TREND 값과 같다)


class TradeKind(str, Enum):
    """paper_trades 원장 행 종류."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    FUNDING = "FUNDING"


class CallbackAction(str, Enum):
    """텔레그램 callback_data 동작 코드 ("v1:<코드>:<신호ID>")."""

    APPROVE = "A"   # [승인] → 확인 화면(CONFIRM_PENDING)
    CONFIRM = "C"   # [확인] → APPROVED
    CANCEL = "X"    # 확인 화면 [취소] → CARD_SENT
    PASS = "P"      # [패스] → PASSED
    DETAIL = "D"    # [상세] (상태 변화 없음)


class Actor(str, Enum):
    ENGINE = "ENGINE"
    PAPER = "PAPER"
    ANALYST = "ANALYST"
    TELEGRAM_USER = "TELEGRAM_USER"
    TELEGRAM_UNKNOWN = "TELEGRAM_UNKNOWN"   # 허용되지 않은 사용자·채팅
    OPERATOR = "OPERATOR"                   # 서버에서 직접(설정 파일·CLI)
    SYSTEM = "SYSTEM"


class AuditEvent(str, Enum):
    STATE_TRANSITION = "STATE_TRANSITION"
    SIGNAL_CREATED = "SIGNAL_CREATED"
    BUTTON = "BUTTON"                       # 허용된 클릭(결과 포함)
    BUTTON_REJECTED = "BUTTON_REJECTED"     # 권한·형식·만료·중복으로 무시
    COMMAND = "COMMAND"
    COMMAND_REJECTED = "COMMAND_REJECTED"
    CLAUDE_CALL = "CLAUDE_CALL"
    PAPER_FILL = "PAPER_FILL"
    PAPER_EXIT = "PAPER_EXIT"
    PAPER_FUNDING = "PAPER_FUNDING"
    CYCLE = "CYCLE"                         # 일일 사이클 시작·끝
    CONFIG_LOADED = "CONFIG_LOADED"
    STARTUP_CHECK = "STARTUP_CHECK"
    DATA_CHECK = "DATA_CHECK"               # 시세 이상·시계 오차
    FLAG_CHANGED = "FLAG_CHANGED"           # /pause /resume
    ALERT = "ALERT"


class SubsystemAction(str, Enum):
    """strategy.evaluate_day 결과: 하위 시스템 N 하나의 그날 판단."""

    ENTRY = "ENTRY"   # 진입 신호(포지션·진행 중 신호 없음 + close > U_N) → 신호 카드
    EXIT = "EXIT"     # 보유 중 청산 신호(close < D_M) → 자동 추세 청산
    HOLD = "HOLD"     # 보유 중, 청산 신호 없음
    NONE = "NONE"     # 포지션 없음, 진입 신호 없음 (또는 워밍업 전)
    BUSY = "BUSY"     # 승인 절차 중인 신호가 있음(보통 생기지 않음: 승인 창 2시간 < 하루)


# ---------------------------------------------------------------------------
# 신호 ID·callback_data
# ---------------------------------------------------------------------------
SIGNAL_ID_LEN = 16                                  # base32 16자 = 80비트 난수
SIGNAL_ID_RE = re.compile(r"[A-Z2-7]{16}")          # fullmatch로만 쓴다(끝 줄바꿈 허용 방지)
CALLBACK_VERSION = "v1"
CALLBACK_MAX_BYTES = 64                             # 텔레그램 callback_data 한도
_CALLBACK_RE = re.compile(r"v1:([ACXPD]):([A-Z2-7]{16})")


def new_signal_id() -> str:
    """추측 불가 난수 신호 ID (secrets, 80비트, base32 대문자 16자). 순번 금지 (ARCHITECTURE §4.3)."""
    return base64.b32encode(secrets.token_bytes(10)).decode("ascii")


def make_callback_data(action: CallbackAction, signal_id: str) -> str:
    if not isinstance(signal_id, str) or not SIGNAL_ID_RE.fullmatch(signal_id):
        raise ValueError("신호 ID 형식이 아님")
    data = f"{CALLBACK_VERSION}:{CallbackAction(action).value}:{signal_id}"
    if len(data.encode("ascii")) > CALLBACK_MAX_BYTES:  # 구조상 21바이트 — 방어적 검사
        raise ValueError("callback_data가 64바이트를 넘음")
    return data


@dataclass(frozen=True)
class ParsedCallback:
    action: CallbackAction
    signal_id: str


def parse_callback_data(data: object) -> ParsedCallback | None:
    """callback_data 엄격 파싱. 형식·버전·동작·ID가 하나라도 어긋나면 None (예외 없음).

    callback_data는 사용자 앱이 보낸 값이라 조작될 수 있다: 가격·수량은 절대 담지 않고 모든 값은 DB에서 꺼낸다.
    """
    if not isinstance(data, str) or len(data) > CALLBACK_MAX_BYTES:
        return None
    m = _CALLBACK_RE.fullmatch(data)
    if m is None:
        return None
    return ParsedCallback(CallbackAction(m.group(1)), m.group(2))


# ---------------------------------------------------------------------------
# 도메인 자료형
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubsystemSignal:
    """하위 시스템 N 하나의 그날 판단(strategy.evaluate_day 출력). 값은 모두 backtest.trend 계산 그대로."""

    n: int
    m: int                       # 청산 기간 M = exit_period(N)
    action: SubsystemAction
    side: int                    # +1 롱 (이 조합은 롱만). NONE이면 0
    signal_close_ns: int         # 신호 일봉 마감 = 다음 날 00:00 UTC
    decision_ns: int             # 판단 시각 = 마감 + 60초
    close: float                 # 당일 종가
    entry_level: float           # U_N (직전 N개 종가 최고, 당일 제외)
    exit_level: float            # D_M (직전 M개 종가 최저, 당일 제외)
    atr20: float                 # ATR20[t] (직전 20개 TR 평균, 현재 봉 제외)
    valid: bool                  # U_N·D_N·U_M·D_M·ATR20 모두 계산 가능(T-7)

    @property
    def stop_distance(self) -> float:
        """보호 손절 거리 = 2 × ATR20 (TrendConfig.stop_atr_mult)."""
        from backtest.trend import STOP_ATR_MULT  # 지역 import: 상수 하나만 쓴다
        return STOP_ATR_MULT * self.atr20


@dataclass(frozen=True)
class AnalystResult:
    """Claude 분석 결과. ok=False면 카드에 'Claude 분석 없음'을 쓰고 신호는 그대로 보낸다."""

    ok: bool
    status: str                         # 'ok'|'disabled'|'timeout'|'error'|'refusal'|'schema_invalid'|'truncated'
    prompt_version: str
    model: str
    summary: str = ""
    counter_evidence: tuple[str, ...] = ()
    invalidation: str = ""
    opinion: str | None = None          # 'approve'|'pass'
    confidence_note: str = ""
    input_json: str = ""                # 보낸 입력(수치 JSON)
    raw_response: str | None = None     # 원본 응답(JSON 직렬화). 비밀 없음
    stop_reason: str | None = None
    error: str | None = None            # 짧은 오류 요약(비밀·전체 스택 없음)
    latency_ms: int | None = None


@dataclass(frozen=True)
class Button:
    text: str
    callback_data: str


@dataclass(frozen=True)
class OutgoingMessage:
    """텔레그램으로 보낼 메시지 한 건(도메인 → telegram_ui). parse_mode는 쓰지 않는다(평문)."""

    text: str
    buttons: tuple[tuple[Button, ...], ...] = ()
    signal_id: str | None = None        # 카드면 신호 ID (전송 성공 후 CARD_SENT 전이에 쓴다)
    kind: str = "info"                  # 'card'|'confirm'|'fill'|'exit'|'expired'|'report'|'alert'|'info'
    edit_message_id: int | None = None  # 값이 있으면 새로 보내지 않고 그 메시지를 고친다(만료·처리 완료 표시, 버튼 제거)


# ---------------------------------------------------------------------------
# 인터페이스 (Protocol)
# ---------------------------------------------------------------------------


@runtime_checkable
class Clock(Protocol):
    def now_ns(self) -> int: ...


class SystemClock:
    """실시간 시계 (UTC ns)."""

    def now_ns(self) -> int:
        return time.time_ns()


@dataclass
class FakeClock:
    """재생·테스트용 시계. advance()/set()으로만 움직인다."""

    t_ns: int

    def now_ns(self) -> int:
        return int(self.t_ns)

    def set(self, t_ns: int) -> None:
        self.t_ns = int(t_ns)

    def advance(self, delta_ns: int) -> int:
        if delta_ns < 0:
            raise ValueError("시계를 되돌릴 수 없다")
        self.t_ns += int(delta_ns)
        return self.t_ns


@runtime_checkable
class MarketData(Protocol):
    """시세 공급원. 구현: marketdata.LiveBinance(공개 REST), marketdata.Replay(data/binance 파일).

    모든 메서드는 '마감된 봉만' 돌려준다: 반환 봉은 전부 close_ns ≤ 인자 시각. 미래 참조 금지는 구현의 책임.
    프레임 형식은 backtest.types.make_bars_frame 표준(열 open·high·low·close·volume·open_ns·close_ns).
    """

    def daily_bars(self, until_ns: int) -> pd.DataFrame:
        """close_ns ≤ until_ns 인 일봉 전체(시간순, 빈 구간 없음). 신호 계산 입력."""
        ...

    def minute_bars(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        """open_ns ≥ start_ns 이고 close_ns ≤ until_ns 인 1분봉(시간순)."""
        ...

    def funding(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        """start_ns < time_ns ≤ until_ns 인 펀딩(열 time_ns int64, rate float64)."""
        ...

    def server_time_ns(self) -> int | None:
        """거래소 서버 시각(시계 오차 검사용). 재생 모드는 None."""
        ...


@runtime_checkable
class ChatTransport(Protocol):
    """텔레그램 전송 계층(비동기). 구현: telegram_ui의 PTB 어댑터 / 테스트용 가짜. 받는 쪽은 허용 채팅 하나뿐."""

    async def send(self, text: str, buttons: tuple[tuple[Button, ...], ...] = ()) -> int:
        """허용 채팅에 평문 전송, message_id 반환. 실패하면 예외."""
        ...

    async def edit(self, message_id: int, text: str, buttons: tuple[tuple[Button, ...], ...] = ()) -> None: ...

    async def answer_callback(self, callback_query_id: str, text: str | None = None) -> None: ...


@runtime_checkable
class AnalystClient(Protocol):
    """Claude 호출 계층. 구현: analyst.AnthropicAnalystClient(실제) / 테스트용 가짜.

    analyze는 절대 예외를 밖으로 던지지 않는다: 실패는 AnalystResult(ok=False, status=...)로 돌려준다.
    """

    def analyze(self, input_payload: dict[str, Any]) -> AnalystResult: ...


@dataclass
class CycleReport:
    """engine.run_daily_cycle 결과: 보낼 메시지와 요약(테스트·로그용)."""

    decision_ns: int
    signals: list[SubsystemSignal] = field(default_factory=list)
    created_signal_ids: list[str] = field(default_factory=list)
    exit_position_ids: list[int] = field(default_factory=list)
    outgoing: list[OutgoingMessage] = field(default_factory=list)
    skipped_reason: str | None = None
