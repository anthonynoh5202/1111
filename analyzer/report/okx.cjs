/* OKX에서 BTC-USDT-SWAP 4시간봉을 읽는다 (공개 API, 키 없음).
   - history-candles: 마감된 봉을 과거로 거슬러 받는다 (일봉 평균선 계산에 충분한 양)
   - candles: 지금 만들어지는 중인 봉까지 포함한 최신 봉
   거래량은 vol_btc(= volCcy, 바이낸스 거래량과 맞는 칼럼. research/okx_vs_futures 에서 검증)를 쓴다.
   4시간봉은 UTC 정렬(00·04·08·12·16·20시)이라 밤 9시 봉 판정이 그대로 맞는다. */
const J = require("../tv/judge.cjs");

const BASE = "https://www.okx.com";
const INST = "BTC-USDT-SWAP";
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function getJson(url) {
  let r;
  try { r = await fetch(url, { signal: AbortSignal.timeout(20000), headers: { "User-Agent": "btc-report/0.1", Accept: "application/json" } }); }
  catch (e) { throw new J.Stop("OKX 시세를 읽지 못했습니다(" + (e.name || "오류") + "). 인터넷/접속 가능 여부를 확인하세요."); }
  if (!r.ok) throw new J.Stop("OKX가 " + r.status + " 을 돌려줬습니다.");
  let j; try { j = await r.json(); } catch (e) { throw new J.Stop("OKX 응답을 읽지 못했습니다."); }
  if (j.code !== "0") throw new J.Stop("OKX 오류: " + (j.msg || j.code));
  return j.data || [];
}

// OKX 한 줄 [ts, o, h, l, c, vol_contracts, vol_btc, vol_quote, confirm] -> [open_time_ms, o, h, l, c, vol_btc]
function toBar(x) { return [Number(x[0]), Number(x[1]), Number(x[2]), Number(x[3]), Number(x[4]), Number(x[6])]; }

/* 반환: { bars, symbol, forming_included } — bars 는 시작 시각 오름차순, 마지막이 진행 중인 봉일 수 있다 */
async function readOKX(opts) {
  const want = (opts && opts.bars) || 900;   // 일봉 120 평균선(= 4시간봉 약 720개)보다 넉넉히
  const map = new Map();
  let after = null;
  for (let page = 0; page < 20 && map.size < want; page++) {
    const url = BASE + "/api/v5/market/history-candles?instId=" + INST + "&bar=4H&limit=100" + (after ? "&after=" + after : "");
    const d = await getJson(url);
    if (!d.length) break;
    for (const x of d) if (x[8] === "1") map.set(Number(x[0]), toBar(x));   // 마감된 봉만
    after = Math.min(...d.map(x => Number(x[0])));
    await sleep(150);
  }
  // 지금 만들어지는 중인 봉까지 포함한 최신 몇 개
  const recent = await getJson(BASE + "/api/v5/market/candles?instId=" + INST + "&bar=4H&limit=20");
  let forming = null;
  for (const x of recent) {
    const b = toBar(x);
    if (x[8] === "1") map.set(b[0], b);
    else if (!forming || b[0] > forming[0]) forming = b;   // 아직 안 닫힌 봉
  }
  const bars = [...map.values()].sort((a, b) => a[0] - b[0]);
  if (forming) bars.push(forming);
  if (bars.length < 30) throw new J.Stop("OKX에서 받은 봉이 너무 적습니다(" + bars.length + "개).");
  return { bars: J.toBars(bars), symbol: "OKX:BTC-USDT-SWAP", forming_included: !!forming };
}

/* 아무 타임프레임이나 최근 봉을 읽는다(단타 요약표용). bar 예: "5m","15m","30m","1H","4H","1D".
   반환: [[시작ms, 시, 고, 저, 종, 거래량(btc)], ...] 오름차순. 마지막은 진행 중 봉일 수 있다. */
async function readOKXTf(bar, limit) {
  const d = await getJson(BASE + "/api/v5/market/candles?instId=" + INST + "&bar=" + bar + "&limit=" + (limit || 300));
  const rows = d.map(toBar).filter(b => b.every(Number.isFinite)).sort((a, b) => a[0] - b[0]);
  if (rows.length < 5) throw new J.Stop("OKX " + bar + " 봉이 너무 적습니다(" + rows.length + "개).");
  return rows;
}

module.exports = { readOKX, readOKXTf };
