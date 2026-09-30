# backtest 설계서 — G1 백테스트 엔진

> 기준 문서: `docs/RULES_SPEC.md` **v1.0 (고정)** · 작성 2026-09-30 (설계 담당)
> 우선순위: **명세 §12 > 명세 §1~§11 > 이 문서 §7 해석 확정(I-번호) > 이 문서의 나머지.**
> 이 문서가 명세와 어긋나 보이면 명세를 따르고 리드에게 알린다. 명세 파일은 절대 고치지 않는다.

---

## 0. 목적과 품질 기준

- **목적**: 진입 시나리오 4종(L1a·L1b·S2·S3) × 방향 필터 2종(DA·DB) × 봉 설정 2종(P1·P2) = **16조합**이 무작위 진입보다 나은지 판정한다(G1, §8.3).
- **품질 기준 (우선순위 순)**
  1. 미래 참조(look-ahead) 없음 — §4 계약
  2. 명세와 정확히 일치 — §7 해석 확정
  3. 체결·비용을 부풀리지 않음 — 애매하면 불리한 쪽
  4. 결정적 — 같은 입력이면 같은 결과, 난수는 시드 고정(§3.5)
- 애매한 곳을 새로 만나면 **성과를 부풀리지 않는 쪽**을 고르고, 반환값 `decisions`에 "어디가 애매했고 무엇을 택했는지"를 적는다.

## 1. 파일과 담당

| 파일 | 담당 | 상태 |
|---|---|---|
| `config.py` | 설계 | **구현 완료** — 명세 숫자 전부, `ComboConfig`, 조합 목록, 공용 소형 함수 |
| `types.py` | 설계 | **구현 완료** — 표준 프레임, `Plan`·`TradeResult`·`SignalLog`·`Candidate` 등 |
| `DESIGN.md` | 설계 | 이 문서 |
| `tests/conftest.py`, `tests/__init__.py`, `tests/test_design_contracts.py` | 설계 | **구현 완료** — 합성 데이터 도우미, 설계 계약 테스트 |
| `data.py`, `indicators.py`, `tests/test_data.py`, `tests/test_indicators.py` | 데이터·지표 | 스텁 |
| `execution.py`, `random_baseline.py`, `tests/test_execution.py`, `tests/test_random_baseline.py` | 체결 엔진 | 스텁 |
| `metrics.py`, `baselines.py`, `tests/test_metrics.py`, `tests/test_baselines.py` | 통계·기준선 | 스텁 |
| `structure.py`, `filters.py`, `scenarios.py`, `tests/test_structure.py`, `tests/test_filters.py`, `tests/test_scenarios.py`, `tests/test_no_lookahead.py` | 구조·시나리오 | 스텁 |
| `run_g1.py`, `report.py`, `README.md`, `tests/test_integration.py` | 통합 | 스텁 |

- 자기 파일만 고친다. 다른 파일 수정이 필요하면 고치지 말고 `open_issues`에 적는다(통합 담당은 인터페이스 불일치 해결을 위한 최소 수정 허용, 모두 기록).
- 공개 함수의 **시그니처는 스텁 파일이 기준**이다. 바꾸려면 리드와 합의한다. 내부 도우미(`_이름`)는 자유.
- `config.py`·`types.py`의 이름·형식은 계약이다. 바꿔야 하면 리드에게 요청한다.

## 2. 데이터 흐름

```
data/binance/*.csv.gz
   │  data.load_market()                         캐시: data/cache/*.npz
   ▼
MarketData ── bars{'15m','1h','4h','1d'}  exec_bars(5분 | 1분 병합)  funding(+2026-09 대체값)  events_ns(None)
   │
   │  scenarios.build_context(market, setting, vr_threshold)      ← (P1|P2, VR 2|3)마다 1회, 캐시
   │     S·D 봉: indicators.compute_indicators → structure.build_structure (스윙·기준봉·마디·허리·생존)
   │     S 봉  : filters.fixed_filter_flags (F2·F4·F5·F6)
   ▼
ScenarioContext
   │  scenarios.generate_candidates(ctx, cfg)                     ← 조합 cfg마다
   │     후보 시점 탐지 → WARMUP·SC_* → 가격 계산(Plan: active_from·valid_until·cancel_effective_time)
   │     → filters.filter_reasons (F1 방향 as-of, F2~F7) → filters.risk_reasons (RISK_*)
   ▼
list[Candidate]  (I-37 순서로 정렬, 사유는 미리 계산된 것만)
   │  execution.run_sequence(cands, xb, fa, cfg)                  ← 'all' / 'exec' 모드 각각, 비용 2배는 같은 후보로 한 번 더
   │     순차: F8 → F9 → [exec 모드] MASK_DND → MASK_DAILY_CAP → simulate_plan (체결·청산·비용·펀딩·R)
   ▼
trades: list[TradeResult]   logs: list[SignalLog]
   │  metrics.summarize_run / random_baseline.run_random_baseline / metrics.g1_verdict / metrics.deflated_sharpe
   │  baselines.donchian_ensemble (일봉)
   ▼
run_g1 → backtest/results/g1_results.json, trades_<key>.csv, signals_<key>.csv, TRIALS.md 한 줄
   ▼
report.write_report → backtest/results/G1_REPORT.md
```

## 3. 공통 규약

### 3.1 시각
- 내부 시각은 모두 **int64 나노초, UTC epoch**. 문자열·Timestamp는 입출력 경계에서만 쓴다(`config.ts_ns`, `config.ns_to_iso`).
- 봉 시각 = **시작 시각** `open_ns`. **`close_ns = open_ns + 봉 길이`**(봉이 끝나는 순간). 바이낸스 `close_time`(−1ms)은 쓰지 않는다.
- **봉 사용 가능 시각 = `close_ns + 60초`** (`config.AVAIL_DELAY_NS`, §1·§12.1).
- 계획의 시각:

| 이름 | 정의 |
|---|---|
| `signal_time` | 신호 봉 마감 `close_ns[t]` (L1b는 확인 봉 C 마감) — 명세의 "신호 시각" |
| `approval_time` | `signal_time + 60초` — 판단·승인 요청 시각. 가용성 마스크·F8·F9·정렬 기준 |
| `active_from` | `approval_time + 지연 L` — 이 시각 **이후에 시작하는** 실행 봉부터 체결 가능 |
| `valid_until` | 지정가: `signal_time + N × 신호 봉 길이` (§12.1) / `ioc_cap`·`market`: `active_from` |
| `cancel_effective_time` | 취소 조건이 처음 성립한 신호 봉 k의 `close_ns[k] + 60초` (없으면 None) |

- 하루 경계는 UTC 00:00(연도·달 통계). 가용성(방해 금지, 하루 6건)만 KST(UTC+9)다.
- **pandas 3 주의**: `pd.to_datetime(x, unit='ms')`는 단위가 ms, `date_range`는 us다. `DatetimeIndex.asi8`는 그 단위 그대로 나온다. 정수 시각은 반드시 `open_ns`/`close_ns` 열이나 `Timestamp.value`(항상 ns)에서 얻고, 인덱스를 만들 땐 `.as_unit('ns')`.

### 3.2 표준 프레임 (`types.py`가 단일 출처)

**봉 프레임** — `types.make_bars_frame`으로 만들고 `types.check_bars_frame`으로 검사한다.

| 항목 | 형식 |
|---|---|
| 인덱스 | `DatetimeIndex`, tz=UTC, unit=ns, 이름 `open_time`, 엄격히 증가 |
| `open, high, low, close, volume` | float64 |
| `open_ns, close_ns` | int64 ns |

신호·방향·확인 봉은 길이가 고정이고, 실행 봉은 5분/1분이 섞인다. 실데이터에 빈 구간·중복은 없다(`quality_report.json`).

**펀딩 프레임** — `time_ns`(int64, 정시로 내림) · `rate`(float64) · `synthetic`(bool, 대체값 여부), RangeIndex.
**지표 프레임** — 열 `indicators.INDICATOR_COLUMNS`(§6.4), 인덱스 = 봉 프레임 인덱스.
**마디 표** — 열 `types.MADI_COLUMNS`(§6.5).
**배열 묶음** — `types.ExecArrays`(실행 봉), `types.FundingArrays`(펀딩): 체결 엔진·무작위 기준선이 쓰는 numpy 배열.

### 3.3 봉 번호
- 지표·구조 배열은 그 간격 봉 프레임의 **위치 번호**(0..n−1)와 길이·순서가 같다. 문서의 t·i·k·j는 위치 번호다.
- 간격 사이의 대응은 **항상 as-of**로 한다: `config.asof_index(close_ns + AVAIL_DELAY_NS, 판단 시각)` (§4 C-2).

### 3.4 가격
- `config.round_price` = `np.round(x, 1)` (0.1 USDT). 반올림 대상: 허리 H, 계획의 진입·손절·목표가, L1b 상한가, 무작위 기준선의 손절·목표. **A·B·W와 지표 값은 반올림하지 않는다** (I-14).

### 3.5 결정성
- 난수는 `config.make_rng(*문자열)`로만 만든다(RANDOM_SEED + crc32). 파이썬 `hash()` 금지(실행마다 바뀜).
  - 부트스트랩 `make_rng('bootstrap', key)`, 순열 `make_rng('perm', key)`, 무작위 기준선 `make_rng('random_baseline', key)`. `key = ComboConfig.key`.
- 정렬은 안정 정렬(`np.argsort(kind='stable')`)과 명시한 동률 규칙(I-37 등)으로 한다.
- 조합을 여러 프로세스로 나눠 돌려도 결과가 같아야 한다(조합 사이에 난수 상태를 공유하지 않는다).
- `g1_results.json`은 `created_utc`·`runtime_sec`를 빼면 두 번 돌려도 같아야 한다.

### 3.6 pandas 3 / numpy 2
- copy-on-write가 항상 켜져 있다. `df['c'].to_numpy()`는 **읽기 전용**일 수 있다 → 고치려면 `.to_numpy(copy=True)`. 연쇄 대입(`df['a'][i] = …`) 금지.
- 계산은 numpy 배열로. 파이썬 반복은 후보·마디·계획 단위까지만(봉 단위 반복은 성능 목표를 넘기 쉽다).
- scipy·numba·pyarrow·matplotlib이 없다. 새 패키지 설치 금지. 정규분포는 `statistics.NormalDist`. 캐시는 `.npz`.

### 3.7 코드 스타일
- 읽기 쉬운 코드, 짧은 한국어 docstring, 핵심 계산 줄에 근거 주석(예: `# RULES_SPEC §4.3, I-13`).
- 숫자는 `config`에서 가져온다(매직 넘버 금지).
- 실행은 저장소 루트에서 `python -m backtest.…`. `types.py`가 표준 라이브러리 `types`와 이름이 같으므로 `backtest/` 안에서 파일을 스크립트로 직접 실행하지 않는다.

## 4. 미래 참조 금지 계약 (모든 담당 필수)

| # | 계약 |
|---|---|
| C-1 | 신호 봉 t에 대한 판단은 `close_ns[t] + 60초`에 하며, 모든 간격에서 `close_ns ≤ close_ns[t]`인 봉만 쓴다. |
| C-2 | 다른 간격 봉 X는 `close_ns[X] + 60초 ≤ 판단 시각`일 때만 쓴다: `asof_index(close_ns + AVAIL_DELAY_NS, 판단 시각)`. 진행 중인 봉 금지. 예: 1H 봉 03:00~04:00의 판단(04:01)에는 00:00~04:00 4H 봉을 쓸 수 있다(I-1). |
| C-3 | "최근 n개 평균"·분위는 현재 봉을 뺀 `[t−n, t−1]`. 현재 봉 자신의 값(종가·거래량)은 쓸 수 있다. |
| C-4 | `is_sh[i]`·`is_sl[i]`는 봉 i+3 마감 전 사용 금지. 시점 t에서는 `last_sh[t]`·`last_sl[t]`(i+3 ≤ t)만 쓴다. |
| C-5 | 마디는 `tb_idx` 봉 마감 전에는 없는 것이다. 허리는 `a_idx..b_idx` 봉만으로. "살아 있음"은 t까지의 종가만으로. |
| C-6 | 신호 봉 k의 정보로 성립한 취소는 `close_ns[k] + 60초`부터 효력. 그 전 체결은 유효. 체결 엔진은 이 시각 말고 신호 봉 데이터를 보지 않는다. |
| C-7 | 진입은 `active_from` 이후 **시작하는** 실행 봉부터, 봉 전체가 주문 수명 안에 있어야 인정(I-31). |
| C-8 | 체결 봉에서는 손절만 보고 목표는 다음 봉부터. 청산은 앞으로만 훑는다. |
| C-9 | 순차 상태: F8은 승인 시각 전에 끝난 손절만, F9는 직전 계획의 `busy_until`, 하루 6건은 그날 이미 보낸 요청만 본다. |
| C-10 | `valid`가 False인 봉, as-of 결과가 −1인 곳에서는 신호를 내지 않는다(§12.3). |
| C-11 | 전체 기간 평균·분위·최댓값처럼 미래가 섞인 통계를 신호에 쓰지 않는다(판정 뒤 비교용 통계·무작위 기준선의 "그 달" 추출은 예외). |
| C-12 | `tests/test_no_lookahead.py`의 절단·미래 변경 테스트가 통과해야 한다(§9 T-NLA). |

## 5. 실행 봉 병합 규칙 (§12.1)

- `open_ns < 2023-10-01 00:00 UTC`(`config.EXEC_SWITCH_NS`)는 5분봉 파일, 그 이상은 1분봉 파일(연도별 4개)을 쓴다. 이어 붙여 **하나의 실행 봉 프레임**으로 만든다.
- 경계: 마지막 5분봉 2023-09-30 23:55의 `close_ns` = 첫 1분봉 `open_ns`(2023-10-01 00:00). 겹침·빈 구간 없음. 합계 394,272 + 1,575,360 = **1,969,632봉**.
- 봉 길이가 섞이므로 시각 계산은 항상 `open_ns`/`close_ns`로 한다(봉 개수 × 길이로 계산 금지).
- 5분봉 구간의 효과(보수적): `active_from`이 5분 경계가 아니면 다음 5분봉부터 체결, 취소·만료 시각을 넘는 봉은 체결 불인정(I-31).
- 한 실행 봉 안에서 손절·목표를 둘 다 건드리면 **손절 먼저**(1분·5분 모두, §12.1이 §8.2의 "1분봉으로 순서 판정"을 대체).
- 신호·방향·확인 봉(15m·1h·4h·1d)은 각 파일을 그대로 쓴다. §1의 "합쳐 만든다"는 파일이 없을 때 규칙이고 v1은 모두 있다. 5m→1h 비교의 몇 봉 불일치(quality_report)는 무시한다.

## 6. 모듈별 명세

공개 함수의 시그니처·docstring은 각 스텁 파일에 있다. 아래는 입출력과 세부 규칙이다.

### 6.1 `config.py` (구현 완료)
- 명세의 모든 숫자(절 번호 주석). 그룹: 경로 · 시간 · §2 봉 설정 · §3 · §4 · §5 · §6 · §7 · §8.1 · §8.2/§12 · §8.3 · §12.4.
- `ComboConfig(scenario, direction_filter, setting, latency_min=10, waist_method='cluster', vr_threshold=2.0, cost_multiplier=1.0, apply_availability_mask=True, event_filter_on=False, l1b_rearm=False)` (frozen, 값 검사). `l1b_rearm`은 L1b 전용 보고용 진단(I-22, 꼬리표 'rearm').
  - 속성: `bars`(S·D·C 이름), `side`, `order_type`, `latency_ns`, `s_dur_ns`, `max_hold_ns`, `base_key`('L1a-DA-P1'), `variant`('lat5','mid','vr3','cost2','ev'를 '_'로), `mode`('exec'|'all'), `key`('L1a-DA-P1_exec', 'S3-DB-P2_lat5_exec'), `replace(**)`, `as_dict()`.
- `g1_combos(apply_availability_mask=True)` → 16개(시나리오 → 방향 필터 → 봉 설정 순). `sensitivity_combos()` → 80개 `(꼬리표, 설정)`: 16조합 × {lat5, lat15, mid, vr3, cost2}, 모두 실행 가능 모드. `L1B_REARM_VARIANT = ('rearm', {'l1b_rearm': True})`는 명세 §9 목록 밖의 진단이라 80개에 넣지 않고, `run_g1.sensitivity_variants`가 L1b 조합에만 덧붙인다(보고만).
- 공용 소형 함수(단일 출처, 다른 곳에서 같은 식을 다시 쓰지 말 것):

| 함수 | 뜻 |
|---|---|
| `stable_seed(text)`, `make_rng(*parts)` | 결정적 시드·난수 생성기 |
| `ts_ns(x)`, `ns_to_iso(ns)` | 시각 변환 |
| `round_price(x)` | 0.1 반올림 |
| `entry_fee_rate(order_type)` | limit → 메이커 0.02%, ioc_cap·market → 테이커 0.05% |
| `c_stop_per_unit(entry, stop, rate)` | `rate × entry + (테이커 + 슬리피지) × stop` (§12.2) |
| `risk_per_unit(entry, stop, rate)` | d + c_stop, d = abs(entry − stop) = R 분모 (I-29: 리스크 검사는 계획가, 체결 뒤 R 분모는 실제 체결가) |
| `net_rr(side, entry, stop, target, rate)` | `(side × (target − entry) − rate × entry − 메이커 × target) ÷ risk_per_unit` (§12.2) |
| `kst_day_index(ns)`, `kst_minute_of_day(ns)`, `in_dnd(ns)`, `kst_session(ns)` | KST 날짜, 방해 금지 [00:30, 07:30), 보고용 시간대 |
| `asof_index(avail_ns, query_ns)` | `avail ≤ query`인 마지막 번호, 없으면 −1 |

### 6.2 `types.py` (구현 완료)
- 코드 값: `Reason`(사유 코드), `REASON_ORDER`(기록 순서 = 검사 순서), `PRECOMPUTED_REASONS`(WARMUP~RISK_RR), `SEQUENTIAL_REASONS`(F8~MASK), `Status`, `Exit`, `CANCEL_KINDS`.
- 프레임: `make_bars_frame`, `check_bars_frame`, `make_funding_frame`, `check_funding_frame`.
- 묶음: `ExecArrays`, `FundingArrays`, `MarketData`, `Structure`, `ScenarioContext`.
- 계획·결과: `CancelRule`, `Plan`(`order_end` = min(만료, 취소 효력)), `TradeResult`(`r_account`), `SignalLog`(`reason`), `Candidate`(plan 없으면 사유 필수).
- 도우미: `sort_reasons`, `records_frame`(CSV용), `to_jsonable`(NaN→None, ±inf→"inf"/"-inf").

### 6.3 `data.py` — 데이터·지표 담당
| 함수 | 입력 → 출력 | 규칙 |
|---|---|---|
| `load_klines(tf)` | 캔들 파일 → 봉 프레임 | `open_time`(ms)만 시각으로. `usecols=[open_time, open, high, low, close, volume]`. 중복·빈 구간 → ValueError. '1m'은 연도별 4개 파일 연결 |
| `load_exec_bars()` | → 실행 봉 프레임 | §5. `check_bars_frame(contiguous=True)` 통과 |
| `load_funding(until_ns)` | → 펀딩 프레임 | `calc_time`을 정시로 내림(오차 ≤ 47ms), rate = `last_funding_rate`. 대체값: 마지막 실제 기록 이후 & `≥ 2026-09-01 00:00` & `≤ until_ns`인 8시간 격자(00·08·16)마다 0.0001, `synthetic=True` (I-35) |
| `load_events(path)` | → int64 ns 배열 또는 None | 파일 없으면 None(F3 꺼짐). 형식 I-49 |
| `resample_bars(bars, tf)` | 봉 → 큰 봉 | §1 합치기, UTC epoch 경계, 불완전 구간 버림 |
| `load_market()` | → `MarketData` | bars(15m·1h·4h·1d), exec, funding(until = 실행 봉 마지막 close_ns), events |
| `data_fingerprint()` | → {파일: sha256} | 결과 JSON 기록용 |

- 캐시: `data/cache/`에만 `.npz`(배열: open_ns, open, high, low, close, volume + 원본 파일 이름·크기·수정 시각 서명). 서명이 다르면 다시 만든다. `cache_dir=None`이면 캐시 없이.
- 실데이터 사실(테스트에 씀): 1h 59,112봉(2020-01-01 00:00 ~ 2026-09-28 23:00), 4h 14,778, 1d 2,463, 15m 236,448, 5m 709,344, 1m 1,575,360, 펀딩 7,305행(마지막 2026-08-31 16:00), 대체 펀딩 85행(2026-09-01 00:00 ~ 2026-09-29 00:00).

### 6.4 `indicators.py` — 데이터·지표 담당
`compute_indicators(bars)` → 아래 열(`INDICATOR_COLUMNS`). "직전 n개" = `[t−n, t−1]`.

| 열 | 정의 | 첫 유효 t |
|---|---|---|
| `body`, `range` | \|c−o\|, h−l | 0 |
| `tr` | max(h−l, \|h−c[t−1]\|, \|l−c[t−1]\|), tr[0]=NaN | 1 |
| `atr` | 직전 14개 tr 평균 | 15 |
| `vol_avg`, `vr` | 직전 20개 거래량 평균, volume ÷ vol_avg | 20 |
| `body_avg`, `long_bar` | 직전 20개 몸통 평균, body ≥ 2 × body_avg | 20 |
| `upper_wick`, `lower_wick` | (h − max(o,c)) ÷ range, (min(o,c) − l) ÷ range, range 0이면 0 | 0 |
| `ma20`, `ma60`, `ma120` | 직전 n개 종가 평균 (I-2) | 20/60/120 |
| `spread` | (max(ma) − min(ma)) ÷ close[t] | 120 |
| `spread_q80`, `spread_on` | 직전 500개 spread의 80% 분위, spread ≥ 그 값 (I-3) | 620 |
| `slope20/60/120` | sign(close[t] − close[t−n]) ∈ {−1,0,1} (I-5) | 20/60/120 |
| `atr_q20` | 직전 100개 atr의 20% 분위 | 115 |
| `surge` | range ≥ 3 × atr (자기 봉 atr) | 15 |
| `buffer` | 0.1 × atr | 15 |
| `valid` | atr·vr·body_avg·ma120·spread_q80·slope120·atr_q20 모두 NaN 아님 | **620** |

- 분위는 numpy `linear`. 창 안에 NaN이 하나라도 있으면 NaN. bool 열은 NaN이면 False.
- 성능: `trailing_quantile`은 pandas `rolling(n).quantile(q, interpolation='linear')`를 `shift(1)`과 함께 쓰면 빠르다(naive와 1e-9 이내 일치 필수).

### 6.5 `structure.py` — 구조·시나리오 담당
- `find_swings` → `last_confirmed` → `detect_kijun` → `detect_madis`(허리 포함) → `paint_alive` → `build_structure`.
- **스윙**(I-6): high[i]가 앞뒤 3개 모두보다 **엄격히** 크다. i+3 봉 마감에 확정.
- **기준봉**(§4.1, I-7): 스텁 docstring의 식 그대로. `valid[t]`가 False면 아님. `last_sh[t] = −1`이면 아님.
- **마디**(§4.2, I-8~I-12): 기준봉 t마다 A = `last_sl[t]`의 low, B = t 이상에서 처음 스윙 고점(= B 봉은 기준봉 이후), `tb_idx = b_idx + 3 ≤ t + 60`. 무효: `close[a_idx..tb_idx]` 중 < A, W ≤ 0, a_idx < 20, 거래량 조건 실패. 같은 (방향, b_idx)는 가장 이른 기준봉 것 하나.
- **허리**(§4.3, I-13) 예시: A=100, B=110 → W=10, 구간 [103.5, 106.5], 칸 시작 = 103.5(A 쪽 끝), 폭 w = 0.1035, K = ceil(3/0.1035) = 29(마지막 칸은 106.5에서 잘림). 값 105.0 → 칸 14 = [104.949, 105.0525] → 가운데 105.00075 → H = 105.0.
- **살아 있음**(I-12): `tb_idx ≤ t ≤ min(death_idx − 1, tb_idx + 300)`. `paint_alive`는 마디 행 순서대로 칠해 "가장 최근(최대 tb_idx) 살아 있는 마디"를 준다.
- 마디 표 열(`types.MADI_COLUMNS`): madi_id(str), direction(int8), kijun_idx·a_idx·b_idx·tb_idx·death_idx·end_idx·tb_close_ns(int64), a_price·b_price·w·h_cluster·h_mid·vol_ab_mean·vol_pre_mean(float64), waist_fallback(bool). 행 순서 (tb_idx, kijun_idx). 마디가 없으면 열만 있는 빈 표.
- `madi_id = f"{tf}{U|D}-{B 봉 시작 %Y%m%d%H%M}"` (예 `1hU-202403011000`).

### 6.6 `filters.py` — 구조·시나리오 담당

| 필터 | 계산 위치 | 정의 (해석) |
|---|---|---|
| F1 | `direction_at` | §5. DA: D의 가장 최근 살아 있는 상승(하락) 마디가 있고 D 종가 >(<) 그 허리. DB: D 기울기 60·120 모두 +(−). D는 as-of(I-1). D 지표 워밍업 중에는 허용 안 됨 → F1 |
| F2 | `fixed_filter_flags` | vr < 0.7 and atr ≤ atr_q20 |
| F3 | `event_block` | `cfg.event_filter_on`일 때만. [e−2h, e+1h] (I-49) |
| F4 | `fixed_filter_flags` | spread_on |
| F5 | `fixed_filter_flags` | [t−5, t−1]에 surge (I-16) |
| F6 | `trap_counts` | 완성 봉이 [t−48, t−1]인 트랩 ≥ 2 (I-17) |
| F7 | `f7_block` | 롱: 살아 있는 하락 마디, 숏: 살아 있는 상승 마디 (S2 제외) |
| RISK_STOP_BAND | `stop_band_ok` | max(0.4%·entry, 1·ATR) ≤ d ≤ min(2%·entry, 3·ATR), 양 끝 포함 |
| RISK_RR | `risk_reasons` | `config.net_rr(…, entry_fee_rate(order_type))` < 1.5, 기본 비용 (I-27) |

- F2·F4·F5·F6·F7의 기준 봉 = 신호 봉(L1a·S2·S3) / `k_last`(L1b, I-15).
- 시나리오별 적용: L1a·L1b: F1~F7 / S2: F1~F6 / S3: F1~F7. F3은 모두 `event_filter_on`일 때만. F8·F9는 순차 엔진.

### 6.7 `scenarios.py` — 구조·시나리오 담당
- `build_context(market, setting, vr_threshold)` → `ScenarioContext` (설정·VR마다 한 번, `run_g1`이 캐시).
- `generate_candidates(ctx, cfg)` → 정렬된 `list[Candidate]`.

| | L1a (§7.1) | L1b (§7.2) | S2 (§7.3) | S3 (§7.4) |
|---|---|---|---|---|
| 후보 시점 | 상승 마디마다 t = tb_idx | C 봉 확인 이벤트 (마디당 첫 준비 1회, I-22) | 봉 t: 음봉, vr ≥ 2, close < H(가장 최근 살아 있는 상승 마디, 확정 **후**) | 봉 t: close < S and (vr ≥ 2 or 최근 10봉 두 번째 종가 이탈) |
| 필터 기준 S 봉 | t | k_last | t | t |
| SC 사유 | close ≤ H → SC_CLOSE_VS_WAIST, close[t] < close[t−60] → SC_SLOPE60, 건강 위반 → SC_UNHEALTHY | 건강 위반(k_last까지) → SC_UNHEALTHY | — | close ≥ 최근 상승 마디 허리 → SC_CLOSE_VS_WAIST, 목표 없음 → SC_NO_TARGET |
| 주문 | limit 매수 @ H | ioc_cap @ round(close_c × 1.001) | limit 매도 @ H | limit 매도 @ round(S) |
| 손절 | round(A − b[t]) | round(min(lowest, H) − b[k_last]) | round(max(high[t], H + 0.5·atr[t]) + b[t]) | round(S + atr[t]) |
| 목표 | round(H + W) | round(lowest + W) | round(A) | round(S 아래 가장 가까운 확정 스윙 저점) |
| 유효 | 24봉 | IOC(첫 실행 봉) | 12봉 | 12봉 |
| 취소(k = t+1..t+N) | close < A / high > B + 0.5W / 건강 위반 | 없음 | close > B | close > S |
| madi_id | 마디 | 마디 | 마디 | None |

- "건강 위반" = `mean(volume[b_idx+1..k]) ≥ vol_ab_mean` (§12.1, I-21).
- 세부 상태 기계(L1b)·지지선(S3)은 스텁 docstring과 I-22~I-25가 기준이다.
- `Plan.meta`·`SignalLog.meta`에 넣을 키(있는 것만): `s_idx`(필터 기준 S 봉), `tb_close_ns`(근거 마디 확정 시각, 없으면 0 — 정렬용, 필수), `A`, `B`, `W`, `H`, `waist_fallback`, `k_last`·`arm_idx`(L1b), `support_idx`(S3), `net_rr`, `d_pct`(= d ÷ entry).
- 폐기 후보에도 가격을 계산할 수 있으면 plan을 붙인다(진단용). `WARMUP`이면 plan=None, 사유는 `('WARMUP',)` 하나.

### 6.8 `execution.py` — 체결 엔진 담당

**진입** (`entry_window`, `find_entry`, I-30·I-31·I-44)
- `j0 = searchsorted(open_ns, active_from, 'left')`. 지정가: `j1 = searchsorted(close_ns, order_end, 'right')`, 체결 = [j0, j1)에서 롱 `low < 지정가` / 숏 `high > 지정가`인 첫 봉, 체결가 = 지정가(메이커).
- ioc_cap: 봉 j0 하나만. 롱 `open ≤ 상한`이면 open에 체결(테이커), 아니면 not_filled. market: open[j0]에 체결(테이커).

**청산** (`scan_exit`, I-32~I-34, I-36): 체결 봉 j_e부터
1. `j > j_e`이고 `open_ns[j] ≥ entry_time + max_hold_ns` → open[j]에 time 청산(테이커 + 슬리피지)
2. 손절 닿음(롱 `low ≤ stop`) → stop 청산(테이커 + 슬리피지). 청산가 = stop, 단 갭(`j > j_e` 또는 ioc_cap·market 체결 봉에서 시가가 이미 손절 너머) → open
3. `j > j_e`이고 목표 관통(롱 `high > target`) → target 청산(메이커). 같은 봉이면 손절 우선
4. 데이터 끝 → 마지막 봉 close에 eod(테이커 + 슬리피지)

**금액** (단위당, m = cost_multiplier): fees = (진입 수수료율 × 진입가 + 청산 수수료율 × 청산가) × m, slippage = 0.0002 × 청산가 × m (stop·time·eod), funding = Σ(지불 × m, 수취 × 1) (창 = `funding_start(order_type, 진입 봉 시작, active_from)` < f ≤ 청산 봉 시작, I-35), gross = side × (청산가 − 진입가), net = gross − fees − slippage − funding, `risk_per_unit = config.risk_per_unit(실제 진입가, plan.stop, entry_fee_rate(order_type))` (지정가는 = 계획가, I-29), `r_multiple = net ÷ risk_per_unit`, `size_fraction = min(1, 0.6 × 계획 위험 ÷ (0.005 × plan.entry_price))` (계획 위험 = `risk_per_unit(plan.entry_price, …)`, 수량은 계획 시점). 미체결이면 risk_per_unit = 계획 위험(참고값).
- 즉시 체결될 지정가(체결 봉 = j0이고 시가가 이미 지정가 너머): §12.1대로 지정가·메이커로 체결하되 `meta['marketable_open']`(시가)·`meta['marketable_edge_r']`(`marketable_edge` ÷ R, 양수 = 엔진이 테이커 즉시 체결보다 유리)를 남기고 `metrics.summarize_run`의 `marketable_limit`에 요약한다(검토 LA-2·F4).

**상태와 busy_until** (I-48)

| status | 뜻 | busy_until |
|---|---|---|
| filled | 체결 | 청산 봉 close_ns (= exit_bar_close_ns) |
| cancelled | cancel_effective_time < valid_until 이고 그 전에 체결 없음 | order_end |
| expired | 만료까지 체결 없음 | order_end (= valid_until) |
| not_filled | IOC 실패 / 실행 봉 없음 | 시도 봉 close_ns / active_from |

**순차 처리** (`run_sequence`, §12.3)
```
busy_until = −∞; stops = {madi_id: [exit_bar_close_ns…]}; requests = {KST 날짜: 수}
for cand in candidates:                              # 이미 I-37 순서
    if cand.log.reasons: 기록(그대로); continue
    p = cand.plan; D = p.approval_time
    if p.madi_id and #{s ∈ stops[p.madi_id] : s ≤ D} ≥ 2:     폐기 F8
    elif D < busy_until:                                      폐기 F9   (같은 시각의 만료·취소는 먼저 처리, I-20)
    elif mask and in_dnd(D):                                  폐기 MASK_DND
    elif mask and requests[kst_day(D)] ≥ 6:                   폐기 MASK_DAILY_CAP
    else:
        if mask: requests[kst_day(D)] += 1
        tr = simulate_plan(p, xb, fa, cfg.cost_multiplier); busy_until = tr.busy_until
        if tr.exit_reason == 'stop' and p.madi_id: stops[p.madi_id].append(tr.exit_bar_close_ns)
        기록(passed, plan_id)
```
- 비용 2배(G1 기준 4)는 같은 후보로 `cfg.replace(cost_multiplier=2.0)` 한 번 더 돌린다. 체결·청산 시점은 비용과 무관하므로 거래 집합이 같다.

### 6.9 `random_baseline.py` — 체결 엔진 담당 (I-40)
- 기준: 그 조합 **실행 가능 모드의 체결 거래**. 거래마다 (진입 달, 방향, stop_pct = |진입가 − 손절| ÷ 진입가, target_pct 같은 방식)을 유지.
- 반복마다 거래마다: 같은 달(UTC)의 S 봉 close_ns 하나를 균등 추출 → approval = +60초 → active_from = +L → 첫 실행 봉 시가에 market 진입 → stop/target = round(진입가 × (1 ∓ pct)) → `execution.simulate_plan`과 같은 청산·비용 규칙(비용 배수 = cfg.cost_multiplier).
- 거래끼리 겹침 무시(독립). 반복 평균 R의 분포에서 p95(`np.quantile`, linear). 기본 1,000회, 조합 하나가 5분을 넘으면 300회(보고서에 명시).
- 펀딩 창은 활성 시각 < f ≤ 청산(시가 체결, I-35). 보고용 `same_fee` = 같은 추출·청산에서 진입 수수료만 `entry_fee_rate(cfg.order_type)`로 바꾼 분포의 {mean, p05, p50, p95}(판정은 테이커 분포 p95 그대로, 검토 F2). 추출 시각에는 방해 금지 시간의 신호 봉 마감도 들어간다(§12.4 문자 그대로, 검토 LA-3: 보수적).
- 성능 힌트: 반복×거래를 한꺼번에 뽑고, 청산 탐색은 거래별로 짧은 창(예: 512봉)부터 늘려 가며 numpy로.

### 6.10 `metrics.py` — 통계·기준선 담당
- `summarize_run` → §8.2 RunSummary. `g1_verdict` → §8.1 verdict. DSR은 16조합을 다 돌린 뒤 `run_g1`이 부른다(분산은 실행 가능 모드, 거래 2건 이상 조합의 거래당 샤프, ddof=1).
- 판정 조건(§8.3): c1 mean_r ≥ 0.15 · c2 boot_lo > 0 · c3 pf ≥ 1.2 · c4 비용 2배 mean_r > 0 · c5 mean_r > 무작위 p95 · c6 양수 연도 ≥ 4(2020~2026, 거래 없는 해는 양수 아님) · c7 n ≥ 30. n < 30이면 `pending`, 아니면 c1~c6 모두 참일 때 `pass`.

### 6.11 `baselines.py` — 통계·기준선 담당
- 일봉 돈치안 앙상블(I-43). 비교용 보고만: CAGR, 최대 낙폭, 샤프, 거래 수, 기간별 결과.

### 6.12 `run_g1.py` — 통합 담당
- 순서: `load_market` → 기본 16조합마다 `run_combo`(all·exec·cost2·무작위) → DSR → 민감도 80개(`run_sensitivity`, 실행 가능 모드, 무작위 없음) → 돈치안 → `write_results` → `append_trials` → `report.write_report`.
- 문맥 캐시: `ctx_cache[(setting, vr_threshold)]`. 조합 단위 병렬(`--jobs`, 기본 4). 결과는 조합 순서(`g1_combos()` 순)로 모은다.
- `span_weeks` = (S 봉 마지막 close_ns − valid가 처음 True인 S 봉 close_ns) ÷ 7일.
- CSV: `trades_<key>.csv` = `records_frame(trades)` 맨 앞에 `key` 열, `signals_<key>.csv` = `records_frame(logs)` 같은 방식. 기본 16조합 × 2모드 = 각 32개(민감도는 CSV 없음).
- TRIALS.md 한 줄 형식(§8.4). 실행마다 추가, 지우지 않는다.

### 6.13 `report.py` — 통합 담당
- `g1_results.json` → `G1_REPORT.md`(한국어). 담을 내용은 스텁 docstring 목록(DEV_GUIDE §6.15 첫 장 양식 참고). 결론 한 문장 필수. 미실시 항목(PBO, 워크포워드, freqtrade 교차 검증)은 "v1.0 범위 밖"으로 적는다.

## 7. 해석 확정 (I-번호) — 명세가 애매한 곳과 택한 해석

| I | 명세 | 애매한 점 | 확정 해석 (보수적 선택) |
|---|---|---|---|
| I-1 | §1 상위 봉 | "t 이전에 마감된 4H"의 t가 봉 시작인지 판단 시각인지 | 판단 시각 기준: `close_ns + 60초 ≤ 판단 시각`인 마지막 봉. 신호 봉과 같은 순간 마감한 상위 봉은 쓴다(마감 후 60초에 판단하므로 미래 참조 아님) |
| I-2 | §3 | MA20·60·120도 "현재 봉 제외"인가 | 예. 모든 평균은 [t−n, t−1]. spread 분모는 현재 종가 |
| I-3 | §3·§6 F2 | "상위 20% 이상", "하위 20%"의 계산법 | spread[t] ≥ Q0.80(직전 500), atr[t] ≤ Q0.20(직전 100), numpy linear 분위 |
| I-4 | §3 ATR | 첫 봉 TR | TR[0] = NaN, ATR[t] = mean(TR[t−14..t−1]) → t ≥ 15 |
| I-5 | §3 기울기 | 같을 때 | 0(상승도 하락도 아님). t < N은 NaN |
| I-6 | §3 스윙 | 동률 | 엄격한 부등호(동률이면 스윙 아님). 데이터 끝 3봉은 미확정(False) |
| I-7 | §4.1 | 조건 판단 불가(워밍업·확정 스윙 없음) | 기준봉 아님 |
| I-8 | §4.2 B | "기준봉 이후 처음 확정되는 스윙 고점"에 기준봉 전 봉(t−2, t−1)이 포함되나 | 아니다. B 봉 번호 ≥ t(기준봉 포함 이후)인 첫 스윙 고점. T_B = b+3 ≤ t+60 |
| I-9 | §4.2 무효 | "T_B 전에" 범위 | close[a_idx..tb_idx] 중 하나라도 < A면 무효(T_B 봉 포함, 보수적) |
| I-10 | §4.2 거래량 | 창 정의 | mean(vol[a..b]) ≥ mean(vol[a−20..a−1]), a < 20이면 무효 |
| I-11 | §4.2 | 기준봉 여럿이 같은 B | (방향, b_idx)당 하나: 가장 이른 유효 기준봉의 마디 |
| I-12 | §4.2 살아 있음 | 경계 | tb ≤ t ≤ tb+300, (tb, t]에 close < A 없음. "가장 최근" = 최대 tb_idx(동률이면 뒤 행) |
| I-13 | §4.3 허리 | 칸 폭의 "가격", 칸 시작점, 동점 거래량의 "걸친 봉", 하락 대칭 | 칸은 A 쪽 구간 끝에서 시작, 폭 = 그 끝 가격 × 0.001, 마지막 칸은 잘림. 걸친 봉 = [low, high]가 칸과 겹치는 봉. 동점 최종 = A에 가까운 칸(상승 = 낮은 가격 칸, **하락 = §4.4 '상승의 대칭'으로 높은 가격 칸** — 문자 그대로 '낮은 가격 칸'이면 DA 숏 허용이 일부 봉에서 줄지만 검토 시점 S2·S3 후보 결과는 같음, 검토 SPEC-WAIST-TIE-DOWN → 문서화만). H = 칸 가운데 반올림 |
| I-14 | §7 반올림 | 무엇을 언제 | H·계획 가격만 `np.round(x,1)`. H를 먼저 반올림하고 그 값에서 계획 가격 계산. A·B·W 원값 |
| I-15 | §6·§12.2 | L1b의 "신호 봉" | 확인 시각에 마지막으로 마감된 S 봉 k_last (ATR 규칙과 같음) |
| I-16 | §6 F5 | "직전 5봉", 어느 ATR | [t−5, t−1] (현재 봉 제외), 각 봉 자신의 ATR과 비교 |
| I-17 | §6 F6 | 트랩의 스윙·이탈·집계 | 기준 = j−1 시점 확정 가장 최근 스윙. 이탈 = 종가가 기준을 **넘어가는 봉**(직전 종가는 안쪽). 5봉 안 첫 복귀 봉 = 완성. [t−48, t−1]에 완성된 수(지지+저항) ≥ 2 |
| I-18 | §6 F7 | 살아 있음 | I-12와 같은 정의(S 봉) |
| I-19 | §6 F8, §12.3 | S3는 마디 근거가 아님, 손절 시점 | F8은 madi_id가 있는 계획(L1a·L1b·S2)만. S3는 적용 안 함(명세 문자 그대로). 청산 봉 끝 ≤ 승인 시각인 'stop' 청산만 셈 |
| I-20 | §6 F9 | 같은 시각 | 승인 시각 < busy_until이면 F9. 같은 시각에 끝나는 취소·만료는 먼저 처리(막지 않음) |
| I-21 | §7.1·§12.1 | 건강한 조정을 T_B 봉에서도 보나 | 본다. T_B에서 위반이면 신호 폐기 SC_UNHEALTHY(봇은 이미 알고 주문하지 않음). T_B+1..T_B+24는 취소 규칙 |
| I-22 | §7.2 | L1b 준비·확인·폐기·재준비 | 준비: S 봉 k ∈ [tb+1, end_idx], H ≤ low[k] ≤ H+0.25W인 **첫** 봉(H 아래로 뚫은 봉은 준비 아님, 문자 그대로). 확인 C 봉은 준비 봉 마감 **뒤** 마감, 24 S 봉 창 안, k_last ≤ end_idx. 준비 뒤 종가 < H 두 번째 봉에서 폐기. 확인 1회로 에피소드 끝(신호 폐기돼도). **마디당 준비는 1회**: 확인 → 신호 1개, 폐기·창 끝·사망 → 그 마디의 L1b 끝(§7.2 문장, STRATEGY P13 '같은 가격은 첫 터치만'; 검토 SPEC-L1B-REARM로 검토 전 구현의 '끝난 뒤 다시 준비'에서 바꿈). 옛 해석은 `l1b_rearm=True` 진단으로만 보고 |
| I-23 | §7.2 | "T_B 이후 최저가" | C 봉 저가 최소: open ≥ close_ns[tb], close ≤ 확인 봉 마감 |
| I-24 | §7.3 | 어느 마디, "확정 후" | 봉 t에서 살아 있고 tb < t인 상승 마디 중 가장 최근(paint_alive start_offset=1). VR ≥ 2는 고정값 |
| I-25 | §7.4 | 지지선·두 번째 이탈·목표·"가장 최근 상승 마디" | 창 [t−100, t−1], 터치 = 봉 수(스윙 봉 자신 포함). 두 번째 이탈 = [t−9, t−1]에 종가 < S가 정확히 1개. 목표 = 확정 스윙 저점 중 low < S의 최댓값(기간 무관, 0.1% 안쪽 동행 저점도 문자 그대로 포함 → RR 검사에서 걸러질 수 있음). 허리 조건의 마디 = 확정된 가장 최근 상승 마디(생존 무관) |
| I-26 | §9 VR 3 | 어느 VR | §4.1 기준봉 VR만(S·D 모두). S2·S3의 VR ≥ 2, F2의 0.7은 그대로 |
| I-27 | §8.1·§12.2 | 비용 2배 때 리스크 검사 | 리스크 검사는 항상 기본 비용. cost_multiplier는 실현 손익에만 → 같은 거래 집합을 더 비싸게 계산(보수적) |
| I-28 | §8.1 포지션 크기 | 명목 0.6배 초과 시 폐기인가 | 폐기 아님. 수량을 줄인 비율 size_fraction을 기록. G1 판정은 §12.2 정의의 단위당 R(r_multiple). 계좌 기준 R(r_account)은 보조 보고 |
| I-29 | §12.2 R | d는 계획가 기준인가 실제 체결가 기준인가, 비용 2배 때 분모 | 분모 = **실제 진입가**·손절가·**기본 비용**의 d + c_stop. 지정가는 체결가 = 계획가. L1b(IOC 상한)·시장가는 실제 체결가(첫 실행 봉 시가) → 손절 = 정확히 −1R, 무작위 기준선과 같은 단위(검토 F1: 옛 '상한가 기준'은 실데이터에서 손실을 작게 기록해 평균 R을 +0.03R 안팎 부풀림). 수량(size_fraction)은 계획 시점 계획가 기준. 신호 단계 리스크 검사(§8.1)는 계획가 그대로 |
| I-30 | §12.1 | 목표·손절 부등호 | 진입 지정가 관통(<, >). 목표도 관통(롱 high > target). 손절은 닿으면(롱 low ≤ stop) |
| I-31 | §12.1 | 5분봉에서 활성·취소·만료 경계 | 봉 시작 ≥ active_from 이고 봉 끝 ≤ min(valid_until, cancel_effective_time)인 봉만 진입 인정 |
| I-32 | §12.1 | 체결 봉에서 손절 | 체결 봉 안 손절 닿음 = 그 봉 손절. 목표는 다음 봉부터. 같은 봉 손절·목표는 손절 |
| I-33 | §12.2 | 갭으로 손절을 뛰어넘을 때 | 손절가 체결이 원칙. 단 체결 봉 뒤(또는 IOC·market 체결 봉)에서 시가가 이미 손절 너머면 시가(더 불리). 지정가 체결·목표는 갭이 유리해도 지정가(유리한 체결을 주지 않음) |
| I-34 | §12.2 시간 청산 | "72봉 지나면"의 기준 | 체결 봉 시작 + 72 × 신호 봉 길이 이후 시작하는 첫 실행 봉의 시가 |
| I-35 | §12.2 펀딩 | 가격·대체값·비용 2배, 5분봉 시가 체결 | 진입 < f ≤ 청산(각 실행 봉 시작 시각). 시가 체결 주문(ioc_cap·market)의 '진입'은 min(체결 봉 시작, 활성 시각) — 5분봉 구간에서 활성 뒤 첫 5분봉 시가로 체결을 늦춰 잡는 사이의 펀딩을 빼지 않는다(검토 F3; 1분봉 구간은 같음). 가격 = f를 포함하는 실행 봉 시가. 대체 0.0001은 2026-09-01 00:00부터 데이터 끝까지. 비용 2배는 지불분만 2배 |
| I-36 | — | 데이터 끝까지 청산 안 됨 | 마지막 실행 봉 종가에 'eod'(테이커 + 슬리피지), 통계에 포함 |
| I-37 | §12.3 | 같은 시각 후보 순서 | (approval_time, −근거 마디 tb_close_ns, plan_id) 오름차순 → 가장 최근 마디 먼저 |
| I-38 | §12.3 마스크 | 방해 금지 판정 시각, 6건에 무엇을 세나 | 승인 시각(KST)으로 판정. 6건은 F8·F9·방해 금지를 통과해 실제 보낸 요청만. 7번째부터 MASK_DAILY_CAP |
| I-39 | §8.3-6 | 연도 기준·거래 없는 해 | 진입 시각의 UTC 연도. 거래 없는 해는 양수로 세지 않음 |
| I-40 | §12.4 무작위 | 달·가격·겹침·비교 공정성 | 진입 시각 UTC 달. 같은 달 S 봉 마감 균등 추출(방해 금지 시간 포함, 문자 그대로), +60초 +L 뒤 첫 실행 봉 시가 테이커 진입, 손절·목표 %는 실제 진입가 대비. 거래 간 겹침 무시. 보고용으로 진입 수수료만 조합과 같게 둔 분포(`same_fee`)도 낸다(판정 아님, 검토 F2) |
| I-41 | §12.4 DSR | 분산·첨도 | V[SR] = 16조합(실행 가능, 거래 ≥ 2) 거래당 샤프의 분산(ddof=1). 첨도는 비초과(정규 3). γ = 0.5772156649 |
| I-42 | §8.3-7 | 순열 검정 | 부호 뒤집기, 한쪽(평균 > 0), p = (1 + #≥관측) ÷ (1 + 10,000). 보고용(판정 보류일 때 참고) |
| I-43 | §12.4 돈치안 | 세부 | baselines.py docstring 규칙(현재 봉 제외 창, 다음 날 시가 체결, 테이커, 각 0.2배, 슬리피지 없음) |
| I-44 | §12.1 L1b | IOC 수명 | active_from 이후 첫 실행 봉 하나. 롱: 시가 ≤ 상한이면 시가 체결, 아니면 not_filled |
| I-45 | §7 | 가격 순서 이상 | 롱 stop < entry < target, 숏 target < entry < stop 아니면 SC_BAD_GEOMETRY |
| I-46 | §7.1 | L1a 취소 검사 범위 | k = tb+1..tb+24의 신호 봉 마감마다. 효력 close_ns[k] + 60초 |
| I-47 | §7.3·§7.4 | S2·S3 취소 | S2 close[k] > B, S3 close[k] > S, k = t+1..t+12 |
| I-48 | — | 상태와 자리 차지 | §6.8 표 |
| I-49 | §6 F3 | 파일 형식·경계 | `data/events.csv`, 열 `time_utc`(ISO, UTC) 필수·`kind` 선택. [e−2h, e+1h] 양 끝 포함. 파일이 없으면 F3 꺼짐(G1 기본), 켰는데 없으면 오류 |
| I-50 | §12.3 | 워밍업 기록 | S 봉 valid=False면 사유 WARMUP 하나만(plan 없음). D 봉 워밍업은 방향 불허 → F1 |

## 8. 결과 파일 형식

### 8.1 `backtest/results/g1_results.json`
```jsonc
{
  "schema": "g1_results/1",
  "spec_version": "v1.0",
  "created_utc": "2026-10-01T12:00:00Z",       // 결정성 비교에서 제외
  "runtime_sec": 1234.5,                        // 결정성 비교에서 제외
  "git_commit": "abc1234" | null,
  "data": {
    "span_utc": ["2020-01-01T00:00:00Z", "2026-09-29T00:00:00Z"],
    "exec_switch_utc": "2023-10-01T00:00:00Z",
    "funding_last_real_utc": "2026-08-31T16:00:00Z",
    "funding_fallback_rate": 0.0001,
    "sha256": {"BTCUSDT_1h.csv.gz": "…", …}
  },
  "params": {"latency_min": 10, "random_reps": 1000, "random_reps_reduced": false, "bootstrap_n": 10000,
             "perm_n": 10000, "seed": 20260930, "dsr_n_trials": 16, "cost_stress_mult": 2.0,
             "event_filter": "off: data/events.csv 없음"},
  "combos": [                                   // g1_combos() 순서, 16개
    {
      "key": "L1a-DA-P1",                       // base_key
      "config": {…ComboConfig.as_dict() (exec 설정)…},
      "all":  RunSummary,                       // 마스크 없음
      "exec": RunSummary,                       // 실행 가능 (G1 판정 기준)
      "exec_cost2": {"n": 0, "mean_r": null, "pf": null, "boot_lo": null},
      "random": {"reps": 1000, "n_trades": 0, "mean": null, "p05": null, "p50": null, "p95": null,
                 "n_not_filled": 0, "means": [ … ], "seed_parts": […],
                 "same_fee": {"entry_fee_rate": 0.0002, "mean": null, "p05": null, "p50": null, "p95": null}},
      "dsr": null,
      "verdict": {"c1_mean_r": false, "c2_boot_lo": false, "c3_pf": false, "c4_cost2": false,
                  "c5_random": false, "c6_years": false, "c7_enough_trades": false, "result": "pending"}
    }
  ],
  "dsr_sr_trials_var": null,
  "sensitivity": [ {"key": "L1a-DA-P1", "variant": "lat5", "config": {…}, "exec": RunSummary} ],  // 80개 + L1b 'rearm' 진단 4개
  "donchian": {"cagr": …, "max_drawdown": …, "sharpe": …, "n_trades": …, "final_equity": …,
               "start_utc": …, "end_utc": …, "per_period": {"20": {…}, "55": {…}, "100": {…}}},
  "summary": {"pass_candidates": ["…"], "pending": ["…"], "n_pass": 0,
              "decision": "통과 후보 0개 → 개발 중지, 사용자와 재검토 (§8.3)"}
}
```
- 모든 값은 `types.to_jsonable`로 변환(NaN → null, ±inf → "inf"/"-inf"). `json.dumps(ensure_ascii=False, indent=1)`.

### 8.2 RunSummary (`metrics.summarize_run`)
| 키 | 뜻 |
|---|---|
| `n_candidates` | 후보(SignalLog) 수 |
| `n_passed` | 통과 신호 수 = 실행한 계획 수 (실행 가능 모드에서는 "실행 가능 신호") |
| `discard_first_reason` | {사유: 수} 대표 사유 기준 |
| `discard_any_reason` | {사유: 수} 사유가 하나라도 포함된 후보 수 |
| `status_counts` | {filled, cancelled, expired, not_filled} |
| `exit_counts` | {stop, target, time, eod} |
| `n`, `n_long`, `n_short` | 체결 거래 수 (G1 표본) |
| `mean_r`, `median_r`, `std_r`, `win_rate` | R 요약 (win_rate = R > 0 비율) |
| `pf`, `boot_lo`, `boot_hi` | PF, 부트스트랩 평균 95% 구간 |
| `sharpe`, `skew`, `kurt` | 거래당 샤프, 왜도, 첨도(비초과) |
| `yearly`, `positive_years` | {"2020": 평균 R 또는 null, …}, 양수 연도 수 |
| `perm_p` | 부호 뒤집기 p값 |
| `mean_r_account`, `mean_size_fraction` | 계좌 기준 보조 지표 (I-28) |
| `by_session` | {"day"/"evening"/"night": {"n", "mean_r"}} 승인 시각 KST 시간대(config.kst_session) |
| `by_side` | {"long"/"short": {"n", "mean_r"}} |
| `waist_fallback_rate` | 체결 거래 중 plan.meta['waist_fallback'] 비율(마디 근거 거래만, 없으면 null) |
| `span_weeks`, `passed_per_week`, `g3_weeks_to_150` | 신호 빈도와 G3 150건까지 예상 주 수 (PLAN D1) |
| (보조) `yearly_n`, `total_r`, `sqn`, `max_consec_losses`, `max_drawdown_r` | 연도별 거래 수, R 합, SQN, 최대 연속 손실, R 곡선 최대 낙폭 |
| (보조) `marketable_limit` | 즉시 체결될 지정가 체결 요약 {n, n_engine_favorable, favorable_r_sum, mean_edge_r} (검토 LA-2·F4) |

### 8.3 CSV
- `trades_<key>.csv` (key = `ComboConfig.key`, 예 `trades_L1a-DA-P1_exec.csv`): 첫 열 `key` + `TradeResult.as_record()` 열(시각은 ISO 문자열과 `*_ns` 둘 다, `r_account`, meta는 JSON 문자열).
- `signals_<key>.csv`: 첫 열 `key` + `SignalLog.as_record()` 열(`reason` = 대표 사유, `reasons` = ';'로 이은 전체).

### 8.4 `backtest/TRIALS.md` 한 줄
`| YYYY-MM-DD | v1.0 | G1 실행 (무작위 N회, F3 꺼짐, 커밋 abc1234) | 16 | 통과 후보 k개: L1a-DB-P2, … / 보류 m개 |`

## 9. 필수 테스트 목록 (구체적 사례)

실데이터를 읽는 느린 테스트(1분봉·실행 봉 전체)는 `@pytest.mark.slow`. 합성 데이터는 `backtest/tests/conftest.py` 도우미를 쓴다.

**T-DATA (test_data.py)**
1. `load_klines('1h')`: 59,112행, 첫 `open_ns` = 2020-01-01 00:00(= 1,577,836,800 × 10⁹), `check_bars_frame(dur_ns=1h)` 통과, 인덱스 unit ns.
2. `load_exec_bars()` (slow): 1,969,632행, 2023-09-30 23:55 5분봉 다음이 2023-10-01 00:00 1분봉, contiguous.
3. `load_funding(until_ns=2026-09-29 00:00)`: 실제 7,305행 + 대체 85행(0.0001, synthetic), 대체값은 2026-09-01 00:00 이상만, 시각은 모두 00·08·16시.
4. 캐시: `tmp_path`를 cache_dir로 두 번 불러 배열이 같고, 두 번째는 CSV를 읽지 않음(monkeypatch로 확인). 원본 서명이 바뀌면 다시 만듦.
5. `resample_bars`: 합성 5분봉 → 1시간봉이 conftest `aggregate_bars`와 같음, 불완전 끝 구간 버림. 실데이터 5m→1h와 1h 파일 불일치 봉 ≤ quality_report 수(open 2·high 2·low 2·close 1).
6. `load_events`: 파일 없음 → None, 임시 CSV → 정렬된 int64 ns.

**T-IND (test_indicators.py)**
1. `trailing_mean([1,2,3,4,5], 2)` = [nan, nan, 1.5, 2.5, 3.5].
2. `true_range`·`atr`: 손 계산 예(atr[14] NaN, atr[15] = mean(tr[1..14])).
3. vr[t]는 volume[t−21] 변경에 무관, volume[t−1]에는 영향.
4. 장대봉 경계(body = 2 × body_avg → True), range 0인 봉의 꼬리 비율 0.
5. 기울기 동률 → 0, t < n → NaN.
6. `trailing_quantile`이 naive `np.quantile(x[t−n:t], q)` 루프와 1e-9 이내 일치(q=0.8/n=500, q=0.2/n=100, 앞부분 NaN 포함).
7. ma20[t]는 close[t] 변경에 무관(현재 제외), spread[t]는 변함(분모).
8. 길이 1,500 무작위 봉에서 `valid`가 처음 True인 번호 = 620, 열 이름·dtype = INDICATOR_COLUMNS 계약.
9. 앞부분 불변: `compute_indicators(bars.iloc[:k])` = `compute_indicators(bars).iloc[:k]` (k = 700, 1000).

**T-STR (test_structure.py)**
1. 스윙 엄격성: high [1,2,3,5,3,2,1] → 3번 봉 스윙, [1,2,5,5,3,2,1,0] → 스윙 없음.
2. `last_confirmed`: 스윙 i → last[i+2]는 이전 값, last[i+3] = i.
3. 기준봉 양성 1건 + 조건 하나씩 깨뜨린 음성(음봉, 장대 아님, vr < 2, slope20 ≤ 0, slope60 ≤ 0, close ≤ 최근 확정 스윙 고점, 윗꼬리 ≥ 0.5, 확산, valid False) 각 1건. vr_threshold=3이면 vr 2.5 봉 탈락.
4. 마디: A·B·tb·W 값, close < A(T_B 전) → 무효, B가 60봉 안에 확정 안 됨 → 무효, 거래량 조건 실패 → 무효, 같은 B 중복 → 가장 이른 기준봉 하나.
5. 허리 예시(§6.5): A=100, B=110, 값이 105.0 근처에 몰림 → H = 105.0.
6. 허리 동점 → 거래량 큰 칸, 그래도 동점 → 상승은 낮은 칸, 하락은 높은 칸.
7. 허리 대체: 구간 안 값 없음(구간을 건너뛰는 급등) → H = round(A + 0.5W), waist_fallback True.
8. 하락 마디 = 상승 마디의 가격 반전(p → K − p) 대칭: A·B·W 대응, H 대응(반올림·동점 규칙 안에서).
9. 살아 있음: tb+300에서 살아 있고 tb+301에서 아님, 첫 close < A 봉부터 죽음, `paint_alive`는 가장 최근 마디, start_offset=1이면 tb 봉 제외.
10. `most_recent_confirmed`는 죽은 마디도 돌려줌.

**T-FIL (test_filters.py)**
1. DA: 살아 있는 상승 마디 & 종가 > H → long_ok, 종가 == H → 아님. DB: 기울기 동률 → 불허.
2. as-of 경계: 판단 시각이 D 봉 close_ns + 60초와 같으면 그 봉 사용, 1ns 이르면 이전 봉.
3. F2는 두 조건 모두일 때만.
4. F5: surge 봉 t → t에서는 False, t+1..t+5 True, t+6 False.
5. F6: 48봉 안 트랩 2개 → True, 1개 → False, 5봉 안에 복귀 없으면 트랩 아님, t에 완성된 트랩은 t+1부터 셈, 이미 아래에 있던 종가는 이탈이 아님.
6. F7 방향별, S2에는 F7 사유가 붙지 않음.
7. F3: [e−2h, e+1h] 양 끝 포함, event_filter_on인데 events None → FileNotFoundError, 꺼져 있으면 F3 없음.
8. 손절 폭 경계: entry 100, ATR 0.3 → d 0.4 통과, 0.39 실패 / ATR 0.3이면 상한 0.9: 0.9 통과, 0.91 실패.
9. 순손익비: (+1, 100, 99, 102, limit) = 1.79895… 통과, 목표 101.5 → 1.34003… RISK_RR, ioc_cap이면 테이커 요율.

**T-SCN (test_scenarios.py)**
1. L1a 가격·시각: entry = H, stop = round(A − 0.1·ATR), target = round(H + W), valid_until = close_ns[tb] + 24h(P1), active_from = close_ns[tb] + 60s + 10min.
2. L1a SC: 종가 ≤ H, 기울기 60 음수, T_B 건강 위반 각각.
3. L1a 취소: k에서 close < A → cancel_effective_time = close_ns[k] + 60s, cancel_reason 'close_below' / high > B + 0.5W / 건강 위반 / 24봉 안 없음 → None.
4. L1b: 준비 → C 확인 → entry = round(close_c × 1.001), stop·target(lowest 기준), valid_until = active_from, 준비 봉과 같은 시각에 마감한 C 봉은 확인 불가, 종가 < H 두 번 → 신호 없음, 24봉 창 넘으면 신호 없음, 마디당 준비 1회(확인·폐기 뒤 재준비 없음), `l1b_rearm` 진단은 재준비.
5. S2: 확정 후 살아 있는 마디에서 음봉·vr≥2·종가<H → 계획, tb 봉 자신은 후보 아님, F7 없음, 취소 close > B.
6. S3: 터치 2회 지지 → vr ≥ 2 이탈 → 계획, 두 번째 종가 이탈(n_prev == 1) → 계획, 세 번째(n_prev ≥ 2, vr < 2) → 없음, 목표 = S 아래 가장 가까운 스윙 저점, 없음 → SC_NO_TARGET, 종가 ≥ 최근 상승 마디 허리 → SC_CLOSE_VS_WAIST.
7. WARMUP: valid False 봉 후보 → 사유 ('WARMUP',), plan None.
8. 정렬(I-37)·plan_id 형식·고유성.
9. 모든 계획 가격이 0.1 격자.

**T-NLA (test_no_lookahead.py)**
1. 지표·구조 앞부분 불변(절단 k에서 [0, k) 배열·tb_idx < k 마디 동일).
2. 후보 절단 불변: `market_small`, 절단 시각 T 세 곳에서 `truncate_market(m, T)`와 전체의 후보 중 approval_time ≤ T인 것이 plan_id·사유·가격·시각까지 같음. cancel_effective_time은 전체 쪽 값이 ≤ T면 같고, > T면 절단 쪽은 None.
3. 미래 변경 불변: T 이후 봉 가격·거래량을 바꿔도(연속성 유지) approval_time ≤ T 후보가 같음.
4. as-of: 무작위 판단 시각 q에 대해 close[idx] + 60s ≤ q < close[idx+1] + 60s.
5. 체결: 청산 봉 뒤 실행 봉을 바꿔도 TradeResult 동일, active_from 전에 시작한 봉에서는 체결 없음.
6. (slow) 끝까지 절단 불변: 실데이터 P1(2023-01~2024-10)·P2(2020-06~2024-10) 창에서 16조합 × 두 모드 × (실제 후보·사유를 지운 강제 계획)을 후보 → 순차 엔진(F8·F9·방해 금지·하루 6건) → 체결·청산·펀딩까지 돌리고, 절단 시각(고정 + 청산 사유별·체결 봉·신호 봉·취소 진행 중·IOC 첫 봉)마다 승인 시각 < T 결정·T까지 끝난 거래(필드 전부)·T에 걸친 거래가 같은지 본다(검토 LA-1로 추가 — '끝내 체결되지 않은 주문은 자리를 차지하지 않은 것으로 보기' 같은 순차 단계 미래 참조를 잡는다).

**T-EXE (test_execution.py)**
1. 지정가 롱: low == 지정가 → 미체결, low < 지정가 → 지정가 체결. 숏 대칭.
2. 활성: 1분봉 구간은 첫 봉 open = approval + L, 5분봉 구간은 10:01 + 10분 → 10:15 봉부터.
3. 수명 경계: 끝이 cancel_effective_time과 같은 1분봉은 인정, 넘는 봉(5분봉 포함)은 불인정.
4. 체결 봉 손절: 같은 봉 손절, 체결 봉의 목표 관통은 무시(다음 봉부터).
5. 체결 뒤 한 봉에서 손절·목표 모두 → 손절.
6. 목표 high == target → 청산 없음, 손절 low == stop → 손절.
7. 갭: 체결 뒤 봉이 손절 아래에서 시작 → 시가 청산. IOC 체결 봉 시가 ≤ 손절 → 시가 청산.
8. 시간 청산: P1 72시간, P2 288시간 뒤 시작 봉 시가, 테이커 + 슬리피지.
9. 펀딩: 07:59 봉 진입·08:00 이후 청산 → 부과, 08:00 봉 지정가 진입 → 없음, 5분봉 구간 IOC·시장가(활성 07:56 → 08:00 봉 시가) → 부과, 롱 양수 지불·숏 수취, 비용 2배는 지불만 2배.
10. R: 기본 비용 손절 → r = −1 − funding/risk(펀딩 없으면 −1.0, 1e-12, IOC가 상한보다 낮게 체결돼도 −1.0), 목표 도달 손 계산 예, 비용 2배 → 분자만 변함.
11. IOC: 시가 ≤ 상한 → 시가 체결(테이커), 시가 > 상한 → not_filled, busy_until = 그 봉 close_ns.
12. cancelled vs expired, 상태별 busy_until(§6.8 표).
13. F9: busy 중 승인 → F9, busy_until과 같은 시각 → 허용.
14. F8: 같은 마디 손절 2회 뒤 → F8, 청산 봉 끝이 승인 뒤인 손절은 안 셈, madi_id None은 F8 없음.
15. 마스크: KST 00:30 승인 → MASK_DND, 07:30 → 통과, 하루 7번째 → MASK_DAILY_CAP, DND 폐기는 6건에 안 셈, all 모드는 둘 다 무시.
16. eod 청산.
17. size_fraction: entry 100, stop 99.6, limit → risk 0.4897 → 0.5877….
18. 같은 입력 두 번 → 같은 결과.

**T-RB (test_random_baseline.py)**
1. 달·방향·거리 유지(반올림 오차 안).
2. 결정적: 같은 cfg → 같은 means, 다른 cfg.key → 다른 means.
3. 진입 = S 마감 + 60s + L 뒤 첫 실행 봉 시가, R에 테이커 진입 수수료.
4. p95 = `np.quantile(means, 0.95)`.
5. 거래 0건 → 빈 means, 분위 NaN.

**T-MET (test_metrics.py)**
1. 부트스트랩: 상수 배열 → (c, c), 같은 시드 → 같은 값.
2. PF: [1, −0.5, 2] → 6.0, 손실 없음 → inf, 빈 배열 → nan.
3. 연도: 거래 없는 해 None, 양수 연도 수.
4. DSR: 공식 직접 계산(NormalDist)과 일치, sr = SR0이면 0.5.
5. 부호 뒤집기: 양수만 10개 → p ≈ 1/1024 근처, 대칭 → 0.5 근처.
6. g1_verdict: n = 29 → pending, 각 조건 하나씩 깨면 fail, None 입력 → 그 조건 False.
7. summarize_run 키 = §8.2 목록.

**T-BAS (test_baselines.py)**
1. 계속 오르는 경로: 21번째 종가 뒤 롱, 10일 최저 이탈에서 청산.
2. t 마감 결정은 t+1 시가부터(close[t+1] 변경이 position[t]에 무영향).
3. 왕복 수수료 = 2 × 0.0005 × 명목.
4. 명목 합 ≤ 0.6 × 자산.

**T-INT (test_integration.py)**
1. `market_small`에서 `run_combo` 결과가 §8.1 combos[] 키를 모두 가짐, CSV가 tmp_path에 생김.
2. 두 번 실행 → `created_utc`·`runtime_sec` 빼고 JSON 같음.
3. jobs=1과 jobs=2 결과 같음.
4. TRIALS.md(임시 복사본)에 정확히 한 줄 추가.
5. 보고서에 결론 문장·F3 꺼짐 문구.
6. (slow) 실데이터 조합 하나 끝까지.

**T-DES (test_design_contracts.py, 설계 담당)**: config 숫자·조합 목록·키 규칙, 공용 소형 함수, 표준 프레임 검사, conftest 도우미 계약.

## 10. 성능 목표

- **전체 G1 (`python -m backtest.run_g1`) 60분 이내** (CPU 4, 메모리 15GB). 목표 30분.

| 단계 | 목표 |
|---|---|
| `load_market` (캐시 있음 / 없음) | ≤ 10초 / ≤ 90초 |
| `compute_indicators` (1h 59k봉) | ≤ 2초 |
| `build_structure` (1h) | ≤ 5초 |
| `fixed_filter_flags` (1h) | ≤ 5초 |
| `build_context` (P1 한 번) | ≤ 20초 |
| `generate_candidates` (조합 하나) | ≤ 10초 |
| `run_sequence` (조합·모드 하나) | ≤ 5초 |
| `run_random_baseline` (1,000회, 조합 하나) | ≤ 90초 (5분 넘으면 300회로 줄이고 보고) |
| 민감도 80개 | ≤ 10분 |

- 프로세스당 메모리 ≤ 3GB. 봉 단위 파이썬 반복 금지(마디·후보·계획 단위 반복은 허용). 시각 → 번호는 `np.searchsorted`, 구간 평균은 누적합.

## 11. 작업 순서와 통합 체크리스트

1. 네 팀 동시 시작. 서로 기다리지 않도록:
   - 데이터·지표: `compute_indicators`를 먼저 끝낸다(구조 팀이 씀).
   - 구조·시나리오: 단위 테스트는 필요한 지표 열만 가진 작은 `ind` 프레임을 직접 만들어 쓴다(§6.5 열 목록).
   - 체결 엔진: conftest `make_bars`/`make_exec_bars`/`make_funding`으로 손 계산 사례를 만든다.
   - 통계·기준선: 배열 입력만으로 독립.
2. 통합: `python -c 'import backtest.config, backtest.types'` → `pytest -q backtest/tests` → `python -m backtest.run_g1 --only S3-DB-P2 --reps 20 --no-sensitivity --no-trials --out <임시>` → 전체 실행 → TRIALS.md 한 줄 → 보고서.
3. 커밋·푸시는 리드가 한다.

## 12. 검토 반영 기록과 v2 후보 (2026-09-30, 수정 담당)

v1.0 명세는 고치지 않았다. 코드로 바꾼 해석(v1.0 G1 결과에 반영): I-22(L1b 마디당 준비 1회), I-29(R 분모 = 실제 진입가), I-35(시가 체결 주문의 펀딩 창 = 활성 시각부터). 보고만 더한 것: 즉시 체결될 지정가 건수(`marketable_limit`), 같은 진입 수수료 무작위 분포(`same_fee`), L1b 재준비 진단('rearm'), 결론 문장의 DSR, 보고서 한계 문구.

v2에서 정할 후보 (G1 전 변경 금지 — 명세를 v2로 올릴 때 TRIALS.md에 기록):
1. S3 목표: 전체 이력의 'S 바로 아래 스윙 저점'(I-25) 대신 지지선과 같은 최근 100봉 안의 S × (1 − 0.1%) 아래 가장 가까운 스윙 저점(검토 SPEC-S3-TARGET: 지금은 S3가 사실상 시험되지 않음).
2. S3 손절 반올림: 손절 S + ATR이 손절 폭 하한(1 ATR)과 같은 거리 → 손절을 진입가에서 먼 쪽으로 0.1 올림하거나 손절 폭 검사에 반 틱(0.05) 허용(검토 SPEC-S3-STOP-ROUNDING).
3. S3 이탈·터치: '이탈 = 직전 종가 ≥ S인 봉', '두 번째 이탈 = S 위로 회복한 뒤 다시 종가 < S', '터치 = 스윙 봉 ±3봉 밖의 별도 방문'(검토 SPEC-S3-BREAK-TOUCH).
4. 즉시 체결될 지정가: 활성 시각에 이미 체결 가능한 지정가는 첫 실행 봉 시가에 테이커 체결(검토 LA-2·F4; v1.0은 명세대로 지정가·메이커, 평균적으로 보수적).
5. 무작위 기준선: 실행 가능 모드는 승인 시각이 방해 금지 밖인 신호 봉 마감만 추출(검토 LA-3), 진입 수수료를 조합의 주문 형태와 같게(검토 F2).
6. 허리 동점(하락 마디): 대칭(A 쪽 칸) 대신 두 방향 모두 '낮은 가격 칸'으로 통일할지(검토 SPEC-WAIST-TIE-DOWN).
7. L1b 손절 폭 검사: 상한가 기준으로 통과한 뒤 실제 체결가 기준 손절 폭이 하한보다 좁은 체결을 어떻게 볼지(검토 F1 부수 관찰).
