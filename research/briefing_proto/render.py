"""차트 위 번호 표시(프로토타입): marks JSON을 받아 일봉·4시간봉 그림과 닮은꼴 그림을 만든다.

marks 종류: candle(봉 표시) / box(구간 상자) / level(가로선) / band(가격 띠) / zone(워뇨띠 눈대중 상자)
           / offchart(차트 밖 목표) / highs(고점 여러 개) / arrow(Claude 시나리오 화살표)
관점(view): CP 차트프로 = 검은 원, WY 워뇨띠 = 초록 네모, CL Claude 종합 = 빈 네모
"""
from __future__ import annotations

import json
import pathlib
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]      # 저장소 루트
MAS = (5, 20, 60, 120, 240)
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#1f1f1d", "#52514e", "#8a8984", "#e9e8e3"
UP, DOWN = "#d94a3d", "#3d6fd9"                       # 한국식: 양봉 빨강, 음봉 파랑
MA_GRAY = {5: "#c9c8c2", 20: "#a6a59f", 60: "#7f7e78", 120: "#5a5953", 240: "#2f2e2b"}
WY_FILL, WY_EDGE, WY_BADGE = "#1baf7a", "#138a60", "#0f7a55"
VIEW_NAME = {"CP": "차트프로", "WY": "워뇨띠", "CL": "Claude 종합"}


FONT_DIRS = (pathlib.Path.home() / ".chartpro_textbook_fonts",)   # 교재 만들 때 받은 프리텐다드(없으면 기본 글꼴)


def pick_font() -> None:
    for fd in FONT_DIRS:                                   # 프리텐다드(무료 OFL)가 있으면 우선
        for f in sorted(fd.glob("Pretendard-*.ttf")) if fd.is_dir() else ():
            font_manager.fontManager.addfont(str(f))
    names = {f.name for f in font_manager.fontManager.ttflist}
    for n in ("Pretendard", "AppleGothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic", "WenQuanYi Zen Hei"):
        if n in names:
            plt.rcParams["font.family"] = n
            break
    plt.rcParams["axes.unicode_minus"] = False


def load(tf: str) -> pd.DataFrame:
    df = pd.read_csv(REPO / f"data/binance/BTCUSDT_{tf}.csv.gz")
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul")
    df = df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    for n in MAS:
        df[f"ma{n}"] = df["close"].rolling(n).mean()
    df["vavg"] = df["volume"].shift(1).rolling(20).mean()
    return df


def key(t: pd.Timestamp, tf: str) -> str:
    return t.strftime("%Y-%m-%d") if tf == "1d" else t.strftime("%Y-%m-%d %H")


def badge(ax, x, y, no, view, dx=0, dy=0, size=10, leader=None):
    """번호 배지. view에 따라 모양·색이 다르다(색만으로 구분하지 않음)."""
    if view == "WY":
        box = dict(boxstyle="square,pad=0.28", fc=WY_BADGE, ec="white", lw=1.0)
        col = "white"
    elif view == "CL":
        box = dict(boxstyle="round,pad=0.28", fc="white", ec=INK, lw=1.3)
        col = INK
    else:
        box = dict(boxstyle="circle,pad=0.25", fc=INK, ec="white", lw=1.0)
        col = "white"
    ap = dict(arrowstyle="-", color=INK2, lw=0.8, shrinkA=0, shrinkB=2) if leader else None
    ax.annotate(str(no), xy=(x, y), xytext=(dx, dy), textcoords="offset points", ha="center", va="center",
                fontsize=size, fontweight="bold", color=col, bbox=box, arrowprops=ap, zorder=12,
                annotation_clip=False)


def label(ax, x, y, text, dx=0, dy=0, ha="left", size=10.5, color=INK, weight="normal"):
    ax.annotate(text, xy=(x, y), xytext=(dx, dy), textcoords="offset points", ha=ha, va="center",
                fontsize=size, color=color, fontweight=weight, zorder=12, annotation_clip=False,
                bbox=dict(boxstyle="round,pad=0.15", fc=SURFACE, ec="none", alpha=0.85))


def spread(ys: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """오른쪽 여백 라벨이 겹치지 않게 세로 위치를 벌린다."""
    order = np.argsort(ys)
    out = np.array(ys, dtype=float)
    prev = -np.inf
    for i in order:
        out[i] = max(out[i], prev + gap)
        prev = out[i]
    over = out[order[-1]] - hi
    if over > 0:
        out -= over
        prev = np.inf
        for i in order[::-1]:
            out[i] = min(out[i], prev - gap)
            prev = out[i]
    return [max(v, lo) for v in out]


def draw(df: pd.DataFrame, tf: str, start: str, marks: list[dict], path: pathlib.Path, title: str,
         right_bars: int, arrow_len: int = 0) -> None:
    pick_font()
    i0 = int(np.flatnonzero(df["time"].map(lambda t: key(t, tf)) >= start)[0])
    d = df.iloc[i0:].reset_index(drop=True)
    pos = {key(t, tf): i for i, t in enumerate(d["time"])}
    n = len(d)
    last = n - 1
    fig, (ax, axv) = plt.subplots(2, 1, figsize=(16, 10), dpi=100, sharex=True, facecolor=SURFACE,
                                  gridspec_kw={"height_ratios": [3.6, 1], "hspace": 0.03})
    for a in (ax, axv):
        a.set_facecolor(SURFACE)
        a.grid(color=GRID, lw=0.8)
        a.set_axisbelow(True)
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            a.spines[s].set_color("#c9c8c2")
        a.tick_params(colors=INK2, labelsize=10)
    w = 0.64
    yr = d["high"].max() - d["low"].min()
    for i, r in d.iterrows():
        col = UP if r["close"] >= r["open"] else DOWN
        ax.vlines(i, r["low"], r["high"], color=col, lw=0.9, zorder=3)
        lo, hi = sorted((r["open"], r["close"]))
        ax.add_patch(Rectangle((i - w / 2, lo), w, max(hi - lo, yr * 0.0012), fc=col, ec=col, lw=0.5, zorder=3))
    x = np.arange(n)
    for m in MAS:
        s = d[f"ma{m}"]
        if s.notna().any():
            ax.plot(x, s, color=MA_GRAY[m], lw=1.0 + 0.12 * MAS.index(m), zorder=2)
            ax.annotate(f"{m}", xy=(last, s.iloc[-1]), xytext=(5, 0), textcoords="offset points",
                        fontsize=8.5, color=INK2, va="center", annotation_clip=False, zorder=9,
                        bbox=dict(boxstyle="round,pad=0.1", fc=SURFACE, ec="none", alpha=0.9))
    # 가격 범위: 표시 대상 가격도 들어오게
    prices = [d["low"].min(), d["high"].max()]
    for mk in marks:
        if tf not in mk["tf"].split(","):
            continue
        for k in ("price", "lo", "hi", "to"):
            if k in mk and mk["kind"] != "offchart":
                prices.append(mk[k])
    ymin, ymax = min(prices), max(prices)
    pad = (ymax - ymin) * 0.06
    ax.set_ylim(ymin - pad * 1.6, ymax + pad * 1.4)
    ylo, yhi = ax.get_ylim()
    xr = last + right_bars
    ax.set_xlim(-1, xr)
    lab_x = last + arrow_len + 3.2                         # 오른쪽 여백 라벨 시작
    margin_items = []                                      # (y, anchor, no, view, text)
    keys = [key(t, tf) for t in d["time"]]

    def x_from(mk):                                        # 선 시작 위치(t0 없거나 창보다 앞이면 왼쪽 끝)
        t0 = mk.get("t0")
        if not t0:
            return -1
        for i, k in enumerate(keys):
            if k >= t0:
                return i - 0.5 if i > 0 else -1
        return -1
    for mk in marks:
        if tf not in mk["tf"].split(","):
            continue
        kind, no, view = mk["kind"], mk["no"], mk["view"]
        if kind == "level":
            ax.hlines(mk["price"], x_from(mk), lab_x - 0.4, color=INK, lw=1.0, ls=(0, (5, 3)), zorder=4)
            margin_items.append((mk["price"], mk["price"], no, view, mk["text"]))
        elif kind == "band":
            xs = x_from(mk)
            ax.add_patch(Rectangle((xs, mk["lo"]), lab_x - 0.4 - xs, mk["hi"] - mk["lo"], fc=INK, alpha=0.08, lw=0,
                                   zorder=1))
            for p in (mk["lo"], mk["hi"]):
                ax.hlines(p, xs, lab_x - 0.4, color=INK, lw=0.8, ls=(0, (2, 2)), zorder=4)
            mid = (mk["lo"] + mk["hi"]) / 2
            margin_items.append((mid, mid, no, view, mk["text"]))
        elif kind == "zone":
            xs = pos.get(mk.get("t0", ""), 0) - 0.5
            ax.add_patch(Rectangle((xs, mk["lo"]), lab_x - 0.4 - xs, mk["hi"] - mk["lo"], fc=WY_FILL, alpha=0.16,
                                   ec=WY_EDGE, lw=1.0, zorder=1))
            mid = (mk["lo"] + mk["hi"]) / 2
            margin_items.append((mid, mid, no, view, mk["text"]))
        elif kind == "box":
            xa, xb = pos[mk["t0"]] - 0.5, pos[mk["t1"]] + 0.5
            ax.add_patch(Rectangle((xa, mk["lo"]), xb - xa, mk["hi"] - mk["lo"], fc="none", ec=INK, lw=1.1,
                                   ls=(0, (4, 3)), zorder=4))
            badge(ax, xa, mk["hi"], no, view, dx=10, dy=14)
            label(ax, xa, mk["hi"], mk["text"], dx=22, dy=14)
        elif kind == "candle":
            idx = [pos[t] for t in mk["times"] if t in pos]
            above = mk.get("side", "above") == "above"
            for i in idx:
                r = d.iloc[i]
                yv = r["high"] if above else r["low"]
                ax.annotate("", xy=(i, yv), xytext=(0, 16 if above else -16), textcoords="offset points",
                            arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.1, mutation_scale=9), zorder=11)
            dy = 30 if above else -30
            if mk.get("group", False):                     # 여러 봉을 한 묶음으로: 가장 바깥 봉에 배지 하나
                ext = max(idx, key=lambda i: d["high"][i]) if above else min(idx, key=lambda i: d["low"][i])
                spots = [ext]
            else:                                          # 봉마다 배지, 글은 첫 봉에만
                spots = idx
            for j, i in enumerate(spots):
                yv = d["high"][i] if above else d["low"][i]
                badge(ax, i, yv, no, view, dy=dy, size=10 if j == 0 else 9)
                if j == 0:
                    ha = mk.get("ha", "right" if i > last * 0.72 else "left")
                    label(ax, i, yv, mk["text"], dx=(-13 if ha == "right" else 13), dy=dy, ha=ha)
        elif kind == "highs":
            idx = [pos[t] for t in mk["times"] if t in pos]
            hs = [d["high"][i] for i in idx]
            ax.plot(idx, hs, color=INK, lw=1.0, ls=(0, (1, 2)), zorder=5)
            ax.scatter(idx, [h + yr * 0.004 for h in hs], marker="v", s=36, color=INK, zorder=6)
            badge(ax, idx[0], hs[0], no, view, dx=-2, dy=26)
            label(ax, idx[0], hs[0], mk["text"], dx=11, dy=26)
        elif kind == "arrow":
            y0 = float(d["close"].iloc[-1])
            ax.annotate("", xy=(last + arrow_len, mk["to"]), xytext=(last + 0.6, y0),
                        arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.4, ls=(0, (4, 2)), mutation_scale=14),
                        zorder=10)
            margin_items.append((mk["to"], mk["to"], no, view, mk["text"]))
        elif kind == "offchart":
            ax.annotate("", xy=(last + 1.5, yhi), xytext=(last + 1.5, yhi - (yhi - ylo) * 0.07),
                        arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.3, mutation_scale=13), zorder=10,
                        annotation_clip=False)
            margin_items.append((yhi - (yhi - ylo) * 0.035, None, no, view, mk["text"]))
    c = float(d["close"].iloc[-1])
    margin_items.append((c, c, None, "close", f"종가 {c:,.0f}"))
    # 오른쪽 여백 라벨(겹치지 않게)
    if margin_items:
        ys = spread([m[0] for m in margin_items], gap=(yhi - ylo) * 0.042, lo=ylo, hi=yhi - (yhi - ylo) * 0.01)
        for (y_true, anchor, no, view, text), y in zip(margin_items, ys):
            if anchor is not None and abs(y - anchor) > (yhi - ylo) * 0.004:
                ax.plot([lab_x - 0.4, lab_x + 0.25], [anchor, y], color=INK2, lw=0.7, zorder=5)
            if no is None:                                 # 종가 줄
                label(ax, lab_x + 0.9, y, text, dx=-6, size=10.5, weight="bold")
                ax.hlines(anchor, last + 0.4, lab_x - 0.4, color=INK, lw=0.8, zorder=5)
                continue
            badge(ax, lab_x + 0.9, y, no, view, size=9.5)
            label(ax, lab_x + 0.9, y, text, dx=11, size=10.5)
    ax.scatter([last], [c], s=22, color=INK, zorder=13)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    # 거래량
    vcol = [UP if cc >= oo else DOWN for oo, cc in zip(d["open"], d["close"])]
    spike = (d["volume"] >= 2 * d["vavg"]).to_numpy()
    axv.bar(x, d["volume"], color=[c_ if s else c_ + "55" for c_, s in zip(vcol, spike)], width=w, zorder=3)
    axv.plot(x, d["vavg"], color=INK2, lw=1.0, zorder=4)
    axv.annotate("거래량(진한 막대 = 직전 20봉 평균의 2배 이상, 선 = 평균)", xy=(0, 1), xycoords="axes fraction",
                 xytext=(4, -10), textcoords="offset points", fontsize=9.5, color=INK2, va="top")
    axv.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k"))
    step = max(1, n // 9)
    ticks = list(range(0, n, step))
    axv.set_xticks(ticks)
    fmt = "%m-%d" if tf == "1d" else "%m-%d %H시"
    axv.set_xticklabels([d["time"][i].strftime(fmt) for i in ticks], fontsize=10)
    # 제목·범례
    fig.text(0.07, 0.955, title, fontsize=16, fontweight="bold", color=INK, ha="left")
    lx = 0.07
    fig.text(lx, 0.925, "번호 모양:", fontsize=10.5, color=INK2, ha="left", va="center")
    for nm, view, off in (("차트프로", "CP", 0.055), ("워뇨띠", "WY", 0.125), ("Claude 종합", "CL", 0.19)):
        bx = dict(CP=dict(boxstyle="circle,pad=0.25", fc=INK, ec="white"),
                  WY=dict(boxstyle="square,pad=0.28", fc=WY_BADGE, ec="white"),
                  CL=dict(boxstyle="round,pad=0.28", fc="white", ec=INK, lw=1.3))[view]
        fig.text(lx + off, 0.925, "1", fontsize=9, fontweight="bold", color=("white" if view != "CL" else INK),
                 ha="center", va="center", bbox=bx)
        fig.text(lx + off + 0.011, 0.925, nm, fontsize=10.5, color=INK, ha="left", va="center")
    fig.text(lx + 0.29, 0.925, "회색 선 = 이동평균(오른쪽 끝 숫자 = 기간)  ·  양봉 빨강 / 음봉 파랑", fontsize=10.5,
             color=INK2, ha="left", va="center")
    fig.savefig(path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def draw_similar(sim: dict, path: pathlib.Path, title: str) -> None:
    pick_font()
    fig, axes = plt.subplots(2, 3, figsize=(16, 9.5), dpi=100, facecolor=SURFACE)
    conf = [("1d", 20, 10, "일봉 20일"), ("1d", 40, 10, "일봉 40일"), ("1d", 60, 10, "일봉 60일"),
            ("4h", 30, 18, "4시간봉 30봉"), ("4h", 60, 18, "4시간봉 60봉"), ("4h", 120, 18, "4시간봉 120봉")]
    for ax, (tf, L, hz, nm) in zip(axes.flat, conf):
        r = sim[f"{tf}_{L}"]
        ax.set_facecolor(SURFACE)
        ax.grid(color=GRID, lw=0.8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color("#c9c8c2")
        ax.tick_params(colors=INK2, labelsize=9.5)
        paths = [np.array(p) * 100 - 100 for p in r["paths"]]
        nmax = len(paths[0]) - 1
        for p in paths[3:]:
            ax.plot(range(nmax + 1), p, color="#b9b8b2", lw=1.0, zorder=2)
        for k, p in enumerate(paths[:3]):
            ax.plot(range(nmax + 1), p, color=INK, lw=1.6, zorder=3)
            yend = float(np.clip(p[-1], -19, 29 if tf == "1d" else 14))
            ax.annotate(f"{k + 1}위", xy=(nmax, yend), xytext=(3, 0), textcoords="offset points", fontsize=8.5,
                        color=INK, va="center", annotation_clip=False)
        ax.axhline(0, color=MUTED, lw=0.9, zorder=1)
        ax.axvline(hz, color=INK2, lw=0.8, ls=(0, (2, 2)), zorder=1)
        s = r["summary"][str(hz)] if str(hz) in r["summary"] else r["summary"][hz]
        b = r["baseline"][str(hz)] if str(hz) in r["baseline"] else r["baseline"][hz]
        ax.set_ylim(-20, 30 if tf == "1d" else 15)
        ax.set_xlim(0, nmax + 3)
        unit = "일" if tf == "1d" else "봉"
        ax.set_title(f"{nm} 구간 → {hz}{unit} 뒤: 상승 {s['up']} / 하락 {s['down']}", fontsize=11.5, color=INK,
                     loc="left", fontweight="bold")
        top3 = " / ".join(f"{v:+.1f}%" for v in s["top3"])
        ax.text(0.02, 0.04, f"상위 3개 {top3}\n아무 때나 고르면 {b['up_share']:.0f}%가 상승\n1위 점수 {r['top1']} "
                            f"(무작위 상위1% {r['p99']})", transform=ax.transAxes, fontsize=9, color=INK2,
                va="bottom", bbox=dict(boxstyle="round,pad=0.3", fc=SURFACE, ec=GRID))
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}%"))
        ax.set_xlabel("그 뒤 지난 " + ("일수" if tf == "1d" else "4시간봉 수"), fontsize=9.5, color=INK2)
        ups, dns, med = s["up"], s["down"], s["median"]
        if ups >= 8 and med > 0 and all(v > 0 for v in s["top3"]):
            verdict = "모임(상승)"
        elif dns >= 8 and med < 0 and all(v < 0 for v in s["top3"]):
            verdict = "모임(하락)"
        else:
            verdict = "갈림"
        ax.text(0.98, 0.96, verdict, transform=ax.transAxes, ha="right", va="top", fontsize=11, fontweight="bold",
                color=(WY_BADGE if verdict.startswith("모임") else INK),
                bbox=dict(boxstyle="round,pad=0.3", fc=SURFACE, ec=INK2, lw=0.8))
    fig.text(0.06, 0.965, title, fontsize=15, fontweight="bold", color=INK, ha="left")
    fig.text(0.06, 0.935, "검은 선 = 점수 상위 3개, 회색 = 나머지 7개 · 0% = 지금 가격 · 점선 = 판정에 쓴 시점"
                          " · 과거에 실제로 일어난 일이며 예측이 아님 · 범위 밖은 잘림",
             fontsize=10.5, color=INK2, ha="left")
    fig.tight_layout(rect=(0.04, 0, 1, 0.92))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def main(out: str) -> None:
    o = pathlib.Path(out).expanduser()
    spec = json.loads((pathlib.Path(__file__).parent / "sample_0929.json").read_text(encoding="utf-8"))
    marks = spec["marks"]
    d1, h4 = load("1d"), load("4h")
    draw(d1, "1d", "2026-05-01", marks, o / "brief_1d.png",
         "BTCUSDT 일봉 · 2026-09-29 09:00 KST 기준 (과거 데이터 샘플)", right_bars=34)
    draw(h4, "4h", "2026-09-20 09", marks, o / "brief_4h.png",
         "BTCUSDT 4시간봉 · 2026-09-29 09:00 KST 기준 (과거 데이터 샘플)", right_bars=30, arrow_len=7)
    sim = json.loads((o / "similar.json").read_text(encoding="utf-8"))
    draw_similar(sim, o / "brief_similar.png", "워뇨띠 관점 재료: 닮은꼴 검색 결과 (우리 구현, 2020~2026 바이낸스)")
    print("ok")


if __name__ == "__main__":
    main(sys.argv[1])
