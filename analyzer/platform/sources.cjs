/* 봉 자료를 읽어 오는 곳 두 가지.
   - 트레이딩뷰: MCP 서버(vendor/tradingview-mcp)를 띄워 도구를 부른다. 읽기 도구 두 개만 쓴다.
   - 바이낸스: 선물 공개 시세 API. 키가 필요 없다. 트레이딩뷰를 못 읽을 때의 대체와, 두 자료의 대조에 쓴다. */
const fs = require("fs"), path = require("path");
const { Client } = require("@modelcontextprotocol/sdk/client/index.js");
const { StdioClientTransport, getDefaultEnvironment } = require("@modelcontextprotocol/sdk/client/stdio.js");
const J = require("../tv/judge.cjs");
const A = require("../src/core.js");

const MCP_SERVER = path.join(__dirname, "../../vendor/tradingview-mcp/src/server.js");
// 이 플랫폼이 부를 수 있는 트레이딩뷰 도구는 이것뿐이다. 차트를 바꾸는 두 도구는 설정에서 허락했을 때만 쓴다.
const READ_TOOLS = ["chart_get_state", "data_get_ohlcv"];
const SWITCH_TOOLS = ["chart_set_symbol", "chart_set_timeframe"];
const BINANCE = "https://fapi.binance.com";

const sleep = ms => new Promise(r => setTimeout(r, ms));
function withTimeout(p, ms, what) {
  let t; const guard = new Promise((_, rej) => { t = setTimeout(() => rej(new J.Stop(what + "이(가) " + ms / 1000 + "초 안에 끝나지 않았습니다.")), ms); });
  return Promise.race([p, guard]).finally(() => clearTimeout(t));
}

/* 트레이딩뷰에서 4시간봉 500개를 읽는다. 반환: { bars, symbol } */
async function readTradingView(cfg) {
  const server = cfg.mcpServerPath || MCP_SERVER;
  if (!fs.existsSync(server)) throw new J.Stop("트레이딩뷰 연결 도구가 없습니다. 먼저 analyzer/tv/setup 을 실행하세요.");
  const allowed = new Set(READ_TOOLS.concat(cfg.autoSwitchChart ? SWITCH_TOOLS : []));
  const client = new Client({ name: "btc-analyzer-platform", version: "0.1.0" });
  // 연결 도구에는 기본 환경 변수(PATH 등)만 넘긴다. API 키 같은 값은 넘어가지 않는다.
  const transport = new StdioClientTransport({ command: process.execPath, args: [server], stderr: "ignore", env: { ...getDefaultEnvironment(), ...(cfg.mcpEnv || {}) } });
  const call = async (name, args) => {
    if (!allowed.has(name)) throw new Error("허락하지 않은 도구입니다: " + name);
    const r = await withTimeout(client.callTool({ name, arguments: args || {} }), 60000, "트레이딩뷰 도구 " + name);
    const text = (r.content || []).filter(c => c.type === "text").map(c => c.text).join("");
    let j; try { j = JSON.parse(text); } catch (e) { throw new J.Stop("트레이딩뷰 도구 " + name + "의 답을 읽지 못했습니다."); }
    if (r.isError || j.success === false) throw new J.Stop("트레이딩뷰에서 읽지 못했습니다(" + name + "): " + (j.error || "이유 없음"));
    return j;
  };
  try {
    await withTimeout(client.connect(transport), 20000, "트레이딩뷰 연결 도구 시작");
    let st = await call("chart_get_state");
    const ok = () => { try { J.checkChart(st.symbol, st.resolution); return true; } catch (e) { return false; } };
    if (!ok() && cfg.autoSwitchChart) {
      await call("chart_set_symbol", { symbol: "BINANCE:BTCUSDT.P" });
      await call("chart_set_timeframe", { timeframe: "240" });
      await sleep(cfg.switchWaitMs == null ? 3000 : cfg.switchWaitMs);
      st = await call("chart_get_state");
    }
    J.checkChart(st.symbol, st.resolution);
    const o = await call("data_get_ohlcv", { count: 500 });
    return { bars: J.toBars(o.bars), symbol: String(st.symbol) };
  } finally {
    try { await client.close(); } catch (e) { /* 이미 닫힘 */ }
  }
}

/* 바이낸스 선물 공개 시세에서 4시간봉을 읽는다. 반환: { bars, symbol } */
async function readBinance(cfg, limit) {
  const base = cfg.binanceBase || BINANCE;
  const url = base + "/fapi/v1/klines?symbol=BTCUSDT&interval=4h&limit=" + (limit || 1500);
  let r;
  try { r = await fetch(url, { signal: AbortSignal.timeout(15000), redirect: "error", headers: { Accept: "application/json" } }); }
  catch (e) { throw new J.Stop("바이낸스 시세를 읽지 못했습니다(" + (e.name || "오류") + "). 인터넷 연결과 접속 가능 여부를 확인하세요."); }
  if (!r.ok) throw new J.Stop("바이낸스가 " + r.status + " 을 돌려줬습니다.");
  let rows; try { rows = await r.json(); } catch (e) { throw new J.Stop("바이낸스 응답을 읽지 못했습니다."); }
  if (!Array.isArray(rows) || rows.some(x => !Array.isArray(x) || x.length < 6)) throw new J.Stop("바이낸스 응답이 예상한 모양이 아닙니다.");
  return { bars: J.toBars(rows.map(x => x.slice(0, 6))), symbol: "BTCUSDT" };
}

/* 두 자료의 최근 마감 봉을 대조한다. 종가는 0.05%, 거래량은 3% 넘게 다르면 다르다고 본다 */
function crossCheck(a, b, now) {
  const closed = bars => new Map(bars.filter(x => x[0] + A.MS4 <= now).map(x => [x[0], x]));
  const ma = closed(a), mb = closed(b);
  const times = [...ma.keys()].filter(t => mb.has(t)).sort((x, y) => y - x).slice(0, 20);
  let priceDiff = 0, volDiff = 0, worstPrice = 0, worstVol = 0;
  for (const t of times) {
    const x = ma.get(t), y = mb.get(t);
    const dp = Math.abs(x[4] / y[4] - 1) * 100, dv = y[5] > 0 ? Math.abs(x[5] / y[5] - 1) * 100 : 0;
    worstPrice = Math.max(worstPrice, dp); worstVol = Math.max(worstVol, dv);
    if (dp > 0.05) priceDiff++; if (dv > 3) volDiff++;
  }
  return { compared: times.length, price_mismatch: priceDiff, volume_mismatch: volDiff, worst_price_pct: +worstPrice.toFixed(4), worst_volume_pct: +worstVol.toFixed(2), ok: times.length >= 5 && priceDiff === 0 && volDiff === 0 };
}

module.exports = { readTradingView, readBinance, crossCheck, READ_TOOLS, SWITCH_TOOLS };
