# 수집 로그 (2026-09-29)

## 자막(transcript)
- 사전 테스트: 실패 (HTTP 400 Precondition check failed) — 호출자 보고
- 재시도 3건: B-8-CXFhLK4, kHMp_Qu09MY, 0pUv5LR4Mfk → 모두 HTTP 400 Bad Request
- www.youtube.com / googlevideo.com 은 조직 정책 차단 → 우회하지 않음
- 결론: 자막 0/138

## details (설명란 + 인기 댓글 첫 페이지, 최대 20개)
- 138/138 성공 (1건은 1차 실패 후 재시도 성공), 댓글 합계 2,586개
- 파일: raw/details/<videoId>.json
- 설명란은 대부분 공통 보일러플레이트(카페·재생목록 링크) + 해시태그. 최근 영상 설명란은 유료 신호 서비스 홍보(기법 아님, 제외)

## 웹 검색 (WebSearch 7회, WebFetch 4회)
- "차트프로 밥그릇 패턴 기준봉 정리", "차트프로 세력가 기준가 찾는법 …", "차트프로 AF 패턴 기법",
  "\"차트프로\" 강의 요약 기준마디 허리 blog", "\"차트프로\" 유튜브 초급 차트편 정리 눌림목 돌파매매",
  "차트프로 밥그릇 기법 급소 9군데 요약", "차트프로 원웨이 패턴 기준마디 트랩"
- 결과: 차트프로 강의를 직접 요약한 글은 찾지 못함. 일반 기준봉/밥그릇 설명 글만 검색됨(차트프로 출처 아님 → 보고서 규칙 근거로 쓰지 않음)
- WebFetch: tv.naver.com (도구 차단), youtubecategory.com (DNS 실패), haesun247.com (EGRESS_BLOCKED), kr.tradingview.com (EGRESS_BLOCKED) → 모두 건너뜀
