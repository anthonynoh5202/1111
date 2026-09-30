"""데이터 적재 테스트 (T-DATA, DESIGN §9).

- 합성 CSV(바이낸스 형식)를 tmp_path에 써서: 왕복 정확도, 중복·빈 구간·단위 오류 검출, 1분봉 연도 파일 병합,
  실행 봉 병합, 펀딩 내림·대체값, 이벤트 파일, 재표본, 캐시(두 번째는 CSV를 안 읽음·서명 변경 시 재생성)
- 실데이터: 행 수·기간·경계(DESIGN §6.3 사실), 5m→1h 불일치 ≤ quality_report. 실행 봉 전체는 @slow.
  실데이터 테스트는 기본 캐시(data/cache/)를 쓴다(처음 한 번만 CSV를 읽음).
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import data as D
from backtest import types as T
from backtest.tests.conftest import (aggregate_bars, make_bars, make_exec_bars, ns, random_walk_bars,
                                     split_bars)

HAVE_REAL = all((C.DATA_DIR / f).exists() for f in (
    "BTCUSDT_5m.csv.gz", "BTCUSDT_15m.csv.gz", "BTCUSDT_1h.csv.gz", "BTCUSDT_4h.csv.gz", "BTCUSDT_1d.csv.gz",
    "BTCUSDT_fundingRate.csv.gz")) and bool(list(C.DATA_DIR.glob("BTCUSDT_1m_*.csv.gz")))
real = pytest.mark.skipif(not HAVE_REAL, reason="data/binance 실데이터 없음")


# ---------------------------------------------------------------------------
# 합성 파일 도우미 (바이낸스 CSV 형식 그대로)
# ---------------------------------------------------------------------------


def write_klines(path, bars: pd.DataFrame) -> None:
    """표준 봉 프레임 → 바이낸스 캔들 CSV(.csv.gz). close_time = 끝 − 1ms (로더는 쓰지 않음)."""
    o_ms = bars["open_ns"].to_numpy() // 1_000_000
    df = pd.DataFrame({
        "open_time": o_ms,
        "open": bars["open"].to_numpy(), "high": bars["high"].to_numpy(),
        "low": bars["low"].to_numpy(), "close": bars["close"].to_numpy(),
        "volume": bars["volume"].to_numpy(),
        "close_time": bars["close_ns"].to_numpy() // 1_000_000 - 1,
        "quote_volume": 0.0, "count": 0, "taker_buy_volume": 0.0, "taker_buy_quote_volume": 0.0, "ignore": 0,
    })
    df.to_csv(path, index=False, compression="gzip")


def write_funding(path, times_ns, rates, offsets_ms=0) -> None:
    ms = np.asarray(times_ns, dtype=np.int64) // 1_000_000 + np.asarray(offsets_ms, dtype=np.int64)
    pd.DataFrame({"calc_time": ms, "funding_interval_hours": 8,
                  "last_funding_rate": np.broadcast_to(np.asarray(rates, dtype=float), ms.shape)}).to_csv(
        path, index=False, compression="gzip")


def grid_8h(start, end) -> np.ndarray:
    step = C.FUNDING_INTERVAL_NS
    t0 = -(-ns(start) // step) * step
    return np.arange(t0, ns(end) + 1, step, dtype=np.int64)


@pytest.fixture
def synth(tmp_path):
    """2023-09-30 00:00 ~ 2023-10-02 00:00 합성 시장 파일 묶음(실데이터와 같은 파일 이름·실행 봉 전환 시각 포함)."""
    d = tmp_path / "binance"
    d.mkdir()
    base = random_walk_bars(2 * 288, seed=3, start="2023-09-30", tf="5m", p0=27000.0)
    one = split_bars(base[base["open_ns"] >= C.EXEC_SWITCH_NS], "1m")
    write_klines(d / "BTCUSDT_5m.csv.gz", base)
    write_klines(d / "BTCUSDT_1m_2023.csv.gz", one)
    for tf in ("15m", "1h", "4h", "1d"):
        write_klines(d / f"BTCUSDT_{tf}.csv.gz", aggregate_bars(base, tf))
    times = grid_8h("2023-09-30", "2023-10-02")
    write_funding(d / "BTCUSDT_fundingRate.csv.gz", times, np.linspace(-1e-4, 3e-4, len(times)),
                  offsets_ms=np.arange(len(times)) % 48)   # 실데이터처럼 0~47ms 늦은 calc_time
    (d / "BTCUSDT_metrics.csv.gz").write_bytes(b"not used")  # 입력이 아닌 파일
    return {"dir": d, "base": base, "one": one, "cache": tmp_path / "cache", "funding_times": times}


# ---------------------------------------------------------------------------
# load_klines (합성)
# ---------------------------------------------------------------------------


def test_load_klines_roundtrip_exact(tmp_path):
    bars = random_walk_bars(300, seed=8, tf="1h", start="2024-01-01")
    write_klines(tmp_path / "BTCUSDT_1h.csv.gz", bars)
    got = D.load_klines("1h", data_dir=tmp_path, cache_dir=None)
    pd.testing.assert_frame_equal(got, bars, check_exact=True)   # 가격·시각이 비트 단위로 같다
    assert list(got.columns) == list(T.BAR_COLUMNS)
    assert got.index.name == "open_time" and got.index.unit == "ns" and str(got.index.tz) == "UTC"
    T.check_bars_frame(got, dur_ns=C.TF_NS["1h"])
    assert (got["close_ns"] - got["open_ns"] == C.TF_NS["1h"]).all()   # close_ns = 시작 + 봉 길이 (−1ms 아님)


def test_decimal_prices_parse_to_round_price_values(tmp_path):
    rows = [(42314.3, 42320.1, 42310.7, 42318.9, 1.001), (42318.9, 42330.0, 42300.2, 42301.4, 2.5)]
    write_klines(tmp_path / "BTCUSDT_1h.csv.gz", make_bars(rows))
    text = pd.read_csv(tmp_path / "BTCUSDT_1h.csv.gz", dtype=str)
    got = D.load_klines("1h", data_dir=tmp_path, cache_dir=None)
    for col in ("open", "high", "low", "close"):
        # CSV 문자열 → 가장 가까운 double = config.round_price 값 (지정가 등호 경계 보호)
        np.testing.assert_array_equal(got[col].to_numpy(), [float(s) for s in text[col]])
        np.testing.assert_array_equal(got[col].to_numpy(), C.round_price(got[col].to_numpy()))


def test_load_klines_rejects_bad_files(tmp_path):
    bars = random_walk_bars(10, seed=1, tf="1h", start="2024-01-01")
    cases = {
        "dup": pd.concat([bars.iloc[:5], bars.iloc[4:]]),           # 중복 봉
        "gap": pd.concat([bars.iloc[:4], bars.iloc[5:]]),           # 빈 구간
        "misaligned": bars,                                         # 정시가 아닌 시작
    }
    for name, frame in cases.items():
        d = tmp_path / name
        d.mkdir()
        write_klines(d / "BTCUSDT_1h.csv.gz", frame)
        if name == "misaligned":
            df = pd.read_csv(d / "BTCUSDT_1h.csv.gz")
            df["open_time"] += 30 * 60 * 1000
            df.to_csv(d / "BTCUSDT_1h.csv.gz", index=False, compression="gzip")
        with pytest.raises(ValueError):
            D.load_klines("1h", data_dir=d, cache_dir=None)
    d = tmp_path / "micro"                                          # 마이크로초로 저장된 시각 → 단위 오류
    d.mkdir()
    write_klines(d / "BTCUSDT_1h.csv.gz", bars)
    df = pd.read_csv(d / "BTCUSDT_1h.csv.gz")
    df["open_time"] *= 1000
    df.to_csv(d / "BTCUSDT_1h.csv.gz", index=False, compression="gzip")
    with pytest.raises(ValueError, match="ms"):
        D.load_klines("1h", data_dir=d, cache_dir=None)
    with pytest.raises(FileNotFoundError):
        D.load_klines("4h", data_dir=tmp_path, cache_dir=None)
    with pytest.raises(ValueError):
        D.load_klines("2h", data_dir=tmp_path, cache_dir=None)


def test_load_klines_1m_joins_year_files(tmp_path):
    one = random_walk_bars(240, seed=2, tf="1m", start="2023-12-31 22:00")  # 해를 넘는 4시간
    cut = int(np.searchsorted(one["open_ns"].to_numpy(), ns("2024-01-01")))
    write_klines(tmp_path / "BTCUSDT_1m_2024.csv.gz", one.iloc[cut:])
    write_klines(tmp_path / "BTCUSDT_1m_2023.csv.gz", one.iloc[:cut])
    write_klines(tmp_path / "BTCUSDT_1m_extra.csv.gz", one.iloc[:3])      # 연도 이름이 아닌 파일은 무시
    assert [p.name for p in D.kline_files("1m", tmp_path)] == ["BTCUSDT_1m_2023.csv.gz", "BTCUSDT_1m_2024.csv.gz"]
    got = D.load_klines("1m", data_dir=tmp_path, cache_dir=None)
    pd.testing.assert_frame_equal(got, one, check_exact=True)
    write_klines(tmp_path / "BTCUSDT_1m_2024.csv.gz", one.iloc[cut - 1:])  # 경계 봉이 두 파일에 → 중복
    with pytest.raises(ValueError, match="중복"):
        D.load_klines("1m", data_dir=tmp_path, cache_dir=None)


# ---------------------------------------------------------------------------
# 캐시 (T-DATA-4)
# ---------------------------------------------------------------------------


def _count_csv_reads(monkeypatch) -> list:
    calls = []
    real_reader = D._read_kline_csv

    def counting(path):
        calls.append(path.name)
        return real_reader(path)

    monkeypatch.setattr(D, "_read_kline_csv", counting)
    return calls


def test_cache_second_load_skips_csv(tmp_path, monkeypatch):
    bars = random_walk_bars(500, seed=4, tf="15m", start="2024-02-01")
    write_klines(tmp_path / "BTCUSDT_15m.csv.gz", bars)
    cache = tmp_path / "cache"
    calls = _count_csv_reads(monkeypatch)
    first = D.load_klines("15m", data_dir=tmp_path, cache_dir=cache)
    assert calls == ["BTCUSDT_15m.csv.gz"] and (cache / "BTCUSDT_15m.npz").exists()

    def boom(path):
        raise AssertionError(f"캐시가 있는데 CSV를 읽음: {path}")

    monkeypatch.setattr(D, "_read_kline_csv", boom)
    second = D.load_klines("15m", data_dir=tmp_path, cache_dir=cache)
    pd.testing.assert_frame_equal(second, first, check_exact=True)
    pd.testing.assert_frame_equal(second, bars, check_exact=True)
    assert not list(cache.glob("*.tmp"))                                   # 임시 파일이 남지 않음


def test_cache_rebuilds_when_source_changes(tmp_path, monkeypatch):
    bars = random_walk_bars(50, seed=5, tf="1h", start="2024-02-01")
    src = tmp_path / "BTCUSDT_1h.csv.gz"
    write_klines(src, bars)
    cache = tmp_path / "cache"
    calls = _count_csv_reads(monkeypatch)
    D.load_klines("1h", data_dir=tmp_path, cache_dir=cache)
    D.load_klines("1h", data_dir=tmp_path, cache_dir=cache)
    assert len(calls) == 1
    changed = bars.copy()
    changed.loc[changed.index[10], "close"] = changed["close"].iloc[10] + 0.1
    changed.loc[changed.index[10], "high"] = max(changed["high"].iloc[10], changed["close"].iloc[10])
    write_klines(src, changed)
    st = src.stat()
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))  # 서명(수정 시각)이 확실히 바뀌게
    got = D.load_klines("1h", data_dir=tmp_path, cache_dir=cache)
    assert len(calls) == 2                                                 # 서명이 달라 다시 읽음
    assert got["close"].iloc[10] == changed["close"].iloc[10]
    D.load_klines("1h", data_dir=tmp_path, cache_dir=cache)
    assert len(calls) == 2                                                 # 새 캐시 사용


def test_cache_corrupt_file_is_rebuilt_and_none_writes_nothing(tmp_path):
    bars = random_walk_bars(40, seed=6, tf="4h", start="2024-02-01")
    write_klines(tmp_path / "BTCUSDT_4h.csv.gz", bars)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "BTCUSDT_4h.npz").write_bytes(b"garbage")
    got = D.load_klines("4h", data_dir=tmp_path, cache_dir=cache)
    pd.testing.assert_frame_equal(got, bars, check_exact=True)
    with np.load(cache / "BTCUSDT_4h.npz", allow_pickle=False) as z:     # 다시 쓴 캐시는 정상
        assert z["open_ns"].dtype == np.int64 and len(z["close"]) == 40
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    D.load_klines("4h", data_dir=tmp_path, cache_dir=None)               # 캐시 없음 → 아무것도 쓰지 않음
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


# ---------------------------------------------------------------------------
# 실행 봉 병합 (합성, §12.1)
# ---------------------------------------------------------------------------


def test_load_exec_bars_synthetic(synth):
    d, base, one = synth["dir"], synth["base"], synth["one"]
    x = D.load_exec_bars(data_dir=d, cache_dir=None)
    T.check_bars_frame(x, contiguous=True)
    expected = make_exec_bars(base[base["open_ns"] < C.EXEC_SWITCH_NS], one)
    pd.testing.assert_frame_equal(x, expected, check_exact=True)
    k = int(np.searchsorted(x["open_ns"].to_numpy(), C.EXEC_SWITCH_NS))
    assert k == 288 and len(x) == 288 + 1440
    dur = (x["close_ns"] - x["open_ns"]).to_numpy()
    assert (dur[:k] == C.TF_NS["5m"]).all() and (dur[k:] == C.TF_NS["1m"]).all()
    assert x["close_ns"].iloc[k - 1] == x["open_ns"].iloc[k] == C.EXEC_SWITCH_NS
    # 실행 봉을 다시 합치면 15분·1시간봉과 같다 (봉 길이가 섞여도 재표본 가능).
    # 거래량은 split_bars가 v/5로 나눠서 다시 더할 때 반올림 오차만 있다.
    for tf in ("15m", "1h"):
        got, ref = D.resample_bars(x, tf), aggregate_bars(base, tf)
        pd.testing.assert_frame_equal(got.drop(columns="volume"), ref.drop(columns="volume"), check_exact=True)
        np.testing.assert_allclose(got["volume"].to_numpy(), ref["volume"].to_numpy(), rtol=1e-12)


def test_load_exec_bars_switch_rules(synth):
    d = synth["dir"]
    later = C.EXEC_SWITCH_NS + C.NS_PER_HOUR                     # 1분봉은 전환 시각 이후 부분만 쓴다
    x = D.load_exec_bars(switch_ns=later, data_dir=d, cache_dir=None)
    k = int(np.searchsorted(x["open_ns"].to_numpy(), later))
    assert k == 288 + 12 and len(x) == 288 + 12 + 1440 - 60
    with pytest.raises(ValueError):                              # 5분 경계가 아닌 전환 시각
        D.load_exec_bars(switch_ns=C.EXEC_SWITCH_NS + C.NS_PER_MIN, data_dir=d, cache_dir=None)
    with pytest.raises(ValueError):                              # 1분봉이 전환 시각보다 늦게 시작 → 빈 구간
        D.load_exec_bars(switch_ns=C.EXEC_SWITCH_NS - C.NS_PER_HOUR, data_dir=d, cache_dir=None)


# ---------------------------------------------------------------------------
# 펀딩 (§12.2, I-35)
# ---------------------------------------------------------------------------


def test_load_funding_floors_calc_time(synth):
    f = D.load_funding(data_dir=synth["dir"])
    T.check_funding_frame(f)
    np.testing.assert_array_equal(f["time_ns"].to_numpy(), synth["funding_times"])  # 0~47ms → 정시로 내림
    assert not f["synthetic"].any() and len(f) == 7
    assert f["rate"].iloc[0] == pytest.approx(-1e-4)
    assert len(D.load_funding(until_ns=ns("2023-10-05"), data_dir=synth["dir"])) == 7  # 2026-09 전이면 대체값 없음


def test_load_funding_fallback_after_last_real(tmp_path):
    times = grid_8h("2026-08-30", "2026-08-31 16:00")
    write_funding(tmp_path / "BTCUSDT_fundingRate.csv.gz", times, 5e-5, offsets_ms=47)
    f = D.load_funding(until_ns=ns("2026-09-02 00:00"), data_dir=tmp_path)
    T.check_funding_frame(f)
    syn = f[f["synthetic"]]
    assert (~f["synthetic"]).sum() == len(times)
    assert syn["time_ns"].tolist() == [ns("2026-09-01 00:00"), ns("2026-09-01 08:00"), ns("2026-09-01 16:00"),
                                       ns("2026-09-02 00:00")]                   # until 포함
    assert (syn["rate"] == C.FUNDING_FALLBACK_RATE).all()
    assert (f["time_ns"] % C.FUNDING_INTERVAL_NS == 0).all()                    # 00·08·16시 격자
    # 실제 기록이 2026-09 안까지 있으면 그 뒤부터만 대체값
    write_funding(tmp_path / "BTCUSDT_fundingRate.csv.gz", grid_8h("2026-08-31", "2026-09-01 08:00"), 5e-5)
    f2 = D.load_funding(until_ns=ns("2026-09-02 00:00"), data_dir=tmp_path)
    assert f2.loc[f2["synthetic"], "time_ns"].tolist() == [ns("2026-09-01 16:00"), ns("2026-09-02 00:00")]
    assert len(D.load_funding(data_dir=tmp_path)) == 5                           # until 없으면 실제 기록만


def test_load_funding_gap_warns_and_bad_times_raise(tmp_path):
    p = tmp_path / "BTCUSDT_fundingRate.csv.gz"
    write_funding(p, grid_8h("2026-08-18", "2026-08-20"), 1e-4)
    with pytest.warns(RuntimeWarning, match="펀딩 공백"):
        f = D.load_funding(until_ns=ns("2026-09-01 08:00"), data_dir=tmp_path)
    assert f.loc[f["synthetic"], "time_ns"].tolist() == [ns("2026-09-01 00:00"), ns("2026-09-01 08:00")]
    write_funding(p, grid_8h("2026-08-18", "2026-08-20"), 1e-4, offsets_ms=61_000)  # 정시에서 1분 넘게 벗어남
    with pytest.raises(ValueError, match="정시"):
        D.load_funding(data_dir=tmp_path)
    t = grid_8h("2026-08-18", "2026-08-19")
    write_funding(p, np.r_[t, t[-1]], 1e-4, offsets_ms=np.r_[np.zeros(len(t), dtype=np.int64), 30])  # 같은 정시 둘
    with pytest.raises(ValueError, match="같은 정시"):
        D.load_funding(data_dir=tmp_path)


# ---------------------------------------------------------------------------
# 이벤트 파일 (F3, I-49)
# ---------------------------------------------------------------------------


def test_load_events(tmp_path):
    p = tmp_path / "events.csv"
    assert D.load_events(p) is None                                   # 파일 없음 → F3 꺼짐
    p.write_text("time_utc,kind\n2024-03-20T18:00:00Z,FOMC\n2024-01-11 13:30,CPI\n"
                 "2024-02-13T22:30:00+09:00,CPI\n", encoding="utf-8")
    ev = D.load_events(p)
    assert ev.dtype == np.int64
    assert ev.tolist() == [ns("2024-01-11 13:30"), ns("2024-02-13 13:30"), ns("2024-03-20 18:00")]  # 정렬, UTC
    p.write_text("time_utc,kind\n", encoding="utf-8")
    assert D.load_events(p).tolist() == []
    p.write_text("when,kind\n2024-01-01,CPI\n", encoding="utf-8")
    with pytest.raises(ValueError, match="time_utc"):
        D.load_events(p)
    p.write_text("time_utc\nnot-a-date\n", encoding="utf-8")
    with pytest.raises(ValueError):
        D.load_events(p)


# ---------------------------------------------------------------------------
# 재표본 (§1, T-DATA-5)
# ---------------------------------------------------------------------------


def test_resample_hand_example_and_incomplete_buckets():
    rows = [(100, 102, 99, 101, 1), (101, 105, 100, 104, 2), (104, 104.5, 98, 99, 3), (99, 100, 97, 98, 4)]
    five = make_bars(rows, tf="5m", start="2024-01-01 00:00")
    got = D.resample_bars(five, "15m")
    assert len(got) == 1                                                 # 00:15 구간은 봉 1개뿐 → 버림
    r = got.iloc[0]
    assert (r["open"], r["high"], r["low"], r["close"], r["volume"]) == (100, 105, 98, 99, 6)
    assert r["open_ns"] == ns("2024-01-01 00:00") and r["close_ns"] == ns("2024-01-01 00:15")
    late = make_bars(rows + [(98, 99, 96, 97, 5)], tf="5m", start="2024-01-01 00:05")  # 00:05~00:30
    got_late = D.resample_bars(late, "15m")                             # 00:00 구간은 앞이 모자람 → 버림
    assert got_late["open_ns"].tolist() == [ns("2024-01-01 00:15")]
    assert got_late[["open", "high", "low", "close", "volume"]].iloc[0].tolist() == [104, 104.5, 96, 97, 12]
    holes = T.make_bars_frame(five["open_ns"].to_numpy()[[0, 2]], [100, 104], [102, 104.5], [99, 98],
                              [101, 99], [1, 3], C.TF_NS["5m"])        # 가운데 빈 봉 → 버림
    assert len(D.resample_bars(holes, "15m")) == 0
    assert len(D.resample_bars(five.iloc[:0], "1h")) == 0


def test_resample_matches_aggregate_and_arbitrary_interval():
    five = random_walk_bars(12 * 30 + 7, seed=12, tf="5m", start="2024-03-01")
    got = D.resample_bars(five, "1h")
    pd.testing.assert_frame_equal(got, aggregate_bars(five, "1h"), check_exact=True)
    assert len(got) == 30                                                # 끝의 불완전 구간(7봉) 버림
    two = D.resample_bars(got, "2h")                                     # 임의 간격
    assert len(two) == 15 and (two["close_ns"] - two["open_ns"] == 2 * C.NS_PER_HOUR).all()
    np.testing.assert_array_equal(two["open"].to_numpy(), got["open"].to_numpy()[0::2])
    np.testing.assert_array_equal(two["close"].to_numpy(), got["close"].to_numpy()[1::2])
    np.testing.assert_array_equal(two["high"].to_numpy(), np.maximum(got["high"].to_numpy()[0::2],
                                                                     got["high"].to_numpy()[1::2]))
    assert len(D.resample_bars(got, "90m")) == 0                         # 1시간봉으로는 90분봉을 못 만든다
    assert D.tf_to_ns("3d") == 3 * C.NS_PER_DAY and D.tf_to_ns("1h") == C.TF_NS["1h"]
    for bad in ("abc", "0h", "5s", "h"):
        with pytest.raises(ValueError):
            D.tf_to_ns(bad)


# ---------------------------------------------------------------------------
# load_market · data_fingerprint (합성)
# ---------------------------------------------------------------------------


def test_load_market_synthetic(synth):
    d, base = synth["dir"], synth["base"]
    m = D.load_market(data_dir=d, cache_dir=synth["cache"], with_events=False)
    assert isinstance(m, T.MarketData) and set(m.bars) == {"15m", "1h", "4h", "1d"}
    for tf, b in m.bars.items():
        T.check_bars_frame(b, dur_ns=C.TF_NS[tf])
        pd.testing.assert_frame_equal(b, aggregate_bars(base, tf), check_exact=True)
    assert len(m.exec_bars) == 288 + 1440 and m.events_ns is None
    assert m.funding["time_ns"].iloc[-1] <= m.exec_bars["close_ns"].iloc[-1]
    xa = m.exec_arrays()
    assert len(xa) == len(m.exec_bars) and xa.close_ns[-1] == ns("2023-10-02")
    ev, ref = D.load_market(data_dir=d, cache_dir=synth["cache"]).events_ns, D.load_events()  # 기본 경로 이벤트
    assert (ev is None and ref is None) or np.array_equal(ev, ref)


def test_data_fingerprint_synthetic(synth):
    d = synth["dir"]
    fp = D.data_fingerprint(d)
    assert list(fp) == sorted(fp) and "BTCUSDT_metrics.csv.gz" not in fp  # 입력 파일만
    assert set(fp) == {"BTCUSDT_5m.csv.gz", "BTCUSDT_1m_2023.csv.gz", "BTCUSDT_15m.csv.gz", "BTCUSDT_1h.csv.gz",
                       "BTCUSDT_4h.csv.gz", "BTCUSDT_1d.csv.gz", "BTCUSDT_fundingRate.csv.gz"}
    for name, digest in fp.items():
        assert digest == hashlib.sha256((d / name).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 실데이터 (DESIGN §6.3 사실, T-DATA-1·2·3·5)
# ---------------------------------------------------------------------------

FIRST_OPEN_NS = 1_577_836_800 * C.NS_PER_SEC   # 2020-01-01 00:00 UTC


@real
@pytest.mark.parametrize("tf,rows,last_open", [
    ("15m", 236_448, "2026-09-28 23:45"), ("1h", 59_112, "2026-09-28 23:00"),
    ("4h", 14_778, "2026-09-28 20:00"), ("1d", 2_463, "2026-09-28 00:00"),
])
def test_real_klines(tf, rows, last_open):
    b = D.load_klines(tf)
    assert len(b) == rows
    assert b["open_ns"].iloc[0] == FIRST_OPEN_NS and b["open_ns"].iloc[-1] == ns(last_open)
    T.check_bars_frame(b, dur_ns=C.TF_NS[tf])
    assert b.index.unit == "ns" and list(b.columns) == list(T.BAR_COLUMNS)


@real
def test_real_first_1h_bar_values():
    first = D.load_klines("1h").iloc[0]
    # 원본 첫 줄: 1577836800000,7189.43,7190.52,7170.15,7171.55,2449.049
    assert (first["open"], first["high"], first["low"], first["close"], first["volume"]) == (
        7189.43, 7190.52, 7170.15, 7171.55, 2449.049)


@real
def test_real_funding():
    until = ns("2026-09-29 00:00")
    f = D.load_funding(until_ns=until)
    T.check_funding_frame(f)
    real_rows, syn = f[~f["synthetic"]], f[f["synthetic"]]
    assert len(real_rows) == 7_305 and len(syn) == 85
    assert real_rows["time_ns"].iloc[0] == FIRST_OPEN_NS and real_rows["rate"].iloc[0] == -0.00012359
    assert real_rows["time_ns"].iloc[-1] == ns("2026-08-31 16:00")
    assert syn["time_ns"].iloc[0] == ns("2026-09-01 00:00") == C.FUNDING_FALLBACK_FROM_NS
    assert syn["time_ns"].iloc[-1] == until and (syn["rate"] == 0.0001).all()
    assert (f["time_ns"] % C.FUNDING_INTERVAL_NS == 0).all()                   # 모두 00·08·16시 정각
    assert len(D.load_funding()) == 7_305


@real
def test_real_resample_5m_to_1h_within_quality_report():
    one_h = D.load_klines("1h")
    agg = D.resample_bars(D.load_klines("5m"), "1h")
    np.testing.assert_array_equal(agg["open_ns"].to_numpy(), one_h["open_ns"].to_numpy())
    report = json.loads((C.DATA_DIR / "quality_report.json").read_text(encoding="utf-8"))["5m_to_1h"]["mismatches"]
    for col in ("open", "high", "low", "close"):
        n_bad = int((np.abs(agg[col].to_numpy() - one_h[col].to_numpy()) > 1e-6).sum())
        assert n_bad <= report[col], col                                        # open 2·high 2·low 2·close 1


@real
def test_real_fingerprint_covers_inputs_only():
    fp = D.data_fingerprint()
    assert set(fp) == {"BTCUSDT_5m.csv.gz", "BTCUSDT_15m.csv.gz", "BTCUSDT_1h.csv.gz", "BTCUSDT_4h.csv.gz",
                       "BTCUSDT_1d.csv.gz", "BTCUSDT_fundingRate.csv.gz", "BTCUSDT_1m_2023.csv.gz",
                       "BTCUSDT_1m_2024.csv.gz", "BTCUSDT_1m_2025.csv.gz", "BTCUSDT_1m_2026.csv.gz"}
    assert all(len(v) == 64 and int(v, 16) >= 0 for v in fp.values())


@real
@pytest.mark.slow
def test_real_1m_and_exec_bars():
    one = D.load_klines("1m")
    assert len(one) == 1_575_360
    assert one["open_ns"].iloc[0] == C.EXEC_SWITCH_NS and one["open_ns"].iloc[-1] == ns("2026-09-28 23:59")
    x = D.load_exec_bars()
    assert len(x) == 1_969_632 == 394_272 + 1_575_360
    T.check_bars_frame(x, contiguous=True)
    k = int(np.searchsorted(x["open_ns"].to_numpy(), C.EXEC_SWITCH_NS))
    assert k == 394_272
    assert x["open_ns"].iloc[k - 1] == ns("2023-09-30 23:55") and x["close_ns"].iloc[k - 1] == C.EXEC_SWITCH_NS
    assert x["open_ns"].iloc[k] == C.EXEC_SWITCH_NS and x["close_ns"].iloc[k] == ns("2023-10-01 00:01")
    five = D.load_klines("5m")
    for col in T.BAR_COLUMNS:
        np.testing.assert_array_equal(x[col].to_numpy()[:k], five[col].to_numpy()[:k])
        np.testing.assert_array_equal(x[col].to_numpy()[k:], one[col].to_numpy())
    assert x["close_ns"].iloc[-1] == ns("2026-09-29 00:00")


@real
@pytest.mark.slow
def test_real_load_market():
    m = D.load_market()
    assert {tf: len(b) for tf, b in m.bars.items()} == {"15m": 236_448, "1h": 59_112, "4h": 14_778, "1d": 2_463}
    assert len(m.exec_bars) == 1_969_632
    assert len(m.funding) == 7_305 + 85 and m.funding["time_ns"].iloc[-1] == m.exec_bars["close_ns"].iloc[-1]
    if not C.EVENTS_CSV.exists():
        assert m.events_ns is None                                              # §10-2 F3 꺼짐
