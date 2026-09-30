"""텔레그램: 카드 렌더링·버튼·콜백 검증·명령 — 텔레그램 담당 구현 (bot/DESIGN.md §2.3, §7.2, §9.6).

보안 규칙 (DESIGN §7.2)
- 롱 폴링만(인바운드 포트 0). 시작할 때 웹훅 설정을 확인(있으면 경고·감사)하고 deleteWebhook 후 폴링.
- 허용 사용자 ID 1개·허용 채팅 ID 1개(둘 다 int 비교, bool 거부, chat.type == 'private').
  아니면 **응답하지 않고**(answerCallbackQuery도 안 함) 감사 로그만.
- callback_data = types.make_callback_data / parse_callback_data ("v1:<A|C|X|P|D>:<16자 base32>")만 받는다.
  가격·수량은 callback_data에 없다. 모든 값은 DB에서 꺼낸다.
- 중복 클릭: db.record_button(callback_query_id 고유)으로 거르고, 상태 전이는 engine(→ db 원자적 UPDATE)만 한다.
- 모든 메시지는 평문(parse_mode 없음), 링크 미리보기 끔, protect_content 켬, 첫 줄 모드 머리표 [PAPER]/[REPLAY].
  Claude 텍스트는 sanitize_text(URL·마크업·제어 문자 제거, 길이 제한).
- 명령: /status /positions /pause /resume /help 만. 설정 변경 명령 없음. 나머지 문장은 무시(감사 로그).

콜백 검사 순서 (handle_callback)
  ① 형식 파싱(부작용 없는 순수 함수, 결과는 ②에서만 씀) ② 사용자 ID ③ 채팅 ID·private
     — ②③ 실패면 형식과 무관하게 무응답 + 감사(BUTTON_REJECTED, actor=TELEGRAM_UNKNOWN)
  ④ 형식 실패 → "알 수 없는 버튼" ⑤ 신호 존재 ⑥ 카드 메시지 일치 ⑦ 상태·만료·일시정지 사전 검사
  ⑧ 중복(db.record_button) ⑨ engine 원자적 전이 ⑩ 현재 상태로 카드 다시 그리기. 거부는 전부 감사.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

from backtest import config as C
from backtest import trend as TR
from bot import db
from bot.config import BotConfig, RedactingFilter, Secret
from bot.types import (
    Actor,
    AuditEvent,
    Button,
    CallbackAction,
    Clock,
    OutgoingMessage,
    SignalState,
    SystemClock,
    kst_str,
    make_callback_data,
    ns_to_ms,
    parse_callback_data,
)

log = logging.getLogger(__name__)

MAX_TEXT = 3500           # 텔레그램 4096자 한도보다 여유
MAX_CLAUDE_FIELD = 600    # Claude 필드 하나당 표시 길이
MAX_COUNTER_ITEMS = 5     # 반대 근거 표시 개수
MAX_ANSWER_TEXT = 190     # answerCallbackQuery 팝업(텔레그램 200자 한도)
TG_HARD_LIMIT = 4096

COMMANDS = ("status", "positions", "pause", "resume", "help")
ALLOWED_UPDATES = ("message", "callback_query")
POLLING_KWARGS: dict[str, Any] = {"allowed_updates": list(ALLOWED_UPDATES), "drop_pending_updates": True}

ACTION_LABEL = {
    CallbackAction.APPROVE: "승인", CallbackAction.CONFIRM: "확인", CallbackAction.CANCEL: "취소",
    CallbackAction.PASS: "패스", CallbackAction.DETAIL: "상세",
}
# 동작별로 버튼이 유효한 상태(사전 검사용. 최종 판정은 engine → db 원자적 전이).
_EXPECTED_STATES: dict[CallbackAction, frozenset[SignalState]] = {
    CallbackAction.APPROVE: frozenset({SignalState.CARD_SENT}),
    CallbackAction.CONFIRM: frozenset({SignalState.CONFIRM_PENDING}),
    CallbackAction.CANCEL: frozenset({SignalState.CONFIRM_PENDING}),
    CallbackAction.PASS: frozenset({SignalState.CARD_SENT, SignalState.CONFIRM_PENDING}),
}


@dataclass(frozen=True)
class CallbackContext:
    callback_query_id: str
    update_id: int | None
    from_user_id: int | None
    chat_id: int | None
    chat_type: str | None
    message_id: int | None
    data: object


@dataclass
class CallbackOutcome:
    answer_text: str | None = None                      # answerCallbackQuery 팝업(없으면 조용히)
    answer: bool = True                                 # 허용되지 않은 사용자·중복이면 False(아예 응답 안 함)
    edit: OutgoingMessage | None = None                 # 원래 메시지 교체
    send: list[OutgoingMessage] = field(default_factory=list)
    result: str = ""                                    # 테스트·로그용 요약 코드(사용자에게 보내지 않음)


# ---------------------------------------------------------------------------
# 텍스트 정리
# ---------------------------------------------------------------------------

_URL_RE = re.compile(
    r"(?:https?://|tg://|www\.|t\.me/|telegram\.me/)\S*"            # 명시적 URL·텔레그램 딥링크
    r"|\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/\S*)?",                  # 맨 도메인(evil.com/x) — 텔레그램이 자동 링크함
    re.IGNORECASE,
)
_MARKUP_CHARS = str.maketrans("", "", "<>*_`[]~|\\")
_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"</?[A-Za-z][^<>]{0,80}>")
LINK_REMOVED = "(링크 제거)"
NUMBER_MASKED = "(숫자)"
# 4자리 이상 숫자(구분자 , . 허용): Claude 글에 나온 가격은 가린다 — 화면의 가격은 코드가 계산한 값만(PV-14/22, AS-20)
_NUMBER_RE = re.compile(r"\d(?:[\d,.]*\d)?")
# @사용자명(평문이어도 텔레그램 앱이 누를 수 있는 멘션으로 만든다), #해시태그, 줄 첫머리·공백 뒤 /명령
_MENTION_RE = re.compile(r"@(?=[A-Za-z0-9_]{3,})")
_HASHTAG_RE = re.compile(r"#(?=\w)")
_BOT_COMMAND_RE = re.compile(r"(?:(?<=\s)|^)/(?=[A-Za-z])")
_PATTERN_REDACTOR = RedactingFilter()   # 비밀 모양 문자열(봇 토큰·sk-ant- 키·핑 UUID) 가림 — config와 같은 패턴


def _strip_controls(s: str) -> str:
    """제어 문자(Cc)·서식 문자(Cf: 양방향 제어·폭 없는 문자)·서로게이트·비공개 영역을 공백/삭제로 바꾼다."""
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat == "Cc":
            out.append(" ")
        elif cat in ("Cf", "Cs", "Co", "Cn"):
            continue
        else:
            out.append(ch)
    return "".join(out)


def _mask_long_number(m: re.Match) -> str:
    tok = m.group(0)
    return NUMBER_MASKED if sum(ch.isdigit() for ch in tok) >= 4 else tok


def sanitize_text(text: object, max_len: int = MAX_CLAUDE_FIELD) -> str:
    """Claude 글 표시용 정리(SECURITY PV-22). URL(http, https, www., t.me, tg://, 맨 도메인)·마크업 문자·제어 문자
    제거, @멘션·#해시태그·/명령 표식 제거(누를 수 있는 요소 없음), 4자리 이상 숫자 가림(가격은 코드 값만),
    공백 정리, 길이 제한(말줄임).

    parse_mode를 쓰지 않으므로 마크업은 원래 해석되지 않지만, 이중 방어로 지운다. None → ''.
    ID 같은 코드 값 표시에는 쓰지 않는다(_safe_token 사용).
    """
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    s = unicodedata.normalize("NFKC", s)          # 전각 문자로 만든 URL(ｈｔｔｐ：／／) 우회 차단
    s = _strip_controls(s)
    s = _PATTERN_REDACTOR.redact(s).replace("***", "(가림)")
    s = _TAG_RE.sub("", s)
    s = s.translate(_MARKUP_CHARS)
    s = _URL_RE.sub(LINK_REMOVED, s)
    s = _MENTION_RE.sub("", s)
    s = _HASHTAG_RE.sub("", s)
    s = _BOT_COMMAND_RE.sub("", s)
    s = _NUMBER_RE.sub(_mask_long_number, s)
    s = _WS_RE.sub(" ", s).strip()
    max_len = max(1, int(max_len))
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9_.:-]")


def _safe_token(v: object, max_len: int = 40) -> str:
    """코드가 정한 짧은 식별자(상태·사유·모델·프롬프트 버전) 표시용: 허용 문자만 남긴다."""
    if v is None:
        return ""
    return _SAFE_TOKEN_RE.sub("", str(v))[:max_len]


def _outbound(text: str) -> str:
    """전송 직전 마지막 방어선: 비밀 모양 문자열 가림 + 텔레그램 한도."""
    return _clip_message(_PATTERN_REDACTOR.redact(text if isinstance(text, str) else str(text)), TG_HARD_LIMIT)


def _clip_message(text: str, limit: int = MAX_TEXT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# 권한
# ---------------------------------------------------------------------------


def _strict_int(v: object) -> bool:
    return type(v) is int  # bool·float·str·int 하위형 거부


def is_authorized(cfg: BotConfig, from_user_id: object, chat_id: object, chat_type: object) -> bool:
    """from_user_id == allowed_user_id and chat_id == allowed_chat_id and chat_type == 'private' (int만, bool 거부)."""
    tg = cfg.telegram
    allowed_user, allowed_chat = tg.allowed_user_id, tg.allowed_chat_id
    if not (_strict_int(allowed_user) and _strict_int(allowed_chat) and allowed_user > 0 and allowed_chat > 0):
        return False  # 설정이 비었거나 이상하면 기본 거부
    if not (_strict_int(from_user_id) and _strict_int(chat_id)):
        return False
    if not (isinstance(chat_type, str) and str(chat_type) == "private"):
        return False
    return from_user_id == allowed_user and chat_id == allowed_chat


# ---------------------------------------------------------------------------
# 버튼·렌더링
# ---------------------------------------------------------------------------


def card_buttons(signal_id: str) -> tuple[tuple[Button, ...], ...]:
    """[승인] [패스] [상세]."""
    return ((Button("승인", make_callback_data(CallbackAction.APPROVE, signal_id)),
             Button("패스", make_callback_data(CallbackAction.PASS, signal_id)),
             Button("상세", make_callback_data(CallbackAction.DETAIL, signal_id))),)


def confirm_buttons(signal_id: str) -> tuple[tuple[Button, ...], ...]:
    """[확인] [취소] (60초 안에)."""
    return ((Button("확인", make_callback_data(CallbackAction.CONFIRM, signal_id)),
             Button("취소", make_callback_data(CallbackAction.CANCEL, signal_id))),)


def _fmt_price(x: object) -> str:
    try:
        return f"{float(x):,.1f}"
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(x: float) -> str:
    return f"{x:+.2f}%"


def _card_numbers(signal: sqlite3.Row, cfg: BotConfig) -> dict[str, float]:
    """카드에 쓰는 수치. 식은 backtest 함수를 그대로 호출(DESIGN §3.3). 진입 기준가 = 신호 종가(실제 체결은 확인 뒤 첫 1분봉 시가)."""
    tcfg = cfg.trend_config()
    side = int(signal["side"])
    close = float(signal["close"])
    atr = float(signal["atr20"])
    stop = C.round_price(close - side * tcfg.stop_atr_mult * atr)
    risk = float(C.risk_per_unit(close, stop, tcfg.entry_rate)) + tcfg.entry_slip_rate * close
    entry_level = float(signal["entry_level"])
    return {
        "close": close, "atr20": atr, "stop": stop, "stop_dist": abs(close - stop),
        "stop_pct": abs(close - stop) / close * 100.0, "risk": risk,
        "breakout_pct": (close / entry_level - 1.0) * 100.0 if entry_level else 0.0,
        "risk_budget": cfg.paper.equity_usdt * TR.RISK_R, "entry_level": entry_level,
        "exit_level": float(signal["exit_level"]),
    }


def _analysis_output(analysis: sqlite3.Row | None) -> dict[str, Any] | None:
    """analyses 행 → 검증된 출력 dict. ok가 아니거나 JSON이 깨졌으면 None."""
    if analysis is None:
        return None
    try:
        if not int(analysis["ok"]) or not analysis["output_json"]:
            return None
        out = json.loads(analysis["output_json"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return out if isinstance(out, dict) else None


def _analysis_status(analysis: sqlite3.Row | None) -> str:
    if analysis is None:
        return "없음"
    try:
        return _safe_token(analysis["status"], 20) or "알 수 없음"
    except (KeyError, IndexError):
        return "알 수 없음"


def _claude_lines(analysis: sqlite3.Row | None, *, field_len: int = MAX_CLAUDE_FIELD) -> list[str]:
    lines = ["— Claude(참고 의견, 관문 아님) —"]
    out = _analysis_output(analysis)
    if out is None:
        lines.append(f"Claude 분석 없음 (사유: {_analysis_status(analysis)})")
        return lines
    opinion = {"approve": "승인", "pass": "패스"}.get(out.get("opinion"), "없음")
    lines.append(f"요약: {sanitize_text(out.get('summary'), field_len) or '-'}")
    counters = out.get("counter_evidence")
    counters = counters if isinstance(counters, list) else []
    shown = [sanitize_text(c, field_len) for c in counters[:MAX_COUNTER_ITEMS]]
    shown = [c for c in shown if c]
    if shown:
        lines.append("반대 근거:")
        lines.extend(f" - {c}" for c in shown)
    else:
        lines.append("반대 근거: -")
    lines.append(f"무효화: {sanitize_text(out.get('invalidation'), field_len) or '-'}")
    lines.append(f"의견: {opinion} · 메모: {sanitize_text(out.get('confidence_note'), field_len) or '-'}")
    return lines


def _header(signal: sqlite3.Row, cfg: BotConfig) -> str:
    side = "롱" if int(signal["side"]) > 0 else "숏"
    return f"{cfg.mode_tag} 승인 요청 · {cfg.marketdata.symbol} 1D · {side} ({int(signal['subsystem_n'])}일 돌파)"


def _card_text(signal: sqlite3.Row, analysis: sqlite3.Row | None, cfg: BotConfig) -> str:
    n = int(signal["subsystem_n"])
    m = TR.exit_period(n)
    v = _card_numbers(signal, cfg)
    lines = [
        _header(signal, cfg),
        f"신호 일봉 {signal['signal_day']} 마감 · 판단 {kst_str(signal['decision_ms'])}",
        f"진입 기준가(종가) {_fmt_price(v['close'])} > {n}일 최고 {_fmt_price(v['entry_level'])} "
        f"({_fmt_pct(v['breakout_pct'])})",
        f"보호 손절 {_fmt_price(v['stop'])} (2×ATR20, ATR20 {_fmt_price(v['atr20'])})",
        f"손절 거리 {_fmt_price(v['stop_dist'])} ({v['stop_pct']:.2f}%)",
        f"위험 1R = {_fmt_price(v['risk'])} USDT/BTC (손절 거리+비용) · 한도 자본의 {TR.RISK_R * 100:.1f}% "
        f"({v['risk_budget']:,.1f} USDT)",
        f"추세 청산(자동): 종가 < {m}일 최저 (현재 {_fmt_price(v['exit_level'])})",
        "모의 체결: [확인] 뒤 첫 1분봉 시가 (테이커 0.05% + 슬리피지 0.02%)",
        f"승인 마감 {kst_str(signal['expires_ms'])} · [승인] 뒤 60초 안에 [확인]",
        "",
        *_claude_lines(analysis),
    ]
    return "\n".join(lines)


def render_card(signal: sqlite3.Row, analysis: sqlite3.Row | None, cfg: BotConfig) -> OutgoingMessage:
    """신호 카드(평문). 첫 줄 "[PAPER] 승인 요청 · BTCUSDT 1D · 롱 (N일 돌파)", 진입 기준가·손절·손절 거리 %·위험(R)·
    Claude 요약·반대 근거·무효화·의견 또는 'Claude 분석 없음'·만료 시각(KST). kind='card', signal_id 채움."""
    text = _card_text(signal, analysis, cfg)
    if len(text) > MAX_TEXT:  # Claude 필드를 줄여 다시
        body = _card_text(signal, None, cfg).rsplit("— Claude", 1)[0]
        text = body + "\n".join(_claude_lines(analysis, field_len=200))
    return OutgoingMessage(text=_clip_message(text), buttons=card_buttons(signal["signal_id"]),
                           signal_id=signal["signal_id"], kind="card")


def render_detail(signal: sqlite3.Row, analysis: sqlite3.Row | None, cfg: BotConfig) -> str:
    """[상세]: 상태·시각·지표 원값·Claude 메타(모델·프롬프트 버전·상태·지연). 비밀 없음."""
    v = _card_numbers(signal, cfg)
    n = int(signal["subsystem_n"])
    lines = [
        f"{cfg.mode_tag} 신호 상세 · {cfg.marketdata.symbol} 1D · {n}일 돌파 ({cfg.strategy_key})",
        f"신호 ID {signal['signal_id']}",
        f"상태 {signal['state']}" + (f" ({_safe_token(signal['state_reason'], 40)})" if signal["state_reason"] else ""),
        f"신호 일봉 마감 {kst_str(signal['signal_close_ms'])}",
        f"판단 {kst_str(signal['decision_ms'])} · 승인 마감 {kst_str(signal['expires_ms'])}",
        f"종가 {_fmt_price(v['close'])} · U{n} {_fmt_price(v['entry_level'])} · "
        f"D{TR.exit_period(n)} {_fmt_price(v['exit_level'])} · ATR20 {_fmt_price(v['atr20'])}",
        f"예상 손절(종가 기준) {_fmt_price(v['stop'])} · 1R {_fmt_price(v['risk'])}",
    ]
    if signal["confirm_requested_ms"] is not None:
        lines.append(f"[승인] {kst_str(signal['confirm_requested_ms'], '%H:%M:%S KST')}")
    if signal["approved_ms"] is not None:
        lat = signal["approval_latency_ms"]
        lat_txt = f" · 판단 후 {int(lat) // 60000}분 {int(lat) // 1000 % 60}초" if lat is not None else ""
        lines.append(f"[확인] {kst_str(signal['approved_ms'], '%H:%M:%S KST')}{lat_txt}")
    if analysis is not None:
        lines.append(f"Claude: 상태 {_analysis_status(analysis)} · 모델 {_safe_token(analysis['model'], 40)} · "
                     f"프롬프트 {_safe_token(analysis['prompt_version'], 40)}"
                     + (f" · {int(analysis['latency_ms']) / 1000:.1f}초" if analysis["latency_ms"] is not None else ""))
    lines.append("")
    lines.extend(_claude_lines(analysis))
    return _clip_message("\n".join(lines))


def _load_analysis(conn: sqlite3.Connection, signal: sqlite3.Row) -> sqlite3.Row | None:
    aid = signal["analysis_id"]
    if aid is None:
        return None
    return conn.execute("SELECT * FROM analyses WHERE analysis_id = ?", (int(aid),)).fetchone()


_STATE_FOOTER = {
    SignalState.APPROVED: "승인 확정 — 다음 1분봉 시가에 모의 체결 대기",
    SignalState.FILLED: "모의 체결됨 — 보호 손절·추세 청산 자동 감시 중",
    SignalState.CLOSED: "포지션 종료",
    SignalState.PASSED: "패스함 — 진입하지 않음",
    SignalState.EXPIRED: "승인 창 만료 — 진입하지 않음",
    SignalState.SKIPPED: "건너뜀 — 진입하지 않음",
    SignalState.NEW: "전송 대기",
}


def render_state_message(signal: sqlite3.Row, analysis: sqlite3.Row | None, cfg: BotConfig,
                         message_id: int | None, *, note: str | None = None) -> OutgoingMessage:
    """카드 메시지를 현재 상태에 맞게 다시 그린다(원래 메시지 교체용).

    CARD_SENT → 카드 + [승인][패스][상세], CONFIRM_PENDING → 확인 화면 + [확인][취소], 그 밖 → 버튼 없음 + 상태 문구.
    note가 있으면 상태 문구 대신(또는 앞에) 표시하고 버튼을 없앤다(예: 만료 확인됨).
    """
    sid = signal["signal_id"]
    base = _card_text(signal, analysis, cfg)
    state = SignalState(signal["state"])
    buttons: tuple[tuple[Button, ...], ...] = ()
    kind = "info"
    if note is not None:
        footer = note
    elif state == SignalState.CARD_SENT:
        footer, buttons, kind = "", card_buttons(sid), "card"
    elif state == SignalState.CONFIRM_PENDING:
        until = signal["confirm_expires_ms"]
        footer = (f">> 확인 필요: {kst_str(until, '%H:%M:%S KST')}까지 [확인]을 누르면 승인됩니다. "
                  "(60초 지나면 카드로 돌아감)")
        buttons, kind = confirm_buttons(sid), "confirm"
    else:
        footer = _STATE_FOOTER.get(state, state.value)
        if state == SignalState.APPROVED and signal["approved_ms"] is not None:
            footer += f" (확인 {kst_str(signal['approved_ms'], '%H:%M:%S KST')})"
        if state == SignalState.SKIPPED and signal["state_reason"]:
            footer += f" (사유: {_safe_token(signal['state_reason'], 40)})"
    text = base if not footer else f"{base}\n\n{footer}"
    if len(text) > MAX_TEXT:
        text = _clip_message(base, MAX_TEXT - len(footer) - 2) + "\n\n" + footer
    return OutgoingMessage(text=text, buttons=buttons, signal_id=sid, kind=kind, edit_message_id=message_id)


# ---------------------------------------------------------------------------
# 콜백 처리
# ---------------------------------------------------------------------------


def _reject(conn: sqlite3.Connection, now_ms: int, ctx: CallbackContext, reason: str, *,
            actor: Actor = Actor.TELEGRAM_USER, signal_id: str | None = None,
            extra: dict[str, Any] | None = None) -> None:
    """버튼 거부 감사 로그. callback_data 원문은 남기지 않는다(조작된 임의 문자열) — 길이와 파싱된 ID만."""
    payload: dict[str, Any] = {
        "reason": reason,
        "callback_query_id": _safe_token(ctx.callback_query_id, 64),
        "update_id": ctx.update_id if _strict_int(ctx.update_id) else None,
        "from_user_id": ctx.from_user_id if _strict_int(ctx.from_user_id) else repr(type(ctx.from_user_id).__name__),
        "chat_id": ctx.chat_id if _strict_int(ctx.chat_id) else repr(type(ctx.chat_id).__name__),
        "chat_type": _safe_token(ctx.chat_type, 20) if ctx.chat_type is not None else None,
        "message_id": ctx.message_id if _strict_int(ctx.message_id) else None,
        "data_len": len(ctx.data) if isinstance(ctx.data, (str, bytes)) else None,
    }
    if extra:
        payload.update(extra)
    db.audit(conn, ts_ms=now_ms, actor=actor, event=AuditEvent.BUTTON_REJECTED,
             entity_type="signal" if signal_id else None, entity_id=signal_id, payload=payload)


# ---------------------------------------------------------------------------
# 권한 없는 시도: 감사 행 묶기 + 운영 채팅 경고(속도 제한) — SEC-04(DT-06), SEC-09
# ---------------------------------------------------------------------------

UNAUTH_AUDIT_WINDOW_MS = 60_000          # 이 창 안에서
UNAUTH_AUDIT_MAX_PER_WINDOW = 20         # 보낸 사람별 첫 시도만, 창당 최대 이만큼 감사 행(나머지는 개수만)
UNAUTH_ALERT_INTERVAL_MS = 600_000       # 운영 채팅 경고는 10분에 한 번(그동안 개수를 모아 알림)


class UnauthorizedTracker:
    """권한 없는 업데이트 처리 정책(메모리, 엔진마다 하나). 상대에게는 절대 응답하지 않는다.

    - 감사: 창(60초)마다 보낸 사람별 첫 시도만 행을 남기고(창당 최대 20행), 나머지는 세어 두었다가
      다음 창이 시작될 때 'unauthorized_suppressed' 요약 한 행으로 남긴다(디스크·검토 소음 제한).
    - 경고: 운영(허용) 채팅으로 10분에 한 번, 그 사이 시도 수를 합쳐 알린다.
    """

    def __init__(self) -> None:
        self.window_start_ms: int | None = None
        self.window_senders: set[object] = set()
        self.window_rows = 0
        self.suppressed = 0
        self.last_alert_ms: int | None = None
        self.since_alert = 0
        self.pending_alerts: list[OutgoingMessage] = []   # 명령 경로용(응답 대신 운영 채팅으로)
        self.lock = threading.Lock()

    def record(self, conn: sqlite3.Connection, cfg: BotConfig, now_ms: int, sender: object, kind: str
               ) -> tuple[bool, OutgoingMessage | None]:
        """반환 (이 시도를 자세히 감사할지, 운영 채팅 경고 메시지 또는 None)."""
        now_ms = int(now_ms)
        with self.lock:
            if self.window_start_ms is None or now_ms - self.window_start_ms >= UNAUTH_AUDIT_WINDOW_MS \
                    or now_ms < self.window_start_ms:
                if self.suppressed:
                    db.audit(conn, ts_ms=now_ms, actor=Actor.TELEGRAM_UNKNOWN, event=AuditEvent.ALERT,
                             payload={"reason": "unauthorized_suppressed", "count": self.suppressed,
                                      "window_start_ms": self.window_start_ms})
                self.window_start_ms, self.window_senders, self.window_rows, self.suppressed = now_ms, set(), 0, 0
            key = sender if _strict_int(sender) else repr(type(sender).__name__)
            detailed = key not in self.window_senders and self.window_rows < UNAUTH_AUDIT_MAX_PER_WINDOW
            if detailed:
                self.window_senders.add(key)
                self.window_rows += 1
            else:
                self.suppressed += 1
            self.since_alert += 1
            alert = None
            if self.last_alert_ms is None or now_ms - self.last_alert_ms >= UNAUTH_ALERT_INTERVAL_MS \
                    or now_ms < self.last_alert_ms:
                alert = OutgoingMessage(
                    text=(f"{cfg.mode_tag} 경고: 허용되지 않은 사용자·채팅의 {kind} 시도 {self.since_alert}건"
                          f" (최근 {kst_str(now_ms, '%H:%M KST')}). 응답하지 않았고 감사 로그에 남겼다."
                          " 봇 사용자명이 알려졌을 수 있다 — 반복되면 RUNBOOK '토큰 교체' 참고."),
                    kind="alert")
                self.last_alert_ms = now_ms
                self.since_alert = 0
            return detailed, alert

    def take_alerts(self) -> list[OutgoingMessage]:
        with self.lock:
            out, self.pending_alerts = self.pending_alerts, []
        return out


def unauthorized_tracker(engine) -> UnauthorizedTracker:
    tr = getattr(engine, "unauthorized", None)
    if not isinstance(tr, UnauthorizedTracker):
        tr = UnauthorizedTracker()
        try:
            setattr(engine, "unauthorized", tr)
        except AttributeError:  # pragma: no cover — slots 등
            pass
    return tr


def _engine_call(engine, action: CallbackAction) -> Callable[..., bool]:
    return {
        CallbackAction.APPROVE: engine.request_confirm,
        CallbackAction.CONFIRM: engine.confirm,
        CallbackAction.CANCEL: engine.cancel_confirm,
        CallbackAction.PASS: engine.pass_signal,
    }[action]


def _call_with_press_time(fn: Callable[..., bool], sid: str, now_ms: int) -> bool:
    """버튼을 누른 시각(now_ms)으로 창을 판정하도록 넘긴다(OPS-4: 락 대기 시간이 60초 창을 잡아먹지 않게).
    엔진이 at_ms를 받지 않으면(시험용 가짜) 예전 방식으로 부른다."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # pragma: no cover
        params = {}
    if "at_ms" in params:
        return fn(sid, at_ms=int(now_ms))
    return fn(sid)


_SUCCESS_TEXT = {
    CallbackAction.APPROVE: "60초 안에 [확인]을 눌러야 승인됩니다.",
    CallbackAction.CONFIRM: "승인 확정. 다음 1분봉 시가에 모의 체결합니다.",
    CallbackAction.CANCEL: "취소했습니다. 승인 창 안에서 다시 [승인]할 수 있습니다.",
    CallbackAction.PASS: "패스했습니다.",
}


def handle_callback(engine, conn: sqlite3.Connection, cfg: BotConfig, ctx: CallbackContext,
                    now_ms: int) -> CallbackOutcome:
    """버튼 한 번 처리. 순서는 모듈 설명 참고. 권한 없는 클릭에는 절대 응답하지 않는다(answer=False)."""
    parsed = parse_callback_data(ctx.data)                       # ① 순수 파싱(부작용 없음)

    if not is_authorized(cfg, ctx.from_user_id, ctx.chat_id, ctx.chat_type):   # ②③
        detailed, alert = unauthorized_tracker(engine).record(conn, cfg, now_ms, ctx.from_user_id, "버튼")
        if detailed:
            _reject(conn, now_ms, ctx, "unauthorized", actor=Actor.TELEGRAM_UNKNOWN,
                    signal_id=parsed.signal_id if parsed else None, extra={"format_ok": parsed is not None})
        # 상대에게는 무응답(answer=False, edit 없음). 경고는 운영(허용) 채팅으로만 — 전송 계층은 허용 채팅 고정.
        return CallbackOutcome(answer=False, result="unauthorized", send=[alert] if alert is not None else [])

    if parsed is None:                                           # ④
        _reject(conn, now_ms, ctx, "bad_format")
        return CallbackOutcome(answer_text="알 수 없는 버튼입니다.", result="bad_format")

    sid, action = parsed.signal_id, parsed.action
    sig = db.get_signal(conn, sid)                               # ⑤
    if sig is None:
        _reject(conn, now_ms, ctx, "unknown_signal", extra={"signal_id": sid})
        return CallbackOutcome(answer_text="알 수 없는 신호입니다.", result="unknown_signal")

    # ⑥ 버튼이 달린 메시지가 그 신호의 카드인지(다른 메시지에 붙은 위조 버튼 차단). 카드 기록이 없으면 건너뜀.
    card_mid = sig["tg_message_id"]
    if card_mid is not None and ctx.message_id is not None and int(card_mid) != ctx.message_id:
        _reject(conn, now_ms, ctx, "message_mismatch", signal_id=sid, extra={"action": action.value})
        return CallbackOutcome(answer_text="이 메시지의 버튼이 아닙니다.", result="message_mismatch")

    analysis = _load_analysis(conn, sig)
    state = SignalState(sig["state"])
    latency = int(now_ms) - int(sig["decision_ms"])

    # ⑦ 사전 검사(최종 판정은 ⑨의 원자적 전이)
    if action == CallbackAction.DETAIL:
        pre = "DETAIL"
    elif state not in _EXPECTED_STATES[action]:
        pre = "STALE"
    elif int(now_ms) >= int(sig["expires_ms"]):
        pre = "EXPIRED"
    elif action in (CallbackAction.APPROVE, CallbackAction.CONFIRM) and db.is_paused(conn):
        pre = "PAUSED"
    else:
        pre = "ACCEPTED"

    # ⑧ 중복(같은 callback_query_id 재전송) — 첫 번째만 처리
    first = db.record_button(conn, signal_id=sid, action=action.value, callback_query_id=str(ctx.callback_query_id),
                             update_id=ctx.update_id, from_user_id=ctx.from_user_id, chat_id=ctx.chat_id,
                             message_id=ctx.message_id, clicked_ms=int(now_ms), result=pre, latency_ms=latency)
    if not first:
        _reject(conn, now_ms, ctx, "duplicate", signal_id=sid, extra={"action": action.value})
        return CallbackOutcome(answer=False, result="duplicate")

    if pre == "DETAIL":
        return CallbackOutcome(send=[OutgoingMessage(text=render_detail(sig, analysis, cfg), signal_id=sid,
                                                     kind="info")], result="detail")

    if pre != "ACCEPTED":
        _reject(conn, now_ms, ctx, pre.lower(), signal_id=sid,
                extra={"action": action.value, "state": state.value})
        if pre == "EXPIRED":
            edit = render_state_message(sig, analysis, cfg, ctx.message_id, note=_STATE_FOOTER[SignalState.EXPIRED])
            return CallbackOutcome(answer_text="승인 창(2시간)이 지나 만료된 신호입니다.", edit=edit, result="expired")
        if pre == "PAUSED":
            return CallbackOutcome(answer_text="일시정지 중이라 신규 진입을 받지 않습니다. (/resume)", result="paused")
        edit = render_state_message(sig, analysis, cfg, ctx.message_id)
        return CallbackOutcome(answer_text="이미 처리된 버튼입니다.", edit=edit, result="stale")

    # ⑨ 원자적 전이(engine → db UPDATE ... WHERE state IN 기대값)
    try:
        ok = bool(_call_with_press_time(_engine_call(engine, action), sid, now_ms))
    except Exception as exc:  # noqa: BLE001 — 엔진 오류가 봇 전체를 멈추지 않게. 메시지는 남기지 않음(비밀 유출 방지)
        log.error("engine 오류: %s (%s)", type(exc).__name__, action.value)
        _reject(conn, now_ms, ctx, "engine_error", signal_id=sid,
                extra={"action": action.value, "error_type": type(exc).__name__})
        return CallbackOutcome(answer_text="처리 중 오류가 났습니다. /status로 확인하세요.", result="engine_error")

    after = db.get_signal(conn, sid)
    after_state = SignalState(after["state"])
    edit = render_state_message(after, analysis, cfg, ctx.message_id)            # ⑩
    if not ok:
        _reject(conn, now_ms, ctx, "transition_failed", signal_id=sid,
                extra={"action": action.value, "state_before": state.value, "state_after": after_state.value})
        if action == CallbackAction.CONFIRM and after_state == SignalState.CARD_SENT:
            text = "확인 시간(60초)이 지났습니다. 다시 [승인]하세요."
        elif after_state == SignalState.EXPIRED:
            text = "만료된 신호입니다."
        elif after_state == SignalState.SKIPPED:
            text = "건너뛴 신호입니다(일시정지 등)."
        else:
            text = "이미 처리됐거나 만료된 신호입니다."
        return CallbackOutcome(answer_text=text, edit=edit, result="transition_failed")
    return CallbackOutcome(answer_text=_SUCCESS_TEXT[action], edit=edit, result="ok")


# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------

_COMMAND_RE = re.compile(r"/([A-Za-z_]{1,32})(?:@[A-Za-z0-9_]{1,64})?")

HELP_TEXT = (
    "명령 (모의 운영 · 설정 변경은 서버에서만)\n"
    "/status — 봇 상태·일시정지 여부·대기 신호\n"
    "/positions — 열린 모의 포지션\n"
    "/pause — 신규 진입 중지(보유 포지션 손절·청산 감시는 계속)\n"
    "/resume — 신규 진입 다시 받기\n"
    "/help — 이 도움말\n"
    "신호 카드: [승인] → 60초 안에 [확인]. [패스]는 진입 안 함. 승인 창은 판단 후 2시간."
)


def _tagged(cfg: BotConfig, text: str) -> str:
    text = text if isinstance(text, str) else str(text)
    if not text.startswith(cfg.mode_tag):
        text = f"{cfg.mode_tag} {text}"
    return _clip_message(text)


def handle_command(engine, conn: sqlite3.Connection, cfg: BotConfig, *, from_user_id: object, chat_id: object,
                   chat_type: object, text: str, now_ms: int) -> str | None:
    """/status /positions /pause /resume /help. 허용되지 않은 사용자면 None(응답 안 함).

    감사 로그에는 사용자가 보낸 원문을 남기지 않는다(실수로 붙여 넣은 비밀이 DB에 남지 않게): 명령 이름·길이만.
    """
    raw = text if isinstance(text, str) else ""
    stripped = raw.strip()
    m = _COMMAND_RE.fullmatch(stripped) if len(stripped) <= 100 else None
    cmd = m.group(1).lower() if m else None
    meta = {"text_len": len(raw), "is_command": stripped.startswith("/"),
            "command": cmd if cmd in COMMANDS else None}

    if not is_authorized(cfg, from_user_id, chat_id, chat_type):
        tracker = unauthorized_tracker(engine)
        detailed, alert = tracker.record(conn, cfg, now_ms, from_user_id, "메시지")
        if detailed:
            db.audit(conn, ts_ms=now_ms, actor=Actor.TELEGRAM_UNKNOWN, event=AuditEvent.COMMAND_REJECTED,
                     payload={"reason": "unauthorized",
                              "from_user_id": from_user_id if _strict_int(from_user_id) else None,
                              "chat_id": chat_id if _strict_int(chat_id) else None,
                              "chat_type": _safe_token(chat_type, 20) if chat_type is not None else None, **meta})
        if alert is not None:
            with tracker.lock:
                tracker.pending_alerts.append(alert)      # 상대에게 답하지 않고 운영 채팅으로(on_message가 보냄)
        return None

    if cmd not in COMMANDS:
        reason = "unknown_command" if stripped.startswith("/") else "not_a_command"
        db.audit(conn, ts_ms=now_ms, actor=Actor.TELEGRAM_USER, event=AuditEvent.COMMAND_REJECTED,
                 payload={"reason": reason, **meta})
        if stripped.startswith("/"):
            return _tagged(cfg, "지원하지 않는 명령입니다(인자 없는 명령만). /help")
        return None  # 자유 문장은 무시

    db.audit(conn, ts_ms=now_ms, actor=Actor.TELEGRAM_USER, event=AuditEvent.COMMAND, payload={"command": cmd})
    if cmd == "help":
        return _tagged(cfg, HELP_TEXT)
    if cmd == "status":
        return _tagged(cfg, engine.status_text())
    if cmd == "positions":
        return _tagged(cfg, engine.positions_text())
    if cmd == "pause":
        was_paused = db.is_paused(conn)
        skipped = engine.pause(Actor.TELEGRAM_USER.value)
        head = "이미 일시정지 상태입니다." if was_paused and not skipped else "일시정지: 신규 진입을 받지 않습니다."
        return _tagged(cfg, f"{head} 건너뛴 신호 {len(skipped)}건. 열린 포지션의 보호 손절·추세 청산은 계속 감시합니다.")
    # resume
    changed = engine.resume(Actor.TELEGRAM_USER.value)
    return _tagged(cfg, "재개: 다음 판단부터 신규 신호를 받습니다." if changed else "이미 동작 중입니다(일시정지 아님).")


# ---------------------------------------------------------------------------
# 전송 계층 (python-telegram-bot 22.x)
# ---------------------------------------------------------------------------


def _markup(buttons: tuple[tuple[Button, ...], ...]):
    if not buttons:
        return None
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([[InlineKeyboardButton(b.text, callback_data=b.callback_data) for b in row]
                                 for row in buttons])


class PtbTransport:
    """python-telegram-bot 22.x 기반 ChatTransport. 허용 채팅으로만 보낸다(chat_id 인자 없음).

    평문(parse_mode 없음)·링크 미리보기 끔·protect_content. 토큰은 Bot을 만드는 한 줄에서만 reveal한다.
    """

    def __init__(self, token: Secret | None, chat_id: int, *, bot: Any = None) -> None:
        if not (_strict_int(chat_id) and chat_id > 0):
            raise ValueError("chat_id는 양의 정수(개인 채팅)")
        if bot is None:
            if not isinstance(token, Secret):
                raise TypeError("token은 Secret")
            from telegram import Bot

            bot = Bot(token=token.reveal())
        self._bot = bot
        self._chat_id = chat_id

    @classmethod
    def from_bot(cls, bot: Any, chat_id: int) -> "PtbTransport":
        return cls(None, chat_id, bot=bot)

    def __repr__(self) -> str:
        return f"PtbTransport(chat_id=***{str(self._chat_id)[-3:]})"

    __str__ = __repr__

    @staticmethod
    def _link_opts():
        from telegram import LinkPreviewOptions

        return LinkPreviewOptions(is_disabled=True)

    async def send(self, text: str, buttons: tuple[tuple[Button, ...], ...] = ()) -> int:
        msg = await self._bot.send_message(chat_id=self._chat_id, text=_outbound(text),
                                           parse_mode=None, reply_markup=_markup(buttons),
                                           link_preview_options=self._link_opts(), protect_content=True)
        return int(msg.message_id)

    async def edit(self, message_id: int, text: str, buttons: tuple[tuple[Button, ...], ...] = ()) -> None:
        from telegram.error import BadRequest

        try:
            # reply_markup=None이면 기존 인라인 버튼이 사라진다(처리 완료·만료 표시).
            await self._bot.edit_message_text(text=_outbound(text), chat_id=self._chat_id,
                                              message_id=int(message_id), parse_mode=None,
                                              reply_markup=_markup(buttons),
                                              link_preview_options=self._link_opts())
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return
            raise

    async def answer_callback(self, callback_query_id: str, text: str | None = None) -> None:
        await self._bot.answer_callback_query(
            callback_query_id=str(callback_query_id),
            text=None if text is None else _clip_message(_outbound(text), MAX_ANSWER_TEXT))


async def apply_outcome(transport, ctx: CallbackContext, outcome: CallbackOutcome) -> None:
    """handle_callback 결과를 전송 계층에 반영: 응답(허용된 경우만) → 메시지 교체 → 새 메시지."""
    if outcome.answer:
        try:
            await transport.answer_callback(ctx.callback_query_id, outcome.answer_text)
        except Exception as exc:  # noqa: BLE001 — 응답 실패(오래된 쿼리 등)는 상태에 영향 없음
            log.warning("answer_callback 실패: %s", type(exc).__name__)
    if outcome.edit is not None and outcome.edit.edit_message_id is not None:
        await transport.edit(outcome.edit.edit_message_id, outcome.edit.text, outcome.edit.buttons)
    for msg in outcome.send:
        await transport.send(msg.text, msg.buttons)


async def _deliver_one(transport, msg: OutgoingMessage) -> int | None:
    if msg.edit_message_id is not None:
        await transport.edit(msg.edit_message_id, msg.text, msg.buttons)
        return None
    return await transport.send(msg.text, msg.buttons)


async def send_outgoing(transport, engine, messages: list[OutgoingMessage]) -> list[tuple[OutgoingMessage, bool]]:
    """engine이 돌려준 메시지를 보낸다. edit_message_id가 있으면 수정, 카드(kind='card')는 전송 성공 뒤에만
    engine.mark_card_sent(NEW→CARD_SENT). 전송 실패는 예외 대신 (메시지, False)로 돌려준다.

    재시도(OPS-3): 카드는 NEW로 남아 unsent_cards가 다시 만든다. 카드가 아닌 메시지(체결·청산·경고·만료·리포트)는
    실패하면 DB 보관함(outbox)에 넣고, 다음 호출 때 새 메시지보다 먼저(오래된 순) 다시 보낸다.
    엔진에 보관함 메서드가 없으면(시험용 가짜) 예전처럼 버린다."""
    results: list[tuple[OutgoingMessage, bool]] = []
    pending = getattr(engine, "outbox_pending", None)
    if callable(pending):
        for row in pending():
            text = row["text"]
            if row["edit_message_id"] is None:
                text = f"{text}\n(지연 전송 · 원래 {kst_str(row['created_ms'])})"
            msg = OutgoingMessage(text=text, signal_id=row["signal_id"], kind=row["kind"],
                                  edit_message_id=row["edit_message_id"])
            try:
                await _deliver_one(transport, msg)
            except Exception as exc:  # noqa: BLE001 — 아직 장애 중: 다음 호출에 다시
                log.warning("보관 메시지 재전송 실패: %s (kind=%s)", type(exc).__name__, msg.kind)
                engine.outbox_mark(int(row["outbox_id"]), sent=False)
                results.append((msg, False))
                break
            engine.outbox_mark(int(row["outbox_id"]), sent=True)
            results.append((msg, True))
    add = getattr(engine, "outbox_add", None)
    for msg in messages:
        try:
            mid = await _deliver_one(transport, msg)
            if msg.edit_message_id is None and msg.kind == "card" and msg.signal_id:
                engine.mark_card_sent(msg.signal_id, mid)
            results.append((msg, True))
        except Exception as exc:  # noqa: BLE001
            log.warning("텔레그램 전송 실패: %s (kind=%s)", type(exc).__name__, msg.kind)
            results.append((msg, False))
            if msg.kind != "card" and callable(add):
                try:
                    add(msg)
                except Exception as exc2:  # noqa: BLE001 — 보관 실패가 루프를 멈추지 않게
                    log.error("보관함 저장 실패: %s", type(exc2).__name__)
    return results


async def check_webhook(bot, conn: sqlite3.Connection, cfg: BotConfig, *, now_ms: int,
                        lock: Any = None) -> OutgoingMessage | None:
    """DT-05: 웹훅이 설정돼 있으면(토큰 탈취 뒤 setWebhook으로 업데이트 가로채기) 감사 ALERT + 삭제 + 운영 채팅 경고.
    정상(웹훅 없음)이면 None. 시작 때와 5분마다 부른다. 예외는 호출자가 처리."""
    info = await bot.get_webhook_info()
    if not getattr(info, "url", ""):
        return None
    log.warning("웹훅 설정 발견 — 삭제하고 롱 폴링 유지")

    def _audit():
        db.audit(conn, ts_ms=int(now_ms), actor=Actor.SYSTEM, event=AuditEvent.ALERT,
                 payload={"reason": "webhook_was_set"})
    if lock is not None:
        def run():
            with lock:
                _audit()
        await asyncio.to_thread(run)
    else:
        _audit()
    await bot.delete_webhook(drop_pending_updates=False)
    return OutgoingMessage(text=(f"{cfg.mode_tag} 경고: 텔레그램 웹훅이 설정돼 있었다(토큰 유출 의심). 삭제하고 롱 폴링을"
                                 " 유지한다. RUNBOOK '토큰 교체'를 따라 토큰을 바꾸라."), kind="alert")


def callback_context_from_update(update: Any) -> CallbackContext | None:
    """PTB Update → CallbackContext. callback_query가 없으면 None."""
    q = getattr(update, "callback_query", None)
    if q is None:
        return None
    msg = getattr(q, "message", None)
    chat = getattr(msg, "chat", None) if msg is not None else None
    user = getattr(q, "from_user", None)
    ctype = getattr(chat, "type", None) if chat is not None else None
    return CallbackContext(
        callback_query_id=str(q.id),
        update_id=getattr(update, "update_id", None),
        from_user_id=getattr(user, "id", None) if user is not None else None,
        chat_id=getattr(chat, "id", None) if chat is not None else None,
        chat_type=str(ctype) if ctype is not None else None,
        message_id=getattr(msg, "message_id", None) if msg is not None else None,
        data=getattr(q, "data", None),
    )


def build_application(token: Secret, engine, conn: sqlite3.Connection, cfg: BotConfig, *,
                      clock: Clock | None = None, db_lock: threading.Lock | None = None,
                      transport: Any = None):
    """PTB Application(롱 폴링) + CallbackQueryHandler + CommandHandler(5종) + 나머지 메시지 감사 처리.

    main은 `app.run_polling(**POLLING_KWARGS)`(allowed_updates=['message','callback_query'],
    drop_pending_updates=True)로 돌린다. post_init에서 웹훅 설정을 확인(있으면 경고·감사)하고 deleteWebhook.
    DB 작업은 db_lock을 잡고 스레드에서 실행한다(일일 사이클 스레드와 같은 연결을 공유하므로).
    transport는 테스트용 주입(없으면 app.bot 기반 PtbTransport).
    """
    from telegram import Update
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

    if not isinstance(token, Secret):
        raise TypeError("token은 Secret")
    clock = clock or SystemClock()
    lock = db_lock or threading.Lock()

    async def _post_init(application: Application) -> None:
        info = await application.bot.get_webhook_info()
        if getattr(info, "url", ""):
            log.warning("웹훅 설정 발견 — 삭제하고 롱 폴링으로 전환")
            await _locked(db.audit, conn, ts_ms=ns_to_ms(clock.now_ns()), actor=Actor.SYSTEM,
                          event=AuditEvent.ALERT, payload={"reason": "webhook_was_set"})
        await application.bot.delete_webhook(drop_pending_updates=True)

    app = Application.builder().token(token.reveal()).post_init(_post_init).build()
    tx = transport if transport is not None else PtbTransport.from_bot(app.bot, cfg.telegram.allowed_chat_id)

    async def _locked(fn, *args, **kwargs):
        def run():
            with lock:
                return fn(*args, **kwargs)
        return await asyncio.to_thread(run)

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ctx = callback_context_from_update(update)
        if ctx is None:
            return
        outcome = await _locked(handle_callback, engine, conn, cfg, ctx, ns_to_ms(clock.now_ns()))
        await apply_outcome(tx, ctx, outcome)

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        user = update.effective_user
        chat = update.effective_chat
        text = getattr(msg, "text", None) or ""
        reply = await _locked(handle_command, engine, conn, cfg,
                              from_user_id=getattr(user, "id", None), chat_id=getattr(chat, "id", None),
                              chat_type=str(chat.type) if chat is not None and chat.type is not None else None,
                              text=text, now_ms=ns_to_ms(clock.now_ns()))
        if reply:
            await tx.send(reply)
        for alert in unauthorized_tracker(engine).take_alerts():       # 권한 없는 시도 경고(운영 채팅)
            try:
                await tx.send(alert.text)
            except Exception as exc:  # noqa: BLE001
                log.warning("경고 전송 실패: %s", type(exc).__name__)

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        # 예외 메시지·스택에는 URL(토큰 포함 가능)이 섞일 수 있어 종류만 남긴다(RedactingFilter와 이중 방어).
        log.error("텔레그램 처리 오류: %s", type(context.error).__name__)

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(CommandHandler(list(COMMANDS), on_message))
    app.add_handler(MessageHandler(filters.ALL, on_message))      # 그 밖의 모든 메시지: 감사 후 무시
    app.add_error_handler(on_error)
    return app
