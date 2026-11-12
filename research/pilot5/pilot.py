#!/usr/bin/env python3
"""5만 원 테스트 도구 — 신호 확인, 모의 성적, 내 기록 채점.

- 바이낸스 '공개 시세'만 읽는다. API 키·로그인·주문 기능이 없다(주문은 사람이 앱에서 직접).
- 파이썬 기본 기능만 쓴다(추가 설치 없음, 파이썬 3.9 이상).

쓰는 법 (규칙은 research/pilot5/PROTOCOL.md)
  python3 pilot.py now                 밤 9시 직후: 방금 마감된 4시간봉의 신호와 주문표
  python3 pilot.py paper               2026-09-29 이후 이 신호의 모의 성적(돈 없이)
  python3 pilot.py score journal.csv   내 실전 기록 채점(journal_template.csv를 복사해 채운 파일)

신호 규칙(research/candles 사전 등록 후보, 숫자 고정)
  upper_vol = (고가 − max(시가, 종가)) ÷ (고가 − 저가) × (거래량 ÷ 직전 20봉 평균 거래량)
  upper_vol ≥ 0.42173 → 롱(실전 대상),  ≤ 0.085665 → 숏(기록만),  그 사이 → 없음.  16시간 뒤 청산.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://fapi.binance.com"  # 바이낸스 USDⓈ-M 선물 공개 API
SYMBOL, INTERVAL = "BTCUSDT", "4h"
Q80 = 0.4217300308371426  # 롱 기준 (2020~2023 상위 20% 경계)
Q20 = 0.08566545851163947  # 숏 기준 (하위 20% 경계)
AVG_BARS = 20
HOLD_BARS = 4  # 16시간
MS_4H = 4 * 3600 * 1000
SLOT_OPEN_HOUR_UTC = 8  # 08:00 UTC 시작 → 12:00 UTC = 21:00 KST 마감 봉(실전 대상)
FWD_START_MS = int(datetime(2026, 9, 29, tzinfo=timezone.utc).timestamp() * 1000)  # 처음 보는 자료의 시작
QTY = 0.001  # BTC
STOP_PCT = 0.05  # 재난 손절: 체결가 대비 5% 아래
LATE_LIMIT_MIN = 15  # 마감 뒤 15분이 지나면 그 신호는 건너뛴다
COST_PCT = 0.073  # 과거 자료로 추정한 거래당 비용(%): 실행 0.057 + 펀딩 0.016
KST = timezone(timedelta(hours=9))
HERE = Path(__file__).resolve().parent


# ---------- 자료 읽기 ----------
def http_json(path: str, params: dict) -> object:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "pilot5/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if urllib.parse.urlparse(resp.geturl()).netloc != urllib.parse.urlparse(BASE_URL).netloc:
                raise SystemExit("다른 주소로 넘겨져서 멈췄습니다.")
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        code = f" {e.code}" if isinstance(e, urllib.error.HTTPError) else ""
        raise SystemExit(f"바이낸스 시세를 읽지 못했습니다({type(e).__name__}{code}). 인터넷 연결과 접속 가능 여부를 확인하세요.")


def klines(params: dict) -> list:
    rows = http_json("/fapi/v1/klines", params)
    if not isinstance(rows, list) or any(not isinstance(r, list) or len(r) < 6 for r in rows):
        raise SystemExit("바이낸스 응답이 예상한 모양이 아닙니다. 잠시 뒤 다시 실행하세요.")
    return rows


def to_bar(row) -> tuple:
    """(시작 시각 ms, 시가, 고가, 저가, 종가, 거래량)"""
    return (int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))


def fetch_bars(start_ms: int | None, now_ms: int) -> list[tuple]:
    """마감된 4시간봉만 돌려준다. start_ms가 없으면 최근 60개."""
    bars: list[tuple] = []
    if start_ms is None:
        rows = klines(dict(symbol=SYMBOL, interval=INTERVAL, limit=60))
        bars = [to_bar(r) for r in rows]
    else:
        cur = start_ms
        while True:
            rows = klines(dict(symbol=SYMBOL, interval=INTERVAL, limit=1500, startTime=cur))
            if not rows:
                break
            bars.extend(to_bar(r) for r in rows)
            if len(rows) < 1500:
                break
            cur = int(rows[-1][0]) + 1
    return clean(bars, now_ms)


def read_file(path: str, now_ms: int | None) -> list[tuple]:
    """시험·오프라인용: 바이낸스 klines JSON 또는 open_time,open,high,low,close,volume CSV(.gz 가능)."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        if path.endswith(".json"):
            bars = [to_bar(r) for r in json.load(fh)]
        else:
            bars = [to_bar([r["open_time"], r["open"], r["high"], r["low"], r["close"], r["volume"]])
                    for r in csv.DictReader(fh)]
    return clean(bars, now_ms if now_ms is not None else bars[-1][0] + MS_4H + 60_000)


def clean(bars: list[tuple], now_ms: int) -> list[tuple]:
    seen, out = set(), []
    for b in sorted(bars):
        if b[0] in seen or b[0] + MS_4H > now_ms:  # 중복이거나 아직 마감 안 된 봉
            continue
        seen.add(b[0])
        out.append(b)
    for a, b in zip(out, out[1:]):
        if b[0] - a[0] != MS_4H:
            raise SystemExit(f"4시간봉이 빠진 구간이 있습니다({kst(a[0])} 다음). 잠시 뒤 다시 실행하세요.")
    return out


def server_now_ms() -> int:
    data = http_json("/fapi/v1/time", {})
    if not isinstance(data, dict) or "serverTime" not in data:
        raise SystemExit("바이낸스 서버 시각을 읽지 못했습니다. 잠시 뒤 다시 실행하세요.")
    return int(data["serverTime"])


# ---------- 계산 ----------
def upper_vol(bars: list[tuple], i: int):
    """i번째 봉의 (윗꼬리 비율, 거래량 배수, upper_vol). 계산할 수 없으면 None."""
    if i < AVG_BARS:
        return None
    _, o, h, l, c, v = bars[i]
    avg = sum(b[5] for b in bars[i - AVG_BARS:i]) / AVG_BARS
    if h <= l or avg <= 0:
        return None
    up = (h - max(o, c)) / (h - l)
    mult = v / avg
    return up, mult, up * mult


def signal_of(x: float | None) -> int:
    if x is None:
        return 0
    return 1 if x >= Q80 else (-1 if x <= Q20 else 0)


def kst(ms: int, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return datetime.fromtimestamp(ms / 1000, tz=KST).strftime(fmt)


def is_slot(bar: tuple) -> bool:
    return datetime.fromtimestamp(bar[0] / 1000, tz=timezone.utc).hour == SLOT_OPEN_HOUR_UTC


SIG_KR = {1: "롱", -1: "숏", 0: "없음"}


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def hac_t(z: list[float], lags: int) -> float:
    """평균이 0인지에 대한 t값. 보유 기간이 겹치는 것을 고려한다(Newey–West)."""
    n = len(z)
    if n < 30:
        return float("nan")
    m = mean(z)
    zc = [x - m for x in z]
    var = sum(x * x for x in zc) / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * sum(zc[i] * zc[i - k] for i in range(k, n)) / n
    return m / math.sqrt(var / n) if var > 0 else float("nan")


# ---------- now ----------
def cmd_now(args) -> None:
    if args.file:
        bars = read_file(args.file, args.now_ms)
        now_ms = args.now_ms if args.now_ms is not None else bars[-1][0] + MS_4H + 60_000
    else:
        now_ms = server_now_ms()
        bars = fetch_bars(None, now_ms)
    i = len(bars) - 1
    res = upper_vol(bars, i)
    if res is None:
        raise SystemExit("이 봉은 계산할 수 없습니다(고가 = 저가이거나 자료 부족).")
    up, mult, x = res
    sig = signal_of(x)
    t0, o, h, l, c, v = bars[i]
    close_ms = t0 + MS_4H
    late = (now_ms - close_ms) / 60_000
    slot = is_slot(bars[i])
    print(f"[신호 확인] {kst(close_ms)} KST에 마감된 4시간봉 (바이낸스 {SYMBOL} 선물)")
    print(f"  시가 {o:,.1f} / 고가 {h:,.1f} / 저가 {l:,.1f} / 종가 {c:,.1f}")
    print(f"  윗꼬리 비율 {up:.3f} × 거래량 배수 {mult:.2f} = {x:.3f}   (롱 기준 {Q80:.3f} 이상, 숏 기준 {Q20:.3f} 이하)")
    print(f"  신호: {SIG_KR[sig]}")
    real = sig == 1 and slot and late <= LATE_LIMIT_MIN
    if not slot:
        print("  이 봉은 실전 대상(밤 9시 마감 봉)이 아닙니다. 기록만 합니다.")
    elif sig == 1 and late > LATE_LIMIT_MIN:
        print(f"  마감 뒤 {late:.0f}분이 지났습니다. 규칙상 {LATE_LIMIT_MIN}분이 넘으면 이번 신호는 건너뜁니다(기록만).")
    elif sig == -1:
        print("  숏 신호는 실전에서 하지 않습니다. 기록만 합니다.")
    elif sig == 0:
        print("  오늘은 주문하지 않습니다.")
    if real:
        exit_ms = close_ms + HOLD_BARS * MS_4H
        print("  ── 주문표 ──────────────────────────────")
        print(f"  1) 격리(Isolated)·5배·단방향인지 확인하고, {SYMBOL} {QTY} BTC 매수")
        print("     지정가(Post Only), 가격은 지금 매수 1호가. 10분 안에 체결이 안 되면 취소하고 시장가로 매수")
        print(f"  2) 체결되면 바로 손절 주문: 체결가 × {1 - STOP_PCT:.2f} (참고: {c * (1 - STOP_PCT):,.1f}) "
              "Stop-Market, Reduce-Only, Mark Price")
        print(f"  3) 청산: {kst(exit_ms)} KST. 지정가(Post Only) 매도, 10분 안에 안 되면 시장가. 끝나면 열린 주문 0개 확인")
        print(f"  모의 진입가(일지에 적을 값): {c:,.1f}")
    log = HERE / "signals_log.csv"
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["bar_close_kst", "close", "upper", "vol_mult", "upper_vol", "signal", "slot", "checked_kst", "late_min", "real"])
        w.writerow([kst(close_ms), c, round(up, 4), round(mult, 3), round(x, 4), SIG_KR[sig], "Y" if slot else "N",
                    kst(now_ms), round(late, 1), "Y" if real else "N"])
    print(f"  (확인 기록을 {log.name}에 남겼습니다)")


# ---------- paper ----------
def evaluate(bars: list[tuple], start_ms: int) -> list[dict]:
    rows = []
    for i in range(AVG_BARS, len(bars) - HOLD_BARS):
        if bars[i][0] < start_ms:
            continue
        res = upper_vol(bars, i)
        rows.append(dict(open_ms=bars[i][0], close=bars[i][4], x=res[2] if res else None, sig=signal_of(res[2] if res else None),
                         exit_close=bars[i + HOLD_BARS][4], r=bars[i + HOLD_BARS][4] / bars[i][4] - 1, slot=is_slot(bars[i])))
    return rows


def paper_block(title: str, rows: list[dict], overlap: bool) -> None:
    if not rows:
        print(f"{title}: 아직 자료가 없습니다.")
        return
    base = mean([r["r"] for r in rows])
    lg = [r["r"] for r in rows if r["sig"] == 1]
    sh = [-r["r"] for r in rows if r["sig"] == -1]
    print(f"{title}  (봉 {len(rows)}개)")
    print(f"  아무 때나 롱(기준선): 평균 {base * 100:+.3f}%")
    if lg:
        ex = mean(lg) - base
        d = [1.0 if r["sig"] == 1 else 0.0 for r in rows]
        dm, rm = mean(d), base
        t = hac_t([(a - dm) * (r["r"] - rm) for a, r in zip(d, rows)], HOLD_BARS - 1 if overlap else 0)
        print(f"  롱 신호 {len(lg)}번: 평균 {mean(lg) * 100:+.3f}%, 이긴 비율 {sum(x > 0 for x in lg) / len(lg) * 100:.0f}%, "
              f"기준선 대비 {ex * 100:+.3f}%p, 비용({COST_PCT}%) 뒤 {(mean(lg) - COST_PCT / 100) * 100:+.3f}%")
        print(f"  초과 수익 t값: {t:+.2f}" if t == t else "  초과 수익 t값: 표본이 30개 미만이라 계산하지 않음")
    else:
        print("  롱 신호: 아직 없음")
    if sh:
        print(f"  숏 신호 {len(sh)}번(기록만): 숏 했다면 평균 {mean(sh) * 100:+.3f}%")


def cmd_paper(args) -> None:
    if args.file:
        bars = read_file(args.file, args.now_ms)
    else:
        bars = fetch_bars(FWD_START_MS - (AVG_BARS + 2) * MS_4H, server_now_ms())
    start = args.start_ms if args.start_ms is not None else FWD_START_MS
    rows = evaluate(bars, start)
    if not rows:
        raise SystemExit("평가할 봉이 없습니다.")
    print(f"[모의 성적] {kst(rows[0]['open_ms'] + MS_4H)} ~ {kst(rows[-1]['open_ms'] + MS_4H)} KST 마감 봉, 16시간 보유, 비용 전")
    paper_block("① 하루 6번 전체", rows, overlap=True)
    paper_block("② 밤 9시 마감 봉만(실전 대상)", [r for r in rows if r["slot"]], overlap=False)
    print("읽는 법: t값이 +2를 넘어야 '우연이 아닐 수 있다'고 봅니다. 과거 크기 그대로여도 ①은 1년쯤, ②는 훨씬 더 걸립니다.")
    print("        t값이 −1.5 아래면 이 신호는 버립니다(PROTOCOL.md 판정 C).")
    out = HERE / "paper_log.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["bar_close_kst", "close", "upper_vol", "signal", "slot", "exit_close", "ret_16h_pct"])
        for r in rows:
            w.writerow([kst(r["open_ms"] + MS_4H), r["close"], "" if r["x"] is None else round(r["x"], 4), SIG_KR[r["sig"]],
                        "Y" if r["slot"] else "N", r["exit_close"], round(r["r"] * 100, 4)])
    print(f"(봉별 기록: {out.name})")


# ---------- score ----------
def cmd_score(args) -> None:
    with open(args.journal, newline="", encoding="utf-8-sig") as fh:
        jr = [r for r in csv.DictReader(fh) if (r.get("date") or "").strip() and not r["date"].startswith("#")]
    if not jr:
        raise SystemExit("일지에 기록이 없습니다.")
    days = sorted(datetime.strptime(r["date"].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc) for r in jr)
    first_ms = int(days[0].timestamp() * 1000) + SLOT_OPEN_HOUR_UTC * 3600_000
    if args.file:
        bars = read_file(args.file, args.now_ms)
    else:
        bars = fetch_bars(first_ms - (AVG_BARS + 2) * MS_4H, server_now_ms())
    idx = {b[0]: i for i, b in enumerate(bars)}
    yes = lambda s: (s or "").strip().upper() in ("Y", "YES", "예", "O")
    num = lambda s: float((s or "0").replace(",", "").strip() or 0)
    checked = traded = off_rule = long_sigs = taken = 0
    short, pnl, guesses, lines = [], [], [], []
    equity, low_equity = args.start_usdt, args.start_usdt
    for r in sorted(jr, key=lambda r: r["date"]):
        d = datetime.strptime(r["date"].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        i = idx.get(int(d.timestamp() * 1000) + SLOT_OPEN_HOUR_UTC * 3600_000)
        if i is None:
            lines.append(f"  {r['date']}: 그날 밤 9시 봉 자료가 아직 없습니다.")
            continue
        res = upper_vol(bars, i)
        sig = signal_of(res[2] if res else None)
        checked += yes(r.get("checked"))
        long_sigs += sig == 1
        done = i + HOLD_BARS < len(bars)
        paper = bars[i + HOLD_BARS][4] / bars[i][4] - 1 if done else None
        g = (r.get("my_guess") or "").strip().upper()
        if g in ("L", "S") and done:
            guesses.append((paper > 0) == (g == "L"))
        if not yes(r.get("traded")):
            continue
        traded += 1
        bad = sig != 1 or not yes(r.get("rule_ok"))
        off_rule += bad
        taken += sig == 1
        entry, exitp = num(r.get("entry_price")), num(r.get("exit_price"))
        if entry <= 0 or exitp <= 0:
            lines.append(f"  {r['date']}: 진입가·청산가가 비어 있어 계산에서 뺐습니다.")
            continue
        notional = entry * QTY
        usdt = (exitp - entry) * QTY - abs(num(r.get("fee_usdt"))) + num(r.get("funding_usdt"))
        live = usdt / notional
        equity += usdt
        low_equity = min(low_equity, equity)
        pnl.append(usdt)
        if done and sig == 1:
            short.append(live - paper)
        lines.append(f"  {r['date']}: 실제 {live * 100:+.3f}% ({usdt:+.3f} USDT)"
                     + (f", 모의 {paper * 100:+.3f}%, 실행 손해 {(live - paper) * 100:+.3f}%p" if done else "")
                     + (" ← 규칙 밖" if bad else ""))
    print(f"[내 기록 채점] 일지 {len(jr)}일")
    print("\n".join(lines))
    print("── 요약 ──")
    print(f"  A. 규칙 지키기: 확인한 날 {checked}/{len(jr)}일, 롱 신호 {long_sigs}번 중 실행 {taken}번, 규칙 밖 주문 {off_rule}번")
    if short:
        m, s = mean(short), sd(short)
        se = s / math.sqrt(len(short)) if len(short) > 1 else float("nan")
        print(f"  B. 실행 손해(실제 − 모의): 평균 {m * 100:+.3f}%p (±{2 * se * 100:.3f}), {len(short)}번. 과거 자료 추정은 −0.073%p")
    print(f"  손익 합계: {sum(pnl):+.2f} USDT ≈ {sum(pnl) * args.krw:+,.0f}원 ({len(pnl)}번). 이 숫자는 운이 대부분이라 판정에 쓰지 않습니다.")
    print(f"  계좌: 시작 {args.start_usdt:.2f} → 지금 {equity:.2f} USDT (최저 {low_equity:.2f}). "
          + ("⚠ 시작의 70% 아래로 내려갔습니다. 규칙상 실전을 멈춥니다." if low_equity <= 0.7 * args.start_usdt else "멈춤 기준(70%) 위입니다."))
    if guesses:
        print(f"  내 예측: {sum(guesses)}/{len(guesses)}번 맞음 ({sum(guesses) / len(guesses) * 100:.0f}%). 100번이 넘기 전에는 50%와 구분되지 않습니다.")


def main() -> None:
    p = argparse.ArgumentParser(description="5만 원 테스트 도구 (공개 시세만 읽음, 주문 기능 없음)")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("now", "paper", "score"):
        sp = sub.add_parser(name)
        sp.add_argument("--file", help="시세 파일(JSON 또는 CSV, .gz 가능). 없으면 바이낸스에서 읽음")
        sp.add_argument("--now-ms", type=int, default=None, help=argparse.SUPPRESS)
        if name == "paper":
            sp.add_argument("--start-ms", type=int, default=None, help=argparse.SUPPRESS)
        if name == "score":
            sp.add_argument("journal")
            sp.add_argument("--start-usdt", type=float, default=35.76, help="실전 시작 때 선물 지갑 잔고(USDT)")
            sp.add_argument("--krw", type=float, default=1360.0, help="1 USDT가 몇 원인지")
    args = p.parse_args()
    {"now": cmd_now, "paper": cmd_paper, "score": cmd_score}[args.cmd](args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
