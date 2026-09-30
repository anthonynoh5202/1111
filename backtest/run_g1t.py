"""G1-T 실행 — 추세추종 8개 조합 + 민감도 + 무작위 기준선 (docs/TREND_SPEC.md v1.0).

실행: 저장소 루트에서
    python -m backtest.run_g1t                       # 공식 실행(무작위 1,000회, 민감도, TRIALS.md 한 줄, 보고서)
    python -m backtest.run_g1t --reps 50 --no-trials --out /tmp/x   # 빠른 점검

결과 (기본 backtest/results_trend/)
- g1t_results.json : 조합별 7개 기준·요약·무작위 기준선·계좌 곡선 성과, E1 vs E0, 민감도, 돈치안 참고값
- trades/<조합>.csv : 체결·미체결 거래 전부 (TradeResult.as_record + key·n 열)
- equity/<조합>.csv : 일별 계좌 곡선 두 방식(r = 0.5% 위험 기반 / 하위 시스템당 명목 0.2배 고정)
- G1T_REPORT.md    : 한국어 보고서 (report_trend.write_report)

판정: metrics.g1_verdict(7개 기준, RULES §8.3 = TREND_SPEC §5). c4 = 비용 2배 평균 R, c5 = 무작위 기준선 95% 분위
(E1은 시장가·메이커 진입 두 분포 중 큰 p95, trend.run_trend_random_baseline T-8). 결정적: 난수는 config.make_rng.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import config as C
from backtest import data as D
from backtest import metrics as M
from backtest import trend as TR
from backtest.baselines import donchian_ensemble
from backtest.types import MarketData, records_frame, to_jsonable

RESULTS_DIR = C.REPO_ROOT / "backtest" / "results_trend"
RESULTS_JSON = "g1t_results.json"
REPORT_MD = "G1T_REPORT.md"
SCHEMA = "g1t_results/1"
MDD_LIMIT = 0.30                    # TREND_SPEC §5 최대 낙폭 30% 넘으면 후순위
G1_DONCHIAN_REF = {"cagr": 0.145, "max_drawdown": 0.269}   # TREND_SPEC 오염 고지(G1 기준선 결과)
# 계좌 곡선: 이름 → (크기 방식, 매일 명목 상한 초과분 줄이기). risk·fixed가 본문 기준, *_hold는 '수량 끝까지 고정' 참고값
EQUITY_VARIANTS = {"risk": ("risk", True), "fixed": ("fixed", True),
                   "risk_hold": ("risk", False), "fixed_hold": ("fixed", False)}


def _log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# 조합 하나
# ---------------------------------------------------------------------------


def span_weeks(daily: TR.DailyData, cfg: TR.TrendConfig) -> float:
    """첫 유효 봉 마감 ~ 마지막 봉 마감 (주)."""
    s = TR.combo_start_day(daily, cfg)
    if s >= len(daily):
        return float("nan")
    return float((daily.close_ns[-1] - daily.close_ns[s]) / (7 * C.NS_PER_DAY))


def _summary(trades, logs, daily, cfg) -> dict:
    s = M.summarize_run(trades, logs, span_weeks=span_weeks(daily, cfg), rng_key=cfg.key)
    s["exit_counts"] = TR.exit_counts(trades)             # 'trend' 사유 포함 (stop, trend, eod)
    s["status_counts"] = TR.status_counts(trades)
    return s


def _by_system(trades, cfg) -> dict:
    out = {}
    f = TR.filled(trades)
    for n in cfg.periods:
        r = np.array([t.r_multiple for t in f if t.meta.get("n") == n], dtype=np.float64)
        out[str(n)] = {"n": int(r.size), "mean_r": float(r.mean()) if r.size else None,
                       "pf": M.profit_factor(r), "n_long": sum(1 for t in f if t.meta.get("n") == n and t.side > 0),
                       "n_short": sum(1 for t in f if t.meta.get("n") == n and t.side < 0)}
    return out


def _equity_block(trades, daily, cfg) -> tuple[dict, pd.DataFrame]:
    start = TR.combo_start_day(daily, cfg)
    blocks, cols = {}, {}
    for name, (mode, trim) in EQUITY_VARIANTS.items():
        e = TR.equity_curve(trades, daily, start, sizing=mode, trim=trim)
        blocks[name] = {k: e[k] for k in ("cagr", "max_drawdown", "sharpe", "final_equity", "max_notional_ratio",
                                          "n_trims")}
        cols[f"equity_{name}"] = e["equity"]
        dates = e["dates_ns"]
    blocks["start_utc"] = C.ns_to_iso(int(daily.close_ns[start])) if start < len(daily) else ""
    frame = pd.DataFrame({"date": [C.ns_to_iso(int(x))[:10] for x in dates], **cols})
    return blocks, frame


def run_combo(daily: TR.DailyData, cfg: TR.TrendConfig, xb, fa, *, n_reps: int, table_cache: dict,
              random: bool = True) -> tuple[dict, list, pd.DataFrame]:
    """기본 조합 하나: 거래·요약·비용 2배·무작위 기준선·판정·계좌 곡선. 반환 (결과 블록, 거래, 계좌 곡선 표)."""
    trades, logs = TR.run_trend_combo(daily, cfg, xb, fa)
    summ = _summary(trades, logs, daily, cfg)
    cfg2 = cfg.replace(cost_multiplier=C.G1_COST_STRESS_MULT)
    trades2, _ = TR.run_trend_combo(daily, cfg2, xb, fa)
    cost2 = M.summarize_cost_stress(trades, trades2, rng_key=cfg2.key)   # §8.3-4, 같은 거래 집합 확인
    if random:
        tables = TR.random_tables_for(daily, cfg, xb, fa, table_cache)
        rb = TR.run_trend_random_baseline(trades, tables, cfg, n_reps=n_reps)
    else:
        rb = None
    thr = rb["threshold"] if rb else None
    verdict = M.g1_verdict(summ, cost2["mean_r"], thr)
    eq, frame = _equity_block(trades, daily, cfg)
    block = {
        "key": cfg.key,
        "config": cfg.as_dict(),
        "summary": summ,
        "cost2": cost2,
        "random": _random_block(rb, len(TR.filled(trades))),
        "verdict": verdict,
        "equity": eq,
        "by_system": _by_system(trades, cfg),
    }
    return block, trades, frame


def _random_block(rb: dict | None, n_trades: int) -> dict:
    if rb is None:
        return {"reps": 0, "n_trades": int(n_trades), "mean": None, "p05": None, "p50": None, "p95": None,
                "threshold": None, "skipped": True}
    return {"reps": int(rb["reps"]), "n_trades": int(rb["n_trades"]), "mean": rb["mean"], "p05": rb["p05"],
            "p50": rb["p50"], "p95": rb["p95"], "maker": dict(rb["maker"]), "threshold": rb["threshold"],
            "n_not_filled": int(rb["n_not_filled"]), "seed_parts": list(rb["seed_parts"]),
            "means": np.asarray(rb["means"], dtype=np.float64)}


def run_sensitivity(daily, cfg: TR.TrendConfig, xb, fa) -> list[dict]:
    """민감도 4종(지연 10·120분, 손절 3 × ATR, 비용 2배) — 보고만, 무작위 기준선 없음 (TREND_SPEC §4)."""
    out = []
    for tag, changes in TR.SENSITIVITY_VARIANTS:
        v = cfg.replace(**changes)
        trades, logs = TR.run_trend_combo(daily, v, xb, fa)
        s = _summary(trades, logs, daily, v)
        eq, _ = _equity_block(trades, daily, v)
        out.append({"key": cfg.key, "variant": tag, "config": v.as_dict(),
                    "summary": {k: s[k] for k in ("n", "n_long", "n_short", "mean_r", "median_r", "pf", "boot_lo",
                                                  "boot_hi", "win_rate", "positive_years", "exit_counts",
                                                  "status_counts", "total_r", "max_drawdown_r")},
                    "equity": eq})
    return out


def e1_vs_e0(blocks: dict, trades: dict) -> list[dict]:
    """§5 차트프로 보조 판정: 같은 방향·하위 시스템의 E1 − E0 평균 R 차이 부트스트랩 95% 구간 + 계좌 곡선."""
    out = []
    for d in TR.DIRECTIONS:
        for p in (TR.PERIODS, (TR.SINGLE_PERIOD,)):
            k0 = TR.TrendConfig("E0", d, p).key
            k1 = TR.TrendConfig("E1", d, p).key
            if k0 not in blocks or k1 not in blocks:
                continue
            r0 = [t.r_multiple for t in TR.filled(trades[k0])]
            r1 = [t.r_multiple for t in TR.filled(trades[k1])]
            ci = TR.bootstrap_mean_diff_ci(r1, r0, rng=C.make_rng("trend_e1_vs_e0", k1, k0))
            out.append({"pair": f"{k1} vs {k0}", "e1": k1, "e0": k0, **ci,
                        "e1_better": bool(np.isfinite(ci["lo"]) and ci["lo"] > 0),
                        "equity": {"e1": blocks[k1]["equity"], "e0": blocks[k0]["equity"]}})
    return out


def _simplicity(key: str) -> tuple:
    """§5 단순한 것 우선: 단독 < 앙상블, 롱만 < 롱·숏, E0 < E1."""
    e, d, s = key.split("-", 2)
    return (0 if s != "ENS" else 1, 0 if d == "L" else 1, 0 if e == "E0" else 1)


def selection(blocks: dict, cmp: list[dict]) -> dict:
    """통과 조합 순위 (§5): 단순한 것 우선, 위험 기반 곡선 최대 낙폭 > 30%면 후순위, E1은 E0보다 확실히 나을 때만 채택 후보."""
    passed = [k for k, b in blocks.items() if b["verdict"]["result"] == "pass"]
    pending = [k for k, b in blocks.items() if b["verdict"]["result"] == "pending"]
    failed = [k for k, b in blocks.items() if b["verdict"]["result"] == "fail"]
    e1_ok = {c["e1"] for c in cmp if c["e1_better"]}
    notes = {}
    eligible = []
    for k in passed:
        if k.startswith("E1") and k not in e1_ok:
            notes[k] = "E1이 E0보다 확실히 낫지 않음(차이 구간 하한 ≤ 0) → 채택 후보 아님"
            continue
        eligible.append(k)

    def rank(k):
        mdd = blocks[k]["equity"]["risk"]["max_drawdown"]
        over = 1 if (mdd is None or not np.isfinite(mdd) or mdd > MDD_LIMIT) else 0
        return (over, *_simplicity(k))

    ranked = sorted(eligible, key=rank)
    for k in ranked:
        mdd = blocks[k]["equity"]["risk"]["max_drawdown"]
        if mdd is None or not np.isfinite(mdd) or mdd > MDD_LIMIT:
            notes[k] = f"최대 낙폭 {mdd:.1%} > 30% → 후순위" if mdd is not None and np.isfinite(mdd) else "낙폭 계산 불가"
    if ranked:
        decision = f"통과 {len(passed)}개, 채택 후보 1순위 {ranked[0]} (G3 모의 운영으로 진짜 검증)"
    elif passed:
        decision = f"통과 {len(passed)}개이나 채택 후보 없음(E1 조건 미충족) — 사용자와 재검토"
    else:
        decision = "통과 조합 0개 — 추세추종 기본형 채택 보류, 사용자와 재검토"
    return {"pass": passed, "pending": pending, "fail": failed, "ranked": ranked, "notes": notes,
            "n_pass": len(passed), "n_pending": len(pending), "n_fail": len(failed), "decision": decision}


# ---------------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------------


def _write_json(results: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / RESULTS_JSON
    text = json.dumps(to_jsonable(results), ensure_ascii=False, indent=1, allow_nan=False)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _trades_csv(trades: list, key: str, path: Path) -> None:
    df = records_frame(trades) if trades else pd.DataFrame()
    if len(df):
        df.insert(0, "n", [t.meta.get("n") for t in trades])
    df.insert(0, "key", key)
    df.to_csv(path, index=False)


def run_g1t(*, market: MarketData | None = None, out_dir: Path = RESULTS_DIR, n_reps: int = C.RANDOM_REPS,
            only: list[str] | None = None, sensitivity: bool = True, random: bool = True, trials: bool = False,
            report: bool = True, quiet: bool = False, note: str = "") -> dict:
    """G1-T 전체 실행. market이 None이면 실데이터(data.load_market, 일봉만)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    source = "binance"
    if market is None:
        _log("데이터 읽는 중…", quiet)
        market = D.load_market(tfs=("1d",), with_events=False)
    else:
        source = "synthetic"
    xb, fa = market.exec_arrays(), market.funding_arrays()
    daily = TR.DailyData.from_frame(market.bars["1d"])
    combos = TR.trend_combos()
    if only:
        combos = [c for c in combos if c.key in set(only)]
        if not combos:
            raise ValueError(f"--only에 맞는 조합 없음: {only}")
    (out_dir / "trades").mkdir(parents=True, exist_ok=True)
    (out_dir / "equity").mkdir(parents=True, exist_ok=True)

    blocks, trades_by, table_cache = {}, {}, {}
    for cfg in combos:
        t1 = time.time()
        block, trades, frame = run_combo(daily, cfg, xb, fa, n_reps=n_reps, table_cache=table_cache, random=random)
        blocks[cfg.key] = block
        trades_by[cfg.key] = trades
        _trades_csv(trades, cfg.key, out_dir / "trades" / f"{cfg.key}.csv")
        frame.to_csv(out_dir / "equity" / f"{cfg.key}.csv", index=False)
        s = block["summary"]
        _log(f"{cfg.key}: 거래 {s['n']}건 평균 R {s['mean_r']:+.3f} 판정 {block['verdict']['result']} "
             f"({time.time() - t1:.1f}초)", quiet)

    # DSR (보고용): 8개 조합 거래당 샤프 분산, 시도 수 8
    var = M.sharpe_trials_variance([b["summary"]["sharpe"] for b in blocks.values()])
    for b in blocks.values():
        b["dsr"] = M.dsr_from_summary(b["summary"], var, n_trials=len(TR.trend_combos()))

    cmp = e1_vs_e0(blocks, trades_by)
    sens = []
    if sensitivity:
        for cfg in combos:
            sens.extend(run_sensitivity(daily, cfg, xb, fa))
        _log(f"민감도 {len(sens)}개 완료", quiet)

    try:
        don = donchian_ensemble(market.bars["1d"], fa, xb)
        don = {k: v for k, v in don.items() if k != "equity"}
    except Exception as exc:  # 합성 데이터가 너무 짧을 때 등
        don = {"error": str(exc)}

    from backtest.run_g1 import _data_info, _git_info, code_fingerprint
    git = _git_info()
    full = only is None and random and n_reps == C.RANDOM_REPS and source == "binance"
    results = {
        "schema": SCHEMA,
        "spec_version": TR.TREND_SPEC_VERSION,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime_sec": None,
        "git_commit": git["commit"],
        "git_dirty": git["dirty"],
        "code_sha256": code_fingerprint(),
        "data": _data_info(market, source) | {
            "daily_span_utc": [C.ns_to_iso(int(daily.open_ns[0])), C.ns_to_iso(int(daily.close_ns[-1]))]},
        "params": {"latency_min": TR.LATENCY_MIN, "stop_atr_mult": TR.STOP_ATR_MULT, "atr_n": TR.ATR_N,
                   "periods": list(TR.PERIODS), "exit_periods": [TR.exit_period(p) for p in TR.PERIODS],
                   "e1_valid_days": TR.E1_VALID_DAYS, "random_reps": int(n_reps), "random_enabled": bool(random),
                   "bootstrap_n": C.BOOTSTRAP_N, "seed": C.RANDOM_SEED, "n_trials": len(TR.trend_combos()),
                   "cost_stress_mult": C.G1_COST_STRESS_MULT, "risk_r": TR.RISK_R,
                   "notional_cap_per_system": TR.NOTIONAL_CAP_PER_SYSTEM, "sensitivity": bool(sensitivity),
                   "only": only, "note": note},
        "combos": list(blocks.values()),
        "dsr_sr_trials_var": var,
        "e1_vs_e0": cmp,
        "sensitivity": sens,
        "donchian": don,
        "donchian_g1_reference": G1_DONCHIAN_REF,
        "summary": selection(blocks, cmp) | {"official": bool(full)},
    }
    results["runtime_sec"] = round(time.time() - t0, 1)
    path = _write_json(results, out_dir)
    if trials:
        append_trials(results)
    if report:
        from backtest import report_trend
        report_trend.write_report(path, out_dir / REPORT_MD)
    _log(f"완료 {results['runtime_sec']}초 — {results['summary']['decision']}", quiet)
    return results


def trials_line(results: dict) -> str:
    """TRIALS.md 표 한 줄."""
    p, s = results["params"], results["summary"]
    commit = (results.get("git_commit") or "없음") + ("+작업 트리 변경" if results.get("git_dirty") else "")
    head = "G1-T 실행" if s.get("official") else "G1-T 부분 실행"
    bits = [f"무작위 {p['random_reps']}회" if p.get("random_enabled") else "무작위 없음", f"커밋 {commit}"]
    if not p.get("sensitivity"):
        bits.append("민감도 없음")
    if p.get("note"):
        bits.append(str(p["note"]))
    res = f"통과 {s['n_pass']}개" + (": " + ", ".join(s["pass"]) if s["pass"] else "")
    res += f" / 불합격 {s['n_fail']}개 / 보류 {s['n_pending']}개"
    cells = [results["created_utc"][:10], results["spec_version"], f"{head} ({', '.join(bits)})",
             str(len(results["combos"])), res]
    return "| " + " | ".join(x.replace("|", "/").replace("\n", " ") for x in cells) + " |"


def append_trials(results: dict, path: Path = C.TRIALS_MD) -> None:
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    with open(path, "a", encoding="utf-8") as fh:
        if text and not text.endswith("\n"):
            fh.write("\n")
        fh.write(trials_line(results) + "\n")


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="G1-T 추세추종 백테스트 (TREND_SPEC v1.0)")
    ap.add_argument("--out", type=Path, default=RESULTS_DIR)
    ap.add_argument("--reps", type=int, default=C.RANDOM_REPS, help="무작위 기준선 반복 수 (기본 1000)")
    ap.add_argument("--only", nargs="*", default=None, help="조합 키만 (예: E0-LS-ENS)")
    ap.add_argument("--no-sensitivity", action="store_true")
    ap.add_argument("--no-random", action="store_true")
    ap.add_argument("--no-trials", action="store_true", help="TRIALS.md에 한 줄 추가하지 않음")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--note", default="")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    res = run_g1t(out_dir=a.out, n_reps=a.reps, only=a.only, sensitivity=not a.no_sensitivity,
                  random=not a.no_random, trials=not a.no_trials, report=not a.no_report, quiet=a.quiet,
                  note=a.note)
    print(f"결과: {Path(a.out) / RESULTS_JSON}")
    print(res["summary"]["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
