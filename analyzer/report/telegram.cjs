/* 텔레그램 봇으로 글/파일을 보낸다. 봇 토큰은 secrets.json 에서 받는다(저장소에 커밋하지 않음). */
const fs = require("fs"), path = require("path");

async function sendMessage(token, chatId, text) {
  const r = await fetch("https://api.telegram.org/bot" + token + "/sendMessage", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: String(chatId), text, disable_web_page_preview: true }),
    signal: AbortSignal.timeout(30000)
  });
  const j = await r.json();
  if (!j.ok) throw new Error("텔레그램 sendMessage 실패: " + (j.description || r.status));
  return j.result;
}

async function sendDocument(token, chatId, filePath, caption) {
  const form = new FormData();
  form.append("chat_id", String(chatId));
  if (caption) form.append("caption", caption);
  const buf = fs.readFileSync(filePath);
  form.append("document", new Blob([buf], { type: "application/pdf" }), path.basename(filePath));
  const r = await fetch("https://api.telegram.org/bot" + token + "/sendDocument", { method: "POST", body: form, signal: AbortSignal.timeout(60000) });
  const j = await r.json();
  if (!j.ok) throw new Error("텔레그램 sendDocument 실패: " + (j.description || r.status));
  return j.result;
}

module.exports = { sendMessage, sendDocument };
