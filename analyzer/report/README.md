# BTC/USDT 보고서 파이프라인 (analyzer/report)

차트 데이터 → 클로드 분석 → 6쪽 PDF → 텔레그램. PC·서버 없이 **Claude 공식 예약작업(클라우드)** 에서 돌리는 것을 목표로 한다.

## 흐름

```
node run.cjs fetch   OKX 실시간 봉을 받아 4시간봉 검증 신호 + 멀티 타임프레임 계산 → latest.json
(클로드가 latest.json 을 보고 page_a.json 에 유형 A 의견·단타 관점을 쓴다)
node run.cjs send    latest.json + page_a.json 으로 6쪽 PDF를 만들어 텔레그램 전송
node run.cjs both    fetch + send (클로드 분석 없이 자리표시로)
node run.cjs build   전송 없이 PDF만 (개발 확인용)
```

## 파일

| 파일 | 하는 일 |
|---|---|
| `okx.cjs` | OKX 공개 API로 4시간봉(+타임프레임별) 봉 읽기. 거래량은 `vol_btc`(바이낸스와 맞춘 칼럼) |
| `mtf.cjs` | 타임프레임별 객관 계산(추세·변동성·지지저항·모멘텀)과 차트 자료 |
| `chart.cjs` | PDF 안에 봉차트를 벡터로 직접 그림(브라우저 불필요) |
| `diagrams.cjs` | 분석 이론 페이지의 예시 도식 |
| `pdf.cjs` | 6쪽 보고서 조립 (타임프레임 차트 6개 + 4h 검증 상세 + 분석 이론 + 개념 사전) |
| `telegram.cjs` | 텔레그램 `sendDocument`/`sendMessage` |
| `run.cjs` | 전체 묶기 |

## 보고서 구성 (6쪽)

1. 단타 관점 + 5분·15분 차트
2. 30분·1시간 차트
3. 4시간·일봉 차트
4. 4시간봉 유형 B 검증 신호 상세 (유일하게 과거 검증된 신호)
5. 분석 이론 (그림 예시 포함)
6. 개념 사전

- **유형 A** = 클로드가 차트를 보고 직접 낸 의견(검증 안 됨).
- **유형 B** = 2020~2023 4시간봉으로 기준을 고정해 검증한 신호. **4시간봉 전용**. 다른 타임프레임은 "객관 구조(검증 아님)"만 보여준다.
- 실시간은 OKX(바이낸스 선물과 약 90% 일치) 미리보기. 바이낸스 선물 실시간은 클라우드에서 위치 차단.

## 비밀·설정

- `secrets.json` (커밋 안 함, `.gitignore`): `{ "telegram_token": "...", "chat_id": "..." }`
- 한글 폰트: `fonts/NanumGothic-*.ttf` (OFL, 재배포 가능). 없으면 윈도우 맑은 고딕으로 대체.

## 설치

```
npm ci --omit=dev --ignore-scripts     # pdfkit 만 받는다. 설치 중 스크립트 실행을 끈다
```

PDF를 그림으로 바꿔 눈으로 확인하는 `_render.mjs`는 개발용이다. 필요한 부품(`pdf-to-img`)은 설치 스크립트를 돌리고
압축 풀기 부품(`tar`)에 알려진 취약점이 있어 기본 설치에서 뺐다. 꼭 필요할 때만 `npm install --no-save pdf-to-img` 로 잠깐 받는다.

## 주의

- 주문·매매 기능 없음. 읽고 계산·보고만 한다.
- 기준값(0.4217, 0.0857 등)은 2020~2023 자료로 고정. 바꾸지 않는다.
