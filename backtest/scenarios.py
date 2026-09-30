"""진입 시나리오(§7) — 신호 후보(Candidate)와 주문 계획(Plan)을 만든다.

담당: 구조·시나리오. 설계: backtest/DESIGN.md §6.7, 해석 확정 I-14, I-15, I-21~I-25, I-37, I-45~I-47.

공통 규약
- 판단 시각(approval_time) = 신호 봉(L1b는 확인 봉) 마감 + 60초. active_from = approval_time + cfg.latency_ns.
- 모든 가격은 계산 후 config.round_price (0.1 USDT). A·B·W는 원값, 허리 H는 이미 반올림된 값에서 출발 (I-14).
- 취소 조건은 "신호 봉 마감마다" 검사해 **처음 성립한 봉 k의 close_ns + 60초**를 Plan.cancel_effective_time에 넣는다
  (§12.1). 체결 엔진은 신호 봉 데이터를 보지 않는다. 검사 범위는 신호 봉 다음 봉부터 유효 기간 N봉까지,
  데이터에 있는 봉까지만(없으면 None).
- 폐기 사유는 REASON_ORDER 순서로 모두 기록한다(types.sort_reasons). valid가 False면 WARMUP 하나만 기록하고 plan=None.
- 가격을 계산할 수 있으면 폐기 후보에도 plan을 붙인다(진단용). 순차 엔진은 사유가 있는 후보의 plan을 쓰지 않는다.
- 출력 목록은 (approval_time, −근거 마디 tb_close_ns(없으면 0), plan_id) 오름차순 (I-37).

알게 된 시각(meta, 감사용) — 후보가 쓴 모든 구조가 언제 알려졌는지 (모두 ≤ signal_time이어야 한다, C-1·C-5)
- madi_known_ns(근거 마디 tb_close_ns), arm_known_ns(L1b 준비 봉 마감), support_known_ns·target_known_ns(S3 스윙 확정),
  waist_madi_known_ns(S3 허리 조건 마디), d_known_ns(쓴 D 봉 마감), known_ns = 이들의 최댓값.
- cand_id = make_plan_id(...) — plan이 없는 후보(WARMUP·SC_NO_TARGET)도 식별할 수 있게 모든 후보에 붙인다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backtest import config as C
from backtest import filters as F
from backtest import indicators as IND
from backtest import structure as ST
from backtest.config import ComboConfig
from backtest.types import (CancelRule, Candidate, MarketData, Plan, Reason, ScenarioContext, SignalLog,
                            sort_reasons)

_KNOWN_KEYS = ("madi_known_ns", "arm_known_ns", "support_known_ns", "target_known_ns",
               "waist_madi_known_ns", "d_known_ns")


# ---------------------------------------------------------------------------
# 문맥 (설정·VR 기준마다 한 번)
# ---------------------------------------------------------------------------


def build_context(market: MarketData, setting: str, vr_threshold: float = C.KIJUN_VR_MIN) -> ScenarioContext:
    """봉 설정 하나(P1/P2)와 기준봉 VR 기준 하나에 대한 재료를 한 번 계산한다.

    S·D 봉: indicators.compute_indicators → structure.build_structure(vr_threshold) (D도 같은 vr_threshold, I-26)
    S 봉: filters.fixed_filter_flags. C 봉은 그대로. events_ns = market.events_ns.
    """
    if setting not in C.SETTINGS:
        raise ValueError(f"setting은 {C.SETTING_NAMES} 중 하나: {setting!r}")
    bs = C.SETTINGS[setting]                                   # §2 봉 설정 (S, D, C)
    s_bars, d_bars, c_bars = market.bars[bs.signal], market.bars[bs.direction], market.bars[bs.confirm]
    s_ind = IND.compute_indicators(s_bars)
    s_struct = ST.build_structure(s_bars, s_ind, bs.signal, vr_threshold)
    d_ind = IND.compute_indicators(d_bars)
    d_struct = ST.build_structure(d_bars, d_ind, bs.direction, vr_threshold)  # I-26 D 기준봉도 같은 VR 기준
    s_flags = F.fixed_filter_flags(s_bars, s_ind, s_struct)
    return ScenarioContext(setting=setting, vr_threshold=float(vr_threshold), s_tf=bs.signal, d_tf=bs.direction,
                           c_tf=bs.confirm, s_bars=s_bars, s_ind=s_ind, s_struct=s_struct, d_bars=d_bars,
                           d_ind=d_ind, d_struct=d_struct, c_bars=c_bars, s_flags=s_flags,
                           events_ns=market.events_ns)


def _s_arrays(ctx: ScenarioContext) -> dict[str, np.ndarray]:
    """S 봉·지표 배열 (ctx.cache에 한 번만 꺼내 둔다)."""
    key = ("s_arrays",)
    if key not in ctx.cache:
        b, ind = ctx.s_bars, ctx.s_ind
        out = {k: b[k].to_numpy(dtype=np.float64) for k in ("open", "high", "low", "close", "volume")}
        out.update({k: b[k].to_numpy(dtype=np.int64) for k in ("open_ns", "close_ns")})
        out.update({k: ind[k].to_numpy(dtype=np.float64) for k in ("atr", "buffer", "vr", "slope60")})
        out["valid"] = ind["valid"].to_numpy(dtype=bool)
        ctx.cache[key] = out
    return ctx.cache[key]


def _c_arrays(ctx: ScenarioContext) -> dict[str, np.ndarray]:
    """확인 봉 C 배열 + 확인 기본 조건(양봉 and 종가 > 직전 C 봉 고가, §7.2)."""
    key = ("c_arrays",)
    if key not in ctx.cache:
        b = ctx.c_bars
        out = {k: b[k].to_numpy(dtype=np.float64) for k in ("open", "high", "low", "close")}
        out.update({k: b[k].to_numpy(dtype=np.int64) for k in ("open_ns", "close_ns")})
        o, h, c = out["open"], out["high"], out["close"]
        base = np.zeros(c.shape[0], dtype=bool)
        base[1:] = (c[1:] > o[1:]) & (c[1:] > h[:-1])          # §7.2 양봉 종가 > 직전 C 봉 고가
        out["confirm_base"] = base
        ctx.cache[key] = out
    return ctx.cache[key]


def _madi_arrays(ctx: ScenarioContext, waist_method: str) -> dict[str, np.ndarray]:
    """S 마디 표의 열 배열 + 선택한 허리 H."""
    key = ("madi_arrays", waist_method)
    if key not in ctx.cache:
        m = ctx.s_struct.madis
        out = {k: m[k].to_numpy() for k in ("madi_id", "direction", "kijun_idx", "a_idx", "b_idx", "tb_idx",
                                             "a_price", "b_price", "w", "vol_ab_mean", "end_idx",
                                             "tb_close_ns", "waist_fallback")}
        out["H"] = ST.madi_waist(m, waist_method)
        ctx.cache[key] = out
    return ctx.cache[key]


# ---------------------------------------------------------------------------
# 공용 도우미
# ---------------------------------------------------------------------------


def make_plan_id(scenario: str, signal_time_ns: int, basis: str) -> str:
    """계획 ID = f"{scenario}_{신호 시각 %Y%m%d%H%M}_{basis}". basis = 마디 ID 또는 S3의 f"sup{스윙 저점 번호}"."""
    return f"{scenario}_{ST.fmt_minute(signal_time_ns)}_{basis}"


def first_cancel_index(conditions: dict[str, np.ndarray], start: int, stop: int) -> tuple[int | None, str | None]:
    """보조: 봉 번호 [start, stop] 중 조건 배열(bool, 이름 → 배열) 하나라도 True인 첫 봉과 그 조건 이름.

    같은 봉에서 여러 조건이 동시에 성립하면 dict 순서상 앞의 이름. 없으면 (None, None).
    """
    if not conditions:
        return None, None
    names = list(conditions)
    arrs = [np.asarray(conditions[k], dtype=bool) for k in names]
    start = max(int(start), 0)
    stop = min(int(stop), min(a.shape[0] for a in arrs) - 1)   # 데이터에 있는 봉까지만
    if start > stop:
        return None, None
    table = np.stack([a[start:stop + 1] for a in arrs])        # (조건 수, 봉 수)
    hit = table.any(axis=0)
    if not hit.any():
        return None, None
    k = int(np.argmax(hit))
    return start + k, names[int(np.argmax(table[:, k]))]


def sort_candidates(cands: list[Candidate]) -> list[Candidate]:
    """(approval_time, −근거 마디 tb_close_ns, plan_id 또는 '') 오름차순 정렬 (I-37). tb_close_ns는 log.meta에서 읽는다."""
    def key(c: Candidate):
        return (int(c.log.time), -int(c.log.meta.get("tb_close_ns", 0) or 0), c.log.plan_id or "")
    return sorted(cands, key=key)                              # 파이썬 정렬은 안정 정렬 (결정적)


def plan_geometry_ok(plan: Plan) -> bool:
    """I-45: 롱은 stop < entry < target, 숏은 target < entry < stop 이어야 한다."""
    if plan.side > 0:
        return bool(plan.stop < plan.entry_price < plan.target)
    return bool(plan.target < plan.entry_price < plan.stop)


@dataclass
class _Raw:
    """시나리오가 찾은 후보 하나(필터·리스크 검사 전)."""

    s_idx: int                        # 필터 기준 S 봉 (L1b는 k_last, I-15)
    signal_time: int                  # 신호 봉(L1b는 확인 봉) 마감
    basis: str                        # plan_id 꼬리 (마디 ID 또는 sup{i})
    madi_id: str | None
    sc: list                          # 시나리오 사유 (SC_*)
    entry: float | None
    stop: float | None
    target: float | None
    atr: float                        # 손절 폭 검사 ATR (§12.2)
    valid_until: int | None           # None이면 IOC (= active_from)
    cancel_rules: tuple = ()
    cancel_k: int | None = None       # 취소 조건이 처음 성립한 S 봉
    cancel_kind: str | None = None
    meta: dict = field(default_factory=dict)


def _finite(*xs) -> bool:
    return all(x is not None and np.isfinite(x) for x in xs)


def _cancel_scan(conds: dict[str, np.ndarray], t: int) -> tuple[int | None, str | None]:
    """조건 배열(봉 t+1..부터의 조각) → (취소 성립 봉 번호, 종류)."""
    if not conds:
        return None, None
    length = min(len(a) for a in conds.values())
    k_rel, kind = first_cancel_index(conds, 0, length - 1)
    return (None, None) if k_rel is None else (t + 1 + k_rel, kind)


def _finalize(ctx: ScenarioContext, cfg: ComboConfig, raws: list[_Raw]) -> list[Candidate]:
    """WARMUP → 시나리오 사유 → F1~F7 → 기하 → RISK_* 를 붙여 Candidate 목록을 만든다 (순서는 raws 그대로)."""
    if not raws:
        return []
    a = _s_arrays(ctx)
    s_idx = np.array([r.s_idx for r in raws], dtype=np.int64)
    sig = np.array([r.signal_time for r in raws], dtype=np.int64)
    appr = sig + C.AVAIL_DELAY_NS                              # §12.1 판단 = 마감 + 60초
    valid = a["valid"][s_idx]                                  # §12.3 지표 유효 전이면 WARMUP (I-50)
    f_reasons: list[tuple[str, ...]] = [()] * len(raws)
    vi = np.flatnonzero(valid)
    if vi.size:
        for i, rs in zip(vi.tolist(), F.filter_reasons(ctx, cfg, s_idx[vi], appr[vi])):
            f_reasons[i] = rs
    d_idx = F.direction_asof_index(ctx, appr)
    d_close_ns = ctx.d_bars["close_ns"].to_numpy(dtype=np.int64)
    side, order_type = cfg.side, cfg.order_type
    rate = C.entry_fee_rate(order_type)
    out: list[Candidate] = []
    for i, r in enumerate(raws):
        approval = int(appr[i])
        active_from = approval + cfg.latency_ns                # §12.1 활성 = 판단 + 지연 L
        cand_id = make_plan_id(cfg.scenario, r.signal_time, r.basis)
        meta = {"s_idx": int(r.s_idx), "cand_id": cand_id, "tb_close_ns": 0}
        meta.update(r.meta)
        dj = int(d_idx[i])
        meta["d_idx"] = dj
        meta["d_known_ns"] = int(d_close_ns[dj]) if dj >= 0 else None
        known = [meta[k] for k in _KNOWN_KEYS if meta.get(k) is not None]
        meta["known_ns"] = int(max(known)) if known else None
        if not valid[i]:
            log = SignalLog(time=approval, signal_time=int(r.signal_time), scenario=cfg.scenario, side=side,
                            status="discarded", reasons=(Reason.WARMUP,), plan_id=None, madi_id=r.madi_id,
                            meta=meta)
            out.append(Candidate(log=log, plan=None))
            continue
        reasons = list(r.sc) + list(f_reasons[i])
        plan = None
        if _finite(r.entry, r.stop):
            meta["d_pct"] = abs(r.entry - r.stop) / r.entry
        if _finite(r.entry, r.stop, r.target):
            with np.errstate(all="ignore"):
                meta["net_rr"] = float(C.net_rr(side, np.float64(r.entry), np.float64(r.stop),
                                                np.float64(r.target), rate))  # §12.2 순손익비 (기록용)
            cet = None if r.cancel_k is None else int(a["close_ns"][r.cancel_k]) + C.AVAIL_DELAY_NS  # §12.1 효력
            plan = Plan(plan_id=cand_id, scenario=cfg.scenario, side=side, signal_time=int(r.signal_time),
                        approval_time=approval, active_from=active_from, order_type=order_type,
                        entry_price=float(r.entry), stop=float(r.stop), target=float(r.target),
                        valid_until=int(r.valid_until) if r.valid_until is not None else active_from,
                        max_hold_ns=cfg.max_hold_ns, atr_at_signal=float(r.atr), cancel_effective_time=cet,
                        cancel_reason=r.cancel_kind if cet is not None else None, cancel_rules=r.cancel_rules,
                        madi_id=r.madi_id, meta=dict(meta))
            if not plan_geometry_ok(plan):
                reasons.append(Reason.SC_BAD_GEOMETRY)          # I-45
            reasons.extend(F.risk_reasons(side, plan.entry_price, plan.stop, plan.target, plan.atr_at_signal,
                                          order_type))          # §8.1 (체결 엔진의 식, 기본 비용 I-27)
        elif _finite(r.entry, r.stop) and not F.stop_band_ok(r.entry, r.stop, r.atr):
            reasons.append(Reason.RISK_STOP_BAND)               # 목표가 없어 RR은 못 보지만 손절 폭은 기록
        reasons = sort_reasons(reasons)
        if plan is None and not reasons:
            raise AssertionError(f"가격을 못 정한 후보에 사유가 없음: {cand_id}")
        log = SignalLog(time=approval, signal_time=int(r.signal_time), scenario=cfg.scenario, side=side,
                        status="discarded" if reasons else "passed", reasons=reasons,
                        plan_id=plan.plan_id if plan is not None else None, madi_id=r.madi_id, meta=meta)
        out.append(Candidate(log=log, plan=plan))
    return out


# ---------------------------------------------------------------------------
# 진입 시나리오
# ---------------------------------------------------------------------------


def generate_candidates(ctx: ScenarioContext, cfg: ComboConfig) -> list[Candidate]:
    """cfg.scenario에 맞는 candidates_* 를 불러 정렬된 후보 목록을 돌려준다 (ctx.setting == cfg.setting 확인)."""
    if ctx.setting != cfg.setting:
        raise ValueError(f"문맥 설정 {ctx.setting} ≠ 조합 설정 {cfg.setting}")
    if float(ctx.vr_threshold) != float(cfg.vr_threshold):
        raise ValueError(f"문맥 VR 기준 {ctx.vr_threshold} ≠ 조합 VR 기준 {cfg.vr_threshold} (I-26)")
    fn = {"L1a": candidates_l1a, "L1b": candidates_l1b, "S2": candidates_s2, "S3": candidates_s3}[cfg.scenario]
    return sort_candidates(fn(ctx, cfg))


def _raws(ctx: ScenarioContext, scenario: str, waist_method: str, builder, **opts) -> list[_Raw]:
    """후보 탐지 결과(_Raw 목록)를 ctx.cache에 둔다. 탐지는 방향 필터·지연·비용과 무관하므로
    (시나리오, 허리 방식, 탐지 옵션)마다 한 번만 한다 (DA/DB, 지연·비용 민감도가 같은 탐지를 나눠 씀)."""
    key = ("raws", scenario, waist_method, tuple(sorted(opts.items())))
    if key not in ctx.cache:
        ctx.cache[key] = builder(ctx, waist_method, **opts)
    return ctx.cache[key]


def _madi_meta(md: dict, r: int, waist_method: str) -> dict:
    fb = bool(md["waist_fallback"][r]) if waist_method == "cluster" else False
    return {"A": float(md["a_price"][r]), "B": float(md["b_price"][r]), "W": float(md["w"][r]),
            "H": float(md["H"][r]), "waist_method": waist_method, "waist_fallback": fb,
            "madi_row": int(r), "tb_idx": int(md["tb_idx"][r]),
            "tb_close_ns": int(md["tb_close_ns"][r]), "madi_known_ns": int(md["tb_close_ns"][r])}


def candidates_l1a(ctx: ScenarioContext, cfg: ComboConfig) -> list[Candidate]:
    """§7.1 L1a 허리 대기 매수 (I-21, I-46).

    후보: S의 상승 마디마다 신호 봉 t = tb_idx (신호 시각 = close_ns[t]).
    사유: close[t] ≤ H → SC_CLOSE_VS_WAIST; close[t] < close[t−60] → SC_SLOPE60;
          mean(volume[b_idx+1..t]) ≥ vol_ab_mean → SC_UNHEALTHY; 이어서 F1~F7, RISK_*.
    계획: side +1, order_type 'limit', entry = H, stop = round(A − buffer[t]), target = round(H + W),
          valid_until = close_ns[t] + 24 × S 길이, atr_at_signal = atr[t], madi_id = 마디 ID.
    취소 규칙(k = t+1..t+24): close[k] < A ('close_below'), high[k] > B + 0.5W ('high_above'),
          mean(volume[b_idx+1..k]) ≥ vol_ab_mean ('unhealthy_volume').
    """
    return _finalize(ctx, cfg, _raws(ctx, "L1a", cfg.waist_method, _raws_l1a))


def _raws_l1a(ctx: ScenarioContext, waist_method: str) -> list[_Raw]:
    """candidates_l1a의 후보 탐지 (필터 전)."""
    s_dur = C.TF_NS[ctx.s_tf]                                  # 신호 봉 길이 (ns)
    a, md = _s_arrays(ctx), _madi_arrays(ctx, waist_method)
    c, h, v = a["close"], a["high"], a["volume"]
    n = c.shape[0]
    n_valid = C.L1A_VALID_BARS
    raws: list[_Raw] = []
    for r in np.flatnonzero(md["direction"] == 1):
        t, b = int(md["tb_idx"][r]), int(md["b_idx"][r])
        A, B, W, H = (float(md[k][r]) for k in ("a_price", "b_price", "w", "H"))
        vol_ab = float(md["vol_ab_mean"][r])
        k_hi = min(t + n_valid, n - 1)                         # I-46 취소 검사 k = t+1..t+24 (데이터 안)
        vv = v[b + 1:k_hi + 1]
        run = np.cumsum(vv) / np.arange(1, vv.shape[0] + 1)     # run[k−b−1] = mean(volume[b+1..k]) (§12.1)
        sc = []
        if not c[t] > H:
            sc.append(Reason.SC_CLOSE_VS_WAIST)                 # §7.1 T_B 종가 > H
        if a["slope60"][t] < 0:
            sc.append(Reason.SC_SLOPE60)                        # §7.1 기울기 60 ≥ 0 (close[t] ≥ close[t−60])
        if run[t - b - 1] >= vol_ab:
            sc.append(Reason.SC_UNHEALTHY)                      # I-21 T_B 봉에서 이미 건강한 조정 위반
        ext = B + C.L1A_EXTENSION_W * W
        conds = {"close_below": c[t + 1:k_hi + 1] < A,          # §7.1 (a) 종가 < A
                 "high_above": h[t + 1:k_hi + 1] > ext,          # §7.1 (b) 고가 > B + 0.5W (마디 연장)
                 "unhealthy_volume": run[t - b:] >= vol_ab}      # §12.1 대기 중 건강한 조정 위반
        cancel_k, kind = _cancel_scan(conds, t)
        rules = (CancelRule("close_below", A, "종가 < A"),
                 CancelRule("high_above", ext, "고가 > B + 0.5W"),
                 CancelRule("unhealthy_volume", vol_ab, "B 다음 봉부터 평균 거래량 ≥ A~B 평균"))
        signal_time = int(a["close_ns"][t])
        raws.append(_Raw(
            s_idx=t, signal_time=signal_time, basis=str(md["madi_id"][r]), madi_id=str(md["madi_id"][r]), sc=sc,
            entry=H,                                            # §7.1 지정가 매수 @ H (H는 이미 0.1 반올림)
            stop=C.round_price(A - a["buffer"][t]),             # §7.1 손절 A − b
            target=C.round_price(H + W),                        # §7.1 목표 H + W
            atr=float(a["atr"][t]),
            valid_until=signal_time + n_valid * s_dur,   # §12.1 만료 = 신호 봉 마감 + 24 × 봉 길이
            cancel_rules=rules, cancel_k=cancel_k, cancel_kind=kind, meta=_madi_meta(md, r, waist_method)))
    return raws


def candidates_l1b(ctx: ScenarioContext, cfg: ComboConfig) -> list[Candidate]:
    """§7.2 L1b 허리 확인 매수 (I-15, I-22, I-23, I-44).

    마디마다 상태 기계(IDLE → ARMED → 확인 또는 폐기 → 끝). **마디당 준비는 한 번**(§7.2 문장: 준비 → 확인/폐기,
    STRATEGY P13·§5.1 L1 "같은 가격은 첫 터치만"): 첫 준비 에피소드가 확인되면 신호 1개, 폐기·창 끝·마디 사망이면
    그 마디의 L1b는 끝난다(검토 SPEC-L1B-REARM). cfg.l1b_rearm=True(보고용 진단)면 검토 전 구현(옛 I-22) 해석대로
    에피소드가 끝난 뒤(close_ns[k] > 직전 에피소드 끝 시각) 같은 마디에서 다시 준비한다.
    - 준비: S 봉 k ∈ [tb_idx+1, end_idx], H ≤ low[k] ≤ H + 0.25W 인 첫 봉.
    - 확인 후보 C 봉 c: arm_close < close_c ≤ arm_close + 24 × S 길이, 그리고 k_last(c) ≤ end_idx
      (k_last = 확인 시각에 마지막으로 마감된 S 봉 = asof_index(s_close_ns + 60초, close_c + 60초)).
      조건: close_c > open_c and close_c > high_{c−1} and close_c > H.
    - 폐기: 준비 봉 다음 S 봉들의 종가 < H가 두 번째로 나온 봉 k'(그 close_ns 이후의 C 봉은 안 봄),
      마디 사망·만료, 24봉 창 끝. 확인이 나오면 그 에피소드는 끝(신호가 폐기돼도).
    후보 = 확인 이벤트. 사유: mean(volume[b_idx+1..k_last]) ≥ vol_ab_mean → SC_UNHEALTHY, F1~F7(k_last 기준), RISK_*.
    계획: side +1, 'ioc_cap', entry = round(close_c × 1.001), lowest = min(C 봉 low: open ≥ close_ns[tb_idx], close ≤ close_c),
          stop = round(min(lowest, H) − buffer[k_last]), target = round(lowest + W),
          valid_until = active_from, atr_at_signal = atr[k_last], madi_id, 취소 규칙 없음.
    """
    rearm = bool(cfg.l1b_rearm)
    return _finalize(ctx, cfg, _raws(ctx, "L1b", cfg.waist_method, _raws_l1b, rearm=rearm))


def _raws_l1b(ctx: ScenarioContext, waist_method: str, rearm: bool = False) -> list[_Raw]:
    """candidates_l1b의 후보 탐지 (필터 전). rearm=False(기본)면 마디당 첫 준비 에피소드만 본다 (I-22)."""
    s_dur = C.TF_NS[ctx.s_tf]                                  # 신호 봉 길이 (ns)
    a, md, cb = _s_arrays(ctx), _madi_arrays(ctx, waist_method), _c_arrays(ctx)
    s_low, s_close, s_close_ns, v = a["low"], a["close"], a["close_ns"], a["volume"]
    c_open_ns, c_close_ns, c_low, c_close = cb["open_ns"], cb["close_ns"], cb["low"], cb["close"]
    base = cb["confirm_base"]
    n_s = s_close.shape[0]
    window_ns = C.L1B_ARM_BARS * s_dur                   # §7.2 준비 후 24개 신호 봉
    raws: list[_Raw] = []
    for r in np.flatnonzero(md["direction"] == 1):
        tb, end, b = int(md["tb_idx"][r]), int(md["end_idx"][r]), int(md["b_idx"][r])
        A, B, W, H = (float(md[k][r]) for k in ("a_price", "b_price", "w", "H"))
        vol_ab = float(md["vol_ab_mean"][r])
        zone_hi = H + C.L1B_ZONE_W * W                          # §7.2 준비 구간 [H, H + 0.25W]
        last_k = min(end, n_s - 1)                              # 살아 있는 동안만 준비 (I-22)
        death_close = int(s_close_ns[end + 1]) if end + 1 < n_s else None  # k_last(c) ≤ end ⟺ close_c < 이 시각
        c_first = int(np.searchsorted(c_open_ns, md["tb_close_ns"][r], side="left"))  # I-23 T_B 이후 C 봉
        prev_end = int(md["tb_close_ns"][r])                    # 직전 에피소드 끝 시각 (처음은 T_B)
        k = tb + 1
        while k <= last_k:
            k = max(k, int(np.searchsorted(s_close_ns, prev_end, side="right")))  # close_ns[k] > 직전 끝
            if k > last_k:
                break
            seg = s_low[k:last_k + 1]
            zone = (seg >= H) & (seg <= zone_hi)                # §7.2 준비: 저가가 [H, H + 0.25W] 안
            if not zone.any():
                break
            arm = k + int(np.argmax(zone))
            arm_close = int(s_close_ns[arm])
            window_end = arm_close + window_ns                  # §7.2 확인 C 봉 마감 ≤ 준비 + 24 S 봉
            c_lo = int(np.searchsorted(c_close_ns, arm_close, side="right"))  # 준비 봉 마감 "뒤" 마감한 C 봉 (I-22)
            c_hi = int(np.searchsorted(c_close_ns, window_end, side="right"))
            episode_end = window_end
            below = np.flatnonzero(s_close[arm + 1:min(arm + C.L1B_ARM_BARS, n_s - 1) + 1] < H)
            if below.size >= C.L1B_MAX_CLOSES_BELOW_H:          # §7.2 종가 < H 두 번째 → 폐기 (첫 이탈은 버팀)
                discard_close = int(s_close_ns[arm + 1 + below[C.L1B_MAX_CLOSES_BELOW_H - 1]])
                c_hi = min(c_hi, int(np.searchsorted(c_close_ns, discard_close, side="left")))  # 같은 시각이면 폐기 우선
                episode_end = min(episode_end, discard_close)
            if death_close is not None:                         # 마디 사망·300봉 만료: k_last(c) ≤ end_idx 까지만
                c_hi = min(c_hi, int(np.searchsorted(c_close_ns, death_close, side="left")))
                episode_end = min(episode_end, death_close)
            ok = base[c_lo:c_hi] & (c_close[c_lo:c_hi] > H)      # §7.2 확인: 양봉, > 직전 C 고가, 종가 > H
            if not ok.any():
                if not rearm:
                    break                                       # §7.2 폐기(창 끝·두 번째 이탈·사망) → 이 마디의 L1b 끝
                prev_end = episode_end                          # (진단) 에피소드 끝 뒤에 다시 준비
                k = arm + 1
                continue
            ci = c_lo + int(np.argmax(ok))
            close_c = int(c_close_ns[ci])
            k_last = int(np.searchsorted(s_close_ns, close_c, side="right")) - 1  # I-15 확인 시각에 마감된 마지막 S 봉
            lowest = float(c_low[c_first:ci + 1].min())         # I-23 T_B 이후 최저가 (C 봉 저가)
            health = float(v[b + 1:k_last + 1].mean())          # §7.2 건강한 조정을 확인 시점에 검사
            sc = [Reason.SC_UNHEALTHY] if health >= vol_ab else []
            meta = _madi_meta(md, r, waist_method)
            meta.update({"k_last": k_last, "arm_idx": arm, "arm_known_ns": arm_close, "c_idx": ci,
                         "lowest": lowest, "health_vol_mean": health})
            raws.append(_Raw(
                s_idx=k_last, signal_time=close_c, basis=str(md["madi_id"][r]), madi_id=str(md["madi_id"][r]),
                sc=sc,
                entry=C.round_price(c_close[ci] * C.L1B_CAP_MULT),              # §7.2 상한 지정가 = 확인 종가 × 1.001
                stop=C.round_price(min(lowest, H) - a["buffer"][k_last]),       # §7.2 min(T_B 이후 최저가, H) − b
                target=C.round_price(lowest + W),                               # §7.2 (T_B 이후 최저가) + W
                atr=float(a["atr"][k_last]),                                    # §12.2 확인 시점의 신호 봉 ATR
                valid_until=None, meta=meta))                                   # I-44 IOC: 첫 실행 봉만
            if not rearm:
                break                                           # I-22 마디당 준비 1회: 확인 → 신호 1개로 끝
            prev_end = close_c                                  # (진단) 확인 1회로 에피소드 끝, 그 뒤 재준비
            k = arm + 1
    return raws


def candidates_s2(ctx: ScenarioContext, cfg: ComboConfig) -> list[Candidate]:
    """§7.3 S2 조정 중 급증 음봉 이탈 매도 (I-24, I-47).

    후보: S 봉 t에서 m = paint_alive(상승, start_offset=1)[t] ≥ 0 이고
          close[t] < open[t] and vr[t] ≥ 2(S2_VR_MIN 고정) and close[t] < H(m).
    사유: F1~F6 (F7 적용 안 함), RISK_*.
    계획: side −1, 'limit', entry = H, stop = round(max(high[t], H + 0.5 × atr[t]) + buffer[t]), target = round(A),
          valid_until = close_ns[t] + 12 × S 길이, madi_id = m의 ID.
    취소 규칙(k = t+1..t+12): close[k] > B ('close_above').
    """
    return _finalize(ctx, cfg, _raws(ctx, "S2", cfg.waist_method, _raws_s2))


def _raws_s2(ctx: ScenarioContext, waist_method: str) -> list[_Raw]:
    """candidates_s2의 후보 탐지 (필터 전)."""
    s_dur = C.TF_NS[ctx.s_tf]                                  # 신호 봉 길이 (ns)
    a, md = _s_arrays(ctx), _madi_arrays(ctx, waist_method)
    o, h, c, vr = a["open"], a["high"], a["close"], a["vr"]
    n = c.shape[0]
    key = ("alive_after", 1)
    if key not in ctx.cache:                                    # I-24 확정 "후"만 (tb 봉 자신 제외)
        ctx.cache[key] = ST.paint_alive(ctx.s_struct.madis, n, 1, start_offset=1)
    alive = ctx.cache[key]
    h_m = np.where(alive >= 0, md["H"][np.clip(alive, 0, None)] if md["H"].size else np.nan, np.nan)
    with np.errstate(invalid="ignore"):
        cand = (alive >= 0) & (c < o) & (vr >= C.S2_VR_MIN) & (c < h_m)  # §7.3 음봉, VR ≥ 2, 종가 < H
    n_valid = C.S2_VALID_BARS
    raws: list[_Raw] = []
    for t in np.flatnonzero(cand):
        t = int(t)
        r = int(alive[t])
        A, B, W, H = (float(md[k][r]) for k in ("a_price", "b_price", "w", "H"))
        k_hi = min(t + n_valid, n - 1)
        cancel_k, kind = _cancel_scan({"close_above": c[t + 1:k_hi + 1] > B}, t)  # I-47 종가 > B → 취소
        signal_time = int(a["close_ns"][t])
        meta = _madi_meta(md, r, waist_method)
        meta["x_high"] = float(h[t])
        raws.append(_Raw(
            s_idx=t, signal_time=signal_time, basis=str(md["madi_id"][r]), madi_id=str(md["madi_id"][r]), sc=[],
            entry=H,                                                                            # §7.3 지정가 매도 @ H
            stop=C.round_price(max(h[t], H + C.S2_STOP_ATR_MULT * a["atr"][t]) + a["buffer"][t]),  # §7.3 손절
            target=C.round_price(A),                                                            # §7.3 목표 A
            atr=float(a["atr"][t]),
            valid_until=signal_time + n_valid * s_dur,                                   # §7.3 유효 12봉
            cancel_rules=(CancelRule("close_above", B, "종가 > B"),), cancel_k=cancel_k, cancel_kind=kind,
            meta=meta))
    return raws


def s3_support(ctx: ScenarioContext) -> np.ndarray:
    """§7.4 지지선 (I-25): 봉 t마다 지지선 스윙 저점 번호 i (없으면 −1). ctx.cache에 캐시.

    i = 스윙 저점 중 i ∈ [t−100, t−1], i + 3 ≤ t(확정), 봉 j ∈ [t−100, t−1]의 low가 |low[j] − low[i]| ≤ 0.001 × low[i]
        인 봉 수(스윙 봉 자신 포함) ≥ 2 인 것들 중 가장 큰 i.
    """
    key = ("s3_support",)
    if key in ctx.cache:
        return ctx.cache[key]
    low = _s_arrays(ctx)["low"]
    n = low.shape[0]
    look, k = C.S3_LOOKBACK, C.SWING_K
    support = np.full(n, -1, dtype=np.int64)
    for i in np.flatnonzero(ctx.s_struct.is_sl):                # 오름차순 → 뒤(더 최근) 스윙이 덮어씀
        i = int(i)
        t_lo, t_hi = i + k, min(i + look, n - 1)                # i+3 ≤ t (확정), i ≥ t−100
        if t_lo > t_hi:
            continue
        j_lo = max(t_lo - look, 0)
        seg = low[j_lo:t_hi]                                    # 봉 j ∈ [j_lo, t_hi − 1]
        touch = np.abs(seg - low[i]) <= C.S3_TOUCH_TOL * low[i]  # §7.4 저가가 S ± 0.1% 안
        cs = np.r_[0, np.cumsum(touch)]
        ts = np.arange(t_lo, t_hi + 1, dtype=np.int64)
        cnt = cs[ts - j_lo] - cs[np.maximum(ts - look, 0) - j_lo]  # 창 [t−100, t−1]의 터치 수
        support[ts[cnt >= C.S3_MIN_TOUCHES]] = i                # §7.4 2번 이상 → 지지선 후보, 가장 최근 것
    ctx.cache[key] = support
    return support


def candidates_s3(ctx: ScenarioContext, cfg: ComboConfig) -> list[Candidate]:
    """§7.4 S3 지지 이탈 매도 (I-25, I-47).

    지지선 S(봉 t): 스윙 저점 i ∈ [t−100, t−1], i + 3 ≤ t 중, 봉 j ∈ [t−100, t−1]의 low가
          |low[j] − low[i]| ≤ 0.001 × low[i] 인 봉 수 ≥ 2 인 것들 중 i가 가장 큰 것. S = low[i].
    이탈(후보): close[t] < S and (vr[t] ≥ 2(S3_VR_MIN 고정) or n_prev == 1),
          n_prev = [t−9, t−1] 중 close < S 인 봉 수 (= 이번이 최근 10봉 안 두 번째 종가 이탈).
    사유: 상승 마디가 하나라도 확정돼 있으면(most_recent_confirmed ≥ 0) close[t] ≥ 그 허리 → SC_CLOSE_VS_WAIST;
          목표 없음 → SC_NO_TARGET; F1~F7, RISK_*.
    목표: 봉 t까지 확정된 모든 스윙 저점 중 low < S 인 것의 최댓값 (기간 제한 없음).
    계획: side −1, 'limit', entry = round(S), stop = round(S + atr[t]), target = round(목표),
          valid_until = close_ns[t] + 12 × S 길이, madi_id = None (F8 대상 아님, I-19), meta['support_idx'] = i.
    취소 규칙(k = t+1..t+12): close[k] > S ('close_above').
    """
    return _finalize(ctx, cfg, _raws(ctx, "S3", cfg.waist_method, _raws_s3))


def _raws_s3(ctx: ScenarioContext, waist_method: str) -> list[_Raw]:
    """candidates_s3의 후보 탐지 (필터 전)."""
    s_dur = C.TF_NS[ctx.s_tf]                                  # 신호 봉 길이 (ns)
    a, md = _s_arrays(ctx), _madi_arrays(ctx, waist_method)
    low, c, vr, close_ns = a["low"], a["close"], a["vr"], a["close_ns"]
    n = c.shape[0]
    sup = s3_support(ctx)
    s_lvl = np.where(sup >= 0, low[np.clip(sup, 0, None)], np.nan)
    win = C.S3_REBREAK_WINDOW - 1                               # 직전 9봉 [t−9, t−1]
    n_prev = np.zeros(n, dtype=np.int64)
    with np.errstate(invalid="ignore"):
        for d in range(1, win + 1):
            n_prev[d:] += c[:-d] < s_lvl[d:]                    # 지금 지지선 기준 과거 종가 이탈 수
        cand = (sup >= 0) & (c < s_lvl) & ((vr >= C.S3_VR_MIN) | (n_prev == 1))  # §7.4 이탈, I-25
    mrc = ST.most_recent_confirmed(ctx.s_struct.madis, n, 1)    # I-25 확정된 가장 최근 상승 마디(생존 무관)
    sw_idx = np.flatnonzero(ctx.s_struct.is_sl)
    sw_low = low[sw_idx]
    k = C.SWING_K
    n_valid = C.S3_VALID_BARS
    raws: list[_Raw] = []
    for t in np.flatnonzero(cand):
        t = int(t)
        i = int(sup[t])
        S = float(low[i])
        sc = []
        meta = {"support_idx": i, "S": S, "support_known_ns": int(close_ns[i + k]), "n_prev": int(n_prev[t])}
        m = int(mrc[t])
        if m >= 0:
            meta.update({"waist_madi_id": str(md["madi_id"][m]), "waist_madi_H": float(md["H"][m]),
                         "waist_madi_known_ns": int(md["tb_close_ns"][m])})
            if not c[t] < md["H"][m]:
                sc.append(Reason.SC_CLOSE_VS_WAIST)             # §7.4 종가 < 가장 최근 상승 마디 허리
        lim = int(np.searchsorted(sw_idx, t - k, side="right"))  # t 시점 확정된 스윙 저점 (i + 3 ≤ t)
        below = sw_low[:lim] < S
        target = None
        if below.any():
            pick = int(np.argmax(np.where(below, sw_low[:lim], -np.inf)))  # §7.4 S 아래 가장 가까운 스윙 저점
            tgt_i = int(sw_idx[pick])
            target = C.round_price(low[tgt_i])
            meta.update({"target_idx": tgt_i, "target_known_ns": int(close_ns[tgt_i + k])})
        else:
            sc.append(Reason.SC_NO_TARGET)                      # §7.4 없으면 신호 폐기
        k_hi = min(t + n_valid, n - 1)
        cancel_k, kind = _cancel_scan({"close_above": c[t + 1:k_hi + 1] > S}, t)  # I-47 종가 > S → 취소
        signal_time = int(close_ns[t])
        raws.append(_Raw(
            s_idx=t, signal_time=signal_time, basis=f"sup{i}", madi_id=None, sc=sc,  # I-19 S3는 마디 근거 아님
            entry=C.round_price(S),                                         # §7.4 지정가 매도 @ S
            stop=C.round_price(S + a["atr"][t]),                            # §7.4 손절 S + ATR
            target=target,
            atr=float(a["atr"][t]),
            valid_until=signal_time + n_valid * s_dur,               # §7.4 유효 12봉
            cancel_rules=(CancelRule("close_above", S, "종가 > S"),), cancel_k=cancel_k, cancel_kind=kind,
            meta=meta))
    return raws
