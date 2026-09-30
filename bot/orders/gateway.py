"""주문 게이트웨이(C11) — 게이트웨이 담당 (DESIGN §4).

한 의도를 한 번의 호출 안에서 끝까지(STOP_VERIFIED 또는 종료 상태) 끌고 간다. 순서(바꾸지 말 것):
  의도·신호 재확인 → 시계 → 계정 모드 → 레버리지·마진 → 심볼 규칙 → 포지션·미체결 0 → 계획(plan) → 방화벽
  → (K1 선배치면 손절 먼저) → entry_sent_ms 커밋 → IOC 진입 → 결과 판정(결과 모름이면 조회) → 손절 등록
  → 손절 존재 대조 → 실패 시 reduceOnly 시장가 청산 + T0.
- 모든 거래소 호출 전후 ``queue.add_event``. 모든 주문은 ``firewall.enforce_*`` 통과 후에만.
- 진입 POST는 의도당 최대 1회(재전송 금지). 손절은 같은 clientAlgoId로 최대 3회(재시도 전 조회). 청산은 reduceOnly.
- 게이트웨이 밖의 코드(대조기 포함)는 거래소 주문·취소를 직접 부르지 않는다: 청산은 ``flatten``/``run_trend_exit``,
  취소는 ``cancel_foreign``/``cancel_own_stop``을 거친다.

게이트웨이 담당의 해석(DESIGN과 다른 점이 아니라 빈칸 채우기 — decisions에 기록)
- 도착 기한(entry_deadline_ms, 서버 시각 기준) = 전송 직전 로컬 시각 + 측정 오프셋 + recvWindow + max_clock_skew_ms.
  클라이언트가 서명에 쓴 오프셋이 우리가 잰 값과 최대 max_clock_skew_ms만큼 다를 수 있으므로 그만큼 늦춰 잡는다(보수적).
- 무방비 시간(I2)의 시작점은 ``entry_sent_ms``(체결은 전송보다 이를 수 없다 — 가장 보수적인 기준).
- 사전 점검 조회가 실패(네트워크)하면 아무것도 보내지 않았으므로 REJECTED. ErrorPolicy.halt인 오류만 T0.

수정 담당(검토 지적 반영 — DESIGN §16 R-1..R-14)
- 노출 뒤 보호는 DB 쓰기에 묶이지 않는다(SEC-03·F4): 진입 전송 뒤 DB 예외가 나면 거래소 조회만으로 손절을 걸거나 청산한다
  (``emergency_protect``, 메모리의 보호 대상 ``_guard``). 전송 뒤 구간은 SQLite 대기 시간을 1초로 줄인다. 이벤트 기록 실패는
  메모리에 모았다가 나중에 쓴다(주문 흐름을 멈추지 않는다).
- 손절 없는 포지션을 그대로 두지 않는다(F3·F1·F5·F6·F9): 비상 청산이 실패하면 보호 손절을 다시 건다(``rearm_stop``),
  HALTED 보유는 대조마다 손절을 확인·재등록하고 안 되면 새 청산 주기(f1~f3 재사용)를 돈다(``secure_halted``).
- 429·418의 Retry-After 동안 어떤 호출도 보내지 않는다(``_x``의 대기 창, F2).
- 정지 판정은 DB ∪ B 전용 원장(ledger)의 T0, 해제는 그 T0 뒤에 처음 본 제어 파일 해제만(F8·SEC-02),
  누적 한도(하루 진입 수·T1·T2)는 B 원장 + B가 기록한 청산으로 계산(SEC-04).
"""
from __future__ import annotations

import contextlib
import dataclasses
import logging
import math
import sqlite3
import time
from enum import Enum
from typing import Any, Callable

from bot.orders import queue
from bot.orders.control import ControlState
from bot.orders.ledger import Ledger, LedgerError
from bot.orders.firewall import (
    FirewallContext,
    FirewallRejected,
    OrderPurpose,
    enforce_conditional,
    enforce_order,
)
from bot.orders.plan import PlanRejected, plan_entry, stop_for_fill
from bot.orders.types import (
    CONDITIONAL_ACTIVE_STATUSES,
    CONDITIONAL_FIRED_STATUSES,
    EXIT_ATTEMPTS,
    EXIT_PURPOSES,
    FLAT_PURPOSES,
    FLATTEN_ATTEMPTS,
    INTENT_TERMINAL,
    MAX_ENTRIES_PER_UTC_DAY,
    ORDER_FINAL_STATUSES,
    PRICE_TICK,
    QTY_STEP,
    STOP_PLACE_ATTEMPTS,
    SYMBOL,
    T1_STOPS,
    T1_WINDOW_MS,
    T2_LOSS_FRAC,
    T2_LOSS_R,
    UNKNOWN_GRACE_MS,
    UTC_DAY_MS,
    ConditionalInfo,
    ConditionalRequest,
    ErrorKind,
    ExchangeClient,
    ExchangeError,
    GatewayResult,
    HaltReason,
    IdPurpose,
    IntentExitReason,
    IntentState,
    OrderInfo,
    OrderRequest,
    OrdersConfig,
    OrderType,
    PositionInfo,
    Side,
    StopPlacement,
    TimeInForce,
    WorkingType,
    floor_to_step,
    make_client_id,
    parse_client_id,
)
from bot.types import Clock, NS_PER_MS, SignalState

log = logging.getLogger("bot.orders.gateway")

S = IntentState

# 결과 모름 조회 간격(ms, DESIGN §4.3: 0.5·1·2·4초 뒤 4초 반복)과 전체 한도
RESOLVE_BACKOFF_MS = (500, 1000, 2000, 4000)
RESOLVE_LIMIT_MS = 30_000
STOP_RETRY_SLEEP_MS = 300          # 손절 재시도 사이
VERIFY_POLLS = 3                   # 손절 접수 뒤 조회 대조 시도(조회 지연 흡수, 기한 안에서만)
VERIFY_POLL_SLEEP_MS = 400
CLOSE_POLL_SLEEP_MS = 300          # 청산 주문 뒤 포지션 재조회 전
POST_SEND_BUSY_TIMEOUT_MS = 1000   # 진입 전송 뒤 SQLite 잠금 대기 상한(보호를 DB 잠금에 오래 묶지 않는다, SEC-03)
EVENT_BACKLOG_MAX = 2000           # DB에 못 쓴 order_events를 메모리에 모으는 상한
RATE_LIMIT_DEFAULT_WAIT_MS = 1000  # 429에 Retry-After가 없을 때 기다리는 시간
IP_BAN_DEFAULT_WAIT_MS = 30_000    # 418에 Retry-After가 없을 때(금지 중 호출은 금지를 늘린다)
RATE_WAIT_MAX_MS = 20_000          # 호출 안에서 기다리는 상한. 더 길면(418 금지 등) 보내지 않고 곧바로 같은 오류로 실패
RELEASE_AT_TOLERANCE_MS = 60_000   # 제어 파일 at(사람이 적는 시각)과 T0 시각 비교 여유
TAKER_FEE_EST = 0.0005             # 실현 손익 추정(T2)의 수수료(편도, 보수적)
STOP_EXIT_REASONS = frozenset({IntentExitReason.STOP.value, IntentExitReason.STOP_IMMEDIATE.value})

# 이 오류들은 같은 요청을 다시 해도 소용없다(손절 재시도 대신 곧바로 청산 시도).
_NO_RETRY_KINDS = frozenset({ErrorKind.IP_BANNED, ErrorKind.REGION_BLOCKED, ErrorKind.AUTH, ErrorKind.CLOCK_SKEW})

_ERROR_HALT: dict[ErrorKind, HaltReason] = {
    ErrorKind.CLOCK_SKEW: HaltReason.CLOCK_SKEW,
    ErrorKind.INSUFFICIENT_MARGIN: HaltReason.BALANCE_MISMATCH,
    ErrorKind.ALGO_ENDPOINT_REQUIRED: HaltReason.ALGO_ENDPOINT,
    ErrorKind.ACCOUNT_MODE: HaltReason.ACCOUNT_MODE,
    ErrorKind.TRADING_RESTRICTED: HaltReason.TRADING_RESTRICTED,
    ErrorKind.IP_BANNED: HaltReason.EXCHANGE_BLOCK,
    ErrorKind.REGION_BLOCKED: HaltReason.EXCHANGE_BLOCK,
    ErrorKind.AUTH: HaltReason.AUTH,
}


def halt_reason_for(exc: ExchangeError) -> HaltReason:
    """ExchangeError → T0 사유(표에 없으면 ORDER_ERROR)."""
    return _ERROR_HALT.get(exc.kind, HaltReason.ORDER_ERROR)


def _jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _err_payload(method: str, exc: ExchangeError) -> dict[str, Any]:
    return {"method": method, "kind": exc.kind.value, "code": exc.code, "http": exc.http_status, "msg": exc.msg}


def stop_mismatches(c: ConditionalInfo | None, *, client_algo_id: str, stop_price: float | None) -> list[str]:
    """손절 대조(§4.4). 빈 목록이면 일치. 트리거는 틱 단위로 정확히 같아야 한다."""
    if c is None:
        return ["missing"]
    out: list[str] = []
    if c.client_algo_id != client_algo_id:
        out.append("client_algo_id")
    if c.symbol != SYMBOL:
        out.append("symbol")
    if c.side is not Side.SELL:
        out.append("side")
    if c.type is not OrderType.STOP_MARKET:
        out.append("type")
    if c.close_position is not True:
        out.append("close_position")
    if stop_price is None or not math.isfinite(float(c.trigger_price)) \
            or round(float(c.trigger_price) / PRICE_TICK) != round(float(stop_price) / PRICE_TICK):
        out.append("trigger_price")
    if c.working_type is not WorkingType.MARK_PRICE:
        out.append("working_type")
    if c.price_protect is not False:
        out.append("price_protect")
    if c.status not in CONDITIONAL_ACTIVE_STATUSES:
        out.append("status")
    return out


class _Done(Exception):
    """내부 제어 흐름: 의도가 어떤 상태로 끝났다."""

    def __init__(self, state: IntentState, reason: str | None = None) -> None:
        self.state = state
        self.reason = reason
        super().__init__(state.value)


def realized_pnl(row: Any) -> float | None:
    """끝난 보유의 실현 손익 추정(USDT, 수수료 포함). 청산가를 모르면 손절 청산은 손절가로, 그 밖은 None."""
    def g(k: str) -> Any:
        try:
            return row[k]
        except (KeyError, IndexError):
            return None
    avg = g("avg_fill_price")
    q = g("exit_qty") or g("filled_qty")
    px = g("exit_price")
    if px is None and g("exit_reason") in STOP_EXIT_REASONS:
        px = g("stop_price")
    if avg is None or q is None or px is None:
        return None
    avg, q, px = float(avg), float(q), float(px)
    if not (math.isfinite(avg) and math.isfinite(q) and math.isfinite(px)) or q <= 0 or avg <= 0 or px <= 0:
        return None
    return (px - avg) * q - TAKER_FEE_EST * q * (avg + px)


@dataclasses.dataclass
class _Guard:
    """DB 없이도 보호할 수 있도록 메모리에 두는 현재 노출 의도(SEC-03)."""
    intent_id: int
    signal_id: str
    atr20: float
    avg: float | None = None
    stop: float | None = None


class Gateway:
    def __init__(self, conn: sqlite3.Connection, cfg: OrdersConfig, ex: ExchangeClient, clock: Clock, *,
                 base_url: str, sleep_ms: Callable[[int], None] | None = None,
                 ledger: Ledger | None = None) -> None:
        self.conn = conn
        self.cfg = cfg
        self.ex = ex
        self.clock = clock
        self.base_url = base_url
        self._sleep_ms = sleep_ms or self._default_sleep
        self.ledger = ledger if ledger is not None else Ledger(None)
        self.released: frozenset[int] = frozenset()
        self.halt_ids: list[int] = []           # 이번 공개 호출에서 건 T0 id
        self.clock_offset_ms: int = 0           # 마지막 측정(서버 − 로컬)
        self._guard: _Guard | None = None
        self._rate_until_ms = 0                 # 429·418 대기 창의 끝(로컬 ms) — 그 전에는 어떤 호출도 보내지 않는다
        self._rate_kind = ErrorKind.RATE_LIMITED
        self._event_backlog: list[dict[str, Any]] = []
        self._raw_flat_n = 0                    # DB 없는 비상 청산의 f 번호 순환
        self._block_alerted: set[tuple[str, int]] = set()
        self._tamper_hw: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 기본 도구
    # ------------------------------------------------------------------
    def _default_sleep(self, ms: int) -> None:
        adv = getattr(self.clock, "advance", None)
        if adv is not None:
            adv(int(ms) * NS_PER_MS)            # FakeClock(시험): 시계만 진행
        else:  # pragma: no cover - 실시간
            time.sleep(ms / 1000.0)

    def now_ms(self) -> int:
        return int(self.clock.now_ns()) // NS_PER_MS

    def sleep(self, ms: int) -> None:
        if ms > 0:
            self._sleep_ms(int(ms))

    # --- T0 판정 재료: DB ∪ B 원장, 해제는 T0 뒤에 처음 본 제어 파일 해제만(F8·SEC-02) ---
    def _halt_ts_map(self) -> dict[int, int]:
        m: dict[int, int] = {int(r["halt_id"]): int(r["ts_ms"]) for r in queue.halts(self.conn)}
        for h in self.ledger.halts():
            hid, ts = int(h["id"]), int(h["ts"])
            m[hid] = max(m.get(hid, ts), ts)          # 같은 번호가 다른 T0면 더 늦은 시각(더 엄격)
        return m

    def set_control(self, control: ControlState) -> None:
        """제어 파일 상태 → 실제로 인정하는 해제 집합(self.released).

        해제 id는 (1) 그 T0가 DB 또는 B 원장에 있고 (2) B가 그 id를 **T0 시각 이후에 처음 봤고** (3) at을 적었다면 그 시각이
        T0보다 이르지 않을 때만 인정한다. DB 복원·재생성으로 같은 번호가 다시 쓰여도 옛 해제가 새 T0를 풀지 못한다."""
        now = self.now_ms()
        if control.error is None:
            self.ledger.forget_release_seen(control.released)
        ts = self._halt_ts_map()
        at = dict(control.release_at)
        eff: set[int] = set()
        for hid in sorted(int(x) for x in control.released):
            seen = self.ledger.release_first_seen(hid, now)
            t = ts.get(hid)
            if t is None or seen < t:
                continue
            a = at.get(hid)
            if a is not None and a < t - RELEASE_AT_TOLERANCE_MS:
                continue
            eff.add(hid)
        self.released = frozenset(eff)

    def active_halt_ids(self) -> list[int]:
        """풀리지 않은 T0 id(DB ∪ B 원장). set_control 뒤의 self.released 기준."""
        return sorted(h for h in self._halt_ts_map() if h not in self.released)

    def _flush_events(self) -> None:
        while self._event_backlog:
            queue.add_event(self.conn, **self._event_backlog[0])
            self._event_backlog.pop(0)

    def _event(self, intent_id: int | None, kind: str, *, client_id: str | None = None,
               payload: Any = None) -> None:
        """order_events 기록. DB 쓰기가 실패해도 주문 흐름을 멈추지 않는다(메모리에 모았다가 다음에 쓴다, SEC-03·F4)."""
        rec = dict(intent_id=intent_id, kind=kind, now_ms=self.now_ms(), client_id=client_id,
                   payload=None if payload is None else _jsonable(payload))
        try:
            self._flush_events()
            queue.add_event(self.conn, **rec)
        except sqlite3.Error as exc:
            if len(self._event_backlog) < EVENT_BACKLOG_MAX:
                self._event_backlog.append(rec)
            log.warning("주문 이벤트 DB 기록 실패(%s) — 메모리에 보관(%d건)", type(exc).__name__,
                        len(self._event_backlog))

    # --- 429·418 대기 창(F2): 창 안에서 다시 부르면 위반이 쌓여 IP 금지로 번진다 ---
    def rate_wait(self) -> None:
        """대기 창이 열려 있으면 끝까지 기다린다. 남은 시간이 RATE_WAIT_MAX_MS보다 길면(긴 418 금지) 기다리지도 보내지도 않고
        ExchangeError(원래 종류)로 곧바로 실패한다 — 루프는 계속 돌고(심장 박동·대조 기록), 금지를 늘리지 않는다."""
        now = self.now_ms()
        if now >= self._rate_until_ms:
            return
        left = self._rate_until_ms - now
        if left > RATE_WAIT_MAX_MS:
            raise ExchangeError(self._rate_kind, http_status=429 if self._rate_kind is ErrorKind.RATE_LIMITED else 418,
                                msg="local rate gate (not sent)", retry_after_s=left / 1000.0)
        self.sleep(left)

    def note_exchange_error(self, exc: ExchangeError) -> None:
        if exc.kind not in (ErrorKind.RATE_LIMITED, ErrorKind.IP_BANNED):
            return
        if exc.retry_after_s is not None and math.isfinite(float(exc.retry_after_s)) and exc.retry_after_s > 0:
            wait = int(math.ceil(float(exc.retry_after_s) * 1000)) + 50
        else:
            wait = RATE_LIMIT_DEFAULT_WAIT_MS if exc.kind is ErrorKind.RATE_LIMITED else IP_BAN_DEFAULT_WAIT_MS
        until = self.now_ms() + wait
        if until > self._rate_until_ms:
            self._rate_until_ms = until
            self._rate_kind = exc.kind

    def _x(self, intent_id: int | None, method: str, *args: Any, client_id: str | None = None,
           post: bool = False, log_query: bool = False) -> Any:
        """거래소 호출 + 기록. 주문·취소(post)는 REQUEST/RESPONSE, 조회는 log_query일 때 QUERY. 오류는 ERROR.
        429·418의 대기 창이 열려 있으면 먼저 기다린다(창 안에서는 어떤 요청도 보내지 않는다)."""
        try:
            self.rate_wait()
        except ExchangeError as exc:
            self._event(intent_id, "ERROR", client_id=client_id, payload=_err_payload(method, exc))
            raise
        if post:
            self._event(intent_id, "REQUEST", client_id=client_id,
                        payload={"method": method, "request": args[0] if args else None})
        try:
            res = getattr(self.ex, method)(*args)
        except ExchangeError as exc:
            self.note_exchange_error(exc)
            self._event(intent_id, "ERROR", client_id=client_id, payload=_err_payload(method, exc))
            raise
        if post:
            self._event(intent_id, "RESPONSE", client_id=client_id, payload={"method": method, "response": res})
        elif log_query:
            self._event(intent_id, "QUERY", client_id=client_id, payload={"method": method, "result": res})
        return res

    def _halt(self, reason: HaltReason, *, intent_id: int | None, detail: dict | None = None,
              alert_text: str | None = None) -> int:
        now = self.now_ms()
        hid = queue.raise_halt(self.conn, reason=reason, now_ms=now, intent_id=intent_id,
                               detail=_jsonable(detail) if detail else None, alert_text=alert_text)
        self.halt_ids.append(hid)
        try:
            self.ledger.record_halt(hid, now, HaltReason(reason).value, intent_id)
        except LedgerError:
            log.error("B 원장에 T0 #%d 기록 실패 — 원장 오류로 신규 진입 차단", hid)
        # B 자신의 로그(docker logs)에도 남긴다: outbox 경보는 A가 보내므로 A가 숨길 수 있다(SEC-06 완화)
        log.warning("킬 스위치 T0 #%d: %s (의도 %s)", hid, HaltReason(reason).value, intent_id)
        return hid

    def halt_once(self, reason: HaltReason, *, intent_id: int | None, detail: dict | None = None,
                  alert_text: str | None = None) -> int:
        """같은 사유·의도의 풀리지 않은 T0가 이미 있으면 새로 걸지 않는다(대조기 반복 경보 방지, §7.2)."""
        rows = [(int(r["halt_id"]), r["reason"], r["intent_id"]) for r in queue.halts(self.conn)]
        seen = {h for h, _, _ in rows}
        rows += [(int(h["id"]), h["reason"], h["intent"]) for h in self.ledger.halts() if int(h["id"]) not in seen]
        for hid, rsn, r_iid in rows:
            if hid in self.released:
                continue
            same_intent = (r_iid is None and intent_id is None) or (
                r_iid is not None and intent_id is not None and int(r_iid) == int(intent_id))
            if rsn == reason.value and same_intent:
                return hid
        return self._halt(reason, intent_id=intent_id, detail=detail, alert_text=alert_text)

    def _notify(self, text: str, *, signal_id: str | None = None, kind: str = "info") -> None:
        queue.notify(self.conn, text, now_ms=self.now_ms(), signal_id=signal_id, kind=kind)

    def _row(self, intent_id: int) -> sqlite3.Row:
        row = queue.get_intent(self.conn, intent_id)
        if row is None:
            raise LookupError(f"의도 없음: {intent_id}")
        return row

    def _state(self, intent_id: int) -> IntentState:
        return IntentState(self._row(intent_id)["state"])

    def _transition(self, row: sqlite3.Row, new: IntentState, *, reason: str | None,
                    fields: dict | None = None, expected: Any = None) -> IntentState:
        iid = int(row["intent_id"])
        exp = expected if expected is not None else IntentState(row["state"])
        ok = queue.transition(self.conn, iid, exp, new, now_ms=self.now_ms(), reason=reason, fields=fields)
        if not ok:
            self._event(iid, "NOTE", payload={"transition_lost": True, "to": new.value,
                                              "now": self._state(iid).value})
        elif new in (S.CLOSED, S.FAILED_FLATTENED):
            self._ledger_close(iid)
        return self._state(iid)

    def transition(self, row: sqlite3.Row, new: IntentState, *, reason: str | None, fields: dict | None = None,
                   expected: Any = None) -> IntentState:
        """대조기용 공개 전이(B 원장의 청산 기록 포함)."""
        return self._transition(row, new, reason=reason, fields=fields, expected=expected)

    def _ledger_close(self, iid: int) -> None:
        row = self._row(iid)
        if row["filled_qty"] is None or float(row["filled_qty"]) <= 0:
            return
        try:
            self.ledger.record_close(row["signal_id"], int(row["closed_ms"] or self.now_ms()),
                                     str(row["exit_reason"] or "unknown"), realized_pnl(row))
        except LedgerError:
            log.error("B 원장에 청산 기록 실패(의도 #%d) — 원장 오류로 신규 진입 차단", iid)

    def _set_guard(self, row: sqlite3.Row) -> None:
        def f(k: str) -> float | None:
            v = row[k]
            return float(v) if v is not None and math.isfinite(float(v)) and float(v) > 0 else None
        self._guard = _Guard(intent_id=int(row["intent_id"]), signal_id=row["signal_id"], atr20=float(row["atr20"]),
                             avg=f("avg_fill_price"), stop=f("stop_price"))

    def _fw_ctx(self, row: sqlite3.Row, *, mark: float | None, position_qty: float, **kw: Any) -> FirewallContext:
        return FirewallContext(cfg=self.cfg, client_base_url=self.base_url, signal_id=row["signal_id"],
                               mark_price=mark, position_qty=position_qty, **kw)

    def _result(self, intent_id: int, reason: str | None = None) -> GatewayResult:
        row = self._row(intent_id)
        return GatewayResult(intent_id=intent_id, final_state=IntentState(row["state"]),
                             reason=reason or row["state_reason"], halt_ids=list(self.halt_ids),
                             unprotected_ms=row["unprotected_ms"])

    # ------------------------------------------------------------------
    # 정지·큐 정리
    # ------------------------------------------------------------------
    def block_reason(self, control: ControlState) -> str | None:
        """신규 진입을 막는 이유(없으면 None): 'halted'(수동 정지·풀리지 않은 T0), 'ledger_unavailable'(B 원장 오류),
        누적 한도 'daily_entry_cap'·'t1_stop_streak'·'t2_daily_loss'(다음 UTC 00:00 자동 해제)."""
        self.set_control(control)
        if control.manual_halt or self.active_halt_ids():
            return "halted"
        if self.ledger.error is not None:
            self._alert_block_once("ledger_unavailable", f"B 전용 원장 오류({self.ledger.error}) — 신규 진입 차단"
                                   "(보유 손절·청산은 계속). 서버에서 /state 볼륨 확인(RUNBOOK §T6)")
            return "ledger_unavailable"
        agg = self.aggregate_block(self.now_ms())
        if agg is not None:
            self._alert_block_once(agg, f"누적 한도 {agg} — 다음 UTC 00:00(KST 09:00)까지 신규 진입 차단"
                                   "(보유 손절·추세 청산은 계속)")
        return agg

    def is_halted(self, control: ControlState) -> bool:
        """block_reason이 있으면 True(수동 정지, 풀리지 않은 T0, B 원장 오류, 누적 한도)."""
        return self.block_reason(control) is not None

    def _alert_block_once(self, reason: str, text: str) -> None:
        now = self.now_ms()
        key = (reason, now - now % UTC_DAY_MS)
        if key in self._block_alerted:
            return
        self._block_alerted.add(key)
        log.warning("신규 진입 차단: %s", reason)
        try:
            self._notify(text, kind="alert")
        except sqlite3.Error:
            pass

    # --- 누적 한도(SEC-04) — B 원장(A가 못 씀) ∪ DB의 B 기록. DB에서 A가 지우면 원장이 남고, 더하면 더 막힐 뿐 ---
    def _closes(self, since_ms: int) -> dict[str, tuple[int, str, float | None]]:
        out: dict[str, tuple[int, str, float | None]] = {}
        for r in self.conn.execute(
                "SELECT * FROM order_intents WHERE state IN ('CLOSED', 'FAILED_FLATTENED') AND closed_ms >= ?"
                " AND filled_qty > 0", (int(since_ms),)):
            out[r["signal_id"]] = (int(r["closed_ms"]), str(r["exit_reason"]), realized_pnl(r))
        for c in self.ledger.closes():
            if int(c["ts"]) >= since_ms:
                out[c["sid"]] = (int(c["ts"]), str(c["reason"]), c["pnl"])
        return out

    def aggregate_block(self, now: int) -> str | None:
        day0 = now - now % UTC_DAY_MS
        sids = {e["sid"] for e in self.ledger.entries() if day0 <= int(e["ts"]) <= now}
        sids |= {r[0] for r in self.conn.execute(
            "SELECT signal_id FROM order_intents WHERE entry_sent_ms >= ? AND entry_sent_ms <= ?", (day0, now))}
        if len(sids) >= MAX_ENTRIES_PER_UTC_DAY:
            return "daily_entry_cap"
        closes = self._closes(day0 - T1_WINDOW_MS - UTC_DAY_MS)
        stops = sorted(ts for ts, reason, _ in closes.values() if reason in STOP_EXIT_REASONS)
        for i in range(T1_STOPS - 1, len(stops)):
            if stops[i] - stops[i - T1_STOPS + 1] <= T1_WINDOW_MS:
                release = stops[i] - stops[i] % UTC_DAY_MS + UTC_DAY_MS
                if now < release:
                    return "t1_stop_streak"
        r_unit = float(self.cfg.r_capital_usdt) * float(self.cfg.risk_fraction)
        pnl = sum((p if p is not None else -r_unit) for ts, _, p in closes.values() if day0 <= ts <= now)
        if pnl <= -min(T2_LOSS_R * r_unit, T2_LOSS_FRAC * float(self.cfg.r_capital_usdt)):
            return "t2_daily_loss"
        return None

    # --- DB 무결성(SEC-02) ---
    def check_integrity(self) -> list[str]:
        """추가 전용 표·보호 트리거의 변조 흔적 → T0(ORDER_ERROR, why=db_integrity). 사람이 그 T0를 제어 파일로 풀면
        그 문제 서명은 확인된 것으로 원장에 남겨 같은 문제로 다시 걸지 않는다. 새로 걸었거나 유지 중인 문제 목록."""
        probs = queue.integrity_problems(self.conn)
        try:
            seqs = {r[0]: int(r[1]) for r in self.conn.execute("SELECT name, seq FROM sqlite_sequence")}
        except sqlite3.Error:
            seqs = {}
        for table in queue.APPEND_ONLY_TABLES:
            cur = seqs.get(table, 0)
            hw = self._tamper_hw.get(table, 0)
            if cur < hw:
                probs.append(f"{table}_rewound:{hw}->{cur}")
            self._tamper_hw[table] = max(hw, cur)
        for hid, sigs in self.ledger.tamper_halts().items():
            if hid in self.released:
                self.ledger.accept_tamper(sigs)
        new = [p for p in probs if not self.ledger.tamper_accepted(p)]
        if new:
            hid = self.halt_once(HaltReason.ORDER_ERROR, intent_id=None,
                                 detail={"why": "db_integrity", "problems": new},
                                 alert_text="[TESTNET] 킬 스위치 T0: 주문 DB 변조 흔적(" + ", ".join(new[:5]) +
                                            ") — A 침해 의심. 서버에서 확인 전 해제 금지(RUNBOOK §T6)")
            self.ledger.note_tamper_halt(hid, new)
        return new

    def _reject_queued(self, reason: str, pred: Callable[[sqlite3.Row], bool] = lambda r: True) -> int:
        n = 0
        for row in queue.intents_in_states(self.conn, [S.QUEUED]):
            if pred(row) and queue.transition(self.conn, int(row["intent_id"]), S.QUEUED, S.REJECTED,
                                              now_ms=self.now_ms(), reason=reason):
                n += 1
                self._notify(f"주문 거부({reason}): 신호 {row['signal_id']}", signal_id=row["signal_id"])
        return n

    def reject_queued_if_halted(self, control: ControlState) -> int:
        """정지 중이면 QUEUED 전부 REJECTED(block_reason: 'halted'·누적 한도 등). 바꾼 수."""
        reason = self.block_reason(control)
        if reason is None:
            return 0
        return self._reject_queued(reason)

    def reject_stale_queued(self) -> int:
        """승인 뒤 claim_max_age_ms가 지난 QUEUED → REJECTED('stale_approval') (재시작이 길었을 때 등).
        승인 시각이 미래(시계 오차 한도 넘게)인 것도 거부한다('future_approval' — 위조·시계 오류, SEC-05)."""
        now = self.now_ms()
        n = self._reject_queued("stale_approval",
                                lambda r: int(r["approved_ms"]) + self.cfg.claim_max_age_ms < now)
        return n + self._reject_queued("future_approval",
                                       lambda r: int(r["approved_ms"]) > now + self.cfg.max_clock_skew_ms)

    def reject_queued_if_position_exists(self) -> int:
        """노출 의도가 있으면 QUEUED 전부 REJECTED('position_exists') — O-3(동시 1포지션)."""
        if queue.live_intent(self.conn) is None:
            return 0
        return self._reject_queued("position_exists")

    # ------------------------------------------------------------------
    # §4.1 전체
    # ------------------------------------------------------------------
    def process_intent(self, intent_row: sqlite3.Row, control: ControlState) -> GatewayResult:
        """SUBMITTING 의도 하나를 §4.1 순서대로 처리."""
        self.halt_ids = []
        iid = int(intent_row["intent_id"])
        row = self._row(iid)
        if IntentState(row["state"]) is not S.SUBMITTING:
            return self._result(iid, "not_submitting")
        if row["entry_sent_ms"] is not None:
            # 이미 보냈을 수 있다 → 절대 다시 보내지 않고 조회로만(재시작·중복 호출)
            self._set_guard(row)
            with self._post_send_guard():
                st = self.resolve_entry(row)
                if st in (S.ENTRY_FILLED, S.STOP_PLACED):
                    self.ensure_stop(self._row(iid))
            return self._result(iid)
        try:
            self._submit(row, control)
        except _Done as d:
            return self._result(iid, d.reason)
        return self._result(iid)

    @contextlib.contextmanager
    def _post_send_guard(self):
        """진입 전송 뒤 구간: SQLite 잠금 대기를 줄이고, 거래소 밖 예외(DB 잠김 등)가 나면 **DB 없이** 포지션을 보호한 뒤
        예외를 다시 올린다(SEC-03·F4). 워커는 다음 바퀴에 복구(recover)를 돈다."""
        with self._db_busy_limit(POST_SEND_BUSY_TIMEOUT_MS):
            try:
                yield
            except _Done:
                raise
            except Exception as exc:
                log.error("진입 전송 뒤 예외(%s) — DB 없이 보호 시도", type(exc).__name__)
                try:
                    self.emergency_protect(f"post_send:{type(exc).__name__}")
                except Exception as exc2:  # noqa: BLE001 — 보호 시도 실패는 원래 예외를 가리지 않는다
                    log.error("비상 보호 실패: %s", type(exc2).__name__)
                raise

    @contextlib.contextmanager
    def _db_busy_limit(self, ms: int):
        try:
            cur = int(self.conn.execute("PRAGMA busy_timeout").fetchone()[0])
        except (sqlite3.Error, TypeError, ValueError):
            cur = None
        changed = cur is not None and cur > ms
        if changed:
            self.conn.execute(f"PRAGMA busy_timeout = {int(ms)}")
        try:
            yield
        finally:
            if changed:
                try:
                    self.conn.execute(f"PRAGMA busy_timeout = {int(cur)}")
                except sqlite3.Error:
                    pass

    def _reject(self, row: sqlite3.Row, reason: str, *, halt: HaltReason | None = None,
                detail: dict | None = None) -> None:
        iid = int(row["intent_id"])
        fields: dict[str, Any] = {}
        if halt is not None:
            fields["halt_id"] = self._halt(halt, intent_id=iid, detail={"why": reason, **(detail or {})})
        st = self._transition(row, S.REJECTED, reason=reason, fields=fields or None, expected=S.SUBMITTING)
        self._notify(f"주문 거부({reason}): 신호 {row['signal_id']}" + (" — 킬 스위치 T0" if halt else ""),
                     signal_id=row["signal_id"])
        raise _Done(st, reason)

    def _precheck_error(self, row: sqlite3.Row, step: str, exc: ExchangeError) -> None:
        """사전 점검 조회 실패: 보낸 것이 없으므로 REJECTED. 정책상 halt인 오류만 T0."""
        halt = halt_reason_for(exc) if exc.halts else None
        self._reject(row, f"precheck_{step}:{exc.kind.value.lower()}", halt=halt,
                     detail={"kind": exc.kind.value, "code": exc.code, "http": exc.http_status})

    def _submit(self, row: sqlite3.Row, control: ControlState) -> None:
        iid = int(row["intent_id"])
        sid = row["signal_id"]
        now = self.now_ms()
        block = self.block_reason(control)
        halted = block is not None
        # 0) 정지 중(T0·수동·원장 오류·누적 한도)이면 보내지 않는다
        if halted:
            self._reject(row, block)
        # 1) 의도·신호 재확인
        sig = self.conn.execute("SELECT * FROM signals WHERE signal_id = ?", (sid,)).fetchone()
        if sig is None or sig["state"] != SignalState.APPROVED.value or int(sig["side"]) != 1 \
                or sig["atr20"] is None or not math.isfinite(float(sig["atr20"])) or float(sig["atr20"]) <= 0 \
                or not math.isclose(float(sig["atr20"]), float(row["atr20"]), rel_tol=0, abs_tol=1e-9) \
                or sig["approved_ms"] is None or int(sig["approved_ms"]) != int(row["approved_ms"]):
            self._reject(row, "signal_mismatch")
        if now - int(row["approved_ms"]) > self.cfg.claim_max_age_ms:
            self._reject(row, "stale_approval")
        if int(row["approved_ms"]) > now + self.cfg.max_clock_skew_ms:
            self._reject(row, "future_approval")          # 미래 시각 승인(위조·시계 오류) — SEC-05
        atr20 = float(row["atr20"])

        # 2) 시계
        try:
            server = int(self._x(iid, "server_time_ms"))
        except ExchangeError as exc:
            self._precheck_error(row, "time", exc)
        offset = server - self.now_ms()
        self.clock_offset_ms = offset
        if abs(offset) > self.cfg.max_clock_skew_ms:
            self._reject(row, "clock_skew", halt=HaltReason.CLOCK_SKEW, detail={"offset_ms": offset})

        # 3) 계정 모드
        try:
            acc = self._x(iid, "account_config", log_query=True)
        except ExchangeError as exc:
            self._precheck_error(row, "account", exc)
        if acc.dual_side_position is not False or acc.multi_assets_margin is not False \
                or acc.can_trade is not True or acc.can_withdraw is True:
            self._reject(row, "account_mode", halt=HaltReason.ACCOUNT_MODE, detail={"account": acc})
        # 4) 레버리지·마진(검사만, 바꾸지 않는다)
        if isinstance(acc.leverage, bool) or not isinstance(acc.leverage, int) \
                or acc.leverage != self.cfg.expected_leverage or str(acc.margin_type).lower() != "isolated":
            self._reject(row, "leverage_margin", halt=HaltReason.LEVERAGE_MARGIN, detail={"account": acc})
        # 5) 심볼 규칙
        try:
            rules = self._x(iid, "symbol_rules")
        except ExchangeError as exc:
            self._precheck_error(row, "rules", exc)
        if rules.symbol != SYMBOL or rules.status != "TRADING" or not math.isclose(rules.tick_size, PRICE_TICK) \
                or not math.isclose(rules.step_size, QTY_STEP):
            self._reject(row, "symbol_rules", halt=HaltReason.SYMBOL_RULES, detail={"rules": rules})
        # 6) 상태 사전 조건: 포지션 0, 미체결 0, 조건부 0
        try:
            pos = self._x(iid, "position", log_query=True)
            oo = list(self._x(iid, "open_orders"))
            oc = list(self._x(iid, "open_conditional_orders"))
        except ExchangeError as exc:
            self._precheck_error(row, "state", exc)
        if float(pos.qty) != 0.0:
            self._reject(row, "unknown_position", halt=HaltReason.UNKNOWN_POSITION, detail={"position": pos})
        if oo or oc:
            self._reject(row, "unknown_order", halt=HaltReason.UNKNOWN_ORDER,
                         detail={"open_orders": [o.client_id for o in oo],
                                 "open_conditionals": [c.client_algo_id for c in oc]})
        try:
            mark = float(self._x(iid, "mark_price"))
            bal = self._x(iid, "balance")
        except ExchangeError as exc:
            self._precheck_error(row, "market", exc)

        # 7) 계획
        try:
            plan = plan_entry(mark_price=mark, atr20=atr20, cfg=self.cfg, rules=rules)
        except PlanRejected as pr:
            self._reject(row, pr.reason)
        e1 = make_client_id(sid, IdPurpose.ENTRY)
        req = OrderRequest(symbol=SYMBOL, side=Side.BUY, type=OrderType.LIMIT, qty=plan.qty, client_id=e1,
                           price=plan.limit_price, time_in_force=TimeInForce.IOC, reduce_only=False)
        # 8) 방화벽(진입)
        ctx = self._fw_ctx(row, mark=mark, position_qty=float(pos.qty), account=acc, rules=rules, balance=bal,
                           open_orders=tuple(oo), open_conditionals=tuple(oc), halted=halted,
                           entry_already_sent=row["entry_sent_ms"] is not None, planned_stop=plan.planned_stop)
        try:
            verdict = enforce_order(req, OrderPurpose.ENTRY, ctx)
        except FirewallRejected as fr:
            self._event(iid, "FIREWALL", client_id=e1, payload=fr.verdict.as_json())
            self._reject(row, "firewall", halt=HaltReason.FIREWALL, detail={"violations": list(fr.verdict.violations)})
        self._event(iid, "FIREWALL", client_id=e1, payload=verdict.as_json())

        # 8') K1 선배치 경로: 손절 먼저 걸고 대조
        pre_stop: float | None = None
        if self.cfg.stop_placement is StopPlacement.PRE_ENTRY:
            pre_stop = plan.planned_stop
            self._pre_arm_stop(row, stop=pre_stop, mark=mark, ref_price=plan.limit_price)

        # 9) 진입 전송 기록(커밋 후 전송). B 원장(누적 한도의 근거)에 먼저 남긴다 — 못 남기면 보내지 않는다.
        sent = self.now_ms()
        deadline = sent + self.clock_offset_ms + self.cfg.recv_window_ms + self.cfg.max_clock_skew_ms
        try:
            self.ledger.record_entry(sid, sent)
        except LedgerError:
            if pre_stop is not None:
                self.cancel_own_stop(row)
            self._reject(row, "ledger_unavailable")
        ok = queue.update_fields(self.conn, iid, S.SUBMITTING, {
            "entry_client_id": e1, "entry_sent_ms": sent, "entry_deadline_ms": deadline, "mark_price": mark,
            "limit_price": plan.limit_price, "planned_stop": plan.planned_stop, "planned_qty": plan.qty,
        }, now_ms=sent)
        if not ok:
            if pre_stop is not None:
                self.cancel_own_stop(row)
            raise _Done(self._state(iid), "entry_record_failed")   # 상태가 바뀌었다(다른 주체) — 보내지 않는다
        row = self._row(iid)
        self._set_guard(row)
        if pre_stop is not None and self._guard is not None:
            self._guard.stop = pre_stop

        # 10) 진입 — 여기부터는 노출이 있을 수 있다: DB 예외가 나도 거래소 조회만으로 보호(_post_send_guard)
        with self._post_send_guard():
            try:
                info = self._x(iid, "place_order", req, client_id=e1, post=True)
            except ExchangeError as exc:
                if exc.outcome_unknown:
                    st = self.resolve_entry(row)
                else:
                    st = self._entry_rejected(row, exc)
            else:
                if float(info.executed_qty) > 0 and math.isfinite(float(info.avg_price)) \
                        and float(info.avg_price) > 0 and self._guard is not None:
                    self._guard.avg = float(info.avg_price)
                if info.status in ORDER_FINAL_STATUSES:
                    st = self._entry_outcome(row, info)
                else:
                    st = self.resolve_entry(row)      # IOC인데 끝나지 않은 응답 → 조회로 확정
            if st in (S.ENTRY_FILLED, S.STOP_PLACED):
                # 11)·12) 손절 등록·대조(실패하면 청산 + T0)
                self.ensure_stop(self._row(iid))

    # --- 진입 결과 ---
    def _entry_rejected(self, row: sqlite3.Row, exc: ExchangeError) -> IntentState:
        """확정 거부: 주문 없음 → NOT_FILLED. halt 정책 오류는 T0."""
        fields: dict[str, Any] = {}
        if exc.halts:
            fields["halt_id"] = self._halt(halt_reason_for(exc), intent_id=int(row["intent_id"]),
                                           detail={"entry_error": exc.kind.value, "code": exc.code})
        self._cancel_pre_stop_if_any(row)
        st = self._transition(row, S.NOT_FILLED, reason=f"entry_rejected:{exc.kind.value.lower()}",
                              fields=fields or None, expected=S.SUBMITTING)
        self._notify(f"진입 거부({exc.kind.value}, code {exc.code}): 신호 {row['signal_id']} — 체결 없음"
                     + (", 킬 스위치 T0" if exc.halts else ""), signal_id=row["signal_id"])
        return st

    def _entry_outcome(self, row: sqlite3.Row, info: OrderInfo, *, source: str = "response") -> IntentState:
        if float(info.executed_qty) > 0:
            return self._record_fill(row, qty=float(info.executed_qty), avg=float(info.avg_price),
                                     order_id=info.exchange_order_id, source=source)
        self._cancel_pre_stop_if_any(row)
        st = self._transition(row, S.NOT_FILLED, reason="entry_not_filled",
                              fields={"entry_order_id": info.exchange_order_id}, expected=S.SUBMITTING)
        self._notify(f"진입 미체결(IOC 만료): 신호 {row['signal_id']} — 포지션 없음", signal_id=row["signal_id"])
        return st

    def _record_fill(self, row: sqlite3.Row, *, qty: float, avg: float, order_id: str | None,
                     source: str) -> IntentState:
        iid = int(row["intent_id"])
        if not (math.isfinite(qty) and qty > 0 and math.isfinite(avg) and avg > 0):
            # 체결 수량은 있는데 평균가를 모른다 → 포지션 조회로 보충
            try:
                pos = self._x(iid, "position", log_query=True)
                if float(pos.qty) > 0 and float(pos.entry_price) > 0:
                    avg = float(pos.entry_price)
            except ExchangeError:
                pass
        if not (math.isfinite(avg) and avg > 0):
            hid = self._halt(HaltReason.OUTCOME_UNRESOLVED, intent_id=iid, detail={"why": "fill_price_unknown"})
            return self._transition(row, S.HALTED, reason="fill_price_unknown", fields={"halt_id": hid},
                                    expected=S.SUBMITTING)
        now = self.now_ms()
        if self._guard is not None and self._guard.intent_id == iid:
            self._guard.avg = avg
        fields = {"filled_qty": qty, "avg_fill_price": avg, "entry_fill_ms": now, "entry_order_id": order_id}
        cur = self._row(iid)
        if cur["stop_placed_ms"] is not None and cur["stop_client_id"] is not None:
            # K1 선배치 경로: 손절이 이미 접수돼 있다
            st = self._transition(cur, S.STOP_PLACED, reason=f"entry_filled:{source}", fields=fields,
                                  expected=S.SUBMITTING)
        else:
            st = self._transition(cur, S.ENTRY_FILLED, reason=f"entry_filled:{source}", fields=fields,
                                  expected=S.SUBMITTING)
        if st in INTENT_TERMINAL:
            # 다른 주체(두 번째 B·대조)가 먼저 '체결 없음'으로 끝냈다. 거래소의 체결은 우리 것이다 → 손절 없이 두지 않는다(F6)
            self.handle_orphan_fill(self._row(iid), avg=avg, why=f"fill_after_{st.value.lower()}")
        elif st is S.HALTED:
            st = self.secure_halted(self._row(iid))
        return st

    def resolve_entry(self, intent_row: sqlite3.Row) -> IntentState:
        """진입 결과 모름 절차(§4.3): get_order(e1)·position() 조회, 도착 기한 + GRACE 뒤 부재면 NOT_FILLED."""
        iid = int(intent_row["intent_id"])
        row = self._row(iid)
        if IntentState(row["state"]) is not S.SUBMITTING:
            return IntentState(row["state"])
        if row["entry_sent_ms"] is None:
            raise ValueError("entry_sent_ms가 없는 의도는 결과 모름 절차 대상이 아니다")
        e1 = row["entry_client_id"] or make_client_id(row["signal_id"], IdPurpose.ENTRY)
        deadline = int(row["entry_deadline_ms"]) if row["entry_deadline_ms"] is not None else (
            int(row["entry_sent_ms"]) + self.cfg.recv_window_ms + 2 * self.cfg.max_clock_skew_ms)
        start = self.now_ms()
        i = 0
        last_err: ExchangeError | None = None
        fatal = (ErrorKind.IP_BANNED, ErrorKind.REGION_BLOCKED, ErrorKind.AUTH)
        while True:
            o: OrderInfo | None = None
            got = False                         # get_order가 답했는가(None = '없음'도 답)
            try:
                o = self._x(iid, "get_order", e1, client_id=e1, log_query=True)
                got = True
            except ExchangeError as exc:
                last_err = exc
                if exc.kind in fatal:
                    break                       # 계속 조회해도 소용없고 차단만 길어진다
            if got and o is not None and o.status in ORDER_FINAL_STATUSES:
                return self._entry_outcome(row, o, source="query")
            if o is None:
                # 주문 조회가 '없음'이든 **실패**든 포지션은 본다: 체결됐으면 곧바로 손절 단계로(F1 — 30초 무방비 방지)
                pos: PositionInfo | None = None
                try:
                    pos = self._x(iid, "position", log_query=True)
                except ExchangeError as exc:
                    last_err = exc
                    if exc.kind in fatal:
                        break
                if pos is not None and float(pos.qty) > 0:
                    return self._record_fill(row, qty=float(pos.qty), avg=float(pos.entry_price),
                                             order_id=None, source="position")
                if pos is not None and float(pos.qty) < 0:
                    hid = self._halt(HaltReason.POSITION_MISMATCH, intent_id=iid, detail={"position": pos})
                    return self._transition(row, S.HALTED, reason="short_position", fields={"halt_id": hid},
                                            expected=S.SUBMITTING)
                if got and pos is not None:
                    # '주문 없음 + 포지션 0'을 둘 다 확인했을 때만 도착 기한 판정
                    try:
                        server_now = int(self._x(iid, "server_time_ms"))
                    except ExchangeError:
                        server_now = self.now_ms() + self.clock_offset_ms
                    if server_now > deadline + UNKNOWN_GRACE_MS:
                        self._cancel_pre_stop_if_any(row)
                        st = self._transition(row, S.NOT_FILLED, reason="entry_not_found_after_deadline",
                                              expected=S.SUBMITTING)
                        self._notify(f"진입 미확인 → 접수 안 됨 확정: 신호 {row['signal_id']} — 포지션 없음",
                                     signal_id=row["signal_id"])
                        return st
                    last_err = None
            if self.now_ms() - start >= RESOLVE_LIMIT_MS:
                break
            self.sleep(RESOLVE_BACKOFF_MS[min(i, len(RESOLVE_BACKOFF_MS) - 1)])
            i += 1
        # 확정 불가 → HALTED + T0 (사람). 대조기가 계속 손절 존재를 본다.
        reason = halt_reason_for(last_err) if last_err is not None and last_err.halts else \
            HaltReason.OUTCOME_UNRESOLVED
        hid = self._halt(reason, intent_id=iid, detail={
            "why": "entry_outcome_unresolved", "last_error": None if last_err is None else last_err.kind.value},
            alert_text=f"[TESTNET] 킬 스위치 T0: 진입 결과 확정 불가(신호 {row['signal_id']}) — 거래소 웹에서 포지션·"
                       "주문을 확인하고 필요하면 수동 청산(RUNBOOK)")
        st = self._transition(row, S.HALTED, reason="entry_outcome_unresolved", fields={"halt_id": hid},
                              expected=S.SUBMITTING)
        # 결과는 모르지만 포지션이 보이면 손절 없이 두지 않는다(조회가 되면 손절 재등록, 안 되면 청산 — F1)
        return self.secure_halted(self._row(iid)) if st is S.HALTED else st

    # ------------------------------------------------------------------
    # 손절
    # ------------------------------------------------------------------
    def _stop_request(self, row: sqlite3.Row, stop: float) -> ConditionalRequest:
        return ConditionalRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.STOP_MARKET, trigger_price=stop,
                                  client_algo_id=make_client_id(row["signal_id"], IdPurpose.STOP),
                                  close_position=True, working_type=WorkingType.MARK_PRICE, price_protect=False)

    def _pre_arm_stop(self, row: sqlite3.Row, *, stop: float, mark: float, ref_price: float) -> None:
        """K1 선배치(포지션 0에서 closePosition 손절). 실패하면 취소 → REJECTED + T0 stop_not_verified."""
        iid = int(row["intent_id"])
        req = self._stop_request(row, stop)
        sl = req.client_algo_id
        ctx = self._fw_ctx(row, mark=mark, position_qty=0.0, planned_stop=stop, position_entry_price=ref_price,
                           pre_entry_stop=True)
        try:
            v = enforce_conditional(req, ctx)
        except FirewallRejected as fr:
            self._event(iid, "FIREWALL", client_id=sl, payload=fr.verdict.as_json())
            self._reject(row, "firewall", halt=HaltReason.FIREWALL, detail={"violations": list(fr.verdict.violations)})
        self._event(iid, "FIREWALL", client_id=sl, payload=v.as_json())
        err: str | None = None
        try:
            self._x(iid, "place_conditional", req, client_id=sl, post=True)
        except ExchangeError as exc:
            err = exc.kind.value
        found: ConditionalInfo | None = None
        try:
            found = self._x(iid, "get_conditional", sl, client_id=sl, log_query=True)
        except ExchangeError as exc:
            err = err or exc.kind.value
        mism = stop_mismatches(found, client_algo_id=sl, stop_price=stop)
        if mism:
            self.cancel_own_stop(row)
            self._reject(row, "pre_stop_not_verified", halt=HaltReason.STOP_NOT_VERIFIED,
                         detail={"mismatch": mism, "error": err})
        queue.update_fields(self.conn, iid, S.SUBMITTING, {
            "stop_client_id": sl, "stop_price": stop, "stop_placed_ms": self.now_ms(), "stop_attempts": 1,
        }, now_ms=self.now_ms())

    def _cancel_pre_stop_if_any(self, row: sqlite3.Row) -> None:
        cur = self._row(int(row["intent_id"]))
        if cur["stop_client_id"] is not None or self.cfg.stop_placement is StopPlacement.PRE_ENTRY:
            self.cancel_own_stop(cur)

    def _unprotected_start(self, row: sqlite3.Row) -> int:
        for k in ("entry_sent_ms", "entry_fill_ms"):
            if row[k] is not None:
                return int(row[k])
        return self.now_ms()

    def ensure_stop(self, intent_row: sqlite3.Row, *, restart: bool = False) -> IntentState:
        """손절 등록(없으면)·대조(§4.4). 실패·기한 초과면 flatten(+T0).

        restart=True(재시작 복구, §8·O-6): 새로 걸지 않는다. 대조를 통과한 손절이 있으면 STOP_VERIFIED(늦었으면 경보),
        없으면 청산 + T0 restart_unprotected.
        """
        iid = int(intent_row["intent_id"])
        row = self._row(iid)
        st = IntentState(row["state"])
        if st not in (S.ENTRY_FILLED, S.STOP_PLACED):
            return st
        sl = make_client_id(row["signal_id"], IdPurpose.STOP)
        avg = float(row["avg_fill_price"])
        stop = float(row["stop_price"]) if row["stop_price"] is not None else stop_for_fill(avg, float(row["atr20"]))
        self._set_guard(row)
        if self._guard is not None:
            self._guard.stop = stop
        t0 = self._unprotected_start(row)
        deadline = t0 + self.cfg.stop_deadline_ms

        if restart:
            return self._verify_stop(row, sl=sl, stop=stop, restart=True)

        placed = st is S.STOP_PLACED
        last_err: str | None = None
        attempts = int(row["stop_attempts"] or 0)
        while not placed and attempts < STOP_PLACE_ATTEMPTS:
            if self.now_ms() > deadline:
                return self.flatten(self._row(iid), reason=HaltReason.UNPROTECTED_TIMEOUT)
            # 재시도 전 조회: 이미 접수됐으면 다시 보내지 않는다
            try:
                existing = self._x(iid, "get_conditional", sl, client_id=sl, log_query=True)
            except ExchangeError as exc:
                existing = None
                last_err = exc.kind.value
                if attempts > 0:
                    # 조회도 안 되면 같은 ID 재전송은 -4116/중복 위험 → 다음 시도에서 다시 조회
                    attempts += 1
                    self.sleep(STOP_RETRY_SLEEP_MS)
                    continue
            if existing is not None and existing.status in CONDITIONAL_ACTIVE_STATUSES:
                placed = True
                break
            if existing is not None and existing.status in CONDITIONAL_FIRED_STATUSES:
                return self._closed_without_us(self._row(iid), sl_fired=True)
            try:
                mark = float(self._x(iid, "mark_price"))
                pos = self._x(iid, "position", log_query=True)
            except ExchangeError as exc:
                last_err = exc.kind.value
                attempts += 1
                self.sleep(STOP_RETRY_SLEEP_MS)
                continue
            if float(pos.qty) == 0.0:
                return self._closed_without_us(self._row(iid), sl_fired=False)
            if float(pos.qty) < 0:
                return self._halt_intent(self._row(iid), HaltReason.POSITION_MISMATCH, "short_position",
                                         detail={"position": pos})
            if stop >= mark:
                # 시장이 이미 손절가 아래(체결 직후 급락) → 즉시 청산, 시장 사건이라 T0 없음(O-7)
                return self.flatten(self._row(iid), reason=None, exit_reason=IntentExitReason.STOP_IMMEDIATE)
            req = self._stop_request(row, stop)
            ctx = self._fw_ctx(row, mark=mark, position_qty=float(pos.qty), planned_stop=stop,
                               position_entry_price=avg)
            try:
                v = enforce_conditional(req, ctx)
            except FirewallRejected as fr:
                self._event(iid, "FIREWALL", client_id=sl, payload=fr.verdict.as_json())
                return self.flatten(self._row(iid), reason=HaltReason.FIREWALL)
            self._event(iid, "FIREWALL", client_id=sl, payload=v.as_json())
            attempts += 1
            queue.update_fields(self.conn, iid, S.ENTRY_FILLED,
                                {"stop_client_id": sl, "stop_price": stop, "stop_attempts": attempts},
                                now_ms=self.now_ms())
            try:
                self._x(iid, "place_conditional", req, client_id=sl, post=True)
                placed = True
            except ExchangeError as exc:
                last_err = exc.kind.value
                if exc.kind is ErrorKind.WOULD_TRIGGER:
                    return self.flatten(self._row(iid), reason=None, exit_reason=IntentExitReason.STOP_IMMEDIATE)
                if exc.kind is ErrorKind.ALGO_ENDPOINT_REQUIRED:
                    return self.flatten(self._row(iid), reason=HaltReason.ALGO_ENDPOINT)
                if exc.kind in _NO_RETRY_KINDS:
                    return self.flatten(self._row(iid), reason=halt_reason_for(exc))
                # 결과 모름·그 밖 확정 거부 → 다음 시도(먼저 조회)
                self.sleep(STOP_RETRY_SLEEP_MS)
        if not placed:
            return self.flatten(self._row(iid), reason=HaltReason.STOP_NOT_VERIFIED,
                                detail={"why": "stop_attempts_exhausted", "last_error": last_err})
        row = self._row(iid)
        if IntentState(row["state"]) is S.ENTRY_FILLED:
            now = self.now_ms()
            self._transition(row, S.STOP_PLACED, reason="stop_placed",
                             fields={"stop_client_id": sl, "stop_price": stop, "stop_placed_ms": now},
                             expected=S.ENTRY_FILLED)
        return self._verify_stop(self._row(iid), sl=sl, stop=stop, restart=False)

    def _verify_stop(self, row: sqlite3.Row, *, sl: str, stop: float, restart: bool) -> IntentState:
        """손절 존재 대조(§4.1-12). 통과 → STOP_VERIFIED, 실패 → 청산 + T0."""
        iid = int(row["intent_id"])
        t0 = self._unprotected_start(row)
        deadline = t0 + self.cfg.stop_deadline_ms
        mism: list[str] = ["not_checked"]
        pos: PositionInfo | None = None
        polls = 1 if restart else VERIFY_POLLS
        for k in range(polls):
            try:
                listed = list(self._x(iid, "open_conditional_orders"))
                one = self._x(iid, "get_conditional", sl, client_id=sl, log_query=True)
                pos = self._x(iid, "position", log_query=True)
            except ExchangeError as exc:
                mism = [f"query:{exc.kind.value}"]
            else:
                in_list = next((c for c in listed if c.client_algo_id == sl), None)
                mism = stop_mismatches(in_list, client_algo_id=sl, stop_price=stop)
                if not mism:
                    mism = stop_mismatches(one, client_algo_id=sl, stop_price=stop)
                if float(pos.qty) == 0.0:
                    fired = one is not None and one.status in CONDITIONAL_FIRED_STATUSES
                    return self._closed_without_us(self._row(iid), sl_fired=fired)
                if float(pos.qty) < 0:
                    return self._halt_intent(self._row(iid), HaltReason.POSITION_MISMATCH, "short_position",
                                             detail={"position": pos})
                if not mism:
                    break
            if k + 1 < polls and self.now_ms() + VERIFY_POLL_SLEEP_MS <= deadline:
                self.sleep(VERIFY_POLL_SLEEP_MS)
            else:
                break
        if mism:
            reason = HaltReason.RESTART_UNPROTECTED if restart else HaltReason.STOP_NOT_VERIFIED
            return self.flatten(self._row(iid), reason=reason, detail={"stop_mismatch": mism})
        now = self.now_ms()
        unprotected = 0 if (row["stop_placed_ms"] is not None and row["entry_fill_ms"] is not None
                            and int(row["stop_placed_ms"]) <= int(row["entry_fill_ms"])) else max(0, now - t0)
        if not restart and now > deadline:
            return self.flatten(self._row(iid), reason=HaltReason.UNPROTECTED_TIMEOUT,
                                detail={"unprotected_ms": unprotected})
        st = self._transition(self._row(iid), S.STOP_VERIFIED, reason="stop_verified" + ("_restart" if restart else ""),
                              fields={"stop_client_id": sl, "stop_price": stop, "stop_verified_ms": now,
                                      "unprotected_ms": unprotected},
                              expected=(S.ENTRY_FILLED, S.STOP_PLACED))
        if st is not S.STOP_VERIFIED:
            return st
        row = self._row(iid)
        filled = float(row["filled_qty"])
        self._notify(f"진입 체결 {filled:g} BTC @ {float(row['avg_fill_price']):,.1f}, 보호 손절 {stop:,.1f} 확인"
                     f"(무방비 {unprotected} ms): 신호 {row['signal_id']}", signal_id=row["signal_id"])
        if restart and unprotected > self.cfg.stop_deadline_ms:
            self._notify(f"경고: 재시작 복구에서 손절 확인까지 {unprotected} ms(기준 {self.cfg.stop_deadline_ms} ms) — "
                         "이미 보호됨", signal_id=row["signal_id"], kind="alert")
        if pos is not None and abs(float(pos.qty) - filled) > QTY_STEP * 1.0001:
            # closePosition 손절은 수량과 무관하게 전체를 덮는다 → 청산하지 않고 T0 + 경보(§9)
            hid = self._halt(HaltReason.POSITION_MISMATCH, intent_id=iid,
                             detail={"position_qty": float(pos.qty), "filled_qty": filled})
            queue.update_fields(self.conn, iid, S.STOP_VERIFIED, {"halt_id": hid}, now_ms=self.now_ms())
        return st

    # ------------------------------------------------------------------
    # 청산
    # ------------------------------------------------------------------
    def _halt_intent(self, row: sqlite3.Row, reason: HaltReason, why: str, *, detail: dict | None = None,
                     alert_text: str | None = None, once: bool = False) -> IntentState:
        iid = int(row["intent_id"])
        if once:
            hid = self.halt_once(reason, intent_id=iid, detail={"why": why, **(detail or {})}, alert_text=alert_text)
        else:
            hid = self._halt(reason, intent_id=iid, detail={"why": why, **(detail or {})}, alert_text=alert_text)
        st = IntentState(row["state"])
        if st is S.HALTED or st in INTENT_TERMINAL:
            return st
        return self._transition(row, S.HALTED, reason=why, fields={"halt_id": hid})

    def _closed_without_us(self, row: sqlite3.Row, *, sl_fired: bool) -> IntentState:
        """보유 의도의 포지션이 이미 0. 손절 발동이면 CLOSED(stop), 아니면 CLOSED(external) + T0 position_vanished."""
        iid = int(row["intent_id"])
        st = IntentState(row["state"])
        if st is S.SUBMITTING or row["filled_qty"] is None:
            return st
        self.cancel_own_stop(row)
        now = self.now_ms()
        if sl_fired:
            new = self._transition(row, S.CLOSED, reason="stop_fired",
                                   fields={"exit_reason": IntentExitReason.STOP.value, "closed_ms": now,
                                           "exit_qty": float(row["filled_qty"])})
            self._notify(f"보호 손절 발동 → 포지션 0 (신호 {row['signal_id']})", signal_id=row["signal_id"])
            return new
        hid = self._halt(HaltReason.POSITION_VANISHED, intent_id=iid, detail={"state": st.value})
        if st is S.HALTED:
            return self._transition(row, S.FAILED_FLATTENED, reason="position_vanished",
                                    fields={"exit_reason": IntentExitReason.EXTERNAL.value, "closed_ms": now})
        return self._transition(row, S.CLOSED, reason="position_vanished",
                                fields={"exit_reason": IntentExitReason.EXTERNAL.value, "closed_ms": now,
                                        "halt_id": hid})

    def _reduce_loop(self, row: sqlite3.Row, *, purposes: tuple[IdPurpose, ...], attempts_field: str,
                     fw_purpose: OrderPurpose, per_call: bool = False) -> tuple[bool | None, list[OrderInfo], str | None]:
        """reduceOnly 시장가 매도로 포지션 0 만들기. (포지션 0 확인 여부 | None=숏, 체결된 우리 주문들, 마지막 오류).

        per_call=False(추세 청산 x1~x3): 의도 평생 len(purposes)번 — 손절이 남아 보호하므로 사람 판단(T0)으로 넘긴다.
        per_call=True(비상 청산 f1~f3): 한 번의 호출(주기)에서 최대 len(purposes)번. 시도 수는 누적 기록이지 평생 한도가
        아니다 — 다음 주기(대조·보호)에 번호를 순환해 다시 시도한다(F3c: 1초 안에 평생 한도를 다 써 손절 없는 포지션이
        영영 남던 문제). 끝난 시장가 주문의 clientOrderId 재사용은 '미체결 사이에서만 고유' 규칙상 허용된다고 본다(K15)."""
        iid = int(row["intent_id"])
        fills: list[OrderInfo] = []
        last_err: str | None = None
        used = int(row[attempts_field] or 0)
        sent = 0
        tries = 0
        while True:
            try:
                pos = self._x(iid, "position", log_query=True)
            except ExchangeError as exc:
                last_err = exc.kind.value
                tries += 1
                if tries >= len(purposes) + 1:
                    return False, fills, last_err
                self.sleep(CLOSE_POLL_SLEEP_MS)
                continue
            q = float(pos.qty)
            if q == 0.0:
                return True, fills, last_err
            if q < 0:
                return None, fills, "short_position"
            if (sent if per_call else used) >= len(purposes):
                return False, fills, last_err or "attempts_exhausted"
            try:
                mark = float(self._x(iid, "mark_price"))
            except ExchangeError:
                mark = None
            purpose = purposes[used % len(purposes)]
            cid = make_client_id(row["signal_id"], purpose)
            qty = floor_to_step(q, QTY_STEP)
            req = OrderRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.MARKET, qty=qty, client_id=cid,
                               reduce_only=True)
            try:
                v = enforce_order(req, fw_purpose, self._fw_ctx(row, mark=mark, position_qty=q))
            except FirewallRejected as fr:
                self._event(iid, "FIREWALL", client_id=cid, payload=fr.verdict.as_json())
                return False, fills, "firewall:" + ",".join(fr.verdict.violations)
            self._event(iid, "FIREWALL", client_id=cid, payload=v.as_json())
            used += 1
            sent += 1
            queue.update_fields(self.conn, iid, IntentState(self._row(iid)["state"]), {attempts_field: used},
                                now_ms=self.now_ms())
            try:
                info = self._x(iid, "place_order", req, client_id=cid, post=True)
                if float(info.executed_qty) > 0:
                    fills.append(info)
            except ExchangeError as exc:
                last_err = exc.kind.value
                if exc.outcome_unknown:
                    try:
                        found = self._x(iid, "get_order", cid, client_id=cid, log_query=True)
                        if found is not None and float(found.executed_qty) > 0:
                            fills.append(found)
                    except ExchangeError:
                        pass
            self.sleep(CLOSE_POLL_SLEEP_MS)

    @staticmethod
    def _avg_exit(fills: list[OrderInfo]) -> tuple[float | None, float | None]:
        q = sum(float(f.executed_qty) for f in fills)
        if q <= 0:
            return None, None
        return sum(float(f.executed_qty) * float(f.avg_price) for f in fills) / q, q

    def flatten(self, intent_row: sqlite3.Row, *, reason: HaltReason | None,
                exit_reason: IntentExitReason = IntentExitReason.FLATTEN,
                detail: dict | None = None) -> IntentState:
        """§4.5 비상 청산. reason이 있으면 T0. 청산 확인 불가면 보호 손절을 다시 걸고(rearm_stop) HALTED.

        이미 HALTED(풀리지 않은 T0)인 의도를 다시 청산할 때는 같은 사유·의도의 T0를 새로 만들지 않는다(F3a — 경보 폭주 방지)."""
        iid = int(intent_row["intent_id"])
        row = self._row(iid)
        st = IntentState(row["state"])
        if st in INTENT_TERMINAL:
            return st
        self._set_guard(row)
        again = st is S.HALTED
        halt = self.halt_once if again else self._halt
        flat, fills, err = self._reduce_loop(row, purposes=FLAT_PURPOSES, attempts_field="flatten_attempts",
                                             fw_purpose=OrderPurpose.FLATTEN, per_call=True)
        row = self._row(iid)
        if flat is True:
            self.cancel_own_stop(row)
            self._cancel_own_open_orders(row)
            fields: dict[str, Any] = {"exit_reason": exit_reason.value, "closed_ms": self.now_ms()}
            px, q = self._avg_exit(fills)
            if px is not None:
                fields.update(exit_price=px, exit_qty=q)
            if reason is not None:
                fields["halt_id"] = halt(reason, intent_id=iid, detail={
                    "action": "flattened", "exit_reason": exit_reason.value, **(detail or {})})
            new = self._transition(row, S.FAILED_FLATTENED, reason=(reason.value if reason else exit_reason.value),
                                   fields=fields)
            self._notify(f"비상 청산 완료({exit_reason.value}{', ' + reason.value if reason else ''}): 신호 "
                         f"{row['signal_id']} — 포지션 0" + (", 킬 스위치 T0" if reason else ""),
                         signal_id=row["signal_id"], kind="alert")
            return new
        if flat is None:
            return self._halt_intent(row, HaltReason.POSITION_MISMATCH, "short_position",
                                     detail={"cause": None if reason is None else reason.value}, once=again)
        # 청산 실패·확인 불가 → 손절 없는 포지션으로 두지 않는다: 보호 손절을 다시 건다(F3b·F3c) → HALTED + T0 + P1 경보
        protected = self.rearm_stop(row)
        if reason is not None:
            halt(reason, intent_id=iid, detail={"action": "flatten_attempted", **(detail or {})})
        return self._halt_intent(
            row, HaltReason.FLATTEN_FAILED, "flatten_failed", detail={"last_error": err, "stop_rearmed": protected},
            alert_text=f"[TESTNET] P1 킬 스위치 T0: 비상 청산 실패(신호 {row['signal_id']}, {err}) — "
                       + ("보호 손절은 다시 걸었다. " if protected else "보호 손절도 못 걸었다(대조가 계속 재시도). ")
                       + "거래소 웹에서 수동 청산하고 손절을 확인할 것(RUNBOOK)", once=True)

    # ------------------------------------------------------------------
    # 손절 없는 포지션 보호(재등록·DB 없는 비상 경로)
    # ------------------------------------------------------------------
    def _place_stop_raw(self, iid: int | None, signal_id: str, *, stop: float, mark: float | None, qty: float,
                        ref: float) -> bool:
        """보호 손절(sig-…-sl closePosition) 등록 + 조회 대조. DB 전이 없음(이벤트만, 실패해도 계속). 대조 통과면 True."""
        sl = make_client_id(signal_id, IdPurpose.STOP)
        req = ConditionalRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.STOP_MARKET, trigger_price=stop,
                                 client_algo_id=sl, close_position=True, working_type=WorkingType.MARK_PRICE,
                                 price_protect=False)
        ctx = FirewallContext(cfg=self.cfg, client_base_url=self.base_url, signal_id=signal_id, mark_price=mark,
                              position_qty=qty, planned_stop=stop, position_entry_price=ref)
        try:
            v = enforce_conditional(req, ctx)
        except FirewallRejected as fr:
            self._event(iid, "FIREWALL", client_id=sl, payload=fr.verdict.as_json())
            return False
        self._event(iid, "FIREWALL", client_id=sl, payload=v.as_json())
        try:
            self._x(iid, "place_conditional", req, client_id=sl, post=True)
        except ExchangeError as exc:
            if not (exc.outcome_unknown or exc.kind is ErrorKind.DUPLICATE_CLIENT_ID):
                return False                     # 확정 거부(-2021 즉시 발동 포함) → 호출자가 청산
        for k in range(VERIFY_POLLS):
            try:
                c = self._x(iid, "get_conditional", sl, client_id=sl, log_query=True)
            except ExchangeError:
                c = None
            if not stop_mismatches(c, client_algo_id=sl, stop_price=stop):
                return True
            if k + 1 < VERIFY_POLLS:
                self.sleep(VERIFY_POLL_SLEEP_MS)
        return False

    def _flatten_raw(self, iid: int | None, signal_id: str) -> bool:
        """DB 없는 비상 청산(reduceOnly 시장가, f 번호 순환). 포지션 0을 확인하면 True."""
        for _ in range(FLATTEN_ATTEMPTS):
            try:
                pos = self._x(iid, "position", log_query=True)
            except ExchangeError:
                self.sleep(CLOSE_POLL_SLEEP_MS)
                continue
            q = float(pos.qty)
            if q == 0.0:
                return True
            if q < 0:
                return False
            try:
                mark: float | None = float(self._x(iid, "mark_price"))
            except ExchangeError:
                mark = None
            cid = make_client_id(signal_id, FLAT_PURPOSES[self._raw_flat_n % len(FLAT_PURPOSES)])
            self._raw_flat_n += 1
            req = OrderRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.MARKET, qty=floor_to_step(q, QTY_STEP),
                               client_id=cid, reduce_only=True)
            ctx = FirewallContext(cfg=self.cfg, client_base_url=self.base_url, signal_id=signal_id, mark_price=mark,
                                  position_qty=q)
            try:
                v = enforce_order(req, OrderPurpose.FLATTEN, ctx)
            except FirewallRejected as fr:
                self._event(iid, "FIREWALL", client_id=cid, payload=fr.verdict.as_json())
                return False
            self._event(iid, "FIREWALL", client_id=cid, payload=v.as_json())
            try:
                self._x(iid, "place_order", req, client_id=cid, post=True)
            except ExchangeError:
                pass
            self.sleep(CLOSE_POLL_SLEEP_MS)
        try:
            return float(self._x(iid, "position", log_query=True).qty) == 0.0
        except ExchangeError:
            return False

    def _protective_stop_active(self, iid: int | None, signal_id: str, mark: float | None) -> bool:
        sl = make_client_id(signal_id, IdPurpose.STOP)
        try:
            c = self._x(iid, "get_conditional", sl, client_id=sl, log_query=True)
        except ExchangeError:
            return False
        return (c is not None and c.status in CONDITIONAL_ACTIVE_STATUSES and c.side is Side.SELL
                and c.type is OrderType.STOP_MARKET and c.close_position is True
                and (mark is None or float(c.trigger_price) < float(mark)))

    def rearm_stop(self, intent_row: sqlite3.Row, *, pos: PositionInfo | None = None) -> bool:
        """손절 없는 롱 포지션에 이 의도의 보호 손절을 (다시) 건다. 이미 살아 있는 우리 손절이 있으면 True.

        손절가 = 기록된 stop_price(마크 아래일 때) 또는 체결가(없으면 포지션 평균가) − 2×ATR20. 마크가 이미 그 아래면 False
        (호출자가 청산). 성공하면 stop_* 열을 기록한다(DB 실패는 무시 — 거래소가 보호 중)."""
        iid = int(intent_row["intent_id"])
        row = self._row(iid)
        sid = row["signal_id"]
        try:
            if pos is None:
                pos = self._x(iid, "position", log_query=True)
        except ExchangeError:
            return False
        q = float(pos.qty)
        if q <= 0:
            return q == 0.0
        try:
            mark: float | None = float(self._x(iid, "mark_price"))
        except ExchangeError:
            mark = None
        if self._protective_stop_active(iid, sid, mark):
            return True
        ref = float(row["avg_fill_price"]) if row["avg_fill_price"] is not None else float(pos.entry_price)
        if not (math.isfinite(ref) and ref > 0):
            return False
        stop = float(row["stop_price"]) if row["stop_price"] is not None else stop_for_fill(ref, float(row["atr20"]))
        if mark is not None and stop >= mark:
            return False
        ok = self._place_stop_raw(iid, sid, stop=stop, mark=mark, qty=q, ref=ref)
        if ok:
            self._event(iid, "NOTE", payload={"stop_rearmed": True, "stop": stop, "position_qty": q})
            try:
                queue.update_fields(self.conn, iid, IntentState(row["state"]), {
                    "stop_client_id": make_client_id(sid, IdPurpose.STOP), "stop_price": stop,
                    "stop_placed_ms": self.now_ms()}, now_ms=self.now_ms())
            except sqlite3.Error:
                pass
        return ok

    def secure_halted(self, intent_row: sqlite3.Row) -> IntentState:
        """HALTED 의도에 포지션이 있고 살아 있는 우리 손절이 없으면: 새 비상 청산 주기(f1~f3, O-6과 같은 방향), 청산이 안 되면
        flatten()이 보호 손절을 다시 건다. 손절이 살아 있으면 아무것도 하지 않는다(사람 판단 대기, §8).
        대조마다 불린다(시간 간격을 둔 재시도 — F3b·F3c). 이미 T0가 걸린 의도라 새 사유 T0는 만들지 않는다(F3a)."""
        iid = int(intent_row["intent_id"])
        row = self._row(iid)
        st = IntentState(row["state"])
        if st is not S.HALTED:
            return st
        self._set_guard(row)
        try:
            pos = self._x(iid, "position", log_query=True)
        except ExchangeError:
            return st
        q = float(pos.qty)
        if q == 0.0:
            return st
        if q < 0:
            self.halt_once(HaltReason.POSITION_MISMATCH, intent_id=iid, detail={"position_qty": q})
            return st
        try:
            mark: float | None = float(self._x(iid, "mark_price"))
        except ExchangeError:
            mark = None
        if self._protective_stop_active(iid, row["signal_id"], mark):
            return st
        return self.flatten(self._row(iid), reason=None, detail={"why": "halted_unprotected"})

    def handle_orphan_fill(self, intent_row: sqlite3.Row, *, avg: float | None = None, why: str) -> bool:
        """끝난 의도(NOT_FILLED 등)인데 그 신호의 진입이 거래소에서 체결돼 있다(늦게 보인 체결·두 번째 B — F5·F6).
        의도 상태는 바꾸지 않는다(종료 상태). T0(unknown_position) + 비상 청산, 청산이 안 되면 보호 손절. 포지션 0·보호면 True."""
        iid = int(intent_row["intent_id"])
        row = self._row(iid)
        sid = row["signal_id"]
        self.halt_once(HaltReason.UNKNOWN_POSITION, intent_id=iid, detail={"why": why})
        if self._flatten_raw(iid, sid):
            self.cancel_own_stop(row)
            self._notify(f"늦게 확인된 진입 체결(신호 {sid}, {why}) → 비상 청산 완료 — 포지션 0, 킬 스위치 T0",
                         signal_id=sid, kind="alert")
            return True
        try:
            pos = self._x(iid, "position", log_query=True)
            mark: float | None = float(self._x(iid, "mark_price"))
        except ExchangeError:
            return False
        q = float(pos.qty)
        if q <= 0:
            return q == 0.0
        if self._protective_stop_active(iid, sid, mark):
            return True
        ref = avg if avg is not None and avg > 0 else float(pos.entry_price)
        if not (math.isfinite(ref) and ref > 0):
            return False
        stop = stop_for_fill(ref, float(row["atr20"]))
        return stop < float(mark) and self._place_stop_raw(iid, sid, stop=stop, mark=mark, qty=q, ref=ref)

    def emergency_protect(self, why: str) -> str:
        """DB 없이(쓰기 잠김·예외) 메모리의 보호 대상(_guard)만으로 포지션을 보호한다(SEC-03·F4).
        포지션 0 → 'flat', 우리 손절이 살아 있음 → 'protected', 손절 등록 → 'stop_placed', 청산 → 'flattened'."""
        g = self._guard
        if g is None:
            return "no_guard"
        try:
            pos = self._x(g.intent_id, "position", log_query=True)
        except ExchangeError:
            return "position_unavailable"
        q = float(pos.qty)
        if q <= 0:
            return "flat" if q == 0 else "short"
        try:
            mark: float | None = float(self._x(g.intent_id, "mark_price"))
        except ExchangeError:
            mark = None
        if self._protective_stop_active(g.intent_id, g.signal_id, mark):
            return "protected"
        ref = g.avg if g.avg is not None else float(pos.entry_price)
        result = "failed"
        if math.isfinite(ref) and ref > 0:
            stop = g.stop if g.stop is not None else stop_for_fill(ref, g.atr20)
            if (mark is None or stop < mark) and self._place_stop_raw(g.intent_id, g.signal_id, stop=stop, mark=mark,
                                                                      qty=q, ref=ref):
                result = "stop_placed"
        if result == "failed" and self._flatten_raw(g.intent_id, g.signal_id):
            result = "flattened"
        log.warning("비상 보호(%s): %s", why, result)
        return result

    def verify_held_stop(self, intent_row: sqlite3.Row) -> IntentState:
        """STOP_VERIFIED 보유를 묶음 조회 없이 확인(대조 묶음 조회가 실패하는 동안 — F9·퍼징 seed 553).
        포지션 0 → 손절 발동/외부 청산 기록, 포지션 > 0인데 손절 없음·불일치 → 청산 + T0 stop_missing. 조회 실패면 그대로."""
        iid = int(intent_row["intent_id"])
        row = self._row(iid)
        st = IntentState(row["state"])
        if st is not S.STOP_VERIFIED:
            return st
        sl = make_client_id(row["signal_id"], IdPurpose.STOP)
        try:
            c = self._x(iid, "get_conditional", sl, client_id=sl, log_query=True)
            pos = self._x(iid, "position", log_query=True)
        except ExchangeError:
            return st
        q = float(pos.qty)
        if q == 0.0:
            return self._closed_without_us(row, sl_fired=c is not None and c.status in CONDITIONAL_FIRED_STATUSES)
        if q < 0:
            self.halt_once(HaltReason.POSITION_MISMATCH, intent_id=iid, detail={"position_qty": q})
            return st
        mism = stop_mismatches(c, client_algo_id=sl, stop_price=row["stop_price"])
        if mism:
            return self.flatten(row, reason=HaltReason.STOP_MISSING, detail={"stop_mismatch": mism,
                                                                              "via": "no_snapshot"})
        return st

    def quick_stop_check(self, intent_row: sqlite3.Row) -> bool:
        """STOP_VERIFIED 보유의 손절이 거래소에 살아 있는지 가볍게 조회(대조 주기 사이, F7). 이상하면 False(대조를 앞당긴다).
        조회 실패는 True(판단 보류 — 정규 대조가 본다)."""
        if self.now_ms() < self._rate_until_ms:
            return True                          # 429·418 대기 창: 보내지 않는다
        sl = make_client_id(intent_row["signal_id"], IdPurpose.STOP)
        try:
            c = self.ex.get_conditional(sl)      # 가벼운 조회(이벤트 기록 없음 — 2초마다라 기록이 넘친다)
        except ExchangeError as exc:
            self.note_exchange_error(exc)
            return True
        return c is not None and c.status in CONDITIONAL_ACTIVE_STATUSES

    def quick_unprotected_check(self, intent_row: sqlite3.Row) -> bool:
        """HALTED·EXITING 보유가 손절 없이 남았는지 가볍게 조회(대조 주기 사이, V-2). 손절 없음 **확인**이면 True.

        우리 손절이 살아 있거나 포지션이 0이면 False. 조회 실패·429/418 대기 창이면 False(판단 보류 — 정규 대조가 본다,
        대기 창 안에서는 보내지 않는다). 이벤트는 남기지 않는다(2초마다라 기록이 넘친다)."""
        if self.now_ms() < self._rate_until_ms:
            return False
        sl = make_client_id(intent_row["signal_id"], IdPurpose.STOP)
        try:
            c = self.ex.get_conditional(sl)
            if c is not None and c.status in CONDITIONAL_ACTIVE_STATUSES:
                return False
            q = float(self.ex.position().qty)
        except ExchangeError as exc:
            self.note_exchange_error(exc)
            return False
        return q > 0

    def run_trend_exit(self, intent_row: sqlite3.Row) -> IntentState:
        """§4.6 추세 청산(now ≥ exit_due_ms인 STOP_VERIFIED/EXITING)."""
        iid = int(intent_row["intent_id"])
        row = self._row(iid)
        st = IntentState(row["state"])
        now = self.now_ms()
        if st is S.STOP_VERIFIED:
            if row["exit_due_ms"] is None or now < int(row["exit_due_ms"]):
                return st
            st = self._transition(row, S.EXITING, reason="trend_exit_due", fields={"exit_sent_ms": now},
                                  expected=S.STOP_VERIFIED)
            if st is not S.EXITING:
                return st
        elif st is not S.EXITING:
            return st
        row = self._row(iid)
        self._set_guard(row)
        flat, fills, err = self._reduce_loop(row, purposes=EXIT_PURPOSES, attempts_field="exit_attempts",
                                             fw_purpose=OrderPurpose.EXIT)
        row = self._row(iid)
        if flat is True:
            if fills:
                self.cancel_own_stop(row)
                px, q = self._avg_exit(fills)
                new = self._transition(row, S.CLOSED, reason="trend_exit",
                                       fields={"exit_reason": IntentExitReason.TREND.value, "closed_ms": self.now_ms(),
                                               "exit_price": px, "exit_qty": q}, expected=S.EXITING)
                self._notify(f"추세 청산 완료 {q:g} BTC @ {px:,.1f}: 신호 {row['signal_id']}",
                             signal_id=row["signal_id"])
                return new
            # 우리 청산 체결 없이 0 → 손절 발동이 먼저였는지 확인(§4.6: -2022 경쟁)
            fired = False
            try:
                c = self._x(iid, "get_conditional", make_client_id(row["signal_id"], IdPurpose.STOP),
                            log_query=True)
                fired = c is not None and c.status in CONDITIONAL_FIRED_STATUSES
            except ExchangeError:
                fired = False
            if not fired and int(row["exit_attempts"] or 0) > 0:
                # 청산 주문의 결과를 알 수 없었다(응답 유실) → 우리 x 주문 조회로 한 번 더
                for p in EXIT_PURPOSES[: int(row["exit_attempts"])]:
                    cid = make_client_id(row["signal_id"], p)
                    try:
                        o = self._x(iid, "get_order", cid, client_id=cid, log_query=True)
                    except ExchangeError:
                        o = None
                    if o is not None and float(o.executed_qty) > 0:
                        fills.append(o)
                if fills:
                    self.cancel_own_stop(row)
                    px, q = self._avg_exit(fills)
                    return self._transition(row, S.CLOSED, reason="trend_exit",
                                            fields={"exit_reason": IntentExitReason.TREND.value,
                                                    "closed_ms": self.now_ms(), "exit_price": px, "exit_qty": q},
                                            expected=S.EXITING)
            return self._closed_without_us(row, sl_fired=fired)
        if flat is None:
            return self._halt_intent(row, HaltReason.POSITION_MISMATCH, "short_position")
        # 3회 실패: 손절은 남아 있으므로 EXITING 유지 + T0 + 경보. 손절까지 없으면 비상 청산.
        stop_ok: bool | None = None          # None = 조회 불가(모름) — 모르면 청산으로 올리지 않는다
        try:
            c = self._x(iid, "get_conditional", make_client_id(row["signal_id"], IdPurpose.STOP), log_query=True)
            stop_ok = not stop_mismatches(c, client_algo_id=make_client_id(row["signal_id"], IdPurpose.STOP),
                                          stop_price=row["stop_price"])
        except ExchangeError:
            stop_ok = None
        if stop_ok is False:
            return self.flatten(row, reason=HaltReason.STOP_MISSING, detail={"why": "trend_exit_failed", "error": err})
        self.halt_once(HaltReason.FLATTEN_FAILED, intent_id=iid, detail={"why": "trend_exit_failed", "error": err,
                                                                         "stop_ok": stop_ok})
        return IntentState(self._row(iid)["state"])

    # ------------------------------------------------------------------
    # 취소(대조기도 이것만 쓴다)
    # ------------------------------------------------------------------
    def cancel_own_stop(self, intent_row: sqlite3.Row) -> bool:
        """이 의도의 sl 취소. 없음(None)·이미 끝남(-2011)은 성공 취급(K14: 청산 뒤 항상 명시적으로 취소)."""
        iid = int(intent_row["intent_id"])
        sl = make_client_id(intent_row["signal_id"], IdPurpose.STOP)
        for _ in range(2):
            try:
                self._x(iid, "cancel_conditional", sl, client_id=sl, post=True)
                return True
            except ExchangeError as exc:
                if exc.kind in (ErrorKind.ORDER_NOT_FOUND, ErrorKind.CANCEL_REJECTED):
                    return True
        return False

    def _cancel_own_open_orders(self, row: sqlite3.Row) -> None:
        iid = int(row["intent_id"])
        try:
            oo = list(self._x(iid, "open_orders"))
        except ExchangeError:
            return
        for o in oo:
            p = parse_client_id(o.client_id)
            if p is not None and p.signal_id == row["signal_id"]:
                try:
                    self._x(iid, "cancel_order", o.client_id, client_id=o.client_id, post=True)
                except ExchangeError:
                    pass

    def cancel_foreign(self, client_id: str, *, conditional: bool, intent_id: int | None = None) -> bool:
        """대조기가 찾은 모르는 주문 취소(§9). 성공(또는 이미 없음)이면 True."""
        method = "cancel_conditional" if conditional else "cancel_order"
        try:
            self._x(intent_id, method, client_id, client_id=client_id, post=True)
            return True
        except ExchangeError as exc:
            return exc.kind in (ErrorKind.ORDER_NOT_FOUND, ErrorKind.CANCEL_REJECTED)


# ---------------------------------------------------------------------------
# 시작 거부 전 DB 없는 보호(V-1) — 설정·DB 문제로 B가 recover() 전에 멈춰야 할 때
# ---------------------------------------------------------------------------
RESCUE_DEADLINE_MS = 60_000        # 시작 거부 전 보호에 쓰는 시간 상한(그 뒤 종료 → compose 재시작이 다시 시도)
RESCUE_RETRY_SLEEP_MS = 1_000      # 조회 실패(네트워크 등) 뒤 다시 시도 전


def _is_our_protective_stop(c: ConditionalInfo, mark: float | None) -> bool:
    p = parse_client_id(c.client_algo_id)
    return (p is not None and p.purpose is IdPurpose.STOP and c.symbol == SYMBOL
            and c.status in CONDITIONAL_ACTIVE_STATUSES and c.side is Side.SELL
            and c.type is OrderType.STOP_MARKET and c.close_position is True
            and (mark is None or float(c.trigger_price) < float(mark)))


def protect_without_db(ex: ExchangeClient, cfg: OrdersConfig, clock: Clock, *, base_url: str,
                       sleep_ms: Callable[[int], None], deadline_ms: int = RESCUE_DEADLINE_MS,
                       new_signal_id: Callable[[], str] | None = None) -> str:
    """DB·설정 문제로 시작을 거부하기 **전에** 거래소 사실만으로 포지션을 보호한다(V-1, fail-closed).

    DB를 믿을 수 없으므로 신호·ATR(손절가 계산 재료)을 모른다 → 손절을 새로 만들지 않고, 우리 보호 손절(sig-…-sl,
    closePosition STOP_MARKET 매도, 마크 아래)이 살아 있으면 그대로 두고(사람이 DB를 고친 뒤 recover가 판단),
    없으면 reduceOnly 시장가로 전량 청산한다. 청산 ID는 이번 구조 전용 새 신호 ID의 f1~f3(재사용 없음, K15),
    모든 주문은 방화벽(FLATTEN) 통과. 429·418은 Retry-After 동안 보내지 않는다(기한을 넘기면 포기).
    결과: 'flat' · 'short'(아무것도 안 함 — 롱 전용 방화벽) · 'protected' · 'flattened' · 'unavailable' · 'failed'."""
    from bot.types import new_signal_id as _nsid

    gen = new_signal_id or _nsid

    def now() -> int:
        return int(clock.now_ns()) // NS_PER_MS

    start = now()
    rate_until = 0
    sid = gen()
    n = 0
    flattened_once = False
    last = "unavailable"

    def wait_err(exc: ExchangeError) -> bool:
        """오류 뒤 기다림. 기한 안에 다시 시도할 수 있으면 True."""
        nonlocal rate_until
        if exc.kind in (ErrorKind.RATE_LIMITED, ErrorKind.IP_BANNED):
            ra = exc.retry_after_s
            wait = (int(math.ceil(float(ra) * 1000)) + 50 if ra is not None and math.isfinite(float(ra)) and ra > 0
                    else RATE_LIMIT_DEFAULT_WAIT_MS if exc.kind is ErrorKind.RATE_LIMITED else IP_BAN_DEFAULT_WAIT_MS)
            rate_until = now() + wait
        elif exc.kind in (ErrorKind.AUTH, ErrorKind.REGION_BLOCKED):
            return False                           # 기다려도 안 된다
        else:
            wait = RESCUE_RETRY_SLEEP_MS
        if now() + wait - start > deadline_ms:
            return False
        sleep_ms(wait)
        return True

    while now() - start <= deadline_ms:
        if now() < rate_until:
            sleep_ms(rate_until - now())
        try:
            q = float(ex.position().qty)
        except ExchangeError as exc:
            if not wait_err(exc):
                break
            continue
        if q == 0.0:
            return "flattened" if flattened_once else "flat"
        if q < 0:
            return "short"
        try:
            mark: float | None = float(ex.mark_price())
        except ExchangeError:
            mark = None
        try:
            conds = list(ex.open_conditional_orders())
        except ExchangeError:
            conds = None                           # 손절 확인 불가 → 청산(fail-closed)
        if conds is not None and any(_is_our_protective_stop(c, mark) for c in conds):
            return "protected"
        if n and n % len(FLAT_PURPOSES) == 0:
            sid = gen()                            # f1~f3을 다 쓰면 새 구조 ID(clientOrderId 재사용 없음)
        cid = make_client_id(sid, FLAT_PURPOSES[n % len(FLAT_PURPOSES)])
        n += 1
        req = OrderRequest(symbol=SYMBOL, side=Side.SELL, type=OrderType.MARKET, qty=floor_to_step(q, QTY_STEP),
                           client_id=cid, reduce_only=True)
        ctx = FirewallContext(cfg=cfg, client_base_url=base_url, signal_id=sid, mark_price=mark, position_qty=q)
        try:
            enforce_order(req, OrderPurpose.FLATTEN, ctx)
        except FirewallRejected as fr:
            log.error("시작 거부 전 보호: 방화벽 거부 %s", list(fr.verdict.violations))
            return "failed"
        try:
            ex.place_order(req)
            flattened_once = True
        except ExchangeError as exc:
            if exc.outcome_unknown:
                flattened_once = True
            elif not wait_err(exc):
                last = "failed"
                break
            continue
        last = "failed"
        sleep_ms(CLOSE_POLL_SLEEP_MS)
    return last
