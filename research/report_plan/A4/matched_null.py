"""맞춤 무작위 기준선 — 다른 퀀트의 거래 목록을 받아 '진입 시각만 무작위'로 바꾼 분포를 만든다.

각 실제 거래마다: 같은 달(UTC) 안의 임의의 정시(+5분) · 같은 방향 · 같은 손절 폭(진입가 대비 %) · 같은 목표 배수(R) ·
같은 최대 보유 시간 · 같은 비용 규칙으로 K번 다시 친다. 반복마다 거래당 하나씩 골라 평균 R → 분포(1,000회).
실제 평균 R이 이 분포의 95% 분위를 넘어야 '진입 시점에 실력이 있다'.

입력 CSV 열: entry_utc(ISO), side(+1/−1), stop_pct(예 0.02), target_r(빈칸이면 목표 없음), max_hold_h, r(실제 결과 R)
실행: /home/user/1111/.venv/bin/python matched_null.py trades.csv   (인자 없으면 자체 시험)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

import common as C


def matched_null(trades: pd.DataFrame, k: int = 40, reps: int = 1000, seed: int = 11) -> dict:
    eng = C.Engine()
    rng = np.random.default_rng(seed)
    pool = np.full((len(trades), k), np.nan)
    for i, tr in enumerate(trades.itertuples(index=False)):
        t = C.utc(str(tr.entry_utc).replace("Z", ""))
        ts = pd.Timestamp(t, unit="ns")
        m0 = C.utc(f"{ts.year}-{ts.month:02d}-01")
        m1 = C.utc(f"{ts.year + (ts.month == 12)}-{(ts.month % 12) + 1:02d}-01")
        hours = np.arange(m0, min(m1, C.OOS_END - int(tr.max_hold_h + 2) * C.NS_HOUR), C.NS_HOUR)
        if len(hours) == 0:
            continue
        pick = rng.choice(hours, size=k, replace=True)
        tgt = None if (pd.isna(tr.target_r) or tr.target_r == "") else float(tr.target_r)
        for j, h in enumerate(pick):
            st = int(h + 5 * C.NS_MIN)
            i0 = eng.idx_at(st)
            if i0 >= len(eng.ex.t):
                continue
            ref = eng.ex.o[i0]
            o = eng.run(int(tr.side), st, stop_dist=float(tr.stop_pct) * ref, target_r=tgt,
                        max_hold_ns=int(float(tr.max_hold_h) * C.NS_HOUR))
            if o.status == "filled":
                pool[i, j] = o.r
    means = []
    for _ in range(reps):
        col = rng.integers(0, k, size=len(trades))
        v = pool[np.arange(len(trades)), col]
        means.append(np.nanmean(v))
    means = np.asarray(means)
    actual = float(trades["r"].mean())
    return dict(n=int(len(trades)), actual_mean_r=actual, null_p05=float(np.quantile(means, 0.05)),
                null_p50=float(np.quantile(means, 0.5)), null_p95=float(np.quantile(means, 0.95)),
                p_value=float((np.sum(means >= actual) + 1) / (reps + 1)), beats_p95=bool(actual > np.quantile(means, 0.95)))


def self_test() -> dict:
    """자체 시험: R2 규칙 + 4h 이평 방향(롱·숏), 겹치지 않게(analysis_extra와 같은 방식) OOS 거래로 맞춤 무작위와 비교."""
    from analysis_extra import trend_dir
    from random_baseline import load_spec, period_mask
    d = load_spec("R2")
    t = d["t_dec"]
    m = period_mask(t, "OOS")
    idx = np.nonzero(m)[0]
    dirn = trend_dir("4h", t)
    rows = []
    i = idx[0]
    while i <= idx[-1]:
        s = dirn[i]
        j = 0 if s > 0 else 1
        if s == 0 or not np.isfinite(d["r"][i, j]):
            i += 1
            continue
        rows.append(dict(entry_utc=pd.Timestamp(int(d["entry_t"][i, j]), unit="ns").isoformat(), side=1 if j == 0 else -1,
                         stop_pct=float(d["stop_pct"][i, j]), target_r=2.0, max_hold_h=72, r=float(d["r"][i, j])))
        i = int(np.searchsorted(t, d["exit_t"][i, j], side="right"))
    tr = pd.DataFrame(rows)
    res = matched_null(tr)
    res["what"] = "R2 + 4h SMA20/60 방향, OOS, 겹치지 않게"
    return res


if __name__ == "__main__":
    if len(sys.argv) > 1:
        out = matched_null(pd.read_csv(sys.argv[1]))
    else:
        out = self_test()
    (C.OUT / "matched_null_selftest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))
