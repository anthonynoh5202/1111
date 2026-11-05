"""분석 재료 계산(프로토타입): 9/29 샘플 분석에 필요한 숫자를 뽑는다. 출력은 사람이 읽는 표."""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[2]      # 저장소 루트
sys.path.insert(0, str(REPO))
from backtest.structure import waist_cluster  # noqa: E402

MAS = (5, 20, 60, 120, 240)


def load(tf: str) -> pd.DataFrame:
    df = pd.read_csv(REPO / f"data/binance/BTCUSDT_{tf}.csv.gz")
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    for n in MAS:
        df[f"ma{n}"] = df["close"].rolling(n).mean()
    df["vavg"] = df["volume"].shift(1).rolling(20).mean()          # 직전 20봉 평균(현재 봉 제외)
    df["vr"] = df["volume"] / df["vavg"]
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["pos"] = (df["close"] - df["low"]) / rng                     # 종가 위치
    df["uw"] = (df["high"] - df[["open", "close"]].max(axis=1)) / rng
    df["lw"] = (df[["open", "close"]].min(axis=1) - df["low"]) / rng
    df["body"] = (df["close"] - df["open"]) / rng
    return df


def kst(t, tf):
    k = t.tz_convert("Asia/Seoul")
    return k.strftime("%m-%d") if tf == "1d" else k.strftime("%m-%d %H")


def idx_of(df, tf, label):
    for i in range(len(df) - 1, -1, -1):              # 가장 최근 것(연도 없는 라벨)
        if kst(df["time"].iloc[i], tf) == label:
            return i
    raise KeyError(label)


def table(df, tf, start_label):
    i0 = idx_of(df, tf, start_label)
    print(f"{'시각':>9} {'시가':>8} {'고가':>8} {'저가':>8} {'종가':>8} {'VR':>5} {'위치':>4} {'윗꼬리':>5}")
    for i in range(i0, len(df)):
        r = df.iloc[i]
        print(f"{kst(r.time, tf):>9} {r.open:8.0f} {r.high:8.0f} {r.low:8.0f} {r.close:8.0f} {r.vr:5.2f} {r.pos:4.2f} {r.uw:5.2f}")


def ma_info(df):
    t = len(df) - 1
    c = df["close"].to_numpy()
    out = {}
    for n in MAS:
        out[n] = dict(ma=round(df[f"ma{n}"].iloc[-1], 1),
                      cmp_close=round(c[t - n], 1),                 # 기울기 비교봉(이번 계산에서 빠진 봉)
                      rising=bool(c[t] > c[t - n]),
                      next_turn=round(c[t - n + 1], 1))             # 다음 봉이 이 값보다 높게 마감하면 우상향
    return out


def spread_pct(df):
    m = df[["ma20", "ma60", "ma120"]]
    s = (m.max(axis=1) - m.min(axis=1)) / df["close"]
    now = s.iloc[-1]
    pct = (s.iloc[-500:] < now).mean()
    return round(now * 100, 2), round(pct * 100, 1)


# ---------------- 닮은꼴 검색(우리 구현, 기준서 WY '닮은꼴 찾기' 절) ----------------

def _corr_rows(X, q):
    Xc = X - X.mean(axis=1, keepdims=True)
    qc = q - q.mean()
    den = np.sqrt((Xc ** 2).sum(axis=1) * (qc ** 2).sum())
    with np.errstate(invalid="ignore", divide="ignore"):
        r = (Xc @ qc) / den
    return np.nan_to_num(r)


def similar(df: pd.DataFrame, L: int, horizons: tuple[int, ...], top: int = 10, regime_n: int = 200,
            recent_bars: int = 730, seed: int = 7):
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    T = len(df) - 1
    rng_ = np.where(h - l > 0, h - l, np.nan)
    shape = np.stack([(c - o) / rng_, (h - np.maximum(o, c)) / rng_, (np.minimum(o, c) - l) / rng_], axis=1)
    shape = np.nan_to_num(shape)
    lc = np.log(c)
    W = np.lib.stride_tricks.sliding_window_view
    P = W(lc, L)                         # 행 k = 끝 인덱스 k+L-1
    S = W(shape, (L, 3)).reshape(-1, L * 3)
    V = W(v, L)
    ends = np.arange(L - 1, T + 1)
    q = len(ends) - 1                    # 지금 구간
    score = 0.5 * _corr_rows(P, P[q]) + 0.2 * _corr_rows(S, S[q]) + 0.3 * _corr_rows(V, V[q])
    nmax = max(horizons)
    ok = (ends <= T - L - 1) & (ends + nmax <= T) & (ends >= max(L, regime_n))
    cand = np.flatnonzero(ok)
    order = cand[np.argsort(-score[cand])]
    picked = []
    for k in order:
        e = ends[k]
        if all(abs(e - ends[p]) >= L / 2 for p in picked):
            picked.append(k)
        if len(picked) == top:
            break
    # 점수 차 0.02 이내면 최근 것을 위로
    changed = True
    while changed:
        changed = False
        for i in range(len(picked) - 1):
            a, b = picked[i], picked[i + 1]
            if score[a] - score[b] <= 0.02 and ends[b] > ends[a]:
                picked[i], picked[i + 1] = b, a
                changed = True
    # 무작위 기준선(상위 1%)
    rs = np.random.default_rng(seed)
    valid = np.flatnonzero(ends >= L)
    pairs = []
    while len(pairs) < 3000:
        i, j = rs.choice(valid, 2)
        if abs(i - j) >= L:
            pairs.append((i, j))
    rnd = []
    for i, j in pairs:
        s1 = _corr_rows(P[i][None], P[j])[0]
        s2 = _corr_rows(S[i][None], S[j])[0]
        s3 = _corr_rows(V[i][None], V[j])[0]
        rnd.append(0.5 * s1 + 0.2 * s2 + 0.3 * s3)
    p99 = float(np.percentile(rnd, 99))
    sma = pd.Series(c).rolling(regime_n).mean().to_numpy()
    width_now = (h[T - L + 1:T + 1].max() - l[T - L + 1:T + 1].min()) / c[T]
    rows = []
    for k in picked:
        e = int(ends[k])
        C0 = c[e]
        fw_h, fw_l = h[e + 1:e + nmax + 1], l[e + 1:e + nmax + 1]
        iu, idn = int(np.argmax(fw_h)), int(np.argmin(fw_l))
        width = (h[e - L + 1:e + 1].max() - l[e - L + 1:e + 1].min()) / C0
        rows.append(dict(
            end=df["time"].iloc[e].tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H시"), end_idx=e,
            score=round(float(score[k]), 3), width_ratio=round(float(width / width_now), 2),
            regime="200일선 위" if C0 > sma[e] else "200일선 아래",
            ret={n: round(float(c[e + n] / C0 - 1) * 100, 2) for n in horizons},
            max_up=round(float(fw_h.max() / C0 - 1) * 100, 2), max_up_bar=iu + 1,
            max_dn=round(float(fw_l.min() / C0 - 1) * 100, 2), max_dn_bar=idn + 1,
            first="상승 먼저" if iu < idn else "하락 먼저",
            recent=bool(e >= T - recent_bars)))
    # 아무 때나 골랐을 때(기준선)
    base = {}
    for n in horizons:
        e_all = np.arange(regime_n, T - n + 1)
        r = c[e_all + n] / c[e_all] - 1
        base[n] = dict(up_share=round(float((r > 0).mean()) * 100, 1), median=round(float(np.median(r)) * 100, 2))
    summ = {}
    for n in horizons:
        rr = np.array([x["ret"][n] for x in rows])
        top3 = rr[:3]
        rec = np.array([x["ret"][n] for x in rows if x["recent"]])
        summ[n] = dict(up=int((rr > 0).sum()), down=int((rr <= 0).sum()), median=round(float(np.median(rr)), 2),
                       min=float(rr.min()), max=float(rr.max()), top3=top3.tolist(),
                       recent=(rec.tolist() if len(rec) else []))
    paths = []
    for x in rows:
        e = x["end_idx"]
        paths.append((c[e:e + nmax + 1] / c[e]).tolist())
    return dict(L=L, top1=rows[0]["score"], p99=round(p99, 3), clear=bool(rows[0]["score"] >= p99),
                width_now_pct=round(float(width_now) * 100, 1), rows=rows, baseline=base, summary=summ,
                paths=paths)


def main():
    d1, h4 = load("1d"), load("4h")
    print("=== 일봉 8/10~ ===")
    table(d1, "1d", "08-10")
    print("\n=== 4시간봉 9/20 21시~ ===")
    table(h4, "4h", "09-20 21")
    T = len(d1) - 1
    print("\n=== 이평(일봉) ===", json.dumps(ma_info(d1), ensure_ascii=False))
    print("확산(일봉) % / 최근 500봉 중 백분위:", spread_pct(d1))
    print("=== 이평(4H) ===", json.dumps(ma_info(h4), ensure_ascii=False))
    print("확산(4H):", spread_pct(h4))
    # 스윙(일봉, 앞뒤 3봉)
    hh, ll = d1["high"].to_numpy(), d1["low"].to_numpy()
    sh = [i for i in range(T - 80, T - 2) if hh[i] == hh[i - 3:i + 4].max()]
    sl = [i for i in range(T - 80, T - 2) if ll[i] == ll[i - 3:i + 4].min()]
    print("일봉 스윙고점:", [(kst(d1.time[i], '1d'), hh[i]) for i in sh])
    print("일봉 스윙저점:", [(kst(d1.time[i], '1d'), ll[i]) for i in sl])
    # 마디·허리
    for name, a_lab, b_lab in (("8월 마디", None, None), ("9월 마디", "09-15", "09-21")):
        if a_lab is None:
            seg = d1.iloc[T - 60:idx_of(d1, "1d", "08-19")]
            a = int(seg["low"].idxmin())
            b = sh[[kst(d1.time[i], '1d') for i in sh].index('09-03')] if any(kst(d1.time[i], '1d') == '09-03' for i in sh) else None
        else:
            a, b = idx_of(d1, "1d", a_lab), idx_of(d1, "1d", b_lab)
        A, B = float(d1["low"][a]), float(d1["high"][b])
        H, fb = waist_cluster(d1, a, b, A, B)
        seg = d1.iloc[a:b + 1]
        print(f"{name}: A {kst(d1.time[a], '1d')} {A:.0f} → B {kst(d1.time[b], '1d')} {B:.0f}, W {B - A:.0f}, "
              f"허리(칸 방식 근사) {H:.0f} (대체값 {fb}), (A+B)/2 {(A + B) / 2:.0f}, 마디 평균 VR {seg['vr'].mean():.2f}")
    # 조정 거래량
    def avgv(df, tf, s, e):
        return df["volume"].iloc[idx_of(df, tf, s):idx_of(df, tf, e) + 1].mean()
    up = avgv(d1, "1d", "09-16", "09-21")
    dn = avgv(d1, "1d", "09-22", "09-28")
    print(f"일봉 조정(9/22~28) 평균 거래량 ÷ 상승(9/16~21) = {dn / up:.2f}")
    up4 = avgv(h4, "4h", "09-21 13", "09-23 13")
    dn4 = avgv(h4, "4h", "09-23 17", "09-29 05")
    print(f"4H 조정 평균 ÷ 상승 = {dn4 / up4:.2f}")
    # 박스(8/22~9/19)
    b0, b1 = idx_of(d1, "1d", "08-22"), idx_of(d1, "1d", "09-19")
    box = d1.iloc[b0:b1 + 1]
    print(f"박스 8/22~9/19: 고가 {box.high.max():.0f}, 저가 {box.low.min():.0f}, 종가 범위 {box.close.min():.0f}~{box.close.max():.0f}")
    # 가격 칸 터치 수(일봉 8/22~9/28, 0.25% 칸)
    seg = d1.iloc[b0:]
    vals = np.concatenate([seg[k].to_numpy() for k in ("open", "high", "low", "close")])
    bins = np.arange(74000, 88500, 250)
    cnt, _ = np.histogram(vals, bins)
    top = np.argsort(-cnt)[:8]
    print("가격 칸(250달러) 터치 상위:", [(int(bins[i]), int(cnt[i])) for i in sorted(top)])
    # 닮은꼴
    out = {}
    for tf, df, Ls, hz, reg in (("1d", d1, (20, 40, 60), (5, 10, 20), 200), ("4h", h4, (30, 60, 120), (6, 18, 42), 1200)):
        for L in Ls:
            r = similar(df, L, hz, regime_n=reg, recent_bars=730 if tf == "1d" else 730 * 6)
            out[f"{tf}_{L}"] = r
            print(f"\n=== 닮은꼴 {tf} {L}봉: 1위 {r['top1']} / 무작위 상위1% {r['p99']} → 뚜렷함 {r['clear']} · 지금 구간 폭 {r['width_now_pct']}%")
            for x in r["rows"]:
                print(f"  {x['end']} 점수 {x['score']} 폭비 {x['width_ratio']} {x['regime']} 이후 {x['ret']} "
                      f"최대↑{x['max_up']}%({x['max_up_bar']}봉) 최대↓{x['max_dn']}%({x['max_dn_bar']}봉) {x['first']}{' 최근2년' if x['recent'] else ''}")
            for n, s in r["summary"].items():
                b = r["baseline"][n]
                print(f"  {n}봉 뒤: 상승 {s['up']}/하락 {s['down']}, 중앙 {s['median']}% (범위 {s['min']}~{s['max']}), 상위3 {s['top3']}, "
                      f"최근2년 {s['recent']} | 기준선 상승비율 {b['up_share']}%, 중앙 {b['median']}%")
    dst = pathlib.Path(sys.argv[1]).expanduser()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
