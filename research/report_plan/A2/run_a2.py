"""A2 실행: 신호 → 체결(5분봉) → IS/OOS 지표 → 같은 국면 안 무작위 진입 1,000회 비교.

출력: A2/out/results.json, A2/out/trades.csv, A2/out/tables.md (A2_setups.md 에 옮겨 적는 표)
실행: /home/user/1111/.venv/bin/python run_a2.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import a2lib as A
import setups as S

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
N_RAND = 1000
SEED = 20261106

SETUP_REGIME = {"S1L": "DB_L", "S1S": "DB_S", "S2L": "DADB_L", "S2S": "DADB_S", "S3": "DADB_S"}
SETUP_SIDE = {"S1L": 1, "S1S": -1, "S2L": 1, "S2S": -1, "S3": -1}
PERIODS = {"IS": (A.IS_START, A.OOS_START), "OOS": (A.OOS_START, A.END), "ALL": (A.IS_START, A.END)}


def simulate_signals(eng, mk, sig: pd.DataFrame, side: int) -> dict:
    j = sig["j"].to_numpy(np.int64)
    stop = sig["stop"].to_numpy(np.float64)
    tgt = sig["target"].to_numpy(np.float64)
    if np.isnan(tgt).all():
        res = eng.simulate(j, side, stop=stop, t_r=np.full(j.shape, 2.0))
    else:
        res = eng.simulate(j, side, stop=stop, target=tgt)
    res["atr"] = mk.atr1[j]
    res["d_atr"] = res["d"] / res["atr"]
    return res


def month_groups(mk, mask):
    idx = np.flatnonzero(mask)
    mon = mk.month1[idx]
    order = np.argsort(mon, kind="stable")
    idx, mon = idx[order], mon[order]
    uniq, start = np.unique(mon, return_index=True)
    cnt = np.diff(np.r_[start, mon.shape[0]])
    return idx, uniq, start, cnt


def random_baseline(eng, mk, side, mask, months, d_atr, t_r, rng, n_rand=N_RAND):
    """실제 거래 i 마다 같은 달의 국면 해당 시각 중 무작위 1개, 같은 (손절 거리/ATR, 목표 R) 사용."""
    idx, uniq, start, cnt = month_groups(mk, mask)
    pos = np.searchsorted(uniq, months)
    assert (uniq[pos] == months).all()
    N = months.shape[0]
    u = rng.random((n_rand, N))
    pick = idx[start[pos][None, :] + np.floor(u * cnt[pos][None, :]).astype(np.int64)]
    jj = pick.ravel()
    res = eng.simulate(jj, side, d_atr=np.tile(d_atr, n_rand), t_r=np.tile(t_r, n_rand), atr=mk.atr1[jj])
    r = res["r"].reshape(n_rand, N)
    return r.mean(axis=1), r


def period_mask(entry_ns, per):
    a, b = PERIODS[per]
    return (entry_ns >= a) & (entry_ns < b)


def months_in(per):
    a, b = PERIODS[per]
    return (b - a) / (30.4375 * 86400 * 1e9)


def main(level: str = "full"):
    t0 = time.time()
    mk = A.Market()
    eng = A.Engine(mk, A.load_funding())
    print(f"준비 {time.time() - t0:.1f}s")

    sigs, stats = {}, {}
    sigs["S1L"], stats["S1L"] = S.s1_signals(mk, +1, level)
    sigs["S1S"], stats["S1S"] = S.s1_signals(mk, -1, level)
    sigs["S2L"], stats["S2L"] = S.s2_signals(mk, +1, level)
    sigs["S2S"], stats["S2S"] = S.s2_signals(mk, -1, level)
    sigs["S3"] = S.s3_from_s1s(mk, sigs["S1S"])
    stats["S3"] = {"signals": int((sigs["S3"]["variant"] == "V1").sum()) if len(sigs["S3"]) else 0}
    print("신호 단계 통계:", json.dumps(stats, ensure_ascii=False))
    print(f"신호 {time.time() - t0:.1f}s")

    rng = np.random.default_rng(SEED)
    results = {"stats": stats, "combos": {}, "regime_share": {}, "meta": {
        "n_rand": N_RAND, "seed": SEED, "cost": {"taker": A.TAKER, "maker": A.MAKER, "slip": A.SLIP},
        "max_hold_h": A.MAX_HOLD_H}}
    for nm in ("DB_L", "DB_S", "DADB_L", "DADB_S"):
        msk = mk.regime_mask(nm, level)
        results["regime_share"][nm] = {p: float(msk[period_mask(mk.ct1, p)].mean()) for p in PERIODS}
    all_trades = []
    any_signal = np.zeros(mk.n1, dtype=bool)
    for setup, sig_all in sigs.items():
        side = SETUP_SIDE[setup]
        mask = mk.regime_mask(SETUP_REGIME[setup], level)
        mask_any = mk.valid1.copy()
        mask_any[-(A.MAX_HOLD_H + 2):] = False
        for var in ("V1", "V2", "V3", "V4"):
            sig = sig_all[sig_all["variant"] == var].sort_values("j").reset_index(drop=True) if len(sig_all) else sig_all
            key = f"{setup}-{var}"
            if len(sig) == 0:
                results["combos"][key] = {"n_signals": 0}
                continue
            sig = sig[mask[sig["j"].to_numpy()]].reset_index(drop=True)   # 데이터 끝 72시간 제외 등
            if var == "V1" and setup != "S3":
                any_signal[sig["j"].to_numpy()] = True
            res = simulate_signals(eng, mk, sig, side)
            take = A.sequential(sig["j"].to_numpy(), res)
            entry_ns = res["entry_ns"]
            combo = {"n_signals_total": int(len(sig))}
            for per in PERIODS:
                pm_sig = period_mask(entry_ns, per)
                pm = pm_sig & take
                r = res["r"][pm]
                met = A.metrics(r, res["hold_h"][pm])
                met["signals"] = int(pm_sig.sum())
                met["signals_per_month"] = float(pm_sig.sum() / months_in(per))
                met["trades_per_month"] = float(pm.sum() / months_in(per))
                hours = period_mask(mk.ct1, per).sum()
                met["signal_hour_share"] = float(pm_sig.sum() / hours)
                if pm.sum() > 0:
                    kinds = res["kind"][pm]
                    met["exit_share"] = {k: float((kinds == k).mean()) for k in ("stop", "target", "time")}
                    met["avg_cost_r"] = float(res["r_cost"][pm].mean())
                    met["avg_fund_r"] = float(res["r_fund"][pm].mean())
                    met["avg_d_pct"] = float(res["d_pct"][pm].mean())
                    met["med_d_atr"] = float(np.median(res["d_atr"][pm]))
                    met["avg_t_r"] = float(res["t_r"][pm].mean())
                    met["gross_exp"] = float(res["r_gross"][pm].mean())
                    # 무작위 기준선 (같은 국면, 같은 달, 같은 손절·목표 분포)
                    months = mk.month1[res["j"][pm]]
                    if pm.sum() >= 5:
                        rm, _ = random_baseline(eng, mk, side, mask, months, res["d_atr"][pm], res["t_r"][pm], rng)
                        met["rand_mean"] = float(rm.mean())
                        met["rand_p05"] = float(np.quantile(rm, 0.05))
                        met["rand_p95"] = float(np.quantile(rm, 0.95))
                        met["p_vs_rand"] = float((1 + (rm >= met["exp"]).sum()) / (1 + rm.shape[0]))
                        # 참고: 국면 필터 없이 아무 시각(같은 달·같은 방향)
                        rm2, _ = random_baseline(eng, mk, side, mask_any, months, res["d_atr"][pm], res["t_r"][pm],
                                                 rng, n_rand=300)
                        met["rand_any_mean"] = float(rm2.mean())
                    # 연도별
                    yrs = pd.to_datetime(entry_ns[pm], utc=True).year.to_numpy()
                    met["by_year"] = {int(y): {"n": int((yrs == y).sum()), "exp": float(r[yrs == y].mean())}
                                      for y in np.unique(yrs)}
                combo[per] = met
            results["combos"][key] = combo
            tr = pd.DataFrame({k: res[k] for k in ("j", "entry_ns", "exit_ns", "pe", "stop", "target", "d", "r",
                                                    "r_gross", "r_cost", "r_fund", "kind", "hold_h", "d_atr", "t_r")})
            tr["taken"] = take
            tr["setup"] = setup
            tr["variant"] = var
            tr["side"] = side
            all_trades.append(tr)
            o = combo.get("OOS", {})
            i = combo.get("IS", {})
            print(f"{key:8s} sig={len(sig):4d} IS n={i.get('n', 0):3d} exp={i.get('exp', float('nan')):+.3f} "
                  f"p={i.get('p_vs_rand', float('nan')):.3f} | OOS n={o.get('n', 0):3d} exp={o.get('exp', float('nan')):+.3f} "
                  f"rand={o.get('rand_mean', float('nan')):+.3f} p={o.get('p_vs_rand', float('nan')):.3f}  "
                  f"({time.time() - t0:.0f}s)")
    for per in PERIODS:
        pmh = period_mask(mk.ct1, per)
        results.setdefault("any_signal", {})[per] = {
            "hours": int(pmh.sum()), "signal_hours": int((any_signal & pmh).sum()),
            "share": float((any_signal & pmh).sum() / pmh.sum()),
            "per_month": float((any_signal & pmh).sum() / months_in(per))}
    results["meta"]["level"] = level
    pd.concat(all_trades, ignore_index=True).to_csv(OUT / f"trades_{level}.csv", index=False)
    (OUT / f"results_{level}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=float))
    print(f"끝 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "full")
