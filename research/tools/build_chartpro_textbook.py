"""[대표님 맥에서 실행] 차트프로 초급 강의 교재(HTML)를 만든다 — 개인 학습용.

본문은 저장소의 영상 분석 노트(research/chartpro/analysis/*.md)에서, 장 구성은
research/chartpro/textbook/chapters.json에서 가져온다. 노트의 핵심 내용마다 붙은 시각 [mm:ss]에서
영상 화면을 한 장씩 캡처해 그 내용 바로 아래에 붙인다.

보안·저작권
- 결과물(HTML·캡처)은 저장소 밖(기본 ~/Documents/차트프로_교재)에만 만든다. 저장소 안 경로는 거부한다.
  저장소는 공개라서 캡처가 올라가면 안 된다.
- 영상은 캡처가 끝나면 바로 지운다. 개인 학습용으로만 쓰고 공유하지 않는다.

실행 (저장소 폴더에서, 보통은 make_chartpro_textbook_mac.sh가 대신 실행):
    python research/tools/build_chartpro_textbook.py               # 캡처 포함
    python research/tools/build_chartpro_textbook.py --no-video    # 캡처 없이 본문만(빠른 미리보기)
    python research/tools/build_chartpro_textbook.py --browser chrome   # 유튜브가 로그인을 요구할 때

다시 실행하면 이미 캡처한 영상은 건너뛴다.
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
NOTES_DIR = REPO / "research" / "chartpro" / "analysis"
CHAPTERS = REPO / "research" / "chartpro" / "textbook" / "chapters.json"
DEFAULT_OUT = pathlib.Path.home() / "Documents" / "차트프로_교재"

CAPTURE_DELAY_S = 3      # 말을 시작한 뒤 화면에 그림이 그려질 시간
MAX_SHOTS = 8            # 영상 하나당 최대 캡처 수
MIN_GAP_S = 10           # 이보다 가까운 시각은 같은 화면으로 보고 한 장만

TS_RE = re.compile(r"\[(\d{1,2}):(\d{2})\]")
HEAD_RE = re.compile(r"^### (.+?)\s*\(https://youtu\.be/([\w-]{11})\)\s*$")
SECTION_RE = re.compile(r"^- (핵심|규칙|용어|예시|봇 적용)\s*:?\s*(.*)$")
ITEM_RE = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s+(.*)$")
SECTION_TITLES = {"핵심": "핵심 내용", "규칙": "매매 규칙", "용어": "용어", "예시": "강의 예시",
                  "봇 적용": "봇·BTC 적용 메모"}


# ---------------------------------------------------------------------------
# 노트 읽기
# ---------------------------------------------------------------------------


def parse_notes() -> dict:
    """analysis/*.md → {영상ID: {"title", "sections": [(이름, 머리글, [(깊이, 문장)])]}}"""
    lessons: dict = {}
    for md in sorted(NOTES_DIR.glob("*.md")):
        cur = None
        sec = None
        for raw in md.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip()
            m = HEAD_RE.match(line)
            if m:
                cur = {"title": m.group(1), "sections": []}
                lessons.setdefault(m.group(2), cur)
                sec = None
                continue
            if line.startswith("## ") or line.startswith("### ") or line == "---":
                cur = sec = None
                continue
            if cur is None or not line.strip():
                continue
            s = SECTION_RE.match(line)
            if s:
                sec = (s.group(1), s.group(2).strip(), [])
                cur["sections"].append(sec)
                continue
            if sec is None:
                continue
            it = ITEM_RE.match(line)
            if it and len(it.group(1)) >= 1:
                sec[2].append((max(0, len(it.group(1)) // 2 - 1), it.group(2).strip()))
            elif sec[2]:                                  # 줄바꿈된 이어지는 문장
                depth, text = sec[2][-1]
                sec[2][-1] = (depth, text + " " + line.strip())
    return lessons


def first_ts(text: str) -> int | None:
    m = TS_RE.search(text)
    return None if m is None else int(m.group(1)) * 60 + int(m.group(2))


def capture_points(lesson: dict) -> list:
    """캡처할 시각(초): 핵심의 맨 위 항목마다 첫 시각 + 예시의 첫 시각. 가까운 것은 합친다."""
    picks = []
    for name, head, items in lesson["sections"]:
        if name == "핵심":
            picks += [first_ts(t) for d, t in items if d == 0]
        elif name == "예시":
            picks.append(first_ts(head + " " + " ".join(t for _, t in items)))
    out: list = []
    for t in picks:
        if t is not None and all(abs(t - u) >= MIN_GAP_S for u in out):
            out.append(t)
    return out[:MAX_SHOTS]


# ---------------------------------------------------------------------------
# 캡처 (yt-dlp로 영상 받기 → ffmpeg로 한 장씩 → 영상 삭제)
# ---------------------------------------------------------------------------


def shot_name(vid: str, sec: int) -> str:
    return f"{vid}_{sec:04d}.jpg"


def capture_video(vid: str, seconds: list, img_dir: pathlib.Path, tmp_dir: pathlib.Path,
                  browser: str | None) -> tuple:
    """(성공 장수, 실패 사유 또는 None). 이미 있는 캡처는 건너뛴다."""
    todo = [s for s in seconds if not (img_dir / shot_name(vid, s)).exists()]
    if not todo:
        return len(seconds), None
    import imageio_ffmpeg
    import yt_dlp

    tmp_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bv*[height<=720][ext=mp4]/bv*[height<=720]/b[height<=720]/b",
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
    }
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://youtu.be/{vid}", download=True)
            path = pathlib.Path(ydl.prepare_filename(info))
        duration = int(info.get("duration") or 0)
    except Exception as exc:  # noqa: BLE001 — 한 영상 실패는 건너뛰고 계속
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return 0, f"영상 받기 실패: {type(exc).__name__}: {str(exc)[:160]}"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    ok = len(seconds) - len(todo)
    try:
        for s in todo:
            at = s + CAPTURE_DELAY_S
            if duration:
                at = min(at, max(0, duration - 1))
            out = img_dir / shot_name(vid, s)
            r = subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-ss", str(at), "-i", str(path),
                                "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(out)],
                               capture_output=True, timeout=120)
            if r.returncode == 0 and out.exists():
                ok += 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)     # 영상은 남기지 않는다
    return ok, None if ok == len(seconds) else "일부 캡처 실패"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def inline(text: str, vid: str) -> str:
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = t.replace("[추정]", '<span class="guess" title="자동 자막 오타를 문맥으로 고친 말">[추정]</span>')

    def link(m):
        sec = int(m.group(1)) * 60 + int(m.group(2))
        return (f'<a class="ts" href="https://youtu.be/{vid}?t={sec}" target="_blank" rel="noopener">'
                f'{m.group(1)}:{m.group(2)}</a>')

    return TS_RE.sub(link, t)


def figure(vid: str, sec: int, img_dir: pathlib.Path) -> str:
    name = shot_name(vid, sec)
    label = f"{sec // 60:02d}:{sec % 60:02d}"
    url = f"https://youtu.be/{vid}?t={sec}"
    if (img_dir / name).exists():
        return (f'<figure><a href="{url}" target="_blank" rel="noopener"><img loading="lazy" src="img/{name}" '
                f'alt="강의 화면 {label}"></a><figcaption>▶ 영상 {label} 화면 (누르면 그 시각부터 재생)</figcaption></figure>')
    return f'<p class="noshot"><a href="{url}" target="_blank" rel="noopener">▶ 영상 {label} 에서 화면 보기</a></p>'


def render_items(items: list, vid: str, shots: set, img_dir: pathlib.Path, with_fig: bool) -> str:
    out, depth = [], -1
    for d, text in items:
        while depth < d:
            out.append("<ul>")
            depth += 1
        while depth > d:
            out.append("</li></ul>")
            depth -= 1
        if out and out[-1] not in ("<ul>",):
            out.append("</li>")
        out.append(f"<li>{inline(text, vid)}")
        t = first_ts(text)
        if with_fig and d == 0 and t in shots:
            out.append(figure(vid, t, img_dir))
            shots.discard(t)
    while depth >= 0:
        out.append("</li></ul>")
        depth -= 1
    return "".join(out)


def render_lesson(vid: str, lesson: dict, img_dir: pathlib.Path, num: str) -> str:
    shots = set(capture_points(lesson))
    parts = [f'<section class="lesson" id="v-{vid}"><h3><span class="num">{num}</span> {html.escape(lesson["title"])}</h3>',
             f'<p class="src"><a href="https://youtu.be/{vid}" target="_blank" rel="noopener">원본 강의 보기 ↗</a></p>']
    for name, head, items in lesson["sections"]:
        parts.append(f'<div class="sec sec-{"bot" if name == "봇 적용" else name}"><h4>{SECTION_TITLES[name]}</h4>')
        if head:
            parts.append(f"<p>{inline(head, vid)}</p>")
        parts.append(render_items(items, vid, shots, img_dir, with_fig=(name == "핵심")))
        if name == "예시":
            for t in sorted(shots):
                parts.append(figure(vid, t, img_dir))
            shots.clear()
        parts.append("</div>")
    parts.append("</section>")
    return "".join(parts)


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e1db;--card:#fff;--accent:#c2410c;--soft:#fff4ec;--note:#eef4ff}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#ececec;--muted:#a0a0a6;--line:#2c2c2e;--card:#1f1f21;--accent:#fb923c;--soft:#2a1d14;--note:#17202e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Noto Sans KR",sans-serif;word-break:keep-all}
main{max-width:860px;margin:0 auto;padding:32px 16px 80px}
header.cover{padding:48px 0 24px;border-bottom:2px solid var(--fg);margin-bottom:24px}
header.cover h1{font-size:34px;margin:0 0 6px;letter-spacing:-.02em}
header.cover p{margin:4px 0;color:var(--muted)}
.warn{background:var(--soft);border-left:4px solid var(--accent);padding:10px 14px;border-radius:6px;font-size:14px}
nav.toc ol{padding-left:20px}nav.toc li{margin:2px 0}nav.toc a{color:inherit}
nav.toc ul{padding-left:18px;font-size:14px;color:var(--muted)}
h2.chapter{font-size:26px;margin:64px 0 8px;padding-top:16px;border-top:1px solid var(--line);letter-spacing:-.01em}
.intro{font-size:17px}
.btc{background:var(--note);padding:10px 14px;border-radius:6px;font-size:14px}
.lesson{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin:24px 0}
.lesson h3{margin:0 0 4px;font-size:20px;line-height:1.4}
.num{display:inline-block;min-width:2.2em;color:var(--accent);font-variant-numeric:tabular-nums}
.src{margin:0 0 8px;font-size:13px}.src a{color:var(--muted)}
h4{margin:18px 0 6px;font-size:15px;color:var(--accent)}
.sec-bot{border-top:1px dashed var(--line);margin-top:14px;font-size:14px;color:var(--muted)}
.sec-bot h4{color:var(--muted)}
ul{padding-left:20px;margin:4px 0}li{margin:4px 0}
a.ts{font-size:12px;color:var(--muted);text-decoration:none;border:1px solid var(--line);border-radius:4px;padding:0 4px;margin:0 2px;white-space:nowrap}
.guess{font-size:12px;color:var(--muted)}
figure{margin:10px 0 16px}figure img{width:100%;height:auto;border-radius:8px;border:1px solid var(--line);display:block}
figcaption{font-size:12px;color:var(--muted);margin-top:4px}
.noshot a{font-size:13px;color:var(--muted)}
.review{background:var(--soft);border-radius:10px;padding:14px 18px;margin:20px 0}
.review h4{margin-top:0}
footer{margin-top:64px;font-size:13px;color:var(--muted);border-top:1px solid var(--line);padding-top:16px}
@media print{body{background:#fff;color:#000;font-size:12pt}a.ts{border:none}.lesson{break-inside:auto;border:none;padding:0}
 h2.chapter{break-before:page;border:none}figure{break-inside:avoid}nav.toc{break-after:page}}
"""


def build_html(cfg: dict, lessons: dict, img_dir: pathlib.Path) -> tuple:
    toc, body, missing = [], [], []
    n = 0
    for ci, ch in enumerate(cfg["chapters"], 1):
        cid = f"ch{ci}"
        sub = []
        chunk = [f'<h2 class="chapter" id="{cid}">{html.escape(ch["title"])}</h2>',
                 f'<p class="intro">{html.escape(ch["intro"])}</p>',
                 f'<p class="btc"><strong>BTC에 쓸 때</strong> — {html.escape(ch["btc_note"])}</p>']
        for vid in ch["videos"]:
            if vid not in lessons:
                missing.append(vid)
                continue
            n += 1
            chunk.append(render_lesson(vid, lessons[vid], img_dir, f"{n:02d}"))
            sub.append(f'<li><a href="#v-{vid}">{html.escape(lessons[vid]["title"])}</a></li>')
        if ch.get("review"):
            qs = "".join(f"<li>{html.escape(q)}</li>" for q in ch["review"])
            chunk.append(f'<div class="review"><h4>복습 질문</h4><ol>{qs}</ol></div>')
        body.append("".join(chunk))
        toc.append(f'<li><a href="#{cid}">{html.escape(ch["title"])}</a><ul>{"".join(sub)}</ul></li>')
    today = time.strftime("%Y-%m-%d")
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>{html.escape(cfg["title"])}</title><style>{CSS}</style></head><body><main>
<header class="cover"><h1>{html.escape(cfg["title"])}</h1><p>{html.escape(cfg["subtitle"])}</p><p>만든 날 {today} · 강의 {n}편</p></header>
<p class="warn">개인 학습용입니다. 강의와 화면의 저작권은 차트프로(@chart_pro)에 있습니다. 공유·게시하지 마세요.
본문은 자동 자막을 바탕으로 정리한 노트라 오타를 고친 곳은 <span class="guess">[추정]</span>으로 표시했습니다.
시각 버튼을 누르면 원본 영상의 그 장면부터 재생됩니다.</p>
<nav class="toc"><h2>차례</h2><ol>{"".join(toc)}</ol></nav>
{"".join(body)}
<footer>PDF로 저장: 이 페이지에서 ⌘P → 왼쪽 아래 'PDF' → 'PDF로 저장'.</footer>
</main></body></html>"""
    return page, n, missing


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="차트프로 초급 교재 만들기(개인 학습용)")
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help="결과 폴더(저장소 밖)")
    ap.add_argument("--no-video", action="store_true", help="캡처 없이 본문만 만든다")
    ap.add_argument("--browser", choices=["chrome", "safari", "firefox", "edge", "brave"],
                    help="유튜브가 로그인을 요구할 때 그 브라우저의 로그인 상태를 빌려 쓴다")
    ap.add_argument("--only", nargs="*", help="이 영상 ID만 캡처(시험용)")
    args = ap.parse_args()

    out = args.out.expanduser().resolve()
    if out == REPO or REPO in out.parents:
        print(f"거부: 결과 폴더가 저장소 안입니다({out}). 저장소는 공개라 캡처를 두면 안 됩니다.")
        return 2
    img_dir = out / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    cfg = json.loads(CHAPTERS.read_text(encoding="utf-8"))
    lessons = parse_notes()
    vids = [v for ch in cfg["chapters"] for v in ch["videos"] if v in lessons]

    failed = []
    if not args.no_video:
        targets = [v for v in vids if not args.only or v in args.only]
        for i, vid in enumerate(targets, 1):
            secs = capture_points(lessons[vid])
            ok, err = capture_video(vid, secs, img_dir, out / ".tmp", args.browser)
            print(f"[{i}/{len(targets)}] {lessons[vid]['title'][:40]} — 캡처 {ok}/{len(secs)}"
                  + (f"  ({err})" if err else ""), flush=True)
            if err:
                failed.append(vid)
            time.sleep(1)

    page, n, missing = build_html(cfg, lessons, img_dir)
    (out / "index.html").write_text(page, encoding="utf-8")
    shots = len(list(img_dir.glob("*.jpg")))
    print(f"\n완료: {out / 'index.html'}  (강의 {n}편, 캡처 {shots}장)")
    if missing:
        print("노트에 없는 영상:", ", ".join(missing))
    if failed:
        print(f"캡처가 덜 된 영상 {len(failed)}개 — 다시 실행하면 빠진 것만 이어서 받습니다.")
        print("계속 실패하면 크롬에 유튜브 로그인 후: --browser chrome 을 붙여 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
