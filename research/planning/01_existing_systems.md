# 01. 기존 시스템 조사 — "남들은 이런 걸 어떻게 만들었나"

> 작성일: 2026-09-29 · 작성: 리서처(existing_systems) · 상태: 조사 보고서 (코드 없음)
> 관련 문서: [docs/PLAN.md](../../docs/PLAN.md) (기획 v0.1), [docs/STRATEGY.md](../../docs/STRATEGY.md) (차트 기법 v0.2)
> 표기: **[직접]** = GitHub·PyPI·Anthropic 문서를 직접 열어 확인 · **(검색 요약)** = 웹 검색 결과 요약으로만 확인(원문 미열람) · **확인 필요** = 확인하지 못함

---

## 1. 핵심 요약 (5줄)

1. **완성품은 없다.** 가장 성숙한 오픈소스 봇은 freqtrade(GitHub 스타 54,910, 2026-09-29 커밋, GPL-3.0)다. 여기에 BTC 선물·텔레그램·백테스트가 다 있다. 하지만 **"Claude 분석 → 텔레그램 버튼 승인 → 주문"** 흐름을 그대로 주는 프레임워크는 없다. 가장 가까운 것은 Hummingbot의 Condor와 HKUDS의 Vibe-Trading이며, 둘 다 신생이다.
2. **상용 시그널 서비스는 우리 보안 원칙과 맞지 않는다.** 3Commas·WunderTrading·Cornix와 TradingView 웹훅이 여기에 해당한다. 이 서비스들은 거래 키를 제3자에게 맡기거나, 외부에 공개된 수신 주소(웹훅)를 요구한다. 3Commas 키 유출로 약 2,000만 달러 피해가 난 사례가 있다(검색 요약).
3. **LLM 트레이딩 사례가 남긴 교훈은 세 가지다.**
   - LLM에게 전부 맡긴 대회(Alpha Arena 시즌1)에서는 6개 모델 중 4개가 손실을 냈다. Claude Sonnet 4.5의 수익률은 약 −30~−42%였다(출처마다 다름, 검색 요약).
   - 차트 **이미지**만 보고 방향을 맞힌 정확도는 동전 던지기와 통계적으로 구분되지 않았다. 확신도와 정답 여부의 상관도 거의 0이었다(단일 저자 실험).
   - LLM 판단은 과거 데이터로 백테스트하면 **룩어헤드 편향**이 생긴다.
   → 따라서 **수치를 우선하고, 이미지는 보조로 쓰고, 앞으로 쌓이는 모의매매로 검증**하는 STRATEGY v0.2의 방향이 맞다.
4. **사람 승인(Human-in-the-loop)만으로는 안전하지 않다.** 사람은 AI 추천을 형식적으로 통과시키기 쉽다(자동화 편향). 그래서 하드 가드가 사람 승인보다 **먼저, 그리고 승인과 무관하게** 돌아야 한다. 또 "확신도 0.6" 같은 LLM의 자기평가는 실적으로 보정하기 전까지 리스크 통제 수단으로 쓰면 안 된다.
5. **권고: 하이브리드.** 두뇌(데이터·Claude 분석·텔레그램 승인·하드 가드)는 직접 만들고, 근육(백테스트·주문 실행·실시세 모의매매)은 freqtrade에 맡긴다.
   - 1~3단계는 현 PLAN대로 직접 개발한다.
   - 규칙 백테스트는 freqtrade로 한다.
   - 4단계(모의주문)에 들어가기 전에 **1주짜리 시험 구현**을 한다. freqtrade REST API로 진입하고 거래소 손절 주문이 제대로 걸리는지 확인한 뒤 실행 엔진을 최종 결정한다.

---

## 2. 본문

### 2.0 조사 방법과 한계

| 항목 | 내용 |
|---|---|
| GitHub 수치 | GitHub 검색 API로 2026-09-29에 조회했다. 스타 수, 마지막 push 시각, 라이선스가 여기서 나왔다 [직접]. 스타 수는 인기를 보여 줄 뿐 품질을 보장하지 않는다 |
| 문서 | README와 docs를 raw.githubusercontent.com에서 직접 열람했다. 다만 작은 요약 모델을 거쳐 읽었으므로 세부 문구는 원문과 다를 수 있다 |
| PyPI | `https://pypi.org/pypi/<패키지>/json`에서 최신 버전과 날짜를 확인했다 [직접] |
| 웹 검색 | 서로 다른 검색어로 27회 검색했다. 공식 사이트(freqtrade.io, hummingbot.org, binance.com, tradingview.com, 언론사, arXiv 등)는 조직 네트워크 정책으로 차단되어 **검색 요약만** 봤다. 차단은 우회하지 않았다 |
| 한계 | 상용 서비스(3Commas·WunderTrading·Cornix)의 가격과 기능은 수시로 바뀐다. 모두 검색 요약이므로 가입 전에 공식 사이트에서 다시 확인해야 한다 |

**용어 몇 가지 (처음 한 번만 풀이)**
- **프레임워크**: 뼈대가 이미 짜여 있어서 내 로직만 끼워 넣으면 되는 소프트웨어
- **백테스트**: 과거 데이터로 전략을 돌려 보는 시뮬레이션
- **드라이런(dry-run)**: 실제 시세를 받되 주문은 가짜로 체결시키는 모의매매
- **웹훅(webhook)**: 외부 서비스가 내 서버 주소로 메시지를 밀어 넣는 방식. 내 서버가 인터넷에 열려 있어야 한다
- **폴링(polling)**: 내 프로그램이 먼저 상대 서버에 "새 메시지 있어?"라고 주기적으로 묻는 방식. 내 서버를 외부에 열 필요가 없다
- **REST API**: 프로그램끼리 정해진 주소로 요청을 주고받는 규약
- **거래소 손절(stoploss on exchange)**: 손절 주문을 거래소 서버에 미리 걸어 두는 것. 내 봇이 꺼져도 손절이 작동한다

---

### 2.1 (a) 오픈소스 트레이딩 봇

#### 2.1.1 한눈에 비교

| 이름 | 한 줄 정의 | 언어 | GitHub 스타 | 마지막 push | 최신 PyPI 릴리스 | 라이선스 | 텔레그램 | 선물 거래소 | 백테스트 | LLM 기능 | 우리 적합도 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **freqtrade** | 전략 기반 암호화폐 봇의 사실상 표준 | Python | **54,910** | 2026-09-29 | 2026.8 (2026-08-31) | GPL-3.0 | ◎ 내장 (명령어 제어·알림) | Binance, Bitget, Bybit, Gate, Hyperliquid, Kraken, OKX | ◎ 선물·레버리지·펀딩 반영 | FreqAI(머신러닝). LLM 연동 기능은 없음 | **높음** (실행·백테스트 엔진으로) |
| **Hummingbot** (+Condor) | 마켓메이킹·고빈도 중심 프레임워크. Condor는 그 위의 텔레그램 AI 에이전트 도구 | Python | 20,261 (Condor 207) | 2026-09-28 | 20260920 (2026-09-21) | Apache-2.0 | Condor로 제공 (버튼 메뉴·확인 흐름) | binance_perpetual 등 다수 | ○ V2 controller | Condor: LLM 에이전트, MCP | 중간 (설계 참고용) |
| **Jesse** | 백테스트 정확도를 강조하는 전략 연구 프레임워크 | Python | 8,596 | 2026-09-28 | 3.2.3 (2026-09-27) | MIT (코어) | 라이브 플러그인에 포함 | Binance Futures 등 (라이브는 플러그인) | ◎ "룩어헤드 편향 없음" 주장 | Jesse MCP (Claude 등이 전략 작성·백테스트를 도움) | 중간 (라이브 유료 문제) |
| **OctoBot** | 초보자용 UI와 "tentacle" 플러그인 구조의 봇 | Python | 6,663 | 2026-09-28 | 2.1.1 (2026-03-29) | GPL-3.0 | 내장 (상태 조회·위험도 변경·정지·긴급매매) | Binance, Bybit, Kucoin 등 | ◎ | ChatGPT/Ollama 평가기 (LLM을 "지표"로 사용) | 낮음~중간 |
| **Passivbot** | 역추세 그리드형 마켓메이커 | Python+Rust | 2,113 | 2026-09-29 | — | Unlicense (퍼블릭 도메인) | 커뮤니티 채널만 있음. 봇 연동은 확인 못함 | Bybit, OKX, Bitget, Binance 등 | ◎ Rust 백테스터·최적화기 | 없음 | 낮음 (매매 스타일이 다름) |
| **NautilusTrader** | 기관급 이벤트 기반 엔진 (Rust 코어) | Rust+Python | 29,495 | 2026-09-29 | 1.231.0 (2026-08-02) | LGPL-3.0 | 없음 (문서에 언급 없음) | Binance, Bybit, OKX, Deribit 등 | ◎ 백테스트와 실거래의 동일성 강조 | 없음 | 낮음 (비개발자에게 과함) |

출처: 스타·push·라이선스는 GitHub API [직접]. 최신 릴리스는 PyPI [직접]. 나머지는 각 README [직접]. Jesse 가격, OctoBot 텔레그램 기능, Condor 리스크 한도는 (검색 요약). 전체 URL은 §4.

**라이선스 풀이**
- **GPL-3.0**: 개인이 내 서버에서 쓰는 데는 제약이 없다. 수정본을 **배포하거나 판매할 때**는 소스를 공개해야 한다.
- **LGPL-3.0**: GPL보다 조금 느슨하다. 라이브러리로 가져다 쓸 때의 의무가 적다.
- **Apache-2.0·MIT·Unlicense**: 거의 자유롭게 쓸 수 있다.
- 우리 시스템은 개인용이므로 GPL도 문제되지 않는다. 다만 STRATEGY §9-6("유료 판매 삼가" 요청)과 함께, 상업화할 경우 따로 검토해야 한다.

#### 2.1.2 freqtrade — 가장 유력한 "얹을 대상"

**구조**: 설정 파일(config.json)과 전략 파일(Python 클래스) 하나로 동작한다. 전략 파일 안의 함수가 차례로 실행된다.
- `populate_indicators`: 지표를 계산한다
- `populate_entry_trend`: 진입 신호를 표시한다
- 콜백 함수들: 주문 직전·직후에 끼어들어 추가 처리를 한다

거래소 연동은 내부적으로 ccxt(PLAN §3.2에서 이미 고른 라이브러리)를 쓴다 [직접: README].

| 기능 | 내용 | 우리에게 의미 |
|---|---|---|
| 텔레그램 | 봇 토큰과 `chat_id`를 설정하고, `authorized_users`로 명령할 수 있는 사람을 제한한다. `/status /profit /balance /daily /stop /stopentry /forceexit /forcelong /forceshort` 등을 지원한다. 명령어 단축 **커스텀 키보드**는 있지만 "명령 인자는 지원 안 함"이다. 그룹에 넣으면 "그룹의 모든 멤버에게 모든 명령 권한을 주는 것"이라고 경고한다 [직접: telegram-usage.md] | **명령형 제어**다. 신호마다 [롱][숏][패스] 버튼으로 승인하는 **승인 흐름은 없다**. 승인 UI는 우리가 만들어야 한다 |
| 강제 진입 | `/forcelong`·`/forceshort`와 REST `/forceenter`를 제공한다. `force_entry_enable=true`일 때만 켜지고, 보안상 기본값은 꺼짐이다. REST 파라미터는 `pair, side, price, ordertype, stakeamount, entry_tag, leverage`다 [직접: rest-api.md] | 우리 봇이 사람의 승인을 받은 뒤 이 API를 불러 주문을 넣을 수 있다 (§3의 B2 방식) |
| REST API 보안 | 기본값은 `127.0.0.1`(같은 컴퓨터에서만 접근)이다. 아이디·비밀번호와 JWT(로그인 토큰)를 쓰며, 문서는 "인터넷에 노출하지 말 것을 강력히 권고"한다. 원격 접속은 SSH 터널이나 VPN을 쓰라고 한다 [직접] | 인바운드 포트를 열지 않는다는 우리 원칙과 맞는다 |
| 콜백 | `confirm_trade_entry`: 주문 직전에 호출되며, False를 돌려주면 주문을 취소한다. 다만 "시간이 중요하니 무거운 계산이나 **네트워크 요청을 피하라**"고 한다. `custom_stoploss`는 약 5초마다 호출되며 손절선을 **올리기만** 한다. `stoploss_from_absolute()`로 절대 가격 손절을 걸 수 있다. `leverage` 콜백으로 거래별 레버리지를 정한다 [직접: strategy-callbacks.md] | `confirm_trade_entry` 안에서 사람 승인을 **기다리면 안 된다**(봇 전체가 멈춤). 승인은 바깥에서 받고 `/forceenter`로 넣어야 한다 |
| 거래소 손절 | `stoploss_on_exchange`를 지원한다. 문서는 stop-market을 권장한다("폭락 시 무조건 빠져나오기"). 기본 갱신 주기는 60초다 [직접: stoploss.md]. 바이낸스 선물도 지원한다 [직접: exchanges.md] | PLAN §4.3 "손절 주문 필수"를 거래소 측에서 보장할 수 있다 |
| 선물 설정 | 격리(isolated)와 교차(cross)를 지원한다. 청산가와 손절 사이에 여유(`liquidation_buffer`, 기본 0.05)를 둔다. "레버리지를 쓰면 한 계정에서 봇 2개를 돌릴 수 없다" [직접: leverage.md]. **바이낸스는 One-way Mode와 Single-Asset Mode가 필수**다 [직접: exchanges.md] | 격리 마진·3배 상한과 호환된다. **봇 전용 계정(또는 서브계정)**이 필요하다 (거래소별로 서브계정이 되는지는 확인 필요) |
| 보호장치(Protections) | `StoplossGuard`(손절이 연속되면 정지), `MaxDrawdown`(최대 낙폭 도달 시 정지), `CooldownPeriod`(청산 직후 재진입 금지), `LowProfitPairs`. 백테스트에서도 켤 수 있다 [직접: protections.md] | 일일 손실 한도와 연속 손절 중단의 **2차 방어선**으로 쓸 수 있다 |
| 주의할 버그 보고 | 2022년 이슈 #7489: `forceenter`를 동시에 10번 호출하자 `max_open_trades=3`을 무시하고 모두 진입했다("Bug" 라벨). 현재 해결됐는지는 **확인 필요** [직접] | **하드 가드를 엔진에 맡기지 말고 우리 레이어에 둬야 하는 근거**다 |
| 드라이런·UI·웹훅 | 드라이런 모드, 웹 UI(FreqUI), 외부 알림 웹훅(일반·Discord; 진입·청산·체결 이벤트)을 제공한다 [직접: README, webhook-config.md] | 실시세로 모의매매를 할 수 있다 (PLAN 7단계 검증에 유용) |
| 요구 사양 | Python ≥ 3.11, 최소 RAM 2GB·디스크 1GB·vCPU 2개. Docker 권장 [직접: README] | 가장 작은 VPS보다 한 단계 위 사양이 필요할 수 있다 |

#### 2.1.3 Hummingbot + Condor — 설계를 참고할 대상

- **Hummingbot**은 원래 "고빈도 매매의 대중화"가 목표인 마켓메이킹 중심 프레임워크다. 연결 대상은 세 종류다.
  - 중앙화 거래소: 현물과 무기한 선물(예: `binance_perpetual`)
  - 탈중앙 호가창 거래소: Hyperliquid, dYdX
  - 자동화 마켓메이커(AMM): Uniswap 등
  - 부속 도구로 Condor, Hummingbot API, Gateway가 있다 [직접: README].
- **Condor**는 README에서 "Hummingbot API를 통해 모니터링·거래하는 텔레그램 봇"이다 [직접].
  - 대화형 버튼 메뉴가 있고, "포지션을 **확인(confirmation)** 후 청산"하는 흐름이 있다.
  - AI 에이전트(`/agent`)는 OpenAI, OpenRouter, OpenAI 호환 엔드포인트를 쓴다. **Claude를 직접 지원한다는 문구는 README에 없다**. OpenRouter를 거치면 쓸 수 있을 것으로 보이나 확인 필요다.
  - 운영 조건: Docker가 필요하다. 운영 환경에서는 포트 8000을 공개하지 말고 Tailscale(사설 VPN)을 쓰라고 권고한다.
- 공식 소개글(검색 요약)의 설계 요지:
  - "확률적 추론(에이전트 층)과 결정적 실행(실행 층)을 분리한 2층 구조"
  - 리스크 한도 파라미터: `max_position_size_quote`, `max_single_order_quote`, `max_open_executors`, `max_drawdown_pct`
  - "에이전트가 계정에서 엉뚱한 짓을 하지 못하게 하는 가드레일"
- **PositionExecutor**의 삼중 장벽(Triple Barrier): 손절, 익절, **시간 제한** 세 가지로 청산한다(검색 요약). 손절은 시장가, 익절은 지정가로 설정할 수 있다. 손절 주문을 거래소에 미리 거는지, 봇이 감시하다가 내는지는 **확인 필요**다.
- **평가**: 개념은 우리 시스템과 가장 비슷하다(LLM 판단 + 텔레그램 + 결정적 실행 + 리스크 한도). 하지만 비개발자가 기반으로 삼기에는 무리다.
  - 여러 컨테이너(Hummingbot API, Gateway 등)를 운영해야 한다
  - 마켓메이킹 개념을 알아야 한다
  - Condor 스타 207로 아직 신생이다
  - → **설계를 참고하는 대상**으로만 쓴다.

#### 2.1.4 기타 프레임워크 요점

- **Jesse**
  - README: "룩어헤드 편향 없는 정확하고 빠른 백테스트", 다중 타임프레임·다중 종목, Optuna+Ray 최적화 [직접].
  - **라이브·모의매매와 텔레그램·Slack·Discord 알림은 공식 "Live Trade" 플러그인에 들어 있다**. 평생 라이선스가 약 1,600달러이고 할인이 있다는 요약이 있다(검색 요약). 현재 가격은 확인 필요다.
  - Jesse MCP로 Claude 같은 AI 비서가 전략 작성과 백테스트를 도울 수 있다 [직접].
  - → 백테스트 전용으로는 훌륭하다. 하지만 실행까지 한 엔진으로 하려면 비용이 든다.
- **OctoBot**
  - "ChatGPT 거래 모드"는 LLM에게 시장 맥락을 주고 "오를지 내릴지 + 확신도(%)"를 물어 **지표로** 쓴다(검색 요약).
  - LLM 호출 비용이 커서 원래는 백테스트를 못 했다. 이후 개발사가 **특정 페어의 과거 데이터에 대해 미리 계산해 둔 GPT 답변**을 내려받아 백테스트하도록 바꿨다(검색 요약). → LLM 전략의 백테스트가 얼마나 어려운지 보여 주는 사례다.
  - 텔레그램으로 상태 조회, 위험도 변경, 정지, 긴급 매매를 할 수 있다(검색 요약). 버전 0.4.47에서 GPTEvaluator가 추가됐다. README에 Claude는 언급되지 않는다 [직접].
- **Passivbot**: 이동평균(EMA)과 가격 밴드를 쓰는 역추세 마켓메이커다. 손절 대신 "Unstucking"(작은 손실을 조금씩 실현해 물린 포지션을 푸는 방식)을 쓰고, 선택 기능으로 계좌 손절이 있다. "Used at one's own risk" [직접]. 추세·지지 기반인 우리 기법과 철학이 다르다.
- **NautilusTrader**: "같은 전략 코드를 백테스트와 실거래에서 그대로 실행"하는 것이 강점이다. 다만 스스로 "실거래는 시뮬레이션이 재현하지 못하는 거래소·지연·재동기화 동작을 포함한다"고 인정한다 [직접]. 설치에 Rust 도구와 clang 컴파일러가 필요해 초보자에게는 장벽이 높다.

---

### 2.2 (b) 시그널 → 텔레그램 → 수동·반자동 실행 서비스

| 서비스·방식 | 흐름 | 사람 승인 | 키 보관 위치 | 인바운드 공개 주소 | LLM 분석 | 비용 | 우리 관점 평가 |
|---|---|---|---|---|---|---|---|
| **TradingView 알림 + 웹훅** | Pine Script 조건 충족 → TradingView가 내 URL로 JSON을 POST → 내 서버가 주문 | 없음 (즉시 실행). 직접 만들면 추가 가능 | 내 서버 | **필요**. 포트 80·443만 허용, IPv4만 가능. 발신 IP 4개 허용 목록 권장 (검색 요약) | 없음 | **유료 플랜 필요**. 최소 Essential 월 12.95달러(연 결제)라는 요약이 있음 (검색 요약) | 차트를 **사람이 볼 때**는 좋다. 하지만 **공개 웹훅 서버**가 생겨 "인바운드 포트 없음" 원칙과 충돌한다 → 채택하지 않음 |
| **Binance Futures "Signal Trading"** | TradingView 웹훅 → 바이낸스가 직접 주문 (2023-09 출시) | 없음 | 바이낸스 | TradingView → 바이낸스 (내 서버 불필요) | 없음 | TradingView Pro 이상 | USDⓈ-M 선물만 지원, **지정가 GTC만 지원**, 신호 100개 한도 (검색 요약). LLM도 사람 승인도 넣을 수 없다 |
| **3Commas Signal Bot** | 외부 웹훅(JSON: `secret`, `action`=enter_long 등) → 3Commas가 주문 | 없음 (자동) | **3Commas 서버** | 3Commas 쪽 | 없음 | 구독 | **2022-12 API 키 유출**: 트위터에 키가 공개됐고, 3Commas가 12/29에 인정했다. 공격자가 사용자 계정으로 거래해 **약 2,000만 달러** 피해가 났고 FBI 조사가 보도됐다 (검색 요약: CoinDesk·Cointelegraph·Halborn) |
| **WunderTrading** | TradingView 알림 → 실행 규칙(사이즈·익절) 적용 → 주문. 선물·현물 지원 | 없음 | WunderTrading | 서비스 쪽 | 없음 | 확인 필요 | 3Commas와 같은 제3자 키 보관 구조 |
| **Cornix** | 텔레그램·Discord **시그널 채널의 메시지를 읽어** 자동 주문. 수동 "Follow" 버튼도 있음 | 채널별 자동 또는 **수동 Follow** | Cornix | 불필요 | 없음 | 구독 | 개념상 "텔레그램 + 버튼 → 주문"이 가장 비슷하다. 그러나 **남의 시그널을 추종**하고 키를 제3자가 보관한다. 시그널 채널 품질 문제도 있다 |
| **자체 호스팅 오픈소스** (예: h4rsh-vishwakarma/TradingBot, ytrevor81/TradingView-Binance-Telegram-Bot, 51bitquant/binance-tradingview-webhook-bot) | TradingView 웹훅 → Flask·Node 서버 → 바이낸스 주문 → 텔레그램으로 결과 알림 | 대부분 없음 (결과 **통보**만) | 내 서버 | **필요** | 없음 | 무료 | "텔레그램"이 **승인**이 아니라 **통보** 용도다. 다층 검증 파이프라인이나 드라이런·테스트넷 같은 방어 설계는 참고할 만하다 (검색 요약) |

**관찰**
- 이 시장의 서비스는 대부분 **"신호가 오면 즉시 자동 실행"**하고, 텔레그램은 **알림 창구**로만 쓴다. 신호마다 사람이 승인하는 흐름은 Cornix의 수동 Follow 정도뿐이다.
- 한 번에 두 가지 보안 위험이 있다.
  - 제3자 서비스에 **거래 가능 키를 맡기는 것** (3Commas 사례)
  - TradingView 웹훅을 받으려면 **외부에 공개된 서버를 여는 것**
- 보안 전문가인 사용자의 PLAN §4 원칙(출금 금지 키, IP 화이트리스트, 폴링 방식)은 이 사례들로 보아 옳다. 다만 **출금 권한이 없어도 거래 권한만으로 피해가 난다**는 점을 기억해야 한다. 3Commas 사고에서 공격자는 키로 **거래**를 해서 자금을 빼냈다(검색 요약). 즉 IP 화이트리스트가 출금 금지만큼 중요하다.

---

### 2.3 (c) LLM·AI 트레이딩 에이전트 오픈소스와 "LLM에게 차트를 보게 한" 사례

#### 2.3.1 프로젝트 비교

| 프로젝트 | 스타 (2026-09-29) | 마지막 push | 라이선스 | 무엇을 하나 | 실제 주문 | 차트 이미지 사용 | Claude 지원 |
|---|---|---|---|---|---|---|---|
| **TauricResearch/TradingAgents** | 109,180 | 2026-09-29 | Apache-2.0 | 분석가(펀더멘털·심리·뉴스·기술) → 강세·약세 연구원 **토론** → 트레이더 → 리스크팀 → 포트폴리오 매니저. LangGraph 기반. 논문 arXiv 2412.20138 | **아니오**. "시뮬레이션 거래소로 전송". "투자 조언이 아니며 연구 목적" | 아니오 (MACD·RSI 등 수치 지표) | 예 (Anthropic 포함 다수) |
| **virattt/ai-hedge-fund** | 63,792 | 2026-09-26 | MIT | 유명 투자자 페르소나 에이전트들이 판단 (주식) | **아니오**. "실제로 거래하지 않음" | 아니오 | 예 |
| **HKUDS/Vibe-Trading** | 34,284 | 2026-09-29 (2026-04 생성) | MIT | 개인 트레이딩 에이전트. 증권사·거래소 18곳(Binance·OKX 포함), 선물, 백테스트, MCP 도구 | **예, 단 기본값은 모의**. 실거래는 **거래별 확인**을 거치며, 사전 검증이 "실패하면 닫힌다(fails closed)" | 확인 필요 | 예 |
| **NoFxAiOS/nofx** | 12,990 | 2026-09-05 | AGPL-3.0 | Alpha Arena를 모방한 다중 AI 트레이딩 터미널 (Binance·Hyperliquid 등) | 예 (자율) | 확인 필요 | 예 (awesome-alpha-arena 목록) |
| **AI4Finance/FinRobot** | 8,107 | 2026-09-28 | Apache-2.0 | 금융 분석용 LLM 에이전트 플랫폼 | 분석 중심 | 멀티모달 태그 있음 | 확인 필요 |
| **qrak/LLM_trader** | 130 | 2026-09-29 | MIT | **4K 캔들 차트 PNG를 멀티모달 LLM에 보내 패턴 인식** + 지표 50여 개 + 벡터 DB 기억 + 반성(Reflection) 엔진 | **기본은 모의매매**. 실거래 실행 모듈은 "테스트 중" | **예 (핵심 기능)** | 대체 모델 경로에 포함 (주력은 DeepSeek) |
| **youtube-jocoding/gpt-bitcoin** (국내 조코딩) | 290 | 2026-09-27 | 표기 없음 | v1은 OHLCV+지표로 1시간마다 매수·매도·보유 판단. v2는 뉴스·공포탐욕지수·반성 추가. **v3는 Selenium으로 차트 캡처 → GPT-4o 비전** | **예, 사람 승인 없이 자동** (업비트 현물) | **예** | 아니오 (GPT) |

출처: 스타·라이선스는 GitHub API [직접]. 설명은 각 README [직접]. nofx 설명은 awesome-alpha-arena [직접].

**관찰**
- 스타가 가장 많은 LLM 프로젝트들(TradingAgents, ai-hedge-fund)은 **실제 주문을 내지 않는** 연구·교육용이다. 실거래를 하는 프로젝트는 대개 "기본은 모의, 실거래는 확인 후"로 설계되어 있다(Vibe-Trading, LLM_trader).
- 국내 비개발자 사이에서 유명한 조코딩 gpt-bitcoin은 우리와 가장 비슷한 "바이브코딩" 사례다. 하지만 **현물, 레버리지 없음, 완전 자동**이다. 우리는 **선물·레버리지**라서 같은 구조를 그대로 가져오면 위험이 훨씬 크다. 사람 승인과 하드 가드가 반드시 더해져야 한다.

#### 2.3.2 LLM이 실제로 매매하면? — Alpha Arena 시즌1 (검색 요약)

- **대회 조건**: Nof1.ai가 주최했다. 모델마다 **실제 자금 1만 달러**를 받아 Hyperliquid에서 **암호화폐 무기한 선물**을 **자율로** 거래했다. 프롬프트와 입력 데이터는 모두 같았다. 2025-11-03에 종료됐다.
- **결과**:
  - 6개 모델 중 4개가 손실을 냈다.
  - 1위 Qwen3 Max는 약 +22%, 2위 DeepSeek V3.1은 약 +4~5%였다.
  - **Claude Sonnet 4.5는 −30.81%(한 출처) 또는 −42.01%(다른 출처)로 출처마다 다르다**. "공격적 레버리지로 변동 중 청산"이 원인이라는 해설이 있다.
  - GPT-5는 약 −63%라는 보도가 있다.
- **해석 시 주의**:
  - 약 2주짜리 단일 시즌이다.
  - 2025년 모델(Sonnet 4.5) 기준이며, 현재 권장 모델(Opus 5.5)과 다르다.
  - 대회 규칙이 레버리지를 허용했다.
  - 표본이 작아서 "어떤 모델이 매매를 잘한다"는 결론은 낼 수 없다.
- **우리에게 주는 의미**: 여러 해설이 공통으로 짚는 원인은 **과도한 레버리지와 리스크 통제 부재**다. 이는 PLAN·STRATEGY의 **레버리지 3배 상한, 격리 마진, 전체 노출 1.0배 캡, 사람 승인**을 뒷받침한다. 반대 방향 근거는 없다.

#### 2.3.3 "차트 이미지를 LLM에게 보여 주면 잘 볼까?" — 근거 모음

| 근거 | 내용 | 신뢰도 |
|---|---|---|
| **Anthropic 공식 Vision 문서** [직접] | "공간 추론: 좌표·위치 출력은 **근사치**", "개수 세기: 작은 물체가 많으면 정확하지 않을 수 있음", "고위험 용도에서는 이미지 해석을 **반드시 검토·검증**하고, 완벽한 정밀도가 필요한 작업에는 **사람 감독 없이 쓰지 말 것**". 비용: 이미지 토큰 = ⌈가로/28⌉×⌈세로/28⌉. 예) 1000×1000 이미지 = 1,296토큰 → Opus 5.5 입력 4달러/100만 토큰 기준 **장당 약 0.005달러** | 높음 (1차 출처) |
| **단일 저자 실험 (Roman Antonov, 2026-04, GitHub gist)** [직접] | Claude Haiku 4.5·Sonnet 4.6·Opus 4.7과 Gemini 3 Flash를 실험했다. 실제 크립토 신호 40건(승·패, 롱·숏 각 20건)과 호출 215회를 썼다. **패턴 이름을 맞힌 것은 215회 중 1회**. 방향 정확도는 Haiku 51.4%, Gemini 51.4%, Opus 57.1%이며 **95% 신뢰구간이 모두 50%(동전 던지기)를 포함**했다. **롱 편향**이 있었고(Opus 롱·숏 격차 49%p), **확신도와 정답의 상관 ≈ 0**이었다. 권고는 네 가지다: "이미지 대신 **구조화된 수치**를 넣어라", "비전 LLM은 **예측기가 아니라 필터**로 써라", "운영 투입 조건: 윌슨 95% 하한 > 50%, 확신도-정답 상관 ≥ 0.3, 롱·숏 편향 < 10%p" | 중하 (동료 검토 없음, 표본 작음, 옛 모델. 하지만 방법과 수치를 공개함) |
| **FinChart-Bench (ACL 2026), MME-Finance** (검색 요약) | 금융 차트 질의응답 벤치마크다. 시각언어모델 5종의 평균 정확도는 FinChart-Bench 60.8%, MME-Finance(영문) 44.8%였다. "**캔들차트와 기술적 지표 차트**에서 특히 성능이 낮다" | 중 (논문이지만 원문 미열람) |

→ **결론**: 차트 이미지는 **보조 입력**으로 두고, 판단의 중심은 **코드가 계산한 수치**에 둔다. 이는 STRATEGY v0.2 §2("코드는 측정, Claude는 해석")와 일치한다. 이미지 비용은 장당 0.5센트 수준이라 **비용 때문에 뺄 이유는 없다**. 문제는 **정확도**다. 모의매매 단계에서 "수치만" 대 "수치+이미지"를 비교(A/B)해 이미지가 실제로 도움이 되는지 확인하는 것이 좋다.

#### 2.3.4 LLM 판단은 과거 데이터로 백테스트할 수 없다 — 룩어헤드 편향

- **룩어헤드 편향(look-ahead bias)**: 시뮬레이션 시점에는 알 수 없었던 미래 정보가 섞여 들어가 성과가 부풀려지는 현상이다.
- LLM은 학습 데이터에 **이미 결과가 알려진 과거 시세와 뉴스**를 담고 있다. 그래서 학습 기간과 겹치는 과거 구간을 LLM에게 "판단"시키면 사실상 답을 아는 상태에서 푸는 셈이 된다.
  - 연구(arXiv 2512.23847 등, 검색 요약)는 "학습 데이터 마감일 이전 구간에서는 LLM이 결과를 기억하고 있을 확률이 뚜렷하게 양수이고, 마감일 직후에는 0으로 떨어진다"고 보고했다.
  - ai-hedge-fund도 백테스트 시 "종목명·날짜를 에이전트에게 숨겨 룩어헤드 편향을 줄인다"고 적었다 [직접].
- **시사점**:
  - 코드 규칙(◎)은 freqtrade 같은 엔진으로 **과거 백테스트**한다.
  - **Claude 층의 가치는 앞으로 쌓이는 모의매매(전향적 페이퍼 트레이딩)로만** 검증한다.
  - STRATEGY §9-3이 이미 이렇게 되어 있다. 이 원칙을 명시적으로 적어 두고, "Batch API로 과거 구간을 싸게 돌려 보는" 식의 검증은 **하지 않는다**고 못 박는 것이 좋다.

---

### 2.4 (d) 사람 승인(Human-in-the-loop) 실행 패턴

| 패턴 | 사례 | 핵심 아이디어 | 우리 시스템 적용 |
|---|---|---|---|
| **명령형 제어** | freqtrade `/forcelong`·`/stop`, OctoBot 긴급 매매 | 사람이 직접 명령한다. 신호별 승인이 아니다 | `/stop`(킬 스위치)과 상태 조회만 가져온다 |
| **제안 → 확인 (Propose-Confirm)** | Vibe-Trading: 에이전트는 `propose_*`만 할 수 있고 사람의 "confirm"이 있어야 실행된다. "실행 시점에 승인한 위임 범위(mandate)가 넓어지면 재승인" [직접]. Condor: 확인 후 청산 [직접] | 제안과 실행을 분리한다. **사람이 승인한 정확한 파라미터**에만 실행 권한을 준다 | 버튼 → 확인 화면(수량·레버리지·손절 표시) → 실행. **체결 직전 가격이 승인가에서 정해진 폭 이상 벗어나면 자동 무효·재승인** (PLAN §4.2 유효시간을 보강) |
| **중단 → 재개 + 체크포인트** | LangGraph `interrupt()`와 체크포인트 DB. 대기 상태를 저장하고 승인이 오면 이어서 실행 (검색 요약) | 승인 대기가 길어도 프로세스 재시작에 견딘다 | 신호 **상태 머신**(대기→승인→실행→완료 / 만료 / 거부 / 실패)을 SQLite에 저장한다. 재시작 시 "대기" 신호는 만료 처리한다 |
| **결정적 규칙 우선 (deny-first)** | Claude Agent SDK: 훅과 **거부 규칙이 권한 모드보다 먼저** 평가되며, "bypass 모드에서도 거부 규칙은 막는다" [직접]. FIA: 최대 주문 크기, 포지션 한도, 가격 허용폭 같은 **사전 리스크 통제**를 여러 층에 둔다 (검색 요약) | AI 판단이나 사람 승인보다 **하드 규칙이 먼저** 적용된다 | 하드 가드를 **알림 전(①)과 주문 직전(②) 두 번** 검사한다. 사람이 승인해도 가드를 넘을 수 없다 |
| **실패 시 닫힘 (fail-closed)** | Vibe-Trading "the gate fails closed" (포지션 조회·API 오류·검증 실패) [직접] | 불확실하면 실행하지 않는다 | 잔고·포지션 조회 실패, JSON 스키마 위반, Claude의 refusal·max_tokens 중단이 생기면 **주문하지 않는다** |
| **킬 스위치** | FIA 정의: "모든 신규 주문을 막고 미체결 주문을 취소. 다른 수단이 실패했을 때의 최후 수단" (검색 요약). freqtrade `/stop`, `/stopentry` [직접] | 사전 통제를 대신하지 않는 **마지막 보루**다 | `/stop` = 신규 차단 + 미체결 취소. 보유 포지션 청산은 별도 확인을 거친다 |
| **2층 구조 (추론 / 실행 분리)** | Condor: "확률적 추론 층과 결정적 실행 층 분리" (검색 요약). Anthropic "Building effective agents": 체크포인트에서 사람에게 돌아오고, 반복 횟수 제한 같은 **중단 조건**을 둔다 (검색 요약) | LLM에게 **주문 도구를 주지 않는다** | Claude는 **JSON만 출력**한다. 주문은 코드가 하드 가드를 통과한 경우에만 낸다. MCP나 툴로 Claude가 직접 주문하는 구조(Hummingbot MCP 등)는 **채택하지 않는다** |
| **자동화 편향 대응** | 여러 연구 정리글(검색 요약): 사람은 틀린 AI 추천에도 동의하는 경향이 가장 일관되게 관찰된다. 승인 요청이 많아지면 "고무도장(rubber stamp)"이 된다 | 사람 승인은 **요청이 적고 판단 재료가 좋을 때만** 의미가 있다 | 코드 사전 필터로 알림 수를 줄인다 (STRATEGY v0.2). 알림에 **반대 근거와 무효화 조건**을 함께 표시한다. **승인율·거부율·거부한 신호의 사후 성과**를 기록해 형식적 승인인지 점검한다 |

**텔레그램 구현 관련 사실**
- python-telegram-bot(스타 29,495, LGPL-3.0, 최신 22.8)은 `InlineKeyboardButton`과 `CallbackQueryHandler` 예제를 제공한다 (검색 요약: 공식 examples).
- **한 봇 토큰에는 폴링 연결(getUpdates)이 하나만 허용된다**. 같은 토큰으로 두 프로세스가 폴링하면 "Conflict: terminated by other getUpdates request" 오류가 난다 (검색 요약: python-telegram-bot 이슈 등).
  - → **개발용·운영용 봇 토큰을 분리**한다.
  - → freqtrade를 함께 쓰면 **freqtrade 텔레그램은 끄거나 별도 토큰**을 쓴다.

---

## 3. 우리 시스템에 대한 시사점과 권고

### 3.1 선택지 비교: 전부 자체 개발 vs 기존 프레임워크 위에 얹기

| 기준 | **A. 전부 자체 개발** (현 PLAN) | **B. freqtrade 위에 얹기** (권고 목표) | C. Hummingbot+Condor 기반 | D. OctoBot GPT 모드 | E. 상용 서비스 |
|---|---|---|---|---|---|
| Claude 분석 → 텔레그램 승인 흐름 | 직접 구현 (자유도 최고) | **직접 구현** (A와 같음. 어느 엔진도 이 흐름을 주지 않음) | Condor가 비슷함. 그러나 OpenAI 호환 중심이고 Claude 직접 지원은 미확인 | GPT를 "지표"로만 씀. 신호별 사람 승인 없음 | 없음 |
| 주문 수명주기 (부분 체결, 손절 주문, 고아 주문 정리, 재시작 후 거래소와 대조) | **직접 구현. 버그 위험이 가장 큼** | 2017년부터 운영된 엔진이 처리 | Executor가 처리 | 처리 | 서비스가 처리 |
| 거래소 손절 | 직접 (거래소 API 변경에도 직접 대응) | `stoploss_on_exchange` (바이낸스 선물 지원) | 확인 필요 | 확인 필요 | 서비스 |
| 코드 규칙 백테스트 | 엔진을 직접 만들어야 함 (펀딩비·수수료·청산 반영이 어려움) | **내장** (선물·레버리지·펀딩·보호장치) | 내장 | 내장 | 제한적 |
| 실시세 모의매매 | 직접 | **드라이런 내장** | 모의 내장 | 모의 내장 | 일부 |
| 보안 (키 위치, 인바운드 포트) | 내 서버, 인바운드 없음 | 같음 (REST는 127.0.0.1) | API 포트 8000 → Tailscale 권장 | 웹 UI 포트 | **키를 제3자가 보관** |
| 비개발자 학습 난이도 | 코드는 적지만 **금융 예외 상황을 모두** 직접 알아야 함 | freqtrade 설정과 전략 클래스를 익혀야 함. 문서·커뮤니티 풍부 | 높음 | 중간 | 낮음 |
| 실행 프로세스 수 | 1 | 2 (우리 봇 + freqtrade) | 3개 이상 | 1~2 | 0 |
| 하드 가드 위치 | 우리 코드 | **우리 코드 (필수)** + freqtrade 보호장치(2차) | Condor 리스크 한도 + 우리 코드 | 확인 필요 | 서비스 설정 |
| 라이선스·종속 | 자유 | GPL-3.0 (개인용 무관) | Apache-2.0 | GPL-3.0 | 벤더 종속 |

**B의 세부 방식**

- **B1. 신호 파일 방식**: freqtrade 전략이 우리 DB의 "승인된 신호"를 읽어 `populate_entry_trend`에서 진입한다.
  - → 캔들 마감 주기에 묶여 **승인 후 진입이 최대 1봉 늦어진다**.
  - → 백테스트 코드와 실거래 코드가 달라진다. **비추천**.
- **B2. REST 강제 진입 방식 (권고)**:
  1. 우리 봇이 사람의 승인을 받는다.
  2. 하드 가드 ②를 통과한다.
  3. `127.0.0.1`의 freqtrade REST `/forceenter`를 호출한다(`side, price, ordertype=limit, stakeamount, leverage, entry_tag=신호ID`).
  4. freqtrade가 주문, 거래소 손절, 체결 추적을 맡는다.
  5. 손절 가격은 `custom_stoploss` + `stoploss_from_absolute()`로 **신호별 절대가**를 건다. 정확한 구현 방식(신호ID → 손절가 조회)은 **시험 구현(PoC)에서 확인 필요**하다.

```
┌──────────── 우리 봇 (두뇌·승인) ────────────┐        ┌──── freqtrade (근육) ────┐
│ 스케줄러 → ccxt 공개 시세 → 공용 규칙 모듈  │        │  같은 규칙 모듈을 import  │
│ → Claude(JSON만) → 하드가드① → 텔레그램 버튼 │        │  → 백테스트 전용          │
│ → 사람 확인 → 하드가드② → REST /forceenter ─┼─127.0.0.1─▶ 주문·거래소 손절·체결   │
│ ← 체결·청산 알림 (REST 조회 또는 웹훅) ◀─────┼────────────  추적·드라이런·보호장치 │
└─────────────────────────────────────────────┘        └──────────────────────────┘
```

**B2의 주의점 (이번 조사에서 확인한 사실 기반)**

1. `force_entry_enable=true`로 켜면 freqtrade **텔레그램의 `/forcelong`도 함께 켜진다** [직접]. → freqtrade 텔레그램은 **끄고**, 승인 창구는 우리 봇 하나로 한다.
2. `forceenter`가 `max_open_trades`를 무시한 버그 보고가 있다(#7489, 해결 여부 확인 필요). → **포지션 수, 증거금 20%, 전체 노출 1.0배, 일일 −5% 가드를 우리 코드에서 검사**한다. freqtrade 보호장치는 2차 방어선으로만 쓴다.
3. 바이낸스는 **One-way Mode + Single-Asset Mode**가 필수이고, 레버리지를 쓰면 **한 계정에 봇 하나**만 돌릴 수 있다 [직접]. → 봇 전용 계정 또는 서브계정을 쓰고, 수동 매매와 섞지 않는다.
4. `confirm_trade_entry`에서 승인을 기다리면 안 된다(네트워크 요청 금지 권고) [직접].
5. GPL-3.0이다. 개인 사용에는 문제없다. 수정한 freqtrade를 배포·판매할 경우에만 소스 공개 의무가 생긴다.

### 3.2 권고 (결론)

**권고 0 — 하이브리드 채택: "두뇌는 직접, 근육은 freqtrade"**

| 단계 (PLAN §6) | 권고 | 이유 |
|---|---|---|
| 0~3 (준비·데이터·분석·알림) | **현 PLAN대로 직접 개발.** ccxt 공개 시세, pandas, mplfinance, Anthropic SDK, python-telegram-bot을 쓴다. 주문 기능은 없다 | 우리 시스템의 고유 가치다. 어느 프레임워크에도 없다. 코드가 작아서 배우기 좋고, 돈 위험이 없다 |
| 7의 일부를 앞당김 (규칙 백테스트) | **freqtrade 백테스트로 ◎ 규칙 검증** (STRATEGY §9-1). 규칙은 **공용 Python 모듈** 하나로 만들어, 우리 봇과 freqtrade 전략 파일이 **같은 코드를 import**한다 | 백테스트 엔진을 직접 만들면 수수료·펀딩비·청산 반영에서 틀리기 쉽다. 규칙 코드를 두 벌 두지 않는다 |
| 4 (모의주문) 들어가기 전 | **1주 시험 구현(PoC)**: freqtrade 드라이런 → REST `/forceenter`로 BTC/USDT 선물 롱 1건 → 거래소 손절 생성 → 청산까지 확인. 이어서 바이낸스 테스트넷에서 실제 주문 API를 한 번 확인한다 | 성공하면 **B2**로 간다. 막히면 **A**(직접 ccxt 실행)로 간다. 초보자에게 어느 쪽이 쉬운지는 해 봐야 안다 |
| A를 택하는 경우 | 범위를 **BTC 한 종목, 포지션 하나**로 좁힌다. 필수 구현: ① 진입 체결 즉시 거래소에 reduce-only 손절 주문(포지션을 줄이는 방향으로만 작동하는 주문) ② 재시작 시 거래소의 포지션·주문과 내 DB를 대조 ③ 고아 주문(손절 후 남은 익절 주문 등) 정리 ④ 부분 체결 처리 | freqtrade가 대신 해 주는 부분을 직접 책임져야 한다 |

**나머지 권고 (기존 결정에 대한 확인·지적 포함)**

1. **텔레그램 선택 유지 (확인).** freqtrade, OctoBot, Condor, Jesse 등 주요 봇이 모두 텔레그램을 기본 알림·제어 창구로 쓴다. 단, 토큰 하나당 폴러 하나라는 제약 때문에 **개발용·운영용 봇을 분리**한다.
2. **상용 시그널 서비스와 TradingView 웹훅 경로는 채택하지 않는다 (확인).** 제3자 키 보관(3Commas 유출 사례)과 공개 웹훅 서버가 필요해서다. TradingView는 **사람이 차트를 확인하는 도구**로만 쓴다.
3. **IP 화이트리스트를 "출금 금지"와 같은 급의 필수 항목으로 격상 (지적).** 3Commas 사고는 출금이 아니라 **거래 권한**으로 피해가 났다(검색 요약). PLAN §4.1에 이미 있지만 "권장"이 아니라 **없으면 실거래 불가인 조건**으로 둔다.
4. **Claude에게 주문 도구를 주지 않는다 (신규 원칙).** Claude는 JSON만 출력한다. MCP나 에이전트가 직접 주문하는 구조(Hummingbot MCP, Condor 에이전트 모드, Alpha Arena식 자율 매매)는 쓰지 않는다. Anthropic "Building effective agents"의 권고와도 맞는다. 정해진 경로가 있는 작업은 **자율 에이전트가 아니라 워크플로**로 만든다(검색 요약).
5. **차트 이미지는 보조, 수치가 주입력 (STRATEGY v0.2 지지).** 모의매매에서 이미지 유무를 A/B로 비교한다. 이미지가 성과를 개선하지 못하면 알림용 첨부로만 남긴다.
6. **"확신도 0.6" 기준에 대한 지적.** LLM이 스스로 말하는 확신도는 정답 여부와 상관이 거의 없다는 실험 결과가 있다(gist 감사, 단일 저자). 0.6은 **필터로는 유지**하되 **리스크 통제로 간주하지 않는다**. 모의 신호가 50건 이상 쌓이면 확신도 구간별 적중률을 보고 **다시 보정**한다. 가능하면 확신도를 **코드 점수(규칙 충족 개수 등)와 결합**한다.
7. **Claude 층 검증은 전향적 모의매매로만 (원칙 명문화).** 과거 구간을 Claude에게 판단시키는 백테스트는 룩어헤드 편향 때문에 **하지 않는다**. 실거래 전환 기준을 숫자로 정해 둔다. 예시(외부 감사에서 차용):
   - 모의 신호 N건 이상 (예: 50건)
   - 방향 적중률의 윌슨 95% 하한 > 50%
   - 롱·숏 적중률 격차 < 10%p
   - 코드 단독 대비 Claude가 성과를 개선했는가 (STRATEGY §9-3)
8. **사람 승인을 형식적으로 만들지 않는 장치.** 알림에 **반대 근거와 무효화 조건**을 함께 싣는다. 하루 알림 수에 상한을 둔다. **승인율·거부율·거부 신호의 사후 성과**를 주간 리포트로 만든다. 승인율이 100%에 가까우면 사람 승인이 형식화됐다는 신호다.
9. **하드 가드 두 번 검사 + 실패 시 닫힘.** 알림 전(①)과 주문 직전(②)에 검사한다. 조회 실패, 스키마 위반, Claude refusal(`stop_reason` 확인)이 생기면 주문하지 않는다. 승인 후 가격이 정해진 폭 이상 움직이면 **재승인**을 받는다(Vibe-Trading의 위임 범위 재승인 방식).
10. **"시간 제한 청산" 추가 검토 (신규 제안).** Hummingbot의 삼중 장벽처럼, 정해진 시간 안에 익절도 손절도 안 된 포지션은 알림을 보내거나 청산한다. 워뇨띠의 "보유 시간" 분석(STRATEGY)과 함께 백테스트로 값을 정한다. 이는 **제안이며 근거가 약하므로** 백테스트 전까지 기본값은 "알림만"으로 둔다.
11. **레버리지 3배, 격리, 전체 노출 1.0배 유지 (확인).** Alpha Arena에서 손실의 공통 원인이 과도한 레버리지였다는 해설(검색 요약)과 워뇨띠의 포트폴리오 1.5~2배(STRATEGY §8)가 모두 이 보수적 설정을 뒷받침한다.

### 3.3 다음 단계에 넘길 확인 필요 항목

| # | 항목 | 확인 방법 |
|---|---|---|
| 1 | freqtrade `forceenter`의 `max_open_trades` 무시 문제(#7489)가 해결됐는지 | PoC에서 동시 호출로 시험하거나 이슈 스레드 확인 |
| 2 | `custom_stoploss`로 신호별 절대 손절가를 첫 체결 직후 거래소 손절에 바로 반영할 수 있는지 (`after_fill`, 60초 갱신 주기와의 관계) | PoC (드라이런 → 테스트넷) |
| 3 | 바이낸스 선물 테스트넷을 freqtrade로 연결할 수 있는지, 테스트넷 호가가 실거래와 얼마나 다른지 | PoC |
| 4 | Condor의 Claude 지원 여부(OpenRouter 경유)와 라이선스 | README·LICENSE 파일 재확인 |
| 5 | Jesse Live Trade 플러그인의 현재 가격·조건 | jesse.trade 공식 사이트 (현재 차단) |
| 6 | Alpha Arena 시즌1 공식 최종 수치 | nof1.ai 원문 (현재 차단) |
| 7 | Vibe-Trading의 텔레그램 지원 여부 (README 요약 두 번의 결과가 엇갈림) | README 원문 직접 확인 |
| 8 | 거래소별 서브계정 제공 여부 (봇 전용 계정 분리) | 거래소 담당 리서처에게 이관 |

---

## 4. 출처 목록

표기: [직접] 직접 열람 · [API] GitHub 검색 API 또는 PyPI JSON 직접 조회 · (검색 요약) 검색 결과 요약만 확인

**오픈소스 봇**
1. freqtrade 저장소 — https://github.com/freqtrade/freqtrade [API: 스타 54,910, push 2026-09-29, GPL-3.0]
2. freqtrade README — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/README.md [직접]
3. freqtrade 텔레그램 문서 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/telegram-usage.md [직접]
4. freqtrade REST API 문서 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/rest-api.md [직접]
5. freqtrade 전략 콜백 문서 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/strategy-callbacks.md [직접]
6. freqtrade 레버리지 문서 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/leverage.md [직접]
7. freqtrade 손절 문서 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/stoploss.md [직접]
8. freqtrade 거래소별 문서 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/exchanges.md [직접]
9. freqtrade 보호장치 문서 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/includes/protections.md [직접]
10. freqtrade 웹훅 문서 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/webhook-config.md [직접]
11. freqtrade 이슈 #7489 (forceenter와 max_open_trades) — https://github.com/freqtrade/freqtrade/issues/7489 [직접]
12. freqtrade 텔레그램 문서(공식 사이트) — https://www.freqtrade.io/en/stable/telegram-usage/ (검색 요약)
13. PyPI 버전 정보 — https://pypi.org/pypi/freqtrade/json , https://pypi.org/pypi/ccxt/json , https://pypi.org/pypi/python-telegram-bot/json , https://pypi.org/pypi/OctoBot/json , https://pypi.org/pypi/jesse/json , https://pypi.org/pypi/nautilus_trader/json , https://pypi.org/pypi/hummingbot/json [API]
14. Hummingbot — https://github.com/hummingbot/hummingbot [API], README https://raw.githubusercontent.com/hummingbot/hummingbot/master/README.md [직접]
15. Condor — https://github.com/hummingbot/condor [API], README https://raw.githubusercontent.com/hummingbot/condor/main/README.md [직접]
16. Condor 소개글 — https://hummingbot.org/blog/introducing-condor-the-open-source-harness-for-trading-agents/ (검색 요약)
17. Condor 첫 에이전트 문서 (리스크 한도) — https://condor.hummingbot.org/getting-started/first-agent (검색 요약)
18. Hummingbot API 문서 — https://hummingbot.org/hummingbot-api/ (검색 요약)
19. Hummingbot PositionExecutor — https://hummingbot.org/v2-strategies/executors/positionexecutor/ (검색 요약), 이슈 #7503 https://github.com/hummingbot/hummingbot/issues/7503 (검색 요약)
20. Jesse — https://github.com/jesse-ai/jesse [API], README https://raw.githubusercontent.com/jesse-ai/jesse/master/README.md [직접]
21. Jesse 라이브 플러그인·가격 — https://docs.jesse.trade/docs/livetrade.html , https://gainium.io/review/jesse , https://salehmir.medium.com/the-live-trade-plugin-is-open-for-early-access-3d6b80cc5c1 (검색 요약)
22. OctoBot — https://github.com/Drakkar-Software/OctoBot [API], README https://raw.githubusercontent.com/Drakkar-Software/OctoBot/master/README.md [직접]
23. OctoBot ChatGPT·텔레그램·백테스트 — https://www.octobot.cloud/en/guides/octobot-trading-modes/chatgpt-trading , https://www.octobot.cloud/en/guides/octobot-interfaces/telegram , https://www.octobot.cloud/en/blog/trading-using-chat-gpt , https://www.octobot.cloud/en/guides/octobot-usage/backtesting (검색 요약)
24. Passivbot — https://github.com/enarjord/passivbot [API], README https://raw.githubusercontent.com/enarjord/passivbot/master/README.md [직접]
25. NautilusTrader — https://github.com/nautechsystems/nautilus_trader [API], README https://raw.githubusercontent.com/nautechsystems/nautilus_trader/develop/README.md [직접]

**시그널·상용 서비스**
26. TradingView 웹훅 설정·포트 제한 — https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/ , https://www.tradingview.com/support/solutions/43000529314-i-cannot-send-webhook-to-a-url-with-a-port-number/ (검색 요약)
27. TradingView 웹훅 요건 정리 (유료 플랜, IP) — https://blog.traderspost.io/article/tradingview-webhook-alerts-documentation (검색 요약)
28. Binance Futures Signal Trading — https://www.binance.com/en/support/announcement/binance-futures-launches-signal-trading-with-webhook-integration-0508c94932e74f0a8b0788c085573044 , https://www.binance.com/en/support/faq/how-to-set-up-signal-trading-with-tradingview-3f57291b56474f5e900cc4b754f61ff3 (검색 요약)
29. 3Commas Signal Bot — https://help.3commas.io/en/articles/8529406-signal-bot-custom-signal-type , https://help.3commas.io/en/articles/8894481-signal-bot-json-file-in-custom-signal-type (검색 요약)
30. 3Commas API 키 유출 (2022-12) — https://www.coindesk.com/tech/2022/12/28/anonymous-twitter-user-leaks-alleged-3commas-api-database , https://cointelegraph.com/news/3commas-ceo-confirms-api-key-leak-following-warning-from-cz , https://www.halborn.com/blog/post/explained-the-3commas-breach-december-2022 , https://www.bitdefender.com/en-us/blog/hotforsecurity/the-fbi-is-reportedly-probing-3commas-after-api-keys-leaked-on-twitter (검색 요약)
31. WunderTrading — https://wundertrading.com/en/tradingview-automated-trading (검색 요약)
32. Cornix — https://help.cornix.io/en/articles/8800202-what-is-the-cornix-signals-bot , https://cornix.io/features/signals-bots/ , https://help.cornix.io/en/articles/5814976-cornix-signals-vs-trades (검색 요약)
33. 자체 호스팅 TradingView→바이낸스→텔레그램 봇 — https://github.com/h4rsh-vishwakarma/TradingBot , https://github.com/ytrevor81/TradingView-Binance-Telegram-Bot , https://github.com/51bitquant/binance-tradingview-webhook-bot (검색 요약)

**LLM·AI 트레이딩**
34. TradingAgents — https://github.com/TauricResearch/TradingAgents [API], README https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/README.md [직접], 논문 https://arxiv.org/abs/2412.20138 (미열람)
35. ai-hedge-fund — https://github.com/virattt/ai-hedge-fund [API], README https://raw.githubusercontent.com/virattt/ai-hedge-fund/main/README.md [직접]
36. Vibe-Trading — https://github.com/HKUDS/Vibe-Trading [API], README https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/README.md [직접]
37. nofx — https://github.com/NoFxAiOS/nofx [API]
38. FinRobot — https://github.com/AI4Finance-Foundation/FinRobot [API]
39. awesome-alpha-arena (Alpha Arena 복제 프로젝트 목록) — https://github.com/kukapay/awesome-alpha-arena [직접]
40. LLM_trader — https://github.com/qrak/LLM_trader [직접·API]
41. 조코딩 gpt-bitcoin — https://github.com/youtube-jocoding/gpt-bitcoin [직접·API], 강의 https://www.udemy.com/course/gpt-bitcoin-ai-agent/ (검색 요약)
42. Alpha Arena 시즌1 결과 — https://www.iweaver.ai/blog/alpha-arena-ai-trading-season-1-results/ , https://protos.com/llm-crypto-trading-contest-finds-llms-cant-trade-crypto/ , https://www.datawallet.com/crypto/alpha-arena-nof1-ai-explained , https://news.bitcoin.com/6-bots-with-real-money-hyperliquid-hosts-first-ever-ai-trading-showdown/ (검색 요약)
43. 비전 LLM 차트 판독 감사 (Roman Antonov, 2026-04) — https://gist.github.com/roman-rr/c1cd675f7c35b68ae5ac281c30080166 [직접]
44. Anthropic Vision 문서 (한계·이미지 토큰 비용) — https://platform.claude.com/docs/en/build-with-claude/vision [직접]
45. FinChart-Bench — https://aclanthology.org/2026.acl-long.615/ ; MME-Finance — https://arxiv.org/pdf/2411.03314 , https://hithink-research.github.io/MME-Finance/ (검색 요약)
46. LLM 룩어헤드 편향 연구 — https://arxiv.org/html/2512.23847v2 , https://arxiv.org/html/2605.24564 , https://arxiv.org/html/2602.14233v1 (검색 요약)

**사람 승인·리스크 통제 패턴**
47. Claude Agent SDK 권한 평가 순서 — https://code.claude.com/docs/en/agent-sdk/permissions [직접]
48. Anthropic "Building effective agents" — https://www.anthropic.com/research/building-effective-agents (검색 요약)
49. LangChain/LangGraph Human-in-the-loop — https://docs.langchain.com/oss/python/langchain/human-in-the-loop (검색 요약)
50. FIA 자동매매 리스크 통제 모범 사례 — https://www.fia.org/sites/default/files/2024-07/FIA_WP_AUTOMATED%20TRADING%20RISK%20CONTROLS_FINAL_0.pdf (검색 요약)
51. 자동화 편향·승인 피로 (2차 정리글, 신뢰도 낮음) — https://tianpan.co/blog/2026/06/25/approval-fatigue-how-human-in-the-loop-gates-decay-into-rubber-stamps , https://dev.to/brennhill/automation-bias-why-people-rubber-stamp-ai-and-how-to-fix-it-2587 (검색 요약)
52. python-telegram-bot — https://github.com/python-telegram-bot/python-telegram-bot [API], 인라인 키보드 예제 https://github.com/python-telegram-bot/python-telegram-bot/blob/master/examples/inlinekeyboard.py (검색 요약)
53. 텔레그램 토큰 하나당 폴러 하나 제약 — https://github.com/python-telegram-bot/python-telegram-bot/issues/1143 , https://github.com/python-telegram-bot/python-telegram-bot/issues/4499 (검색 요약)
