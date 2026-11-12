"""pilot.py가 연구 코드(candle_features, pilot_analysis)와 같은 값을 내는지 확인한다.
실행: .venv/bin/python -m pytest research/pilot5 -q
"""
import csv
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "research" / "candles"))

import candle_features as cf  # noqa: E402
import pilot  # noqa: E402
import pilot_analysis as pa  # noqa: E402

DATA = str(ROOT / "data" / "binance" / "BTCUSDT_4h.csv.gz")


@pytest.fixture(scope="module")
def bars():
    return pilot.read_file(DATA, None)


@pytest.fixture(scope="module")
def sig():
    return pa.rule_signals()


def test_thresholds_match_research(sig):
    assert pilot.Q80 == pytest.approx(sig.attrs["q80"], abs=1e-12)
    assert pilot.Q20 == pytest.approx(sig.attrs["q20"], abs=1e-12)


def test_upper_vol_and_signal_match_research(bars, sig):
    assert len(bars) == len(sig)
    x_ref, pos_ref = sig["x"].to_numpy(), sig["pos"].to_numpy()
    checked = 0
    for i in range(cf.WARMUP, len(bars)):
        res = pilot.upper_vol(bars, i)
        if res is None:
            assert not np.isfinite(x_ref[i])
            continue
        assert res[2] == pytest.approx(x_ref[i], rel=1e-9, abs=1e-12)
        assert pilot.signal_of(res[2]) == pos_ref[i]
        checked += 1
    assert checked > 14000


def test_slot_is_21_kst(bars, sig):
    for i in (100, 101, 102, 103, 104, 105):
        assert pilot.is_slot(bars[i]) == (sig["open_hour"].iloc[i] == 8)
        if pilot.is_slot(bars[i]):
            assert pilot.kst(bars[i][0] + pilot.MS_4H, "%H:%M") == "21:00"


def test_paper_matches_research(bars, sig):
    start = int(sig["open_time"].iloc[-600])
    rows = pilot.evaluate(bars, start)
    ref = sig[(sig["open_time"] >= start) & sig["exit_close"].notna()]
    assert len(rows) == len(ref)
    mine = np.array([r["r"] for r in rows if r["sig"] == 1])
    theirs = ref[ref.pos > 0]["r"].to_numpy()
    assert len(mine) == len(theirs) and mine.mean() == pytest.approx(theirs.mean(), rel=1e-9)


def test_now_prints_ticket_and_logs(bars, sig, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pilot, "HERE", tmp_path)
    s = sig[(sig.pos > 0) & (sig.open_hour == 8)].iloc[-1]
    i = int(np.where(sig["open_time"].to_numpy() == s.open_time)[0][0])
    cut = tmp_path / "k.csv"
    with cut.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["open_time", "open", "high", "low", "close", "volume"])
        for b in bars[i - 40:i + 1]:
            w.writerow(b)
    args = type("A", (), dict(file=str(cut), now_ms=int(s.open_time) + pilot.MS_4H + 3 * 60_000))()
    pilot.cmd_now(args)
    out = capsys.readouterr().out
    assert "신호: 롱" in out and "주문표" in out and "21:00 KST에 마감" in out
    rows = list(csv.DictReader((tmp_path / "signals_log.csv").open(encoding="utf-8-sig")))
    assert rows[-1]["signal"] == "롱" and rows[-1]["real"] == "Y"
    # 16분 늦으면 주문표가 나오지 않는다
    args.now_ms = int(s.open_time) + pilot.MS_4H + 16 * 60_000
    pilot.cmd_now(args)
    out = capsys.readouterr().out
    assert "주문표" not in out and "건너뜁니다" in out


def test_score_computes_shortfall(bars, sig, tmp_path, capsys):
    s = sig[(sig.pos > 0) & (sig.open_hour == 8) & sig["exit_close"].notna()].iloc[-1]
    date = s.time.strftime("%Y-%m-%d")
    entry, exitp = s.close + 5.0, s.exit_close - 5.0  # 모의보다 10달러 불리하게 체결
    j = tmp_path / "journal.csv"
    with j.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow("date,my_guess,checked,traded,entry_time,entry_price,entry_type,exit_time,exit_price,exit_type,fee_usdt,funding_usdt,rule_ok,note".split(","))
        w.writerow([date, "L", "Y", "Y", "21:02", entry, "L", "13:01", exitp, "L", 0.03, -0.01, "Y", ""])
    args = type("A", (), dict(journal=str(j), file=DATA, now_ms=None, start_usdt=35.76, krw=1360.0))()
    pilot.cmd_score(args)
    out = capsys.readouterr().out
    live = ((exitp - entry) * 0.001 - 0.03 - 0.01) / (entry * 0.001)
    paper = s.exit_close / s.close - 1
    assert f"실행 손해 {(live - paper) * 100:+.3f}%p" in out
    assert "규칙 밖 주문 0번" in out and "롱 신호 1번 중 실행 1번" in out
