"""검토 지적(SEC-*, R-*, OPS-*) 수정의 회귀 시험 — 수정 담당.

review_*_test.py가 지적 자체를 재현·확인하고, 이 파일은 수정하면서 새로 생긴 동작(경계·보조 경로)을 지킨다.
네트워크 없음(가짜 시세·가짜 전송·가짜 PTB 앱).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backtest import trend as TR
from bot import db
from bot import main as M
from bot import telegram_ui as tu
from bot.config import ConfigError, Secret, check_env_no_secrets, read_telegram_token
from bot.engine import Engine
from bot.tests.conftest import FakeTransport, frame_market_from, make_config
from bot.types import NS_PER_DAY, NS_PER_MIN, NS_PER_SEC, FakeClock, Mode, OutgoingMessage, ns_to_ms

REPO = Path(__file__).resolve().parents[2]
TOKEN = "123456:TEST-dummy-token-not-real"
T0_MS = 1_709_337_660_000


# ---------------------------------------------------------------------------
# SEC-01: 토큰 모양 검사
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value, ok", [
    (TOKEN, True),
    ("1234567890:AAEabcdefghijklmnopqrstuvwxyz012345", True),
    ("123:sk-ant-test-dummy-not-real", False),          # 다른 비밀을 잘못 넣음
    ("sk-ant-test-dummy-not-real", False),
    ("12345678:short", False),
    ("abcdef:AAEabcdefghijklmnopqrstuvwxyz012345", False),
])
def test_telegram_token_shape_checked_before_use(tmp_path, value, ok):
    p = tmp_path / "tok"
    p.write_text(value + "\n")
    os.chmod(p, 0o400)
    if ok:
        assert read_telegram_token(p).reveal() == value
    else:
        with pytest.raises(ConfigError) as ei:
            read_telegram_token(p)
        assert value not in str(ei.value)


# ---------------------------------------------------------------------------
# SEC-02: Claude 글에서 누를 수 있는 요소 제거
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, bad", [
    ("#비트코인 급등 #BTC", "#"),
    ("/start 를 눌러라", "/start"),
    ("줄 바꿈 뒤\n/pause 명령", "/pause"),
    ("@evil_bot 문의", "@evil"),
])
def test_sanitize_strips_clickable_entities(text, bad):
    assert bad not in tu.sanitize_text(text)


def test_sanitize_keeps_short_numbers_and_fractions():
    s = tu.sanitize_text("손절 거리 2.35%, 3/4 확률, 20일 돌파, 비용 0.07%")
    assert "2.35%" in s and "3/4" in s and "20일" in s and "0.07%" in s


def test_audit_ids_not_masked_by_number_rule(conn, bot_config):
    """콜백 쿼리 ID(긴 숫자)는 감사 로그에 그대로(숫자 가림은 Claude 글에만)."""
    eng = Engine(conn, bot_config, None, None, FakeClock(T0_MS * 1_000_000))
    ctx = tu.CallbackContext(callback_query_id="4829301847712399", update_id=1, from_user_id=bot_config.telegram.allowed_user_id,
                             chat_id=bot_config.telegram.allowed_chat_id, chat_type="private", message_id=1, data="garbage")
    tu.handle_callback(eng, conn, bot_config, ctx, T0_MS)
    p = json.loads(conn.execute("SELECT payload_json FROM audit_log WHERE event_type='BUTTON_REJECTED'").fetchone()[0])
    assert p["callback_query_id"] == "4829301847712399"


# ---------------------------------------------------------------------------
# SEC-04: 웹훅 점검(시작 + 5분마다)
# ---------------------------------------------------------------------------


class _WebhookBot:
    def __init__(self, url: str) -> None:
        self.url = url
        self.deleted = 0
        self.checks = 0

    async def get_webhook_info(self):
        self.checks += 1
        return SimpleNamespace(url=self.url)

    async def delete_webhook(self, **kw):
        self.deleted += 1
        self.url = ""


def test_check_webhook_alerts_and_deletes(conn, bot_config):
    bot = _WebhookBot("https://attacker.example/hook")
    msg = asyncio.run(tu.check_webhook(bot, conn, bot_config, now_ms=T0_MS))
    assert msg is not None and msg.kind == "alert" and "attacker" not in msg.text
    assert bot.deleted == 1
    row = conn.execute("SELECT payload_json FROM audit_log WHERE event_type='ALERT'").fetchone()
    assert "webhook_was_set" in row[0]
    assert asyncio.run(tu.check_webhook(bot, conn, bot_config, now_ms=T0_MS)) is None     # 지운 뒤: 정상


def _paper_rt(tmp_path, market, clock, **kw):
    cfg = make_config(tmp_path, **{"claude.enabled": False})
    conn = db.connect(":memory:", mode=Mode.PAPER, now_ms=ns_to_ms(clock.now_ns()))
    mk = frame_market_from(market, clock)
    eng = Engine(conn, cfg, mk, None, clock)
    return M.PaperRuntime(cfg=cfg, secrets=M.Secrets(), conn=conn, clock=clock, market=mk,
                          analyst=eng.analyst, engine=eng, **kw)


class _App:
    def __init__(self, bot) -> None:
        self.bot = bot
        self.post_init = None

        class U:
            async def start_polling(self, **kw):
                pass

            async def stop(self):
                pass
        self.updater = U()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def start(self):
        pass

    async def stop(self):
        pass


def test_supervisor_checks_webhook_periodically(tmp_path, trend_market_small, monkeypatch):
    clock = FakeClock(int(trend_market_small.bars["1d"]["close_ns"].iloc[5]))
    rt = _paper_rt(tmp_path, trend_market_small, clock)
    bot = _WebhookBot("https://attacker.example/hook")
    tx = FakeTransport()
    monkeypatch.setattr(M, "WEBHOOK_CHECK_INTERVAL_S", 0.01)

    async def go():
        stop = asyncio.Event()
        status = M._TelegramStatus()
        task = asyncio.create_task(M._telegram_supervisor(_App(bot), rt, tx, stop, status))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if bot.checks >= 2:
                break
        stop.set()
        await task
        return status.first.result()

    assert asyncio.run(go()) == "up"
    assert bot.checks >= 2 and bot.deleted == 1
    assert any("웹훅" in m.text for m in tx.sent)
    assert rt.health.last_ok is not None                               # 점검 성공 = 텔레그램 정상 신호(OPS-2)


# ---------------------------------------------------------------------------
# SEC-05: 감사 로그 행 삭제(트리거를 되살려 놓아도) 탐지
# ---------------------------------------------------------------------------


def test_audit_row_deletion_detected_even_if_trigger_restored(tmp_path):
    path = tmp_path / "a.sqlite3"
    c = db.connect(path, mode=Mode.PAPER, now_ms=T0_MS)
    for i in range(4):
        db.audit(c, ts_ms=T0_MS + i, actor="SYSTEM", event="ALERT", payload={"i": i})
    trig = c.execute("SELECT sql FROM sqlite_master WHERE name = 'audit_log_no_delete'").fetchone()[0]
    c.execute("DROP TRIGGER audit_log_no_delete")
    c.execute("DELETE FROM audit_log WHERE seq = (SELECT MAX(seq) FROM audit_log)")   # 끝 행 삭제
    c.execute(trig)
    c.close()
    with pytest.raises(db.DbError, match="행 수"):
        db.connect(path, mode=Mode.PAPER, now_ms=T0_MS)


def test_clean_reopen_passes_integrity(tmp_path):
    path = tmp_path / "b.sqlite3"
    c = db.connect(path, mode=Mode.PAPER, now_ms=T0_MS)
    db.audit(c, ts_ms=T0_MS, actor="SYSTEM", event="ALERT", payload={})
    with pytest.raises(Exception):
        with db.transaction(c):                 # 롤백된 삽입은 번호를 남기지 않는다(빈 번호 없음)
            db.audit(c, ts_ms=T0_MS, actor="SYSTEM", event="ALERT", payload={})
            raise RuntimeError("rollback")
    c.close()
    db.connect(path, mode=Mode.PAPER, now_ms=T0_MS).close()


# ---------------------------------------------------------------------------
# SEC-07: 환경 변수 일반 규칙·gitleaks 경로 범위
# ---------------------------------------------------------------------------


def test_env_generic_rule_boundaries():
    bad = check_env_no_secrets({"OPENAI_API_KEY": "x", "GITHUB_TOKEN": "x", "DB_PASSWORD": "x", "AWS_SECRET_ACCESS_KEY": "x",
                                "GPG_KEY": "x", "PYTHON_SHA256": "x", "TOKENIZERS_PARALLELISM": "x", "SSL_CERT_FILE": "x"})
    assert set(bad) == {"OPENAI_API_KEY", "GITHUB_TOKEN", "DB_PASSWORD", "AWS_SECRET_ACCESS_KEY"}


def test_gitleaks_path_allowlist_scoped_to_market_data():
    text = (REPO / ".gitleaks.toml").read_text(encoding="utf-8")
    paths = text.split("paths = [", 1)[1].split("]", 1)[0]
    entries = [ln.strip() for ln in paths.splitlines() if ln.strip().startswith("'''")]
    assert entries and all(e.startswith("'''^data/binance/") for e in entries)
    hc_rule = text.split('id = "healthchecks-ping-url"', 1)[1].split("[allowlist]", 1)[0]
    assert "hc-ping\\.com/[A-Za-z0-9_-]{20,}" in hc_rule                 # slug 형식까지


# ---------------------------------------------------------------------------
# R-1: 놓친 날의 진입 신호는 SKIPPED('missed_cycle') + 알림
# ---------------------------------------------------------------------------


def test_missed_entry_day_recorded_as_skipped_with_notice(tmp_path, trend_market_small):
    daily = TR.DailyData.from_frame(trend_market_small.bars["1d"])
    sigs = {n: TR.channel_signals(daily, n) for n in TR.PERIODS}
    t = next(i for i in range(1, len(daily)) if any(sigs[n].long_entry[i] for n in TR.PERIODS)
             and not any(sigs[n].long_entry[i + 1] for n in TR.PERIODS))
    cfg = make_config(tmp_path, mode="replay", db_path=":memory:", **{"telegram.enabled": False, "claude.enabled": False})
    d_prev, d_miss, d_next = (int(daily.decision_ns[k]) for k in (t - 1, t, t + 1))
    clock = FakeClock(d_prev)
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(d_prev))
    eng = Engine(conn, cfg, frame_market_from(trend_market_small, clock), None, clock)
    assert eng.run_daily_cycle().skipped_reason is None
    clock.set(d_next)                                   # d_miss 하루 동안 꺼져 있었다
    rep = eng.run_daily_cycle()
    assert rep.skipped_reason is None
    rows = conn.execute("SELECT state, state_reason FROM signals WHERE decision_ms = ?", (ns_to_ms(d_miss),)).fetchall()
    assert rows and all(r["state"] == "SKIPPED" and r["state_reason"] == "missed_cycle" for r in rows)
    assert any(m.kind == "alert" and "missed_cycle" in m.text for m in rep.outgoing)
    cyc = conn.execute("SELECT status, note FROM cycles WHERE decision_ms = ?", (ns_to_ms(d_miss),)).fetchone()
    assert cyc["status"] == "DONE" and cyc["note"] == "recovered_missed"


def test_first_run_does_not_recover_history(tmp_path, trend_market_small):
    """DONE 사이클이 하나도 없으면(처음 실행) 과거를 복구하지 않는다(오늘만)."""
    daily = TR.DailyData.from_frame(trend_market_small.bars["1d"])
    dec = int(daily.decision_ns[200])
    cfg = make_config(tmp_path, mode="replay", db_path=":memory:", **{"telegram.enabled": False, "claude.enabled": False})
    clock = FakeClock(dec)
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(dec))
    eng = Engine(conn, cfg, frame_market_from(trend_market_small, clock), None, clock)
    eng.run_daily_cycle()
    assert conn.execute("SELECT COUNT(*) FROM cycles").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# R-4: 1분봉 빈 구간 → 엔진이 감사 + 경고 한 번
# ---------------------------------------------------------------------------


def test_engine_reports_minute_gaps_once(tmp_path, trend_market_small):
    clock = FakeClock(int(trend_market_small.bars["1d"]["close_ns"].iloc[5]))
    rt = _paper_rt(tmp_path, trend_market_small, clock)
    g = [(clock.now_ns() - 10 * NS_PER_MIN, clock.now_ns() - 7 * NS_PER_MIN)]
    rt.market.take_gaps = lambda: [g.pop()] if g else []
    out1 = rt.engine.tick()
    out2 = rt.engine.tick()
    assert sum(1 for m in out1 if m.kind == "alert" and "빈 구간" in m.text) == 1
    assert not [m for m in out2 if "빈 구간" in m.text]
    row = rt.conn.execute("SELECT payload_json FROM audit_log WHERE entity_type = 'minute_gap'").fetchone()
    assert json.loads(row[0])["missing_bars"] == 3


# ---------------------------------------------------------------------------
# OPS-2·OPS-8: 텔레그램이 살아 있으면 핑, 심장 박동 파일 갱신
# ---------------------------------------------------------------------------


def test_ping_and_heartbeat_when_healthy(tmp_path, trend_market_small, monkeypatch):
    daily = TR.DailyData.from_frame(trend_market_small.bars["1d"])
    sigs = {n: TR.channel_signals(daily, n) for n in TR.PERIODS}
    t = next(i for i in range(len(daily)) if any(sigs[n].long_entry[i] for n in TR.PERIODS))
    clock = FakeClock(int(daily.decision_ns[t]) + 5 * NS_PER_SEC)
    hb = tmp_path / "hb"
    rt = _paper_rt(tmp_path, trend_market_small, clock, heartbeat_path=str(hb))
    pings = []

    async def fake_ping(secrets):
        pings.append(1)

    monkeypatch.setattr(M, "_health_ping", fake_ping)
    monkeypatch.setattr(M, "HEALTH_PING_INTERVAL_S", 0)
    object.__setattr__(rt.cfg.schedule, "monitor_interval_s", 0)

    async def go():
        stop = asyncio.Event()
        orig = rt.engine.tick
        n = [0]

        def tick():
            n[0] += 1
            if n[0] >= 3:
                stop.set()
            return orig()
        rt.engine.tick = tick
        await M.paper_loop(rt, FakeTransport(), stop)

    asyncio.run(go())
    assert pings, "텔레그램 정상인데 핑 없음"
    assert hb.exists() and (hb.stat().st_mode & 0o077) == 0


def test_telegram_health_window():
    h = M.TelegramHealth(stale_s=10)
    assert not h.alive(0)
    h.record(1.0, [(None, False)])
    assert not h.alive(1.0)
    h.record(2.0, [(None, False), (None, True)])
    assert h.alive(5.0) and not h.alive(12.5)
    assert M.TelegramHealth(always_ok=True).alive(1e9)


# ---------------------------------------------------------------------------
# OPS-3: 보관함 규칙
# ---------------------------------------------------------------------------


def test_outbox_keeps_latest_report_only_and_cards_not_stored(conn):
    db.outbox_add(conn, kind="report", text="r1", signal_id=None, edit_message_id=None, now_ms=T0_MS)
    db.outbox_add(conn, kind="exit", text="e1", signal_id=None, edit_message_id=None, now_ms=T0_MS + 1)
    db.outbox_add(conn, kind="report", text="r2", signal_id=None, edit_message_id=None, now_ms=T0_MS + 2)
    assert [r["text"] for r in db.outbox_pending(conn, now_ms=T0_MS + 3)] == ["e1", "r2"]


def test_send_outgoing_retries_outbox_first_with_delay_mark(conn, bot_config):
    eng = Engine(conn, bot_config, None, None, FakeClock(T0_MS * 1_000_000))
    tx = FakeTransport(fail_next=2)
    msgs = [OutgoingMessage(text="[PAPER] 모의 청산 A", kind="exit"),
            OutgoingMessage(text="[PAPER] 카드", kind="card", buttons=((tu.Button("x", "v1:A:AAAAAAAAAAAAAAAA"),),))]
    res = asyncio.run(tu.send_outgoing(tx, eng, msgs))
    assert [ok for _, ok in res] == [False, False]
    assert len(db.outbox_pending(conn, now_ms=T0_MS)) == 1          # 청산만 보관(카드는 NEW 재전송 경로)
    asyncio.run(tu.send_outgoing(tx, eng, [OutgoingMessage(text="[PAPER] 새 메시지", kind="info")]))
    assert [m.text.splitlines()[0] for m in tx.sent] == ["[PAPER] 모의 청산 A", "[PAPER] 새 메시지"]
    assert "(지연 전송" in tx.sent[0].text
    assert db.outbox_pending(conn, now_ms=T0_MS) == []


# ---------------------------------------------------------------------------
# OPS-4: 누른 시각 인정 폭 제한
# ---------------------------------------------------------------------------


def test_press_time_is_clamped(conn, bot_config):
    now = T0_MS * 1_000_000
    eng = Engine(conn, bot_config, None, None, FakeClock(now))
    assert eng._press_ms(None) == T0_MS
    assert eng._press_ms(T0_MS + 5_000) == T0_MS                          # 미래 시각 불가
    assert eng._press_ms(T0_MS - 10_000) == T0_MS - 10_000
    assert eng._press_ms(T0_MS - 3_600_000) == T0_MS - 300_000            # 최대 5분 전까지만 인정


# ---------------------------------------------------------------------------
# OPS-7·OPS-8·SEC-10: 배포 파일
# ---------------------------------------------------------------------------


def test_backup_script_encrypts_and_prunes():
    sh = (REPO / "scripts" / "backup.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in sh and "umask 077" in sh
    assert "age -R" in sh and 'rm -f "backups/${name}"' in sh and "-mtime +" in sh
    assert "eval " not in sh


def test_ci_actions_and_images_pinned():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "gitleaks:v8.21.2@sha256:" in ci
    d = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.11-slim@sha256:" in d


# ---------------------------------------------------------------------------
# R-4 보조: 오래 멈췄다 켜져도(> 30일) 1분봉을 30일 조각으로 나눠 따라잡는다(바이낸스 100쪽 한도 회피)
# ---------------------------------------------------------------------------


def test_long_downtime_catch_up_is_chunked(tmp_path, trend_market_small):
    from bot.engine import CATCHUP_WINDOW_NS
    from bot.tests.conftest import insert_test_signal
    from bot.types import Actor, SignalState as S

    d = trend_market_small.bars["1d"]
    start = int(d["close_ns"].iloc[20]) + 60 * NS_PER_SEC
    clock = FakeClock(start)
    rt = _paper_rt(tmp_path, trend_market_small, clock)
    conn = rt.conn
    sid = insert_test_signal(conn, n=20, decision_ns=start, close=100.0, entry_level=99.0, exit_level=1.0, atr20=1.0)
    now = ns_to_ms(start)
    db.transition_signal(conn, sid, S.NEW, S.CARD_SENT, now_ms=now, actor=Actor.ENGINE)
    db.transition_signal(conn, sid, S.CARD_SENT, S.CONFIRM_PENDING, now_ms=now, actor=Actor.ENGINE)
    db.transition_signal(conn, sid, S.CONFIRM_PENDING, S.APPROVED, now_ms=now, actor=Actor.ENGINE,
                         fields=dict(approved_ms=now))
    pid = db.open_position(conn, signal_id=sid, entry_ms=now, entry_price=100.0, qty=0.01, stop=0.5,
                           risk_per_unit=99.5, entry_fee=0.0, entry_slippage=0.0, active_from_ms=now, now_ms=now)
    clock.set(start + 75 * NS_PER_DAY)                   # 75일 동안 꺼져 있었다
    del rt.market.calls[:]
    rt.engine.tick()
    spans = [u - s for kind, s, u in rt.market.calls if kind == "minute"]
    assert len(spans) >= 3 and max(spans) <= CATCHUP_WINDOW_NS + 60 * NS_PER_MIN
    cur = db.get_position(conn, pid)["last_bar_close_ms"]
    assert cur is not None and cur >= ns_to_ms(clock.now_ns()) - 2 * 60_000   # 끝까지 따라잡음
