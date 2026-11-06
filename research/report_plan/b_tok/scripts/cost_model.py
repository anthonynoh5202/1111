"""1시간 보고서 설계안별 월 비용 계산 (B_llm_arch.md 표의 근거). 실제 호출 없음.

단가 출처: platform.claude.com/docs/en/about-claude/pricing (2026-11-06 받음), $/백만 토큰.
GLM 단가: docs.z.ai 가격표(검색 요약, 공식 페이지 직접 열람 불가) — 확인 필요.
"""
from __future__ import annotations

import itertools

M = 1_000_000
HOURS = 720            # 30일 × 24
DAYS = 30

# Claude (input, write5m, write1h, read, output)
OPUS = dict(inp=4.0, w5=5.0, w1h=8.0, rd=0.20, out=20.0)
SONNET = dict(inp=2.0, w5=2.5, w1h=4.0, rd=0.10, out=10.0)
HAIKU = dict(inp=0.10, w5=0.125, w1h=0.20, rd=0.01, out=0.50)   # 프롬프트 10만 토큰 이하 구간
# GLM-5.3 (input, cached input, output) — 검색 요약
GLM53 = dict(inp=1.4, rd=0.26, out=4.4)
GLM53_FLASH = dict(inp=0.15, rd=0.15, out=0.50)                # 캐시 단가 미확인 → 입력과 같다고 가정


def call(p, *, read=0, w5=0, w1h=0, inp=0, out=0):
    return (read * p["rd"] + w5 * p.get("w5", 0) + w1h * p.get("w1h", 0) + inp * p["inp"] + out * p["out"]) / M


def keepalive(p, P):
    """max_tokens=1 갱신 요청: 접두부 캐시 읽기 + 꼬리 30토큰 + 출력 1토큰."""
    return call(p, read=P, inp=30, out=1)


def plan_a(P, D, O, act=0.2, reask=0.15, keep=True):
    """(a) 매시간 Opus 전체 분석. keep=True: 1h 캐시 + :30 갱신(항상 적중). 하루 1번 재기록(재시작·실패 대비)."""
    main = call(OPUS, read=P, inp=D, out=O)
    second = act * call(OPUS, read=P, inp=D, out=O)                       # 행동 신호일 때 2번째 표본
    re = reask * call(OPUS, read=P, inp=D + 3000, out=O)                  # 검사 위반 재요청
    per_hour = main + second + re + (keepalive(OPUS, P) if keep else 0)
    rewrite = DAYS * call(OPUS, w1h=P)                                    # 하루 1번 1h 쓰기
    return HOURS * per_hour + rewrite


def plan_a_nocache(P, D, O, act=0.2, reask=0.15):
    one = call(OPUS, inp=P + D, out=O)
    return HOURS * one * (1 + act + reask)


def plan_a_1h_boundary(P, D, O, hit=0.5):
    """1h 캐시만 쓰고 정확히 60분 간격으로 부를 때(경계 — 적중 보장 없음). 놓치면 1h 쓰기(2배)를 다시 낸다."""
    hit_c = call(OPUS, read=P, inp=D, out=O)
    miss_c = call(OPUS, w1h=P, inp=D, out=O)
    return HOURS * (hit * hit_c + (1 - hit) * miss_c)


def plan_b(P, D, O, n_day=5, act=0.4, reask=0.15, keep=False, haiku=True):
    """(b) 매시간 = 계산 엔진 템플릿 + Haiku 5.5 짧은 해설. Opus 전체 분석은 하루 n_day번(구조 변화·조건 충족·매일 09시).
    keep=False: 분석마다 5분 캐시 쓰기(2번째 표본·재요청은 읽기). keep=True: 50분마다 갱신 + 하루 1번 1h 쓰기."""
    n = n_day * DAYS
    if keep:
        first = call(OPUS, read=P, inp=D, out=O)
        idle_refresh = DAYS * (24 * 60 / 50) * keepalive(OPUS, P)       # 넉넉히: 50분마다 갱신
        base = DAYS * call(OPUS, w1h=P)
    else:
        first = call(OPUS, w5=P, inp=D, out=O)
        idle_refresh = 0.0
        base = 0.0
    second = act * call(OPUS, read=P, inp=D, out=O)
    re = reask * call(OPUS, read=P, inp=D + 3000, out=O)
    opus = n * (first + second + re) + idle_refresh + base
    hk = HOURS * call(HAIKU, inp=4500, out=1200) if haiku else 0.0
    return opus + hk


def plan_c(P, D, O_s, O, act=0.2, reask=0.15):
    """(c) Sonnet 5.5 매시간 전체 분석(1h 캐시 + :30 갱신) + Opus 하루 1번(5분 캐시 쓰기)."""
    s_main = call(SONNET, read=P, inp=D, out=O_s)
    s_extra = (act + reask) * call(SONNET, read=P, inp=D, out=O_s)
    sonnet = HOURS * (s_main + s_extra + keepalive(SONNET, P)) + DAYS * call(SONNET, w1h=P)
    opus = DAYS * (call(OPUS, w5=P, inp=D, out=O) + call(OPUS, read=P, inp=D, out=O))   # 매일 2표본
    return sonnet + opus


def glm(n, P, D, O, hit):
    c = hit * call(GLM53, read=P, inp=D, out=O) + (1 - hit) * call(GLM53, inp=P + D, out=O)
    return n * c


def fmt(x):
    return f"${x:,.0f}"


if __name__ == "__main__":
    D = 8000
    print("== 호출 1회 단가 (P=60K, D=8K, O=10K) ==")
    P, O = 60000, 10000
    rows = {
        "Opus 캐시 없음": call(OPUS, inp=P + D, out=O),
        "Opus 5분 쓰기": call(OPUS, w5=P, inp=D, out=O),
        "Opus 1시간 쓰기": call(OPUS, w1h=P, inp=D, out=O),
        "Opus 캐시 읽기": call(OPUS, read=P, inp=D, out=O),
        "Opus 갱신(max_tokens=1)": keepalive(OPUS, P),
        "Sonnet 캐시 읽기": call(SONNET, read=P, inp=D, out=O),
        "Haiku 짧은 해설(기준서 없이 4.5K 입력)": call(HAIKU, inp=4500, out=1200),
        "Haiku 기준서 포함·캐시 없음": call(HAIKU, inp=P + D, out=3000),
        "GLM-5.3 캐시 없음(O=6K)": call(GLM53, inp=P + D, out=6000),
        "GLM-5.3 캐시 적중(O=6K)": call(GLM53, read=P, inp=D, out=6000),
        "GLM-5.3-Flash 캐시 없음(O=4K)": call(GLM53_FLASH, inp=P + D, out=4000),
    }
    for k, v in rows.items():
        print(f"  {k:<40} ${v:.4f}")
    print("  출력만(Opus 10K):", f"${call(OPUS, out=10000):.3f}", " 접두부 읽기(60K):", f"${call(OPUS, read=60000):.4f}",
          " 접두부 1h 쓰기:", f"${call(OPUS, w1h=60000):.3f}", " 5분 쓰기:", f"${call(OPUS, w5=60000):.3f}")

    print("\n== 월 비용 (30일) ==")
    for P, O in itertools.product((45000, 60000, 75000), (6000, 10000, 16000)):
        a_keep = plan_a(P, D, O)
        a_nc = plan_a_nocache(P, D, O)
        a_b50 = plan_a_1h_boundary(P, D, O, 0.5)
        b5 = plan_b(P, D, O, n_day=5)
        b5k = plan_b(P, D, O, n_day=5, keep=True)
        b10 = plan_b(P, D, O, n_day=10)
        c = plan_c(P, D, O, O)
        print(f"P={P//1000}K O={O//1000}K | a(1h+갱신) {fmt(a_keep)} | a(캐시없음) {fmt(a_nc)} | a(60분 경계, 적중50%) {fmt(a_b50)}"
              f" | b(5회/일) {fmt(b5)} | b(5회/일·갱신) {fmt(b5k)} | b(10회/일) {fmt(b10)} | c {fmt(c)}")

    print("\n== (b) 하루 분석 횟수 민감도 (P=60K, O=10K) ==")
    for n in (2, 3, 5, 8, 12, 24):
        print(f"  {n:>2}회/일: 갱신 없음 {fmt(plan_b(60000, D, 10000, n_day=n))}  갱신 있음 {fmt(plan_b(60000, D, 10000, n_day=n, keep=True))}")

    print("\n== (a) 세부 (P=60K, O=10K) ==")
    P, O = 60000, 10000
    print("  본 호출 출력", fmt(HOURS * call(OPUS, out=O)), " 본 호출 입력(읽기+꼬리)", fmt(HOURS * call(OPUS, read=P, inp=D)),
          " 갱신", fmt(HOURS * keepalive(OPUS, P)), " 하루 1회 재기록", fmt(DAYS * call(OPUS, w1h=P)),
          " 2번째 표본(20%)", fmt(HOURS * 0.2 * call(OPUS, read=P, inp=D, out=O)),
          " 재요청(15%)", fmt(HOURS * 0.15 * call(OPUS, read=P, inp=D + 3000, out=O)))
    print("  1h 캐시 없이 5분 캐시만(매시간 새로 쓰기):", fmt(HOURS * call(OPUS, w5=P, inp=D, out=O)))

    print("\n== GLM 두 번째 의견 (P=60K, D=8K, O=6K) — Claude 예산과 별도 ==")
    for n, lab in ((150, "Opus 분석 때만 150회"), (720, "매시간 720회")):
        print(f"  {lab}: 캐시 적중 0% {fmt(glm(n, 60000, D, 6000, 0))} / 적중 80% {fmt(glm(n, 60000, D, 6000, 0.8))}")

    print("\n== 검증 실험 비용 (Opus, Batch 50% 할인, P=60K, D=8K, O=10K) ==")
    batch = dict(inp=2.0, w5=2.5, w1h=4.0, rd=0.10, out=10.0)
    one_miss = call(batch, inp=P + D, out=O)
    one_hit = call(batch, read=P, inp=D, out=O)
    print(f"  Batch 1회: 캐시 없음 ${one_miss:.3f} / 캐시 적중 ${one_hit:.3f}")
    for name, n in (("반복 일관성 50입력×5회", 250), ("상하 반전 50×2×3", 300), ("날짜제거·가격재조정 50×2×3", 300),
                    ("2026-07~09 깨끗한 검증 360시점×1", 360), ("최소 세트 30×3 + 30×2×2 ×2종 + 180시점", 90 + 120 + 120 + 180)):
        print(f"  {name}: {n}회 → {fmt(n * one_hit)} ~ {fmt(n * one_miss)}")
