# backtest — G1 백테스트 엔진

BTC/USDT 무기한 선물 반자동 시그널봇의 매매 규칙(차트프로식 4가지)이 **무작위 진입보다 나은지** 판정하는 G1 백테스트다.
규칙과 숫자의 단일 기준은 [`docs/RULES_SPEC.md`](../docs/RULES_SPEC.md) **v1.0(고정)**이고, 구현 설계는 [`DESIGN.md`](./DESIGN.md)다.

## 빠른 시작

저장소 루트(`/home/user/1111` 같은 곳)에서 실행한다. `backtest/` 안에서 파일을 직접 실행하지 않는다
(`types.py`가 파이썬 표준 모듈 이름과 같아서 꼬인다).

```bash
python -m pytest backtest/tests -q         # 테스트 전체 (약 4~5분, -m "not slow"면 1분 안팎)
python -m backtest.run_g1                   # G1 전체 실행 → backtest/results/ (1분 이내)
python -m backtest.report                   # 결과 JSON으로 보고서만 다시 만들기
```

처음 실행하면 `data/binance/*.csv.gz`를 읽어 `data/cache/`에 캐시(약 125MB, git 제외)를 만든다. 다음부터는 빠르다.

## `run_g1` 옵션

| 옵션 | 뜻 | 기본 |
|---|---|---|
| `--only L1b-DA-P1` | 조합 이름의 부분 문자열로 거르기. 쉼표로 여러 개(`L1b,S2`, `P2`) | 16조합 전부 |
| `--start 2024-01-01 --end 2025-01-01` | 평가 기간(UTC). **승인 시각**(신호 봉 마감 + 60초)이 [시작, 끝)인 신호만 쓴다. 끝은 미포함 | 전체 |
| `--reps 1000` | 무작위 기준선 반복 수(§12.4). 줄이면 보고서에 "줄임"이라고 적힌다 | 1000 |
| `--jobs 4` | 병렬 프로세스 수(1이면 순차). 결과는 프로세스 수와 무관하게 같다 | 4 |
| `--no-sensitivity` | 민감도(조합마다 지연 5·15분, 허리 (고+저)÷2, 기준봉 VR 3, 비용 2배 + L1b 조합에만 명세 밖 진단 'L1b 재준비') 건너뛰기 | 실행 |
| `--no-random` | 무작위 기준선 건너뛰기(G1 조건 ⑤는 미달로 처리) | 실행 |
| `--no-trials` | `backtest/TRIALS.md`에 시도 기록을 남기지 않기 | 기록 |
| `--no-report` | 보고서를 만들지 않기 | 만듦 |
| `--signal-logs` | 후보별 전체 신호 기록을 `signals/<조합>_<all\|exec>.csv.gz`로 저장(용량 큼) | 안 함 |
| `--out DIR` | 결과 폴더 | `backtest/results` |
| `--note "메모"` | TRIALS.md 한 줄과 결과 JSON에 남길 메모 | 없음 |

예) 2024년 한 해, L1b 네 조합만, 무작위 50회, 기록 없이:
`python -m backtest.run_g1 --start 2024-01-01 --end 2025-01-01 --only L1b --reps 50 --no-trials --out /tmp/g1_2024`

**공식 G1 판정**은 전체 기간 · 16조합 · 무작위 기준선(300회 이상)을 모두 넣은 실행만이다. 그 밖의 실행은 결과와 보고서에
"부분 실행(공식 판정 아님)"이라고 적힌다. **TRIALS.md**에는 기본으로 실행마다 한 줄이 붙는다(§9, 지우지 않는다).

## 결과 파일 (`backtest/results/`)

| 파일 | 내용 |
|---|---|
| `g1_results.json` | 모든 결과(DESIGN §8.1 스키마). 조합마다 전체·실행 가능 요약, 비용 2배, 무작위 기준선 분포(판정용 테이커 진입 + 참고용 같은 진입 수수료 `same_fee`), DSR, 판정. 민감도, 돈치안, 데이터 해시, 코드 커밋·해시 |
| `G1_REPORT.md` | 한국어 보고서. 맨 앞은 코딩을 몰라도 읽을 수 있는 요약, 이어서 판정표·폐기 사유·기준선·민감도·한계·재현 방법 |
| `trades/<조합>_<all\|exec>.csv` | 조합·모드별 실행한 계획 전부(체결·취소·만료·미체결). 진입·청산 시각과 가격, 비용, R |
| `signals_summary.csv` | 신호 폐기 사유별 개수(조합 × 모드 × 사유, 대표 사유 기준과 포함 기준) |
| `run_log.txt` | 실행 시간 기록(단계별·조합별). 실행마다 달라지므로 JSON과 따로 둔다 |

`g1_results.json`은 `created_utc`·`runtime_sec`만 빼면 다시 돌려도 똑같다(난수는 조합 이름으로 시드를 고정).

## 한 조합이 도는 순서

```
data.load_market ─ 캔들(15m·1h·4h·1d), 실행 봉(2023-10 전 5분 / 이후 1분), 펀딩(2026-09 이후 0.01% 가정)
  → scenarios.build_context      지표(indicators)·구조(structure: 스윙·기준봉·마디·허리)·고정 필터(filters)
  → scenarios.generate_candidates  시나리오 후보 + 폐기 사유(워밍업·F1~F7·손절 폭·손익비) + 주문 계획
  → execution.run_sequence       시간순 처리: F8·F9·방해 금지·하루 6건 → 체결·청산·비용·펀딩 → R
       ('all' 마스크 없음 / 'exec' 실행 가능 / 비용 2배를 각각)
  → metrics.summarize_run        평균 R, 부트스트랩 하한, PF, 연도별, 순열 검정 …
  → random_baseline              같은 달·방향·손절/목표 거리로 진입 시각만 무작위(1,000회)
  → metrics.g1_verdict           §8.3 조건 7개 → 통과 후보 / 불합격 / 보류
모든 조합 뒤: DSR(16조합 샤프 분산), 돈치안 기준선(baselines), 결과 파일·보고서(report)
```

## 폴더 구성

| 파일 | 역할 |
|---|---|
| `config.py` | 명세의 모든 숫자, 조합 설정(`ComboConfig`), 공용 소형 함수(반올림·비용·시간·as-of) |
| `types.py` | 표준 프레임과 자료형(`Plan`, `TradeResult`, `SignalLog`, `Candidate` …) |
| `data.py` | 데이터 읽기·검사·캐시, 실행 봉 병합, 펀딩 대체값, 데이터 해시 |
| `indicators.py` | ATR·VR·장대봉·이평 확산·기울기 등 지표(현재 봉 제외 규칙) |
| `structure.py` | 스윙, 기준봉, 기준마디, 허리, 살아 있는 마디 |
| `filters.py` | 방향 필터(DA·DB), 고정 필터 F1~F7, 리스크 검사 |
| `scenarios.py` | 진입 시나리오 L1a·L1b·S2·S3 → 후보와 주문 계획 |
| `execution.py` | 체결 엔진(관통 체결, 손절 우선, 갭, 시간 청산, 펀딩)과 순차 처리(F8·F9·가용성 마스크) |
| `random_baseline.py` | 무작위 진입 기준선 |
| `metrics.py` | 통계(부트스트랩·PF·DSR·순열 검정)와 G1 판정 |
| `baselines.py` | 일봉 돈치안 채널 앙상블(비교용) |
| `run_g1.py` | 전체 실행기(이 문서의 명령) |
| `report.py` | 결과 JSON → 한국어 보고서 |
| `tests/` | pytest. `test_no_lookahead.py`가 미래 참조 금지를 검사한다(후보 단계 + 순차 엔진·체결까지 끝까지 절단 불변 T-NLA-6). `review_*_test.py`는 독립 검토 테스트. 실데이터 느린 테스트는 `@pytest.mark.slow`(`-m "not slow"`로 뺄 수 있다) |

## 지키는 원칙

1. **미래 참조 없음** — 판단은 봉 마감 + 60초에, 그때까지 마감된 봉만으로 한다. 스윙은 3봉 뒤에 확정된다.
2. **명세와 정확히 일치** — 애매한 곳의 해석은 DESIGN.md §7(I-번호)에 모두 적었다. 검토 반영 기록과 v2 후보는 DESIGN.md §12.
3. **체결·비용을 부풀리지 않음** — 지정가는 관통해야 체결, 한 봉에서 손절·목표 모두면 손절, 갭은 불리한 쪽. R 분모는 실제 진입가 기준(손절 = −1R).
4. **결정적** — 같은 입력이면 같은 결과. 난수는 `config.make_rng`로만 만든다.

환경: Python 3.11, pandas 3(copy-on-write), numpy 2. scipy 등 추가 패키지는 쓰지 않는다.
