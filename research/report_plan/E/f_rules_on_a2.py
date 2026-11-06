"""레드팀 점검: 초안 F의 판단 규칙 ③(비용 포함 손익비 목표2>=2)·④(5만 원 단계 손절 손실<=계좌 3%)를
A2 본 시험(full) 거래 기록에 그대로 대 본다. 저장소·A2 결과는 읽기만 한다.
가정: 계좌 35.71 USDT, 0.001 BTC를 83,461 가격의 명목(83.461 USDT)으로 환산(손절 폭 %만 사용),
비용 = 진입 0.07%(시장가, A2와 같음) + 손절 0.07% + 목표 0.02%."""
import numpy as np, pandas as pd
A2 = '/tmp/claude-0/-home-user-1111/25e0663c-3dd5-5112-98b0-d8d31ac17dd0/scratchpad/team/A2/out/trades_full.csv'
t = pd.read_csv(A2)
t = t[t.taken].copy()
t['dt'] = pd.to_datetime(t.entry_ns, unit='ns', utc=True)
t['stop_pct'] = t.d / t.pe * 100
t['risk_pct'] = 83.461 * (t.stop_pct + 0.14) / 100 / 35.71 * 100
c_in, c_sl, c_tp = 0.0007, 0.0007, 0.0002
t['rr_net'] = (t.t_r * t.d - t.pe * (c_in + c_tp)) / (t.d + t.pe * (c_in + c_sl))
periods = {'IS 2020-04~2023': ('2020', '2024', 3.7), 'OOS 2024~2026-09': ('2024', '2026-09-29', 2.75)}
for var in ['V1', 'V2']:
    for name, (a, b, yrs) in periods.items():
        s = t[(t.variant == var) & (t.setup.isin(['S1L', 'S1S', 'S2L', 'S2S'])) & (t.dt >= a) & (t.dt < b)]
        ok = s[s.risk_pct <= 3]
        ok2 = ok[ok.rr_net >= 2]
        sd = ok.r.std(ddof=1) if len(ok) > 1 else np.nan
        print(f'{var} {name}: 거래 {len(s)}(연 {len(s)/yrs:.1f}) | 3% 상한 통과 {len(ok)} 평균R {ok.r.mean():+.2f} '
              f'(95%CI ±{1.96*sd/np.sqrt(max(1,len(ok))):.2f}) | +손익비>=2 통과 {len(ok2)}건(연 {len(ok2)/yrs:.1f})'
              + (f' 평균R {ok2.r.mean():+.2f}' if len(ok2) else ''))
