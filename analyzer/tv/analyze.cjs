#!/usr/bin/env node
/* 트레이딩뷰에서 읽은 4시간봉을 우리 분석기 기준으로 판정한다.
   입력은 tradingview-mcp의 `tv ohlcv` 출력(JSON)이다. 이 도구는 읽고 계산만 한다. 주문 기능이 없다.

   쓰는 법(저장소 폴더에서):
     node vendor/tradingview-mcp/src/cli/index.js ohlcv --count 500 \
       | node analyzer/tv/analyze.cjs --symbol BINANCE:BTCUSDT.P --tf 240 --page analyzer/tv/out/chart.html

   옵션
     --symbol, --tf   차트 상태(chart_get_state)에서 읽은 값. BTCUSDT 무기한 선물 4시간봉이 아니면 멈춘다.
     --page <파일>    같은 자료를 넣은 분석기 화면(HTML)을 만든다.
     --json           사람이 읽는 글 대신 JSON으로 낸다(차트에 그릴 표시 목록 포함).
     --file <파일>    표준 입력 대신 파일에서 읽는다.  --now-ms <숫자>  시험용. */
const fs = require("fs"), path = require("path");
const A = require("../src/core.js");
const { buildPage } = require("../build.cjs");

function fail(msg) { console.error("멈춤: " + msg); process.exit(1); }
function args(argv) {
  const o = {}; for (let k = 0; k < argv.length; k++) {
    const a = argv[k]; if (!a.startsWith("--")) fail("알 수 없는 인자: " + a);
    const key = a.slice(2); if (key === "json") o.json = true; else o[key] = argv[++k];
  } return o;
}
const opt = args(process.argv.slice(2));

// 1) 무엇을 읽었는지 확인한다
const sym = String(opt.symbol || "").toUpperCase();
if (!/BTCUSDT(\.P|PERP)$/.test(sym)) fail("차트가 BTCUSDT 무기한 선물이 아닙니다(받은 값: " + (opt.symbol || "없음") + "). BINANCE:BTCUSDT.P 로 바꾼 뒤 다시 실행하세요.");
if (String(opt.tf) !== "240") fail("차트가 4시간봉이 아닙니다(받은 값: " + (opt.tf || "없음") + "). 240으로 바꾼 뒤 다시 실행하세요.");

let raw;
try { raw = JSON.parse(fs.readFileSync(opt.file || 0, "utf8")); } catch (e) { fail("입력을 JSON으로 읽지 못했습니다. `tv ohlcv` 출력이 맞는지 확인하세요."); }
if (!raw || raw.success === false || !Array.isArray(raw.bars)) fail("봉 자료가 없습니다" + (raw && raw.error ? ": " + raw.error : "."));
const num = x => { const v = Number(x); if (!Number.isFinite(v)) fail("숫자가 아닌 값이 들어 있습니다."); return v; };
const bars = raw.bars.map(b => {
  const t = num(b.time);
  return [t < 1e11 ? t * 1000 : t, num(b.open), num(b.high), num(b.low), num(b.close), num(b.volume)];
});
if (bars.some(b => b[2] < b[3] || b[1] <= 0)) fail("고가가 저가보다 낮은 봉이 있습니다. 자료가 잘못됐습니다.");
const steps = bars.slice(1).map((b, k) => b[0] - bars[k][0]);
if (steps.filter(d => d === A.MS4).length < steps.length * 0.9) fail("봉 간격이 4시간이 아닙니다. 차트 주기를 확인하세요.");

// 2) 계산
const now = opt["now-ms"] ? Number(opt["now-ms"]) : Date.now();
let s, d;
try { s = A.analyze(bars, now, false); d = A.describe(s); } catch (e) { fail(e.message); }
const last = s.bars[s.i], c = last[4];
const ageH = (now - (last[0] + A.MS4)) / 3600000;
const warnings = [];
if (ageH > 4.1) warnings.push("마지막으로 마감된 봉이 " + ageH.toFixed(1) + "시간 전입니다. 리플레이 중이거나 자료가 늦은 것일 수 있습니다.");
if (s.gapAt) warnings.push(A.kstFull(s.gapAt) + " 앞에 빠진 봉이 있어 그 뒤의 " + s.n + "개 봉만 썼습니다.");
if (s.d120 == null) warnings.push("봉이 " + s.n + "개라 일봉 평균선은 계산하지 않았습니다.");
const lateMin = (now - d.close) / 60000;

// 3) 트레이딩뷰 차트에 그릴 표시(draw_shape 인자 그대로)
const sec = ms => Math.round(ms / 1000);
const marks = [];
if (s.res) marks.push({ shape: "horizontal_line", point: { time: sec(s.bars[s.res.i][0]), price: s.res.p }, text: "분석기 7 저항" });
if (s.sup) marks.push({ shape: "horizontal_line", point: { time: sec(s.bars[s.sup.i][0]), price: s.sup.p }, text: "분석기 8 지지" });
marks.push({ shape: "rectangle", point: { time: sec(d.close), price: d.band[1] }, point2: { time: sec(d.close + A.HOLD * A.MS4), price: d.band[0] }, text: "분석기 4 다음 16시간 흔한 범위" });
marks.push({ shape: "text", point: { time: sec(last[0]), price: last[2] }, text: "분석기: 신호 " + d.signalName + " · 크기 " + d.state.name + " · 방향 " + d.direction });

const result = {
  source: { symbol: opt.symbol, timeframe: "240", bars_used: s.n, read_at_kst: A.kstFull(now), last_closed_bar_kst: A.kstFull(d.close) },
  verdict: {
    direction: d.direction, signal: d.signalName,
    signal_value: d.upperVol ? +d.upperVol.x.toFixed(4) : null, long_threshold: 0.422, short_threshold: 0.086,
    is_9pm_bar: d.slot, minutes_since_close: +lateMin.toFixed(1), exit_kst: d.exit ? A.kstFull(d.exit) : null,
    size_state: d.state.name, recent_size_pct: +s.rs.toFixed(2), typical_move_pct: d.state.med, p80_move_pct: d.state.p80,
    band_16h: d.band.map(x => Math.round(x)), close: c
  },
  why: d.why, facts: d.facts.map(([k, v]) => ({ name: k, value: v })),
  forward_test: s.fwd ? { bars: s.fwd.n, long_signals: s.fwd.nl, long_mean_pct: s.fwd.nl ? +(s.fwd.lmean * 100).toFixed(3) : null, baseline_pct: +(s.fwd.base * 100).toFixed(3), t: Number.isNaN(s.fwd.t) ? null : +s.fwd.t.toFixed(2) } : null,
  warnings, marks, page: null
};

// 4) 같은 자료를 넣은 분석기 화면
if (opt.page) {
  const out = path.resolve(opt.page);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const all = s.forming ? s.bars.concat([s.forming]) : s.bars;
  fs.writeFileSync(out, buildPage({ embed: { bars: all, now, symbol: String(opt.symbol) } }));
  result.page = out;
}

if (opt.json) { console.log(JSON.stringify(result, null, 1)); process.exit(0); }
const L = [];
L.push("[BTC/USDT 차트분석기 · 트레이딩뷰 " + opt.symbol + " 4시간봉]");
L.push("기준: " + A.kstFull(d.close) + " KST 마감 봉 (읽은 시각 " + A.kstFull(now) + ", 봉 " + s.n + "개)");
L.push("");
L.push("방향: " + d.direction);
L.push("크기: " + d.state.name + " · 다음 16시간 보통 ±" + d.state.med.toFixed(2) + "%, 5번 중 4번은 " + A.fmt(d.band[0], 0) + " ~ " + A.fmt(d.band[1], 0));
L.push("신호: " + d.signalName + (d.upperVol ? " (값 " + d.upperVol.x.toFixed(3) + ", 롱 기준 0.422 이상)" : ""));
if (d.signal === 1) {
  if (!d.slot) L.push("  이 봉은 밤 9시 마감 봉이 아니라 실전 대상이 아닙니다. 기록만 합니다.");
  else if (lateMin > 15) L.push("  마감 뒤 " + lateMin.toFixed(0) + "분이 지났습니다. 규칙상 15분이 넘으면 건너뜁니다.");
  else L.push("  실전 대상입니다. 청산 시각 " + A.kstFull(d.exit) + " KST. 주문은 PROTOCOL.md의 주문표대로 사람이 직접 합니다.");
}
L.push("");
L.push("판단 근거");
d.why.forEach((t, k) => L.push("  " + (k + 1) + ". " + t));
L.push("");
L.push("차트 구조");
d.facts.forEach(([k, v]) => L.push("  - " + k + ": " + v));
if (s.fwd) L.push("", "2026-09-29 이후 성적(이 자료 범위): 봉 " + s.fwd.n + "개, 롱 신호 " + s.fwd.nl + "번" + (s.fwd.nl ? ", 평균 " + A.pct(s.fwd.lmean * 100, 3) + " (아무 때나 롱 " + A.pct(s.fwd.base * 100, 3) + ")" : ""));
if (warnings.length) { L.push("", "주의"); warnings.forEach(w => L.push("  ! " + w)); }
if (result.page) L.push("", "분석기 화면: " + result.page);
console.log(L.join("\n"));
