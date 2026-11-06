"""무작위 기준선 표(out/random_hourly_*.npz)를 다시 읽어 추가 분석.

1) 무작위 방향 평균(롱 평균과 숏 평균의 평균, 전체 체결 기준 — 지정가 RL의 '둘 다 체결' 부분집합은 미래 조건이라 쓰지 않음)
2) (b)+(c) 결합 기준선: '단순 추세 방향 + 같은 손절·목표·보유'
   - 방향 = 4h 또는 1d 의 SMA20 > SMA60 이면 롱, 아니면 숏(LS) 또는 쉼(LF). 판단 시각까지 마감된 봉만.
   - (가) 매시간 표본 평균(겹침 있음)  (나) 겹치지 않는 결정적 전략: 포지션이 없으면 다음 정시에 바로 진입
3) 관망 채점의 기준 비율(시장가 사양만): 두 방향 모두 손절 / 한쪽이 목표 / 둘 다 시간 청산
4) 연도별 무작위 평균 R (롱·숏)
출력: out/extra_summary.json
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import common as C
from random_baseline import SPECS, load_spec, period_mask


def trend_dir(tf: str, t_dec: np.ndarray) -> np.ndarray:
    b = C.load_tf(tf)
    f, s = C.sma(b.c, 20), C.sma(b.c, 60)
    raw = np.where(np.isfinite(f) & np.isfinite(s), np.where(f > s, 1, -1), 0).astype(float)
    return C.asof_value(b.close_t, raw, t_dec)


def sequential(t_dec, r_pick, exit_pick, rden_pct, risk=0.01, unfilled=None, block_h=1):
    """포지션 없으면 바로 다음 정시 진입. 신호 없음(NaN)이면 다음 정시, 미체결 지정가면 유효 시간(block_h)만큼 기다림."""
    i = 0
    n = len(t_dec)
    rs, eq, peak, mdd = [], 1.0, 1.0, 0.0
    times = []
    while i < n:
        if not np.isfinite(r_pick[i]):
            i += block_h if (unfilled is not None and unfilled[i]) else 1
            continue
        rv = r_pick[i]
        rs.append(rv)
        times.append(t_dec[i])
        lev = min(risk / rden_pct[i], 10.0)
        eq *= 1 + lev * rden_pct[i] * rv
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
        i = int(np.searchsorted(t_dec, exit_pick[i], side="right"))
    return np.asarray(rs), eq, mdd, np.asarray(times)


def main():
    out = {}
    for key, sp in SPECS.items():
        d = load_spec(key)
        t = d["t_dec"]
        res = {"label": sp["label"]}
        # 1) 무작위 방향 평균, 연도별
        yr = {}
        yy = pd.to_datetime(t, unit="ns").year.to_numpy()
        for y in range(2020, 2027):
            m = yy == y
            yr[y] = dict(long=float(np.nanmean(d["r"][m, 0])), short=float(np.nanmean(d["r"][m, 1])))
        res["yearly"] = yr
        mix = {}
        for per in ("IS", "OOS", "CLEAN"):
            m = period_mask(t, per)
            mix[per] = float((np.nanmean(d["r"][m, 0]) + np.nanmean(d["r"][m, 1])) / 2)
        res["mix_mean_allfills"] = mix
        # 3) 관망 기준 비율 (시장가만)
        if sp["entry"] == "market":
            wb = {}
            for per in ("IS", "OOS", "CLEAN"):
                m = period_mask(t, per)
                kl, ks = d["kind"][m, 0], d["kind"][m, 1]
                rl, rs_ = d["r"][m, 0], d["r"][m, 1]
                ok = np.isfinite(rl) & np.isfinite(rs_)
                kl, ks, rl, rs_ = kl[ok], ks[ok], rl[ok], rs_[ok]
                wb[per] = dict(
                    both_stopped=float(((kl == "stop") & (ks == "stop")).mean()),
                    one_target=float(((kl == "target") | (ks == "target")).mean()),
                    both_time=float(((kl == "time") & (ks == "time")).mean()),
                    any_r_ge_1=float((np.maximum(rl, rs_) >= 1).mean()),
                    best_of_two_mean=float(np.maximum(rl, rs_).mean()),
                    worst_of_two_mean=float(np.minimum(rl, rs_).mean()),
                )
            res["watch_base"] = wb
        # 2) 추세 방향 + 같은 규칙
        rden_pct = d["r_den"] / d["entry_px"]
        td = {}
        for tf in ("4h", "1d"):
            dirn = trend_dir(tf, t)
            for mode in ("LS", "LF"):
                pick = np.full(len(t), np.nan)
                ex = np.zeros(len(t), dtype=np.int64)
                rp = np.full(len(t), np.nan)
                unf = np.zeros(len(t), dtype=bool)
                L = dirn > 0
                S = dirn < 0
                pick[L] = d["r"][L, 0]
                ex[L] = d["exit_t"][L, 0]
                rp[L] = rden_pct[L, 0]
                unf[L] = d["kind"][L, 0] == "unfill"
                if mode == "LS":
                    pick[S] = d["r"][S, 1]
                    ex[S] = d["exit_t"][S, 1]
                    rp[S] = rden_pct[S, 1]
                    unf[S] = d["kind"][S, 1] == "unfill"
                name = f"{tf}MA20/60-{mode}"
                rr = {}
                for per in ("IS", "OOS", "CLEAN"):
                    m = period_mask(t, per)
                    hourly = pick[m]
                    hs = C.r_summary(hourly[np.isfinite(hourly)])
                    seq_r, eq, mdd, _ = sequential(t[m], pick[m], ex[m], rp[m], unfilled=unf[m], block_h=int(sp.get("valid", 1)))
                    ss = C.r_summary(seq_r)
                    yrs = ((C.PERIODS[per][1] if per in C.PERIODS else C.OOS_END) - (C.PERIODS[per][0] if per in C.PERIODS else C.CLEAN_START)) / (365 * C.NS_DAY)
                    ss["cagr_risk1"] = float(eq ** (1 / yrs) - 1) if eq > 0 else -1.0
                    ss["mdd_risk1"] = float(mdd)
                    ss["trades_per_month"] = float(len(seq_r) / (yrs * 12))
                    rr[per] = dict(hourly_mean=hs.get("mean"), hourly_n=hs.get("n"), hourly_share=float(np.isfinite(hourly).mean()),
                                   seq=ss)
                td[name] = rr
        res["trend_dir_same_exits"] = td
        out[key] = res
        print(key, "ok", flush=True)
    (C.OUT / "extra_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
