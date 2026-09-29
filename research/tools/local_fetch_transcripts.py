"""[대표님 PC에서 실행] 차트프로 전체 영상 자막을 내려받는다.

클라우드 서버에서는 YouTube가 봇으로 차단하므로, 가정용 인터넷이 연결된 PC에서 실행한다.

준비 (한 번만):
    pip install youtube-transcript-api

실행 (저장소 폴더에서):
    python research/tools/local_fetch_transcripts.py

결과: research/chartpro/transcripts/<영상ID>.txt (이미 받은 파일은 건너뜀)
"""
import json
import pathlib
import time

from youtube_transcript_api import YouTubeTranscriptApi

ROOT = pathlib.Path(__file__).resolve().parents[1]
videos = json.loads((ROOT / "chartpro_videos.json").read_text(encoding="utf-8"))
out = ROOT / "chartpro" / "transcripts"
out.mkdir(parents=True, exist_ok=True)

api = YouTubeTranscriptApi()
ok = skip = fail = 0
for i, v in enumerate(videos, 1):
    path = out / f"{v['id']}.txt"
    if path.exists():
        skip += 1
        continue
    try:
        fetched = api.fetch(v["id"], languages=["ko"])
    except Exception as e:
        print(f"[{i}/{len(videos)}] 실패 {v['id']} {type(e).__name__}")
        fail += 1
        continue
    lines = [f"[{int(s.start) // 60:02d}:{int(s.start) % 60:02d}] {s.text}" for s in fetched]
    path.write_text(f"# {v['title']}\n# https://youtu.be/{v['id']}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    ok += 1
    print(f"[{i}/{len(videos)}] 저장 {v['title'][:40]}")
    time.sleep(1)  # 너무 빠르게 요청하면 차단될 수 있다

print(f"\n완료: 저장 {ok} · 건너뜀 {skip} · 실패 {fail} / 전체 {len(videos)}")
