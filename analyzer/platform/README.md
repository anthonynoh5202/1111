# 차트분석기 자동 분석 플랫폼

4시간봉이 마감될 때마다 바이낸스 선물 공개 시세에서 봉을 읽어 고정된 기준으로 판정하고, 기록과 대시보드를 남긴다.
읽기 전용이다. **주문 기능이 없다.**

```
4시간봉 마감 + 90초
      │
      ▼
바이낸스 선물 공개 시세 (BTCUSDT 4시간봉 1,500개, 키 필요 없음)
      │
      ▼
고정 기준 판정 (analyzer/src/core.js, analyzer/src/judge.cjs)
      │
      ├──────────────────────┬──────────────────────┐
      ▼                      ▼                      ▼
Claude 해설(선택, API)   기록 runs.jsonl      대시보드 127.0.0.1:8787
```

- 판정(방향·크기·신호)은 계산이 낸다. Claude는 그 결과를 풀어 설명할 뿐 판정을 바꾸지 않는다.
- 하루 6번(한국 시간 1·5·9·13·17·21시 직후) 돈다. 대시보드의 "지금 분석"으로 직접 돌릴 수도 있다.

## 켜기

1. 부품을 받는다(한 번만). 설치 중 스크립트 실행은 끈다.
   ```
   cd analyzer/platform
   npm ci --omit=dev --ignore-scripts
   ```
2. 저장소 폴더에서 플랫폼을 켠다.
   ```
   node analyzer/platform/server.cjs
   ```
3. 브라우저에서 `http://127.0.0.1:8787` 을 연다.

끄려면 터미널에서 Ctrl+C. 컴퓨터가 잠들면 그 사이의 회차는 건너뛴다(깨어나면 다음 회차부터 이어 간다).

한 번만 분석하고 끝내려면: `node analyzer/platform/server.cjs --once`

## 설정

`analyzer/platform/config.example.json`을 `config.json`으로 복사해서 고친다. 없으면 기본값으로 돈다.

| 항목 | 기본값 | 뜻 |
|---|---|---|
| `delaySeconds` | `90` | 봉 마감 뒤 기다리는 시간(초) |
| `commentary.enabled` | `false` | Claude 해설을 켤지 |
| `commentary.model` | `claude-opus-5-5` | 해설에 쓸 모델 |
| `commentary.effort` | `medium` | 생각하는 깊이(`low`~`max`). 높을수록 느리고 비싸다 |
| `port` | `8787` | 대시보드 포트 |

## Claude 해설 켜기

1. Anthropic 콘솔(platform.claude.com)에서 API 키를 만든다. 구독(앱)과는 별개이고, 쓴 만큼 요금이 나온다.
2. 키를 환경 변수로 넣고 플랫폼을 켠다. 키를 파일에 적거나 저장소에 올리지 않는다.
   - 맥: `export ANTHROPIC_API_KEY=...` 뒤에 `node analyzer/platform/server.cjs`
   - 윈도우(PowerShell): `$env:ANTHROPIC_API_KEY="..."` 뒤에 `node analyzer\platform\server.cjs`
3. `config.json`에서 `commentary.enabled`를 `true`로 바꾼다.

- 구독 앱(Claude Code, 앱 화면)을 자동으로 조작하는 방식은 쓰지 않는다. API로만 부른다.
- 회차마다 한 번 부른다. 실제 요금은 대시보드의 토큰 수로 확인한다(해설 아래에 입력·출력 토큰이 나온다).
- Claude가 안전상 이유로 답을 거절하면 서버가 대체 모델로 다시 돌리도록 켜 두었다(`fallbacks: "default"`).
- 키가 없거나 틀리면 판정과 기록은 그대로 남고, 해설 자리에 이유가 나온다.

## 기록

`analyzer/platform/data/`에 남는다(저장소에는 올라가지 않는다).

- `runs.jsonl` — 회차마다 한 줄. 성공·실패, 쓴 자료, 판정, 해설.
- `chart.html` — 가장 최근 자료로 그린 분석기 화면.
- `closes.json` — 지난 신호의 16시간 뒤 결과를 채우는 데 쓰는 최근 종가.

대시보드의 기록 표는 마감 봉마다 하나씩 보여 준다. ★은 밤 9시 마감 봉(5만 원 테스트 대상)이다.
롱 신호가 진짜인지는 이 기록이 1년쯤 쌓여야 가릴 수 있다. 플랫폼을 꺼 둔 시간의 봉은 기록되지 않는다.

## 안전

| 위험 | 해 둔 것 |
|---|---|
| 자동으로 주문이 나갈 수 있나 | 없다. 주문 코드가 없고, 거래소 키를 받지 않는다 |
| 대시보드를 남이 열거나 조작 | 이 컴퓨터(127.0.0.1)에서만 열린다. 다른 이름으로 온 요청과 토큰 없는 실행 요청을 거부한다 |
| 자료 글자·Claude 답에 섞인 코드 | 화면에 글자로만 넣는다. 외부 스크립트를 막는 정책(CSP)을 걸었다 |

## 한계

- 실제 바이낸스, 실제 Anthropic API에 연결해서는 시험하지 못했다. 가짜 서비스로 한 회차 전체를 돌리는 시험만 통과했다.
- 바이낸스 선물 시세(`fapi.binance.com`)는 한국 PC에서 읽는다. 클라우드에서는 위치 차단으로 안 된다.
- 알림(텔레그램 등)은 아직 없다. 대시보드를 열어 봐야 한다.
- 판정 기준의 한계는 그대로다. 방향을 맞히는 검증된 신호는 약한 롱 신호 하나뿐이고, 대부분의 회차는 "모름"이 정상이다.

## 시험

```
cd analyzer/platform && npm test
```
