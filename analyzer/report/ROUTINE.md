# 예약작업 순서서 (클라우드에서 보고서 보내기)

Claude 예약작업이 회차마다 이 순서대로 한다. 주문은 하지 않는다. 읽고, 계산하고, 보고서를 보내기만 한다.

## 필요한 것(환경 설정에 미리)

- 환경 변수: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (저장소에 적지 않는다)
- 허용 주소: `www.okx.com`, `api.telegram.org`

## 순서

1. 부품 받기
   ```
   cd analyzer/report
   npm ci --omit=dev --ignore-scripts
   ```
2. 시세 받기(클라우드는 프록시를 거치므로 앞에 붙인다)
   ```
   NODE_USE_ENV_PROXY=1 node run.cjs fetch
   ```
   실패하면 여기서 멈추고, 실패 이유만 적는다. 보내지 않는다.
3. `latest.json`을 읽고 `page_a.json`을 쓴다. 모양은 `page_a.example.json`을 따른다.
   - `scalp`: 여러 타임프레임을 겹쳐 본 단타 관점 한 단락. 끝에 "검증 안 된 의견"이라고 밝힌다.
   - `tf`의 6개(5m, 15m, 30m, 1H, 4H, 1D)마다 `call`(상승·하락·관망), `note`, `marks` 3~4개.
   - `marks`의 `ago`·`price`는 `latest.json`의 `mtf[].chart.bars`에서 실제 봉을 보고 정한다(ago 0 = 마지막 봉).
   - `label`: 차트 위 상자에 들어갈 짧은 글(60자 안).
   - `text`: 차트 분석 초보가 읽는다고 생각하고, 무엇인지 → 왜 중요한지 → 다음에 볼 것 순서로 쉽게(400자 안). 용어(저항, 지지, 쌍바닥 등)는 처음 나올 때 풀어 쓴다.
   - 검증된 신호는 4시간봉 유형 B 하나뿐이다. 유형 A에서 "오른다/내린다"를 확정처럼 쓰지 않는다. 근거가 약하면 `관망`.
   - 판정 기준값(0.4217, 0.0857, 1.39%, 2.14%)은 바꾸지 않는다.
4. 보내기
   ```
   NODE_USE_ENV_PROXY=1 node run.cjs send
   ```
5. 커밋하지 않는다. `latest.json`, `page_a.json`, `report.pdf`는 저장소에 올리지 않는 파일이다.
