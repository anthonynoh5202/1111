# 상용 AI 차트 분석·시그널 서비스와 독립 평가 (조사 기준일: 2026-11-07)

> 표기 규칙: **[주장]** = 회사·벤더·제휴 리뷰의 마케팅 주장(검증 안 됨). **(발췌)** = 이 세션에서는 웹페이지 원문을 직접 열 수 없어(trendspider.com·luxalgo.com·fxstreet.com 등 네트워크 차단) 검색 결과 발췌로만 확인한 내용. 날짜는 가능한 한 명시.

## 1. 주요 상용 제품: 핵심 기능, 확률·신뢰도 표시 방식, 성과 주장, 가격

### Takeaway
상용 "AI 차트 분석"은 대부분 세 층으로 되어 있다. ① 규칙/통계 기반 패턴·추세선 자동 인식, ② 과거에 같은 패턴이 성공한 비율을 "확률/신뢰도/점수"로 붙이는 방식, ③ 2025–2026년에 붙은 LLM 대화형 비서(TrendSpider Sidekick, TradingView AI Copilot, LuxAlgo Quant/Strategy Screener)다. 확률 수치는 사실상 "과거 기저율(base rate)"이거나 회사 내부 시뮬레이션이다. 가격은 월 $0~$999로 넓고, 제3자 출처끼리도 숫자가 자주 엇갈린다. AI 기능은 대개 최상위 요금제에만 들어 있다.

### Cited Findings
**TrendSpider (미국, 차팅·스캐닝)**
- 공식 도움말 설명: "Dynamic multi-factor alerts based on any combination of indicators or trend lines, with optional buffer zones and multi-timeframe capabilities". 즉 고정 가격이 아니라 추세선·지표를 기준으로 한 "동적" 알림이고, 버퍼존과 여러 조건 조합을 지원 — [TrendSpider Help Center](https://help.trendspider.com/kb/overview/introduction-to-trendspider) (발췌)
- 자동 추세선 감지(Automated Trendline Detection)는 공식 문서가 따로 있는 대표 기능 — [TrendSpider Help: Automated Trendline Detection](https://help.trendspider.com/kb/automated-technical-analysis/automated-trendline-detection)
- 멀티 타임프레임 분석: 툴바 아이콘으로 켜면 상위 타임프레임의 추세선·레벨을 하위 타임프레임 차트에 겹쳐 볼 수 있음 — [TrendSpider blog](https://trendspider.com/blog/trendspider-strategy-guide-multi-timeframe-analysis-with-trendlines/)
- 공식 LLM 정보 페이지는 ML 기능을 "ML Quant Lab"으로 소개하고, 로지스틱 회귀·랜덤 포레스트 같은 모델을 학습할 수 있다고 함. 제3자 디렉터리는 같은 기능을 "AI Strategy Lab"(코딩 없이 ML 진입 신호 모델 학습)으로 부름 — [TrendSpider llm-info](https://trendspider.com/llm-info/), [SoftwareFinder](https://softwarefinder.com/artificial-intelligence/trendspider) (발췌)
- LLM 비서 Sidekick은 모든 요금제에 월 25개 무료 메시지가 있고, 더 쓰려면 별도 유료 Sidekick 플랜이 필요 — [TrendSpider pricing](https://trendspider.com/pricing/) (발췌)
- 가격은 출처마다 다름. 한 2026년 리뷰는 최저 플랜이 할인 전 월 $82라고 하고, 다른 사이트들은 $39·$54·$89 같은 다른 숫자를 냄. 무료 등급은 없음 — [StockBrokers.com 2026](https://www.stockbrokers.com/review/tools/trendspider-vs-tradingview), [ChartingLens 2026](https://chartinglens.com/blog/is-trendspider-worth-it), [Toolradar](https://toolradar.com/tools/trendspider/pricing) (발췌, 공식 가격 페이지 원문 미확인)

**TradingView (차팅 플랫폼, 공식 AI + 커뮤니티 ML 스크립트)**
- 2026-03-26: 미국 기업 공시(10-K, 10-Q, 8-K, Form 4, 13D, S-1, 실적 콜 녹취록, IR 자료) AI 요약 기능 출시 — [TradersPost blog](https://blog.traderspost.io/article/tradingview-ai-features-chart-copilot-documents-news)
- 2026-04-02(대부분 출처 기준, 한 출처는 2026-03): "AI Chart Copilot" 공개 베타 출시. 브라우저 사이드패널 확장 프로그램 형태로 차트 분석·알림 설정·뉴스 요약·아이디어 스캔을 하며, 전략을 만들거나 실행하지는 않고 분석에 집중. TradingView는 베타 피드백을 반영해 "TradingView AI"를 모든 브라우저와 데스크톱 앱 사이드패널에 기본 탑재하는 쪽으로 작업 중이라고 밝힘 — [FX News Group](https://fxnewsgroup.com/forex-news/platforms/tradingview-introduces-ai-chart-copilot), [TradersPost review](https://blog.traderspost.io/article/tradingview-ai-chart-copilot-review-guide)
- 리뷰들: 무료 베타는 하루 15회 AI 요청 한도. Pine Script를 믿을 만하게 만들지 못하고 매매도 실행하지 않음. 확장 프로그램 이름은 "TradingView Remix: AI Chart Copilot"이고 게시자는 제3자 개발 도메인 tvremix.xyz라는 지적이 있음(공식 블로그가 홍보) — [TradersPost review](https://blog.traderspost.io/article/tradingview-ai-chart-copilot-review-guide), [TradersPost: Remix extension](https://blog.traderspost.io/article/tradingview-remix-extension)
- 2026-10-20 보도자료 제목: "TradingView launches AI Copilot, an AI assistant that works directly on your charts" — [FXStreet press release](https://www.fxstreet.com/press-releases/tradingview-launches-ai-copilot-an-ai-assistant-that-works-directly-on-your-charts-202610201208) (본문 직접 확인 못 함)
- 일본어 가이드(2026-10-01)는 유료 플랜 가입자만 쓰는 월정액 애드온이고, 월 사용량은 이월되지 않으며, 무료 계정에는 제공하지 않는다고 설명. 공식 자료로 확인하지 못함 — [SmartScope](https://smartscope.blog/blog/tradingview-ai-copilot-monthly-usage-limit-2026/)
- 2026-09: MCP 서버 공개 베타. TradingView 계정을 ChatGPT·Claude 같은 AI 비서에 연결 — [Finance Magnates](https://www.financemagnates.com/forex/tradingview-adds-mcp-as-retail-brokers-adopt-ai-trading-tools/), [Crypto Briefing](https://cryptobriefing.com/tradingview-mcp-server-ai-agents-beta/)
- 커뮤니티 ML 스크립트의 대표 사례는 jdehorty의 "Machine Learning: Lorentzian Classification" — [TradingView script](https://my.tradingview.com/script/WhBzgfDu-Machine-Learning-Lorentzian-Classification/)
- 파생 스크립트 "Lorentzian KNN Classifier (Update) v2.0"의 작성자는 이전 버전에 repainting(나중에 과거 신호가 바뀌는 현상) 문제가 있어 백테스트 결과가 부풀려졌다고 스스로 밝힘 — [TradingView script](https://cn.tradingview.com/script/6zaUr2Cy-Machine-Learning-Lorentzian-KNN-Classifier-Update)
- EDUVEST 파생판은 기본 설정에서 repainting될 수 있고, 설정에서 비(非)repainting 평활화를 고를 수 있다고 명시 — [TradingView kernel-regression scripts](https://il.tradingview.com/scripts/kernel-regression)
- 상충 정보: ChartingLens 리뷰(2026-05 갱신)는 "TradingView에는 AI 트레이딩 기능이 전혀 없다"고 씀. 위 2026년 출시 내용과 맞지 않아 낡은 정보로 판단 — [ChartingLens](https://chartinglens.com/blog/tradingview-review-top-alternatives)

**LuxAlgo (TradingView용 유료 지표 + AI 백테스트)**
- 요금제(LuxAlgo 자사 블로그 기준): Free $0, Premium 월 $39.99, Ultimate 월 $59.99(AI Backtesting 포함) — [LuxAlgo blog](https://luxalgo.com/blog/best-ai-tools-trading-strategy-development/), [LuxAlgo blog breakdown](https://www.luxalgo.com/blog/luxalgo-backtesting-ai-chat-complete-breakdown/)
- 가격 페이지: 월간·연간 결제, 모든 요금제 30일 환불 보장, 지역별 가격과 프로모션은 결제 화면에 표시 — [LuxAlgo pricing.md](https://www.luxalgo.com/pricing.md) (발췌)
- AI Backtesting Assistant는 Ultimate 전용. "a variety of state of the arts large language models"로 LuxAlgo 툴킷 기반 전략을 찾아주며, "over 10 million trading strategies"의 백테스트 결과에 접근한다고 함 **[주장]** — [LuxAlgo docs](https://docs.luxalgo.com/docs/backtesting-assistant/introduction)
- 현재 문서: "Strategy Screener, previously called the AI Backtesting Assistant, sits beside Quant, our coding agent". 옛 자료에서는 두 이름이 섞여 나옴 — [LuxAlgo docs](https://docs.luxalgo.com/platform/ai-backtesting/introduction)
- Signals & Overlays: 추세 확인형(Confirmation)과 역추세형(Contrarian) 신호를 나누고 "Signals Sensitivity"로 조절. 기본값 12이며 5–10은 단기, 20 이상은 장기 추세용 — [LuxAlgo docs: signal settings](https://docs.luxalgo.com/docs/algos/signals-overlays/signal-settings), [LuxAlgo library](https://www.luxalgo.com/library/indicator/luxalgo-signals-overlays/)
- "Optimal Sensitivity" 대시보드는 최근 250봉 동안 민감도 10~20을 grid search로 모두 백테스트해 고름. "Autopilot" 민감도를 켜면 수동 민감도 설정이 무시됨 — [LuxAlgo docs: signal settings](https://docs.luxalgo.com/docs/algos/signals-overlays/signal-settings)

**Tickeron (AI 패턴 검색, 신뢰도 표시)**
- Pattern Search Engine은 일봉 마감 데이터에서 차트 패턴을 찾아 돌파 가격·목표 가격·신뢰도(confidence level)·과거 통계를 제공. 보도자료 기준 14일 무료 체험 뒤 월 $30(날짜 미확인) **[주장]** — [Barchart(보도자료)](https://www.barchart.com/story/news/21027766/tickeron-unlocks-hidden-market-insights-with-ai-stock-pattern-search-engine)
- 외환 분석 도구를 "pre-calculated odds of success"(미리 계산된 성공 확률)로 홍보 **[주장]** — [PR Newswire](https://prnewswire.com/news-releases/tickeron-introduces-ai-powered-forex-trading-analysis-tool-with-pre-calculated-odds-of-success-301077575.html)
- 장중(intraday) 패턴 피드와 추세 예측 엔진 출시 — [Hedgeweek](https://www.hedgeweek.com/tickeron-launches-ai-powered-intraday-pattern-feed-and-trend-prediction-engine/)
- 리뷰들의 설명: 신뢰도는 종목의 과거 이력, 그 패턴의 성공률, 현재 시장 방향으로 정함. 신뢰도로 정렬·필터할 수 있고, 조건을 좁힐수록 신호 수가 줄어듦. 종목별 과거 예측과 그 결과를 볼 수 있음. 다만 모든 패턴에 걸쳐 최고 신뢰도만 한 번에 보는 기능은 없고 패턴부터 골라야 함 — [Liberated Stock Trader](https://www.liberatedstocktrader.com/tickeron-review/), [DayTradeReview](https://daytradereview.com/tickeron-review) (발췌)
- TradingView에 올라온 Tickeron 신호 게시물들은 신뢰도를 68~75% 같은 숫자로 보여줌(예시일 뿐, 성과 데이터 아님) — [TradingView 게시물](https://www.tradingview.com/u/AlTorress/page-4/)

**Trade Ideas – Holly AI (미국 주식 데이트레이딩)**
- 가장 많이 인용되는 "68% 승률"은 Trade Ideas 내부 시뮬레이션 방식에서 나왔고 독립 감사를 받지 않았으며, 전체 Holly 신호가 아니라 최고 신뢰도의 특정 셋업에만 해당함. "실사용자는 슬리피지 뒤 45~55%"라는 말도 있으나 검증할 수 없음 **[주장/미검증]** — [AlphaSignal(제휴성 리뷰)](https://alphasignal-56o.pages.dev/blog/trade-ideas-holly-ai-review/)
- 리뷰 사이트 기준 가격: Standard 월 $167(연간 결제 시 월 $118), Premium 월 $254(연간 결제 시 월 $180), Holly는 Premium 전용. 다른 리뷰는 월 $89~254 범위로 적음 — [Liberated Stock Trader](https://www.liberatedstocktrader.com/trade-ideas-review/), [PropFirmApp](https://propfirmapp.com/trading-tools/trade-ideas) (발췌, 공식 미확인)

**Autochartist (브로커 번들형 패턴 인식 + 변동성 + 리스크 계산기)**
- CMC Markets·IG·Pepperstone 같은 브로커가 MT4 등 자사 플랫폼 부가 기능으로 제공 — [CMC Markets](https://www.cmcmarkets.com/en-gb/trading-platforms/metatrader-4/autochartist), [IG](https://www.ig.com/en/trading-strategies/what-is-autochartist-and-how-do-you-use-it-when-trading--190529), [Pepperstone](https://pepperstone.com/en/learn-to-trade/trading-guides/risk-management-with-autochartist/)
- 찾는 패턴: 삼각형(상승·하락·대칭), 채널, 직사각형, 피보나치 되돌림·확장, ABCD, Gartley, Butterfly. 각 패턴에 "형성 중(emerging)/완성(completed)", "지속형/반전형" 라벨을 붙임. "매달 수천 개 트레이드 아이디어" **[주장]** — [CMC Markets](https://www.cmcmarkets.com/en-gb/trading-platforms/metatrader-4/autochartist)
- 확률 표시: 사용자가 최소 성공 확률을 60~80% 사이에서 5% 단위로 골라 필터. 확률은 패턴 유형·종목·하루 중 시간대별 과거 성과로 평가. 예상 가격 범위에 도달할 확률을 항상 표시. 품질(Quality)·균일성(uniformity)·명확성(clarity) 등급을 1~10으로 표시 — [Engineer the Forex(제3자 설명)](https://sites.google.com/view/engineer-the-forex/autochartist)
- IG 설명: 자동으로 주문을 내지 않으며 "not foolproof"(완벽하지 않음) — [IG](https://www.ig.com/en/trading-strategies/what-is-autochartist-and-how-do-you-use-it-when-trading--190529)
- Volatility Analysis: 주식·크립토·외환의 다음 1시간·4시간·24시간 예상 거래 범위를 보여줌. 표준편차 기반이며 1σ 범위 안에 있을 확률을 68%로 명시. 요일별·시간대별 예상 변동성도 제공 — [Autochartist Help](https://help.autochartist.com/article/an-introduction-to-volatility-analysis/), [Autochartist Support](https://support.autochartist.com/en/knowledgebase/article/volatility-analysis)
- "6개월 데이터 기반, 예측 정확도 최소 68%" **[벤더성 주장]** — [IFC Markets](https://www.ifcmarkets.co.za/introduction/volatility-analysis)
- Risk Calculator: 위험 허용도와 손절 가격으로 포지션 크기를 계산. "Show Expected Trading Ranges"를 체크하면 변동성 예상 범위를 같이 그려줌 — [Autochartist Risk Calculator 사용 설명서(HotForex 호스팅)](https://static.hotforex.com/assets/common/documents/manuals/Autochartist_Risk_Calculator_User_Guide-SV.pdf). 종목 변동성, 계좌 자본, 거래당 위험 %를 함께 고려 — [Pepperstone](https://pepperstone.com/en/learn-to-trade/trading-guides/risk-management-with-autochartist/)

**Kavout (주식 AI 점수, Kai Score)**
- Kai Score는 1~9점이며 높을수록 앞으로 시장보다 잘할 가능성이 크다는 뜻 — [Kavout](https://www.kavout.com/market-lens/kavout-releases-k-score-for-united-kingdom-and-germany-stock-markets)
- 재무(펀더멘털)·기술적·대체 데이터를 합쳐 계산 — [Kavout](https://www.kavout.com/market-lens/leveraging-alternative-sources-for-stock-picking-kai-score)
- 2025-02: Pro 회원이 자연어로 종목 검색 조건을 만들 수 있음(예: "P/E 20 미만 대형주 중 Kai Score 7 초과") — [Kavout](https://www.kavout.com/market-lens/kai-score-is-here-create-ai-stock-picks-your-way)
- 6.0~9.0 구간에 "Outperform: Beat the market, bullish signal" 라벨 — [Kavout Academy](https://www.kavout.com/academy/ai-stock-picker)
- 상충: Walnut Invest 비교 페이지는 "Kavout은 Kai Score를 내지 않는다"고 씀(Kavout 자료와 반대라 신뢰도 낮음) — [Walnut Invest](https://walnutinvest.com/resources/kavout-alternatives)

**CryptoQuant (온체인 데이터 + 알림)**
- 공식 사이트: 어떤 지표에든 기본 제공(프리셋) 알림이나 사용자 정의 알림을 걸 수 있고, 이메일이나 텔레그램으로 받음 — [CryptoQuant](https://cryptoquant.com)
- 요금제별 알림 개수: Basic 1개, Advanced 5개, Professional 20개, Premium 100개 — [TheGodFunded](https://thegodfunded.com/en/tools/cryptoquant/)
- 가격은 출처끼리 다름. CostBench: Advanced 월 $29, Professional $99, Premium $799이고 2026-08 기준 무료 플랜 없음. TheGodFunded: Advanced 월 $39(연간 결제 시 $29), Pro $109/$99, Premium $799/$699이고 무료 Basic 있음 — [CostBench](https://www.costbench.com/software/onchain-analytics/cryptoquant/), [CostBench free plan](https://www.costbench.com/software/onchain-analytics/cryptoquant/free-plan/), [TheGodFunded](https://thegodfunded.com/en/tools/cryptoquant/)

**Glassnode (온체인 분석 + 알림)**
- 2026-06에 Advanced가 $39에서 $49로 올랐고 무료 Studio Standard 등급이 없어짐 — [CostBench changelog](https://costbench.com/changelog/glassnode-plan-removed-2026-06/), [ComparEdge](https://comparedge.com/tools/glassnode/pricing)
- 집계 사이트 기준: Advanced는 연간 결제 시 월 $49, 월 결제 시 $99. Professional은 월 $999 — [ComparEdge](https://comparedge.com/tools/glassnode/pricing), [CostBench](https://www.costbench.com/software/onchain-analytics/glassnode/)
- "실시간 알림은 Professional 전용"이라는 주장은 한 곳에서만 나옴. 알림 개수(5/10/20개)도 출처마다 다름 — [CostBench hidden costs](https://costbench.com/software/onchain-analytics/glassnode/hidden-costs/). 공식 알림 페이지 내용은 확인 못 함 — [Glassnode Studio Alerts](https://studio.glassnode.com/alerts)

**CoinGlass (파생상품·청산 데이터)**
- Prime 요금제: 월 $28, 연간 결제 시 20% 할인, 환불 불가. 청산 히트맵 Model 1/2/3 전체를 쓸 수 있음 — [CoinGlass Prime](https://www.coinglass.com/prime)
- 무료 등급으로도 사이트 대부분을 쓸 수 있지만 히트맵 이력은 제한됨. Prime은 최대 24개월 히트맵과 자동 새로고침을 줌. 분기 결제는 $78 — [TheGodFunded](https://thegodfunded.com/en/tools/coinglass/)
- API에 청산 히트맵 엔드포인트가 있음 — [CoinGlass API docs](https://docs.coinglass.com/reference/liquidation-heatmap-copy). "무료~월 $699"라는 가격 범위(API 등급으로 보임) — [ComparEdge](https://comparedge.com/tools/coinglass)

**3Commas / Cryptohopper (봇 플랫폼의 "AI 시그널")**
- 품질 낮은 비교 블로그 기준: 3Commas는 자체 AI 모델 없이 외부 신호·TradingView 연동 중심이고 연간 결제 시 월 $16부터. Cryptohopper는 전략 마켓플레이스와 AI 전략 디자이너 중심이고, AI 기능은 상위 Hero 요금제(월 $129)에 있음. 무료 Pioneer 등급이 나오는 목록도 있음 — [AI Trading Ranked](https://ai-trading-ranked.pages.dev/posts/cryptohopper-vs-3commas), [HackerNoon](https://hackernoon.com/top-10-best-ai-bot-trading-in-2026-features-and-pricing), [DEV Community](https://dev.to/suhadolsky/3commas-review-2026-is-it-worth-it-1m15) (발췌, 공식 미확인)

**스크린샷을 올리면 GPT류가 분석해 주는 앱**
- 앱스토어에 "Chart AI", "Chart AI Trading Analyzer", "Chartify: AI Chart Analysis", "ChartDetector AI", "Trade AI: Chart AI Analysis" 같은 앱이 많음 — [App Store: Chart AI](https://apps.apple.com/us/app/chart-ai/id6636484876), [App Store: Chart AI Trading Analyzer](https://apps.apple.com/app/id6752585541), [AppFollow: Chartify](https://apps.appfollow.io/ios/chartify-ai-chart-analysis/6739358464?country=mx), [AppFollow: ChartDetector AI](https://apps.appfollow.io/ios/chartdetector-ai/6743856402?country=us), [AppFollow: Trade AI](https://apps.appfollow.io/ios/trade-ai-chart-ai-analysis/6741457696?country=in)
- 스토어 설명은 매매 등급, 진입·청산 가격, 손절, 목표가, "accurate, instant" 인사이트를 내세우지만 정확도 데이터는 없음. 한 트레이딩 가이드는 이런 앱에 대해 "they do not give us a measured error rate for any trading app"라고 하고, 이미지 해석은 "review aid"(검토 보조)일 뿐이라고 함 — [OneTradeJournal](https://onetradejournal.com/ai-trading/ai-chart-analysis) (발췌)
- 한국어 앱 "크립토 차트 AI": 데이터베이스에서 과거의 비슷한 차트 패턴을 찾아 그 뒤에 가격이 어떻게 움직였는지 그림으로 비교해 줌(확률 수치 언급 없음) — [App Store: 크립토 차트 AI](https://apps.apple.com/us/app/%ED%81%AC%EB%A6%BD%ED%86%A0-%EC%B0%A8%ED%8A%B8-ai/id6741916884?l=ko)

### Inferences
- 상용 도구의 "확률/신뢰도"는 거의 다 **조건부 과거 빈도**다(Autochartist: 패턴 유형·종목·시간대별 과거 성과 / Tickeron: 종목 이력·패턴 성공률·시장 방향). 앞날을 맞힌 실적(검증된 예측력)이 아니다. 표본 수(n), 기간, 표본 밖 검증(out-of-sample) 여부를 함께 보여준 사례는 찾지 못했다.
- LLM 비서(TradingView Copilot, TrendSpider Sidekick, LuxAlgo Quant)는 "분석·검색 보조" 역할이고 주문은 내지 않는다. 메시지 수 한도를 두고 상위 요금제로 유도하는 구조다(Sidekick 월 25개, Copilot 베타 하루 15회).
- AI 기능을 최상위 요금제에 묶는 경향이 뚜렷하다(LuxAlgo Ultimate, Trade Ideas Premium, Cryptohopper Hero). 개인용 BTCUSDT 도구라면 데이터 API(CoinGlass 청산 히트맵 API 등)와 자체 규칙, 그리고 API 키 방식 LLM 설명만으로 비슷한 표현을 만들 수 있다.
- 크립토 전용 도구(CryptoQuant·Glassnode·CoinGlass)는 "AI 예측"보다 **데이터와 알림**을 판다. 이 프로젝트에는 예측 엔진보다 입력 데이터원으로서 가치가 크다.
- TradingView MCP나 거래소의 AI 연결 기능은 소비자용 AI 앱과 계정을 잇는 구조다. 프로젝트 원칙("구독 앱 자동화 금지, API 키 또는 사람이 직접 붙여넣기만")에 비춰 보면 자동 리포트에는 쓰지 말고 API 키 방식을 유지해야 한다.

### Gaps
- 이 세션에서는 trendspider.com, luxalgo.com, fxstreet.com 원문을 네트워크 제한 때문에 열지 못했다. 가격과 기능 문구는 검색 결과 발췌와 제3자 집계 사이트에 의존한다. TrendSpider·Trade Ideas·Tickeron(현재가)·Glassnode·CryptoQuant·3Commas·Cryptohopper의 2026-11 공식 가격은 확인하지 못했다.
- Kavout의 가격과 크립토 지원 여부, Autochartist의 개인 직접 구매 가격, 확률 계산의 통계 방법(공개 자료 없음)을 찾지 못했다.
- TradingView AI Copilot의 공식 요금·약관(2026-10 정식 출시 뒤 유료 애드온인지)은 1차 자료로 확인하지 못했다.
- Tickeron "39개 패턴" 같은 세부 수치는 출처를 특정할 수 없어 뺐다.

## 2. 독립 평가: 정확도·유용성에 대한 리뷰·감사·학술/언론 테스트

### Takeaway
제품별 성과 수치(Holly 68%, Autochartist "68% 정확도", Tickeron 신뢰도, LuxAlgo "1천만 개 전략")를 독립적으로 감사하거나 학술적으로 검증한 자료는 찾지 못했다. 대신 일반적인 근거는 회의적이다. 실제 돈을 건 LLM 크립토 매매 대회에서 6개 모델 중 4개가 손실을 냈고(GPT-5 −62.7%), 멀티모달 LLM의 차트 판독 오류율은 높으며, 인플루언서 매수 추천 뒤의 수익률은 며칠 안에 반전된다.

### Cited Findings
- **Alpha Arena 시즌 1 (nof1.ai, 2025-10-18 ~ 11-03/04, Hyperliquid 실거래, 모델당 $10,000):** Qwen3-Max가 +22.32%(잔고 $12,232)로 1위, DeepSeek가 $10,489로 2위. 나머지 4개(Claude Sonnet 4.5, Gemini 2.5 Pro, Grok 4, GPT-5)는 손실이었고 GPT-5는 −62.7%로 최하위 — [GNcrypto](https://www.gncrypto.news/news/qwen-wins-alpha-arena-season-1-with-22-percent-returns/), [Forklog](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/), [Benzinga](https://benzinga.com/crypto/cryptocurrency/25/11/48651974/chatgpt-lost-63-trying-to-trade-crypto-but-one-china-ai-made-a-healthy-profit)
- nof1 스스로도 짧은 기간, 적은 자본, 통계적 통제 부재 때문에 이 결과를 AI 매매 능력의 확정 순위로 보면 안 된다고 밝힘 — [GNcrypto](https://www.gncrypto.news/news/qwen-wins-alpha-arena-season-1-with-22-percent-returns/), [Forklog](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/)
- 시즌 중간 보도는 Grok·DeepSeek·Claude가 앞서고 Gemini·GPT-5가 무너진다고 전했지만 최종 결과와 달랐음(단기 순위가 불안정하다는 뜻) — [Decrypt](https://decrypt.co/345006/ai-crypto-trading-showdown-deepseek-grok-winning-gemini-implodes)
- 시즌 1.5는 이름을 숨긴 모델(Grok 4.2로 보도)이 우승. 같은 프롬프트에서 Qwen은 1,418건, 1위 Grok 4.20은 158건을 주문함. 창업자 Jay Azhang은 LLM에 돈을 맡겨 혼자 매매하게 하는 것은 아직 현실적이지 않다고 말함 — [Forklog](https://forklog.com/en/ai-model-grok-4-2-triumphs-in-trading-tournament/amp)
- **멀티모달 LLM의 차트 읽기 정확도:**
  - Chat BCG (arXiv 2407.12875, 2024-07): GPT-4o와 Gemini Flash 1.5는 여러 그림이 겹친 차트, 누적 차트, 워터폴 차트에서 늘 부정확했다. 숫자 라벨이 없는 차트에서는 오류율이 GPT-4o 최대 83%, Gemini 79% — [arXiv](https://arxiv.org/html/2407.12875v1)
  - arXiv 2405.07001 (2024-05): 저수준 차트 과제에서 GPT-4V 정확도 56.13%. 관련 요소를 강조하는 시각 프롬프트를 주면 83.83% — [arXiv](https://arxiv.org/html/2405.07001v1)
  - arXiv 2510.06782 (2025-10): CHART-6 재실험에서 GPT-5가 GPT-4o보다 평균 20~40%p 높았다. 프롬프트를 바꿔도 효과는 거의 없었음 — [arXiv](https://arxiv.org/abs/2510.06782v1)
  - arXiv 2412.04041 (2024-12): 엘리엇 파동이 표시된 주가 차트로 차트 설명(캡셔닝) 데이터셋을 만들고 범용 비전-언어 모델을 시험 — [arXiv](https://arxiv.org/pdf/2412.04041v1)
- 스크린샷 분석 앱은 측정된 오류율이 없다 — [OneTradeJournal](https://onetradejournal.com/ai-trading/ai-chart-analysis)
- **크립토 인플루언서 연구** (인플루언서 180명, 트윗 약 36,000건, 1,600개 넘는 자산, 2022-12까지 2년간): 트윗 뒤 5일째부터 수익률이 크게 떨어져 10일 누적 −2.24%, 30일 누적 −6.53%. 긍정적 어조와 매수 추천, 팔로워가 많은 자칭 전문가일수록 반전이 강함. 펌프앤덤프와 맞아떨어지는 패턴 — [ProMarket 2023-04-17](https://www.promarket.org/2023/04/17/crypto-influencers-give-poor-investment-advice-and-the-sec-is-taking-notice/), [IU Kelley blog](https://blog.kelley.iu.edu/?p=4898)
- YouTube 크립토 인플루언서 연구(Finance Research Letters): 소형 토큰에만 짧은 효과가 있고, 가격과 거래량이 3일 안에 원래대로 돌아감 — [Phys.org 2023-03](https://phys.org/news/2023-03-youtube-crypto-shown-short-term-impact.pdf)
- arXiv 2411.05577 (2024-11): LLM으로 인플루언서·뉴스 글에서 "매수/비매수" 신호를 뽑았더니 코인과 기간마다 결과가 섞여 나옴. 상위 3개 코인에서만 직전 24시간 신호 합계가 수익률을 예측함 — [arXiv](https://www.arxiv.org/pdf/2411.05577)
- Trade Ideas의 68%는 내부 시뮬레이션이고 독립 감사가 없음 — [AlphaSignal](https://alphasignal-56o.pages.dev/blog/trade-ideas-holly-ai-review/)
- 회의적인 Tickeron 리뷰들의 결론: Pattern Search 등은 리서치를 정리하는 데는 도움이 될 수 있지만 신호 에이전트는 따로 검증해야 함 — [DayTradingToolkit](https://daytradingtoolkit.com/reviews/tickeron-review), [WalletInvestor](https://walletinvestor.com/news/finance-news/tickeron-review-are-pre-built-ai-trading-bots-reliable-for-pattern-recognition/)

### Inferences
- Autochartist의 "68% 정확도"는 1σ 범위의 통계적 정의(정규분포라면 약 68%가 범위 안)와 같은 숫자다. 예측 실력의 증거라기보다 **변동 범위를 정직하게 표현하는 방법**으로 보는 게 맞다.
- Alpha Arena에서 같은 프롬프트로도 주문 수가 9배 차이 난 것은 LLM을 매매 판단의 주체로 쓰면 결과가 불안정하다는 뜻이다. 이 프로젝트처럼 **판단은 고정 규칙, LLM은 설명만** 맡기는 설계가 더 안전하다는 간접 근거다.
- 라벨 없는 차트 판독 오류율이 높다는 결과(Chat BCG)를 보면, LLM에 차트 이미지를 주고 숫자를 읽게 하지 말고 OHLCV·지표값·레벨을 **텍스트 숫자로** 주는 편이 정확하다. 이미지를 쓰더라도 주요 레벨에 숫자 라벨을 붙여야 한다.
- 검색 상위의 "리뷰"는 상당수가 제휴 링크형 사이트(AlphaSignal류 등)다. 독립 근거로 쓰기 어렵다.

### Gaps
- Holly AI 68%, Tickeron 신뢰도, TrendSpider 패턴 인식, LuxAlgo 신호, Autochartist 확률에 대한 독립 감사·학술 검증·보정(calibration) 분석은 찾지 못했다. Investopedia·Benzinga·Finder 리뷰 본문도 읽지 못했다(예: [Benzinga TrendSpider review](https://benzinga.com/money/trendspider-review) URL만 확인).
- 차트 스크린샷으로 기술적 분석을 해서 실제 수익률을 따진 학술 연구는 찾지 못했다(일반 차트 읽기 벤치마크뿐).
- Alpha Arena 시즌 2 결과와 공식(nof1.ai) 원문은 확인하지 못했다.

## 3. 유료 크립토 시그널방(텔레그램·디스코드): 성과 연구, 펌프앤덤프·사기 패턴, 규제 경고

### Takeaway
펌프앤덤프가 아닌 일반 유료 시그널방이 평균적으로 돈을 번다는 독립 연구는 찾지 못했다. 공개된 "승률"은 모두 자기 신고다. 반면 텔레그램·디스코드 펌프앤덤프는 수천 건 규모로 학술 기록이 있고, 늦게 들어온 참여자가 손해를 본다. 미국(CFTC·SEC·FTC), 영국(FCA), 한국(금감원) 모두 "AI"나 "고수익 보장"을 앞세운 신호·봇·리딩방을 경고하거나 제재하고 있다. 2025년 크립토 사기에서는 AI를 쓴 사칭형이 급증했다.

### Cited Findings
- **Xu & Livshits, USENIX Security 2019:** 2018-06-17~2019-02-26 텔레그램 채널에서 조직된 펌프앤덤프 412건을 분석. 약 100개 채널이 하루 평균 2번 펌프를 일으켜 월 약 600만 달러의 인위적 거래량을 만듦. 펌프 전에 비정상 매수가 있었음(내부자 선매집과 맞아떨어짐). 펌프 대상 코인을 높은 정확도로 예측하는 모델을 만듦 — [arXiv 1811.10109](https://arxiv.org/abs/1811.10109), [USENIX](https://usenix.org/conference/usenixsecurity19/presentation/xu-jiahua)
- 언론 보도: 예측 정확도 약 80%. 펌프 시작 18초 뒤에 들어온 사람은 수익을 낼 가망이 거의 없었음 — [MIT Technology Review 2018](https://www.technologyreview.com/s/612496/machine-learning-identifies-cryptocurrency-scams-before-they-happen/), [TNW 2018-12-05](https://thenextweb.com/news/ai-pump-dump-predictor-telegram)
- **Hamrick 외, Information Processing & Management 2021 (2018년 약 6개월 데이터):** 저널판은 디스코드 952건·텔레그램 2,469건, 워킹페이퍼판은 디스코드 1,051건·텔레그램 3,767건. 활동이 소수 채널과 거래소에 몰려 있음. 신호는 "Pump"라고 대놓고 쓰는 Obvious형과 그 말 없이 목표가만 주는 Target형이 있고, Target형 비율은 텔레그램 88%, 디스코드 42%. 상위 75개 코인 펌프의 가격 상승 중앙값은 디스코드 3.5%, 텔레그램 4.8%이고 시가총액이 작을수록 더 큼. 수익성은 시간이 갈수록 크게 떨어짐 — [UCL Discovery PDF](https://discovery.ucl.ac.uk/10133232/1/SSRN-id3303365%20%281%29.pdf), [Gandal 발표자료](https://bfi.uchicago.edu/wp-content/uploads/4_Neil-Gandal_pump-and-dump-presentation-nov-21.pdf), [The Block](https://www.theblock.co/amp/linked/5667/university-researchers-identified-over-4800-pump-and-dump-schemes-involving-crypto-over-a-six-month-period)
- 펌프가 아닌 시그널방 성과에 대한 학술 자료로는 신호 제공자 평가 방법을 제안한 아일랜드 NCI 석사 프로젝트 정도만 있음(동료 심사 논문 아님) — [NCI](https://norma.ncirl.ie/8791/1/mohiburrehman.pdf)
- 벤더 주장의 예: "verified win rates 65%~97%"(검증 방법 공개 안 함) **[주장]** — [Flexe](https://flexe.io/blog/trading-signals-telegram-crypto-verified-2025/). 70개 넘는 채널의 콜 8,000건 이상을 추적했다는 평가 글(공개된 결과 범위는 불분명) — [Coincub](https://coincub.com/blog/best-crypto-signals-telegram-channels-2026/). "텔레그램 시그널방 83%가 사기"라는 주장(글쓴이가 자기 신호를 판매) — [DEV/TrendRider](https://dev.to/trendrider/crypto-trading-signals-telegram-2026-scam-or-legit-51ag)
- **CFTC 고객 권고 "AI Won't Turn Trading Bots into Money Machines" (2024-01-25, Release 8854-24):** 사기꾼들이 AI에 대한 관심을 이용해 자동매매 알고리즘, "trade signal strategies", 크립토 차익거래를 홍보하고 비현실적인 수익을 약속한다. AI는 미래를 예측할 수 없다. 투자 전 업체·트레이더 이력을 확인하라. Mirror Trading International 사례를 듦 — [CFTC advisory](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html), [CFTC press release](https://www.cftc.gov/PressRoom/PressReleases/8854-24)
- 관련 보도(어느 기사인지는 검색 발췌상 불확실): AI 트레이딩 봇에 대한 거짓 주장으로 외환 사기를 벌인 남아공 CEO에게 34억 달러가 넘는 지급 명령 — [CoinMarketCap Academy](https://coinmarketcap.com/academy/article/beware-of-ai-crypto-trading-bot-scams-cftc-warns)
- **SEC 첫 "AI washing" 제재 (2024-03-18):** 투자자문사 Delphia(벌금 $225,000)와 Global Predictions($175,000), 합계 $400,000. Delphia는 2019~2023년 공시·보도자료·웹사이트에서 없는 AI·ML 능력을 있다고 주장. Global Predictions는 "first regulated AI financial advisor", "AI-driven forecasts"를 내세움 — [SEC 2024-36](https://www.sec.gov/newsroom/press-releases/2024-36)
- **FTC Operation AI Comply (2024-09-25 발표):** AI로 기만 행위를 키우는 업체를 일제 단속. Ascend Ecom은 AI 도구로 온라인 상점에서 빨리 돈을 벌 수 있다고 거짓 홍보. Passive Scaling/FBA Machine은 수익 과장으로 소비자에게 1,590만 달러가 넘는 피해를 줌 — [Skadden](https://www.skadden.com/insights/publications/2024/10/new-ftc-initiative-targets-deceptive-ai-claims-and-a-generative-ai-service), [Akin](https://www.akingump.com/en/insights/ai-law-and-regulation-tracker/ftc-announces-five-cases-involving-deceptive-ai-practices). 1년 뒤에도 새 행정부 아래에서 계속되고 있음 — [Mondaq](https://www.mondaq.com/unitedstates/new-technology/1695094/one-year-in-ftcs-operation-ai-comply-continues-under-new-administration-signaling-enduring-enforcement-focus)
- **영국 FCA 핀플루언서 단속:** 2025-06 6개국 9개 규제기관 국제 공조. 핀플루언서 3명(Charles Hunter, Kayan Kalipha, Luke Desmaris)이 FSMA 2000 s21(1) 위반(무허가 투자 권유)으로 기소됐고 모두 무죄를 주장, 2025-10-08 Southwark Crown Court 출석 예정 — [FCA press release](https://www.fca.org.uk/news/press-releases/first-court-appearance-three-finfluencers-charged-fca-led-global-crackdown-illegal-promotions), [Lewis Silkin 2025-09-17](https://www.lewissilkin.com/en/insights/2025/09/17/first-court-appearance-for-three-finfluencers-charged-in-fca-led-global-crackdo-102l58q)
- 2026-04-20부터 약 17개 규제기관이 참여한 2차 "week of action"을 벌였고, SNS 플랫폼에 적극적인 차단을 요구 — [Pulse](https://www.pulse.bot/legal/news/fca-continues-illegal-finfluencer-crackdown-b25fa1e5-84b3-48f0-8361-1871e1621f5c/). 정보공개 청구 결과 2025년 핀플루언서 대상 조치 74건(전년 27건, +174%). 단, 전년 기준값을 다르게 보도한 곳도 있음 — [Professional Adviser](https://www.professionaladviser.com/news/4525398/fca-finfluencer-enforcement-action-increases-174-2025)
- **Chainalysis 2026 Crypto Crime Report (2025년 데이터):** 사칭 사기 건수 전년 대비 약 +1,400%, 건당 평균 피해액 +600% 이상. AI를 쓴 사기가 안 쓴 사기보다 4.5배 수익성이 높음 — [Cointelegraph](https://cointelegraph.com/news/crypto-scams-2025-ai-impersonation-fraud-chainalysis). 확인된 온체인 사기 피해 약 140억 달러, 오프체인까지 합치면 170억 달러 이상으로 추정 — [Forklog](https://forklog.com/en/crypto-scammers-stole-a-record-14bn-in-2025/), [TechRepublic](https://techrepublic.com/article/news-2025-crypto-scam-losses)

### Inferences
- 펌프 연구의 "18초" 결과와 인플루언서 연구의 5일 반전 결과는 둘 다 **신호를 늦게 받는 쪽이 구조적으로 불리하다**는 뜻이다. 이 프로젝트 리포트에는 신호가 나온 시각과 경과 시간, "이미 많이 움직였으면 추격하지 말라"는 구간 표시가 쓸모 있다.
- 규제기관의 공통 경고 신호는 고수익·보장, "AI가 예측", 검증 안 된 승률, 긴급성이다. 리포트 문구에서도 이런 표현은 피해야 한다(개인용이라도 습관 차원에서).
- 시그널방의 "승률"은 손실 신호 삭제나 사후 선별(생존 편향)을 막을 장치가 없으면 의미가 없다. 반대로 이 프로젝트는 모든 리포트를 기록해 손실까지 자동 집계하면 상용 서비스보다 투명할 수 있다.

### Gaps
- 펌프가 아닌 유료 텔레그램/디스코드 시그널방의 수수료 차감 후 순수익을 측정한 동료 심사 연구는 찾지 못했다.
- 트레이딩 봇·시그널만 겨냥한 FTC 사건, 2025~2026년의 새 CFTC 권고, 리딩방 관련 FIU(금융정보분석원) 경고는 찾지 못했다.
- 2차 블로그에 "Click Profit 2,000만 달러 판결, Air AI 2026-03 영업금지"가 언급되지만 FTC 원문으로 확인하지 못해 위 목록에서 뺐다.
- FCA 핀플루언서 3인 재판의 결과와 Chainalysis 보고서 원문은 확인하지 못했다.

## 4. 한국 시장: AI 차트·시그널 서비스와 리딩방 규제·단속 (2024–2026)

### Takeaway
2026년 하반기에 국내 1·2위 거래소가 직접 AI 분석을 내놨다. 빗썸 AI(2026-09-02)는 1시간마다 6개 지표로 상승/하락 신호와 AI 점수를 주고, 업비트(2026-10)는 시황 영상과 가격 변동 원인을 분석하는 "업트레이스"를 냈다. 주식 리딩방은 2024-08-14 시행된 개정 자본시장법으로 유료 양방향 채널이 사실상 막혔다. 2025~2026년에는 점검·과태료가 늘고 AI 자동매매형 불법 영업이 등장했다. 코인 리딩방은 자본시장법 밖이라 규제 공백이 있다는 지적이 있고, 별도 입법이 논의 중이다.

### Cited Findings
**AI 분석 서비스**
- **빗썸 AI (2026-09-02 출시):** AI 종목시그널, AI 종목분석, AI 데일리시황, AI 추천질문 4가지로 구성. 크립토 특화 AI 리서치 플랫폼 서프(Surf)와 함께 개발. 원화마켓 시가총액 상위 200개 가상자산이 대상 — [SBS Biz](https://biz.sbs.co.kr/amp/article/20000332232), [아시아경제](https://core.asiae.co.kr/article/2026090208214201148), [메트로신문](https://www.metroseoul.co.kr/article/20260902500363)
- 1시간마다 기술·소셜 지표 6가지를 합쳐 단기 상승·하락 신호와 AI 종합 점수를 냄. 사람이 분석하기 어려운 지표와 차트 데이터를 AI가 모아 "직관적인 점수"로 보여준다고 설명 — [아시아경제](https://core.asiae.co.kr/article/2026090208214201148), [SBS Biz](https://biz.sbs.co.kr/amp/article/20000332232) (발췌)
- 출시 47일 만에 누적 이용자 50만 명 **[회사 발표]** — [비즈워치 2026-10-20](https://news.bizwatch.co.kr/article/mobile/2026/10/20/0026)
- **업비트(두나무, 2026-10 초):** 업비트 데이터랩에 "시황 리포트"(시장 상황을 90초 이내 영상으로 요약)와 "업트레이스"(차트의 다이아몬드 아이콘을 누르면 그 자산의 가격 변동 원인을 분석)를 추가 — [MTN 2026-10-02](https://news.mtn.co.kr/news-detail/2026100215101380425)
- 외부 AI 연결 주문 기능: 업비트 "Upbit Skills"(2026-05), 빗썸 "AI 트레이드 킷"(2026-06). ChatGPT·Claude 같은 외부 AI와 연결해 자연어로 API를 쓰고 주문까지 처리 — [디지털타임스](https://www.dt.co.kr/article/12067467), [다음뉴스 2026-05-22](https://v.daum.net/v/20260522133702812)
- 뉴데일리(2026-09-07) 기사 제목: "빗썸·업비트, 분석부터 전략 검증·주문까지 AI 접목 / API 거래대금 비중 30% / '최소 권한 원칙 적용하고 주요 거래엔 사람 개입해야'" — [뉴데일리](https://biz.newdaily.co.kr/site/data/html/2026/09/07/2026090700142.html)
- 알파스퀘어(주식) 지표분석: 보고 있는 종목에 보조지표·매매전략을 적용해 과거 신호 성과를 수익률·승률·신호주기로 보여줌(규칙 기반 과거 성과이지 AI 예측은 아님) — [알파스퀘어](https://alphasquare.co.kr/home/insight/posts/44c9b3e3-d4c1-412f-8e5e-b3148351cc87)

**리딩방 규제·단속**
- **개정 자본시장법 (2024-02-13 개정, 2024-08-14 시행):** 유사투자자문업자는 단방향 채널로 불특정 다수에게 개인별이 아닌 조언만 할 수 있다. SNS·오픈채팅방 같은 양방향 채널로 유료 회원제 영업을 하려면 투자자문업 등록이 필요하다. 무료 회원에게 대가 없이 운영하는 양방향 채널은 가능하다. 문자·카톡·텔레그램 유료 영업도 회신 차단 등으로 양방향 소통 가능성을 원천 차단하지 않으면 등록 대상이다. 손실보전·이익보장 약정은 금지되고 신고 불수리 사유가 넓어졌다 — [대한민국 정책브리핑](https://www.korea.kr/news/policyNewsView.do?newsId=148935062), [블록미디어](https://www.blockmedia.co.kr/archives/453144)
- 금감원 일제 점검(2025년 발표): 유사투자자문업자 745곳을 점검해 112개 업체의 위법 혐의 130건을 적발하고, 형사처벌 대상은 수사기관에 통보. 유형은 준수사항 미이행 44.6%, 보고의무 미이행 35.4%, 미등록 투자자문업 12.3% — [데일리안](https://www.dailian.co.kr/news/view/1507767/%EA%B8%88%EA%B0%90%EC%9B%90-%EB%B6%88%EB%B2%95-%EB%A6%AC%EB%94%A9%EB%B0%A9-%EC%A0%90%EA%B2%80-112%EA%B3%B3-%EC%A0%81-2025)
- **2025년 정기점검 결과 (금융위·금감원, 2026-04-19~20 발표):** 105개 업체의 위법행위 133건 적발. 49개사를 검사해 35개사에 과태료 4.7억 원(2024년 22개사 1.4억 원 대비 약 3.3배). 주요 위법은 표시·광고 필수 기재사항 누락, 금융회사로 오인할 수 있는 상호, 사실과 다른 수익률 제시, 손실보전·이익보장 광고. 앞으로 고위험군을 집중 점검하고, 반복 위반은 직권말소로 퇴출 — [정책브리핑](https://www.korea.kr/news/policyNewsView.do?newsId=148963188), [헤럴드경제](https://www.heraldk.com/article/2026041919001151230), [경향신문](https://www.khan.co.kr/article/202604201200001/)
- 금감원이 2026-04부터 AI 기반 상시 감시체계를 가동했고, 등록제 전환이나 자격요건 강화는 논의하지 않는다는 보도(검색 발췌로만 확인, 공식 발표 미확인) — [경기일보 2026-05-15](https://www.kyeonggi.com/article/20260515580226)
- MTN(2026-09-10) 기사 제목 "리딩방 넘어 AI 자동매매까지… 유사투자자문 피해 민원 5년간 500건↑". 박성훈 의원실이 받은 금감원 자료로는 2022~2026-07 유사투자자문 관련 신고 3,357건, 수사의뢰 550건. 일부 업체는 회원 계좌를 자동매매 프로그램과 연결해 투자 판단까지 맡기는 방식으로 불법 영업을 하다 적발됨 — [MTN](https://news.mtn.co.kr/news-detail/2026091011344567777) (발췌). 비슷한 유형으로 "자동매매 프로그램 판매에 미등록 투자자문까지" 한 사례 보도(날짜 미확인) — [블록미디어](https://www.blockmedia.co.kr/archives/200256)
- **소비자경보:** 2026-01-26 "코스피 및 코스닥 열풍 속 불법 리딩방 주의"(2026-3호). 실존하는 유명 증권사 직원이나 전문가를 사칭해 먼저 신뢰를 얻는 수법 — [SBS Biz](https://biz.sbs.co.kr/amp/article/20000287460), [경북매일](https://kbmaeil.com/article/20260127500064). 2025-08-10 "투자 손실 보상"·"코인 무료 지급"을 미끼로 한 투자사기에 "주의" 경보. 증권사 직원 사칭과 가짜 공문을 쓰며, 1억 2,400만 원을 보낸 피해 사례가 있음 — [세계일보](https://www.segye.com/newsView/20250810505285), [경향신문](https://www.khan.co.kr/article/202508101301011/)
- **코인 리딩방 규제 공백과 입법:** 2025-04 발의된 개정안은 코인 리딩방을 "가상자산 유사자문업"으로 지정해 금융위에 신고하게 하고, 손실 보전·이익 보장·허위 수익률 제시를 금지하는 내용 — [비즈워치 2025-04-16](https://news.bizwatch.co.kr/article/mobile/2025/04/16/0008). 당국은 불특정 다수 대상 유사자문 금지를 우선 검토 중이며, 코인 평가업·공시업은 당분간 도입하지 않기로 함 — [블록미디어](https://www.blockmedia.co.kr/archives/574101) (발췌)
- **피해 통계:** 한국금융소비자보호재단 "2024년 가상자산 이용실태 조사"(2025-04-22 발표, 2024-12 조사, 수도권·광역시 거주 만 19~69세 2,500명): 피해 경험 20.3%. 피해 유형(복수 응답)은 거래소 관련 72.8%, 리딩방 44.7%, 투자 사기 35.5%. 피해 뒤 아무 조치도 안 한 경우 67.7%, 피해액 1천만 원 미만이 75.1% — [경향신문](https://www.khan.co.kr/article/202504221626001), [SBS Biz](https://biz.sbs.co.kr/amp/article/20000230164)
- 경찰청 자료 인용 보도(2024-02-28): 2023년 가상자산 불법행위 피해 1조 415억 원, 그중 4분기에만 약 7,000억 원. 주의: 처음 검색 발췌에서는 이 7,000억 원이 "2023-09~2024-01 코인 리딩방 피해"로 나왔지만, 확인해 보니 리딩방만이 아니라 코인 범죄 전체 숫자였음 — [아주경제](https://www.ajunews.com/view/20240228013437434)

### Inferences
- 빗썸 AI의 "1시간마다 점수와 상승/하락 신호"는 이 프로젝트의 매시간 텔레그램 리포트와 주기가 같다. 보도된 내용에는 무효화 조건, 예상 변동 범위, 포지션 크기 같은 리스크 정보 언급이 없다. 차별점은 여기서 만들 수 있다(단, 보도에 없다고 실제 화면에 없다고 단정할 수는 없음).
- 업비트 업트레이스처럼 "왜 움직였나"(뉴스·청산·펀딩 같은 원인)를 붙이는 설명은 LLM이 잘하는 역할이며, 규칙 기반 신호와 섞이지 않게 따로 표시하는 게 좋다.
- 법적 함의(추론): 이 도구는 개인용이라 문제가 없다. 다만 나중에 리포트를 대가를 받고 다른 사람에게 양방향 채널(텔레그램 단톡 등)로 보내면, 주식은 투자자문업 등록 대상이고 코인도 입법이 추진 중이다. 그리고 손실보전·이익보장 표현은 어느 경우든 적발 사유다.

### Gaps
- 빗썸 AI의 6개 지표 이름·가중치·점수 척도, 화면의 면책 문구, 업비트 업트레이스의 원인 추정 방식은 공개 자료에서 확인하지 못했다.
- 2025-04 "가상자산 유사자문업" 법안의 국회 통과 여부와 가상자산 2단계 입법의 2026-11 현재 상태는 확인하지 못했다.
- "경찰청 집계로 2023-09부터 2년간 불법 투자 리딩방(주식·코인 포함) 신고 14,629건, 피해액 1조 2,901억 원"이라는 내용이 검색 발췌에 나왔지만 원문 기사를 특정하지 못했다.
- 거래소 밖의 독립 한국 AI 코인 차트 앱(유료 구독형) 사례는 거의 찾지 못했고, 알파스퀘어의 "AI 유사 차트" 기능도 확인하지 못했다. CryptoQuant가 한국 기반 회사라는 점은 이번 조사에서 출처를 확보하지 못했다.

## 5. 따라 할 만한 표현 방식: 불확실성, 무효화 레벨, 리스크·포지션 크기, 알림 피로 관리

### Takeaway
잘 만든 도구들은 다섯 가지를 한다. ① 확률을 "과거 같은 조건의 기저율 + 사용자가 고르는 최소 임계값"으로 보여준다. ② 예상 변동 범위(1σ = 68%)를 같이 그린다. ③ 손절 거리에서 포지션 크기를 계산해 준다. ④ 패턴 상태(형성 중/완성)와 신호 종류(추세 확인형/역추세형)를 나눈다. ⑤ 다중 조건·버퍼존·개수 한도로 알림을 거른다. 따라 하면 안 되는 것은 보장·고승률 표현, 검증 안 된 "AI 예측" 표방, repainting으로 부풀린 백테스트다.

### Cited Findings
- 패턴 상태 라벨(형성 중/완성, 지속형/반전형) — [CMC Markets: Autochartist](https://www.cmcmarkets.com/en-gb/trading-platforms/metatrader-4/autochartist)
- 최소 성공 확률 필터(60~80%, 5% 단위)와 품질 등급(1~10). 확률은 패턴 유형·종목·시간대별 과거 성과로 계산 — [Engineer the Forex](https://sites.google.com/view/engineer-the-forex/autochartist)
- 1시간·4시간·24시간 예상 범위를 1σ 68%로 표시 — [Autochartist Help](https://help.autochartist.com/article/an-introduction-to-volatility-analysis/)
- 리스크 계산기: 손절 가격과 위험 허용도로 포지션 크기를 정하고, 예상 범위를 함께 표시. 계좌 자본·거래당 위험 %·변동성을 반영 — [Autochartist Risk Calculator guide](https://static.hotforex.com/assets/common/documents/manuals/Autochartist_Risk_Calculator_User_Guide-SV.pdf), [Pepperstone](https://pepperstone.com/en/learn-to-trade/trading-guides/risk-management-with-autochartist/)
- 다중 조건 동적 알림, 버퍼존, 멀티 타임프레임 — [TrendSpider Help Center](https://help.trendspider.com/kb/overview/introduction-to-trendspider)
- 추세 확인형/역추세형 신호를 나누고 민감도를 사용자에게 노출. "최적 민감도"는 최근 250봉 grid search로 정함 — [LuxAlgo docs](https://docs.luxalgo.com/docs/algos/signals-overlays/signal-settings)
- 신뢰도로 정렬·필터하고 과거 예측과 결과를 볼 수 있게 함 — [Liberated Stock Trader: Tickeron](https://www.liberatedstocktrader.com/tickeron-review/)
- 1~9 점수에 구간 라벨(6~9 = Outperform)을 붙임 — [Kavout Academy](https://www.kavout.com/academy/ai-stock-picker)
- 매시간 점수 + 상승/하락 신호(6개 지표 종합) — [아시아경제: 빗썸 AI](https://core.asiae.co.kr/article/2026090208214201148)
- 가격 변동 "원인"을 설명(업트레이스) — [MTN](https://news.mtn.co.kr/news-detail/2026100215101380425)
- 전략별 수익률·승률·신호주기를 함께 보여줌 — [알파스퀘어](https://alphasquare.co.kr/home/insight/posts/44c9b3e3-d4c1-412f-8e5e-b3148351cc87)
- 청산 히트맵을 모델 하나가 아니라 Model 1/2/3로 나눠 제공 — [CoinGlass Prime](https://www.coinglass.com/prime)
- 알림 개수 한도(1/5/20/100개)와 이메일·텔레그램 전달 — [TheGodFunded: CryptoQuant](https://thegodfunded.com/en/tools/cryptoquant/), [CryptoQuant](https://cryptoquant.com)
- repainting 때문에 백테스트가 부풀려졌다는 작성자 본인의 고백 — [TradingView: Lorentzian KNN v2.0](https://cn.tradingview.com/script/6zaUr2Cy-Machine-Learning-Lorentzian-KNN-Classifier-Update)
- "AI는 미래를 예측할 수 없다", 보장 수익은 경고 신호 — [CFTC advisory](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html)
- 손실보전·이익보장 광고, 사실과 다른 수익률 제시는 국내 적발 사유 — [정책브리핑 2026-04](https://www.korea.kr/news/policyNewsView.do?newsId=148963188)
- AI 주문 연동에는 "최소 권한 원칙, 주요 거래엔 사람 개입" — [뉴데일리](https://biz.newdaily.co.kr/site/data/html/2026/09/07/2026090700142.html)

### Inferences (BTCUSDT 매시간 텔레그램 리포트에 적용할 구체안)
1. **확률은 근거와 함께:** "롱 62%" 대신 "최근 2년 1시간봉에서 같은 조건이 나온 n=143번 중 4시간 안에 +1R에 먼저 닿은 비율 54%(검증 구간 기준)"처럼 표본 수·기간·검증 구간을 붙인다. 표본이 작으면(예: n<30) "근거 부족"으로 표시한다. 보정(calibration), 즉 "70%라고 한 것 중 실제로 몇 %가 맞았나"를 주간으로 보여주면 상용 도구보다 투명해진다.
2. **예상 범위 밴드:** 차트에 1h/4h/24h의 1σ(또는 ATR) 범위를 그린다. 손절이 1σ 노이즈 범위 안이면 "손절이 너무 가까움" 경고를 띄운다(Autochartist 방식).
3. **무효화 레벨을 맨 앞에:** 시나리오마다 "이 가격에서 봉이 마감하면 이 시나리오는 폐기"를 굵게 쓰고, 신호에 "봉 마감 확정/미확정" 상태 라벨을 붙인다. 백테스트와 신호는 마감된 봉만 쓴다(repainting 방지).
4. **포지션 크기는 손절에서 역산:** 수량 = (계좌 × 거래당 위험%) ÷ |진입가 − 손절가|. 레버리지는 결과로 나오는 값(필요 증거금)으로만 보여주고, 손절이 예상 청산가보다 반드시 먼저 오는지 확인한다. 청산 히트맵(CoinGlass API)은 "근처에 청산 물량이 몰린 구간" 참고 정보로만 쓴다.
5. **시나리오 두 개:** 하나의 정답 대신 롱/숏 시나리오를 각각의 무효화 조건과 함께 보여준다(CoinGlass 복수 모델, LuxAlgo 확인형/역추세형 분리와 같은 생각).
6. **알림 피로 줄이기:** 매시간 리포트는 "변화 없음"이면 한두 줄로 줄이고, 상태가 바뀔 때(신호 발생·무효화·레벨 도달)만 강조 알림을 보낸다. 최소 확률 임계값, 버퍼존(레벨 근처에서 신호가 깜빡이지 않게), 하루 강조 알림 상한을 둔다.
7. **신호 나이:** 신호가 처음 나온 시각과 지금까지 움직인 정도를 표시한다. "이미 1σ 넘게 움직였으면 추격하지 않음" 규칙을 둔다(펌프·인플루언서 연구에서 늦게 들어간 쪽이 불리했던 결과 반영).
8. **LLM 역할 분리:** 숫자는 텍스트로 넣고 LLM은 "왜 이런 신호인지"만 설명한다. 판단(롱/숏/관망)은 고정 규칙이 낸다. LLM 문장과 규칙 출력은 눈에 보이게 구분한다.
9. **금지 표현:** "확실", "보장", "AI가 예측", 승률만 단독으로 적기. 승률 옆에는 항상 평균 손익비(R)와 표본 수를 같이 적는다(승률 52%라도 손익비 2:1이면 기대값은 플러스, 승률 90%라도 손익비가 나쁘면 마이너스일 수 있음).
10. **트랙레코드 자동 공개:** 손실을 포함해 모든 과거 리포트의 결과를 자동으로 집계해 주간 요약을 보낸다(Tickeron 과거 예측 열람, 알파스퀘어 승률·신호주기 표시처럼). 이렇게 하면 시그널방의 선별 공개와 정반대의 투명성을 얻는다.

### Gaps
- 상용 도구가 신뢰도 보정 곡선(calibration curve)이나 신뢰구간을 공개한 사례는 찾지 못했다.
- 트레이딩 도구의 알림 피로를 직접 다룬 연구나 제품 문서(쿨다운·요약 알림 설계)는 찾지 못했다. 위 6번은 추론이다.
- 빗썸·업비트 AI 화면이 불확실성과 면책을 어떻게 표시하는지는 확인하지 못했다.
