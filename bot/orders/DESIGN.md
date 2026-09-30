# bot/orders/ 설계서 — TESTNET 주문 프로세스(B) v0.1

> 작성: 설계 담당 · 기준: bot/DESIGN.md(모의 운영 봇 v0.1), docs/PLAN.md D6·D7·D8·D14, docs/ARCHITECTURE.md §1.2·§2.2(C11~C13)·§2.3·§2.4·§3.4·§3.5·§5.1·§7, docs/SECURITY.md PV-16·DT-02, research/planning/08_risk_backtest.md §2.5·§3.4, ccxt master `python/ccxt/binance.py`(2026-09-30 조회).
> 이 문서가 **주문 경로의 상태 머신·순서·실패 처리·멱등성·복구·킬 스위치의 기준**이다. 구현이 다르면 문서를 먼저 고치고 §16에 기록한다.
> 설계 담당이 구현·시험한 것: `types.py`, `firewall.py`, `plan.py`, `control.py`, `queue.py`, `tests/conftest.py`, `tests/test_firewall.py`, `tests/test_orders_core.py`.
> 나머지(`binance_client.py`, `fake_exchange.py`, `gateway.py`, `reconcile.py`, `worker.py`)는 시그니처·규칙만 있는 **스텁**이다(`NotImplementedError`).

---

## 0. 범위와 절대 원칙

| 한다 | 하지 않는다 |
|---|---|
| 모드 `testnet` 추가: 바이낸스 **모의 환경**(기본 데모 트레이딩 `demo-fapi.binance.com`)에 실제 서명 주문 | `live` 모드(설정 검증기가 계속 거부), 실서버 호스트 접속(코드 상수로 차단) |
| 진입 = **IOC 상한 지정가** 매수, 보호 손절 = 조건부 STOP_MARKET `closePosition` 매도, 추세 청산 = reduceOnly 시장가 매도 | 순수 시장가 진입, 대기 지정가(GTX+GTD) 진입, 익절 주문(E0-L-ENS에는 목표가가 없다), 분할 진입·청산 |
| 주문 방화벽·주기 대조·킬 스위치 T0·재시작 복구 | 텔레그램에서 주문·청산·해제 명령(승인은 기존 신호 상태 머신뿐) |
| 모든 시험은 **가짜 거래소**(fake_exchange)로 | 이 컨테이너에서 바이낸스 접속(불가) — 실제 확인은 서버 staging의 PoC(§10) |

**절대 원칙** (코드 리뷰의 기준)

1. **fail-closed**: 불확실하면 ① 진입 전이면 주문하지 않는다(REJECTED) ② 노출 뒤면 즉시 reduceOnly 시장가로 청산한다(FAILED_FLATTENED) ③ 청산도 확인할 수 없으면 HALTED + T0 + 경보(사람).
2. **손절 없는 포지션 금지**(I2): 진입 체결 → 손절 **조회 확인**까지 `STOP_DEADLINE_MS`(5초) 안. 넘으면 청산 + T0. 재시작 때 확인 안 된 포지션도 같다.
3. **모든 주문은 방화벽 통과**(§5). 게이트웨이 외의 코드는 `ExchangeClient.place_*`를 부르지 않는다(대조기의 청산도 게이트웨이 함수 경유).
4. **멱등 clientOrderId** `sig-<신호ID>-<용도>`(§6). **진입은 신호당 한 번, 자동 재전송 금지**(I15) — 결과를 모르면 ID로 조회해 판단한다.
5. **거래 키는 B만 파일로 읽는다.** A(분석·텔레그램)에는 키 파일·제어 파일이 마운트되지 않는다(§1).
6. **A→B는 SQLite 큐 테이블**(원자적 전이). B는 A가 쓴 값을 '요청'으로만 본다(다시 읽고 검사).
7. 출금 권한 없는 키를 가정한다(확인 가능하면 검사, K10). 계정 모드·레버리지는 **검사만, 바꾸지 않는다**.

---

## 1. 프로세스 분리

```
┌──────────────── 프로세스 A: bot.main (분석·텔레그램) ───────────────┐      ┌──── 프로세스 B: python -m bot.orders.worker ────┐
│ 비밀: 텔레그램 토큰, Anthropic 키 (거래 키 없음)                    │      │ 비밀: 거래소 API 키 ID + Ed25519 개인키 (파일)   │
│ engine: 일일 사이클 → 신호 카드 → [승인]→[확인] = APPROVED          │      │ 제어 파일(읽기 전용): 수동 정지·T0 해제          │
│   TESTNET: APPROVED 전이와 같은 트랜잭션에서 queue.enqueue → QUEUED │      │ worker 루프(2초):                               │
│   EXIT 판단 → queue.request_exit(보유 의도에 exit_due_ms)           │      │   제어 파일 → 시계 → 대조(30초) → claim → 게이트웨이 │
│   paper.fill_approved/monitor 는 TESTNET에서 쓰지 않는다            │      │ gateway: 사전 점검·방화벽·진입·손절·확인·청산    │
│ telegram_ui: outbox를 보낸다(B의 체결·청산·경고도 여기로)           │      │ reconcile: 거래소 ↔ DB 대조, 불일치 → 경보·정지  │
└──────────────┬──────────────────────────────────────────────────────┘      └──────────────┬──────────────────────────────────┘
               │           같은 SQLite 파일(WAL, /data/testnet.sqlite3)                     │
               └──► signals · order_intents(QUEUED) ─────────────────────► claim(SUBMITTING…) ┘
                    outbox ◄──────────────────── B가 알림 기록(A가 전송) ◄────────────────────┘
```

| 항목 | A (서비스 `bot`, 기존) | B (서비스 `orders`, 신규) |
|---|---|---|
| 진입점 | `python -m bot.main --config /config/bot.toml run` | `python -m bot.orders.worker --config /config/bot.toml` |
| 비밀 파일 | `telegram_bot_token`, `anthropic_api_key` | `binance_api_key`, `binance_ed25519_private_key` (Compose secrets, B에만) |
| 제어 파일 | 없음 | `/control/orders_control.toml` (읽기 전용 마운트) |
| 네트워크 | 텔레그램·Anthropic·바이낸스 공개 시세 | 바이낸스 모의 환경(서명)만 |
| DB 쓰기 | signals·approvals·outbox·…, `order_intents` INSERT(QUEUED)·`cancel_queued`·`request_exit` | `order_intents` 전이, `order_events`·`order_halts`, signals 전이(APPROVED→FILLED/SKIPPED, FILLED→CLOSED), outbox |
| 시작 거부 | TESTNET인데 거래 키 파일이 A에 마운트돼 있으면(설정의 경로에 파일 존재) | mode ≠ testnet, 키 파일 없음·권한 넓음, 호스트가 실서버, 설정이 코드 상한보다 느슨 |

- 두 프로세스가 같은 파일을 쓰므로 테이블 권한을 나눌 수 없다. 그래서 **A가 위조할 수 있는 것**(APPROVED 신호, QUEUED 행, exit 요청, 해제 행)은 B가 이렇게 다룬다:
  - APPROVED 위조 → B의 사전 점검·방화벽이 1회 위험 ≤ r, 명목 ≤ 상한, 롱만, 1포지션으로 묶는다(ARCHITECTURE §1.2와 같은 등급).
  - exit 요청 위조 → 청산은 위험을 줄이는 방향이라 수용(시각만 검사).
  - 해제 위조 → 해제 판정은 **제어 파일만** 본다(`order_halt_releases`는 기록일 뿐).
  - 감사·주문 기록 삭제 → 추가 전용 트리거 + 시작 때 트리거 존재·**본문** 검사(`queue.ensure_schema`) + **매 루프** 무결성 검사
    (`queue.integrity_problems`: 추가 전용 표의 빈 번호·트리거 본문) → T0. 트리거를 지웠다 다시 만들어도 빈 번호가 남는다(R-2).
  - T0 삭제·누적 한도 무력화 → 정지와 한도의 근거를 **B 전용 원장**(`ledger.py`, B만 마운트하는 `/state` 볼륨)에 따로 둔다.
    DB에서 T0 행을 지우고 sqlite_sequence까지 되돌려도 원장의 T0로 정지가 유지된다(R-2, R-4).
  - 보유 의도 상태 위조(예: STOP_VERIFIED → CLOSED) → 대조는 포지션이 0이 아니면 **어떤 보호 손절도 취소하지 않는다**(R-1).
  - DB 쓰기 잠금으로 B를 묶기 → 진입 전송 뒤 보호는 DB 없이도 한다(`emergency_protect`, R-3).
  - 경보 숨기기(outbox 삭제) → **남은 과제**(R-13): B는 T0를 자기 로그(docker logs)에도 남기지만 독립 경보 경로는 없다.

---

## 2. 큐 테이블 스키마 (`bot/orders/queue.py`, 같은 DB에 추가)

| 테이블 | 핵심 열 | 불변식 |
|---|---|---|
| `order_intents` | intent_id, **signal_id UNIQUE**(FK signals), symbol='BTCUSDT', side=1, subsystem_n, atr20·approved_ms(enqueue 때 신호에서 복사), **state**, state_reason, state_version, claimed_ms, mark_price, limit_price, planned_stop, planned_qty, entry_client_id, **entry_sent_ms**, entry_deadline_ms, entry_order_id, filled_qty, avg_fill_price, entry_fill_ms, stop_client_id, stop_price, stop_placed_ms, stop_verified_ms, **unprotected_ms**, stop_attempts, exit_signal_close_ms, exit_due_ms, exit_requested_ms, exit_attempts, exit_sent_ms, flatten_attempts, exit_reason, exit_price, exit_qty, closed_ms, halt_id | 신호당 1행. **노출 가능 상태(INTENT_LIVE) 동시 1행**(부분 고유 인덱스 `ON (symbol) WHERE state IN live`). CHECK: QUEUED면 claimed·sent 없음 / REJECTED면 entry_sent_ms 없음 / NOT_FILLED면 있음 / 보유·CLOSED면 filled_qty>0 / STOP_VERIFIED·EXITING이면 stop_verified_ms / CLOSED·FAILED_FLATTENED면 closed_ms·exit_reason |
| `order_events` | ts_ms, intent_id, kind(REQUEST·RESPONSE·ERROR·QUERY·FIREWALL·RECONCILE·NOTE), client_id, payload_json | **추가 전용**(UPDATE·DELETE·REPLACE 트리거). payload에 서명·키·쿼리 문자열 금지(가림 이중 방어) |
| `order_halts` | halt_id, ts_ms, level='T0', reason(HaltReason), intent_id, detail_json | **추가 전용**. 행이 있고 제어 파일에서 해제되지 않았으면 정지 중 |
| `order_halt_releases` | halt_id UNIQUE, ts_ms, control_ref | 추가 전용. **판정에 쓰지 않는 기록** |
| `order_runtime` | key ∈ {b_heartbeat_ms, last_reconcile_ms, last_reconcile_ok, reconcile_fail_count, b_started_ms, clock_offset_ms} | A의 `/status`가 읽는다(B 생존·대조 상태 표시) |
| (DB 밖) B 전용 원장 `/state/orders_ledger.json` | entries(신호, 전송 시각)·closes(신호, 시각, 사유, 추정 손익)·halts(id, 시각, 사유, 의도)·release_seen(해제 id를 처음 본 시각)·tamper_ok | B만 읽고 쓴다(0600, 원자적 교체). 오류면 신규 진입 차단(`ledger_unavailable`) |

원자적 함수(전부 `BEGIN IMMEDIATE`, 바깥 트랜잭션 합류, 감사 동반):

| 함수 | 누가 | 설명 |
|---|---|---|
| `ensure_schema(conn)` | A·B 시작 | 멱등 생성. 기존 표에 보호 트리거가 빠졌으면 `DbError`(변조 의심) |
| `enqueue(conn, signal_id=, now_ms=)` | A([확인] 전이와 같은 트랜잭션) | APPROVED 롱 신호만(아니면 ValueError), 중복이면 None |
| `cancel_queued(conn, signal_id, now_ms=, reason=)` | A(/pause) | QUEUED→REJECTED. 이미 가져갔으면 False → **신호를 SKIPPED로 바꾸지 말 것** |
| `request_exit(conn, signal_id, exit_signal_close_ms=, exit_due_ms=, now_ms=)` | A(일일 사이클 EXIT) | 보유 상태이고 요청이 없을 때 한 번 |
| `claim_next(conn, now_ms=)` | B | 노출 의도가 없을 때 가장 오래된 QUEUED → SUBMITTING |
| `transition(conn, id, expected, new, now_ms=, reason=, fields=)` | B | INTENT_TRANSITIONS만, INTENT_MUTABLE_FIELDS만. **같은 트랜잭션에서 신호 동기화**(§3.2) |
| `update_fields(conn, id, expected_state, fields, now_ms=)` | B | 상태 유지·열 기록(예: 전송 직전 `entry_sent_ms`) |
| `add_event`, `events_for` | B | 요청·응답·오류·조회·방화벽 판정 기록 |
| `raise_halt(conn, reason=, now_ms=, intent_id=, detail=)` | B | T0 행 + 감사 ALERT + outbox 경고 |
| `active_halt_ids(conn, released)` / `record_release` | B | 해제 판정은 제어 파일의 released 집합 |
| `notify(conn, text, now_ms=)` | B | outbox에 `[TESTNET]` 알림(A가 전송) |

---

## 3. 주문 의도 상태 머신 (`types.IntentState`, `INTENT_TRANSITIONS`)

```
 A: [확인] ─► QUEUED ──claim──► SUBMITTING ──체결>0──► ENTRY_FILLED ──손절 접수──► STOP_PLACED ──조회 대조 OK──► STOP_VERIFIED
                │                  │  │  │                   │                         │                          │   │   │
                │(/pause·낡음·정지) │  │  └─체결 0 확정──► NOT_FILLED                  │                          │   │   └─추세 청산 요청 시각─► EXITING ─포지션 0─► CLOSED
                ▼                  │  └─(K1 선배치: 손절 먼저, 체결>0)──► STOP_PLACED   │                          │   └─손절 발동(포지션 0)──────────────────────────► CLOSED
             REJECTED ◄─진입 전 거부┘                                                 │                          └─대조: 손절 누락·불일치─► FAILED_FLATTENED
                                                         손절 등록·확인 실패 ─────────┴──► reduceOnly 시장가 청산 확인 ──► FAILED_FLATTENED (+T0)
                                    어느 단계든 결과 확정 불가(청산 실패·조회 불가 지속) ──────────────────────────────► HALTED (+T0, 사람)
```

### 3.1 전이표

| 전이 | 조건 | 기록 |
|---|---|---|
| QUEUED → SUBMITTING | `claim_next`: 노출 의도 없음 | claimed_ms |
| QUEUED → REJECTED | A의 `cancel_queued`(/pause), B: T0 정지 중·낡은 승인(`approved_ms + claim_max_age < now`) | reason |
| SUBMITTING → REJECTED | 사전 점검 실패, 계획 불가(최소 수량·명목), 방화벽 거부 — **진입 전송 전** | reason, (방화벽이면 T0) |
| SUBMITTING → NOT_FILLED | 진입을 보냈고 체결 0 확정(IOC 만료·확정 거부·도착 기한 경과 후 조회 없음) | entry_order_id, reason |
| SUBMITTING → ENTRY_FILLED | 체결 수량 > 0 확정(부분 체결 포함) | filled_qty, avg_fill_price, entry_fill_ms |
| SUBMITTING → STOP_PLACED | K1 선배치 경로: 손절이 이미 있고 체결 > 0 | 위 + stop_* |
| ENTRY_FILLED → STOP_PLACED | 손절 접수(응답 또는 같은 ID 조회) | stop_client_id, stop_price, stop_placed_ms |
| ENTRY_FILLED/STOP_PLACED → STOP_VERIFIED | 조회 대조 통과(§4.4), 체결 뒤 5초 안 | stop_verified_ms, unprotected_ms |
| ENTRY_FILLED/STOP_PLACED → CLOSED | 손절 확인 전에 포지션이 이미 0(손절 즉시 발동 등)이고 청산 확인 | exit_reason, closed_ms |
| STOP_VERIFIED → EXITING | `now ≥ exit_due_ms` | exit_sent_ms, exit_attempts |
| STOP_VERIFIED → CLOSED | 대조: 포지션 0 + 손절 발동 확인 | exit_reason='stop', exit_price(체결 조회), closed_ms |
| EXITING → CLOSED | 포지션 0 확인 + 남은 손절 취소 | exit_reason='trend' |
| * → FAILED_FLATTENED | 노출 뒤 실패 → 비상 청산 후 포지션 0 확인 | exit_reason='flatten'/'stop_immediate', halt_id |
| * → HALTED | 청산 실패·확정 불가 | halt_id |
| HALTED → CLOSED/FAILED_FLATTENED | 사람이 서버에서 처리(제어 파일 해제) 뒤 대조기가 거래소 사실(포지션 0)을 기록 | — |

종료: CLOSED, REJECTED, NOT_FILLED, FAILED_FLATTENED. HALTED는 종료가 아니다(노출 가능 상태로 세어 새 claim을 막는다).

### 3.2 신호 상태 동기화 (`queue.transition`이 같은 트랜잭션에서)

| 의도 새 상태 | 신호 목표 | 경로 |
|---|---|---|
| ENTRY_FILLED, STOP_VERIFIED, EXITING, (체결 있는) STOP_PLACED | FILLED | APPROVED→FILLED |
| CLOSED, FAILED_FLATTENED | CLOSED | APPROVED→FILLED→CLOSED 또는 FILLED→CLOSED |
| REJECTED, NOT_FILLED | SKIPPED | APPROVED→SKIPPED (reason `order:<사유>`) |
| QUEUED, SUBMITTING, HALTED | 그대로 | — |

신호가 예상 상태가 아니면(A가 먼저 바꿈·위조) **의도 전이는 되돌리지 않고** 감사 ALERT `signal_state_mismatch`만 남긴다(거래소 사실이 우선). 신호 쪽 actor = `ORDER_GATEWAY`. TESTNET에서는 `paper_positions`를 쓰지 않는다(보유 표시·리포트는 `order_intents`에서).

---

## 4. 주문 순서 (`gateway.process_intent`) 와 단계별 실패 처리

한 의도를 **한 번의 호출 안에서** SUBMITTING → (STOP_VERIFIED | 종료)까지 끌고 간다(손절 없는 구간을 워커 루프 주기에 맡기지 않는다). 모든 거래소 호출 전후로 `order_events`에 REQUEST/RESPONSE/ERROR를 남긴다.

### 4.1 단계

| # | 단계 | 내용 | 실패하면 |
|---|---|---|---|
| 0 | 가져가기 | worker: T0·수동 정지 중이면 QUEUED 전부 REJECTED('halted'). 아니면 `claim_next` | — |
| 1 | 의도·신호 재확인 | signals 재조회: state=APPROVED, side=1, atr20>0 유한, `approved_ms` 같음, `now − approved_ms ≤ claim_max_age_ms`(5분) | REJECTED(`signal_mismatch`/`stale_approval`) |
| 2 | 시계 | `server_time_ms` − 로컬 ≤ 1000ms | REJECTED + **T0** `clock_skew` |
| 3 | **계정 모드 확인** | `account_config`: dualSidePosition=false(One-way), multiAssetsMargin=false(Single-Asset), canTrade, 출금 권한(알 수 있으면 false) | REJECTED + **T0** `account_mode` |
| 4 | **레버리지·마진 확인** | 심볼 레버리지 == `expected_leverage`(≤3), marginType=isolated. **바꾸지 않는다** | REJECTED + **T0** `leverage_margin` |
| 5 | 심볼 규칙 | exchangeInfo: tick 0.1·step 0.001·TRADING | REJECTED + **T0** `symbol_rules` |
| 6 | 상태 사전 조건 | 포지션 0, 미체결 일반 주문 0, 조건부 주문 0 | 모르는 것 발견 → REJECTED + **T0** `unknown_order`/`unknown_position` |
| 7 | 계획 | `plan.plan_entry(mark, atr20, cfg, rules)` → 상한가·계획 손절·수량(내림) | 최소 수량·명목 미달 → REJECTED(`below_min_qty`…) **T0 없음** |
| 8 | 방화벽(진입) | `firewall.enforce_order(req, ENTRY, ctx)` | REJECTED + **T0** `firewall` |
| 8′ | (K1 선배치 경로만) 손절 먼저 | 상한가 기준 계획 손절로 `sig-…-sl` 등록 → 조회 대조 | 실패 → 손절 취소 → REJECTED + T0 `stop_not_verified` |
| 9 | **진입 전송 기록** | `update_fields(entry_client_id, entry_sent_ms, entry_deadline_ms=서명 timestamp+5000, mark_price, limit_price, planned_stop, planned_qty)` **커밋 후** 전송 | 기록 실패 → 전송하지 않음(REJECTED) |
| 10 | **진입** | `place_order(LIMIT BUY IOC, qty, price=상한가, newClientOrderId=sig-…-e1, newOrderRespType=RESULT)` | §4.3 결과 판정 |
| 11 | **손절 등록** | 체결 평균가 기준 `stop = plan.stop_for_fill(avg, atr20)`; `trigger ≥ mark`면 즉시 발동 가격 → 12′. 방화벽(손절) → `place_conditional(STOP_MARKET SELL closePosition MARK_PRICE priceProtect=false, sig-…-sl)` | §4.4 |
| 12 | **손절 존재 대조** | `open_conditional_orders()`(+`get_conditional(sl)`)에서 같은 ID·SELL·STOP_MARKET·closePosition·triggerPrice == stop(틱 일치)·MARK_PRICE·priceProtect=false·status NEW, 그리고 포지션 > 0 | 실패 → 12′ |
| 12′ | **실패 시 청산 + T0** | `flatten(intent, reason)`: 포지션 수량(거래소 조회) reduceOnly 시장가 `sig-…-f1..f3` → 포지션 0 확인 → 남은 sl 취소 → FAILED_FLATTENED + **T0** | 3회 실패·확인 불가 → HALTED + T0 `flatten_failed` + P1 경보 |
| 13 | 완료 | STOP_VERIFIED, `unprotected_ms = stop_verified_ms − entry_fill_ms`, 체결 알림(outbox) | — |

전체 12단계까지(체결 → 확인)가 `stop_deadline_ms`(5초)를 넘으면 12′(`unprotected_timeout`).

### 4.2 계획 (plan.py, 순수 함수)

- 상한가 `L = ceil_tick(mark × (1 + ioc_cap_bps/10⁴))` (기본 10bp, 상한 30bp). 계획 손절 `S_L = strategy.protective_stop(L, atr20)`(= round_price(L − 2×ATR20)).
- R 분모 `rpu = strategy.risk_per_unit(L, S_L)`(수수료·슬리피지 포함, 백테스트와 같은 식).
- 수량 `qty = floor_step(min(R자본 × r ÷ rpu, min(R자본×0.2, max_notional, 절대 명목) ÷ L, 절대 수량), 0.001)`.
- **실제 손절은 체결 평균가 기준** `stop_for_fill(avg, atr20)`(모의 매매·백테스트와 같은 뜻). 상한가 ≥ 체결가라 실제 위험 ≤ 계획 위험.

### 4.3 진입 결과 판정

| 응답 | 판정 |
|---|---|
| 정상 응답, `executedQty > 0` (FILLED 또는 IOC 부분 체결 후 EXPIRED) | ENTRY_FILLED(체결 수량·평균가). 부분 체결도 closePosition 손절이 전체를 덮는다 |
| 정상 응답, `executedQty == 0` (EXPIRED) | NOT_FILLED(`entry_not_filled`) → 신호 SKIPPED. 선배치 손절이 있으면 취소 |
| 확정 거부(ErrorPolicy.outcome_unknown = False): -2019·-4164·-1021·-4400·-4061·400대 | NOT_FILLED(주문 없음 확정). `halt`인 오류(-2019·-1021·-4061·-4400·AUTH·BAD_REQUEST·418·451)는 **T0** |
| 결과 모름(타임아웃·연결 끊김·5xx·-1007·-4116 중복 ID) | **재전송 금지.** `get_order(sig-…-e1)` 조회를 백오프(0.5·1·2·4초)로 반복: 찾으면 그 상태로 판정. 없으면 `position()`도 본다(포지션 > 0이면 체결로 간주, 수량·평균가는 포지션 값). **서버 시각이 `entry_deadline_ms + UNKNOWN_GRACE_MS`를 넘었는데도 주문·포지션 둘 다 없으면** 거래소가 받지 않은 것으로 확정 → NOT_FILLED. 조회 자체가 계속 실패해 확정 못 하면(30초) **HALTED + T0** `outcome_unresolved` |

근거: 바이낸스는 `timestamp + recvWindow`보다 늦게 도착한 서명 요청을 거부한다 → 도착 기한이 지난 뒤 조회에 없는 IOC 주문은 **앞으로도 체결될 수 없다**(IOC는 접수 즉시 끝나므로 '접수됐는데 조회가 늦게 보이는' 창만 GRACE로 덮는다 — K12에서 조회 지연 실측).

### 4.4 손절 등록·확인

- 시도: 최대 `STOP_PLACE_ATTEMPTS`(3)회, **같은 clientAlgoId `sig-…-sl`**. 매 재시도 전에 `get_conditional(sl)`로 이미 접수됐는지 먼저 본다(중복 등록 방지. closePosition 손절이 둘이어도 반대 포지션을 열 수는 없지만 대조가 복잡해진다).
- 오류별: 결과 모름 → 조회 후 판단 / `-2021`(즉시 발동) → 시장이 이미 손절가 아래 → 즉시 청산(FAILED_FLATTENED, exit_reason `stop_immediate`, **T0 없음** — 시장 사건) / `-4120`(algo 창구 필요) → 청산 + **T0** `algo_endpoint` / 그 밖 확정 거부 → 다음 시도, 소진 시 청산 + T0 `stop_not_verified`.
- 대조 항목(모두 일치해야 STOP_VERIFIED): client_algo_id, symbol, side=SELL, type=STOP_MARKET, close_position=True, trigger_price == stop(틱 단위 정확히), working_type=MARK_PRICE, price_protect=False, status=NEW, 그리고 포지션 qty > 0(롱). 트리거 가격이 다르면(옛 파라미터 이름 `stopPrice`를 algo 창구가 무시하는 등 — 08 §2.5) **불일치 = 실패**.

### 4.5 비상 청산 (`gateway.flatten`)

1. `position()` 조회(DB 수량을 믿지 않는다). 0이면 3으로.
2. 방화벽(FLATTEN) → `place_order(MARKET SELL reduceOnly qty=포지션, sig-…-f{n})`. reduceOnly라 **재시도해도 노출이 늘지 않는다** → 결과 모름이면 조회 후 다음 번호(f2, f3)로 재시도 가능(최대 3).
3. 포지션 0 확인 → 남은 조건부·일반 주문(이 신호의 sl 등) 취소 → FAILED_FLATTENED(+T0) 또는 (정상 청산 경로면) CLOSED.
4. 3회 후에도 포지션 > 0이거나 조회 불가 → HALTED + T0 `flatten_failed` + 경보 "거래소 웹에서 수동 청산"(RUNBOOK).

### 4.6 추세 청산 (자동, 사람 승인 없음 — 모의 운영과 같은 규칙)

- A의 일일 사이클이 보유 하위 시스템에 EXIT를 내면 `queue.request_exit(exit_due_ms = 판단 + 30분)`.
- B: `now ≥ exit_due_ms`이고 STOP_VERIFIED면 → EXITING → 방화벽(EXIT) → reduceOnly 시장가 `sig-…-x1`(결과 모름이면 조회 후 x2·x3) → 포지션 0 확인 → sl 취소 → CLOSED(`trend`).
- 손절이 먼저 발동해 포지션이 이미 0이면 CLOSED(`stop`), 청산 주문은 reduceOnly라 `-2022`로 거부될 뿐 반대 포지션을 열지 않는다.
- 3회 실패 → 손절은 남아 있으므로 T0 + 경보(`EXITING` 유지, 대조가 계속 손절 존재를 본다). 손절까지 없으면 flatten.

### 4.7 손절 발동 감지 (대조기)

보유 의도가 STOP_VERIFIED인데 포지션 0 → `get_conditional(sl)` 상태가 TRIGGERED/FINISHED면 CLOSED(`stop`), 체결가는 조건부 주문이 만든 주문 조회(K5: algo → 실제 주문 ID 연결 방법)로 채우고 없으면 None. sl이 CANCELED/없음이면 **우리가 모르는 청산** → CLOSED(`external`) + T0 `position_vanished`.

---

## 5. 주문 방화벽 (`firewall.py`, 구현 완료)

순수 함수. 같은 루프의 거래소 조회값(FirewallContext)으로만 판정. 위반 하나라도 있으면 전송 금지. 코드 상수(①층)가 설정보다 강하다.

| # | 항목 (PV-16) | 진입 | 손절 | 추세·비상 청산 |
|---|---|---|---|---|
| 1 | 모드 = 키 환경: 클라이언트 주소 https + 설정 env의 호스트, 실서버 호스트 금지 | ✔ | ✔ | ✔ |
| 2 | 심볼 = BTCUSDT | ✔ | ✔ | ✔ |
| 3 | clientOrderId = `sig-<이 의도의 신호>-<용도>` (진입 e1, 손절 sl, 청산 x1~3, 비상 f1~3) | ✔ | ✔ | ✔ |
| 4 | 방향: 진입 BUY(롱만) / 손절·청산 SELL | ✔ | ✔ | ✔ |
| 5 | 형식: 진입 LIMIT+IOC(시장가·GTC·GTX 금지), reduceOnly 아님 / 손절 STOP_MARKET+closePosition+MARK_PRICE+priceProtect=false / 청산 MARKET+reduceOnly | ✔ | ✔ | ✔ |
| 6 | 계정: One-way·Single-Asset·canTrade·출금 권한 없음(모르면 통과, K10)·레버리지 == 설정 ≤ 3·격리 | ✔ | — | — |
| 7 | 심볼 규칙: tick 0.1·step 0.001·TRADING | ✔ | — | — |
| 8 | 정지(T0·수동) 아님, 신호당 진입 한 번(entry_sent 없음), 포지션 0·미체결 0 | ✔ | — | — |
| 9 | 수량: 양수·step 배수·≥ minQty·≤ 절대 0.2 BTC | ✔ | — | 양수·step·≤ 포지션 |
| 10 | 가격: tick 배수, 마크 ≤ 상한가 ≤ min(마크×(1+cap)+1틱, 마크×1.01) | ✔ | 트리거 tick·< 마크 | — |
| 11 | 명목 ≤ min(설정, 절대 10,000 USDT, R자본×0.2), ≥ minNotional | ✔ | — | — |
| 12 | 손절 계획 있음(I1), 거리 0.2%~25%, 위험 qty×(L−S) ≤ R자본×min(r, 1%) | ✔ | 트리거 == 계획 손절, 거리 ≤ 25% | — |
| 13 | 잔고: USDT 가용 ≥ 명목÷레버리지×1.02 | ✔ | — | — |
| 14 | 포지션: 롱 > 0 (선배치 경로의 손절만 0 허용) | — | ✔ | ✔ |

**위험을 줄이는 주문은 정지·계정 모드·잔고로 막지 않는다**(막으면 손절 없는 포지션이 남는다). 진입 거부는 정상 운영에서 생기지 않아야 하므로 **T0**를 건다.

---

## 6. 멱등성

| 층 | 방법 |
|---|---|
| 신호 → 의도 | `order_intents.signal_id UNIQUE`, `enqueue`는 중복이면 None |
| 가져가기 | `claim_next`: `UPDATE … WHERE state='QUEUED'` 한 문장 + 노출 의도 1개 인덱스 → 두 워커가 떠도 하나만 |
| 진입 1회 | `entry_sent_ms`를 **전송 전에 커밋**. 재시작 때 이 값이 있으면 절대 다시 보내지 않고 `get_order(e1)`·`position()`으로만 판단. 방화벽 FW-ENTRY-ONCE |
| 주문 ID | `sig-<신호ID 16자>-<용도>`(23자 ≤ 36, `^[.A-Z:/a-z0-9_-]{1,36}$`). 거래소의 ID 중복 방지는 **미체결 사이에서만**이라(ARCHITECTURE §5.1.3) DB 상태가 1차 방어 |
| 손절 | 같은 `sig-…-sl`로 재시도, 재시도 전 조회 |
| 청산 | reduceOnly라 중복돼도 노출 증가 없음. 번호(x1~3, f1~3)로 시도 구분 |
| 전이 | 모든 의도 전이는 `WHERE state IN (기대값)`. 실패(False)면 다른 주체가 먼저 바꾼 것 → 다시 읽고 판단 |

---

## 7. 킬 스위치 T0

### 7.1 조건 (`types.HaltReason`)

손절 등록·확인 실패(`stop_not_verified`), 체결 뒤 5초 안 미확인(`unprotected_timeout`), 보유 중 손절 누락·불일치(`stop_missing`), -4120(`algo_endpoint`), 계정 모드(`account_mode`), 레버리지·마진(`leverage_margin`), 심볼 규칙 변경(`symbol_rules`), 시계 오차 > 1초·-1021(`clock_skew`), 418·451·403(`exchange_block`), 키 거부(`auth`), -4400(`trading_restricted`), `sig-`가 아니거나 활성 의도와 맞지 않는 주문(`unknown_order`), DB에 없는 포지션(`unknown_position`), 수량·방향 불일치(`position_mismatch`), 잔고 부족·불일치(`balance_mismatch`), 청산 실패(`flatten_failed`), 결과 확정 불가(`outcome_unresolved`), 연속 3회 대조 실패(`reconcile_unavailable`), 재시작 때 미확인 포지션(`restart_unprotected`), 우리 청산 없이 포지션 사라짐(`position_vanished`), 방화벽 거부(`firewall`), 그 밖 ErrorPolicy.halt 오류(`order_error`), 제어 파일 `halt = true`·읽기 실패(`operator`, 행은 만들지 않고 파일 상태로 판정).

### 7.2 효과

- 신규 진입 차단: QUEUED는 즉시 REJECTED('halted') → 신호 SKIPPED. claim 안 함.
- **기존 손절은 유지**, 대조는 계속(손절 누락이면 청산은 여전히 한다). 추세 청산도 계속한다(위험을 줄이는 방향).
- 경보: outbox `[TESTNET] 킬 스위치 T0 #id: 사유 …`(A가 전송). 정지 중 매 대조마다 경보하지 않는다(사유·id당 1회).

### 7.4 누적 한도(T1·T2·하루 진입 수) — B가 따로 센다 (R-4)

ARCHITECTURE §2.3: B는 T1~T5를 A가 쓴 값에 기대지 않고 계산한다. 이번 단계는 T1·T2와 하루 진입 수 상한만(T3~T5는 다음 단계).

| 한도 | 조건(코드 상수, `types.py`) | 근거 데이터 | 해제 |
|---|---|---|---|
| 하루 진입 수 | UTC 하루 진입 전송 ≥ `MAX_ENTRIES_PER_UTC_DAY`(3) | B 원장 entries(전송 **전에** 기록, 못 쓰면 보내지 않음) ∪ DB entry_sent_ms | 다음 UTC 00:00 |
| T1 | 24시간 안 손절(stop·stop_immediate) `T1_STOPS`(3)번 | B 원장 closes ∪ DB의 끝난 의도 | 3번째 손절 다음 UTC 00:00 |
| T2 | UTC 하루 실현 손익 ≤ −min(3R, R 자본의 3%) | 같음. 손익 = (청산가 − 체결가)×수량 − 수수료 0.05%×2, 청산가 모르면 손절가(손절 사유) 또는 −1R | 다음 UTC 00:00 |

- 걸리면 `block_reason`이 그 이름을 돌려주고, QUEUED는 그 사유로 REJECTED, 경보는 (사유, UTC 날)당 1회. T0 행은 만들지 않는다(자동 해제).
- 원장 ∪ DB: A가 DB 기록을 지우면 원장이 세고, A가 DB에 가짜 기록을 더하면 **더 막힐 뿐**이다(fail-closed).
- 거래소 손익 내역(`/fapi/v1/income`)으로 세는 것은 K16(PoC 확인 필요) — 확인 전에는 원장의 추정 손익.

### 7.3 해제 — 서버에서만

사람이 원인을 고친 뒤 제어 파일(B에만 읽기 전용 마운트)에 `[[release]] halt_id = N, at = "지금(UTC)", reason = "…"`를 적는다.
**해제는 그 T0에 묶인다(R-8)**: B는 해제 id를 그 T0(DB ∪ B 원장)가 생긴 **뒤에 처음 본** 경우에만 인정하고(처음 본 시각은 B 원장에
남아 재시작에도 유지), `at`이 T0 시각보다 60초 넘게 이르면 무시한다. DB 복원·재생성으로 같은 번호가 다시 쓰여도 옛 해제가 새 T0를 풀지 못한다. B는 매 루프 파일을 읽고(권한 0644 이하·그룹·기타 쓰기 금지, 형식 오류·파일 없음 = 수동 정지로 간주) 해제된 id를 `order_halt_releases`에 기록한다. **텔레그램으로는 해제 불가**(I14). A의 `/resume`은 A의 신규 신호 일시정지만 풀며 T0에는 영향이 없다(B-18 조건 이행: TESTNET에서 T0 해제는 제어 파일).

---

## 8. 재시작 복구 (`worker.recover`) — B가 새 의도를 가져가기 전에 반드시

1. `ensure_schema`(보호 트리거 검사) → 제어 파일 → 시계(오차 > 1초면 T0, 복구는 조회만 계속).
2. 노출 가능 의도(INTENT_LIVE)마다 **거래소 사실**로 판정:

| DB 상태 | 거래소 조회 | 처리 |
|---|---|---|
| SUBMITTING, `entry_sent_ms` 없음 | — | 아무것도 보내지 않았다(선배치 손절 `sl`이 있으면 취소) → REJECTED(`restart_before_send`) |
| SUBMITTING, `entry_sent_ms` 있음 | `get_order(e1)`, `position()` | §4.3 결과 모름 절차 그대로. 체결 > 0이면 ENTRY_FILLED로 기록한 뒤 아래 행 |
| ENTRY_FILLED / STOP_PLACED | `get_conditional(sl)` + 포지션 | 손절이 대조 통과 → STOP_VERIFIED(unprotected_ms = 확인 − 체결, 5초 초과면 기록·경보 — 이미 보호됨). **손절 없음 → 즉시 청산 + T0 `restart_unprotected`**(새로 손절을 거는 대신 청산: 체결 뒤 5초 규칙 I2) |
| STOP_VERIFIED | 대조 1회(§9) | 정상 계속 |
| EXITING | 포지션, `x*` 조회 | 포지션 0 → sl 취소 → CLOSED(`trend`). 포지션 > 0 → 다음 번호로 reduceOnly 재시도(§4.6) |
| HALTED | 대조 1회 | 자동 처리 없음. 살아 있는 우리 손절이 있으면 대기. 없으면 **새 비상 청산 주기**(f1~f3 재사용), 청산이 안 되면 **보호 손절을 다시 건다**(R-5). 같은 사유 T0는 반복하지 않는다 |

3. 노출 의도가 없는데 거래소 포지션 ≠ 0 또는 우리 것이 아닌 주문 → §9 불일치 처리(청산·취소 + T0).
4. QUEUED 중 `approved_ms + claim_max_age_ms < now`는 REJECTED(`stale_approval`) — 재시작이 길었으면 낡은 승인으로 진입하지 않는다.
5. 복구 결과를 outbox로 요약 알림.

강제 종료 지점별 안전성(시험 대상, §15 E2E):
- 전송 기록 전 종료 → 주문 없음 → REJECTED.
- 전송 기록 후·응답 전 종료 → 조회로 확정(체결이면 손절 확인 → 없으면 청산+T0).
- 체결 후·손절 전 종료 → 재시작 때 손절 없음 → 청산 + T0 (그동안의 무방비 구간은 짧게 유지되도록 compose `restart: unless-stopped`, 그리고 K1 선배치 경로가 확인되면 이 구간 자체가 사라진다).
- 손절 확인 후 종료 → 보유 계속(거래소 손절이 보호).

---

## 9. 대조 (`reconcile.reconcile_once`) — 주기 `reconcile_interval_s`(기본·상한 30초)

한 번에 조회: 서버 시각, 포지션, 미체결 일반 주문, 조건부 주문(+ 필요 시 잔고). 마크 가격은 실패해도 None으로 계속(R-9).
조회 실패는 `reconcile_fail_count` 증가, 3회 연속이면 T0 `reconcile_unavailable`. 묶음 조회가 실패해도 노출 의도는 **자체 조회로**
확인한다(R-9): SUBMITTING → 결과 모름 절차, ENTRY_FILLED·STOP_PLACED → 손절 확인(없으면 청산), STOP_VERIFIED → 손절·포지션 조회
(손절 없음이면 청산 + T0), HALTED → secure_halted. 대조 주기 사이에도 STOP_VERIFIED면 매 바퀴 `get_conditional(sl)`로 손절 존재를
가볍게 보고, 없으면 대조를 앞당긴다(R-11 — 사라진 손절의 무방비가 30초가 아니라 루프 주기로 묶인다).

| 불일치 | 처리 |
|---|---|
| 노출 의도 없음 + 포지션 ≠ 0 | 먼저 최근 NOT_FILLED 의도의 e1을 조회: 체결돼 있으면 **우리 늦은 체결** → 비상 청산(안 되면 손절) + T0 `unknown_position`(R-7). 아니면 모르는 포지션 → **청산하지 않고 T0 `unknown_position` + 경보**(사람이 거래소 웹에서 확인·정리, RUNBOOK). 결정 O-11 |
| 보유 의도 + 포지션 0 | §4.7 손절 발동 감지 → CLOSED(stop) 또는 CLOSED(external)+T0 |
| 보유 의도 + 포지션 수량 ≠ filled_qty(±1 step) 또는 숏 | T0 `position_mismatch` + 경보. 손절(closePosition)은 수량과 무관하게 전체를 덮으므로 청산은 손절 누락일 때만 |
| STOP_VERIFIED + sl 없음·불일치 | **즉시 청산 + T0** `stop_missing` → FAILED_FLATTENED |
| `sig-`가 아닌 주문, 또는 다른 신호 ID의 주문 | 일반 주문은 **취소**(열린 진입이 무방비 체결될 수 있으므로) + T0 `unknown_order`. 조건부 주문 중 closePosition·reduceOnly 매도는 위험을 줄이므로 취소하지 않고 T0만 |
| 끝난 의도의 남은 sl(고아) | **포지션 0일 때만** 취소(경보 없음, 기록만). 포지션이 있으면 **그대로 두고** T0 `position_mismatch`(`terminal_intent_stop_with_position` — DB 위조 의심, R-1) |
| 서버 시각 오차 > 1초 | T0 `clock_skew` |

결과는 `order_runtime.last_reconcile_ms / last_reconcile_ok`에 기록(A의 /status 표시, 데드맨 핑 조건에 포함 — 통합 담당).

---

## 10. PoC 확인 항목(K)과 두 경로 설계

이 컨테이너는 바이낸스에 접속할 수 없다. 아래는 서버 staging에서 데모 키로 확인한다(RUNBOOK 테스트넷 절차). **확인 전 기본값은 항상 보수적인 쪽**이다.

| K | 확인할 것 | 가능(확인됨)일 때 | 불가능·미확인(기본) |
|---|---|---|---|
| K1 | 포지션 0일 때 closePosition STOP_MARKET을 **미리** 걸 수 있는가, 포지션 종료 시 자동 취소되는가 | `stop_placement = "pre_entry"`: 손절 선배치·대조 → IOC 진입 → 체결 즉시 STOP_PLACED(무방비 0초). 미체결이면 손절 취소 | `"post_fill"`: 진입 → 손절 → 대조(무방비 ≤ 5초). **기본** |
| K2 | 조건부 주문 창구: algo(`POST /fapi/v1/algoOrder`, `algoType=CONDITIONAL`, `triggerPrice`, `clientAlgoId`) vs 옛 창구(`POST /fapi/v1/order` `type=STOP_MARKET`, `stopPrice`) | `conditional_api = "legacy"`(데모에서 옛 창구가 정상일 때만) | `"algo"` **기본**. 옛 창구에서 -4120 → 청산 + T0(실행 중 자동 전환 금지) |
| K3 | 모의 환경 호스트: 데모(`demo-fapi.binance.com`) vs 구 테스트넷(`testnet.binancefuture.com`) — ccxt master는 선물 sandbox를 '지원 종료, demo trading 사용'으로 표시 | `env = "testnet"` | `env = "demo"` **기본** |
| K4 | algo 주문 요청의 필드 이름(`type` vs `orderType`, `priceProtect` 값 `TRUE/FALSE` 대소문자, `closePosition` 문자열) | — | binance_client가 ccxt 매핑을 따르고, **응답의 triggerPrice·closePosition·workingType을 대조**(§4.4)해 무시된 필드를 잡는다 |
| K5 | algo 주문 상태 값·전이(NEW/TRIGGERING/TRIGGERED/FINISHED/CANCELED/EXPIRED/REJECTED), 발동 뒤 만들어진 실제 주문 ID·체결가 연결, 종료된 algo 주문 조회 가능 기간 | 체결가를 CLOSED에 기록 | 체결가 None으로 CLOSED(stop), 경보 없음 |
| K6 | IOC 부분 체결 시 응답 `status`(EXPIRED + executedQty>0) | — | executedQty만 믿는다(상태 이름 무관) |
| K7 | `priceProtect=false` 허용 여부 | — | 거부되면 손절 등록 실패 → 청산 + T0 (true로 바꾸는 것은 결정 필요) |
| K8 | 심볼 레버리지·마진 조회 엔드포인트(`GET /fapi/v1/symbolConfig` vs `positionRisk v2/v3`) | — | 둘 다 시도, 둘 다 실패면 T0(`leverage_margin`) |
| K9 | 데모에서 `positionSide/dual`·`multiAssetsMargin` 조회 지원 | — | 조회 실패 = 모름 = REJECTED + T0 |
| K10 | 키 권한(출금 꺼짐) 조회: `GET /sapi/v1/account/apiRestrictions`는 현물 API라 데모 선물 키에서 안 될 수 있음 | `can_withdraw=False` 검사 | None(모름) 허용 — **LIVE 전에는 반드시 확인**(LIVE 설계의 선행 조건) |
| K11 | BTCUSDT 최소 수량·최소 명목(-4164 문구상 5~20 USDT) | — | exchangeInfo 값을 그대로 쓰고 미달이면 REJECTED |
| K12 | 주문 접수 → 조회에 보이기까지 지연(결과 모름 판정 GRACE 2초의 근거) | GRACE 조정 | 2초 |
| K13 | `countdownCancelAll`이 algo 손절도 지우는가 | — | **쓰지 않는다**(IOC라 걸어 둔 진입이 없어 필요 없음) |
| K14 | 폐쇄된 포지션의 closePosition 손절이 자동 취소되는가(추세 청산 뒤 고아 손절) | 취소 단계 생략 가능 | 청산 뒤 **항상 명시적으로 취소**(없으면 ORDER_NOT_FOUND = 성공 취급) |
| K15 | 끝난 시장가 주문의 clientOrderId 재사용(비상 청산 f1~f3을 다음 주기에 다시 씀) | 그대로 | 거부(-4116)면 다음 번호. reduceOnly라 중복돼도 노출이 늘지 않는다 |
| K16 | 손익 내역(`GET /fapi/v1/income` REALIZED_PNL)으로 T2 계산 | 거래소 사실로 T2 | B 원장의 추정 손익(§7.4) |

설정 전환 규칙: K 결과로 바꾸는 값(`stop_placement`, `conditional_api`, `env`)은 서버 설정(③층)에서만, 바꿀 때 RUNBOOK의 PoC 기록 칸에 날짜·결과를 적는다. 텔레그램으로는 바꿀 수 없다.

---

## 11. 바이낸스 클라이언트 규격 (`binance_client.py`, 거래소 클라이언트 담당)

- **서명: Ed25519만**(HMAC·RSA 미지원). 개인키 PEM(PKCS#8)을 `bot.config.read_secret`과 같은 검사(절대 경로·일반 파일·0400/0600·크기)로 읽고 `cryptography`의 `Ed25519PrivateKey`로 로드. 서명 대상 = 요청 쿼리 문자열(`urlencode(params + timestamp + recvWindow)` 순서 그대로), `signature = urlquote(base64(sign(payload)))`를 끝에 붙인다(ccxt `sign()`: `eddsa(encode(query), secret, 'ed25519')` → `encode_uri_component`). 헤더 `X-MBX-APIKEY`(키 ID). GET·DELETE는 쿼리, POST는 `application/x-www-form-urlencoded` 본문.
- `recvWindow=5000` 고정. `timestamp = 로컬 ms + 측정 오프셋`. 오프셋은 `GET /fapi/v1/time`을 왕복 중간값으로 60초마다 갱신, **|오프셋| > 1000ms면 서명 요청을 보내지 않고** `ExchangeError(CLOCK_SKEW)`.
- 재시도: **조회만**(ErrorPolicy.retry_read, 최대 2회, 429는 Retry-After 준수, 418이면 즉시 중단). 주문 POST는 어떤 오류에도 재전송하지 않는다. 응답 없음·5xx·-1007 → `OUTCOME_UNKNOWN`.
- 오류 분류: `types.classify_error(http_status, code)` 하나만 쓴다(표: -1021 CLOCK_SKEW, -2019 INSUFFICIENT_MARGIN, -4120 ALGO_ENDPOINT_REQUIRED, -4164 MIN_NOTIONAL, -2021 WOULD_TRIGGER, -2022 REDUCE_ONLY_REJECTED, -2013 ORDER_NOT_FOUND, -2011 CANCEL_REJECTED, -4116 DUPLICATE_CLIENT_ID, -4061 ACCOUNT_MODE, -4400 TRADING_RESTRICTED, 429/-1003 RATE_LIMITED, 418 IP_BANNED, 451/403 REGION_BLOCKED, 401/-2014/-2015/-1022 AUTH, 5xx/-1007/-1001/무응답 OUTCOME_UNKNOWN, 그 밖 4xx BAD_REQUEST). 표를 넓힐 때는 types.py를 고친다(설계 검토).
- 호스트는 `OrdersConfig.base_url`(코드 상수표)만. 실서버 호스트면 생성자에서 거부. 로그·예외·order_events에 서명·키·전체 쿼리를 넣지 않는다. httpx 로거는 WARNING.
- 엔드포인트(ccxt `binance.py` 기준, K 표시는 데모 확인 필요):

| 메서드 | 요청 |
|---|---|
| `server_time_ms` | GET `/fapi/v1/time` |
| `symbol_rules` | GET `/fapi/v1/exchangeInfo` → BTCUSDT PRICE_FILTER.tickSize, LOT_SIZE.stepSize·minQty, MIN_NOTIONAL.notional |
| `account_config` | GET `/fapi/v1/positionSide/dual`, GET `/fapi/v1/multiAssetsMargin`, GET `/fapi/v1/symbolConfig?symbol=BTCUSDT`(K8), 계정 canTrade(`/fapi/v2/account` 또는 v3) |
| `balance` | GET `/fapi/v2/balance`(또는 v3) → USDT availableBalance |
| `mark_price` | GET `/fapi/v1/premiumIndex?symbol=BTCUSDT` → markPrice |
| `position` | GET `/fapi/v3/positionRisk?symbol=BTCUSDT` → positionAmt, entryPrice (없으면 qty 0) |
| `open_orders` | GET `/fapi/v1/openOrders?symbol=BTCUSDT` |
| `open_conditional_orders` | ALGO: GET `/fapi/v1/openAlgoOrders?symbol=BTCUSDT` / LEGACY: openOrders 중 STOP_MARKET |
| `place_order` | POST `/fapi/v1/order` symbol, side, type(LIMIT·MARKET), timeInForce=IOC(LIMIT), quantity, price(LIMIT), reduceOnly=true(청산), newClientOrderId, newOrderRespType=RESULT |
| `get_order` / `cancel_order` | GET / DELETE `/fapi/v1/order?symbol=BTCUSDT&origClientOrderId=…` (-2013 → None) |
| `place_conditional` | ALGO: POST `/fapi/v1/algoOrder` algoType=CONDITIONAL, symbol, side=SELL, type=STOP_MARKET, triggerPrice, closePosition=true, workingType=MARK_PRICE, priceProtect=false, clientAlgoId (quantity·reduceOnly 없음). LEGACY: POST `/fapi/v1/order` type=STOP_MARKET, stopPrice, closePosition=true, workingType, priceProtect, newClientOrderId |
| `get_conditional` / `cancel_conditional` | ALGO: GET / DELETE `/fapi/v1/algoOrder?clientAlgoId=…` / LEGACY: `/fapi/v1/order?origClientOrderId=…` |

- 시험(`test_binance_client.py`): 고정 Ed25519 키로 서명 벡터(같은 쿼리 → 같은 서명, 공개키로 검증), 요청 형태(메서드·경로·파라미터 이름·순서·본문/쿼리 위치)가 ccxt의 `sign()`·`create_order_request`와 같은지, 실서버 호스트 거부, 오류 분류 표, 주문 POST 재전송 0회, 조회 재시도·Retry-After, 시계 오차 시 서명 요청 차단, 로그에 키·서명 없음. 전송 계층은 `httpx.MockTransport`.

---

## 12. 가짜 거래소 규격 (`fake_exchange.py`, 가짜 거래소 담당)

`FakeExchange(clock, *, env=ExchangeEnv.DEMO, mark=…, rules=…, account=…, balance=…)`가 `ExchangeClient`를 구현한다. 바이낸스 규칙을 흉내 낸다: One-way 순포지션, IOC LIMIT(마크·호가 모형으로 전량/부분/0 체결), reduceOnly(포지션 초과 불가, 0이면 -2022), closePosition STOP_MARKET(마크 ≤ 트리거면 발동 → 포지션 전량 시장가 청산, 이미 트리거 아래면 -2021), 미체결 사이 clientOrderId 중복 -4116, 조건부 주문을 LEGACY 창구로 보내면(설정) -4120, `timestamp + recvWindow` 도착 기한.
시장 조작: `set_mark(price)`, `tick(ms)`(발동·체결 지연 처리), `set_book(…)`.

장애 주입(`inject(Fault…)`, 호출 순서·메서드별로 1회/지속):

| 장애 | 동작 |
|---|---|
| 타임아웃(요청 전) | 주문이 거래소에 **도달하지 않음** + OUTCOME_UNKNOWN |
| 타임아웃(처리 후) | 주문 **처리됨** + OUTCOME_UNKNOWN(응답 유실) |
| 중복 응답 | 같은 응답을 두 번 돌려줌(호출자가 두 번 처리해도 한 번 효과인지) |
| 부분 체결 | IOC가 요청 수량의 일부만 체결 |
| 주문 거부 | 지정 코드(-2019, -4164, -1021, -4400, -4061 …)로 확정 거부 |
| 손절 누락 | 조건부 주문이 접수 응답은 오지만 목록·조회에 없음 / 나중에 사라짐(거래소 측 취소) |
| 손절 필드 무시 | triggerPrice가 다른 값으로 저장됨(K4 흉내) |
| 시계 오차 | 서버 시각 = 로컬 + 오프셋 |
| 레이트 리밋 | 429(Retry-After) → 계속 어기면 418 |
| 연결 끊김 | N번째 호출부터 모든 호출 OUTCOME_UNKNOWN(조회 포함) |
| 체결 지연 | 주문은 접수되지만 조회에 T ms 뒤에야 보임 |
| 계정 모드 | Hedge·Multi-Asset·cross·레버리지 5 |
| 모르는 주문·포지션 | 우리 ID가 아닌 주문·포지션을 심어 둠 |
| 지역 차단·인증 | 451·403·401 |

모든 호출은 `calls` 목록에 (메서드, 요청, 결과) 로 기록(시험에서 '주문 POST가 몇 번 나갔나'를 센다).

---

## 13. 모듈 인터페이스 (스텁 시그니처)

```python
# bot/orders/binance_client.py
class BinanceFuturesClient:  # ExchangeClient
    def __init__(self, cfg: OrdersConfig, api_key: Secret, private_key_pem: Secret, *, clock: Clock,
                 http_client: httpx.Client | None = None)
    @property base_url -> str
    def sync_time(self) -> int                     # 오프셋 갱신(ms), |오프셋| > 한도면 CLOCK_SKEW
    def sign_query(self, params: list[tuple[str, str]]) -> str      # 'a=1&b=2&signature=…' (시험용 공개)
    (+ ExchangeClient 메서드 전부)
def load_private_key(pem: Secret) -> Ed25519PrivateKey

# bot/orders/fake_exchange.py
class FakeExchange:  # ExchangeClient
    def __init__(self, clock: Clock, *, env=ExchangeEnv.DEMO, mark: float = 60_000.0, rules=None, account=None,
                 balance=None, conditional_api=ConditionalApi.ALGO, base_url: str | None = None)
    def set_mark(self, price: float) -> None;  def tick(self, dt_ms: int = 0) -> None
    def inject(self, fault: Fault) -> None;    calls: list[CallRecord]
class Fault (dataclass): kind: FaultKind, method: str | None, times: int, code: int | None, …

# bot/orders/gateway.py
class Gateway:
    def __init__(self, conn, cfg: OrdersConfig, ex: ExchangeClient, clock: Clock, *, base_url: str)
    def is_halted(self, control: ControlState) -> bool
    def process_intent(self, intent_row, control: ControlState) -> GatewayResult     # §4 전체
    def resolve_entry(self, intent_row) -> IntentState                               # §4.3 결과 모름 절차(복구에서도 사용)
    def ensure_stop(self, intent_row) -> IntentState                                 # §4.4 (복구·대조에서도)
    def flatten(self, intent_row, *, reason: HaltReason | None, exit_reason: IntentExitReason) -> IntentState
    def run_trend_exit(self, intent_row) -> IntentState                              # §4.6
    def reject_queued_if_halted(self, control: ControlState) -> int

# bot/orders/reconcile.py
@dataclass class ReconcileReport: ok, snapshot, issues: list[str], actions: list[str], halt_ids: list[int]
def take_snapshot(ex: ExchangeClient, clock: Clock, *, with_balance: bool = False) -> ExchangeSnapshot
def reconcile_once(conn, gw: Gateway, ex: ExchangeClient, clock: Clock, control: ControlState) -> ReconcileReport
def recover(conn, gw: Gateway, ex: ExchangeClient, clock: Clock, control: ControlState) -> ReconcileReport  # §8

# bot/orders/worker.py
class Worker:
    def __init__(self, conn, cfg: OrdersConfig, ex: ExchangeClient, clock: Clock)
    def startup(self) -> ReconcileReport             # ensure_schema → control → recover
    def run_once(self) -> None                        # 한 바퀴: control → 시계 → (주기면) 대조 → 추세 청산 → claim/처리
    def run_forever(self, stop: threading.Event) -> None
def main(argv: list[str] | None = None) -> int        # 종료 코드: 0 정상, 2 설정·비밀 오류, 3 DB 모드 불일치
```

---

## 14. A 쪽 통합 변경 (통합 담당, 최소 수정)

| 파일 | 변경 |
|---|---|
| `bot/types.py` | `Mode.TESTNET = "testnet"`(머리표 `[TESTNET]`). `Actor`에 값 추가 없이 문자열 `ORDER_GATEWAY` 사용 |
| `bot/config.py` | mode `testnet` 허용(`live`는 계속 거부). `[orders]` 절은 `OrdersConfig.from_mapping`으로 검증(A는 키 경로만 알고 파일은 읽지 않는다). TESTNET에서 A 프로세스에 거래 키 파일이 보이면 시작 거부(I12 확장) |
| `bot/db.py` | signals.mode CHECK에 'testnet' 추가(새 DB만 해당, 기존 paper DB 영향 없음). TESTNET이면 connect 뒤 `orders.queue.ensure_schema` |
| `bot/engine.py` | TESTNET: `confirm()`의 APPROVED 전이와 **같은 트랜잭션**에서 `queue.enqueue`. `paper.fill_approved/monitor/catch_up` 대신 의도 상태로 보유 판정(evaluate_day의 held = 보유 의도의 subsystem). EXIT → `queue.request_exit(exit_due = 판단 + 30분)`. `/pause`: APPROVED 신호는 `cancel_queued`가 True일 때만 SKIPPED. **새 진입 신호는 노출 의도가 있으면 만들되 카드에 '보유 중(1포지션)'을 표시하고, B가 REJECTED('position_exists')로 끝낸다**(O-3) |
| `bot/main.py` | TESTNET 모드 실행 경로(시세는 공개 실서버 시세 또는 데모 시세 — O-9), `/status`에 B 생존(order_runtime)·T0 표시, `/resume`은 T0에 영향 없음 안내 |
| `docker-compose.yml` | 서비스 `orders`(같은 이미지, `command: python -m bot.orders.worker …`, secrets `binance_api_key`·`binance_ed25519_private_key`는 **이 서비스에만**, `/control` 읽기 전용, ports 없음·read_only·cap_drop). A 서비스에는 거래 키·제어 파일 없음. staging(테스트넷) 프로젝트로 분리 |
| `docs/RUNBOOK.md` | 테스트넷 절차: 데모 계정·Ed25519 키 생성(서버에서, 공개키만 등록), 계정 모드 설정(웹: One-way·Single-Asset·격리·3배), 제어 파일 작성·권한, K1~K14 PoC 기록표, T0 해제, 수동 청산 |

---

## 15. 시험 시나리오 목록

비동기 없음(B는 동기). 시계는 `FakeClock`, 거래소는 `FakeExchange`. 공용 도우미는 `bot/orders/tests/conftest.py`.

### 15.1 설계 담당(완료)
- `test_firewall.py`: 정상 진입·손절·청산 통과 / 위반 항목별 거부(환경 실서버·다른 env 호스트·http, 심볼, ID 형식·다른 신호·용도, 숏 진입, 시장가·GTC 진입, reduceOnly 진입, 정지, 진입 2회, 계정 Hedge·Multi-Asset·출금 권한, 레버리지 5·설정과 다름·bool, cross, 규칙 tick 변경, 포지션 있음, 미체결 있음, 수량 step·최소·절대, 가격 틱·상한 초과·마크 아래, 명목·최소 명목, 손절 계획 없음·거리, 위험 초과, 잔고 부족·없음, 손절 형식 5종·트리거 불일치·마크 이상, 청산 매수·reduceOnly 아님·포지션 초과·포지션 없음) / 청산·손절은 정지·계정 모드에도 통과 / plan_entry 결과가 방화벽 통과(여러 마크·ATR)
- `test_orders_core.py`: 전이표 모양(종료 상태 갇힘 없음·LIVE 정의·REJECTED는 전송 전만), clientOrderId 왕복·거부, 오류 분류 표, OrdersConfig 검증(모르는 키·느슨한 값·호스트 키 거부), plan(수량 내림·상한·최소 미달·손절 = strategy 값), 제어 파일(정상·오류 = 정지·권한), queue(enqueue 조건·멱등, claim 동시 1개, 전이·신호 동기화, 금지 전이, 추가 전용 트리거, 해제는 제어 파일만, cancel_queued 경쟁)

### 15.2 거래소 클라이언트 담당 (`test_binance_client.py`) — §11 목록

### 15.3 가짜 거래소 담당 (`test_fake_exchange.py`) — §12 규칙 각각 + 장애 14종 각각의 효과

### 15.4 게이트웨이·대조 담당 (`test_gateway.py`, `test_reconcile.py`) — 반드시 포함
1. 정상: QUEUED → STOP_VERIFIED, 주문 POST 정확히 2건(e1, sl), unprotected_ms ≤ 5000, 신호 FILLED, 알림
2. 계정 Hedge / Multi-Asset / cross / 레버리지 5 → 주문 0건, REJECTED, T0
3. 시계 오차 1500ms → 주문 0건, T0
4. 최소 명목 미달 → REJECTED, T0 없음
5. IOC 체결 0 → NOT_FILLED, 신호 SKIPPED
6. IOC 부분 체결 → 체결 수량으로 ENTRY_FILLED → 손절(closePosition) → STOP_VERIFIED
7. 진입 타임아웃(도달 안 함) → 조회 없음 → 도착 기한 뒤 NOT_FILLED, 진입 POST 1건뿐
8. 진입 타임아웃(처리됨) → 조회로 체결 발견 → 손절 → STOP_VERIFIED, 진입 POST 1건뿐
9. 진입 중복 응답 → 한 번만 처리
10. 진입 확정 거부 -2019 → NOT_FILLED + T0
11. 손절 등록 타임아웃(처리됨) → 같은 ID 조회로 발견 → STOP_VERIFIED, sl POST 1건
12. 손절 3회 거부 → 청산(f1) → FAILED_FLATTENED + T0, 포지션 0
13. 손절 접수됐으나 목록에 없음(누락) → 청산 + T0
14. 손절 triggerPrice 다름 → 불일치 → 청산 + T0
15. -4120 → 청산 + T0 `algo_endpoint`
16. -2021(즉시 발동) → 청산, FAILED_FLATTENED(stop_immediate), T0 없음
17. 체결 지연(조회에 늦게 보임) → GRACE 안에 발견
18. 손절 확인이 5초 넘게 걸림 → 청산 + T0 `unprotected_timeout`
19. 청산도 실패(연결 끊김) → HALTED + T0, 새 claim 없음
20. T0 중 QUEUED → REJECTED('halted'), 주문 0건. 제어 파일 해제 뒤 다음 신호 정상
21. 레이트 리밋 429 → 조회만 재시도, 418 → T0
22. 대조: 손절 사라짐 → 청산 + T0 / 손절 발동 → CLOSED(stop) / 모르는 주문 → 취소 + T0 / 모르는 포지션 → T0 / 수량 불일치 → T0 / 조회 3회 실패 → T0 / 고아 sl 정리
23. 추세 청산: exit_due 전 아무것도 안 함, 뒤 x1 → CLOSED(trend) → sl 취소, 신호 CLOSED
24. 추세 청산과 손절 발동 경쟁(포지션 이미 0) → -2022 → CLOSED(stop)

### 15.5 통합 담당 (`test_e2e_testnet_sim.py`)
신호 생성 → 카드 → [승인]·[확인] → QUEUED → B 처리 → STOP_VERIFIED → (가격 하락) 손절 발동 → CLOSED, 그리고 추세 청산 경로. 각 단계 사이 **B 강제 종료(객체 폐기)·재시작(새 Worker + 같은 DB 파일)**: 전송 기록 전 / 전송 후 응답 전 / 체결 후 손절 전 / 손절 확인 후 / EXITING 중 — 매번 최종 거래소 상태가 '포지션 0 또는 손절 있는 포지션'이고 진입 POST ≤ 1. A 프로세스에 거래 키가 없음(설정·compose 검사), T0 해제가 텔레그램으로 안 됨.

실행: `.venv/bin/python -m pytest bot/orders/tests -q`.

---

## 16. 결정 기록 (설계 담당, 보수적 해석)

| # | 결정 | 이유 |
|---|---|---|
| O-1 | 진입은 **IOC 상한 지정가만**(기본 상한 10bp, 코드 상한 30bp). 대기 지정가(GTX+GTD)는 이 단계에서 구현하지 않음 | ARCHITECTURE §3.4: K1 미확인이면 IOC가 기본. 걸어 둔 진입이 봇 정지 중 무방비 체결되는 경로 제거. E0 모의 체결(확인 뒤 첫 1분봉 시가)과도 뜻이 가깝다 |
| O-2 | 익절 주문 없음 | E0-L-ENS 청산은 보호 손절 + 추세 청산뿐(TREND_SPEC). PLAN D7의 익절은 다른 전략용 |
| O-3 | **거래소 포지션은 동시에 1개**(하위 시스템 1개). 다른 N의 신호가 승인돼도 노출 의도가 있으면 B가 REJECTED('position_exists') | One-way 순포지션 + closePosition 손절은 하위 시스템별 손절을 나눌 수 없다. I6·PLAN D8 '최대 1포지션'. 모의 운영(최대 3개)과의 차이는 TESTNET 결과 비교 때 명시 |
| O-4 | 계정 모드·레버리지·마진은 **검사만**(바꾸지 않음). 다르면 REJECTED + T0 | 08 §2.5-4, ARCHITECTURE §5.1.1. 모드 변경은 모든 종목에 적용되고 포지션 중 변경 가능 여부가 불확실 |
| O-5 | 결과 모름 판정의 끝은 '서명 timestamp + recvWindow + 2초' 뒤 조회 부재 | 바이낸스가 늦게 도착한 서명 요청을 거부하는 규칙에 근거. 조회 자체가 안 되면 HALTED |
| O-6 | 재시작 때 손절이 확인되지 않은 포지션은 **손절을 새로 거는 대신 청산 + T0** | I2(5초)를 이미 넘은 상태. 새 손절 등록도 실패할 수 있는 상황에서 가장 확실한 쪽 |
| O-7 | -2021(손절 즉시 발동 가격)은 청산하되 T0를 걸지 않음 | 기술 실패가 아니라 시장 사건(체결 직후 손절가 아래). 경보는 보냄 |
| O-8 | 킬 스위치 해제는 제어 파일의 halt_id만 인정, DB 해제 행은 판정에 안 씀. 제어 파일 없음·형식 오류 = 수동 정지 | A 침해 시 해제 위조 차단(I14), fail-closed |
| O-9 | 모의 환경 기본은 데모 트레이딩(`demo-fapi.binance.com`), 호스트는 코드 상수표 | ccxt master가 선물 sandbox 지원 종료를 표시. 설정에서 호스트를 받지 않아 실서버 오지정 불가 |
| O-10 | 절대 상한 0.2 BTC·10,000 USDT, 위험 상한 1%, 손절 거리 0.2~25%, 가격 괴리 1% | PV-16 제안값·PLAN D8 상한. 절대 명목은 D20(잔고 상한) 결정 때 재검토 |
| O-11 | 대조에서 '모르는 포지션'은 **청산하지 않고 T0 + 경보**(기본). 손절 없는 **우리** 포지션만 자동 청산 | 우리 ID 규칙(sig-<신호>)으로 청산 주문을 만들 수 없고, 사람의 수동 개입(RUNBOOK 수동 청산) 중일 수 있다. 봇 계좌 수동 매매 금지는 운영 규칙(ARCHITECTURE §9) — 게이트웨이 담당이 반대 근거가 있으면 이 표를 먼저 고칠 것 |
| O-12 | 모르는 **일반** 주문은 취소, 모르는 조건부 reduceOnly·closePosition 매도는 두고 T0 | 걸린 진입 주문은 무방비 체결 위험, 줄이기 전용 주문은 위험을 늘리지 않음 |
| O-13 | 큐·킬 스위치 저장 함수(`queue.py`)와 제어 파일(`control.py`), 계획(`plan.py`)을 설계 담당이 구현 | 상태 머신의 원자성·불변식이 게이트웨이·대조·통합 시험의 공통 토대. 원래 설계 담당이 db.py를 맡은 것과 같은 분담 |
| O-14 | B의 신호 재검증은 필드 대조·낡음·위험 한도까지. 공개 일봉으로 신호를 **재계산**하는 G-d 완전판은 다음 단계 | A 위조 시 피해는 방화벽이 1회 위험 ≤ r로 묶는다(ARCHITECTURE §1.2 등급). 재계산은 B에 시세 경로를 더해 범위가 커짐 |
| O-15 | T0 정지 중에도 추세 청산·손절 누락 청산은 계속 | 위험을 줄이는 동작은 막지 않는다(ARCHITECTURE T0: 기존 손절 유지) |

### 16.1 검토 지적 수정 기록 (수정 담당, 2026-09-30)

재현 시험: `tests/review_security_test.py`(SEC-xx)·`tests/review_chaos_test.py`(Fxx)의 xfail을 지워 회귀 시험으로 바꿨고, 새 부품은
`tests/test_review_fixes.py`. 퍼징 600 시드(0~599)에서 끝 상태 무방비·대조 누락 0건(수정 전 seed 192·346·571 등 실패).

| # | 지적 | 수정 |
|---|---|---|
| R-1 | SEC-01 CLOSED 위조 → 대조가 살아 있는 손절 취소 | `_check_foreign`: 끝난 의도의 sl은 **포지션 0일 때만** 취소. 포지션이 있으면 유지 + T0 `position_mismatch` |
| R-2 | SEC-02 트리거 재생성으로 T0 삭제 | 매 루프 `queue.integrity_problems`(추가 전용 표의 행 수 = 최대 id = sqlite_sequence, 트리거 **본문** 비교) + sqlite_sequence 감소 감시 → T0 `order_error`(why=db_integrity). 해제되면 그 문제 서명은 원장에 '확인됨'. B가 건 T0는 B 원장에도 → DB에서 지워도 정지 유지. `ensure_schema`도 본문 검사 |
| R-3 | SEC-03·F4 DB 잠금·예외로 손절 없음 | 진입 전송 뒤 구간을 `_post_send_guard`로 감싼다: SQLite 대기 1초, 거래소 밖 예외면 **DB 없이** `emergency_protect`(메모리 `_guard`: 신호·ATR·체결가 → 손절 등록·대조, 안 되면 reduceOnly 청산) 후 예외 재발생. 워커는 예외 뒤 다음 바퀴에 `recover()`를 먼저 돈다. `order_events` 기록 실패는 메모리에 모았다가 나중에 쓴다(주문 흐름을 멈추지 않음) |
| R-4 | SEC-04 누적 한도 없음 | §7.4 — 하루 진입 3, T1, T2를 B 원장 ∪ DB로. 다음 UTC 00:00 자동 해제 |
| R-5 | F3a·F3b·F3c 청산 시도 평생 3회 소진 → 영구 무방비, T0 폭주 | 비상 청산은 **호출(주기)마다** f1~f3(번호 재사용 — K15), 청산 실패면 `rearm_stop`으로 보호 손절 재등록 후 HALTED. HALTED는 대조마다 `secure_halted`(손절 있으면 대기, 없으면 새 청산 주기 → 실패면 손절). 이미 T0가 걸린 의도의 반복 청산은 `halt_once`(새 T0·경보 없음). 추세 청산 x1~x3은 평생 3회 그대로(손절이 남아 보호) |
| R-6 | F2 429 Retry-After 무시 → 418 | 게이트웨이의 모든 거래소 호출(`_x`)과 대조 묶음 조회가 429·418 대기 창을 지킨다(창 안에서는 어떤 요청도 보내지 않음). 손절 경로에 429가 걸리면 I2 5초는 원리상 지킬 수 없다 → 무방비는 Retry-After로 묶이고 창이 끝나면 청산 + T0 `unprotected_timeout`. 시험 기대를 이렇게 바꿨다 |
| R-7 | F5 늦게 보인 체결 → 모르는 포지션으로 방치 | 대조: 노출 의도 없이 롱이면 최근 NOT_FILLED 3건의 e1 조회 → 체결이면 `handle_orphan_fill`(DB 없는 청산, 안 되면 손절) + T0. 의도 상태는 바꾸지 않는다(종료 상태 전이 금지 유지) |
| R-8 | F8 해제가 halt_id 숫자에만 묶임 | §7.3 — '그 T0 뒤에 처음 본 해제'만 + `at` 검사. 처음 본 시각은 B 원장(재시작에도 유지) |
| R-9 | F9 마크 조회 하나로 복구·대조 정지 | `take_snapshot`은 마크 실패를 None으로. 묶음 조회 실패 중에도 노출 의도는 자체 조회로 확인·보호(`_protect_without_snapshot`) |
| R-10 | F1 get_order 실패 시 포지션 안 봄 | `resolve_entry`: 주문 조회가 없음이든 **실패**든 포지션을 보고, 체결이면 곧바로 손절 단계. HALTED로 끝나도 `secure_halted` |
| R-11 | F7 사라진 손절 감지가 대조 주기(30초) | STOP_VERIFIED면 매 바퀴 가벼운 `get_conditional(sl)` → 없으면 대조를 앞당김 |
| R-12 | F6 B 두 개 | `main(run)`이 DB 옆 `<db>.orders.lock`에 배타 flock, 잡혀 있으면 종료 코드 2. `_record_fill`이 전이를 잃었는데(다른 주체가 NOT_FILLED 확정) 체결이 있으면 `handle_orphan_fill` |
| R-13 | SEC-06 B의 독립 경보 경로 없음 | **남은 과제**. 완화만: B는 T0를 자기 로그에 WARNING으로 남긴다. 독립 경로(B 전용 헬스 핑 비밀 또는 C18 외부 감시자)는 비밀·운영 결정이 필요해 이번 범위 밖 |
| R-14 | SEC-05 미래 approved_ms | `_submit`·`reject_stale_queued` 모두 `approved_ms > now + max_clock_skew_ms`면 REJECTED(`future_approval`) |

