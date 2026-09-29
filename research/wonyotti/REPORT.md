# 워뇨띠(aoa) 매매 원칙 조사 보고서

작성일: 2026-09-29 · 원자료 메모: `research/wonyotti/raw/`

## 1. 조사 방법과 한계
- WebSearch 28회 (한국어·영어). 요약은 raw/01_search_notes.md
- WebFetch 29회 시도. 성공은 GitHub 5곳뿐 (raw/00_access_log.md)
- 유튜브: yt_api search 5회, details 8개 영상. 자막은 모두 실패(HTTP 400) (raw/03_youtube.md)

| 구분 | 출처 | 상태 |
|---|---|---|
| 직접 열람 | GitHub: twoimo/aoa-bitmex-analysis, JTech-CO/BTC-Legend, wonjun-opensource/wonyotti-trade-book, kwondoyun07/wonyotti-lab, Jeonyomi/Wonyotti | 성공 |
| 직접 열람 | 유튜브 영상 설명과 댓글 | 성공 |
| 검색 요약만 | BitMEX 블로그(인터뷰·AMA), fmkorea, dcinside, coinness, koinquest, threads, theddari, 94bit, coinexpert, donkeypress, bitpunk, tokenpost, 언론(한경, 머니투데이, 블루밍비트 등) | 네트워크 정책으로 차단. 우회하지 않음 |

한계:
1. **A등급 원문을 한 건도 직접 읽지 못했다.** 인용은 모두 검색엔진 요약을 거친 문장이다. 표의 신뢰도는 원래 출처의 등급이고, 실제 확신도는 한 단계 낮춰 읽어야 한다.
2. 검색 요약기가 틀린 곳이 있다. 예: "2021년 600만원으로 시작"이라는 요약이 나왔지만 다른 출처는 모두 2017-12라고 한다.
3. 여러 정리글이 같은 원문(2021-09 디시 Q&A)을 옮긴 것이다. 그래서 "교차" 숫자는 독립 확인 수가 아니라, 검색에서 같은 내용이 보인 출처 수다.
4. 2026-09-22 공개 원장의 원본은 받지 못했다. 제3자 분석 수치만 옮겼다.
5. 개인 신상은 조사하지 않았다.

## 2. 인물 개요 (확인된 사실만)
| 항목 | 내용 | 출처 | 신뢰도 |
|---|---|---|---|
| 활동명 | 디시 "워뇨띠", BitMEX "aoa" | BitMEX 블로그, 언론 | A(요약 경유) |
| 입문 | 2017-12 입문, 2018-03 BitMEX 선물 시작 | https://blog.bitmex.com/whale-trader-talks-aoa/ | A(요약 경유) |
| BitMEX 발표 성과 | "From under $5,000 to ~$300,000,000 in profits" | https://x.com/BitMEX/status/1932749245846859999 | B |
| 원장 성과 | 2018-03~2021-12 한 계정: 실현 3,537.32 XBT, 입금 14.49, 출금 2,814.54, 최종 잔고 737.27 XBT | https://github.com/twoimo/aoa-bitmex-analysis , https://github.com/JTech-CO/BTC-Legend | A 데이터 / C 계산 |
| 랭킹 | BitMEX 선물 총수익 4위 (2024-03 기사) | https://www.blockchaintoday.co.kr/news/articleView.html?idxno=41776 | C |
| 공백과 복귀 | 2021 잠적 → 2025-04 디시 복귀 | https://www.jemin.com/news/articleView.html?idxno=812377 | C |
| 인터뷰 | 2025-06-11 BitMEX Whale Trader Talks 첫 회 | BitMEX 블로그 | A(요약 경유) |
| AMA | 2025-09-17 19~21시 KST, 트롤박스 International 2 | https://blog.bitmex.com/aoa-trollbox-ama/ | A(요약 경유) |
| 원장 공개 | 2026-09-22 디시 차트 마이너 갤러리, 약 140만 행 | https://gall.dcinside.com/mgallery/board/view/?id=chartanalysis&no=5051684 , https://www.mt.co.kr/society/2026/09/23/2026092223334644601 | A(요약 경유) |
| 공식 창구 | 디시와 트롤박스뿐, 그 외는 사칭 | https://namu.wiki/w/%EC%9B%8C%EB%87%A8%EB%9D%A0 | B |
| 방식 | 사람이 직접 주문한 재량 매매, 지정가 위주 | 원장 분석 저장소 | C |

원화 수익(3,700억~4,000억)은 기사마다 달라서 쓰지 않는다.

## 3. 주제별 원칙 (원칙 / 인용 / 출처 / 신뢰도 / 교차)
### 3.1 타임프레임
- 여러 봉을 두루 본다: "3분봉, 30분봉, 3시간봉, 3일봉을 제외한 모든 봉을 참고" / https://www.fmkorea.com/3946325329 , https://94bit.com/47-2/ / B / 3
- 평소엔 "매매하기 편하게 1분봉을 켜둘 뿐" / 위와 같음, https://coinpan.com/free/226243697 / B / 3
- 아주 작은 봉은 "휩쏘가 많기에 신경 쓰지 않으려 한다" / 94bit / B / 2
- 원장상 보유 시간이 점점 길어진다(스캘핑 → 단타 → 스윙). 2021 XBTUSD 보유 중앙값 약 15.4시간 / https://gall.dcinside.com/mgallery/board/view/?id=chartanalysis&no=5051899 , https://github.com/kwondoyun07/wonyotti-lab , https://www.youtube.com/watch?v=exT7Avd6YBc / C / 3
- "큰 봉으로 추세, 1분봉으로 진입"은 해설자의 해석이다. 본인 발언으로 확인되지 않았다.

### 3.2 캔들
- 캔들 형태 + 거래량 위주, 다른 보조지표는 안 쓴다 / https://www.fmkorea.com/7125367168 , coinexpert, trader-ggd 외 / B / 8+
- "캔들은 대부분의 거래소가 일치해서 아직 신뢰도가 있다" / 94bit / B / 2
- "하락 이후 윗꼬리가 늘어섰던 시세까지 시장이 시세를 회복시키는 힘이 있으면 그 뒤에 큰 상승을, 회복시키는 기미가 없다면 큰 하락" / https://www.fmkorea.com/5706109288 , fmkorea 3946325329 / B / 2
- 가장 큰 비밀은 "역사는 반복된다": 현재와 똑같은 과거 캔들 모양을 찾는다 / fmkorea 3946325329, https://www.coinmaster.tips/f1/243473 , dcinside 908514 / B / 5
- 닮은꼴의 우선순위: 가까운 과거일수록 잘 맞는다. 다만 먼 과거라도 모양이 더 정확히 같으면 그쪽을 우선한다 / 위와 같음 / B / 3

### 3.3 거래량
- "거래량만 보거나 캔들만 보기보다는 꼭 병행" / fmkorea 7125367168 외 / B / 5
- "거래량은 신뢰도가 떨어졌지만 큰 거래소의 거래량 패턴이 비슷할 때 참고" / 94bit / B / 2
- 큰 손실 뒤 "충분한 변동성과 거래량이 있다면 즉각 복구 매매, 없다면 생길 때까지 쉰다" / 94bit, coinexpert / B / 4

### 3.4 이평선
- "기본 이평선… 추세를 가늠할 때나 반등 근거를 찾을 때 가끔" / 94bit, coinexpert / B / 3
- 이평선 기간은 어느 출처에도 없다. 블록미디어는 원장으로 RSI·이평선 기반 진입을 설명할 수 있는지 검토했다(결론은 설명란에 없음) / https://www.youtube.com/watch?v=bC3i7s-_WRc / C / 1

### 3.5 추세, 지지, 저항
- "차트에 선을 긋지는 않습니다. 추세, 지지저항 등은 캔들만 봐도 충분히" / https://www.tokenpost.kr/forum/free/293464 , 94bit / B / 4
- "추세선 대신 이평선과 눈대중으로 가늠하며 지지를 주로 본다" / fmkorea 7125367168 / B / 2
- 원장 분석: 역추세는 벌기도 잃기도 했고, 롱숏을 쉬지 않고 바꿨다. 추세 매매 승률이 높다 / https://www.youtube.com/watch?v=hNvnfNKLs3w / C / 2

### 3.6 진입
- 아는 패턴(과거 닮은꼴)일 때만 들어간다 / 3.2 / B / 5
- 지정가로 미리 걸어 둔다. maker 비율은 67.16%(체결 수 기준)와 85.6% 두 주장이 있다 / twoimo, wonyotti-trade-book, wonyotti-lab / C / 3
- 나눠서 들어간다: 원장상 진입 주문 중앙값 5회, 최대 포지션은 첫 진입의 약 4배. 본인은 "10분할"이었다가 이후 "3분할"이라고 했다 / dcinside 5051899, 94bit / B·C / 3
- "지지선에서 물을 타야… 확실하지 않은 곳에서 물을 타서 비중만 커지는 경우를 주의" / 94bit, dcinside 3149397 / B / 2
- "Risk management is the skill you want to acquire, not getting the entry point right" / https://www.bitmex.com/blog/aoa-trollbox-ama , https://en.bloomingbit.io/feed/news/90214 / A(요약 경유) / 3

### 3.7 손절
- "시나리오에서 어긋나거나 멘탈이 지나치게 흔들리기 시작하면 손절". 현재 흐름이 아는 과거 모양과 완전히 달라지면 손절 / 94bit, fmkorea 3946325329 / B / 4
- AMA(2025): "-20%가 강제 손절 타이밍". 거래소 자산의 20%이며, 그 이상이면 복구가 어렵다 / https://www.hankyung.com/article/202509183671O , https://bloomingbit.io/en/feed/news/97220 / A(요약 경유) / 3
- 1회 최대 허용 손실: "시드가 적을 땐 1회 -20%, 요즘은 -10% 정도" / fmkorea 3946325329, https://theddari.com/en/trends/telegram/1446671164/40969 / B / 2
- "max loss is never more than 30% of his capital" / BitMEX 인터뷰 / A(요약 경유) / 4
- "시세 기준 3%까지는 버티다 5%쯤 되면 손절" / 원출처 미특정 / C / 1
- 항상 격리 마진. 청산돼도 대부분 시드의 20~30%만 잃었다 / https://m.cafe.daum.net/dotax/Elgq/4711585 , 94bit / B / 3
- 원장상 손실 포지션 보유 중앙값(약 21.9시간)이 이익 포지션(약 15.5시간)보다 길다. 즉 기계적으로 바로 자르는 방식은 아니었다 / dcinside 5051899 / C

### 3.8 익절
- "아는 구간 끝나면 익절합니다" / https://www.fmkorea.com/3944021692 , https://gall.dcinside.com/mgallery/board/view/?id=chartanalysis&no=809348 , theddari / B / 5
- 보통 시드의 5%면 만족하고 익절. 하루 최대 20%, 하루 30%는 번 적이 없다 / fmkorea 3946325329, coinexpert / B / 4
- 1회 익절 폭: 과거 0.5~1%, 최근 평균 3% / theddari / B·C / 2
- 승률을 중시한다. "큰 손익비를 원하면 요행을 기대하게 된다" / fmkorea 3946325329 / B / 2

### 3.9 레버리지와 비중
- "a maximum of 1.5 to 2x leverage when looking at his whole portfolio" / BitMEX 인터뷰 / A(요약 경유) / 4
- 자산이 커질수록 배율을 낮춘다: 3천만원 시절 시드 25%로 25배 → 풀시드 10분할 10~15배 → 현재 3분할 3배 / 94bit, tokenpost 포럼 / B / 3
- 2018년 초중반: 시드의 1/5을 10배 격리 / 다음카페 dotax 4711585 / B / 1
- "never go all in", 잃어도 괜찮은 비중으로 / BitMEX AMA, fmkorea 7125367168 / A·B / 4
- 애매할 땐 시드의 40%를 BTC로 보유(FOMO·FUD 방지). 상승장에서도 최소 30%는 BTC / dotax 4711585, dcinside 3149397 / B / 2

### 3.10 복리와 자금관리
- 수익을 꾸준히 은행으로 출금 / fmkorea 7125367168 / B / 2
- 원장상 출금 2,814.54 / 실현 3,537.32 ≈ 80% (블록미디어는 82%) / twoimo, 블록미디어 / A 데이터 / 3
- 복구용 자산은 남기고 추가 입금은 지양 / 94bit / B / 2. 원장상 입금은 총 14.49 XBT뿐이다
- "90% 확률로 2배 수익이라도 10%로 0원이 될 수 있으면 피한다" / https://www.threads.com/@coin.gallery02/post/DOtI355kxfK , theddari / B / 2

### 3.11 심리
- "the key to his success was to keep having doubts about the market". BTC·ETH가 10분의 1, 20분의 1로 떨어질 수 있다 / BitMEX 인터뷰 / A(요약 경유) / 4
- Rule #1: "not fall in love with a specific position" / BitMEX 인터뷰, https://www.coinreaders.com/165878 / A(요약 경유) / 4
- 큰 손실 뒤엔 조건이 되면 복구, 아니면 휴식. 자산 계산을 미뤄 현실을 받아들일 시간을 둔다 / 94bit, coinexpert / B / 4
- 모의투자보다 리스크를 관리한 실전 경험 / https://koinquest.com/honey_tip/12418 / B / 3
- 시스템 없이 운만 좋은 사람은 망한다(트롤박스) / 한경 / B / 2

### 3.12 시장관
- 알트는 참여자가 적어 차트 신뢰성이 떨어진다 → BTC 중심 / dcinside 3149397, https://coinness.com/community/lounge/229103 / B / 3
- 알트는 BTC와 같이 움직이는 시총 상위만 / B / 2
- 원장: XBTUSD가 실현 손익의 약 56.7%, 후기로 갈수록 알트 기여가 커진다 / BTC-Legend / C / 1
- 2021년 이후 크립토가 "미국 주식시장처럼" 거시 이슈를 따른다 / BitMEX 인터뷰 / A(요약 경유) / 2

### 3.13 이력
2017-12 입문 → 2018-03 BitMEX 시작(원장상 첫 이벤트 2018-03-05) → 2018-09-21 XRP 청산으로 시드 50% 손실(94bit, B) → 2020-03 코로나 폭락 날 +276 BTC / 2021 하루 -282 BTC(블록미디어, C) → 2021-09-27경 디시 Q&A → 2021-12 원장 끝(XBTUSD 숏 미청산) → 2025-04 복귀 → 2025-06-11 인터뷰 → 2025-09-17 AMA → 2026-09-22 원장 공개

## 4. 시그널 봇 규칙 후보 (◎ 코드화 가능 / ○ 근사 가능 / × 재량 판단)
### 리스크와 자금관리 (근거가 가장 강함)
- R1 전체 자산 대비 명목 노출 > 2배 → 신규 진입 금지 (A) ◎
- R2 계좌 평가손실 ≤ -20% → 전 포지션 청산, 매매 중지 (A) ◎
- R3 단일 포지션 손실이 계좌의 -10%에 닿음 → 손절 (B) ◎
- R4 누적 최대 손실 한도 30%. R2가 먼저 작동하게 설계 (A) ◎
- R5 격리 마진. 한 포지션 증거금 ≤ 계좌의 20~25% (B) ◎
- R6 자산 구간별로 최대 레버리지를 단계적으로 낮춤 (B, 공식 자체는 발언 아님) ○
- R7 1회 익절 목표 계좌 +3~5%. 일 수익 +20%에 닿으면 당일 신규 진입 중지 (B) ◎
- R8 실현 이익의 일정 비율을 출금하라는 알림 (원장 약 80%) ◎
- R9 큰 손실 뒤 변동성·거래량이 기준 이상이면 재개, 아니면 쿨다운 (B) ○
- R10 파산 확률이 있는 사이징은 거절 (예: 청산가까지 거리 < N×ATR) (B) ○

### 필터
- F1 거래량(여러 거래소 교차 확인)과 변동성이 기준 미만 → 신호 억제 ○
- F2 1분봉만의 신호는 무시하고 5분봉 이상에서 확인 ○
- F3 타임프레임: 1m/5m/15m/1h/4h/1d (3m·30m·3h·3d 제외) ◎
- F4 알트는 BTC 상관계수가 높고 시총 상위일 때만 ◎

### 진입과 청산 (근거가 약함)
- S1 과거 닮은꼴: 최근 N개 봉의 OHLCV 모양을 과거와 비교(DTW, 코사인 유사도 등)해 상위 k개의 이후 수익률 분포로 방향을 정함. 최근 구간에 가중치, 단 유사도가 더 높으면 먼 과거 우선 ○ (본인 방식의 근사일 뿐)
- S2 윗꼬리 회복: 윗꼬리가 몰린 가격대를 거래량과 함께 되찾으면 롱, 못 되찾으면 숏 ○
- S3 이평선이나 스윙 저점 같은 지지 근처에서 지정가로 3~5회 분할 매수 ○
- S4 물타기는 지지에서만 ○
- S5 닮은꼴 구간이 끝나면 익절. 유사도가 임계 아래로 떨어지면 손절 ○
- S6 기본 주문은 지정가(post-only) ◎
- S7 "시나리오 붕괴", "멘탈 흔들림" 손절 ×
- S8 "아는 구간"인지 판단 ×

### 주의
- 원장 공개자는 원장으로 만든 봇이나 2차 제작물의 유료 판매를 삼가 달라고 요청했다 (https://github.com/kwondoyun07/wonyotti-lab). 상업화한다면 이 요청을 따라야 한다.
- 제3자 백테스트에서 원장에서 뽑은 진입 신호만으로는 2024~25년에 손실이 났다 (코린이유치원, 블록미디어). 재현할 핵심은 신호보다 R1~R10이다.

## 5. 오해·과장 주의
- "보유 중앙값 8.27초 초단타": 체결 단위와 포지션 단위를 섞은 오류로 보인다. 포지션 기준은 약 15시간 (https://www.youtube.com/watch?v=exT7Avd6YBc)
- wonyotti-trade-book의 실현 1,897 BTC, maker 85.6%, 1,444,583건: 다른 두 저장소(3,537 BTC, 67.16%, 1,439,207건)와 맞지 않는다. "L ≤ min(10, C/√Equity)"는 저자의 모델이다
- "항상 3배 이하": 시기에 따라 다르다(25배, 10~15배를 쓴 시기도 있음). 1.5~2배는 포트폴리오 전체 기준이다. 댓글의 "77배", "150배"는 맥락을 알 수 없다
- 손절 기준 -20%(계좌 강제) / -10%(1회) / 30%(누적 최대) / 가격 3~5%(출처 미특정)는 기준이 서로 다르다. 섞으면 안 된다
- "하루 2번 손절이면 중지", "시작 마진 200% 도달 시 50% 출금": 따라하기 블로그의 규칙으로 보인다 (D)
- "1분봉으로 매매한다": 켜 둘 뿐이다. 원장상 보유는 수 시간에서 수십 시간이다
- 원화 수익 수치는 기사마다 다른 추정치다. "500억 청산"은 글쓴이 스스로 루머라고 했다 (https://www.clien.net/service/board/cm_vcoin/16758247)
- 유튜브 채널 "워뇨띠"(텔레그램 홍보)와 텔레그램 @aoafan은 사칭이거나 팬 채널이다. "거래내역 유출"이라는 영상 제목은 사실과 다르다(본인이 공개)
- 요약기 오류 "2021년 시작" → 실제는 2017-12

## 6. 참고문헌
A(요약 경유): https://blog.bitmex.com/whale-trader-talks-aoa/ · https://www.bitmex.com/blog/aoa-trollbox-ama · https://blog.bitmex.com/aoa-trollbox-ama/ · https://gall.dcinside.com/mgallery/board/view/?id=chartanalysis&no=5051684 · https://gall.dcinside.com/mgallery/board/view/?id=chartanalysis&no=5050579

B: https://www.fmkorea.com/3946325329 · https://www.fmkorea.com/3946308771 · https://www.fmkorea.com/3944021692 · https://www.fmkorea.com/5706109288 · https://www.fmkorea.com/7125367168 · https://www.fmkorea.com/8508959799 · https://www.fmkorea.com/8713864851 · https://www.fmkorea.com/8142717319 · https://coinness.com/community/lounge/229103 · https://koinquest.com/honey_tip/12418 · https://www.threads.com/@coin.gallery02/post/DOtI355kxfK · dcinside chartanalysis 957259/957263/959039/809348/3943782/908514/3149397/2321834 · https://94bit.com/47-2/ · https://m.cafe.daum.net/dotax/Elgq/4711585 · https://m.cafe.daum.net/dotax/Elgq/4589545 · https://www.coinmaster.tips/f1/243473 · https://namu.wiki/w/%EC%9B%8C%EB%87%A8%EB%9D%A0 · https://x.com/BitMEX/status/1932749245846859999

C: https://github.com/twoimo/aoa-bitmex-analysis · https://github.com/JTech-CO/BTC-Legend · https://github.com/kwondoyun07/wonyotti-lab · https://github.com/wonjun-opensource/wonyotti-trade-book · https://github.com/Jeonyomi/Wonyotti · dcinside 5051899/5052052/5052178/5052698/5050720, dcbest 465253/465260 · YouTube bC3i7s-_WRc, exT7Avd6YBc, hNvnfNKLs3w, jXYPDGgMgNo, nIP2NAPBtR8, J-7tPXNz30A, EpstKF3qVmQ · https://theddari.com/en/trends/telegram/1446671164/40969 · bitpunk.one · coinexpert.co.kr · https://donkeypress.com/nyotti/ · https://www.tokenpost.kr/forum/free/293464 · trader-ggd.com · https://www.hankyung.com/article/202509183671O · https://en.bloomingbit.io/feed/news/90214 · https://bloomingbit.io/en/feed/news/97220 · https://www.mt.co.kr/society/2026/09/23/2026092223334644601 · https://www.mt.co.kr/stock/2025/10/30/2025103011490322038 · https://www.jemin.com/news/articleView.html?idxno=812377 · https://www.coinreaders.com/165878 · https://www.blockchaintoday.co.kr/news/articleView.html?idxno=41776 · https://x.com/fulllleverage/status/1932731144627470656

D: coinbibleinvest.com 16138892 · mathnet.or.kr "워뇨띠 매매법 2탄" · https://www.clien.net/service/board/cm_vcoin/16758247 · 유튜브 "워뇨띠" 채널(t7K31n1PREg 등) · https://tgstat.com/channel/@aoafan

## 후속 과제
1. 원장 원본을 받아 직접 계산한다(포지션 보유 시간, 손실 분포, 레버리지, 진입 직전 OHLCV). 이 값으로 R6·S1~S3 파라미터를 정한다.
2. BitMEX 인터뷰·AMA 원문을 사람이 열어 인용을 대조한다.
