# TESTNET 주문 경로 독립 검증 보고서 (VERIFY_REPORT)

- 검증 대상: `bot/orders/`(프로세스 B), `bot/engine.py`·`bot/config.py`·`bot/db.py` TESTNET 연동, `docker-compose.yml`, `docs/RUNBOOK.md` §10.
- 1차 검증(§1–§8): 수정 담당의 검토 지적 수정(DESIGN §16.1 R-1..R-14)을 반영한 뒤의 상태(2026-09-30).
- **2차 검증(§9, 이 문서 맨 위 판정)**: 1차 지적 V-1·V-2를 고친 R-15·R-16 반영 뒤의 상태(2026-09-30).
- 검증관이 만든 것: `bot/orders/verify/` 아래 스크립트와 `results/*.json`. 제품 코드와 시험 코드는 **고치지 않았다**.
  2차에서 더한 것: `rescue_edge_probe.py`, `halted_query_fail_probe.py`, `fuzz_exact.py`, `kill_restart_sim.py`의 S12 시나리오.
- 이 컨테이너에서는 바이낸스(실서버·데모·테스트넷)에 접속할 수 없다. 그래서 아래 결과는 전부 **가짜 거래소**(`fake_exchange.py`)
  기준이다. 실제 거래소에서 확인할 항목은 §7(2차 갱신은 §9.6)에 따로 적었다.

## 0. 판정 요약 (2차)

| 항목 | 결과 |
|---|---|
| 1차 치명 지적 V-1(시작 거부 시 무기한 무방비) | **해결 확인**. 가짜 시계 main 경로(종료 3, 포지션 0), **실제 프로세스** SIGKILL + 트리거 삭제 + 재시작 2회(S12: 종료 3·3, f1 1건으로 청산, 무방비 1.75초, 두 번째 재시작 주문 0), 경계 사례 20가지(§9.2) |
| 1차 치명 지적 V-2(B가 살아 있는데 약 31초 무방비) | **해결 확인(퍼징 범위)**. seed 9531·4253: 30.8초 → 4.8·2.8초. 시드 1000–9999 재실행에서 끝 상태 위험 0, 10초 초과 0. 거래소 상태가 바뀔 때마다 표본을 뜨는 정밀 측정(`fuzz_exact`)으로도 분포가 같다. 다만 **좁은 남은 틈** 하나가 있다(V-8, 낮음–중간) |
| 전체 시험 모음 | **1588 passed**, 0 failed(`pytest` 저장소 전체). 검증관 스크립트를 더한 뒤 다시 돌려도 같다(§9.1) |
| 실제 프로세스 SIGKILL·재시작 | 27개 시나리오(기존 26 + S12) 모두 안전. 진입 POST ≤ 1. 결과가 1차와 같다(정상 5–12ms, 체결 직후 강제 종료는 중단 + 약 0.7초) |
| 키 분리(strace) | 다시 돌려 A 쪽 키 읽기 0 (§9.5) |
| 새로 찾은 것 | **V-7(낮음)** 시작 거부 전 구조(protect_without_db)가 주문 POST의 '결과 모름'(5xx·연결 끊김) 뒤에 **잠 없이** 다시 보낸다. **V-8(낮음–중간)** HALTED 무방비인데 손절 단건 조회(get_conditional)만 계속 실패하면 다음 대조까지(견본 10초 → 8.3초, 설정 상한 30초 → 28.3초) 기다린다. 문서 사소 2건(§9.4) |
| 결론 | **ok**(치명 없음). V-1·V-2는 해결됐고, 끝 상태 안전성·방화벽·키 분리는 유지된다. V-7·V-8은 테스트넷(가짜 돈)을 막을 수준이 아니지만 LIVE 전에 고치기를 권한다 |

## 0.1 1차 판정 요약 (기록용, 2차에서 V-1·V-2 해결)

| 항목 | 결과 |
|---|---|
| 전체 시험 모음 | **1575 passed**, 0 failed, 0 xfail (`pytest` 저장소 전체, 311초). `bot/` 1078개, `bot/orders/` 633개 |
| 가짜 거래소 e2e(`test_e2e_testnet_sim.py`) | 15/15 통과 |
| 실제 프로세스 SIGKILL·재시작(V1) | 26개 시나리오 모두 끝 상태 안전(포지션 0이거나 우리 손절로 보호, 진입 POST ≤ 1, DB와 거래소 일치) |
| 장애 주입 퍼징 확장(V4) | 시드 1000–9999(9,000개): **끝 상태 위험 0건**. 다만 B가 살아 있는데도 **약 31초 동안 손절이 없는** 경우가 2건 있다(§5 V-2) |
| 방화벽·사전 점검 한도 밖 시도(V2) | 게이트웨이 경유 **31/31 차단**, 방화벽 단독 31/31 거부, 기준(정상) 4/4 통과. 요구한 20가지보다 많다 |
| 거래 키가 A에서 읽히는가(V3, strace) | A 쪽 어느 경로에서도 **읽기로 열지 않는다**(A1–A4). 양성 대조로 B는 키 두 파일을 여는 것이 보인다 |
| 새 결함 | **V-1(중간)**: 체결 직후 B가 죽고, 재시작할 때 시작 거부(DB 스키마 검사 등)를 하면 무방비 포지션이 **무기한** 남는다. **V-2(중간)**: 청산이 실패하고 다시 건 손절까지 확인되지 않으면, 다음 대조까지 최대 30초 동안 손절이 없다 |
| 결론 | **issues**. 끝 상태 안전성·방화벽·키 분리는 확인됐다. 다만 무방비 구간은 설계 목표(I2, 5초)를 두 가지 경로(V-1, V-2)에서 넘는다. 테스트넷(가짜 돈)을 시작하는 것을 막을 수준은 아니지만, LIVE로 가기 전에는 반드시 고쳐야 한다 |

## 1. 시험 모음

```
.venv/bin/python -m pytest -q -p no:cacheprovider            → 1575 passed in 311.63s
.venv/bin/python -m pytest -q -p no:cacheprovider bot/orders → 633 passed in 29.70s
.venv/bin/python -m pytest bot/orders/tests/test_e2e_testnet_sim.py -v → 15 passed
```

수정 담당이 보고한 1078은 `pytest bot` 범위의 수다(검증관이 수집해 보니 1078개로 같다). e2e 15개는 모두 통과했다.
정상 경로(손절 발동, 추세 청산 + 두 번째 신호), 진입 중 강제 종료 4지점, STOP_VERIFIED 보유 중 강제 종료, EXITING 중
강제 종료 2지점, 복구 도중 다시 강제 종료, T0는 제어 파일로만 해제, A에 거래 키 없음, compose 키 분리, 견본 설정 로드,
장기 엔진 사이클이 여기에 들어간다. 다만 이 e2e의 '강제 종료'는 같은 프로세스 안에서 예외로 흉내 낸 것이라, V1에서
진짜 프로세스로 다시 확인했다.

## 2. V1 — 실제 프로세스 SIGKILL·재시작 (`kill_restart_sim.py`)

구성은 이렇다. 가짜 거래소를 별도 서버 프로세스에 두고 실시간 시계를 쓴다. B는 진짜 자식 프로세스로
`bot.orders.worker.main(run)`을 띄운다. 설정·제어 파일·원장·flock·SQLite WAL은 실물이고, 클라이언트만 원격 가짜로 바꿨다.
거래소 쪽에서 지정한 호출의 **직전 또는 처리 직후(응답 전)**에 `SIGKILL`을 보낸다. 그리고 거래소 프로세스 안의 감시 스레드가
2ms마다 '롱 포지션 + 활성 closePosition 손절 없음' 상태를 잰다(거래소가 본 사실 기준).

| 시나리오 | 끝 상태 | T0 | 무방비 최대(ms, 거래소 기준) |
|---|---|---|---|
| S00 정상(강제 종료 없음) | STOP_VERIFIED | – | 6.6 |
| S01 진입이 거래소에 닿기 전 종료 | NOT_FILLED(진입 POST 0) | – | 0 |
| S02 체결 직후 종료, 중단 1초 | FAILED_FLATTENED | restart_unprotected | **1,733** |
| S02b 체결 직후 종료, 중단 5초 | FAILED_FLATTENED | restart_unprotected | **5,789** |
| S02c 체결 직후 종료, 중단 10초 | FAILED_FLATTENED | restart_unprotected | **10,665** |
| S03 손절 접수 직후 종료 | STOP_VERIFIED(재시작 뒤 확인) | – | 5.2 |
| S04 손절 확인 조회 직전 종료 | FAILED_FLATTENED | restart_unprotected | 1,694 |
| S05 체결 직후 종료 + 복구 중 다시 종료 | FAILED_FLATTENED | restart_unprotected | 3,398 |
| S06 보유 중 종료 | STOP_VERIFIED | – | 4.9 |
| S07 추세 청산 x1 체결 직후 종료 | CLOSED(trend) | – | 7.4 |
| S08 x1이 닿기 전 종료 | CLOSED(trend) | – | 6.7 |
| S09 손절 거부 → 비상 청산 f1 체결 직후 종료 | CLOSED(external) | position_vanished | 931 |
| S10 B가 죽은 동안 손절 발동 | CLOSED(stop) | – | 5.9 |
| S11 손절 등록 직전 종료 | FAILED_FLATTENED | restart_unprotected | 1,769 |
| random_0..11(2–4회 무작위 SIGKILL, 중단 0.3–3초, 청산·손절 발동 섞음) | 모두 안전 | – | 최대 1,723 |

- 26개 모두 안전했다(`results/kill_restart.json` `unsafe: []`). 진입 POST는 모든 경우에 신호당 1회 이하였다.
- 정상 경로의 무방비 구간은 가짜 거래소와 로컬 통신 기준으로 5–10ms다(DB 기록 `unprotected_ms`로는 11–21ms). 실제 데모에서는
  왕복 3회(진입 → 손절 → 조회)만큼 늘어난다(§7 P-1).
- **체결과 손절 확인 사이에 B가 죽으면** 무방비 구간은 `중단 시간 + 재기동 약 0.7초`다. 재시작한 B는 확인되지 않은
  포지션에 손절을 거는 대신 바로 청산하고 T0를 건다(설계 §8대로). 이 구간은 B가 되살아나는 시간에만 묶이고, 상한이 없다.
  compose의 `restart: unless-stopped`는 반복 실패 때 대기를 늘린다. 게다가 재시작이 거부되면 영원히 이어진다(§5 V-1).
  근본 대책은 K1 선배치(`stop_placement = "pre_entry"`)다. PoC 확인이 필요하다.
- S09는 우리 비상 청산(f1)이 체결된 뒤 죽은 경우다. 재시작한 B는 이것을 '외부에서 사라진 포지션'(position_vanished T0)으로
  기록했다. 보수적인 오분류일 뿐 안전에는 문제가 없다(V-4, 낮음).

## 3. V4 — 장애 주입 퍼징 확장 (`fuzz_extended.py`)

수정 담당이 쓰지 않은 시드 1000–9999(9,000개)에 `review_chaos_test._fuzz_once`를 그대로 돌렸다. 한 번에 장애 1–4개를 넣고,
60%는 무작위 강제 종료 + 5초 중단을 섞었으며, 추세 청산 요청과 손절 발동도 넣었다. 가짜 시계 기준이다.

- **끝 상태 위험 0건**. 다섯 가지를 봤다. 포지션 < 0 없음, 진입 POST > 1 없음, 노출 의도 > 1 없음, 무방비로 끝난 경우 없음,
  'DB는 끝남인데 거래소 포지션 있음' 없음.
- 끝 상태 분포: CLOSED 3,574 · FAILED_FLATTENED 2,210 · STOP_VERIFIED 1,950 · REJECTED 783 · NOT_FILLED 394 · HALTED 51 · EXITING 38.
- 무방비 최대 구간 분포: 0초 7,567 · 5초 이하 1,235 · 5–6초 173 · 6–10초 20 · **10초 초과 5**.
- 10초를 넘은 5건(5291, 7954, 4253, 9531, 3016) 가운데 4건은 **강제 종료 없이** 일어났다. 거래소 주문 기록으로 실제 구간을
  다시 계산했다(퍼징 감시기는 B가 거래소를 부를 때만 표본을 떠서 구간을 부풀린다).
  - **9531**: 요청 도착 지연 9초(> recvWindow 5초) 장애 5회. 손절, f1–f3, 다시 건 손절이 모두 거래소에서 버려졌다.
    T0 두 개가 걸린 뒤, 다음 대조(30초)의 새 청산 주기에서 f2가 체결됐다. **실제 무방비 약 30.8초**.
  - **4253**: 손절이 사라지는 장애 5회와 청산 거부(-4164) 3회가 겹쳤다. 14.0초에 손절 사라짐을 감지했지만 f1–f3가 거부됐다.
    다시 건 손절(14.9초)도 곧 사라졌는데, B는 이를 조회로 알고도 다음 대조까지 기다렸다. 45.7초에 f1이 체결됐다.
    **실제 무방비 약 30.8초**.
  - 5291(실제 약 3–5초)과 3016(실제 약 3.3초)은 표본 추출 때문에 부풀려진 값이다(f1 체결·손절 생성 시각으로 확인).
  - 7954는 강제 종료가 섞였고, 같은 메커니즘으로 약 31초였다.
- 수정 담당의 보고 "6초를 넘는 일시 무방비는 seed 346(7초) 하나"는 0–599 범위에서만 맞는다. 범위를 넓히면 V-2가 드러난다.

## 4. V2 — 한도 밖 주문 시도 (`firewall_limits.py`)

**게이트웨이 경유(실제 Worker 루프 + 가짜 거래소)**: 한도 밖 조건은 세 가지 방법으로 만들었다. 거래소 상태를 바꾸거나,
A가 위조할 수 있는 DB 값을 고치거나, `plan_entry`를 망가뜨려 방화벽만 남겼다. 기준 대조군(한도 안)은 실제로 진입과 손절까지
나갔다(STOP_VERIFIED, 0.016 BTC). 이것으로 시험이 헛돌지 않음을 확인했다.

| # | 시도 | 막은 층(사유) | 거래소 도착 POST |
|---|---|---|---|
| 1 | 수량 0.25 BTC(절대 상한 0.2 초과) | 방화벽 FW-QTY-ABS·NOTIONAL·RISK + T0 | 0 |
| 2 | 명목 6,000 USDT(상한 초과) | FW-NOTIONAL·RISK + T0 | 0 |
| 3 | 위험 > R×0.5% | FW-RISK + T0 | 0 |
| 4 | 상한가 = 마크 +1.5% | FW-PRICE-BAND + T0 | 0 |
| 5 | 매수 상한가 < 마크 | FW-PRICE-BAND + T0 | 0 |
| 6 | 틱 배수 아닌 가격 | FW-PRICE-TICK + T0 | 0 |
| 7 | 스텝 배수 아닌 수량 | FW-QTY-STEP + T0 | 0 |
| 8 | 수량 0 | FW-QTY + T0 | 0 |
| 9 | 계획 손절 없음 | FW-STOP-PLAN + T0 | 0 |
| 10 | 손절 ≥ 진입가 | FW-STOP-PLAN + T0 | 0 |
| 11 | A 위조 ATR로 손절 거리 33% | FW-STOP-DIST + T0 | 0 |
| 12 | A 위조 ATR로 손절 거리 0.05% | FW-STOP-DIST + T0 | 0 |
| 13 | 잔고 부족 | FW-BALANCE + T0 | 0 |
| 14 | 레버리지 5배 | 사전 점검 leverage_margin + T0 | 0 |
| 15 | 교차 마진 | leverage_margin + T0 | 0 |
| 16 | Hedge 모드 | account_mode + T0 | 0 |
| 17 | Multi-Asset | account_mode + T0 | 0 |
| 18 | 출금 권한 있는 키 | account_mode + T0 | 0 |
| 19 | 클라이언트 주소가 실서버 | FW-ENV + T0 | 0 |
| 20 | A가 신호를 숏으로 위조 | B의 신호 재확인(signal_mismatch) | 0 |
| 21 | 거래소에 포지션이 이미 있음 | unknown_position + T0 | 0 |
| 22 | 우리 것이 아닌 미체결 주문 | unknown_order + T0 | 0 |
| 23 | 심볼 규칙 변경(tick 1.0) | symbol_rules + T0 | 0 |
| 24 | 풀리지 않은 T0 | halted | 0 |
| 25 | 제어 파일 수동 정지 | halted | 0 |
| 26 | 하루 진입 3회 초과(B 원장) | daily_entry_cap | 0 |
| 27 | 승인 6분 전(낡음) | stale_approval | 0 |
| 28 | 미래 시각 승인 | future_approval | 0 |
| 29 | 서버 시각 오차 2초 | clock_skew + T0 | 0 |
| 30 | 결과 모름 뒤 재시작 → 진입 재전송 | 재전송 없음(e1 POST 1, 도착 0) → NOT_FILLED | 1(미도착) |
| 31 | 보유 중 두 번째 승인 신호 | position_exists(두 번째 e1 POST 0) | 0 |

**방화벽 단독(순수 함수)**: 게이트웨이가 스스로는 만들지 않는 모양의 주문 31가지가 모두 거부됐다. ETHUSDT, 숏 진입, 시장가 진입,
GTC, 임의 clientOrderId나 다른 신호의 ID, 실서버·http 주소, 진입 두 번, 진입 reduceOnly, NaN 수량, 마크 모름, 손절 BUY,
closePosition=false, CONTRACT_PRICE, priceProtect=true, LIMIT형 손절, 트리거 ≥ 마크, 트리거 ≠ 계획, 손절 거리 30%, 포지션 없음,
숏 포지션, ID 용도 e1, 청산 reduceOnly=false, 청산 BUY, 청산 수량 > 포지션, 포지션 0, LIMIT 청산, 용도가 다른 ID,
비상 청산 reduceOnly=false, 비상 청산 수량 초과가 여기에 들어간다. 기준 진입·손절·청산·비상 청산 4개는 통과했다(`direct_wrong: []`).

참고로 A는 `signals.side`를 UPDATE할 수 있다(보호 트리거 없음). B의 재확인이 이것을 막는다(20번).

## 5. 발견 사항

### V-1 (중간, 2차: 해결 — R-15, §9.2) 무방비 포지션이 있는데 B가 재시작을 거부하면 보호가 무기한 멈춘다
- 위치: `bot/orders/worker.py` `main()`과 `Worker.startup()`. 설정(`load_config`)·비밀(`from_files`)·A 비밀 노출·
  `db.connect` 모드·`queue.ensure_schema`(보호 트리거 없음 또는 본문 다름 → `DbError`) 가운데 하나라도 실패하면
  `recover()` 전에 EXIT_CONFIG나 EXIT_DB로 끝난다.
- 재현: `.venv/bin/python -m bot.orders.verify.startup_refusal_probe`(`results/startup_refusal.json`).
  - 먼저 체결 직후, 손절 등록 직전에 종료한다(포지션 0.016, 손절 0).
  - 대조군은 그대로 재시작한다. 이때는 청산되어 포지션 0.
  - 보호 트리거 1개를 지운 뒤 재시작하면 `DbError`로 거부되고, **포지션 0.016·손절 0이 그대로 남는다**.
- 영향: compose가 재시작해도 같은 이유로 계속 거부된다. A의 경보는 'B 심장 박동 없음'(5분 뒤)뿐이고 무방비라는 내용은 없다.
  사람이 거래소 웹을 보기 전까지 손절 없는 포지션이 유지된다. 이렇게 되는 조건은 두 가지가 겹칠 때다.
  하나는 B 크래시(OOM, 배포, 호스트 재부팅)이고, 다른 하나는 운영자 실수(설정 수정, 키 파일 권한, DB 복원)나 A 침해(트리거 삭제)다.
- 권고:
  - 시작 거부 사유가 있어도, 거래소 클라이언트를 만들 수 있으면 **보호 전용 복구**를 먼저 돈다. DB 없이 포지션을 조회하고,
    우리 손절이 없으면 reduceOnly 청산을 하거나 계획 손절을 건다. 그다음에 종료한다.
  - 이 경우의 T0와 경보는 B 로그에 남긴다.
  - 스키마 변조 T0는 그 다음 단계로 처리한다.

### V-2 (중간, 2차: 해결 — R-16, §9.3. 남은 좁은 틈은 V-8) 청산 실패 뒤 다시 건 손절이 확인되지 않으면 다음 대조(최대 30초)까지 무방비
- 위치: 비상 청산(f1–f3)이 실패하면 `rearm_stop` 뒤 HALTED가 된다. 그런데 HALTED 의도의 `secure_halted`는 대조 때만 부른다
  (`reconcile.py:212·285`). 루프마다 하는 가벼운 손절 확인(`quick_stop_check`, R-11)은 **STOP_VERIFIED에만** 적용된다
  (`worker.py _run_once`).
- 재현: 퍼징 시드 9531과 4253(강제 종료 없음). 명령은 아래와 같다.
  ```
  .venv/bin/python -c "import tempfile,pathlib;from bot.orders.tests.review_chaos_test import _fuzz_once;from bot.orders.tests.conftest import T_APPROVED_MS;from bot.types import FakeClock,NS_PER_MS;d=tempfile.mkdtemp();print(_fuzz_once(9531,pathlib.Path(d),FakeClock((T_APPROVED_MS+5000)*NS_PER_MS)))"
  ```
  결과는 worst 30,800ms이고 halts ['stop_not_verified','flatten_failed']다. 거래소 기록상 f2 체결은 30.8초였고, 그 사이 활성 손절은 없었다.
- 영향: 거래소가 요청을 잃거나 거부하는 장애가 계속되는 동안 무방비 구간이 I2(5초)가 아니라
  `reconcile_interval_s`(설정 상한 30초) + 약 1초로 묶인다. B는 손절이 없음을 **이미 알고** 있는데도 기다린다.
- 권고:
  - HALTED이고 확인된 손절이 없는 의도는 루프마다(`loop_interval_s`) `secure_halted`를 돈다. 429·418 대기 창은 계속 지킨다.
  - 또는 `quick_stop_check`를 HALTED·EXITING까지 넓힌다.
  - 테스트넷 설정 견본의 `reconcile_interval_s`를 10으로 낮추는 것도 완화책이 된다.

### V-3 (정보, 2차: 정밀 측정으로 해소 — §9.3) 퍼징 감시기는 무방비 구간을 부풀린다
`review_chaos_test.Monitor`는 B가 거래소를 부를 때만 표본을 뜬다. 지연 도착한 주문이 B의 호출 사이에 체결되면 구간 끝을 늦게 본다
(5291: 표시 31.7초, 실제 3–5초). 반대로 짧은 구간을 놓칠 수도 있다. 시험 판정(끝 상태)에는 영향이 없다. 다만 '최대 무방비'를
보고할 때는 거래소 기록(주문 체결·조건부 주문 생성 시각)으로 다시 계산해야 한다. V1은 2ms 실시간 감시라 이 문제가 없다.

### V-4 (낮음) 우리 비상 청산 체결 뒤 강제 종료되면 '외부 청산'으로 기록된다
S09. 재시작 복구가 f1–f3 체결을 조회해 연결하지 않고 `position_vanished` T0 + CLOSED(external)로 기록한다. 보수적인 쪽이라
안전에는 문제가 없지만, 불필요한 T0이고 운영자가 헷갈릴 수 있다.

### V-5 (낮음, 기존 SEC-06) B의 독립 경보 경로 없음
수정 담당이 남은 과제로 적은 그대로다. V-1·V-2와 겹치면 경보가 A를 거쳐 늦게 가거나 가지 않는다.

### V-6 (낮음) 418 긴 금지 중에는 보호 수단이 없다
Retry-After가 20초를 넘으면 게이트웨이는 보내지 않는다. 손절과 청산 모두 막히므로, 체결 직후 418을 받으면 금지가 풀릴 때까지
무방비다. 이것은 거래소 쪽 제약이라 코드로 없앨 수 없다. RUNBOOK T8에 "418이면 거래소 웹에서 직접 청산"을 넣기를 권한다.

## 6. V3 — 거래 키가 A 쪽 어디에서도 읽히지 않는가 (`key_access_trace.py`, strace -f)

배치는 compose와 같게 흉내 냈다. A와 B는 같은 설정 내용을 쓰고 키 경로만 다르다. A가 보는 키 경로에는 파일이 없고,
B가 보는 경로에는 실제 Ed25519 PEM과 키 ID가 있다. 파일 관련 시스템 호출은 전부 추적했다.

| 측정 | 결과 |
|---|---|
| A1: A가 보는 경로에 키 파일을 일부러 둠 → `bot.main check` | 종료 2(시작 거부). 키 파일은 `newfstatat`(존재 확인)만 하고 **open 없음** |
| A2: 정상 배치 `check`, `run --dry-run` | 키·제어 파일·원장: `newfstatat` ENOENT만. 읽기 open 0 |
| A3: A 실제 동작(설정·비밀 로드 → Engine → 카드 → [승인]·[확인] → 큐 → 실제 B 자식이 진입·손절 → outbox → 청산 요청 → CLOSED) | A 프로세스의 키·제어·원장 읽기 open **0**. A에 올라온 모듈은 `bot.orders.{queue,types,…}`뿐이다. `binance_client`·`gateway`·`worker`는 **올라오지 않았다** |
| B0 양성 대조(같은 흐름의 B) | `binance_api_key`, `binance_ed25519_private_key`를 O_RDONLY로 각각 open → 추적이 헛돌지 않는다 |
| A4: A 쪽 시험 모음 전체(`bot/tests`, 445개)를 strace 아래 실행 | 키 읽기 open 0. 처음 실행 때는 `config/orders_control.example.toml` 1건이 잡혔다. 이것은 저장소 견본 파일이고, 비밀 스캔 시험이 `git ls-files` 전체를 읽은 것이다. 스크립트에서 저장소 견본(`config/*.example.toml`)을 비밀 아님으로 분류한 뒤 다시 실행해 전부 통과했다 |
| 키 문자열 유출 | DB 파일(WAL 포함)·A가 보낸 텔레그램 텍스트·B 로그 어디에도 키 ID나 PEM 본문이 없다 |

compose도 확인했다. `binance_*` secrets·제어 파일·`ordersstate`(원장)는 `orders` 서비스에만 붙고, `bot`(A)에는 없다.
텔레그램 명령은 `status/positions/pause/resume/help` 5개뿐이고 주문 명령은 없다. `/resume`은 T0를 풀지 않는다.
`mode = "live"`는 `config.py`가 거부한다.

## 7. 실제 테스트넷(데모)에서 사용자가 확인할 항목 (이 컨테이너에서는 확인할 수 없음)

- **P-1** 정상 경로의 실제 무방비 구간이다. 데모에서 체결부터 손절 조회 확인까지 걸린 시간(`order_intents.unprotected_ms`)을
  10회 이상 재서 5초 한도와 비교한다(여기서는 로컬 5–21ms).
- **P-2** Ed25519 서명이 데모에서 실제로 받아들여지는지 확인한다(T4 selftest의 서명 조회 통과). recvWindow 5000과 timestamp 순서도 함께 본다.
- **P-3** K1이다. 포지션 0에서 closePosition STOP_MARKET을 선배치할 수 있는지, 포지션이 닫히면 자동 취소되는지 본다.
  가능하면 `pre_entry`로 V1의 '체결 직후 크래시' 무방비를 0으로 만들 수 있다.
- **P-4** K2·K4·K7이다. `POST /fapi/v1/algoOrder`(algoType=CONDITIONAL, triggerPrice, clientAlgoId, closePosition,
  workingType=MARK_PRICE, priceProtect=false)가 접수되는지, 조회 응답의 필드와 값이 대조 규칙과 맞는지 본다. `openAlgoOrders`와
  `algoOrder` 조회 경로도 확인한다.
- **P-5** K3이다. 데모 호스트 `demo-fapi.binance.com`이 맞는지, 구 테스트넷이 아닌지 본다.
- **P-6** K5다. 손절이 발동한 뒤 algo 상태 값, 실제 주문 ID와 체결가 연결, 종료된 algo 주문을 조회할 수 있는 기간을 본다.
- **P-7** K6·K12다. IOC 부분 체결 응답 모양과, 주문 접수부터 조회에 보이기까지의 지연(GRACE 2초의 근거)을 본다.
- **P-8** K8·K9·K10이다. symbolConfig·positionRisk·positionSide/dual·multiAssetsMargin 조회가 되는지, 출금 권한 조회가 되는지 본다.
  출금 권한은 LIVE 전에 반드시 확인한다.
- **P-9** K11이다. BTCUSDT minQty·minNotional, 그리고 -4164 문구를 본다.
- **P-10** K14·K15다. 청산 뒤 closePosition 손절이 자동 취소되는지, 끝난 시장가 주문의 clientOrderId(f1–f3)를 다시 쓸 수 있는지 본다.
  재사용이 거부되면 두 번째 청산 주기부터 청산이 불가능해진다. 이 경우 V-2와 합쳐 보호가 손절 재등록에만 의존하게 된다.
- **P-11** K16이다. `GET /fapi/v1/income` REALIZED_PNL로 T2를 계산할 수 있는지 본다.
- **P-12** 오류 코드 분류가 실제 응답과 맞는지 본다. -1021(시각), -2019(증거금), -4120(algo 창구), -4164(최소 명목),
  -2021(즉시 발동), 429의 Retry-After 헤더 유무, 418·451 응답 모양이 대상이다.
- **P-13** compose 실물 분리다. `docker compose exec bot ls /run/secrets /control /state`에는 키·제어 파일·원장이 **없어야** 하고,
  `orders` 컨테이너에서는 uid 10001로 키를 읽을 수 있어야 한다(호스트 파일 chown 10001, chmod 400). 비 swarm compose의 secrets는
  바인드 마운트라서 호스트 권한이 그대로 보인다.
- **P-14** 실제 강제 종료 복구 시간이다. 데모에서 작은 보유 중에 `docker kill -s KILL <orders>`를 해서 재기동과 복구까지
  몇 초 걸리는지 잰다(V1의 '중단 + 0.7초'가 실제로 몇 초인지). 체결 직후 창은 재현이 어려우므로 STOP_VERIFIED 상태에서 한다.
- **P-15** `ordersstate` 볼륨의 권한(0700, uid 10001)과 원장 파일(0600)을 확인한다. 이미지를 다시 빌드해야 한다.
- **P-16** 서버 시계다. `timedatectl`로 동기화를 확인하고, 서버 시각 차가 1000ms 안인지 본다.
- **P-17** V-1·V-2를 고치기 전 운영 수칙이다. B가 `DB`나 `설정` 오류로 재시작을 반복하면 **즉시 거래소 웹에서 포지션과 손절을
  확인**한다.

## 8. 재현 명령

```
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m bot.orders.verify.firewall_limits            # results/firewall_limits.json (V2)
.venv/bin/python -m bot.orders.verify.kill_restart_sim --random 12   # results/kill_restart.json (V1, 약 9분)
.venv/bin/python -m bot.orders.verify.key_access_trace           # results/key_access_trace.json (V3, strace 필요, 약 8분)
.venv/bin/python -m bot.orders.verify.fuzz_extended --start 1000 --count 9000 --jobs 4   # results/fuzz_extended.json (V4)
.venv/bin/python -m bot.orders.verify.startup_refusal_probe      # results/startup_refusal.json (V-1 재현, 종료 코드 1 = 재현됨)
```

검증관이 시험용 스크립트를 고친 것은 두 가지다. `key_access_trace.py`에서는 저장소 견본 `config/*.example.toml`을 비밀 아님으로
분류하도록 바꿨다. `fuzz_extended.py`에서는 강제 종료가 없는 경우를 따로 집계하도록 바꿨다.

---

## 9. 2차 검증 (V-1·V-2 수정 R-15·R-16 확인)

### 9.1 시험 모음
```
.venv/bin/python -m pytest -q -p no:cacheprovider                  → 1588 passed in 290s (검증관 스크립트 수정 뒤 재실행)
.venv/bin/python -m pytest bot/orders/tests/test_verify_fixes.py -v → 13 passed
```
처음 전체 실행에서 1건이 실패했다(`review_security_test::test_nothing_outside_gateway_calls_exchange_order_methods`).
원인은 검증관이 새로 만든 `rescue_edge_probe.py`가 가짜 거래소의 `place_conditional`을 직접 부른 것이었다. 이 보안 시험은
bot/ 전체에서 주문 메서드 직접 호출을 금지한다. 스크립트를 `plant_foreign_order`로 바꾼 뒤 다시 실행해 통과했다. 제품 결함은 아니다.

### 9.2 V-1 — 시작 거부 전 DB 없는 보호 (`worker.main` → `gateway.protect_without_db`)
코드 검토:
- 거부 경로 다섯 곳(A 비밀 보임, DB 연결 실패, 시작 중 DbError, 시작 중 그 밖의 예외, Worker 생성 실패)이 모두 `refuse()`를 거친다.
  run이 아닌 명령(selftest·status)은 보호 없이 거부한다.
- 단일 인스턴스 잠금은 DB 연결보다 먼저 잡는다. 다른 B가 잠금을 쥐고 있으면 구조를 하지 않는다.
- 구조 주문은 방화벽 FLATTEN을 거치고, reduceOnly·SELL·MARKET·`sig-<새 ID>-f1..f3`이다. 3번마다 새 신호 ID를 써서 clientOrderId를 재사용하지 않는다.
- 남는 거부 경로가 있다. 설정 파일 로드 실패, 키 파일 읽기 실패, 비밀 환경 변수, mode ≠ testnet이다. 이때는 거래소 클라이언트를 만들 수 없어 구조가 불가능하다. 설계상 한계로 보고 RUNBOOK T8(웹 확인)로 대응한다.

재현·측정:
- `startup_refusal_probe`(수정 담당 판): main 경로에서 트리거를 지우면 종료 3, 포지션 0이다. 대조군도 포지션 0이다. 검증관이 다시 돌려 같은 결과를 얻었다.
- **실제 프로세스 S12**(`kill_restart_sim`): 진입 체결 직후 SIGKILL을 보내고, 죽은 동안 보호 트리거를 지운 뒤 1초 뒤 재시작했다.
  B는 종료 3으로 끝났고, 그 전에 `f1` 1건으로 청산했다. 거래소 기준 무방비는 **1,745ms**(= 중단 1초 + 기동 약 0.7초)였다.
  compose처럼 한 번 더 재시작해도 종료 3이었고 **추가 주문은 0**이었다. 끝 상태는 포지션 0이다.
- 경계 사례 20가지(`rescue_edge_probe`, `results/rescue_edge.json`):

| 장면 | 결과 | 끝 포지션 |
|---|---|---|
| 손절 없음(기본) | flattened, 주문 1 | 0 |
| 우리 손절 살아 있음 | protected, 주문 0 | 0.016 + 손절 유지 |
| 웹에서 건 남의 손절만 있음 | flattened(우리 것 아님 → 보수적으로 청산) | 0 |
| 조건부 목록 조회 실패(우리 손절 있음) | flattened(확인 불가 → 청산, fail-closed) | 0 |
| f1 지연 도착 3초 · 응답 유실 · 체결 표시 지연 · 부분 체결 · -4164 ×5 | 모두 flattened. 숏 0, ID 재사용 0 | 0 |
| 429(Retry-After 5초) | 5.35초 기다린 뒤 flattened | 0 |
| 주문 계속 거부(-2019) | 60초 뒤 failed(주문 61건, 모두 새 ID) | 0.016 → 운영자 경보 |
| 포지션 조회 5xx·연결 끊김·418 장기 | 60초 뒤 unavailable(주문 0) | 0.016 → 운영자 경보 |
| 401 | 즉시 unavailable | 0.016 → 운영자 경보 |
| 숏 포지션 | short, 주문 0 | 그대로 |
| **주문 POST만 계속 '결과 모름'(TIMEOUT_BEFORE·503)** | **잠 없이 반복**. 호출 상한 2,000에서 멈췄다(주문 500건) | 0.016 |

### 9.3 V-2 — HALTED 무방비 매 바퀴 재보호 (`Worker._run_once` → `quick_unprotected_check` → `secure_halted`)
- `fuzz_extended`를 시드 1000–9999로 다시 돌렸다. 끝 상태 위험 **0**이다. 무방비 최대 분포는 0초 7,567 · 5초 이하 1,240 · 5–6초 173 · 6–10초 20 · **10초 초과 0**이다
  (수정 담당 보고와 같다). 강제 종료가 없는 경우의 최악은 9531(4.8초)과 3016(4.6초)이다. 6초를 넘는 것은 모두 강제 종료 + 5초 중단이 섞인 경우다(최악 1110, 7.6초).
- **정밀 재측정**(`fuzz_exact`, V-3 대응): `FakeExchange._process`(시계 진행·늦은 도착·체결·발동) 끝마다 표본을 떴다. 같은 9,000개에서
  분포와 최악 시드가 **똑같았다**. 수정 뒤에는 HALTED 동안에도 B가 2초마다 거래소를 부르므로 V-3의 과대 추정이 사라졌다.
- 방향성 시험(`halted_query_fail_probe`, `results/halted_query_fail.json`). 장면은 HALTED이고 손절이 없는 상태다. 그 뒤 거래소가 회복된다.

| 회복 뒤 장애 | 대조 주기 | 보호까지 |
|---|---|---|
| 없음 | 30초 | 2.3초 |
| 손절 등록이 계속 사라짐(청산은 됨) | 30초 | 2.3초 |
| **get_conditional 503 계속** | 30초 / 10초 | **28.3초 / 8.3초** |
| get_conditional + openAlgoOrders 503 계속 | 30초 / 10초 | 28.3초 / 8.3초 |
| 포지션 조회 503 ×5 | 30초 | 12.3초 |

### 9.4 새 발견
**V-7 (낮음) 구조 루프가 '결과 모름' 뒤에 잠들지 않는다**
- 위치: `gateway.protect_without_db`. `place_order`가 `outcome_unknown`으로 끝나면 `flattened_once = True; continue`로 곧바로
  다음 바퀴(포지션 → 마크 → 조건부 목록 → 새 ID로 POST)를 돈다. 확정 오류 경로(`wait_err`)와 정상 경로(`CLOSE_POLL_SLEEP_MS`)는 잠든다.
- 실제 클라이언트는 5xx를 OUTCOME_UNKNOWN으로 분류한다. 그래서 바이낸스가 주문 창구에서 빠르게 503·-1007을 돌려주는 동안(변동성 큰 때 흔하다)
  60초 기한까지 RTT마다 요청 4개와 주문 1건을 보낸다. reduceOnly라 숏은 생기지 않았다(모든 경계 사례에서 숏 0). 결국 429에 걸리면 기다리므로
  무한은 아니다. 다만 가중치를 낭비하고, 늦게 도착한 주문이 많이 쌓인다.
- 권고: 결과 모름 뒤에도 `sleep_ms(CLOSE_POLL_SLEEP_MS)`(또는 1초)를 둔다.

**V-8 (낮음–중간) HALTED 무방비 + 손절 단건 조회만 실패 → 다음 대조까지 기다림**
- 위치: `Gateway.quick_unprotected_check`. `get_conditional`이 실패하면 '판단 보류'로 False를 돌려준다. 그러면 HALTED 보유를
  `reconcile_interval_s`(견본 10초, 설정 상한 30초)까지 두게 된다. 그런데 `secure_halted`는 같은 조회가 실패하면 '보호 아님'으로 보고
  청산한다. 그러므로 이 경우 매 바퀴 `secure_halted`를 불러도 fail-closed 방향이 맞다.
- 이 조합은 현실성이 있다. 조건부(algo) 창구 장애가 나면 손절 등록이 실패하고(그래서 HALTED 무방비가 된다), 같은 창구의 조회도 함께 실패하기 쉽다. 반면 일반 주문 창구(청산)는 멀쩡할 수 있다.
- 측정: 8.3초(견본 10초 주기)와 28.3초(30초 주기). I2(5초)를 넘는다. 1차 V-2의 31초보다 조건이 좁다.
- 권고:
  - HALTED 의도에서 조건부 조회가 실패하면 포지션만 확인해서, 포지션 > 0이면 True를 돌려준다(secure_halted가 판단한다).
  - 또는 flatten()이 `stop_rearmed=False`로 끝난 의도를 메모리에 표시해 두고, 손절이 **확인될 때까지** 매 바퀴 secure_halted를 돈다.
  - 설정 검증기의 `reconcile_interval_s` 상한을 10으로 낮추는 것도 완화가 된다.

**V-9 (정보) 문서**
- `bot/orders/DESIGN.md` §16.1: R-14와 R-15 사이에 빈 줄이 있어 R-15·R-16 행이 표 밖으로 떨어진다(렌더링하면 머리글 없는 줄이 된다).
- `docs/RUNBOOK.md` T8의 새 행은 '종료 코드 2·3으로 계속 재시작'이라고 적었다. 그런데 시작 복구 중 예외가 나면 종료 1로도 끝난다(`startup:<예외>`). 1도 넣어야 한다.

**기존 항목 상태**: V-3은 정밀 측정으로 확인해 해소했다(수정 뒤 분포가 같다). V-4는 그대로이고 보수적이다. 구조 청산 뒤 재시작해도 CLOSED(external) + T0가 된다.
V-5(SEC-06)는 그대로다. 구조 결과는 stderr·로그에는 항상 남지만, 텔레그램에는 A와 outbox가 살아 있을 때만 간다. V-6은 RUNBOOK T8에 반영됐다.
체결 직후 강제 종료의 무방비(중단 + 약 0.7초)는 그대로이고, K1 pre_entry만 없앨 수 있다.

### 9.5 키 분리 재확인
`key_access_trace`를 다시 실행했다(`results/key_access_trace.json`, 종료 0). A1(키를 둔 A는 시작 거부, stat만 함)·A2·A3(실제 B 자식까지 CLOSED)·A4(A 쪽 시험 모음)에서 키 읽기 open은 0이었다. 양성 대조 B0에서는 키 두 파일을 여는 것이 보였다. 키 원문 유출도 0이다. 수정으로 바뀐 것은 B의 main뿐이다. A 비밀이 보이는 경우에도
B는 자기 키 두 파일만 읽고 구조한 뒤 종료 2로 끝난다(`test_v1_a_secret_visible_refusal_also_protects`).

### 9.6 실제 테스트넷에서 확인할 것(2차 추가·변경)
- **P-4 보강**: `GET /fapi/v1/algoOrder` 단건 조회가 장애일 때 `openAlgoOrders`와 일반 주문 창구가 따로 사는지 본다(V-8의 현실성).
  구조(protect_without_db)의 `open_conditional_orders`가 실제 algo 응답에서 우리 손절을 알아보는지도 본다(clientAlgoId·closePosition·side·type 필드).
- **P-12 보강**: 주문 POST가 503이나 -1007을 줄 때 응답 시간이 얼마인지 본다(V-7의 반복 속도).
- **P-17 변경**: `orders`가 종료 1·2·3으로 재시작을 반복하면, 로그의 `거래소 포지션 보호 결과`를 먼저 본다. 결과가 `flat`·`flattened`·`protected`가 아니면
  **즉시 거래소 웹에서** 포지션과 손절을 확인한다. `flatten_failed` T0가 오면 여전히 웹부터 본다(V-8).
- **P-18(신규)**: 데모에서 작은 포지션을 연 뒤 B를 멈춘다. 손절을 웹에서 지우고, DB 트리거 하나를 지운 채 B를 재시작한다. 종료 3과 `flattened`,
  그리고 f1 주문 ID(`sig-<새 ID>-f1`)가 거래소에서 reduceOnly 시장가로 체결되는지 확인한다. 끝나면 DB를 복원하고 제어 파일로 T0를 해제한다.

### 9.7 재현 명령(2차)
```
.venv/bin/python -m bot.orders.verify.startup_refusal_probe                 # V-1(main 경로) — 종료 0 = 보호됨
.venv/bin/python -m bot.orders.verify.rescue_edge_probe                     # results/rescue_edge.json — 종료 1 = V-7 재현
.venv/bin/python -m bot.orders.verify.halted_query_fail_probe               # results/halted_query_fail.json — 종료 1 = V-8 재현
.venv/bin/python -m bot.orders.verify.fuzz_extended --start 1000 --count 9000 --jobs 3   # 약 10분
.venv/bin/python -m bot.orders.verify.fuzz_exact --start 1000 --count 9000 --jobs 4      # results/fuzz_exact.json, 약 9분
.venv/bin/python -m bot.orders.verify.kill_restart_sim --random 12          # S12 포함 27개, 약 10분
```
