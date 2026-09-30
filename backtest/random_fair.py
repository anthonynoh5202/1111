"""TREND v1.1(참고) — 전체 기간 무작위 진입 기준선 ('공정 무작위').

왜 있나
- TREND_SPEC §5(T-8)의 공식 무작위 기준선은 실제 거래의 (진입 달, 방향, 하위 시스템)을 유지한다. 돌파 신호는 추세가 강한 달에
  몰리므로, 같은 달 안에서 무작위로 들어가도 추세 청산 규칙 덕에 큰 R이 나온다. 그래서 공식 기준선은 "진입 날짜 선택"만의
  가치를 재지, "어느 달에 거래하느냐"(돌파 신호가 추세 구간을 골라내는 능력)는 재지 않는다.
- 이 모듈은 달 조건을 풀고, 진입일을 **전체 평가 기간**(그 하위 시스템의 모든 유효 일봉)에서 균등 추출한다.
  같은 거래 수·방향·하위 시스템, 같은 보호 손절(그날 2 × ATR20)·같은 추세 청산(그 방향 M일 반대 돌파)·같은 비용.

⚠️ 결과를 본 뒤(G1-T 실행 뒤) 추가한 **참고 지표**다. G1-T 판정(c5)에 쓰지 않는다. TRIALS.md에 기록한다.

재사용 (복사 금지)
- 무작위 거래 하나의 결과는 trend.random_table(= trend.simulate_trend_trade, entry_mode='E0')이 이미 모든 유효 일봉마다 계산한다.
  여기서는 그 표에서 뽑는 방식만 다르다.

해석 확정 (F-번호, 보수적 선택)
- F-1 추출 풀 = 표의 체결된 일봉만(filled=True). 공식 기준선은 미체결을 뽑으면 그 거래를 빼고 평균을 내지만(n_not_filled),
  여기서는 "같은 거래 수"를 정확히 지키려고 체결 가능한 날에서만 뽑는다. 미체결 일봉은 대부분 데이터 끝 근처(진입 봉 없음)라
  편향이 작다. 제외 수는 결과에 적는다.
- F-2 거래끼리 겹침 무시, 재진입·반대 진입 없음 (T-8과 같음). 복원 추출.
- F-3 E1 조합은 시장가 분포와 '진입만 메이커·슬리피지 없음' 분포 중 p95가 큰 쪽을 기준으로 삼는다(T-8과 같은 보수적 선택).
- F-4 난수 = config.make_rng('trend_random_fair', 조합 키) — 결정적, 공식 기준선과 다른 흐름.
- F-5 '넘음' = 실제 평균 R > 공정 p95(엄격). 순위 = 실제 평균 R 이상인 반복 비율(한쪽 p값 근사, (k+1)/(reps+1)).

실행: .venv/bin/python -m backtest.random_fair  →  backtest/results_trend/fair_baseline.json (+ --trials면 TRIALS.md 한 줄)
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backtest import config as C
from backtest import trend as TR
from backtest.types import MarketData, to_jsonable

SPEC_VERSION = "TREND v1.1(참고)"
SCHEMA = "trend_fair_baseline/1"
RESULTS_DIR = C.REPO_ROOT / "backtest" / "results_trend"
RESULTS_JSON = "fair_baseline.json"
# TRIALS.md 날짜 = 실제 실행일(UTC). 결과 JSON의 created_utc에서 꺼내고, 없으면 지금(UTC). (R-5: 고정 문자열로 미래 날짜가 찍히던 문제)
TRIALS_DESC = "전체 기간 무작위 기준선 추가 — 결과를 본 뒤 추가한 참고 지표, 판정에 쓰지 않음"


def _dist(means: np.ndarray) -> dict:
    f = np.asarray(means, dtype=np.float64)
    f = f[np.isfinite(f)]
    nan = float("nan")
    if not f.size:
        return dict(mean=nan, p05=nan, p50=nan, p95=nan)
    p05, p50, p95 = (float(v) for v in np.quantile(f, [0.05, 0.5, C.G1_RANDOM_QUANTILE]))
    return dict(mean=float(f.mean()), p05=p05, p50=p50, p95=p95)


def fair_random_baseline(trades: list, tables: dict, cfg: TR.TrendConfig, *, n_reps: int = C.RANDOM_REPS,
                         rng: np.random.Generator | None = None) -> dict:
    """전체 기간 무작위 기준선. 실제 체결 거래마다 (하위 시스템 N, 방향)만 유지하고, tables[(N, side)]의
    체결 가능한 유효 일봉 전체에서 균등 복원 추출한다(F-1·F-2). 반복마다 평균 R.

    반환: reps, n_trades, means, mean, p05, p50, p95, maker={...}, threshold(F-3), pool_sizes, n_excluded_unfilled.
    """
    seed_parts = ["trend_random_fair", cfg.key]
    rng = C.make_rng(*seed_parts) if rng is None else rng
    base = TR.filled(trades)
    n_reps = int(n_reps)
    nan = float("nan")
    out = dict(reps=n_reps, n_trades=len(base), seed_parts=seed_parts)
    empty = dict(means=np.array([]), mean=nan, p05=nan, p50=nan, p95=nan,
                 maker=dict(mean=nan, p05=nan, p50=nan, p95=nan), threshold=nan, pool_sizes={},
                 n_excluded_unfilled={})
    if not base or n_reps <= 0:
        return out | empty
    keys = sorted({(int(t.meta["n"]), int(t.side)) for t in base})
    pool_r, pool_rm, offsets, sizes, excluded = [], [], {}, {}, {}
    off = 0
    for key in keys:
        tb = tables[key]
        ok = np.asarray(tb.filled, dtype=bool)
        r, rm = np.asarray(tb.r, dtype=np.float64)[ok], np.asarray(tb.r_maker, dtype=np.float64)[ok]
        if not r.size:
            raise ValueError(f"공정 무작위 기준선: {key}에 체결 가능한 일봉 없음")
        offsets[key] = off
        sizes[key] = int(r.size)
        excluded[key] = int((~ok).sum())
        pool_r.append(r)
        pool_rm.append(rm)
        off += r.size
    pool_r, pool_rm = np.concatenate(pool_r), np.concatenate(pool_rm)
    lo = np.array([offsets[(int(t.meta["n"]), int(t.side))] for t in base], dtype=np.int64)
    hi = lo + np.array([sizes[(int(t.meta["n"]), int(t.side))] for t in base], dtype=np.int64)
    shape = (n_reps, len(base))
    idx = rng.integers(np.broadcast_to(lo, shape), np.broadcast_to(hi, shape))
    means = pool_r[idx].mean(axis=1)
    d = _dist(means)
    d_mk = _dist(pool_rm[idx].mean(axis=1))
    thr = d["p95"] if cfg.entry == "E0" else float(np.nanmax([d["p95"], d_mk["p95"]]))
    fmt = lambda k: f"N{k[0]}{'L' if k[1] > 0 else 'S'}"  # noqa: E731
    return out | dict(means=means, **d, maker=d_mk, threshold=thr,
                      pool_sizes={fmt(k): v for k, v in sizes.items()},
                      n_excluded_unfilled={fmt(k): v for k, v in excluded.items()})


def compare(actual_mean_r: float, fair: dict) -> dict:
    """실제 평균 R과 공정 분포 비교 (F-5)."""
    means = np.asarray(fair.get("means", []), dtype=np.float64)
    means = means[np.isfinite(means)]
    thr = fair.get("threshold", float("nan"))
    a = float(actual_mean_r)
    if not means.size or not np.isfinite(a):
        return dict(beats_p95=None, frac_ge_actual=None, p_value=None, margin_vs_p95=None)
    k = int((means >= a).sum())
    return dict(beats_p95=bool(a > thr), frac_ge_actual=k / means.size, p_value=(k + 1) / (means.size + 1),
                margin_vs_p95=a - float(thr))


def _month_matched(g1t: dict | None, key: str) -> dict | None:
    """g1t_results.json의 공식(같은 달) 기준선 요약 — 비교 표시용."""
    if not g1t:
        return None
    for b in g1t.get("combos", []):
        if b.get("key") == key:
            r = b.get("random") or {}
            return {k: r.get(k) for k in ("mean", "p05", "p50", "p95", "threshold", "n_not_filled")}
    return None


def run_fair(*, market: MarketData | None = None, out_dir: Path = RESULTS_DIR, n_reps: int = C.RANDOM_REPS,
             only: list[str] | None = None, trials: bool = False, quiet: bool = False,
             g1t_path: Path | None = None) -> dict:
    """8개 조합 각각: 실제 거래(run_trend_combo) → 표(random_tables_for) → 공정 무작위 분포 → 비교. JSON 저장."""
    t0 = time.time()
    out_dir = Path(out_dir)
    source = "binance"
    if market is None:
        from backtest import data as D
        if not quiet:
            print("데이터 읽는 중…", flush=True)
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
    g1t = None
    gp = Path(g1t_path) if g1t_path else out_dir / "g1t_results.json"
    if source == "binance" and gp.exists():
        g1t = json.loads(gp.read_text(encoding="utf-8"))

    blocks, cache = [], {}
    for cfg in combos:
        trades, _ = TR.run_trend_combo(daily, cfg, xb, fa)
        f = TR.filled(trades)
        r = np.array([t.r_multiple for t in f], dtype=np.float64)
        actual = float(r.mean()) if r.size else float("nan")
        tables = TR.random_tables_for(daily, cfg, xb, fa, cache)
        fair = fair_random_baseline(trades, tables, cfg, n_reps=n_reps)
        cmpd = compare(actual, fair)
        fair_out = {k: v for k, v in fair.items() if k != "means"}
        blocks.append({"key": cfg.key, "n_trades": len(f), "actual_mean_r": actual, "fair": fair_out,
                       "compare": cmpd, "month_matched": _month_matched(g1t, cfg.key)})
        if not quiet:
            print(f"{cfg.key}: 거래 {len(f)} 실제 {actual:+.3f} | 공정 평균 {fair['mean']:+.3f} "
                  f"p95 {fair['threshold']:+.3f} → {'초과' if cmpd['beats_p95'] else '미달'}", flush=True)

    n_beat = sum(1 for b in blocks if b["compare"]["beats_p95"])
    results = {
        "schema": SCHEMA,
        "spec_version": SPEC_VERSION,
        "note": "결과를 본 뒤 추가한 참고 지표 — G1-T 판정(c5)에 쓰지 않음",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime_sec": None,
        "source": source,
        "daily_span_utc": [C.ns_to_iso(int(daily.open_ns[0])), C.ns_to_iso(int(daily.close_ns[-1]))],
        "params": {"reps": int(n_reps), "quantile": C.G1_RANDOM_QUANTILE, "latency_min": TR.LATENCY_MIN,
                   "stop_atr_mult": TR.STOP_ATR_MULT, "periods": list(TR.PERIODS), "seed": C.RANDOM_SEED,
                   "only": only,
                   "rules": ["F-1 체결 가능한 일봉만 추출", "F-2 복원 추출·겹침 무시", "F-3 E1은 max(시장가 p95, 메이커 p95)",
                             "F-4 make_rng('trend_random_fair', key)", "F-5 넘음 = 실제 > p95"]},
        "combos": blocks,
        "summary": {"n_combos": len(blocks), "n_beat_fair_p95": n_beat,
                    "beat": [b["key"] for b in blocks if b["compare"]["beats_p95"]]},
    }
    results["runtime_sec"] = round(time.time() - t0, 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / RESULTS_JSON
    path.write_text(json.dumps(to_jsonable(results), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if trials:
        append_trials(results)
    return results


def trials_line(results: dict) -> str:
    s = results["summary"]
    parts = []
    for b in results["combos"]:
        parts.append(f"{b['key']} {b['actual_mean_r']:+.2f}/{b['fair']['threshold']:+.2f}")
    summ = (f"실제 평균 R > 공정 무작위 p95: {s['n_beat_fair_p95']}/{s['n_combos']}개 "
            f"(무작위 {results['params']['reps']}회; 실제/p95: {', '.join(parts)})")
    return f"| {trials_date(results)} | {SPEC_VERSION} | {TRIALS_DESC} | {s['n_combos']} | {summ} |"


def trials_date(results: dict) -> str:
    """TRIALS.md에 쓸 실행일(UTC 'YYYY-MM-DD'): results['created_utc']의 날짜, 없으면 오늘(UTC)."""
    created = str(results.get("created_utc") or "")
    if len(created) >= 10 and created[4] == "-" and created[7] == "-":
        return created[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def append_trials(results: dict, path: Path = C.TRIALS_MD) -> None:
    line = trials_line(results)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + line + "\n", encoding="utf-8")


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="TREND v1.1(참고) 전체 기간 무작위 기준선")
    ap.add_argument("--out", type=Path, default=RESULTS_DIR)
    ap.add_argument("--reps", type=int, default=C.RANDOM_REPS)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--trials", action="store_true", help="TRIALS.md에 한 줄 추가")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    run_fair(out_dir=a.out, n_reps=a.reps, only=a.only, trials=a.trials, quiet=a.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
