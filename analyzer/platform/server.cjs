#!/usr/bin/env node
/* BTC/USDT 차트분석기 자동 분석 플랫폼.
   4시간봉이 마감될 때마다 트레이딩뷰(MCP)에서 봉을 읽어 고정된 기준으로 판정하고, 기록과 대시보드를 남긴다.
   읽기 전용이다. 주문 기능이 없다. 이 컴퓨터 안에서만 열린다(127.0.0.1).

   실행(저장소 폴더에서):  node analyzer/platform/server.cjs
   한 번만 분석하고 끝내기:  node analyzer/platform/server.cjs --once */
const http = require("http"), fs = require("fs"), path = require("path"), crypto = require("crypto");
const A = require("../src/core.js");
const E = require("./engine.cjs");

function createApp(cfg, deps) {
  const token = crypto.randomBytes(24).toString("hex");
  const state = { running: false, nextRunAt: null, timer: null, startedAt: Date.now() };
  const dash = fs.readFileSync(path.join(__dirname, "dashboard.html"), "utf8");
  const now = () => (deps && deps.now ? deps.now() : Date.now());

  async function run(trigger) {
    if (state.running) return null;          // 겹쳐 돌리지 않는다
    state.running = true;
    try { return await E.runOnce(cfg, trigger, deps); }
    finally { state.running = false; }
  }
  function schedule() {
    state.nextRunAt = E.nextRunAt(now(), cfg.delaySeconds);
    state.timer = setTimeout(async () => { try { await run("일정"); } catch (e) { console.error("일정 실행 오류:", e.message); } schedule(); }, Math.max(1000, state.nextRunAt - now()));
    if (state.timer.unref && deps && deps.unref) state.timer.unref();
  }
  function status() {
    const h = E.history(cfg, 60), ok = h.lastOk;
    return {
      running: state.running, next_run_kst: state.nextRunAt ? A.kstFull(state.nextRunAt) : null, next_run_ms: state.nextRunAt,
      config: { source: cfg.source, fallbackToBinance: cfg.fallbackToBinance, crossCheck: cfg.crossCheck, autoSwitchChart: cfg.autoSwitchChart, commentary: cfg.commentary.enabled, model: cfg.commentary.model },
      last_run: h.last ? { run_at_kst: h.last.run_at_kst, ok: h.last.ok, trigger: h.last.trigger, source_used: h.last.source_used, notes: h.last.notes, error: h.last.error || null } : null,
      latest: ok ? { run_at_kst: ok.run_at_kst, source_used: ok.source_used, cross_check: ok.cross_check || null, result: { ...ok.result, marks: undefined }, commentary: ok.commentary || null } : null,
      history: h.runs
    };
  }

  const SEC = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'unsafe-inline'; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; img-src data:; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
    "X-Frame-Options": "SAMEORIGIN", "Cross-Origin-Resource-Policy": "same-origin"
  };
  const send = (res, code, type, body) => { res.writeHead(code, { "Content-Type": type, ...SEC }); res.end(body); };
  const json = (res, code, obj) => send(res, code, "application/json; charset=utf-8", JSON.stringify(obj));

  const server = http.createServer(async (req, res) => {
    // 이 컴퓨터에서 연 주소만 받는다(다른 사이트가 이름을 속여 접근하는 것을 막는다)
    const host = String(req.headers.host || "");
    if (host !== "127.0.0.1:" + cfg.port && host !== "localhost:" + cfg.port) return send(res, 403, "text/plain; charset=utf-8", "거부했습니다.");
    try {
      if (req.method !== "GET" && req.method !== "POST") return send(res, 405, "text/plain; charset=utf-8", "쓸 수 없는 방식입니다.");
      let url; try { url = new URL(req.url, "http://" + host); } catch (e) { return send(res, 400, "text/plain; charset=utf-8", "잘못된 주소입니다."); }
      if (req.method === "GET" && url.pathname === "/") return send(res, 200, "text/html; charset=utf-8", dash.replace("__TOKEN__", token));
      if (req.method === "GET" && url.pathname === "/chart") {
        const f = path.join(cfg.dataDir, "chart.html");
        if (!fs.existsSync(f)) return send(res, 200, "text/html; charset=utf-8", '<!DOCTYPE html><meta charset="utf-8"><body style="font-family:sans-serif;padding:24px;color:#667">아직 분석한 자료가 없습니다.</body>');
        return send(res, 200, "text/html; charset=utf-8", fs.readFileSync(f));
      }
      if (req.method === "GET" && url.pathname === "/api/status") return json(res, 200, status());
      if (req.method === "POST" && url.pathname === "/api/run") {
        // 대시보드에서 누른 것만 받는다
        const given = Buffer.from(String(req.headers["x-token"] || "")), want = Buffer.from(token);
        if (given.length !== want.length || !crypto.timingSafeEqual(given, want)) return json(res, 403, { ok: false, message: "허락되지 않은 요청입니다." });
        if (req.headers.origin && req.headers.origin !== "http://" + host) return json(res, 403, { ok: false, message: "허락되지 않은 요청입니다." });
        if (state.running) return json(res, 409, { ok: false, message: "이미 분석하는 중입니다." });
        const rec = await run("직접");
        return json(res, 200, { ok: !!(rec && rec.ok), message: rec && rec.ok ? "분석했습니다." : (rec && rec.error) || "분석하지 못했습니다." });
      }
      return send(res, 404, "text/plain; charset=utf-8", "없는 주소입니다.");
    } catch (e) {
      console.error("요청 처리 오류:", e.message);
      return json(res, 500, { ok: false, message: "처리 중 오류가 났습니다." });
    }
  });
  return { server, run, schedule, status, token, stop: () => { clearTimeout(state.timer); server.close(); } };
}

module.exports = { createApp };

if (require.main === module) {
  let cfg;
  try { cfg = E.loadConfig(); } catch (e) { console.error("멈춤: " + e.message); process.exit(1); }
  if (process.argv.includes("--once")) {
    E.runOnce(cfg, "직접").then(rec => {
      if (rec.ok) { const v = rec.result.verdict; console.log(rec.bar_close_kst + " 마감 봉 · 자료 " + rec.source_used + " · 방향 " + v.direction + " · 크기 " + v.size_state + " · 신호 " + v.signal); }
      else console.log("분석하지 못했습니다: " + rec.error);
      rec.notes.forEach(n => console.log("  - " + n));
      process.exit(rec.ok ? 0 : 1);
    });
  } else {
    const app = createApp(cfg);
    app.server.on("error", e => { console.error("멈춤: " + (e.code === "EADDRINUSE" ? cfg.port + "번 포트를 이미 쓰고 있습니다. 설정의 port를 바꾸거나 먼저 켠 것을 끄세요." : e.message)); process.exit(1); });
    app.server.listen(cfg.port, "127.0.0.1", () => {
      console.log("차트분석기 플랫폼을 켰습니다.  대시보드: http://127.0.0.1:" + cfg.port);
      console.log("자료: " + (cfg.source === "tradingview" ? "트레이딩뷰(MCP)" + (cfg.fallbackToBinance ? ", 못 읽으면 바이낸스" : "") : "바이낸스") + " · Claude 해설: " + (cfg.commentary.enabled ? "켬(" + cfg.commentary.model + ")" : "끔"));
      app.schedule();
      console.log("다음 자동 분석: " + app.status().next_run_kst + " KST (4시간마다). 끄려면 Ctrl+C.");
      app.run("시작").then(rec => { if (rec) console.log(rec.ok ? "첫 분석을 마쳤습니다(" + rec.bar_close_kst + " 마감 봉, 자료 " + rec.source_used + ")." : "첫 분석을 하지 못했습니다: " + rec.error); if (rec) rec.notes.forEach(n => console.log("  - " + n)); });
    });
  }
}
