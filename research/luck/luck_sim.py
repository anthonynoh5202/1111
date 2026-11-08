"""실력 없는 트레이더 1만 명 모의실험: 생존 편향이 '캔들로 벌었다'는 이야기를 얼마나 만들어 내나.

가정(바꿔 볼 수 있음)
- 1년에 100번 거래, 매번 계좌의 RISK(기본 5%)를 손절 폭으로 건다.
- 이기면 +2R(손익비 2), 지면 -1R. 승률 P_WIN=0.32 -> 거래당 기대값 -0.04R(수수료·미끄러짐 몫).
- 실력이 있는 경우와 비교: 승률 0.36 -> 거래당 +0.08R.
"""
import json
import numpy as np

rng = np.random.default_rng(20261108)
N, T, RISK = 10_000, 100, 0.05

def year(p_win, risk=RISK, n=N):
    wins = rng.binomial(T, p_win, size=n)
    return (1 + 2 * risk) ** wins * (1 - risk) ** (T - wins)

def summary(final):
    return {
        "profit_pct": round(float((final > 1).mean() * 100), 1),
        "doubled_people": int((final >= 2).sum()),
        "x5_people": int((final >= 5).sum()),
        "x10_people": int((final >= 10).sum()),
        "lost_half_pct": round(float((final <= 0.5).mean() * 100), 1),
        "median_return_pct": round(float((np.median(final) - 1) * 100), 1),
        "best_multiple": round(float(final.max()), 1),
    }

out = {}
y1 = year(0.32)
out["no_skill_year1"] = summary(y1)
y2 = year(0.32)
top = y1 >= 2
out["no_skill_year2_of_year1_doublers"] = {
    "people": int(top.sum()),
    "profit_pct_year2": round(float((y2[top] > 1).mean() * 100), 1),
    "doubled_again_pct": round(float((y2[top] >= 2).mean() * 100), 1),
    "everyone_profit_pct_year2": round(float((y2 > 1).mean() * 100), 1),
}
out["no_skill_risk10pct_year1"] = summary(year(0.32, risk=0.10))
out["skill_p036_year1"] = summary(year(0.36))

# 실력(+0.08R, +0.10R)을 운과 구분하는 데 필요한 거래 수(단측 95%, 정규 근사)
def trades_needed(p_win, z=1.645):
    mu = p_win * 2 - (1 - p_win)
    sd = np.sqrt(p_win * (1 - p_win)) * 3  # 결과가 +2 또는 -1
    return int(np.ceil((z * sd / mu) ** 2)), round(float(mu), 3)
for p in (0.36, 0.3667, 0.38):
    n_req, mu = trades_needed(p)
    out[f"trades_needed_edge_{mu}R"] = n_req
print(json.dumps(out, ensure_ascii=False, indent=1))
