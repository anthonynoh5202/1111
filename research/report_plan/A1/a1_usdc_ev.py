"""A1 §6(d) BTCUSDC 비용 시나리오의 거래당 순기대값(분석식). 가정: 메이커 0%, 테이커 0.04%(2026-09 기준 프로모션),
손절 시장가 슬리피지 0.03%(유동성이 BTCUSDT보다 얕다고 보고 0.02%→0.03%로 가정), 진입·목표는 지정가."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import a1_common as C
from a1_mc import EDGES, FUND_MEAN, HOLD_MEAN_H, d_pool

for tf in ("1h", "4h"):
    pool = d_pool(tf)
    fund = FUND_MEAN * HOLD_MEAN_H[tf] / 8
    for scen, cw, cl in (("BTCUSDT 시장가 왕복", 0.0014, 0.0014), ("BTCUSDT 지정가 진입·목표", 0.0004, 0.0009),
                         ("BTCUSDC 지정가 진입·목표(프로모션)", 0.0, 0.0007)):
        cw2, cl2 = cw + fund, cl + fund
        w = (2 * pool - cw2) / (pool + cl2)
        cr = (cl2 / (pool + cl2)).mean()
        evs = {k: p * w.mean() - (1 - p) for k, p in EDGES.items()}
        print(f"| {tf} | {scen} | {cr:.3f}R | " + " | ".join(f"{v:+.3f}R" for v in evs.values()) + " |")
