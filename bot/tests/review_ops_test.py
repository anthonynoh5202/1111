"""적대적 운영 감사 시험 (운영 감사관). 소스는 고치지 않는다.

- 통과 시험: 확인된 운영 통제(/pause 지속·위험 축소 방향, 백업 디렉터리 자동 생성·0600, idle tick 디스크 증가 없음)
- xfail(strict=True): 확인된 운영 결함. 고쳐지면 XPASS → 실패로 바뀌어 표시를 지우라고 알려 준다.
- 수정 담당 반영: OPS-1~9 수정 후 xfail 표시를 지우고, '현재 동작 기록' 시험은 고친 동작을 단언하도록 바꿨다.
실행: .venv/bin/python -m pytest bot/tests/review_ops_test.py -q -rxX
"""
from __future__ import annotations

import asyncio
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from bot import db
from bot import main as M
from bot import telegram_ui as tu
from bot.config import Secret
from bot.engine import Engine
from bot.marketdata import MarketDataError
from bot.tests.conftest import FakeTransport, FrameMarket, frame_market_from, make_config
from bot.types import NS_PER_MIN, NS_PER_SEC, FakeClock, Mode, SignalState, ns_to_ms

REPO = Path(__file__).resolve().parents[2]
TOKEN = "123456:TEST-dummy-token-not-real"


def _breakout(market):
    from backtest import trend as TR

    daily = TR.DailyData.from_frame(market.bars["1d"])
    sigs = {n: TR.channel_signals(daily, n) for n in TR.PERIODS}
    t = next(i for i in range(len(daily)) if any(sigs[n].long_entry[i] for n in TR.PERIODS))
    return daily, t


def _paper_rt(tmp_path, market, clock, *, market_obj=None, secrets=None):
    cfg = make_config(tmp_path, **{"claude.enabled": False})
    conn = db.connect(":memory:", mode=Mode.PAPER, now_ms=ns_to_ms(clock.now_ns()))
    mk = market_obj or frame_market_from(market, clock)
    eng = Engine(conn, cfg, mk, None, clock)
    return M.PaperRuntime(cfg=cfg, secrets=secrets or M.Secrets(), conn=conn, clock=clock, market=mk,
                          analyst=eng.analyst, engine=eng)


class _FakeApp:
    """PTB Application 가짜(네트워크 없음). enter_exc가 있으면 initialize(getMe)에서 그 예외."""

    def __init__(self, enter_exc=None):
        self.enter_exc = enter_exc
        self.bot = object()
        self.post_init = None

        class U:
            async def start_polling(self, **kw):
                pass

            async def stop(self):
                pass

        self.updater = U()

    async def __aenter__(self):
        if self.enter_exc is not None:
            raise self.enter_exc
        return self

    async def __aexit__(self, *exc):
        return None

    async def start(self):
        pass

    async def stop(self):
        pass


# ---------------------------------------------------------------------------
# OPS-1 시작 시 외부 의존(바이낸스 시계·텔레그램 getMe) 실패 → 예외가 main 밖으로 → 재시작 루프, 알림 없음
# ---------------------------------------------------------------------------


def test_startup_clock_failure_does_not_crash(tmp_path, trend_market_small, monkeypatch):
    daily, t = _breakout(trend_market_small)
    clock = FakeClock(int(daily.decision_ns[t]) + 5 * NS_PER_SEC)
    rt = _paper_rt(tmp_path, trend_market_small, clock)

    def boom():
        raise MarketDataError("/fapi/v1/time: HTTP 451 (재시도 안 함)")

    rt.market.check_clock = boom
    tx = FakeTransport()
    monkeypatch.setattr(tu, "build_application", lambda *a, **k: _FakeApp())
    monkeypatch.setattr(tu.PtbTransport, "from_bot", classmethod(lambda cls, bot, chat_id: tx))

    async def fake_loop(rt_, transport, stop):
        return None

    monkeypatch.setattr(M, "paper_loop", fake_loop)
    asyncio.run(M.run_paper(rt))          # 원하는 동작: 죽지 않고 경고를 보낸 뒤 루프(다음 주기 재시도)
    assert any("시계" in m.text or "시세" in m.text for m in tx.sent)


def test_startup_clock_failure_escapes_main_as_uncaught_exception(tmp_path, trend_market_small, monkeypatch, capsys):
    """OPS-1 수정: 시작 중 어떤 예외도 main 밖으로 나가지 않는다 → 종료 코드 규약(1) + 가린 한 줄, 트레이스백 없음."""
    daily, t = _breakout(trend_market_small)
    clock = FakeClock(int(daily.decision_ns[t]) + 5 * NS_PER_SEC)
    rt = _paper_rt(tmp_path, trend_market_small, clock)

    def boom(rt_):
        raise RuntimeError(f"예상 못한 오류 {TOKEN}")

    monkeypatch.setattr(M, "build_paper_runtime", lambda cfg, secrets, **kw: rt)
    monkeypatch.setattr(M, "run_paper", boom)
    monkeypatch.setattr(M, "load_config", lambda path: rt.cfg)
    monkeypatch.setattr(M, "load_secrets", lambda cfg: M.Secrets())
    code = M.main(["--config", "x", "run"], environ={})
    out = capsys.readouterr()
    assert code == M.EXIT_ERROR
    assert TOKEN not in out.out + out.err and "Traceback" not in out.err and "RuntimeError" in out.err


def test_startup_telegram_outage_keeps_monitoring(tmp_path, trend_market_small, monkeypatch):
    from telegram.error import NetworkError

    daily, t = _breakout(trend_market_small)
    clock = FakeClock(int(daily.decision_ns[t]) + 5 * NS_PER_SEC)
    rt = _paper_rt(tmp_path, trend_market_small, clock)
    rt.market.check_clock = lambda: 0
    ran = []
    monkeypatch.setattr(tu, "build_application", lambda *a, **k: _FakeApp(NetworkError("httpx.ConnectError")))
    monkeypatch.setattr(tu.PtbTransport, "from_bot", classmethod(lambda cls, bot, chat_id: FakeTransport()))

    async def fake_loop(rt_, transport, stop):
        ran.append(True)

    monkeypatch.setattr(M, "paper_loop", fake_loop)
    asyncio.run(M.run_paper(rt))
    assert ran, "텔레그램 없이도 감시 루프는 돌아야 한다"


# ---------------------------------------------------------------------------
# OPS-2 헬스체크 핑은 텔레그램이 완전히 죽어 있어도 계속 나간다 → 데드맨 스위치가 가장 흔한 장애를 못 잡음
# ---------------------------------------------------------------------------


class _DeadTransport(FakeTransport):
    async def send(self, text, buttons=()):
        raise ConnectionError("telegram down")

    async def edit(self, message_id, text, buttons=()):
        raise ConnectionError("telegram down")


def _run_loop_rounds(rt, transport, rounds: int, monkeypatch, step_ns: int = 60 * NS_PER_SEC):
    """paper_loop를 실제로 돌리되 대기 시간을 0으로 만들고, 바퀴마다 가짜 시계를 step만큼 민다."""
    pings = []

    async def fake_ping(secrets):
        pings.append(1)

    monkeypatch.setattr(M, "_health_ping", fake_ping)
    monkeypatch.setattr(M, "HEALTH_PING_INTERVAL_S", 0)
    object.__setattr__(rt.cfg.schedule, "monitor_interval_s", 0)
    orig_tick = rt.engine.tick
    count = [0]

    async def go():
        stop = asyncio.Event()

        def tick():
            out = orig_tick()
            count[0] += 1
            rt.clock.set(rt.clock.now_ns() + step_ns)
            if count[0] >= rounds:
                stop.set()
            return out

        rt.engine.tick = tick
        await M.paper_loop(rt, transport, stop)

    asyncio.run(go())
    return pings


def test_health_ping_stops_when_telegram_is_dead(tmp_path, trend_market_small, monkeypatch):
    daily, t = _breakout(trend_market_small)
    clock = FakeClock(int(daily.decision_ns[t]) + 5 * NS_PER_SEC)
    rt = _paper_rt(tmp_path, trend_market_small, clock,
                   secrets=M.Secrets(ping_url=Secret("https://hc-ping.com/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b")))
    pings = _run_loop_rounds(rt, _DeadTransport(), 5, monkeypatch)
    assert rt.conn.execute("SELECT COUNT(*) FROM signals WHERE state='NEW'").fetchone()[0] >= 1  # 카드 못 보냄
    assert pings == [], f"텔레그램이 죽었는데 핑 {len(pings)}회"


# ---------------------------------------------------------------------------
# OPS-3 카드 말고는(체결·손절·청산·경고·일일 리포트) 전송 실패 시 재시도하지 않는다 → 영구 유실
# ---------------------------------------------------------------------------


class _CardsOnlyTransport(FakeTransport):
    """버튼 있는 메시지(카드)만 성공, 나머지(체결·청산·리포트·경고)는 실패 — 텔레그램 간헐 장애 흉내."""

    down: bool = True

    async def send(self, text, buttons=()):
        if self.down and not buttons:
            raise ConnectionError("telegram flaky")
        return await super().send(text, buttons)


def test_exit_notifications_survive_transient_telegram_failure(tmp_path, trend_market_small):
    cfg = make_config(tmp_path, mode="replay", **{"telegram.enabled": False, "claude.enabled": False,
                                                  "replay.auto_approve_latency_min": 30})
    d = trend_market_small.bars["1d"]
    first = int(d["close_ns"].iloc[0])
    clock = FakeClock(first)
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(first))
    eng = Engine(conn, cfg, frame_market_from(trend_market_small, clock), None, clock)
    tx = _CardsOnlyTransport()
    decisions = [int(c) + 60 * NS_PER_SEC for c in d["close_ns"].iloc[1:]]
    M.run_replay_loop(eng, clock, tx, decisions, auto_approve_latency_min=30)
    closed = conn.execute("SELECT COUNT(*) FROM paper_positions WHERE state='CLOSED'").fetchone()[0]
    assert closed >= 1
    tx.down = False                                     # 텔레그램 복구
    clock.set(clock.now_ns() + 60 * NS_PER_SEC)
    M.deliver(tx, eng, eng.tick())
    delivered_exit = [m for m in tx.sent if not m.buttons and "청산" in m.text]
    assert len(delivered_exit) >= closed, f"청산 {closed}건 중 알림 도착 {len(delivered_exit)}건"


# ---------------------------------------------------------------------------
# OPS-4 tick이 시세 재시도(최대 ~47초/요청) 동안 engine.lock을 쥔다 → 그 사이 누른 [확인]이 60초 창을 넘겨 거부
# ---------------------------------------------------------------------------


def test_confirm_pressed_in_time_is_not_rejected_by_lock_wait(tmp_path, trend_market_small):
    from bot.telegram_ui import CallbackContext, handle_callback
    from bot.types import CallbackAction, make_callback_data

    daily, t = _breakout(trend_market_small)
    clock = FakeClock(int(daily.decision_ns[t]) + 5 * NS_PER_SEC)
    rt = _paper_rt(tmp_path, trend_market_small, clock)
    eng, conn, cfg = rt.engine, rt.conn, rt.cfg
    rep = eng.run_daily_cycle()
    asyncio.run(tu.send_outgoing(FakeTransport(), eng, rep.outgoing))
    sig = conn.execute("SELECT * FROM signals WHERE state='CARD_SENT'").fetchone()
    sid, mid = sig["signal_id"], int(sig["tg_message_id"])

    def ctx(action, qid):
        return CallbackContext(callback_query_id=qid, update_id=None, from_user_id=cfg.telegram.allowed_user_id,
                               chat_id=cfg.telegram.allowed_chat_id, chat_type="private", message_id=mid,
                               data=make_callback_data(action, sid))

    handle_callback(eng, conn, cfg, ctx(CallbackAction.APPROVE, "q1"), ns_to_ms(clock.now_ns()))
    assert db.get_signal(conn, sid)["state"] == SignalState.CONFIRM_PENDING.value
    press_ms = ns_to_ms(clock.now_ns()) + 10_000            # 승인 10초 뒤 [확인]을 누름(_locked가 이 시각을 넘긴다)
    with eng.lock:                                         # 다른 스레드의 긴 작업이 락을 쥔 동안 70초 흐름
        clock.set(clock.now_ns() + 70 * NS_PER_SEC)
    with eng.lock:                                         # telegram_ui._locked와 같은 순서
        handle_callback(eng, conn, cfg, ctx(CallbackAction.CONFIRM, "q2"), press_ms)
    assert db.get_signal(conn, sid)["state"] == SignalState.APPROVED.value


def test_tick_and_cycle_do_network_io_while_holding_engine_lock(tmp_path, trend_market_small):
    """OPS-4 수정: tick·사이클의 시세 조회(1분봉·펀딩·일봉)는 engine.lock 밖에서 한다(락은 DB 반영에만)."""
    import threading

    daily, t = _breakout(trend_market_small)
    clock = FakeClock(int(daily.decision_ns[t]) + 5 * NS_PER_SEC)
    rt = _paper_rt(tmp_path, trend_market_small, clock)
    eng, mk = rt.engine, rt.market
    held: list[tuple[str, bool]] = []

    def owned() -> bool:
        return eng.lock._is_owned()  # RLock: 현재 스레드가 쥐고 있나

    for name in ("minute_bars", "funding", "daily_bars"):
        orig = getattr(mk, name)

        def wrap(*a, _o=orig, _n=name):
            held.append((_n, owned()))
            return _o(*a)
        setattr(mk, name, wrap)
    rep = eng.run_daily_cycle()
    asyncio.run(tu.send_outgoing(FakeTransport(), eng, rep.outgoing))
    sig = rt.conn.execute("SELECT signal_id FROM signals WHERE state='CARD_SENT'").fetchone()[0]
    assert eng.request_confirm(sig) and eng.confirm(sig)
    for k in range(1, 400):                       # 체결 → 감시(손절·추세 청산) 동안 여러 번
        clock.set(clock.now_ns() + 30 * NS_PER_MIN)
        eng.tick()
    assert any(n == "minute_bars" for n, _ in held) and any(n == "daily_bars" for n, _ in held)
    assert not [h for h in held if h[1]], f"락을 쥔 채 시세 조회: {[h for h in held if h[1]][:3]}"
    assert threading.current_thread() is threading.main_thread()


# ---------------------------------------------------------------------------
# OPS-5 늦은 시작(late_start)·일시정지로 생성 즉시 건너뛴 신호는 사용자에게 아무 알림도 없다
# ---------------------------------------------------------------------------


def test_late_start_skip_only_counted_in_daily_report(tmp_path, trend_market_small):
    """OPS-9 수정: 판단 + 2시간 뒤 재시작하면 그날 신호는 SKIPPED(late_start) — 어느 하위 시스템이 왜 건너뛰어졌는지
    알림을 보낸다(리포트의 '건너뜀 1' 숫자만이 아니라)."""
    daily, t = _breakout(trend_market_small)
    clock = FakeClock(int(daily.decision_ns[t]) + 3 * 3600 * NS_PER_SEC)
    rt = _paper_rt(tmp_path, trend_market_small, clock)
    rep = rt.engine.run_daily_cycle()
    texts = "\n".join(m.text for m in rep.outgoing)
    assert rt.conn.execute("SELECT COUNT(*) FROM signals WHERE state='SKIPPED'").fetchone()[0] >= 1
    assert "건너뜀 1" in texts
    notice = [m for m in rep.outgoing if m.kind == "alert" and "late_start" in m.text]
    assert len(notice) == 1 and "늦은 시작" in notice[0].text and "일 돌파" in notice[0].text


# ---------------------------------------------------------------------------
# 확인된 올바른 동작
# ---------------------------------------------------------------------------


def test_pause_skips_approved_keeps_open_positions_and_persists(tmp_path, trend_market_small):
    """/pause: 체결 대기(APPROVED)까지 건너뛰고, 플래그는 DB에 남아 재시작 뒤에도 유지, 다음 신호도 SKIPPED."""
    daily, t = _breakout(trend_market_small)
    dec = int(daily.decision_ns[t])
    clock = FakeClock(dec + 5 * NS_PER_SEC)
    path = tmp_path / "p.sqlite3"
    cfg = make_config(tmp_path, db_path=str(path), **{"claude.enabled": False})
    conn = db.connect(path, mode=Mode.PAPER, now_ms=ns_to_ms(clock.now_ns()))
    eng = Engine(conn, cfg, frame_market_from(trend_market_small, clock), None, clock)
    rep = eng.run_daily_cycle()
    asyncio.run(tu.send_outgoing(FakeTransport(), eng, rep.outgoing))
    sid = conn.execute("SELECT signal_id FROM signals WHERE state='CARD_SENT'").fetchone()[0]
    assert eng.request_confirm(sid) and eng.confirm(sid)
    assert eng.pause("telegram_user") == [sid]
    conn.close()
    conn2 = db.connect(path, mode=Mode.PAPER, now_ms=ns_to_ms(clock.now_ns()))
    assert db.is_paused(conn2)
    assert db.get_signal(conn2, sid)["state"] == SignalState.SKIPPED.value
    assert conn2.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0] == 0
    conn2.close()


def test_idle_ticks_do_not_grow_database(tmp_path, trend_market_small):
    """디스크: 할 일 없는 1분 tick 1440회(하루)가 audit_log·DB를 키우지 않는다."""
    d = trend_market_small.bars["1d"]
    start = int(d["close_ns"].iloc[5]) + 3600 * NS_PER_SEC
    clock = FakeClock(start)
    rt = _paper_rt(tmp_path, trend_market_small, clock)
    before = rt.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    for _ in range(1440):
        clock.set(clock.now_ns() + NS_PER_MIN)
        rt.engine.tick()
    after = rt.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert after - before == 0


def test_backup_creates_missing_dir_private(tmp_path):
    os.umask(0o077)
    conn = db.connect(tmp_path / "b.sqlite3", mode=Mode.PAPER, now_ms=0)
    dest = tmp_path / "backups" / "x.sqlite3"
    db.backup_to(conn, dest)
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    conn.close()


def test_compose_has_no_container_healthcheck_and_backup_lives_in_same_volume():
    """OPS-7·OPS-8 수정: compose healthcheck(심장 박동 파일 나이), 백업은 별도 호스트 디렉터리(./backups → /backups),
    RUNBOOK에 자동 백업(cron)·암호화(age)·보존 정리·WAL 삭제 명령·복원 전 check."""
    comp = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    runbook = (REPO / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "healthcheck:" in comp and M.HEARTBEAT_PATH in comp
    assert "./backups:/backups" in comp and "/data/backups/" not in runbook
    assert "cron" in runbook and "age " in runbook and "rm -f /data/bot.sqlite3-wal /data/bot.sqlite3-shm" in runbook


def test_uncaught_startup_exception_prints_token_unredacted(tmp_path):
    """OPS-6 수정 확인(서브프로세스, 실제 인터프리터 출력):
    (1) main 경로: 시작 중 InvalidToken(메시지에 토큰 원문) → 잡혀서 종료 코드 1, stdout·stderr에 토큰 없음.
    (2) 마지막 방어선: 가림 excepthook을 설치한 뒤 잡히지 않은 예외도 토큰이 가려진다."""
    code = f"""
import asyncio, sys
sys.path.insert(0, {str(REPO)!r})
from telegram.error import InvalidToken
from bot import main as M
async def boom(rt):
    raise InvalidToken("The token `{TOKEN}` was rejected by the server.")
M.run_paper = boom
class RT:
    market = None
    class conn:
        @staticmethod
        def close(): pass
M.build_paper_runtime = lambda cfg, secrets, **k: RT
from bot.config import Mode
cfg = type("C", (), {{"mode": Mode.PAPER}})()
M.load_config = lambda path: cfg
M.load_secrets = lambda c: M.Secrets()
sys.exit(M.main(["--config", "x", "run"], environ={{}}))
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={"PATH": os.environ.get("PATH", "")}, timeout=60)
    assert r.returncode == 1
    assert TOKEN not in r.stderr + r.stdout and "InvalidToken" in r.stderr
    code2 = f"""
import sys
sys.path.insert(0, {str(REPO)!r})
from bot import main as M
M.install_excepthooks(None)
raise RuntimeError("https://api.telegram.org/bot{TOKEN}/getMe")
"""
    r2 = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True,
                        env={"PATH": os.environ.get("PATH", "")}, timeout=60)
    assert r2.returncode == 1 and "RuntimeError" in r2.stderr and TOKEN not in r2.stderr


def test_base_image_env_names_do_not_trip_secret_env_check():
    """python:3.11-slim 이미지가 넣는 환경 변수(GPG_KEY 등)와 compose의 TZ로는 시작 거부가 일어나지 않는다."""
    from bot.config import check_env_no_secrets

    env = {"PATH": "/usr/local/bin", "LANG": "C.UTF-8", "GPG_KEY": "A035C8C19219BA821ECEA86B64E628F8D684696D",
           "PYTHON_VERSION": "3.11.14", "PYTHON_SHA256": "0" * 64, "HOSTNAME": "x", "HOME": "/nonexistent",
           "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "PIP_NO_CACHE_DIR": "1",
           "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    assert check_env_no_secrets(env) == []
