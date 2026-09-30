"""시세 공급원 시험 — 핵심 담당 (DESIGN §9.2, §10).

LiveBinance는 httpx.MockTransport 가짜 응답으로만 시험한다(이 컨테이너는 바이낸스 접속 불가).
- 미마감 봉 제거, 빈 구간·중복·가격 이상 거부, 429·5xx 재시도(Retry-After), 418 즉시 중지, 4xx 재시도 안 함
- 시계 오차, API 키·서명 헤더 없음, https만, 1분봉 페이지 넘김, 펀딩 정시 내림
Replay: until 이후를 절대 안 줌(미래 조회 예외), 파일 재생 일봉 == backtest.data.load_klines('1d')
"""
from __future__ import annotations

from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import data as D
from bot.config import MarketDataConfig
from bot.marketdata import LiveBinance, MarketDataError, Replay
from bot.types import NS_PER_DAY, NS_PER_MIN, NS_PER_MS, FakeClock, MarketData

DAY_MS = NS_PER_DAY // NS_PER_MS
MIN_MS = 60_000
T0_MS = int(pd.Timestamp("2024-01-01", tz="UTC").value) // NS_PER_MS


def kline(open_ms: int, dur_ms: int, o=100.0, h=110.0, l=90.0, c=105.0, v=1.0) -> list:
    return [open_ms, f"{o}", f"{h}", f"{l}", f"{c}", f"{v}", open_ms + dur_ms - 1, "0", 1, "0", "0", "0"]


class FakeBinance:
    """가짜 fapi. 요청을 기록하고 시나리오대로 응답한다."""

    def __init__(self, *, days: int = 400, minutes_from_ms: int | None = None, n_minutes: int = 0,
                 server_ms: int | None = None, statuses: list[int] | None = None, funding: list[dict] | None = None,
                 daily_rows=None, retry_after: str | None = None):
        self.requests: list[httpx.Request] = []
        self.days = days
        self.minutes_from_ms = minutes_from_ms
        self.n_minutes = n_minutes
        self.server_ms = server_ms
        self.statuses = list(statuses or [])
        self.funding_rows = funding or []
        self.daily_rows = daily_rows
        self.retry_after = retry_after

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.statuses:
            code = self.statuses.pop(0)
            if code != 200:
                headers = {"Retry-After": self.retry_after} if self.retry_after else {}
                return httpx.Response(code, json={"code": -1, "msg": "x"}, headers=headers)
        p = request.url.path
        q = request.url.params
        if p == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": self.server_ms})
        if p == "/fapi/v1/fundingRate":
            s, e = int(q["startTime"]), int(q["endTime"])
            rows = [r for r in self.funding_rows if s <= r["fundingTime"] <= e][: int(q["limit"])]
            return httpx.Response(200, json=rows)
        if p == "/fapi/v1/klines":
            if q["interval"] == "1d":
                if self.daily_rows is not None:
                    return httpx.Response(200, json=self.daily_rows)
                end = int(q["endTime"])
                opens = [T0_MS + i * DAY_MS for i in range(self.days)]
                rows = [kline(o, DAY_MS) for o in opens if o <= end][-int(q["limit"]):]
                return httpx.Response(200, json=rows)
            s, e = int(q["startTime"]), int(q["endTime"])
            opens = [self.minutes_from_ms + i * MIN_MS for i in range(self.n_minutes)]
            rows = [kline(o, MIN_MS) for o in opens if s <= o <= e][: int(q["limit"])]
            return httpx.Response(200, json=rows)
        return httpx.Response(404)


def live(fake: FakeBinance, now_ns: int, **cfg_kw) -> tuple[LiveBinance, list[float]]:
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(fake))
    cfg = MarketDataConfig(**cfg_kw)
    return LiveBinance(cfg, FakeClock(now_ns), client, sleep=sleeps.append), sleeps


# ---------------------------------------------------------------------------
# LiveBinance
# ---------------------------------------------------------------------------


def test_live_is_marketdata_and_daily_drops_unclosed_bar():
    fake = FakeBinance(days=400)
    # 지금 = 마지막(399번째) 일봉 진행 중 → 그 봉은 버리고 398번째까지
    now_ns = (T0_MS + 399 * DAY_MS + 5 * 3600_000) * NS_PER_MS
    md, _ = live(fake, now_ns)
    assert isinstance(md, MarketData)
    df = md.daily_bars(now_ns)
    assert len(df) == 399 and int(df["close_ns"].iloc[-1]) == (T0_MS + 399 * DAY_MS) * NS_PER_MS
    assert (df["close_ns"] <= now_ns).all()
    # until으로 더 앞에서 자르기
    until = (T0_MS + 300 * DAY_MS) * NS_PER_MS + 60 * 10**9
    df2 = md.daily_bars(until)
    assert int(df2["close_ns"].iloc[-1]) == (T0_MS + 300 * DAY_MS) * NS_PER_MS
    req = fake.requests[-1]
    assert req.url.scheme == "https" and req.url.host == "fapi.binance.com"
    assert req.url.params["symbol"] == "BTCUSDT" and req.url.params["interval"] == "1d"


def test_no_api_key_or_signature_sent():
    fake = FakeBinance(days=30, server_ms=T0_MS + 40 * DAY_MS)
    now_ns = (T0_MS + 40 * DAY_MS) * NS_PER_MS
    md, _ = live(fake, now_ns)
    md.daily_bars(now_ns)
    md.server_time_ns()
    for r in fake.requests:
        lower = {k.lower() for k in r.headers}
        assert "x-mbx-apikey" not in lower and "authorization" not in lower
        assert "signature" not in r.url.params and "timestamp" not in r.url.params
        assert r.method == "GET"


def test_http_base_url_rejected():
    with pytest.raises(MarketDataError):
        LiveBinance(MarketDataConfig(base_url="http://fapi.binance.com"), FakeClock(0), httpx.Client())


def test_gap_duplicate_and_bad_prices_rejected():
    now_ns = (T0_MS + 10 * DAY_MS) * NS_PER_MS
    gap = [kline(T0_MS, DAY_MS), kline(T0_MS + 2 * DAY_MS, DAY_MS)]
    dup = [kline(T0_MS, DAY_MS), kline(T0_MS, DAY_MS)]
    neg = [kline(T0_MS, DAY_MS, o=-1.0)]
    hl = [kline(T0_MS, DAY_MS, h=100.0, c=105.0)]            # high < close
    wrong_len = [[T0_MS, "1", "1", "1", "1", "1", T0_MS + 3600_000 - 1]]
    for rows in (gap, dup, neg, hl, wrong_len, [["x"]], {"a": 1}):
        md, _ = live(FakeBinance(daily_rows=rows), now_ns)
        with pytest.raises(MarketDataError):
            md.daily_bars(now_ns)


def test_retry_on_429_and_5xx_with_backoff_and_retry_after():
    now_ns = (T0_MS + 40 * DAY_MS) * NS_PER_MS
    fake = FakeBinance(days=30, statuses=[429, 503, 200], retry_after="7")
    md, sleeps = live(fake, now_ns, max_retries=3)
    df = md.daily_bars(now_ns)
    assert len(df) == 30 and len(fake.requests) == 3
    assert sleeps == [7.0, 7.0]                                # max(2**i, Retry-After)
    fake = FakeBinance(days=30, statuses=[500, 502])
    md, sleeps = live(fake, now_ns, max_retries=3)
    md.daily_bars(now_ns)
    assert sleeps == [1.0, 2.0]


def test_retry_exhausted_and_transport_errors():
    now_ns = (T0_MS + 40 * DAY_MS) * NS_PER_MS
    fake = FakeBinance(statuses=[500, 500, 500])
    md, sleeps = live(fake, now_ns, max_retries=2)
    with pytest.raises(MarketDataError, match="재시도 소진"):
        md.daily_bars(now_ns)
    assert len(fake.requests) == 3 and sleeps == [1.0, 2.0]

    calls = []

    def boom(request):
        calls.append(request)
        raise httpx.ConnectError("down")

    md = LiveBinance(MarketDataConfig(max_retries=1), FakeClock(now_ns),
                     httpx.Client(transport=httpx.MockTransport(boom)), sleep=lambda s: None)
    with pytest.raises(MarketDataError):
        md.daily_bars(now_ns)
    assert len(calls) == 2


def test_418_stops_immediately_and_4xx_not_retried():
    now_ns = (T0_MS + 40 * DAY_MS) * NS_PER_MS
    fake = FakeBinance(statuses=[418, 200])
    md, sleeps = live(fake, now_ns, max_retries=5)
    with pytest.raises(MarketDataError, match="418"):
        md.daily_bars(now_ns)
    assert len(fake.requests) == 1 and sleeps == []
    fake = FakeBinance(statuses=[400, 200])
    md, sleeps = live(fake, now_ns, max_retries=5)
    with pytest.raises(MarketDataError, match="400"):
        md.daily_bars(now_ns)
    assert len(fake.requests) == 1


def test_redirect_not_followed():
    def redirect(request):
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    md = LiveBinance(MarketDataConfig(), FakeClock(10**18), httpx.Client(transport=httpx.MockTransport(redirect)),
                     sleep=lambda s: None)
    with pytest.raises(MarketDataError):
        md.daily_bars(10**18)


def test_minute_bars_paginate_and_drop_unclosed():
    start_ms = T0_MS
    fake = FakeBinance(minutes_from_ms=start_ms, n_minutes=4000)
    now_ns = (start_ms + 3200 * MIN_MS + 30_000) * NS_PER_MS   # 3200번째 봉 진행 중
    md, _ = live(fake, now_ns)
    df = md.minute_bars(start_ms * NS_PER_MS, now_ns + 10 * NS_PER_MIN)
    assert len(df) == 3200
    assert int(df["open_ns"].iloc[0]) == start_ms * NS_PER_MS
    assert (df["close_ns"] <= now_ns).all()
    assert len([r for r in fake.requests if r.url.params.get("interval") == "1m"]) == 3
    # start 이전 봉은 없음, 범위가 비면 빈 프레임
    df2 = md.minute_bars((start_ms + 10 * MIN_MS) * NS_PER_MS, (start_ms + 20 * MIN_MS) * NS_PER_MS)
    assert len(df2) == 10 and int(df2["open_ns"].iloc[0]) == (start_ms + 10 * MIN_MS) * NS_PER_MS
    assert len(md.minute_bars(5, 5)) == 0


def test_funding_floored_to_hour_and_windowed():
    base = T0_MS
    rows = [{"symbol": "BTCUSDT", "fundingTime": base + k * 8 * 3600_000 + 7, "fundingRate": "0.0001",
             "markPrice": "1"} for k in range(6)]
    now_ns = (base + 3 * DAY_MS) * NS_PER_MS
    md, _ = live(FakeBinance(funding=rows), now_ns)
    f = md.funding(base * NS_PER_MS, (base + 16 * 3600_000) * NS_PER_MS)
    assert list(f.columns) == ["time_ns", "rate", "synthetic"]
    # start < t ≤ until (start 시각 정각 펀딩은 제외)
    assert f["time_ns"].tolist() == [(base + 8 * 3600_000) * NS_PER_MS, (base + 16 * 3600_000) * NS_PER_MS]
    assert f["rate"].tolist() == [0.0001, 0.0001]
    bad = [dict(rows[0], fundingTime=base + 5 * 60_000)]
    md, _ = live(FakeBinance(funding=bad), now_ns)
    with pytest.raises(MarketDataError):
        md.funding((base - 1) * NS_PER_MS, (base + 3600_000) * NS_PER_MS)


def test_clock_skew_check():
    now_ns = (T0_MS + 1000) * NS_PER_MS
    md, _ = live(FakeBinance(server_ms=T0_MS + 1500), now_ns)
    assert md.check_clock() == 500
    md, _ = live(FakeBinance(server_ms=T0_MS + 3000), now_ns)
    with pytest.raises(MarketDataError, match="시계 오차"):
        md.check_clock()
    md, _ = live(FakeBinance(server_ms=T0_MS - 2000), now_ns)
    with pytest.raises(MarketDataError):
        md.check_clock()


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def test_replay_never_returns_future(trend_market_small):
    m = trend_market_small
    d0 = int(m.bars["1d"]["close_ns"].iloc[120])
    clock = FakeClock(d0 + 60 * 10**9)
    rp = Replay.from_frames(m.bars["1d"], m.exec_bars, m.funding, clock)
    assert isinstance(rp, MarketData) and rp.server_time_ns() is None
    now = clock.now_ns()
    daily = rp.daily_bars(now)
    assert len(daily) == 121 and int(daily["close_ns"].iloc[-1]) == d0
    mins = rp.minute_bars(d0 - NS_PER_DAY, now)
    assert len(mins) == 1441 and int(mins["close_ns"].max()) <= now
    f = rp.funding(d0 - NS_PER_DAY, now)
    assert (f["time_ns"] > d0 - NS_PER_DAY).all() and (f["time_ns"] <= now).all() and len(f) == 3
    for call in (lambda: rp.daily_bars(now + 1), lambda: rp.minute_bars(d0, now + NS_PER_MIN),
                 lambda: rp.funding(d0, now + 1)):
        with pytest.raises(MarketDataError, match="미래"):
            call()
    assert rp.max_until_ns == now
    # 시계를 움직이면 그만큼만 더 보인다
    clock.advance(NS_PER_DAY)
    assert len(rp.daily_bars(clock.now_ns())) == 122


def test_replay_matches_frame_market_slices(trend_market_small):
    from bot.tests.conftest import frame_market_from

    m = trend_market_small
    clock = FakeClock(int(m.bars["1d"]["close_ns"].iloc[-1]))
    rp = Replay.from_frames(m.bars["1d"], m.exec_bars, m.funding, clock)
    fm = frame_market_from(m, clock)
    rng = np.random.default_rng(0)
    lo, hi = int(m.exec_bars["open_ns"].iloc[0]), clock.now_ns()
    for _ in range(20):
        a, b = sorted(int(x) for x in rng.integers(lo, hi, size=2))
        pd.testing.assert_frame_equal(rp.minute_bars(a, b), fm.minute_bars(a, b))
        pd.testing.assert_frame_equal(rp.funding(a, b), fm.funding(a, b))
        pd.testing.assert_frame_equal(rp.daily_bars(b), fm.daily_bars(b))


def test_replay_daily_from_and_bad_input(trend_market_small):
    m = trend_market_small
    clock = FakeClock(int(m.bars["1d"]["close_ns"].iloc[-1]))
    start = int(m.bars["1d"]["open_ns"].iloc[50])
    rp = Replay.from_frames(m.bars["1d"], m.exec_bars, m.funding, clock, daily_from_ns=start)
    assert int(rp.daily_bars(clock.now_ns())["open_ns"].iloc[0]) == start
    with pytest.raises(MarketDataError):
        Replay.from_frames(m.bars["1d"].drop(m.bars["1d"].index[10]), m.exec_bars, m.funding, clock)


@pytest.mark.skipif(not (C.DATA_DIR / "BTCUSDT_1d.csv.gz").exists(), reason="data/binance 없음")
def test_replay_file_daily_equals_load_klines():
    want = D.load_klines("1d", cache_dir=None)
    clock = FakeClock(int(want["close_ns"].iloc[-1]) + 60 * 10**9)
    rp = Replay(C.DATA_DIR, clock)
    pd.testing.assert_frame_equal(rp.daily_bars(clock.now_ns()), want)
    mid = int(want["close_ns"].iloc[500])
    got = rp.daily_bars(mid)
    assert len(got) == 501 and (got["close_ns"] <= mid).all()
    f = rp.funding(mid - NS_PER_DAY, mid)
    assert len(f) == 3
