"""통합 테스트 (DESIGN §9 T-INT) — run_g1 전체 흐름, 결과 파일 스키마, 결정성, 시도 기록, 보고서.

- 합성 시장(conftest.make_market 300일, 2023-10-01 전 5분 / 이후 1분 실행 봉)으로 16조합 + 민감도 80개를 끝까지
  돌린다(몇 초). 이 시장은 P1 몇 조합에서 거래가 나고, 실행 가능 모드에서 방해 금지·하루 6건으로 빠지는 신호도 있다.
- 실데이터 테스트(2024-01~03, P1 조합 하나)는 @slow이며 데이터가 없으면 건너뛴다.
"""
from __future__ import annotations

import json
import math
import shutil

import numpy as np
import pandas as pd
import pytest

from backtest import config as C
from backtest import execution as X
from backtest import metrics as M
from backtest import report as RPT
from backtest import run_g1 as R
from backtest import types as T
from backtest.tests.conftest import make_market

REPS = 30  # 테스트용 무작위 기준선 반복 수

TOP_KEYS = ("schema", "spec_version", "created_utc", "runtime_sec", "git_commit", "data", "params", "combos",
            "dsr_sr_trials_var", "sensitivity", "donchian", "summary")          # DESIGN §8.1
COMBO_KEYS = ("key", "config", "all", "exec", "exec_cost2", "random", "dsr", "verdict")
COST2_KEYS = ("n", "mean_r", "pf", "boot_lo")
RANDOM_KEYS = ("reps", "n_trades", "mean", "p05", "p50", "p95", "n_not_filled", "means")
DONCHIAN_KEYS = ("cagr", "max_drawdown", "sharpe", "n_trades", "final_equity", "start_utc", "end_utc", "per_period")
SUMMARY_KEYS = ("pass_candidates", "pending", "n_pass", "decision")
PARAM_KEYS = ("latency_min", "random_reps", "random_reps_reduced", "bootstrap_n", "perm_n", "seed", "dsr_n_trials",
              "cost_stress_mult", "event_filter")
VOLATILE = ("created_utc", "runtime_sec")  # 결정성 비교에서 뺄 키 (DESIGN §3.5)
N_L1B = sum(c.scenario == "L1b" for c in C.g1_combos())   # L1b 조합에만 붙는 진단 'rearm' 수 (검토 SPEC-L1B-REARM)
N_SENS = 16 * len(C.SENSITIVITY_VARIANTS) + N_L1B          # 민감도 80개 + L1b 재준비 진단 4개


# ---------------------------------------------------------------------------
# 준비
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def market_int() -> T.MarketData:
    """300일 합성 시장 (2023-01-01 시작, 2023-10-01부터 1분 실행 봉). 공유 객체라 수정 금지."""
    return make_market(days=300, seed=2, start="2023-01-01", one_minute_from="2023-10-01")


@pytest.fixture(scope="module")
def run_once(market_int, tmp_path_factory):
    """16조합 + 민감도 전체를 한 번(순차) 돌린 결과와 출력 폴더."""
    out = tmp_path_factory.mktemp("g1_a")
    res = R.run_g1(out_dir=out, n_reps=REPS, jobs=1, market=market_int, trials=False, quiet=True)
    return res, out


def _strip(res: dict) -> dict:
    return {k: v for k, v in res.items() if k not in VOLATILE}


def _no_nan_json(text: str) -> dict:
    def bad(token):
        raise AssertionError(f"JSON에 {token} 토큰이 있음")
    return json.loads(text, parse_constant=bad)


def assert_results_schema(res: dict, n_combos: int, n_sensitivity: int) -> None:
    """결과 dict가 DESIGN §8.1 스키마(+ 덧붙인 키)를 따르는지."""
    for k in TOP_KEYS:
        assert k in res, k
    assert res["schema"] == R.SCHEMA and res["spec_version"] == C.SPEC_VERSION
    assert all(k in res["params"] for k in PARAM_KEYS)
    assert res["params"]["seed"] == C.RANDOM_SEED and res["params"]["dsr_n_trials"] == C.DSR_N_TRIALS
    assert res["params"]["event_filter"].startswith("off")                       # §10-2 F3 꺼짐
    assert len(res["combos"]) == n_combos
    order = [c.base_key for c in C.g1_combos()]
    keys = [c["key"] for c in res["combos"]]
    assert keys == sorted(keys, key=order.index)                                 # g1_combos() 순서
    for c in res["combos"]:
        assert tuple(c) == COMBO_KEYS
        assert c["config"]["key"] == f"{c['key']}_exec" and c["config"]["apply_availability_mask"] is True
        for mode in R.MODES:
            assert tuple(c[mode])[:len(M.RUN_SUMMARY_KEYS)] == M.RUN_SUMMARY_KEYS   # §8.2 순서
        assert all(k in c["exec_cost2"] for k in COST2_KEYS)
        assert all(k in c["random"] for k in RANDOM_KEYS)
        if not c["random"].get("skipped"):                                        # 같은 진입 수수료 분포(보고용, F2)
            assert set(c["random"]["same_fee"]) == {"entry_fee_rate", "mean", "p05", "p50", "p95"}
        assert tuple(c["verdict"]) == M.VERDICT_KEYS
        assert c["verdict"]["result"] in ("pass", "fail", "pending")
    assert len(res["sensitivity"]) == n_sensitivity
    for s in res["sensitivity"]:
        assert set(s) == {"key", "variant", "config", "exec"}
        assert s["config"]["mode"] == "exec" and s["config"]["variant"] == s["variant"]
        assert (s["variant"] == C.L1B_REARM_VARIANT[0]) == s["config"]["l1b_rearm"]
        assert not s["config"]["l1b_rearm"] or s["key"].startswith("L1b-")      # 진단은 L1b에만
    if res["donchian"] is not None:
        assert all(k in res["donchian"] for k in DONCHIAN_KEYS) and "equity" not in res["donchian"]
    assert all(k in res["summary"] for k in SUMMARY_KEYS)


# ---------------------------------------------------------------------------
# T-INT-1: 스키마·파일
# ---------------------------------------------------------------------------


def test_results_json_schema_and_file(run_once):
    res, out = run_once
    assert_results_schema(res, 16, N_SENS)
    text = (out / R.RESULTS_JSON).read_text(encoding="utf-8")
    assert _no_nan_json(text) == res                                             # 돌려준 dict = 파일 내용, NaN 없음
    assert [s["variant"] for s in res["sensitivity"][:5]] == [t for t, _ in C.SENSITIVITY_VARIANTS]
    assert res["data"]["source"] == "injected" and res["data"]["sha256"] == {}
    assert res["summary"]["official"] is False                                   # 합성 데이터·무작위 30회
    assert "부분 실행" in res["summary"]["decision"]
    for name in (R.REPORT_MD, R.SIGNALS_SUMMARY_CSV, R.RUN_LOG):
        assert (out / name).is_file(), name


def test_run_combo_direct_matches_pipeline(run_once, market_int, tmp_path):
    """run_combo를 직접 불러도 combos[] 항목과 같고(dsr 제외), trades CSV가 두 모드 모두 생긴다."""
    res, _ = run_once
    xb, fa = market_int.exec_arrays(), market_int.funding_arrays()
    cfg = C.ComboConfig("L1b", "DB", "P1")
    entry = R.run_combo(market_int, cfg, xb=xb, fa=fa, ctx_cache={}, n_reps=REPS, with_random=True, out_dir=tmp_path)
    assert tuple(entry) == COMBO_KEYS and entry["dsr"] is None
    ref = next(c for c in res["combos"] if c["key"] == cfg.base_key)
    got = T.to_jsonable(entry)
    assert {k: v for k, v in got.items() if k != "dsr"} == {k: v for k, v in ref.items() if k != "dsr"}
    for mode in R.MODES:
        path = tmp_path / R.TRADES_DIR / f"{cfg.base_key}_{mode}.csv"
        assert path.is_file()
        assert pd.read_csv(path).columns[0] == "key"


def test_run_sensitivity_direct_matches_pipeline(run_once, market_int):
    res, _ = run_once
    xb, fa = market_int.exec_arrays(), market_int.funding_arrays()
    tag, cfg = R.sensitivity_variants(C.ComboConfig("L1b", "DB", "P1"))[0]
    got = T.to_jsonable(R.run_sensitivity(market_int, tag, cfg, xb=xb, fa=fa, ctx_cache={}))
    ref = next(s for s in res["sensitivity"] if s["key"] == "L1b-DB-P1" and s["variant"] == tag)
    assert got == ref


def test_trade_csvs_match_summaries(run_once):
    res, out = run_once
    n_total = 0
    for c in res["combos"]:
        for mode in R.MODES:
            df = pd.read_csv(out / R.TRADES_DIR / f"{c['key']}_{mode}.csv")
            s = c[mode]
            assert list(df.columns[:2]) == ["key", "plan_id"]
            assert len(df) == sum(s["status_counts"].values())                   # 실행한 계획 전부(미체결 포함)
            filled = df[df["status"] == T.Status.FILLED]
            assert len(filled) == s["n"]
            if s["n"]:
                assert (filled["key"] == f"{c['key']}_{mode}").all()
                assert math.isclose(filled["r_multiple"].mean(), s["mean_r"], rel_tol=1e-9, abs_tol=1e-12)
            n_total += s["n"]
    assert n_total > 0, "합성 시장에서 거래가 하나도 나지 않았다 — 테스트 시장을 바꿔야 한다"


def test_signals_summary_partition(run_once):
    """signals_summary.csv: 조합·모드마다 대표 사유 수 + 통과 수 = 후보 수, 포함 수 ≥ 대표 수."""
    res, out = run_once
    df = pd.read_csv(out / R.SIGNALS_SUMMARY_CSV)
    assert set(df["reason"]) == set(T.REASON_ORDER) | {R.PASSED_ROW}
    by = {(c["key"], m): c[m] for c in res["combos"] for m in R.MODES}
    for (combo, mode), g in df.groupby(["combo", "mode"]):
        s = by[(combo, mode)]
        assert g["first_count"].sum() == s["n_candidates"] == g["n_candidates"].iloc[0]
        assert int(g.loc[g["reason"] == R.PASSED_ROW, "first_count"].iloc[0]) == s["n_passed"]
        assert (g["any_count"] >= g["first_count"]).all()
        if mode == "all":                                                        # 전체 모드는 마스크 없음
            assert g.loc[g["reason"].isin(["MASK_DND", "MASK_DAILY_CAP"]), "any_count"].sum() == 0


def test_availability_mask_only_in_exec_mode(run_once):
    res, _ = run_once
    masked = 0
    for c in res["combos"]:
        assert c["all"]["discard_any_reason"]["MASK_DND"] == 0
        assert c["all"]["discard_any_reason"]["MASK_DAILY_CAP"] == 0
        masked += c["exec"]["discard_any_reason"]["MASK_DND"] + c["exec"]["discard_any_reason"]["MASK_DAILY_CAP"]
        assert c["all"]["n_candidates"] == c["exec"]["n_candidates"]             # 같은 후보를 두 번 시뮬레이션
    assert masked > 0


def test_cost2_same_trades_and_costlier(run_once):
    res, _ = run_once
    for c in res["combos"]:
        cost2, e = c["exec_cost2"], c["exec"]
        assert cost2["same_trades"] is True and cost2["n"] == e["n"]
        assert cost2["cost_multiplier"] in (C.G1_COST_STRESS_MULT, None)
        if e["n"]:
            assert cost2["mean_r"] < e["mean_r"]                                 # 비용만 커졌다 (I-27)


def test_random_block_and_verdict_recomputed(run_once):
    res, _ = run_once
    for c in res["combos"]:
        rnd, e = c["random"], c["exec"]
        assert rnd["reps"] == REPS and rnd["n_trades"] == e["n"]
        means = [m for m in rnd["means"] if m is not None]
        if e["n"]:
            assert len(rnd["means"]) == REPS
            assert math.isclose(rnd["p95"], float(np.quantile(means, C.G1_RANDOM_QUANTILE)), rel_tol=1e-12)
        else:
            assert rnd["means"] == [] and rnd["p95"] is None
        again = M.g1_verdict(e, c["exec_cost2"]["mean_r"], rnd["p95"])           # JSON 값으로 다시 판정해도 같다
        assert again == c["verdict"]
        if e["n"] < C.G1_MIN_TRADES:
            assert c["verdict"]["result"] == "pending"


def test_dsr_uses_trials_variance(run_once):
    res, _ = run_once
    var = M.sharpe_trials_variance([c["exec"]["sharpe"] for c in res["combos"]])
    stored = res["dsr_sr_trials_var"]
    assert (stored is None and (var is None or math.isnan(var))) or math.isclose(stored, var, rel_tol=1e-12)
    for c in res["combos"]:
        want = M.dsr_from_summary(c["exec"], var)
        assert (c["dsr"] is None and math.isnan(want)) or math.isclose(c["dsr"], want, rel_tol=1e-12)


# ---------------------------------------------------------------------------
# T-INT-2·3·4: 결정성, 프로세스 수 무관, 시도 기록 한 줄
# ---------------------------------------------------------------------------


def test_second_run_with_two_jobs_is_identical_and_appends_one_trials_line(run_once, market_int, tmp_path):
    res_a, out_a = run_once
    trials = tmp_path / "TRIALS.md"
    shutil.copy(C.TRIALS_MD, trials)
    before = trials.read_text(encoding="utf-8").splitlines()
    out_b = tmp_path / "g1_b"
    res_b = R.run_g1(out_dir=out_b, n_reps=REPS, jobs=2, market=market_int, trials=True, trials_path=trials,
                     quiet=True)
    assert _strip(res_a) == _strip(res_b)                                        # T-INT-2·3
    for c in res_a["combos"]:                                                    # 거래 CSV도 바이트 단위로 같다
        for mode in R.MODES:
            name = f"{c['key']}_{mode}.csv"
            assert (out_a / R.TRADES_DIR / name).read_bytes() == (out_b / R.TRADES_DIR / name).read_bytes()
    assert (out_a / R.SIGNALS_SUMMARY_CSV).read_bytes() == (out_b / R.SIGNALS_SUMMARY_CSV).read_bytes()

    def norm(r):  # 보고서도 날짜·실행 시간 말고는 같다
        return RPT.render_markdown({**r, "created_utc": "2000-01-01T00:00:00Z", "runtime_sec": 0})
    assert norm(res_a) == norm(res_b)
    after = trials.read_text(encoding="utf-8").splitlines()                      # T-INT-4
    assert after[:len(before)] == before and len(after) == len(before) + 1
    line = after[-1]
    cells = [x.strip() for x in line.strip().strip("|").split("|")]
    assert len(cells) == 5 and cells[1] == C.SPEC_VERSION and cells[3] == "16"
    assert "F3 꺼짐" in cells[2] and "합성 데이터" in cells[2] and "공식 G1 아님" in cells[4]
    assert cells[0] == res_b["created_utc"][:10]


def test_trials_line_for_official_run_shape(run_once):
    res, _ = run_once
    fake = json.loads(json.dumps(res))
    fake["summary"].update(official=True, pass_candidates=["L1b-DA-P1"], n_pass=1)
    fake["data"]["source"] = "binance"
    fake["params"]["random_reps"] = C.RANDOM_REPS
    line = R.trials_line(fake)
    assert line.startswith(f"| {res['created_utc'][:10]} | {C.SPEC_VERSION} | G1 실행 (무작위 1000회")
    assert "통과 후보 1개: L1b-DA-P1" in line and "공식 G1 아님" not in line


# ---------------------------------------------------------------------------
# T-INT-5: 보고서
# ---------------------------------------------------------------------------


def test_report_has_conclusion_f3_and_sections(run_once):
    res, out = run_once
    md = (out / R.REPORT_MD).read_text(encoding="utf-8")
    assert md == RPT.render_markdown(json.loads((out / R.RESULTS_JSON).read_text(encoding="utf-8")))
    assert "**결론" in md and "F3 이벤트 필터: 꺼짐" in md
    for head in ("## 한눈에 보기", "## 1. 조합별 판정표", "## 2. 전체 신호 vs 실행 가능 신호", "## 3. 신호 폐기 사유",
                 "## 4. 기준선", "## 5. 민감도", "## 6. 과최적화", "## 7. 한계와 가정", "## 8. 재현 방법"):
        assert head in md, head
    for c in res["combos"]:
        assert f"| {c['key']} |" in md
    assert "PBO" in md and "워크포워드" in md and "freqtrade" in md                # 범위 밖 명시
    assert "공식 판정 아님" in md                                                 # 부분 실행 제목


def test_report_conclusion_follows_official_verdict(run_once):
    res, _ = run_once
    fake = json.loads(json.dumps(res))
    fake["summary"].update(official=True, pass_candidates=[], n_pass=0)
    md0 = RPT.render_markdown(fake)
    assert "개발을 멈추고 사용자와 재검토" in md0 and "# G1 판정 보고서" in md0
    fake["summary"].update(pass_candidates=["L1b-DB-P1"], n_pass=1)
    md1 = RPT.render_markdown(fake)
    assert "1개(L1b-DB-P1(DSR " in md1 and "G1 기준을 모두 넘어" in md1


def test_report_conclusion_shows_dsr_and_weak_evidence_note():
    """검토 F5 회귀: 결론 문장의 통과 후보마다 DSR을 붙이고, DSR < 0.95면 '다중 시험 보정 후 근거 약함'을 덧붙인다."""
    def res(dsr):
        return {"summary": {"official": True, "pass_candidates": ["L1b-DA-P1"], "n_pass": 1, "n_fail": 15,
                            "n_pending": 0}, "combos": [{"key": "L1b-DA-P1", "dsr": dsr}]}
    weak = RPT._conclusion(res(0.21))
    assert "L1b-DA-P1(DSR 0.21)" in weak and "근거가 약하다" in weak
    strong = RPT._conclusion(res(0.97))
    assert "L1b-DA-P1(DSR 0.97)" in strong and "근거가 약하다" not in strong
    missing = RPT._conclusion(res(None))
    assert "DSR –" in missing and "근거가 약하다" in missing
    partial = RPT._conclusion({"summary": {"official": False, "partial_reasons": ["기간 2024"], "pass_candidates":
                                           ["L1b-DA-P1"], "n_pass": 1, "n_fail": 0, "n_pending": 15},
                               "combos": [{"key": "L1b-DA-P1", "dsr": 0.5}]})
    assert "L1b-DA-P1(DSR 0.50)" in partial and "근거가 약하다" in partial


def test_report_mentions_review_fixes(run_once):
    """검토 반영 문구: L1b 준비 규칙, R 기준(실제 진입가), 같은 진입 수수료 분포, 즉시 체결될 지정가, 방해 금지 추출, 허리 동점."""
    res, out = run_once
    md = (out / R.REPORT_MD).read_text(encoding="utf-8")
    for text in ("L1b 준비 규칙", "실제 진입가", "같은 진입 수수료 95% 분위(참고)", "즉시 체결될 지정가",
                 "방해 금지 시간(KST 00:30~07:30)의 신호 봉 마감도", "허리 동점 규칙", "L1b 재준비(명세 밖 진단)",
                 "S3 해석 메모", "T-NLA-6"):
        assert text in md, text
    s3 = [c for c in res["combos"] if c["key"].startswith("S3")]
    fake = json.loads(json.dumps(res))
    for c in fake["combos"]:                                                     # S3 전부 0건·RR 미달 → '사실상 시험 안 됨'
        if c["key"].startswith("S3"):
            c["exec"].update(n=0, n_candidates=100, discard_any_reason={**c["exec"]["discard_any_reason"], "RISK_RR": 90})
    md2 = RPT.render_markdown(fake)
    assert len(s3) == 4 and "사실상 시험되지 않았다" in md2 and "명세 그대로의 결과" not in md2


def test_report_accepts_missing_and_infinite_values(run_once):
    """JSON에서 돌아온 None·'inf'·빈 목록이 섞여도 보고서가 만들어진다."""
    res, _ = run_once
    fake = json.loads(json.dumps(res))
    c = fake["combos"][0]
    c["exec"].update(pf="inf", mean_r=None, boot_lo=None)
    c["random"].update(means=[], p95=None)
    fake["sensitivity"], fake["donchian"] = [], None
    md = RPT.render_markdown(fake)
    assert "∞" in md and "민감도를 돌리지 않았다" in md and "미실시" in md


# ---------------------------------------------------------------------------
# 기간·조합 선택·명령행
# ---------------------------------------------------------------------------


def test_period_filters_candidates_by_approval_time(market_int, tmp_path):
    start, end = "2023-07-01", "2023-10-15"
    res = R.run_g1(out_dir=tmp_path, n_reps=5, jobs=1, market=market_int, only=["L1b-DB-P1", "S3-DB-P1"],
                   sensitivity=False, trials=False, report=False, start=start, end=end, signal_logs=True,
                   quiet=True)
    assert_results_schema(res, 2, 0)
    assert res["params"]["period_utc"] == ["2023-07-01T00:00:00Z", "2023-10-15T00:00:00Z"]
    lo, hi = C.ts_ns(start), C.ts_ns(end)
    for c in res["combos"]:
        for mode in R.MODES:
            sig = pd.read_csv(tmp_path / R.SIGNALS_DIR / f"{c['key']}_{mode}.csv.gz")
            assert len(sig) == c[mode]["n_candidates"]
            assert ((sig["time_ns"] >= lo) & (sig["time_ns"] < hi)).all()
            tr = pd.read_csv(tmp_path / R.TRADES_DIR / f"{c['key']}_{mode}.csv")
            assert ((tr["approval_time_ns"] >= lo) & (tr["approval_time_ns"] < hi)).all()
        weeks = c["exec"]["span_weeks"]
        assert 0 < weeks <= (hi - lo) / (7 * C.NS_PER_DAY) + 1e-9
    assert res["summary"]["official"] is False and "기간" in res["summary"]["decision"]
    assert res["donchian"]["start_utc"] >= "2023-06-30"                          # 돈치안도 기간 시작부터


def test_select_combos_and_parse_args():
    assert [c.base_key for c in R.select_combos(["L1b-DA-P1"])] == ["L1b-DA-P1"]
    assert len(R.select_combos(["L1b", "S2"])) == 8
    assert len(R.select_combos(None)) == 16
    with pytest.raises(ValueError):
        R.select_combos(["XYZ"])
    a = R.parse_args(["--only", "L1b-DA-P1,S2", "--reps", "50", "--jobs", "2", "--start", "2024-01-01",
                      "--end", "2025-01-01", "--no-sensitivity", "--no-trials"])
    assert a.only == ["L1b-DA-P1", "S2"] and a.reps == 50 and a.jobs == 2 and a.no_sensitivity and a.no_trials
    assert R.parse_period(a.start, a.end) == (C.ts_ns("2024-01-01"), C.ts_ns("2025-01-01"))
    d = R.parse_args([])
    assert d.reps == C.RANDOM_REPS and d.jobs == 4 and d.only is None and d.out == C.RESULTS_DIR
    with pytest.raises(SystemExit):
        R.parse_args(["--start", "2024-02-01", "--end", "2024-01-01"])
    with pytest.raises(SystemExit):
        R.parse_args(["--jobs", "0"])
    with pytest.raises(SystemExit):
        R.parse_args(["--only", "XYZ"])                                          # 맞는 조합 없음 → 깔끔한 오류


def test_no_random_run_marks_condition5_failed(market_int, tmp_path):
    res = R.run_g1(out_dir=tmp_path, jobs=1, market=market_int, only=["L1b-DB-P1"], random=False,
                   sensitivity=False, trials=False, quiet=True)
    c = res["combos"][0]
    assert c["random"]["reps"] == 0 and c["random"].get("skipped") is True
    assert c["verdict"]["c5_random"] is False
    assert res["params"]["random_enabled"] is False
    assert "무작위 기준선을 돌리지 않았다" in (tmp_path / R.REPORT_MD).read_text(encoding="utf-8")


def test_runs_use_engine_rules_for_all_mode(market_int):
    """'전체' 모드 = 같은 후보를 마스크 없이 run_sequence에 넣은 것 (회계 단일 출처 확인)."""
    from backtest import scenarios as SC
    cfg = C.ComboConfig("L1b", "DB", "P1")
    ctx = SC.build_context(market_int, "P1", 2.0)
    cands = SC.generate_candidates(ctx, cfg)
    cands_all = SC.generate_candidates(ctx, cfg.replace(apply_availability_mask=False))
    js = T.to_jsonable                                                           # NaN을 None으로 바꿔 비교
    assert js([c.log for c in cands]) == js([c.log for c in cands_all])          # 후보는 마스크와 무관
    assert js([c.plan for c in cands]) == js([c.plan for c in cands_all])
    xb, fa = market_int.exec_arrays(), market_int.funding_arrays()
    t1, _ = X.run_sequence(cands, xb, fa, cfg.replace(apply_availability_mask=False))
    t2, _ = X.run_sequence(cands_all, xb, fa, cfg.replace(apply_availability_mask=False))
    assert js(t1) == js(t2)


# ---------------------------------------------------------------------------
# T-INT-6: 실데이터 (짧은 기간, P1 조합 하나)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_real_data_short_period_one_combo(tmp_path):
    from backtest import data as D
    try:
        D.kline_files("1m")
        D.kline_files("1h")
    except FileNotFoundError as exc:
        pytest.skip(f"실데이터 없음: {exc}")
    res = R.run_g1(out_dir=tmp_path, n_reps=20, jobs=1, only=["L1b-DA-P1"], start="2024-01-01", end="2024-04-01",
                   trials=False, quiet=True)
    assert_results_schema(res, 1, len(C.SENSITIVITY_VARIANTS) + 1)             # + L1b 재준비 진단
    d = res["data"]
    assert d["source"] == "binance" and len(d["sha256"]) >= 10
    assert d["span_utc"][0] == "2020-01-01T00:00:00Z" and d["exec_switch_utc"] == "2023-10-01T00:00:00Z"
    assert d["exec_bars"]["n"] == d["exec_bars"]["n_5m"] + d["exec_bars"]["n_1m"]
    assert d["funding_n_synthetic"] > 0 and d["funding_last_real_utc"] == "2026-08-31T16:00:00Z"
    assert res["summary"]["official"] is False
    for mode in R.MODES:
        tr = pd.read_csv(tmp_path / R.TRADES_DIR / f"L1b-DA-P1_{mode}.csv")
        lo, hi = C.ts_ns("2024-01-01"), C.ts_ns("2024-04-01")
        assert ((tr["approval_time_ns"] >= lo) & (tr["approval_time_ns"] < hi)).all()
    md = (tmp_path / R.REPORT_MD).read_text(encoding="utf-8")
    assert "F3 이벤트 필터: 꺼짐" in md and "BTCUSDT_1h.csv.gz" in md
