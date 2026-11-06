"""(c) 무작위 진입 기준선 — 매시간 보고 시각마다 롱·숏을 '같은 손절·목표·보유 규칙'으로 들어가 본 결과.

질문: "진입 시점·방향을 아무렇게나 골라도 이 손절·목표·보유 규칙이면 얼마가 나오나?"
→ 어떤 추천 시스템이든 같은 규칙을 쓴다면 이 분포를 넘어야 '진입 판단에 실력이 있다'고 말할 수 있다.

규칙(사양 4개, 결과 전부 보고)
- 판단 시각: 매시 1시간봉 마감, 진입 = 마감 + 5분 첫 실행 봉 시가(시장가) 또는 지정가.
- R1  1h 스윙   : 손절 1.5×ATR14(1h), 목표 2R, 최대 보유 24시간, 시장가
- R2  4h 스윙   : 손절 1.5×ATR14(4h), 목표 2R, 최대 보유 72시간, 시장가
- R3  4h 넓게   : 손절 2.0×ATR14(4h), 목표 3R, 최대 보유 120시간, 시장가
- RL  4h 지정가 : 지정가 = 마감가 −(롱)/+(숏) 0.5×ATR14(1h), 6시간 유효, 손절 1.5×ATR14(4h)(지정가 기준), 목표 2R, 보유 72시간
- 비용·채점: common.py (테이커 0.05%·메이커 0.02%·슬리피지 0.02%, 실제 펀딩, 1분/5분 봉, 같은 봉이면 손절 우선).

출력: out/random_hourly_<spec>.npz (매시간 × 롱/숏 결과), out/random_summary.json
실행: /home/user/1111/.venv/bin/python random_baseline.py
"""
from __future__ import annotations

import json
import sys
import time
from multiprocessing import Pool

import numpy as np

import zlib

import common as C


def C_seed(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode())

SPECS = {
    "R1": dict(label="1h 스윙(손절 1.5×ATR1h, 목표 2R, 24h)", atr_tf="1h", k=1.5, tr=2.0, hold=24, entry="market"),
    "R2": dict(label="4h 스윙(손절 1.5×ATR4h, 목표 2R, 72h)", atr_tf="4h", k=1.5, tr=2.0, hold=72, entry="market"),
    "R3": dict(label="4h 넓게(손절 2×ATR4h, 목표 3R, 120h)", atr_tf="4h", k=2.0, tr=3.0, hold=120, entry="market"),
    "RL": dict(label="4h 지정가(0.5×ATR1h 눌림, 6h 유효, 손절 1.5×ATR4h, 2R, 72h)", atr_tf="4h", k=1.5, tr=2.0, hold=72,
               entry="limit", pull_tf="1h", pull=0.5, valid=6),
}
ENTRY_DELAY = 5 * C.NS_MIN
START = C.utc("2020-01-04 00:00")


def decision_grid():
    b1 = C.load_tf("1h")
    close_t = b1.close_t
    m = (close_t >= START) & (close_t < C.OOS_END)
    return close_t[m], b1.c[m]


def atr_asof(tf: str, query_t: np.ndarray) -> np.ndarray:
    b = C.load_tf(tf)
    a = C.atr(b, 14)
    return C.asof_value(b.close_t, a, query_t)


def run_spec(key: str) -> str:
    sp = SPECS[key]
    eng = C.Engine()
    t_dec, px_dec = decision_grid()
    a_stop = atr_asof(sp["atr_tf"], t_dec)
    a_pull = atr_asof(sp.get("pull_tf", "1h"), t_dec)
    n = len(t_dec)
    fields = ["r", "r_gross", "cost_r", "fund_r", "mfe_r", "mae_r", "entry_px", "r_den"]
    out = {f: np.full((n, 2), np.nan) for f in fields}
    kind = np.full((n, 2), "", dtype="<U7")
    entry_t = np.zeros((n, 2), dtype=np.int64)
    exit_t = np.zeros((n, 2), dtype=np.int64)
    amb = np.zeros((n, 2), dtype=bool)
    res = np.zeros((n, 2), dtype=np.int16)
    stop_pct = np.full((n, 2), np.nan)
    t0 = time.time()
    hold = sp["hold"] * C.NS_HOUR
    for i in range(n):
        if not np.isfinite(a_stop[i]) or not np.isfinite(a_pull[i]):
            continue
        st = int(t_dec[i] + ENTRY_DELAY)
        for j, side in enumerate((1, -1)):
            dist = sp["k"] * a_stop[i]
            if sp["entry"] == "market":
                o = eng.run(side, st, stop_dist=dist, target_r=sp["tr"], max_hold_ns=hold)
            else:
                lim = px_dec[i] - side * sp["pull"] * a_pull[i]
                o = eng.run(side, st, entry="limit", limit_px=float(lim), valid_until=int(st + sp["valid"] * C.NS_HOUR),
                            stop_dist=dist, target_r=sp["tr"], max_hold_ns=hold)
            if o.status != "filled":
                kind[i, j] = "unfill" if o.status == "unfilled" else "nodata"
                continue
            for f in fields:
                out[f][i, j] = getattr(o, f)
            kind[i, j] = o.exit_kind
            entry_t[i, j] = o.entry_t
            exit_t[i, j] = o.exit_t
            amb[i, j] = o.ambiguous
            res[i, j] = o.res_min
            stop_pct[i, j] = dist / o.entry_px
        if i % 10000 == 0:
            print(key, i, n, f"{time.time()-t0:.0f}s", flush=True)
    np.savez_compressed(C.OUT / f"random_hourly_{key}.npz", t_dec=t_dec, px_dec=px_dec, kind=kind, entry_t=entry_t,
                        exit_t=exit_t, amb=amb, res=res, stop_pct=stop_pct, **out)
    return f"{key} done {time.time()-t0:.0f}s"


# ---------------------------------------------------------------------------
# 분석
# ---------------------------------------------------------------------------
def load_spec(key: str) -> dict:
    z = np.load(C.OUT / f"random_hourly_{key}.npz")
    return {k: z[k] for k in z.files}


def period_mask(t: np.ndarray, per: str) -> np.ndarray:
    a, b = C.PERIODS[per] if per in C.PERIODS else (C.CLEAN_START, C.OOS_END)
    return (t >= a) & (t < b)


def acf_tau(x: np.ndarray, max_lag: int) -> tuple[float, list[float]]:
    """적분 자기상관 시간 τ = 1 + 2Σρ_k (ρ가 처음 0.02 아래로 떨어지면 멈춤, Sokal식 단순 절단)."""
    x = x[np.isfinite(x)]
    x = x - x.mean()
    v = np.dot(x, x) / len(x)
    rhos = []
    tau = 1.0
    for k in range(1, max_lag + 1):
        rho = float(np.dot(x[:-k], x[k:]) / (len(x) - k) / v)
        rhos.append(rho)
        if rho < 0.02:
            break
        tau += 2 * rho
    return tau, rhos


def random_strategies(d: dict, side_mode: str, per: str, wait_h: float, risk: float, n_sims: int, seed: int,
                      lev_cap: float = 10.0, block_h: int = 1) -> dict:
    """겹치지 않는 무작위 전략 n_sims개: 포지션이 없을 때 매시간 확률 q = 1/wait_h로 진입.

    side_mode: 'long' | 'short' | 'mix'(매번 50:50). 위험 r = 자산 × risk (수량 = 자산×risk ÷ R분모, 명목 ≤ lev_cap배).
    자산은 거래 종료 때만 갱신(보유 중 평가손은 최대 −1R이라 낙폭 과소 ≤ 1R 정도).
    """
    rng = np.random.default_rng(seed)
    t = d["t_dec"]
    m = period_mask(t, per)
    idx = np.nonzero(m)[0]
    r = d["r"][idx]           # (n, 2)
    ex_t = d["exit_t"][idx]
    en_t = d["entry_t"][idx]
    td = t[idx]
    rden_pct = d["r_den"][idx] / d["entry_px"][idx]
    kinds = d["kind"][idx]
    n = len(idx)
    years = (C.PERIODS[per][1] - C.PERIODS[per][0]) / (365 * C.NS_DAY) if per in C.PERIODS else (C.OOS_END - C.CLEAN_START) / (365 * C.NS_DAY)
    q = 1.0 / wait_h
    means, ns, cagrs, mdds, mdd_r = [], [], [], [], []
    for s in range(n_sims):
        i = 0
        rs = []
        eq = 1.0
        peak = 1.0
        mdd = 0.0
        # 다음 진입 후보 시각을 기하분포로 건너뛴다
        while True:
            i += int(rng.geometric(q)) - 1
            if i >= n:
                break
            j = 0 if side_mode == "long" else 1 if side_mode == "short" else int(rng.integers(0, 2))
            rv = r[i, j]
            if not np.isfinite(rv):
                # 미체결 지정가: 그 주문이 유효 시간 동안 걸려 있으므로 그동안 새 주문 없음(미래 정보로 건너뛰지 않음)
                i += block_h if kinds[i, j] == "unfill" else 1
                continue
            rs.append(rv)
            lev = min(risk / rden_pct[i, j], lev_cap)
            eq *= 1 + lev * rden_pct[i, j] * rv
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
            # 청산 뒤 첫 판단 시각으로 이동
            i = int(np.searchsorted(td, ex_t[i, j], side="right"))
        rs = np.asarray(rs)
        if len(rs) == 0:
            continue
        means.append(rs.mean())
        ns.append(len(rs))
        cagrs.append(eq ** (1 / years) - 1 if eq > 0 else -1)
        mdds.append(mdd)
        mdd_r.append(C.max_dd_r(rs))
    q5 = lambda a: [float(np.quantile(a, p)) for p in (0.05, 0.5, 0.95)]
    return dict(n_trades_median=float(np.median(ns)), mean_r_p05_p50_p95=q5(means), cagr_p05_p50_p95=q5(cagrs),
                mdd_p05_p50_p95=q5(mdds), mdd_r_p05_p50_p95=q5(mdd_r), n_sims=len(means))


def summarize() -> dict:
    out = {}
    for key, sp in SPECS.items():
        d = load_spec(key)
        t = d["t_dec"]
        res_spec = {"label": sp["label"], "periods": {}}
        for per in ("IS", "OOS", "CLEAN"):
            m = period_mask(t, per)
            pr = {}
            for j, side in enumerate(("long", "short")):
                r = d["r"][m, j]
                k = d["kind"][m, j]
                ok = np.isfinite(r)
                hold_h = (d["exit_t"][m, j] - d["entry_t"][m, j]) / C.NS_HOUR
                s = C.r_summary(r[ok], hold_h[ok])
                s.update(
                    n_decisions=int(m.sum()),
                    fill_rate=float(ok.mean()),
                    target_rate=float((k[ok] == "target").mean()),
                    stop_rate=float((k[ok] == "stop").mean()),
                    time_rate=float((k[ok] == "time").mean()),
                    cost_r=float(np.nanmean(d["cost_r"][m, j][ok])),
                    fund_r=float(np.nanmean(d["fund_r"][m, j][ok])),
                    gross_mean=float(np.nanmean(d["r_gross"][m, j][ok])),
                    mfe_med=float(np.nanmedian(d["mfe_r"][m, j][ok])),
                    mae_med=float(np.nanmedian(d["mae_r"][m, j][ok])),
                    mfe_ge1=float((d["mfe_r"][m, j][ok] >= 1).mean()),
                    stop_pct_med=float(np.nanmedian(d["stop_pct"][m, j][ok])),
                    amb_rate=float(d["amb"][m, j][ok].mean()),
                )
                pr[side] = s
            # 롱·숏 평균(무작위 방향) = 추세 효과가 상쇄된 '순수 비용' 근사
            both = np.isfinite(d["r"][m, 0]) & np.isfinite(d["r"][m, 1])
            rl, rs_ = d["r"][m, 0][both], d["r"][m, 1][both]
            pr["mix_mean"] = float((rl.mean() + rs_.mean()) / 2)
            # 관망 채점용 기본 비율: 두 방향 모두 손절(=어떤 거래도 졌을 '휩쏘') / 어느 한쪽이 목표 도달(=놓칠 수 있는 '깨끗한 움직임')
            kl, ks = d["kind"][m, 0][both], d["kind"][m, 1][both]
            pr["watch_base"] = dict(
                both_stopped=float(((kl == "stop") & (ks == "stop")).mean()),
                one_target=float(((kl == "target") | (ks == "target")).mean()),
                neither=float(((kl == "time") & (ks == "time")).mean()),
                best_of_two_mean=float(np.maximum(rl, rs_).mean()),
            )
            res_spec["periods"][per] = pr
        # 겹침: 같은 방향 매시간 결과의 자기상관 → 독립 표본 수
        m = period_mask(t, "OOS")
        tau_l, rho_l = acf_tau(d["r"][m, 0], max_lag=sp["hold"] * 2)
        tau_s, rho_s = acf_tau(d["r"][m, 1], max_lag=sp["hold"] * 2)
        res_spec["overlap"] = dict(tau_long_h=tau_l, tau_short_h=tau_s,
                                   rho_lag1=rho_l[0] if rho_l else None, rho_lag6=rho_l[5] if len(rho_l) > 5 else None,
                                   rho_lag24=rho_l[23] if len(rho_l) > 23 else None,
                                   indep_per_day_long=24 / tau_l, indep_per_month_long=24 * 30.4 / tau_l)
        # 겹치지 않는 무작위 전략 분포 (기다림 평균 24시간, 위험 1%)
        sims = {}
        for per in ("IS", "OOS"):
            for mode in ("long", "short", "mix"):
                sims[f"{per}_{mode}"] = random_strategies(d, mode, per, wait_h=24, risk=0.01, n_sims=1000,
                                                          seed=C_seed(key, per, mode), block_h=int(sp.get("valid", 1)))
        res_spec["random_strategies_wait24_risk1pct"] = sims
        out[key] = res_spec
        print(key, "summarized", flush=True)
    (C.OUT / "random_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        summarize()
    else:
        keys = list(SPECS) if len(sys.argv) < 2 else sys.argv[1:]
        with Pool(min(4, len(keys))) as p:
            for msg in p.imap_unordered(run_spec, keys):
                print(msg, flush=True)
        summarize()
