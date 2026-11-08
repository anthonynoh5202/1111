"""미국 S&P 500 (Shiller 월별 자료) 배당 재투자·물가 제외 수익 분포.
입력: Shiller data.csv (raw.githubusercontent.com/datasets/s-and-p-500). 배당·물가가 있는 달만 씀.
"""
import sys, json
import numpy as np, pandas as pd

df = pd.read_csv(sys.argv[1], parse_dates=["Date"])
df = df[(df["Consumer Price Index"] > 0) & (df["Dividend"] > 0)].reset_index(drop=True)
p, d, cpi = df["SP500"].values, df["Dividend"].values, df["Consumer Price Index"].values
# 월 총수익: (P_t + D_t/12) / P_{t-1}  (Shiller 배당은 연율)
gross = np.ones(len(df))
gross[1:] = (p[1:] + d[1:] / 12.0) / p[:-1]
real_gross = gross.copy()
real_gross[1:] = gross[1:] * cpi[:-1] / cpi[1:]
tr_real = np.cumprod(real_gross)
dates = df["Date"].dt.strftime("%Y-%m").values
out = {"period": f"{dates[0]}~{dates[-1]}", "months": int(len(df))}

def ann(a, b, years):
    return (tr_real[b] / tr_real[a]) ** (1 / years) - 1

full_years = (len(df) - 1) / 12
out["full_real_cagr"] = round(ann(0, len(df) - 1, full_years) * 100, 2)
for start in ["1900-01", "1926-01", "1950-01", "1990-01"]:
    i = int(np.where(dates == start)[0][0])
    out[f"real_cagr_from_{start}"] = round(ann(i, len(df) - 1, (len(df) - 1 - i) / 12) * 100, 2)

# 일시금: 기간별 연환산 실질 수익 분포
for yrs in [1, 5, 10, 20, 30]:
    n = yrs * 12
    r = np.array([ann(i, i + n, yrs) for i in range(len(df) - n)])
    worst_i = int(np.argmin(r))
    out[f"lump_{yrs}y"] = {
        "windows": int(len(r)),
        "loss_share_pct": round(float((r < 0).mean() * 100), 1),
        "worst_pct": round(float(r.min() * 100), 2),
        "worst_start": dates[worst_i],
        "median_pct": round(float(np.median(r) * 100), 2),
        "best_pct": round(float(r.max() * 100), 2),
    }

# 최대 낙폭(실질 총수익)과 회복에 걸린 기간
peak = np.maximum.accumulate(tr_real)
dd = tr_real / peak - 1
i_min = int(np.argmin(dd))
i_peak = int(np.argmax(tr_real[: i_min + 1]))
rec = np.where(tr_real[i_min:] >= tr_real[i_peak])[0]
out["max_drawdown_real"] = {
    "pct": round(float(dd[i_min] * 100), 1), "peak": dates[i_peak], "trough": dates[i_min],
    "recovered": dates[i_min + rec[0]] if len(rec) else None,
}
# 1950년 이후 최대 낙폭
j0 = int(np.where(dates == "1950-01")[0][0])
sub = tr_real[j0:]
pk = np.maximum.accumulate(sub); dd2 = sub / pk - 1; k = int(np.argmin(dd2)); kp = int(np.argmax(sub[: k + 1]))
rec2 = np.where(sub[k:] >= sub[kp])[0]
out["max_drawdown_real_since_1950"] = {
    "pct": round(float(dd2[k] * 100), 1), "peak": dates[j0 + kp], "trough": dates[j0 + k],
    "recovered": dates[j0 + k + rec2[0]] if len(rec2) else None,
}

# 매달 같은 실질 금액 적립: 기간 끝 평가액 / 넣은 돈 합계
for yrs in [10, 20]:
    n = yrs * 12
    mult = []
    for i in range(len(df) - n):
        seg = tr_real[i : i + n + 1]
        # 매달 초(i..i+n-1)에 1씩 넣고 i+n에서 평가
        val = np.sum(seg[-1] / seg[:-1])
        mult.append(val / n)
    mult = np.array(mult)
    w = int(np.argmin(mult))
    out[f"dca_{yrs}y"] = {
        "windows": int(len(mult)),
        "loss_share_pct": round(float((mult < 1).mean() * 100), 1),
        "worst_multiple": round(float(mult.min()), 2), "worst_start": dates[w],
        "p10_multiple": round(float(np.percentile(mult, 10)), 2),
        "median_multiple": round(float(np.median(mult)), 2),
    }
print(json.dumps(out, ensure_ascii=False, indent=1))
