#!/bin/bash
# [대표님 맥에서 실행] 차트프로 교재(1권 초급·2권 중급·3권 실전·4권 해외선물) 만들기 — 준비부터 실행까지 한 번에.
#   저장소 폴더에서:  bash research/tools/make_chartpro_textbook_mac.sh
#   유튜브가 로그인을 요구하면:  bash research/tools/make_chartpro_textbook_mac.sh --browser chrome
#   한 권만 만들려면:  ... --volume 2   (1 초급, 2 중급, 3 실전, 4 해외선물, 기본은 전부)
#   영상 첫 8초 안에서 찍힌 옛 캡처를 다시 찍으려면:  ... --recapture
# 결과: ~/Documents/차트프로_교재/ 안의 차트프로_1권_초급.pdf · .docx 등 권별 파일 (저장소 밖, 개인 학습용)
#       끝나면 결과 폴더(한 권만 만들면 그 PDF)가 열린다.
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
"$VENV/bin/python" -m pip install -q -U "yt-dlp[default]" imageio-ffmpeg python-docx playwright pymupdf fonttools
"$VENV/bin/python" -m pip install -q -U deno || echo "(deno 설치 실패 — 그래도 계속 진행)"

# 책 글꼴(모두 무료 OFL 글꼴): 본명조(Noto Serif KR), 프리텐다드, Instrument Serif, DM Mono
FONTS="$HOME/.chartpro_textbook_fonts"
mkdir -p "$FONTS"
fetch() {
  [ -s "$FONTS/$1" ] && return 0
  if curl -fsSL --retry 2 -o "$FONTS/$1.part" "$2"; then
    mv -f "$FONTS/$1.part" "$FONTS/$1"
  else
    rm -f "$FONTS/$1.part"
    echo "(글꼴 $1 받기 실패 — 기본 글꼴로 계속)"
  fi
}
echo "책 글꼴 확인 중 (처음엔 약 40MB를 받아요)..."
GF=https://raw.githubusercontent.com/google/fonts/main/ofl
PT=https://raw.githubusercontent.com/orioncactus/pretendard/main/packages/pretendard/dist/public/static/alternative
fetch NotoSerifKR-VF.ttf "$GF/notoserifkr/NotoSerifKR%5Bwght%5D.ttf"
for w in Light Regular SemiBold Bold; do fetch "Pretendard-$w.ttf" "$PT/Pretendard-$w.ttf"; done
fetch InstrumentSerif-Regular.ttf "$GF/instrumentserif/InstrumentSerif-Regular.ttf"
fetch DMMono-Regular.ttf "$GF/dmmono/DMMono-Regular.ttf"

# PDF를 만들 브라우저: 구글 크롬이 있으면 그것을 쓰고, 없으면 Playwright용 크로미움을 한 번 받아 둔다.
if [ ! -d "/Applications/Google Chrome.app" ]; then
  "$VENV/bin/python" -m playwright install chromium || echo "(PDF용 브라우저 설치 실패 — PDF 없이 HTML·워드만 만듭니다)"
fi

PATH="$VENV/bin:$PATH" "$VENV/bin/python" research/tools/build_chartpro_textbook.py --open "$@"

# 워드에서도 같은 글꼴이 보이도록 내 계정 글꼴 폴더에 복사(관리자 권한 필요 없음, 이미 있으면 건너뜀)
mkdir -p "$HOME/Library/Fonts"
for f in "$FONTS"/NotoSerifKR-Regular.ttf "$FONTS"/NotoSerifKR-SemiBold.ttf "$FONTS"/NotoSerifKR-Bold.ttf "$FONTS"/Pretendard-*.ttf; do
  [ -f "$f" ] && [ ! -f "$HOME/Library/Fonts/$(basename "$f")" ] && cp "$f" "$HOME/Library/Fonts/" || true
done
