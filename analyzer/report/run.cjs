/* BTC/USDT 차트 데이터 -> 검증 신호 계산 -> (클로드 자유 분석) -> 2장 PDF -> 텔레그램.
   사용법:
     node run.cjs fetch   OKX 실시간 봉을 받아 검증 신호를 계산하고 latest.json 에 저장
     node run.cjs send    latest.json + page_a.json 으로 2장 PDF를 만들어 텔레그램 전송
     node run.cjs both    위 둘을 잇따라 (클로드 분석 없이 자리표시로)
   page_a.json 모양: { "call": "롱|숏|관망", "summary": "한 줄 요약", "body": "본문" } */
const fs = require("fs"), path = require("path");
const A = require("../src/core.js");
const J = require("../tv/judge.cjs");
const { readOKX, readOKXTf } = require("./okx.cjs");
const { computeTf, tfChart } = require("./mtf.cjs");
const { buildPdf } = require("./pdf.cjs");
const tg = require("./telegram.cjs");

const TFS = [["5분", "5m"], ["15분", "15m"], ["30분", "30m"], ["1시간", "1H"], ["4시간", "4H"], ["일봉", "1D"]];

const HERE = __dirname;
const LATEST = path.join(HERE, "latest.json");
const PAGE_A = path.join(HERE, "page_a.json");
const PDF = path.join(HERE, "report.pdf");

function secrets() {
  const f = path.join(HERE, "secrets.json");
  if (!fs.existsSync(f)) throw new Error("secrets.json 이 없습니다. { telegram_token, chat_id } 를 넣으세요.");
  // 이 파일이 git에 올라가 있으면 보내지 않는다(공개 저장소에 토큰이 새는 것을 막는다)
  const tracked = require("child_process").spawnSync("git", ["ls-files", "--error-unmatch", "secrets.json"], { cwd: HERE, stdio: "ignore" });
  if (tracked.status === 0) throw new Error("secrets.json 이 git에 올라가 있습니다. 토큰을 새로 발급받고, 파일을 git에서 빼세요(git rm --cached analyzer/report/secrets.json).");
  if (process.platform !== "win32" && (fs.statSync(f).mode & 0o077)) console.error("주의: secrets.json 을 이 PC의 다른 사용자도 읽을 수 있습니다. chmod 600 analyzer/report/secrets.json 을 권합니다.");
  let s; try { s = JSON.parse(fs.readFileSync(f, "utf8")); } catch (e) { throw new Error("secrets.json 을 읽지 못했습니다(JSON 모양 확인)."); }
  return s;
}

/* core.js 결과(s)에서 차트에 그릴 자료를 뽑는다. 최근 N개 봉만. */
function chartData(s) {
  const N = 80;
  const b = s.bars, nClosed = b.length;
  const all = s.forming ? b.concat([s.forming]) : b;
  const start = Math.max(0, all.length - N);
  const volAvg = A.sma(b.map(x => x[5]), A.AVG);   // 마감 봉 기준 거래량 20봉 평균
  const bars = [];
  for (let gi = start; gi < all.length; gi++) {
    const forming = gi >= nClosed;                 // 마지막 진행 중 봉
    const ci = forming ? -1 : gi;
    bars.push({
      t: all[gi][0], o: all[gi][1], h: all[gi][2], l: all[gi][3], c: all[gi][4], v: all[gi][5],
      ma20: ci >= 0 ? s.ma20[ci] : null, ma60: ci >= 0 ? s.ma60[ci] : null, volAvg: ci >= 0 ? volAvg[ci] : null, forming
    });
  }
  const lastPeak = s.ph.length ? s.ph[s.ph.length - 1].i : null;
  const lastTrough = s.pl.length ? s.pl[s.pl.length - 1].i : null;
  const toWin = gi => (gi == null || gi < start) ? null : gi - start;
  let lo = Infinity, hi = -Infinity; for (const b of bars) { lo = Math.min(lo, b.l); hi = Math.max(hi, b.h); }
  return {
    bars,
    res: s.res ? s.res.p : null, sup: s.sup ? s.sup.p : null,
    band: [s.px * (1 - A.STATES[s.state].p80 / 100), s.px * (1 + A.STATES[s.state].p80 / 100)].map(x => Math.round(x)),
    sigIdx: toWin(s.i), last6Idx: toWin(s.i - 5),
    peakIdx: toWin(lastPeak), troughIdx: toWin(lastTrough),
    range: { from: A.kstFull(bars[0].t), to: A.kstFull(bars[bars.length - 1].t), lo: Math.round(lo), hi: Math.round(hi), n: bars.length }
  };
}

/* 단타 요약표: 여러 타임프레임을 각각 읽어 상태를 계산한다. */
async function fetchMtf() {
  const out = [];
  for (const [label, bar] of TFS) {
    try {
      const rows = await readOKXTf(bar, 300);
      const stat = computeTf(rows, bar);
      out.push(Object.assign({ label, bar }, stat, { chart: tfChart(rows, stat.sup, stat.res) }));
    }
    catch (e) { out.push({ label, bar, error: e.message }); }
  }
  return out;
}

async function fetchStep() {
  const now = Date.now();
  const got = await readOKX({ bars: 900 });
  const { result, s } = J.judge(got.bars, now, got.symbol);
  const recent = got.bars.slice(-14).map(b => ({ kst: A.kstFull(b[0]), o: b[1], h: b[2], l: b[3], c: b[4], v: +b[5].toFixed(1) }));
  const chart = chartData(s);
  const mtf = await fetchMtf();
  fs.writeFileSync(LATEST, JSON.stringify({ now, symbol: got.symbol, forming_included: got.forming_included, result, chart, mtf, recent }, null, 1));
  console.log("저장:", LATEST);
  console.log("검증 신호:", result.verdict.signal, "| 방향:", result.verdict.direction, "| 신호값:", result.verdict.signal_value, "| 크기:", result.verdict.size_state);
  console.log("기준 봉:", result.source.last_closed_bar_kst, "KST 마감 · 봉", result.source.bars_used, "개");
  if (result.warnings.length) console.log("주의:", result.warnings.join(" / "));
}

function loadForBuild() {
  if (!fs.existsSync(LATEST)) throw new Error("latest.json 이 없습니다. 먼저 node run.cjs fetch 를 하세요.");
  const latest = JSON.parse(fs.readFileSync(LATEST, "utf8"));
  let pageA = { call: "관망", summary: "", body: "(클로드 분석이 아직 작성되지 않았습니다. 예약작업에서 이 칸을 채웁니다.)" };
  if (fs.existsSync(PAGE_A)) { try { pageA = JSON.parse(fs.readFileSync(PAGE_A, "utf8")); } catch (e) { throw new Error("page_a.json 을 읽지 못했습니다: " + e.message); } }
  return { latest, pageA };
}

async function buildStep() {
  const { latest, pageA } = loadForBuild();
  await buildPdf(PDF, { pageA, scalp: pageA.scalp, result: latest.result, chart: latest.chart, mtf: latest.mtf });
  console.log("PDF 만듦:", PDF);
}

async function sendStep() {
  const { latest, pageA } = loadForBuild();
  await buildPdf(PDF, { pageA, scalp: pageA.scalp, result: latest.result, chart: latest.chart, mtf: latest.mtf });
  const v = latest.result.verdict;
  const cap = "BTC/USDT 분석 보고서 · " + latest.result.source.read_at_kst + " KST\n1쪽 클로드 판단: " + (pageA.call || "-") + " · 2쪽 검증 신호: " + v.signal;
  const s = secrets();
  await tg.sendDocument(s.telegram_token, s.chat_id, PDF, cap);
  console.log("텔레그램 전송 완료:", PDF);
}

(async () => {
  const cmd = process.argv[2];
  try {
    if (cmd === "fetch") await fetchStep();
    else if (cmd === "send") await sendStep();
    else if (cmd === "build") await buildStep();
    else if (cmd === "both") { await fetchStep(); await sendStep(); }
    else { console.error("사용법: node run.cjs [fetch|send|build|both]"); process.exit(1); }
  } catch (e) { console.error("오류:", e.message); process.exit(1); }
})();
