/* 한 번의 분석(읽기 → 판정 → 해설 → 기록)과 일정 계산. */
const fs = require("fs"), path = require("path");
const A = require("../src/core.js");
const J = require("../src/judge.cjs");
const { buildPage } = require("../build.cjs");
const Src = require("./sources.cjs");
const { writeCommentary } = require("./commentary.cjs");

const DEFAULTS = {
  port: 8787,
  delaySeconds: 90,              // 4시간봉 마감 뒤 몇 초 기다렸다가 읽을지
  commentary: { enabled: false, model: "claude-opus-5-5", effort: "medium" }
};
const HERE = __dirname;

function loadConfig(file) {
  const f = file || path.join(HERE, "config.json");
  let user = {};
  if (fs.existsSync(f)) { try { user = JSON.parse(fs.readFileSync(f, "utf8")); } catch (e) { throw new Error("설정 파일을 읽지 못했습니다(" + f + "): " + e.message); } }
  const cfg = { ...DEFAULTS, ...user, commentary: { ...DEFAULTS.commentary, ...(user.commentary || {}) } };
  if (!(cfg.delaySeconds >= 30 && cfg.delaySeconds <= 3600)) throw new Error("설정의 delaySeconds는 30~3600 사이여야 합니다.");
  if (!Number.isInteger(cfg.port) || cfg.port < 1024 || cfg.port > 65535) throw new Error("설정의 port는 1024~65535 사이 정수여야 합니다.");
  cfg.dataDir = cfg.dataDir || path.join(HERE, "data");
  return cfg;
}

/* 다음 실행 시각: 4시간봉 마감(UTC 0·4·8·12·16·20시 = 한국 9·13·17·21·1·5시) + 기다림 */
function nextRunAt(now, delaySeconds) {
  const delay = delaySeconds * 1000;
  let t = Math.floor(now / A.MS4) * A.MS4 + delay;
  if (t <= now) t += A.MS4;
  return t;
}

/* 한 번 분석한다. 실패해도 던지지 않고 기록에 이유를 남긴다. */
async function runOnce(cfg, trigger, deps) {
  const d = { readBinance: Src.readBinance, writeCommentary, now: () => Date.now(), ...(deps || {}) };
  const started = d.now();
  const rec = { run_at_ms: started, run_at_kst: A.kstFull(started), trigger, ok: false, source_used: null, notes: [] };
  let got = null;
  try { got = await d.readBinance(cfg); rec.source_used = "binance"; }
  catch (e) { rec.notes.push("바이낸스: " + (e instanceof J.Stop ? e.message : "예상하지 못한 오류(" + e.message + ")")); }
  if (!got) { rec.error = "자료를 읽지 못해 이번 회차는 분석하지 않았습니다."; return save(cfg, rec); }

  const now = d.now();
  let out;
  try { out = J.judge(got.bars, now, "바이낸스 " + got.symbol); }
  catch (e) { rec.error = e instanceof J.Stop ? e.message : "판정 중 오류: " + e.message; return save(cfg, rec); }
  const { result, s } = out;
  rec.ok = true;
  rec.bar_close_ms = result.bar_close_ms;
  rec.bar_close_kst = result.source.last_closed_bar_kst;
  rec.result = result;
  rec.commentary = await d.writeCommentary(cfg, result, s);

  // 대시보드에 넣을 분석기 화면
  fs.mkdirSync(cfg.dataDir, { recursive: true });
  const all = s.forming ? s.bars.concat([s.forming]) : s.bars;
  fs.writeFileSync(path.join(cfg.dataDir, "chart.html"), buildPage({ embed: { bars: all, now, symbol: result.source.symbol } }));
  // 지난 신호의 16시간 뒤 결과를 채울 수 있게 최근 종가를 남긴다
  rec.closes = s.bars.slice(-60).map(b => [b[0] + A.MS4, b[4]]);
  return save(cfg, rec);
}

function save(cfg, rec) {
  fs.mkdirSync(cfg.dataDir, { recursive: true });
  const { closes, ...line } = rec;
  fs.appendFileSync(path.join(cfg.dataDir, "runs.jsonl"), JSON.stringify(line) + "\n");
  if (closes) fs.writeFileSync(path.join(cfg.dataDir, "closes.json"), JSON.stringify(closes));
  return rec;
}

/* 기록을 읽어 대시보드용으로 정리한다: 마감 봉마다 마지막 성공 기록 하나 */
function history(cfg, limit) {
  const f = path.join(cfg.dataDir, "runs.jsonl");
  if (!fs.existsSync(f)) return { runs: [], last: null, lastOk: null };
  const lines = fs.readFileSync(f, "utf8").split("\n").filter(Boolean);
  const all = []; for (const l of lines) { try { all.push(JSON.parse(l)); } catch (e) { /* 깨진 줄은 건너뜀 */ } }
  let closes = new Map();
  try { closes = new Map(JSON.parse(fs.readFileSync(path.join(cfg.dataDir, "closes.json"), "utf8"))); } catch (e) { /* 아직 없음 */ }
  const byBar = new Map(); for (const r of all) if (r.ok) byBar.set(r.bar_close_ms, r);
  const runs = [...byBar.values()].sort((a, b) => b.bar_close_ms - a.bar_close_ms).slice(0, limit || 60).map(r => {
    const v = r.result.verdict, exitClose = closes.get(r.bar_close_ms + A.HOLD * A.MS4);
    return {
      bar_close_kst: r.bar_close_kst, source: r.source_used, signal: v.signal, signal_value: v.signal_value, size_state: v.size_state,
      close: v.close, is_9pm_bar: v.is_9pm_bar,
      after_16h_pct: exitClose ? +((exitClose / v.close - 1) * 100).toFixed(3) : null
    };
  });
  const last = all.length ? all[all.length - 1] : null;
  let lastOk = null; for (let k = all.length - 1; k >= 0; k--) if (all[k].ok) { lastOk = all[k]; break; }
  return { runs, last, lastOk };
}

module.exports = { DEFAULTS, loadConfig, nextRunAt, runOnce, history };
