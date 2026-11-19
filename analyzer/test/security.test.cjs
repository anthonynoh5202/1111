/* 실행: node --test analyzer/test/security.test.cjs
   저장소가 공개라서, 비밀 값이 올라갔는지와 보안 장치가 살아 있는지를 시험으로 지킨다. */
const test = require("node:test"), assert = require("node:assert"), fs = require("fs"), path = require("path"), cp = require("child_process");
const ROOT = path.join(__dirname, "../..");
const git = args => cp.spawnSync("git", args, { cwd: ROOT, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
const tracked = (() => { const r = git(["ls-files", "-z"]); return r.status === 0 ? r.stdout.split("\0").filter(Boolean) : null; })();

const SECRET_PATTERNS = [
  ["텔레그램 봇 토큰", /\b\d{8,10}:[A-Za-z0-9_-]{35}\b/],
  ["Anthropic API 키", /sk-ant-[A-Za-z0-9_-]{20,}/],
  ["개인 키", /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ["GitHub 토큰", /\b(ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b/],
  ["AWS 키", /\bAKIA[0-9A-Z]{16}\b/],
  ["Slack 토큰", /\bxox[baprs]-[A-Za-z0-9-]{10,}/],
];

test("올라간 파일에 비밀 값 모양이 없다", { skip: !tracked && "git 저장소가 아님" }, () => {
  const hits = [];
  for (const f of tracked) {
    if (/\.(ttf|png|jpg|gz|zip|pdf)$/i.test(f) || /package-lock\.json$/.test(f) || f === "analyzer/test/security.test.cjs") continue;
    const full = path.join(ROOT, f); if (!fs.existsSync(full) || fs.statSync(full).size > 3 * 1024 * 1024) continue;
    const text = fs.readFileSync(full, "utf8");
    for (const [name, re] of SECRET_PATTERNS) if (re.test(text)) hits.push(f + " (" + name + ")");
  }
  assert.deepStrictEqual(hits, []);
});

test("비밀·개인 설정 파일은 올라가 있지 않고, 올리려 해도 무시된다", { skip: !tracked && "git 저장소가 아님" }, () => {
  const bad = tracked.filter(f => /(^|\/)(secrets(\..*)?\.json|\.env(\..*)?|config\.json)$/.test(f) || /\.(pem|key)$/.test(f));
  assert.deepStrictEqual(bad, []);
  for (const f of ["analyzer/report/secrets.json", "analyzer/platform/config.json", ".env", "analyzer/platform/data/runs.jsonl"])
    assert.strictEqual(git(["check-ignore", "-q", f]).status, 0, f + " 가 .gitignore 에 없다");
});

test("화면에 넣는 자료는 스크립트를 빠져나오지 못하고, 단독 화면은 접속할 곳이 제한된다", () => {
  const { buildPage } = require("../build.cjs");
  const html = buildPage({ embed: { bars: [], now: 0, symbol: "</script><script>alert(1)</script>" } });
  assert.ok(!html.includes("</script><script>alert(1)"));
  const csp = (html.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/) || [])[1];
  assert.match(csp, /default-src 'none'/); assert.match(csp, /connect-src https:\/\/fapi\.binance\.com(;|$)/);
});

test("텔레그램: 토큰 모양이 아니면 보내지 않고, 오류 글에 토큰이 섞이지 않는다", async () => {
  const tg = require("../report/telegram.cjs");
  await assert.rejects(tg.sendMessage("not-a-token", "123", "x"), /토큰 모양/);
  await assert.rejects(tg.sendMessage("123456789:" + "A".repeat(35), "채팅방", "x"), /chat_id 모양/);
  const token = "123456789:" + "A".repeat(35), real = global.fetch;
  try {
    global.fetch = async () => { throw new TypeError("fetch failed https://api.telegram.org/bot" + token + "/sendMessage"); };
    await assert.rejects(tg.sendMessage(token, "123", "x"), e => !e.message.includes(token));
    global.fetch = async () => ({ status: 401, json: async () => ({ ok: false, description: "Unauthorized for bot" + token }) });
    await assert.rejects(tg.sendMessage(token, "123", "x"), e => !e.message.includes(token) && /Unauthorized/.test(e.message));
  } finally { global.fetch = real; }
});

