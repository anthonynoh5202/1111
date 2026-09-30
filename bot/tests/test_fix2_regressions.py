"""검증관 지적(V-1, V-2, 기타) 수정의 회귀 시험 — 수정 담당 2차. 네트워크 없음."""
from __future__ import annotations

import re
import sqlite3
import subprocess
import tomllib
from pathlib import Path

import pytest

from bot import db
from bot.types import Mode

REPO = Path(__file__).resolve().parents[2]
T0_MS = 1_709_337_660_000


# ---------------------------------------------------------------------------
# V-1: INSERT OR REPLACE / REPLACE INTO 로 추가 전용 테이블 덮어쓰기 차단
# ---------------------------------------------------------------------------

_REPLACE_STMTS = {
    "audit_log": [
        "INSERT OR REPLACE INTO audit_log(seq, ts_ms, actor, event_type) VALUES (1, 0, 'X', 'Y')",
        "REPLACE INTO audit_log(seq, ts_ms, actor, event_type) VALUES (1, 0, 'X', 'Y')",
    ],
    "config_snapshots": [
        "INSERT OR REPLACE INTO config_snapshots(snapshot_id, ts_ms, fingerprint, bot_version, config_json)"
        " VALUES (1, 0, 'f', 'v', '{}')",
        "REPLACE INTO config_snapshots(snapshot_id, ts_ms, fingerprint, bot_version, config_json)"
        " VALUES (1, 0, 'f', 'v', '{}')",
    ],
}


def _seed(c: sqlite3.Connection) -> None:
    for i in range(3):
        db.audit(c, ts_ms=T0_MS + i, actor="SYSTEM", event="ALERT", payload={"i": i})
    c.execute("INSERT INTO config_snapshots(ts_ms, fingerprint, bot_version, config_json) VALUES (?, 'orig', '1', '{}')",
              (T0_MS,))


def _snapshot(c: sqlite3.Connection) -> tuple:
    a = [tuple(r) for r in c.execute("SELECT * FROM audit_log ORDER BY seq")]
    s = [tuple(r) for r in c.execute("SELECT * FROM config_snapshots ORDER BY snapshot_id")]
    return a, s


@pytest.mark.parametrize("table", sorted(_REPLACE_STMTS))
def test_replace_blocked_via_bot_connection(tmp_path, table):
    c = db.connect(tmp_path / "r.sqlite3", mode=Mode.PAPER, now_ms=T0_MS)
    assert c.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
    _seed(c)
    before = _snapshot(c)
    for stmt in _REPLACE_STMTS[table]:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            c.execute(stmt)
    assert _snapshot(c) == before


@pytest.mark.parametrize("table", sorted(_REPLACE_STMTS))
def test_replace_blocked_even_without_recursive_triggers(tmp_path, table):
    """봇 밖의 sqlite3 연결(recursive_triggers 기본값 OFF)에서도 BEFORE INSERT 트리거가 단독으로 막는다."""
    path = tmp_path / "r.sqlite3"
    c = db.connect(path, mode=Mode.PAPER, now_ms=T0_MS)
    _seed(c)
    c.close()
    raw = sqlite3.connect(path, isolation_level=None)
    assert raw.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
    before = _snapshot(raw)
    for stmt in _REPLACE_STMTS[table]:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            raw.execute(stmt)
    assert _snapshot(raw) == before
    raw.close()
    db.connect(path, mode=Mode.PAPER, now_ms=T0_MS).close()          # 무결성 검사 통과


def test_normal_appends_still_work_after_replace_triggers(tmp_path):
    c = db.connect(tmp_path / "n.sqlite3", mode=Mode.PAPER, now_ms=T0_MS)
    _seed(c)
    db.audit(c, ts_ms=T0_MS, actor="SYSTEM", event="ALERT", payload={})
    c.execute("INSERT INTO audit_log(seq, ts_ms, actor, event_type) VALUES (NULL, 0, 'A', 'B')")   # 새 번호
    assert c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 5


@pytest.mark.parametrize("trig", ["audit_log_no_replace", "config_snapshots_no_replace"])
def test_missing_replace_trigger_refuses_start(tmp_path, trig):
    assert trig in db.PROTECT_TRIGGERS
    path = tmp_path / "t.sqlite3"
    c = db.connect(path, mode=Mode.PAPER, now_ms=T0_MS)
    c.execute(f"DROP TRIGGER {trig}")
    c.close()
    with pytest.raises(db.DbError, match="트리거"):
        db.connect(path, mode=Mode.PAPER, now_ms=T0_MS)


# ---------------------------------------------------------------------------
# V-2: 저장소 파일이 프로젝트 자체 gitleaks 사용자 규칙에 걸리지 않는다(허용 목록 반영)
# ---------------------------------------------------------------------------


def _repo_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git 사용 불가")
    return [f for f in out.splitlines() if f]


def test_custom_gitleaks_rules_have_no_unallowed_hits():
    cfg = tomllib.loads((REPO / ".gitleaks.toml").read_text(encoding="utf-8"))
    rules = [(r["id"], re.compile(r["regex"])) for r in cfg["rules"]]
    allow = [re.compile(x) for x in cfg["allowlist"]["regexes"]]
    skip = [re.compile(x) for x in cfg["allowlist"]["paths"]]
    hits = []
    for f in _repo_files():
        if any(p.search(f) for p in skip):
            continue
        try:
            text = (REPO / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for rid, rx in rules:
            for m in rx.finditer(text):
                if not any(a.search(m.group(0)) for a in allow):
                    hits.append((f, rid, m.group(0)[:40]))
    assert hits == []


def test_gitleaks_allowlist_is_by_value_not_broad_path():
    cfg = tomllib.loads((REPO / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert all(p.startswith("^data/binance/") for p in cfg["allowlist"]["paths"])
    assert not any("tests" in p or "verify" in p for p in cfg["allowlist"]["paths"])


# ---------------------------------------------------------------------------
# 기타: 이미지·저장소 위생, 백업 스크립트 순서
# ---------------------------------------------------------------------------


def test_dockerignore_excludes_verify_and_tests():
    lines = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "bot/verify/" in lines and "bot/tests/" in lines


def test_local_replay_config_is_gitignored():
    r = subprocess.run(["git", "check-ignore", "-q", "config/replay.local.toml"], cwd=REPO)
    assert r.returncode == 0


def test_backup_checks_recipient_before_creating_plaintext():
    sh = (REPO / "scripts" / "backup.sh").read_text(encoding="utf-8")
    i_check = sh.index('if [ ! -s "$RECIPIENT_FILE" ]')
    i_age_cmd = sh.index("command -v age")
    i_trap = sh.index("trap ")
    i_dump = sh.index("docker compose run")
    assert i_check < i_dump and i_age_cmd < i_dump and i_trap < i_dump
    assert "%H%M%S" in sh
