# 기술적 분석·캔들 패턴의 수익성과 "무엇이 예측 가능한가"에 대한 학술 근거 (암호화폐 중심)

> 작성일 2026-11-07.
> **출처를 어떻게 모았나:** 이 세션에서는 WebFetch가 모든 외부 호스트(faculty.washington.edu, centaur.reading.ac.uk, cepr.org, repository.eduhk.hk, ideas.repec.org, www.cxoadvisory.com 등)에서 네트워크 허용 목록 때문에 막혔다. 그래서 아래 내용은 WebSearch가 돌려준 초록, 서지 기록, 저장소 페이지, 2차 요약에서 가져왔다. 논문 본문의 표를 직접 보지 못한 수치에는 "(2차 요약)" 또는 "(검색 요약)"을 붙였다.
> **표기:** **[PR]** 동료심사(peer-reviewed) 학술지·학회 / **[WP]** 워킹페이퍼·arXiv / **[기관]** 국제기구 보고서 / **[학위]** 학위논문 / **[업계]** 업계·언론 자료.
> **용어 메모:** *표본외(out-of-sample)* = 규칙을 만들 때 쓰지 않은 기간으로 검증하는 것. *데이터 스누핑(data snooping)* = 규칙을 아주 많이 시험해 보다가 우연히 좋아 보이는 것을 고르는 문제. 이를 보정하는 검정이 White's Reality Check, Hansen SPA다. *R²* = 예측이 실제 움직임을 얼마나 설명하는지(0~1). *손익분기 비용(break-even cost)* = 이 비용을 넘으면 전략 수익이 0이 되는 거래비용 수준.

## 1. 캔들스틱 패턴은 비용과 데이터 스누핑 검정을 거친 뒤에도 수익을 내는가 (Candlestick pattern profitability)

### Takeaway
가장 많이 인용되는 엄격한 검정인 Marshall, Young & Rose(2006)는 미국 DJIA 종목에서 28개 신호를 부트스트랩으로 검정했고, 캔들 패턴이 투자자에게 가치를 만들지 못한다고 결론 내렸다. 암호화폐 상위 23개 코인에 68개 패턴을 검정한 IEEE 학회 논문도 "크립토 매매에 거의 쓸모없다"고 보고했다. 대만 주식에서는 일부 강세 반전 패턴이 수익적이라는 결과(Lu et al. 2012)가 있다. 하지만 이는 특정 시장·기간·소수 패턴에 한정된다. 크립토에서 비용과 다중검정 보정을 통과한 캔들 패턴의 강건한 증거는 찾지 못했다.

### Cited Findings
- **[PR] Marshall, Young & Rose (2006, *Journal of Banking & Finance*)** "Candlestick technical trading strategies: Can they create value for investors?"
  - DJIA 구성종목 1992–2002 데이터로 28개 캔들 신호를 검정했다.
  - 캔들 기법은 1700년대 일본 쌀 시장에서 만들어졌으므로, 이 표본은 "명백한 표본외 검정"이다.
  - 결론: "캔들 기술적 분석을 따르는 트레이더가 시장을 이긴다는 증거가 없다."
  - 출처: [Massey Univ. 저장소(저자 학위논문 기록)](https://mro.massey.ac.nz/handle/10179/1604)
- 같은 연구의 2차 요약: 수익률이 정규분포라고 가정하지 않는 부트스트랩 검정에서, 28개 신호 중 어떤 것도 가격 움직임을 예측한다는 증거가 없었다(10일 보유 기준). — [CXO Advisory "Candlesticks, Fiddlesticks"](https://www.cxoadvisory.com/technical-trading/candlesticks-fiddlesticks/) (2차 요약)
- **[PR] Lu, Shiu & Liu (2012, *Review of Financial Economics* 21(2):63–68)**
  - 데이터: 대만 Top 50 Tracker Fund 구성종목의 일별 시가·고가·저가·종가, 2002-10-29 ~ 2008-12-31.
  - 강세 반전 3개와 약세 반전 3개 패턴을 검정했고, **강세 반전 패턴 3개가 수익적**이었다.
  - 다양한 시장 국면, 표본외 검정, 부트스트랩으로 강건성을 점검했다.
  - 출처: [EconPapers 서지·초록](https://econpapers.repec.org/RePEc:eee:revfin:v:21:y:2012:i:2:p:63-68) (거래비용 반영 방식은 본문에서 확인하지 못함)
- **[PR] Lu (2014, *Pacific-Basin Finance Journal* 26:65–78)** "The profitability of candlestick charting in the Taiwan stock market"
  - 서지만 확인했다. — [IDEAS](https://ideas.repec.org/a/eee/pacfin/v26y2014icp65-78.html)
  - 같은 연구 그룹의 단일봉(single-line) 패턴 학위논문 기록은 "4개 패턴이 거래비용 차감 후에도 대만 시장에서 수익적"이라고 보고한다. — [NCKU 학위논문 기록](https://thesis.lib.ncku.edu.tw/thesis/detail/e13ec1d499b37150eacf0e9f9891054e)
  - 이 학위논문은 2012년 논문과 별개 연구이므로 둘을 섞으면 안 된다.
- **[PR-학회] "Do Candlestick Patterns Work in Cryptocurrency Trading?" (IEEE 학회 논문)**
  - 시가총액 상위 23개 암호화폐의 **일봉** 데이터로 흔히 쓰는 캔들 패턴 **68개**를 통계 분석했다.
  - 다수 패턴의 정확도가 비교적 낮았고, 연구한 패턴들이 크립토 매매에 "거의 쓸모가 없다(of little use)"고 결론 내렸다.
  - 출처: [IEEE Xplore 9671826](https://ieeexplore.ieee.org/document/9671826); [EdUHK 저장소](https://repository.eduhk.hk/en/publications/do-candlestick-patterns-work-in-cryptocurrency-trading/)
- **[PR] *Applied Economics Letters* 29(10):947–954 (2022)**
  - 1분봉에서 양봉이나 음봉이 연속으로 나온 뒤 비트코인 선물을 데이트레이딩하는 전략(손절·익절로 청산)을 검정했다.
  - 결과 수치는 이번 세션에서 확인하지 못했다. — [IDEAS](https://ideas.repec.org/a/taf/apeclt/v29y2022i10p947-954.html)
- **[PR] PeerJ Computer Science (cs-337)** 단기 비트코인 알고리즘 매매 연구
  - 거래 수수료(검색 요약상 4%)를 넣으면, 15일 거래 기간에서는 수익을 내는 BTC 전략이 하나도 없었다.
  - 30일 기간에서는 2개 전략만 수익을 유지했다.
  - 캔들 전용 연구는 아니다. — [PeerJ PDF](https://peerj.com/articles/cs-337.pdf) (수수료 가정은 원문 확인 필요)
- **신뢰할 수 없는 자료 경고:** 한 블로그는 "CoinGecko 2026 연구", "Glassnode 2026 연구"를 인용하며 캔들 관련 수치와 극적인 사례('트리플 탑'으로 17억 달러 손실 등)를 제시한다. 출처 검증이 안 되므로 인용하지 말 것. — [Ledgermind 블로그](https://theledgermind.com/?p=1432)

### Inferences
- 캔들 모양만으로 방향을 예측한다는 주장은 미국 주식과 크립토 모두에서 학술 근거가 약하다.
- 대만의 긍정 결과는 "여러 패턴 중 일부가 통과"하는 구조라서 데이터 스누핑 위험이 크다. 다른 시장에서 재현되지도 않았다.
- '차트프로'식 규칙(거래량이 급증한 기준봉, 지지/저항, 돌파 후 눌림)은 캔들, 거래량, 가격 레벨을 합친 규칙이다. 기존 연구가 그대로 검정한 대상이 아니다.
  - 그래서 프로젝트 내부 백테스트가 유일한 검증 수단이다. 표본외 분리, 수수료·슬리피지·펀딩비 포함, 다중검정 보정이 필요하다.
- 1시간 리포트에서 캔들 패턴은 "지금 상황 설명(맥락)"으로는 쓸 수 있다. 하지만 "다음 방향 예측"으로 내세우면 근거를 과장하게 된다.

### Gaps
- Caginalp & Laurent (1998, *Applied Mathematical Finance*) "The Predictive Power of Price Patterns"는 원문 사본 링크만 확인했다([mql5 사본 PDF](https://c.mql5.com/forextsd/forum/210/The%20Predictive%20Power%20of%20Price%20Patterns.pdf)). S&P 500 종목 반전 패턴의 유의한 수익 같은 구체 수치는 검증하지 못했다.
- **장중·선물 캔들 연구**는 검색하지 못했다. 예: Marshall·Young·Cahan(2008, 일본 주식), Fock·Klein·Zwergel(2005, DAX·Bund 선물 장중), Duvinage·Mazza·Petitjean(2013, DJIA 장중). BTC 무기한 선물 1시간봉과 가장 가까운 문헌이라 추가 조사할 가치가 크다.
- "Can 1-day candlestick patterns be profitable on the 30 component stocks of the DJIA?" (*Applied Economics* 48(35), 2016)는 제목만 확인했다. — [IDEAS](https://ideas.repec.org/a/taf/applec/v48y2016i35p3345-3354.html)
- IEEE 크립토 캔들 논문의 저자, 연도, 표본기간, 비용 처리는 원문 접근이 막혀 확인하지 못했다.
- 2023–2026년 크립토 캔들 전용 동료심사 연구(딥러닝 패턴 인식 제외)는 거의 찾지 못했다.

## 2. 크립토 기술적 매매 규칙(이동평균·돌파·오실레이터): 비용, 데이터 스누핑 검정, 기간별 감쇠

### Takeaway
2010–2018년 초기 표본에서는 이동평균·돌파 규칙이 비트코인과 알트코인에서 유의한 예측력과 위험조정 수익을 보였다. 약 15,000개 규칙을 다중검정 보정한 Hudson & Urquhart(2021)도 이를 확인했다. 그러나 다음 세 가지 한계가 있다.
1. 수익의 상당수가 비용 전(gross) 수치이거나 손익분기 비용 기준이다.
2. 2017년 12월 비트코인 선물 상장 뒤 추세추종 규칙의 예측력이 급감했다(Shynkevich 2021). H&U도 비트코인의 표본외 기간에는 예측력이 없다고 보고한 것으로 보인다(검색 발췌 기준).
3. 75,360개 규칙에 비용과 데이터마이닝 보정을 적용한 2024년 연구도, 장점이 '원수익'보다 '위험 대비 성과(큰 하락 회피)'에 있다고 본다.

### Cited Findings
- **[PR] Hudson & Urquhart (2021, *Annals of Operations Research* 297:191–220; 온라인 2019-08-30; DOI 10.1007/s10479-019-03357-1)** "Technical trading and cryptocurrencies"
  - 5개 규칙군, 약 **15,000개 규칙**을 비트코인 시장 2곳과 다른 주요 코인 3개에 적용했다.
  - 다중가설 검정으로 거짓 양성을 통제한 뒤에도 **모든 규칙군, 모든 코인에서 유의한 예측력과 수익성**이 나왔다.
  - 매수 후 보유(B&H)보다 상당히 높은 위험조정 수익을 보였다.
  - 저자들이 내세운 이유: 크립토는 펀더멘털 정보가 부족해서 과거 가격이 자연스러운 신호가 된다.
  - 출처: [Reading 저장소 초록](https://centaur.reading.ac.uk/85715); [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1)
- 같은 논문은 규칙이 "길고 심한 낙폭(drawdown)에 대한 보호"를 제공한다고 했다. — [Hull 저장소](https://hull-repository.worktribe.com/output/2328042) (검색 요약)
- 같은 논문의 검색 발췌:
  - **표본외 기간에는 비트코인에서 예측력이 없고, 다른 코인에서는 예측력이 남아 있다.**
  - 손익분기 거래비용은 크립토 시장의 통상 비용보다 상당히 높다.
  - 출처: [Springer 페이지 검색 발췌](https://link.springer.com/article/10.1007/s10479-019-03357-1) (검색 발췌라서 원문 확인 권장)
- **[PR] Detzel, Liu, Strauss, Zhou & Zhu (2021, *Financial Management* 50(1):107–137)**
  - 가격과 이동평균의 비율이 비트코인 일간 수익률을 표본 안과 밖에서 모두 예측했다.
  - 이 비율에 기반한 전략은 B&H 대비 경제적으로 유의한 알파와 샤프비율 개선을 냈다.
  - 소형주, 신생기업, 애널리스트가 적게 다루는 주식, 닷컴 시기 나스닥에서도 비슷한 결과가 나왔다.
  - 합리적 학습으로 기술적 분석이 자연스럽게 생겨나는 균형 모형을 제시했다.
  - 출처: [IDEAS](https://ideas.repec.org/a/bla/finmgt/v50y2021i1p107-137.html); [EconPapers](https://econpapers.repec.org/RePEc:bla:finmgt:v:50:y:2021:i:1:p:107-137)
- 같은 연구의 2018년 WP 수치("Bitcoin: Predictability and Profitability via Technical Analysis", 2010–2017 표본). **모두 비용 전(gross) 수치**다.

  | 항목 | B&H | SMA 전략 |
  |---|---|---|
  | 연환산 초과수익 | 224% | 203–216% |
  | 연환산 변동성 | 111% | 83.8–97.0% |
  | 샤프비율 | 2.0 | 2.6(5일 SMA) → 2.2(100일 SMA) |
  | 최대낙폭 | −89.5% | 미확인 |
  | **손익분기 전환 비용** | — | 1.1%(5일 SMA) → 4.5%(100일 SMA) |

  - 요약자는 당시 비트코인의 긴 체결 시간과 큰 마찰 비용이 손익분기 비용을 넘었을 수 있다고 경고했다.
  - 출처: [CXO Advisory "Timing Bitcoin with SMAs"](https://www.cxoadvisory.com/currency-trading/timing-bitcoin-with-smas/) (2차 요약)
- **[PR] Corbet, Eraslan, Lucey & Sensoy (2019, *Finance Research Letters* 31:32–37)**
  - 고빈도 비트코인 수익률로 이동평균 오실레이터와 거래범위돌파(TRB: 지지·저항 돌파) 규칙을 검정했다.
  - 이동평균 전략이 지지를 받았고, **가변 길이 이동평균(VMA)** 이 가장 좋은 성과를 냈다.
  - 매수 신호의 수익이 매도 신호보다 높았다.
  - 출처: [DCU 저장소](https://doras.dcu.ie/25053); [EconPapers](https://econpapers.repec.org/RePEc:eee:finlet:v:31:y:2019:i:c:p:32-37)
- **[PR] Grobys, Ahmed & Sapkota (2020, *Finance Research Letters* 32:101396)**
  - VMA 오실레이터(단기와 장기 이동평균 비교)를 검정했고, 20일 이동평균 전략이 가장 좋았다.
  - **비트코인을 제외하면** 시장 평균 수익을 통제한 뒤 연 8.76% 초과수익이 났다.
  - 결론: 크립토 시장은 비효율적이다.
  - 출처: [IDEAS](https://ideas.repec.org/a/eee/finlet/v32y2020ics1544612319308852.html); [Vaasa대 저장소](https://osuva.uwasa.fi/handle/11111/619)
- **[PR] Ahmed, Grobys & Sapkota (2020, *Finance Research Letters* 35)** — 프라이버시 코인 10종 전체에 적용하면, 단순 기술 규칙은 합산 기준으로 일관된 수익을 내지 못했다. — [IDEAS](https://ideas.repec.org/a/eee/finlet/v35y2020ics1544612320300829.html)
- **[PR] Gerritsen, Bouri, Ramezanifar & Roubaud (2020, *Finance Research Letters* 34)**
  - 추세추종 지표 7종을 검정했다.
  - **거래범위돌파(TRB)** 규칙은 강한 추세장에서 가치를 더했다(정상장·호황장 하위기간에서 대체로 지지됨). TRB는 비트코인 가격에 유의한 예측력을 보였다.
  - 출처: [Utrecht 포털](https://research-portal.uu.nl/en/publications/the-profitability-of-technical-trading-rules-in-the-bitcoin-marke/); [Utrecht dspace](https://dspace.library.uu.nl/handle/1874/407735)
  - 비공식 요약에 따르면: 일별 2010-07 ~ 2018-12, TRB 평균 샤프 약 0.08, RSI·볼린저밴드 같은 역추세 지표는 대체로 B&H보다 못함, **거래비용 미반영**. — [TradingView 요약](https://my.tradingview.com/chart/BTCUSD/tK5t6vU6-The-profitability-of-TA-trading-rules-in-the-Bitcoin-market) (비공식, 원문 확인 필요)
- **[PR] Shynkevich (2021, *Journal of Futures Markets* 41(1):115–134)** "Impact of bitcoin futures on the informational efficiency of bitcoin spot market"
  - **2017년 12월 비트코인 선물 도입 전까지는 유의한 수익률 예측력이 있었다. 그 뒤로 추세추종 규칙의 예측력이 "급격히(dramatically)" 줄었다.**
  - 이더리움에서는 효율성이 개선된 징후가 없었다.
  - 출처: [EconPapers](https://econpapers.repec.org/RePEc:wly:jfutmk:v:41:y:2021:i:1:p:115-134)
- **[PR] Deprez & Frömmel (2024, *International Review of Economics & Finance* 93(B):858–874)** "Are simple technical trading rules profitable in bitcoin markets?"
  - 6개 규칙군 **75,360개 규칙**을 일간과 장중 빈도에서 검정했고, 거래비용과 데이터마이닝 보정을 적용했다.
  - 단순 규칙이 표본외에서 B&H를 이길 수 있었지만, **주로 위험 대비 수익 측면(risk–return wise)** 에서였다.
  - 출처: [EconPapers](https://econpapers.repec.org/RePEc:eee:reveco:v:93:y:2024:i:pb:p:858-874) (저자명과 세부 내용은 검색 요약 기준)
- **[PR] Resta, Pagnottoni & De Giuli (2020, *Risks* 8(2):44)** — 일간 빈도 매매가 장중 매매보다 전반적으로 더 수익적이었다. — [IDEAS](https://ideas.repec.org/a/gam/jrisks/v8y2020i2p44-d354452.html) (검색 요약)
- **[PR] "Forecasting Bitcoin with technical analysis: A not-so-random forest?"** (*International Journal of Forecasting*, 검색 요약 기준)
  - 비트코인 가격은 **1시간 빈도에서 약형 효율적**이다. 즉 과거 가격만으로는 시간 단위 예측이 어렵다.
  - 기술 지표에 비선형 모형을 결합하면 **일간** 시계에서 랜덤워크보다 통계적으로 유의하게 나았다.
  - 출처: [AMiner](https://www.aminer.org/pub/62283eb15aee126c0fdfb0d8/forecasting-bitcoin-with-technical-analysis-a-not-so-random-forest)
- **[PR] *Journal of Capital Markets Studies*(Emerald) "Technical trading rules' profitability and dynamic risk premiums of cryptocurrency exchange rates"** — 검색 요약에 따르면, 시간에 따라 변하는 위험프리미엄을 고려한 뒤에도 기술적 분석이 수익적이었다. — [Emerald](https://emerald.com/insight/content/doi/10.1108/JCMS-10-2021-0030); [UJ 학위 기록](https://ujcontent.uj.ac.za/esploro/outputs/graduate/Technical-trading-rules-profitability-and-dynamic/9914909007691) (요약과 출처의 연결이 불명확하므로 원문 확인 필요)
- **[학위] Bakker (Erasmus)** — 크립토에서 여러 기술 전략이 데이터 스누핑과 거래비용을 조정한 뒤에도 유의하게 수익적이었다. — [Erasmus 학위논문 PDF](https://thesis.eur.nl/pub/41546/Bakker.pdf) (비동료심사)
- **데이터 스누핑 검정 방법론(주식 문헌)**
  - Sullivan, Timmermann & White(1999, *Journal of Finance*)는 White의 부트스트랩 Reality Check로, 약 100년치 DJIA 일별 데이터에서 규칙 전체의 데이터 스누핑 효과를 측정했다. — [STW 논문 PDF(강의자료 사본)](https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf)
  - White's Reality Check와 Hansen SPA로 재검토한 연구는 "유의하게 수익적인 단순 규칙이 상대적으로 '젊은' 시장(NASDAQ Composite, Russell 2000)에는 있고, '성숙한' 시장(DJIA, S&P 500)에는 없다"고 보고했다. — [재검토 논문 PDF 사본](https://c.mql5.com/forextsd/forum/211/Re-Examining%20the%20Profitability%20of%20Technical%20Analysis%20with%20Whitets%20Reality%20Check%20and%20Hansen9s%20SPA%20Tes.pdf) (저자는 Hsu & Kuan, *Journal of Financial Econometrics* 2005로 알려져 있으나 이번 세션에서 검증하지 못함)

### Inferences
- **패턴:** 초기의 미성숙한 표본(2010–2018)에서는 추세추종(이동평균·돌파) 규칙이 강했다. 선물 도입(2017.12)과 시장 성숙 이후 비트코인에서는 크게 약해졌다.
  - 근거: Shynkevich, H&U의 표본외 BTC 무예측력, Grobys의 "비트코인 제외" 결과.
  - 알트코인이나 젊은 시장에서 수익이 더 오래 남는 경향은 주식의 "젊은 시장 vs 성숙한 시장" 결과와 같은 방향이다.
- **남아 있는 쓸모:** "더 많이 버는 것"보다 **"큰 하락장을 피해 위험 대비 성과를 높이는 것"** 이다(H&U의 낙폭 보호, Deprez & Frömmel의 위험-수익 기준). 즉 추세 필터는 '지금 어떤 장세인가'를 판별하는 용도로 의미가 있다.
- **'돌파 후 눌림' 규칙과의 연결:** 차트프로식 '돌파 후 눌림'에 가장 가까운 학술 규칙은 TRB(지지·저항 돌파)다. TRB는 강한 추세장에서만, 그것도 비용 전 기준으로 가치를 보였다(Gerritsen; Corbet).
- **빈도:** 일간이 장중보다 나았고(Resta), 1시간 빈도는 약형 효율적이었다. 따라서 1시간 단위 방향 신호는 근거가 가장 약하고 비용 부담은 가장 크다. 이동평균이 짧을수록 손익분기 비용이 낮다(Detzel WP: 5일 1.1% vs 100일 4.5%).
- **프로젝트 백테스트 체크리스트(문헌 기준):**
  - 표본외 기간 분리
  - 하위기간 안정성(특히 2018년 이후, 2024년 ETF 이후)
  - 수수료, 슬리피지, 펀딩비 반영
  - 다중검정 보정(White RC, Hansen SPA, StepM 등)
  - B&H 및 위험조정 지표와 비교

### Gaps
- 원문 접근이 막혀 다음은 확인하지 못했다: H&U의 정확한 표본 기간과 규칙별 수익 수치, Deprez & Frömmel의 표본기간·살아남은 규칙군·장중 결과.
- STW(1999)의 "표본내 최고 규칙이 이후 1987–1996 표본외에서는 유의하지 않다"는 결과는 널리 인용되지만, 이번 세션에서 검증하지 못했다.
- 바이낸스 BTCUSDT **무기한 선물**(펀딩비 포함)을 대상으로 다중검정 보정까지 한 동료심사 연구는 찾지 못했다.
- 2025–2026년 최신 표본(현물 ETF 승인 이후)에서 기술 규칙 수익성을 다룬 연구는 찾지 못했다. arXiv 2602.10785가 검색됐지만 내용은 확인하지 못했다. — [arXiv](https://arxiv.org/html/2602.10785v1)

## 3. 시계열 모멘텀·추세추종, 장중 모멘텀, 요일·시간대 효과

### Takeaway
- Liu & Tsyvinski(2021, RFS)는 BTC·ETH·XRP에 일간·주간 시계열 모멘텀이 유의하다고 보였다.
- Liu·Tsyvinski·Wu(2022, JF)는 시장·규모·모멘텀 3요인이 코인 간 수익 차이를 설명한다고 보였다.
- 다만 두 연구 모두 2018년 이전이 중심인 미성숙 시장 표본이고, 비용 전 결과다.
- 장중에서는 거래량으로 정의한 "첫 30분 → 마지막 30분" 모멘텀이 보고됐다(Shen·Urquhart·Wang 2022).
- 요일·시간대 **수익률** 이상현상은 오래가지 않았지만, **거래량** 패턴은 지속적이었다(Baur et al. 2019).

### Cited Findings
- **[PR] Liu & Tsyvinski (2021, *Review of Financial Studies* 34(6):2689–2727; NBER WP 24877, 2018)** "Risks and Returns of Cryptocurrency" — "비트코인·리플·이더리움 세 코인 모두 일간·주간 빈도에서 유의한 시계열 모멘텀"이 있다. — [NBER WP PDF](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf); [SSRN](https://papers.ssrn.com/abstract=3226806)
- 같은 연구의 요약: 비트코인 주간 수익률에서 이번 주 수익률이 1표준편차 높으면, 다음 1주 수익률이 **3.16%** 높다. — [VoxEU 칼럼](https://cepr.org/voxeu/columns/risks-and-returns-cryptocurrencies); [WEF 재게재](https://www.weforum.org/stories/2018/09/what-are-the-risks-and-returns-associated-with-cryptocurrencies/) (2차 요약)
- **[PR] Liu, Tsyvinski & Wu (2022, *Journal of Finance* 77(2):1133–1177; NBER WP 25882, 2019)** "Common Risk Factors in Cryptocurrency"
  - 크립토 **시장·규모·모멘텀** 3요인이 코인별 기대수익 차이를 설명한다.
  - 주식에서 쓰는 요인 25개 중 9개가 유의한 롱숏 초과수익을 냈고, 9개 모두 3요인 모형으로 설명됐다.
  - 출처: [NBER PDF](https://www.nber.org/papers/w25882.pdf); [EconPapers](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:2:p:1133-1177)
  - 2차 요약에 따르면: 표본은 약 1,700개 코인, 2014–2018년이다. 모멘텀은 대형 코인에서 더 강했다. 초기 미성숙 시장이고 비용 전(gross) 수익이라는 한계가 있다. — [CXO Advisory](https://cxoadvisory.com/size-effect/cryptocurrency-factor-model) (2차 요약)
  - 출처 충돌: Alpha Architect 페이지는 게재지를 *Economic Modelling* 2020으로 적었는데, JF 기록과 맞지 않는다. 오기로 보인다. — [Alpha Architect](https://alphaarchitect.com/2022/06/factors-investing-in-cryptocurrency)
- **[PR] Shen, Urquhart & Wang (2022, *Financial Review* 57(2):319–344; 온라인 2021-10-26)** "Bitcoin intraday time-series momentum"
  - 24시간 열리는 시장이라 장 시작·마감이 없으므로, 거래량을 "시장 시간"의 대리변수로 썼다.
  - **첫 30분 수익률이 마지막 30분 수익률을 양(+)의 방향으로 예측했다.**
  - 거래량과 변동성이 가장 큰 세션에서 예측력이 가장 컸다.
  - 원인은 늦게 정보를 얻은 거래가 아니라 **유동성 공급**이었다. 외환시장 결과와 같다.
  - 시장 타이밍과 자산배분에서 상당한 경제적 이득이 있었고, 특히 비트코인 하락장에서 컸다.
  - 출처: [Birmingham 포털](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/); [Reading 저장소](https://centaur.reading.ac.uk/100181)
- **[PR] Baur, Cahill, Godfrey & Liu (2019, *Finance Research Letters* 31:78–92)**
  - 7개 거래소, 1,500만 개가 넘는 관측치를 썼다.
  - 수익률: **특정 시기의 이상현상은 있지만, 시간이 지나도 지속되는 효과는 없었다.**
  - 거래 활동: 모든 거래소에서 **지속적인 차이**가 있었다. 현지 저녁과 주말에는 낮고, 미국 주식시장 개장 시간에는 높고, 자정부터 새벽까지는 낮았다.
  - 결론: 비트코인은 약형 효율적이다.
  - 출처: [EconPapers](https://econpapers.repec.org/RePEc:eee:finlet:v:31:y:2019:i:c:p:78-92)
  - 2차 요약: USD 거래소의 패턴이 더 강했고, 주말 거래량 감소와 월요일 수익 증가는 외환시장과 비슷했다. — [Quantpedia](https://quantpedia.com/are-there-any-simple-calendar-effects-in-bitcoin-market/)
- **[WP] arXiv 2109.12142** — 비트코인과 이더의 요일·시간대별 **변동성과 거래량** 패턴을 보고했다. — [arXiv PDF](https://arxiv.org/pdf/2109.12142v2.pdf) (세부 수치 미확인)
- **[PR] Kogan, Makarov, Niessner & Schoar (*Journal of Financial Economics* 159:103897; NBER WP 31317, 2023)** "Are Cryptos Different? Evidence from Retail Trading"
  - eToro 개인투자자 20만 명을 분석했다.
  - 같은 투자자가 주식과 금에서는 **역추세(contrarian)** 로, 크립토에서는 **모멘텀**으로 매매했다.
  - 큰 가격 변동 뒤에도 크립토 포지션을 유지했고, 개인 특성으로는 이 차이가 설명되지 않았다.
  - 저자들이 제시한 메커니즘: 투자자들은 "가격이 오르면 미래에 더 널리 쓰일 가능성이 커진다"는 머릿속 모형을 갖고 있다.
  - 출처: [NBER](https://www.nber.org/papers/w31317); [Alpha Architect 요약](https://alphaarchitect.com/are-cryptos-different/)

### Inferences
- 기술적 신호 중 학술 근거가 가장 강한 것은 **일간·주간 모멘텀(추세)** 이다. 1시간 단위의 근거는 장중 특정 구간(거래량 기준 첫 구간과 마지막 구간) 정도로 제한적이다.
- 개인이 크립토에서 모멘텀을 따른다는 사실(Kogan et al.)은 모멘텀이 개인 수요에서 생길 수 있음을 시사한다. 동시에 과열과 급반전 위험도 키운다. 이는 4번의 청산 문헌과 연결된다.
- 거래량에는 시간대·요일 패턴이 **지속적으로** 있다. 따라서 '기준봉 거래량 급증'은 단순 평균과 비교하지 말고, **같은 요일·같은 시간대 평균과 비교**해서 정규화해야 한다. 그래야 주말·새벽의 가짜 신호나 놓친 신호가 줄어든다(Baur et al. 근거).

### Gaps
- Liu & Tsyvinski 시계열 모멘텀의 롱숏 수익과 샤프 수치는 원문 표를 확인하지 못했다. Scribd 사본 스니펫의 "상위 5분위 주 11.20%, 샤프 0.48"은 맥락이 불명확해 쓰지 않았다.
- 2019년 이후 표본으로 LT 시계열 모멘텀을 재현한 연구는 이번 세션에서 찾지 못했다. JFQA의 크립토 "trend factor" 논문 PDF가 검색됐지만 내용은 확인하지 못했다. — [JFQA PDF](https://jfqa.org/wp-content/uploads/2024/09/24955-trend-factor-cross-section-crypto-returns.pdf)
- 다음은 내용을 확인하지 못했다: Wen et al.(2022) 크립토 장중 모멘텀/반전, Caporale & Plastun(2019) 요일효과, 하루 비정상수익 뒤의 모멘텀 연구(Brunel WP: [PDF](https://www.brunel.ac.uk/economics-finance-and-accounting/research/pdf/1917-Oct-GMC-Momentum-effect-in-the-Cryptocurrency-Market-after-One-day-Abnormal-Returns.pdf)).

## 4. 개인 데이트레이더와 크립토 선물 개인투자자의 성과

### Takeaway
대규모 행정자료 연구들은 나라와 자산을 가리지 않고 같은 결과를 보인다. 개인 데이트레이더 대다수는 손실을 본다.
- 대만(1992–2006): 수수료를 뺀 뒤 꾸준히 이익을 낸 데이트레이더는 1% 미만이었다.
- 브라질 지수선물: 최저임금보다 많이 번 데이트레이더는 1.1%였다.
- 크립토: BIS는 2015–2022년 앱 사용자의 과반이 BTC에서 손실을 봤다고 추정했다.
- 무기한 선물: 강제청산, 즉시성(시장가 체결), 수수료가 개인에게서 다른 참여자로 돈이 옮겨 가는 주된 경로였다(Hyperliquid 연구, 2026). BitMEX에서 청산된 트레이더의 평균 레버리지는 약 58–60배였다.

### Cited Findings
- **[PR] Barber, Lee, Liu & Odean (2014, *Journal of Financial Markets* 18:1–24)** "The Cross-Section of Speculator Skill: Evidence from Day Trading"
  - 대만증권거래소 1992–2006년 전체 거래 기록을 썼다.
  - 데이트레이더 중 **수수료를 뺀 뒤에도 예측 가능하고 꾸준하게 양(+)의 비정상수익을 내는 비율은 1% 미만**이었다.
  - 출처: [EconPapers](https://econpapers.repec.org/RePEc:eee:finmar:v:18:y:2014:i:c:p:1-24); [eScholarship](https://escholarship.org/uc/item/7k75v0qx)
  - 검색 요약에 따르면: 전년도 수익 상위 500명은 이후 수수료 뒤 하루 약 37.9bp를 벌었고, 최하위 그룹은 하루 약 −28.9bp를 잃었다. 원문 표 확인이 필요하다. — [Berkeley 사본 PDF](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/Day%20Trading%20Skill%20110523.pdf)
- **[WP] Chague, De-Losso & Giovannetti ("Day Trading for a Living?", SSRN 3423101, 2019)**
  - 브라질 증권당국 자료로, 2013–2015년에 처음 미니 보베스파 지수선물 데이트레이딩을 시작한 개인 19,646명을 분석했다.
  - 최저임금보다 많이 번 사람은 **1.1%**, 은행 창구직원 초봉보다 많이 번 사람은 **0.5%** 였다.
  - 데이트레이딩을 하면서 실력이 는다는 증거가 없었다.
  - 출처: [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101); [EconPapers](https://econpapers.repec.org/RePEc:fgv:eesptd:525)
  - 2차 요약: 300일 넘게 지속한 사람의 **97%가 손실**을 봤다. 이는 거래소·중개 수수료를 뺀 뒤이고, 소득세·플랫폼·강의비를 빼기 전 수치다. — [CXO Advisory](https://www.cxoadvisory.com/investing-expertise/day-trading-a-bust/); [Quantpedia](https://quantpedia.com/retail-day-trading-is-an-uphill-battle/)
- **[기관] BIS Bulletin No 69 "Crypto shocks and retail losses" (2023-02-20; Cornelli, Doerr, Frost, Gambacorta)**
  - 2015-08 ~ 2022-12 주요 크립토 거래 앱 데이터를 썼다.
  - 거의 모든 국가에서 **크립토 앱 사용자의 과반이 비트코인 보유로 손실**을 봤다. 앱을 처음 내려받은 달부터 매달 $100어치를 샀다고 가정한 추정이다.
  - 사용자의 약 3/4이 BTC 가격이 $20,000 이상일 때 앱을 내려받았다.
  - 급락 전에 1,000 BTC 이상을 가진 대형 보유자('고래')는 팔았고, 소액 개인('크릴')은 샀다.
  - 출처: [BIS](https://www.bis.org/publ/bisbull69.htm); [BIS PDF](https://www.bis.org/publ/bisbull69.pdf)
- **[PR-학회] Jia, Moallemi, Wang & Zeng (AFT 2026, LIPIcs)** "Who Loses and Why? Market Microstructure of Perpetual Futures"
  - Hyperliquid의 전체 온체인 주문·체결 기록(2025-03-27 ~ 06-30)을 분석했다.
  - 웹 화면에서 손으로 거래하는 지갑을 대부분 개인으로 분류했다.
  - **즉시성(시장가 체결), 강제 청산, 수수료**가 참여자 사이 돈이 옮겨 가는 주된 경로였다.
  - 출처: [Dagstuhl LIPIcs](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2026.36)
- **[WP] "Liquidation, Leverage and Optimal Margin in Bitcoin Futures Markets" (arXiv 2102.04591)** — BitMEX 무기한 선물에서 강제청산된 트레이더의 평균 레버리지는 롱 **58.13배**, 숏 **59.94배**였다. — [arXiv](https://arxiv.org/pdf/2102.04591)
- **[WP] 자동 디레버리징(ADL) 연구 (arXiv 2512.01112)** — 저자는 자기가 아는 한 무기한 선물 거래소의 청산을 정식으로 연구한 논문이 없었다고 썼다. 학술 근거가 얇다는 신호다. — [arXiv](https://arxiv.org/pdf/2512.01112)
- **[업계] Coinglass 2025 연간 보고서(뉴스 요약 경유)** — 2025년 총 청산액은 약 **1,546.4억 달러**였다. — [MEXC 뉴스 1](https://www.mexc.com/news/388166); [MEXC 뉴스 2](https://www.mexc.com/news/388471) (업계 집계라 검증되지 않았고, 두 페이지 중 어느 쪽이 출처인지도 확정하지 못함)

### Inferences
- 개인 단기매매의 대다수가 손실을 본다는 것은 나라, 자산, 시대를 넘어 반복되는 강한 결과다. 크립토 무기한 선물은 높은 레버리지와 강제청산 구조가 손실 경로를 하나 더 얹는다.
- 도구가 "고수의 규칙"을 따라 하게 한다고 성과가 보장되지는 않는다. 워뇨띠 같은 성공 사례는 살아남은 사람만 보이는 생존자 편향일 수 있다.
- 따라서 리포트에 레버리지, 청산까지의 거리, 비용 경고를 기본으로 넣는 것이 근거에 맞다. 프로젝트의 LIVE 금지 원칙과도 일치한다.
- Hyperliquid 연구 결과에 맞추려면, 리포트가 "시장가로 추격 진입"을 부추기지 않도록 설계해야 한다(즉시성 비용).

### Gaps
- 바이낸스·바이빗 같은 중앙화 거래소에서 개인 선물 트레이더의 손익 분포를 다룬 동료심사 연구는 찾지 못했다. 거래소 내부 데이터가 공개되지 않기 때문이다.
- 한국 개인투자자(업비트·빗썸, 해외 선물 이용자)를 대상으로 한 성과 연구는 검색하지 않았다.
- Chague et al.이 학술지에 실렸는지는 확인하지 못했다. SSRN/FGV 워킹페이퍼로만 확인했다.
- Barber et al.(2014)의 상위·하위 그룹 bp 수치는 검색 요약 기준이다.

## 5. 변동성 vs 방향(수익률): 무엇이 더 예측 가능한가 (GARCH/HAR-RV, 내재변동성, R² 비교)

### Takeaway
- **변동성**은 몰려서 나타나고(군집) 오래 이어지는(장기기억) 성질 때문에 꽤 예측할 수 있다. HAR 계열 모형은 비트코인에서도 표본외 성능이 좋았고, 1일 Mincer-Zarnowitz R²가 약 0.27–0.29인 사례가 있다. 다만 이 수치는 비동료심사 자료 1건 기준이다.
- **방향(수익률)** 은 거의 예측되지 않는다. 비트코인 일간 표본외 R²는 최고 약 2–3% 수준이고, 예측변수 대부분이 표본외에서 실패한다.
- **내재변동성**(Deribit 옵션)은 단독으로는 HAR보다 못하다. 하지만 모형 예측과 결합하면 정확도가 가장 높았다.
- 이론상 변동성 예측력은 기대수익이 0이 아닐 때 약간의 '부호(방향)' 예측력을 만든다. 그 효과는 일간보다 중간 길이 시계에서 더 잘 나타난다.

### Cited Findings
- **[PR] Andersen & Bollerslev (1998, *International Economic Review* 39(4):885–905)** "Answering the Skeptics: Yes, Standard Volatility Models Do Provide Accurate Forecasts"
  - 일간 제곱수익률을 정답으로 쓰면 변동성 예측이 나빠 보인다. 하지만 이는 **정답으로 쓴 지표에 잡음이 많기 때문**이다.
  - 좋은 변동성 예측과, 제곱수익률 대비 낮은 R²는 서로 모순되지 않는다.
  - 장중 고빈도 데이터로 만든 실현변동성으로 평가하면, 표준 모형이 "놀랄 만큼 정확한" 일간 예측을 낸다.
  - 출처: [EconPapers](https://econpapers.repec.org/RePEc:ier:iecrev:v:39:y:1998:i:4:p:885-905); [NBER WP 6023](https://www.nber.org/papers/w6023)
- **[PR] Corsi (2009, *Journal of Financial Econometrics* 7(2):174–196)** HAR-RV
  - 일·주·월 변동성 성분을 더해서 만든 모형이다.
  - 형식상 장기기억 모형이 아닌데도, 데이터에 보이는 장기기억 같은 지속성을 재현한다. 예측 성능도 "매우 좋다".
  - 출처: [EconPapers](https://econpapers.repec.org/RePEc:oup:jfinec:v:7:y:2009:i:2:p:174-196); [SSRN](https://papers.ssrn.com/abstract=1365738)
- **[PR] Christoffersen & Diebold (2006, *Management Science* 52(8):1273–1287; NBER WP 10009)**
  - 기대수익이 0이 아니면, **변동성이 예측 가능하다는 것은 부호(방향)도 어느 정도 예측 가능하다는 뜻**이다.
  - 평균 수익률을 예측할 수 없어도 부호와 변동성은 예측할 수 있다.
  - 이 부호 예측력은 비선형이라 부호 자기상관, 런 검정, 전통적 마켓타이밍 검정으로는 잘 잡히지 않는다.
  - **일간이나 연간보다 중간 길이 시계에서 나타날 가능성이 크다.** 미국 주식에서 확인됐다.
  - 출처: [NBER](https://www.nber.org/papers/w10009); [EconPapers](https://econpapers.repec.org/RePEc:inm:ormnsc:v:52:y:2006:i:8:p:1273-1287)
- **[PR] Shen, Urquhart & Wang (2020)** 비트코인 변동성 예측
  - HAR 변형 18개를 1일 ~ 2개월 시계에서 비교했다.
  - 표본외에서는 **HARQ-F-J**가 가장 좋았고, 점프(가격 급변)가 모든 시계에서 중요했다.
  - 출처: [Reading 저장소 수정본 PDF](https://centaur.reading.ac.uk/87932/1/R%26R_Forecasting%20the%20Volatility%20of%20Bitcoin_complete.pdf) (게재지는 *European Financial Management*로 알려져 있으나 이번 세션에서 검증하지 못함)
- **[WP] arXiv 1912.05228**
  - 비트코인에서 점프, 특히 양의 점프는 이후 실현분산을 낮췄다.
  - 점프와 부호를 나눠 모형에 넣으면 긴 시계에서는 도움이 됐지만, **1일 시계에서는 단순 HAR가 가장 좋았다.**
  - 출처: [arXiv PDF](https://arxiv.org/pdf/1912.05228v3.pdf)
- **[발표자료] HU Berlin 슬라이드(Hu Junjie, 크립토 실현변동성)** — 1일 시계 Mincer-Zarnowitz R²는 단순 HAR가 약 **0.267**, 실현 반분산(semivariance) 변형이 약 **0.285**였다. 표본외 R²와는 다른 통계량이다. — [HU Berlin PDF](https://www.wiwi.hu-berlin.de/de/forschung/irtg/lvb/members/personalpages/hujunjie/rcvj.pdf) (비동료심사, 검색 요약 기준)
- **[학위] Verschoor (Erasmus, 2022)** — 2015–2022년 비트코인에 HAR-RV-J 확장 모형을 적용했다. 음의 반분산(하락 쪽 변동성) 항을 넣자 표본 안팎 성능이 모두 좋아졌다. — [Erasmus PDF](https://thesis.eur.nl/pub/63410/Final_version_thesis_Johan_Verschoor.pdf)
- **[WP] LSTM vs HAR 워킹페이퍼** — HAR/HAR-X는 표본외에서 안정적이고 경쟁력이 있었다. LSTM은 HAR를 확실하게 이기지 못했다. — [Synapse 기록](https://synapsesocial.com/papers/W7118180075)
- **[PR] "Forecasting bitcoin volatility: Evidence from the options market"**
  - Deribit 체결가로 내재변동성(IV)을 계산했다.
  - IV 하나만으로는 ARMA·HAR보다 덜 정확했다. 하지만 **IV와 모형 예측을 결합하면 모든 시계에서 정확도가 가장 높았다.** BTC 옵션시장에 고유한 정보가 있다는 뜻이다.
  - 출처: [vLex 사본](https://law-journals-books.vlex.com/vid/forecasting-bitcoin-volatility-evidence-855595395) (Scribd 파일명 "fut-22144"로 보아 *Journal of Futures Markets* 게재로 추정 — [Scribd](https://www.scribd.com/document/572396763/fut-22144))
- **[WP] arXiv 2401.02049** — GARCH류 예측과 BTC 옵션 IV를 비교했다. 행사가가 극단적인 옵션(moneyness)에서는 유동성 제약 때문에 IV가 왜곡됐다. — [arXiv PDF](https://www.arxiv.org/pdf/2401.02049)
- **[업계] DVOL 맥락** — Deribit DVOL은 VIX와 같은 방식으로 만든 30일 내재변동성 지수다. 2026년(11월 초까지) 평균은 42.4였고, 최근 실현변동성도 비교적 안정적이었다. — [Crypto Briefing](https://cryptobriefing.com/bitcoin-options-calmest-year-deribit-dvol/)
- **[PR/WP] Yae & Tian — 크립토 수익률 표본외 예측 종합 비교**
  - 의미 있는 예측변수는 주식시장과의 상관관계 변화 하나뿐이었다. 표본외 R²는 **BTC 2.69%, ETH 1.71%, XRP 2.12%** 였다.
  - 투자자 관심, 거래량처럼 표본 안에서 유명한 예측변수는 **표본외에서 유의한 예측력이 없었다.**
  - 출처: [논문 색인](https://search.napstic.cn/literature/periodical/4dac1ab23c3a8347208b9a1cc5f2ded2)
  - 이전 WP 버전: 일간 표본외 R² 최대 2.33%(코로나 이전 3.52%). — [AUT 학회 WP PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/576990/George-Tian-NZ_2021.pdf)
- **[학위] 2026 박사논문(UDP, Sanhueza)** — 2014-09 ~ 2025-04 일별 데이터로 기술·펀더멘털·심리·거시 4계열 141개 예측변수를 검정했다. 표본 안에서 유의한 변수는 67개였지만, **표본외 예측을 개선한 변수는 29개**뿐이었다. — [UDP PDF](https://doctorados.udp.cl/cms/wp-content/uploads/2026/06/Tesis_Doctoral_Aliro_Sanhueza.pdf)
- **[PR] Bariviera (2017)** — 2011–2017년 비트코인 수익률은 2014년 이후 더 효율적이 됐다. 반면 **변동성(고가-저가 로그차)은 전 기간 장기기억을 유지했다.** — [arXiv](https://arxiv.org/abs/1709.08090)
- **[PR] Baur et al. (2019)** — 요일·시간대 수익률 효과는 지속되지 않았지만, **거래량 패턴은 지속적이었다.** — [EconPapers](https://econpapers.repec.org/RePEc:eee:finlet:v:31:y:2019:i:c:p:78-92)

### Inferences
- **대략적인 비교:** 변동성 1일 예측 R²는 약 0.25–0.3(MZ, HAR, 비동료심사 자료 1건)이고, 수익률 1일 표본외 R²는 약 0–3%다. 한 자릿수 이상 차이가 난다. 거래량의 시간대 패턴도 지속적이라 예측할 수 있다.
  - 단, 두 수치는 서로 다른 통계량이다. MZ R²는 예측값과 실제값의 상관을 보고, 표본외 R²는 기준 예측 대비 개선을 본다. 엄밀한 비교는 아니다.
- 1시간 리포트의 중심은 "오를까, 내릴까"가 아니라 **"얼마나 움직일 가능성이 큰가(변동성, 예상 범위)", "거래량이 평소와 비교해 어떤가"** 에 두는 것이 문헌과 가장 잘 맞는다. 방향 의견을 낼 때는 50%에 가까운 확률과 불확실성을 함께 적어야 한다.
- 변동성 예측은 1시간 수익률의 제곱이 아니라 **분 단위 데이터로 만든 실현변동성**으로 평가해야 공정하다(Andersen & Bollerslev). 1시간 실현변동성 기반 HAR와 DVOL 비교가 비용이 적게 드는 기준선이 된다.
- 변동성에서 방향으로 이어지는 연결(Christoffersen & Diebold)은 실제로 있지만 약하다. 게다가 일간보다 긴 시계에서 나타나므로, 1시간 방향 예측의 근거로 쓰기는 어렵다.

### Gaps
- Andersen & Bollerslev(1998)의 구체적인 R² 수치(제곱수익률 대비로는 매우 낮고 실현변동성 대비로는 훨씬 높다는 결과)는 원문 PDF 접근이 막혀 검증하지 못했다.
- 주가지수 수익률 예측의 대표적인 표본외 R²(Welch & Goyal 2008, Campbell & Thompson 2008 등)는 이번 세션에서 검색하지 않았다.
- DVOL 지수 자체가 실현변동성을 얼마나 잘 예측하는지 직접 검정한 동료심사 연구는 찾지 못했다.
- 비트코인 **1시간** 시계의 HAR R²(시간 단위 실현변동성 예측)는 찾지 못했다.
- 검색 스니펫에 "기술 지표를 결합하면 표본외 R² 최대 0.523%"라는 수치가 있었지만, 어느 논문인지 확정하지 못해 쓰지 않았다.

## 6. 비트코인 시장 효율성은 시간이 지나며 높아졌는가

### Takeaway
Urquhart(2016) 이후 여러 연구가 "초기(대략 2010–2013)에는 비효율적이었고, 2014년 이후 점점 효율적이 됐다"고 보고했다. 2017년 12월 선물 상장 뒤 추세 규칙의 예측력이 급감한 것(Shynkevich 2021)도 이를 뒷받침한다. 다만 다음과 같은 단서가 붙는다.
- 검정 방법에 따라 결론이 갈린다. 수익률을 변환하면 효율적이라는 Nadarajah & Chu와, 2010–2017년 대부분 비효율적이었다는 Kristoufek이 맞선다.
- 변동성의 장기기억은 계속 남아 있다.
- 1시간 빈도는 약형 효율적이고, 알트코인은 덜 효율적이라는 결과가 많다.

### Cited Findings
- **[PR] Urquhart (2016, *Economics Letters* 148:80–82)** "The inefficiency of Bitcoin"
  - 전체 표본에서 비트코인 수익률은 유의하게 비효율적이었다.
  - 두 하위기간으로 나누면, 후기에는 일부 검정이 효율성을 시사했다.
  - 결론: "비효율적이지만 효율적인 시장으로 이동 중일 수 있다."
  - 출처: [Reading 저장소](https://centaur.reading.ac.uk/79170); [EconPapers](https://econpapers.repec.org/RePEc:eee:ecolet:v:148:y:2016:i:c:p:80-82)
- **[PR] Nadarajah & Chu (2017, *Economics Letters* 150:6–9)** "On the inefficiency of Bitcoin" — 비트코인 수익률에 단순한 거듭제곱 변환을 하면, 8개 검정에서 효율적 시장 가설을 만족했다. — [EconPapers](https://econpapers.repec.org/RePEc:eee:ecolet:v:150:y:2017:i:c:p:6-9); [요약](https://cdecker.github.io/btcresearch/2016/nadarajah2016inefficiency.html)
- **[PR] Bariviera (2017, *Economics Letters* 161:1–4)** "The inefficiency of Bitcoin revisited: A dynamic approach"
  - 2011–2017년 허스트 지수(DFA 방식)를 분석했다.
  - 일간 수익률은 전반부에 한 방향으로 이어지는 성질(persistent)을 보였고, **2014년 이후에는 정보 효율성이 더 높아졌다.** 비효율의 주된 원인은 첫 하위기간이었다.
  - 변동성은 전 기간 장기기억을 보였다.
  - R/S 방법은 장기기억을 과다하게 잡는 경향이 있고, DFA가 더 정밀했다.
  - 출처: [arXiv](https://arxiv.org/abs/1709.08090); [EconPapers](https://econpapers.repec.org/RePEc:eee:ecolet:v:161:y:2017:i:c:p:1-4)
- **[WP] Takaishi & Adachi (2019, arXiv 1902.09253)** "Market efficiency, liquidity, and multifractality of Bitcoin: A dynamic study"
  - 2011년 이후 수익률은 백색잡음(예측할 수 없는 무작위 움직임)과 양립했다. 이는 Urquhart의 반지속성 결과와 맞지 않는다.
  - 같은 논문이 인용한 Kristoufek은 2010–2017년을 대부분 비효율적이었다고 봤다.
  - 출처: [arXiv PDF](https://arxiv.org/pdf/1902.09253v1.pdf)
- **[PR] Shynkevich (2021, *Journal of Futures Markets*)** — 선물 도입(2017.12) 전에는 유의한 예측력이 있었고, 그 뒤 추세추종 규칙의 예측력이 급감했다. 선물이 BTC 현물시장의 효율성을 높인 것으로 보인다. ETH는 개선되지 않았다. — [EconPapers](https://econpapers.repec.org/RePEc:wly:jfutmk:v:41:y:2021:i:1:p:115-134)
- **[PR] Baur et al. (2019)** — 일관된 달력 가격 패턴이 없어 약형 효율적이라고 봤다. — [EconPapers](https://econpapers.repec.org/RePEc:eee:finlet:v:31:y:2019:i:c:p:78-92)
- **[PR] "not-so-random forest" (IJF)** — 1시간 빈도에서 약형 효율적이었다. — [AMiner](https://www.aminer.org/pub/62283eb15aee126c0fdfb0d8/forecasting-bitcoin-with-technical-analysis-a-not-so-random-forest)
- **[PR] Hudson & Urquhart (2021)** — 표본외에서 BTC는 예측력이 없었고, 다른 코인은 예측력이 남았다(검색 발췌). — [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1)
- **[PR] Grobys, Ahmed & Sapkota (2020)** — 20일 이동평균 초과수익(연 8.76%)이 "비트코인을 제외한" 코인에서 보고됐다. — [IDEAS](https://ideas.repec.org/a/eee/finlet/v32y2020ics1544612319308852.html)
- **[PR] 2023 *Fractal and Fractional* 7(12):870 (MDPI)** — 검색 요약은 Cabezas-Rivas et al.(2023)이 가격의 높은 지속성(효율성 저하)과, 순수 탈중앙 코인에서 뚜렷한 비효율 징후를 발견했다고 소개했다. — [MDPI](https://mdpi.com/2504-3110/7/12/870) (이 페이지가 그 논문 자체인지, 그 논문을 인용한 다른 논문인지 불명확)

### Inferences
- "적응적 시장 가설(AMH)"이 가장 잘 들어맞는다. 수익 기회는 시장이 미성숙할 때나 특정 장세에서 나타났다가, 참여자와 상품(선물, ETF)이 늘면 줄어든다.
  - 그래서 프로젝트는 규칙 성과를 **롤링 구간으로 계속 다시 검증**해야 한다. 과거 성과, 특히 2018년 이전 성과를 현재 기대치로 쓰면 안 된다.
- BTC는 크립토 중 가장 효율적인 편이다(Grobys의 "BTC 제외 시 수익", H&U의 표본외 BTC 무예측력). 따라서 BTCUSDT에서 단순 기술적 분석으로 기대할 수 있는 초과수익은 작다.
- 수익률은 효율적으로 바뀌어 왔지만 변동성의 장기기억은 남아 있다(Bariviera). 이는 5번의 결론과 같은 방향이다. 방향보다 변동성이 예측 대상으로 더 낫다.

### Gaps
- 2024년 1월 미국 현물 ETF 승인 뒤 효율성이 어떻게 변했는지 다룬 연구는 이번 세션에서 찾지 못했다.
- 크립토 효율성 서베이 논문과, 적응적 시장 가설로 달력효과를 동적 분석한 논문([UNED 기록](https://portalcientifico.uned.es/documentos/653bfc548e0df037b36df52b?lang=eu))은 제목 수준만 확인했거나 검색하지 못했다.
- arXiv 2003.13517 등 효율성 관련 일부 검색 결과는 내용을 확인하지 못했다.
