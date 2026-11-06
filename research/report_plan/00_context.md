# 팀 공통 배경 (모든 에이전트가 먼저 읽을 것)

## 사용자와 요청 (2026-11-06, 사용자 원문 요약)
- 사용자: 한국인, 정보보호 종사자, 코딩 초보. 설명은 한국어·쉬운 말.
- 요청 원문(번호 그대로):
  1. PDF에 차트 한 개로, 롱인지 숏인지, 레버리지는 얼마로 해야 하는지 등을 알려 주면 좋겠다.
  2. 분석은 ① Claude가 전문가 입장에서 한 차트 분석 ② 워뇨띠 관점 ③ 차트프로 관점, 이 세 가지를 차트에 담아 달라.
  3. 텔레그램으로 1시간에 한 번씩 보내 달라.
  4. 전문가 입장에서 깊게 생각해 보고 위 조건을 수정해도 된다. 최적의 조건으로 판단해서 기획해 달라.
  5. Claude API와 GLM API가 있다. (Claude API 예산은 월 300달러라고 전에 말함)
  6. 주문은 사용자가 바이낸스에서 직접 한다. (시스템은 주문하지 않는다 → 거래소 API 키 불필요)
  7. 돈을 벌고 싶다.
  8. 일단 5만 원으로 테스트하고 점점 불려 나갈 것이다.
  9. 기술적으로 깊게 판단해 달라.

## 지금까지의 사실·결정
- 대상: 바이낸스 USDⓈ-M BTCUSDT 무기한 선물(24시간, 롱·숏, 펀딩비 8시간마다).
- 저장소: /home/user/1111 (공개 저장소). 지침: /home/user/1111/CLAUDE.md
  - 구독 앱 자동화 금지(Claude는 API 키로만). 비밀(키·토큰·ID)은 파일에서만 읽고 커밋·로그 금지. 환경 변수에 비밀 두지 않음. LIVE(실거래) 모드 금지. 테스트: `.venv/bin/python -m pytest bot -q -m "not slow"`.
- 기존 시스템(docs/STATUS.md 참고): 추세 돌파 전략 E0-L-ENS(롱 전용, N일 고점 돌파) 백테스트에서 우위 없음(G1 판정 불가, G1-T 0/8). 모의 매매 봇·주문 연결부(가짜 거래소)만 있음, 실제 운용 0시간.
- 기준서(분석 근거 규칙집): /home/user/1111/bot/prompts/playbook_chartpro.md (차트프로 v0.2, 25개념 177규칙 [CP-NN-n]), /home/user/1111/bot/prompts/playbook_wonyotti.md (워뇨띠 v0.2, 15개념 42규칙 [WY-NN-n]). 두 파일 합계 약 100KB(한국어).
  - 기준서 시험: 교재 복습 91문항 기준 약 82% 답함.
- 세 관점 브리핑 프로토타입: /home/user/1111/research/briefing_proto/
  - facts.py(기준봉·마디·허리·거래량 배수·이평 비교봉·닮은꼴 검색), render.py(차트 위 번호 표시 그림), sample_0929.json(번호 표시 목록 예시), brief_0929.md(2026-09-29 09:00 KST 기준 세 관점 설명 예시), wy_similarity_check.py.
  - 닮은꼴 검색(워뇨띠 '역사는 반복' 원칙의 우리 구현) 과거 2년 점검: '모임' 판정 17%, 그날들의 10일 뒤 방향 적중 47%(같은 기간 아무 날 10일 뒤 상승 비율 53%) → 우위 없음.
- 코드 자산(재사용 후보): bot/marketdata.py(LiveBinance: 공개 fapi klines 1d·1m, fundingRate, time — 키 없음), bot/analyst.py(Anthropic 클라이언트: 키는 파일 Secret, 시간 제한, stop_reason 처리, 비용 계산, 스키마 검사), bot/telegram_ui.py(PtbTransport: python-telegram-bot 22.8, 허용 채팅에만 글·버튼 전송, 사진 전송은 아직 없음), bot/config.py(설정 검사, 비밀 파일 경로, check_env_no_secrets), bot/db.py(sqlite), backtest/structure.py·indicators.py(스윙·기준봉·마디·허리·살아 있는 마디), backtest/data.py.
- 로컬 데이터: /home/user/1111/data/binance/ — BTCUSDT_1m_2023~2026, 5m, 15m, 1h, 4h, 1d (.csv.gz, 열: open_time(ms), open, high, low, close, volume, close_time, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore), 2020-01-01 ~ 2026-09-28. fundingRate(~2026-08-31, 열 calc_time, funding_interval_hours, last_funding_rate), metrics(2021-12 ~ 2026-09-28, 5분 간격: sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio).
  - .venv 파이썬: /home/user/1111/.venv/bin/python (pandas, numpy, matplotlib 있음).
- 이 작업 컨테이너 네트워크: 바이낸스·텔레그램 접속 불가, api.anthropic.com 접속 가능(키 없음), PyPI·raw.githubusercontent.com 가능, 웹 검색 가능. 실제 운영은 사용자 맥(또는 서버)에서.
- 확인된 외부 사실(2026-11 검색):
  - 바이낸스 BTCUSDT 최소 주문 금액 100 USDT(2023-11-02 공지, 바뀔 수 있음 — 실제 값은 GET /fapi/v1/exchangeInfo로 확인).
  - 국내 미신고 해외 거래소는 2021년 접속 차단·원화 출금 막힘 사례가 있음. 개인 이용자 처벌·현재 차단 여부는 미확인(사용자가 확인할 몫).
- Claude 가격(내부 자료, 단위 $/백만 토큰): Opus 5.5 입력 4 / 출력 20, Sonnet 5.5 2/10, Haiku 5.5 0.10/0.50(확인 필요), 캐시 읽기 Opus 0.20. 정확한 값·캐시 배수는 /tmp/claude-0/bundled-skills/2.1.318/81ebea726effba69323665e5fbbad5c0/claude-api/ 안의 문서를 확인할 것. 모델 ID: claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5. Claude 학습 데이터는 2026년 중반까지라 그 이전 비트코인 가격을 기억할 수 있음(과거 시험 오염 주의).
- 사용자 계좌: 5만 원 ≈ 35~36 USDT(환율 1,400원 가정).

## 산출 규칙
- 저장소 파일은 고치지 않는다(읽기만). 커밋·푸시 금지. 결과와 스크립트는 지정된 scratchpad/team/ 아래에만.
- 비밀 값은 다루지 않는다.
- 결과 문서는 한국어, 쉬운 말, 숫자에는 근거(계산·출처·가정)를 붙인다. 추정은 추정이라고 쓴다.
- 결론을 먼저 쓰고, 사용자 요청을 그대로 따르는 게 나쁘면 이유와 대안을 분명히 쓴다(요청 4번이 허락함).
- 끝나면 10~20줄 요약만 보고한다(상세는 파일에).

## 퀀트 공통 가정 (퀀트 담당끼리 맞출 것)
- 비용: 테이커 0.05%/편, 메이커 0.02%/편(VIP0 기준, 웹에서 확인되면 갱신), 시장가 슬리피지 0.02%/편. 펀딩은 로컬 실제 값(~2026-08-31), 그 뒤는 0.01%/8시간 가정.
- 계좌: 35.7 USDT로 시작. BTCUSDT 최소 주문 100 USDT, 수량 단위 0.001 BTC(확인 필요) → 가격이 10만 달러 미만이면 실제 최소 수량이 0.002 BTC(약 167 USDT)일 수 있음. 이 점을 꼭 확인할 것.
- 표본: 학습(IS) 2020-01~2023-12, 검증(OOS) 2024-01~2026-09-28. 변수 조합은 많이 시험하지 말고(설정당 최대 3~4개 변형), 시험한 것은 전부 보고한다(좋은 것만 고르지 말 것).
- 성과 단위: R(진입~손절 거리) 기준 기대값, 승률, 평균 손익비, 최대 낙폭(R), 거래 수, 평균 보유 시간. 원화 환산은 퀀트① 사이징 규칙으로.
- 미래 정보 금지: 확정된 봉만 쓴다. 스윙(앞뒤 3봉)은 확정되는 봉(i+3) 마감 뒤에만 쓴다. 시각 표시는 KST.
- 결과가 나쁘면 나쁘다고 쓴다. "우위 없음"도 중요한 결과다.

## 정정 (팀 결과 반영, 총괄)
- 바이낸스가 2026-04-14부터 BTCUSDT·BTCUSDC 최소 주문 금액을 100→50 USDT로 낮춤(퀀트① 확인, 맥에서 exchangeInfo로 재확인 필요). 지금 가격에서 최소 수량 0.001 BTC(약 83.5 USDT = 계좌의 2.3배).
