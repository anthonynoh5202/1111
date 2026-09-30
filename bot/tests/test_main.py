"""진입점(bot/main.py) 시험 — 통합 담당. 네트워크 없음.

paper 모드는 이 컨테이너에서 실제로 돌릴 수 없으므로(바이낸스·텔레그램·Claude 접속 불가) 설정 검증·--dry-run·
스케줄 루프 한 바퀴(가짜 시세·가짜 전송)만 시험한다. 재생 명령은 실데이터 짧은 구간(@slow).
"""
from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from bot import db
from bot import main as M
from bot.engine import Engine
from bot.tests.conftest import ALLOWED_CHAT_ID, ALLOWED_USER_ID, FakeTransport, frame_market_from, make_config
from bot.types import NS_PER_SEC, FakeClock, Mode

REPO = Path(__file__).resolve().parents[2]
TOKEN = "123456:TEST-dummy-token-not-real"
API_KEY = "sk-ant-test-dummy-not-real"


def write_toml(path: Path, mode: str, db_path: Path, secret_dir: Path | None = None, **extra: str) -> Path:
    lines = [f'mode = "{mode}"', f'db_path = "{db_path}"', ""]
    if mode == "paper":
        lines += ["[telegram]", "enabled = true", f"allowed_user_id = {ALLOWED_USER_ID}",
                  f"allowed_chat_id = {ALLOWED_CHAT_ID}", f'bot_token_file = "{secret_dir / "telegram_bot_token"}"', "",
                  "[claude]", "enabled = true", f'api_key_file = "{secret_dir / "anthropic_api_key"}"', ""]
    else:
        lines += ["[telegram]", "enabled = false", "", "[claude]", "enabled = false", ""]
    for sec, body in extra.items():
        lines += [f"[{sec}]", body, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def paper_toml(tmp_path, secret_dir):
    return write_toml(tmp_path / "bot.toml", "paper", tmp_path / "data" / "bot.sqlite3", secret_dir)


def run_main(args, capsys):
    code = M.main(args, environ={})
    out = capsys.readouterr()
    return code, out.out, out.err


# ---------------------------------------------------------------------------
# 시작 점검
# ---------------------------------------------------------------------------


def test_env_secret_names_refused(paper_toml, capsys):
    code = M.main(["--config", str(paper_toml), "check"],
                  environ={"TELEGRAM_BOT_TOKEN": TOKEN, "PATH": "/usr/bin"})
    err = capsys.readouterr().err
    assert code == M.EXIT_CONFIG
    assert "TELEGRAM_BOT_TOKEN" in err and TOKEN not in err


def test_check_ok_and_prints_no_secrets(paper_toml, capsys, tmp_path):
    code, out, err = run_main(["--config", str(paper_toml), "check"], capsys)
    assert code == M.EXIT_OK, err
    assert "점검 통과" in out and "텔레그램 있음" in out
    for s in (TOKEN, API_KEY, str(ALLOWED_USER_ID)):
        assert s not in out + err
    db_file = tmp_path / "data" / "bot.sqlite3"
    assert stat.S_IMODE(os.stat(db_file).st_mode) == 0o600


def test_missing_config_and_secret_file(tmp_path, secret_dir, capsys):
    code, _, err = run_main(["--config", str(tmp_path / "none.toml"), "check"], capsys)
    assert code == M.EXIT_CONFIG and "설정 파일이 없다" in err
    (secret_dir / "anthropic_api_key").unlink()
    p = write_toml(tmp_path / "b.toml", "paper", tmp_path / "x.sqlite3", secret_dir)
    code, _, err = run_main(["--config", str(p), "check"], capsys)
    assert code == M.EXIT_CONFIG and "비밀 파일이 없다" in err


def test_live_mode_refused(tmp_path, capsys):
    p = tmp_path / "live.toml"
    p.write_text(f'mode = "live"\ndb_path = "{tmp_path / "x.sqlite3"}"\n', encoding="utf-8")
    code, _, err = run_main(["--config", str(p), "check"], capsys)
    assert code == M.EXIT_CONFIG and "live" in err


def test_db_mode_mismatch_exit_3(tmp_path, secret_dir, capsys):
    dbp = tmp_path / "shared.sqlite3"
    db.connect(dbp, mode=Mode.REPLAY, now_ms=0).close()
    p = write_toml(tmp_path / "bot.toml", "paper", dbp, secret_dir)
    code, _, err = run_main(["--config", str(p), "check"], capsys)
    assert code == M.EXIT_DB and "replay" in err


def test_run_dry_run_no_network(paper_toml, capsys, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise AssertionError("dry-run이 네트워크를 쓰면 안 된다")

    monkeypatch.setattr(httpx.Client, "send", boom)
    code, out, err = run_main(["--config", str(paper_toml), "run", "--dry-run"], capsys)
    assert code == M.EXIT_OK, err
    assert "dry-run 통과" in out and "네트워크 호출 없음" in out
    assert TOKEN not in out + err and API_KEY not in out + err


def test_run_refuses_replay_config_and_replay_refuses_paper(tmp_path, paper_toml, capsys):
    rp = write_toml(tmp_path / "r.toml", "replay", tmp_path / "r.sqlite3")
    code, _, err = run_main(["--config", str(rp), "run", "--dry-run"], capsys)
    assert code == M.EXIT_CONFIG
    code, _, err = run_main(["--config", str(paper_toml), "replay"], capsys)
    assert code == M.EXIT_CONFIG and "replay" in err


def test_replay_mode_reads_no_secrets(tmp_path, capsys, monkeypatch):
    """재생 모드는 비밀 파일을 읽지 않는다(B-14): 비밀 경로가 없어도 check 통과."""
    rp = write_toml(tmp_path / "r.toml", "replay", tmp_path / "r.sqlite3")
    called = []
    monkeypatch.setattr(M, "load_secrets", lambda cfg: called.append(1) or M.Secrets())
    code, out, err = run_main(["--config", str(rp), "check"], capsys)
    assert code == M.EXIT_OK, err
    assert "텔레그램 없음" in out


def test_backup_creates_private_copy_and_refuses_overwrite(paper_toml, tmp_path, capsys):
    assert run_main(["--config", str(paper_toml), "check"], capsys)[0] == 0
    dest = tmp_path / "backups" / "b1.sqlite3"
    code, out, err = run_main(["--config", str(paper_toml), "backup", "--dest", str(dest)], capsys)
    assert code == M.EXIT_OK, err
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600
    c = db.connect(dest, mode=Mode.PAPER, now_ms=0)
    assert c.execute("SELECT COUNT(*) FROM db_meta").fetchone()[0] >= 3
    c.close()
    code, _, err = run_main(["--config", str(paper_toml), "backup", "--dest", str(dest)], capsys)
    assert code == M.EXIT_ERROR and "이미 있다" in err


# ---------------------------------------------------------------------------
# paper 구성·스케줄 루프 (네트워크 없음)
# ---------------------------------------------------------------------------


def test_build_paper_runtime_uses_file_secrets(bot_config, secret_dir, tmp_path):
    from bot.analyst import AnthropicAnalystClient
    from bot.config import load_secrets
    from bot.marketdata import LiveBinance

    cfg = make_config(secret_dir, db_path=str(tmp_path / "p.sqlite3"))
    rt = M.build_paper_runtime(cfg, load_secrets(cfg), analyst_client_factory=lambda api_key, timeout_s: object())
    try:
        assert isinstance(rt.market, LiveBinance)
        assert isinstance(rt.analyst, AnthropicAnalystClient)
        assert API_KEY not in repr(rt.analyst)
        assert db.db_mode(rt.conn) == Mode.PAPER
    finally:
        rt.market.close()
        rt.conn.close()


def test_paper_loop_one_round_runs_cycle_and_sends_cards(tmp_path, trend_market_small):
    """스케줄 루프 한 바퀴: 판단 시각이 지났으면 사이클 → 카드 전송 성공 뒤 CARD_SENT. 두 번째 바퀴는 사이클 재실행 없음."""
    from backtest import trend as TR

    daily = TR.DailyData.from_frame(trend_market_small.bars["1d"])
    sigs = {n: TR.channel_signals(daily, n) for n in TR.PERIODS}
    t = next(i for i in range(len(daily)) if any(sigs[n].long_entry[i] for n in TR.PERIODS))
    clock = FakeClock(int(daily.decision_ns[t]) + 5 * NS_PER_SEC)
    cfg = make_config(tmp_path, **{"claude.enabled": False})
    conn = db.connect(":memory:", mode=Mode.PAPER, now_ms=clock.now_ns() // 1_000_000)
    eng = Engine(conn, cfg, frame_market_from(trend_market_small, clock), None, clock)
    rt = M.PaperRuntime(cfg=cfg, secrets=M.Secrets(), conn=conn, clock=clock, market=eng.market,
                        analyst=eng.analyst, engine=eng)
    tx = FakeTransport()

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(M.paper_loop(rt, tx, stop))
        await asyncio.sleep(0.5)
        stop.set()
        await task

    asyncio.run(go())
    cards = [m for m in tx.sent if m.buttons]
    assert cards, "카드가 전송되지 않았다"
    states = {r["state"] for r in conn.execute("SELECT state FROM signals")}
    assert states == {"CARD_SENT"}
    n_cycles = conn.execute("SELECT COUNT(*) FROM cycles WHERE status='DONE'").fetchone()[0]
    assert n_cycles == 1
    asyncio.run(go())                                    # 같은 날 두 번째: 사이클 재실행·카드 재전송 없음
    assert len([m for m in tx.sent if m.buttons]) == len(cards)


def test_recording_transport_and_decision_times(tmp_path):
    cfg = make_config(tmp_path, mode="replay", **{"telegram.enabled": False, "claude.enabled": False,
                                                  "replay.start": "2024-01-03", "replay.end": "2024-01-04"})
    day = 86_400 * NS_PER_SEC
    import pandas as pd

    base = int(pd.Timestamp("2024-01-01", tz="UTC").value)
    closes = [base + k * day for k in range(1, 8)]   # 01-02 ~ 01-08 00:00 마감
    decs = M.replay_decision_times(cfg, closes)
    assert [pd.Timestamp(d, tz="UTC").strftime("%m-%d %H:%M") for d in decs] == ["01-03 00:01", "01-04 00:01"]
    tx = M.RecordingTransport()
    assert asyncio.run(tx.send("x" * 500)) == 1 and len(tx.sent[0][1]) == 80


# ---------------------------------------------------------------------------
# 재생 명령 (실데이터, 짧은 구간)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not (REPO / "data" / "binance" / "BTCUSDT_1d.csv.gz").exists(), reason="실데이터 없음")
def test_replay_command_short_period(tmp_path, capsys):
    from backtest import config as C

    rp = write_toml(tmp_path / "r.toml", "replay", tmp_path / "r.sqlite3",
                    replay='start = "2024-02-01"\nend = "2024-03-31"\nauto_approve_latency_min = 30',
                    marketdata=f'data_dir = "{REPO / "data" / "binance"}"')
    out_csv = tmp_path / "pos.csv"
    args = ["--config", str(rp), "replay", "--trades-csv", str(out_csv)]
    if Path(C.CACHE_DIR).is_dir():
        args += ["--cache-dir", str(C.CACHE_DIR)]
    code, out, err = run_main(args, capsys)
    assert code == M.EXIT_OK, err
    assert "재생 완료" in out and "실패 0" in out
    assert out_csv.exists()
    # 같은 DB로 다시 돌려도 멱등
    code, out2, _ = run_main(args, capsys)
    assert code == M.EXIT_OK
    keep = lambda o: [x.strip() for x in o.splitlines()[0].split("·") if "신호" in x or "포지션" in x]  # noqa: E731
    assert keep(out) == keep(out2) and len(keep(out)) == 2


# ---------------------------------------------------------------------------
# 배포 견본 파일
# ---------------------------------------------------------------------------


def test_example_configs_are_valid():
    """config/*.example.toml이 로더를 통과한다(paper 견본은 숫자 ID 두 개를 채워야 통과 — 빈 값으로는 시작 거부)."""
    import tomllib

    from bot.config import ConfigError, config_from_dict

    raw = tomllib.loads((REPO / "config" / "bot.example.toml").read_text(encoding="utf-8"))
    with pytest.raises(ConfigError):
        config_from_dict(raw)                               # ID 0 → 거부(채우기 전에는 못 켠다)
    raw["telegram"]["allowed_user_id"] = ALLOWED_USER_ID
    raw["telegram"]["allowed_chat_id"] = ALLOWED_CHAT_ID
    cfg = config_from_dict(raw)
    assert cfg.mode == Mode.PAPER and cfg.telegram.bot_token_file.startswith("/run/secrets/")
    rcfg = config_from_dict(tomllib.loads((REPO / "config" / "replay.example.toml").read_text(encoding="utf-8")))
    assert rcfg.mode == Mode.REPLAY and rcfg.replay.auto_approve_latency_min == 30


def test_deploy_files_security_rules():
    """compose: ports 없음·read_only·cap_drop·no-new-privileges·secrets 파일. Dockerfile: 비루트. .env.example: 값 없음."""
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    body = [ln for ln in compose.splitlines() if not ln.strip().startswith("#")]
    assert not any(ln.strip().startswith("ports:") for ln in body)
    for needle in ("read_only: true", "cap_drop: [ALL]", "no-new-privileges:true", "max-size: \"10m\"",
                   "restart: unless-stopped", "file: ./secrets/telegram_bot_token"):
        assert needle in compose, needle
    docker = "\n".join(ln for ln in (REPO / "Dockerfile").read_text(encoding="utf-8").splitlines()
                       if not ln.lstrip().startswith("#"))
    assert "USER 10001:10001" in docker and "EXPOSE" not in docker and "FROM python:3.11-slim" in docker
    for ln in (REPO / ".env.example").read_text(encoding="utf-8").splitlines():
        if ln and not ln.startswith("#"):
            name, _, value = ln.partition("=")
            assert value == "" and not M.check_env_no_secrets({name: "x"}), ln
    req = (REPO / "requirements.txt").read_text(encoding="utf-8")
    pins = [ln for ln in req.splitlines() if ln and not ln.startswith(("#", " "))]
    assert pins and all("==" in ln for ln in pins)
    # PV-24(검토 SEC-10): 모든 고정 줄에 해시가 따라온다
    blocks = req.split("\n")
    for i, ln in enumerate(blocks):
        if ln and not ln.startswith(("#", " ")):
            assert ln.endswith("\\") and blocks[i + 1].strip().startswith("--hash=sha256:"), ln
    assert "--require-hashes" in (REPO / "Dockerfile").read_text(encoding="utf-8")


def test_run_paper_wires_polling_without_network(tmp_path, monkeypatch, trend_market_small):
    """run_paper 배선: post_init(deleteWebhook) → start → start_polling(POLLING_KWARGS) → 시작 알림 → 루프 → 정지.
    PTB Application을 가짜로 바꿔 네트워크 없이 순서만 본다."""
    from bot import telegram_ui as tu
    from bot.config import Secret

    calls: list = []

    class FakeUpdater:
        async def start_polling(self, **kw):
            calls.append(("start_polling", kw))

        async def stop(self):
            calls.append("updater.stop")

    class FakeApp:
        bot = object()
        updater = FakeUpdater()

        async def __aenter__(self):
            calls.append("initialize")
            return self

        async def __aexit__(self, *exc):
            calls.append("shutdown")

        async def start(self):
            calls.append("start")

        async def stop(self):
            calls.append("stop")

    fake_app = FakeApp()
    fake_app.post_init = lambda app: _coro(calls.append("post_init"))
    tx = FakeTransport()
    monkeypatch.setattr(tu, "build_application", lambda token, engine, conn, cfg, **kw: (
        calls.append(("build", kw.get("db_lock") is engine.lock)), fake_app)[1])
    monkeypatch.setattr(tu.PtbTransport, "from_bot", classmethod(lambda cls, bot, chat_id: tx))

    async def fake_loop(rt, transport, stop):
        calls.append(("loop", transport is tx))

    monkeypatch.setattr(M, "paper_loop", fake_loop)
    clock = FakeClock(int(trend_market_small.bars["1d"]["close_ns"].iloc[-1]) + 3600 * NS_PER_SEC)
    cfg = make_config(tmp_path, **{"claude.enabled": False})
    conn = db.connect(":memory:", mode=Mode.PAPER, now_ms=clock.now_ns() // 1_000_000)
    market = frame_market_from(trend_market_small, clock)
    market.check_clock = lambda: 0
    eng = Engine(conn, cfg, market, None, clock)
    rt = M.PaperRuntime(cfg=cfg, secrets=M.Secrets(telegram_token=Secret(TOKEN)), conn=conn, clock=clock,
                        market=market, analyst=eng.analyst, engine=eng)
    assert asyncio.run(M.run_paper(rt)) == M.EXIT_OK
    names = [c if isinstance(c, str) else c[0] for c in calls]
    assert names == ["build", "initialize", "post_init", "start", "start_polling", "loop", "updater.stop", "stop",
                     "shutdown"]
    assert calls[0] == ("build", True)                      # 텔레그램 핸들러와 엔진이 같은 DB 락
    assert calls[4] == ("start_polling", tu.POLLING_KWARGS)
    assert tx.sent and tx.sent[0].text.startswith("[PAPER] 시작") and TOKEN not in tx.sent[0].text


async def _coro(_):
    return None
