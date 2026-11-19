/* 봉 자료를 읽어 오는 곳: 바이낸스 선물 공개 시세 API. 키가 필요 없다. */
const J = require("../src/judge.cjs");

const BINANCE = "https://fapi.binance.com";

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

module.exports = { readBinance };
