"""[대표님 맥에서 실행] 차트프로 초급 강의 교재를 만든다 — 개인 학습용.

결과물 (모두 저장소 밖, 기본 ~/Documents/차트프로_교재/)
- 차트프로_초급_교재.pdf   ← 읽기·인쇄용 (주 결과물)
- 차트프로_초급_교재.docx  ← 워드에서 고쳐 쓰기용
- index.html + img/*.jpg  ← 위 두 파일을 만드는 중간 결과(브라우저로도 볼 수 있음)

본문은 저장소의 영상 분석 노트(research/chartpro/analysis/*.md)와 보강 노트
(research/chartpro/textbook/supplements/<영상ID>.md, 없어도 됨)에서, 장 구성은
research/chartpro/textbook/chapters.json에서 가져온다. 노트의 핵심 내용마다 붙은 시각 [mm:ss]에서
영상 화면을 한 장씩 캡처해 그 내용 바로 아래에 붙인다.

보안·저작권
- 결과물은 저장소 밖에만 만든다. 저장소 안 경로는 거부한다(저장소는 공개라 캡처가 올라가면 안 된다).
- 영상은 캡처가 끝나면 바로 지운다. 개인 학습용으로만 쓰고 공유하지 않는다.

실행 (저장소 폴더에서, 보통은 make_chartpro_textbook_mac.sh가 대신 실행):
    python research/tools/build_chartpro_textbook.py               # 캡처 + HTML + DOCX + PDF
    python research/tools/build_chartpro_textbook.py --no-video    # 캡처 없이(이미 있는 캡처만 써서) 빠르게
    python research/tools/build_chartpro_textbook.py --browser chrome   # 유튜브가 로그인을 요구할 때
    python research/tools/build_chartpro_textbook.py --recapture   # 영상 첫 8초 안에서 찍힌 옛 캡처를 다시 찍기

다시 실행하면 이미 있는 캡처는 건너뛰고, 새로 필요한 캡처가 있는 영상만 받는다.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
NOTES_DIR = REPO / "research" / "chartpro" / "analysis"
CHAPTERS = REPO / "research" / "chartpro" / "textbook" / "chapters.json"
SUPPLEMENTS_DIR = REPO / "research" / "chartpro" / "textbook" / "supplements"
TYPO_NOTE = NOTES_DIR / "01.md"
DEFAULT_OUT = pathlib.Path.home() / "Documents" / "차트프로_교재"
DOCX_NAME = "차트프로_초급_교재.docx"
PDF_NAME = "차트프로_초급_교재.pdf"
MANIFEST_NAME = "captures.json"   # 캡처 시각·중복 판정 기록 (결과 폴더 안)

CAPTURE_DELAY_S = 3      # 말을 시작한 뒤 화면에 그림이 그려질 시간
MIN_CAPTURE_S = 8        # 영상 첫 부분(제목·인트로)은 찍지 않는다
MAX_SHOTS = 12           # 영상 하나당 최대 캡처 수
MIN_GAP_S = 10           # 이보다 가까운 시각은 같은 화면으로 보고 한 장만
SIG_W, SIG_H = 32, 18    # 중복 판정용 축소 크기(흑백)
DUP_MAD = 2.0            # 축소 화면의 평균 밝기 차이(0~255)가 이보다 작으면 같은 화면

TS_RE = re.compile(r"\[(\d{1,2}):(\d{2})\]")
HEAD_RE = re.compile(r"^### (.+?)\s*\(https://youtu\.be/([\w-]{11})\)\s*$")
NOTE_SEC_RE = re.compile(r"^- (핵심|규칙|용어|예시|봇 적용|기타)(?:\([^)]*\))?\s*(?::\s*(.*))?$")
SUP_SEC_RE = re.compile(r"^- (빠진 내용|보강 설명|바로잡기)\s*(?::\s*(.*))?$")
ITEM_RE = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s+(.*)$")
INLINE_RE = re.compile(r"\*\*(.+?)\*\*|\[(\d{1,2}):(\d{2})\]|(\[추정(?::[^\]]*)?\])")
SECTION_TITLES = {"핵심": "핵심 내용", "규칙": "매매 규칙", "용어": "용어", "예시": "강의 예시",
                  "봇 적용": "봇·BTC 적용 메모", "기타": "덧붙임",
                  "빠진 내용": "추가 내용(자막 대조)", "보강 설명": "보강 설명", "바로잡기": "바로잡기"}
FIG_SECTIONS = ("핵심", "빠진 내용")   # 맨 위 항목 아래에 캡처를 붙이는 부분


# ---------------------------------------------------------------------------
# 노트 읽기
# ---------------------------------------------------------------------------


def parse_sections(lines: list, sec_re: re.Pattern) -> list:
    """'- 이름: 머리글' + 들여쓴 항목 → [(이름, 머리글, [(깊이, 문장)])]. 모르는 '- 이름:' 줄은 구역을 끝낸다."""
    sections: list = []
    sec = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        s = sec_re.match(line)
        if s:
            sec = (s.group(1), (s.group(2) or "").strip(), [])
            sections.append(sec)
            continue
        if line.startswith("- "):          # 들여쓰기 없는 다른 항목(예: '- 참고:') → 구역 끝
            sec = None
            continue
        if sec is None:
            continue
        it = ITEM_RE.match(line)
        if it and len(it.group(1)) >= 1:
            sec[2].append((max(0, len(it.group(1)) // 2 - 1), it.group(2).strip()))
        elif sec[2]:                                  # 줄바꿈된 이어지는 문장
            depth, text = sec[2][-1]
            sec[2][-1] = (depth, text + " " + line.strip())
    return sections


def parse_notes() -> dict:
    """analysis/*.md → {영상ID: {"title", "sections": [...], "sup": {}}}"""
    lessons: dict = {}
    for md in sorted(NOTES_DIR.glob("*.md")):
        vid, title, buf = None, None, []

        def flush():
            if vid and vid not in lessons:
                lessons[vid] = {"title": title, "sections": parse_sections(buf, NOTE_SEC_RE), "sup": {}}

        for raw in md.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip()
            m = HEAD_RE.match(line)
            if m or line.startswith("## ") or line.startswith("### ") or line == "---":
                flush()
                vid, title, buf = (m.group(2), m.group(1), []) if m else (None, None, [])
                continue
            if vid:
                buf.append(line)
        flush()
    return lessons


def load_supplements(lessons: dict, sup_dir: pathlib.Path) -> int:
    """supplements/<영상ID>.md를 읽어 lessons[vid]["sup"]에 넣는다. 읽은 파일 수를 돌려준다."""
    n = 0
    if not sup_dir.is_dir():
        return 0
    for md in sorted(sup_dir.glob("*.md")):
        vid = md.stem
        if vid not in lessons:
            continue
        secs = parse_sections(md.read_text(encoding="utf-8").splitlines(), SUP_SEC_RE)
        sup = {}
        for name, head, items in secs:
            if name in sup:
                sup[name] = (sup[name][0], sup[name][1] + items)
            else:
                sup[name] = (head, items)
        lessons[vid]["sup"] = sup
        n += 1
    return n


def parse_typos() -> list:
    """01.md의 '자주 나오는 자동 자막 오타' 표 → [(자막 표기, 바로잡은 말)]. 모양이 다르면 빈 목록."""
    try:
        lines = TYPO_NOTE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows, on = [], False
    for line in lines:
        if line.startswith("### ") and "자막 오타" in line:
            on = True
            continue
        if not on:
            continue
        s = line.strip()
        if not s.startswith("|"):
            if rows or s.startswith("#") or s == "---":
                break
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) != 2 or set(cells[0]) <= set("-: "):
            continue
        if cells[0] == "자막 표기":
            continue
        rows.append((cells[0], cells[1]))
    return rows


def first_ts(text: str) -> int | None:
    m = TS_RE.search(text)
    return None if m is None else int(m.group(1)) * 60 + int(m.group(2))


def capture_points(lesson: dict) -> list:
    """캡처할 시각(초): 핵심의 맨 위 항목마다 첫 시각 + 예시의 첫 시각 + 보강 노트 '빠진 내용' 맨 위 항목.
    가까운 것은 합친다. 기존 노트 시각이 먼저 들어가므로 예전 캡처는 그대로 쓰인다."""
    picks = []
    for name, head, items in lesson["sections"]:
        if name == "핵심":
            picks += [first_ts(t) for d, t in items if d == 0]
        elif name == "예시":
            picks.append(first_ts(head + " " + " ".join(t for _, t in items)))
    if "빠진 내용" in lesson.get("sup", {}):
        picks += [first_ts(t) for d, t in lesson["sup"]["빠진 내용"][1] if d == 0]
    out: list = []
    for t in picks:
        if t is not None and all(abs(t - u) >= MIN_GAP_S for u in out):
            out.append(t)
    return out[:MAX_SHOTS]


def merged_sections(lesson: dict) -> list:
    """노트 구역 + 보강 구역을 읽기 좋은 순서로 합친다."""
    secs = list(lesson["sections"])
    sup = lesson.get("sup", {})
    extra = [(n, *sup[n]) for n in ("빠진 내용", "보강 설명") if n in sup]
    if extra:
        idx = [i for i, s in enumerate(secs) if s[0] in ("핵심", "규칙")]
        at = idx[-1] + 1 if idx else 0
        secs[at:at] = extra
    if "바로잡기" in sup:
        idx = [i for i, s in enumerate(secs) if s[0] == "봇 적용"]
        secs.insert(idx[0] if idx else len(secs), ("바로잡기", *sup["바로잡기"]))
    return secs


# ---------------------------------------------------------------------------
# 캡처 (yt-dlp로 영상 받기 → ffmpeg로 한 장씩 → 영상 삭제) + 같은 화면 걸러내기
# ---------------------------------------------------------------------------


def shot_name(vid: str, sec: int) -> str:
    """파일 이름은 노트의 시각으로 정한다(실제로 찍은 시각이 바뀌어도 예전 파일이 그대로 맞는다)."""
    return f"{vid}_{sec:04d}.jpg"


def capture_second(sec: int, duration: int = 0) -> int:
    at = max(sec + CAPTURE_DELAY_S, MIN_CAPTURE_S)
    if duration:
        at = min(at, max(0, duration - 1))
    return at


def load_manifest(out: pathlib.Path) -> dict:
    try:
        data = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_manifest(out: pathlib.Path, manifest: dict) -> None:
    tmp = out / (MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, out / MANIFEST_NAME)


def needs_recapture(sec: int, entry: dict, mode: str | None) -> bool:
    if mode == "all":
        return True
    if mode == "early":   # 예전 방식(시각+3초)으로 영상 첫 8초 안에서 찍힌 것만
        return sec + CAPTURE_DELAY_S < MIN_CAPTURE_S and entry.get("at", {}).get(str(sec), 0) < MIN_CAPTURE_S
    return False


def capture_video(vid: str, seconds: list, img_dir: pathlib.Path, tmp_dir: pathlib.Path,
                  browser: str | None, redo: set, entry: dict) -> tuple:
    """(성공 장수, 실패 사유 또는 None). 이미 있는 캡처는 건너뛴다(redo에 든 것은 다시 찍는다)."""
    todo = [s for s in seconds if s in redo or not (img_dir / shot_name(vid, s)).exists()]
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
        return len(seconds) - len(todo), f"영상 받기 실패: {type(exc).__name__}: {str(exc)[:160]}"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    ok = len(seconds) - len(todo)
    at_map = entry.setdefault("at", {})
    try:
        for s in todo:
            at = capture_second(s, duration)
            out = img_dir / shot_name(vid, s)
            part = tmp_dir / ("new_" + out.name)
            r = subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-ss", str(at), "-i", str(path),
                                "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(part)],
                               capture_output=True, timeout=120)
            if r.returncode == 0 and part.exists() and part.stat().st_size > 0:
                os.replace(part, out)          # 새 캡처가 성공했을 때만 예전 파일을 바꾼다
                at_map[str(s)] = at
                entry.get("sig", {}).pop(str(s), None)
                ok += 1
            elif out.exists():
                ok += 1                        # 다시 찍기 실패 → 예전 캡처를 그대로 쓴다
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)     # 영상은 남기지 않는다
    return ok, None if ok == len(seconds) else "일부 캡처 실패"


def image_signature(ffmpeg: str, path: pathlib.Path) -> bytes | None:
    try:
        r = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(path), "-vf",
                            f"scale={SIG_W}:{SIG_H}:flags=area,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 and len(r.stdout) == SIG_W * SIG_H else None


def mean_abs_diff(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def mark_duplicates(vid: str, seconds: list, img_dir: pathlib.Path, entry: dict, ffmpeg: str) -> list:
    """한 영상 안에서 앞 캡처와 거의 같은 화면을 찾아 entry["dup"]에 적는다(파일은 지우지 않는다)."""
    sigs = entry.setdefault("sig", {})
    kept, dups = [], []
    for s in seconds:
        p = img_dir / shot_name(vid, s)
        if not p.exists():
            continue
        key = str(s)
        mtime = int(p.stat().st_mtime)
        cached = sigs.get(key)
        if not cached or cached.get("mtime") != mtime:
            raw = image_signature(ffmpeg, p)
            if raw is None:
                continue
            cached = sigs[key] = {"mtime": mtime, "hex": raw.hex()}
        raw = bytes.fromhex(cached["hex"])
        if any(mean_abs_diff(raw, k) < DUP_MAD for k in kept):
            dups.append(s)
        else:
            kept.append(raw)
    entry["dup"] = dups
    return dups


# ---------------------------------------------------------------------------
# 문서 모델 (HTML과 DOCX가 같은 내용을 쓰도록 한 번만 만든다)
# ---------------------------------------------------------------------------
# 글 조각(run): ("text"|"bold"|"guess", 글) 또는 ("ts", "mm:ss", url) 또는 ("link", 글, url) 또는 ("anchor", 글, id)


def runs(text: str, vid: str | None) -> list:
    out, pos = [], 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append(("text", text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(("bold", m.group(1)))
        elif m.group(2) is not None:
            label = f"{m.group(2)}:{m.group(3)}"
            if vid:
                sec = int(m.group(2)) * 60 + int(m.group(3))
                out.append(("ts", label, f"https://youtu.be/{vid}?t={sec}"))
            else:
                out.append(("text", f"[{label}]"))
        else:
            out.append(("guess", m.group(4)))
        pos = m.end()
    if pos < len(text):
        out.append(("text", text[pos:]))
    return out


def mmss(sec: int) -> str:
    return f"{sec // 60:02d}:{sec % 60:02d}"


def parse_mmss(t) -> int | None:
    try:
        parts = [int(x) for x in str(t).strip().split(":")]
    except ValueError:
        return None
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec if parts else None


def jpeg_size(path: pathlib.Path) -> tuple | None:
    """JPEG 머리에서 (가로, 세로)를 읽는다. 표준 라이브러리만 쓴다."""
    try:
        d = path.read_bytes()
    except OSError:
        return None
    i = 2
    while i + 9 < len(d):
        if d[i] != 0xFF:
            return None
        m = d[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        seg = int.from_bytes(d[i + 2:i + 4], "big")
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(d[i + 7:i + 9], "big"), int.from_bytes(d[i + 5:i + 7], "big")
        i += 2 + seg
    return None


def figure_block(vid: str, sec: int, img_dir: pathlib.Path, dups: set) -> dict:
    name = shot_name(vid, sec)
    path = img_dir / name
    fig = {"t": "figure", "label": mmss(sec), "url": f"https://youtu.be/{vid}?t={sec}", "img": None, "note": ""}
    if sec in dups:
        fig["note"] = "앞 화면과 같아 생략"
    elif path.exists():
        fig["img"] = path
        fig["rel"] = f"img/{name}"
        fig["size"] = jpeg_size(path)
    return fig


HANGUL_INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
SIMPLE_INITIAL = {"ㄲ": "ㄱ", "ㄸ": "ㄷ", "ㅃ": "ㅂ", "ㅆ": "ㅅ", "ㅉ": "ㅈ"}


def term_key(term: str) -> str:
    term = re.sub(r"\[추정[^\]]*\]", "", term)
    return re.sub(r"[\s*\"'“”‘’()（）\[\]]", "", term).lower()


def term_initial(term: str) -> str:
    for ch in term:
        if "가" <= ch <= "힣":
            ini = HANGUL_INITIALS[(ord(ch) - 0xAC00) // 588]
            return SIMPLE_INITIAL.get(ini, ini)
        if ch.isalnum():
            return "A–Z·숫자"
    return "A–Z·숫자"


def split_term(text: str) -> tuple | None:
    """'용어 = 뜻 [mm:ss]' 또는 '용어: 뜻' → (용어, 뜻). 형식이 아니면 None."""
    for sep in (" = ", ": "):
        if sep in text:
            term, rest = text.split(sep, 1)
            term = TS_RE.sub("", term).replace("**", "").strip()
            if 0 < len(term) <= 30 and rest.strip():
                return term, rest.strip()
    return None


def build_glossary(cfg: dict, lessons: dict, nums: dict) -> list:
    entries: dict = {}
    for ch in cfg["chapters"]:
        for vid in ch["videos"]:
            if vid not in lessons:
                continue
            for name, head, items in lessons[vid]["sections"]:
                if name != "용어":
                    continue
                for d, t in items:
                    sp = split_term(t) if d == 0 else None
                    if not sp:
                        continue
                    key = term_key(sp[0])
                    if key in entries:
                        if vid not in entries[key]["vids"]:
                            entries[key]["vids"].append(vid)
                    else:
                        entries[key] = {"term": sp[0], "def": sp[1], "vid": vid, "vids": [vid]}

    def sort_key(e):
        t = re.sub(r"^[\s\"'“‘(\[]+", "", e["term"])
        return (0 if t[:1] and "가" <= t[0] <= "힣" else 1, t)

    groups: dict = {}
    for e in sorted(entries.values(), key=sort_key):
        groups.setdefault(term_initial(re.sub(r"^[\s\"'“‘(\[]+", "", e["term"])), []).append(e)
    blocks = []
    for ini, es in groups.items():
        rows = []
        for e in es:
            refs = []
            for v in e["vids"]:
                if refs:
                    refs.append(("text", ", "))
                refs.append(("anchor", f"{nums[v]}강", f"v-{v}"))
            rows.append([[("bold", e["term"])], runs(e["def"], e["vid"]), refs])
        blocks.append({"t": "h3", "text": ini})
        blocks.append({"t": "table", "cls": "gloss", "head": ["용어", "뜻", "나온 강의"], "rows": rows,
                       "widths": [3.6, 9.6, 2.8]})
    return blocks


def lesson_blocks(vid: str, lesson: dict, num: str, img_dir: pathlib.Path, dups: set) -> list:
    shots = set(capture_points(lesson))
    out = [{"t": "lesson", "id": f"v-{vid}", "num": num, "title": lesson["title"],
            "url": f"https://youtu.be/{vid}"}]
    for name, head, items in merged_sections(lesson):
        if name == "바로잡기":
            paras = ([runs(head, vid)] if head else []) + [runs(t, vid) for _, t in items]
            out.append({"t": "box", "kind": "fix", "title": "바로잡기 (노트 수정)", "paras": paras})
            continue
        out.append({"t": "h4", "text": SECTION_TITLES[name], "kind": name})
        if head:
            out.append({"t": "para", "runs": runs(head, vid), "cls": "sec-head"})
        lst = []
        for d, text in items:
            fig = None
            ts = first_ts(text)
            if name in FIG_SECTIONS and d == 0 and ts in shots:
                fig = figure_block(vid, ts, img_dir, dups)
                shots.discard(ts)
            lst.append((d, runs(text, vid), fig))
        if lst:
            out.append({"t": "list", "items": lst, "kind": name})
        if name == "예시":
            for t in sorted(shots):
                out.append(figure_block(vid, t, img_dir, dups))
            shots.clear()
    for t in sorted(shots):       # 예시 구역이 없을 때 남은 캡처
        out.append(figure_block(vid, t, img_dir, dups))
    return out


def review_blocks(review: list, lessons: dict, nums: dict) -> dict:
    items = []
    for r in review:
        if isinstance(r, str):
            items.append({"q": runs(r, None), "a": None, "refs": []})
            continue
        if not isinstance(r, dict) or not r.get("q"):
            continue
        ref = r.get("ref") or {}
        vid = ref.get("vid") if isinstance(ref, dict) else None
        refs = []
        if vid:
            sec = parse_mmss(ref.get("t", "")) if ref.get("t") else None
            url = f"https://youtu.be/{vid}" + (f"?t={sec}" if sec is not None else "")
            refs.append(("link", f"▶ 영상 {mmss(sec)}" if sec is not None else "▶ 영상 보기", url))
            if vid in nums:
                refs.append(("text", " · "))
                refs.append(("anchor", f"본문 {nums[vid]}강 다시 읽기", f"v-{vid}"))
        items.append({"q": runs(str(r["q"]), None), "a": runs(str(r.get("a") or ""), vid) or None,
                      "refs": refs})
    return {"t": "review", "items": items}


def build_model(cfg: dict, lessons: dict, img_dir: pathlib.Path, manifest: dict) -> tuple:
    """(블록 목록, 강의 수, 노트에 없는 영상)"""
    nums, n, missing = {}, 0, []
    for ch in cfg["chapters"]:
        for vid in ch["videos"]:
            if vid in lessons and vid not in nums:
                n += 1
                nums[vid] = f"{n:02d}"
            elif vid not in lessons:
                missing.append(vid)

    toc: list = []
    body: list = []
    for ci, ch in enumerate(cfg["chapters"], 1):
        cid = f"ch{ci}"
        toc.append((1, ch["title"], cid))
        body.append({"t": "chapter", "id": cid, "title": ch["title"]})
        if ch.get("intro"):
            body.append({"t": "para", "runs": runs(ch["intro"], None), "cls": "intro"})
        if ch.get("btc_note"):
            body.append({"t": "box", "kind": "btc", "title": "BTC에 쓸 때", "paras": [runs(ch["btc_note"], None)]})
        for vid in ch["videos"]:
            if vid not in lessons:
                continue
            toc.append((2, f'{nums[vid]}. {lessons[vid]["title"]}', f"v-{vid}"))
            dups = set(manifest.get(vid, {}).get("dup", []))
            body += lesson_blocks(vid, lessons[vid], nums[vid], img_dir, dups)
        if ch.get("review"):
            body.append(review_blocks(ch["review"], lessons, nums))

    gloss = build_glossary(cfg, lessons, nums)
    typos = parse_typos()
    if gloss or typos:
        toc.append((1, "용어 사전", "glossary"))
        body.append({"t": "chapter", "id": "glossary", "title": "용어 사전"})
        body.append({"t": "para", "cls": "intro", "runs": [(
            "text", "강의 노트의 '용어'를 모아 가나다순으로 정리했다. 같은 용어가 여러 강의에 나오면 처음 나온 뜻을 싣고, "
                    "나온 강의 번호를 모두 적었다.")]})
        body += gloss
        if typos:
            body.append({"t": "h2", "text": "자막 오타 표", "id": "typos"})
            body.append({"t": "para", "runs": [("text", "자동 자막에 자주 나오는 잘못된 표기와 바로잡은 말이다. "
                                                       "영상 자막을 직접 볼 때 참고한다.")]})
            body.append({"t": "table", "cls": "typo", "head": ["자막 표기", "바로잡은 말"],
                         "rows": [[runs(a, None), runs(b, None)] for a, b in typos], "widths": [7.0, 9.0]})

    app = cfg.get("project_appendix")
    if isinstance(app, dict) and app.get("title"):
        toc.append((1, app["title"], "appendix"))
        body.append({"t": "chapter", "id": "appendix", "title": app["title"]})
        for p in app.get("paragraphs") or []:
            body.append({"t": "para", "runs": runs(str(p), None)})

    front = [{"t": "cover", "title": cfg["title"], "subtitle": cfg.get("subtitle", ""),
              "meta": f"만든 날 {time.strftime('%Y-%m-%d')} · 강의 {n}편"},
             {"t": "box", "kind": "warn", "title": "", "paras": [
                 [("text", "개인 학습용입니다. 강의와 화면의 저작권은 차트프로(@chart_pro)에 있습니다. 공유·게시하지 마세요.")],
                 [("text", "본문은 자동 자막을 바탕으로 정리한 노트라 오타를 고친 곳은 "), ("guess", "[추정]"),
                  ("text", "으로 표시했습니다. 시각 표시(예: 03:12)를 누르면 원본 영상의 그 장면부터 재생됩니다.")]]}]
    if cfg.get("how_to_study"):
        front.append({"t": "box", "kind": "study", "title": "이 교재로 공부하는 법",
                      "paras": [runs(str(s), None) for s in cfg["how_to_study"]], "bullets": True})
    front.append({"t": "toc", "entries": toc})
    return front + body, n, missing


# ---------------------------------------------------------------------------
# HTML (인쇄·PDF용 정적 페이지, 스크립트 없음)
# ---------------------------------------------------------------------------


def h_runs(rs: list) -> str:
    out = []
    for r in rs:
        k, text = r[0], html.escape(r[1], quote=False)
        if k == "bold":
            out.append(f"<strong>{text}</strong>")
        elif k == "guess":
            out.append(f'<span class="guess">{text}</span>')
        elif k == "ts":
            out.append(f'<a class="ts" href="{html.escape(r[2])}">{text}</a>')
        elif k == "link":
            out.append(f'<a href="{html.escape(r[2])}">{text}</a>')
        elif k == "anchor":
            out.append(f'<a href="#{html.escape(r[2])}">{text}</a>')
        else:
            out.append(text)
    return "".join(out)


def h_figure(f: dict) -> str:
    url = html.escape(f["url"])
    if f["img"] is None:
        note = f' ({f["note"]})' if f["note"] else ""
        return f'<p class="noshot"><a href="{url}">▶ 영상 {f["label"]} 화면 보기</a>{note}</p>'
    wh = f' width="{f["size"][0]}" height="{f["size"][1]}"' if f.get("size") else ""
    return (f'<figure><img src="{html.escape(f["rel"])}"{wh} alt="강의 화면 {f["label"]}">'
            f'<figcaption>영상 {f["label"]} 화면 · <a href="{url}">유튜브에서 이 장면 보기</a></figcaption></figure>')


def h_list(items: list) -> str:
    out, depth = [], -1
    for d, rs, fig in items:
        d = min(d, depth + 1)
        while depth < d:
            out.append("<ul>")
            depth += 1
        while depth > d:
            out.append("</li></ul>")
            depth -= 1
        if out[-1] != "<ul>":
            out.append("</li>")
        out.append(f"<li>{h_runs(rs)}")
        if fig:
            out.append(h_figure(fig))
    while depth >= 0:
        out.append("</li></ul>")
        depth -= 1
    return "".join(out)


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#66666c;--line:#dedcd5;--card:#fff;--accent:#b23c0b;--soft:#fff4ec;
 --note:#eef4ff;--fix:#f3f7ec;--fixline:#6b8e23}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#ececec;--muted:#a0a0a6;--line:#333336;--card:#1f1f21;
 --accent:#fb923c;--soft:#2a1d14;--note:#17202e;--fix:#1c2416;--fixline:#9acd32}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);
 font:16px/1.75 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Noto Sans CJK KR","Malgun Gothic","WenQuanYi Zen Hei",sans-serif;
 word-break:keep-all;overflow-wrap:anywhere}
main{max-width:820px;margin:0 auto;padding:24px 16px 64px}
a{color:inherit}
.cover{padding:56px 0 24px;border-bottom:2px solid var(--fg);margin-bottom:24px}
.cover h1{font-size:34px;line-height:1.3;margin:0 0 8px;letter-spacing:-.02em}
.cover p{margin:4px 0;color:var(--muted)}
.box{border-radius:8px;padding:10px 16px;margin:16px 0;font-size:14px}
.box p{margin:4px 0}.box ul{margin:4px 0}
.box .bt{font-weight:700;margin:0 0 4px}
.box-warn{background:var(--soft);border-left:4px solid var(--accent)}
.box-study{background:var(--note);border-left:4px solid #3b6fd6}
.box-btc{background:var(--note)}
.box-fix{background:var(--fix);border-left:4px solid var(--fixline);font-size:13.5px}
nav.toc h2{font-size:22px;margin:32px 0 8px}
nav.toc ol{list-style:none;padding-left:0;margin:0}
nav.toc li.l1{font-weight:700;margin:12px 0 2px}
nav.toc li.l2{font-size:14px;margin:1px 0 1px 1.2em;color:var(--muted);font-weight:400}
nav.toc a{text-decoration:none}
section.chapter > h2{font-size:27px;line-height:1.35;margin:56px 0 10px;padding-top:16px;border-top:2px solid var(--fg);letter-spacing:-.01em}
h2.sub{font-size:21px;margin:36px 0 8px}
.intro{font-size:16.5px}
.lesson{border-top:1px solid var(--line);margin:32px 0 0;padding-top:12px}
.lesson h3{margin:0 0 2px;font-size:20px;line-height:1.45}
.num{color:var(--accent);font-variant-numeric:tabular-nums;margin-right:.3em}
.src{margin:0 0 6px;font-size:13px;color:var(--muted)}
h4{margin:16px 0 4px;font-size:15px;color:var(--accent)}
h4.k-봇{color:var(--muted)}
.sec-봇 + .sec-head, h4.k-봇 ~ ul.k-봇{color:var(--muted);font-size:14px}
ul{padding-left:20px;margin:4px 0}li{margin:3px 0}
a.ts{font-size:12px;color:var(--muted);text-decoration:none;border:1px solid var(--line);border-radius:4px;padding:0 4px;margin:0 2px;white-space:nowrap}
.guess{font-size:12px;color:var(--muted)}
figure{margin:8px 0 14px;break-inside:avoid;page-break-inside:avoid}
figure img{width:100%;height:auto;border-radius:6px;border:1px solid var(--line);display:block}
figcaption{font-size:12px;color:var(--muted);margin-top:3px}
.noshot{font-size:13px;color:var(--muted);margin:4px 0 10px}
.review{background:var(--soft);border-radius:10px;padding:12px 18px;margin:28px 0}
.review h4{margin-top:4px}
.review ol{padding-left:22px}.review li{margin:10px 0}
.review .q{font-weight:700}
.review .a{margin:2px 0 0;padding-left:10px;border-left:3px solid var(--line)}
.review .a b{color:var(--accent)}
.review .ref{font-size:13px;color:var(--muted);margin:2px 0 0 13px}
.tw{overflow-x:auto;margin:8px 0 16px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--soft)}
table.gloss td:first-child{white-space:nowrap;width:24%}
table.gloss td:last-child{width:15%;font-size:13px}
@media (max-width:600px){table.gloss td:first-child{white-space:normal;width:30%}th,td{padding:4px 6px}}
h3.ini{font-size:18px;margin:20px 0 4px;color:var(--accent)}
footer{margin-top:56px;font-size:13px;color:var(--muted);border-top:1px solid var(--line);padding-top:16px}
@page{size:A4;margin:16mm 15mm 18mm}
@media print{
 :root{--bg:#fff;--fg:#000;--muted:#555;--line:#ccc;--card:#fff;--accent:#a3360a;--soft:#fff4ec;--note:#eef4ff;--fix:#f3f7ec}
 body{font-size:10.5pt;line-height:1.6;-webkit-print-color-adjust:exact;print-color-adjust:exact}
 main{max-width:none;padding:0}
 .cover{padding-top:60mm;border:none}
 nav.toc{break-before:page}
 section.chapter{break-before:page}
 section.chapter > h2{margin-top:0;border-top:none}
 h2,h3,h4{break-after:avoid;page-break-after:avoid}
 .lesson{margin-top:18px}
 a{text-decoration:none}
 a.ts{border:none;padding:0}
 figure img{max-height:105mm;width:auto;max-width:100%;margin:0 auto}
 table.gloss td:first-child,table.gloss td:last-child{white-space:normal}
 tr{break-inside:avoid}
 .review{break-inside:auto}
 footer{display:none}
}
"""


def render_html(blocks: list) -> str:
    out = []
    title = ""
    in_chapter = in_lesson = False

    def close_lesson():
        nonlocal in_lesson
        if in_lesson:
            out.append("</section>")
            in_lesson = False

    def close_chapter():
        nonlocal in_chapter
        close_lesson()
        if in_chapter:
            out.append("</section>")
            in_chapter = False

    for b in blocks:
        t = b["t"]
        if t == "cover":
            title = b["title"]
            out.append(f'<header class="cover"><h1>{html.escape(b["title"])}</h1>'
                       f'<p>{html.escape(b["subtitle"])}</p><p>{html.escape(b["meta"])}</p></header>')
        elif t == "box":
            inner = (f'<ul>{"".join(f"<li>{h_runs(p)}</li>" for p in b["paras"])}</ul>' if b.get("bullets")
                     else "".join(f"<p>{h_runs(p)}</p>" for p in b["paras"]))
            bt = f'<p class="bt">{html.escape(b["title"])}</p>' if b["title"] else ""
            out.append(f'<div class="box box-{b["kind"]}">{bt}{inner}</div>')
        elif t == "toc":
            lis = "".join(f'<li class="l{lv}"><a href="#{html.escape(a)}">{html.escape(tx)}</a></li>'
                          for lv, tx, a in b["entries"])
            out.append(f'<nav class="toc"><h2>차례</h2><ol>{lis}</ol></nav>')
        elif t == "chapter":
            close_chapter()
            out.append(f'<section class="chapter" id="{b["id"]}"><h2>{html.escape(b["title"])}</h2>')
            in_chapter = True
        elif t == "h2":
            close_lesson()
            out.append(f'<h2 class="sub" id="{b["id"]}">{html.escape(b["text"])}</h2>')
        elif t == "lesson":
            close_lesson()
            out.append(f'<section class="lesson" id="{html.escape(b["id"])}"><h3><span class="num">{b["num"]}</span>'
                       f'{html.escape(b["title"])}</h3><p class="src">원본 강의: <a href="{b["url"]}">{b["url"]}</a></p>')
            in_lesson = True
        elif t == "h4":
            k = "봇" if b["kind"] == "봇 적용" else b["kind"]
            out.append(f'<h4 class="k-{k}">{html.escape(b["text"])}</h4>')
        elif t == "h3":
            out.append(f'<h3 class="ini">{html.escape(b["text"])}</h3>')
        elif t == "para":
            cls = f' class="{b["cls"]}"' if b.get("cls") else ""
            out.append(f"<p{cls}>{h_runs(b['runs'])}</p>")
        elif t == "list":
            k = "봇" if b["kind"] == "봇 적용" else b["kind"]
            out.append(h_list(b["items"]).replace("<ul>", f'<ul class="k-{k}">', 1))
        elif t == "figure":
            out.append(h_figure(b))
        elif t == "review":
            close_lesson()
            lis = []
            for it in b["items"]:
                s = f'<li><p class="q">{h_runs(it["q"])}</p>'
                if it["a"]:
                    s += f'<p class="a"><b>답</b> {h_runs(it["a"])}</p>'
                if it["refs"]:
                    s += f'<p class="ref">{h_runs(it["refs"])}</p>'
                lis.append(s + "</li>")
            out.append(f'<div class="review"><h4>복습 질문</h4><ol>{"".join(lis)}</ol></div>')
        elif t == "table":
            head = "".join(f"<th>{html.escape(h)}</th>" for h in b["head"])
            rows = "".join("<tr>" + "".join(f"<td>{h_runs(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
            out.append(f'<div class="tw"><table class="{b["cls"]}"><thead><tr>{head}</tr></thead>'
                       f"<tbody>{rows}</tbody></table></div>")
    close_chapter()
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>
{"".join(out)}
<footer>개인 학습용 · 공유 금지. 같은 폴더의 {PDF_NAME}(읽기·인쇄용)과 {DOCX_NAME}(워드 편집용)도 같은 내용입니다.</footer>
</main></body></html>"""


# ---------------------------------------------------------------------------
# DOCX (python-docx — 없으면 건너뛴다)
# ---------------------------------------------------------------------------


KO_FONT = "Apple SD Gothic Neo"
KO_FONT_ALT = "Malgun Gothic"


def write_docx(blocks: list, path: pathlib.Path) -> None:
    import docx
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    ACCENT = RGBColor(0xA3, 0x36, 0x0A)
    MUTED = RGBColor(0x66, 0x66, 0x6C)
    LINK = RGBColor(0x1F, 0x4E, 0xB4)

    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin, sec.bottom_margin = Cm(2.0), Cm(2.0)

    def set_fonts(rpr_owner):
        rpr = rpr_owner.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            if rf.get(qn(a)) is not None:
                del rf.attrib[qn(a)]
        for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rf.set(qn(a), KO_FONT)
        lang = rpr.find(qn("w:lang"))
        if lang is None:
            lang = OxmlElement("w:lang")
            rpr.append(lang)
        lang.set(qn("w:eastAsia"), "ko-KR")

    styles = d.styles
    for name in ("Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Heading 3", "Heading 4",
                 "List Bullet", "List Bullet 2", "List Bullet 3", "Caption"):
        try:
            st = styles[name]
        except KeyError:
            continue
        set_fonts(st.element)
    normal = styles["Normal"]
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.3
    for name, size, color in (("Heading 1", 20, RGBColor(0x1D, 0x1D, 0x1F)), ("Heading 2", 14, RGBColor(0x1D, 0x1D, 0x1F)),
                              ("Heading 3", 11.5, ACCENT), ("Title", 30, RGBColor(0x1D, 0x1D, 0x1F))):
        st = styles[name]
        st.font.size = Pt(size)
        st.font.color.rgb = color
        st.font.bold = True
    styles["Heading 1"].paragraph_format.space_after = Pt(10)
    styles["Heading 2"].paragraph_format.space_before = Pt(18)
    styles["Heading 3"].paragraph_format.space_before = Pt(8)
    styles["Heading 3"].paragraph_format.space_after = Pt(2)

    # 글꼴 표: 맥 글꼴이 없는 컴퓨터(윈도)에서는 맑은 고딕으로 바꿔 보이도록 대체 이름을 적어 둔다
    try:
        for rel in d.part.rels.values():
            if rel.reltype.endswith("/fontTable") and not rel.is_external:
                part = rel.target_part
                blob = part.blob.decode("utf-8")
                if KO_FONT not in blob and "</w:fonts>" in blob:
                    font_xml = (f'<w:font w:name="{KO_FONT}"><w:altName w:val="{KO_FONT_ALT}"/>'
                                '<w:charset w:val="81"/><w:family w:val="swiss"/><w:pitch w:val="variable"/></w:font>')
                    part._blob = blob.replace("</w:fonts>", font_xml + "</w:fonts>").encode("utf-8")
    except Exception:  # noqa: BLE001 — 대체 글꼴 표시는 없어도 된다
        pass

    bm_ids: dict = {}

    def bm_name(anchor: str) -> str:
        if anchor not in bm_ids:
            bm_ids[anchor] = f"bm{len(bm_ids) + 1}"
        return bm_ids[anchor]

    bm_counter = [0]

    def add_bookmark(p, anchor):
        bm_counter[0] += 1
        start = OxmlElement("w:bookmarkStart")
        start.set(qn("w:id"), str(bm_counter[0]))
        start.set(qn("w:name"), bm_name(anchor))
        end = OxmlElement("w:bookmarkEnd")
        end.set(qn("w:id"), str(bm_counter[0]))
        p._p.insert(1 if p._p.pPr is not None else 0, start)
        p._p.append(end)

    def link_run(p, text, url=None, anchor=None, size=None, color=LINK, underline=True):
        h = OxmlElement("w:hyperlink")
        if url:
            h.set(qn("r:id"), p.part.relate_to(url, RT.HYPERLINK, is_external=True))
        else:
            h.set(qn("w:anchor"), bm_name(anchor))
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        c = OxmlElement("w:color")
        c.set(qn("w:val"), str(color))
        rpr.append(c)
        if size:                      # rPr 안 순서: color → sz → u (워드는 순서가 틀리면 파일을 못 연다)
            sz = OxmlElement("w:sz")
            sz.set(qn("w:val"), str(int(size * 2)))
            rpr.append(sz)
        if underline:
            u = OxmlElement("w:u")
            u.set(qn("w:val"), "single")
            rpr.append(u)
        r.append(rpr)
        t = OxmlElement("w:t")
        t.text = text
        t.set(qn("xml:space"), "preserve")
        r.append(t)
        h.append(r)
        p._p.append(h)

    def add_runs(p, rs, size=None):
        prev = None
        for r in rs:
            k = r[0]
            if k == "ts":
                if prev == "ts":
                    p.add_run(" ")
                link_run(p, r[1], url=r[2], size=8.5, color=MUTED, underline=False)
            elif k == "link":
                link_run(p, r[1], url=r[2], size=size)
            elif k == "anchor":
                link_run(p, r[1], anchor=r[2], size=size)
            else:
                run = p.add_run(r[1])
                if size:
                    run.font.size = Pt(size)
                if k == "bold":
                    run.bold = True
                elif k == "guess":
                    run.font.size = Pt(8.5)
                    run.font.color.rgb = MUTED
            prev = k

    def shade(p, fill, border=None):
        ppr = p._p.get_or_add_pPr()
        if border:
            bdr = OxmlElement("w:pBdr")
            left = OxmlElement("w:left")
            for k, v in (("w:val", "single"), ("w:sz", "18"), ("w:space", "6"), ("w:color", border)):
                left.set(qn(k), v)
            bdr.append(left)
            ppr.append(bdr)
        shd = OxmlElement("w:shd")
        for k, v in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", fill)):
            shd.set(qn(k), v)
        ppr.append(shd)
        p.paragraph_format.left_indent = Cm(0.3)
        p.paragraph_format.right_indent = Cm(0.3)

    def add_figure(f, indent=0.0):
        if f["img"] is None:
            p = d.add_paragraph()
            p.paragraph_format.left_indent = Cm(indent)
            link_run(p, f"▶ 영상 {f['label']} 화면 보기", url=f["url"], size=9)
            if f["note"]:
                r = p.add_run(f" ({f['note']})")
                r.font.size = Pt(9)
                r.font.color.rgb = MUTED
            return
        p = d.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_after = Pt(0)
        p.add_run().add_picture(str(f["img"]), width=Cm(15))
        cap = d.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = cap.add_run(f"영상 {f['label']} 화면 · ")
        r.font.size = Pt(8.5)
        r.font.color.rgb = MUTED
        link_run(cap, "유튜브에서 이 장면 보기", url=f["url"], size=8.5)
        cap.paragraph_format.space_after = Pt(8)

    def add_table(b):
        tb = d.add_table(rows=1, cols=len(b["head"]))
        tb.style = "Table Grid"
        tb.alignment = WD_TABLE_ALIGNMENT.CENTER
        tb.autofit = False
        hdr = tb.rows[0]
        trpr = hdr._tr.get_or_add_trPr()
        th = OxmlElement("w:tblHeader")
        th.set(qn("w:val"), "true")
        trpr.append(th)
        for i, h in enumerate(b["head"]):
            c = hdr.cells[i]
            c.paragraphs[0].add_run(h).bold = True
        for row in b["rows"]:
            cells = tb.add_row().cells
            for i, rs in enumerate(row):
                add_runs(cells[i].paragraphs[0], rs, size=9.5)
        for row in tb.rows:
            for i, w in enumerate(b.get("widths") or []):
                row.cells[i].width = Cm(w)
        d.add_paragraph()

    LIST_STYLES = ["List Bullet", "List Bullet 2", "List Bullet 3"]
    for b in blocks:
        t = b["t"]
        if t == "cover":
            for _ in range(6):
                d.add_paragraph()
            d.add_paragraph(b["title"], style="Title")
            p = d.add_paragraph(b["subtitle"])
            p.runs[0].font.size = Pt(13)
            p = d.add_paragraph(b["meta"])
            p.runs[0].font.color.rgb = MUTED
            d.add_paragraph()
        elif t == "box":
            fill, border = {"warn": ("FFF4EC", "B23C0B"), "study": ("EEF4FF", "3B6FD6"),
                            "btc": ("EEF4FF", None), "fix": ("F3F7EC", "6B8E23")}.get(b["kind"], ("F5F5F5", None))
            if b["title"]:
                p = d.add_paragraph()
                p.add_run(b["title"]).bold = True
                shade(p, fill, border)
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.keep_with_next = True
            for i, rs in enumerate(b["paras"]):
                p = d.add_paragraph()
                add_runs(p, ([("text", "• ")] if b.get("bullets") else []) + rs, size=9.5)
                shade(p, fill, border)
                p.paragraph_format.space_after = Pt(0 if i < len(b["paras"]) - 1 else 8)
        elif t == "toc":
            p = d.add_paragraph()
            p.add_run().add_break(WD_BREAK.PAGE)
            p = d.add_paragraph()
            r = p.add_run("차례")
            r.bold = True
            r.font.size = Pt(20)
            for lv, tx, a in b["entries"]:
                p = d.add_paragraph()
                p.paragraph_format.space_after = Pt(1 if lv == 2 else 2)
                if lv == 1:
                    p.paragraph_format.space_before = Pt(8)
                    link_run(p, tx, anchor=a, size=11.5, color=RGBColor(0x1D, 0x1D, 0x1F), underline=False)
                else:
                    p.paragraph_format.left_indent = Cm(0.8)
                    link_run(p, tx, anchor=a, size=9.5, color=MUTED, underline=False)
        elif t == "chapter":
            h = d.add_heading(b["title"], level=1)
            h.paragraph_format.page_break_before = True
            add_bookmark(h, b["id"])
        elif t == "h2":
            h = d.add_heading(b["text"], level=2)
            add_bookmark(h, b["id"])
        elif t == "lesson":
            h = d.add_heading("", level=2)
            r = h.add_run(b["num"] + "  ")
            r.font.color.rgb = ACCENT
            h.add_run(b["title"])
            h.paragraph_format.keep_with_next = True
            add_bookmark(h, b["id"])
            p = d.add_paragraph()
            r = p.add_run("원본 강의: ")
            r.font.size = Pt(9)
            r.font.color.rgb = MUTED
            link_run(p, b["url"], url=b["url"], size=9)
        elif t == "h4":
            h = d.add_heading(b["text"], level=3)
            if b["kind"] == "봇 적용":
                h.runs[0].font.color.rgb = MUTED
        elif t == "h3":
            d.add_heading(b["text"], level=3)
        elif t == "para":
            p = d.add_paragraph()
            add_runs(p, b["runs"], size=11 if b.get("cls") == "intro" else None)
        elif t == "list":
            small = 9.5 if b["kind"] in ("봇 적용", "기타") else None
            for dep, rs, fig in b["items"]:
                p = d.add_paragraph(style=LIST_STYLES[min(dep, 2)])
                p.paragraph_format.space_after = Pt(2)
                add_runs(p, rs, size=small)
                if fig:
                    add_figure(fig)
        elif t == "figure":
            add_figure(b)
        elif t == "review":
            p = d.add_heading("복습 질문", level=3)
            p.paragraph_format.space_before = Pt(16)
            for i, it in enumerate(b["items"], 1):
                p = d.add_paragraph()
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(1)
                p.paragraph_format.keep_with_next = bool(it["a"] or it["refs"])
                add_runs(p, [("bold", f"Q{i}. ")] + [("bold", r[1]) if r[0] in ("text", "bold") else r for r in it["q"]])
                if it["a"]:
                    p = d.add_paragraph()
                    p.paragraph_format.left_indent = Cm(0.6)
                    p.paragraph_format.space_after = Pt(1)
                    r = p.add_run("답  ")
                    r.bold = True
                    r.font.color.rgb = ACCENT
                    add_runs(p, it["a"])
                if it["refs"]:
                    p = d.add_paragraph()
                    p.paragraph_format.left_indent = Cm(0.6)
                    add_runs(p, it["refs"], size=9)
        elif t == "table":
            add_table(b)
    # 바닥글 가운데에 쪽 번호
    fp = d.sections[0].footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "18")
    rpr.append(sz)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    fp._p.append(fld)
    tmp = path.with_suffix(".docx.part")
    d.save(str(tmp))
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# PDF (Playwright + 크롬/크로미움 — 없으면 건너뛴다)
# ---------------------------------------------------------------------------


MAC_CHROME = pathlib.Path("/Applications/Google Chrome.app")


def write_pdf(html_path: pathlib.Path, pdf_path: pathlib.Path) -> None:
    from playwright.sync_api import sync_playwright

    footer = ('<div style="width:100%;font-size:8px;color:#888;text-align:center;font-family:sans-serif">'
              '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')
    tmp = pdf_path.with_suffix(".pdf.part")
    with sync_playwright() as p:
        browser = None
        if sys.platform == "darwin" and MAC_CHROME.exists():
            try:
                browser = p.chromium.launch(channel="chrome")
            except Exception:  # noqa: BLE001 — 설치된 크롬을 못 쓰면 Playwright 크로미움으로
                browser = None
        if browser is None:
            browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(html_path.as_uri(), wait_until="load", timeout=300_000)
            page.emulate_media(media="print")
            page.pdf(path=str(tmp), format="A4", print_background=True, display_header_footer=True,
                     header_template="<span></span>", footer_template=footer,
                     margin={"top": "16mm", "bottom": "18mm", "left": "15mm", "right": "15mm"})
        finally:
            browser.close()
    os.replace(tmp, pdf_path)


# ---------------------------------------------------------------------------


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="차트프로 초급 교재 만들기(개인 학습용)")
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help="결과 폴더(저장소 밖)")
    ap.add_argument("--no-video", action="store_true", help="영상을 받지 않는다(이미 있는 캡처만 쓴다)")
    ap.add_argument("--browser", choices=["chrome", "safari", "firefox", "edge", "brave"],
                    help="유튜브가 로그인을 요구할 때 그 브라우저의 로그인 상태를 빌려 쓴다")
    ap.add_argument("--only", nargs="*", help="이 영상 ID만 캡처(시험용). 여러 개는 띄어 쓴다")
    ap.add_argument("--recapture", nargs="?", const="early", choices=["early", "all"],
                    help="캡처 다시 찍기: 값 없이 쓰면 영상 첫 8초 안에서 찍힌 옛 캡처만, 'all'이면 전부")
    ap.add_argument("--supplements-dir", type=pathlib.Path,
                    default=pathlib.Path(os.environ.get("CHARTPRO_SUPPLEMENTS_DIR") or SUPPLEMENTS_DIR),
                    help="보강 노트 폴더(기본: research/chartpro/textbook/supplements)")
    ap.add_argument("--no-docx", action="store_true", help="워드(DOCX) 파일을 만들지 않는다")
    ap.add_argument("--no-pdf", action="store_true", help="PDF 파일을 만들지 않는다")
    ap.add_argument("--open", action="store_true", help="끝나면 PDF(없으면 HTML)를 연다(맥)")
    ap.add_argument("--check", action="store_true", help="영상을 받지 않고 캡처가 다 됐는지만 확인한다")
    # 영상 ID는 '-'로 시작할 수 있어(예: -vFKpVjo7vE) --only 뒤의 값은 직접 모은다
    argv = list(sys.argv[1:] if argv is None else argv)
    only, rest, i = None, [], 0
    while i < len(argv):
        if argv[i] == "--only":
            only, i = [], i + 1
            while i < len(argv) and not argv[i].startswith("--"):
                only += [x for x in argv[i].split(",") if x]
                i += 1
            continue
        rest.append(argv[i])
        i += 1
    args = ap.parse_args(rest)
    args.only = only

    out = args.out.expanduser().resolve()
    if out == REPO or REPO in out.parents:
        print(f"거부: 결과 폴더가 저장소 안입니다({out}). 저장소는 공개라 캡처를 두면 안 됩니다.")
        return 2
    img_dir = out / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    cfg = json.loads(CHAPTERS.read_text(encoding="utf-8"))
    lessons = parse_notes()
    n_sup = load_supplements(lessons, args.supplements_dir.expanduser())
    vids = list(dict.fromkeys(v for ch in cfg["chapters"] for v in ch["videos"] if v in lessons))
    manifest = load_manifest(out)

    if args.check:
        total = have = 0
        lacking = []
        for vid in vids:
            secs = capture_points(lessons[vid])
            miss = [s for s in secs if not (img_dir / shot_name(vid, s)).exists()]
            total += len(secs)
            have += len(secs) - len(miss)
            if miss:
                lacking.append((vid, len(secs) - len(miss), len(secs)))
        print(f"캡처 {have}/{total}장 (영상 {len(vids)}편 중 덜 된 영상 {len(lacking)}편)")
        for vid, h, t in lacking:
            print(f"  - {lessons[vid]['title'][:40]}  {h}/{t}  ({vid})")
        for name in (PDF_NAME, DOCX_NAME):
            print(f"{name}: {'있음' if (out / name).exists() else '없음'}")
        print("모두 완료" if not lacking else "덜 된 영상은 같은 명령을 다시 실행하면 이어서 받습니다.")
        return 0

    failed = []
    if not args.no_video:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:  # noqa: BLE001
            print(f"캡처 도구(imageio-ffmpeg)를 못 찾아 캡처를 건너뜁니다: {exc}")
            ffmpeg = None
        targets = [v for v in vids if not args.only or v in args.only] if ffmpeg else []
        for i, vid in enumerate(targets, 1):
            secs = capture_points(lessons[vid])
            entry = manifest.setdefault(vid, {})
            redo = {s for s in secs if (img_dir / shot_name(vid, s)).exists()
                    and needs_recapture(s, entry, args.recapture)}
            need = [s for s in secs if s in redo or not (img_dir / shot_name(vid, s)).exists()]
            ok, err = capture_video(vid, secs, img_dir, out / ".tmp", args.browser, redo, entry)
            dups = mark_duplicates(vid, secs, img_dir, entry, ffmpeg)
            save_manifest(out, manifest)
            note = f", 같은 화면 {len(dups)}장 생략" if dups else ""
            print(f"[{i}/{len(targets)}] {lessons[vid]['title'][:40]} — 캡처 {ok}/{len(secs)}"
                  + (f" (새로 {len(need)})" if need else "") + note + (f"  ({err})" if err else ""), flush=True)
            if err:
                failed.append(vid)
            if need:
                time.sleep(1)

    blocks, n, missing = build_model(cfg, lessons, img_dir, manifest)
    html_path = out / "index.html"
    html_path.write_text(render_html(blocks), encoding="utf-8")
    shots = len(list(img_dir.glob("*.jpg")))
    print(f"\nHTML: {html_path}  (강의 {n}편, 캡처 {shots}장, 보강 노트 {n_sup}개)")

    made = {}
    if not args.no_docx:
        try:
            write_docx(blocks, out / DOCX_NAME)
            made["docx"] = out / DOCX_NAME
            print(f"워드: {out / DOCX_NAME}")
        except ImportError:
            print("워드 파일은 건너뜀: python-docx가 설치되어 있지 않습니다 (맥 실행 스크립트를 쓰면 자동 설치).")
        except Exception as exc:  # noqa: BLE001
            print(f"워드 파일 만들기 실패: {type(exc).__name__}: {exc}")
    if not args.no_pdf:
        try:
            write_pdf(html_path, out / PDF_NAME)
            made["pdf"] = out / PDF_NAME
            print(f"PDF: {out / PDF_NAME}")
        except ImportError:
            print("PDF는 건너뜀: playwright가 설치되어 있지 않습니다 (맥 실행 스크립트를 쓰면 자동 설치).")
        except Exception as exc:  # noqa: BLE001
            print(f"PDF 만들기 실패: {type(exc).__name__}: {str(exc)[:300]}")
            print("  브라우저가 없다는 메시지면: 가상환경 파이썬으로 'python -m playwright install chromium' 실행 후 다시.")

    if missing:
        print("노트에 없는 영상:", ", ".join(missing))
    if failed:
        print(f"캡처가 덜 된 영상 {len(failed)}개 — 다시 실행하면 빠진 것만 이어서 받습니다.")
        print("계속 실패하면 크롬에 유튜브 로그인 후: --browser chrome 을 붙여 실행하세요.")
    if args.open and sys.platform == "darwin":
        target = made.get("pdf") or html_path
        subprocess.run(["open", str(target)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
