"""공용 합성 데이터 도우미 — 모든 테스트가 같이 쓴다 (설계 담당 소유).

쓰는 법
    from backtest.tests.conftest import make_bars, bars_from_path, random_walk_bars, make_market, ...
또는 fixture(rng, small_bars, market_small, market_factory)를 테스트 인자로 받는다.

- 모든 봉 도우미는 backtest.types의 표준 봉 프레임을 돌려준다(types.check_bars_frame 통과):
  인덱스 = open_time DatetimeIndex(UTC, ns), 열 open·high·low·close·volume(float64), open_ns·close_ns(int64).
- 시각 인자는 문자열('2024-01-01 00:00', UTC로 해석) 또는 int ns.
- 난수는 seed로 고정한다(결정적). session fixture(market_small)는 여러 테스트가 공유하므로 수정하지 말 것.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import types as T

T0 = "2024-01-01 00:00"  # 기본 시작 시각 (UTC)


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 실데이터·전체 실행처럼 오래 걸리는 테스트 (-m 'not slow'로 뺄 수 있음)")


# ---------------------------------------------------------------------------
# 기본 도우미
# ---------------------------------------------------------------------------


def ns(value) -> int:
    """시각 → int64 ns (UTC). int면 그대로."""
    if isinstance(value, (int, np.integer)):
        return int(value)
    return C.ts_ns(value)


def _frame(open_ns, o, h, l, c, v, dur_ns) -> pd.DataFrame:
    df = T.make_bars_frame(open_ns, o, h, l, c, v, dur_ns)
    T.check_bars_frame(df, contiguous=True)
    return df


def make_bars(rows=None, *, closes=None, start=T0, tf: str = "1h", volume=100.0, wick: float = 0.0) -> pd.DataFrame:
    """지정한 가격으로 표준 봉 프레임을 만든다.

    rows  : (open, high, low, close) 또는 (open, high, low, close, volume) 튜플 목록 — 봉을 정확히 지정할 때.
    closes: 종가 목록 — open = 직전 종가(첫 봉은 자기 종가), high/low = max/min(open, close) × (1 ± wick).
    volume: 스칼라 또는 봉별 목록 (rows에 거래량이 없을 때 사용).
    예) make_bars([(100, 101, 99, 100.5), (100.5, 102, 100, 101)], tf="1h")
        make_bars(closes=[100, 101, 102], volume=[10, 20, 30])
    """
    if (rows is None) == (closes is None):
        raise ValueError("rows와 closes 중 하나만 준다")
    if rows is not None:
        arr = np.asarray(rows, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] not in (4, 5):
            raise ValueError("rows는 (o,h,l,c) 또는 (o,h,l,c,v) 튜플 목록")
        o, h, l, c = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
        v = arr[:, 4] if arr.shape[1] == 5 else np.broadcast_to(np.asarray(volume, dtype=np.float64), o.shape)
    else:
        c = np.asarray(closes, dtype=np.float64)
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) * (1.0 + wick)
        l = np.minimum(o, c) * (1.0 - wick)
        v = np.broadcast_to(np.asarray(volume, dtype=np.float64), c.shape)
    n = len(c)
    dur = C.TF_NS[tf]
    open_ns = ns(start) + dur * np.arange(n, dtype=np.int64)
    return _frame(open_ns, o, h, l, c, np.array(v, dtype=np.float64), dur)


def bars_from_path(anchors, legs=5, *, start=T0, tf: str = "1h", volume=100.0, wick: float = 0.0) -> pd.DataFrame:
    """꺾은선 가격 경로로 봉을 만든다: anchors[0]에서 시작해 각 anchor까지 legs개 봉으로 직선 이동(종가 기준).

    legs는 정수(모든 구간 같음) 또는 구간별 목록. 예) bars_from_path([100, 110, 105, 120], legs=[5, 3, 6])
    봉 수 = 1 + sum(legs). volume은 스칼라 또는 봉별 목록.
    """
    anchors = [float(a) for a in anchors]
    seg = [legs] * (len(anchors) - 1) if np.isscalar(legs) else list(legs)
    if len(seg) != len(anchors) - 1:
        raise ValueError("legs 개수 = anchors 개수 − 1")
    closes = [anchors[0]]
    for a, b, k in zip(anchors[:-1], anchors[1:], seg):
        closes.extend(np.linspace(a, b, int(k) + 1)[1:].tolist())
    return make_bars(closes=np.round(closes, 1), start=start, tf=tf, volume=volume, wick=wick)


def random_walk_bars(n: int, *, seed: int = 0, start=T0, tf: str = "1h", p0: float = 30000.0,
                     sigma: float = 0.004, trend_len: int = 150, trend_strength: float = 0.25,
                     burst_prob: float = 0.01, burst_len=1, burst_mult: float = 4.0,
                     burst_drift: float = 2.5, base_volume: float = 100.0) -> pd.DataFrame:
    """구조(추세·거래량 급증)가 있는 무작위 봉. 가격은 0.1 단위, OHLC 논리를 항상 만족한다.

    - trend_len 봉마다 추세 방향(−1/0/+1) × trend_strength × sigma의 표류를 고른다.
    - 봉마다 burst_prob 확률로 "급증 구간"을 시작: 길이 burst_len(정수 또는 (최소, 최대) 범위에서 무작위),
      거래량 × burst_mult, 수익률 = 방향 × burst_drift × sigma(+잡음). 기준봉·음봉 급증 같은 모양을 만든다.
    """
    rng = np.random.default_rng(seed)
    n_reg = n // max(trend_len, 1) + 1
    drift = np.repeat(rng.choice([-1.0, 0.0, 1.0], size=n_reg), trend_len)[:n] * trend_strength * sigma
    ret = drift + sigma * rng.standard_normal(n)
    vol = base_volume * np.exp(0.3 * rng.standard_normal(n))
    burst = np.zeros(n, dtype=bool)
    starts = np.flatnonzero(rng.random(n) < burst_prob)
    lo, hi = (burst_len, burst_len) if np.isscalar(burst_len) else burst_len
    lengths = rng.integers(int(lo), int(hi) + 1, size=len(starts))
    for s, blen in zip(starts, lengths):
        sign = np.sign(drift[s]) or rng.choice([-1.0, 1.0])
        e = min(n, s + int(blen))
        ret[s:e] = sign * burst_drift * sigma + 0.3 * sigma * rng.standard_normal(e - s)
        burst[s:e] = True
    vol[burst] *= burst_mult
    close = np.round(p0 * np.exp(np.cumsum(ret)), 1)
    open_ = np.r_[round(p0, 1), close[:-1]]
    up = np.abs(rng.normal(0.0, sigma / 2, n))
    dn = np.abs(rng.normal(0.0, sigma / 2, n))
    high = np.round(np.maximum(open_, close) * (1 + up), 1)
    low = np.round(np.minimum(open_, close) * (1 - dn), 1)
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    dur = C.TF_NS[tf]
    open_ns = ns(start) + dur * np.arange(n, dtype=np.int64)
    return _frame(open_ns, open_, high, low, close, np.round(vol, 3), dur)


# ---------------------------------------------------------------------------
# 간격 바꾸기 (여러 간격이 서로 맞는 합성 시장을 만들 때)
# ---------------------------------------------------------------------------


def aggregate_bars(bars: pd.DataFrame, tf: str) -> pd.DataFrame:
    """작은 봉 → 큰 봉 (§1 규칙: 시가 첫값, 고가 최대, 저가 최소, 종가 마지막, 거래량 합).

    경계는 UTC epoch 기준 TF_NS[tf] 배수. 구성 봉 길이의 합이 TF_NS[tf]인(완전한) 구간만 남긴다.
    (테스트 데이터용 간단 구현. 제품 코드는 data.resample_bars.)
    """
    tf_ns = C.TF_NS[tf]
    o_ns = bars["open_ns"].to_numpy()
    dur = bars["close_ns"].to_numpy() - o_ns
    key = o_ns // tf_ns
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], len(key)]
    o = bars["open"].to_numpy()[starts]
    c = bars["close"].to_numpy()[ends - 1]
    h = np.maximum.reduceat(bars["high"].to_numpy(), starts)
    l = np.minimum.reduceat(bars["low"].to_numpy(), starts)
    v = np.add.reduceat(bars["volume"].to_numpy(), starts)
    dsum = np.add.reduceat(dur, starts)
    keep = (dsum == tf_ns) & (o_ns[starts] == key[starts] * tf_ns)
    return _frame(key[starts][keep] * tf_ns, o[keep], h[keep], l[keep], c[keep], v[keep], tf_ns)


def split_bars(bars: pd.DataFrame, sub_tf: str = "1m") -> pd.DataFrame:
    """큰 봉 → 작은 봉 (다시 합치면 원래 OHLC가 정확히 나온다). 거래량은 똑같이 나눈다.

    봉 안 경로: 양봉(종가 ≥ 시가)은 시가 → 저가 → 고가 → 종가, 음봉은 시가 → 고가 → 저가 → 종가의 꺾은선.
    봉 하나당 작은 봉 수 m은 3 이상이어야 한다(5m→1m = 5, 1h→15m = 4 …).
    """
    sub = C.TF_NS[sub_tf]
    durs = np.unique(bars["close_ns"].to_numpy() - bars["open_ns"].to_numpy())
    if len(durs) != 1 or durs[0] % sub:
        raise ValueError("split_bars: 봉 길이가 하나이고 sub_tf의 배수여야 한다")
    m = int(durs[0] // sub)
    if m < 3:
        raise ValueError("split_bars: 작은 봉이 3개 이상이어야 한다")
    o, h, l, c = (bars[k].to_numpy() for k in ("open", "high", "low", "close"))
    bull = c >= o
    anchors = np.stack([o, np.where(bull, l, h), np.where(bull, h, l), c], axis=1)  # (n, 4)
    a1, a2 = m // 3, (2 * m) // 3
    xs = np.array([0, a1, a2, m], dtype=np.float64)
    w = np.zeros((m + 1, 4))
    for k in range(m + 1):
        seg = min(np.searchsorted(xs, k, side="right") - 1, 2)
        t = (k - xs[seg]) / (xs[seg + 1] - xs[seg])
        w[k, seg], w[k, seg + 1] = 1.0 - t, t
    path = anchors @ w.T  # (n, m+1)
    path[:, 1:-1] = np.clip(np.round(path[:, 1:-1], 1), l[:, None], h[:, None])
    path[:, [0, a1, a2, m]] = anchors  # 기준점은 정확히
    so, sc = path[:, :-1].ravel(), path[:, 1:].ravel()
    sv = np.repeat(bars["volume"].to_numpy() / m, m)
    open_ns = (bars["open_ns"].to_numpy()[:, None] + sub * np.arange(m)[None, :]).ravel()
    return _frame(open_ns, so, np.maximum(so, sc), np.minimum(so, sc), sc, sv, sub)


def make_exec_bars(*frames: pd.DataFrame) -> pd.DataFrame:
    """실행 봉 프레임들(예: 5분봉 앞부분 + 1분봉 뒷부분)을 시간순으로 잇는다. 빈 구간이 있으면 ValueError."""
    parts = [f for f in frames if len(f)]
    df = pd.concat(parts) if parts else frames[0]
    out = T.make_bars_frame(df["open_ns"].to_numpy(), df["open"].to_numpy(), df["high"].to_numpy(),
                            df["low"].to_numpy(), df["close"].to_numpy(), df["volume"].to_numpy(),
                            df["close_ns"].to_numpy() - df["open_ns"].to_numpy())
    T.check_bars_frame(out, contiguous=True)
    return out


def make_funding(start, end, *, rate=C.FUNDING_FALLBACK_RATE, every_h: int = 8,
                 synthetic: bool = False) -> pd.DataFrame:
    """펀딩 프레임: start 이상 end 이하의 every_h시간 격자(UTC 00시 기준) 시각마다 rate.

    rate는 스칼라 또는 시각 수만큼의 목록/배열.
    """
    step = every_h * C.NS_PER_HOUR
    t0 = -(-ns(start) // step) * step
    times = np.arange(t0, ns(end) + 1, step, dtype=np.int64)
    rates = np.broadcast_to(np.asarray(rate, dtype=np.float64), times.shape)
    df = T.make_funding_frame(times, rates, np.full(times.shape, synthetic))
    T.check_funding_frame(df)
    return df


# ---------------------------------------------------------------------------
# 합성 시장 (여러 간격 + 실행 봉 + 펀딩)
# ---------------------------------------------------------------------------


def make_market(days: int = 120, *, seed: int = 0, start="2023-09-01", one_minute_from=None,
                tfs: tuple[str, ...] = ("15m", "1h", "4h", "1d"), funding_rate=C.FUNDING_FALLBACK_RATE,
                sigma_5m: float = 0.0015, p0: float = 30000.0) -> T.MarketData:
    """서로 맞는 합성 MarketData.

    - 5분봉 무작위 경로(days × 288개, 추세·1~4시간짜리 급증 구간 포함)를 만들고 tfs 간격으로 합친다.
    - 실행 봉: one_minute_from이 None이면 전부 5분봉, 주면 그 시각부터 1분봉(5분봉을 split_bars) — 실데이터 병합 규칙과 같은 모양.
    - 펀딩: 8시간마다 funding_rate. events_ns = None.
    start는 UTC 자정이어야 한다(일봉 경계를 맞추려고).
    """
    if ns(start) % C.NS_PER_DAY:
        raise ValueError("make_market: start는 UTC 자정이어야 한다")
    base = random_walk_bars(days * 288, seed=seed, start=start, tf="5m", p0=p0, sigma=sigma_5m,
                            trend_len=288 * 3, trend_strength=0.03, burst_prob=0.0012, burst_len=(12, 48),
                            burst_mult=4.0, burst_drift=0.6)
    bars = {tf: aggregate_bars(base, tf) for tf in tfs}
    if one_minute_from is None:
        exec_bars = base
    else:
        t1 = ns(one_minute_from)
        before = base[base["open_ns"] < t1]
        after = base[base["open_ns"] >= t1]
        exec_bars = make_exec_bars(before, split_bars(after, "1m")) if len(after) else before
    end = int(base["close_ns"].iloc[-1])
    funding = make_funding(start, end, rate=funding_rate)
    return T.MarketData(bars=bars, exec_bars=exec_bars, funding=funding, events_ns=None)


def truncate_market(market: T.MarketData, t_ns) -> T.MarketData:
    """t_ns까지 마감된 봉(close_ns ≤ t_ns)과 그때까지의 펀딩(time_ns ≤ t_ns)만 남긴 복사본 (미래 참조 테스트용)."""
    t = ns(t_ns)
    bars = {tf: b[b["close_ns"] <= t] for tf, b in market.bars.items()}
    exec_bars = market.exec_bars[market.exec_bars["close_ns"] <= t]
    funding = market.funding[market.funding["time_ns"] <= t].reset_index(drop=True)
    return T.MarketData(bars=bars, exec_bars=exec_bars, funding=funding, events_ns=market.events_ns)


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def rng() -> np.random.Generator:
    """테스트용 고정 난수."""
    return np.random.default_rng(12345)


@pytest.fixture
def small_bars() -> pd.DataFrame:
    """1시간봉 10개 (손으로 확인하기 쉬운 값)."""
    return make_bars(closes=[100, 101, 102, 101, 100, 99, 100, 101, 103, 102], tf="1h",
                     volume=[10, 12, 9, 11, 10, 30, 10, 9, 12, 11], wick=0.001)


@pytest.fixture(scope="session")
def market_small() -> T.MarketData:
    """150일 합성 시장(2023-08-01 시작, 2023-10-01부터 1분 실행 봉). 공유 객체이므로 수정 금지."""
    return make_market(days=150, seed=7, start="2023-08-01", one_minute_from="2023-10-01")


@pytest.fixture
def market_factory():
    """make_market를 돌려준다: market_factory(days=…, seed=…)."""
    return make_market
