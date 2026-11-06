"""레드팀 점검: B의 Opus 트리거 빈도 가정(하루 3~5회)을 로컬 데이터로 하한 추정.
S(4h 마감 때 새 확정 스윙), V(1h VR>=3 또는 봉 폭>=2xATR14), D(매일 09시)만 센다. P·E·기준봉·마디·허리·박스는 빼서 '하한'이다.
기간: 2024-01-01 ~ 2026-09-28 (OOS와 같음). 저장소는 읽기만 한다."""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, '/home/user/1111')
from backtest.structure import find_swings

D = '/home/user/1111/data/binance/'
def load(tf):
    df = pd.read_csv(D + f'BTCUSDT_{tf}.csv.gz')
    df['t'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    return df

h4 = load('4h'); h1 = load('1h')
K = 3
sh, sl = find_swings(h4['high'].to_numpy(float), h4['low'].to_numpy(float), K)
# 스윙 i는 i+K 봉 마감 때 확정 -> 그 마감 시각에 S 발생
conf_idx = sorted(set([i + K for i in np.where(sh)[0]] + [i + K for i in np.where(sl)[0]]))
conf_idx = [i for i in conf_idx if i < len(h4)]
close_t = h4['t'] + pd.Timedelta(hours=4)
s_times = close_t.iloc[conf_idx]
mask = (s_times >= '2024-01-01') & (s_times < '2026-09-28')
s_times = s_times[mask]
days = (pd.Timestamp('2026-09-28', tz='UTC') - pd.Timestamp('2024-01-01', tz='UTC')).days
n4 = ((close_t >= '2024-01-01') & (close_t < '2026-09-28')).sum()
print(f'기간 {days}일, 4h 마감 {n4}회')
print(f'S(새 확정 4h 스윙이 생긴 4h 마감): {len(s_times)}회 = 하루 {len(s_times)/days:.2f}회 (4h 마감의 {len(s_times)/n4:.0%})')

# V: 1h VR>=3 또는 range>=2*ATR14 (ATR은 직전 14봉, 현재 봉 제외)
v = h1['volume'].to_numpy(float); hi = h1['high'].to_numpy(float); lo = h1['low'].to_numpy(float); c = h1['close'].to_numpy(float)
vr = v / pd.Series(v).shift(1).rolling(20).mean().to_numpy()
pc = np.r_[np.nan, c[:-1]]
tr = np.nanmax(np.vstack([hi - lo, np.abs(hi - pc), np.abs(lo - pc)]), axis=0)
atr = pd.Series(tr).shift(1).rolling(14).mean().to_numpy()
vflag = (vr >= 3) | ((hi - lo) >= 2 * atr)
t1close = h1['t'] + pd.Timedelta(hours=1)
m1 = (t1close >= '2024-01-01') & (t1close < '2026-09-28')
vt = t1close[m1 & vflag]
# 같은 종류 2시간에 1번만
kept = []
last = None
for t in vt:
    if last is None or (t - last) >= pd.Timedelta(hours=2):
        kept.append(t); last = t
print(f'V(VR>=3 또는 폭>=2ATR): 원시 {len(vt)}회 = 하루 {len(vt)/days:.2f}회, 2시간 묶음 뒤 {len(kept)}회 = 하루 {len(kept)/days:.2f}회')

# 합치기: D(00:00 UTC = 09 KST) + S + V, 같은 시각은 하나로
allt = set(pd.date_range('2024-01-02', '2026-09-27', freq='D', tz='UTC'))
allt |= set(s_times.tolist()); allt |= set(kept)
per_day = pd.Series(1, index=sorted(allt)).groupby(lambda x: (x + pd.Timedelta(hours=9)).date()).sum()
print(f'D+S+V 합(같은 시각 합침): 하루 평균 {per_day.mean():.2f}회, 중앙 {per_day.median():.0f}, 90% {per_day.quantile(.9):.0f}, 8회 이상인 날 {(per_day>=8).mean():.0%}')
