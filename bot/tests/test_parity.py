"""대조 시험 — 재생(replay) 모의 거래 == 백테스트 E0-L-ENS 거래 (통합 담당, bot/DESIGN.md §3.5).

재생 모드에서 모든 카드를 '판단 + 30분'에 자동 승인·확인하면(백테스트 L=30분과 대응) 모의 거래가
backtest.trend.run_trend_combo(TrendConfig('E0','L'))의 체결 거래와 같아야 한다.

비교 항목과 허용 오차 (명시)
- 정확히 같아야 함: 거래 수, 하위 시스템 N, 방향, 신호 일봉 마감 시각, 진입 시각, 청산 시각, 청산 사유
- 가격(진입가·손절·청산가·R 분모): 절대 오차 1e-9 (같은 식·같은 입력이라 실제로는 0)
- 수수료·슬리피지: 절대 오차 1e-9
- 펀딩·순손익·R: 상대 오차 1e-9 (+ 절대 1e-9) — 펀딩 합산 순서만 다름(백테스트 np.sum vs DB 행 누적)
- 데이터 끝에서 백테스트가 'eod'로 닫은 거래: 모의는 계속 보유(OPEN) → 진입 항목만 비교(DESIGN §3.6)

데이터
① 합성 trend_market_small(260일, 체결 8건) — 항상 실행
② 실데이터 2020-01-01 ~ 2026-09-28 전체(@slow): 기준 = backtest/results_trend/trades/E0-L-ENS.csv(G1-T 공식 결과)
   재생 시세 = main.build_replay_market(exec_bars='backtest'): 백테스트와 같은 실행 봉(2023-10 전 5분봉 + 이후 1분봉)과
   같은 펀딩(파일 끝 뒤 §12.2 대체값 포함).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import trend as TR
from backtest.types import ExecArrays, FundingArrays, records_frame
from bot import db
from bot import main as M
from bot import telegram_ui as tu
from bot.engine import Engine
from bot.marketdata import Replay
from bot.tests.conftest import ALLOWED_CHAT_ID, ALLOWED_USER_ID, FrameMarket, make_config
from bot.types import (
    NS_PER_MIN,
    FakeClock,
    Mode,
    SignalState,
    make_callback_data,
    CallbackAction,
    ns_to_ms,
)

REPO = Path(__file__).resolve().parents[2]
TRADES_CSV = REPO / "backtest" / "results_trend" / "trades" / "E0-L-ENS.csv"
DATA_DIR = REPO / "data" / "binance"

PRICE_ATOL = 1e-9
COST_ATOL = 1e-9
REL_TOL = 1e-9


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


def replay_config(tmp_path, **over):
    base = {"telegram.enabled": False, "claude.enabled": False}
    base.update(over)
    return make_config(tmp_path, mode="replay", db_path=":memory:", **base)


def backtest_trades(market) -> pd.DataFrame:
    """합성 시장에서 백테스트 E0-L-ENS 체결 거래(records_frame 열 이름 = trades CSV와 같다)."""
    daily = TR.DailyData.from_frame(market.bars["1d"])
    trades, _ = TR.run_trend_combo(daily, TR.TrendConfig("E0", "L"), ExecArrays.from_frame(market.exec_bars),
                                   FundingArrays.from_frame(market.funding))
    df = records_frame(TR.filled(trades))
    df.insert(0, "n", [t.meta.get("n") for t in TR.filled(trades)])
    return df


def run_replay(cfg, market, clock, *, latency_min, end_ns=None):
    """main.run_replay_loop 그대로(재생 명령과 같은 경로). 반환 (conn, engine, 요약, 전송 기록)."""
    daily = market.bars["1d"] if hasattr(market, "bars") else None
    close_ns = daily["close_ns"].to_numpy() if daily is not None else market._daily_close
    decisions = M.replay_decision_times(cfg, close_ns)
    clock.set(decisions[0])
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(decisions[0]))
    mk = market if not hasattr(market, "bars") else Replay.from_frames(
        market.bars["1d"], market.exec_bars, market.funding, clock)
    eng = Engine(conn, cfg, mk, None, clock)
    tx = M.RecordingTransport(keep_text=True)
    summ = M.run_replay_loop(eng, clock, tx, decisions, auto_approve_latency_min=latency_min,
                             end_ns=end_ns if end_ns is not None else int(close_ns[-1]))
    return conn, eng, summ, tx


def compare(bot_rows: list[dict], bt: pd.DataFrame) -> dict:
    """DESIGN §3.5 비교. 어긋나면 AssertionError(첫 불일치 위치와 값). 반환 = 최대 오차 요약."""
    bt = bt.sort_values(["entry_time_ns", "n"], kind="stable").reset_index(drop=True)
    assert len(bot_rows) == len(bt), f"거래 수 다름: 모의 {len(bot_rows)} vs 백테스트 {len(bt)}"
    worst = {"price": 0.0, "cost": 0.0, "rel": 0.0}
    for i, (p, b) in enumerate(zip(bot_rows, bt.to_dict("records"))):
        where = f"#{i} N{b['n']} 진입 {b['entry_time']}"
        assert int(p["subsystem_n"]) == int(b["n"]), where
        assert int(p["side"]) == int(b["side"]), where
        assert int(p["signal_close_ms"]) * 1_000_000 == int(b["signal_time_ns"]), where
        assert int(p["entry_ms"]) * 1_000_000 == int(b["entry_time_ns"]), where
        assert int(p["approved_ms"]) * 1_000_000 == int(b["active_from_ns"]), where
        for bk, pk in (("entry_price", "entry_price"), ("stop", "stop"), ("risk_per_unit", "risk_per_unit")):
            d = abs(float(p[pk]) - float(b[bk]))
            worst["price"] = max(worst["price"], d)
            assert d <= PRICE_ATOL, f"{where} {bk}: {p[pk]} vs {b[bk]}"
        if b["exit_reason"] == "eod":           # 데이터 끝: 백테스트 강제 청산, 모의는 보유 중
            assert p["state"] == "OPEN" and p["exit_ms"] is None, where
            continue
        assert p["state"] == "CLOSED", where
        assert int(p["exit_ms"]) * 1_000_000 == int(b["exit_time_ns"]), f"{where} 청산 시각"
        assert p["exit_reason"] == b["exit_reason"], f"{where} 사유 {p['exit_reason']} vs {b['exit_reason']}"
        d = abs(float(p["exit_price"]) - float(b["exit_price"]))
        worst["price"] = max(worst["price"], d)
        assert d <= PRICE_ATOL, f"{where} 청산가"
        for k in ("fees", "slippage"):
            d = abs(float(p[k]) - float(b[k]))
            worst["cost"] = max(worst["cost"], d)
            assert d <= COST_ATOL, f"{where} {k}: {p[k]} vs {b[k]}"
        for k in ("funding", "net_pnl", "r_multiple"):
            assert math.isclose(float(p[k]), float(b[k]), rel_tol=REL_TOL, abs_tol=1e-9), \
                f"{where} {k}: {p[k]} vs {b[k]}"
            if float(b[k]) != 0:
                worst["rel"] = max(worst["rel"], abs(float(p[k]) - float(b[k])) / abs(float(b[k])))
    return worst


# ---------------------------------------------------------------------------
# ① 합성 시장 (항상)
# ---------------------------------------------------------------------------


def test_synthetic_replay_matches_backtest(tmp_path, trend_market_small):
    cfg = replay_config(tmp_path)
    clock = FakeClock(0)
    conn, eng, summ, tx = run_replay(cfg, trend_market_small, clock, latency_min=30)
    bt = backtest_trades(trend_market_small)
    assert len(bt) == 8                                  # conftest가 보장하는 합성 시장 성질
    compare(M.export_positions(conn), bt)
    assert summ.failed_cycles == 0
    assert summ.approved == summ.positions == len(bt)
    # 신호는 전부 승인됐고, 체결된 신호만 FILLED/CLOSED (패스·만료 없음)
    states = {r["state"] for r in conn.execute("SELECT state FROM signals")}
    assert states <= {"FILLED", "CLOSED"}
    # 원장: 포지션마다 ENTRY 1, 청산이면 EXIT 1
    n_entry = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE kind='ENTRY'").fetchone()[0]
    n_exit = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE kind='EXIT'").fetchone()[0]
    assert n_entry == summ.positions and n_exit == summ.closed


def test_synthetic_no_future_lookup(tmp_path, trend_market_small):
    """재생 중 미래 조회 0건: FrameMarket은 until > now 조회를 LookaheadError로 막는다(삼키지 않게 AssertionError 계열)."""
    cfg = replay_config(tmp_path)
    clock = FakeClock(0)
    fm = FrameMarket(trend_market_small.bars["1d"], trend_market_small.exec_bars, trend_market_small.funding, clock)
    close_ns = trend_market_small.bars["1d"]["close_ns"].to_numpy()
    decisions = M.replay_decision_times(cfg, close_ns)
    clock.set(decisions[0])
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(decisions[0]))
    eng = Engine(conn, cfg, fm, None, clock)
    summ = M.run_replay_loop(eng, clock, M.RecordingTransport(), decisions, auto_approve_latency_min=30,
                             end_ns=int(close_ns[-1]))
    assert summ.failed_cycles == 0 and summ.positions == 8
    compare(M.export_positions(conn), backtest_trades(trend_market_small))


def test_replay_market_records_max_until_not_past_clock(tmp_path, trend_market_small):
    cfg = replay_config(tmp_path)
    clock = FakeClock(0)
    conn, eng, summ, _ = run_replay(cfg, trend_market_small, clock, latency_min=30)
    assert summ.max_until_ns is not None and summ.max_until_ns <= clock.now_ns()


def test_no_auto_approve_all_expire(tmp_path, trend_market_small):
    """자동 승인 없음(None) → 카드는 나가지만 전부 만료, 모의 포지션 0."""
    cfg = replay_config(tmp_path, **{"replay.auto_approve_latency_min": None})
    clock = FakeClock(0)
    conn, eng, summ, tx = run_replay(cfg, trend_market_small, clock, latency_min=None)
    assert summ.positions == 0 and summ.approved == 0
    states = [r["state"] for r in conn.execute("SELECT state FROM signals")]
    assert states and set(states) == {"EXPIRED"}
    # 만료되면 카드 메시지를 고친다(버튼 제거)
    assert len(tx.edits) == len(states) and all(not b for _, _, b in tx.edits)
    # 사람이 패스·만료하면 하위 시스템은 비어 있어 다음 날 새 신호가 날 수 있다(§3.6) → 백테스트 진입 수 이상
    assert len(states) >= len(backtest_trades(trend_market_small))


def test_replay_is_idempotent_on_rerun(tmp_path, trend_market_small):
    """같은 DB로 같은 기간을 다시 돌려도(재시작 가정: 새 시계·새 엔진) 신호·포지션·원장이 늘지 않는다."""
    cfg = replay_config(tmp_path)
    clock = FakeClock(0)
    conn, eng, summ, _ = run_replay(cfg, trend_market_small, clock, latency_min=30)

    def snapshot():
        return ([tuple(r) for r in conn.execute("SELECT signal_id, state FROM signals ORDER BY signal_id")],
                [tuple(r) for r in conn.execute("SELECT position_id, state, exit_ms, r_multiple FROM paper_positions")],
                conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0])

    before = snapshot()
    close_ns = trend_market_small.bars["1d"]["close_ns"].to_numpy()
    decisions = M.replay_decision_times(cfg, close_ns)
    clock2 = FakeClock(decisions[0])
    mk = trend_market_small
    eng2 = Engine(conn, cfg, Replay.from_frames(mk.bars["1d"], mk.exec_bars, mk.funding, clock2), None, clock2)
    summ2 = M.run_replay_loop(eng2, clock2, M.RecordingTransport(), decisions, auto_approve_latency_min=30,
                              end_ns=int(close_ns[-1]))
    assert summ2.approved == 0
    assert snapshot() == before


def test_end_to_end_buttons_with_real_engine(tmp_path, trend_market_small):
    """실제 Engine + telegram_ui.handle_callback(버튼 경로)로 [승인]→[확인]을 눌러도 백테스트와 같다.

    재생 모드이지만 텔레그램 권한 검사까지 타도록 telegram.enabled 설정(가짜 전송, 네트워크 없음).
    확인 버튼은 판단 + 30분, 승인 버튼은 그 30초 전.
    """
    cfg = make_config(tmp_path, mode="replay", db_path=":memory:", **{"claude.enabled": False})
    clock = FakeClock(0)
    mk_src = trend_market_small
    close_ns = mk_src.bars["1d"]["close_ns"].to_numpy()
    decisions = M.replay_decision_times(cfg, close_ns)
    clock.set(decisions[0])
    conn = db.connect(":memory:", mode=Mode.REPLAY, now_ms=ns_to_ms(decisions[0]))
    market = Replay.from_frames(mk_src.bars["1d"], mk_src.exec_bars, mk_src.funding, clock)
    eng = Engine(conn, cfg, market, None, clock)
    tx = M.RecordingTransport(keep_text=True)
    qid = 0

    def click(sig, action):
        nonlocal qid
        qid += 1
        ctx = tu.CallbackContext(callback_query_id=f"q{qid}", update_id=qid, from_user_id=ALLOWED_USER_ID,
                                 chat_id=ALLOWED_CHAT_ID, chat_type="private", message_id=int(sig["tg_message_id"]),
                                 data=make_callback_data(action, sig["signal_id"]))
        out = tu.handle_callback(eng, conn, cfg, ctx, ns_to_ms(clock.now_ns()))
        M.asyncio.run(tu.apply_outcome(tx, ctx, out))
        return out

    for dec in decisions:
        clock.set(max(clock.now_ns(), dec))
        M.deliver(tx, eng, eng.tick())
        M.deliver(tx, eng, eng.run_daily_cycle().outgoing)
        todays = [s for s in db.signals_in_states(conn, [SignalState.CARD_SENT]) if s["decision_ms"] == ns_to_ms(dec)]
        if todays:
            clock.set(dec + 30 * NS_PER_MIN - 30 * 1_000_000_000)
            for s in todays:
                click(s, CallbackAction.APPROVE)
            clock.set(dec + 30 * NS_PER_MIN)
            for s in todays:
                s = db.get_signal(conn, s["signal_id"])
                assert s["state"] == "CONFIRM_PENDING"
                click(s, CallbackAction.CONFIRM)
                assert db.get_signal(conn, s["signal_id"])["state"] == "APPROVED"
    clock.set(max(clock.now_ns(), int(close_ns[-1])))
    M.deliver(tx, eng, eng.tick())
    compare(M.export_positions(conn), backtest_trades(mk_src))
    # 승인 지연 기록 = 30분
    lat = {r[0] for r in conn.execute("SELECT approval_latency_ms FROM signals WHERE approved_ms IS NOT NULL")}
    assert lat == {30 * 60 * 1000}


# ---------------------------------------------------------------------------
# ② 실데이터 전체 기간 (slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not (TRADES_CSV.exists() and (DATA_DIR / "BTCUSDT_1d.csv.gz").exists()),
                    reason="실데이터 또는 G1-T 거래 파일 없음")
def test_real_data_full_period_matches_g1t_trades(tmp_path):
    """2020-01-01 ~ 2026-09-28 전체를 재생(자동 승인 30분) → G1-T 공식 E0-L-ENS 거래 100건과 대조."""
    cfg = replay_config(tmp_path, **{"replay.start": "2020-01-01", "replay.end": "2026-09-29",
                                     "marketdata.data_dir": str(DATA_DIR)})
    clock = FakeClock(0)
    cache = C.CACHE_DIR if Path(C.CACHE_DIR).is_dir() else None
    market = M.build_replay_market(cfg, clock, exec_bars="backtest", cache_dir=cache)
    conn, eng, summ, tx = run_replay(cfg, market, clock, latency_min=30)
    bt = pd.read_csv(TRADES_CSV)
    bt = bt[bt["status"] == "filled"]
    worst = compare(M.export_positions(conn), bt)
    assert summ.failed_cycles == 0
    assert summ.positions == len(bt) == 100
    assert summ.open_at_end == int((bt["exit_reason"] == "eod").sum())
    assert summ.max_until_ns <= clock.now_ns()
    # 합계 R(청산분)도 같아야 한다
    closed = bt[bt["exit_reason"] != "eod"]
    bot_r = conn.execute("SELECT SUM(r_multiple) FROM paper_positions WHERE state='CLOSED'").fetchone()[0]
    assert math.isclose(bot_r, float(closed["r_multiple"].sum()), rel_tol=1e-9)
    assert worst["price"] <= PRICE_ATOL
