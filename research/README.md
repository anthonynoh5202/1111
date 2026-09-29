# 리서치 에이전트 팀

Anthropic 공식 문서의 **서브에이전트(Subagents)** 방식으로 구성했다.
- 정의 파일: `.claude/agents/*.md` (YAML 프런트매터 + 시스템 프롬프트)
- 참고 문서: https://code.claude.com/docs/en/sub-agents · https://code.claude.com/docs/en/agent-teams
  · https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them

## 구성 (오케스트레이터-워커 + 검증 에이전트 패턴)

```
                 [리드 = 메인 Claude 세션]
                  │ 작업 분배·결과 취합
      ┌───────────┴────────────┐          ← 1단계: 서로 독립적이라 병렬 실행
[chartpro-researcher]   [wonyotti-researcher]
 차트프로 유튜브 조사     워뇨띠 자료 조사
      └───────────┬────────────┘
                  ▼                        ← 2단계
        [strategy-synthesizer]  → docs/STRATEGY.md 갱신
                  ▼                        ← 3단계
         [research-verifier]    → research/VERIFICATION.md (독립 팩트체크)
```

| 에이전트 | 역할 | 도구 | 산출물 |
|---|---|---|---|
| chartpro-researcher | 차트프로 강의 수집·기법 규칙화 | Bash(yt_api), 웹 검색 | `research/chartpro/REPORT.md` |
| wonyotti-researcher | 워뇨띠 자료 수집·신뢰도 평가 | Bash(yt_api), 웹 검색 | `research/wonyotti/REPORT.md` |
| strategy-synthesizer | 두 보고서 종합 → 전략 문서 갱신 | 파일 읽기·쓰기만 | `docs/STRATEGY.md` |
| research-verifier | 주장·출처 독립 검증 | 웹 검색, 읽기 | `research/VERIFICATION.md` |

### 설계 원칙 (공식 문서 기준)
- **맥락 기준 분할**: 서로 정보를 공유할 필요가 없는 조사만 병렬로 나눴다
- **단일 책임 + 최소 도구**: 종합 에이전트는 웹 접근 없이 보고서만 읽는다
- **자기완결적 지시 + 정해진 출력 형식**: 각 에이전트는 무엇을 어디에 쓸지 명시돼 있다
- **검증 에이전트 분리**: 작성자와 독립된 팩트체커가 마지막에 확인한다
- **Agent Teams(실험 기능)를 쓰지 않은 이유**: 이번 작업은 조사원끼리 토론할 필요가 없고, 서브에이전트가 토큰 비용이 더 적다

## 도구
- `tools/yt_api.py` — YouTube 내부 API로 채널 영상 목록, 설명란, 댓글, 검색, 자막을 가져온다
  - ⚠️ 현재 클라우드 환경의 네트워크 정책상 **자막 서버(www.youtube.com)와 영상 스트림(googlevideo.com)은 차단**되어 자막은 받지 못한다
  - 환경 설정에서 `www.youtube.com`을 허용하면 자막 기반 분석이 가능해진다
- `chartpro_videos.json` — 차트프로 채널 전체 영상 목록 (138개, 2026-09-29 기준)

---

## v1.0 기획 문서 세트 (2026-09-29)

두 번째 에이전트 팀(워크플로, 에이전트 26명)이 전체 기획을 조사·검토·작성했다.

```
[조사 8명 병렬] → [비판 3명: 트레이딩·보안·제품운영] → [판정 1명: 채택/기각, 공통 결정값]
   → [문서 작성 9명 병렬] → [일관성 검증 1명] → [문서별 수정 4명]
```

| 파일 | 내용 |
|---|---|
| `planning/01_existing_systems.md` | freqtrade 등 기존 봇·시그널 서비스·LLM 트레이딩 에이전트 사례, 자체 개발 vs 프레임워크 |
| `planning/02_chart_methods.md` | 다른 트레이더들의 차트 분석 방법 34가지와 근거 수준 |
| `planning/03_llm_trading.md` | LLM 트레이딩 실증(대회·연구), 실패 양상, Claude 설계 권고, 비용 |
| `planning/04_exchanges_regulation.md` | 거래소 보안·기능 비교, 한국 규제·세금 현황 |
| `planning/05_infra_ops.md` | 호스팅 후보, 서버 보안, 모니터링, 월 비용 |
| `planning/06_software_stack.md` | 라이브러리 버전·유지보수 상태, 백테스트 도구 |
| `planning/07_telegram_hitl.md` | 텔레그램 승인 버튼 보안, 가격 재검증, Slack 비교 |
| `planning/08_risk_backtest.md` | 포지션 크기, 주문 유형, 백테스트 함정, 실거래 전환 기준 |
| `market/CHART_METHODS.md` | 차트 분석 방법 정리(사용자용 읽기 자료) |
| `market/LANDSCAPE.md` | 비슷한 시스템·거래소·규제 지형도 |

설계 문서는 `docs/`에 있다. 읽는 순서는 [docs/README.md](../docs/README.md)를 본다.
