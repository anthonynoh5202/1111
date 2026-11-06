"""3·4번 — 통계 기준(신뢰구간·필요 거래 수·겹침·다중 검정·순차 검정)과 5만 원 단계 모의 실험.

입력: out/random_hourly_*.npz, out/random_summary.json, out/trend_trades.csv.gz (앞 스크립트 결과)
출력: out/stats_summary.json
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

import common as C
from random_baseline import load_spec, period_mask

RNG = np.random.default_rng(20261106)


def sigma_table() -> dict:
    out = {}
    for key in ("R1", "R2", "R3", "RL"):
        d = load_spec(key)
        m = period_mask(d["t_dec"], "OOS")
        r = d["r"][m].ravel()
        r = r[np.isfinite(r)]
        out[key] = dict(sd=float(r.std(ddof=1)), skew=float(pd.Series(r).skew()), mean=float(r.mean()))
    tt = pd.read_csv(C.OUT / "trend_trades.csv.gz")
    for rule in ("4h-MOM-LF-S", "4h-MA-LF-S", "1d-MOM-LF-S", "1d-MA-LS-S"):
        r = tt.loc[tt["rule"] == rule, "r"].to_numpy()
        out[rule] = dict(sd=float(r.std(ddof=1)), skew=float(pd.Series(r).skew()), mean=float(r.mean()), n=int(len(r)))
    # 저장소 G1-T E0-L-ENS (참고: 거래 파일에서)
    try:
        g = pd.read_csv(C.REPO / "backtest" / "results_trend" / "trades" / "E0-L-ENS.csv")
        col = "r_multiple" if "r_multiple" in g.columns else [c for c in g.columns if c.lower().startswith("r")][0]
        r = g[col].dropna().to_numpy(float)
        out["G1T_E0-L-ENS"] = dict(sd=float(r.std(ddof=1)), skew=float(pd.Series(r).skew()), mean=float(r.mean()), n=int(len(r)))
    except Exception as e:  # noqa: BLE001
        out["G1T_E0-L-ENS"] = dict(error=str(e))
    return out


def ci_halfwidth_table(sigmas=(1.2, 2.0, 3.0), ns=(30, 50, 100, 200, 300, 500, 1000, 2000)) -> dict:
    return {f"sd{s}": {n: 1.96 * s / math.sqrt(n) for n in ns} for s in sigmas}


def required_n_table(sigmas=(1.2, 2.0, 3.0), deltas=(0.05, 0.1, 0.15, 0.2, 0.3, 0.5)) -> dict:
    out = {}
    for s in sigmas:
        out[f"sd{s}"] = {}
        for dl in deltas:
            out[f"sd{s}"][dl] = dict(
                power80_alpha5_one=C.n_required(s, dl, 0.05, 0.8),
                power80_alpha5_bonf16=C.n_required(s, dl, 0.05 / 16, 0.8),
                lower_bound_gt0_at_mean=(1.96 * s / dl) ** 2,
            )
    return out


def empirical_power(key="R2", deltas=(0.1, 0.2), ns=(100, 300, 1000), sims=2000) -> dict:
    """실제 R 분포(무작위 R2, OOS, 롱·숏 합침)에서 평균만 δ로 옮겨 N건 뽑았을 때 '95% 하한 > 0' 비율.

    거래끼리 독립이라고 가정(겹치지 않는 실제 거래). 하한은 정규 근사(N ≥ 100이면 부트스트랩과 거의 같다).
    """
    d = load_spec(key)
    m = period_mask(d["t_dec"], "OOS")
    r = d["r"][m].ravel()
    r = r[np.isfinite(r)]
    r = r - r.mean()
    out = {}
    for dl in deltas:
        for n in ns:
            idx = RNG.integers(0, len(r), size=(sims, n))
            x = r[idx] + dl
            lo = x.mean(1) - 1.96 * x.std(1, ddof=1) / math.sqrt(n)
            out[f"d{dl}_n{n}"] = float((lo > 0).mean())
    # 0 우위에서 우연히 '+0.1R 이상' 나올 확률
    for n in ns:
        idx = RNG.integers(0, len(r), size=(sims, n))
        out[f"null_mean_ge_0.1_n{n}"] = float((r[idx].mean(1) >= 0.1).mean())
    return out


def neff_by_spacing(key: str, per: str, spacings=(1, 2, 4, 6, 12, 24, 48)) -> dict:
    """보고 간격 s시간마다 하나씩 표본을 쓸 때 독립 표본 수(같은 방향 롱 결과의 자기상관으로 계산)."""
    d = load_spec(key)
    m = period_mask(d["t_dec"], per)
    x = d["r"][m, 0]
    x = x[np.isfinite(x)]
    x = x - x.mean()
    v = x.var()
    hours = len(x)
    out = {"hours": hours}
    for s in spacings:
        y = x[::s]
        n = len(y)
        tau = 1.0
        for k in range(1, max(2, 400 // s)):
            if k >= n - 2:
                break
            rho = float(np.dot(y[:-k], y[k:]) / (n - k) / v)
            if rho < 0.02:
                break
            tau += 2 * rho
        out[s] = dict(points=n, tau=tau, n_eff=n / tau)
    return out


def multiple_testing(ms=(1, 4, 8, 16, 32, 100), ns=(100, 300, 1000), sd=1.2, sims=200_000) -> dict:
    out = {}
    for M in ms:
        z = RNG.standard_normal((sims // max(1, M // 4 + 1), M)).max(axis=1)
        e_max = float(z.mean())
        p95_max = float(np.quantile(z, 0.95))
        row = dict(E_max_z=e_max, p95_max_z=p95_max, bonf_z=C.ND.inv_cdf(1 - 0.05 / M))
        for n in ns:
            se = sd / math.sqrt(n)
            row[f"luck_best_meanR_n{n}"] = e_max * se
            row[f"p95_best_meanR_n{n}"] = p95_max * se
        out[M] = row
    return out


def sprt_design(mu1=0.15, sd=1.2, alpha=0.05, beta=0.2, n_max=400, sims=20_000) -> dict:
    """Wald 순차 검정: H0 μ=0 vs H1 μ=mu1. 누적 R 경계 = a + b·n (통과) / −c + b·n (중단)."""
    A = math.log((1 - beta) / alpha)
    B = math.log(beta / (1 - alpha))
    k = mu1 / sd ** 2
    b = mu1 / 2
    a_up = A / k
    c_dn = -B / k
    table = {n: dict(pass_cum_r=a_up + b * n, pass_mean=(a_up + b * n) / n, stop_cum_r=-c_dn + b * n,
                     stop_mean=(-c_dn + b * n) / n) for n in (30, 50, 100, 150, 200, 300, 400)}
    # 실제 R 분포로 운영 특성 확인
    d = load_spec("R2")
    m = period_mask(d["t_dec"], "OOS")
    r = d["r"][m].ravel()
    r = r[np.isfinite(r)]
    r = r - r.mean()
    oc = {}
    for mu in (-0.1, 0.0, 0.05, 0.1, 0.15, 0.2, 0.3):
        x = r[RNG.integers(0, len(r), size=(sims, n_max))] + mu
        cum = np.cumsum(x, axis=1)
        nn = np.arange(1, n_max + 1)
        up = cum >= a_up + b * nn
        dn = cum <= -c_dn + b * nn
        first_up = np.where(up.any(1), up.argmax(1), n_max + 1)
        first_dn = np.where(dn.any(1), dn.argmax(1), n_max + 1)
        passed = first_up < first_dn
        stopped = first_dn < first_up
        decided_n = np.minimum(first_up, first_dn) + 1
        oc[mu] = dict(p_pass=float(passed.mean()), p_stop=float(stopped.mean()),
                      p_undecided=float((~passed & ~stopped).mean()),
                      median_n=float(np.median(np.minimum(decided_n, n_max))))
    return dict(mu1=mu1, sd=sd, alpha=alpha, beta=beta, a_up=a_up, c_dn=c_dn, slope=b, table=table, oc=oc, n_max=n_max)


def small_account_mc(e0=35.7, notional=(83.461, 166.9), rden_pct=(0.0115, 0.0237), mus=(-0.035, 0.0, 0.1, 0.2),
                     n_trades=(30, 50, 100), sims=20_000) -> dict:
    """5만 원(35.7 USDT) 단계: 최소 주문 때문에 1회 위험이 고정된다. 무작위 R2 분포(평균만 바꿈)로 자산 경로."""
    d = load_spec("R2")
    m = period_mask(d["t_dec"], "OOS")
    r = d["r"][m].ravel()
    r = r[np.isfinite(r)]
    r = r - r.mean()
    out = {}
    for N in notional:
        for rp in rden_pct:
            one_r = N * rp
            for mu in mus:
                x = r[RNG.integers(0, len(r), size=(sims, max(n_trades)))] + mu
                path = e0 + np.cumsum(x * one_r, axis=1)
                minp = np.minimum.accumulate(path, axis=1)
                cumr = np.cumsum(x, axis=1)
                ddr = np.maximum.accumulate(np.maximum(cumr, 0), axis=1) - cumr
                row = dict(one_r_usdt=one_r, one_r_pct_of_equity=one_r / e0,
                           p_cum_m12_by_30=float((np.minimum.accumulate(cumr, axis=1)[:, 29] <= -12).mean()),
                           p_dd15_by_100=float((np.maximum.accumulate(ddr, axis=1)[:, 99] >= 15).mean()),
                           p_dd20_by_100=float((np.maximum.accumulate(ddr, axis=1)[:, 99] >= 20).mean()))
                for n in n_trades:
                    row[f"p_half_by_{n}"] = float((minp[:, n - 1] <= e0 * 0.5).mean())
                    row[f"p_bust_by_{n}"] = float((minp[:, n - 1] <= one_r).mean())
                    row[f"median_eq_{n}"] = float(np.median(path[:, n - 1]))
                    row[f"p_profit_{n}"] = float((path[:, n - 1] > e0).mean())
                out[f"N{N:.0f}_rden{rp*100:.2f}%_mu{mu:+.3f}"] = row
    return out


def main():
    rs = json.loads((C.OUT / "random_summary.json").read_text())
    out = dict(
        sigma=sigma_table(),
        ci_halfwidth=ci_halfwidth_table(),
        required_n=required_n_table(),
        empirical_power=empirical_power(),
        overlap={k: v["overlap"] for k, v in rs.items()},
        neff_spacing={f"{k}_{p}": neff_by_spacing(k, p) for k in ("R1", "R2") for p in ("OOS", "CLEAN")},
        multiple_testing=multiple_testing(),
        sprt=sprt_design(),
        small_account=small_account_mc(),
    )
    (C.OUT / "stats_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))
    print("ok")


if __name__ == "__main__":
    main()
