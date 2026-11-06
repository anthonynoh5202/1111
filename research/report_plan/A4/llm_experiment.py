"""5번 — LLM 층(엔진 + Claude)의 가치를 재는 실험: 표본 수·검출 가능한 최소 효과·비용.

가격($/백만 토큰, platform.claude.com pricing 2026-11-06 받음: team/b_fetch/about-claude_pricing.md)
- Opus 5.5  : 입력 4, 캐시 쓰기 5분 5 / 1시간 8, 캐시 읽기 0.20, 출력 20, 배치(50%) 입력 2·출력 10
- Sonnet 5.5: 입력 2, 캐시 쓰기 2.5 / 4, 캐시 읽기 0.10, 출력 10, 배치 1·5
- Haiku 5.5 : 입력 0.10, 캐시 읽기 0.01, 출력 0.50, 배치 0.05·0.25 (프롬프트 10만 토큰 이하)
토큰 가정(추정): 고정 접두부(기준서 2개 + 지시문) ≈ 52K — 옛 Claude 토크나이저로 기준서 50.2K 측정(team/b_tok), 새 모델은 다를 수 있음.
                 매번 바뀌는 입력(사실 JSON 4K + 차트 그림 2장 × 약 1.6K) ≈ 7.5K, 출력(세 관점 설명 + 표시 목록 + 생각) ≈ 6K.
출력: out/llm_summary.json
"""
from __future__ import annotations

import json
import math

import numpy as np

import common as C
from random_baseline import load_spec, period_mask

M = 1e6
PRICE = {
    "opus": dict(inp=4.0, rd=0.20, w1h=8.0, out=20.0, b_inp=2.0, b_rd=0.10, b_out=10.0),
    "sonnet": dict(inp=2.0, rd=0.10, w1h=4.0, out=10.0, b_inp=1.0, b_rd=0.05, b_out=5.0),
    "haiku": dict(inp=0.10, rd=0.01, w1h=0.20, out=0.50, b_inp=0.05, b_rd=0.005, b_out=0.25),
}
TOK = dict(prefix=52_000, dyn=7_500, out=6_000)


def per_call(model: str, *, batch: bool, cached: bool, tok=TOK) -> float:
    p = PRICE[model]
    if batch:
        pre = tok["prefix"] * (p["b_rd"] if cached else p["b_inp"])
        return (pre + tok["dyn"] * p["b_inp"] + tok["out"] * p["b_out"]) / M
    pre = tok["prefix"] * (p["rd"] if cached else p["inp"])
    return (pre + tok["dyn"] * p["inp"] + tok["out"] * p["out"]) / M


def live_month(model: str) -> float:
    """매시간 1회(720회/월), 1시간 캐시 + 30분 갱신 요청(읽기)로 항상 적중, 하루 1번 1시간 캐시 다시 쓰기."""
    p = PRICE[model]
    calls = 720 * per_call(model, batch=False, cached=True)
    keep = 720 * (TOK["prefix"] * p["rd"] + 30 * p["inp"]) / M
    rewrite = 30 * TOK["prefix"] * p["w1h"] / M
    return calls + keep + rewrite


def paired_sigma() -> dict:
    """엔진만(A) vs 엔진+Claude(B) 짝 차이 Δ = R_B − R_A 의 표준편차(정해진 바꿈 비율 f에서).

    R2 규칙(무작위 표, OOS)의 실제 롱·숏 결과로 계산:
    - '거부'(veto): B가 A의 거래를 관망으로 바꿈 → Δ = −R_A (비율 f)
    - '뒤집기'(flip): B가 방향을 반대로 → Δ = R_반대 − R_A (비율 f)
    """
    d = load_spec("R2")
    m = period_mask(d["t_dec"], "OOS")
    rl, rs = d["r"][m, 0], d["r"][m, 1]
    ok = np.isfinite(rl) & np.isfinite(rs)
    rl, rs = rl[ok], rs[ok]
    out = {"corr_long_short_same_hour": float(np.corrcoef(rl, rs)[0, 1])}
    e_veto = float(np.mean(np.concatenate([rl, rs]) ** 2))
    e_flip = float(np.mean((rs - rl) ** 2))
    for f in (0.1, 0.2, 0.3, 0.5):
        out[f"veto_f{f}"] = math.sqrt(f * e_veto)
        out[f"flip_f{f}"] = math.sqrt(f * e_flip)
    return out


def mde(sigma: float, n_eff: float, alpha=0.05, power=0.8) -> float:
    return (C.ND.inv_cdf(1 - alpha) + C.ND.inv_cdf(power)) * sigma / math.sqrt(n_eff)


def main():
    st = json.loads((C.OUT / "stats_summary.json").read_text())
    tau = {"R1": st["overlap"]["R1"]["tau_long_h"], "R2": st["overlap"]["R2"]["tau_long_h"]}
    sig = paired_sigma()
    costs = {}
    for mdl in PRICE:
        costs[mdl] = dict(
            std_cached=per_call(mdl, batch=False, cached=True),
            std_nocache=per_call(mdl, batch=False, cached=False),
            batch_cached=per_call(mdl, batch=True, cached=True),
            batch_nocache=per_call(mdl, batch=True, cached=False),
            live_month_hourly=live_month(mdl),
        )
    # 실험 설계 후보
    hours_clean = (C.utc("2026-09-25") - C.CLEAN_START) / C.NS_HOUR      # 결과 확인에 72시간 필요
    hours_clean_aug = (C.utc("2026-09-25") - C.utc("2026-08-01")) / C.NS_HOUR
    hours_hist = (C.utc("2026-06-01") - C.utc("2020-03-01")) / C.NS_HOUR
    designs = {}
    for name, hours, spacing, arms in (
        ("E1 깨끗한 구간 2026-07-01~09-25, 4시간 간격, 원본+상하반전", hours_clean, 4, 2),
        ("E1' 더 깨끗한 구간 2026-08-01~09-25, 2시간 간격, 원본+상하반전", hours_clean_aug, 2, 2),
        ("E2 과거(익명화) 2020-03~2026-05, 24시간 간격, 익명 원본+익명 반전", hours_hist, 24, 2),
        ("E2' 과거(익명화) 2020-03~2026-05, 12시간 간격, 익명 원본만", hours_hist, 12, 1),
        ("E3 날짜 맞히기 탐침(오염 검사) 100건", None, None, 1),
        ("F  앞으로의 모의 기록 6개월(매시간, 실운영 호출로 충당)", 24 * 182, 1, 0),
        ("F' 앞으로의 모의 기록 12개월", 24 * 365, 1, 0),
    ):
        if hours is None:
            n_points = 100
            n_eff = {"R1": float("nan"), "R2": float("nan")}
        else:
            n_points = int(hours / spacing)
            # 간격이 τ보다 짧으면 독립 표본은 대략 '시간 ÷ τ'에서 멈춘다(stats_design.neff_by_spacing로 확인)
            n_eff = {k: min(n_points, hours / tau[k]) if spacing < tau[k] else n_points for k in tau}
        calls = n_points * arms
        row = dict(points=n_points, calls=calls,
                   cost_opus_batch_cached=calls * costs["opus"]["batch_cached"],
                   cost_opus_batch_nocache=calls * costs["opus"]["batch_nocache"],
                   cost_sonnet_batch_cached=calls * costs["sonnet"]["batch_cached"],
                   n_eff_R1=n_eff["R1"], n_eff_R2=n_eff["R2"])
        for k in ("R1", "R2"):
            for lab, s in (("veto30", sig["veto_f0.3"]), ("flip20", sig["flip_f0.2"])):
                row[f"mde_{k}_{lab}"] = mde(s, n_eff[k]) if np.isfinite(n_eff[k]) else float("nan")
        designs[name] = row
    out = dict(tokens=TOK, price=PRICE, costs=costs, paired_sigma=sig, tau=tau, designs=designs,
               hours=dict(clean=hours_clean, clean_aug=hours_clean_aug, hist=hours_hist))
    (C.OUT / "llm_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float))
    print(json.dumps(out, ensure_ascii=False, indent=1, default=float)[:6000])


if __name__ == "__main__":
    main()
