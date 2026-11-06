"""A1 §2·§4·§5·§6 표 만들기(마크다운 출력). 입력: out/stops.json, out/dstop_{1h,4h}.npy (a1_stops.py 결과).

실행: /home/user/1111/.venv/bin/python -I A1/a1_tables.py > A1/out/tables.md
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

S = json.loads((C.OUT_DIR / "stops.json").read_text())
E0 = C.ACCOUNT_USDT
COST = C.COST_ALL_MARKET          # 0.14% 왕복
FUND = S["funding"]


def min_qty(price: float, min_notional: float, step: float = C.BTC_STEP) -> float:
    return max(step, math.ceil(min_notional / price / step - 1e-9) * step)


def lev_min_for(notional: float, equity: float) -> int:
    room = equity - notional * (C.TAKER + C.SLIP)
    return math.ceil(notional / room - 1e-9)


def lev_allowed(d: float, side: str = "long") -> int:
    req = max(LIQ_MULT * d, d + LIQ_GAP)
    return min(LEV_CAP, C.max_lev_for_liq(req, side))


def table_min_position() -> str:
    rows = ["| BTC 가격 | 최소 수량(50 USDT 규칙, 지금) | 포지션 금액 | 5만 원 계좌 필요 최소 레버리지 | 20배일 때 증거금(계좌 대비) | (구 규칙 100 USDT) 최소 수량 · 금액 · 최소 레버리지 |",
            "|---:|---:|---:|---:|---:|---:|"]
    for p in (50_000, 60_000, 70_000, 80_000, C.REF_PRICE, 90_000, 99_000, 100_000, 110_000, 120_000):
        q50 = min_qty(p, C.BTC_MIN_NOTIONAL_NOW)
        n50 = q50 * p
        q100 = min_qty(p, C.BTC_MIN_NOTIONAL_OLD)
        n100 = q100 * p
        rows.append(f"| {p:,.0f} | {q50:.3f} BTC | {n50:,.1f} USDT ({C.krw(n50)/1e4:,.1f}만 원) | {lev_min_for(n50, E0)}배 "
                    f"| {n50/20:.2f} USDT ({n50/20/E0*100:.0f}%) | {q100:.3f} · {n100:,.1f} · {lev_min_for(n100, E0)}배 |")
    return "\n".join(rows)


def stop_quantiles(tf: str) -> dict:
    x = S[tf]["d_both"]
    return {"p25": x["p25"], "p50": x["p50"], "p75": x["p75"]}


def table_loss_per_stop() -> str:
    hold = {"1h": S["1h"]["baseline_2R"]["long"]["hours_resolved"]["p50"],
            "4h": S["4h"]["baseline_2R"]["long"]["hours_resolved"]["p50"]}
    rows = ["| 봉 | 손절 폭(분위) | 포지션 | 손절 시 손실(비용 포함) | 계좌 대비 | 비용 ÷ R | 펀딩(중앙 보유 시간, 평균 요율) ÷ R |",
            "|---|---:|---|---:|---:|---:|---:|"]
    for tf in ("1h", "4h"):
        qs = stop_quantiles(tf)
        for lab, d in qs.items():
            for qname, qty, price in (("0.001 BTC @83,461", 0.001, C.REF_PRICE), ("0.001 BTC @110,000", 0.001, 110_000.0),
                                      ("0.002 BTC @83,461(구 규칙)", 0.002, C.REF_PRICE)):
                n = qty * price
                fund = FUND["mean"] * hold[tf] / 8
                loss = n * (d + COST + fund)
                rows.append(f"| {tf} | {lab} {d*100:.2f}% | {qname} = {n:,.1f} USDT | {loss:.2f} USDT ({C.krw(loss):,.0f}원) "
                            f"| **{loss/E0*100:.1f}%** | {COST/(d+COST+fund)*100:.0f}% | {fund/(d+COST+fund)*100:.1f}% |")
    return "\n".join(rows)


def table_funding() -> str:
    rows = ["| 보유 시간 | 펀딩 횟수 | 평균 요율(0.0064%/8h) 비용 | 90% 분위(0.0100%) | 99% 분위(0.0467%) | 0.001 BTC(83.5 USDT) 평균 비용 | 1h 중앙 손절(1.0%) R 대비 | 4h 중앙 손절(2.2%) R 대비 |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    n = 0.001 * C.REF_PRICE
    d1, d4 = S["1h"]["d_both"]["p50"], S["4h"]["d_both"]["p50"]
    for h in (8, 24, 72, 168):
        k = h / 8
        m, p90, p99 = FUND["mean"] * k, FUND["p90"] * k, FUND["p99"] * k
        rows.append(f"| {h}시간 | {k:.0f}회 | {m*100:.3f}% | {p90*100:.3f}% | {p99*100:.3f}% | {n*m:.4f} USDT ({C.krw(n*m):.0f}원) "
                    f"| {m/(d1+COST)*100:.1f}% | {m/(d4+COST)*100:.1f}% |")
    return "\n".join(rows)


def table_leverage() -> str:
    d1, d4 = S["1h"]["d_both"]["p50"], S["4h"]["d_both"]["p50"]
    n = 0.001 * C.REF_PRICE
    rows = ["| 설정 레버리지 | 청산까지 거리 롱 / 숏 | 1h 중앙 손절(1.0%) 대비 | 4h 중앙 손절(2.2%) 대비 | 0.001 BTC 증거금(= 손절 실패 시 최대 손실) | 계좌(35.7) 대비 | 규칙 통과(1h / 4h) |",
            "|---:|---:|---:|---:|---:|---:|:---:|"]
    for L in (1, 2, 3, 5, 10, 15, 17, 20, 25, 50, 75, 100, 125, 150):
        dl, ds = C.liq_distance(L, "long"), C.liq_distance(L, "short")
        if dl >= 0.999:
            dls = "청산 없음(가격 0)"
        else:
            dls = f"−{dl*100:.1f}%"
        req1, req4 = max(LIQ_MULT * d1, d1 + LIQ_GAP), max(LIQ_MULT * d4, d4 + LIQ_GAP)
        ok1 = "✓" if min(dl, ds) >= req1 else "✗"
        ok4 = "✓" if min(dl, ds) >= req4 else "✗"
        m = n / L
        rows.append(f"| {L}배 | {dls} / +{ds*100:.1f}% | {min(dl, ds)/d1:.1f}배 | {min(dl, ds)/d4:.1f}배 | {m:.2f} USDT ({C.krw(m):,.0f}원) "
                    f"| {m/E0*100:.0f}% | {ok1} / {ok4} |")
    return "\n".join(rows)


def table_overshoot() -> str:
    rows = ["| 봉·방향 | 손절 횟수 | 손절 뒤 더 밀린 폭 p50 / p99 / p99.9 / 최대 (같은 1분) | ≥1% / ≥2% / ≥3% 비율 (같은 1분) | ≥3% 비율 (5분 안 / 60분 안) | ≥5% 비율 (60분 안) |",
            "|---|---:|---:|---:|---:|---:|"]
    for tf in ("1h", "4h"):
        for side in ("long", "short"):
            b = S[tf]["baseline_2R"][side]
            o1, o5, o60 = (b["overshoot_after_stop"][k] for k in ("ov1", "ov5", "ov60"))
            rows.append(f"| {tf} {'롱' if side=='long' else '숏'} | {b['n_stop']:,} | {o1['p50']*100:.2f}% / {o1['p99']*100:.2f}% / {o1['p99_9']*100:.2f}% / {o1['max']*100:.2f}% "
                        f"| {o1['share_ge_1']*100:.2f}% / {o1['share_ge_2']*100:.2f}% / {o1['share_ge_3']*100:.2f}% "
                        f"| {o5['share_ge_3']*100:.2f}% / {o60['share_ge_3']*100:.2f}% | {o60['share_ge_5']*100:.2f}% |")
    return "\n".join(rows)


def table_rule_lev_by_stop() -> str:
    rows = ["| 손절 거리 | 필요한 청산 거리 = max(2×손절, 손절+3%p) | 허용 최대 레버리지(상한 20) | 0.001 BTC 증거금 | 증거금 ÷ 손절 손실(R) |",
            "|---:|---:|---:|---:|---:|"]
    n = 0.001 * C.REF_PRICE
    for d in (0.003, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.04, 0.06, 0.08):
        req = max(LIQ_MULT * d, d + LIQ_GAP)
        L = lev_allowed(d)
        m = n / L
        r = n * (d + COST)
        rows.append(f"| {d*100:.2f}% | {req*100:.1f}% | {L}배 | {m:.2f} USDT | {m/r:.1f}R |")
    return "\n".join(rows)


def feasible_share() -> str:
    rows = ["| 봉 | 손절 폭 표본 | 최소 수량(0.001 BTC)일 때 계좌 위험 ≤ 1% | ≤ 2% | ≤ 3% | ≤ 5% | 위험 중앙값 |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    n = 0.001 * C.REF_PRICE
    for tf in ("1h", "4h"):
        d = np.load(C.OUT_DIR / f"dstop_{tf}.npy")
        risk = n * (d + COST) / E0
        rows.append(f"| {tf} | {d.size:,} | {(risk <= 0.01).mean()*100:.0f}% | {(risk <= 0.02).mean()*100:.0f}% | {(risk <= 0.03).mean()*100:.0f}% "
                    f"| {(risk <= 0.05).mean()*100:.0f}% | {np.median(risk)*100:.1f}% |")
    return "\n".join(rows)


def table_capital() -> str:
    """(c) 자금별: 0.001 BTC 최소 단위로 1~2% 위험 관리가 되나."""
    rows = ["| 계좌 | USDT | 1h 중앙 손절(1.0%) 최소 수량 손실 → 계좌 대비 | 4h 중앙 손절(2.2%) → 계좌 대비 | 1% 위험이면 수량(1h / 4h) | 2% 위험이면 수량(1h / 4h) | 1~2% 관리 가능? |",
            "|---:|---:|---:|---:|---:|---:|---|"]
    d1, d4 = S["1h"]["d_both"]["p50"], S["4h"]["d_both"]["p50"]
    n = 0.001 * C.REF_PRICE
    for krw in (50_000, 100_000, 200_000, 400_000, 500_000, 1_000_000, 2_000_000):
        e = krw / C.KRW_PER_USDT
        l1, l4 = n * (d1 + COST), n * (d4 + COST)
        def q(risk, d):
            raw = e * risk / (C.REF_PRICE * (d + COST))
            return math.floor(raw / 0.001 + 1e-9) * 0.001
        q11, q14, q21, q24 = q(0.01, d1), q(0.01, d4), q(0.02, d1), q(0.02, d4)
        def fmt(x):
            return f"{x:.3f}" if x >= 0.001 else "0(불가)"
        ok1 = l1 / e <= 0.02
        ok4 = l4 / e <= 0.02
        verdict = ("1h·4h 모두 가능" if ok1 and ok4 and q14 >= 0.001 else
                   "1h만 2% 이내, 4h는 초과" if ok1 and not ok4 else
                   "1h는 2% 이내(1%는 불가), 4h는 초과" if ok1 else "둘 다 2% 초과(강제 위험)")
        if ok1 and ok4 and q14 < 0.001:
            verdict = "1h 가능, 4h는 2%에서만"
        rows.append(f"| {krw/10000:,.0f}만 원 | {e:,.1f} | {l1:.2f} USDT → {l1/e*100:.1f}% | {l4:.2f} USDT → {l4/e*100:.1f}% "
                    f"| {fmt(q11)} / {fmt(q14)} | {fmt(q21)} / {fmt(q24)} | {verdict} |")
    return "\n".join(rows)


def table_eth() -> str:
    """(b) ETHUSDT: 최소 20 USDT, 0.001 ETH 단위. ETH 손절 폭 = BTC × 1.4(가정), 가격 1,900(추정)."""
    eth_px = 1_900.0
    ratio = 1.4
    rows = ["| 봉 | ETH 손절 폭(가정 = BTC×1.4) | 1% 위험(0.36 USDT) 포지션 | 2% 위험(0.71 USDT) 포지션 | 최소 20 USDT 통과? (1% / 2%) |",
            "|---|---:|---:|---:|---|"]
    for tf in ("1h", "4h"):
        d = S[tf]["d_both"]["p50"] * ratio
        n1 = E0 * 0.01 / (d + COST)
        n2 = E0 * 0.02 / (d + COST)
        q1 = math.floor(n1 / eth_px / 0.001) * 0.001
        q2 = math.floor(n2 / eth_px / 0.001) * 0.001
        rows.append(f"| {tf} | {d*100:.2f}% | {n1:.1f} USDT ({q1:.3f} ETH) | {n2:.1f} USDT ({q2:.3f} ETH) "
                    f"| {'✓' if q1*eth_px >= 20 else '✗'} / {'✓' if q2*eth_px >= 20 else '✗'} |")
    return "\n".join(rows)


def baseline_table() -> str:
    rows = ["| 봉·방향 | 진입 표본 | 2R 목표 먼저 | 손절 먼저 | 30일 내 미결 | 평균 R(비용 전) | 결판까지 중앙 / 평균 / p90 시간 |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for tf in ("1h", "4h"):
        for side in ("long", "short"):
            b = S[tf]["baseline_2R"][side]
            n = b["n_entries"]
            h = b["hours_resolved"]
            rows.append(f"| {tf} {'롱' if side=='long' else '숏'} | {n:,} | {b['n_tp']/n*100:.1f}% | {b['n_stop']/n*100:.1f}% | {b['n_open']/n*100:.1f}% "
                        f"| {b['mean_r_gross_all']:+.3f}R | {h['p50']:.0f} / {h['mean']:.0f} / {h['p90']:.0f}시간 |")
    return "\n".join(rows)


def dist_table() -> str:
    rows = ["| 봉 | 항목 | 10% | 25% | 중앙값 | 75% | 90% | 평균 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    names = {"atr_pct": "ATR14(%)", "d_long": "롱 손절: 최근 확정 스윙 저점까지(%)", "d_short": "숏 손절: 최근 확정 스윙 고점까지(%)",
             "d_both": "롱·숏 합친 손절 폭(%)", "d_long_in_atr": "롱 손절 ÷ ATR(배)", "d_short_in_atr": "숏 손절 ÷ ATR(배)"}
    for tf in ("1h", "4h"):
        for k, lab in names.items():
            x = S[tf][k]
            mult = 1 if "in_atr" in k else 100
            fmt = (lambda v: f"{v*mult:.2f}")
            rows.append(f"| {tf} | {lab} | {fmt(x['p10'])} | {fmt(x['p25'])} | **{fmt(x['p50'])}** | {fmt(x['p75'])} | {fmt(x['p90'])} | {fmt(x['mean'])} |")
    yr = ["| 봉 | 연도 | ATR14 중앙(%) | 롱 손절 중앙(%) | 숏 손절 중앙(%) |", "|---|---|---:|---:|---:|"]
    for tf in ("1h", "4h"):
        for y, v in S[tf]["yearly"].items():
            yr.append(f"| {tf} | {y} | {v['atr_pct_p50']*100:.2f} | {v['d_long_p50']*100:.2f} | {v['d_short_p50']*100:.2f} |")
    return "\n".join(rows) + "\n\n" + "\n".join(yr)


if __name__ == "__main__":
    print("## min_position\n" + table_min_position())
    print("\n## dist\n" + dist_table())
    print("\n## loss_per_stop\n" + table_loss_per_stop())
    print("\n## feasible_share\n" + feasible_share())
    print("\n## funding\n" + table_funding())
    print("\n## leverage\n" + table_leverage())
    print("\n## overshoot\n" + table_overshoot())
    print("\n## rule_lev_by_stop\n" + table_rule_lev_by_stop())
    print("\n## capital\n" + table_capital())
    print("\n## eth\n" + table_eth())
    print("\n## baseline\n" + baseline_table())
    print("\nfunding stats:", {k: v for k, v in FUND.items()})


def table_min_account() -> str:
    """0.001 BTC 최소 단위로 '1회 위험 ≤ X%'를 지키려면 계좌가 얼마여야 하나(손절 폭 분위별)."""
    n = 0.001 * C.REF_PRICE
    rows = ["| 봉 | 손절 폭 | 0.001 BTC 손절 손실 | 위험 0.5%면 필요 계좌 | 1% | 2% |", "|---|---:|---:|---:|---:|---:|"]
    hold = {"1h": S["1h"]["baseline_2R"]["long"]["hours_resolved"]["p50"],
            "4h": S["4h"]["baseline_2R"]["long"]["hours_resolved"]["p50"]}
    for tf in ("1h", "4h"):
        for lab, d in stop_quantiles(tf).items():
            loss = n * (d + COST + FUND["mean"] * hold[tf] / 8)
            cells = [f"{C.krw(loss / x)/1e4:,.1f}만 원" for x in (0.005, 0.01, 0.02)]
            rows.append(f"| {tf} | {lab} {d*100:.2f}% | {loss:.2f} USDT | " + " | ".join(cells) + " |")
    return "\n".join(rows)


if __name__ == "__main__":
    print("\n## min_account\n" + table_min_account())
