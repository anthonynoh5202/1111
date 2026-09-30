"""telegram_ui 시험 (DESIGN §10): 권한·위조·중복·만료·2단계 승인·명령·평문·토큰 비노출.

엔진은 이 파일의 FakeEngine(db 원자적 전이만 쓰는 최소 구현)으로 대신한다 — 텔레그램 계층만 시험한다.
전송은 conftest.FakeTransport(가짜) / 가짜 PTB Bot. 네트워크 없음.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from dataclasses import dataclass, field

import pytest

from bot import db
from bot import telegram_ui as tu
from bot.config import Secret, read_secret
from bot.tests.conftest import (
    ALLOWED_CHAT_ID,
    ALLOWED_USER_ID,
    OTHER_USER_ID,
    T_MS,
    FakeTransport,
    insert_test_signal,
    make_config,
    ok_analysis,
    run_async,
)
from bot.types import (
    AnalystResult,
    CallbackAction,
    SignalState,
    make_callback_data,
)

TOKEN = "123456:TEST-dummy-token-not-real"
S = SignalState


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


@dataclass
class FakeEngine:
    """engine의 버튼·명령 API를 db 원자적 전이로 흉내 낸다(DESIGN §4 가드 그대로)."""

    conn: object
    now: list = field(default_factory=lambda: [T_MS])
    calls: list = field(default_factory=list)
    raise_on: str | None = None

    def _now(self) -> int:
        return self.now[0]

    def request_confirm(self, sid: str) -> bool:
        self.calls.append(("A", sid))
        if self.raise_on == "A":
            raise RuntimeError("boom https://api.telegram.org/bot" + TOKEN)
        sig = db.get_signal(self.conn, sid)
        if self._now() >= sig["expires_ms"] or db.is_paused(self.conn):
            return False
        return db.transition_signal(self.conn, sid, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=self._now(),
                                    actor="TELEGRAM_USER",
                                    fields={"confirm_requested_ms": self._now(),
                                            "confirm_expires_ms": self._now() + 60_000})

    def confirm(self, sid: str) -> bool:
        self.calls.append(("C", sid))
        sig = db.get_signal(self.conn, sid)
        if sig["state"] == S.CONFIRM_PENDING.value and self._now() > sig["confirm_expires_ms"]:
            db.transition_signal(self.conn, sid, S.CONFIRM_PENDING, S.CARD_SENT, now_ms=self._now(),
                                 actor="ENGINE", reason="confirm_timeout")
            return False
        if self._now() >= sig["expires_ms"] or db.is_paused(self.conn):
            return False
        return db.transition_signal(self.conn, sid, S.CONFIRM_PENDING, S.APPROVED, now_ms=self._now(),
                                    actor="TELEGRAM_USER",
                                    fields={"approved_ms": self._now(),
                                            "approval_latency_ms": self._now() - sig["decision_ms"]})

    def cancel_confirm(self, sid: str) -> bool:
        self.calls.append(("X", sid))
        return db.transition_signal(self.conn, sid, S.CONFIRM_PENDING, S.CARD_SENT, now_ms=self._now(),
                                    actor="TELEGRAM_USER", reason="cancel")

    def pass_signal(self, sid: str) -> bool:
        self.calls.append(("P", sid))
        return db.transition_signal(self.conn, sid, [S.CARD_SENT, S.CONFIRM_PENDING], S.PASSED,
                                    now_ms=self._now(), actor="TELEGRAM_USER")

    def mark_card_sent(self, sid: str, message_id: int) -> bool:
        self.calls.append(("sent", sid, message_id))
        return db.transition_signal(self.conn, sid, S.NEW, S.CARD_SENT, now_ms=self._now(), actor="ENGINE",
                                    fields={"card_sent_ms": self._now(), "tg_message_id": message_id})

    def pause(self, actor: str) -> list[str]:
        db.set_paused(self.conn, True, now_ms=self._now(), actor=actor)
        return []

    def resume(self, actor: str) -> bool:
        return db.set_paused(self.conn, False, now_ms=self._now(), actor=actor)

    def status_text(self) -> str:
        return "상태: 정상"

    def positions_text(self) -> str:
        return "열린 포지션 없음"


@pytest.fixture
def cfg(secret_dir):
    return make_config(secret_dir)


@pytest.fixture
def engine(conn):
    return FakeEngine(conn)


MID = 5001


def sent_signal(conn, engine, *, analysis: AnalystResult | None = None, **kw) -> str:
    sid = insert_test_signal(conn, **kw)
    if analysis is not None:
        aid = db.insert_analysis(conn, analysis, signal_day="2024-03-01", now_ms=T_MS)
        db.transition_signal(conn, sid, S.NEW, S.CARD_SENT, now_ms=T_MS, actor="ENGINE",
                             fields={"card_sent_ms": T_MS, "tg_message_id": MID, "analysis_id": aid})
    else:
        assert engine.mark_card_sent(sid, MID)
    return sid


_qid = [0]


def ctx_for(action, sid, *, user=ALLOWED_USER_ID, chat=ALLOWED_CHAT_ID, chat_type="private", mid=MID,
            data=..., qid=None) -> tu.CallbackContext:
    _qid[0] += 1
    if data is ...:
        data = make_callback_data(action, sid)
    return tu.CallbackContext(callback_query_id=qid or f"q{_qid[0]}", update_id=_qid[0], from_user_id=user,
                              chat_id=chat, chat_type=chat_type, message_id=mid, data=data)


def audits(conn, event=None):
    q = "SELECT * FROM audit_log" + (" WHERE event_type = ?" if event else "") + " ORDER BY seq"
    return conn.execute(q, (event,) if event else ()).fetchall()


def reasons(conn):
    return [json.loads(r["payload_json"])["reason"] for r in audits(conn, "BUTTON_REJECTED")]


def state(conn, sid):
    return db.get_signal(conn, sid)["state"]


def all_buttons(buttons):
    return [b for row in buttons for b in row]


# ---------------------------------------------------------------------------
# sanitize_text · is_authorized
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "see https://evil.example/x now", "http://a.b", "www.evil.com", "t.me/joinchat/abc", "tg://resolve?domain=x",
    "visit evil.com/path", "ｈｔｔｐｓ：／／evil.com", "EVIL.COM",
])
def test_sanitize_removes_urls(raw):
    out = tu.sanitize_text(raw)
    assert "evil" not in out.lower() and "://" not in out and "t.me" not in out and "www." not in out
    assert tu.LINK_REMOVED in out


def test_sanitize_markup_controls_whitespace_length():
    s = tu.sanitize_text("<b>굵게</b> *별* _밑줄_ `코드` [링크](x)\n\t둘째​줄‮거꾸로\x00끝")
    for ch in "<>*_`[]​‮\x00\n\t":
        assert ch not in s
    assert "굵게" in s and "둘째줄거꾸로 끝" in s
    long = tu.sanitize_text("가" * 1000)
    assert len(long) == tu.MAX_CLAUDE_FIELD and long.endswith("…")
    assert tu.sanitize_text(None) == "" and tu.sanitize_text(12.5) == "12.5"
    # SEC-02(PV-22): 4자리 이상 숫자는 가린다(화면의 가격은 코드 값만). 3자리 이하·백분율은 그대로.
    assert tu.sanitize_text("0.5% 하락, ATR 1,850.0 e.g. 가격") == "0.5% 하락, ATR (숫자) e.g. 가격"
    assert tu.sanitize_text("12.5% 와 250") == "12.5% 와 250"


def test_is_authorized(cfg):
    assert tu.is_authorized(cfg, ALLOWED_USER_ID, ALLOWED_CHAT_ID, "private")
    bad = [
        (OTHER_USER_ID, ALLOWED_CHAT_ID, "private"),
        (ALLOWED_USER_ID, OTHER_USER_ID, "private"),
        (ALLOWED_USER_ID, ALLOWED_CHAT_ID, "group"),
        (ALLOWED_USER_ID, ALLOWED_CHAT_ID, "supergroup"),
        (str(ALLOWED_USER_ID), ALLOWED_CHAT_ID, "private"),
        (ALLOWED_USER_ID, str(ALLOWED_CHAT_ID), "private"),
        (float(ALLOWED_USER_ID), ALLOWED_CHAT_ID, "private"),
        (None, ALLOWED_CHAT_ID, "private"),
        (ALLOWED_USER_ID, None, None),
        (True, ALLOWED_CHAT_ID, "private"),
    ]
    for args in bad:
        assert not tu.is_authorized(cfg, *args), args


def test_is_authorized_bool_ids_never_match():
    c = make_config(None, **{"telegram.allowed_user_id": 1, "telegram.allowed_chat_id": 1})
    assert tu.is_authorized(c, 1, 1, "private")
    assert not tu.is_authorized(c, True, True, "private")
    assert not tu.is_authorized(c, True, 1, "private")


# ---------------------------------------------------------------------------
# 렌더링
# ---------------------------------------------------------------------------


def test_card_render_with_analysis(conn, engine, cfg):
    sid = sent_signal(conn, engine, analysis=ok_analysis(summary="돌파 확인 https://x.io 참고",
                                                          counter_evidence=("거래량 약함", "<b>과열</b>")))
    sig = db.get_signal(conn, sid)
    an = tu._load_analysis(conn, sig)
    msg = tu.render_card(sig, an, cfg)
    lines = msg.text.split("\n")
    assert lines[0] == "[PAPER] 승인 요청 · BTCUSDT 1D · 롱 (20일 돌파)"
    assert msg.kind == "card" and msg.signal_id == sid
    t = msg.text
    # close 50,000, atr 1,500 → 손절 47,000 (2×ATR), 거리 6.00%
    assert "진입 기준가(종가) 50,000.0" in t and "보호 손절 47,000.0" in t and "(6.00%)" in t
    assert "1R = " in t and "USDT/BTC" in t
    assert "승인 마감 2024-03-02 11:01 KST" in t
    assert "요약: 돌파 확인" in t and "x.io" not in t and tu.LINK_REMOVED in t
    assert " - 거래량 약함" in t and " - 과열" in t and "<b>" not in t
    assert "의견: 승인" in t and "무효화:" in t
    assert [b.text for b in all_buttons(msg.buttons)] == ["승인", "패스", "상세"]
    assert [b.callback_data for b in all_buttons(msg.buttons)] == [
        f"v1:A:{sid}", f"v1:P:{sid}", f"v1:D:{sid}"]
    assert len(t) <= tu.MAX_TEXT


def test_card_without_analysis_and_failed_analysis(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    sig = db.get_signal(conn, sid)
    assert "Claude 분석 없음 (사유: 없음)" in tu.render_card(sig, None, cfg).text
    failed = AnalystResult(ok=False, status="timeout", prompt_version="analyst_v1", model="claude-opus-5-5",
                           input_json="{}", error="timeout")
    aid = db.insert_analysis(conn, failed, signal_day="2024-03-01", now_ms=T_MS)
    an = conn.execute("SELECT * FROM analyses WHERE analysis_id=?", (aid,)).fetchone()
    t = tu.render_card(sig, an, cfg).text
    assert "Claude 분석 없음 (사유: timeout)" in t and "요약:" not in t


def test_card_long_claude_fields_capped(conn, engine, cfg):
    sid = sent_signal(conn, engine, analysis=ok_analysis(summary="가" * 5000,
                                                          counter_evidence=tuple("나" * 3000 for _ in range(9))))
    sig = db.get_signal(conn, sid)
    msg = tu.render_card(sig, tu._load_analysis(conn, sig), cfg)
    assert len(msg.text) <= tu.MAX_TEXT
    assert msg.text.startswith("[PAPER] 승인 요청")


def test_mode_tag_replay(replay_conn, secret_dir):
    from bot.types import Mode
    rcfg = make_config(secret_dir, mode="replay")
    sid = insert_test_signal(replay_conn, mode=Mode.REPLAY)
    sig = db.get_signal(replay_conn, sid)
    assert tu.render_card(sig, None, rcfg).text.startswith("[REPLAY] 승인 요청 · BTCUSDT 1D · 롱 (20일 돌파)")
    assert tu.render_detail(sig, None, rcfg).startswith("[REPLAY]")


def test_detail_render(conn, engine, cfg):
    sid = sent_signal(conn, engine, analysis=ok_analysis(), n=55)
    sig = db.get_signal(conn, sid)
    d = tu.render_detail(sig, tu._load_analysis(conn, sig), cfg)
    assert d.startswith("[PAPER] 신호 상세") and sid in d and "U55" in d and "D28" in d
    assert "claude-opus-5-5" in d and "analyst_v1" in d


# ---------------------------------------------------------------------------
# 콜백: 권한·형식
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kw", [
    dict(user=OTHER_USER_ID), dict(chat=OTHER_USER_ID), dict(chat_type="group"), dict(chat_type="channel"),
    dict(user=True), dict(user=str(ALLOWED_USER_ID)), dict(chat=None, chat_type=None), dict(user=None),
])
def test_unauthorized_no_answer_and_audited(conn, engine, cfg, kw):
    sid = sent_signal(conn, engine)
    before = audits(conn)
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid, **kw), T_MS + 1000)
    # 상대에게는 무응답. out.send에는 운영(허용) 채팅으로 가는 경고만 있을 수 있다(SEC-04, DT-06).
    assert out.answer is False and out.edit is None and out.answer_text is None
    assert all(m.kind == "alert" and not m.buttons and m.edit_message_id is None for m in out.send)
    assert state(conn, sid) == "CARD_SENT" and engine.calls == [("sent", sid, MID)]
    new = audits(conn)[len(before):]
    assert len(new) == 1 and new[0]["event_type"] == "BUTTON_REJECTED" and new[0]["actor"] == "TELEGRAM_UNKNOWN"
    assert json.loads(new[0]["payload_json"])["reason"] == "unauthorized"
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    ft = FakeTransport()
    run_async(tu.apply_outcome(ft, ctx_for(CallbackAction.APPROVE, sid, **kw), out))
    assert ft.answers == [] and ft.edits == []
    assert all(m.text.startswith("[PAPER] 경고") and not m.buttons for m in ft.sent)   # 허용 채팅 고정 전송 계층


def test_unauthorized_bad_format_still_silent(conn, engine, cfg):
    out = tu.handle_callback(engine, conn, cfg, ctx_for(None, None, user=OTHER_USER_ID, data="garbage"), T_MS)
    assert out.answer is False
    p = json.loads(audits(conn, "BUTTON_REJECTED")[-1]["payload_json"])
    assert p["reason"] == "unauthorized" and p["format_ok"] is False and "garbage" not in json.dumps(p)


@pytest.mark.parametrize("data", [
    None, 123, b"v1:A:AAAAAAAAAAAAAAAA", "", "v2:A:AAAAAAAAAAAAAAAA", "v1:Z:AAAAAAAAAAAAAAAA",
    "v1:A:aaaaaaaaaaaaaaaa", "v1:A:AAAAAAAAAAAAAAA", "v1:A:AAAAAAAAAAAAAAAA\n", "v1:A:AAAAAAAAAAAAAAAA:99999",
    "v1:A:AAAAAAAAAAAAAAAA;price=1", "x" * 200,
])
def test_forged_callback_data(conn, engine, cfg, data):
    sent_signal(conn, engine)
    out = tu.handle_callback(engine, conn, cfg, ctx_for(None, None, data=data), T_MS)
    assert out.answer is True and out.answer_text == "알 수 없는 버튼입니다." and out.edit is None
    assert reasons(conn)[-1] == "bad_format"
    assert engine.calls[1:] == []


def test_unknown_signal(conn, engine, cfg):
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, "ABCDEFGHIJKLMNOP"), T_MS)
    assert out.answer_text == "알 수 없는 신호입니다." and reasons(conn) == ["unknown_signal"]


def test_message_mismatch_rejected(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid, mid=MID + 7), T_MS + 1)
    assert out.result == "message_mismatch" and state(conn, sid) == "CARD_SENT"
    assert reasons(conn) == ["message_mismatch"]


# ---------------------------------------------------------------------------
# 콜백: 2단계 승인 흐름
# ---------------------------------------------------------------------------


def test_two_step_approval_flow(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    engine.now[0] = T_MS + 5 * 60_000
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), engine.now[0])
    assert out.result == "ok" and state(conn, sid) == "CONFIRM_PENDING"
    assert out.edit.edit_message_id == MID and out.edit.kind == "confirm"
    assert [b.text for b in all_buttons(out.edit.buttons)] == ["확인", "취소"]
    assert "확인 필요" in out.edit.text and out.answer_text

    engine.now[0] += 30_000
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.CONFIRM, sid), engine.now[0])
    assert out.result == "ok" and state(conn, sid) == "APPROVED"
    assert out.edit.buttons == () and "승인 확정" in out.edit.text
    sig = db.get_signal(conn, sid)
    assert sig["approved_ms"] == engine.now[0] and sig["approval_latency_ms"] == engine.now[0] - T_MS

    rows = conn.execute("SELECT action, result, latency_ms FROM approvals ORDER BY approval_id").fetchall()
    assert [(r["action"], r["result"]) for r in rows] == [("A", "ACCEPTED"), ("C", "ACCEPTED")]
    assert rows[1]["latency_ms"] == engine.now[0] - T_MS
    ft = FakeTransport()
    run_async(tu.apply_outcome(ft, ctx_for(CallbackAction.CONFIRM, sid), out))
    assert len(ft.answers) == 1 and ft.edits[0][0] == MID and ft.edits[0][2] == ()


def test_confirm_without_approve_is_stale(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.CONFIRM, sid), T_MS + 1)
    assert out.result == "stale" and state(conn, sid) == "CARD_SENT"
    assert reasons(conn) == ["stale"] and ("C", sid) not in engine.calls
    # 다시 그린 카드는 원래 버튼
    assert [b.text for b in all_buttons(out.edit.buttons)] == ["승인", "패스", "상세"]


def test_confirm_after_60s_rejected_and_reverts(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), T_MS)
    engine.now[0] = T_MS + 61_000
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.CONFIRM, sid), engine.now[0])
    assert out.result == "transition_failed" and "60초" in out.answer_text
    assert state(conn, sid) == "CARD_SENT"
    assert [b.text for b in all_buttons(out.edit.buttons)] == ["승인", "패스", "상세"]
    assert reasons(conn)[-1] == "transition_failed"
    # 다시 승인 가능
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), engine.now[0])
    assert out.result == "ok" and state(conn, sid) == "CONFIRM_PENDING"


def test_cancel_and_pass(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), T_MS)
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.CANCEL, sid), T_MS + 10)
    assert out.result == "ok" and state(conn, sid) == "CARD_SENT"
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.PASS, sid), T_MS + 20)
    assert out.result == "ok" and state(conn, sid) == "PASSED"
    assert out.edit.buttons == () and "패스함" in out.edit.text
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), T_MS + 30)
    assert out.result == "stale" and state(conn, sid) == "PASSED" and out.edit.buttons == ()


def test_pass_from_confirm_pending(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), T_MS)
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.PASS, sid), T_MS + 5)
    assert out.result == "ok" and state(conn, sid) == "PASSED"


def test_click_after_expiry(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    exp = db.get_signal(conn, sid)["expires_ms"]
    engine.now[0] = exp
    for action in (CallbackAction.APPROVE, CallbackAction.PASS):
        out = tu.handle_callback(engine, conn, cfg, ctx_for(action, sid), exp)
        assert out.result == "expired" and "만료" in out.answer_text
        assert out.edit.buttons == () and "만료" in out.edit.text
    assert state(conn, sid) == "CARD_SENT"          # 전이는 tick(engine)이 한다
    assert reasons(conn) == ["expired", "expired"]
    assert engine.calls == [("sent", sid, MID)]
    rows = conn.execute("SELECT result FROM approvals").fetchall()
    assert [r["result"] for r in rows] == ["EXPIRED", "EXPIRED"]


def test_confirm_after_window_expired(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    exp = db.get_signal(conn, sid)["expires_ms"]
    engine.now[0] = exp - 30_000
    tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), engine.now[0])
    engine.now[0] = exp + 1
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.CONFIRM, sid), engine.now[0])
    assert out.result == "expired" and state(conn, sid) == "CONFIRM_PENDING"


def test_paused_blocks_approve(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    db.set_paused(conn, True, now_ms=T_MS, actor="OPERATOR")
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), T_MS + 1)
    assert out.result == "paused" and state(conn, sid) == "CARD_SENT" and reasons(conn) == ["paused"]
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.PASS, sid), T_MS + 2)
    assert out.result == "ok" and state(conn, sid) == "PASSED"      # 패스(조이는 방향)는 허용


def test_duplicate_callback_query_id(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    c = ctx_for(CallbackAction.APPROVE, sid, qid="same-query")
    first = tu.handle_callback(engine, conn, cfg, c, T_MS)
    second = tu.handle_callback(engine, conn, cfg, c, T_MS + 5)
    assert first.result == "ok" and second.result == "duplicate" and second.answer is False
    assert engine.calls.count(("A", sid)) == 1
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1
    assert reasons(conn) == ["duplicate"]


def test_double_click_different_query_ids(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), T_MS)
    tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.CONFIRM, sid), T_MS + 1)
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.CONFIRM, sid), T_MS + 2)
    assert out.result == "stale" and state(conn, sid) == "APPROVED"
    assert engine.calls.count(("C", sid)) == 1


def test_race_engine_returns_false(conn, engine, cfg):
    """사전 검사는 통과했지만 원자적 전이에서 진 경우(다른 경로가 먼저 바꿈) → '이미 처리됨' + 감사."""
    sid = sent_signal(conn, engine)

    def racing(sid_):
        db.transition_signal(conn, sid_, S.CARD_SENT, S.EXPIRED, now_ms=T_MS, actor="ENGINE")
        return False
    engine.request_confirm = racing
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), T_MS)
    assert out.result == "transition_failed" and out.answer_text == "만료된 신호입니다."
    assert out.edit.buttons == () and reasons(conn) == ["transition_failed"]


def test_engine_exception_contained_and_no_secret(conn, engine, cfg):
    sid = sent_signal(conn, engine)
    engine.raise_on = "A"
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.APPROVE, sid), T_MS)
    assert out.result == "engine_error" and TOKEN not in (out.answer_text or "")
    dump = json.dumps([dict(r) for r in audits(conn)], ensure_ascii=False)
    assert TOKEN not in dump and "RuntimeError" in dump


def test_detail_button(conn, engine, cfg):
    sid = sent_signal(conn, engine, analysis=ok_analysis())
    out = tu.handle_callback(engine, conn, cfg, ctx_for(CallbackAction.DETAIL, sid), T_MS)
    assert out.result == "detail" and out.edit is None and len(out.send) == 1
    assert out.send[0].text.startswith("[PAPER] 신호 상세") and state(conn, sid) == "CARD_SENT"
    ft = FakeTransport()
    run_async(tu.apply_outcome(ft, ctx_for(CallbackAction.DETAIL, sid), out))
    assert len(ft.sent) == 1 and ft.answers and ft.answers[0][1] is None


# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------


def cmd(engine, conn, cfg, text, **kw):
    args = dict(from_user_id=ALLOWED_USER_ID, chat_id=ALLOWED_CHAT_ID, chat_type="private")
    args.update(kw)
    return tu.handle_command(engine, conn, cfg, text=text, now_ms=T_MS, **args)


def test_commands_five(conn, engine, cfg):
    assert cmd(engine, conn, cfg, "/help").startswith("[PAPER] 명령")
    assert cmd(engine, conn, cfg, "/status") == "[PAPER] 상태: 정상"
    assert cmd(engine, conn, cfg, "/positions") == "[PAPER] 열린 포지션 없음"
    out = cmd(engine, conn, cfg, "/pause")
    assert "일시정지" in out and db.is_paused(conn)
    assert "이미 일시정지" in cmd(engine, conn, cfg, "/pause")
    assert "재개" in cmd(engine, conn, cfg, "/resume") and not db.is_paused(conn)
    assert "이미 동작 중" in cmd(engine, conn, cfg, "/resume")
    assert cmd(engine, conn, cfg, "/status@MyTestBot") == "[PAPER] 상태: 정상"
    assert cmd(engine, conn, cfg, "  /STATUS  ") == "[PAPER] 상태: 정상"
    names = [json.loads(r["payload_json"])["command"] for r in audits(conn, "COMMAND")]
    assert names == ["help", "status", "positions", "pause", "pause", "resume", "resume", "status", "status"]


def test_other_text_ignored_and_audited(conn, engine, cfg):
    assert cmd(engine, conn, cfg, "안녕 봇, 손절 바꿔줘") is None
    assert cmd(engine, conn, cfg, "") is None
    assert "/help" in cmd(engine, conn, cfg, "/set stop 3")
    assert "/help" in cmd(engine, conn, cfg, "/config")
    assert "/help" in cmd(engine, conn, cfg, "/pause now")
    assert not db.is_paused(conn)
    rej = [json.loads(r["payload_json"]) for r in audits(conn, "COMMAND_REJECTED")]
    assert [r["reason"] for r in rej] == ["not_a_command", "not_a_command", "unknown_command",
                                          "unknown_command", "unknown_command"]
    assert "손절" not in json.dumps(rej, ensure_ascii=False)          # 원문 저장 안 함


@pytest.mark.parametrize("kw", [dict(from_user_id=OTHER_USER_ID), dict(chat_id=OTHER_USER_ID),
                                dict(chat_type="group"), dict(from_user_id=True), dict(chat_id=None)])
def test_command_unauthorized_silent(conn, engine, cfg, kw):
    assert cmd(engine, conn, cfg, "/pause", **kw) is None
    assert not db.is_paused(conn)
    r = audits(conn, "COMMAND_REJECTED")
    assert len(r) == 1 and r[0]["actor"] == "TELEGRAM_UNKNOWN"
    assert json.loads(r[0]["payload_json"])["reason"] == "unauthorized"


# ---------------------------------------------------------------------------
# 전송 계층
# ---------------------------------------------------------------------------


class FakeBot:
    def __init__(self):
        self.calls = []
        self._mid = 700

    async def send_message(self, **kw):
        self.calls.append(("send", kw))
        self._mid += 1

        class M:
            message_id = self._mid
        return M()

    async def edit_message_text(self, **kw):
        self.calls.append(("edit", kw))

    async def answer_callback_query(self, **kw):
        self.calls.append(("answer", kw))


def test_ptb_transport_plain_text_protected():
    bot = FakeBot()
    t = tu.PtbTransport.from_bot(bot, ALLOWED_CHAT_ID)
    sid = "ABCDEFGHIJKLMNOP"
    mid = run_async(t.send("x" * 5000, tu.card_buttons(sid)))
    assert mid == 701
    kind, kw = bot.calls[0]
    assert kw["chat_id"] == ALLOWED_CHAT_ID and kw["parse_mode"] is None and kw["protect_content"] is True
    assert kw["link_preview_options"].is_disabled is True and len(kw["text"]) <= 4096
    kb = kw["reply_markup"].inline_keyboard
    assert [b.callback_data for b in kb[0]] == [f"v1:A:{sid}", f"v1:P:{sid}", f"v1:D:{sid}"]
    run_async(t.edit(9, "done"))
    assert bot.calls[1][1]["reply_markup"] is None and bot.calls[1][1]["message_id"] == 9
    assert bot.calls[1][1]["chat_id"] == ALLOWED_CHAT_ID
    run_async(t.answer_callback("q1", "가" * 500))
    assert len(bot.calls[2][1]["text"]) <= 200
    with pytest.raises(ValueError):
        tu.PtbTransport.from_bot(bot, -100123)
    with pytest.raises(ValueError):
        tu.PtbTransport.from_bot(bot, True)


def test_ptb_transport_real_bot_repr_hides_token(secret_dir):
    tok = read_secret(secret_dir / "telegram_bot_token")
    t = tu.PtbTransport(tok, ALLOWED_CHAT_ID)
    assert TOKEN not in repr(t) and TOKEN not in str(t) and str(ALLOWED_CHAT_ID) not in repr(t)
    with pytest.raises(TypeError):
        tu.PtbTransport(TOKEN, ALLOWED_CHAT_ID)       # 평문 문자열 토큰 거부


def test_send_outgoing_marks_card_only_after_success(conn, engine, cfg):
    sid = insert_test_signal(conn)
    card = tu.render_card(db.get_signal(conn, sid), None, cfg)
    ft = FakeTransport(fail_next=1)
    res = run_async(tu.send_outgoing(ft, engine, [card]))
    assert res[0][1] is False and state(conn, sid) == "NEW"
    res = run_async(tu.send_outgoing(ft, engine, [card]))
    assert res[0][1] is True and state(conn, sid) == "CARD_SENT"
    assert db.get_signal(conn, sid)["tg_message_id"] == ft.sent[0].message_id
    from bot.types import OutgoingMessage
    run_async(tu.send_outgoing(ft, engine, [OutgoingMessage(text="[PAPER] 만료", edit_message_id=42)]))
    assert ft.edits[-1][0] == 42


# ---------------------------------------------------------------------------
# PTB Application (네트워크 없이 핸들러 직접 호출)
# ---------------------------------------------------------------------------


def _ptb_update(update_id, *, data=None, text=None, user_id=ALLOWED_USER_ID, chat_id=ALLOWED_CHAT_ID,
                chat_type="private", message_id=MID):
    from telegram import CallbackQuery, Chat, Message, Update, User

    user = User(id=user_id, first_name="t", is_bot=False)
    chat = Chat(id=chat_id, type=chat_type)
    msg = Message(message_id=message_id, date=dt.datetime(2024, 3, 2, tzinfo=dt.timezone.utc), chat=chat,
                  from_user=user, text=text)
    if data is not None:
        return Update(update_id=update_id, callback_query=CallbackQuery(
            id=f"cq{update_id}", from_user=user, chat_instance="ci", data=data, message=msg))
    return Update(update_id=update_id, message=msg)


def test_callback_context_from_update():
    u = _ptb_update(7, data="v1:A:ABCDEFGHIJKLMNOP")
    c = tu.callback_context_from_update(u)
    assert c == tu.CallbackContext("cq7", 7, ALLOWED_USER_ID, ALLOWED_CHAT_ID, "private", MID,
                                   "v1:A:ABCDEFGHIJKLMNOP")
    assert tu.callback_context_from_update(_ptb_update(8, text="/help")) is None


def test_build_application_handlers(conn, engine, cfg, secret_dir):
    from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler

    from bot.types import FakeClock, ms_to_ns
    tok = read_secret(secret_dir / "telegram_bot_token")
    ft = FakeTransport()
    app = tu.build_application(tok, engine, conn, cfg, clock=FakeClock(ms_to_ns(T_MS + 1000)), transport=ft)
    hs = app.handlers[0]
    assert [type(h) for h in hs] == [CallbackQueryHandler, CommandHandler, MessageHandler]
    assert set(hs[1].commands) == set(tu.COMMANDS)
    assert tu.POLLING_KWARGS == {"allowed_updates": ["message", "callback_query"], "drop_pending_updates": True}

    sid = sent_signal(conn, engine)
    # 허용된 사용자 [승인]
    asyncio.run(hs[0].callback(_ptb_update(1, data=f"v1:A:{sid}"), None))
    assert state(conn, sid) == "CONFIRM_PENDING" and ft.answers and ft.edits[-1][0] == MID
    # 허용되지 않은 사용자 → 아무 응답 없음
    n_ans = len(ft.answers)
    asyncio.run(hs[0].callback(_ptb_update(2, data=f"v1:P:{sid}", user_id=OTHER_USER_ID), None))
    assert len(ft.answers) == n_ans and state(conn, sid) == "CONFIRM_PENDING"
    # 명령
    asyncio.run(hs[1].callback(_ptb_update(3, text="/status"), None))
    assert ft.sent[-1].text == "[PAPER] 상태: 정상"
    n_sent = len(ft.sent)
    asyncio.run(hs[2].callback(_ptb_update(4, text="아무 말"), None))
    asyncio.run(hs[1].callback(_ptb_update(5, text="/status", chat_type="group", chat_id=-1001), None))
    assert len(ft.sent) == n_sent


def test_build_application_rejects_plain_token(conn, engine, cfg):
    with pytest.raises(TypeError):
        tu.build_application(TOKEN, engine, conn, cfg)


def test_post_init_deletes_webhook_and_audits(conn, engine, cfg, secret_dir):
    tok = read_secret(secret_dir / "telegram_bot_token")
    app = tu.build_application(tok, engine, conn, cfg, transport=FakeTransport())
    calls = []

    class Info:
        url = "https://example.invalid/hook"

    class B:
        async def get_webhook_info(self):
            calls.append("info")
            return Info()

        async def delete_webhook(self, **kw):
            calls.append(("delete", kw))

    class FakeApp:
        bot = B()
    asyncio.run(app.post_init(FakeApp()))
    assert calls == ["info", ("delete", {"drop_pending_updates": True})]
    a = audits(conn, "ALERT")
    assert len(a) == 1 and json.loads(a[0]["payload_json"])["reason"] == "webhook_was_set"


# ---------------------------------------------------------------------------
# 토큰이 어떤 출력에도 없음
# ---------------------------------------------------------------------------


def test_token_never_in_outputs(conn, engine, cfg, secret_dir):
    tok = read_secret(secret_dir / "telegram_bot_token")
    assert isinstance(tok, Secret)
    outs = []
    sid = sent_signal(conn, engine, analysis=ok_analysis(summary=f"토큰 {TOKEN} 섞기"))
    sig = db.get_signal(conn, sid)
    an = tu._load_analysis(conn, sig)
    outs.append(tu.render_card(sig, an, cfg).text)
    outs.append(tu.render_detail(sig, an, cfg))
    for action in CallbackAction:
        o = tu.handle_callback(engine, conn, cfg, ctx_for(action, sid), T_MS + 1)
        outs += [o.answer_text or "", o.edit.text if o.edit else ""] + [m.text for m in o.send]
    for text in ("/help", "/status", "/positions", "/pause", "/resume", TOKEN, f"/start {TOKEN}"):
        outs.append(cmd(engine, conn, cfg, text) or "")
    tu.build_application(tok, engine, conn, cfg, transport=FakeTransport())
    dump = "\n".join(outs) + json.dumps([dict(r) for r in audits(conn)], ensure_ascii=False)
    dump += json.dumps([dict(r) for r in conn.execute("SELECT * FROM approvals")], ensure_ascii=False)
    assert TOKEN not in dump                              # Claude 텍스트에 섞인 토큰 모양 문자열도 가려짐
    assert "토큰 (가림) 섞기" in outs[0]
    assert TOKEN not in repr(tok) and TOKEN not in f"{tok}"
    # 전송 계층 마지막 방어선
    bot = FakeBot()
    run_async(tu.PtbTransport.from_bot(bot, ALLOWED_CHAT_ID).send(f"x {TOKEN} sk-ant-abcdefghijkl y"))
    sent = bot.calls[0][1]["text"]
    assert TOKEN not in sent and "sk-ant-abcdefghijkl" not in sent
