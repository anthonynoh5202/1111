"""5만 원 테스트 설계용 계산 — 실제 돈을 넣기 전에 과거 자료로 알 수 있는 것을 먼저 계산한다.

대상 규칙(research/candles 사전 등록에서 유일하게 통과한 후보, 숫자 고정):
- 4시간봉이 마감되면 upper_vol = 윗꼬리 비율 × (거래량 ÷ 직전 20봉 평균 거래량)을 계산한다.
- upper_vol ≥ Q80(0.42173…)이면 롱, ≤ Q20(0.085666…)이면 숏, 그 사이는 쉰다. 16시간(4봉) 뒤 청산.

이 파일이 계산하는 것 (모두 결과를 본 뒤의 설계용 계산이다. 사전 등록 판정을 바꾸지 않는다)
1. 롱 쪽·숏 쪽을 나눠 본 성적(학습 기간·검증 기간·연도별)과, 같은 기간 '아무 때나 롱' 대비 초과 수익.
2. 하루 6개 마감 시각별 신호 수. 실전 시각은 성적이 아니라 '직장인이 주문할 수 있는가'로 고른다(21시 마감 봉).
3. 1분봉으로 본 실행 비용: 종가에 지정가를 걸면 몇 %가 체결되나, 안 되면 10분 뒤 시장가로 들어갈 때 얼마나 손해인가.
4. 재난 손절(진입가 대비 5% 반대)이 몇 번 걸리나. 펀딩비.
5. 5만 원·최소 수량(0.001 BTC)으로 12주(롱 신호 약 13번) 거래했을 때 결과 분포(부트스트랩).
6. 이 신호가 진짜인지 가리는 데 필요한 기간.

실행: .venv/bin/python -I research/pilot5/pilot_analysis.py  →  research/pilot5/results/analysis.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "candles"))
import candle_features as cf  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
DATA = ROOT / "data" / "binance"

H = 4  # 보유 4봉 = 16시간
MS_4H = 4 * 3600 * 1000
MS_1M = 60 * 1000
TICK = 0.1
WAIT_MIN = 10  # 지정가를 걸어 두는 시간(분)
MAKER, TAKER = 0.0002, 0.0005
STOP_PCT = 0.05  # 재난 손절: 진입가 대비 5% 반대
STOP_SLIP = 0.0005
SLOT_A_OPEN_HOUR_UTC = 8  # 08:00 UTC에 시작해 12:00 UTC(21:00 KST)에 마감하는 봉
KRW_PER_USDT = 1360.0  # 2026-11-10 기사 환산값에서 역산(가정)
START_KRW = 50_000.0
TRANSFER_COST_USDT = 1.0  # 송금·환전 비용 가정
QTY = 0.001
BTC_PRICE = 75_000.0  # 2026-11-10 기사 기준 약 74,765달러
STOP_EQUITY = 0.70  # 계좌가 시작의 70% 아래면 실전 중단
REPS = 20_000
SEED = 20261112


def load_1m() -> pd.DataFrame:
    parts = [pd.read_csv(DATA / f"BTCUSDT_1m_{y}.csv.gz", usecols=["open_time", "high", "low", "close"])
             for y in (2023, 2024, 2025, 2026)]
    return pd.concat(parts).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


def rule_signals() -> pd.DataFrame:
    """4시간봉마다 신호(+1 롱, −1 숏, 0 없음)와 16시간 뒤 종가."""
    df = cf.load("4h")
    O, Hh, L, C, V, TB = cf.arrays(df)
    is_is = (df["time"] < cf.IS_END).to_numpy()
    x = cf.features(O, Hh, L, C, V, TB)["upper_vol"]
    r, valid, sel = cf.fwd(C, is_is, H)
    im = valid & sel & np.isfinite(x) & is_is  # 사전 등록과 같은 학습 표본
    q20, q80 = np.quantile(x[im], [0.2, 0.8])
    pos = np.where(x >= q80, 1, np.where(x <= q20, -1, 0))
    pos[~np.isfinite(x)] = 0
    n = len(df)
    exit_close = np.full(n, np.nan)
    exit_close[: n - H] = C[H:]
    ot = ((df["time"] - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy()
    out = pd.DataFrame(dict(open_time=ot, time=df["time"], close=C, exit_close=exit_close, x=x, pos=pos,
                            is_is=is_is, valid=valid))
    out["open_hour"] = out["time"].dt.hour
    out["year"] = out["time"].dt.year
    out["r"] = out["exit_close"] / out["close"] - 1
    out.attrs["q20"], out.attrs["q80"] = float(q20), float(q80)
    return out


def hac_t(z: np.ndarray, lags: int) -> float:
    """평균이 0인지에 대한 t값(겹치는 보유 기간을 고려한 Newey–West)."""
    n = len(z)
    if n < 10:
        return float("nan")
    zc = z - z.mean()
    var = float(zc @ zc) / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * float(zc[k:] @ zc[:-k]) / n
    return float(z.mean() / math.sqrt(max(var, 1e-30) / n))


def desc(x) -> dict:
    x = np.asarray(x, dtype=float)
    return dict(n=int(len(x)), mean_pct=round(float(x.mean()) * 100, 4), sd_pct=round(float(x.std(ddof=1)) * 100, 3),
                hit=round(float((x > 0).mean()), 3))


def leg_evidence(s: pd.DataFrame) -> dict:
    """롱 쪽: 신호 뒤 16시간 수익 − 같은 기간 전체 평균. t는 (신호 여부, 수익)의 공분산 검정."""
    r = s["r"].to_numpy()
    d = (s["pos"].to_numpy() > 0).astype(float)
    sh = (s["pos"].to_numpy() < 0).astype(float)
    years = (s["time"].iloc[-1] - s["time"].iloc[0]).days / 365.25
    t_long = hac_t((d - d.mean()) * (r - r.mean()), H - 1)
    t_short = hac_t((sh - sh.mean()) * (-(r - r.mean())), H - 1)
    return dict(years=round(years, 2), base_mean_pct=round(float(r.mean()) * 100, 4),
                long=desc(r[d == 1]), long_excess_pct=round(float(r[d == 1].mean() - r.mean()) * 100, 4),
                long_excess_t=round(t_long, 2),
                short=desc(-r[sh == 1]), short_excess_pct=round(float(-r[sh == 1].mean() + r.mean()) * 100, 4),
                short_excess_t=round(t_short, 2))


def simulate_execution(sig: pd.DataFrame, m1: pd.DataFrame) -> pd.DataFrame:
    """1분봉으로 실행을 흉내 낸다. 검증 기간, 신호가 있는 봉 전부."""
    t1 = m1["open_time"].to_numpy()
    hi, lo, cl = m1["high"].to_numpy(float), m1["low"].to_numpy(float), m1["close"].to_numpy(float)
    rows = []
    s = sig[(~sig.is_is) & sig.valid & (sig.pos != 0)]
    for ot, c0, c1, d, hour, year in zip(s.open_time, s.close, s.exit_close, s.pos, s.open_hour, s.year):
        T = ot + MS_4H
        T2 = T + H * MS_4H
        i0 = int(np.searchsorted(t1, T))
        j0 = int(np.searchsorted(t1, T2))
        if i0 >= len(t1) or t1[i0] != T or j0 + WAIT_MIN > len(t1) or t1[j0] != T2:
            continue
        if t1[i0 + WAIT_MIN - 1] != T + (WAIT_MIN - 1) * MS_1M or t1[j0 + WAIT_MIN - 1] != T2 + (WAIT_MIN - 1) * MS_1M:
            continue
        # 진입: 종가에 지정가 → 10분 안에 가격이 한 틱 더 유리하게 지나가면 체결, 아니면 10분 뒤 시장가
        hit_e = (lo[i0:i0 + WAIT_MIN] <= c0 - TICK) if d > 0 else (hi[i0:i0 + WAIT_MIN] >= c0 + TICK)
        e_fill = bool(hit_e.any())
        e_price = c0 if e_fill else cl[i0 + WAIT_MIN - 1]
        e_fee = MAKER if e_fill else TAKER
        e_idx = i0 + (int(np.argmax(hit_e)) if e_fill else WAIT_MIN - 1)
        seg_lo, seg_hi = lo[e_idx + 1:j0], hi[e_idx + 1:j0]
        if len(seg_lo) == 0:
            continue
        mae = (1 - seg_lo.min() / e_price) if d > 0 else (seg_hi.max() / e_price - 1)
        # 청산: 16시간 뒤 가격에 지정가 → 10분 안에 한 틱 유리하게 지나가면 체결, 아니면 시장가
        hit_x = (hi[j0:j0 + WAIT_MIN] >= c1 + TICK) if d > 0 else (lo[j0:j0 + WAIT_MIN] <= c1 - TICK)
        x_fill = bool(hit_x.any())
        x_price = c1 if x_fill else cl[j0 + WAIT_MIN - 1]
        x_fee = MAKER if x_fill else TAKER
        paper = d * (c1 / c0 - 1)
        live = d * (x_price / e_price - 1) - e_fee - x_fee
        stopped = mae >= STOP_PCT
        live_stop = (-STOP_PCT - STOP_SLIP - e_fee - TAKER) if stopped else live
        rows.append(dict(open_time=ot, year=year, open_hour=hour, pos=d, paper=paper, taker_both=paper - 2 * TAKER,
                         live=live, live_stop=live_stop, e_fill=e_fill, x_fill=x_fill, mae=mae, stopped=stopped,
                         entry_slip=d * (e_price / c0 - 1)))
    return pd.DataFrame(rows)


def exec_summary(e: pd.DataFrame) -> dict:
    sf = (e.live - e.paper).to_numpy()
    return dict(n=int(len(e)), paper=desc(e.paper), taker_both=desc(e.taker_both), limit_then_market=desc(e.live),
                limit_then_market_with_stop=desc(e.live_stop),
                entry_fill_pct=round(float(e.e_fill.mean() * 100), 1), exit_fill_pct=round(float(e.x_fill.mean() * 100), 1),
                shortfall_mean_pct=round(float(sf.mean()) * 100, 4), shortfall_sd_pct=round(float(sf.std(ddof=1)) * 100, 4),
                entry_slip_when_unfilled_pct=round(float(e.entry_slip[~e.e_fill].mean()) * 100, 4),
                stop_hit_pct=round(float(e.stopped.mean() * 100), 2),
                stop_cost_pct=round(float((e.live_stop - e.live).mean()) * 100, 4),
                mae_ge=dict((f"{int(k * 100)}%", round(float((e.mae >= k).mean() * 100), 2)) for k in (0.03, 0.05, 0.08, 0.10)),
                worst_trade_pct=round(float(e.live.min()) * 100, 2),
                worst_trade_with_stop_pct=round(float(e.live_stop.min()) * 100, 2))


def funding_cost(sig: pd.DataFrame) -> dict:
    f = pd.read_csv(DATA / "BTCUSDT_fundingRate.csv.gz")
    ft = (f["calc_time"].to_numpy() // 1000 * 1000).astype("int64")
    fr = f["last_funding_rate"].to_numpy(float)
    s = sig[(~sig.is_is) & sig.valid & (sig.pos > 0) & (sig.open_hour == SLOT_A_OPEN_HOUR_UTC)]
    costs, n_events = [], []
    for ot in s.open_time:
        T, T2 = ot + MS_4H, ot + MS_4H + H * MS_4H
        if T2 > ft.max():
            continue
        m = (ft > T) & (ft <= T2)
        costs.append(fr[m].sum())  # 롱이 내는 돈(명목 대비). 음수면 받는다
        n_events.append(int(m.sum()))
    c = np.array(costs)
    return dict(trades=int(len(c)), mean_cost_pct=round(float(c.mean()) * 100, 4), mean_events=round(float(np.mean(n_events)), 2),
                worst_cost_pct=round(float(c.max()) * 100, 4))


def bootstrap(ret: np.ndarray, n_trades: int, notional: float, e0: float, rng: np.random.Generator) -> dict:
    """ret에서 n_trades개를 뽑아 순서대로 거래. 계좌가 70% 아래로 내려가면 멈춘다."""
    draws = ret[rng.integers(0, len(ret), size=(REPS, n_trades))] * notional
    eq = e0 + np.cumsum(draws, axis=1)
    stop_hit = eq <= STOP_EQUITY * e0
    first = np.where(stop_hit.any(axis=1), stop_hit.argmax(axis=1), n_trades - 1)
    pnl_krw = (eq[np.arange(REPS), first] - e0) * KRW_PER_USDT
    q = np.quantile(pnl_krw, [0.05, 0.25, 0.5, 0.75, 0.95])
    return dict(mean_krw=round(float(pnl_krw.mean())), p05_krw=round(float(q[0])), p25_krw=round(float(q[1])),
                median_krw=round(float(q[2])), p75_krw=round(float(q[3])), p95_krw=round(float(q[4])),
                profit_prob_pct=round(float((pnl_krw > 0).mean() * 100), 1),
                stop_hit_pct=round(float(stop_hit.any(axis=1).mean() * 100), 1))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    sig = rule_signals()
    v = sig[sig.valid]
    is_, oos = v[v.is_is], v[~v.is_is]
    res: dict = {"rule": dict(q20=sig.attrs["q20"], q80=sig.attrs["q80"], hold_bars=H),
                 "assumptions": dict(krw_per_usdt=KRW_PER_USDT, start_krw=START_KRW, transfer_cost_usdt=TRANSFER_COST_USDT,
                                     qty_btc=QTY, btc_price=BTC_PRICE, wait_min=WAIT_MIN, maker=MAKER, taker=TAKER,
                                     stop_pct=STOP_PCT)}

    # 1. 롱 쪽·숏 쪽
    res["legs"] = dict(is_2020_2023=leg_evidence(is_), oos_2024_2026=leg_evidence(oos), all_2020_2026=leg_evidence(v))
    by_year = []
    for y, g in v.groupby("year"):
        L, S = g[g.pos > 0], g[g.pos < 0]
        by_year.append(dict(year=int(y), base_pct=round(float(g.r.mean()) * 100, 3), long_n=int(len(L)),
                            long_pct=round(float(L.r.mean()) * 100, 3),
                            long_excess_pct=round(float(L.r.mean() - g.r.mean()) * 100, 3),
                            short_n=int(len(S)), short_pnl_pct=round(float(-S.r.mean()) * 100, 3)))
    res["legs_by_year"] = by_year
    # 사전 등록 규칙(롱·숏 대칭) 전체 봉 성적과 필요한 기간
    z = (oos.pos * oos.r).to_numpy()
    act = (oos.pos != 0).to_numpy()
    yrs = res["legs"]["oos_2024_2026"]["years"]
    t_g, t_m = hac_t(z, H - 1), hac_t(z - act * 2 * MAKER, H - 1)
    res["symmetric_rule_oos"] = dict(active=int(act.sum()), gross_mean_pct=round(float(z[act].mean()) * 100, 4),
                                     gross_t=round(t_g, 2), years_needed_gross_t2=round(yrs * (2 / t_g) ** 2, 1),
                                     maker_net_t=round(t_m, 2), years_needed_maker_t2=round(yrs * (2 / t_m) ** 2, 1))
    t_l = res["legs"]["oos_2024_2026"]["long_excess_t"]
    res["long_leg_forward_power"] = dict(oos_t=t_l, expected_t_after_1y_all_slots=round(t_l / math.sqrt(yrs), 2),
                                         years_needed_t2_all_slots=round(yrs * (2 / t_l) ** 2, 1),
                                         years_needed_t2_one_slot=round(yrs * (2 / t_l) ** 2 * 6, 1))

    # 2. 마감 시각별
    slots = []
    for hour in (0, 4, 8, 12, 16, 20):
        g = oos[oos.open_hour == hour]
        L = g[g.pos > 0]
        close_kst = (hour + 4 + 9) % 24
        slots.append(dict(bar_close_kst=f"{close_kst:02d}:00", exit_kst=f"{(close_kst + 16) % 24:02d}:00",
                          long_signals_per_month=round(len(L) / len(g) * 30.4, 1),
                          short_signals_per_month=round(int((g.pos < 0).sum()) / len(g) * 30.4, 1),
                          base_pct=round(float(g.r.mean()) * 100, 3), long_pct=round(float(L.r.mean()) * 100, 3),
                          long_excess_pct=round(float(L.r.mean() - g.r.mean()) * 100, 3),
                          long_hit=round(float((L.r > 0).mean()), 3)))
    res["slots_oos"] = slots
    a_all = v[(v.open_hour == SLOT_A_OPEN_HOUR_UTC)]
    res["slot_a_long_by_year"] = [dict(year=int(y), base_pct=round(float(g.r.mean()) * 100, 3), long_n=int((g.pos > 0).sum()),
                                       long_pct=round(float(g[g.pos > 0].r.mean()) * 100, 3),
                                       long_hit=round(float((g[g.pos > 0].r > 0).mean()), 3))
                                  for y, g in a_all.groupby("year")]

    # 3·4. 실행 흉내 (검증 기간, 1분봉)
    ex = simulate_execution(sig, load_1m())
    ex.to_csv(OUT / "execution_sim.csv", index=False, float_format="%.6g")
    exl = ex[ex.pos > 0]
    al = exl[exl.open_hour == SLOT_A_OPEN_HOUR_UTC]
    res["execution_oos"] = dict(all_signals=exec_summary(ex), long_all_slots=exec_summary(exl), long_slot_a=exec_summary(al))
    res["funding_long_slot_a_oos"] = funding_cost(sig)
    # 2020~2026 전체에서 롱 신호 뒤 16시간 동안 가장 불리했던 움직임(4시간봉 저가 기준)
    b4 = cf.load("4h")
    lo4, c4 = b4["low"].to_numpy(float), b4["close"].to_numpy(float)
    idx = np.where((sig["pos"].to_numpy() > 0) & sig["valid"].to_numpy())[0]
    maes = np.array([1 - lo4[i + 1:i + H + 1].min() / c4[i] for i in idx if i + H < len(c4)])
    res["long_mae_2020_2026"] = dict(n=int(len(maes)), worst_pct=round(float(maes.max()) * 100, 1),
                                     ge=dict((f"{int(k * 100)}%", round(float((maes >= k).mean() * 100), 2))
                                             for k in (0.05, 0.10, 0.15, 0.20)))

    # 5. 5만 원·12주(롱 신호 약 13번) 부트스트랩 — 21시 마감 봉 롱, 지정가→시장가, 재난 손절 포함
    e0 = START_KRW / KRW_PER_USDT - TRANSFER_COST_USDT
    notional = QTY * BTC_PRICE
    per_month = slots[2]["long_signals_per_month"]
    n_tr = int(round(per_month * 12 / 4.345))
    ret = al.live_stop.to_numpy()
    cost = float(-(al.live - al.paper).mean())
    no_edge = ret - float(al.paper.mean())  # 비용 전 평균 0(시장 제자리, 실력 없음)
    excess = res["legs"]["oos_2024_2026"]["long_excess_pct"] / 100
    avg_edge = no_edge + excess  # 비용 전 평균 = 6개 시각 전체의 초과 수익(시장 제자리 가정)
    bear = no_edge + excess - 0.0015  # 하락장(2022년 수준, 16시간마다 −0.15%)에서 같은 초과 수익
    res["pilot_12_weeks_long_only"] = dict(
        start_equity_usdt=round(e0, 2), notional_usdt=notional, leverage=round(notional / e0, 2), trades=n_tr,
        one_sd_per_trade_krw=round(float(ret.std(ddof=1)) * notional * KRW_PER_USDT),
        stop_loss_per_trade_krw=round((STOP_PCT + STOP_SLIP + MAKER + TAKER) * notional * KRW_PER_USDT),
        cost_per_trade_krw=round(cost * notional * KRW_PER_USDT),
        scenario_net_mean_pct=dict(no_edge=round(float(no_edge.mean()) * 100, 4), average_edge=round(float(avg_edge.mean()) * 100, 4),
                                   bear_market=round(float(bear.mean()) * 100, 4), slot_a_as_observed=round(float(ret.mean()) * 100, 4)),
        no_edge=bootstrap(no_edge, n_tr, notional, e0, rng), average_edge=bootstrap(avg_edge, n_tr, notional, e0, rng),
        bear_market=bootstrap(bear, n_tr, notional, e0, rng), slot_a_as_observed=bootstrap(ret, n_tr, notional, e0, rng))
    # 참고: 롱·숏 둘 다 30번 했다면
    both = ex[ex.open_hour == SLOT_A_OPEN_HOUR_UTC]
    b_no = both.live_stop.to_numpy() - float(both.paper.mean())
    res["reference_both_sides_30_trades"] = dict(no_edge=bootstrap(b_no, 30, notional, e0, rng),
                                                 average_edge=bootstrap(b_no + float(z[act].mean()), 30, notional, e0, rng))

    # 비용은 몇 번이면 잴 수 있나
    sf = (al.live - al.paper).to_numpy()
    res["what_13_trades_can_measure"] = dict(
        cost_mean_pct=round(float(-sf.mean()) * 100, 4), cost_sd_pct=round(float(sf.std(ddof=1)) * 100, 4),
        cost_se_pct=round(float(sf.std(ddof=1) / math.sqrt(n_tr)) * 100, 4),
        pnl_sd_pct=round(float(ret.std(ddof=1)) * 100, 3), pnl_se_pct=round(float(ret.std(ddof=1) / math.sqrt(n_tr)) * 100, 3),
        edge_to_detect_pct=round(excess * 100, 3))

    # 6. 진짜라면 얼마를 버나(월): 21시 봉 롱만, 비용 뒤 초과 수익
    net = excess - cost
    res["scale_math"] = dict(trades_per_month=per_month, net_edge_pct=round(net * 100, 4),
                             monthly_krw_at_min_size=round(per_month * net * notional * KRW_PER_USDT),
                             notional_krw_for_1m_per_month=round(1_000_000 / (per_month * net) / 1e6) * 1_000_000)
    (OUT / "analysis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
