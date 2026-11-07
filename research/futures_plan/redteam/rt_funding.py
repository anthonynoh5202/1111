import numpy as np, pandas as pd
f = pd.read_csv('/home/user/1111/data/binance/BTCUSDT_fundingRate.csv.gz')
t = pd.to_datetime(f.calc_time, unit='ms', utc=True).dt.round('h')
s = pd.Series(f.last_funding_rate.values.astype(float), index=t).sort_index()
s = s[~s.index.duplicated()]
print('n =', len(s), s.index[0], s.index[-1])
print('exact 0.0001 values stored as:', repr(s[s.between(0.0000999, 0.0001001)].iloc[0]), ' unique near 1e-4:', s[s.between(0.0000999, 0.0001001)].unique()[:5])
print('np.mean of 21 x 1e-4 >= 1e-4 ?', np.mean([0.0001]*21) >= 0.0001, repr(np.mean([0.0001]*21)), ' rolling:', repr(pd.Series([0.0001]*30).rolling(21).mean().iloc[-1]))
TOL = 1e-9
above = s > 0.0001 + TOL
print('last settlement > 0.01%:', s.index[above][-1])
print('settlements > 0.01% in 2025-2026:', int(above[s.index >= '2025-01-01'].sum()))
# longest negative run (settlements) by year
neg = (s < -TOL).astype(int)
runs = []
cur = 0; start = None
for ts, v in neg.items():
    if v:
        if cur == 0: start = ts
        cur += 1
    else:
        if cur: runs.append((start, cur))
        cur = 0
if cur: runs.append((start, cur))
r2026 = [r for r in runs if r[0] >= pd.Timestamp('2026-01-01', tz='UTC')]
print('longest negative settlement run in 2026: %d settlements (%.1f days) starting %s' % (max(r2026, key=lambda x: x[1])[1], max(r2026, key=lambda x: x[1])[1]/3, max(r2026, key=lambda x: x[1])[0]))
m7 = s.rolling(21).mean()
negm7 = m7 < -TOL
# longest run of negative 7d avg (in settlements)
best = (0, None); cur = 0; st = None
for ts, v in negm7.items():
    if v:
        if cur == 0: st = ts
        cur += 1
        if cur > best[0]: best = (cur, st)
    else:
        cur = 0
print('longest run 7d-avg negative: %.1f days from %s' % (best[0]/3, best[1]))
# daily average funding negative streak (calendar days) in 2026
daily = s.groupby(s.index.floor('D')).mean()
dn = daily < -TOL
best = (0, None); cur = 0
for ts, v in dn.items():
    if v:
        if cur == 0: st = ts
        cur += 1
        if cur > best[0]: best = (cur, st)
    else: cur = 0
print('longest streak of negative DAILY-average funding: %d days from %s' % best)
# Feb-May 2026 share of negative days
seg = daily['2026-02-01':'2026-05-31']
print('2026-02..05: days with negative daily avg = %d / %d' % ((seg < -TOL).sum(), len(seg)))
# Carry 'standby' trigger: 7d avg >= 0.01% (with tol) continuously for > 21 days
ok = (m7 >= 0.0001 - TOL)
cnt = 0; trig = []
for ts, v in ok.items():
    cnt = cnt + 1 if v else 0
    if cnt == 63 + 1:   # > 21 days = 63 settlements
        trig.append(ts)
print('times the >=21-day condition was first met (episodes):', len(trig))
print([str(x.date()) for x in trig])
# same but with exact comparison (no tolerance)
ok2 = (m7 >= 0.0001)
print('share of time ok with tol vs exact >=:', round(ok.mean(),3), round(ok2.mean(),3))
