"""G1 전체 실행기 — 16조합 × (전체 / 실행 가능) + 비용 2배 + 무작위 기준선 + 민감도 + 돈치안 → 결과 파일.

담당: 통합. 설계: backtest/DESIGN.md §6.12, §8(결과 파일 형식), §10(성능).
실행: 저장소 루트에서 `python -m backtest.run_g1` (backtest/ 안에서 스크립트로 직접 실행하지 않는다).

흐름 (조합 cfg 하나)
1. ctx = scenarios.build_context(market, cfg.setting, cfg.vr_threshold)   # (setting, vr)별 캐시
2. cands = scenarios.generate_candidates(ctx, cfg)                         # 마스크·비용과 무관 → 한 번만
   (기간을 주면 승인 시각이 [시작, 끝)인 후보만 남긴다)
3. trades, logs = execution.run_sequence(cands, xb, fa, cfg)             # 'all'과 'exec' 모드 각각 (§12.3)
4. 비용 2배: run_sequence(cands, xb, fa, cfg.replace(cost_multiplier=2.0)) # 같은 후보, 회계만 다름 (I-27)
5. 무작위 기준선: random_baseline.run_random_baseline(exec 모드 체결 거래, ctx.s_bars.close_ns, …) (§12.4)
6. metrics.summarize_run / g1_verdict, 모든 조합 뒤 DSR(16조합 샤프 분산, I-41)
결과(out_dir): g1_results.json(DESIGN §8.1), trades/<조합>_<all|exec>.csv, signals_summary.csv(폐기 사유별 개수),
run_log.txt(실행 시간), G1_REPORT.md(report.py). TRIALS.md에 한 줄 추가(§9).

결정성(DESIGN §3.5): 조합마다 cfg.key로 난수를 만들고 결과는 g1_combos() 순서로 모은다 → 프로세스 수와 무관.
g1_results.json은 created_utc·runtime_sec 말고는 두 번 돌려도 같다(실행 시간은 run_log.txt에만 쓴다).
병렬: 부모가 데이터·문맥을 준비한 뒤 fork로 작업 프로세스를 만든다(큰 배열을 복사·피클하지 않음).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import baselines as B
from backtest import config as C
from backtest import data as D
from backtest import execution as X
from backtest import metrics as M
from backtest import random_baseline as RB
from backtest import report as RPT
from backtest import scenarios as SC
from backtest.config import ComboConfig
from backtest.types import (REASON_ORDER, Candidate, ExecArrays, FundingArrays, MarketData, SignalLog,
                            TradeResult, records_frame, to_jsonable)

SCHEMA = "g1_results/1"
RESULTS_JSON = "g1_results.json"
REPORT_MD = "G1_REPORT.md"
SIGNALS_SUMMARY_CSV = "signals_summary.csv"
RUN_LOG = "run_log.txt"
TRADES_DIR = "trades"      # trades/<조합>_<all|exec>.csv
SIGNALS_DIR = "signals"    # --signal-logs: signals/<조합>_<all|exec>.csv.gz (후보별 전체 기록)
MODES = ("all", "exec")    # 전체(마스크 없음) / 실행 가능(마스크 적용, G1 판정 기준)
PASSED_ROW = "PASSED"      # signals_summary.csv에서 통과(실행한 계획) 줄의 사유 이름

# 빈 목록도 같은 열 머리글로 CSV를 쓰기 위한 열 이름 (as_record의 키 순서)
_TRADE_COLUMNS = tuple(TradeResult(
    plan_id="", scenario="", side=1, order_type="limit", signal_time=0, approval_time=0, active_from=0,
    plan_entry=0.0, stop=0.0, target=0.0, status="expired", busy_until=0, risk_per_unit=1.0).as_record())
_SIGNAL_COLUMNS = tuple(SignalLog(time=0, signal_time=0, scenario="", side=1, status="passed").as_record())

# 작업 프로세스가 fork로 물려받는 공유 상태 (부모가 작업 시작 전에 채운다)
_STATE: dict = {}


# ---------------------------------------------------------------------------
# 명령행
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """명령행 옵션.

    --out DIR (기본 C.RESULTS_DIR) / --reps N (기본 C.RANDOM_REPS) / --jobs N (기본 4, 프로세스 수) /
    --only KEY[,KEY…] (base_key 부분 문자열로 조합 거르기) / --no-sensitivity / --no-random / --no-trials
    덧붙인 옵션: --start/--end (기간, 승인 시각 기준 [시작, 끝), 기본 전체) / --no-report /
    --signal-logs (후보별 전체 신호 기록 CSV) / --note (TRIALS.md·결과에 남길 메모)
    """
    p = argparse.ArgumentParser(
        prog="python -m backtest.run_g1",
        description="G1 백테스트 실행 (docs/RULES_SPEC.md v1.0): 16조합 × 전체/실행 가능 + 비용 2배 + 무작위·돈치안 "
                    "기준선 + 민감도 → backtest/results/",
    )
    p.add_argument("--out", type=Path, default=C.RESULTS_DIR, help="결과 폴더 (기본: backtest/results)")
    p.add_argument("--reps", type=int, default=C.RANDOM_REPS,
                   help=f"무작위 기준선 반복 수 (기본 {C.RANDOM_REPS}, 줄이면 보고서에 명시됨)")
    p.add_argument("--jobs", type=int, default=4, help="병렬 프로세스 수 (기본 4, 1이면 순차)")
    p.add_argument("--only", type=str, default=None,
                   help="조합 거르기: 조합 이름의 부분 문자열, 쉼표로 여러 개 (예: L1b-DA-P1 / L1b,S2 / P2)")
    p.add_argument("--start", type=str, default=None,
                   help="기간 시작(포함, UTC). 예: 2024-01-01. 승인 시각(신호 봉 마감 + 60초) 기준. 기본: 데이터 처음")
    p.add_argument("--end", type=str, default=None,
                   help="기간 끝(미포함, UTC). 예: 2025-01-01. 기본: 데이터 끝")
    p.add_argument("--no-sensitivity", action="store_true", help="민감도 실행(조합마다 5개 변형)을 건너뛴다")
    p.add_argument("--no-random", action="store_true", help="무작위 기준선을 건너뛴다 (G1 조건 5는 미달로 처리)")
    p.add_argument("--no-trials", action="store_true", help="backtest/TRIALS.md에 기록하지 않는다")
    p.add_argument("--no-report", action="store_true", help="G1_REPORT.md를 만들지 않는다")
    p.add_argument("--signal-logs", action="store_true",
                   help="후보별 전체 신호 기록을 signals/<조합>_<all|exec>.csv.gz로 저장 (용량 큼)")
    p.add_argument("--note", type=str, default="", help="TRIALS.md 한 줄과 결과 JSON에 남길 메모")
    args = p.parse_args(argv)
    if args.reps < 0:
        p.error("--reps는 0 이상")
    if args.jobs < 1:
        p.error("--jobs는 1 이상")
    args.only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    try:
        parse_period(args.start, args.end)
        select_combos(args.only)
    except ValueError as exc:
        p.error(str(exc))
    return args


def parse_period(start=None, end=None) -> tuple[int | None, int | None] | None:
    """기간 → (시작 ns | None, 끝 ns | None). 둘 다 없으면 None(전체). 시작 ≥ 끝이면 ValueError."""
    if start in (None, "") and end in (None, ""):
        return None
    lo = C.ts_ns(start) if start not in (None, "") else None
    hi = C.ts_ns(end) if end not in (None, "") else None
    if lo is not None and hi is not None and lo >= hi:
        raise ValueError(f"기간 시작({start})이 끝({end})보다 앞이어야 한다")
    return lo, hi


def select_combos(only: list[str] | None = None) -> list[ComboConfig]:
    """기본 16조합(g1_combos 순서) 중 이름(base_key)에 only의 문자열 하나라도 들어 있는 것. 없으면 ValueError."""
    combos = C.g1_combos(apply_availability_mask=True)
    if not only:
        return combos
    picked = [c for c in combos if any(s in c.base_key for s in only)]
    if not picked:
        names = ", ".join(c.base_key for c in combos)
        raise ValueError(f"--only {only}에 맞는 조합이 없다. 조합 이름: {names}")
    return picked


# ---------------------------------------------------------------------------
# 작은 도우미
# ---------------------------------------------------------------------------


def get_context(ctx_cache: dict, market: MarketData, setting: str, vr_threshold: float):
    """문맥 캐시: (setting, vr_threshold)마다 scenarios.build_context를 한 번만 부른다."""
    key = (setting, float(vr_threshold))
    if key not in ctx_cache:
        ctx_cache[key] = SC.build_context(market, setting, float(vr_threshold))
    return ctx_cache[key]


def filter_period(cands: list[Candidate], period) -> list[Candidate]:
    """승인 시각(log.time = 신호 봉 마감 + 60초)이 [시작, 끝)인 후보만 남긴다(순서 유지)."""
    if period is None:
        return cands
    lo, hi = period
    return [c for c in cands
            if (lo is None or c.log.time >= lo) and (hi is None or c.log.time < hi)]


def span_weeks(ctx, period=None) -> float:
    """신호 빈도 분모(주): (S 봉 마지막 close_ns − valid가 처음 True인 S 봉 close_ns) ÷ 7일 (DESIGN §6.12).

    기간을 주면 그 기간과 겹치는 부분만 센다. 겹침이 없으면 0.
    """
    close_ns = ctx.s_bars["close_ns"].to_numpy(dtype=np.int64)
    valid = ctx.s_ind["valid"].to_numpy(dtype=bool)
    if close_ns.size == 0 or not valid.any():
        return float("nan")
    lo, hi = int(close_ns[int(np.argmax(valid))]), int(close_ns[-1])
    if period is not None:
        if period[0] is not None:
            lo = max(lo, int(period[0]))
        if period[1] is not None:
            hi = min(hi, int(period[1]))
    return max(hi - lo, 0) / (7 * C.NS_PER_DAY)


def _write_records_csv(items: list, key: str, path: Path, columns: tuple[str, ...]) -> None:
    """TradeResult·SignalLog 목록 → CSV (첫 열 key). 빈 목록이면 머리글만."""
    df = records_frame(items) if items else pd.DataFrame(columns=list(columns))
    df.insert(0, "key", key)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _clear_outputs(out_dir: Path) -> None:
    """이전 실행이 남긴 조합별 CSV를 지운다(이번 결과 JSON과 파일 목록이 어긋나지 않게). 우리 파일 이름만 지운다."""
    for sub, patterns in ((TRADES_DIR, ("*_all.csv", "*_exec.csv")),
                          (SIGNALS_DIR, ("*_all.csv.gz", "*_exec.csv.gz"))):
        d = out_dir / sub
        if d.is_dir():
            for pat in patterns:
                for f in d.glob(pat):
                    f.unlink()


def _random_block(rb: dict | None, n_trades: int) -> dict:
    """무작위 기준선 결과 → 결과 JSON의 random 항목(DESIGN §8.1 키 순서). rb가 None이면 미실시.

    same_fee: 진입 수수료만 조합의 주문 형태 요율로 바꾼 무작위 분포 요약(보고용, 판정은 p95 — §12.4, 검토 F2).
    """
    if rb is None:
        return {"reps": 0, "n_trades": int(n_trades), "mean": None, "p05": None, "p50": None, "p95": None,
                "n_not_filled": 0, "means": [], "skipped": True}
    return {"reps": int(rb["reps"]), "n_trades": int(rb["n_trades"]), "mean": rb["mean"], "p05": rb["p05"],
            "p50": rb["p50"], "p95": rb["p95"], "n_not_filled": int(rb["n_not_filled"]),
            "means": np.asarray(rb["means"], dtype=np.float64), "seed_parts": list(rb.get("seed_parts", [])),
            "same_fee": dict(rb.get("same_fee") or {})}


def _git_info() -> dict:
    """코드 커밋과 작업 트리 변경 여부(backtest/ 코드만, results·TRIALS.md 제외). git이 없으면 None."""
    def run(*args) -> str:
        return subprocess.run(["git", *args], cwd=C.REPO_ROOT, capture_output=True, text=True,
                              timeout=20, check=True).stdout
    try:
        commit = run("rev-parse", "--short", "HEAD").strip() or None
        status = run("status", "--porcelain", "--untracked-files=all", "--", "backtest",
                     ":(exclude)backtest/results", ":(exclude)backtest/TRIALS.md")
        return {"commit": commit, "dirty": bool(status.strip())}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def code_fingerprint() -> str:
    """backtest/*.py(테스트 제외) 내용의 sha256 — 커밋 전 코드로 돌린 결과도 어떤 코드였는지 알 수 있게."""
    h = hashlib.sha256()
    for path in sorted((C.REPO_ROOT / "backtest").glob("*.py")):
        h.update(path.name.encode("utf-8") + b"\0")
        h.update(path.read_bytes() + b"\0")
    return h.hexdigest()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _data_info(market: MarketData, source: str) -> dict:
    """결과 JSON의 data 항목: 기간, 실행 봉 전환 시각, 펀딩 대체값, 입력 파일 해시."""
    eb = market.exec_bars
    o_ns = eb["open_ns"].to_numpy(dtype=np.int64)
    dur = eb["close_ns"].to_numpy(dtype=np.int64) - o_ns
    fund = market.funding
    real = fund.loc[~fund["synthetic"].to_numpy(dtype=bool), "time_ns"].to_numpy(dtype=np.int64)
    info = {
        "source": source,
        "span_utc": [C.ns_to_iso(int(o_ns[0])), C.ns_to_iso(int(eb["close_ns"].iloc[-1]))] if len(eb) else None,
        "exec_switch_utc": C.ns_to_iso(C.EXEC_SWITCH_NS),
        "exec_bars": {"n": int(len(eb)), "n_5m": int(np.count_nonzero(dur == C.TF_NS["5m"])),
                      "n_1m": int(np.count_nonzero(dur == C.TF_NS["1m"]))},
        "funding_last_real_utc": C.ns_to_iso(int(real[-1])) if real.size else None,
        "funding_n_synthetic": int(fund["synthetic"].to_numpy(dtype=bool).sum()),
        "funding_fallback_rate": C.FUNDING_FALLBACK_RATE,
        "sha256": D.data_fingerprint() if source == "binance" else {},
        "events_file": None,
    }
    if market.events_ns is not None and C.EVENTS_CSV.exists():
        info["events_file"] = {"path": str(C.EVENTS_CSV.relative_to(C.REPO_ROOT)), "n": int(len(market.events_ns)),
                               "sha256": _file_sha256(C.EVENTS_CSV)}
    return info


def _daily_for_period(daily: pd.DataFrame, period) -> pd.DataFrame:
    """돈치안용 일봉: 기간이 있으면 시작 전 101일(채널 준비 100일 + 1)부터 끝까지만 → 자산 곡선이 기간 시작에서 출발."""
    if period is None:
        return daily
    lo, hi = period
    o_ns = daily["open_ns"].to_numpy(dtype=np.int64)
    c_ns = daily["close_ns"].to_numpy(dtype=np.int64)
    i0 = 0 if lo is None else int(np.searchsorted(o_ns, lo, side="left"))
    i1 = len(daily) if hi is None else int(np.searchsorted(c_ns, hi, side="right"))
    return daily.iloc[max(0, i0 - max(C.DONCHIAN_PERIODS) - 1):i1]


def sensitivity_variants(cfg: ComboConfig, events_available: bool = False) -> list[tuple[str, ComboConfig]]:
    """기본 조합 하나의 민감도 변형(§9, config.SENSITIVITY_VARIANTS 순서). 이벤트 파일이 있으면 'ev'(F3 켬, §10-2) 추가.

    L1b 조합에는 명세 §9 목록 밖의 진단 'rearm'(config.L1B_REARM_VARIANT: 검토 전 구현의 해석, 옛 I-22 재준비)을 맨 뒤에
    덧붙인다 — 보고만 하고 판정·선택에 쓰지 않는다(검토 SPEC-L1B-REARM).
    """
    base = cfg.replace(apply_availability_mask=True)
    out = [(tag, base.replace(**changes)) for tag, changes in C.SENSITIVITY_VARIANTS]
    if events_available:
        out.append(("ev", base.replace(event_filter_on=True)))
    if base.scenario == "L1b":
        tag, changes = C.L1B_REARM_VARIANT
        out.append((tag, base.replace(**changes)))
    return out


# ---------------------------------------------------------------------------
# 조합 하나
# ---------------------------------------------------------------------------


def _run_combo_timed(market: MarketData, cfg: ComboConfig, *, xb: ExecArrays, fa: FundingArrays, ctx_cache: dict,
                     n_reps: int, with_random: bool, out_dir: Path | None, period=None,
                     signal_logs: bool = False) -> tuple[dict, dict]:
    """run_combo의 본체: (combos[] 항목, 단계별 시간(초)). 시간은 결과 JSON에 넣지 않는다(결정성)."""
    tm: dict[str, float] = {}
    t = time.perf_counter()
    cfg_exec = cfg.replace(apply_availability_mask=True)       # §12.3 실행 가능 (G1 판정 기준)
    cfg_all = cfg.replace(apply_availability_mask=False)       # §12.3 전체 (마스크 없음)
    cfg_cost2 = cfg_exec.replace(cost_multiplier=C.G1_COST_STRESS_MULT)  # §8.3-4 비용 2배 (I-27)
    ctx = get_context(ctx_cache, market, cfg.setting, cfg.vr_threshold)
    # 후보는 마스크·비용 배수와 무관하다(리스크 검사는 기본 비용, I-27) → 한 번 만들어 세 실행이 같이 쓴다
    cands = filter_period(SC.generate_candidates(ctx, cfg_exec), period)
    tm["candidates"] = time.perf_counter() - t

    t = time.perf_counter()
    runs = {
        "all": X.run_sequence(cands, xb, fa, cfg_all),
        "exec": X.run_sequence(cands, xb, fa, cfg_exec),
    }
    trades_cost2, _ = X.run_sequence(cands, xb, fa, cfg_cost2)
    tm["sequence"] = time.perf_counter() - t

    t = time.perf_counter()
    weeks = span_weeks(ctx, period)
    summaries = {mode: M.summarize_run(runs[mode][0], runs[mode][1], span_weeks=weeks,
                                       rng_key=(cfg_all if mode == "all" else cfg_exec).key)
                 for mode in MODES}
    cost2 = M.summarize_cost_stress(runs["exec"][0], trades_cost2, rng_key=cfg_cost2.key)
    if not cost2["same_trades"]:
        # 비용은 체결·청산 시점을 바꾸지 않아야 한다(I-27). 다르면 엔진 오류이므로 멈춘다.
        raise RuntimeError(f"{cfg.base_key}: 비용 2배 실행의 거래 집합이 기본 비용과 다르다 (I-27 위반)")
    tm["summary"] = time.perf_counter() - t

    t = time.perf_counter()
    n_exec = int(summaries["exec"]["n"])
    rb = None
    if with_random:
        rb = RB.run_random_baseline(runs["exec"][0], ctx.s_bars["close_ns"].to_numpy(dtype=np.int64), xb, fa,
                                    cfg_exec, n_reps=int(n_reps))                 # §8.4, §12.4 (실행 가능 거래 기준)
    random_block = _random_block(rb, n_exec)
    tm["random"] = time.perf_counter() - t

    verdict = M.g1_verdict(summaries["exec"], cost2["mean_r"], random_block["p95"])  # §8.3

    t = time.perf_counter()
    if out_dir is not None:
        for mode, c in (("all", cfg_all), ("exec", cfg_exec)):
            trades, logs = runs[mode]
            _write_records_csv(trades, c.key, Path(out_dir) / TRADES_DIR / f"{c.key}.csv", _TRADE_COLUMNS)
            if signal_logs:
                _write_records_csv(logs, c.key, Path(out_dir) / SIGNALS_DIR / f"{c.key}.csv.gz", _SIGNAL_COLUMNS)
    tm["write_csv"] = time.perf_counter() - t

    entry = {
        "key": cfg.base_key,
        "config": cfg_exec.as_dict(),
        "all": summaries["all"],
        "exec": summaries["exec"],
        "exec_cost2": cost2,
        "random": random_block,
        "dsr": None,          # 모든 조합을 돌린 뒤 run_g1이 채운다 (I-41)
        "verdict": verdict,
    }
    return entry, tm


def run_combo(market: MarketData, cfg: ComboConfig, *, xb: ExecArrays, fa: FundingArrays,
              ctx_cache: dict, n_reps: int, with_random: bool, out_dir: Path | None,
              period=None, signal_logs: bool = False) -> dict:
    """기본 조합 하나(cfg는 기본 설정)의 'all'·'exec'·비용 2배·무작위 기준선을 돌려 DESIGN §8.1의 combos[] 항목을 만든다.

    out_dir가 있으면 trades/<key>.csv를 쓴다(두 모드 모두, key = 'L1a-DA-P1_all' | '…_exec').
    period = (시작 ns | None, 끝 ns | None): 승인 시각이 그 안인 후보만 쓴다. signal_logs면 signals/<key>.csv.gz도 쓴다.
    dsr은 None으로 두고, 모든 조합을 돌린 뒤 run_g1이 채운다.
    """
    entry, _ = _run_combo_timed(market, cfg, xb=xb, fa=fa, ctx_cache=ctx_cache, n_reps=n_reps,
                                with_random=with_random, out_dir=out_dir, period=period, signal_logs=signal_logs)
    return entry


def run_sensitivity(market: MarketData, tag: str, cfg: ComboConfig, *, xb: ExecArrays, fa: FundingArrays,
                    ctx_cache: dict, period=None) -> dict:
    """민감도 하나(실행 가능 모드) → DESIGN §8.1의 sensitivity[] 항목. 무작위 기준선은 돌리지 않는다.

    결과는 보고만 하고 조합 선택·판정에 쓰지 않는다 (§9).
    """
    ctx = get_context(ctx_cache, market, cfg.setting, cfg.vr_threshold)
    cands = filter_period(SC.generate_candidates(ctx, cfg), period)
    trades, logs = X.run_sequence(cands, xb, fa, cfg)
    summary = M.summarize_run(trades, logs, span_weeks=span_weeks(ctx, period), rng_key=cfg.key)
    return {"key": cfg.base_key, "variant": tag, "config": cfg.as_dict(), "exec": summary}


# ---------------------------------------------------------------------------
# 작업 단위(기본 조합 + 그 민감도) — 순차·병렬 공용
# ---------------------------------------------------------------------------


def _combo_task(task: tuple) -> tuple:
    """작업 하나: (번호, 기본 조합, 민감도 목록) → (번호, combos[] 항목, sensitivity[] 항목들, 시간)."""
    idx, cfg, variants = task
    st = _STATE
    t0 = time.perf_counter()
    entry, tm = _run_combo_timed(st["market"], cfg, xb=st["xb"], fa=st["fa"], ctx_cache=st["ctx_cache"],
                                 n_reps=st["n_reps"], with_random=st["with_random"], out_dir=st["out_dir"],
                                 period=st["period"], signal_logs=st["signal_logs"])
    t = time.perf_counter()
    sens = [run_sensitivity(st["market"], tag, vcfg, xb=st["xb"], fa=st["fa"], ctx_cache=st["ctx_cache"],
                            period=st["period"]) for tag, vcfg in variants]
    tm["sensitivity"] = time.perf_counter() - t
    tm["total"] = time.perf_counter() - t0
    return idx, entry, sens, tm


def _run_tasks(tasks: list[tuple], jobs: int, log) -> list[tuple]:
    """작업들을 순차(jobs=1) 또는 fork 프로세스 풀로 돌리고 입력 순서대로 돌려준다."""
    out: list = [None] * len(tasks)

    def done(res):
        idx, entry, _, tm = res
        out[idx] = res
        log(f"{entry['key']:<10s} 완료 {tm['total']:6.2f}초 (후보 {tm['candidates']:.2f} · 순차 {tm['sequence']:.2f}"
            f" · 요약 {tm['summary']:.2f} · 무작위 {tm['random']:.2f} · 민감도 {tm['sensitivity']:.2f})"
            f" 실행 가능 거래 {entry['exec']['n']}건")

    use_pool = jobs > 1 and len(tasks) > 1 and "fork" in mp.get_all_start_methods()
    if not use_pool:
        if jobs > 1 and len(tasks) > 1:
            log("fork를 쓸 수 없어 순차로 실행한다")
        for task in tasks:
            done(_combo_task(task))
        return out
    with ProcessPoolExecutor(max_workers=min(jobs, len(tasks)), mp_context=mp.get_context("fork")) as ex:
        futures = [ex.submit(_combo_task, task) for task in tasks]
        for fut in as_completed(futures):
            done(fut.result())
    return out


# ---------------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------------


class _RunLog:
    """진행 기록: 표준 오류로 찍고, 끝나면 run_log.txt로 남긴다."""

    def __init__(self, t0: float, quiet: bool = False):
        self.t0, self.quiet, self.lines = t0, quiet, []

    def __call__(self, msg: str) -> None:
        line = f"[{time.perf_counter() - self.t0:7.1f}초] {msg}"
        self.lines.append(line)
        if not self.quiet:
            print(line, file=sys.stderr, flush=True)


def _short_time(ns: int | None, none: str) -> str:
    """사람이 읽는 시각: 자정이면 날짜만('2024-01-01'), 아니면 ISO 전체. None이면 none."""
    if ns is None:
        return none
    iso = C.ns_to_iso(int(ns))
    return iso[:10] if int(ns) % C.NS_PER_DAY == 0 else iso


def _event_filter_note(market: MarketData) -> str:
    if market.events_ns is None:
        return "off: data/events.csv 없음"                         # DESIGN §8.1 예시 문구 그대로 (§10-2)
    return "off: G1 기본(§10-2), data/events.csv 있음 → 민감도 'ev'(F3 켬)로만 확인"


def _decision(official: bool, why_partial: list[str], passed: list[str]) -> str:
    """summary.decision 문장 (§8.3)."""
    if not official:
        return ("부분 실행(" + ", ".join(why_partial) + ") → 공식 G1 판정이 아니다. "
                "판정은 전체 기간·16조합·무작위 기준선을 모두 넣은 실행으로 한다.")
    if passed:
        return f"통과 후보 {len(passed)}개({', '.join(passed)}) → 사용자와 다음 단계 진행 여부 결정 (§8.3)"
    return "통과 후보 0개 → 개발 중지, 사용자와 재검토 (§8.3)"


def run_g1(*, out_dir: Path = C.RESULTS_DIR, n_reps: int = C.RANDOM_REPS, jobs: int = 4,
           only: list[str] | None = None, sensitivity: bool = True, random: bool = True,
           trials: bool = True, start=None, end=None, market: MarketData | None = None,
           trials_path: Path = C.TRIALS_MD, report: bool = True, signal_logs: bool = False,
           note: str = "", quiet: bool = False) -> dict:
    """G1 전체 실행 → 결과 dict(= g1_results.json 내용). 병렬로 돌려도 결과가 같아야 한다(조합별 시드).

    덧붙인 키워드(기본값이면 설계 그대로):
    - start/end: 기간(UTC, 승인 시각 기준 [시작, 끝)). 지표·구조는 그 전 데이터로 준비하고, 기간 안에 진입한
      거래는 기간 뒤 데이터로 끝까지 청산한다. 기본은 전체.
    - market: 미리 만든 MarketData(테스트용 합성 시장). None이면 data.load_market()으로 실데이터를 읽는다.
    - trials_path: TRIALS.md 경로(테스트는 임시 복사본). report: G1_REPORT.md를 만들지.
    - signal_logs: 후보별 전체 신호 기록 CSV. note: TRIALS.md·params에 남길 메모. quiet: 진행 기록을 찍지 않음.
    """
    global _STATE
    t_start = time.perf_counter()
    created_utc = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    log = _RunLog(t_start, quiet)
    out_dir = Path(out_dir)
    period = parse_period(start, end)
    combos = select_combos(only)
    n_reps = int(n_reps) if random else 0
    stage: dict[str, float] = {}

    # 1. 데이터
    t = time.perf_counter()
    source = "binance" if market is None else "injected"
    if market is None:
        market = D.load_market()
    xb, fa = market.exec_arrays(), market.funding_arrays()
    data_info = _data_info(market, source)
    stage["load"] = time.perf_counter() - t
    log(f"데이터 준비 {stage['load']:.1f}초: 실행 봉 {len(xb):,}개, 펀딩 {len(fa.time_ns):,}개 ({source})")

    # 2. 문맥 (fork 전에 부모가 만들어 두면 작업 프로세스가 물려받는다)
    t = time.perf_counter()
    events_available = market.events_ns is not None
    ctx_cache: dict = {}
    needed = {(c.setting, float(c.vr_threshold)) for c in combos}
    variants = {c.base_key: (sensitivity_variants(c, events_available) if sensitivity else []) for c in combos}
    needed |= {(v.setting, float(v.vr_threshold)) for vs in variants.values() for _, v in vs}
    for setting, vr in sorted(needed):
        get_context(ctx_cache, market, setting, vr)
    stage["contexts"] = time.perf_counter() - t
    log(f"문맥 준비 {stage['contexts']:.1f}초: " + ", ".join(f"{s}·VR{v:g}" for s, v in sorted(needed)))

    # 3. 조합 실행 (+ 민감도)
    out_dir.mkdir(parents=True, exist_ok=True)
    _clear_outputs(out_dir)
    _STATE = dict(market=market, xb=xb, fa=fa, ctx_cache=ctx_cache, n_reps=n_reps, with_random=bool(random),
                  out_dir=out_dir, period=period, signal_logs=bool(signal_logs))
    t = time.perf_counter()
    try:
        tasks = [(i, cfg, variants[cfg.base_key]) for i, cfg in enumerate(combos)]
        outputs = _run_tasks(tasks, int(jobs), log)
    finally:
        _STATE = {}
    stage["combos"] = time.perf_counter() - t
    combos_out = [o[1] for o in outputs]
    sens_out = [s for o in outputs for s in o[2]]
    task_times = {o[1]["key"]: o[3] for o in outputs}
    log(f"조합 {len(combos_out)}개 + 민감도 {len(sens_out)}개 {stage['combos']:.1f}초 (프로세스 {jobs}개)")

    # 4. DSR (I-41): 실행 가능 모드, 거래 2건 이상 조합의 거래당 샤프 분산
    sr_var = M.sharpe_trials_variance([c["exec"]["sharpe"] for c in combos_out])
    for c in combos_out:
        c["dsr"] = M.dsr_from_summary(c["exec"], sr_var)

    # 5. 돈치안 기준선 (§8.4, 비교용 보고만)
    t = time.perf_counter()
    donchian = None
    if "1d" in market.bars and len(market.bars["1d"]):
        donchian = B.donchian_ensemble(_daily_for_period(market.bars["1d"], period), fa, xb)
        donchian.pop("equity", None)                          # 일별 자산 배열은 JSON에 넣지 않는다
    stage["donchian"] = time.perf_counter() - t

    # 6. 요약·판정 (§8.3)
    by_result = {r: [c["key"] for c in combos_out if c["verdict"]["result"] == r] for r in ("pass", "fail", "pending")}
    why_partial = []
    if period is not None:
        why_partial.append(f"기간 {_short_time(period[0], '처음')}~{_short_time(period[1], '끝')}")
    if len(combos) != len(C.g1_combos()):
        why_partial.append(f"조합 {len(combos)}개")
    if not random:
        why_partial.append("무작위 기준선 없음")
    elif n_reps < C.RANDOM_REPS_REDUCED:
        why_partial.append(f"무작위 {n_reps}회 < {C.RANDOM_REPS_REDUCED}회")
    if source != "binance":
        why_partial.append("합성 데이터")
    official = not why_partial
    summary = {
        "pass_candidates": by_result["pass"],
        "pending": by_result["pending"],
        "fail": by_result["fail"],
        "n_pass": len(by_result["pass"]),
        "n_pending": len(by_result["pending"]),
        "n_fail": len(by_result["fail"]),
        "official": official,
        "partial_reasons": why_partial,
        "decision": _decision(official, why_partial, by_result["pass"]),
    }

    git = _git_info()
    params = {
        "latency_min": C.LATENCY_DEFAULT_MIN,
        "latency_sensitivity_min": list(C.LATENCY_SENSITIVITY_MIN),
        "random_reps": n_reps,
        "random_reps_reduced": bool(random) and n_reps < C.RANDOM_REPS,
        "random_enabled": bool(random),
        "bootstrap_n": C.BOOTSTRAP_N,
        "perm_n": C.PERM_N,
        "seed": C.RANDOM_SEED,
        "dsr_n_trials": C.DSR_N_TRIALS,
        "cost_stress_mult": C.G1_COST_STRESS_MULT,
        "event_filter": _event_filter_note(market),
        "period_utc": None if period is None else [C.ns_to_iso(period[0]) if period[0] is not None else None,
                                                   C.ns_to_iso(period[1]) if period[1] is not None else None],
        "period_basis": "승인 시각(신호 봉 마감 + 60초) ∈ [시작, 끝). 진입한 거래는 기간 뒤 데이터로 끝까지 청산",
        "combos_selected": [c.base_key for c in combos],
        "only": list(only) if only else None,
        "sensitivity": bool(sensitivity),
        "sensitivity_variants": [tag for tag, _ in C.SENSITIVITY_VARIANTS] + (["ev"] if events_available else [])
                                + [f"{C.L1B_REARM_VARIANT[0]}(L1b 진단, 명세 §9 밖)"],
        "availability": {"dnd_kst": "00:30~07:30", "daily_cap": C.DAILY_APPROVAL_CAP},
        "donchian_cap_mode": donchian.get("cap_mode") if donchian else None,
        "note": note,
    }
    files = {"results_json": RESULTS_JSON, "report_md": REPORT_MD if report else None,
             "trades_dir": TRADES_DIR, "signals_summary_csv": SIGNALS_SUMMARY_CSV,
             "signals_dir": SIGNALS_DIR if signal_logs else None, "run_log": RUN_LOG}
    results = {
        "schema": SCHEMA,
        "spec_version": C.SPEC_VERSION,
        "created_utc": created_utc,
        "runtime_sec": None,
        "git_commit": git["commit"],
        "git_dirty": git["dirty"],
        "code_sha256": code_fingerprint(),
        "data": data_info,
        "params": params,
        "combos": combos_out,
        "dsr_sr_trials_var": sr_var,
        "sensitivity": sens_out,
        "donchian": donchian,
        "summary": summary,
        "files": files,
    }

    # 7. 파일 쓰기
    t = time.perf_counter()
    results["runtime_sec"] = round(time.perf_counter() - t_start, 1)
    results = to_jsonable(results)
    path = write_results(results, out_dir)
    signals_summary_frame(results).to_csv(out_dir / SIGNALS_SUMMARY_CSV, index=False)
    stage["write"] = time.perf_counter() - t
    log(f"결과 쓰기 {stage['write']:.1f}초: {path}")
    if trials:
        append_trials(results, trials_path)
        log(f"시도 기록 한 줄 추가: {trials_path}")
    if report:
        t = time.perf_counter()
        rp = RPT.write_report(path, out_dir / REPORT_MD)
        stage["report"] = time.perf_counter() - t
        log(f"보고서 {stage['report']:.1f}초: {rp}")
    total = time.perf_counter() - t_start
    log(f"끝: 총 {total:.1f}초 — {summary['decision']}")
    _write_run_log(out_dir / RUN_LOG, log, results, stage, task_times, jobs, total)
    return results


def _write_run_log(path: Path, log: _RunLog, results: dict, stage: dict, task_times: dict, jobs: int,
                   total: float) -> None:
    """실행 시간 기록(run_log.txt): 진행 줄 + 단계별·조합별 시간 표. 결과 JSON과 달리 실행마다 달라진다."""
    lines = [f"G1 실행 기록 — {results['created_utc']} (명세 {results['spec_version']}, 커밋 {results['git_commit']})",
             f"프로세스 {jobs}개, CPU {os.cpu_count()}개, 총 {total:.1f}초", "", "[진행]", *log.lines, "",
             "[단계별 시간(초)]"]
    lines += [f"  {k:<10s} {v:8.2f}" for k, v in stage.items()]
    lines += ["", "[조합별 시간(초) — 작업 프로세스 안에서 잰 값]",
              "  조합        합계   후보   순차   요약  무작위  CSV  민감도"]
    sums: dict[str, float] = {}
    for key, tm in task_times.items():
        lines.append(f"  {key:<10s} {tm['total']:6.2f} {tm['candidates']:6.2f} {tm['sequence']:6.2f} "
                     f"{tm['summary']:6.2f} {tm['random']:6.2f} {tm['write_csv']:5.2f} {tm['sensitivity']:6.2f}")
        for k, v in tm.items():
            sums[k] = sums.get(k, 0.0) + v
    if sums:
        lines.append(f"  {'합계':<10s} {sums['total']:6.2f} {sums['candidates']:6.2f} {sums['sequence']:6.2f} "
                     f"{sums['summary']:6.2f} {sums['random']:6.2f} {sums['write_csv']:5.2f} {sums['sensitivity']:6.2f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 결과 파일
# ---------------------------------------------------------------------------


def write_results(results: dict, out_dir: Path) -> Path:
    """g1_results.json을 쓴다(types.to_jsonable, ensure_ascii=False, indent=1, NaN 없음). 경로를 돌려준다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / RESULTS_JSON
    text = json.dumps(to_jsonable(results), ensure_ascii=False, indent=1, allow_nan=False)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)                                     # 원자적 교체 (쓰다 만 파일이 남지 않게)
    return path


def signals_summary_frame(results: dict) -> pd.DataFrame:
    """신호 로그 요약(폐기 사유별 개수) 표: 조합 × 모드 × 사유.

    열: combo, mode(all|exec), n_candidates, reason, reason_ko, first_count(대표 사유 기준),
    any_count(그 사유가 하나라도 붙은 후보 수), first_share(first_count ÷ n_candidates).
    reason = 'PASSED' 줄은 통과(실행한 계획) 수라서, 한 조합·모드의 first_count 합 = n_candidates.
    """
    rows = []
    for c in results["combos"]:
        for mode in MODES:
            s = c[mode]
            n = int(s["n_candidates"])
            share = (lambda k: k / n if n else None)
            rows.append({"combo": c["key"], "mode": mode, "n_candidates": n, "reason": PASSED_ROW,
                         "reason_ko": RPT.REASON_KO[PASSED_ROW], "first_count": int(s["n_passed"]),
                         "any_count": int(s["n_passed"]), "first_share": share(int(s["n_passed"]))})
            first, any_ = s["discard_first_reason"], s["discard_any_reason"]
            for r in REASON_ORDER:
                f = int(first.get(r, 0))
                rows.append({"combo": c["key"], "mode": mode, "n_candidates": n, "reason": r,
                             "reason_ko": RPT.REASON_KO.get(r, r), "first_count": f,
                             "any_count": int(any_.get(r, 0)), "first_share": share(f)})
    cols = ["combo", "mode", "n_candidates", "reason", "reason_ko", "first_count", "any_count", "first_share"]
    return pd.DataFrame(rows, columns=cols)


def trials_line(results: dict) -> str:
    """TRIALS.md 표의 한 줄 (§9, DESIGN §8.4)."""
    p, s = results["params"], results["summary"]
    commit = results.get("git_commit") or "없음"
    if results.get("git_dirty"):
        commit += "+작업 트리 변경"
    head = "G1 실행" if s.get("official") else "부분 실행"
    bits = []
    if p.get("period_utc"):
        a, b = p["period_utc"]
        bits.append(f"기간 {(a or '처음')[:10]}~{(b or '끝')[:10]}")
    bits.append(f"무작위 {p['random_reps']}회" if p.get("random_enabled") else "무작위 없음")
    if not p.get("sensitivity"):
        bits.append("민감도 없음")
    bits.append("F3 꺼짐")
    bits.append(f"커밋 {commit}")
    if results.get("data", {}).get("source") != "binance":
        bits.append("합성 데이터")
    if p.get("note"):
        bits.append(str(p["note"]))
    content = f"{head} ({', '.join(bits)})"
    res = f"통과 후보 {s['n_pass']}개"
    if s["pass_candidates"]:
        res += ": " + ", ".join(s["pass_candidates"])
    res += f" / 불합격 {s['n_fail']}개 / 보류 {s['n_pending']}개"
    if not s.get("official"):
        res += " (공식 G1 아님)"
    cells = [results["created_utc"][:10], results["spec_version"], content, str(len(results["combos"])), res]
    return "| " + " | ".join(x.replace("|", "/").replace("\n", " ") for x in cells) + " |"


def append_trials(results: dict, path: Path = C.TRIALS_MD) -> None:
    """TRIALS.md 표에 한 줄 추가 (§9): | 날짜 | v1.0 | 내용(무작위 반복 수·F3 상태) | 16 | 통과 후보 요약 |."""
    path = Path(path)
    if not path.exists():
        path.write_text("# 백테스트 시도 기록\n\n| 날짜 | 명세 버전 | 내용 | 조합 수 | 결과 요약 |\n"
                        "|---|---|---|---|---|\n", encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    with open(path, "a", encoding="utf-8") as fh:
        if text and not text.endswith("\n"):
            fh.write("\n")
        fh.write(trials_line(results) + "\n")                 # 지우지 않고 덧붙이기만 한다 (§9)


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. 성공 0."""
    args = parse_args(argv)
    results = run_g1(out_dir=args.out, n_reps=args.reps, jobs=args.jobs, only=args.only,
                     sensitivity=not args.no_sensitivity, random=not args.no_random, trials=not args.no_trials,
                     start=args.start, end=args.end, report=not args.no_report, signal_logs=args.signal_logs,
                     note=args.note)
    s = results["summary"]
    print(f"G1 {'판정' if s['official'] else '부분 실행'}: 통과 후보 {s['n_pass']}개 / 불합격 {s['n_fail']}개 / "
          f"보류 {s['n_pending']}개 — {s['decision']}")
    print(f"결과: {Path(args.out) / RESULTS_JSON}")
    if not args.no_report:
        print(f"보고서: {Path(args.out) / REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
