"""G1 결과 독립 검증 — backtest 패키지를 import 하지 않는다(원자료 + RULES_SPEC v1.0 만).

실행: 저장소 루트에서  python backtest/verify/verify_g1.py   (결과: backtest/verify/VERIFY_REPORT.md, verify_result.json)

1) 거래 CSV 행을 조합·모드별 시드 고정 무작위 5건(없으면 전부)으로 뽑고, 표본이 작아 **전 행**도 함께 검증한다:
   기준봉·마디(A·B·W)·허리 H·신호 시각·진입가·손절·목표·필터(F1~F7)·리스크 검사 → 실행 봉으로 체결·청산·수수료·펀딩·R.
2) G1_REPORT.md ↔ g1_results.json, g1_results.json ↔ 거래 CSV 재계산 (평균 R·PF·거래 수 등).
3) 상식 점검: 무작위 기준선 기대값(달 안 전수 계산) vs −(왕복 비용 ÷ 위험), 실행 가능 ≤ 전체, 손절 폭 밴드, 순손익비 ≥ 1.5,
   포지션 겹침 0, 방해 금지 승인 0(실행 가능), 하루 6건.
+ 후보 수·폐기 사유 수(사유 포함 기준)를 독립 구현으로 다시 세어 엔진과 비교.
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import indep as I  # noqa: E402

ROOT = I.ROOT
RES = ROOT / "backtest" / "results"
OUT_MD = ROOT / "backtest" / "verify" / "VERIFY_REPORT.md"
OUT_JSON = ROOT / "backtest" / "verify" / "verify_result.json"
SEED = 20260930
LAT_NS = 10 * I.MIN_NS

# 허용 오차 (명시)
TOL_PRICE = 1e-6        # 가격(0.1 반올림 뒤) 절대
TOL_MONEY = 1e-6        # 단위당 수수료·슬리피지·펀딩·손익 (USDT) 절대
TOL_R = 1e-9            # R 절대
TOL_META = 1e-6         # A·B·W·H 절대
TOL_STAT = 1e-9         # JSON 통계 ↔ CSV 재계산 (상대)
BAND_EPS = 1e-9         # 손절 폭 밴드 양 끝 포함 판정의 부동소수 오차 (0.1 USDT 격자보다 훨씬 작음)

checks: list[dict] = []
critical: list[str] = []
other: list[str] = []
notes: list[str] = []


def check(name: str, passed: bool, detail: str, is_critical: bool = False):
    checks.append(dict(name=name, passed=bool(passed), detail=detail))
    if not passed:
        (critical if is_critical else other).append(f"{name}: {detail}")


# ---------------------------------------------------------------------------
# 준비
# ---------------------------------------------------------------------------


def prepare():
    t0 = time.time()
    ctx = {}
    bars = {tf: I.load_bars(tf) for tf in ("15m", "1h", "4h", "1d")}
    for tf in ("1h", "4h", "1d"):
        b = bars[tf]
        b.ind = I.compute_indicators(b)
        b.sw = I.swings(b)
        b.madis = I.detect_madis(b, b.ind, b.sw)
        b.traps = I.trap_completions(b, b.sw)
    X = I.load_exec()
    F_ns, F_rate, n_syn = I.load_funding(int(X.close_ns[-1]))
    ctx.update(bars=bars, X=X, F_ns=F_ns, F_rate=F_rate, n_syn=n_syn, load_sec=time.time() - t0)
    return ctx


# ---------------------------------------------------------------------------
# 시나리오 재계산 (§7)
# ---------------------------------------------------------------------------


def f1_allowed(ctx, setting, dfilter, side, decision_ns):
    """§5 방향 필터(D 봉 as-of). 반환 (허용?, 설명)."""
    D = ctx["bars"][I.SETTINGS[setting][1]]
    d = I.asof(D.close_ns, decision_ns)
    if d < 0:
        return False, "D 봉 없음"
    if dfilter == "DB":
        if np.isnan(D.ind["slope120"][d]):
            return False, "D 기울기 120 워밍업"
        s60, s120 = D.ind["slope60"][d], D.ind["slope120"][d]
        ok = (s60 > 0 and s120 > 0) if side > 0 else (s60 < 0 and s120 < 0)
        return bool(ok), f"D={I.ns_iso(D.open_ns[d])} slope60={s60:+.0f} slope120={s120:+.0f}"
    m = I.most_recent_alive(D.madis, d, side)
    if m < 0:
        return False, f"D={I.ns_iso(D.open_ns[d])} 살아 있는 마디 없음"
    H = D.madis.loc[m, "H"]
    ok = D.c[d] > H if side > 0 else D.c[d] < H
    return bool(ok), f"D={I.ns_iso(D.open_ns[d])} 마디 {D.madis.loc[m, 'madi_id']} H={H} close={D.c[d]}"


def fixed_filters(S, s, side, scenario):
    """F2·F4·F5·F6·F7 (§6, 기준 봉 s). 반환 걸린 필터 목록."""
    ind = S.ind
    out = []
    if ind["vr"][s] < 0.7 and ind["atr"][s] <= ind["atr_q20"][s]:
        out.append("F2")
    if ind["spread_on"][s]:
        out.append("F4")
    if ind["surge"][max(s - 5, 0):s].any():
        out.append("F5")
    tc = S.traps
    if int(((tc >= s - 48) & (tc <= s - 1)).sum()) >= 2:
        out.append("F6")
    if scenario != "S2":
        if I.most_recent_alive(S.madis, s, -side) >= 0:
            out.append("F7")
    return out


def risk_fails(S, s, side, order_type, entry, stop, target):
    """§8.1·§12.2 손절 폭·순손익비 (계획가, 기본 비용)."""
    atr = S.ind["atr"][s]
    fe = I.MAKER if order_type == "limit" else I.TAKER
    d = abs(entry - stop)
    out = []
    lo, hi = max(0.004 * entry, atr), min(0.02 * entry, 3 * atr)
    if not (lo - BAND_EPS <= d <= hi + BAND_EPS):          # 양 끝 포함, 부동소수 오차만 허용
        out.append("RISK_STOP_BAND")
    rr = (abs(target - entry) - fe * entry - I.MAKER * target) / (d + fe * entry + (I.TAKER + I.SLIP) * stop)
    if rr < 1.5:
        out.append("RISK_RR")
    return out, rr, d / entry, atr


def l1b_event(S, C, m):
    """§7.2 준비 → 확인. 마디당 준비 1회(I-22). 반환 dict 또는 None."""
    tb, end, H, W = int(m.tb), int(m.end), m.H, m.W
    ka = None
    for k in range(tb + 1, end + 1):
        if H <= S.l[k] <= H + 0.25 * W:
            ka = k
            break
    if ka is None:
        return None
    arm_close = int(S.close_ns[ka])
    below = [k for k in range(ka + 1, min(end, ka + 24) + 1) if S.c[k] < H]
    kill_ns = int(S.close_ns[below[1]]) if len(below) >= 2 else 2**62
    dur = I.TF_NS[S.tf]
    c_lo = int(np.searchsorted(C.close_ns, arm_close, "right"))
    c_hi = int(np.searchsorted(C.close_ns, arm_close + 24 * dur, "right"))
    for c in range(c_lo, c_hi):
        cc = int(C.close_ns[c])
        if cc > kill_ns:
            return None
        k_last = I.asof(S.close_ns, cc + I.AVAIL_NS)
        if k_last > end:
            return None
        if C.c[c] > C.o[c] and C.c[c] > C.h[c - 1] and C.c[c] > H:
            lo_i = int(np.searchsorted(C.open_ns, S.close_ns[tb], "left"))
            lowest = float(C.l[lo_i:c + 1].min())                       # I-23 T_B 이후 최저가(C 봉)
            return dict(ka=ka, c=c, k_last=k_last, signal_ns=cc, lowest=lowest)
    return None


def plan_for(ctx, setting, scenario, m, t=None):
    """마디 m(행)과 신호 봉 t로 계획을 만든다. 반환 dict(signal_ns, s, entry, stop, target, order_type,
    valid_until, cancel_eff, sc_reasons, extra) 또는 None."""
    S_tf, _, C_tf = I.SETTINGS[setting]
    S, C = ctx["bars"][S_tf], ctx["bars"][C_tf]
    dur = I.TF_NS[S_tf]
    atr, buf = S.ind["atr"], 0.1 * S.ind["atr"]
    sc = []
    if scenario == "L1a":
        t = int(m.tb)
        H, A, W, B = m.H, m.A, m.W, m.B
        if not S.c[t] > H:
            sc.append("SC_CLOSE_VS_WAIST")
        if S.c[t] < S.c[t - 60]:
            sc.append("SC_SLOPE60")
        if S.v[int(m.b) + 1:t + 1].mean() >= m.vol_ab:
            sc.append("SC_UNHEALTHY")
        entry, stop, target = H, I.rnd(A - buf[t]), I.rnd(H + W)
        cancel_k = None
        for k in range(t + 1, min(t + 24, S.n - 1) + 1):
            if S.c[k] < A or S.h[k] > B + 0.5 * W or S.v[int(m.b) + 1:k + 1].mean() >= m.vol_ab:
                cancel_k = k
                break
        return dict(signal_ns=int(S.close_ns[t]), s=t, entry=entry, stop=stop, target=target, order_type="limit",
                    side=1, valid_until=int(S.close_ns[t]) + 24 * dur,
                    cancel_eff=None if cancel_k is None else int(S.close_ns[cancel_k]) + I.AVAIL_NS, sc=sc)
    if scenario == "L1b":
        ev = l1b_event(S, C, m)
        if ev is None:
            return None
        k = ev["k_last"]
        if S.v[int(m.b) + 1:k + 1].mean() >= m.vol_ab:
            sc.append("SC_UNHEALTHY")
        cap = I.rnd(C.c[ev["c"]] * 1.001)
        stop = I.rnd(min(ev["lowest"], m.H) - buf[k])
        target = I.rnd(ev["lowest"] + m.W)
        if not (stop < cap < target):
            sc.append("SC_BAD_GEOMETRY")
        return dict(signal_ns=ev["signal_ns"], s=k, entry=cap, stop=stop, target=target, order_type="ioc_cap",
                    side=1, valid_until=ev["signal_ns"] + I.AVAIL_NS + LAT_NS, cancel_eff=None, sc=sc, extra=ev)
    if scenario == "S2":
        H, A, B = m.H, m.A, m.B
        entry = H
        stop = I.rnd(max(S.h[t], H + 0.5 * atr[t]) + buf[t])
        target = I.rnd(A)
        if not (target < entry < stop):
            sc.append("SC_BAD_GEOMETRY")
        cancel_k = None
        for k in range(t + 1, min(t + 12, S.n - 1) + 1):
            if S.c[k] > B:
                cancel_k = k
                break
        return dict(signal_ns=int(S.close_ns[t]), s=t, entry=entry, stop=stop, target=target, order_type="limit",
                    side=-1, valid_until=int(S.close_ns[t]) + 12 * dur,
                    cancel_eff=None if cancel_k is None else int(S.close_ns[cancel_k]) + I.AVAIL_NS, sc=sc)
    raise ValueError(scenario)


def s2_paint(S):
    """봉 t마다 tb < t 이고 살아 있는 가장 최근 상승 마디 행(I-24)."""
    arr = np.full(S.n, -1, np.int64)
    md = S.madis
    for r in md.index[md.direction == 1]:
        tb, end = int(md.at[r, "tb"]), int(md.at[r, "end"])
        arr[tb + 1:end + 1] = r
    return arr


def s3_candidates(S):
    """§7.4 지지선·이탈 후보(I-25 해석) — 수와 RR 미달 비율 교차 확인용."""
    n = S.n
    sl = S.sw["sl_idx"]
    out = []
    lows_conf_sorted = []  # (확정 시점 순서로 추가) 목표 탐색용
    conf_ptr = 0
    conf_lows = []
    for t in range(n):
        while conf_ptr < len(sl) and sl[conf_ptr] + 3 <= t:
            conf_lows.append(S.l[sl[conf_ptr]])
            conf_ptr += 1
        lo_w = max(t - 100, 0)
        cand = sl[(sl >= lo_w) & (sl <= t - 3)]
        sup = -1
        for i in cand[::-1]:
            L = S.l[i]
            if int((np.abs(S.l[lo_w:t] - L) <= 0.001 * L).sum()) >= 2:
                sup = int(i)
                break
        if sup < 0:
            continue
        Sp = S.l[sup]
        if not S.c[t] < Sp:
            continue
        nprev = int((S.c[max(t - 9, 0):t] < Sp).sum())
        vr = S.ind["vr"][t]
        if not ((vr >= 2) or nprev == 1):
            continue
        below = [x for x in conf_lows if x < Sp]
        tgt = max(below) if below else None
        out.append((t, sup, Sp, tgt))
    return out


# ---------------------------------------------------------------------------
# 1) 후보 수·사유 교차 확인
# ---------------------------------------------------------------------------


def candidate_reasons(ctx, setting, dfilter, scenario):
    """조합 하나의 후보 목록과 사유(F8·F9·마스크 제외)를 독립 계산."""
    S_tf, _, C_tf = I.SETTINGS[setting]
    S, C = ctx["bars"][S_tf], ctx["bars"][C_tf]
    md = S.madis
    res = []
    if scenario in ("L1a", "L1b"):
        for r in md.index[md.direction == 1]:
            m = md.loc[r]
            p = plan_for(ctx, setting, scenario, m)
            if p is None:
                continue
            res.append((m, p))
        side = 1
    elif scenario == "S2":
        paint = s2_paint(S)
        for t in range(S.n):
            r = paint[t]
            if r < 0:
                continue
            m = md.loc[r]
            if S.c[t] < S.o[t] and S.ind["vr"][t] >= 2 and S.c[t] < m.H:
                res.append((m, plan_for(ctx, setting, "S2", m, t)))
        side = -1
    else:
        side = -1
        for t, sup, Sp, tgt in s3_candidates(S):
            sc = []
            ups = md[(md.direction == 1) & (md.tb <= t)]
            if len(ups) and not S.c[t] < ups.iloc[-1].H:
                sc.append("SC_CLOSE_VS_WAIST")
            if tgt is None:
                sc.append("SC_NO_TARGET")
            p = dict(signal_ns=int(S.close_ns[t]), s=t, entry=I.rnd(Sp), stop=I.rnd(Sp + S.ind["atr"][t]),
                     target=None if tgt is None else I.rnd(tgt), order_type="limit", side=-1, sc=sc)
            if tgt is not None and not (p["target"] < p["entry"] < p["stop"]):
                sc.append("SC_BAD_GEOMETRY")
            res.append((None, p))
    counts = Counter()
    for m, p in res:
        s = p["s"]
        reasons = []
        if not S.ind["valid"][s]:
            counts["WARMUP"] += 1
            continue
        reasons += p["sc"]
        ok, _ = f1_allowed(ctx, setting, dfilter, side, p["signal_ns"] + I.AVAIL_NS)
        if not ok:
            reasons.append("F1")
        reasons += fixed_filters(S, s, side, scenario)
        if p.get("target") is not None:
            reasons += risk_fails(S, s, side, p["order_type"], p["entry"], p["stop"], p["target"])[0]
        for x in set(reasons):
            counts[x] += 1
    return len(res), counts


# ---------------------------------------------------------------------------
# 2) 거래 행 검증
# ---------------------------------------------------------------------------


def verify_row(ctx, row, setting, dfilter):
    """거래 CSV 한 행 → (불일치 목록, 기록 dict)."""
    S_tf = I.SETTINGS[setting][0]
    S = ctx["bars"][S_tf]
    X = ctx["X"]
    scen = row["scenario"]
    meta = json.loads(row["meta"])
    mism = []
    rec = dict(key=row["key"], plan_id=row["plan_id"], status=row["status"], r_eng=float(row["r_multiple"])
               if row["status"] == "filled" else None)
    md = S.madis
    hit = md.index[(md.madi_id == row["madi_id"])]
    if len(hit) != 1:
        return [f"마디 {row['madi_id']} 를 독립 구현에서 찾지 못함"], rec
    m = md.loc[hit[0]]
    # 구조 (§4.1~§4.3)
    for k_meta, v in (("A", m.A), ("B", m.B), ("W", m.W), ("H", m.H)):
        if abs(float(meta[k_meta]) - v) > TOL_META:
            mism.append(f"{k_meta}: 엔진 {meta[k_meta]} vs 독립 {v}")
    if bool(meta.get("waist_fallback")) != bool(m.fallback):
        mism.append(f"waist_fallback: 엔진 {meta.get('waist_fallback')} vs 독립 {m.fallback}")
    if int(meta.get("tb_close_ns", m.tb_close_ns)) != m.tb_close_ns:
        mism.append("T_B 시각 불일치")
    rec.update(kijun=I.ns_iso(S.open_ns[int(m.kijun)]), A=m.A, B=m.B, W=m.W, H=m.H,
               early_swing_ambiguity=bool(m.early_swing_before_b))
    sig_ns = I.iso_ns(row["signal_time"])
    if scen == "S2":
        t = int(np.searchsorted(S.close_ns, sig_ns))
        if t >= S.n or S.close_ns[t] != sig_ns:
            return mism + ["S2 신호 봉을 찾지 못함"], rec
        if ("paint", setting) not in ctx:
            ctx[("paint", setting)] = s2_paint(S)
        paint = ctx[("paint", setting)]
        if paint[t] != hit[0]:
            mism.append(f"S2 근거 마디: 독립 구현의 가장 최근 살아 있는 상승 마디 = "
                        f"{md.loc[paint[t], 'madi_id'] if paint[t] >= 0 else '없음'}")
        if not (S.c[t] < S.o[t] and S.ind["vr"][t] >= 2 and S.c[t] < m.H):
            mism.append("S2 준비 조건(음봉·VR≥2·종가<H) 불성립")
        p = plan_for(ctx, setting, "S2", m, t)
    else:
        p = plan_for(ctx, setting, scen, m)
        if p is None:
            return mism + [f"{scen} 신호가 독립 구현에서 나오지 않음"], rec
    if p["signal_ns"] != sig_ns:
        mism.append(f"신호 시각: 엔진 {row['signal_time']} vs 독립 {I.ns_iso(p['signal_ns'])}")
    if p["sc"]:
        mism.append(f"시나리오 조건 위반: {p['sc']}")
    if scen == "L1b":
        if abs(meta["lowest"] - p["extra"]["lowest"]) > TOL_META:
            mism.append(f"L1b lowest: 엔진 {meta['lowest']} vs 독립 {p['extra']['lowest']}")
        if int(meta["k_last"]) != p["s"]:
            mism.append("L1b k_last 불일치")
    for col, v in (("plan_entry", p["entry"]), ("stop", p["stop"]), ("target", p["target"])):
        if abs(float(row[col]) - v) > TOL_PRICE:
            mism.append(f"{col}: 엔진 {row[col]} vs 독립 {v}")
    # 필터·리스크 (통과한 계획이므로 모두 비어 있어야)
    side = int(row["side"])
    ok, why = f1_allowed(ctx, setting, dfilter, side, sig_ns + I.AVAIL_NS)
    if not ok:
        mism.append(f"F1 방향 필터 불허: {why}")
    ff = fixed_filters(S, p["s"], side, scen)
    if ff:
        mism.append(f"고정 필터 걸림: {ff}")
    rf, rr, dpct, atr = risk_fails(S, p["s"], side, p["order_type"], p["entry"], p["stop"], p["target"])
    if rf:
        mism.append(f"리스크 검사 실패: {rf} (d%={dpct:.4%}, atr={atr:.2f}, rr={rr:.3f})")
    rec.update(net_rr=rr, d_pct=dpct, atr=atr, band_lo=max(0.004, atr / p["entry"]),
               band_hi=min(0.02, 3 * atr / p["entry"]))
    if abs(meta.get("net_rr", rr) - rr) > 1e-9:
        mism.append(f"net_rr: 엔진 {meta.get('net_rr')} vs 독립 {rr}")
    # 시각
    appr, act = sig_ns + I.AVAIL_NS, sig_ns + I.AVAIL_NS + LAT_NS
    if I.iso_ns(row["approval_time"]) != appr or I.iso_ns(row["active_from"]) != act:
        mism.append("승인·활성 시각 불일치")
    # 체결 (§12.1·§12.2)
    order_end = p["valid_until"] if p["cancel_eff"] is None else min(p["valid_until"], p["cancel_eff"])
    canc = p["cancel_eff"] is not None and p["cancel_eff"] < p["valid_until"]
    sim = I.simulate(X, ctx["F_ns"], ctx["F_rate"], side, p["order_type"], p["entry"], p["stop"], p["target"],
                     act, order_end, canc, 72 * I.TF_NS[S_tf])
    sim_spec = I.simulate(X, ctx["F_ns"], ctx["F_rate"], side, p["order_type"], p["entry"], p["stop"],
                          p["target"], act, order_end, canc, 72 * I.TF_NS[S_tf], funding_start_mode="spec")
    rec.update(sim=sim)
    if sim.status != row["status"]:
        mism.append(f"status: 엔진 {row['status']} vs 독립 {sim.status}")
    if I.iso_ns(row["busy_until"]) != sim.busy_until:
        mism.append(f"busy_until: 엔진 {row['busy_until']} vs 독립 {I.ns_iso(sim.busy_until)}")
    if sim.status == "filled" and row["status"] == "filled":
        cmp = [("entry_time", I.iso_ns(row["entry_time"]), int(X.open_ns[sim.entry_j]), 0),
               ("entry_price", float(row["entry_price"]), sim.entry_price, TOL_PRICE),
               ("exit_time", I.iso_ns(row["exit_time"]), int(X.open_ns[sim.exit_j]), 0),
               ("exit_price", float(row["exit_price"]), sim.exit_price, TOL_PRICE),
               ("fees", float(row["fees"]), sim.fees, TOL_MONEY),
               ("slippage", float(row["slippage"]), sim.slippage, TOL_MONEY),
               ("funding", float(row["funding"]), sim.funding, TOL_MONEY),
               ("gross_pnl", float(row["gross_pnl"]), sim.gross, TOL_MONEY),
               ("net_pnl", float(row["net_pnl"]), sim.net, TOL_MONEY),
               ("r_multiple", float(row["r_multiple"]), sim.r, TOL_R),
               ("risk_per_unit", float(row["risk_per_unit"]), sim.risk, TOL_MONEY)]
        for name, a, b, tol in cmp:
            if not abs(a - b) <= tol:
                mism.append(f"{name}: 엔진 {a} vs 독립 {b}")
        if row["exit_reason"] != sim.exit_reason:
            mism.append(f"exit_reason: 엔진 {row['exit_reason']} vs 독립 {sim.exit_reason}")
        rec.update(funding_spec_diff_r=(sim_spec.r - sim.r))
    return mism, rec


def truncated_ctx(ctx, setting, signal_ns):
    """신호 시각(판단 = +60초)까지 알 수 있는 봉만 남긴 문맥 (미래 참조 점검용)."""
    S_tf, D_tf, C_tf = I.SETTINGS[setting]
    decision = signal_ns + I.AVAIL_NS
    new = dict(ctx)
    new["bars"] = dict(ctx["bars"])
    for tf in (S_tf, D_tf, C_tf):
        b = ctx["bars"][tf]
        k = int(np.searchsorted(b.close_ns + I.AVAIL_NS, decision, "right"))   # close + 60초 ≤ 판단 시각
        tb = I.Bars(tf, b.open_ns[:k], b.close_ns[:k], b.o[:k], b.h[:k], b.l[:k], b.c[:k], b.v[:k])
        if tf != C_tf:
            tb.ind = I.compute_indicators(tb)
            tb.sw = I.swings(tb)
            tb.madis = I.detect_madis(tb, tb.ind, tb.sw)
            if tf == S_tf:
                tb.traps = I.trap_completions(tb, tb.sw)
        new["bars"][tf] = tb
    return new


def verify_truncated(ctx, row, setting, dfilter):
    """미래 참조 점검: 신호 시각까지의 데이터만으로 같은 신호·계획·필터 통과가 나오는가."""
    sig_ns = I.iso_ns(row["signal_time"])
    T = truncated_ctx(ctx, setting, sig_ns)
    S = T["bars"][I.SETTINGS[setting][0]]
    md = S.madis
    hit = md.index[md.madi_id == row["madi_id"]]
    if len(hit) != 1:
        return ["자른 데이터에서 근거 마디 없음"]
    m = md.loc[hit[0]]
    scen = row["scenario"]
    if scen == "S2":
        t = S.n - 1
        if S.close_ns[t] != sig_ns:
            return ["자른 데이터의 마지막 봉 ≠ 신호 봉"]
        if s2_paint(S)[t] != hit[0]:
            return ["자른 데이터에서 S2 근거 마디가 다름"]
        p = plan_for(T, setting, "S2", m, t)
    else:
        p = plan_for(T, setting, scen, m)
        if p is None:
            return ["자른 데이터에서 신호 없음"]
    out = []
    if p["signal_ns"] != sig_ns:
        out.append("신호 시각 다름")
    if p["sc"]:
        out.append(f"시나리오 조건 {p['sc']}")
    for col, v in (("plan_entry", p["entry"]), ("stop", p["stop"]), ("target", p["target"])):
        if abs(float(row[col]) - v) > TOL_PRICE:
            out.append(f"{col} 다름")
    side = int(row["side"])
    if not f1_allowed(T, setting, dfilter, side, sig_ns + I.AVAIL_NS)[0]:
        out.append("F1")
    out += fixed_filters(S, p["s"], side, scen)
    out += risk_fails(S, p["s"], side, p["order_type"], p["entry"], p["stop"], p["target"])[0]
    meta = json.loads(row["meta"])
    for k_meta in ("A", "B", "W", "H"):
        if abs(float(meta[k_meta]) - float(m[k_meta])) > TOL_META:
            out.append(f"{k_meta} 다름")
    return out


# ---------------------------------------------------------------------------
# 통계 도우미
# ---------------------------------------------------------------------------


def pf_of(r):
    pos, neg = r[r > 0].sum(), -r[r < 0].sum()
    if neg == 0:
        return math.inf if pos > 0 else None
    return pos / neg


def jnum(x):
    if x is None:
        return None
    if isinstance(x, str):
        return {"inf": math.inf, "-inf": -math.inf}.get(x, None)
    return float(x)


def close(a, b, tol=TOL_STAT):
    if a is None or b is None:
        return a is None and b is None
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# ---------------------------------------------------------------------------
# 무작위 기준선 기대값 (달 안 전수)
# ---------------------------------------------------------------------------


def random_expectation(ctx, setting, trades):
    """실행 가능 체결 거래마다 같은 달 모든 S 봉 마감에서 시장가 진입 → 청산. 반복 평균의 기대값을 전수로 구한다."""
    S_tf = I.SETTINGS[setting][0]
    S = ctx["bars"][S_tf]
    X = ctx["X"]
    per_trade = []
    for _, tr in trades.iterrows():
        side = int(tr["side"])
        e = float(tr["entry_price"])
        sp, tp = abs(e - float(tr["stop"])) / e, abs(float(tr["target"]) - e) / e
        et = pd.Timestamp(tr["entry_time"])
        m0 = pd.Timestamp(year=et.year, month=et.month, day=1, tz="UTC").value
        m1 = (pd.Timestamp(year=et.year, month=et.month, day=1, tz="UTC") + pd.offsets.MonthBegin(1)).value
        idx = np.flatnonzero((S.close_ns >= m0) & (S.close_ns < m1))
        rs, costs, gross = [], [], []
        for k in idx:
            act = int(S.close_ns[k]) + I.AVAIL_NS + LAT_NS
            j0 = int(np.searchsorted(X.open_ns, act, "left"))
            if j0 >= X.n:
                continue
            px = float(X.o[j0])
            stop, target = I.rnd(px * (1 - side * sp)), I.rnd(px * (1 + side * tp))
            sim = I.simulate(X, ctx["F_ns"], ctx["F_rate"], side, "market", px, stop, target, act, act, False,
                             72 * I.TF_NS[S_tf])
            rs.append(sim.r)
            costs.append((sim.fees + sim.slippage + sim.funding) / sim.risk)
            gross.append(sim.gross / sim.risk)
        per_trade.append(dict(mean_r=float(np.mean(rs)), cost_r=float(np.mean(costs)), gross_r=float(np.mean(gross)),
                              n_draws=len(rs), sp=sp))
    return per_trade


# ---------------------------------------------------------------------------
# 보고서 표 파서
# ---------------------------------------------------------------------------


def md_tables(text):
    """마크다운 표를 (앞 제목줄 목록, 행 목록) 으로."""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-:| ]+\|$", lines[i + 1]):
            head = [c.strip() for c in lines[i].strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append([c.strip() for c in lines[j].strip("|").split("|")])
                j += 1
            ctx_line = next((lines[k] for k in range(i - 1, -1, -1) if lines[k].strip()), "")
            out.append(dict(head=head, rows=rows, before=ctx_line))
            i = j
        else:
            i += 1
    return out


def cell_num(s):
    s = s.replace("*", "").replace(",", "").replace("건", "").strip()
    if s in ("–", "-", ""):
        return None
    if s == "∞":
        return math.inf
    s = s.replace("%", "")
    m = re.match(r"^([+-]?\d+(\.\d+)?)", s)
    return float(m.group(1)) if m else None


def approx_cell(cell, val, decimals, pct=False):
    """보고서 칸(반올림된 표시) ↔ JSON 값. 표시 자릿수의 반 + 여유."""
    got = cell_num(cell)
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return got is None
    if isinstance(val, float) and math.isinf(val):
        return got == math.inf
    if got is None:
        return False
    v = val * 100 if pct else val
    return abs(got - v) <= 0.5 * 10 ** (-decimals) + 1e-9


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def main():
    t_start = time.time()
    J = json.loads((RES / "g1_results.json").read_text())
    report_md = (RES / "G1_REPORT.md").read_text()
    global ctx_X
    ctx = prepare()
    X = ctx["X"]
    ctx_X = X
    info = dict(load_sec=round(ctx["load_sec"], 1), n_exec_bars=X.n, n_funding_synthetic=ctx["n_syn"])
    check("데이터: 실행 봉 수·대체 펀딩 수", X.n == J["data"]["exec_bars"]["n"] and ctx["n_syn"] == J["data"]["funding_n_synthetic"],
          f"독립 {X.n:,}봉 / 대체 펀딩 {ctx['n_syn']}개 vs JSON {J['data']['exec_bars']['n']:,} / "
          f"{J['data']['funding_n_synthetic']}")

    # ---------------- 1) 후보 수·사유 교차 확인 ----------------
    cand_rows = []
    combos = [c["key"] for c in J["combos"]]
    for key in combos:
        scen, dfl, setting = key.split("-")
        n_c, cnt = candidate_reasons(ctx, setting, dfl, scen)
        cj = next(c for c in J["combos"] if c["key"] == key)["exec"]
        eng_any = cj["discard_any_reason"]
        diffs = {}
        for rsn in ("WARMUP", "SC_CLOSE_VS_WAIST", "SC_SLOPE60", "SC_UNHEALTHY", "SC_NO_TARGET", "SC_BAD_GEOMETRY",
                    "F1", "F2", "F4", "F5", "F6", "F7", "RISK_STOP_BAND", "RISK_RR"):
            if cnt.get(rsn, 0) != eng_any.get(rsn, 0):
                diffs[rsn] = (eng_any.get(rsn, 0), cnt.get(rsn, 0))
        cand_rows.append(dict(key=key, eng_n=cj["n_candidates"], ind_n=n_c, diffs=diffs))
    n_match = sum(r["eng_n"] == r["ind_n"] for r in cand_rows)
    n_reason_match = sum(not r["diffs"] for r in cand_rows)
    check("후보 수 (독립 재계산)", n_match == len(cand_rows),
          f"{n_match}/{len(cand_rows)} 조합 일치" + "".join(
              f"; {r['key']} 엔진 {r['eng_n']} vs 독립 {r['ind_n']}" for r in cand_rows if r["eng_n"] != r["ind_n"]))
    check("폐기 사유 수(사유 포함 기준, F8·F9·마스크 제외)", n_reason_match == len(cand_rows),
          f"{n_reason_match}/{len(cand_rows)} 조합 완전 일치" + "".join(
              f"; {r['key']} " + ", ".join(f"{k} 엔진 {a} vs 독립 {b}" for k, (a, b) in r["diffs"].items())
              for r in cand_rows if r["diffs"]))

    # ---------------- 2) 거래 행 검증 ----------------
    rng = np.random.default_rng(SEED)
    row_results = []
    sampled_ids = []
    all_csv = {}
    for f in sorted((RES / "trades").glob("*.csv")):
        df = pd.read_csv(f)
        all_csv[f.stem] = df
        if len(df):
            take = rng.choice(len(df), size=min(5, len(df)), replace=False)
            sampled_ids += [(f.stem, int(i)) for i in sorted(take)]
    for stem, df in all_csv.items():
        combo = stem.rsplit("_", 1)[0]
        scen, dfl, setting = combo.split("-")
        for i, row in df.iterrows():
            mism, rec = verify_row(ctx, row, setting, dfl)
            rec.update(file=stem, row=i, mism=mism, sampled=(stem, i) in sampled_ids)
            row_results.append(rec)
    n_rows = len(row_results)
    n_bad = sum(bool(r["mism"]) for r in row_results)
    n_sampled = sum(r["sampled"] for r in row_results)
    n_s_bad = sum(bool(r["mism"]) for r in row_results if r["sampled"])
    n_filled = sum(r["status"] == "filled" for r in row_results)
    check("표본 거래 재계산 (조합·모드별 시드 고정 5건)", n_s_bad == 0 and n_sampled >= 20,
          f"표본 {n_sampled}행 (시드 {SEED}) 중 불일치 {n_s_bad}행", is_critical=n_s_bad > 0)
    check("전 행 재계산 (모든 거래 CSV 행)", n_bad == 0,
          f"{n_rows}행(체결 {n_filled}) 중 불일치 {n_bad}행" + "".join(
              f"; {r['file']}#{r['row']}: {'; '.join(r['mism'][:3])}" for r in row_results if r["mism"])[:1500],
          is_critical=n_bad > 0)

    # 미래 참조: 신호 시각에서 자른 데이터로 다시 (신호마다 한 번)
    seen_sig, la_bad = {}, []
    for stem, df in all_csv.items():
        combo = stem.rsplit("_", 1)[0]
        scen, dfl, setting = combo.split("-")
        for _, row in df.iterrows():
            key = (combo, row["plan_id"])
            if key in seen_sig:
                continue
            seen_sig[key] = verify_truncated(ctx, row, setting, dfl)
            if seen_sig[key]:
                la_bad.append(f"{combo} {row['plan_id']}: {seen_sig[key]}")
    check("미래 참조 없음: 신호 시각까지 자른 데이터로 재계산해도 같은 신호·계획·필터 통과", not la_bad,
          f"고유 신호 {len(seen_sig)}개 검사, 불일치 {len(la_bad)}" + ("" if not la_bad else ": " + "; ".join(la_bad[:5])),
          is_critical=bool(la_bad))
    # 애매한 해석의 영향 (거래 근거 마디)
    amb_early, amb_width, dh = set(), set(), []
    for r in row_results:
        if r.get("early_swing_ambiguity"):
            amb_early.add(r["plan_id"])
    for (setting, tf) in (("P1", "1h"), ("P2", "4h")):
        b = ctx["bars"][tf]
        md = b.madis
        used = {row["madi_id"] for stem, df in all_csv.items() if stem.split("-")[2].startswith(setting)
                for _, row in df.iterrows()}
        for _, m in md[md.madi_id.isin(used)].iterrows():
            h2, _ = I.waist(b, int(m.a), int(m.b), m.A, m.W, int(m.direction), width_mode="mid")
            if abs(h2 - m.H) > 1e-9:
                amb_width.add(m.madi_id)
                dh.append((abs(h2 - m.H) / m.H, abs(h2 - m.H) / m.W))
    n_md = {tf: len(ctx["bars"][tf].madis) for tf in ("1h", "4h")}
    n_early = {tf: int(sum(len(x) > 0 for x in ctx["bars"][tf].madis.early_swing_before_b)) for tf in ("1h", "4h")}
    EXTRA_NOTES.append(f"애매함 ①(§4.2 B '기준봉 이후 처음 확정되는 스윙 고점'): 기준봉 직전 봉(t−2, t−1)의 스윙이 기준봉 뒤에 "
                       f"확정되는 마디는 1h {n_early['1h']}/{n_md['1h']}개, 4h {n_early['4h']}/{n_md['4h']}개. "
                       f"거래 CSV 계획 중 해당: {len(amb_early)}개 → B 해석(B 봉 ≥ 기준봉, I-8)은 거래 결과에 영향 없음.")
    EXTRA_NOTES.append(f"애매함 ②(§4.3 칸 폭 '가격 × 0.001'의 가격): A 쪽 구간 끝(I-13) 대신 구간 가운데 가격으로 폭을 잡으면 "
                       f"거래 근거 마디 {len(amb_width)}개의 허리 H가 움직인다(칸 경계가 밀림): 가격 대비 중앙값 "
                       f"{np.median([x[0] for x in dh]) if dh else 0:.3%}, 최대 {max(x[0] for x in dh) if dh else 0:.3%} "
                       f"(W 대비 최대 {max(x[1] for x in dh) if dh else 0:.1%}; 큰 경우는 최빈 칸 자체가 바뀜). 명세 문장은 칸 폭의 "
                       "기준 가격을 정하지 않았고 엔진·검증 모두 A 쪽 끝 가격(I-13)을 썼다 — 엔진 오류는 아니지만 허리 정의가 "
                       "칸 나누기에 민감하다는 명세 수준의 취약점(v2에서 고정 권장). 전 조합이 거래 30건 미만 보류라 판정은 바뀌지 않음.")

    # ---------------- 3) JSON ↔ CSV ----------------
    jc_bad = []
    for c in J["combos"]:
        for mode in ("all", "exec"):
            df = all_csv[f"{c['key']}_{mode}"]
            s = c[mode]
            fl = df[df.status == "filled"]
            r = fl["r_multiple"].to_numpy(float)
            yrs = pd.to_datetime(fl["entry_time"]).dt.year.to_numpy() if len(fl) else np.array([])
            exp = dict(n=len(fl), n_passed=len(df), n_long=int((fl.side > 0).sum()), n_short=int((fl.side < 0).sum()),
                       mean_r=float(r.mean()) if len(r) else None,
                       median_r=float(np.median(r)) if len(r) else None,
                       std_r=float(r.std(ddof=1)) if len(r) >= 2 else None,
                       win_rate=float((r > 0).mean()) if len(r) else None, pf=pf_of(r) if len(r) else None,
                       total_r=float(r.sum()) if len(r) else None)
            for k, v in exp.items():
                got = jnum(s.get(k)) if k not in ("n", "n_passed", "n_long", "n_short") else s.get(k)
                if k == "total_r" and v is None and got in (None, 0.0):
                    continue
                if k == "pf" and not len(r):
                    continue
                if not close(got, v):
                    jc_bad.append(f"{c['key']}/{mode} {k}: JSON {got} vs CSV {v}")
            for st in ("filled", "cancelled", "expired", "not_filled"):
                if s["status_counts"].get(st, 0) != int((df.status == st).sum()):
                    jc_bad.append(f"{c['key']}/{mode} status {st}")
            for ex in ("stop", "target", "time", "eod"):
                if s["exit_counts"].get(ex, 0) != int((fl.exit_reason == ex).sum()):
                    jc_bad.append(f"{c['key']}/{mode} exit {ex}")
            pos_years = 0
            for y in range(2020, 2027):
                ry = r[yrs == y] if len(r) else np.array([])
                v = float(ry.mean()) if len(ry) else None
                if not close(jnum(s["yearly"].get(str(y))), v):
                    jc_bad.append(f"{c['key']}/{mode} yearly {y}")
                pos_years += int(v is not None and v > 0)
            if s["positive_years"] != pos_years:
                jc_bad.append(f"{c['key']}/{mode} positive_years")
            if len(r) >= 2:
                sh = r.mean() / r.std(ddof=1)
                if not close(jnum(s["sharpe"]), float(sh)):
                    jc_bad.append(f"{c['key']}/{mode} sharpe")
        # 비용 2배 (독립 시뮬 r_cost2, 지불 펀딩만 2배)
        ex_rows = [x for x in row_results if x["file"] == f"{c['key']}_exec" and x["status"] == "filled"]
        if ex_rows:
            r2 = np.array([x["sim"].r_cost2 for x in ex_rows])
            if not close(jnum(c["exec_cost2"]["mean_r"]), float(r2.mean()), 1e-9):
                jc_bad.append(f"{c['key']} exec_cost2.mean_r JSON {c['exec_cost2']['mean_r']} vs 독립 {r2.mean()}")
            if not close(jnum(c["exec_cost2"]["pf"]), pf_of(r2), 1e-9):
                jc_bad.append(f"{c['key']} exec_cost2.pf")
        # 무작위 분포 요약 ↔ means 목록
        rd = c["random"]
        if rd.get("means"):
            mm = np.array(rd["means"], float)
            if len(mm) != J["params"]["random_reps"] or not close(rd["mean"], float(mm.mean())) \
                    or not close(rd["p95"], float(np.quantile(mm, 0.95))) \
                    or not close(rd["p05"], float(np.quantile(mm, 0.05))):
                jc_bad.append(f"{c['key']} random 요약 ↔ means 불일치")
        # 판정 재계산 (§8.3)
        e = c["exec"]
        n = e["n"]
        mean = jnum(e["mean_r"])
        cond = dict(c1_mean_r=mean is not None and mean >= 0.15,
                    c2_boot_lo=jnum(e["boot_lo"]) is not None and jnum(e["boot_lo"]) > 0,
                    c3_pf=jnum(e["pf"]) is not None and jnum(e["pf"]) >= 1.2,
                    c4_cost2=jnum(c["exec_cost2"]["mean_r"]) is not None and jnum(c["exec_cost2"]["mean_r"]) > 0,
                    c5_random=mean is not None and rd.get("p95") is not None and mean > rd["p95"],
                    c6_years=e["positive_years"] >= 4, c7_enough_trades=n >= 30)
        result = "pending" if n < 30 else ("pass" if all(v for k, v in cond.items() if k != "c7_enough_trades")
                                           else "fail")
        for k, v in cond.items():
            if c["verdict"][k] != v:
                jc_bad.append(f"{c['key']} verdict {k}: JSON {c['verdict'][k]} vs 재계산 {v}")
        if c["verdict"]["result"] != result:
            jc_bad.append(f"{c['key']} verdict result: JSON {c['verdict']['result']} vs 재계산 {result}")
    # 부트스트랩 하한 (근사: 독립 시드)
    boot_diff = []
    brng = np.random.default_rng(SEED + 1)
    for c in J["combos"]:
        df = all_csv[f"{c['key']}_exec"]
        r = df[df.status == "filled"]["r_multiple"].to_numpy(float)
        if len(r):
            bm = r[brng.integers(0, len(r), size=(10000, len(r)))].mean(axis=1)
            boot_diff.append((c["key"], jnum(c["exec"]["boot_lo"]), float(np.quantile(bm, 0.025))))
    max_bd = max(abs(a - b) for _, a, b in boot_diff) if boot_diff else 0
    check("JSON ↔ 거래 CSV (n·평균 R·PF·중앙값·승률·연도별·상태·청산 사유·비용 2배·무작위 요약·판정)", not jc_bad,
          f"불일치 {len(jc_bad)}건" + ("" if not jc_bad else ": " + "; ".join(jc_bad[:10])), is_critical=bool(jc_bad))
    check("부트스트랩 하한 (독립 시드 근사)", max_bd <= 0.05,
          f"최대 차이 {max_bd:.4f}R (허용 0.05R, 난수 시드가 달라 근사 비교)")
    # DSR 분산
    shs = []
    for c in J["combos"]:
        df = all_csv[f"{c['key']}_exec"]
        r = df[df.status == "filled"]["r_multiple"].to_numpy(float)
        if len(r) >= 2:
            shs.append(r.mean() / r.std(ddof=1))
    var = float(np.var(shs, ddof=1))
    check("DSR 시도 간 샤프 분산", close(J["dsr_sr_trials_var"], var, 1e-9),
          f"JSON {J['dsr_sr_trials_var']:.4f} vs CSV 재계산 {var:.4f} (조합 {len(shs)}개)")

    # ---------------- 4) 보고서 ↔ JSON ----------------
    rep_bad = []
    tabs = md_tables(report_md)
    CJ = {c["key"]: c for c in J["combos"]}

    def tab(first_head_prefix, contains=None):
        for t in tabs:
            if t["head"][0] == first_head_prefix and (contains is None or any(contains in h for h in t["head"])):
                return t
        return None

    t1 = tab("조합", "DSR")
    for row in t1["rows"]:
        c = CJ[row[0]]
        e, a = c["exec"], c["all"]
        na, ne = [cell_num(x) for x in row[1].split("/")]
        ok = [na == a["n"], ne == e["n"], approx_cell(row[2], jnum(e["mean_r"]), 3),
              approx_cell(row[3], jnum(e["boot_lo"]), 3), approx_cell(row[4], jnum(e["pf"]), 2),
              approx_cell(row[5], jnum(c["exec_cost2"]["mean_r"]), 3),
              approx_cell(row[6], c["random"].get("p95"), 3),
              row[7] == f"{e['positive_years']}/7", approx_cell(row[8], jnum(c["dsr"]), 2),
              ("보류" in row[9]) == (c["verdict"]["result"] == "pending")]
        if not all(ok):
            rep_bad.append(f"§1 표 {row[0]} 칸 {[i for i, x in enumerate(ok) if not x]}")
    t1b = tab("조합", "⑦ 거래 ≥ 30")
    keys7 = ["c1_mean_r", "c2_boot_lo", "c3_pf", "c4_cost2", "c5_random", "c6_years", "c7_enough_trades"]
    for row in t1b["rows"]:
        c = CJ[row[0]]
        marks = [x == "○" for x in row[1:8]]
        if marks != [c["verdict"][k] for k in keys7] or not approx_cell(row[8], jnum(c["exec"]["perm_p"]), 3):
            rep_bad.append(f"§1 조건표 {row[0]}")
    t2 = tab("조합", "하루 6건 초과로 빠진 신호")
    for row in t2["rows"]:
        c = CJ[row[0]]
        e, a = c["exec"], c["all"]
        ok = [cell_num(row[1]) == a["n"], approx_cell(row[2], jnum(a["mean_r"]), 3), cell_num(row[3]) == e["n"],
              approx_cell(row[4], jnum(e["mean_r"]), 3),
              cell_num(row[5]) == e["discard_first_reason"]["MASK_DND"],
              cell_num(row[6]) == e["discard_first_reason"]["MASK_DAILY_CAP"]]
        if not all(ok):
            rep_bad.append(f"§2 전체/실행 표 {row[0]} 칸 {[i for i, x in enumerate(ok) if not x]}")
    t2b = tab("조합", "심야 00:30~07:30 (거래 / 평균 R)")
    for row in t2b["rows"]:
        a = CJ[row[0]]["all"]
        for cell, ses in zip(row[1:4], ("day", "evening", "night")):
            n_s, m_s = cell.split("/")
            if cell_num(n_s) != a["by_session"][ses]["n"] or not approx_cell(m_s, jnum(a["by_session"][ses]["mean_r"]), 3):
                rep_bad.append(f"§2 시간대 표 {row[0]} {ses}")
    t2c = tab("시나리오-방향")
    for row in t2c["rows"]:
        for setting, off in (("P1", 1), ("P2", 5)):
            e = CJ[f"{row[0]}-{setting}"]["exec"]
            g3 = jnum(e["g3_weeks_to_150"])
            ok = [cell_num(row[off]) == e["n"], approx_cell(row[off + 1], jnum(e["mean_r"]), 3),
                  approx_cell(row[off + 2], jnum(e["passed_per_week"]), 2),
                  (row[off + 3] == "∞") if (g3 is None or math.isinf(g3)) else approx_cell(row[off + 3], g3, 0)]
            if not all(ok):
                rep_bad.append(f"§2 P1/P2 표 {row[0]} {setting} 칸 {[i for i, x in enumerate(ok) if not x]}")
    t3 = tab("조합", "워밍업")
    sc_keys = ["SC_CLOSE_VS_WAIST", "SC_SLOPE60", "SC_UNHEALTHY", "SC_NO_TARGET", "SC_BAD_GEOMETRY"]
    for row in t3["rows"]:
        e = CJ[row[0]]["exec"]
        dfr = e["discard_first_reason"]
        exp = [e["n_candidates"], e["n_passed"], dfr["WARMUP"], sum(dfr[k] for k in sc_keys)] + \
              [dfr[k] for k in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "RISK_STOP_BAND", "RISK_RR", "F8", "F9",
                                "MASK_DND", "MASK_DAILY_CAP")]
        got = [cell_num(x) for x in row[1:]]
        if got != exp:
            rep_bad.append(f"§3 사유표 {row[0]}")
        if e["n_candidates"] != sum(dfr.values()) + e["n_passed"]:
            rep_bad.append(f"§3 {row[0]}: 대표 사유 합 + 통과 ≠ 후보 수")
    t3b = tab("조합", "RISK_STOP_BAND")
    for row in t3b["rows"]:
        e = CJ[row[0]]["exec"]
        for h, cell in zip(t3b["head"][1:], row[1:]):
            share = e["discard_any_reason"][h] / e["n_candidates"]
            if not approx_cell(cell, share, 0, pct=True):
                rep_bad.append(f"§3 비율표 {row[0]} {h}")
    t4 = tab("조합", "무작위 평균")
    for row in t4["rows"]:
        c = CJ[row[0]]
        rd = c["random"]
        mm = np.array(rd["means"], float)
        pos = float((mm < jnum(c["exec"]["mean_r"])).mean())
        ok = [approx_cell(row[1].split("(")[0], jnum(c["exec"]["mean_r"]), 3),
              approx_cell(row[2], rd["mean"], 3), approx_cell(row[3], rd["p05"], 3),
              approx_cell(row[4], rd["p50"], 3), approx_cell(row[5], rd["p95"], 3),
              approx_cell(row[6], pos, 0, pct=True), cell_num(row[7]) == rd["n_not_filled"],
              approx_cell(row[8], rd["same_fee"]["p95"], 3)]
        if not all(ok):
            rep_bad.append(f"§4.1 무작위 표 {row[0]} 칸 {[i for i, x in enumerate(ok) if not x]}")
    dj = J["donchian"]
    t42 = tab("항목")
    vals = {r[0]: r[1] for r in t42["rows"]}
    ok = [approx_cell(vals["연 수익률(CAGR)"], dj["cagr"], 1, pct=True),
          approx_cell(vals["최대 낙폭(MDD)"], dj["max_drawdown"], 1, pct=True),
          approx_cell(vals["샤프(일간, 연율화)"], dj["sharpe"], 2), cell_num(vals["진입 횟수"]) == dj["n_trades"],
          approx_cell(vals["최종 자산 (시작 1.0)"], dj["final_equity"], 3)]
    if not all(ok):
        rep_bad.append(f"§4.2 돈치안 표 칸 {[i for i, x in enumerate(ok) if not x]}")
    t5 = tab("조합", "지연 5분")
    SENS = {(s["key"], s["variant"].split("(")[0]): s for s in J["sensitivity"]}
    vmap = [None, "lat5", "lat15", "mid", "vr3", "cost2", "rearm"]
    for row in t5["rows"]:
        for i, v in enumerate(vmap):
            cell = row[i + 1]
            e = CJ[row[0]]["exec"] if v is None else (SENS.get((row[0], v)) or {}).get("exec")
            if e is None:
                if cell != "–":
                    rep_bad.append(f"§5 {row[0]} {v}")
                continue
            n_s, m_s = cell.split("/")
            if cell_num(n_s) != e["n"] or not approx_cell(m_s, jnum(e["mean_r"]), 3):
                rep_bad.append(f"§5 민감도 {row[0]} {v}")
    tA = tab("조합", "2020")
    for row in tA["rows"]:
        e = CJ[row[0]]["exec"]
        for y, cell in zip(range(2020, 2027), row[1:8]):
            v = jnum(e["yearly"][str(y)])
            if v is None:
                if cell != "–":
                    rep_bad.append(f"부록 A {row[0]} {y}")
            else:
                m_ = re.match(r"^([+-]?\d+\.\d+) \((\d+)\)$", cell)
                if not m_ or abs(float(m_.group(1)) - v) > 0.0005 + 1e-9 or int(m_.group(2)) != e["yearly_n"][str(y)]:
                    rep_bad.append(f"부록 A {row[0]} {y}")
        if cell_num(row[8]) != e["positive_years"]:
            rep_bad.append(f"부록 A {row[0]} 양수 연도")
    sm = J["summary"]
    if f"통과 후보 {sm['n_pass']}개" not in report_md or f"판정 보류 {sm['n_pending']}개" not in report_md:
        rep_bad.append("머리말 결론 문장의 개수")
    if f"{J['dsr_sr_trials_var']:.4f}" not in report_md:
        rep_bad.append("§6 샤프 분산 표기")
    if f"{J['params']['random_reps']:,}회" not in report_md:
        rep_bad.append("무작위 반복 수 표기")
    if J["code_sha256"][:12] not in report_md:
        rep_bad.append("코드 해시 표기")
    for fname, h in J["data"]["sha256"].items():
        if h[:16] not in report_md:
            rep_bad.append(f"데이터 해시 {fname}")
    n_tables = 12
    check("G1_REPORT.md ↔ g1_results.json", not rep_bad,
          f"표 {n_tables}종·머리말·해시 비교, 불일치 {len(rep_bad)}건" + ("" if not rep_bad else ": " + "; ".join(rep_bad[:10])),
          is_critical=bool(rep_bad))

    # ---------------- 5) 상식 점검 ----------------
    # 5a 실행 가능 ≤ 전체
    bad = [c["key"] for c in J["combos"] if c["exec"]["n"] > c["all"]["n"]]
    tot_a, tot_e = sum(c["all"]["n"] for c in J["combos"]), sum(c["exec"]["n"] for c in J["combos"])
    check("실행 가능 거래 수 ≤ 전체 거래 수", not bad, f"조합별 모두 성립 (합계 실행 가능 {tot_e} ≤ 전체 {tot_a})"
          if not bad else f"위반 {bad}")
    # 5b 손절 폭 밴드 · 순손익비 (모든 행: 계획가 기준)
    band_bad, rr_bad = [], []
    realized_narrow = []
    for r in row_results:
        if "d_pct" not in r:
            continue
        if not (r["band_lo"] - 1e-12 <= r["d_pct"] <= r["band_hi"] + 1e-12):  # 거래 행은 경계에서 멀다
            band_bad.append(f"{r['file']}#{r['row']}")
        if r["net_rr"] < 1.5:
            rr_bad.append(f"{r['file']}#{r['row']}")
        s = r["sim"]
        if s.status == "filled":
            d_act = abs(s.entry_price - float(all_csv[r["file"]].loc[r["row"], "stop"])) / s.entry_price
            if d_act < r["band_lo"] - 1e-12:
                realized_narrow.append(f"{r['file']}#{r['row']} ({d_act:.3%} < {r['band_lo']:.3%})")
    ncheck = sum("d_pct" in r for r in row_results)
    dp = [r["d_pct"] for r in row_results if "d_pct" in r]
    check("모든 손절 폭이 밴드 안 (계획가, 신호 봉 ATR)", not band_bad,
          f"{ncheck}행 검사, 위반 {len(band_bad)} (d/진입가 범위 {min(dp):.3%}~{max(dp):.3%})"
          + ("" if not band_bad else f": {band_bad[:5]}"), is_critical=bool(band_bad))
    rrs = [r["net_rr"] for r in row_results if "net_rr" in r]
    check("모든 순손익비 ≥ 1.5", not rr_bad, f"{ncheck}행 검사, 최솟값 {min(rrs):.3f}, 위반 {len(rr_bad)}",
          is_critical=bool(rr_bad))
    if realized_narrow:
        notes.append("L1b(IOC 상한)는 실제 체결가가 상한보다 낮아 **실제** 손절 폭이 밴드 하한보다 좁아진 체결이 있다: "
                     + ", ".join(realized_narrow[:8]) + f" (총 {len(realized_narrow)}건). 명세 §8.1 검사는 신호 시점 계획가 "
                     "기준이라 규칙 위반은 아니며, R 분모는 실제 진입가 기준이라 손절 = −1R로 정확히 기록된다(보고서 §7에 이미 명시).")
    # 5c 겹침·F9·방해 금지·하루 6건·F8
    ov_bad, dnd_bad, cap_bad, f8_bad = [], [], [], []
    for stem, df in all_csv.items():
        if not len(df):
            continue
        d = df.sort_values("approval_time", kind="stable")
        prev_busy = None
        stops = defaultdict(list)
        for _, r in d.iterrows():
            ap = I.iso_ns(r["approval_time"])
            if prev_busy is not None and ap < prev_busy:
                ov_bad.append(f"{stem} {r['plan_id']}")
            prev_busy = I.iso_ns(r["busy_until"])
            if isinstance(r["madi_id"], str) and sum(s <= ap for s in stops[r["madi_id"]]) >= 2:
                f8_bad.append(f"{stem} {r['plan_id']}")
            if r["status"] == "filled" and r["exit_reason"] == "stop" and isinstance(r["madi_id"], str):
                stops[r["madi_id"]].append(I.iso_ns(r["busy_until"]))
        fl = d[d.status == "filled"]
        ivs = sorted((I.iso_ns(a), I.iso_ns(b)) for a, b in zip(fl["entry_time"], fl["busy_until"]))
        for (a0, b0), (a1, b1) in zip(ivs, ivs[1:]):
            if a1 < b0:
                ov_bad.append(f"{stem} 포지션 겹침 {I.ns_iso(a1)}")
        if stem.endswith("_exec"):
            for ap in d["approval_time"]:
                if I.in_dnd(I.iso_ns(ap)):
                    dnd_bad.append(f"{stem} {ap}")
            per_day = Counter(I.kst_day(I.iso_ns(ap)) for ap in d["approval_time"])
            cap_bad += [f"{stem} {k}" for k, v in per_day.items() if v > 6]
    n_all_dnd = sum(I.in_dnd(I.iso_ns(ap)) for stem, df in all_csv.items() if stem.endswith("_all")
                    for ap in df["approval_time"])
    check("포지션·대기 주문 겹침 0건 (F9, 모든 CSV)", not ov_bad, f"위반 {len(ov_bad)}" + (f": {ov_bad[:5]}" if ov_bad else ""),
          is_critical=bool(ov_bad))
    check("방해 금지 시간 승인 0건 (실행 가능 CSV)", not dnd_bad,
          f"실행 가능 위반 {len(dnd_bad)} (참고: 전체 모드 CSV에는 방해 금지 승인 {n_all_dnd}건 — 정상)",
          is_critical=bool(dnd_bad))
    check("KST 하루 승인 요청 ≤ 6 (실행 가능 CSV)", not cap_bad, f"위반 {len(cap_bad)}", is_critical=bool(cap_bad))
    check("F8 같은 마디 2손절 뒤 신호 0건", not f8_bad, f"위반 {len(f8_bad)}", is_critical=bool(f8_bad))

    # 5d 무작위 기준선 기대값 (전수) vs JSON, 그리고 −비용/위험
    rnd_rows = []
    for c in J["combos"]:
        df = all_csv[f"{c['key']}_exec"]
        fl = df[df.status == "filled"]
        if not len(fl):
            continue
        setting = c["key"].split("-")[2]
        pt = random_expectation(ctx, setting, fl)
        exp_mean = float(np.mean([p["mean_r"] for p in pt]))
        cost_r = float(np.mean([p["cost_r"] for p in pt]))
        gross_r = float(np.mean([p["gross_r"] for p in pt]))
        mm = np.array(c["random"]["means"], float)
        se = float(mm.std(ddof=1) / math.sqrt(len(mm)))
        rnd_rows.append(dict(key=c["key"], n=len(fl), json_mean=c["random"]["mean"], exp_mean=exp_mean, se=se,
                             z=(c["random"]["mean"] - exp_mean) / se if se > 0 else 0.0, cost_r=cost_r,
                             gross_r=gross_r, sp=float(np.mean([p["sp"] for p in pt]))))
    zmax = max(abs(r["z"]) for r in rnd_rows)
    check("무작위 기준선 평균 = 같은 달 전수 기대값 (독립 구현)", zmax <= 4,
          "; ".join(f"{r['key']} JSON {r['json_mean']:+.3f} vs 전수 {r['exp_mean']:+.3f} (z={r['z']:+.1f})"
                    for r in rnd_rows), is_critical=zmax > 6)
    w = np.array([r["n"] for r in rnd_rows], float)
    pooled_json = float(np.sum(w * [r["json_mean"] for r in rnd_rows]) / w.sum())
    pooled_cost = float(np.sum(w * [r["cost_r"] for r in rnd_rows]) / w.sum())
    pooled_gross = float(np.sum(w * [r["gross_r"] for r in rnd_rows]) / w.sum())
    check("무작위 기준선 ≈ −(왕복 비용 ÷ 위험) (+ 그 달 추세)", abs(pooled_json - (pooled_gross - pooled_cost)) < 0.05,
          f"거래 가중 풀링: 무작위 평균 {pooled_json:+.3f}R = 가격 변동분 {pooled_gross:+.3f}R − 비용분 {pooled_cost:.3f}R "
          f"(비용분 −{pooled_cost:.3f}R 이 '−왕복 비용÷위험'. 조합별 편차는 그 달 추세(가격 변동분)로 설명됨)")

    # 5e 펀딩 창 해석 영향 (IOC)
    fdiff = [abs(r.get("funding_spec_diff_r", 0.0)) for r in row_results if r["status"] == "filled"]
    check("펀딩 창 해석(IOC: 활성 시각 vs 진입 봉 시작) 영향", max(fdiff) < 1e-3,
          f"엔진 해석(I-35)과 명세 문자 그대로(진입 시각 < f)의 R 차이 최대 {max(fdiff):.2e}R")

    # ---------------- 저장 ----------------
    summary = dict(info=info, cand_rows=cand_rows, rnd_rows=rnd_rows, boot_diff=boot_diff,
                   n_rows=n_rows, n_filled=n_filled, n_bad=n_bad, n_sampled=n_sampled, runtime_sec=time.time() - t_start)
    write_report(J, summary, row_results)
    OUT_JSON.write_text(json.dumps(dict(checks=checks, critical=critical, other=other, notes=notes,
                                        runtime_sec=round(time.time() - t_start, 1)), ensure_ascii=False, indent=1))
    print(json.dumps(dict(n_checks=len(checks), failed=[c["name"] for c in checks if not c["passed"]],
                          critical=critical, other=other), ensure_ascii=False, indent=1))


def write_report(J, S, rows):
    L = []
    ok = not critical
    L.append("# G1 독립 검증 보고서 (VERIFY_REPORT)\n")
    L.append(f"- 검증 대상: `backtest/results/g1_results.json` (created {J['created_utc']}, 코드 해시 "
             f"`{J['code_sha256'][:12]}`), `G1_REPORT.md`, `trades/*.csv` 32개")
    L.append("- 방법: `backtest` 패키지를 **import 하지 않는** 독립 구현(`backtest/verify/indep.py`)으로 원자료 "
             "`data/binance/*.csv.gz` 와 `docs/RULES_SPEC.md` v1.0(§12 우선)만으로 다시 계산. 명세가 애매한 곳은 "
             "설계서 DESIGN.md §7(I-번호)의 해석을 기준으로 삼되, 대안 해석의 영향을 따로 측정.")
    L.append(f"- 실행: `python backtest/verify/verify_g1.py` · 소요 {S['runtime_sec']:.0f}초 · 난수 시드 {SEED}")
    L.append(f"- **결론: {'결과를 믿을 수 없게 만드는 문제 없음' if ok else '치명적 문제 발견'}** — 검사 {len(checks)}개 중 "
             f"통과 {sum(c['passed'] for c in checks)}개.\n")
    L.append("## 허용 오차\n")
    L.append(f"| 항목 | 허용 오차 |\n|---|---|\n| 가격(진입·손절·목표·체결·청산) | {TOL_PRICE:g} USDT |\n"
             f"| A·B·W·H | {TOL_META:g} USDT |\n| 시각 | 0 (정확히 일치) |\n| 단위당 수수료·슬리피지·펀딩·손익 | "
             f"{TOL_MONEY:g} USDT |\n| R | {TOL_R:g} |\n| JSON 통계 ↔ CSV 재계산 | 상대 {TOL_STAT:g} |\n"
             f"| 보고서 표시값 | 표시 자릿수의 ½ |\n| 부트스트랩 하한(시드 다름) | 0.05R |\n"
             f"| 무작위 기준선 평균 vs 전수 기대값 | \\|z\\| ≤ 4 (SE = 반복 평균 표준편차/√1000) |\n")
    L.append("## 검사 결과\n")
    L.append("| # | 검사 | 결과 | 내용 |\n|---:|---|---|---|")
    for i, c in enumerate(checks, 1):
        det = c["detail"].replace("|", "\\|")
        L.append(f"| {i} | {c['name']} | {'통과' if c['passed'] else '**실패**'} | {det} |")
    L.append("")
    L.append("## 1. 거래 재계산 (조합·모드별 시드 고정 5건 + 전 행)\n")
    L.append(f"거래 CSV 32개의 **전 행 {S['n_rows']}개**(체결 {S['n_filled']}개, 취소·만료·미체결 포함)를 다시 계산했다. "
             f"요구된 표본(조합·모드별 무작위 5건, 시드 {SEED})은 {S['n_sampled']}행이며 전 행 검증에 포함된다. "
             "행마다: 근거 마디를 독립 구현의 마디 표에서 찾고(A·B·W·H·허리 대체값 여부·T_B), 시나리오 신호 시각과 "
             "조건, 계획 가격(진입·손절·목표, 0.1 반올림), F1~F7·손절 폭·순손익비, 승인·활성 시각, 주문 끝(만료·취소 효력), "
             "실행 봉(2023-10 전 5분·후 1분)으로 상태·체결 시각·가격·청산 시각·가격·사유·수수료·슬리피지·펀딩·순손익·R·busy_until.\n")
    L.append("| 파일 | 계획 | 표본 | 상태 | 신호→진입 | 청산 | R(엔진) | R(독립) | 일치 |\n|---|---|:-:|---|---|---|---:|---:|:-:|")
    for r in rows:
        s = r.get("sim")
        if s is None:
            continue
        csv_r = ""
        if s.status == "filled":
            L.append(f"| {r['file']} | {r['plan_id']} | {'●' if r['sampled'] else ''} | {r['status']} | "
                     f"{I.ns_iso(ctx_X.open_ns[s.entry_j])} @{s.entry_price:.2f} | {s.exit_reason} "
                     f"{I.ns_iso(ctx_X.open_ns[s.exit_j])} @{s.exit_price:.2f} | {r.get('r_eng', 0):+.4f} | {s.r:+.4f} | "
                     f"{'○' if not r['mism'] else '×'} |")
        else:
            L.append(f"| {r['file']} | {r['plan_id']} | {'●' if r['sampled'] else ''} | {r['status']} | – | – | – | – | "
                     f"{'○' if not r['mism'] else '×'} |")
    L.append("")
    L.append("## 2. 후보 수·폐기 사유 독립 재계산 (사유 포함 기준, F8·F9·마스크 제외)\n")
    L.append("| 조합 | 후보(엔진) | 후보(독립) | 사유 불일치 |\n|---|---:|---:|---|")
    for r in S["cand_rows"]:
        d = ", ".join(f"{k} {a}→{b}" for k, (a, b) in r["diffs"].items()) or "없음"
        L.append(f"| {r['key']} | {r['eng_n']:,} | {r['ind_n']:,} | {d} |")
    L.append("")
    L.append("## 3. 무작위 기준선 점검\n")
    L.append("같은 달의 **모든** 신호 봉 마감에서 시장가로 들어가는 경우를 전부 계산한 기대값(독립 구현)과 엔진의 1,000회 평균을 "
             "비교하고, 그 기대값을 '가격 변동분(비용 전)'과 '비용분(수수료·슬리피지·펀딩 ÷ 위험)'으로 나눴다.\n")
    L.append("| 조합 | 거래 | 평균 손절 폭 | JSON 무작위 평균 | 전수 기대값 | z | 가격 변동분 | −비용분 |\n"
             "|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in S["rnd_rows"]:
        L.append(f"| {r['key']} | {r['n']} | {r['sp']:.2%} | {r['json_mean']:+.3f} | {r['exp_mean']:+.3f} | {r['z']:+.1f} | "
                 f"{r['gross_r']:+.3f} | {-r['cost_r']:+.3f} |")
    L.append("")
    L.append("## 4. 기타 문제·메모\n")
    for x in other:
        L.append(f"- (비치명) {x}")
    for x in notes:
        L.append(f"- {x}")
    for x in EXTRA_NOTES:
        L.append(f"- {x}")
    if critical:
        L.append("\n## 치명적 문제\n")
        for x in critical:
            L.append(f"- {x}")
    OUT_MD.write_text("\n".join(L) + "\n")


EXTRA_NOTES: list[str] = [
    "검증 쪽 해석(명세 문장이 여럿으로 읽히는 곳, 가장 보수적인 쪽 또는 §12 문장 그대로): ATR·VR·몸통·MA 평균은 현재 봉 제외 "
    "[t−n, t−1](§3 머리말); 스윙은 엄격한 부등호, i+3 마감에 확정; 마디 무효 검사는 종가 [A 봉, T_B 봉](T_B 포함); 허리 칸은 A 쪽 끝에서 "
    "시작; L1b '두 번 마감'은 신호 봉 종가; F6 트랩은 완성 봉이 직전 48봉 안; 펀딩 가격 = 그 시각을 포함하는 실행 봉 시가; "
    "시간 청산 기준 = 체결 봉 시작 + 72 신호 봉; R 분모 = 실제 진입가 기준 d + c_stop(§12.2). 이 선택은 설계서 I-번호와 같다 — 따라서 "
    "이 검증은 '엔진이 문서화된 해석을 정확히 구현했는가'를 독립 코드로 확인한 것이고, 해석 자체의 대안은 ①②·펀딩 창처럼 따로 측정했다.",
    "손절 폭 밴드 경계: S3 손절(S + ATR)은 하한(1 × ATR)과 같은 거리라 0.1 반올림 뒤 부동소수 오차 크기(< 1e-9)로 경계에 걸린다. "
    "엔진은 1e-9 허용(양 끝 포함)을 쓰며 검증도 같게 두었다(허용 없이 세면 S3-P1 후보 69개, S3-P2 14개가 추가로 '손절 폭' 탈락 — "
    "S3 거래는 어차피 0건이라 결과 영향 없음).",
    "거래 CSV의 `*_ns` 열 일부(entry_time_ns, exit_time_ns, exit_bar_close_ns)는 빈 값이 섞여 실수형(예 1.596231e+18)으로 저장된다. "
    "초 단위 시각이라 값 손실은 없지만, 검증은 ISO 문자열 열을 썼다(비치명, 형식 메모).",
]
ctx_X = None

if __name__ == "__main__":
    main()
