"""현물 4시간봉으로 계산한 신호가 선물 신호(검증한 것)와 얼마나 같은지 본다.
기준값(0.4217, 0.0857)은 고정. 수익은 항상 선물 종가 기준(16시간 뒤)."""
import sys, glob, zipfile, io, csv, gzip, json, math
import numpy as np
spot_dir, fut_dir, fut_hist = sys.argv[1:4]
Q80, Q20, AVG, HOLD, MS4 = 0.4217300308371426, 0.08566545851163947, 20, 4, 14400000
def read_zip_dir(d):
    out = {}
    for f in sorted(glob.glob(d + "/*.zip")):
        z = zipfile.ZipFile(f)
        for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
            if not row or not row[0][0].isdigit(): continue
            t = int(row[0]);  t = t // 1000 if t > 1e14 else t      # 현물은 2025년부터 마이크로초
            out[t] = (float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))
    return out
spot = read_zip_dir(spot_dir)
fut = {}
for r in csv.DictReader(gzip.open(fut_hist, "rt")):
    fut[int(r["open_time"])] = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["volume"]))
n_hist = len(fut); fut.update(read_zip_dir(fut_dir))
T = sorted(set(spot) & set(fut))
gaps = sum(1 for a, b in zip(T, T[1:]) if b - a != MS4)
print(f"현물 봉 {len(spot)}, 선물 봉 {len(fut)} (보관소에서 더한 것 {len(fut)-n_hist}), 겹치는 봉 {len(T)}, 빠진 곳 {gaps}")
def uv(D):
    A = np.array([D[t] for t in T]); o, h, l, c, v = A.T
    avg = np.full(len(T), np.nan); cs = np.cumsum(v)
    avg[AVG:] = (cs[AVG - 1:-1] - np.concatenate(([0], cs[:-AVG - 1]))) / AVG
    rng = h - l
    with np.errstate(divide="ignore", invalid="ignore"):
        up = (h - np.maximum(o, c)) / rng; mult = v / avg
    x = up * mult; x[(rng <= 0) | ~np.isfinite(x)] = np.nan
    return x, up, mult, c
xs, ups, ms, cs_ = uv(spot); xf, upf, mf, cf = uv(fut)
Tn = np.array(T); ok = np.isfinite(xs) & np.isfinite(xf)
# 이어진 구간에서만(빠진 봉 주변 제외) 16시간 뒤 선물 수익
fwd = np.full(len(T), np.nan)
for i in range(len(T) - HOLD):
    if Tn[i + HOLD] - Tn[i] == HOLD * MS4: fwd[i] = cf[i + HOLD] / cf[i] - 1
sig = lambda x: np.where(x >= Q80, 1, np.where(x <= Q20, -1, 0))
ss, sf = sig(xs), sig(xf)
def hac_t(z, lags=3):
    n = len(z); m = z.mean(); zc = z - m; var = (zc @ zc) / n
    for k in range(1, lags + 1): var += 2 * (1 - k / (lags + 1)) * (zc[k:] @ zc[:-k]) / n
    return m / math.sqrt(var / n)
def block(name, m):
    m = m & ok & np.isfinite(fwd)
    a, b, r = ss[m], sf[m], fwd[m]
    both = ((a == 1) & (b == 1)).sum(); so = (a == 1).sum(); fo = (b == 1).sum()
    base = r.mean()
    def ex(s):
        d = (s == 1).astype(float); return (r[s == 1].mean() - base) * 100, hac_t((d - d.mean()) * (r - base))
    es, ts = ex(a); ef, tf = ex(b)
    print(f"{name}: 봉 {m.sum()} | 롱 신호 선물 {fo}({fo/m.sum()*100:.1f}%) 현물 {so}({so/m.sum()*100:.1f}%) 둘 다 {both} | 현물 롱 중 선물도 롱 {both/so*100:.0f}%, 선물 롱 중 현물도 롱 {both/fo*100:.0f}% | 세 갈래 일치 {(a==b).mean()*100:.0f}% | 신호값 상관 {np.corrcoef(xs[m],xf[m])[0,1]:.3f}")
    print(f"     초과 수익(선물 16시간, 비용 전): 선물 신호 {ef:+.3f}%p (t {tf:.2f}) / 현물 신호 {es:+.3f}%p (t {ts:.2f}) | 아무 때나 롱 {base*100:+.3f}%")
    return dict(n=int(m.sum()), fut_long=int(fo), spot_long=int(so), both=int(both), excess_fut=round(ef,3), t_fut=round(tf,2), excess_spot=round(es,3), t_spot=round(ts,2))
import datetime as dt
ms_ = lambda y, mo, d: int(dt.datetime(y, mo, d, tzinfo=dt.timezone.utc).timestamp() * 1000)
res = {}
res["2020~2023"] = block("2020~2023 (기준을 정한 기간)", Tn < ms_(2024, 1, 1))
res["2024~2026-09"] = block("2024-01~2026-09 (확인 기간)", (Tn >= ms_(2024, 1, 1)) & (Tn < ms_(2026, 9, 29)))
res["2026-09-29~"] = block("2026-09-29 이후 (처음 보는 자료)", Tn >= ms_(2026, 9, 29))
print("부분별 차이(전체): 윗꼬리 비율 상관 %.3f, 거래량 배수 상관 %.3f, 종가 차이 중앙값 %.3f%%" % (np.corrcoef(ups[ok], upf[ok])[0, 1], np.corrcoef(ms[ok], mf[ok])[0, 1], np.median(np.abs(cs_[ok] / cf[ok] - 1)) * 100))
# 밤 9시 봉만
slot = np.array([dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).hour == 8 for t in T])
res["9pm_oos"] = block("밤 9시 마감 봉만, 2024-01 이후", slot & (Tn >= ms_(2024, 1, 1)))
json.dump(res, open(sys.argv[4], "w"), indent=1)
