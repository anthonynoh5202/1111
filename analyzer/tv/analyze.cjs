#!/usr/bin/env node
/* 트레이딩뷰에서 읽은 4시간봉을 우리 분석기 기준으로 판정한다(한 번 실행하는 명령줄 도구).
   이 도구는 읽고 계산만 한다. 주문 기능이 없다. 정해진 시각마다 자동으로 돌리려면 analyzer/platform 을 쓴다.

   쓰는 법(저장소 폴더에서, 맥·윈도우 같음):
     node analyzer/tv/analyze.cjs --from-tv --page analyzer/tv/out/chart.html

   옵션
     --from-tv        트레이딩뷰에서 차트 상태(종목·주기)와 4시간봉 500개를 직접 읽는다.
     --symbol, --tf   --from-tv 없이 `tv ohlcv` 출력을 표준 입력으로 줄 때, 차트 상태에서 읽은 값을 적는다.
                      어느 쪽이든 BTCUSDT 무기한 선물 4시간봉이 아니면 멈춘다.
     --page <파일>    같은 자료를 넣은 분석기 화면(HTML)을 만든다.
     --json           사람이 읽는 글 대신 JSON으로 낸다(차트에 그릴 표시 목록 포함).
     --file <파일>    표준 입력 대신 파일에서 읽는다.  --now-ms <숫자>  시험용. */
const fs = require("fs"), path = require("path");
const { buildPage } = require("../build.cjs");
const J = require("./judge.cjs");

function fail(msg) { console.error("멈춤: " + msg); process.exit(1); }
function args(argv) {
  const o = {}; for (let k = 0; k < argv.length; k++) {
    const a = argv[k]; if (!a.startsWith("--")) fail("알 수 없는 인자: " + a);
    const key = a.slice(2); if (key === "json" || key === "from-tv") o[key] = true; else o[key] = argv[++k];
  } return o;
}
const opt = args(process.argv.slice(2));

// 트레이딩뷰에서 직접 읽기(연결 도구의 명령을 그대로 부른다. 셸 파이프를 쓰지 않아 윈도우에서도 같다)
function tv(cmd, extra) {
  const cli = path.join(__dirname, "../../vendor/tradingview-mcp/src/cli/index.js");
  if (!fs.existsSync(cli)) fail("연결 도구가 없습니다. 먼저 설치하세요: analyzer/tv/README.md");
  const r = require("child_process").spawnSync(process.execPath, [cli, cmd, ...(extra || [])], { encoding: "utf8", maxBuffer: 32 * 1024 * 1024, timeout: 120000 });
  let j = null; for (const t of [r.stdout, r.stderr]) { try { j = JSON.parse(t); break; } catch (e) { /* 다음 */ } }
  if (!j) fail("트레이딩뷰 연결 도구가 답하지 않았습니다(" + cmd + ").");
  if (j.success === false) fail("트레이딩뷰에서 읽지 못했습니다: " + j.error + "\n      트레이딩뷰가 디버그 모드로 떠 있는지 확인하세요(analyzer/tv/README.md의 '연결이 안 될 때').");
  return j;
}
function readStdin() {
  const chunks = [], buf = Buffer.alloc(65536);
  for (;;) {
    let n; try { n = fs.readSync(0, buf, 0, buf.length, null); } catch (e) { if (e.code === "EAGAIN") continue; if (e.code === "EOF") break; throw e; }
    if (!n) break; chunks.push(Buffer.from(buf.subarray(0, n)));
  }
  return Buffer.concat(chunks).toString("utf8");
}

try {
  if (opt["from-tv"]) { const st = tv("state"); opt.symbol = st.symbol; opt.tf = st.resolution; }
  J.checkChart(opt.symbol, opt.tf);

  let raw;
  if (opt["from-tv"]) raw = tv("ohlcv", ["--count", "500"]);
  else { try { raw = JSON.parse(opt.file ? fs.readFileSync(opt.file, "utf8") : readStdin()); } catch (e) { fail("입력을 JSON으로 읽지 못했습니다. `tv ohlcv` 출력이 맞는지 확인하세요."); } }
  if (!raw || raw.success === false || !Array.isArray(raw.bars)) fail("봉 자료가 없습니다" + (raw && raw.error ? ": " + raw.error : "."));

  const now = opt["now-ms"] ? Number(opt["now-ms"]) : Date.now();
  const { result, s, d } = J.judge(J.toBars(raw.bars), now, opt.symbol);
  result.page = null;
  if (opt.page) {
    const out = path.resolve(opt.page);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    const all = s.forming ? s.bars.concat([s.forming]) : s.bars;
    fs.writeFileSync(out, buildPage({ embed: { bars: all, now, symbol: "트레이딩뷰 " + String(opt.symbol) } }));
    result.page = out;
  }
  if (opt.json) console.log(JSON.stringify(result, null, 1));
  else console.log(J.toText(result, d) + (result.page ? "\n\n분석기 화면: " + result.page : ""));
} catch (e) {
  if (e instanceof J.Stop) fail(e.message);
  throw e;
}
