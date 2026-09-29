# 접근 로그 (2026-09-29)

## WebFetch 결과
| URL | 결과 |
|---|---|
| https://blog.bitmex.com/whale-trader-talks-aoa/ | EGRESS_BLOCKED |
| https://www.bitmex.com/blog/aoa-trollbox-ama | EGRESS_BLOCKED |
| https://koinquest.com/honey_tip/12418 | EGRESS_BLOCKED |
| https://theddari.com/en/trends/telegram/1446671164/40969 | EGRESS_BLOCKED |
| https://www.threads.com/@coin.gallery02/post/DOtI355kxfK | EGRESS_BLOCKED |
| https://94bit.com/47-2/ | DNS 실패 (EAI_AGAIN) |
| https://coinexpert.co.kr/... | EGRESS_BLOCKED |
| https://donkeypress.com/nyotti/ | EGRESS_BLOCKED |
| https://www.bitpunk.one/entry/... | EGRESS_BLOCKED |
| https://www.tokenpost.kr/forum/free/293464 | EGRESS_BLOCKED |
| https://www.hankyung.com/article/202509183671O | EGRESS_BLOCKED |
| https://kr.tradingview.com/news/bloomingbit:29022756a65a7:0/ | EGRESS_BLOCKED |
| https://en.bloomingbit.io/feed/news/90214 | EGRESS_BLOCKED |
| https://bloomingbit.io/en/feed/news/97220 | EGRESS_BLOCKED |
| https://www.coinreaders.com/165878 | EGRESS_BLOCKED |
| https://www.jemin.com/news/articleView.html?idxno=812377 | EGRESS_BLOCKED |
| https://mathnet.or.kr/워뇨띠-매매법-2탄/ | EGRESS_BLOCKED |
| https://coinbibleinvest.com/blog/?bmode=view&idx=16138892 | EGRESS_BLOCKED |
| https://v.daum.net/v/20250616112735011 | EGRESS_BLOCKED |
| https://www.blockchaintoday.co.kr/news/articleView.html?idxno=41776 | EGRESS_BLOCKED |
| https://coinfor.co.kr/... (fmkorea Q&A 미러) | DNS 실패 |
| https://www.mt.co.kr/society/2026/09/23/2026092223334644601 | EGRESS_BLOCKED |
| https://wonyotti.coinduck.store | EGRESS_BLOCKED |
| https://github.com/yeodongwon519/wonyotti-trades | 404 (삭제/비공개) |
| https://github.com/twoimo/aoa-bitmex-analysis | 성공 |
| https://github.com/JTech-CO/BTC-Legend | 성공 (2회) |
| https://github.com/wonjun-opensource/wonyotti-trade-book | 성공 |
| https://github.com/Jeonyomi/Wonyotti | 성공 (데이터 없음, 체크리스트만) |
| https://github.com/kwondoyun07/wonyotti-lab | 성공 |

지시에 따라 fmkorea / dcinside / coinness / namu.wiki / naver 등은 시도하지 않았고, 차단 도메인 우회도 하지 않았다.
프록시 상태 확인(curl) 시도는 권한 분류기에 의해 거부되어 중단했다.

## 유튜브 (research/tools/yt_api.py)
- search: 5개 검색어 → yt_search_*.json
- details: 8개 영상 → yt_details_*.json
- transcript: 8개 모두 실패(HTTP 400) → 파일 삭제
