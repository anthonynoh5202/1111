/* 타임프레임별로 '지금 상태'를 객관적으로 계산한다(단타 요약표용). 예측이 아니라 묘사.
   - 추세: 20·50 이동평균 정렬 + 종가 위치
   - 변동성: 최근 14봉 (고-저)/종가 평균
   - 가까운 지지/저항: 최근 피벗 저점/고점 중 현재가에 가장 가까운 것
   - 24봉 변화율, 데이터 기간(봉 수·분) */
const A = require("../src/core.js");

const INTERVAL_MIN = { "5m": 5, "15m": 15, "30m": 30, "1H": 60, "4H": 240, "1D": 1440 };

function computeTf(bars, bar) {
  const n = bars.length, C = bars.map(b => b[4]);
  const ma20 = A.sma(C, 20), ma50 = A.sma(C, 50);
  const c = C[n - 1], m20 = ma20[n - 1], m50 = ma50[n - 1];
  let trend = "횡보";
  if (m20 != null && m50 != null) {
    if (m20 > m50 && c >= m20) trend = "상승";
    else if (m20 < m50 && c <= m20) trend = "하락";
  }
  const k = Math.min(14, n); let vs = 0; for (let i = n - k; i < n; i++) vs += (bars[i][2] - bars[i][3]) / bars[i][4] * 100;
  const volPct = vs / k;
  const w = Math.min(40, n); let lo = Infinity, hi = -Infinity; for (let i = n - w; i < n; i++) { lo = Math.min(lo, bars[i][3]); hi = Math.max(hi, bars[i][2]); }
  const K = 3, ph = [], pl = [], s = Math.max(K, n - 80);
  for (let i = s; i < n - K; i++) {
    let isH = true, isL = true;
    for (let j = i - K; j <= i + K; j++) { if (bars[j][2] > bars[i][2]) isH = false; if (bars[j][3] < bars[i][3]) isL = false; }
    if (isH) ph.push(bars[i][2]); if (isL) pl.push(bars[i][3]);
  }
  const res = ph.filter(p => p > c).sort((a, b) => a - b)[0] || null;
  const sup = pl.filter(p => p < c).sort((a, b) => b - a)[0] || null;
  const j = Math.max(0, n - 1 - 24), chg = (c / C[j] - 1) * 100;
  const spanMin = (INTERVAL_MIN[bar] || 0) * (n - 1);
  return { n, from: bars[0][0], to: bars[n - 1][0], spanMin, trend, volPct, lo, hi, sup, res, chg, close: c };
}

/* 타임프레임 차트용 자료(최근 80봉 + 이동평균·거래량평균). 4시간봉 전용 표시(신호·띠·번호)는 없다. */
function tfChart(bars, sup, res, formingLast) {
  const N = 80, n = bars.length, start = Math.max(0, n - N);
  const C = bars.map(b => b[4]);
  const ma20 = A.sma(C, 20), ma60 = A.sma(C, 60), volAvg = A.sma(bars.map(b => b[5]), 20);
  const win = [];
  for (let gi = start; gi < n; gi++) win.push({ t: bars[gi][0], o: bars[gi][1], h: bars[gi][2], l: bars[gi][3], c: bars[gi][4], v: bars[gi][5], ma20: ma20[gi], ma60: ma60[gi], volAvg: volAvg[gi], forming: !!formingLast && gi === n - 1 });
  let lo = Infinity, hi = -Infinity; for (const b of win) { lo = Math.min(lo, b.l); hi = Math.max(hi, b.h); }
  return {
    bars: win, res: res || null, sup: sup || null, band: null, simple: true,
    sigIdx: null, last6Idx: null, peakIdx: null, troughIdx: null,
    range: { from: A.kstFull(win[0].t), to: A.kstFull(win[win.length - 1].t), lo: Math.round(lo), hi: Math.round(hi), n: win.length }
  };
}

module.exports = { computeTf, tfChart, INTERVAL_MIN };
