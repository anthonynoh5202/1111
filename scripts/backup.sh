#!/usr/bin/env bash
# 매일 DB 백업 → age 암호화 → (선택) 서버 밖 복사 → 오래된 백업 정리 → (선택) healthchecks 핑.
# docs/RUNBOOK.md §6 참고. 서버의 봇 폴더에서 root cron으로 돌린다(백업 폴더 주인이 봇 사용자 10001이라서).
#   sudo crontab -e  →  10 18 * * * /절대경로/btcbot/scripts/backup.sh >> /var/log/btcbot-backup.log 2>&1
# 비밀 값은 이 파일에 쓰지 않는다. age 받는 사람(공개키)은 비밀이 아니다: config/backup_age_recipient.txt
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."

KEEP_DAYS="${KEEP_DAYS:-30}"                         # 서버 안 암호화 백업 보존 일수(INFRA §8.3: 30일 이상)
RECIPIENT_FILE="config/backup_age_recipient.txt"    # age 공개키(age1...) 한 줄
OFFSITE_REMOTE_FILE="config/backup_rclone_remote"   # (선택) rclone 대상 한 줄(예: offsite:btcbot-backups). 쓰기 전용 자격증명 권장
PING_FILE="secrets/backup_ping_url"                 # (선택) healthchecks 'prod-backup' 체크 핑 URL 파일

stamp="$(date -u +%Y%m%d-%H%M%S)"                 # 초까지 넣어 같은 분에 두 번 돌려도 이름이 겹치지 않게
name="bot-${stamp}.sqlite3"

# 0) 사전 점검 — 평문 백업을 만들기 전에 암호화할 수 있는지부터 확인한다
if [ ! -s "$RECIPIENT_FILE" ]; then
  echo "오류: $RECIPIENT_FILE 이 없다(age 공개키). 백업을 만들지 않고 끝낸다" >&2
  exit 1
fi
if ! command -v age >/dev/null 2>&1; then
  echo "오류: age 명령이 없다(sudo apt install age). 백업을 만들지 않고 끝낸다" >&2
  exit 1
fi

# 백업·암호화 중 어디서 실패해도 평문이 남지 않게
trap 'rm -f "backups/${name}"' EXIT

# 1) 온라인 백업(봇이 돌고 있어도 안전) — 컨테이너 안 /backups = 호스트 ./backups
docker compose run --rm -T bot backup --dest "/backups/${name}"

# 2) age 암호화 후 평문 삭제(공개키만 서버에 둔다 — 개인키는 오프라인 보관)
age -R "$RECIPIENT_FILE" -o "backups/${name}.age" "backups/${name}"
rm -f "backups/${name}"

# 3) (선택) 서버 밖으로 복사(rclone). 명령 문자열을 실행(eval)하지 않고 대상 이름만 읽는다
if [ -s "$OFFSITE_REMOTE_FILE" ]; then
  remote="$(head -n1 "$OFFSITE_REMOTE_FILE")"
  rclone copy "backups/${name}.age" "$remote"
fi

# 4) 보존 기간이 지난 암호화 백업 정리(디스크가 차지 않게)
find backups -maxdepth 1 -name 'bot-*.sqlite3.age' -mtime +"$KEEP_DAYS" -print -delete

# 5) (선택) healthchecks 핑 — URL은 파일에서 읽고 화면에 찍지 않는다
if [ -s "$PING_FILE" ]; then
  curl -fsS -m 10 --retry 3 -o /dev/null "$(head -n1 "$PING_FILE")" || echo "경고: 백업 핑 실패" >&2
fi
echo "백업 완료: backups/${name}.age"
