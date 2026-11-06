# C. 데이터·인프라·보안 설계 — 1시간마다 "수집 → 계산 → AI 분석 → PDF·그림 → 텔레그램 → 기록"

> 작성: 데이터·인프라·보안 담당 · 2026-11-06 · 저장소는 읽기만 했다(수정·커밋 없음)
> 표기: **[직접]** 원문(공식 SDK 소스·명세 사본·PyPI·저장소 코드)을 직접 열어 확인 · **[실측]** 이 컨테이너에서 직접 재 봄 · **(검색 요약)** 웹 검색 요약으로만 확인 · **(추정)** 가정을 둔 계산 · **확인 필요** 확인 못 함
> 이 컨테이너는 바이낸스·텔레그램에 접속할 수 없다. 그래서 바이낸스 사실은 공식 SDK 소스(GitHub raw), 텔레그램 사실은 Bot API 10.3 명세 사본과 python-telegram-bot 22.8 소스로 확인했다. developers.binance.com 등 일반 사이트는 이 세션에서 막혀 있다.

---

## 0. 결론 (먼저 읽을 것)

| # | 결정 | 한 줄 이유 |
|---|---|---|
| 1 | **처음 2~4주는 사용자 맥에서 돌린다.** 맥은 전원을 꽂아 두고, 봇이 도는 동안만 잠자기를 막는다(`caffeinate`). 가동률이 95% 밑이거나 노트북이라 24시간이 안 되면 **도쿄 리전 작은 서버**(월 약 $5~12, 확인 필요)로 옮긴다 | 추가 비용 0에 가깝고 한국 IP 그대로라 "서버로 우회" 논란이 없다. 서버는 계좌(약 36 USDT) 대비 월 14~33%가 고정비다 |
| 2 | 구조 = **launchd(감시자) → 상주 프로세스(일정·텔레그램, 텔레그램 토큰만) → 매시간 새 작업 프로세스(데이터·계산·AI·그림, AI 키만) → SQLite + 파일** | 작업마다 새 프로세스라 메모리 누수·멈춤을 15분 제한으로 끊고, 비밀도 프로세스별로 나뉜다(최소 권한) |
| 3 | **매시 정각 봉 마감 + 20초**(바이낸스 서버 시각 기준) 시작 → 목표 전송 **HH:03**, 늦으면 HH:10에 "지연" 표시, HH:15에 포기·경고. 잠자기 등으로 놓친 시간은 **소급하지 않고** 최신 봉 1건만 "지연 보고" | 1시간 지난 보고서는 쓸모가 없다. 몰아서 보내면 알림 폭탄이다 |
| 4 | 데이터는 **REST만**(봉 1h·4h·1d, 마크가격·펀딩, 미결제약정, 통계 5종, 거래 규칙). 시간당 가중치 약 9 — 한도의 0.01%도 안 된다. **웹소켓은 쓰지 않는다**. 30일만 보관되는 통계는 **매시간 DB에 쌓는다** | 웹소켓은 2026-03에 주소 체계가 바뀌는 등 유지 부담만 크다 |
| 5 | 텔레그램: 매시간 **사진 1장(1280px 차트) + 요약 캡션(≤1,024자) 무음 + [PDF] [상세] 버튼**. PDF는 4시간봉 마감·판단 변경·요청 때 자동 첨부. **소리는 "진입 조건 충족·판단 변경·시스템 치명"만** | 하루 24번 소리 알림은 곧 무시된다 |
| 6 | 한글 명령 `/분석` 등은 **텔레그램 규칙상 명령으로 등록할 수 없다**(영문 소문자·숫자·밑줄만 [직접]). → `/now /status /history /pause /resume` + 한글 키보드 버튼("분석·상태·기록·중지") | 기존 권한 검사(`is_authorized`)를 그대로 쓴다 |
| 7 | PDF는 **matplotlib 한 그림 → PDF(Type 42, 한글 TTF 포함) + PNG**. 실측: PDF 56KB, 사진 169KB, 약 1.2초, 최대 메모리 166MB. **Playwright(브라우저)는 쓰지 않는다** | 가볍고, 해시 고정이 되고, AI 글이 "실행되는 내용"이 될 길이 없다 |
| 8 | 비밀 3개(Anthropic·GLM·텔레그램)는 `~/.config/btcreport/secrets/` 파일(폴더 700, 파일 600). 저장소·iCloud·문서 폴더 밖, Time Machine 제외. 환경 변수 금지·로그 가림 유지 | 기존 `read_secret`·`check_env_no_secrets`·`RedactingFilter` 재사용 |
| 9 | **맥에서 지금 requirements.txt는 그대로 설치가 실패한다**: cryptography·cffi에 맥용 휠 해시가 없다 [직접]. 보고서 전용 `requirements-report.txt`(cryptography 제외, matplotlib 계열 모든 플랫폼 해시)를 새로 만들고 **맥은 파이썬 3.14**로 고정한다(3.15는 numpy 2.4.6 휠이 없음 [직접]) | |
| 10 | 대체 경로: **주 모델 Claude → GLM → 계산 엔진 템플릿**. 무엇이 실패해도 그 시간 보고서는 나간다. 비용은 코드(일·월 상한) + 콘솔 한도 + GLM 선불 잔액의 3중 상한 | |
| 11 | **비용 경고**: 월 $300 = 약 42만 원 = 계좌 5만 원의 8배다. 우위가 확인되기 전에는 "매시간 저가 모델 + 4시간마다 상위 모델"로 **월 $30~55(약 4~8만 원, 추정)** 이하를 권한다(§8.4) | 요청 4번 허락에 따른 수정 제안 |
| 12 | 만드는 순서: **① AI 없이 PDF 받아 보기(2일) → ② 자동 실행·기록(2일) → ③ AI·대체·비용 상한(3일) → ④ 강화·맥 설치(2일) → ⑤ 1~2주 관찰**. 개발 약 9.5일, 달력 2~3주(추정) | 가장 먼저 "맥에서 바이낸스가 열리는지·텔레그램이 오는지"를 확인한다 |

**꼭 피해야 할 함정 13가지** (모두 이번 조사에서 근거 확인)

| # | 함정 | 대책 |
|---|---|---|
| 1 | 같은 텔레그램 토큰으로 두 프로세스가 롱 폴링 → 409 충돌 | 보고서용 **새 봇**을 만든다(기존 모의 봇과 토큰 분리) |
| 2 | launchd로 돈 파이썬은 문서·데스크톱·다운로드·iCloud 폴더를 못 읽는다(TCC) (검색 요약) | 코드·데이터를 `~/Library/Application Support/btcreport/`에 둔다. 파이썬에 "전체 디스크 접근"을 주지 않는다 |
| 3 | requirements.txt 해시가 맥 휠을 안 덮음(cryptography·cffi) [직접] | 보고서 전용 해시 파일 |
| 4 | 파이썬 3.15: numpy 2.4.6·contourpy 1.3.3·pydantic_core 2.46.5 휠 없음 [직접] | 3.14 설치판 사용, 스크립트가 버전 확인 |
| 5 | 맥 기본 한글 글꼴(.ttc)을 PDF Type 42로 넣으면 오류 사례(matplotlib #21893) (검색 요약) | Pretendard TTF(OFL)를 버전·해시 고정으로 받아 쓴다 |
| 6 | 텔레그램 명령은 영문만 [직접] | 영문 명령 + 한글 버튼 |
| 7 | 앨범(sendMediaGroup)에는 버튼을 못 달고, 사진과 PDF를 섞을 수 없다 [직접] | 사진 1장 + 버튼 방식 |
| 8 | 사진은 텔레그램이 다시 압축(1920×1080 → 1280×720 사례) (검색 요약) | 미리보기는 처음부터 1280px·큰 글씨로 |
| 9 | 맥 잠자기 동안 파이썬 단조 시계가 멈출 수 있다(bpo-41303) (검색 요약) | 긴 대기 대신 **15초마다 벽시계 확인** |
| 10 | 바이낸스 통계(미결제약정 기록·롱숏비)는 최근 30일만 [직접] | 매시간 DB 저장 |
| 11 | 맥이 밤마다 자면 하트비트 경보가 매일 밤 울린다 | 24시간 운영(잠자기 막기)인지, 낮 시간만인지 먼저 정하고 경보 일정도 맞춘다 |
| 12 | AI가 쓴 숫자(가격·레버리지)를 그대로 보여 주면 틀린 조언이 된다 | 가격·레버리지는 **코드가 계산**, AI는 의견과 수준 번호만 |
| 13 | 텔레그램 토큰이 털리면 메시지 번호로 과거 메시지를 복사해 갈 수 있다(protect_content는 '전달'만 막는다고 명세에 있음) [직접] | 텔레그램에는 비밀·계좌 금액 절대값·개인 정보를 **처음부터 보내지 않는다** |

---

## 1. 전체 구조

```
[launchd: com.btcreport.daemon]  KeepAlive (죽으면 다시 띄움)
        │
        ▼
[상주 프로세스 bot.report.main run]  ── 텔레그램 토큰만 읽음
   ├─ 시작할 때 caffeinate -i -s -w <자기 PID> 를 띄움 → 이 프로세스가 사는 동안만 잠자기 방지
   ├─ 일정 루프: 15초마다 벽시계·바이낸스 서버 시각 확인 → "새 1시간봉 마감 + 20초"면 작업 시작
   ├─ 작업 실행: subprocess(python -m bot.report.worker --bar <마감시각>), 제한 15분
   ├─ 텔레그램: 롱 폴링(명령·버튼) + 발신(사진·PDF·글) + 보관함(outbox) 재전송
   ├─ 하트비트: 성공마다 healthchecks 핑, 실패면 /fail
   └─ 워치독: 루프가 5분 넘게 멈추면 스스로 종료 → launchd가 다시 띄움
        │ DB(WAL)로만 주고받음
        ▼
[작업 프로세스 bot.report.worker]  ── Anthropic·GLM 키만 읽음(텔레그램 토큰 없음)
   데이터 수집(REST) → 검사 → 계산(지표·수준·규칙 판정·최소 주문·레버리지) → AI(주→대체→템플릿)
   → 그림 1장 → PDF + PNG → DB에 BUILT 기록 후 종료
        ▼
[기록] ~/Library/Application Support/btcreport/
   data/report.sqlite3 (보고서·시세 스냅샷·AI 호출·비용·감사 로그)  ·  out/YYYY/MM/*.pdf|*.png (30일)
```

- 상주 프로세스가 텔레그램 발신을 혼자 맡는다 → 보낼 곳·형식·소리 정책·중복 방지가 한곳에 모인다.
- 작업 프로세스에는 텔레그램 토큰이 없고, 상주 프로세스에는 AI 키가 없다. 한쪽이 뚫려도 비밀 하나씩만 샌다(기존 프로세스 A/B 분리 원칙 SEC-08과 같은 생각).
- 하나의 맥에 하나만: 잠금 파일(`fcntl.flock`)로 두 번째 실행을 거부한다.

---

## 2. 재사용 지도 (모듈별: 그대로 / 고칠 것 / 새로 만들 것)

> 원칙: 기존 모의 봇(E0-L-ENS 일봉)의 검증기·DB는 **느슨하게 고치지 않는다.** 보고서 시스템은 `bot/report/` 새 패키지와 **별도 설정·별도 DB 파일**로 만들고, 공용 부품만 꺼내 쓴다.

| 모듈 | 그대로 쓸 것 | 고칠 것 | 새로 만들 것 |
|---|---|---|---|
| `bot/config.py` | `Secret`(repr·str에 값 안 나옴), `read_secret`(절대 경로·일반 파일·600/400·1~4096바이트·공백 거부), `read_telegram_token`(토큰 모양 검사), `check_env_no_secrets`, `ConfigError`, `_coerce`(모르는 키 거부), `RedactingFilter`, `setup_logging` | `Secrets`에 `glm_api_key` 추가 · `FORBIDDEN_ENV_NAMES`에 `GLM_API_KEY`·`ZHIPUAI_API_KEY`·`ZAI_API_KEY` 추가(일반 규칙 `*_API_KEY`가 이미 잡지만 명시) · `RedactingFilter`가 비밀 4개 값(+핑 URL)을 가리게 · `_LOG_SECRET_PATTERNS`에 GLM 키 모양(형식 확인 필요) 추가 · `setup_logging(file_path=…)`: 회전 파일 핸들러(10MB×5, 0600)에도 **같은 필터** | `bot/report/config.py`: `ReportConfig`(mode="report"), `ReportScheduleConfig`, `GlmConfig`, `BudgetConfig`, `OutputConfig`, `load_report_config()`, `validate_report()`, `ALLOWED_GLM_BASE_URLS`, `ALLOWED_CLAUDE_MODELS` |
| `bot/marketdata.py` | `LiveBinance._get`(지수 백오프, Retry-After, 418이면 중지, **리다이렉트 안 따라감**, 응답 본문을 오류에 안 넣음), `_parse_klines` 검사(봉 길이·경계·양수), `server_time_ns`, `check_clock`, 가짜 전송 주입 구조 | `_INTERVAL_NS`에 `1h`·`4h` 추가 · 봉 파싱에서 **테이커 매수량(9번 열)·체결 수(8번 열)** 보존 · 451·403·3xx·DNS/TLS 실패를 `MarketAccessBlocked`로 구분(경고 등급용) · 마감 판정을 바이낸스 서버 시각으로 하는 옵션 | `LiveBinance.bars(interval, until_ns, limit)`, `premium_index()`, `open_interest()`, `open_interest_hist(period, limit)`, `taker_ratio(period, limit)`, `long_short_ratios(period, limit)`(전체·상위 계정·상위 포지션), `exchange_filters()`(하루 1번 캐시), `class MarketAccessBlocked` |
| `bot/analyst.py` | `serialize_input`, `_call_with_deadline`(벽시계 상한), `_classify_exception`(예외 원문 안 남김), `_usage_dict`, `_first_text`, stop_reason 처리(refusal·max_tokens), `analyze()`가 절대 예외를 던지지 않는 구조, `DisabledAnalyst` | `load_prompt` 버전 규칙에 `report_vN` 허용 · `PRICE_PER_MTOK`에 Sonnet 5.5($2/$10)·Haiku 5.5($0.10/$0.50, 10만 토큰 초과 $0.50/$2.50) 추가 [직접] · `estimate_cost_usd`의 캐시 읽기 배수를 모델별로(Opus 5.5는 0.05배 = $0.20) [직접] | `bot/report/ai.py`: `ReportAnalyst`(프로토콜), `AnthropicReportClient`, `GlmReportClient`(httpx, 고정 URL, 새 SDK 없음), `validate_public_payload()`, `validate_report_output()`, `BudgetGuard`, `analyze_with_fallback()` |
| `bot/telegram_ui.py` | `is_authorized`(숫자 사용자 ID + 채팅 ID + private, bool 거부), `sanitize_text`(URL·멘션·마크업·제어 문자 제거, 4자리 이상 숫자 가림), `_outbound`, `UnauthorizedTracker`(무응답 + 감사 + 10분 1회 경고), `check_webhook`, `callback_context_from_update`, `POLLING_KWARGS`(allowed_updates 2종), `send_outgoing`의 보관함 흐름 | `PtbTransport`에 `send_photo(png, caption, *, silent, buttons, protect)`, `send_document(pdf, filename, caption, *, silent, protect)`, `edit_caption()`/`edit_media()` 추가 · 캡션 전용 자르기 `_outbound_caption()`(1,024자, UTF-16 단위로 세기) · `make/parse_callback_data`에 보고서 동작(F=PDF 다시 받기, S=상세) 추가 · `COMMANDS`·`_COMMAND_RE`는 보고서용 별도 목록 | `bot/report/notify.py`: `build_caption()`, `decide_loudness()`, 방해 금지·아침 묶음 · `bot/report/commands.py`: `handle_report_command()`(+한글 별칭) |
| `bot/db.py` | `_ensure_private_file`(0600), WAL·`synchronous=FULL`·`trusted_schema=OFF`·`recursive_triggers`, `transaction`, `audit` + `_redact`, 추가 전용 트리거 + `check_integrity`, `backup_to`, outbox 함수 | `connect()`를 `open_sqlite(path)` + `init_schema(schema, mode)`로 나눠 신호 표 없는 DB도 같은 규칙으로 열게 · outbox에 첨부 파일 경로 열 | `bot/report/store.py`: §9 표들 + 상태 전이 함수(`claim_report`, `mark_built`, `mark_sending`, `mark_sent`, `mark_missed`) |
| `bot/main.py` | `os.umask(0o077)`, `install_excepthooks`(가린 트레이스백만), `_loop_exception_handler`, `TelegramHealth`, `_telegram_supervisor`(재시도·InvalidToken이면 종료·5분 웹훅 점검), `_health_ping`, `_touch_heartbeat`, 종료 코드(0/1/2/3) | 위 함수들을 `bot/runtime_common.py`로 옮겨 두 진입점이 함께 씀 | `bot/report/main.py`(`run`·`once`·`check`·`test-send`·`backup`), `bot/report/worker.py`(`run_one(bar_close_ms)`), 잠금·워치독 |
| `research/briefing_proto/` | `facts.py`의 계산 방법(기준봉·마디·허리·거래량 배수), `render.py`의 색·배지·글꼴 선택 방식 | — | `bot/report/facts.py`(테스트와 함께 다시 작성), `bot/report/render.py`(한 Figure → PDF + PNG), `bot/report/sizing.py`(최소 주문·레버리지) |
| `backtest/` | `structure.py`(스윙·기준봉·마디·허리), `indicators.py` | — | — |
| 의존성 | — | `requirements.txt`의 맥 해시 문제(cryptography·cffi) | `requirements-report.txt`(§7.3) |
| `scripts/` | `backup.sh`의 방식(age 공개키 암호화, 평문 삭제) | — | `scripts/mac/install_report.sh`, `uninstall_report.sh`, `status_report.sh`, `com.btcreport.daemon.plist.template` |
| CI | 테스트·gitleaks(전체 이력) | 파이썬 3.14 매트릭스 추가, `requirements-report.txt` 해시 설치 확인 단계 | `.gitleaks.toml`에 GLM 키 규칙 |

---

## 3. 바이낸스 공개 데이터

### 3.1 쓸 엔드포인트 (모두 키·서명 없음, 호스트 `https://fapi.binance.com`)

가중치·보관 기간은 바이낸스 공식 SDK(`binance-connector-python`, `market_data_api.py`) 문서 문자열에서 직접 확인했다 [직접].

| 무엇 | 엔드포인트 | 권장 파라미터 | 가중치 [직접] | 보관 [직접] | 용도·주의 |
|---|---|---|---|---|---|
| 1시간봉 | `GET /fapi/v1/klines` | `interval=1h&limit=499` | 1~99개: 1 · 100~499: 2 · 500~1000: 5 · 1000 초과: 10 | 제한 없음 | 차트·지표. **limit 500이면 가중치가 5로 뛴다 → 499**. 마지막 원소는 진행 중인 봉일 수 있어 버린다(기존 `_closed_only`) |
| 4시간봉 | 같음 | `interval=4h&limit=300` | 2 | | 상위 흐름. 마감 01·05·09·13·17·21시 KST |
| 일봉 | 같음 | `interval=1d&limit=400` | 2 | | 큰 흐름. 마감 09시 KST |
| 마크·지수 가격, 예상 펀딩, 다음 펀딩 시각 | `GET /fapi/v1/premiumIndex` | `symbol=BTCUSDT` | 심볼 지정 1 (없으면 10) | 현재값 | 보고서 "현재가"는 마크 가격 |
| 확정 펀딩 기록 | `GET /fapi/v1/fundingRate` | `symbol`, `limit` | fundingInfo와 함께 **5분에 500회/IP** 별도 한도 | 기본 최근 200건 | 기존 `funding()` 재사용 |
| 펀딩 간격·상하한 변경 | `GET /fapi/v1/fundingInfo` | — | 0 (위 한도 공유) | — | BTCUSDT 간격이 8시간에서 바뀌면 감지(선택) |
| 미결제약정 현재 | `GET /fapi/v1/openInterest` | `symbol` | 1 | 현재값 | |
| 미결제약정 기록 | `GET /futures/data/openInterestHist` | `period=5m`(limit 12) + `1h`(limit 48) | 0, 별도 **5분에 1,000회/IP** | **최근 1개월만** | 거래 없는 구간은 기록이 빠진다(문서) |
| 테이커 매수/매도량 | `GET /futures/data/takerlongshortRatio` | 같음 | 0, 같은 별도 한도 | 최근 30일 | |
| 전체 계정 롱숏비 | `GET /futures/data/globalLongShortAccountRatio` | 같음 | 0, 같은 별도 한도 | 최근 30일 | |
| 상위 20% 계정 롱숏비 | `GET /futures/data/topLongShortAccountRatio` | 같음 | 문서에 "Security Type: MARKET_DATA" 표기 | 최근 30일 | SDK 호출 방식은 다른 공개 엔드포인트와 같다 [직접]. **키 없이 되는지 맥에서 첫날 확인** |
| 상위 20% 포지션 롱숏비 | `GET /futures/data/topLongShortPositionRatio` | 같음 | 0, MARKET_DATA 표기 | 최근 30일 | 위와 같음 |
| 거래 규칙 | `GET /fapi/v1/exchangeInfo` | — | 1 | — | **하루 1번**. `status=TRADING`, PRICE_FILTER(tickSize), LOT_SIZE·MARKET_LOT_SIZE(stepSize·minQty), MIN_NOTIONAL. 응답의 `rateLimits`로 IP 한도도 기록 |
| 서버 시각 | `GET /fapi/v1/time` | — | 1 | — | 시계 오차·봉 마감 판정 |

- 통계 기간 값은 `5m 15m 30m 1h 2h 4h 6h 12h 1d` [직접], 봉 간격은 `1m … 1h 2h 4h 6h 8h 12h 1d 3d 1w …` [직접].
- 통계 엔드포인트가 1시간 구간을 **마감 몇 초·몇 분 뒤에** 내놓는지는 공식 문서에 없다 → **확인 필요**(맥에서 1주일 동안 "응답의 마지막 timestamp vs 받은 시각"을 기록). 그때까지는 받은 최신 값을 쓰고 그 기준 시각을 보고서에 적는다. 기다리느라 보고서를 늦추지 않는다.

### 3.2 요청량

| 항목 | 시간당 | 근거 |
|---|---|---|
| 가중치(REQUEST_WEIGHT) | 봉 3종 × 2 + premiumIndex 1 + openInterest 1 + time 1 ≈ **9** (+ exchangeInfo 하루 1) | 위 표 [직접] |
| 통계 엔드포인트 | 약 10회(5m·1h × 5종) | 별도 한도 5분 1,000회 [직접] |
| IP 한도 | 분당 2,400으로 알려짐 — **이번엔 원문 확인 못 함** → exchangeInfo `rateLimits`를 시작할 때 기록 | 확인 필요 |
| 결론 | 요청량 걱정은 없다. `/now` 하루 10번을 더해도 무시할 수준 | |

- 응답 헤더 `X-MBX-USED-WEIGHT-1M`을 기록해 두면 다른 프로그램(같은 IP)과 합쳐 한도에 가까운지 볼 수 있다(검색 요약).
- 429면 `Retry-After`를 지키고, 무시하면 418(IP 차단, 2분~3일로 늘어남)이 온다(검색 요약, 기존 코드가 이미 418이면 멈춤).

### 3.3 최소 주문·레버리지 — 엔진이 매시간 계산할 것

`exchangeInfo`의 숫자로 코드가 계산한다(AI가 정하지 않음).

```
최소 수량 = max(minQty, 올림((minNotional ÷ 가격) ÷ stepSize) × stepSize)
최소 명목 = 최소 수량 × 가격
필요한 최소 레버리지 = 최소 명목 ÷ 계좌 증거금
최소 1회 위험(손절 거리 d%) = 최소 명목 × d%  → 계좌 대비 %
```

| 예시 (가정: stepSize 0.001, minQty 0.001, MIN_NOTIONAL 100 USDT — 실제 값 **확인 필요**) | 값 |
|---|---|
| 가격 83,461 (로컬 데이터 마지막 종가, 2026-09-28) | — |
| 최소 수량 | 0.002 BTC (0.001이면 83.5 USDT < 100) |
| 최소 명목 | 약 166.9 USDT |
| 계좌 35.7 USDT일 때 필요한 최소 레버리지 | **약 4.7배** |
| 손절 1%일 때 최소 위험 | 1.67 USDT = **계좌의 4.7%** |

→ 계좌가 작아서 "1% 위험 규칙"을 지킬 수 없는 시간이 대부분이다. 보고서는 이 사실을 숫자로 보여 주고, 규칙상 위험 한도를 넘으면 "진입 불가(최소 주문 때문에 위험 과다)"로 표시해야 한다(퀀트 담당과 맞출 항목). 레버리지 구간표(`leverageBracket`)는 서명이 필요한 엔드포인트라 **키 없이는 못 본다**.

### 3.4 웹소켓이 필요한가

| 용도 | 필요? | 이유 |
|---|---|---|
| 1시간 보고서 | **아니오** | 봉 마감 뒤 REST 한 번이면 된다 |
| 가격 감시("진입 조건 가격에 닿으면 알림", 나중) | 아니오 → REST로 | `premiumIndex`를 60초마다(가중치 1) 부르면 분당 한도의 0.04%다 |
| 웹소켓을 피하는 이유 | | 2026-03에 USDⓈ-M 웹소켓이 `/public`·`/market`·`/private` 경로로 나뉘었고 옛 주소는 2026-04-23에 끊긴다고 공지됐다 (검색 요약). 24시간마다 끊김·재연결·핑 처리도 해야 한다 |

### 3.5 접속 문제: 지역 차단(HTTP 451)과 한국 차단

| 위치 | 바이낸스 공개 API | 근거 |
|---|---|---|
| 미국 IP(미국 클라우드 리전, GitHub Actions 등) | **451 (막힘)** | 여러 사례 (검색 요약) |
| 싱가포르 리전 | **451 사례 보고** | 클라우드 지원 게시판 사례 (검색 요약) |
| 일본(도쿄) 리전 | 막힌다는 근거 못 찾음, "더 안전한 지역"이라는 업체 주장뿐 | 확인 필요 → 서버를 만들자마자 `fapi.binance.com/fapi/v1/time`으로 확인 (INFRA §2.4 30분 점검과 같음) |
| 한국 가정 인터넷(사용자 맥) | 웹 차단 대상으로 확인되지 않음. 단 구글 플레이가 2026-01-28부터 미신고 해외 거래소 앱(바이낸스 포함) 신규 설치·업데이트를 제한하기로 했고(실제 적용 시점은 보도가 엇갈림), 금융정보분석원(FIU)이 미신고 사업자 27곳(BingX·KuCoin·MEXC 등) 웹 접속 차단을 결정했다는 보도가 있다(시점 확인 필요) | (검색 요약) — 바이낸스 웹 차단 여부는 FIU 최신 발표로 **확인 필요** |

**한국에서 막히면 어떻게 보이나** — 바이낸스의 451이 아니라 **통신사 차단**으로 보인다(DNS 실패, 연결 재설정, warning.or.kr로 넘기는 302 등). 그래서 오류를 아래처럼 나눠 경고한다.

| 증상 | 뜻 | 동작 |
|---|---|---|
| HTTP 451 | 바이낸스가 접속 지역을 막음 | 재시도 안 함, **치명 경고(소리)**, 보고서는 "데이터 없음" |
| HTTP 403 | 방화벽(WAF) 차단 | 재시도 안 함, 치명 경고 |
| HTTP 3xx | 다른 곳으로 넘기려 함(통신사 안내 페이지 의심) | **따라가지 않음**(기존 설정), "접속 차단 의심" 경고 |
| DNS 실패·연결 재설정·TLS 오류가 10분 넘게 | 네트워크 장애 또는 차단 | 재시도 후 경고 |
| HTTP 418 / 429 | IP 차단 / 과다 요청 | 멈춤 / Retry-After 지킴 |
| HTTP 5xx | 거래소 장애·점검 | 재시도 |

**대안 비교** (차단될 때)

| 대안 | 평가 |
|---|---|
| 해외 서버·VPN으로 우회 | 기술적으로는 된다. 그러나 기존 원칙(SECURITY PV-33, INFRA §13.1: "서버 위치로 차단을 우회하지 않는다")과 충돌. **권하지 않음** |
| 다른 해외 거래소(Bybit·OKX) 공개 API | 같은 미신고 사업자 문제. 또 사용자가 실제로 거래하는 시장이 아니다 |
| data.binance.vision(일별 파일) | 실시간이 아니다(하루 단위). 같은 계열 도메인이라 함께 막힐 수 있다 |
| 국내 거래소(업비트·빗썸) | 무기한 선물이 없다. 원화 현물 가격은 참고만 가능 |
| **결론** | 한국에서 바이낸스가 막히면 사용자의 수동 주문도 막히므로 이 시스템의 전제가 무너진다. **경고 → 보고 중지 → 사용자 결정**이 맞다 |

---

## 4. 실행 위치와 일정

### 4.1 맥 vs 작은 클라우드 서버

| 기준 | 사용자 맥 (추천: 1단계) | 작은 서버 (Lightsail 도쿄 0.5~1GB) | 제외한 곳 |
|---|---|---|---|
| 월 비용 | 전기료 약 1~3천 원(추정) | $5(0.5GB, 공식 문서) ~ $7~12(1~2GB, 확인 필요) (검색 요약) = 계좌의 14~33%/월 | GitHub Actions 예약 실행: 미국 IP라 451, CI에 비밀 금지 원칙 / Claude Code 클라우드: 구독 앱 자동화 금지(CLAUDE.md) |
| 24시간 가동 | 잠자기·뚜껑·전원·Wi-Fi·업데이트 재시작에 약함 | 강함 | |
| 바이낸스 접속 | 한국 IP 그대로(우회 논란 없음) | 451 확인 필요, 한국 차단 시 "우회" 논란 | 미국·싱가포르 리전(451) |
| 보안 | **일상 기기**라 바이낸스 로그인 세션·텔레그램과 같은 곳 → 맥이 뚫리면 피해가 가장 큼 | 일상 기기와 분리(좋음). 대신 인터넷에 노출된 서버 관리(하드닝·패치) 부담 | |
| 운영 난이도 | 쉬움(이미 교재 스크립트를 맥에서 돌림) | 중간(SSH·방화벽·Docker). 기존 Dockerfile·compose·RUNBOOK 재사용 가능 | |
| 메모리 | 충분 | 실측 최대 166MB → 0.5GB도 되지만 1GB 권장(추정) | |
| 옮길 기준 | 2~4주 측정 후 **보고서 도착률 95% 미만**이거나 노트북이라 24시간 불가 → 서버 | | |

### 4.2 맥에서 안정적으로 돌리는 설정

| 항목 | 설정 | 이유·근거 |
|---|---|---|
| 실행 방식 | **LaunchAgent**(`~/Library/LaunchAgents/com.btcreport.daemon.plist`), `RunAtLoad=true`, `KeepAlive={SuccessfulExit=false}`, `ThrottleInterval=60`, `ProcessType=Standard`(Background 금지: 느려짐), `Umask=63`(=077) | 죽으면 다시 띄움. 설정 오류(종료 코드 0으로 끝내게)면 반복 재시작 안 함 |
| 잠자기 | 상주 프로세스가 시작할 때 `/usr/bin/caffeinate -i -s -w <자기 PID>`를 띄운다 | 봇이 도는 동안만 잠자기를 막는다(`-s`는 전원 연결 때만, `-w`는 봇이 끝나면 자동 해제). launchd가 보는 종료 코드도 봇 자신의 것이라 재시작 규칙이 꼬이지 않는다. 화면은 꺼져도 된다 |
| 노트북 | 전원 연결 + 시스템 설정 > 배터리 > 옵션 > "전원 어댑터 연결 시 디스플레이가 꺼져 있을 때 자동 잠자기 방지" | `caffeinate` 같은 방식은 **뚜껑 닫기 잠자기를 못 막는다** (검색 요약). 뚜껑을 닫으려면 외부 모니터(클램셸) 필요 |
| 데스크톱 맥(mac mini 등) | 시스템 설정 > 에너지: 자동 잠자기 방지, "정전 후 자동 시작" | 24시간 운영에 가장 쉬움 |
| macOS 업데이트 | "업데이트 다운로드"는 켬, **"macOS 업데이트 설치"는 끄고 직접**, 보안 응답은 자동 유지 | 자동 설치 뒤 재시작되면 FileVault 때문에 **로그인 전까지 LaunchAgent가 안 돈다**. 하트비트 경보로 알아챈다 |
| 놓친 실행 | launchd는 잠든 동안의 `StartCalendarInterval` 작업을 깨어난 뒤 실행한다(검색 요약)지만, 우리는 상주 프로세스가 **깨어난 뒤 15초 안에** 스스로 감지 | 맥 잠자기 동안 단조 시계가 멈출 수 있어 긴 `sleep` 금지(bpo-41303) |
| 폴더 | 코드·데이터 `~/Library/Application Support/btcreport/`, 설정·비밀 `~/.config/btcreport/`, 로그 `~/Library/Logs/btcreport/` | 문서·데스크톱·다운로드·iCloud는 launchd 작업이 못 읽는다(TCC, 검색 요약). 파이썬에 "전체 디스크 접근" 권한을 주지 않는다 |
| 코드 위치 | 작업용 저장소와 **별도 사본**(태그 버전을 복사, 쓰기 금지) | 실험 중인 코드가 운영에 섞이지 않게 |
| 네트워크 | 깨어난 직후 Wi-Fi가 늦게 붙으면 재시도(최대 2분) | |
| 더 안전한 선택(2단계) | 봇 전용 **일반 사용자 계정**(관리자 아님) + LaunchDaemon(`UserName=btcreport`) | 내 계정의 브라우저 세션·키체인과 격리되고, 업데이트 재시작 뒤 로그인 없이도 돈다(FileVault 잠금 해제 후). 설치에 sudo가 필요해 1단계에서는 선택 |

맥 폴더 배치

| 경로 | 내용 | 권한 |
|---|---|---|
| `~/Library/Application Support/btcreport/app/` | 배포한 코드(태그 사본) | 쓰기 금지 권장 |
| `.../btcreport/venv/` | 파이썬 3.14 가상환경(해시 고정 설치) | 700 |
| `.../btcreport/data/report.sqlite3` | DB | 600 (기존 `_ensure_private_file`) |
| `.../btcreport/out/YYYY/MM/` | PDF·PNG (30일 보관) | 700 |
| `.../btcreport/fonts/` | Pretendard TTF (해시 확인) | 700 |
| `.../btcreport/backups/` | DB 백업 14개 | 700 |
| `~/.config/btcreport/report.toml` | 설정(비밀 없음, 텔레그램 숫자 ID 있음) | 600 |
| `~/.config/btcreport/secrets/` | 비밀 3개(+선택 1) | 폴더 700 / 파일 600 |
| `~/Library/Logs/btcreport/` | 앱 로그(10MB×5, 가림 필터) + launchd 출력 | 700 |
| `~/Library/LaunchAgents/com.btcreport.daemon.plist` | launchd 설정(**비밀·환경 변수 없음**) | 644 |

### 4.3 서버로 갈 때 (요약 — 상세는 INFRA.md §2~§4 그대로)

| 항목 | 내용 |
|---|---|
| 지역 | 도쿄(451 확인 필요). 미국·싱가포르 금지 |
| 크기 | 1GB 권장(실측 최대 166MB + 여유) |
| 보안 강화 | 들어오는 포트 0(텔레그램은 롱 폴링, SSH는 Tailscale), 키 로그인만, 자동 보안 업데이트, 기존 compose의 비루트·읽기 전용·`cap_drop: ALL`, Compose secrets 파일, chrony, AWS 루트 MFA·예산 알림 |
| 준비 시간 | 초보자 기준 반나절(추정, 안내서가 있을 때) |

### 4.4 1시간 일정 (예: 10시 보고서)

| 시각 (KST) | 단계 | 제한·재시도 |
|---|---|---|
| 10:00:00.000 | 09:00~09:59:59.999 1시간봉 마감 | — |
| **10:00:20** | 시작(바이낸스 서버 시각 기준). 마지막 마감 봉의 `close_time = 09:59:59.999`인지 확인, 아니면 10초마다 재확인 | 최대 2분 |
| ~10:00:35 | 데이터 수집(요청 약 17개) + 검사(연속성·양수·이상치) | 요청당 10초, 재시도 1·2·4초(기존) / 전체 60초 |
| ~10:00:40 | 계산(지표·수준·규칙 판정·최소 주문·레버리지) | 10초 |
| ~10:02:00 | AI 분석(주 모델) | **240초** → 넘으면 GLM(120초) → 넘으면 템플릿 |
| ~10:02:10 | 그림 1장 → PDF + PNG | 20초 (실측 약 1.5초) |
| ~10:02:15 | 텔레그램 전송(상주 프로세스) | 재시도 3번(RetryAfter 지킴), 실패하면 보관함에 넣고 60초마다 재시도 |
| 10:10:00 | 이때까지 못 보냈으면 "지연" 표시를 붙여 보냄 | |
| 10:15:00 | 작업 프로세스 강제 종료, MISSED 기록, 경고 | |
| 11:22 무렵 | 핑이 없으면 healthchecks 경보(주기 60분 + 유예 20분) | 바깥 서비스라 맥이 죽어도 온다 |

- **왜 +20초인가**: ① 마감 직후 몇 초 동안 직전 봉 값이 다듬어질 여지(추정) ② 시계 오차 허용(1초)의 20배 여유 ③ 통계 갱신 지연(확인 필요). 설정으로 10~120초 조정.
- **봉 마감 판정은 바이낸스 서버 시각으로**: 맥 시계가 틀려도 미래 봉을 쓰지 않는다. 맥 시계 오차는 매 실행 기록, 1초 넘으면 하루 한 번 경고.

### 4.5 놓친 실행 정책 (잠자기·정전·네트워크)

| 상황 | 동작 |
|---|---|
| 02:10에 잠들어 09:47에 깨어남 | 03시~09시 보고서는 **MISSED로만 기록**. 09:00 봉으로 보고서 1건을 "지연 보고(봉 마감 09:00, 생성 09:47)"로 무음 전송 |
| 지연 보고인데 규칙상 "진입 조건 충족" | **소리를 내지 않고** "확인 필요(가격이 이미 움직였을 수 있음, 현재 마크가격 표시)"로 낮춘다 |
| 같은 시간 보고서 재요청(재시작 등) | DB 고유키로 막는다(§8.5) |
| 하루 생존 보고(09:00 KST, 무음) | 지난 24시간 보낸·지연·놓친 건수, AI 경로별 횟수, 비용, 시계 오차, 디스크 여유, 마지막 백업 |

---

## 5. 텔레그램 전달

### 5.1 한도 (Bot API 10.3 명세 사본 2026-08-24, python-telegram-bot 22.8 소스) [직접]

| 항목 | 한도 |
|---|---|
| 글(sendMessage) | 4,096자 (기존 코드는 여유 두고 3,500) |
| 캡션(사진·문서) | **0~1,024자** (엔티티 해석 후) |
| 사진(sendPhoto) | 10MB, 가로+세로 ≤ 10,000, 가로세로 비 ≤ 20 |
| 문서(sendDocument) | 50MB. 썸네일은 JPEG 200kB 미만, 320px 이하 |
| 앨범(sendMediaGroup) | 2~10개. **문서는 문서끼리만** 묶인다. **버튼(reply_markup) 없음** |
| 수정(editMessageMedia) | 사진·문서를 다른 파일로 교체 가능(버튼 포함) |
| 무음(disable_notification) | "알림은 오지만 소리가 나지 않는다" |
| 명령(BotCommand) | 1~32자, **영문 소문자·숫자·밑줄만** |
| 버튼 데이터(callback_data) | 1~64바이트 |
| 속도 | 한 채팅에 초당 약 1건(짧은 몰림은 허용, 계속되면 429) |
| PTB 22.8이 지원하는 Bot API | 10.0 |

### 5.2 매시간 무엇을 보낼까 (3안)

| 안 | 매시간 | 하루 메시지 | 장점 | 단점 |
|---|---|---|---|---|
| A. 요청 그대로 | PDF 문서 1개 + 캡션(무음) | 24 | 요청과 같음, PDF 보관 쉬움 | 채팅에 차트가 안 보이고(파일 아이콘) 눌러야 열린다 |
| **B. 추천** | **사진 1장(1280px, PDF와 같은 그림) + 캡션(무음) + [PDF] [상세] 버튼.** PDF는 4시간봉 마감·판단 변경·요청 때 자동 | 24 + 6~8 | 열지 않아도 차트·결론이 보임. PDF도 받음 | 메시지가 A보다 조금 많음 |
| C. 알림 최소 | 고정한 "상태판" 메시지 1개를 매시간 **수정**(수정은 알림 없음), 판단이 바뀔 때만 새 메시지 | 2~6 | 피로 최소 | "매시간 받는" 느낌이 없음. 지난 보고는 `/history` |

- 설정 하나(`delivery = "photo" | "document" | "dashboard"`)로 바꿀 수 있게 만든다.
- 사진은 텔레그램이 다시 압축하므로(1280px로 줄어든 사례, 검색 요약) **처음부터 1280px**로 그리고 핵심 숫자(판정·진입·손절·레버리지)를 크게. 실측: 1280×905 PNG 169KB [실측].
- 캡션은 코드가 만든 틀(판정 · 진입 조건 · 손절 · 목표 · 레버리지·최소 주문 · 세 관점 한 줄씩 · 데이터 기준 시각 · 분석 경로)로 채우고, 1,024자를 넘으면 낮은 순위 줄부터 뺀다(`build_caption`). 이모지는 UTF-16에서 2자로 세므로 쓰지 않는다.
- `protect_content`: 기존 원칙은 켬(전달·저장 금지). 보고서 PDF는 공개 시세 분석이라 **꺼서 사용자가 저장할 수 있게** 하는 것을 권한다(설정 `protect_reports=false`). 상태·비용 메시지는 계속 켠다.
- 단, protect_content는 완전한 방어가 아니다: 명세상 "전달(forwardMessage)"은 막지만 "복사(copyMessage)"의 예외 목록에는 없다 [직접]. 토큰이 털리면 메시지 번호를 하나씩 넣어 과거 메시지를 빼낼 수 있다고 보고, **텔레그램에는 처음부터 민감한 내용(비밀·계좌 금액 절대값·개인 정보)을 보내지 않는다**. 계좌 규모는 비율로만 쓴다.

### 5.3 소리 정책 (알림 피로 줄이기)

| 종류 | 예 | 소리 | 방해 금지 시간(기본 01:00~07:00 KST, 설정) |
|---|---|---|---|
| 중요 | 규칙 엔진의 **진입 조건 충족**(새로 생김), **판단 변경**(관망→롱/숏, 롱↔숏) | 켬 | 보내되 무음 |
| 치명 | 바이낸스 접속 차단(451·403·리다이렉트), **2시간 연속 보고 실패**, 비용 상한 100%, 웹훅 발견(토큰 유출 의심) | 켬 | **켬** |
| 정기 | 매시간 보고서, PDF | 끔 | 보내지 않고 07:00에 밤사이 묶음 요약 1건 |
| 정보 | AI 대체 경로 사용, 비용 50·80%, 하루 생존 보고 | 끔 | 끔 |

- 같은 경고는 10분에 1번만(기존 `UnauthorizedTracker`와 같은 묶음 방식).
- 소리·무음이 폰 잠금 화면에서 어떻게 보이는지는 ARCHITECTURE 확인 항목 21번 그대로 맥 확인 목록에 넣는다(§10.3).

### 5.4 명령 (한글 명령은 등록 불가 → 영문 + 한글 버튼)

| 요청한 이름 | 실제 명령 [직접: 영문만 가능] | 한글 버튼·글자 | 하는 일 | 제한 |
|---|---|---|---|---|
| /분석 | `/now` | "분석" | 방금 마감된 봉으로 즉시 보고서 | **10분에 1번, 하루 10번**, 비용 상한 적용(AI 비용이 들기 때문) |
| /상태 | `/status` | "상태" | 마지막·다음 보고 시각, 오늘·이번 달 비용, AI 경로, 시계 오차, 하트비트 상태 | — |
| /기록 | `/history` | "기록" | 최근 6건 판정 요약 + [PDF 다시 받기] | 파일 보관 30일 |
| /중지 | `/pause` (재개 `/resume`) | "중지" / "재개" | **정기 보고만** 멈춤. 치명 경고·하트비트는 계속 | 텔레그램으로 봇 프로세스를 끄지는 않는다(명령 통로가 끊기므로) |
| (추가) | `/help` | "도움말" | 명령 설명 | — |

- `setMyCommands`로 영문 명령에 한글 설명을 붙여 메뉴에 보이게 하고, 한글은 고정 키보드 버튼(정확히 같은 글자만 인식)으로 받는다.
- **권한 검사 재사용**: 모든 명령·버튼 앞에서 `is_authorized`(숫자 사용자 ID + 채팅 ID + private). 모르는 사람에게는 무응답 + 감사 로그 + 10분 1회 경고(기존 `UnauthorizedTracker`). 자유 문장은 처리하지 않는다. 버튼 데이터는 `v1:F:<16자 무작위 보고서 토큰>`(번호·가격 없음, 기존 PV-12와 같은 방식). 봇은 **어떤 메시지에도 링크를 넣지 않는다**(→ 링크가 오면 피싱이라고 판단 가능, PV-22).

---

## 6. PDF·그림 생성

### 6.1 방식 비교

| 기준 | **matplotlib (채택)** | HTML→PDF (Playwright) |
|---|---|---|
| 설치 | pip 휠, 해시 고정 가능(§7.3) | pip + 크로미움을 따로 받음(`playwright install`, 해시 고정 밖) 또는 설치된 크롬(자동 업데이트로 결과가 바뀜) |
| 속도·메모리 | PDF 약 1.2초, PNG 0.24초, 최대 166MB(라이브러리 포함) [실측] | 매번 브라우저 기동 수 초, 수백 MB(추정) |
| 한글 | TTF 지정, Type 42 **부분 포함**(쓴 글자만) — PDF 안 `FontFile2` 4개 확인 [실측] | CSS 글꼴, 글 품질 좋음 |
| 배치 | 긴 글·표는 줄바꿈을 직접 해야 함 | 표·글 배치 쉬움 |
| 보안 | AI 글은 그림 속 글자일 뿐(실행 요소 없음) | AI 글을 HTML에 넣으면 이스케이프·JS 끄기·외부 요청 차단을 빠짐없이 해야 함(주입 위험) |
| 같은 그림 재사용 | 한 Figure로 PDF·PNG 둘 다 | PNG는 스크린샷을 따로 |
| 결정성 | 메타데이터 날짜를 끄면 같은 입력 → 같은 파일(해시 비교로 중복·회귀 시험) | 브라우저 버전에 따라 변함 |

결론: 1장짜리 "차트 + 판단 표 + 세 관점 글"은 matplotlib로 충분하다. 저장소의 교재 생성기(Playwright)는 수동·오프라인 도구라 그대로 둔다.

### 6.2 실측 (이 컨테이너, 168개 1시간봉 + 이평 3개 + 수평선 2개 + 표 8줄 + 한글 문단, A4 가로)

| 출력 | 크기 | 시간 |
|---|---|---|
| PDF, `pdf.fonttype=42` | **56.0KB** | 1.2~1.5초 |
| PDF, `pdf.fonttype=3` | 101.0KB | 0.35초 |
| PNG 1987×1405 | 271KB | 0.24초 |
| PNG **1280×905**(텔레그램용) | **169KB** (JPEG 88% 142KB) | — |
| 프로세스 전체(파이썬 시작·임포트 포함) | 최대 메모리 166MB | 4.1~4.4초 |

시험 스크립트: `/tmp/claude-0/-home-user-1111/25e0663c-3dd5-5112-98b0-d8d31ac17dd0/scratchpad/team/c_work/scripts/pdf_bench.py` (그림 속 숫자는 시험용 가짜 값).

### 6.3 글꼴 규칙

| 규칙 | 값 |
|---|---|
| 글꼴 | Pretendard v1.3.9 Regular·Bold TTF (SIL OFL) |
| 받는 곳(태그 고정) | `https://raw.githubusercontent.com/orioncactus/pretendard/v1.3.9/packages/pretendard/dist/public/static/alternative/Pretendard-{Regular,Bold}.ttf` |
| sha256 [실측] | Regular `6d0af5258997aec7354a6e340fc2325ba321c410ca48b3af858c8c3d6e92a324` · Bold `c16b88c670d23e83fa1170c954cbc4822d3b8dad3c3cde15d798a94b43d97985` |
| 설치 스크립트 | 받은 뒤 해시가 다르면 **설치 중단** |
| 금지 | Apple SD Gothic Neo 등 `.ttc` 묶음 글꼴로 Type 42 저장(matplotlib #21893 오류 사례) |
| 글꼴이 없거나 해시 불일치 | 그림을 만들지 않고 **글만 보고 + 경고**(한글이 네모로 깨진 PDF를 보내지 않음) |
| 설정 | `pdf.fonttype = 42`, `axes.unicode_minus = False`, PdfPages 메타데이터 `CreationDate=None`(결정성) |

### 6.4 파일 크기·보관

| 대상 | 크기(실측·추정) | 보관 |
|---|---|---|
| PDF | 56KB 실측, 내용이 늘면 100~300KB (추정) | **30일**(`keep_days`), 지나면 삭제 |
| PNG 1280px | 약 170KB | 30일 |
| 하루 합계 | 약 6~12MB (추정) | 30일 ≈ 0.2~0.4GB |
| DB(보고서 메타·입력 JSON·AI 응답·시세 스냅샷) | 시간당 20~40KB (추정) → 연 0.2~0.35GB | **영구** (성과 평가·백테스트 재료) |
| DB 백업 | DB 크기 × 14 | 14일(매일, age 공개키 암호화 선택) |
| 로그 | 10MB × 5 | 자동 교체 |

---

## 7. 보안 (정보보호 관점)

### 7.1 비밀 3개 (+선택 1)

| 비밀 | 파일 | 누가 읽나 | 만드는 곳 | 털리면 | 교체 |
|---|---|---|---|---|---|
| Anthropic API 키 | `~/.config/btcreport/secrets/anthropic_api_key` | 작업 프로세스만 | Console의 **보고서 전용 워크스페이스**(월 지출 한도 설정) | 그 한도까지 과금. 지난 대화 열람 기능은 우리가 쓰지 않음(Files·Batches 미사용) | Console에서 폐기 → 새 파일 → 재시작 |
| GLM API 키 | `.../glm_api_key` | 작업 프로세스만 | z.ai **종량제 API 키**(코딩 플랜 구독을 봇에 쓰지 않는다 — 약관 확인 필요) | 선불 잔액까지 | z.ai에서 폐기 |
| 텔레그램 봇 토큰 | `.../telegram_bot_token` | 상주 프로세스만 | BotFather(보고서 전용 **새 봇**) | 봇 행세(가짜 메시지·피싱 링크), 내 명령 가로채기, 봇 메시지 수정·삭제, **메시지 번호로 과거 메시지 전달·복사**(기록 조회 기능은 없지만 이 방법이 있다 [직접]). **주문 권한 없음** | BotFather `/revoke` |
| (선택) 하트비트 핑 URL | `.../healthcheck_ping_url` | 상주 프로세스 | healthchecks.io | 가짜 생존 신호 | 대시보드 재발급 |

| 규칙 | 이유 |
|---|---|
| 폴더 700, 파일 600(또는 400). 기존 `read_secret`이 그룹·다른 사용자 권한이 있으면 시작 거부 | 같은 맥의 다른 계정·프로그램 차단 |
| 저장소 **밖**(공개 저장소), iCloud Drive·데스크톱·문서 폴더 밖 | 실수 커밋·클라우드 동기화·TCC 문제 |
| 입력은 `read -rs`로(화면·셸 기록에 안 남음). **클립보드 관리자 앱이 있으면 복사·붙여넣기 금지** | 클립보드 기록에 남는다 |
| 환경 변수·launchd plist·설정 파일에 값 금지(기존 `check_env_no_secrets`가 시작 거부) | plist·환경 변수는 다른 프로세스가 볼 수 있다 |
| Time Machine에서 제외(`tmutil addexclusion ~/.config/btcreport/secrets`), 원본은 비밀번호 관리자 | 백업 디스크가 암호화돼 있지 않으면 비밀이 그대로 복사된다. 모두 재발급 가능한 값이다 |
| FileVault 켬, 자동 로그인 끔, 화면 잠금 | 맥 도난·분실 |
| 맥 키체인은 나중 선택지 | 더 안전하지만 LaunchDaemon(로그인 전)에서는 잠겨 있고 CLAUDE.md의 "파일에서만" 원칙과 다르다 |

### 7.2 간단한 위협 모델 (무엇이 털리면 무슨 일이 생기나)

| 털리는 것 | 공격자가 할 수 있는 일 | 피해 상한 | 미리 막기 | 알아채기 | 사고 대응 |
|---|---|---|---|---|---|
| Anthropic 키 | API 사용 | 워크스페이스 월 한도(예: $70) | 파일 600, 로그 가림, 전용 워크스페이스 | 콘솔 사용량 vs 우리 `ai_calls` 기록 차이 | 키 폐기 |
| GLM 키 | API 사용 | 선불 잔액(예: $10), 자동 충전 끔 | 같음 | z.ai 사용량 | 폐기 |
| 텔레그램 토큰 | 위 표(과거 메시지 빼내기 포함) | 채팅에 있던 내용 노출 + 피싱에 속으면 바이낸스 계정까지 | 봇은 링크를 안 보냄, 5분 웹훅 점검(기존), 허용 ID, **민감한 내용은 애초에 안 보냄** | 웹훅 경고, 내가 모르는 메시지, 409 충돌 | `/revoke` 후 새 토큰 |
| 텔레그램 계정(폰) | `/now` 남용, `/pause` | 비용 상한까지 | 텔레그램 2단계 비밀번호, `/now` 속도 제한 | 비용 경고 | 다른 기기에서 세션 종료 |
| **맥 사용자 계정** | 비밀 3개 + **같은 맥의 바이낸스 로그인 세션·텔레그램 앱** | **가장 큼**(바이낸스 계정 자산) | FileVault, 해시 고정, 봇 전용 사용자 계정(2단계), 바이낸스 2FA·출금 주소 화이트리스트 | 로그인·새 기기 알림 | 키 3개 모두 폐기, 바이낸스 비밀번호·세션 정리 |
| 의존성(PyPI) 오염 | 맥에서 코드 실행 → 위 줄과 같음 | 같음 | 버전·해시 고정, 새 패키지 검토, pip-audit | CI 경고 | 이전 버전으로, 키 교체 |
| 시세 위조(DNS·중간자) | 가짜 가격 → 틀린 조언 | **사용자의 수동 주문 손실** | TLS 검증, 리다이렉트 안 따름, 호스트 허용 목록(기존), 값 이상 검사 → **이상하면 진입 조언을 내지 않음**(fail-closed) | 이상치 경고 | — |
| AI 오답·조작 | 그럴듯한 틀린 근거 | 같음 | 입력은 숫자 JSON만, 가격·레버리지는 코드 계산, 출력 스키마 검사, 글 정리(기존 `sanitize_text`) | 규칙 엔진과 의견 불일치를 화면에 표시 | — |
| 보고서 유출 | 분석·계좌 규모 노출 | 사생활 수준 | 계좌는 비율로 표시(선택) | — | — |

→ 돈과 직결되는 현실적 위험은 "비밀 유출"보다 **틀린 조언으로 사용자가 직접 손해 보는 것**이다. 그래서 데이터·계산·AI 출력 검사가 보안 통제다.

### 7.3 의존성 고정

| 항목 | 내용 |
|---|---|
| 문제 1 [직접] | 현 `requirements.txt`의 `cryptography==50.0.2`(해시 12개)·`cffi==2.1.1`(해시 2개)는 **맥 arm64 휠 해시가 없다** → 맥에서 `--require-hashes` 설치 실패. 나머지 24개는 순수 파이썬 휠이거나 맥 휠 해시를 포함 |
| 문제 2 [직접] | 파이썬 3.15용 휠이 없는 것: numpy 2.4.6(3.11~3.14만), contourpy 1.3.3(~3.14), pydantic_core 2.46.5(~3.14). 3.15는 2026-10 출시(검색 요약) → 맥에 "최신"을 깔면 깨진다 |
| 해결 | `requirements-report.txt`를 새로 만든다: 보고서에 필요한 것만(anthropic, httpx, numpy, pandas, python-telegram-bot + 전이 의존성) + **matplotlib 3.11.2, contourpy 1.3.3, cycler 0.12.1, fonttools 4.68.0, kiwisolver 1.5.1, pillow 13.0.0, pyparsing 3.3.3, packaging 26.3**. cryptography·cffi·pycparser는 넣지 않는다(거래소 서명 없음) |
| 맥 휠 확인 [직접] | 위 matplotlib 계열은 모두 맥 arm64·x86 휠이 PyPI에 있다(3.11~3.14) |
| 해시 만드는 법 | 모든 플랫폼·버전 해시를 넣는다(`uv pip compile --universal --generate-hashes` 또는 PyPI JSON). 이 컨테이너에서 PyPI 접속이 되므로 여기서 만들고 CI가 `pip install --dry-run --require-hashes`로 확인 |
| 설치 | `pip install --require-hashes --only-binary=:all: -r requirements-report.txt` |
| 파이썬 | 맥 **3.14**(python.org 설치판). 설치 스크립트가 3.11~3.14가 아니면 중단. CI에 3.14 추가 |
| 정기 | 월 1회 pip-audit, 갱신은 PR + CI + 맥 확인 |

### 7.4 로그 가림

| 대상 | 방법 |
|---|---|
| 앱 로그 | `setup_logging`에 회전 파일 핸들러 추가, **같은 `RedactingFilter`** (비밀 값 그대로 치환 + 모양 패턴) |
| 텔레그램 토큰이 URL에 들어가는 문제 | httpx·telegram 로거 WARNING 유지(기존 `NOISY_LOGGERS`) |
| 잡히지 않은 예외 | 기존 `install_excepthooks`(가린 트레이스백만 stderr로) — launchd의 stderr 파일에도 가린 글만 간다 |
| GLM 키 | 값 치환(확실) + 모양 패턴(형식 **확인 필요**: Zhipu 계열은 `32자 16진수.16자` 형태로 알려짐, 추정) |
| 감사 로그 | 기존 `_redact`(키 이름·값 패턴) 유지, 사용자 원문은 저장 안 함 |
| 점검 | 맥 확인 목록 11번: 로그에서 `sk-ant-`·토큰 모양 검색 결과 0줄 |

### 7.5 gitleaks·저장소

- CI의 gitleaks(전체 이력) 유지. `.gitleaks.toml`에 GLM 키 규칙 추가(형식 확인 후), 테스트용 가짜 값만 허용 목록.
- 설정·비밀·출력이 저장소 밖에 있으므로 커밋될 경로 자체가 없다. 그래도 `.gitignore`에 `report.toml`, `*.pdf`(출력 폴더를 저장소 안에 잘못 지정한 경우) 추가.
- 설정 검증기: 비밀·DB·출력 경로가 저장소 폴더 안이면 **시작 거부**(실수 방지, 새 규칙).

### 7.6 GLM에 보내는 것 = 공개 시세 숫자만

| 보낸다 | 보내지 않는다 |
|---|---|
| 봉(OHLCV·테이커 매수량), 지표, 펀딩, 미결제약정, 롱숏비, 코드가 계산한 수준(번호 + 가격), 기준서 본문(공개 저장소에 이미 있음) | 계좌 금액·잔고·포지션, 텔레그램 ID, 파일 경로, 사용자가 보낸 글, 비밀, 기기 정보 |

- 구현: `build_public_payload()`가 만든 JSON만 AI에 보낸다. `validate_public_payload()`가 **키 허용 목록·숫자만·문자열은 정해진 모양만**(기존 `validate_input`과 같은 방식) 검사하고, 어긋나면 호출하지 않는다. 시험: "계좌" 관련 키가 들어가면 거부되는지.
- Claude에도 같은 페이로드를 보낸다(사이징은 코드가 하므로 AI는 계좌를 알 필요가 없다).
- Z.ai: 싱가포르 법인이 처리, 기본 보관 안 함·학습 안 함이라는 3자 요약이 있으나 원문(API DPA) 확인 못 함 (검색 요약) → 공개 데이터만 보내는 것으로 위험을 없앤다.
- 주소 고정: `https://api.z.ai/api/paas/v4/`(OpenAI 호환, Bearer) (검색 요약). 중국 본토용 `open.bigmodel.cn`은 사용자가 가진 키가 그쪽일 때만 허용 목록에 둔다. 새 SDK 없이 httpx로 부르고, 응답 JSON은 우리 검증기로 다시 검사.

### 7.7 맥 보안 설정 (사용자 체크)

| 설정 | 값 |
|---|---|
| FileVault | 켬 |
| 방화벽 | 켬(+스텔스 모드). 봇은 들어오는 연결이 필요 없다(롱 폴링) |
| 원격 로그인(SSH)·화면 공유 | 필요 없으면 끔 |
| 자동 로그인 | 끔 |
| 파이썬에 전체 디스크 접근 | **주지 않음** |
| (선택) 나가는 연결 감시 | LuLu 같은 무료 도구로 파이썬의 외부 접속을 4곳(바이낸스·Anthropic·z.ai·텔레그램)+핑으로 제한 |

---

## 8. 안정성

### 8.1 시간 제한

| 단계 | 제한 | 실패하면 |
|---|---|---|
| 바이낸스 요청 1개 | 연결 5초·전체 10초, 재시도 3번(1·2·4초) | 데이터 단계 실패 → 30초 뒤 단계 재시도(HH:05까지) → 그래도 실패면 "데이터 없음" 보고 + 경고 |
| Claude | 벽시계 240초(기존 `_call_with_deadline`), SDK 재시도 0. 429·529·5xx면 10초 안에서 1번 재시도 | GLM으로 |
| GLM | 120초 | 템플릿으로 |
| 그림 | 20초 | 글만 보고 |
| 텔레그램 업로드 | 쓰기 30초, 재시도 3번(RetryAfter 지킴) | 보관함 → 60초마다 재시도(다음 정각 전까지) → FAILED, 다음 보고서에 "지난 보고 전송 실패" 한 줄 |
| 작업 프로세스 전체 | **15분** | 강제 종료, MISSED, 경고 |
| 상주 루프 | 5분 동안 한 바퀴도 못 돌면 워치독이 종료 | launchd가 다시 띄움 |

### 8.2 대체 경로 (항상 무언가 보낸다)

| 순서 | 경로 | 넘어가는 조건 | 보고서 표시 |
|---|---|---|---|
| 0 | **계산 엔진(항상 먼저 실행)**: 지표·수준·규칙 판정·최소 주문·레버리지 | — | 숫자는 언제나 이것 |
| 1 | Claude(주 모델) | 시간 초과, refusal, max_tokens, 스키마 실패, 오류, **비용 상한** | "분석: Claude …" |
| 2 | GLM | 같음 | "분석: GLM(대체)" |
| 3 | 템플릿 | — | "AI 분석 없음(사유) — 계산 엔진 결과만" |

- AI는 코드 숫자를 바꾸지 못한다. 의견이 규칙 판정과 다르면 "AI: 롱 / 규칙: 관망"처럼 둘 다 보여 준다.
- 연속 3회 대체 경로면 정보 경고(무음), 24시간 계속이면 치명.

### 8.3 하트비트 ("보고서가 안 오면 알림")

| 겹 | 도구 | 잡는 것 |
|---|---|---|
| ① 바깥 감시 | **healthchecks.io** 체크 1개: 주기 60분 + 유예 20분. 작업 시작 `/start`, 전송 성공 핑, 실패 `/fail`. 경보는 이메일 + healthchecks 자체 텔레그램 연동(우리 봇이 아님) | 맥 꺼짐·잠자기·네트워크 끊김·봇 죽음 — **맥이 죽어도 온다** |
| ② 하루 생존 보고 | 09:00 KST 무음 | "돌긴 도는데 아무것도 안 함" |
| ③ 상주 프로세스 안 | 2시간 연속 실패면 치명 경고(소리) | 데이터·AI·전송 고장 |

- 무료 요금제는 체크 20개, 체크당 기록 100개(검색 요약) — 1개면 충분.
- 맥을 밤에 재울 계획이면 healthchecks를 cron 일정(예: `5 8-23 * * *`, Asia/Seoul)으로 맞춰야 매일 밤 헛경보가 안 난다.

### 8.4 비용 상한

**3중 상한**: ① 코드(`BudgetGuard`: 하루·한 달, 호출 전 최악 비용으로 미리 검사, 호출 뒤 실제 사용량으로 기록) ② Anthropic 콘솔 워크스페이스 월 한도(코드 상한 + 20%, 최종 방어선) ③ GLM 선불 잔액(자동 충전 끔). 50·80% 정보 알림, 100%면 더 싼 경로 → 템플릿.

AI 비용 추정 (가정: 기준서 약 3만 토큰 — 한글 약 2.5만 자 + 영문·기호 약 2.4만 자 [실측 글자 수] / 시세 입력 8천 토큰 / 출력(생각 포함) 6천 토큰 / 세 관점을 **한 번의 호출**로 / 시간 사이 캐시는 안 맞는다고 가정: 60분 간격이 1시간 캐시 수명의 경계라 믿을 수 없다 [직접: 수명은 요청 시작부터 잼] — 모두 **추정**, 단가 [직접])

| 모델 (입력/출력 $/백만 토큰) | 1회 | 매시간 30일(720회) | 원화(1,400원) | 계좌 5만 원 대비 |
|---|---|---|---|---|
| Opus 5.5 ($4/$20) | 약 $0.27 | **약 $196** | 약 27만 원 | 5.5배 |
| Sonnet 5.5 ($2/$10) | 약 $0.14 | 약 $98 | 약 14만 원 | 2.7배 |
| Haiku 5.5 ($0.10/$0.50, 토큰 약 30% 더 셈) | 약 $0.009 | 약 $6 | 약 9천 원 | 0.2배 |
| GLM-5 ($1/$3.20, 검색 요약) | 약 $0.06 | 약 $41 | 약 6만 원 | 1.2배 |
| GLM-5.3-Flash ($0.15/$0.50, 검색 요약) | 약 $0.009 | 약 $6 | 약 9천 원 | 0.2배 |
| 참고: Opus로 세 관점 **따로 3번**(같은 실행 안 캐시 사용, 호출당 출력 3천 토큰) | 약 $0.44 | 약 $315 | 약 44만 원 | 8.8배 → 예산 초과 |

| 권하는 예시 (모델 선택은 AI 담당과 확정) | 월 추정 |
|---|---|
| 매시간 저가 모델(Haiku 또는 GLM-Flash) + 4시간봉 마감 6회/일만 Sonnet | 약 $31 (4.3만 원) |
| 위 + 판단 변경·`/now` 하루 평균 3회만 Opus | 약 $55 (7.7만 원) |
| 기본 상한 제안 | 코드: 하루 $4·한 달 $60 / 콘솔: $70 / GLM 선불: $10 |

- 사용자가 말한 월 $300은 **콘솔 한도의 최댓값**으로만 두고(검증기: 월 상한 ≤ $300), 우위가 확인될 때 올린다.
- 같은 실행 안에서 여러 번 부를 때만 5분 캐시가 이득이다(쓰기 1.25배, Opus 5.5 읽기 0.05배) [직접].

### 8.5 중복 전송 방지

| 장치 | 내용 |
|---|---|
| 한 번만 실행 | 상주 프로세스 시작 때 잠금 파일에 `fcntl.flock`(배타·비차단) → 두 번째는 종료 코드 4로 끝남 |
| DB 고유키 | `reports`의 `UNIQUE(kind, bar_close_ms)` + `claim_report()`는 `INSERT … ON CONFLICT DO NOTHING` 한 번(기존 원자적 전이 방식) |
| 상태 | PENDING → BUILDING → BUILT → SENDING → SENT / FAILED / MISSED / SKIPPED |
| 텔레그램에는 멱등 키가 없다 | "보낸 뒤 DB 기록 전에 죽음"이면 재시작 때 SENDING이 남는다 → "(재전송 · 중복일 수 있음)" 표시를 붙여 1번만 다시 보낸다(정보성 보고서는 놓치는 것보다 드문 중복이 낫다) |
| 409 충돌 감지 | 다른 프로세스가 같은 토큰으로 롱 폴링 중 → 치명 경고(설정 실수) |

### 8.6 시계 확인

| 확인 | 기준 | 동작 |
|---|---|---|
| 매 실행 바이낸스 `serverTime`과 비교(기존 `check_clock`, 왕복 중간값) | 1초 초과 | 하루 1번 정보 경고 |
| | 5초 초과 | 치명 경고(맥 "날짜 및 시간 자동 설정" 확인) |
| 봉 마감 판정 | 항상 서버 시각 | 맥 시계가 틀려도 미래 봉을 쓰지 않음 |
| 대기 방식 | 15초마다 벽시계 재확인 | 잠자기 동안 단조 시계 정지 문제 회피 |

---

## 9. 설정 섹션과 DB 표

### 9.1 `~/.config/btcreport/report.toml` (예시, 비밀 값 없음)

```toml
mode = "report"                    # "live"는 검증기가 거부. 거래소 키 항목 자체가 없다
db_path = "/Users/<나>/Library/Application Support/btcreport/data/report.sqlite3"   # 절대 경로, 저장소 밖

[telegram]
enabled = true
allowed_user_id = 0                # 숫자
allowed_chat_id = 0                # 개인 채팅(양수)만
bot_token_file = "/Users/<나>/.config/btcreport/secrets/telegram_bot_token"
delivery = "photo"                 # photo(추천) | document | dashboard
protect_reports = false

[schedule]
interval = "1h"
delay_s = 20                       # 10~120
deadline_s = 900                   # 작업 강제 종료
quiet_hours_kst = "01:00-07:00"    # 빈 값 = 없음
digest_hour_kst = 7

[claude]
enabled = true
api_key_file = "/Users/<나>/.config/btcreport/secrets/anthropic_api_key"
model = "claude-sonnet-5-5"        # 허용 목록: opus-5-5 / sonnet-5-5 / haiku-5-5
effort = "medium"
timeout_s = 240                    # ≤ 300
max_tokens = 16000
prompt_version = "report_v1"

[glm]
enabled = true
api_key_file = "/Users/<나>/.config/btcreport/secrets/glm_api_key"
base_url = "https://api.z.ai/api/paas/v4"   # 허용 목록만
model = "glm-5"                    # 확인 필요
timeout_s = 120

[budget]
daily_usd = 4.0
monthly_usd = 60.0                 # ≤ 300
ondemand_per_day = 10
ondemand_min_interval_s = 600

[marketdata]                       # 기존 MarketDataConfig 재사용(호스트 허용 목록·BTCUSDT 고정)
request_timeout_s = 10.0
max_retries = 3

[output]
dir = "/Users/<나>/Library/Application Support/btcreport/out"
keep_days = 30
font_regular = ".../fonts/Pretendard-Regular.ttf"
font_regular_sha256 = "6d0af525…a324"

[health]
ping_url_file = ""                 # 선택
```

### 9.2 DB 표 (`report.sqlite3`, 모의 봇 DB와 별도 파일)

| 표 | 핵심 열 | 용도 |
|---|---|---|
| `db_meta` | schema_version, mode='report' | 다른 DB를 여는 실수 방지(기존 방식) |
| `reports` | report_id, token(16자 무작위), kind(hourly·ondemand·digest), bar_close_ms, **UNIQUE(kind, bar_close_ms)**, state, attempts, created/built/sent_ms, latency_ms(전송−마감), stale_s, judgment(LONG·SHORT·WAIT·NO_ENTRY·NO_DATA), loud, provider(claude·glm·template), model, ai_status, cost_usd, input_json(공개 페이로드), input_sha256, facts_json, analysis_json(검증 통과분), pdf/png 경로·sha256, caption, error | 보고서 원장 |
| `report_messages` | report_id, tg_message_id, kind(photo·document·text), silent, sent_ms | 보낸 메시지 추적·`/history` |
| `market_snapshots` | ts_ms, 봉 OHLCV·테이커 매수량, mark·index, 예상 펀딩·다음 펀딩, OI·OI 가치, 테이커비, 롱숏 3종, stats_asof_ms | **30일 넘는 통계 기록 쌓기**(백테스트 재료) |
| `ai_calls` | call_id, report_id, provider, model, started_ms, latency_ms, status, 토큰(입력·출력·캐시 읽기·쓰기), cost_usd(추정), request_id, error | 비용 원장 = `BudgetGuard`의 근거 |
| `report_outcomes` | report_id, horizon(1h·4h·24h), 종가 변화, 최대 유리·불리 폭, 손절·목표 먼저 닿음 | **조언이 실제로 맞았는지** 매일 채점(퀀트 평가용) |
| `runtime_flags` | key ∈ (reports_paused), value, updated_ms, updated_by | `/pause` |
| `outbox` | 기존 + 첨부 파일 경로 | 전송 실패 재시도 |
| `audit_log`, `config_snapshots` | 기존과 같음(추가 전용 트리거·무결성 검사) | 감사 |

---

## 10. 만드는 순서

### 10.1 단계별 작업 (개발 시간은 Claude Code 세션 기준 집중 작업 + 시험, 추정)

| 단계 | 할 일 | 산출물 | 개발 | 사용자 | 이 컨테이너에서 하는 시험 |
|---|---|---|---|---|---|
| 0 | 준비: BotFather로 **보고서용 새 봇**, 내 텔레그램 숫자 ID, Anthropic 전용 워크스페이스·키·월 한도, z.ai 종량제 키·선불 $10, healthchecks 체크, 맥 전원·업데이트 설정, 파이썬 3.14 설치 | 비밀 파일 3개(사용자가 맥에서 직접) | — | 1~2시간 | — |
| 1 | **MVP: AI 없이 PDF 받기** — `LiveBinance` 확장(1h·4h·1d·premiumIndex·OI·통계·exchangeInfo, 오류 구분), 간단 계산·최소 주문, matplotlib 그림·PDF·PNG, `PtbTransport.send_photo/send_document`, `once`·`test-send` 명령 | 맥에서 명령 한 줄로 텔레그램에 첫 보고서 | 2일 | 30분 | 가짜 바이낸스(httpx MockTransport, 로컬 CSV로 만든 응답), 가짜 봇, PDF 1쪽·`FontFile2` 존재·캡션 ≤1,024·PNG ≤10MB |
| 2 | **자동 실행·기록** — `store.py` 스키마·상태 전이, 일정 루프(15초 폴링·+20초·지연·포기·소급 안 함), 작업 하위 프로세스·15분 제한, 잠금 파일, 보관함, healthchecks, 하루 생존 보고, launchd plist·설치 스크립트 초안 | 맥에서 매시간 자동 수신 | 2일 | 30분 | 가짜 시계로 30시간 흘리기(6시간 잠자기 구간 포함 → 지연 보고 1건 + MISSED 6건), 중복 실행·재시작 중복 0, SENDING 복구 |
| 3 | **AI·대체·비용** — 공개 페이로드·검증기, `AnthropicReportClient`, `GlmReportClient`, `BudgetGuard`, `analyze_with_fallback`, 소리 정책·방해 금지, 명령(`/now /status /history /pause /resume /help` + 한글 버튼) | 세 관점 포함 보고서, 명령 동작 | 3일 | 1시간(프롬프트 확인) | 가짜 AI 클라이언트로 시간 초과·refusal·429·스키마 실패·상한 초과 → 대체 경로, 페이로드에 계좌 키 들어가면 거부, 권한 없는 사용자 무응답 |
| 4 | **강화·설치** — 로그 가림 확장·시험, `requirements-report.txt` 해시(이 컨테이너에서 PyPI로 생성), 글꼴 해시 확인, 설정 검증(저장소 안 경로 거부), 백업·보관 정리, gitleaks 규칙, `RUNBOOK_MAC.md` | 설치 스크립트 완성 | 2일 | 1시간 | 비밀 모양 문자열이 로그에 0건, 환경 변수 비밀 거부, 권한 644 비밀 파일 거부, plist에 비밀 없음, `pip install --dry-run --require-hashes` 통과 |
| 5 | **관찰** — 1~2주 운영, 측정: 도착률·지연 분포·하루 비용·대체 경로 비율·통계 갱신 지연, 서버 이전 판단 | 운영 보고 | 0.5일(수정) | 매일 1분 | — |
| 합계 | | | **약 9.5일** | 약 5시간 + 관찰 | 달력 **2~3주**(맥 쪽 확인을 기다리는 시간 포함) |

- 1단계를 먼저 끝내면 사흘 안에 사용자가 "실제 PDF를 텔레그램으로 받는 것"을 본다. 디자인·관점 내용(다른 담당)은 그 위에서 고친다.
- 각 단계 끝에 기존 원칙대로 `.venv/bin/python -m pytest bot -q -m "not slow"` 통과, 작업 브랜치에 커밋·푸시.

### 10.2 이 컨테이너에서의 시험 방법 (바이낸스·텔레그램 접속 불가)

| 대상 | 방법 |
|---|---|
| 바이낸스 | 기존 `FakeBinance`(bot/tests/test_marketdata.py) 확장: 새 엔드포인트 응답을 **로컬 데이터**(`data/binance/BTCUSDT_1h·4h·1d.csv.gz`, `metrics`, `fundingRate`)로 만들어 돌려줌. 451·403·302·418·429(Retry-After)·5xx·시간 초과·NaN·빈 구간·미마감 봉 주입 |
| 텔레그램 | 기존 `FakeBot`(test_telegram_ui.py)에 `send_photo`·`send_document`·`edit_message_media` 추가 → 받은 바이트의 PNG·PDF 시그니처, chat_id 고정, `disable_notification`·`protect_content` 값, 캡션 길이 검사 |
| AI | 기존 `FakeFactory`·`FakeAnalyst` 방식으로 가짜 Claude·GLM(지연·거절·잘못된 JSON·비용 사용량) |
| 시간 | 기존 `FakeClock`으로 시간 점프(잠자기·재시작) |
| 그림 | 실제 matplotlib 렌더링(글꼴은 시험용으로 받아 해시 확인), 1쪽·글꼴 포함·크기 상한 |
| 보안 | 로그 캡처에서 가짜 비밀 문자열 0건, `check_env_no_secrets`, 파일 권한 거부, 설정 모르는 키 거부, live 거부 |
| 의존성 | PyPI 접속으로 해시 생성·검증(맥 arm64·x86, 3.11~3.14) |
| 못 하는 것 | 실제 바이낸스·텔레그램·Anthropic(키 없음)·GLM 호출 → 맥 확인 목록으로 |

### 10.3 맥에서 확인할 것 (사용자가 한 번씩, 결과를 기록)

| # | 확인 | 합격 기준 |
|---|---|---|
| 1 | `python3.14 --version`, 설치 스크립트의 해시 설치 | 오류 없음 |
| 2 | `curl -sS -o /dev/null -w "%{http_code}\n" https://fapi.binance.com/fapi/v1/time` | **200** (451·302·000이면 중단하고 보고) |
| 3 | `.../futures/data/topLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=2` 키 없이 | 200 (아니면 그 지표는 빼고 진행) |
| 4 | `check` 명령 | 비밀 "있음", 권한 통과, 비밀 환경 변수 없음 |
| 5 | `test-send` | 사진·PDF 도착, **무음과 소리의 차이를 잠금 화면에서 확인** |
| 6 | `launchctl print gui/$(id -u)/com.btcreport.daemon` / 프로세스 강제 종료 | 실행 중 / 1분 안에 다시 뜸 |
| 7 | ① `pmset -g assertions`에 봇의 caffeinate가 보이는지 ② 잠자기 시험: 정각을 넘기도록 70분 재우기(직접 "잠자기" 선택) | ① 보임 ② 깨어난 뒤 "지연 보고" 1건만, 그 사이 healthchecks 경보 메일 |
| 8 | 네트워크 시험: 정각 전후 10분 Wi-Fi 끄기 | 재시도 뒤 지연 전송 |
| 9 | 재부팅 후 로그인 | 자동 시작, 시작 알림 |
| 10 | `sntp time.apple.com` | 오차 1초 미만, `/status`의 시계 오차와 비슷 |
| 11 | 로그 검색: `grep -rE "sk-ant-" ~/Library/Logs/btcreport/` 와 `grep -rE "[0-9]{8,}:[A-Za-z0-9_-]{30,}" ~/Library/Logs/btcreport/` | 둘 다 **0줄** |
| 12 | `tmutil isexcluded ~/.config/btcreport/secrets`, `ls -la ~/.config/btcreport/secrets` | 제외됨 / `drwx------`·`-rw-------` |
| 13 | 다른 텔레그램 계정으로 봇에 말 걸기 | 무응답 + 내 채팅에 경고 |
| 14 | 24시간 뒤 `/status`의 비용 vs 콘솔 사용량 | 차이 ±20% 안 |
| 15 | 1주일 통계 갱신 지연 기록 | 평균·최대 지연 숫자 확보(§3.1 확인 필요 해소) |
| 16 | 사진 미리보기 해상도(받은 사진 정보) | 1280px 여부 확인 |

---

## 11. 결정 필요 · 확인 필요

**사용자·팀 결정**

| # | 정할 것 | 추천 |
|---|---|---|
| D1 | 24시간 운영(맥 잠자기 막기) vs 깨어 있는 시간만 | 데스크톱 맥이면 24시간, 노트북이면 낮 시간 + 경보 일정 맞춤 |
| D2 | 텔레그램 안 A·B·C | **B**(사진 + 버튼, PDF는 4시간마다·판단 변경·요청) |
| D3 | 방해 금지 시간 | 01:00~07:00 KST, 07:00 묶음 요약 |
| D4 | AI 월 예산 | 우위 확인 전 **$60 이하**(콘솔 $70), 사용자 상한 $300은 최댓값으로만 |
| D5 | 보고서용 새 텔레그램 봇 | 만든다(기존 모의 봇과 409 충돌 방지) |
| D6 | 봇 전용 맥 사용자 계정 | 2단계(1~2주 안정화 뒤)에 도입 |
| D7 | 서버 이전 기준 | 도착률 95% 미만 또는 24시간 필요 시, 도쿄, 451 확인 후 |

**확인 필요 (맥·조사로 해결)**

| # | 확인할 것 | 언제·어떻게 |
|---|---|---|
| C1 | 통계 엔드포인트의 1시간 구간 갱신 지연, MARKET_DATA 표기 엔드포인트가 키 없이 되는지 | 맥 첫 주 |
| C2 | BTCUSDT 실제 stepSize·minQty·MIN_NOTIONAL, IP 가중치 한도 | 첫 실행의 exchangeInfo 기록 |
| C3 | 도쿄 서버에서 451 여부 | 서버 만들 때만 |
| C4 | 한국의 바이낸스 웹 차단 여부(FIU 최신 발표) | 사용자, 수시 |
| C5 | z.ai 약관(코딩 플랜의 자동화 사용 금지 여부)·API 데이터 정책 원문, GLM 키 형식, 모델 이름 | 키 만들 때 |
| C6 | 텔레그램 사진 축소 해상도 | 맥 확인 16번 |
| C7 | healthchecks 무료 요금제의 최소 주기·텔레그램 연동 | 체크 만들 때 |
| C8 | Lightsail 도쿄 1GB 월 가격 | 서버 만들 때만 |
| C9 | 파이썬 3.15용 numpy 휠이 나왔는지(나오면 3.15 허용) | 월 1회 |
| C10 | protect_content가 켜진 봇 메시지를 copyMessage로 복사할 수 있는지(명세에 명시 없음) | 시험용 봇 두 개로 1회 시험 |
| C11 | `caffeinate -w <PID>`가 맥 버전에서 잠자기를 실제로 막는지(`pmset -g assertions`에 보이는지) | 맥 확인 7번과 함께 |

---

## 12. 출처

**직접 확인 [직접]**
- 바이낸스 공식 SDK `binance-connector-python` — USDⓈ-M `market_data_api.py`(엔드포인트·가중치·보관 기간·MARKET_DATA 표기), `models/enums.py`(봉 간격·통계 기간): https://raw.githubusercontent.com/binance/binance-connector-python/master/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py
- 텔레그램 Bot API 명세 사본 10.3(2026-08-24): https://raw.githubusercontent.com/PaulSonOfLars/telegram-bot-api-spec/main/api.json (sendPhoto·sendDocument·sendMediaGroup·editMessageMedia·BotCommand·disable_notification)
- python-telegram-bot v22.8 `constants.py`·`_bot.py`·`_botcommand.py`: https://raw.githubusercontent.com/python-telegram-bot/python-telegram-bot/v22.8/src/telegram/constants.py
- PyPI JSON(휠 플랫폼·파이썬 버전·해시 대조): https://pypi.org/pypi/matplotlib/3.11.2/json 등 14개 패키지
- Claude 가격·캐시 규칙: claude-api 스킬 문서 `shared/models.md`, `shared/prompt-caching.md`(Opus 5.5 $4/$20·캐시 읽기 $0.20, Sonnet 5.5 $2/$10, Haiku 5.5 $0.10/$0.50, 쓰기 1.25배·2배, 수명은 요청 시작부터)
- Pretendard v1.3.9 글꼴·라이선스: https://raw.githubusercontent.com/orioncactus/pretendard/v1.3.9/packages/pretendard/dist/public/static/alternative/Pretendard-Regular.ttf
- 저장소 코드: bot/marketdata.py, config.py, telegram_ui.py, analyst.py, db.py, main.py, requirements.txt, docs/INFRA.md·SECURITY.md·RUNBOOK.md·ARCHITECTURE.md·STATUS.md

**실측 [실측]** — 이 컨테이너, matplotlib 3.11.2, `.venv` 파이썬 3.11: PDF·PNG 크기·시간·최대 메모리, 글꼴 해시

**검색 요약 (원문 미열람)**
- 바이낸스 451(미국·클라우드 IP): [ccxt #15872](https://github.com/ccxt/ccxt/issues/15872), [binance.vision 451](https://dev.binance.vision/t/api-error-451-unavailable-for-legal-reasons/13828), [binance.vision 미국](https://dev.binance.vision/t/error-451-when-accessing-the-futures-api-from-us/16725), [QuotaGuard](https://quotaguard.com/blog/binance-futures-api-static-ip), [Railway 싱가포르 451](https://station.railway.com/questions/binance-api-returns-http-451-from-singap-7079b988)
- 한국 차단 동향: [전자신문 2026-01-16 구글 바이낸스 앱 차단](https://m.etnews.com/20260116000146), [블록미디어 구글 플레이 1/28](https://www.blockmedia.co.kr/archives/1032177), [딜사이트 웹 차단](https://dealsite.co.kr/articles/170541), [디지털애셋 바이낸스 차단 논란](https://www.digitalasset.works/news/articleView.html?idxno=42239)
- 바이낸스 웹소켓 경로 변경: [Binance Change Log](https://developers.binance.com/docs/derivatives/change-log), [Important WebSocket Change Notice](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice)
- 요청 한도·418: [Binance General Info](https://developers.binance.com/docs/derivatives/futures-data/general-info)
- launchd 잠자기 동작: [launchd.plist(5) 사본](https://git.saurik.com/apple/launchd.git/blob_plain/ed34e3c3e5fb80e0702ac7fb92f189862089d820:/launchd/src/launchd.plist.5), [Apple 포럼 StartInterval](https://developer.apple.com/forums/thread/23361)
- 맥 잠자기 막기: [Technobezz](https://www.technobezz.com/how-to-stop-your-mac-from-going-to-sleep), [Maine IT 뚜껑 닫기](https://tdx.maine.edu/TDClient/2624/Portal/KB/ArticleDet?ID=173788)
- TCC(launchd 폴더 접근): [Apple 포럼 118508](https://developer.apple.com/forums/thread/118508), [TCC launchd woes](https://nunn-blog.pages.dev/2023/11/28/tcc-launchd-woes)
- 파이썬 단조 시계와 맥 잠자기: [bpo-41303](https://bugs.python.org/issue41303)
- 파이썬 3.15 출시: [Real Python 2026-10 뉴스](https://realpython.com/python-news-october-2026/)
- matplotlib TTC Type 42 오류: [matplotlib #21893](https://github.com/matplotlib/matplotlib/issues/21893), [Fonts in Matplotlib](https://matplotlib.org/stable/users/explain/text/fonts.html)
- 텔레그램 사진 압축 사례: [Home Assistant 커뮤니티](https://community.home-assistant.io/t/telegram-image-compression/95820)
- healthchecks 요금: [Capterra](https://www.capterra.com/p/249957/Healthchecksio/pricing/), [freetier.co](https://freetier.co/directory/products/healthchecksio)
- Lightsail 요금: [AWS Lightsail bundles](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html), [cloudburn](https://cloudburn.io/blog/amazon-lightsail-pricing)
- Z.ai GLM: [Z.ai 가격](https://docs.z.ai/guides/overview/pricing), [Z.ai 개인정보](https://docs.z.ai/legal-agreement/privacy-policy), [glm-ai.chat API 안내](https://glm-ai.chat/docs/api/), [Standard Compute 요약](https://standardcompute.com/providers/z-ai)

**이 세션에서 막혀 열지 못한 곳**: developers.binance.com, station.railway.com, dev.to (네트워크 허용 목록 밖)
