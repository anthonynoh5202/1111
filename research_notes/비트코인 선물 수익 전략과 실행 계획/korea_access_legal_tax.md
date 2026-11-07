# 한국 거주 개인의 비트코인 선물 거래 경로 — 접근성·송금·법적 위험·세금 (기준일 2026-11-07)

> **조사 방법과 한계 (보고서 작성자 필독)**
> - 기준일 2026-11-07. 각 항목에 날짜를 달았다.
> - 이 세션에서 WebFetch는 대부분의 한국 도메인(kiwoom.com, zdnet.co.kr, etoday.co.kr, blockmedia.co.kr, coinddak.com, veatlaw.kr에서 확인)에 **네트워크 정책 때문에 접속할 수 없었다**(DNS 차단). WebSearch도 세션 공유 한도(턴당 200회)가 **조사 도중 소진**됐다. 그래서 아래 인용은 모두 **검색 결과 발췌문**(검색엔진이 원문에서 뽑은 인용·요약)에 기반한다. 원문 전체는 읽지 못했다. 날짜·수치는 원문이나 공식 자료로 다시 확인해야 한다.
> - 표시: **[공식확인 필요]** = 정부·거래소 1차 자료로 확인하지 못함, **[2차]** = 언론 재인용·해외 매체·브로커 자료, **[블로그]** = 개인·업체 블로그(신뢰도 낮음).
> - 경로 요약(상세 근거는 아래): (A) 해외 중앙화 거래소(바이낸스 등)는 가능하지만 규제 압박이 커지는 중이다. (B) 온체인 DEX(하이퍼리퀴드)는 한국 내 직접 조치가 확인되지 않았다. (C) 국내 증권사 해외선물 계좌로 CME 비트코인 선물을 거래하는 길은 **막혀 있다**. (D) 해외 FCM 직접 계좌는 외환법·세금이 불확실하다. (E) 미국 상장 비트코인 선물 ETF는 국내 증권사로 살 수 있지만 선물을 대신하기엔 불완전하다. (F) 국내 파생상품·현물 ETF는 없다.

---

## 1. 해외 거래소(바이낸스·바이비트·OKX·비트겟·하이퍼리퀴드) 접근성 — FIU 조치, 앱·웹 차단, 개인 처벌 여부, 계정·KYC

### Takeaway
2026-11 현재 바이낸스·OKX·바이비트·비트겟은 모두 FIU 미신고 사업자다(신고 사업자는 국내 27~28곳뿐). 이들의 "내국인 대상 영업"은 특금법상 불법이지만, **처벌 대상은 사업자**이고 이용자 개인을 처벌하는 조항은 확인되지 않았다. 실제 차단은 구글플레이 앱의 신규 설치·업데이트 제한 수준이다(정책 시행 2026-01-28, 실제 집행은 7월에 부분적으로, 그나마 들쭉날쭉). 웹사이트 차단은 방미심위 심의가 늦어져 실행되지 않았다. 대신 보호장치 부재, 수사 연루, 송금 경로 규제 같은 간접 위험이 계속 커지고 있다.

### Cited Findings

**FIU의 법적 입장과 단속 실적**
- 미신고 가상자산사업자의 영업은 특금법상 "5년 이하의 징역 또는 5천만원 이하의 벌금" 대상이다. 내국인을 상대로 영업하는 국외 사업자도 신고 대상이다 — [금융위 보도자료(2022, 게시번호 78323)](https://fsc.go.kr/no010101/78323); [아시아경제 2026-10-30](https://view.asiae.co.kr/article/2026103016094883766)
- FIU는 국내 영업 여부를 한국어 홈페이지 제공, 한국인 대상 마케팅, 원화 결제 지원 등으로 판단한다고 설명했다(2025-03 앱 차단 발표 때) — [머니투데이 2025-03-26](https://www.mt.co.kr/stock/2025/03/26/2025032616073587057); [디지털타임스](https://www.dt.co.kr/article/11653962)
- 2022-08-18 FIU는 MEXC·KuCoin 등 내국인 대상 미신고 영업 외국 사업자 16곳을 수사기관에 통보했다 — [한국경제 2022-08-18](https://www.hankyung.com/article/2022081827751)
- 2025-03-25 구글은 FIU 요청에 따라 KuCoin·MEXC 등 미신고 해외 사업자 17곳 앱의 국내 신규 설치와 기존 이용자 업데이트를 막았다 — [머니투데이](https://www.mt.co.kr/stock/2025/03/26/2025032616073587057); [디지털애셋](https://www.digitalasset.works/news/articleView.html?idxno=26862); [서울경제](https://www.sedaily.com/article/14044986)
- 2026-06 FIU 보도자료(보도·법률뉴스레터 인용):
  - 신고 사업자는 총 28개사이고, 그 밖의 사업자가 한국인을 상대로 영업하면 모두 불법이다.
  - 집중조사로 불법 장외거래소 8곳과 국내 영업 해외거래소 4곳 등 12곳을 적발해 경찰에 수사를 의뢰했다. 신고 사업자에게는 이들과 거래하지 말라고 통보했고, 앱마켓에는 접속차단을 요청했다.
  - 2026-08 개정 특금법 시행 후에는 불법 영업에 가담한 사람이 일정 기간 국내 가상자산사업자의 대주주가 될 수 없다.
  - 출처: [법무법인 태평양(BKL) Legal Update](https://www.bkl.co.kr/law/insight/newsletter/6614); 같은 시기로 보이는 금융위 게시물 [fsc.go.kr 87177](https://www.fsc.go.kr/po010103/87177?curPage=22). **[공식확인 필요: 후속 검색에서 6/25 보도자료 원문을 특정하지 못했고, 적발된 해외거래소 4곳의 이름도 확인하지 못함]**
- 2026-10-30 FIU 발표:
  - DAXA가 적발한 미신고 업체 3곳(테더맥스·슈퍼트러스트·이지스벤처스)을 수사기관에 통보했다. 누적 통보는 47개 업체다. 테더맥스·슈퍼트러스트는 국내 접속차단을 요청했다.
  - DAXA의 2026-06 합동조사에서 적발 업체의 평균 거래수수료는 1.5~10%로, 국내 5대 원화거래소 평균(0.16%)의 최대 62배였다.
  - 출처: [네이트(FIU 보도) 2026-10-30](https://news.nate.com/view/20261030n29878); [아시아경제 2026-10-30](https://view.asiae.co.kr/article/2026103016094883766); [네이트 2026-10-30](https://m.news.nate.com/view/20261030n24360)

**구글플레이 앱 차단 경과(2026)**
- 2026-01-14 구글은 한국 대상 가상자산 거래소·수탁형 지갑 앱에 새 정책을 공지했다.
  - 개발자 콘솔에 FIU 신고수리 증빙('신고수리 완료' 서류)을 올려야 한다. 시행일은 2026-01-28이다.
  - 미신고 거래소는 신규 이용자가 앱을 설치할 수 없고 기존 이용자는 업데이트를 받지 못하게 될 예정이었다. 바이낸스·OKX가 영향 대상으로 지목됐다.
  - 당시 FIU 신고를 마친 국내 플랫폼은 27곳이었다.
  - 출처: [Cointelegraph](https://cointelegraph.com/news/google-play-crypto-app-rules-south-korea-exchanges-risk) [2차]; [The Block](https://www.theblock.co/post/385892/google-play-ban-south-korea) [2차]; [Yahoo Finance](https://finance.yahoo.com/news/google-play-block-binance-okx-114810381.html) [2차]; [FX Leaders 2026-01-16](https://www.fxleaders.com/news/2026/01/16/south-koreas-jan-28-rule-could-block-17-crypto-apps-from-google-play/) [2차]; [블록미디어](https://www.blockmedia.co.kr/archives/1032177); [다음(크립토브리핑) 2026-01-26](https://v.daum.net/v/20260126141418308)
- 1/28 차단은 바로 집행되지 않았다. 2026-02-21 기준으로 바이낸스 등 주요 해외 거래소 앱을 여전히 설치할 수 있었다는 보도가 있다 — [네이트 2026-02-21](https://m.news.nate.com/view/20260221n06027)
- 2026-07:
  - 디지털애셋은 최소 29개 해외 거래소가 국내 구글플레이에서 "설치 불가"라고 보도했다. 바이비트 앱 지원은 7/10, OKX는 7/24에 중단됐고, OKX는 4일 만에 검색·설치가 다시 됐다 — [디지털애셋](https://www.digitalasset.works/news/articleView.html?idxno=42150)
  - 코인딱도 7/24부터 신규 다운로드가 막혔다고 보도했다 — [코인딱](https://www.coinddak.com/news/articleView.html?idxno=7121)
- 서울경제 보도(보도일 미확인, 2026-08경으로 추정) — [서울경제](https://www.sedaily.com/article/20080941):
  - OKX 앱은 차단 한 달 만에 국내 플레이스토어에서 다시 검색·설치할 수 있게 됐고, 바이낸스 앱도 내려받을 수 있었다.
  - OKX는 OKX벤처스를 통해 코인원 지분 19.6%를 갖고 있다. 기사는 국내 지분이 얽힌 거래소가 예외를 받는 것 아니냐는 의문을 제기했다.
  - FIU는 "OKX는 국내에서 적극 영업하지 않는다"고 답했다.
- 바이낸스 측 설명(보도 인용): 이미 설치된 앱은 정상 작동하고 웹으로 계정에 접속하는 데도 문제가 없다. 다만 기기를 바꾸거나 초기화한 뒤 다시 설치하는 것은 실패할 수 있다 — [Yellow(한국어)](https://yellow.com/ko/news/%EB%B0%94%EC%9D%B4%EB%82%B8%EC%8A%A4%EC%99%80-okx-1%EC%9B%94-28%EC%9D%BC%EB%B6%80%ED%84%B0-%ED%95%9C%EA%B5%AD%EC%97%90%EC%84%9C-%EA%B5%AC%EA%B8%80-%ED%94%8C%EB%A0%88%EC%9D%B4-%EC%82%AC%EC%9A%A9-%EA%B8%88%EC%A7%80%EB%90%98%EB%8A%94-%EC%9D%B4%EC%9C%A0) [2차]; [네이트 크립토퀵서치 2026-01-29](https://news.nate.com/view/20260129n35138) [2차]
- 안랩은 공식 스토어 차단 뒤 늘어나는 보안 위험(비공식 설치 경로 등)을 다룬 분석을 냈다(제목 기준, 세부 내용 미확인) — [AhnLab ASEC](https://asec.ahnlab.com/en/92277/); [AhnLab 콘텐츠센터](https://www.ahnlab.com/ko/contents/content-center/36072)

**웹사이트 차단**
- FIU는 미신고 해외 거래소 웹사이트 차단을 방송미디어통신심의위원회에 요청했다. 하지만 실제 차단 여부는 방미심위가 자체 기준과 절차로 심의해 정하는 구조이고, 심의가 늦어져 2026-07 기준 실제 차단은 이뤄지지 않았다 — [법무법인 비트(2026-07 자료)](https://veatlaw.kr/main/board_detail/2024) **[공식확인 필요]**
- 앱 차단은 앱 마켓 배포를 막는 것이지 거래소 서버 접속을 막는 방식이 아니다(거래소 측 자료) — [BTCC 아카데미](https://www.btcc.com/ko-KR/academy/others/the-way-to-deal-with-blocking-crypto-exchanges) [업체 자료]

**이용자 개인 처벌 여부**
- 처벌 조문의 주체는 영업자다. 이용자 처벌 근거는 검색에서 확인되지 않았다.
- 금융위의 경고: 미신고 사업자는 가상자산이용자보호법·특금법 관계법령을 적용받지 않아 보호장치가 부족하다. 또 "이용자 본인의 자금이 미신고 사업자의 범죄자금과 혼재되거나, 거래상대방·자금출처 확인 과정에서 수사 대상이 되는 등 예상하지 못한 불이익"을 받을 수 있다 — [금융위 게시물 87177](https://www.fsc.go.kr/po010103/87177?curPage=22); [금융위 보도자료 78323](https://fsc.go.kr/no010101/78323)
- 금융위는 과거(2021~2022년경) VPN 등 "우회 접속까지 처벌할 순 없다"는 입장이었다 — [블록미디어](https://www.blockmedia.co.kr/archives/187016)
- 미신고 해외 거래소를 위해 국내 회원을 모으거나 레퍼럴 수수료를 받는 활동은 형사책임 문제가 될 수 있다는 2026년 법률 해설이 있다(개정 특금법 조문은 제시하지 않음) — [로톡](https://www.lawtalk.co.kr/posts/168312) [법률칼럼]

**거래소별 상황**
- **바이낸스**
  - 2021-08 원화 거래쌍과 원화 결제 옵션을 중단했다 — [FXStreet 2021-08-13](https://www.fxstreet.com/amp/cryptocurrencies/news/binance-discontinues-south-korean-won-trading-pairs-payment-options-202108131318)
  - 공식 "금지 국가 목록"(2024-02-27 갱신본) 검색 발췌에는 한국이 보이지 않는다. 바이낸스는 수시로 국가를 추가할 수 있다 — [Binance List of Prohibited Countries](https://www.binance.com/en/legal/list-of-prohibited-countries/) **[공식확인 필요: 현행본 미확인]**
  - 2026-06 삼성전자·SK하이닉스·현대차 연계 주식 무기한선물을 내놓았지만, 한국 거주자는 이용할 수 없다고 보도됐다 — [MEXC News](https://www.mexc.com/news/1124485) [2차, 출처 URL 귀속 불확실]
- **바이낸스와 고팍스**
  - FIU는 2025-10-15 고팍스 운영사 스트리미의 임원변경 신고를 수리했다. 바이낸스가 대주주가 된 지 약 2년 8개월 만이고, 이로써 바이낸스가 고팍스의 실질 경영권을 확보했다 — [헤럴드경제 2025-10-16](https://www.heraldk.com/article/2025101618140727930); [비즈워치 2025-10-16](https://news.bizwatch.co.kr/article/mobile/2025/10/16/0015); [한국경제](https://www.hankyung.com/article/2025101637811)
  - Binance (AP) Holdings가 스트리미 지분 67.45%를 갖고 있다(2025년 말). 디지털자산기본법 논의에서 거래소 대주주 지분 상한(20% 수준 거론)이 검토되고 있다.
  - 스트리미의 2025년 영업수익은 43억원, 영업손실은 76억원이고, 자본총계 −2,185억원으로 완전자본잠식 상태다 — [딜사이트](https://dealsite.co.kr/articles/169527); [딜사이트](https://dealsite.co.kr/articles/169637)
  - 바이낸스는 고팍스 지분을 갖고 있지만 한국에 독립 법인을 운영하지 않는다(Binance.com 자체는 미신고) — [Cointelegraph](https://cointelegraph.com/news/google-play-crypto-app-rules-south-korea-exchanges-risk) [2차]
- **OKX**: 국내 당국이 과거 미신고 영업으로 지목한 적이 있다고 보도됐다 — [The Block](https://www.theblock.co/post/385892/google-play-ban-south-korea) [2차]. 코인원 지분 19.6%(OKX벤처스) — [서울경제](https://www.sedaily.com/article/20080941)
- **바이비트**: 2026-07-10 구글플레이 앱 지원이 차단됐다고 보도됐다 — [디지털애셋](https://www.digitalasset.works/news/articleView.html?idxno=42150)
- **비트겟·하이퍼리퀴드**: 한국 당국이 직접 지목한 조치나 기사는 검색에서 나오지 않았다(Gaps 참조).

**국내 원화 거래소(온램프) 제재 위험**
- 2026-03-17 FIU는 빗썸에 약 2,450만 달러의 과태료와 6개월 영업 일부정지 처분을 내렸다(AML 위반) — [Cointelegraph](https://cointelegraph.com/news/south-korea-fines-bithumb-24-5m-six-month-partial-suspension-aml) [2차]; [FXStreet](https://www.fxstreet.com/cryptocurrencies/news/south-korea-fines-bithumb-24m-orders-6-month-partial-business-suspension-202603170559) [2차]
- 코인원은 약 350만 달러(52억원) 과태료와 함께 3개월간 신규 이용자의 가상자산 입출금 금지 처분을 받았다(KYC/AML 미흡 약 7만 건) — [The Block](https://theblock.co/post/397206/coinone-hit-with-3-5-million-fine-three-month-partial-suspension-over-aml-violations-reports) [2차]; [Whale Alert](https://whale-alert.io/stories/aea5016a900329/South-Korea-fines-Coinone-52B-won-bars-new-user-depositswithdrawals-for-3-months-after-on-site-finds-70000-KYCAML-failures) [2차, 날짜 미확인]
- 법원은 FIU의 두나무(업비트) 영업정지 처분을 취소했다 — [Cointelegraph](https://cointelegraph.com/news/south-korea-court-cancels-dunamu-upbit-suspension-fiu) [2차, 날짜 미확인]

### Inferences
- 2026-11 현재 개인이 바이낸스 등을 쓴다는 이유만으로 형사처벌될 근거는 보이지 않는다. 다만 당국은 앱·웹·송금 같은 "접근 경로 차단"을 일관되게 강화하고 있다. 그래서 현실적인 위험은 처벌보다 다음과 같은 운영상 문제다.
  - 송금 경로가 막힘
  - 사고가 나도 법적 보호를 받지 못함
  - 수사·자금출처 소명에 휘말릴 수 있음
  - 기기를 바꾸면 앱을 다시 설치하지 못할 수 있음
- 구글플레이 차단은 일관되게 집행되지 않았다(1월 미집행 → 7월 부분 집행 → 일부 앱 재등장). 그래서 앱 사용 가능 여부는 수시로 바뀐다고 봐야 한다. 실행 계획은 웹, 이미 설치한 앱, API를 전제로 짜되 언제든 막힐 수 있다고 가정하는 편이 안전하다.
- 자동매매 봇 관점: 앱 차단은 API 접근과 직접 관계가 없다. 그러나 방미심위의 웹·도메인 차단이 실제로 실행되면 API 도메인 접근에도 영향이 갈 수 있다(추론, 확인 필요).
- 빗썸·코인원 계정을 새로 열면 영업 일부정지(신규 고객의 외부 입출금 제한) 기간에 걸려 해외 송금이 막힐 수 있다. 이미 쓰던 업비트 계정 경로가 가장 현실적이다(추론).
- 바이낸스가 고팍스를 인수했다고 Binance.com 이용이 국내에서 합법화되는 것은 아니다. 고팍스는 파생상품을 제공하지 않는다(4번 항목 참조).

### Gaps
- 2026-06 FIU 보도자료 원문과 적발된 해외거래소 4곳의 이름.
- 2026-11 현재 바이낸스·OKX·바이비트·비트겟 앱의 국내 구글플레이·애플 앱스토어 실제 상태. iOS 정책은 검색 결과가 없었다.
- 하이퍼리퀴드의 한국 이용자 제한, 약관상 제한 국가, 특금법상 DEX 프런트엔드가 신고 대상인지 — 검색 한도가 소진돼 조사하지 못했다.
- 비트겟의 한국 관련 개별 조치 — 조사하지 못했다.
- 바이낸스 현행 이용약관에 한국 거주자 제한이 있는지(2024년판만 확인).
- 2026-03 보도로 소개된 "바이낸스의 한국 재진출·서비스 확대는 규제 심사가 끝나기 전까지 잠정적"이라는 내용은 출처 URL을 특정하지 못해 인용하지 않았다.

---

## 2. 자금 이동 경로 — 원화 → 업비트·빗썸 → 해외 거래소 → 귀환, 트래블룰, 개정 특금법(2026-08-20)·개정 외국환거래법(2026-12 예정), 비용·한도

### Takeaway
현재 실무 경로는 다음 순서다: 원화 → 업비트(본인 계정)에서 USDT·BTC 매수 → 트래블룰 본인 명의 확인 → 본인 명의 해외 거래소 계정 → 같은 경로로 귀환. 그런데 규제가 세 단계로 겹쳐 오고 있다.
1. 2026-08-20 개정 특금법·시행령 주요 규정 시행(신고제 강화)
2. 2026-12 초 시행 예정인 개정 외국환거래법: 국경 간 가상자산 이전업자 등록, 한국은행 외환전산망 보고, 국세청 등과 정보 공유
3. 2027-02-20 트래블룰 100만원 기준 폐지: 모든 금액에 적용되고, 해외 거래소·개인지갑은 위험도별로 제한

결과적으로 경로는 "가능하지만 모든 이동이 기록·감시되는" 쪽으로 좁아지고 있다. 여기에 2026-10-30 바이낸스 해킹 직후 국내 거래소들이 바이낸스행 출금을 제한할 수 있다고 공지했다.

### Cited Findings

**현행 트래블룰과 업비트 출금 규칙**
- 트래블룰은 2022-03-25 특금법에 따라 시행됐다. 100만원 이상 사업자 간 이전에 송·수신인 정보를 제공해야 한다 — [금융위 보도자료](https://www.fsc.go.kr/po010101/77579)
- 업비트 고객센터 안내:
  - 100만원 이상 입출금은 (i) 트래블룰 솔루션 연동 사업자, (ii) 계정주 확인이 가능한 사업자, (iii) 등록된 개인지갑 주소로만 출금할 수 있다.
  - "위험평가를 통과한 해외 거래소는 본인 계정으로부터의 입금만 가능하고 출금은 불가"하다.
  - 출처: [업비트 고객센터](https://support.upbit.com/hc/ko/articles/5127139476121-%ED%8A%B8%EB%9E%98%EB%B8%94%EB%A3%B0-%EC%86%94%EB%A3%A8%EC%85%98-%EC%97%B0%EB%8F%99-%EA%B0%80%EC%83%81%EC%9E%90%EC%82%B0%EC%82%AC%EC%97%85%EC%9E%90-%EC%99%B8%EC%97%90-%EC%9E%85%EA%B8%88-%EA%B0%80%EB%8A%A5%ED%95%9C-%EA%B1%B0%EB%9E%98%EC%86%8C%EA%B0%80-%EC%9E%88%EB%82%98%EC%9A%94); [업비트 트래블룰 알아보기](https://support.upbit.com/hc/ko/articles/4498679629337-%ED%8A%B8%EB%9E%98%EB%B8%94%EB%A3%B0-%EC%95%8C%EC%95%84%EB%B3%B4%EA%B8%B0) **[게시일 미확인 — 현행 여부와 바이낸스가 어느 범주인지 공식확인 필요]**
- 업비트에서 바이낸스로 100만원 이상 보낼 때는 영문명 일치 등 본인 확인이 필요하다(2026-07 기준 블로그) — [Bullstory](https://bullstory.io/blog/바이낸스-비트코인-완전-정복-현재-가격부터-업비트-송금까지-2026) [블로그]
- 업비트는 "입금처가 확인되지 않은 100만원 미만 가상자산 출금"도 "13일부터" 제한한다고 보도됐다 — [디지털타임스](https://www.dt.co.kr/article/11644222); [오늘경제](https://www.startuptoday.co.kr/news/articleView.html?idxno=404730); [녹색경제신문](https://www.greened.kr/news/articleView.html?idxno=323184). **[시행 연월이 불명확: 발췌문에는 '2026-07-10'이라는 날짜가 있지만 검색 메타데이터는 1년 이상 전 기사로 표시. 디지털타임스 기사번호로 보면 2025년 3월경으로 추정되나 확인 필요]**
- 2026-10-30 업비트·빗썸·코인원이 바이낸스 보안사고와 관련해 출금 주의 공지를 냈다. 업비트는 "투자자 보호를 위해 필요하다고 판단하면 바이낸스로의 출금을 제한할 수 있다"고 밝혔고, 자산 동결 요청에도 협조한다고 했다 — [이투데이 2026-10-30](https://www.etoday.co.kr/news/view/2642406)

**개정 특금법·시행령(2026-08-20 / 2027-02-20)**
- 2026-03-30 시행령 개정안을 입법예고했다. 사업자 진입규제를 강화하고 트래블룰을 100만원 미만까지 넓히는 내용이다 — [네이트 2026-03-30](https://m.news.nate.com/view/20260330n30276); [블록미디어](https://www.blockmedia.co.kr/archives/1070648)
- 개정 시행령은 (2026-08) 11일 국무회의를 거쳤다. 대주주·신고요건 등 주요 규정은 2026-08-20부터 시행된다. 트래블룰 금액 기준 폐지는 6개월 유예 뒤 2027-02-20부터 적용된다 — [이데일리](https://edaily.co.kr/News/Read?mediaCodeNo=257&newsId=02420646645546008); [Xangle](https://xangle.io/insight/events/6a7a759f962c5f6693cff437)
- 기준을 바꾼 배경: 2025년 하반기 국내 사업자 간 이전거래의 약 60%가 100만원 미만이었다(쪼개기 송금으로 규제를 피할 우려) — [이데일리](https://edaily.co.kr/News/Read?mediaCodeNo=257&newsId=02420646645546008); [Xangle](https://xangle.io/insight/events/6a7a759f962c5f6693cff437)
- 해외 거래소·개인지갑 거래는 위험도에 따라 다르게 다룬다:
  - 저위험 해외 사업자와의 거래는 허용한다.
  - 그 밖의 해외 거래소와 개인지갑은 송·수신인이 같은 사람일 때만 허용한다.
  - 고위험 거래는 제한한다.
  - 1,000만원 이상 해외 거래소·개인지갑 거래에는 사업자가 자체 의심거래 관리체계를 운영해야 한다(일부 보도는 "의심거래로 FIU에 보고"라고 표현).
  - 출처: [ZDNet Korea 2026-02-04](https://zdnet.co.kr/view/?no=20260204140238); [이투데이(넥스블록)](https://www.etoday.co.kr/news/view/2613380); [위키트리](https://www.wikitree.co.kr/articles/1170308); [이데일리](https://edaily.co.kr/News/Read?mediaCodeNo=257&newsId=02420646645546008)
- 받는 쪽 사업자는 이전정보가 빠져 있으면 상대 사업자에 요구해야 하고, 그래도 제공되지 않으면 거래를 거절해야 한다 — [이투데이(넥스블록)](https://www.etoday.co.kr/news/view/2613380)
- 특금법(법률) 개정분 중 신고제와 퇴직자 제재조치 통보는 2026-08-20부터, 이전거래 자금세탁방지 의무 등 나머지는 공포 후 6개월부터 시행된다 — [이투데이(넥스블록)](https://www.etoday.co.kr/news/view/2613380); [넥스블록](https://m.nexblock.co.kr/article/1002775) **[공식확인 필요]**
- 일부 블로그는 트래블룰 전면 시행일을 8/20으로 적는 등 정보가 엇갈린다 — [ktradeatlas](https://ktradeatlas.com/travel-rule/) [블로그]

**개정 외국환거래법(국경 간 가상자산 이전) — 2026-12 시행 예정**
- 국경 간 가상자산 이전업자는 재정경제부 장관에게 미리 등록해야 한다(전산설비, 외국환업무 경력자 또는 교육 이수자 2명 이상 등). 국경 간 이전 내역은 한국은행 외환전산망에 보고하고, 이 정보는 국세청·관세청·금감원·FIU와 공유한다 — [아시아경제 2026-05-26](https://view.asiae.co.kr/article/2026052609425726001); [한국경제TV 2026-05-26](https://www.wowtv.co.kr/NewsCenter/News/Read?articleId=A202605260188); [한국세정신문(국무회의 의결)](https://www.taxtimes.co.kr/news/article.html?no=275266)
- 시행령 입법예고안에 따르면 국내 사업자와 해외 사업자 사이의 이전뿐 아니라 **국내 사업자와 개인지갑 사이의 이전**도 "가상자산이전업무"에 들어간다 — [법률신문(대륙아주)](https://www.lawtimes.co.kr/news/articleView.html?idxno=228533)
- 보이스피싱, 불법 무역대금, 가상자산 환치기 같은 중대 위반은 한 번만 걸려도 등록을 취소한다("원스트라이크 아웃"). 과징금 상한은 위반 이익의 최대 100%까지 올라간다 — [아시아경제](https://view.asiae.co.kr/article/2026052609425726001); [서울경제](https://www.sedaily.com/article/20098844)
- 공포 후 6개월 뒤 시행된다. 한 보도는 2026-12-03 시행 예정이라고 했고, 다른 보도는 "12월 초"라고만 했다 — [네이트 2026-05-26](https://news.nate.com/view/20260526n32235); [법률신문](https://www.lawtimes.co.kr/news/articleView.html?idxno=228533) **[공식확인 필요]**
- "해외 코인 거래 관리망 확대…6월 신고(해외금융계좌)에 연말 보고까지" — [이투데이](https://m.etoday.co.kr/news/view/2589554)

**비용·한도**
- 2026-07-28 보도: 국내 거래소에서 USDT·USDC 등 스테이블코인 6종의 거래 수수료가 무료로 바뀌었다(출금 수수료와는 별개). 발췌문에서는 어느 거래소인지 분명하지 않다 — [비즈워치 2026-07-28](https://news.bizwatch.co.kr/article/mobile/2026/07/28/0014) **[거래소 확인 필요]**
- 온체인 송금비용(거래소 출금수수료 제외):
  - USDT 1,000달러 송금은 체인에 따라 약 2센트에서 15달러까지 든다. 트론은 대부분 1달러 이하다.
  - 2026-04 BTC로 50달러를 보내면 약 0.44달러가 들었다(혼잡하면 크게 오름).
  - 출처: [Plisio – USDT 이체 수수료](https://plisio.net/ko/crypto/usdt-transfer-fee) [업체 자료]; [Plisio – 암호화폐 수수료](https://plisio.net/ko/crypto/crypto-fees) [업체 자료]
- 김치프리미엄:
  - 2026-07 업비트 BTC가 바이낸스 환산가보다 약 2.1% 낮은 "역김프" 상태였다 — [Bullstory](https://bullstory.io/blog/가상화폐-실시간-시세-거래소마다-숫자가-다른-진짜-이유-2026년-7월) [블로그]
  - 2026-08에도 "올해 국내 가격이 해외보다 낮은 역김프가 이어진다" — [MyDailyByte](https://www.mydailybyte.com/post/%EC%97%AD%EA%B9%80%EC%B9%98%ED%94%84%EB%A6%AC%EB%AF%B8%EC%97%84-2608) [블로그]
- DAXA 비교: 국내 5대 원화거래소의 평균 거래수수료는 0.16%(2026-06 조사) — [네이트(FIU 보도) 2026-10-30](https://news.nate.com/view/20261030n29878)

### Inferences
- **현재(2026-11) 실무 경로(추론)**:
  1. 원화를 업비트에 입금한다.
  2. USDT(트론 등 저비용 체인) 또는 BTC를 산다.
  3. 본인 명의 바이낸스 계정으로 출금한다(영문명 일치, 계정주 확인).
  4. 선물 지갑으로 옮긴다.
  5. 귀환할 때는 바이낸스에서 업비트 본인 계정으로 입금하고, 매도해 원화로 출금한다.
  - 2026-10-30 공지("바이낸스로의 출금을 제한할 수 있다")는 현재 업비트→바이낸스 출금이 허용돼 있다는 뜻으로 읽힌다.
- **2026-12 이후**: 국경 간 이전 내역이 한국은행 전산망에 보고되고 국세청과 공유된다. 과세가 시작되기 전이라도 자금 흐름 기록은 남는다. 해외금융계좌 신고(5억원 초과) 누락이 적발될 가능성도 커진다.
- **2027-02-20 이후**:
  - 소액도 트래블룰을 적용받아 "100만원 미만 쪼개기"가 통하지 않는다.
  - 바이낸스가 "저위험"으로 분류되거나 "송·수신인 동일" 조건을 충족해야 출금할 수 있다.
  - 고위험으로 분류되면 경로 자체가 막힐 위험이 있다.
  - 하이퍼리퀴드 같은 DEX를 쓰려면 개인지갑을 거쳐야 하므로 "본인 소유 개인지갑 등록"이 필수가 된다.
- **역김프의 영향**: 국내에서 사서 해외로 보내는 쪽은 유리하지만 귀환할 때는 불리하다. 왕복으로 보면 프리미엄이 바뀌는 것 자체가 위험이다.
- 해외 거래소가 출금을 멈추면(10월 해킹 때 약 56시간) 국내에서 증거금을 보충할 수 없어 청산 위험이 커진다. "해외 거래소엔 최소 증거금만 둔다"는 원칙과 "버퍼가 부족하면 청산된다"는 위험은 서로 맞바꾸는 관계다(6번 항목 참조).

### Gaps
- 업비트·빗썸의 현행 "입출금 가능 해외 사업자 목록"과 바이낸스·바이비트·OKX·비트겟·하이퍼리퀴드(개인지갑) 각각의 출금·입금 가능 여부(2026-11).
- 업비트 출금수수료 실제 금액(BTC, USDT-TRC20 등) — 공식 페이지에 접속할 수 없었다.
- "저위험 해외 사업자" 판정 기준과 명단(시행령·고시) — 확인하지 못했다.
- "첫 원화 입금 뒤 72시간 출금 제한" — 검색 발췌에만 있고 출처를 특정하지 못했다.
- "해외 거래소에서 국내로 연 1만 달러 넘게 들여오면 국세청 통보 대상"이라는 주장([glasswallet](https://glasswallet.com/calculate/crypto-tax/exchange-tax-comparison/) [블로그]) — 외화송금 기준과 혼동했을 가능성이 있어 확인하지 못했다.
- 개정 외국환거래법 시행령 최종본과 정확한 시행일.

---

## 3. 규제권 대안 — CME 비트코인 선물(BTC·MBT·BFF)과 국내 증권사 해외선물 계좌

### Takeaway
CME에는 표준 BTC(5 BTC), 마이크로 MBT(0.1 BTC), Bitcoin Friday BFF(0.02 BTC, 매주 금요일 만기)가 상장돼 있고, 2026-05-29부터 24시간·주 7일 거래로 바뀌었다. 그러나 **국내 증권사 해외선물 계좌로는 가상화폐 선물을 거래할 수 없다**. 한국투자증권 2025-10 공지는 "국내 제도상 거래 제한, 시세만 참고용 제공"이라고 했고, 2017년 금융위 입장 이후 바뀌었다는 확인은 없다. 따라서 "국내 증권사를 거치는 CME 비트코인 선물"은 2026-11 기준 사실상 막힌 경로다. 남은 대안은 해외 FCM 직접 계좌(외환법·세금 불확실)와 미국 상장 비트코인 선물 ETF(국내 증권사 해외주식 계좌, 레버리지 상품은 사전교육 1시간 필요)다.

### Cited Findings

**국내 증권사의 취급 여부**
- 한국투자증권 2025-10 공지: CME 가상화폐선물 4종의 시세 조회는 제공한다. 하지만 국내 제도상 가상화폐선물 거래가 제한돼 거래는 지원하지 않고 시세는 참고용이다 — [한국투자증권 공지](https://securities.koreainvestment.com/main/customer/notice/Notice.jsp?cmd=TF04ga000002&num=45495)
- 2017-12 금융위 입장: 비트코인 같은 가상화폐는 자본시장법상 금융투자상품이 아니어서 국내에서 파생상품 거래를 할 수 없다. 해외에서 거래된다고 국내 거래가 가능해지는 것도 아니다. 이에 신한금융투자·이베스트투자증권은 해외선물 중개 준비를 중단했다 — [한국경제 2017-12-06](https://www.hankyung.com/article/2017120667471); [이데일리](https://edaily.co.kr/News/Read?mediaCodeNo=257&newsId=02437046616155896); [서울경제](https://m.sedaily.com/article/11734685)
- 예탁원은 "국내에서 CME 비트코인 선물 취급 가능...감독당국 의지 문제"라고 했다. 증권사 요청이 없어 매매를 지원하지 않았다는 설명이다 — [블록미디어](https://www.blockmedia.co.kr/archives/197874) [보도일 미확인]
- 2026년에 국내 증권사의 비트코인 선물 중개를 새로 허용했다는 공식 발표는 검색에서 찾지 못했다. 2026-07-15 공개된 국내 코인 현물 ETF 청사진 보도는 "법 개정·김프 해소·선물 도입"이 먼저 필요하다고 정리했다. 즉 국내 비트코인 선물 제도는 아직 없다 — [네이트 2026-07-15](https://m.news.nate.com/view/20260715n29782)

**CME 상품 사양(1차: cmegroup.com)**
- 24/7 거래:
  - CME는 2026-02-19 발표대로 2026-05-29(금) 16:00 CT부터 암호화폐 선물·옵션의 24/7 거래를 시작했다. 2025-10에는 "2026년 초" 계획으로 처음 발표했었다.
  - Globex에는 주말 정기점검 시간이 있다. ClearPort는 토요일 02:00–04:00 CT에 멈춘다. 비트코인 선물 이벤트 계약도 같은 날 24/7로 바뀌었다.
  - 출처: [CME 보도자료 2026-02-19](https://www.cmegroup.com/media-room/press-releases/2026/2/19/cme_group_to_launch247cryptocurrencyfuturesandoptionstradingonma.html); [CME IR](https://investor.cmegroup.com/news-releases/news-release-details/cme-group-announces-launch-247-cryptocurrency-futures-and); [CME ClearPort 공지 2026-05-21](https://www.cmegroup.com/notices/risk-management-and-monitoring/2026/05/20260521.html); [CME Globex 공지 2026-05-25](https://www.cmegroup.com/notices/electronic-trading/2026/05/20260525.html)
- BFF(Bitcoin Friday):
  - 크기는 0.02 BTC(1/50 BTC)이고 현금결제다. 매주 금요일 16:00 ET에 만기된다.
  - 가장 가까운 금요일과 그다음 두 금요일물이 상장되고, 신규물은 목요일에 추가된다.
  - 정산 기준은 CME CF Bitcoin Reference Rate New York Variant(BRRNY)다. 최소 틱은 $5/BTC, 즉 계약당 $0.10이다.
  - 2024 CME 기사는 명목가 약 $1,300, 증거금 약 $300(전일 정산가의 24%)을 예로 들었다.
  - 출처: [CME BFF 팩트카드](https://www.cmegroup.com/content/dam/cmegroup/markets/cryptocurrencies/files/bitcoin-friday-futures-fact-card.pdf); [CME 2024 기사](https://www.cmegroup.com/articles/2024/bitcoin-friday-futures-your-new-bff.html)
- MBT는 0.1 BTC(표준 BTC 5 BTC의 1/50)이고, 틱은 $5/BTC, 즉 계약당 $0.50이다 — [CME MBT 개요](https://www.cmegroup.com/education/courses/introduction-to-bitcoin/micro-bitcoin-futures-product-overview); [Optimus Futures](https://optimusfutures.com/Micro-Bitcoin-Futures.php) [2차]
- 증거금:
  - 2026-03-24 기준 표준 BTC 1계약의 초기증거금은 약 $140,000, MBT는 약 $2,800이었다(브로커 자료).
  - CME는 변동성에 따라 증거금을 수시로 조정한다. FCM(선물중개회사)은 CME 최소치보다 높게 요구할 수 있다.
  - 24/7 확대와 함께 증거금을 바꾼다는 발표는 없었다.
  - 출처: [Schwab](https://international.schwab.com/story/micro-bitcoin-and-ether-futures-offer-small-bites-crypto) [2차, 수치 귀속 불확실]; [Optimus Futures](https://optimusfutures.com/crypto-futures.php) [2차]; [Kraken Learn](https://www.kraken.com/learn/futures-trading-micro-vs-standard-contracts) [2차]
- CFTC Staff Letter 26-05(2026년 초): FCM이 BTC·ETH를 헤어컷(할인) 적용 후 증거금 담보로 받을 수 있다 — [NexusFi](https://nexusfi.com/a/regulation/crypto-futures-regulation) [2차]
- 2026년 신상품: CME CF 비트코인 변동성지수(BVX) 선물 첫 거래(2026-06), Nasdaq CME Crypto Index 선물 출시 발표(2026-05-14) — [CME 2026-06-05](https://www.cmegroup.com/media-room/press-releases/2026/6/05/cme_group_announcesfirsttradesfornewbitcoinvolatilityfutures.html); [CME 2026-05-14](https://www.cmegroup.com/media-room/press-releases/2026/5/14/cme_group_to_launchnasdaqcmecryptoindexfutures.html)
- 24/7 출시 무렵 BTC 가격은 약 $73,000이었다 — [Investing.com 한국어](https://kr.investing.com/news/cryptocurrency-news/article-1966080)

**해외파생상품 개인투자자 규제(국내 증권사를 거칠 때)**
- 2025-12-15부터:
  - 해외 파생상품을 처음 거래하는 개인은 사전교육 최소 1시간과 모의거래 최소 3시간을 이수해야 한다.
  - 해외 레버리지 ETP는 사전교육 1시간이 의무다.
  - 이수 시간은 연령·투자경험에 따라 달라질 수 있다.
  - 개인의 해외파생 손실은 2024년 약 3,899억원으로 5년 연속 손실이었다.
  - 출처: [경북매일 2025-12-15(금감원 발표)](https://kbmaeil.com/article/20251215500253)
- 키움증권 공지(원문 접속 불가, 검색 발췌): 시행일 이후 해외파생상품을 새로 거래하는 일반 개인은 사전교육 1시간과 모의거래 3시간을 이수해야 한다. 모의거래는 증권사 시스템이나 CME 모의거래 시스템으로 할 수 있다. 시행일 이전에 해외 선물·옵션을 거래한 경험이 있으면 면제될 수 있다 — [키움증권 공지](https://kiwoom.com/h/hts/popup/VHtsNoticePopView?flag=content&gubun=1&mtsgb=&pagegb=2&seq=00002429&title=%ED%95%B4%EC%99%B8%EC%84%A0%EB%AC%BC%EC%98%B5%EC%85%98+%EC%82%AC%EC%A0%84%EA%B5%90%EC%9C%A1+%EB%AA%A8%EC%9D%98%EA%B1%B0%EB%9E%98+%EC%A0%9C%EB%8F%84+%EC%95%88%EB%82%B4&tp=); 증권사 안내 페이지 [KB증권](https://www.kbsec.com/go.able?linkcd=s040409060000), [미래에셋](https://securities.miraeasset.com/imf/800/imf101.do), [한국투자 모의투자](https://www.truefriend.com/main/research/virtual/_static/TF07db010000.jsp)
- 기본예탁금:
  - 2019 금융위 발전방안은 "증거금과 중복규제인 기본예탁금은 완화"하는 방향이었다 — [금융위](https://www.fsc.go.kr/no010101/73717)
  - 2020 기사는 (국내 파생) 처음 거래할 때 1,000만원 이상의 기본예탁금이 필요하다고 보도했다 — [딜사이트](https://dealsite.co.kr/articles/65983)
  - 2026 블로그도 국내 선물옵션 기본예탁금을 1천만원 이상으로 정리했다 — [IndexFlowPro](https://indexflowpro.com/derivatives-account/) [블로그]
  - **해외파생상품의 현행 기본예탁금 요건은 확인하지 못했다.**
- 한 블로그는 CME 등 해외파생에는 교육·모의거래 의무가 없다고 주장하지만 증권사 공지와 어긋난다 — [alexmoney 2026-09](https://www.alexmoney.co.kr/2026/09/2026-derivatives-futures-options-margin-call-guide.html) [블로그, 부정확]

**대안 1: 미국 상장 비트코인 선물 ETF(국내 증권사 해외주식 계좌)**
- 금융위(2024-01) 입장 — [금융위 보도참고](https://www.fsc.go.kr/no010101/81466?srchCtgry=&curPage=1&srchKey=sj&srchText=%EB%B9%84%ED%8A%B8%EC%BD%94%EC%9D%B8&srchBeginDt=2023-12-16&srchEndDt=2024-03-16); [이데일리 마켓인](https://marketin.edaily.co.kr/News/ReadE?newsId=01574406638757720):
  - 국내 증권사가 해외 상장 비트코인 현물 ETF를 중개하면 자본시장법 위배 소지가 있다.
  - 비트코인 선물 ETF는 선물계약을 기초로 하므로 현행법 위배가 아니다. 해외 비트코인 선물 ETF는 지금처럼 거래되고 달리 규율할 계획이 없다.
- 당시(2024-01경) KB증권은 비트코인 선물 ETF 23개의 신규 매수를 일시 중단했고, 다른 증권사도 중단을 검토했다 — [블록미디어](https://www.blockmedia.co.kr/archives/445851); [블록미디어](https://www.blockmedia.co.kr/archives/445211) [보도일 추정]
- 2025-12-15부터 해외 레버리지 ETP에는 사전교육 1시간이 의무다 — [경북매일](https://kbmaeil.com/article/20251215500253)

**대안 2: 해외 FCM 직접 계좌** — 근거를 확보하지 못했다(Gaps 참조).

### Inferences
- 국내 증권사를 거치는 CME 비트코인 선물은 2026-11 기준 쓸 수 없다고 보는 것이 안전하다. 실행 계획에서는 "향후 허용되면 쓸 옵션"으로만 둔다.
- 허용될 경우의 최소 자본(추정, BTC $73,000 기준):
  - BFF 1계약: 명목 약 $1,460, 증거금(24%) 약 $350.
  - MBT 1계약: 명목 약 $7,300, 증거금 약 $2,800(2026-03 수치).
  - 소액 전략에 잘 맞고, 2026-05-29 이후 24/7이라 주말 갭 문제도 사라졌다.
- 해외 FCM(예: IBKR) 직접 계좌:
  - 2017 금융위 입장("가상화폐는 금융투자상품이 아님")과 외환법상 "국내 투자중개업자를 거쳐야 한다"는 원칙이 적용될 가능성 때문에 적법성이 불확실하다.
  - 세금 분류도 불확실하다(5번 항목 참조). 전문가 확인 없이는 권하지 않는다(추론).
- 미국 비트코인 선물 ETF는 롤오버 비용이 들고 숏·레버리지 선택지가 제한적이다. 그래서 "선물 트레이딩"을 대신하기엔 불완전하다. 세금은 해외주식 양도소득세(22%, 연 250만원 공제)로 추정된다(5번 항목).

### Gaps
- 2026-11 현재 키움·삼성·미래에셋·NH·한국투자 등 증권사별 CME 가상화폐선물 취급 여부를 담은 최신 공지(한국투자 2025-10 공지 외에는 확인 못 함).
- 해외파생상품 기본예탁금 현행 기준, 증권사별 CME 마이크로 계약 수수료(계약당 달러), 해외선물 환전·증거금 관행 — 확인하지 못했다.
- CME 현행(2026-11) MBT·BFF·BTC 공식 증거금 — CME 마진 페이지에 접속할 수 없었다.
- IBKR 등 해외 FCM 직접 거래의 외국환거래법상 적법성과 신고 절차. 검색 발췌에 "금감원은 주식보상으로 받은 해외주식을 해외 증권사로 매매·예치하면 외환법 위반으로 제재받을 소지가 있으니 국내 투자중개업자를 거쳐야 한다고 안내"라는 내용이 있었지만, 원문 URL을 특정하지 못해 인용하지 않았다.
- CME Spot-Quoted futures 등 그 밖의 소형 계약 사양 — 조사하지 못했다.
- 2026년 미국 비트코인 선물·현물 ETF를 국내 증권사에서 살 수 있는지 재확인이 필요하다.

---

## 4. 국내 상품 — 비트코인 현물 ETF와 국내 거래소 파생상품 현황

### Takeaway
2026-11 현재 국내 비트코인 현물 ETF는 없다. 정부가 2026-07-14 "하반기 경제성장전략"에서 자본시장법을 고쳐 ETF 기초자산에 가상자산을 넣겠다고 발표했지만 국회를 통과하지 못했다. 국내 원화 거래소에는 선물·무기한선물 같은 파생상품이 없다. "코인 대여(렌딩)"도 2025-09 가이드라인으로 담보를 넘는 대여(레버리지) 금지, 연 20% 수수료 상한 등의 제한을 받는다. 국내에서 BTC 선물에 해당하는 합법 상품은 사실상 없다.

### Cited Findings
- 2026-07-14 금융위는 "2026년 하반기 경제성장전략"에서 ETF 기초자산 범위에 가상자산을 넣는 방향으로 법을 고치겠다고 밝혔다 — [서울경제TV 2026-07-16](https://www.sentv.co.kr/article/view/sentv202607160105); [네이트 2026-07-14](https://m.news.nate.com/view/20260714n30307)
- 현행 자본시장법은 ETF 기초자산을 금융투자상품·통화·일반상품 등으로 한정해 가상자산이 들어가지 않는다. 2025-06 민병덕 의원이 개정안을 냈지만 2026-06 기준 약 1년째 위원회 심사 단계다 — [리포테라](https://www.reportera.co.kr/economy/korea-bitcoin-spot-etf-roadmap-t/) [2차]
- 2025-08-26 정무위가 개정안을 법안소위에 회부했지만, 이후 소위 통과나 본회의 처리 소식은 없다(2026-11 블로그 정리) — [TILNOTE 2026-11](https://tilnote.io/en/pages/6aed13f18be42d394a48864a) [블로그]
- 청사진 보도는 법 개정, 김치프리미엄 해소, 선물 도입이 필요하다고 정리했다. 자본시장연구원은 운용사가 해외 플랫폼에서 현물을 직접 조달하게 하는 방안을 제안했고, 비트코인 ETF를 먼저 허용한 뒤 알트코인으로 넓히는 단계적 접근도 거론됐다 — [네이트 2026-07-15](https://m.news.nate.com/view/20260715n29782); [네이트](https://view.nate.com/tech/view/395656/)
- 금융위(2024-01): 국회가 자본시장법을 고치지 않는 한 비트코인 현물 ETF 발행과 중개는 불가하다 — [금융위 보도참고](https://www.fsc.go.kr/no010101/81466?srchCtgry=&curPage=1&srchKey=sj&srchText=%EB%B9%84%ED%8A%B8%EC%BD%94%EC%9D%B8&srchBeginDt=2023-12-16&srchEndDt=2024-03-16); [Investing.com(이코노믹리뷰)](https://kr.investing.com/news/stock-market-news/article-989496)
- 디지털자산기본법 진행 상황:
  - 2026-03 정무위 법안소위 안건에서 빠졌다.
  - 2026-07 정부·여당이 연내 통과를 목표로 내걸었다.
  - 2026-10 중순 보도는 "11월 통과?"라고 물으며 처리가 불투명하다고 전했다.
  - 쟁점은 스테이블코인 발행주체(은행 51% 안)와 거래소 지분 제한 등이다.
  - 출처: [데일리안](https://www.dailian.co.kr/news/view/1701457/); [다음 2026-07-18](https://v.daum.net/v/20260718090003105); [디지털데일리 2026-01-28](https://www.ddaily.co.kr/page/view/2026012814522903290); [뉴스토마토](https://newstomato.com/ReadNews.aspx?no=1296017)
- 가상자산 대여(렌딩) 가이드라인(2025-09-05 발표):
  - 레버리지 서비스와 금전성 대여를 제한하고, 담보를 넘는 대여를 금지한다. 제3자 협력·위탁을 통한 간접 대여도 허용하지 않는다(사업자 자체 재산으로 직접 운영할 때만 허용).
  - 신규 이용자는 DAXA 교육과 적격성 테스트를 거쳐야 하고, 대여 한도는 거래 경험에 따라 다르다. 수수료 상한은 연 20%다.
  - DAXA 자율규제로 먼저 시행하고 나중에 법제화를 추진한다.
  - 출처: [블록미디어](https://www.blockmedia.co.kr/archives/976822); [블록미디어](https://www.blockmedia.co.kr/archives/954439); [딜사이트](https://dealsite.co.kr/articles/147042)
- 빗썸은 렌딩 레버리지를 4배에서 2배로 낮췄다. 업비트는 2025-08 당국 제재로 중단했다가 수정 규정에 맞춰 재개했다. 빗썸 대여 서비스는 제3자(블록투리얼)가 운영하는 구조라 가이드라인과 충돌한다는 지적이 있었다 — [딜사이트](https://dealsite.co.kr/articles/147747); [블록미디어](https://www.blockmedia.co.kr/archives/976822)
- 업계 관계자: "국내에서 레버리지나 파생상품을 못한다는 것을 이미 인지하고 있었다" — [블록미디어](https://www.blockmedia.co.kr/archives/976822) [발췌상 귀속 불확실]

### Inferences
- 선물(숏·레버리지) 전략을 국내 합법 상품만으로 실행하는 길은 2026-11 기준 없다.
- 현물 ETF는 법 개정과 상장 절차를 고려하면 빨라야 2027년 이후일 것이다(추론). 나오더라도 현물 롱 전용이라 선물 전략을 대신할 수 없다. 국내 비트코인 선물 시장 도입은 "과제"로 언급될 뿐 일정이 없다.
- 렌딩 서비스는 레버리지가 최대 2배 수준이고, 연 20% 상한까지 비용이 들 수 있으며, DAXA 교육이 필요하다. 그래서 무기한선물을 대신하는 도구로는 부적합하다(추론).

### Gaps
- 국내 거래소의 파생상품 제공을 금지하는 명시적 법조문(가상자산이용자보호법, 금융당국 가이드 등) — 확인하지 못했다.
- 2026년 국내 렌딩 서비스 현황(코인원 "코인 빌리기" 등)과 가이드라인 법제화 여부.
- 디지털자산기본법·자본시장법 개정안의 11월 정기국회 처리 결과(기준일 이후).

---

## 5. 세금 — 가상자산 과세 일정, 해외 거래소 선물 손익, 해외파생상품 양도세, 해외금융계좌·CARF

### Takeaway
1. 가상자산 소득세는 현행법상 2027-01-01 시행(기타소득, 연 250만원 초과분 22%) 예정이었다. 그런데 정부가 **2026-11-05 2년 추가 유예(2029년 시행)와 손실 3년 이월공제 도입을 발표**했다. 국회에서 소득세법을 고쳐야 확정되며, 기준일 현재 미확정이다.
2. 해외 가상자산 거래소의 무기한선물 손익이 "가상자산 양도·대여 소득"에 해당하는지는 불명확하다. 재경부는 관련 과세 방침이 정해지지 않았다고 밝혔다.
3. CME 등 해외 장내파생 손익은 양도소득세 대상이다(탄력세율 10% + 지방세 1% = 11%, 연 250만원 공제, 국내 파생과 손익통산, 다음 해 5월 신고). 다만 기초자산이 가상자산인 CME 비트코인 선물이 여기에 들어가는지는 공식 확인되지 않았다.
4. 해외금융계좌(해외 거래소에 있는 코인 포함) 잔액 합계가 매월 말일 중 하루라도 5억원을 넘으면 다음 해 6월에 신고해야 한다.

### Cited Findings

**가상자산 과세 일정**
- 2020 소득세법 개정으로 근거가 마련됐고, 현행법상 시행일은 2027-01-01이다. 연간 소득 중 250만원을 넘는 금액에 22%(소득세 20% + 지방소득세)를 매긴다. 소득 구분은 기타소득이고, 과세 대상은 가상자산의 양도·대여 소득이다. 취득가액은 2026-12-31 시가를 적용하는 것으로 알려졌다. 첫 신고·납부는 2028-05로 예정돼 있었다 — [이코노미사이언스](https://www.e-science.co.kr/news/articleView.html?idxno=132915); [블로터](https://www.bloter.net/news/articleView.html?idxno=669414); [한국세정신문](https://www.taxtimes.co.kr/news/article.html?no=275357); [도모법률사무소](https://domolaw.co.kr/legal-guide/da1b8c7c-2164-46d0-985e-242b36d855fa) [법률칼럼]
- 2026년 세제개편안(8월)에는 유예안이 들어가지 않았다(2027 유지) — [블로터](https://www.bloter.net/news/articleView.html?idxno=669414); [이코노미스트 2026-07-22](https://economist.co.kr/article/view/ecn202607220024)
- 한동훈 전 대표는 "CARF로 20%도 못 잡는다"며 2년 유예를 요구했고, 정부는 "예정대로"라고 답했다(2026 중) — [위키트리](https://www.wikitree.co.kr/articles/1162864)
- 2026-11-03 여당 재경위가 당 지도부에 과세 유예를 건의했다(2년 연장론) — [대한경제 2026-11-03](https://www.dnews.co.kr/uhtml/view.jsp?idxno=202611031606003150474); [뉴스1](https://www.news1.kr/politics/assembly/6340959)
- **2026-11-05 정부 발표**:
  - 가상자산 과세를 2년 더 유예해 2029년부터 시행한다(4번째 유예).
  - 3년간 생긴 손실을 이익에서 빼주는 이월공제를 추진한다.
  - 기본공제 250만원과 세율은 유지한다. 보도마다 세율 표기가 20%와 22%로 다른데, 지방세 포함 여부 차이로 보인다.
  - 미국과의 CARF 과세정보 교환이 2029년에 시작되는 점을 고려했다.
  - 민관합동 워킹그룹을 꾸려 내년 정기국회에 개정안을 내고, 2028 상반기에 세부 과세기준을 발표한다. 유예는 이번 정기국회에서 손실 이월공제와 함께 처리하도록 추진한다.
  - 출처: [파이낸셜뉴스 2026-11-05](https://www.fnnews.com/news/202611051834343489); [MBC](https://imnews.imbc.com/news/2026/econo/article/6863473_36933.html); [글로벌이코노믹 2026-11-05](https://www.g-enews.com/article/Securities/2026/11/202611051930425062153ddfb15a_1); [YTN 사이언스 2026-11-06](https://m.science.ytn.co.kr/program/view_today.php?s_mcd=0082&key=202611061101305901); [네이트 2026-11-05](https://m.news.nate.com/view/20261105n26285)
- 구체적인 유예 기간과 시행 시점은 국회의 소득세법 개정안 심사에서 정해진다 — [이투데이](https://www.etoday.co.kr/news/view/2642525); [대한경제](https://www.dnews.co.kr/uhtml/view.jsp?idxno=202611031606003150474) **[공식확인 필요: 국회 통과 전]**

**해외 거래소 선물(무기한) 손익의 과세**
- 블로그·세무서비스들은 해외 거래소 손익도 국내와 합산해 신고해야 한다고 설명한다. 선물 손익이 가상자산 양도소득에 포함되는지는 출처마다 엇갈린다("포함" vs "기준이 모호") — [브런치](https://brunch.co.kr/@f4068b5f015d492/79) [블로그]; [CryptoTax](https://cryptotax.cloud/blog/coin-tax/overseas-exchange-tax) [업체]; [Chainlens](https://www.chainlens.app/blog/overseas-exchange-tax) [업체]; [비즈넵 AI](https://ai.bznav.com/contents/355236) [업체]
- 세무사 답변 중에는 "해외 코인 선물 거래는 가상자산을 양도·대여하는 것으로 볼 수 없어 별도로 과세대상이 아닌 것으로 판단된다"는 의견도 있다(개인 의견) — [아하 Q&A](https://www.a-ha.io/questions/495b817b0fd96287ac38e3abc99abc3e) [Q&A]
- 헤럴드경제: "비트코인 연계 무기한선물 과세는 자본시장법상 분류가 먼저…금융위 협의 필요" — [헤럴드경제](https://biz.heraldcorp.com/article/10924994)
- 재경부는 "해외 코인거래소 주식 무기한선물 과세" 보도가 사실이 아니라고 했다(과세 방침 미결정). 원래 보도는 해외 거래소 미국주식 무기한선물 수익에 내년부터 11% 과세 방침이라는 내용이었고, 이후 부인됐다 — [디지털애셋](https://www.digitalasset.works/news/articleView.html?idxno=44012); [이코노미블록](https://economybloc.com/news/121437/) [부인된 보도]

**해외파생상품 양도소득세**
- 국세청: 파생상품 양도소득세의 기본세율은 20%이지만 한시적으로 탄력세율 10%를 적용하며, 대상에 해외 장내파생상품이 포함된다 — [국세청](https://www.nts.go.kr/tax/sub/1.5.4.파생상품에%20대한%20양도소득세%20신고납부%20안내.html)
- KB증권: 해외 파생상품시장에서 거래되는 파생상품 수익은 양도소득세 대상이다. 세율은 11%(지방소득세 포함)이고, 기본공제는 250만원이며, 다음 해 5/1~5/31에 신고·납부한다 — [KB증권](https://m.kbsec.com/go.able?linkcd=s100100020003)
- 국내 파생상품과는 손익을 합산하고 해외주식과는 합산하지 않는다(근거: 소득세법 시행령 167조의9, 159조의2, 지방세법 시행령 100조 12항) — [Glasswallet](https://glasswallet.com/blog/overseas-futures-tax-guide) [블로그]; 2020 정책자료도 국내외 파생 손익을 합산해 250만원을 공제한다고 설명 — [금융세제 선진화 추진방향(2020)](https://www.smallake.kr/wp-content/uploads/2020/06/금융세제-선진화-추진-방향.pdf)
- 소득세법 103조는 주식(2호)과 파생상품(3호)을 별도 호로 나눠 각각 연 250만원을 공제한다 — [Glasswallet](https://glasswallet.com/blog/overseas-futures-tax-guide) [블로그, 법조문 원문 확인 필요]
- 참고로 해외주식 양도소득세는 20% + 지방세 2% = 22%이고, 국내·외 주식을 합쳐 연 250만원을 공제한다 — [TheInfoHunter](https://theinfohunter.com/?p=287) [블로그]; [한국투자증권 홈택스 신고방법 PDF](https://file.koreainvestment.com/updata/namo/2024귀속홈택스신고방법.pdf)

**해외금융계좌 신고**
- 해외금융계좌 잔액 합계가 직전 연도 매월 말일 중 하루라도 5억원을 넘으면 신고해야 한다(연말 잔액 기준이 아님, 계좌 합산).
- 해외 가상자산사업자가 보관하는 코인도 포함된다(2022 보유분, 즉 2023-06 신고분부터). 예: 해외주식 3억원 + 해외 거래소 코인 3억원 = 6억원으로 신고 대상.
- 2026년 신고기한은 2026-06-30이었다.
- 출처: [이투데이](https://www.etoday.co.kr/news/view/2474569); [한국세정신문](https://taxtimes.co.kr/mobile/article.html?no=275388); [Sateconomy](https://sateconomy.co.kr/news/view/1065589847966590)
- 잔액이 변하지 않았어도 해마다 다시 신고해야 한다 — [한국세정신문](https://taxtimes.co.kr/news/article.html?no=275390)
- 미신고·과소신고 시 과태료는 10~20%이고, 50억원을 넘으면 형사처벌까지 가능하다. 스스로 수정신고하거나 기한 후 신고하면 과태료를 최대 90%까지 감경받고 명단공개 대상에서 빠진다 — [BrainDetox](https://braindetox.kr/posts/offshore_investment_reporting_guide.html) [블로그]; [Sateconomy](https://sateconomy.co.kr/news/view/1065589847966590)
- 2026-09: 해외자산 신고액이 100조원을 넘었고, 위반 적발 포상금은 최대 20억원이다 — [머니투데이 2026-09-04](https://www.mt.co.kr/article/2026090415470087684)

**CARF(국가 간 가상자산 거래정보 교환)와 감시 인프라**
- 한국은 2024년 CARF 다자간 협정에 서명했고, 국제조세조정법을 고쳐 자동정보교환 대상에 암호화자산 거래를 넣었으며, 2026-01 이행 규정을 시행했다.
- 첫 교환은 2027년(OECD 일정)이다. 한국 투자자가 많이 쓰는 해외 거래소 소재지인 UAE·세이셸·홍콩·싱가포르는 2028년, 미국은 2029년에 교환이 시작된다. 기재부는 2028년 교환 정보가 2027년 거래를 다루므로 반드시 공백이 생기지는 않는다고 설명했다.
- 출처: [이코노미스트 2026-07-22](https://economist.co.kr/article/view/ecn202607220024)
- 체이널리시스는 CARF 관련 사건이 전 세계 온체인 잠재 과세활동의 약 14%라고 추산했다. DEX 활동과 개인 간 송금은 CARF 범위 밖이다 — [벤처스퀘어](https://www.venturesquare.net/1109793/)
- 국세청은 2027년 과세에 대비해 개인지갑 추적 소프트웨어를 도입한다 — [위키트리](https://www.wikitree.co.kr/articles/1156339)

### Inferences
- 2026년 해외 거래소 무기한선물 손익의 현재 상태(추론): 가상자산 과세가 아직 시작되지 않았고, 해외 거래소는 자본시장법상 "해외 파생상품시장"으로 보기 어렵다. 그래서 현행 소득세법(과세 대상 소득을 법에 열거한 것만 과세)상 과세할 근거가 약해 사실상 비과세일 가능성이 크다. 하지만 공식 해석이 없으므로 거래 기록(손익, 입출금, 수수료)을 모두 보관해야 한다.
- 유예안이 국회를 통과하면 2027~2028년도 같은 상태가 이어진다. 2029년 과세가 시작될 때 무기한선물 손익의 분류(가상자산 소득인지, 파생 소득인지, 과세 제외인지)가 핵심 쟁점이 된다. 3년 손실 이월공제가 도입되면 손실 기록도 가치가 생긴다(추론).
- 해외 거래소 잔액 + 해외주식 등의 합계가 어느 달 말일에라도 5억원을 넘으면 신고해야 한다. 소액으로 시작하는 계획이라면 해당할 가능성이 낮다. 다만 2026-12 개정 외환법(이전 내역을 한국은행에 보고하고 국세청과 공유)으로 적발 가능성은 높아진다.
- CME 비트코인 선물(해외 FCM 경유) 손익은 해외파생 11%로 과세될 가능성이 높다. 하지만 2017 금융위가 "가상화폐는 금융투자상품이 아님"이라고 본 만큼, 자본시장법상 "파생상품"에 해당하는지 논란이 있을 수 있다. 실제로 거래하기 전에 국세청 서면질의나 세무사 확인이 필요하다(추론).

### Gaps
- 국세청·재경부의 유권해석: 무기한선물 손익, CME BTC 선물 손익 — 없음.
- 2026-11-05 정부 유예안의 국회 통과 여부와 최종 시행일(통상 12월 초 처리, 기준일 이후).
- 해외파생 탄력세율 10%의 적용 기한(언제까지 "한시"인지).
- 해외금융계좌 과태료율, 형사처벌 기준의 2026년 현행 국세청 공식 안내 — 블로그·언론 발췌로만 확인했다.

---

## 6. 거래소 상대방 위험(FTX 교훈, 2026-10 바이낸스 해킹)과 바이낸스 BTCUSDT 무기한선물 최소주문·수수료

### Takeaway
2026-10-29~30 바이낸스가 약 63억 달러(약 8.4조원)를 해킹당했다. FBI는 북한 해킹조직 "TraderTraitor"를 배후로 지목했다. 바이낸스는 모든 입출금을 약 56시간 멈췄다가 11/1부터 주요 10개 자산의 출금을 단계적으로 재개했고, 피해의 약 95%를 보전했다고 밝혔다. "거래소 자체가 가장 큰 단일 위험"이라는 FTX의 교훈이 2026년에 다시 확인된 셈이다.

바이낸스 BTCUSDT 무기한선물 조건:
- 최소 주문 명목가는 2026-04-14부터 50 USDT다(이전 100 USDT, 2차 보도 기준).
- VIP0 수수료는 메이커 0.02%, 테이커 0.05%다.
- BNB로 내면 선물 수수료가 10% 할인된다(현물의 25%와 혼동하지 말 것).

### Cited Findings

**바이낸스 해킹(2026-10-29~30)**
- 피해 규모는 약 63억 달러(8.4조원)로 역대 최대 가상자산 해킹이다. 해커는 감염된 직원 노트북으로 내부 시스템에 들어가 출금 승인 시스템을 공격했고, 20분 동안 자산을 빼냈다.
- 거래소는 피해 확산을 막으려 모든 입출금을 일시 중단했다.
- 1단계 출금은 11/1 오전 6~9시(현지)부터 BTC·ETH·USDT 등 주요 10개 자산으로 재개됐다.
- 피해의 약 95%를 보전했고, 나머지 5%는 유동성이 낮은 자산이라 시장에서 확보하는 데 시간이 걸린다.
- FBI는 북한 "TraderTraitor"를 배후로 지목했다.
- 해킹 날짜(29일/30일)와 재개 시점 표기가 보도마다 다르다. 바이낸스는 조사가 끝나면 사고 보고서를 공개하겠다고 했다.
- 출처: [헤럴드경제](https://biz.heraldcorp.com/article/10921806); [재경일보](https://news.jkn.co.kr/post/1059149); [네이트 2026-11-01](https://m.news.nate.com/view/20261101n11831); [네이트 2026-11-01](https://m.news.nate.com/view/20261101n11390)
- 출금 중단부터 1단계 복구까지 약 56시간이 걸렸다 — [TechFlow](https://techflowpost.com/ko-KR/article/35131) [2차]
- 국내 거래소들은 출금 주의 공지와 함께 바이낸스행 출금을 제한할 수 있다고 공지했다(업비트는 자산 동결 요청에 협조). 같은 기사 부제에 따르면 바이낸스는 손실을 전액 보전하고 48시간 안에 출금을 재개하겠다고 했다 — [이투데이 2026-10-30](https://www.etoday.co.kr/news/view/2642406)

**그 밖의 상대방·시장구조 위험 사례**
- 2025-10-10 폭락:
  - 하루 약 190억 달러의 포지션이 청산돼 사상 최대 규모였다. 하이퍼리퀴드에서만 6,300개 넘는 지갑이 청산됐다.
  - 하이퍼리퀴드의 교차마진 ADL(자동 디레버리징)이 2년여 만에 처음 발동됐다. 극단적인 시장 붕괴로 HLP(유동성 풀)의 감당 능력이 바닥났기 때문이다.
  - ADL이 수익을 내던 포지션을 강제로 닫는다는 비판이 나왔다. 창업자는 전체적으로 이롭게 작동했고, 가동률 100%에 부실채권도 없었다고 주장했다.
  - 출처: [Wu Blockchain](https://wublock.substack.com/p/hyperliquid-activates-cross-margin) [2차]; [Sentora](https://sentora.com/research/articles/structural-shifts-in-crypto-the-black-friday-drawdown-and-hyperliquid-s-bid-to-challenge-cexs) [2차]; [Pulse](https://www.pulse.bot/crypto/blogs/hyperliquid-founder-denies-claims-that-dex-prioritizes-revenue-over-traders-bd99ddfd-0369-4282-876a-663219eb721c/) [2차]; [Crypto Briefing](https://cryptobriefing.com/crypto-accountability-market-crash-debate/) [2차]
- 이용자 권고: 보험기금이 미결제약정에 비해 얼마나 큰지 확인하고, ADL이 언제·어떤 순서로 작동하는지 이해하라 — [Wu Blockchain](https://wublock.substack.com/p/hyperliquid-activates-cross-margin) [2차]
- 미신고 사업자를 이용하면 가상자산이용자보호법과 특금법의 보호를 받지 못한다(금융위) — [금융위 게시물 87177](https://www.fsc.go.kr/po010103/87177?curPage=22)

**바이낸스 BTCUSDT 무기한선물 사양**
- 최소 명목가: 바이낸스는 2026-04-14 14:30(UTC+8)부터 BTCUSDT·BTCUSDC USDⓈ-M 무기한선물의 최소 주문 명목가를 100에서 50 USDT/USDC로 낮췄다. 기존 주문에는 영향이 없다 — [Odaily](http://www.odaily.news/en/newsflash/475946) [2차]; [Longbridge](https://longbridge.com/en/news/282143186) [2차]. **[바이낸스 원 공지는 확인하지 못함]**
- 이전 이력: 2023-11 최소 명목가를 5에서 100 USDT로 올렸다. 최신 값은 API `GET /fapi/v1/exchangeInfo`로 확인할 수 있다 — [바이낸스 공지 2023-11-02](https://www.binance.com/en/support/announcement/updates-on-minimum-notional-value-for-btcusdt-and-ethusdt-perpetual-contracts-2023-11-02-e4384cba297a4bd2a154be644d5d76f9); [Binance Futures Trading Rules](https://www.binance.com/en/futures/trading-rules)
- 바이낸스의 일반 계약사양 FAQ는 아직 5 USDT로 적혀 있어 갱신되지 않은 것으로 보인다 — [바이낸스 FAQ](https://www.binance.com/en/support/faq/usd%E2%93%A2-margined-futures-contract-specifications-360033161972)
- 수수료:
  - 일반(VIP0) USDⓈ-M은 메이커 0.02%, 테이커 0.05%다(수수료 = 명목가 × 요율) — [바이낸스 FAQ 360033544231](https://www.binance.com/support/faq/360033544231)
  - "일반 사용자"는 30일 거래량 1,500만 달러 미만이거나 BNB 보유 25개 미만인 사용자다 — [Finder](https://www.finder.com/binance-futures-fees) [2차]
- BNB 할인:
  - 선물 수수료를 BNB로 내면 10% 할인된다. BNB가 USDⓈ-M 선물 지갑에 있어야 하고, 부족하면 USDT로 차감돼 할인이 적용되지 않는다.
  - 일부 2차 가이드가 말하는 25%는 현물 기준이다.
  - 출처: [바이낸스 FAQ](https://www.binance.com/support/faq/360033544231); [바이낸스 선물 수수료 FAQ](https://www.binance.com/en/support/faq/detail/98488a516eb84e3eb34605683dffd554)
- 테이커 프로그램 할인은 BNB 할인과 VIP 요율 위에 추가로 적용된다 — [바이낸스 공지 2025-08-12](https://www.binance.com/support/announcement/detail/bec831262e4b4a49b021e6f4030921be)

### Inferences
- **최소 주문**: 50 USDT는 BTC $73,000 기준 약 0.00068 BTC다. 다만 수량 단위(LOT_SIZE, stepSize) 제약이 따로 있어 실제 최소 주문은 더 클 수 있다. 봇은 실행할 때 `exchangeInfo`의 MIN_NOTIONAL과 LOT_SIZE를 둘 다 읽어야 한다(추론).
- **수수료**: VIP0 왕복 비용은 테이커 0.10%(BNB 0.09%), 메이커 0.04%(BNB 0.036%)다. 1,000 USDT 명목 테이커 왕복이면 약 1.0 USDT(BNB 0.9 USDT)다. 매매가 잦은 전략이라면 메이커 위주로 체결하는 것이 중요하다(추론).
- **상대방 위험 관리 원칙(추론, 2026-10 해킹 사례 기반)**:
  1. 해외 거래소에는 전략에 필요한 증거금과 일정 버퍼만 두고 나머지는 국내에 둔다.
  2. 격리마진과 낮은 레버리지로, 출금이 56시간 이상 멈춰도 증거금을 보충하지 않고 버틸 수 있게 한다.
  3. 수익은 정기적으로 국내로 인출한다.
  4. 거래소 분산은 유효하지만, 트래블룰·화이트리스트 제약 때문에 운영 부담이 커진다.
  5. 국내 거래소가 바이낸스 출금을 제한할 경우를 대비해 귀환 대안 경로(다른 본인 명의 거래소 등)를 미리 확인해 둔다.
  6. DEX(하이퍼리퀴드)는 거래소 파산·해킹 위험 대신 ADL, 스마트컨트랙트, 브리지 위험을 진다.
- 미신고 해외 거래소에서 사고가 나면 국내법상 피해구제 수단이 없다. 그래서 보전 여부는 전적으로 거래소의 자율 결정에 달려 있다(10월 사례에서는 95% 보전 발표).

### Gaps
- **FTX 사례**(2022 파산, 고객자산 유용·혼장 등)의 출처는 검색 한도가 소진돼 수집하지 못했다. 보고서에서 FTX를 쓸 때는 별도 출처가 필요하다.
- 바이낸스 원 공지(2026-04 최소 명목가)와 2026-11 현행 VIP0 수수료·BNB 할인 — 직접 확인하지 못했다. 바이낸스 페이지에 접속할 수 없었다.
- 바이낸스 해킹 공식 사고 보고서, SAFU 기금 사용 여부, 최종 보전 비율, 선물 포지션에 대한 영향(청산·펀딩 등).
- 바이낸스 준비금 증명(PoR) 최신치 — 조사하지 못했다.
- BTCUSDT LOT_SIZE(최소 수량), 최대 레버리지 단계(notional tier) — 조사하지 못했다.
- 바이비트·OKX·비트겟·하이퍼리퀴드의 최소 주문과 수수료 비교 — 조사하지 못했다.
