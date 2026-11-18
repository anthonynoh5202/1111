/* PDF 안에 봉차트를 벡터로 직접 그린다(브라우저 없이 클라우드에서도 됨).
   그리는 것: 4시간 봉, 거래량 막대 + 거래량 20봉 평균선, 가격 20·60봉 평균선,
   가까운 저항/지지 가로선, 다음 16시간 흔한 범위 띠, 그리고 판단 근거 ①~⑧ 번호.
   cd(차트 자료)는 run.cjs 가 core.js 결과에서 뽑아 latest.json 에 저장한 것을 쓴다. */

const UP = "#16a34a", DN = "#dc2626", INK = "#1a1a1a", MUTE = "#6b7280", GRID = "#e5e7eb";
const MA20 = "#2563eb", MA60 = "#9333ea", VMA = "#ea580c", RES = "#dc2626", SUP = "#16a34a", BAND = "#f59e0b";

function marker(doc, cx, cy, n, color) {
  doc.save().circle(cx, cy, 8).fillOpacity(1).fill(color).restore();
  doc.fillColor("#ffffff").font("kr-bold").fontSize(9).text(String(n), cx - 8, cy - 5.5, { width: 16, align: "center", lineBreak: false });
  doc.fillColor(INK);
}

/* area = {x, y, w, h}. 가격판(위) + 거래량판(아래) */
function drawChart(doc, area, cd) {
  const bars = cd.bars;
  const n = bars.length;
  const GUT = 46;                     // 왼쪽 가격 눈금 자리
  const RPAD_SLOTS = 5;               // 오른쪽 띠를 그릴 여백(봉 칸 수)
  const plotX = area.x + GUT, plotW = area.w - GUT - 6;
  const slots = n + RPAD_SLOTS, slotW = plotW / slots, cw = Math.max(1.4, slotW * 0.62);
  const cx = i => plotX + (i + 0.5) * slotW;
  const bandX = plotX + n * slotW;    // 띠 시작 x(마지막 봉 오른쪽)

  const priceH = area.h * 0.70, gap = area.h * 0.05;
  const priceTop = area.y, priceBot = area.y + priceH;
  const volTop = priceBot + gap, volBot = area.y + area.h;

  // --- 가격 세로 범위 ---
  let pmin = Infinity, pmax = -Infinity;
  for (const b of bars) { pmin = Math.min(pmin, b.l); pmax = Math.max(pmax, b.h); }
  if (cd.res) pmax = Math.max(pmax, cd.res);
  if (cd.sup) pmin = Math.min(pmin, cd.sup);
  if (cd.band) { pmin = Math.min(pmin, cd.band[0]); pmax = Math.max(pmax, cd.band[1]); }
  const pad = (pmax - pmin) * 0.06; pmin -= pad; pmax += pad;
  const yP = p => priceBot - (p - pmin) / (pmax - pmin) * priceH;

  // --- 거래량 세로 범위 ---
  let vmax = 0; for (const b of bars) vmax = Math.max(vmax, b.v, b.volAvg || 0);
  const yV = v => volBot - (v / vmax) * (volBot - volTop);

  // --- 테두리/가로 눈금 ---
  doc.save().lineWidth(0.5).strokeColor(GRID);
  for (let k = 0; k <= 4; k++) {
    const p = pmin + (pmax - pmin) * k / 4, y = yP(p);
    doc.moveTo(plotX, y).lineTo(plotX + plotW, y).stroke();
    doc.fillColor(MUTE).font("kr").fontSize(7).text(Math.round(p).toLocaleString("en-US"), area.x, y - 4, { width: GUT - 4, align: "right", lineBreak: false });
  }
  doc.restore();

  // --- ③ 최근 6봉(24시간) 음영 ---
  if (cd.last6Idx != null && cd.last6Idx < n) {
    const x0 = cx(cd.last6Idx) - cw / 2, x1 = cx(n - 1) + cw / 2;
    doc.save().fillOpacity(0.08).fill("#000000").rect(x0, priceTop, x1 - x0, priceH).fill().restore();
  }

  // --- ④ 다음 16시간 흔한 범위 띠 ---
  if (cd.band) {
    const y1 = yP(cd.band[1]), y0 = yP(cd.band[0]);
    doc.save().fillOpacity(0.18).fill(BAND).rect(bandX, y1, plotW + plotX - bandX, y0 - y1).fill().restore();
  }

  // --- 가격 이평선 20·60 ---
  const poly = (key, color) => {
    doc.save().lineWidth(1).strokeColor(color); let started = false;
    for (let i = 0; i < n; i++) {
      const v = bars[i][key]; if (v == null) { started = false; continue; }
      const x = cx(i), y = yP(v);
      if (!started) { doc.moveTo(x, y); started = true; } else doc.lineTo(x, y);
    }
    doc.stroke().restore();
  };
  poly("ma60", MA60); poly("ma20", MA20);

  // --- 봉 ---
  for (let i = 0; i < n; i++) {
    const b = bars[i], up = b.c >= b.o, col = up ? UP : DN, x = cx(i);
    doc.save().lineWidth(1).strokeColor(col).moveTo(x, yP(b.h)).lineTo(x, yP(b.l)).stroke().restore();
    const yo = yP(b.o), yc = yP(b.c), top = Math.min(yo, yc), hgt = Math.max(1, Math.abs(yo - yc));
    doc.save().fillColor(col).rect(x - cw / 2, top, cw, hgt).fill().restore();
  }

  // --- 거래량 막대 + 거래량 20봉 평균선 ---
  for (let i = 0; i < n; i++) {
    const b = bars[i], col = b.c >= b.o ? UP : DN;
    doc.save().fillOpacity(0.55).fillColor(col).rect(cx(i) - cw / 2, yV(b.v), cw, volBot - yV(b.v)).fill().restore();
  }
  doc.save().lineWidth(1.2).strokeColor(VMA); let vs = false;
  for (let i = 0; i < n; i++) { const a = bars[i].volAvg; if (a == null) { vs = false; continue; } const x = cx(i), y = yV(a); if (!vs) { doc.moveTo(x, y); vs = true; } else doc.lineTo(x, y); }
  doc.stroke().restore();
  doc.fillColor(MUTE).font("kr").fontSize(7).text("거래량", area.x, volTop - 9, { lineBreak: false });

  // --- ⑦ 저항 / ⑧ 지지 가로선 ---
  const hline = (p, color, label) => {
    const y = yP(p);
    doc.save().lineWidth(1).strokeColor(color).dash(3, { space: 2 }).moveTo(plotX, y).lineTo(bandX, y).stroke().undash().restore();
    doc.fillColor(color).font("kr").fontSize(7).text(label + " " + Math.round(p).toLocaleString("en-US"), plotX + 2, y - 9, { lineBreak: false });
    doc.fillColor(INK);
  };
  if (cd.res) hline(cd.res, RES, "저항");
  if (cd.sup) hline(cd.sup, SUP, "지지");

  // --- 날짜 눈금 ---
  doc.fillColor(MUTE).font("kr").fontSize(6.5);
  for (let i = 0; i < n; i += 12) {
    const d = new Date(bars[i].t + 9 * 3600000);
    doc.text((d.getUTCMonth() + 1) + "/" + d.getUTCDate(), cx(i) - 10, volBot + 3, { width: 20, align: "center", lineBreak: false });
  }
  doc.fillColor(INK);

  // --- 번호 (1)~(8): 4시간봉 전용. 다른 타임프레임(simple)은 번호 없이 저항/지지선만 ---
  if (cd.simple) return;
  const sig = cd.sigIdx;
  if (sig != null && sig < n) {
    marker(doc, cx(sig) - slotW, yP(bars[sig].h) - 16, 1, INK);         // (1) 윗꼬리 (오른쪽 번호들과 겹치지 않게 살짝 왼쪽 위)
    marker(doc, cx(sig), yV(bars[sig].v) - 12, 2, VMA);                 // ② 거래량/평균
  }
  if (cd.last6Idx != null) marker(doc, cx(Math.min(n - 1, (cd.last6Idx + n - 1) / 2)), priceTop + 10, 3, "#000000"); // ③ 크기
  if (cd.band) marker(doc, bandX + (plotX + plotW - bandX) / 2, yP((cd.band[0] + cd.band[1]) / 2), 4, BAND);         // ④ 띠
  if (cd.peakIdx != null && cd.peakIdx < n) marker(doc, cx(cd.peakIdx), yP(bars[cd.peakIdx].h) - 12, 5, MUTE);       // ⑤ 고점
  if (cd.troughIdx != null && cd.troughIdx < n) marker(doc, cx(cd.troughIdx), yP(bars[cd.troughIdx].l) + 12, 6, MUTE); // ⑥ 저점
  if (cd.res) marker(doc, bandX - 2, yP(cd.res), 7, RES);
  if (cd.sup) marker(doc, bandX - 2, yP(cd.sup), 8, SUP);
}

module.exports = { drawChart };
