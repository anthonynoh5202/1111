"""G1-T 보고서 — backtest/results_trend/g1t_results.json → G1T_REPORT.md (한국어).

담을 내용: 맨 앞 비전문가용 요약 → 조합별 7개 기준 표 → 조합별 상세 → E1 vs E0 비교 → 계좌 곡선 두 방식 →
무작위 기준선 → 민감도 → 채택 순위 → 한계와 오염 고지 → 재현 방법.
실행: python -m backtest.report_trend [결과 JSON 경로] [보고서 경로]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from backtest.report import _f, _int, _mark, _num, _pct, _r, _table

RESULTS_DIR = Path(__file__).resolve().parent / "results_trend"

ENTRY_KO = {"E0": "돌파 즉시(시장가)", "E1": "돌파 레벨 눌림 대기(지정가)"}
DIR_KO = {"LS": "롱·숏", "L": "롱만"}
CRIT = (("c1_mean_r", "평균 R ≥ +0.15"), ("c2_boot_lo", "부트스트랩 하한 > 0"), ("c3_pf", "PF ≥ 1.2"),
        ("c4_cost2", "비용 2배 평균 R > 0"), ("c5_random", "무작위 95% 분위 초과"),
        ("c6_years", "양수 연도 ≥ 4"), ("c7_enough_trades", "거래 ≥ 30"))
RESULT_KO = {"pass": "통과", "fail": "불합격", "pending": "보류(거래 < 30)"}
VARIANT_KO = {"lat10": "지연 10분", "lat120": "지연 120분", "stop3": "손절 3 × ATR", "cost2": "비용 2배"}


def combo_name(key: str) -> str:
    """'E0-LS-ENS' → 'E0 돌파 즉시(시장가) · 롱·숏 · 앙상블(20·55·100)'."""
    base = key.split("_")[0]
    e, d, s = base.split("-", 2)
    sys_ko = "앙상블(20·55·100)" if s == "ENS" else f"{s[1:]}일 단독"
    return f"{e} {ENTRY_KO.get(e, e)} · {DIR_KO.get(d, d)} · {sys_ko}"


def _eq(e: dict | None, k: str) -> str:
    if not e:
        return "–"
    return _pct(e.get(k), 1)


def _plain_summary(res: dict) -> list[str]:
    s = res["summary"]
    combos = {c["key"]: c for c in res["combos"]}
    lines = ["## 한눈에 보기 (비전문가용 요약)", ""]
    lines.append(f"- **결론: {s['decision']}.**")
    lines.append(f"- 시험한 방법 {len(combos)}가지 중 7개 합격 기준을 모두 넘은 것 {s['n_pass']}개, "
                 f"거래가 30건이 안 돼 판단을 미룬 것 {s['n_pending']}개, 떨어진 것 {s['n_fail']}개.")
    best = max(combos.values(), key=lambda c: _num(c["summary"]["mean_r"]) or -1e9) if combos else None
    if best:
        b = best["summary"]
        lines.append(f"- 거래당 성과가 가장 좋은 방법은 **{combo_name(best['key'])}**: 거래 {b['n']}건, "
                     f"거래 한 번에 평균 {_f(b['mean_r'], 2)}R(R = 손절 때 잃는 돈 1단위). "
                     f"한 번에 계좌의 0.5%만 걸었을 때 연 {_eq(best['equity'].get('risk'), 'cagr')}, "
                     f"최대 낙폭 {_eq(best['equity'].get('risk'), 'max_drawdown')}.")
    rnd = [c for c in combos.values() if c["verdict"].get("c5_random") is False and c["summary"]["n"]]
    if rnd:
        lines.append(f"- **주의:** {len(rnd)}개 방법은 '아무 날에나 들어가고 같은 방식으로 빠져나오는' 무작위 진입보다 "
                     "거래당 성과가 확실히 낫지 않았다. 즉 이익의 상당 부분이 '진입 시점'보다 "
                     "'손절 + 추세가 꺾일 때까지 버티는 청산 방식'에서 나온다는 뜻일 수 있다. 다만 무작위 진입은 "
                     "명세(§5)대로 '실제 거래가 있던 달' 안에서만 뽑아 돌파 직전 날짜도 들어가므로, 아무 날에서나 뽑을 때보다 "
                     "기준선이 크게 높아진다(전략에 불리한 쪽). 불합격을 '진입에 가치가 없다'로 곧바로 읽으면 안 된다.")
    cmp = res.get("e1_vs_e0") or []
    if cmp:
        better = [c for c in cmp if c["e1_better"]]
        lines.append(f"- 차트프로식 '돌파 가격까지 되돌아오면 사기(E1)'가 '바로 사기(E0)'보다 확실히 나은 경우: "
                     f"{len(better)}/{len(cmp)}쌍. " + ("E1은 채택 후보가 아니다." if not better else
                                                      "나은 쌍만 채택 후보로 본다."))
    lines.append("- ⚠️ 이 전략의 기본형은 이전 시험(G1)에서 비교 기준선으로 이미 결과를 본 적이 있어 과거 데이터 시험은 "
                 "완전한 검증이 아니다. 진짜 검증은 규칙을 고정한 뒤의 모의 운영(G3)이다.")
    lines.append("")
    return lines


def _verdict_table(res: dict) -> list[str]:
    rows = []
    for c in res["combos"]:
        s, v, cs, rb = c["summary"], c["verdict"], c["cost2"], c["random"]
        rows.append([f"`{c['key']}`", _int(s["n"]), _r(s["mean_r"]), _r(s["boot_lo"]), _f(s["pf"]),
                     _r(cs.get("mean_r")), _r(rb.get("threshold")), f"{_int(s['positive_years'])}/7",
                     " ".join(_mark(v[k]) for k, _ in CRIT), f"**{RESULT_KO.get(v['result'], v['result'])}**"])
    lines = ["## 1. 조합별 G1-T 판정 (7개 기준, TREND_SPEC §5 = RULES §8.3)", "",
             "기준 순서: " + " · ".join(f"{i + 1} {name}" for i, (_, name) in enumerate(CRIT)) + ". ○ 충족, × 미충족.",
             ""]
    lines += _table(["조합", "거래", "평균 R", "부트스트랩 하한", "PF", "비용 2배 평균 R", "무작위 기준(95%)",
                     "양수 연도", "기준 1~7", "판정"], rows, right={1, 2, 3, 4, 5, 6, 7})
    lines.append("")
    lines += ["조합 이름: " + "; ".join(f"`{c['key']}` = {combo_name(c['key'])}" for c in res["combos"]), ""]
    return lines


def _detail(res: dict) -> list[str]:
    lines = ["## 2. 조합별 상세", ""]
    rows = []
    for c in res["combos"]:
        s = c["summary"]
        ex, st = s["exit_counts"], s["status_counts"]
        bys = c.get("by_system", {})
        sys_txt = ", ".join(f"N{n}: {_int(b['n'])}건 {_r(b['mean_r'])}" for n, b in bys.items())
        rows.append([f"`{c['key']}`", f"{_int(s['n_long'])}/{_int(s['n_short'])}",
                     f"{_int(ex.get('stop'))}/{_int(ex.get('trend'))}/{_int(ex.get('eod'))}",
                     f"{_int(st.get('expired'))}/{_int(st.get('cancelled'))}", _pct(s["win_rate"]),
                     _r(s["median_r"]), _f(s["max_drawdown_r"], 1), _int(s["max_consec_losses"]),
                     _f(c.get("dsr"), 2), sys_txt])
    lines += _table(["조합", "롱/숏", "손절/추세/끝", "E1 만료/취소", "승률", "중앙 R", "R 낙폭", "최대 연속 손실",
                     "DSR(참고)", "하위 시스템별"], rows, right={4, 5, 6, 7, 8})
    lines.append("")
    years = [str(y) for y in range(2020, 2027)]
    rows = []
    for c in res["combos"]:
        s = c["summary"]
        rows.append([f"`{c['key']}`"] + [f"{_r(s['yearly'].get(y))} ({_int(s['yearly_n'].get(y))})" for y in years])
    lines += ["연도별 평균 R (거래 수, 진입 시각 UTC 연도):", ""]
    lines += _table(["조합"] + years, rows)
    lines += ["", "DSR은 8개 조합의 거래당 샤프 분산으로 시도 수 8을 보정한 참고값(판정 기준 아님).", ""]
    return lines


def _e1_vs_e0(res: dict) -> list[str]:
    cmp = res.get("e1_vs_e0") or []
    lines = ["## 3. 차트프로 보조 판정: E1(눌림 대기) vs E0(돌파 즉시)", "",
             "같은 방향·하위 시스템끼리 비교. 평균 R 차이(E1 − E0)의 부트스트랩 95% 구간(두 표본 각각 복원 추출 10,000회)과 "
             "계좌 곡선(r = 0.5% 위험 기반). **구간 하한 > 0일 때만 E1이 채택 후보**(TREND_SPEC §5).", ""]
    rows = []
    for c in cmp:
        e1, e0 = c["equity"]["e1"].get("risk"), c["equity"]["e0"].get("risk")
        rows.append([c["pair"], f"{_int(c['n1'])}/{_int(c['n0'])}", _r(c["diff"]), f"[{_r(c['lo'])}, {_r(c['hi'])}]",
                     f"{_eq(e1, 'cagr')} / {_eq(e0, 'cagr')}", f"{_eq(e1, 'max_drawdown')} / {_eq(e0, 'max_drawdown')}",
                     "**E1 우위**" if c["e1_better"] else "E1 우위 아님"])
    lines += _table(["비교", "거래 E1/E0", "평균 R 차이", "95% 구간", "연 수익률 E1/E0", "최대 낙폭 E1/E0", "결론"],
                    rows, right={1, 2, 3, 4, 5})
    lines.append("")
    return lines


def _equity(res: dict) -> list[str]:
    lines = ["## 4. 계좌 곡선 (보고용, 판정은 R로)", "",
             "- **위험 기반**: 하위 시스템마다 1회 위험 r = 0.5% (명목 = 자산 × 0.005 ÷ (R 분모 ÷ 진입가), "
             "하위 시스템당 ≤ 0.2배, 합계 ≤ 0.6배).",
             "- **명목 고정**: G1 돈치안 기준선과 같은 '하위 시스템당 명목 0.2배'.",
             "- 두 방식 모두 수량은 진입 직전 일봉 마감 자산으로 정해 청산까지 유지하되, 매일 시가에 거래 하나의 명목이 "
             "0.2 × 자산을 넘으면 넘는 만큼만 줄인다(G1 기준선의 'trim'과 같음, 테이커 + 슬리피지). "
             "자산은 일봉 종가로 평가(보유 중 비용은 청산 때 반영). 연 수익률 = 365일 기준 복리, 최대 낙폭은 일봉 종가 기준"
             "(장중 낙폭은 더 클 수 있음).", ""]
    rows = []
    for c in res["combos"]:
        r, f = c["equity"].get("risk"), c["equity"].get("fixed")
        rows.append([f"`{c['key']}`", c["equity"].get("start_utc", "")[:10], _eq(r, "cagr"), _eq(r, "max_drawdown"),
                     _f(r.get("sharpe") if r else None), _f(r.get("final_equity") if r else None),
                     _eq(f, "cagr"), _eq(f, "max_drawdown"), _f(f.get("sharpe") if f else None),
                     _f(f.get("final_equity") if f else None)])
    lines += _table(["조합", "시작", "위험 기반 연 수익률", "최대 낙폭", "샤프", "최종 자산", "명목 0.2배 연 수익률",
                     "최대 낙폭", "샤프", "최종 자산"], rows, right=set(range(2, 10)))
    rows = []
    for c in res["combos"]:
        r, f = c["equity"].get("risk_hold"), c["equity"].get("fixed_hold")
        rows.append([f"`{c['key']}`", _eq(r, "cagr"), _eq(r, "max_drawdown"), _eq(f, "cagr"), _eq(f, "max_drawdown"),
                     _f(f.get("max_notional_ratio") if f else None)])
    lines += ["", "참고 — 줄이지 않고 **수량을 청산까지 고정**했을 때(추세가 이어지면 명목이 0.2배를 크게 넘는다):", ""]
    lines += _table(["조합", "위험 기반 연 수익률", "최대 낙폭", "명목 0.2배 연 수익률", "최대 낙폭", "최대 명목 합 ÷ 자산(시가·진입 순간)"],
                    rows)
    don = res.get("donchian") or {}
    ref = res.get("donchian_g1_reference") or {}
    lines += ["", f"참고 — G1 돈치안 기준선(baselines.py, 다음 날 시가 체결·보호 손절 없음·청산 27일): "
              f"이번 데이터로 다시 계산 연 {_pct(don.get('cagr'), 1)}, 최대 낙폭 {_pct(don.get('max_drawdown'), 1)} "
              f"(G1 보고 값 연 {_pct(ref.get('cagr'), 1)}, 낙폭 {_pct(ref.get('max_drawdown'), 1)}).", ""]
    return lines


def _random(res: dict) -> list[str]:
    lines = ["## 5. 무작위 기준선 (TREND_SPEC §5)", "",
             "실제 체결 거래마다 같은 달(진입 시각 UTC)·같은 방향·같은 하위 시스템을 유지하고, 그 달의 유효 일봉 하나를 "
             "균등 추출해 그 일봉 마감 + 60초 + 30분 뒤 첫 실행 봉 시가에 시장가(테이커 + 슬리피지) 진입, 같은 보호 손절"
             "(그날 2 × ATR20)과 같은 추세 청산(그 방향 M일 반대 돌파)으로 청산. 거래끼리 겹침은 무시. 반복 평균 R의 분포. "
             "E1 조합은 진입만 메이커(슬리피지 없음)로 바꾼 분포의 95% 분위와 둘 중 **큰 값**을 기준으로 쓴다(보수적).", ""]
    rows = []
    for c in res["combos"]:
        rb, s = c["random"], c["summary"]
        mk = rb.get("maker") or {}
        rows.append([f"`{c['key']}`", _int(rb.get("reps")), _r(s["mean_r"]), _r(rb.get("mean")), _r(rb.get("p05")),
                     _r(rb.get("p50")), _r(rb.get("p95")), _r(mk.get("p95")), _r(rb.get("threshold")),
                     _mark(c["verdict"].get("c5_random"))])
    lines += _table(["조합", "반복", "실제 평균 R", "무작위 평균", "5%", "50%", "95%", "95%(메이커 진입)", "판정 기준",
                     "초과"], rows, right=set(range(1, 9)))
    lines.append("")
    return lines


def _sensitivity(res: dict) -> list[str]:
    sens = res.get("sensitivity") or []
    lines = ["## 6. 민감도 (선택에 쓰지 않음, TREND_SPEC §4)", ""]
    if not sens:
        return lines + ["미실시.", ""]
    base = {c["key"]: c for c in res["combos"]}
    rows = []
    for s in sens:
        b = base.get(s["key"], {}).get("summary", {})
        ss = s["summary"]
        rows.append([f"`{s['key']}`", VARIANT_KO.get(s["variant"], s["variant"]), _int(ss["n"]), _r(b.get("mean_r")),
                     _r(ss["mean_r"]), _r(ss["boot_lo"]), _f(ss["pf"]), f"{_int(ss['positive_years'])}/7",
                     _eq(s["equity"].get("risk"), "cagr"), _eq(s["equity"].get("risk"), "max_drawdown")])
    lines += _table(["조합", "변형", "거래", "기본 평균 R", "변형 평균 R", "부트스트랩 하한", "PF", "양수 연도",
                     "위험 기반 연 수익률", "최대 낙폭"], rows, right=set(range(2, 10)))
    lines.append("")
    return lines


def _ranking(res: dict) -> list[str]:
    s = res["summary"]
    lines = ["## 7. 채택 순위 (TREND_SPEC §5)", "",
             "통과 조합 중 단순한 것 우선(단독 > 앙상블, 롱만 > 롱·숏, E0 > E1), 위험 기반 곡선 최대 낙폭 30% 초과는 후순위, "
             "E1은 E0보다 확실히 나을 때(차이 구간 하한 > 0)만 채택 후보.", ""]
    lines.append(f"- 통과: {', '.join(f'`{k}`' for k in s['pass']) or '없음'}")
    lines.append(f"- 채택 후보 순위: {' > '.join(f'`{k}`' for k in s['ranked']) or '없음'}")
    for k, v in (s.get("notes") or {}).items():
        lines.append(f"  - `{k}`: {v}")
    lines.append(f"- 보류(거래 < 30): {', '.join(f'`{k}`' for k in s['pending']) or '없음'}")
    lines.append(f"- 결론: **{s['decision']}**")
    lines.append("")
    return lines


def _mk_text(res: dict) -> str:
    parts = []
    for c in res["combos"]:
        if c["key"].startswith("E1"):
            mk = c["summary"].get("marketable_limit") or {}
            parts.append(f"`{c['key']}` {_int(mk.get('n'))}건(평균 유리분 {_r(mk.get('mean_edge_r'))}R)")
    return ", ".join(parts) or "해당 없음"


def _limits(res: dict) -> list[str]:
    p = res["params"]
    lines = ["## 8. 한계와 오염 고지", "",
             "- ⚠️ **오염**: 돈치안 앙상블(이 전략의 기본형)은 G1에서 비교 기준선으로 한 번 결과를 봤다(연 14.5%, 최대 낙폭 "
             "26.9%). 명세는 그 뒤에 고정됐으므로 이 과거 시험은 완전한 표본 외 검증이 아니다. 진짜 검증은 G3 모의 운영.",
             "- 데이터는 비트코인 한 종목·약 6.7년. 큰 추세 몇 번이 성과 대부분을 만들 수 있어 연도별·하위 시스템별 표를 같이 봐야 한다.",
             "- 계좌 곡선은 일봉 종가 평가라 장중 낙폭을 과소평가한다. 거래 간 자금 경합·증거금 부족·청산(강제 청산)은 모형에 없다.",
             "- 체결: 실행 봉(2023-10-01 전 5분봉, 이후 1분봉) 시가·지정가 관통 가정. 슬리피지는 고정 0.02%(급변 때 실제는 더 클 수 있음). "
             "E1 지정가가 활성 시각에 이미 지정가 너머(갭)에서 시작해도 지정가·메이커로 체결(RULES §12.1 문자 그대로: 가격은 실제 시가보다 불리, 수수료는 유리 — 유리분이 양수면 엔진이 성과를 부풀린 쪽).",
             f"  이런 E1 체결 수: {_mk_text(res)}.",
             "- 펀딩은 실제 기록(2026-09 이후 0.01% 대체값). 비용 2배는 수수료·슬리피지·지불 펀딩에만 곱했다.",
             "- 가용성 마스크는 적용하지 않았다: 판단 시각이 항상 KST 09:01(방해 금지 밖)이고 하루 진입 요청이 최대 3건이라 걸릴 수 없다.",
             "- 무작위 기준선은 거래끼리 겹침을 무시하고, 그 달 안의 모든 유효 일봉에서 뽑는다(방향·하위 시스템 유지). "
             f"반복 {p.get('random_reps')}회. ⚠️ 선택 효과: 뽑는 달이 '뒤에 돌파가 나온 달'이라 돌파 전 날짜의 진입이 "
             "포함돼 기준선이 무조건 추출(전체 유효 일봉)보다 크게 높다(예: N100 롱 무작위 평균 R — 거래 달 약 6.7, 전체 일봉 약 2.4, "
             "실제 거래 약 1.8; 검토 TS-2). 전략을 부풀리지 않는 방향이지만 c5 판정의 주된 원인이므로 해석에 주의.",
             "- 해석 확정(trend.py 머리말 T-1~T-8): 하위 시스템당 포지션·대기 주문 1개, 손절 뒤 같은 방향 재진입 허용, 청산 신호 날의 "
             "반대 진입 검사, E1 취소 효력 = 청산 신호 판단 시각(마감 + 60초), E0 진입 슬리피지를 R 분모에 포함, "
             "ATR20 = 직전 20개 일봉 TR 평균(당일 제외), 신호는 모든 값이 계산 가능한 날부터.",
             "- PBO·워크포워드·다른 종목 검증은 이번 범위 밖.", ""]
    return lines


def _repro(res: dict) -> list[str]:
    d = res.get("data", {})
    span = d.get("daily_span_utc") or ["", ""]
    commit = (res.get("git_commit") or "없음") + ("+작업 트리 변경" if res.get("git_dirty") else "")
    return ["## 9. 재현 방법", "",
            "```", "python -m backtest.run_g1t            # 공식 실행 (무작위 1,000회, 민감도, TRIALS.md 한 줄)",
            "python -m backtest.report_trend      # 보고서만 다시 쓰기", "```", "",
            f"- 명세 {res.get('spec_version')} · 커밋 {commit} · 코드 해시 {str(res.get('code_sha256'))[:12]} · "
            f"시드 {res['params'].get('seed')} · 실행 {res.get('runtime_sec')}초",
            f"- 일봉 기간 {span[0][:10]} ~ {span[1][:10]} · 데이터 출처 {d.get('source')}",
            "- 결과: `g1t_results.json`, 거래 `trades/<조합>.csv`, 계좌 곡선 `equity/<조합>.csv`.", ""]


def render_markdown(res: dict) -> str:
    head = ["# G1-T 추세추종 백테스트 보고서", "",
            f"> 명세 {res.get('spec_version')} (docs/TREND_SPEC.md) · 생성 {res.get('created_utc')} · "
            f"{'공식 실행' if res['summary'].get('official') else '부분 실행(공식 G1-T 아님)'}", ""]
    parts = (head + _plain_summary(res) + _verdict_table(res) + _detail(res) + _e1_vs_e0(res) + _equity(res)
             + _random(res) + _sensitivity(res) + _ranking(res) + _limits(res) + _repro(res))
    return "\n".join(parts).rstrip() + "\n"


def write_report(results_path: Path = RESULTS_DIR / "g1t_results.json",
                 out_path: Path = RESULTS_DIR / "G1T_REPORT.md") -> Path:
    res = json.loads(Path(results_path).read_text(encoding="utf-8"))
    out_path = Path(out_path)
    out_path.write_text(render_markdown(res), encoding="utf-8")
    return out_path


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rp = Path(argv[0]) if argv else RESULTS_DIR / "g1t_results.json"
    op = Path(argv[1]) if len(argv) > 1 else rp.with_name("G1T_REPORT.md")
    print(write_report(rp, op))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
