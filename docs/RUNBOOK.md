# 운영 설명서 (RUNBOOK) — BTC 추세추종 모의 운영(PAPER) 봇

> 대상: 서버 작업이 익숙하지 않은 사람. 명령은 **그대로 복사해서** 붙여 넣으면 된다.
> 이 봇은 **모의 운영 전용**이다. 거래소 API 키도, 주문 코드도 없다. 실제 돈은 움직이지 않는다.
> 예외: **테스트넷(TESTNET) 단계**는 바이낸스 **모의 환경(데모 트레이딩)**에 실제 주문을 보낸다(가짜 돈).
> 별도 서버·폴더에서만 하고, 절차는 맨 아래 [§10 테스트넷 절차](#10-테스트넷testnet-절차)를 따른다. LIVE(실거래)는 없다.
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
- `/resume`이 텔레그램에서 되는 것은 PAPER 단계의 예외다(SECURITY PV-15는 '해제는 서버에서'). TESTNET에서는
  `/pause`·`/resume`이 **신규 신호 받기만** 켜고 끄며, 주문 쪽 킬 스위치(T0)는 **서버 제어 파일로만** 풀린다(§10 T5).

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

주문 프로세스(`python -m bot.orders.worker`, 테스트넷 서비스 `orders`)도 같다: `0` 정상 · `1` 오류·selftest 실패 ·
`2` 설정·비밀 오류(mode가 testnet이 아님, 키 파일 없음·권한 넓음·PEM 형식, A의 비밀이 보임) · `3` DB 오류.

---

## 10. 테스트넷(TESTNET) 절차

> 바이낸스 **모의 환경(데모 트레이딩, `demo-fapi.binance.com`)**에 실제 서명 주문을 보내는 단계다(가짜 돈).
> 설계 기준: [bot/orders/DESIGN.md](../bot/orders/DESIGN.md). LIVE(실거래)는 없다 — 설정에 `mode = "live"`를 쓰면 시작을 거부한다.
> 호스트는 코드에 고정돼 있다(설정으로 실서버 주소를 넣을 수 없다).

두 프로세스로 돈다.

| | A: 서비스 `bot` (기존) | B: 서비스 `orders` (새로) |
|---|---|---|
| 하는 일 | 신호 계산·텔레그램 카드·[승인]·[확인]·추세 청산 **요청** | 주문(진입·손절·청산)·30초마다 거래소 대조·킬 스위치 |
| 비밀 | 텔레그램 토큰, Anthropic 키 | 바이낸스 API 키 ID, Ed25519 개인키 |
| 제어 파일 | 없음 | `config/orders_control.toml`(읽기 전용) |
| B 전용 원장 | 없음(보이면 A가 시작 거부) | 볼륨 `ordersstate` → `/state/orders_ledger.json`: T0·진입·청산·해제 첫 확인 시각 |

- 승인은 지금과 똑같이 텔레그램 [승인] → 60초 안에 [확인]. [확인]하는 순간 주문 큐에 들어가고 B가 2초 안에 가져간다.
- 진입은 **IOC 상한 지정가**(마크 +0.1% 이내, 안 되면 체결 0 → 신호 건너뜀). 체결 직후 거래소에 보호 손절(2×ATR20,
  closePosition)을 걸고 **조회로 확인**한다. 5초 안에 확인하지 못하면 즉시 시장가 청산 + 킬 스위치.
- 추세 청산은 모의 운영과 같이 **자동**(판단 + 30분). 손절은 거래소가 직접 한다(봇이 꺼져 있어도).
- 거래소 포지션은 **동시에 1개**다. 보유 중에 다른 신호가 오면 카드에 `보유 중(1포지션)`이 붙고, 승인해도 주문하지 않는다.
- 텔레그램으로는 주문·청산·킬 스위치 해제를 **할 수 없다**. `/pause`는 새 신호만 막는다.
- B는 **하나만** 돈다(DB 옆 잠금 파일 `testnet.sqlite3.orders.lock`). 서비스가 도는 중에 `docker compose run --rm orders`
  (기본 명령 `run`)를 하면 두 번째 B는 `다른 주문 프로세스(B)가 이미 돌고 있다`로 바로 끝난다(종료 코드 2). `status`·
  `selftest`는 잠그지 않는다.
- B는 A와 따로 **누적 한도**를 센다(B 전용 원장 기준, 다음 UTC 00:00 = KST 09:00 자동 해제): UTC 하루 진입 3번,
  24시간 안 손절 3번(T1), 하루 실현 손실 −3R 또는 R 자본 −3%(T2). 걸리면 텔레그램 `누적 한도 …` 경고, 새 진입 거부.

### T1. 준비 (paper와 분리)
- **별도 서버(또는 별도 폴더)**에서 한다. paper 운영 폴더에서 하지 않는다(DB·설정이 다르다).
- 1-1 ~ 1-4, 2-1 ~ 2-2(텔레그램·Anthropic 비밀 파일)를 이 폴더에서도 똑같이 한다. 텔레그램 봇은 **테스트넷 전용 봇**을
  하나 더 만드는 것을 권한다(메시지 머리표가 `[TESTNET]`이지만 채팅을 나누면 헷갈리지 않는다).
- 서버 시계: `timedatectl`에서 `System clock synchronized: yes`. 1초 넘게 틀리면 B가 주문하지 않는다.

### T2. 데모 계정·Ed25519 키 만들기 (사용자가 할 일)
1. 바이낸스 **데모 트레이딩**(웹 `demo.binance.com`)에 로그인해 선물(USDⓈ-M) 데모 계정을 연다(가짜 USDT가 들어 있다).
   메뉴 이름은 바뀔 수 있다 — '데모 트레이딩'의 **API 관리**를 찾는다.
2. **서버에서** 키 쌍을 만든다. 개인키는 서버 밖으로 내보내지 않는다(복사·메신저·메모 금지):
   ```bash
   mkdir -p secrets && chmod 700 secrets
   openssl genpkey -algorithm ed25519 -out secrets/binance_ed25519_private_key
   openssl pkey -in secrets/binance_ed25519_private_key -pubout -out binance_ed25519_public.pem
   cat binance_ed25519_public.pem        # 이 '공개키'만 바이낸스에 등록한다
   ```
   개인키 파일은 `-----BEGIN PRIVATE KEY-----`로 시작해야 한다(PKCS#8, 암호 없음). 다른 형식이면 B가 시작을 거부한다.
3. 데모 API 관리에서 **자체 생성(Self-generated) 키 → Ed25519**를 고르고 공개키 내용을 붙여 넣는다.
   권한은 **읽기 + 선물 거래(Enable Futures)만** 켠다. **출금(Withdrawals)·현물·마진·범용 전송은 켜지 않는다.**
   가능하면 **IP 제한**에 이 서버의 공인 IP만 넣는다.
4. 등록이 끝나면 화면에 나오는 **API 키(ID)**를 파일에 넣는다(값이 화면에 남지 않게):
   ```bash
   read -rs BK && printf '%s' "$BK" > secrets/binance_api_key && unset BK
   sudo chown 10001:10001 secrets/binance_api_key secrets/binance_ed25519_private_key
   sudo chmod 400 secrets/binance_api_key secrets/binance_ed25519_private_key
   rm binance_ed25519_public.pem        # 공개키 사본은 지워도 된다(바이낸스에 등록돼 있음)
   ```
5. 키가 샜을 수 있으면: 데모 API 관리에서 키 **삭제** → 2~4를 새로 한다 → `docker compose --profile testnet restart orders`.

### T3. 거래소 웹에서 계정 설정 (봇은 **검사만** 하고 바꾸지 않는다)
데모 선물 화면에서 한 번 맞춰 둔다. 다르면 B가 진입을 거부하고 킬 스위치(T0)를 건다.

| 항목 | 값 | 봇이 보는 곳 |
|---|---|---|
| 포지션 모드 | **One-way**(단방향). Hedge 금지 | `account_mode` |
| 자산 모드 | **Single-Asset**(멀티 에셋 끔) | `account_mode` |
| BTCUSDT 마진 | **Isolated**(격리) | `leverage_margin` |
| BTCUSDT 레버리지 | 설정 `expected_leverage`와 같은 값(기본 **3**, 3 넘으면 거부) | `leverage_margin` |

### T4. 설정·제어 파일 만들고 점검
```bash
cp config/bot.testnet.example.toml config/bot.toml
nano config/bot.toml                     # 텔레그램 숫자 ID 두 개, [orders] r_capital_usdt(데모 잔고에 맞게)
cp config/orders_control.example.toml config/orders_control.toml
chmod 644 config/orders_control.toml     # 그룹·다른 사용자 '쓰기'가 있으면 B가 수동 정지로 본다
docker compose build
docker compose run --rm bot check                              # A 점검: 거래 키가 A에 보이면 여기서 거부된다
docker compose --profile testnet run --rm orders selftest      # B 점검: 거래소 **조회만**(주문 없음)
```
`selftest`는 항목마다 `[통과]`/`[실패]`를 찍는다. 실패하면 고치고 다시 한다.

| 실패 항목 | 해결 |
|---|---|
| 서버 시각 | 서버 NTP 동기화(`timedatectl`). 1000ms 넘으면 주문 안 함 |
| 계정 모드 | T3의 One-way·Single-Asset |
| 레버리지·마진 | T3의 Isolated·레버리지(= `expected_leverage`) |
| 심볼 규칙 | tick 0.1·step 0.001이 아니면 거래소 규칙이 바뀐 것 — 개발자에게 알린다(코드 상수 확인) |
| 잔고 | 데모 계정에 USDT가 있어야 한다 |
| 조회 실패 `AUTH` | 키 ID·공개키 등록·권한(선물)·IP 제한 확인 |
| 조회 실패 `REGION_BLOCKED`(451·403)·`IP_BANNED`(418) | 서버 위치·IP 문제. 418이면 몇 분~몇 시간 기다린다 |
| `출금 권한: 모름(K10…)` | 실패가 아니다. 데모에서는 키 권한을 조회하지 못할 수 있다 — 웹에서 출금 권한이 꺼져 있는지 **눈으로** 확인 |

### T5. 제어 파일 — 정지와 킬 스위치(T0) 해제 (서버에서만)
`config/orders_control.toml`은 B에만 **읽기 전용**으로 붙는다. B는 2초마다 읽는다(재시작 필요 없음).
- **신규 진입 정지**: `halt = true`로 바꾼다. 보유 포지션의 손절·추세 청산은 계속된다. 풀 때는 `halt = false`.
- 파일이 없거나, 형식이 틀리거나, 그룹·다른 사용자 쓰기 권한이 있으면 B는 **수동 정지**로 본다(텔레그램 경고 `주문 제어 파일 문제`).
- **킬 스위치 T0**: 손절 확인 실패·계정 모드 이상·모르는 주문·조회 불가 등이 생기면 텔레그램에 `킬 스위치 T0 #N: 사유`가 온다.
  그동안 새 진입은 전부 거부되고, 보유 포지션의 손절은 거래소에 그대로 있다.
- **해제 순서**: ① 원인을 확인하고 고친다(T6 `status`, 로그, 거래소 웹) ② 제어 파일에 아래를 **추가**한다 ③ 텔레그램에 `T0 #N 해제` 알림이 온다.
  ```toml
  [[release]]
  halt_id = 3                        # 텔레그램 경고의 #N
  at = "2026-10-01T09:00:00Z"
  reason = "손절 누락 원인(데모 점검) 확인 후 해제"   # 필수
  ```
  텔레그램 `/resume`은 T0를 풀지 **않는다**. DB에 해제 행을 넣어도 소용없다(판정은 제어 파일만).
- **해제는 그 T0에 묶인다**: B는 `halt_id`를 **그 T0가 생긴 뒤에 처음 봤을 때만** 해제로 인정하고, `at`을 적으면 그 시각이
  T0 시각보다 이르면 무시한다. 그래서 `at`은 **적는 지금 시각(UTC)**으로 적는다. DB를 백업에서 되살리거나 새로 만든 뒤에는
  T0 번호가 다시 1부터 쓰일 수 있다 — 옛 `[[release]]` 줄은 새 T0를 풀지 못하므로(의도된 동작) 지우고, 새 T0마다 새로 적는다.
  해제가 안 먹으면 B 로그에 `인정하지 않은 id`가 찍힌다.
- **DB 변조 흔적 T0**(`order_error`, 경고 문구 `주문 DB 변조 흔적`): 추가 전용 표(T0·주문 기록)의 행이 지워졌거나 보호
  트리거 본문이 바뀌었다 = A 침해 의심. 서버에서 원인(누가 DB를 고쳤나)을 확인하기 전에는 해제하지 않는다. 해제하면 그
  흔적은 '확인됨'으로 원장에 남고, 더 지워지면 다시 T0가 걸린다.

### T6. 시작·상태 보기
```bash
docker compose --profile testnet up -d          # A(bot) + B(orders)
docker compose --profile testnet ps             # 둘 다 (healthy)
docker compose --profile testnet logs --tail 100 orders
docker compose --profile testnet exec orders python -m bot.orders.worker --config /config/bot.toml status
```
- 텔레그램에 `[TESTNET] 시작 …`(A)과 `[TESTNET] 주문 프로세스(B) 재시작 복구: 이상 없음`(B)이 오면 정상이다.
- 텔레그램 `/status`에 B 심장 박동·마지막 대조·풀리지 않은 T0가, `/positions`에 거래소(데모) 보유가 나온다.
- `status`(서버 명령)는 DB만 읽는다: 노출 의도, T0마다 `정지 중`/`해제됨`, 마지막 대조, 시계 오차.
- 멈추기: `docker compose --profile testnet stop orders`(B만) — 거래소 손절은 남아 있어 보유 포지션은 보호된다.
  다시 켜면 B가 먼저 **거래소 사실로 복구**한다(손절이 확인되지 않은 포지션은 새로 손절을 거는 대신 청산 + T0 —
  청산이 안 되면 그때는 보호 손절을 다시 건다).
- **B 전용 원장**(`ordersstate` 볼륨의 `/state/orders_ledger.json`, 0600): B가 건 T0·진입·청산을 A가 못 쓰는 곳에 남긴다.
  B 로그에 `B 전용 원장 … 문제`(권한·손상·폴더 없음)가 나오면 B는 **새 진입만 막고** 보호는 계속한다. 볼륨이 붙어 있는지
  (`docker compose --profile testnet exec orders ls -l /state`), 파일 권한이 0600인지 확인한다. 손상됐으면 파일을 다른 이름으로
  옮기고 `restart orders`(새 원장으로 시작 — 그 뒤 하루 진입 수·T1·T2는 DB의 B 기록으로도 센다).

### T7. 왕복 시험 (텔레그램 /selftest 대신 서버 명령)
B가 돌고 있는 상태에서, 시험 신호 한 건으로 **진입 → 손절 등록·확인 → 추세 청산 → 손절 취소**를 끝까지 해 본다.
```bash
docker compose --profile testnet exec orders python -m bot.orders.worker --config /config/bot.toml selftest --roundtrip
```
- 먼저 T4의 조회 점검을 다시 하고, 통과해야 시작한다. 보유 중·대기 중인 의도가 있거나 T0·수동 정지 중이면 시작하지 않는다.
- 크기는 진짜 신호와 같은 규칙(R 자본 × 0.5% 위험, 명목 상한)이다. 시험 ATR은 마크의 1%(손절 거리 약 2%).
- 끝에 `결과: CLOSED exit_reason=trend`와 `주문 요청: sig-…-e1×1, sig-…-sl×…, sig-…-x1×1`이 나오면 통과다.
  텔레그램에도 `[TESTNET]` 체결·청산 알림이 온다(알림 경로 왕복 확인).
- 실패하면 결과 줄의 상태·`halt_id`를 보고 T5·T8을 따른다. 거래소 웹에서 포지션 0·미체결 0인지 **눈으로** 확인한다.
- 시험 신호는 DB에 `spec_version = SELFTEST`로 남는다(진짜 신호와 구분).

### T8. 문제 대응
| 증상 | 할 일 |
|---|---|
| 텔레그램 `주문 프로세스(B) 심장 박동 없음` / `orders`가 `(unhealthy)` | `docker compose --profile testnet logs --tail 200 orders` → `restart orders`. 보유 포지션은 거래소 손절이 보호 중 |
| `P1 킬 스위치 T0: 비상 청산 실패` | **거래소 웹에서 BTCUSDT 포지션을 시장가로 닫고, 남은 주문·조건부 주문을 모두 취소**한다 → `status`로 확인 → 원인 확인 뒤 T5로 해제. B가 포지션 0을 확인해 그 의도를 끝낸다 |
| T0 `unknown_position`(모르는 포지션) | 봇 계좌에서 사람이 거래했거나 이상. 봇은 **청산하지 않는다**. 웹에서 확인·정리 → T5 해제. 봇 계좌에서 손으로 매매하지 않는다 |
| T0 `unknown_order` | 봇이 모르는 일반 주문은 이미 취소했다. 웹에서 확인 → T5 해제 |
| T0 `stop_missing`·`stop_not_verified`·`restart_unprotected` | 봇이 이미 청산했다(포지션 0 확인). 로그·order_events로 원인 확인(데모 장애·K 항목) → T5 해제 |
| T0 `algo_endpoint`(-4120) | 손절 창구 설정(`conditional_api`)이 거래소와 다르다. T9 K2 확인 뒤 설정 수정 → 재시작 → 해제 |
| T0 `clock_skew` | 서버 시계 동기화 → 해제 |
| T0 `auth`·`exchange_block` | 키·권한·IP·지역 차단 확인(T2) → 해제 |
| T0 `reconcile_unavailable` | 거래소 조회가 3번 연속 실패. 거래소 점검·네트워크 확인. 손절은 거래소에 있다 → 복구 뒤 해제 |
| 신호가 `order:position_exists`로 건너뜀 | 정상(동시 1포지션) |
| 신호가 `order:stale_approval`로 건너뜀 | [확인] 뒤 5분 안에 B가 못 가져갔다(B가 꺼져 있었음). 정상 보호 동작 |
| 신호가 `order:future_approval`로 건너뜀 | 승인 시각이 미래 = A 서버 시계 이상 또는 DB 위조. 시계·A 로그 확인 |
| 신호가 `order:daily_entry_cap`·`t1_stop_streak`·`t2_daily_loss`로 건너뜀 | 누적 한도(위 T 절). 다음 UTC 00:00(KST 09:00)에 자동 해제. 짧은 시간에 여러 번이면 A 침해·이상 신호를 의심 |
| 신호가 `order:ledger_unavailable`로 건너뜀 | B 전용 원장 문제(T6). 보유 보호는 계속된다 |
| T0 `unknown_position` + 경고 `늦게 확인된 진입 체결` | 체결이 조회에 늦게 보여 '체결 없음'으로 끝낸 신호의 진입이 실제로는 체결돼 있었다. 봇이 이미 청산했다(안 되면 손절을 걸었다). 웹에서 포지션 0 확인 → 해제 |
| T0 `position_mismatch`(`terminal_intent_stop_with_position`) | DB는 '끝남'인데 거래소에 포지션과 그 신호의 손절이 있다(DB 위조 의심). 봇은 **손절을 지우지 않고** 둔다. 웹에서 확인·정리 → 해제 |
| `P1 … 비상 청산 실패 — 보호 손절은 다시 걸었다` / `보호 손절도 못 걸었다` | 포지션은 손절로 보호 중이거나 아직 무방비다. B는 **매 바퀴(2초)** HALTED 보유의 손절을 조회해, 없으면 곧바로 다시 청산·손절을 시도한다(V-2 — 대조 주기를 기다리지 않는다). 그래도 **거래소 웹에서 포지션·손절을 즉시 확인**하고 청산한 뒤 해제 |
| `orders`가 종료 코드 2·3으로 계속 재시작(로그 `시작 거부(...) — 거래소 포지션 보호 결과: ...`) | 설정·비밀·DB 문제(트리거 누락·모드 불일치·A 비밀이 보임 등)로 B가 시작을 거부한다. **거부하기 전에** B는 DB 없이 거래소만 보고 보호한다(V-1): 우리 손절이 살아 있으면 그대로(`protected`), 없으면 reduceOnly 시장가로 전량 청산(`flattened`, 주문 ID `sig-<새 ID>-f1..f3`). 결과가 `flat`·`flattened`·`protected`가 아니면(`unavailable`·`failed`·`short`) **거래소 웹에서 즉시 청산**. 다른 B가 잠금을 쥐고 있으면 아무것도 하지 않는다. 원인을 고친 뒤 재시작하면 recover가 거래소 사실(포지션 0 → CLOSED·T0)을 기록한다. 이 경보는 A의 outbox가 살아 있을 때만 텔레그램으로 간다(R-13) — `docker compose ps`의 재시작 횟수도 본다 |
| B 로그 `비상 보호(...)` | DB 쓰기가 막힌 동안(잠김 등) B가 DB 없이 손절을 걸거나 청산했다. DB가 풀리면 다음 바퀴에 거래소 사실로 기록한다. A가 DB를 오래 잡고 있지 않은지 확인 |
| 429(레이트 리밋) | B는 Retry-After 동안 **아무 요청도 보내지 않는다**(더 보내면 418 금지로 번진다). 그동안 손절 등록이 막히면 창이 끝난 뒤 청산 + T0 `unprotected_timeout` |
| 418(IP 금지)·로그 `local rate gate` | 금지 동안 B는 손절도 청산도 **보낼 수 없다**(거래소가 막는다, V-6). 금지 직전에 체결된 포지션은 금지가 풀릴 때까지 무방비일 수 있다 → **거래소 웹 UI에서 포지션·손절을 즉시 확인하고, 손절이 없으면 웹에서 시장가로 청산**한다(웹은 API IP 금지와 별개). 금지가 풀리면 B가 대조로 거래소 사실을 기록한다 → T5 해제 |

### T9. PoC 확인 기록표 (데모 키로 한 번씩 확인하고 적는다)
이 컨테이너(개발 환경)에서는 바이낸스에 접속할 수 없어 아래는 **확인되지 않았다**. 확인 전에는 보수적인 기본값으로 돈다.
설정값을 바꿀 때는 이 표에 날짜·결과를 먼저 적는다(텔레그램으로는 바꿀 수 없다).

| K | 확인할 것 | 확인 방법 | 기본값(미확인) | 결과·날짜 |
|---|---|---|---|---|
| K1 | 포지션 0에서 closePosition 손절을 미리 걸 수 있나, 포지션이 닫히면 자동 취소되나 | 데모 웹에서 포지션 없이 BTCUSDT 'Stop Market · Close Position' 주문을 걸어 본다 | `stop_placement = "post_fill"` | |
| K2 | 조건부 주문 창구(algo `/fapi/v1/algoOrder` vs 옛 `/fapi/v1/order`) | T7 왕복 시험 통과 = algo 창구 동작. 로그에 -4120이 있으면 창구 문제 | `conditional_api = "algo"` | |
| K3 | 모의 환경 호스트(데모 vs 구 테스트넷) | T4 `selftest`의 `환경` 줄 통과 | `env = "demo"` | |
| K4 | algo 요청 필드 이름·값(type/orderType, priceProtect 대소문자) | T7 통과(봇이 손절 트리거·closePosition·workingType을 조회로 대조) | ccxt 매핑 | |
| K5 | 손절 발동 뒤 상태 값·실제 주문 연결·조회 가능 기간 | 작은 포지션에서 손절이 실제로 발동했을 때 `status`·order_events | 청산가 None으로 CLOSED(stop) | |
| K6 | IOC 부분 체결 응답 모양 | 로그·order_events의 진입 응답 | executedQty만 믿음 | |
| K7 | `priceProtect=false` 허용 | T7 통과 | false | |
| K8 | 레버리지·마진 조회 엔드포인트 | T4 `레버리지·마진` 통과 | symbolConfig → positionRisk | |
| K9 | positionSide/dual·multiAssetsMargin 조회 | T4 `계정 모드` 통과 | 조회 실패 = 거부 + T0 | |
| K10 | 키 출금 권한 조회 | T4 `출금 권한`(데모는 '모름'일 수 있음) | 모름 허용 — **LIVE 전 필수 확인** | |
| K11 | BTCUSDT 최소 수량·최소 명목 | T4 `심볼 규칙` 줄의 minQty·minNotional | 거래소 값 그대로 | |
| K12 | 주문 접수 → 조회에 보이기까지 지연 | order_events의 REQUEST·QUERY 시각 | 2초 | |
| K13 | countdownCancelAll이 algo 손절도 지우나 | 쓰지 않음 | 쓰지 않음 | |
| K14 | 청산 뒤 closePosition 손절이 자동 취소되나 | T7 뒤 웹의 조건부 주문 목록(봇은 항상 명시적으로 취소) | 항상 취소 | |
| K15 | 끝난(FILLED·EXPIRED) 시장가 주문의 clientOrderId를 다시 쓸 수 있나(비상 청산 f1~f3을 다음 주기에 재사용) | 데모에서 같은 `newClientOrderId`로 reduceOnly 시장가를 두 번(첫 주문이 끝난 뒤) | 재사용(거부되면 -4116 → 다음 번호) | |
| K16 | 손익 내역(income, REALIZED_PNL) 조회로 T2를 거래소 사실로 계산할 수 있나 | `GET /fapi/v1/income` (서명) 응답 | B 원장의 추정 손익(청산가·손절가, 수수료 0.05% 가정) | |
