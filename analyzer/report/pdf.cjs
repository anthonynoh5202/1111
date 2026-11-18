/* 학습용 PDF 보고서 (브라우저 없이, 클라우드에서도 됨).
   유형 A(클로드 의견) = 차트 + A의 차트 분석 · 유형 B(검증 신호) = 차트 + B의 차트 분석 · 개념 사전.
   한글 폰트: report/fonts/NotoSansKR(클라우드용)을 먼저, 없으면 윈도우 맑은 고딕. */
const PDFDocument = require("pdfkit");
const fs = require("fs"), path = require("path");
const { drawChart } = require("./chart.cjs");
const { DIAGRAMS } = require("./diagrams.cjs");

const HERE = __dirname;
function pick(list) { for (const p of list) if (p && fs.existsSync(p)) return p; return null; }
// 번들 한글 폰트(재배포 가능)를 먼저, 없으면 윈도우 맑은 고딕(로컬 개발용).
const REG = pick([path.join(HERE, "fonts", "NanumGothic-Regular.ttf"), path.join(HERE, "fonts", "NotoSansKR-Regular.ttf"), "C:\\Windows\\Fonts\\malgun.ttf"]);
const BOLD = pick([path.join(HERE, "fonts", "NanumGothic-Bold.ttf"), path.join(HERE, "fonts", "NotoSansKR-Bold.ttf"), "C:\\Windows\\Fonts\\malgunbd.ttf"]) || REG;

const ACCENT = "#4f46e5", INK = "#111827", MUTE = "#6b7280", LINE = "#e5e7eb", SOFT = "#f9fafb";
const GREEN = "#15803d", RED = "#b91c1c", GRAY = "#4b5563", AMBER = "#b45309", AMBER_BG = "#fffbeb", ACC_BG = "#eef2ff";

function cw(doc) { return doc.page.width - doc.page.margins.left - doc.page.margins.right; }
function ML(doc) { return doc.page.margins.left; }
const fmt = n => Math.round(n).toLocaleString("en-US");
const pct = n => (n >= 0 ? "+" : "") + Number(n).toFixed(3) + "%p";
const spanText = min => min < 2880 ? Math.round(min / 60) + "시간" : Math.round(min / 1440) + "일";
function callColor(s) { s = String(s || ""); if (s.includes("롱")) return GREEN; if (s.includes("숏")) return RED; return GRAY; }
function trendColor(t) { return t === "상승" ? GREEN : t === "하락" ? RED : GRAY; }

/* ---- 페이지 틀(머리글·꼬리글): 넘침 페이지에도 자동으로 그려진다 ---- */
let CUR = { label: "", foot: "" };
function topBar(doc) { doc.save().rect(0, 0, doc.page.width, 6).fill(ACCENT).restore(); }
function drawHeader(doc, label) {
  const x = ML(doc), w = cw(doc);
  doc.font("kr-bold").fontSize(8.5).fillColor(MUTE).text("BTC/USDT 분석 보고서", x, 22, { lineBreak: false });
  doc.font("kr").fontSize(8.5).fillColor(ACCENT).text(label, x, 22, { width: w, align: "right", lineBreak: false });
  doc.save().strokeColor(LINE).lineWidth(0.5).moveTo(x, 36).lineTo(x + w, 36).stroke().restore();
}
function drawFooter(doc, text) {
  const x = ML(doc), w = cw(doc), y = doc.page.height - 34, savedBottom = doc.page.margins.bottom;
  doc.page.margins.bottom = 0;
  doc.save().strokeColor(LINE).lineWidth(0.5).moveTo(x, y).lineTo(x + w, y).stroke().restore();
  doc.font("kr").fontSize(7.5).fillColor(MUTE).text(text || "자동 생성 · 매매·투자 조언 아님 · 기준값은 2020~2023 자료로 고정", x, y + 6, { width: w, lineBreak: false });
  doc.page.margins.bottom = savedBottom;
}
function frame(doc) { topBar(doc); drawHeader(doc, CUR.label); drawFooter(doc, CUR.foot); doc.x = doc.page.margins.left; doc.y = doc.page.margins.top; }
function startPage(doc, label, foot, first) { CUR = { label, foot }; if (first) frame(doc); else doc.addPage(); }
function ensureSpace(doc, need) { if (doc.y + need > doc.page.height - doc.page.margins.bottom) doc.addPage(); }

/* ---- 공통 부품 ---- */
function section(doc, title, color) {
  doc.moveDown(0.5);
  const x = ML(doc), y = doc.y;
  doc.save().roundedRect(x, y + 1.5, 3.5, 13, 1).fill(color || ACCENT).restore();
  doc.font("kr-bold").fontSize(12.5).fillColor(INK).text(title, x + 10, y);
  doc.moveDown(0.25); doc.x = x; doc.font("kr").fillColor(INK);
}
function boxLines(doc, lines, style) {
  style = style || {}; const x = ML(doc), w = cw(doc), pad = 9;
  let h = pad * 2;
  for (const ln of lines) { doc.font(ln.bold ? "kr-bold" : "kr").fontSize(ln.size || 9.5); h += doc.heightOfString(ln.t, { width: w - pad * 2 }) + (ln.gap == null ? 2 : ln.gap); }
  const y = doc.y;
  doc.save().roundedRect(x, y, w, h, 5).fillAndStroke(style.bg || SOFT, style.border || LINE).restore();
  let yy = y + pad;
  for (const ln of lines) { doc.font(ln.bold ? "kr-bold" : "kr").fontSize(ln.size || 9.5).fillColor(ln.color || style.fg || INK).text(ln.t, x + pad, yy, { width: w - pad * 2 }); yy = doc.y + (ln.gap == null ? 2 : ln.gap); }
  doc.y = y + h + 6; doc.x = x; doc.fillColor(INK);
}
function callBanner(doc, tag, call, sub) {
  const x = ML(doc), w = cw(doc), h = sub ? 52 : 40, y = doc.y, color = callColor(call);
  doc.save().roundedRect(x, y, w, h, 6).fill(color).restore();
  doc.fillColor("#ffffff").font("kr").fontSize(9.5).text(tag, x + 14, y + 8, { width: w - 28, lineBreak: false });
  doc.font("kr-bold").fontSize(21).fillColor("#ffffff").text(call, x + 14, y + 20, { lineBreak: false });
  if (sub) doc.font("kr").fontSize(9).fillColor("#ffffff").text(sub, x + 150, y + 22, { width: w - 164 });
  doc.y = y + h + 8; doc.x = x; doc.fillColor(INK);
}
function bullets(doc, items, color) {
  doc.font("kr").fontSize(10).fillColor(INK);
  for (const it of items) {
    const x = ML(doc), y = doc.y;
    doc.save().circle(x + 3, y + 5.5, 2).fill(color || ACCENT).restore();
    doc.fillColor(INK).text(it, x + 12, y, { width: cw(doc) - 12, lineGap: 1 });
    doc.moveDown(0.15);
  }
}
function bulletsSm(doc, items, color) {
  doc.font("kr").fontSize(9).fillColor(INK);
  for (const it of items) {
    const x = ML(doc), y = doc.y;
    doc.save().circle(x + 3, y + 5, 1.8).fill(color || ACCENT).restore();
    doc.fillColor(INK).text(it, x + 12, y, { width: cw(doc) - 12, lineGap: 0.5 });
  }
}
/* 차트 + 범례. 유형 A·B 두 페이지가 각자 자기 위에 그린다. */
function chartBlock(doc, data, h) {
  section(doc, "차트 (번호를 아래 설명이 짚습니다)");
  const x = ML(doc), w = cw(doc), y = doc.y;
  if (data.chart && data.chart.bars && data.chart.bars.length) drawChart(doc, { x, y, w, h }, data.chart);
  else doc.font("kr").fontSize(11).fillColor(MUTE).text("(차트 자료 없음)");
  doc.y = y + h + 8; doc.x = x;
  const rg = data.chart && data.chart.range;
  if (rg) doc.font("kr").fontSize(8).fillColor(MUTE).text("데이터 범위: " + rg.from + " ~ " + rg.to + " KST · 봉 " + rg.n + "개 · 가격 " + fmt(rg.lo) + " ~ " + fmt(rg.hi), { width: w });
  doc.font("kr").fontSize(8).fillColor(MUTE).text("선: 파랑=가격 20봉평균 · 보라=60봉평균 · 주황=거래량 20봉평균 · 빨강점선=저항 · 초록점선=지지 · 노랑=다음 16시간 범위", { width: w });
  doc.moveDown(0.2);
  const legend = ["(1) 마지막 봉 윗꼬리", "(2) 그 봉 거래량 vs 20봉평균", "(3) 최근 6봉 크기", "(4) 다음 16시간 범위", "(5) 최근 고점 흐름", "(6) 최근 저점 흐름", "(7) 가까운 저항", "(8) 가까운 지지"];
  doc.fontSize(8.3).fillColor(INK);
  const colW = w / 4;
  for (let i = 0; i < legend.length; i += 4) {
    const yy = doc.y;
    for (let k = 0; k < 4 && legend[i + k]; k++) doc.text(legend[i + k], x + k * colW, yy, { width: colW - 4, lineBreak: false });
    doc.y = yy + 11;
  }
  doc.x = x;
}

/* ---- 인트로: 제목 + 단타 관점 ---- */
function pageIntro(doc, data) {
  doc.font("kr-bold").fontSize(16).fillColor(INK).text("타임프레임별 차트 분석 — 단타 참고");
  doc.font("kr").fontSize(9).fillColor(MUTE).text("5분~일봉 6개 차트를 각각 유형 A(클로드 의견)와 유형 B로 봅니다. 유형 B의 '검증된 신호'는 4시간봉 전용이고, 다른 봉은 객관적 구조 계산(예측 아님)입니다.", { width: cw(doc), lineGap: 1 });
  doc.moveDown(0.3);
  boxLines(doc, [
    { t: "클로드 단타 관점 (검증 안 된 의견)", bold: true, color: AMBER, size: 10 },
    { t: data.scalp || "(단타 관점이 아직 작성되지 않았습니다.)", size: 9 }
  ], { bg: AMBER_BG, border: "#fde68a" });
}

/* ---- 타임프레임 한 개 블록: 차트 + 유형 A + 유형 B ---- */
function tfBlock(doc, m, aRead, result) {
  ensureSpace(doc, 300);
  const x = ML(doc), w = cw(doc);
  doc.font("kr-bold").fontSize(12).fillColor(INK).text(m.label + "  (" + m.bar + ")", x, doc.y);
  doc.moveDown(0.15);
  const y = doc.y, h = 158;
  if (m.chart && m.chart.bars && m.chart.bars.length) drawChart(doc, { x, y, w, h }, m.chart);
  else doc.font("kr").fontSize(9).fillColor(MUTE).text("(차트 자료 없음)");
  doc.y = y + h + 5; doc.x = x;
  const rg = m.chart && m.chart.range;
  if (rg) doc.font("kr").fontSize(7.3).fillColor(MUTE).text("데이터 " + rg.from + " ~ " + rg.to + " · 봉 " + rg.n + " · 파랑=20평균 보라=60평균 주황=거래량평균 빨강점선=저항 초록점선=지지", { width: w });
  doc.moveDown(0.2);

  // 유형 A (클로드 의견)
  const a = aRead || {};
  doc.font("kr-bold").fontSize(9).fillColor(callColor(a.call)).text("유형 A · 클로드: " + (a.call || "-"), x, doc.y, { continued: true });
  doc.font("kr").fontSize(9).fillColor(INK).text("  " + (a.note || "(의견 없음)"), { width: w });
  doc.moveDown(0.1);

  // 유형 B (4시간봉만 검증, 나머지는 객관 구조)
  if (m.error) doc.font("kr").fontSize(9).fillColor(MUTE).text("유형 B · 자료 읽기 실패");
  else if (m.bar === "4H" && result) {
    const v = result.verdict;
    doc.font("kr-bold").fontSize(9).fillColor(ACCENT).text("유형 B · 검증 신호: " + v.signal, x, doc.y, { continued: true });
    doc.font("kr").fontSize(9).fillColor(INK).text("  신호값 " + (v.signal_value != null ? v.signal_value.toFixed(3) : "-") + " (롱 " + v.long_threshold + ") · 크기 " + v.size_state + " · 16시간 ±" + v.p80_move_pct.toFixed(2) + "% → 자세한 근거는 '유형 B 상세' 쪽", { width: w });
  } else {
    doc.font("kr-bold").fontSize(9).fillColor(ACCENT).text("유형 B 자리 · 객관 구조", x, doc.y, { continued: true });
    doc.font("kr").fontSize(9).fillColor(INK).text(" (검증된 방향 신호 아님): 추세 " + m.trend + " · 지지 " + (m.sup ? fmt(m.sup) : "-") + " / 저항 " + (m.res ? fmt(m.res) : "-") + " · 변동성 ±" + m.volPct.toFixed(2) + "% · 24봉 " + (m.chg >= 0 ? "+" : "") + m.chg.toFixed(1) + "%", { width: w });
  }
  doc.moveDown(0.1);
  const theory = m.bar === "4H"
    ? "추세(이동평균 배열) · 지지/저항 · 거래량 확증 · 변동성 · 윗꼬리×거래량 돌파(검증)"
    : "추세(이동평균 배열) · 지지/저항 · 거래량 확증 · 변동성 · 모멘텀";
  doc.font("kr").fontSize(7.8).fillColor(MUTE).text("쓰인 이론: " + theory + "  → 설명은 '분석 이론' 쪽", x, doc.y, { width: w });
  doc.moveDown(0.3);
  doc.save().strokeColor(LINE).lineWidth(0.5).moveTo(x, doc.y).lineTo(x + w, doc.y).stroke().restore();
  doc.moveDown(0.35);
}

/* ---- 유형 B: 4시간봉 검증 신호 상세 ---- */
function pageB(doc, data) {
  const r = data.result, v = r.verdict;
  callBanner(doc, "유형 B · 2020~2023 자료로 기준을 고정한 검증 신호", v.signal, "방향 " + v.direction);
  chartBlock(doc, data, 205);

  const calc = v.signal_value != null
    ? "신호값 " + v.signal_value.toFixed(3) + " = 윗꼬리 비율 × 거래량 배수. 롱 기준 " + v.long_threshold + " 이상이면 '롱', " + v.short_threshold + " 이하면 '숏(기록만)', 그 사이면 '없음'."
    : "이번 봉은 신호값을 계산할 수 없었습니다.";
  boxLines(doc, [{ t: "어떻게 이 신호가 나왔나", bold: true, color: ACCENT, size: 10 }, { t: calc, size: 9.5 }], { bg: ACC_BG, border: "#c7d2fe" });

  section(doc, "크기와 예상 범위");
  doc.font("kr").fontSize(9.5).fillColor(INK);
  doc.text("· 크기 상태: " + v.size_state + " (최근 6봉 평균 " + v.recent_size_pct.toFixed(2) + "%)");
  doc.text("· 다음 16시간: 보통 ±" + v.typical_move_pct.toFixed(2) + "%, 5번 중 4번 " + fmt(v.band_16h[0]) + " ~ " + fmt(v.band_16h[1]) + " (지금 종가 " + fmt(v.close) + ")");
  if (v.signal === "롱") {
    if (!v.is_9pm_bar) doc.fillColor(GRAY).text("· 밤 9시 마감 봉이 아니라 실전 대상이 아닙니다(기록만).");
    else if (v.minutes_since_close > 15) doc.fillColor(AMBER).text("· 마감 뒤 " + v.minutes_since_close.toFixed(0) + "분 지남 — 규칙상 15분 넘으면 건너뜀.");
    else doc.fillColor(GREEN).text("· 실전 대상. 청산 " + (v.exit_kst || "-") + " KST. 주문은 사람이 직접.");
    doc.fillColor(INK);
  }

  section(doc, "차트를 짚어가며 (번호별 근거)");
  doc.font("kr").fontSize(9).fillColor(INK);
  (r.why || []).forEach((t, i) => { doc.text("(" + (i + 1) + ") " + t, { width: cw(doc), lineGap: 0.5 }); doc.moveDown(0.05); });

  const f = r.forward_test;
  if (f) boxLines(doc, [{ t: "처음 보는 자료 성적 (2026-09-29 이후, 이 자료 범위)", bold: true, size: 9.5 },
  { t: "봉 " + f.bars + "개, 롱 신호 " + f.long_signals + "번" + (f.long_signals ? " · 평균 " + pct(f.long_mean_pct) + " (아무 때나 롱 " + pct(f.baseline_pct) + ", t " + (f.t == null ? "-" : f.t) + "). 표본이 작아 아직 판정하지 않습니다." : ""), size: 9 }], {});
}

/* ---- 개념 사전 ---- */
const GLOSSARY = [
  ["봉(캔들)", "4시간 동안의 시가·고가·저가·종가를 막대 하나로 나타낸 것. 굵은 몸통은 시가~종가, 가는 선(꼬리)은 그 시간의 최고·최저까지입니다."],
  ["윗꼬리 / 윗꼬리 비율", "봉 위로 삐친 선. 위로 올랐다가 되밀린 흔적입니다. '윗꼬리 비율'은 봉 전체 길이 중 윗꼬리가 차지하는 몫(0~1)으로, 클수록 위에서 눌린 것입니다."],
  ["거래량 / 20봉 평균 / 거래량 배수", "거래량은 그 봉 동안 사고판 양입니다. '20봉 평균'은 직전 20개 봉 거래량의 평균(차트 주황선). '거래량 배수'는 이번 봉 거래량 ÷ 그 평균으로, 1보다 크면 평소보다 활발한 것입니다."],
  ["신호값", "이 분석기의 핵심 숫자 = 윗꼬리 비율 × 거래량 배수. 위에서 눌렸는데(윗꼬리) 거래까지 터지면 값이 커집니다. 롱 기준 0.422 이상이면 '롱', 0.086 이하면 '숏(기록만)', 그 사이는 '없음'. 기준값은 2020~2023 자료로 정해 고정했습니다."],
  ["롱 / 숏", "롱은 오를 것에 베팅, 숏은 내릴 것에 베팅입니다. 이 분석기의 숏은 과거 두 기간 모두 손해라 실전은 안 하고 기록만 합니다."],
  ["이동평균선 (20·60·120봉)", "최근 N개 봉 종가의 평균을 이은 선으로 추세의 큰 방향을 봅니다. 20<60<120이면 역배열(내림세 정렬), 20>60>120이면 정배열(오름세 정렬)입니다."],
  ["지지 / 저항", "지지는 아래에서 가격을 받쳐온 가격대, 저항은 위에서 눌러온 가격대입니다. 뚫리면 그 방향으로 더 가기 쉽습니다. (과거 검증에서 방향 적중력이 확인되지 않아 참고용입니다.)"],
  ["크기 상태 (조용·보통·거침)", "최근 6봉(24시간)의 봉 크기 평균으로 장이 얼마나 출렁이는지 구분합니다. 1.39% 미만=조용, 1.39~2.14%=보통, 2.14% 이상=거침. 범위 예측에 씁니다."],
  ["다음 16시간 흔한 범위(띠)", "크기 상태를 바탕으로 앞으로 16시간 가격이 머물 법한 범위입니다. 진한 띠=보통 움직임(±중앙값), 옅은 띠=5번 중 4번이 든 범위(±p80). 방향이 아니라 '폭'의 예측입니다."],
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
  ["다중 타임프레임 분석", "같은 종목을 여러 시간대(5분~일봉)로 겹쳐 봅니다. 큰 시간대가 큰 흐름, 작은 시간대가 진입 타이밍을 주고, 상위와 하위가 같은 방향이면 신뢰가 올라갑니다. 한계: 시간대마다 신호가 엇갈리면 오히려 판단이 어려워집니다(지금이 그런 상태)."],
  ["모멘텀 (변화율)", "최근 일정 기간(예: 24봉) 가격이 몇 % 움직였는지 봅니다. 움직이던 방향으로 좀 더 가려는 관성을 읽습니다. 한계: 급변 뒤 되돌림 구간에선 약합니다."],
  ["윗꼬리 × 거래량 돌파 신호 (유형 B · 유일하게 검증됨)", "윗꼬리 비율 × 거래량 배수로 '위에서 눌렸는데 거래가 터진' 봉을 잡아냅니다. 2020~2023 4시간봉에서 이 값이 큰 뒤 평균적으로 올랐기에(과거 검증) 기준 0.422를 넘으면 '롱'으로 봅니다. 한계: 4시간봉 전용, 초과 수익이 작고, 다른 타임프레임엔 적용할 수 없습니다."]
];
function pageTheory(doc) {
  doc.font("kr-bold").fontSize(15).fillColor(INK).text("분석 이론 — 이 보고서가 쓰는 방법과 근거");
  doc.font("kr").fontSize(9).fillColor(MUTE).text("각 차트의 판단이 '어떤 기술·이론'에서 나왔는지입니다. 왼쪽 그림은 개념 예시(실제 자료 아님). 기술적 분석은 대부분 경험칙(보장 아님)이며, 과거 자료로 검증된 것은 맨 아래 유형 B 하나뿐입니다.", { width: cw(doc), lineGap: 1 });
  doc.moveDown(0.4);
  const x = ML(doc), w = cw(doc), dw = 120, dh = 66, gap = 12, tx = x + dw + gap, tw = w - dw - gap;
  THEORIES.forEach(([t, d], i) => {
    const top = doc.y;
    if (DIAGRAMS[i]) DIAGRAMS[i](doc, x, top, dw, dh);
    doc.font("kr-bold").fontSize(9.8).fillColor(ACCENT).text(t, tx, top, { width: tw });
    doc.font("kr").fontSize(8.5).fillColor(INK).text(d, tx, doc.y + 1, { width: tw, lineGap: 0.5 });
    doc.y = Math.max(doc.y, top + dh) + 8; doc.x = x;
  });
}

function pageGlossary(doc) {
  doc.font("kr-bold").fontSize(15).fillColor(INK).text("개념 사전 — 이 보고서의 용어 풀이");
  doc.font("kr").fontSize(9).fillColor(MUTE).text("보고서에 나온 말을 쉽게 풀었습니다. 한 번 익혀 두면 다음부터 훨씬 잘 읽힙니다.");
  doc.moveDown(0.4);
  const x = ML(doc), w = cw(doc);
  for (const [t, d] of GLOSSARY) {
    const y = doc.y;
    doc.save().circle(x + 2.5, y + 5.5, 2.5).fill(ACCENT).restore();
    doc.font("kr-bold").fontSize(9.8).fillColor(ACCENT).text(t, x + 10, y, { width: w - 10 });
    doc.font("kr").fontSize(9).fillColor(INK).text(d, x + 10, doc.y, { width: w - 10, lineGap: 0.5 });
    doc.moveDown(0.3);
  }
}

function buildPdf(outPath, data) {
  if (!REG) throw new Error("한글 폰트를 찾지 못했습니다. report/fonts/ 에 NotoSansKR-Regular.ttf 를 두거나 윈도우 맑은 고딕이 필요합니다.");
  const doc = new PDFDocument({ size: "A4", margins: { top: 48, bottom: 44, left: 48, right: 48 }, info: { Title: "BTC 분석 보고서" } });
  const stream = fs.createWriteStream(outPath);
  doc.pipe(stream);
  doc.registerFont("kr", REG);
  doc.registerFont("kr-bold", BOLD);
  doc.on("pageAdded", () => frame(doc));

  startPage(doc, "단타 · 타임프레임별 차트", "단타 참고 · 검증된 신호는 4시간봉뿐 · 매매·투자 조언 아님", true);
  pageIntro(doc, data);
  const tf = (data.pageA && data.pageA.tf) || {};
  for (const m of (data.mtf || [])) tfBlock(doc, m, tf[m.bar], data.result);
  startPage(doc, "유형 B · 4시간봉 검증 상세", "유형 B · OKX 실시간 미리보기(바이낸스 선물과 약 90% 일치) · 확정은 하루 1회 바이낸스 보관소");
  pageB(doc, data);
  startPage(doc, "분석 이론", "분석 이론 · 학습용 · 대부분 경험칙(보장 아님)");
  pageTheory(doc);
  startPage(doc, "개념 사전", "개념 사전 · 학습용");
  pageGlossary(doc);

  doc.end();
  return new Promise((res, rej) => { stream.on("finish", () => res(outPath)); stream.on("error", rej); });
}

module.exports = { buildPdf };
