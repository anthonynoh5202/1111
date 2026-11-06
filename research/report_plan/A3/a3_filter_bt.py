"""A3. 단순 돌파 규칙 + 수급 특징 필터 → IS/OOS 기대값(R) 비교.

기본 규칙 (고정):
- 4시간봉. 신호 봉 i 마감 시 종가 > 직전 20봉 최고가(처음 넘은 봉만) → 롱, 종가 < 직전 20봉 최저가(처음) → 숏.
- 진입: 다음 봉 시가(= 신호 봉 마감 직후) 시장가. 테이커 0.05% + 슬리피지 0.02%.
- 손절: 진입가 ∓ 2×ATR14(4h, 신호 봉 포함 14봉 TR 평균). 목표: 2R(= 4×ATR) 지정가(메이커 0.02%).
- 최대 보유 42봉(7일) 뒤 시장가 청산. 청산 판정은 5분봉, 한 5분봉 안에서 손절·목표가 함께 닿으면 손절 먼저(보수적).
- 펀딩: 보유 중 정산 시각마다 실제 펀딩(2026-09 이후 0.01% 가정). 롱은 양수 펀딩을 낸다.
- 신호마다 독립 거래로 평가(겹침 허용) → 필터는 거래의 부분집합을 고르는 것과 같다.
필터 (실행 전 고정, 특징 계열당 1개):
- F1 펀딩 과열 회피: 롱은 fund_pct90 < 0.8, 숏은 fund_pct90 > 0.2
- F2 OI 동반: 돌파 봉(4h) 동안 OI 증가 (doi_4h > 0), 롱·숏 공통
- F3 테이커 동반: 롱은 돌파 봉 테이커 매수비율 > 0.5, 숏은 < 0.5
- F4 저변동성 돌파: atr_rank(180일 백분위) <= 0.5
- F5 군중 역행: 롱은 전체 계정 롱숏 z < 0, 숏은 z > 0
"""
import numpy as np
import pandas as pd

from common import OUT, IS_START, OOS_START, load_funding, load_klines

FEE_T, FEE_M, SLIP = 0.0005, 0.0002, 0.0002
N_BRK, ATR_N, STOP_ATR, TGT_R, MAX_HOLD_H = 20, 14, 2.0, 2.0, 168

feat = pd.read_pickle(OUT + "hourly.pkl")

q = load_klines("4h")
q["T"] = q.index + pd.Timedelta(hours=4)
pc = q["close"].shift(1)
tr = pd.concat([q["high"] - q["low"], (q["high"] - pc).abs(), (q["low"] - pc).abs()], axis=1).max(axis=1)
q["atr"] = tr.rolling(ATR_N).mean()
q["hh"] = q["high"].shift(1).rolling(N_BRK).max()
q["ll"] = q["low"].shift(1).rolling(N_BRK).min()
up = q["close"] > q["hh"]; dn = q["close"] < q["ll"]
q["sig"] = 0
q.loc[up & ~up.shift(1, fill_value=False), "sig"] = 1
q.loc[dn & ~dn.shift(1, fill_value=False), "sig"] = -1

k5 = load_klines("5m", cols=["open_time", "open", "high", "low", "close"])
t5 = k5.index.values.astype("datetime64[ns]").astype(np.int64)
o5, h5, l5, c5 = (k5[c].to_numpy() for c in ("open", "high", "low", "close"))
fr = load_funding()
ft = fr.index.values.astype("datetime64[ns]").astype(np.int64)
# 정산 시각(ms 오차) → 정시로
ft = (np.round(ft / 3.6e12) * 3.6e12).astype(np.int64)
fv = fr.to_numpy()
FUND_LAST_NS = ft[-1]
H_NS = 3_600_000_000_000

sigs = q[(q["sig"] != 0) & (q["T"] >= IS_START) & q["atr"].notna()].copy()
data_end_ns = t5[-1] + 5 * 60 * 10**9
trades = []
for _, s in sigs.iterrows():
    T_ns = s["T"].value
    if T_ns + MAX_HOLD_H * H_NS > data_end_ns:
        continue
    side = int(s["sig"])
    j0 = np.searchsorted(t5, T_ns)
    entry = o5[j0]
    risk = STOP_ATR * s["atr"]
    stop = entry - side * risk
    tgt = entry + side * TGT_R * risk
    j1 = j0 + MAX_HOLD_H * 12
    hi, lo, op = h5[j0:j1], l5[j0:j1], o5[j0:j1]
    if side == 1:
        hit_s = lo <= stop; hit_t = hi >= tgt
    else:
        hit_s = hi >= stop; hit_t = lo <= tgt
    is_ = np.argmax(hit_s) if hit_s.any() else 10**9
    it_ = np.argmax(hit_t) if hit_t.any() else 10**9
    if is_ == 10**9 and it_ == 10**9:
        k = len(hi) - 1; px = c5[j0 + k]; why = "time"; fee_x = FEE_T + SLIP
    elif is_ <= it_:
        k = is_
        px = (min(op[k], stop) if side == 1 else max(op[k], stop)); why = "stop"; fee_x = FEE_T + SLIP
    else:
        k = it_; px = tgt; why = "target"; fee_x = FEE_M
    exit_ns = t5[j0 + k] + 5 * 60 * 10**9
    # 펀딩: entry < t_f <= exit
    a, b = np.searchsorted(ft, T_ns, side="right"), np.searchsorted(ft, exit_ns, side="right")
    fund = 0.0
    for idx in range(a, b):
        jf = min(np.searchsorted(t5, ft[idx]), len(o5) - 1)
        fund += side * fv[idx] * o5[jf]
    # 데이터 끝 뒤 정산 (0.01% 가정)
    tf = max(FUND_LAST_NS, T_ns)
    nxt = (tf // (8 * H_NS) + 1) * 8 * H_NS
    while nxt <= exit_ns:
        if nxt > FUND_LAST_NS:
            jf = min(np.searchsorted(t5, nxt), len(o5) - 1)
            fund += side * 0.0001 * o5[jf]
        nxt += 8 * H_NS
    cost = entry * (FEE_T + SLIP) + px * fee_x
    pnl = side * (px - entry) - cost - fund
    trades.append(dict(T=s["T"], side=side, entry=entry, stop=stop, tgt=tgt, risk=risk, exit=px, why=why,
                       hold_h=(exit_ns - T_ns) / H_NS, R=pnl / risk, R_gross=side * (px - entry) / risk,
                       cost_R=cost / risk, fund_R=fund / risk))
tr_ = pd.DataFrame(trades).set_index("T")
cols = ["fund_pct90", "doi_4h", "tbr_4h", "atr_rank", "ls_global_z", "fund_last", "doi_24h", "dec_hour_kst", "dow_kst"]
tr_ = tr_.join(feat[cols], how="left")
tr_["period"] = np.where(tr_.index < OOS_START, "IS", "OOS")

L = tr_.side == 1
F = {
    "F0 기본(필터 없음)": pd.Series(True, index=tr_.index),
    "F1 펀딩 과열 회피": (L & (tr_.fund_pct90 < 0.8)) | (~L & (tr_.fund_pct90 > 0.2)),
    "F2 OI 동반(돌파 봉 OI↑)": tr_.doi_4h > 0,
    "F3 테이커 동반": (L & (tr_.tbr_4h > 0.5)) | (~L & (tr_.tbr_4h < 0.5)),
    "F4 저변동성 돌파": tr_.atr_rank <= 0.5,
    "F5 군중 역행(전체 롱숏)": (L & (tr_.ls_global_z < 0)) | (~L & (tr_.ls_global_z > 0)),
}
NEEDS = {"F1 펀딩 과열 회피": "fund_pct90", "F2 OI 동반(돌파 봉 OI↑)": "doi_4h", "F3 테이커 동반": "tbr_4h",
         "F4 저변동성 돌파": "atr_rank", "F5 군중 역행(전체 롱숏)": "ls_global_z"}


def stats(r: pd.DataFrame) -> dict:
    if len(r) == 0:
        return dict(n=0)
    R = r.R.to_numpy()
    cum = np.cumsum(R); dd = (np.maximum.accumulate(np.r_[0, cum])[1:] - cum).max()
    w, l_ = R[R > 0], R[R <= 0]
    return dict(n=len(R), win=(R > 0).mean(), ev=R.mean(), se=R.std(ddof=1) / np.sqrt(len(R)) if len(R) > 1 else np.nan,
                t=R.mean() / (R.std(ddof=1) / np.sqrt(len(R))) if len(R) > 1 else np.nan,
                avg_win=w.mean() if len(w) else np.nan, avg_loss=l_.mean() if len(l_) else np.nan,
                payoff=(w.mean() / -l_.mean()) if len(w) and len(l_) else np.nan,
                sumR=R.sum(), maxdd=dd, hold_h=r.hold_h.mean(), time_exit=(r.why == "time").mean(),
                long_share=(r.side == 1).mean())


rows = []
for name, f in F.items():
    for per in ("IS", "OOS"):
        base = tr_[tr_.period == per]
        if name in NEEDS:
            base = base[base[NEEDS[name]].notna()]
        ff = f.reindex(base.index).fillna(False).astype(bool)
        inn, out = base[ff], base[~ff]
        si, so = stats(inn), stats(out)
        diff = si.get("ev", np.nan) - so.get("ev", np.nan) if so.get("n", 0) > 1 else np.nan
        sed = np.sqrt(si.get("se", np.nan) ** 2 + so.get("se", np.nan) ** 2) if so.get("n", 0) > 1 else np.nan
        rows.append(dict(filter=name, period=per, base_n=len(base), **si, out_n=so.get("n", 0), out_ev=so.get("ev", np.nan),
                         diff=diff, t_diff=diff / sed if sed and np.isfinite(sed) else np.nan))
res = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(res.round(3).to_string(index=False))
res.to_csv(OUT + "a3_filter_results.csv", index=False)
tr_.to_csv(OUT + "a3_trades.csv")

print("\n청산 사유 비율:", tr_.why.value_counts(normalize=True).round(3).to_dict())
print("비용 평균 R:", round(tr_.cost_R.mean(), 3), " 펀딩 평균 R:", round(tr_.fund_R.mean(), 4))
print("롱/숏별 (기본):")
print(tr_.groupby(["period", "side"]).R.agg(["count", "mean", lambda x: (x > 0).mean()]).round(3))
# 겹침 비율
T_ns = tr_.index.values.astype("datetime64[ns]").astype(np.int64)
end_ns = T_ns + (tr_.hold_h.to_numpy() * H_NS).astype(np.int64)
ov = np.mean([((T_ns[:i] < T_ns[i]) & (end_ns[:i] > T_ns[i])).any() for i in range(len(T_ns))])
print("다른 거래가 열려 있는 동안 생긴 신호 비율:", round(ov, 3))
