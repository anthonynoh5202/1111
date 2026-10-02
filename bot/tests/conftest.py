"""bot 테스트 공용 도우미·가짜 구현 — 설계 담당 소유 (bot/DESIGN.md §10).

제공
- 시각 상수: T_DECISION_NS(2024-03-02 00:01:00 UTC 판단), T_MS
- fixture: conn(메모리 DB, paper), replay_conn, file_db(임시 파일 WAL), secret_dir(0600 비밀 파일), bot_config,
  fake_clock, fake_transport, fake_analyst, trend_market_factory
- 함수: make_config(**overrides), insert_test_signal(conn, ...), FrameMarket(프레임 기반 MarketData, 미래 참조 차단),
  FakeTransport(비동기 전송 기록·실패 주입), FakeAnalyst(정해진 결과 반환), ok_analysis(), minute_market_from_frames
- 비동기 테스트는 pytest-asyncio가 없으므로 asyncio.run(...)으로 돌린다.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from backtest.tests.conftest import make_market  # 합성 시장(5분봉 무작위 경로 → 여러 간격 + 1분 실행 봉)
from bot import db
from bot.config import BotConfig, config_from_dict
from bot.types import (
    NS_PER_DAY,
    NS_PER_MIN,
    NS_PER_MS,
    AnalystResult,
    Button,
    FakeClock,
    Mode,
    new_signal_id,
)

ALLOWED_USER_ID = 123456789
ALLOWED_CHAT_ID = 123456789
OTHER_USER_ID = 987654321
T_DAY_START_NS = int(pd.Timestamp("2024-03-02", tz="UTC").value)   # 판단 날 00:00 UTC
T_DECISION_NS = T_DAY_START_NS + 60 * 1_000_000_000                # + 60초
T_MS = T_DECISION_NS // NS_PER_MS


# ---------------------------------------------------------------------------
# 설정·비밀
# ---------------------------------------------------------------------------


def make_config(tmp_path: Path | None = None, **overrides: Any) -> BotConfig:
    """검증을 통과하는 기본 설정 dict에 overrides(최상위 키 또는 'section.key')를 덮어써 BotConfig를 만든다."""
    base = Path("/run/secrets") if tmp_path is None else Path(tmp_path)
    raw: dict[str, Any] = {
        "mode": "paper",
        "db_path": str(base / "bot.sqlite3"),
        "telegram": {"enabled": True, "allowed_user_id": ALLOWED_USER_ID, "allowed_chat_id": ALLOWED_CHAT_ID,
                     "bot_token_file": str(base / "telegram_bot_token")},
        "claude": {"enabled": True, "api_key_file": str(base / "anthropic_api_key")},
    }
    for key, value in overrides.items():
        if "." in key:
            sec, name = key.split(".", 1)
            raw.setdefault(sec, {})[name] = value
        else:
            raw[key] = value
    return config_from_dict(raw)


@pytest.fixture
def secret_dir(tmp_path: Path) -> Path:
    """가짜 비밀 파일(0600) 두 개가 있는 디렉터리. 값은 테스트 전용 더미."""
    d = tmp_path / "secrets"
    d.mkdir(mode=0o700)
    for name, value in (("telegram_bot_token", "123456:TEST-dummy-token-not-real"),
                        ("anthropic_api_key", "sk-ant-test-dummy-not-real")):
        p = d / name
        p.write_text(value + "\n")
        os.chmod(p, 0o600)
    return d


@pytest.fixture
def bot_config(secret_dir: Path) -> BotConfig:
    return make_config(secret_dir)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    c = db.connect(":memory:", mode=Mode.PAPER, now_ms=T_MS)
    yield c
    c.close()


@pytest.fixture
def replay_conn():
    c = db.connect(":memory:", mode=Mode.REPLAY, now_ms=T_MS)
    yield c
    c.close()


@pytest.fixture
def file_db(tmp_path: Path) -> Path:
    return tmp_path / "data" / "bot.sqlite3"


def insert_test_signal(conn, *, n: int = 20, decision_ns: int = T_DECISION_NS, close: float = 50_000.0,
                       entry_level: float = 49_000.0, exit_level: float = 45_000.0, atr20: float = 1_500.0,
                       approval_window_s: int = 7200, mode: Mode = Mode.PAPER,
                       signal_id: str | None = None) -> str:
    """NEW 신호 한 건을 넣고 ID를 돌려준다(숫자는 그럴듯한 더미)."""
    sid = signal_id or new_signal_id()
    close_ns = decision_ns - 60 * 1_000_000_000
    day = pd.Timestamp(close_ns - NS_PER_DAY, unit="ns", tz="UTC").strftime("%Y-%m-%d")
    ok = db.insert_signal(conn, signal_id=sid, mode=mode, strategy_key="E0-L-ENS", spec_version="TREND v1.0",
                          subsystem_n=n, side=1, signal_day=day, signal_close_ms=close_ns // NS_PER_MS,
                          decision_ms=decision_ns // NS_PER_MS,
                          expires_ms=decision_ns // NS_PER_MS + approval_window_s * 1000,
                          close=close, entry_level=entry_level, exit_level=exit_level, atr20=atr20,
                          now_ms=decision_ns // NS_PER_MS)
    assert ok
    return sid


# ---------------------------------------------------------------------------
# 시계·가짜 외부 연동
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock(T_DECISION_NS)


@dataclass
class SentMessage:
    message_id: int
    text: str
    buttons: tuple[tuple[Button, ...], ...]
    protect: bool = True


@dataclass
class FakeTransport:
    """ChatTransport 가짜. fail_next=k면 다음 k번 send가 예외."""

    sent: list[SentMessage] = field(default_factory=list)
    edits: list[tuple[int, str, tuple]] = field(default_factory=list)
    answers: list[tuple[str, str | None]] = field(default_factory=list)
    fail_next: int = 0
    _next_id: int = 1000

    async def send(self, text: str, buttons: tuple[tuple[Button, ...], ...] = (), *, protect: bool = True) -> int:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("가짜 전송 실패")
        self._next_id += 1
        self.sent.append(SentMessage(self._next_id, text, buttons, protect))
        return self._next_id

    async def edit(self, message_id: int, text: str, buttons: tuple[tuple[Button, ...], ...] = ()) -> None:
        self.edits.append((message_id, text, buttons))

    async def answer_callback(self, callback_query_id: str, text: str | None = None) -> None:
        self.answers.append((callback_query_id, text))


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()


def run_async(coro):
    return asyncio.run(coro)


def ok_analysis(**overrides: Any) -> AnalystResult:
    base = dict(ok=True, status="ok", prompt_version="analyst_v1", model="claude-opus-5-5",
                summary="20일 돌파, ATR 대비 과열 아님", counter_evidence=("거래량 평균 이하",),
                invalidation="종가가 10일 최저 아래", opinion="approve", confidence_note="표본 적음",
                input_json="{}", raw_response="{}", stop_reason="end_turn", latency_ms=1234)
    base.update(overrides)
    return AnalystResult(**base)


@dataclass
class FakeAnalyst:
    """AnalystClient 가짜: 정해진 결과를 돌려주고 받은 입력을 기록한다."""

    result: AnalystResult = field(default_factory=ok_analysis)
    calls: list[dict] = field(default_factory=list)

    def analyze(self, input_payload: dict[str, Any]) -> AnalystResult:
        self.calls.append(input_payload)
        return self.result


@pytest.fixture
def fake_analyst() -> FakeAnalyst:
    return FakeAnalyst()


# ---------------------------------------------------------------------------
# 시세 가짜 (프레임 기반) — marketdata.Replay가 준비되기 전에도 엔진·모의 매매 테스트를 돌릴 수 있게
# ---------------------------------------------------------------------------


class LookaheadError(AssertionError):
    pass


class FrameMarket:
    """MarketData 가짜: 미리 만든 프레임에서 '마감된 봉만' 준다. until_ns > clock.now_ns()면 LookaheadError."""

    def __init__(self, daily: pd.DataFrame, minute: pd.DataFrame, funding: pd.DataFrame, clock: FakeClock) -> None:
        self.daily = daily
        self.minute = minute
        self.funding_df = funding
        self.clock = clock
        self.calls: list[tuple[str, int, int]] = []

    def _guard(self, until_ns: int) -> None:
        if int(until_ns) > self.clock.now_ns():
            raise LookaheadError(f"미래 조회: until={until_ns} > now={self.clock.now_ns()}")

    def daily_bars(self, until_ns: int) -> pd.DataFrame:
        self._guard(until_ns)
        self.calls.append(("daily", 0, int(until_ns)))
        return self.daily[self.daily["close_ns"] <= int(until_ns)]

    def minute_bars(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        self._guard(until_ns)
        self.calls.append(("minute", int(start_ns), int(until_ns)))
        m = self.minute
        return m[(m["open_ns"] >= int(start_ns)) & (m["close_ns"] <= int(until_ns))]

    def funding(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        self._guard(until_ns)
        f = self.funding_df
        return f[(f["time_ns"] > int(start_ns)) & (f["time_ns"] <= int(until_ns))].reset_index(drop=True)

    def server_time_ns(self) -> int | None:
        return None


def trend_market(days: int = 260, *, seed: int = 5, start: str = "2023-10-01"):
    """합성 시장(backtest make_market): 실행 봉이 처음부터 1분봉. 반환 backtest.types.MarketData.

    bars["1d"] = 일봉, exec_bars = 1분봉, funding = 8시간 0.01%. 기본값(260일, seed 5)은 세 하위 시스템 모두 거래가 있다.
    """
    return make_market(days=days, seed=seed, start=start, one_minute_from=start, tfs=("1d",))


@pytest.fixture(scope="session")
def trend_market_small():
    """세션 공유 합성 시장(수정 금지). 260일, seed 5: 백테스트 E0-L-ENS 체결 8건(N20 4·N55 2·N100 2, 추세 청산 4·손절 4)."""
    return trend_market()


def frame_market_from(market, clock: FakeClock) -> FrameMarket:
    return FrameMarket(market.bars["1d"], market.exec_bars, market.funding, clock)


__all__ = [
    "ALLOWED_CHAT_ID", "ALLOWED_USER_ID", "OTHER_USER_ID", "T_DAY_START_NS", "T_DECISION_NS", "T_MS",
    "FakeAnalyst", "FakeTransport", "FrameMarket", "LookaheadError", "SentMessage", "frame_market_from",
    "insert_test_signal", "make_config", "ok_analysis", "run_async", "trend_market", "NS_PER_MIN", "np",
]
