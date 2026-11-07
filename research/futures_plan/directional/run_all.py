"""Run all pre-registered variants + benchmarks under the three cost scenarios; save daily results."""
import pickle, time
import numpy as np
import pandas as pd
from common import (COSTS, OUT, load_klines, bar_inputs, run_engine, to_daily)
from strategies import build_all

t0 = time.time()
S = build_all()
inputs = {tf: bar_inputs(tf) for tf in ['1d', '4h', '1h']}
ret1d_nofund = bar_inputs('1d', with_funding=False)

res = {c: {} for c in COSTS}
weights = {}
for name, (tf, fam, dec) in S.items():
    target = dec.shift(1).fillna(0.0).values
    ret, F = inputs[tf]
    idx = load_klines(tf).index
    for c, cost in COSTS.items():
        out = run_engine(target, ret, F, cost)
        res[c][name] = to_daily(idx, out)
    weights[name] = (tf, target)
    print(f'{name:22s} done {time.time()-t0:6.1f}s', flush=True)

# benchmarks: always 1x long from the first bar
d1 = load_klines('1d')
tgt = np.ones(len(d1))
for c, cost in COSTS.items():
    r0, F0 = ret1d_nofund
    res[c]['BH-SPOT'] = to_daily(d1.index, run_engine(tgt, r0, F0, cost))
    r1, F1 = inputs['1d']
    res[c]['BH-PERP'] = to_daily(d1.index, run_engine(tgt, r1, F1, cost))

with open(f'{OUT}/daily_results.pkl', 'wb') as f:
    pickle.dump({'res': res, 'family': {k: v[1] for k, v in S.items()}, 'tf': {k: v[0] for k, v in S.items()}}, f)
with open(f'{OUT}/targets.pkl', 'wb') as f:
    pickle.dump({k: (v[0], v[2]) for k, v in S.items()}, f)
print('saved', time.time() - t0)
