# 오픈소스 빌딩블록 조사: BTCUSDT 무기한선물 차트 분석 + 시간별 텔레그램 리포트 도구 (2026-11-07 기준)

## 1. Freqtrade와 FreqAI: 기능, 텔레그램 연동, 라이선스, 커뮤니티 규모, 한계와 과적합 경고

### Takeaway
Freqtrade(GPL-3.0, 별 56.6k, 2026-11-05 커밋, PyPI 2026.10)는 가장 성숙한 오픈소스 크립토 봇입니다. 데이터 다운로드, 백테스트, hyperopt, 텔레그램 제어, FreqAI가 모두 들어 있습니다. FreqAI는 LightGBM, XGBoost, PyTorch, 강화학습을 지원하고, 슬라이딩 윈도 재학습과 DI/SVM/DBSCAN 이상치 제거를 제공합니다. 다만 세 가지 제약이 있습니다.
- Python 3.12 이상이 필요합니다. 이 프로젝트의 `.venv`는 3.11.18입니다.
- 자동매매 봇 구조입니다.
- 라이선스가 GPL입니다.

그래서 통째로 쓰기보다 개념과 검증 도구를 빌려 오는 편이 현실적입니다. 빌릴 만한 것은 슬라이딩 윈도, 모델 만료, lookahead/recursive 분석, 백테스트 가정 목록입니다.

### Cited Findings

#### 메타데이터 수집 방법 (모든 섹션 공통)
- 별, 포크, 라이선스는 GitHub 검색 API로 2026-11-07에 조회했습니다([조회1](https://api.github.com/search/repositories?q=repo:freqtrade/freqtrade+repo:jesse-ai/jesse+repo:hummingbot/hummingbot+repo:nautechsystems/nautilus_trader+repo:mementum/backtrader+repo:kernc/backtesting.py+repo:polakowo/vectorbt+repo:stefan-jansen/zipline-reloaded+repo:QuantConnect/Lean+repo:microsoft/qlib+repo:AI4Finance-Foundation/FinRL+repo:AI4Finance-Foundation/FinRL-Meta+repo:OpenBB-finance/OpenBB+repo:ccxt/ccxt+repo:matplotlib/mplfinance+repo:plotly/Kaleido+repo:tradingview/lightweight-charts+repo:louisnw01/lightweight-charts-python+repo:python-telegram-bot/python-telegram-bot+repo:aiogram/aiogram+repo:binance/binance-public-data+repo:Drakkar-Software/OctoBot+repo:CryptoSignal/Crypto-Signal+repo:TauricResearch/TradingAgents+repo:virattt/ai-hedge-fund+repo:microsoft/RD-Agent+repo:whittlem/pycryptobot+repo:sammchardy/python-binance&per_page=50), [조회2](https://api.github.com/search/repositories?q=repo:OpenBB-finance/OpenBB+repo:stefan-jansen/zipline-reloaded+repo:plotly/plotly.py+repo:Kozea/WeasyPrint+repo:py-pdf/fpdf2+repo:TA-Lib/ta-lib-python+repo:bukosabino/ta+repo:agronholm/apscheduler+repo:eternnoir/pyTelegramBotAPI+repo:binance/binance-connector-python+repo:hummingbot/condor+repo:AI4Finance-Foundation/FinRL-Trading+repo:fabston/TradingView-Webhook-Bot+repo:matplotlib/matplotlib&per_page=30)).
  - OpenBB, zipline-reloaded, fpdf2는 두 조회 모두 결과에 나오지 않았습니다. 별 수는 미확인입니다.
- "최근 커밋"은 기본 브랜치 HEAD 커밋 날짜입니다. 2026-11-07에 각 저장소를 shallow clone(`git log -1`)해서 확인했습니다.
- "최신 릴리스"와 "Python 요구"는 PyPI JSON의 `version`, 업로드일, `requires_python`입니다([예: freqtrade](https://pypi.org/project/freqtrade/)).

#### 규모, 유지보수, 라이선스
- **규모:** 별 56,578, 포크 11,697입니다. 열린 이슈+PR은 27개(API 값)입니다. — [GitHub freqtrade/freqtrade](https://github.com/freqtrade/freqtrade)
- **라이선스:** GPL-3.0입니다. — [GitHub freqtrade/freqtrade](https://github.com/freqtrade/freqtrade)
- **최근 커밋:** develop 브랜치 2026-11-05, "Merge pull request #13740 … update/binance-leverage-tiers"입니다. — [commits](https://github.com/freqtrade/freqtrade/commits/develop)
- **최신 릴리스:** `freqtrade` 2026.10, 2026-10-30 업로드입니다. — [PyPI freqtrade](https://pypi.org/project/freqtrade/)
- **Python 요구:** `requires_python >=3.12`, 분류자는 3.12~3.14입니다. — [PyPI freqtrade](https://pypi.org/project/freqtrade/)
- **설치 문서:** "Python >= 3.12"를 요구하고 uv 설치도 지원합니다. Docker 이미지에는 python3.13이 들어 있습니다. — [docs/installation.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/installation.md)
- **커뮤니티 전략 저장소:** `freqtrade-strategies`의 최근 커밋은 2026-09-08입니다. — [commits](https://github.com/freqtrade/freqtrade-strategies/commits)
- **커뮤니티 채널:** 공식 커뮤니티는 Discord 서버입니다. 질문과 개발 논의를 위해 가입을 권장합니다. — [README](https://github.com/freqtrade/freqtrade/blob/develop/README.md)

#### Freqtrade 핵심 기능
- README는 Freqtrade를 이렇게 소개합니다. — [README](https://github.com/freqtrade/freqtrade/blob/develop/README.md)
  > "free and open source crypto trading bot written in Python … controlled via Telegram or webUI. It contains backtesting, plotting and money management tools as well as strategy optimization by machine learning."
- **지원 선물 거래소:** Binance, Hyperliquid(DEX), Kraken 등입니다. 거래소별 노트와 레버리지 문서를 먼저 읽으라고 안내합니다. — [README](https://github.com/freqtrade/freqtrade/blob/develop/README.md)
- **CLI 서브커맨드:** README 목록에 다음이 있습니다. — [README](https://github.com/freqtrade/freqtrade/blob/develop/README.md)
  - 데이터: `download-data`, `convert-data`, `list-data`
  - 백테스트: `backtesting`, `backtesting-analysis`
  - 최적화: `hyperopt`, `edge`
  - 차트: `plot-dataframe`, `plot-profit`
- **데이터 다운로드:**
  - `--days 20` 같은 상대 기간이나 `--timerange 20200101-` 같은 절대 시작점을 씁니다. 기존 데이터가 있으면 빠진 구간만 자동으로 받습니다. 과거 쪽 추가는 `--prepend`로 합니다. — [docs/data-download.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/data-download.md)
  - 선물(`--trading-mode futures`)에서는 `mark`와 `funding_rate` 캔들을 자동으로 받습니다. 미결제약정은 `--candle-types open_interest`로 따로 요청합니다. — [docs/data-download.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/data-download.md)
  - 기본 저장 포맷은 `feather`(Apache Arrow)이고, `parquet`(OHLCV만)도 고를 수 있습니다. — [docs/data-download.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/data-download.md)
- **차트 기능:** "Plotting modules use the Plotly library." 즉 plot-dataframe은 Plotly 기반입니다. — [docs/plotting.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/plotting.md)
- **선물 마진 모드:** `isolated`와 `cross`를 지원합니다. — [docs/leverage.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/leverage.md)
  - 문서 경고: cross 모드는 "may not be fully simulated in dry-run or backtesting mode"입니다.
  - 청산 경고 기능은 "experimental … best effort"입니다.
- **Binance 관련 노트:** — [docs/exchanges.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/exchanges.md)
  - 서버 국가 기준으로 API 접근이 제한됩니다. 문서가 예로 든 차단국(전체 목록 아님)은 캐나다, 말레이시아, 네덜란드, 미국입니다.
  - 선물에서는 "orderbook must be used because there is no price ticker data for futures"입니다.
  - 유럽 규제 대응용 BNFCR 선물 모드가 있습니다.
  - BNB를 블랙리스트에 넣으라고 권장합니다.

#### FreqAI 기능
- **정의:** 다음은 [docs/freqai.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai.md)의 설명입니다.
  > "a software designed to automate a variety of tasks associated with training a predictive machine learning model to generate market forecasts given a set of input signals"
  - 같은 문서는 FreqAI가 "not-for-profit"이고 토큰이나 시그널을 팔지 않는다고 명시합니다.
- **기능 목록:** 같은 문서에 나오는 기능입니다. — [docs/freqai.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai.md)
  - Self-adaptive retraining (라이브 중 재학습)
  - Rapid feature engineering (10k+ 피처)
  - 학습을 별도 스레드나 GPU로 분리
  - 자동 재학습을 흉내 내는 "Realistic backtesting"
  - Smart outlier removal
  - Crash resilience (모델 디스크 저장, 오래된 파일 정리)
  - 자동 정규화, 자동 데이터 다운로드, NaN 처리, PCA
  - producer/consumer 봇 플릿
- **모델:**
  - `--freqaimodel`로 LightGBM과 XGBoost의 회귀, 분류, 다중 타깃 예제를 바로 씁니다. `IFreqaiModel`을 상속하면 커스텀 모델도 만들 수 있습니다. — [docs/freqai-configuration.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-configuration.md)
  - CatBoost는 "No longer actively supported since 2025.12"입니다. — [docs/freqai-configuration.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-configuration.md)
  - PyTorch 모듈(`PyTorchMLPRegressor` 등)은 torch 약 700MB를 추가로 설치해야 합니다. — [docs/freqai-configuration.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-configuration.md)
  - "PyTorch dropped support for macOS x64 (intel based Apple devices) in version 2.3. Subsequently, freqtrade also dropped support for PyTorch on this platform." — [docs/freqai-configuration.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-configuration.md)
- **강화학습:** — [docs/freqai-reinforcement-learning.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-reinforcement-learning.md)
  - "built on stable_baselines3 (torch) and OpenAI gym" 기반이며 PPO 같은 `model_type`을 씁니다.
  - 환경은 Base3/4/5ActionRLEnv입니다. long-only가 가능한 것은 Base3뿐입니다.
  - 의존성이 약 700MB 늘어나고, `_freqairl` Docker 이미지가 따로 있습니다.
- **재학습 윈도 파라미터:** — [docs/freqai-parameter-table.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-parameter-table.md)
  - `train_period_days`: 필수. 슬라이딩 학습 윈도의 폭입니다.
  - `backtest_period_days`: 필수. 재학습 전에 추론할 일수입니다.
  - `live_retrain_hours`: 기본 0. 가능한 한 자주 재학습합니다.
  - `expiration_hours`: 기본 0. 이 시간보다 오래된 모델로는 예측하지 않습니다.
  - `purge_old_models`: 기본 2개 보관입니다.
  - `fit_live_predictions_candles`: 동적 타깃 임계값 계산용입니다.
  - `save_backtest_models`
  - `data_kitchen_thread_count`: 기본 "max threads − 2"입니다.
- **예제 설정:** 30일로 학습하고 이어지는 7일을 백테스트합니다. 학습 횟수는 `--timerange ÷ backtest_period_days`입니다. 예를 들어 10일을 0.1로 나누면 페어당 100개 모델을 학습합니다. — [docs/freqai-running.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-running.md)
- **이상치 탐지와 차원 축소:** — [docs/freqai-parameter-table.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-parameter-table.md), [docs/freqai-feature-engineering.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-feature-engineering.md)
  - `DI_threshold`: Dissimilarity Index 방식입니다.
  - `use_SVM_to_remove_outliers`
  - `use_DBSCAN_to_remove_outliers`
  - `outlier_protection_percentage`: SVM/DBSCAN이 이 비율 이상을 이상치로 잡으면 경고를 남기고 이상치 제거를 무시합니다.
  - `principal_component_analysis`: PCA 차원 축소입니다.
  - 피처 엔지니어링 문서에 DI, SVM, DBSCAN, PCA와 데이터 파이프라인 커스터마이즈 섹션이 있습니다.
- **학술 출판:** FreqAI는 JOSS에 실렸습니다(DOI 10.21105/joss.04864). — [docs/freqai.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai.md) → [JOSS](https://joss.theoj.org/papers/10.21105/joss.04864)

#### 텔레그램 연동
- **설정 순서:** BotFather로 봇을 만들어 토큰을 `token`에 넣습니다. userinfobot으로 Id를 얻어 `chat_id`에 넣습니다. — [docs/telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/telegram-usage.md)
  - 그룹은 음수 chat_id를, 토픽은 `topic_id`를 씁니다. `/tg_info`로 확인합니다.
- **명령 권한 제한:** `authorized_users`로 명령할 수 있는 사람을 제한합니다. "If `"authorized_users": []` is present and empty, no user will be allowed to control the bot." 나머지 사용자는 메시지만 받습니다. — [docs/telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/telegram-usage.md)
- **알림과 키보드:** `notification_settings`로 알림 소음을 조절하고, `allow_custom_messages`와 커스텀 키보드를 지원합니다. — [docs/telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/telegram-usage.md)
- **명령 예시:** `/status`, `/profit`, `/forceexit`, `/stopentry`, `/stop` 등입니다. — [docs/telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/telegram-usage.md)
- **비밀값을 환경변수로:** `FREQTRADE__` 접두사로 설정을 덮어씁니다. 예: `FREQTRADE__EXCHANGE__KEY` ("to keep your exchange key secret"), `FREQTRADE__TELEGRAM__CHAT_ID`. 우선순위는 환경변수 > 설정파일이고, CLI 인자가 최우선입니다. — [docs/configuration.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/configuration.md)
- **파일에서 키 읽기:** RSA 키를 `export FREQTRADE__EXCHANGE__SECRET="$(cat ./rsa_binance.private)"`처럼 파일에서 읽는 예시가 있습니다. — [docs/exchanges.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/exchanges.md)

#### 공식 문서의 한계와 과적합 경고
- **README 면책:** "This software is for educational purposes only. Do not risk money which…" 그리고 "Always start by running a trading bot in Dry-Run". — [README](https://github.com/freqtrade/freqtrade/blob/develop/README.md)
- **백테스트 가정:** — [docs/backtesting.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/backtesting.md)
  - 진입은 시가에서 이뤄집니다.
  - 고가~저가 범위 안이면 슬리피지 없이 체결된다고 봅니다.
  - 스톱로스는 정확히 스톱 가격에서 체결됩니다(수수료 2배 가산).
  - 한 캔들 안에서는 "Low happens before high"로 가정합니다.
  - 평가 순서는 exit-signal → stoploss → ROI → trailing입니다.
  - 결론: "backtesting will **never** replace running a strategy in dry-run mode."
- **hyperopt 정밀도:** 소수점을 3자리로 제한합니다. 이유는 "every value more precise than this will usually result in overfitted results"입니다. — [docs/hyperopt.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/hyperopt.md)
- **look-ahead 편향:** "Lookahead bias is the bane of any strategy … very hard to detect." 백테스트는 전체 데이터프레임을 한 번에 계산하므로, 미래 캔들을 보면 결과가 왜곡됩니다. 이를 검증하는 `lookahead-analysis` 명령이 있습니다. — [docs/lookahead-analysis.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/lookahead-analysis.md)
- **재귀형 지표:** 백테스트는 데이터를 전부 쓰지만, 라이브는 거래소가 주는 캔들 수만큼만 씁니다. 그래서 재귀형 지표 값이 달라질 수 있고, 이를 검증하는 `recursive-analysis`가 있습니다. — [docs/recursive-analysis.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/recursive-analysis.md)
- **FreqAI 백테스트의 look-ahead 함정:** 타깃 함수는 윈도마다 호출합니다. 반면 `feature_engineering_*()`의 피처 정의는 전체 학습 구간에 한 번 수행됩니다. 문서는 이를 look-ahead 주의사항으로 안내합니다. — [docs/freqai-running.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-running.md)
- **continual_learning:** "naive approach … high probability of overfitting/getting stuck in local minima while the market moves away from your model"입니다. — [docs/freqai-parameter-table.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-parameter-table.md)
- **예제는 운영용이 아님:**
  - 예제 전략은 "Not for production"입니다. — [docs/freqai.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai.md)
  - RL 예제 보상함수는 "it is *not* for live production"입니다. — [docs/freqai-reinforcement-learning.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-reinforcement-learning.md)
- **모델 파일 보안:** 외부에서 받은 모델 파일을 로드하면 `weights_only=False` 때문에 보안 위험이 있습니다. 직접 학습한 모델만 쓰면 위험이 없습니다. — [docs/freqai-running.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-running.md)
- **Tensorboard:** 학습을 느리게 하므로 운영에서는 끄라고 합니다. — [docs/freqai-running.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-running.md)

### Inferences
- **Python 버전 충돌:** 이 프로젝트 `.venv`는 Python 3.11.18입니다. 최신 Freqtrade(≥3.12)는 같은 가상환경에 설치할 수 없습니다. 쓰려면 별도 venv나 Docker가 필요합니다.
- **용도 차이:** Freqtrade는 주문을 내는 봇 구조입니다. "사용자가 수동 주문, LIVE 금지"라는 요구에 맞추려면 dry-run 신호기로만 써야 합니다. 그러면 이미 있는 자체 봇과 기능이 겹칩니다.
- **빌려 올 가치가 큰 것:** FreqAI의 설계 아이디어입니다.
  - 슬라이딩 윈도 재학습
  - 모델 만료(`expiration_hours`)
  - 이상치 보호 비율
  - 백테스트 창 개수 = 기간 ÷ 재학습 주기
  - lookahead/recursive 검증 개념
  - 이것들을 고정 규칙(TREND_SPEC)과 TRIALS.md 기록 방식에 이식하면 좋습니다.
- **GPL 주의:** Freqtrade는 GPL-3.0입니다. 공개 저장소에 코드를 복사하면 파생저작물 의무가 생길 수 있습니다. 코드 대신 개념을 재구현하는 편이 안전합니다.
- **macOS:** Apple Silicon Mac이면 PyTorch 경로도 가능합니다. Intel Mac에서는 FreqAI PyTorch를 쓸 수 없습니다.

### Gaps
- Discord 회원 수 같은 커뮤니티 규모 수치는 찾지 못했습니다.
- FreqAI의 실제 라이브 성과를 정량 비교한 독립 연구는 찾지 못했습니다.
- freqtrade.io의 stable 문서와 develop 브랜치 문서가 얼마나 다른지 확인하지 못했습니다. 이번 조사는 develop 브랜치 markdown을 읽었습니다.

## 2. 기타 프레임워크: 목적, 강점, Python 버전, 2025~2026 유지보수 상태, 연구용 vs 라이브용

### Takeaway
2026-11 기준 상태는 네 갈래로 나뉩니다.
- **활발하게 유지보수:** Jesse, NautilusTrader, vectorbt, LEAN, CCXT, OpenBB(ODP), Hummingbot, backtesting.py
- **유지보수만 하고 기능 개발은 다른 곳으로:** Zipline-reloaded, FinRL
- **사실상 정지:** backtrader
- **크립토 1h 분석에 부적합:** Qlib(크립토는 일봉, OHLC 없음, 백테스트 불가)

단일 사용자의 1h BTCUSDT 분석에는 **CCXT 또는 Binance 공식 SDK(데이터)**와 **vectorbt 또는 backtesting.py(연구용 백테스트)** 정도가 가볍습니다. NautilusTrader와 LEAN은 강력하지만 무겁습니다.

### Cited Findings

#### 비교표
표의 별, 라이선스는 [조회1](https://api.github.com/search/repositories?q=repo:freqtrade/freqtrade+repo:jesse-ai/jesse+repo:hummingbot/hummingbot+repo:nautechsystems/nautilus_trader+repo:mementum/backtrader+repo:kernc/backtesting.py+repo:polakowo/vectorbt+repo:stefan-jansen/zipline-reloaded+repo:QuantConnect/Lean+repo:microsoft/qlib+repo:AI4Finance-Foundation/FinRL+repo:AI4Finance-Foundation/FinRL-Meta+repo:OpenBB-finance/OpenBB+repo:ccxt/ccxt+repo:matplotlib/mplfinance+repo:plotly/Kaleido+repo:tradingview/lightweight-charts+repo:louisnw01/lightweight-charts-python+repo:python-telegram-bot/python-telegram-bot+repo:aiogram/aiogram+repo:binance/binance-public-data+repo:Drakkar-Software/OctoBot+repo:CryptoSignal/Crypto-Signal+repo:TauricResearch/TradingAgents+repo:virattt/ai-hedge-fund+repo:microsoft/RD-Agent+repo:whittlem/pycryptobot+repo:sammchardy/python-binance&per_page=50)과 각 GitHub 페이지 기준입니다. 커밋은 기본 브랜치 HEAD, 릴리스와 Python은 PyPI 기준입니다.

| 프로젝트 | 목적 | 별 | 라이선스 | 최근 커밋 | 최신 PyPI 릴리스 | Python | 출처 |
|---|---|---|---|---|---|---|---|
| Jesse | 크립토 전략 연구, 백테스트, 최적화, 라이브 | 8,775 | MIT | 2026-11-06 | 3.6.0 (2026-11-03) | ≥3.10 | [GH](https://github.com/jesse-ai/jesse), [PyPI](https://pypi.org/project/jesse/) |
| Hummingbot | 마켓메이킹/HFT 봇 (CEX+DEX) | 20,977 | Apache-2.0 | 2026-09-22 (master) | 20260922 (2026-10-07) | ≥3.10.12 | [GH](https://github.com/hummingbot/hummingbot), [PyPI](https://pypi.org/project/hummingbot/) |
| NautilusTrader | Rust 네이티브 이벤트 기반 엔진 | 31,319 | LGPL-3.0 | 2026-11-07 (develop) | 1.231.0 (2026-08-02) | PyPI ≥3.12,<3.15 / develop README 3.13~3.15 | [GH](https://github.com/nautechsystems/nautilus_trader), [PyPI](https://pypi.org/project/nautilus_trader/) |
| backtrader | 이벤트 기반 백테스트 | 23,678 | GPL-3.0 | 2023-04-19 | 1.9.78.123 (2023-04-19) | 분류자 3.7까지 | [GH](https://github.com/mementum/backtrader), [PyPI](https://pypi.org/project/backtrader/) |
| backtesting.py | 경량 백테스트 | 9,208 | AGPL-3.0 | 2026-08-05 | 0.6.6 (2026-07-22) | ≥3.9 | [GH](https://github.com/kernc/backtesting.py), [PyPI](https://pypi.org/project/backtesting/) |
| vectorbt (커뮤니티판) | 벡터화 대규모 연구 | 9,724 | Apache-2.0 + Commons Clause | 2026-11-03 | 1.2.0 (2026-10-19) | ≥3.11,<3.15 | [GH](https://github.com/polakowo/vectorbt), [PyPI](https://pypi.org/project/vectorbt/) |
| Zipline-reloaded | Quantopian 계열 이벤트 기반 백테스트 | 미확인 | Apache-2.0 | 2026-11-02 | 3.2.1 (2026-10-25) | ≥3.11,<3.15 | [GH](https://github.com/stefan-jansen/zipline-reloaded), [PyPI](https://pypi.org/project/zipline-reloaded/) |
| QuantConnect LEAN (+lean CLI) | C# 엔진 + Python 알고리즘, Docker 기반 CLI | 22,426 | Apache-2.0 | 2026-11-06 | lean CLI 1.0.233 (2026-10-27) | CLI ≥3.9 | [GH](https://github.com/QuantConnect/Lean), [PyPI](https://pypi.org/project/lean/) |
| Microsoft Qlib | AI 퀀트 연구 플랫폼 | 50,084 | MIT | 2026-10-08 | pyqlib 0.9.7 (2025-08-15) | 3.8~3.12 | [GH](https://github.com/microsoft/qlib), [PyPI](https://pypi.org/project/pyqlib/) |
| FinRL / FinRL-Meta | 금융 심층강화학습 / 시장 환경·데이터 | 17,010 / 1,961 | MIT / MIT | 2026-10-25 / 2026-09-28 | finrl 0.3.7 (2024-04-12) | README 배지 3.6 (낡음) | [GH FinRL](https://github.com/AI4Finance-Foundation/FinRL), [GH Meta](https://github.com/AI4Finance-Foundation/FinRL-Meta), [PyPI](https://pypi.org/project/finrl/) |
| OpenBB (ODP) | 금융 데이터 통합 플랫폼 | 미확인 | Apache-2.0 | 2026-11-06 | openbb 5.0.0 (2026-09-29) | ≥3.10,<4 | [GH](https://github.com/OpenBB-finance/OpenBB), [PyPI](https://pypi.org/project/openbb/) |
| CCXT | 100개+ 거래소 통합 API | 44,784 | MIT | 2026-11-05 | 4.5.92 (2026-11-04) | ≥3.10 | [GH](https://github.com/ccxt/ccxt), [PyPI](https://pypi.org/project/ccxt/) |

#### 프레임워크별 세부
- **Jesse**
  - 다음 기능을 제공합니다. — [README](https://github.com/jesse-ai/jesse/blob/master/README.md)
    - 다중 타임프레임과 다중 심볼을 look-ahead 없이 백테스트하고 라이브로 돌립니다.
    - Optimize 모드(Optuna + Ray)
    - Monte Carlo 분석: "to distinguish skill from luck and guard against overfitting"
    - 내장 ML 파이프라인: 백테스트에서 라벨 데이터를 모아 scikit-learn 모델을 학습합니다.
    - 300개 이상의 지표
    - 대화형 차트
    - Jesse MCP: Claude, Codex 등 AI 어시스턴트와 연결합니다.
    - 라이브와 페이퍼 트레이딩 알림(Telegram, Slack, Discord)
  - LICENSE는 MIT입니다. — [LICENSE](https://github.com/jesse-ai/jesse/blob/master/LICENSE)
- **Hummingbot**
  - Apache 2.0이며 "democratize high-frequency trading"을 목표로 합니다. — [README](https://github.com/hummingbot/hummingbot/blob/master/README.md)
  - API 키 없이 `binance_paper_trade`로 실시간 Binance 데이터에 대고 모의 거래를 할 수 있습니다. — [README](https://github.com/hummingbot/hummingbot/blob/master/README.md)
  - DEX 미들웨어는 Gateway이고, Docker Compose로 배포합니다. — [README](https://github.com/hummingbot/hummingbot/blob/master/README.md)
  - Condor는 "AI harness"입니다. LLM 판단을 결정론적 주문 실행에 연결합니다. — [README](https://github.com/hummingbot/hummingbot/blob/master/README.md)
  - Condor 저장소: 별 253, MIT입니다. — [GH condor](https://github.com/hummingbot/condor)
- **NautilusTrader**
  - "production-grade, Rust-native engine"입니다. 같은 전략 코드를 백테스트와 라이브에서 씁니다. — [README](https://github.com/nautechsystems/nautilus_trader/blob/develop/README.md)
  - 백테스트는 틱, 바, 오더북 데이터를 나노초 해상도로 다룹니다. — [README](https://github.com/nautechsystems/nautilus_trader/blob/develop/README.md)
  - v2 런타임 Python 바인딩은 PyO3입니다. "During the v2 transition, v1 receives only critical security backports on the `develop_v1` branch." — [README](https://github.com/nautechsystems/nautilus_trader/blob/develop/README.md)
  - Binance 통합 상태는 "stable"입니다. — [README](https://github.com/nautechsystems/nautilus_trader/blob/develop/README.md)
  - develop 플랫폼 표는 Python 3.13~3.15입니다. 3.15는 "source build or a development wheel until the next PyPI release"입니다. 반면 마지막 PyPI 1.231.0은 2026-08-02에 나왔고 ≥3.12입니다. — [README](https://github.com/nautechsystems/nautilus_trader/blob/develop/README.md), [PyPI](https://pypi.org/project/nautilus_trader/)
- **backtrader**
  - 기본 브랜치 마지막 커밋은 2023-04-19 "Version 1.9.78.123"이고, PyPI 마지막 릴리스도 같은 날입니다. — [commits](https://github.com/mementum/backtrader/commits), [PyPI](https://pypi.org/project/backtrader/)
  - PyPI 분류자는 Python 3.7까지입니다. — [PyPI](https://pypi.org/project/backtrader/)
- **backtesting.py**
  - 기능: "Backtest trading strategies with Python", SAMBO 기반 내장 최적화, 대화형 시각화. — [README](https://github.com/kernc/backtesting.py/blob/master/README.md)
  - 라이선스는 AGPL-3.0입니다. — [PyPI](https://pypi.org/project/backtesting/)
  - 2026-08 커밋 예: "Size shared memory by materialized array". — [commits](https://github.com/kernc/backtesting.py/commits)
- **vectorbt / vectorbt PRO**
  - 커뮤니티판은 "Python toolkit for trading research"입니다. NumPy와 Numba로 가속하고, README에는 선택형 Rust 구성요소도 언급됩니다. — [README](https://github.com/polakowo/vectorbt/blob/master/README.md)
  - "VectorBT is the open-source community edition of VectorBT PRO. PRO extends the library with parallelization, additional data integrations, portfolio optimization, …" — [README](https://github.com/polakowo/vectorbt/blob/master/README.md)
  - 라이선스는 "Apache 2.0 with Commons Clause"입니다. 소프트웨어 판매("Sell")를 금지하며, GitHub 배지는 "Fair Code"입니다. — [LICENSE.md](https://github.com/polakowo/vectorbt/blob/master/LICENSE.md)
- **Zipline-reloaded**
  - "We continue to maintain Zipline Reloaded for bug, security and compatibility fixes. Our new feature development focuses on ML4T Backtest." — [README](https://github.com/stefan-jansen/zipline-reloaded/blob/main/README.md)
- **LEAN**
  - "event-driven, professional-caliber algorithmic trading platform"입니다. — [README](https://github.com/QuantConnect/Lean/blob/master/readme.md)
  - lean CLI로 로컬 Jupyter, 백테스트, 최적화, 라이브를 Docker로 실행합니다. "For most users we strongly recommend the LEAN CLI". — [README](https://github.com/QuantConnect/Lean/blob/master/readme.md)
  - Python 지원은 Algorithm.Python 프로젝트를 통해서입니다. — [README](https://github.com/QuantConnect/Lean/blob/master/readme.md)
- **Qlib (크립토 지원)**
  - 크립토 수집기는 Coingecko 일봉 데이터입니다. — [crypto collector README](https://github.com/microsoft/qlib/blob/main/scripts/data_collector/crypto/README.md)
  - 원문: "Crypto dataset only support Data retrieval function but not support backtest function due to the lack of OHLC data." — [crypto collector README](https://github.com/microsoft/qlib/blob/main/scripts/data_collector/crypto/README.md)
  - 지원 Python은 3.8~3.12(README 표)입니다. — [README](https://github.com/microsoft/qlib/blob/main/README.md)
  - 2026-10-08 커밋: "fix(security): constrain config-driven code execution (#2340)". — [commits](https://github.com/microsoft/qlib/commits)
  - LLM 기반 자동 팩터 발굴 도구 RD-Agent: 별 15,268, MIT입니다. 2026-09-23 커밋 "release 1.0.0"이 있습니다. — [README](https://github.com/microsoft/qlib/blob/main/README.md), [GH RD-Agent](https://github.com/microsoft/RD-Agent)
- **FinRL / FinRL-Meta**
  - FinRL README는 "FinRL → FinRL-X"로 이어집니다. 이 저장소는 "preserves the original end-to-end educational and research framework"이고, 신규 사용자는 FinRL-X / FinRL-Trading을 쓰라고 권장합니다. — [README](https://github.com/AI4Finance-Foundation/FinRL/blob/master/README.md)
  - FinRL-Trading: 별 3,911, Apache-2.0입니다. — [GH](https://github.com/AI4Finance-Foundation/FinRL-Trading)
  - FinRL-Meta 데이터 소스 표에 Binance(1s, 1min)와 CCXT(1min OHLCV)가 있습니다. — [README](https://github.com/AI4Finance-Foundation/FinRL-Meta/blob/master/README.md)
- **OpenBB**
  - 현재 이름은 "Open Data Platform by OpenBB (ODP)"입니다. 데이터 엔지니어가 데이터 소스를 AI copilot이나 대시보드에 연결하는 "connect once, consume everywhere" 계층입니다. 연결 대상은 Python, OpenBB Workspace(엔터프라이즈 UI), Excel, MCP 서버입니다. — [README](https://github.com/OpenBB-finance/OpenBB/blob/develop/README.md)
  - LICENSE: "All files in this repository are licensed under the Apache License, Version 2.0" (Copyright 2021-2026). — [LICENSE](https://github.com/OpenBB-finance/OpenBB/blob/develop/LICENSE)
- **CCXT**
  - "more than 100 exchanges and prediction markets"를 JS/TS/Python/C#/PHP/Go/Java/Rust로 지원합니다. 공개·비공개 REST와 WebSocket을 구현합니다. 인증 거래소에 binance, bybit, gate, okx가 있습니다. — [README](https://github.com/ccxt/ccxt/blob/master/README.md)

### Inferences
- **연구 단계 백테스트:** 의존성이 가볍고 Python 3.11에서 돌아가는 후보는 vectorbt(≥3.11)와 backtesting.py(≥3.9)입니다.
  - backtesting.py는 AGPL입니다. 웹 서비스로 공개할 계획이 없으면 문제가 적지만, 공개 저장소이므로 라이선스 표기는 확인해야 합니다.
  - vectorbt의 Commons Clause는 판매만 막습니다. 개인용이면 문제없습니다.
- **라이브 엔진:** NautilusTrader와 LEAN은 "백테스트 = 라이브 동일 코드"가 강점입니다. 그러나 이 프로젝트는 수동 주문이고 LIVE를 금지합니다. 그래서 장점이 거의 살지 않고, 복잡도(Docker, C#, v2 전환)만 늘어납니다.
- **Qlib과 FinRL:** BTCUSDT 1h 선물 분석의 직접 기반으로 부적합합니다.
  - Qlib 크립토는 일봉이고 백테스트가 안 됩니다.
  - FinRL은 교육·연구용이고 PyPI가 2024년에 멈췄습니다.
- **Hummingbot:** 목적이 마켓메이킹입니다. 차트 분석 리포트 용도와 맞지 않습니다.

### Gaps
- vectorbt PRO의 가격과 접근 방식(구독 여부)은 확인하지 못했습니다. vectorbt.pro 페이지는 조회하지 않았습니다.
- Jesse 라이브 트레이딩이 무료인지 확인하지 못했습니다.
- LEAN에서 Binance 선물 과거 데이터를 쓰는 데 드는 비용과 조건은 확인하지 못했습니다.
- Zipline의 24/7 크립토 캘린더 지원 여부는 확인하지 못했습니다.
- OpenBB와 zipline-reloaded의 별 수는 API 결과에 나오지 않아 미확인입니다.
- backtesting.py가 단일 종목 전용인지는 README에서 확인하지 못했습니다.

## 3. 차트와 리포트 생성 라이브러리 (mplfinance, matplotlib, plotly/kaleido, lightweight-charts) 및 PDF 생성

### Takeaway
서버나 맥에서 사람 개입 없이(headless) PNG/PDF를 만드는 데 가장 의존성이 적은 조합은 **matplotlib**입니다. PNG는 matplotlib으로, 여러 페이지 PDF는 `PdfPages`로 만듭니다. 텍스트와 이미지 레이아웃이 필요하면 fpdf2 또는 ReportLab을 씁니다. 나머지는 각자 걸림돌이 있습니다.
- **mplfinance:** 캔들 전용으로 편하지만 2023-08 이후 릴리스가 없는 베타입니다.
- **plotly + Kaleido:** v1부터 Chrome이 필요합니다.
- **TradingView lightweight-charts:** 브라우저 JS 라이브러리입니다. PNG를 만들려면 헤드리스 브라우저가 따로 필요합니다.

### Cited Findings

| 라이브러리 | 용도 | 별 | 라이선스 | 최근 활동 | 최신 릴리스 | Python | 출처 |
|---|---|---|---|---|---|---|---|
| mplfinance | matplotlib 기반 금융 차트 | 4,459 | BSD-style (PyPI). GitHub은 NOASSERTION | 마지막 커밋 2024-04-02 | 0.12.10b0 (2023-08-02, 베타) | 분류자 ≤3.9 | [GH](https://github.com/matplotlib/mplfinance), [PyPI](https://pypi.org/project/mplfinance/) |
| matplotlib | 범용 플롯, PDF 백엔드 | 23,427 | 자체 라이선스(PyPI 표기 "License agreement for matplotlib…") | push 2026-11-07 | 3.11.2 (2026-09-11) | ≥3.11 | [GH](https://github.com/matplotlib/matplotlib), [PyPI](https://pypi.org/project/matplotlib/) |
| plotly | 대화형 시각화 | 18,879 | MIT | push 2026-11-06 | 7.1.0 (2026-09-15) | ≥3.8 | [GH](https://github.com/plotly/plotly.py), [PyPI](https://pypi.org/project/plotly/) |
| Kaleido | plotly 정적 내보내기(png/svg/pdf 등) | 504 | MIT | 커밋 2026-10-31 | 1.5.0 (2026-10-06) | ≥3.9 | [GH](https://github.com/plotly/Kaleido), [PyPI](https://pypi.org/project/kaleido/) |
| TradingView Lightweight Charts | HTML5 금융 차트(JS) | 17,795 | Apache-2.0 + NOTICE | 커밋 2026-11-06 | (npm, 미확인) | 해당 없음 | [GH](https://github.com/tradingview/lightweight-charts) |
| lightweight-charts-python | 위 라이브러리의 Python 래퍼 | 2,169 | MIT | 커밋 2024-09-28 | 2.1 (2024-09-28) | ≥3.8 | [GH](https://github.com/louisnw01/lightweight-charts-python), [PyPI](https://pypi.org/project/lightweight-charts/) |
| WeasyPrint | 문서 → PDF ("The Awesome Document Factory") | 9,762 | BSD-3-Clause | push 2026-11-05 | 70.0 (2026-09-08) | ≥3.10 | [GH](https://github.com/Kozea/WeasyPrint), [PyPI](https://pypi.org/project/weasyprint/) |
| ReportLab | PDF 툴킷 | 미확인 | BSD | 미확인 | 5.1.0 (2026-10-22) | ≥3.9,<4 | [PyPI](https://pypi.org/project/reportlab/) |
| fpdf2 | "Simple & fast PDF generation for Python" | 미확인 | LGPL-3.0-only | 미확인 | 2.9.0 (2026-10-29) | ≥3.11 | [PyPI](https://pypi.org/project/fpdf2/) |

- **mplfinance:** "matplotlib utilities for the visualization, and visual analysis, of financial data"입니다. matplotlib과 pandas가 필요합니다. — [README](https://github.com/matplotlib/mplfinance/blob/master/README.md)
- **matplotlib PdfPages:** 클래스 docstring이 "A multi-page PDF file."입니다. 즉 matplotlib만으로 여러 장짜리 PDF를 만들 수 있습니다. — [backend_pdf.py](https://github.com/matplotlib/matplotlib/blob/main/lib/matplotlib/backends/backend_pdf.py)
- **Kaleido v1:** "As of version 1.0.0, Kaleido requires Chrome to be installed." Chrome이 없으면 `kaleido_get_chrome` 명령이나 `kaleido.get_chrome_sync()`로 설치합니다. Kaleido v1을 쓰려면 "Plotly.py v6.1.1 or later"가 필요합니다. — [Kaleido src/py/README](https://github.com/plotly/Kaleido/blob/master/src/py/README.md)
- **Freqtrade 차트:** 내장 차트는 Plotly 기반입니다. 이 중 `plotly` 인자는 freq-ui에서 동작하지 않습니다. — [docs/plotting.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/plotting.md)
- **TradingView Lightweight Charts:**
  - "one of the smallest and fastest financial HTML5 charts"입니다. 플러그인으로 확장할 수 있습니다. 저장소에 Claude Code와 Codex용 "Agent Skills" 2개가 들어 있습니다. — [README](https://github.com/tradingview/lightweight-charts/blob/master/README.md)
  - LICENSE는 Apache-2.0입니다. 4(d)항에 따라 파생물은 NOTICE 파일의 attribution을 포함해야 합니다. NOTICE 내용은 "TradingView Lightweight Charts™ Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/"입니다. — [LICENSE](https://github.com/tradingview/lightweight-charts/blob/master/LICENSE), [NOTICE](https://github.com/tradingview/lightweight-charts/blob/master/NOTICE)
- **lightweight-charts-python:** README가 밝히는 지원 환경은 "Jupyter Notebooks, PyQt6, PyQt5, PySide6, wxPython, Streamlit, and asyncio"입니다. 헤드리스 이미지 내보내기에 대한 언급은 README에 없습니다. — [README](https://github.com/louisnw01/lightweight-charts-python/blob/main/README.md)
- **Jesse 차트:** 대화형 차트에 캔들, 지표, 수평 레벨, 주문, 체결 거래를 동기화해서 보여 줍니다. 백테스트, 페이퍼, 라이브에서 모두 씁니다. — [README](https://github.com/jesse-ai/jesse/blob/master/README.md)
- **텔레그램 크기 제한:** 사진은 10MB, 일반 파일(문서) 업로드는 50MB, 캡션은 1024자, 메시지는 4096자입니다. PTB가 Bot API 제한을 상수로 담은 `constants.py` 기준입니다. — [PTB constants.py](https://github.com/python-telegram-bot/python-telegram-bot/blob/master/src/telegram/constants.py)

### Inferences
- **시간별 리포트 기본안:**
  - matplotlib으로 1h 캔들 PNG를 만듭니다. 이미 의존 중인 pandas와 numpy만으로 캔들 몸통과 꼬리를 그릴 수 있습니다.
  - PNG는 `sendPhoto`로 보냅니다(캡션 1024자 이내 요약).
  - 상세 리포트는 `PdfPages`나 fpdf2로 PDF를 만들어 `sendDocument`로 보냅니다.
  - 이렇게 하면 Chrome이나 브라우저 의존성이 없습니다.
- **mplfinance 위험:** 프로젝트가 pandas 3.0.6과 numpy 2.4.6을 씁니다. 2023년 릴리스인 mplfinance와 호환되는지 사전 테스트가 필요합니다. 깨지면 직접 그리는 편이 유지보수에 유리합니다.
- **plotly + Kaleido:** 작은 서버에서는 Chrome 설치와 업데이트가 운영 부담이 됩니다. 대화형 HTML이 필요할 때만 쓰는 게 좋습니다.
- **lightweight-charts:** 웹 대시보드용으로 적합합니다. 텔레그램 PNG용으로는 헤드리스 브라우저가 필요해 과합니다. 공개 웹에 쓰면 NOTICE와 attribution을 지켜야 합니다.
- **LLM 비전 입력:** 같은 차트 PNG를 그대로 재사용할 수 있습니다. 사례 하나는 차트를 512×512로 줄여서 보냅니다(6장 참고).

### Gaps
- Telegram이 `sendPhoto` 이미지를 재압축하는지, `sendDocument`와 화질이 어떻게 다른지는 공식 문서로 확인하지 못했습니다. core.telegram.org는 이 세션에서 차단됐습니다.
- mplfinance가 pandas 3.x, matplotlib 3.11에서 동작하는지는 미검증입니다.
- WeasyPrint의 시스템 의존성(Pango 등)과 Mac 설치 절차는 이번에 확인하지 못했습니다.
- fpdf2와 ReportLab의 GitHub 별 수는 미확인입니다.

## 4. 텔레그램 봇 구현: 라이브러리, 공개 시그널 봇, 차트 전송, 스케줄링, 사용자 인증, 속도 제한, 토큰 보안

### Takeaway
python-telegram-bot(PTB) 22.x를 유지하면 됩니다. 이 프로젝트가 이미 22.8을 쓰고 있습니다. PTB는 LGPL-3.0이고 Python ≥3.10이며, JobQueue(APScheduler)와 AIORateLimiter를 extra로 제공합니다. 단일 사용자 봇이라면 시간당 메시지 몇 개 수준이므로 속도 제한(채팅당 약 1msg/s, 그룹당 약 20msg/min)은 문제가 되지 않습니다. 보안의 핵심은 세 가지입니다.
- 토큰은 파일이나 환경변수로만 다룹니다.
- 허용된 user_id나 chat_id에서 온 업데이트만 처리합니다.
- gitleaks의 Telegram 토큰 규칙을 유지합니다.

### Cited Findings

#### 라이브러리

| 라이브러리 | 별 | 라이선스 | 최신 릴리스 | Python | 출처 |
|---|---|---|---|---|---|
| python-telegram-bot | 29,564 | LGPL-3.0 (README, PyPI). GitHub 자동감지는 "GPL-3.0"로 표시 | 22.8 (2026-06-12), 마지막 커밋 2026-11-01 | ≥3.10 (분류자 3.10~3.15) | [GH](https://github.com/python-telegram-bot/python-telegram-bot), [PyPI](https://pypi.org/project/python-telegram-bot/) |
| aiogram | 5,917 | MIT | 3.31.0 (2026-08-26), 마지막 커밋 2026-11-01 | PyPI ≥3.10,<3.15. dev-3.x README는 "Python 3.11+" | [GH](https://github.com/aiogram/aiogram), [PyPI](https://pypi.org/project/aiogram/) |
| pyTelegramBotAPI | 8,793 | GPL-2.0 | 4.37.1 (2026-10-17) | ≥3.11 | [GH](https://github.com/eternnoir/pyTelegramBotAPI), [PyPI](https://pypi.org/project/pyTelegramBotAPI/) |
| APScheduler (PTB JobQueue 백엔드) | 7,690 | MIT | 3.11.3 (2026-06-28) | ≥3.8 | [GH](https://github.com/agronholm/apscheduler), [PyPI](https://pypi.org/project/APScheduler/) |

- **PTB 라이선스:** "applications that use the library don't have to be [LGPL]". 라이브러리를 수정하거나 정적 링크한 파생물만 LGPL-3로 재배포해야 합니다. — [README.rst](https://github.com/python-telegram-bot/python-telegram-bot/blob/master/README.rst)
- **PTB extras:** — [README.rst](https://github.com/python-telegram-bot/python-telegram-bot/blob/master/README.rst)
  - `[job-queue]`: APScheduler>=3.10.4,<3.12.0
  - `[rate-limiter]`: aiolimiter, `AIORateLimiter`
  - `[webhooks]`: tornado
  - `[socks]`, `[http2]`, `[callback-data]`
  - `[ext]`: telegram.ext 관련 extra를 한 번에 설치합니다.
- **aiogram:** asyncio와 aiohttp 기반이며, 타입힌트, FSM, 라우터, 미들웨어, magic filters, I18n을 제공합니다. "Supports Telegram Bot API 10.3"이라고 밝힙니다. — [README.rst](https://github.com/aiogram/aiogram/blob/dev-3.x/README.rst)

#### 차트 전송 (sendPhoto/sendDocument) 관련 한도
PTB `constants.py`가 Bot API 제한을 코드로 담고 있습니다. — [PTB constants.py](https://github.com/python-telegram-bot/python-telegram-bot/blob/master/src/telegram/constants.py)

| 항목 | 값 |
|---|---|
| `PHOTOSIZE_UPLOAD` | 10MB |
| `FILESIZE_UPLOAD` | 50MB |
| `FILESIZE_DOWNLOAD` | 20MB |
| `FILESIZE_UPLOAD_LOCAL_MODE` | 2000MB |
| 메시지 `MAX_TEXT_LENGTH` | 4096 |
| `CAPTION_LENGTH` | 1024 |
| 미디어 그룹 | 2~10개 |

- **자체 Bot API 서버:** tdlib/telegram-bot-api로 직접 운영하면 한도가 커집니다. "Upload files up to 2000 MB", "Download files without a size limit", "Use any port for the webhook", "Set max_webhook_connections up to 100000". — [tdlib/telegram-bot-api](https://github.com/tdlib/telegram-bot-api)

#### 스케줄링
- **설치:** "Since v20, you must install PTB with the optional requirement `job-queue`", 즉 `pip install python-telegram-bot[job-queue]`입니다. — [PTB wiki: JobQueue](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Extensions---JobQueue)
- **메서드:** `run_once`, `run_repeating`(예: `interval=60, first=10`), `run_daily`, `run_monthly`가 있습니다. 백엔드는 APScheduler입니다. — [PTB wiki: JobQueue](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Extensions---JobQueue)

#### 사용자 인증 (허용목록)
- **봇 전체 차단 패턴:** `update.effective_user.id`가 허용목록에 없으면 거절 메시지를 보내고 `raise ApplicationHandlerStop`으로 이후 처리를 막습니다. 특정 기능만 막으려면 `filters.Chat`이나 `filters.User`를 핸들러에 붙입니다. — [PTB wiki: design patterns](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Frequently-requested-design-patterns)
- **Freqtrade 방식:** `authorized_users`를 쓰고, 빈 리스트면 아무도 제어할 수 없습니다. — [docs/telegram-usage.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/telegram-usage.md)

#### 속도 제한
- **공식 FAQ 인용 (PTB 위키):** "~30 messages/second for all ordinary messages and ~20 messages/minute for group messages"입니다. 또한 "Telegram does *not* document the precise limits". 한도에 걸리면 `RetryAfter` 오류가 나고, 무시하고 계속 재시도하면 일시 차단될 수 있습니다. — [PTB wiki: Avoiding flood limits](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits)
- **PTB 상수:** `MESSAGES_PER_SECOND_PER_CHAT = 1`, `MESSAGES_PER_SECOND = 30`, `MESSAGES_PER_MINUTE_PER_GROUP = 20`, `PAID_MESSAGES_PER_SECOND = 1000`. — [PTB constants.py](https://github.com/python-telegram-bot/python-telegram-bot/blob/master/src/telegram/constants.py)
- **내장 레이트리미터:** v20 이후 `BaseRateLimiter`가 있습니다(`ExtBot`에서만 동작). — [PTB wiki: Avoiding flood limits](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits)
- **유료 브로드캐스트:** `allow_paid_broadcast`(Telegram Stars를 내고 초당 최대 1000건)는 PTB 레이트리미터가 자동으로 고려하지 않습니다.
  - 위키는 이 기능을 "Bot API 7.1 … october-31-2024", "PTB v27.1"로 표기합니다. 링크 대상은 PTB v21.7 changelog여서 표기 오타로 보입니다. — [PTB wiki: Avoiding flood limits](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits)

#### 토큰과 비밀 보안
- **gitleaks 탐지 규칙:** 기본 설정에 `id = "telegram-bot-api-token"`이 있습니다. "Detected a Telegram Bot API Token, risking unauthorized bot operations and message interception"이라는 설명과 함께 `telegr` 키워드와 토큰 패턴 정규식으로 잡습니다. — [gitleaks.toml](https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml)
- **Freqtrade:** 환경변수(`FREQTRADE__…`)로 비밀을 설정 파일 밖에 둡니다. 키는 `$(cat file)`로 파일에서 읽습니다. — [docs/configuration.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/configuration.md), [docs/exchanges.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/exchanges.md)
- **pycryptobot 경고:** README가 사칭 사기를 경고합니다. "Never share your API keys with anyone", "Don't let anyone run your bots for you", "Telegram admins will never message you first". — [README](https://github.com/whittlem/pycryptobot/blob/main/README.md)

#### 공개 시그널·분석 봇 사례 (GitHub)
- **Freqtrade:** 텔레그램 RPC 제어와 알림이 내장돼 있습니다(1장).
- **Jesse:** 라이브와 페이퍼 알림을 Telegram, Slack, Discord로 보냅니다. — [README](https://github.com/jesse-ai/jesse/blob/master/README.md)
- **OctoBot:** 별 6,906, GPL-3.0, 마지막 커밋 2026-10-07입니다. PyPI 2.1.1(2026-03-29)은 Python ≥3.12이고, PyPI 요약은 "Cryptocurrencies alert / trading bot"입니다. — [GH](https://github.com/Drakkar-Software/OctoBot), [PyPI](https://pypi.org/project/octobot/)
  - "OctoBot can also be connected to a Telegram bot, turning OctoBot into a Telegram trading bot"입니다. — [README](https://github.com/Drakkar-Software/OctoBot/blob/master/README.md)
  - OpenAI나 Ollama 모델로 거래하는 "AI connectors"가 있습니다. — [README](https://github.com/Drakkar-Software/OctoBot/blob/master/README.md)
  - Binance, Coinbase, MEXC, Hyperliquid를 포함해 15개 이상 거래소를 지원합니다. — [README](https://github.com/Drakkar-Software/OctoBot/blob/master/README.md)
- **CryptoSignal/Crypto-Signal:** 별 5,657, MIT입니다. RSI, Ichimoku 등으로 기술적 분석을 자동화하는 CLI입니다. 마지막 커밋이 2022-08-09로 사실상 정지 상태입니다. — [GH](https://github.com/CryptoSignal/Crypto-Signal), [README](https://github.com/CryptoSignal/Crypto-Signal/blob/master/README.md)
- **pycryptobot:** 별 2,059, Apache-2.0입니다. 기본 브랜치 마지막 커밋은 2024-03-04(v8.2.4)입니다. — [GH](https://github.com/whittlem/pycryptobot)
- **fabston/TradingView-Webhook-Bot:** 별 1,898, MIT입니다. "listens to TradingView alerts via webhooks"입니다. 기본 브랜치 마지막 커밋은 2024-05-01입니다. — [GH](https://github.com/fabston/TradingView-Webhook-Bot), [README](https://github.com/fabston/TradingView-Webhook-Bot/blob/master/README.md)
- **LLM 기반 분석 프레임워크(텔레그램 내장은 아님):**
  - TradingAgents: 별 121,068, Apache-2.0, 마지막 커밋 2026-11-04입니다. "designed for research purposes"이고 Python 3.11+이며, OpenAI, Anthropic, Gemini, Ollama 등 여러 제공자를 지원합니다. — [GH](https://github.com/TauricResearch/TradingAgents), [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
  - ai-hedge-fund: 별 64,528, MIT입니다. "proof of concept … for **educational** purposes only", "the system does not actually make any trades"입니다. — [GH](https://github.com/virattt/ai-hedge-fund), [README](https://github.com/virattt/ai-hedge-fund/blob/main/README.md)

#### 이 프로젝트의 현재 상태 (로컬 저장소 관찰)
- `requirements.txt`에 `python-telegram-bot==22.8`, `httpx==0.28.1`, `pandas==3.0.6`, `numpy==2.4.6`, `anthropic==1.9.0`이 있습니다. APScheduler는 없어서 JobQueue extra가 설치되지 않은 상태입니다. 차트 라이브러리(matplotlib 등)도 없습니다. — 로컬 파일 `/home/user/1111/requirements.txt`
- `.venv` Python은 3.11.18입니다. `bot/telegram_ui.py`가 존재합니다. — 로컬 `/home/user/1111/.venv/bin/python --version`, `/home/user/1111/bot/`

### Inferences
- **라이브러리:** PTB를 유지하는 게 좋습니다. 이미 의존 중이고, LGPL이라 앱 코드에 전염되지 않습니다. aiogram으로 바꿀 이유는 적습니다.
- **시간별 리포트 스케줄:** 두 가지 방법이 있습니다. 둘 다 정각 직후에 캔들이 확정됐는지 확인하는 처리가 필요합니다.
  - `run_repeating(interval=3600, first=정각+수초)`. `[job-queue]` extra를 추가하고 해시 고정 requirements를 갱신해야 합니다.
  - 기존 asyncio 루프에서 직접 스케줄합니다.
- **메시지 구성:** 1회 리포트를 "사진 1장 + PDF 1개 + 텍스트"로 보내도 채팅당 초당 1건 권고만 지키면 충분합니다. `RetryAfter` 처리는 넣어 두는 게 좋습니다.
- **인증:** 단일 사용자라면 허용 user_id 하나와 chat_id 고정으로 충분합니다. 그 밖의 업데이트는 무시하는 미들웨어(`ApplicationHandlerStop`)를 두면 됩니다. Freqtrade처럼 "수신만 허용, 명령은 제한" 모델도 참고할 만합니다.
- **보안:** CI gitleaks 기본 규칙이 Telegram 토큰을 잡으므로 현행 원칙(파일에서만 읽기, 로그에 남기지 않기)과 잘 맞습니다. 토큰이 유출되면 BotFather에서 재발급(revoke)해야 합니다. 다만 공식 절차 문서는 이번 세션에서 확인하지 못했습니다.

### Gaps
- 공식 Telegram Bot API 문서(core.telegram.org/bots/api, /bots/faq, /bots/features)는 이 세션의 네트워크 정책 때문에 조회가 차단됐습니다. 한도는 PTB 상수, PTB 위키, tdlib README로 대신 확인했습니다. core.telegram.org를 세션 네트워크 설정에서 허용해야 원문을 검증할 수 있습니다.
- BotFather 토큰 재발급(revoke) 절차의 공식 원문은 확인하지 못했습니다.
- LLM과 텔레그램을 결합한 공개 저장소 중 활발히 유지되는 소규모 단일 사용자 사례(별 수, 커밋 날짜 포함)는 추가 확인이 필요합니다. 아래 6장의 블로그 사례는 저장소 상태를 확인하지 못했습니다.

## 5. 데이터 소스: Binance 공개 REST·웹소켓, data.binance.vision 대량 과거 데이터, CCXT, 함정(속도 제한, HTTP 451, 데이터 공백)

### Takeaway
과거 1h 캔들은 **data.binance.vision**의 일/월 zip 파일을 쓰고 `.CHECKSUM`으로 검증하는 게 가장 효율적입니다. 최신분은 **`GET /fapi/v1/klines`**로 증분 수집합니다(weight는 LIMIT에 따라 1/2/5/10). 함정은 네 가지입니다.
1. **지역 차단:** 미국 등 제한 지역 서버 IP에서는 HTTP 451("restricted location")이 납니다.
2. **속도 제한:** 429 다음에 무시하고 계속 요청하면 418(IP 자동 차단)이 됩니다.
3. **스팟 타임스탬프 단위:** 2025-01-01부터 스팟 데이터는 마이크로초입니다.
4. **SDK 교체:** 구형 선물 커넥터가 deprecated되고 모듈형 SDK로 바뀌었습니다.

### Cited Findings

#### data.binance.vision (binance-public-data)
- **업데이트 주기:** 공개 데이터를 `daily`와 `monthly` 파일로 제공합니다. "new `daily` data becoming available the next day and new `monthly` data at the first monday of the month"입니다. — [binance-public-data README](https://github.com/binance/binance-public-data)
- **선물 데이터:** USD-M과 COIN-M을 지원합니다. USD-M klines 파일 데이터는 "from `/fapi/v1/klines` API endpoint"이고 12개 컬럼입니다. — [binance-public-data README](https://github.com/binance/binance-public-data)
  - 컬럼: Open time, OHLC, Volume, Close time, Quote asset volume, Number of trades, Taker buy base/quote volume, Ignore.
- **함정, 스팟 타임스탬프 단위:** "The timestamp for SPOT Data from January 1st 2025 onwards will be in microseconds." — [binance-public-data README](https://github.com/binance/binance-public-data)
- **간격과 무결성:** — [binance-public-data README](https://github.com/binance/binance-public-data)
  - 지원 간격은 `1s`~`1mo`입니다. 대소문자를 구분하지 않는 파일시스템 때문에 `1M` 대신 `1mo`를 씁니다.
  - 각 zip 옆에 `.CHECKSUM` 파일이 있습니다.
  - python과 shell 헬퍼 스크립트를 제공합니다.
  - URL 예: `https://data.binance.vision/data/spot/monthly/klines/ADABKRW/1h/ADABKRW-1h-2020-08.zip`
- **저장소 상태:** 별 2,564, 라이선스 표기 없음(null), 마지막 커밋 2026-10-16입니다. — [GH](https://github.com/binance/binance-public-data)

#### REST (USDⓈ-M 선물)
- **Binance 공식 모듈형 SDK docstring:** `GET /fapi/v1/klines`에서 "Klines are uniquely identified by their open time."이고, "If startTime and endTime are not sent, the most recent klines are returned."입니다. — [market_data_api.py](https://github.com/binance/binance-connector-python/blob/master/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py)

  Weight는 LIMIT 값에 따라 다릅니다(같은 출처).

  | LIMIT | weight |
  |---|---|
  | [1,100) | 1 |
  | [100,500) | 2 |
  | [500,1000] | 5 |
  | >1000 | 10 |

- **최대 limit 값 충돌:** deprecated된 구형 커넥터 docstring은 "limit … Default 500, max 1000"입니다. — [um_futures/market.py](https://github.com/binance/binance-futures-connector-python/blob/main/binance/um_futures/market.py)
  - 그러나 신형 SDK의 weight 표에는 ">1000" 구간이 있어서, 1000보다 큰 limit도 허용되는 것으로 보입니다. 최신 최대값은 공식 문서에서 확인해야 합니다(Gaps).
- **SDK 교체:**
  - 구형 커넥터: "Binance Futures Public API Connector Python - DEPRECATED … Please use the new modular connector repository: binance-connector-python"입니다. 마지막 커밋은 2025-07-18입니다. — [binance-futures-connector-python](https://github.com/binance/binance-futures-connector-python)
  - 신형 모듈형 SDK는 `binance-sdk-derivatives-trading-usds-futures` 등 상품별 패키지입니다. — [binance-connector-python README](https://github.com/binance/binance-connector-python)
  - 최신은 18.3.0(2026-11-06)이고 Python ≥3.11,<3.16입니다. — [PyPI](https://pypi.org/project/binance-sdk-derivatives-trading-usds-futures/)
- **HTTP 상태코드 (스팟 문서 기준):** — [binance-spot-api-docs rest-api.md](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md)
  - 403: WAF 규칙 위반
  - 409: cancelReplace 부분 성공
  - 429: 요청 한도 초과
  - 418: 429 이후에도 계속 요청해 IP가 자동 차단됨

#### 웹소켓
- **스팟 (stream.binance.com):** — [web-socket-streams.md](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md)
  - 연결은 24시간만 유효합니다("expect to be disconnected at the 24 hour mark").
  - 서버가 20초마다 ping을 보내고, pong이 필요합니다.
  - 수신 메시지는 초당 5개로 제한됩니다.
  - 연결당 최대 1024 스트림입니다.
  - "300 connections per attempt every 5 minutes per IP"입니다.
- **선물 SDK:** 기본 WS URL은 `wss://fstream.binance.com`입니다. 원문: "The WebSocket connection is automatically renewed for both WebSocket API and WebSocket Streams connections, before the 24 hours expiration of the API key." — [USDS futures SDK docs](https://github.com/binance/binance-connector-python/tree/master/clients/derivatives_trading_usds_futures/docs)

#### HTTP 451 지역 차단
- **사례 (CCXT 이슈 #15917, 2022-12-02):** `api.binance.com/api/v3/exchangeInfo`가 HTTP 451을 돌려줬습니다. 본문은 "Service unavailable from a restricted location according to 'b. Eligibility'"입니다. 메인테이너는 유사 이슈 #15891로 안내하고 닫았습니다. — [ccxt#15917](https://github.com/ccxt/ccxt/issues/15917)
- **Freqtrade 문서:** "Binance restricts API access regarding the server country"이고, 예로 든 차단국(전체 목록 아님)은 캐나다, 말레이시아, 네덜란드, 미국입니다. — [docs/exchanges.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/exchanges.md)
- **사용자 보고 (검색 요약 기준, 원문 미확인):** — [Linode community](https://www.linode.com/community/questions/23972/linode-and-binancecom), [Railway](https://station.railway.com/questions/deployment-is-crashing-7b190d57), [Google dev forum](https://discuss.google.dev/t/google-cloud-function-ip-address-setting/97868)
  - 미국 리전 Linode 서버는 막히고 프랑크푸르트 서버는 됐습니다.
  - GCP 외부 IP는 리전과 관계없이 Mountain View로 잡혀 차단됐습니다.
  - Railway는 4개 리전 모두 차단됐습니다.
  - 정적 IP 프록시를 권하는 글은 판매사 블로그입니다. — [QuotaGuard](https://quotaguard.com/blog/binance-futures-api-static-ip)
- **이 세션에서 직접 관찰:** 이 클라우드 샌드박스에서는 `api.binance.com`, `fapi.binance.com`, `data.binance.vision` 모두 연결 자체가 실패했습니다(HTTP 451이 아니라 세션 네트워크 정책 때문). 프로젝트 `bot/marketdata.py` 주석에도 "이 컨테이너에서는 접속 불가"라고 적혀 있습니다. — 로컬 `/home/user/1111/bot/marketdata.py`

#### CCXT와 커뮤니티 SDK
- **CCXT:** 별 44,784, MIT, 4.5.92(2026-11-04), Python ≥3.10입니다. 공개·비공개 REST와 WebSocket을 통합하고, 인증 거래소에 binance가 있습니다. — [README](https://github.com/ccxt/ccxt/blob/master/README.md), [PyPI](https://pypi.org/project/ccxt/)
- **python-binance (커뮤니티):** 별 7,222, MIT, 1.0.37(2026-06-08)입니다. — [GH](https://github.com/sammchardy/python-binance), [PyPI](https://pypi.org/project/python-binance/)
- **FinRL-Meta:** 데이터 처리기 목록에 Binance와 CCXT가 있습니다. — [README](https://github.com/AI4Finance-Foundation/FinRL-Meta/blob/master/README.md)

#### 이 프로젝트의 현재 구현 (로컬 관찰)
- `bot/config.py`가 `ALLOWED_MARKET_BASE_URLS = frozenset({"https://fapi.binance.com"})`로 접속 대상을 허용목록으로 묶습니다.
- `bot/marketdata.py`는 `/fapi/v1/klines`, `/fapi/v1/fundingRate`, `/fapi/v1/time`을 키와 서명 없이 httpx로 호출합니다.
- 출처: 로컬 `/home/user/1111/bot/config.py`, `/home/user/1111/bot/marketdata.py`

### Inferences
- **수집 흐름:**
  1. data.binance.vision에서 `futures/um` 월간 zip을 받아 1h 캔들의 긴 이력을 채웁니다. 최근 며칠은 일간 zip으로 채웁니다.
  2. 직전 몇 시간은 REST klines로 채웁니다.
  3. 매시 정각 이후 마지막 확정 캔들을 REST로 받습니다.
  - limit을 1000 이하로 두면 호출당 weight가 5 이하라서 시간당 1~2회 호출은 한도와 거리가 멉니다.
- **허용목록 갱신:** data.binance.vision을 쓰려면 `ALLOWED_MARKET_BASE_URLS` 같은 허용목록에 추가하고 테스트해야 합니다. 체크섬 검증 실패 시 거부하는 처리도 넣어야 합니다.
- **데이터 품질 검사:** 키는 "open time"입니다. 1h 간격 연속성(빠진 시각), 중복, 미확정 캔들(현재 시각보다 close time이 뒤)을 검사하는 코드가 필요합니다. 스팟 데이터를 섞을 때는 2025년 이후 마이크로초 단위에 주의해야 합니다.
- **서버 위치:** 작은 서버를 빌린다면 미국 리전과 GCP 같은 일부 클라우드는 451 위험이 큽니다. 한국 맥에서 직접 돌리거나, 허용 지역 서버를 써야 합니다. 최신 제한 목록은 Binance 약관에서 확인해야 합니다.
- **SDK 의존성:** 공식 모듈형 SDK는 Python ≥3.11이라 현재 venv에서 쓸 수 있습니다. 그러나 이미 httpx로 직접 호출하고 있으므로 의존성을 늘릴 필요는 적습니다.

### Gaps
- Binance 공식 개발자 문서(developers.binance.com)는 이 세션에서 차단됐습니다. 그래서 다음 항목을 공식 원문으로 확인하지 못했습니다. 세션 네트워크 설정에서 developers.binance.com을 허용해야 검증할 수 있습니다.
  - USDⓈ-M 선물 IP 한도(분당 request weight 수치)
  - klines 최대 limit(1000인지 1500인지)
  - 선물 웹소켓 수신 메시지 한도와 연결당 스트림 수
  - 451 코드의 공식 설명
- data.binance.vision 선물 경로의 정확한 디렉터리 구조(`data/futures/um/...`)는 README에서 텍스트로 확인하지 못했습니다(README 예시는 스팟 경로).
- Binance 캔들 데이터 공백(점검 시간 등)의 공식 목록이나 통계는 찾지 못했습니다.
- 한국 IP가 Binance 제한 지역인지는 공식적으로 확인하지 못했습니다.

## 6. 실사용 경험 보고: Freqtrade/FreqAI 또는 LLM + 텔레그램 봇을 만든 사람들의 후기 (성공, 실패, 유지보수 부담)

### Takeaway
신뢰할 만한 정량 후기는 드뭅니다. 반복해서 나오는 교훈은 다음과 같습니다.
1. 교차검증 정확도와 라이브 정확도 사이에 큰 격차가 생깁니다(예: 75%가 52%로).
2. LLM 분석은 그럴듯하게 들려도 믿기 어렵습니다. 강세·약세 논거를 강제로 나누는 구조화와 과거 결과 피드백이 필요합니다.
3. 호출 비용과 지연이 문제가 됩니다.
4. 백테스트 체결 가정이 실제와 다릅니다.

유지보수 부담은 주로 외부 변화에서 옵니다. 이번 조사에서 관찰된 예는 SDK deprecated, Chrome 의존 추가, Python 하한 상향, 모델 라이브러리 지원 중단, 타임스탬프 단위 변경입니다.

### Cited Findings

#### FreqAI 관련 후기
- **DEV Community 글 "How I built a profitable FreqAI plugin using institutional ML techniques":** 교차검증 정확도 약 75%가 라이브에서 52%로 떨어졌고, 수정 후 63%가 됐다고 보고합니다. 저자가 자기 플러그인을 홍보하는 글이라 수치는 신중히 봐야 합니다(검색 요약 기준, dev.to 본문은 세션에서 차단). — [dev.to](https://dev.to/stefano_viana_dda882cfae5/how-i-built-a-profitable-freqai-plugin-using-institutional-ml-techniques-1l9k)
- **같은 주제의 글 "The Problem with Default FreqAI":** 미러 사이트에서 검색됐습니다. 본문은 확인하지 못했습니다. — [techfordev mirror](https://techfordev.netlify.app/articles/3515208)
- **Reddit 과적합 토론 (제3자 미러, 검색 요약 기준):** 어떤 조언이 어느 스레드에서 나왔는지는 요약에서 확정할 수 없습니다. 아래 스냅샷 묶음 전체를 출처로 봐야 합니다. — [snapshot 1](https://reddit.sentinel-team.org/posts/1pku05q/snapshots/2025-12-13T09%3A41%3A11.995295Z), [snapshot 2](https://reddit.sentinel-team.org/posts/1qif9i9/snapshots/2026-01-21T15%3A10%3A15.323814Z), [snapshot 3](https://reddit.sentinel-team.org/posts/1qpkyop/snapshots/2026-02-21T05%3A30%3A03.124646Z), [snapshot 4](https://reddit.sentinel-team.org/posts/1ry6h3y/snapshots/2026-03-20T16%3A07%3A03.461719Z)
  - 파라미터 민감도 테스트를 권합니다. 선택값 근처에서 결과가 크게 바뀌면 안 됩니다.
  - 롤링 윈도 백테스트로 기간별 안정성을 보라고 합니다.
  - 지정가 주문을 미리 체결된 것으로 취급하는 백테스트 오류를 경고합니다.
  - 소액이나 페이퍼로 먼저 운영하고, 실제 체결과 백테스트 가정을 비교하라고 권합니다.
  - 원 Reddit 링크가 아니라 미러이므로 신뢰도는 낮습니다.
- **공식 문서가 경고하는 실패 지점 (1장 참고):** 백테스트 가정, continual_learning 과적합, 예제는 운영용이 아님, lookahead/recursive 편향. — [docs/backtesting.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/backtesting.md), [docs/freqai-parameter-table.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-parameter-table.md)

#### LLM + 텔레그램 분석 봇 후기 (모두 검색 요약 기준, dev.to 본문은 세션에서 차단)
- **검색 요약에 나온 교훈:** 요약은 이 교훈들을 "한 빌더", "같은 빌더", "다른 프로젝트"로만 표현했습니다. 그래서 어떤 교훈이 어느 글에서 나왔는지는 확정할 수 없습니다. 아래 글 묶음 전체를 출처로 봐야 합니다. — [dev.to/qrak](https://dev.to/qrak/-stop-trading-like-its-1999-an-llm-crypto-bot-that-sees-charts-remembers-trades-and-learns-1cd1), [dev.to/ik_park](https://dev.to/ik_park_0d77e14c7c6f1cb70/how-i-automated-crypto-pattern-analysis-with-telegram-bots-and-deep-learning-20mb), [dev.to/pythonbotdev](https://dev.to/pythonbotdev/i-built-a-multi-agent-ai-trading-signal-bot-for-okx-futures-in-python-1i2c), [dev.to/dineshstack](https://dev.to/dineshstack/how-i-built-an-ai-crypto-trading-bot-with-claude-ai-426e), [dev.to/mfs_corp](https://dev.to/mfs_corp/how-i-built-a-telegram-bot-for-real-time-crypto-alerts-and-you-can-too-26io)
  1. **LLM 신뢰성:** 초기 LLM이 "beautiful-sounding analysis that was hard to trust"를 만들었습니다. 그래서 강세 논거, 약세 논거, 결정 순서로 구조화했습니다.
  2. **과거 거래 기억:** 같은 빌더가 비슷한 과거 거래 5건과 그 결과를 프롬프트에 넣었습니다.
  3. **비용:** 분석 1회에 API 호출이 5회 이상 들어서 더 가벼운 설계로 바꿨습니다.
  4. **실수에서 배우기:** 다른 프로젝트는 직전 결정을 실제 시장과 비교해 채점하고, 실수를 한 줄짜리 교훈으로 바꿉니다.
  5. **캔들 lookback:** 단기 패턴에는 3캔들, 스윙에는 30캔들 이상이 낫습니다. 교차 자산 검증도 중요합니다.
- **OKX 다중 에이전트 봇 (제목상 이 글로 보임):** OKX 무기한 60개 페어를 5분마다 스캔하고, 패턴을 0~10점으로 매겨 텔레그램 시그널을 보냅니다. 추론은 LLM, 차트 분석은 별도 비전 모델이 맡습니다. — [dev.to/pythonbotdev](https://dev.to/pythonbotdev/i-built-a-multi-agent-ai-trading-signal-bot-for-okx-futures-in-python-1i2c)
- **n8n 워크플로 템플릿:** 차트 이미지를 512×512로 줄여 비전 모델(GPT-4 Vision 등)에 넣고 결과를 텔레그램으로 보냅니다. — [growwstacks](https://growwstacks.com/workflows/analyze-stock-charts-with-gpt-4-vision-and-send-results-via-telegram), [neura.market](https://www.neura.market/workflow/ai-stock-chart-analyzer-gpt-4-vision-telegram-bot)
- **실시간 이상 감지 모니터 구축기:** 제목에 메모리(RAM) 문제와 씨름했다는 내용이 있습니다. — [dev.to/rdin777](https://dev.to/rdin777/how-i-built-defi-sentinel-real-time-market-anomaly-monitoring-and-battling-ram-issues-6d2)
- **정량 성과는 없음:** 검색된 LLM + 텔레그램 봇 글들은 정확도나 수익성 같은 정량 성과를 제시하지 않았습니다. 모두 빌더 본인의 인상입니다(검색 요약).

#### LLM 프레임워크의 자체 경고
- **TradingAgents:** "designed for research purposes. Trading performance may vary based on … backbone language models, model temperature, trading periods …". — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **ai-hedge-fund:** "Not intended for real trading or investment", "Past performance does not indicate future results". — [README](https://github.com/virattt/ai-hedge-fund/blob/main/README.md)

#### 유지보수 부담 신호 (이번 조사에서 관찰된 변화)
- **Binance 구형 선물 커넥터 deprecated:** 마지막 커밋은 2025-07-18이고, 모듈형 SDK로 옮기라고 합니다. — [GH](https://github.com/binance/binance-futures-connector-python)
- **스팟 공개 데이터 타임스탬프:** 2025-01-01부터 마이크로초로 바뀌었습니다. — [binance-public-data](https://github.com/binance/binance-public-data)
- **Kaleido v1:** Chrome이 필요해졌고 Plotly ≥6.1.1이 필요합니다. — [Kaleido README](https://github.com/plotly/Kaleido/blob/master/src/py/README.md)
- **FreqAI:** CatBoost 지원이 2025.12에 중단됐고, Intel Mac PyTorch 지원도 중단됐습니다. — [docs/freqai-configuration.md](https://github.com/freqtrade/freqtrade/blob/develop/docs/freqai-configuration.md)
- **Freqtrade Python 하한:** 3.12로 올라갔습니다. — [PyPI](https://pypi.org/project/freqtrade/)
- **NautilusTrader:** v1에서 v2로 전환 중이고, v1은 보안 백포트만 받습니다. — [README](https://github.com/nautechsystems/nautilus_trader/blob/develop/README.md)
- **멈춘 프로젝트:** — [CryptoSignal](https://github.com/CryptoSignal/Crypto-Signal), [pycryptobot](https://github.com/whittlem/pycryptobot), [mplfinance](https://github.com/matplotlib/mplfinance), [lightweight-charts-python](https://github.com/louisnw01/lightweight-charts-python), [backtrader](https://github.com/mementum/backtrader), [finrl PyPI](https://pypi.org/project/finrl/)
  - CryptoSignal: 2022
  - pycryptobot: 2024-03
  - mplfinance: 2024-04
  - lightweight-charts-python: 2024-09
  - backtrader: 2023
  - FinRL PyPI: 2024-04
- **pandas-ta:**
  - PyPI 마지막 릴리스는 0.4.71b0(2025-09-14)이고 Python ≥3.12입니다. project_urls는 여전히 `github.com/twopirllc/pandas-ta`를 가리킵니다. — [PyPI pandas-ta](https://pypi.org/project/pandas-ta/)
  - 2026-11-07에 해당 GitHub 저장소를 익명으로 clone하고 README를 받으려 했으나 둘 다 실패했습니다(raw 404, 인증 요구). 즉 공개 접근이 안 되는 상태로 관찰됐습니다. — [github.com/twopirllc/pandas-ta](https://github.com/twopirllc/pandas-ta)
  - NumPy 2 호환 wheel을 위한 포크 `pandas-ta-openbb`가 있습니다. — [PyPI pandas-ta-openbb](https://pypi.org/project/pandas-ta-openbb/)

### Inferences
- **LLM 분석을 붙일 때 설계에 반영할 교훈:**
  - 강세·약세·결론을 나누는 구조화된 출력(JSON 스키마)
  - 과거 리포트와 실제 결과를 비교하는 자동 채점(TRIALS.md 기록 방식과 결합)
  - 호출 수를 1~2회로 제한해 비용을 관리
  - 차트 이미지는 적당한 해상도로 줄이기
  - LLM 출력은 "참고 의견"으로 표시하고 고정 규칙 신호와 분리하기
- **FreqAI 후기의 핵심(CV와 라이브의 큰 격차):** 사용자의 "규칙 고정, 새 버전은 TRIALS.md에 기록" 원칙이 바로 이 과적합을 막는 장치입니다. ML 모델을 넣는다면 다음이 필요합니다.
  - 학습 구간과 검증 구간을 시간 순으로 엄격히 분리
  - 재학습 주기와 만료 규칙을 고정
  - 모든 시도를 기록해 시도 횟수를 고려한 평가
- **유지보수 부담 줄이기:** 외부 의존성(특히 브라우저, 정체된 래퍼, 거래소 SDK)을 최소화하고, 해시 고정 requirements와 테스트로 업데이트 충격을 흡수하는 게 효과적입니다. 이 프로젝트는 이미 해시 고정 requirements를 씁니다.
- **n8n 템플릿:** 사용자 규칙상 구독 앱 자동화는 금지입니다. API 키 방식이라도 n8n까지 들일 이유는 적습니다. 파이썬 코드 안에서 anthropic SDK를 직접 호출하는 현재 구조가 약관과 단순성 면에서 낫습니다.

### Gaps
- dev.to(검색된 후기 대부분의 원문 위치)는 이 세션의 네트워크 정책으로 차단돼 본문을 직접 확인하지 못했습니다. 위 후기 내용은 검색 결과 요약에 근거합니다. dev.to를 세션 네트워크 설정에서 허용해야 원문을 검증할 수 있습니다.
- reddit.com 원문 스레드(r/algotrading, r/freqtrade)의 FreqAI 라이브 성과 후기는 직접 찾지 못했습니다. 제3자 미러만 확인했습니다.
- LLM 차트 판독 정확도에 대한 체계적 평가(논문, 벤치마크)는 이번 범위에서 찾지 못했습니다. 다른 조사자 범위일 수 있습니다.
- pandas-ta 저장소가 비공개 전환인지, 이름 변경인지, 삭제인지는 원인을 확인하지 못했습니다.

## 7. 종합: 무엇을 재사용하고 무엇을 직접 만들 것인가 (목표 질문)

### Takeaway
이 프로젝트에는 이미 자체 봇이 있습니다(PTB 22.8, httpx로 fapi 공개 REST, anthropic SDK, Python 3.11.18). 그래서 프레임워크를 교체하기보다 작은 라이브러리와 검증된 개념을 붙이는 게 맞습니다.

**재사용할 것**
- data.binance.vision + CHECKSUM (과거 캔들)
- `/fapi/v1/klines` (증분)
- PTB (JobQueue는 선택)
- matplotlib (PNG, PdfPages)
- fpdf2 (PDF)
- LightGBM (필요 시 ML)
- Freqtrade/FreqAI의 검증 개념

**직접 만들 것**
- 리포트 내용과 레이아웃
- 데이터 품질 검사
- 스케줄과 재시도
- LLM 프롬프트와 채점 루프
- 고정 규칙 엔진(기존 코드)

### Cited Findings
- **현재 의존성:** PTB 22.8, httpx, pandas 3.0.6, numpy 2.4.6, anthropic 1.9.0이 있습니다. 차트, PDF, ML 라이브러리는 없습니다. — 로컬 `/home/user/1111/requirements.txt`
- **현재 Python:** `.venv`는 3.11.18입니다. — 로컬 `/home/user/1111/.venv/bin/python --version`
- **Python 3.11에서 최신판이 바로 되는 것:** — 각 PyPI 페이지: [python-telegram-bot](https://pypi.org/project/python-telegram-bot/), [aiogram](https://pypi.org/project/aiogram/), [ccxt](https://pypi.org/project/ccxt/), [lightgbm](https://pypi.org/project/lightgbm/), [matplotlib](https://pypi.org/project/matplotlib/), [fpdf2](https://pypi.org/project/fpdf2/), [reportlab](https://pypi.org/project/reportlab/), [weasyprint](https://pypi.org/project/weasyprint/), [vectorbt](https://pypi.org/project/vectorbt/), [zipline-reloaded](https://pypi.org/project/zipline-reloaded/), [jesse](https://pypi.org/project/jesse/), [backtesting](https://pypi.org/project/backtesting/), [kaleido](https://pypi.org/project/kaleido/), [plotly](https://pypi.org/project/plotly/), [binance-sdk-derivatives-trading-usds-futures](https://pypi.org/project/binance-sdk-derivatives-trading-usds-futures/), [TA-Lib](https://pypi.org/project/TA-Lib/), [APScheduler](https://pypi.org/project/APScheduler/)

  | 패키지 | 최신 버전 | Python 요구 |
  |---|---|---|
  | PTB | 22.8 | ≥3.10 |
  | aiogram | 3.31.0 | ≥3.10 |
  | CCXT | 4.5.92 | ≥3.10 |
  | LightGBM | 4.7.0 (2026-07-18) | ≥3.10 |
  | matplotlib | 3.11.2 | ≥3.11 |
  | fpdf2 | 2.9.0 | ≥3.11 |
  | ReportLab | 5.1.0 | ≥3.9 |
  | WeasyPrint | 70.0 | ≥3.10 |
  | vectorbt | 1.2.0 | ≥3.11 |
  | zipline-reloaded | 3.2.1 | ≥3.11 |
  | Jesse | 3.6.0 | ≥3.10 |
  | backtesting.py | 0.6.6 | ≥3.9 |
  | Kaleido | 1.5.0 | ≥3.9 |
  | plotly | 7.1.0 | ≥3.8 |
  | Binance USDS 선물 SDK | 18.3.0 | ≥3.11 |
  | TA-Lib | 0.8.3 (2026-10-28) | ≥3.9 |
  | APScheduler | 3.11.3 | ≥3.8 |

- **최신판이 Python ≥3.12를 요구해 현재 venv에서 안 되는 것:** — [freqtrade](https://pypi.org/project/freqtrade/), [xgboost](https://pypi.org/project/xgboost/), [nautilus_trader](https://pypi.org/project/nautilus_trader/), [octobot](https://pypi.org/project/octobot/), [pandas-ta](https://pypi.org/project/pandas-ta/)

  | 패키지 | 최신 버전 |
  |---|---|
  | Freqtrade | 2026.10 |
  | XGBoost | 3.4.1 (2026-08-15) |
  | NautilusTrader | 1.231.0 |
  | OctoBot | 2.1.1 |
  | pandas-ta | 0.4.71b0 |

- **TA-Lib 저장소:** 별 12,382, BSD-2-Clause, push 2026-11-05입니다. — [GH](https://github.com/TA-Lib/ta-lib-python)
- **ta (bukosabino):** 별 5,251, MIT입니다. PyPI 0.11.0은 2023-11-02에 나왔습니다. — [GH](https://github.com/bukosabino/ta), [PyPI](https://pypi.org/project/ta/)

### Inferences
- **그대로 재사용 (라이브러리):**
  - 데이터: `data.binance.vision` 월·일 zip + `.CHECKSUM` → 기존 httpx 기반 `/fapi/v1/klines` 증분. 필요하면 CCXT를 쓰되, 현재 직접 호출 구조면 추가 의존성은 불필요합니다.
  - 텔레그램: PTB 유지(`sendPhoto` PNG, `sendDocument` PDF, 허용목록 미들웨어, 필요 시 `[job-queue]`·`[rate-limiter]` extra).
  - 차트: matplotlib으로 캔들을 직접 그리기(가장 안정). mplfinance는 pandas 3 호환을 검증한 경우에만 씁니다.
  - PDF: 차트만 묶으면 `PdfPages`, 텍스트 표·요약 레이아웃이 필요하면 fpdf2(LGPL이지만 라이브러리 사용)나 ReportLab(BSD)을 씁니다.
  - ML(선택): LightGBM(FreqAI 기본 예제와 같은 계열, Python 3.11 가능). 지표는 TA-Lib(활발)이 낫고, pandas-ta와 ta는 정체되거나 접근이 안 되니 피합니다.
  - 연구용 백테스트(선택): vectorbt(Commons Clause, 개인용 OK)나 backtesting.py(AGPL). 고정 규칙이 단순하면 기존 `backtest/` 코드를 유지하는 게 낫습니다.
- **개념만 차용 (코드 복사 금지, GPL 문제):**
  - Freqtrade 백테스트 가정 목록(체결가, 슬리피지 없음, 캔들 내 순서)을 리포트의 "가정" 칸에 명시합니다.
  - `lookahead-analysis`와 `recursive-analysis`에 해당하는 자체 테스트를 만듭니다. 예: 지표를 한 번에 계산한 값과 증분으로 계산한 값을 비교합니다.
  - FreqAI의 `train_period_days`, `backtest_period_days`(walk-forward), `expiration_hours`(오래된 모델로 예측 금지), `outlier_protection_percentage`, DI 기반 "학습 분포 밖이면 신뢰도 낮음" 표시를 가져옵니다.
  - Jesse의 Monte Carlo(거래 순서 섞기)로 "운인지 실력인지"를 점검합니다.
- **채택하지 않음:**
  - Freqtrade/FreqAI 전체 채택: Python 3.12+ 필요, 주문 봇 구조, GPL, 기존 코드와 중복.
  - NautilusTrader와 LEAN: 무겁고, v2 전환 중이거나 C#/Docker 기반.
  - Hummingbot: 마켓메이킹용.
  - Qlib: 크립토는 일봉이고 백테스트 불가.
  - FinRL: 교육용, PyPI 정체.
  - backtrader와 CryptoSignal: 정지.
  - plotly+Kaleido와 lightweight-charts: 브라우저나 Chrome 의존.
- **직접 구축:**
  - 시간별 리포트 템플릿(텍스트 요약, 차트, PDF)
  - 정각 이후 캔들 확정 확인과 재시도 스케줄러
  - 데이터 공백·중복·미확정 캔들 검사
  - LLM 분석 프롬프트(구조화 출력, 강세·약세 분리)
  - 과거 리포트 자동 채점과 기록
  - 비밀 로딩(파일에서만, 로그 마스킹)
  - LIVE 금지 검증기 유지
- **운영 위치:** 한국의 맥이나 미국 외 지역의 소형 서버를 권합니다. Binance 451 위험이 있기 때문입니다. 텔레그램과 Binance 둘 다 외부로 나가는 호출만 쓰는 polling 구조면 서버에 포트를 열 필요가 없습니다.

### Gaps
- Python 3.11을 지원하는 XGBoost나 Freqtrade의 구버전 범위는 확인하지 않았습니다.
- 사용자의 저장소 라이선스(공개 저장소의 LICENSE)는 확인하지 않았습니다. GPL, AGPL, LGPL 의존성과의 호환 판단에 필요합니다.
- 소형 서버 후보(지역별 Binance 접근 가능 여부)는 공식 목록이 없어서 실제 접속 테스트가 필요합니다.
