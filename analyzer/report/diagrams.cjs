/* 분석 이론 페이지에 넣을 작은 예시 도식들. 데이터가 아니라 개념을 보여주는 손그림 수준의 벡터. */
const G = "#16a34a", R = "#dc2626", BL = "#2563eb", PU = "#9333ea", OR = "#ea580c", MU = "#6b7280", INK = "#111827", LINE = "#e5e7eb";

function frameBox(doc, x, y, w, h) { doc.save().roundedRect(x, y, w, h, 3).fillAndStroke("#fcfcfd", LINE).restore(); }
function cap(doc, x, y, w, t) { doc.font("kr").fontSize(6).fillColor(MU).text(t, x, y, { width: w, align: "center", lineBreak: false }); }
function candle(doc, cx, cw, bTop, bBot, wTop, wBot, col) {
  doc.save().lineWidth(1).strokeColor(col).moveTo(cx, wTop).lineTo(cx, wBot).stroke();
  doc.rect(cx - cw / 2, Math.min(bTop, bBot), cw, Math.max(1, Math.abs(bBot - bTop))).fill(col).restore();
}
function arrow(doc, x1, y1, x2, y2, col, lw) {
  doc.save().lineWidth(lw || 1.5).strokeColor(col).fillColor(col).moveTo(x1, y1).lineTo(x2, y2).stroke();
  const a = Math.atan2(y2 - y1, x2 - x1), s = 4;
  doc.moveTo(x2, y2).lineTo(x2 - s * Math.cos(a - 0.5), y2 - s * Math.sin(a - 0.5)).lineTo(x2 - s * Math.cos(a + 0.5), y2 - s * Math.sin(a + 0.5)).fill();
  doc.restore();
}

/* 0) 이동평균 배열(역배열): 세 선이 아래로, 20이 맨 아래 */
function maAlign(doc, x, y, w, h) {
  frameBox(doc, x, y, w, h); const x0 = x + 7, x1 = x + w - 7;
  doc.save().lineWidth(1.4);
  doc.strokeColor("#9ca3af").moveTo(x0, y + h * 0.26).lineTo(x1, y + h * 0.40).stroke();
  doc.strokeColor(PU).moveTo(x0, y + h * 0.38).lineTo(x1, y + h * 0.56).stroke();
  doc.strokeColor(BL).moveTo(x0, y + h * 0.50).lineTo(x1, y + h * 0.74).stroke();
  doc.restore();
  doc.font("kr").fontSize(5.5).fillColor("#9ca3af").text("120", x1 - 14, y + h * 0.34, { lineBreak: false });
  doc.fillColor(PU).text("60", x1 - 14, y + h * 0.50, { lineBreak: false });
  doc.fillColor(BL).text("20", x1 - 14, y + h * 0.68, { lineBreak: false });
  cap(doc, x, y + h - 10, w, "역배열 = 하락 정렬");
}

/* 1) 지지·저항: 가로선 2개 + 사이에서 튕기는 가격 */
function supRes(doc, x, y, w, h) {
  frameBox(doc, x, y, w, h); const x0 = x + 7, x1 = x + w - 7, top = y + h * 0.26, bot = y + h * 0.66;
  doc.save().lineWidth(1).dash(2, { space: 1.5 });
  doc.strokeColor(R).moveTo(x0, top).lineTo(x1, top).stroke();
  doc.strokeColor(G).moveTo(x0, bot).lineTo(x1, bot).stroke();
  doc.undash().restore();
  doc.save().lineWidth(1.2).strokeColor(INK);
  doc.moveTo(x0, bot).lineTo(x + w * 0.33, top).lineTo(x + w * 0.55, bot).lineTo(x + w * 0.78, top).lineTo(x1, bot).stroke();
  doc.restore();
  doc.font("kr").fontSize(5.5).fillColor(R).text("저항", x0, top - 7, { lineBreak: false });
  doc.fillColor(G).text("지지", x0, bot + 1, { lineBreak: false });
  cap(doc, x, y + h - 10, w, "닿으면 되돌림");
}

/* 2) 거래량 확증: 거래량 큰 봉 vs 작은 봉 */
function volume(doc, x, y, w, h) {
  frameBox(doc, x, y, w, h); const base = y + h * 0.66, a = x + w * 0.33, b = x + w * 0.66;
  candle(doc, a, 8, y + h * 0.22, y + h * 0.42, y + h * 0.16, y + h * 0.48, G);
  candle(doc, b, 8, y + h * 0.24, y + h * 0.42, y + h * 0.18, y + h * 0.48, G);
  doc.save().fillColor(OR).fillOpacity(0.7).rect(a - 5, base, 10, y + h * 0.94 - base).fill().restore();
  doc.save().fillColor(OR).fillOpacity(0.7).rect(b - 5, y + h * 0.86, 10, y + h * 0.94 - (y + h * 0.86)).fill().restore();
  doc.font("kr").fontSize(5.5).fillColor(MU).text("거래량 큼", a - 14, y + h - 9, { width: 28, align: "center", lineBreak: false });
  doc.fillColor(MU).text("작음", b - 12, y + h - 9, { width: 24, align: "center", lineBreak: false });
}

/* 3) 변동성: 작은 봉들 vs 큰 봉들 */
function volatility(doc, x, y, w, h) {
  frameBox(doc, x, y, w, h); const mid = y + h * 0.45;
  const small = [x + w * 0.15, x + w * 0.27, x + w * 0.39];
  const big = [x + w * 0.62, x + w * 0.76, x + w * 0.90];
  small.forEach((cx, i) => candle(doc, cx, 6, mid - 4, mid + 4, mid - 7, mid + 7, i % 2 ? R : G));
  big.forEach((cx, i) => candle(doc, cx, 7, mid - 11, mid + 11, mid - 16, mid + 16, i % 2 ? R : G));
  cap(doc, x, y + h - 10, w, "조용          거침");
}

/* 4) 다중 타임프레임: 큰 하락 화살표 + 작은 상승 화살표 */
function mtf(doc, x, y, w, h) {
  frameBox(doc, x, y, w, h);
  arrow(doc, x + w * 0.32, y + h * 0.18, x + w * 0.5, y + h * 0.82, R, 2.5);
  arrow(doc, x + w * 0.6, y + h * 0.72, x + w * 0.72, y + h * 0.42, G, 1.5);
  doc.font("kr").fontSize(5.5).fillColor(R).text("일봉↓", x + w * 0.16, y + h * 0.22, { lineBreak: false });
  doc.fillColor(G).text("5분↑", x + w * 0.66, y + h * 0.74, { lineBreak: false });
  cap(doc, x, y + h - 10, w, "큰 흐름 속 반등");
}

/* 5) 모멘텀: 올라가는 화살표 + 기준선 */
function momentum(doc, x, y, w, h) {
  frameBox(doc, x, y, w, h); const b = y + h * 0.6;
  doc.save().lineWidth(0.5).strokeColor(LINE).dash(2, { space: 2 }).moveTo(x + 7, b).lineTo(x + w - 7, b).stroke().undash().restore();
  arrow(doc, x + w * 0.18, y + h * 0.72, x + w * 0.82, y + h * 0.26, BL, 2);
  cap(doc, x, y + h - 10, w, "같은 방향으로 관성");
}

/* 6) 윗꼬리×거래량 신호(히어로): 긴 윗꼬리 봉 + 큰 거래량 */
function signal(doc, x, y, w, h) {
  frameBox(doc, x, y, w, h); const cx = x + w * 0.42, base = y + h * 0.64;
  candle(doc, cx, 10, y + h * 0.50, y + h * 0.60, y + h * 0.14, y + h * 0.60, R); // 긴 윗꼬리
  doc.save().fillColor(OR).fillOpacity(0.7).rect(cx - 6, base, 12, y + h * 0.92 - base).fill().restore();
  doc.save().lineWidth(0.5).strokeColor(MU).dash(1, { space: 1 }).moveTo(cx + 8, y + h * 0.14).lineTo(x + w - 6, y + h * 0.14).stroke().undash().restore();
  doc.font("kr").fontSize(5.5).fillColor(MU).text("긴 윗꼬리", x + w - 42, y + h * 0.12, { width: 40, lineBreak: false });
  doc.fillColor(OR).text("거래량 큼", x + w - 42, base + 2, { width: 40, lineBreak: false });
  cap(doc, x, y + h - 9, w, "둘 곱이 크면 신호");
}

const DIAGRAMS = [maAlign, supRes, volume, volatility, mtf, momentum, signal];
module.exports = { DIAGRAMS };
