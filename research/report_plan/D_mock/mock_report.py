"""보고서 시안(모의): 2026-09-29 09:00 KST 기준 1페이지 PDF + 텔레그램 미리보기 PNG.

실행:  /home/user/1111/.venv/bin/python mock_report.py
- 저장소 데이터(/home/user/1111/data/binance/)는 읽기만 한다. 비밀 값은 쓰지 않는다.
- 결과(이 파일과 같은 폴더):
    mock_report.pdf        정식 보고서(휴대폰 세로 화면용 1페이지, 벡터)
    mock_report_page.png   같은 페이지를 PNG로(눈 확인용)
    mock_preview.png       텔레그램 사진 미리보기(1080x1350, 4:5)
- 판단 내용은 research/briefing_proto/brief_0929.md(관망 + 조건부 롱 계획)를 쓰되,
  손절만 허리(80.8k) 바로 아래 → 9/20 저점(80.1k) 아래 79.8k로 고쳤다([CP-17-7] 허리 바로 아래에 컷을 붙이지 않는다).
- 수량·증거금·레버리지·청산가·원화 손실은 퀀트①의 참조 구현 scratchpad/team/A1/a1_sizing.py를 불러 계산한다
  (최소 주문 50 USDT·수량 단위 0.001 BTC, 2026-04-14부터 / 레버리지 규칙 L1~L3 / 5만 원 단계 강제 위험 상한 3%).
- 검사기 규칙(이 단계): 1회 위험 ≤ 3%, 손익비(목표2, 비용 뒤) ≥ 2. 하나라도 못 넘으면 "진입 불가"로 표시한다.
- 과거 데이터 샘플이며 투자 권유가 아니다.
"""
from __future__ import annotations

import itertools
import math
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib import transforms as mtrans  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle  # noqa: E402
from matplotlib.textpath import TextToPath  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
FONT_DIR = HERE.parents[1] / "fonts"                      # scratchpad/fonts
DATA = pathlib.Path("/home/user/1111/data/binance")
sys.dont_write_bytecode = True                            # A1 폴더에 __pycache__를 만들지 않는다
sys.path.insert(0, str(HERE.parent / "A1"))               # 퀀트① 사이징 참조 구현
import a1_common as A1C  # noqa: E402
import a1_sizing as A1S  # noqa: E402

# ------------------------------------------------------------------ 글꼴·색
for _w in ("Regular", "SemiBold", "Bold"):
    font_manager.fontManager.addfont(str(FONT_DIR / f"Pretendard-{_w}.ttf"))
plt.rcParams.update({"font.family": "Pretendard", "pdf.fonttype": 42, "ps.fonttype": 42,
                     "axes.unicode_minus": False})

SURFACE, PAPER, INK, INK2, MUTED = "#fcfcfb", "#f2f1ec", "#1f1f1d", "#52514e", "#8a8984"
GRID, HAIR = "#ebeae4", "#dcdbd4"
UP, DOWN = "#d94a3d", "#3d6fd9"                        # 한국식: 양봉·이익 빨강 / 음봉·손실 파랑
WY_C = WY_FILL = WY_EDGE = "#008300"                    # 워뇨띠 초록: 색약 검사(빨강 양봉과 ΔE 6.9)는 모양·번호·글자 보조 구분 조건으로 통과
WARN_BG, WARN_ICON, WARN_INK = "#fbefd2", "#e3a008", "#6b4700"
PILL = "#4a4945"
CHECK_BG = "#ecebe6"

# ------------------------------------------------------------------ 기준 시각·계획(사람이 정한 값)
ASOF = pd.Timestamp("2026-09-29 09:00", tz="Asia/Seoul")   # 이 시각에 마감된 봉까지만 쓴다
START = pd.Timestamp("2026-09-19 09:00", tz="Asia/Seoul")  # 차트 첫 봉(4시간봉 60개)
FUTURE = 14                                                # 오른쪽 계획 칸(4시간봉 칸 수)

PLAN = dict(entry_lo=82_300, entry_hi=83_100, entry=82_700,   # entry = 수량 계산용 가정(구간 가운데)
            stop=79_800, t1=84_800, t2=87_000,
            low_0920=80_095.9, waist=(80_822, 81_144), box_top=82_283,
            wick=(84_855, 85_224), sup=(82_500, 83_130), prev_high=87_385.1)
HOLD_H = 36            # 4시간봉 계획의 예상 보유 시간(펀딩 비용 계산, A1 예시와 같은 값)
RR_MIN = 2.0           # 검사기: 손익비(목표2, 비용 뒤) 하한
RECHECK_ENTRY = 82_300  # 재검토 조건 계산용 진입가(82.3k 부근)
VIEWS_ONE_LINE = (("CP", "차트프로", "매수 쪽 · 대기"), ("WY", "워뇨띠", "관망"), ("CL", "Claude", "관망 · 모의 기록"))


def sizing(p: dict) -> dict:
    """a1_sizing.plan_trade로 계산하고 검사기 규칙(위험 ≤ 3%, 손익비 ≥ 2)을 붙인다."""
    E = A1C.ACCOUNT_USDT
    k = A1C.KRW_PER_USDT
    t2 = A1S.plan_trade(E, 0.02, p["entry"], p["stop"], "long", target=p["t2"], hold_hours=HOLD_H)
    t1 = A1S.plan_trade(E, 0.02, p["entry"], p["stop"], "long", target=p["t1"], hold_hours=HOLD_H)
    # 진입 불가여도 "이 계획대로라면" 레버리지·증거금·청산가를 보여 주려고 위험 상한만 풀어서 한 번 더 계산
    would = A1S.plan_trade(E, 0.02, p["entry"], p["stop"], "long", target=p["t2"], hold_hours=HOLD_H,
                           max_forced_risk=1.0)
    r2 = t2.gain_at_target / t2.loss_at_stop
    r1 = t1.gain_at_target / t1.loss_at_stop
    risk_ok = t2.risk_frac <= A1S.MAX_FORCED_RISK
    rr_ok = r2 >= RR_MIN
    # 재검토 조건: 82.3k 진입에서 위험 3% 이내가 되는 최대 손절 폭(이분 탐색, 1시간봉 자리라 보유 12시간 가정)
    lo, hi = 0.0, 0.05
    for _ in range(60):
        mid = (lo + hi) / 2
        pp = A1S.plan_trade(E, 0.02, RECHECK_ENTRY, RECHECK_ENTRY * (1 - mid), "long", target=p["t2"], hold_hours=12)
        lo, hi = (mid, hi) if not pp.verdict.startswith("NO_TRADE") else (lo, mid)
    rc_stop = math.ceil(RECHECK_ENTRY * (1 - lo) / 10) * 10              # 10단위 올림(위험이 3%를 넘지 않게)
    rc = A1S.plan_trade(E, 0.02, RECHECK_ENTRY, rc_stop, "long", target=p["t2"], hold_hours=12)
    return dict(qty=t2.qty, notional=t2.notional, loss=t2.loss_at_stop, loss_krw=t2.loss_at_stop * k,
                risk=t2.risk_frac, cap=A1S.MAX_FORCED_RISK, cap_krw=E * A1S.MAX_FORCED_RISK * k,
                over=t2.risk_frac / A1S.MAX_FORCED_RISK, eff_lev=t2.eff_leverage, r1=r1, r2=r2,
                risk_ok=risk_ok, rr_ok=rr_ok, tradeable=(not t2.verdict.startswith("NO_TRADE")) and rr_ok,
                verdict=t2.verdict, lev=would.lev, lev_min=would.lev_min, margin=would.margin,
                margin_krw=would.margin * k, liq=would.liq_price, liq_dist=would.liq_distance, d_stop=t2.d_stop,
                rc_dist=lo, rc_stop=rc_stop, rc_risk=rc.risk_frac, rc_r2=rc.gain_at_target / rc.loss_at_stop,
                rc_lev=rc.lev, equity=E, krw=k, min_notional=A1C.BTC_MIN_NOTIONAL_NOW, step=A1C.BTC_STEP,
                entry_limit=A1S.entry_limit_for_cap(E, p["stop"], "long"))


# ------------------------------------------------------------------ 데이터
def load(tf: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"BTCUSDT_{tf}.csv.gz", usecols=["open_time", "open", "high", "low", "close", "volume"])
    df["t"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul")
    df = df[df["t"] + pd.Timedelta(tf) <= ASOF].reset_index(drop=True)   # 미래 정보 금지: 마감된 봉만
    df["vavg"] = df["volume"].shift(1).rolling(20).mean()               # 직전 20봉 평균(현재 봉 제외)
    df["vr"] = df["volume"] / df["vavg"]
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    return df


# ------------------------------------------------------------------ 글자 폭·배지
_T2P = TextToPath()
WARN = []                                               # 칸에 안 들어가 줄인 글 목록


def tw(s: str, size: float, weight: str = "normal") -> float:
    """글자 폭(pt)."""
    if not s:
        return 0.0
    w, _, _ = _T2P.get_text_width_height_descent(s, FontProperties(family="Pretendard", size=size, weight=weight),
                                                  ismath=False)
    return w


def fit(s: str, size: float, maxw: float, weight: str = "normal", floor: float = 5.6) -> float:
    """한 줄 글이 maxw(pt)에 들어가도록 글자 크기를 줄인다(줄이면 기록)."""
    z = size
    while tw(s, z, weight) > maxw and z > floor:
        z -= 0.1
    if z < size - 0.05:
        WARN.append(f"줄임 {size}->{z:.1f}pt: {s[:26]}")
    return z


BADGE = {"CP": dict(marker="o", d=10.6, fc=INK, ec=SURFACE, lw=0.9, tc="white", fs=6.4),
         "WY": dict(marker="s", d=9.4, fc=WY_C, ec=SURFACE, lw=0.9, tc="white", fs=6.4),
         "CL": dict(marker="D", d=7.5, fc="white", ec=INK, lw=1.05, tc=INK, fs=5.9)}
VIEW_NAME = {"CP": "차트프로", "WY": "워뇨띠", "CL": "Claude 종합"}
REG = {"badges": [], "candles": []}                    # 겹침 검사용 등록부


def vis_w(view: str, sc: float = 1.0) -> float:
    """배지의 눈에 보이는 폭(pt). 다이아몬드는 대각선이 폭."""
    b = BADGE[view]
    return b["d"] * sc * (1.414 if b["marker"] == "D" else 1.0)


def badge(ax, x, y, view, txt="", sc=1.0, transform=None, z=30, tag=None):
    """관점 배지: 차트프로 = 검은 원, 워뇨띠 = 초록 네모, Claude = 흰 다이아몬드(색 + 모양 + 번호)."""
    b = BADGE[view]
    tr = transform if transform is not None else ax.transData
    ax.scatter([x], [y], s=(b["d"] * sc) ** 2, marker=b["marker"], facecolors=b["fc"], edgecolors=b["ec"],
               linewidths=b["lw"] * sc, transform=tr, zorder=z, clip_on=False)
    if txt:
        t = ax.text(x, y, txt, transform=tr, ha="center", va="center_baseline", fontsize=b["fs"] * sc,
                    fontweight="bold", color=b["tc"], zorder=z + 1, clip_on=False)
        t.set_gid("badge-num")
    REG["badges"].append((ax, x, y, tr, vis_w(view, sc), tag or f"{view}{txt}"))


def off(ax, dx=0.0, dy=0.0):
    return mtrans.offset_copy(ax.transData, fig=ax.figure, x=dx, y=dy, units="points")


# ------------------------------------------------------------------ 캔버스(pt 좌표, 위→아래)
class Canvas:
    def __init__(self, W: float, H: float, dpi: int):
        self.W, self.H = W, H
        self.fig = plt.figure(figsize=(W / 72, H / 72), dpi=dpi, facecolor=SURFACE)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, W)
        self.ax.set_ylim(H, 0)
        self.ax.axis("off")

    def text(self, x, y, s, size=8.0, color=INK, weight="normal", ha="left", va="top", **kw):
        return self.ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va, **kw)

    def box(self, x, y, w, h, fc=PAPER, ec="none", lw=0.0, r=6.0, z=1):
        p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw,
                           zorder=z, mutation_aspect=1)
        self.ax.add_patch(p)
        return p

    def hline(self, x0, x1, y, color=HAIR, lw=0.6):
        self.ax.plot([x0, x1], [y, y], color=color, lw=lw, solid_capstyle="butt", zorder=2)

    def rect_frac(self, x, y, w, h):
        """pt 사각형 → fig.add_axes 좌표."""
        return [x / self.W, 1 - (y + h) / self.H, w / self.W, h / self.H]

    def chip(self, x, y, s, size=6.8, fc=PILL, tc="white", pad=4.5, h=12.0):
        """작은 글자 칩. 오른쪽 끝 x를 돌려준다."""
        w = tw(s, size, "bold") + 2 * pad
        self.box(x, y, w, h, fc=fc, r=h / 2, z=3)
        self.text(x + w / 2, y + h / 2 + 0.3, s, size=size, color=tc, weight="bold", ha="center", va="center", zorder=4)
        return x + w

    def flow(self, x, y, width, tokens, lh, indent=0.0):
        """글자·배지 토큰을 폭에 맞춰 줄바꿈하며 배치한다. y = 첫 줄 기준선. 마지막 줄 기준선을 돌려준다.
        tokens: ("t", 글, 크기, 색, 굵기) / ("b", 관점, 번호)"""
        cx, cy = x, y
        for tok in tokens:
            if tok[0] == "b":
                bw = vis_w(tok[1], 0.92) + 2.4
                if cx + bw > x + width:
                    cx, cy = x + indent, cy + lh
                badge(self.ax, cx + bw / 2 - 1.2, cy - 2.7, tok[1], tok[2], sc=0.92, tag=f"list{tok[1]}{tok[2]}")
                cx += bw
                continue
            _, s, size, color, weight = tok
            sp = tw("가 나", size, weight) - tw("가나", size, weight)
            for word in s.split(" "):
                if not word:
                    continue
                w = tw(word, size, weight)
                if cx + w > x + width + 0.5 and cx > x + indent + 0.1:
                    cx, cy = x + indent, cy + lh
                self.ax.text(cx, cy, word, fontsize=size, color=color, fontweight=weight, ha="left", va="baseline")
                cx += w + sp
        return cy


# ------------------------------------------------------------------ 차트(4시간봉 + 참고 계획 + 번호 8개)
def draw_chart(cv: Canvas, rect_pt, d: pd.DataFrame, p: dict, marks: bool = True, sc: float = 1.0):
    x, y, w, h = rect_pt
    vol_h = h * 0.20
    gap = 3.0
    ax = cv.fig.add_axes(cv.rect_frac(x, y, w, h - vol_h - gap))
    axv = cv.fig.add_axes(cv.rect_frac(x, y + h - vol_h, w, vol_h), sharex=ax)
    n = len(d)
    xr = (-0.9, n + FUTURE - 0.4)
    for a in (ax, axv):
        a.set_facecolor(SURFACE)
        for s in a.spines.values():
            s.set_visible(False)
        a.tick_params(length=0, colors=MUTED, labelsize=6.4 * sc, pad=2)
        a.set_xlim(*xr)
    lo = min(d["low"].min(), p["stop"]) - 700
    hi = max(d["high"].max(), p["t2"]) + 420
    ax.set_ylim(lo, hi)
    ticks = list(range(int(math.ceil(lo / 1000) * 1000), int(hi) + 1, 1000))
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"{t // 1000}k" for t in ticks])
    for t in ticks:                                                    # 가는 실선 격자(점선 아님)
        ax.axhline(t, color=GRID, lw=0.5, zorder=0)
    days = [i for i, t in enumerate(d["t"]) if t.hour == 9]
    for i in days:
        for a in (ax, axv):
            a.axvline(i - 0.5, color=GRID, lw=0.5, zorder=0)
    lab_days = [i for i in days if d["t"][i].day % 2 == 0]
    axv.set_xticks([i - 0.5 for i in lab_days])
    axv.set_xticklabels([f"{d['t'][i].month}/{d['t'][i].day}" for i in lab_days])
    ax.tick_params(axis="x", labelbottom=False)
    axv.set_yticks([])
    # 참고 계획 영역(오른쪽 미래 칸): 이익 쪽 옅은 빨강, 손실 쪽 옅은 파랑, 진입 구간 회색
    fx0, fx1 = n - 0.5, n + FUTURE - 0.4
    ax.add_patch(Rectangle((fx0, p["entry_hi"]), fx1 - fx0, p["t2"] - p["entry_hi"], fc=UP, alpha=0.05, lw=0, zorder=1))
    ax.add_patch(Rectangle((fx0, p["stop"]), fx1 - fx0, p["entry_lo"] - p["stop"], fc=DOWN, alpha=0.06, lw=0, zorder=1))
    ax.add_patch(Rectangle((fx0, p["entry_lo"]), fx1 - fx0, p["entry_hi"] - p["entry_lo"], fc=INK, alpha=0.10,
                           ec="none", zorder=2))
    for v, c in ((p["t2"], UP), (p["t1"], UP), (p["stop"], DOWN)):
        ax.hlines(v, fx0, fx1, color=c, lw=1.2, zorder=4)
    for a in (ax, axv):                                                # '지금' 경계(점선 = 시간 경계)
        a.axvline(fx0, color=INK2, lw=0.6, ls=(0, (1.5, 1.5)), zorder=3)
    ax.text((fx0 + fx1) / 2, (p["t2"] + p["t1"]) / 2, "참고 계획\n(지금은 진입 불가)", fontsize=6.0 * sc, color=INK2,
            ha="center", va="center", linespacing=1.2, zorder=8)
    # 캔들(한국식 색)
    bw = 0.62
    for i, r in d.iterrows():
        col = UP if r["close"] >= r["open"] else DOWN
        ax.vlines(i, r["low"], r["high"], color=col, lw=0.65, zorder=5)
        b0, b1 = sorted((r["open"], r["close"]))
        ax.add_patch(Rectangle((i - bw / 2, b0), bw, max(b1 - b0, 18), fc=col, ec=col, lw=0.3, zorder=5))
        REG["candles"].append((ax, i, r["low"], r["high"]))
    for m, c in (("ma20", "#bdbcb6"), ("ma60", "#8f8e88")):
        ax.plot(np.arange(n), d[m], color=c, lw=0.8, zorder=3, solid_capstyle="round")
    # 거래량
    vcol = [UP if cc >= oo else DOWN for oo, cc in zip(d["open"], d["close"])]
    spike = (d["vr"] >= 2).to_numpy()
    bars = axv.bar(np.arange(n), d["volume"], width=bw, color=vcol, zorder=3)
    for bar, s in zip(bars, spike):
        bar.set_alpha(1.0 if s else 0.32)
    axv.plot(np.arange(n), d["vavg"], color=INK2, lw=0.6, zorder=4)
    vmax = d["volume"].max()
    axv.set_ylim(0, vmax * 1.12)
    axv.text(28.6, vmax * 1.04, "거래량 · 진한 막대 = 평균의 2배 이상", fontsize=5.9 * sc, color=INK2, va="top",
             ha="left", zorder=6)                                      # 급증 막대를 가리지 않는 자리(9/24~9/28)
    axv.text(n + 0.2, vmax * 0.92, "지금 09:00", fontsize=6.4 * sc, color=INK, fontweight="bold", va="top", ha="left")
    axv.text(n + 0.2, vmax * 0.50, "다음 판정 13:00\n(4시간봉 마감)", fontsize=5.9 * sc, color=INK2, va="top",
             ha="left", linespacing=1.15)
    # 계획 글(오른쪽 끝 정렬) + 지금 가격
    lx = fx1 - 0.35
    for v, s in ((p["t2"], f"목표2 {p['t2'] / 1000:.1f}k"), (p["t1"], f"목표1 {p['t1'] / 1000:.1f}k")):
        ax.text(lx, v, s, transform=off(ax, 0, 1.6), fontsize=6.7 * sc, color=INK, fontweight="semibold",
                ha="right", va="bottom", zorder=8)
    ax.text(lx, p["stop"], f"손절 {p['stop'] / 1000:.1f}k", transform=off(ax, 0, -1.6), fontsize=6.7 * sc,
            color=INK, fontweight="semibold", ha="right", va="top", zorder=8)
    ax.text(lx, (p["entry_lo"] + p["entry_hi"]) / 2, "진입 구간", fontsize=6.4 * sc, color=INK,
            fontweight="semibold", ha="right", va="center", zorder=8)
    badge(ax, fx0 + 1.5, (p["entry_lo"] + p["entry_hi"]) / 2, "CL", "", sc=0.9 * sc, tag="plan-diamond")
    c = float(d["close"].iloc[-1])
    ax.hlines(c, n - 1, fx0 + 2.6, color=INK, lw=0.6, ls=(0, (1, 1.2)), zorder=6)
    ax.scatter([n - 1], [c], s=9 * sc, color=INK, zorder=9, edgecolors=SURFACE, linewidths=0.6)
    ax.text(fx0 + 2.9, c, f"지금 {c:,.0f}", fontsize=6.4 * sc, color=INK, fontweight="bold", ha="left",
            va="center", zorder=8)
    if not marks:
        return ax, axv
    # ---------- 번호 표시 8개: 차트프로 ●1~5 · 워뇨띠 ■6~7 · Claude ◇8
    idx = {t.strftime("%m-%d %H"): i for i, t in enumerate(d["t"])}
    ax.hlines(p["box_top"], -0.9, fx0, color=INK, lw=0.75, ls=(0, (3.5, 2.2)), zorder=4)   # ② 기준선(점선 = 문턱)
    w0, w1 = p["waist"]
    ax.add_patch(Rectangle((-0.9, w0), fx0 + 0.9, w1 - w0, fc=INK, alpha=0.07, lw=0, zorder=1))   # ③ 허리 띠
    for key, (z0, z1) in (("09-25 09", p["wick"]), ("09-24 17", p["sup"])):                 # ⑥⑦ 워뇨띠 구간
        xs = idx[key] - 0.5
        ax.add_patch(Rectangle((xs, z0), fx0 - xs, z1 - z0, fc=WY_FILL, alpha=0.11, lw=0, zorder=2))
        ax.add_patch(Rectangle((xs, z0), fx0 - xs, z1 - z0, fc="none", ec=WY_EDGE, alpha=0.55, lw=0.5, zorder=2))
    hs = [idx[k] for k in ("09-25 17", "09-27 21", "09-29 01")]                                # ④ 낮아지는 고점
    hv = [d["high"][i] for i in hs]
    ax.plot(hs, [v + 90 for v in hv], color=INK, lw=0.7, ls=(0, (1, 1.4)), zorder=6)
    ax.scatter(hs, hv, s=10, marker="v", color=INK, zorder=7, transform=off(ax, 0, 3.2))

    def tag(xv, yv, s, dx, dy, ha):
        ax.text(xv, yv, s, transform=off(ax, dx, dy), fontsize=6.3 * sc, color=INK2, ha=ha, va="center",
                zorder=9, bbox=dict(boxstyle="round,pad=0.12", fc=SURFACE, ec="none", alpha=0.85))

    def arrow_at(i):
        ax.scatter([i], [d["low"][i]], s=9, marker="^", color=INK, zorder=7, transform=off(ax, 0, -3.4))

    i1 = idx["09-21 17"]                                                                       # ① 기준봉 후보
    badge(ax, i1 - 2.4, 84_150, "CP", "1", sc=sc, tag="m1")
    ax.annotate("", xy=(i1 - 0.42, 83_550), xytext=(i1 - 1.75, 83_980),
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6), zorder=6)
    tag(i1 - 2.4, 84_150, "기준봉 후보", -7.5, 0, "right")
    badge(ax, 21, p["box_top"], "CP", "2", sc=sc, tag="m2")                                   # ② 옛 박스 상단
    tag(21, p["box_top"], "옛 박스 상단", 7.0, -7.0, "left")
    badge(ax, 27.5, (w0 + w1) / 2, "CP", "3", sc=sc, tag="m3")                                # ③ 허리
    tag(27.5, (w0 + w1) / 2, "허리(근사)", 7.0, 0, "left")
    badge(ax, hs[1], hv[1], "CP", "4", sc=sc, transform=off(ax, 0, 16.0), tag="m4")           # ④
    tag(hs[1], hv[1], "고점 낮아짐", -7.0, 16.0, "right")
    i5a, i5b = idx["09-23 21"], idx["09-28 09"]                                                # ⑤ 거래 터진 음봉
    arrow_at(i5a)
    badge(ax, i5a, d["low"][i5a], "CP", "5", sc=sc, transform=off(ax, 0, -14.0), tag="m5a")
    tag(i5a, d["low"][i5a], "거래 터진 음봉", -6.6, -14.0, "right")
    arrow_at(i5b)
    badge(ax, i5b, d["low"][i5b], "CP", "5", sc=sc, transform=off(ax, -8.0, -11.0), tag="m5b")
    badge(ax, idx["09-29 01"] - 2.0, sum(p["wick"]) / 2, "WY", "6", sc=sc, tag="m6")          # ⑥ 윗꼬리 몰림
    badge(ax, idx["09-24 17"] + 2.5, sum(p["sup"]) / 2, "WY", "7", sc=sc, tag="m7")           # ⑦ 받침
    tag(idx["09-24 17"] + 2.5, sum(p["sup"]) / 2, "받침", 7.0, 0, "left")
    i8 = idx["09-20 09"]                                                                       # ⑧ 9/20 저점
    arrow_at(i8)
    badge(ax, i8, p["low_0920"], "CL", "8", sc=sc, transform=off(ax, 0, -12.5), tag="m8")
    tag(i8, p["low_0920"], "9/20 저점 80.1k", 7.5, -12.5, "left")
    return ax, axv


# ------------------------------------------------------------------ 공통 조각
def fmt(v: float) -> str:
    return f"{v:,.0f}"


def legend_row(cv: Canvas, x, y, width, sc=1.0):
    cx = x
    for view, nm in (("CP", "차트프로 1~5"), ("WY", "워뇨띠 6·7"), ("CL", "Claude 8·계획")):
        bwid = vis_w(view, 0.8 * sc)
        badge(cv.ax, cx + bwid / 2, y - 2.6, view, "", sc=0.8 * sc, tag=f"legend{view}")
        cv.text(cx + bwid + 3, y, nm, size=6.9 * sc, color=INK2, va="baseline")
        cx += bwid + 3 + tw(nm, 6.9 * sc) + 8
    s = "빨강 양봉 · 파랑 음봉 · 회색 선 20·60 이평"
    cv.text(x + width, y, s, size=fit(s, 6.3 * sc, x + width - cx), color=MUTED, va="baseline", ha="right")


def views_strip(cv: Canvas, x, y, width, size=7.2):
    """세 관점 한 줄 요약(모양 + 이름 + 판단). y = 기준선."""
    parts = []
    for view, nm, verdict in VIEWS_ONE_LINE:
        parts.append((view, nm, verdict, vis_w(view, 0.8) + 3 + tw(nm, size, "semibold") + 4 + tw(verdict, size)))
    gapw = (width - sum(p_[3] for p_ in parts)) / (len(parts) - 1)
    cx = x
    for k, (view, nm, verdict, wd) in enumerate(parts):
        bwid = vis_w(view, 0.8)
        badge(cv.ax, cx + bwid / 2, y - 2.6, view, "", sc=0.8, tag=f"strip{view}")
        cv.text(cx + bwid + 3, y, nm, size=size, weight="semibold", va="baseline")
        cv.text(cx + bwid + 3 + tw(nm, size, "semibold") + 4, y, verdict, size=size, color=INK2, va="baseline")
        if k < len(parts) - 1:
            sx = cx + wd + gapw / 2
            cv.ax.plot([sx, sx], [y - 7.5, y + 1.5], color=HAIR, lw=0.7)
        cx += wd + gapw


def risk_icon(cv: Canvas, x, y, s=10.0):
    cv.ax.add_patch(Polygon([[x, y + s * 0.9], [x + s / 2, y], [x + s, y + s * 0.9]], closed=True, fc=WARN_ICON,
                            ec=WARN_ICON, lw=0.8, joinstyle="round", zorder=3))
    cv.text(x + s / 2, y + s * 0.62, "!", size=s * 0.62, color="white", weight="bold", ha="center", va="center",
            zorder=4)


def info_icon(cv: Canvas, x, y, s=10.0):
    cv.ax.add_patch(Circle((x + s / 2, y + s / 2), s / 2, fc=INK2, ec="none", zorder=3))
    cv.text(x + s / 2, y + s / 2 + 0.4, "i", size=s * 0.68, color="white", weight="bold", ha="center", va="center",
            zorder=4)


def check_texts(sz: dict) -> dict:
    """검사기 결과와 재검토 조건 문구(페이지·미리보기 공용)."""
    bad = []
    if not sz["rr_ok"]:
        bad.append(f"손익비 {sz['r2']:.1f}(<{RR_MIN:.0f})")
    if not sz["risk_ok"]:
        bad.append(f"손실 {sz['risk'] * 100:.1f}%(>{sz['cap'] * 100:.0f}%)")
    head = ("지금 조건으로는 진입 불가: " + " · ".join(bad)) if bad else "검사기 통과: 진입 검토 가능"
    rule = (f"검사기 기준(5만 원 단계): 1회 위험 ≤ {sz['cap'] * 100:.0f}% · 손익비(목표2, 수수료·슬리피지·펀딩 뺀 값)"
            f" ≥ {RR_MIN:.0f}")
    recheck = (f"재검토: 82.3k 부근에서 손절 폭 약 {sz['rc_dist'] * 100:.1f}% 이내로 잡히는 1시간봉 반등 자리가 생기면"
               f"({fmt(RECHECK_ENTRY)} 진입이면 손절 {fmt(sz['rc_stop'])} 이상) 다시 계산")
    return dict(head=head, rule=rule, recheck=recheck)


# ------------------------------------------------------------------ 페이지(정식 보고서)
def page(path_pdf, path_png, d: pd.DataFrame, sz: dict, H: float = 1200.0, dpi: int = 240) -> float:
    p = PLAN
    W, M = 324.0, 12.0
    CW = W - 2 * M
    cv = Canvas(W, H, dpi)
    c = float(d["close"].iloc[-1])
    ct = check_texts(sz)
    y = 11.0
    # 머리말
    cv.text(M, y, "BTCUSDT 무기한 선물 · 정식 보고서", size=7.3, color=MUTED)
    cv.text(M, y + 10.5, "2026-09-29 (화) 09:00 KST", size=10.8, weight="bold")
    cv.text(W - M, y, "현재가(4시간봉 종가)", size=7.3, color=MUTED, ha="right")
    cv.text(W - M, y + 9.5, fmt(c), size=13.8, weight="bold", ha="right")
    y += 29
    pill = "과거 데이터 샘플 · 투자 권유 아님 · 주문은 본인이 직접"
    cv.box(M, y, tw(pill, 6.8) + 12, 13, fc="none", ec=WARN_ICON, lw=0.7, r=6.5)
    cv.text(M + 6, y + 6.6, pill, size=6.8, color=WARN_INK, va="center")
    y += 19
    # 결론 카드
    ch = 70.0
    cv.box(M, y, CW, ch, fc=PAPER, r=8)
    cv.box(M + 8, y + 9, 46, 27, fc=PILL, r=6)
    cv.text(M + 31, y + 22.6, "관망", size=15.5, color="white", weight="bold", ha="center", va="center")
    hx = M + 62
    cv.text(hx, y + 8.5, "지금은 진입하지 않음", size=12.6, weight="bold")
    s = "지지 82.3k와 저항 84.0k 한가운데라 손익비가 나쁨"
    cv.text(hx, y + 26.5, s, size=fit(s, 7.6, W - M - 8 - hx - 40), color=INK2)
    rx = W - M - 8
    cv.text(rx, y + 8.5, "신뢰도", size=6.8, color=MUTED, ha="right")
    for k in range(3):
        cv.box(rx - 34 + k * 12, y + 19, 10, 4, fc=(INK if k == 0 else HAIR), r=2)
    cv.text(rx, y + 26.5, "낮음", size=8.8, weight="semibold", ha="right")
    cv.hline(M + 8, W - M - 8, y + 45.5, color=HAIR)
    views_strip(cv, M + 9, y + 60.0, CW - 18, size=7.3)
    y += ch + 5
    # 검증 상태(결론 카드 바로 아래)
    vh = 29.0
    cv.box(M, y, CW, vh, fc="none", ec=HAIR, lw=0.8, r=6)
    info_icon(cv, M + 8, y + 6.5, 9.5)
    toks = [("t", "검증 상태", 7.0, INK, "bold"),
            ("t", "이 진입 방식은 과거 검증에서 우위가 확인되지 않음(차트프로 진입 조건 OOS 합격 0개) → "
                  "지금은 모의 기록 단계", 7.0, INK2, "normal")]
    last = cv.flow(M + 23, y + 12.2, CW - 31, toks, lh=9.0)
    assert last + 5 <= y + vh, "검증 상태 글이 넘침"
    y += vh + 9
    # 참고 계획: 검사기 결과를 먼저
    cv.text(M, y, "참고 계획 · 조건부 롱", size=7.8, color=INK2, weight="semibold")
    cv.text(W - M, y + 0.6, f"수량 계산은 {fmt(p['entry'])} 진입 가정", size=6.6, color=MUTED, ha="right")
    y += 13
    kh = 55.0
    cv.box(M, y, CW, kh, fc=CHECK_BG, r=6)
    xe = cv.chip(M + 8, y + 6.5, "검사기", size=6.6)
    cv.text(xe + 6, y + 12.8, ct["head"], size=fit(ct["head"], 8.8, W - M - 8 - xe - 6, "bold"), weight="bold",
            va="center")
    cv.text(M + 8, y + 22.5, ct["rule"], size=fit(ct["rule"], 6.5, CW - 16), color=INK2)
    last = cv.flow(M + 8, y + 37.0, CW - 16, [("t", ct["recheck"], 6.7, INK, "normal")], lh=8.6)
    assert last + 4 <= y + kh, "검사기 칸 글이 넘침"
    y += kh + 6
    tiles = [("진입 구간", f"{fmt(p['entry_lo'])} ~ {fmt(p['entry_hi'])}", "4시간봉 반등 양봉 + 거래 증가로 마감 시", INK2),
             ("손절", fmt(p["stop"]), f"−{(1 - p['stop'] / p['entry']) * 100:.1f}% · 9/20 저점 80.1k 아래", DOWN),
             ("목표 1", fmt(p["t1"]), f"+{(p['t1'] / p['entry'] - 1) * 100:.1f}% · 손익비 {sz['r1']:.1f} · 닿으면 손절을 본전으로", UP),
             ("목표 2", fmt(p["t2"]), f"+{(p['t2'] / p['entry'] - 1) * 100:.1f}% · 손익비 {sz['r2']:.1f} · 전고 87.4k 아래", UP)]
    tw_, th, g = (CW - 6) / 2, 40.0, 6.0
    for k, (lab, val, note, col) in enumerate(tiles):
        tx = M + (k % 2) * (tw_ + g)
        ty = y + (k // 2) * (th + g)
        cv.box(tx, ty, tw_, th, fc=PAPER, r=6)
        cv.box(tx, ty, 3.2, th, fc=col, r=1.6, z=2)
        cv.text(tx + 10, ty + 5.5, lab, size=7.1, color=INK2)
        cv.text(tx + 10, ty + 14.0, val, size=12.6, weight="bold")
        cv.text(tx + 10, ty + 29.5, note, size=fit(note, 6.8, tw_ - 15), color=INK2)
    y += 2 * th + g + 6
    # 수량·레버리지(a1_sizing) — 진입 불가라도 "이 계획대로라면"을 참고로
    bh = 58.0
    cv.box(M, y, CW, bh, fc=PAPER, r=6)
    cells = [("수량(최소 단위)", f"{sz['qty']:.3f} BTC"), ("레버리지(규칙)", f"{sz['lev']}배 격리"),
             ("증거금", f"{sz['margin']:.2f} USDT"), ("청산가(추정)", f"≈ {round(sz['liq'], -2):,.0f}")]
    cw = CW / 4
    for k, (lab, val) in enumerate(cells):
        cx = M + k * cw
        if k:
            cv.ax.plot([cx, cx], [y + 7, y + 26], color=HAIR, lw=0.6)
        cv.text(cx + 8, y + 6.5, lab, size=fit(lab, 6.6, cw - 10), color=INK2)
        cv.text(cx + 8, y + 15.5, val, size=fit(val, 9.9, cw - 11, "bold"), weight="bold")
    note = [("t", "레버리지는 증거금 크기일 뿐, 잃는 돈은 손절이 정함", 6.7, INK, "semibold"),
            ("t", f"(3배든 {sz['lev']}배든 손절 시 약 {round(sz['loss_krw'], -2):,.0f}원). 규칙: 격리, 청산 거리 ≥ "
                  f"max(손절 거리×2, 손절 거리+3%p)를 지키는 가장 높은 배수, 상한 20배 → 청산가는 손절 거리의 "
                  f"{sz['liq_dist'] / sz['d_stop']:.1f}배 밖.", 6.5, INK2, "normal")]
    last = cv.flow(M + 8, y + 37.5, CW - 16, note, lh=8.4)
    assert last + 4 <= y + bh, "수량 칸 글이 넘침"
    y += bh + 6
    # 위험 띠(잃을 수 있는 돈)
    rh = 45.0
    cv.box(M, y, CW, rh, fc=WARN_BG, r=6)
    risk_icon(cv, M + 8, y + 8.0, 11)
    cv.text(M + 25, y + 7.0, f"손절 시 잃는 돈 약 {round(sz['loss_krw'], -2):,.0f}원 (계좌의 {sz['risk'] * 100:.1f}%)",
            size=9.6, weight="bold")
    small = [("t", f"이 단계 상한 {sz['cap'] * 100:.0f}%(약 {round(sz['cap_krw'], -2):,.0f}원)의 {sz['over']:.1f}배. "
                   f"최소 수량 {sz['qty']:.3f} BTC라 더 못 줄임. 실질 레버리지 {sz['eff_lev']:.1f}배(워뇨띠 기준 "
                   f"2배 초과). 손절 주문 없이 청산되면 최대 약 {round(sz['margin_krw'], -2):,.0f}원(증거금).",
              6.8, WARN_INK, "normal")]
    last = cv.flow(M + 25, y + 26.0, CW - 32, small, lh=8.8)
    assert last + 6 <= y + rh, "위험 띠 글이 넘침"
    y += rh + 7
    # 무효화·유효
    for lab, s in (("무효화", "4시간봉이 거래 늘며 82,300 아래로 마감하면 계획 취소"),
                   ("유효", "9/30 09:00까지 · 다음 판정 13:00(4시간봉 마감)")):
        cv.text(M, y + 6.7, lab, size=7.1, color=INK2, weight="semibold", va="baseline")
        last = cv.flow(M + 34, y + 6.7, CW - 34, [("t", s, 7.5, INK, "normal")], lh=9.4)
        y = last + 6.6
    y += 4
    cv.hline(M, W - M, y)
    y += 9
    # 차트
    cv.text(M, y, f"4시간봉 {len(d)}개(9/19~9/29) · 세 관점 번호 + 참고 계획", size=8.2, weight="semibold")
    y += 13.5
    legend_row(cv, M, y + 6.5, CW)
    y += 12
    ch_h = 210.0
    draw_chart(cv, (M + 16, y, CW - 16, ch_h), d, p, marks=True)
    y += ch_h + 15
    cv.hline(M, W - M, y)
    y += 9
    # 세 관점(각 3줄 + 근거 규칙 번호)
    views = [
        ("CP", "매수 관점 · 아직 살 자리 아님", "", [
            (["1", "2"], "9/21 기준봉 후보 뒤 첫 눌림, 옛 박스 상단 82.3k 위 → 매수만 본다", "CP-10-2 · CP-07-6"),
            (["3"], "허리 80.8~81.1k(근사) 위라 매도는 보지 않음", "CP-05-3 · CP-06-1"),
            (["4", "5"], "고점이 낮아지고 눌림에 거래 터진 음봉 → 반등 양봉까지 기다림", "CP-14-2 · CP-01-5 · CP-11-3")]),
        ("WY", "모르는 구간 · 관망", "공개 발언으로 재구성한 관점", [
            ([], "닮은꼴 결과가 갈림 → 방향을 고르지 않음", "WY-04-3 · WY-07-1"),
            (["6"], "윗꼬리 몰린 84.9~85.2k를 못 되찾음 → 약세 쪽(약한 신호)", "WY-05-2"),
            (["7"], "82.5~83.1k에서 여러 번 받침 → 받쳐 주는지부터 본다", "WY-06-2")]),
        ("CL", "관망 · 진입 불가 · 모의 기록만", "두 관점 종합", [
            ([], "지금 83.5k는 목표까지 3.5k < 손절까지 3.7k. 숏도 안 봄(9월 마디 살아 있음)",
             "CP-25-3 · CP-05-3"),
            (["8"], "손절은 허리 바로 아래가 아니라 9/20 저점 80.1k 아래 79.8k", "CP-17-7 · CP-07-4"),
            ([], "이 손절로는 검사기 미달 → 손절을 당기지 않고, 자리가 올 때까지 모의 기록만 남김", "CP-17-6")]),
    ]
    for view, verdict, sub, lines in views:
        badge(cv.ax, M + vis_w(view) / 2, y + 5.2, view, "", sc=1.0, tag=f"head{view}")
        cv.text(M + 14, y + 8.6, VIEW_NAME[view], size=8.8, weight="bold", va="baseline")
        nx = M + 14 + tw(VIEW_NAME[view], 8.8, "bold") + 6
        cv.text(nx, y + 8.6, verdict, size=8.0, weight="semibold", va="baseline")
        if sub:
            cv.text(W - M, y + 8.6, sub, size=6.2, color=MUTED, va="baseline", ha="right")
        y += 20.0
        for nums, s, rules in lines:
            toks = [("b", view, n_) for n_ in nums] or [("t", "·", 7.6, MUTED, "bold")]
            toks += [("t", s, 7.5, INK, "normal"), ("t", f"[{rules}]", 6.2, MUTED, "normal")]
            last = cv.flow(M + 6, y, CW - 6, toks, lh=9.6, indent=12)
            y = last + 11.2
        y += 4.0
    y += 1
    cv.hline(M, W - M, y)
    y += 8
    foot1 = [("t", "데이터: 바이낸스 BTCUSDT 무기한 4시간봉, 2026-09-29 09:00 KST 마감분까지. 과거 데이터 샘플이며 "
                   "투자 권유가 아님. 이 진입 방식은 과거 검증에서 우위가 확인되지 않음(모의 기록 단계).", 6.2, MUTED,
              "normal")]
    foot2 = [("t", f"가정: 1 USDT = {sz['krw']:,.0f}원, 계좌 {sz['equity']:.1f} USDT(5만 원), 진입 {fmt(p['entry'])}, "
                   f"최소 주문 {sz['min_notional']:.0f} USDT(2026-04-14부터)·수량 단위 {sz['step']:.3f} BTC, "
                   "수수료 0.05%+슬리피지 0.02%/편(목표는 지정가 0.02%), 펀딩 0.01%/8시간·36시간 보유, "
                   "유지증거금률 0.4%. 계산은 퀀트① a1_sizing.py. 실제 값은 거래소(exchangeInfo)에서 확인.",
              6.2, MUTED, "normal")]
    last = cv.flow(M, y + 6, CW, foot1, lh=8.2)
    last = cv.flow(M, last + 9.0, CW, foot2, lh=8.2)
    used = last + 9
    if path_pdf is not None:
        cv.fig.savefig(path_pdf, facecolor=SURFACE, metadata={"Title": "BTCUSDT 보고서 시안 2026-09-29 09:00 KST"})
        cv.fig.savefig(path_png, facecolor=SURFACE, dpi=dpi)
        report_overlaps(cv.fig, "page")
    plt.close(cv.fig)
    return used


# ------------------------------------------------------------------ 텔레그램 미리보기(사진, 1080x1350)
def preview(path_png, d: pd.DataFrame, sz: dict):
    p = PLAN
    W, H, M = 324.0, 405.0, 14.0
    CW = W - 2 * M
    cv = Canvas(W, H, 240)
    c = float(d["close"].iloc[-1])
    ct = check_texts(sz)
    y = 13.0
    cv.text(M, y, "BTCUSDT · 9/29(화) 09:00 KST", size=9.0, weight="semibold", color=INK2)
    cv.text(W - M, y + 0.5, "샘플 · 투자 권유 아님", size=7.6, color=WARN_INK, ha="right")
    y += 17
    cv.box(M, y, 64, 34, fc=PILL, r=7)
    cv.text(M + 32, y + 17.5, "관망", size=20, color="white", weight="bold", ha="center", va="center")
    cv.text(M + 74, y + 1.0, "지금은 매매 안 함", size=15.5, weight="bold")
    cv.text(M + 74, y + 21.0, f"지금 {fmt(c)} · 신뢰도 낮음", size=8.9, color=INK2)
    y += 43
    views_strip(cv, M + 2, y + 7.5, CW - 4, size=7.6)
    y += 15
    # 검사기 결과 + 재검토
    kh = 41.0
    cv.box(M, y, CW, kh, fc=CHECK_BG, r=6)
    xe = cv.chip(M + 7, y + 6.0, "검사기", size=6.9, h=12.5)
    head = f"진입 불가 · 손익비 {sz['r2']:.1f}(<{RR_MIN:.0f}) · 손절 시 −{round(sz['loss_krw'], -2):,.0f}원 = {sz['risk'] * 100:.1f}%(>{sz['cap'] * 100:.0f}%)"
    cv.text(xe + 5, y + 12.6, head, size=fit(head, 8.6, W - M - 6 - xe - 5, "bold"), weight="bold", va="center")
    rc = f"재검토: 82.3k 부근 1시간봉 자리에서 손절 폭 {sz['rc_dist'] * 100:.1f}% 이내면 다시 계산"
    cv.text(M + 7, y + 30.0, rc, size=fit(rc, 7.6, CW - 14), color=INK, va="center")
    y += kh + 5
    vs = "검증 상태: 이 진입 방식은 우위 미확인(OOS 합격 0개) → 모의 기록 단계"
    info_icon(cv, M + 1, y + 1.5, 9)
    cv.text(M + 14, y + 6.2, vs, size=fit(vs, 7.6, CW - 14), color=INK2, va="center")
    y += 17
    draw_chart(cv, (M + 14, y, CW - 14, H - y - 28), d, p, marks=False, sc=1.12)
    cv.text(M, H - 10, "진입 판정은 4시간봉 마감 때만 · 근거와 세 관점은 PDF", size=7.1, color=MUTED, va="baseline")
    cv.fig.savefig(path_png, facecolor=SURFACE, dpi=240)
    report_overlaps(cv.fig, "preview")
    plt.close(cv.fig)


# ------------------------------------------------------------------ 겹침 검사(글자·배지·캔들)
def report_overlaps(fig, name: str):
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    boxes = []
    for ax in fig.axes:
        for t in ax.texts:
            if t.get_gid() == "badge-num" or not t.get_text().strip():
                continue
            boxes.append(("T:" + t.get_text()[:14].replace("\n", " "), t.get_window_extent(r).expanded(1.0, 0.92), ax))
    px = fig.dpi / 72
    for ax, x, y, tr, wpt, tagname in REG["badges"]:
        if ax.figure is not fig:
            continue
        cx, cy = tr.transform((x, y))
        hh = wpt * px / 2
        boxes.append(("B:" + tagname, mtrans.Bbox([[cx - hh, cy - hh], [cx + hh, cy + hh]]), ax))
    bad = []
    for (a, ba, _), (b, bb, _) in itertools.combinations(boxes, 2):
        if ba.overlaps(bb):
            inter = mtrans.Bbox.intersection(ba, bb)
            if inter is not None and inter.width > 1.0 and inter.height > 1.0:
                bad.append(f"{a} <> {b}")
    for ax, i, lo, hi in REG["candles"]:                     # 글자·배지가 캔들(꼬리 포함)을 덮는지
        if ax.figure is not fig:
            continue
        (x0, y0), (x1, y1) = ax.transData.transform((i - 0.31, lo)), ax.transData.transform((i + 0.31, hi))
        cb = mtrans.Bbox([[x0, y0], [x1, y1]])
        for nm, bx, axx in boxes:
            if axx is ax and bx.overlaps(cb):
                inter = mtrans.Bbox.intersection(bx, cb)
                if inter is not None and inter.width > 0.5 and inter.height > 0.5:
                    bad.append(f"{nm} <> candle#{i}")
    fb = fig.bbox                                            # 그림 밖으로 잘린 글
    for nm, bx, _ in boxes:
        if bx.x0 < fb.x0 - 0.5 or bx.x1 > fb.x1 + 0.5 or bx.y0 < fb.y0 - 0.5 or bx.y1 > fb.y1 + 0.5:
            bad.append(f"{nm} <> 그림 밖")
    print(f"[{name}] 겹침·잘림 {len(bad)}건")
    for s in bad:
        print("   ", s)


def main():
    d = load("4h")
    d = d[d["t"] >= START].reset_index(drop=True)
    assert d["t"].iloc[-1] == pd.Timestamp("2026-09-29 05:00", tz="Asia/Seoul"), d["t"].iloc[-1]
    sz = sizing(PLAN)
    print("봉 수", len(d), "종가", d["close"].iloc[-1])
    print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in sz.items()})
    print(check_texts(sz))
    used = page(None, None, d, sz)                                  # 1차: 높이 재기
    REG["badges"].clear(), REG["candles"].clear(), WARN.clear()
    H = math.ceil(used)
    page(HERE / "mock_report.pdf", HERE / "mock_report_page.png", d, sz, H=H)
    REG["badges"].clear(), REG["candles"].clear()
    preview(HERE / "mock_preview.png", d, sz)
    print("페이지 크기(pt) 324 x", H, "→ 세로/가로", round(H / 324, 2))
    for s_ in WARN:
        print("  ", s_)


if __name__ == "__main__":
    main()
