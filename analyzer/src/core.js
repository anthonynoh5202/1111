/* BTC/USDT 차트분석기 계산 모듈.
   화면(index.html)과 자동 분석 플랫폼·보고서(src/judge.cjs)가 같은 식을 쓴다.
   식과 기준값은 research/pilot5/pilot.py, size_states.py와 같다. 기준값은 2020~2023 자료로 정해 고정한 값이다. */
var BTCAN = (function () {
  "use strict";
  const Q80 = 0.4217300308371426, Q20 = 0.08566545851163947, AVG = 20, HOLD = 4, MS4 = 4 * 3600 * 1000;
  const FWD = Date.UTC(2026, 8, 29), COST = 0.073, MIN_BARS = 130;
  const SIZE_Q = [1.39, 2.14];
  const STATES = [
    { name: "조용", rule: "1.39% 미만", med: 0.79, p80: 1.88, dip3: 7.7, up: 51.2 },
    { name: "보통", rule: "1.39~2.14%", med: 1.07, p80: 2.42, dip3: 15.0, up: 51.5 },
    { name: "거침", rule: "2.14% 이상", med: 1.58, p80: 3.36, dip3: 29.8, up: 53.4 }];

  const fmt = (x, d = 1) => x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (x, d = 2) => (x >= 0 ? "+" : "") + x.toFixed(d) + "%";
  const p2 = n => String(n).padStart(2, "0");
  function kst(ms, withDate = true) {
    const d = new Date(ms + 9 * 3600 * 1000), t = p2(d.getUTCHours()) + ":" + p2(d.getUTCMinutes());
    return withDate ? (d.getUTCMonth() + 1) + "/" + d.getUTCDate() + " " + t : t;
  }
  function kstFull(ms) {
    const d = new Date(ms + 9 * 3600 * 1000);
    return d.getUTCFullYear() + "-" + p2(d.getUTCMonth() + 1) + "-" + p2(d.getUTCDate()) + " " + p2(d.getUTCHours()) + ":" + p2(d.getUTCMinutes());
  }

  /* i번째 봉의 윗꼬리 비율, 거래량 배수, 둘의 곱. 계산할 수 없으면 null */
  function upperVol(b, i) {
    if (i < AVG) return null;
    const [, o, h, l, c, v] = b[i]; let s = 0; for (let k = i - AVG; k < i; k++) s += b[k][5];
    const avg = s / AVG; if (h <= l || avg <= 0) return null;
    const up = (h - Math.max(o, c)) / (h - l), mult = v / avg; return { up, mult, x: up * mult };
  }
  const sigOf = x => x == null ? 0 : (x >= Q80 ? 1 : (x <= Q20 ? -1 : 0));
  const mean = a => a.reduce((s, x) => s + x, 0) / a.length;
  /* 평균이 0인지에 대한 t값. 보유 기간이 겹치는 것을 고려한다(Newey–West) */
  function hacT(z, lags) {
    const n = z.length; if (n < 30) return NaN; const m = mean(z), zc = z.map(x => x - m);
    let v = zc.reduce((s, x) => s + x * x, 0) / n;
    for (let k = 1; k <= lags; k++) { let s = 0; for (let i = k; i < n; i++) s += zc[i] * zc[i - k]; v += 2 * (1 - k / (lags + 1)) * s / n; }
    return v > 0 ? m / Math.sqrt(v / n) : NaN;
  }
  function sma(c, n) {
    const out = new Array(c.length).fill(null); let s = 0;
    for (let i = 0; i < c.length; i++) { s += c[i]; if (i >= n) s -= c[i - n]; if (i >= n - 1) out[i] = s / n; } return out;
  }

  /* all: [시작 시각 ms, 시가, 고가, 저가, 종가, 거래량]의 배열. now: 지금 시각 ms(마감 안 된 봉을 가르는 기준) */
  function analyze(all, now, live) {
    const seen = new Set(); let bars = [], forming = null;
    all.slice().sort((a, b) => a[0] - b[0]).forEach(b => {
      if (seen.has(b[0])) return; seen.add(b[0]);
      if (b[0] + MS4 > now) forming = b; else bars.push(b);
    });
    // 빠진 봉이 있으면 그 뒤의 이어진 구간만 쓴다
    let gapAt = null;
    for (let k = bars.length - 1; k > 0; k--) if (bars[k][0] - bars[k - 1][0] !== MS4) { gapAt = bars[k][0]; bars = bars.slice(k); break; }
    if (forming && bars.length && forming[0] - bars[bars.length - 1][0] !== MS4) forming = null;
    const n = bars.length, i = n - 1;
    if (n < MIN_BARS) throw new Error("이어진 4시간봉이 " + n + "개뿐입니다. " + MIN_BARS + "개 이상 필요합니다.");
    const C = bars.map(b => b[4]);
    const uv = bars.map((_, k) => upperVol(bars, k)), sig = uv.map(u => sigOf(u ? u.x : null));
    let rs = 0; for (let k = i - 5; k <= i; k++) rs += (bars[k][2] - bars[k][3]) / bars[k][4] * 100; rs /= 6;
    const state = rs < SIZE_Q[0] ? 0 : (rs < SIZE_Q[1] ? 1 : 2);
    let lo20 = Infinity, hi20 = -Infinity; for (let k = i - 19; k <= i; k++) { lo20 = Math.min(lo20, bars[k][3]); hi20 = Math.max(hi20, bars[k][2]); }
    const ma20 = sma(C, 20), ma60 = sma(C, 60), ma120 = sma(C, 120);
    // 일봉(09:00 KST 시작)으로 묶기
    const dmap = new Map(); bars.forEach(b => {
      const d = Math.floor(b[0] / 86400000), e = dmap.get(d);
      if (!e) dmap.set(d, { c: b[4], n: 1 }); else { e.c = b[4]; e.n++; }
    });
    const dC = [...dmap.values()].filter(e => e.n === 6).map(e => e.c);
    const lastOf = a => a.length ? a[a.length - 1] : null;
    const d20 = lastOf(sma(dC, 20)), d60 = lastOf(sma(dC, 60)), d120 = lastOf(sma(dC, 120));
    // 고점·저점(앞뒤 5봉보다 높거나 낮은 봉)
    const K = 5, ph = [], pl = [];
    for (let k = Math.max(K, n - 240); k < n - K; k++) {
      let isH = true, isL = true;
      for (let j = k - K; j <= k + K; j++) { if (bars[j][2] > bars[k][2]) isH = false; if (bars[j][3] < bars[k][3]) isL = false; }
      if (isH) ph.push({ i: k, p: bars[k][2] }); if (isL) pl.push({ i: k, p: bars[k][3] });
    }
    const px = C[i];
    const res = ph.filter(p => p.p > px).sort((a, b) => a.p - b.p)[0] || null;
    const sup = pl.filter(p => p.p < px).sort((a, b) => b.p - a.p)[0] || null;
    // 처음 보는 자료(2026-09-29 이후) 성적
    const rows = []; for (let k = AVG; k < n - HOLD; k++) { if (bars[k][0] < FWD) continue; rows.push({ s: sig[k], r: bars[k + HOLD][4] / bars[k][4] - 1 }); }
    let fwd = null;
    if (rows.length) {
      const base = mean(rows.map(r => r.r)), lg = rows.filter(r => r.s === 1).map(r => r.r), sh = rows.filter(r => r.s === -1).map(r => -r.r);
      const dm = lg.length / rows.length;
      const t = hacT(rows.map(r => ((r.s === 1 ? 1 : 0) - dm) * (r.r - base)), HOLD - 1);
      fwd = { n: rows.length, base, nl: lg.length, lmean: lg.length ? mean(lg) : NaN, t, ns: sh.length, smean: sh.length ? mean(sh) : NaN };
    }
    return {
      bars, forming, n, i, C, uv, sig, rs, state, lo20, hi20, ma20, ma60, ma120, d20, d60, d120, dN: dC.length, ph, pl, res, sup, fwd, live, now, gapAt,
      px: forming ? forming[4] : px, pxTime: forming ? now : bars[i][0] + MS4
    };
  }

  /* 분석 결과를 사람이 읽는 글로 바꾼다. facts: [이름, 값] 목록, why: 판단 근거 1~8번 */
  function describe(s) {
    const b = s.bars, i = s.i, last = b[i], c = last[4], u = s.uv[i], sg = s.sig[i], st = STATES[s.state];
    const close = last[0] + MS4, slot = new Date(last[0]).getUTCHours() === 8;
    const F = [];
    const m20 = s.ma20[i], m60 = s.ma60[i], m120 = s.ma120[i];
    const order = (a, b2, c2) => a > b2 && b2 > c2 ? "정배열(20 > 60 > 120)" : (a < b2 && b2 < c2 ? "역배열(20 < 60 < 120)" : "섞여 있음");
    F.push(["4시간봉 평균선", order(m20, m60, m120)]);
    F.push(["종가와 4시간 20·60·120봉 평균", [m20, m60, m120].map(m => pct((c / m - 1) * 100, 1)).join(" / ")]);
    if (s.d120 != null) F.push(["일봉 평균선", order(s.d20, s.d60, s.d120) + " · 종가는 20일선 " + (c >= s.d20 ? "위" : "아래")]);
    const lastH = s.ph.slice(-3).map(p => p.p), lastL = s.pl.slice(-3).map(p => p.p);
    const trend = a => a.length < 3 ? "자료 부족" : (a[0] < a[1] && a[1] < a[2] ? "높아지는 중" : (a[0] > a[1] && a[1] > a[2] ? "낮아지는 중" : "엇갈림"));
    F.push(["최근 고점 3개", lastH.map(x => fmt(x / 1000, 1) + "k").join(" → ") + " · " + trend(lastH)]);
    F.push(["최근 저점 3개", lastL.map(x => fmt(x / 1000, 1) + "k").join(" → ") + " · " + trend(lastL)]);
    F.push(["가까운 저항(위 고점)", s.res ? fmt(s.res.p, 0) + " (" + pct((s.res.p / c - 1) * 100, 1) + ")" : "최근 40일 고점 위에 있음"]);
    F.push(["가까운 지지(아래 저점)", s.sup ? fmt(s.sup.p, 0) + " (" + pct((s.sup.p / c - 1) * 100, 1) + ")" : "최근 40일 저점 아래에 있음"]);
    F.push(["마지막 봉 거래량", u ? "직전 20봉 평균의 " + u.mult.toFixed(2) + "배" : "–"]);

    const W = [];
    if (u) {
      W.push("마지막으로 마감된 봉입니다. 굵은 세로줄이 윗꼬리이고, 봉 전체 길이의 " + Math.round(u.up * 100) + "%입니다(윗꼬리 비율 " + u.up.toFixed(3) + ").");
      W.push("이 봉의 거래량은 직전 20봉 평균(아래 가로선)의 " + u.mult.toFixed(2) + "배입니다. 둘을 곱한 값이 " + u.x.toFixed(3) + "이고, " +
        (sg === 1 ? "롱 기준 0.422를 넘어서 신호가 '롱'입니다." : (sg === -1 ? "숏 기준 0.086 아래라 '숏(기록만)'입니다. 숏은 과거 두 기간 모두 손해라 실전에서 하지 않습니다." : "롱 기준 0.422에 못 미치고 숏 기준 0.086보다는 커서 신호가 '없음'입니다.")));
    }
    W.push("음영으로 칠한 최근 6봉(24시간)의 봉 크기 평균이 " + s.rs.toFixed(2) + "%입니다. " + (s.state === 0 ? "1.39%보다 작아서" : (s.state === 1 ? "1.39%와 2.14% 사이라서" : "2.14%를 넘어서")) + " 크기 상태가 '" + st.name + "'입니다.");
    W.push("오른쪽 띠가 다음 16시간의 흔한 범위입니다. 진한 띠는 보통 움직임(±" + st.med.toFixed(2) + "%), 옅은 띠는 5번 중 4번이 들어간 범위(±" + st.p80.toFixed(2) + "%)입니다. " +
      (sg === 1 ? "롱 신호가 있어도 과거 초과 수익(+0.15~0.18%p)이 띠 폭보다 훨씬 작아서 띠는 위아래가 같습니다. 그래서 방향은 '약한 롱 쪽'까지만 말합니다." : "띠가 위아래로 똑같은 것은 어느 쪽으로 갈지 가를 근거가 없기 때문입니다. 이 상태에서 과거에 오른 비율은 " + st.up + "%였습니다. 그래서 방향은 '모름'입니다."));
    W.push("최근 고점 3개는 " + lastH.map(x => fmt(x / 1000, 1) + "k").join(" → ") + "로 " + trend(lastH) + "입니다.");
    W.push("최근 저점 3개는 " + lastL.map(x => fmt(x / 1000, 1) + "k").join(" → ") + "로 " + trend(lastL) + "입니다." +
      (trend(lastH) === "낮아지는 중" && trend(lastL) === "높아지는 중" ? " 고점은 내려오고 저점은 올라와 폭이 좁아지는 중이라, 구조로도 방향이 갈립니다." : ""));
    W.push(s.res ? "가까운 저항은 " + fmt(s.res.p, 0) + "(" + pct((s.res.p / c - 1) * 100, 1) + ")입니다. 종가 위에 있는 고점 중 가장 가까운 것입니다." : "종가가 최근 40일의 고점들 위에 있어 가까운 저항이 없습니다.");
    W.push((s.sup ? "가까운 지지는 " + fmt(s.sup.p, 0) + "(" + pct((s.sup.p / c - 1) * 100, 1) + ")입니다. " : "종가가 최근 40일의 저점들 아래에 있어 가까운 지지가 없습니다. ") + "5~8번은 과거 검증에서 방향을 맞히는 힘이 확인되지 않아 판정에는 쓰지 않았습니다.");

    return {
      facts: F, why: W, close, slot, signal: sg, signalName: sg === 1 ? "롱" : (sg === -1 ? "숏(기록만)" : "없음"),
      direction: sg === 1 ? "약한 롱 쪽" : "모름", state: st, upperVol: u,
      band: [c * (1 - st.p80 / 100), c * (1 + st.p80 / 100)], exit: sg === 1 ? close + HOLD * MS4 : null
    };
  }

  return { Q80, Q20, AVG, HOLD, MS4, FWD, COST, SIZE_Q, STATES, MIN_BARS, fmt, pct, kst, kstFull, upperVol, sigOf, hacT, sma, analyze, describe };
})();
if (typeof module !== "undefined" && module.exports) module.exports = BTCAN;
