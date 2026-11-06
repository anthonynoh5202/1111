"""out/results_{full,dir,none}.json, out/fwd_check.json → out/tables.md (A2_setups.md 표 원본)."""
from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
SETUPS = ("S1L", "S1S", "S2L", "S2S", "S3")
VARS = ("V1", "V2", "V3", "V4")
NAMES = {"S1L": "S1 롱", "S1S": "S1 숏", "S2L": "S2 롱", "S2S": "S2 숏", "S3": "S3 숏"}
VNAMES = {"V1": "구조손절·2R", "V2": "구조손절·구조목표", "V3": "절대손절·2R", "V4": "절대손절·구조목표"}


def f(x, nd=2, sign=False):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—" if x is None or math.isnan(x) else "∞"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def detail(res, per):
    lines = [f"| 설정 | 변형 | 거래 | 승률 | 평균 이익R | 평균 손실R | 기대값R [95% CI] | PF | 최대낙폭R | 보유(h) | 비용R | 월 신호 | 무작위 평균R | p |",
             "|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s in SETUPS:
        for v in VARS:
            c = res["combos"].get(f"{s}-{v}", {})
            m = c.get(per, {})
            if not m or m.get("n", 0) == 0:
                lines.append(f"| {NAMES[s]} | {v} {VNAMES[v]} | 0 | | | | | | | | | {f(m.get('signals_per_month', 0.0), 2)} | | |")
                continue
            ci = f"{f(m['exp'], 2, True)} [{f(m['ci_lo'], 2, True)}, {f(m['ci_hi'], 2, True)}]"
            lines.append(
                f"| {NAMES[s]} | {v} {VNAMES[v]} | {m['n']} | {100 * m['win']:.0f}% | {f(m['avg_win'], 2)} | "
                f"{f(m['avg_loss'], 2)} | {ci} | {f(m['pf'], 2)} | {f(m['mdd'], 1)} | {f(m.get('hold_h'), 0)} | "
                f"{f(m.get('avg_cost_r'), 2)} | {f(m['signals_per_month'], 2)} | {f(m.get('rand_mean'), 2, True)} | "
                f"{f(m.get('p_vs_rand'), 3)} |")
    return "\n".join(lines)


def compact(res):
    lines = ["| 설정 | 변형 | IS 거래 | IS 기대값R | IS p | OOS 거래 | OOS 기대값R | OOS PF | OOS 무작위R | OOS p |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in SETUPS:
        for v in VARS:
            c = res["combos"].get(f"{s}-{v}", {})
            i, o = c.get("IS", {}), c.get("OOS", {})
            lines.append(f"| {NAMES[s]} | {v} | {i.get('n', 0)} | {f(i.get('exp', float('nan')), 2, True)} | "
                         f"{f(i.get('p_vs_rand'), 3)} | {o.get('n', 0)} | {f(o.get('exp', float('nan')), 2, True)} | "
                         f"{f(o.get('pf', float('nan')), 2)} | {f(o.get('rand_mean'), 2, True)} | {f(o.get('p_vs_rand'), 3)} |")
    return "\n".join(lines)


def judge(res):
    """사전 기준: IS·OOS 기대값 > 0, OOS 거래 ≥ 30, OOS PF ≥ 1.2, OOS p(무작위) < 0.05, IS p < 0.05."""
    ok = []
    for k, c in res["combos"].items():
        i, o = c.get("IS", {}), c.get("OOS", {})
        if (i.get("n", 0) >= 30 and o.get("n", 0) >= 30 and i.get("exp", -1) > 0 and o.get("exp", -1) > 0
                and o.get("pf", 0) >= 1.2 and o.get("p_vs_rand", 1) < 0.05 and i.get("p_vs_rand", 1) < 0.05):
            ok.append(k)
    return ok


def main():
    parts = []
    for lv in ("full", "dir", "none"):
        res = json.loads((OUT / f"results_{lv}.json").read_text())
        parts.append(f"## level={lv}\n")
        parts.append(f"합격 조합: {judge(res) or '없음'}\n")
        parts.append(f"국면 비율(시간 중 %): " + ", ".join(
            f"{k} IS {100 * v['IS']:.1f}% / OOS {100 * v['OOS']:.1f}%" for k, v in res["regime_share"].items()) + "\n")
        parts.append(f"진입 신호가 하나라도 나온 시간(S1·S2 롱숏 V1 합): " + ", ".join(
            f"{p} {v['signal_hours']}시간/{v['hours']}시간 = {100 * v['share']:.2f}% (월 {v['per_month']:.1f}회)"
            for p, v in res["any_signal"].items()) + "\n")
        parts.append("### IS\n" + detail(res, "IS") + "\n")
        parts.append("### OOS\n" + detail(res, "OOS") + "\n")
        parts.append("### 요약\n" + compact(res) + "\n")
        # 부가: 비용 전 기대값, 종료 비율, 연도별
        extra = ["| 설정-변형 | 기간 | 비용 전 기대값R | 비용R | 펀딩R | 손절/목표/시간 종료 | 평균 손절폭% | 손절폭/ATR(중앙) | 연도별 기대값R(거래) |",
                 "|---|---|---:|---:|---:|---|---:|---:|---|"]
        for k, c in res["combos"].items():
            for per in ("IS", "OOS"):
                m = c.get(per, {})
                if not m or m.get("n", 0) == 0:
                    continue
                es = m["exit_share"]
                yrs = ", ".join(f"{y}:{f(d['exp'], 2, True)}({d['n']})" for y, d in m["by_year"].items())
                extra.append(f"| {k} | {per} | {f(m['gross_exp'], 2, True)} | {f(m['avg_cost_r'], 2)} | "
                             f"{f(m['avg_fund_r'], 3, True)} | {100 * es['stop']:.0f}/{100 * es['target']:.0f}/{100 * es['time']:.0f}% | "
                             f"{100 * m['avg_d_pct']:.2f} | {f(m['med_d_atr'], 2)} | {yrs} |")
        parts.append("### 부가\n" + "\n".join(extra) + "\n")
        parts.append("### 신호 단계 통계\n```\n" + json.dumps(res["stats"], ensure_ascii=False) + "\n```\n")
    fw = json.loads((OUT / "fwd_check.json").read_text())
    lines = ["| 단계 | 설정 | 기간 | 신호 | 4h 평균(무작위) p | 24h 평균(무작위) p | 72h 평균(무작위) p |", "|---|---|---|---:|---|---|---|"]
    for k, r in fw.items():
        lv, s, per = k.split("|")
        cells = [f"{f(r[f'h{h}']['mean'], 2, True)} ({f(r[f'h{h}']['rand'], 2, True)}) {f(r[f'h{h}']['p'], 3)}" for h in (4, 24, 72)]
        lines.append(f"| {lv} | {NAMES[s]} | {per} | {r['n']} | " + " | ".join(cells) + " |")
    parts.append("## 비용 전 방향성 점검 (ATR 단위)\n" + "\n".join(lines) + "\n")
    (OUT / "tables.md").write_text("\n".join(parts))
    print((OUT / "tables.md").read_text()[:200])


if __name__ == "__main__":
    main()
