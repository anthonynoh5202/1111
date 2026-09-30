"""구조 정의(차트프로) — 스윙, 기준봉, 기준마디, 허리, 살아 있는 마디 (RULES_SPEC §3 스윙, §4).

담당: 구조·시나리오. 설계: backtest/DESIGN.md §6.5, 해석 확정 I-6~I-13.

미래 참조 주의
- is_sh / is_sl[i]는 봉 i+3의 값까지 보고 정한다 → 봉 i+3 마감 전에는 절대 쓰지 않는다. 시점 t의 판단에는
  last_sh / last_sl(확정된 것만)을 쓴다.
- 마디는 tb_idx(= b_idx + 3) 봉 마감에야 존재가 알려진다. 허리 계산은 a_idx..b_idx 봉만 쓴다.
- "살아 있음"은 t까지의 종가만으로 정한다(death_idx는 t 이후 정보가 아니라 '처음 죽은 봉' 기록일 뿐).

알게 된 시각(known time) — 모든 구조가 언제 알려지는지 (판단은 그 시각 + 60초)
- 스윙 i: close_ns[i + 3] (swing_known_ns)            - 기준봉 t: close_ns[t]
- 마디: tb_close_ns 열 = close_ns[tb_idx]              - 살아 있음·죽음: 그 봉의 close_ns
- 트랩(filters.trap_counts): 완성 봉 close_ns          - S3 지지선·목표 스윙: 스윙 확정 시각 (scenarios가 meta에 기록)

ind(지표 프레임)에서 쓰는 열: open/high/low/close/volume(bars), long_bar, vr, slope20, slope60,
upper_wick, lower_wick, spread_on, valid. 단위 테스트에서는 이 열만 가진 작은 프레임을 직접 만들어도 된다.

구현 메모
- 스윙 규칙은 indicators.swing_points·last_confirmed_swing이 단일 출처다(같은 규칙 I-6을 두 번 쓰지 않는다).
- 마디·허리는 마디(기준봉) 단위 파이썬 반복 + 그 안은 numpy (봉 단위 반복 없음, DESIGN §10).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from backtest import config as C
from backtest import indicators as IND
from backtest.types import MADI_COLUMNS, Structure

_BIN_EPS = 1e-9          # 허리 칸 번호 계산(칸 단위)의 부동소수 허용 오차 (I-13 "부동소수 오차 1e-9 허용")
_SCAN_FIRST = 512        # 마디 죽음 탐색 첫 창(봉 수)
_SCAN_GROWTH = 8         # 창을 넓히는 배수

_MADI_DTYPES = {
    "madi_id": object, "direction": np.int8,
    "kijun_idx": np.int64, "a_idx": np.int64, "b_idx": np.int64, "tb_idx": np.int64,
    "a_price": np.float64, "b_price": np.float64, "w": np.float64,
    "h_cluster": np.float64, "h_mid": np.float64, "waist_fallback": bool,
    "vol_ab_mean": np.float64, "vol_pre_mean": np.float64,
    "death_idx": np.int64, "end_idx": np.int64, "tb_close_ns": np.int64,
}


# ---------------------------------------------------------------------------
# 스윙 (§3, I-6, C-4)
# ---------------------------------------------------------------------------


def find_swings(high: np.ndarray, low: np.ndarray, k: int = C.SWING_K) -> tuple[np.ndarray, np.ndarray]:
    """스윙 고점·저점 표시 (§3, I-6).

    is_sh[i] = high[i] > high[j] (j ∈ [i−k, i+k], j ≠ i, 모두 엄격한 부등호). i < k 또는 i + k > n − 1이면 False.
    is_sl[i]는 low 기준 대칭(low[i] < 이웃 모두). 같은 값(동률)이 있으면 스윙이 아니다.
    반환: (is_sh, is_sl) bool 배열. ※ 봉 i+k 마감 전에는 쓰면 안 된다.
    """
    return IND.swing_points(high, low, k)  # 단일 출처 (indicators, I-6)


def last_confirmed(is_swing: np.ndarray, k: int = C.SWING_K) -> np.ndarray:
    """봉 t 마감 시점에 확정된 가장 최근 스윙 번호: max{i : is_swing[i] and i + k ≤ t}, 없으면 −1 (int64)."""
    return IND.last_confirmed_swing(is_swing, k)  # §3 "i+3 봉 마감 시점에 확정", C-4


def swing_known_ns(close_ns: np.ndarray, is_swing: np.ndarray, k: int = C.SWING_K) -> np.ndarray:
    """스윙 i를 알게 된 시각 = close_ns[i + k] (스윙이 아닌 봉은 −1). 감사·테스트용 (C-4)."""
    return IND.swing_confirm_ns(close_ns, is_swing, k)


# ---------------------------------------------------------------------------
# 기준봉 (§4.1, I-7)
# ---------------------------------------------------------------------------


def _col(frame: pd.DataFrame, name: str, dtype=np.float64) -> np.ndarray:
    return frame[name].to_numpy(dtype=dtype)


def detect_kijun(bars: pd.DataFrame, ind: pd.DataFrame, last_sh: np.ndarray, last_sl: np.ndarray,
                 vr_threshold: float = C.KIJUN_VR_MIN) -> tuple[np.ndarray, np.ndarray]:
    """상승·하락 기준봉 (§4.1, I-7). 반환 (kijun_up, kijun_dn) bool 배열.

    상승: valid[t] and close > open and long_bar and vr ≥ vr_threshold and slope20 > 0 and slope60 > 0
          and last_sh[t] ≥ 0 and close > high[last_sh[t]] and upper_wick < 0.5 and not spread_on.
    하락: 대칭 (close < open, slope < 0, last_sl, close < low[last_sl[t]], lower_wick < 0.5).
    """
    o, h, l, c = (_col(bars, k) for k in ("open", "high", "low", "close"))
    last_sh = np.asarray(last_sh, dtype=np.int64)
    last_sl = np.asarray(last_sl, dtype=np.int64)
    valid = _col(ind, "valid", bool)
    long_bar = _col(ind, "long_bar", bool)
    spread_on = _col(ind, "spread_on", bool)
    vr = _col(ind, "vr")
    s_fast, s_slow = (_col(ind, f"slope{n}") for n in C.KIJUN_SLOPE_NS)
    upper_wick, lower_wick = _col(ind, "upper_wick"), _col(ind, "lower_wick")
    sh_high = np.where(last_sh >= 0, h[np.clip(last_sh, 0, None)], np.nan)  # t 시점 확정 최근 스윙 고점의 high
    sl_low = np.where(last_sl >= 0, l[np.clip(last_sl, 0, None)], np.nan)
    with np.errstate(invalid="ignore"):
        # §4.1-1 장대봉, -2 VR ≥ 기준(민감도 3, I-26), -5 확산 제외, §12.3 지표 유효 전 아님 (NaN 비교 = False)
        common = valid & long_bar & (vr >= vr_threshold) & ~spread_on
        up = (common & (c > o)                                  # §4.1-1 양봉
              & (s_fast > 0) & (s_slow > 0)                     # §4.1-3 기울기 20·60 상승
              & (last_sh >= 0) & (c > sh_high)                  # §4.1-4 close > 최근 확정 스윙 고점 (없으면 아님, I-7)
              & (upper_wick < C.KIJUN_MAX_WICK))                # §4.1-5 윗꼬리 비율 ≥ 0.5 제외
        dn = (common & (c < o)                                  # §4.1 하락 대칭: 음봉
              & (s_fast < 0) & (s_slow < 0)
              & (last_sl >= 0) & (c < sl_low)
              & (lower_wick < C.KIJUN_MAX_WICK))                # 아랫꼬리 비율 ≥ 0.5 제외
    return up, dn


# ---------------------------------------------------------------------------
# 허리 (§4.3, I-13)
# ---------------------------------------------------------------------------


def _waist_cluster_core(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray,
                        a_idx: int, b_idx: int, a_price: float, b_price: float) -> tuple[float, bool]:
    """waist_cluster의 배열판 (마디마다 DataFrame 열을 다시 꺼내지 않으려고)."""
    A, B = float(a_price), float(b_price)
    W = abs(B - A)
    if not W > 0 or a_idx > b_idx:
        raise ValueError(f"허리: W > 0, a_idx ≤ b_idx 여야 함 (A={A}, B={B}, a={a_idx}, b={b_idx})")
    d = 1.0 if B > A else -1.0                                  # 상승 +1, 하락 −1 (§4.4 대칭)
    lo_frac, hi_frac = C.WAIST_BAND
    start = A + d * lo_frac * W                                 # I-13 칸 시작 = A 쪽 구간 끝 (상승 A+0.35W, 하락 A−0.35W)
    bw = start * C.WAIST_BIN_FRAC                               # §4.3 칸 폭 = 그 끝 가격 × 0.001
    u_max = (hi_frac - lo_frac) * W / bw                        # 구간 길이(0.30W)를 칸 단위로
    n_bins = max(1, math.ceil(u_max - _BIN_EPS))                # K = ceil(0.30W / w), 마지막 칸은 구간 끝에서 자름

    seg = slice(int(a_idx), int(b_idx) + 1)                     # §4.3 A~B 구간 봉 (a_idx..b_idx)
    vals = np.concatenate([o[seg], h[seg], l[seg], c[seg]])     # 봉마다 open·high·low·close 네 값
    u = d * (vals - start) / bw                                 # A 쪽 끝에서 B 쪽으로 잰 칸 단위 위치
    inside = (u >= -_BIN_EPS) & (u <= u_max + _BIN_EPS)         # 구간 [A+0.35W, A+0.65W] 양 끝 포함
    if not inside.any():
        # §4.3 구간 안에 닿은 값이 없으면 H = A + 0.5W, waist_fallback = true
        return C.round_price(A + d * C.WAIST_FALLBACK_FRAC * W), True
    idx = np.clip(np.floor(u[inside] + _BIN_EPS).astype(np.int64), 0, n_bins - 1)
    counts = np.bincount(idx, minlength=n_bins)                 # §4.3 칸마다 닿은 값의 수
    tied = np.flatnonzero(counts == counts.max())
    if tied.size > 1:
        # §4.3 동점 → 그 칸과 [low, high]가 겹치는(닫힌 구간) 봉들의 거래량 합이 큰 칸 (I-13)
        ul = d * (l[seg] - start) / bw
        uh = d * (h[seg] - start) / bw
        bar_lo, bar_hi = np.minimum(ul, uh), np.maximum(ul, uh)
        bin_lo = tied.astype(np.float64)
        bin_hi = np.minimum(bin_lo + 1.0, u_max)
        overlap = ((bar_lo[None, :] <= bin_hi[:, None] + _BIN_EPS)
                   & (bar_hi[None, :] >= bin_lo[:, None] - _BIN_EPS))
        vol = (overlap * v[seg][None, :]).sum(axis=1)
        tied = tied[vol == vol.max()]
    best = int(tied.min())                                      # 그래도 같으면 A에 가까운 칸 (상승: 낮은 칸, 하락: §4.4 대칭으로 높은 칸, I-13)
    center_u = (best + min(best + 1.0, u_max)) / 2.0            # 칸(잘린 칸이면 잘린 칸)의 가운데
    return C.round_price(start + d * center_u * bw), False      # I-14 H는 0.1 반올림


def waist_cluster(bars: pd.DataFrame, a_idx: int, b_idx: int, a_price: float, b_price: float) -> tuple[float, bool]:
    """§4.3 허리 H (칸 방식, I-13). 반환 (H, waist_fallback).

    - W = |B − A|, 구간 = [min(A,B) + 0.35W, min(A,B) + 0.65W] (양 끝 포함).
    - 칸: A에 가까운 구간 끝(상승: A+0.35W, 하락: A−0.35W)에서 B 쪽으로 폭 w = 그 끝 가격 × 0.001.
      칸 수 K = ceil(0.30W / w) (부동소수 오차 1e-9 허용), 마지막 칸은 구간 끝에서 자른다.
    - a_idx..b_idx 각 봉의 open·high·low·close 중 구간 안의 값마다 해당 칸에 +1.
    - 최다 칸. 동점 → 그 칸과 [low, high]가 겹치는(닫힌 구간) a_idx..b_idx 봉들의 거래량 합이 큰 칸
      → 그래도 같으면 A에 가까운 칸(상승: 낮은 가격 칸, 하락: §4.4 '상승의 대칭'으로 높은 가격 칸 — 검토 SPEC-WAIST-TIE-DOWN,
      문자 그대로 '낮은 칸'과 다른 점은 DESIGN I-13·보고서에 명시).
    - H = 그 칸(잘린 경우 잘린 칸)의 가운데 가격, round_price. 구간 안 값이 하나도 없으면
      H = round_price(A ± 0.5W)(= (A+B)/2), waist_fallback = True.
    """
    o, h, l, c, v = (_col(bars, k) for k in ("open", "high", "low", "close", "volume"))
    return _waist_cluster_core(o, h, l, c, v, int(a_idx), int(b_idx), a_price, b_price)


def waist_midpoint(a_price: float, b_price: float) -> float:
    """민감도용 허리 (§9 "(고+저)÷2"): round_price((A + B) / 2)."""
    return C.round_price((float(a_price) + float(b_price)) / 2.0)


# ---------------------------------------------------------------------------
# 기준마디 (§4.2·§4.4, I-8~I-12)
# ---------------------------------------------------------------------------


def _next_true(mask: np.ndarray) -> np.ndarray:
    """nxt[t] = min{i ≥ t : mask[i]}, 없으면 n."""
    n = mask.shape[0]
    idx = np.where(mask, np.arange(n, dtype=np.int64), np.int64(n))
    return np.minimum.accumulate(idx[::-1])[::-1] if n else idx


def _first_cross(c: np.ndarray, start: int, level: float, below: bool) -> int:
    """start 이상에서 처음 close < level(below) 또는 close > level 인 봉 번호, 없으면 n. 창을 넓혀 가며 찾는다."""
    n = c.shape[0]
    pos, width = int(start), _SCAN_FIRST
    while pos < n:
        seg = c[pos:pos + width]
        hit = seg < level if below else seg > level
        if hit.any():
            return pos + int(np.argmax(hit))
        pos += width
        width *= _SCAN_GROWTH
    return n


def fmt_minute(ts_ns: int) -> str:
    """int ns → 'YYYYmmddHHMM' (UTC). 마디 ID·계획 ID용."""
    return datetime.fromtimestamp(int(ts_ns) // C.NS_PER_SEC, tz=timezone.utc).strftime("%Y%m%d%H%M")


def empty_madis() -> pd.DataFrame:
    """열만 있는 빈 마디 표."""
    return pd.DataFrame({k: pd.Series([], dtype=_MADI_DTYPES[k]) for k in MADI_COLUMNS})


def detect_madis(bars: pd.DataFrame, ind: pd.DataFrame, is_sh: np.ndarray, is_sl: np.ndarray,
                 last_sh: np.ndarray, last_sl: np.ndarray, kijun_up: np.ndarray, kijun_dn: np.ndarray,
                 tf: str) -> pd.DataFrame:
    """기준마디 표 (§4.2·§4.4, I-8~I-12). 열 = types.MADI_COLUMNS, 행 순서 (tb_idx, kijun_idx) 오름차순.

    상승 기준봉 t마다:
    - a_idx = last_sl[t] (없으면 후보 없음), A = low[a_idx]
    - b_idx = t 이상에서 처음 is_sh인 번호, B = high[b_idx], tb_idx = b_idx + 3.
      tb_idx > t + 60 이거나 tb_idx > n − 1이면 무효.
    - 무효: close[a_idx..tb_idx] 중 하나라도 < A / W = B − A ≤ 0 / a_idx < 20 /
            mean(volume[a_idx..b_idx]) < mean(volume[a_idx−20..a_idx−1])
    - death_idx = tb_idx 뒤 처음 close < A인 봉(없으면 n), end_idx = min(death_idx − 1, tb_idx + 300)
    - 같은 (direction, b_idx)가 여럿이면 가장 이른 기준봉의 것 하나만 남긴다 (I-11)
    하락은 대칭(a_idx = last_sh[t], A = high, b_idx = t 이상 첫 is_sl, 무효·죽음은 close > A).
    madi_id = f"{tf}{'U'|'D'}-{B 봉 시작 시각 %Y%m%d%H%M}".
    """
    o, h, l, c, v = (_col(bars, k) for k in ("open", "high", "low", "close", "volume"))
    open_ns = _col(bars, "open_ns", np.int64)
    close_ns = _col(bars, "close_ns", np.int64)
    n = c.shape[0]
    k = C.SWING_K
    rows: list[dict] = []
    for direction, kijun, last_a, is_b in ((1, kijun_up, last_sl, is_sh), (-1, kijun_dn, last_sh, is_sl)):
        up = direction > 0
        last_a = np.asarray(last_a, dtype=np.int64)
        nxt_b = _next_true(np.asarray(is_b, dtype=bool))       # I-8 B = t 이상에서 처음 확정되는 스윙
        seen_b: set[int] = set()
        for t in np.flatnonzero(np.asarray(kijun, dtype=bool)):  # 기준봉 번호 오름차순 → 같은 B는 가장 이른 것 (I-11)
            a_idx = int(last_a[t])                             # §4.2 A = 기준봉 t 시점 확정 최근 스윙 저점(하락: 고점)
            if a_idx < 0:
                continue
            b_idx = int(nxt_b[t])
            if b_idx >= n:
                continue
            tb = b_idx + k                                     # §4.2 T_B = B 봉 + 3봉 마감
            if tb > t + C.MADI_B_MAX_BARS or tb > n - 1:       # §4.2 60봉 안에 확정 안 됨 / 데이터 안에서 미확정
                continue
            a_price = float(l[a_idx] if up else h[a_idx])
            b_price = float(h[b_idx] if up else l[b_idx])
            w = direction * (b_price - a_price)                # §4.2 W = B − A
            if not w > 0:
                continue
            if a_idx < C.MADI_PRE_VOL_N:                       # I-10 A 직전 20봉이 없으면 무효
                continue
            seg_close = c[a_idx:tb + 1]                        # I-9 T_B 봉 포함, 종가가 A를 넘어서면 무효
            if (seg_close < a_price).any() if up else (seg_close > a_price).any():
                continue
            vol_ab = float(v[a_idx:b_idx + 1].mean())          # §4.2 A~B 구간 평균 거래량
            vol_pre = float(v[a_idx - C.MADI_PRE_VOL_N:a_idx].mean())  # A 직전 20봉 평균
            if vol_ab < vol_pre:                               # §4.2 거래량 조건
                continue
            if b_idx in seen_b:                                # I-11 (방향, b_idx)당 하나
                continue
            seen_b.add(b_idx)
            death = _first_cross(c, tb + 1, a_price, below=up)  # I-12 확정 뒤 처음 종가가 A를 넘어선 봉
            end = min(death - 1, tb + C.MADI_ALIVE_BARS)       # §4.2 살아 있는 마디: 300봉 이내
            h_cl, fallback = _waist_cluster_core(o, h, l, c, v, a_idx, b_idx, a_price, b_price)
            rows.append({
                "madi_id": f"{tf}{'U' if up else 'D'}-{fmt_minute(open_ns[b_idx])}",
                "direction": direction, "kijun_idx": int(t), "a_idx": a_idx, "b_idx": b_idx, "tb_idx": tb,
                "a_price": a_price, "b_price": b_price, "w": w,
                "h_cluster": h_cl, "h_mid": waist_midpoint(a_price, b_price), "waist_fallback": fallback,
                "vol_ab_mean": vol_ab, "vol_pre_mean": vol_pre,
                "death_idx": int(death), "end_idx": int(end), "tb_close_ns": int(close_ns[tb]),
            })
    if not rows:
        return empty_madis()
    df = pd.DataFrame(rows, columns=list(MADI_COLUMNS))
    df = df.sort_values(["tb_idx", "kijun_idx", "direction"], kind="stable").reset_index(drop=True)
    return df.astype(_MADI_DTYPES)


# ---------------------------------------------------------------------------
# 살아 있는 마디·최근 마디·허리 선택 (I-12, I-24, I-25)
# ---------------------------------------------------------------------------


def paint_alive(madis: pd.DataFrame, n: int, direction: int, start_offset: int = 0) -> np.ndarray:
    """봉마다 살아 있는 마디 중 가장 최근 것(최대 tb_idx, 동률이면 뒤 행)의 행 번호, 없으면 −1 (I-12).

    마디 행을 순서대로 [tb_idx + start_offset, end_idx] 구간에 칠하면 된다(뒤 행이 덮어씀).
    start_offset=0: 확정 봉부터 살아 있음(DA·F7). start_offset=1: 확정 "후"만(S2, I-24).
    """
    out = np.full(int(n), -1, dtype=np.int64)
    if len(madis) == 0:
        return out
    d = madis["direction"].to_numpy()
    tb = madis["tb_idx"].to_numpy(dtype=np.int64)
    end = madis["end_idx"].to_numpy(dtype=np.int64)
    for r in np.flatnonzero(d == direction):                   # 행 순서 = (tb_idx, kijun_idx) → 뒤 행이 더 최근
        s = int(tb[r]) + int(start_offset)
        e = min(int(end[r]), int(n) - 1)                        # I-12 tb ≤ t ≤ min(death − 1, tb + 300)
        if s <= e:
            out[s:e + 1] = r
    return out


def most_recent_confirmed(madis: pd.DataFrame, n: int, direction: int) -> np.ndarray:
    """봉 t까지 확정된(tb_idx ≤ t) 마디 중 가장 최근 것의 행 번호(생존 여부 무관), 없으면 −1. S3 추가 조건용 (I-25)."""
    out = np.full(int(n), -1, dtype=np.int64)
    if len(madis) == 0:
        return out
    d = madis["direction"].to_numpy()
    tb = madis["tb_idx"].to_numpy(dtype=np.int64)
    rows = np.flatnonzero(d == direction)
    keep = tb[rows] < n
    np.maximum.at(out, tb[rows][keep], rows[keep])             # 같은 봉이면 뒤 행
    return np.maximum.accumulate(out)                          # 행 순서가 tb_idx 순이므로 최대 행 = 가장 최근


def madi_waist(madis: pd.DataFrame, waist_method: str) -> np.ndarray:
    """마디 표의 허리 열 선택: 'cluster' → h_cluster, 'midpoint' → h_mid (행 순서 그대로, float64)."""
    if waist_method == "cluster":
        return madis["h_cluster"].to_numpy(dtype=np.float64)
    if waist_method == "midpoint":
        return madis["h_mid"].to_numpy(dtype=np.float64)
    raise ValueError(f"waist_method는 {C.WAIST_METHODS} 중 하나: {waist_method!r}")


def build_structure(bars: pd.DataFrame, ind: pd.DataFrame, tf: str,
                    vr_threshold: float = C.KIJUN_VR_MIN) -> Structure:
    """위 함수를 차례로 불러 types.Structure를 만든다 (alive_up/alive_dn은 start_offset=0)."""
    h, l = _col(bars, "high"), _col(bars, "low")
    n = h.shape[0]
    is_sh, is_sl = find_swings(h, l)
    last_sh, last_sl = last_confirmed(is_sh), last_confirmed(is_sl)
    kijun_up, kijun_dn = detect_kijun(bars, ind, last_sh, last_sl, vr_threshold)
    madis = detect_madis(bars, ind, is_sh, is_sl, last_sh, last_sl, kijun_up, kijun_dn, tf)
    return Structure(tf=tf, is_sh=is_sh, is_sl=is_sl, last_sh=last_sh, last_sl=last_sl,
                     kijun_up=kijun_up, kijun_dn=kijun_dn, madis=madis,
                     alive_up=paint_alive(madis, n, 1, 0), alive_dn=paint_alive(madis, n, -1, 0))
