/* 실행: node --test analyzer/test
   계산 모듈이 연구 코드(research/pilot5/pilot.py)와 같은 값을 내는지, 트레이딩뷰 도구가 잘못된 입력을 거부하는지 본다. */
const test = require("node:test"), assert = require("node:assert"), fs = require("fs"), path = require("path"), cp = require("child_process");
const A = require("../src/core.js");
const snap = JSON.parse(fs.readFileSync(path.join(__dirname, "../src/snapshot.json"), "utf8"));
const now = snap[snap.length - 1][0] + A.MS4 + 60000;
const CLI = path.join(__dirname, "../tv/analyze.cjs");
const tvJson = bars => JSON.stringify({ success: true, bars: bars.map(b => ({ time: b[0] / 1000, open: b[1], high: b[2], low: b[3], close: b[4], volume: b[5] })) });
const run = (input, args) => cp.spawnSync("node", [CLI, ...args], { input, encoding: "utf8" });

test("마지막 봉의 신호값과 크기 상태가 연구 코드 값과 같다", () => {
  const s = A.analyze(snap, now, false);
  assert.ok(Math.abs(s.uv[s.i].x - 0.15159329881093753) < 1e-12);   // pilot.py upper_vol
  assert.ok(Math.abs(s.rs - 1.2804535523565146) < 1e-12);           // size_states.py recent
  assert.strictEqual(A.STATES[s.state].name, "조용");
  assert.strictEqual(s.sig[s.i], 0);
});
test("기준값 경계: 0.4217300308371426 이상은 롱, 0.08566545851163947 이하는 숏", () => {
  assert.strictEqual(A.sigOf(A.Q80), 1); assert.strictEqual(A.sigOf(A.Q80 - 1e-9), 0);
  assert.strictEqual(A.sigOf(A.Q20), -1); assert.strictEqual(A.sigOf(A.Q20 + 1e-9), 0); assert.strictEqual(A.sigOf(null), 0);
});
test("마감 안 된 봉은 판정에 쓰지 않는다", () => {
  const s = A.analyze(snap, snap[snap.length - 1][0] + 1000, false);
  assert.strictEqual(s.n, snap.length - 1); assert.ok(s.forming);
});
test("빠진 봉이 있으면 그 뒤 구간만 쓴다", () => {
  const cut = snap.slice(0, 1000).concat(snap.slice(1001));
  const s = A.analyze(cut, now, false);
  assert.strictEqual(s.n, 499); assert.strictEqual(s.gapAt, snap[1001][0]);
});
test("봉이 모자라면 멈춘다", () => { assert.throws(() => A.analyze(snap.slice(-50), now, false), /개 이상 필요/); });
test("트레이딩뷰 도구: 500봉을 넣으면 화면과 같은 판정을 낸다", () => {
  const r = run(tvJson(snap.slice(-500)), ["--symbol", "BINANCE:BTCUSDT.P", "--tf", "240", "--json", "--now-ms", String(now)]);
  assert.strictEqual(r.status, 0, r.stderr);
  const j = JSON.parse(r.stdout);
  assert.strictEqual(j.verdict.signal, "없음"); assert.strictEqual(j.verdict.direction, "모름"); assert.strictEqual(j.verdict.size_state, "조용");
  assert.strictEqual(j.verdict.signal_value, 0.1516); assert.strictEqual(j.why.length, 8); assert.ok(j.marks.length >= 2);
});
test("트레이딩뷰 도구: 다른 종목·다른 주기·깨진 입력은 거부한다", () => {
  assert.notStrictEqual(run(tvJson(snap.slice(-500)), ["--symbol", "BINANCE:ETHUSDT.P", "--tf", "240"]).status, 0);
  assert.notStrictEqual(run(tvJson(snap.slice(-500)), ["--symbol", "BINANCE:BTCUSDT.P", "--tf", "60"]).status, 0);
  assert.notStrictEqual(run(tvJson(snap.slice(-500).filter((_, k) => k % 6 === 0)), ["--symbol", "BINANCE:BTCUSDT.P", "--tf", "240"]).status, 0);
  assert.notStrictEqual(run("not json", ["--symbol", "BINANCE:BTCUSDT.P", "--tf", "240"]).status, 0);
});
