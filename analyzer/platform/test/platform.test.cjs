/* 실행: (analyzer/platform 폴더에서) npm test
   가짜 트레이딩뷰 MCP 서버, 가짜 바이낸스, 가짜 Anthropic API로 한 회차 전체를 돌려 본다. 진짜 서비스에는 접속하지 않는다. */
const test = require("node:test"), assert = require("node:assert"), fs = require("fs"), os = require("os"), path = require("path"), http = require("http");
const A = require("../../src/core.js");
const E = require("../engine.cjs");
const Src = require("../sources.cjs");
const { createApp } = require("../server.cjs");

const snap = JSON.parse(fs.readFileSync(path.join(__dirname, "../../src/snapshot.json"), "utf8"));
const NOW = snap[snap.length - 1][0] + A.MS4 + 7 * 60000;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "btcan-"));
const tvFile = path.join(tmp, "tv.json");
const writeTv = bars => fs.writeFileSync(tvFile, JSON.stringify({ success: true, bars: bars.map(b => ({ time: b[0] / 1000, open: b[1], high: b[2], low: b[3], close: b[4], volume: b[5] })) }));
writeTv(snap.slice(-500));

let seen = { anthropic: null, anthropicHeaders: null, anthropicMode: "ok", binanceMode: "ok" };
const fake = http.createServer((req, res) => {
  let body = ""; req.on("data", d => body += d); req.on("end", () => {
    if (req.url.startsWith("/fapi/v1/klines")) {
      if (seen.binanceMode === "down") { res.writeHead(503); return res.end("x"); }
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify(snap.map(b => [b[0], String(b[1]), String(b[2]), String(b[3]), String(b[4]), String(b[5]), b[0] + A.MS4 - 1])));
    }
    if (req.url.startsWith("/v1/messages")) {
      seen.anthropic = JSON.parse(body); seen.anthropicHeaders = req.headers;
      if (seen.anthropicMode === "401") { res.writeHead(401, { "Content-Type": "application/json" }); return res.end(JSON.stringify({ type: "error", error: { type: "authentication_error", message: "invalid x-api-key" } })); }
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ id: "msg_test", type: "message", role: "assistant", model: "claude-opus-5-5", content: [{ type: "thinking", thinking: "", signature: "s" }, { type: "text", text: "1. 한 줄 결론: 방향은 모름입니다." }], stop_reason: "end_turn", stop_sequence: null, usage: { input_tokens: 1200, output_tokens: 300 } }));
    }
    res.writeHead(404); res.end();
  });
});
let base;
test.before(async () => { await new Promise(r => fake.listen(0, "127.0.0.1", r)); base = "http://127.0.0.1:" + fake.address().port; process.env.ANTHROPIC_API_KEY = "test-key-not-real"; });
test.after(() => { fake.close(); fs.rmSync(tmp, { recursive: true, force: true }); });

let dirN = 0;
const fakeEnv = () => Object.fromEntries(Object.entries(process.env).filter(([k]) => k.startsWith("FAKE_")));
const cfgOf = over => ({ ...E.DEFAULTS, mcpEnv: fakeEnv(), mcpServerPath: path.join(__dirname, "fake_tv_server.cjs"), binanceBase: base, switchWaitMs: 10, dataDir: path.join(tmp, "d" + (++dirN)), ...over, commentary: { ...E.DEFAULTS.commentary, baseURL: base, ...((over || {}).commentary || {}) } });
const deps = { now: () => NOW };
const env = (o, fn) => async () => { const old = {}; for (const k in o) { old[k] = process.env[k]; process.env[k] = o[k]; } try { await fn(); } finally { for (const k in o) { if (old[k] === undefined) delete process.env[k]; else process.env[k] = old[k]; } } };

test("다음 실행 시각은 4시간봉 마감 + 기다림이다", () => {
  const t0 = Date.UTC(2026, 10, 18, 12, 0, 0);                       // 한국 21:00 마감
  assert.strictEqual(E.nextRunAt(t0 - 1000, 90), t0 + 90000);
  assert.strictEqual(E.nextRunAt(t0 + 10000, 90), t0 + 90000);       // 마감 직후, 아직 안 돌았으면 이번 것
  assert.strictEqual(E.nextRunAt(t0 + 90000, 90), t0 + A.MS4 + 90000);
});

test("한 회차: 트레이딩뷰(MCP)에서 읽고, 바이낸스와 대조하고, 판정하고, 해설을 받고, 기록한다", env({ FAKE_BARS: tvFile }, async () => {
  const cfg = cfgOf({ commentary: { enabled: true } });
  const rec = await E.runOnce(cfg, "시험", deps);
  assert.strictEqual(rec.ok, true, JSON.stringify(rec.notes));
  assert.strictEqual(rec.source_used, "tradingview");
  assert.deepStrictEqual([rec.cross_check.ok, rec.cross_check.compared], [true, 20]);
  assert.strictEqual(rec.result.verdict.signal, "없음"); assert.strictEqual(rec.result.verdict.direction, "모름");
  assert.strictEqual(rec.result.verdict.signal_value, 0.1516);
  assert.match(rec.commentary.text, /모름/);
  // Claude 호출 모양: 기본 모델, 거절 대비 대체, 노력 수준, 판정을 바꾸지 말라는 지시
  assert.strictEqual(seen.anthropic.model, "claude-opus-5-5"); assert.strictEqual(seen.anthropic.fallbacks, "default");
  assert.strictEqual(seen.anthropic.output_config.effort, "medium"); assert.match(seen.anthropicHeaders["anthropic-beta"], /server-side-fallback-2026-07-01/);
  assert.ok(!("thinking" in seen.anthropic) && !("temperature" in seen.anthropic));
  assert.match(seen.anthropic.messages[0].content, /"signal": "없음"/); assert.ok(!seen.anthropic.messages[0].content.includes('"marks"'));
  assert.ok(fs.readFileSync(path.join(cfg.dataDir, "chart.html"), "utf8").includes("트레이딩뷰 BINANCE:BTCUSDT.P"));
  const h = E.history(cfg);
  assert.strictEqual(h.runs.length, 1); assert.strictEqual(h.runs[0].source, "tradingview");
  assert.ok(!fs.existsSync(tvFile + ".evil"), "위험한 도구를 부르면 안 된다");
}));

test("연결 도구에는 API 키 같은 환경 변수가 넘어가지 않는다", () => {
  const { getDefaultEnvironment } = require("@modelcontextprotocol/sdk/client/stdio.js");
  assert.ok(!("ANTHROPIC_API_KEY" in getDefaultEnvironment()));
});

test("차트가 다른 종목이면 바꾸지 않고 바이낸스 자료로 대신 분석한다", env({ FAKE_BARS: tvFile, FAKE_SYMBOL: "NASDAQ:AAPL" }, async () => {
  const rec = await E.runOnce(cfgOf(), "시험", deps);
  assert.strictEqual(rec.ok, true); assert.strictEqual(rec.source_used, "binance");
  assert.match(rec.notes.join(" "), /BTCUSDT 무기한 선물이 아닙니다/);
  assert.strictEqual(rec.result.source.bars_used, 1500); assert.strictEqual(rec.cross_check, undefined);
  assert.deepStrictEqual(rec.commentary, { skipped: "설정에서 꺼져 있습니다." });
}));

test("자동 전환을 켜면 차트를 BTCUSDT.P 4시간봉으로 바꾼 뒤 읽는다", env({ FAKE_BARS: tvFile, FAKE_SYMBOL: "NASDAQ:AAPL", FAKE_TF: "60" }, async () => {
  const rec = await E.runOnce(cfgOf({ autoSwitchChart: true }), "시험", deps);
  assert.strictEqual(rec.ok, true); assert.strictEqual(rec.source_used, "tradingview");
}));

test("트레이딩뷰와 바이낸스가 다르면 주의를 남긴다", env({ FAKE_BARS: tvFile }, async () => {
  const bad = snap.slice(-500).map((b, k, a) => k === a.length - 2 ? [b[0], b[1], b[2] * 1.01, b[3], b[4] * 1.01, b[5] * 2] : b);
  writeTv(bad);
  try {
    const rec = await E.runOnce(cfgOf(), "시험", deps);
    assert.strictEqual(rec.ok, true); assert.strictEqual(rec.cross_check.ok, false);
    assert.match(rec.result.warnings.join(" "), /최근 봉이 다릅니다/);
  } finally { writeTv(snap.slice(-500)); }
}));

test("둘 다 못 읽으면 분석하지 않고 이유를 남긴다", env({ FAKE_BARS: tvFile, FAKE_FAIL: "1" }, async () => {
  seen.binanceMode = "down";
  try {
    const cfg = cfgOf();
    const rec = await E.runOnce(cfg, "시험", deps);
    assert.strictEqual(rec.ok, false); assert.match(rec.error, /분석하지 않았습니다/); assert.strictEqual(rec.notes.length, 2);
    assert.strictEqual(E.history(cfg).runs.length, 0); assert.strictEqual(E.history(cfg).last.ok, false);
  } finally { seen.binanceMode = "ok"; }
}));

test("API 키가 틀려도 판정은 남고, 해설 자리에 이유가 남는다", env({ FAKE_BARS: tvFile }, async () => {
  seen.anthropicMode = "401";
  try {
    const rec = await E.runOnce(cfgOf({ commentary: { enabled: true } }), "시험", deps);
    assert.strictEqual(rec.ok, true); assert.match(rec.commentary.error, /API 키/);
  } finally { seen.anthropicMode = "ok"; }
}));

test("허락한 도구 목록에는 읽기 도구만 있다", () => {
  assert.deepStrictEqual(Src.READ_TOOLS, ["chart_get_state", "data_get_ohlcv"]);
  assert.deepStrictEqual(Src.SWITCH_TOOLS, ["chart_set_symbol", "chart_set_timeframe"]);
});

test("대시보드 서버: 다른 주소 이름과 토큰 없는 실행 요청을 거부한다", env({ FAKE_BARS: tvFile }, async () => {
  const cfg = cfgOf({ port: 18787 });
  const app = createApp(cfg, deps);
  await new Promise(r => app.server.listen(cfg.port, "127.0.0.1", r));
  const u = "http://127.0.0.1:" + cfg.port;
  const raw = (p, headers, method) => new Promise((res, rej) => { const q = http.request({ host: "127.0.0.1", port: cfg.port, path: p, method: method || "GET", headers }, r => { let b = ""; r.on("data", d => b += d); r.on("end", () => res({ status: r.statusCode, body: b, headers: r.headers })); }); q.on("error", rej); q.end(); });
  try {
    assert.strictEqual((await raw("/", { Host: "evil.example:18787" })).status, 403);
    const page = await raw("/", { Host: "127.0.0.1:18787" });
    assert.strictEqual(page.status, 200); assert.ok(page.body.includes(app.token)); assert.match(page.headers["content-security-policy"], /default-src 'none'/);
    assert.strictEqual((await fetch(u + "/api/run", { method: "POST" })).status, 403);
    assert.strictEqual((await fetch(u + "/api/run", { method: "POST", headers: { "X-Token": "0".repeat(48) } })).status, 403);
    assert.strictEqual((await fetch(u + "/api/run", { method: "POST", headers: { "X-Token": app.token, Origin: "http://evil.example" } })).status, 403);
    const ok = await fetch(u + "/api/run", { method: "POST", headers: { "X-Token": app.token } });
    assert.deepStrictEqual(await ok.json(), { ok: true, message: "분석했습니다." });
    const st = await (await fetch(u + "/api/status")).json();
    assert.strictEqual(st.latest.result.verdict.direction, "모름"); assert.strictEqual(st.history.length, 1); assert.strictEqual(st.latest.result.marks, undefined);
    assert.ok((await (await fetch(u + "/chart")).text()).includes("BTC/USDT 차트분석기"));
    assert.strictEqual((await fetch(u + "/nope")).status, 404);
  } finally { app.stop(); }
}));
