"""체결 엔진 검증: 이진 탐색 결과를 5분봉 단순 반복과 대조."""
import numpy as np
import a2lib as A
import setups as S

mk = A.Market()
eng = A.Engine(mk, A.load_funding())
rng = np.random.default_rng(1)

def naive(j, side, stop, target):
    s = eng.starts[j]
    pe = eng.o5[s] * (1 + side * A.SLIP)
    d = side * (pe - stop)
    for k in range(A.K5):
        hi, lo, op = eng.h5[s + k], eng.l5[s + k], eng.o5[s + k]
        hs = lo <= stop if side > 0 else hi >= stop
        ht = hi > target if side > 0 else lo < target
        if hs:
            px = (min(stop, op) if side > 0 else max(stop, op)) * (1 - side * A.SLIP); fee = A.TAKER; kind = "stop"; break
        if ht:
            px = target; fee = A.MAKER; kind = "target"; break
    else:
        k = A.K5 - 1; px = eng.c5[s + k] * (1 - side * A.SLIP); fee = A.TAKER; kind = "time"
    t0, t1 = eng.t5[s], eng.t5[s + k]
    ft, fr = A.load_funding() if not hasattr(naive, "f") else naive.f
    naive.f = (ft, fr)
    fs = fr[(ft > t0) & (ft <= t1)].sum()
    r = side * (px - pe) / d - (A.TAKER * pe + fee * px) / d - side * fs * pe / d
    return r, kind, k

bad = 0
for side in (1, -1):
    js = rng.integers(1000, mk.n1 - 100, size=300)
    atr = mk.atr1[js]
    res = eng.simulate(js, side, d_atr=rng.uniform(0.5, 4, size=300), t_r=rng.uniform(0.5, 4, size=300), atr=atr)
    for i, j in enumerate(js):
        r, kind, k = naive(j, side, res["stop"][i], res["target"][i])
        if abs(r - res["r"][i]) > 1e-9 or kind != res["kind"][i]:
            bad += 1
            print("불일치", side, j, r, res["r"][i], kind, res["kind"][i])
print("불일치 건수:", bad, "/ 600")
