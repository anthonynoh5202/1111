"""채널 전체 영상의 자막을 research/chartpro/transcripts/<id>.txt 로 저장한다. 이미 받은 파일은 건너뛴다."""
import json
import pathlib
import sys
import time

import yt_api

ROOT = pathlib.Path(__file__).resolve().parents[1]
videos = json.loads((ROOT / "chartpro_videos.json").read_text())
out = ROOT / "chartpro" / "transcripts"
out.mkdir(parents=True, exist_ok=True)

ok = fail = skip = 0
for v in videos:
    path = out / f"{v['id']}.txt"
    if path.exists():
        skip += 1
        continue
    try:
        text = yt_api.transcript(v["id"])
    except Exception as e:  # 네트워크 차단 등
        print(f"FAIL {v['id']} {e}", file=sys.stderr)
        fail += 1
        continue
    if not text:
        print(f"NONE {v['id']} {v['title']}", file=sys.stderr)
        fail += 1
        continue
    path.write_text(f"# {v['title']}\n# https://youtu.be/{v['id']}\n\n{text}\n")
    ok += 1
    time.sleep(0.5)

print(f"저장 {ok} · 건너뜀 {skip} · 실패 {fail} / 전체 {len(videos)}")
