"""G1 판정 보고서 — g1_results.json → 사람이 읽는 한국어 마크다운 (DEV_GUIDE §6.15 첫 장 양식 참고).

담당: 통합. 설계: backtest/DESIGN.md §6.13.
실행: `python -m backtest.report [--results backtest/results/g1_results.json] [--out backtest/results/G1_REPORT.md]`

보고서에 반드시 들어갈 것
- 명세 버전·코드 커밋·데이터 해시·기간, F3 이벤트 필터 꺼짐 명시(§10-2), 무작위 반복 수(300으로 줄였으면 명시)
- 조합별 판정표(실행 가능 기준): 거래 수, 평균 R, 부트스트랩 하한, PF, 비용 2배 평균 R, 무작위 95% 분위, 양수 연도 수, DSR, 판정
- 전체 vs 실행 가능, 시간대별(낮·저녁·심야), P1 vs P2 (G3 150건까지 걸리는 주 수 포함)
- 기준선(무작위 분포 위치, 돈치안 CAGR·MDD·샤프), 민감도 표(선택에 쓰지 않음을 명시)
- 결론 한 문장: 통과 후보 목록, 0개면 "개발 중지·사용자 재검토"(§8.3)
- v1.0 범위 밖으로 미실시한 것: PBO, 워크포워드, freqtrade 교차 검증

구성: 맨 앞은 코딩을 모르는 사람도 읽을 수 있는 요약, 그다음 표와 세부. 입력은 JSON(값이 None·"inf" 문자열·
문자열 연도 키로 돌아온 것)을 그대로 받는다. 같은 JSON이면 같은 보고서가 나온다(결정적).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from backtest import config as C

# ---------------------------------------------------------------------------
# 사람이 읽는 이름
# ---------------------------------------------------------------------------
REASON_KO = {
    "PASSED": "통과(실행한 계획)",
    "WARMUP": "지표 준비 전(워밍업)",
    "SC_CLOSE_VS_WAIST": "시나리오 조건: 종가와 허리 위치",
    "SC_SLOPE60": "시나리오 조건: 기울기 60 하락(L1a)",
    "SC_UNHEALTHY": "시나리오 조건: 건강하지 않은 조정(거래량)",
    "SC_NO_TARGET": "시나리오 조건: 목표(아래 스윙 저점) 없음(S3)",
    "SC_BAD_GEOMETRY": "가격 순서 이상(손절·진입·목표)",
    "F1": "F1 방향 필터가 허용 안 함",
    "F2": "F2 저거래량·저변동성",
    "F3": "F3 이벤트(FOMC·CPI) 전후",
    "F4": "F4 이평 확산(과열)",
    "F5": "F5 급등 쿨다운",
    "F6": "F6 박스(트랩 2회 이상)",
    "F7": "F7 살아 있는 반대 마디",
    "RISK_STOP_BAND": "손절 폭이 0.4~2%·1~3 ATR 밖",
    "RISK_RR": "순손익비 1.5 미만",
    "F8": "F8 같은 마디에서 이미 2번 손절",
    "F9": "F9 포지션·대기 주문 보유 중",
    "MASK_DND": "방해 금지 시간(KST 00:30~07:30)",
    "MASK_DAILY_CAP": "하루 승인 요청 6건 초과",
}
VERDICT_KO = {"pass": "통과 후보", "fail": "불합격", "pending": "보류(30건 미만)"}
SCENARIO_KO = {"L1a": "허리 대기 매수", "L1b": "허리 확인 매수", "S2": "급증 음봉 이탈 매도", "S3": "지지 이탈 매도"}
FILTER_KO = {"DA": "허리 기준 방향", "DB": "이평 기준 방향"}
SETTING_KO = {"P1": "1시간봉 신호(4시간봉 방향)", "P2": "4시간봉 신호(일봉 방향)"}
SESSION_KO = {"day": "낮 07:30~18:00", "evening": "저녁 18:00~00:30", "night": "심야 00:30~07:30"}
VARIANT_KO = {"lat5": "지연 5분", "lat15": "지연 15분", "mid": "허리 (고+저)÷2", "vr3": "기준봉 VR 3",
              "cost2": "비용 2배", "ev": "F3 이벤트 켬", "rearm": "L1b 재준비(명세 밖 진단)"}
CONDITIONS = (  # (verdict 키, 표 머리글)
    ("c1_mean_r", "① 평균 R ≥ 0.15"),
    ("c2_boot_lo", "② CI 하한 > 0"),
    ("c3_pf", "③ PF ≥ 1.2"),
    ("c4_cost2", "④ 비용 2배 > 0"),
    ("c5_random", "⑤ 무작위 95% 초과"),
    ("c6_years", "⑥ 양수 연도 ≥ 4"),
    ("c7_enough_trades", "⑦ 거래 ≥ 30"),
)
# 폐기 사유 표의 열 묶음 (대표 사유 기준, 합 = 후보 수)
REASON_GROUPS = (
    ("워밍업", ("WARMUP",)),
    ("시나리오", ("SC_CLOSE_VS_WAIST", "SC_SLOPE60", "SC_UNHEALTHY", "SC_NO_TARGET", "SC_BAD_GEOMETRY")),
    ("F1", ("F1",)), ("F2", ("F2",)), ("F3", ("F3",)), ("F4", ("F4",)), ("F5", ("F5",)), ("F6", ("F6",)),
    ("F7", ("F7",)), ("손절 폭", ("RISK_STOP_BAND",)), ("손익비", ("RISK_RR",)), ("F8", ("F8",)), ("F9", ("F9",)),
    ("방해 금지", ("MASK_DND",)), ("6건 초과", ("MASK_DAILY_CAP",)),
)
ANY_REASONS = ("F1", "F2", "F4", "F5", "F6", "F7", "RISK_STOP_BAND", "RISK_RR", "F8", "F9", "MASK_DND")


# ---------------------------------------------------------------------------
# 숫자 모양
# ---------------------------------------------------------------------------


def _num(x) -> float | None:
    """JSON 값 → float. None·NaN·해석 불가 → None, 'inf'/'-inf' → ±inf."""
    if x is None or isinstance(x, bool):
        return None if x is None else float(x)
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("inf", "+inf", "infinity"):
            return math.inf
        if s in ("-inf", "-infinity"):
            return -math.inf
        try:
            v = float(s)
        except ValueError:
            return None
    else:
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
    return None if math.isnan(v) else v


def _f(x, nd: int = 2, signed: bool = False) -> str:
    """소수 표시. 값 없음 → '–', ±inf → '∞'/'-∞'."""
    v = _num(x)
    if v is None:
        return "–"
    if math.isinf(v):
        return "∞" if v > 0 else "-∞"
    return f"{v:+.{nd}f}" if signed else f"{v:.{nd}f}"


def _r(x) -> str:
    """R 값 (부호 포함, 소수 셋째 자리)."""
    return _f(x, 3, signed=True)


def _pct(x, nd: int = 0) -> str:
    v = _num(x)
    return "–" if v is None or math.isinf(v) else f"{100 * v:.{nd}f}%"


def _int(x) -> str:
    v = _num(x)
    return "–" if v is None or math.isinf(v) else f"{int(round(v)):,}"


def _weeks(x) -> str:
    """주 수: 값 없음 → '–', inf → '∞', 나머지는 천 단위 쉼표 정수."""
    v = _num(x)
    if v is None:
        return "–"
    return "∞" if math.isinf(v) else f"{v:,.0f}"


def _date(iso) -> str:
    return iso[:10] if isinstance(iso, str) and iso else "–"


def _end_date(iso) -> str:
    """끝 시각(미포함, 예: 마지막 봉 마감 2026-09-29T00:00:00Z) → 마지막 날(2026-09-28)."""
    if not isinstance(iso, str) or not iso:
        return "–"
    ns = C.ts_ns(iso) - 1                                     # 끝 시각 바로 전 순간이 속한 날
    return C.ns_to_iso(ns)[:10]


def _table(headers: list[str], rows: list[list], right: set[int] | None = None) -> list[str]:
    """마크다운 표. right = 오른쪽 정렬할 열 번호(숫자 열)."""
    right = set(range(1, len(headers))) if right is None else right
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---:" if i in right else "---" for i in range(len(headers))) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in row) + " |")
    return lines


def _mark(v) -> str:
    return "○" if v is True else "×" if v is False else "–"


def _combo_name(key: str) -> str:
    """'L1b-DA-P1' → 'L1b 허리 확인 매수 · 허리 기준 방향 · 1시간봉 신호(4시간봉 방향)'."""
    try:
        s, d, p = key.split("-")
    except ValueError:
        return key
    return f"{s} {SCENARIO_KO.get(s, s)} · {FILTER_KO.get(d, d)} · {SETTING_KO.get(p, p)}"


# ---------------------------------------------------------------------------
# 결과에서 뽑는 값
# ---------------------------------------------------------------------------


def _n(summary: dict | None) -> int:
    v = _num((summary or {}).get("n"))
    return int(v) if v is not None else 0


def _beats_both(combo: dict) -> bool:
    """실행 가능 평균 R이 무작위 95% 분위(판정, 테이커 진입)와 같은 진입 수수료 분포의 95% 분위(참고) 둘 다보다 높은가."""
    actual = _num(combo["exec"].get("mean_r"))
    rnd = combo.get("random") or {}
    p95, p95_same = _num(rnd.get("p95")), _num((rnd.get("same_fee") or {}).get("p95"))
    return actual is not None and p95 is not None and p95_same is not None and actual > max(p95, p95_same)


def _random_position(combo: dict) -> float | None:
    """무작위 반복 평균 R 중 실제 평균 R보다 낮은 비율(0~1). 값이 없으면 None."""
    actual = _num(combo["exec"].get("mean_r"))
    means = [m for m in (_num(x) for x in (combo.get("random") or {}).get("means") or []) if m is not None]
    if actual is None or not means:
        return None
    return sum(1 for m in means if m < actual) / len(means)


def _ranked(res: dict) -> tuple[list[tuple[str, float, int]], bool]:
    """실행 가능 평균 R 순위(높은 순). 거래 30건 이상 조합이 있으면 그것만, 없으면 거래가 있는 조합 전부(참고)."""
    rows = [(c["key"], _num(c["exec"].get("mean_r")), _n(c["exec"])) for c in res["combos"]]
    rows = [r for r in rows if r[1] is not None and r[2] > 0]
    judged = [r for r in rows if r[2] >= C.G1_MIN_TRADES]
    pool = judged if judged else rows
    return sorted(pool, key=lambda r: (-r[1], r[0])), bool(judged)


def _top_reason(summary: dict, *, skip=("WARMUP",)) -> tuple[str, int] | None:
    """사유가 붙은 후보가 가장 많은 사유(any 기준, 워밍업 제외)."""
    any_ = summary.get("discard_any_reason") or {}
    best = max(((k, int(v)) for k, v in any_.items() if k not in skip and _num(v)), key=lambda kv: kv[1],
               default=None)
    return best if best and best[1] > 0 else None


def _marketable_text(res: dict) -> str:
    """즉시 체결될 지정가를 §12.1대로 지정가·메이커로 체결한 건수 (실행 가능 모드 합계, 검토 LA-2·F4)."""
    rows = [(c["exec"].get("marketable_limit") or {}) for c in res["combos"]]
    head = ("- **즉시 체결될 지정가**: 활성 시각에 이미 체결 가능한 지정가(롱: 활성 뒤 첫 실행 봉 시가 < 지정가)도 명세 §12.1대로 "
            "지정가에 메이커 수수료로 체결했다. 실제로는 그 시가 근처에서 테이커로 체결된다.")
    if not any(r for r in rows):
        return head
    n = sum(int(_num(r.get("n")) or 0) for r in rows)
    fav = sum(int(_num(r.get("n_engine_favorable")) or 0) for r in rows)
    fav_r = sum(_num(r.get("favorable_r_sum")) or 0.0 for r in rows)
    means = [(_num(r.get("mean_edge_r")), int(_num(r.get("n")) or 0)) for r in rows]
    tot = sum(k for m, k in means if m is not None)
    avg = sum(m * k for m, k in means if m is not None) / tot if tot else None
    if n == 0:
        return head + " 이번 실행 가능 거래에는 이런 체결이 없었다."
    return (head + f" 실행 가능 거래 중 이런 체결은 {n}건이고, 즉시 테이커 체결과 비교한 엔진의 진입 원가 이득은 평균 "
            f"{_r(avg)}R(음수 = 엔진이 보수적)이다. 엔진이 유리한 경우(가격 차이 < 수수료 차이 0.03%)는 {fav}건, "
            f"합 {_r(fav_r)}R이다(진입 원가만 비교, 결과 JSON의 marketable_limit).")


def _f3_text(res: dict) -> str:
    """F3 이벤트 필터 상태를 사람이 읽는 문장으로 (§10-2)."""
    if (res.get("data") or {}).get("events_file"):
        return "G1 기본값은 꺼짐(§10-2). data/events.csv가 있어 민감도 'F3 이벤트 켬'으로만 따로 확인했다"
    return "FOMC·CPI 날짜표(data/events.csv)가 없어 끈 채로 돌렸다(§10-2). 발표 전후에도 신호를 냈다"


def _data_name(d: dict) -> str:
    return ("바이낸스 USDⓈ-M BTCUSDT 무기한 선물" if d.get("source") == "binance"
            else "합성 시장(테스트용, 실데이터 아님)")


# ---------------------------------------------------------------------------
# 절
# ---------------------------------------------------------------------------


def _header(res: dict) -> list[str]:
    d, p, s = res.get("data") or {}, res.get("params") or {}, res.get("summary") or {}
    commit = res.get("git_commit") or "없음"
    if res.get("git_dirty"):
        commit += " (커밋되지 않은 변경 포함 — 코드 해시로 식별)"
    sha = d.get("sha256") or {}
    data_hash = "합성 데이터(테스트용)" if d.get("source") != "binance" else (
        f"파일 {len(sha)}개, 해시는 §8 참고" if sha else "없음")
    span = d.get("span_utc") or [None, None]
    period = p.get("period_utc")
    period_txt = "전체" if not period else f"{_date(period[0]) if period[0] else '처음'} ~ " \
                                         f"{_end_date(period[1]) if period[1] else '끝'} (승인 시각 기준)"
    reps = p.get("random_reps")
    reps_txt = "미실시" if not p.get("random_enabled") else f"{_int(reps)}회"
    if p.get("random_reps_reduced"):
        reps_txt += f" (기본 {C.RANDOM_REPS:,}회에서 줄임)"
    title = "G1 판정 보고서" if s.get("official") else "G1 부분 실행 보고서 (공식 판정 아님)"
    return [
        f"# {title} — {_date(res.get('created_utc'))}",
        "",
        f"- 명세: RULES_SPEC {res.get('spec_version', '?')} (고정) · 코드 커밋: {commit} · "
        f"코드 해시: `{(res.get('code_sha256') or '')[:12]}`",
        f"- 데이터: {_data_name(d)} {_date(span[0])} ~ {_end_date(span[1])} (UTC) · 데이터 해시: {data_hash}",
        f"- 평가 기간: {period_txt} · 실행 봉: {_date(d.get('exec_switch_utc'))} 전 5분봉 / 이후 1분봉",
        f"- 무작위 기준선: {reps_txt} · 부트스트랩 {_int(p.get('bootstrap_n'))}회 · 지연 L {p.get('latency_min')}분 "
        f"(민감도 {', '.join(str(x) for x in p.get('latency_sensitivity_min') or [])}분)",
        f"- **F3 이벤트 필터: 꺼짐** — {_f3_text(res)}",
        f"- 실행 시간: {_f(res.get('runtime_sec'), 1)}초 · 결과 파일: `g1_results.json`",
        "",
    ]


def _pass_dsr(res: dict, passed: list[str]) -> tuple[str, list[str]]:
    """통과 후보 목록 → ('L1b-DA-P1(DSR 0.21), …', DSR이 0.95 미만이거나 없는 후보들) (§8.3 DSR 함께 보고, 검토 F5)."""
    dsr = {c["key"]: _num(c.get("dsr")) for c in res["combos"]}
    text = ", ".join(f"{k}(DSR {_f(dsr.get(k))})" for k in passed)
    weak = [k for k in passed if dsr.get(k) is None or dsr[k] < C.DSR_REPORT_STRONG]
    return text, weak


def _weak_dsr_note(weak: list[str]) -> str:
    if not weak:
        return ""
    return (f" 단, {', '.join(weak)}는 DSR이 {C.DSR_REPORT_STRONG:.2f} 미만(또는 계산 불가)이라 16개 조합을 시험한 것을 "
            f"보정하면 근거가 약하다(우연 통과일 수 있음).")


def _conclusion(res: dict) -> str:
    s = res["summary"]
    k = len(res["combos"])
    passed = s.get("pass_candidates") or []
    pass_text, weak = _pass_dsr(res, passed)
    if not s.get("official"):
        why = ", ".join(s.get("partial_reasons") or [])
        tail = f"(통과 후보: {pass_text})" if passed else ""
        return (f"**결론(참고용): 부분 실행({why})이라 공식 G1 판정이 아니다.** 이 실행의 {k}개 조합 중 "
                f"통과 후보 {s['n_pass']}개{tail}, 불합격 {s['n_fail']}개, 판정 보류 {s['n_pending']}개였다."
                + _weak_dsr_note(weak))
    if passed:
        return (f"**결론: 16개 조합 중 {len(passed)}개({pass_text})가 G1 기준을 모두 넘어 '통과 후보'다. "
                f"다음 단계로 갈지는 사용자가 결정한다(§8.3).**" + _weak_dsr_note(weak))
    return (f"**결론: 16개 조합 중 G1 기준을 모두 넘은 조합이 없다(통과 후보 0개 — 불합격 {s['n_fail']}개, "
            f"판정 보류 {s['n_pending']}개). 규칙(§8.3)에 따라 개발을 멈추고 사용자와 재검토한다.**")


def _plain_summary(res: dict) -> list[str]:
    s, d, p = res["summary"], res.get("data") or {}, res.get("params") or {}
    combos = res["combos"]
    k = len(combos)
    ranked, judged = _ranked(res)
    with_trades = [c for c in combos if _n(c["exec"]) > 0]
    enough = [c for c in combos if _n(c["exec"]) >= C.G1_MIN_TRADES]
    beat = [c["key"] for c in with_trades if (c.get("verdict") or {}).get("c5_random")]
    span = d.get("span_utc") or [None, None]
    out = ["## 한눈에 보기 (코딩을 몰라도 읽을 수 있는 요약)", "",
           f"- **무엇을 시험했나**: 차트프로식 매매 규칙 4가지(L1a·L1b·S2·S3)를 방향 판단 2가지(DA 허리 기준·DB 이평 기준)와 "
           f"봉 설정 2가지(P1 1시간봉·P2 4시간봉)로 조합한 {k}가지를 {_data_name(d)} 과거 데이터({_date(span[0])} ~ "
           f"{_end_date(span[1])})로 돌렸다. 사람이 승인할 수 없는 시간(한국 시각 00:30~07:30)의 신호와 하루 7번째 이후 신호를 뺀 "
           f"**'실행 가능' 결과로 판정**한다.",
           "- **합격 기준(G1, 미리 정한 7가지)**: 수수료·슬리피지·펀딩을 넣고도 거래 1건당 평균 **+0.15R 이상**, "
           "통계적으로 0보다 확실히 큼(부트스트랩 95% 하한 > 0), PF(이익 합 ÷ 손실 합) 1.2 이상, 비용을 2배로 해도 플러스, "
           "무작위로 들어간 것의 95% 분위보다 높음, 7개 연도 중 4개 이상 플러스. 거래가 30건 미만이면 판정 보류.",
           f"- **결과**: {k}개 조합 중 **통과 후보 {s['n_pass']}개**, 불합격 {s['n_fail']}개, "
           f"판정 보류 {s['n_pending']}개. 실행 가능 거래가 30건 이상인 조합: {len(enough)}개."]
    if ranked:
        best, worst = ranked[0], ranked[-1]
        note = "" if judged else " (모두 거래 30건 미만이라 참고만)"
        out.append(f"- **가장 좋은 조합**: {best[0]} — 실행 가능 평균 {_r(best[1])}R, 거래 {best[2]}건{note}. "
                   f"**가장 나쁜 조합**: {worst[0]} — 평균 {_r(worst[1])}R, 거래 {worst[2]}건.")
    else:
        out.append("- **가장 좋은/나쁜 조합**: 실행 가능 거래가 난 조합이 없어 비교할 수 없다.")
    if p.get("random_enabled"):
        both = [c["key"] for c in with_trades if _beats_both(c)]
        out.append(f"- **무작위 진입과 비교**: 거래가 난 {len(with_trades)}개 조합 중 {len(beat)}개가 무작위 진입(같은 달·방향·"
                   f"손절/목표 거리, 진입 시각만 무작위) 평균 R의 95% 분위를 넘었다"
                   + (f" ({', '.join(beat)})." if beat else ".")
                   + f" 진입 수수료를 조합과 같게 둔 무작위 분포(참고, §4.1)의 95% 분위까지 넘은 조합은 {len(both)}개"
                   + (f"({', '.join(both)})." if both else "."))
    else:
        out.append("- **무작위 진입과 비교**: 이번 실행에서는 무작위 기준선을 돌리지 않았다(조건 ⑤는 미달로 처리).")
    zero = [c["key"] for c in combos if _n(c["exec"]) == 0]
    lim = ["표본이 적다" + (f"(거래 0건 조합 {len(zero)}개)" if zero else ""),
           "FOMC·CPI 발표 전후를 쉬는 F3 필터가 꺼져 있다(날짜표 없음)",
           f"{_date(d.get('exec_switch_utc'))} 전은 1분봉이 없어 5분봉으로 체결을 판정했다(손절 우선의 보수적 가정)"]
    if d.get("funding_n_synthetic"):
        lim.append(f"{_date(d.get('funding_last_real_utc'))} 뒤 펀딩비는 실제 기록이 없어 0.01%로 가정했다")
    lim.append("과거 결과는 미래 수익을 보장하지 않는다")
    out.append("- **읽을 때 주의할 점(한계)**: " + "; ".join(lim) + ". 자세한 내용은 §7.")
    out.append("- **R이란**: 손절까지의 위험(손실 폭 + 비용)을 1로 놓은 손익 단위. 평균 +0.15R은 1만 원의 위험을 걸 때마다 "
               "평균 1,500원을 벌었다는 뜻이고, -1R은 손절 한 번의 손실이다.")
    out.append("")
    return out


def _verdict_table(res: dict) -> list[str]:
    rows, cond_rows = [], []
    for c in res["combos"]:
        e, v = c["exec"], c.get("verdict") or {}
        rnd = c.get("random") or {}
        rows.append([c["key"], f"{_int(c['all'].get('n'))} / {_int(e.get('n'))}", _r(e.get("mean_r")),
                     _r(e.get("boot_lo")), _f(e.get("pf")), _r((c.get("exec_cost2") or {}).get("mean_r")),
                     _r(rnd.get("p95")), f"{_int(e.get('positive_years'))}/{len(C.G1_YEARS)}", _f(c.get("dsr")),
                     f"**{VERDICT_KO.get(v.get('result'), v.get('result', '–'))}**"])
        cond_rows.append([c["key"]] + [_mark(v.get(key)) for key, _ in CONDITIONS]
                         + [_f(e.get("perm_p"), 3), VERDICT_KO.get(v.get("result"), "–")])
    out = ["## 1. 조합별 판정표 (실행 가능 신호 기준, §8.3)", "",
           "조합 이름 = 시나리오-방향 필터-봉 설정. 예: `L1b-DA-P1` = L1b 허리 확인 매수 · DA 허리 기준 방향 · "
           "P1 1시간봉 신호. 모든 R은 수수료·슬리피지·펀딩을 뺀 값이다.", ""]
    out += _table(["조합", "거래 수 (전체 / 실행 가능)", "평균 R", "95% CI 하한", "PF", "비용 2배 평균 R",
                   "무작위 95% 분위", "양수 연도", "DSR", "G1 판정"], rows, right=set(range(1, 9)))
    out += ["", "조건별 충족 여부 (○ 충족, × 미달). 판정 보류는 ⑦ 미달(거래 30건 미만)이라 통계로 판단할 수 없다는 뜻이며, "
            "이때는 부호 뒤집기 순열 검정 p값(작을수록 평균 R > 0의 근거가 강함)을 참고로 적는다.", ""]
    out += _table(["조합"] + [h for _, h in CONDITIONS] + ["순열 p(참고)", "판정"], cond_rows,
                  right={len(CONDITIONS) + 1})
    out.append("")
    return out


def _modes_sessions(res: dict) -> list[str]:
    combos = res["combos"]
    out = ["## 2. 전체 신호 vs 실행 가능 신호 · 시간대별 · P1 vs P2", "",
           "**전체**는 사람이 언제나 승인한다고 본 결과, **실행 가능**은 방해 금지 시간(KST 00:30~07:30)과 하루 6건 초과 "
           "요청을 뺀 결과다(§12.3). 두 결과는 따로 시뮬레이션했다(한 신호를 빼면 뒤의 신호가 들어갈 수 있다).", ""]
    rows = []
    for c in combos:
        a, e = c["all"], c["exec"]
        first = e.get("discard_first_reason") or {}
        rows.append([c["key"], _int(a.get("n")), _r(a.get("mean_r")), _int(e.get("n")), _r(e.get("mean_r")),
                     _int(first.get("MASK_DND")), _int(first.get("MASK_DAILY_CAP"))])
    out += _table(["조합", "전체 거래", "전체 평균 R", "실행 가능 거래", "실행 가능 평균 R", "방해 금지로 빠진 신호",
                   "하루 6건 초과로 빠진 신호"], rows)
    out += ["", "**시간대별 (전체 모드, 승인 시각 KST 기준)** — 심야는 실행 가능 모드에서 빠지는 시간이다. 거래가 난 조합만.", ""]
    rows = []
    for c in combos:
        bs = c["all"].get("by_session") or {}
        if _n(c["all"]) == 0:
            continue
        rows.append([c["key"]] + [f"{_int((bs.get(k) or {}).get('n'))}건 / {_r((bs.get(k) or {}).get('mean_r'))}"
                                  for k in SESSION_KO])
    out += _table(["조합"] + [f"{v} (거래 / 평균 R)" for v in SESSION_KO.values()], rows) if rows else ["(거래 없음)"]
    out += ["", "**P1(1시간봉) vs P2(4시간봉)** — 실행 가능 기준. 주당 통과 신호와 'G3 150건까지 걸리는 주 수'는 실제 운영에서 "
            "검증 표본 150건을 모으는 데 걸리는 기간 추정이다(PLAN D1).", ""]
    by_key = {c["key"]: c for c in combos}
    rows = []
    for s in C.SCENARIOS:
        for dfl in C.DIRECTION_FILTERS:
            cells = [f"{s}-{dfl}"]
            present = False
            for p in C.SETTING_NAMES:
                c = by_key.get(f"{s}-{dfl}-{p}")
                if c is None:
                    cells += ["–"] * 4
                    continue
                present = True
                e = c["exec"]
                cells += [_int(e.get("n")), _r(e.get("mean_r")), _f(e.get("passed_per_week"), 2),
                          _weeks(e.get("g3_weeks_to_150"))]
            if present:
                rows.append(cells)
    out += _table(["시나리오-방향", "P1 거래", "P1 평균 R", "P1 주당 통과 신호", "P1 150건까지(주)",
                   "P2 거래", "P2 평균 R", "P2 주당 통과 신호", "P2 150건까지(주)"], rows)
    out.append("")
    return out


def _reasons(res: dict) -> list[str]:
    combos = res["combos"]
    out = ["## 3. 신호 폐기 사유 분포 (실행 가능 모드)", "",
           "후보 신호가 어디서 걸러졌는지다. 아래 표는 **대표 사유**(검사 순서상 처음 걸린 것) 기준이라 한 줄의 합이 후보 수와 같다. "
           "사유 뜻은 표 아래에 있다. 전체 표(두 모드, 대표·포함 기준)는 `signals_summary.csv`.", ""]
    rows = []
    for c in combos:
        e = c["exec"]
        first = e.get("discard_first_reason") or {}
        rows.append([c["key"], _int(e.get("n_candidates")), _int(e.get("n_passed"))]
                    + [_int(sum(int(_num(first.get(r)) or 0) for r in rs)) for _, rs in REASON_GROUPS])
    out += _table(["조합", "후보", "통과"] + [g for g, _ in REASON_GROUPS], rows)
    out += ["", "**사유가 붙은 후보 비율** (한 후보에 여러 사유가 붙을 수 있어 합이 100%를 넘는다. 워밍업 후보 포함한 분모).", ""]
    rows = []
    for c in combos:
        e = c["exec"]
        n = _num(e.get("n_candidates")) or 0
        any_ = e.get("discard_any_reason") or {}
        rows.append([c["key"]] + [_pct((_num(any_.get(r)) or 0) / n) if n else "–" for r in ANY_REASONS])
    out += _table(["조합"] + list(ANY_REASONS), rows)
    out += ["", "사유 코드 뜻: " + "; ".join(f"`{k}` {v}" for k, v in REASON_KO.items() if k != "PASSED") + ".", ""]
    blocked = []
    for c in combos:
        if _n(c["exec"]) == 0 and _num(c["exec"].get("n_candidates")):
            top = _top_reason(c["exec"])
            if top:
                n = _num(c["exec"].get("n_candidates")) or 1
                blocked.append(f"{c['key']}({REASON_KO.get(top[0], top[0])} {_pct(top[1] / n)})")
    if blocked:
        out += ["거래가 0건인 조합에서 가장 많이 걸린 사유: " + ", ".join(blocked) + ".", ""]
    return out


def _baselines(res: dict) -> list[str]:
    p = res.get("params") or {}
    out = ["## 4. 기준선", "", "### 4.1 무작위 진입 (§8.4, §12.4)", ""]
    if not p.get("random_enabled"):
        out += ["이번 실행에서는 무작위 기준선을 돌리지 않았다. G1 조건 ⑤는 미달로 처리했다.", ""]
    else:
        reduced = f" (기본 {C.RANDOM_REPS:,}회에서 줄임)" if p.get("random_reps_reduced") else ""
        out += [f"조합마다 실행 가능 거래를 기준으로, 같은 달·같은 방향·같은 손절/목표 거리(%)를 두고 진입 시각만 그 달의 신호 봉 "
                f"마감 중에서 무작위로 뽑아 시장가(테이커)로 들어가 같은 청산 규칙으로 처리했다. {_int(p.get('random_reps'))}회 "
                f"반복{reduced}. '실제 위치'는 무작위 반복 평균 R 중 실제보다 낮았던 비율이다(95% 넘으면 조건 ⑤ 충족).",
                "",
                "판정(조건 ⑤)은 명세 §12.4대로 시장가(테이커 0.05%) 진입 분포의 95% 분위로 한다. 지정가 조합(L1a·S2·S3, 메이커 "
                "0.02%)과 비교하면 무작위 쪽에만 진입 비용 0.03%가 더 붙고 R 분모도 커져 이긴 거래·시간 청산의 R이 낮아진다"
                "(손절 거래는 둘 다 −1R; 이긴 거래당 약 0.05~0.15R, 손절 폭이 좁을수록 큼). 그래서 같은 추출·같은 청산에서 진입 "
                "수수료만 조합과 같게 둔 분포의 95% 분위를 **참고로** 함께 싣는다(판정에는 쓰지 않음, L1b는 둘 다 테이커라 같다). "
                "또 추출 시각에는 방해 금지 시간(KST 00:30~07:30)의 신호 봉 마감도 들어간다(§12.4 문자 그대로). 실행 가능 거래는 이 "
                "시간에 승인될 수 없어 시간대 분포가 다르며, 검토 측정으로는 이 때문에 기준선 평균이 약 +0.006R 높아진다(조건 ⑤를 "
                "넘기 약간 어려운 쪽, 잡음 수준).", ""]
        rows = []
        for c in res["combos"]:
            e, rnd = c["exec"], c.get("random") or {}
            if _n(e) == 0:
                continue
            same = rnd.get("same_fee") or {}
            rows.append([c["key"], f"{_r(e.get('mean_r'))} ({_int(e.get('n'))}건)", _r(rnd.get("mean")),
                         _r(rnd.get("p05")), _r(rnd.get("p50")), _r(rnd.get("p95")), _pct(_random_position(c)),
                         _int(rnd.get("n_not_filled")), _r(same.get("p95")), _mark(_beats_both(c))])
        out += _table(["조합", "실제 평균 R (거래)", "무작위 평균", "5% 분위", "50% 분위", "95% 분위(판정)", "실제 위치",
                       "무작위 미체결", "같은 진입 수수료 95% 분위(참고)", "두 분위 모두 초과"], rows) if rows else \
            ["(실행 가능 거래가 난 조합이 없어 무작위 기준선이 없다)"]
        out.append("")
    out += ["### 4.2 일봉 돈치안 채널 앙상블 (추세추종, 비교용 보고만)", ""]
    dn = res.get("donchian")
    if not dn:
        out += ["미실시.", ""]
        return out
    out += [f"20·55·100일 종가 돌파로 진입하고 절반 기간 반대 돌파로 청산하는 세 전략을 같은 비중(전략마다 명목 0.2배, 합 0.6배)으로 "
            f"돌렸다. 테이커 수수료·펀딩 포함. 기간 {_date(dn.get('start_utc'))} ~ {_end_date(dn.get('end_utc'))}. "
            f"G1 판정에는 쓰지 않는다(단위가 자산 곡선이라 거래당 R과 직접 비교하기 어렵다).", ""]
    out += _table(["항목", "값"], [
        ["연 수익률(CAGR)", _pct(dn.get("cagr"), 1)],
        ["최대 낙폭(MDD)", _pct(dn.get("max_drawdown"), 1)],
        ["샤프(일간, 연율화)", _f(dn.get("sharpe"))],
        ["진입 횟수", _int(dn.get("n_trades"))],
        ["최종 자산 (시작 1.0)", _f(dn.get("final_equity"), 3)],
        ["누적 수수료 / 누적 펀딩 (자산 1.0 기준)", f"{_f(dn.get('total_fees'), 3)} / {_f(dn.get('total_funding'), 3)}"],
        ["명목 상한 방식", f"{dn.get('cap_mode', '–')} (최대 명목 ÷ 자산 {_f(dn.get('max_notional_ratio'), 3)})"],
    ], right={1})
    per = dn.get("per_period") or {}
    if per:
        out += ["", "기간 하나만 따로(같은 명목 상한 0.6배):", ""]
        out += _table(["기간(일)", "진입 횟수", "CAGR", "MDD", "샤프", "최종 자산"],
                      [[k, _int(v.get("n_trades")), _pct(v.get("cagr"), 1), _pct(v.get("max_drawdown"), 1),
                        _f(v.get("sharpe")), _f(v.get("final_equity"), 3)] for k, v in per.items()])
    if dn.get("cap_mode") == "trim":
        out += ["", "명목 상한: 명세 §12.4 '전체 명목 ≤ 0.6배'를 지키려고, 전략 하나의 명목이 그날 시가에 자산 × 0.2를 넘으면 "
                "넘는 만큼만 줄였다(늘리지는 않음)."]
    out.append("")
    return out


def _sensitivity(res: dict) -> list[str]:
    sens = res.get("sensitivity") or []
    out = ["## 5. 민감도 확인 (조합 선택·판정에 쓰지 않음, §9)", ""]
    if not sens:
        return out + ["이번 실행에서는 민감도를 돌리지 않았다.", ""]
    tags = []
    for s in sens:
        if s["variant"] not in tags:
            tags.append(s["variant"])
    cell = {(s["key"], s["variant"]): s["exec"] for s in sens}
    out += ["숫자는 실행 가능 모드의 '거래 수 / 평균 R'이다. 기본값에서 하나만 바꿔 결과가 얼마나 흔들리는지 본다. "
            "**결과는 보고만 하고 조합 선택에 쓰지 않는다.** 무작위 기준선은 돌리지 않았다."]
    if "rearm" in tags:
        out.append("'L1b 재준비(명세 밖 진단)'는 명세 §9 민감도 목록에 없는 진단이다: 검토 전 구현의 해석(옛 I-22: 한 마디에서 준비 에피소드가 "
                   "끝나면 다시 준비)으로 L1b를 돌린 결과이며, 기본은 명세 §7.2 문장대로 마디당 준비 1회다(§7 한계 참고).")
    out.append("")
    rows = []
    for c in res["combos"]:
        row = [c["key"], f"{_int(c['exec'].get('n'))} / {_r(c['exec'].get('mean_r'))}"]
        for t in tags:
            e = cell.get((c["key"], t))
            row.append("–" if e is None else f"{_int(e.get('n'))} / {_r(e.get('mean_r'))}")
        rows.append(row)
    out += _table(["조합", "기본"] + [VARIANT_KO.get(t, t) for t in tags], rows)
    out.append("")
    return out


def _overfit(res: dict) -> list[str]:
    s = res["summary"]
    var = res.get("dsr_sr_trials_var")
    note = "" if len(res["combos"]) == C.DSR_N_TRIALS else \
        f" 이번 실행은 {len(res['combos'])}개 조합만 돌려 분산 추정이 부정확하다."
    out = ["## 6. 과최적화 점검", "",
           f"- **DSR(다중 시험 보정 샤프, Bailey·López de Prado 2014)**: 16개 조합을 시험해 가장 좋은 것을 고를 때 생기는 운의 몫을 "
           f"빼고, 거래당 샤프가 0보다 클 확률(0~1)이다. 1에 가까울수록 근거가 강하다. 시도 수 N = {C.DSR_N_TRIALS}, 시도 간 "
           f"샤프 분산 {_f(var, 4)}(실행 가능, 거래 2건 이상 조합).{note} 보고용이며 판정 조건은 아니다(§8.3). 조합별 값은 §1 표.",
           "- **미래 참조 점검**: 신호·구조·체결의 미래 참조 금지 테스트(`backtest/tests/test_no_lookahead.py`: 데이터 절단·미래 "
           "변경에 후보가 그대로인지, 그리고 후보 → 순차 엔진(F8·F9·방해 금지·하루 6건) → 체결·청산·펀딩까지 끝까지 절단 "
           "불변인지(T-NLA-6))가 테스트 모음에 들어 있다.",
           "- **v1.0 범위 밖(미실시)**: PBO(백테스트 과최적화 확률), 워크포워드, 1등 주변 ±20% 민감도, freqtrade 교차 검증.",
           f"- **판정 요약**: 통과 후보 {s['n_pass']}개 / 불합격 {s['n_fail']}개 / 보류 {s['n_pending']}개.", ""]
    return out


def _limitations(res: dict) -> list[str]:
    d, p, s = res.get("data") or {}, res.get("params") or {}, res["summary"]
    combos = res["combos"]
    out = ["## 7. 한계와 가정", ""]
    out.append(f"- **F3 이벤트 필터 꺼짐**: {_f3_text(res)}.")
    out.append(f"- **체결 판정 봉**: {_date(d.get('exec_switch_utc'))} 전에는 1분봉이 없어 5분봉으로 체결·청산을 판정했다. "
               "5분봉 안의 가격 순서를 모르므로 한 봉에서 손절과 목표를 둘 다 건드리면 손절로 보았고(1분봉 구간도 같음, §12.1), "
               "주문 시작이 5분 경계가 아니면 다음 5분봉부터 체결을 인정했다(보수적).")
    if d.get("funding_n_synthetic"):
        out.append(f"- **펀딩비 가정**: 실제 기록은 {_date(d.get('funding_last_real_utc'))}까지다. 그 뒤 "
                   f"{_int(d.get('funding_n_synthetic'))}번의 펀딩은 {_pct(d.get('funding_fallback_rate'), 2)}로 가정했다(§12.2).")
    out.append("- **체결 모델**: 지정가는 가격이 뚫고 지나가야(관통) 체결로 본다. 대기열 순서·부분 체결·시장 충격은 모델에 없다. "
               "손절·시간 청산에만 슬리피지 0.02%를 넣었다. L1b 상한 지정가(IOC)는 5분봉 구간에서 활성 뒤 첫 5분봉 시가에 "
               "체결하지만, 펀딩은 활성 시각부터 센다(그 사이 펀딩 시각을 빼지 않음).")
    out.append(_marketable_text(res))
    out.append("- **R 기준**: 거래당 R = 단위당 순손익 ÷ (손절 폭 + 기본 비용)이고, 손절 폭·비용은 **실제 진입가** 기준이다. "
               "지정가는 계획가에 체결되므로 계획가와 같고, L1b 상한 지정가(IOC)는 실제 체결가(첫 실행 봉 시가)로 계산해 "
               "손절 = 정확히 −1R이며 무작위 기준선과 같은 단위다(검토 전 구현(옛 I-29)은 상한가 기준이라 L1b 손실을 작게 기록했다). "
               "L1b의 손절 폭 검사(§8.1)는 신호 시점의 상한가 기준이라, 시가가 상한보다 낮게 체결되면 실제 손절 폭이 하한"
               "(0.4%·1 ATR)보다 좁을 수 있다. 명목 상한(0.6배) 때문에 수량을 줄인 효과는 판정에 넣지 않고 보조 지표로만 "
               "기록했다(I-28, 수량은 계획 가격 기준).")
    if any(c["key"].startswith("L1b") for c in combos):
        out.append("- **L1b 준비 규칙**: 마디 하나에서 준비(저가가 [H, H + 0.25W]에 들어옴)는 **한 번만** 본다. 확인되면 신호 "
                   "1개, 폐기(24봉 안 확인 없음·종가 H 아래 두 번째·마디 사망)되면 그 마디의 L1b는 끝이다(명세 §7.2 문장, 근거 "
                   "STRATEGY '같은 가격은 첫 터치만'). 검토 전 구현의 해석(옛 I-22: 에피소드가 끝나면 같은 마디에서 다시 준비)은 명세에 없는 "
                   "규칙으로 L1b 표본 대부분을 만들었다(검토: P1 실행 가능 체결 43건 중 34건이 재준비). 이 해석의 결과는 §5 "
                   "민감도 표의 'L1b 재준비(명세 밖 진단)'로만 보고한다.")
    few = [c["key"] for c in combos if 0 < _n(c["exec"]) < C.G1_MIN_TRADES]
    zero = [c["key"] for c in combos if _n(c["exec"]) == 0]
    if few or zero:
        out.append(f"- **표본 수**: 실행 가능 거래가 30건 미만인 조합 {len(few) + len(zero)}개(0건 {len(zero)}개)는 판정 보류다. "
                   "적은 표본의 평균 R은 운에 크게 흔들린다.")
    s3 = [c for c in combos if c["key"].startswith("S3")]
    if s3 and all(_n(c["exec"]) == 0 for c in s3):
        rr = {c["key"]: ((_num((c["exec"].get("discard_any_reason") or {}).get("RISK_RR")) or 0)
                         / max(_num(c["exec"].get("n_candidates")) or 1, 1)) for c in s3}
        shares = ", ".join(f"{k} {_pct(v)}" for k, v in rr.items())
        if min(rr.values()) >= 0.5:
            out.append(f"- **S3 거래 없음 = 사실상 시험되지 않음**: S3 조합은 모두 거래가 0건이다. 후보 대부분이 순손익비 1.5 "
                       f"미만으로 탈락했다(순손익비 미달 후보 비율: {shares}). 목표 규칙 때문이다: 명세 §7.4 'S 아래 가장 가까운 "
                       "확정 스윙 저점'에는 기간이 없는데, 이를 전체 이력(6년 넘는 스윙 저점 수천 개)에서 찾는 해석(I-25)이라 "
                       "목표가 거의 항상 S 바로 밑(대개 S ± 0.1% 안)에 잡힌다. 따라서 S3는 v1.0에서 사실상 시험되지 않았다. "
                       "v2 후보: 목표 = 지지선과 같은 최근 100봉 안에서 S × (1 − 0.1%) 아래의 가장 가까운 스윙 저점.")
        else:
            out.append(f"- **S3 거래 없음**: S3 조합은 모두 거래가 0건이다(순손익비 미달 후보 비율: {shares}). "
                       "걸린 사유는 §3 표 참고.")
    if s3:
        out.append("- **S3 해석 메모(명세 문장 그대로, v2에서 정할 것)**: 손절 S + ATR은 손절 폭 하한(1 × ATR)과 같은 거리라 "
                   "S와 손절을 따로 0.1 USDT 반올림한 방향만으로 손절 폭 검사를 통과하거나 탈락한다(검토: 해당 P1 후보의 약 "
                   "46%). '이탈'은 직전 종가가 이미 S 아래인 봉도 VR ≥ 2면 새 이탈로 세고, '두 번째 종가 이탈'은 S 아래 연속 "
                   "두 봉으로도 성립하며, 지지선의 '2번 이상 닿음'은 스윙 봉 자신과 바로 옆 봉으로도 채워진다.")
    out.append("- **지표 준비 기간**: 신호 봉 620개(P1 약 26일, P2 약 103일)가 지나야 신호를 낸다. P2의 방향 봉은 일봉이라 "
               "허리 기준 방향(DA)은 일봉 620개(약 1.7년)가 지난 뒤에야 방향을 허용한다(이평 기준 DB는 120일).")
    end = (d.get("span_utc") or [None, None])[1]
    partial = ""
    last = _end_date(end)
    if last[:4].isdigit() and int(last[:4]) in C.G1_YEARS and last[5:10] != "12-31":
        partial = f" {last[:4]}년은 {last}까지만 있다."
    out.append(f"- **연도**: 연도별 조건(⑥)은 {C.G1_YEARS[0]}~{C.G1_YEARS[-1]}년 {len(C.G1_YEARS)}개 연도로 센다."
               f"{partial} 거래가 없는 해는 양수로 세지 않는다.")
    out.append("- **데이터 끝**: 끝까지 청산되지 않은 거래는 마지막 실행 봉 종가에 청산했다(I-36).")
    out.append("- **허리 동점 규칙(하락 마디)**: 명세 §4.3 '그래도 같으면 낮은 칸'을 하락 마디에서는 §4.4 '상승의 대칭'으로 읽어 "
               "A 쪽(높은 가격) 칸을 쓴다(I-13). 거래량까지 같은 동점은 드물지 않지만(검토: 4H 마디 228개 중 28개), 문자 그대로 "
               "'낮은 가격 칸'으로 바꿔도 검토 시점의 S2·S3 후보 결과는 바뀌지 않았다(DA 숏 허용이 일부 봉에서 줄어들 뿐).")
    if p.get("random_enabled"):
        out.append("- **무작위 기준선**: 무작위 거래끼리의 겹침(한 번에 1포지션)은 무시했다. 진입은 시장가(테이커, §12.4 그대로)라 "
                   "지정가(메이커) 조합과 비교하면 무작위 쪽 이긴 거래의 R이 약 0.05~0.15R 낮다(조건 ⑤를 넘기 쉬운 쪽) → "
                   "§4.1에 같은 진입 수수료 분포의 95% 분위를 참고로 함께 실었다. 추출 시각에 방해 금지 시간의 신호 봉 마감도 "
                   "들어간다(§12.4 그대로, 기준선 평균 약 +0.006R, 보수적).")
    if res.get("donchian"):
        out.append("- **돈치안 기준선**: 비교용이다. 다음 날 시가 체결·테이커 수수료·펀딩 포함, 슬리피지 없음.")
    out.append("- **다중 시험**: 16개 조합을 동시에 시험했다. 하나가 우연히 통과할 수 있어 DSR을 함께 본다.")
    if not s.get("official"):
        out.append(f"- **부분 실행**: {', '.join(s.get('partial_reasons') or [])}. 공식 G1 판정이 아니다.")
    if res.get("git_dirty"):
        out.append("- **코드 버전**: 커밋되지 않은 코드로 실행했다. 어떤 코드였는지는 코드 해시(`code_sha256`)로 식별한다.")
    out.append("")
    return out


def _repro(res: dict) -> list[str]:
    d, p = res.get("data") or {}, res.get("params") or {}
    period = p.get("period_utc")
    cmd = "python -m backtest.run_g1"
    if period:
        if period[0]:
            cmd += f" --start {period[0][:10]}"
        if period[1]:
            cmd += f" --end {period[1][:10]}"
    if p.get("only"):
        cmd += f" --only {','.join(p['only'])}"
    if not p.get("random_enabled"):
        cmd += " --no-random"
    elif p.get("random_reps") != C.RANDOM_REPS:
        cmd += f" --reps {p.get('random_reps')}"
    if not p.get("sensitivity"):
        cmd += " --no-sensitivity"
    out = ["## 8. 재현 방법", "",
           "저장소 루트에서 (Python 3.11, pandas 3, numpy 2):", "", "```bash",
           "python -m pytest backtest/tests -q        # 테스트 전체 (미래 참조·체결·통계 검사 포함)",
           f"{cmd:<40s}  # 이 결과를 다시 만드는 명령"
           + ("" if d.get("source") == "binance" else " (합성 데이터 실행은 테스트 코드로만 재현된다)"),
           "python -m backtest.report                  # g1_results.json → G1_REPORT.md 만 다시 쓰기",
           "```", "",
           f"- 코드: 커밋 `{res.get('git_commit') or '없음'}`" + (" + 커밋되지 않은 변경" if res.get("git_dirty") else "")
           + f", 코드 해시 `{res.get('code_sha256') or '–'}` (backtest/*.py 내용의 sha256).",
           f"- 난수: 기본 시드 {p.get('seed')}. 부트스트랩·순열·무작위 기준선은 조합 이름으로 시드를 나눠 만든다(같은 입력이면 같은 결과). "
           "`g1_results.json`은 created_utc·runtime_sec 말고는 다시 돌려도 같다.",
           "- 실행 시간·단계별 시간은 `run_log.txt`, 조합별 거래는 `trades/<조합>_<all|exec>.csv`, 폐기 사유 집계는 "
           "`signals_summary.csv`에 있다.", ""]
    sha = d.get("sha256") or {}
    if sha:
        out += ["입력 데이터 sha256 (앞 16자리):", ""]
        out += _table(["파일", "sha256"], [[k, f"`{v[:16]}`"] for k, v in sha.items()], right=set())
        out.append("")
    if d.get("events_file"):
        ev = d["events_file"]
        out += [f"- 이벤트 파일: `{ev.get('path')}` ({_int(ev.get('n'))}개), sha256 `{(ev.get('sha256') or '')[:16]}`", ""]
    return out


def _appendix(res: dict) -> list[str]:
    years = [str(y) for y in C.G1_YEARS]
    out = ["## 부록 A. 연도별 평균 R (실행 가능, 진입 시각의 UTC 연도)", "",
           "칸 = 평균 R (거래 수). 거래가 없는 해는 '–'.", ""]
    rows = []
    for c in res["combos"]:
        e = c["exec"]
        yr, yn = e.get("yearly") or {}, e.get("yearly_n") or {}
        rows.append([c["key"]] + [("–" if _num(yr.get(y)) is None else f"{_r(yr.get(y))} ({_int(yn.get(y))})")
                                  for y in years] + [_int(e.get("positive_years"))])
    out += _table(["조합"] + years + ["양수 연도"], rows)
    out += ["", "## 부록 B. 용어", "",
            "- **R**: 위험 1단위(손절 폭 + 비용) 대비 손익. -1R = 손절 한 번.",
            "- **PF(Profit Factor)**: 이익 거래 R의 합 ÷ 손실 거래 R의 합(절댓값). 1보다 크면 번 쪽이 크다.",
            "- **95% CI 하한(부트스트랩)**: 거래를 무작위로 다시 뽑아 평균을 1만 번 계산했을 때 아래쪽 2.5% 값. 0보다 크면 "
            "'평균이 플러스'라는 근거가 통계적으로 확실하다는 뜻.",
            "- **비용 2배**: 수수료·슬리피지·지불 펀딩을 두 배로 놓고 다시 계산한 평균 R(거래는 같음).",
            "- **무작위 95% 분위**: 무작위 진입을 여러 번 반복했을 때 평균 R의 위쪽 5% 경계. 이보다 높아야 '운이 아니다'.",
            "- **DSR**: 여러 조합을 시험한 효과를 뺀 샤프의 신뢰도(0~1).",
            "- **판정 보류**: 거래가 30건 미만이라 판정하지 않음(표본 부족).",
            "- **실행 가능 / 전체**: 사람이 승인할 수 없는 신호(방해 금지 시간, 하루 6건 초과)를 뺀 결과 / 빼지 않은 결과.", ""]
    return out


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------


def render_markdown(results: dict) -> str:
    """결과 dict(DESIGN §8.1 스키마) → 마크다운 문자열."""
    s = results["summary"]
    lines = _header(results)
    lines += [_conclusion(results), "", f"> 판정 규칙에 따른 결정: {s.get('decision', '')}", ""]
    lines += _plain_summary(results)
    lines += _verdict_table(results)
    lines += _modes_sessions(results)
    lines += _reasons(results)
    lines += _baselines(results)
    lines += _sensitivity(results)
    lines += _overfit(results)
    lines += _limitations(results)
    lines += _repro(results)
    lines += _appendix(results)
    return "\n".join(lines).rstrip() + "\n"


def write_report(results_path: Path = C.RESULTS_DIR / "g1_results.json",
                 out_path: Path = C.RESULTS_DIR / "G1_REPORT.md") -> Path:
    """JSON을 읽어 보고서를 쓰고 경로를 돌려준다."""
    results = json.loads(Path(results_path).read_text(encoding="utf-8"))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(results), encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. 성공 0."""
    p = argparse.ArgumentParser(prog="python -m backtest.report", description="g1_results.json → G1_REPORT.md")
    p.add_argument("--results", type=Path, default=C.RESULTS_DIR / "g1_results.json", help="결과 JSON 경로")
    p.add_argument("--out", type=Path, default=None, help="보고서 경로 (기본: 결과 JSON과 같은 폴더의 G1_REPORT.md)")
    args = p.parse_args(argv)
    out = args.out if args.out is not None else args.results.with_name("G1_REPORT.md")
    path = write_report(args.results, out)
    print(f"보고서: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
