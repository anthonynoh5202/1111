"""A1 §9 키워 나가기 사다리 보정: 단계 관문의 '잘못 통과/제대로 통과' 확률, 멈춤 규칙(낙폭·연패)이 울릴 확률, 기대 수익.

실행: /home/user/1111/.venv/bin/python -I A1/a1_ladder.py   (결과: A1/out/ladder.md, ladder.json)

- 거래 1건의 순R: 이기면 +(2d − c_win)/(d + c_loss), 지면 −1 (a1_mc와 같은 비용·손절 분포, 1h 기본).
- 진짜 실력 3가지: ① 승률 40%(비용 전 +0.2R) ③ 36.67%(+0.1R) ② 33.3%(0R, '실력 없음').
- 비용 2가지: 시장가 왕복 / 지정가 진입·목표.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np

import a1_common as C
from a1_mc import EDGES, SEED, costs, d_pool

N_PATHS = 20_000


def r_paths(tf: str, p: float, scen: str, n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    pool = d_pool(tf)
    c_win, c_loss = costs(tf, scen)
    d = pool[rng.integers(0, pool.size, (N_PATHS, n))]
    win = rng.random((N_PATHS, n)) < p
    return np.where(win, (2 * d - c_win) / (d + c_loss), -1.0)


def max_dd_frac(r: np.ndarray, f: float) -> np.ndarray:
    """고정 비율 f 복리 잔고의 최대 낙폭(고점 대비)."""
    eq = np.cumprod(1 + f * r, axis=1)
    eq = np.concatenate([np.ones((r.shape[0], 1)), eq], axis=1)
    peak = np.maximum.accumulate(eq, axis=1)
    return (1 - eq / peak).max(axis=1)


def max_losing_streak(r: np.ndarray) -> np.ndarray:
    loss = r < 0
    best = np.zeros(r.shape[0], dtype=int)
    cur = np.zeros(r.shape[0], dtype=int)
    for t in range(r.shape[1]):
        cur = np.where(loss[:, t], cur + 1, 0)
        best = np.maximum(best, cur)
    return best


def main() -> None:
    out = {"gate": {}, "dd": {}, "streak": {}}
    lines = []
    k = 0
    # 1) 관문: N건 뒤 평균 순R ≥ 기준일 확률
    lines.append("### 관문 보정: N번 거래 뒤 '평균 순R ≥ 기준'일 확률 (1h, 위: 시장가 / 아래: 지정가)\n")
    lines.append("| 비용 | 진짜 실력 | 순기대값 | N=30, 기준 −0.2R | N=50, 기준 −0.1R | N=100, 기준 0R | N=200, 기준 0R | N=200, 기준 +0.05R |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for scen in ("market", "maker"):
        for name, p in EDGES.items():
            r = r_paths("1h", p, scen, 200, SEED + 100 + k)
            k += 1
            mu = float(r.mean())
            cells = []
            for n, thr in ((30, -0.2), (50, -0.1), (100, 0.0), (200, 0.0), (200, 0.05)):
                pr = float((r[:, :n].mean(axis=1) >= thr).mean())
                out["gate"][f"{scen}|{name}|{n}|{thr}"] = pr
                cells.append(f"{pr*100:.0f}%")
            lines.append(f"| {'시장가' if scen=='market' else '지정가'} | {name} | {mu:+.3f}R | " + " | ".join(cells) + " |")
    # 2) 멈춤 규칙: 1% 위험 복리로 100·200번 안에 낙폭 ≥ X%가 생길 확률, 최장 연패
    lines.append("\n### 멈춤 규칙 보정: 1회 위험 1%로 거래할 때, 정해진 횟수 안에 최대 낙폭이 기준을 넘을 확률 (1h, 지정가 비용)\n")
    lines.append("| 진짜 실력 | 거래 수 | 낙폭 ≥10% | ≥15% | ≥20% | ≥30% | 최장 연패 중앙값 | 8연패 이상 | 10연패 이상 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, p in EDGES.items():
        r = r_paths("1h", p, "maker", 200, SEED + 200 + k)
        k += 1
        for n in (100, 200):
            dd = max_dd_frac(r[:, :n], 0.01)
            st = max_losing_streak(r[:, :n])
            row = {f"dd_ge_{x}": float((dd >= x / 100).mean()) for x in (10, 15, 20, 30)}
            row |= {"streak_p50": float(np.median(st)), "streak_ge8": float((st >= 8).mean()), "streak_ge10": float((st >= 10).mean())}
            out["dd"][f"{name}|{n}"] = row
            lines.append(f"| {name} | {n} | {row['dd_ge_10']*100:.0f}% | {row['dd_ge_15']*100:.0f}% | {row['dd_ge_20']*100:.0f}% | {row['dd_ge_30']*100:.1f}% "
                         f"| {row['streak_p50']:.0f} | {row['streak_ge8']*100:.0f}% | {row['streak_ge10']*100:.0f}% |")
    # 2b) R 단위(더하기) 최대 낙폭: 강제 위험처럼 위험 %가 일정하지 않을 때도 쓰는 기준
    lines.append("\n### R 단위 최대 낙폭(고점 대비 누적 R)이 기준 이상이 될 확률 (1h, 지정가 비용)\n")
    lines.append("| 진짜 실력 | 거래 수 | ≥6R | ≥8R | ≥10R | ≥12R | ≥15R | ≥20R | 중앙값 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    out["dd_r"] = {}
    for name, p in EDGES.items():
        r = r_paths("1h", p, "maker", 200, SEED + 300 + k)
        k += 1
        for n in (30, 50, 100, 200):
            cum = np.concatenate([np.zeros((r.shape[0], 1)), np.cumsum(r[:, :n], axis=1)], axis=1)
            dd = (np.maximum.accumulate(cum, axis=1) - cum).max(axis=1)
            row = {f"ge_{x}": float((dd >= x).mean()) for x in (6, 8, 10, 12, 15, 20)} | {"p50": float(np.median(dd))}
            out["dd_r"][f"{name}|{n}"] = row
            lines.append(f"| {name} | {n} | " + " | ".join(f"{row[f'ge_{x}']*100:.0f}%" for x in (6, 8, 10, 12, 15, 20))
                         + f" | {row['p50']:.1f}R |")
    # 3) 기대 수익(원/년): 단계별 1회 위험 금액 × 연간 거래 수 × 순기대값
    lines.append("\n### 현실적인 기대 수익(1년, 원) — 1회 위험 금액 × 거래 수 × 순기대값, 괄호는 ±1 표준편차 범위\n")
    lines.append("| 단계(입금) | 1회 위험 | 1회 위험 금액 | 연 150건 × 순 +0.08R(1h 지정가 ①) | 연 150건 × 순 +0.013R(1h 시장가 ①) | 연 150건 × 순 −0.10R(실력 없음, 지정가) |")
    lines.append("|---|---|---:|---:|---:|---:|")
    sd_r = 1.3
    stages = [("5만 원", "0.001 BTC 강제(1h 중앙 손절)", 0.96 * C.KRW_PER_USDT),
              ("20만 원", "1%", 2_000.0), ("50만 원", "1%", 5_000.0), ("100만 원", "1%", 10_000.0), ("100만 원", "2%", 20_000.0)]
    for st, rk, amt in stages:
        cells = []
        for ev in (0.08, 0.013, -0.10):
            mean = 150 * ev * amt
            sd = (150 ** 0.5) * sd_r * amt
            cells.append(f"{mean:+,.0f} ({mean-sd:+,.0f} ~ {mean+sd:+,.0f})")
        lines.append(f"| {st} | {rk} | {amt:,.0f}원 | " + " | ".join(cells) + " |")
    (C.OUT_DIR / "ladder.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    (C.OUT_DIR / "ladder.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
