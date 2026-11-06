"""A1 §8 보고서용 사이징·레버리지·청산가 계산식(참조 구현). 저장소 코드가 아니다 — 팀이 옮겨 쓸 기준식.

핵심 원칙
1) 수량이 먼저다: 수량 = 허용 손실 ÷ (1 BTC당 손절 손실 + 비용). 레버리지는 수량을 바꾸지 않는다.
2) 레버리지는 '의견'이 아니라 계산 결과다: 격리 증거금을 얼마나 맡길지(= 손절이 실패했을 때 최대 손실)를 정한다.
   - 청산 안전 규칙: 청산 거리 ≥ max(손절 거리 × LIQ_MULT, 손절 거리 + LIQ_GAP)
   - 그 규칙을 지키는 가장 높은 레버리지(= 가장 적은 증거금)를 쓰되 LEV_CAP을 넘지 않는다.
   - 증거금이 잔고에 안 들어가면(필요 최소 레버리지 > 허용 최대 레버리지) 진입하지 않는다.
3) 최소 수량 때문에 목표 위험보다 커지면 '강제 위험'으로 표시하고, 상한(MAX_FORCED_RISK)을 넘으면 관망.

실행하면 예시 4개를 출력한다: /home/user/1111/.venv/bin/python -I A1/a1_sizing.py
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import a1_common as C

LIQ_MULT = 2.0      # 청산 거리 ≥ 손절 거리의 2배
LIQ_GAP = 0.03      # 그리고 손절가 너머 최소 3%p(진입가 기준) 더
LEV_CAP = 20        # 설정 레버리지 상한(신규 계정 30일 20배 제한과 같은 값)
MAX_FORCED_RISK = 0.03   # 최소 수량 때문에 커진 위험의 상한(5만 원 단계). 넘으면 관망


@dataclass
class Plan:
    side: str
    equity: float
    entry: float
    stop: float
    target: float | None
    d_stop: float            # 손절 거리(진입가 대비)
    qty_target: float        # 목표 위험으로 계산한 수량(단위 내림 전)
    qty: float               # 실제 수량(단위 내림, 최소 수량 반영)
    forced_min: bool         # 최소 수량 때문에 목표보다 크게 잡힘
    notional: float
    loss_at_stop: float      # 손절 시 손실(수수료·슬리피지·예상 펀딩 포함), USDT
    risk_frac: float         # loss_at_stop ÷ 잔고
    cost_share_of_r: float   # 비용이 손실(R)에서 차지하는 비율
    gain_at_target: float | None
    lev_min: int             # 증거금이 잔고에 들어가는 최소 레버리지
    lev_max: int             # 청산 안전 규칙이 허용하는 최대 레버리지(상한 포함)
    lev: int | None          # 설정할 레버리지(None = 진입 불가)
    margin: float | None     # 격리 증거금 = 손절 실패 시 최대 손실
    liq_price: float | None
    liq_distance: float | None
    eff_leverage: float      # 계좌 기준 실효 레버리지 = 포지션 ÷ 잔고
    verdict: str             # OK / FORCED / NO_TRADE(사유)


def floor_step(x: float, step: float) -> float:
    return math.floor(x / step + 1e-9) * step


def ceil_step(x: float, step: float) -> float:
    return math.ceil(x / step - 1e-9) * step


def liq_price(entry: float, qty: float, margin: float, side: str, mmr: float = C.MMR_TIER1, cum: float = 0.0) -> float:
    """바이낸스 격리 청산가: LP = (WB + cum − s·Q·EP) / (Q·MMR − s·Q)."""
    s = 1 if side == "long" else -1
    return (margin + cum - s * qty * entry) / (qty * mmr - s * qty)


def plan_trade(equity: float, risk_target: float, entry: float, stop: float, side: str, *,
               target: float | None = None, min_notional: float = C.BTC_MIN_NOTIONAL_NOW,
               step: float = C.BTC_STEP, min_qty: float = C.BTC_STEP,
               fee_in: float = C.TAKER + C.SLIP, fee_out: float = C.TAKER + C.SLIP,
               fee_tp: float = C.MAKER, funding_8h: float = C.FUNDING_DEFAULT_8H, hold_hours: float = 12.0,
               mmr: float = C.MMR_TIER1, lev_cap: int = LEV_CAP, liq_mult: float = LIQ_MULT,
               liq_gap: float = LIQ_GAP, max_forced_risk: float = MAX_FORCED_RISK) -> Plan:
    if side not in ("long", "short"):
        raise ValueError("side")
    if (side == "long" and not stop < entry) or (side == "short" and not stop > entry):
        raise ValueError("손절가가 진입가의 반대쪽에 있어야 한다")
    d = abs(entry - stop) / entry
    # 펀딩: 롱은 양수 펀딩을 내고 숏은 받는다. 보수적으로 '내는 쪽'만 비용으로 넣는다.
    pays = (funding_8h > 0 and side == "long") or (funding_8h < 0 and side == "short")
    fund = abs(funding_8h) * hold_hours / 8 * entry if pays else 0.0
    per_unit = abs(entry - stop) + entry * fee_in + stop * fee_out + fund   # 1 BTC당 손절 시 손실
    qty_target = equity * risk_target / per_unit
    qty_min = max(min_qty, ceil_step(min_notional / entry, step))
    qty = floor_step(qty_target, step)
    forced = qty < qty_min
    if forced:
        qty = qty_min
    notional = qty * entry
    loss = qty * per_unit
    risk = loss / equity
    gain = None
    if target is not None:
        gain = qty * (abs(target - entry) - entry * fee_in - target * fee_tp - fund)
    # 레버리지
    d_liq_req = max(liq_mult * d, d + liq_gap)
    lev_max = 0
    for L in range(1, lev_cap + 1):
        if C.liq_distance(L, side, mmr) >= d_liq_req:
            lev_max = L
    open_fee = notional * fee_in
    room = equity - open_fee
    lev_min = math.ceil(notional / room - 1e-9) if room > 0 else 10**9
    verdict = "FORCED" if forced else "OK"
    lev = margin = lp = dl = None
    if lev_max == 0:
        verdict = "NO_TRADE(손절이 너무 넓어 청산 안전 규칙을 지키는 레버리지가 없음)"
    elif lev_min > lev_max:
        verdict = f"NO_TRADE(증거금 부족: 최소 {lev_min}배 필요 > 허용 {lev_max}배)"
    elif forced and risk > max_forced_risk:
        verdict = f"NO_TRADE(최소 수량 강제 위험 {risk*100:.1f}% > 상한 {max_forced_risk*100:.0f}%)"
    if not verdict.startswith("NO_TRADE"):
        lev = lev_max
        margin = notional / lev
        lp = liq_price(entry, qty, margin, side, mmr)
        dl = abs(lp - entry) / entry
    return Plan(side, equity, entry, stop, target, d, qty_target, qty, forced, notional, loss, risk,
                (loss - qty * abs(entry - stop)) / loss, gain, lev_min, lev_max, lev, margin, lp, dl,
                notional / equity, verdict)


def entry_limit_for_cap(equity: float, stop: float, side: str, *, cap: float = MAX_FORCED_RISK,
                        qty: float = C.BTC_STEP, fee_in: float = C.TAKER + C.SLIP,
                        fee_out: float = C.TAKER + C.SLIP) -> float | None:
    """[CP-17-6] '손절선을 당기지 말고 진입 가격을 옮긴다': 최소 수량으로도 위험 ≤ cap이 되는 진입 가격 한계.
    롱이면 이 값 이하, 숏이면 이 값 이상에서만 진입한다. 손실 = qty × (|E−S| + E·fee_in + S·fee_out) ≤ cap × equity."""
    budget = cap * equity / qty - stop * fee_out          # |E−S| + E·fee_in ≤ budget
    if side == "long":                                    # (E − S) + E·fee_in ≤ budget → E ≤ (budget + S)/(1 + fee_in)
        e = (budget + stop) / (1 + fee_in)
        return e if e > stop else None
    e = (stop - budget) / (1 - fee_in)                    # (S − E) + E·fee_in ≤ budget → E ≥ (S − budget)/(1 − fee_in)
    return e if e < stop else None


def render(p: Plan, rate: float = C.KRW_PER_USDT) -> str:
    """보고서(텔레그램·PDF)에 넣을 '주문표' 블록(한국어)."""
    side_k = "롱(오르면 이익)" if p.side == "long" else "숏(내리면 이익)"
    lines = [f"방향: {side_k}",
             f"진입 {p.entry:,.1f} · 손절 {p.stop:,.1f} ({'-' if p.side == 'long' else '+'}{p.d_stop*100:.2f}%)"
             + (f" · 목표 {p.target:,.1f}" if p.target else "")]
    if p.verdict.startswith("NO_TRADE"):
        lines.append(f"판정: 진입 안 함 — {p.verdict[9:-1]}")
        lines.append(f"(참고) 최소 수량 {p.qty:.3f} BTC = {p.notional:,.1f} USDT, 손절 시 {p.loss_at_stop:.2f} USDT"
                     f"(약 {p.loss_at_stop*rate:,.0f}원) = 계좌의 {p.risk_frac*100:.1f}%")
        lim = entry_limit_for_cap(p.equity, p.stop, p.side)
        if lim is not None and "강제 위험" in p.verdict:
            lines.append(f"대안: 손절은 그대로 두고 진입가를 옮긴다 — {'롱은 ' + format(lim, ',.1f') + ' 이하' if p.side == 'long' else '숏은 ' + format(lim, ',.1f') + ' 이상'}"
                         f" 지정가면 위험 {MAX_FORCED_RISK*100:.0f}% 이내. 안 오면 포기 [CP-17-6]")
        return "\n".join(lines)
    lines += [
        f"수량: {p.qty:.3f} BTC (포지션 {p.notional:,.1f} USDT ≈ {p.notional*rate/10000:,.1f}만 원)"
        + (" ← 최소 주문 단위라 목표 위험보다 큼" if p.forced_min else ""),
        f"손절 시 손실: {p.loss_at_stop:.2f} USDT (약 {p.loss_at_stop*rate:,.0f}원) = 계좌의 {p.risk_frac*100:.1f}%"
        f" (수수료·슬리피지가 이 중 {p.cost_share_of_r*100:.0f}%)",
    ]
    if p.gain_at_target is not None:
        lines.append(f"목표 도달 시 이익: {p.gain_at_target:.2f} USDT (약 {p.gain_at_target*rate:,.0f}원)"
                     f" = {p.gain_at_target/p.loss_at_stop:.2f}R")
    lines += [
        f"레버리지(격리): {p.lev}배로 설정 = 포지션 {p.notional:,.1f} ÷ 증거금 {p.margin:.2f} USDT"
        f" (가능 범위 {p.lev_min}~{p.lev_max}배 중 증거금이 가장 적은 값)",
        f"청산가: {p.liq_price:,.1f} (진입가에서 {p.liq_distance*100:.1f}%, 손절 거리의 {p.liq_distance/p.d_stop:.1f}배)",
        f"손절 주문이 안 걸렸을 때 최대 손실 = 증거금 {p.margin:.2f} USDT (약 {p.margin*rate:,.0f}원)",
        f"계좌 기준 실효 레버리지: {p.eff_leverage:.1f}배 (포지션 ÷ 잔고)",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    E5 = C.ACCOUNT_USDT
    px = C.REF_PRICE
    ex = [
        ("5만 원·1h·롱·손절 1.0%", E5, 0.02, px, px * (1 - 0.010), "long", px * (1 + 0.020)),
        ("5만 원·1h·숏·손절 0.6%", E5, 0.02, px, px * (1 + 0.006), "short", px * (1 - 0.012)),
        ("5만 원·4h·롱·손절 2.2%", E5, 0.02, px, px * (1 - 0.022), "long", px * (1 + 0.044)),
        ("20만 원·1h·롱·손절 1.0%", 200_000 / C.KRW_PER_USDT, 0.01, px, px * (1 - 0.010), "long", px * (1 + 0.02)),
        ("100만 원·4h·숏·손절 2.2%", 1_000_000 / C.KRW_PER_USDT, 0.01, px, px * (1 + 0.022), "short", px * (1 - 0.044)),
    ]
    for name, eq, r, e, s, side, t in ex:
        p = plan_trade(eq, r, e, s, side, target=t, hold_hours=12 if "1h" in name else 36)
        print(f"### {name} (목표 위험 {r*100:.0f}%)")
        print(render(p))
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(p).items()})
        print()
