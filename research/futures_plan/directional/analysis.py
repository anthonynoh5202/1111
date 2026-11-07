"""Metrics tables, bootstrap CIs, beat-B&H tests, multiple-testing (DSR, max-stat, PBO), walk-forward."""
import pickle, itertools, json
from statistics import NormalDist
import numpy as np
import pandas as pd
from common import (OUT, COSTS, IS_START, IS_END, OOS_START, OOS_END, FULL_START, metrics, sl,
                    cbb_idx, sharpe_rows)

ND = NormalDist()
D = pickle.load(open(f'{OUT}/daily_results.pkl', 'rb'))
RES, FAM = D['res'], D['family']
VARIANTS = list(FAM.keys())
BENCH = ['BH-SPOT', 'BH-PERP']
ALL = BENCH + VARIANTS
WIN = {'IS': (IS_START, IS_END), 'OOS': (OOS_START, OOS_END), 'FULL': (FULL_START, OOS_END)}
NBOOT, BLOCK = 5000, 20
rng = np.random.default_rng(20261107)

# ---------------------------------------------------------------- 1. metric tables
tables = {}
for c in COSTS:
    for w, (a, b) in WIN.items():
        rows = {k: metrics(sl(RES[c][k], a, b)) for k in ALL}
        tables[(c, w)] = pd.DataFrame(rows).T
        tables[(c, w)].to_csv(f'{OUT}/metrics_{c}_{w}.csv')


def fmt_table(df, cols=('CAGR', 'Vol', 'Sharpe', 'MaxDD', 'Calmar', 'Turnover', 'InMkt', 'AvgExp',
                        'GrossYr', 'TCYr', 'FundYr', 'CostShare')):
    out = df[list(cols)].copy()
    pct = ['CAGR', 'Vol', 'MaxDD', 'InMkt', 'GrossYr', 'TCYr', 'FundYr', 'CostShare']
    for col in out.columns:
        if col in pct:
            out[col] = (out[col] * 100).map(lambda v: f'{v:.1f}' if pd.notna(v) else 'n/a')
        else:
            out[col] = out[col].map(lambda v: f'{v:.2f}' if pd.notna(v) else 'n/a')
    return out


# ---------------------------------------------------------------- 2. bootstrap
def boot_window(c, a, b):
    R = np.column_stack([sl(RES[c][k], a, b)['r'].values for k in ALL])
    n, K = R.shape
    idx = cbb_idx(n, BLOCK, NBOOT, rng)
    SR = np.empty((NBOOT, K)); MU = np.empty((NBOOT, K))
    for s in range(0, NBOOT, 250):
        X = R[idx[s:s + 250]]                       # (b, n, K)
        MU[s:s + 250] = X.mean(axis=1) * 365
        SR[s:s + 250] = X.mean(axis=1) / X.std(axis=1, ddof=1) * np.sqrt(365)
    sr0 = R.mean(0) / R.std(0, ddof=1) * np.sqrt(365)
    mu0 = R.mean(0) * 365
    return R, SR, MU, sr0, mu0


boot = {}
summary = {}
for w in ['IS', 'OOS', 'FULL']:
    a, b = WIN[w]
    R, SR, MU, sr0, mu0 = boot_window('base', a, b)
    boot[w] = (R, SR, MU, sr0, mu0)
    df = pd.DataFrame(index=ALL)
    df['Sharpe'] = sr0
    df['SR_lo'] = np.percentile(SR, 2.5, axis=0); df['SR_hi'] = np.percentile(SR, 97.5, axis=0)
    df['MeanAnn'] = mu0
    df['Mu_lo'] = np.percentile(MU, 2.5, axis=0); df['Mu_hi'] = np.percentile(MU, 97.5, axis=0)
    df['p(SR<=0)'] = ((SR - sr0) >= sr0).mean(axis=0)          # centred bootstrap, one-sided
    for bi, bn in enumerate(BENCH):
        d = SR - SR[:, [bi]]
        d0 = sr0 - sr0[bi]
        df[f'dSR_vs_{bn}'] = d0
        df[f'dSR_lo_{bn}'] = np.percentile(d, 2.5, axis=0)
        df[f'dSR_hi_{bn}'] = np.percentile(d, 97.5, axis=0)
        df[f'p_dSR_{bn}'] = ((d - d0) >= d0).mean(axis=0)
        # single-step max-T adjusted p (over the 21 variants only)
        vmask = np.array([k in VARIANTS for k in ALL])
        Tmax = (d - d0)[:, vmask].max(axis=1)
        df[f'padj_dSR_{bn}'] = [(Tmax >= x).mean() if k in VARIANTS else np.nan for k, x in zip(ALL, d0)]
    vmask = np.array([k in VARIANTS for k in ALL])
    Tmax0 = (SR - sr0)[:, vmask].max(axis=1)
    df['padj(SR<=0)'] = [(Tmax0 >= x).mean() if k in VARIANTS else np.nan for k, x in zip(ALL, sr0)]
    df.to_csv(f'{OUT}/bootstrap_{w}.csv')
    summary[w] = df

# ---------------------------------------------------------------- 3. deflated Sharpe
EULER = 0.5772156649


def dsr(R_var, names):
    """R_var: (n, K) daily returns of the K trials; returns DSR info for the best trial."""
    n, K = R_var.shape
    sr = R_var.mean(0) / R_var.std(0, ddof=1)          # per-day units
    best = int(np.argmax(sr))
    x = R_var[:, best]
    g3 = ((x - x.mean()) ** 3).mean() / x.std() ** 3
    g4 = ((x - x.mean()) ** 4).mean() / x.std() ** 4
    C = np.corrcoef(R_var.T)
    rho = (C.sum() - K) / (K * (K - 1))
    out = {}
    for label, N in [('N=21', K), ('N_eff', rho + (1 - rho) * K)]:
        N = max(N, 1.0001)
        sr0 = np.sqrt(sr.var(ddof=1)) * ((1 - EULER) * ND.inv_cdf(1 - 1 / N) + EULER * ND.inv_cdf(1 - 1 / (N * np.e)))
        z = (sr[best] - sr0) * np.sqrt(n - 1) / np.sqrt(1 - g3 * sr[best] + (g4 - 1) / 4 * sr[best] ** 2)
        out[label] = dict(N=N, SR0_ann=sr0 * np.sqrt(365), DSR=ND.cdf(z))
    # plain PSR vs 0
    z0 = sr[best] * np.sqrt(n - 1) / np.sqrt(1 - g3 * sr[best] + (g4 - 1) / 4 * sr[best] ** 2)
    return dict(best=names[best], SR_ann=sr[best] * np.sqrt(365), skew=g3, kurt=g4, avg_corr=rho,
                PSR0=ND.cdf(z0), **{f'{k}_{kk}': vv for k, v in out.items() for kk, vv in v.items()})


dsr_res = {}
for w in ['IS', 'OOS', 'FULL']:
    R = boot[w][0][:, 2:]   # variants only
    dsr_res[w] = dsr(R, VARIANTS)
# DSR of the IS-best variant evaluated OOS (honest: selection made IS)
is_best = summary['IS'].loc[VARIANTS, 'Sharpe'].idxmax()

# ---------------------------------------------------------------- 4. CSCV PBO
def cscv_pbo(R, S=16):
    n, K = R.shape
    edges = np.linspace(0, n, S + 1).astype(int)
    sums = np.array([R[edges[i]:edges[i + 1]].sum(0) for i in range(S)])
    sq = np.array([(R[edges[i]:edges[i + 1]] ** 2).sum(0) for i in range(S)])
    cnt = np.diff(edges)
    lam = []
    oos_of_best = []
    for comb in itertools.combinations(range(S), S // 2):
        m = np.zeros(S, bool); m[list(comb)] = True
        def shp(mask):
            N = cnt[mask].sum(); s1 = sums[mask].sum(0); s2 = sq[mask].sum(0)
            mu = s1 / N; var = (s2 - N * mu ** 2) / (N - 1)
            return mu / np.sqrt(var)
        si, so = shp(m), shp(~m)
        b = int(np.argmax(si))
        rank = (so < so[b]).sum() + 0.5 * ((so == so[b]).sum() - 1) + 1   # 1..K
        om = rank / (K + 1)
        lam.append(np.log(om / (1 - om)))
        oos_of_best.append(so[b] * np.sqrt(365))
    lam = np.array(lam)
    return dict(PBO=(lam <= 0).mean(), n_comb=len(lam), median_oos_SR_of_IS_best=float(np.median(oos_of_best)))


pbo = cscv_pbo(boot['FULL'][0][:, 2:])

# ---------------------------------------------------------------- 5. walk-forward
def walk_forward(c='base'):
    Rd = pd.DataFrame({k: sl(RES[c][k], FULL_START, OOS_END)['r'] for k in VARIANTS})
    W0 = pd.DataFrame({k: sl(RES[c][k], FULL_START, OOS_END)['w0'] for k in VARIANTS})
    picks = []
    seg1, seg3 = [], []
    prev1, prev3 = None, None
    for Y in range(2022, 2027):
        tr = Rd[Rd.index < pd.Timestamp(f'{Y}-01-01', tz='UTC')]
        te = Rd[(Rd.index >= pd.Timestamp(f'{Y}-01-01', tz='UTC')) & (Rd.index <= pd.Timestamp(f'{Y}-12-31', tz='UTC'))]
        sr = tr.mean() / tr.std() * np.sqrt(365)
        top = sr.sort_values(ascending=False).index[:3].tolist()
        picks.append((Y, top, sr[top].round(2).tolist()))
        r1 = te[top[0]].copy()
        r3 = te[top].mean(axis=1)
        d0 = te.index[0]
        if prev1 is not None:
            r1.iloc[0] -= abs(W0.loc[d0, top[0]] - W0.loc[d0, prev1]) * COSTS[c]
            w_new = W0.loc[d0, top].mean(); w_old = W0.loc[d0, prev3].mean()
            r3.iloc[0] -= abs(w_new - w_old) * COSTS[c]
        prev1, prev3 = top[0], top
        seg1.append(r1); seg3.append(r3)
    return picks, pd.concat(seg1), pd.concat(seg3)


picks, wf1, wf3 = walk_forward()
wf_tab = {}
for name, r in [('WF top-1', wf1), ('WF top-3 EW', wf3)]:
    d = pd.DataFrame({'r': r, 'gross': 0.0, 'tc': 0.0, 'fund': 0.0, 'trade': 0.0, 'absw': np.nan, 'inmkt': np.nan})
    wf_tab[name] = metrics(d)
for k in BENCH + ['F1 COMBO-LO']:
    wf_tab[k] = metrics(sl(RES['base'][k], wf1.index[0], wf1.index[-1]))
wf_tab = pd.DataFrame(wf_tab).T[['CAGR', 'Vol', 'Sharpe', 'MaxDD', 'Calmar']]
wf_tab.to_csv(f'{OUT}/walkforward.csv')

# ---------------------------------------------------------------- 6. calendar-year returns & beta (base)
yr = {}
for k in ALL:
    r = sl(RES['base'][k], FULL_START, OOS_END)['r']
    yr[k] = (1 + r).groupby(r.index.year).prod() - 1
yr = pd.DataFrame(yr).T
yr.to_csv(f'{OUT}/calendar_years.csv')
beta = {}
rb = sl(RES['base']['BH-SPOT'], OOS_START, OOS_END)['r']
for k in ALL:
    r = sl(RES['base'][k], OOS_START, OOS_END)['r']
    cov = np.cov(r, rb)
    b_ = cov[0, 1] / cov[1, 1]
    alpha = (r.mean() - b_ * rb.mean()) * 365
    beta[k] = dict(beta=b_, corr=np.corrcoef(r, rb)[0, 1], alpha_ann=alpha)
beta = pd.DataFrame(beta).T
beta.to_csv(f'{OUT}/beta_oos.csv')

# ---------------------------------------------------------------- dump
with open(f'{OUT}/analysis.pkl', 'wb') as f:
    pickle.dump(dict(tables=tables, summary=summary, dsr=dsr_res, pbo=pbo, picks=picks, wf=wf_tab,
                     years=yr, beta=beta, is_best=is_best), f)

pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
for w in ['IS', 'OOS']:
    print(f'\n===== {w} base costs')
    print(fmt_table(tables[('base', w)]).to_string())
for w in ['IS', 'OOS']:
    print(f'\n===== {w} maker / stress Sharpe & CAGR')
    print(pd.DataFrame({'Sh_maker': tables[('maker', w)]['Sharpe'], 'Sh_base': tables[('base', w)]['Sharpe'],
                        'Sh_stress': tables[('stress', w)]['Sharpe'],
                        'CAGR_maker': tables[('maker', w)]['CAGR'], 'CAGR_base': tables[('base', w)]['CAGR'],
                        'CAGR_stress': tables[('stress', w)]['CAGR']}).round(3).to_string())
for w in ['IS', 'OOS']:
    print(f'\n===== {w} bootstrap')
    cols = ['Sharpe', 'SR_lo', 'SR_hi', 'MeanAnn', 'Mu_lo', 'Mu_hi', 'p(SR<=0)', 'padj(SR<=0)',
            'dSR_vs_BH-SPOT', 'dSR_lo_BH-SPOT', 'dSR_hi_BH-SPOT', 'p_dSR_BH-SPOT', 'padj_dSR_BH-SPOT',
            'dSR_vs_BH-PERP', 'p_dSR_BH-PERP', 'padj_dSR_BH-PERP']
    print(summary[w][cols].round(3).to_string())
print('\nDSR', json.dumps(dsr_res, indent=1, default=float))
print('IS-best variant:', is_best)
print('PBO', pbo)
print('WF picks', picks)
print(wf_tab.round(3).to_string())
print(yr.round(3).to_string())
print(beta.round(3).to_string())
