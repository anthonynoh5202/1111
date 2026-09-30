"""서버 전용 제어 파일(정지·해제) 읽기 — 설계 담당 소유 (DESIGN §7.3).

- 파일은 프로세스 B에만 **읽기 전용**으로 마운트한다(A·텔레그램에는 없음). 사람이 서버에서 SSH로만 고친다.
- 킬 스위치 T0 해제는 이 파일의 ``[[release]] halt_id = N`` 으로만 된다. DB의 해제 기록(order_halt_releases)은
  기록일 뿐 판정에 쓰지 않는다(A가 DB에 해제 행을 위조해도 효과 없음).
- fail-closed: 파일이 없거나, 권한이 넓거나(그룹·기타 쓰기), 형식이 틀리면 ``manual_halt=True``(신규 진입 차단)로 본다.
- 해제는 T0 행에 묶인다(F8): B는 해제 id를 **그 T0가 생긴 뒤에 처음 본 경우에만** 인정한다(게이트웨이·B 원장). ``at``을 적으면
  (권장) 그 시각이 T0 시각보다 이르면 무시한다 — DB 복원·재생성 뒤 옛 제어 파일의 같은 번호가 새 T0를 풀지 못하게.

형식(TOML)::

    halt = false                       # true = 수동 정지(신규 진입 차단, 보유 포지션의 손절은 유지)
    [[release]]
    halt_id = 3
    at = "2026-10-01T09:00:00Z"
    reason = "손절 누락 원인(데모 점검) 확인 후 해제"
"""
from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MAX_CONTROL_BYTES = 64 * 1024


@dataclass(frozen=True)
class ControlState:
    manual_halt: bool
    released: frozenset[int] = field(default_factory=frozenset)
    error: str | None = None            # 읽기·형식 오류 요약(있으면 manual_halt=True)
    ref: str = ""                       # 해제 근거(파일 경로·수정 시각) — order_halt_releases.control_ref
    release_at: tuple[tuple[int, int], ...] = ()   # (halt_id, at의 epoch ms) — at을 적은 해제만


def _at_ms(v: object) -> int | None:
    """TOML at 값(문자열 ISO-8601 또는 TOML 날짜시각) → epoch ms. 시간대가 없으면 UTC로 본다. 형식 오류면 None."""
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def parse_control(text: str, *, ref: str = "") -> ControlState:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
        return ControlState(True, frozenset(), f"toml:{type(exc).__name__}", ref)
    unknown = set(data) - {"halt", "release"}
    if unknown:
        return ControlState(True, frozenset(), f"unknown_keys:{sorted(unknown)}", ref)
    halt = data.get("halt", False)
    if not isinstance(halt, bool):
        return ControlState(True, frozenset(), "halt_not_bool", ref)
    rel = data.get("release", [])
    if not isinstance(rel, list):
        return ControlState(True, frozenset(), "release_not_list", ref)
    ids: set[int] = set()
    ats: dict[int, int] = {}
    for item in rel:
        if not isinstance(item, dict) or set(item) - {"halt_id", "at", "reason"}:
            return ControlState(True, frozenset(), "release_item_invalid", ref)
        hid = item.get("halt_id")
        reason = item.get("reason")
        if isinstance(hid, bool) or not isinstance(hid, int) or hid <= 0:
            return ControlState(True, frozenset(), "release_halt_id_invalid", ref)
        if not isinstance(reason, str) or not reason.strip():
            return ControlState(True, frozenset(), "release_reason_required", ref)
        if "at" in item:
            at = _at_ms(item["at"])
            if at is None:
                return ControlState(True, frozenset(), "release_at_invalid", ref)
            ats[hid] = min(at, ats.get(hid, at))
        ids.add(hid)
    return ControlState(bool(halt), frozenset(ids), None, ref, tuple(sorted(ats.items())))


def load_control(path: str | os.PathLike[str]) -> ControlState:
    """제어 파일 읽기. 문제가 있으면 manual_halt=True(오류 사유 포함)."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return ControlState(True, frozenset(), "missing", str(p))
    ref = f"{p}@{int(st.st_mtime)}"
    if not stat.S_ISREG(st.st_mode):
        return ControlState(True, frozenset(), "not_regular_file", ref)
    if st.st_mode & 0o022:
        return ControlState(True, frozenset(), "writable_by_others", ref)
    if st.st_size > MAX_CONTROL_BYTES:
        return ControlState(True, frozenset(), "too_large", ref)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ControlState(True, frozenset(), f"read:{type(exc).__name__}", ref)
    return parse_control(text, ref=ref)
