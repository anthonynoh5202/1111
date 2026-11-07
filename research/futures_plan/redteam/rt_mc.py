import numpy as np
rng = np.random.default_rng(1)
N, T = 20000, 200
win = rng.random((N, T)) < 0.4
for f in [0.01, 0.02, 0.05]:
    mult = np.where(win, 1 + 2 * f, 1 - f)
    eq = np.cumprod(mult, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((N, 1)), eq], axis=1), axis=1)[:, 1:]
    mdd = (eq / peak - 1).min(axis=1)
    print(f'f={f:.0%}: P(MDD>=20%) = {np.mean(mdd <= -0.2)*100:.1f}%, median MDD = {np.median(mdd)*100:.1f}%')
# streaks
loss = ~win
def maxrun(row):
    best = cur = 0
    for v in row:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best
runs = np.array([maxrun(r) for r in loss[:5000]])
print('P(>=8 losses in a row) =', (runs >= 8).mean(), ' P(>=10) =', (runs >= 10).mean())
