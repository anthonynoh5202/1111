"""Render result tables as Markdown (copied into the research note)."""
import pickle
import numpy as np
import pandas as pd
from common import OUT

A = pickle.load(open(f'{OUT}/analysis.pkl', 'rb'))
S = pickle.load(open(f'{OUT}/sizing.pkl', 'rb'))
C = pickle.load(open(f'{OUT}/capital.pkl', 'rb'))
spb = pd.read_csv(f'{OUT}/spot_vs_bh_boot.csv')
out = []


def p(x, d=1):
    return 'n/a' if pd.isna(x) else f'{x * 100:.{d}f}%'


def f2(x):
    return 'n/a' if pd.isna(x) else f'{x:.2f}'


def md(df):
    cols = list(df.columns)
    s = '| ' + ' | '.join(cols) + ' |\n| ' + ' | '.join(['---'] * len(cols)) + ' |\n'
    for _, r in df.iterrows():
        s += '| ' + ' | '.join(str(v) for v in r.values) + ' |\n'
    return s


def perf(win):
    t = A['tables'][('base', win)]
    rows = []
    for k, r in t.iterrows():
        rows.append({'전략': k, 'CAGR': p(r.CAGR), '변동성': p(r.Vol, 0), 'Sharpe': f2(r.Sharpe), 'MDD': p(r.MaxDD, 0),
                     'Calmar': f2(r.Calmar), '회전율(배/년)': f'{r.Turnover:.0f}', '보유시간': p(r.InMkt, 0),
                     '평균노출': f2(r.AvgExp), '거래비용/년': p(r.TCYr), '펀딩/년': p(r.FundYr),
                     '비용÷총이익': p(r.CostShare, 0) if pd.notna(r.CostShare) and r.CostShare < 5 else ('총이익≤0' if pd.isna(r.CostShare) else '>500%')})
    return md(pd.DataFrame(rows))


out.append('## T_IS\n' + perf('IS'))
out.append('## T_OOS\n' + perf('OOS'))

# cost sensitivity
rows = []
for k in A['tables'][('base', 'IS')].index:
    rows.append({'전략': k,
                 'IS Sharpe (메이커/기본/스트레스)': ' / '.join(f2(A['tables'][(c, 'IS')].loc[k, 'Sharpe']) for c in ['maker', 'base', 'stress']),
                 'OOS Sharpe (메이커/기본/스트레스)': ' / '.join(f2(A['tables'][(c, 'OOS')].loc[k, 'Sharpe']) for c in ['maker', 'base', 'stress']),
                 'OOS CAGR (메이커/기본/스트레스)': ' / '.join(p(A['tables'][(c, 'OOS')].loc[k, 'CAGR']) for c in ['maker', 'base', 'stress'])})
out.append('## T_COST\n' + md(pd.DataFrame(rows)))

# bootstrap
for win in ['IS', 'OOS']:
    b = A['summary'][win]
    rows = []
    for k, r in b.iterrows():
        rows.append({'전략': k, 'Sharpe [95% CI]': f"{r.Sharpe:.2f} [{r.SR_lo:.2f}, {r.SR_hi:.2f}]",
                     '연평균수익(산술) [95% CI]': f"{p(r.MeanAnn, 0)} [{p(r.Mu_lo, 0)}, {p(r.Mu_hi, 0)}]",
                     'p(Sharpe≤0)': f2(r['p(SR<=0)']),
                     'ΔSharpe vs 현물B&H [95% CI]': f"{r['dSR_vs_BH-SPOT']:+.2f} [{r['dSR_lo_BH-SPOT']:+.2f}, {r['dSR_hi_BH-SPOT']:+.2f}]",
                     'p / 보정p (vs 현물)': f"{r['p_dSR_BH-SPOT']:.2f} / {f2(r['padj_dSR_BH-SPOT'])}",
                     'ΔSharpe vs 선물B&H': f"{r['dSR_vs_BH-PERP']:+.2f}",
                     'p / 보정p (vs 선물)': f"{r['p_dSR_BH-PERP']:.2f} / {f2(r['padj_dSR_BH-PERP'])}"})
    out.append(f'## T_BOOT_{win}\n' + md(pd.DataFrame(rows)))

# years
y = A['years']
yy = y.copy()
for c in yy.columns:
    yy[c] = yy[c].map(lambda v: p(v, 0))
yy.insert(0, '전략', yy.index)
yy.columns = ['전략'] + [f"{c}{'(7/20~)' if str(c) == '2020' else ''}{'(~9/28)' if str(c) == '2026' else ''}" for c in y.columns]
out.append('## T_YEARS\n' + md(yy.reset_index(drop=True)))

# walk-forward
rows = [{'시험연도': Y, '직전까지 Sharpe 상위 3개': ', '.join(f'{a} ({b:.2f})' for a, b in zip(t, s))} for Y, t, s in A['picks']]
out.append('## T_WF_PICKS\n' + md(pd.DataFrame(rows)))
wf = A['wf']
rows = [{'포트폴리오 (2022-01-01~2026-09-28)': k, 'CAGR': p(r.CAGR), '변동성': p(r.Vol, 0), 'Sharpe': f2(r.Sharpe), 'MDD': p(r.MaxDD, 0), 'Calmar': f2(r.Calmar)} for k, r in wf.iterrows()]
out.append('## T_WF\n' + md(pd.DataFrame(rows)))

# DSR / PBO
rows = []
for w, d in A['dsr'].items():
    rows.append({'구간': w, '최고 변형': d['best'], 'Sharpe': f2(d['SR_ann']), 'PSR(>0)': f2(d['PSR0']),
                 '운으로 기대되는 최고 Sharpe (N=21 / N_eff)': f"{d['N=21_SR0_ann']:.2f} / {d['N_eff_SR0_ann']:.2f} (N_eff={d['N_eff_N']:.1f})",
                 'DSR (N=21 / N_eff)': f"{d['N=21_DSR']:.2f} / {d['N_eff_DSR']:.2f}"})
out.append('## T_DSR\n' + md(pd.DataFrame(rows)) + f"\nPBO(CSCV,16블록,{A['pbo']['n_comb']}조합) = {A['pbo']['PBO']:.2f}; IS최고변형의 OOS Sharpe 중앙값 = {A['pbo']['median_oos_SR_of_IS_best']:.2f}\n")

# spot vs perp
sp = S['spot']
rows = []
for _, r in sp.iterrows():
    rows.append({'전략': r['name'], '구간': r.win, '선물 CAGR / Sharpe / MDD': f"{p(r.perp_CAGR)} / {r.perp_Sharpe:.2f} / {p(r.perp_MDD, 0)}",
                 '현물 CAGR / Sharpe / MDD': f"{p(r.spot_CAGR)} / {r.spot_Sharpe:.2f} / {p(r.spot_MDD, 0)}"})
out.append('## T_SPOT\n' + md(pd.DataFrame(rows)))
rows = []
for _, r in spb.iterrows():
    rows.append({'구간': r.win, '전략(현물 구현)': r['name'], 'Sharpe': f2(r.SR), '현물B&H Sharpe': f2(r.SR_BH),
                 'ΔSharpe [95% CI]': f"{r.dSR:+.2f} [{r.lo:+.2f}, {r.hi:+.2f}]", 'p / 보정p': f"{r.p:.2f} / {r.padj:.2f}"})
out.append('## T_SPOT_BOOT\n' + md(pd.DataFrame(rows)))

# leverage history
lt = S['levtab']
rows = []
for (name, L), g in lt.groupby(['name', 'L'], sort=False):
    fu, oo = g[g.win == 'FULL'].iloc[0], g[g.win == 'OOS'].iloc[0]
    dead = fu.liq > 0
    rows.append({'전략': name, '레버리지': f'{L:g}x', '전체 CAGR': p(fu.CAGR), '전체 MDD': p(fu.MaxDD, 0),
                 '전체 Sharpe': f2(fu.Sharpe) if not dead else '-',
                 'OOS CAGR': p(oo.CAGR) if not dead else '(이미 청산)', 'OOS MDD': p(oo.MaxDD, 0) if not dead else '-',
                 '청산 횟수': int(fu.liq)})
out.append('## T_LEV\n' + md(pd.DataFrame(rows)))

# Kelly
k = S['kelly']
rows = []
for name, g in k.groupby('name', sort=False):
    rec = {'전략': name}
    for w in ['FULL', 'IS', 'OOS']:
        r = g[g.win == w].iloc[0]
        rec[f'켈리 L* ({w})'] = f'{r.kelly_L:.2f}'
    r = g[g.win == 'FULL'].iloc[0]
    rec['연 기하성장 1x / 2x / 3x (전체)'] = f"{p(r.g1, 0)} / {p(r.g2, 0)} / {p(r.g3, 0)}"
    rows.append(rec)
out.append('## T_KELLY\n' + md(pd.DataFrame(rows)))

# bootstrap leverage paths (block 20)
b = S['boot']
rows = []
for _, r in b[b.block == 20].iterrows():
    rows.append({'전략': r['name'], '기간': '1년' if r.H == 365 else '3년', '레버리지': f'{r.L:g}x',
                 'CAGR 중앙값 [5%, 95%]': f"{p(r.med_CAGR, 0)} [{p(r.p05_CAGR, 0)}, {p(r.p95_CAGR, 0)}]",
                 '손실확률': p(r.P_loss, 0), 'MDD 중앙값': p(r.med_MDD, 0), 'P(MDD≤-50%)': p(r.P_DD50, 0), 'P(MDD≤-80%)': p(r.P_DD80, 0)})
out.append('## T_BOOTLEV\n' + md(pd.DataFrame(rows)))
rows = []
for _, r in b[(b.block == 60) & (b.H == 1095)].iterrows():
    rows.append({'전략': r['name'], '레버리지': f'{r.L:g}x', 'P(MDD≤-50%) 3년, 블록60': p(r.P_DD50, 0)})
out.append('## T_BOOTLEV60\n' + md(pd.DataFrame(rows)))

# liquidation
g = S['gen']
rows = []
for _, r in g.iterrows():
    rows.append({'보유기간(고정수량)': f'{int(r.H)}일', '최악 롱 낙폭': p(r.worst_long, 0), '최악 숏 상승': p(r.worst_short, 0),
                 '롱 청산 2x/3x/5x/10x': ' / '.join(p(r[f'long_L{L}'], 1) for L in [2, 3, 5, 10]),
                 '숏 청산 1x/2x/3x/5x': ' / '.join(p(r[f'short_L{L}'], 1) for L in [1, 2, 3, 5])})
out.append('## T_LIQ_GEN\n' + md(pd.DataFrame(rows)) + '\n임계값(진입가 대비 불리한 움직임): ' +
           ', '.join(f'{L}x {v * 100:.1f}%' for L, v in S['th'].items()) + '\n')
lt2 = S['liq_trades']
rows = [{'전략': r['name'], '거래 수': int(r.n_trades), '최악 MAE': p(r.worst_mae, 0), 'MAE 중앙값': p(r.median_mae, 1),
         '청산 거래 수 1x/2x/3x/5x/10x': ' / '.join(str(int(r[f'liq_L{L}'])) for L in [1, 2, 3, 5, 10])} for _, r in lt2.iterrows()]
out.append('## T_LIQ_TRADES\n' + md(pd.DataFrame(rows)))
ld = S['liq_daily']
rows = []
for name, gg in ld.groupby('name', sort=False):
    rows.append({'전략 (2020-01-01부터, 매일 재조정)': name, **{f'{L}x': (f"{int(r.n_liq)}회 ({r.dates})" if r.n_liq else '0') for L, r in zip(gg.L, gg.itertuples())}})
out.append('## T_LIQ_DAILY\n' + md(pd.DataFrame(rows)))
out.append('## WORST\n' + '\n'.join(f'- {k}: {v}' for k, v in S['worst'].items()) + '\n')

# discrete tiers
dsc = C['disc']
rows = []
for name, gg in dsc.groupby('name', sort=False):
    if name == 'BH-PERP':
        continue
    rec = {'전략': name}
    for _, r in gg.iterrows():
        if r.capital_usdt in (100, 300, 500, 714, 1000, 2000, 7143, 71429):
            krw = '~1억원' if r.capital_krw >= 9.9e7 else f"~{r.capital_krw / 1e4:,.0f}만원"
            rec[f"{int(r.capital_usdt):,} USDT ({krw})"] = f"{r.TE * 100:.1f}%"
    rows.append(rec)
out.append('## T_DISC (OOS 추적오차, 연율)\n' + md(pd.DataFrame(rows)))

# KRW pnl
pl = C['pl']
rows = []
for _, r in pl.iterrows():
    if r.tier != '1,000만':
        continue
    rows.append({'전략': r['name'], '레버리지': f'{r.L:g}x', '근거 데이터': {'FULL': '전체(2020-07~)', 'OOS': 'OOS(2024~)', 'FULL_half': '전체, 평균수익 절반(보수)'}[r.src],
                 '평균': f"{r['mean'] / 1e4:+,.0f}만", '중앙값': f"{r['median'] / 1e4:+,.0f}만",
                 '5%~95% 범위': f"{r.p05 / 1e4:+,.0f}만 ~ {r.p95 / 1e4:+,.0f}만", '손실확률': p(r.P_loss, 0), '-20%↓ 확률': p(r.P_loss20, 0)})
out.append('## T_KRW (1,000만원 기준, 1년)\n' + md(pd.DataFrame(rows)))

open(f'{OUT}/tables.md', 'w').write('\n'.join(out))
print('\n'.join(out))

# tiers table: median (5%~95%) per tier, selected strategies
def won(x):
    v = x / 1e4
    if abs(v) >= 10000:
        return f"{v / 1e4:+.2f}억"
    return f"{v:+,.0f}만"


rows = []
sel = [('F1 COMBO-LO', 1.0), ('F1 COMBO-LO', 2.0), ('B1 SMA50-LO', 1.0), ('D3 VT-SMA100-LO', 1.0), ('BH-SPOT', 1.0), ('BH-PERP', 1.0)]
for name, L in sel:
    for src in ['OOS', 'FULL_half']:
        g = pl[(pl['name'] == name) & (pl.L == L) & (pl.src == src)]
        rec = {'전략': f'{name} {L:g}x', '시나리오': {'OOS': 'OOS 기반', 'FULL_half': '보수(평균 절반)'}[src]}
        for tier in ['100만', '1,000만', '1억']:
            r = g[g.tier == tier].iloc[0]
            rec[f'{tier}원: 중앙값 (5%~95%)'] = f"{won(r['median'])} ({won(r.p05)} ~ {won(r.p95)})"
        rec['손실확률'] = p(g.iloc[0].P_loss, 0)
        rows.append(rec)
tt = md(pd.DataFrame(rows))
open(f'{OUT}/tables.md', 'a').write('\n## T_TIERS\n' + tt)
print(tt)
