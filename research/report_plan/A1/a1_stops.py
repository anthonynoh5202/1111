"""A1 §3·§5 데이터 분석: 손절 폭 분포, 손절 뒤 '더 밀림(overshoot)', 무작위 진입 기준선, 펀딩 분포.

실행: /home/user/1111/.venv/bin/python -I A1/a1_stops.py   (결과: A1/out/stops.json + 표 출력)

정의(미래 정보 금지)
- 판단 시점 = 봉 t 마감. 진입가 = 봉 t 종가.
- ATR14 = Wilder 14, 봉 t까지의 값. ATR% = ATR/종가.
- 스윙 저점 i = 앞뒤 3봉보다 저가가 엄격히 낮음. 봉 i+3 마감 뒤에만 사용(i ≤ t−3).
- 롱 손절 후보 = 확정된 스윙 저점 중 가장 최근이면서 '현재 종가보다 아래'인 것. 거리 = (종가 − 그 저가)/종가.
  숏은 스윙 고점으로 대칭. 버퍼(틱·ATR 여유)는 더하지 않은 '맨 거리'다.
- 표본: 판단 시점(봉 마감)이 2024-01-01 ~ 2026-09-28인 모든 봉(전략 신호가 아니라 '아무 때나' 표본).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import a1_common as C

TF_MS = {"1h": 3_600_000, "4h": 14_400_000}
K = 3
LOOKBACK_SWINGS = 200          # 아래쪽 스윙을 찾을 때 거슬러 볼 최대 스윙 개수


def q(a, ps=(10, 25, 50, 75, 90)):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return {f"p{p}": float(np.percentile(a, p)) for p in ps} | {"n": int(a.size), "mean": float(a.mean())}


def stop_distances(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    atr = C.wilder_atr(h, l, c, 14)
    is_sh, is_sl = C.swing_points(h, l, K)
    n = len(df)
    sl_idx = np.flatnonzero(is_sl)
    sh_idx = np.flatnonzero(is_sh)
    d_long = np.full(n, np.nan)
    d_short = np.full(n, np.nan)
    age_long = np.full(n, np.nan)
    age_short = np.full(n, np.nan)
    recent_sl_above = np.zeros(n, dtype=bool)   # 가장 최근 확정 스윙 저점이 이미 종가 위(깨짐)
    recent_sh_below = np.zeros(n, dtype=bool)
    ps = 0   # 확정된 스윙 저점 개수 포인터
    ph = 0
    for t in range(n):
        while ps < len(sl_idx) and sl_idx[ps] + K <= t:
            ps += 1
        while ph < len(sh_idx) and sh_idx[ph] + K <= t:
            ph += 1
        ct = c[t]
        if ps > 0:
            recent_sl_above[t] = l[sl_idx[ps - 1]] >= ct
            for j in range(ps - 1, max(-1, ps - 1 - LOOKBACK_SWINGS), -1):
                if l[sl_idx[j]] < ct:
                    d_long[t] = (ct - l[sl_idx[j]]) / ct
                    age_long[t] = t - sl_idx[j]
                    break
        if ph > 0:
            recent_sh_below[t] = h[sh_idx[ph - 1]] <= ct
            for j in range(ph - 1, max(-1, ph - 1 - LOOKBACK_SWINGS), -1):
                if h[sh_idx[j]] > ct:
                    d_short[t] = (h[sh_idx[j]] - ct) / ct
                    age_short[t] = t - sh_idx[j]
                    break
    out = pd.DataFrame({
        "close": c, "atr_pct": atr / c, "d_long": d_long, "d_short": d_short,
        "age_long": age_long, "age_short": age_short,
        "sl_broken": recent_sl_above, "sh_broken": recent_sh_below,
    }, index=df.index)
    out["decision_ms"] = df.index.as_unit("ms").asi8 + TF_MS[tf]   # 봉 마감 시각(ms)
    out["stop_long"] = c * (1 - d_long)
    out["stop_short"] = c * (1 + d_short)
    return out


def first_hit(arr: np.ndarray, start: int, level: float, below: bool, max_len: int) -> int:
    """arr[start:]에서 처음으로 level에 닿는 인덱스(below=True면 arr ≤ level). 없으면 −1."""
    n = len(arr)
    pos = start
    end = min(n, start + max_len)
    w = 1440
    while pos < end:
        stop = min(end, pos + w)
        seg = arr[pos:stop]
        hits = np.flatnonzero(seg <= level) if below else np.flatnonzero(seg >= level)
        if hits.size:
            return pos + int(hits[0])
        pos = stop
        w = min(w * 4, 200_000)
    return -1


def overshoot_and_baseline(dist: pd.DataFrame, m1: pd.DataFrame, tf: str, rr: float = 2.0,
                           max_days: int = 30, step: int = 1) -> dict:
    """손절에 닿은 뒤 얼마나 더 밀렸나 + 2R 목표/스윙 손절 무작위 진입 기준선(1분봉, 같은 1분봉에서 둘 다 닿으면 손절)."""
    m_open_ms = m1.index.as_unit("ms").asi8
    lo, hi = m1["low"].to_numpy(), m1["high"].to_numpy()
    sel = dist[(dist.index >= C.IS_START) & (dist.index < C.IS_END)]
    sel = sel.iloc[::step]
    max_len = max_days * 1440
    rec = {"long": [], "short": []}
    for ts, row in sel.iterrows():
        i0 = int(np.searchsorted(m_open_ms, row["decision_ms"]))   # 판단 직후 첫 1분봉
        if i0 >= len(lo):
            continue
        entry = row["close"]
        for side in ("long", "short"):
            d = row["d_long"] if side == "long" else row["d_short"]
            if not np.isfinite(d) or d <= 0:
                continue
            if side == "long":
                S = entry * (1 - d)
                T = entry * (1 + rr * d)
                js = first_hit(lo, i0, S, True, max_len)
                jt = first_hit(hi, i0, T, False, max_len)
            else:
                S = entry * (1 + d)
                T = entry * (1 - rr * d)
                js = first_hit(hi, i0, S, False, max_len)
                jt = first_hit(lo, i0, T, True, max_len)
            if js < 0 and jt < 0:
                last = min(len(lo) - 1, i0 + max_len - 1)
                px = m1["close"].iat[last]
                r = ((px - entry) if side == "long" else (entry - px)) / (entry * d)
                rec[side].append((ts, d, "open", r, (last - i0 + 1) / 60, np.nan, np.nan, np.nan, np.nan))
                continue
            stop_first = js >= 0 and (jt < 0 or js <= jt)
            if stop_first:
                j = js
                ov = []
                for wmin in (1, 5, 15, 60):
                    seg_lo = lo[j:j + wmin].min() if side == "long" else None
                    seg_hi = hi[j:j + wmin].max() if side == "short" else None
                    ov.append(((S - seg_lo) if side == "long" else (seg_hi - S)) / entry)
                rec[side].append((ts, d, "stop", -1.0, (j - i0 + 1) / 60, *ov))
            else:
                rec[side].append((ts, d, "tp", rr, (jt - i0 + 1) / 60, np.nan, np.nan, np.nan, np.nan))
    res = {}
    cols = ["ts", "d", "outcome", "r", "hours", "ov1", "ov5", "ov15", "ov60"]
    for side in ("long", "short"):
        df = pd.DataFrame(rec[side], columns=cols)
        st = df[df.outcome == "stop"]
        o = {}
        for c in ("ov1", "ov5", "ov15", "ov60"):
            a = st[c].to_numpy()
            o[c] = {
                "p50": float(np.percentile(a, 50)), "p90": float(np.percentile(a, 90)),
                "p99": float(np.percentile(a, 99)), "p99_9": float(np.percentile(a, 99.9)),
                "max": float(a.max()),
                **{f"share_ge_{g}": float((a >= g / 100).mean()) for g in (0.5, 1, 2, 3, 5)},
            }
        resolved = df[df.outcome != "open"]
        res[side] = {
            "n_entries": int(len(df)), "n_stop": int((df.outcome == "stop").sum()),
            "n_tp": int((df.outcome == "tp").sum()), "n_open": int((df.outcome == "open").sum()),
            "win_rate_resolved": float((resolved.outcome == "tp").mean()),
            "mean_r_gross_all": float(df.r.mean()),
            "hours_resolved": q(resolved.hours.to_numpy()),
            "hours_stop": q(df[df.outcome == "stop"].hours.to_numpy()),
            "hours_tp": q(df[df.outcome == "tp"].hours.to_numpy()),
            "overshoot_after_stop": o,
        }
        # 최악의 사례(1분 안 더 밀림 상위 5건): 진입 판단 시각(KST)·손절 폭·더 밀린 폭
        top = st.sort_values("ov1", ascending=False).head(5)
        res[side]["worst_ov1"] = [
            {"decision_kst": str((r.ts + pd.Timedelta(hours=9 + (1 if tf == "1h" else 4))).strftime("%Y-%m-%d %H:%M")),
             "d_stop": float(r.d), "ov1": float(r.ov1), "ov5": float(r.ov5), "ov60": float(r.ov60)}
            for r in top.itertuples()]
        df.to_csv(C.OUT_DIR / f"baseline_{tf}_{side}.csv.gz", index=False)
    return res


def funding_stats() -> dict:
    f = C.load_funding()
    f = f[(f.index >= C.IS_START) & (f.index < C.IS_END)]
    r = f["last_funding_rate"].to_numpy()
    by_year = {str(y): float(g["last_funding_rate"].mean()) for y, g in f.groupby(f.index.year)}
    return {
        "n": int(r.size), "from": str(f.index.min()), "to": str(f.index.max()),
        "mean": float(r.mean()), "median": float(np.median(r)), "mean_abs": float(np.abs(r).mean()),
        "p10": float(np.percentile(r, 10)), "p90": float(np.percentile(r, 90)),
        "p99": float(np.percentile(r, 99)), "min": float(r.min()), "max": float(r.max()),
        "share_pos": float((r > 0).mean()), "share_eq_0_01pct": float(np.isclose(r, 0.0001).mean()),
        "by_year_mean": by_year,
    }


def main() -> None:
    out = {"funding": funding_stats()}
    m1 = C.load_1m()
    for tf in ("1h", "4h"):
        bars = C.load_klines(tf)
        dist = stop_distances(bars, tf)
        sel = dist[(dist.index >= C.IS_START) & (dist.index < C.IS_END)]
        yearly = {}
        for y, g in sel.groupby(sel.index.year):
            yearly[str(y)] = {"atr_pct_p50": float(g.atr_pct.median()), "d_long_p50": float(g.d_long.median()),
                              "d_short_p50": float(g.d_short.median())}
        both = np.r_[sel.d_long.to_numpy(), sel.d_short.to_numpy()]
        out[tf] = {
            "n_bars": int(len(sel)),
            "atr_pct": q(sel.atr_pct), "d_long": q(sel.d_long), "d_short": q(sel.d_short),
            "d_both": q(both),
            "d_long_in_atr": q(sel.d_long / sel.atr_pct), "d_short_in_atr": q(sel.d_short / sel.atr_pct),
            "age_long_bars": q(sel.age_long), "age_short_bars": q(sel.age_short),
            "share_recent_sl_broken": float(sel.sl_broken.mean()),
            "share_recent_sh_broken": float(sel.sh_broken.mean()),
            "nan_long": int(sel.d_long.isna().sum()), "nan_short": int(sel.d_short.isna().sum()),
            "yearly": yearly,
        }
        # 매매 표본용 손절 폭 분포(몬테카를로가 다시 씀) 저장
        np.save(C.OUT_DIR / f"dstop_{tf}.npy", both[np.isfinite(both)])
        step = 1 if tf == "1h" else 1
        out[tf]["baseline_2R"] = overshoot_and_baseline(dist, m1, tf, rr=2.0, step=step)
        print(tf, "done", flush=True)
    (C.OUT_DIR / "stops.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
