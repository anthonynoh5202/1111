"""공정 무작위 기준선(TREND v1.1 참고) 독립 재현 — 검증관 작성.

backtest/random_fair.py를 쓰지 않고, parity_check.Sim(원자료 재계산, bot·backtest 미사용)으로
'모든 유효 일봉에서 들어갔다면'의 거래 결과 표를 만든 뒤, 실제 E0-L-ENS와 같은 하위 시스템별 거래 수
(N20 56, N55 25, N100 19 — 백테스트 CSV에서 읽음)로 복원 추출 1,000회 → 평균 R 분포의 p95와 비교한다.

데이터 끝까지 청산이 없는 거래(eod)는 마지막 실행 봉 종가로 닫는다(테이커 + 슬리피지) — 백테스트의 eod와 같은 취지.
난수는 다르므로 결론(p95를 넘는가)·p값·평균·표 크기를 비교한다. p95 자체는 참조 JSON이 1,000회 한 번이라
시드 오차(±0.045)가 커서 직접 비교하지 않고 차이만 보고한다(기본 10만 회로 안정된 값을 낸다).

사용법: .venv/bin/python bot/verify/fair_baseline_check.py [--reps 1000] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parity_check as P  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FAIR_JSON = REPO / "backtest" / "results_trend" / "fair_baseline.json"


def trade_table(sim: P.Sim, n: int) -> np.ndarray:
    """유효 일봉 i마다 그날 진입했다면의 R(겹침 무시). 진입 봉이 없으면 제외."""
    c = sim.close
    m = P.M_OF[n]
    last_close = float(sim.x["close"].to_numpy()[-1])
    out = []
    # 추세 청산 신호 날(종가 < D_M)의 목록을 미리
    exit_days = np.array([j for j in range(m, len(c)) if c[j] < c[j - m:j].min()], dtype=int)
    for i in range(max(n, 21), len(c)):
        if np.isnan(sim.atr20[i]):
            continue
        dec = int(sim.day_close_ms[i]) + P.DECISION_DELAY_MS
        ke = sim.first_bar_at_or_after(dec + P.LATENCY_MS)
        if ke is None:
            continue
        entry = float(sim.xopen[ke])
        stop = round(entry - 2.0 * float(sim.atr20[i]), 1)
        risk = (entry - stop) + (P.TAKER + P.SLIP) * (entry + stop)
        k = int(np.searchsorted(exit_days, i, side="right"))
        kt = None
        if k < len(exit_days):
            j = int(exit_days[k])
            kt = sim.first_bar_at_or_after(int(sim.day_close_ms[j]) + P.DECISION_DELAY_MS + P.LATENCY_MS)
        hi = kt if kt is not None else len(sim.xo)
        hits = np.nonzero(sim.xlow[ke:hi] <= stop)[0]
        if len(hits):
            kx = ke + int(hits[0])
            px = float(min(sim.xopen[kx], stop))
            exit_ms = int(sim.xo[kx])
        elif kt is not None:
            kx, px, exit_ms = kt, float(sim.xopen[kt]), int(sim.xo[kt])
        else:
            px, exit_ms = last_close, int(sim.xo[-1] + sim.xlen[-1])
        fund = sim.funding(min(int(sim.xo[ke]), dec + P.LATENCY_MS), exit_ms)
        net = (px - entry) - (P.TAKER + P.SLIP) * (entry + px) - fund
        out.append(net / risk)
    return np.array(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=100000)   # p95는 꼬리가 두꺼워 1,000회면 ±0.05 흔들린다
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)

    bt = pd.read_csv(P.BT_CSV)
    counts = bt["n"].value_counts().to_dict()
    actual = float(bt["r_multiple"].mean())
    sim = P.Sim()
    tables = {n: trade_table(sim, n) for n in (20, 55, 100)}
    rng = np.random.default_rng(a.seed)
    means = np.empty(a.reps)
    for r in range(a.reps):
        parts = [rng.choice(tables[n], size=int(counts[n]), replace=True) for n in (20, 55, 100)]
        means[r] = np.concatenate(parts).mean()
    p05, p50, p95 = np.quantile(means, [0.05, 0.5, 0.95])
    frac = float((means >= actual).mean())

    ref = json.load(open(FAIR_JSON, encoding="utf-8"))
    rc = [c for c in ref["combos"] if c["key"] == "E0-L-ENS"][0]
    out = dict(actual_mean_r_all100=actual, counts={int(k): int(v) for k, v in counts.items()},
               pool_sizes={n: int(len(t)) for n, t in tables.items()},
               independent=dict(mean=float(means.mean()), p05=float(p05), p50=float(p50), p95=float(p95),
                                frac_ge_actual=frac, beats_p95=bool(actual > p95)),
               reference=dict(actual=rc["actual_mean_r"], mean=rc["fair"]["mean"], p05=rc["fair"]["p05"],
                              p50=rc["fair"]["p50"], p95=rc["fair"]["p95"], frac_ge_actual=rc["compare"]["frac_ge_actual"],
                              beats_p95=rc["compare"]["beats_p95"], pool_sizes=rc["fair"]["pool_sizes"]))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    # 비교 기준: 결론(beats_p95)·p값·평균·표 크기. p95 자체는 참조가 1,000회 한 번(고정 시드)이라 시드 오차가 크다
    # (검증 때 참조 함수를 시드 30개로 돌리면 p95 = 1.852 ± 0.044, 10만 회 = 1.851; 참조 JSON의 1.981은 +2.9 sd).
    agree = (out["independent"]["beats_p95"] == out["reference"]["beats_p95"]
             and abs(out["independent"]["frac_ge_actual"] - out["reference"]["frac_ge_actual"]) < 0.03
             and abs(out["independent"]["mean"] - out["reference"]["mean"]) < 0.03
             and out["pool_sizes"] == {20: 2441, 55: 2407, 100: 2362}
             and abs(actual - rc["actual_mean_r"]) < 1e-9)
    out["p95_gap_vs_reference"] = out["independent"]["p95"] - out["reference"]["p95"]
    print("독립 재현과 fair_baseline.json 일치(몬테카를로 오차 안):", agree)
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if agree else 1


if __name__ == "__main__":
    sys.exit(main())
