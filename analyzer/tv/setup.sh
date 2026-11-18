#!/bin/bash
# 트레이딩뷰 연결 도구(tradingview-mcp)를 이 저장소의 vendor/ 폴더에 받는다.
# - 우리가 읽어 본 판(커밋)으로 고정해서 받는다. 최신판을 자동으로 따라가지 않는다.
# - 설치 중 스크립트 실행을 끈다(--ignore-scripts).
# 쓰는 법(저장소 폴더에서):  bash analyzer/tv/setup.sh
set -euo pipefail
REPO="https://github.com/tradesdontlie/tradingview-mcp"
PIN="c05b8f5755ed8e64ea242de88ddbf46aa24d56a4"   # 2026-07-28 판. 2026-11-18에 읽어 봄
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$ROOT/vendor/tradingview-mcp"

command -v node >/dev/null || { echo "Node.js가 없습니다. https://nodejs.org 에서 18 이상을 설치한 뒤 다시 실행하세요."; exit 1; }
command -v git  >/dev/null || { echo "git이 없습니다."; exit 1; }
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 18 ] || { echo "Node.js $NODE_MAJOR 입니다. 18 이상이 필요합니다."; exit 1; }

if [ ! -d "$DEST/.git" ]; then
  mkdir -p "$ROOT/vendor"
  git clone --quiet "$REPO" "$DEST"
fi
git -C "$DEST" fetch --quiet origin
git -C "$DEST" checkout --quiet --detach "$PIN"
[ "$(git -C "$DEST" rev-parse HEAD)" = "$PIN" ] || { echo "고정한 판을 받지 못했습니다."; exit 1; }
(cd "$DEST" && npm ci --ignore-scripts --no-audit --no-fund --omit=dev --silent)

(cd "$ROOT/analyzer/platform" && npm ci --ignore-scripts --no-audit --no-fund --omit=dev --silent)

echo "받았습니다: vendor/tradingview-mcp (판 ${PIN:0:7}), 자동 분석 플랫폼의 부품"
echo "다음: 1) 트레이딩뷰 데스크톱을 디버그 모드로 실행   bash vendor/tradingview-mcp/scripts/launch_tv_debug_mac.sh"
echo "      2) 자동 분석 켜기   node analyzer/platform/server.cjs   (안내: analyzer/platform/README.md)"
echo "         또는 이 폴더에서 claude 를 실행하고  '차트 분석해줘' 라고 말하기"
