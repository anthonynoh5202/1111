"""A→B 주문 큐(SQLite) — 스키마 + 원자적 전이 — 설계 담당 소유 (DESIGN §2, §3).

- 같은 DB 파일(bot.db, WAL)에 테이블을 더한다(``ensure_schema``, CREATE IF NOT EXISTS — 멱등).
  TESTNET 모드에서 ``bot.db.connect`` 뒤 A·B 둘 다 한 번 부른다(통합 담당이 연결).
- 전이는 ``UPDATE … WHERE intent_id=? AND state IN (기대값)`` 한 문장. 영향 행 0이면 False(경쟁·중복·상태 불일치).
  허용 전이는 ``types.INTENT_TRANSITIONS``만. 같은 트랜잭션에서 신호(signals) 상태를 맞추고(sync), 감사 로그 한 줄.
- 거래소 노출이 있을 수 있는 의도(INTENT_LIVE)는 **동시에 1개**(부분 고유 인덱스) — I6(동시 포지션 ≤ 1).
- order_events·order_halts·order_halt_releases는 추가 전용(UPDATE·DELETE·REPLACE 트리거가 ABORT).
- B는 A가 쓴 값을 '요청'으로만 본다: 큐 행의 atr20·approved_ms는 enqueue 때 signals에서 복사한 값이고,
  B는 가져간 뒤 signals를 다시 읽어 대조한다(gateway의 사전 점검).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Mapping

from bot import db
from bot.orders.types import (
    INTENT_LIVE,
    ORDER_ACTOR,
    SYMBOL,
    HaltReason,
    IntentExitReason,
    IntentState,
    can_intent_transition,
)
from bot.types import AuditEvent, SignalState

_ST = ",".join(f"'{s.value}'" for s in IntentState)
_LIVE = ",".join(f"'{s.value}'" for s in sorted(INTENT_LIVE, key=lambda s: s.value))
_EXIT = ",".join(f"'{r.value}'" for r in IntentExitReason)
_HALT = ",".join(f"'{r.value}'" for r in HaltReason)

EVENT_KINDS = ("REQUEST", "RESPONSE", "ERROR", "QUERY", "FIREWALL", "RECONCILE", "NOTE")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS order_intents (
    intent_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id            TEXT NOT NULL UNIQUE REFERENCES signals(signal_id),
    symbol               TEXT NOT NULL CHECK (symbol = '{SYMBOL}'),
    side                 INTEGER NOT NULL CHECK (side = 1),
    subsystem_n          INTEGER NOT NULL CHECK (subsystem_n IN (20, 55, 100)),
    atr20                REAL NOT NULL CHECK (atr20 > 0),
    approved_ms          INTEGER NOT NULL,
    state                TEXT NOT NULL CHECK (state IN ({_ST})),
    state_reason         TEXT,
    state_version        INTEGER NOT NULL DEFAULT 0,
    created_ms           INTEGER NOT NULL,
    updated_ms           INTEGER NOT NULL,
    claimed_ms           INTEGER,
    mark_price           REAL,
    limit_price          REAL,
    planned_stop         REAL,
    planned_qty          REAL,
    entry_client_id      TEXT,
    entry_sent_ms        INTEGER,               -- 진입 전송 직전에 커밋(재시작 때 '보냈을 수 있음'의 근거)
    entry_deadline_ms    INTEGER,               -- 서명 timestamp + recvWindow (이 뒤에는 거래소가 받지 않는다)
    entry_order_id       TEXT,
    filled_qty           REAL,
    avg_fill_price       REAL,
    entry_fill_ms        INTEGER,
    stop_client_id       TEXT,
    stop_price           REAL,
    stop_placed_ms       INTEGER,
    stop_verified_ms     INTEGER,
    unprotected_ms       INTEGER,               -- 체결 → 손절 확인까지(ms). 선배치 경로는 0
    stop_attempts        INTEGER NOT NULL DEFAULT 0,
    exit_signal_close_ms INTEGER,
    exit_due_ms          INTEGER,
    exit_requested_ms    INTEGER,
    exit_attempts        INTEGER NOT NULL DEFAULT 0,
    exit_sent_ms         INTEGER,
    flatten_attempts     INTEGER NOT NULL DEFAULT 0,
    exit_reason          TEXT CHECK (exit_reason IS NULL OR exit_reason IN ({_EXIT})),
    exit_price           REAL,
    exit_qty             REAL,
    closed_ms            INTEGER,
    halt_id              INTEGER,
    CHECK (state != 'QUEUED' OR (claimed_ms IS NULL AND entry_sent_ms IS NULL)),
    CHECK (state != 'REJECTED' OR entry_sent_ms IS NULL),
    CHECK (state != 'NOT_FILLED' OR entry_sent_ms IS NOT NULL),
    CHECK (state NOT IN ('ENTRY_FILLED', 'STOP_PLACED', 'STOP_VERIFIED', 'EXITING', 'CLOSED')
           OR (filled_qty IS NOT NULL AND filled_qty > 0 AND avg_fill_price IS NOT NULL AND avg_fill_price > 0)),
    CHECK (state NOT IN ('STOP_VERIFIED', 'EXITING') OR stop_verified_ms IS NOT NULL),
    CHECK (state NOT IN ('CLOSED', 'FAILED_FLATTENED') OR (closed_ms IS NOT NULL AND exit_reason IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS order_intents_one_live ON order_intents(symbol) WHERE state IN ({_LIVE});
CREATE INDEX IF NOT EXISTS order_intents_state ON order_intents(state);

CREATE TABLE IF NOT EXISTS order_events (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,
    intent_id    INTEGER REFERENCES order_intents(intent_id),
    kind         TEXT NOT NULL CHECK (kind IN ({",".join(f"'{k}'" for k in EVENT_KINDS)})),
    client_id    TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS order_events_intent ON order_events(intent_id);
CREATE TRIGGER IF NOT EXISTS order_events_no_update BEFORE UPDATE ON order_events
BEGIN SELECT RAISE(ABORT, 'order_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS order_events_no_delete BEFORE DELETE ON order_events
BEGIN SELECT RAISE(ABORT, 'order_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS order_events_no_replace BEFORE INSERT ON order_events
WHEN NEW.event_id IS NOT NULL AND EXISTS (SELECT 1 FROM order_events WHERE event_id = NEW.event_id)
BEGIN SELECT RAISE(ABORT, 'order_events is append-only'); END;

CREATE TABLE IF NOT EXISTS order_halts (
    halt_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,
    level        TEXT NOT NULL CHECK (level = 'T0'),
    reason       TEXT NOT NULL CHECK (reason IN ({_HALT})),
    intent_id    INTEGER REFERENCES order_intents(intent_id),
    detail_json  TEXT
);
CREATE TRIGGER IF NOT EXISTS order_halts_no_update BEFORE UPDATE ON order_halts
BEGIN SELECT RAISE(ABORT, 'order_halts is append-only'); END;
CREATE TRIGGER IF NOT EXISTS order_halts_no_delete BEFORE DELETE ON order_halts
BEGIN SELECT RAISE(ABORT, 'order_halts is append-only'); END;
CREATE TRIGGER IF NOT EXISTS order_halts_no_replace BEFORE INSERT ON order_halts
WHEN NEW.halt_id IS NOT NULL AND EXISTS (SELECT 1 FROM order_halts WHERE halt_id = NEW.halt_id)
BEGIN SELECT RAISE(ABORT, 'order_halts is append-only'); END;

CREATE TABLE IF NOT EXISTS order_halt_releases (
    release_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    halt_id      INTEGER NOT NULL UNIQUE REFERENCES order_halts(halt_id),
    ts_ms        INTEGER NOT NULL,
    control_ref  TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS order_halt_releases_no_update BEFORE UPDATE ON order_halt_releases
BEGIN SELECT RAISE(ABORT, 'order_halt_releases is append-only'); END;
CREATE TRIGGER IF NOT EXISTS order_halt_releases_no_delete BEFORE DELETE ON order_halt_releases
BEGIN SELECT RAISE(ABORT, 'order_halt_releases is append-only'); END;

CREATE TABLE IF NOT EXISTS order_runtime (
    key        TEXT PRIMARY KEY CHECK (key IN ('b_heartbeat_ms', 'last_reconcile_ms', 'last_reconcile_ok',
                                               'reconcile_fail_count', 'b_started_ms', 'clock_offset_ms')),
    value      TEXT NOT NULL,
    updated_ms INTEGER NOT NULL
);
"""

PROTECT_TRIGGERS = ("order_events_no_update", "order_events_no_delete", "order_events_no_replace",
                    "order_halts_no_update", "order_halts_no_delete", "order_halts_no_replace",
                    "order_halt_releases_no_update", "order_halt_releases_no_delete")

# B가 바꿀 수 있는 열(식별·복사 열 제외)
INTENT_MUTABLE_FIELDS = frozenset({
    "claimed_ms", "mark_price", "limit_price", "planned_stop", "planned_qty", "entry_client_id", "entry_sent_ms",
    "entry_deadline_ms", "entry_order_id", "filled_qty", "avg_fill_price", "entry_fill_ms", "stop_client_id",
    "stop_price", "stop_placed_ms", "stop_verified_ms", "unprotected_ms", "stop_attempts", "exit_sent_ms",
    "exit_attempts", "flatten_attempts", "exit_reason", "exit_price", "exit_qty", "closed_ms", "halt_id",
})

# 의도 상태 → 신호가 있어야 할 상태(동기화 목표). None = 건드리지 않음.
_SIGNAL_TARGET: dict[IntentState, SignalState | None] = {
    IntentState.QUEUED: None,
    IntentState.SUBMITTING: None,
    IntentState.ENTRY_FILLED: SignalState.FILLED,
    IntentState.STOP_PLACED: None,          # 선배치 경로에서는 체결 전일 수 있다 → filled_qty로 판단(아래)
    IntentState.STOP_VERIFIED: SignalState.FILLED,
    IntentState.EXITING: SignalState.FILLED,
    IntentState.CLOSED: SignalState.CLOSED,
    IntentState.REJECTED: SignalState.SKIPPED,
    IntentState.NOT_FILLED: SignalState.SKIPPED,
    IntentState.FAILED_FLATTENED: SignalState.CLOSED,
    IntentState.HALTED: None,
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """테이블·트리거 생성(멱등). 이미 있던 order_events가 있는데 보호 트리거가 빠졌으면 DbError(변조 의심)."""
    existed = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'order_events'").fetchone() is not None
    if existed:
        have = {r[0]: _norm_sql(r[1]) for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")}
        missing = [t for t in PROTECT_TRIGGERS if t not in have]
        if missing:
            raise db.DbError(f"주문 기록 보호 트리거가 없다(변조 의심, 시작 거부): {missing}")
        exp = _expected_trigger_sql()
        altered = [t for t in PROTECT_TRIGGERS if have[t] != exp.get(t)]
        if altered:
            raise db.DbError(f"주문 기록 보호 트리거 본문이 다르다(변조 의심, 시작 거부): {altered}")
    with db.transaction(conn):
        for stmt in db._split_sql(SCHEMA):
            conn.execute(stmt)


_EXPECTED_TRIGGER_SQL: dict[str, str] | None = None
APPEND_ONLY_TABLES = ("order_halts", "order_events", "order_halt_releases")


def _norm_sql(sql: str | None) -> str:
    return " ".join(str(sql or "").split()).lower()


def _expected_trigger_sql() -> dict[str, str]:
    """보호 트리거의 기대 SQL(sqlite_master 저장 형태) — 빈 메모리 DB에 SCHEMA를 만들어 읽는다."""
    global _EXPECTED_TRIGGER_SQL
    if _EXPECTED_TRIGGER_SQL is None:
        m = sqlite3.connect(":memory:")
        try:
            m.execute("CREATE TABLE signals(signal_id TEXT PRIMARY KEY)")
            for stmt in db._split_sql(SCHEMA):
                m.execute(stmt)
            _EXPECTED_TRIGGER_SQL = {r[0]: _norm_sql(r[1]) for r in m.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'") if r[0] in PROTECT_TRIGGERS}
        finally:
            m.close()
    return _EXPECTED_TRIGGER_SQL


def integrity_problems(conn: sqlite3.Connection) -> list[str]:
    """추가 전용 표의 변조 흔적(SEC-02). 빈 목록이면 이상 없음. 각 항목은 문제의 '서명'(같은 문제면 같은 문자열).

    - 보호 트리거가 없거나 SQL 본문이 기대와 다름(이름만 보지 않는다)
    - 추가 전용 표(AUTOINCREMENT)는 지우는 경로가 없으므로 행 수 == 최대 id == sqlite_sequence여야 한다.
      다르면 누군가 행을 지웠다(트리거를 지웠다 다시 만든 경우 포함). 서명에 빠진 개수를 넣어, 더 지우면 새 문제가 된다.
    B는 매 루프 이것을 보고 문제가 있으면 T0(ORDER_ERROR, why=db_integrity)를 건다. B 원장(ledger)은 별도로 T0를 보관한다.
    """
    out: list[str] = []
    exp = _expected_trigger_sql()
    have = {r[0]: _norm_sql(r[1]) for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")}
    for name in PROTECT_TRIGGERS:
        if name not in have:
            out.append(f"trigger_missing:{name}")
        elif have[name] != exp.get(name):
            out.append(f"trigger_altered:{name}")
    try:
        seqs = {r[0]: int(r[1]) for r in conn.execute("SELECT name, seq FROM sqlite_sequence")}
    except sqlite3.Error:
        seqs = {}
    for table in APPEND_ONLY_TABLES:
        pk = "halt_id" if table == "order_halts" else "event_id" if table == "order_events" else "release_id"
        n, mx = conn.execute(f"SELECT COUNT(*), COALESCE(MAX({pk}), 0) FROM {table}").fetchone()
        seq = seqs.get(table, 0)
        if not (int(n) == int(mx) == int(seq)):
            out.append(f"{table}_gap:{int(max(mx, seq)) - int(n)}")
    return out


def _dumps(payload: Mapping[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(db._redact(dict(payload)), ensure_ascii=False, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# A 쪽 (프로세스 A: engine) — 키 없이 DB만
# ---------------------------------------------------------------------------


def enqueue(conn: sqlite3.Connection, *, signal_id: str, now_ms: int) -> int | None:
    """APPROVED 신호의 주문 의도를 QUEUED로 넣는다. A가 [확인] 전이와 **같은 트랜잭션**에서 부른다.

    신호가 없거나 APPROVED·롱이 아니면 ValueError(호출 코드 버그). 이미 있으면 None(멱등).
    """
    with db.transaction(conn):
        sig = conn.execute("SELECT * FROM signals WHERE signal_id = ?", (signal_id,)).fetchone()
        if sig is None or sig["state"] != SignalState.APPROVED.value or int(sig["side"]) != 1 \
                or sig["approved_ms"] is None:
            raise ValueError("APPROVED 롱 신호만 큐에 넣을 수 있다")
        if conn.execute("SELECT 1 FROM order_intents WHERE signal_id = ?", (signal_id,)).fetchone():
            return None
        cur = conn.execute(
            "INSERT INTO order_intents(signal_id, symbol, side, subsystem_n, atr20, approved_ms, state,"
            " created_ms, updated_ms) VALUES (?, ?, 1, ?, ?, ?, 'QUEUED', ?, ?)",
            (signal_id, SYMBOL, int(sig["subsystem_n"]), float(sig["atr20"]), int(sig["approved_ms"]),
             int(now_ms), int(now_ms)))
        iid = int(cur.lastrowid)
        db.audit(conn, ts_ms=now_ms, actor="ENGINE", event=AuditEvent.STATE_TRANSITION, entity_type="order_intent",
                 entity_id=iid, to_state=IntentState.QUEUED.value, payload={"signal_id": signal_id})
        return iid


def cancel_queued(conn: sqlite3.Connection, signal_id: str, *, now_ms: int, reason: str,
                  actor: str = "ENGINE") -> bool:
    """아직 B가 가져가지 않은(QUEUED) 의도를 REJECTED로(A의 /pause 등). 이미 가져갔으면 False — 그때는 신호를
    SKIPPED로 바꾸지 말 것(B가 거래소 사실로 끝낸다)."""
    with db.transaction(conn):
        row = intent_for_signal(conn, signal_id)
        if row is None:
            return False
        return transition(conn, int(row["intent_id"]), IntentState.QUEUED, IntentState.REJECTED, now_ms=now_ms,
                          reason=reason, actor=actor)


def request_exit(conn: sqlite3.Connection, signal_id: str, *, exit_signal_close_ms: int, exit_due_ms: int,
                 now_ms: int) -> bool:
    """추세 청산 요청(A의 일일 사이클 EXIT 판단). 보유 중(ENTRY_FILLED·STOP_PLACED·STOP_VERIFIED)이고 아직 요청이
    없을 때 한 번만 True. 청산은 위험을 줄이는 방향이라 B는 이 값을 믿고 실행한다(시각만 검사)."""
    with db.transaction(conn):
        cur = conn.execute(
            "UPDATE order_intents SET exit_signal_close_ms = ?, exit_due_ms = ?, exit_requested_ms = ?, updated_ms = ?"
            " WHERE signal_id = ? AND exit_due_ms IS NULL"
            " AND state IN ('ENTRY_FILLED', 'STOP_PLACED', 'STOP_VERIFIED')",
            (int(exit_signal_close_ms), int(exit_due_ms), int(now_ms), int(now_ms), signal_id))
        if cur.rowcount != 1:
            return False
        db.audit(conn, ts_ms=now_ms, actor="ENGINE", event=AuditEvent.STATE_TRANSITION, entity_type="order_intent",
                 entity_id=signal_id, payload={"exit_requested": True, "exit_due_ms": int(exit_due_ms)})
        return True


# ---------------------------------------------------------------------------
# B 쪽 (프로세스 B: gateway·reconcile·worker)
# ---------------------------------------------------------------------------


def get_intent(conn: sqlite3.Connection, intent_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM order_intents WHERE intent_id = ?", (int(intent_id),)).fetchone()


def intent_for_signal(conn: sqlite3.Connection, signal_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM order_intents WHERE signal_id = ?", (signal_id,)).fetchone()


def intents_in_states(conn: sqlite3.Connection, states: Iterable[IntentState | str]) -> list[sqlite3.Row]:
    vals = [IntentState(s).value for s in states]
    if not vals:
        return []
    ph = ",".join("?" for _ in vals)
    return list(conn.execute(f"SELECT * FROM order_intents WHERE state IN ({ph}) ORDER BY intent_id", vals))


def live_intent(conn: sqlite3.Connection) -> sqlite3.Row | None:
    rows = intents_in_states(conn, INTENT_LIVE)
    return rows[0] if rows else None


def claim_next(conn: sqlite3.Connection, *, now_ms: int) -> sqlite3.Row | None:
    """가장 오래된 QUEUED 하나를 SUBMITTING으로 원자적으로 가져간다. 노출 중인 의도가 있으면 None(동시 1개)."""
    with db.transaction(conn):
        if live_intent(conn) is not None:
            return None
        row = conn.execute("SELECT intent_id FROM order_intents WHERE state = 'QUEUED'"
                           " ORDER BY approved_ms, intent_id LIMIT 1").fetchone()
        if row is None:
            return None
        ok = transition(conn, int(row["intent_id"]), IntentState.QUEUED, IntentState.SUBMITTING, now_ms=now_ms,
                        reason="claimed", fields={"claimed_ms": int(now_ms)})
        return get_intent(conn, int(row["intent_id"])) if ok else None


def _sync_signal(conn: sqlite3.Connection, row: sqlite3.Row, new: IntentState, *, now_ms: int,
                 reason: str | None) -> None:
    target = _SIGNAL_TARGET[new]
    if new is IntentState.STOP_PLACED and row["filled_qty"] is not None and float(row["filled_qty"]) > 0:
        target = SignalState.FILLED
    if target is None:
        return
    sid = row["signal_id"]
    sig = conn.execute("SELECT state FROM signals WHERE signal_id = ?", (sid,)).fetchone()
    cur = SignalState(sig["state"]) if sig is not None else None
    if cur == target:
        return
    if target is SignalState.FILLED:
        path = [SignalState.FILLED] if cur is SignalState.APPROVED else None
    elif target is SignalState.CLOSED:
        path = ([SignalState.FILLED, SignalState.CLOSED] if cur is SignalState.APPROVED
                else [SignalState.CLOSED] if cur is SignalState.FILLED else None)
    else:  # SKIPPED
        path = [SignalState.SKIPPED] if cur is SignalState.APPROVED else None
    if path is None:
        # 거래소 사실이 우선이다: 의도 전이는 되돌리지 않고 불일치만 기록한다(A가 먼저 바꿨거나 위조).
        db.audit(conn, ts_ms=now_ms, actor=ORDER_ACTOR, event=AuditEvent.ALERT, entity_type="signal", entity_id=sid,
                 payload={"reason": "signal_state_mismatch", "signal_state": None if cur is None else cur.value,
                          "intent_state": new.value})
        return
    src = cur
    for dst in path:
        db.transition_signal(conn, sid, src, dst, now_ms=now_ms, actor=ORDER_ACTOR,
                             reason=f"order:{reason or new.value.lower()}"[:120])
        src = dst


def transition(conn: sqlite3.Connection, intent_id: int, expected: IntentState | str | Iterable[IntentState | str],
               new: IntentState | str, *, now_ms: int, reason: str | None = None,
               fields: Mapping[str, Any] | None = None, actor: str = ORDER_ACTOR,
               payload: Mapping[str, Any] | None = None) -> bool:
    """원자적 의도 전이 + 신호 동기화 + 감사. 허용되지 않은 조합·열은 ValueError(코드 버그)."""
    new_state = IntentState(new)
    exp = (IntentState(expected),) if isinstance(expected, (str, IntentState)) else tuple(
        IntentState(s) for s in expected)
    for s in exp:
        if not can_intent_transition(s, new_state):
            raise ValueError(f"허용되지 않은 의도 전이: {s.value} → {new_state.value}")
    extra = dict(fields or {})
    bad = set(extra) - INTENT_MUTABLE_FIELDS
    if bad:
        raise ValueError(f"바꿀 수 없는 열: {sorted(bad)}")
    sets = ["state = ?", "state_reason = ?", "state_version = state_version + 1", "updated_ms = ?"]
    params: list[Any] = [new_state.value, reason, int(now_ms)]
    for k in sorted(extra):
        sets.append(f"{k} = ?")
        params.append(extra[k])
    ph = ",".join("?" for _ in exp)
    with db.transaction(conn):
        before = get_intent(conn, intent_id)
        if before is None:
            return False
        cur = conn.execute(f"UPDATE order_intents SET {', '.join(sets)} WHERE intent_id = ? AND state IN ({ph})",
                           (*params, int(intent_id), *(s.value for s in exp)))
        if cur.rowcount != 1:
            return False
        after = get_intent(conn, intent_id)
        db.audit(conn, ts_ms=now_ms, actor=actor, event=AuditEvent.STATE_TRANSITION, entity_type="order_intent",
                 entity_id=int(intent_id), from_state=before["state"], to_state=new_state.value,
                 payload=dict(reason=reason, signal_id=before["signal_id"], **({"fields": extra} if extra else {}),
                              **(dict(payload) if payload else {})))
        _sync_signal(conn, after, new_state, now_ms=now_ms, reason=reason)
    return True


def update_fields(conn: sqlite3.Connection, intent_id: int, expected: IntentState | str, fields: Mapping[str, Any], *,
                  now_ms: int) -> bool:
    """상태는 그대로 두고 열만 기록(예: 진입 전송 직전 entry_sent_ms). 상태가 기대값이 아니면 False."""
    extra = dict(fields)
    bad = set(extra) - INTENT_MUTABLE_FIELDS
    if bad or not extra:
        raise ValueError(f"바꿀 수 없는 열: {sorted(bad)}")
    sets = [f"{k} = ?" for k in sorted(extra)] + ["updated_ms = ?"]
    params = [extra[k] for k in sorted(extra)] + [int(now_ms)]
    with db.transaction(conn):
        cur = conn.execute(f"UPDATE order_intents SET {', '.join(sets)} WHERE intent_id = ? AND state = ?",
                           (*params, int(intent_id), IntentState(expected).value))
        return cur.rowcount == 1


def add_event(conn: sqlite3.Connection, *, intent_id: int | None, kind: str, now_ms: int,
              client_id: str | None = None, payload: Mapping[str, Any] | None = None) -> int:
    """거래소 요청·응답·오류·조회·방화벽 판정 기록(추가 전용). payload에 서명·키·전체 URL 금지(가림 이중 방어)."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"모르는 이벤트 종류: {kind}")
    cur = conn.execute("INSERT INTO order_events(ts_ms, intent_id, kind, client_id, payload_json) VALUES (?,?,?,?,?)",
                       (int(now_ms), intent_id, kind, client_id, _dumps(payload)))
    return int(cur.lastrowid)


def events_for(conn: sqlite3.Connection, intent_id: int) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM order_events WHERE intent_id = ? ORDER BY event_id", (int(intent_id),)))


# --- 킬 스위치 T0 ---


def raise_halt(conn: sqlite3.Connection, *, reason: HaltReason | str, now_ms: int, intent_id: int | None = None,
               detail: Mapping[str, Any] | None = None, alert_text: str | None = None) -> int:
    """T0 기록(추가 전용) + 감사 ALERT + 텔레그램 보낼 경고(outbox, A가 전송). 반환 halt_id."""
    r = HaltReason(reason)
    with db.transaction(conn):
        cur = conn.execute("INSERT INTO order_halts(ts_ms, level, reason, intent_id, detail_json) VALUES (?,?,?,?,?)",
                           (int(now_ms), "T0", r.value, intent_id, _dumps(detail)))
        hid = int(cur.lastrowid)
        db.audit(conn, ts_ms=now_ms, actor=ORDER_ACTOR, event=AuditEvent.ALERT, entity_type="order_halt",
                 entity_id=hid, payload={"reason": r.value, "intent_id": intent_id, **(dict(detail) if detail else {})})
        text = alert_text or (f"[TESTNET] 킬 스위치 T0 #{hid}: {r.value} — 신규 진입 차단, 보유 손절 유지. "
                              "해제는 서버 제어 파일에서만(RUNBOOK)")
        db.outbox_add(conn, kind="alert", text=text, signal_id=None, edit_message_id=None, now_ms=now_ms)
        return hid


def halts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM order_halts ORDER BY halt_id"))


def active_halt_ids(conn: sqlite3.Connection, released: Iterable[int]) -> list[int]:
    """풀리지 않은 T0 id 목록. 해제 판정은 **제어 파일의 released 집합만** 쓴다(DB 해제 행은 기록일 뿐)."""
    rel = {int(x) for x in released}
    return [int(r["halt_id"]) for r in halts(conn) if int(r["halt_id"]) not in rel]


def record_release(conn: sqlite3.Connection, halt_id: int, *, control_ref: str, now_ms: int) -> bool:
    """제어 파일에서 해제된 halt를 기록(처음 한 번만 True)."""
    with db.transaction(conn):
        if conn.execute("SELECT 1 FROM order_halts WHERE halt_id = ?", (int(halt_id),)).fetchone() is None:
            return False
        if conn.execute("SELECT 1 FROM order_halt_releases WHERE halt_id = ?", (int(halt_id),)).fetchone():
            return False
        conn.execute("INSERT INTO order_halt_releases(halt_id, ts_ms, control_ref) VALUES (?,?,?)",
                     (int(halt_id), int(now_ms), str(control_ref)[:200]))
        db.audit(conn, ts_ms=now_ms, actor="OPERATOR", event=AuditEvent.FLAG_CHANGED, entity_type="order_halt",
                 entity_id=int(halt_id), payload={"released": True, "control_ref": str(control_ref)[:200]})
        return True


def notify(conn: sqlite3.Connection, text: str, *, now_ms: int, signal_id: str | None = None,
           kind: str = "info") -> int:
    """B → 텔레그램 알림(outbox 경유, A가 보낸다). B는 텔레그램 토큰이 없다."""
    if not text.startswith("[TESTNET]"):
        text = "[TESTNET] " + text
    return db.outbox_add(conn, kind=kind, text=text, signal_id=signal_id, edit_message_id=None, now_ms=now_ms)


# --- 런타임 표시값 ---


def set_runtime(conn: sqlite3.Connection, key: str, value: Any, *, now_ms: int) -> None:
    conn.execute("INSERT INTO order_runtime(key, value, updated_ms) VALUES (?,?,?)"
                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_ms = excluded.updated_ms",
                 (key, str(value), int(now_ms)))


def get_runtime(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM order_runtime WHERE key = ?", (key,)).fetchone()
