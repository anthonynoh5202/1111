"""B 전용 원장(ledger) — 수정 담당 (SEC-02·SEC-04·F8, DESIGN §7.4).

A와 B는 같은 SQLite 파일을 쓰므로 A가 침해되면 DB의 무엇이든 바꿀 수 있다(트리거를 지웠다가 다시 만드는 것까지 — SEC-02).
그래서 **정지 판정과 누적 한도의 근거**는 B만 마운트하는 볼륨(/state)의 이 파일에 따로 남긴다. A는 이 파일을 볼 수 없다.

기록하는 것
- entries: B가 보낸 진입(신호 ID, 전송 시각) — UTC 하루 진입 상한(MAX_ENTRIES_PER_UTC_DAY)
- closes: B가 끝낸 보유(신호 ID, 시각, 청산 사유, 추정 실현 손익 USDT) — T1(24시간 손절 3회)·T2(하루 −3R)
- halts: B가 건 T0(id, 시각, 사유, 의도) — DB에서 지워져도 정지가 풀리지 않는다
- release_seen: 제어 파일의 해제 id를 **처음 본 시각** — 해제는 그 T0가 생긴 뒤에 처음 본 것만 인정(F8)
- tamper_ok: 사람이 해제로 확인한 DB 무결성 문제 서명(같은 문제로 T0를 반복하지 않게)

규칙
- path=None이면 메모리 전용(시험). 파일이면 쓸 때마다 원자적 교체(임시 파일 0600 → fsync → rename → 폴더 fsync).
- 읽기·쓰기 실패는 ``error``에 남긴다. 게이트웨이는 ``error``가 있으면 **신규 진입을 막는다**(fail-closed). 보유 손절·청산은 계속.
- 파일 권한이 그룹·기타에 열려 있거나(0o077), 형식이 틀리면 error(손상·변조 의심).
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable

LEDGER_VERSION = 1
MAX_LEDGER_BYTES = 4 * 1024 * 1024
KEEP_MS = 8 * 24 * 60 * 60 * 1000          # 이보다 오래된 진입·청산 기록은 정리(T1 24시간·하루 경계보다 충분히 길게)


class LedgerError(RuntimeError):
    pass


def _empty() -> dict[str, Any]:
    return {"version": LEDGER_VERSION, "entries": [], "closes": [], "halts": [], "release_seen": {},
            "tamper_ok": [], "tamper_halts": {}}


def _valid(d: Any) -> bool:
    if not isinstance(d, dict) or d.get("version") != LEDGER_VERSION:
        return False
    for k in ("entries", "closes", "halts", "tamper_ok"):
        if not isinstance(d.get(k), list):
            return False
    if not isinstance(d.get("release_seen"), dict) or not isinstance(d.setdefault("tamper_halts", {}), dict):
        return False
    try:
        for e in d["entries"]:
            str(e["sid"]), int(e["ts"])
        for c in d["closes"]:
            str(c["sid"]), int(c["ts"]), str(c["reason"])
            if c.get("pnl") is not None:
                float(c["pnl"])
        for h in d["halts"]:
            int(h["id"]), int(h["ts"]), str(h["reason"])
        for k, v in d["release_seen"].items():
            int(k), int(v)
        for t in d["tamper_ok"]:
            str(t)
        for k, v in d["tamper_halts"].items():
            int(k), [str(x) for x in v]
    except (KeyError, TypeError, ValueError):
        return False
    return True


class Ledger:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path else None
        self.error: str | None = None
        self._d = _empty()
        if self.path is not None:
            self._load()

    # ------------------------------------------------------------------
    # 파일
    # ------------------------------------------------------------------
    def _load(self) -> None:
        p = self.path
        assert p is not None
        try:
            st = p.lstat()
        except FileNotFoundError:
            if not p.parent.is_dir():
                self.error = "dir_missing"
                return
            try:
                self._save()                     # 첫 실행: 빈 원장을 만든다
            except LedgerError:
                pass
            return
        except OSError as exc:
            self.error = f"stat:{type(exc).__name__}"
            return
        if not stat.S_ISREG(st.st_mode):
            self.error = "not_regular_file"
            return
        if st.st_mode & 0o077:
            self.error = "permissions_too_open"
            return
        if st.st_size > MAX_LEDGER_BYTES:
            self.error = "too_large"
            return
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self.error = f"read:{type(exc).__name__}"
            return
        if not _valid(d):
            self.error = "corrupt"
            return
        self._d = d
        self.error = None

    def _save(self) -> None:
        if self.path is None:
            return
        p = self.path
        data = json.dumps(self._d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(prefix=".ledger-", dir=str(p.parent))
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, p)
            tmp = None
            try:
                dfd = os.open(str(p.parent), os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass
        except OSError as exc:
            self.error = f"write:{type(exc).__name__}"
            raise LedgerError(self.error) from None
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        if self.error is not None and self.error.startswith("write:"):
            self.error = None

    def _mutate_and_save(self, now_ms: int | None = None) -> None:
        if now_ms is not None:
            self._prune(int(now_ms))
        self._save()

    def _prune(self, now_ms: int) -> None:
        lo = now_ms - KEEP_MS
        self._d["entries"] = [e for e in self._d["entries"] if int(e["ts"]) >= lo]
        self._d["closes"] = [c for c in self._d["closes"] if int(c["ts"]) >= lo]

    # ------------------------------------------------------------------
    # 진입·청산(누적 한도)
    # ------------------------------------------------------------------
    def record_entry(self, signal_id: str, ts_ms: int) -> None:
        """진입 전송 **전에** 부른다. 저장 실패면 LedgerError(→ 보내지 않는다)."""
        if self.error is not None:
            raise LedgerError(self.error)
        self._d["entries"].append({"sid": str(signal_id), "ts": int(ts_ms)})
        self._mutate_and_save(ts_ms)

    def entries(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self._d["entries"]]

    def record_close(self, signal_id: str, ts_ms: int, reason: str, pnl_usdt: float | None) -> None:
        """보유 종료 기록(신호당 한 번). 실패는 error에 남기고 LedgerError."""
        if any(c["sid"] == str(signal_id) for c in self._d["closes"]):
            return
        self._d["closes"].append({"sid": str(signal_id), "ts": int(ts_ms), "reason": str(reason),
                                  "pnl": None if pnl_usdt is None else float(pnl_usdt)})
        self._mutate_and_save(ts_ms)

    def closes(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self._d["closes"]]

    # ------------------------------------------------------------------
    # T0
    # ------------------------------------------------------------------
    def record_halt(self, halt_id: int, ts_ms: int, reason: str, intent_id: int | None) -> None:
        self._d["halts"].append({"id": int(halt_id), "ts": int(ts_ms), "reason": str(reason),
                                 "intent": None if intent_id is None else int(intent_id)})
        self._save()

    def halts(self) -> list[dict[str, Any]]:
        return [dict(h) for h in self._d["halts"]]

    def release_first_seen(self, halt_id: int, now_ms: int) -> int:
        """제어 파일 해제 id를 처음 본 시각(없으면 지금으로 기록). 저장 실패는 error에만 남긴다."""
        k = str(int(halt_id))
        seen = self._d["release_seen"].get(k)
        if seen is None:
            self._d["release_seen"][k] = int(now_ms)
            try:
                self._save()
            except LedgerError:
                pass
            return int(now_ms)
        return int(seen)

    def forget_release_seen(self, keep: Iterable[int]) -> None:
        """제어 파일에서 사라진 해제 id의 '처음 본 시각'을 지운다(다시 적으면 그때 새로 본 것으로)."""
        keep_s = {str(int(x)) for x in keep}
        drop = [k for k in self._d["release_seen"] if k not in keep_s]
        if drop:
            for k in drop:
                del self._d["release_seen"][k]
            try:
                self._save()
            except LedgerError:
                pass

    # ------------------------------------------------------------------
    # DB 무결성 문제(사람이 확인한 것)
    # ------------------------------------------------------------------
    def tamper_accepted(self, signature: str) -> bool:
        return signature in self._d["tamper_ok"]

    def note_tamper_halt(self, halt_id: int, signatures: Iterable[str]) -> None:
        """변조 T0와 그 문제 서명을 묶어 둔다(그 T0가 해제되면 서명을 확인된 것으로)."""
        k = str(int(halt_id))
        cur = self._d["tamper_halts"].setdefault(k, [])
        add = [s for s in signatures if s not in cur]
        if add:
            cur.extend(add)
            try:
                self._save()
            except LedgerError:
                pass

    def tamper_halts(self) -> dict[int, list[str]]:
        return {int(k): list(v) for k, v in self._d["tamper_halts"].items()}

    def accept_tamper(self, signatures: Iterable[str]) -> None:
        new = [s for s in signatures if s not in self._d["tamper_ok"]]
        if new:
            self._d["tamper_ok"].extend(new)
            try:
                self._save()
            except LedgerError:
                pass
