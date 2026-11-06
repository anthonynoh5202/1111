"""A2 진입 조건 S1·S2·S3 신호 생성 (결정적, 미래 정보 없음).

숏은 가격을 뒤집은 공간(o'=−o, h'=−l, l'=−h, c'=−c)에서 롱과 똑같은 논리를 돌린 뒤 가격을 되돌린다
→ 롱·숏 정의가 정확히 대칭이다.

신호 = 1H 봉 j 마감에 "진입" 판단. 진입은 j+1 봉 시가(체결 엔진).
변형(설정당 4개): 손절 {구조, 절대} × 목표 {2R, 구조}
  V1 구조 손절 + 2R   V2 구조 손절 + 구조 목표   V3 절대 손절 + 2R   V4 절대 손절 + 구조 목표
  구조 목표는 (목표 − 신호 봉 종가) ≥ 1 × (신호 봉 종가 − 손절)일 때만 신호 [CP-18-2][CP-25-3], 아니면 버림.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

S1_WINDOW = 24       # 돌파 후 24봉(1일) 안에 첫 눌림 + 돌려 세움이 나와야 함 [CP-12-4 안 주면 보낸다]
S2_ARM_WINDOW = 48   # 허리 구간 첫 터치 뒤 48봉(2일) 안에 반등 양봉
S2_ZONE_W = 0.25     # 허리 위 지지 구간 [H, H + 0.25W]
BUF_ATR = 0.1        # 손절 여유 b = 0.1 × ATR(1H)
MIN_RR_STRUCT = 1.0  # 구조 목표 최소 손익비


def _space(mk, side):
    if side > 0:
        return mk.o1, mk.h1, mk.l1, mk.c1
    return -mk.o1, -mk.l1, -mk.h1, -mk.c1


def _variants(rows: list[dict], side: int) -> pd.DataFrame:
    """rows(뒤집힌 공간 값) → 변형별 손절·목표(원래 가격). 구조 목표는 손익비 검사."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = []
    for v, (stop_col, tgt) in {"V1": ("stop_struct", "2R"), "V2": ("stop_struct", "struct"),
                               "V3": ("stop_abs", "2R"), "V4": ("stop_abs", "struct")}.items():
        d = df.copy()
        d["variant"] = v
        st = d[stop_col].to_numpy()
        risk = d["c_sig"].to_numpy() - st
        ok = risk > 0
        if tgt == "struct":
            ok &= (d["tgt_struct"].to_numpy() - d["c_sig"].to_numpy()) >= MIN_RR_STRUCT * risk
            d["target"] = side * d["tgt_struct"]
        else:
            d["target"] = np.nan
        d["stop"] = side * st
        d = d[ok]
        out.append(d)
    res = pd.concat(out, ignore_index=True)
    res["side"] = side
    return res


# ---------------------------------------------------------------------------
# S1 돌파(이탈) 후 첫 눌림(되돌림) [CP-10-2][CP-12-4][CP-01-1][CP-04][CP-15-2][CP-11-4]
# ---------------------------------------------------------------------------

def s1_signals(mk, side: int, level: str = "full") -> tuple[pd.DataFrame, dict]:
    o, h, l, c = _space(mk, side)
    v, atr, vr = mk.v1, mk.atr1, mk.vr1
    ind = mk.ind1
    long_bar = ind["long_bar"].to_numpy()
    wick = ind["upper_wick"].to_numpy() if side > 0 else ind["lower_wick"].to_numpy()
    last = mk.last_sh1 if side > 0 else mk.last_sl1
    n = mk.n1
    lvl = np.where(last >= 0, h[np.clip(last, 0, None)], np.nan)   # 확정 스윙 고점(숏: 저점)
    prev_c = np.r_[np.nan, c[:-1]]
    with np.errstate(invalid="ignore"):
        cand = (mk.valid1 & (c > o) & long_bar & (vr >= 2.0) & (last >= 0) & (c > lvl) & (prev_c <= lvl)
                & (wick < 0.5) & ~mk.spread1)
    regime = mk.regime_mask("DB_L" if side > 0 else "DB_S", level)
    stats = {"breakouts": int(cand.sum()), "no_pullback": 0, "failed": 0, "expired": 0,
             "vol_fail": 0, "regime_fail": 0}
    rows = []
    seen_j = set()
    for x in np.flatnonzero(cand):
        L = lvl[x]
        pb = -1
        HH = h[x]
        trig = -1
        end = min(x + 1 + S1_WINDOW, n - 1)
        status = "expired"
        for j in range(x + 1, end):
            if c[j] < L:                         # 종가가 돌파 레벨 아래로 → 돌파 실패 [CP-17-8]
                status = "failed"
                break
            if pb < 0:
                HH = max(HH, h[j])
                if c[j] < o[j]:                  # 첫 음봉 = 눌림 시작
                    pb = j
                continue
            if c[j] > o[j] and c[j] > h[j - 1]:  # 양봉 + 직전 봉 고가 위 종가 = 돌려 세움 [CP-11-3]
                trig = j
                break
        if trig < 0:
            if pb < 0 and status == "expired":
                stats["no_pullback"] += 1
            else:
                stats[status] += 1
            continue
        j = trig
        vol_pb = v[pb:j].mean()
        vol_imp = v[x:pb].mean()
        if not vol_pb < vol_imp:                 # 눌림 중 거래 감소 [CP-01-3][CP-11-1]
            stats["vol_fail"] += 1
            continue
        if not regime[j]:
            stats["regime_fail"] += 1
            continue
        if j in seen_j:
            continue
        seen_j.add(j)
        PL = l[pb:j + 1].min()
        b = BUF_ATR * atr[j]
        rows.append({"j": j, "x": x, "pb": pb, "level": side * L, "c_sig": c[j],
                     "stop_struct": PL - b,                    # 되돌림 저점 아래
                     "stop_abs": min(PL, l[x]) - b,            # 돌파 양봉 아래 [CP-12-7]
                     "tgt_struct": HH,                         # 직전 고점 [CP-11-4][CP-18-1]
                     "atr": atr[j]})
    stats["signals"] = len(rows)
    return _variants(rows, side), stats


# ---------------------------------------------------------------------------
# S2 마디 허리 위 눌림 확인 [CP-11][CP-06-1][CP-05-3][CP-08-10][CP-09-7]
# ---------------------------------------------------------------------------

def s2_signals(mk, side: int, level: str = "full") -> tuple[pd.DataFrame, dict]:
    o, h, l, c = _space(mk, side)
    atr = mk.atr1
    md = mk.madis4
    alive4 = mk.st4.alive_up if side > 0 else mk.st4.alive_dn
    regime = mk.regime_mask("DADB_L" if side > 0 else "DADB_S", level)
    c4 = mk.c4 if side > 0 else -mk.c4
    v4 = mk.v4
    n = mk.n1
    stats = {"madis": 0, "never_touched": 0, "cancel_2close": 0, "expired": 0, "vol_fail": 0,
             "regime_fail": 0, "below_waist": 0}
    rows = []
    for m in np.flatnonzero(md["direction"].to_numpy() == side):
        r = md.iloc[m]
        stats["madis"] += 1
        A, B, H, W = side * r.a_price, side * r.b_price, side * r.h_cluster, r.w
        b_idx, end_idx = int(r.b_idx), int(r.end_idx)
        j0 = int(np.searchsorted(mk.t1, r.tb_close_ns, side="left"))   # 마디 확정 뒤 첫 1H 봉
        jB = int(mk.j_of_4h[b_idx])
        armed = -1
        n_below = 0
        status = "never_touched"
        trig = -1
        for j in range(j0, n - 1):
            i4 = mk.i4[j]
            if i4 > end_idx or alive4[i4] != m:         # 마디 죽음(종가 A 이탈) 또는 더 새 마디로 교체
                break
            if armed < 0:
                if l[j] <= H + S2_ZONE_W * W:           # 허리 위 지지 구간 첫 터치 [CP-11-2][CP-08-10]
                    armed = j
                    status = "expired"
                else:
                    continue
            if j - armed > S2_ARM_WINDOW:
                break
            if c[j] < H:                                 # 허리 아래 종가: 첫 번째는 버팀, 두 번째면 폐기 [CP-06-6]
                n_below += 1
                if n_below >= 2:
                    status = "cancel_2close"
                    break
            if c[j] > o[j] and c[j] > h[j - 1] and c[j] > H:   # 반등 양봉으로 돌려 세움 [CP-11-3]
                trig = j
                break
        if trig < 0:
            stats[status] += 1
            continue
        j = trig
        i4 = mk.i4[j]
        if not v4[b_idx + 1:i4 + 1].mean() < r.vol_ab_mean:    # 조정 중 거래 감소 [CP-11-1][CP-01-3]
            stats["vol_fail"] += 1
            continue
        if not c4[i4] > H:                                     # 4H 종가가 허리 위 [CP-06-1]
            stats["below_waist"] += 1
            continue
        if not regime[j]:
            stats["regime_fail"] += 1
            continue
        PL = l[jB:j + 1].min()
        b = BUF_ATR * atr[j]
        rows.append({"j": j, "madi": r.madi_id, "c_sig": c[j], "H": side * H, "A": side * A, "B": side * B,
                     "stop_struct": PL - b,          # 눌림 저점 아래 [CP-11-4 눌림 확인]
                     "stop_abs": A - b,              # 마디 시작점 = 절대 기준가 [CP-06-7][CP-05 주의]
                     "tgt_struct": B,                # 마디 고점 = 직전 고점 [CP-11-4]
                     "atr": atr[j]})
    stats["signals"] = len(rows)
    return _variants(rows, side), stats


def s3_from_s1s(mk, s1s: pd.DataFrame) -> pd.DataFrame:
    """S3 = S1 숏 신호 중 '살아 있는 4H 하락 마디 + 4H 종가 < 그 허리'일 때만 [CP-05-7][CP-08-5][CP-06-2]."""
    if s1s.empty:
        return s1s
    keep = mk.da_short[s1s["j"].to_numpy()]
    return s1s[keep].reset_index(drop=True)
