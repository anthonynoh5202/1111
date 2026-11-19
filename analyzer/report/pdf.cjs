/* 학습용 PDF 보고서 (브라우저 없이, 클라우드에서도 됨).
   1쪽 요약(핵심 숫자·단타 관점·타임프레임 표) → 타임프레임 차트 6개(쪽마다 2개) → 유형 B 상세 → 분석 이론 → 개념 사전.
   한글 폰트: report/fonts/NanumGothic(번들)을 먼저, 없으면 윈도우 맑은 고딕. */
const PDFDocument = require("pdfkit");
const fs = require("fs"), path = require("path");
const { drawChart, COLORS } = require("./chart.cjs");
const { DIAGRAMS } = require("./diagrams.cjs");

const HERE = __dirname;
function pick(list) { for (const p of list) if (p && fs.existsSync(p)) return p; return null; }
const REG = pick([path.join(HERE, "fonts", "NanumGothic-Regular.ttf"), path.join(HERE, "fonts", "NotoSansKR-Regular.ttf"), "C:\\Windows\\Fonts\\malgun.ttf"]);
const BOLD = pick([path.join(HERE, "fonts", "NanumGothic-Bold.ttf"), path.join(HERE, "fonts", "NotoSansKR-Bold.ttf"), "C:\\Windows\\Fonts\\malgunbd.ttf"]) || REG;

/* 색: 남색 하나를 강조로, 나머지는 회색 단계. 오름·내림은 채도를 낮춘 초록·빨강. */
const INK = "#0f172a", TEXT = "#334155", MUTE = "#64748b", FAINT = "#94a3b8", LINE = "#e2e8f0", PANEL = "#f6f7f9";
const ACCENT = "#1e3a5f", UP = COLORS.up, DN = COLORS.dn, NEUTRAL = "#64748b", WARN = "#a16207", WARN_BG = "#fbf7ee";

const fmt = n => Math.round(n).toLocaleString("en-US");
const pct = n => (n >= 0 ? "+" : "") + Number(n).toFixed(3) + "%p";
const signed = (n, d) => (n >= 0 ? "+" : "") + Number(n).toFixed(d) + "%";
function callColor(s) { s = String(s || ""); if (/롱|상승/.test(s)) return UP; if (/숏|하락/.test(s)) return DN; return NEUTRAL; }
const LH = { lineGap: 2.2 };

const cw = doc => doc.page.width - doc.page.margins.left - doc.page.margins.right;
const ML = doc => doc.page.margins.left;

/* ---- 머리글·꼬리글: 모든 쪽을 다 만든 뒤 한꺼번에 그린다(쪽 번호 때문에) ---- */
let CUR = { label: "", foot: "" }; const PAGES = [];
function chrome(doc, meta, i, total) {
  const x = ML(doc), w = cw(doc), bottom = doc.page.margins.bottom;
  doc.page.margins.bottom = 0;
  doc.font("kr-bold").fontSize(7.5).fillColor(INK).text("BTC/USDT", x, 28, { lineBreak: false, characterSpacing: 0.6 });
  doc.font("kr").fontSize(7.5).fillColor(MUTE).text("분석 보고서", x + 44, 28, { lineBreak: false });
  doc.font("kr").fontSize(7.5).fillColor(MUTE).text(meta.label, x, 28, { width: w, align: "right", lineBreak: false });
  doc.save().lineWidth(0.6).strokeColor(INK).moveTo(x, 42).lineTo(x + w, 42).stroke().restore();
  const fy = doc.page.height - 36;
  doc.save().lineWidth(0.5).strokeColor(LINE).moveTo(x, fy).lineTo(x + w, fy).stroke().restore();
  doc.font("kr").fontSize(6.8).fillColor(FAINT).text(meta.foot || "자동 생성 · 매매·투자 조언 아님 · 기준값은 2020~2023 자료로 고정", x, fy + 7, { width: w - 40, lineBreak: false });
  doc.font("kr").fontSize(6.8).fillColor(MUTE).text(i + " / " + total, x, fy + 7, { width: w, align: "right", lineBreak: false });
  doc.page.margins.bottom = bottom;
}
function startPage(doc, label, foot) { CUR = { label, foot }; doc.addPage(); }
function ensureSpace(doc, need) { if (doc.y + need > doc.page.height - doc.page.margins.bottom) doc.addPage(); }

/* ---- 공통 부품 ---- */
function eyebrow(doc, t, color) {
  doc.font("kr-bold").fontSize(7.5).fillColor(color || ACCENT).text(t, ML(doc), doc.y, { characterSpacing: 0.8 });
}
function pageTitle(doc, kicker, title, lead) {
  eyebrow(doc, kicker);
  doc.moveDown(0.25);
  doc.font("kr-bold").fontSize(20).fillColor(INK).text(title, ML(doc), doc.y, { width: cw(doc) });
  if (lead) { doc.moveDown(0.35); doc.font("kr").fontSize(8.8).fillColor(MUTE).text(lead, { width: cw(doc) * 0.86, ...LH }); }
  doc.moveDown(1);
}
function section(doc, title, note) {
  ensureSpace(doc, 60);
  doc.moveDown(0.6);
  const x = ML(doc), w = cw(doc), y = doc.y;
  doc.font("kr-bold").fontSize(10.5).fillColor(INK).text(title, x, y, { lineBreak: false });
  if (note) doc.font("kr").fontSize(7.5).fillColor(FAINT).text(note, x, y + 2.5, { width: w, align: "right", lineBreak: false });
  doc.save().lineWidth(0.5).strokeColor(LINE).moveTo(x, y + 17).lineTo(x + w, y + 17).stroke().restore();
  doc.x = x; doc.y = y + 25;
}
/* 회색 바탕 판. lines = [{t, bold, size, color}] */
function panel(doc, lines, opt) {
  opt = opt || {}; const x = opt.x == null ? ML(doc) : opt.x, w = opt.w || cw(doc), pad = 11, rule = opt.rule ? 3 : 0;
  const inner = w - pad * 2 - rule;
  let h = pad * 2;
  for (const ln of lines) { doc.font(ln.bold ? "kr-bold" : "kr").fontSize(ln.size || 9); h += doc.heightOfString(ln.t, { width: inner, ...LH }) + (ln.gap == null ? 3 : ln.gap); }
  h -= 3; if (opt.minH) h = Math.max(h, opt.minH);
  const y = opt.y == null ? doc.y : opt.y;
  if (opt.measure) return h;
  doc.save().roundedRect(x, y, w, h, 4).fill(opt.bg || PANEL).restore();
  if (rule) doc.save().rect(x, y, rule, h).fill(opt.rule).restore();
  let yy = y + pad;
  for (const ln of lines) {
    doc.font(ln.bold ? "kr-bold" : "kr").fontSize(ln.size || 9).fillColor(ln.color || TEXT)
      .text(ln.t, x + pad + rule, yy, { width: inner, characterSpacing: ln.spacing || 0, ...LH });
    yy = doc.y + (ln.gap == null ? 3 : ln.gap);
  }
  if (opt.y == null) { doc.y = y + h + 10; doc.x = ML(doc); }
  return h;
}
/* 핵심 숫자 줄: 칸마다 작은 이름 + 큰 값 + 보조 글 */
function kpis(doc, items) {
  const x = ML(doc), w = cw(doc), n = items.length, colW = w / n, y = doc.y, h = 54;
  doc.save().lineWidth(0.5).strokeColor(LINE).moveTo(x, y).lineTo(x + w, y).moveTo(x, y + h).lineTo(x + w, y + h).stroke().restore();
  items.forEach((it, k) => {
    const cx = x + k * colW + (k ? 12 : 0), iw = colW - (k ? 16 : 4);
    if (k) doc.save().lineWidth(0.5).strokeColor(LINE).moveTo(x + k * colW, y + 10).lineTo(x + k * colW, y + h - 10).stroke().restore();
    doc.font("kr").fontSize(7).fillColor(MUTE).text(it.label, cx, y + 9, { width: iw, lineBreak: false });
    let fs = 14.5; doc.font("kr-bold"); while (fs > 9 && doc.fontSize(fs).widthOfString(it.value) > iw) fs -= 0.5;
    doc.fontSize(fs).fillColor(it.color || INK).text(it.value, cx, y + 20 + (14.5 - fs) * 0.6, { width: iw, lineBreak: false });
    if (it.sub) doc.font("kr").fontSize(6.8).fillColor(FAINT).text(it.sub, cx, y + 39, { width: iw, lineBreak: false });
  });
  doc.y = y + h + 14; doc.x = x;
}
/* 작은 색 견본 + 이름 줄(차트 범례) */
function legend(doc, items, x, y, right) {
  let xx = x;
  doc.font("kr").fontSize(6.6);
  for (const it of items) {
    doc.save().lineWidth(it.bar ? 4 : 1.2).strokeColor(it.color).strokeOpacity(it.bar ? 0.35 : 1);
    if (it.dash) doc.dash(2, { space: 1.5 });
    doc.moveTo(xx, y + 3.6).lineTo(xx + 10, y + 3.6).stroke().undash().restore();
    doc.fillColor(MUTE).text(it.t, xx + 13, y, { lineBreak: false });
    xx += 13 + doc.widthOfString(it.t) + 10;
  }
  if (right) doc.fillColor(FAINT).text(right.t, x, y, { width: right.w, align: "right", lineBreak: false });
}
const LEGEND_TF = [
  { color: COLORS.ma20, t: "20봉 평균" }, { color: COLORS.ma60, t: "60봉 평균" }, { color: COLORS.vma, t: "거래량 20봉 평균" },
  { color: COLORS.res, t: "저항", dash: true }, { color: COLORS.sup, t: "지지", dash: true }
];

/* ---- 1쪽: 요약 ---- */
function pageSummary(doc, data) {
  const r = data.result, v = r && r.verdict, src = r && r.source;
  pageTitle(doc, "BTC/USDT 무기한 · 멀티 타임프레임", "오늘의 차트 요약",
    (src ? "기준 " + src.last_closed_bar_kst + " KST 마감 봉 · 읽은 시각 " + src.read_at_kst + " · " : "") +
    "OKX 실시간 미리보기(바이낸스 선물과 약 90% 일치). 판정 숫자는 계산이 내고, 해설은 참고용 의견입니다.");
  if (v) kpis(doc, [
    { label: "지금 가격", value: fmt(v.close), sub: "4시간봉 종가" },
    { label: "검증 신호 (4시간봉)", value: v.signal, color: callColor(v.signal), sub: "신호값 " + (v.signal_value != null ? v.signal_value.toFixed(3) : "-") + " · 롱 기준 " + v.long_threshold },
    { label: "크기 상태", value: v.size_state, sub: "다음 16시간 보통 ±" + v.typical_move_pct.toFixed(2) + "%" },
    { label: "다음 16시간 범위 (5번 중 4번)", value: fmt(v.band_16h[0]) + "–" + fmt(v.band_16h[1]), sub: "방향이 아니라 폭의 예측" }
  ]);
  panel(doc, [
    { t: "클로드 단타 관점  ·  검증 안 된 의견", bold: true, size: 7.5, color: WARN, spacing: 0.4, gap: 5 },
    { t: data.scalp || "(단타 관점이 아직 작성되지 않았습니다.)", size: 9.2, color: INK }
  ], { bg: WARN_BG, rule: "#d6b36a" });

  section(doc, "타임프레임 한눈에", "객관 구조 계산 · 예측 아님");
  summaryTable(doc, data);
  doc.moveDown(0.7);
  doc.font("kr").fontSize(7.8).fillColor(MUTE).text("유형 A = 클로드가 차트를 보고 낸 의견(검증 안 됨).  유형 B = 2020~2023 자료로 기준을 고정한 검증 신호(4시간봉 전용). 다른 봉의 추세·지지·저항은 계산일 뿐 방향 예측이 아닙니다.", ML(doc), doc.y, { width: cw(doc), ...LH });
  contents(doc, data);
}
/* 이 보고서의 구성(1쪽 아래) */
function contents(doc, data) {
  const n = (data.mtf || []).length, chartPages = n, rows = [];
  let p = 2;
  if (chartPages) { rows.push([p + (chartPages > 1 ? "–" + (p + chartPages - 1) : ""), "타임프레임별 차트", "5분부터 일봉까지 한 쪽에 하나씩. 클로드가 차트에 번호를 그리고(유형 A) 번호별로 설명."]); p += chartPages; }
  if (data.result) rows.push([String(p++), "유형 B 상세", "4시간봉 검증 신호가 어떻게 나왔는지, 차트 번호별 근거."]);
  rows.push([String(p++), "분석 이론", "추세·지지/저항·거래량·변동성·모멘텀과 검증된 신호의 원리."]);
  rows.push([String(p++), "개념 사전", "보고서에 나오는 용어 풀이."]);
  section(doc, "이 보고서의 구성");
  const x = ML(doc), w = cw(doc);
  for (const [pg, t, d] of rows) {
    const y = doc.y;
    doc.font("kr-bold").fontSize(8).fillColor(ACCENT).text(pg + "쪽", x, y + 1, { width: 40, lineBreak: false });
    doc.font("kr-bold").fontSize(9).fillColor(INK).text(t, x + 46, y, { width: 110, lineBreak: false });
    doc.font("kr").fontSize(8.4).fillColor(TEXT).text(d, x + 160, y + 0.5, { width: w - 160, lineBreak: false });
    doc.y = y + 15;
    doc.save().lineWidth(0.5).strokeColor(LINE).moveTo(x, doc.y).lineTo(x + w, doc.y).stroke().restore();
    doc.y += 8;
  }
}
function summaryTable(doc, data) {
  const x = ML(doc), w = cw(doc), tf = (data.pageA && data.pageA.tf) || {};
  const cols = [
    { t: "타임프레임", w: 0.16 }, { t: "추세", w: 0.11 }, { t: "24봉 변화", w: 0.12, right: true }, { t: "변동성", w: 0.11, right: true },
    { t: "지지", w: 0.13, right: true }, { t: "저항", w: 0.13, right: true }, { t: "클로드 의견", w: 0.24, pad: 14 }
  ];
  let y = doc.y;
  const cell = (k, text, yy, style) => {
    let cx = x; for (let j = 0; j < k; j++) cx += cols[j].w * w;
    const c = cols[k], cwid = c.w * w - 6;
    doc.font(style.bold ? "kr-bold" : "kr").fontSize(style.size).fillColor(style.color || TEXT)
      .text(text, cx + (c.pad || 0), yy, { width: cwid - (c.pad || 0), align: c.right ? "right" : "left", lineBreak: false });
  };
  cols.forEach((c, k) => cell(k, c.t, y, { size: 7, color: MUTE }));
  y += 14;
  doc.save().lineWidth(0.6).strokeColor(INK).moveTo(x, y).lineTo(x + w, y).stroke().restore();
  for (const m of (data.mtf || [])) {
    const rowH = 23, ty = y + 7.5;
    cell(0, m.label, ty, { size: 9, bold: true, color: INK });
    if (m.error) cell(1, "자료 읽기 실패", ty, { size: 8.5, color: FAINT });
    else {
      const tc = callColor(m.trend);
      let cx = x + cols[0].w * w;
      doc.save().circle(cx + 3, ty + 4.5, 2.6).fill(tc).restore();
      doc.font("kr-bold").fontSize(8.8).fillColor(tc).text(m.trend, cx + 10, ty, { lineBreak: false });
      cell(2, signed(m.chg, 1), ty, { size: 8.8, color: m.chg >= 0 ? UP : DN });
      cell(3, "±" + m.volPct.toFixed(2) + "%", ty, { size: 8.8 });
      cell(4, m.sup ? fmt(m.sup) : "–", ty, { size: 8.8 });
      cell(5, m.res ? fmt(m.res) : "–", ty, { size: 8.8 });
    }
    const a = tf[m.bar] || {};
    cell(6, a.call || "–", ty, { size: 8.8, bold: true, color: callColor(a.call) });
    y += rowH;
    doc.save().lineWidth(0.5).strokeColor(LINE).moveTo(x, y).lineTo(x + w, y).stroke().restore();
  }
  doc.y = y; doc.x = x;
}

/* page_a.json 의 표시(marks)를 검사한다. 클로드가 쓴 값이라 모양·범위를 확인하고, 틀린 것은 뺀다. */
const MARK_TYPES = ["level", "bar", "zone", "trend"];
function cleanMarks(marks, nBars) {
  if (!Array.isArray(marks)) return [];
  const num = v => (typeof v === "number" && Number.isFinite(v) && v > 0) ? v : null;
  const ago = v => (Number.isInteger(v) && v >= 0 && v < nBars) ? v : null;
  const out = [];
  for (const m of marks.slice(0, 6)) {
    if (!m || !MARK_TYPES.includes(m.type) || typeof m.text !== "string" || !m.text.trim()) continue;
    const a = { n: out.length + 1, type: m.type, text: m.text.trim().slice(0, 220), price: num(m.price), price2: num(m.price2), ago: ago(m.ago), ago2: ago(m.ago2) };
    if (a.type === "level" && a.price == null) continue;
    if (a.type === "bar" && a.ago == null) continue;
    if (a.type === "zone" && (a.price == null || a.price2 == null)) continue;
    if (a.type === "trend" && (a.price == null || a.price2 == null || a.ago == null || a.ago2 == null)) continue;
    out.push(a);
  }
  return out;
}

/* ---- 타임프레임 한 쪽: 머리줄 + 큰 차트(클로드 표시 포함) + 유형 A 번호별 설명 + 유형 B 칸 ---- */
function tfBlock(doc, m, aRead, result) {
  const x = ML(doc), w = cw(doc), y0 = doc.y, a = aRead || {};
  doc.font("kr-bold").fontSize(16).fillColor(INK).text(m.label, x, y0, { lineBreak: false });
  const lw = doc.widthOfString(m.label);
  doc.font("kr").fontSize(8.5).fillColor(FAINT).text(m.bar, x + lw + 7, y0 + 6, { lineBreak: false });
  if (!m.error) {
    const parts = [["추세 ", m.trend, callColor(m.trend)], ["   24봉 ", signed(m.chg, 1), m.chg >= 0 ? UP : DN], ["   변동성 ", "±" + m.volPct.toFixed(2) + "%", INK]];
    doc.font("kr").fontSize(8);
    let tw = 0; for (const [k, val] of parts) { doc.font("kr"); tw += doc.widthOfString(k); doc.font("kr-bold"); tw += doc.widthOfString(val); }
    let xx = x + w - tw;
    for (const [k, val, col] of parts) {
      doc.font("kr").fillColor(MUTE).text(k, xx, y0 + 6, { lineBreak: false }); xx += doc.widthOfString(k);
      doc.font("kr-bold").fillColor(col).text(val, xx, y0 + 6, { lineBreak: false }); xx += doc.widthOfString(val);
    }
  }
  const hasChart = m.chart && m.chart.bars && m.chart.bars.length;
  const marks = hasChart ? cleanMarks(a.marks, m.chart.bars.length) : [];
  const cy = y0 + 28, ch = 380;
  if (hasChart) drawChart(doc, { x, y: cy, w, h: ch }, { ...m.chart, annotations: marks });
  else doc.font("kr").fontSize(9).fillColor(FAINT).text("(차트 자료 없음)", x, cy + 120, { width: w, align: "center" });
  const rg = m.chart && m.chart.range;
  legend(doc, LEGEND_TF.concat(marks.length ? [{ color: COLORS.ann, t: "클로드 표시" }] : []), x, cy + ch + 5, rg ? { t: "봉 " + rg.n + "개 · " + rg.from + " ~ " + rg.to, w } : null);
  doc.y = cy + ch + 24;

  // 유형 A: 의견 + 번호별 설명
  const hy = doc.y;
  doc.font("kr-bold").fontSize(7.5).fillColor(COLORS.ann).text("유형 A · 클로드 차트 분석", x, hy, { characterSpacing: 0.6, lineBreak: false });
  doc.font("kr").fontSize(7.5).fillColor(FAINT).text("검증 안 된 의견", x, hy, { width: w, align: "right", lineBreak: false });
  doc.save().lineWidth(0.5).strokeColor(LINE).moveTo(x, hy + 14).lineTo(x + w, hy + 14).stroke().restore();
  doc.y = hy + 22;
  const callY = doc.y;
  doc.font("kr-bold").fontSize(15).fillColor(callColor(a.call)).text(a.call || "–", x, callY, { lineBreak: false });
  doc.font("kr").fontSize(8.6).fillColor(TEXT).text(a.note || "(의견 없음)", x + 62, callY + 2, { width: w - 62, ...LH });
  doc.y = Math.max(doc.y, callY + 20) + 8;
  for (const mk of marks) {
    ensureSpace(doc, 24);
    const yy = doc.y;
    doc.save().roundedRect(x, yy, 13, 13, 3).fill(COLORS.ann).restore();
    doc.font("kr-bold").fontSize(7.5).fillColor("#ffffff").text(String(mk.n), x, yy + 2.6, { width: 13, align: "center", lineBreak: false });
    doc.font("kr").fontSize(8.6).fillColor(TEXT).text(mk.text, x + 22, yy + 1, { width: w - 22, ...LH });
    doc.y += 5;
  }
  if (!marks.length && a.call) { doc.font("kr").fontSize(7.8).fillColor(FAINT).text("(차트에 그린 표시가 없습니다.)", x, doc.y); doc.moveDown(0.4); }

  // 유형 B 칸(한 줄)
  doc.moveDown(0.5); ensureSpace(doc, 60);
  let B;
  if (m.error) B = [{ t: "유형 B", bold: true, size: 6.8, color: MUTE, gap: 3 }, { t: "자료 읽기 실패", size: 8.4, color: FAINT }];
  else if (m.bar === "4H" && result) {
    const v = result.verdict;
    B = [{ t: "유형 B · 검증 신호", bold: true, size: 6.8, color: ACCENT, spacing: 0.4, gap: 4 },
    { t: v.signal + "  —  신호값 " + (v.signal_value != null ? v.signal_value.toFixed(3) : "-") + " (롱 기준 " + v.long_threshold + ") · 크기 " + v.size_state + " · 16시간 ±" + v.p80_move_pct.toFixed(2) + "%. 근거는 '유형 B 상세' 쪽.", size: 8.4, color: INK }];
  } else {
    B = [{ t: "유형 B 자리 · 객관 구조 (검증 신호 아님)", bold: true, size: 6.8, color: MUTE, spacing: 0.4, gap: 4 },
    { t: "계산된 지지 " + (m.sup ? fmt(m.sup) : "–") + " / 저항 " + (m.res ? fmt(m.res) : "–") + " (차트의 초록·빨강 점선). 이동평균 배열 · 지지/저항 · 거래량 · 변동성 · 모멘텀으로 계산.", size: 8.4, color: INK }];
  }
  panel(doc, B);
}

/* ---- 유형 B: 4시간봉 검증 신호 상세 ---- */
function gauge(doc, x, y, w, v) {
  const max = Math.max(0.6, (v.signal_value || 0) * 1.15), X = t => x + Math.min(1, t / max) * w;
  doc.save().roundedRect(x, y, w, 7, 3.5).fill("#eef1f5").restore();
  doc.save().fillOpacity(0.25).fillColor(DN).rect(x, y, X(v.short_threshold) - x, 7).fill().restore();
  doc.save().fillOpacity(0.25).fillColor(UP).rect(X(v.long_threshold), y, x + w - X(v.long_threshold), 7).fill().restore();
  doc.font("kr").fontSize(6.3).fillColor(FAINT);
  doc.text("숏(기록만) " + v.short_threshold, x, y + 11, { lineBreak: false });
  doc.text("롱 " + v.long_threshold, X(v.long_threshold) - 1, y + 11, { lineBreak: false });
  if (v.signal_value != null) {
    const mx = X(v.signal_value);
    doc.save().lineWidth(1.5).circle(mx, y + 3.5, 5).fillAndStroke(INK, "#ffffff").restore();
    doc.font("kr-bold").fontSize(7).fillColor(INK).text(v.signal_value.toFixed(3), mx - 20, y - 12, { width: 40, align: "center", lineBreak: false });
  }
}
function pageB(doc, data) {
  const r = data.result, v = r.verdict, x = ML(doc), w = cw(doc);
  eyebrow(doc, "유형 B · 2020~2023 자료로 기준을 고정한 검증 신호");
  doc.moveDown(0.3);
  const y = doc.y;
  doc.font("kr-bold").fontSize(30).fillColor(callColor(v.signal)).text(v.signal, x, y, { lineBreak: false });
  doc.font("kr").fontSize(8.5).fillColor(MUTE).text("방향 " + v.direction + " · 크기 " + v.size_state, x, y + 40, { lineBreak: false });
  doc.font("kr").fontSize(6.8).fillColor(MUTE).text("신호값 = 윗꼬리 비율 × 거래량 배수", x + w * 0.42, y + 4, { width: w * 0.58, lineBreak: false });
  gauge(doc, x + w * 0.42, y + 28, w * 0.58, v);
  doc.y = y + 64;

  section(doc, "차트", "번호는 아래 '번호별 근거'와 짝입니다");
  const cy = doc.y, ch = 215;
  if (data.chart && data.chart.bars && data.chart.bars.length) drawChart(doc, { x, y: cy, w, h: ch }, data.chart);
  const rg = data.chart && data.chart.range;
  legend(doc, LEGEND_TF.concat([{ color: COLORS.band, t: "다음 16시간 범위", bar: true }]), x, cy + ch + 5, rg ? { t: "봉 " + rg.n + "개 · " + rg.from + " ~ " + rg.to, w } : null);
  doc.y = cy + ch + 22;

  const calc = v.signal_value != null
    ? "신호값 " + v.signal_value.toFixed(3) + " = 윗꼬리 비율 × 거래량 배수. " + v.long_threshold + " 이상이면 '롱', " + v.short_threshold + " 이하면 '숏(기록만)', 그 사이면 '없음'."
    : "이번 봉은 신호값을 계산할 수 없었습니다.";
  let range = "다음 16시간 보통 ±" + v.typical_move_pct.toFixed(2) + "%, 5번 중 4번은 " + fmt(v.band_16h[0]) + " ~ " + fmt(v.band_16h[1]) + " (지금 " + fmt(v.close) + "). 최근 6봉 평균 크기 " + v.recent_size_pct.toFixed(2) + "%.";
  if (v.signal === "롱") {
    if (!v.is_9pm_bar) range += " 밤 9시 마감 봉이 아니라 실전 대상이 아닙니다(기록만).";
    else if (v.minutes_since_close > 15) range += " 마감 뒤 " + v.minutes_since_close.toFixed(0) + "분 지남. 규칙상 15분이 넘으면 건너뜁니다.";
    else range += " 실전 대상. 청산 " + (v.exit_kst || "-") + " KST. 주문은 사람이 직접.";
  }
  const gap = 10, colW = (w - gap) / 2, py = doc.y;
  const L = [{ t: "어떻게 이 신호가 나왔나", bold: true, size: 6.8, color: ACCENT, spacing: 0.4, gap: 4 }, { t: calc, size: 8.4 }];
  const R = [{ t: "크기와 예상 범위", bold: true, size: 6.8, color: ACCENT, spacing: 0.4, gap: 4 }, { t: range, size: 8.4 }];
  const h = Math.max(panel(doc, L, { w: colW, measure: true }), panel(doc, R, { w: colW, measure: true }));
  panel(doc, L, { x, y: py, w: colW, minH: h }); panel(doc, R, { x: x + colW + gap, y: py, w: colW, minH: h });
  doc.y = py + h + 4;

  section(doc, "번호별 근거");
  (r.why || []).forEach((t, i) => {
    ensureSpace(doc, 30);
    const yy = doc.y;
    doc.save().circle(x + 6, yy + 5.5, 6).fill(i < 4 ? INK : FAINT).restore();
    doc.font("kr-bold").fontSize(7).fillColor("#ffffff").text(String(i + 1), x, yy + 1.8, { width: 12, align: "center", lineBreak: false });
    doc.font("kr").fontSize(8.4).fillColor(TEXT).text(t, x + 20, yy, { width: w - 20, ...LH });
    doc.y += 4;
  });

  const f = r.forward_test;
  if (f) {
    doc.moveDown(0.4); ensureSpace(doc, 50);
    panel(doc, [{ t: "처음 보는 자료 성적  ·  2026-09-29 이후", bold: true, size: 6.8, color: MUTE, spacing: 0.4, gap: 4 },
    { t: "봉 " + f.bars + "개, 롱 신호 " + f.long_signals + "번" + (f.long_signals ? " · 평균 " + pct(f.long_mean_pct) + " (아무 때나 롱 " + pct(f.baseline_pct) + ", t " + (f.t == null ? "-" : f.t) + "). 표본이 작아 아직 판정하지 않습니다." : ""), size: 8.4 }]);
  }
}

/* ---- 개념 사전 ---- */
const GLOSSARY = [
  ["봉(캔들)", "4시간 동안의 시가·고가·저가·종가를 막대 하나로 나타낸 것. 굵은 몸통은 시가~종가, 가는 선(꼬리)은 그 시간의 최고·최저까지입니다."],
  ["윗꼬리 / 윗꼬리 비율", "봉 위로 삐친 선. 위로 올랐다가 되밀린 흔적입니다. '윗꼬리 비율'은 봉 전체 길이 중 윗꼬리가 차지하는 몫(0~1)으로, 클수록 위에서 눌린 것입니다."],
  ["거래량 / 20봉 평균 / 거래량 배수", "거래량은 그 봉 동안 사고판 양입니다. '20봉 평균'은 직전 20개 봉 거래량의 평균(차트 회색선). '거래량 배수'는 이번 봉 거래량 ÷ 그 평균으로, 1보다 크면 평소보다 활발한 것입니다."],
  ["신호값", "이 분석기의 핵심 숫자 = 윗꼬리 비율 × 거래량 배수. 위에서 눌렸는데(윗꼬리) 거래까지 터지면 값이 커집니다. 롱 기준 0.422 이상이면 '롱', 0.086 이하면 '숏(기록만)', 그 사이는 '없음'. 기준값은 2020~2023 자료로 정해 고정했습니다."],
  ["롱 / 숏", "롱은 오를 것에 베팅, 숏은 내릴 것에 베팅입니다. 이 분석기의 숏은 과거 두 기간 모두 손해라 실전은 안 하고 기록만 합니다."],
  ["이동평균선 (20·60·120봉)", "최근 N개 봉 종가의 평균을 이은 선으로 추세의 큰 방향을 봅니다. 20<60<120이면 역배열(내림세 정렬), 20>60>120이면 정배열(오름세 정렬)입니다."],
  ["지지 / 저항", "지지는 아래에서 가격을 받쳐온 가격대, 저항은 위에서 눌러온 가격대입니다. 뚫리면 그 방향으로 더 가기 쉽습니다. (과거 검증에서 방향 적중력이 확인되지 않아 참고용입니다.)"],
  ["크기 상태 (조용·보통·거침)", "최근 6봉(24시간)의 봉 크기 평균으로 장이 얼마나 출렁이는지 구분합니다. 1.39% 미만=조용, 1.39~2.14%=보통, 2.14% 이상=거침. 범위 예측에 씁니다."],
  ["다음 16시간 흔한 범위(띠)", "크기 상태를 바탕으로 앞으로 16시간 가격이 머물 법한 범위입니다. 띠는 5번 중 4번이 든 범위(±p80)입니다. 방향이 아니라 '폭'의 예측입니다."],
  ["t값", "어떤 숫자가 '우연이 아닐' 만한지 보는 통계치입니다. 대략 절댓값이 2를 넘으면 의미 있다고 보고, 표본이 작으면 작게 나와 '모름'으로 둡니다."],
  ["밤 9시 봉", "이 전략이 실전으로 삼는 유일한 봉(KST 21시 마감)입니다. 다른 시간대 봉의 신호는 기록만 하고 실전에 넣지 않습니다."],
  ["OKX 미리보기 vs 바이낸스 선물", "클라우드에서 바이낸스 선물 실시간을 못 읽어, 대신 OKX로 미리 봅니다. 바이낸스 신호와 약 90% 일치하고 초과 수익은 약 60% 수준입니다. 확정은 하루 1회 바이낸스 보관소로 따로 기록합니다."],
  ["유형 A vs 유형 B", "A는 클로드가 차트를 보고 낸 '의견'(검증 안 됨), B는 과거 자료로 검증해 기준을 고정한 '신호'입니다. A는 참고, B가 규칙입니다."]
];
/* ---- 기술적 분석 이론 (왜 이렇게 분석했나) ---- */
const THEORIES = [
  ["추세 추종 & 이동평균 배열", "가격 평균선(20·60·120봉)을 겹쳐 방향을 봅니다. 단기선이 장기선 위면 정배열(상승 정렬), 아래면 역배열(하락 정렬). 추세는 한동안 이어진다는 생각(추세 추종)에서, 배열로 그 방향을 단순하게 읽습니다. 한계: 횡보장에선 자주 꼬여 헛신호가 나고, 과거 평균이라 전환은 늦게 잡힙니다."],
  ["지지 · 저항 (수요·공급)", "과거에 가격이 여러 번 멈춘 자리입니다. 아래는 지지, 위는 저항(최근 피벗 고점·저점으로 찾음). 그 가격대에 주문이 몰렸던 기억이 반복되는 경향을 이용합니다. 한계: 미래를 보장하지 않고, 뚫리면 반대로 작용합니다. 이 보고서에선 방향 적중력이 검증되지 않아 참고용입니다."],
  ["거래량 확증", "가격 움직임에 거래량이 실렸는지 봅니다(20봉 평균과 비교한 배수). 거래가 많이 실린 움직임이 더 믿을 만하고, 거래가 적은 움직임은 쉽게 되돌려진다는 생각입니다. 한계: 거래소마다 거래량 기준이 달라 절대 비교가 어렵습니다."],
  ["변동성 (봉 크기)", "최근 봉들이 얼마나 크게 움직였는지로 '앞으로 흔한 범위'(띠)를 가늠합니다. 변동성은 한동안 뭉치는 경향(크면 계속 큼)이 있기 때문입니다. 한계: 폭만 알려줄 뿐 방향은 알려주지 않습니다."],
  ["다중 타임프레임 분석", "같은 종목을 여러 시간대(5분~일봉)로 겹쳐 봅니다. 큰 시간대가 큰 흐름, 작은 시간대가 진입 타이밍을 주고, 상위와 하위가 같은 방향이면 신뢰가 올라갑니다. 한계: 시간대마다 신호가 엇갈리면 오히려 판단이 어려워집니다."],
  ["모멘텀 (변화율)", "최근 일정 기간(예: 24봉) 가격이 몇 % 움직였는지 봅니다. 움직이던 방향으로 좀 더 가려는 관성을 읽습니다. 한계: 급변 뒤 되돌림 구간에선 약합니다."],
  ["윗꼬리 × 거래량 돌파 신호 (유형 B · 유일하게 검증됨)", "윗꼬리 비율 × 거래량 배수로 '위에서 눌렸는데 거래가 터진' 봉을 잡아냅니다. 2020~2023 4시간봉에서 이 값이 큰 뒤 평균적으로 올랐기에(과거 검증) 기준 0.422를 넘으면 '롱'으로 봅니다. 한계: 4시간봉 전용, 초과 수익이 작고, 다른 타임프레임엔 적용할 수 없습니다."]
];
function pageTheory(doc) {
  pageTitle(doc, "학습", "분석 이론", "각 차트의 판단이 어떤 기술·이론에서 나왔는지입니다. 왼쪽 그림은 개념 예시(실제 자료 아님). 기술적 분석은 대부분 경험칙(보장 아님)이며, 과거 자료로 검증된 것은 맨 아래 유형 B 하나뿐입니다.");
  const x = ML(doc), w = cw(doc), dw = 112, dh = 64, gap = 16, tx = x + dw + gap, tw = w - dw - gap;
  THEORIES.forEach(([t, d], i) => {
    const top = doc.y, last = i === THEORIES.length - 1;
    if (DIAGRAMS[i]) DIAGRAMS[i](doc, x, top, dw, dh);
    doc.font("kr").fontSize(7).fillColor(last ? ACCENT : FAINT).text(String(i + 1).padStart(2, "0") + (last ? "  ·  검증됨" : ""), tx, top + 1, { characterSpacing: 0.5 });
    doc.font("kr-bold").fontSize(10).fillColor(INK).text(t, tx, doc.y + 1, { width: tw });
    doc.font("kr").fontSize(8.2).fillColor(TEXT).text(d, tx, doc.y + 2, { width: tw, ...LH });
    doc.y = Math.max(doc.y, top + dh) + 9;
    if (!last) doc.save().lineWidth(0.5).strokeColor(LINE).moveTo(x, doc.y).lineTo(x + w, doc.y).stroke().restore();
    doc.y += 9; doc.x = x;
  });
}

function pageGlossary(doc) {
  pageTitle(doc, "학습", "개념 사전", "보고서에 나온 말을 쉽게 풀었습니다. 한 번 익혀 두면 다음부터 훨씬 잘 읽힙니다.");
  const x = ML(doc), w = cw(doc), tw = 128, dx = x + tw + 12, dw = w - tw - 12;
  doc.save().lineWidth(0.6).strokeColor(INK).moveTo(x, doc.y).lineTo(x + w, doc.y).stroke().restore();
  doc.y += 9;
  for (const [t, d] of GLOSSARY) {
    doc.font("kr").fontSize(8.4);
    const hd = doc.heightOfString(d, { width: dw, ...LH });
    doc.font("kr-bold").fontSize(8.8);
    const ht = doc.heightOfString(t, { width: tw });
    ensureSpace(doc, Math.max(hd, ht) + 18);
    const yy = doc.y;
    doc.font("kr-bold").fontSize(8.8).fillColor(INK).text(t, x, yy, { width: tw });
    doc.font("kr").fontSize(8.4).fillColor(TEXT).text(d, dx, yy, { width: dw, ...LH });
    doc.y = yy + Math.max(hd, ht) + 8;
    doc.save().lineWidth(0.5).strokeColor(LINE).moveTo(x, doc.y).lineTo(x + w, doc.y).stroke().restore();
    doc.y += 8;
  }
}

function buildPdf(outPath, data) {
  if (!REG) throw new Error("한글 폰트를 찾지 못했습니다. report/fonts/ 에 NanumGothic-Regular.ttf 를 두거나 윈도우 맑은 고딕이 필요합니다.");
  PAGES.length = 0;
  const doc = new PDFDocument({ size: "A4", autoFirstPage: false, bufferPages: true, margins: { top: 62, bottom: 52, left: 46, right: 46 }, info: { Title: "BTC 분석 보고서" } });
  const stream = fs.createWriteStream(outPath);
  doc.pipe(stream);
  doc.registerFont("kr", REG);
  doc.registerFont("kr-bold", BOLD);
  doc.on("pageAdded", () => PAGES.push({ ...CUR }));

  const foot = "단타 참고 · 검증된 신호는 4시간봉뿐 · 매매·투자 조언 아님";
  startPage(doc, "요약", foot);
  pageSummary(doc, data);
  const tf = (data.pageA && data.pageA.tf) || {}, list = data.mtf || [];
  for (let i = 0; i < list.length; i++) {
    startPage(doc, "타임프레임별 차트 · " + list[i].label, foot);
    tfBlock(doc, list[i], tf[list[i].bar], data.result);
  }
  if (data.result) { startPage(doc, "유형 B · 4시간봉 검증 상세", "유형 B · OKX 실시간 미리보기(바이낸스 선물과 약 90% 일치) · 확정은 하루 1회 바이낸스 보관소"); pageB(doc, data); }
  startPage(doc, "분석 이론", "분석 이론 · 학습용 · 대부분 경험칙(보장 아님)");
  pageTheory(doc);
  startPage(doc, "개념 사전", "개념 사전 · 학습용");
  pageGlossary(doc);

  const range = doc.bufferedPageRange();
  for (let i = 0; i < range.count; i++) { doc.switchToPage(range.start + i); chrome(doc, PAGES[i] || CUR, i + 1, range.count); }
  doc.end();
  return new Promise((res, rej) => { stream.on("finish", () => res(outPath)); stream.on("error", rej); });
}

module.exports = { buildPdf, cleanMarks };
