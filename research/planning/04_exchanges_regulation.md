# 04. 거래소 선택과 한국 규제·세금

> 작성일: 2026-09-29 · 작성: 리서처(exchanges_regulation) · 상태: 조사 보고서 (코드 없음)
> 관련 문서: [docs/PLAN.md](../../docs/PLAN.md) (기획 v0.1, 특히 §3.2 거래소·§4 보안), [01_existing_systems.md](./01_existing_systems.md) (§5 미해결 8번 "거래소별 서브계정"을 이 문서가 넘겨받음)
> 표기: **[직접]** = GitHub·PyPI 원문을 직접 열어 확인 · **(검색 요약)** = 웹 검색 결과 요약으로만 확인(원문 미열람) · **확인 필요** = 확인하지 못함(추측하지 않음)
> 이 문서는 법률·세무 자문이 아니다. 규제·세금 부분은 모두 **실거래 전에 세무사·변호사에게 확인**해야 한다.

---

## 1. 핵심 요약 (5줄)

1. **기본 거래소는 바이낸스 USDⓈ-M 선물을 유지할 것을 권고한다.** 무기한 선물 거래량 1위다(2026년 상반기 CEX 점유율 약 33~35%, 검색 요약). Ed25519 키, IP 제한, 출금 권한 분리, 서브계정을 제공하고, 모의 환경도 테스트넷과 데모 트레이딩 두 가지가 있다. ccxt 인증 거래소이기도 하다 [직접]. 예비 후보는 OKX, 그다음이 Bybit다. **Bitget은 2026-09-24 해킹(약 3.9억 달러) 직후라 보류**한다. **Hyperliquid**는 USDC로 정산하고 지갑 개인키를 직접 관리해야 하며 규제도 없어서 2단계 검토 대상으로 둔다.
2. **보안의 핵심은 거래소 선택보다 노출을 줄이는 것이다.** 후보 5곳 모두 사고 이력이 있다. 바이낸스 2019년(API 키 탈취, 7,000 BTC), 바이비트 2025년(약 14~15억 달러), OKX 2020년(출금 수 주 중단), 비트겟 2026년, Hyperliquid 2025년(시세 조작 3건)이다. 그래서 봇 전용 서브계정에 필요한 증거금만 둔다. 키는 출금 권한이 없고 IP가 제한된 Ed25519 키를 쓴다. 메인 계정에는 출금 주소 화이트리스트를 건다.
3. **한국 규제에서 커지는 것은 "처벌"보다 "접근성" 위험이다.** FIU(금융정보분석원)에 신고한 사업자는 28곳뿐이고, 해외 선물 거래소는 모두 미신고다. 불법 책임은 거래소에 있고, 이용자 개인을 처벌하는 규정은 현재 없다(검색 요약). 하지만 차단은 계속 넓어지고 있다. 2025-03에 앱 17곳이 차단됐고, 2026-01-28 구글 정책으로 모든 미신고 거래소 앱이 대상이 됐다. 웹사이트 차단 기준도 2026-09 말을 목표로 마련 중이다. 국내 거래소에서 미신고 거래소로 보내는 송금도 제한된다. 그래서 **거래소를 바꿀 수 있는 설계가 보험**이 된다.
4. **세금: 가상자산 소득 과세는 2027-01-01 시행이 정부 방침이다.** 2026년 세제개편안에 추가 유예가 없고, 250만 원을 공제한 뒤 22%를 매긴다. 다만 국회는 연말에 최종 의결하고, 2030년 유예 법안도 발의돼 있다. 그래서 **"사실상 확정에 가깝지만 최종 확정은 아님"**이다. 무기한 선물 손익이 어떤 소득으로 분류되는지는 **불명확**하다. 2027년부터 CARF(국가 간 가상자산 거래정보 교환)가 시작된다. → 시스템은 체결·수수료·펀딩비·입출금을 세무용으로 모두 남겨야 한다. 해외 거래소 잔액이 월말 중 하루라도 5억 원을 넘으면 해외금융계좌 신고 대상이다.
5. **ccxt로 "설정만 바꾸면 교체된다"는 PLAN §3.2의 표현은 과장이다.** 거래소마다 다음이 다르다.
   - 정산 통화(USDT/USDC)와 심볼
   - 포지션 모드
   - 손절 주문 방식. 바이낸스가 2025-12-09에 조건부 주문을 새 엔드포인트로 옮기자 봇 손절이 실패한 사례가 있다 [직접]
   - 모의 환경 호출법, 키 만료 규칙, 서버 국가 제한

   → 거래소 어댑터, 거래소별 데모 통합 테스트, 시작 시 자가 점검, ccxt 버전 고정이 필요하다.

---

## 2. 본문

### 2.0 조사 방법과 한계

| 항목 | 내용 |
|---|---|
| 웹 검색 | 서로 다른 검색어로 **47회** 검색했다(영어·한국어). 거래소 공식 사이트, 개발자 문서(developers.binance.com, okx.com 등), 한국 정부·언론 사이트는 조직 네트워크 정책으로 **직접 열람이 차단**됐다. 차단은 우회하지 않았다. 그래서 이 문서의 한국 규제·세금 내용은 **모두 (검색 요약)**이다 |
| 직접 열람 [직접] | ① 바이낸스 API 키 종류 문서 (GitHub `binance/binance-spot-api-docs`) ② 바이비트 API 문서 원본 (GitHub `bybit-exchange/docs`의 데모·키 생성·서브키 문서) ③ ccxt README와 거래소별 파이썬 소스 (binance·bybit·okx·bitget·hyperliquid) ④ PyPI 버전 정보 (ccxt, pybit, hyperliquid-python-sdk) ⑤ freqtrade 거래소 문서와 이슈 #12610 ⑥ Hyperliquid 파이썬 SDK README |
| 한계 | 수수료·점유율·규제는 자주 바뀐다. 가입과 실거래 전에 공식 페이지에서 다시 확인해야 한다. 검색 요약은 요약 모델을 거친 것이라 수치가 원문과 다를 수 있다. 출처끼리 수치가 다르면 둘 다 적었다 |

**용어 (처음 한 번만 풀이)**
- **무기한 선물(perpetual)**: 만기가 없는 선물 계약. 가격을 현물에 붙여 두려고 롱과 숏이 주기적으로 **펀딩비**를 주고받는다
- **USDⓈ-M**: USDT 같은 스테이블코인을 증거금·정산 통화로 쓰는 선물 (바이낸스 명칭)
- **CEX / DEX**: 회사가 자산을 보관하는 중앙화 거래소 / 스마트컨트랙트·블록체인으로 운영되고 내 지갑으로 거래하는 탈중앙 거래소
- **준비금 증명(PoR, Proof of Reserves)**: 거래소가 고객 예치금만큼 자산을 실제로 갖고 있음을 보여 주는 공개 검증. **머클 트리**는 내 잔액이 합계에 포함됐는지 각자 확인하게 해 주는 해시 구조다
- **HMAC / RSA / Ed25519**: API 요청에 서명하는 방식. HMAC은 거래소와 내가 **같은 비밀값**을 나눠 갖는다. RSA·Ed25519는 **비대칭 키**다. 나는 개인키로 서명하고 거래소에는 공개키만 준다. 그래서 거래소 쪽에서 새어 나가도 내 서명키는 안전하다
- **IP 화이트리스트**: 등록한 IP에서 온 요청만 받는 설정
- **서브계정**: 한 사람 명의 아래 잔고와 키를 분리한 하위 계정
- **테스트넷 / 데모 트레이딩**: 가상 자금으로 주문을 시험하는 환경. 거래소마다 구조가 다르다(§2.5)
- **메이커 / 테이커**: 호가창에 주문을 **걸어 두는** 쪽(메이커, 보통 수수료가 싸다) / 걸린 주문을 **바로 체결시키는** 쪽(테이커)
- **ADL(자동 디레버리징)**: 청산된 포지션의 손실을 메울 수 없을 때, 이익 중인 반대편 포지션을 강제로 줄이는 장치
- **VASP / FIU / 특금법**: 가상자산사업자 / 금융위원회 산하 금융정보분석원 / 특정금융정보법. 한국에서 가상자산 영업을 하려면 FIU에 신고해야 한다
- **트래블룰**: 거래소 간 가상자산을 옮길 때 보내는 사람과 받는 사람 정보를 함께 넘기게 하는 규칙
- **CARF**: OECD의 암호화자산 보고 체계. 나라끼리 자국민의 해외 거래 정보를 교환한다

---

### 2.1 후보 거래소 한눈에 보기 — 규모와 점유율

| 거래소 | 형태 | 무기한 선물 점유율 (2026) | 비고 |
|---|---|---|---|
| **Binance** | CEX | 2026년 상반기 CEX 무기한 선물 거래량의 **35%** [1] · 1~4월 33% [2] · 1분기 파생 거래량 약 4.90조 달러(상위 10곳 중 34.9%) [3] | 2~3위 합계보다 크다 [3] (모두 검색 요약) |
| **OKX** | CEX | 상반기 16% [1] · 1분기 약 2.19조 달러 [3] | 2위 |
| **Bybit** | CEX | 상반기 11% [1] · 1분기 약 1.49조 달러 [3] | 3위 |
| MEXC · Gate | CEX | 상반기 10% · 9% [1] | 한국에서는 MEXC 앱이 2025-03부터 차단됨(§2.8) |
| **Bitget** | CEX | 상반기 상위 5위 밖 [1] | 2026-09-24 해킹(§2.2) |
| **Hyperliquid** | DEX (자체 체인) | 전체 무기한 선물 **미결제약정의 약 9.3%** (2026-07 초) [5]. 온체인 무기한 선물 중 약 1/3~40% 이상 [4][6] | 출처마다 온체인 점유율이 크게 다르다(33~70%). **DEX 1위라는 점만 확실** |

- Binance·OKX·Bybit 세 곳이 파생 거래량의 60% 이상을 차지한다 [3] (검색 요약)
- DEX의 미결제약정 점유율은 2026-04 기준 13.5% 이상으로 커지고 있다 [4] (검색 요약)
- **우리에게 주는 의미**: BTC/USDT는 어느 대형 거래소에서도 유동성이 충분하다. 우리 주문 규모(수백~수천 USDT)에서는 체결 품질 차이가 거의 없다. 따라서 **선택 기준은 규모보다 보안·API·규제 접근성**이어야 한다.

### 2.2 보안 사고와 사건 이력

| 거래소 | 시기 | 내용 | 고객 피해 처리 | 우리에게 주는 교훈 |
|---|---|---|---|---|
| Binance | 2019-05 | 약 7,000 BTC(약 4,000만 달러) 탈취. 해커가 **다수 사용자의 API 키와 2FA 코드**를 확보했다 [10] (검색 요약) | 고객 보호 기금 SAFU로 전액 보전 [10] | **API 키 유출이 곧 공격 경로다.** 출금 권한 금지와 IP 제한이 필수인 이유다 |
| Binance | 2025-10-10 | 관세 발표로 약 190억 달러가 청산된 폭락이 있었다. 이때 바이낸스 **내부 가격 기준으로 USDe가 0.65달러까지 이탈**했고, 이를 담보로 쓴 포지션이 연쇄 청산됐다 [11] | 약 3.28억 달러 직접 보상 [11] (검색 요약) | **증거금은 USDT 하나만** 쓴다. 이색 담보(USDe, wBETH 등)나 멀티에셋 모드는 쓰지 않는다 |
| Binance | 2025-12-09 | USDⓈ-M 선물의 조건부 주문(STOP_MARKET 등)이 새 **Algo Order 엔드포인트**로 옮겨졌다. 옛 방식으로 보낸 손절 주문은 `-4120` 오류로 거부됐다. freqtrade는 이 때문에 손절 주문을 걸지 못했다 [22] [직접] | 해당 없음 (API 변경) | **거래소 API는 예고 없이 바뀐다.** "진입 후 손절 주문이 실제로 거래소에 존재하는지" 확인하는 절차가 필수다 |
| Bybit | 2025-02-21 | 콜드월렛에서 ETH 약 40만 개(약 14~15억 달러)가 탈취됐다. **역대 최대 거래소 해킹**이다. 공격자는 멀티시그 지갑 서비스 Safe{Wallet} 개발자 PC를 장악하고, 서명 화면에 악성 스크립트를 넣어 수신 주소를 바꿨다. FBI는 북한 라자루스 소행으로 지목했다 [7] | 약 72시간 안에 긴급 대출·매입으로 ETH 부족분을 메웠고, 출금을 제한 없이 처리했다. 감사받은 PoR로 1:1 회복을 공표했다 [8] (검색 요약) | 대형 거래소도 **공급망 공격**에 뚫린다. 대응은 모범적이었지만, 우리 쪽 대책은 역시 "필요한 만큼만 예치"다 |
| OKX (당시 OKEx) | 2020-10 | 개인키 보유자(창업자)가 수사에 협조하느라 연락이 끊겨 **출금이 수 주간 중단**됐다 [13] (검색 요약) | 이후 재개 | 해킹이 아니어도 **출금 동결** 위험이 있다 |
| OKX | 2025-02 | 미국 법무부에 무등록 송금업·자금세탁방지 위반으로 **유죄를 인정**하고 약 5.04억 달러를 냈다 [12] | 해당 없음 | 규제 위험 신호다 (한국 이용자에게 직접 영향은 확인 필요) |
| Bitget | 2025-04 | VOXEL 선물 이상 거래. 봇 오류로 시세 조작성 차익이 생겼고, 해당 계정을 **롤백(거래 취소)**했다 [14] | 롤백 | 거래소가 **체결된 거래를 사후에 취소**할 수 있다 |
| **Bitget** | **2026-09-24** | 핫·웜 월렛에서 **약 3.875억 달러**가 유출됐다. 백엔드 지갑 인프라의 승인 데이터 위조 취약점이 원인이고, 개인키는 유출되지 않았다고 발표했다 [15] | 보호 기금으로 전액 보전한다고 발표. 9/28 BTC부터 **단계적으로 출금 재개**, 10/2 전면 정상화 예정 [15] (검색 요약) | **5일 전 사건이다.** 원인 분석 보고서가 나올 때까지 신규 채택을 보류한다 |
| Hyperliquid | 2025-03 | JELLY 토큰 시세 조작. **검증인 투표로 상장폐지하고 정산 가격을 정했다** → "탈중앙인데 개입했다"는 비판 [16] | 커뮤니티 금고(HLP)가 처리 | DEX도 운영 주체가 개입할 수 있다 |
| Hyperliquid | 2025-07 | API 서버 장애로 포지션이 37분간 조작 불능. 약 199만 달러 환불 [16] | 환불 | 장애 동안 **손절을 못 할 수 있다** |
| Hyperliquid | 2025-10-10 | 폭락 때 **ADL 34,983건**(지갑 19,337개)이 발생했다 [11] | — | 이익 중인 포지션도 강제로 줄어들 수 있다 |
| Hyperliquid | 2025-11 | POPCAT 시세 조작으로 HLP에 약 490만 달러 부실이 생겼다 → 미결제약정 한도와 레버리지 단계를 강화했다 [16] | HLP 부담 | BTC처럼 유동성이 큰 종목과는 거리가 있다 |
| (참고) 업비트 | 2025-11-27 | 솔라나 핫월렛에서 약 445억 원 유출. 라자루스 소행 추정 [50] | 업비트 부담 | **FIU에 신고한 국내 거래소도 해킹된다** |

**정리**: 후보 중 "사고 없는 거래소"는 없다. 개인 계정 입장에서 현실적인 위험 순서는 다음과 같다(분석 의견).
① **내 API 키·계정 탈취** → ② **봇 버그**(손절 누락 등) → ③ **규제로 접근이 끊기는 것** → ④ 거래소 파산·해킹.
④는 PoR과 대형 거래소 선택으로 줄이고, ①~③은 우리 설계로 막는다.

### 2.3 준비금 증명(PoR)

| 거래소 | 방식 | 최근 공개 수치 | 확인 수준 |
|---|---|---|---|
| Binance | 월 1회. 머클 트리와 zk-SNARK(영지식 증명: 내용을 드러내지 않고 "부채보다 자산이 많다"를 증명) | 2026-08-01 기준 BTC·ETH **100.25%**, USDT 103.62%, USDC 107.64% [17] | 검색 요약 |
| OKX | 월 1회. 머클 트리와 zk-STARK, Hacken 감사 | 2025년 말 37번째 보고서에서 BTC·USDT 105% [17] | 검색 요약 |
| Bybit | Hacken 감사 PoR | 해킹 직후인 2025-02-26에도 100% 초과 [17] | 검색 요약 |
| Bitget | 머클 트리. 오픈소스 검증 도구 | 2026-09 보고서(46번째)에서 총 **135%** [17]. **9/24 해킹 전 수치인지 확인 필요** | 검색 요약 |
| Hyperliquid | 해당 없음. 자산이 블록체인에 공개돼 누구나 확인할 수 있다 | — | — |

- **한계**: PoR은 특정 시점의 "자산 ≥ 고객 예치금"만 보여 준다. 숨은 부채, 스냅샷 전후의 자금 이동, 운영상 출금 동결은 보여 주지 못한다(일반적 한계, 분석 의견).
- **실무 규칙**: 우리 봇 계정의 잔액이 매달 PoR 머클 트리에 포함됐는지 확인하는 절차를 운영 체크리스트에 넣는다(바이낸스·OKX·Bitget 모두 사용자 검증 기능 제공, 검색 요약).

### 2.4 API 보안 기능 비교 (핵심 표)

| 기능 | **Binance** | **Bybit** | **OKX** | **Bitget** | **Hyperliquid** |
|---|---|---|---|---|---|
| 서명 키 종류 | **Ed25519(권장)**, RSA, HMAC(**폐기 예정**) [18] [직접] | HMAC(시스템 발급) 또는 **RSA(직접 생성, 개인키는 거래소가 모름)** [23] [직접] | HMAC와 패스프레이즈 [24] (검색 요약). ccxt 코드에 RSA·Ed25519 서명 없음 [30] [직접] | HMAC와 패스프레이즈 [25]. ccxt 코드에 RSA 서명 없음 [30] [직접]. 거래소 쪽 RSA 제공 여부는 확인 필요 | 이더리움식 지갑 개인키(secp256k1) 서명 [30] [직접] |
| ccxt가 비대칭 키 서명 지원 | 예. 비밀값이 PEM 개인키면 Ed25519/RSA로 서명 [30] [직접] | 예. PEM이면 RSA [30] [직접] | 아니오 | 아니오 | 해당 없음 |
| IP 화이트리스트 | 있음. **IP 제한 없는 시스템 발급 키는 "읽기"만 가능**(2023-01-30부터) [19] (검색 요약) | 있음. **IP를 묶지 않은 키는 90일 뒤 무효**. 비밀번호를 바꾸면 7일 뒤 무효 [23] [직접] | 있음(최대 20개). IP 없는 거래·출금 키는 **14일 미사용 시 삭제** [24] (검색 요약) | 있음(최대 10개 권장) [25] (검색 요약) | 없음. 블록체인 서명 방식이라 IP 개념이 없다 |
| 출금 권한 분리 | 있음. 출금 권한은 **IP 제한이 있어야만** 켤 수 있다 [19] (검색 요약) | 있음(권한 목록에 Withdrawal 별도) [23] [직접] | 있음(읽기/거래/출금) [24] | 있음(읽기/거래/이체/출금) [25] | **API 지갑(에이전트)은 주문만 가능하고 출금은 원천적으로 불가능** [26] (검색 요약). freqtrade도 "실제 지갑 키 말고 API 지갑을 쓰라"고 명시 [31] [직접] |
| 서브계정 | 있음. 본인 인증과 2FA 필요. 개수 한도는 출처마다 다르다(5~20) → 확인 필요 [20] (검색 요약) | 있음. 서브계정별 API 키 발급 API가 있다 [23] [직접] | 있음 (세부 조건 확인 필요) | 있음 (일반 사용자 조건 확인 필요) | 있음 (볼트와 동시 사용 불가) [31] [직접] |
| 출금 주소 화이트리스트 | 있음. 새 주소는 일정 시간 출금을 막는 옵션 [29] | 있음. 새 주소 24시간 잠금 [29] | 있음. 새 주소 약 24시간 잠금 [29] | 있음 [29] | 해당 없음 (내 지갑에서 직접 관리) |
| 피싱 방지 코드 | 있음 [29] | 확인 필요 | 있음 [29] | 있음 [29] | 해당 없음 |

**보안 담당자 관점의 판단 (분석 의견)**
- **바이낸스 Ed25519가 가장 좋은 선택지다.** 개인키를 우리 서버에서 만들고 거래소에는 공개키만 등록한다. 그래서 거래소 쪽에서 키 정보가 새도 서명을 위조할 수 없다. 2019년 바이낸스 사고처럼 "키 유출 → 도용"되는 경로를 한 단계 줄여 준다. 게다가 HMAC은 바이낸스가 **폐기 예정**이라고 밝혔다 [18]. 처음부터 Ed25519로 시작해야 나중에 옮겨 가는 일이 없다.
- **Hyperliquid의 API 지갑 모델은 구조상 가장 강하다.** "출금 불가"를 거래소 설정이 아니라 **프로토콜이 강제**하기 때문이다. 하지만 메인 지갑 개인키(= 전 재산)를 사람이 직접 관리해야 한다. 코딩 비전문가인 1인 운영자에게는 이 부담이 이점보다 크다.
- 어느 거래소든 **키 만료 규칙이 서로 다르다** (Bybit: IP 미지정 90일, OKX: 14일 미사용). 운영 중에 봇이 갑자기 인증 오류로 멈출 수 있다. → 키 만료일을 기록하고 교체 주기를 정한다(§3.2).

### 2.5 테스트넷·데모 환경

| 거래소 | 환경 | 주소 (REST) | ccxt에서 켜는 법 [직접] | 비고 |
|---|---|---|---|---|
| Binance | ① 선물 **테스트넷** | testnet.binancefuture.com | `set_sandbox_mode(True)` | 기존 환경 |
| Binance | ② **데모 트레이딩** | demo-fapi.binance.com | `enable_demo_trading(True)` (①과 동시 사용 불가, 데모에서는 sapi 계열 API 미지원) | 새 환경. 두 환경의 차이는 바이낸스 FAQ에 있지만 차단돼 **확인 필요** [21] |
| Bybit | ① 테스트넷 | api-testnet.bybit.com | `set_sandbox_mode(True)` | 공식 문서가 "테스트넷에서 데모를 쓰는 건 무의미하다"고 설명 [23] [직접] |
| Bybit | ② **데모 트레이딩** (권장) | api-demo.bybit.com | `enable_demo_trading(True)` | **실계정에서 데모 모드로 전환해 키를 만든다.** 사용자 ID가 따로 나오고, 주문 기록은 **7일만 보관**된다. 일부 API는 제공되지 않는다 [23] [직접] |
| OKX | 데모 트레이딩 | 실서버와 같은 주소, 헤더 `x-simulated-trading: 1` | `set_sandbox_mode(True)` | 데모 키는 만료되지 않는다 [24] (검색 요약) |
| Bitget | 데모 트레이딩 | 실서버와 같은 주소, 헤더 `PAPTRADING: 1` | `set_sandbox_mode(True)` 또는 `enable_demo_trading(True)` | 데모 모드에서 별도 키를 만든다 [25] |
| Hyperliquid | 테스트넷 | api.hyperliquid-testnet.xyz | `set_sandbox_mode(True)` | **메인넷에 같은 주소로 먼저 입금한 이력이 있어야** 테스트용 USDC(1,000)를 받는다 [27] (검색 요약) → 완전 무위험으로 시작할 수 없다 |

- **PLAN 보완점**: PLAN §3.2의 "선물 테스트넷 제공"은 맞다. 다만 2026년 현재 바이낸스와 바이비트는 **모의 환경이 두 종류**이고, ccxt 호출법도 다르다. 4단계 시험 구현(PoC)에서 **두 환경 모두** 연결해 호가·체결이 실거래와 얼마나 다른지 기록한 뒤 하나를 고르는 것을 권한다.

### 2.6 수수료 — 우리 규모에서는 선택 기준이 아니다

| 거래소 | 기본 메이커 / 테이커 (USDT 무기한) | 할인 |
|---|---|---|
| Binance | 0.020% / 0.050% | BNB로 내면 약 10% 할인 [28] |
| Bybit | 0.020% / 0.055% | — |
| OKX | 0.020% / 0.050% | OKB 보유 등급 할인 [28] |
| Bitget | 0.020% / 0.060% | — |
| Hyperliquid | 0.015% / 0.045% (USDC 정산) | 출시 뒤 기본 요율 변동 없음 [28] |

(모두 검색 요약 [28]. 가입 전 공식 수수료 페이지 확인 필요.)

**계산 예시 (사용자의 기존 리스크 규칙 적용)**
- 계좌 1,000 USDT, 증거금 ≤ 20% → 200 USDT, 레버리지 3배 → 포지션 명목 600 USDT
- 진입·청산 모두 테이커일 때 왕복 수수료: 바이낸스 600 × 0.05% × 2 = **0.60 USDT**, Hyperliquid 0.54 USDT → **한 번에 0.06 USDT 차이**
- 손절 2%에 걸리면 손실 600 × 2% = **12 USDT = 계좌의 1.2%**. 수수료는 손실 위험의 약 5%다
- → **수수료 차이는 거래소를 고를 이유가 못 된다.** 오히려 사용자 규칙(증거금 20% × 3배 × 손절 2%)이 사실상 **1회 최대 손실을 계좌의 1.2%로 제한**하고 있다는 점이 확인된다. 보수적인 좋은 규칙이다. 다만 손절 폭이 좁을수록 포지션을 키우는 "위험 고정형" 계산(1회 위험 = 계좌의 N%)으로 바꾸면 규칙이 더 명확해진다. 전략 문서에서 결정할 사항이다.
- 펀딩비 주기와 수준은 거래소마다 다르다 → **확인 필요**. 여러 날 들고 가는 포지션이라면 수수료보다 펀딩비가 더 클 수 있다.

### 2.7 ccxt 지원과 "교체 가능 설계"의 실제 차이

**ccxt 현황** [직접]: 최신 **4.5.84 (2026-09-24 배포)** [30]. Binance, Binance USDⓈ-M, Bybit, OKX, Bitget, Hyperliquid 모두 **"CCXT Certified"와 "CCXT Pro"(웹소켓 실시간)** 표시가 있다 [30].

**거래소를 바꿀 때 달라지는 것 (ccxt가 감춰 주지 못하는 차이)**

| 항목 | 차이 | 근거 |
|---|---|---|
| 정산 통화·심볼 | CEX는 `BTC/USDT:USDT`, Hyperliquid는 **USDC** 정산 (`BTC/USDC:USDC`) | ccxt hyperliquid 소스에 정산 통화가 USDC로 고정 [30] [직접] |
| 계정 모드 | 바이낸스는 **One-way 모드 + Single-Asset 모드**가 필수 (freqtrade 기준)이고, 레버리지를 쓰면 계정당 봇 하나. Bybit·Bitget은 (서브)계정 **전체**의 포지션 모드를 바꾼다. OKX는 **거래 중 모드 변경을 지원하지 않는다** | freqtrade 문서 [31] [직접] |
| 손절 주문 | 바이낸스는 2025-12-09부터 조건부 주문이 **Algo 엔드포인트**로 바뀌었다(ccxt 소스에 `algoOrder` 계열 엔드포인트가 들어 있다 [30] [직접]. 어느 버전부터인지는 확인 필요). Hyperliquid는 거래소 손절을 **스톱-리밋만** 지원한다(freqtrade 기준) | [22][31] [직접] |
| 과거 캔들 조회 | OKX는 **호출당 100개**, Hyperliquid는 **최근 5,000개까지만** 제공 | freqtrade 문서 [31] [직접] |
| 모의 환경 | `set_sandbox_mode`와 `enable_demo_trading`이 거래소마다 다른 환경을 가리킨다(§2.5) | ccxt 소스 [30] [직접] |
| 인증 정보 | OKX·Bitget은 **패스프레이즈**가 추가로 필요하고, Hyperliquid는 **지갑 주소 + 개인키**를 쓴다 | ccxt 소스 [30] [직접], freqtrade [31] |
| 키 수명 | Bybit 90일(IP 미지정), OKX 14일 미사용 삭제, 바이낸스는 IP 없으면 읽기 전용 | §2.4 |
| 서버 국가 제한 | **바이낸스는 서버가 있는 국가를 보고 API를 막는다**(캐나다·말레이시아·네덜란드·미국 등) | freqtrade 문서 [31] [직접]. Bybit 제한국 목록에 싱가포르·홍콩 포함 [51] (검색 요약, 서버 IP 적용 여부는 확인 필요) |
| 오류 코드·요청 한도 | 거래소별로 제각각. ccxt는 공통 예외로 바꿔 주지만 세부 원인은 거래소 코드로 봐야 한다 | 일반 |

→ **결론**: ccxt 덕분에 "주문 넣기" 코드는 90% 재사용된다. 하지만 **계정 모드, 손절 방식, 모의 환경, 키 관리, 서버 위치**는 거래소마다 따로 검증해야 한다(§3.3).

### 2.8 한국 거주자 관점 — 규제

#### 2.8.1 기본 구조 (특금법)

| 사실 | 내용 | 확인 수준 |
|---|---|---|
| 신고 의무 | 해외 사업자도 **내국인을 상대로 영업하면** 특금법상 FIU 신고 대상이다 [32][36] | 검색 요약 (FSC 보도자료 제목·요약) |
| 신고 현황 | 2026-06-24 FIU 발표: 신고 사업자는 두나무·코빗 등 **28곳**이고, "그 외에 국내에서 가상자산 거래를 지원하는 업체는 모두 불법" [36] | 검색 요약 |
| 해외 대형 거래소 | Binance·Bybit·OKX·Bitget 모두 **FIU 미신고** [35] | 검색 요약 |
| 이용자 개인 처벌 | 금융당국 입장은 "해외 거래소 우회 접속은 **거래소만 처벌**하고 거래자 처벌은 없다" (2021 보도) [38]. 법무법인 칼럼도 같은 취지다 [38] | 검색 요약. **최신 법령 기준으로 변호사 확인 필요** |
| 예외: 영업성 | 남을 대신해 매매하거나, 중개·알선하거나, 계속·반복적인 OTC(개인 간 장외) 거래를 **영업으로** 하면 본인이 미신고 사업자가 될 수 있다(특금법 제17조, 5년 이하 징역 또는 5천만 원 이하 벌금) [38] | 검색 요약 |
| 국내 법 보호 | 미신고 거래소에는 **가상자산이용자보호법**(2024-07 시행: 예치금 분리 보관, 불공정거래 규제 등)이 적용되지 않는다 → 분쟁·파산 때 국내 법 보호를 받기 어렵다 [36] | 검색 요약 |

#### 2.8.2 차단 조치 타임라인

| 시점 | 조치 | 대상 | 출처 |
|---|---|---|---|
| 2025-03-25 | FIU 요청으로 **구글플레이**가 앱 신규 설치·업데이트 차단 | KuCoin, MEXC, Phemex, XT.com, Bitrue 등 **17곳** (바이낸스·바이비트·OKX는 이때 대상 아님) | [32] |
| 2025 (시점 확인 필요) | **애플 앱스토어** 차단 | 14곳 | [33] |
| 2026-01-28 | **구글플레이 정책 시행**: 한국 대상 가상자산 거래소·지갑 앱은 **FIU 신고 사업자만** 배포 가능. 블랙리스트 방식이 아니라 **미신고 전체**가 대상 | Binance·Bybit·OKX 등 전부 | [34] |
| 2026-02 | "차단된다더니 여전히 설치됨" 보도 → 적용이 순차적·불완전함 | — | [34] |
| 2026-07-10 | Bybit 앱이 한국 구글플레이에서 검색·설치 불가 | Bybit | [35] |
| 2026-07-24~28 | OKX 앱 삭제 → **4일 뒤 복귀** (OKX 계열이 2026-05 코인원 지분 19.6%를 인수했고 7/22 FIU 승인 [44]. 복귀와의 인과관계는 **확인 필요**) | OKX | [35][44] |
| 2026-06-25 | "앱 차단 뒤에도 **기존 회원은 계속 거래 가능**" 보도 | — | [37] |
| 2026-07-30 | 방송미디어통신심의위원회와 FIU가 **사기 피해가 확정되지 않아도** 미신고 해외 거래소 **웹사이트 접속 차단**(시정 요구)에 나서기로 합의 | 미신고 해외 거래소 | [37] |
| 2026-09-22 | 두 기관이 구체 기준을 **9월 말까지** 확정할 계획 | 〃 | [37] |

(모두 검색 요약. 바이낸스 앱의 현재 설치 가능 여부는 **확인 필요**.)

**국내 → 해외 송금 경로**
- 업비트는 특금법 시행령 제10조의20을 근거로 **미신고 거래소 23곳**(KuCoin, MEXC 등)과의 입출금을 금액과 상관없이 막는다 [39]
- 바이낸스·OKX·바이비트는 (검색 요약 기준) 아직 트래블룰 연동 대상으로 안내된다. 100만 원 이상은 이름·생년월일 일치를 확인한다 [39]
- → **이 목록에 바이낸스가 추가되면 원화 → 바이낸스 입금 경로가 끊긴다.** 현재 추가 계획은 확인되지 않았다(확인 필요)

#### 2.8.3 이용자 개인의 법적·실무적 위험 정리

| 행위 | 법적 처벌 위험 | 실무 위험 | 확인 수준 |
|---|---|---|---|
| 본인 돈으로 해외 거래소에서 선물 매매 | 현재 **처벌 규정 없음** [38] | 국내 법 보호 없음. 앱·웹 접근이 끊길 수 있음. 송금 경로가 막힐 수 있음 | 검색 요약 → 변호사 확인 권고 |
| 우리 시스템을 **남에게 제공**(신호 판매, 타인 계좌 대리 매매, 카피트레이딩 운영) | 미신고 영업 등으로 처벌될 수 있음 [38]. 신호 판매는 별도 규제(예: 유사투자자문) 가능성 → 이번 조사 범위 밖, **확인 필요** | 큼 | 검색 요약 |
| VPN으로 차단 우회 | 이용자 처벌 규정은 확인되지 않음 | **거래소 약관 위반**(예: Hyperliquid 약관은 VPN을 명시적으로 금지 [51]) → 계정 동결 위험. **권하지 않음** | 검색 요약 |
| 원화를 해외로 보내 코인을 사고 국내에 되파는 차익거래 | 개인의 일회성 행위는 무죄·과태료 취소 판례가 있다. **영업적 환치기**는 외국환거래법 위반(3년 이하 징역 등) [49] | 우리 시스템과 무관 | 검색 요약 |
| (직업상) 소속 회사 규정 | 금융권·보안 조직은 임직원 가상자산 거래에 **사내 규정**을 둘 수 있다 | 징계 위험 | **본인 회사 규정 확인 필요** (분석 의견) |

#### 2.8.4 국내 거래소는 선물을 제공할 수 없다

- 현행 가상자산법상 국내 거래소의 영업 범위는 **현물 "단순 매매"**다. 선물·옵션 등 파생상품은 취급할 수 없다 [40] (검색 요약)
- 2025-07 업비트·빗썸이 코인 대여(사실상 레버리지) 서비스를 내놓자 금융당국이 "보호 장치 부족"을 지적했고, 사실상 중단됐다 [40] (검색 요약)
- **디지털자산기본법(2단계 입법)**: 2026-09 현재 정부안 제출이 늦어져 공청회가 무산됐고, 연내 입법이 불투명하다. 파생상품 도입은 "논의될 수 있다" 수준이다 [41] (검색 요약)
- → **가까운 미래(최소 1~2년)에 국내 거래소 선물로 옮겨 갈 수 있는 선택지는 없다** (분석 의견)

#### 2.8.5 해외 거래소들의 한국 움직임이 뜻하는 것

| 사건 | 내용 | 해석 (분석 의견) |
|---|---|---|
| 바이낸스의 고팍스 인수 완료 | 2025-10 FIU가 대주주 변경을 승인해 바이낸스가 4년 만에 한국 시장에 복귀 [42] | 국내 법인은 선물을 할 수 없다. 규제 당국과 관계를 맺은 만큼, 바이낸스 본사(.com)가 앞으로 **한국 이용자를 더 제한할 가능성**을 배제할 수 없다 |
| 바이낸스의 한국 주식 무기한 선물 | 2026년에 코스피 추종·삼성전자·SK하이닉스 등 무기한 선물을 상장했다. **한국인 KYC 계정은 거래 불가**(바이낸스 자체 결정) [43] | 바이낸스는 **국적 기준으로 상품을 막을 수 있고 실제로 막고 있다** → BTC 선물도 막힐 수 있다는 가정으로 설계해야 한다 |
| OKX의 코인원 지분 인수 | 2026-05 OKX Ventures가 19.6% 인수(800억 원), 2026-07-22 FIU 승인 [44] | 앱이 4일 만에 복귀한 것과 함께 보면, OKX가 한국 규제에 비교적 우호적으로 접근하고 있다(인과관계는 확인 필요) |
| 우회 이용 증가 | "불편해도 해외" 보도. 국내 투자자 지갑이 DEX 3곳에 넣은 돈이 2024-01 이후 누적 약 2.4조 원 [53] | 규제가 강해질수록 DEX(Hyperliquid 등)로 옮겨 가는 흐름이 있다 |

### 2.9 한국 거주자 관점 — 세금

#### 2.9.1 가상자산 소득 과세 시행 시점 (2026-09-29 현재)

| 항목 | 내용 | 확인 수준 |
|---|---|---|
| 연기 이력 | 2022 → 2023 → 2025 → **2027-01-01**로 세 번 미뤄짐 [45] | 검색 요약 (다수 언론 일치) |
| 2026년 정부 방침 | 재정경제부의 **2026년 세제개편안**(2026-08-03 발표 [45])에 **추가 유예가 없다** → 2027-01-01 시행 방침 [45] | 검색 요약 |
| 확정 여부 | 세법 개정은 보통 **12월 국회 본회의**에서 확정된다 [45]. 김재섭 의원(국민의힘)이 **2030-01-01로 3년 유예**하는 소득세법 개정안을 대표 발의했다 [45] | 검색 요약 → **"정부는 시행 방침, 국회 최종 확정 전"** |
| 과세 방식 | 기타소득으로 분리과세한다. 연간 손익을 합친 뒤 **250만 원을 공제**하고, 초과분에 **22%**(소득세 20% + 지방세 2%)를 매긴다. 첫 신고·납부는 **2028-05** [45] | 검색 요약 |
| 의제 취득가액 | 시행 전부터 보유한 자산은 실제 취득가와 **2026-12-31 시가** 중 높은 금액을 취득가로 인정 [45] | 검색 요약 |

#### 2.9.2 무기한 선물 손익은 어떻게 과세되나 — 불명확

- 가상자산소득은 "가상자산을 **양도·대여**해서 생긴 소득"을 기타소득으로 분류하는 구조다 [45]. 해외 거래소 **무기한 선물 손익**이 여기에 들어가는지, 다른 소득(예: 파생상품 양도소득, 기타소득)으로 분류되는지는 **아직 명확히 정해지지 않았다**는 설명이 많다 [46] (검색 요약)
- 국내 거주자는 전 세계 소득이 과세 대상이다. 해외 거래소 수익도 포함된다 [46]
- → **세무사 확인이 필수다.** 확인할 것: ① 선물 손익의 소득 구분 ② 손익을 합치는 범위(현물·선물·거래소 간) ③ 펀딩비·수수료의 필요경비 인정 여부 ④ USDT 손익을 원화로 바꾸는 기준 시점

#### 2.9.3 해외 거래소 거래는 국세청이 알 수 있나 — CARF

- 한국은 CARF 다자간 협정에 서명했다. **2026년 거래분을 2027년에 처음 교환**한다(48개국 안팎) [47] (검색 요약)
- 해외 거래소는 한국 국세청에 거래내역을 낼 의무가 없다. 그래서 CARF 전까지는 **본인이 스스로 계산해 신고**하는 구조다 [47]
- 미국 쪽 거래정보는 **2029년에야** 들어온다는 보도가 있다 [47] (제목 수준 확인)
- → **"안 걸린다"를 전제로 하면 안 된다.** 우리 시스템은 세무 신고용 기록을 **처음부터** 남겨야 한다(§3.4)

#### 2.9.4 해외금융계좌 신고

| 항목 | 내용 | 확인 수준 |
|---|---|---|
| 대상 | 거주자가 가진 해외금융계좌 잔액 합계가 **해당 연도 매월 말일 중 하루라도 5억 원 초과** → 다음 해 6월에 신고 [48] | 검색 요약 (국세청 안내 페이지 제목과 언론 일치) |
| 가상자산 | **2023년 신고분(2022년 잔액)부터** 해외 가상자산 거래소 계좌 포함 [48] | 검색 요약 |
| 미신고 제재 | 미신고·과소신고 금액의 **10% 과태료**(한도 10억 원). **50억 원 초과**면 형사처벌 가능 [48] | 검색 요약 |
| 개인 지갑·DEX | 국세청 예규: **비수탁·탈중앙 지갑**(메타마스크, 렛저 등)에 보관한 가상자산은 신고 대상이 **아니다** [48] | 검색 요약. Hyperliquid 포지션·증거금에도 적용되는지는 **확인 필요** |
| 우리 시스템 | 소액으로 시작하면 해당 가능성은 낮다. 다만 **다른 해외 계좌(해외 주식 등)와 합산**된다는 점에 주의 | 분석 의견 |

### 2.10 기존 기획(PLAN v0.1)에 대한 검토

| PLAN 내용 | 판정 | 근거와 보완 |
|---|---|---|
| §3.2 "바이낸스로 시작" | **맞음** | 유동성 1위, 사용자가 이미 KYC를 마쳤고 익숙하다. Ed25519 지원, 모의 환경 두 종류 (§2.1, §2.4, §2.5) |
| §3.2 "선물 테스트넷 제공" | **보완** | 2026년 현재 **테스트넷과 데모 트레이딩이 따로 있다**. ccxt 호출도 다르다. PoC에서 둘 다 시험 (§2.5) |
| §3.2 "ccxt로 설정만 교체" | **과장** | 계정 모드, 손절 방식, 정산 통화, 인증 정보, 키 수명, 서버 국가 제한이 다르다 → 어댑터와 거래소별 테스트가 필요하다 (§2.7, §3.3) |
| §3.2 "규제·세금은 직접 확인" | **구체화** | 앱·웹 차단 확대, 송금 경로 위험, 2027 과세, CARF, 해외금융계좌 (§2.8, §2.9) |
| §4.1 "선물 거래만 허용, 출금 금지" | **맞음 + 강화** | 여기에 더해 **Ed25519 직접 생성 키**, **봇 전용 서브계정**, **메인 계정 출금 주소 화이트리스트**, **이체 권한도 끔** (§3.2) |
| §4.1 "IP 화이트리스트: 배포 서버의 고정 IP" | **맞음 + 주의** | 서버 **국가**도 거래소 제한 목록에 없어야 한다(바이낸스는 미국 등 서버 차단 [31]). 집 인터넷은 IP가 바뀌므로 부적합 → 고정 IP 클라우드 서버 |
| §4.3 "격리 마진" | **맞음** | 3배 격리에서 청산가는 약 30% 가까이 떨어져 있고 손절(≤2%)보다 훨씬 멀다. 추가로 **증거금은 USDT 단일 자산** (2025-10-10 USDe 사례, §2.2) |
| §6 로드맵 4단계 "테스트넷 주문 (손절·익절 포함)" | **보완** | "손절 주문이 **거래소에 실제로 걸렸는지 조회해 확인**"을 합격 기준에 넣는다 (2025-12 바이낸스 algo 이전 사례) |
| (없음) 세무 기록 | **추가** | 체결·수수료·펀딩비·입출금·환율을 모두 기록하고 월별로 내보낸다 (§3.4) |
| (없음) 접근 불가 대비 | **추가** | 거래소 접근이 끊기면 → 신규 진입 중지, 기존 포지션은 거래소 손절에 맡김, 수동 대응 절차 (§3.4) |

---

## 3. 우리 시스템에 대한 시사점과 권고

### 3.1 기본 거래소 권고

| 순위 | 거래소 | 권고 | 핵심 이유 | 주의 |
|---|---|---|---|---|
| **1 (기본)** | **Binance USDⓈ-M** | **채택** | 유동성 1위. **Ed25519** 키. IP 제한 없으면 읽기 전용이라 키 관리 규칙이 엄격하다. 모의 환경 2종. 월별 PoR 100%+. ccxt 인증. 사용자가 이미 쓰고 있다 | 한국 규제로 앱 차단(2026-01~). **국적 기준 상품 제한 전례**가 있다. 2025-12 API 변경 사례. 서버 국가 제한 |
| 2 (예비) | OKX | 어댑터만 준비 | 2위 유동성. 데모 키 만료 없음. IP 20개. PoR 이력이 길다. 한국 코인원 지분으로 규제에 우호적인 접근 | HMAC뿐이다(비대칭 키 없음). 과거 캔들 100개/호출. 2020 출금 동결, 2025 미국 유죄 인정 |
| 3 (예비) | Bybit | 어댑터만 준비 | 공식 API 문서가 GitHub에 공개돼 있다(검증하기 쉽다). **RSA 직접 생성 키**. 데모 환경이 잘 돼 있다. 해킹 대응(72시간 안에 부족분 보전)이 모범적 | 역대 최대 해킹 이력. 한국 구글플레이에서 2026-07부터 차단. IP 미지정 키 90일 만료 |
| 보류 | Bitget | **당분간 제외** | — | **2026-09-24 해킹**으로 출금을 단계적으로 재개하는 중이다. 원인 분석 공개와 3개월 이상 안정 운영을 확인한 뒤 재검토 |
| 2단계 검토 | Hyperliquid | 연구만 | **API 지갑은 출금 불가**(프로토콜이 강제). 온체인이라 투명하다. 수수료가 가장 낮다. 한국 앱 차단과 무관하다 | **USDC 정산**(USDT 아님). 메인 지갑 개인키를 직접 관리해야 한다. **규제·보호 장치 없음**. 검증인 개입과 ADL 이력. 테스트넷을 쓰려면 메인넷 입금이 먼저 필요. VPN 금지 약관. 특금법상 DEX의 지위 확인 필요 |

**사용자 생각("보안성과 인기에 따라 거래소를 바꿀 수 있다")에 대한 의견**
- 방향은 맞다. 다만 **보안성 차이는 거래소보다 우리 운영 방식에서 더 크게 난다.** 모든 후보에 사고 이력이 있다(§2.2). 개인 봇 계정에 가장 큰 위험은 키 탈취와 봇 버그다.
- 따라서 **"기본 거래소는 하나, 교체 준비는 하나 더"**가 현실적이다. 처음부터 여러 거래소에 동시에 주문하면 테스트와 보안 표면이 두 배가 된다. 예비 거래소는 **어댑터와 데모 테스트까지만** 해 둔다. 바이낸스 접근이 막히는 등 "교체 사유"가 생기면 그때 켠다.

### 3.2 계정·키 보안 설계 (정보보호 관점 체크리스트)

1. **계정 구조**: 메인 계정(사람만 사용, API 키 없음)과 **봇 전용 서브계정**(봇 키만)으로 나눈다. 바이낸스·바이비트 모두 계정 모드 요구사항 때문에 봇 전용 (서브)계정을 권장한다 [31]
2. **봇 계정 잔고 상한**: 봇 계정에는 **당장 쓸 증거금 + 여유분만** 둔다. 예를 들어 전략이 쓸 최대 증거금의 2~3배다(수치는 결정 필요). 이익이 나면 사람이 주기적으로 메인 계정으로 옮긴다
3. **키 발급 규칙**
   - 서명 방식: 바이낸스는 **Ed25519**를 쓴다(서버에서 직접 생성하고 공개키만 등록). HMAC은 쓰지 않는다
   - 권한: **선물 거래 + 읽기만** 켠다. **출금, 범용 이체, 현물·마진은 끈다**
   - IP 제한: 배포 서버의 고정 IP 1개만 넣는다
   - 개발용: **데모/테스트넷 키만** 쓴다. 실키는 8단계(실거래) 전까지 만들지 않는다
4. **메인 계정 방어**: **출금 주소 화이트리스트**를 켜고, 새 주소에는 잠금 시간을 둔다. **피싱 방지 코드**, 2FA(가능하면 하드웨어 보안키. 지원 여부는 확인 필요)도 설정한다. 이메일 계정도 별도로 보호한다
5. **비밀값 보관**: 개인키 파일은 서버에서만 읽을 수 있게 권한을 좁힌다. Git, 채팅, 스크린샷에 절대 넣지 않는다(PLAN §4.1과 같음). **키 원본을 Claude 대화창에 붙여 넣지 않는다**
6. **키 수명 관리**: 발급일·만료 규칙·교체 예정일을 기록한다(Bybit 90일, OKX 14일 미사용 등). 교체 주기는 90일을 권장한다(바이낸스 US 권고 [19], 검색 요약)
7. **증거금 자산**: **USDT 단일 자산 모드**로 쓰고, 멀티에셋 담보는 쓰지 않는다(2025-10-10 교훈)
8. **서버 위치**: 거래소의 **서버 국가 제한 목록에 없는 리전**을 고른다. 바이낸스는 미국·캐나다·말레이시아·네덜란드 등을 제한한다 [31]. 바이비트 제한국에는 싱가포르·홍콩이 포함된다 [51](서버 IP 기준 적용 여부는 확인 필요). 서울 리전이 한국 웹 차단 조치의 영향을 받는지도 **확인 필요**다
9. **월간 점검**: PoR 머클 트리에 봇 계정이 포함됐는지, API 키 목록에 모르는 키가 없는지, 로그인 기록을 확인한다

### 3.3 교체 가능 설계(ccxt)에서 지킬 점

1. **거래소 어댑터 층을 둔다.** 전략·리스크·텔레그램 코드는 거래소 이름을 모르게 한다. 어댑터가 다음 **공통 동작**만 제공한다.
   - 시세 조회
   - 계정 모드 점검·설정 (One-way, 격리, 레버리지)
   - 진입 + **거래소 손절·익절 등록**
   - 열린 주문·포지션 조회
   - 체결·수수료·펀딩 내역 조회
2. **거래소별 차이는 어댑터 안의 설정표로 관리한다.** 설정표에 들어갈 항목은 다음과 같다.
   - 심볼 (`BTC/USDT:USDT` / `BTC/USDC:USDC`)
   - 정산 통화
   - 모의 환경 켜는 방법 (sandbox / demo)
   - 추가 인증 (패스프레이즈 등)
   - 손절 주문 파라미터
   - 캔들 조회 한도
   - 키 만료 규칙
   - 허용 서버 국가
3. **시작 시 자가 점검**: 봇이 켜질 때마다 다음을 **거래소에서 직접 조회**한다. 하나라도 다르면 **주문 기능을 잠근다**. freqtrade도 바이낸스 모드를 시작할 때 검사한다 [31].
   - 포지션 모드, 마진 모드, 레버리지
   - 증거금 자산 모드
   - 키 권한 (출금이 꺼져 있는지)
4. **진입 후 재확인**: 진입이 체결되면 **몇 초 안에 손절 주문이 거래소에 존재하는지 조회**한다. 없으면 즉시 재시도한다. 그래도 실패하면 **포지션을 시장가로 정리하고 텔레그램으로 경보**를 보낸다(2025-12 바이낸스 algo 이전 사례 대비)
5. **ccxt 버전 고정과 갱신 절차**: 버전을 고정한다(현재 최신 4.5.84 [30]). 갱신할 때는 **데모 환경에서 진입 → 손절 → 청산을 한 바퀴 돌려 본 뒤** 운영에 반영한다. 거래소 API 변경 공지(changelog)를 월 1회 확인한다
6. **거래소별 통합 테스트**: 예비 거래소를 "지원한다"고 표시하려면 해당 거래소 **데모에서 위 4번까지 통과**해야 한다. 통과하기 전에는 설정으로도 켤 수 없게 막는다
7. **동시 운영 금지 (초기)**: 한 번에 한 거래소, 한 포지션만. 거래소를 옮길 때는 기존 거래소 포지션이 0인지 확인한 뒤 전환한다

### 3.4 규제·세금 대응 운영 규칙

1. **개인용으로만 운영**: 신호와 봇을 남에게 제공·판매하거나 남의 계좌를 운용하지 않는다(미신고 영업 위험, §2.8.3). 공개 저장소에 코드를 올리는 것은 괜찮지만, "서비스"로 운영하지 않는다
2. **세무용 기록을 1단계부터 설계**: 다음 필드를 DB에 모두 남기고 월별 CSV로 내보낸다. **2027-01-01 이후 거래분**부터 과세 대상이 될 수 있다
   - 체결마다: 시각(UTC), 방향, 수량, 가격, 수수료와 수수료 자산, 실현손익
   - 펀딩비 내역
   - 거래소 입출금: 금액, 주소, 트랜잭션 해시
   - 기록 시점의 **USDT/KRW 환율**
3. **접근 불가 대응 절차**: 거래소 API·웹 접근이 끊기거나(차단·키 만료·장애) 오류가 계속되면 다음 순서로 대응한다.
   - ① 신규 진입 자동 중지
   - ② 기존 포지션은 **거래소에 걸어 둔 손절·익절**에 맡긴다(그래서 거래소 쪽 손절이 필수)
   - ③ 텔레그램으로 사람에게 경보
   - ④ 사람이 판단해 수동으로 대응
4. **입금 경로 점검**: 분기마다 업비트·빗썸의 "입출금 가능 거래소 / 미신고 제한 거래소" 공지를 확인한다[39]. 기본 거래소가 제한 목록에 오르면 **교체를 검토**한다
5. **해외금융계좌**: 해외 거래소 잔액과 다른 해외 계좌 잔액의 **월말 합계**를 추적한다. 5억 원에 가까워지면 신고를 준비한다
6. **전문가 확인 (실거래 8단계 전 필수)**
   - 세무사: 선물 손익의 소득 분류, 필요경비, 원화 환산 기준, 2027 시행이 최종 확정됐는지
   - 변호사: 개인의 미신고 해외 거래소 이용에 관한 최신 해석, 웹 차단 이후의 이용
   - 본인 회사: 임직원 가상자산 거래 규정

### 3.5 결정 필요 · 확인 필요 목록

| # | 항목 | 종류 | 어떻게 |
|---|---|---|---|
| 1 | 봇 계정 잔고 상한 (예: 최대 증거금의 2~3배) | 결정 필요 | 사용자 |
| 2 | 바이낸스 테스트넷과 데모 트레이딩 중 무엇을 개발용으로 쓸지 | 확인 필요 | PoC에서 두 환경의 호가·체결 비교 |
| 3 | ccxt에 바이낸스 Algo 주문(조건부 손절)이 반영된 버전과 `create_order` 호출 방식 | 확인 필요 | ccxt 변경 이력 + 데모 PoC |
| 4 | 바이낸스 서브계정 생성 조건과 개수 한도 (5~20, 출처마다 다름) | 확인 필요 | 바이낸스 앱 계정 설정 화면 |
| 5 | 하드웨어 보안키(패스키) 지원 여부 (거래소별) | 확인 필요 | 각 거래소 보안 설정 |
| 6 | 펀딩비 주기·수준 (거래소별) | 확인 필요 | 공식 문서 (접속 가능한 환경에서) |
| 7 | 바이낸스 앱의 현재 한국 구글플레이 상태, 웹 차단 기준(9월 말)이 바이낸스에 적용되는지 | 확인 필요 | 언론 후속 보도 |
| 8 | 배포 서버 리전 (예: 서울/도쿄 등)이 각 거래소 제한·한국 차단 조치의 영향을 받는지 | 확인 필요 | 배포 담당 리서처 + PoC |
| 9 | 무기한 선물 손익의 세법상 분류, 2027 과세의 국회 최종 의결 | 확인 필요 | 세무사, 2026-12 국회 결과 |
| 10 | Hyperliquid 이용의 특금법·해외금융계좌상 지위 | 확인 필요 | 2단계 검토 시 변호사·세무사 |
| 11 | Bitget 해킹 원인 분석 공개 여부 | 확인 필요 | 2026-Q4 재검토 |

---

## 4. 출처 목록

**시장 점유율·통계**
1. CoinGecko, Market Share of Crypto Derivatives Exchanges — https://www.coingecko.com/research/publications/crypto-derivatives-exchanges-market-share (검색 요약)
2. crypto.news, "CoinGecko: Binance, OKX dominate perps as perp DEX OI share nearly quadruples" — https://crypto.news/coingecko-binance-okx-dominate-perps-as-perp-dex-oi-share-nearly-quadruples/ (검색 요약)
3. CoinGlass, 2026 Q1 Cryptocurrency Market Share Research Report — https://www.coinglass.com/zh/learn/2026-q1-mktshare-report-en (검색 요약)
4. CoinGecko, State of Crypto Perpetuals Report 2026 — https://www.coingecko.com/research/publications/state-of-crypto-perpetuals-report-2026 ; Blockeden, Perp DEX Wars 2026 — https://blockeden.xyz/blog/2026/01/29/perp-dex-wars-2026-hyperliquid-lighter-aster-edgex-paradex-decentralized-derivatives/ (검색 요약)
5. Bitget News, "Hyperliquid hits record 9% share of aggregate perp open interest" — https://www.bitget.com/news/detail/12560605511810 (검색 요약)
6. Datawallet, Hyperliquid Statistics 2026 — https://www.datawallet.com/crypto/hyperliquid-statistics ; Hyperliquid vs Binance — https://www.datawallet.com/crypto/hyperliquid-vs-binance (검색 요약)

**보안 사고**
7. NCC Group, Bybit Hack In-Depth Technical Analysis — https://www.nccgroup.com/research/in-depth-technical-analysis-of-the-bybit-hack/ ; Sygnia — https://www.sygnia.co/blog/sygnia-investigation-bybit-hack/ ; TRM Labs — https://www.trmlabs.com/resources/blog/the-bybit-hack-following-north-koreas-largest-exploit (검색 요약)
8. Cointelegraph, "Bybit has fully closed the ETH gap" — https://cointelegraph.com/news/bybit-purchases-742-million-ether-days-after-hack ; CNBC — https://www.cnbc.com/2025/02/24/bybit-replenished-reserves-after-record-breaking-1point5-billion-hack.html (검색 요약)
9. CoinDesk, "Bybit sues North Korea and Lazarus Group..." (2026-08-07) — https://www.coindesk.com/policy/2026/08/07/bybit-sues-north-korea-and-lazarus-group-over-usd1-5-billion-hack-secures-asset-freeze (제목만 확인)
10. CoinDesk, "Hackers Steal $40.7 Million in Bitcoin From Crypto Exchange Binance" — https://www.coindesk.com/markets/2019/05/07/hackers-steal-407-million-in-bitcoin-from-crypto-exchange-binance ; Decrypt — https://decrypt.co/6930/binance-hack-security-breach (검색 요약)
11. CoinGecko, October 10 Crypto Crash Explained — https://www.coingecko.com/learn/october-10-crypto-crash-explained ; CoinDesk Research — https://www.coindesk.com/research/market-spotlight-the-19-billion-liquidation-that-shook-crypto ; bit.com — https://www.bit.com/knowledge-hub/october-10-crypto-crash-binance-usde (검색 요약)
12. CNBC, "U.S. says OKX crypto exchange operator enters $505 million guilty plea" — https://www.cnbc.com/2025/02/24/us-says-okx-crypto-exchange-operator-enters-505-million-guilty-plea.html (검색 요약)
13. CoinDesk, "OKEx Suspends Withdrawals, Says Key Holder Not Available..." (2020-10-16) — https://www.coindesk.com/markets/2020/10/16/okex-suspends-withdrawals-says-key-holder-not-available-due-to-cooperation-with-investigation (검색 요약)
14. Cointelegraph, "Bitget detects irregularity in VOXEL-USDT futures, rolls back accounts" — https://cointelegraph.com/news/bitget-detects-irregularity-voxelusdt-futures (검색 요약)
15. The Block, "Bitget starts phased withdrawal resumption following $388 million..." (2026-09-28) — https://www.theblock.co/news/business/2026-09-28-bitget-starts-phased-withdrawal-resumption-416965 ; BleepingComputer — https://www.bleepingcomputer.com/news/security/bitget-resumes-bitcoin-withdrawals-after-3875-million-crypto-heist/ ; PYMNTS — https://www.pymnts.com/cryptocurrency/2026/bitget-suffers-years-largest-crypto-hack-as-losses-top-387-million/ (검색 요약)
16. Halborn, Hyperliquid Hack (March 2025) — https://www.halborn.com/blog/post/explained-the-hyperliquid-hack-march-2025 ; CoinDesk, POPCAT (2025-11-13) — https://www.coindesk.com/markets/2025/11/13/peak-degen-warfare-alleged-popcat-manipulation-hits-hyperliquid-with-usd4-9m-loss ; HyperAcademy, Hack History — https://hyperacademy.io/en/articles/hyperliquid-security-and-hack-risk ; The Defiant, outage refund — https://thedefiant.io/news/defi/hyperliquid-to-refund-users-affected-by-platform-outage (검색 요약)

**준비금 증명**
17. Crypto Briefing, Binance PoR August 2026 — https://cryptobriefing.com/binance-proof-of-reserves-august-2026/ ; crypto.news, PoR 공개 주기 — https://crypto.news/how-often-do-major-exchanges-actually-publish-proof-of-reserves/ ; Hacken, Bybit PoR — https://hacken.io/case-studies/bybit-proof-of-reserves/ ; CoinGape, Bitget PoR — https://coingape.com/bitget-boosts-proof-of-reserves-to-19-crypto-assets-with-bitcoin-ethereum-xrp/ (검색 요약)

**API·테스트 환경·수수료**
18. Binance, API Key Types — https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/faqs/api_key_types.md **[직접]** (GitHub: https://github.com/binance/binance-spot-api-docs/blob/master/faqs/api_key_types.md)
19. Binance, How to Create API Keys — https://www.binance.com/en/support/faq/how-to-create-api-keys-on-binance-360002502072 ; Updates to API Key Permission Rules — https://www.binance.com/en/support/announcement/updates-to-api-key-permission-rules-2021-07-26-11e4c2f44e7a47b9b5fc0e479c0b256f ; Binance.US API key best practices — https://support.binance.us/en/articles/9842812-binance-us-api-keys-best-practices-safety-tips (검색 요약)
20. Binance, Sub-Account Functions FAQ — https://www.binance.com/en/support/faq/binance-sub-account-functions-and-frequently-asked-questions-360020632811 (검색 요약)
21. Binance Derivatives General Info (테스트넷 주소) — https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info (검색 요약)
22. Binance Derivatives Change Log — https://developers.binance.com/docs/derivatives/change-log (검색 요약) ; freqtrade issue #12610 "Binance Futures: Stoploss orders fail with error -4120" — https://github.com/freqtrade/freqtrade/issues/12610 **[직접]**
23. Bybit API 문서 원본 (GitHub `bybit-exchange/docs`) — https://raw.githubusercontent.com/bybit-exchange/docs/main/docs/v5/demo.mdx , https://raw.githubusercontent.com/bybit-exchange/docs/main/docs/v5/guide.mdx , https://raw.githubusercontent.com/bybit-exchange/docs/main/docs/v5/user/create-subuid-apikey.mdx , https://raw.githubusercontent.com/bybit-exchange/docs/main/docs/v5/user/modify-sub-apikey.mdx **[직접]** (게시본: https://bybit-exchange.github.io/docs/v5/demo)
24. OKX API v5 — https://www.okx.com/docs-v5/en/ ; QuotaGuard, OKX 14-day deletion — https://www.quotaguard.com/blog/okx-api-key-14-day-deletion-static-ip-fix (검색 요약)
25. Bitget API Quick Start — https://www.bitget.com/api-doc/uta/guide ; Gunbot, Bitget API key — https://www.gunbot.com/support/guides/exchange-configuration/creating-api-keys/bitget-api-key-creation/ (검색 요약)
26. Hyperliquid Docs, Nonces and API wallets — https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets ; Chainstack, Agent Wallets — https://chainstack.com/hyperliquid-agent-wallets-nonce-state-machine/ (검색 요약) ; Hyperliquid Python SDK README — https://github.com/hyperliquid-dex/hyperliquid-python-sdk **[직접]**
27. Hyperliquid Docs, Testnet faucet — https://hyperliquid.gitbook.io/hyperliquid-docs/onboarding/testnet-faucet (검색 요약)
28. crypto.news, Maker and taker fees compared — https://crypto.news/maker-and-taker-fees-compared-across-8-crypto-exchanges/ ; CryptoSlate, Futures exchanges — https://cryptoslate.com/crypto-exchanges/futures/ ; Hyperliquid fees — https://hyperliquidguide.com/guides/fees/fees-explained ; Bitsgap, Binance fees 2026 — https://bitsgap.com/blog/binance-trading-fees-explained-what-it-costs (검색 요약)
29. Binance, Withdrawal Whitelist — https://www.binance.com/en-JP/support/faq/how-to-enable-withdrawal-whitelist-on-binance-1d08944f103b4fc78d3519913b600086 ; Binance Anti-Phishing Code — https://www.binance.com/en/support/faq/what-is-an-anti-phishing-code-and-how-to-set-it-up-on-binance-311927d6c4b4478ba094fc6a611d5201 ; OKX Whitelist mode — https://www.okx.com/help-center/9521339801485 ; Bitget withdrawal settings — https://www.bitget.com/support/articles/12560603820641 (검색 요약)
30. ccxt README — https://raw.githubusercontent.com/ccxt/ccxt/master/README.md **[직접]** ; ccxt 파이썬 소스 — https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/binance.py , …/bybit.py , …/okx.py , …/bitget.py , …/hyperliquid.py **[직접]** ; PyPI — https://pypi.org/pypi/ccxt/json (4.5.84, 2026-09-24), https://pypi.org/pypi/pybit/json (5.17.0), https://pypi.org/pypi/hyperliquid-python-sdk/json (0.24.0) **[직접]**
31. freqtrade 거래소별 문서 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/exchanges.md **[직접]**

**한국 규제**
32. 금융위원회 보도참고, "국외 미신고 가상자산사업자의 구글플레이 앱에 대한 국내 접속 차단" — https://www.fsc.go.kr/no010101/84237 ; 아시아경제 — https://www.asiae.co.kr/article/2025032616075886679 ; 머니투데이 — https://www.mt.co.kr/stock/2025/03/26/2025032616073587057 (검색 요약)
33. SBS Biz, "애플, 국외 미신고 가상자산사업자 앱 접속 차단" — https://biz.sbs.co.kr/article/20000228715 (검색 요약)
34. 법률신문, "구글플레이의 해외 가상자산 거래소 및 지갑 앱 정책" — https://www.lawtimes.co.kr/LawFirm-NewsLetter/215096 ; 디지털애셋 — https://www.digitalasset.works/news/articleView.html?idxno=31142 ; Cryptonews — https://cryptonews.com/news/google-play-to-block-binance-okx-from-korea-starting-jan-28/ ; 다음(2026-01-17) — https://v.daum.net/v/20260117100244337 ; 뉴시스(2026-02-06) — https://www.newsis.com/view/NISX20260206_0003505813 (검색 요약)
35. crypto.news, "OKX app returns to South Korea's Google Play Store after four day suspension" — https://crypto.news/okx-app-returns-to-south-koreas-google-play-store-after-four-day-suspension/ ; Bloomingbit, Bybit app blocked — https://en.bloomingbit.io/feed/news/115971 ; 서울경제 영문 — https://en.sedaily.com/finance/2026/08/19/banned-app-of-coinone-shareholder-okx-reappears-on-google ; wherelegalcrypto (Binance/Bybit in Korea) — https://wherelegalcrypto.com/exchanges/binance/south-korea/ (검색 요약)
36. 아시아경제, FIU "신고된 28곳 가상자산사업자 빼고 전부 불법" (2026-06-24) — https://view.asiae.co.kr/article/2026062409544314510 ; 금융위원회 보도자료 — https://www.fsc.go.kr/no010101/85060 (검색 요약)
37. 다음/아시아경제, "불법 거래소 뒷북 차단에도…기존 회원은 코인거래" — https://v.daum.net/v/20260625161200977 ; "[단독] 드디어 불법 코인거래소 차단된다…방미심위" — https://view.asiae.co.kr/article/2026073018314271848 ; "[단독] 해외 코인거래소 FIU 신고 안하면 바로…" — https://view.asiae.co.kr/article/2026092214243195647 (검색 요약)
38. 뉴스핌(2021), "바이낸스, 한국서 '우회거래'하나...금융위 제재" — https://www.newspim.com/news/view/20210726000646 ; 법무법인 칼럼 — https://bh-law.kr/ko/news/column/coin-otc-p2p-punishment-key-issues , https://bh-law.kr/en/news/column/crypto-special-financial-law-violation-penalty-defense (검색 요약)
39. 업비트, 미신고 불법 영업행위 가상자산사업자 리스트 — https://support.upbit.com/hc/ko/articles/9843733405977 ; 입출금 가능 VASP 리스트 — https://support.upbit.com/hc/ko/articles/5048002559897 ; 코인원, 미신고거래소 입출금 제한 — https://support.coinone.co.kr/support/solutions/articles/31000169481 (검색 요약)
40. 경향신문, "가상자산 선물ETF는 되고 선물 거래는 안 되는…" — https://www.khan.co.kr/article/202408282032035 ; 뉴시스, 업비트·빗썸 마진거래 — https://www.newsis.com/view/NISX20250707_0003242629 ; 다음, "업비트·빗썸, 코인 레버리지 투자 사실상 중단" — https://v.daum.net/v/Ym7ZbaWAyj (검색 요약)
41. 아시아투데이, "공청회 일정도 못잡은 가상자산기본법" — https://www.asiatoday.co.kr/kn/view.php?key=20260930010010378 ; 뉴스핌 — https://www.newspim.com/news/view/20260909001001 ; 뉴시스 — https://www.newsis.com/view/NISX20260917_0003793358 ; 법률신문, 2026 10대 이슈 — https://www.lawtimes.co.kr/news/articleView.html?idxno=215219 (검색 요약)
42. The Block, "Binance completes Gopax acquisition" — https://www.theblock.co/post/374864/binance-completes-acquisition-gopax ; KED Global — https://www.kedglobal.com/cryptocurrencies/newsView/ked202510160007 (검색 요약)
43. 네이트뉴스, "바이낸스, 코스피 추종 무기한 선물 출시" — https://news.nate.com/view/20260313n12610 ; "바이낸스, 네이버 등 무기한 선물 출시…한국인…" — https://m.news.nate.com/view/20260814n28827 ; 다음, "바이낸스發 초위험 레버리지…" — https://v.daum.net/v/20260701000230742 (검색 요약)
44. CoinDesk, "OKX Ventures buys $53 million stake in Korea's Coinone" — https://www.coindesk.com/markets/2026/05/29/okx-ventures-buys-usd53-million-stake-in-korea-s-coinone-exchange ; Bloomingbit, FIU clears Coinone shareholder change — https://en.bloomingbit.io/feed/news/116832 (검색 요약)
50. CoinDesk, Upbit hack (2025-11-28) — https://www.coindesk.com/markets/2025/11/28/south-korea-suspects-north-korea-linked-lazarus-behind-usd36m-upbit-hack (검색 요약)
51. Datawallet, Binance / Bybit / Hyperliquid restricted countries — https://www.datawallet.com/crypto/binance-restricted-countries , https://www.datawallet.com/crypto/bybit-restricted-countries , https://www.datawallet.com/crypto/hyperliquid-supported-and-restricted-countries (검색 요약, 신뢰도 낮음 — 거래소 약관 원문 확인 필요)
53. 디지털타임스, "불편해도 해외… 규제 비웃는 코인거래소 우회" — https://www.dt.co.kr/article/12040926 ; 데일리안, "국내 돌아올 이유 없다…해외로 쏠리는 코인" — https://m.dailian.co.kr/news/view/1678502 (검색 요약)

**세금**
45. 한국일보, "코인 세금 내년부터 시행…" (2026-09-19) — https://www.hankookilbo.com/news/article/A2026091910080001575 ; 블로터, "더는 안 미룬다…정부, 2027년 '가상자산 과세' 시행" — https://www.bloter.net/news/articleView.html?idxno=669414 ; 핀포인트뉴스, 2030년 유예 법안 — https://www.pinpointnews.co.kr/news/articleView.html?idxno=491046 ; 서울신문(2026-04-27) — https://www.seoul.co.kr/news/plan/taxtech/2026/04/27/20260427500143 ; 재정경제부, 2026년 세제개편안 발표 — https://mofe.go.kr/nw/nes/detailNesDtaView.do?searchBbsId1=MOSFBBS_000000000028&searchNttId1=MOSF_000000000078809&menuNo=4010100 ; 법률신문, 2026년 세제개편안 주요 사항 — https://www.lawtimes.co.kr/news/articleView.html?idxno=226948 (검색 요약)
46. KB Think, 코인 세금 — https://kbthink.com/crypto/crypto-tax.html ; 브런치, 코인 선물 세금 2026 — https://brunch.co.kr/@f4068b5f015d492/79 (검색 요약, 선물 과세 불명확 부분은 신뢰도 중하)
47. 한국일보, "2027년부터 해외 암호화자산 거래정보 정부 간 교환" — https://www.hankookilbo.com/News/Read/A2025102815210003392 ; 뉴시스 — https://www.newsis.com/view/NISX20251028_0003379955 ; 파이낸셜뉴스, "내년 코인 과세 시작인데…美 거래정보는 2029년에야" — https://www.fnnews.com/news/202609181324478898 (검색 요약)
48. 국세청, 해외금융계좌 신고 — https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7819&mi=2513 ; 한국경제 — https://www.hankyung.com/article/2025061560921 ; 딜사이트, "국세청, '가상자산 개인지갑' 신고 대상 제외" — https://dealsite.co.kr/articles/115901 ; 국세 예규 — https://www.intn.co.kr/news/articleView.html?idxno=2032862 (검색 요약)
49. 법률신문, 김치 프리미엄 판결 — https://www.lawtimes.co.kr/news/articleView.html?idxno=195854 ; 법무법인 세종 뉴스레터 — https://www.shinkim.com/kor/media/newsletter/2207 (검색 요약)

> 출처 번호 50·51·53은 본문 작성 순서 때문에 규제 절에 넣었다. 52는 비워 둔다.
