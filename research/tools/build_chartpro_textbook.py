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
TEXTBOOK_DIR = REPO / "research" / "chartpro" / "textbook"
VOLUMES = {1: (CHAPTERS, "차트프로_1권_초급"), 2: (TEXTBOOK_DIR / "vol2.json", "차트프로_2권_중급"),
           3: (TEXTBOOK_DIR / "vol3.json", "차트프로_3권_실전"), 4: (TEXTBOOK_DIR / "vol4.json", "차트프로_4권_해외선물")}
MANIFEST_NAME = "captures.json"   # 캡처 시각·중복 판정 기록 (결과 폴더 안)

CAPTURE_DELAY_S = 3      # 말을 시작한 뒤 화면에 그림이 그려질 시간
MIN_CAPTURE_S = 8        # 영상 첫 부분(제목·인트로)은 찍지 않는다
MAX_SHOTS = 12           # 영상 하나당 최대 캡처 수
MIN_GAP_S = 10           # 이보다 가까운 시각은 같은 화면으로 보고 한 장만
SIG_W, SIG_H = 32, 18    # 중복 판정용 축소 크기(흑백)
DUP_MAD = 2.0            # 축소 화면의 평균 밝기 차이(0~255)가 이보다 작으면 같은 화면

# 영상 시각 표기: [03:12] · (03:12) · [03:12~03:40] · [03:12–03:40] (노트마다 모양이 조금 다르다)
_TS1 = r"[\[(](\d{1,2}):(\d{2})(?:\s*[~–-]\s*\d{1,2}:\d{2})?[\])]"
TS_RE = re.compile(_TS1)
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
# 문서 모델 (HTML·PDF와 DOCX가 같은 내용을 쓰도록 한 번만 만든다)
# ---------------------------------------------------------------------------
# 글 조각(run): ("text"|"bold"|"guess", 글) 또는 ("link", 글, url) 또는 ("anchor", 글, id)
# 책에는 영상 시각([mm:ss])을 싣지 않는다. 시각은 캡처 위치를 정하는 데만 쓴다.

_TS0 = r"[\[(]\d{1,2}:\d{2}(?:\s*[~–-]\s*\d{1,2}:\d{2})?[\])]"
TS_GROUP_RE = re.compile(_TS0 + r"(?:\s*(?:~|–|-|,|·|/)?\s*" + _TS0 + r")*")


def strip_ts(text: str) -> str:
    t = TS_GROUP_RE.sub("", text)
    t = re.sub(r"\(\s*[,~·/]*\s*\)", "", t)            # 시각만 들어 있던 괄호
    t = re.sub(r"\s+([,.:;)\]」』])", r"\1", t)
    t = re.sub(r"([(\[「『])\s+", r"\1", t)
    t = re.sub(r",\s*([)\]])", r"\1", t)
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    return re.sub(r"\s*[,~·/]\s*$", "", t)


def runs(text: str, vid: str | None = None) -> list:
    text = strip_ts(text)
    out, pos = [], 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append(("text", text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(("bold", m.group(1)))
        elif m.group(4) is not None:
            out.append(("guess", m.group(4)))
        pos = m.end()
    if pos < len(text):
        out.append(("text", text[pos:]))
    return out


def plain(text: str) -> str:
    return re.sub(r"\[추정[^\]]*\]", "", strip_ts(text)).replace("**", "").strip()


def short_caption(text: str, limit: int = 46) -> str:
    t = plain(text)
    for sep in (". ", " — ", ": ", " → "):
        if sep in t and 8 <= t.index(sep) <= limit:
            return t[:t.index(sep)].rstrip(".")
    return t if len(t) <= limit else t[:limit].rstrip() + "…"


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


class FigCounter:
    def __init__(self):
        self.chapter, self.n = "", 0

    def start(self, chapter: str):
        self.chapter, self.n = chapter, 0

    def next(self) -> str:
        self.n += 1
        return f"{self.chapter}-{self.n}" if self.chapter else str(self.n)


def figure_block(vid: str, sec: int, img_dir: pathlib.Path, dups: set, caption: str, figs: FigCounter) -> dict | None:
    """캡처가 있고 앞 화면과 다를 때만 그림을 싣는다(책에는 '영상 보기' 링크를 넣지 않는다)."""
    path = img_dir / shot_name(vid, sec)
    if sec in dups or not path.exists():
        return None
    return {"t": "figure", "num": figs.next(), "caption": caption, "img": path,
            "rel": f"img/{path.name}", "size": jpeg_size(path)}


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
    """'용어 = 뜻' 또는 '용어: 뜻' → (용어, 뜻). 형식이 아니면 None."""
    text = strip_ts(text)
    for sep in (" = ", ": "):
        if sep in text:
            term, rest = text.split(sep, 1)
            term = term.replace("**", "").strip()
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
                        entries[key] = {"term": sp[0], "def": sp[1], "vids": [vid]}

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
            rows.append([[("bold", e["term"])], runs(e["def"]), refs])
        blocks.append({"t": "h3", "text": ini})
        blocks.append({"t": "table", "cls": "gloss", "head": ["용어", "뜻", "강의"], "rows": rows,
                       "widths": [3.2, 9.0, 2.0]})
    return blocks


SECTION_LABELS = {"핵심": "핵심 내용", "규칙": "매매 규칙", "용어": "용어", "예시": "강의 예시", "기타": "덧붙임",
                  "빠진 내용": "강의에서 더 나온 내용", "보강 설명": "쉽게 풀어 보기"}


def lesson_blocks(vid: str, lesson: dict, num: str, img_dir: pathlib.Path, dups: set, figs: FigCounter) -> list:
    shots = set(capture_points(lesson))
    ltitle, series = lesson_title(lesson["title"])
    out = [{"t": "lesson", "id": f"v-{vid}", "num": num, "title": ltitle, "series": series,
            "src": f"youtu.be/{vid}"}]
    leftover: list = []
    for name, head, items in merged_sections(lesson):
        if name in ("바로잡기", "봇 적용"):
            paras = ([runs(head)] if head else []) + [runs(t) for _, t in items]
            paras = [p for p in paras if p]
            if name == "봇 적용" and paras and paras[0] and paras[0][0][0] == "text":
                first = paras[0][0][1]
                for sym, label in (("◎", "코드로 옮기기 쉬움"), ("○", "비슷하게 옮길 수 있음"), ("×", "사람의 판단 필요")):
                    if first.lstrip().startswith(sym):
                        rest = first.lstrip()[1:].lstrip(" —-:")
                        paras[0] = [("bold", label), ("text", (" — " + rest) if rest else "")] + paras[0][1:]
                        break
            if paras:
                out.append({"t": "box", "kind": "fix" if name == "바로잡기" else "bot",
                            "title": "바로잡기" if name == "바로잡기" else "BTC 노트",
                            "paras": paras, "bullets": len(paras) > 1})
            continue
        out.append({"t": "h4", "text": SECTION_LABELS.get(name, name), "kind": name})
        if head and plain(head):
            out.append({"t": "para", "runs": runs(head), "cls": "sec-head"})
        lst = []
        for d, text in items:
            fig = None
            ts = first_ts(text)
            if name in FIG_SECTIONS and d == 0 and ts in shots:
                fig = figure_block(vid, ts, img_dir, dups, short_caption(text), figs)
                shots.discard(ts)
            if plain(text):
                lst.append((d, runs(text), fig))
        if lst:
            out.append({"t": "list", "items": lst, "kind": name})
        if name == "예시":
            for t in sorted(shots):
                f = figure_block(vid, t, img_dir, dups, "강의 예시 화면", figs)
                if f:
                    out.append(f)
            shots.clear()
    for t in sorted(shots):       # 예시 구역이 없을 때 남은 캡처
        f = figure_block(vid, t, img_dir, dups, "강의 화면", figs)
        if f:
            leftover.append(f)
    return out + leftover


SERIES_RE = re.compile(r"^\s*【([^】]+)】\s*")


def lesson_title(title: str) -> tuple:
    """'【초급-차트편#1】 캔들 기초강의 ①' → ('캔들 기초강의 ①', '초급 차트편 #1')."""
    m = SERIES_RE.match(title)
    if not m:
        return title, ""
    series = m.group(1).replace("-", " ").replace("#", " #").replace("  ", " ").strip()
    if series.startswith("초급 #"):
        series = "초급 차트편 " + series[3:]
    return title[m.end():].strip(), series


def chapter_parts(title: str) -> tuple:
    """'1장. 캔들의 기초' → ('01', '캔들의 기초'). 번호가 없으면 ('', 제목)."""
    m = re.match(r"^\s*(\d+)\s*장\.?\s*(.+)$", title)
    return (f"{int(m.group(1)):02d}", m.group(2).strip()) if m else ("", title)


def build_model(cfg: dict, lessons: dict, img_dir: pathlib.Path, manifest: dict, vol: int = 1) -> tuple:
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
    answers: list = []
    figs = FigCounter()
    for ci, ch in enumerate(cfg["chapters"], 1):
        cid = f"ch{ci}"
        cnum, cname = chapter_parts(ch["title"])
        figs.start(str(int(cnum)) if cnum else str(ci))
        toc.append((1, cnum, cname, cid))
        vids = [v for v in ch["videos"] if v in lessons]
        body.append({"t": "chapter", "id": cid, "num": cnum, "title": cname,
                     "intro": runs(ch.get("intro", "")) if ch.get("intro") else None,
                     "lessons": [(nums[v], lesson_title(lessons[v]["title"])[0], f"v-{v}") for v in vids],
                     "btc": runs(ch["btc_note"]) if ch.get("btc_note") else None})
        for vid in vids:
            toc.append((2, nums[vid], lesson_title(lessons[vid]["title"])[0], f"v-{vid}"))
            dups = set(manifest.get(vid, {}).get("dup", []))
            body += lesson_blocks(vid, lessons[vid], nums[vid], img_dir, dups, figs)
        qs, ans = [], []
        for r in ch.get("review") or []:
            if isinstance(r, str):
                qs.append(runs(r))
                continue
            if not isinstance(r, dict) or not r.get("q"):
                continue
            qs.append(runs(str(r["q"])))
            ref = r.get("ref") if isinstance(r.get("ref"), dict) else {}
            refs = [("anchor", f"→ 본문 {nums[ref['vid']]}강", f"v-{ref['vid']}")] if ref.get("vid") in nums else []
            ans.append((runs(str(r["q"])), runs(str(r.get("a") or "")), refs))
        if qs:
            body.append({"t": "review", "items": qs, "has_answers": bool(ans)})
        if ans:
            answers.append((cnum, cname, ans))

    app = cfg.get("project_appendix")
    if isinstance(app, dict) and app.get("title"):
        title = re.sub(r"^\s*부록\.?\s*", "", app["title"])
        toc.append((1, "부록", title, "appendix"))
        body.append({"t": "back", "id": "appendix", "label": "부록", "title": title})
        for p in app.get("paragraphs") or []:
            body.append({"t": "para", "runs": runs(str(p))})

    if answers:
        toc.append((1, "", "정답과 해설", "answers"))
        body.append({"t": "back", "id": "answers", "label": "", "title": "정답과 해설"})
        body.append({"t": "answers", "groups": answers})

    gloss = build_glossary(cfg, lessons, nums)
    typos = parse_typos()
    if gloss:
        toc.append((1, "", "용어 사전", "glossary"))
        body.append({"t": "back", "id": "glossary", "label": "", "title": "용어 사전"})
        body.append({"t": "para", "cls": "note", "runs": [(
            "text", "강의 노트의 용어를 가나다순으로 모았다. 같은 용어가 여러 강의에 나오면 처음 나온 뜻을 싣고 "
                    "나온 강의 번호를 모두 적었다.")]})
        body += gloss
    if typos:
        toc.append((1, "", "자막 오타 표", "typos"))
        body.append({"t": "back", "id": "typos", "label": "", "title": "자막 오타 표"})
        body.append({"t": "para", "cls": "note", "runs": [(
            "text", "자동 자막에 자주 나오는 잘못된 표기와 바로잡은 말이다. 본문에서 이렇게 고친 곳은 [추정]으로 표시했다.")]})
        body.append({"t": "table", "cls": "typo", "head": ["자막 표기", "바로잡은 말"],
                     "rows": [[runs(a), runs(b)] for a, b in typos], "widths": [6.4, 7.8]})

    today = time.strftime("%Y년 %-m월 %-d일") if sys.platform != "win32" else time.strftime("%Y-%m-%d")
    front = [{"t": "cover", "title": cfg["title"], "subtitle": cfg.get("subtitle", ""), "lessons": n,
              "chapters": len(cfg["chapters"]), "vol": vol},
             {"t": "notice", "title": cfg["title"], "paras": [
                 f"만든 날  {today}",
                 f"구성  강의 {n}편 · {len(cfg['chapters'])}개 장",
                 "원작  차트프로(@chart_pro) 유튜브 초급 강의",
                 "이 책은 강의 자동 자막을 바탕으로 정리한 개인 학습용 노트입니다. 강의 내용과 화면의 저작권은 "
                 "차트프로에 있습니다. 복제·공유·게시하지 마세요.",
                 "자동 자막의 오타를 문맥으로 고친 말에는 [추정]을 붙였습니다. 투자 판단의 근거로 쓰기 전에 "
                 "반드시 원본 강의로 확인하세요."]}]
    if cfg.get("how_to_study"):
        front.append({"t": "study", "title": "이 책으로 공부하는 법", "items": [runs(str(s)) for s in cfg["how_to_study"]]})
    front.append({"t": "toc", "entries": toc})
    return front + body, n, missing


# ---------------------------------------------------------------------------
# HTML (인쇄·PDF용 정적 페이지, 스크립트 없음)
# ---------------------------------------------------------------------------

BOOK_W, BOOK_H = 182, 257          # B5(mm)
SERIF = ('"BookSerif","Noto Serif KR","AppleMyungjo","Nanum Myeongjo","NanumMyeongjo","Noto Serif KR","Noto Serif CJK KR","Batang",'
         '"WenQuanYi Zen Hei",serif')
SANS = ('"BookSans","Pretendard","Apple SD Gothic Neo","Noto Sans KR","Noto Sans CJK KR","Malgun Gothic","WenQuanYi Zen Hei",sans-serif')


NUM = '"BookNum","Instrument Serif","Times New Roman",serif'
MONO = '"BookMono","DM Mono",ui-monospace,Menlo,monospace'

# 글꼴 파일(맥 스크립트가 ~/.chartpro_textbook_fonts 에 받아 둔다). 없으면 시스템 글꼴로 대신한다.
FONTS_DIR = pathlib.Path(os.environ.get("CHARTPRO_FONTS_DIR") or (pathlib.Path.home() / ".chartpro_textbook_fonts"))
SERIF_VF = "NotoSerifKR-VF.ttf"
SERIF_STATIC = [(400, "NotoSerifKR-Regular.ttf"), (600, "NotoSerifKR-SemiBold.ttf"), (700, "NotoSerifKR-Bold.ttf")]
FONT_FILES = [("BookSerif", "400", "NotoSerifKR-Regular.ttf"), ("BookSerif", "600", "NotoSerifKR-SemiBold.ttf"),
              ("BookSerif", "700", "NotoSerifKR-Bold.ttf"),
              ("BookSans", "300", "Pretendard-Light.ttf"), ("BookSans", "400", "Pretendard-Regular.ttf"),
              ("BookSans", "600", "Pretendard-SemiBold.ttf"), ("BookSans", "700", "Pretendard-Bold.ttf"),
              ("BookNum", "400", "InstrumentSerif-Regular.ttf"), ("BookMono", "400", "DMMono-Regular.ttf")]


def font_faces(fonts_dir: pathlib.Path) -> str:
    out = []
    for fam, w, name in FONT_FILES:
        f = fonts_dir / name
        if f.exists():
            out.append(f'@font-face{{font-family:"{fam}";font-weight:{w};src:url("{f.resolve().as_uri()}")}}')
    return "\n".join(out)


def prepare_fonts(fonts_dir: pathlib.Path) -> None:
    """가변 글꼴(본명조)을 굵기별 일반 글꼴로 바꿔 둔다. 가변 글꼴은 PDF에 그림 글꼴(Type3)로 들어가 흐려지기 때문."""
    vf = fonts_dir / SERIF_VF
    todo = [(w, fonts_dir / n) for w, n in SERIF_STATIC if not (fonts_dir / n).exists()]
    if not vf.exists() or not todo:
        return
    try:
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
    except ImportError:
        print("글꼴 변환 도구(fonttools)가 없어 본명조를 시스템 명조로 대신합니다.")
        return
    for w, dst in todo:
        font = instancer.instantiateVariableFont(TTFont(str(vf)), {"wght": w}, updateFontNames=True)
        tmp = dst.with_suffix(".part")
        font.save(str(tmp))
        os.replace(tmp, dst)


def fonts_found(fonts_dir: pathlib.Path) -> int:
    return sum((fonts_dir / n).exists() for _, _, n in FONT_FILES)


def h_runs(rs: list) -> str:
    out = []
    for r in rs:
        k, text = r[0], html.escape(r[1], quote=False)
        if k == "bold":
            out.append(f"<strong>{text}</strong>")
        elif k == "guess":
            out.append(f'<span class="guess">{text}</span>')
        elif k == "link":
            out.append(f'<a href="{html.escape(r[2])}">{text}</a>')
        elif k == "anchor":
            out.append(f'<a href="#{html.escape(r[2])}">{text}</a>')
        else:
            out.append(text)
    return "".join(out)


def h_figure(f: dict) -> str:
    wh = f' width="{f["size"][0]}" height="{f["size"][1]}"' if f.get("size") else ""
    return (f'<figure><img src="{html.escape(f["rel"])}"{wh} alt="">'
            f'<figcaption><b>그림 {f["num"]}</b>{html.escape(f["caption"])}</figcaption></figure>')


def h_list(items: list, cls: str) -> str:
    out, depth = [], -1
    for d, rs, fig in items:
        d = min(d, depth + 1)
        while depth < d:
            out.append(f'<ul class="{cls}">' if depth < 0 else "<ul>")
            depth += 1
        while depth > d:
            out.append("</li></ul>")
            depth -= 1
        if not out[-1].startswith("<ul"):
            out.append("</li>")
        out.append(f"<li>{h_runs(rs)}")
        if fig:
            out.append(h_figure(fig))
    while depth >= 0:
        out.append("</li></ul>")
        depth -= 1
    return "".join(out)


def book_css(title: str) -> str:
    head = html.escape(title).replace('"', "")
    return font_faces(FONTS_DIR) + f"""
:root{{--ink:#1e1e1c;--muted:#8c887f;--rule:#dcd7cc;--accent:#1e1e1c;--accent2:#c8452d;--tint:#f3f0e8;
 --warm:#f3f0e8;--fix:#f3f0e8;--fixline:#8c887f;--paper:#f3f0e8}}
*{{box-sizing:border-box}}
html{{background:#e9e7e2}}
body{{margin:0;color:var(--ink);font-family:{SERIF};font-size:9.6pt;line-height:1.85;word-break:keep-all;
 overflow-wrap:break-word;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
main{{background:#fff;max-width:{BOOK_W}mm;margin:0 auto}}
a{{color:inherit;text-decoration:none}}
h1,h2,h3,h4,.sans,figcaption,.box,.toc,table,.lesson-head,.opener,.back-head,.review,.answers,.notice{{font-family:{SANS}}}
p{{margin:0 0 .55em;text-align:justify}}
strong{{font-family:{SANS};font-weight:600}}
.guess{{font-family:{SANS};font-size:7.5pt;color:var(--muted);vertical-align:1px}}

/* 쪽 설정: B5, 안쪽 여백을 넓게, 바깥쪽에 쪽 번호와 머리글 */
@page{{size:{BOOK_W}mm {BOOK_H}mm;margin:21mm 17mm 22mm 19mm}}
@page :left{{margin-left:17mm;margin-right:19mm;
 @top-left{{content:"{head}";font-family:{SANS};font-weight:300;font-size:7pt;color:#8c887f;letter-spacing:.08em;vertical-align:bottom;padding-bottom:4mm}}
 @bottom-left{{content:counter(page);font-family:{NUM};font-size:10.5pt;color:#1e1e1c;vertical-align:top;padding-top:5mm}}}}
@page :right{{margin-left:19mm;margin-right:17mm;
 @top-right{{content:"CHART STUDY NOTES";font-family:{MONO};font-size:6.3pt;color:#8c887f;letter-spacing:.22em;vertical-align:bottom;padding-bottom:4mm}}
 @bottom-right{{content:counter(page);font-family:{NUM};font-size:10.5pt;color:#1e1e1c;vertical-align:top;padding-top:5mm}}}}
@page bare{{@top-left{{content:none}}@top-right{{content:none}}@bottom-left{{content:none}}@bottom-right{{content:none}}}}
@page cover{{margin:0;@top-left{{content:none}}@top-right{{content:none}}@bottom-left{{content:none}}@bottom-right{{content:none}}}}

/* 표지 */
.cover{{page:cover;overflow:hidden;background:var(--paper)}}
.cover .cv{{position:relative;width:{BOOK_W}mm;height:{BOOK_H - 1}mm}}
.cover svg{{position:absolute;left:0;top:0;display:block;width:{BOOK_W}mm;height:{BOOK_H}mm}}
.cover .kt{{font-family:{SANS};font-weight:300;letter-spacing:-.25px}}
.cover .ks{{font-family:{SANS};font-weight:400}}
.cover .num{{font-family:{NUM}}}
.cover .mono{{font-family:{MONO}}}

/* 판권·공부법·차례 */
.notice{{page:bare;break-before:page;min-height:200mm;display:flex;flex-direction:column;justify-content:flex-end;
 font-size:8.5pt;color:#444;line-height:1.75}}
.notice h2{{font-size:13pt;margin:0 0 5mm;color:var(--ink)}}
.notice p{{margin:0 0 2.5mm;text-align:left}}
.notice .rule{{border-top:1px solid var(--rule);margin:4mm 0}}
.study{{break-before:page}}
.study h2,.toc h2,.back-head h1{{font-size:21pt;font-weight:300;margin:6mm 0 9mm;letter-spacing:-.02em}}
.study ol{{margin:0;padding:0;list-style:none;counter-reset:s}}
.study li{{counter-increment:s;position:relative;padding:0 0 4mm 12mm;margin:0 0 4mm;border-bottom:1px solid #ebe7df;
 font-family:{SERIF};font-size:10.5pt;line-height:1.8}}
.study li::before{{content:counter(s,decimal-leading-zero);position:absolute;left:0;top:-1mm;font-family:{NUM};
 color:var(--accent2);font-size:16pt}}
.toc{{break-before:page}}
.toc ol{{list-style:none;margin:0;padding:0}}
.toc li{{display:flex;align-items:baseline;gap:2mm}}
.toc li .t{{flex:1;min-width:0}}
.toc li .dots{{flex:1 1 6mm;border-bottom:1px dotted #b9b3a8;transform:translateY(-1.2mm);min-width:6mm}}
.toc li .pg{{width:9mm;text-align:right;font-variant-numeric:tabular-nums}}
.toc li.l1{{font-weight:600;font-size:10.2pt;margin:5mm 0 1.2mm;break-after:avoid}}
.toc li.l1 .n{{color:var(--accent2);width:9mm;flex:none;font-family:{NUM};font-weight:400;font-size:13pt}}
.toc li.l1 .pg{{font-family:{NUM};font-weight:400;font-size:11pt}}
.toc li.l2{{font-size:8.6pt;color:#3a3a3a;margin:0 0 .6mm 9mm;font-weight:400}}
.toc li.l2 .n{{color:var(--muted);width:7mm;flex:none;font-family:{MONO};font-size:7pt}}
.toc li.l2 .t{{flex:0 1 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}

/* 장 시작 페이지 */
.opener{{page:bare;break-before:page;position:relative;padding-top:12mm}}
.opener .label{{font-family:{MONO};font-size:7.5pt;letter-spacing:.42em;color:var(--muted);margin:0;
 padding-bottom:3mm;border-bottom:.25mm solid var(--ink)}}
.opener .big{{font-family:{NUM};font-size:110pt;line-height:.95;font-weight:400;color:var(--ink);margin:10mm 0 2mm;
 letter-spacing:-.02em}}
.opener .big::after{{content:"";display:inline-block;width:3mm;height:3mm;background:var(--accent2);margin-left:2mm}}
.opener h1{{font-size:25pt;line-height:1.3;margin:0 0 10mm;font-weight:300;letter-spacing:-.03em}}
.opener .intro{{font-family:{SERIF};font-size:10.5pt;line-height:1.85;margin:0 0 8mm;text-align:justify}}
.opener .inside{{font-size:8.6pt;margin:0 0 8mm}}
.opener .inside p{{font-family:{MONO};letter-spacing:.3em;color:var(--muted);font-size:6.5pt;margin:0 0 2mm}}
.opener .inside ol{{list-style:none;margin:0;padding:0;columns:1}}
.opener .inside li{{padding:1.2mm 0;border-bottom:1px solid #ece8e0;display:flex;gap:3mm}}
.opener .inside li b{{color:var(--accent2);font-family:{MONO};font-weight:400;font-size:7.5pt;padding-top:.4mm}}
.back-head{{break-before:page;padding-top:10mm;margin-bottom:6mm}}
.back-head .label{{font-family:{MONO};font-size:7.5pt;letter-spacing:.42em;color:var(--muted);margin:0 0 4mm}}
.back-head h1{{padding-bottom:5mm;border-bottom:.25mm solid var(--ink)}}
.back-body{{break-before:page}}
.back-body.cont{{break-before:auto}}

/* 강의 */
.lesson-head{{break-before:page;margin:0 0 6mm}}
.lesson-head .k{{display:flex;align-items:center;gap:3mm;font-family:{MONO};font-size:7pt;letter-spacing:.32em;
 color:var(--accent2);margin:0 0 3mm}}
.lesson-head .k::after{{content:"";flex:1;border-top:1px solid var(--rule)}}
.lesson-head h2{{font-size:16pt;line-height:1.4;margin:0 0 2mm;font-weight:600;letter-spacing:-.025em}}
.lesson-head .src{{font-size:7.5pt;color:#9a9a9a;margin:0;letter-spacing:.02em}}
h4{{font-size:9.6pt;margin:6mm 0 2mm;color:var(--accent);font-weight:600;display:flex;align-items:center;gap:2mm;
 break-after:avoid}}
h4::before{{content:"";width:1.6mm;height:1.6mm;background:var(--accent);display:inline-block}}
h4.k-빠진내용,h4.k-보강설명{{color:var(--accent2)}}
h4.k-빠진내용::before,h4.k-보강설명::before{{background:var(--accent2)}}
.sec-head{{margin-bottom:1.5mm}}
ul{{margin:0 0 2mm;padding-left:4.5mm}}
li{{margin:0 0 1.4mm;text-align:justify}}
li::marker{{color:var(--accent)}}
ul ul{{margin-top:1mm;font-size:9.4pt;color:#333}}
ul.k-용어 li,ul.k-기타 li{{font-size:9.3pt}}
figure{{margin:3.5mm 0 4.5mm;break-inside:avoid;text-align:center}}
figure img{{display:block;max-width:100%;max-height:78mm;width:auto;height:auto;margin:0 auto;border:.3mm solid #d8d3c9}}
figcaption{{font-size:7.8pt;color:#555;margin-top:1.8mm;line-height:1.5;text-align:center}}
figcaption b{{color:var(--accent2);margin-right:2mm;font-family:{MONO};font-weight:400;letter-spacing:.08em}}
.box{{margin:5mm 0;padding:3.5mm 4.5mm;font-size:8.7pt;line-height:1.7;break-inside:avoid}}
.box .bt{{font-weight:800;font-size:8pt;letter-spacing:.18em;margin:0 0 1.5mm}}
.box p{{margin:0 0 1mm;text-align:left}}
.box ul{{margin:0;padding-left:4mm}}
.box .bt{{font-family:{MONO};font-weight:400;font-size:6.6pt;letter-spacing:.3em}}
.box-bot{{background:var(--paper);border-top:.25mm solid var(--ink)}}
.box-bot .bt{{color:var(--ink)}}
.box-fix{{background:transparent;border:.25mm solid var(--rule);border-left:.8mm solid var(--muted)}}
.box-fix .bt{{color:var(--muted)}}
.box-btc{{background:var(--paper);border-top:.25mm solid var(--accent2);margin:10mm 0 0}}
.box-btc .bt{{color:var(--accent2)}}
.review{{margin:9mm 0 0;border:.25mm solid var(--ink);padding:5mm 6mm 3mm;break-inside:avoid}}
.review .bt{{font-weight:600;font-size:10.5pt;margin:0 0 3mm;display:flex;justify-content:space-between;align-items:baseline}}
.review .bt span{{font-family:{MONO};font-size:6.4pt;letter-spacing:.12em;font-weight:400;color:var(--muted)}}
.review ol{{margin:0;padding-left:6mm}}
.review li{{font-family:{SERIF};font-size:9.8pt;margin:0 0 2.5mm}}
.review li::marker{{font-family:{SANS};font-weight:800;color:var(--accent2)}}
.answers h3{{font-size:11pt;margin:7mm 0 2.5mm;padding-bottom:1.5mm;border-bottom:1px solid var(--rule);break-after:avoid}}
.answers h3 b{{color:var(--accent2);margin-right:2.5mm;font-family:{NUM};font-weight:400;font-size:14pt}}
.answers .qa{{margin:0 0 3.5mm;break-inside:avoid}}
.answers .q{{font-weight:700;font-size:9.2pt;margin:0 0 .8mm}}
.answers .q b{{color:var(--accent2);margin-right:1.5mm}}
.answers .a{{font-family:{SERIF};font-size:9.4pt;margin:0;padding-left:5.5mm;text-align:justify}}
.answers .a a{{font-family:{SANS};font-size:7.8pt;color:var(--accent);white-space:nowrap;margin-left:1.5mm}}
h3.ini{{font-size:12pt;font-weight:300;margin:6mm 0 2mm;color:var(--accent2);break-after:avoid}}
table{{border-collapse:collapse;width:100%;font-size:8.3pt;line-height:1.55;margin:0 0 4mm}}
th{{text-align:left;font-weight:600;border-bottom:.25mm solid var(--ink);padding:1.5mm 2mm;font-size:7.8pt;letter-spacing:.06em}}
td{{border-bottom:1px solid #e3ded4;padding:1.6mm 2mm;vertical-align:top}}
tr{{break-inside:avoid}}
table.gloss td:first-child{{width:24%}}
table.gloss td:last-child{{width:12%;color:var(--accent);white-space:nowrap}}
.note{{font-size:8.8pt;color:#555;font-family:{SANS}}}
.mk{{position:absolute;left:0;top:0;font-size:1px;line-height:1px;color:#fff;white-space:nowrap}}
.lesson-head,.opener,.back-head{{position:relative}}

@media screen{{
 main{{box-shadow:0 2px 18px rgba(0,0,0,.12)}}
 .cover,.notice,.study,.toc,.opener,.back-head,.back-body,.lesson-head{{margin-top:0}}
 main>*:not(.cover){{padding-left:18mm;padding-right:18mm}}
 .lesson-head,.opener,.back-head,.study,.toc{{padding-top:14mm;border-top:6px solid #e9e7e2}}
 .box-btc{{position:static;margin-top:8mm}}
}}
"""


def cover_svg(title: str, subtitle: str, lessons: int, chapters: int, vol: int = 1) -> str:
    """표지(B5, mm 단위 SVG). 'Quiet Ledger': 얇은 캔들의 축적, 긴 횡보 뒤 단 하나의 붉은 캔들.
    실제 시세가 아니라 고정된 장식용 모양이다(같은 결과가 나오도록 난수 씨앗 고정)."""
    import random

    W, H = BOOK_W, BOOK_H
    PAPER, INK, G1, G2, RULE, RED = "#F3F0E8", "#1E1E1C", "#8C887F", "#B9B4AA", "#DCD7CC", "#C8452D"
    rnd = random.Random(20261003 + (vol - 1) * 97)

    # 가격 흐름: 하락 → 오래 좁게 횡보(기준마디 전) → 한 번의 장대 돌파 → 완만한 상승과 얕은 눌림
    n_down, n_base, n_up = 30, 44, 26
    seq, p = [], 100.0
    for _ in range(n_down):
        o = p
        c = o - rnd.uniform(-0.55, 1.35)
        seq.append((o, c))
        p = c
    base_lo, base_hi = p - 2.2, p + 2.0
    for _ in range(n_base):
        o = p
        c = min(base_hi, max(base_lo, o + rnd.uniform(-1.0, 1.0)))
        seq.append((o, c))
        p = c
    brk = len(seq)
    o = (base_lo + base_hi) / 2
    c = base_hi + 7.5
    seq.append((o, c))
    p = c
    for i in range(n_up - 1):
        o = p
        drift = 0.62 if not 6 <= i <= 10 else -0.55
        c = o + drift + rnd.uniform(-0.9, 0.9)
        seq.append((o, c))
        p = c
    bars = []
    for i, (o, c) in enumerate(seq):
        span = abs(c - o)
        wick = 0.35 + rnd.random() * (0.9 if i != brk else 0.5)
        hi = max(o, c) + wick * (1.4 if span < 0.6 else 1.0)
        lo = min(o, c) - (0.35 + rnd.random() * 0.9)
        bars.append((o, hi, lo, c))

    # 그리는 영역
    x0, x1, y0, y1 = 18.0, W - 26.0, 58.0, 160.0
    pmin = min(b[2] for b in bars) - 1.5
    pmax = max(b[1] for b in bars) + 1.5
    step = (x1 - x0) / len(bars)
    bw = step * 0.56

    def Y(v):
        return y1 - (v - pmin) / (pmax - pmin) * (y1 - y0)

    out = [f'<svg class="cover-art" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'width="{W}mm" height="{H}mm" aria-hidden="true">',
           f'<rect width="{W}" height="{H}" fill="{PAPER}"/>']
    # 가로 눈금(아주 옅게)과 오른쪽 작은 숫자
    for k in range(11):
        yy = y0 + k * (y1 - y0) / 10
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{yy:.2f}" y2="{yy:.2f}" stroke="{RULE}" stroke-width=".12"/>')
        val = pmax - k * (pmax - pmin) / 10
        out.append(f'<text x="{x1 + 2.2}" y="{yy + .9:.2f}" class="mono" font-size="2.1" fill="{G2}">'
                   f'{val:06.2f}</text>')
    # 세로 눈금: 20봉마다 아주 짧은 표시
    for i in range(0, len(bars) + 1, 20):
        xx = x0 + i * step
        out.append(f'<line x1="{xx:.2f}" x2="{xx:.2f}" y1="{y1 + 1.2}" y2="{y1 + 2.6}" stroke="{G1}" stroke-width=".12"/>')
        out.append(f'<text x="{xx:.2f}" y="{y1 + 5.6}" class="mono" font-size="2.1" fill="{G2}" '
                   f'text-anchor="middle">{i:03d}</text>')
    # 횡보 상단(돌파 기준선): 점선 한 줄
    by = Y(base_hi + 0.2)
    bx0 = x0 + n_down * step
    out.append(f'<line x1="{bx0:.2f}" x2="{x1:.2f}" y1="{by:.2f}" y2="{by:.2f}" stroke="{G1}" '
               f'stroke-width=".14" stroke-dasharray=".5 .9"/>')
    # 캔들
    for i, (o, hi, lo, c) in enumerate(bars):
        cx = x0 + (i + 0.5) * step
        up = c >= o
        col = RED if i == brk else INK
        out.append(f'<line x1="{cx:.2f}" x2="{cx:.2f}" y1="{Y(hi):.2f}" y2="{Y(lo):.2f}" stroke="{col}" '
                   f'stroke-width=".13"/>')
        top, bot = Y(max(o, c)), Y(min(o, c))
        h = max(bot - top, .22)
        if i == brk:
            out.append(f'<rect x="{cx - bw / 2:.2f}" y="{top:.2f}" width="{bw:.2f}" height="{h:.2f}" fill="{RED}"/>')
            mid = Y((o + c) / 2)                    # 허리: 붉은 캔들 몸통의 가운데에 아주 짧은 표시
            out.append(f'<line x1="{cx + bw / 2 + .5:.2f}" x2="{cx + bw / 2 + 2.2:.2f}" y1="{mid:.2f}" '
                       f'y2="{mid:.2f}" stroke="{RED}" stroke-width=".14"/>')
        elif up:
            out.append(f'<rect x="{cx - bw / 2 + .065:.2f}" y="{top:.2f}" width="{bw - .13:.2f}" height="{h:.2f}" '
                       f'fill="{PAPER}" stroke="{INK}" stroke-width=".13"/>')
        else:
            out.append(f'<rect x="{cx - bw / 2:.2f}" y="{top:.2f}" width="{bw:.2f}" height="{h:.2f}" fill="{INK}"/>')
    # 거래량: 가는 막대, 돌파 봉만 진하게
    vy = 176.0
    rv = random.Random(7)
    for i, (o, hi, lo, c) in enumerate(bars):
        cx = x0 + (i + 0.5) * step
        v = 1.2 + rv.random() * 2.6 + (abs(c - o) * .7)
        if n_down <= i < brk:
            v *= .55
        if i == brk:
            v = 11.5
        out.append(f'<line x1="{cx:.2f}" x2="{cx:.2f}" y1="{vy:.2f}" y2="{vy - v:.2f}" '
                   f'stroke="{INK if i == brk else G2}" stroke-width="{bw * .55:.2f}"/>')
    out.append(f'<line x1="{x0}" x2="{x1}" y1="{vy + .4}" y2="{vy + .4}" stroke="{G2}" stroke-width=".12"/>')

    # 글자
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    out.append(f'<text x="18" y="24" class="mono" font-size="2.5" letter-spacing=".9" fill="{INK}">'
               f'CHART STUDY NOTES</text>')
    out.append(f'<text x="{W - 18}" y="24" class="mono" font-size="2.5" letter-spacing=".9" fill="{G1}" '
               f'text-anchor="end">VOL. {vol:02d}</text>')
    out.append(f'<line x1="18" x2="{W - 18}" y1="28" y2="28" stroke="{INK}" stroke-width=".18"/>')
    out.append(f'<text x="18" y="35.2" class="mono" font-size="2.1" letter-spacing=".5" fill="{G1}">'
               f'FIG. 0 — ACCUMULATION, COMPRESSION, RELEASE</text>')

    words = title.split()
    ty = 206.0
    if len(words) >= 2:
        out.append(f'<text x="17.2" y="{ty}" class="kt" font-size="15.5" fill="{INK}">{esc(words[0])}</text>')
        out.append(f'<text x="17.2" y="{ty + 17}" class="kt" font-size="15.5" fill="{INK}">{esc(" ".join(words[1:]))}</text>')
        sy = ty + 26.5
    else:
        out.append(f'<text x="17.2" y="{ty}" class="kt" font-size="15.5" fill="{INK}">{esc(title)}</text>')
        sy = ty + 9.5
    out.append(f'<text x="{W - 18}" y="{ty + 17}" class="num" font-size="34" fill="{INK}" text-anchor="end">'
               f'{lessons}</text>')
    out.append(f'<text x="{W - 18}" y="{ty + 23.5}" class="mono" font-size="2.1" letter-spacing=".5" fill="{G1}" '
               f'text-anchor="end">LESSONS</text>')
    sub = subtitle.replace(" — 개인 학습용", "").strip()
    out.append(f'<text x="18" y="{sy}" class="ks" font-size="3.1" fill="{G1}">{esc(sub)}</text>')
    out.append(f'<line x1="18" x2="{W - 18}" y1="{H - 21}" y2="{H - 21}" stroke="{INK}" stroke-width=".18"/>')
    out.append(f'<text x="18" y="{H - 15.5}" class="mono" font-size="2.1" letter-spacing=".5" fill="{G1}">'
               f'PL. {vol:02d} — {chapters} CHAPTERS</text>')
    out.append(f'<text x="{W - 18}" y="{H - 15.5}" class="mono" font-size="2.1" letter-spacing=".5" fill="{G1}" '
               f'text-anchor="end">PERSONAL EDITION · NOT FOR DISTRIBUTION</text>')
    out.append("</svg>")
    return "".join(out)


def render_html(blocks: list, markers: bool = False, pages: dict | None = None) -> str:
    """markers=True면 제목마다 PDF에서 찾을 수 있는 작은 표식을 넣는다(쪽 번호 계산용, 1차 렌더링에만)."""
    pages = pages or {}
    out = []
    title = ""

    def mk(anchor: str) -> str:
        if not markers:
            return ""
        return f'<span class="mk">@@{marker_ids.setdefault(anchor, len(marker_ids) + 1)}@@</span>'

    for b in blocks:
        t = b["t"]
        if t == "cover":
            title = b["title"]
            # 표지 SVG는 고정 높이 상자 안에 절대 위치로 둔다(SVG를 바로 두면 크롬이 표지 쪽 여백 0을 무시함)
            out.append(f'<section class="cover"><div class="cv">'
                       f'{cover_svg(b["title"], b["subtitle"], b["lessons"], b.get("chapters", 10), b.get("vol", 1))}</div></section>')
        elif t == "notice":
            ps = b["paras"]
            meta = "".join(f"<p>{html.escape(p)}</p>" for p in ps[:3])
            rest = "".join(f"<p>{html.escape(p)}</p>" for p in ps[3:])
            out.append(f'<section class="notice"><h2>{html.escape(b["title"])}</h2>{meta}<div class="rule"></div>{rest}</section>')
        elif t == "study":
            lis = "".join(f"<li>{h_runs(r)}</li>" for r in b["items"])
            out.append(f'<section class="study"><h2>{html.escape(b["title"])}</h2><ol>{lis}</ol></section>')
        elif t == "toc":
            lis = []
            for lv, num, tx, a in b["entries"]:
                pg = pages.get(a, "")
                lis.append(f'<li class="l{lv}"><span class="n">{html.escape(num)}</span>'
                           f'<a class="t" href="#{html.escape(a)}">{html.escape(tx)}</a>'
                           f'<span class="dots"></span><span class="pg">{pg}</span></li>')
            out.append(f'<nav class="toc"><h2>차례</h2><ol>{"".join(lis)}</ol></nav>')
        elif t == "chapter":
            inside = "".join(f'<li><b>{n}</b><a href="#{a}">{html.escape(tx)}</a></li>' for n, tx, a in b["lessons"])
            intro = f'<p class="intro">{h_runs(b["intro"])}</p>' if b["intro"] else ""
            btc = (f'<div class="box box-btc"><p class="bt">BTC에 쓸 때</p><p>{h_runs(b["btc"])}</p></div>'
                   if b["btc"] else "")
            big = f'<p class="big">{b["num"]}</p>' if b["num"] else ""
            out.append(f'<section class="opener" id="{b["id"]}">{mk(b["id"])}<p class="label">CHAPTER</p>{big}'
                       f'<h1>{html.escape(b["title"])}</h1>{intro}'
                       f'<div class="inside"><p>이 장의 강의</p><ol>{inside}</ol></div>{btc}</section>')
        elif t == "back":
            label = f'<p class="label">{html.escape(b["label"])}</p>' if b["label"] else '<p class="label">&nbsp;</p>'
            out.append(f'<section class="back-head" id="{b["id"]}">{mk(b["id"])}{label}'
                       f'<h1>{html.escape(b["title"])}</h1></section>')
        elif t == "lesson":
            out.append(f'<header class="lesson-head" id="{html.escape(b["id"])}">{mk(b["id"])}'
                       f'<p class="k">LESSON {b["num"]}</p><h2>{html.escape(b["title"])}</h2>'
                       f'<p class="src">{html.escape(b["series"] + " · " if b["series"] else "")}원본 강의 '
                       f'{html.escape(b["src"])}</p></header>')
        elif t == "h4":
            out.append(f'<h4 class="k-{b["kind"].replace(" ", "")}">{html.escape(b["text"])}</h4>')
        elif t == "h3":
            out.append(f'<h3 class="ini">{html.escape(b["text"])}</h3>')
        elif t == "para":
            cls = f' class="{b["cls"]}"' if b.get("cls") else ""
            out.append(f"<p{cls}>{h_runs(b['runs'])}</p>")
        elif t == "list":
            out.append(h_list(b["items"], "k-" + b["kind"].replace(" ", "")))
        elif t == "figure":
            out.append(h_figure(b))
        elif t == "box":
            inner = (f'<ul>{"".join(f"<li>{h_runs(p)}</li>" for p in b["paras"])}</ul>' if b.get("bullets")
                     else "".join(f"<p>{h_runs(p)}</p>" for p in b["paras"]))
            out.append(f'<div class="box box-{b["kind"]}"><p class="bt">{html.escape(b["title"])}</p>{inner}</div>')
        elif t == "review":
            lis = "".join(f"<li>{h_runs(q)}</li>" for q in b["items"])
            hint = "<span>정답과 해설은 책 뒤에</span>" if b["has_answers"] else ""
            out.append(f'<div class="review"><p class="bt">확인 문제{hint}</p><ol>{lis}</ol></div>')
        elif t == "answers":
            parts = []
            for cnum, cname, items in b["groups"]:
                parts.append(f'<h3><b>{cnum}</b>{html.escape(cname)}</h3>')
                for i, (q, a, refs) in enumerate(items, 1):
                    parts.append(f'<div class="qa"><p class="q"><b>{i}</b>{h_runs(q)}</p>'
                                 f'<p class="a">{h_runs(a)}{h_runs(refs)}</p></div>')
            out.append(f'<section class="answers">{"".join(parts)}</section>')
        elif t == "table":
            head = "".join(f"<th>{html.escape(h)}</th>" for h in b["head"])
            rows = "".join("<tr>" + "".join(f"<td>{h_runs(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
            out.append(f'<table class="{b["cls"]}"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>')
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>{html.escape(title)}</title><style>{book_css(title)}</style></head><body><main>
{"".join(out)}
</main></body></html>"""


# ---------------------------------------------------------------------------
# DOCX (python-docx — 없으면 건너뛴다)
# ---------------------------------------------------------------------------


KO_SERIF, KO_SERIF_ALT = "Noto Serif KR", "AppleMyungjo"     # 맥 스크립트가 내 글꼴 폴더에 설치
KO_SANS, KO_SANS_ALT = "Pretendard", "Apple SD Gothic Neo"


def write_docx(blocks: list, path: pathlib.Path, cover_png: pathlib.Path | None = None) -> None:
    import docx
    from docx.enum.section import WD_SECTION
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    INK = RGBColor(0x1B, 0x1B, 0x1B)
    ACCENT = RGBColor(0x1F, 0x4E, 0x5F)
    ACCENT2 = RGBColor(0xC0, 0x60, 0x3A)
    MUTED = RGBColor(0x6A, 0x6A, 0x6A)
    GREEN = RGBColor(0x6B, 0x8A, 0x3A)

    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(BOOK_W / 10), Cm(BOOK_H / 10)
    sec.left_margin, sec.right_margin = Cm(1.9), Cm(1.7)       # 거울 여백: 왼쪽 값이 안쪽
    sec.top_margin, sec.bottom_margin = Cm(2.1), Cm(2.2)
    sec.header_distance, sec.footer_distance = Cm(1.1), Cm(1.1)
    text_w = BOOK_W / 10 - 1.9 - 1.7
    settings = d.settings.element
    mm = OxmlElement("w:mirrorMargins")
    settings.insert(0, mm)
    d.settings.odd_and_even_pages_header_footer = True

    def set_font(owner, font):
        rpr = owner.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            if rf.get(qn(a)) is not None:
                del rf.attrib[qn(a)]
        for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rf.set(qn(a), font)
        lang = rpr.find(qn("w:lang"))
        if lang is None:
            lang = OxmlElement("w:lang")
            rpr.append(lang)
        lang.set(qn("w:eastAsia"), "ko-KR")

    styles = d.styles
    for name in ("Normal", "List Bullet", "List Bullet 2", "List Bullet 3"):
        set_font(styles[name].element, KO_SERIF)
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3", "Caption"):
        set_font(styles[name].element, KO_SANS)
    normal = styles["Normal"]
    normal.font.size = Pt(10)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.line_spacing = 1.45
    for name, size, color in (("Title", 30, RGBColor(0xFF, 0xFF, 0xFF)), ("Heading 1", 22, INK),
                              ("Heading 2", 15, INK), ("Heading 3", 10, ACCENT)):
        st = styles[name]
        st.font.size = Pt(size)
        st.font.color.rgb = color
        st.font.bold = True
        st.paragraph_format.keep_with_next = True
    styles["Heading 1"].paragraph_format.space_after = Pt(14)
    styles["Heading 2"].paragraph_format.space_before = Pt(0)
    styles["Heading 2"].paragraph_format.space_after = Pt(2)
    styles["Heading 3"].paragraph_format.space_before = Pt(10)
    styles["Heading 3"].paragraph_format.space_after = Pt(3)

    # 글꼴 표: 맥 글꼴이 없는 컴퓨터(윈도)에서 대신 쓸 글꼴 이름
    try:
        for rel in d.part.rels.values():
            if rel.reltype.endswith("/fontTable") and not rel.is_external:
                part = rel.target_part
                blob = part.blob.decode("utf-8")
                add = ""
                for f, alt, fam in ((KO_SERIF, KO_SERIF_ALT, "roman"), (KO_SANS, KO_SANS_ALT, "swiss")):
                    if f not in blob:
                        add += (f'<w:font w:name="{f}"><w:altName w:val="{alt}"/><w:charset w:val="81"/>'
                                f'<w:family w:val="{fam}"/><w:pitch w:val="variable"/></w:font>')
                if add and "</w:fonts>" in blob:
                    part._blob = blob.replace("</w:fonts>", add + "</w:fonts>").encode("utf-8")
    except Exception:  # noqa: BLE001 — 대체 글꼴 표시는 없어도 된다
        pass

    bm_ids: dict = {}
    bm_counter = [0]

    def bm_name(anchor: str) -> str:
        if anchor not in bm_ids:
            bm_ids[anchor] = f"bm{len(bm_ids) + 1}"
        return bm_ids[anchor]

    def add_bookmark(p, anchor):
        bm_counter[0] += 1
        start = OxmlElement("w:bookmarkStart")
        start.set(qn("w:id"), str(bm_counter[0]))
        start.set(qn("w:name"), bm_name(anchor))
        end = OxmlElement("w:bookmarkEnd")
        end.set(qn("w:id"), str(bm_counter[0]))
        p._p.insert(1 if p._p.pPr is not None else 0, start)
        p._p.append(end)

    def styled_run(p, text, size=None, bold=False, color=None, font=None, spacing=None):
        r = p.add_run(text)
        if size:
            r.font.size = Pt(size)
        if bold:
            r.bold = True
        if color is not None:
            r.font.color.rgb = color
        if font:
            set_font(r._r, font)
        if spacing:
            rpr = r._r.get_or_add_rPr()
            sp = OxmlElement("w:spacing")
            sp.set(qn("w:val"), str(spacing))
            rpr.append(sp)
        return r

    def anchor_run(p, text, anchor, size=None, color=ACCENT, bold=False, font=None):
        h = OxmlElement("w:hyperlink")
        h.set(qn("w:anchor"), bm_name(anchor))
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        if font:
            rf = OxmlElement("w:rFonts")
            for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
                rf.set(qn(a), font)
            rpr.append(rf)
        if bold:
            rpr.append(OxmlElement("w:b"))
        c = OxmlElement("w:color")                 # rPr 안 순서: rFonts → b → color → sz
        c.set(qn("w:val"), str(color))
        rpr.append(c)
        if size:
            sz = OxmlElement("w:sz")
            sz.set(qn("w:val"), str(int(size * 2)))
            rpr.append(sz)
        r.append(rpr)
        t = OxmlElement("w:t")
        t.text = text
        t.set(qn("xml:space"), "preserve")
        r.append(t)
        h.append(r)
        p._p.append(h)

    def add_runs(p, rs, size=None, font=None):
        for r in rs:
            k = r[0]
            if k == "anchor":
                anchor_run(p, r[1], r[2], size=(size or 10) - 1.5, font=KO_SANS)
            elif k == "link":
                styled_run(p, r[1], size=size, font=font)
            else:
                run = styled_run(p, r[1], size=size, font=font)
                if k == "bold":
                    run.bold = True
                    set_font(run._r, KO_SANS)
                elif k == "guess":
                    run.font.size = Pt(7.5)
                    run.font.color.rgb = MUTED
                    set_font(run._r, KO_SANS)

    def ppr_add(p, el):
        p._p.get_or_add_pPr().append(el)

    def shade(p, fill, left=None, top=None):
        ppr = p._p.get_or_add_pPr()
        if left or top:
            bdr = OxmlElement("w:pBdr")
            for side, color, sz in (("w:top", top, "12"), ("w:left", left, "24")):
                if color:
                    e = OxmlElement(side)
                    for k, v in (("w:val", "single"), ("w:sz", sz), ("w:space", "4"), ("w:color", color)):
                        e.set(qn(k), v)
                    bdr.append(e)
            ppr.append(bdr)
        shd = OxmlElement("w:shd")
        for k, v in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", fill)):
            shd.set(qn(k), v)
        ppr.append(shd)
        p.paragraph_format.left_indent = Cm(0.25)
        p.paragraph_format.right_indent = Cm(0.25)

    def bottom_rule(p, color="1B1B1B", sz="12"):
        bdr = OxmlElement("w:pBdr")
        e = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", sz), ("w:space", "6"), ("w:color", color)):
            e.set(qn(k), v)
        bdr.append(e)
        ppr_add(p, bdr)

    def page_break():
        d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def add_figure(f):
        if not f:
            return
        p = d.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(0)
        w = min(text_w - 1.5, 11.5)
        if f.get("size") and f["size"][1] / f["size"][0] > 0.62:      # 세로로 긴 화면은 높이로 제한
            w = min(w, 9.0 * f["size"][0] / f["size"][1])
        p.add_run().add_picture(str(f["img"]), width=Cm(w))
        cap = d.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        styled_run(cap, f"그림 {f['num']}  ", size=8, bold=True, color=ACCENT, font=KO_SANS)
        styled_run(cap, f["caption"], size=8, color=MUTED, font=KO_SANS)
        cap.paragraph_format.space_after = Pt(9)

    def add_table(b):
        tb = d.add_table(rows=1, cols=len(b["head"]))
        tb.alignment = WD_TABLE_ALIGNMENT.CENTER
        tb.autofit = False
        hdr = tb.rows[0]
        trpr = hdr._tr.get_or_add_trPr()
        th = OxmlElement("w:tblHeader")
        th.set(qn("w:val"), "true")
        trpr.append(th)
        for i, h in enumerate(b["head"]):
            pp = hdr.cells[i].paragraphs[0]
            styled_run(pp, h, size=8, bold=True, font=KO_SANS)
            bottom_rule(pp, sz="8")
        for row in b["rows"]:
            cells = tb.add_row().cells
            for i, rs in enumerate(row):
                pp = cells[i].paragraphs[0]
                pp.paragraph_format.space_after = Pt(1)
                add_runs(pp, rs, size=8.5, font=KO_SANS)
        scale = text_w / sum(b.get("widths") or [text_w])
        for row in tb.rows:
            for i, w in enumerate(b.get("widths") or []):
                row.cells[i].width = Cm(w * scale)
        d.add_paragraph()

    def box(title, paras, fill, color, left=False, bullets=False):
        p = d.add_paragraph()
        styled_run(p, title, size=8, bold=True, color=RGBColor.from_string(color), font=KO_SANS, spacing=30)
        shade(p, fill, left=color if left else None, top=None if left else color)
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.keep_with_next = True
        for i, rs in enumerate(paras):
            q = d.add_paragraph()
            add_runs(q, ([("text", "· ")] if bullets else []) + rs, size=8.8, font=KO_SANS)
            shade(q, fill, left=color if left else None)
            q.paragraph_format.space_after = Pt(0 if i < len(paras) - 1 else 8)
            q.paragraph_format.keep_with_next = i < len(paras) - 1

    LIST_STYLES = ["List Bullet", "List Bullet 2", "List Bullet 3"]
    for b in blocks:
        t = b["t"]
        if t == "cover":
            # 표지: 그림(표지 PNG)이 있으면 여백 없는 첫 구역에 쪽 가득, 없으면 글자 표지
            if cover_png and cover_png.exists():
                cs = d.sections[0]
                cs.left_margin = cs.right_margin = cs.top_margin = cs.bottom_margin = Cm(0)
                cs.header_distance = cs.footer_distance = Cm(0)
                cp = d.paragraphs[0] if d.paragraphs else d.add_paragraph()
                cp.paragraph_format.space_after = Pt(0)
                cp.paragraph_format.line_spacing = 1.0
                cp.add_run().add_picture(str(cover_png), width=Cm(BOOK_W / 10), height=Cm(BOOK_H / 10 - 0.05))
            else:
                for _ in range(10):
                    d.add_paragraph()
                p = d.add_paragraph()
                styled_run(p, "CHART STUDY NOTES", size=8, color=MUTED, font=KO_SANS, spacing=60)
                p = d.add_paragraph()
                styled_run(p, b["title"], size=30, color=INK, font=KO_SANS)
                p = d.add_paragraph()
                styled_run(p, b["subtitle"], size=9.5, color=MUTED, font=KO_SANS)
            ns = d.add_section(WD_SECTION.NEW_PAGE)
            ns.left_margin, ns.right_margin = Cm(1.9), Cm(1.7)
            ns.top_margin, ns.bottom_margin = Cm(2.1), Cm(2.2)
            ns.header_distance, ns.footer_distance = Cm(1.1), Cm(1.1)
            ns.page_width, ns.page_height = Cm(BOOK_W / 10), Cm(BOOK_H / 10)
            continue
        elif t == "notice":
            for _ in range(16):
                d.add_paragraph()
            p = d.add_paragraph()
            styled_run(p, b["title"], size=13, bold=True, font=KO_SANS)
            bottom_rule(p, color="CFCAC0", sz="6")
            for line in b["paras"]:
                p = d.add_paragraph()
                p.paragraph_format.space_after = Pt(4)
                styled_run(p, line, size=8.5, color=RGBColor(0x44, 0x44, 0x44), font=KO_SANS)
        elif t == "study":
            page_break()
            p = d.add_paragraph()
            styled_run(p, b["title"], size=20, bold=True, font=KO_SANS)
            p.paragraph_format.space_after = Pt(18)
            for i, rs in enumerate(b["items"], 1):
                p = d.add_paragraph()
                p.paragraph_format.left_indent = Cm(1.1)
                p.paragraph_format.first_line_indent = Cm(-1.1)
                p.paragraph_format.space_after = Pt(10)
                styled_run(p, f"{i:02d}\t", size=12, bold=True, color=ACCENT2, font=KO_SANS)
                add_runs(p, rs, size=10.5)
                bottom_rule(p, color="EBE7DF", sz="4")
        elif t == "toc":
            page_break()
            p = d.add_paragraph()
            styled_run(p, "차례", size=20, bold=True, font=KO_SANS)
            p.paragraph_format.space_after = Pt(14)
            for lv, num, tx, a in b["entries"]:
                p = d.add_paragraph()
                if lv == 1:
                    p.paragraph_format.space_before = Pt(10)
                    p.paragraph_format.space_after = Pt(2)
                    p.paragraph_format.keep_with_next = True
                    styled_run(p, (num + "   ") if num else "", size=10.5, bold=True, color=ACCENT2, font=KO_SANS)
                    anchor_run(p, tx, a, size=10.5, color=INK, bold=True, font=KO_SANS)
                else:
                    p.paragraph_format.left_indent = Cm(0.9)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1.25
                    styled_run(p, num + "  ", size=8.5, color=MUTED, font=KO_SANS)
                    anchor_run(p, tx, a, size=8.5, color=RGBColor(0x3A, 0x3A, 0x3A), font=KO_SANS)
        elif t in ("chapter", "back"):
            page_break()
            p = d.add_paragraph()
            p.paragraph_format.space_before = Pt(40)
            label = "CHAPTER" if t == "chapter" else (b["label"] or " ")
            styled_run(p, label, size=9, bold=True, color=ACCENT2, font=KO_SANS, spacing=80)
            if t == "chapter" and b["num"]:
                p = d.add_paragraph()
                p.paragraph_format.space_after = Pt(0)
                styled_run(p, b["num"], size=60, bold=True, color=ACCENT, font=KO_SANS)
            h = d.add_heading(b["title"], level=1)
            bottom_rule(h)
            add_bookmark(h, b["id"])
            if t == "chapter":
                if b["intro"]:
                    p = d.add_paragraph()
                    p.paragraph_format.space_before = Pt(6)
                    p.paragraph_format.space_after = Pt(16)
                    add_runs(p, b["intro"], size=10.5)
                p = d.add_paragraph()
                styled_run(p, "이 장의 강의", size=7.5, bold=True, color=MUTED, font=KO_SANS, spacing=40)
                for n, tx, a in b["lessons"]:
                    p = d.add_paragraph()
                    p.paragraph_format.space_after = Pt(1)
                    bottom_rule(p, color="ECE8E0", sz="4")
                    styled_run(p, n + "   ", size=8.6, bold=True, color=ACCENT2, font=KO_SANS)
                    anchor_run(p, tx, a, size=8.6, color=INK, font=KO_SANS)
                if b["btc"]:
                    d.add_paragraph()
                    box("BTC에 쓸 때", [b["btc"]], "F7F1E8", "C0603A")
        elif t == "lesson":
            page_break()
            p = d.add_paragraph()
            styled_run(p, f"LESSON {b['num']}", size=8, bold=True, color=ACCENT2, font=KO_SANS, spacing=60)
            bottom_rule(p, color="CFCAC0", sz="4")
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
            h = d.add_heading(b["title"], level=2)
            add_bookmark(h, b["id"])
            p = d.add_paragraph()
            styled_run(p, (b["series"] + " · " if b["series"] else "") + f"원본 강의 {b['src']}", size=7.5, color=RGBColor(0x9A, 0x9A, 0x9A), font=KO_SANS)
            p.paragraph_format.space_after = Pt(10)
        elif t == "h4":
            h = d.add_heading("■ " + b["text"], level=3)
            if b["kind"] in ("빠진 내용", "보강 설명"):
                for r in h.runs:
                    r.font.color.rgb = ACCENT2
        elif t == "h3":
            h = d.add_heading(b["text"], level=3)
            for r in h.runs:
                r.font.color.rgb = ACCENT2
                r.font.size = Pt(12)
        elif t == "para":
            p = d.add_paragraph()
            if b.get("cls") == "note":
                add_runs(p, b["runs"], size=8.8, font=KO_SANS)
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                add_runs(p, b["runs"])
        elif t == "list":
            small = 9.3 if b["kind"] in ("용어", "기타") else None
            for dep, rs, fig in b["items"]:
                p = d.add_paragraph(style=LIST_STYLES[min(dep, 2)])
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                p.paragraph_format.space_after = Pt(2)
                add_runs(p, rs, size=small if dep == 0 else (small or 9.4))
                add_figure(fig)
        elif t == "figure":
            add_figure(b)
        elif t == "box":
            fill, color, left = {"bot": ("EEF3F4", "1F4E5F", False), "fix": ("F1F5EA", "6B8A3A", True)}.get(
                b["kind"], ("F5F5F5", "6A6A6A", True))
            box(b["title"], b["paras"], fill, color, left=left, bullets=b.get("bullets", False))
        elif t == "review":
            d.add_paragraph()
            tb = d.add_table(rows=1, cols=1)
            tb.style = "Table Grid"
            cell = tb.rows[0].cells[0]
            cp = cell.paragraphs[0]
            styled_run(cp, "확인 문제", size=11, bold=True, font=KO_SANS)
            if b["has_answers"]:
                styled_run(cp, "    정답과 해설은 책 뒤에", size=7.5, color=MUTED, font=KO_SANS)
            cp.paragraph_format.space_after = Pt(6)
            for i, q in enumerate(b["items"], 1):
                p = cell.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.6)
                p.paragraph_format.first_line_indent = Cm(-0.6)
                p.paragraph_format.space_after = Pt(4)
                styled_run(p, f"{i}\t", size=10, bold=True, color=ACCENT2, font=KO_SANS)
                add_runs(p, q, size=9.8)
            d.add_paragraph()
        elif t == "answers":
            page_break()
            for cnum, cname, items in b["groups"]:
                p = d.add_paragraph()
                p.paragraph_format.space_before = Pt(12)
                p.paragraph_format.keep_with_next = True
                styled_run(p, (cnum + "  ") if cnum else "", size=11, bold=True, color=ACCENT2, font=KO_SANS)
                styled_run(p, cname, size=11, bold=True, font=KO_SANS)
                bottom_rule(p, color="CFCAC0", sz="4")
                for i, (q, a, refs) in enumerate(items, 1):
                    p = d.add_paragraph()
                    p.paragraph_format.space_before = Pt(4)
                    p.paragraph_format.space_after = Pt(1)
                    p.paragraph_format.keep_with_next = True
                    styled_run(p, f"{i}  ", size=9.2, bold=True, color=ACCENT2, font=KO_SANS)
                    add_runs(p, [("bold", r[1]) if r[0] == "text" else r for r in q], size=9.2, font=KO_SANS)
                    p = d.add_paragraph()
                    p.paragraph_format.left_indent = Cm(0.55)
                    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                    add_runs(p, a + ([("text", "  ")] + refs if refs else []), size=9.4)
        elif t == "table":
            add_table(b)

    # 머리글·바닥글: 홀수쪽은 오른쪽, 짝수쪽은 왼쪽(바깥쪽)에 쪽 번호. 표지에는 넣지 않는다.
    sec = d.sections[-1]
    if len(d.sections) > 1:
        for hf in (sec.header, sec.even_page_header, sec.footer, sec.even_page_footer):
            hf.is_linked_to_previous = False
    else:
        sec.different_first_page_header_footer = True

    def page_field(p):
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), "PAGE")
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), "17")
        rpr.append(sz)
        r.append(rpr)
        tt = OxmlElement("w:t")
        tt.text = "1"
        r.append(tt)
        fld.append(r)
        p._p.append(fld)

    for hf, align, text in ((sec.header, WD_ALIGN_PARAGRAPH.RIGHT, "CHART STUDY NOTES"),
                            (sec.even_page_header, WD_ALIGN_PARAGRAPH.LEFT, None)):
        p = hf.paragraphs[0]
        p.alignment = align
        styled_run(p, text or next((b["title"] for b in blocks if b["t"] == "cover"), ""), size=7.5,
                   color=RGBColor(0x8A, 0x8A, 0x8A), font=KO_SANS, spacing=20)
    for hf, align in ((sec.footer, WD_ALIGN_PARAGRAPH.RIGHT), (sec.even_page_footer, WD_ALIGN_PARAGRAPH.LEFT)):
        p = hf.paragraphs[0]
        p.alignment = align
        page_field(p)

    tmp = path.with_suffix(".docx.part")
    d.save(str(tmp))
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# PDF (Playwright + 크롬/크로미움 — 없으면 건너뛴다)
# ---------------------------------------------------------------------------


MAC_CHROME = pathlib.Path("/Applications/Google Chrome.app")


def launch_browser(p):
    if sys.platform == "darwin" and MAC_CHROME.exists():
        try:
            return p.chromium.launch(channel="chrome")
        except Exception:  # noqa: BLE001 — 설치된 크롬을 못 쓰면 Playwright 크로미움으로
            pass
    return p.chromium.launch()


def render_cover_png(blocks: list, out: pathlib.Path) -> pathlib.Path | None:
    """워드 표지용 그림: 표지 SVG를 브라우저로 그려 PNG로 저장(약 300dpi)."""
    from playwright.sync_api import sync_playwright

    cover = next((b for b in blocks if b["t"] == "cover"), None)
    if cover is None:
        return None
    html_path, png = out / ".cover.html", out / f".cover_{cover.get('vol', 1)}.png"
    css = book_css(cover["title"])
    html_path.write_text(f'<!doctype html><html><head><meta charset="utf-8"><style>{css}'
                         f'html,body{{margin:0;background:#fff}}</style></head><body>'
                         f'{cover_svg(cover["title"], cover["subtitle"], cover["lessons"], cover.get("chapters", 10), cover.get("vol", 1))}'
                         f'</body></html>', encoding="utf-8")
    px_w, px_h = round(BOOK_W / 25.4 * 96), round(BOOK_H / 25.4 * 96)
    with sync_playwright() as p:
        browser = launch_browser(p)
        try:
            page = browser.new_page(viewport={"width": px_w, "height": px_h}, device_scale_factor=3.2)
            page.goto(html_path.as_uri(), wait_until="load")
            page.wait_for_timeout(300)
            page.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": px_w, "height": px_h})
        finally:
            browser.close()
    html_path.unlink(missing_ok=True)
    return png
UNAVAILABLE_MARKS = {"Private video": "비공개", "Video unavailable": "삭제·차단", "This video has been removed": "삭제",
                     "members-only": "회원 전용"}
MARK_RE = re.compile(r"@@(\d+)@@")
marker_ids: dict = {}   # 제목 id → 표식 번호(PDF 글자 추출이 '-' 같은 기호를 흘리지 않도록 숫자만 쓴다)


def write_pdf(blocks: list, html_path: pathlib.Path, pdf_path: pathlib.Path) -> bool:
    """2단계: ① 제목 표식을 넣어 렌더링 → 표식이 있는 쪽을 찾아 차례에 쪽 번호 → ② 최종 렌더링.
    pymupdf가 없으면 쪽 번호 없이 한 번만 렌더링한다. 차례에 쪽 번호를 넣었으면 True."""
    from playwright.sync_api import sync_playwright

    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # 옛 이름
        except ImportError:
            pymupdf = None

    tmp = pdf_path.with_suffix(".pdf.part")
    numbered = False
    with sync_playwright() as p:
        browser = launch_browser(p)
        try:
            page = browser.new_page()

            def render(markup: str):
                html_path.write_text(markup, encoding="utf-8")
                page.goto(html_path.as_uri(), wait_until="load", timeout=300_000)
                page.emulate_media(media="print")
                page.pdf(path=str(tmp), print_background=True, prefer_css_page_size=True)

            pages = {}
            if pymupdf is not None:
                render(render_html(blocks, markers=True))
                doc = pymupdf.open(str(tmp))
                back = {v: k for k, v in marker_ids.items()}
                for i, pg in enumerate(doc):
                    for num in MARK_RE.findall(re.sub(r"\s+", "", pg.get_text())):
                        if int(num) in back:
                            pages.setdefault(back[int(num)], i + 1)
                doc.close()
                numbered = bool(pages)
            render(render_html(blocks, pages=pages))
        finally:
            browser.close()
    os.replace(tmp, pdf_path)
    return numbered


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
    ap.add_argument("--volume", default="all", choices=["all", "1", "2", "3", "4"],
                    help="만들 권: 1 초급, 2 중급, 3 실전, 4 해외선물, all 전부(기본)")
    ap.add_argument("--fonts-dir", type=pathlib.Path, default=None,
                    help="책 글꼴 폴더(기본: ~/.chartpro_textbook_fonts, 맥 스크립트가 받아 둔다)")
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
    global FONTS_DIR
    if args.fonts_dir:
        FONTS_DIR = args.fonts_dir.expanduser()

    out = args.out.expanduser().resolve()
    if out == REPO or REPO in out.parents:
        print(f"거부: 결과 폴더가 저장소 안입니다({out}). 저장소는 공개라 캡처를 두면 안 됩니다.")
        return 2
    img_dir = out / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    lessons = parse_notes()
    n_sup = load_supplements(lessons, args.supplements_dir.expanduser())
    manifest = load_manifest(out)
    wanted = sorted(VOLUMES) if args.volume == "all" else [int(args.volume)]
    books = []
    for vol in wanted:
        cfg_path, base = VOLUMES[vol]
        if not cfg_path.exists():
            if args.volume != "all":
                print(f"{vol}권 구성 파일이 없습니다: {cfg_path}")
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        vids = list(dict.fromkeys(v for ch in cfg["chapters"] for v in ch["videos"] if v in lessons))
        books.append((vol, base, cfg, vids))
    if not books:
        print("만들 권이 없습니다.")
        return 1

    if args.check:
        any_lacking = False
        for vol, base, cfg, vids in books:
            total = have = 0
            lacking = []
            for vid in vids:
                secs = capture_points(lessons[vid])
                miss = [s for s in secs if not (img_dir / shot_name(vid, s)).exists()]
                total += len(secs)
                have += len(secs) - len(miss)
                if miss:
                    lacking.append((vid, len(secs) - len(miss), len(secs)))
            print(f"[{vol}권] {cfg['title']}: 캡처 {have}/{total}장 (영상 {len(vids)}편 중 덜 된 영상 {len(lacking)}편)")
            for vid, h, t in lacking:
                gone = manifest.get(vid, {}).get("unavailable")
                print(f"  - {lessons[vid]['title'][:40]}  {h}/{t}  ({vid})" + (f"  ※ 유튜브 {gone} 영상" if gone else ""))
            for name in (base + ".pdf", base + ".docx"):
                print(f"  {name}: {'있음' if (out / name).exists() else '없음'}")
            any_lacking = any_lacking or any(not manifest.get(v, {}).get("unavailable") for v, _, _ in lacking)
        print("모두 완료" if not any_lacking else "덜 된 영상은 같은 명령을 다시 실행하면 이어서 받습니다.")
        return 0

    failed = []
    if not args.no_video:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:  # noqa: BLE001
            print(f"캡처 도구(imageio-ffmpeg)를 못 찾아 캡처를 건너뜁니다: {exc}")
            ffmpeg = None
        all_vids = list(dict.fromkeys(v for _, _, _, vids in books for v in vids))
        targets = [v for v in all_vids if not args.only or v in args.only] if ffmpeg else []
        for i, vid in enumerate(targets, 1):
            secs = capture_points(lessons[vid])
            entry = manifest.setdefault(vid, {})
            if entry.get("unavailable") and args.recapture != "all":
                print(f"[{i}/{len(targets)}] {lessons[vid]['title'][:40]} — 건너뜀 (유튜브에서 볼 수 없는 영상: "
                      f"{entry['unavailable']})", flush=True)
                continue
            redo = {s for s in secs if (img_dir / shot_name(vid, s)).exists()
                    and needs_recapture(s, entry, args.recapture)}
            need = [s for s in secs if s in redo or not (img_dir / shot_name(vid, s)).exists()]
            ok, err = capture_video(vid, secs, img_dir, out / ".tmp", args.browser, redo, entry)
            dups = mark_duplicates(vid, secs, img_dir, entry, ffmpeg)
            save_manifest(out, manifest)
            note = f", 같은 화면 {len(dups)}장 생략" if dups else ""
            print(f"[{i}/{len(targets)}] {lessons[vid]['title'][:40]} — 캡처 {ok}/{len(secs)}"
                  + (f" (새로 {len(need)})" if need else "") + note + (f"  ({err})" if err else ""), flush=True)
            gone = next((k for k in UNAVAILABLE_MARKS if err and k in err), None)
            if gone:                       # 비공개·삭제 영상: 기억해 두고 다음부터 건너뛴다(--recapture all 이면 다시 시도)
                entry["unavailable"] = UNAVAILABLE_MARKS[gone]
                save_manifest(out, manifest)
                print("    → 유튜브에서 볼 수 없는 영상이라 다음부터 건너뜁니다. 책에는 글만 들어갑니다.", flush=True)
            elif err:
                failed.append(vid)
            if need:
                time.sleep(1)

    try:
        prepare_fonts(FONTS_DIR)
    except Exception as exc:  # noqa: BLE001 — 변환 실패 시 시스템 글꼴로
        print(f"글꼴 변환 실패: {type(exc).__name__}")
    nf = fonts_found(FONTS_DIR)
    print(f"\n글꼴: {nf}/{len(FONT_FILES)}개 찾음" + ("" if nf == len(FONT_FILES) else f" ({FONTS_DIR} — 없는 글꼴은 시스템 글꼴로 대신)"))

    made_pdfs = []
    for vol, base, cfg, vids in books:
        blocks, n, missing = build_model(cfg, lessons, img_dir, manifest, vol=vol)
        html_path = out / f"{base}.html"
        html_path.write_text(render_html(blocks), encoding="utf-8")
        shots = sum(1 for v in vids for s in capture_points(lessons[v]) if (img_dir / shot_name(v, s)).exists())
        print(f"\n[{vol}권] {cfg['title']} — 강의 {n}편, 캡처 {shots}장")
        if not args.no_docx:
            cover_png = None
            try:
                cover_png = render_cover_png(blocks, out)
            except Exception as exc:  # noqa: BLE001 — 표지 그림이 없으면 글자 표지로
                print(f"  워드 표지 그림은 건너뜀: {type(exc).__name__}")
            try:
                write_docx(blocks, out / f"{base}.docx", cover_png)
                print(f"  워드: {out / (base + '.docx')}")
            except ImportError:
                print("  워드 파일은 건너뜀: python-docx가 설치되어 있지 않습니다 (맥 실행 스크립트를 쓰면 자동 설치).")
            except Exception as exc:  # noqa: BLE001
                print(f"  워드 파일 만들기 실패: {type(exc).__name__}: {exc}")
        if not args.no_pdf:
            try:
                numbered = write_pdf(blocks, html_path, out / f"{base}.pdf")
                made_pdfs.append(out / f"{base}.pdf")
                print(f"  PDF: {out / (base + '.pdf')}" + ("" if numbered else "  (차례 쪽 번호 없음: pymupdf 미설치)"))
            except ImportError:
                print("  PDF는 건너뜀: playwright가 설치되어 있지 않습니다 (맥 실행 스크립트를 쓰면 자동 설치).")
            except Exception as exc:  # noqa: BLE001
                print(f"  PDF 만들기 실패: {type(exc).__name__}: {str(exc)[:300]}")
                print("  브라우저가 없다는 메시지면: 가상환경 파이썬으로 'python -m playwright install chromium' 실행 후 다시.")
        if missing:
            print("  노트에 없는 영상:", ", ".join(missing))

    if failed:
        print(f"\n캡처가 덜 된 영상 {len(failed)}개 — 다시 실행하면 빠진 것만 이어서 받습니다.")
        print("계속 실패하면 크롬에 유튜브 로그인 후: --browser chrome 을 붙여 실행하세요.")
    if args.open and sys.platform == "darwin":
        target = made_pdfs[0] if len(made_pdfs) == 1 else out
        subprocess.run(["open", str(target)], check=False)
    return 0



if __name__ == "__main__":
    sys.exit(main())
