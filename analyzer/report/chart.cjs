/* PDF 안에 봉차트를 벡터로 직접 그린다(브라우저 없이 클라우드에서도 됨).
   그리는 것: 봉, 거래량 막대 + 거래량 20봉 평균선, 가격 20·60봉 평균선,
   가까운 저항/지지 가로선, 다음 16시간 흔한 범위 띠, 그리고 판단 근거 1~8 번호(4시간봉만).
   cd(차트 자료)는 run.cjs 가 core.js 결과에서 뽑아 latest.json 에 저장한 것을 쓴다. */

const C = {
  ink: "#0f172a", mute: "#64748b", faint: "#94a3b8", grid: "#eef1f5", axis: "#e2e8f0",
  up: "#1a9e77", dn: "#e0525e", ma20: "#3f6fd1", ma60: "#c58b2b", vma: "#7c8798",
  res: "#e0525e", sup: "#1a9e77", band: "#c58b2b"
};
const fmt = n => Math.round(n).toLocaleString("en-US");

function marker(doc, cx, cy, n, color) {
  doc.save().lineWidth(1.2).circle(cx, cy, 6.5).fillAndStroke(color, "#ffffff").restore();
  doc.fillColor("#ffffff").font("kr-bold").fontSize(7.5).text(String(n), cx - 6.5, cy - 4.2, { width: 13, align: "center", lineBreak: false });
}

/* 오른쪽 눈금 자리에 붙는 가격 표(알약 모양) */
function pill(doc, x, y, w, text, bg, fg) {
  doc.save().roundedRect(x, y - 6, w, 12, 2.5).fill(bg).restore();
  doc.fillColor(fg || "#ffffff").font("kr-bold").fontSize(6.5).text(text, x, y - 3.6, { width: w, align: "center", lineBreak: false });
}

/* area = {x, y, w, h}. 가격판(위) + 거래량판(아래) + 날짜 눈금(맨 아래 12pt 안) */
function drawChart(doc, area, cd) {
  const bars = cd.bars, n = bars.length;
  const AXIS = 44;                    // 오른쪽 가격 눈금 자리
  const DATE_H = 12;                  // 맨 아래 날짜 눈금 자리
  const RPAD_SLOTS = cd.band ? 6 : 1; // 오른쪽 띠 여백(봉 칸 수)
  const plotX = area.x, plotW = area.w - AXIS - 4;
  const slots = n + RPAD_SLOTS, slotW = plotW / slots, bw = Math.max(1.2, slotW * 0.64);
  const cx = i => plotX + (i + 0.5) * slotW;
  const bandX = plotX + n * slotW;
  const axisX = plotX + plotW + 4;

  const inner = area.h - DATE_H;
  const priceH = inner * 0.74, gap = inner * 0.04;
  const priceTop = area.y, priceBot = area.y + priceH;
  const volTop = priceBot + gap, volBot = area.y + inner;

  // 가격 세로 범위
  let pmin = Infinity, pmax = -Infinity;
  for (const b of bars) { pmin = Math.min(pmin, b.l); pmax = Math.max(pmax, b.h); for (const k of ["ma20", "ma60"]) if (b[k] != null) { pmin = Math.min(pmin, b[k]); pmax = Math.max(pmax, b[k]); } }
  if (cd.res) pmax = Math.max(pmax, cd.res);
  if (cd.sup) pmin = Math.min(pmin, cd.sup);
  if (cd.band) { pmin = Math.min(pmin, cd.band[0]); pmax = Math.max(pmax, cd.band[1]); }
  const pad = (pmax - pmin) * 0.07; pmin -= pad; pmax += pad;
  const yP = p => priceBot - (p - pmin) / (pmax - pmin) * priceH;

  let vmax = 0; for (const b of bars) vmax = Math.max(vmax, b.v, b.volAvg || 0);
  const yV = v => volBot - (v / (vmax || 1)) * (volBot - volTop);

  // 가로 눈금(옅은 선) + 오른쪽 가격 숫자. 가격 표(지금·저항·지지)와 겹치는 숫자는 뺀다.
  const pills = [bars[n - 1].c, cd.res, cd.sup].filter(v => v != null).map(yP);
  for (let k = 0; k <= 4; k++) {
    const p = pmin + (pmax - pmin) * (k + 0.5) / 5, y = yP(p);
    doc.save().lineWidth(0.5).strokeColor(C.grid).moveTo(plotX, y).lineTo(plotX + plotW, y).stroke().restore();
    if (pills.every(py => Math.abs(py - y) > 14)) doc.fillColor(C.faint).font("kr").fontSize(6.3).text(fmt(p), axisX + 3, y - 3.4, { width: AXIS - 4, lineBreak: false });
  }
  // 가격판·거래량판 경계와 바닥선
  doc.save().lineWidth(0.6).strokeColor(C.axis);
  doc.moveTo(plotX, priceBot).lineTo(plotX + plotW, priceBot).stroke();
  doc.moveTo(plotX, volBot).lineTo(plotX + plotW, volBot).stroke();
  doc.moveTo(plotX + plotW, priceTop).lineTo(plotX + plotW, volBot).stroke();
  doc.restore();

  // (3) 최근 6봉 음영
  if (cd.last6Idx != null && cd.last6Idx < n) {
    const x0 = cx(cd.last6Idx) - slotW / 2, x1 = cx(n - 1) + slotW / 2;
    doc.save().fillOpacity(0.05).fillColor(C.ink).rect(x0, priceTop, x1 - x0, priceH).fill().restore();
  }
  // (4) 다음 16시간 흔한 범위 띠
  if (cd.band) {
    const y1 = yP(cd.band[1]), y0 = yP(cd.band[0]);
    doc.save().fillOpacity(0.13).fillColor(C.band).rect(bandX, y1, plotX + plotW - bandX, y0 - y1).fill().restore();
    doc.save().lineWidth(0.6).strokeOpacity(0.6).strokeColor(C.band)
      .moveTo(bandX, y1).lineTo(plotX + plotW, y1).moveTo(bandX, y0).lineTo(plotX + plotW, y0).stroke().restore();
  }

  // 가격 이평선 20·60
  const poly = (key, color, lw) => {
    doc.save().lineWidth(lw).strokeColor(color).lineJoin("round"); let started = false, any = false;
    for (let i = 0; i < n; i++) {
      const v = bars[i][key]; if (v == null) { started = false; continue; }
      const x = cx(i), y = yP(v);
      if (!started) { doc.moveTo(x, y); started = true; } else { doc.lineTo(x, y); any = true; }
    }
    if (any) doc.stroke(); doc.restore();
  };
  poly("ma60", C.ma60, 1.1); poly("ma20", C.ma20, 1.1);

  // 봉
  for (let i = 0; i < n; i++) {
    const b = bars[i], col = b.c >= b.o ? C.up : C.dn, x = cx(i);
    doc.save().lineWidth(0.7).strokeColor(col).moveTo(x, yP(b.h)).lineTo(x, yP(b.l)).stroke().restore();
    const yo = yP(b.o), yc = yP(b.c), top = Math.min(yo, yc), hgt = Math.max(0.8, Math.abs(yo - yc));
    doc.save().fillColor(col).rect(x - bw / 2, top, bw, hgt).fill().restore();
  }

  // 거래량 막대 + 20봉 평균선
  for (let i = 0; i < n; i++) {
    const b = bars[i], col = b.c >= b.o ? C.up : C.dn;
    doc.save().fillOpacity(0.32).fillColor(col).rect(cx(i) - bw / 2, yV(b.v), bw, volBot - yV(b.v)).fill().restore();
  }
  doc.save().lineWidth(0.9).strokeColor(C.vma); let vs = false, vany = false;
  for (let i = 0; i < n; i++) { const a = bars[i].volAvg; if (a == null) { vs = false; continue; } const x = cx(i), y = yV(a); if (!vs) { doc.moveTo(x, y); vs = true; } else { doc.lineTo(x, y); vany = true; } }
  if (vany) doc.stroke(); doc.restore();
  doc.fillColor(C.faint).font("kr").fontSize(6).text("거래량", plotX + 3, volTop + 2, { lineBreak: false });

  // 지금 가격(오른쪽 진한 표) + 저항/지지 가로선과 표
  const last = bars[n - 1], yLast = yP(last.c);
  doc.save().lineWidth(0.5).strokeColor(C.ink).strokeOpacity(0.35).dash(1, { space: 1.5 }).moveTo(cx(n - 1), yLast).lineTo(plotX + plotW, yLast).stroke().undash().restore();
  const close = cd.res && cd.sup && Math.abs(yP(cd.res) - yP(cd.sup)) < 12;
  const hline = (p, color, label, below) => {
    let y = yP(p);
    doc.save().lineWidth(0.7).strokeColor(color).dash(3, { space: 2.5 }).moveTo(plotX, y).lineTo(plotX + plotW, y).stroke().undash().restore();
    const ly = below ? y + 2.5 : y - 8.5;
    doc.font("kr").fontSize(6.3);
    doc.save().fillOpacity(0.85).fillColor("#ffffff").rect(plotX + 1, ly - 0.5, doc.widthOfString(label) + 4, 8).fill().restore();
    doc.fillColor(color).text(label, plotX + 3, ly, { lineBreak: false });
    if (Math.abs(y - yLast) < 12) y = y < yLast ? yLast - 12 : yLast + 12;   // 지금 가격 표와 겹치지 않게
    pill(doc, axisX, y, AXIS, fmt(p), color);
  };
  if (cd.res) hline(cd.res, C.res, "저항");
  if (cd.sup) hline(cd.sup, C.sup, "지지", close);
  pill(doc, axisX, yLast, AXIS, fmt(last.c), C.ink);

  // 날짜 눈금(아래 자리 안에서만)
  doc.fillColor(C.faint).font("kr").fontSize(6.2);
  const step = Math.max(1, Math.round(n / 7));
  const intraday = n > 1 && bars[1].t - bars[0].t < 86400000, shortSpan = bars[n - 1].t - bars[0].t < 2 * 86400000;
  for (let i = 0; i < n; i += step) {
    const d = new Date(bars[i].t + 9 * 3600000);
    const hm = String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0"), md = (d.getUTCMonth() + 1) + "/" + d.getUTCDate();
    const label = !intraday ? md : shortSpan ? hm : md + " " + String(d.getUTCHours()).padStart(2, "0") + "시";
    doc.text(label, cx(i) - 26, volBot + 3, { width: 52, align: "center", lineBreak: false });
  }

  // 번호 1~8: 4시간봉 전용
  if (cd.simple) return;
  const sig = cd.sigIdx;
  if (sig != null && sig < n) {
    marker(doc, cx(sig) - slotW * 1.5, yP(bars[sig].h) - 14, 1, C.ink);
    marker(doc, cx(sig), Math.max(volTop + 7, yV(bars[sig].v) - 10), 2, C.vma);
  }
  if (cd.last6Idx != null) marker(doc, cx(Math.min(n - 1, (cd.last6Idx + n - 1) / 2)), priceTop + 9, 3, C.mute);
  if (cd.band) marker(doc, bandX + (plotX + plotW - bandX) / 2, yP((cd.band[0] + cd.band[1]) / 2), 4, C.band);
  if (cd.peakIdx != null && cd.peakIdx < n) marker(doc, cx(cd.peakIdx), yP(bars[cd.peakIdx].h) - 11, 5, C.mute);
  if (cd.troughIdx != null && cd.troughIdx < n) marker(doc, cx(cd.troughIdx), yP(bars[cd.troughIdx].l) + 11, 6, C.mute);
  if (cd.res) marker(doc, bandX - 4, yP(cd.res), 7, C.res);
  if (cd.sup) marker(doc, bandX - 4, yP(cd.sup), 8, C.sup);
}

module.exports = { drawChart, COLORS: C };
