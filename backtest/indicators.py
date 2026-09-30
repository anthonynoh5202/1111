"""기본 수치(지표) — RULES_SPEC §3을 봉 배열에 계산한다.

담당: 데이터·지표. 설계: backtest/DESIGN.md §6.4.

핵심 규약 (DESIGN §4 미래 참조 금지 계약)
- 모든 "최근 n개 평균"은 **현재 봉을 뺀 직전 n개** (MA20·60·120 포함, I-2).
- 현재 봉의 값(종가·거래량·몸통 등)은 쓴다: 판단은 그 봉 마감 + 60초에 하기 때문.
- 계산할 수 없는 값은 NaN. 조건(bool) 열은 NaN이면 False. `valid`가 False인 봉에서는 신호를 내지 않는다(§12.3).
- 입력은 표준 봉 프레임(types.make_bars_frame 형식). 출력 인덱스 = 입력 인덱스, 위치 번호 t가 봉 번호.

구현 메모
- 이동 평균·분위는 창(sliding window)마다 따로 계산한다(누적합을 쓰지 않음). 그래서 값 t는 창 [t−n, t−1]의
  값만으로 정해지고, 앞부분만 넣어 계산해도 전체로 계산한 값과 비트 단위로 같다(T-IND-9, DESIGN C-12).
- 분위는 numpy 'linear' 방식을 창마다 그대로 쓴다(naive `np.quantile(x[t−n:t], q)`와 비트 단위로 같음, I-3).
- 스윙 고저(§3)는 structure.find_swings·last_confirmed와 같은 규칙(I-6, C-4)을 여기에도 둔다(swing_points 등).
  compute_indicators의 열에는 넣지 않는다(열 계약 INDICATOR_COLUMNS 고정).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from backtest import config as C

# compute_indicators가 돌려주는 열 (이름·순서 고정, dtype: bool 표시 외에는 float64)
INDICATOR_COLUMNS = (
    "body",         # |close − open|                                    §3
    "range",        # high − low                                        §3
    "tr",           # True Range, tr[0] = NaN                            §3, I-4
    "atr",          # trailing_mean(tr, 14)  (t ≥ 15부터 값)              §3, I-4
    "vol_avg",      # trailing_mean(volume, 20)
    "vr",           # volume ÷ vol_avg (vol_avg == 0이면 NaN)             §3
    "body_avg",     # trailing_mean(body, 20)
    "long_bar",     # bool: body ≥ 2 × body_avg                          §3 장대봉
    "upper_wick",   # (high − max(open, close)) ÷ range, range == 0이면 0 §3
    "lower_wick",   # (min(open, close) − low) ÷ range, range == 0이면 0  §3 (하락 기준봉용)
    "ma20",         # trailing_mean(close, 20)                           §3, I-2
    "ma60",         # trailing_mean(close, 60)
    "ma120",        # trailing_mean(close, 120)
    "spread",       # (max(ma20, ma60, ma120) − min(…)) ÷ close[t]        §3 이평 확산
    "spread_q80",   # trailing_quantile(spread, 500, 0.80)               §3, I-3
    "spread_on",    # bool: spread ≥ spread_q80 ("확산", §4.1-5, §6 F4)
    "slope20",      # sign(close[t] − close[t−20]) ∈ {−1, 0, +1}, t < 20이면 NaN  §3, I-5
    "slope60",
    "slope120",
    "atr_q20",      # trailing_quantile(atr, 100, 0.20)                  §6 F2, I-3
    "surge",        # bool: range ≥ 3 × atr (그 봉 자신의 atr)             §6 F5, I-16
    "buffer",       # b = 0.1 × atr                                     §3
    "valid",        # bool: atr·vr·body_avg·ma120·spread_q80·slope120·atr_q20 모두 NaN 아님 (§12.3)
)
BOOL_INDICATOR_COLUMNS = ("long_bar", "spread_on", "surge", "valid")

# valid 판정에 쓰는 열 (DESIGN §6.4). 실데이터·합성 데이터 모두 첫 유효 봉 번호 = 120 + 500 = 620.
VALID_REQUIRED_COLUMNS = ("atr", "vr", "body_avg", "ma120", "spread_q80", "slope120", "atr_q20")
FIRST_VALID_INDEX = max(C.MA_PERIODS) + C.SPREAD_LOOKBACK  # 620 (§12.3 "지표가 유효해지는 시점")

_QUANTILE_CHUNK_ELEMS = 4_000_000  # 분위 계산 때 한 번에 복사하는 원소 수 상한(메모리 약 32MB)


def _as_float_array(x) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"1차원 배열이어야 함: shape={arr.shape}")
    return arr


def _check_window(n: int) -> int:
    if int(n) != n or n < 1:
        raise ValueError(f"창 길이 n은 1 이상 정수: {n!r}")
    return int(n)


def _trailing_windows(x: np.ndarray, n: int) -> np.ndarray:
    """행 r = x[r : r+n] (= 봉 t = r + n의 직전 n개 창, 현재 봉 제외). 복사하지 않는 보기(view)."""
    return sliding_window_view(x, n)[:-1]


def trailing_mean(x: np.ndarray, n: int) -> np.ndarray:
    """직전 n개 평균(현재 제외): out[t] = mean(x[t−n .. t−1]). t < n이거나 창 안에 NaN이 있으면 NaN (§3, I-2).

    예: x=[1,2,3,4,5], n=2 → [nan, nan, 1.5, 2.5, 3.5]
    """
    x = _as_float_array(x)
    n = _check_window(n)
    out = np.full(x.shape[0], np.nan)
    if x.shape[0] > n:
        out[n:] = _trailing_windows(x, n).mean(axis=1)  # RULES_SPEC §3 "현재 봉을 뺀 직전 n개"
    return out


def trailing_quantile(x: np.ndarray, n: int, q: float) -> np.ndarray:
    """직전 n개 값(현재 제외)의 q 분위 (numpy 'linear' 방식, I-3). t < n이거나 창 안에 NaN이 있으면 NaN.

    naive 기준: out[t] = np.quantile(x[t−n:t], q). 성능을 위해 pandas rolling().quantile(interpolation='linear')를
    shift(1)과 함께 써도 되지만, 결과가 naive와 1e-9 이내로 같아야 한다(테스트 T-IND-6).
    (구현: 창마다 np.quantile을 그대로 부른다 → naive와 비트 단위로 같다. 메모리 때문에 행을 나눠 계산.)
    """
    x = _as_float_array(x)
    n = _check_window(n)
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"분위 q는 0~1: {q!r}")
    out = np.full(x.shape[0], np.nan)
    if x.shape[0] <= n:
        return out
    win = _trailing_windows(x, n)
    step = max(1, _QUANTILE_CHUNK_ELEMS // n)
    for s in range(0, win.shape[0], step):
        # np.quantile은 창에 NaN이 있으면 NaN을 돌려준다 (창 안 NaN → NaN 규약)
        out[n + s: n + s + step] = np.quantile(win[s: s + step], q, axis=1, method="linear")
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """TR[t] = max(high−low, |high−close[t−1]|, |low−close[t−1]|). TR[0] = NaN (직전 종가 없음, I-4)."""
    h, l, c = _as_float_array(high), _as_float_array(low), _as_float_array(close)
    if not h.shape == l.shape == c.shape:
        raise ValueError("high·low·close 길이가 다름")
    prev_close = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_close), np.abs(l - prev_close)))  # §3 TR
    if tr.shape[0]:
        tr[0] = np.nan
    return tr


def slope_sign(close: np.ndarray, n: int) -> np.ndarray:
    """기울기 N (캔들 카운팅, §3, I-5): sign(close[t] − close[t−n]) → +1 상승, −1 하락, 0 같음. t < n이면 NaN."""
    c = _as_float_array(close)
    n = _check_window(n)
    out = np.full(c.shape[0], np.nan)
    if c.shape[0] > n:
        out[n:] = np.sign(c[n:] - c[:-n])  # §3 close[t] vs close[t−N]
    return out


def compute_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    """표준 봉 프레임 → 지표 프레임 (열 = INDICATOR_COLUMNS, 인덱스 = bars.index).

    bool 열(BOOL_INDICATOR_COLUMNS)은 dtype bool, 나머지는 float64.
    실데이터 기준 valid는 봉 번호 620부터 True(이평 확산 120 + 500, §12.3).
    """
    missing = [c for c in ("open", "high", "low", "close", "volume") if c not in bars.columns]
    if missing:
        raise ValueError(f"봉 프레임에 열 없음: {missing}")
    o = bars["open"].to_numpy(dtype=np.float64)
    h = bars["high"].to_numpy(dtype=np.float64)
    l = bars["low"].to_numpy(dtype=np.float64)
    c = bars["close"].to_numpy(dtype=np.float64)
    v = bars["volume"].to_numpy(dtype=np.float64)

    out: dict[str, np.ndarray] = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        body = np.abs(c - o)                                    # §3 몸통
        rng = h - l                                             # §3 범위
        out["body"] = body
        out["range"] = rng

        tr = true_range(h, l, c)                                # §3 TR, I-4
        atr = trailing_mean(tr, C.ATR_N)                        # §3 ATR = 직전 14개 TR 평균 (현재 봉 제외)
        out["tr"] = tr
        out["atr"] = atr

        vol_avg = trailing_mean(v, C.VR_N)                      # §3 VR 분모: 직전 20개 평균 거래량
        out["vol_avg"] = vol_avg
        out["vr"] = np.where(vol_avg > 0, v / vol_avg, np.nan)  # §3 VR (평균 0이면 계산 불가 → NaN)

        body_avg = trailing_mean(body, C.BODY_AVG_N)            # §3 장대봉: 직전 20개 평균 몸통
        out["body_avg"] = body_avg
        out["long_bar"] = body >= C.LONG_BAR_MULT * body_avg    # §3 몸통 ≥ 2 × 평균 (NaN → False)

        top = np.maximum(o, c)
        bottom = np.minimum(o, c)
        zero_or_nan = np.where(rng == 0, 0.0, np.nan)            # 범위 0이면 0, 범위를 알 수 없으면 NaN
        out["upper_wick"] = np.where(rng > 0, (h - top) / rng, zero_or_nan)     # §3 윗꼬리 비율
        out["lower_wick"] = np.where(rng > 0, (bottom - l) / rng, zero_or_nan)  # §3 아랫꼬리 비율

        mas = [trailing_mean(c, p) for p in C.MA_PERIODS]       # §3·I-2 이평도 현재 봉 제외
        for p, ma in zip(C.MA_PERIODS, mas):
            out[f"ma{p}"] = ma
        ma_stack = np.vstack(mas)
        spread = (ma_stack.max(axis=0) - ma_stack.min(axis=0)) / c  # §3 이평 확산 (분모 = 현재 종가)
        out["spread"] = spread
        spread_q80 = trailing_quantile(spread, C.SPREAD_LOOKBACK, C.SPREAD_QUANTILE)  # §3·I-3 직전 500봉 80% 분위
        out["spread_q80"] = spread_q80
        out["spread_on"] = spread >= spread_q80                 # §3 "상위 20% 이상" (NaN → False)

        for p in C.SLOPE_NS:
            out[f"slope{p}"] = slope_sign(c, p)                 # §3 기울기 N, I-5

        out["atr_q20"] = trailing_quantile(atr, C.F2_ATR_LOOKBACK, C.F2_ATR_QUANTILE)  # §6 F2·I-3 직전 100봉 20% 분위
        out["surge"] = rng >= C.F5_RANGE_ATR_MULT * atr         # §6 F5 범위 ≥ 3 × ATR (자기 봉 ATR, I-16)
        out["buffer"] = C.BUFFER_ATR_MULT * atr                 # §3 가격 버퍼 b = 0.1 × ATR

    valid = np.ones(c.shape[0], dtype=bool)
    for name in VALID_REQUIRED_COLUMNS:                         # §12.3 지표 유효 전에는 신호 없음
        valid &= ~np.isnan(out[name])
    out["valid"] = valid

    data = {}
    for name in INDICATOR_COLUMNS:
        dtype = bool if name in BOOL_INDICATOR_COLUMNS else np.float64
        data[name] = np.asarray(out[name], dtype=dtype)
    return pd.DataFrame(data, index=bars.index)


# ---------------------------------------------------------------------------
# 스윙 고저 (§3) — structure.find_swings·last_confirmed와 같은 규칙 (I-6, DESIGN C-4)
# ---------------------------------------------------------------------------


def swing_points(high: np.ndarray, low: np.ndarray, k: int = C.SWING_K) -> tuple[np.ndarray, np.ndarray]:
    """스윙 고점·저점 표시 (§3, I-6). 반환 (is_sh, is_sl) bool 배열.

    is_sh[i] = high[i]가 앞 k개·뒤 k개 봉의 high보다 모두 **엄격히** 큼(동률이면 아님). is_sl은 low 기준 대칭.
    i < k 또는 i + k > n − 1(뒤 봉이 모자람)이면 False.
    ※ 봉 i+k의 값을 보고 정하므로 봉 i+k 마감 전에는 쓰면 안 된다 → 시점 t에서는 last_confirmed_swing을 쓴다.
    """
    h, l = _as_float_array(high), _as_float_array(low)
    if h.shape != l.shape:
        raise ValueError("high·low 길이가 다름")
    k = _check_window(k)
    n = h.shape[0]
    is_sh = np.zeros(n, dtype=bool)
    is_sl = np.zeros(n, dtype=bool)
    if n < 2 * k + 1:
        return is_sh, is_sl
    hc, lc = h[k:n - k], l[k:n - k]
    sh = np.ones(n - 2 * k, dtype=bool)
    sl = np.ones(n - 2 * k, dtype=bool)
    for d in range(1, k + 1):  # 앞뒤 d번째 이웃과 엄격 비교 (§3 "모두 큼")
        sh &= (hc > h[k - d:n - k - d]) & (hc > h[k + d:n - k + d])
        sl &= (lc < l[k - d:n - k - d]) & (lc < l[k + d:n - k + d])
    is_sh[k:n - k] = sh
    is_sl[k:n - k] = sl
    return is_sh, is_sl


def last_confirmed_swing(is_swing: np.ndarray, k: int = C.SWING_K) -> np.ndarray:
    """봉 t 마감 시점에 확정된 가장 최근 스윙 번호: max{i : is_swing[i] and i + k ≤ t}, 없으면 −1 (int64, C-4).

    스윙 i는 봉 i+k 마감에 확정된다(§3). 그래서 t = i+k−1(예: k=3이면 i+2)에서는 아직 보이지 않는다.
    """
    s = np.asarray(is_swing, dtype=bool)
    k = _check_window(k)
    n = s.shape[0]
    idx = np.where(s, np.arange(n, dtype=np.int64), np.int64(-1))
    known = np.full(n, -1, dtype=np.int64)
    if n > k:
        known[k:] = idx[:n - k]  # 봉 t에서 알 수 있는 것은 i ≤ t − k 뿐
    return np.maximum.accumulate(known) if n else known


def swing_confirm_ns(close_ns: np.ndarray, is_swing: np.ndarray, k: int = C.SWING_K) -> np.ndarray:
    """스윙 i의 확정 시각 = 봉 i+k의 마감 시각 close_ns[i+k] (§3). 스윙이 아닌 봉은 −1 (int64).

    (판단은 그 시각 + 60초에 한다: config.AVAIL_DELAY_NS)
    """
    cns = np.asarray(close_ns, dtype=np.int64)
    s = np.asarray(is_swing, dtype=bool)
    if cns.shape != s.shape:
        raise ValueError("close_ns·is_swing 길이가 다름")
    k = _check_window(k)
    out = np.full(s.shape[0], -1, dtype=np.int64)
    i = np.flatnonzero(s)
    i = i[i + k < s.shape[0]]  # swing_points 결과라면 모두 해당(끝 k봉은 스윙이 아님)
    out[i] = cns[i + k]
    return out
