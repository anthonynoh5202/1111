"""손절·목표와 무관한 점검: 신호 뒤 h시간 수익률(ATR 단위, 비용 전)을 같은 국면·같은 달 무작위 시각과 비교.

fwd_h = side × (close[j+h] − open[j+1]) ÷ ATR[j]   (진입 = 신호 다음 봉 시가)
무작위: 신호마다 같은 달의 국면 해당 시각 1개, 2,000회. p = 무작위 평균 ≥ 실제 평균인 비율.
출력: out/fwd_check.json
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import a2lib as A
import setups as S
from run_a2 import SETUP_REGIME, SETUP_SIDE, PERIODS, month_groups, period_mask

OUT = Path(__file__).resolve().parent / "out"
HS = (4, 24, 72)


def fwd(mk, j, side, h):
    jj = np.minimum(j + h, mk.n1 - 1)
    return side * (mk.c1[jj] - mk.o1[np.minimum(j + 1, mk.n1 - 1)]) / mk.atr1[j]


def main():
    mk = A.Market()
    rng = np.random.default_rng(7)
    out = {}
    for level in ("full", "dir", "none"):
        sigs = {"S1L": S.s1_signals(mk, 1, level)[0], "S1S": S.s1_signals(mk, -1, level)[0],
                "S2L": S.s2_signals(mk, 1, level)[0], "S2S": S.s2_signals(mk, -1, level)[0]}
        sigs["S3"] = S.s3_from_s1s(mk, sigs["S1S"])
        for setup, sg in sigs.items():
            side = SETUP_SIDE[setup]
            mask = mk.regime_mask(SETUP_REGIME[setup], level)
            j_all = np.sort(sg[sg["variant"] == "V1"]["j"].to_numpy())
            j_all = j_all[mask[j_all]]
            for per in ("IS", "OOS"):
                j = j_all[period_mask(mk.ct1[j_all], per)]
                if j.size < 5:
                    continue
                idx, uniq, start, cnt = month_groups(mk, mask)
                pos = np.searchsorted(uniq, mk.month1[j])
                pick = idx[start[pos][None, :] + np.floor(rng.random((2000, j.size)) * cnt[pos][None, :]).astype(np.int64)]
                rec = {"n": int(j.size)}
                for h in HS:
                    a = fwd(mk, j, side, h)
                    rnd = fwd(mk, pick, side, h).mean(axis=1)
                    rec[f"h{h}"] = {"mean": float(a.mean()), "rand": float(rnd.mean()),
                                    "p": float((1 + (rnd >= a.mean()).sum()) / 2001),
                                    "hit": float((a > 0).mean())}
                out[f"{level}|{setup}|{per}"] = rec
                print(level, setup, per, rec["n"], {h: (round(rec[f'h{h}']['mean'], 2), round(rec[f'h{h}']['rand'], 2),
                                                       round(rec[f'h{h}']['p'], 3)) for h in HS})
    (OUT / "fwd_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
