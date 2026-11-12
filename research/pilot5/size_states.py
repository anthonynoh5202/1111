"""'다음 16시간에 얼마나 움직일까'는 맞힐 수 있나 — 최근 24시간 봉 크기로 나눠 본 다음 움직임.

- 자료: 바이낸스 BTCUSDT 선물 4시간봉. 경계는 2020~2023년으로 정하고 2024-01~2026-09에서 확인한다.
- 상태: 최근 6봉(24시간)의 (고가−저가)÷종가 평균. 2020~2023년의 3등분 경계로 조용·보통·거침.
- 본 것: 다음 16시간 움직임의 크기, 방향, 16시간 안에 3%·5% 넘게 내려간 적이 있는 비율.
실행: .venv/bin/python -I research/pilot5/size_states.py  →  results/size_states.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "candles"))
import candle_features as cf  # noqa: E402

H = 4
df = cf.load("4h")
O, Hi, L, C, V, TB = cf.arrays(df)
is_is = (df["time"] < cf.IS_END).to_numpy()
n = len(C)
recent = pd.Series((Hi - L) / C * 100).rolling(6).mean().to_numpy()
fwd = np.full(n, np.nan)
fwd[: n - H] = (C[H:] / C[: n - H] - 1) * 100
dip = np.full(n, np.nan)
for k in range(n - H):
    dip[k] = (1 - L[k + 1:k + H + 1].min() / C[k]) * 100
ok = np.isfinite(recent) & np.isfinite(fwd)
q1, q2 = np.quantile(recent[ok & is_is], [1 / 3, 2 / 3])
oos = ok & ~is_is


def rank_corr(a, b):
    return float(np.corrcoef(pd.Series(a).rank(), pd.Series(b).rank())[0, 1])


out = {"boundaries_pct": [round(float(q1), 2), round(float(q2), 2)],
       "rank_corr_size": round(rank_corr(recent[oos], np.abs(fwd[oos])), 3),
       "rank_corr_direction": round(rank_corr(recent[oos], fwd[oos]), 3), "states": {}}
for name, m in (("조용", recent < q1), ("보통", (recent >= q1) & (recent < q2)), ("거침", recent >= q2)):
    s = fwd[oos & m]
    a = np.abs(s)
    d = dip[oos & m]
    out["states"][name] = dict(share_pct=round(float((oos & m).sum() / oos.sum() * 100), 1),
                               median_move_pct=round(float(np.median(a)), 2), p80_move_pct=round(float(np.quantile(a, 0.8)), 2),
                               p90_move_pct=round(float(np.quantile(a, 0.9)), 2), up_share_pct=round(float((s > 0).mean() * 100), 1),
                               dip_ge_3_pct=round(float((d >= 3).mean() * 100), 1), dip_ge_5_pct=round(float((d >= 5).mean() * 100), 1))
i = n - 1
out["latest"] = dict(bar_close_utc=str(df["time"].iloc[i] + pd.Timedelta(hours=4)), close=float(C[i]),
                     recent_size_pct=round(float(recent[i]), 2),
                     state="조용" if recent[i] < q1 else ("보통" if recent[i] < q2 else "거침"),
                     range20=[float(L[i - 19:i + 1].min()), float(Hi[i - 19:i + 1].max())],
                     pos20_pct=round(float((C[i] - L[i - 19:i + 1].min()) / (Hi[i - 19:i + 1].max() - L[i - 19:i + 1].min()) * 100)))
(Path(__file__).resolve().parent / "results" / "size_states.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out, ensure_ascii=False, indent=1))
