# 06. 소프트웨어 스택 조사: 무엇을 설치하고, 무엇을 쓰고, 무엇을 피할까

> 작성일: 2026-09-29 · 작성: 리서처(software_stack) · 상태: 조사 보고서 (코드 작성·패키지 설치 없음)
> 관련 문서: [docs/PLAN.md](../../docs/PLAN.md) §5 기술 스택, [docs/STRATEGY.md](../../docs/STRATEGY.md), [01_existing_systems.md](./01_existing_systems.md) (freqtrade 하이브리드 권고), [03_llm_trading.md](./03_llm_trading.md) (Claude 사용법·비용), [04_exchanges_regulation.md](./04_exchanges_regulation.md) (ccxt 거래소별 차이)
> 표기: **[직접]** = PyPI JSON·GitHub·공식 문서 원문을 직접 열어 확인 · **(검색 요약)** = 웹 검색 결과 요약으로만 확인 · **확인 필요** = 확인하지 못함 · **(추정)** = 가정을 두고 계산한 값

---

## 1. 핵심 요약 (5줄)

1. **Python 3.14와 uv로 시작한다.** uv는 파이썬과 라이브러리 설치를 한 번에 관리하는 도구다. 3.14는 버그 수정이 2027-10까지, 보안 수정이 2030-10까지 나온다. numpy·pandas·TA-Lib·numba·freqtrade가 모두 3.14용 설치 파일을 배포하고 있다. 3.15.0은 10/1 출시 예정이지만 numba·TA-Lib·vectorbt·aiogram 등이 아직 3.15를 지원 범위에 넣지 않았다 [직접].
2. **최소 스택은 외부 패키지 6개로 충분하다.** ccxt · pandas · mplfinance · anthropic · python-telegram-bot[job-queue] · pydantic-settings다.
   - 이동평균과 거래량 배수는 pandas 한 줄로 계산된다. **지표 라이브러리는 필요 없다.**
   - APScheduler를 따로 설치하지 않는다. 텔레그램 라이브러리에 내장된 예약 실행 기능(JobQueue)이 내부적으로 APScheduler 3.x를 쓴다.
   - DB는 Python 내장 sqlite3, 로그는 내장 logging으로 시작한다.
3. **피해야 할 것들:**
   - pandas-ta: GitHub 원 저장소가 사라졌고, PyPI에는 릴리스 2개만 남았으며, 관리 주체가 바뀌었다. 공급망 공격(라이브러리를 통한 악성 코드 유입) 위험 신호다.
   - backtrader: 2023-04 이후 릴리스가 없다.
   - python-binance는 비공식이고, binance-futures-connector는 바이낸스가 폐기를 선언했다.
   - ta: 2023-11 이후 멈췄다.
   - PLAN이 고른 mplfinance는 2024-04 이후 커밋이 없다. **1단계에서 pandas 3.0과 호환되는지 먼저 확인**하고, 안 되면 matplotlib로 직접 그린다.
4. **백테스트는 freqtrade를 주력으로 쓴다(01 문서 권고 유지).** 백테스트는 과거 데이터로 규칙을 모의 실행해 성과를 보는 것이다.
   - freqtrade는 격리 마진 선물, 레버리지, 펀딩비, 상위 타임프레임, 룩어헤드 자동 점검을 모두 갖췄다.
   - 입문용 보조 도구로 backtesting.py를 쓴다.
   - vectorbt 무료판은 레버리지와 지정가 주문이 유료(PRO) 기능이라 맞지 않는다. NautilusTrader는 초보자에게 과하다.
   - Claude의 판단 자체는 백테스트할 수 없다. 모의매매 기록으로 검증한다.
5. **개발 도구는 "폰 + Claude Code(웹) + GitHub"가 중심이다.** VS Code·Git·Docker Desktop은 PC로 작업할 때만 필요하고, 모두 개인에게 무료다.
   - 24시간 운영은 **리눅스 VPS(원격 가상 서버) + Docker Engine**으로 한다.
   - 윈도 PC의 Docker는 운영에 쓰지 않는다. 시계가 틀어지는 문제가 있다(freqtrade 공식 경고).
   - Claude API 비용(추정): 1시간봉마다 빠짐없이 호출하면 Opus 5.5 기준 월 약 $46이다. 코드로 먼저 걸러 필요할 때만 호출하면 월 $6 안팎이다.

---

## 2. 본문

### 2.0 조사 방법과 한계

| 항목 | 내용 |
|---|---|
| PyPI 직접 열람 | 패키지 60여 개의 `https://pypi.org/pypi/<패키지>/json`을 받아 확인했다(2026-09-29). 최신 버전, 릴리스일, 요구 Python 버전, 설치 파일(휠) 종류, 의존성, 라이선스 표기를 봤다 [1] [직접] |
| GitHub 직접 열람 | 저장소 메타데이터(스타, 마지막 푸시, 라이선스, 보관 여부)는 GitHub 검색 API로 봤다 [9]. README·LICENSE·공식 문서 원문은 raw.githubusercontent.com에서, 일부 커밋 이력은 github.com에서 확인했다 [직접] |
| Python 지원 일정 | python/peps 저장소의 PEP 693·719·745·790 원문 [2]–[5] [직접] |
| Anthropic | platform.claude.com 가격·비전 문서 [32][33], code.claude.com Claude Code 개요 [35] [직접]. 세션에 번들된 Anthropic 공식 Claude API 스킬 문서 [34] |
| **웹 검색 한계** | **웹 검색 한도(세션당 200회)를 앞선 조사들이 다 써서 이번에는 1회만 검색했다.** 과제의 "서로 다른 검색어로 최소 10회" 요건은 **충족하지 못했다.** 대신 1차 출처(PyPI·GitHub·공식 문서)를 직접 열어 보완했다. 검색 요약에만 기댄 주장은 1건(pandas-ta 보관 경고, §2.4.1)이다 |
| 차단 사이트 | docs.ccxt.com, 바이낸스 테스트넷, python.org, docs.docker.com 등은 조직 네트워크 정책으로 막혀 있다. 우회하지 않았다. python.org 대신 PEP 원문을, Docker 공식 사이트 대신 docker/docs GitHub 원문을 봤다 |
| 하지 않은 것 | 패키지 설치와 실행 시험은 하지 않았다(개발 금지). 따라서 "실제로 설치·동작하는지"는 모두 **1단계 시험 구현(PoC)에서 확인할 항목**으로 남긴다(§3.4) |

### 2.1 Python 버전 권고

Python은 버전마다 지원 기간이 정해져 있다. 대략 2년간 버그 수정판이 나오고, 이후 출시 5년째까지 보안 수정만 나온다. 보안 수정 기간에는 윈도용 설치 파일 없이 소스만 배포된다 [2][4].

| 버전 | 출시 | 현재 상태 (2026-09-29) | 지원 종료 | 우리 라이브러리 지원 | 판정 |
|---|---|---|---|---|---|
| 3.12 | 2023-10-02 | 보안 수정만 (3.12.14, 2026-08-12) [5] | 약 2028-10 | 대부분 됨 | 비권장. 버그 수정이 이미 끝났다 |
| 3.13 | 2024-10-07 | 마지막 버그 수정판 3.13.16이 **2026-10-06** 예정. 이후 보안 수정만 [4] | 약 2029-10 | 전부 됨 | 차선 |
| **3.14** | 2025-10-07 | 버그 수정 진행 중 (3.14.7, 2026-08-05. 3.14.8은 10-06 예정) [2] | 버그 수정 약 2027-10, 보안 약 2030-10 [2] | **전부 됨.** freqtrade 공식 Docker 이미지도 `python:3.14.7-slim`을 쓴다 [6] | **권고** |
| 3.15 | **2026-10-01 예정** [3] | 출시 직전 | 약 2031-10 | numba·TA-Lib·nautilus는 3.14까지만 설치 파일 제공. aiogram·vectorbt는 `<3.15`로 명시 [1] | 최소 6개월 보류 |

근거는 PyPI의 설치 파일 태그다 [1] [직접]. cp314는 Python 3.14용이라는 뜻이다.

| 패키지 | 설치 파일 태그 | Python 요구 |
|---|---|---|
| numpy 2.5.3 | cp312–cp315 | 3.12 이상 |
| pandas 3.0.6 | cp311–cp315 | 3.11 이상 |
| TA-Lib 0.8.1 | cp39–cp314 | — |
| numba 0.67.0 | cp310–cp314 | — |
| nautilus_trader | cp312–cp314 | — |

- **최신 numpy는 Python 3.12 이상을 요구한다.** 오래된 3.10·3.11 튜토리얼을 따라 하면 버전이 맞지 않을 수 있다.
- 사소한 점: ccxt의 선택적 가속 라이브러리 `coincurve`는 Python 3.14 미만에만 설치되도록 지정돼 있다 [1]. 바이낸스 주문 서명(Ed25519/HMAC)에 영향이 있는지는 **확인 필요**다. 영향이 있더라도 속도 차이일 가능성이 크다(추정).

### 2.2 패키지 관리: uv vs pip

- **패키지 관리자**: 라이브러리를 내려받아 설치하고 버전을 관리하는 도구.
- **가상환경**: 프로젝트별로 격리된 설치 공간.
- **락파일**: 설치된 모든 패키지의 정확한 버전을 적어 둔 파일. 서버에서도 똑같이 재현할 수 있게 해 준다.

| 항목 | **uv** | pip (+ venv) |
|---|---|---|
| 최신 | 0.12.20 (2026-09-28), MIT OR Apache-2.0, GitHub 스타 90,272 [1][9] | Python에 기본 포함 |
| 하는 일 | pip·pip-tools·pipx·poetry·pyenv·virtualenv를 **하나로 대체**한다 [7] | 설치만 한다. 가상환경은 venv로 따로 만든다 |
| Python 자체 설치 | `uv python install 3.14` [8] | 안 됨 (Python을 따로 설치해야 함) |
| 락파일 | `uv.lock` (모든 OS 공용) [7] | 기본 없음 (requirements.txt로 수동 고정) |
| 속도 | pip보다 10–100배 빠르다고 자체 벤치마크에서 밝힘 [7] | 기준 |
| 성숙도 | 아직 0.x(1.0 이전). 명령이 바뀔 여지가 있다 | 매우 성숙 |
| 생태계 | freqtrade 설치 문서가 "uv 또는 Python 3.11+ pip"을 전제로 한다 [30] | 모든 튜토리얼의 기본 |

- **판정: uv 권고.**
  - 초보자가 외울 명령이 4개뿐이다: `uv init`, `uv add`, `uv run`, `uv sync`.
  - 락파일 덕분에 PC·클라우드·VPS가 같은 버전으로 돌아간다.
  - Claude Code가 다루기도 쉽다.
- 대안: pip + venv. 자료는 가장 많다.
- 비용: 무료.
- 보안상 의미: 버전을 락파일로 고정해 두면, 어떤 패키지가 공급망 사고를 당해도(§2.4.1) 그 새 버전이 자동으로 들어오지 않는다. `uv.lock`에 파일 지문(해시)이 기록되는지는 **확인 필요**다.

### 2.3 라이브러리 후보 비교

아래 라이브러리는 모두 **무료 오픈소스**라서 비용 열을 생략한다. 유료 옵션만 §2.7에 따로 정리했다. 라이선스는 개인 사용이라면 모두 문제없다. 뜻만 알아 두면 된다.

| 라이선스 | 뜻 (개인 사용자 관점) |
|---|---|
| MIT · BSD · Apache-2.0 | 자유롭게 사용·수정·배포할 수 있다 |
| LGPL-3.0 | 라이브러리를 **수정해서 배포**할 때만 공개 의무가 생긴다. 가져다 쓰는 앱은 해당 없음 [18] |
| GPL-3.0 | 수정한 프로그램을 **배포**하면 소스를 공개해야 한다 |
| AGPL-3.0 | GPL에 더해, **네트워크 서비스로 남에게 제공**해도 공개 의무가 생긴다 |
| Apache-2.0 + Commons Clause | 사용은 자유지만 이 소프트웨어를 **팔 수는 없다** [23] |

판정 기호: ◎ 권고 · ○ 조건부/대안 · △ 나중에·특수 상황 · ✕ 비권장

#### 2.3.1 거래소 연동

| 패키지 | 최신 (릴리스일) | 라이선스 | 유지보수 상태 | 판정 | 이유 / 대안 |
|---|---|---|---|---|---|
| **ccxt** | 4.5.84 (2026-09-24) | MIT | 매우 활발하다. 9/21·9/23·9/24 연속 릴리스, 스타 44,208, 오늘도 푸시 [1][9] | ◎ | 거래소를 바꿔도 같은 방식으로 쓸 수 있다. freqtrade도 내부에서 쓴다. **릴리스가 거의 매일 나오므로 버전을 고정하고, 올릴 때는 의도적으로 올린다.** 거래소별로 감춰 주지 못하는 차이는 04 문서 §2.7 참고 |
| binance-sdk-derivatives-trading-usds-futures (**바이낸스 공식**) | 17.5.0 (2026-09-23). 첫 출시 2025-07-17, 릴리스 44회 | MIT | 활발 [1] | ○ 예비 | 바이낸스 전용이다. ccxt가 바이낸스 API 변경(예: 2025-12 손절 주문이 Algo 엔드포인트로 이전, 04 문서)을 늦게 따라올 때 비상용으로 둔다. Python `<3.15` |
| python-binance | 1.0.37 (2026-06-08) | MIT | 비공식 개인 프로젝트, 미해결 이슈 533개 [1][9] | ✕ | 공식 SDK나 ccxt를 쓰면 된다 |
| binance-futures-connector | 4.2.0 (2026-04-30) | MIT | **바이낸스가 "DEPRECATED(폐기)"를 선언**하고 새 모듈형 SDK로 옮기라고 안내 [21] | ✕ | 위 공식 SDK로 대체 |

#### 2.3.2 알림·버튼

| 패키지 | 최신 | 라이선스 | 유지보수 | 판정 | 이유 / 대안 |
|---|---|---|---|---|---|
| **python-telegram-bot (PTB)** | 22.8 (2026-06-12) | LGPL-3.0 | 스타 29,496, 미해결 이슈 32개, 오늘도 푸시 [1][9] | ◎ | 인라인 버튼·콜백 예제가 많다(01 문서). **JobQueue(예약 실행)가 내장**돼 있다(`[job-queue]` 옵션이 APScheduler를 설치) [18]. 폴링 방식이라 서버 포트를 열 필요가 없다. 개발 브랜치 README 기준 Bot API 10.0 지원 [18]. 라이브러리를 수정하지 않고 쓰기만 하면 LGPL 의무가 없다 [18] |
| aiogram | 3.31.0 (2026-08-26) | MIT | 스타 5,875, 활발 [1][9] | ○ 대안 | 라우터·미들웨어 구조가 깔끔하고 새 텔레그램 기능 반영이 빠르다(개발 브랜치 README 기준 Bot API 10.3) [19]. 단 **pydantic `<2.14`로 묶여 있어** anthropic 등 다른 패키지와 버전이 부딪칠 수 있다 [1]. 초보자 자료량을 PTB와 비교한 결과는 확인 필요 |
| slack-bolt / slack-sdk | 1.30.0 (2026-07-15) / 3.44.1 (2026-09-03) | MIT | 활발 [1] | △ | Slack을 쓸 경우의 선택지다. **Socket Mode(`SocketModeHandler`)를 쓰면 외부에 공개된 서버 없이 버튼 이벤트를 받을 수 있다** [20] → PLAN §3.1의 근거를 고쳐야 한다(§3.2) |

#### 2.3.3 AI

| 패키지 | 최신 | 라이선스 | 유지보수 | 판정 | 이유 |
|---|---|---|---|---|---|
| **anthropic** (공식 Python SDK) | 1.9.0 (2026-09-28) | MIT | 공식, 9/18·9/22·9/28 연속 릴리스 [1] | ◎ 필수 | Claude API 공식 SDK다. **1.x부터 Python 3.10 이상을 요구하고, 내부 통신 라이브러리가 `httpx2`로 바뀌었다** [1][34]. 옛 0.x 예제 코드와 다를 수 있으니 Claude에게 "anthropic 1.x 기준"이라고 명시한다. pydantic을 이미 의존하므로, Claude 응답을 pydantic 모델(데이터 형식 정의)로 바로 검증할 수 있다(`messages.parse`) [34] |

#### 2.3.4 데이터 처리

| 패키지 | 최신 | 라이선스 | 유지보수 | 판정 | 이유 / 대안 |
|---|---|---|---|---|---|
| **pandas** | 3.0.6 (2026-09-17) | BSD-3 | 매우 활발 | ◎ | 캔들 같은 표 형태 데이터의 표준이다. **3.0(2026-01-21)에서 동작이 바뀌었다**(§2.4.2) [16] |
| numpy | 2.5.3 (2026-09-06) | BSD-3 등 | 활발 | ◎ (자동) | pandas를 설치하면 따라온다. Python 3.12 이상 필요 [1] |
| polars | 1.44.2 (2026-09-09), 2.0 RC 진행 중 | MIT | 매우 활발 | ✕ 지금은 불필요 | 대용량에서는 빠르다. 하지만 캔들 수천 개 규모에서는 이점이 없다. mplfinance·freqtrade·backtesting.py가 모두 pandas 기반이라 변환 수고만 늘어난다. 지금은 2.0 전환기이기도 하다 [1] |

#### 2.3.5 지표 계산

| 패키지 | 최신 | 라이선스 | 유지보수 | 판정 | 이유 / 대안 |
|---|---|---|---|---|---|
| **(pandas로 직접 계산)** | — | — | — | ◎ | 이동평균은 `rolling(n).mean()`, 거래량 배수는 `volume / volume.rolling(n).mean()` 수준이다. STRATEGY §4의 기준봉·허리·꼬리 비율은 어차피 어떤 라이브러리에도 없는 **자체 정의**라 직접 짜야 한다 |
| TA-Lib | 0.8.1 (2026-09-21) | BSD-2 | 활발 (스타 12,261) [9] | ○ 나중에 | **0.6.5부터 C 라이브러리를 포함한 설치 파일(휠)을 제공한다**(리눅스·맥·윈도, Python 3.9–3.14) [14]. 예전 "설치 지옥"은 대부분 해소됐다. 캔들 패턴 인식이 필요해질 때 쓴다. 주의: freqtrade는 `TA-Lib<0.8`을 요구하므로 같은 환경에 넣으면 버전이 부딪친다 [1] |
| pandas-ta | 0.4.71b0 (2025-09-14) | PyPI에 표기 없음(웹사이트 약관으로 연결) | **GitHub 원 저장소 404**, PyPI 릴리스 2개만 남음 [직접] | ✕ **금지** | §2.4.1 |
| pandas-ta-classic | 0.8.32 (2026-09-14) | MIT | 2025-06에 생긴 커뮤니티 포크, 스타 447 [1][9] | △ | pandas-ta 방식이 꼭 필요할 때만 쓴다. 신생·소규모라 채택 전 코드 검토가 필요하다 |
| ta | 0.11.0 (2023-11-02) | MIT | PyPI 릴리스가 2023년 이후 없음, 휠 없이 소스만 [1] | ✕ | 정체 상태 |

참고: freqtrade는 pandas-ta 대신 **자체 포크 `ft-pandas-ta`**(0.3.16, 2025-09-29)를 쓴다 [1].

#### 2.3.6 차트 이미지

| 패키지 | 최신 | 라이선스 | 유지보수 | 판정 | 이유 / 대안 |
|---|---|---|---|---|---|
| mplfinance | 0.12.10b0 (2023-08-02, **베타**) | BSD 계열 | **마지막 커밋 2024-04-02** [15], 미해결 이슈 177개 [9]. 2026-09-24에 "현재 pandas에서 `kwarg_help()`가 충돌한다"는 수정 PR #703이 올라왔다 [15] | ○ 조건부 | 함수 하나로 캔들+거래량+이평 이미지를 만든다. 초보자에게 가장 쉽다. 다만 정체돼 있으므로 **1단계에서 pandas 3.0과 렌더링을 확인**하고 버전을 고정한다 |
| matplotlib | 3.11.2 (2026-09-11) | PSF 계열 | 매우 활발 [1] | ◎ 대안 | mplfinance의 기반 라이브러리다. 캔들은 막대와 선으로 직접 그리면 된다(코드 수십 줄, Claude가 작성 가능) |
| plotly + kaleido | 7.1.0 (2026-09-15) + 1.4.0 (2026-08-31) | MIT | 활발 [1] | ✕ 서버용 비권장 | **kaleido 1.0부터 이미지를 저장하려면 Chrome 브라우저를 따로 설치해야 한다** [17]. 서버·Docker 이미지가 무거워지고 공격 표면이 넓어진다. PC에서 사람이 보는 인터랙티브 차트용이다 |

#### 2.3.7 스케줄링·저장·설정

| 패키지 | 최신 | 라이선스 | 판정 | 이유 / 대안 |
|---|---|---|---|---|
| APScheduler | 3.11.3 (2026-06-28). 4.0은 아직 알파(4.0.0a6, 2025-04-27) [1] | MIT | ○ (간접) | `python-telegram-bot[job-queue]`가 APScheduler `>=3.10.4,<3.12`를 설치해 JobQueue로 감싸 준다 [18]. **따로 설치하거나 직접 다룰 필요가 없다.** 4.0 알파는 쓰지 않는다 |
| **sqlite3** (Python 내장) | Python에 포함 | — | ◎ | 설치가 필요 없고 파일 하나로 끝난다. 감사 로그와 신호 상태(1회 처리·만료) 저장에 충분하다 |
| SQLAlchemy | 2.1.1 (2026-09-25). 2.0.54 (2026-09-15)도 병행 유지 [1] | MIT | △ 나중에 | ORM(파이썬 객체로 DB를 다루는 도구)이다. 2.1은 9/24에 막 나왔으니, 쓸 거라면 2.0.x를 쓴다. 초보 단계에는 학습 부담이 크다 |
| alembic | 1.20.0 (2026-09-11) | MIT | ✕ 지금 불필요 | DB 구조 변경 이력을 관리한다. SQLAlchemy를 쓸 때만 필요하다 |
| pydantic | 2.13.5 (2026-08-28) | MIT | ◎ (자동) | anthropic이 이미 의존한다. Claude 응답 JSON 검증에 쓴다 |
| **pydantic-settings** | 2.15.0 (2026-08-07) | MIT | ◎ | `.env`와 환경변수에서 API 키·리스크 한도를 읽고 **형식을 검증**한다(예: 레버리지가 1~3 사이 숫자인지). 설정이 틀리면 시작하자마자 멈춘다. 보안상 유리하다 |
| python-dotenv | 1.2.3 (2026-08-16) | BSD-3 | △ 대안 | `.env`를 읽기만 하고 검증은 하지 않는다 |

#### 2.3.8 통신·재시도·로깅·품질

| 패키지 | 최신 | 라이선스 | 판정 | 이유 / 대안 |
|---|---|---|---|---|
| httpx | 0.28.1 (2024-12-06), 1.0 개발판 진행 중 [1] | BSD-3 | ✕ 직접 불필요 | PTB가 내부에서 쓰고(`httpx<0.29` 고정), anthropic 1.x는 `httpx2`를 쓴다 [1]. 우리 코드가 직접 HTTP를 호출할 일이 없다 |
| tenacity | 9.1.4 (2026-02-07) | Apache-2.0 | △ | 재시도 도구다. anthropic SDK는 자체 재시도(기본 2회)가 있다 [34]. **주문 요청에는 자동 재시도를 걸지 않는다**(같은 주문이 두 번 나갈 수 있음). 시세 조회에만 쓴다 |
| **logging** (Python 내장) | — | — | ◎ 시작 | 설치가 필요 없다 |
| loguru | 0.7.3 (2024-12-06) | MIT | ○ | 릴리스는 뜸하지만 커밋은 2026-08-30까지 이어지고 있다 [40]. 설정 한 줄로 파일 로그와 파일 교체를 해 준다 |
| structlog | 26.1.0 (2026-06-06) | MIT/Apache-2.0 | △ | 구조화(JSON) 로그다. 나중에 로그 분석 도구와 연결할 때 쓴다 |
| **pytest** | 9.1.1 (2026-06-19) | MIT | ◎ | 하드 가드(레버리지·손절 폭·중복 클릭·만료) **테스트에 필수**다 |
| **ruff** | 0.16.9 (2026-09-24) | MIT | ◎ | 린터(코드 실수 검사)와 포매터(코드 정리)를 한 번에 한다. uv와 같은 회사(Astral) 제품이다 [7] |
| mypy | 2.3.1 (2026-08-15) | MIT | △ | 타입 검사 도구다. 초기에는 생략해도 된다 |
| pre-commit | 4.6.2 (2026-08-10) | MIT | ○ | git 커밋 직전에 검사를 자동 실행한다 |
| **gitleaks** (Go 도구) | GitHub 스타 29,548, 활발 [9] | 확인 필요 | ◎ (보안) | 커밋에 API 키가 섞여 들어가면 막아 준다. pre-commit에 연결한다. 대안: Yelp detect-secrets(스타 4,647) |

감사 로그는 로그 파일이 아니라 **DB(sqlite)에 남긴다**(PLAN §4.4). logging은 운영 진단용이다.

### 2.4 쟁점 상세

#### 2.4.1 pandas-ta: 공급망 위험 사례 (채택 금지)

| 확인 내용 | 근거 |
|---|---|
| GitHub 원 저장소 `twopirllc/pandas-ta`가 **404**다. GitHub 검색 API도 "존재하지 않거나 권한 없음"으로 응답했다 | [10] [직접] |
| PyPI에 남은 릴리스는 **0.4.67b0(2025-09-03)과 0.4.71b0(2025-09-14) 두 개뿐**이다. 과거 0.3.x 이력이 PyPI 목록에서 사라졌다 | [11] [직접] |
| PyPI 작성자는 "Pandas TA Support &lt;support@pandas-ta.dev&gt;"다. 소스 저장소 링크가 없고, 라이선스는 PyPI에 적혀 있지 않고 웹사이트로 연결된다. `numba==0.61.2`로 정확히 고정돼 있고, 분류상 Python 3.12만 지원한다 | [1][11] [직접] |
| 원작자 공지: "2026-07-01까지 추가 지원이 없으면 저장소를 보관(archive)한다", "2025-07-01 이후 릴리스는 기업 유료·구독형으로 전환" | [13] (검색 요약) |
| 포크 저장소 이슈 #30: 관리자가 바뀌었고, PyPI 이력이 지워졌고, 새 웹사이트가 생겼다. 이를 두고 사용자가 **공급망 공격 가능성을 우려**했다. 결론은 없다 | [12] [직접] |

→ 보안 실무 관점에서 전형적인 위험 신호가 모두 모였다: **관리 주체 변경 + 이력 삭제 + 소스 비공개**. 돈이 걸린 레버리지 선물 봇의 의존성에서는 제외한다. 이 사례를 **새 패키지 도입 체크리스트**(§3.3)의 반례로 쓴다.

#### 2.4.2 mplfinance 정체와 pandas 3.0 변경점 (바이브 코딩 주의)

pandas 3.0 공식 변경 문서의 주요 변경 [16] [직접]:

| 변경 | 내용 | 우리에게 주는 영향 |
|---|---|---|
| 문자열 전용 타입이 기본값 | 문자열 열이 `object`가 아니라 새 string 타입이 된다 | 심볼·신호 ID 비교 코드에서 경고가 날 수 있다 |
| Copy-on-Write(복사 시점 변경)가 기본값 | 복사·뷰 동작이 일관되게 바뀌었다. `copy=` 키워드는 효과가 없다 | 옛 예제의 "체인 할당"(`df[...][...] = 값`)이 기대대로 동작하지 않는다 |
| 날짜 해상도 자동 추론 | 날짜 변환이 항상 나노초로 되던 것에서, 입력에 맞춰 단위를 추론하는 방식으로 바뀌었다 | ccxt가 주는 밀리초 타임스탬프를 변환할 때 결과 타입이 달라질 수 있다 |

- **바이브 코딩 주의**: Claude가 학습한 예제 대부분은 pandas 2.x 기준일 가능성이 높다(추정). 코드를 요청할 때 "pandas 3.0 기준"이라고 명시한다. 1단계에서 경고(FutureWarning 등) 없이 도는지 확인한다.
- mplfinance는 2024-04 이후 커밋이 없다. 현재 pandas에서 일부 함수(`kwarg_help`)가 충돌한다는 PR이 열려 있다 [15]. 핵심 기능인 `plot()`이 pandas 3.0에서 정상인지는 **확인 필요**다.
  - 1단계 PoC 확인 항목: 캔들+거래량+MA 3개가 한 장에 그려지는지, 경고가 없는지.
  - 실패하면 matplotlib로 직접 그린다.
  - 이미지 안에는 한글을 넣지 않는다(폰트 문제 회피). 설명은 텔레그램 캡션 텍스트로 보낸다.

#### 2.4.3 스케줄러와 비동기: 프로그램 하나, 이벤트 루프 하나

- PTB v20부터는 **비동기(asyncio)** 방식이다 [18]. 비동기란 무언가를 기다리는 동안 다른 일을 번갈아 처리하는 방식이다. 버튼 클릭 대기와 정시 분석을 **한 프로그램**에서 함께 처리할 수 있다.
- ccxt(의존성에 aiohttp 포함 [1])와 anthropic(AsyncAnthropic [34])도 비동기 버전이 있다. 셋을 하나의 비동기 루프로 통일하면 프로세스가 1개로 끝난다.
- PLAN의 "APScheduler 별도 사용"은 PTB JobQueue로 흡수한다. JobQueue 안에서 APScheduler 3.x가 돈다 [18].
- **시계 동기화(NTP)는 필수다.** freqtrade 문서는 "봇을 돌리는 시스템 시계는 NTP로 자주 동기화돼야 거래소와 통신 문제가 없다"고 경고한다 [30]. 윈도 Docker에서는 컨테이너 시계가 점점 뒤로 밀려 `Timestamp ... outside of the recvWindow` 오류가 난다 [31].
- 캔들 마감 후 거래소 데이터가 몇 초 뒤에 확정되는지는 **확인 필요**다. 마감 직후가 아니라 몇 초 뒤에 조회하는 안전 여유를 두는 것을 1단계에서 정한다.

#### 2.4.4 텔레그램 vs Slack: 결론은 유지, 근거는 수정

- 텔레그램 유지 권고는 01 문서와 같다. 주요 봇들(freqtrade, OctoBot, Jesse)이 모두 텔레그램을 기본 알림 창구로 쓰고, 폰 사용성이 좋다.
- PLAN §3.1은 "Slack은 외부 공개 서버(HTTPS)가 필요하다"고 적었다. 이것은 **정확하지 않다.** Slack Bolt의 **Socket Mode**는 봇이 Slack에 먼저 접속하는 방식이라 포트를 열 필요가 없다 [20].
- 두 채널 모두 인바운드 포트 없이 운영할 수 있다. 차이는 **모바일 사용성, 설정 단순성, 개인 용도 적합성**이다. 표의 근거만 고친다.
- 01 문서에서 확인한 제약: **봇 토큰 하나에는 폴링 연결 하나만 허용된다.** 개발용과 운영용 봇 토큰을 분리한다. freqtrade를 함께 쓰면 freqtrade 쪽 텔레그램은 끈다.

#### 2.4.5 Claude API SDK와 비용 (추정)

사용할 기능과 근거:

| 기능 | 내용 | 근거 |
|---|---|---|
| 모델 가격 | 입력/출력 $/100만 토큰: Opus 5.5 $4/$20 · Sonnet 5.5 $2/$10 · Haiku 4.5 $1/$5 | [32] [직접] |
| 캐시 읽기 | Opus 5.5 $0.20 (기본 입력가의 0.05배) · Sonnet 5.5 $0.20 · Haiku 4.5 $0.10. 5분 캐시 쓰기는 입력가의 1.25배, 1시간 캐시 쓰기는 2배 | [32] [직접] |
| Batch API | 입력·출력 모두 50% 할인. 비실시간 처리 전용 | [32] [직접] |
| 이미지 토큰 | `⌈가로/28⌉ × ⌈세로/28⌉` 토큰. 1000×1000 이미지는 1,296토큰. Opus 5.5는 고해상도 등급(긴 변 최대 2576px), Haiku 4.5는 표준 등급(긴 변 1568px) | [33] [직접] |
| 구조화 출력 | `output_config.format`으로 JSON 스키마를 강제한다. Python은 `messages.parse()`로 결과를 검증한다 | [34] |
| thinking·effort | Opus 5.5는 thinking(내부 추론)을 끌 수 없고 effort로 조절한다(기본 medium). **추론 토큰은 화면에 안 보여도 출력 토큰으로 과금된다** | [34] |
| 거절(refusal) | 안전 분류기가 거절하면 `stop_reason == "refusal"`이 온다. 응답 본문을 읽기 전에 반드시 확인하고, 서버측 `fallbacks`를 쓴다. assistant prefill(응답 앞부분 미리 채우기)은 불가 | [34] |

월 비용 추정 **(추정)**. 가정은 다음과 같다.

- 호출 1회당 입력 약 6,000토큰: 시스템 프롬프트·규칙 약 3,000 + 수치 JSON 약 1,700 + 1000×1000 차트 이미지 1,296.
- 출력 약 2,000토큰: 결과 JSON 약 500 + 추론 약 1,500. effort low~medium 가정이며 실측이 필요하다.

| 호출 방식 | 월 호출 수 | Opus 5.5 ($0.064/회) | Sonnet 5.5 ($0.032/회) | Haiku 4.5 ($0.016/회) |
|---|---|---|---|---|
| 1시간봉 마감마다 전수 호출 | 720 | **약 $46** | 약 $23 | 약 $12 |
| 4시간봉 마감마다 전수 호출 | 180 | 약 $12 | 약 $6 | 약 $3 |
| **코드 규칙이 후보를 낼 때만 호출** (하루 3회 가정) | 90 | **약 $6** | 약 $3 | 약 $1.4 |

- **프롬프트 캐싱은 도움이 거의 안 된다.** 호출 간격이 1시간이면 5분 캐시는 만료된다. 1시간 캐시는 쓰기 비용이 2배라 이득이 작다. 03 문서의 결론과 같다.
- **Batch API(50% 할인)는 실시간 알림에 못 쓴다.** 지난 신호를 한꺼번에 다시 채점하는 사후 평가에만 쓴다.
- 가장 큰 절감 수단은 **"코드가 먼저 거르고 Claude는 후보만 해석"**하는 구조다. STRATEGY v0.2의 "코드 계산 → Claude 해석" 구조와 일치한다.
- 모델 선택은 사용자 결정이다. 비용이 같은 수준이라면 Opus 5.5의 effort를 low로 먼저 측정해 보는 것이 공식 가이드의 권장 순서다 [34]. Anthropic Console에서 **월 지출 한도**를 설정한다(03 문서).

### 2.5 백테스트 도구 비교

용어:
- **룩어헤드 편향**: 과거 시점 판단에 미래 데이터가 섞여 성과가 부풀려지는 오류.
- **펀딩비**: 무기한 선물에서 롱·숏 사이에 주기적으로 주고받는 비용.
- **슬리피지**: 원하는 가격과 실제 체결 가격의 차이.

| 도구 | 최신 (릴리스일) | 라이선스 | 선물·레버리지 | 펀딩비 | 다중 타임프레임 | 룩어헤드 점검 | 난이도 | 판정 |
|---|---|---|---|---|---|---|---|---|
| **freqtrade** | 2026.8 (2026-08-31), 스타 54,911 [1][9] | GPL-3.0 | ◎ `trading_mode: futures`, `margin_mode: isolated`(격리) [28] | ◎ 반영. 데이터가 없는 기간은 0으로 두라고 권장 [28] | ◎ `@informative` 데코레이터로 상위 봉 사용 [29] + `--timeframe-detail 5m`로 봉 안의 움직임 근사 [26] | ◎ `lookahead-analysis`, `recursive-analysis` 명령 [27] | 중 | **◎ 주력** |
| backtesting.py | 0.6.6 (2026-07-22), 스타 9,007 [1][9] | AGPL-3.0 | ○ `margin` 값으로 레버리지 근사(레버리지 = 1/margin), 숏, 손절·익절(`sl`/`tp`) 지원. 소수점 수량은 `FractionalBacktest` [24] | ✕ 없음 (직접 구현) | ○ `resample_apply` [24] | ✕ 없음 | **하** | ○ 학습·빠른 확인용 보조 |
| vectorbt (무료판) | 1.1.1 (2026-09-26), 스타 9,210 [1][9] | Apache-2.0 + Commons Clause [23] | △ **레버리지·지정가 주문은 PRO(유료) 기능** [23] | 확인 필요 | ○ | ✕ | 중상 (numba·scikit-learn 등 의존성 무거움) [1] | ✕ 보류 |
| backtrader | 1.9.78.123 (**2023-04-19**), 마지막 푸시 2024-08-19, 이슈 게시판 닫힘 [1][9] | GPL-3.0 | ○ | ✕ | ○ | ✕ | 중 | ✕ 정체 |
| NautilusTrader | 1.231.0 (2026-08-02), 2.0.0rc5 (2026-09-15) [1] | LGPL-3.0 | ◎ | 확인 필요 | ◎ | 이벤트 기반 설계로 구조적으로 방지(01 문서) | **상** (Rust 코어, Python 3.12 이상) | ✕ 과함 |
| Jesse | 3.2.3 (2026-09-27), 스타 8,596 [1][9] | MIT (코어) | ◎ | 확인 필요 | ◎ | 룩어헤드 방지를 강조(01 문서) | 중 | ○ 대안 (실거래 플러그인은 유료, 01 문서) |

**freqtrade 백테스트가 가정하는 것** [26] [직접]. 결과를 읽을 때 반드시 기억한다.

- 진입은 봉 시가에서 이뤄지고, 요청 가격이 봉 고가~저가 범위 안이면 **슬리피지 없이 체결**된다고 본다.
- 손절은 **정확히 손절가에 체결**되고, 수수료 2배만큼 손실이 추가된다고 본다. 실제 급락에서는 더 불리하게 체결될 수 있다.
- 한 봉 안에서는 **저가가 고가보다 먼저** 왔다고 가정한다(자본 보호 쪽). `--timeframe-detail 5m`로 이 문제를 완화한다.
- "백테스트는 드라이런(모의 실거래)을 **절대 대체하지 못한다**."

→ 권고 흐름:
1. STRATEGY의 코드 규칙(◎)을 freqtrade로 백테스트한다(Docker, 별도 환경).
2. 한 규칙만 빨리 실험할 때는 backtesting.py를 쓴다.
3. **Claude 판단 계층은 백테스트하지 않는다.** Claude가 과거 가격을 이미 알고 있을 수 있어 룩어헤드가 생긴다(01·03 문서). 테스트넷과 모의매매 기록으로 A/B 비교한다.

### 2.6 개발 도구

| 도구 | 용도 | 언제 필요 | 비용 | 판정 | 비고 |
|---|---|---|---|---|---|
| **Claude Code** (웹·모바일 앱) | 코드 작성·실행·PR 생성 | **지금부터** (현재 사용 중) | Claude 구독 또는 Anthropic Console 계정이 필요하다 [35]. 요금제 가격은 확인 필요 | ◎ | 브라우저와 iOS·Android Claude 앱에서 쓸 수 있다 [35]. 데스크톱 앱은 유료 구독이 필요하다 [35]. 설치형은 npm 방식이 폐기돼 공식 설치 스크립트나 WinGet을 쓴다 [36]. **주의 1**: 이번 세션의 클라우드 환경은 네트워크 정책이 `testnet.binancefuture.com`, `docs.ccxt.com` 연결을 거부했다(세션 프록시 기록). 클라우드에서 테스트넷 연동을 시험하려면 세션 제목 표시줄의 클라우드 환경 메뉴 → Edit → Network access에서 허용 도메인을 추가해야 한다. **주의 2**: 클라우드 세션에는 **실거래 키를 넣지 않는다.** 테스트넷 키만 넣는다 |
| **GitHub** | 코드 보관, PR 검토 | 지금 (이 저장소를 이미 사용 중) | 무료 요금제로 충분할 것으로 본다(요금제 세부는 확인 필요) | ◎ | 저장소는 **비공개**를 권장한다. 비공개 저장소에서 GitHub 비밀정보 스캐닝이 어디까지 제공되는지는 확인 필요 → gitleaks로 로컬에서 먼저 막는다 |
| Git | 버전 관리 | PC 작업 시 | 무료 | ◎ | 윈도에서 Claude Code를 쓰면 Git for Windows 설치를 권장한다(없으면 PowerShell로 대체) [35] |
| VS Code | 코드 편집기 | PC 작업 시 | 무료. Microsoft 제품 라이선스이고, 원본 소스(Code-OSS)는 MIT [37] | ○ | Claude Code 확장이 있다 [35]. 폰 중심이면 당장은 필요 없다 |
| Docker Desktop | PC에서 컨테이너 실행 | 윈도·맥 PC에서 freqtrade 백테스트를 할 때 | **개인 사용, 교육, 소규모 사업자(250인 미만이면서 연매출 1천만 달러 미만) 무료** [38] | △ | 윈도는 Windows 10 22H2 / 11 23H2 이상과 WSL 2(윈도 속 리눅스)가 필요하다 [38]. **윈도 Docker는 운영용으로 쓰지 않는다.** 시계 밀림 문제 때문이며, freqtrade도 "실험·데이터 다운로드·백테스트용만"이라고 적었다 [31] |
| **Docker Engine** (리눅스 서버) | VPS에서 봇·freqtrade 24시간 실행 | 6단계 배포 | 무료. 오픈소스 Moby 기반, Apache-2.0 [39] | ◎ | Docker Desktop 라이선스와 별개다. freqtrade도 "리눅스 VPS 사용이 가장 안정적"이라고 권장한다 [31]. ARM 서버에서는 freqtrade를 Docker로만 지원한다 [30] |

### 2.7 비용 요약

| 항목 | 비용 | 비고 |
|---|---|---|
| 라이브러리 전부, Python, uv, Git, VS Code | 0원 | 오픈소스·무료 |
| GitHub | 0원 (무료 요금제 가정) | 확인 필요 |
| Docker Desktop | 0원 (개인 사용) | 대기업 상업 사용만 유료 [38] |
| Docker Engine (VPS) | 0원 | [39] |
| Claude Code | 기존 Claude 구독에 포함되는지는 요금제에 따라 다르다 | 확인 필요 [35] |
| **Claude API** | 월 약 $1.4 ~ $46 (추정, §2.4.5) | claude.ai 구독과 **별도 과금**이다(Console에서 키 발급) |
| VPS | 확인 필요 | 운영 환경 조사 범위. 이 문서에서는 조사하지 않았다 |
| vectorbt PRO, Jesse 실거래 플러그인 | 유료 | **필요 없다** |

---

## 3. 우리 시스템에 대한 시사점과 권고

### 3.1 권고 최소 스택 (PLAN §6 단계별)

| 단계 | 추가하는 것 | 우리 봇의 외부 패키지 누적 |
|---|---|---|
| 0. 준비 | uv 설치 → `uv python install 3.14`. Git·GitHub(사용 중). gitleaks + pre-commit. 개발용·운영용 텔레그램 봇 토큰 분리 | 0 |
| 1. 데이터 | **ccxt**, **pandas**, **mplfinance** (numpy·matplotlib는 자동 설치). pandas 3.0 호환 확인 | 3 |
| 2. 분석 | **anthropic** (pydantic 자동 설치) | 4 |
| 3. 알림 | **python-telegram-bot[job-queue]** (APScheduler 자동 설치) | 5 |
| 4. 모의주문 | 추가 없음 (ccxt 사용). 비상용으로 바이낸스 공식 SDK를 검토 | 5 |
| 5. 리스크 | **pydantic-settings**, sqlite3(내장), logging(내장) | 6 |
| 6. 배포 | 리눅스 VPS + Docker Engine, NTP 시계 동기화 | 6 |
| 7. 검증 | **freqtrade는 우리 봇과 분리된 Docker 컨테이너로 설치**. 보조 도구 backtesting.py는 별도 환경 | 6 (별도 환경 제외) |
| 개발 도구 | pytest, ruff | +2 (개발용) |

freqtrade를 분리하는 이유는 세 가지다. 의존성이 많고(scipy, TA-Lib `<0.8`, ft-pandas-ta 등 [1]), 우리 봇과 버전이 부딪칠 수 있고, GPL-3.0이다. 01 문서의 "하이브리드(두뇌는 직접, 근육은 freqtrade)" 구조와도 맞는다.

### 3.2 기존 기획(PLAN §5) 수정 제안

| 항목 | PLAN v0.1 | 제안 | 근거 |
|---|---|---|---|
| Python 버전 | 명시 없음 | **3.14 고정** (`.python-version`) | §2.1 [2][6] |
| 패키지 관리 | 명시 없음 | **uv + uv.lock**, 모든 버전 고정 | §2.2 [7] |
| 스케줄링 | APScheduler 별도 | **PTB JobQueue**로 흡수 (내부가 APScheduler 3.x) | [18] |
| 지표 | pandas | 유지. **pandas로 직접 계산.** pandas-ta는 금지, TA-Lib은 필요할 때만 | §2.3.5, §2.4.1 |
| 차트 이미지 | mplfinance | 유지하되 **1단계에서 pandas 3.0 호환 확인**. 실패하면 matplotlib 직접 | §2.4.2 [15][16] |
| 알림 채널 근거 | "Slack은 외부 공개 서버 필요" | **Slack도 Socket Mode면 필요 없다**로 수정. 텔레그램 선택은 유지 | [20] |
| 거래소 연동 | ccxt | 유지. **버전 고정 + 올릴 때마다 테스트넷에서 손절 주문 생성 회귀 테스트.** 비상용 바이낸스 공식 SDK. python-binance는 쓰지 않는다 | §2.3.1, 04 문서 |
| 저장소 | SQLite | 유지. **내장 sqlite3부터.** SQLAlchemy는 나중에 | §2.3.7 |
| 설정·비밀 | `.env` | 유지 + **pydantic-settings로 형식 검증** + gitleaks | §2.3.7 |
| 배포 | Docker + VPS | 유지. **리눅스 VPS의 Docker Engine**을 명시. 윈도 PC 운영과 윈도 Docker 운영은 비권장. NTP 필수 | [30][31][39] |
| 백테스트 | (7단계에 개념만) | **freqtrade 주력**, backtesting.py 보조. Claude 계층은 모의매매로 검증 | §2.5 |

### 3.3 보안 관점 권고 (공급망·운영)

1. **의존성 최소화**: 외부 패키지를 6개로 제한하고 전부 락파일로 고정한다. 업데이트는 월 1회 의도적으로 하고, 테스트넷 통과 후 반영한다.
2. **새 패키지 도입 체크리스트** (pandas-ta가 반례):
   - 소스 저장소가 공개돼 있고 PyPI와 연결돼 있는가
   - 최근 12개월 안에 릴리스가 있는가
   - 관리자가 바뀌었거나 릴리스 이력이 지워지지 않았는가
   - 라이선스가 명시돼 있는가
   - 휠(미리 빌드된 설치 파일)이 우리 Python 버전용으로 나오는가
3. **비밀정보**: `.env`를 `.gitignore`에 넣고, gitleaks를 pre-commit에 연결한다. 클라우드 Claude Code 세션에는 테스트넷 키만 넣는다.
4. **주문 요청은 자동 재시도 금지**: tenacity 같은 재시도는 조회에만 쓴다. 주문은 고유 ID(clientOrderId 등)로 중복을 막는다. 중복 방지 방식의 거래소별 세부는 확인 필요.
5. **ccxt 업데이트 회귀 테스트**: 거래소 API가 예고 없이 바뀐 사례가 있다(2025-12 바이낸스 Algo 주문 이전, 04 문서). 업데이트 후에는 "진입 → 거래소에 손절 주문이 실제로 존재하는지"를 테스트넷에서 확인한다.
6. **무거운 런타임 배제**: 서버 이미지에 Chrome(kaleido)을 넣지 않는다. 공격 표면과 이미지 크기를 줄이기 위해서다.
7. **시계 동기화**: VPS에서 NTP를 켜고, 시작할 때 거래소 서버 시각과의 차이를 점검한다(freqtrade 경고 [30]).

### 3.4 남은 확인 필요 항목 (1단계 PoC에서 확인)

| # | 확인할 것 | 방법 |
|---|---|---|
| 1 | mplfinance `plot()`이 pandas 3.0.x에서 경고·오류 없이 캔들+거래량+MA 3개를 그리는지 | 1단계 PoC |
| 2 | ccxt 4.5.x의 바이낸스 선물 손절(Algo 엔드포인트)이 테스트넷에서 생성·조회되는지 | 4단계 전 PoC (04 문서와 공동) |
| 3 | 1시간봉 마감 후 거래소 캔들 데이터가 확정되기까지의 지연 | 1단계에서 여러 번 측정 |
| 4 | Claude 호출 1회당 실제 입력·출력 토큰(특히 effort low/medium별 추론 토큰) | 2단계에서 `usage` 기록으로 실측 → §2.4.5 추정 갱신 |
| 5 | `uv.lock`에 해시가 기록되는지, 설치 시 해시 검증이 되는지 | uv 문서 확인 |
| 6 | Python 3.14에서 ccxt `coincurve` 미설치가 바이낸스 서명에 영향을 주는지 | 1단계 PoC |
| 7 | GitHub 무료 요금제에서 비공개 저장소 비밀정보 스캐닝 제공 범위, Claude Code 요금제별 포함 여부 | 공식 페이지 확인 (현재 차단) |
| 8 | gitleaks 라이선스·최신 버전, VPS 비용 | 공식 저장소·운영 환경 조사 |
| 9 | 웹 검색 보강: 한국어 초보자 자료량(PTB vs aiogram), 커뮤니티 평판 | 검색 한도가 복구되면 재조사 |

---

## 4. 출처 목록

**PyPI (직접 열람, 2026-09-29)**
- [1] PyPI JSON API — `https://pypi.org/pypi/<패키지>/json`. 조회한 패키지: ccxt, python-binance, binance-futures-connector, binance-connector, binance-sdk-derivatives-trading-usds-futures, pybit, python-okx, python-telegram-bot, aiogram, slack-bolt, slack-sdk, anthropic, pandas, numpy, polars, pandas-ta, pandas-ta-classic, ft-pandas-ta, TA-Lib, ta, finta, talipp, tulipy, stock-indicators, numba, mplfinance, matplotlib, plotly, kaleido, choreographer, finplot, bokeh, lightweight-charts, APScheduler, SQLAlchemy, alembic, aiosqlite, duckdb, pyarrow, pydantic, pydantic-settings, python-dotenv, httpx, tenacity, loguru, structlog, pytest, pytest-asyncio, ruff, mypy, pre-commit, uv, vectorbt, backtesting, backtrader, freqtrade, nautilus_trader, jesse. 예: https://pypi.org/pypi/ccxt/json , https://pypi.org/pypi/pandas-ta/json , https://pypi.org/pypi/TA-Lib/json

**Python 지원 일정 (직접)**
- [2] PEP 745 (Python 3.14 일정) — https://raw.githubusercontent.com/python/peps/main/peps/pep-0745.rst (https://peps.python.org/pep-0745/)
- [3] PEP 790 (Python 3.15 일정) — https://raw.githubusercontent.com/python/peps/main/peps/pep-0790.rst
- [4] PEP 719 (Python 3.13 일정) — https://raw.githubusercontent.com/python/peps/main/peps/pep-0719.rst
- [5] PEP 693 (Python 3.12 일정) — https://raw.githubusercontent.com/python/peps/main/peps/pep-0693.rst
- [6] freqtrade Dockerfile (`python:3.14.7-slim-trixie`) — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/Dockerfile

**패키지 관리 (직접)**
- [7] uv README — https://raw.githubusercontent.com/astral-sh/uv/main/README.md
- [8] uv Python 버전 문서 — https://raw.githubusercontent.com/astral-sh/uv/main/docs/concepts/python-versions.md

**GitHub 메타데이터 (직접, GitHub 검색 API, 2026-09-29)**
- [9] 스타·마지막 푸시·라이선스·보관 여부 — https://github.com/ccxt/ccxt , https://github.com/freqtrade/freqtrade , https://github.com/nautechsystems/nautilus_trader , https://github.com/mementum/backtrader , https://github.com/TA-Lib/ta-lib-python , https://github.com/polakowo/vectorbt , https://github.com/kernc/backtesting.py , https://github.com/bukosabino/ta , https://github.com/matplotlib/mplfinance , https://github.com/python-telegram-bot/python-telegram-bot , https://github.com/aiogram/aiogram , https://github.com/sammchardy/python-binance , https://github.com/anthropics/anthropic-sdk-python , https://github.com/agronholm/apscheduler , https://github.com/Delgan/loguru , https://github.com/hynek/structlog , https://github.com/jd/tenacity , https://github.com/encode/httpx , https://github.com/plotly/Kaleido , https://github.com/astral-sh/uv , https://github.com/astral-sh/ruff , https://github.com/xgboosted/pandas-ta-classic , https://github.com/gitleaks/gitleaks , https://github.com/Yelp/detect-secrets , https://github.com/pre-commit/pre-commit , https://github.com/microsoft/vscode , https://github.com/jesse-ai/jesse , https://github.com/pandas-dev/pandas , https://github.com/pola-rs/polars

**지표·차트 라이브러리**
- [10] pandas-ta 원 저장소 (HTTP 404) — https://github.com/twopirllc/pandas-ta [직접]
- [11] pandas-ta PyPI — https://pypi.org/project/pandas-ta/ [직접]
- [12] pandas-ta-classic 이슈 #30 "Can someone Explain what happened with pandas-ta?" — https://github.com/xgboosted/pandas-ta-classic/issues/30 [직접]
- [13] pandas-ta 보관 경고·유료 전환 방침 — https://libraries.io/pypi/pandas-ta , https://aur.archlinux.org/packages/python-pandas-ta , https://github.com/twopirllc (검색 요약)
- [14] TA-Lib PyPI 설명 ("Wheels: starting with version 0.6.5 ... include the underlying TA-Lib C library") — https://pypi.org/project/TA-Lib/ [직접]
- [15] mplfinance 커밋 이력 — https://github.com/matplotlib/mplfinance/commits/master , pandas 관련 PR #703 — https://github.com/matplotlib/mplfinance/issues?q=pandas+3 [직접]
- [16] pandas 3.0.0 변경 사항 — https://raw.githubusercontent.com/pandas-dev/pandas/main/doc/source/whatsnew/v3.0.0.rst [직접]
- [17] kaleido PyPI ("As of version 1.0.0, Kaleido requires Chrome to be installed") — https://pypi.org/project/kaleido/ [직접]

**알림·거래소 SDK**
- [18] python-telegram-bot README (Optional Dependencies, 라이선스, Bot API 지원) — https://raw.githubusercontent.com/python-telegram-bot/python-telegram-bot/master/README.rst [직접]
- [19] aiogram README — https://raw.githubusercontent.com/aiogram/aiogram/dev-3.x/README.rst [직접]
- [20] slack-bolt PyPI ("Running a Socket Mode app", `SocketModeHandler`) — https://pypi.org/project/slack-bolt/ [직접]
- [21] binance-futures-connector PyPI ("This repository is deprecated") — https://pypi.org/project/binance-futures-connector/ , 새 저장소 https://github.com/binance/binance-connector-python [직접]
- [22] 바이낸스 공식 USDⓈ-M 선물 SDK — https://pypi.org/project/binance-sdk-derivatives-trading-usds-futures/ [직접]

**백테스트**
- [23] vectorbt LICENSE.md (Apache 2.0 with Commons Clause), README (PRO 기능: limit orders, leverage) — https://raw.githubusercontent.com/polakowo/vectorbt/master/LICENSE.md , https://raw.githubusercontent.com/polakowo/vectorbt/master/README.md [직접]
- [24] backtesting.py README·소스 (`margin`, `sl`/`tp`, `resample_apply`, `FractionalBacktest`) — https://raw.githubusercontent.com/kernc/backtesting.py/master/README.md , https://raw.githubusercontent.com/kernc/backtesting.py/master/backtesting/backtesting.py , https://raw.githubusercontent.com/kernc/backtesting.py/master/backtesting/lib.py [직접]
- [25] backtrader README — https://raw.githubusercontent.com/mementum/backtrader/master/README.rst [직접]
- [26] freqtrade 백테스트 문서 (Assumptions, `--timeframe-detail`) — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/backtesting.md [직접]
- [27] freqtrade lookahead-analysis — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/lookahead-analysis.md [직접]
- [28] freqtrade 레버리지·마진 모드·펀딩비 — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/leverage.md [직접]
- [29] freqtrade 전략 작성 (`@informative`) — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/strategy-customization.md [직접]
- [30] freqtrade 설치 문서 (Python ≥3.11, uv, 시계 동기화, ARM은 Docker) — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/installation.md [직접]
- [31] freqtrade Docker 빠른 시작 (윈도 Docker 시계 문제, 리눅스 VPS 권장) — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/docker_quickstart.md [직접]

**Anthropic**
- [32] Claude API 가격 — https://platform.claude.com/docs/en/about-claude/pricing.md [직접]
- [33] Claude 비전(이미지) 문서 — https://platform.claude.com/docs/en/build-with-claude/vision.md [직접]
- [34] Anthropic 공식 Claude API 스킬 문서(세션 번들, 2026-09 기준: SDK 1.x·httpx2·structured outputs·effort·refusal/fallbacks·기본 재시도 2회), Python SDK 저장소 — https://github.com/anthropics/anthropic-sdk-python , 마이그레이션 가이드 https://github.com/anthropics/anthropic-sdk-python/blob/main/MIGRATION.md
- [35] Claude Code 개요 (지원 화면, 구독·Console 필요, 데스크톱은 유료 구독, 윈도 Git 권장) — https://code.claude.com/docs/en/overview [직접]
- [36] Claude Code README (npm 설치 폐기) — https://raw.githubusercontent.com/anthropics/claude-code/main/README.md [직접]

**개발 도구**
- [37] VS Code (Code-OSS) README — https://raw.githubusercontent.com/microsoft/vscode/main/README.md [직접]
- [38] Docker Desktop 설치 문서 (라이선스 조건, 윈도 요구사항) — https://raw.githubusercontent.com/docker/docs/main/content/manuals/desktop/setup/install/mac-install.md , https://raw.githubusercontent.com/docker/docs/main/content/manuals/desktop/setup/install/windows-install.md [직접]
- [39] Moby (Docker Engine 오픈소스, Apache-2.0) — https://github.com/moby/moby [직접]
- [40] loguru 커밋 이력 — https://github.com/Delgan/loguru/commits/master [직접]

**내부 문서**
- [41] 01_existing_systems.md (freqtrade 하이브리드, 텔레그램 토큰당 폴러 1개), 03_llm_trading.md (차트 이미지 한계, 캐싱 판단, 월 지출 한도), 04_exchanges_regulation.md (ccxt 거래소별 차이, 바이낸스 Algo 주문 이전)
