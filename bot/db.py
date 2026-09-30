"""SQLite(WAL) 저장소: 스키마 + 원자적 상태 전이 — 설계 담당 소유 (bot/DESIGN.md §4, §8).

원칙
- DB 파일 하나(모드마다 따로: paper.sqlite3 / replay.sqlite3). db_meta.mode로 다른 모드 DB를 여는 실수를 막는다.
- 모든 시각은 UTC 정수 ms(열 이름 *_ms). 가격은 REAL(백테스트 float와 같은 값을 그대로 저장해 대조가 정확하도록).
- 상태 전이는 전부 `UPDATE … WHERE id=? AND state IN (기대값)` 한 번으로 한다. 영향 행이 1이면 성공, 0이면
  누군가 먼저 바꿨거나(중복 클릭·경쟁) 상태가 다르다 → False (멱등). 허용 전이는 types.SIGNAL_TRANSITIONS만 기준.
- 복합 동작(체결 = 신호 APPROVED→FILLED + 포지션 생성 + 원장 ENTRY + 감사)은 한 트랜잭션(BEGIN IMMEDIATE)으로 묶는다.
- audit_log·config_snapshots는 추가 전용: UPDATE·DELETE는 트리거가 막는다.
- 연결은 autocommit(isolation_level=None)이고 쓰기는 transaction()으로만 묶는다. 중첩 호출은 바깥 트랜잭션에 합류한다.
- 감사 로그 payload에는 비밀을 넣지 않는다. 방어적으로 이름이 token/secret/api_key/password인 키는 '***'로 바꾼다.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from bot.types import (
    ACTIVE_STATES,
    Actor,
    AnalystResult,
    AuditEvent,
    ExitReason,
    Mode,
    PositionState,
    SignalState,
    TradeKind,
    can_transition,
)

SCHEMA_VERSION = 1
_STATES_SQL = ",".join(f"'{s.value}'" for s in SignalState)
_REDACT_KEY_PARTS = ("token", "secret", "api_key", "apikey", "password", "authorization", "ping_url")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS db_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    analysis_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_day     TEXT NOT NULL,                 -- 신호 일봉 날짜 'YYYY-MM-DD'(UTC 시작일)
    created_ms     INTEGER NOT NULL,
    prompt_version TEXT NOT NULL,
    model          TEXT NOT NULL,
    status         TEXT NOT NULL,                 -- ok|disabled|timeout|error|refusal|schema_invalid|truncated
    ok             INTEGER NOT NULL CHECK (ok IN (0, 1)),
    opinion        TEXT CHECK (opinion IS NULL OR opinion IN ('approve', 'pass')),
    input_json     TEXT NOT NULL,                 -- 보낸 수치 JSON 그대로
    output_json    TEXT,                          -- 검증 통과한 구조화 출력
    raw_response   TEXT,                          -- 원본 응답 직렬화
    stop_reason    TEXT,
    error          TEXT,
    latency_ms     INTEGER
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id            TEXT PRIMARY KEY CHECK (length(signal_id) = 16),
    mode                 TEXT NOT NULL CHECK (mode IN ('replay', 'paper')),
    strategy_key         TEXT NOT NULL,
    spec_version         TEXT NOT NULL,
    subsystem_n          INTEGER NOT NULL CHECK (subsystem_n IN (20, 55, 100)),
    side                 INTEGER NOT NULL CHECK (side IN (1, -1)),
    signal_day           TEXT NOT NULL,           -- 신호 일봉의 UTC 날짜(봉 시작일)
    signal_close_ms      INTEGER NOT NULL,        -- 일봉 마감 = 다음 날 00:00 UTC
    decision_ms          INTEGER NOT NULL,        -- 마감 + 60초
    expires_ms           INTEGER NOT NULL,        -- 판단 + 승인 창(2시간)
    close                REAL NOT NULL,
    entry_level          REAL NOT NULL,           -- U_N
    exit_level           REAL NOT NULL,           -- D_M
    atr20                REAL NOT NULL CHECK (atr20 > 0),
    state                TEXT NOT NULL CHECK (state IN ({_STATES_SQL})),
    state_reason         TEXT,
    state_version        INTEGER NOT NULL DEFAULT 0,
    card_sent_ms         INTEGER,
    tg_message_id        INTEGER,
    confirm_requested_ms INTEGER,
    confirm_expires_ms   INTEGER,
    approved_ms          INTEGER,                 -- [확인] 클릭 시각 (모의 체결 기준)
    approval_latency_ms  INTEGER,                 -- 확인 시각 − 판단 시각
    analysis_id          INTEGER REFERENCES analyses(analysis_id),
    created_ms           INTEGER NOT NULL,
    updated_ms           INTEGER NOT NULL,
    UNIQUE (mode, subsystem_n, side, signal_close_ms)
);
CREATE INDEX IF NOT EXISTS signals_state ON signals(state);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id         TEXT NOT NULL REFERENCES signals(signal_id),
    action            TEXT NOT NULL CHECK (action IN ('A', 'C', 'X', 'P', 'D')),
    callback_query_id TEXT NOT NULL UNIQUE,       -- 같은 클릭 재전송 차단
    update_id         INTEGER,
    from_user_id      INTEGER NOT NULL,
    chat_id           INTEGER NOT NULL,
    message_id        INTEGER,
    clicked_ms        INTEGER NOT NULL,
    result            TEXT NOT NULL,              -- ACCEPTED | STALE(상태 불일치·만료) | ...
    latency_ms        INTEGER                     -- 클릭 − 판단 시각
);

CREATE TABLE IF NOT EXISTS paper_positions (
    position_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id           TEXT NOT NULL UNIQUE REFERENCES signals(signal_id),
    subsystem_n         INTEGER NOT NULL CHECK (subsystem_n IN (20, 55, 100)),
    side                INTEGER NOT NULL CHECK (side IN (1, -1)),
    state               TEXT NOT NULL CHECK (state IN ('OPEN', 'CLOSED')),
    active_from_ms      INTEGER NOT NULL,         -- 확인 시각(펀딩 창 시작 = min(체결 봉, 이 값))
    entry_ms            INTEGER NOT NULL,         -- 체결 1분봉 시작
    entry_price         REAL NOT NULL CHECK (entry_price > 0),
    qty                 REAL NOT NULL CHECK (qty > 0),
    stop                REAL NOT NULL CHECK (stop > 0),
    risk_per_unit       REAL NOT NULL CHECK (risk_per_unit > 0),
    entry_fee           REAL NOT NULL,            -- 단위당
    entry_slippage      REAL NOT NULL,            -- 단위당
    last_bar_close_ms   INTEGER,                  -- 감시 커서: 처리한 마지막 1분봉 끝
    exit_signal_close_ms INTEGER,                 -- 추세 청산 신호 일봉 마감
    exit_due_ms         INTEGER,                  -- 추세 청산 시각 = 청산 신호 판단 + 30분
    exit_ms             INTEGER,                  -- 청산 1분봉 시작
    exit_bar_close_ms   INTEGER,
    exit_price          REAL,
    exit_reason         TEXT CHECK (exit_reason IS NULL OR exit_reason IN ('stop', 'trend')),
    fees                REAL,                     -- 단위당 (진입+청산)
    slippage            REAL,                     -- 단위당 (진입+청산)
    funding             REAL NOT NULL DEFAULT 0,  -- 단위당 누적 (양수 = 지불)
    gross_pnl           REAL,                     -- 단위당
    net_pnl             REAL,                     -- 단위당
    r_multiple          REAL,
    pnl_usdt            REAL,                     -- net_pnl × qty
    state_version       INTEGER NOT NULL DEFAULT 0,
    created_ms          INTEGER NOT NULL,
    updated_ms          INTEGER NOT NULL,
    CHECK ((state = 'OPEN' AND exit_ms IS NULL) OR (state = 'CLOSED' AND exit_ms IS NOT NULL))
);
-- 하위 시스템당 열린 포지션 최대 1개 (TREND_SPEC §1)
CREATE UNIQUE INDEX IF NOT EXISTS paper_positions_one_open ON paper_positions(subsystem_n) WHERE state = 'OPEN';

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id  INTEGER NOT NULL REFERENCES paper_positions(position_id),
    kind         TEXT NOT NULL CHECK (kind IN ('ENTRY', 'EXIT', 'FUNDING')),
    ts_ms        INTEGER NOT NULL,        -- ENTRY/EXIT = 체결 봉 시작, FUNDING = 펀딩 시각
    price        REAL NOT NULL,
    qty          REAL NOT NULL,
    fee          REAL NOT NULL DEFAULT 0,       -- 단위당
    slippage     REAL NOT NULL DEFAULT 0,       -- 단위당
    funding      REAL NOT NULL DEFAULT 0,       -- 단위당 (FUNDING 행)
    rate         REAL,                          -- FUNDING 행의 펀딩비
    reason       TEXT,
    created_ms   INTEGER NOT NULL,
    UNIQUE (position_id, kind, ts_ms)
);
CREATE UNIQUE INDEX IF NOT EXISTS paper_trades_one_entry_exit ON paper_trades(position_id, kind)
    WHERE kind IN ('ENTRY', 'EXIT');

CREATE TABLE IF NOT EXISTS audit_log (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,
    actor        TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    entity_type  TEXT,
    entity_id    TEXT,
    from_state   TEXT,
    to_state     TEXT,
    payload_json TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
-- INSERT OR REPLACE / REPLACE INTO 로 기존 번호를 덮어쓰는 것 차단(REPLACE의 삭제는 recursive_triggers가 꺼져 있으면
-- BEFORE DELETE 트리거를 부르지 않는다). connect()가 recursive_triggers도 켜 두지만 이 트리거가 단독으로 막는다.
CREATE TRIGGER IF NOT EXISTS audit_log_no_replace BEFORE INSERT ON audit_log
WHEN NEW.seq IS NOT NULL AND EXISTS (SELECT 1 FROM audit_log WHERE seq = NEW.seq)
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE TABLE IF NOT EXISTS config_snapshots (
    snapshot_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,
    fingerprint  TEXT NOT NULL,
    bot_version  TEXT NOT NULL,
    config_json  TEXT NOT NULL             -- BotConfig.redacted_dict() (비밀 값 없음)
);
CREATE TRIGGER IF NOT EXISTS config_snapshots_no_update BEFORE UPDATE ON config_snapshots
BEGIN SELECT RAISE(ABORT, 'config_snapshots is append-only'); END;
CREATE TRIGGER IF NOT EXISTS config_snapshots_no_delete BEFORE DELETE ON config_snapshots
BEGIN SELECT RAISE(ABORT, 'config_snapshots is append-only'); END;
CREATE TRIGGER IF NOT EXISTS config_snapshots_no_replace BEFORE INSERT ON config_snapshots
WHEN NEW.snapshot_id IS NOT NULL AND EXISTS (SELECT 1 FROM config_snapshots WHERE snapshot_id = NEW.snapshot_id)
BEGIN SELECT RAISE(ABORT, 'config_snapshots is append-only'); END;

-- 전송 실패한 카드 아닌 메시지(체결·청산·경고·만료·리포트) 재시도 보관함(OPS-3). 카드는 signals NEW 상태로 재전송한다.
CREATE TABLE IF NOT EXISTS outbox (
    outbox_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,
    text            TEXT NOT NULL,
    signal_id       TEXT,
    edit_message_id INTEGER,
    created_ms      INTEGER NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 1,
    last_try_ms     INTEGER,
    sent_ms         INTEGER,
    dropped_ms      INTEGER,                 -- 더 새 리포트로 대체·상한 초과로 포기
    drop_reason     TEXT
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(outbox_id) WHERE sent_ms IS NULL AND dropped_ms IS NULL;

CREATE TABLE IF NOT EXISTS runtime_flags (
    key        TEXT PRIMARY KEY CHECK (key IN ('paused')),
    value      TEXT NOT NULL,
    updated_ms INTEGER NOT NULL,
    updated_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cycles (
    cycle_day   TEXT PRIMARY KEY,                -- 판단 날짜(UTC) 'YYYY-MM-DD'
    decision_ms INTEGER NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('RUNNING', 'DONE', 'FAILED')),
    started_ms  INTEGER NOT NULL,
    finished_ms INTEGER,
    note        TEXT
);
"""

SIGNAL_MUTABLE_FIELDS = frozenset({
    "card_sent_ms", "tg_message_id", "confirm_requested_ms", "confirm_expires_ms",
    "approved_ms", "approval_latency_ms", "analysis_id",
})


class DbError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 연결·스키마
# ---------------------------------------------------------------------------


# 추가 전용 보호 트리거(SEC-05). 이미 있던 DB에서 하나라도 없어졌으면 변조로 보고 시작을 거부한다.
PROTECT_TRIGGERS = ("audit_log_no_update", "audit_log_no_delete", "audit_log_no_replace",
                    "config_snapshots_no_update", "config_snapshots_no_delete", "config_snapshots_no_replace")


def _ensure_private_file(path: Path) -> None:
    """DB 파일이 없으면 0600으로 먼저 만든다(WAL/SHM은 프로세스 umask 077로 — main이 설정).

    이미 있는 파일은 권한을 검사한다(SEC-06, PV-09): 그룹·다른 사용자 권한이 있으면 DbError
    (복원한 백업을 0644로 둔 경우 등 — `chmod 600`으로 고친 뒤 다시 시작)."""
    if path.exists():
        st = path.stat()
        if st.st_mode & 0o077:
            raise DbError(f"DB 파일 권한이 너무 넓다(그룹·다른 사용자 권한 금지, chmod 600 필요): {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)


def connect(path: str | os.PathLike[str], *, mode: Mode, now_ms: int) -> sqlite3.Connection:
    """DB를 열고(없으면 0600으로 생성) 스키마를 적용한다. 다른 모드로 만든 DB면 DbError.

    path=':memory:'는 테스트용.
    """
    mode = Mode(mode)
    if str(path) != ":memory:":
        _ensure_private_file(Path(path))
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    if str(path) != ":memory:":
        jm = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(jm).lower() != "wal":
            conn.close()
            raise DbError(f"WAL 모드를 켤 수 없다: {jm}")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA trusted_schema = OFF")
    # REPLACE 충돌 처리의 행 삭제도 BEFORE DELETE 트리거를 거치게 한다(감사 로그 덮어쓰기 차단, V-1)
    conn.execute("PRAGMA recursive_triggers = ON")
    init_schema(conn, mode=mode, now_ms=now_ms)
    return conn


def check_integrity(conn: sqlite3.Connection) -> None:
    """이미 있던 DB의 감사 로그 무결성 검사(SEC-05, SECURITY §6.4 L1+). 문제면 DbError(시작 거부).

    - 추가 전용 트리거 6개(UPDATE·DELETE·REPLACE 차단)가 모두 있어야 한다(DROP TRIGGER 뒤 행 삭제 → 다시 열 때 조용히 재생성되는 것을 막는다).
    - audit_log 행 수 == sqlite_sequence의 마지막 seq (AUTOINCREMENT는 롤백된 삽입의 번호를 되돌리므로
      정상 운영에서는 빈 번호가 생기지 않는다. 행이 지워졌으면 수가 모자란다).
    해시 체인(L4)은 다음 단계(TESTNET 전)에 검토한다.
    """
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    missing = [t for t in PROTECT_TRIGGERS if t not in have]
    if missing:
        raise DbError(f"감사 로그 보호 트리거가 없다(변조 의심, 시작 거부): {missing} — RUNBOOK '감사 로그 변조 경고' 참고")
    n = int(conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'audit_log'").fetchone()
    last = int(row[0]) if row is not None else 0
    if n != last:
        raise DbError(f"감사 로그 행 수({n})가 마지막 번호({last})와 다르다(행 삭제 의심, 시작 거부)"
                      " — RUNBOOK '감사 로그 변조 경고' 참고")


def init_schema(conn: sqlite3.Connection, *, mode: Mode, now_ms: int) -> None:
    existed = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'db_meta'").fetchone()
    if existed is not None:
        check_integrity(conn)                      # 스키마(트리거) 재생성 전에 검사해야 흔적이 남는다
    with transaction(conn):
        for stmt in _split_sql(SCHEMA):
            conn.execute(stmt)
        meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM db_meta")}
        if not meta:
            conn.executemany("INSERT INTO db_meta(key, value) VALUES (?, ?)",
                             [("schema_version", str(SCHEMA_VERSION)), ("mode", Mode(mode).value),
                              ("created_ms", str(int(now_ms)))])
        else:
            if meta.get("mode") != Mode(mode).value:
                raise DbError(f"이 DB는 {meta.get('mode')} 모드용이다(요청: {Mode(mode).value})")
            if meta.get("schema_version") != str(SCHEMA_VERSION):
                raise DbError(f"스키마 버전 불일치: {meta.get('schema_version')} != {SCHEMA_VERSION}")


def _split_sql(script: str) -> list[str]:
    """스키마 스크립트를 문장 단위로 나눈다(트리거 BEGIN…END 안의 ';'는 유지)."""
    out: list[str] = []
    buf: list[str] = []
    for line in script.splitlines():
        stripped = line.split("--", 1)[0].rstrip()
        if not stripped.strip():
            continue
        buf.append(stripped)
        joined = "\n".join(buf)
        if joined.rstrip().endswith(";") and sqlite3.complete_statement(joined):
            out.append(joined)
            buf = []
    if buf and "\n".join(buf).strip():
        raise DbError("스키마 끝에 끝나지 않은 문장")
    return out


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE … COMMIT (예외면 ROLLBACK). 이미 트랜잭션 안이면 합류(바깥이 커밋·롤백)."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def db_mode(conn: sqlite3.Connection) -> Mode:
    row = conn.execute("SELECT value FROM db_meta WHERE key = 'mode'").fetchone()
    return Mode(row["value"])


# ---------------------------------------------------------------------------
# 감사 로그
# ---------------------------------------------------------------------------


def _redact(obj: Any) -> Any:
    """키 이름 기반 가림 + 값 패턴 가림(SEC-05: 무해한 키 아래 들어간 토큰·키 모양 문자열도 '***')."""
    if isinstance(obj, Mapping):
        return {str(k): ("***" if any(p in str(k).lower() for p in _REDACT_KEY_PARTS) else _redact(v))
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    if isinstance(obj, str):
        return _pattern_redact(obj)
    return obj


def _pattern_redact(text: str) -> str:
    from bot.config import RedactingFilter  # 순환 import 방지(늦은 import)

    global _PATTERN_FILTER
    if _PATTERN_FILTER is None:
        _PATTERN_FILTER = RedactingFilter()
    return _PATTERN_FILTER.redact(text)


_PATTERN_FILTER: Any = None


def _enum_value(v: Any) -> Any:
    return getattr(v, "value", v)


def audit(conn: sqlite3.Connection, *, ts_ms: int, actor: Actor | str, event: AuditEvent | str,
          entity_type: str | None = None, entity_id: str | int | None = None,
          from_state: str | None = None, to_state: str | None = None,
          payload: Mapping[str, Any] | None = None) -> int:
    """감사 로그 한 줄 추가(추가 전용). 반환 seq."""
    payload_json = None
    if payload is not None:
        payload_json = json.dumps(_redact(payload), ensure_ascii=False, sort_keys=True, default=str)
    cur = conn.execute(
        "INSERT INTO audit_log(ts_ms, actor, event_type, entity_type, entity_id, from_state, to_state, payload_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (int(ts_ms), str(_enum_value(actor)), str(_enum_value(event)), entity_type,
         None if entity_id is None else str(entity_id), _enum_value(from_state), _enum_value(to_state),
         payload_json))
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# 분석·설정 스냅샷
# ---------------------------------------------------------------------------


def insert_analysis(conn: sqlite3.Connection, result: AnalystResult, *, signal_day: str, now_ms: int) -> int:
    output = None
    if result.ok:
        output = json.dumps(dict(summary=result.summary, counter_evidence=list(result.counter_evidence),
                                 invalidation=result.invalidation, opinion=result.opinion,
                                 confidence_note=result.confidence_note), ensure_ascii=False, sort_keys=True)
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO analyses(signal_day, created_ms, prompt_version, model, status, ok, opinion, input_json,"
            " output_json, raw_response, stop_reason, error, latency_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (signal_day, int(now_ms), result.prompt_version, result.model, result.status, 1 if result.ok else 0,
             result.opinion if result.ok else None, result.input_json, output, result.raw_response,
             result.stop_reason, result.error, result.latency_ms))
        aid = int(cur.lastrowid)
        audit(conn, ts_ms=now_ms, actor=Actor.ANALYST, event=AuditEvent.CLAUDE_CALL, entity_type="analysis",
              entity_id=aid, payload=dict(status=result.status, ok=result.ok, model=result.model,
                                          prompt_version=result.prompt_version, latency_ms=result.latency_ms,
                                          stop_reason=result.stop_reason, error=result.error))
    return aid


def save_config_snapshot(conn: sqlite3.Connection, *, config_dict: Mapping[str, Any], fingerprint: str,
                         bot_version: str, now_ms: int) -> int:
    """설정 스냅샷(가린 dict) 저장. 직전 스냅샷과 지문이 같아도 시작 기록으로 한 줄 남긴다."""
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO config_snapshots(ts_ms, fingerprint, bot_version, config_json) VALUES (?, ?, ?, ?)",
            (int(now_ms), fingerprint, bot_version,
             json.dumps(_redact(dict(config_dict)), ensure_ascii=False, sort_keys=True, default=str)))
        sid = int(cur.lastrowid)
        audit(conn, ts_ms=now_ms, actor=Actor.SYSTEM, event=AuditEvent.CONFIG_LOADED, entity_type="config",
              entity_id=sid, payload=dict(fingerprint=fingerprint, bot_version=bot_version))
    return sid


# ---------------------------------------------------------------------------
# 신호
# ---------------------------------------------------------------------------


def insert_signal(conn: sqlite3.Connection, *, signal_id: str, mode: Mode, strategy_key: str, spec_version: str,
                  subsystem_n: int, side: int, signal_day: str, signal_close_ms: int, decision_ms: int,
                  expires_ms: int, close: float, entry_level: float, exit_level: float, atr20: float,
                  now_ms: int, analysis_id: int | None = None) -> bool:
    """NEW 신호 추가. 같은 (모드, N, 방향, 마감) 신호가 이미 있으면 False (사이클 재실행 멱등)."""
    with transaction(conn):
        try:
            conn.execute(
                "INSERT INTO signals(signal_id, mode, strategy_key, spec_version, subsystem_n, side, signal_day,"
                " signal_close_ms, decision_ms, expires_ms, close, entry_level, exit_level, atr20, state,"
                " analysis_id, created_ms, updated_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (signal_id, Mode(mode).value, strategy_key, spec_version, int(subsystem_n), int(side), signal_day,
                 int(signal_close_ms), int(decision_ms), int(expires_ms), float(close), float(entry_level),
                 float(exit_level), float(atr20), SignalState.NEW.value, analysis_id, int(now_ms), int(now_ms)))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc) and "signals.mode" in str(exc):
                return False
            raise
        audit(conn, ts_ms=now_ms, actor=Actor.ENGINE, event=AuditEvent.SIGNAL_CREATED, entity_type="signal",
              entity_id=signal_id, to_state=SignalState.NEW.value,
              payload=dict(n=int(subsystem_n), side=int(side), signal_day=signal_day, close=float(close),
                           entry_level=float(entry_level), exit_level=float(exit_level), atr20=float(atr20)))
    return True


def _states(expected: SignalState | str | Iterable[SignalState | str]) -> tuple[SignalState, ...]:
    if isinstance(expected, (SignalState, str)):
        return (SignalState(expected),)
    out = tuple(SignalState(s) for s in expected)
    if not out:
        raise ValueError("기대 상태가 비어 있다")
    return out


def transition_signal(conn: sqlite3.Connection, signal_id: str,
                      expected: SignalState | str | Iterable[SignalState | str], new: SignalState | str, *,
                      now_ms: int, actor: Actor | str, reason: str | None = None,
                      fields: Mapping[str, Any] | None = None, payload: Mapping[str, Any] | None = None) -> bool:
    """원자적 상태 전이. 성공이면 True(감사 로그 한 줄), 상태가 기대값이 아니면 False(아무것도 안 바뀜).

    - 허용되지 않은 (기대 → 새) 조합은 호출 코드의 버그이므로 ValueError.
    - fields: 함께 기록할 열(SIGNAL_MUTABLE_FIELDS만). state_version은 1 증가.
    """
    new_state = SignalState(new)
    exp = _states(expected)
    for s in exp:
        if not can_transition(s, new_state):
            raise ValueError(f"허용되지 않은 전이: {s.value} → {new_state.value}")
    extra = dict(fields or {})
    bad = set(extra) - SIGNAL_MUTABLE_FIELDS
    if bad:
        raise ValueError(f"바꿀 수 없는 열: {sorted(bad)}")
    sets = ["state = ?", "state_reason = ?", "state_version = state_version + 1", "updated_ms = ?"]
    params: list[Any] = [new_state.value, reason, int(now_ms)]
    for k in sorted(extra):
        sets.append(f"{k} = ?")
        params.append(extra[k])
    placeholders = ",".join("?" for _ in exp)
    with transaction(conn):
        row = conn.execute("SELECT state FROM signals WHERE signal_id = ?", (signal_id,)).fetchone()
        if row is None:
            return False
        cur = conn.execute(
            f"UPDATE signals SET {', '.join(sets)} WHERE signal_id = ? AND state IN ({placeholders})",
            (*params, signal_id, *(s.value for s in exp)))
        if cur.rowcount != 1:
            return False
        audit(conn, ts_ms=now_ms, actor=actor, event=AuditEvent.STATE_TRANSITION, entity_type="signal",
              entity_id=signal_id, from_state=row["state"], to_state=new_state.value,
              payload=dict(reason=reason, **({"fields": extra} if extra else {}), **(dict(payload) if payload else {})))
    return True


def get_signal(conn: sqlite3.Connection, signal_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM signals WHERE signal_id = ?", (signal_id,)).fetchone()


def signals_in_states(conn: sqlite3.Connection, states: Iterable[SignalState | str]) -> list[sqlite3.Row]:
    st = [SignalState(s).value for s in states]
    if not st:
        return []
    q = f"SELECT * FROM signals WHERE state IN ({','.join('?' for _ in st)}) ORDER BY decision_ms, subsystem_n"
    return list(conn.execute(q, st))


def active_signal_for_subsystem(conn: sqlite3.Connection, subsystem_n: int) -> sqlite3.Row | None:
    """하위 시스템 N의 진행 중 신호(NEW~FILLED). 있으면 그 하위 시스템은 새 진입 신호를 만들지 않는다."""
    st = [s.value for s in ACTIVE_STATES]
    return conn.execute(
        f"SELECT * FROM signals WHERE subsystem_n = ? AND state IN ({','.join('?' for _ in st)})"
        " ORDER BY decision_ms DESC LIMIT 1", (int(subsystem_n), *st)).fetchone()


# ---------------------------------------------------------------------------
# 버튼 기록
# ---------------------------------------------------------------------------


def record_button(conn: sqlite3.Connection, *, signal_id: str, action: str, callback_query_id: str,
                  update_id: int | None, from_user_id: int, chat_id: int, message_id: int | None,
                  clicked_ms: int, result: str, latency_ms: int | None = None) -> bool:
    """허용된 사용자의 클릭 한 건. 같은 callback_query_id가 이미 있으면 False(재전송·중복)."""
    with transaction(conn):
        try:
            conn.execute(
                "INSERT INTO approvals(signal_id, action, callback_query_id, update_id, from_user_id, chat_id,"
                " message_id, clicked_ms, result, latency_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (signal_id, action, str(callback_query_id), update_id, int(from_user_id), int(chat_id), message_id,
                 int(clicked_ms), result, latency_ms))
        except sqlite3.IntegrityError as exc:
            if "callback_query_id" in str(exc):
                return False
            raise
        audit(conn, ts_ms=clicked_ms, actor=Actor.TELEGRAM_USER, event=AuditEvent.BUTTON, entity_type="signal",
              entity_id=signal_id, payload=dict(action=action, result=result, update_id=update_id,
                                                callback_query_id=str(callback_query_id), latency_ms=latency_ms))
    return True


# ---------------------------------------------------------------------------
# 모의 포지션
# ---------------------------------------------------------------------------


def open_position(conn: sqlite3.Connection, *, signal_id: str, entry_ms: int, entry_price: float, qty: float,
                  stop: float, risk_per_unit: float, entry_fee: float, entry_slippage: float,
                  active_from_ms: int, now_ms: int) -> int | None:
    """모의 체결(한 트랜잭션): 신호 APPROVED→FILLED + 포지션 OPEN + 원장 ENTRY + 감사.

    신호가 APPROVED가 아니거나 그 하위 시스템에 이미 열린 포지션이 있으면 전부 되돌리고 None.
    """
    with transaction(conn):
        sig = get_signal(conn, signal_id)
        if sig is None or sig["state"] != SignalState.APPROVED.value:
            return None
        if open_position_for_subsystem(conn, sig["subsystem_n"]) is not None:
            return None
        if not transition_signal(conn, signal_id, SignalState.APPROVED, SignalState.FILLED, now_ms=now_ms,
                                 actor=Actor.PAPER, reason="paper_fill"):
            return None
        cur = conn.execute(
            "INSERT INTO paper_positions(signal_id, subsystem_n, side, state, active_from_ms, entry_ms, entry_price,"
            " qty, stop, risk_per_unit, entry_fee, entry_slippage, created_ms, updated_ms)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (signal_id, sig["subsystem_n"], sig["side"], PositionState.OPEN.value, int(active_from_ms),
             int(entry_ms), float(entry_price), float(qty), float(stop), float(risk_per_unit), float(entry_fee),
             float(entry_slippage), int(now_ms), int(now_ms)))
        pid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO paper_trades(position_id, kind, ts_ms, price, qty, fee, slippage, reason, created_ms)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, TradeKind.ENTRY.value, int(entry_ms), float(entry_price), float(qty), float(entry_fee),
             float(entry_slippage), "E0", int(now_ms)))
        audit(conn, ts_ms=now_ms, actor=Actor.PAPER, event=AuditEvent.PAPER_FILL, entity_type="position",
              entity_id=pid, to_state=PositionState.OPEN.value,
              payload=dict(signal_id=signal_id, entry_ms=int(entry_ms), entry_price=float(entry_price),
                           qty=float(qty), stop=float(stop), risk_per_unit=float(risk_per_unit)))
    return pid


def get_position(conn: sqlite3.Connection, position_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM paper_positions WHERE position_id = ?", (int(position_id),)).fetchone()


def open_positions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM paper_positions WHERE state = 'OPEN' ORDER BY subsystem_n"))


def open_position_for_subsystem(conn: sqlite3.Connection, subsystem_n: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM paper_positions WHERE state = 'OPEN' AND subsystem_n = ?",
                        (int(subsystem_n),)).fetchone()


def set_exit_plan(conn: sqlite3.Connection, position_id: int, *, exit_signal_close_ms: int, exit_due_ms: int,
                  now_ms: int) -> bool:
    """추세 청산 예약(한 번만). 열린 포지션이고 아직 예약이 없을 때만 True."""
    with transaction(conn):
        cur = conn.execute(
            "UPDATE paper_positions SET exit_signal_close_ms = ?, exit_due_ms = ?, state_version = state_version + 1,"
            " updated_ms = ? WHERE position_id = ? AND state = 'OPEN' AND exit_due_ms IS NULL",
            (int(exit_signal_close_ms), int(exit_due_ms), int(now_ms), int(position_id)))
        if cur.rowcount != 1:
            return False
        audit(conn, ts_ms=now_ms, actor=Actor.ENGINE, event=AuditEvent.STATE_TRANSITION, entity_type="position",
              entity_id=position_id, payload=dict(exit_plan="trend", exit_signal_close_ms=int(exit_signal_close_ms),
                                                  exit_due_ms=int(exit_due_ms)))
    return True


def advance_cursor(conn: sqlite3.Connection, position_id: int, last_bar_close_ms: int, *, now_ms: int) -> bool:
    """감시 커서 전진(앞으로만). 열린 포지션이고 새 값이 더 클 때만 True."""
    cur = conn.execute(
        "UPDATE paper_positions SET last_bar_close_ms = ?, updated_ms = ? WHERE position_id = ? AND state = 'OPEN'"
        " AND (last_bar_close_ms IS NULL OR last_bar_close_ms < ?)",
        (int(last_bar_close_ms), int(now_ms), int(position_id), int(last_bar_close_ms)))
    return cur.rowcount == 1


def add_funding(conn: sqlite3.Connection, position_id: int, *, ts_ms: int, rate: float, price: float,
                amount_per_unit: float, now_ms: int) -> bool:
    """펀딩 한 번(단위당, 양수 = 지불). 같은 펀딩 시각이 이미 있으면 False(멱등)."""
    with transaction(conn):
        pos = get_position(conn, position_id)
        if pos is None or pos["state"] != PositionState.OPEN.value:
            return False
        try:
            conn.execute(
                "INSERT INTO paper_trades(position_id, kind, ts_ms, price, qty, funding, rate, reason, created_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (int(position_id), TradeKind.FUNDING.value, int(ts_ms), float(price), float(pos["qty"]),
                 float(amount_per_unit), float(rate), "funding", int(now_ms)))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                return False
            raise
        conn.execute("UPDATE paper_positions SET funding = funding + ?, updated_ms = ? WHERE position_id = ?",
                     (float(amount_per_unit), int(now_ms), int(position_id)))
        audit(conn, ts_ms=now_ms, actor=Actor.PAPER, event=AuditEvent.PAPER_FUNDING, entity_type="position",
              entity_id=position_id, payload=dict(ts_ms=int(ts_ms), rate=float(rate), price=float(price),
                                                  amount_per_unit=float(amount_per_unit)))
    return True


def close_position(conn: sqlite3.Connection, position_id: int, *, exit_ms: int, exit_bar_close_ms: int,
                   exit_price: float, exit_reason: ExitReason | str, fees: float, slippage: float,
                   gross_pnl: float, net_pnl: float, r_multiple: float, now_ms: int,
                   exit_fee: float, exit_slippage: float) -> bool:
    """청산(한 트랜잭션): 포지션 OPEN→CLOSED + 원장 EXIT + 신호 FILLED→CLOSED + 감사. 이미 닫혔으면 False.

    fees·slippage·gross/net_pnl은 단위당 합계(진입+청산), exit_fee·exit_slippage는 청산 몫(원장 EXIT 행).
    funding은 add_funding으로 쌓인 값을 그대로 둔다(net_pnl은 호출자가 funding을 빼서 계산해 넘긴다).
    """
    reason = ExitReason(exit_reason)
    with transaction(conn):
        pos = get_position(conn, position_id)
        if pos is None or pos["state"] != PositionState.OPEN.value:
            return False
        cur = conn.execute(
            "UPDATE paper_positions SET state = 'CLOSED', exit_ms = ?, exit_bar_close_ms = ?, exit_price = ?,"
            " exit_reason = ?, fees = ?, slippage = ?, gross_pnl = ?, net_pnl = ?, r_multiple = ?, pnl_usdt = ?,"
            " state_version = state_version + 1, updated_ms = ? WHERE position_id = ? AND state = 'OPEN'",
            (int(exit_ms), int(exit_bar_close_ms), float(exit_price), reason.value, float(fees), float(slippage),
             float(gross_pnl), float(net_pnl), float(r_multiple), float(net_pnl) * float(pos["qty"]), int(now_ms),
             int(position_id)))
        if cur.rowcount != 1:
            return False
        conn.execute(
            "INSERT INTO paper_trades(position_id, kind, ts_ms, price, qty, fee, slippage, reason, created_ms)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (int(position_id), TradeKind.EXIT.value, int(exit_ms), float(exit_price), float(pos["qty"]),
             float(exit_fee), float(exit_slippage), reason.value, int(now_ms)))
        if not transition_signal(conn, pos["signal_id"], SignalState.FILLED, SignalState.CLOSED, now_ms=now_ms,
                                 actor=Actor.PAPER, reason=reason.value):
            raise DbError(f"포지션 {position_id}의 신호가 FILLED가 아니다(불변식 위반)")
        audit(conn, ts_ms=now_ms, actor=Actor.PAPER, event=AuditEvent.PAPER_EXIT, entity_type="position",
              entity_id=position_id, from_state=PositionState.OPEN.value, to_state=PositionState.CLOSED.value,
              payload=dict(exit_ms=int(exit_ms), exit_price=float(exit_price), reason=reason.value,
                           net_pnl=float(net_pnl), r_multiple=float(r_multiple)))
    return True


# ---------------------------------------------------------------------------
# 실행 플래그(/pause /resume)·사이클
# ---------------------------------------------------------------------------


def is_paused(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM runtime_flags WHERE key = 'paused'").fetchone()
    return row is not None and row["value"] == "1"


def set_paused(conn: sqlite3.Connection, paused: bool, *, now_ms: int, actor: Actor | str) -> bool:
    """일시정지 설정. 값이 실제로 바뀌면 True(감사 로그), 이미 그 값이면 False."""
    value = "1" if paused else "0"
    with transaction(conn):
        before = is_paused(conn)
        if before == paused:
            return False
        conn.execute(
            "INSERT INTO runtime_flags(key, value, updated_ms, updated_by) VALUES ('paused', ?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_ms = excluded.updated_ms,"
            " updated_by = excluded.updated_by",
            (value, int(now_ms), str(_enum_value(actor))))
        audit(conn, ts_ms=now_ms, actor=actor, event=AuditEvent.FLAG_CHANGED, entity_type="flag", entity_id="paused",
              from_state="1" if before else "0", to_state=value)
    return True


def begin_cycle(conn: sqlite3.Connection, cycle_day: str, *, decision_ms: int, now_ms: int) -> bool:
    """일일 사이클 시작. 그날 사이클이 이미 DONE이면 False(다시 돌리지 않음). RUNNING·FAILED면 재시작 허용."""
    with transaction(conn):
        row = conn.execute("SELECT status FROM cycles WHERE cycle_day = ?", (cycle_day,)).fetchone()
        if row is not None and row["status"] == "DONE":
            return False
        conn.execute(
            "INSERT INTO cycles(cycle_day, decision_ms, status, started_ms) VALUES (?, ?, 'RUNNING', ?)"
            " ON CONFLICT(cycle_day) DO UPDATE SET status = 'RUNNING', started_ms = excluded.started_ms,"
            " finished_ms = NULL, note = NULL",
            (cycle_day, int(decision_ms), int(now_ms)))
        audit(conn, ts_ms=now_ms, actor=Actor.ENGINE, event=AuditEvent.CYCLE, entity_type="cycle",
              entity_id=cycle_day, from_state=None if row is None else row["status"], to_state="RUNNING")
    return True


def finish_cycle(conn: sqlite3.Connection, cycle_day: str, *, ok: bool, now_ms: int, note: str | None = None) -> bool:
    status = "DONE" if ok else "FAILED"
    with transaction(conn):
        cur = conn.execute(
            "UPDATE cycles SET status = ?, finished_ms = ?, note = ? WHERE cycle_day = ? AND status = 'RUNNING'",
            (status, int(now_ms), note, cycle_day))
        if cur.rowcount != 1:
            return False
        audit(conn, ts_ms=now_ms, actor=Actor.ENGINE, event=AuditEvent.CYCLE, entity_type="cycle",
              entity_id=cycle_day, from_state="RUNNING", to_state=status, payload=dict(note=note))
    return True


def backup_to(conn: sqlite3.Connection, dest: str | os.PathLike[str]) -> None:
    """온라인 백업(sqlite3 backup API). 대상 파일은 0600으로 만든다."""
    p = Path(dest)
    _ensure_private_file(p)
    target = sqlite3.connect(str(p))
    try:
        conn.backup(target)
    finally:
        target.close()


# ---------------------------------------------------------------------------
# 전송 보관함(outbox) — OPS-3
# ---------------------------------------------------------------------------

OUTBOX_MAX_PENDING = 500                  # 미전송 보관 메시지 상한(넘으면 가장 오래된 것부터 포기, 감사 기록)


def outbox_add(conn: sqlite3.Connection, *, kind: str, text: str, signal_id: str | None,
               edit_message_id: int | None, now_ms: int) -> int:
    """전송 실패한 메시지를 보관. 리포트는 가장 새 것 하나만 남긴다(이전 미전송 리포트는 대체)."""
    with transaction(conn):
        if kind == "report":
            conn.execute("UPDATE outbox SET dropped_ms = ?, drop_reason = 'superseded' WHERE kind = 'report'"
                         " AND sent_ms IS NULL AND dropped_ms IS NULL", (int(now_ms),))
        cur = conn.execute(
            "INSERT INTO outbox(kind, text, signal_id, edit_message_id, created_ms, last_try_ms)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (str(kind), str(text), signal_id, None if edit_message_id is None else int(edit_message_id),
             int(now_ms), int(now_ms)))
        return int(cur.lastrowid)


def outbox_pending(conn: sqlite3.Connection, *, now_ms: int, limit: int = 100) -> list[sqlite3.Row]:
    """보낼 차례인 보관 메시지(오래된 순). 상한(500건)을 넘은 가장 오래된 것은 포기로 표시하고 감사 기록.
    청산·체결 알림은 늦어도 보내는 것이 낫다(기록 성격) — 기한으로 버리지 않고, 본문에 원래 시각을 붙여 보낸다."""
    with transaction(conn):
        n = int(conn.execute("SELECT COUNT(*) FROM outbox WHERE sent_ms IS NULL AND dropped_ms IS NULL").fetchone()[0])
        old = [] if n <= OUTBOX_MAX_PENDING else list(conn.execute(
            "SELECT outbox_id, kind FROM outbox WHERE sent_ms IS NULL AND dropped_ms IS NULL ORDER BY outbox_id"
            " LIMIT ?", (n - OUTBOX_MAX_PENDING,)))
        for r in old:
            conn.execute("UPDATE outbox SET dropped_ms = ?, drop_reason = 'overflow' WHERE outbox_id = ?",
                         (int(now_ms), int(r["outbox_id"])))
            audit(conn, ts_ms=now_ms, actor=Actor.SYSTEM, event=AuditEvent.ALERT, entity_type="outbox",
                  entity_id=int(r["outbox_id"]), payload=dict(reason="outbox_overflow", kind=r["kind"]))
    return list(conn.execute("SELECT * FROM outbox WHERE sent_ms IS NULL AND dropped_ms IS NULL"
                             " ORDER BY outbox_id LIMIT ?", (int(limit),)))


def outbox_mark(conn: sqlite3.Connection, outbox_id: int, *, sent: bool, now_ms: int) -> None:
    if sent:
        conn.execute("UPDATE outbox SET sent_ms = ?, last_try_ms = ? WHERE outbox_id = ? AND sent_ms IS NULL",
                     (int(now_ms), int(now_ms), int(outbox_id)))
    else:
        conn.execute("UPDATE outbox SET attempts = attempts + 1, last_try_ms = ? WHERE outbox_id = ?",
                     (int(now_ms), int(outbox_id)))
