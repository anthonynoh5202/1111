#!/usr/bin/env node
/* 분석기 화면을 한 파일로 묶는다.
   node analyzer/build.cjs          → analyzer/index.html (실시간을 못 읽으면 저장 자료를 보여 주는 기본 화면)
   다른 코드에서는 buildPage({embed})로 플랫폼이 읽은 봉을 넣은 화면을 만든다. */
const fs = require("fs"), path = require("path");
const SRC = path.join(__dirname, "src");

// 이 화면이 접속할 수 있는 곳을 글꼴과 바이낸스 공개 시세로 제한한다
const CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src https://fapi.binance.com; img-src data:; base-uri 'none'; form-action 'none'";

function buildPage({ embed = null, standalone = true } = {}) {
  const page = fs.readFileSync(path.join(SRC, "page.html"), "utf8");
  const core = fs.readFileSync(path.join(SRC, "core.js"), "utf8");
  const snap = fs.readFileSync(path.join(SRC, "snapshot.json"), "utf8").trim();
  const sub = (s, mark, text) => {
    if (s.split(mark).length !== 2) throw new Error("자리 표시 " + mark + " 가 한 번만 있어야 합니다");
    return s.replace(mark, () => text);
  };
  let out = sub(page, "/*CORE*/", core);
  out = sub(out, "/*SNAPSHOT*/[]", embed ? "[]" : snap);
  out = sub(out, "/*EMBED*/null", embed ? JSON.stringify(embed).replace(/</g, "\\u003c") : "null");
  if (!standalone) return out;
  return '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n<meta http-equiv="Content-Security-Policy" content="' + CSP + '">\n</head>\n<body>\n' + out + "\n</body>\n</html>\n";
}

module.exports = { buildPage };

if (require.main === module) {
  fs.writeFileSync(path.join(__dirname, "index.html"), buildPage());
  const frag = process.argv[2];
  if (frag) fs.writeFileSync(frag, buildPage({ standalone: false }));
  console.log("만들었습니다: analyzer/index.html" + (frag ? ", " + frag : ""));
}
