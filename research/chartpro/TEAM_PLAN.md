# 차트프로 전체 영상 분석 — 에이전트 팀 계획

## 병목
영상 내용은 자막에 있다. 이 클라우드 환경에서는 두 가지로 막혀 있다.
1. 조직 네트워크 정책: `www.youtube.com`(자막 파일), `*.googlevideo.com`(영상 스트림) 차단
2. YouTube 봇 차단: 클라우드 서버 IP는 "로그인하여 봇이 아님을 확인하세요"(LOGIN_REQUIRED)로 거부

→ 자막은 **가정용 인터넷 PC**에서 `research/tools/local_fetch_transcripts.py`로 받아 저장소에 올린다.

## 팀 구성 (자막 확보 후 실행, 총 9개 에이전트)

| 단계 | 에이전트 | 담당 | 영상 수 |
|---|---|---|---|
| 1 병렬 | video-analyst A | 초급-차트편 #1~#20 | 약 20 |
| 1 병렬 | video-analyst B | 초급-차트편 #21~#39 | 약 20 |
| 1 병렬 | video-analyst C | 중급-차트편 전체 | 22 |
| 1 병렬 | video-analyst D | 초급·중급 심리편 + 시나리오 매매 | 22 |
| 1 병렬 | video-analyst E | 실전매매 리뷰 | 21 |
| 1 병렬 | video-analyst F | 해외선물 시리즈 + 기타 | 33 |
| 2 | chartpro-researcher (종합) | A~F 결과 → `research/chartpro/REPORT.md` v2 | — |
| 3 | strategy-synthesizer | 보고서 → `docs/STRATEGY.md` 갱신 | — |
| 4 | research-verifier | 자막 원문 대조 검증 → `research/VERIFICATION.md` | — |

- 분석가는 자막 파일만 읽는다(최소 도구: Read/Glob/Grep). 서로 겹치지 않는 묶음을 받아 병렬로 돈다
- 결과는 리드가 받아 `research/chartpro/analysis/<묶음>.md`로 저장한다
