# 07. 사람 승인(Human-in-the-loop) 채널 조사: 텔레그램 버튼 승인 설계

> 작성일: 2026-09-29 · 작성: 리서처(telegram_hitl) · 상태: 조사·설계 보고서 (코드 없음, 설치 없음)
> 관련 문서: [docs/PLAN.md](../../docs/PLAN.md) (기획 v0.1, 특히 §2 흐름·§3.1 알림 채널·§4.2 버튼 보안), [docs/STRATEGY.md](../../docs/STRATEGY.md) (v0.2, §7 지정가 분할 진입·§8 하드 가드), [01_existing_systems.md](./01_existing_systems.md) (§2.4 사람 승인 패턴), [03_llm_trading.md](./03_llm_trading.md), [04_exchanges_regulation.md](./04_exchanges_regulation.md), [05_infra_ops.md](./05_infra_ops.md)
> 표기: **[직접]** = GitHub·PyPI 원문을 직접 열어 확인 · **(검색 요약)** = 다른 리서처 문서에 검색 요약으로만 확인된 사실을 옮김 · **(분석)** = 확인한 사실을 바탕으로 이 문서가 추론한 것 · **확인 필요** = 확인하지 못함(추측하지 않음) · **(제안값)** = 근거 없는 출발값, 페이퍼 기록으로 조정

---

## 1. 핵심 요약 (5줄)

1. **채널은 텔레그램(롱 폴링)을 유지한다.** 봇이 텔레그램에 먼저 접속해 새 소식을 가져오므로 서버에 들어오는 포트가 0개다. 버튼, 무음 알림, 메시지 수정 기능도 다 있다 [직접]. 다만 PLAN §3.1의 "Slack은 외부 공개 HTTPS 서버가 필요하다"는 **틀렸다**. Slack도 **Socket Mode**를 쓰면 공개 주소가 필요 없다 [직접]. 텔레그램을 고르는 이유는 보안 차이가 아니라 **개인용·모바일·단순함**이다.
2. **버튼 보안은 "콜백 데이터는 텔레그램이 아니라 사용자 앱이 보낸 값이라 조작될 수 있다"는 사실에서 출발한다** [직접: python-telegram-bot 위키, Bot API 문서]. 그래서 다음을 지킨다.
   - 버튼에는 **추측할 수 없는 신호 ID와 동작(승인/패스)만** 넣는다(최대 64바이트).
   - 가격·수량·손절은 **서버 DB에서 다시 꺼낸다**.
   - **사용자 ID와 채팅 ID를 둘 다** 화이트리스트로 확인한다. 1:1 채팅에서만 받는다.
   - 신호 상태는 DB에서 **원자적으로 한 번만** 바꾼다. 거래소 주문 ID도 신호 ID로 고정한다.
3. **PLAN에 빠진 핵심은 "승인 시점 가격 재검증"이다.** 버튼을 누를 때와 확정할 때 두 번, **현재가로 하드 가드를 다시 계산**한다.
   - 예: 손익비가 딱 1.5인 롱 신호는 가격이 0.1%만 불리하게 움직여도 시장가로 들어가면 손익비가 **1.33**으로 떨어져 가드에 걸린다(§2.6).
   - 그래서 기본값은 **계획 진입가에 거는 post-only 지정가**다. 여기에 **거래소 쪽 자동 만료(GTD)**를 붙인다. 바이낸스 GTD는 "현재 + 600초보다 커야 한다"는 조건이 있다 [직접].
   - "즉시 진입"은 재계산을 통과할 때만 허용하고, **가격 상한을 건 IOC 지정가**로 낸다. 순수 시장가로는 들어가지 않는다.
4. **계정 탈취를 최악의 경우로 놓고 권한을 비대칭으로 나눈다.**
   - 텔레그램으로는 **위험을 줄이는 동작**만 한다: 신호 승인(가드 안에서만), 패스, 정지, 일시정지.
   - **한도 완화·정지 해제·설정 변경**은 서버에서만 한다(2단계에서는 Tailscale 내부 대시보드 + 패스키).
   - 봇 토큰 유출은 탐지할 수 있다. `getWebhookInfo`에 모르는 URL이 생기거나 폴링에서 409 충돌이 나면, **신규 주문을 자동 차단**하고 이메일로 경보한다.
   - 텔레그램 계정에는 **2단계 인증 비밀번호**가 필수다.
5. **알림 피로는 "사람이 행동해야 할 때만 알린다"(PagerDuty 원칙 [직접])로 관리한다.**
   - 채팅을 셋으로 나눈다: 승인 채팅(소리 켬), 운영 채팅(무음), 아침 요약.
   - **방해 금지 시간에는 신호를 보내지 않고 기록만** 한다.
   - 하루 승인 요청 수에 상한을 둔다.
   - **승인율, 결정 시간, 패스한 신호의 사후 성과**를 재서 승인이 형식적 도장 찍기(고무도장)로 변했는지 점검한다.

---

## 2. 본문

### 2.0 조사 방법과 한계

| 항목 | 내용 |
|---|---|
| 웹 검색 | **이번 리서처는 WebSearch를 한 번도 하지 못했다.** 세션 전체 검색 한도(200회, 다른 리서처와 공유)가 이미 소진된 상태였다. 과제의 "최소 10회 검색" 조건은 **충족하지 못했다**. 한도를 늘리는 것은 사용자만 할 수 있어서, 우회하지 않고 아래 직접 열람으로 대신했다 |
| 직접 열람 [직접] | 허용 도메인(github.com, raw.githubusercontent.com, pypi.org)에서 **서로 다른 원문 30여 건**을 열었다. ① 텔레그램 Bot API 명세 사본(Bot API 10.3) ② aiogram 소스의 Bot API 메서드 설명(공식 문서 문구를 그대로 옮긴 docstring) ③ python-telegram-bot 위키 5개 페이지와 소스 ④ freqtrade 텔레그램 문서 ⑤ Slack bolt-python·python-slack-sdk 문서와 소스 ⑥ Discord API 문서 원본 ⑦ 바이낸스 현물 API 문서와 USDⓈ-M 선물 공식 SDK ⑧ 바이비트 API 문서 원본 ⑨ TDLib 명세 ⑩ ntfy 문서 ⑪ PagerDuty 알림 원칙 ⑫ Vibe-Trading README ⑬ PyPI 버전 정보 |
| 차단 | core.telegram.org, telegram.org, slack.com, binance.com 문서 사이트는 조직 네트워크 정책으로 막혀 있어 열지 않았다. 텔레그램 공식 문구는 **GitHub에 있는 사본과 라이브러리 docstring**으로 확인했다. 원 사이트와 문구가 다를 수 있다 |
| 한계 | 텔레그램 계정 보안(2단계 인증 세부, 활성 세션, 로그인 알림), BotFather 메뉴, 채팅별 전송 한도는 공식 원문을 열지 못했다. 해당 항목은 **확인 필요**로 표시했다 |

**용어 (처음 한 번만 풀이)**
- **롱 폴링(long polling)**: 봇이 텔레그램 서버에 "새 소식 있어?"라고 묻고, 소식이 올 때까지 연결을 잠시 열어 두는 방식이다. 봇이 **밖으로 나가는** 연결만 쓴다
- **웹훅(webhook)**: 텔레그램이 내 서버 주소로 소식을 **밀어 넣는** 방식이다. 내 서버가 인터넷에 열려 있어야 한다
- **인라인 키보드**: 메시지 아래에 붙는 버튼 묶음이다
- **콜백 쿼리(callback query)**: 버튼을 누르면 봇에게 전달되는 이벤트다. 버튼에 심어 둔 `callback_data` 문자열이 함께 온다
- **멱등성(idempotency)**: 같은 요청이 두 번 와도 결과가 한 번 처리한 것과 같게 만드는 성질이다
- **원자적 상태 전이(CAS, compare-and-swap)**: "상태가 '대기'일 때만 '실행 중'으로 바꿔라"를 DB가 한 번에 처리하는 것이다. 두 요청이 동시에 와도 하나만 성공한다
- **HMAC**: 비밀 키로 만든 서명이다. 비밀 키가 없으면 같은 서명을 만들 수 없다
- **post-only 지정가**: 호가창에 **걸리기만 하는** 주문이다. 즉시 체결될 가격이면 거래소가 취소한다(메이커 수수료 보장)
- **GTD(Good Till Date)**: 지정한 시각이 지나면 거래소가 알아서 취소하는 주문이다
- **IOC(Immediate or Cancel)**: 즉시 체결되는 만큼만 체결하고 나머지는 바로 취소하는 주문이다. 가격 상한을 걸면 "상한이 있는 시장가"처럼 쓸 수 있다
- **슬리피지(slippage)**: 예상한 가격과 실제 체결 가격의 차이다
- **패스키(passkey)**: 비밀번호 대신 기기 안의 키와 생체 인증으로 로그인하는 표준(FIDO2·WebAuthn) 방식이다
- **Socket Mode**: Slack 앱이 Slack에 먼저 웹소켓으로 접속해 이벤트를 받는 방식이다. 텔레그램 롱 폴링과 같은 방향이다

---

### 2.1 텔레그램 Bot API: 이 시스템에 중요한 사실

| 항목 | 확인한 사실 | 출처 | 우리 시스템에 주는 의미 |
|---|---|---|---|
| 현재 버전 | **Bot API 10.3, 2026-08-24** 발표 | [1] [직접] | 라이브러리가 이 버전을 지원하는지 확인한다. python-telegram-bot 최신은 **22.8(2026-06-12)**, aiogram은 **3.31.0(2026-08-26)** [직접: PyPI [30]] |
| 버튼 데이터 한도 | `callback_data`: **"1-64 bytes"** | [1] [직접], [9] [직접] | 한글은 UTF-8에서 한 글자가 3바이트다. **ASCII만** 쓰고, 가격·수량 같은 내용은 넣지 않는다 |
| 콜백을 누가 보내나 | "Callback updates are **not sent by Telegram, but by the client**. This means that they can be manipulated by a user." | [9] [직접] (python-telegram-bot 위키) | 버튼 데이터는 **입력값**으로 취급한다. 서버가 만든 신호인지, 아직 유효한지 DB에서 확인한다 |
| 콜백 데이터 일치 여부 | `data`: "Be aware that the message originated the query **can contain no callback buttons with this data**" | [4] [직접] (Bot API 문구를 옮긴 aiogram docstring) | 메시지에 없던 데이터가 올 수 있다고 텔레그램이 스스로 경고한다. 위와 같은 결론이다 |
| 콜백 응답 의무 | "Telegram clients will display a **progress bar until you call answerCallbackQuery**. It is, therefore, necessary to react by calling answerCallbackQuery even if no notification to the user is needed" | [4] [직접] | 클릭하면 **먼저 응답**하고(로딩 표시 제거) 무거운 처리는 그 뒤에 한다. 응답 문구는 0~200자, `show_alert`로 팝업을 띄울 수 있다 [3]. 늦게 응답하면 오류가 난다는 보고가 있지만 **정확한 시간은 확인 필요**다 |
| 업데이트 확정 방식 | "An update is considered confirmed as soon as getUpdates is called with an **offset higher than its update_id**." 그리고 "In order to **avoid getting duplicate updates**, recalculate offset after each server response." | [2] [직접] | 봇이 처리 도중 죽으면 **같은 업데이트(같은 클릭)가 다시 온다**. 그래서 멱등성이 필수다(§2.3.4) |
| update_id | 순차적으로 증가한다. "allows you to **ignore repeated updates**". 1주일 넘게 업데이트가 없으면 다음 번호는 무작위로 정해진다 | [5] [직접] | 처리한 `update_id`와 콜백 `id`를 DB에 저장해 중복을 거른다 |
| 웹훅과 폴링은 동시에 못 쓴다 | getUpdates: "This method **will not work if an outgoing webhook is set up**." | [2] [직접] | 토큰을 훔친 사람이 웹훅을 걸면 **우리 폴링이 멈춘다**. 이것이 탐지 신호가 된다(§2.4) |
| 받을 업데이트 종류 제한 | `allowed_updates`로 받을 종류를 지정할 수 있다. 예: `["message", "callback_query"]` | [2] [직접] | **메시지와 콜백만** 받는다. 공격 표면이 줄어든다 |
| 토큰의 위치 | python-telegram-bot 기본 주소는 `https://api.telegram.org/bot`이고, 토큰은 **이 문자열 뒤에 붙는다** | [15] [직접] | 토큰이 **URL 경로**에 들어간다. HTTP 디버그 로그를 켜면 토큰이 로그에 남는다(05 §2.5와 같은 결론) |
| 무음 전송 | `disable_notification`: "Sends the message silently. Users will receive a notification with no sound" | [1][6] [직접] | 정보성 알림은 무음으로 보낸다(§2.9) |
| 전달·저장 방지 | `protect_content`: "Protects the contents of the sent message from forwarding and saving" | [1][6] [직접] | 포지션·잔고 메시지에 켠다. 스크린샷까지 막는지는 확인 필요다 |
| 메시지 길이 | 일반 메시지 1~4,096자, 사진 캡션 0~**1,024자**, 사진 10MB 이하 | [6][7] [직접] | 차트 이미지 캡션에는 **요약만** 넣고, 긴 근거는 별도 메시지나 [상세] 버튼으로 뺀다 |
| 버튼만 고치기 | `editMessageReplyMarkup`: "edit only the reply markup of messages sent by the bot" | [1] [직접] | 결정이 나거나 만료되면 **버튼을 지워** 오래된 클릭을 줄인다. 다만 버튼을 지워도 조작된 콜백은 올 수 있으므로 서버 검증이 여전히 필요하다 |
| 메시지 삭제 한도 | "A message can only be deleted if it was sent **less than 48 hours** ago" | [1] [직접] | 오래된 신호 메시지는 삭제하지 말고 **수정**으로 만료를 표시한다 |
| 전송 속도 한도 | "~**30 messages/second** for all ordinary messages and ~**20 messages/minute** for group messages". 한도를 넘으면 `RetryAfter` 오류가 나고, 무시하고 계속 재시도하면 "bot being banned for some time" | [8] [직접] | 우리 알림량(하루 수십 건)으로는 문제가 없다. 다만 **오류 알림 폭주**는 묶어서 보낸다(05 §2.9와 같음). 채팅 하나당 초당 한도는 **확인 필요**다 |
| 토큰 하나당 폴러 하나 | 같은 토큰으로 두 프로세스가 폴링하면 "Conflict: terminated by other getUpdates request"(409) 오류가 난다 | 01 §2.4 (검색 요약) | 개발용·운영용 봇을 분리한다(01·05와 같음). 뜻밖의 409는 **토큰 유출 신호**일 수도 있다 |
| 재시작 시 밀린 업데이트 | python-telegram-bot `run_polling(drop_pending_updates=...)`: "Whether to clean any pending updates on Telegram servers before actually starting to poll. Default is False." | [14] [직접] | 모두 버리면 **꺼져 있는 동안 보낸 `/stop`도 사라진다**. 버리지 말고 받되, **정지 명령은 오래돼도 실행**하고 **승인 클릭은 신호 만료 규칙으로 거절**한다(§3.2) |
| 업데이트 보관 기간 | 서버에 쌓인 업데이트가 최대 24시간 보관된다는 공식 문구가 있는 것으로 알려져 있다 | **확인 필요** (원문 미열람) | 확인되면 "하루 넘게 꺼져 있으면 `/stop`도 사라진다"는 뜻이다. 비상 정지는 텔레그램에만 의존하지 않는다(05 §2.11) |

---

### 2.2 수신 방식: 롱 폴링 vs 웹훅

| 기준 | **롱 폴링 (권장)** | 웹훅 |
|---|---|---|
| 연결 방향 | 봇 → 텔레그램 (밖으로 나가는 연결만) | 텔레그램 → 내 서버 (**들어오는 연결**) |
| 서버 요건 | 없음. 방화벽에서 들어오는 연결을 **전부 막아도** 된다 | "A public IP address or domain", HTTPS 필수 [10] [직접]. 포트는 **443, 80, 88, 8443**만 된다 [3][10] [직접] |
| 가짜 요청 방어 | 해당 없음. 업데이트는 텔레그램 서버에서만 가져온다 | 비밀값을 `X-Telegram-Bot-Api-Secret-Token` 헤더로 받아 확인해야 한다(1~256자) [3] [직접]. "so no one can send fake updates to your bot" [10] [직접] |
| 실패 시 재시도 | 봇이 다시 물어보면 된다. 확정 전 업데이트는 다시 온다 [2] | 텔레그램이 2XX 외 응답에 "repeat the request and give up after a reasonable amount of attempts" [3] [직접] |
| 지연 | 수 초 이내 (우리 용도로 충분, 분석) | 약간 빠름 |
| 인스턴스 | 토큰 하나당 폴러 하나 (01, 검색 요약) | 여러 서버에 나눌 수 있음 (우리에게 불필요) |
| 인증서·도메인 관리 | 없음 | 도메인, TLS 인증서 갱신, 리버스 프록시가 필요하다 |
| 라이브러리 권고 | — | "You should have a good reason to switch from polling to a webhook. **Don't do it simply because it sounds cool.**" [10] [직접] |
| 우리 결론 | **채택.** 05의 "서버로 들어오는 문 0개" 원칙과 맞는다 | 채택하지 않는다 |

---

### 2.3 버튼(콜백) 보안

#### 2.3.1 위협을 먼저 정리한다 (분석)

| # | 위협 | 어떻게 일어나나 | 막는 방법 |
|---|---|---|---|
| T1 | **다른 사람이 버튼을 누름** | 봇이 그룹에 초대됨, 메시지가 전달(forward)됨 | 사용자 ID **그리고** 채팅 ID 화이트리스트, 1:1 채팅만, 그룹 참여 금지 설정(BotFather 메뉴는 **확인 필요**). freqtrade 문서도 경고한다: "When using telegram groups, you're giving **every member** of the telegram group access to your freqtrade bot" [16] [직접] |
| T2 | **조작된 콜백 데이터** | 사용자 앱이 콜백을 보내므로 값이 조작될 수 있다 [9]. 토큰을 훔친 사람이 봇 이름으로 **가짜 버튼**을 보낼 수도 있다(§2.4) | 버튼에는 **랜덤 신호 ID + 동작**만 넣는다. 파라미터는 서버 DB에서 꺼낸다. ID는 **순번 금지**(`124` 다음 `125`는 추측된다) |
| T3 | **중복 실행** | 두 번 연속 클릭, 처리 도중 재시작해서 같은 업데이트가 다시 옴 [2], 네트워크 재시도 | DB 원자적 상태 전이 + 처리한 `update_id`·콜백 ID 기록 + 거래소 주문 ID를 신호 ID에서 만든다(§2.3.4) |
| T4 | **오래된 신호 승인** | 알림을 한참 뒤에 봄. 재시작 뒤 밀린 클릭이 처리됨 | 신호 만료 시각은 서버에 저장한다. 클릭 시점과 확정 시점에 **가격 재검증**을 한다(§2.6) |
| T5 | **표시된 숫자와 실제 주문이 다름** | 토큰을 훔친 사람이 봇 메시지를 **수정**해 손절가를 다르게 보이게 함(§2.4). 또는 코드 버그 | 확인 화면은 클릭 순간 **서버가 새로 만든다**. 주문은 DB 값으로만 낸다. 최종 보고 메시지에 **실제 주문 응답**(거래소가 돌려준 값)을 표시한다 |
| T6 | **잘못 누름** | 폰에서 롱/숏·확인/취소를 잘못 누름 | 2단계 확인, 분석 방향 버튼 하나만 제공(§2.10), 확인 버튼과 취소 버튼을 서로 다른 줄에 배치 |

#### 2.3.2 클릭이 오면 이 순서로 검사한다

| 순서 | 검사 | 실패하면 | 근거 |
|---|---|---|---|
| 0 | 즉시 `answerCallbackQuery` (로딩 표시 제거) | — | [4] [직접] |
| 1 | `callback_query.from.id`가 허용 사용자 ID(숫자)인가 | 무시 + 감사 로그 + 운영 채팅에 경고. 상대방에게는 아무 말도 하지 않는다 | [12] [직접] (python-telegram-bot의 사용자 제한 예), [16] |
| 2 | `callback_query.message.chat.id`가 허용 채팅 ID이고, 채팅 종류가 1:1(private)인가 | 위와 같음 | T1 (분석) |
| 3 | `callback_data` 형식·버전·(선택) HMAC 서명이 맞는가 | "알 수 없는 버튼" 응답 + 기록 | [9] (분석) |
| 4 | 신호 ID가 DB에 있고, 상태가 이 동작을 허용하는가 | "이미 처리됨/만료됨" 팝업(`show_alert`) | T3·T4 |
| 5 | 킬 스위치·일일 한도·이벤트 금지 구간 등 **현재 시점**의 가드 | "차단됨: 사유" | STRATEGY §8 |
| 6 | 현재가 재검증(§2.6) | "가격 변동으로 무효" + 버튼 제거 | §2.6 |
| 7 | 통과하면 **확인 화면**을 서버가 새로 계산해 보여 준다 | — | PLAN §4.2 |

- **@사용자명은 쓰지 않는다.** 사용자명은 바꿀 수 있다. 숫자 ID만 쓴다. python-telegram-bot 예제도 숫자 ID 목록을 쓴다 [12] [직접].
- 권한 검사는 **모든 핸들러에 공통으로** 먼저 걸리게 만든다. python-telegram-bot 문서는 핸들러별 필터(`filters.User`, `filters.Chat`)나 공통 콜백으로 막는 방법을 제시한다 [12] [직접].

#### 2.3.3 callback_data 형식 (64바이트 안)

```
v1:A:K7Q2M9XT4P:Zq3v8Rk1Wm0c
│  │ │          └ (선택) HMAC-SHA256 앞 9바이트를 base64url로 = 12자
│  │ └ 신호 ID: 랜덤 50비트를 base32로 = 10자 (순번 금지)
│  └ 동작: A=승인요청, C=확정, X=취소, P=패스, R1~R4=패스 이유
└ 형식 버전
→ 전체 28바이트 (한도 64바이트)
```

- **HMAC은 선택이다(심층 방어).** 신호 ID가 랜덤이고 서버 상태를 확인한다면, HMAC이 추가로 막는 공격은 "ID 추측"뿐이다(분석). 한편 토큰을 훔친 사람이 가로챈 콜백에서 **실제 데이터를 복사해 재사용**하는 것은 HMAC으로 막지 못한다. 이것은 **1회성 + 만료 + 확정 단계**가 막는다.
- python-telegram-bot의 "arbitrary callback_data" 기능은 객체를 메모리 캐시에 두고 UUID만 보낸다. 조작된 데이터는 `InvalidCallbackData`로 처리된다 [9] [직접]. 다만 "If you don't use persistence, **buttons won't work after restarting your bot**" [9] [직접]이고 캐시는 기본 1,024개다. 우리는 이 기능 대신 **SQLite의 신호 테이블**을 진실의 원천으로 쓴다(분석). 재시작에 견디고 감사 로그와도 합쳐진다.

#### 2.3.4 중복·재전송·동시 클릭 (멱등성)

| 원인 | 실제 모습 | 방어 (여러 겹) |
|---|---|---|
| 같은 버튼을 빠르게 두 번 누름 | 콜백 ID가 다른 두 요청이 같은 데이터로 온다. python-telegram-bot 문서도 "multiple CBQ from one button" 문제를 다룬다 [12] [직접] | DB에서 `UPDATE signals SET state='EXECUTING' WHERE id=? AND state='CONFIRMING'` → **바뀐 행이 1개일 때만** 진행한다(원자적 상태 전이) |
| 처리 도중 봇이 죽음 → 재시작 | 오프셋이 확정되지 않아 **같은 update_id가 다시 온다** [2] | 처리한 `update_id`와 콜백 ID를 **고유 키**로 저장한다. 이미 있으면 건너뛴다 |
| 주문 요청을 보냈는데 응답이 끊김 | 주문이 들어갔는지 모른다 | 거래소 주문 ID(`clientOrderId`)를 **신호 ID에서 결정적으로 만든다**(예: `sig-K7Q2M9XT4P-e1`). 재시도 전에 **그 ID로 주문을 조회**한다 |
| 거래소 중복 방지 규칙 | 바이낸스: "A unique id **among open orders**" [23][24] [직접]. 현물 문서는 "Orders with the same newClientOrderID can be accepted **only when the previous one is filled**" [22] [직접]이라고 적는다. 바이비트 `orderLinkId`는 최대 36자이고 "always unique" [25] [직접] | 바이낸스에서는 **체결된 뒤 같은 ID가 다시 받아들여질 수 있다**(현물 문서 기준, 선물도 같은지는 **확인 필요**). 즉 거래소만으로는 중복 체결을 막지 못한다. **DB 상태 전이가 1차 방어**다 |
| 형식 제약 | 바이낸스 선물 `newClientOrderId`: `^[.A-Z:/a-z0-9_-]{1,36}$` [24] [직접] | 신호 ID + 분할 번호가 36자 안에 들어가게 짓는다 |

---

### 2.4 봇 토큰이 유출되면 (분석, 사실 부분은 출처 표기)

| 구분 | 내용 |
|---|---|
| 공격자가 할 수 있는 것 | ① `getUpdates`로 **우리 봇의 업데이트를 가로챈다**. 우리 폴링과 충돌해 409가 난다(01, 검색 요약). ② `setWebhook`으로 업데이트를 **자기 서버로 돌린다**. 그러면 우리 `getUpdates`는 동작하지 않는다 [2][3] [직접]. ③ 봇 이름으로 나에게 **메시지와 가짜 버튼**을 보낸다. 피싱 링크를 보내거나, 버튼 데이터를 마음대로 넣을 수 있다. ④ 봇이 보낸 **기존 메시지를 수정**한다(`editMessage*`는 봇이 보낸 메시지를 고치는 기능이다 [1]). 알림에 표시된 손절가를 바꿔 보이게 할 수 있다 |
| 공격자가 할 수 없는 것 | ⑤ **거래소 주문**. 거래소 키가 서버에 따로 있다. ⑥ **출금**. 키에 출금 권한이 없다(PLAN §4.1). ⑦ 우리가 폴링으로 받는 콜백의 `from.id`를 **내 ID로 위조하는 것**. 폴링에서는 업데이트를 텔레그램 서버에서만 받는다. 내 ID로 된 콜백이 오려면 **내가 실제로 눌러야** 한다. 다만 ③의 가짜 버튼을 내가 누르면 가능하다 → T2·T5 방어가 막는다 |
| 최대 피해 (우리 설계 기준) | 우리 설계에서는 버튼 데이터에 파라미터가 없고, 서버가 만든 신호만 실행하며, 하드 가드와 확인 화면을 서버가 계산한다. 그래서 토큰을 가진 공격자의 최대 효과는 다음 셋이다. ⓐ 알림 방해(서비스 거부) ⓑ 피싱 메시지 ⓒ 매매 정보 열람. **임의 주문은 불가능하다** |
| 탐지 | ① 5분마다 `getWebhookInfo`를 호출한다. URL이 비어 있지 않으면 이상이다 [3] 참고. ② 예상하지 못한 409 Conflict가 난다. ③ 시작할 때 `getMe`로 봇 ID가 설정값과 같은지 본다. ④ 사람이 내가 보내지 않은 봇 메시지를 발견한다 |
| 자동 대응 (fail-closed) | 이상을 탐지하면 **신규 주문을 차단**하고, 대기 신호를 모두 만료시킨다. 경보는 **텔레그램이 아닌 경로**(healthchecks 이메일, 05 §2.9)로 보낸다. 텔레그램 채널이 공격자 손에 있을 수 있기 때문이다 |
| 사람 대응 절차 | ① BotFather에서 토큰을 재발급한다(`/revoke` 등 메뉴 이름과, 이전 토큰이 즉시 무효가 되는지는 **확인 필요**). ② 서버 `.env`의 토큰을 교체하고 재시작한다. ③ `getWebhookInfo`에서 URL이 비었는지 확인한다(공격자가 걸어 둔 웹훅은 `setWebhook`에 빈 URL을 넣어 제거한다 [3] [직접]). ④ 유출 경로를 조사한다: 로그, Git 기록, 백업, 개발 PC. ⑤ 감사 로그에서 그 기간의 콜백을 검토한다 |
| 예방 | 토큰은 `.env`(권한 600)에만 둔다. **HTTP 디버그 로그를 끈다**(토큰이 URL에 있음 [15]). 개발용·운영용 봇을 분리한다. 저장소에 비밀 정보 스캐너를 둔다(05 §2.5) |

---

### 2.5 텔레그램 계정 탈취·폰 분실

| 시나리오 | 공격자가 할 수 있는 것 | 우리 설계에서의 최대 피해 (분석) | 방어 |
|---|---|---|---|
| 계정 탈취 (SIM 스와프로 SMS 코드 가로채기, 로그인 코드 피싱, 세션 탈취) | 다른 기기에서 내 계정으로 로그인해 **대기 중인 신호를 승인**한다. 포지션·잔고 메시지를 읽는다 | **시스템이 만든 신호를 하드 가드 안에서 승인하는 것뿐**이다. 1회 손실은 계좌의 1.2% 이하이고, 하루 -5%에서 차단된다(STRATEGY §8). 즉 "내가 모든 신호를 승인한 것"과 같은 수준이다. 정지 해제·한도 완화는 텔레그램으로 할 수 없게 설계한다(§3.4) | ① 텔레그램 **2단계 인증 비밀번호**를 설정한다. TDLib 명세에 "Represents the current state of **2-step verification**"이 있다 [26] [직접]. 복구 이메일 설정, 로그인 알림, 활성 세션 목록 점검 절차는 **확인 필요**(공식 FAQ 미열람). ② 통신사 **번호이동·유심 변경 제한 서비스**를 신청한다(한국 통신사 제공 여부와 이름은 **확인 필요**). ③ 전화번호 공개 범위를 "아무도 안 보임"으로 둔다(설정 이름은 확인 필요) |
| 폰 분실 (잠금 풀린 상태) | 위와 같다 | 위와 같다 | OS 화면 잠금, 텔레그램 앱 자체 잠금(암호·생체)은 **확인 필요**. **잠금 화면 알림 미리보기를 끈다**. 폰을 잃어버리면 다른 기기에서 세션을 종료하고, 서버에서 신규 주문을 차단한다 |
| 텔레그램 서버가 메시지를 봄 | 봇과의 대화는 텔레그램 클라우드에 저장된다. 봇은 종단간 암호화(비밀 대화)를 쓸 수 없다는 것이 일반적인 이해다 | 매매 정보 노출(금액·방향) | 이 부분은 **확인 필요**다. 메시지에는 **비밀 정보(API 키, 비밀번호)를 절대 넣지 않는다**. 금액은 필요한 만큼만 표시한다 |
| 텔레그램 장애 | 알림·승인을 못 한다 | 기회 손실만 있다. 손절은 거래소에 걸려 있다(05 §2.11) | 대기 신호는 만료된다. 비상 경로는 거래소 웹에서 키 삭제와 포지션 청산이다(05) |

**보안 담당자 관점 정리 (분석)**: 이 설계의 핵심은 채널 인증을 완벽하게 만드는 데 있지 않다. **채널이 뚫려도 피해 상한이 하드 가드로 정해지게** 만드는 데 있다. 그래서 텔레그램 쪽 강화(2단계 인증 등)는 필수 위생으로 하고, 진짜 방어선은 서버의 가드와 거래소 설정(출금 금지 키, IP 제한, 거래소에 걸린 손절)에 둔다. 04·05 문서의 결론과 같다.

---

### 2.6 승인 시점 가격 재검증

#### 2.6.1 왜 필요한가

알림 → 사람이 보고 → 버튼 → 확인 → 주문까지 **수 분에서 최대 15분**(PLAN §4.2 유효시간)이 걸린다. 그동안 가격이 움직이면 다음이 바뀐다.
- 진입가
- 손절 폭(%)
- 손익비
- 수량(손실 한도에 맞춘 크기)

PLAN §4.2에는 "유효시간"만 있고 **가격 조건이 없다**. 01 §2.4도 "체결 직전 가격이 승인가에서 정해진 폭 이상 벗어나면 자동 무효"를 권고했다.

#### 2.6.2 재검증 규칙 (제안값)

기호: E = 계획 진입가, S = 손절가, T1 = 1차 목표가, P = 현재가(**마크 가격**. 청산 계산에 쓰이는 기준가), D = |E − S|

| # | 규칙 | 롱 기준 판정 | 이유 |
|---|---|---|---|
| R1 | **시나리오 종료 확인** | 신호 이후 가격이 S 또는 T1에 **한 번이라도 닿았으면** 무효 (1분봉 고가·저가로 확인) | 이미 끝난 매매에 늦게 올라타지 않는다 |
| R2 | **괴리 한도** | \|P − E\| ≤ min(0.25 × D, E의 0.3%) (제안값) | 계획과 크게 다른 가격에 들어가지 않는다 |
| R3 | **하드 가드 재계산** | P를 진입가로 보고 다시 계산한다. 손절 폭 (P − S) / P ≤ **2%**, 손익비 (T1 − P) / (P − S) ≥ **1.5** | STRATEGY §8 가드를 **클릭 시점 가격**으로 다시 적용한다 |
| R4 | **손절에 너무 가까움** | P − S < 0.3 × D면 무효 (제안값) | 가격이 손절 쪽으로 밀리는 중이면 시나리오가 깨지고 있다는 뜻이다 |
| R5 | **수량 재계산** | 손절 시 손실이 계좌의 1.2% 이하가 되도록 P 기준으로 수량을 다시 정한다. 증거금 20%·레버리지 3배 상한도 다시 확인한다 | 확인 화면에 **새 수량과 예상 최대 손실(USDT·%)**을 표시한다 |
| R6 | **두 번 검사** | 버튼 클릭 때 한 번, [확정] 클릭 때 한 번 더 한다 | 확인 화면을 보는 동안에도 가격이 움직인다 |

#### 2.6.3 계산 예시 (왜 R3가 핵심인가)

롱 신호: E = 100,000, S = 98,600 (손절 폭 1.4%), T1 = 102,100 → 손익비 = 2,100 / 1,400 = **1.50** (가드 경계값)

| 클릭 시 현재가 P | 괴리 | 시장가로 들어갈 때 손절 폭 | 시장가로 들어갈 때 손익비 | 판정 |
|---|---|---|---|---|
| 100,000 | 0% | 1.40% | 1.50 | 통과 |
| 100,100 (+0.1%) | +0.1% | 1.50% | 2,000 / 1,500 = **1.33** | 시장가 **불가** (R3). E에 지정가를 걸면 체결 시 1.50 유지 |
| 100,250 (+0.25%) | +0.25% | 1.65% | 1,850 / 1,650 = **1.12** | 시장가 불가 |
| 99,800 (−0.2%) | −0.2% | 1.20% | 2,300 / 1,200 = 1.92 | 통과 (유리한 쪽). 단 R4: P − S = 1,200 ≥ 0.3 × 1,400 = 420 → 통과 |
| 98,900 (−1.1%) | −1.1% | 0.30% | — | **무효** (R2 괴리 초과, R4 손절 근접) |

→ **교훈 (분석)**: 손익비가 경계값 근처인 신호는 **가격이 조금만 불리해져도 시장가 진입이 가드를 깬다**. 그래서 "계획가에 지정가"가 기본이어야 한다. 괴리 %만 보는 규칙으로는 이 문제를 잡지 못한다. **재계산(R3)이 핵심**이다.

#### 2.6.4 지정가 vs 시장가

| 방식 | 장점 | 단점 | 거래소 기능 (확인한 것) | 우리 판단 |
|---|---|---|---|---|
| **post-only 지정가 @E** | 계획 손익비를 유지한다. 메이커 수수료(04 §2.3) | 체결이 안 될 수 있다. 가격이 되돌아와 체결되면 **불리한 체결**(나쁜 흐름에서만 체결되는 역선택)일 수 있다 | 바이낸스 USDⓈ-M `timeInForce`에 `GTX`(post-only) 있음 [23] [직접]. 바이비트 `PostOnly`: "If the order would be filled immediately when submitted, it will be cancelled" [25] [직접] | **기본값**. STRATEGY §7(W3 지정가 선주문)과 같다 |
| **거래소 쪽 만료 (GTD)** | 봇이 죽어도 거래소가 미체결 주문을 취소한다 | 최소 시간 제약이 있다 | 바이낸스: `GTD`는 `goodTillDate` 필수, "must be greater than the current time **plus 600 seconds**" [24] [직접]. 바이비트 GTD 지원은 **확인 필요** | 지정가에 **GTD = 승인 시각 + 15분**(600초 초과)을 붙인다. **봇 쪽 취소 타이머도 이중으로** 둔다. 재시작하면 오래된 미체결을 정리한다 |
| **가격 상한 IOC 지정가** ("보호된 시장가") | 즉시 체결되고 최악 가격이 정해진다 | 상한을 넘으면 체결이 안 된다(= 안전) | 바이낸스 `IOC` [23] [직접]. 바이비트는 시장가에 `slippageTolerance`(Percent 0.01~10)가 있다 [25] [직접] | "즉시 진입" 버튼은 **R3 재계산을 통과할 때만** 보여 준다. 상한 = P × (1 + 0.1%) (제안값) |
| 순수 시장가 | 체결이 확실하다 | 슬리피지 상한이 없다 | — | **진입에는 쓰지 않는다.** 손절 실행(거래소 손절 주문)에만 쓴다(STRATEGY §7) |
| 바이낸스 `priceMatch` (QUEUE 등) | 가격을 적지 않고 "내 쪽 최우선 호가"로 건다 | `price`와 함께 쓸 수 없다 [24] [직접] | `OPPONENT`, `QUEUE`, `QUEUE_5` 등 [23] [직접] | 2단계 후보. post-only가 "이미 E보다 유리해서" 거절될 때 대안이 될 수 있다. 테스트넷 검증 전에는 쓰지 않는다 |

---

### 2.7 신호 만료와 2단계 확인

#### 2.7.1 상태 머신 (01 §2.4의 제안을 구체화)

```
CREATED ──알림 발송──▶ PENDING ──[승인] 클릭 + 검사 통과──▶ CONFIRMING ──[확정] + 재검사 통과──▶ EXECUTING ──▶ PLACED ──▶ FILLED / PARTIAL / CANCELLED_TTL
   │                     │                                   │                                   │
   │                     ├─[패스]──▶ PASSED                  ├─[취소]──▶ PASSED                  └─오류──▶ FAILED (주문 없음 확인 후)
   │                     ├─시간 초과──▶ EXPIRED              ├─60초 초과──▶ EXPIRED
   │                     ├─가격 규칙 위반──▶ INVALIDATED     └─재검사 실패──▶ INVALIDATED
   └─가드·킬스위치──▶ BLOCKED (알림 안 보냄)
```

- **종료 상태**(PASSED, EXPIRED, INVALIDATED, BLOCKED, FILLED, FAILED 등)에서는 **어떤 전이도 허용하지 않는다**.
- 모든 전이는 "현재 상태가 X일 때만 Y로"라는 원자적 UPDATE로 처리한다(§2.3.4).
- **재시작할 때**:
  - PENDING·CONFIRMING 중 만료 시각이 지난 것 → EXPIRED
  - EXECUTING → 거래소에서 `clientOrderId`로 조회해 PLACED 또는 FAILED로 맞춘다(04 §3 자가 점검과 연결)

#### 2.7.2 타이머 (제안값)

| 타이머 | 값 | 근거 |
|---|---|---|
| 신호 유효시간 | **15분** (PLAN 유지) | PLAN §4.2. 가격 재검증이 추가되므로 더 늘려도 안전성은 유지된다. 하지만 1시간봉 신호의 15분봉 타이밍 조건(STRATEGY §3)이 바뀌므로 유지한다. 페이퍼 단계에서 **클릭까지 걸린 시간 분포**를 보고 조정한다 |
| 확인 화면 유효시간 | **60초** | 확인 화면의 숫자는 그 순간 가격 기준이다. 오래 두면 의미가 없다 |
| 미체결 지정가 | **승인 후 15분** (바이낸스 GTD 최소 600초 초과 조건 충족) | [24] [직접] |
| 만료 처리 | 만료 즉시 메시지를 **수정**해 "만료됨"으로 표시하고 버튼을 지운다 | [1] [직접] |

#### 2.7.3 2단계 확인이 "형식"이 되지 않게 (분석)

- 확인 화면은 "정말 하시겠습니까?"가 아니다. **클릭 순간 새로 계산한 숫자**를 보여 준다. 알림 때와 달라진 값은 강조한다(예: "손익비 1.50 → 1.62").
- 확인 화면 항목:
  - 방향, 주문 방식(지정가 @E / 즉시 IOC 상한)
  - 수량, 명목 금액, 증거금(계좌 %), 레버리지·격리
  - 손절가와 **손절 시 손실(USDT, 계좌 %)**, 목표가
  - 오늘 남은 손실 한도
  - 이 화면이 만료되는 시각
- Slack 버튼은 앱 안에서 뜨는 확인 대화상자(ConfirmObject)를 기본 제공한다 [21] [직접]. 하지만 이 대화상자는 **서버가 새로 계산한 값을 보여 주지 못한다**. 그래서 어느 채널이든 **서버 왕복 방식의 확인 단계**가 필요하다.

---

### 2.8 채널 비교

| 채널 | 서버로 들어오는 포트 | 버튼 → 서버 전달 | 사용자 확인 수단 | 알림 제어 | 비개발자 난이도 | 보안 메모 | 적합도 |
|---|---|---|---|---|---|---|---|
| **텔레그램 봇 (롱 폴링)** | **0** [2][10] | 콜백 쿼리, 64바이트 [1] | `from.id`, `chat.id` | 무음 전송 [6], 채팅별 음소거 | **쉬움**. python-telegram-bot 22.8 [30], 예제·위키가 풍부 [8]~[14] | 콜백 데이터는 조작될 수 있음 [9]. 토큰이 URL에 있음 [15]. 계정 보안은 사용자 몫 | **◎ 권장** |
| Slack (Socket Mode) | **0**. 웹소켓으로 나가는 연결. "SLACK_SIGNING_SECRET is not required", "Running ngrok is not required" [17] [직접], [18] [직접] | 버튼 `value` 최대 2,000자, `action_id` 255자 [21] [직접] | 페이로드의 사용자 ID (분석) | Slack 앱 알림 설정 | 중간. 앱 생성·토큰 2종(xoxb-, xapp-) [18]. **3초 안에 `ack()`** 해야 함 [19] [직접] | 워크스페이스 관리가 필요하다. 무료 요금제 제한(메시지 보관 기간 등)은 **확인 필요** | ○ 가능. 팀 협업이 필요해지면 재검토 |
| Slack (HTTP 방식) | **필요** (공개 HTTPS 요청 URL) | 위와 같음 | 서명 비밀값 검증 | 위와 같음 | 어려움 | 인바운드 노출 | ✕ |
| Discord 봇 (Gateway) | **0**. Gateway로 받으면 공개 주소가 필요 없다. 두 방식은 "mutually exclusive" [20] [직접] | 인터랙션. **3초 안에 첫 응답**, 토큰은 15분 유효 [20] [직접] | 사용자 ID | 서버·채널별 설정 | 중간 | 서버(길드) 구성이 필요. 개인용으로는 과하다 | △ |
| 웹 대시보드 + 패스키 (Tailscale 내부에서만 접속) | 공인 인터넷 0 (Tailscale 사설망 안에서만 열림, 05 §2.4) | 웹 요청 | **패스키**(py_webauthn 3.0.1, 2026-09-25 [28][30] [직접]) | 푸시가 없다 → 알림은 텔레그램이 맡는다 | **어려움**. 웹 서버·세션·WebAuthn 구현 | 가장 강한 인증이다(FIDO2 표준 특성, 원문 미확인). 폰에 Tailscale 앱이 필요하다 | △ → **2단계에서 "권한 완화 작업" 전용**으로 |
| 텔레그램 Mini App | 웹 페이지 호스팅과 결과를 받을 백엔드가 필요 (분석) | initData를 HMAC-SHA256("WebAppData" 키)으로 검증 [27] [직접] | 텔레그램 서명 데이터 | 텔레그램과 같음 | 어려움 | 받는 쪽 서버가 필요하다 → "들어오는 문 0개" 원칙과 충돌 | ✕ (지금은) |
| ntfy 푸시 + 액션 버튼 | `http` 액션은 **폰이 URL로 직접 HTTP 요청**을 보낸다 [29] [직접] → 받을 서버가 필요 | 액션 최대 3개 [29] | 직접 구현 | 우선순위 1~5 [29] [직접] | 중간 | 인바운드가 필요하다(Tailscale로 가릴 수는 있음) | △ (알림 보조용으로만) |
| 전용 네이티브 앱 | 설계에 따라 다름 | 직접 구현 | 직접 구현 | 직접 구현 | **매우 어려움**(앱 스토어 배포 등) | — | ✕ |
| 이메일 / SMS | 0 | 버튼 없음 | — | — | 쉬움 | 승인 채널로는 부적합 | 비상 경보 전용 (05 §2.9) |

**참고 사례**: Vibe-Trading은 텔레그램·Slack·Discord 등 여러 메신저에서 확인을 받는다. 에이전트의 `propose_*`는 "never touch the job store until you confirm". 오류는 "fail closed"로 처리한다 [31] [직접]. freqtrade는 텔레그램을 기본 제어 창구로 쓰고 `authorized_users`로 제어 권한을 제한한다 [16] [직접]. **"제안은 AI, 실행 권한은 사람 확인 뒤 코드"**라는 구조가 공통이다.

---

### 2.9 알림 피로 관리 (24시간 시장)

#### 2.9.1 원칙

- PagerDuty: "An alert is something which **requires a human to perform an action**. Anything else is a notification." "Anything that **wakes up a human** in the middle of the night should be **immediately human actionable**." "Notifications … shouldn't be waking people up under any circumstance." [32] [직접]
- 01 §2.4 자동화 편향(검색 요약): 승인 요청이 많아지면 사람은 **고무도장**(내용을 안 보고 찍는 도장)이 된다.
- freqtrade는 이벤트 종류별로 알림을 `on / silent / off`로 설정할 수 있다 [16] [직접]. 우리도 같은 구조를 쓴다.

#### 2.9.2 알림 등급 (제안)

| 등급 | 예 | 전송 방식 | 방해 금지 시간에는 |
|---|---|---|---|
| **P1 긴급 (사람이 지금 해야 함)** | 포지션에 거래소 손절이 없고 자동 복구도 실패함, 토큰 이상 징후, 킬 스위치 자동 발동, 계좌 이상 | 승인 채팅, **소리 켬**. 추가로 이메일 경보(healthchecks, 05) | **보낸다.** 단 "자동 조치로 해결된 것"은 P2로 내린다(PagerDuty "행동 가능해야 깨운다") |
| **P2 승인 요청** | 매매 신호 | 승인 채팅, 소리 켬, 차트 이미지 + 요약 + 버튼 | **보내지 않는다.** "야간 미발송"으로 기록하고 사후 성과를 집계한다 |
| **P3 결과·상태** | 체결, 익절·손절 체결, 만료, 가드 차단 | 승인 채팅, **무음** [6] | 무음으로 보내거나 아침 요약에 모은다 |
| **P4 정보** | 관망 판정, 하트비트, 비용 | **운영 채팅**(무음, 음소거 권장) 또는 요약에만 | 요약에만 |

#### 2.9.3 방해 금지 시간과 요약 (제안값)

| 항목 | 제안 | 이유 |
|---|---|---|
| 방해 금지 시간 | 기본 **00:30~07:30 KST**. 사용자가 `/quiet` 명령으로 조정 | 잠결에 누르는 승인은 품질이 낮다(분석). 보유 포지션은 거래소 손절이 보호한다(05 §2.11) |
| 방해 금지 중 신호 | 보내지 않는다. 대신 **"미발송 신호" 기록**을 남긴다 | 사후에 "놓친 기회"를 측정해 이 규칙의 비용을 확인한다 |
| 아침 요약 (08:00 KST) | 지난 24시간의 신호(발송/미발송/승인/패스/만료/가드 차단), 포지션과 손절 상태, 실현 손익, 남은 일일 한도, Claude API 비용, 시스템 상태(05의 생존 보고와 합침) | 알림 한 번으로 하루를 파악한다 |
| 주간 요약 (일요일) | 승인율, 결정 시간 중앙값, 만료율, **패스한 신호의 사후 R**, 야간 미발송 신호의 사후 R, 롱·숏 비율(03 §3.2), 비용 | 사람과 Claude의 기여도를 잰다(03 §3.2) |
| 하루 승인 요청 상한 | **6건** (제안값). 넘으면 이후 신호는 기록만 한다 | 고무도장을 막는다. 1시간봉 코드 사전 필터(STRATEGY §2) 뒤라면 보통은 이보다 적을 것이다(추정) |
| 같은 신호 병합 | 같은 시나리오·같은 수준(level)의 신호가 2시간 안에 다시 나오면 **새 메시지 대신 기존 메시지를 수정** | 알림 수를 줄인다 |
| 일시 중지 | `/snooze 2h`: 그동안 P2를 보내지 않음 | 회의·운전 중 |
| 폰 설정 | 텔레그램에서 **승인 채팅만 알림 켜기**, 운영 채팅은 음소거. OS 방해 금지 모드의 예외 설정은 사용자 선택 | — |

#### 2.9.4 "고무도장" 점검 지표

| 지표 | 경고 기준 (제안값) | 의미 |
|---|---|---|
| 승인율 | 4주 연속 > 90% | 거의 다 승인한다 → 사람 판단이 기여하지 않을 수 있다 |
| 결정 시간 중앙값 | < 15초 | 내용을 읽지 않았을 가능성이 있다 |
| 패스한 신호의 사후 평균 R vs 승인한 신호 | 패스 쪽이 더 좋음 | 사람의 거절이 오히려 손해다 |
| 만료율 | > 50% | 알림 시간대나 빈도가 생활과 맞지 않는다 |

패스할 때 **이유 버튼**(근거 약함 / 타이밍 늦음 / 개인 사정 / 기타)을 한 번 누르게 하면 이 분석이 쉬워진다. 누르지 않아도 된다.

---

### 2.10 기존 기획(PLAN·STRATEGY)에 대한 검토

| 위치 | 기존 내용 | 판정 | 근거 | 수정 제안 |
|---|---|---|---|---|
| PLAN §3.1 표 | Slack은 "외부 공개 서버(HTTPS) 필요", "인바운드 웹훅 수신 필요" | **틀림** | Slack Socket Mode는 웹소켓으로 나가는 연결만 쓴다. 서명 비밀값과 ngrok이 필요 없다 [17][18] [직접] | "Slack도 Socket Mode면 인바운드 불필요. 텔레그램을 고른 이유는 개인용·모바일·단순함"으로 고친다. **결론(텔레그램)은 유지** |
| PLAN §2 ④ | 버튼 [롱] [숏] [패스] | **개선 필요** | Claude가 롱이라고 했는데 [숏]을 주면, 분석·손절 근거가 없는 역방향 주문 길이 열린다. STRATEGY §1.4 "역추세 금지"와도 충돌한다 (분석) | **[분석 방향 승인] [패스]** 두 개(+ 선택: [상세]). 반대 방향 매매는 시스템 밖의 수동 매매로 본다 |
| PLAN §4.2 화이트리스트 | "허용된 사용자 ID(본인)만" | **보완** | 그룹에 봇이 들어가면 전원이 누를 수 있다 [16]. 사용자명은 바뀐다 | **숫자 사용자 ID + 채팅 ID + 1:1 채팅만** 허용. 그룹 참여 금지 |
| PLAN §4.2 유효시간 | 15분 지나면 만료 | **유지 + 보완** | 시간만으로는 가격 변화를 못 잡는다(§2.6.3) | **클릭·확정 두 시점의 가격 재검증(R1~R6)**을 추가한다 |
| PLAN §4.2 1회성 | "같은 신호는 한 번만 주문" | **보완** | 같은 업데이트가 다시 오고 [2], 바이낸스 주문 ID 중복 방지는 미체결 주문 사이에서만 보장된다 [22][24] | DB 원자적 상태 전이 + update_id·콜백 ID 기록 + 결정적 `clientOrderId` + 재시도 전 조회 |
| PLAN §4.2 2단계 확인 | "주문 내용 확인 → [확인]" | **유지 + 보완** | 형식적 확인은 효과가 작다 (01 §2.4 자동화 편향) | 확인 화면은 **서버가 현재가로 새로 계산**하고 60초 뒤 만료. 달라진 값을 강조 |
| PLAN §4.3 킬 스위치 | 텔레그램 `/stop` | **유지 + 보완** | 계정 탈취 시나리오(§2.5) | `/stop`은 오래된 명령이어도 실행한다. **재개(`/resume`)는 텔레그램에서 불가**, 서버에서만 |
| PLAN §3.3 | "관망이면 알림 생략" (추가 옵션) | **채택 권장** | PagerDuty 원칙 [32] | 기본값으로 올린다. 방해 금지 시간·하루 상한도 추가 |
| PLAN §4.4 감사 로그 | 버튼 클릭(누가, 언제) | **보완** | 사후 분석(§2.9.4)과 사고 조사에 필요 | 콜백 ID, update_id, `from.id`, `chat.id`, 클릭 시각, 그때 가격, 재검증 결과, 결정 소요 시간, 패스 이유 |
| STRATEGY §7 | 유효시간 뒤 미체결분 자동 취소 | **보완** | 봇이 죽으면 취소도 못 한다 | 거래소 **GTD**(바이낸스 600초 초과 조건 [24]) + 봇 취소 이중화 + 재시작 시 정리 |
| PLAN §5 | python-telegram-bot | **유지** | 22.8(2026-06-12), Python ≥ 3.10 [30] [직접]. 위키 문서가 풍부하다 [8]~[13] | 대안은 aiogram 3.31.0 [30]. 바꿀 이유는 없다 |

---

## 3. 우리 시스템에 대한 시사점과 권고

### 3.1 권장 채널 (결론)

| 역할 | 채널 | 단계 |
|---|---|---|
| 신호 승인·결과 보고 | **텔레그램 봇, 롱 폴링, 1:1 채팅** ("승인 채팅") | 3단계부터 |
| 운영 로그·오류 | 텔레그램 **두 번째 채팅**(무음·음소거). 봇 하나로 채팅만 나눈다. 토큰 하나당 폴러 하나 제약이 있으므로 봇을 둘로 늘릴 필요는 없다(분석) | 3단계부터 |
| 비상 경보 (텔레그램과 독립) | healthchecks.io 이메일 (05 §2.9) | 6단계 |
| 권한 완화 작업 (정지 해제, 한도 변경) | 서버 SSH(Tailscale, 05). 2단계 후보: Tailscale 내부 웹 대시보드 + 패스키 | 1단계: SSH만 |
| Slack·Discord | **쓰지 않는다** | — |

### 3.2 승인 흐름 설계

```
[분석 완료] 코드 사전 필터 → Claude(JSON) → 하드 가드 ① (STRATEGY §8)
     │  통과 & 방해 금지 시간 아님 & 하루 상한 이내
     ▼
[① 알림]  차트 이미지 + 요약(캡션 ≤1024자) + 반대 근거 + 무효화 조건
          버튼: [▲ 롱 승인]  [패스]  (+[상세])      상태 = PENDING, 만료 15분
     │ 클릭
     ▼
[② 1차 검사]  answerCallbackQuery → 사용자·채팅 ID → 형식 → DB 상태 → 킬스위치·일일한도
              → 가격 재검증 R1~R5 (현재 마크 가격)
     │ 통과                                   │ 실패: 팝업으로 사유 + 메시지 수정(버튼 제거)
     ▼
[③ 확인 화면]  서버가 새로 계산한 수량·손실·손익비, 달라진 값 강조
               버튼: [확정 (지정가 @E)]  [즉시 진입 (IOC 상한)]*  [취소]
               *R3 통과 시에만 표시        상태 = CONFIRMING, 만료 60초
     │ [확정]
     ▼
[④ 최종 검사]  원자적 전이 CONFIRMING→EXECUTING (1개 행만 성공) → 가격 재검증 한 번 더
     ▼
[⑤ 주문]  clientOrderId = sig-<ID>-e1 → 진입(post-only GTX + GTD 15분)
          → 체결 시 거래소 손절·익절 등록 → 손절 존재 확인 (04 §3, 05 §2.11)
     ▼
[⑥ 보고]  거래소 응답 값으로 결과 보고(무음) → 원 메시지 수정 "승인됨 hh:mm KST"
          → 감사 로그 (콜백ID, update_id, from.id, chat.id, 가격, 검사 결과, 소요 시간)
```

- 재시작할 때: 밀린 업데이트를 버리지 않는다. `/stop`은 실행하고, 승인 클릭은 만료 규칙으로 거절한다. EXECUTING 상태는 거래소 조회로 맞춘다.
- 모든 실패는 **주문 없음**으로 끝난다(fail-closed, 01 §2.4·03 §2.5).

### 3.3 메시지 모양 (예시, 숫자는 가상)

```
[BTC/USDT 1H] 롱 후보 L1 기준가 지지 눌림 · 확신 체크 4/5
진입 100,000 (지정가) · 손절 98,600 (-1.4%) · 목표 102,100 · 손익비 1.50
반대 근거: 4H 거래량 감소 중
무효화: 1H 종가 98,600 아래 마감
유효: 21:15 KST까지
[▲ 롱 승인]   [패스]
```

```
확인 (60초, 21:08:30까지)  현재가 100,050 (+0.05%)
지정가 100,000 · 수량 0.012 BTC · 명목 1,200 USDT · 증거금 400 (계좌 20%) · 3x 격리
손절 시 손실 -16.8 USDT (계좌 -0.84%) · 오늘 남은 한도 -5.0%
[확정 (지정가)]
[취소]
```

(손익비가 경계값이라 R3에서 "즉시 진입"이 빠진 예다.)

### 3.4 명령 권한: "텔레그램은 조이는 방향만" (분석)

| 명령 | 텔레그램에서 | 확인 단계 | 이유 |
|---|---|---|---|
| 신호 승인·패스 | 가능 | 2단계 | 가드 안에서만 실행된다 |
| `/status`, `/positions` | 가능 | 없음 | 조회만 한다 (`protect_content` 켬) |
| `/pause` (신규 진입 중지) | 가능 | 없음 | 위험을 줄인다. freqtrade `/stopentry`와 같은 개념 [16] |
| `/stop` (신규 차단 + 미체결 취소) | 가능 | **없음 (즉시)** | 비상 시 빨라야 한다 |
| `/flat` (보유 포지션 전부 청산) | 가능 | 2단계 | 되돌릴 수 없다 |
| `/quiet`, `/snooze` | 가능 | 없음 | 알림만 바꾼다 |
| `/resume` (정지 해제) | **불가** → 서버에서 | — | 계정 탈취 시 공격자가 풀 수 없게 한다 |
| 레버리지·한도·손절 폭 변경 | **불가** → 서버 설정 파일 + 재배포 | — | 완화 방향 변경은 사람 검토(PR)를 거친다(PLAN §6) |
| 자유 문장으로 Claude에게 지시 | **불가** (1단계) | — | 프롬프트 인젝션과 임의 주문 경로를 막는다(03 §2.3) |

### 3.5 설정값 제안 (모두 제안값)

| 항목 | 값 |
|---|---|
| 수신 방식 | 롱 폴링, `allowed_updates = ["message", "callback_query"]` |
| 허용 | 숫자 사용자 ID 1개 + 승인 채팅 ID + 운영 채팅 ID, private 채팅만 |
| callback_data | `v1:<동작>:<랜덤 신호 ID 10자>[:<HMAC 12자>]`, ASCII, ≤ 40바이트 |
| 신호 유효 / 확인 유효 / 미체결 | 15분 / 60초 / 15분(GTD, 600초 초과) |
| 가격 괴리 한도 | min(0.25 × 손절 거리, 0.3%) + 가드 재계산 |
| 즉시 진입 가격 상한 | 현재가 ± 0.1% (IOC) |
| 방해 금지 | 00:30~07:30 KST |
| 하루 승인 요청 상한 | 6건 |
| 웹훅 점검 | 5분마다 `getWebhookInfo`, URL이 생기면 신규 주문 차단 + 이메일 |
| 로그 | HTTP 디버그 로그 끔(토큰 노출 방지) |

### 3.6 개발 단계별 적용 (PLAN §6과 대응)

| PLAN 단계 | 이 문서의 적용 |
|---|---|
| 0. 준비 | 텔레그램 **2단계 인증 비밀번호** 설정, 개발용·운영용 봇 2개 생성, 승인·운영 채팅 ID 확인. 통신사 유심 보호 서비스 확인 |
| 3. 알림 | 롱 폴링, 화이트리스트, 버튼 2개([승인] [패스]), 무음 등급, 메시지 수정으로 만료 표시. **주문 기능은 아직 없다** |
| 4. 모의주문 | 상태 머신, 확인 화면, 가격 재검증 R1~R6, `clientOrderId`, GTX + GTD를 **테스트넷**에서 확인 |
| 5. 리스크 | 멱등성 시험(두 번 클릭, 처리 중 강제 종료 후 재시작, 응답 끊김), 웹훅 탐지, `/stop` 비대칭 권한 |
| 6. 배포 | 이메일 비상 경로, 방해 금지 시간, 아침 요약 |
| 7. 검증 | 승인율·결정 시간·만료율·패스 신호 사후 R·야간 미발송 사후 R 기록 (§2.9.4) |

**꼭 해 볼 시험 (5단계)**
1. 버튼을 1초 안에 두 번 누른다 → 주문이 1건이어야 한다.
2. [확정] 직후 봇을 강제로 끄고 다시 켠다 → 중복 주문이 없어야 하고, 상태가 거래소와 맞아야 한다.
3. 다른 텔레그램 계정으로 봇에게 `/start`와 버튼 데이터를 보낸다 → 무시되고 경고가 남아야 한다.
4. 16분 뒤에 [승인]을 누른다 → "만료" 팝업이 떠야 한다.
5. 테스트 봇에 웹훅을 걸어 본다 → 폴링 실패를 탐지하고, 신규 주문이 차단되고, 이메일 경보가 가야 한다.
6. 가격이 E + 0.1%일 때 누른다 → 손익비 1.5 경계 신호에서 "즉시 진입" 버튼이 없어야 한다.

### 3.7 사용자 결정이 필요한 질문

1. PLAN의 [롱] [숏] [패스]를 **[분석 방향 승인] [패스]**로 줄이는 데 동의하시나요?
2. 방해 금지 시간은 몇 시부터 몇 시까지로 할까요? 그 시간의 신호는 **아예 보내지 않는** 쪽에 동의하시나요?
3. "즉시 진입(IOC 상한)" 버튼을 둘까요, 아니면 **지정가만** 쓸까요? (지정가만 쓰는 쪽이 단순하고 계획 손익비를 지킵니다)
4. 정지 해제(`/resume`)를 텔레그램에서 막고 서버에서만 하는 데 동의하시나요? 불편하면 2단계에서 패스키 대시보드를 만들 수 있습니다.
5. 하루 승인 요청 상한(제안 6건)이 적절한가요?
6. 패스할 때 이유 버튼을 보여 줄까요? (분석에는 도움이 되지만 누를 게 하나 늘어납니다)

### 3.8 확인 필요 목록

| # | 항목 | 확인 방법 |
|---|---|---|
| 1 | 텔레그램 서버의 업데이트 보관 기간(24시간이라는 문구) | core.telegram.org/bots/api "Getting updates" 절 직접 열람 |
| 2 | `answerCallbackQuery` 응답 제한 시간 | 공식 문서 또는 테스트 봇으로 실험 |
| 3 | 채팅 하나당 전송 한도(초당 1건 등) | 공식 FAQ |
| 4 | BotFather의 토큰 재발급 메뉴, 이전 토큰이 즉시 무효가 되는지, 그룹 참여 금지 설정 | BotFather에서 직접 확인 |
| 5 | 텔레그램 2단계 인증의 복구 이메일, 로그인 알림, 활성 세션 종료, 앱 암호 잠금 | 텔레그램 앱 설정에서 직접 확인 |
| 6 | 봇 대화의 종단간 암호화 불가 여부 | 공식 FAQ |
| 7 | 한국 통신사의 유심 변경·번호이동 제한 서비스 이름과 신청 방법 | 통신사 고객센터 |
| 8 | 바이낸스 **선물**에서 체결된 주문과 같은 `newClientOrderId`를 다시 받아 주는지(현물 문서는 "허용") | 테스트넷 실험 |
| 9 | 바이비트·OKX의 GTD 지원 여부 | 각 거래소 API 문서 (04의 어댑터 설계에 반영) |
| 10 | Slack 무료 요금제의 메시지 보관 제한 | Slack 요금제 페이지 (채택하지 않으므로 우선순위 낮음) |

---

## 4. 출처 목록

**[직접] = 원문을 직접 열어 확인**

1. 텔레그램 Bot API 명세 사본(Bot API 10.3, 2026-08-24): callback_data 1-64 bytes, CallbackQuery, getUpdates offset, setWebhook, disable_notification, protect_content, editMessageReplyMarkup, deleteMessage 48시간 — https://raw.githubusercontent.com/PaulSonOfLars/telegram-bot-api-spec/main/api.json [직접]
2. aiogram `GetUpdates` (Bot API 문구 사본: 웹훅 설정 시 동작 안 함, 오프셋 재계산, 확정 방식, allowed_updates) — https://raw.githubusercontent.com/aiogram/aiogram/dev-3.x/aiogram/methods/get_updates.py [직접]
3. aiogram `SetWebhook`, `AnswerCallbackQuery` (포트 443/80/88/8443, 재시도, 비밀 헤더, 응답 문구 0-200자) — https://raw.githubusercontent.com/aiogram/aiogram/dev-3.x/aiogram/methods/set_webhook.py , https://raw.githubusercontent.com/aiogram/aiogram/dev-3.x/aiogram/methods/answer_callback_query.py [직접]
4. aiogram `CallbackQuery` (진행 표시줄 NOTE, "can contain no callback buttons with this data") — https://raw.githubusercontent.com/aiogram/aiogram/dev-3.x/aiogram/types/callback_query.py [직접]
5. aiogram `Update` (update_id 순차, 반복 업데이트 무시) — https://raw.githubusercontent.com/aiogram/aiogram/dev-3.x/aiogram/types/update.py [직접]
6. aiogram `SendMessage` (본문 1-4096자, 무음, 전달 방지) — https://raw.githubusercontent.com/aiogram/aiogram/dev-3.x/aiogram/methods/send_message.py [직접]
7. aiogram `SendPhoto` (캡션 0-1024자, 사진 10MB) — https://raw.githubusercontent.com/aiogram/aiogram/dev-3.x/aiogram/methods/send_photo.py [직접]
8. python-telegram-bot 위키 "Avoiding flood limits" — https://raw.githubusercontent.com/wiki/python-telegram-bot/python-telegram-bot/Avoiding-flood-limits.md [직접]
9. python-telegram-bot 위키 "Arbitrary callback_data" (64바이트, 클라이언트가 보내 조작 가능, 캐시 1024, 재시작 시 버튼 무효) — https://raw.githubusercontent.com/wiki/python-telegram-bot/python-telegram-bot/Arbitrary-callback_data.md [직접]
10. python-telegram-bot 위키 "Webhooks" (공개 IP, HTTPS, 포트, secret_token, "Don't do it simply because it sounds cool") — https://raw.githubusercontent.com/wiki/python-telegram-bot/python-telegram-bot/Webhooks.md [직접]
11. python-telegram-bot 위키 FAQ (그룹 privacy mode) — https://raw.githubusercontent.com/wiki/python-telegram-bot/python-telegram-bot/Frequently-Asked-Questions.md [직접]
12. python-telegram-bot 위키 "Frequently requested design patterns" (사용자 제한, 한 버튼 다중 콜백) — https://raw.githubusercontent.com/wiki/python-telegram-bot/python-telegram-bot/Frequently-requested-design-patterns.md [직접]
13. python-telegram-bot 인라인 키보드 예제 — https://github.com/python-telegram-bot/python-telegram-bot/blob/master/examples/inlinekeyboard.py (01 문서 인용, 검색 요약)
14. python-telegram-bot `Application.run_polling` (drop_pending_updates) — https://raw.githubusercontent.com/python-telegram-bot/python-telegram-bot/master/src/telegram/ext/_application.py [직접]
15. python-telegram-bot `Bot` (base_url 기본값, 토큰을 URL 뒤에 붙임) — https://raw.githubusercontent.com/python-telegram-bot/python-telegram-bot/master/src/telegram/_bot.py [직접]
16. freqtrade 텔레그램 문서 (notification_settings on/silent/off, authorized_users, 그룹 경고, /stopentry vs /stop) — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/telegram-usage.md [직접]
17. Slack bolt-python README (Socket Mode: 서명 비밀값·ngrok 불필요) — https://github.com/slackapi/bolt-python [직접]
18. bolt-python Socket Mode 문서 — https://raw.githubusercontent.com/slackapi/bolt-python/main/docs/english/concepts/socket-mode.md [직접]
19. bolt-python acknowledge 문서 ("only have 3 seconds") — https://raw.githubusercontent.com/slackapi/bolt-python/main/docs/english/concepts/acknowledge.md [직접]; actions 문서 — https://raw.githubusercontent.com/slackapi/bolt-python/main/docs/english/concepts/actions.md [직접]
20. Discord API 문서 "Receiving and Responding" (Gateway vs 엔드포인트 상호 배타, 3초, 토큰 15분) — https://raw.githubusercontent.com/discord/discord-api-docs/main/developers/interactions/receiving-and-responding.mdx [직접]
21. python-slack-sdk `ButtonElement` (value 2000자, action_id 255자, confirm 대화상자) — https://raw.githubusercontent.com/slackapi/python-slack-sdk/main/slack_sdk/models/blocks/block_elements.py [직접]
22. 바이낸스 현물 REST API 문서 (newClientOrderId 재사용 규칙, recvWindow) — https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md [직접]
23. 바이낸스 USDⓈ-M 선물 공식 SDK enum (timeInForce GTC/IOC/FOK/GTX/GTD/RPI, priceMatch) — https://raw.githubusercontent.com/binance/binance-connector-python/master/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/models/enums.py [직접]
24. 바이낸스 USDⓈ-M 선물 공식 SDK `new_order` (newClientOrderId 형식, goodTillDate 600초, priceMatch) — https://raw.githubusercontent.com/binance/binance-connector-python/master/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/trade_api.py [직접]
25. 바이비트 v5 주문 생성 문서 (orderLinkId, PostOnly, slippageTolerance, TP/SL) — https://raw.githubusercontent.com/bybit-exchange/docs/master/docs/v5/order/create-order.mdx [직접]
26. TDLib API 명세 (passwordState: 2-step verification) — https://raw.githubusercontent.com/tdlib/td/master/td/generate/scheme/td_api.tl [직접]
27. aiogram Mini App initData 검증 (HMAC-SHA256, "WebAppData") — https://raw.githubusercontent.com/aiogram/aiogram/dev-3.x/aiogram/utils/web_app.py [직접]
28. py_webauthn README (서버 측 WebAuthn, Python 3.10+) — https://github.com/duo-labs/py_webauthn [직접]
29. ntfy 발행 문서 (액션 버튼 view/broadcast/http/copy, 최대 3개, 우선순위 1-5) — https://raw.githubusercontent.com/binwiederhier/ntfy/main/docs/publish.md [직접]
30. PyPI 버전 정보 (2026-09-29 조회): python-telegram-bot 22.8 (2026-06-12), aiogram 3.31.0 (2026-08-26), slack-bolt 1.30.0 (2026-07-15), webauthn 3.0.1 (2026-09-25), ccxt 4.5.84 (2026-09-24) — https://pypi.org/pypi/python-telegram-bot/json , https://pypi.org/pypi/aiogram/json , https://pypi.org/pypi/slack-bolt/json , https://pypi.org/pypi/webauthn/json , https://pypi.org/pypi/ccxt/json [직접]
31. HKUDS/Vibe-Trading README (propose/confirm, mandate, fail closed, 다중 메신저 확인) — https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/README.md [직접]
32. PagerDuty Incident Response 문서 "Alerting Principles" — https://raw.githubusercontent.com/PagerDuty/incident-response-docs/master/docs/oncall/alerting_principles.md [직접]
33. 텔레그램 Bot API 서버 README (logOut, 로컬 서버) — https://raw.githubusercontent.com/tdlib/telegram-bot-api/master/README.md [직접] (참고용)

**다른 리서처 문서에서 가져온 것**
34. 토큰 하나당 폴러 하나(409 Conflict) — [01_existing_systems.md](./01_existing_systems.md) §2.4 (검색 요약: https://github.com/python-telegram-bot/python-telegram-bot/issues/1143 , https://github.com/python-telegram-bot/python-telegram-bot/issues/4499)
35. 사람 승인 패턴·자동화 편향·킬 스위치 정의 — [01_existing_systems.md](./01_existing_systems.md) §2.4 (일부 검색 요약)
36. 들어오는 문 0개, Tailscale, healthchecks 비상 경로, 토큰 로그 마스킹, 재시작 점검 — [05_infra_ops.md](./05_infra_ops.md) §1, §2.4~§2.11
37. 메이커·테이커 수수료, 거래소 어댑터·자가 점검 — [04_exchanges_regulation.md](./04_exchanges_regulation.md) §2.3, §3
38. 실패 상태 처리, 롱·숏 편향 점검, 기여도 측정 — [03_llm_trading.md](./03_llm_trading.md) §2.5, §3.2
