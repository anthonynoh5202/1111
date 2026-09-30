"""적대적 검토: 명세 일치 감사 — RULES_SPEC v1.0 §3~§8, §12 문장 ↔ 코드 1:1 대조 (검토자 전용, 제품 코드는 고치지 않는다).

기준: docs/RULES_SPEC.md v1.0 (특히 §12 구현 확정 사항). 설계 해석 번호(I-n)는 backtest/DESIGN.md §7.

구성
A. test_spec_*      : 명세 문장의 숫자·부등호·목록(변형 16개·민감도 80개)을 손으로 다시 적어 config·공용 함수와 대조.
B. test_ref_*       : 명세 문장에서 따로 짠 느린 참조 구현(_ref_*) vs 제품 — 실데이터 전수(@slow).
                      B1 지표·스윙·기준봉·마디·허리(1h·4h·1d 전체 봉)
                      B2 16조합 후보 전부: 사유 집합(SC·F1~F7·기하·RISK)·진입/손절/목표·만료·취소 효력 시각·취소 종류
C. test_hand_*      : 실데이터 신호 몇 개를 원본 CSV(backtest.data 안 씀)에서 명세 문장대로 한 줄씩 따라가 손으로 확인
                      (L1a 손절·L1a 취소·L1b 목표·L1b IOC 미체결·S2 목표·S3 목표 선택). 손 계산 값은 숫자로 박아 둔다.
D. test_g1_*        : G1 판정 7개 기준의 경계값(부등호 방향)과 pass/fail/pending.
E. test_finding_*   : 명세 해석 쟁점을 숫자로 고정한 기록(현재 동작 — 통과해야 한다).
   xfail(strict)    : 명세 문장과 다른 해석. 고치면 XPASS → strict 실패로 알려 준다(그때 표시를 지운다).

성과 숫자(조합 평균 R 등)는 보지 않는다. 손 추적 거래 몇 건의 R만 손 계산과 맞춘다.
참조 구현은 backtest 모듈을 쓰지 않는다(숫자도 명세에서 손으로 다시 적음). 실데이터가 없으면 B·C·E는 건너뛴다.
"""
from __future__ import annotations

import collections
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import execution as X
from backtest import metrics as M
from backtest import scenarios as SC
from backtest.types import ExecArrays, FundingArrays

DATA = Path(__file__).resolve().parents[2] / "data" / "binance"
HAVE_DATA = (DATA / "BTCUSDT_1h.csv.gz").exists() and (DATA / "BTCUSDT_1m_2024.csv.gz").exists()
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="실데이터 없음 (data/binance)")

# 명세 값 (손으로 다시 적음 — config가 틀려도 잡히게)
MAKER, TAKER, SLIP = 0.0002, 0.0005, 0.0002           # §8.2, §12.2
SEC_NS = 10**9
MIN_NS = 60 * SEC_NS
AVAIL = 60 * SEC_NS                                     # §1, §12.1 마감 + 60초
MS = 1_000_000                                          # ms → ns
H1_MS, M1_MS, M5_MS, M15_MS = 3_600_000, 60_000, 300_000, 900_000
SWITCH_MS = 1_696_118_400_000                           # §12.1 2023-10-01 00:00 UTC (1분봉 시작)


def _rnd(x) -> float:
    """§7 공통: 0.1 USDT 반올림."""
    return float(np.round(float(x), 1))


def _ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value // MS)


# ===========================================================================
# A. 명세 숫자·목록 (config) — 손으로 다시 적은 값과 대조
# ===========================================================================


def test_spec_numbers_sections_2_to_7():
    """§2 봉 설정·지연, §3 기본 수치, §4 구조, §5 방향, §6 필터, §7 시나리오 숫자."""
    assert C.SETTINGS["P1"] == ("1h", "4h", "15m") and C.SETTINGS["P2"] == ("4h", "1d", "1h")   # §2 (S, D, C)
    assert C.LATENCY_DEFAULT_MIN == 10 and tuple(C.LATENCY_SENSITIVITY_MIN) == (5, 15)          # §2 지연 L
    assert (C.ATR_N, C.VR_N, C.BODY_AVG_N, C.LONG_BAR_MULT, C.SWING_K) == (14, 20, 20, 2.0, 3)    # §3
    assert tuple(C.MA_PERIODS) == (20, 60, 120) and (C.SPREAD_LOOKBACK, C.SPREAD_QUANTILE) == (500, 0.80)
    assert C.BUFFER_ATR_MULT == 0.1                                                              # §3 b = 0.1 ATR
    assert (C.KIJUN_VR_MIN, C.KIJUN_MAX_WICK, tuple(C.KIJUN_SLOPE_NS)) == (2.0, 0.5, (20, 60))    # §4.1
    assert (C.MADI_B_MAX_BARS, C.MADI_PRE_VOL_N, C.MADI_ALIVE_BARS) == (60, 20, 300)            # §4.2
    assert tuple(C.WAIST_BAND) == (0.35, 0.65) and C.WAIST_BIN_FRAC == 0.001 and C.WAIST_FALLBACK_FRAC == 0.5  # §4.3
    assert tuple(C.DB_SLOPE_NS) == (60, 120)                                                     # §5 DB
    assert (C.F2_VR_MAX, C.F2_ATR_LOOKBACK, C.F2_ATR_QUANTILE) == (0.7, 100, 0.20)               # §6 F2
    assert (C.F3_BEFORE_NS, C.F3_AFTER_NS) == (2 * 3600 * SEC_NS, 3600 * SEC_NS)                 # §6 F3
    assert (C.F5_LOOKBACK, C.F5_RANGE_ATR_MULT) == (5, 3.0)                                      # §6 F5
    assert (C.F6_LOOKBACK, C.F6_RETURN_BARS, C.F6_MIN_TRAPS, C.F8_MAX_STOPS) == (48, 5, 2, 2)    # §6 F6·F8
    assert (C.L1A_VALID_BARS, C.L1A_SLOPE_N, C.L1A_EXTENSION_W) == (24, 60, 0.5)                 # §7.1
    assert (C.L1B_ZONE_W, C.L1B_ARM_BARS, C.L1B_CAP_MULT, C.L1B_MAX_CLOSES_BELOW_H) == (0.25, 24, 1.001, 2)  # §7.2
    assert (C.S2_VR_MIN, C.S2_STOP_ATR_MULT, C.S2_VALID_BARS) == (2.0, 0.5, 12)                  # §7.3
    assert (C.S3_LOOKBACK, C.S3_TOUCH_TOL, C.S3_MIN_TOUCHES, C.S3_VR_MIN, C.S3_REBREAK_WINDOW,
            C.S3_STOP_ATR_MULT, C.S3_VALID_BARS) == (100, 0.001, 2, 2.0, 10, 1.0, 12)             # §7.4
    assert C.PRICE_TICK == 0.1                                                                    # §7 공통
    assert C.SCENARIO_SIDE == {"L1a": 1, "L1b": 1, "S2": -1, "S3": -1}
    assert C.SCENARIO_ORDER_TYPE == {"L1a": "limit", "L1b": "ioc_cap", "S2": "limit", "S3": "limit"}
    assert C.SCENARIO_APPLIES_F7 == {"L1a": True, "L1b": True, "S2": False, "S3": True}           # §7.3 S2만 F7 제외


def test_spec_numbers_sections_8_to_12():
    """§8.1 리스크, §8.2·§12 체결·비용·마스크, §8.3 G1, §12.4 통계."""
    assert (C.STOP_MIN_PCT, C.STOP_MIN_ATR, C.STOP_MAX_PCT, C.STOP_MAX_ATR) == (0.004, 1.0, 0.02, 3.0)  # §8.1
    assert (C.MIN_NET_RR, C.RISK_FRACTION, C.MAX_NOTIONAL_FRAC, C.MAX_LEVERAGE) == (1.5, 0.005, 0.6, 3)
    assert (C.FEE_MAKER, C.FEE_TAKER, C.SLIPPAGE, C.MAX_HOLD_BARS) == (MAKER, TAKER, SLIP, 72)   # §8.2·§12.2
    assert C.FUNDING_FALLBACK_RATE == 0.0001 and C.FUNDING_FALLBACK_FROM_NS == _ms("2026-09-01") * MS
    assert C.EXEC_SWITCH_NS == SWITCH_MS * MS                                                    # §12.1 실행 봉 전환
    assert (C.DND_START_MIN_KST, C.DND_END_MIN_KST, C.DAILY_APPROVAL_CAP) == (30, 450, 6)       # §10-3, §12.3
    assert (C.G1_MIN_MEAN_R, C.G1_MIN_PF, C.G1_COST_STRESS_MULT, C.G1_RANDOM_QUANTILE) == (0.15, 1.2, 2.0, 0.95)
    assert tuple(C.G1_YEARS) == (2020, 2021, 2022, 2023, 2024, 2025, 2026) and C.G1_MIN_POSITIVE_YEARS == 4
    assert C.G1_MIN_TRADES == 30                                                                  # §8.3-7
    assert (C.BOOTSTRAP_N, C.BOOTSTRAP_LOWER_Q, C.DSR_N_TRIALS) == (10_000, 0.025, 16)            # §12.4
    assert (C.RANDOM_REPS, C.RANDOM_REPS_REDUCED) == (1000, 300)
    assert tuple(C.DONCHIAN_PERIODS) == (20, 55, 100) and C.DONCHIAN_NOTIONAL_CAP == 0.6


def test_spec_combos_16_and_sensitivity_80():
    """§9: 시나리오 4 × 방향 2 × 봉 설정 2 = 16, 민감도 = 지연 5·15분, 허리 (고+저)÷2, VR 3, 비용 2배 (보고만)."""
    combos = C.g1_combos()
    assert len(combos) == 16 and len({c.base_key for c in combos}) == 16
    assert {(c.scenario, c.direction_filter, c.setting) for c in combos} == {
        (s, d, p) for s in ("L1a", "L1b", "S2", "S3") for d in ("DA", "DB") for p in ("P1", "P2")}
    for c in combos:   # 기본값: 지연 10분, 허리 칸 방식, VR 2, 비용 1배, F3 꺼짐(§10-2), 실행 가능 모드
        assert (c.latency_min, c.waist_method, c.vr_threshold, c.cost_multiplier, c.event_filter_on) == \
            (10, "cluster", 2.0, 1.0, False)
    sens = C.sensitivity_combos()
    assert len(sens) == 80
    by_tag = collections.defaultdict(list)
    for tag, cfg in sens:
        by_tag[tag].append(cfg)
        assert cfg.apply_availability_mask                         # 실행 가능 모드
    assert set(by_tag) == {"lat5", "lat15", "mid", "vr3", "cost2"}
    assert all(c.latency_min == 5 for c in by_tag["lat5"]) and all(c.latency_min == 15 for c in by_tag["lat15"])
    assert all(c.waist_method == "midpoint" for c in by_tag["mid"])
    assert all(c.vr_threshold == 3.0 for c in by_tag["vr3"]) and all(c.cost_multiplier == 2.0 for c in by_tag["cost2"])
    for tag, cfgs in by_tag.items():                               # 변형마다 바꾼 값 하나만 기본과 다르다
        assert len(cfgs) == 16 and {c.base_key for c in cfgs} == {c.base_key for c in combos}


def test_spec_risk_formulas_hand_cases():
    """§8.1 손절 폭 양 끝 포함, §12.2 순손익비·R 분모 식 (손 계산)."""
    # 손절 폭: entry 100, ATR 0.3 → 하한 max(0.4, 0.3) = 0.4, 상한 min(2.0, 0.9) = 0.9
    assert X.stop_band_ok(100.0, 99.6, 0.3) and not X.stop_band_ok(100.0, 99.61, 0.3)
    assert X.stop_band_ok(100.0, 99.1, 0.3) and not X.stop_band_ok(100.0, 99.09, 0.3)
    # 순손익비 (롱 지정가): (102 − 100 − 0.0002·100 − 0.0002·102) ÷ (1 + 0.0002·100 + 0.0007·99)
    want = (2 - 0.02 - 0.0204) / (1 + 0.02 + 0.0693)
    assert C.net_rr(1, 100.0, 99.0, 102.0, MAKER) == pytest.approx(want, abs=1e-12)
    # L1b 상한 지정가는 테이커 진입 수수료
    want_ioc = (2 - 0.05 - 0.0204) / (1 + 0.05 + 0.0693)
    assert C.net_rr(1, 100.0, 99.0, 102.0, C.entry_fee_rate("ioc_cap")) == pytest.approx(want_ioc, abs=1e-12)
    # R 분모 = d + c_stop, c_stop = 진입 수수료 + 손절 테이커 + 손절 슬리피지 (§12.2)
    assert C.risk_per_unit(30000.0, 29850.0, MAKER) == pytest.approx(150 + 6.0 + 0.0007 * 29850, abs=1e-9)
    # 숏 대칭
    assert C.net_rr(-1, 100.0, 101.0, 98.0, MAKER) == pytest.approx(
        (2 - 0.02 - 0.0196) / (1 + 0.02 + 0.0007 * 101), abs=1e-12)


def test_spec_dnd_and_daily_cap_boundaries():
    """§12.3 KST [00:30, 07:30) 방해 금지. 1시간·15분봉 마감(+60초)이 경계와 어긋나지 않는다."""
    kst = lambda s: C.ts_ns(s) - 9 * 3600 * SEC_NS               # KST 벽시계 s의 UTC 순간
    assert not C.in_dnd(kst("2024-01-02 00:29:59")) and C.in_dnd(kst("2024-01-02 00:30"))
    assert C.in_dnd(kst("2024-01-02 07:29:59")) and not C.in_dnd(kst("2024-01-02 07:30"))
    # 명세 "승인 시각 = 신호 시각(L1b는 확인 시각)" vs 코드 "신호 시각 + 60초": 봉 마감이 15분 격자라 판정이 같다
    for hh in range(24):
        for mm in (0, 15, 30, 45):
            t = kst(f"2024-01-02 {hh:02d}:{mm:02d}")
            assert bool(C.in_dnd(t)) == bool(C.in_dnd(t + AVAIL))
            assert int(C.kst_day_index(t)) == int(C.kst_day_index(t + AVAIL))


# ===========================================================================
# B. 참조 구현 (명세 문장에서 직접, backtest 모듈 안 씀) — 느리지만 읽기 쉽게
# ===========================================================================


def _arrs(bars: pd.DataFrame) -> dict:
    return {k: bars[k].to_numpy() for k in ("open", "high", "low", "close", "volume", "open_ns", "close_ns")}


class _RefInd:
    """§3 지표: 봉마다 창 평균·분위를 np.mean/np.quantile로 직접 (현재 봉 제외 = [t−n, t−1])."""

    def __init__(self, a: dict):
        o, h, l, c, v = a["open"], a["high"], a["low"], a["close"], a["volume"]
        n = len(c)
        self.body, self.rng = np.abs(c - o), h - l
        tr = np.full(n, np.nan)
        for j in range(1, n):                                   # TR = max(h−l, |h−c₋₁|, |l−c₋₁|)
            tr[j] = max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1]))
        nan = np.full(n, np.nan)
        self.atr, vavg, bavg = nan.copy(), nan.copy(), nan.copy()
        ma = {p: nan.copy() for p in (20, 60, 120)}
        for t in range(n):
            if t >= 15:
                self.atr[t] = np.mean(tr[t - 14:t])             # 직전 14개 TR
            if t >= 20:
                vavg[t] = np.mean(v[t - 20:t])                  # 직전 20개 거래량
                bavg[t] = np.mean(self.body[t - 20:t])          # 직전 20개 몸통
            for p in (20, 60, 120):
                if t >= p:
                    ma[p][t] = np.mean(c[t - p:t])
        with np.errstate(invalid="ignore", divide="ignore"):
            self.vr = v / vavg
            self.long = self.body >= 2 * bavg                   # 장대봉
            safe = np.where(self.rng > 0, self.rng, 1.0)
            self.uw = np.where(self.rng > 0, (h - np.maximum(o, c)) / safe, 0.0)
            self.lw = np.where(self.rng > 0, (np.minimum(o, c) - l) / safe, 0.0)
            st = np.vstack([ma[20], ma[60], ma[120]])
            self.spread = (st.max(axis=0) - st.min(axis=0)) / c
        self.spread_on = np.zeros(n, bool)
        self.atr_q20 = nan.copy()
        for t in range(620, n):                                 # 직전 500봉 중 상위 20% 이상
            self.spread_on[t] = self.spread[t] >= np.quantile(self.spread[t - 500:t], 0.8)
        for t in range(115, n):
            self.atr_q20[t] = np.quantile(self.atr[t - 100:t], 0.2)
        self.slope = {}
        for p in (20, 60, 120):
            s = np.full(n, np.nan)
            s[p:] = np.sign(c[p:] - c[:-p])
            self.slope[p] = s
        self.valid = np.arange(n) >= 620                        # §12.3 이평 확산 500봉 준비
        with np.errstate(invalid="ignore"):
            self.surge = self.rng >= 3 * self.atr


def _ref_swings(a: dict) -> tuple[np.ndarray, np.ndarray]:
    """§3 스윙: 앞 3개·뒤 3개보다 모두 (엄격히) 큼/작음."""
    h, l = a["high"], a["low"]
    n = len(h)
    sh, sl = np.zeros(n, bool), np.zeros(n, bool)
    for i in range(3, n - 3):
        sh[i] = all(h[i] > h[j] for j in range(i - 3, i + 4) if j != i)
        sl[i] = all(l[i] < l[j] for j in range(i - 3, i + 4) if j != i)
    return sh, sl


def _ref_last(flags: np.ndarray) -> np.ndarray:
    """봉 t 마감에 확정된 가장 최근 스윙 (i + 3 ≤ t)."""
    out, cur = np.full(len(flags), -1, np.int64), -1
    for t in range(len(flags)):
        if t - 3 >= 0 and flags[t - 3]:
            cur = t - 3
        out[t] = cur
    return out


def _ref_kijun(a, ind, sh, sl, vr_thr=2.0):
    """§4.1 기준봉 (상승·하락)."""
    o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    lsh, lsl = _ref_last(sh), _ref_last(sl)
    up, dn = np.zeros(len(c), bool), np.zeros(len(c), bool)
    for t in range(len(c)):
        if not (ind.valid[t] and ind.long[t] and ind.vr[t] >= vr_thr and not ind.spread_on[t]):
            continue
        up[t] = bool(c[t] > o[t] and ind.slope[20][t] > 0 and ind.slope[60][t] > 0 and lsh[t] >= 0
                     and c[t] > h[lsh[t]] and ind.uw[t] < 0.5)
        dn[t] = bool(c[t] < o[t] and ind.slope[20][t] < 0 and ind.slope[60][t] < 0 and lsl[t] >= 0
                     and c[t] < l[lsl[t]] and ind.lw[t] < 0.5)
    return up, dn, lsh, lsl


def _ref_waist(a, ai, bi, A, B) -> tuple[float, bool]:
    """§4.3 허리 (칸 = A 쪽 구간 끝에서 폭 = 그 가격 × 0.001, 마지막 칸 잘림, 동점 → 걸친 봉 거래량 → A 쪽 칸)."""
    o, h, l, c, v = a["open"], a["high"], a["low"], a["close"], a["volume"]
    d = 1.0 if B > A else -1.0
    W = abs(B - A)
    lo_end, hi_end = A + d * 0.35 * W, A + d * 0.65 * W
    w = lo_end * 0.001
    umax = 0.30 * W / w
    K = max(1, int(math.ceil(umax - 1e-9)))
    p_lo, p_hi = min(lo_end, hi_end), max(lo_end, hi_end)
    counts = [0] * K
    for j in range(ai, bi + 1):
        for x in (o[j], h[j], l[j], c[j]):
            if p_lo - 1e-9 <= x <= p_hi + 1e-9:
                counts[min(max(int(math.floor(d * (x - lo_end) / w + 1e-9)), 0), K - 1)] += 1
    if max(counts) == 0:
        return _rnd(A + d * 0.5 * W), True
    tied = [k for k in range(K) if counts[k] == max(counts)]
    if len(tied) > 1:
        vols = []
        for k in tied:
            e1, e2 = lo_end + d * k * w, lo_end + d * min(k + 1, umax) * w
            b_lo, b_hi = min(e1, e2), max(e1, e2)
            vols.append(sum(v[j] for j in range(ai, bi + 1) if l[j] <= b_hi + 1e-9 and h[j] >= b_lo - 1e-9))
        tied = [k for k, vol in zip(tied, vols) if vol == max(vols)]
    k = min(tied)
    return _rnd(lo_end + d * (k + min(k + 1, umax)) / 2 * w), False


def _ref_madis(a, sh, sl, up, dn, lsh, lsl) -> list[dict]:
    """§4.2·§4.4 기준마디 (I-8~I-12 해석)."""
    c, v, h, l = a["close"], a["volume"], a["high"], a["low"]
    n = len(c)
    rows = []
    for direction, kj, last_a, is_b in ((1, up, lsl, sh), (-1, dn, lsh, sl)):
        seen = set()
        for t in np.flatnonzero(kj):
            t = int(t)
            ai = int(last_a[t])
            bi = next((i for i in range(t, n) if is_b[i]), None)
            if ai < 0 or bi is None:
                continue
            tb = bi + 3
            if tb > t + 60 or tb > n - 1:                       # 60봉 안에 B 확정
                continue
            A = float(l[ai] if direction > 0 else h[ai])
            B = float(h[bi] if direction > 0 else l[bi])
            W = direction * (B - A)
            if W <= 0 or ai < 20:
                continue
            seg = c[ai:tb + 1]
            if (seg < A).any() if direction > 0 else (seg > A).any():   # T_B 전 종가 A 이탈 → 무효
                continue
            vab, vpre = float(np.mean(v[ai:bi + 1])), float(np.mean(v[ai - 20:ai]))
            if vab < vpre or bi in seen:                        # 거래량 조건, 같은 B는 가장 이른 기준봉
                continue
            seen.add(bi)
            death = next((j for j in range(tb + 1, n) if ((c[j] < A) if direction > 0 else (c[j] > A))), n)
            H, fb = _ref_waist(a, ai, bi, A, B)
            rows.append(dict(direction=direction, kijun_idx=t, a_idx=ai, b_idx=bi, tb_idx=tb, A=A, B=B, W=W,
                             H=H, H_mid=_rnd((A + B) / 2), fallback=fb, vab=vab, death=death,
                             end=min(death - 1, tb + 300)))
    rows.sort(key=lambda r: (r["tb_idx"], r["kijun_idx"], r["direction"]))
    return rows


def _ref_alive(rows, t, direction, start_offset=0) -> list[dict]:
    return [r for r in rows if r["direction"] == direction and r["tb_idx"] + start_offset <= t <= r["end"]]


def _ref_recent_alive(rows, t, direction, start_offset=0):
    best = None
    for r in _ref_alive(rows, t, direction, start_offset):   # 가장 최근 = 최대 tb (동률이면 뒤 행)
        if best is None or r["tb_idx"] >= best["tb_idx"]:
            best = r
    return best


def _ref_trap_done(a, sh, sl) -> np.ndarray:
    """§6 F6 트랩 완성 봉 (I-17: j−1 시점 최근 확정 스윙, 넘어가는 봉, 5봉 안 첫 복귀)."""
    c, h, l = a["close"], a["high"], a["low"]
    lsh, lsl = _ref_last(sh), _ref_last(sl)
    done = []
    for j in range(1, len(c)):
        for sup in (True, False):
            ref = lsl[j - 1] if sup else lsh[j - 1]
            if ref < 0:
                continue
            L = l[ref] if sup else h[ref]
            if not ((c[j - 1] >= L > c[j]) if sup else (c[j - 1] <= L < c[j])):
                continue
            for m in range(j + 1, min(j + 5, len(c) - 1) + 1):
                if (c[m] > L) if sup else (c[m] < L):
                    done.append(m)
                    break
    return np.array(sorted(done), dtype=np.int64)


class _RefSetting:
    """봉 설정 하나(P1/P2)의 참조 재료: S·D·C 봉, 지표, 스윙, 마디, 필터."""

    def __init__(self, market, setting: str):
        stf, dtf, ctf = {"P1": ("1h", "4h", "15m"), "P2": ("4h", "1d", "1h")}[setting]
        self.s_dur = {"1h": 3600, "4h": 14400}[stf] * SEC_NS
        self.a, self.da, self.ca = _arrs(market.bars[stf]), _arrs(market.bars[dtf]), _arrs(market.bars[ctf])
        self.ind, self.dind = _RefInd(self.a), _RefInd(self.da)
        self.sh, self.sl = _ref_swings(self.a)
        dsh, dsl = _ref_swings(self.da)
        self.up, self.dn, self.lsh, self.lsl = _ref_kijun(self.a, self.ind, self.sh, self.sl)
        dup, ddn, dlsh, dlsl = _ref_kijun(self.da, self.dind, dsh, dsl)
        self.rows = _ref_madis(self.a, self.sh, self.sl, self.up, self.dn, self.lsh, self.lsl)
        self.drows = _ref_madis(self.da, dsh, dsl, dup, ddn, dlsh, dlsl)
        self.trap_done = _ref_trap_done(self.a, self.sh, self.sl)

    # --- §5 방향 필터 (D 봉 as-of: 마감 + 60초 ≤ 판단 시각) ---
    def allowed(self, T: int, side: int, method: str) -> bool:
        j = int(np.searchsorted(self.da["close_ns"] + AVAIL, T, side="right")) - 1
        if j < 0:
            return False
        if method == "DB":
            s60, s120 = self.dind.slope[60][j], self.dind.slope[120][j]
            return bool((s60 > 0 and s120 > 0) if side > 0 else (s60 < 0 and s120 < 0))
        r = _ref_recent_alive(self.drows, j, side)
        return r is not None and bool(self.da["close"][j] > r["H"] if side > 0 else self.da["close"][j] < r["H"])

    # --- §6 F2·F4·F5·F6·F7 (신호 봉 s) ---
    def fixed(self, s: int, side: int, apply_f7: bool) -> set:
        ind, out = self.ind, set()
        if ind.vr[s] < 0.7 and ind.atr[s] <= ind.atr_q20[s]:
            out.add("F2")
        if ind.spread_on[s]:
            out.add("F4")
        if any(ind.surge[j] for j in range(max(0, s - 5), s)):
            out.add("F5")
        if int(((self.trap_done >= s - 48) & (self.trap_done <= s - 1)).sum()) >= 2:
            out.add("F6")
        if apply_f7 and _ref_alive(self.rows, s, -side):
            out.add("F7")
        return out


def _ref_risk(side, entry, stop, target, atr, entry_rate) -> set:
    """§8.1 손절 폭 + §12.2 순손익비 + 가격 순서(I-45)."""
    out = set()
    d = abs(entry - stop)
    if not (max(0.004 * entry, atr) - 1e-9 <= d <= min(0.02 * entry, 3 * atr) + 1e-9):
        out.add("RISK_STOP_BAND")
    if target is None:
        return out
    if not ((stop < entry < target) if side > 0 else (target < entry < stop)):
        out.add("SC_BAD_GEOMETRY")
    rr = (side * (target - entry) - entry_rate * entry - MAKER * target) / (d + entry_rate * entry + (TAKER + SLIP) * stop)
    if not rr >= 1.5 - 1e-9:
        out.add("RISK_RR")
    return out


def _ref_first_cancel(conds, t, k_hi):
    for k in range(t + 1, k_hi + 1):
        for name, f in conds:
            if f(k):
                return k, name
    return None, None


def _ref_candidates(R: _RefSetting, scen: str) -> list[dict]:
    """§7 시나리오 후보 (방향 필터 F1은 뒤에서 붙인다). 각 후보: sig·T·s·side·sc·가격·유효·취소."""
    a, ind, rows = R.a, R.ind, R.rows
    o, h, l, c, v, cns = a["open"], a["high"], a["low"], a["close"], a["volume"], a["close_ns"]
    n = len(c)
    out = []

    def add(sig, s, side, sc, entry, stop, target, atr, rate, apply_f7, valid_until, cancel):
        if not ind.valid[s]:
            out.append(dict(sig=int(sig), T=int(sig) + AVAIL, side=side, base={"WARMUP"}, warm=True))
            return
        base = set(sc) | R.fixed(s, side, apply_f7) | _ref_risk(side, entry, stop, target, atr, rate)
        k, kind = cancel
        out.append(dict(sig=int(sig), T=int(sig) + AVAIL, side=side, base=base, warm=False, entry=entry, stop=stop,
                        target=target, valid_until=valid_until, cet=None if k is None else int(cns[k]) + AVAIL,
                        cancel=kind, atr=float(atr)))

    if scen == "L1a":                                           # §7.1
        for r in (r for r in rows if r["direction"] == 1):
            t, b, A, B, W, H, vab = (r[k] for k in ("tb_idx", "b_idx", "A", "B", "W", "H", "vab"))
            sc = {x for x, bad in (("SC_CLOSE_VS_WAIST", not c[t] > H), ("SC_SLOPE60", not c[t] >= c[t - 60]),
                                   ("SC_UNHEALTHY", np.mean(v[b + 1:t + 1]) >= vab)) if bad}
            cancel = _ref_first_cancel([("close_below", lambda k: c[k] < A),
                                        ("high_above", lambda k: h[k] > B + 0.5 * W),
                                        ("unhealthy_volume", lambda k: np.mean(v[b + 1:k + 1]) >= vab)],
                                       t, min(t + 24, n - 1))
            add(cns[t], t, 1, sc, H, _rnd(A - 0.1 * ind.atr[t]), _rnd(H + W), ind.atr[t], MAKER, True,
                int(cns[t]) + 24 * R.s_dur, cancel)
    elif scen == "S2":                                          # §7.3
        for t in range(n):
            if not (c[t] < o[t] and ind.vr[t] >= 2):
                continue
            r = _ref_recent_alive(rows, t, 1, start_offset=1)
            if r is None or not c[t] < r["H"]:
                continue
            A, B, H = r["A"], r["B"], r["H"]
            cancel = _ref_first_cancel([("close_above", lambda k: c[k] > B)], t, min(t + 12, n - 1))
            add(cns[t], t, -1, set(), H, _rnd(max(h[t], H + 0.5 * ind.atr[t]) + 0.1 * ind.atr[t]), _rnd(A),
                ind.atr[t], MAKER, False, int(cns[t]) + 12 * R.s_dur, cancel)
    elif scen == "S3":                                          # §7.4 (I-25 해석)
        sw = np.flatnonzero(R.sl)
        up_rows = [(r["tb_idx"], i) for i, r in enumerate(rows) if r["direction"] == 1]
        for t in range(n):
            lo = max(0, t - 100)
            sup = -1
            for i in range(lo, t):
                if R.sl[i] and i + 3 <= t and int(np.sum(np.abs(l[lo:t] - l[i]) <= 0.001 * l[i])) >= 2:
                    sup = i
            if sup < 0:
                continue
            S = l[sup]
            nprev = int(np.sum(c[max(0, t - 9):t] < S))
            if not (c[t] < S and (ind.vr[t] >= 2 or nprev == 1)):
                continue
            sc = set()
            conf = [x for x in up_rows if x[0] <= t]
            if conf and not c[t] < rows[max(conf)[1]]["H"]:
                sc.add("SC_CLOSE_VS_WAIST")
            msk = (sw + 3 <= t) & (l[sw] < S)
            tgt = _rnd(l[sw][msk].max()) if msk.any() else None
            if tgt is None:
                sc.add("SC_NO_TARGET")
            cancel = _ref_first_cancel([("close_above", lambda k: c[k] > S)], t, min(t + 12, n - 1))
            add(cns[t], t, -1, sc, _rnd(S), _rnd(S + ind.atr[t]), tgt, ind.atr[t], MAKER, True,
                int(cns[t]) + 12 * R.s_dur, cancel)
    elif scen == "L1b":                                         # §7.2 마디당 준비 1회 (I-22, 검토 SPEC-L1B-REARM 반영)
        ca = R.ca
        co, ch, cl, cc, c_open, c_close = ca["open"], ca["high"], ca["low"], ca["close"], ca["open_ns"], ca["close_ns"]
        for r in (r for r in rows if r["direction"] == 1):
            tb, end, b, W, H, vab = (r[k] for k in ("tb_idx", "end", "b_idx", "W", "H", "vab"))
            tb_close = int(cns[tb])
            arm = next((kk for kk in range(tb + 1, min(end, n - 1) + 1) if H <= l[kk] <= H + 0.25 * W), None)
            if arm is None:                                     # 살아 있는 동안 준비가 한 번도 없음
                continue
            arm_close = int(cns[arm])
            win_end = arm_close + 24 * R.s_dur                  # 준비 후 24 신호 봉 안에 확인
            below = [j for j in range(arm + 1, min(arm + 24, n - 1) + 1) if c[j] < H]
            lim = int(cns[below[1]]) if len(below) >= 2 else None   # 종가 < H 두 번째 → 폐기
            if end + 1 < n:
                lim = int(cns[end + 1]) if lim is None else min(lim, int(cns[end + 1]))   # 마디 사망·만료
            j = int(np.searchsorted(c_close, arm_close, side="right"))
            ci = None
            while j < len(cc) and c_close[j] <= win_end and (lim is None or c_close[j] < lim):
                if j >= 1 and cc[j] > co[j] and cc[j] > ch[j - 1] and cc[j] > H:
                    ci = j
                    break
                j += 1
            if ci is None:                                      # 폐기 → 그 마디의 L1b는 끝 (다시 준비하지 않음)
                continue
            close_c = int(c_close[ci])
            kl = int(np.searchsorted(cns, close_c, side="right")) - 1
            lowest = float(np.min(cl[int(np.searchsorted(c_open, tb_close, side="left")):ci + 1]))
            sc = {"SC_UNHEALTHY"} if np.mean(v[b + 1:kl + 1]) >= vab else set()
            add(close_c, kl, 1, sc, _rnd(cc[ci] * 1.001), _rnd(min(lowest, H) - 0.1 * ind.atr[kl]),
                _rnd(lowest + W), ind.atr[kl], TAKER, True, None, (None, None))
    return out


# ---------------------------------------------------------------------------
# B 고정 재료 (모듈 단위, 한 번만)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def market():
    from backtest import data as D
    return D.load_market()


@pytest.fixture(scope="module")
def xb_fa(market):
    return ExecArrays.from_frame(market.exec_bars), FundingArrays.from_frame(market.funding)


@pytest.fixture(scope="module")
def ctxs(market):
    return {p: SC.build_context(market, p, 2.0) for p in ("P1", "P2")}


@pytest.fixture(scope="module")
def refs(market):
    return {p: _RefSetting(market, p) for p in ("P1", "P2")}


# ===========================================================================
# B1·B2. 참조 구현 vs 제품 (실데이터 전수)
# ===========================================================================


@needs_data
@pytest.mark.slow
@pytest.mark.parametrize("setting", ["P1", "P2"])
def test_ref_structure_matches_product(setting, refs, ctxs):
    """§3 지표·스윙, §4.1 기준봉, §4.2 마디, §4.3 허리(칸·중간값·대체값), 살아 있음 끝 — S봉·D봉 전체가 같다."""
    R, ctx = refs[setting], ctxs[setting]
    for ref_a, ref_ind, ref_rows, bars_ind, struct, ref_sw in (
            (R.a, R.ind, R.rows, ctx.s_ind, ctx.s_struct, (R.sh, R.sl, R.up, R.dn)),
            (R.da, R.dind, R.drows, ctx.d_ind, ctx.d_struct, None)):
        np.testing.assert_array_equal(ref_ind.atr, bars_ind["atr"].to_numpy())
        np.testing.assert_array_equal(ref_ind.vr, bars_ind["vr"].to_numpy())
        np.testing.assert_array_equal(ref_ind.spread_on, bars_ind["spread_on"].to_numpy())
        np.testing.assert_array_equal(ref_ind.long, bars_ind["long_bar"].to_numpy())
        np.testing.assert_array_equal(ref_ind.valid, bars_ind["valid"].to_numpy())
        if ref_sw is not None:
            sh, sl, up, dn = ref_sw
            np.testing.assert_array_equal(sh, struct.is_sh)
            np.testing.assert_array_equal(sl, struct.is_sl)
            np.testing.assert_array_equal(up, struct.kijun_up)
            np.testing.assert_array_equal(dn, struct.kijun_dn)
        m = struct.madis
        assert len(ref_rows) == len(m)
        for r, (_, p) in zip(ref_rows, m.iterrows()):
            assert (r["direction"], r["kijun_idx"], r["a_idx"], r["b_idx"], r["tb_idx"]) == \
                (p.direction, p.kijun_idx, p.a_idx, p.b_idx, p.tb_idx)
            assert (r["A"], r["B"], r["H"], r["H_mid"], r["fallback"], r["death"], r["end"]) == \
                (p.a_price, p.b_price, p.h_cluster, p.h_mid, p.waist_fallback, p.death_idx, p.end_idx)
            assert r["W"] == pytest.approx(p.w, abs=1e-9)


def _key(x):
    return (x["entry"] if x.get("entry") is not None else 0, x.get("stop") or 0, x.get("target") or 0)


@needs_data
@pytest.mark.slow
@pytest.mark.parametrize("setting", ["P1", "P2"])
@pytest.mark.parametrize("scen", ["L1a", "L1b", "S2", "S3"])
def test_ref_candidates_match_product_all_combos(setting, scen, refs, ctxs):
    """16조합 × 모든 후보: 사유 집합·진입/손절/목표·만료·취소 효력 시각·취소 종류가 참조 구현과 같다(DA·DB)."""
    R, ctx = refs[setting], ctxs[setting]
    raws = _ref_candidates(R, scen)
    assert raws, "후보가 하나도 없음 — 참조 구현 확인 필요"
    for method in ("DA", "DB"):
        prod = SC.generate_candidates(ctx, C.ComboConfig(scen, method, setting))
        ref = []
        for x in raws:
            reasons = set(x["base"])
            if not x["warm"] and not R.allowed(x["T"], x["side"], method):
                reasons.add("F1")                                  # §6 F1 = §5 방향 불허
            ref.append(dict(x, reasons=reasons))
        by_p, by_r = collections.defaultdict(list), collections.defaultdict(list)
        for cn in prod:
            p = cn.plan
            by_p[cn.log.signal_time].append(dict(
                reasons=set(cn.log.reasons), entry=None if p is None else p.entry_price, stop=None if p is None else p.stop,
                target=None if p is None else p.target, valid_until=None if p is None else p.valid_until,
                cet=None if p is None else p.cancel_effective_time, cancel=None if p is None else p.cancel_reason,
                order_type=None if p is None else p.order_type, approval=cn.log.time,
                active=None if p is None else p.active_from, hold=None if p is None else p.max_hold_ns,
                atr=None if p is None else p.atr_at_signal))
        for x in ref:
            by_r[x["sig"]].append(x)
        assert sorted(by_p) == sorted(by_r), f"{scen}-{method}-{setting}: 신호 시각 집합이 다름"
        n_pass = 0
        for sig in by_p:
            P, Rr = sorted(by_p[sig], key=_key), sorted(by_r[sig], key=_key)
            assert len(P) == len(Rr)
            for p, r in zip(P, Rr):
                where = f"{scen}-{method}-{setting} @ {C.ns_to_iso(sig)}"
                assert p["approval"] == sig + AVAIL, where              # §12.1 판단 = 마감 + 60초
                assert p["reasons"] == r["reasons"], where
                n_pass += not p["reasons"]
                if r["warm"]:
                    continue
                if p["entry"] is None:                                   # 목표 없음(S3 SC_NO_TARGET) → 계획 없음
                    assert r["target"] is None and "SC_NO_TARGET" in r["reasons"], where
                    continue
                assert (p["entry"], p["stop"], p["target"]) == (r["entry"], r["stop"], r["target"]), where
                assert p["active"] == sig + AVAIL + 10 * MIN_NS, where          # §12.1 활성 = 판단 + 지연 L(10분)
                assert p["hold"] == 72 * R.s_dur, where                          # §12.2 신호 봉 72개
                assert p["atr"] == r["atr"], where                               # §12.2 손절 폭 검사 ATR
                if r["valid_until"] is not None:                         # 지정가: 신호 봉 마감 + N × 봉 길이
                    assert p["valid_until"] == r["valid_until"], where
                else:                                                    # L1b IOC: 활성 시각 = 판단 + 10분
                    assert p["order_type"] == "ioc_cap" and p["valid_until"] == sig + AVAIL + 10 * MIN_NS, where
                assert (p["cet"], p["cancel"]) == (r["cet"], r["cancel"]), where
        assert n_pass == sum(1 for x in ref if not x["reasons"])


# ===========================================================================
# C. 손 추적 — 원본 CSV에서 명세대로 한 줄씩 (backtest.data 안 씀)
# ===========================================================================


class _Raw:
    """원본 CSV 읽기 (open_time ms 그대로). 실행 봉 = 2023-10-01 전 5분봉 + 이후 1분봉 (§12.1)."""

    _cache: dict = {}

    @classmethod
    def bars(cls, tf: str) -> pd.DataFrame:
        if tf not in cls._cache:
            cls._cache[tf] = pd.read_csv(DATA / f"BTCUSDT_{tf}.csv.gz", usecols=range(6), float_precision="round_trip")
        return cls._cache[tf]

    @classmethod
    def exec_bars(cls, years: tuple[int, ...]) -> pd.DataFrame:
        key = ("exec", years)
        if key not in cls._cache:
            parts = []
            if min(years) <= 2023:
                f5 = cls.bars("5m")
                f5 = f5[f5.open_time < SWITCH_MS].assign(dur=M5_MS)
                parts.append(f5)
            for y in years:
                if y >= 2023:
                    f1 = pd.read_csv(DATA / f"BTCUSDT_1m_{y}.csv.gz", usecols=range(6), float_precision="round_trip")
                    parts.append(f1[f1.open_time >= SWITCH_MS].assign(dur=M1_MS))
            cls._cache[key] = pd.concat(parts, ignore_index=True).sort_values("open_time", ignore_index=True)
        return cls._cache[key]

    @classmethod
    def funding(cls) -> pd.DataFrame:
        if "funding" not in cls._cache:
            f = pd.read_csv(DATA / "BTCUSDT_fundingRate.csv.gz")
            cls._cache["funding"] = f.assign(t=(f.calc_time // H1_MS) * H1_MS)
        return cls._cache["funding"]


def _hand_exec(years, side, kind, entry, stop, target, active_ms, order_end_ms, hold_ms):
    """§12.1~12.2 체결·청산 손 계산 (한 봉씩): 진입 → 손절(닿음, 같은 봉 먼저) → 목표(관통, 다음 봉부터) → 시간."""
    x = _Raw.exec_bars(years)
    ot, dur = x.open_time.to_numpy(), x.dur.to_numpy()
    o, h, l = x.open.to_numpy(), x.high.to_numpy(), x.low.to_numpy()
    j = int(np.searchsorted(ot, active_ms))                          # 활성 시각 이후 "시작하는" 첫 봉
    fill = None
    if kind == "limit":
        while ot[j] + dur[j] <= order_end_ms:                        # 봉 전체가 주문 수명 안
            if (l[j] < entry) if side > 0 else (h[j] > entry):       # 관통해야 체결
                fill = (j, entry)
                break
            j += 1
    elif (o[j] <= entry) if side > 0 else (o[j] >= entry):           # IOC: 첫 봉 시가 ≤ 상한
        fill = (j, float(o[j]))
    if fill is None:
        return dict(filled=False, first_bar=int(ot[int(np.searchsorted(ot, active_ms))]), bar_end=int(ot[j] + dur[j]))
    je, pe = fill
    k = je
    while True:
        if k > je and ot[k] >= ot[je] + hold_ms:
            ex = (k, float(o[k]), "time")
            break
        if (l[k] <= stop) if side > 0 else (h[k] >= stop):
            px = stop
            if k > je or kind != "limit":                           # 갭이면 더 불리한 시가
                px = min(stop, o[k]) if side > 0 else max(stop, o[k])
            ex = (k, px, "stop")
            break
        if k > je and ((h[k] > target) if side > 0 else (l[k] < target)):
            ex = (k, target, "target")
            break
        k += 1
    k, px, why = ex
    er = MAKER if kind == "limit" else TAKER
    fees = er * pe + (MAKER if why == "target" else TAKER) * px
    slip = 0.0 if why == "target" else SLIP * px
    fu = _Raw.funding()
    f_lo = ot[je] if kind == "limit" else min(ot[je], active_ms)      # 시가 체결(IOC)은 활성 시각부터 (I-35)
    fsel = fu[(fu.t > f_lo) & (fu.t <= ot[k])]                       # 진입 < 펀딩 ≤ 청산
    fprice = np.array([o[int(np.searchsorted(ot, t, side="right")) - 1] for t in fsel.t])
    funding = float(np.sum(side * fsel.last_funding_rate.to_numpy() * fprice)) if len(fsel) else 0.0
    risk = abs(pe - stop) + er * pe + (TAKER + SLIP) * stop          # R 분모 = 실제 체결가 기준 (§12.2, I-29)
    r = (side * (px - pe) - fees - slip - funding) / risk
    return dict(filled=True, entry_ms=int(ot[je]), entry_px=pe, exit_ms=int(ot[k]), exit_px=px, why=why,
                n_funding=len(fsel), funding=funding, r=r)


def _hand_ind(tf: str):
    b = _Raw.bars(tf)
    o, h, l, c, v = (b[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    ot = b.open_time.to_numpy()

    def tr(j):
        return max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1]))

    def atr(t):
        return float(np.mean([tr(j) for j in range(t - 14, t)]))

    def is_sh(i):
        return all(h[i] > h[j] for j in range(i - 3, i + 4) if j != i)

    def is_sl(i):
        return all(l[i] < l[j] for j in range(i - 3, i + 4) if j != i)

    def idx(s):
        return int(np.searchsorted(ot, _ms(s)))

    return o, h, l, c, v, ot, atr, is_sh, is_sl, idx


def _product_trade(ctxs, xb_fa, scen, method, setting, plan_id, mask=True, rearm=False):
    xb, fa = xb_fa
    cfg = C.ComboConfig(scen, method, setting, apply_availability_mask=mask, l1b_rearm=rearm)
    cands = SC.generate_candidates(ctxs[setting], cfg)
    trades, logs = X.run_sequence(cands, xb, fa, cfg)
    cand = next(cn for cn in cands if cn.log.plan_id == plan_id)
    trade = next((t for t in trades if t.plan_id == plan_id), None)
    log = next(g for g in logs if g.plan_id == plan_id)
    return cand, trade, log, cands, logs


@needs_data
@pytest.mark.slow
def test_hand_l1a_stop_trade_2023_01_29(ctxs, xb_fa):
    """L1a_202301292300_1hU-202301291900 — 기준봉·마디·허리·조건·가격·취소·5분봉 체결까지 손으로 (§4, §7.1, §12)."""
    o, h, l, c, v, ot, atr, is_sh, is_sl, idx = _hand_ind("1h")
    k = b = idx("2023-01-29 19:00")                     # 기준봉 = B 봉 자신 (I-8: B 번호 ≥ 기준봉)
    tb = b + 3
    assert is_sh(b) and h[b] == 23962.7                 # §3 스윙 고점: 앞뒤 3개보다 모두 큼
    # §4.1 기준봉 조건 1~5
    body, bavg = abs(c[k] - o[k]), float(np.mean(np.abs(c[k - 20:k] - o[k - 20:k])))
    assert c[k] > o[k] and body >= 2 * bavg                             # 214.8 ≥ 112.03
    assert v[k] / np.mean(v[k - 20:k]) == pytest.approx(2.742, abs=1e-3)    # VR ≥ 2
    assert c[k] > c[k - 20] and c[k] > c[k - 60]                        # 기울기 20·60 상승
    lsh = max(i for i in range(k - 3, 3, -1) if is_sh(i))
    assert ot[lsh] == _ms("2023-01-29 11:00") and c[k] > h[lsh]         # 확정 최근 스윙 고점 23680.0 돌파
    assert (h[k] - max(o[k], c[k])) / (h[k] - l[k]) < 0.5               # 윗꼬리 0.22
    # §4.2 마디: A = 기준봉 시점 확정 최근 스윙 저점
    a = max(i for i in range(k - 3, 3, -1) if is_sl(i))
    A, B = l[a], h[b]
    W = B - A
    assert (ot[a], A, B) == (_ms("2023-01-29 08:00"), 23151.0, 23962.7) and W == pytest.approx(811.7)
    assert (c[a:tb + 1] >= A).all() and tb <= k + 60                    # 무효 아님
    vab = float(np.mean(v[a:b + 1]))
    assert vab >= np.mean(v[a - 20:a])                                  # 28151 ≥ 12101
    # §4.3 허리: 칸 11개, 최다 칸 하나(8회) → H
    lo, w = A + 0.35 * W, (A + 0.35 * W) * 0.001
    kbins = math.ceil(0.30 * W / w - 1e-9)
    cnt = np.zeros(kbins, int)
    for j in range(a, b + 1):
        for x in (o[j], h[j], l[j], c[j]):
            if lo <= x <= A + 0.65 * W:
                cnt[min(int((x - lo) / w), kbins - 1)] += 1
    assert kbins == 11 and cnt.max() == 8 and list(np.flatnonzero(cnt == 8)) == [4]
    H = _rnd(lo + 4.5 * w)
    assert H == 23540.6
    # §7.1 추가 조건·가격·리스크
    assert c[tb] > H and c[tb] >= c[tb - 60] and np.mean(v[b + 1:tb + 1]) < vab
    at = atr(tb)
    stop, target = _rnd(A - 0.1 * at), _rnd(H + W)
    assert (stop, target) == (23130.5, 24352.3)
    assert max(0.004 * H, at) <= H - stop <= min(0.02 * H, 3 * at)
    assert (target - H - MAKER * H - MAKER * target) / (H - stop + MAKER * H + 0.0007 * stop) == pytest.approx(1.8611, abs=1e-4)
    # 취소: 첫 종가 < A = 2023-01-30 11:00 봉 → 효력 12:01
    kc = next(kk for kk in range(tb + 1, tb + 25) if c[kk] < A or h[kk] > B + 0.5 * W or np.mean(v[b + 1:kk + 1]) >= vab)
    assert ot[kc] == _ms("2023-01-30 11:00") and c[kc] < A
    cet_ms = int(ot[kc]) + H1_MS + 60_000
    # §12.1 체결: 활성 23:11 → 5분봉 23:15부터, 08:25 봉 저가 23529.0 < H → 체결, 09:35 봉 손절 (시가 위 → 손절가)
    got = _hand_exec((2023,), 1, "limit", H, stop, target, _ms("2023-01-29 23:11"),
                     min(_ms("2023-01-30 23:00"), cet_ms), 72 * H1_MS)
    assert got["filled"] and got["entry_ms"] == _ms("2023-01-30 08:25") and got["exit_ms"] == _ms("2023-01-30 09:35")
    assert got["why"] == "stop" and got["exit_px"] == 23130.5 and got["n_funding"] == 0
    assert got["r"] == pytest.approx(-1.0, abs=1e-9)                    # 펀딩 없는 손절 = 정확히 −1R
    # 제품과 대조
    cand, trade, log, _, _ = _product_trade(ctxs, xb_fa, "L1a", "DA", "P1", "L1a_202301292300_1hU-202301291900")
    p = cand.plan
    assert cand.log.reasons == () and (p.entry_price, p.stop, p.target) == (H, stop, target)
    assert p.cancel_effective_time == cet_ms * MS and p.cancel_reason == "close_below"
    assert p.valid_until == _ms("2023-01-30 23:00") * MS and p.active_from == _ms("2023-01-29 23:11") * MS
    assert trade.entry_time == got["entry_ms"] * MS and trade.exit_time == got["exit_ms"] * MS
    assert trade.r_multiple == pytest.approx(got["r"], abs=1e-9)


@needs_data
@pytest.mark.slow
def test_hand_l1a_cancel_unhealthy_2024_07_29(ctxs, xb_fa):
    """L1a_202407291000 — 대기 중 건강한 조정 위반(§12.1)이 13:00 봉 마감에 성립 → 14:01부터 취소, 그 전 미체결."""
    o, h, l, c, v, ot, atr, is_sh, is_sl, idx = _hand_ind("1h")
    b = idx("2024-07-29 06:00")
    tb = b + 3
    a = max(i for i in range(b - 80, b) if is_sl(i) and l[i] == 67771.6)
    vab = float(np.mean(v[a:b + 1]))
    kc = next(kk for kk in range(tb + 1, tb + 25) if np.mean(v[b + 1:kk + 1]) >= vab)
    assert ot[kc] == _ms("2024-07-29 13:00")
    assert all(c[kk] >= 67771.6 and h[kk] <= 69872.6 + 0.5 * 2101.0 for kk in range(tb + 1, kc + 1))
    got = _hand_exec((2024,), 1, "limit", 68541.2, 67728.6, 70642.2, _ms("2024-07-29 10:11"),
                     _ms("2024-07-29 14:01"), 72 * H1_MS)
    assert not got["filled"]
    cand, trade, _, _, _ = _product_trade(ctxs, xb_fa, "L1a", "DA", "P1", "L1a_202407291000_1hU-202407290600")
    assert cand.plan.cancel_reason == "unhealthy_volume"
    assert cand.plan.cancel_effective_time == _ms("2024-07-29 14:01") * MS
    assert trade.status == "cancelled" and trade.busy_until == _ms("2024-07-29 14:01") * MS


@needs_data
@pytest.mark.slow
def test_hand_l1b_one_setup_per_madi_2020_10_19(ctxs, xb_fa):
    """L1b 마디 1hU-202010191600 — 준비·확인·최저가·k_last·IOC 체결·목표·펀딩을 손으로 (§7.2, §12.1~12.2).

    §7.2대로 마디당 준비는 한 번: 준비 20:00 봉 → 확인 C 21:45 → 신호 22:00(KST 07:01 승인 → 실행 가능 모드에서 방해 금지).
    이 마디의 L1b는 그걸로 끝이다(검토 SPEC-L1B-REARM 수정). 수정 전 해석(I-22 재준비)에서는 한 봉 뒤 다시 준비된
    00:00 신호가 거래가 됐다 — 그 거래는 이제 진단(l1b_rearm=True)에만 있다. R 분모는 실제 체결가 기준(검토 F1 수정).
    """
    o, h, l, c, v, ot, atr, is_sh, is_sl, idx = _hand_ind("1h")
    cb = _Raw.bars("15m")
    co, ch, cl, cc, cot = (cb[k].to_numpy() for k in ("open", "high", "low", "close", "open_time"))
    b = idx("2020-10-19 16:00")
    tb = b + 3
    A, B = 11404.01, 11830.0
    W, H = B - A, 11639.8
    a = idx("2020-10-19 03:00")
    assert is_sh(b) and h[b] == B and is_sl(a) and l[a] == A
    vab = float(np.mean(v[a:b + 1]))
    # 준비(유일): 20:00 봉(저가 11658.01 ∈ [H, H+0.25W]) → 확인 C 21:45 → 신호 22:00
    arm1 = idx("2020-10-19 20:00")
    assert arm1 == tb + 1 and H <= l[arm1] <= H + 0.25 * W
    c1 = int(np.searchsorted(cot, _ms("2020-10-19 21:45")))
    assert cc[c1] > co[c1] and cc[c1] > ch[c1 - 1] and cc[c1] > H
    assert all(not (cc[j] > co[j] and cc[j] > ch[j - 1] and cc[j] > H) for j in range(c1 - 3, c1))  # 21:00~21:30 불확인
    kl1 = idx("2020-10-19 21:00")                             # 확인 시각(22:00)에 마감된 마지막 S 봉
    lowest1 = float(cl[int(np.searchsorted(cot, int(ot[tb]) + H1_MS)):c1 + 1].min())
    assert lowest1 == 11658.01
    at1 = atr(kl1)
    entry1, stop1, target1 = _rnd(cc[c1] * 1.001), _rnd(min(lowest1, H) - 0.1 * at1), _rnd(lowest1 + W)
    assert (entry1, stop1, target1) == (11753.3, 11632.4, 12084.0)
    assert np.mean(v[b + 1:kl1 + 1]) < vab                         # 건강한 조정
    assert max(0.004 * entry1, at1) <= entry1 - stop1 <= min(0.02 * entry1, 3 * at1)
    got1 = _hand_exec((2020,), 1, "ioc", entry1, stop1, target1, _ms("2020-10-19 22:11"), _ms("2020-10-19 22:11"),
                      72 * H1_MS)
    assert got1["filled"] and got1["entry_ms"] == _ms("2020-10-19 22:15") and got1["entry_px"] == 11728.14
    assert got1["why"] == "target" and got1["exit_ms"] == _ms("2020-10-21 02:50") and got1["n_funding"] == 4
    # R = (355.86 − 8.28087 − 3.06623) ÷ (95.74 + 5.86407 + 8.14268) — 분모는 실제 체결가 11728.14 기준
    assert got1["r"] == pytest.approx(3.139163, abs=1e-6)
    # 제품(기본): 이 마디의 L1b 후보는 22:00 하나뿐. 실행 가능 모드 = 방해 금지, 전체 모드 = 위 손 계산 거래
    _, _, log, cands, _ = _product_trade(ctxs, xb_fa, "L1b", "DA", "P1", "L1b_202010192200_1hU-202010191600")
    assert [cn.log.plan_id for cn in cands if cn.log.madi_id == "1hU-202010191600"] == [
        "L1b_202010192200_1hU-202010191600"]
    assert log.reasons == ("MASK_DND",)
    cand, trade, _, _, _ = _product_trade(ctxs, xb_fa, "L1b", "DA", "P1", "L1b_202010192200_1hU-202010191600",
                                          mask=False)
    assert (cand.plan.entry_price, cand.plan.stop, cand.plan.target) == (entry1, stop1, target1)
    assert trade.entry_price == 11728.14 and trade.exit_reason == "target"
    assert trade.r_multiple == pytest.approx(got1["r"], abs=1e-9)
    # 진단(l1b_rearm=True, 수정 전 해석): 재준비 22:00 봉 → 확인 C 23:45 → 신호 00:00이 실행 가능 거래가 된다
    arm2 = idx("2020-10-19 22:00")
    assert H <= l[arm2] <= H + 0.25 * W
    c2 = int(np.searchsorted(cot, _ms("2020-10-19 23:45")))
    assert cc[c2] > co[c2] and cc[c2] > ch[c2 - 1] and cc[c2] > H
    kl = idx("2020-10-19 23:00")
    lowest = float(cl[int(np.searchsorted(cot, int(ot[tb]) + H1_MS)):c2 + 1].min())
    at = atr(kl)
    entry, stop, target = _rnd(cc[c2] * 1.001), _rnd(min(lowest, H) - 0.1 * at), _rnd(lowest + W)
    assert (entry, stop, target) == (11756.7, 11631.9, 12084.0)
    got = _hand_exec((2020,), 1, "ioc", entry, stop, target, _ms("2020-10-20 00:11"), _ms("2020-10-20 00:11"), 72 * H1_MS)
    assert got["filled"] and got["entry_ms"] == _ms("2020-10-20 00:15") and got["entry_px"] == 11719.22
    assert got["why"] == "target" and got["exit_ms"] == _ms("2020-10-21 02:50") and got["n_funding"] == 3
    # 실제 체결가 기준 분모 101.32194 → 3.49985 (수정 전 상한가 기준 분모 138.82068이면 2.55446)
    assert got["r"] == pytest.approx(3.499853, abs=1e-6)
    cand, trade, _, _, logs = _product_trade(ctxs, xb_fa, "L1b", "DA", "P1", "L1b_202010200000_1hU-202010191600",
                                             rearm=True)
    assert (cand.plan.entry_price, cand.plan.stop, cand.plan.target) == (entry, stop, target)
    assert trade.entry_price == 11719.22 and trade.exit_reason == "target"
    assert trade.r_multiple == pytest.approx(got["r"], abs=1e-9)
    first = next(g for g in logs if g.plan_id == "L1b_202010192200_1hU-202010191600")
    assert first.reasons == ("MASK_DND",)


@needs_data
@pytest.mark.slow
def test_hand_l1b_ioc_not_filled_2020_06_02(ctxs, xb_fa):
    """L1b_202006020800 — 활성 08:11 뒤 첫 실행 봉(5분봉 08:15) 시가 10140.41 > 상한 10136.4 → 미체결(§12.1 IOC).

    이 신호는 마디 1hU-202006012300의 재준비 에피소드라 진단(l1b_rearm=True)에만 있다. 기본(마디당 준비 1회)에서는
    그 마디의 첫 준비 확인(05:30)이 F5로 폐기되고 끝난다.
    """
    got = _hand_exec((2020,), 1, "ioc", 10136.4, 9980.2, 11067.4, _ms("2020-06-02 08:11"), _ms("2020-06-02 08:11"),
                     72 * H1_MS)
    assert not got["filled"] and got["first_bar"] == _ms("2020-06-02 08:15")
    _, trade, _, _, _ = _product_trade(ctxs, xb_fa, "L1b", "DA", "P1", "L1b_202006020800_1hU-202006012300", rearm=True)
    assert trade.status == "not_filled" and trade.busy_until == _ms("2020-06-02 08:20") * MS
    base = SC.generate_candidates(ctxs["P1"], C.ComboConfig("L1b", "DA", "P1"))
    assert [(cn.log.plan_id, cn.log.reasons) for cn in base if cn.log.madi_id == "1hU-202006012300"] == [
        ("L1b_202006020530_1hU-202006012300", ("F5",))]


@needs_data
@pytest.mark.slow
def test_hand_s2_target_trade_2024_08_30(ctxs, xb_fa):
    """S2_202408301500 — 살아 있는 상승 마디에서 VR 3.455 음봉 종가 < H → 지정가 매도 @ H, 1분봉 체결·목표·펀딩 4회 (§7.3)."""
    o, h, l, c, v, ot, atr, is_sh, is_sl, idx = _hand_ind("1h")
    b = idx("2024-08-20 05:00")
    tb = b + 3
    A, B, H = 57750.0, 61386.0, 59229.2
    x = idx("2024-08-30 14:00")
    assert is_sh(b) and h[b] == B
    assert 1 <= x - tb <= 300 and (c[tb + 1:x + 1] >= A).all()              # 확정 후 살아 있음(246봉째)
    assert c[x] < o[x] and v[x] / np.mean(v[x - 20:x]) == pytest.approx(3.455, abs=1e-3) and c[x] < H
    at = atr(x)
    stop = _rnd(max(h[x], H + 0.5 * at) + 0.1 * at)
    assert stop == 59858.2                                                   # max(59820.0, 59420.26) + 38.21
    assert max(0.004 * H, at) <= stop - H <= min(0.02 * H, 3 * at)
    got = _hand_exec((2024,), -1, "limit", H, stop, A, _ms("2024-08-30 15:11"), _ms("2024-08-31 03:00"), 72 * H1_MS)
    assert got["filled"] and got["entry_ms"] == _ms("2024-08-30 18:38")
    assert got["why"] == "target" and got["exit_ms"] == _ms("2024-09-01 05:39") and got["n_funding"] == 4
    assert got["funding"] < 0                                                # 숏은 양수 비율 펀딩을 받는다
    assert got["r"] == pytest.approx(2.140691, abs=1e-6)
    cand, trade, _, _, _ = _product_trade(ctxs, xb_fa, "S2", "DA", "P1", "S2_202408301500_1hU-202408200500")
    assert cand.log.reasons == () and (cand.plan.entry_price, cand.plan.stop, cand.plan.target) == (H, stop, A)
    assert trade.r_multiple == pytest.approx(got["r"], abs=1e-9)


@needs_data
@pytest.mark.slow
def test_hand_s3_target_is_a_swing_low_from_1_7_years_ago(ctxs):
    """S3_202602240200 — 지지선·이탈·목표를 손으로 (§7.4, I-25). 목표가 S보다 10.8 아래인 2024-06-22 스윙 저점이라
    순손익비 −0.023 → RISK_RR. (지지선의 '두 번째 터치'도 스윙 봉 바로 옆 봉이다.)"""
    o, h, l, c, v, ot, atr, is_sh, is_sl, idx = _hand_ind("1h")
    i, t = idx("2026-02-23 01:00"), idx("2026-02-24 01:00")
    S = l[i]
    assert S == 64232.8 and is_sl(i) and i + 3 <= t
    touches = [int(ot[j]) for j in range(t - 100, t) if abs(l[j] - S) <= 0.001 * S]
    assert touches == [_ms("2026-02-23 01:00"), _ms("2026-02-23 02:00")]    # 스윙 봉 + 바로 다음 봉
    assert c[t] < S and v[t] / np.mean(v[t - 20:t]) >= 2 and int(np.sum(c[t - 9:t] < S)) == 0
    below = [j for j in range(3, t - 2) if is_sl(j) and l[j] < S]
    tgt = max(below, key=lambda j: l[j])
    assert ot[tgt] == _ms("2024-06-22 15:00") and l[tgt] == 64222.0 and t - tgt == 14674
    stop = _rnd(S + atr(t))
    rr = (S - l[tgt] - MAKER * S - MAKER * l[tgt]) / (stop - S + MAKER * S + 0.0007 * stop)
    assert rr == pytest.approx(-0.0233, abs=1e-3)
    recent = [j for j in below if j >= t - 100 and l[j] < S * (1 - 0.001)]
    assert l[max(recent, key=lambda j: l[j])] == 63860.0                     # 최근 100봉·±0.1% 밖이면 63860.0
    cand = next(cn for cn in SC.generate_candidates(ctxs["P1"], C.ComboConfig("S3", "DB", "P1"))
                if cn.log.plan_id == "S3_202602240200_sup53881")
    assert cand.log.reasons == ("RISK_RR",) and cand.plan.target == 64222.0


# ===========================================================================
# D. G1 판정 7개 기준 (§8.3) — 경계값과 부등호 방향
# ===========================================================================


def _summary(**kw) -> dict:
    base = dict(mean_r=0.2, boot_lo=0.01, pf=1.5, positive_years=5, n=40)
    base.update(kw)
    return base


def test_g1_all_pass_and_each_boundary():
    ok = M.g1_verdict(_summary(), 0.05, 0.1)
    assert ok["result"] == "pass" and all(ok[k] for k in M.VERDICT_KEYS[:7])
    cases = [                                                   # (요약 변경, 비용 2배, 무작위 p95, 걸리는 조건, 결과)
        (dict(mean_r=0.15), 0.05, 0.1, None, "pass"),           # ① ≥ 0.15 (같으면 통과)
        (dict(mean_r=0.1499999), 0.05, 0.1, "c1_mean_r", "fail"),
        (dict(boot_lo=0.0), 0.05, 0.1, "c2_boot_lo", "fail"),   # ② 하한 > 0 (0이면 실패)
        (dict(pf=1.2), 0.05, 0.1, None, "pass"),                # ③ ≥ 1.2
        (dict(pf=1.1999), 0.05, 0.1, "c3_pf", "fail"),
        ({}, 0.0, 0.1, "c4_cost2", "fail"),                     # ④ 비용 2배 평균 > 0 (0이면 실패)
        ({}, 0.05, 0.2, "c5_random", "fail"),                   # ⑤ 무작위 95% 분위보다 "높음" (같으면 실패)
        ({}, 0.05, 0.19999, None, "pass"),
        (dict(positive_years=4), 0.05, 0.1, None, "pass"),      # ⑥ 7개 연도 중 4개 이상
        (dict(positive_years=3), 0.05, 0.1, "c6_years", "fail"),
        (dict(n=30), 0.05, 0.1, None, "pass"),                  # ⑦ 30건 미만이면 보류
        (dict(n=29), 0.05, 0.1, "c7_enough_trades", "pending"),
        (dict(n=29, mean_r=-1.0), 0.05, 0.1, "c7_enough_trades", "pending"),   # 보류가 불합격보다 먼저
    ]
    for change, cost2, p95, bad, result in cases:
        v = M.g1_verdict(_summary(**change), cost2, p95)
        assert v["result"] == result, (change, cost2, p95)
        if bad:
            assert v[bad] is False
    assert M.g1_verdict(_summary(), None, 0.1)["c4_cost2"] is False      # 값 없음 = 실패 (무작위 미실시 등)
    assert M.g1_verdict(_summary(), 0.05, None)["c5_random"] is False


def test_g1_positive_years_counts_only_strictly_positive():
    """§8.3-6: 거래 없는 해(None)·평균 0인 해는 양수가 아니다. 연도 = 진입 시각 UTC 연도."""
    yearly = M.yearly_mean_r(np.array([0.5, -0.2, 0.0, 1.0]), np.array([2020, 2021, 2022, 2026]))
    assert yearly == {2020: 0.5, 2021: -0.2, 2022: 0.0, 2023: None, 2024: None, 2025: None, 2026: 1.0}
    assert M.positive_year_count(yearly) == 2
    assert list(M.utc_year(np.array([C.ts_ns("2023-12-31 23:59"), C.ts_ns("2024-01-01 00:00")]))) == [2023, 2024]


def test_g1_bootstrap_lower_is_2_5pct_quantile_of_means():
    """§12.4: 복원 추출 10,000회 평균의 2.5% 분위 = 하한 (같은 시드 → 같은 값)."""
    r = np.array([1.0, -1.0, 2.0, -1.0, 0.5, -0.5, 3.0, -1.0])
    rng = np.random.default_rng(7)
    means = r[rng.integers(0, r.size, size=(10_000, r.size))].mean(axis=1)
    lo, hi = M.bootstrap_mean_ci(r, rng=np.random.default_rng(7))
    assert lo == pytest.approx(np.quantile(means, 0.025)) and hi == pytest.approx(np.quantile(means, 0.975))
    assert M.profit_factor(np.array([1.0, -0.5, 2.0])) == pytest.approx(6.0)   # PF = 이익 합 ÷ 손실 합 (R)


# ===========================================================================
# E. 명세 해석 쟁점 — 숫자로 고정한 기록 + 명세 문장과 다른 해석(xfail strict)
# ===========================================================================


def _l1b_first_arm(ctx) -> dict:
    """마디마다 T_B 뒤 처음으로 저가가 [H, H+0.25W]에 들어온 S 봉(= 명세 §7.2 '준비'가 처음 성립한 봉)."""
    md, low = ctx.s_struct.madis, ctx.s_bars["low"].to_numpy()
    out = {}
    for r in np.flatnonzero(md.direction.to_numpy() == 1):
        tb, end, H, W = int(md.tb_idx[r]), int(md.end_idx[r]), float(md.h_cluster[r]), float(md.w[r])
        seg = low[tb + 1:min(end, len(low) - 1) + 1]
        z = np.flatnonzero((seg >= H) & (seg <= H + 0.25 * W))
        if z.size:
            out[str(md.madi_id[r])] = tb + 1 + int(z[0])
    return out


@needs_data
@pytest.mark.slow
def test_finding_l1b_rearm_makes_most_of_the_l1b_sample(ctxs, xb_fa):
    """쟁점 → 수정됨: 옛 I-22 '에피소드가 끝나면(확인·폐기·창 끝) 같은 마디에서 다시 준비 가능'은 명세 §7.2에 없는 규칙이다.

    §7.2는 준비(ARMED) 하나와 '폐기'만 적고, 근거 문서 STRATEGY P13·§5.1 L1은 '같은 가격은 첫 터치만'이다.
    수정: 기본 = 마디당 첫 준비 에피소드 하나(= 수정 전 후보 중 첫 준비에서 나온 것과 같다). 수정 전 동작은 진단
    (l1b_rearm=True)으로만 남아 수정 전 숫자를 그대로 낸다: 실행 가능 체결 43건 중 34건이 재준비, 첫 준비만 쓰면 9건
    (n < 30 → 판정 보류). (거래 수만 본다. 평균 R은 보지 않는다.)
    """
    xb, fa = xb_fa
    ctx = ctxs["P1"]
    first_arm = _l1b_first_arm(ctx)
    got = {}
    for method in ("DA", "DB"):
        cfg = C.ComboConfig("L1b", method, "P1")
        cands = SC.generate_candidates(ctx, cfg)
        diag_cfg = cfg.replace(l1b_rearm=True)
        diag = SC.generate_candidates(ctx, diag_cfg)
        first = [cn for cn in diag if first_arm.get(cn.log.madi_id) == cn.log.meta["arm_idx"]]
        assert [cn.log.meta["cand_id"] for cn in cands] == [cn.log.meta["cand_id"] for cn in first]   # 기본 = 첫 준비
        assert [cn.log.reasons for cn in cands] == [cn.log.reasons for cn in first]
        tr_base, _ = X.run_sequence(cands, xb, fa, cfg)
        tr_diag, _ = X.run_sequence(diag, xb, fa, diag_cfg)
        arm_of = {cn.log.plan_id: cn.log.meta["arm_idx"] for cn in diag}
        per_madi = collections.Counter(cn.log.madi_id for cn in diag)
        got[method] = dict(cands=len(cands), passed=sum(not cn.log.reasons for cn in cands),
                           filled=sum(t.status == "filled" for t in tr_base),
                           diag_cands=len(diag), diag_madis=len(per_madi), diag_max_per_madi=max(per_madi.values()),
                           diag_passed=sum(not cn.log.reasons for cn in diag),
                           diag_filled=sum(t.status == "filled" for t in tr_diag),
                           diag_filled_from_rearm=sum(t.status == "filled" and arm_of[t.plan_id] != first_arm[t.madi_id]
                                                      for t in tr_diag))
    # 기본(수정 후): 실행 가능 체결 9건(DA)·8건(DB) → n < 30. 진단(수정 전): 43건 중 34건이 재준비
    assert got["DA"] == dict(cands=434, passed=15, filled=9, diag_cands=7132, diag_madis=444, diag_max_per_madi=86,
                             diag_passed=144, diag_filled=43, diag_filled_from_rearm=34)
    assert got["DB"] == dict(cands=434, passed=13, filled=8, diag_cands=7132, diag_madis=444, diag_max_per_madi=86,
                             diag_passed=143, diag_filled=36, diag_filled_from_rearm=28)
    # 한 마디(1hU-202010191600)가 8시간 동안 통과 신호 7개를 내던 것(진단) → 기본은 1개
    diag_one = [cn for cn in SC.generate_candidates(ctx, C.ComboConfig("L1b", "DA", "P1", l1b_rearm=True))
                if cn.log.madi_id == "1hU-202010191600"]
    passed = [cn.log.signal_time for cn in diag_one if not cn.log.reasons]
    assert len(diag_one) == 12 and len(passed) == 7 and passed[-1] - passed[0] == int(7.5 * 3600) * SEC_NS
    one = [cn for cn in SC.generate_candidates(ctx, C.ComboConfig("L1b", "DA", "P1"))
           if cn.log.madi_id == "1hU-202010191600"]
    assert len(one) == 1 and one[0].log.reasons == ()


@needs_data
@pytest.mark.slow
def test_spec_l1b_one_setup_per_madi(ctxs):
    """명세 문장 기준: 한 마디에서 나오는 L1b 확인(신호 후보)은 많아야 1개.
    (검토 xfail 테스트 — 마디당 준비 1회로 고친 뒤 통과하므로 표시를 지웠다. P2도 같이 본다.)"""
    for setting in ("P1", "P2"):
        cands = SC.generate_candidates(ctxs[setting], C.ComboConfig("L1b", "DA", setting))
        per_madi = collections.Counter(cn.log.madi_id for cn in cands)
        assert max(per_madi.values()) <= 1, setting


@needs_data
@pytest.mark.slow
def test_finding_s3_target_rule_leaves_no_testable_signal(ctxs):
    """쟁점: §7.4 목표 'S 아래 가장 가까운 확정 스윙 저점'을 I-25는 기간 제한 없이(전체 이력) 찾는다.

    BTC 6.7년 이력의 수천 개 스윙 저점 중 S 바로 밑 것이 거의 항상 있어 목표가 S와 붙는다 → 순손익비 1.5 불가
    → S3 4조합 통과 0건(제품 보고서는 '명세 그대로'라고 적지만 기간 무제한은 I-25의 선택이다).
    P1 목표의 68%는 S의 ±0.1% 터치 범위(§7.4가 'S에 닿음'으로 보는 범위) 안이고, 목표 스윙의 중앙 나이는 883봉(37일)이다.
    또 후보의 69%는 직전 종가가 이미 S 아래인 봉(새 이탈이 아닌 계속 하락)이다.
    """
    ctx = ctxs["P1"]
    low, close = ctx.s_bars["low"].to_numpy(), ctx.s_bars["close"].to_numpy()
    for method in ("DA", "DB"):
        for setting in ("P1", "P2"):
            cands = SC.generate_candidates(ctxs[setting], C.ComboConfig("S3", method, setting))
            assert sum(not cn.log.reasons for cn in cands) == 0
    cands = SC.generate_candidates(ctx, C.ComboConfig("S3", "DA", "P1"))
    with_t = [cn for cn in cands if "target_idx" in cn.log.meta]
    in_band = np.mean([(cn.log.meta["S"] - low[cn.log.meta["target_idx"]]) <= 0.001 * cn.log.meta["S"] for cn in with_t])
    ages = np.array([cn.log.meta["s_idx"] - cn.log.meta["target_idx"] for cn in with_t])
    rr = np.array([cn.log.meta["net_rr"] for cn in with_t if "net_rr" in cn.log.meta])   # 워밍업 후보는 계획 없음
    assert len(cands) == 3412 and len(with_t) == 3407
    assert in_band == pytest.approx(0.681, abs=0.001) and int(np.median(ages)) == 883
    assert int(np.sum(rr >= 1.5)) == 35 and float(np.median(rr)) < 0.02
    cont = sum(1 for cn in cands if close[cn.log.meta["s_idx"] - 1] < cn.log.meta["S"])
    assert cont == 2366


@needs_data
@pytest.mark.slow
def test_finding_availability_mask_uses_approval_time_not_signal_time(ctxs, xb_fa):
    """§12.3은 '승인 시각(L1a·S2·S3는 신호 시각, L1b는 확인 시각)'이고 코드는 신호 시각 + 60초를 쓴다.
    봉 마감이 15분 격자라 방해 금지·하루 경계 판정이 같다(A의 경계 테스트) → 실행 가능 결과 차이 없음."""
    xb, fa = xb_fa
    for scen in ("L1a", "L1b", "S2"):
        cfg = C.ComboConfig(scen, "DA", "P1")
        cands = SC.generate_candidates(ctxs["P1"], cfg)
        _, logs = X.run_sequence(cands, xb, fa, cfg)
        for g in logs:
            if "MASK_DND" in g.reasons:
                assert C.in_dnd(g.signal_time) and C.in_dnd(g.time)


@needs_data
@pytest.mark.slow
def test_finding_s3_stop_at_band_edge_is_decided_by_rounding(ctxs):
    """쟁점: §7.4 손절 S + ATR은 §8.1 손절 폭 하한(1 × ATR)과 정확히 같다. §7의 0.1 USDT 반올림이 아래로 가면
    d < ATR(차이 < 0.05)이 되어 RISK_STOP_BAND로 폐기된다 → ATR이 [0.4%, 2%]인 P1 S3 후보 2,802개 중 1,290개(46%)가
    반올림 방향만으로 탈락(동전 던지기). 지금은 S3 목표 문제로 통과 0건이라 판정 영향은 없다."""
    ctx = ctxs["P1"]
    atr = ctx.s_ind["atr"].to_numpy()
    n_edge = n_round = 0
    for cn in SC.generate_candidates(ctx, C.ComboConfig("S3", "DA", "P1")):
        if cn.plan is None:
            continue
        a, e, s = atr[cn.log.meta["s_idx"]], cn.plan.entry_price, cn.plan.stop
        if 0.004 * e <= a <= 0.02 * e:
            n_edge += 1
            if "RISK_STOP_BAND" in cn.log.reasons and 0 < a - (s - e) < 0.05 + 1e-9:
                n_round += 1
                assert s == _rnd(cn.log.meta["S"] + a)             # 손절은 명세대로 round(S + ATR) (S는 원값)
    assert (n_edge, n_round) == (2802, 1290)
