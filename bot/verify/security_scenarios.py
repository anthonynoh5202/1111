"""보안 시나리오 직접 실행 — 검증관 작성 (네트워크 없음, 가짜 전송 계층).

실제 PTB Application 핸들러(telegram_ui.build_application)에 telegram.Update.de_json으로 만든 업데이트를 넣고,
실제 Engine(bot.engine.Engine)과 파일 SQLite(WAL)를 쓴다. 전송은 이 파일의 RecTransport(기록만).

시나리오
 S1  허용되지 않은 사용자의 유효한 버튼(진짜 신호 ID) → 무응답·상태 불변·감사 1행·운영 채팅 경고만
 S2  허용 사용자지만 그룹 채팅 / 다른 채팅 ID / 문자열 ID / bool ID → 모두 거부
 S3  위조 callback_data(모르는 ID, 버전 v2, 64바이트 초과, SQL 모양, 가격 끼워 넣기, 비문자열) → 상태 불변
 S4  같은 callback_query_id 재전송(순차·동시) → 첫 번째만 처리
 S5  다른 메시지에 붙은 버튼(message_id 불일치) → 거부
 S6  동시 클릭: [확인] 10개(다른 query id) 동시 → APPROVED 전이 정확히 1번
 S7  DB 수준 경쟁: 연결 2개 × 스레드 16개가 같은 전이를 동시에 → 정확히 1개 성공(50회 반복)
 S8  만료(2시간)·확인 창(60초) 초과·일시정지 중 승인 → 전이 없음
 S9  권한 없는 명령(/pause, /resume, /status) → 응답 없음·플래그 불변. 허용 사용자의 설정 변경 시도 → 거부
 S10 권한 없는 버튼 1,000번 폭주 → 감사 행 상한, 상대에게 응답 0, 운영 경고 1번
 S11 감사 로그 UPDATE/DELETE 차단(audit_log, config_snapshots), 트리거 삭제 후 재시작 거부, 행 삭제 후 재시작 거부
 S12 (알려진 한계 확인) 트리거를 지우고 행 수정 후 트리거 재생성 → 탐지 안 됨(L1+ 한계, 기록용)

사용법: .venv/bin/python bot/verify/security_scenarios.py [--json out.json]   종료 코드 0 = 필수 항목 모두 통과
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from telegram import Update  # noqa: E402

from bot import db  # noqa: E402
from bot import telegram_ui as tu  # noqa: E402
from bot.config import Secret  # noqa: E402
from bot.engine import Engine  # noqa: E402
from bot.tests.conftest import (  # noqa: E402
    ALLOWED_CHAT_ID,
    ALLOWED_USER_ID,
    OTHER_USER_ID,
    T_DECISION_NS,
    T_MS,
    insert_test_signal,
    make_config,
)
from bot.types import CallbackAction, FakeClock, Mode, SignalState, make_callback_data, new_signal_id  # noqa: E402

TOKEN = "123456:TEST-dummy-token-not-real"
S = SignalState
RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "", *, required: bool = True) -> None:
    RESULTS.append(dict(name=name, passed=bool(ok), detail=detail, required=required))
    mark = "PASS" if ok else ("FAIL" if required else "NOTE")
    print(f"[{mark}] {name} — {detail}")


@dataclass
class RecTransport:
    sent: list[tuple[int, str, tuple]] = field(default_factory=list)
    edits: list[tuple[int, str, tuple]] = field(default_factory=list)
    answers: list[tuple[str, str | None]] = field(default_factory=list)
    _id: int = 5000

    async def send(self, text, buttons=(), *, protect=True):
        self._id += 1
        self.sent.append((self._id, text, buttons))
        return self._id

    async def edit(self, message_id, text, buttons=()):
        self.edits.append((message_id, text, buttons))

    async def answer_callback(self, cqid, text=None):
        self.answers.append((cqid, text))


class Env:
    """파일 DB + 실제 Engine + 실제 PTB 핸들러."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.cfg = make_config(tmp, db_path=str(tmp / "bot.sqlite3"))
        self.clock = FakeClock(T_DECISION_NS)
        self.conn = db.connect(tmp / "bot.sqlite3", mode=Mode.PAPER, now_ms=T_MS)
        self.engine = Engine(self.conn, self.cfg, None, None, self.clock)
        self.tx = RecTransport()
        self.app = tu.build_application(Secret(TOKEN), self.engine, self.conn, self.cfg, clock=self.clock,
                                        transport=self.tx)
        hs = self.app.handlers[0]
        self.on_callback = hs[0].callback
        self.on_message = hs[-1].callback
        self._uid = 0
        self._cq = 0

    def card(self, n: int = 20) -> tuple[str, int]:
        sid = insert_test_signal(self.conn, n=n, decision_ns=T_DECISION_NS)
        mid = 900 + n
        assert self.engine.mark_card_sent(sid, mid)
        return sid, mid

    def state(self, sid: str) -> str:
        return db.get_signal(self.conn, sid)["state"]

    def audit_count(self, where: str = "1=1", params=()) -> int:
        return int(self.conn.execute(f"SELECT COUNT(*) FROM audit_log WHERE {where}", params).fetchone()[0])

    def cb_update(self, data, *, user=ALLOWED_USER_ID, chat=ALLOWED_CHAT_ID, chat_type="private", mid=None,
                  cqid: str | None = None) -> Update:
        self._uid += 1
        self._cq += 1
        d = {"update_id": self._uid,
             "callback_query": {"id": cqid or f"cq{self._cq}", "chat_instance": "ci",
                                "from": {"id": user, "is_bot": False, "first_name": "u"},
                                "message": {"message_id": mid or 1, "date": 0,
                                            "chat": {"id": chat, "type": chat_type}}}}
        if data is not None:
            d["callback_query"]["data"] = data
        return Update.de_json(d, self.app.bot)

    def msg_update(self, text: str, *, user=ALLOWED_USER_ID, chat=ALLOWED_CHAT_ID, chat_type="private") -> Update:
        self._uid += 1
        ents = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}] if text.startswith("/") else []
        d = {"update_id": self._uid,
             "message": {"message_id": self._uid, "date": 0, "text": text, "entities": ents,
                         "chat": {"id": chat, "type": chat_type},
                         "from": {"id": user, "is_bot": False, "first_name": "u"}}}
        return Update.de_json(d, self.app.bot)

    def click(self, upd: Update) -> None:
        asyncio.run(self.on_callback(upd, None))

    def clicks_concurrent(self, upds: list[Update]) -> None:
        async def go():
            await asyncio.gather(*(self.on_callback(u, None) for u in upds))
        asyncio.run(go())

    def say(self, upd: Update) -> None:
        asyncio.run(self.on_message(upd, None))

    def close(self) -> None:
        self.conn.close()


def fresh(tag: str) -> Env:
    d = Path(tempfile.mkdtemp(prefix=f"sec_{tag}_"))
    os.chmod(d, 0o700)
    return Env(d)


# ---------------------------------------------------------------------------


def s1_unauthorized_user() -> None:
    e = fresh("s1")
    sid, mid = e.card()
    before = e.audit_count("event_type = 'BUTTON_REJECTED'")
    for act in (CallbackAction.APPROVE, CallbackAction.PASS, CallbackAction.DETAIL):
        e.click(e.cb_update(make_callback_data(act, sid), user=OTHER_USER_ID, chat=OTHER_USER_ID, mid=mid))
    rej = e.audit_count("event_type = 'BUTTON_REJECTED'") - before
    payloads = [json.loads(r[0]) for r in e.conn.execute(
        "SELECT payload_json FROM audit_log WHERE event_type='BUTTON_REJECTED'")]
    check("S1 권한 없는 사용자: 상태 불변", e.state(sid) == S.CARD_SENT.value, e.state(sid))
    check("S1 권한 없는 사용자: 상대에게 응답·수정 없음", not e.tx.answers and not e.tx.edits,
          f"answers={len(e.tx.answers)} edits={len(e.tx.edits)}")
    check("S1 권한 없는 사용자: 감사 행 남김(같은 사람 60초 안 = 1행)", rej == 1 and payloads[0].get("reason") == "unauthorized",
          f"rows={rej} payload={payloads[:1]}")
    alerts = [t for _, t, _ in e.tx.sent]
    check("S1 운영(허용) 채팅 경고 1번(상대 아님: 전송 계층은 허용 채팅 고정)",
          len(alerts) == 1 and "허용되지 않은" in alerts[0], f"sent={len(alerts)}")
    check("S1 approvals 테이블에 기록 안 됨(허용 클릭만 기록)",
          int(e.conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]) == 0, "")
    e.close()


def s2_identity_variants() -> None:
    e = fresh("s2")
    sid, mid = e.card()
    data = make_callback_data(CallbackAction.APPROVE, sid)
    cases = [
        ("허용 사용자 + 그룹 채팅(음수 ID)", dict(chat=-100123, chat_type="supergroup")),
        ("허용 사용자 + 그룹 타입, 같은 채팅 ID", dict(chat_type="group")),
        ("다른 사용자 + 허용 채팅 ID", dict(user=OTHER_USER_ID)),
        ("허용 사용자 + 다른 개인 채팅", dict(chat=OTHER_USER_ID)),
        ("채널 타입", dict(chat_type="channel")),
    ]
    for name, kw in cases:
        e.click(e.cb_update(data, mid=mid, **kw))
        check(f"S2 {name} → 거부", e.state(sid) == S.CARD_SENT.value and not e.tx.answers, e.state(sid))
    # 타입 혼동: 문자열·bool ID (PTB를 거치지 않고 handle_callback 직접)
    for name, uid, cid in (("문자열 사용자 ID", str(ALLOWED_USER_ID), ALLOWED_CHAT_ID),
                           ("문자열 채팅 ID", ALLOWED_USER_ID, str(ALLOWED_CHAT_ID)),
                           ("bool 사용자 ID", True, ALLOWED_CHAT_ID), ("None 사용자", None, ALLOWED_CHAT_ID)):
        ctx = tu.CallbackContext(callback_query_id=f"t-{name}", update_id=1, from_user_id=uid, chat_id=cid,
                                 chat_type="private", message_id=mid, data=data)
        out = tu.handle_callback(e.engine, e.conn, e.cfg, ctx, T_MS + 1000)
        check(f"S2 {name} → 거부(무응답)", out.result == "unauthorized" and out.answer is False
              and e.state(sid) == S.CARD_SENT.value, out.result)
    # 설정이 0(미설정)이면 기본 거부
    cfg0 = make_config(e.tmp, **{"telegram.allowed_user_id": 0, "telegram.allowed_chat_id": 0}) \
        if _cfg_allows_zero(e) else None
    if cfg0 is not None:
        ok = not tu.is_authorized(cfg0, 0, 0, "private")
        check("S2 허용 ID 미설정(0) → 모두 거부", ok, "")
    else:
        check("S2 허용 ID 미설정(0) → 설정 검증 단계에서 거부", True, "config_from_dict가 0을 거부")
    e.close()


def _cfg_allows_zero(e: Env) -> bool:
    try:
        make_config(e.tmp, **{"telegram.allowed_user_id": 0, "telegram.allowed_chat_id": 0})
        return True
    except Exception:  # noqa: BLE001
        return False


def s3_forged_data() -> None:
    e = fresh("s3")
    sid, mid = e.card()
    unknown = new_signal_id()
    forged = [
        ("모르는 신호 ID", make_callback_data(CallbackAction.CONFIRM, unknown)),
        ("버전 v2", f"v2:A:{sid}"),
        ("없는 동작 코드", f"v1:Z:{sid}"),
        ("소문자 ID", f"v1:A:{sid.lower()}"),
        ("64바이트 초과", "v1:A:" + "A" * 80),
        ("SQL 모양", f"v1:A:{sid}' OR '1'='1"),
        ("가격 끼워 넣기", f"v1:C:{sid}:price=1"),
        ("빈 값", ""),
        ("줄바꿈", f"v1:A:{sid}\n"),
        ("data 없음(게임 버튼)", None),
    ]
    for name, data in forged:
        e.click(e.cb_update(data, mid=mid))
        check(f"S3 위조 data: {name} → 상태 불변", e.state(sid) == S.CARD_SENT.value, e.state(sid))
    # [확인]을 [승인] 없이 바로(2단계 건너뛰기)
    e.click(e.cb_update(make_callback_data(CallbackAction.CONFIRM, sid), mid=mid))
    check("S3 [승인] 없이 [확인]만 → 전이 없음(2단계 우회 불가)", e.state(sid) == S.CARD_SENT.value, e.state(sid))
    n_signals = int(e.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
    check("S3 위조로 신호 테이블 변화 없음", n_signals == 1, f"signals={n_signals}")
    e.close()


def s4_replay() -> None:
    e = fresh("s4")
    sid, mid = e.card()
    data_a = make_callback_data(CallbackAction.APPROVE, sid)
    e.click(e.cb_update(data_a, mid=mid, cqid="same-1"))
    st1 = e.state(sid)
    n_ans = len(e.tx.answers)
    e.click(e.cb_update(data_a, mid=mid, cqid="same-1"))            # 재전송(같은 query id)
    check("S4 순차 재전송: 두 번째는 무응답·상태 그대로", st1 == S.CONFIRM_PENDING.value and e.state(sid) == st1
          and len(e.tx.answers) == n_ans, f"{st1} answers {n_ans}->{len(e.tx.answers)}")
    dup = e.audit_count("event_type='BUTTON_REJECTED' AND payload_json LIKE '%duplicate%'")
    check("S4 재전송 감사 행(duplicate)", dup == 1, f"{dup}")
    # 동시 재전송: [확인] 같은 query id 5개 동시
    data_c = make_callback_data(CallbackAction.CONFIRM, sid)
    e.clicks_concurrent([e.cb_update(data_c, mid=mid, cqid="same-2") for _ in range(5)])
    appr = int(e.conn.execute("SELECT COUNT(*) FROM approvals WHERE callback_query_id='same-2'").fetchone()[0])
    to_appr = e.audit_count("event_type='STATE_TRANSITION' AND to_state='APPROVED' AND entity_id=?", (sid,))
    check("S4 동시 재전송(같은 id ×5): 처리 1번, APPROVED 1번", appr == 1 and to_appr == 1 and
          e.state(sid) == S.APPROVED.value, f"approvals={appr} transitions={to_appr} state={e.state(sid)}")
    # 처리 끝난 카드의 옛 버튼(새 query id) → stale
    e.click(e.cb_update(make_callback_data(CallbackAction.PASS, sid), mid=mid))
    check("S4 승인 뒤 옛 카드 [패스] → 상태 그대로(APPROVED)", e.state(sid) == S.APPROVED.value, e.state(sid))
    e.close()


def s5_message_mismatch() -> None:
    e = fresh("s5")
    sid, mid = e.card()
    e.click(e.cb_update(make_callback_data(CallbackAction.APPROVE, sid), mid=mid + 1))
    check("S5 다른 메시지의 버튼 → 거부", e.state(sid) == S.CARD_SENT.value, e.state(sid))
    e.close()


def s6_concurrent_confirm() -> None:
    e = fresh("s6")
    sid, mid = e.card()
    e.click(e.cb_update(make_callback_data(CallbackAction.APPROVE, sid), mid=mid))
    data_c = make_callback_data(CallbackAction.CONFIRM, sid)
    data_p = make_callback_data(CallbackAction.PASS, sid)
    ups = [e.cb_update(data_c, mid=mid) for _ in range(10)] + [e.cb_update(data_p, mid=mid) for _ in range(5)]
    e.clicks_concurrent(ups)
    final = e.state(sid)
    to_final = e.audit_count("event_type='STATE_TRANSITION' AND to_state IN ('APPROVED','PASSED') AND entity_id=?",
                             (sid,))
    check("S6 [확인]×10 + [패스]×5 동시 → 최종 전이 정확히 1번", to_final == 1 and final in ("APPROVED", "PASSED"),
          f"final={final} transitions={to_final}")
    # 엔진 직접(텔레그램 락 없이) 스레드 경쟁
    sid2, mid2 = e.card(n=55)
    assert e.engine.request_confirm(sid2)
    res: list[bool] = []
    bar = threading.Barrier(12)

    def w():
        bar.wait()
        res.append(e.engine.confirm(sid2))
    ts = [threading.Thread(target=w) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("S6 engine.confirm 스레드 12개 동시 → True 정확히 1개", res.count(True) == 1, f"{res.count(True)}")
    e.close()


def s7_db_race() -> None:
    d = Path(tempfile.mkdtemp(prefix="sec_s7_"))
    bad_rounds = 0
    errors: list[str] = []
    for k in range(50):
        p = d / f"race{k}.sqlite3"          # 반복마다 새 DB(하위 시스템당 진행 중 신호 1개 제약)
        c0 = db.connect(p, mode=Mode.PAPER, now_ms=T_MS)
        sid = insert_test_signal(c0, n=20)
        db.transition_signal(c0, sid, S.NEW, S.CARD_SENT, now_ms=T_MS, actor="ENGINE")
        db.transition_signal(c0, sid, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=T_MS, actor="TELEGRAM_USER")
        conns = [db.connect(p, mode=Mode.PAPER, now_ms=T_MS) for _ in range(2)]
        res: list[bool] = []
        lk = threading.Lock()
        bar = threading.Barrier(16)

        def w(i):
            c = conns[i % 2]
            bar.wait()
            try:
                # 같은 연결을 두 스레드가 쓰므로 연결별 잠금(운영의 db_lock과 같은 구조), 연결 사이는 SQLite가 직렬화
                with conn_locks[i % 2]:
                    r = db.transition_signal(c, sid, S.CONFIRM_PENDING, S.APPROVED, now_ms=T_MS, actor="TELEGRAM_USER")
            except Exception as exc:  # noqa: BLE001
                r = False
                errors.append(type(exc).__name__)
            with lk:
                res.append(r)
        conn_locks = [threading.Lock(), threading.Lock()]
        ts = [threading.Thread(target=w, args=(i,)) for i in range(16)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        if res.count(True) != 1:
            bad_rounds += 1
        n_tr = int(c0.execute("SELECT COUNT(*) FROM audit_log WHERE to_state='APPROVED'").fetchone()[0])
        if n_tr != 1:
            bad_rounds += 1
        for c in conns:
            c.close()
        c0.close()
    check("S7 DB 경쟁(연결 2 × 스레드 16, 50회): 매번 정확히 1개 성공", bad_rounds == 0,
          f"bad_rounds={bad_rounds} errors={sorted(set(errors))}")


def s8_windows() -> None:
    e = fresh("s8")
    sid, mid = e.card()
    e.clock.set(T_DECISION_NS + 7200 * 1_000_000_000)
    e.click(e.cb_update(make_callback_data(CallbackAction.APPROVE, sid), mid=mid))
    ans = e.tx.answers[-1][1] if e.tx.answers else ""
    check("S8 2시간 뒤 [승인] → 거부(승인 안 됨, '만료' 응답; EXPIRED 전이는 tick이 한다)",
          e.state(sid) in (S.CARD_SENT.value, S.EXPIRED.value) and "만료" in (ans or ""), f"{e.state(sid)} / {ans}")
    e.engine.tick() if e.engine.market is not None else None
    e.close()
    e = fresh("s8b")
    sid, mid = e.card()
    e.click(e.cb_update(make_callback_data(CallbackAction.APPROVE, sid), mid=mid))
    e.clock.advance(61 * 1_000_000_000)
    e.click(e.cb_update(make_callback_data(CallbackAction.CONFIRM, sid), mid=mid))
    check("S8 [승인] 61초 뒤 [확인] → 승인 안 됨(CARD_SENT로 되돌림)", e.state(sid) == S.CARD_SENT.value, e.state(sid))
    e.say(e.msg_update("/pause"))
    sid2, mid2 = e.card(n=100)
    e.click(e.cb_update(make_callback_data(CallbackAction.APPROVE, sid2), mid=mid2))
    check("S8 일시정지 중 [승인] → 전이 없음", e.state(sid2) == S.CARD_SENT.value, e.state(sid2))
    e.close()


def s9_commands() -> None:
    e = fresh("s9")
    for cmd in ("/pause", "/status", "/positions", "/help"):
        e.say(e.msg_update(cmd, user=OTHER_USER_ID, chat=OTHER_USER_ID))
    replies = [t for _, t, _ in e.tx.sent if "허용되지 않은" not in t]
    check("S9 권한 없는 명령 → 상대에게 응답 없음", not replies, f"non-alert sends={len(replies)}")
    check("S9 권한 없는 /pause → 플래그 불변", not db.is_paused(e.conn), "")
    e.say(e.msg_update("/pause"))
    check("S9 허용 사용자 /pause → 일시정지", db.is_paused(e.conn), "")
    e.say(e.msg_update("/resume", user=OTHER_USER_ID, chat=OTHER_USER_ID))
    check("S9 권한 없는 /resume → 여전히 일시정지", db.is_paused(e.conn), "")
    n0 = len(e.tx.sent)
    for t in ("/set approval_window_s 999999", "/config", "/resume now", "/allow 555", "/pause@evil_bot x"):
        e.say(e.msg_update(t))
    new = [t for _, t, _ in e.tx.sent[n0:]]
    check("S9 허용 사용자라도 인자 있는 명령·설정 변경 명령 → 거부(설정 불변, 여전히 일시정지)",
          db.is_paused(e.conn) and all("지원하지 않는" in t for t in new) and e.cfg.schedule.approval_window_s == 7200,
          f"replies={len(new)}")
    # 권한 없는 메시지 원문이 감사 로그에 남지 않는지(실수로 붙여 넣은 비밀 보호)
    e.say(e.msg_update("sk-ant-api03-abcdefghijklmnopqrst", user=OTHER_USER_ID, chat=OTHER_USER_ID))
    e.say(e.msg_update("my token 123456789:AAEabcdefghijklmnopqrstuvwxyz012345"))
    dump = "\n".join(r[0] or "" for r in e.conn.execute("SELECT payload_json FROM audit_log"))
    check("S9 메시지 원문(비밀 모양)이 감사 로그에 없음", "sk-ant-api03" not in dump and "AAEabcdefghij" not in dump, "")
    e.close()


def s10_flood() -> None:
    e = fresh("s10")
    sid, mid = e.card()
    before = e.audit_count()
    data = make_callback_data(CallbackAction.APPROVE, sid)
    for i in range(1000):
        uid = 10_000_000 + (i % 50)            # 50명이 번갈아
        e.click(e.cb_update(data, user=uid, chat=uid, mid=mid))
    rows = e.audit_count() - before
    check("S10 권한 없는 클릭 1,000번 → 감사 행 상한(≤ 21) · 상대 응답 0 · 운영 경고 1번",
          rows <= 21 and not e.tx.answers and len(e.tx.sent) == 1 and e.state(sid) == S.CARD_SENT.value,
          f"audit_rows={rows} answers={len(e.tx.answers)} alerts={len(e.tx.sent)}")
    e.clock.advance(61 * 1_000_000_000)
    e.click(e.cb_update(data, user=OTHER_USER_ID, chat=OTHER_USER_ID, mid=mid))
    sup = e.audit_count("payload_json LIKE '%unauthorized_suppressed%'")
    check("S10 다음 창 시작 시 억제 개수 요약 1행", sup == 1, f"{sup}")
    e.close()


def s11_audit_append_only() -> None:
    d = Path(tempfile.mkdtemp(prefix="sec_s11_"))
    p = d / "a.sqlite3"
    c = db.connect(p, mode=Mode.PAPER, now_ms=T_MS)
    db.audit(c, ts_ms=T_MS, actor="SYSTEM", event="ALERT", payload={"x": 1})
    db.save_config_snapshot(c, config_dict={"a": 1}, fingerprint="f", bot_version="v", now_ms=T_MS)
    for tbl, stmt in (("audit_log", "UPDATE audit_log SET payload_json='{}'"),
                      ("audit_log", "DELETE FROM audit_log"),
                      ("audit_log", "UPDATE audit_log SET seq = seq + 1000"),
                      ("config_snapshots", "UPDATE config_snapshots SET config_json='{}'"),
                      ("config_snapshots", "DELETE FROM config_snapshots")):
        try:
            c.execute(stmt)
            ok, msg = False, "실행됨"
        except sqlite3.DatabaseError as exc:
            ok, msg = "append-only" in str(exc), str(exc)
        check(f"S11 {stmt.split()[0]} {tbl} 차단", ok, msg)
    # INSERT OR REPLACE(= DELETE + INSERT)로 덮어쓰기
    try:
        c.execute("INSERT OR REPLACE INTO audit_log(seq, ts_ms, actor, event_type) VALUES (1, 0, 'X', 'Y')")
        row = c.execute("SELECT actor FROM audit_log WHERE seq=1").fetchone()[0]
        check("S11 INSERT OR REPLACE로 기존 행 덮어쓰기 차단", row != "X", f"actor={row}")
    except sqlite3.DatabaseError as exc:
        check("S11 INSERT OR REPLACE로 기존 행 덮어쓰기 차단", True, str(exc))
    n = c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    c.close()
    # 트리거 삭제 → 행 삭제 → 재시작
    raw = sqlite3.connect(p)
    raw.execute("DROP TRIGGER audit_log_no_delete")
    raw.execute("DELETE FROM audit_log WHERE seq = (SELECT MIN(seq) FROM audit_log)")
    raw.commit()
    raw.close()
    try:
        db.connect(p, mode=Mode.PAPER, now_ms=T_MS).close()
        check("S11 트리거 삭제 + 행 삭제 후 재시작 → 거부", False, "열림")
    except db.DbError as exc:
        check("S11 트리거 삭제 + 행 삭제 후 재시작 → 거부", True, str(exc)[:80])
    # 트리거를 되살려도 행 수 != 마지막 번호 → 거부
    raw = sqlite3.connect(p)
    raw.execute("CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;")
    raw.commit()
    raw.close()
    try:
        db.connect(p, mode=Mode.PAPER, now_ms=T_MS).close()
        check("S11 트리거 복구해도 행 삭제 흔적(행 수 != seq) → 거부", False, "열림")
    except db.DbError as exc:
        check("S11 트리거 복구해도 행 삭제 흔적(행 수 != seq) → 거부", True, str(exc)[:80])
    # 권한 검사: 0644 DB 거부
    p2 = d / "b.sqlite3"
    db.connect(p2, mode=Mode.PAPER, now_ms=T_MS).close()
    os.chmod(p2, 0o644)
    try:
        db.connect(p2, mode=Mode.PAPER, now_ms=T_MS).close()
        check("S11 DB 파일 0644 → 시작 거부", False, "열림")
    except db.DbError:
        check("S11 DB 파일 0644 → 시작 거부", True, "")
    check("S11 (참고) 행 수", n >= 2, f"{n}", required=False)


def s12_known_limit() -> None:
    d = Path(tempfile.mkdtemp(prefix="sec_s12_"))
    p = d / "a.sqlite3"
    c = db.connect(p, mode=Mode.PAPER, now_ms=T_MS)
    db.audit(c, ts_ms=T_MS, actor="SYSTEM", event="ALERT", payload={"x": "original"})
    c.close()
    raw = sqlite3.connect(p)
    raw.execute("DROP TRIGGER audit_log_no_update")
    raw.execute("UPDATE audit_log SET payload_json='{\"x\":\"forged\"}' WHERE payload_json LIKE '%original%'")
    raw.execute("CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;")
    raw.commit()
    raw.close()
    try:
        db.connect(p, mode=Mode.PAPER, now_ms=T_MS).close()
        detected = False
    except db.DbError:
        detected = True
    check("S12 (알려진 한계) DB 파일 쓰기 권한자가 트리거를 지웠다 되살리며 행 수정 → 탐지 안 됨",
          not detected, "L1+ 한계(해시 체인 L4는 TESTNET 전 과제) — 기대대로 탐지 못 함", required=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    os.umask(0o077)
    for f in (s1_unauthorized_user, s2_identity_variants, s3_forged_data, s4_replay, s5_message_mismatch,
              s6_concurrent_confirm, s7_db_race, s8_windows, s9_commands, s10_flood, s11_audit_append_only,
              s12_known_limit):
        try:
            f()
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"{f.__name__} 실행", False, f"{type(exc).__name__}: {exc}")
    req = [r for r in RESULTS if r["required"]]
    failed = [r for r in req if not r["passed"]]
    print(f"\n필수 {len(req)}개 중 통과 {len(req) - len(failed)}개, 실패 {len(failed)}개")
    if a.json:
        Path(a.json).write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
