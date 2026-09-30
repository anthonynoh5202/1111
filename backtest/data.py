"""데이터 적재 — 바이낸스 캔들·펀딩·이벤트를 표준 프레임으로 읽고 캐시한다.

담당: 데이터·지표. 설계: backtest/DESIGN.md §6.3.
근거: RULES_SPEC §1(시간 규칙), §12.1(실행 봉 병합), §12.2(펀딩 대체값), §6 F3(이벤트 파일).

- 입력 파일 형식은 tools/check_data.py 참고. 캔들은 open_time(ms)만 시각으로 쓰고 close_time 열은 쓰지 않는다
  (표준 프레임의 close_ns = open_ns + 봉 길이).
- 캐시는 data/cache/ 에만 .npz로 쓴다(pyarrow 없음). 원본 파일의 크기·수정 시각이 바뀌면 다시 만든다.
- 네트워크 사용 금지. 모든 시각은 int64 ns(UTC). 표준 프레임은 backtest.types.make_bars_frame으로 만든다.

구현 메모
- 가격은 float_precision='round_trip'으로 읽는다: "42314.30" → 42314.3에 가장 가까운 double (config.round_price와
  같은 값). 지정가 관통(저가 < 지정가) 같은 등호 경계가 파싱 오차로 뒤집히지 않게 하려는 것이다.
- 캐시 쓰기는 임시 파일 → os.replace(원자적 교체)라서 여러 프로세스가 동시에 불러도 깨진 파일을 읽지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import config as C
from backtest import types as T
from backtest.types import MarketData

KLINE_TFS = ("1m", "5m", "15m", "1h", "4h", "1d")

SYMBOL = "BTCUSDT"
KLINE_COLUMNS = ("open_time", "open", "high", "low", "close", "volume")  # 캔들 CSV에서 읽는 열
FUNDING_FILE = f"{SYMBOL}_fundingRate.csv.gz"
CACHE_VERSION = "g1-klines-npz/1"  # 캐시 형식·파싱 규칙이 바뀌면 올린다(서명에 들어가 옛 캐시를 무효화)

_NS_PER_MS = 1_000_000
_MS_PER_HOUR = 3_600_000
# open_time·calc_time(ms)이 그럴듯한 범위인지(단위 착오 검출: 초·마이크로초로 저장된 파일 등)
_MS_MIN = 1_483_228_800_000   # 2017-01-01 00:00 UTC
_MS_MAX = 4_102_444_800_000   # 2100-01-01 00:00 UTC
_FUNDING_MAX_OFFSET_MS = 60_000  # calc_time은 정시 직후(데이터 최대 47ms). 1분 넘게 벗어나면 이상 데이터로 본다
_CACHE_ARRAYS = ("open_ns", "open", "high", "low", "close", "volume")
_TF_PATTERN = re.compile(r"(\d+)(m|h|d)")
_TF_UNIT_NS = {"m": C.NS_PER_MIN, "h": C.NS_PER_HOUR, "d": C.NS_PER_DAY}


# ---------------------------------------------------------------------------
# 작은 도우미
# ---------------------------------------------------------------------------


def tf_to_ns(tf: str) -> int:
    """봉 간격 이름 → 길이(ns). config.TF_NS의 이름('1m'…'1d') 외에 '2h', '30m', '3d' 같은 임의 간격도 받는다."""
    if tf in C.TF_NS:
        return int(C.TF_NS[tf])
    m = _TF_PATTERN.fullmatch(str(tf))
    if not m or int(m.group(1)) <= 0:
        raise ValueError(f"알 수 없는 봉 간격: {tf!r} (예: '5m', '1h', '4h', '1d', '2h')")
    return int(m.group(1)) * _TF_UNIT_NS[m.group(2)]


def kline_files(tf: str, data_dir: Path = C.DATA_DIR) -> list[Path]:
    """tf 캔들의 원본 파일 목록. '1m'은 BTCUSDT_1m_{연도}.csv.gz를 연도순으로, 나머지는 BTCUSDT_{tf}.csv.gz 하나."""
    if tf not in KLINE_TFS:
        raise ValueError(f"tf는 {KLINE_TFS} 중 하나: {tf!r}")
    data_dir = Path(data_dir)
    if tf == "1m":
        pat = re.compile(rf"{SYMBOL}_1m_(\d{{4}})\.csv\.gz")
        files = sorted((p for p in data_dir.glob(f"{SYMBOL}_1m_*.csv.gz") if pat.fullmatch(p.name)),
                       key=lambda p: p.name)
        if not files:
            raise FileNotFoundError(f"1분봉 파일 없음: {data_dir}/{SYMBOL}_1m_YYYY.csv.gz")
        return files
    path = data_dir / f"{SYMBOL}_{tf}.csv.gz"
    if not path.exists():
        raise FileNotFoundError(f"캔들 파일 없음: {path}")
    return [path]


def _iso(ns) -> str:
    return C.ns_to_iso(int(ns))


def _check_ms_range(ms: np.ndarray, label: str) -> None:
    """ms 시각이 2017~2100 범위인지(단위 착오 검출)."""
    if ms.size and (ms.min() < _MS_MIN or ms.max() >= _MS_MAX):
        raise ValueError(f"{label}: 시각이 ms 단위로 보이지 않음 (최소 {ms.min()}, 최대 {ms.max()})")


def _check_kline_times(open_ns: np.ndarray, dur_ns: int, label: str) -> None:
    """정렬된 봉 시작 시각 검사: 간격 경계 정렬, 중복 없음, 빈 구간 없음. 어기면 ValueError."""
    if open_ns.size == 0:
        raise ValueError(f"{label}: 봉이 없음")
    if open_ns[0] % dur_ns:
        raise ValueError(f"{label}: 첫 봉 {_iso(open_ns[0])}이 봉 간격 경계(UTC epoch 기준)에 맞지 않음")
    d = np.diff(open_ns)
    dup = np.flatnonzero(d == 0)
    if dup.size:
        raise ValueError(f"{label}: 중복 봉 {dup.size}개 (첫 중복 {_iso(open_ns[dup[0]])})")
    bad = np.flatnonzero(d != dur_ns)
    if bad.size:
        j = bad[0]
        raise ValueError(f"{label}: 빈 구간·어긋난 간격 {bad.size}곳 (첫 위치 {_iso(open_ns[j])} → {_iso(open_ns[j + 1])})")


def _read_kline_csv(path: Path) -> dict[str, np.ndarray]:
    """캔들 CSV 하나 → 열 배열 (open_time은 ms 그대로). 네트워크 없이 로컬 파일만 읽는다."""
    dtype = {"open_time": np.int64, **{c: np.float64 for c in KLINE_COLUMNS[1:]}}
    df = pd.read_csv(path, usecols=list(KLINE_COLUMNS), dtype=dtype, float_precision="round_trip")
    return {c: df[c].to_numpy() for c in KLINE_COLUMNS}


def _parse_klines(files: list[Path], tf: str) -> dict[str, np.ndarray]:
    """원본 파일들 → 정렬·검사된 배열 (open_ns, open, high, low, close, volume)."""
    parts = [_read_kline_csv(f) for f in files]
    cols = {c: np.concatenate([p[c] for p in parts]) for c in KLINE_COLUMNS}
    ms = cols["open_time"]
    _check_ms_range(ms, f"{tf} 캔들")
    open_ns = ms.astype(np.int64) * _NS_PER_MS                  # §1 봉 시각 = 시작 시각(open_time)
    order = np.argsort(open_ns, kind="stable")                  # 연도별 파일을 이어도 시간순이 되도록
    out = {"open_ns": open_ns[order]}
    for c in KLINE_COLUMNS[1:]:
        out[c] = np.ascontiguousarray(cols[c][order], dtype=np.float64)
    _check_kline_times(out["open_ns"], tf_to_ns(tf), f"{tf} 캔들")
    return out


def _file_signature(files: list[Path]) -> list[list]:
    sig = []
    for f in files:
        st = f.stat()
        sig.append([f.name, str(f.resolve()), int(st.st_size), int(st.st_mtime_ns)])
    return sig


def _cache_signature(kind: str, files: list[Path]) -> str:
    """캐시 서명 = 형식 버전 + 종류 + 원본 파일(이름·경로·크기·수정 시각). 하나라도 바뀌면 캐시를 다시 만든다."""
    return json.dumps({"version": CACHE_VERSION, "kind": kind, "files": _file_signature(files)},
                      sort_keys=True, ensure_ascii=False)


def _cache_load(path: Path, signature: str) -> dict[str, np.ndarray] | None:
    """캐시를 읽는다. 없거나·서명이 다르거나·깨졌으면 None."""
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as z:
            if str(z["signature"].item()) != signature:
                return None
            arrays = {k: z[k] for k in _CACHE_ARRAYS}
    except Exception:  # 깨진·옛 형식 캐시 → 다시 만든다
        return None
    n = arrays["open_ns"].shape[0]
    if arrays["open_ns"].dtype != np.int64 or any(
            a.shape != (n,) or (k != "open_ns" and a.dtype != np.float64) for k, a in arrays.items()):
        return None
    return arrays


def _cache_save(path: Path, signature: str, arrays: dict[str, np.ndarray]) -> None:
    """캐시를 원자적으로 쓴다(임시 파일 → os.replace). 쓰기 실패는 경고만 하고 계속한다."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as fh:
            np.savez(fh, signature=np.array(signature), **{k: arrays[k] for k in _CACHE_ARRAYS})
        os.replace(tmp, path)
    except OSError as exc:
        warnings.warn(f"캐시를 쓰지 못함 ({path}): {exc}", RuntimeWarning, stacklevel=3)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _bars_frame(arrays: dict[str, np.ndarray], dur_ns, label: str, *, fixed_dur: int | None) -> pd.DataFrame:
    df = T.make_bars_frame(arrays["open_ns"], arrays["open"], arrays["high"], arrays["low"],
                           arrays["close"], arrays["volume"], dur_ns)
    try:
        T.check_bars_frame(df, dur_ns=fixed_dur, contiguous=True)
    except ValueError as exc:
        raise ValueError(f"{label}: 표준 봉 프레임 검사 실패 — {exc}") from exc
    return df


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------


def load_klines(tf: str, *, data_dir: Path = C.DATA_DIR, cache_dir: Path | None = C.CACHE_DIR) -> pd.DataFrame:
    """캔들 파일 → 표준 봉 프레임 (types.check_bars_frame(dur_ns=TF_NS[tf]) 통과).

    tf: '1m'(BTCUSDT_1m_{2023..2026}.csv.gz를 이어 붙임) | '5m' | '15m' | '1h' | '4h' | '1d'.
    중복·빈 구간이 있으면 ValueError. cache_dir=None이면 캐시를 쓰지 않는다.
    """
    files = kline_files(tf, data_dir)
    dur = tf_to_ns(tf)
    arrays = None
    cache_path = signature = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"{SYMBOL}_{tf}.npz"
        signature = _cache_signature(f"klines:{tf}", files)
        arrays = _cache_load(cache_path, signature)
        if arrays is not None:
            _check_kline_times(arrays["open_ns"], dur, f"{tf} 캐시")
    if arrays is None:
        arrays = _parse_klines(files, tf)
        if cache_path is not None:
            _cache_save(cache_path, signature, arrays)
    return _bars_frame(arrays, dur, f"{tf} 캔들", fixed_dur=dur)


def load_exec_bars(*, switch_ns: int = C.EXEC_SWITCH_NS, data_dir: Path = C.DATA_DIR,
                   cache_dir: Path | None = C.CACHE_DIR) -> pd.DataFrame:
    """실행 봉 = 5분봉(open_ns < switch_ns) + 1분봉(open_ns ≥ switch_ns)을 시간순으로 이은 표준 봉 프레임 (§12.1, DESIGN §5).

    봉 길이가 섞이므로 close_ns = open_ns + 각 봉 길이. check_bars_frame(contiguous=True) 통과해야 한다
    (마지막 5분봉 2023-09-30 23:55의 close_ns == 첫 1분봉 open_ns).
    """
    before_tf, after_tf = C.EXEC_TF_BEFORE, C.EXEC_TF_AFTER
    before_dur, after_dur = tf_to_ns(before_tf), tf_to_ns(after_tf)
    switch_ns = int(switch_ns)
    if switch_ns % before_dur:
        raise ValueError(f"switch_ns {_iso(switch_ns)}가 {before_tf} 경계가 아님 (봉이 겹치게 됨)")
    before = load_klines(before_tf, data_dir=data_dir, cache_dir=cache_dir)
    after = load_klines(after_tf, data_dir=data_dir, cache_dir=cache_dir)
    mb = before["open_ns"].to_numpy() < switch_ns               # §12.1 2023-10-01 전: 5분봉
    ma = after["open_ns"].to_numpy() >= switch_ns               # §12.1 2023-10-01 이후: 1분봉
    if not ma.any():
        raise ValueError(f"{after_tf} 봉이 {_iso(switch_ns)} 이후에 없음")
    parts = [(before, mb, before_dur), (after, ma, after_dur)]
    arrays = {k: np.concatenate([f[k].to_numpy()[m] for f, m, _ in parts]) for k in _CACHE_ARRAYS}
    dur = np.concatenate([np.full(int(m.sum()), d, dtype=np.int64) for _, m, d in parts])
    # 경계 검사(마지막 5분봉 끝 = 첫 1분봉 시작)는 check_bars_frame(contiguous=True)가 한다 (DESIGN §5)
    return _bars_frame(arrays, dur, "실행 봉", fixed_dur=None)


def load_funding(*, until_ns: int | None = None, data_dir: Path = C.DATA_DIR) -> pd.DataFrame:
    """펀딩비 파일 → 표준 펀딩 프레임 (types.make_funding_frame 형식).

    - calc_time(ms)을 정시로 내린다(원본 오차 ≤ 47ms). rate = last_funding_rate.
    - until_ns를 주면: 마지막 실제 기록 이후이면서 FUNDING_FALLBACK_FROM_NS(2026-09-01 00:00) 이상,
      until_ns 이하인 8시간 격자(00·08·16 UTC)마다 FUNDING_FALLBACK_RATE를 synthetic=True로 덧붙인다 (§12.2, I-35).
    """
    path = Path(data_dir) / FUNDING_FILE
    if not path.exists():
        raise FileNotFoundError(f"펀딩 파일 없음: {path}")
    df = pd.read_csv(path, usecols=["calc_time", "last_funding_rate"],
                     dtype={"calc_time": np.int64, "last_funding_rate": np.float64},
                     float_precision="round_trip")
    ms = df["calc_time"].to_numpy()
    _check_ms_range(ms, "펀딩 calc_time")
    floored_ms = (ms // _MS_PER_HOUR) * _MS_PER_HOUR            # §12.2·I-35 펀딩 시각 = 정시로 내림
    offset = ms - floored_ms
    if offset.size and offset.max() > _FUNDING_MAX_OFFSET_MS:
        j = int(np.argmax(offset))
        raise ValueError(f"펀딩 calc_time이 정시 직후가 아님: {ms[j]} ms (정시에서 {offset[j]} ms)")
    order = np.argsort(floored_ms, kind="stable")
    time_ns = floored_ms[order].astype(np.int64) * _NS_PER_MS
    rate = df["last_funding_rate"].to_numpy()[order]
    if time_ns.size > 1 and np.any(np.diff(time_ns) == 0):
        j = int(np.flatnonzero(np.diff(time_ns) == 0)[0])
        raise ValueError(f"같은 정시로 내려지는 펀딩 기록이 둘 이상: {_iso(time_ns[j])}")
    synthetic = np.zeros(time_ns.shape[0], dtype=bool)

    if until_ns is not None:
        step = int(C.FUNDING_INTERVAL_NS)
        last_real = int(time_ns[-1]) if time_ns.size else None
        start = C.FUNDING_FALLBACK_FROM_NS if last_real is None else max(C.FUNDING_FALLBACK_FROM_NS, last_real + 1)
        first = -(-start // step) * step                          # 8시간 격자(UTC 00·08·16)로 올림
        fb = np.arange(first, int(until_ns) + 1, step, dtype=np.int64)  # §12.2 "2026-09 이후 0.01%"
        if last_real is not None and fb.size and fb[0] > last_real + step:
            warnings.warn(f"펀딩 공백: 마지막 실제 기록 {_iso(last_real)} ~ 대체값 시작 {_iso(fb[0])} 사이에 펀딩 없음",
                          RuntimeWarning, stacklevel=2)
        time_ns = np.concatenate([time_ns, fb])
        rate = np.concatenate([rate, np.full(fb.shape[0], C.FUNDING_FALLBACK_RATE)])
        synthetic = np.concatenate([synthetic, np.ones(fb.shape[0], dtype=bool)])

    frame = T.make_funding_frame(time_ns, rate, synthetic)
    T.check_funding_frame(frame)
    return frame


def load_events(path: Path = C.EVENTS_CSV) -> np.ndarray | None:
    """F3 이벤트 시각 (int64 ns, 오름차순). 파일이 없으면 None (→ F3 꺼짐, §10-2).

    파일 형식(DESIGN I-49): CSV, 열 time_utc(ISO 8601, UTC) 필수, kind(FOMC/CPI 등) 선택.
    """
    path = Path(path)
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"time_utc": str})
    if "time_utc" not in df.columns:
        raise ValueError(f"{path}: time_utc 열이 없음 (DESIGN I-49)")
    if len(df) == 0:
        return np.empty(0, dtype=np.int64)
    if df["time_utc"].isna().any():
        raise ValueError(f"{path}: 비어 있는 time_utc가 있음")
    try:
        ts = pd.to_datetime(df["time_utc"], utc=True, format="ISO8601")  # 시간대 없는 값은 UTC로 본다
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{path}: time_utc를 ISO 8601 시각으로 읽을 수 없음 — {exc}") from exc
    out = pd.DatetimeIndex(ts).as_unit("ns").asi8.astype(np.int64)
    return np.sort(out, kind="stable")


def resample_bars(bars: pd.DataFrame, tf: str) -> pd.DataFrame:
    """§1 봉 합치기: 시가=첫 시가, 고가=최댓값, 저가=최솟값, 종가=마지막 종가, 거래량=합.

    구간 경계는 UTC epoch 기준 TF_NS[tf]의 배수(4h: 00·04·…, 1d: 00:00 UTC). 원본 봉이 모자란 구간은 버린다.
    v1은 필요한 간격이 모두 파일로 있어 검증·테스트 데이터 생성용이다.
    (tf는 '2h'·'30m' 같은 임의 간격도 받는다 — tf_to_ns. 봉 길이가 섞인 실행 봉도 합칠 수 있다.)
    """
    step = tf_to_ns(tf)
    T.check_bars_frame(bars, contiguous=False)
    o_ns = bars["open_ns"].to_numpy()
    c_ns = bars["close_ns"].to_numpy()
    n = o_ns.shape[0]
    if n == 0:
        e = np.empty(0)
        return T.make_bars_frame(np.empty(0, dtype=np.int64), e, e, e, e, e, step)
    key = np.floor_divide(o_ns, step)                           # 봉이 속한 구간 번호 (시작 시각 기준)
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], n]                                 # 구간 [starts, ends)
    g_start = key[starts] * step
    # 완전한 구간만: 첫 봉이 구간 시작에서 시작, 마지막 봉이 구간 끝에서 끝나고, 안에 빈틈이 없어야 함
    brk = np.r_[c_ns[:-1] != o_ns[1:], False]                   # 봉 i와 i+1 사이 빈틈(또는 겹침)
    brk_cum = np.r_[0, np.cumsum(brk)]
    inner_breaks = brk_cum[ends - 1] - brk_cum[starts]
    complete = (o_ns[starts] == g_start) & (c_ns[ends - 1] == g_start + step) & (inner_breaks == 0)
    o = bars["open"].to_numpy()[starts]                         # §1 시가 = 첫 봉 시가
    c = bars["close"].to_numpy()[ends - 1]                      # §1 종가 = 마지막 봉 종가
    h = np.maximum.reduceat(bars["high"].to_numpy(), starts)    # §1 고가 = 최댓값
    l = np.minimum.reduceat(bars["low"].to_numpy(), starts)     # §1 저가 = 최솟값
    v = np.add.reduceat(bars["volume"].to_numpy(), starts)      # §1 거래량 = 합
    return T.make_bars_frame(g_start[complete], o[complete], h[complete], l[complete], c[complete],
                             v[complete], step)


def load_market(*, tfs: tuple[str, ...] = ("15m", "1h", "4h", "1d"), with_events: bool = True,
                data_dir: Path = C.DATA_DIR, cache_dir: Path | None = C.CACHE_DIR) -> MarketData:
    """G1에 필요한 데이터 전부를 MarketData로 돌려준다.

    - bars: tfs 각각 load_klines
    - exec_bars: load_exec_bars()
    - funding: load_funding(until_ns=실행 봉 마지막 close_ns)
    - events_ns: with_events면 load_events(), 아니면 None
    """
    bars = {tf: load_klines(tf, data_dir=data_dir, cache_dir=cache_dir) for tf in tfs}
    exec_bars = load_exec_bars(data_dir=data_dir, cache_dir=cache_dir)
    until_ns = int(exec_bars["close_ns"].iloc[-1])
    funding = load_funding(until_ns=until_ns, data_dir=data_dir)
    events_ns = load_events() if with_events else None
    return MarketData(bars=bars, exec_bars=exec_bars, funding=funding, events_ns=events_ns)


def input_files(data_dir: Path = C.DATA_DIR) -> list[Path]:
    """백테스트가 읽는 원본 파일 목록(있는 것만, 이름순): 캔들 6종(1분봉 연도별 포함) + 펀딩."""
    data_dir = Path(data_dir)
    files: list[Path] = []
    for tf in KLINE_TFS:
        try:
            files.extend(kline_files(tf, data_dir))
        except FileNotFoundError:
            continue
    if (data_dir / FUNDING_FILE).exists():
        files.append(data_dir / FUNDING_FILE)
    return sorted(files, key=lambda p: p.name)


def data_fingerprint(data_dir: Path = C.DATA_DIR) -> dict[str, str]:
    """입력 파일 이름 → sha256 16진 문자열 (결과 JSON data.sha256, DEV_GUIDE §6.15 '데이터 해시')."""
    out: dict[str, str] = {}
    for path in input_files(data_dir):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out[path.name] = h.hexdigest()
    return out
