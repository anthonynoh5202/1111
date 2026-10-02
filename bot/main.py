"""실행 진입점 — 통합 담당 구현 (bot/DESIGN.md §2, §9.7, §11).

사용
    python -m bot.main --config /config/bot.toml check              # 설정·비밀 파일·DB 점검만(값 출력 없음)
    python -m bot.main --config /config/bot.toml run [--dry-run]    # mode=paper: 스케줄러 + 텔레그램 롱 폴링
    python -m bot.main --config bot.replay.toml replay [--exec-bars backtest|1m] [--trades-csv PATH]
    python -m bot.main --config /config/bot.toml backup --dest /backups/bot-YYYYMMDD.sqlite3

종료 코드: 0 정상, 2 설정·비밀 오류(환경 변수 비밀 포함, 텔레그램 토큰 거부), 3 DB 오류(모드 불일치·권한·감사 로그 변조),
1 그 밖의 오류(메시지는 가림 필터를 거친 로그로만, 트레이스백은 가림 excepthook으로).

시작 순서 (DESIGN §2.4)
1) os.umask(0o077)  2) config.check_env_no_secrets()가 비어 있지 않으면 종료(코드 2, 이름만 출력)
3) load_config → load_secrets(파일) → setup_logging(가림 필터) → db.connect(모드 일치 확인) → db.save_config_snapshot
4) paper: LiveBinance.check_clock, 텔레그램 롱 폴링(deleteWebhook은 build_application의 post_init), Engine,
   스케줄(매일 00:01:00 UTC 사이클, monitor_interval_s마다 tick)
   replay: FakeClock + Replay(파일) + 기록용 가짜 전송 + DisabledAnalyst. 자동 승인 = 판단 + L분에 [승인]·[확인]
5) SIGTERM/SIGINT → 진행 중 사이클 끝내고 DB 닫기

이 모듈에는 거래소 키·주문 코드가 없다. 외부 호출은 공개 시세(LiveBinance), 텔레그램(롱 폴링),
Claude(분석), healthchecks 핑(선택)뿐이다. mode=testnet도 `run`으로 같은 경로를 탄다(프로세스 A): 승인된 신호는
주문 큐(order_intents)에 들어가고, 실제 주문은 별도 프로세스 B(`python -m bot.orders.worker`, compose 서비스 orders)가 한다.
testnet에서 A에 거래 키·제어 파일이 보이면 load_secrets가 시작을 거부한다(config.check_no_trading_keys).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import signal
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from bot import BOT_VERSION, db
from bot.config import BotConfig, ConfigError, Secrets, check_env_no_secrets, load_config, load_secrets, setup_logging
from bot.types import (
    NS_PER_DAY,
    NS_PER_MIN,
    NS_PER_SEC,
    Button,
    FakeClock,
    Mode,
    OutgoingMessage,
    SignalState,
    SystemClock,
    ms_to_ns,
    ns_to_ms,
    utc_iso_ms,
)

log = logging.getLogger("bot.main")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2
EXIT_DB = 3

REPO_ROOT = Path(__file__).resolve().parent.parent
HEALTH_PING_INTERVAL_S = 300          # healthchecks 핑 주기(성공한 tick 기준, INFRA §7.2와 같은 5분 — 기간 5분·유예 10분)
HEALTH_PING_TIMEOUT_S = 10.0
TELEGRAM_STALE_S = 900                # 마지막 텔레그램 성공(전송·웹훅 점검)이 이보다 오래되면 핑을 보내지 않는다(OPS-2)
WEBHOOK_CHECK_INTERVAL_S = 300        # DT-05: 웹훅 가로채기 점검 주기
TELEGRAM_RETRY_MIN_S = 5.0            # 텔레그램 시작 실패 재시도(지수 백오프, 최대 5분)
TELEGRAM_RETRY_MAX_S = 300.0
HEARTBEAT_PATH = "/tmp/bot-heartbeat"  # compose healthcheck가 이 파일의 나이를 본다(OPS-8)


# ---------------------------------------------------------------------------
# 공용 도우미
# ---------------------------------------------------------------------------


def _err(msg: str) -> None:
    """사용자에게 보이는 오류 한 줄(stderr). 비밀 값은 절대 넣지 않는다(호출자가 경로·이름만 넘김)."""
    print(f"오류: {msg}", file=sys.stderr)


def _now_ms_system() -> int:
    return ns_to_ms(SystemClock().now_ns())


def install_excepthooks(secrets: Secrets | None) -> None:
    """잡히지 않은 예외의 마지막 방어선(SEC-01/OPS-6): 기본 excepthook은 트레이스백을 가림 필터 밖(stderr = docker 로그)으로
    쓴다. 예외 메시지에 토큰이 실릴 수 있으므로(PTB InvalidToken) 가림을 거친 문자열만 쓴다. 스레드 예외도 같게."""
    import threading
    import traceback

    from bot.config import RedactingFilter

    red = RedactingFilter(secrets)

    def _hook(exc_type, exc, tb) -> None:
        try:
            text = "".join(traceback.format_exception(exc_type, exc, tb))
            sys.stderr.write(red.redact(f"처리되지 않은 예외({exc_type.__name__}):\n{text}"))
        except Exception:  # noqa: BLE001 — 훅 자체가 실패해도 값은 쓰지 않는다
            sys.stderr.write(f"처리되지 않은 예외: {getattr(exc_type, '__name__', '?')}\n")

    def _thread_hook(args) -> None:
        if args.exc_type is SystemExit:
            return
        _hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def _loop_exception_handler(loop, context: dict) -> None:
    """asyncio 루프에서 잡히지 않은 예외: 종류만(메시지·트레이스백은 가림 필터를 거치는 로거로도 남기지 않는다)."""
    exc = context.get("exception")
    log.error("비동기 작업 예외: %s", type(exc).__name__ if exc is not None else str(context.get("message", ""))[:80])


class TelegramHealth:
    """텔레그램이 실제로 동작하는지(OPS-2). 마지막 성공(메시지 전송·웹훅 점검) 시각으로 판단.
    always_ok=True면(텔레그램 비활성) 늘 정상으로 본다."""

    def __init__(self, *, always_ok: bool = False, stale_s: float = TELEGRAM_STALE_S) -> None:
        self.always_ok = always_ok
        self.stale_s = float(stale_s)
        self.last_ok: float | None = None
        self.last_fail: float | None = None
        self.down_alerted = False

    def ok(self, t: float) -> None:
        self.last_ok = float(t)

    def fail(self, t: float) -> None:
        self.last_fail = float(t)

    def alive(self, t: float) -> bool:
        if self.always_ok:
            return True
        return self.last_ok is not None and float(t) - self.last_ok <= self.stale_s

    def record(self, t: float, results) -> None:
        """send_outgoing 결과 반영: 하나라도 성공이면 ok, 전부 실패면 fail."""
        if not results:
            return
        if any(ok for _, ok in results):
            self.ok(t)
        else:
            self.fail(t)


def _touch_heartbeat(path: str | None) -> None:
    """compose healthcheck용 심장 박동 파일(내용 없음, 수정 시각만). 실패해도 루프는 계속."""
    if not path:
        return
    try:
        p = Path(path)
        p.touch(mode=0o600, exist_ok=True)
        os.utime(p, None)
    except OSError as exc:
        log.warning("심장 박동 파일 갱신 실패: %s", type(exc).__name__)


def resolve_data_dir(cfg: BotConfig) -> Path:
    """marketdata.data_dir(재생 입력). 상대 경로는 저장소 루트 기준."""
    p = Path(cfg.marketdata.data_dir)
    return p if p.is_absolute() else REPO_ROOT / p


def open_db(cfg: BotConfig, now_ms: int) -> sqlite3.Connection:
    """DB 열기 + 설정 스냅샷(가린 값). 모드 불일치는 db.DbError."""
    conn = db.connect(cfg.db_path, mode=cfg.mode, now_ms=now_ms)
    db.save_config_snapshot(conn, config_dict=cfg.redacted_dict(), fingerprint=cfg.fingerprint(),
                            bot_version=BOT_VERSION, now_ms=now_ms)
    return conn


# ---------------------------------------------------------------------------
# 재생(replay) 모드
# ---------------------------------------------------------------------------


def exec_replay_class():
    """백테스트 실행 봉(2023-10-01 전 5분봉 + 이후 1분봉, backtest.data.load_exec_bars)을 '분봉'으로 주는 Replay.

    1분봉 파일은 2023-10-01부터만 있으므로, 2020년부터 재생하려면 백테스트와 같은 실행 봉을 써야 한다.
    paper 코드는 봉 길이에 의존하지 않고(open_ns ≥ 확인 시각인 첫 봉, close_ns 커서) 동작한다(DESIGN §3.4).
    실운영(paper)은 LiveBinance의 진짜 1분봉을 쓴다.
    """
    from bot.marketdata import Replay

    class ExecReplay(Replay):
        """펀딩도 백테스트(backtest.data.load_market)와 같게: load_funding(until_ns=실행 봉 끝) —
        파일 끝 뒤(2026-09-01부터)는 §12.2 대체값(0.01%/8h, synthetic)을 덧붙인다. 입력이 백테스트와 같아야
        대조 시험이 성립한다. paper 모드는 LiveBinance의 실제 펀딩을 쓰므로 대체값과 무관하다."""

        def __init__(self, data_dir, clock, *, cache_dir=None, daily_from_ns=None) -> None:
            from backtest import data as D

            super().__init__(data_dir, clock, cache_dir=cache_dir, daily_from_ns=daily_from_ns)
            self._load_minute()
            until = int(self._m_close[-1])
            self._funding = D.load_funding(until_ns=until, data_dir=self._data_dir).reset_index(drop=True)
            self._f_time = self._funding["time_ns"].to_numpy()

        def _load_minute(self) -> None:
            if self._minute is None:
                from backtest import data as D

                self._set_minute(D.load_exec_bars(data_dir=self._data_dir, cache_dir=self._cache_dir))

    return ExecReplay


def build_replay_market(cfg: BotConfig, clock: FakeClock, *, exec_bars: str = "backtest",
                        cache_dir: Path | None = None):
    """재생 시세. exec_bars='backtest'(기본: 5분+1분 실행 봉, 2020년부터 가능) | '1m'(1분봉만, 2023-10부터)."""
    from bot.marketdata import Replay

    cls = exec_replay_class() if exec_bars == "backtest" else Replay
    if exec_bars not in ("backtest", "1m"):
        raise ValueError("exec_bars는 'backtest' 또는 '1m'")
    return cls(resolve_data_dir(cfg), clock, cache_dir=cache_dir)


@dataclass
class RecordingTransport:
    """재생 모드 전송 계층: 보내지 않고 기록만 한다(ChatTransport 모양). 외부 연결 없음."""

    sent: list[tuple[int, str, tuple]] = field(default_factory=list)
    edits: list[tuple[int, str, tuple]] = field(default_factory=list)
    answers: list[tuple[str, str | None]] = field(default_factory=list)
    keep_text: bool = False           # 전체 재생에서 메모리 절약: 기본은 본문을 버리고 개수만
    _next_id: int = 0

    async def send(self, text: str, buttons: tuple[tuple[Button, ...], ...] = (), *, protect: bool = True) -> int:
        self._next_id += 1
        self.sent.append((self._next_id, text if self.keep_text else text[:80], buttons))
        return self._next_id

    async def edit(self, message_id: int, text: str, buttons: tuple[tuple[Button, ...], ...] = ()) -> None:
        self.edits.append((int(message_id), text if self.keep_text else text[:80], buttons))

    async def answer_callback(self, callback_query_id: str, text: str | None = None) -> None:
        self.answers.append((callback_query_id, text))


def deliver(transport, engine, messages: list[OutgoingMessage]) -> None:
    """engine 메시지 전송(동기 래퍼). 카드는 전송 성공 뒤에만 NEW→CARD_SENT(telegram_ui.send_outgoing).
    새 메시지가 없어도 부른다: 보관함(outbox)에 남은 실패 메시지를 다시 보내야 하므로(OPS-3)."""
    from bot import telegram_ui as tu

    asyncio.run(tu.send_outgoing(transport, engine, messages))


def _date_ns(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) * NS_PER_SEC


def replay_decision_times(cfg: BotConfig, daily_close_ns: Sequence[int]) -> list[int]:
    """재생할 판단 시각 목록: 일봉 마감 + 60초 중 replay.start ≤ 판단 날짜 ≤ replay.end (UTC, 빈 값 = 끝까지).

    판단 날짜 D의 사이클은 D−1일 일봉(D 00:00 마감)을 본다. 예: start='2020-01-01'이어도 첫 일봉이
    2020-01-01이면 첫 사이클은 2020-01-02 00:01 UTC.
    """
    delay = int(cfg.schedule.decision_delay_s) * NS_PER_SEC
    lo = _date_ns(cfg.replay.start) if cfg.replay.start else None
    hi = _date_ns(cfg.replay.end) + NS_PER_DAY if cfg.replay.end else None
    out = []
    for c in daily_close_ns:
        dec = int(c) + delay
        if lo is not None and dec < lo:
            continue
        if hi is not None and dec >= hi:
            continue
        out.append(dec)
    return out


@dataclass
class ReplaySummary:
    cycles: int = 0
    failed_cycles: int = 0
    signals: int = 0
    approved: int = 0
    positions: int = 0
    closed: int = 0
    open_at_end: int = 0
    sent_messages: int = 0
    max_until_ns: int | None = None
    end_ns: int | None = None

    def line(self) -> str:
        return (f"재생 완료: 사이클 {self.cycles}(실패 {self.failed_cycles}) · 신호 {self.signals} · 승인 {self.approved}"
                f" · 모의 포지션 {self.positions}(청산 {self.closed}, 보유 {self.open_at_end})"
                f" · 메시지 {self.sent_messages}")


def auto_approve(engine, decision_ns: int) -> int:
    """재생 자동 승인: 이 판단의 CARD_SENT 신호마다 [승인] → [확인]을 같은 시각에(지연은 시계가 이미 반영). 승인 수."""
    n = 0
    dec_ms = ns_to_ms(decision_ns)
    for sig in db.signals_in_states(engine.conn, [SignalState.CARD_SENT]):
        if int(sig["decision_ms"]) != dec_ms:
            continue
        if engine.request_confirm(sig["signal_id"]) and engine.confirm(sig["signal_id"]):
            n += 1
    return n


def run_replay_loop(engine, clock: FakeClock, transport, decisions: Sequence[int], *,
                    auto_approve_latency_min: int | None, end_ns: int | None = None,
                    progress_every: int = 0) -> ReplaySummary:
    """과거를 하루씩 흘려보낸다. 하루 = [판단 시각: tick → 사이클 → 카드 전송] → [판단 + L분: 자동 승인·확인].

    - tick을 사이클 직전에 부르므로 전날 신호의 만료·체결·손절·추세 청산이 다음 신호 계산 전에 모두 반영된다
      (paper는 커서 기반이라 tick 주기와 결과가 무관: DESIGN §2.2).
    - 끝나면 end_ns(없으면 마지막 판단 시각)까지 tick 한 번 더.
    시계는 앞으로만 간다(FakeClock). 재생 중 미래 조회는 Replay가 예외로 막는다.
    """
    summ = ReplaySummary()
    for i, dec in enumerate(decisions):
        clock.set(max(clock.now_ns(), int(dec)))
        deliver(transport, engine, engine.tick())
        rep = engine.run_daily_cycle()
        summ.cycles += 1
        if rep.skipped_reason not in (None, "already_done"):
            summ.failed_cycles += 1
            log.warning("재생 사이클 %s: %s", utc_iso_ms(ns_to_ms(dec)), rep.skipped_reason)
        deliver(transport, engine, rep.outgoing)
        if auto_approve_latency_min is not None:
            clock.set(int(dec) + int(auto_approve_latency_min) * NS_PER_MIN)
            summ.approved += auto_approve(engine, int(dec))
        if progress_every and (i + 1) % progress_every == 0:
            log.info("재생 진행: %s (%d/%d)", utc_iso_ms(ns_to_ms(dec))[:10], i + 1, len(decisions))
    final = max(clock.now_ns(), int(end_ns) if end_ns is not None else 0)
    clock.set(final)
    deliver(transport, engine, engine.tick())
    conn = engine.conn
    summ.signals = int(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
    summ.positions = int(conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0])
    summ.closed = int(conn.execute("SELECT COUNT(*) FROM paper_positions WHERE state = 'CLOSED'").fetchone()[0])
    summ.open_at_end = summ.positions - summ.closed
    summ.sent_messages = len(getattr(transport, "sent", ()))
    summ.max_until_ns = getattr(engine.market, "max_until_ns", None)
    summ.end_ns = final
    return summ


POSITION_EXPORT_COLUMNS = (
    "position_id", "signal_id", "subsystem_n", "side", "state", "signal_close_ms", "decision_ms", "approved_ms",
    "entry_ms", "entry_price", "stop", "risk_per_unit", "qty", "exit_ms", "exit_price", "exit_reason",
    "fees", "slippage", "funding", "gross_pnl", "net_pnl", "r_multiple",
)


def export_positions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """모의 포지션 + 신호 정보(대조·보고용). 진입 시각·N 순."""
    rows = conn.execute(
        "SELECT p.*, s.signal_close_ms AS signal_close_ms, s.decision_ms AS decision_ms,"
        " s.approved_ms AS approved_ms FROM paper_positions p JOIN signals s USING (signal_id)"
        " ORDER BY p.entry_ms, p.subsystem_n").fetchall()
    return [{k: r[k] for k in POSITION_EXPORT_COLUMNS} for r in rows]


def write_positions_csv(conn: sqlite3.Connection, path: str | os.PathLike[str]) -> int:
    rows = export_positions(conn)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(POSITION_EXPORT_COLUMNS) + ["entry_utc", "exit_utc"])
        w.writeheader()
        for r in rows:
            w.writerow(r | {"entry_utc": utc_iso_ms(r["entry_ms"]), "exit_utc": utc_iso_ms(r["exit_ms"])})
    return len(rows)


def cmd_replay(cfg: BotConfig, args: argparse.Namespace) -> int:
    from bot.engine import Engine

    if cfg.mode != Mode.REPLAY:
        _err("replay 명령은 mode = \"replay\" 설정에서만 쓴다(paper DB를 재생으로 더럽히지 않게)")
        return EXIT_CONFIG
    clock = FakeClock(0)
    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    market = build_replay_market(cfg, clock, exec_bars=args.exec_bars, cache_dir=cache_dir)
    daily_close = market._daily_close  # 재생 입력의 일봉 마감 시각(판단 시각 목록용, 미래 조회 아님)
    decisions = replay_decision_times(cfg, daily_close)
    if not decisions:
        _err("재생할 판단 시각이 없다(replay.start/end와 데이터 기간 확인)")
        return EXIT_CONFIG
    clock.set(decisions[0])
    try:
        conn = open_db(cfg, ns_to_ms(decisions[0]))
    except db.DbError as exc:
        _err(f"DB: {exc}")
        return EXIT_DB
    try:
        engine = Engine(conn, cfg, market, None, clock)   # 재생: DisabledAnalyst(외부 호출 없음)
        transport = RecordingTransport()
        end_ns = int(daily_close[-1]) if len(daily_close) else None
        summ = run_replay_loop(engine, clock, transport, decisions,
                               auto_approve_latency_min=cfg.replay.auto_approve_latency_min,
                               end_ns=max(end_ns or 0, decisions[-1]), progress_every=100)
        print(summ.line())
        if args.trades_csv:
            n = write_positions_csv(conn, args.trades_csv)
            print(f"모의 포지션 {n}건 → {args.trades_csv}")
    finally:
        conn.close()
    return EXIT_OK


# ---------------------------------------------------------------------------
# paper 모드
# ---------------------------------------------------------------------------


@dataclass
class PaperRuntime:
    """paper 실행에 필요한 객체 묶음(네트워크 없이 만들 수 있다: --dry-run·시험용)."""

    cfg: BotConfig
    secrets: Secrets
    conn: sqlite3.Connection
    clock: Any
    market: Any
    analyst: Any
    engine: Any
    health: TelegramHealth = field(default_factory=TelegramHealth)
    heartbeat_path: str | None = None          # run_paper가 HEARTBEAT_PATH로 채운다(시험은 None = 파일 없음)
    startup_alerts: list = field(default_factory=list)   # 시작 중 문제(시계 확인 실패 등) — 첫 바퀴에 보낸다


def build_paper_runtime(cfg: BotConfig, secrets: Secrets, *, clock=None, http_client=None,
                        analyst_client_factory=None) -> PaperRuntime:
    """paper 구성요소를 만든다(네트워크 호출 없음). DB 모드 불일치는 db.DbError."""
    from bot.analyst import AnthropicAnalystClient, DisabledAnalyst
    from bot.engine import Engine
    from bot.marketdata import LiveBinance

    if cfg.mode not in (Mode.PAPER, Mode.TESTNET):
        raise ConfigError("run 명령은 mode = \"paper\" 또는 \"testnet\" 설정에서만 쓴다")
    clock = clock or SystemClock()
    conn = open_db(cfg, ns_to_ms(clock.now_ns()))
    try:
        market = LiveBinance(cfg.marketdata, clock, http_client=http_client)
        if cfg.claude.enabled:
            if secrets.anthropic_api_key is None:
                raise ConfigError("claude.enabled인데 API 키 파일을 읽지 않았다")
            kw = {"client_factory": analyst_client_factory} if analyst_client_factory is not None else {}
            analyst = AnthropicAnalystClient(secrets.anthropic_api_key, cfg.claude, **kw)
        else:
            analyst = DisabledAnalyst(cfg.claude.prompt_version, cfg.claude.model)
        engine = Engine(conn, cfg, market, analyst, clock)
    except BaseException:
        conn.close()
        raise
    return PaperRuntime(cfg=cfg, secrets=secrets, conn=conn, clock=clock, market=market, analyst=analyst,
                        engine=engine)


def _cycle_done(engine, decision_ns: int) -> bool:
    day = utc_iso_ms(ns_to_ms(decision_ns))[:10]
    with engine.lock:
        row = engine.conn.execute("SELECT status FROM cycles WHERE cycle_day = ?", (day,)).fetchone()
    return row is not None and row["status"] == "DONE"


async def _health_ping(secrets: Secrets) -> None:
    """healthchecks 핑(선택). URL은 비밀 — 로그에는 오류 종류만."""
    if secrets.ping_url is None:
        return
    import httpx

    url = secrets.ping_url.reveal()
    if not url.startswith("https://"):
        log.warning("헬스체크 URL이 https가 아니라 핑을 보내지 않는다")
        return
    try:
        async with httpx.AsyncClient(timeout=HEALTH_PING_TIMEOUT_S, follow_redirects=False) as client:
            await client.get(url)
    except Exception as exc:  # noqa: BLE001 — 핑 실패는 운영에 영향 없음
        log.warning("헬스체크 핑 실패: %s", type(exc).__name__)


async def paper_loop(rt: PaperRuntime, transport, stop: asyncio.Event) -> None:
    """스케줄 루프: monitor_interval_s마다 [판단 시각이 지났고 오늘 사이클 미완료면 사이클] → tick → 전송.

    사이클·tick은 동기 코드라 asyncio.to_thread로 돌린다(Claude 최대 120초 동안 텔레그램 버튼 처리 계속).
    DB 공유: 엔진은 engine.lock(RLock) 안에서만 DB를 쓰고, 텔레그램 핸들러도 같은 락을 쓴다(build_application db_lock).
    전송 실패한 카드 아닌 메시지는 DB 보관함에 남아 다음 바퀴에 다시 보낸다(telegram_ui.send_outgoing, OPS-3).
    healthchecks 핑은 tick이 성공했고 텔레그램이 살아 있을 때만(마지막 성공이 15분 안, OPS-2) 5분마다 보낸다.
    """
    from bot import telegram_ui as tu

    engine, interval = rt.engine, int(rt.cfg.schedule.monitor_interval_s)
    last_ping = float("-inf")
    loop = asyncio.get_running_loop()
    pending = list(rt.startup_alerts)
    rt.startup_alerts.clear()
    while not stop.is_set():
        try:
            if pending:
                rt.health.record(loop.time(), await tu.send_outgoing(transport, engine, pending))
                pending = []
            now_ns = engine.now_ns()
            dec = engine.decision_ns_for(now_ns)
            if now_ns >= dec and not _cycle_done(engine, dec):
                rep = await asyncio.to_thread(engine.run_daily_cycle)
                rt.health.record(loop.time(), await tu.send_outgoing(transport, engine, rep.outgoing))
            msgs = await asyncio.to_thread(engine.tick)
            rt.health.record(loop.time(), await tu.send_outgoing(transport, engine, msgs))
            _touch_heartbeat(rt.heartbeat_path)
            now = loop.time()
            if now - last_ping >= HEALTH_PING_INTERVAL_S:
                if rt.health.alive(now):
                    last_ping = now
                    await _health_ping(rt.secrets)
                elif not rt.health.down_alerted:
                    rt.health.down_alerted = True
                    log.error("텔레그램 응답 없음(마지막 성공 %s초 넘음) — 헬스체크 핑을 멈춘다",
                              int(rt.health.stale_s))
            if rt.health.alive(now):
                rt.health.down_alerted = False
        except Exception as exc:  # noqa: BLE001 — 루프는 죽지 않는다(다음 주기 재시도), 종류만 기록
            log.error("스케줄 루프 오류: %s", type(exc).__name__, exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


class _TelegramStatus:
    def __init__(self) -> None:
        self.first = asyncio.get_running_loop().create_future()   # 'up' | 'fatal' | 'retrying'
        self.fatal: str | None = None

    def settle(self, value: str) -> None:
        if not self.first.done():
            self.first.set_result(value)


async def _wait_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(0.0, float(seconds)))
    except asyncio.TimeoutError:
        pass


async def _telegram_supervisor(app, rt: PaperRuntime, transport, stop: asyncio.Event, status: _TelegramStatus) -> None:
    """텔레그램 시작·유지(OPS-1b): 시작(getMe) 실패가 일시적(네트워크)이면 지수 백오프로 다시 시도하고,
    그동안 스케줄 루프(모의 손절·추세 청산 감시)는 계속 돈다(메시지는 보관함에 쌓였다가 복구 뒤 전송).
    토큰 거부(InvalidToken)는 설정 오류라 봇을 멈춘다(재시도해도 소용없음). 예외 메시지는 기록하지 않는다(토큰 포함 가능).
    동작 중에는 5분마다 웹훅 설정을 점검한다(DT-05) — 성공하면 텔레그램 정상 신호로도 쓴다(OPS-2)."""
    from telegram.error import InvalidToken

    from bot import telegram_ui as tu

    loop = asyncio.get_running_loop()
    delay = TELEGRAM_RETRY_MIN_S
    while not stop.is_set():
        try:
            async with app:
                # run_polling을 쓰지 않으므로(우리 스케줄 루프와 같은 이벤트 루프) post_init(웹훅 확인·deleteWebhook)을 직접 부른다.
                if app.post_init is not None:
                    await app.post_init(app)
                await app.start()
                await app.updater.start_polling(**tu.POLLING_KWARGS)
                rt.health.ok(loop.time())
                status.settle("up")
                delay = TELEGRAM_RETRY_MIN_S
                try:
                    while not stop.is_set():
                        await _wait_or_stop(stop, WEBHOOK_CHECK_INTERVAL_S)
                        if stop.is_set():
                            break
                        try:
                            alert = await tu.check_webhook(app.bot, rt.conn, rt.cfg, now_ms=rt.engine.now_ms(),
                                                           lock=rt.engine.lock)
                            rt.health.ok(loop.time())
                            if alert is not None:
                                await tu.send_outgoing(transport, rt.engine, [alert])
                        except Exception as exc:  # noqa: BLE001 — 점검 실패 = 텔레그램 이상 신호(핑 중단 판단에 쓰임)
                            rt.health.fail(loop.time())
                            log.warning("웹훅 점검 실패: %s", type(exc).__name__)
                finally:
                    await app.updater.stop()
                    await app.stop()
            return
        except InvalidToken:
            status.fatal = "InvalidToken"
            log.error("텔레그램이 봇 토큰을 거부했다(InvalidToken) — 토큰 파일을 확인하라(RUNBOOK §8). 값은 기록하지 않는다")
            status.settle("fatal")
            stop.set()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — 일시 장애: 기다렸다 다시(메시지·트레이스백은 남기지 않음)
            rt.health.fail(loop.time())
            log.warning("텔레그램 시작 실패(%s) — %d초 뒤 재시도. 그동안 모의 감시는 계속", type(exc).__name__, int(delay))
            status.settle("retrying")
            await _wait_or_stop(stop, delay)
            delay = min(delay * 2, TELEGRAM_RETRY_MAX_S)
    status.settle("stopped")


async def run_paper(rt: PaperRuntime) -> int:
    """텔레그램 롱 폴링 + 스케줄 루프. SIGTERM/SIGINT에서 진행 중 작업을 끝내고 멈춘다.

    시작 중 외부 의존 실패는 봇을 죽이지 않는다(OPS-1): 시계 확인 실패는 경고로 남기고(사이클마다 다시 검사해 보류),
    텔레그램 일시 장애는 뒤에서 재시도한다. 텔레그램 토큰 거부만 설정 오류로 종료(EXIT_CONFIG)."""
    from bot import telegram_ui as tu
    from bot.marketdata import MarketDataError

    cfg = rt.cfg
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_loop_exception_handler)
    try:
        skew = await asyncio.to_thread(rt.market.check_clock)
        log.info("시계 오차 %s ms", skew)
    except MarketDataError as exc:
        log.warning("시작 시 시계·시세 확인 실패(%s) — 계속 실행, 사이클마다 다시 검사", type(exc).__name__)
        rt.startup_alerts.append(OutgoingMessage(
            text=(f"{cfg.mode_tag} 경고: 시작 시 바이낸스 시계·시세 확인 실패({type(exc).__name__}). 봇은 계속 돌고,"
                  " 일일 사이클은 시계가 맞을 때까지 보류된다(RUNBOOK §8)."), kind="alert"))
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover
            pass
    if not cfg.telegram.enabled:
        log.warning("텔레그램 비활성: 카드는 기록만 되고 승인할 수 없다(전부 만료)")
        rt.health.always_ok = True
        transport = RecordingTransport()
        await paper_loop(rt, transport, stop)
        return EXIT_OK
    app = tu.build_application(rt.secrets.telegram_token, rt.engine, rt.conn, cfg, clock=rt.clock,
                               db_lock=rt.engine.lock)
    transport = tu.PtbTransport.from_bot(app.bot, cfg.telegram.allowed_chat_id)
    status = _TelegramStatus()
    sup = asyncio.create_task(_telegram_supervisor(app, rt, transport, stop, status))
    await asyncio.wait({status.first, sup}, return_when=asyncio.FIRST_COMPLETED)
    first = status.first.result() if status.first.done() else "stopped"
    if first == "fatal":
        await sup
        return EXIT_CONFIG
    rt.startup_alerts.insert(0, OutgoingMessage(
        text=f"{cfg.mode_tag} 시작 v{BOT_VERSION} · 설정 지문 {cfg.fingerprint()[:8]}", kind="info"))
    if first == "up":
        rt.health.record(loop.time(), await tu.send_outgoing(transport, rt.engine, rt.startup_alerts))
        rt.startup_alerts.clear()
    try:
        await paper_loop(rt, transport, stop)
    finally:
        stop.set()
        try:
            await sup
        except Exception as exc:  # noqa: BLE001
            log.error("텔레그램 종료 중 오류: %s", type(exc).__name__)
    return EXIT_CONFIG if status.fatal else EXIT_OK


def cmd_run(cfg: BotConfig, secrets: Secrets, args: argparse.Namespace) -> int:
    try:
        rt = build_paper_runtime(cfg, secrets)
    except db.DbError as exc:
        _err(f"DB: {exc}")
        return EXIT_DB
    try:
        if args.dry_run:
            print(f"dry-run 통과: mode={cfg.mode.value} · 전략 {cfg.strategy_key} · 설정 지문 {cfg.fingerprint()[:8]}"
                  f" · 텔레그램 {'켜짐' if cfg.telegram.enabled else '꺼짐'} · Claude {'켜짐' if cfg.claude.enabled else '꺼짐'}"
                  " · 네트워크 호출 없음")
            return EXIT_OK
        rt.heartbeat_path = HEARTBEAT_PATH
        return asyncio.run(run_paper(rt))
    finally:
        close = getattr(rt.market, "close", None)
        if callable(close):
            close()
        rt.conn.close()


# ---------------------------------------------------------------------------
# check / backup
# ---------------------------------------------------------------------------


def cmd_check(cfg: BotConfig, secrets: Secrets) -> int:
    """설정·비밀 파일·DB 점검(네트워크 없음). 값은 출력하지 않는다."""
    try:
        conn = db.connect(cfg.db_path, mode=cfg.mode, now_ms=_now_ms_system())
    except db.DbError as exc:
        _err(f"DB: {exc}")
        return EXIT_DB
    try:
        n_sig = int(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
        paused = db.is_paused(conn)
    finally:
        conn.close()
    have = lambda s: "있음" if s is not None else "없음"  # noqa: E731
    print(f"점검 통과: mode={cfg.mode.value} · 전략 {cfg.strategy_key} · 설정 지문 {cfg.fingerprint()[:8]}")
    print(f"비밀 파일: 텔레그램 {have(secrets.telegram_token)} · Claude {have(secrets.anthropic_api_key)}"
          f" · 헬스체크 {have(secrets.ping_url)}")
    print(f"DB: 신호 {n_sig}건 · 신규 진입 {'일시정지' if paused else '받는 중'}")
    return EXIT_OK


def cmd_backup(cfg: BotConfig, args: argparse.Namespace) -> int:
    dest = Path(args.dest)
    if dest.exists():
        _err(f"백업 대상이 이미 있다(덮어쓰지 않음): {dest}")
        return EXIT_ERROR
    try:
        conn = db.connect(cfg.db_path, mode=cfg.mode, now_ms=_now_ms_system())
    except db.DbError as exc:
        _err(f"DB: {exc}")
        return EXIT_DB
    try:
        db.backup_to(conn, dest)
    finally:
        conn.close()
    print(f"백업 완료: {dest}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m bot.main", description="BTC 추세추종 모의 운영 봇(PAPER 전용)")
    p.add_argument("--config", required=True, help="설정 TOML 경로(bot.example.toml 참고)")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="설정·비밀 파일·DB 점검")
    r = sub.add_parser("run", help="paper 모드 실행(텔레그램 롱 폴링 + 스케줄)")
    r.add_argument("--dry-run", action="store_true", help="구성만 만들고 종료(네트워크 호출 없음)")
    rp = sub.add_parser("replay", help="과거 재생(replay 모드)")
    rp.add_argument("--exec-bars", default="backtest", choices=["backtest", "1m"],
                    help="체결·감시 봉: backtest=백테스트 실행 봉(5분+1분, 기본) / 1m=1분봉만(2023-10부터)")
    rp.add_argument("--trades-csv", default="", help="모의 포지션을 CSV로 저장할 경로")
    rp.add_argument("--cache-dir", default="", help="backtest 데이터 캐시 디렉터리(선택, 쓰기 가능해야 함)")
    b = sub.add_parser("backup", help="DB 온라인 백업")
    b.add_argument("--dest", required=True, help="백업 파일 경로(없는 파일)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, *, environ=None) -> int:
    os.umask(0o077)                                  # 1) DB·WAL·백업 파일 0600
    args = parse_args(argv)
    bad_env = check_env_no_secrets(environ)          # 2) 비밀은 파일로만
    if bad_env:
        _err("비밀로 보이는 환경 변수가 있어 시작하지 않는다(값은 보지 않음): " + ", ".join(bad_env)
             + " — 비밀은 /run/secrets 파일로만 넘긴다")
        return EXIT_CONFIG
    try:                                             # 3) 설정 → 비밀 파일
        cfg = load_config(args.config)
        secrets = load_secrets(cfg) if args.command in ("check", "run") else Secrets()
    except ConfigError as exc:
        _err(str(exc))
        return EXIT_CONFIG
    handler = setup_logging(secrets, level=getattr(logging, args.log_level))
    import threading

    prev_hooks = (sys.excepthook, threading.excepthook)
    install_excepthooks(secrets)                     # 잡히지 않은 예외도 가림을 거친다(SEC-01)
    try:
        if args.command == "check":
            return cmd_check(cfg, secrets)
        if args.command == "run":
            if cfg.mode not in (Mode.PAPER, Mode.TESTNET):
                _err("run 명령은 mode = \"paper\" 또는 \"testnet\" 설정에서만 쓴다(재생은 replay 명령)")
                return EXIT_CONFIG
            return cmd_run(cfg, secrets, args)
        if args.command == "replay":
            return cmd_replay(cfg, args)
        if args.command == "backup":
            return cmd_backup(cfg, args)
        return EXIT_ERROR  # pragma: no cover (argparse가 막음)
    except ConfigError as exc:
        _err(str(exc))
        return EXIT_CONFIG
    except db.DbError as exc:
        _err(f"DB: {exc}")
        return EXIT_DB
    except Exception as exc:  # noqa: BLE001 — 마지막 방어선: 메시지는 가림 필터를 거친 로그로만, 트레이스백 없음
        log.error("처리되지 않은 오류로 종료: %s", type(exc).__name__)
        _err(f"처리되지 않은 오류로 종료({type(exc).__name__}) — 로그 확인(RUNBOOK §8)")
        return EXIT_ERROR
    finally:
        logging.getLogger().removeHandler(handler)
        sys.excepthook, threading.excepthook = prev_hooks


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
