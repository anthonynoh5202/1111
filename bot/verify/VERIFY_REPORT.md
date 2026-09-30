# 독립 검증 보고서 — PAPER 봇 (E0-L-ENS)

- 검증일: 2026-09-30 (UTC) · 검증관: 독립 검증 담당 (코드 수정 없음, `bot/verify/`만 씀)
- 대상: 작업 트리(커밋 안 됨) — `bot/`, `backtest/random_fair.py`, 배포 파일, `docs/RUNBOOK.md`
- **2차 판정: 1차의 V-1·V-2는 해결됨. 새로 치명 1건(V-4): 실제 gitleaks v8.21.2로 돌려 보니 CI gitleaks 작업이 첫 실행에서 실패한다**
  (기존 커밋 이력의 실험 이름 116건 + 새 테스트 값 1건이 기본 규칙 `generic-api-key`에 걸림. 모두 가짜 양성). 고치는 법은 §0-3에서 검증함.

| 항목 | 1차 | 2차 |
|---|---|---|
| (1) 전체 테스트 | 930 통과 | **942 통과 / 실패 0** (`.venv/bin/python -m pytest -q`, 324초; 새 회귀 시험 12개 포함) |
| (2) 재생 == 백테스트 | 100건 일치, 최대 오차 0 | **다시 실행: 100/100 일치, 최대 오차 0**(3자 대조 통과). 1차 CSV와 다른 것은 난수 `signal_id` 열뿐 |
| (3) 보안 시나리오 | 55개 중 54개 | **55개 중 55개**(6초) |
| (3) V-1 REPLACE 덮어쓰기 | ❌ | ✅ 7가지 변형(OR REPLACE, REPLACE INTO, UPSERT, OR IGNORE, UPDATE OR REPLACE, config_snapshots 2종) × recursive_triggers OFF/ON 모두 차단 |
| (3) V-2 사용자 규칙 3개 | 2건 걸림 | ✅ 0건(실제 gitleaks 바이너리로 확인) |
| (3) gitleaks 기본 규칙 | 실행 못 함 | ❌ **V-4: 117건(가짜 양성) → CI 실패** |
| (4) backup.sh | 통과 | ✅ 수정본 다시 리허설(공개키 없음/정상/age 실패 3경우, 평문 남지 않음) |
| (5) fair_baseline | 결론 같음 | ✅ 다시 실행, 결론 같음. TRIALS.md에 "p95 ≈ 1.85로 인용" 주석 추가 확인 |

## 0. 2차 검증 (수정 2차 반영 뒤)

### 0-1. V-1 감사 로그 REPLACE 덮어쓰기 — 해결
- `bot/db.py`: `audit_log_no_replace`, `config_snapshots_no_replace`(BEFORE INSERT, 같은 번호가 있으면 ABORT) 추가, `PROTECT_TRIGGERS` 6개,
  `connect()`에 `PRAGMA recursive_triggers = ON`. `init_schema`는 `check_integrity`를 스키마 재적용 **전에** 부르므로, 트리거가 빠진
  옛 DB는 조용히 복구되지 않고 시작 거부된다(`test_missing_replace_trigger_refuses_start`).
- 독립 시험(검증관 스크립트, 봇 연결이 아닌 **맨 sqlite3 연결**로): 아래 7가지를 recursive_triggers OFF·ON 각각에서 시도 → **14/14 차단**, 행 불변.
  `INSERT OR REPLACE`, `REPLACE INTO`, `INSERT … ON CONFLICT(seq) DO UPDATE`, `INSERT OR IGNORE`(중복 번호), `UPDATE OR REPLACE`,
  config_snapshots의 OR REPLACE·UPSERT.
- 큰 번호(seq=100)로 끼워 넣기는 삽입은 되지만 재시작 때 "행 수(4) ≠ 마지막 번호(100)"로 **시작 거부**된다(탐지됨).
- 봇 코드의 UPSERT 2곳(`runtime_flags`, `cycles`)은 보호 테이블이 아니고, recursive_triggers ON에도 전체 테스트가 통과한다.
- `security_scenarios.py`: 필수 55개 중 55개 통과.

### 0-2. V-2 테스트 값 — 해결
- 두 값은 허용 목록의 가짜 값으로 바뀌었다(허용은 값 단위, 경로 단위 아님). `security_scenarios.py`의 토큰·키 모양 값도 허용 목록 값으로 바뀜.
- **실제 gitleaks v8.21.2**(공식 릴리스, sha256 `5bc41815…16e3ba`를 체크섬 파일과 대조, 검증관 임시 폴더에서만 실행)로 확인:
  사용자 규칙 3개(telegram·anthropic·healthchecks) 걸린 것 **0건**.
- 허용 목록이 진짜 비밀을 가리지 않는지: 임시 폴더에 난수로 만든 토큰·sk-ant 키·ping URL을 두고 돌리면 3개 모두 잡힌다.

### 0-3. V-4 (치명 — CI 실패) gitleaks 기본 규칙 `generic-api-key`가 가짜 양성 117건을 낸다
CI는 `gitleaks detect --config=.gitleaks.toml --exit-code 1`로 **전체 이력**을 검사하고, 설정은 `useDefault = true`다.
1차·수정 2차는 사용자 규칙 3개만 흉내 냈고 기본 규칙은 돌리지 못했다. 이번에 실제 바이너리로 돌렸다.

| 어디서 | 건수 | 걸린 값(비밀 아님) |
|---|---|---|
| 현재 git 이력 31커밋(이미 커밋된 파일) | **116** | 실험 이름. `"key": "E0-L-ENS_cost2"`, `"key": "L1a-DA-P2_exec"` 등 — `backtest/results/g1_results.json` 88, `backtest/results_trend/g1t_results.json` 24, `backtest/tests/test_trend.py` 2, `test_design_contracts.py` 1, `test_metrics.py` 1 |
| 작업 트리를 임시 복제본에 커밋해 본 것(32커밋째) | **+1** | `bot/tests/review_ops_test.py:424` `"GPG_KEY": "A035C8C1…"` (python 이미지의 공개 GPG 지문, 비밀 아님) |

- 이미 커밋된 이력은 파일을 고쳐도 사라지지 않으므로 **허용 목록으로만** 풀 수 있다.
- 결과: 지금 커밋·푸시하면 CI `gitleaks` 작업이 **첫 실행부터 실패**한다(`--exit-code 1`).
- 고치는 법(검증함): `.gitleaks.toml`의 `[allowlist] regexes`에 두 줄 추가. 허용 목록 regex는 기본적으로 '걸린 값'에 대해 검사되므로
  고정(anchored)된 실험 이름 모양만 풀린다.
  ```toml
    '''^(?:E[01]|L1[ab]|S[23])-[A-Za-z0-9-]+_[a-z0-9_]+$''',   # 백테스트 실험 이름(E0-L-ENS_cost2, L1a-DA-P2_exec …)
    '''A035C8C19219BA821ECEA86B64E628F8D684696D''',                 # python:3.11 이미지의 공개 GPG 지문(테스트 값)
  ```
  (두 번째 줄 대신 테스트 값을 `"0" * 40`처럼 엔트로피가 낮은 값으로 바꿔도 된다 — 테스트의 목적은 이름 검사라 값은 상관없다.)
  이 설정으로 임시 복제본(이력 32커밋)을 다시 돌리면 **no leaks found, 종료 코드 0**. 위의 난수 비밀 3종은 여전히 모두 잡힌다.
- 재발 방지 제안: `test_custom_gitleaks_rules_have_no_unallowed_hits`는 사용자 규칙만 흉내 낸다. 기본 규칙까지 보려면 gitleaks 바이너리가
  필요하므로, 커밋 전 로컬에서 `gitleaks detect --config=.gitleaks.toml` 한 번을 RUNBOOK/README 개발 절차에 넣는 것이 좋다.

### 0-4. 나머지 1차 지적(V-3) — 모두 반영 확인
- `.dockerignore`에 `bot/verify/` 있음. `.gitignore`에 `config/*.local.toml` 있음.
- `scripts/backup.sh`: 공개키·age 확인이 평문 생성 **앞**으로 옮겨짐, EXIT trap으로 실패 시 평문 삭제, 파일 이름에 초 포함.
  가짜 `docker` + 실제 age로 다시 리허설: ① 공개키 없음 → 종료 1, 평문 생성 안 함 ② 정상 → `.age` 0600, 복호화 내용 일치, 평문 없음
  ③ 공개키 파일이 깨짐(age 실패) → 종료 1, 평문 없음. `bash -n` 통과.
- TRIALS.md 참고 줄에 "E0-L-ENS p95는 시드 30개 1.85±0.04, 10만 회 1.85로 인용" 주석이 붙음(결과 JSON은 생성물이라 그대로 — 적절).
- CI의 배포 파일 규칙(ports 없음, 비밀 이름=값 없음)을 로컬에서 같은 grep으로 돌림 → 통과.

### 0-5. 여전히 확인하지 못한 것
docker build/up, compose healthcheck 실제 동작, rclone, 실제 텔레그램·바이낸스·Claude 호출(데몬·네트워크·키 없음).
배포 전에 서버에서: 빌드 → `check` → `run --dry-run` → `up -d` → (healthy) → 백업·복원 리허설. 알려진 한계 L1+(트리거를 지웠다 되살리며
행 수정)는 그대로이며 해시 체인은 TESTNET 전 과제.

---

아래 §1~§7은 **1차 검증** 기록이다(당시 상태 그대로, V-1·V-2·V-3은 §0에서 해결 확인).

---

## 1. 테스트 (1차)

```
.venv/bin/python -m pytest -q                      → 930 passed in 337.56s
.venv/bin/python -m pytest bot/tests -q            → 433 passed in 59.32s (검증 스크립트 추가 뒤)
```
`review_*_test.py`(112개)도 `*_test.py` 기본 규칙으로 수집된다. 느린 대조 시험(`-m slow`)도 포함.

## 2. 재생(replay) 대조 — `bot/verify/parity_check.py`

### 실행
```bash
# 설정: config/replay.example.toml에서 db_path(임시), data_dir = "data/binance"만 바꿈
env -i PATH=/usr/bin:/bin .venv/bin/python -m bot.main --config <replay.toml> replay --trades-csv pos.csv
#   → 재생 완료: 사이클 2463(실패 0) · 신호 100 · 승인 100 · 모의 포지션 100(청산 97, 보유 3) · 메시지 2760 (36초)
.venv/bin/python bot/verify/parity_check.py --replay-csv pos.csv      # 종료 코드 0 = 통과
```
- 참고: 이 컨테이너 셸에는 `GH_TOKEN` 같은 환경 변수가 있어 봇이 **시작을 거부**했다(설계대로). `env -i`로 비운 뒤 실행.
- 재생 결과 거래 목록: `bot/verify/replay_positions_2020_2026.csv` (100행)

### 독립 스크립트가 하는 일
`parity_check.py`는 `bot`·`backtest`를 **import하지 않는다**(pandas·numpy만). 세 가지를 비교한다.
1. 재생 CSV ↔ 백테스트 `backtest/results_trend/trades/E0-L-ENS.csv`
2. 백테스트 CSV ↔ **원자료 재계산**: `data/binance` 원본 파일에서 TREND_SPEC v1.0 문장만 보고 다시 짠 시뮬레이터
3. 재생 CSV ↔ 원자료 재계산

비교 규칙: 거래 수·N·신호 일봉·진입 시각·청산 시각·청산 사유는 정확히 같아야 함. 가격·손절·R 분모·수수료·슬리피지는
절대 오차 1e-9. 펀딩·손익·R은 상대 오차 1e-9.
데이터 끝의 백테스트 `eod` 3건은 재생에서 OPEN이어야 하고, 진입 항목만 비교한다.

### 결과
| 비교 | 개수 | 청산 비교 | 보유 | 최대 오차 |
|---|---|---|---|---|
| 재생 vs 백테스트 | 100 / 100 | 97 | 3 | **모든 항목 0.0** |
| 백테스트 vs 원자료 재계산 | 100 / 100 | 97 | 3 | 가격 0, 비용 ≤ 1.4e-14, 펀딩·R 상대 ≤ 1e-9 |
| 재생 vs 원자료 재계산 | 100 / 100 | 97 | 3 | 위와 같음 |

- 재생: 거래 100건(N20 56, N55 25, N100 19), 손절 42, 추세 청산 55, 보유 3. 청산 97건 평균 R +1.308.
- 재생 자체 점검 통과: 모두 롱, 판단 = 마감 + 60초, 승인 = 판단 + 30분, 승인 전 진입 없음, 하위 시스템별 포지션 겹침 없음.
- 백테스트 meta의 `atr20`·`level`이 원자료 재계산과 같음(ATR 오차 4.6e-13, level 0).

**원자료 재계산을 맞추는 동안 명세 해석 3곳을 확인했다.** 모두 `backtest/DESIGN.md`·RULES_SPEC에 적혀 있고 코드와 일치한다.
1. ATR20 = 직전 20개 TR 평균이고 **현재 봉은 뺀다**(RULES_SPEC §3 "직전"). 처음에 현재 봉을 넣고 짰더니 손절가가 어긋났다.
2. 손절가는 0.1 USDT로 반올림한다(RULES_SPEC §6 공통).
3. 펀딩 시각은 **정시로 내린다**. 원본 `calc_time`은 정시 + 0~47ms다(I-35). 내리지 않으면 2023-02-16 N20·N100 거래
   (2023-02-24 16:00 봉에서 손절)의 16:00 펀딩 1회가 빠진다. 경계 규칙이라 결과는 보수적(펀딩을 더 냄)이다.

### 추가: 진짜 1분봉만으로 재생 (`--exec-bars 1m`, 2023-10-02부터)
paper 모드가 실제로 쓰는 1분봉 경로(빈 구간 허용 포함)를 시험했다. 44건 모두 거래 수·진입·청산 시각·가격·사유·수수료가
백테스트와 **같다**. 다른 것은 2026-09-01 이후 펀딩뿐이다(3건). 일반 `Replay`는 §12.2 대체값(0.01%)을 넣지 않기 때문이며,
설계대로다(paper는 실제 펀딩을 씀).

## 3. 보안 점검

### 3-1. 시나리오 직접 실행 — `bot/verify/security_scenarios.py`
실제 PTB `Application` 핸들러(`telegram_ui.build_application`)에 `telegram.Update.de_json`으로 만든 업데이트를 넣었다.
엔진은 실제 `Engine`, DB는 파일 SQLite(WAL), 전송 계층은 가짜(기록만)다. 네트워크는 쓰지 않았다.

| # | 시나리오 | 결과 |
|---|---|---|
| S1 | 허용되지 않은 사용자가 진짜 신호 ID로 [승인]·[패스]·[상세] | 상태 불변, 상대에게 응답·수정 0, 감사 1행, 운영 채팅 경고 1번, approvals 기록 없음 ✅ |
| S2 | 그룹·슈퍼그룹·채널, 다른 채팅 ID, 문자열·bool·None ID, ID 미설정(0) | 모두 거부(무응답) ✅ |
| S3 | 위조 data 10종(모르는 ID, v2, 없는 동작, 소문자, 64바이트 초과, SQL 모양, 가격 끼워 넣기, 빈 값, 줄바꿈, data 없음) + [승인] 없이 [확인] | 상태 불변, 2단계 우회 불가 ✅ |
| S4 | 같은 callback_query_id 재전송(순차), 같은 id 5개 동시 | 첫 번째만 처리, duplicate 감사, APPROVED 전이 1번 ✅ |
| S5 | 다른 메시지에 붙은 버튼 | 거부 ✅ |
| S6 | [확인]×10 + [패스]×5 동시, engine.confirm 스레드 12개 동시 | 최종 전이 정확히 1번, True 정확히 1개 ✅ |
| S7 | DB 수준 경쟁: 연결 2개 × 스레드 16개가 같은 전이(50회 반복) | 매번 정확히 1개 성공, 오류 0 ✅ |
| S8 | 2시간 뒤 [승인], [승인] 61초 뒤 [확인], 일시정지 중 [승인] | 모두 승인 안 됨 ✅ |
| S9 | 권한 없는 /pause /resume /status, 허용 사용자의 `/set …` `/config` `/resume now` `/pause@evil_bot x`, 비밀 모양 메시지 | 응답 없음·플래그 불변, 설정 변경 불가, 원문은 감사 로그에 남지 않음 ✅ |
| S10 | 권한 없는 클릭 1,000번(50명) | 감사 20행 + 다음 창에 요약 1행, 상대 응답 0, 경고 1번 ✅ |
| S11 | audit_log·config_snapshots의 UPDATE/DELETE, 트리거 삭제 + 행 삭제 뒤 재시작, 트리거 복구 뒤 재시작, DB 0644 | 모두 차단·시작 거부 ✅ · **`INSERT OR REPLACE`로 덮어쓰기 ❌ (V-1)** |
| S12 | (알려진 한계) 트리거를 지웠다가 되살리며 행 수정 | 탐지 안 됨. 문서의 L1+ 한계와 같다(해시 체인은 TESTNET 전 과제) — 기록용 |

### 3-2. 비밀 패턴 검색
- 작업 트리 전체(`.venv`·`data` 제외)와 git 이력 31커밋(`git log --all -p`)을 검색했다. 패턴: sk-ant-, 텔레그램 토큰, AKIA, 개인키,
  ghp_, xox, hc-ping, AGE-SECRET-KEY. **진짜 비밀 없음.** 걸린 것은 모두 테스트용 가짜 값이다.
- `.gitleaks.toml`의 사용자 규칙 3개 + 허용 목록을 파이썬으로 흉내 내 커밋 대상 파일 전체에 돌렸다. **2건이 걸린다**(V-2).
  gitleaks 기본 규칙 전체는 실행하지 못했다(바이너리 없음, docker 데몬 없음).
- `.env.example`은 이름만 있음, compose `environment`는 `TZ`만, `ports:` 없음(`docker compose config`로 확인).

### 3-3. 시작 시 거부(RUNBOOK §8을 직접 재현, 모든 경우 출력에 토큰·키 값이 없는지 확인)
| 입력 | 종료 코드 | 값 노출 |
|---|---|---|
| 환경 변수 `TELEGRAM_BOT_TOKEN`, `MY_PING_URL` | 2 | 없음 |
| 비밀 파일 0644 | 2 | 없음 |
| 텔레그램 토큰 파일에 sk-ant 키(check, run --dry-run) | 2 | 없음 |
| allowed_user_id = 0 / 그룹 채팅 ID(음수) | 2 | 없음 |
| approval_window_s = 99999 / 모르는 키 / base_url = evil | 2 | 없음 |
| paper 경로에 replay DB | 3 | 없음 |
| DB 파일 0644(복원 실수) | 3 | 없음 |

### 3-4. 공급망
- `requirements.txt` 23개 패키지, `requirements-dev.txt` 모두 버전 고정 + 해시(408줄). python:3.11-slim 기준(manylinux x86_64, cp311)으로
  `pip install --dry-run --require-hashes --only-binary=:all:` 해석에 **성공**했다.
  (주의: `--platform`을 하나만 주면 jiter가 없다고 나온다. 여러 manylinux 태그를 줘야 한다. 실제 docker 빌드는 자동으로 맞는다.)
- CI 액션은 커밋 SHA로 고정, gitleaks 이미지는 digest로 고정.

## 4. RUNBOOK 따라 하기 (docker 없이)
임시 폴더를 '서버의 봇 폴더'로 삼아 문서 순서대로 했다. 경로만 `/run/secrets`·`/data`에서 임시 폴더로 바꿨다.

| 절 | 한 일 | 결과 |
|---|---|---|
| 1-4 | backups 폴더 700 | ✅ |
| 2-2 | secrets 700, 토큰·키 파일 400(가짜 값) | ✅ |
| 2-3 | bot.example.toml 복사, 숫자 ID 두 개만 채움 | ✅ |
| 2-4 | `check` → "점검 통과", `run --dry-run` → "dry-run 통과 · 네트워크 호출 없음" | ✅ DB 파일 0600, 폴더 0700 |
| §8 | 오류 11종 | ✅ 위 3-3 |
| §6 자동 백업 | `scripts/backup.sh` 실행. `docker`는 가짜 스크립트로 바꿔 로컬 `backup` 명령을 부르게 함. age는 실제 사용(age-keygen, 공개키만 config) | ✅ `.age`(0600) 생성, 평문 삭제, 40일 된 백업 정리. 공개키가 없으면 평문을 지우고 종료 1 |
| §6 수동 백업 | 같은 이름 두 번 | ✅ 두 번째 거부, 권한 0600 |
| §6 복원 | age -d로 복호화 → WAL/SHM 삭제 → chmod 600 → cp -p → check | ✅ 점검 통과, integrity_check ok. 0644로 두면 코드 3으로 거부 |
| compose | `docker compose config -q` (데몬 없이 파일 검증), `--profile replay` 서비스 목록 | ✅ |

**하지 못한 것**: `docker compose build/up`(데몬 없음), compose healthcheck 실제 동작, rclone(없음), 실제 텔레그램·바이낸스·Claude
연결(네트워크·키 없음). 배포 전에 서버에서 한 번 해 볼 것: 빌드 → `check` → `run --dry-run` → `up -d` → `(healthy)` 확인 → 백업·복원 리허설.

## 5. 공정 무작위 기준선(TREND v1.1 참고) — `bot/verify/fair_baseline_check.py`
- `fair_baseline.json`: 8개 조합 모두 실제 평균 R이 공정 무작위 p95를 넘지 못함(0/8). E0-L-ENS: 실제 +1.306, 참조 p95 +1.981, p = 0.216.
- **독립 재현**: `backtest`를 쓰지 않고 원자료 시뮬레이터로 '모든 유효 일봉에 진입했다면' 표를 만들었다.
  표 크기는 **N20 2441 · N55 2407 · N100 2362로 정확히 같다.** 날짜별 R 차이는 최대 0.003(펀딩 경계 반올림 수준)이다.
  같은 거래 수(56/25/19)로 복원 추출 10만 회 → 평균 0.910, **p95 1.855**, 실제 이상 비율 0.210. 결론이 같다.
- **p95 값 차이의 원인**: 참조 JSON은 1,000회 한 번(고정 시드)이다. 참조 함수 `random_fair.fair_random_baseline`을 다른 시드 30개로
  돌리면 p95 = 1.852 ± 0.044(최소 1.769, 최대 1.947)이고, 10만 회는 1.851이다. JSON의 1.981은 +2.9 sd 쪽에 있는 값이다.
  버그는 아니다(결정적 시드). 다만 **p95 자체를 인용할 때는 ≈ 1.85로 읽어야 한다.** 결론(넘지 못함)은 어느 쪽이든 같다.
- **의미(사용자에게 중요)**: E0-L-ENS의 R은 '돌파 날짜를 고르는 능력'보다 **청산 규칙(추세 청산 + 2×ATR 손절)**에서 온다.
  아무 날에나 같은 규칙으로 들어가도 5번 중 1번은 실제보다 좋다. 이 봇의 PAPER 운영은 전략을 검증하는 단계로 보는 것이 맞다.
- TRIALS.md: 새 줄 1개, 날짜 2026-09-30(실제 실행일) 확인. 이전 TREND v1.0 줄의 2026-10-01 날짜는 이번 범위 밖이라 그대로.

## 6. 발견 사항 (고칠 것)

### V-1 (중간, **2차: 해결**) 감사 로그를 `INSERT OR REPLACE`로 덮어쓸 수 있고, 시작 검사도 못 잡는다
- 재현: `INSERT OR REPLACE INTO audit_log(seq, ts_ms, actor, event_type, payload_json) VALUES (<있는 seq>, …)` → 원래 행이 바뀐다.
  `REPLACE INTO config_snapshots …`도 같다. 행 수와 `sqlite_sequence`가 그대로라 재시작 때 `check_integrity`도 통과한다.
- 원인: SQLite의 REPLACE 충돌 처리는 `PRAGMA recursive_triggers`가 꺼져 있으면 **DELETE 트리거를 부르지 않고** 행을 지운다.
  `bot/db.py`의 보호는 BEFORE UPDATE/DELETE 트리거뿐이다.
- 위험: 봇 코드는 REPLACE를 쓰지 않는다(grep 확인). 그래서 위험은 SQL을 실행할 수 있는 주체(코드 버그, 향후 기능, DB 파일 접근자)에 한정된다.
  하지만 '트리거 삭제'와 달리 **흔적 없이** 바뀐다. 문서의 "수정·삭제 불가" 약속(RUNBOOK §5, DESIGN)과 어긋난다.
- 고치는 법(검증함): 두 테이블에 아래 트리거를 추가하고 `PROTECT_TRIGGERS`에 넣는다. pragma가 꺼진 외부 연결에서도 막힌다.
  추가로 `connect()`에 `PRAGMA recursive_triggers = ON`도 넣으면 이중 방어가 된다.
  ```sql
  CREATE TRIGGER IF NOT EXISTS audit_log_no_replace BEFORE INSERT ON audit_log
  WHEN NEW.seq IS NOT NULL AND EXISTS (SELECT 1 FROM audit_log WHERE seq = NEW.seq)
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
  -- config_snapshots도 같은 식(snapshot_id)
  ```
  주의: `PROTECT_TRIGGERS`에 새 트리거를 넣으면, 이미 있는 DB는 `check_integrity`가 트리거 없음으로 거부한다. 배포된 DB가 아직 없으니
  지금 넣는 것이 가장 쉽다. 아니면 스키마 버전을 올려 이관한다.

### V-2 (낮음, **2차: 해결**) 테스트 값 2개가 프로젝트 gitleaks 규칙 `healthchecks-ping-url`에 걸린다
- `bot/tests/review_security_test.py:360` (22자 ping key 모양의 URL — 수정 2차에서 허용목록의 가짜 값 `TEST-dummy-pingkey-not-real`로 교체)
- `bot/tests/review_ops_test.py:194` (0으로 채운 UUID URL — 수정 2차에서 허용목록의 가짜 UUID로 교체)
- `.gitleaks.toml` 허용 목록에 없다. 커밋하면 CI의 gitleaks 작업(`--exit-code 1`, 전체 이력)이 실패한다.
- 첫 번째 값은 진짜 ping key처럼 생겼다(22자). 가짜라도 누가 봐도 가짜인 값(예: `TESTpingKEYnotREAL000000`)으로 바꾸고 그 값을
  허용 목록에 넣을 것. 허용 목록은 값 단위로 넣고, 경로 단위로 넣지 않는다.

### V-3 (낮음, **2차: 모두 반영**) 운영 편의·정리
- `bot/verify/`가 도커 이미지에 들어간다. `.dockerignore`가 `bot/tests/`만 뺀다. 실행되지는 않지만(`security_scenarios.py`는
  이미지에 없는 `bot.tests`를 import) 이미지에 필요 없는 파일이다. `.dockerignore`에 `bot/verify/`를 추가할 것.
- `config/replay.local.toml`(README·RUNBOOK §7이 만들라고 함)이 `.gitignore`에 없다. 비밀은 없지만 개인 경로가 커밋될 수 있다.
- `scripts/backup.sh`는 백업을 먼저 만든 뒤 age 공개키를 확인한다. 평문은 지우므로 안전하지만 확인을 앞으로 옮기는 편이 낫다.
  같은 분(minute) 안에 두 번 돌리면 이름이 겹쳐 실패한다(cron 하루 1회면 문제 없음).
- `fair_baseline.json`의 p95는 1,000회 한 번이라 ±0.045 흔들린다(§5). 참고 지표이므로 그대로 둬도 되지만, 인용할 때는 10만 회 값을 함께 적는 것이 정확하다.

## 7. 검증 도구 (다시 돌리는 법)
```bash
# 재생 CSV 만들기(환경 변수에 비밀 이름이 있으면 env -i로)
env -i PATH=/usr/bin:/bin .venv/bin/python -m bot.main --config config/replay.local.toml replay --trades-csv /tmp/pos.csv
.venv/bin/python bot/verify/parity_check.py --replay-csv /tmp/pos.csv          # 3자 대조(약 7초), 0 = 통과
.venv/bin/python bot/verify/security_scenarios.py                              # 보안 시나리오(약 6초), 2차: 55/55 통과
.venv/bin/python bot/verify/fair_baseline_check.py                             # 공정 기준선 독립 재현(약 10초)
# 2차 추가: 실제 gitleaks(공식 릴리스 바이너리, 체크섬 확인)로 CI와 같은 검사
gitleaks detect --source=. --config=.gitleaks.toml --redact --exit-code 1   # 지금은 V-4 때문에 실패(116건)
```
