# bot — BTC 추세추종 모의 운영(PAPER) 봇

전략 **E0-L-ENS**(docs/TREND_SPEC.md v1.0: 롱만, 20·55·100일 돌파 즉시 진입, 보호 손절 2×ATR20, 추세 청산 자동)을
텔레그램 2단계 승인 + 모의 체결로 운영한다. **거래소 키·주문 코드 없음**(실제 돈이 움직이지 않는다).

- 설계(인터페이스·상태 머신·DB·보안): [DESIGN.md](./DESIGN.md)
- 운영 설명서(설치·시작·중지·긴급정지·로그·백업): [../docs/RUNBOOK.md](../docs/RUNBOOK.md)

## 구조

| 파일 | 역할 |
|---|---|
| `main.py` | 진입점: `check` / `run [--dry-run]`(paper) / `replay` / `backup` |
| `engine.py` | 일일 사이클(09:01 KST), 1분 tick, 버튼 상태 전이, /pause·/resume |
| `strategy.py` | `backtest.trend` 함수 재사용 어댑터(식 복사 없음) |
| `paper.py` | 모의 체결·보호 손절·추세 청산·펀딩·일일 리포트 |
| `marketdata.py` | `LiveBinance`(공개 REST) / `Replay`(과거 파일, 미래 조회 차단) |
| `telegram_ui.py` | 카드·버튼·콜백 검증·명령·롱 폴링 |
| `analyst.py`, `prompts/analyst_v1.md` | Claude 분석(참고 의견, 관문 아님) |
| `db.py`, `types.py`, `config.py` | SQLite(WAL) 스키마·원자적 전이·감사 로그, 공용 자료형, 설정·비밀 파일 |

## 실행 (개발 PC)

```bash
.venv/bin/python -m pytest backtest/tests bot/tests -m "not slow" -q     # 빠른 시험 전체
.venv/bin/python -m pytest bot/tests/test_parity.py -m slow -q            # 실데이터 전체 재생 대조(약 30초)
.venv/bin/python -m bot.main --config config/replay.local.toml replay --trades-csv /tmp/pos.csv
```
운영은 Docker로만 한다(RUNBOOK §1~3).

## 대조 결과 (replay == backtest)

`replay` 모드로 2020-01-01 ~ 2026-09-28을 재생하고 모든 신호를 판단 + 30분에 자동 승인하면,
모의 거래 100건이 `backtest/results_trend/trades/E0-L-ENS.csv`와 일치한다.

| 항목 | 허용 오차 | 실제 최대 오차 |
|---|---|---|
| 거래 수·N·신호 일봉·진입 시각·청산 시각·청산 사유 | 정확히 같음 | 같음 |
| 진입가·손절·R 분모·청산가 | 1e-9 | 0 |
| 수수료·슬리피지 | 1e-9 | 0 |
| 펀딩·순손익·R | 상대 1e-9 | 약 3e-15 |

데이터 끝에서 백테스트가 `eod`로 닫은 3건은 모의에서 계속 보유(OPEN) 상태이므로 진입 항목만 비교한다(DESIGN §3.6).
재생 입력은 백테스트와 같다: 체결 봉 = 2023-10 전 5분봉 + 이후 1분봉, 펀딩 = 파일 끝 뒤 §12.2 대체값 포함.

## 보안 요약
- 인바운드 포트 0(텔레그램 롱 폴링), 허용 사용자·채팅 ID 각 1개(숫자), 그 밖의 사용자는 무응답 + 감사 로그.
- 비밀은 `/run/secrets/*` 파일로만. 환경 변수에 비밀 이름이 있으면 시작 거부. 로그는 비밀 모양 문자열 자동 가림.
- 컨테이너: 비루트(uid 10001), 읽기 전용 루트, `cap_drop: ALL`, `no-new-privileges`, 로그 10MB×5.
- 공급망: `requirements.txt` 버전 고정, CI에서 pytest + gitleaks(`.gitleaks.toml`).
