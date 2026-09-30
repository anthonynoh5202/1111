"""검증 V1 — 실제 프로세스 강제 종료(SIGKILL)·재시작 시뮬레이션 (독립 검증관).

시험 모음(test_e2e_testnet_sim.py)의 '강제 종료'는 같은 프로세스 안에서 예외로 흉내 낸 것이다. 여기서는
- 가짜 거래소(FakeExchange, **실시간 SystemClock**)를 별도 서버 프로세스(multiprocessing BaseManager)에 두고,
- 주문 프로세스 B를 **진짜 자식 프로세스** ``bot.orders.worker.main(run)``으로 띄워(설정 파일·제어 파일·원장·단일 실행
  잠금·SQLite WAL 파일 전부 실물, 거래소 클라이언트만 원격 가짜로 주입),
- 거래소 서버 쪽에서 지정한 호출 **직전/직후**(요청이 거래소에서 처리된 뒤 응답이 돌아가기 전)에 ``os.kill(pid, SIGKILL)``,
- 정해진 중단 시간 뒤 새 프로세스로 재시작(compose ``restart: unless-stopped`` 흉내),
- 거래소 프로세스 안의 감시 스레드가 2ms마다 '롱 포지션 + 우리 closePosition 손절 없음(무방비)' 구간을 실시간으로 잰다.

A(분석·텔레그램) 역할은 이 부모 프로세스가 같은 DB 파일에 APPROVED 신호 + QUEUED 의도·exit 요청을 넣는 것으로 흉내 낸다.

실행: .venv/bin/python -m bot.orders.verify.kill_restart_sim [--random N]  → results/kill_restart.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import threading
import time
from multiprocessing.managers import BaseManager
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "results" / "kill_restart.json"
PY = str(REPO / ".venv" / "bin" / "python")
AUTHKEY = b"verify-kill-restart"

EX_METHODS = ("server_time_ms", "symbol_rules", "account_config", "balance", "mark_price", "position",
              "open_orders", "open_conditional_orders", "place_order", "get_order", "cancel_order",
              "place_conditional", "get_conditional", "cancel_conditional")


# ---------------------------------------------------------------------------
# 거래소 서버 프로세스 쪽
# ---------------------------------------------------------------------------


def _cid_of(method: str, args: tuple) -> str | None:
    if not args:
        return None
    a = args[0]
    if isinstance(a, str):
        return a
    return getattr(a, "client_id", None) or getattr(a, "client_algo_id", None)


class Hub:
    """FakeExchange 하나 + 잠금 + 무방비 감시 + 강제 종료 훅."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.fx = None
        self.kills: list[dict[str, Any]] = []
        self.kill_log: list[dict[str, Any]] = []
        self.intervals: list[tuple[float, float]] = []
        self._un_start: float | None = None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._monitor, daemon=True)
        self._t.start()

    # --- 준비 ---
    def reset(self, mark: float = 60_000.0) -> None:
        from bot.orders.fake_exchange import FakeExchange
        from bot.types import SystemClock

        with self.lock:
            self.fx = FakeExchange(SystemClock(), mark=mark)
            self.kills = []
            self.kill_log = []
            self.intervals = []
            self._un_start = None

    def arm(self, pid: int, method: str, when: str, suffix: str | None = None, nth: int = 1) -> None:
        with self.lock:
            self.kills.append(dict(pid=pid, method=method, when=when, suffix=suffix, left=nth))

    def disarm(self) -> None:
        with self.lock:
            self.kills = []

    def set_mark(self, p: float) -> None:
        with self.lock:
            self.fx.set_mark(p)
            self.fx.tick(0)

    def inject(self, fault) -> None:
        with self.lock:
            self.fx.inject(fault)

    def clear_faults(self) -> None:
        with self.lock:
            self.fx.clear_faults()

    # --- 감시 ---
    def _protected(self) -> bool:
        from bot.orders.types import CONDITIONAL_ACTIVE_STATUSES, OrderType, Side

        fx = self.fx
        q = fx.position_qty
        if q == 0:
            return True
        if q < 0:
            return False
        return any(c.side is Side.SELL and c.type is OrderType.STOP_MARKET and c.close_position
                   and c.status in CONDITIONAL_ACTIVE_STATUSES and c.client_algo_id.startswith("sig-")
                   and c.trigger_price < fx.mark for c in fx.active_conditionals())

    def _sample(self) -> None:
        now = time.monotonic()
        ok = self._protected()
        if not ok and self._un_start is None:
            self._un_start = now
        elif ok and self._un_start is not None:
            self.intervals.append((self._un_start, now))
            self._un_start = None

    def _monitor(self) -> None:
        while not self._stop.is_set():
            with self.lock:
                if self.fx is not None:
                    try:
                        self.fx.tick(0)
                        self._sample()
                    except Exception:  # noqa: BLE001
                        pass
            time.sleep(0.002)

    # --- 호출 ---
    def _maybe_kill(self, when: str, method: str, cid: str | None) -> bool:
        for k in self.kills:
            if k["left"] <= 0 or k["method"] != method or k["when"] != when:
                continue
            if k["suffix"] is not None and not (cid or "").endswith(k["suffix"]):
                continue
            k["left"] -= 1
            if k["left"] == 0:
                try:
                    os.kill(k["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.kill_log.append(dict(t=time.time(), method=method, when=when, cid=cid, pid=k["pid"]))
                return True
        return False

    def call(self, method: str, args: tuple):
        from bot.orders.types import ExchangeError

        if method not in EX_METHODS:
            raise ValueError(method)
        with self.lock:
            cid = _cid_of(method, args)
            if self._maybe_kill("before", method, cid):
                self._sample()
                return ("dead", None)          # 요청은 거래소에 닿지 않았다(자식은 이미 죽음)
            try:
                res = getattr(self.fx, method)(*args)
                out = ("ok", res)
            except ExchangeError as e:
                out = ("err", dict(kind=e.kind, http_status=e.http_status, code=e.code, msg=e.msg,
                                   retry_after_s=e.retry_after_s))
            self._sample()
            self._maybe_kill("after", method, cid)   # 처리됨 → 응답 전 강제 종료
            return out

    # --- 결과 ---
    def status(self) -> dict[str, Any]:
        from bot.orders.types import CONDITIONAL_ACTIVE_STATUSES

        with self.lock:
            self._sample()
            ivs = list(self.intervals)
            open_iv = None if self._un_start is None else time.monotonic() - self._un_start
            fx = self.fx
            posts: dict[str, int] = {}
            for c in fx.calls:
                if c.method in ("place_order", "place_conditional", "cancel_order", "cancel_conditional"):
                    key = f"{c.method}:{(c.client_id or '')[-2:]}"
                    posts[key] = posts.get(key, 0) + 1
            return dict(
                position=fx.position_qty, protected=self._protected(), mark=fx.mark,
                active_stops=[(c.client_algo_id, c.trigger_price, c.status.value) for c in fx.all_conditionals()
                              if c.status in CONDITIONAL_ACTIVE_STATUSES],
                unprotected_ms=[round((b - a) * 1000, 1) for a, b in ivs],
                open_unprotected_ms=None if open_iv is None else round(open_iv * 1000, 1),
                posts=posts, e1_posts=sum(1 for c in fx.calls if c.method == "place_order"
                                          and (c.client_id or "").endswith("-e1")),
                kill_log=list(self.kill_log))


_HUB: Hub | None = None


def get_hub() -> Hub:
    global _HUB
    if _HUB is None:
        _HUB = Hub()
    return _HUB


class HubManager(BaseManager):
    pass


HubManager.register("hub", callable=get_hub)


# ---------------------------------------------------------------------------
# 자식(B) 쪽
# ---------------------------------------------------------------------------


def child_main(addr: str, cfg_path: str) -> int:
    from bot.orders import worker as W
    from bot.orders.types import ExchangeEnv, ExchangeError, env_base_url

    host, port = addr.rsplit(":", 1)
    m = HubManager(address=(host, int(port)), authkey=AUTHKEY)
    m.connect()
    hub = m.hub()

    class Remote:
        env = ExchangeEnv.DEMO
        base_url = env_base_url(ExchangeEnv.DEMO)

        def __getattr__(self, name: str):
            if name not in EX_METHODS:
                raise AttributeError(name)

            def f(*args):
                tag, val = hub.call(name, args)
                if tag == "ok":
                    return val
                if tag == "err":
                    raise ExchangeError(val.pop("kind"), **val)
                time.sleep(60)                   # 'dead': SIGKILL이 곧 도착
                raise SystemExit(99)

            return f

    def factory(ocfg, clock):
        if os.environ.get("VERIFY_LOAD_KEYS") == "1":
            # 키 추적 검증용: 실제 B처럼 키 파일을 읽어 서명 클라이언트를 만든다(네트워크는 쓰지 않고 버린다)
            from bot.orders.binance_client import BinanceFuturesClient

            BinanceFuturesClient.from_files(ocfg, clock=clock).close()
        return Remote()

    return W.main(["--config", cfg_path, "--log-level", "INFO", "run"], client_factory=factory)


# ---------------------------------------------------------------------------
# 부모(A 역할 + 지휘)
# ---------------------------------------------------------------------------


class Run:
    def __init__(self, hub, addr: str, name: str, root: Path) -> None:
        from bot import db
        from bot.types import Mode

        self.hub = hub
        self.addr = addr
        self.name = name
        self.dir = root / name
        (self.dir / "b").mkdir(parents=True)
        os.chmod(self.dir / "b", 0o700)
        src = (REPO / "config" / "bot.testnet.example.toml").read_text(encoding="utf-8")
        d = str(self.dir)
        repl = {
            '"/data/testnet.sqlite3"': f'"{d}/testnet.sqlite3"',
            '"/run/secrets/binance_api_key"': f'"{d}/b/binance_api_key"',
            '"/run/secrets/binance_ed25519_private_key"': f'"{d}/b/binance_ed25519_private_key"',
            '"/control/orders_control.toml"': f'"{d}/b/orders_control.toml"',
            '"/state/orders_ledger.json"': f'"{d}/b/orders_ledger.json"',
            "enabled = true": "enabled = false",
            "r_capital_usdt = 1000.0": "r_capital_usdt = 10000.0",
            "max_notional_usdt = 1000.0": "max_notional_usdt = 10000.0",
            "loop_interval_s = 2.0": "loop_interval_s = 0.5",
            "reconcile_interval_s = 10": "reconcile_interval_s = 5",
        }
        for a, b in repl.items():
            src = src.replace(a, b)
        self.cfg_path = self.dir / "bot.toml"
        self.cfg_path.write_text(src, encoding="utf-8")
        ctl = self.dir / "b" / "orders_control.toml"
        ctl.write_text("halt = false\n", encoding="utf-8")
        os.chmod(ctl, 0o600)
        self.db_path = self.dir / "testnet.sqlite3"
        self.conn = db.connect(self.db_path, mode=Mode.TESTNET, now_ms=int(time.time() * 1000))
        self.proc: subprocess.Popen | None = None
        self.starts = 0
        self.exit_codes: list[int | None] = []
        hub.reset()

    # --- B 프로세스 ---
    def start_b(self, arm: list[tuple] | None = None) -> None:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.dir), "PYTHONPATH": str(REPO),
               "LANG": "C.UTF-8"}
        log = open(self.dir / f"b{self.starts}.log", "w")
        self.proc = subprocess.Popen([PY, "-m", "bot.orders.verify.kill_restart_sim", "--child", self.addr,
                                      str(self.cfg_path)], cwd=str(REPO), env=env, stdout=log, stderr=log)
        self.starts += 1
        for spec in arm or []:
            self.hub.arm(self.proc.pid, *spec)

    def wait_dead(self, timeout: float = 20.0) -> bool:
        assert self.proc is not None
        try:
            self.exit_codes.append(self.proc.wait(timeout=timeout))
            return True
        except subprocess.TimeoutExpired:
            return False

    def restart(self, downtime_s: float, arm: list[tuple] | None = None) -> None:
        time.sleep(downtime_s)
        self.start_b(arm)

    def stop_b(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.exit_codes.append(self.proc.wait(timeout=30))
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.exit_codes.append(self.proc.wait())

    # --- A 역할 ---
    def approve(self, n: int = 20) -> tuple[str, int]:
        from bot.orders.tests.conftest import make_approved_intent

        now = int(time.time() * 1000)
        return make_approved_intent(self.conn, n=n, approved_ms=now, decision_ns=(now - 60_000) * 1_000_000)

    def request_exit(self, sid: str) -> bool:
        from bot.orders import queue

        now = int(time.time() * 1000)
        return queue.request_exit(self.conn, sid, exit_signal_close_ms=now, exit_due_ms=now, now_ms=now)

    def intent(self, iid: int):
        from bot.orders import queue

        return queue.get_intent(self.conn, iid)

    def wait_state(self, iid: int, states: set[str], timeout: float = 30.0) -> str:
        end = time.time() + timeout
        st = ""
        while time.time() < end:
            st = self.intent(iid)["state"]
            if st in states:
                return st
            time.sleep(0.05)
        return st

    def b_ready(self, timeout: float = 20.0) -> bool:
        from bot.orders import queue

        end = time.time() + timeout
        t0 = int(time.time() * 1000)
        while time.time() < end:
            r = queue.get_runtime(self.conn, "b_heartbeat_ms")
            if r is not None and int(float(r["value"])) >= t0:
                return True
            time.sleep(0.05)
        return False

    def finish(self, settle_s: float = 8.0) -> dict[str, Any]:
        from bot.orders import queue
        from bot.orders.types import INTENT_LIVE

        time.sleep(settle_s)
        self.stop_b()
        st = self.hub.status()
        live = queue.intents_in_states(self.conn, INTENT_LIVE)
        intents = [dict(id=r["intent_id"], state=r["state"], reason=r["state_reason"], exit=r["exit_reason"],
                        unprotected_ms=r["unprotected_ms"]) for r in
                   self.conn.execute("SELECT * FROM order_intents ORDER BY intent_id")]
        halts = [r["reason"] for r in queue.halts(self.conn)]
        worst = max(st["unprotected_ms"] + ([st["open_unprotected_ms"]] if st["open_unprotected_ms"] else [0.0]))
        db_flat_but_pos = (not live) and st["position"] > 0
        safe = (st["position"] >= 0 and st["protected"] and st["e1_posts"] <= len(intents) and len(live) <= 1
                and not db_flat_but_pos)
        self.conn.close()
        return dict(name=self.name, safe=safe, worst_unprotected_ms=worst, exchange=st, intents=intents, halts=halts,
                    b_starts=self.starts, b_exit_codes=self.exit_codes, db_flat_but_position=db_flat_but_pos)


def scenario(hub, addr: str, root: Path, name: str, **kw: Any) -> dict[str, Any]:
    """kw: kill1(첫 기동의 강제 종료 지점 목록), down(중단 초), kill2(재시작 직후 복구 중 강제 종료), exit(추세 청산 요청),
    kill_exit(청산 중 강제 종료 지점), stop_fail(손절 등록 거부 → 비상 청산), fire_while_dead(죽은 동안 손절 발동)."""
    from bot.orders.fake_exchange import Fault, FaultKind

    r = Run(hub, addr, name, root)
    notes: list[str] = []
    r.start_b()
    if not r.b_ready():
        notes.append("B not ready")
    if kw.get("stop_fail"):
        hub.inject(Fault(FaultKind.REJECT, method="place_conditional", code=-1111, times=10))
    for spec in kw.get("kill1", []):
        hub.arm(r.proc.pid, *spec)
    sid, iid = r.approve()
    if kw.get("kill1"):
        died = r.wait_dead(20)
        notes.append(f"killed={died} state_at_kill={r.intent(iid)['state']}")
        if kw.get("stop_fail"):
            hub.clear_faults()
        if kw.get("tamper"):
            # 2차 검증(V-1 수정 확인): B가 죽은 동안 보호 트리거 1개 삭제 → 재시작은 거부(3)되어야 하고,
            # 거부 전에 DB 없이 포지션을 청산해야 한다. compose 재시작처럼 한 번 더 띄워 추가 주문이 없는지 본다.
            r.conn.execute("DROP TRIGGER order_events_no_delete")
            r.conn.commit()
            r.restart(kw.get("down", 1.0))
            notes.append(f"tamper_restart_exited={r.wait_dead(90)} code={r.exit_codes[-1:]}")
            posts_before = hub.status()["posts"]
            r.restart(0.5)
            notes.append(f"tamper_restart2_exited={r.wait_dead(90)} code={r.exit_codes[-1:]}")
            notes.append(f"posts_after_1st={posts_before} posts_after_2nd={hub.status()['posts']}")
            res = r.finish(1.0)
            res["notes"] = notes
            res["params"] = {k: v for k, v in kw.items()}
            return res
        r.restart(kw.get("down", 1.0), kw.get("kill2"))
        if kw.get("kill2"):
            died2 = r.wait_dead(20)
            notes.append(f"killed_in_recovery={died2}")
            r.restart(kw.get("down", 1.0))
    st = r.wait_state(iid, {"STOP_VERIFIED", "REJECTED", "NOT_FILLED", "FAILED_FLATTENED", "CLOSED", "HALTED"}, 30)
    notes.append(f"after_entry={st}")
    if kw.get("stop_fail") and not kw.get("kill1"):
        hub.clear_faults()
    if kw.get("idle_kill") and st == "STOP_VERIFIED":
        time.sleep(0.7)
        r.proc.send_signal(signal.SIGKILL)
        r.wait_dead()
        if kw.get("fire_while_dead"):
            hub.set_mark(60_000.0 * 0.9)          # 손절 발동(롱 → 0)
        r.restart(kw.get("down", 1.0))
    if kw.get("exit") and st == "STOP_VERIFIED":
        for spec in kw.get("kill_exit", []):
            hub.arm(r.proc.pid, *spec)
        r.request_exit(sid)
        if kw.get("kill_exit"):
            died = r.wait_dead(20)
            notes.append(f"killed_in_exit={died} state={r.intent(iid)['state']}")
            r.restart(kw.get("down", 1.0))
        st = r.wait_state(iid, {"CLOSED", "FAILED_FLATTENED", "HALTED"}, 30)
        notes.append(f"after_exit={st}")
    if kw.get("fire_while_dead"):
        st = r.wait_state(iid, {"CLOSED", "FAILED_FLATTENED", "HALTED"}, 30)
        notes.append(f"after_fire={st}")
    res = r.finish(kw.get("settle", 6.0))
    res["notes"] = notes
    res["params"] = {k: v for k, v in kw.items()}
    return res


def random_scenario(hub, addr: str, root: Path, seed: int) -> dict[str, Any]:
    """무작위 시각 SIGKILL 여러 번 + 무작위 중단 시간 + 추세 청산·손절 발동."""
    rnd = random.Random(seed)
    r = Run(hub, addr, f"random_{seed}", root)
    r.start_b()
    r.b_ready()
    sid, iid = r.approve()
    kills = []
    exit_asked = fired = False
    for k in range(rnd.randint(2, 4)):
        time.sleep(rnd.uniform(0.0, 1.5))
        if r.proc.poll() is None:
            r.proc.send_signal(signal.SIGKILL)
            r.wait_dead()
        st = r.intent(iid)["state"]
        kills.append(st)
        if not exit_asked and st == "STOP_VERIFIED" and rnd.random() < 0.4:
            exit_asked = r.request_exit(sid)
        elif not fired and st == "STOP_VERIFIED" and rnd.random() < 0.3:
            hub.set_mark(54_000.0)
            fired = True
        r.restart(rnd.uniform(0.3, 3.0))
    r.wait_state(iid, {"STOP_VERIFIED", "REJECTED", "NOT_FILLED", "FAILED_FLATTENED", "CLOSED", "HALTED"}, 30)
    res = r.finish(6.0)
    res["notes"] = [f"states_at_kills={kills}", f"exit_asked={exit_asked}", f"stop_fired={fired}"]
    return res


SCENARIOS: list[tuple[str, dict[str, Any]]] = [
    ("S00_normal_no_kill", dict()),
    ("S01_kill_before_entry_reaches", dict(kill1=[("place_order", "before", "-e1")])),
    ("S02_kill_after_fill_down1s", dict(kill1=[("place_order", "after", "-e1")], down=1.0)),
    ("S02b_kill_after_fill_down5s", dict(kill1=[("place_order", "after", "-e1")], down=5.0)),
    ("S02c_kill_after_fill_down10s", dict(kill1=[("place_order", "after", "-e1")], down=10.0)),
    ("S03_kill_after_stop_accepted", dict(kill1=[("place_conditional", "after", "-sl")])),
    ("S04_kill_before_stop_verify_query", dict(kill1=[("get_conditional", "before", "-sl")])),
    ("S05_kill_after_fill_then_kill_in_recovery",
     dict(kill1=[("place_order", "after", "-e1")], kill2=[("position", "before", None)], down=1.0)),
    ("S06_kill_while_holding", dict(idle_kill=True)),
    ("S07_kill_after_exit_x1_executed", dict(exit=True, kill_exit=[("place_order", "after", "-x1")])),
    ("S08_kill_before_exit_x1_reaches", dict(exit=True, kill_exit=[("place_order", "before", "-x1")])),
    ("S09_stop_rejected_kill_after_flatten_f1",
     dict(stop_fail=True, kill1=[("place_order", "after", "-f1")])),
    ("S10_stop_fires_while_b_dead", dict(idle_kill=True, fire_while_dead=True, down=3.0)),
    ("S11_kill_before_stop_place", dict(kill1=[("place_conditional", "before", "-sl")])),
    ("S12_kill_after_fill_then_db_tamper_refused_restart",
     dict(kill1=[("place_order", "after", "-e1")], tamper=True, down=1.0)),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", nargs=2)
    ap.add_argument("--random", type=int, default=12)
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    if a.child:
        return child_main(*a.child)
    m = HubManager(address=("127.0.0.1", 0), authkey=AUTHKEY)
    m.start()
    addr = f"127.0.0.1:{m.address[1]}"
    hub = m.hub()
    results = []
    with tempfile.TemporaryDirectory(prefix="killsim-") as d:
        root = Path(d)
        for name, kw in SCENARIOS:
            if a.only and a.only not in name:
                continue
            t0 = time.time()
            res = scenario(hub, addr, root, name, **kw)
            res["elapsed_s"] = round(time.time() - t0, 1)
            results.append(res)
            print(json.dumps({k: res[k] for k in ("name", "safe", "worst_unprotected_ms", "intents", "halts",
                                                  "notes", "b_exit_codes")}, ensure_ascii=False, default=str),
                  flush=True)
            print("   exchange:", json.dumps({k: res["exchange"][k] for k in
                                               ("position", "protected", "unprotected_ms", "posts")},
                                              ensure_ascii=False), flush=True)
        for seed in range(a.random):
            res = random_scenario(hub, addr, root, seed)
            results.append(res)
            print(json.dumps({k: res[k] for k in ("name", "safe", "worst_unprotected_ms", "intents", "halts",
                                                  "notes")}, ensure_ascii=False, default=str), flush=True)
    m.shutdown()
    summary = dict(total=len(results), unsafe=[r["name"] for r in results if not r["safe"]],
                   worst_unprotected_ms=max(r["worst_unprotected_ms"] for r in results),
                   worst_by_scenario={r["name"]: r["worst_unprotected_ms"] for r in results})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(summary=summary, results=results), ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    return 0 if not summary["unsafe"] else 1


if __name__ == "__main__":
    sys.exit(main())
