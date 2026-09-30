# 운영 설명서 (RUNBOOK) — BTC 추세추종 모의 운영(PAPER) 봇

> 대상: 서버 작업이 익숙하지 않은 사람. 명령은 **그대로 복사해서** 붙여 넣으면 된다.
> 이 봇은 **모의 운영 전용**이다. 거래소 API 키도, 주문 코드도 없다. 실제 돈은 움직이지 않는다.
> 설계 기준: [bot/DESIGN.md](../bot/DESIGN.md), 보안: [SECURITY.md](./SECURITY.md), 서버: [INFRA.md](./INFRA.md).

---

## 0. 한눈에 보기

| 하고 싶은 일 | 명령 (서버의 봇 폴더에서) |
|---|---|
| 시작 | `docker compose up -d --build` |
| 상태 보기 | `docker compose ps` (STATUS가 `(healthy)`여야 정상) / 텔레그램 `/status` |
| 로그 보기 | `docker compose logs --tail 200 -f bot` |
| **긴급 정지(신규 진입만 막기)** | 텔레그램 `/pause` |
| **완전 정지(봇 끄기)** | `docker compose stop bot` |
| 다시 켜기 | `docker compose start bot` (신규 진입 재개는 텔레그램 `/resume`) |
| 백업(수동) | `docker compose run --rm bot backup --dest /backups/bot-$(date -u +%Y%m%d).sqlite3` (자동 백업은 §6) |
| 설정 점검 | `docker compose run --rm bot check` |

봇이 하는 일 (매일):
1. **09:01 KST**(00:01 UTC): 어제 일봉이 마감되면 20·55·100일 돌파 신호를 계산한다(백테스트와 같은 코드).
2. 신호가 있으면 텔레그램에 카드를 보낸다: **[승인] [패스] [상세]**. Claude 분석은 참고 의견일 뿐이다.
3. [승인]을 누르면 **60초 안에 [확인]**을 한 번 더 눌러야 한다. 승인 마감은 **11:01 KST**(2시간).
4. 확인하면 그 뒤 첫 1분봉 시가로 **모의 체결**한다. 보호 손절(2×ATR20)·추세 청산은 **자동**이다.
5. 매일 사이클 뒤 일일 리포트가 온다.

---

## 1. 처음 설치 (한 번만)

### 1-1. 준비물
- 리눅스 서버 한 대(INFRA §2 권고), Docker Engine + Docker Compose 설치됨 (`docker version`, `docker compose version`으로 확인)
- 텔레그램 봇 토큰(BotFather에서 발급), Anthropic API 키(Claude)

### 1-2. 코드 받기
```bash
git clone <저장소 주소> btcbot
cd btcbot
```

### 1-3. 베이스 이미지 고정 (이미 되어 있음, INFRA H17)
`Dockerfile`의 `FROM python:3.11-slim@sha256:...`은 digest로 고정돼 있다(같은 태그가 다른 이미지로 바뀌어도 영향 없음).
보안 업데이트를 받으려면 개발 PC에서 `docker buildx imagetools inspect python:3.11-slim`의 `Digest` 값으로 바꾸고
테스트를 돌린 뒤 커밋한다(서버에서 직접 고치지 않는다).

### 1-4. 백업 폴더 만들기
```bash
mkdir -p backups && sudo chown 10001:10001 backups && sudo chmod 700 backups
```
(백업은 DB 볼륨이 아니라 이 호스트 폴더에 쌓인다. `docker compose down -v`로 볼륨이 지워져도 백업은 남는다.)

---

## 2. 비밀 파일과 설정 만들기

### 2-1. 원칙 (꼭 지킬 것)
- 비밀(토큰·키·핑 URL)은 **파일로만** 넘긴다. 환경 변수·설정 파일·채팅·메모장에 붙여 넣지 않는다.
- 환경 변수에 `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN` 같은 이름이 있으면 봇이 **시작을 거부**한다(일부러 그렇게 만듦).
- `secrets/` 폴더와 `config/bot.toml`은 git에 올라가지 않는다(`.gitignore`).

### 2-2. 비밀 파일 만들기
화면에 값이 남지 않도록 `read -s`로 입력한다(입력해도 글자가 보이지 않는 것이 정상).
```bash
mkdir -p secrets && chmod 700 secrets
read -rs TG && printf '%s' "$TG" > secrets/telegram_bot_token && unset TG
read -rs AK && printf '%s' "$AK" > secrets/anthropic_api_key && unset AK
sudo chown 10001:10001 secrets/telegram_bot_token secrets/anthropic_api_key
sudo chmod 400 secrets/telegram_bot_token secrets/anthropic_api_key
```
(`10001`은 컨테이너 안 봇 사용자 번호다. 봇만 읽을 수 있게 한다. **권한은 400(또는 600)이어야 한다** —
그룹·다른 사용자 권한이 조금이라도 있으면 봇이 `비밀 파일 권한이 너무 넓다`며 시작을 거부한다.)
텔레그램 토큰 파일에는 `숫자:문자열` 모양의 봇 토큰만 넣는다. 다른 파일(예: Anthropic 키)을 잘못 넣으면
텔레그램에 보내기 전에 모양 검사로 거부한다(값은 출력하지 않는다).

### 2-2b. 헬스체크(데드맨 스위치) 켜기 — **설치 단계로 꼭 한다**
봇이 죽거나 텔레그램이 끊기면 텔레그램으로는 알릴 수 없다. 그래서 바깥 서비스(healthchecks.io)가 대신 알린다.
1. healthchecks.io에서 체크 하나를 만든다(이름 `paper-bot`, **주기 5분 · 유예 10분**). 알림은 이메일(+ healthchecks 자체 텔레그램 연동)로.
2. 핑 URL을 같은 방법으로 파일에 넣는다:
   `read -rs HC && printf '%s' "$HC" > secrets/healthcheck_ping_url && unset HC` → `sudo chown 10001:10001` · `sudo chmod 400`
3. `docker-compose.yml`의 `healthcheck_ping_url` 주석 두 곳을 풀고, `config/bot.toml`에 `[health] ping_url_file = "/run/secrets/healthcheck_ping_url"`.

봇은 5분마다 핑을 보내되, **1분 감시(tick)가 성공하고 텔레그램이 살아 있을 때만** 보낸다(마지막 텔레그램 성공이
15분 넘게 없으면 핑을 멈춘다). 토큰 폐기·봇 차단·텔레그램 장애도 healthchecks 경보로 알 수 있다.
(INFRA §7.2의 `prod-analysis` 60분 주기보다 촘촘한 값이다 — 모의 봇은 1분 감시의 생존을 본다.)

### 2-3. 설정 파일 만들기
```bash
cp config/bot.example.toml config/bot.toml
nano config/bot.toml
```
채울 것은 **숫자 두 개**뿐이다.
- `allowed_user_id`: 내 텔레그램 사용자 ID. 텔레그램에서 `@userinfobot`에 아무 말이나 보내면 알려 준다.
- `allowed_chat_id`: 봇과의 **개인 채팅** ID. 개인 채팅이면 보통 사용자 ID와 같다. 그룹 채팅은 거부된다.

따옴표 없이 숫자만 쓴다. 모르는 키나 오타가 있으면 봇이 시작을 거부하고 이유를 알려 준다.

### 2-4. 점검
```bash
docker compose build
docker compose run --rm bot check
```
`점검 통과`가 나오면 된다. 토큰·키 값은 어디에도 출력되지 않는다(“있음/없음”만).
`run --dry-run`으로 네트워크 없이 구성까지 확인할 수 있다: `docker compose run --rm bot run --dry-run`

---

## 3. 시작 · 중지

### 시작
```bash
docker compose up -d --build
docker compose logs --tail 50 bot
```
텔레그램에 `[PAPER] 시작 v0.1.0-paper · 설정 지문 xxxxxxxx`가 오면 정상이다. 텔레그램에서 `/status`를 보내 본다.

### 중지 / 다시 켜기
```bash
docker compose stop bot      # 끄기(진행 중인 일일 사이클은 끝내고 멈춤, 최대 약 2분)
docker compose start bot     # 다시 켜기
```
꺼져 있던 동안의 일(만료, 모의 체결, 손절, 추세 청산)은 켜진 뒤 **자동으로 따라잡는다**(모든 상태가 DB에 있다).
- 판단 시각(09:01 KST)에서 2시간이 지난 뒤 켜지면 그날 신호는 `late_start`로 건너뛴다(오래된 신호로 진입하지 않음).
  어느 신호가 왜 건너뛰어졌는지 텔레그램 알림이 온다.
- 하루 이상 꺼져 있었으면(최대 30일) 놓친 날의 **추세 청산 신호를 다시 계산**해 열린 모의 포지션을 청산한다.
  놓친 날의 진입 신호는 `missed_cycle`로 건너뛴다(알림). 청산이 백테스트보다 늦어진 경우 감사 로그에 `exit_plan_late`로 남는다.
- 시작할 때 바이낸스 시계 확인이나 텔레그램 접속이 실패해도 봇은 **죽지 않는다**. 모의 손절·청산 감시는 계속 돌고,
  텔레그램은 뒤에서 다시 접속한다(5초 → 최대 5분 간격). 그동안 못 보낸 체결·청산·경고 메시지는 DB에 보관했다가
  복구되면 `(지연 전송 · 원래 …)` 표시와 함께 보낸다.

### 설정 바꾸기
텔레그램으로는 설정을 바꿀 수 **없다**(일부러 막음). 서버에서 `config/bot.toml`을 고치고 `docker compose restart bot`.

---

## 4. 긴급 정지

| 상황 | 할 일 | 효과 |
|---|---|---|
| 새 진입을 당장 막고 싶다 | 텔레그램 `/pause` | 승인 대기·체결 대기 신호 전부 건너뜀. **열린 모의 포지션의 손절·추세 청산은 계속** 돈다 |
| 봇 자체를 멈추고 싶다 | `docker compose stop bot` | 전부 멈춤. 다시 켜면 따라잡음 |
| 텔레그램 토큰이 샜을 수 있다 | ① `docker compose stop bot` ② BotFather에서 `/revoke`로 토큰 폐기·재발급 ③ 2-2 방법으로 파일 교체 ④ `docker compose up -d` | 옛 토큰 무효 |
| Anthropic 키가 샜을 수 있다 | ① Anthropic 콘솔에서 키 폐기 ② 새 키로 파일 교체 ③ `docker compose restart bot` | Claude 분석이 없어도 신호 카드는 나간다 |
| 다시 신규 진입 받기 | 텔레그램 `/resume` | 다음 판단부터 새 신호. 건너뛴 신호는 되살리지 않음 |

- 모르는 사람이 봇에 말을 걸거나 버튼을 눌러도 봇은 **대답하지 않고** 감사 로그에 남긴다. 대신 **내 채팅으로 경고**가 온다
  (10분에 한 번, 그 사이 시도 수를 합쳐서). 반복되면 봇 사용자명이 알려진 것이다 — 위 '토큰이 샜을 수 있다'를 따른다.
- 봇은 5분마다 텔레그램 웹훅 설정을 점검한다. 누가 토큰으로 웹훅을 걸면(메시지 가로채기) 지우고 경고를 보낸다 →
  **토큰이 샌 것**이므로 위 절차로 토큰을 바꾼다.
- `/resume`이 텔레그램에서 되는 것은 PAPER 단계의 예외다(SECURITY PV-15는 '해제는 서버에서'). TESTNET/LIVE 전에 서버 쪽 해제로 바꾼다.

---

## 5. 로그 보기

```bash
docker compose logs --tail 200 bot          # 최근 200줄
docker compose logs -f bot                  # 실시간(끝내려면 Ctrl+C)
docker compose logs --since 24h bot | grep -E "WARNING|ERROR"
```
- 로그 파일은 10MB × 5개까지만 보관한다(자동 교체).
- 토큰·키 모양 문자열은 로그에서 자동으로 `***`로 가려진다.
- 모든 상태 변화·버튼·명령은 DB의 **감사 로그(audit_log)**에 남는다(수정·삭제 불가).

---

## 6. 백업 · 복원

### 자동 백업 (설치 때 한 번 설정, INFRA §8.3)
`scripts/backup.sh`가 하는 일: 온라인 백업(봇이 돌고 있어도 안전) → **age 공개키 암호화** → 평문 삭제 →
(선택) 서버 밖 복사(rclone) → **30일 지난 백업 정리** → (선택) healthchecks 핑.

1. age 설치: `sudo apt install age`. 개발 PC(서버 아님)에서 `age-keygen -o backup_key.txt` →
   **개인키 파일은 오프라인 비밀번호 관리자에 보관**하고 서버에 두지 않는다. 출력의 `Public key: age1...`만 서버의
   `config/backup_age_recipient.txt`에 한 줄로 적는다(공개키는 비밀이 아니다).
2. (선택) 서버 밖 저장소: `rclone config`로 대상을 만들고(쓰기 전용 자격증명 권장), 대상 이름을
   `config/backup_rclone_remote`에 한 줄로 적는다(예: `offsite:btcbot-backups`).
3. (선택) healthchecks에 `prod-backup` 체크(주기 1일 · 유예 2시간)를 만들고 URL을 `secrets/backup_ping_url`(chmod 400)에.
4. root cron에 등록(매일 03:10 KST = 18:10 UTC, 봉 마감 시각을 피함):
```bash
sudo crontab -e
# 아래 한 줄 추가 (경로는 실제 봇 폴더로)
10 18 * * * /home/ubuntu/btcbot/scripts/backup.sh >> /var/log/btcbot-backup.log 2>&1
```
5. 한 번 손으로 돌려 확인: `sudo ./scripts/backup.sh` → `backups/bot-YYYYMMDD-HHMMSS.sqlite3.age`가 생기면 된다.

수동 백업(암호화 없이, 급할 때):
```bash
docker compose run --rm bot backup --dest /backups/bot-$(date -u +%Y%m%d).sqlite3
```
- 같은 이름이 이미 있으면 덮어쓰지 않고 거부한다. 백업 파일 권한은 0600.
- 디스크 여유가 1GB 밑으로 떨어지면 일일 사이클 뒤 텔레그램 경고가 온다. 오래된 백업부터 지운다.

### 복원 (순서 그대로)
```bash
# 0) 개발 PC에서 복호화: age -d -i backup_key.txt -o bot-YYYYMMDD.sqlite3 bot-YYYYMMDD-HHMMSS.sqlite3.age
#    → 서버의 ./backups/ 로 옮긴다
docker compose stop bot
# 1) 남은 WAL·SHM 파일 삭제(봇이 멈춘 상태에서만! 복원한 DB에 옛 WAL이 섞이면 망가질 수 있다)
docker compose run --rm --no-deps --entrypoint sh bot -c 'rm -f /data/bot.sqlite3-wal /data/bot.sqlite3-shm'
# 2) 백업 파일을 운영 DB 자리로 복사(주인 10001·권한 600 유지)
sudo chown 10001:10001 ./backups/bot-YYYYMMDD.sqlite3 && sudo chmod 600 ./backups/bot-YYYYMMDD.sqlite3
docker compose run --rm --no-deps --entrypoint sh bot -c 'cp -p /backups/bot-YYYYMMDD.sqlite3 /data/bot.sqlite3'
# 3) 먼저 점검, 통과하면 시작
docker compose run --rm bot check
docker compose start bot
```
- DB 파일 권한이 600이 아니면(그룹·다른 사용자 권한) 봇이 `DB 파일 권한이 너무 넓다`며 거부한다(코드 3).
- 재생(replay) DB를 운영 경로에 넣으면 봇이 “모드가 다르다”며 거부한다(종료 코드 3).

### 감사 로그 변조 경고
시작할 때 `감사 로그 보호 트리거가 없다` 또는 `감사 로그 행 수가 마지막 번호와 다르다`(코드 3)가 나오면,
누군가 DB 파일을 직접 고친 흔적이다. **봇을 켜지 말고** 서버 접속 기록을 확인한 뒤, 믿을 수 있는 백업으로 복원한다(위 절차).

---

## 7. 과거 재생(replay) — 봇이 백테스트와 같은지 확인

과거 데이터를 하루씩 흘려보내며 봇 전체(신호 → 카드 → 자동 승인 → 모의 체결·청산)를 돌린다.
텔레그램·Claude·인터넷을 쓰지 않는다(비밀 파일도 읽지 않음).
```bash
cp config/replay.example.toml config/replay.toml
docker compose --profile replay run --rm replay
```
로컬(개발 PC)에서는:
```bash
.venv/bin/python -m bot.main --config config/replay.local.toml replay --trades-csv /tmp/replay_positions.csv
```
(`replay.local.toml`은 replay 견본에서 `db_path`와 `data_dir = "data/binance"`만 바꾼 것)

- 모든 신호를 판단 + 30분에 자동 승인한다 → 백테스트(G1-T, L=30분)와 같은 조건.
- 2020-01-01 ~ 2026-09-28 전체 재생 결과는 `backtest/results_trend/trades/E0-L-ENS.csv`와 거래 100건이 **진입·청산 시각, 사유, R까지 일치**한다(`bot/tests/test_parity.py`).
- 2023-10 이전은 1분봉 파일이 없어 백테스트와 같은 5분봉을 체결 봉으로 쓴다(`--exec-bars backtest`, 기본값).

---

## 8. 자주 보는 문제

| 증상 | 원인·해결 |
|---|---|
| `비밀로 보이는 환경 변수가 있어 시작하지 않는다` | 서버나 compose에 비밀 이름 환경 변수가 있다. 지우고 파일로만 넘긴다 |
| `비밀 파일이 없다` / `읽을 권한이 없다` | 2-2 다시. `sudo chown 10001:10001 secrets/*` 확인 |
| `telegram.allowed_user_id는 양의 정수` | `config/bot.toml`의 숫자 ID를 채우지 않았다 |
| `이 DB는 replay 모드용이다` (코드 3) | 재생 DB를 운영 경로에 넣었다. 운영 DB로 되돌린다 |
| 카드에 `Claude 분석 없음` | Claude 호출 실패·시간 초과(120초). 신호는 정상이며 사람이 판단하면 된다 |
| `시계 오차 초과 — 사이클 보류` | 서버 시계가 1초 넘게 틀림. `timedatectl`로 NTP 동기화 확인. 다음 주기에 자동 재시도 |
| 버튼을 눌렀는데 “이미 처리됨/만료됨” | 두 번 눌렀거나 승인 마감(11:01 KST)이 지났다. 정상 동작 |
| `시작 시 바이낸스 시계·시세 확인 실패` 경고 | 바이낸스 접속 문제(점검·차단 451/418·네트워크) 또는 서버 시계 오차. 봇은 계속 돌며 사이클은 보류·재시도(경고는 그날 한 번). 오래가면 `curl -sI https://fapi.binance.com/fapi/v1/time`, `timedatectl` 확인 |
| 로그 `텔레그램 시작 실패(NetworkError) — N초 뒤 재시도` | 텔레그램 일시 장애. 자동 재시도, 감시는 계속. 메시지는 복구 뒤 `(지연 전송)`으로 온다 |
| 로그 `텔레그램이 봇 토큰을 거부했다(InvalidToken)`, 종료 코드 2 | 토큰이 틀렸거나 폐기됐다. BotFather에서 확인하고 2-2로 파일 교체 |
| `텔레그램 토큰 파일 내용이 봇 토큰 모양이 아니다` | 토큰 파일에 다른 값(예: Anthropic 키)을 넣었다. 파일을 바로잡는다 |
| `비밀 파일 권한이 너무 넓다` / `DB 파일 권한이 너무 넓다` | `sudo chmod 400 secrets/*` / DB는 복원 절차의 권한 명령 |
| `docker compose ps`가 `(unhealthy)` | 스케줄 루프가 5분 넘게 멈췄다. `docker compose logs --tail 200 bot` 확인 후 `docker compose restart bot` |
| 로그 `텔레그램 응답 없음 — 헬스체크 핑을 멈춘다` | 15분 넘게 텔레그램 전송·점검이 모두 실패. 토큰 폐기·봇 차단·채팅 삭제 여부 확인 |
| `거래소 1분봉 빈 구간` 경고 | 바이낸스 점검 등으로 봉이 비었다. 다음 봉으로 체결·감시를 계속한다(백테스트와 같은 규칙). 조치 불필요 |
| `처리되지 않은 오류로 종료(…)`, 종료 코드 1 | 예상 못한 오류. 로그의 앞뒤 줄을 보관하고 재시작. 값(토큰 등)은 가려져 있다 |

## 9. 종료 코드
`0` 정상 · `1` 그 밖의 오류 · `2` 설정·비밀 오류(텔레그램 토큰 거부 포함) · `3` DB 오류(모드 불일치·권한·감사 로그 변조)
