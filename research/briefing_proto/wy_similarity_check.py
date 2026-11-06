"""워뇨띠 닮은꼴 규칙이 과거 2년 동안 얼마나 자주 '모임(아는 구간)'을 냈는지, 그때 맞았는지 센다(일봉, 미래 정보 없이)."""
import numpy as np, pandas as pd
df = pd.read_csv(__import__("pathlib").Path(__file__).resolve().parents[2] / "data/binance/BTCUSDT_1d.csv.gz")
o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
n = len(c); HZ = 10
rng = np.where(h - l > 0, h - l, np.nan)
shape = np.nan_to_num(np.stack([(c - o) / rng, (h - np.maximum(o, c)) / rng, (np.minimum(o, c) - l) / rng], 1))
W = np.lib.stride_tricks.sliding_window_view

def corr(X, q):
    Xc = X - X.mean(1, keepdims=True); qc = q - q.mean()
    d = np.sqrt((Xc ** 2).sum(1) * (qc ** 2).sum())
    with np.errstate(all="ignore"):
        return np.nan_to_num((Xc @ qc) / d)

res = {}
for L in (20, 40, 60):
    P, S, V = W(np.log(c), L), W(shape, (L, 3)).reshape(-1, L * 3), W(v, L)
    ends = np.arange(L - 1, n)
    rows = []
    for T in range(n - 1 - 730, n - 1 - HZ, 2):           # 최근 2년, 이틀 간격, 결과(10일 뒤)를 아는 날까지
        q = T - (L - 1)
        sc = 0.5 * corr(P, P[q]) + 0.2 * corr(S, S[q]) + 0.3 * corr(V, V[q])
        ok = (ends <= T - L - 1) & (ends + HZ <= T) & (ends >= 200)
        cand = np.flatnonzero(ok); order = cand[np.argsort(-sc[cand])]
        pk = []
        for k in order:
            if all(abs(ends[k] - ends[p]) >= L / 2 for p in pk):
                pk.append(k)
            if len(pk) == 10:
                break
        ch = True
        while ch:
            ch = False
            for i in range(len(pk) - 1):
                a, b = pk[i], pk[i + 1]
                if sc[a] - sc[b] <= 0.02 and ends[b] > ends[a]:
                    pk[i], pk[i + 1] = b, a; ch = True
        r = np.array([c[ends[k] + HZ] / c[ends[k]] - 1 for k in pk])
        up, med, t3 = int((r > 0).sum()), float(np.median(r)), r[:3]
        if up >= 8 and med > 0 and (t3 > 0).all():
            vd = 1
        elif 10 - up >= 8 and med < 0 and (t3 < 0).all():
            vd = -1
        else:
            vd = 0
        rows.append((T, vd, c[T + HZ] / c[T] - 1))
    res[L] = rows
    a = np.array([(x[1], x[2]) for x in rows])
    m = a[:, 0] != 0
    hit = ((np.sign(a[m, 1]) == a[m, 0]).mean() * 100) if m.any() else float("nan")
    print(f"일봉 {L}일 구간: 판정한 날 {len(a)}일 중 '모임' {m.sum()}일 ({m.mean()*100:.1f}%) "
          f"[상승 {int((a[:,0]==1).sum())}, 하락 {int((a[:,0]==-1).sum())}] → 10일 뒤 방향 적중 {hit:.0f}%")
# 세 길이 중 하나라도 모임이고, 서로 반대가 없는 날
T0 = [x[0] for x in res[20]]
all_v = np.array([[x[1] for x in res[L]] for L in (20, 40, 60)])
act = np.array([x[2] for x in res[20]])
anym = (all_v != 0).any(0); conflict = (all_v == 1).any(0) & (all_v == -1).any(0)
sel = anym & ~conflict
dirn = np.sign(all_v.sum(0))
print(f"세 길이 중 하나라도 '모임'(반대 판정 없음): {sel.sum()}일 / {len(sel)}일 ({sel.mean()*100:.1f}%), "
      f"10일 뒤 방향 적중 {((np.sign(act[sel]) == dirn[sel]).mean()*100):.0f}%")
print(f"기준선(같은 기간 아무 날이나 10일 뒤 상승 비율): {(act > 0).mean()*100:.0f}%")
