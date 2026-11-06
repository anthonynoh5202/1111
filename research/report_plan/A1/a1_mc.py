"""A1 §7 몬테카를로: 기대값 가정 ①②③ × 사이징 방식 × 1h/4h 손절 폭 분포, 100번 매매, 20,000 경로, 시드 고정.

실행: /home/user/1111/.venv/bin/python -I A1/a1_mc.py   (결과: A1/out/mc.json, A1/out/mc.md)

가정
- 결과(비용 전): 이기면 +2R, 지면 −1R. R = 진입~손절 가격 거리. 승률 p: ① 0.40(+0.2R) ② 1/3(0R) ③ 0.3667(+0.1R).
- 손절 폭 d: a1_stops.py의 '아무 때나' 스윙 손절 분포에서 뽑는다. 너무 좁거나 넓은 것은 실전에서 거른다고 보고
  1h는 0.3~3.0%, 4h는 0.6~6.0%만 쓴다(구간 밖 표본 버림).
- 비용(기본): 왕복 시장가 0.14%(테이커 0.05%+슬리피지 0.02% ×2) + 펀딩(평균 요율 × 평균 보유 시간, 롱·숏 모두 '내는' 것으로
  보수적 계산). 1h 평균 보유 32시간, 4h 85시간(a1_stops 무작위 진입 기준선의 결판까지 평균).
  메이커 시나리오: 진입·목표 지정가(0.02%씩), 손절 시장가(0.07%) → 이길 때 0.04%, 질 때 0.09% + 펀딩.
- 사이징
  A/B 자유 사이징 2%/5%: '손절 시 손실(비용 포함) = 잔고 × f'. 최소 수량 제약 없음(= 자금이 충분하거나 작은 단위 상품).
  C  BTCUSDT 최소 수량 강제: 늘 0.001 BTC(83.5 USDT). 실제 위험 = 83.5×(d+비용)/잔고 (잔고가 줄면 커진다).
  D  C + '강제 위험 3% 넘으면 관망': 그 신호는 건너뛰고 다음 신호(조건을 만족하는 d만 뽑음).
  E  구 규칙 0.002 BTC(166.9 USDT) 강제(참고용, 2026-04-14 전 규칙).
- 사실상 파산(최소 주문 불가)
  A/B: 잔고 < 20 USDT × (중앙 d + 비용) ÷ f  → 최소 주문 20 USDT 상품(ETHUSDT와 같은 최소액)에서도 그 위험 %를 못 지킴
  C/E: 잔고 < 포지션 ÷ 허용 레버리지(청산 규칙, 상한 20배) + 진입 비용 → 최소 주문 증거금도 못 냄
  D:   잔고 < 83.5 × (d 10% 분위 + 비용) ÷ 3% → 신호의 90% 이상이 3% 상한에 걸려 사실상 매매 불가
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np

import a1_common as C
from a1_sizing import LIQ_GAP, LIQ_MULT, LEV_CAP

SEED = 20261106
N_PATHS = 20_000
N_TRADES = 100
E0 = C.ACCOUNT_USDT
EDGES = {"①+0.2R": 0.40, "②0R": 1 / 3, "③+0.1R": 0.3667}
BAND = {"1h": (0.003, 0.030), "4h": (0.006, 0.060)}
HOLD_MEAN_H = {"1h": 32.0, "4h": 85.0}
S = json.loads((C.OUT_DIR / "stops.json").read_text())
FUND_MEAN = S["funding"]["mean"]
N_BTC = 0.001 * C.REF_PRICE
N_OLD = 0.002 * C.REF_PRICE
FORCED_CAP = 0.03


def d_pool(tf: str) -> np.ndarray:
    d = np.load(C.OUT_DIR / f"dstop_{tf}.npy")
    lo, hi = BAND[tf]
    return np.sort(d[(d >= lo) & (d <= hi)])


def costs(tf: str, scenario: str) -> tuple[float, float]:
    fund = FUND_MEAN * HOLD_MEAN_H[tf] / 8
    if scenario == "market":
        return C.COST_ALL_MARKET + fund, C.COST_ALL_MARKET + fund       # (이길 때, 질 때)
    return 2 * C.MAKER + fund, C.MAKER + C.TAKER + C.SLIP + fund


def lev_allowed(d):
    """청산 규칙(max(2d, d+3%p))을 롱·숏 모두 지키는 최대 정수 레버리지(상한 20). 숏 쪽이 더 엄격하다:
    숏 청산 거리 = (1/L − MMR)/(1 + MMR) ≥ req  →  L ≤ 1/(MMR + req·(1+MMR))."""
    d = np.asarray(d, dtype=float)
    req = np.maximum(LIQ_MULT * d, d + LIQ_GAP)
    L = np.floor(1.0 / (C.MMR_TIER1 + req * (1 + C.MMR_TIER1)) + 1e-9)
    return np.clip(L, 1, LEV_CAP)


def run(tf: str, p_win: float, mode: str, scenario: str = "market", seed_off: int = 0) -> dict:
    rng = np.random.default_rng(SEED + seed_off)
    pool = d_pool(tf)
    c_win, c_loss = costs(tf, scenario)
    d_med = float(np.median(pool))
    E = np.full(N_PATHS, E0)
    alive = np.ones(N_PATHS, dtype=bool)
    min_E = E.copy()
    risk_sum = np.zeros(N_PATHS)
    n_taken = np.zeros(N_PATHS, dtype=int)
    if mode in ("A2", "B5"):
        f = 0.02 if mode == "A2" else 0.05
        ruin_E = 20.0 * (d_med + c_loss) / f
    elif mode in ("C", "E"):
        N = N_BTC if mode == "C" else N_OLD
        ruin_E = float(N / lev_allowed(d_med) + N * (C.TAKER + C.SLIP))
    elif mode == "D":
        N = N_BTC
        ruin_E = N * (float(np.quantile(pool, 0.10)) + c_loss) / FORCED_CAP
    else:
        raise ValueError(mode)
    ruined = np.zeros(N_PATHS, dtype=bool)
    for t in range(N_TRADES):
        win = rng.random(N_PATHS) < p_win
        if mode == "D":
            # 3% 상한을 지키는 d만: d ≤ 0.03E/N − c_loss
            d_max = FORCED_CAP * E / N - c_loss
            k = np.searchsorted(pool, d_max, side="right")
            ok = k >= max(1, int(0.10 * pool.size))
            idx = np.minimum((rng.random(N_PATHS) * np.maximum(k, 1)).astype(int), pool.size - 1)
            d = pool[idx]
        else:
            d = pool[rng.integers(0, pool.size, N_PATHS)]
            ok = np.ones(N_PATHS, dtype=bool)
            if mode in ("C", "E"):
                # 그 신호의 손절 폭으로 허용되는 레버리지에서 증거금이 잔고에 안 들어가면 건너뜀(파산 판정은 중앙 d 기준)
                ok = E >= N / lev_allowed(d) + N * (C.TAKER + C.SLIP)
        act = alive & ok & ~ruined
        if mode in ("A2", "B5"):
            loss = f * E
            notional = loss / (d + c_loss)
            pnl = np.where(win, notional * (2 * d - c_win), -loss)
            risk = np.full(N_PATHS, f)
        else:
            pnl = np.where(win, N * (2 * d - c_win), -N * (d + c_loss))
            risk = N * (d + c_loss) / E
        E = np.where(act, E + pnl, E)
        risk_sum += np.where(act, risk, 0.0)
        n_taken += act.astype(int)
        min_E = np.minimum(min_E, E)
        newly = act & (E < ruin_E)
        ruined |= newly
        if mode == "D":
            ruined |= alive & ~ok      # 조건을 만족하는 신호가 거의 없음 = 사실상 매매 불가
    q10, q50, q90 = np.percentile(E, [10, 50, 90])
    return {
        "tf": tf, "edge_p": p_win, "mode": mode, "scenario": scenario,
        "final_p10": float(q10), "final_p50": float(q50), "final_p90": float(q90), "final_mean": float(E.mean()),
        "p_final_le_half": float((E <= 0.5 * E0).mean()),
        "p_ever_le_half": float((min_E <= 0.5 * E0).mean()),
        "p_ruin": float(ruined.mean()), "ruin_E": float(ruin_E),
        "p_profit": float((E > E0).mean()),
        "mean_risk": float((risk_sum / np.maximum(n_taken, 1)).mean()),
        "mean_trades": float(n_taken.mean()),
        "net_ev_r_per_trade": None,
    }


def net_ev(tf: str, p_win: float, scenario: str) -> dict:
    """분석식: 위험 단위(손실=1)로 본 거래당 순기대값(d 분포 평균)."""
    pool = d_pool(tf)
    c_win, c_loss = costs(tf, scenario)
    w = (2 * pool - c_win) / (pool + c_loss)       # 이길 때 몇 R(비용 포함 R 기준)
    ev = p_win * w.mean() - (1 - p_win)
    return {"ev_r": float(ev), "win_r_mean": float(w.mean()), "cost_r_mean": float((c_loss / (pool + c_loss)).mean()),
            "d_med": float(np.median(pool))}


def need_n(ev: float, sd: float, z: float) -> float:
    return math.inf if ev <= 0 else (z * sd / ev) ** 2


def main() -> None:
    res = {"ev": {}, "mc": [], "need_n": {}}
    for tf in ("1h", "4h"):
        for scen in ("market", "maker"):
            for name, p in EDGES.items():
                res["ev"][f"{tf}|{scen}|{name}"] = net_ev(tf, p, scen)
    k = 0
    for tf in ("1h", "4h"):
        for name, p in EDGES.items():
            for mode in ("A2", "B5", "C", "D", "E"):
                r = run(tf, p, mode, "market", seed_off=k)
                r["edge"] = name
                res["mc"].append(r)
                k += 1
    for name, p in EDGES.items():           # 메이커 비용 민감도(1h, C·A2)
        for mode in ("A2", "C"):
            r = run("1h", p, mode, "maker", seed_off=k)
            r["edge"] = name
            res["mc"].append(r)
            k += 1
    # 필요한 거래 수: 순기대값 μ, 표준편차 σ(이항 +w/−1)로 단측 90%·95% 하한 > 0
    for key, v in res["ev"].items():
        tf, scen, name = key.split("|")
        p = EDGES[name]
        w = v["win_r_mean"]
        mu = v["ev_r"]
        sd = math.sqrt(p * (1 - p)) * (w + 1)
        res["need_n"][key] = {"mu": mu, "sd": sd, "n90": need_n(mu, sd, 1.2816), "n95": need_n(mu, sd, 1.6449)}
    (C.OUT_DIR / "mc.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    # 마크다운
    lines = []
    lines.append("### 거래당 순기대값(비용 포함, 손실=1R 기준)\n")
    lines.append("| 봉 | 비용 | 가정 | 비용 ÷ R(평균) | 이길 때 평균 | 순기대값 | 단측 95%로 '0보다 크다' 확인에 필요한 거래 수 |")
    lines.append("|---|---|---|---:|---:|---:|---:|")
    for key, v in res["ev"].items():
        tf, scen, name = key.split("|")
        nn = res["need_n"][key]
        n95 = "불가(≤0)" if math.isinf(nn["n95"]) else f"{nn['n95']:,.0f}"
        lines.append(f"| {tf} | {'시장가 왕복' if scen=='market' else '지정가 진입·목표'} | {name} | {v['cost_r_mean']:.3f}R | +{v['win_r_mean']:.2f}R | **{v['ev_r']:+.3f}R** | {n95} |")
    lab = {"A2": "자유 사이징 2%", "B5": "자유 사이징 5%", "C": "BTC 최소 0.001 강제", "D": "최소 0.001 + 강제 위험 3% 상한", "E": "구 규칙 0.002 강제"}
    for scen in ("market", "maker"):
        lines.append(f"\n### 100번 매매 결과 — 비용: {'시장가 왕복(기본)' if scen=='market' else '지정가 진입·목표(민감도, 1h만)'}\n")
        lines.append("| 봉 | 가정 | 사이징 | 평균 실제 위험 | 최종 잔고 중앙값 | 하위 10% | 상위 10% | 이익으로 끝날 확률 | 100번 뒤 반토막 이하 | 도중 한 번이라도 반토막 | 사실상 파산 (기준 잔고) |")
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in res["mc"]:
            if r["scenario"] != scen:
                continue
            lines.append(f"| {r['tf']} | {r['edge']} | {lab[r['mode']]} | {r['mean_risk']*100:.1f}% | {r['final_p50']:.1f} USDT ({C.krw(r['final_p50'])/1e4:.1f}만) "
                         f"| {r['final_p10']:.1f} ({C.krw(r['final_p10'])/1e4:.1f}만) | {r['final_p90']:.1f} | {r['p_profit']*100:.0f}% | {r['p_final_le_half']*100:.1f}% "
                         f"| {r['p_ever_le_half']*100:.1f}% | {r['p_ruin']*100:.1f}% (<{r['ruin_E']:.1f}) |")
    (C.OUT_DIR / "mc.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
