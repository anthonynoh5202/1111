"""방향 필터(§5)·공통 고정 필터(§6 F1~F7)·리스크 검사(§8.1).

담당: 구조·시나리오. 설계: backtest/DESIGN.md §6.6, 해석 확정 I-1, I-15~I-18, I-27, I-49.

- 여기의 필터는 모두 "신호 시점에 이미 아는 값"만으로 미리(벡터로) 계산한다.
  F8(같은 마디 2손절)·F9(포지션 보유)·가용성 마스크는 거래 결과에 따라 달라지므로
  execution.run_sequence가 순차로 처리한다 (DESIGN §6.8).
- "신호 봉"은 L1a·S2·S3는 신호 봉 자신, L1b는 확인 시각에 마지막으로 마감된 S 봉(k_last)이다 (I-15).
- 상위 봉 D는 as-of 규칙: close_ns + 60초 ≤ 판단 시각인 마지막 D 봉 (config.asof_index, I-1).
- 리스크 검사(stop_band_ok·risk_reasons)의 식은 체결 엔진 모듈(execution)에 있는 것이 단일 출처다.
  여기 함수는 같은 시그니처로 그것을 부른다(두 팀이 같은 식을 따로 쓰다 어긋나지 않게).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import config as C
from backtest import execution as X
from backtest.config import ComboConfig
from backtest.structure import madi_waist
from backtest.types import Reason, ScenarioContext, Structure

FIXED_FLAG_COLUMNS = ("F2", "F4", "F5", "F6")  # fixed_filter_flags 결과 열 (bool)
FILTER_CODES = (Reason.F1, Reason.F2, Reason.F3, Reason.F4, Reason.F5, Reason.F6, Reason.F7)  # REASON_ORDER 순서


# ---------------------------------------------------------------------------
# §5 방향 필터
# ---------------------------------------------------------------------------


def direction_permission(d_bars: pd.DataFrame, d_ind: pd.DataFrame, d_struct: Structure, method: str,
                         waist_method: str = "cluster") -> tuple[np.ndarray, np.ndarray]:
    """방향 봉 D마다 롱·숏 허용 여부 (§5). 반환 (long_ok, short_ok) bool 배열 (길이 = D 봉 수).

    DA: long_ok[j] = alive_up[j] ≥ 0 and close[j] > 그 마디 허리; short_ok[j] = alive_dn[j] ≥ 0 and close[j] < 허리.
        허리는 waist_method로 고른다(structure.madi_waist).
    DB: long_ok[j] = slope60 > 0 and slope120 > 0; short_ok[j] = 둘 다 < 0 (NaN이면 False).
    """
    close = d_bars["close"].to_numpy(dtype=np.float64)
    if method == "DA":
        waist = madi_waist(d_struct.madis, waist_method)
        up = np.asarray(d_struct.alive_up, dtype=np.int64)
        dn = np.asarray(d_struct.alive_dn, dtype=np.int64)
        h_up = waist[up] if waist.size else np.full(up.shape, np.nan)  # up = −1이면 아래에서 버린다
        h_dn = waist[dn] if waist.size else np.full(dn.shape, np.nan)
        long_ok = (up >= 0) & (close > h_up)     # §5 DA 롱: 가장 최근 살아 있는 상승 마디 & D 종가 > 그 허리
        short_ok = (dn >= 0) & (close < h_dn)    # §5 DA 숏: 가장 최근 살아 있는 하락 마디 & D 종가 < 그 허리
        return long_ok, short_ok
    if method == "DB":
        with np.errstate(invalid="ignore"):
            s_mid, s_long = (d_ind[f"slope{n}"].to_numpy(dtype=np.float64) for n in C.DB_SLOPE_NS)
            long_ok = (s_mid > 0) & (s_long > 0)     # §5 DB 롱: 기울기 60 상승 그리고 기울기 120 상승
            short_ok = (s_mid < 0) & (s_long < 0)    # §5 DB 숏: 둘 다 하락 (동률·NaN이면 불허, I-5)
        return long_ok, short_ok
    raise ValueError(f"방향 필터는 {C.DIRECTION_FILTERS} 중 하나: {method!r}")


def direction_asof_index(ctx: ScenarioContext, approval_ns) -> np.ndarray:
    """판단 시각마다 쓸 수 있는 마지막 D 봉 번호 (close_ns + 60초 ≤ 판단 시각, 없으면 −1) (§1, I-1, C-2)."""
    key = ("d_avail",)
    if key not in ctx.cache:
        ctx.cache[key] = ctx.d_bars["close_ns"].to_numpy(dtype=np.int64) + C.AVAIL_DELAY_NS
    return np.atleast_1d(C.asof_index(ctx.cache[key], np.asarray(approval_ns, dtype=np.int64)))


def direction_at(ctx: ScenarioContext, method: str, waist_method: str,
                 approval_ns: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """판단 시각들에서의 (long_ok, short_ok). D 봉 as-of 번호 = asof_index(d_close_ns + 60초, approval_ns).

    as-of 번호가 −1이면 둘 다 False. 봉별 허용 배열은 ctx.cache[('dir', method, waist_method)]에 캐시한다.
    """
    key = ("dir", method, waist_method)
    if key not in ctx.cache:
        ctx.cache[key] = direction_permission(ctx.d_bars, ctx.d_ind, ctx.d_struct, method, waist_method)
    long_bar, short_bar = ctx.cache[key]
    j = direction_asof_index(ctx, approval_ns)               # §1 진행 중인 D 봉 금지 (I-1)
    ok = j >= 0                                              # C-10 as-of 결과 −1이면 신호 없음
    long_ok = np.zeros(j.shape, dtype=bool)
    short_ok = np.zeros(j.shape, dtype=bool)
    long_ok[ok] = long_bar[j[ok]]
    short_ok[ok] = short_bar[j[ok]]
    return long_ok, short_ok


# ---------------------------------------------------------------------------
# §6 공통 고정 필터 (F2·F4·F5·F6: S 봉마다 미리 계산)
# ---------------------------------------------------------------------------


def trap_events(bars: pd.DataFrame, struct: Structure) -> pd.DataFrame:
    """F6 트랩 목록 (감사·테스트용). 열: kind('support'|'resistance'), break_idx(j), done_idx(m), level, known_ns.

    known_ns = 완성 봉 m의 마감 시각(close_ns[m]) = 그 트랩을 알게 된 시각. 정의는 trap_counts docstring (I-17).
    """
    c = bars["close"].to_numpy(dtype=np.float64)
    close_ns = bars["close_ns"].to_numpy(dtype=np.int64)
    n = c.shape[0]
    parts = []
    for kind, last, ref_px, sign in (("support", struct.last_sl, bars["low"], 1.0),
                                     ("resistance", struct.last_sh, bars["high"], -1.0)):
        if n < 2:
            break
        px = ref_px.to_numpy(dtype=np.float64)
        j = np.arange(1, n, dtype=np.int64)
        ref = np.asarray(last, dtype=np.int64)[j - 1]           # I-17 기준 = j−1 시점 확정 가장 최근 스윙
        has = ref >= 0
        level = np.where(has, px[np.clip(ref, 0, None)], np.nan)
        prev, cur = c[j - 1], c[j]
        with np.errstate(invalid="ignore"):
            # 지지(sign +1): close[j−1] ≥ L > close[j] (이탈), 저항(sign −1): close[j−1] ≤ H < close[j] (돌파)
            brk = has & (sign * prev >= sign * level) & (sign * level > sign * cur)
        jb, lev = j[brk], level[brk]
        if jb.size == 0:
            continue
        mm = jb[:, None] + np.arange(1, C.F6_RETURN_BARS + 1)[None, :]   # §6 F6 이탈 뒤 5봉 안
        inb = mm < n
        cm = c[np.clip(mm, 0, n - 1)]
        back = inb & (sign * cm > sign * lev[:, None])                  # 종가가 그 가격 위(저항: 아래)로 복귀
        done = back.any(axis=1)
        m = jb[done] + 1 + np.argmax(back[done], axis=1)                # 처음 복귀한 봉 = 완성 봉
        parts.append(pd.DataFrame({"kind": kind, "break_idx": jb[done], "done_idx": m.astype(np.int64),
                                   "level": lev[done], "known_ns": close_ns[m]}))
    if not parts:
        return pd.DataFrame({"kind": pd.Series([], dtype=object), "break_idx": pd.Series([], dtype=np.int64),
                             "done_idx": pd.Series([], dtype=np.int64), "level": pd.Series([], dtype=np.float64),
                             "known_ns": pd.Series([], dtype=np.int64)})
    return pd.concat(parts, ignore_index=True)


def trap_counts(bars: pd.DataFrame, struct: Structure) -> np.ndarray:
    """F6용: 봉 t에서 직전 48봉 안에 완성된 트랩 수 (int64, I-17).

    지지 트랩: 봉 j에서 L = low[last_sl[j−1]] (j−1 시점 확정 스윙 저점)일 때 close[j−1] ≥ L > close[j] (이탈),
               이후 m ∈ [j+1, j+5] 중 처음 close[m] > L 이면 트랩, 완성 봉 = m.
    저항 트랩: 대칭 (high[last_sh[j−1]], close[j−1] ≤ H < close[j], 이후 close[m] < H).
    결과[t] = 완성 봉 m ∈ [t−48, t−1] 인 트랩 수 (지지 + 저항).
    """
    n = len(bars)
    done = np.zeros(n, dtype=np.int64)
    ev = trap_events(bars, struct)
    if len(ev):
        np.add.at(done, ev["done_idx"].to_numpy(dtype=np.int64), 1)
    cs = np.r_[0, np.cumsum(done)]
    t = np.arange(n, dtype=np.int64)
    lo = np.maximum(t - C.F6_LOOKBACK, 0)
    return (cs[t] - cs[lo]).astype(np.int64)                    # I-17 완성 봉 ∈ [t−48, t−1] (현재 봉 제외)


def fixed_filter_flags(bars: pd.DataFrame, ind: pd.DataFrame, struct: Structure) -> pd.DataFrame:
    """S 봉마다 F2·F4·F5·F6 걸림 여부 (열 = FIXED_FLAG_COLUMNS, bool, 인덱스 = bars.index).

    F2: vr < 0.7 and atr ≤ atr_q20 (§6, I-3)
    F4: spread_on
    F5: surge가 [t−5, t−1] 중 하나라도 True (I-16)
    F6: trap_counts ≥ 2 (I-17)
    NaN 때문에 판단할 수 없으면 False (그런 봉은 valid=False라 어차피 WARMUP으로 폐기).
    """
    vr = ind["vr"].to_numpy(dtype=np.float64)
    atr = ind["atr"].to_numpy(dtype=np.float64)
    atr_q = ind["atr_q20"].to_numpy(dtype=np.float64)
    with np.errstate(invalid="ignore"):
        f2 = (vr < C.F2_VR_MAX) & (atr <= atr_q)                # §6 F2 VR < 0.7 그리고 ATR 하위 20%
    f4 = ind["spread_on"].to_numpy(dtype=bool)                  # §6 F4 이평 확산
    surge = ind["surge"].to_numpy(dtype=np.int64)               # 봉 자신의 범위 ≥ 3 × 자기 ATR
    cs = np.r_[0, np.cumsum(surge)]
    t = np.arange(surge.shape[0], dtype=np.int64)
    f5 = (cs[t] - cs[np.maximum(t - C.F5_LOOKBACK, 0)]) > 0     # §6 F5·I-16 [t−5, t−1]에 급등 봉
    f6 = trap_counts(bars, struct) >= C.F6_MIN_TRAPS            # §6 F6 직전 48봉 트랩 2회 이상
    return pd.DataFrame({"F2": f2, "F4": f4, "F5": f5, "F6": f6}, index=bars.index)


def f7_block(struct: Structure, s_idx: np.ndarray, side: int) -> np.ndarray:
    """F7 (§6, I-18): 롱이면 봉 s_idx에 살아 있는 하락 마디(alive_dn ≥ 0), 숏이면 살아 있는 상승 마디가 있으면 True."""
    alive = struct.alive_dn if side > 0 else struct.alive_up
    return np.asarray(alive, dtype=np.int64)[np.asarray(s_idx, dtype=np.int64)] >= 0


def event_block(approval_ns: np.ndarray, events_ns: np.ndarray | None) -> np.ndarray:
    """F3 (§6, I-49): 이벤트 e에 대해 e − 2시간 ≤ 판단 시각 ≤ e + 1시간이면 True. events_ns가 None이면 모두 False."""
    q = np.atleast_1d(np.asarray(approval_ns, dtype=np.int64))
    if events_ns is None or len(events_ns) == 0:
        return np.zeros(q.shape, dtype=bool)
    ev = np.sort(np.asarray(events_ns, dtype=np.int64))
    lo = np.searchsorted(ev, q - C.F3_AFTER_NS, side="left")    # e ≥ 판단 − 1시간
    hi = np.searchsorted(ev, q + C.F3_BEFORE_NS, side="right")  # e ≤ 판단 + 2시간 (양 끝 포함)
    return hi > lo


def filter_reasons(ctx: ScenarioContext, cfg: ComboConfig, s_idx: np.ndarray,
                   approval_ns: np.ndarray) -> list[tuple[str, ...]]:
    """후보 여러 개의 F1~F7 사유 (types.Reason 코드, REASON_ORDER 순서의 튜플 목록).

    - F1: cfg.side 방향이 direction_at(ctx, cfg.direction_filter, cfg.waist_method, approval_ns)로 허용 안 됨
    - F2·F4·F5·F6: ctx.s_flags의 s_idx 행
    - F3: cfg.event_filter_on일 때만 (켰는데 ctx.events_ns가 None이면 FileNotFoundError)
    - F7: C.SCENARIO_APPLIES_F7[cfg.scenario]일 때만 f7_block
    s_idx는 필터 기준 S 봉 번호(I-15), approval_ns는 판단 시각. 두 배열 길이가 같다.
    """
    s_idx = np.atleast_1d(np.asarray(s_idx, dtype=np.int64))
    appr = np.atleast_1d(np.asarray(approval_ns, dtype=np.int64))
    if s_idx.shape != appr.shape:
        raise ValueError("s_idx와 approval_ns 길이가 다름")
    m = s_idx.shape[0]
    if m == 0:
        return []
    long_ok, short_ok = direction_at(ctx, cfg.direction_filter, cfg.waist_method, appr)
    allowed = long_ok if cfg.side > 0 else short_ok
    zeros = np.zeros(m, dtype=bool)
    flags = ctx.s_flags
    hit = {
        Reason.F1: ~allowed,                                             # §6 F1 방향 반대 (§5)
        Reason.F2: flags["F2"].to_numpy(dtype=bool)[s_idx],
        Reason.F3: zeros,
        Reason.F4: flags["F4"].to_numpy(dtype=bool)[s_idx],
        Reason.F5: flags["F5"].to_numpy(dtype=bool)[s_idx],
        Reason.F6: flags["F6"].to_numpy(dtype=bool)[s_idx],
        Reason.F7: zeros,
    }
    if cfg.event_filter_on:                                              # §6 F3, §10-2 기본 꺼짐
        if ctx.events_ns is None:
            raise FileNotFoundError(f"F3를 켰는데 이벤트 파일이 없음: {C.EVENTS_CSV} (DESIGN I-49)")
        hit[Reason.F3] = event_block(appr, ctx.events_ns)
    if C.SCENARIO_APPLIES_F7[cfg.scenario]:                              # §7.3 S2는 F7 제외
        hit[Reason.F7] = f7_block(ctx.s_struct, s_idx, cfg.side)
    table = np.stack([hit[code] for code in FILTER_CODES], axis=1)       # (m, 7) — REASON_ORDER 순서
    return [tuple(code for code, on in zip(FILTER_CODES, row) if on) for row in table.tolist()]


# ---------------------------------------------------------------------------
# §8.1 리스크 검사 — 식은 execution 모듈이 단일 출처
# ---------------------------------------------------------------------------


def stop_band_ok(entry, stop, atr):
    """§8.1 손절 폭: max(0.4% × entry, 1 × ATR) ≤ |entry − stop| ≤ min(2% × entry, 3 × ATR) (양 끝 포함).

    ATR은 신호 봉(L1b는 k_last) ATR (§12.2). 배열·스칼라 모두 받는다.
    (execution.stop_band_ok를 그대로 부른다: 양 끝은 부동소수 오차 1e-9만큼 포함, NaN이면 실패.)
    """
    return X.stop_band_ok(entry, stop, atr)


def risk_reasons(side: int, entry: float, stop: float, target: float, atr: float,
                 order_type: str) -> tuple[str, ...]:
    """§8.1 리스크 검사 사유: RISK_STOP_BAND(stop_band_ok 실패), RISK_RR(config.net_rr < 1.5).

    비용은 항상 기본 비용(배수 1)으로 계산한다 (I-27). 진입 수수료율 = config.entry_fee_rate(order_type).
    포지션 크기는 폐기 사유가 아니다 (I-28).
    (execution.risk_reasons를 그대로 부른다 — 식의 단일 출처.)
    """
    return X.risk_reasons(side, entry, stop, target, atr, order_type)
