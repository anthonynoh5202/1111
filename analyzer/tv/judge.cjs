/* 봉 자료를 받아 차트분석기 기준으로 판정한 결과를 만든다.
   명령줄 도구(tv/analyze.cjs)와 자동 분석 플랫폼(platform/)이 함께 쓴다. */
const A = require("../src/core.js");

class Stop extends Error { }   // 사용자가 고칠 수 있는 이유로 멈출 때

/* 트레이딩뷰·바이낸스에서 읽은 봉을 [시작 시각 ms, 시가, 고가, 저가, 종가, 거래량]으로 바꾸고 확인한다 */
function toBars(rows) {
  if (!Array.isArray(rows) || !rows.length) throw new Stop("봉 자료가 없습니다.");
  const num = x => { const v = Number(x); if (!Number.isFinite(v)) throw new Stop("숫자가 아닌 값이 들어 있습니다."); return v; };
  const bars = rows.map(b => {
    const r = Array.isArray(b) ? b : [b.time, b.open, b.high, b.low, b.close, b.volume];
    const t = num(r[0]);
    return [t < 1e11 ? t * 1000 : t, num(r[1]), num(r[2]), num(r[3]), num(r[4]), num(r[5])];
  });
  if (bars.some(b => b[2] < b[3] || b[1] <= 0)) throw new Stop("고가가 저가보다 낮은 봉이 있습니다. 자료가 잘못됐습니다.");
  const steps = bars.slice(1).map((b, k) => b[0] - bars[k][0]);
  if (steps.filter(d => d === A.MS4).length < steps.length * 0.9) throw new Stop("봉 간격이 4시간이 아닙니다. 차트 주기를 확인하세요.");
  return bars;
}

/* 종목과 주기가 BTCUSDT 무기한 선물 4시간봉인지 확인한다 */
function checkChart(symbol, tf) {
  // 이름 전체가 정확히 맞아야 한다. 이 글자는 화면·기록·Claude 해설 입력에 들어가므로 다른 글자가 섞인 이름은 받지 않는다.
  const shown = v => String(v == null ? "없음" : v).replace(/[^A-Za-z0-9:._-]/g, "?").slice(0, 40);
  if (!/^(BINANCE:)?BTCUSDT(\.P|PERP)$/.test(String(symbol || "").toUpperCase())) throw new Stop("차트가 바이낸스 BTCUSDT 무기한 선물이 아닙니다(받은 값: " + shown(symbol) + "). BINANCE:BTCUSDT.P 로 바꾼 뒤 다시 실행하세요.");
  if (String(tf) !== "240") throw new Stop("차트가 4시간봉이 아닙니다(받은 값: " + shown(tf) + "). 240으로 바꾼 뒤 다시 실행하세요.");
}

function judge(bars, now, symbol) {
  let s, d;
  try { s = A.analyze(bars, now, false); d = A.describe(s); } catch (e) { throw new Stop(e.message); }
  const last = s.bars[s.i], c = last[4];
  const ageH = (now - (last[0] + A.MS4)) / 3600000;
  const warnings = [];
  if (ageH > 4.1) warnings.push("마지막으로 마감된 봉이 " + ageH.toFixed(1) + "시간 전입니다. 리플레이 중이거나 자료가 늦은 것일 수 있습니다.");
  if (s.gapAt) warnings.push(A.kstFull(s.gapAt) + " 앞에 빠진 봉이 있어 그 뒤의 " + s.n + "개 봉만 썼습니다.");
  if (s.d120 == null) warnings.push("봉이 " + s.n + "개라 일봉 평균선은 계산하지 않았습니다.");
  const lateMin = (now - d.close) / 60000;

  // 트레이딩뷰 차트에 그릴 표시(draw_shape 인자 그대로)
  const sec = ms => Math.round(ms / 1000);
  const marks = [];
  if (s.res) marks.push({ shape: "horizontal_line", point: { time: sec(s.bars[s.res.i][0]), price: s.res.p }, text: "분석기 7 저항" });
  if (s.sup) marks.push({ shape: "horizontal_line", point: { time: sec(s.bars[s.sup.i][0]), price: s.sup.p }, text: "분석기 8 지지" });
  marks.push({ shape: "rectangle", point: { time: sec(d.close), price: d.band[1] }, point2: { time: sec(d.close + A.HOLD * A.MS4), price: d.band[0] }, text: "분석기 4 다음 16시간 흔한 범위" });
  marks.push({ shape: "text", point: { time: sec(last[0]), price: last[2] }, text: "분석기: 신호 " + d.signalName + " · 크기 " + d.state.name + " · 방향 " + d.direction });

  const result = {
    source: { symbol: String(symbol), timeframe: "240", bars_used: s.n, read_at_kst: A.kstFull(now), last_closed_bar_kst: A.kstFull(d.close) },
    bar_close_ms: d.close,
    verdict: {
      direction: d.direction, signal: d.signalName,
      signal_value: d.upperVol ? +d.upperVol.x.toFixed(4) : null, long_threshold: 0.422, short_threshold: 0.086,
      is_9pm_bar: d.slot, minutes_since_close: +lateMin.toFixed(1), exit_kst: d.exit ? A.kstFull(d.exit) : null,
      size_state: d.state.name, recent_size_pct: +s.rs.toFixed(2), typical_move_pct: d.state.med, p80_move_pct: d.state.p80,
      band_16h: d.band.map(x => Math.round(x)), close: c
    },
    why: d.why, facts: d.facts.map(([k, v]) => ({ name: k, value: v })),
    forward_test: s.fwd ? { bars: s.fwd.n, long_signals: s.fwd.nl, long_mean_pct: s.fwd.nl ? +(s.fwd.lmean * 100).toFixed(3) : null, baseline_pct: +(s.fwd.base * 100).toFixed(3), t: Number.isNaN(s.fwd.t) ? null : +s.fwd.t.toFixed(2) } : null,
    warnings, marks
  };
  return { result, s, d };
}

/* 사람이 읽는 글 */
function toText(result, d) {
  const v = result.verdict, L = [];
  L.push("[BTC/USDT 차트분석기 · " + result.source.symbol + " 4시간봉]");
  L.push("기준: " + result.source.last_closed_bar_kst + " KST 마감 봉 (읽은 시각 " + result.source.read_at_kst + ", 봉 " + result.source.bars_used + "개)");
  L.push("");
  L.push("방향: " + v.direction);
  L.push("크기: " + v.size_state + " · 다음 16시간 보통 ±" + v.typical_move_pct.toFixed(2) + "%, 5번 중 4번은 " + A.fmt(v.band_16h[0], 0) + " ~ " + A.fmt(v.band_16h[1], 0));
  L.push("신호: " + v.signal + (v.signal_value != null ? " (값 " + v.signal_value.toFixed(3) + ", 롱 기준 0.422 이상)" : ""));
  if (d.signal === 1) {
    if (!v.is_9pm_bar) L.push("  이 봉은 밤 9시 마감 봉이 아니라 실전 대상이 아닙니다. 기록만 합니다.");
    else if (v.minutes_since_close > 15) L.push("  마감 뒤 " + v.minutes_since_close.toFixed(0) + "분이 지났습니다. 규칙상 15분이 넘으면 건너뜁니다.");
    else L.push("  실전 대상입니다. 청산 시각 " + v.exit_kst + " KST. 주문은 PROTOCOL.md의 주문표대로 사람이 직접 합니다.");
  }
  L.push("", "판단 근거");
  result.why.forEach((t, k) => L.push("  " + (k + 1) + ". " + t));
  L.push("", "차트 구조");
  result.facts.forEach(f => L.push("  - " + f.name + ": " + f.value));
  const f = result.forward_test;
  if (f) L.push("", "2026-09-29 이후 성적(이 자료 범위): 봉 " + f.bars + "개, 롱 신호 " + f.long_signals + "번" + (f.long_signals ? ", 평균 " + A.pct(f.long_mean_pct, 3) + " (아무 때나 롱 " + A.pct(f.baseline_pct, 3) + ")" : ""));
  if (result.warnings.length) { L.push("", "주의"); result.warnings.forEach(w => L.push("  ! " + w)); }
  return L.join("\n");
}

module.exports = { Stop, toBars, checkChart, judge, toText };
