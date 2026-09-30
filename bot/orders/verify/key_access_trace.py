"""검증 V3 — 거래 키가 A(분석·텔레그램) 쪽 어디에서도 읽히지 않는가: OS 수준 파일 접근 추적(strace) (독립 검증관).

배치 흉내: compose에서 bot.toml은 A·B가 **같은 파일**이고 키 경로(/run/secrets/binance_*)는 B 컨테이너에만 있다.
여기서는 같은 설정 내용을 두 벌 쓰되 키 경로만 다르게 한다 — A 설정의 키 경로에는 파일이 없고(A 컨테이너 관점),
B 설정의 키 경로에는 실제 Ed25519 PEM·키 ID가 있다(B 컨테이너 관점).

측정(각각 strace -f, 파일 관련 시스템 호출 전부)
- A1: A `check` — A 관점 경로에 키 파일을 **일부러 둔** 경우: 시작 거부(종료 2) + 키 파일을 open하지 않고 lstat만.
- A2: A `check`·`run --dry-run` (정상 배치).
- A3: A 실동작 — 실제 load_config·load_secrets(텔레그램·Claude 비밀 읽기) → Engine → 카드 전송 → [승인]·[확인]
       (telegram_ui.handle_callback) → 큐 → **실제 B 자식 프로세스**(키를 읽는 실물 경로 + 가짜 거래소)가 진입·손절 →
       A가 outbox 전송·/status → exit 요청 → B 청산 → A 전송. A 프로세스만 추적.
- B0(양성 대조): 같은 흐름에서 B 자식을 추적 → 키 두 파일을 open(O_RDONLY) 하는 것이 **보여야** 한다(추적이 헛돌지 않음).
- A4: A 쪽 시험 모음 전체(bot/tests, 약 500개) — 어떤 A 코드도 키·제어·원장 파일을 읽기로 열지 않는다.
- 부가: B가 돈 뒤 DB 파일·A 로그·outbox·전송 텍스트에 키 ID·PEM 본문 문자열이 없는지.

실행: .venv/bin/python -m bot.orders.verify.key_access_trace  → results/key_access_trace.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets as pysecrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "results" / "key_access_trace.json"
PY = str(REPO / ".venv" / "bin" / "python")
SENSITIVE = re.compile(r"binance_api_key|binance_ed25519_private_key|orders_control|orders_ledger")
OPEN_RE = re.compile(r'^(\d+)\s+(?:\[pid\s+\d+\]\s+)?(openat|open|creat|openat2)\((?:AT_FDCWD|\d+|[^,]*),?\s*"([^"]*)",\s*([A-Z_|]+)')
ANY_RE = re.compile(r'^(\d+)\s+(\w+)\((?:AT_FDCWD,\s*)?"([^"]*)"')


def strace_cmd(out: Path) -> list[str]:
    return ["strace", "-f", "-qq", "-s", "256", "-e", "trace=%file", "-o", str(out)]


def parse_trace(path: Path, extra_sensitive: list[str]) -> dict[str, Any]:
    reads, writes, meta, benign = [], [], [], []
    opened_paths: set[str] = set()
    for line in path.read_text(errors="replace").splitlines():
        m = OPEN_RE.match(line)
        if m:
            p, flags = m.group(3), m.group(4)
            opened_paths.add(p)
            hit = SENSITIVE.search(p) or any(s and s in p for s in extra_sensitive)
            if hit and p.startswith(str(REPO / "config")) and p.endswith(".example.toml"):
                benign.append(p)             # 저장소의 견본 파일(비밀 아님 — A 시험의 비밀 스캔이 git 파일 전체를 읽음)
                continue
            if hit:
                rec = dict(syscall=m.group(2), path=p, flags=flags, result=line.rsplit("=", 1)[-1].strip())
                (writes if ("O_WRONLY" in flags or "O_CREAT" in flags) else reads).append(rec)
            continue
        m = ANY_RE.match(line)
        if m and (SENSITIVE.search(m.group(3)) or any(s and s in m.group(3) for s in extra_sensitive)):
            meta.append(dict(syscall=m.group(2), path=m.group(3), result=line.rsplit("=", 1)[-1].strip()))
    return dict(open_for_read=reads, open_for_write=writes, metadata_only=meta, benign_repo_templates=sorted(set(benign)),
                n_distinct_opened=len(opened_paths))


def write_secret(p: Path, data: bytes) -> None:
    p.write_bytes(data)
    os.chmod(p, 0o400)


def make_env(d: Path) -> tuple[Path, Path, dict[str, str]]:
    """A 설정·B 설정 파일과 비밀(A: 텔레그램·Claude 더미, B: 실제 Ed25519 PEM + 키 ID)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from bot.tests.conftest import ALLOWED_CHAT_ID, ALLOWED_USER_ID

    a_sec, b_sec, a_view = d / "a_secrets", d / "b_secrets", d / "a_view_of_run_secrets"
    for x in (a_sec, b_sec):
        x.mkdir(mode=0o700)
    a_view.mkdir(mode=0o700)          # A 컨테이너의 /run/secrets: 키 파일이 없다
    write_secret(a_sec / "telegram_bot_token", b"123456:TEST-dummy-token-not-real-abcdefghij\n")
    write_secret(a_sec / "anthropic_api_key", b"sk-ant-test-dummy-not-real\n")
    key_id = "VERIFYKEYID" + pysecrets.token_hex(16)
    pem = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption())
    write_secret(b_sec / "binance_api_key", key_id.encode() + b"\n")
    write_secret(b_sec / "binance_ed25519_private_key", pem)
    ctl = b_sec / "orders_control.toml"
    ctl.write_text("halt = false\n")
    os.chmod(ctl, 0o600)
    src = (REPO / "config" / "bot.testnet.example.toml").read_text(encoding="utf-8")
    common = {
        '"/data/testnet.sqlite3"': f'"{d}/testnet.sqlite3"',
        "allowed_user_id = 0": f"allowed_user_id = {ALLOWED_USER_ID}",
        "allowed_chat_id = 0": f"allowed_chat_id = {ALLOWED_CHAT_ID}",
        "r_capital_usdt = 1000.0": "r_capital_usdt = 10000.0",
        "max_notional_usdt = 1000.0": "max_notional_usdt = 10000.0",
        "loop_interval_s = 2.0": "loop_interval_s = 0.5",
        "reconcile_interval_s = 10": "reconcile_interval_s = 5",
    }

    def render(view: Path, tg_dir: Path) -> str:
        s = src
        for a, b in common.items():
            s = s.replace(a, b)
        return (s.replace('"/run/secrets/binance_api_key"', f'"{view}/binance_api_key"')
                .replace('"/run/secrets/binance_ed25519_private_key"', f'"{view}/binance_ed25519_private_key"')
                .replace('"/control/orders_control.toml"', f'"{view}/orders_control.toml"')
                .replace('"/state/orders_ledger.json"', f'"{view}/orders_ledger.json"')
                .replace('"/run/secrets/telegram_bot_token"', f'"{tg_dir}/telegram_bot_token"')
                .replace('"/run/secrets/anthropic_api_key"', f'"{tg_dir}/anthropic_api_key"'))

    a_cfg, b_cfg = d / "a_bot.toml", d / "b_bot.toml"
    a_cfg.write_text(render(a_view, a_sec))
    # B는 A 비밀(텔레그램 토큰)이 보이면 시작 거부 → B 관점의 텔레그램 경로는 없는 곳
    b_cfg.write_text(render(b_sec, d / "b_view_of_a_secrets"))
    return a_cfg, b_cfg, dict(key_id=key_id, pem_body=pem.decode().splitlines()[1], b_sec=str(b_sec),
                              a_view=str(a_view), a_sec=str(a_sec))


# ---------------------------------------------------------------------------
# A3: A 실동작(이 함수는 strace 아래 별도 프로세스로 돈다)
# ---------------------------------------------------------------------------


def a_flow(a_cfg: str, report: str) -> int:
    import asyncio

    from bot import db
    from bot import telegram_ui as tu
    from bot.config import load_config, load_secrets
    from bot.engine import Engine
    from bot.orders import queue
    from bot.tests.conftest import ALLOWED_CHAT_ID, ALLOWED_USER_ID, FakeTransport, insert_test_signal
    from bot.types import CallbackAction, Mode, SystemClock, make_callback_data

    class NoMarket:
        def daily_bars(self, until_ns):
            raise RuntimeError("no market in trace harness")

        minute_bars = funding = daily_bars

        def server_time_ns(self):
            return None

    cfg = load_config(a_cfg)
    secrets = load_secrets(cfg)                         # check_no_trading_keys + 텔레그램·Claude 비밀 읽기(실물 경로)
    clock = SystemClock()
    conn = db.connect(cfg.db_path, mode=Mode.TESTNET, now_ms=clock.now_ns() // 1_000_000)
    engine = Engine(conn, cfg, NoMarket(), None, clock)
    transport = FakeTransport()
    run = lambda coro: asyncio.new_event_loop().run_until_complete(coro)  # noqa: E731
    now_ns = clock.now_ns()
    sid = insert_test_signal(conn, decision_ns=now_ns - 60 * 10**9, mode=Mode.TESTNET)
    run(tu.send_outgoing(transport, engine, engine.unsent_cards()))
    mid = transport.sent[-1].message_id

    def press(action):
        ctx = tu.CallbackContext(callback_query_id=f"q{action.value}", update_id=1, from_user_id=ALLOWED_USER_ID,
                                 chat_id=ALLOWED_CHAT_ID, chat_type="private", message_id=mid,
                                 data=make_callback_data(action, sid))
        with engine.lock:
            return tu.handle_callback(engine, conn, cfg, ctx, clock.now_ns() // 1_000_000)

    press(CallbackAction.APPROVE)
    press(CallbackAction.CONFIRM)
    log: list[str] = [f"signal={db.get_signal(conn, sid)['state']} intent={queue.intent_for_signal(conn, sid)['state']}"]

    def wait(states, t=40.0):
        end = time.time() + t
        while time.time() < end:
            st = queue.intent_for_signal(conn, sid)["state"]
            if st in states:
                return st
            run(tu.send_outgoing(transport, engine, []))       # outbox(B 알림) 전송
            time.sleep(0.1)
        return queue.intent_for_signal(conn, sid)["state"]

    log.append("after_entry=" + wait({"STOP_VERIFIED", "REJECTED", "NOT_FILLED", "FAILED_FLATTENED"}))
    try:
        run(tu.send_outgoing(transport, engine, engine.tick()))
    except Exception as exc:  # noqa: BLE001
        log.append(f"tick:{type(exc).__name__}")
    n = clock.now_ns() // 1_000_000
    log.append(f"exit_requested={queue.request_exit(conn, sid, exit_signal_close_ms=n, exit_due_ms=n, now_ms=n)}")
    log.append("after_exit=" + wait({"CLOSED", "FAILED_FLATTENED", "HALTED"}))
    run(tu.send_outgoing(transport, engine, []))
    mods = sorted(m for m in sys.modules if m.startswith("bot.orders"))
    Path(report).write_text(json.dumps(dict(log=log, orders_modules_loaded=mods,
                                            sent_texts=[m.text for m in transport.sent],
                                            secrets_loaded=dict(tg=secrets.telegram_token is not None,
                                                                claude=secrets.anthropic_api_key is not None)),
                                       ensure_ascii=False))
    conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-flow", nargs=2)
    ap.add_argument("--skip-suite", action="store_true")
    a = ap.parse_args(argv)
    if a.a_flow:
        return a_flow(*a.a_flow)
    from multiprocessing.managers import BaseManager  # noqa: F401

    from bot.orders.verify.kill_restart_sim import AUTHKEY, HubManager  # noqa: F401

    res: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="keytrace-") as td:
        d = Path(td)
        a_cfg, b_cfg, info = make_env(d)
        extra = [info["b_sec"], info["a_view"] + "/binance"]
        clean_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(d), "PYTHONPATH": str(REPO),
                     "LANG": "C.UTF-8"}

        # A1: A 관점에 키 파일이 보이면 시작 거부 + 키 내용을 읽지 않는다
        leak = Path(info["a_view"]) / "binance_ed25519_private_key"
        write_secret(leak, b"-----BEGIN PRIVATE KEY-----\nplanted\n-----END PRIVATE KEY-----\n")
        t = d / "trace_A1.txt"
        p = subprocess.run(strace_cmd(t) + [PY, "-m", "bot.main", "--config", str(a_cfg), "check"], cwd=REPO,
                           env=clean_env, capture_output=True, text=True, timeout=120)
        res["A1_key_visible_to_A"] = dict(exit=p.returncode, stderr=p.stderr.strip()[-300:],
                                          trace=parse_trace(t, extra))
        leak.unlink()

        # A2: 정상 배치의 check / run --dry-run
        for cmd in (["check"], ["run", "--dry-run"]):
            t = d / f"trace_A2_{cmd[0]}.txt"
            p = subprocess.run(strace_cmd(t) + [PY, "-m", "bot.main", "--config", str(a_cfg), *cmd], cwd=REPO,
                               env=clean_env, capture_output=True, text=True, timeout=120)
            res[f"A2_{'_'.join(cmd)}"] = dict(exit=p.returncode, stdout=p.stdout.strip()[-300:],
                                               stderr=p.stderr.strip()[-300:], trace=parse_trace(t, extra))

        # A3 + B0: 실제 B 자식(키 파일 읽기 + 가짜 거래소)과 A 실동작 — 둘 다 추적(별도 파일)
        m = HubManager(address=("127.0.0.1", 0), authkey=AUTHKEY)
        m.start()
        hub = m.hub()
        hub.reset()
        # A가 DB를 먼저 만든다(B가 시작할 때 모드 확인)
        from bot import db
        from bot.types import Mode

        db.connect(d / "testnet.sqlite3", mode=Mode.TESTNET, now_ms=int(time.time() * 1000)).close()
        tb = d / "trace_B0.txt"
        blog = open(d / "b.log", "w")
        benv = dict(clean_env, VERIFY_LOAD_KEYS="1")
        bproc = subprocess.Popen(strace_cmd(tb) + [PY, "-m", "bot.orders.verify.kill_restart_sim", "--child",
                                                    f"127.0.0.1:{m.address[1]}", str(b_cfg)],
                                 cwd=REPO, env=benv, stdout=blog, stderr=blog)
        time.sleep(4.0)
        ta = d / "trace_A3.txt"
        rep = d / "a3.json"
        p = subprocess.run(strace_cmd(ta) + [PY, "-m", "bot.orders.verify.key_access_trace", "--a-flow", str(a_cfg),
                                             str(rep)], cwd=REPO, env=clean_env, capture_output=True, text=True,
                           timeout=300)
        bproc.terminate()
        try:
            bproc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            bproc.kill()
        st = hub.status()
        m.shutdown()
        a3 = json.loads(rep.read_text()) if rep.exists() else {}
        res["A3_a_process_live_flow"] = dict(exit=p.returncode, stderr=p.stderr.strip()[-500:], flow=a3.get("log"),
                                             orders_modules_loaded_in_A=a3.get("orders_modules_loaded"),
                                             secrets_loaded=a3.get("secrets_loaded"),
                                             exchange_posts=st["posts"], trace=parse_trace(ta, extra))
        res["B0_positive_control_b_process"] = dict(trace=parse_trace(tb, extra),
                                                    b_log_tail=(d / "b.log").read_text()[-600:])
        # 부가: 키 문자열이 DB·A 전송 텍스트·B 로그에 없는지
        blobs = {"db": b"".join(f.read_bytes() for f in d.glob("testnet.sqlite3*")),
                 "a_sent_texts": json.dumps(a3.get("sent_texts", []), ensure_ascii=False).encode(),
                 "b_log": (d / "b.log").read_bytes()}
        res["key_material_in_outputs"] = {k: (info["key_id"].encode() in v or info["pem_body"].encode() in v)
                                          for k, v in blobs.items()}

        # A4: A 쪽 시험 모음 전체
        if not a.skip_suite:
            t = d / "trace_A4.txt"
            p = subprocess.run(strace_cmd(t) + [PY, "-m", "pytest", "bot/tests", "-q", "-x", "-p",
                                                "no:cacheprovider"], cwd=REPO, env=clean_env, capture_output=True,
                               text=True, timeout=1500)
            tr = parse_trace(t, [])
            res["A4_a_side_test_suite"] = dict(exit=p.returncode, tail=p.stdout.strip().splitlines()[-1:],
                                               trace=dict(open_for_read=tr["open_for_read"],
                                                          n_open_for_write=len(tr["open_for_write"]),
                                                          n_metadata_only=len(tr["metadata_only"]),
                                                          benign_repo_templates=tr["benign_repo_templates"],
                                                          n_distinct_opened=tr["n_distinct_opened"]))

    def a_reads(k: str) -> list:
        return res.get(k, {}).get("trace", {}).get("open_for_read", [])

    verdict = dict(
        A1_refused=res["A1_key_visible_to_A"]["exit"] == 2 and not a_reads("A1_key_visible_to_A"),
        A2_no_key_reads=not a_reads("A2_check") and not a_reads("A2_run_--dry-run"),
        A3_no_key_reads=not a_reads("A3_a_process_live_flow"),
        A3_flow_completed=bool(res["A3_a_process_live_flow"]["flow"]) and
        "after_exit=CLOSED" in (res["A3_a_process_live_flow"]["flow"] or []),
        A3_no_binance_client_module=not any(x in (res["A3_a_process_live_flow"]["orders_modules_loaded_in_A"] or [])
                                            for x in ("bot.orders.binance_client", "bot.orders.worker",
                                                      "bot.orders.gateway")),
        B0_reads_both_keys=sum(1 for r in res["B0_positive_control_b_process"]["trace"]["open_for_read"]
                               if "binance_" in r["path"] and not r["result"].startswith("-1")) >= 2,
        A4_no_key_reads=("A4_a_side_test_suite" not in res) or not a_reads("A4_a_side_test_suite"),
        no_key_material_in_outputs=not any(res["key_material_in_outputs"].values()),
    )
    res["verdict"] = verdict
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=1))
    for k in ("A1_key_visible_to_A", "A2_check", "A2_run_--dry-run", "A3_a_process_live_flow",
              "B0_positive_control_b_process", "A4_a_side_test_suite"):
        if k in res:
            tr = res[k]["trace"]
            keyish = [r for r in tr["open_for_read"] if "binance_" in r["path"]]
            print(k, "exit", res[k].get("exit"), "| key-file opens for read:", keyish,
                  "| other sensitive opens:", len(tr["open_for_read"]) - len(keyish), "| metadata-only:",
                  sorted({(m["syscall"], Path(m["path"]).name) for m in tr["metadata_only"]})
                  if isinstance(tr.get("metadata_only"), list) else tr.get("n_metadata_only"))
    print("A3 flow", res["A3_a_process_live_flow"]["flow"], res["A3_a_process_live_flow"]["stderr"][-300:])
    return 0 if all(verdict.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
