# bot/ 설계서 — 추세추종 모의 운영(PAPER) 봇 v0.1

> 작성: 설계 담당 · 기준: docs/TREND_SPEC.md v1.0(조합 **E0-L-ENS**), docs/PLAN.md §4, docs/ARCHITECTURE.md, docs/SECURITY.md, docs/INFRA.md
> 이 문서가 **인터페이스·상태 머신·DB·시간 규칙·보안 규칙의 기준**이다. 구현이 이 문서와 다르면 문서를 먼저 고치고 결정 기록(§12)에 남긴다.
> 설계 담당이 직접 구현·시험한 것: `bot/types.py`, `bot/config.py`, `bot/db.py`, `bot/tests/conftest.py`, `test_db.py`, `test_config.py`, `test_fixtures.py`.
> 나머지 모듈은 시그니처와 규칙만 담은 **스텁**이다(`NotImplementedError`).

---

## 0. 범위

| 한다 | 하지 않는다 (다음 단계) |
|---|---|
| 매일 일봉 마감 뒤 신호 계산(백테스트와 **같은 함수**) | 거래소 API 키, 주문, 서명 요청 — **실제 돈이 움직이는 코드 없음** |
| 텔레그램 카드 → 2단계 승인 → 모의 체결 | 숏, E1(눌림 진입), 55일 단독 등 다른 조합 |
| 보호 손절·추세 청산·펀딩 모의 처리, 일일 리포트 | 텔레그램으로 설정 변경, 자유 문장 지시 |
| Claude 분석(참고 의견, 관문 아님) | 외부 뉴스·텍스트를 Claude에 넣기 |
| 과거 재생(replay) 모드, 백테스트 대조 시험 | 웹훅, 인바운드 포트 |

모드는 `replay`(과거 파일을 하루씩, 가짜 시계) / `paper`(실시간 공개 시세 + 모의 체결) 둘뿐이다. `live`는 설정 로더가 거부한다.

---

## 1. 모듈 책임표

| 파일 | 담당 | 책임 | 외부 의존 |
|---|---|---|---|
| `bot/types.py` | 설계 ✅ | 상태·전이표, 시간 변환, 신호 ID·callback_data, 도메인 자료형, Protocol(Clock·MarketData·ChatTransport·AnalystClient) | 없음 |
| `bot/config.py` | 설계 ✅ | TOML 설정 로드·엄격 검증, 비밀 파일 읽기(`Secret`), 환경 변수 비밀 금지, 로그 가림 필터 | tomllib |
| `bot/db.py` | 설계 ✅ | SQLite(WAL) 스키마, 원자적 전이·복합 트랜잭션, 추가 전용 감사 로그, 백업 | sqlite3 |
| `bot/strategy.py` | 핵심 | `backtest.trend` 재사용 어댑터(복사 금지), 손절·R 분모·청산 시각 계산, Claude 입력 수치 JSON | backtest |
| `bot/marketdata.py` | 핵심 | `LiveBinance`(fapi 공개 REST) / `Replay`(data/binance, 시각 T까지만) | httpx, backtest.data |
| `bot/engine.py` | 핵심 | 일일 사이클, 1분 tick, 버튼 동작의 상태 전이, /pause·/resume, 상태 문구 | db, strategy, paper, analyst |
| `bot/paper.py` | 모의 매매 | 모의 체결·보호 손절·추세 청산·펀딩·일일 리포트 | db, backtest.execution |
| `bot/telegram_ui.py` | 텔레그램 | 카드·버튼 렌더링, 콜백 검증 순서, 명령, PTB 롱 폴링 전송 계층 | python-telegram-bot 22.8 |
| `bot/analyst.py` + `bot/prompts/analyst_v1.md` | Claude | 구조화 출력 호출, 검증, 실패 시 'Claude 분석 없음' | anthropic 1.9.0 |
| `bot/main.py` | 통합 | 진입점(check/run/replay/backup), 시작 점검, 스케줄 루프 | 전부 |
| `backtest/random_fair.py` | 기준선 | 전체 기간 무작위 진입 기준선(참고용) | backtest |

의존 방향: `main → engine → (strategy, paper, analyst, db) → types/config`. `telegram_ui`는 engine을 **호출만** 하고 engine은 telegram을 모른다(보낼 메시지를 `OutgoingMessage`로 돌려줌). 도메인(engine·paper·db·strategy)은 **동기 코드**, 텔레그램만 비동기다.

---

## 2. 데이터 흐름

### 2.1 일일 사이클 (매일 00:00 UTC 마감 + 60초 = 09:01 KST)

```
main 루프(60초마다)
 └─ now ≥ 오늘 판단 시각 이고 cycles[오늘] ≠ DONE ?
     └─ engine.run_daily_cycle()                       (asyncio.to_thread로 실행 — Claude 최대 120초)
         1. 시계 검사: paper면 market.check_clock() (|서버−로컬| > 1000ms → 사이클 FAILED + 경고, 다음 tick 재시도)
         2. db.begin_cycle(날짜)  (DONE이면 끝)
         3. frame = market.daily_bars(판단 시각)        ← 네트워크는 engine.lock 밖(검토 OPS-4)
            놓친 판단일 복구(검토 R-1): 마지막 DONE 사이클 다음 날 ~ 어제(최대 30일)를 날짜순으로
              paper.catch_up(그날 판단) → evaluate_day(그날까지 일봉) → EXIT면 청산 예약(늦으면 감사 'exit_plan_late'),
              ENTRY면 신호를 만들고 즉시 SKIPPED('missed_cycle') → cycles[그날] = DONE('recovered_missed')
         4. paper.catch_up(until = 판단 시각)          ← 신호 계산 전에 반드시. 00:00~00:01 1분봉까지 손절·청산 반영 (T-2)
            (1분봉·펀딩은 락 밖에서 미리 가져오고 DB 반영만 락 안: engine._Prefetched)
            strategy.evaluate_day(frame, 판단 시각 기준 보유 포지션, 진행 중 신호)
              판단 시각 기준 보유 = 판단 전 진입 AND (OPEN 또는 청산 봉 마감 > 판단)  ← tick이 판단 뒤 손절을
              먼저 반영했어도(사이클 재시도) 같은 날 재진입 신호를 만들지 않는다(검토 R-2, 백테스트 T-2와 같음)
         5. N마다:
              EXIT  → db.set_exit_plan(due = 판단 + 30분)          (자동, 사람 승인 없음)
              ENTRY → db.insert_signal(NEW)                          (UNIQUE로 재실행 멱등)
                      일시정지면 곧바로 NEW→SKIPPED('paused')
                      now > 만료(판단+2시간)면 NEW→SKIPPED('late_start')  (재시작이 늦은 경우)
         6. NEW가 하나라도 있으면: input = strategy.analysis_input(...); result = analyst.analyze(input)
              → db.insert_analysis(성공·실패 모두 저장) → 신호에 analysis_id 기록(전이 없이 CARD_SENT 때 fields로)
         7. 카드 OutgoingMessage 목록 생성(kind='card')
         8. db.finish_cycle(DONE), 생성 즉시 건너뛴 신호 알림(사유: late_start/paused/missed_cycle, 검토 OPS-9),
            디스크 여유 < 1GiB면 경고(하루 한 번)
         실패(시세 이상·시계 오차)면 FAILED + 경고 — 1분마다 재시도하지만 경고는 (날짜, 종류)당 한 번(검토 R-3)
 └─ main: 카드마다 transport.send → 성공하면 engine.mark_card_sent(signal_id, message_id)  (NEW→CARD_SENT)
          실패하면 NEW로 남고 tick마다 engine.unsent_cards()로 재시도(만료 전까지)
          카드가 아닌 메시지(체결·청산·경고·만료·리포트)는 실패하면 DB outbox에 보관 → 다음 전송 때 먼저 재전송
          (본문 끝에 '(지연 전송 · 원래 시각)', 리포트는 가장 새 것만, 미전송 500건 상한) — 검토 OPS-3
```

### 2.2 1분 tick

```
engine.tick():
  a. 만료: NEW/CARD_SENT/CONFIRM_PENDING 이고 now ≥ expires_ms → EXPIRED (카드 메시지 수정: 버튼 제거, "만료")
  b. 확인 창 초과: CONFIRM_PENDING 이고 now > confirm_expires_ms → CARD_SENT ('confirm_timeout', 카드 버튼 원복)
  c. paper.fill_approved(now): APPROVED마다 체결 봉(open_ns ≥ approved)이 마감됐으면 체결 → FILLED
  d. paper.monitor(now): 열린 포지션마다 커서 뒤 1분봉을 시간순으로 → 추세 청산/보호 손절/펀딩
     (c·d의 시세 조회는 락 밖에서 한 번에[가장 이른 커서 − 60분, now], 오래 멈췄으면 30일씩 나눠 따라잡음 — OPS-4, R-4)
  d'. 1분봉 빈 구간(거래소 점검)은 오류가 아니다: 다음 봉으로 계속(백테스트와 같음), 빈 구간마다 감사 + 경고 한 번(R-4)
  e. 미전송 카드 재전송 목록
  → OutgoingMessage 목록 반환(체결·청산 알림, 만료 수정)
```

**결과는 tick 주기와 무관해야 한다**: paper는 커서 기반 일괄 처리라, 1분마다 부르든 하루 한 번 부르든 같은 체결·청산이 나와야 한다(재생 모드는 이 성질로 빠르게 돈다).

### 2.3 버튼

```
텔레그램 → PTB CallbackQueryHandler → telegram_ui.handle_callback(ctx)
  ① 권한: from.id == allowed_user_id AND chat.id == allowed_chat_id AND chat.type == 'private'
       실패 → 응답하지 않음 + audit BUTTON_REJECTED(actor=TELEGRAM_UNKNOWN)
              (60초 창마다 보낸 사람별 첫 시도만·창당 20행, 나머지는 요약 1행 — SEC-09)
              + 운영(허용) 채팅으로 경고(10분에 한 번, 시도 수 합산 — SEC-04/DT-06)
  ② 형식: parse_callback_data(data) (fullmatch "v1:[ACXPD]:[A-Z2-7]{16}")      실패 → "알 수 없는 버튼" + 감사
  ③ 신호 존재: db.get_signal                                                  없음 → "알 수 없는 신호" + 감사
  ④ 중복: db.record_button(callback_query_id 고유)                              중복 → 조용히 무시 + 감사
  ⑤ 동작: A→engine.request_confirm, C→engine.confirm, X→engine.cancel_confirm, P→engine.pass_signal, D→상세
       창(확인 60초·승인 2시간)은 **버튼을 누른 시각**으로 판정(락 대기 시간 제외, 최대 5분 전까지 인정 — OPS-4)
       전이 실패(False) → "이미 처리됨/만료됨" 팝업 (상태 불일치·만료·일시정지)
  ⑥ 결과: 카드 수정(확인 화면 [확인][취소] / 승인됨 / 패스됨), answerCallbackQuery
```

### 2.4 시작 순서 (main)

1. `os.umask(0o077)` (DB·WAL·백업 파일 0600)
2. `config.check_env_no_secrets()`가 비어 있지 않으면 **종료 코드 2**(이름만 출력, 값은 보지 않음)
3. `load_config` → `setup_logging(load_secrets(cfg))` → `db.connect(mode 일치)` → `db.save_config_snapshot`
4. paper: `LiveBinance.check_clock()` — 실패해도 죽지 않는다(경고를 첫 바퀴에 보내고 계속, 사이클마다 다시 검사 — OPS-1).
   텔레그램 감독 작업: `deleteWebhook` 후 롱 폴링 시작. 일시 장애(NetworkError 등)면 5초→5분 지수 백오프로 재시도하고
   그동안 스케줄 루프(모의 감시)는 계속 돈다. 토큰 거부(InvalidToken)만 종료 코드 2. 동작 중 5분마다 웹훅 점검(DT-05).
   시작 알림 `[PAPER] 시작 v…, 설정 지문 앞 8자`
5. 재시작 복구: 상태가 전부 DB에 있고 tick이 만료·확인 창·체결·감시를 커서로 따라잡는다. 놓친 판단일은 §2.1의 복구.
6. 비밀 누출 방지 마지막 방어선(SEC-01/OPS-6): main은 모든 예외를 잡아 종류만 기록(코드 1), 가림 excepthook·
   threading.excepthook·asyncio 예외 처리기 설치. 텔레그램 토큰 파일은 모양 검사(`숫자:문자열`, `sk-ant-` 거부).
7. 데드맨(OPS-2): healthchecks 핑은 tick 성공 AND 텔레그램 정상(마지막 전송·웹훅 점검 성공이 15분 안)일 때만 5분마다.
   compose healthcheck는 루프가 매 바퀴 갱신하는 `/tmp/bot-heartbeat`의 나이(5분)로 본다(OPS-8).

---

## 3. 신호 계산 — backtest.trend 재사용 (가장 중요)

### 3.1 원칙
- 신호·손절·R·비용 공식은 **`backtest/trend.py`·`backtest/config.py`·`backtest/execution.py`의 함수를 import해서 그대로 호출**한다. 식을 옮겨 적지 않는다.
- 조합 설정은 `backtest.trend.TrendConfig(entry="E0", direction="L", periods=(20, 55, 100))` 하나. `BotConfig.trend_config()`가 만들고 `base_key == "E0-L-ENS"`를 확인한다. 기본값 그대로: `latency_min=30`, `stop_atr_mult=2.0`, `cost_multiplier=1.0`.

### 3.2 호출 순서 (strategy.evaluate_day)

```python
from backtest import trend as TR, config as C

frame  = market.daily_bars(until_ns=decision_ns)      # close_ns ≤ 판단 시각인 마감 일봉(표준 봉 프레임)
daily  = TR.DailyData.from_frame(frame)               # atr = trailing_mean(true_range(h,l,c), 20)  (현재 봉 제외)
t      = len(daily) - 1                               # 방금 마감된 일봉
assert daily.decision_ns[t] == decision_ns            # = close_ns[t] + C.AVAIL_DELAY_NS(60초). 다르면 ValueError(오래된·미래 데이터)
for n in cfg.periods:                                 # (20, 55, 100)
    sig = TR.channel_signals(daily, n)                # up=U_N, dn=D_N, ex_hi=U_M, ex_lo=D_M, valid, long_entry, long_exit …
    if 보유 중(n):     action = EXIT if sig.long_exit[t] else HOLD
    elif 진행 중 신호(n): action = BUSY
    elif sig.long_entry[t]: action = ENTRY            # valid[t] & close[t] > U_N[t]
    else:              action = NONE
    SubsystemSignal(n=n, m=sig.m, close=daily.close[t], entry_level=sig.up[t], exit_level=sig.ex_lo[t],
                    atr20=daily.atr[t], valid=bool(sig.valid[t]), signal_close_ns=daily.close_ns[t], decision_ns=…)
```

- `short_entry`는 보지 않는다(`TrendConfig.allow_short == False`, `run_subsystem`과 같은 처리).
- `channel_signals`·`trailing_extremes`·`trailing_mean`은 **직전 창만** 쓰므로, 판단 시각까지 자른 프레임의 마지막 값 = 전체 기간으로 계산한 백테스트의 같은 봉 값이다(미래 참조 없음, `test_strategy`에서 검사). LiveBinance가 최근 500일만 받아도 값이 같다(필요 창: 100일 + ATR 21일).

### 3.3 체결 뒤 숫자 (strategy 도우미 → paper가 사용)

| 값 | 식 (그대로 호출) | 백테스트 대응 (`simulate_trend_trade`) |
|---|---|---|
| 보호 손절 | `C.round_price(entry − side × cfg.stop_atr_mult × atr20)` — atr20은 **신호 날** 값(signals.atr20) | `stop = C.round_price(entry_price − side * dist)` |
| R 분모 | `C.risk_per_unit(entry, stop, cfg.entry_rate) + cfg.entry_slip_rate × entry` | `risk = …` (T-6) |
| 비용 | `fees, slip_exit = X.trade_costs(cfg.entry_rate, entry, exit, False, 1.0)`; `slippage = slip_exit + cfg.entry_slip_rate × entry` | 같음 |
| 펀딩 | `f_start = X.funding_start('market', entry_ms, approved_ms)`; `f_start < f ≤ exit_bar_open`마다 `side × rate_f × open(f 시각 1분봉)` | `X.funding_cost` |
| 순손익·R | `net = gross − fees − slippage − funding`, `R = net / risk` | 같음 |
| 추세 청산 시각 | `exit_due = 청산 신호 판단 시각 + cfg.latency_ns` (30분) | `time_limit = exit_signal_ns + cfg.latency_ns` |
| 크기(보고용) | `qty = min(equity × TR.RISK_R ÷ risk, equity × TR.NOTIONAL_CAP_PER_SYSTEM ÷ entry)` | `size_fraction` |

### 3.4 봉 단위 청산 규칙 (paper.monitor, `X.scan_exit`의 order_type='market' 규칙과 동일)

체결 봉 j0(= `open_ns ≥ approved_ns`인 첫 1분봉)부터 시간순으로 봉 j마다:
1. `j > j0` 이고 `exit_due`가 있고 `open_ns[j] ≥ exit_due` → **추세 청산**, 가격 `open[j]` (`reason='trend'`)
2. 아니면 `low[j] ≤ stop` → **보호 손절**, 가격 `min(stop, open[j])` (시장가 주문이라 체결 봉도 갭 규칙 적용, I-33)
3. 둘 다 아니면 다음 봉. 처리한 봉의 `close_ns`로 커서 전진.

청산 가격·시각은 `exit_ms = open_ns[j]`, `exit_bar_close_ms = close_ns[j]`.

펀딩 순서: 봉 j를 판정하기 **직전에** `f_start < f ≤ open_ns[j]`인 아직 안 넣은 펀딩 f를 모두 넣는다(가격 = f를 포함하는 1분봉 시가, `X.funding_prices`와 같은 뜻). 그래서 청산 봉 시작과 같은 시각의 펀딩은 포함되고, 청산 봉 안쪽(시작 뒤) 펀딩은 빠진다 — `X.funding_cost`의 `f ≤ exit_time`과 같다.

### 3.5 대조 시험 (test_parity, 통합 담당)
재생 모드에서 **모든 카드를 판단 + 30분에 자동 확인**(`replay.auto_approve_latency_min = 30`)하면, 결과가 `TR.run_trend_combo(daily, TrendConfig("E0","L"), xb, fa)`의 체결 거래와 **같아야 한다**:
- 비교 항목: 하위 시스템 N, 신호 마감, 진입 시각·가격, 손절, 청산 시각·가격·사유, 수수료·슬리피지(1e-9), 펀딩·순손익·R(상대 1e-9: 펀딩 합산 순서만 다름).
- 재생 끝에 열린 포지션은 백테스트의 `eod` 거래와 진입 항목만 비교.
- 데이터: ① 합성 `trend_market_small`(260일, 전부 1분 실행 봉, 백테스트 체결 8건 — conftest가 보장) ② 느린 실데이터(`@pytest.mark.slow`): 일봉을 2023-01-01 이전 N일부터 자르고 실행 봉 = 1분봉(2023-01~)으로 **백테스트도 같은 입력**으로 돌린다(백테스트 원래 규칙은 2023-10 전 5분봉이므로).
- 자동 승인 지연 30분은 백테스트의 L=30분과 대응된다: 백테스트 `active_from = 판단 + 30분`, 모의 `approved_ms = 판단 + 30분` → 같은 체결 봉·같은 `funding_start`.

### 3.6 백테스트와 **의도적으로** 다른 점 (대조 시험 밖)
| 상황 | 백테스트 | 모의 운영 | 이유 |
|---|---|---|---|
| 사람이 패스·만료 | 없음(항상 진입) | 하위 시스템은 비어 있음 → 다음 날도 `close > U_N`이면 **새 신호** | TREND_SPEC §1 "그 하위 시스템이 롱 포지션이 아님"을 문자 그대로 |
| 승인 지연 | 고정 30분 | 실제 확인 시각(기록: `approval_latency_ms`) | 승인 지연 분포 수집 |
| 데이터 끝 | `eod` 청산 | 없음(계속 보유) | — |
| 일시정지 | 없음 | 신규 신호 SKIPPED, 보유 포지션 관리는 계속 | 위험을 줄이는 방향만 |

---

## 4. 신호 상태 머신

```
                ┌──────────── SKIPPED (paused / late_start / fill_failed)
                │      ┌───── EXPIRED (승인 창 2시간 초과)
NEW ──카드 전송──► CARD_SENT ──[승인]──► CONFIRM_PENDING ──[확인] 60초 안──► APPROVED ──첫 1분봉 시가──► FILLED ──손절/추세 청산──► CLOSED
                │   ▲  │                    │   │                              │
                │   │  └─[패스]─► PASSED ◄──┘   └─[취소]·60초 초과─► CARD_SENT   └─/pause·체결 불가─► SKIPPED
```

| 전이 | 누가 | 조건(가드) | 기록 필드 |
|---|---|---|---|
| NEW → CARD_SENT | engine.mark_card_sent (전송 성공 후) | now < expires | card_sent_ms, tg_message_id, analysis_id |
| NEW → EXPIRED | tick | now ≥ expires (전송 계속 실패) | — |
| NEW → SKIPPED | 사이클·/pause | 일시정지, 늦은 시작 | reason |
| CARD_SENT → CONFIRM_PENDING | [승인] | now < expires, 일시정지 아님 | confirm_requested_ms, confirm_expires_ms = now+60초 |
| CARD_SENT/CONFIRM_PENDING → PASSED | [패스] | 없음 | — |
| CONFIRM_PENDING → APPROVED | [확인] | now ≤ confirm_expires, now < expires, 일시정지 아님 | approved_ms, approval_latency_ms = approved − decision |
| CONFIRM_PENDING → CARD_SENT | [취소] 또는 tick(60초 초과) | — | reason 'cancel'/'confirm_timeout' |
| CARD_SENT/CONFIRM_PENDING → EXPIRED | tick | now ≥ expires | — |
| APPROVED → FILLED | paper (db.open_position 한 트랜잭션) | 체결 봉 마감, 그 N에 열린 포지션 없음 | 포지션 행 생성 |
| APPROVED → SKIPPED | /pause, 체결 불가 | — | reason |
| FILLED → CLOSED | paper (db.close_position 한 트랜잭션) | — | exit_reason |

- 허용 전이는 `types.SIGNAL_TRANSITIONS` **하나뿐**이고 `db.transition_signal`이 검사한다(없는 전이는 `ValueError` = 코드 버그).
- 모든 전이는 `UPDATE signals SET … WHERE signal_id=? AND state IN (기대값)` 한 문장. 영향 행 0이면 False(중복 클릭·경쟁·만료) → 호출자는 "이미 처리됨"으로 답한다. 성공하면 같은 트랜잭션에서 감사 로그 한 줄.
- `APPROVED`로 가는 길은 `CONFIRM_PENDING`뿐, `FILLED`로 가는 길은 `APPROVED`뿐(`test_transition_table_shape`).
- 종료 상태: CLOSED, PASSED, EXPIRED, SKIPPED. 모든 비종료 상태는 종료 상태로 갈 수 있다(갇힘 없음).
- 하위 시스템 "바쁨" = `ACTIVE_STATES`(NEW~FILLED) 신호가 있음. 승인 창(2시간) < 하루라서 다음 판단 때는 보통 FILLED(보유)이거나 종료 상태다.

---

## 5. 시간 규칙

| 규칙 | 값 |
|---|---|
| 저장 | 모든 시각 **UTC 정수 ms**, 열 이름 `*_ms`. 내부 계산은 ns(backtest와 같은 단위). 변환은 `types.ns_to_ms`/`ms_to_ns` |
| 표시 | `types.kst_str(ms)` → `YYYY-MM-DD HH:MM KST`. 저장·비교에 KST를 쓰지 않는다 |
| 판단 시각 | 일봉 마감(00:00 UTC) + 60초 = **09:01 KST** (`C.AVAIL_DELAY_NS`, 설정 고정 60) |
| 승인 창 | 판단 + 7200초 = 11:01 KST (`expires_ms`, 이 시각 **이상**이면 만료) |
| 확인 창 | [승인] + 60초 (`confirm_expires_ms`, 이 시각 **초과**면 무효) |
| 체결 봉 | `open_ns ≥ approved_ns`인 첫 1분봉(= `ceil_minute(approved)`에 시작하는 봉). 그 봉이 **마감된 뒤** 처리 |
| 추세 청산 | `open_ns ≥ 청산 신호 판단 + 30분`인 첫 1분봉(체결 봉 제외) 시가 |
| 감시 범위 | `close_ns ≤ now`인 봉만. 미마감 봉은 절대 쓰지 않는다 |
| 사이클 날짜 | `cycle_day` = 판단 시각의 UTC 날짜. `signal_day` = 신호 일봉의 UTC 시작일(= cycle_day − 1일) |
| 시계 | paper: `SystemClock` + 매 사이클 서버 시각 비교(허용 1000ms). replay: `FakeClock`(되돌리기 불가) |
| 재생 미래 참조 차단 | `Replay`·`FrameMarket`은 `until_ns > clock.now_ns()` 조회를 예외로 막는다 |

---

## 6. 모의 체결 규칙 요약 (paper)

- 체결가 = 체결 봉 시가(§5). 비용 = 테이커 0.05% + 진입 슬리피지 0.02%(E0), 청산 테이커 0.05% + 슬리피지 0.02% — 전부 `backtest.config` 상수(`FEE_TAKER`, `SLIPPAGE`)에서 온다.
- 보호 손절은 체결 봉부터 활성(§3.4). 손절·추세 청산은 **사람 승인 없이 자동**.
- 펀딩: `paper_trades(kind='FUNDING')` 한 행씩, `(position_id, kind, ts_ms)` 고유라 재실행해도 한 번만.
- 원장: ENTRY 1행, EXIT 1행(부분 고유 인덱스), FUNDING n행. 포지션 행의 합계와 원장이 일치해야 한다(test_paper).
- 일일 리포트(매일 사이클 뒤): 열린 포지션(진입가·손절·미실현 R·보유일), 어제 청산, 누적 거래 수·평균 R·합계 R, 승인 지연 중앙값, 패스·만료 수, Claude 의견 vs 사람 결정 표.

---

## 7. 보안 규칙 (사용자: 정보보호 종사자 — 기본 거부)

### 7.1 비밀
- 비밀 3종(텔레그램 봇 토큰, Anthropic API 키, 헬스체크 핑 URL)은 **파일 경로로만** 받는다(`/run/secrets/*`). `config.read_secret` 검사: 절대 경로, 일반 파일, 다른 사용자 쓰기 불가, 1~4096바이트, UTF-8, 내부 공백·제어 문자 없음. 오류 메시지에 값 없음.
- 값은 `Secret` 래퍼로만 다닌다: repr/str/format이 `***`, pickle·hash 불가. `.reveal()`은 SDK·HTTP 클라이언트를 만드는 **그 한 줄**에서만.
- 환경 변수에 비밀 이름(`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `BINANCE_*` …)이 있으면 시작 거부(`check_env_no_secrets`). Anthropic SDK에는 `api_key=`를 명시해 환경 변수를 읽지 않게 한다.
- 로그: `setup_logging`이 루트 핸들러에 `RedactingFilter`(알려진 비밀 값 + 토큰·`sk-ant-`·hc-ping UUID 모양 가림, 예외 스택 포함)를 달고, URL을 INFO로 남기는 `httpx`·`httpcore`·`telegram`·`anthropic` 로거는 WARNING으로 올린다(httpx는 텔레그램 URL에 토큰을 넣어 로그한다).
- 감사 로그 payload는 키 이름이 token/secret/api_key/password/authorization/ping_url이면 `***`(`db._redact`, 이중 방어). 설정 스냅샷은 경로만 있고 텔레그램 ID는 끝 3자리만.
- `.env.example`에는 **이름만**(값 없음), 실제 비밀은 저장소 밖. `.gitignore`: `.env*`(예시 제외), `*.sqlite3*`, `secrets/`, `backups/`, `bot.toml`(실설정).

### 7.2 텔레그램
- **롱 폴링만**(인바운드 포트 0, compose에 `ports:` 없음). 시작 시 `deleteWebhook`, `allowed_updates=['message','callback_query']`, `drop_pending_updates=True`.
- 허용 사용자 ID 1개·허용 채팅 ID 1개, 둘 다 **int**로 비교(bool·문자열 거부), `chat.type == 'private'`. 설정은 양의 정수만 허용(그룹 채팅 ID는 음수라 거부).
- 허용되지 않은 사용자·채팅: **응답하지 않고**(answerCallbackQuery도 안 함) 감사 로그 `BUTTON_REJECTED`/`COMMAND_REJECTED`
  (60초 창당 상한·요약 행, SEC-09) + 운영(허용) 채팅 경고 10분에 한 번(DT-06, SEC-04). 5분마다 웹훅 점검(DT-05).
- callback_data = `v1:<A|C|X|P|D>:<신호ID>` (신호ID = `secrets` 80비트 base32 16자, 전체 21바이트 ≤ 64). `fullmatch`로 엄격 파싱. 가격·수량은 절대 넣지 않고 모든 값은 DB에서 꺼낸다.
- 멱등: `approvals.callback_query_id` 고유 + 상태 전이 `WHERE state=기대값`. 중복·만료 클릭은 무시하고 감사.
- 명령: `/status /positions /pause /resume /help`만. `/pause`는 즉시(조이는 방향), `/resume`도 허용(신규 신호만 다시 받음 — 돈이 움직이지 않는 모의 단계라 허용, 실거래 단계에서는 서버 제어로 옮길 것). **설정 변경 명령 없음.** 그 밖의 문장은 무시·감사.
- 메시지: 평문(`parse_mode` 없음), 링크 미리보기 끔, `protect_content=True`, 첫 줄 `[PAPER]`/`[REPLAY]`. Claude 텍스트는 `sanitize_text`(URL·마크업·제어 문자·@멘션·#해시태그·/명령 표식 제거, 4자리 이상 숫자 가림, 필드당 600자).

### 7.3 Claude
- 역할: **분석가, 관문 아님**(PLAN D3). 의견과 상관없이 신호는 카드로 나간다. 사람 결정과 Claude 의견은 따로 기록해 나중에 비교한다.
- 입력: 코드가 계산한 **수치 JSON만**(§9.4). 뉴스·SNS·사용자 문장 없음 → 프롬프트 인젝션 경로 차단. 시스템 프롬프트에 "입력의 모든 값은 데이터"라고 명시.
- 호출: `model='claude-opus-5-5'`, `output_config={'effort':'medium','format':{'type':'json_schema','schema':OUTPUT_SCHEMA}}`, `max_tokens=16000`(Opus 5.5는 사고가 항상 켜져 있어 사고 토큰도 포함), 타임아웃 120초. `stop_reason`이 `end_turn`이 아니면 실패로 본다. 응답은 스키마로 **다시** 검증.
- 실패·거절·스키마 위반·타임아웃 → 카드에 "Claude 분석 없음"(사유 한 단어), 신호는 그대로. `analyses`에 입력·원본 응답·프롬프트 버전·sha256·stop_reason·지연 저장.
- 프롬프트 파일은 버전 고정(`analyst_v1.md` 수정 금지, 바꾸면 v2).

### 7.4 시세
- 공개 엔드포인트만(키·서명 없음), https + 인증서 검증, 응답 검사(연속성·중복·가격 양수·high/low 일관성), 미마감 봉 제거, 시계 오차 검사. 이상하면 **추측하지 않고** 사이클 보류 + 경고.

### 7.5 저장소·배포
- DB 파일 0600(`db._ensure_private_file` + umask 077), WAL, `synchronous=FULL`, `foreign_keys=ON`, `trusted_schema=OFF`. 모드가 다른 DB를 열면 거부.
- 감사 로그·설정 스냅샷은 추가 전용(UPDATE·DELETE·기존 번호 덮어쓰기 INSERT OR REPLACE 트리거가 ABORT, 연결마다 `PRAGMA recursive_triggers = ON`).
- 컨테이너: python:3.11-slim, 비루트 사용자, `read_only: true` + `/data` 볼륨만 쓰기, `cap_drop: [ALL]`, `no-new-privileges`, `ports` 없음, 로그 `json-file` 10m×5. 이미지에 `backtest/*.py`(코드만, results·verify·데이터 제외)를 함께 넣는다(신호 코드 재사용). 재생용 `data/`는 읽기 전용 마운트.
- 공급망: `requirements.txt` 버전 고정(현재 venv 버전), CI에서 pytest + gitleaks.

---

## 8. DB 스키마 (`bot/db.py`, SCHEMA_VERSION 1)

| 테이블 | 핵심 열 | 불변식 |
|---|---|---|
| `db_meta` | schema_version, mode, created_ms | 다른 모드로 열면 DbError |
| `signals` | signal_id(16자), subsystem_n∈{20,55,100}, side, signal_day, signal_close_ms, decision_ms, expires_ms, close, entry_level(U_N), exit_level(D_M), atr20, **state**, state_reason, state_version, card_sent_ms, tg_message_id, confirm_*_ms, approved_ms, approval_latency_ms, analysis_id | UNIQUE(mode, N, side, signal_close_ms) = 사이클 재실행 멱등. state CHECK = enum |
| `analyses` | status, ok, opinion, input_json, output_json, raw_response, prompt_version, model, stop_reason, error, latency_ms | 성공·실패 모두 저장 |
| `approvals` | signal_id, action, **callback_query_id UNIQUE**, from_user_id, chat_id, message_id, clicked_ms, result, latency_ms | 허용된 사용자 클릭만(거부는 audit_log) |
| `paper_positions` | signal_id UNIQUE, subsystem_n, state OPEN/CLOSED, active_from_ms, entry_ms, entry_price, qty, stop, risk_per_unit, entry_fee, entry_slippage, last_bar_close_ms(커서), exit_signal_close_ms, exit_due_ms, exit_*, fees, slippage, funding, gross/net_pnl, r_multiple, pnl_usdt | **부분 고유 인덱스: N당 OPEN 1개**. CHECK: OPEN⇔exit_ms NULL |
| `paper_trades` | position_id, kind ENTRY/EXIT/FUNDING, ts_ms, price, qty, fee, slippage, funding, rate | UNIQUE(position_id, kind, ts_ms), ENTRY·EXIT 포지션당 1개 |
| `audit_log` | seq, ts_ms, actor, event_type, entity_type/id, from/to_state, payload_json | **추가 전용 트리거** |
| `config_snapshots` | fingerprint, bot_version, config_json(가린 값) | 추가 전용 트리거 |
| `runtime_flags` | key='paused' | 변경은 감사 로그 |
| `cycles` | cycle_day, decision_ms, status RUNNING/DONE/FAILED | DONE이면 재실행 안 함 |

**원자적 함수** (전부 `BEGIN IMMEDIATE`, 중첩 시 바깥 트랜잭션에 합류, 성공 시 감사 로그 동반):

| 함수 | 반환 | 설명 |
|---|---|---|
| `connect(path, mode=, now_ms=)` | Connection | 0600 생성, WAL, 스키마, 모드 확인 |
| `transaction(conn)` | 컨텍스트 | 예외면 ROLLBACK |
| `audit(conn, ts_ms=, actor=, event=, …, payload=)` | seq | 비밀 키 가림 |
| `insert_signal(…)` | bool | 중복이면 False |
| `transition_signal(conn, id, expected, new, now_ms=, actor=, reason=, fields=, payload=)` | bool | 허용 전이만, `fields`는 SIGNAL_MUTABLE_FIELDS만 |
| `get_signal`, `signals_in_states`, `active_signal_for_subsystem` | 행 | 조회 |
| `record_button(…)` | bool | callback_query_id 중복이면 False |
| `insert_analysis(conn, AnalystResult, signal_day=, now_ms=)` | id | |
| `open_position(…)` | id \| None | APPROVED→FILLED + 포지션 + ENTRY + 감사, N에 열린 포지션 있으면 None(전부 롤백) |
| `set_exit_plan(…)` | bool | 한 번만 |
| `advance_cursor(…)` | bool | 앞으로만 |
| `add_funding(…)` | bool | 같은 시각 두 번 불가, 열린 포지션만 |
| `close_position(…)` | bool | OPEN→CLOSED + EXIT + 신호 FILLED→CLOSED + 감사 |
| `is_paused`, `set_paused` | bool | 값이 바뀔 때만 True |
| `begin_cycle`, `finish_cycle` | bool | DONE 재실행 금지, FAILED 재시도 허용 |
| `save_config_snapshot` | id | |
| `backup_to(conn, dest)` | — | sqlite 온라인 백업, 대상 0600 |

---

## 9. 인터페이스 시그니처

### 9.1 공용 (`bot/types.py`, 구현 완료)
`Mode`, `SignalState`, `SIGNAL_TRANSITIONS`, `TERMINAL_STATES`, `ACTIVE_STATES`, `PENDING_APPROVAL_STATES`, `can_transition`, `PositionState`, `ExitReason('stop'|'trend')`, `TradeKind`, `CallbackAction(A,C,X,P,D)`, `Actor`, `AuditEvent`, `SubsystemAction(ENTRY,EXIT,HOLD,NONE,BUSY)`, `new_signal_id()`, `make_callback_data(action, id)`, `parse_callback_data(data) -> ParsedCallback|None`, `SubsystemSignal`, `AnalystResult`, `Button`, `OutgoingMessage(text, buttons, signal_id, kind, edit_message_id)`, `CycleReport`, `Clock`/`SystemClock`/`FakeClock`, `MarketData`, `ChatTransport`(async send/edit/answer_callback), `AnalystClient`, 시간 도우미(`ns_to_ms`, `ms_to_ns`, `utc_iso_ms`, `kst_str`, `utc_day_start_ns`, `ceil_minute_ns`).

### 9.2 시세 (`bot/marketdata.py`)
```python
class LiveBinance:  # MarketData
    def __init__(self, cfg: MarketDataConfig, clock: Clock, http_client: httpx.Client | None = None)
    def daily_bars(self, until_ns: int) -> pd.DataFrame      # GET /fapi/v1/klines interval=1d limit=500
    def minute_bars(self, start_ns: int, until_ns: int) -> pd.DataFrame   # interval=1m, limit=1500씩 페이지
    def funding(self, start_ns: int, until_ns: int) -> pd.DataFrame      # GET /fapi/v1/fundingRate
    def server_time_ns(self) -> int | None                   # GET /fapi/v1/time
    def check_clock(self) -> int                             # 오차 ms, 초과면 MarketDataError
class Replay:       # MarketData
    def __init__(self, data_dir, clock: Clock)               # backtest.data.load_klines('1d'), ('1m'), load_funding()
    @classmethod from_frames(cls, daily, minute, funding, clock) -> Replay
class MarketDataError(RuntimeError)
```
테스트: httpx `MockTransport`로 가짜 응답(미마감 봉 제거, 빈 구간·중복 거부, 429 재시도·418 중지, 시계 오차, 키 헤더 없음).

### 9.3 엔진 (`bot/engine.py`)
```python
class Engine:
    def __init__(self, conn, cfg: BotConfig, market: MarketData, analyst: AnalystClient | None, clock: Clock)
    def run_daily_cycle(self) -> CycleReport
    def mark_card_sent(self, signal_id: str, message_id: int) -> bool
    def request_confirm(self, signal_id: str) -> bool
    def confirm(self, signal_id: str) -> bool
    def cancel_confirm(self, signal_id: str) -> bool
    def pass_signal(self, signal_id: str) -> bool
    def tick(self) -> list[OutgoingMessage]
    def unsent_cards(self) -> list[OutgoingMessage]
    def pause(self, actor: str) -> list[str]
    def resume(self, actor: str) -> bool
    def status_text(self) -> str
    def positions_text(self) -> str
```

### 9.4 Claude (`bot/analyst.py`)
```python
PROMPT_VERSION = "analyst_v1"; OUTPUT_SCHEMA = {...}      # summary, counter_evidence[], invalidation, opinion enum, confidence_note
def load_prompt(version) -> tuple[str, str]               # (본문, sha256)
def validate_output(obj) -> str | None
class AnthropicAnalystClient:  def __init__(self, api_key: Secret, cfg: ClaudeConfig, *, client_factory=None); def analyze(payload) -> AnalystResult
class DisabledAnalyst                                     # 구현됨: 항상 status='disabled'
```
입력 JSON(`strategy.analysis_input`, 키 고정 — 바꾸면 `schema` 버전 올림):
```json
{"schema":"analyst_input_v1","symbol":"BTCUSDT","timeframe":"1d","decision_time_utc":"2024-03-02T00:01:00Z",
 "strategy":{"key":"E0-L-ENS","spec":"TREND v1.0","periods":[20,55,100],"stop_atr_mult":2.0},
 "recent_daily":[{"date":"2024-02-01","open":…,"high":…,"low":…,"close":…,"volume":…}, … 최근 30개],
 "indicators":{"sma20":…,"sma50":…,"sma100":…,"sma200":…,"atr20":…,"atr20_pct":…,"ret_7d_pct":…,"ret_30d_pct":…,
               "dist_from_100d_high_pct":…},
 "subsystems":[{"n":20,"m":10,"action":"ENTRY","close":…,"entry_level":…,"exit_level":…,"breakout_pct":…,
                "stop_if_filled_at_close":…,"stop_distance_pct":…}, …],
 "open_positions":[{"n":55,"entry_price":…,"stop":…,"unrealized_r":…,"days_held":…}]}
```
이평(sma*)은 표시·분석용이며 결정에 쓰지 않는다. 숫자는 소수 2자리 반올림, 문자열은 코드가 만든 고정 값뿐.

### 9.5 모의 매매 (`bot/paper.py`)
```python
def position_size(equity_usdt, entry_price, risk_per_unit) -> float
def fill_approved(conn, cfg, market, now_ns) -> list[OutgoingMessage]
def monitor(conn, cfg, market, now_ns) -> list[OutgoingMessage]
def catch_up(conn, cfg, market, until_ns) -> list[OutgoingMessage]
def daily_report(conn, cfg, now_ns) -> OutgoingMessage
```

### 9.6 텔레그램 (`bot/telegram_ui.py`)
```python
def sanitize_text(text, max_len=600) -> str
def is_authorized(cfg, from_user_id, chat_id, chat_type) -> bool
def card_buttons(signal_id) / confirm_buttons(signal_id) -> tuple[tuple[Button, ...], ...]
def render_card(signal_row, analysis_row | None, cfg) -> OutgoingMessage
def render_detail(signal_row, analysis_row | None, cfg) -> str
def handle_callback(engine, conn, cfg, ctx: CallbackContext, now_ms) -> CallbackOutcome
def handle_command(engine, conn, cfg, *, from_user_id, chat_id, chat_type, text, now_ms) -> str | None
class PtbTransport(token: Secret, chat_id: int)          # ChatTransport
def build_application(token, engine, conn, cfg)           # PTB Application(롱 폴링)
```
카드 예시(평문):
```
[PAPER] 롱 신호 · 20일 돌파 (E0-L-ENS)
신호 일봉 2024-03-01 마감 · 판단 2024-03-02 09:01 KST
종가 62,500.0 > 20일 최고 61,800.0 (+1.13%)
ATR20 1,850.0 · 예상 손절(종가 기준) 58,800.0 (−5.92%)
추세 청산: 종가 < 10일 최저(현재 57,900.0)
승인 마감 11:01 KST · 승인 → 60초 안에 [확인]
— Claude(참고, 관문 아님) —
요약: …  / 반대 근거: … / 무효화: … / 의견: 승인 / 메모: …
[승인] [패스] [상세]
```
PTB JobQueue는 쓰지 않는다(APScheduler 미설치). 스케줄은 main의 asyncio 루프.

### 9.7 진입점 (`bot/main.py`)
`python -m bot.main --config PATH {check|run|replay|backup --dest PATH}`. 종료 코드: 0 정상, 2 설정·비밀 오류, 3 DB 모드 불일치.

---

## 10. 테스트 목록

비동기는 `asyncio.run`(pytest-asyncio 없음). 공용 도우미는 `bot/tests/conftest.py`(가짜 전송·가짜 분석가·`FrameMarket`·합성 시장·임시 비밀 파일).

| 파일 | 담당 | 반드시 포함할 시험 |
|---|---|---|
| `test_db.py` ✅ | 설계 | WAL·0600·모드 잠금, 전이표 모양(갇힘 없음, APPROVED 진입로 하나), 멱등 삽입, 전이 성공/불일치/금지/필드 제한, 중복 클릭 첫 번째만, **8스레드 동시 확인 중 하나만 성공**, 감사 로그·스냅샷 추가 전용, payload 가림, 롤백, 버튼 중복, 분석 저장·외래 키, 체결 원자성·N당 1포지션, 청산·펀딩·커서·예약, 플래그, 사이클, 백업 |
| `test_config.py` ✅ | 설계 | 기본 설정·TrendConfig, TOML 로드, 거부 19종(live, 문자열 ID, 그룹 채팅, 상대 경로, 모델·타임아웃·지연 변경 …), 비밀 읽기·거부 7종·값 비노출, 환경 변수 금지, callback 왕복·변형 14종 거부, 시간 도우미, 로그 가림 |
| `test_fixtures.py` ✅ | 설계 | 합성 시장 거래 수, FrameMarket 미래 참조 차단, 가짜 전송 |
| `test_strategy.py` | 핵심 | 잘린 프레임 마지막 값 == 전체 프레임 같은 봉 값(모든 t), ENTRY/EXIT/HOLD/NONE/BUSY 분기, 워밍업 NONE, decision_ns 불일치 거부, 손절·R 분모 == simulate_trend_trade 값, 숏 신호 무시 |
| `test_marketdata.py` | 핵심 | 위 §9.2 + Replay가 until 이후를 절대 안 줌 + 파일 재생 일봉 == load_klines('1d') |
| `test_engine.py` | 핵심 | 사이클 순서(catch_up이 신호 전), 재실행 멱등, 일시정지 SKIPPED, 늦은 시작 SKIPPED, 만료·확인 창 되돌림, Claude 실패해도 카드, 전송 실패 재시도, 판단 시각 전 호출 거부, 시계 오차 보류 |
| `test_telegram_ui.py` | 텔레그램 | 권한 없는 사용자·다른 채팅·그룹·bool ID → 무응답+감사, 위조 callback_data, 중복 callback_query_id, 만료 뒤 클릭, 2단계 승인 흐름, 60초 초과 확인 거부, 명령 5종·그 밖 무시, 평문·URL 제거·길이, 모드 머리표, 토큰이 어떤 출력에도 없음 |
| `test_analyst.py` | Claude | 가짜 SDK: 정상, refusal, max_tokens, 스키마 위반(추가 키·enum 밖·타입), 타임아웃·예외 → 예외 없이 ok=False, 요청 인자(model·effort·format·api_key 명시), 입력에 외부 텍스트 없음, 프롬프트 버전 경로 조작 거부 |
| `test_paper.py` | 모의 매매 | 체결 봉 선택(경계: 정확히 분 경계/1ns 뒤), 체결 봉 손절·갭, 추세 청산이 체결 봉 제외, 손절 우선, 펀딩 창 경계, **tick 주기 무관(1분 vs 하루 1회 결과 동일)**, 원장 합계 일치, 크기 상한, 리포트 |
| `test_parity.py` | 통합 | §3.5 대조(합성 필수, 실데이터 slow) + 자동 승인 없으면 전부 EXPIRED, 재생 중 미래 조회 0건 |
| `backtest/tests/test_random_fair.py` | 기준선 | 같은 거래 수·방향, 전체 기간 균등 추출, 같은 손절·청산, 시드 결정성 |

실행: `.venv/bin/python -m pytest bot/tests -q` (전체 저장소는 `-m "not slow"`).

---

## 11. 운영 파일 (통합 담당) 요구사항 요약
- `Dockerfile`: `python:3.11-slim`(가능하면 digest 고정), `useradd -u 10001 bot`, `USER bot`, `PYTHONDONTWRITEBYTECODE=1`, `pip install --no-cache-dir -r requirements.txt`, `COPY bot/ backtest/*.py` (backtest/results·verify·tests 제외), `ENTRYPOINT ["python","-m","bot.main","--config","/config/bot.toml"]`.
- `docker-compose.yml`: 서비스 1개, `ports` 없음, `secrets:`(file) 3종 → `/run/secrets/…`, `/config/bot.toml` 읽기 전용, `/data` 볼륨, `read_only: true`, `tmpfs: /tmp`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `restart: unless-stopped`, `logging: json-file max-size 10m max-file 5`, `environment`에 비밀 없음(TZ=UTC 정도).
- `.env.example`: 이름만. `bot.example.toml`(값 없는 견본)은 통합 담당이 만든다.
- `docs/RUNBOOK.md`(한국어, 비전문가용): 설치, 비밀 파일 만들기(`chmod 600`), 시작·중지, 긴급정지(`/pause` 또는 `docker compose stop`), 로그 보기, 백업(`main backup`), 복원, 재생 모드 실행.

---

## 12. 결정 기록 (설계 담당, 보수적 해석)

| # | 결정 | 이유 |
|---|---|---|
| B-1 | 확인 창 60초 초과·[취소]는 EXPIRED가 아니라 **CARD_SENT로 되돌림** | 승인 창(2시간) 안에서 다시 누를 수 있게. 되돌림도 원자적 전이·감사 |
| B-2 | 확인 화면에 [취소](`X`) 버튼 추가 | ARCHITECTURE §5.3.2의 동작 코드와 맞춤 |
| B-3 | `/pause`는 NEW·CARD_SENT·CONFIRM_PENDING·**APPROVED(체결 전)**까지 SKIPPED. 열린 포지션 관리는 계속 | "신규 진입 중지"를 가장 넓게, 위험 줄이는 청산은 멈추지 않음 |
| B-4 | 늦게 시작해 승인 창이 이미 지났으면 신호를 만들되 즉시 SKIPPED('late_start') | 기록은 남기고 낡은 신호로 진입하지 않음 |
| B-5 | 추세 청산 지연 = TREND_SPEC의 L=30분(설정 고정) | 명세 문자 그대로, 백테스트와 같은 경로 |
| B-6 | 사람이 패스·만료하면 하위 시스템은 비어 있고, 다음 날 조건이 맞으면 새 신호 | 명세 §1 문자 그대로. 백테스트와의 차이는 §3.6에 명시 |
| B-7 | 테이블 `analyses`·`runtime_flags`·`cycles`·`db_meta`를 6개 필수 테이블에 추가 | Claude 입력·응답 저장, /pause 영속, 사이클 멱등, 모드 혼동 방지 |
| B-8 | 가격은 REAL(10진 문자열 아님) | 백테스트 float와 비트 단위 대조. 실거래 단계에서 재검토 |
| B-9 | 신호 ID는 80비트 base32 16자(ARCHITECTURE 초안 10자보다 김) | 추측 불가 여유. callback 21바이트 ≤ 64 |
| B-10 | 텔레그램 허용 채팅은 양수(개인 채팅)만 | 그룹에 봇이 들어가 다른 사람이 버튼을 보는 경로 차단 |
| B-11 | `claude.max_tokens` 기본 16000 | Opus 5.5는 사고가 항상 켜져 있고 사고 토큰이 max_tokens에 포함(SDK 문서 예시값) |
| B-12 | 설정에서 판단 지연 60초·추세 청산 30분·모델·심볼은 바꿀 수 없음(검증에서 거부) | 백테스트와 다른 경로가 조용히 생기는 것을 막음 |
| B-13 | 도메인 동기 + 텔레그램 비동기, engine은 메시지를 돌려주기만 함 | 테스트 단순, 전송 실패가 상태를 망가뜨리지 않음(전송 성공 뒤에만 CARD_SENT) |
| B-14 | 재생 모드는 비밀을 읽지 않음(가짜 전송·DisabledAnalyst 기본) | 재생 중 실제 외부 호출 차단 |
| B-15 | Docker 이미지에 `backtest/*.py` 포함 | ARCHITECTURE §9 "backtest는 이미지에 넣지 않음"과 다르지만, 리드 결정(같은 코드 경로 재사용)이 우선 |
| B-16 | `/resume`을 텔레그램에서 허용 | 모의 단계는 돈이 움직이지 않음. 실거래 단계에서는 서버 제어 파일로 옮긴다(ARCHITECTURE §5.3.3) |
| B-17 | 검토 반영(수정 담당): 설정의 승인 창·확인 창·시계 오차는 확정값이 **상한**(7200초·60초·1000ms, 줄이는 것만 허용), 시세 호스트는 `https://fapi.binance.com`만 | SECURITY PV-17(설정은 조이는 방향만)·PV-30. 가짜 시세 호스트로 가짜 신호를 만드는 경로 차단(SEC-03) |
| B-18 | `/resume` 텔레그램 허용은 **PAPER 단계의 승인된 예외**로 유지(SECURITY PV-15와 충돌) | 리드 결정 #3이 명령 목록에 /resume을 명시. TESTNET/LIVE 전에 서버 쪽 해제(제어 파일)로 바꾸는 것이 조건(SEC-09) |
| B-19 | 비밀 파일은 그룹·다른 사용자 권한이 하나라도 있으면 거부(400/600만), 이미 있는 DB 파일도 같은 검사 | PV-09. 복원한 백업을 0644로 둔 경우를 시작 때 잡는다(SEC-06) |
| B-20 | 감사 로그 무결성 L1+: 기존 DB를 열 때 보호 트리거 6개(UPDATE·DELETE·REPLACE 차단) 존재 + `COUNT(audit_log) == sqlite_sequence` 확인, 아니면 시작 거부. 감사 payload 값도 패턴 가림 | 트리거를 지우고 행을 지운 뒤 닫으면 다음 연결이 조용히 트리거를 되살리던 틈(SEC-05). 해시 체인(L4)은 TESTNET 전 검토 |
| B-21 | Claude 글 표시: 4자리 이상 숫자 → `(숫자)`, `@`멘션·`#`해시태그·`/`명령 표식 제거 | 카드의 가격은 코드 값만(PV-14/22), 누를 수 있는 요소 없음(SEC-02). ID 표시에는 쓰지 않는다(_safe_token) |
| B-22 | Claude 입력 검사에 키별 엄격 스키마 추가(중첩 키 목록·문자열 자리·항목 수 고정) | 심층 방어(SEC-08). 기존 사유 코드(input_free_text 등)는 그대로 먼저 검사 |
| B-23 | outbox 테이블 추가(SCHEMA_VERSION은 1 유지: `CREATE TABLE IF NOT EXISTS`라 기존 DB에 그대로 더해짐, 배포된 DB 없음) | 카드 아닌 메시지 유실 방지(OPS-3) |
| B-24 | 놓친 판단일 복구는 최대 30일, 처음 실행(DONE 사이클 없음)이면 복구하지 않음 | 1분봉 조회 한도·오래된 판단 재계산의 의미 제한. 넘친 날 수는 감사 'missed_cycles_truncated' |
| B-25 | 추세 청산 예정 시각이 이미 커서 뒤로 지났으면(놓친 날·늦은 사이클) 커서 뒤 첫 봉에 청산하고 감사 'exit_plan_late' | 이미 지난 봉의 펀딩 기록을 되돌리지 않기 위해. 백테스트와의 차이는 기록으로 남긴다(R-1/R-2 보조) |
| B-26 | 감사 로그·설정 스냅샷에 BEFORE INSERT 덮어쓰기 차단 트리거(`*_no_replace`) 추가 + `PRAGMA recursive_triggers = ON`, 보호 트리거 6개. SCHEMA_VERSION 1 유지(배포된 DB 없음 — 이전에 만든 로컬 DB는 새 트리거가 없어 시작 거부되므로 새로 만든다) | REPLACE의 충돌 삭제가 BEFORE DELETE 트리거를 우회하고 행 수·sqlite_sequence도 그대로라 L1+ 검사를 통과하던 틈(V-1) |
