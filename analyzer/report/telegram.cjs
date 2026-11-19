/* 텔레그램 봇으로 글/파일을 보낸다. 봇 토큰은 secrets.json 에서 받는다(저장소에 커밋하지 않음).
   토큰은 주소에 들어가므로, 오류 글·기록에 주소를 절대 싣지 않는다. */
const fs = require("fs"), path = require("path");

const TOKEN_RE = /^\d{6,12}:[A-Za-z0-9_-]{30,50}$/, CHAT_RE = /^-?\d{1,20}$|^@[A-Za-z0-9_]{4,64}$/;
function check(token, chatId) {
  if (typeof token !== "string" || !TOKEN_RE.test(token)) throw new Error("텔레그램 토큰 모양이 아닙니다. secrets.json 의 telegram_token 을 확인하세요.");
  if (!CHAT_RE.test(String(chatId))) throw new Error("텔레그램 chat_id 모양이 아닙니다. secrets.json 의 chat_id 를 확인하세요.");
}
const scrub = (text, token) => String(text || "").split(token).join("(토큰)").slice(0, 200);

async function call(token, method, init, what) {
  let r, j;
  try { r = await fetch("https://api.telegram.org/bot" + token + "/" + method, { ...init, redirect: "error" }); }
  catch (e) { throw new Error("텔레그램 " + what + " 실패: 연결하지 못했습니다(" + (e.name || "오류") + ")."); }   // e.message 는 싣지 않는다
  try { j = await r.json(); } catch (e) { throw new Error("텔레그램 " + what + " 실패: 응답을 읽지 못했습니다(" + r.status + ")."); }
  if (!j.ok) throw new Error("텔레그램 " + what + " 실패: " + scrub(j.description || r.status, token));
  return j.result;
}

async function sendMessage(token, chatId, text) {
  check(token, chatId);
  return call(token, "sendMessage", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: String(chatId), text, disable_web_page_preview: true }),
    signal: AbortSignal.timeout(30000)
  }, "sendMessage");
}

async function sendDocument(token, chatId, filePath, caption) {
  check(token, chatId);
  const form = new FormData();
  form.append("chat_id", String(chatId));
  if (caption) form.append("caption", String(caption).slice(0, 1000));
  const buf = fs.readFileSync(filePath);
  form.append("document", new Blob([buf], { type: "application/pdf" }), path.basename(filePath));
  return call(token, "sendDocument", { method: "POST", body: form, signal: AbortSignal.timeout(60000) }, "sendDocument");
}

module.exports = { sendMessage, sendDocument };
