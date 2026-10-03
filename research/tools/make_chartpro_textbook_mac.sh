#!/bin/bash
# [대표님 맥에서 실행] 차트프로 초급 교재 만들기 — 준비부터 실행까지 한 번에.
#   저장소 폴더에서:  bash research/tools/make_chartpro_textbook_mac.sh
#   유튜브가 로그인을 요구하면:  bash research/tools/make_chartpro_textbook_mac.sh --browser chrome
#   영상 첫 8초 안에서 찍힌 옛 캡처를 다시 찍으려면:  ... --recapture
# 결과: ~/Documents/차트프로_교재/ 안의 차트프로_초급_교재.pdf · .docx (저장소 밖, 개인 학습용)
#       끝나면 PDF가 자동으로 열린다(--out 으로 폴더를 바꿔도 그 폴더의 PDF가 열린다).
# 다시 실행하면 이미 있는 캡처는 건너뛴다. 보통은 git pull 후 같은 명령을 다시 실행하면 된다.
set -e
cd "$(dirname "$0")/../.."

PY=""
for c in python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 \
         /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 /opt/homebrew/bin/python3 "$HOME"/.local/bin/python3.1[0-9] python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "파이썬 3.10 이상이 필요합니다. https://www.python.org/downloads/macos/ 에서 최신 버전을 설치한 뒤 다시 실행하세요."
  exit 1
fi

VENV="$HOME/.chartpro_textbook_venv"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
echo "도구 설치·업데이트 중 (처음엔 몇 분 걸려요)..."
"$VENV/bin/python" -m pip install -q -U pip
"$VENV/bin/python" -m pip install -q -U "yt-dlp[default]" imageio-ffmpeg python-docx playwright pymupdf
"$VENV/bin/python" -m pip install -q -U deno || echo "(deno 설치 실패 — 그래도 계속 진행)"

# PDF를 만들 브라우저: 구글 크롬이 있으면 그것을 쓰고, 없으면 Playwright용 크로미움을 한 번 받아 둔다.
if [ ! -d "/Applications/Google Chrome.app" ]; then
  "$VENV/bin/python" -m playwright install chromium || echo "(PDF용 브라우저 설치 실패 — PDF 없이 HTML·워드만 만듭니다)"
fi

PATH="$VENV/bin:$PATH" "$VENV/bin/python" research/tools/build_chartpro_textbook.py --open "$@"
