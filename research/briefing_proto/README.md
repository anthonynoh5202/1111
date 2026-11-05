# 세 관점 브리핑 프로토타입 (샘플)

차트프로·워뇨띠·Claude 종합, 세 관점으로 차트 위에 번호를 매겨 설명하는 형식을 미리 만들어 본 것이다.
**실서비스 코드가 아니다.** 형식이 정해지면 `bot/` 아래에 테스트와 함께 다시 만든다.

- `facts.py` — 분석 재료(기준봉·마디·허리·거래량·이평 비교봉·닮은꼴 검색)를 계산해 출력한다.
  - 닮은꼴 검색은 워뇨띠 기준서의 "닮은꼴 찾기" 절을 우리가 구현한 것이다.
- `sample_0929.json` — 차트 위 번호 표시 목록(marks). 나중에 Claude API가 이 모양으로 돌려준다.
- `render.py` — marks를 일봉·4시간봉 그림과 닮은꼴 그림으로 그린다.
- `brief_0929.md` — 2026-09-29 09:00 KST 기준 세 관점 설명 예시(과거 데이터). 기준서 `bot/prompts/playbook_*.md`의 규칙 번호를 인용한다.

실행(저장소 폴더에서, 결과는 저장소 밖 `~/brief_out`에 생김):

```
.venv/bin/python research/briefing_proto/facts.py ~/brief_out/similar.json
.venv/bin/python research/briefing_proto/render.py ~/brief_out
```
