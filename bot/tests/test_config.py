"""bot.config·bot.types — 설정 검증, 비밀 파일, 환경 변수 금지, callback_data 파싱, 시간 도우미 (설계 담당)."""
from __future__ import annotations

import os
import pickle

import pytest

from bot import config as CF
from bot.tests.conftest import ALLOWED_USER_ID, make_config
from bot.types import (
    CALLBACK_MAX_BYTES,
    CallbackAction,
    FakeClock,
    Mode,
    ceil_minute_ns,
    kst_str,
    make_callback_data,
    new_signal_id,
    parse_callback_data,
    utc_iso_ms,
)

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------


def test_default_config_valid_and_trend_config(bot_config):
    assert bot_config.mode == Mode.PAPER
    tc = bot_config.trend_config()
    assert tc.base_key == "E0-L-ENS" and tc.periods == (20, 55, 100)
    assert tc.latency_min == 30 and tc.stop_atr_mult == 2.0 and not tc.allow_short
    assert bot_config.mode_tag == "[PAPER]"
    assert bot_config.claude.model == "claude-opus-5-5" and bot_config.claude.effort == "medium"
    assert bot_config.claude.timeout_s == 120


def test_load_config_from_toml(tmp_path):
    p = tmp_path / "bot.toml"
    p.write_text(
        'mode = "replay"\ndb_path = "/tmp/x.sqlite3"\n'
        "[telegram]\nenabled = false\n"
        "[claude]\nenabled = false\n"
        '[replay]\nstart = "2024-01-01"\nend = "2024-06-30"\n'
    )
    cfg = CF.load_config(p)
    assert cfg.mode == Mode.REPLAY and cfg.replay.start == "2024-01-01"
    assert CF.load_secrets(cfg) == CF.Secrets()      # 재생 모드는 비밀을 읽지 않는다


@pytest.mark.parametrize("override, match", [
    ({"mode": "live"}, "live"),
    ({"mode": "PAPER"}, "mode"),
    ({"strategy_key": "E0-LS-ENS"}, "strategy_key"),
    ({"unknown_top": 1}, "모르는 최상위 키"),
    ({"telegram.alowed_user_id": 1}, "모르는 키"),                       # 오타
    ({"telegram.allowed_user_id": "123456789"}, "정수"),                 # 문자열 ID 거부
    ({"telegram.allowed_user_id": True}, "정수"),                        # bool 거부
    ({"telegram.allowed_chat_id": -100123}, "개인 채팅"),                # 그룹 채팅 거부
    ({"telegram.allowed_user_id": 0}, "양의 정수"),
    ({"telegram.bot_token_file": "secrets/token"}, "절대 경로"),
    ({"claude.model": "claude-sonnet-5"}, "claude.model"),
    ({"claude.timeout_s": 600}, "timeout"),
    ({"claude.prompt_version": "../../etc/passwd"}, "prompt_version"),
    ({"schedule.decision_delay_s": 30}, "decision_delay_s"),
    ({"schedule.trend_exit_latency_min": 10}, "trend_exit_latency_min"),
    ({"marketdata.base_url": "http://fapi.binance.com"}, "https"),
    ({"marketdata.symbol": "ETHUSDT"}, "BTCUSDT"),
    ({"paper.equity_usdt": 0}, "양수"),
    ({"replay.start": "2024/01/01"}, "YYYY-MM-DD"),
])
def test_config_rejects(override, match):
    with pytest.raises(CF.ConfigError, match=match):
        make_config(**override)


def test_telegram_disabled_allows_zero_ids():
    cfg = make_config(**{"telegram.enabled": False, "telegram.allowed_user_id": 0, "telegram.allowed_chat_id": 0})
    assert not cfg.telegram.enabled


def test_redacted_dict_and_fingerprint(bot_config):
    d = bot_config.redacted_dict()
    assert str(ALLOWED_USER_ID) not in str(d)
    assert d["telegram"]["allowed_user_id"].endswith(str(ALLOWED_USER_ID)[-3:])
    assert d["mode"] == "paper"
    fp = bot_config.fingerprint()
    assert len(fp) == 64 and fp == make_config(os.path.dirname(bot_config.telegram.bot_token_file)).fingerprint()


# ---------------------------------------------------------------------------
# 비밀
# ---------------------------------------------------------------------------


def test_read_secret_ok_and_never_printed(secret_dir):
    s = CF.read_secret(secret_dir / "telegram_bot_token")
    assert s.reveal() == "123456:TEST-dummy-token-not-real"
    for text in (repr(s), str(s), f"{s}", f"{s!r}", "%s" % (s,)):
        assert "TEST-dummy" not in text
    with pytest.raises(TypeError):
        pickle.dumps(s)
    with pytest.raises(TypeError):
        hash(s)


def test_load_secrets_reads_enabled_only(bot_config, secret_dir):
    sec = CF.load_secrets(bot_config)
    assert sec.telegram_token is not None and sec.anthropic_api_key is not None and sec.ping_url is None
    assert "dummy" not in repr(sec)


@pytest.mark.parametrize("content, mode, match", [
    (b"", 0o600, "크기"),
    (b"\n", 0o600, "비어"),
    (b"abc def", 0o600, "공백"),
    (b"abc\x00def", 0o600, "제어"),
    (b"x" * 5000, 0o600, "크기"),
    (b"\xff\xfe", 0o600, "UTF-8"),
    (b"token", 0o602, "권한이 너무 넓다"),
    (b"token", 0o644, "권한이 너무 넓다"),        # SEC-06: 그룹·다른 사용자 읽기도 거부(PV-09)
    (b"token", 0o640, "권한이 너무 넓다"),
])
def test_read_secret_rejects(tmp_path, content, mode, match):
    p = tmp_path / "s"
    p.write_bytes(content)
    os.chmod(p, mode)
    with pytest.raises(CF.ConfigError, match=match) as ei:
        CF.read_secret(p)
    msg_without_path = str(ei.value).replace(str(p), "")
    value = content.decode("utf-8", errors="ignore").strip()
    assert len(value) < 3 or value not in msg_without_path     # 오류 메시지에 비밀 값이 나오지 않는다


def test_read_secret_path_rules(tmp_path):
    with pytest.raises(CF.ConfigError, match="절대 경로"):
        CF.read_secret("relative/path")
    with pytest.raises(CF.ConfigError, match="없다"):
        CF.read_secret(tmp_path / "missing")
    with pytest.raises(CF.ConfigError, match="일반 파일"):
        CF.read_secret(tmp_path)


def test_check_env_no_secrets():
    assert CF.check_env_no_secrets({"PATH": "/bin", "HOME": "/root", "TZ": "UTC"}) == []
    bad = CF.check_env_no_secrets({"ANTHROPIC_API_KEY": "x", "TELEGRAM_BOT_TOKEN": "y", "BINANCE_API_SECRET": "z",
                                   "BOT_TELEGRAM_TOKEN": "w", "PATH": "/bin"})
    assert bad == ["ANTHROPIC_API_KEY", "BINANCE_API_SECRET", "BOT_TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN"]


# ---------------------------------------------------------------------------
# types: callback_data·시간
# ---------------------------------------------------------------------------


def test_callback_roundtrip():
    sid = new_signal_id()
    for action in CallbackAction:
        data = make_callback_data(action, sid)
        assert len(data.encode()) <= CALLBACK_MAX_BYTES
        parsed = parse_callback_data(data)
        assert parsed is not None and parsed.action == action and parsed.signal_id == sid


@pytest.mark.parametrize("data", [
    None, 123, b"v1:A:AAAAAAAAAAAAAAAA", "", "v2:A:AAAAAAAAAAAAAAAA", "v1:Z:AAAAAAAAAAAAAAAA",
    "v1:A:AAAAAAAAAAAAAAA", "v1:A:AAAAAAAAAAAAAAAAA", "v1:A:aaaaaaaaaaaaaaaa", "v1:A:AAAAAAAAAAAAAAA1",
    "v1:A:AAAAAAAAAAAAAAAA\n", " v1:A:AAAAAAAAAAAAAAAA", "v1:A:AAAAAAAAAAAAAAAA:price=1", "v1:A:" + "A" * 100,
])
def test_callback_rejects_malformed(data):
    assert parse_callback_data(data) is None


def test_make_callback_rejects_bad_id():
    with pytest.raises(ValueError):
        make_callback_data(CallbackAction.APPROVE, "not-an-id")


def test_time_helpers():
    ms = 1_709_337_660_000                       # 2024-03-02 00:01:00 UTC
    assert utc_iso_ms(ms) == "2024-03-02T00:01:00Z"
    assert kst_str(ms) == "2024-03-02 09:01 KST"
    assert ceil_minute_ns(ms * 1_000_000) == ms * 1_000_000
    assert ceil_minute_ns(ms * 1_000_000 + 1) == (ms + 60_000) * 1_000_000
    c = FakeClock(5)
    assert c.advance(10) == 15
    with pytest.raises(ValueError):
        c.advance(-1)


# ---------------------------------------------------------------------------
# 로그 가림
# ---------------------------------------------------------------------------


def test_redacting_filter_hides_secrets(bot_config, secret_dir):
    import logging

    sec = CF.load_secrets(bot_config)
    f = CF.RedactingFilter(sec)
    token = sec.telegram_token.reveal()
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1, "HTTP Request: POST https://api.telegram.org/bot%s/getUpdates",
                            (token,), None)
    assert f.filter(rec)
    assert token not in rec.getMessage() and "***" in rec.getMessage()
    # 알려진 값이 없어도 모양으로 가린다
    g = CF.RedactingFilter()
    assert "AAE" not in g.redact("bot1234567890:AAEabcdefghijklmnopqrstuvwxyz012345")
    assert g.redact("key=sk-ant-api03-abcdefghijkl") == "key=***"
    assert g.redact("https://hc-ping.com/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b") == "https://hc-ping.com/***"
    # 예외 스택 안의 비밀도 가린다
    try:
        raise RuntimeError(f"connect failed {token}")
    except RuntimeError:
        import sys
        rec2 = logging.LogRecord("x", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())
    f.filter(rec2)
    assert token not in rec2.getMessage() and rec2.exc_info is None
