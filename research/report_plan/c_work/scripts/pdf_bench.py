"""한 장짜리 보고서(차트 1개 + 한글 글) PDF·PNG 시험: 크기·시간·글꼴 포함 여부.
사용: python -I pdf_bench.py <fonts_dir> <data_csv_1h> <out_dir>
"""
import sys, time, pathlib, textwrap, re, io
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages

fonts, csv, out = map(pathlib.Path, sys.argv[1:4])
out.mkdir(parents=True, exist_ok=True)
for f in sorted(fonts.glob("Pretendard-*.ttf")):
    font_manager.fontManager.addfont(str(f))
plt.rcParams["font.family"] = "Pretendard"
plt.rcParams["axes.unicode_minus"] = False

t0 = time.perf_counter()
df = pd.read_csv(csv).tail(24 * 7)          # 1시간봉 7일 = 168개
df["t"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul")
for n in (20, 60, 120):
    df[f"ma{n}"] = df["close"].rolling(n, min_periods=1).mean()
t_load = time.perf_counter() - t0

KO = ("[관점 1 · Claude 종합] 4시간봉 기준 직전 고점 돌파 실패 뒤 허리선 아래로 내려왔다. 1시간봉 거래량은 20봉 평균의 0.8배로 "
      "힘이 약하다. 결론: 관망. 롱은 84,800 위 1시간봉 종가 확정 때만, 손절 83,900, 레버리지 2배 이하. "
      "[관점 2 · 워뇨띠] 추세가 꺾이지 않았으면 눌림에서만 산다. 지금은 박스 중간이라 손익비가 나오지 않는다. "
      "[관점 3 · 차트프로] 기준봉 시가(83,120)를 지키는 동안은 매수 우위, 깨지면 숏 관점 전환. 마디 84,780 저항. "
      "펀딩 +0.0100%, 미결제약정 24시간 +1.2%, 테이커 매수/매도 0.97. 이 보고서는 참고용이며 주문은 사용자가 직접 한다.")

def build(fig_w=11.69, fig_h=8.27):
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=100, facecolor="white")
    gs = fig.add_gridspec(3, 3, height_ratios=[3, 1, 1.6], width_ratios=[2.2, 1, 1], hspace=0.25, wspace=0.15)
    ax = fig.add_subplot(gs[0, :2]); axv = fig.add_subplot(gs[1, :2], sharex=ax)
    x = np.arange(len(df)); o, h, l, c, v = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    up = c >= o
    ax.vlines(x, l, h, color=np.where(up, "#d94a3d", "#3d6fd9"), lw=0.8)
    ax.bar(x, np.abs(c - o), bottom=np.minimum(o, c), color=np.where(up, "#d94a3d", "#3d6fd9"), width=0.7)
    for n, col in ((20, "#a6a59f"), (60, "#7f7e78"), (120, "#2f2e2b")):
        ax.plot(x, df[f"ma{n}"], color=col, lw=1, label=f"{n}선")
    for y, lab in ((84780, "마디 저항 84,780"), (83120, "기준봉 시가 83,120")):
        ax.axhline(y, color="#555", lw=0.8, ls="--"); ax.text(x[-1] + 1, y, lab, fontsize=8, va="center")
    ax.legend(loc="upper left", fontsize=8); ax.set_title("BTCUSDT 무기한 · 1시간봉 · 2026-09-29 08:00 KST 마감 기준", fontsize=12, loc="left")
    axv.bar(x, v, color=np.where(up, "#d94a3d", "#3d6fd9"), width=0.7)
    ticks = x[::24]; axv.set_xticks(ticks, [df["t"].iloc[i].strftime("%m-%d %H시") for i in ticks], fontsize=8)
    side = fig.add_subplot(gs[0:2, 2]); side.axis("off")
    rows = [("판정", "관망 (롱 조건부)"), ("진입 조건", "84,800 위 1h 종가"), ("손절", "83,900 (-1.06%)"), ("목표", "86,200 / 87,500"),
            ("레버리지", "2배 이하 (최소 주문 0.002 BTC)"), ("위험", "계좌의 1% = 0.36 USDT"), ("펀딩", "+0.0100% / 8h"), ("OI 24h", "+1.2%")]
    for i, (k, val) in enumerate(rows):
        side.text(0.0, 1 - i * 0.11, k, fontsize=10, color="#666", transform=side.transAxes)
        side.text(0.38, 1 - i * 0.11, val, fontsize=10, weight="bold", transform=side.transAxes)
    tx = fig.add_subplot(gs[2, :]); tx.axis("off")
    tx.text(0, 1, "\n".join(textwrap.wrap(KO, 95)), fontsize=9.5, va="top", transform=tx.transAxes, linespacing=1.5)
    return fig

res = {}
for ft in (42, 3):
    plt.rcParams["pdf.fonttype"] = ft
    t1 = time.perf_counter(); fig = build()
    p = out / f"report_ft{ft}.pdf"
    with PdfPages(p, metadata={"Title": "BTC 1h report", "Creator": "test"}) as pdf:
        pdf.savefig(fig)
    t_pdf = time.perf_counter() - t1
    t2 = time.perf_counter()
    png = out / f"report_ft{ft}.png"
    fig.savefig(png, dpi=170)          # 11.69in*170 ≈ 1987px 폭
    t_png = time.perf_counter() - t2
    plt.close(fig)
    raw = p.read_bytes()
    res[ft] = dict(pdf_kb=round(len(raw) / 1024, 1), png_kb=round(png.stat().st_size / 1024, 1), t_pdf=round(t_pdf, 2), t_png=round(t_png, 2),
                   fontfile2=raw.count(b"/FontFile2"), type3=raw.count(b"/Type3"), cidtype2=raw.count(b"/CIDFontType2"))
from PIL import Image
w, h = Image.open(out / "report_ft42.png").size
print("load_s", round(t_load, 2), "png_px", w, h)
for k, v in res.items():
    print("fonttype", k, v)
