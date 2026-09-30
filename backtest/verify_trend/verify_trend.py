"""G1-T(TREND v1.0) 독립 검증 스크립트. backtest 패키지를 import 하지 않는다.

실행 (저장소 루트에서):  python backtest/verify_trend/verify_trend.py [--reps 1000] [--quick]
출력: backtest/verify_trend/verify_result.json (+ 표준 출력 요약)

점검
 1. 표본 거래 재계산 — 조합마다 ≥ 5건(시드 고정, 합계 ≥ 40): 순수 파이썬 경로로 신호·레벨·ATR20·진입·손절·청산·
    수수료·슬리피지·펀딩·R을 원자료에서 다시 계산해 거래 CSV와 비교
 2. 전체 거래 독립 재생성 — 8개 조합 모두(요구는 E0-LS-N55 하나): indep.py 상태 기계로 거래 목록을 만들어
    CSV와 1:1 대조, 거래 수·평균 R·PF 일치 확인. 비용 2배·민감도 32개도 재생성해 JSON과 대조
 3. 보고서 수치 = JSON = 거래 CSV 재집계 (판정 7개 기준 포함, 부트스트랩은 독립 난수로 근사 대조)
 4. 미래 참조: (a) 신호 배열 접두 불변(절단 20곳) (b) 거래마다 신호 봉까지 자른 일봉으로 레벨·ATR·신호 재계산
    (c) 신호 봉 뒤 일봉을 무작위로 바꿔도 신호·레벨·ATR 불변 (d) 진입 봉 시작 ≥ 활성, 체결 봉 = 활성 뒤 첫 봉(E0)
    (e) 청산 신호도 그 날까지 자른 일봉으로 재계산
 5. 상식: 무작위 기준선 독립 재계산(평균·p95), 무조건 무작위 R, 명목 상한(계좌 곡선 독립 재구성),
    하위 시스템 안 겹침 없음, LS의 롱 거래 = L 거래, R 하한
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import indep as I  # noqa: E402

ROOT = I.ROOT
RES = os.path.join(ROOT, "backtest", "results_trend")
COMBOS = [(e, d, p) for e in ("E0", "E1") for d in ("LS", "L") for p in ("ENS", "N55")]
PERIODS = {"ENS": (20, 55, 100), "N55": (55,)}
YEARS = tuple(range(2020, 2027))
SEED = 777_2026
checks: list[dict] = []


def key_of(e, d, p):
    return f"{e}-{d}-{p}"


def check(name, passed, detail, critical=False):
    checks.append(dict(name=name, passed=bool(passed), detail=str(detail), critical=bool(critical)))
    print(("PASS " if passed else ("FAIL*" if critical else "FAIL ")) + name + " :: " + str(detail)[:400])


def iso(ns):
    return pd.Timestamp(int(ns), unit="ns", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def rel_close(a, b, tol=1e-9, abs_tol=1e-9):
    return abs(a - b) <= max(abs_tol, tol * max(abs(a), abs(b)))


# ---------------------------------------------------------------------------
# 통계 (독립 구현)
# ---------------------------------------------------------------------------

def pf(r):
    r = np.asarray(r)
    w, l = r[r > 0].sum(), -r[r < 0].sum()
    return float("inf") if l == 0 else float(w / l)


def boot_lo(r, rng, n=10000):
    r = np.asarray(r)
    idx = rng.integers(0, r.size, size=(n, r.size))
    return float(np.quantile(r[idx].mean(axis=1), 0.025))


def years_of(ns):
    return pd.to_datetime(np.asarray(ns, dtype=np.int64), unit="ns", utc=True).year.to_numpy()


def yearly(r, yrs):
    out = {}
    for y in YEARS:
        s = r[yrs == y]
        out[y] = (float(s.mean()) if s.size else None, int(s.size))
    return out


# ---------------------------------------------------------------------------
# 1. 순수 파이썬 거래 재계산 (indep.sim_trade와도 다른 경로)
# ---------------------------------------------------------------------------

def py_trade(daily, ex, fund, row, n, mode, lat=30, katr=2.0):
    """CSV 한 행의 (신호 봉, 방향, N)만 받아 모든 값을 반복문으로 다시 계산."""
    side = int(row["side"])
    sig_ns = int(row["signal_time_ns"])
    cns = daily["close_ns"]
    t = int(np.flatnonzero(cns == sig_ns)[0])
    c, h, l = daily["close"], daily["high"], daily["low"]
    m = I.exit_len(n)
    upN = max(c[t - n:t]); dnN = min(c[t - n:t])
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(t - 20, t)]
    atr = sum(trs) / 20.0
    cond = c[t] > upN if side > 0 else c[t] < dnN
    level = upN if side > 0 else dnN
    # 청산 신호 날: 이후 날 k에서 직전 m개 종가 기준
    k = None
    for kk in range(t + 1, len(c)):
        w = c[kk - m:kk]
        if (side > 0 and c[kk] < min(w)) or (side < 0 and c[kk] > max(w)):
            k = kk
            break
    dec = sig_ns + I.NS_MIN
    act = dec + lat * I.NS_MIN
    ons, cls = ex["open_ns"], ex["close_ns"]
    j = int(np.searchsorted(ons, act))            # 시작 ≥ 활성 첫 봉
    assert j == 0 or ons[j - 1] < act
    out = dict(t=t, cond=bool(cond), level=float(level), atr=float(atr), exit_day=k)
    if mode == "E0":
        je, entry, er, es = j, float(ex["open"][j]), I.TAKER, I.SLIP
    else:
        lim = float(np.round(level, 1))
        vu = sig_ns + 5 * I.NS_DAY
        oe = vu
        if k is not None and cns[k] + I.NS_MIN < vu:
            oe = int(cns[k] + I.NS_MIN)
        je = None
        while j < len(ons) and cls[j] <= oe:
            if (side > 0 and ex["low"][j] < lim) or (side < 0 and ex["high"][j] > lim):
                je = j
                break
            j += 1
        if je is None:
            out.update(status="unfilled", order_end=oe, limit=lim)
            return out
        entry, er, es = lim, I.MAKER, 0.0
    stop = float(np.round(entry - side * katr * atr, 1))
    jt = len(ons)
    if k is not None:
        tl = int(cns[k]) + I.NS_MIN + lat * I.NS_MIN
        jt = je + 1
        while jt < len(ons) and ons[jt] < tl:
            jt += 1
    jx = None
    lo_arr, hi_arr = ex["low"], ex["high"]
    for jj in range(je, min(jt, len(ons))):
        if (side > 0 and lo_arr[jj] <= stop) or (side < 0 and hi_arr[jj] >= stop):
            jx = jj
            break
    if jx is not None:
        px = stop
        if jx > je or mode == "E0":
            o = float(ex["open"][jx])
            px = min(stop, o) if side > 0 else max(stop, o)
        reason = "stop"
    elif jt < len(ons):
        jx, px, reason = jt, float(ex["open"][jt]), "trend"
    else:
        jx, px, reason = len(ons) - 1, float(ex["close"][-1]), "eod"
    et, xt = int(ons[je]), int(ons[jx])
    fs = min(et, act) if mode == "E0" else et
    fcost = 0.0
    for f, r in zip(fund["time_ns"], fund["rate"]):
        if fs < f <= xt:
            jf = int(np.searchsorted(ons, f, side="right")) - 1
            x = side * r * float(ex["open"][jf])
            fcost += x
    fees = er * entry + I.TAKER * px
    slip = I.SLIP * px + es * entry
    net = side * (px - entry) - fees - slip - fcost
    risk = abs(entry - stop) + er * entry + (I.TAKER + I.SLIP) * stop + es * entry
    out.update(status="filled", entry_time=et, entry_price=entry, stop=stop, exit_time=xt, exit_price=px,
               exit_reason=reason, fees=fees, slippage=slip, funding=fcost, r=net / risk)
    return out


# ---------------------------------------------------------------------------
# 계좌 곡선 (TREND §3, trend.equity_curve docstring 규칙을 독립 구현)
# ---------------------------------------------------------------------------

def equity(trs, daily, start_day, sizing, trim, cap=0.2, risk_r=0.005):
    f = sorted([t for t in trs if t["status"] == "filled"], key=lambda t: (t["entry_time"], t["n"]))
    cns = daily["close_ns"]
    nd = len(cns)
    ent = [int(np.searchsorted(cns, t["entry_time"], side="right")) for t in f]
    exd = [int(np.searchsorted(cns, t["exit_time"], side="right")) for t in f]
    cash, prev = 1.0, 1.0
    pos = {}
    eq = []
    maxratio = 0.0
    for i in range(start_day, nd):
        if i > start_day:
            o = float(daily["open"][i])
            if trim:
                for j in sorted(pos):
                    q = pos[j]; t = f[j]
                    if q * o > cap * prev * (1 + 1e-9):
                        nq = cap * prev / o
                        slip_e = I.SLIP if t["mode"] == "E0" else 0.0
                        er = I.TAKER if t["mode"] == "E0" else I.MAKER
                        span = max(t["exit_time"] - t["entry_time"], 1)
                        frac = min(max((int(daily["open_ns"][i]) - t["entry_time"]) / span, 0.0), 1.0)
                        pnl = (t["side"] * (o - t["entry_price"]) - (er + slip_e) * t["entry_price"]
                               - (I.TAKER + I.SLIP) * o - t["funding"] * frac)
                        cash += (q - nq) * pnl
                        pos[j] = nq
            if pos and prev > 0:
                maxratio = max(maxratio, sum(q * o for q in pos.values()) / prev)
            for j in range(len(f)):
                if ent[j] == i:
                    t = f[j]
                    notional = min(prev * risk_r / (t["risk"] / t["entry_price"]), cap * prev) if sizing == "risk" \
                        else cap * prev
                    pos[j] = notional / t["entry_price"]
            for j in range(len(f)):
                if exd[j] == i and j in pos:
                    cash += pos.pop(j) * f[j]["net"]
        c = float(daily["close"][i])
        eq.append(cash + sum(q * f[j]["side"] * (c - f[j]["entry_price"]) for j, q in pos.items()))
        prev = eq[-1]
    eq = np.array(eq)
    days = (cns[-1] - cns[start_day]) / I.NS_DAY
    peak = np.maximum.accumulate(eq)
    ret = eq[1:] / eq[:-1] - 1
    return dict(eq=eq, cagr=float((eq[-1] / eq[0]) ** (365 / days) - 1), mdd=float(np.max(1 - eq / peak)),
                sharpe=float(ret.mean() / ret.std(ddof=1) * math.sqrt(365)), maxratio=maxratio)


# ---------------------------------------------------------------------------
# 보고서 표 읽기
# ---------------------------------------------------------------------------

def md_tables(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    tables, cur = [], []
    for ln in lines:
        if ln.startswith("|"):
            cur.append([c.strip() for c in ln.strip().strip("|").split("|")])
        elif cur:
            tables.append(cur); cur = []
    if cur:
        tables.append(cur)
    return [dict(header=t[0], rows=t[2:]) for t in tables]


def num(s):
    s = s.replace("`", "").replace("*", "").replace(",", "").strip()
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)(%?)", s)
    if not m:
        return None
    v = float(m.group(1))
    return v / 100 if m.group(2) else v


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=1000)
    ap.add_argument("--cache", default=os.environ.get("VERIFY_CACHE", ""))
    ap.add_argument("--out", default=os.path.join(HERE, "verify_result.json"))
    args = ap.parse_args()
    t0 = time.time()
    daily, ex, fund = I.load_all(args.cache or None)
    print(f"data: daily {daily['close'].size}, exec {ex['open_ns'].size}, funding {fund['time_ns'].size} "
          f"(synthetic {int(fund['synthetic'].sum())}), {time.time() - t0:.1f}s")
    J = json.load(open(os.path.join(RES, "g1t_results.json")))
    jc = {c["key"]: c for c in J["combos"]}
    csv = {}
    for e, d, p in COMBOS:
        k = key_of(e, d, p)
        df = pd.read_csv(os.path.join(RES, "trades", f"{k}.csv"))
        df["meta_d"] = df["meta"].apply(json.loads)
        df["N"] = df["meta_d"].apply(lambda m: int(m["n"]))
        csv[k] = df
    atr = I.atr_prior(daily["high"], daily["low"], daily["close"], 20)
    sigs = {n: I.signals(daily, n, atr) for n in (20, 55, 100)}
    result = dict(created=pd.Timestamp.now(tz="UTC").isoformat(), seed=SEED, combos={})

    # ---- 데이터 기본 사실
    check("data.exec_bars", ex["open_ns"].size == J["data"]["exec_bars"]["n"],
          f"독립 병합 {ex['open_ns'].size} vs JSON {J['data']['exec_bars']['n']}")
    check("data.funding_synthetic", int(fund["synthetic"].sum()) == J["data"]["funding_n_synthetic"],
          f"대체 펀딩 {int(fund['synthetic'].sum())}행 vs JSON {J['data']['funding_n_synthetic']}")

    # ================= 2. 전체 재생성 =================
    regen = {}
    for e, d, p in COMBOS:
        k = key_of(e, d, p)
        regen[k] = I.run_combo(daily, ex, fund, mode=e, direction=d, periods=PERIODS[p], sigs=sigs)
    fields = [("entry_time_ns", "entry_time", 0), ("entry_price", "entry_price", 1e-9), ("stop", "stop", 1e-9),
              ("exit_time_ns", "exit_time", 0), ("exit_price", "exit_price", 1e-9), ("fees", "fees", 1e-7),
              ("slippage", "slippage", 1e-7), ("funding", "funding", 1e-7), ("r_multiple", "r", 1e-7),
              ("risk_per_unit", "risk", 1e-7)]
    for e, d, p in COMBOS:
        k = key_of(e, d, p)
        df = csv[k]
        mine = regen[k]
        mk = {(r["n"], r["side"], r["signal_ns"]): r for r in mine}
        ck = {(int(r.N), int(r.side), int(r.signal_time_ns)): r for r in df.itertuples()}
        only_mine = sorted(set(mk) - set(ck))
        only_csv = sorted(set(ck) - set(mk))
        worst = {}
        status_mis = 0
        reason_mis = 0
        for kk in set(mk) & set(ck):
            a, b = mk[kk], ck[kk]
            st_b = b.status
            st_a = a["status"]
            if st_a != st_b:
                status_mis += 1
                continue
            if st_a != "filled":
                continue
            if a["exit_reason"] != b.exit_reason:
                reason_mis += 1
            for cf, mf, tol in fields:
                va, vb = float(a[mf]), float(getattr(b, cf))
                diff = abs(va - vb) / max(1.0, abs(vb)) if tol else abs(va - vb)
                worst[cf] = max(worst.get(cf, 0.0), diff)
        ok_set = not only_mine and not only_csv and status_mis == 0 and reason_mis == 0
        ok_vals = all(worst.get(cf, 0) <= (tol if tol else 0) for cf, _, tol in fields)
        rf = np.array([r["r"] for r in mine if r["status"] == "filled"])
        n_j, mr_j, pf_j = jc[k]["summary"]["n"], jc[k]["summary"]["mean_r"], jc[k]["summary"]["pf"]
        ok_stats = rf.size == n_j and abs(rf.mean() - mr_j) < 1e-9 and abs(pf(rf) - pf_j) < 1e-9
        check(f"regen.{k}", ok_set and ok_vals and ok_stats,
              f"행 {len(mine)}/{len(df)}, 나만 {len(only_mine)} CSV만 {len(only_csv)}, 상태 불일치 {status_mis}, "
              f"청산 사유 불일치 {reason_mis}, 최대 상대오차 " +
              ", ".join(f"{c}={v:.1e}" for c, v in worst.items()) +
              f"; n {rf.size}/{n_j}, 평균 R {rf.mean():.6f}/{mr_j:.6f}, PF {pf(rf):.6f}/{pf_j:.6f}",
              critical=not (ok_set and ok_stats))
        result["combos"][k] = dict(n=int(rf.size), mean_r=float(rf.mean()), pf=pf(rf), only_mine=len(only_mine),
                                   only_csv=len(only_csv), worst=worst)

    # E1 상태(만료·취소) 수
    for e, d, p in COMBOS:
        k = key_of(e, d, p)
        mine = regen[k]
        sc = {s: sum(1 for r in mine if r["status"] == s) for s in ("filled", "cancelled", "expired", "not_filled")}
        js = jc[k]["summary"]["status_counts"]
        ec = {s: sum(1 for r in mine if r.get("exit_reason") == s) for s in ("stop", "trend", "eod")}
        check(f"regen.status_exit_counts.{k}", sc == js and ec == jc[k]["summary"]["exit_counts"],
              f"상태 {sc} vs {js}; 청산 {ec} vs {jc[k]['summary']['exit_counts']}")

    # 비용 2배
    for e, d, p in COMBOS:
        k = key_of(e, d, p)
        m2 = I.run_combo(daily, ex, fund, mode=e, direction=d, periods=PERIODS[p], cost=2.0, sigs=sigs)
        r2 = np.array([r["r"] for r in m2 if r["status"] == "filled"])
        j2 = jc[k]["cost2"]
        same = [(r["n"], r["signal_ns"], r.get("exit_time")) for r in m2 if r["status"] == "filled"] == \
               [(r["n"], r["signal_ns"], r.get("exit_time")) for r in regen[k] if r["status"] == "filled"]
        check(f"cost2.{k}", r2.size == j2["n"] and abs(r2.mean() - j2["mean_r"]) < 1e-9 and abs(pf(r2) - j2["pf"]) < 1e-9
              and same, f"n {r2.size}/{j2['n']}, 평균 R {r2.mean():.6f}/{j2['mean_r']:.6f}, PF {pf(r2):.4f}/{j2['pf']:.4f}, "
              f"거래 집합 같음 {same}", critical=abs(r2.mean() - j2["mean_r"]) > 1e-3)
        result["combos"][k]["cost2_mean_r"] = float(r2.mean())

    # 민감도 32개
    sens_bad = []
    for s in J["sensitivity"]:
        cfg = s["config"]
        e, d = cfg["entry"], cfg["direction"]
        per = tuple(cfg["periods"])
        m3 = I.run_combo(daily, ex, fund, mode=e, direction=d, periods=per, lat_min=cfg["latency_min"],
                         k_atr=cfg["stop_atr_mult"], cost=cfg["cost_multiplier"],
                         sigs=sigs if True else None)
        r3 = np.array([r["r"] for r in m3 if r["status"] == "filled"])
        if not (r3.size == s["summary"]["n"] and abs(r3.mean() - s["summary"]["mean_r"]) < 1e-9):
            sens_bad.append((cfg["key"], r3.size, s["summary"]["n"], float(r3.mean()), s["summary"]["mean_r"]))
    check("sensitivity.regen32", not sens_bad, f"불일치 {len(sens_bad)}/32 {sens_bad[:4]}")

    # ================= 1. 표본 거래 순수 파이썬 재계산 =================
    rng = np.random.default_rng(SEED)
    sample_rows = []
    total = 0
    bad = []
    for e, d, p in COMBOS:
        k = key_of(e, d, p)
        df = csv[k]
        fl = df[df.status == "filled"]
        pick = list(rng.choice(fl.index.to_numpy(), size=min(5, len(fl)), replace=False))
        # 청산 사유 다양성: 없으면 하나씩 추가 (갭 손절·eod 포함)
        for rs in ("stop", "trend", "eod"):
            if not any(df.loc[i, "exit_reason"] == rs for i in pick):
                cand = fl.index[fl.exit_reason == rs].to_numpy()
                if cand.size:
                    pick.append(int(rng.choice(cand)))
        if e == "E1":
            un = df.index[df.status != "filled"].to_numpy()
            if un.size:
                pick.append(int(rng.choice(un)))
        for i in pick:
            row = df.loc[i]
            n = int(row["N"])
            got = py_trade(daily, ex, fund, row, n, e)
            meta = row["meta_d"]
            errs = []
            if not got["cond"]:
                errs.append("신호 조건 불성립")
            if abs(got["level"] - meta["level"]) > 1e-9:
                errs.append(f"레벨 {got['level']} vs {meta['level']}")
            if abs(got["atr"] - meta["atr20"]) > 1e-6:
                errs.append(f"ATR {got['atr']} vs {meta['atr20']}")
            exs = iso(daily["close_ns"][got["exit_day"]] + I.NS_MIN) if got["exit_day"] is not None else ""
            if exs != (meta.get("exit_signal_time") or ""):
                errs.append(f"청산 신호 {exs} vs {meta.get('exit_signal_time')}")
            if row["status"] == "filled":
                if got["status"] != "filled":
                    errs.append("미체결로 계산됨")
                else:
                    for cf, mf in (("entry_time_ns", "entry_time"), ("exit_time_ns", "exit_time")):
                        if int(got[mf]) != int(row[cf]):
                            errs.append(f"{cf} {iso(got[mf])} vs {iso(row[cf])}")
                    for cf, mf in (("entry_price", "entry_price"), ("stop", "stop"), ("exit_price", "exit_price"),
                                   ("fees", "fees"), ("slippage", "slippage"), ("funding", "funding"),
                                   ("r_multiple", "r")):
                        if not rel_close(float(got[mf]), float(row[cf]), 1e-7, 1e-7):
                            errs.append(f"{cf} {got[mf]:.6f} vs {row[cf]:.6f}")
                    if got["exit_reason"] != row["exit_reason"]:
                        errs.append(f"사유 {got['exit_reason']} vs {row['exit_reason']}")
            else:
                if got["status"] == "filled":
                    errs.append("CSV 미체결인데 체결로 계산됨")
            total += 1
            sample_rows.append(dict(combo=k, plan_id=row["plan_id"], status=row["status"],
                                    exit_reason=row["exit_reason"] if row["status"] == "filled" else "",
                                    r_csv=float(row["r_multiple"]) if row["status"] == "filled" else None,
                                    r_mine=float(got["r"]) if got.get("status") == "filled" else None,
                                    ok=not errs, errs=errs))
            if errs:
                bad.append((k, row["plan_id"], errs))
    per_combo = {key_of(*c): sum(1 for s in sample_rows if s["combo"] == key_of(*c)) for c in COMBOS}
    check("sample.recompute", not bad and total >= 30 and min(per_combo.values()) >= 5,
          f"{total}건(조합별 {per_combo}), 불일치 {len(bad)} {bad[:3]}", critical=bool(bad))
    result["sample"] = sample_rows

    # ================= 3. 보고서 = JSON = CSV 재집계 =================
    agg_bad = []
    brng = np.random.default_rng(SEED + 1)
    for e, d, p in COMBOS:
        k = key_of(e, d, p)
        df = csv[k]
        fl = df[df.status == "filled"]
        r = fl["r_multiple"].to_numpy()
        s = jc[k]["summary"]
        yrs = years_of(fl["entry_time_ns"].to_numpy())
        yy = yearly(r, yrs)
        pos_years = sum(1 for y in YEARS if yy[y][0] is not None and yy[y][0] > 0)
        mine = dict(n=len(r), n_long=int((fl.side > 0).sum()), n_short=int((fl.side < 0).sum()),
                    mean_r=r.mean(), median_r=float(np.median(r)), win_rate=float((r > 0).mean()), pf=pf(r),
                    total_r=r.sum(), positive_years=pos_years, std_r=float(r.std(ddof=1)))
        for kk, v in mine.items():
            if not rel_close(float(v), float(s[kk]), 1e-9, 1e-9):
                agg_bad.append((k, kk, v, s[kk]))
        for y in YEARS:
            jy = s["yearly"].get(str(y))
            if (jy is None) != (yy[y][0] is None) or (jy is not None and abs(jy - yy[y][0]) > 1e-9) \
                    or s["yearly_n"].get(str(y), 0) != yy[y][1]:
                agg_bad.append((k, f"year{y}", yy[y], jy))
        for n_ in PERIODS[p]:
            rs = fl[fl.N == n_]["r_multiple"].to_numpy()
            bs = jc[k]["by_system"][str(n_)]
            if bs["n"] != rs.size or abs(bs["mean_r"] - rs.mean()) > 1e-9:
                agg_bad.append((k, f"N{n_}", rs.size, bs))
        bl = boot_lo(r, brng)
        result["combos"][k]["boot_lo_indep"] = bl
        if abs(bl - s["boot_lo"]) > 0.06:
            agg_bad.append((k, "boot_lo", bl, s["boot_lo"]))
        # 판정 재계산 (JSON의 무작위 기준 p95·비용 2배는 위에서 독립 확인)
        v = jc[k]["verdict"]
        c = dict(c1_mean_r=mine["mean_r"] >= 0.15, c2_boot_lo=s["boot_lo"] > 0, c3_pf=mine["pf"] >= 1.2,
                 c4_cost2=result["combos"][k]["cost2_mean_r"] > 0,
                 c5_random=mine["mean_r"] > jc[k]["random"]["threshold"], c6_years=pos_years >= 4,
                 c7_enough_trades=len(r) >= 30)
        res = "pending" if not c["c7_enough_trades"] else ("pass" if all(c.values()) else "fail")
        res_json = {"pending": "pending", "hold": "pending"}.get(v["result"], v["result"])
        for ck_, cv in c.items():
            if bool(v[ck_]) != bool(cv):
                agg_bad.append((k, ck_, cv, v[ck_]))
        if res != res_json:
            agg_bad.append((k, "verdict", res, v["result"]))
        result["combos"][k].update(verdict_indep=res, boot_lo_json=s["boot_lo"], positive_years=pos_years)
    check("aggregate.csv_vs_json", not agg_bad, f"불일치 {len(agg_bad)} {agg_bad[:5]}", critical=bool(agg_bad))
    # 요약 목록
    summ = J["summary"]
    vs = {k: result["combos"][k]["verdict_indep"] for k in result["combos"]}
    check("aggregate.summary_lists",
          sorted(summ["fail"]) == sorted(k for k, v in vs.items() if v == "fail") and
          sorted(summ["pending"]) == sorted(k for k, v in vs.items() if v == "pending") and not summ["pass"],
          f"fail {summ['fail']} pending {summ['pending']} pass {summ['pass']}")

    # E1 vs E0 차이
    e1bad = []
    for pr in J["e1_vs_e0"]:
        r1 = csv[pr["e1"]].query("status=='filled'")["r_multiple"].to_numpy()
        r0 = csv[pr["e0"]].query("status=='filled'")["r_multiple"].to_numpy()
        diff = r1.mean() - r0.mean()
        g = np.random.default_rng(SEED + 2)
        dd = r1[g.integers(0, r1.size, (10000, r1.size))].mean(1) - r0[g.integers(0, r0.size, (10000, r0.size))].mean(1)
        lo, hi = np.quantile(dd, [0.025, 0.975])
        if abs(diff - pr["diff"]) > 1e-9 or abs(lo - pr["lo"]) > 0.15 or abs(hi - pr["hi"]) > 0.15 or \
                (lo > 0) != pr["e1_better"]:
            e1bad.append((pr["pair"], diff, lo, hi, pr["diff"], pr["lo"], pr["hi"]))
    check("aggregate.e1_vs_e0", not e1bad, f"불일치 {e1bad}")

    # 보고서 표
    tabs = md_tables(os.path.join(RES, "G1T_REPORT.md"))
    rep_bad = []

    def find(h0):
        return [t for t in tabs if t["header"][:len(h0)] == h0]
    t1 = find(["조합", "거래", "평균 R", "부트스트랩 하한"])[0]
    for row in t1["rows"]:
        k = row[0].strip("`")
        s = jc[k]["summary"]
        exp = [s["n"], s["mean_r"], s["boot_lo"], s["pf"], jc[k]["cost2"]["mean_r"], jc[k]["random"]["threshold"]]
        got = [num(x) for x in row[1:7]]
        tol = [0, 5e-4, 5e-4, 5e-3, 5e-4, 5e-4]
        for a, b, tl in zip(got, exp, tol):
            if a is None or abs(a - b) > tl + 1e-12:
                rep_bad.append(("§1", k, a, b))
        if num(row[7].split("/")[0]) != s["positive_years"]:
            rep_bad.append(("§1 years", k, row[7], s["positive_years"]))
        marks = row[8].split()
        vv = jc[k]["verdict"]
        want = ["○" if vv[c] else "×" for c in ("c1_mean_r", "c2_boot_lo", "c3_pf", "c4_cost2", "c5_random",
                                                  "c6_years", "c7_enough_trades")]
        if marks != want:
            rep_bad.append(("§1 marks", k, marks, want))
        lab = {"fail": "불합격", "pending": "보류", "hold": "보류", "pass": "통과"}[vv["result"]]
        if lab not in row[9]:
            rep_bad.append(("§1 verdict", k, row[9], vv["result"]))
    ty = find(["조합", "2020", "2021"])[0]
    for row in ty["rows"]:
        k = row[0].strip("`")
        s = jc[k]["summary"]
        for y, cell in zip(YEARS, row[1:]):
            v = num(cell)
            nn = int(re.search(r"\((\d+)\)", cell).group(1)) if "(" in cell else 0
            jy = s["yearly"].get(str(y))
            if (jy is None and v is not None) or (jy is not None and abs(v - jy) > 5e-4) or nn != s["yearly_n"].get(str(y), 0):
                rep_bad.append(("§2 year", k, y, cell, jy))
    t3 = find(["비교", "거래 E1/E0"])[0]
    for row, pr in zip(t3["rows"], J["e1_vs_e0"]):
        if abs(num(row[2]) - pr["diff"]) > 5e-4:
            rep_bad.append(("§3", pr["pair"], row[2], pr["diff"]))
        lo_s, hi_s = re.findall(r"[+-]?\d+\.\d+", row[3])
        if abs(float(lo_s) - pr["lo"]) > 5e-4 or abs(float(hi_s) - pr["hi"]) > 5e-4:
            rep_bad.append(("§3 ci", pr["pair"], row[3], pr["lo"], pr["hi"]))
    t4 = find(["조합", "시작", "위험 기반 연 수익률"])[0]
    for row in t4["rows"]:
        k = row[0].strip("`")
        eqj = jc[k]["equity"]
        exp = [eqj["risk"]["cagr"], eqj["risk"]["max_drawdown"], eqj["fixed"]["cagr"], eqj["fixed"]["max_drawdown"]]
        got = [num(row[2]), num(row[3]), num(row[6]), num(row[7])]
        for a, b in zip(got, exp):
            if abs(a - b) > 5e-4 + 1e-12:
                rep_bad.append(("§4", k, a, b))
    t5 = find(["조합", "반복", "실제 평균 R"])[0]
    for row in t5["rows"]:
        k = row[0].strip("`")
        rj = jc[k]["random"]
        exp = [jc[k]["summary"]["mean_r"], rj["mean"], rj["p05"], rj["p50"], rj["p95"], rj["maker"]["p95"], rj["threshold"]]
        got = [num(x) for x in row[2:9]]
        for a, b in zip(got, exp):
            if abs(a - b) > 5e-4 + 1e-12:
                rep_bad.append(("§5", k, a, b))
    t6 = find(["조합", "변형", "거래"])[0]
    smap = {(s["key"], s["variant"]): s for s in J["sensitivity"]}
    vname = {"지연 10분": "lat10", "지연 120분": "lat120", "손절 3 × ATR": "stop3", "비용 2배": "cost2"}
    for row in t6["rows"]:
        k = row[0].strip("`")
        s = smap[(k, vname[row[1]])]
        if int(num(row[2])) != s["summary"]["n"] or abs(num(row[4]) - s["summary"]["mean_r"]) > 5e-4:
            rep_bad.append(("§6", k, row[1], row[2], row[4], s["summary"]["n"], s["summary"]["mean_r"]))
    check("report.tables_vs_json", not rep_bad, f"불일치 {len(rep_bad)} {rep_bad[:5]}", critical=bool(rep_bad))
    # 요약 문장 수치
    rep_txt = open(os.path.join(RES, "G1T_REPORT.md"), encoding="utf-8").read()
    j = jc["E0-L-N55"]
    ok = ("거래 25건" in rep_txt and "평균 2.33R" in rep_txt and "연 4.1%" in rep_txt and "최대 낙폭 9.3%" in rep_txt
          and abs(j["summary"]["mean_r"] - 2.326) < 5e-4 and abs(j["equity"]["risk"]["cagr"] - 0.041) < 5e-4
          and abs(j["equity"]["risk"]["max_drawdown"] - 0.0931) < 5e-4)
    check("report.headline", ok, "한눈에 보기의 E0-L-N55 문장(25건, 2.33R, 연 4.1%, 낙폭 9.3%) = JSON")

    # ================= 4. 미래 참조 =================
    L = daily["close"].size
    cuts = sorted(set(np.linspace(130, L - 1, 20).astype(int).tolist()))
    pre_bad = 0
    for cut in cuts:
        dcut = {k: v[:cut] for k, v in daily.items()}
        atr_c = I.atr_prior(dcut["high"], dcut["low"], dcut["close"], 20)
        for n in (20, 55, 100):
            sc = I.signals(dcut, n, atr_c)
            sf = sigs[n]
            for a in ("up", "dn", "xup", "xdn", "atr"):
                x, y = getattr(sc, a), getattr(sf, a)[:cut]
                if not np.array_equal(np.isnan(x), np.isnan(y)) or not np.allclose(x[~np.isnan(x)], y[~np.isnan(y)], rtol=0, atol=0):
                    pre_bad += 1
            for a in ("le", "se", "lx", "sx"):
                if not np.array_equal(getattr(sc, a), getattr(sf, a)[:cut]):
                    pre_bad += 1
    check("lookahead.prefix_invariance", pre_bad == 0, f"절단 {len(cuts)}곳 × N 3개, 불일치 {pre_bad}", critical=pre_bad > 0)
    # 구현 거래: 신호 봉까지 자른 일봉 + 미래 교란
    la_bad = []
    prng = np.random.default_rng(SEED + 3)
    n_checked = 0
    for k, df in csv.items():
        e = k[:2]
        for row in df.itertuples():
            n = int(row.N)
            meta = row.meta_d
            t = int(np.flatnonzero(daily["close_ns"] == int(row.signal_time_ns))[0])
            dcut = {kk: v[:t + 1].copy() for kk, v in daily.items()}
            # 미래 교란: 잘린 뒤에 가짜 미래를 붙여도 t의 값이 같아야
            fake = {kk: v.copy() for kk, v in daily.items()}
            sh = prng.normal(1.0, 0.2, L - t - 1)
            for col in ("open", "high", "low", "close"):
                fake[col][t + 1:] = fake[col][t + 1:] * sh
            fake["high"][t + 1:] = np.maximum.reduce([fake["open"][t + 1:], fake["high"][t + 1:], fake["close"][t + 1:]])
            fake["low"][t + 1:] = np.minimum.reduce([fake["open"][t + 1:], fake["low"][t + 1:], fake["close"][t + 1:]])
            for dd, tag in ((dcut, "cut"), (fake, "fake")):
                c = dd["close"]
                up, dn = c[t - n:t].max(), c[t - n:t].min()
                h, l = dd["high"], dd["low"]
                tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(t - 20, t)]
                lev = up if row.side > 0 else dn
                cond = c[t] > up if row.side > 0 else c[t] < dn
                if not cond or abs(lev - meta["level"]) > 1e-9 or abs(np.mean(tr) - meta["atr20"]) > 1e-6:
                    la_bad.append((k, row.plan_id, tag))
            # 이미 진행 중이 아니어야 하는 조건: 롱 신호면 전날까지 롱 포지션 없어야 → 재생성 대조로 확인됨
            # 진입 시각 ≥ 활성, E0는 활성 이후 첫 봉
            act = int(row.active_from_ns)
            if act != int(row.signal_time_ns) + 60 * 10**9 + 30 * I.NS_MIN:
                la_bad.append((k, row.plan_id, "active"))
            if row.status == "filled":
                et = int(row.entry_time_ns)
                j = int(np.searchsorted(ex["open_ns"], et))
                if et < act or (e == "E0" and (j > 0 and ex["open_ns"][j - 1] >= act)):
                    la_bad.append((k, row.plan_id, "entry_before_active"))
                # 추세 청산: 청산 신호 날까지 자른 일봉으로 재계산, 청산 봉 시작 ≥ 그 판단 + L
                if row.exit_reason == "trend":
                    xs = pd.Timestamp(meta["exit_signal_time"]).value - 60 * 10**9
                    kx = int(np.flatnonzero(daily["close_ns"] == xs)[0])
                    m = I.exit_len(n)
                    c = daily["close"][:kx + 1]
                    okx = c[kx] < c[kx - m:kx].min() if row.side > 0 else c[kx] > c[kx - m:kx].max()
                    first = not any((c[q] < c[q - m:q].min() if row.side > 0 else c[q] > c[q - m:q].max())
                                    for q in range(t + 1, kx))
                    if not okx or not first or int(row.exit_time_ns) < xs + 60 * 10**9 + 30 * I.NS_MIN:
                        la_bad.append((k, row.plan_id, "trend_exit"))
                if row.exit_reason == "stop":
                    # 손절 봉 전에는 손절에 닿지 않았어야 (진입 봉 ~ 청산 봉 직전)
                    j0 = int(np.searchsorted(ex["open_ns"], et)); jx = int(np.searchsorted(ex["open_ns"], int(row.exit_time_ns)))
                    seg = ex["low"][j0:jx] <= row.stop if row.side > 0 else ex["high"][j0:jx] >= row.stop
                    hitx = ex["low"][jx] <= row.stop if row.side > 0 else ex["high"][jx] >= row.stop
                    if seg.any() or not hitx:
                        la_bad.append((k, row.plan_id, "stop_first_touch"))
            n_checked += 1
    check("lookahead.trades_truncated_and_perturbed", not la_bad,
          f"구현 거래 {n_checked}행(8조합 CSV 전체): 신호 봉까지 자른 일봉·미래 교란 일봉으로 레벨·ATR·신호 재계산, "
          f"활성 이후 첫 봉 진입, 추세 청산 신호 재계산, 손절 첫 닿음 — 불일치 {len(la_bad)} {la_bad[:4]}",
          critical=bool(la_bad))
    # E1: 체결 봉 끝 ≤ 주문 수명, 체결 봉 시작 ≥ 활성
    e1_bad = []
    for k, df in csv.items():
        if not k.startswith("E1"):
            continue
        for row in df.itertuples():
            meta = row.meta_d
            vu = pd.Timestamp(meta["valid_until"]).value
            oe = vu
            if meta.get("exit_signal_time"):
                xd = pd.Timestamp(meta["exit_signal_time"]).value
                if xd < vu:
                    oe = xd
            if row.status == "filled":
                j = int(np.searchsorted(ex["open_ns"], int(row.entry_time_ns)))
                lim = float(row.plan_entry)
                ok_hit = ex["low"][j] < lim if row.side > 0 else ex["high"][j] > lim
                if ex["close_ns"][j] > oe or int(row.entry_time_ns) < int(row.active_from_ns) or not ok_hit \
                        or abs(row.entry_price - lim) > 1e-9:
                    e1_bad.append((k, row.plan_id))
            else:
                if int(row.busy_until_ns) != oe:
                    e1_bad.append((k, row.plan_id, "order_end"))
    check("lookahead.e1_order_window", not e1_bad, f"E1 체결 봉 끝 ≤ min(만료, 청산 신호 판단), 관통, 지정가 체결 — 불일치 {len(e1_bad)}",
          critical=bool(e1_bad))

    # ================= 5. 상식 점검 =================
    # 5a 무작위 기준선 독립 재계산
    t1_ = time.time()
    tables = {}
    for n in (20, 55, 100):
        sg = sigs[n]
        days = np.flatnonzero(sg.valid)
        for side in (1, -1):
            rr = np.full(days.size, np.nan); rm = np.full(days.size, np.nan)
            for i, dd in enumerate(days):
                tr = I.sim_trade(daily, sg, int(dd), side, ex, fund, mode="E0")
                if tr["status"] == "filled":
                    rr[i] = tr["r"]
                    trm = I.sim_trade(daily, sg, int(dd), side, ex, fund, mode="E0", maker_variant=True)
                    rm[i] = trm["r"]
            months = pd.to_datetime(daily["close_ns"][days], unit="ns", utc=True)
            tables[(n, side)] = dict(days=days, r=rr, rm=rm, ym=(months.year * 12 + months.month - 1).to_numpy())
    print(f"random tables {time.time() - t1_:.1f}s")
    uncond = {f"N{n}{'L' if s > 0 else 'S'}": float(np.nanmean(tables[(n, s)]["r"])) for n in (20, 55, 100) for s in (1, -1)}
    result["random_unconditional_mean_r"] = uncond
    rb_bad = []
    result["random"] = {}
    for e, d, p in COMBOS:
        k = key_of(e, d, p)
        fl = csv[k].query("status=='filled'")
        et = pd.to_datetime(fl["entry_time_ns"].to_numpy(), unit="ns", utc=True)
        ym = (et.year * 12 + et.month - 1).to_numpy()
        g = np.random.default_rng([SEED, len(k), sum(map(ord, k))])
        pools = []
        for (n, s), y in zip(zip(fl.N.to_numpy(), fl.side.to_numpy()), ym):
            tb = tables[(int(n), int(s))]
            sel = np.flatnonzero(tb["ym"] == y)
            pools.append((tb, sel))
        means, means_m = np.empty(args.reps), np.empty(args.reps)
        for rep in range(args.reps):
            v, vm = [], []
            for tb, sel in pools:
                ii = sel[g.integers(0, sel.size)]
                if np.isfinite(tb["r"][ii]):
                    v.append(tb["r"][ii]); vm.append(tb["rm"][ii])
            means[rep], means_m[rep] = np.mean(v), np.mean(vm)
        p95, p95m = float(np.quantile(means, 0.95)), float(np.quantile(means_m, 0.95))
        thr = p95 if e == "E0" else max(p95, p95m)
        rj = jc[k]["random"]
        # 몬테카를로 오차: 반복 평균의 표준편차 / sqrt(reps) 수준 + p95 추정 오차
        sd = float(np.std(means))
        ok = abs(means.mean() - rj["mean"]) < max(0.03, 3 * sd / math.sqrt(args.reps) * 3) and abs(thr - rj["threshold"]) < max(0.06, 0.25 * sd)
        real = float(fl.r_multiple.mean())
        result["random"][k] = dict(mean=float(means.mean()), p95=p95, p95_maker=p95m, threshold=thr, sd=sd,
                                   json_mean=rj["mean"], json_threshold=rj["threshold"], real=real,
                                   c5_indep=real > thr)
        if not ok or (real > thr) != bool(jc[k]["verdict"]["c5_random"]):
            rb_bad.append((k, round(means.mean(), 3), rj["mean"], round(thr, 3), rj["threshold"]))
    check("sanity.random_baseline_indep", not rb_bad,
          "독립 표(유효 일봉 전부 시장가 진입) + 독립 난수 1000회: " +
          "; ".join(f"{k} 평균 {v['mean']:.3f}/{v['json_mean']:.3f} 기준 {v['threshold']:.3f}/{v['json_threshold']:.3f}"
                    for k, v in result["random"].items()), critical=bool(rb_bad))
    check("sanity.random_unconditional", True, "유효 일봉 전체 무조건 무작위 평균 R: " +
          ", ".join(f"{k} {v:+.3f}" for k, v in uncond.items()))
    # 진단(판정 아님): 기준선 설계 민감도 — (a) 무조건 추출(전체 유효 일봉, (N, 방향) 구성 유지)
    # (b) 거래 달 안에서 '실제 신호일 이후' 날만 추출(같은 달의 돌파 전 날짜 제외)
    diag = {}
    for e, d, p in COMBOS:
        k = key_of(e, d, p)
        fl = csv[k].query("status=='filled'")
        g = np.random.default_rng([SEED, 99, sum(map(ord, k))])
        comp = list(zip(fl.N.astype(int), fl.side.astype(int), fl.signal_time_ns.astype(np.int64)))
        et = pd.to_datetime(fl["entry_time_ns"].to_numpy(), unit="ns", utc=True)
        ym = (et.year * 12 + et.month - 1).to_numpy()
        pa, pb = [], []
        for (n, s, sn), y in zip(comp, ym):
            tb = tables[(n, s)]
            ok_ = np.isfinite(tb["r"])
            pa.append(np.flatnonzero(ok_))
            sel = np.flatnonzero((tb["ym"] == y) & ok_ & (daily["close_ns"][tb["days"]] >= sn))
            pb.append(sel if sel.size else np.flatnonzero((tb["ym"] == y) & ok_))
        ma, mb = np.empty(args.reps), np.empty(args.reps)
        for rep in range(args.reps):
            ma[rep] = np.mean([tables[(n, s)]["r"][pl[g.integers(0, pl.size)]] for (n, s, _), pl in zip(comp, pa)])
            mb[rep] = np.mean([tables[(n, s)]["r"][pl[g.integers(0, pl.size)]] for (n, s, _), pl in zip(comp, pb)])
        diag[k] = dict(real=float(fl.r_multiple.mean()), uncond_mean=float(ma.mean()), uncond_p95=float(np.quantile(ma, 0.95)),
                       post_signal_mean=float(mb.mean()), post_signal_p95=float(np.quantile(mb, 0.95)),
                       spec_p95=result["random"][k]["threshold"])
    result["random_design_diagnostic"] = diag
    check("diagnostic.random_design", True, "; ".join(
        f"{k} 실제 {v['real']:+.3f} | 명세(거래 달) p95 {v['spec_p95']:+.3f} | 무조건 평균 {v['uncond_mean']:+.3f} p95 {v['uncond_p95']:+.3f}"
        f" | 신호일 이후만 평균 {v['post_signal_mean']:+.3f} p95 {v['post_signal_p95']:+.3f}" for k, v in diag.items()))
    # 무작위 미체결 원인: 활성 뒤 실행 봉이 없는 마지막 일봉뿐인가
    nf_days = sorted({int(tables[(n, s)]["days"][i]) for (n, s) in tables for i in np.flatnonzero(~np.isfinite(tables[(n, s)]["r"]))})
    check("sanity.random_not_filled_cause", nf_days == [L - 1],
          f"무작위 표에서 체결 안 되는 일봉 = {[iso(daily['close_ns'][x]) for x in nf_days]} (데이터 마지막 일봉: 활성 시각 뒤 실행 봉 없음)")
    # 일봉 파일 vs 실행 봉 집계 일치 (신호 자료와 체결 자료가 같은 시장인지)
    dn = np.searchsorted(daily["open_ns"], ex["open_ns"], side="right") - 1
    agg_h = np.full(L, -np.inf); agg_l = np.full(L, np.inf)
    np.maximum.at(agg_h, dn, ex["high"]); np.minimum.at(agg_l, dn, ex["low"])
    last_idx = np.r_[np.flatnonzero(np.diff(dn)), dn.size - 1]
    first_idx = np.r_[0, np.flatnonzero(np.diff(dn)) + 1]
    agg_c = ex["close"][last_idx]; agg_o = ex["open"][first_idx]
    dev = {nm: float(np.max(np.abs(a - b) / b)) for nm, a, b in (("open", agg_o, daily["open"]), ("high", agg_h, daily["high"]),
                                                                 ("low", agg_l, daily["low"]), ("close", agg_c, daily["close"]))}
    n_close_mis = int(np.sum(np.abs(agg_c - daily["close"]) > 0.05))
    contiguous = bool((np.diff(daily["open_ns"]) == I.NS_DAY).all())
    check("data.daily_vs_exec", contiguous and max(dev.values()) < 2e-3,
          f"일봉 연속 {contiguous}; 실행 봉 집계 대비 최대 상대차 " + ", ".join(f"{k} {v:.1e}" for k, v in dev.items()) +
          f"; 종가 0.05 초과 차이 {n_close_mis}일")
    # E1 '즉시 체결될 지정가'(활성 뒤 첫 봉 시가가 이미 지정가 너머) 수 — 보고서 §8 문장 대조
    rep_txt = open(os.path.join(RES, "G1T_REPORT.md"), encoding="utf-8").read()
    mk_bad = []
    for k, df in csv.items():
        if not k.startswith("E1"):
            continue
        cnt = 0
        for row in df[df.status == "filled"].itertuples():
            j0 = int(np.searchsorted(ex["open_ns"], int(row.active_from_ns)))
            je = int(np.searchsorted(ex["open_ns"], int(row.entry_time_ns)))
            o = ex["open"][je]
            if je == j0 and ((row.side > 0 and o < row.plan_entry) or (row.side < 0 and o > row.plan_entry)):
                cnt += 1
        m_ = re.search(rf"`{k}` (\d+)건", rep_txt)
        if not m_ or int(m_.group(1)) != cnt:
            mk_bad.append((k, cnt, m_.group(1) if m_ else None))
    check("report.e1_marketable_count", not mk_bad, f"E1 즉시 체결 지정가 수 독립 계산 = 보고서 §8 — 불일치 {mk_bad}")
    # 성과 집중도
    conc_msgs = []
    for k in ("E0-LS-ENS", "E0-L-ENS", "E0-LS-N55"):
        r = np.sort(csv[k].query("status=='filled'").r_multiple.to_numpy())[::-1]
        conc_msgs.append(f"{k}: 상위 2건 {r[:2].round(1).tolist()} = 총 R의 {r[:2].sum() / r.sum():.0%}, 제외 시 평균 {r[2:].mean():+.3f}")
    check("diagnostic.concentration", True, "; ".join(conc_msgs))
    # 5b 무작위 선택 효과: 거래 달 추출 vs 거래 달 중 신호 이후 날만
    # 5c 겹침: 하위 시스템 안에서 거래·대기 주문이 겹치지 않음
    ov_bad = []
    for k, df in csv.items():
        for n_, g_ in df.groupby("N"):
            g_ = g_.sort_values("approval_time_ns")
            prev_busy = -1
            for row in g_.itertuples():
                if row.approval_time_ns < prev_busy:
                    # 반대 신호: 청산 신호 날 판단 시각에 새 진입(이전 거래의 추세 청산과 같은 시각 청산 봉)
                    ok_rev = False
                    if prev_row.status == "filled" and prev_row.exit_reason in ("trend", "stop"):
                        xs = prev_row.meta_d.get("exit_signal_time")
                        ok_rev = bool(xs) and pd.Timestamp(xs).value == int(row.approval_time_ns)
                    if not ok_rev:
                        ov_bad.append((k, n_, row.plan_id))
                    elif row.status == "filled" and prev_row.status == "filled" and int(row.entry_time_ns) < int(prev_row.exit_time_ns):
                        ov_bad.append((k, n_, row.plan_id, "entry_before_prev_exit"))
                prev_busy = int(row.busy_until_ns)
                prev_row = row
    check("sanity.no_overlap_within_system", not ov_bad,
          f"하위 시스템 안 동시 포지션·대기 주문 없음(반대 신호 날 제외, 그때도 새 진입 ≥ 이전 청산) — 위반 {len(ov_bad)} {ov_bad[:3]}",
          critical=bool(ov_bad))
    # 5d LS의 롱 = L
    same_bad = []
    for e in ("E0", "E1"):
        for p in ("ENS", "N55"):
            a = csv[key_of(e, "LS", p)]; b = csv[key_of(e, "L", p)]
            ka = a[a.side > 0].assign(pid=lambda x: x.plan_id.str.split("_", n=1).str[1]).sort_values("pid")
            kb = b.assign(pid=lambda x: x.plan_id.str.split("_", n=1).str[1]).sort_values("pid")
            ra, rb = ka.r_multiple.to_numpy(), kb.r_multiple.to_numpy()   # 미체결 행은 NaN
            if len(ka) != len(kb) or (ka.pid.to_numpy() != kb.pid.to_numpy()).any() or \
                    (ka.status.to_numpy() != kb.status.to_numpy()).any() or \
                    not np.array_equal(ra, rb, equal_nan=True):
                same_bad.append((e, p))
    check("sanity.long_subset_identical", not same_bad, f"LS 조합의 롱 행 = L 조합 행(같은 신호·R): 불일치 {same_bad}")
    # 5e R 범위와 손절 R
    rng_msgs = []
    for k, df in csv.items():
        fl = df[df.status == "filled"]
        st = fl[fl.exit_reason == "stop"]
        gap = st[(st.side > 0) & (st.exit_price < st.stop) | (st.side < 0) & (st.exit_price > st.stop)]
        nongap = st.drop(gap.index)
        # 손절 청산 R = -(d + 비용)/(d + c_stop) - 펀딩: -1 근처
        rng_msgs.append(f"{k}: min {fl.r_multiple.min():.2f}, max {fl.r_multiple.max():.1f}, 손절 {len(st)}건 중 갭 {len(gap)}건, "
                        f"비갭 손절 R [{nongap.r_multiple.min():.3f}, {nongap.r_multiple.max():.3f}]")
    minr = min(csv[k].r_multiple.min() for k in csv)
    check("sanity.r_range", minr > -2.0, "; ".join(rng_msgs))
    # 5f 명목 상한 — 계좌 곡선 독립 재구성
    eq_msgs, eq_bad = [], []
    result["equity"] = {}
    for k in ("E0-LS-N55", "E0-LS-ENS", "E1-L-ENS"):
        e, d, p = k.split("-")
        trs = regen[k]
        start = min(int(np.flatnonzero(sigs[n].valid)[0]) for n in PERIODS[p])
        ecsv = pd.read_csv(os.path.join(RES, "equity", f"{k}.csv"))
        out = {}
        for sizing, trim, col in (("risk", True, "equity_risk"), ("fixed", True, "equity_fixed"),
                                  ("risk", False, "equity_risk_hold"), ("fixed", False, "equity_fixed_hold")):
            r_ = equity(trs, daily, start, sizing, trim)
            dev = float(np.max(np.abs(r_["eq"] - ecsv[col].to_numpy()))) if len(r_["eq"]) == len(ecsv) else float("inf")
            jname = {"equity_risk": "risk", "equity_fixed": "fixed", "equity_risk_hold": "risk_hold",
                     "equity_fixed_hold": "fixed_hold"}[col]
            je = jc[k]["equity"][jname]
            out[col] = dict(maxdev=dev, cagr=r_["cagr"], mdd=r_["mdd"], maxratio=r_["maxratio"],
                            json_cagr=je["cagr"], json_mdd=je["max_drawdown"], json_ratio=je.get("max_notional_ratio"))
            if dev > 1e-9 or abs(r_["cagr"] - je["cagr"]) > 1e-9 or abs(r_["mdd"] - je["max_drawdown"]) > 1e-9:
                eq_bad.append((k, col, dev))
        result["equity"][k] = out
        eq_msgs.append(f"{k}: " + ", ".join(f"{c} 최대차 {v['maxdev']:.1e} 명목비(시가) {v['maxratio']:.3f}" for c, v in out.items()))
    check("sanity.equity_curve_indep", not eq_bad, " | ".join(eq_msgs))
    # 위험 기반 명목(진입 시) ≤ 0.2 × 자산 by 구성 — 진입 시 0.005/d_pct 분포
    fr = []
    for k, df in csv.items():
        fl = df[df.status == "filled"]
        frac = 0.005 / (fl.risk_per_unit / fl.entry_price)
        fr.append((k, float(frac.min()), float(frac.max()), int((frac > 0.2).sum())))
    check("sanity.notional_at_entry", all(x[3] >= 0 for x in fr),
          "위험 기반 진입 명목 ÷ 자산 = 0.005 ÷ (R 분모 ÷ 진입가): " + "; ".join(f"{k} [{a:.3f}, {b:.3f}] 상한 0.2 걸린 {c}건" for k, a, b, c in fr))
    # 5g 같은 시각 동시 진입(앙상블)과 최대 동시 포지션
    conc = {}
    for k, df in csv.items():
        fl = df[df.status == "filled"]
        ev = sorted([(t, 1) for t in fl.entry_time_ns] + [(t, -1) for t in fl.exit_time_ns], key=lambda x: (x[0], x[1]))
        cur = mx = 0
        for _, s in ev:
            cur += s; mx = max(mx, cur)
        conc[k] = mx
    check("sanity.max_concurrent_positions", all(v <= (3 if "ENS" in k else 1) for k, v in conc.items()),
          f"최대 동시 포지션 {conc} (앙상블 ≤ 3, 단독 ≤ 1)")
    # 5h 규칙 해석 영향: R 분모에 E0 진입 슬리피지를 넣지 않았다면(RULES §12.2 문자 그대로)
    lit = {}
    for k in ("E0-LS-ENS", "E0-LS-N55", "E0-L-ENS", "E0-L-N55"):
        rl = np.array([r["r_literal"] for r in regen[k] if r["status"] == "filled"])
        lit[k] = (float(rl.mean()), result["combos"][k]["mean_r"])
    check("sanity.r_denominator_literal", all(abs(a - b) < 0.02 for a, b in lit.values()),
          "R 분모에서 E0 진입 슬리피지를 뺀 문자 그대로 평균 R vs 보고: " + "; ".join(f"{k} {a:.4f}/{b:.4f}" for k, (a, b) in lit.items()))
    # 5i 손절 뒤 즉시 재진입 수 (T-2 해석 영향)
    reent = {}
    for k in ("E0-LS-ENS", "E0-L-ENS"):
        rows = [r for r in regen[k] if r["status"] == "filled"]
        cnt = 0; rsum = []
        by = {}
        for r in rows:
            by.setdefault(r["n"], []).append(r)
        for n_, lst in by.items():
            lst.sort(key=lambda r: r["t"])
            for a, b in zip(lst, lst[1:]):
                if a["exit_reason"] == "stop" and a["side"] == b["side"] and b["t"] < (a["exit_signal_day"] or 10**9):
                    cnt += 1; rsum.append(b["r"])
        reent[k] = (cnt, float(np.mean(rsum)) if rsum else None)
    check("sanity.reentry_after_stop", True, "손절 뒤 청산 신호 전 같은 방향 재진입(T-2) 수·평균 R: " +
          "; ".join(f"{k} {c}건 평균 {m:+.3f}" if m is not None else f"{k} 0건" for k, (c, m) in reent.items()))
    result["reentry"] = reent

    result["checks"] = checks
    result["runtime_sec"] = round(time.time() - t0, 1)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    nf = sum(1 for c in checks if not c["passed"])
    print(f"\n점검 {len(checks)}개, 실패 {nf}개, {result['runtime_sec']}s")


if __name__ == "__main__":
    main()
