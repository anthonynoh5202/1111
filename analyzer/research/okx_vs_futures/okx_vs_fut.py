"""OKX BTC-USDT-SWAP 4시간봉으로 계산한 신호가 바이낸스 선물 신호(검증한 것)와 얼마나 같은지 본다.
기준값(0.4217, 0.0857)은 고정. 수익은 바이낸스 선물 종가 기준(16시간 뒤), 비용 전."""
import sys, glob, zipfile, io, csv, gzip, json, math, datetime as dt
import numpy as np
okx_csv, fut_dir, fut_hist, out_json = sys.argv[1:5]
Q80, Q20, AVG, HOLD, MS4 = 0.4217300308371426, 0.08566545851163947, 20, 4, 14400000
okx = {}
for r in csv.DictReader(open(okx_csv)):
    if r["confirm"] != "1": continue
    okx[int(r["open_time"])] = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["vol_btc"]))
fut = {}
for r in csv.DictReader(gzip.open(fut_hist, "rt")):
    fut[int(r["open_time"])] = (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["volume"]))
for f in sorted(glob.glob(fut_dir + "/*.zip")):
    z = zipfile.ZipFile(f)
    for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
        if row and row[0][0].isdigit(): fut[int(row[0])] = tuple(float(x) for x in row[1:6])
T = sorted(set(okx) & set(fut)); Tn = np.array(T)
print(f"OKX 봉 {len(okx)}, 바이낸스 선물 봉 {len(fut)}, 겹치는 봉 {len(T)}, 빠진 곳 {sum(1 for a,b in zip(T,T[1:]) if b-a!=MS4)}")
def uv(D):
    A = np.array([D[t] for t in T]); o, h, l, c, v = A.T
    avg = np.full(len(T), np.nan); cs = np.cumsum(v)
    avg[AVG:] = (cs[AVG - 1:-1] - np.concatenate(([0], cs[:-AVG - 1]))) / AVG
    rng = h - l
    with np.errstate(divide="ignore", invalid="ignore"): up = (h - np.maximum(o, c)) / rng; mult = v / avg
    x = up * mult; x[(rng <= 0) | ~np.isfinite(x)] = np.nan
    return x, up, mult, c
xo, upo, mo, co = uv(okx); xf, upf, mf, cf = uv(fut)
ok = np.isfinite(xo) & np.isfinite(xf)
fwd = np.full(len(T), np.nan)
for i in range(len(T) - HOLD):
    if Tn[i + HOLD] - Tn[i] == HOLD * MS4: fwd[i] = cf[i + HOLD] / cf[i] - 1
def hac_t(z, lags=3):
    n = len(z); m = z.mean(); zc = z - m; var = (zc @ zc) / n
    for k in range(1, lags + 1): var += 2 * (1 - k / (lags + 1)) * (zc[k:] @ zc[:-k]) / n
    return m / math.sqrt(var / n)
ms_ = lambda y, mo_, d: int(dt.datetime(y, mo_, d, tzinfo=dt.timezone.utc).timestamp() * 1000)
IS = Tn < ms_(2024, 1, 1); OOS = (Tn >= ms_(2024, 1, 1)) & (Tn < ms_(2026, 9, 29)); FWD = Tn >= ms_(2026, 9, 29)
slot = np.array([dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).hour == 8 for t in T])
def block(name, m, q80=Q80, quiet=False):
    m = m & ok & np.isfinite(fwd); a = xo[m] >= q80; b = xf[m] >= Q80; r = fwd[m]; base = r.mean()
    def ex(s):
        d = s.astype(float); return (r[s].mean() - base) * 100, hac_t((d - d.mean()) * (r - base))
    eo, to = ex(a); ef, tf = ex(b); both = (a & b).sum()
    res = dict(bars=int(m.sum()), fut_long=int(b.sum()), okx_long=int(a.sum()), both=int(both), okx_in_fut_pct=round(both / a.sum() * 100), fut_in_okx_pct=round(both / b.sum() * 100),
               excess_fut=round(ef, 3), t_fut=round(tf, 2), excess_okx=round(eo, 3), t_okx=round(to, 2), corr=round(float(np.corrcoef(xo[m], xf[m])[0, 1]), 3))
    if not quiet:
        print(f"{name}: 봉 {m.sum()} | 롱 신호 바이낸스 {b.sum()}({b.mean()*100:.1f}%) OKX {a.sum()}({a.mean()*100:.1f}%) 둘 다 {both} | OKX 롱 중 바이낸스도 롱 {both/a.sum()*100:.0f}%, 바이낸스 롱 중 OKX도 롱 {both/b.sum()*100:.0f}% | 신호값 상관 {res['corr']}")
        print(f"     초과 수익: 바이낸스 신호 {ef:+.3f}%p (t {tf:.2f}) / OKX 신호 {eo:+.3f}%p (t {to:.2f}) | 아무 때나 롱 {base*100:+.3f}%")
    return res
out = {}
out["2020~2023"] = block("2020~2023 (기준을 정한 기간)", IS)
out["2024~2026-09"] = block("2024-01~2026-09 (확인 기간)", OOS)
out["2026-09-29~"] = block("2026-09-29 이후 (처음 보는 자료)", FWD)
out["9pm_2024~"] = block("밤 9시 마감 봉만, 2024-01 이후", slot & (Tn >= ms_(2024, 1, 1)))
print("부분별(전체): 윗꼬리 비율 상관 %.3f, 거래량 배수 상관 %.3f, 종가 차이 중앙값 %.3f%%" % (np.corrcoef(upo[ok], upf[ok])[0, 1], np.corrcoef(mo[ok], mf[ok])[0, 1], np.median(np.abs(co[ok] / cf[ok] - 1)) * 100))
# 연도별(OKX 신호)
print("연도별 OKX 신호 초과 수익(%p) / 바이낸스 신호:")
for y in range(2020, 2027):
    m = (Tn >= ms_(y, 1, 1)) & (Tn < ms_(y + 1, 1, 1)); r = block("", m, quiet=True); print(f"   {y}: OKX {r['excess_okx']:+.3f} (t {r['t_okx']:.2f}) / 바이낸스 {r['excess_fut']:+.3f} (t {r['t_fut']:.2f})  봉 {r['bars']}")
    out[f"year_{y}"] = r
# 사후 점검(참고): OKX 자료로 2020~2023 상위 20% 경계를 다시 잡으면
q = float(np.quantile(xo[IS & ok], 0.8)); print(f"참고(사후): OKX의 2020~2023 상위 20% 경계 = {q:.4f} (바이낸스 기준 0.4217)")
out["refit_oos"] = block("참고(사후) 경계를 OKX로 다시 잡은 확인 기간", OOS, q80=q); out["refit_q80"] = round(q, 4)
json.dump(out, open(out_json, "w"), indent=1, ensure_ascii=False)
