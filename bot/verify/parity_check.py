"""독립 대조 스크립트 — 재생(replay) 모의 거래 vs 백테스트 E0-L-ENS 거래 vs 원자료 재계산.

검증관이 따로 쓴 것이다. `bot`·`backtest` 패키지를 **하나도 import하지 않는다**(pandas·numpy·표준 라이브러리만).
그래서 두 구현이 같은 버그를 공유하더라도 ③ 원자료 재계산에서 드러난다.

비교 세 가지
① 재생 CSV(bot.main replay --trades-csv) == 백테스트 CSV(backtest/results_trend/trades/E0-L-ENS.csv)
② 백테스트 CSV == 원자료(data/binance) 에서 TREND_SPEC v1.0 문장만 보고 다시 짠 시뮬레이터
③ 재생 CSV == 원자료 시뮬레이터

TREND_SPEC v1.0 해석(이 스크립트가 쓴 것, 명세 문장 그대로)
- U_N = 직전 N개 일봉(당일 제외) 종가 최댓값, D_M = 직전 M개 종가 최솟값, M = {20:10, 55:28, 100:50}
- 롱 진입: 당일 종가 > U_N 이고 그 하위 시스템이 판단 시각에 포지션이 없음
  (판단 시각 = 일봉 마감 + 60초; 청산 봉이 판단 시각 이후에 마감하면 아직 보유로 본다)
- 활성 = 판단 + 30분, 체결 = 활성 이후 첫 실행 봉 시가 (실행 봉: 2023-10-01 전 5분봉, 이후 1분봉)
- 보호 손절 = 진입가 − 2 × ATR20(신호 일; 직전 20개 TR 단순 평균·현재 봉 제외, RULES_SPEC §3), 0.1 USDT 반올림
  (RULES_SPEC §6 공통), 진입 봉부터 활성, 갭이면 그 봉 시가
- 추세 청산: 진입 뒤 일봉 종가 < D_M → 그 판단 + 30분 이후 첫 실행 봉 시가
- 비용: 테이커 0.05% + 슬리피지 0.02% (진입·청산 가격 각각), 펀딩 = min(진입 봉, 활성) < f ≤ 청산 봉 마다
  비율 × 그 시각 가격(f를 포함하는 실행 봉 시가)
  (2026-09-01 이후 펀딩 파일이 없는 구간은 0.01%/8h 대체값). R = 순손익 ÷ (d + 0.0007 × (진입가 + 손절가))

사용법
  .venv/bin/python bot/verify/parity_check.py --replay-csv /path/pos.csv [--json out.json]
종료 코드 0 = 모든 필수 항목 통과, 1 = 불일치.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "binance"
BT_CSV = REPO / "backtest" / "results_trend" / "trades" / "E0-L-ENS.csv"

MS_MIN = 60_000
MS_DAY = 86_400_000
CUTOVER_MS = 1_696_118_400_000      # 2023-10-01T00:00:00Z: 이 시각부터 1분봉
TAKER = 0.0005
SLIP = 0.0002
LATENCY_MS = 30 * MS_MIN
DECISION_DELAY_MS = 60_000
M_OF = {20: 10, 55: 28, 100: 50}
FUNDING_FALLBACK_FROM_MS = 1_788_220_800_000   # 2026-09-01T00:00:00Z
FUNDING_FALLBACK_RATE = 0.0001

PRICE_ATOL = 1e-9
COST_ATOL = 1e-9
REL_TOL = 1e-9


def iso(ms) -> str:
    if ms is None or (isinstance(ms, float) and math.isnan(ms)):
        return ""
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 원자료
# ---------------------------------------------------------------------------


def load_daily() -> pd.DataFrame:
    d = pd.read_csv(DATA / "BTCUSDT_1d.csv.gz", usecols=["open_time", "open", "high", "low", "close"])
    d = d.sort_values("open_time").reset_index(drop=True)
    assert (np.diff(d["open_time"].to_numpy()) == MS_DAY).all(), "일봉 구멍"
    return d


def load_exec() -> pd.DataFrame:
    cols = ["open_time", "open", "high", "low", "close"]
    five = pd.read_csv(DATA / "BTCUSDT_5m.csv.gz", usecols=cols)
    five = five[five["open_time"] < CUTOVER_MS].assign(len_ms=5 * MS_MIN)
    ones = [pd.read_csv(p, usecols=cols) for p in sorted(DATA.glob("BTCUSDT_1m_*.csv.gz"))]
    one = pd.concat(ones)
    one = one[one["open_time"] >= CUTOVER_MS].assign(len_ms=MS_MIN)
    x = pd.concat([five, one]).sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    return x


def load_funding(until_ms: int) -> tuple[np.ndarray, np.ndarray]:
    f = pd.read_csv(DATA / "BTCUSDT_fundingRate.csv.gz")
    t = f["calc_time"].to_numpy(np.int64)
    # calc_time은 정시 + 0~47ms로 기록된다. 정시로 내림(backtest/DESIGN.md I-35와 같은 해석). 내리지 않으면
    # '청산 봉 시작 == 펀딩 정시'인 경계(예: 2023-02-24 16:00 손절)에서 펀딩 1회가 빠진다.
    t = (t // 3_600_000) * 3_600_000
    r = f["last_funding_rate"].to_numpy(float)
    last = int(t[-1])
    extra_t = []
    k = FUNDING_FALLBACK_FROM_MS
    while k <= until_ms:
        if k > last:
            extra_t.append(k)
        k += 8 * 3600 * 1000
    t = np.concatenate([t, np.array(extra_t, dtype=np.int64)])
    r = np.concatenate([r, np.full(len(extra_t), FUNDING_FALLBACK_RATE)])
    return t, r


# ---------------------------------------------------------------------------
# 독립 시뮬레이터 (TREND_SPEC v1.0, E0, 롱만, 앙상블)
# ---------------------------------------------------------------------------


def atr_sma(d: pd.DataFrame, n: int) -> np.ndarray:
    h, l, c = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr[0] = np.nan                       # 첫 봉은 이전 종가 없음
    # RULES_SPEC §3 "직전 n개 봉" = 현재 봉 제외(TREND_SPEC U_N의 "직전 N개(당일 제외)"와 같은 말)
    return pd.Series(tr).rolling(n, min_periods=n).mean().shift(1).to_numpy()


class Sim:
    def __init__(self) -> None:
        self.d = load_daily()
        self.x = load_exec()
        self.xo = self.x["open_time"].to_numpy(np.int64)
        self.xopen = self.x["open"].to_numpy(float)
        self.xlow = self.x["low"].to_numpy(float)
        self.xlen = self.x["len_ms"].to_numpy(np.int64)
        self.ft, self.fr = load_funding(int(self.xo[-1] + self.xlen[-1]))
        self.atr20 = atr_sma(self.d, 20)
        self.close = self.d["close"].to_numpy(float)
        self.day_close_ms = self.d["open_time"].to_numpy(np.int64) + MS_DAY

    def first_bar_at_or_after(self, t_ms: int) -> int | None:
        k = int(np.searchsorted(self.xo, t_ms, side="left"))
        return k if k < len(self.xo) else None

    def price_at(self, t_ms: np.ndarray) -> np.ndarray:
        """펀딩 시각의 가격 = 그 시각을 포함하는 실행 봉의 시가(없으면 그 뒤 첫 봉)."""
        k = np.searchsorted(self.xo, t_ms, side="right") - 1
        k = np.clip(k, 0, len(self.xo) - 1)
        inside = (self.xo[k] <= t_ms) & (t_ms < self.xo[k] + self.xlen[k])
        k2 = np.where(inside, k, np.minimum(k + 1, len(self.xo) - 1))
        return self.xopen[k2]

    def funding(self, entry_ms: int, exit_ms: int) -> float:
        m = (self.ft > entry_ms) & (self.ft <= exit_ms)
        if not m.any():
            return 0.0
        return float(np.sum(self.fr[m] * self.price_at(self.ft[m])))

    def run(self) -> list[dict]:
        out: list[dict] = []
        c = self.close
        for n in (20, 55, 100):
            m = M_OF[n]
            busy_until = -1          # 청산 봉 마감 시각(ms); None = 끝까지 보유
            i = n
            while i < len(c):
                dec = int(self.day_close_ms[i]) + DECISION_DELAY_MS
                if busy_until is None:
                    break
                level = c[i - n:i].max()
                if not (c[i] > level) or busy_until > dec or np.isnan(self.atr20[i]):
                    i += 1
                    continue
                ke = self.first_bar_at_or_after(dec + LATENCY_MS)
                if ke is None:
                    break
                entry = float(self.xopen[ke])
                entry_ms = int(self.xo[ke])
                stop = round(entry - 2.0 * float(self.atr20[i]), 1)   # RULES_SPEC §6 공통: 가격 0.1 USDT 반올림
                # 추세 청산 후보: 진입 뒤 판단 시각이 오는 첫 날 j(> i)에서 종가 < D_M
                kt = None
                jt = None
                for j in range(i + 1, len(c)):
                    if c[j] < c[j - m:j].min():
                        jt = j
                        kt = self.first_bar_at_or_after(int(self.day_close_ms[j]) + DECISION_DELAY_MS + LATENCY_MS)
                        break
                hi = kt if kt is not None else len(self.xo)
                hits = np.nonzero(self.xlow[ke:hi] <= stop)[0]
                if len(hits):
                    ks = ke + int(hits[0])
                    exit_price = float(min(self.xopen[ks], stop))
                    kx, reason = ks, "stop"
                elif kt is not None:
                    kx, reason, exit_price = kt, "trend", float(self.xopen[kt])
                else:
                    kx, reason, exit_price = None, "open", float("nan")
                rec = dict(n=n, signal_close_ms=int(self.day_close_ms[i]), entry_ms=entry_ms, entry_price=entry,
                           stop=stop, risk_per_unit=(entry - stop) + (TAKER + SLIP) * (entry + stop),
                           atr20=float(self.atr20[i]), level=float(level))
                if kx is None:
                    rec.update(exit_ms=None, exit_price=None, exit_reason="open")
                    out.append(rec)
                    busy_until = None
                    break
                exit_ms = int(self.xo[kx])
                fees = TAKER * (entry + exit_price)
                slip = SLIP * (entry + exit_price)
                # 펀딩 창 시작 = min(체결 봉 시작, 활성 시각) (RULES_SPEC §12.2 해석 I-35: 시장가는 활성 시각에 낸 것으로)
                fund = self.funding(min(entry_ms, dec + LATENCY_MS), exit_ms)
                gross = exit_price - entry
                net = gross - fees - slip - fund
                rec.update(exit_ms=exit_ms, exit_price=exit_price, exit_reason=reason, fees=fees, slippage=slip,
                           funding=fund, gross_pnl=gross, net_pnl=net, r_multiple=net / rec["risk_per_unit"])
                out.append(rec)
                busy_until = int(self.xo[kx] + self.xlen[kx])
                # 다음 진입 후보는 신호 다음 날부터(보유 중 판단은 busy_until로 걸러짐)
                i += 1
        out.sort(key=lambda r: (r["entry_ms"], r["n"]))
        return out


# ---------------------------------------------------------------------------
# 표준화
# ---------------------------------------------------------------------------


def norm_backtest(path: Path) -> list[dict]:
    b = pd.read_csv(path)
    rows = []
    for r in b.itertuples(index=False):
        eod = r.exit_reason == "eod"
        rows.append(dict(
            n=int(r.n), signal_close_ms=int(r.signal_time_ns) // 1_000_000, entry_ms=int(r.entry_time_ns) // 1_000_000,
            entry_price=float(r.entry_price), stop=float(r.stop), risk_per_unit=float(r.risk_per_unit),
            exit_ms=None if eod else int(r.exit_time_ns) // 1_000_000,
            exit_price=None if eod else float(r.exit_price),
            exit_reason="open" if eod else r.exit_reason,
            fees=float(r.fees), slippage=float(r.slippage), funding=float(r.funding),
            gross_pnl=float(r.gross_pnl), net_pnl=float(r.net_pnl), r_multiple=float(r.r_multiple),
            eod=eod, meta=json.loads(r.meta)))
    rows.sort(key=lambda r: (r["entry_ms"], r["n"]))
    return rows


def norm_replay(path: Path) -> list[dict]:
    p = pd.read_csv(path)
    rows = []
    for r in p.itertuples(index=False):
        open_ = r.state != "CLOSED"
        rows.append(dict(
            n=int(r.subsystem_n), side=int(r.side), state=r.state, signal_close_ms=int(r.signal_close_ms),
            decision_ms=int(r.decision_ms), approved_ms=int(r.approved_ms), entry_ms=int(r.entry_ms),
            entry_price=float(r.entry_price), stop=float(r.stop), risk_per_unit=float(r.risk_per_unit),
            exit_ms=None if open_ else int(r.exit_ms), exit_price=None if open_ else float(r.exit_price),
            exit_reason="open" if open_ else r.exit_reason,
            fees=float(r.fees), slippage=float(r.slippage), funding=float(r.funding),
            gross_pnl=float(r.gross_pnl), net_pnl=float(r.net_pnl), r_multiple=float(r.r_multiple)))
    rows.sort(key=lambda r: (r["entry_ms"], r["n"]))
    return rows


# ---------------------------------------------------------------------------
# 비교
# ---------------------------------------------------------------------------

EXACT = ("n", "signal_close_ms", "entry_ms")
EXACT_CLOSED = ("exit_ms", "exit_reason")
PRICE = ("entry_price", "stop", "risk_per_unit")
PRICE_CLOSED = ("exit_price",)
COST_CLOSED = ("fees", "slippage")
REL_CLOSED = ("funding", "gross_pnl", "net_pnl", "r_multiple")


def compare(a: list[dict], b: list[dict], name_a: str, name_b: str, *, rel_tol: float = REL_TOL,
            skip_closed_if=lambda ra, rb: False) -> dict:
    res = dict(pair=f"{name_a} vs {name_b}", count_a=len(a), count_b=len(b), mismatches=[], max_err={},
               compared_closed=0, open_only=0)
    ka = {(r["n"], r["entry_ms"]): r for r in a}
    kb = {(r["n"], r["entry_ms"]): r for r in b}
    only_a = sorted(set(ka) - set(kb))
    only_b = sorted(set(kb) - set(ka))
    for k in only_a:
        res["mismatches"].append(f"{name_a}에만: N{k[0]} {iso(k[1])}")
    for k in only_b:
        res["mismatches"].append(f"{name_b}에만: N{k[0]} {iso(k[1])}")

    def upd(f, e):
        res["max_err"][f] = max(res["max_err"].get(f, 0.0), e)

    for k in sorted(set(ka) & set(kb)):
        ra, rb = ka[k], kb[k]
        tag = f"N{k[0]} {iso(k[1])}"
        for f in EXACT:
            if ra[f] != rb[f]:
                res["mismatches"].append(f"{tag} {f}: {ra[f]} != {rb[f]}")
        for f in PRICE:
            e = abs(ra[f] - rb[f])
            upd(f, e)
            if e > PRICE_ATOL:
                res["mismatches"].append(f"{tag} {f}: {ra[f]} vs {rb[f]}")
        both_closed = ra["exit_reason"] != "open" and rb["exit_reason"] != "open"
        if ra["exit_reason"] == "open" or rb["exit_reason"] == "open":
            res["open_only"] += 1
            if ra["exit_reason"] != rb["exit_reason"]:
                res["mismatches"].append(f"{tag} 보유/청산 상태: {ra['exit_reason']} vs {rb['exit_reason']}")
            continue
        if not both_closed or skip_closed_if(ra, rb):
            continue
        res["compared_closed"] += 1
        for f in EXACT_CLOSED:
            if ra[f] != rb[f]:
                res["mismatches"].append(f"{tag} {f}: {ra[f]} != {rb[f]}")
        for f in PRICE_CLOSED:
            e = abs(ra[f] - rb[f])
            upd(f, e)
            if e > PRICE_ATOL:
                res["mismatches"].append(f"{tag} {f}: {ra[f]} vs {rb[f]}")
        for f in COST_CLOSED:
            e = abs(ra[f] - rb[f])
            upd(f, e)
            if e > COST_ATOL:
                res["mismatches"].append(f"{tag} {f}: {ra[f]} vs {rb[f]}")
        for f in REL_CLOSED:
            e = abs(ra[f] - rb[f])
            rel = e / max(abs(ra[f]), abs(rb[f]), 1e-12)
            upd(f + "_rel", rel if e > 1e-9 else 0.0)
            if e > 1e-9 + rel_tol * max(abs(ra[f]), abs(rb[f])):
                res["mismatches"].append(f"{tag} {f}: {ra[f]} vs {rb[f]} (상대 {rel:.2e})")
    res["ok"] = not res["mismatches"]
    return res


def replay_checks(rep: list[dict]) -> dict:
    """재생 CSV 자체 점검: 롱만, 승인 지연 30분, 진입 ≥ 승인, 손절 < 진입, 상태."""
    issues = []
    for r in rep:
        tag = f"N{r['n']} {iso(r['entry_ms'])}"
        if r["side"] != 1:
            issues.append(f"{tag} 숏 포지션")
        if r["decision_ms"] != r["signal_close_ms"] + DECISION_DELAY_MS:
            issues.append(f"{tag} 판단 시각 != 마감+60초")
        if r["approved_ms"] != r["decision_ms"] + LATENCY_MS:
            issues.append(f"{tag} 승인 시각 != 판단+30분")
        if r["entry_ms"] < r["approved_ms"]:
            issues.append(f"{tag} 승인 전 진입")
        if not r["stop"] < r["entry_price"]:
            issues.append(f"{tag} 손절 >= 진입가")
        if r["state"] not in ("OPEN", "CLOSED"):
            issues.append(f"{tag} 이상한 상태 {r['state']}")
    by_n: dict[int, list[dict]] = {}
    for r in rep:
        by_n.setdefault(r["n"], []).append(r)
    for n, rs in by_n.items():
        for a, b in zip(rs, rs[1:]):
            if a["exit_ms"] is None or b["entry_ms"] <= a["exit_ms"]:
                issues.append(f"N{n} 겹치는 포지션 {iso(a['entry_ms'])} / {iso(b['entry_ms'])}")
        if sum(1 for r in rs if r["exit_reason"] == "open") > 1:
            issues.append(f"N{n} 보유 포지션 2개 이상")
    return dict(ok=not issues, issues=issues)


def meta_checks(bt: list[dict], sim: list[dict]) -> dict:
    """백테스트 meta의 atr20·level이 원자료 재계산과 같은지."""
    ks = {(r["n"], r["entry_ms"]): r for r in sim}
    worst_atr = worst_lvl = 0.0
    bad = []
    for r in bt:
        s = ks.get((r["n"], r["entry_ms"]))
        if s is None:
            continue
        ea = abs(r["meta"]["atr20"] - s["atr20"])
        el = abs(r["meta"]["level"] - s["level"])
        worst_atr, worst_lvl = max(worst_atr, ea), max(worst_lvl, el)
        if ea > 1e-6 or el > 1e-9:
            bad.append(f"N{r['n']} {iso(r['entry_ms'])} atr {r['meta']['atr20']} vs {s['atr20']}, "
                       f"level {r['meta']['level']} vs {s['level']}")
    return dict(ok=not bad, max_atr_err=worst_atr, max_level_err=worst_lvl, issues=bad[:20])


def summary_stats(rows: list[dict]) -> dict:
    closed = [r for r in rows if r["exit_reason"] != "open"]
    rs = np.array([r["r_multiple"] for r in closed])
    return dict(trades=len(rows), closed=len(closed), open=len(rows) - len(closed),
                by_reason={k: sum(1 for r in closed if r["exit_reason"] == k) for k in ("stop", "trend")},
                by_n={n: sum(1 for r in rows if r["n"] == n) for n in (20, 55, 100)},
                mean_r_closed=float(rs.mean()) if len(rs) else None,
                sum_net_closed=float(sum(r["net_pnl"] for r in closed)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-csv", required=True)
    ap.add_argument("--backtest-csv", default=str(BT_CSV))
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)

    bt = norm_backtest(Path(a.backtest_csv))
    rep = norm_replay(Path(a.replay_csv))
    sim = Sim().run()

    r1 = compare(rep, bt, "replay", "backtest")
    r2 = compare(bt, sim, "backtest", "rawsim", rel_tol=1e-9)
    r3 = compare(rep, sim, "replay", "rawsim", rel_tol=1e-9)
    rc = replay_checks(rep)
    mc = meta_checks(bt, sim)
    eod_bt = sum(1 for r in bt if r["eod"])
    open_rep = sum(1 for r in rep if r["exit_reason"] == "open")

    out = dict(replay=summary_stats(rep), backtest=summary_stats(bt), rawsim=summary_stats(sim),
               replay_vs_backtest=r1, backtest_vs_rawsim=r2, replay_vs_rawsim=r3,
               replay_self=rc, backtest_meta_vs_raw=mc, backtest_eod=eod_bt, replay_open=open_rep)
    ok = r1["ok"] and r2["ok"] and r3["ok"] and rc["ok"] and mc["ok"] and eod_bt == open_rep
    out["ok"] = ok

    for k in ("replay", "backtest", "rawsim"):
        print(f"[{k}] {out[k]}")
    for r in (r1, r2, r3):
        print(f"[{r['pair']}] ok={r['ok']} 개수 {r['count_a']}/{r['count_b']} 청산 비교 {r['compared_closed']}"
              f" 보유 {r['open_only']} 최대오차 {json.dumps(r['max_err'])}")
        for m in r["mismatches"][:15]:
            print("   -", m)
    print(f"[replay 자체 점검] ok={rc['ok']} {rc['issues'][:10]}")
    print(f"[backtest meta vs 원자료] ok={mc['ok']} atr {mc['max_atr_err']:.3g} level {mc['max_level_err']:.3g}"
          f" {mc['issues'][:5]}")
    print(f"[eod] backtest eod {eod_bt} == replay OPEN {open_rep}: {eod_bt == open_rep}")
    print("결과:", "통과" if ok else "불일치")
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
