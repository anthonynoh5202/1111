# 05. 운영 환경(인프라·운영) 조사: 24시간 안전하게 돌리는 방법

> 작성일: 2026-09-29 · 작성: 리서처(infra_ops) · 상태: 조사 보고서 (코드 없음, 설치 없음)
> 관련 문서: [docs/PLAN.md](../../docs/PLAN.md) (기획 v0.1), [docs/STRATEGY.md](../../docs/STRATEGY.md) (차트 기법 v0.2), [01_existing_systems.md](./01_existing_systems.md), [03_llm_trading.md](./03_llm_trading.md)
> 표기: **[직접]** = GitHub 원문, code.claude.com 문서를 직접 열어 확인했다 · **(검색 요약)** = 웹 검색 결과 요약으로만 확인했다(원문 미열람) · **확인 필요** = 확인하지 못했다 · **(추정)** = 내가 계산하거나 추론한 값이다

---

## 1. 핵심 요약 (5줄)

1. **서버는 AWS Lightsail 도쿄(또는 서울) 리전의 리눅스 2GB 요금제(월 $12)에 무료 고정 IP를 붙여 쓰는 것을 권한다.** 결정 기준은 값이 아니다. **거래소가 막지 않는 나라의 고정 IP**인지가 기준이다.
   - 미국 IP는 바이낸스에서 451, 바이비트에서 403 오류가 난다. 그래서 미국 리전만 무료인 **GCP 무료 티어는 탈락**이다.
   - **Oracle 무료 티어**는 2026-08부터 A1 한도가 절반으로 줄었다. 또 "7일간 CPU 사용률 95퍼센타일이 15% 미만이면 회수할 수 있다"는 규정이 있는데, 대부분 쉬고 있는 우리 봇이 정확히 이 조건에 해당한다.
   - **집 PC와 라즈베리파이**는 유동 IP라서 IP 화이트리스트와 충돌한다.
2. **지연시간은 결정 요인이 아니다.** 바이낸스 매칭 엔진은 AWS 도쿄에 있다. 서울에서는 약 72ms, 도쿄에서는 한 자릿수 ms 걸린다(검색 요약). 하지만 우리 시스템은 1시간봉을 쓰고 사람이 수십 초에서 수 분 뒤에 승인한다. 이 차이는 결과에 영향을 주지 않는다.
3. **보안 원칙은 "서버로 들어오는 문 0개"다.** 텔레그램은 폴링으로 받고, 외부에서 들어오는 연결은 모두 막고, SSH는 Tailscale로만 연다.
   - Docker는 UFW 방화벽을 **우회**한다. 그러니 포트를 외부에 공개하지 않는다 [직접].
   - 비밀 정보는 `.env`(권한 600)에 두고, 나중에 sops+age 암호화로 옮긴다.
   - 실제 방어선은 네 가지다: 출금 금지 키, IP 화이트리스트, 봇용 자금 분리, **거래소에 걸어 둔 손절 주문**.
4. **운영 방식:**
   - Docker Compose로 실행한다. 자동 재시작을 켜고 로그 크기를 제한한다.
   - chrony로 시계를 맞춘다. recvWindow(요청 유효 시간)는 5000으로 두고 **늘리지 않는다**.
   - 알림은 세 겹이다: 외부 데드맨 스위치(healthchecks.io 무료), 텔레그램 에러 알림, 매일 아침 생존 보고.
   - SQLite는 매일 암호화 백업을 떠서 서버 밖에 보관한다.
   - 봇이 재시작할 때마다 "모든 포지션에 거래소 손절이 걸려 있는지" 점검한다.
   - 배포는 **사람이 직접** 한다. CI는 테스트만 자동으로 돌린다.
5. **월 총비용은 약 $23~31(약 3.2만~4.3만 원)이다.** 서버 $12, 백업·스냅샷 약 $1, Claude API $10~18(코드 사전 필터 사용 시, 03 문서)을 더한 값이다.
   - Claude를 매시간 호출하면 $55~86이다.
   - Lightsail 신규 가입자는 첫 3개월 서버가 무료다(검색 요약).
   - **주의:** 2026-09 현재 한국 정부가 해외 거래소 접속 차단 기준을 논의하고 있다. 실거래 전에 법률 검토가 필요하다. **서버 위치로 차단을 우회하는 설계는 권하지 않는다.**

---

## 2. 본문

### 2.0 조사 방법과 한계

| 항목 | 내용 |
|---|---|
| 웹 검색 | 서로 다른 검색어로 36회 검색했다(영어·한국어). 36회째에 세션 전체 검색 한도(200회, 다른 리서처와 공유)에 걸려 멈췄다. 그 뒤에는 허용된 원문(GitHub, code.claude.com)만 열어서 확인했다 |
| 직접 확인 | 바이낸스 REST 문서의 시간 규칙(GitHub), 바이비트 문서 원본(GitHub), freqtrade 문서(거래소·설치·Docker), sops, ufw-docker, Uptime Kuma, Healthchecks 저장소, freqtrade 이슈 #12610, Claude Code 클라우드 세션·환경 문서 |
| 차단된 곳 | docs.aws.amazon.com, 언론사(asiae 등), binance.com, developers.binance.com, 오라클 문서. 모두 **검색 요약**으로만 봤다. 차단은 우회하지 않았다 |
| 한계 | 클라우드 요금은 수시로 바뀐다. 특히 Hetzner는 2026년에 두 번 인상했다. EC2와 GCP의 도쿄·서울 요금은 검색 한도 때문에 확인하지 못했다(**확인 필요**). 가입 직전에 공식 요금표를 다시 확인할 것 |

### 2.1 용어 풀이 (처음 한 번만)

| 용어 | 뜻 |
|---|---|
| **VPS / 인스턴스** | 클라우드 회사가 빌려주는 가상 서버 한 대. 24시간 켜 둔다 |
| **리전(region)** | 클라우드 데이터센터가 있는 지역. 예: 도쿄 `ap-northeast-1`, 서울 `ap-northeast-2` |
| **고정 IP(static IP)** | 서버를 껐다 켜도 바뀌지 않는 인터넷 주소. 거래소 IP 화이트리스트에 등록하려면 필요하다 |
| **IP 화이트리스트** | 등록한 IP에서 온 요청만 API 키로 받아 주는 거래소 설정. 키가 새어도 다른 곳에서는 못 쓴다 |
| **지연시간(latency)** | 요청이 거래소에 갔다가 돌아오는 데 걸리는 시간(ms = 1/1000초) |
| **인바운드 / 아웃바운드** | 밖에서 서버로 들어오는 연결 / 서버에서 밖으로 나가는 연결 |
| **하드닝(hardening)** | 서버에서 불필요한 문을 닫고 설정을 조여 공격 면적을 줄이는 작업 |
| **SSH** | 서버에 원격으로 접속해 명령을 치는 방법. 기본 포트는 22 |
| **UFW** | 우분투 리눅스의 간단한 방화벽 도구 |
| **fail2ban** | 로그인 실패를 반복하는 IP를 자동으로 차단하는 도구 |
| **NTP / chrony** | 서버 시계를 표준 시간에 맞추는 규약 / 그 프로그램 |
| **recvWindow** | 거래소가 "이 요청은 몇 ms 안에 도착해야 유효하다"고 보는 허용 시간 |
| **Docker / 컨테이너** | 프로그램과 필요한 부품을 한 상자(이미지)에 담아 어디서든 똑같이 실행하는 기술 |
| **Docker Compose** | 여러 컨테이너의 실행 설정을 파일 하나(`compose.yaml`)로 관리하는 도구 |
| **systemd** | 리눅스에서 프로그램을 서비스로 등록해 부팅 시 자동 실행하고 죽으면 재시작하는 관리자 |
| **CI/CD** | 코드를 올릴 때마다 자동으로 테스트(CI)하고 배포(CD)하는 흐름 |
| **데드맨 스위치** | 봇이 주기적으로 "살아 있음" 신호를 보내다가 신호가 끊기면 외부 서비스가 알림을 주는 방식 |
| **RPO / RTO** | 장애 시 잃어도 되는 데이터 기간 / 복구에 걸려도 되는 시간 |
| **스냅샷** | 서버 디스크 전체를 특정 시점 그대로 복사해 둔 것 |
| **런북(runbook)** | 장애가 났을 때 순서대로 따라 할 수 있게 적어 둔 대응 절차서 |

---

### 2.2 거래소 쪽 제약: 호스팅보다 먼저 봐야 할 것

서버를 어디에 둘지는 **거래소가 어떤 IP를 막는지**가 먼저 결정한다. 가격과 성능은 그다음이다.

#### 2.2.1 거래소별 제약 비교

| 항목 | 바이낸스 (USDⓈ-M 선물) | 바이비트 | OKX |
|---|---|---|---|
| 매칭 엔진 위치 | **AWS 도쿄(ap-northeast-1)** (검색 요약) | **AWS 싱가포르, AZ ID apse1-az3** [직접: 바이비트 FAQ 원본] | 알리바바 클라우드 홍콩. AWS 경유 주소 `aws.okx.com`도 있음 (검색 요약) |
| 서버 IP 국가 차단 | 451 오류 "Service unavailable from a restricted location". freqtrade 문서: "현재 알려진 차단 국가는 **캐나다, 말레이시아, 네덜란드, 미국**(전체 목록 아님)" [직접]. GCP·Streamlit·PythonAnywhere·Kaggle 같은 미국 클라우드에서 실패 사례가 많음 (검색 요약) | 미국·중국 본토 IP는 403 (검색 요약. 단, 바이비트 문서 원본 `guide.mdx`에서는 해당 문구를 찾지 못함 → **확인 필요**). 일부 클라우드 IP 대역을 CDN(CloudFront)이 막은 사례도 있음 (검색 요약). 네덜란드·홍콩 사용자는 별도 도메인을 쓰라는 안내 [직접] | **확인 필요** |
| 계정 기준 제한 | KYC(본인 인증) 거주국이 제한 국가면 IP와 무관하게 막힘 (검색 요약) | 이용약관상 제외 14개 지역에 미국·싱가포르·캐나다·홍콩 포함 (검색 요약) | 확인 필요 |
| IP 미등록 키 정책 | 과거에는 "IP 미등록 키는 90일 뒤 거래 권한 해제·삭제" 규정이 있었음. **2026-08-06부터 적용하지 않는다**는 요약이 있음 (검색 요약, TradersPost. 공식 공지 원문 미확인 → **확인 필요**) | IP 미등록 키는 **90일 뒤 만료** (검색 요약) | 거래·출금 권한이 있는 IP 미등록 키는 **14일 미사용 시 자동 삭제** (검색 요약) |
| IP 화이트리스트 | 키당 **최대 30개**, 개별 IP만 가능(대역·와일드카드 불가) (검색 요약). 바이낸스는 권한과 무관하게 **모든 키에 화이트리스트를 강력 권장** (검색 요약: 바이낸스 보안 블로그). IPv6 지원 여부는 **확인 필요** | 지원 (세부 확인 필요) | 지원 |
| 키 방식 | **Ed25519 자체 생성 키**를 "성능·보안이 가장 좋다"며 권장. 개인키는 내 서버에만 있고 거래소에는 공개키만 등록한다 (검색 요약) | HMAC, RSA | 확인 필요 |
| 시간 규칙 | `timestamp < 서버시각 + 1초` 그리고 `서버시각 − timestamp ≤ recvWindow`. 기본 5000ms, **최대 60000ms**. 권장은 "5000 이하" [직접: 바이낸스 REST 문서] | `서버시각 − recv_window ≤ timestamp < 서버시각 + 1000`. 기본 5000ms [직접] | 확인 필요 |
| 과다 호출 제재 | 429 오류 뒤에도 계속 호출하면 418로 **IP 자동 차단**. 반복하면 **2분에서 3일까지** 늘어난다 [직접] | 확인 필요 | 확인 필요 |

**해석**
- **고정 IP + IP 화이트리스트는 세 거래소 모두에서 사실상 필수다.** 바이비트·OKX는 IP 없는 키를 만료·삭제하고, 바이낸스는 강력히 권장한다. 01 문서의 결론("IP 화이트리스트는 출금 금지와 같은 급의 필수 조건", 3Commas 사고 근거)과 같다.
- **미국 서버는 쓸 수 없다.** 바이낸스와 바이비트가 둘 다 미국 IP를 막는다. 나중에 거래소를 바꿀 가능성까지 생각하면 **일본·싱가포르·한국 리전**이 무난하다. 한 판매사 블로그는 바이낸스 선물용으로 "도쿄·싱가포르가 안전한 선택"이라고 했다(검색 요약. 이해관계가 있는 출처라 신뢰도는 중).
- **바이낸스의 2025-12-09 변경**: 조건부 주문(STOP_MARKET, TAKE_PROFIT_MARKET 등)이 새 주소 `fapi/v1/algoOrder`(Algo 서비스)로 옮겨졌다. 옛 주소로 보내면 **-4120 오류**가 난다. freqtrade는 ccxt 4.5.20 이상으로 맞춰 해결했다 [직접: freqtrade 이슈 #12610]. 인프라 관점에서 이것은 "서버가 죽어도 포지션을 지키는 유일한 안전망(거래소 손절)"이 API 변경으로 조용히 실패할 수 있다는 뜻이다. **§2.9 감시 항목에 넣는다.**
- **선물 테스트넷 주소**: 바이낸스 문서는 선물 테스트넷을 `https://demo-fapi.binance.com`으로 안내한다(검색 요약). 예전 주소 `testnet.binancefuture.com`과의 관계는 **확인 필요**다.

#### 2.2.2 지연시간: 우리 시스템에는 중요하지 않다

| 서버 위치 → 바이낸스(도쿄) | 대략적인 왕복 시간 (검색 요약) |
|---|---|
| AWS 도쿄 | 한 자릿수 ms (REST 기준 약 20~25ms라는 측정도 있음) |
| 서울 | 약 72ms |
| 홍콩 | 약 90ms |
| 싱가포르 | 약 100ms |
| 미국 | 120ms 이상 (게다가 차단됨) |
| 유럽 | 200ms 이상 |

- 우리 흐름은 1시간봉 마감 → Claude 분석(30~60초, 03 문서) → **사람이 확인 후 버튼 두 번** → 주문이다. 사람의 반응 시간(수십 초~수 분)이 네트워크 차이(약 70ms)보다 **수천 배** 크다(추정).
- 결론: **"거래소 옆에 서버를 둔다"(코로케이션)에는 돈을 쓸 필요가 없다.** 도쿄를 권하는 이유는 지연시간이 아니라, 거래소를 바꿔도 막힐 가능성이 낮은 지역이고 가격이 서울과 같기 때문이다.

#### 2.2.3 한국 규제 동향 (인프라에 주는 영향만)

| 시점 | 내용 | 출처 |
|---|---|---|
| 2021-08 | 바이낸스가 **한국어 서비스를 중단**하고 원화 표시를 없앰. 특금법 신고 의무를 피하려는 조치로 보도됨 | (검색 요약) 파이낸셜뉴스·딜사이트 |
| 2025-03 | 금융정보분석원(FIU)이 미신고 해외 거래소 17곳(MEXC 등)의 **국내 접속을 차단** | (검색 요약) 이코노믹리뷰·지디넷 |
| 2026-01-28 | 구글이 **미신고 해외 거래소 앱의 플레이스토어 유통을 차단**. 바이낸스·바이비트 안드로이드 앱 사용이 사실상 어려워졌다는 보도 | (검색 요약) 지디넷·다음 |
| 2026-07~09 | 방송미디어통신심의위원회(방미심위)와 FIU가 "사기 피해가 확정되지 않아도 위법성이 인정되면 차단 절차"를 밟는 방향에 합의. FIU는 바이낸스를 "한국어 서비스 중단"을 이유로 심의 대상에서 뺐고, 방미심위는 형평성 문제를 제기함. **9월 중 구체 기준 확정 예정**으로 보도됨 | (검색 요약) 아시아경제·디지털애셋 |

**인프라에 미치는 영향**
1. **비상 정지 경로가 줄어든다.** 서버나 텔레그램이 죽었을 때 사람이 직접 거래소에 들어가 키를 삭제하거나 포지션을 닫아야 한다. 그런데 한국 폰에서는 거래소 앱을 받기 어려워졌다. **웹 브라우저로 로그인해 키 삭제·포지션 청산을 할 수 있는지 미리 연습해 둔다** (§2.12).
2. **집 서버와 서울 리전의 영향은 알 수 없다.** 국내 접속 차단이 시행되면 한국 인터넷 회사 회선을 쓰는 집 서버는 영향을 받을 수 있다. AWS 서울 리전이 영향을 받는지는 **확인 필요**다.
3. **서버를 해외에 두어 국내 차단을 피하는 것을 설계 목표로 삼지 않는다.** 정부 차단이 시행되면 그것은 기술 문제가 아니라 **법적 신호**다. 이때는 거래소 선택과 이용 적법성을 다시 검토해야 한다. 사용자의 "직접 최신 규제를 확인"(PLAN §3.2)을 **실거래(8단계) 진입 조건**으로 올릴 것을 권한다.
4. "2026년 현재 특별한 규제 없이 바이낸스 이용 가능"이라는 요약도 있었다. 하지만 출처가 블로그 수준이라 신뢰도가 낮다(검색 요약).

---

### 2.3 호스팅 후보 비교

#### 2.3.1 필요한 사양 (추정)

| 구성 요소 | 메모리 추정 | 근거 |
|---|---|---|
| Python 봇(pandas, mplfinance, 텔레그램, ccxt, anthropic SDK) | 300~600MB | 추정 |
| Docker 자체 | 100~200MB | 추정 |
| freqtrade를 실행 엔진으로 함께 쓸 경우 | freqtrade 공식 최소 요구 **RAM 2GB, vCPU 2개, 디스크 1GB** | 01 문서 (freqtrade README 직접 확인) |
| 백테스트(몇 년치 1H·15m) | 순간적으로 1GB 이상 | 추정 |

→ **2GB가 무난하다.** freqtrade를 쓰지 않고 백테스트를 서버에서 돌리지 않으면 1GB에 스왑(디스크를 메모리처럼 쓰는 보조 공간)을 더해 버틸 수 있다(추정).

#### 2.3.2 후보 비교표

| 후보 | 월 비용 (2GB급 기준) | 고정 IP | 거래소 접근 | 가용성·안정성 | 운영 난이도 | 판정 |
|---|---|---|---|---|---|---|
| **AWS Lightsail 도쿄** | **$12** (2 vCPU, 2GB, 60GB SSD, 전송 3TB). 신규 가입자 **첫 3개월 무료** (검색 요약). 1GB는 $7, 0.5GB는 $5 | 고정 IP가 인스턴스에 붙어 있으면 **무료**, 떼어 두면 시간당 $0.005 (검색 요약) | 바이낸스 매칭 엔진과 같은 리전. 일본은 알려진 차단 국가 목록에 없음 [직접: freqtrade] | AWS 수준. 자동 스냅샷 지원 | **쉬움**: 웹 콘솔, 정액제, 브라우저 SSH | ✅ **1순위** |
| **AWS Lightsail 서울** | 같은 가격 (아시아 일부 리전만 전송량 절반인데 뭄바이·시드니·자카르타가 해당하고 서울·도쿄는 해당 없음, 검색 요약) | 같음 | 바이낸스까지 약 72ms. 국내 차단 조치의 영향 여부는 **확인 필요** | 같음 | 쉬움 | ✅ 동급 대안 |
| AWS EC2 (도쿄·서울·싱가포르) | 인스턴스 + **공인 IPv4 $3.6/월**(2024-02부터 모든 공인 IPv4가 시간당 $0.005) + 디스크를 따로 계산. 도쿄 t4g.small 요금은 **확인 필요** (Lightsail보다 싸지 않을 것으로 추정) | 탄력적 IP(Elastic IP) | 같음 | 최고 수준 | **어려움**: VPC(가상 네트워크)·보안그룹·IAM(권한 관리)을 이해해야 함 | △ 나중에 옮길 곳 |
| AWS 새 무료 플랜 (2025-07-15 이후 가입) | 크레딧 $100 + 최대 $100 추가, **최대 6개월** (검색 요약) | — | — | — | — | 초기 비용 절감용으로만. 영구 무료 아님 |
| **Oracle Cloud 무료(Always Free)** | $0. 단, A1(ARM) 한도가 **4 OCPU·24GB → 2 OCPU·12GB로 축소**, 2026-08-18부터 적용 (검색 요약: InfoQ) | 예약 공인 IP 가능 (세부 확인 필요) | 한국(서울·춘천)·일본 리전 있음. 차단 사례는 확인 못 함 | **유휴 회수 규정**: 7일간 CPU 95퍼센타일, 네트워크, 메모리(A1)가 **모두 15% 미만**이면 회수 가능. **용량이 보장되지 않고**(out of host capacity), 가입 때 정한 홈 리전에서만 생성 (검색 요약) | 중간 (ARM, 콘솔 복잡) | ❌ 운영 서버로는 부적합. 우리 봇은 한 시간에 1분만 일하므로 회수 조건에 해당함(추정). 일부러 부하를 거는 우회는 권하지 않음 |
| GCP 무료(e2-micro) | $0 | 무료 외부 IP | **미국 리전만(us-west1, us-central1, us-east1)** → 바이낸스 451 (GCP에서 fapi 451 사례, 검색 요약) | — | 중간 | ❌ **탈락** |
| GCP 도쿄 유료 | **확인 필요** | 고정 외부 IP 별도 요금 (확인 필요) | 가능 | 좋음 | 중간~어려움 | △ 이점 없음 |
| Vultr 도쿄·서울 | 1 vCPU·1GB **$5**(Regular) / $6(High Frequency), 도쿄 확인 (검색 요약). IPv6 전용 $2.5 요금제 있음. 2GB 요금은 **확인 필요**. 서울 리전 존재는 **확인 필요** | 인스턴스 IP는 유지됨 (예약 IP 요금은 확인 필요) | 가능 (추정) | 양호 | 쉬움 | ○ 대안 |
| Hetzner (독일·핀란드·미국·**싱가포르**) | 2026-04·06 두 차례 인상. 싱가포르는 EU보다 20~40% 비싸고 **CPX12가 €15.49**(IPv4 별도). 싱가포르 트래픽 포함량은 0.5TB(EU는 20TB) (검색 요약) | IPv4 별도 요금 (확인 필요) | EU 파생상품은 계정 기준 제한이 있고, 네덜란드 IP는 차단 [직접: freqtrade]. 독일·핀란드 IP는 **확인 필요**. 미국 리전은 차단 | 양호 | 중간 | △ 가성비 우위가 사라짐 |
| **집 PC / NAS** | 전기요금만(월 수천~1만 원대, 누진제에 따라 다름, 추정) | ❌ **유동 IP**. 공유기가 계속 켜져 있으면 오래 유지되지만 정전·재할당 시 바뀜. 고정 IP는 KT 기업용(오피스넷) 가입 또는 SK브로드밴드의 조건부 상품 (검색 요약) | IP가 바뀌면 화이트리스트 때문에 주문이 막힘(안전하게 실패하지만 멈춤). 국내 차단 조치의 영향을 받을 수 있음 | 정전, 윈도우 업데이트 재부팅, 절전 모드 | 쉬움~중간 | ❌ 운영용 부적합. **개발·테스트용 ○** |
| **라즈베리파이 5** | 본체 + NVMe + UPS 한 번 구매(약 20~35만 원, 추정). 전기 월 1~2천 원(추정) | 집 PC와 같음 | 같음 | **SD카드는 정전 시 손상 위험**이 크다. NVMe + UPS(USB 신호선으로 안전 종료)가 해법 (검색 요약) | 중간 (ARM, 하드웨어 관리) | ❌ 운영용 부적합 |

#### 2.3.3 후보별 메모
- **Lightsail을 1순위로 둔 이유**
  1. 정액제라 요금이 예측된다.
  2. 고정 IP가 무료다.
  3. 웹 콘솔에서 스냅샷·방화벽·브라우저 SSH를 모두 다룰 수 있다.
  4. 나중에 EC2로 옮길 길이 있다.
  5. 코딩 비전문가가 네트워크 설정(VPC)을 몰라도 된다.
- **Lightsail에서 주의할 점 두 가지**
  - Lightsail 인스턴스의 **기본 공인 IP는 껐다 켜면 바뀐다**. 반드시 "고정 IP"를 만들어 붙이고 그 IP를 거래소에 등록한다.
  - IPv6 전용 요금제가 더 싸지만 바이낸스 화이트리스트의 IPv6 지원이 **확인 필요**라서 IPv4 요금제를 쓴다.
- **Oracle 무료 티어**: 유료(PAYG) 계정으로 바꾸면 유휴 회수에서 빠진다는 이야기가 있지만 **확인 필요**다. 무료라는 장점과 회수·용량 불확실성을 비교하면, 돈이 걸린 시스템에는 월 $12를 내는 편이 낫다.
- **집 PC**: 텔레그램 폴링이라 포트 포워딩(공유기 포트 개방)이 필요 없다는 점은 좋다. 하지만 거래 키가 가족 기기와 같은 집 네트워크에 놓인다. 개발·테스트넷 실험용으로만 쓴다.

---

### 2.4 서버 하드닝 (보안 설정)

사용자는 보안 전문가다. 아래는 "코딩 비전문가도 Claude와 함께 따라 할 수 있는 수준"으로 우선순위를 매긴 것이다.

#### 2.4.1 체크리스트

| 우선 | 항목 | 권장 설정 | 이유·근거 |
|---|---|---|---|
| 1 | **인바운드 전면 차단** | Lightsail 방화벽(클라우드 쪽)에서 **SSH 외 전부 차단**. Tailscale을 쓰면 SSH도 닫음. UFW는 `default deny incoming` | 텔레그램은 롱 폴링이라 **들어오는 포트가 필요 없다** (검색 요약: 폴링은 아웃바운드만, NAT 뒤에서도 동작) |
| 1 | **SSH 키 전용** | `PasswordAuthentication no`, `PermitRootLogin no`, 전용 사용자만 `AllowUsers` | 우분투 24.04 하드닝 가이드 공통 권장 (검색 요약) |
| 1 | **SSH 포트 비공개** | **Tailscale**(WireGuard 기반 사설망)로만 SSH 접속 → 공인 IP의 22번 포트가 아예 응답하지 않음. 무료 Personal 요금제: 사용자 6명, 기기 무제한(2026-08 기준), Tailscale SSH는 호스트 5대까지 (검색 요약) | 폰에서도 Tailscale 앱으로 접속할 수 있다. 대안: Lightsail 브라우저 SSH (방화벽을 콘솔 접속용으로만 제한하는 옵션은 **확인 필요**) |
| 1 | **Docker 포트 공개 금지** | `compose.yaml`에 `ports:`를 **쓰지 않는다**. 꼭 필요하면 `127.0.0.1:포트:포트`로 로컬에만 연다 | "`ufw deny 8080`을 해도 Docker가 공개한 포트는 외부에서 접근된다" [직접: ufw-docker README]. Docker는 iptables를 직접 고쳐 UFW를 우회한다 (검색 요약) |
| 2 | **자동 보안 업데이트** | `unattended-upgrades` 켜기. 자동 재부팅은 **캔들 마감 시각(정각)을 피한 시각**(예: UTC 19:30 = 한국 04:30)으로 | 재부팅 뒤 Docker가 봇을 자동으로 다시 띄우고, 봇은 시작 점검(§2.12)을 거친다 |
| 2 | **fail2ban** | SSH를 공개한다면 **필수**. Tailscale로 SSH를 닫았다면 **선택** | 로그인 시도 자체가 없으면 효과가 작다 |
| 2 | **아웃바운드 제한** | 1단계: UFW에서 나가는 포트를 **443/tcp(HTTPS), 53(DNS), 123/udp(NTP)**만 허용. 2단계(선택): 도메인 허용목록 프록시로 `*.binance.com`, `api.telegram.org`, `api.anthropic.com`, `hc-ping.com`, 패키지 저장소, GitHub만 허용 | 포트 제한만으로는 "443으로 아무 곳에나 유출"을 막지 못한다(한계를 인정). 거래소 IP는 CDN 뒤에서 바뀌므로 IP 기반 허용목록은 유지하기 어렵다(추정). 도메인 프록시는 보안 전문가인 사용자에게 권할 만하지만 **안정화 뒤**에 한다 |
| 2 | **최소 권한 실행** | 봇은 root가 아닌 전용 사용자로, 컨테이너 안에서도 non-root로 실행. **`docker` 그룹은 사실상 root 권한**이므로 사람 계정만 넣는다 | 일반 원칙 |
| 3 | **시간대** | 서버 시간대는 **UTC**로 둔다. 텔레그램 메시지에만 한국 시간(KST)을 표시 | STRATEGY v0.2는 하루 경계를 UTC 00:00으로 고정했다. 서버 시간대가 다르면 일일 손실 한도가 어긋난다 |
| 3 | **디스크 알림** | 사용률 80%에서 텔레그램 경고 | 로그 폭주 대비 (§2.10) |

#### 2.4.2 계정 보안 (서버 밖이 더 중요하다)

| 계정 | 조치 |
|---|---|
| **거래소** | 2FA(2단계 인증), 피싱 방지 코드, **출금 주소 화이트리스트 잠금**. API 키는 **선물 거래만 허용, 출금 금지 + IP 화이트리스트 + (바이낸스라면) Ed25519**. **봇이 쓸 자금만 선물 지갑에 두고 나머지는 분리**한다. 하위 계정을 쓸 수 있는지는 **확인 필요** |
| **AWS** | 루트 계정 MFA(다중 인증), 일상 작업은 별도 사용자, **예산 알림(Budgets)** 설정 |
| **Anthropic Console** | API 키를 전용 Workspace에 발급하고 **월 지출 한도**를 설정 (03 문서) |
| **텔레그램** | 봇 토큰은 BotFather에서만 관리. **개발용 봇과 운영용 봇을 따로** 만든다 (§2.6: 같은 토큰으로 두 프로세스가 폴링하면 409 충돌) |
| **GitHub** | 2FA, 저장소는 **비공개**, main 브랜치 보호(PR 필수), Secret scanning(비밀 유출 검사)과 push protection(비밀 푸시 차단) 켜기 |

---

### 2.5 비밀(API 키·토큰) 관리

#### 2.5.1 먼저 위협 모델

| 위협 | 비밀 관리로 막을 수 있나 | 실제로 막는 것 |
|---|---|---|
| GitHub·백업·로그·스크린샷·Claude 세션으로 **키가 새어 나감** | ✅ 막을 수 있다 | `.gitignore`, 암호화, 로그 마스킹, Claude 클라우드에 실키를 넣지 않기 |
| **서버 자체가 뚫림** | ❌ 막기 어렵다 (봇이 키를 써야 하므로 공격자도 읽을 수 있음) | 출금 금지 키, **IP 화이트리스트**(공격자가 서버 안에서만 쓸 수 있음), 봇용 자금 분리, 하드 가드, 인바운드 0개 |
| 새어 나간 키를 **다른 곳에서 사용** | — | IP 화이트리스트가 막는다 |
| 키가 새어 나간 것을 **늦게 알아챔** | — | 거래소 주문 알림, 매일 잔고 보고, 이상 주문 감지 |

→ 비밀 관리 도구보다 **키 권한과 IP 화이트리스트가 1차 방어선**이다. 비밀 관리는 "실수로 흘리지 않기"에 집중한다.

#### 2.5.2 방법 비교

| 단계 | 방법 | 비용 | 장점 | 단점 | 권고 |
|---|---|---|---|---|---|
| A | 서버의 `.env` 파일, 권한 `600`(소유자만 읽기), 봇 사용자 소유. Docker에는 실행 시점에 `env_file`로 주입하고 **이미지에 굽지 않음** | $0 | 가장 단순 | 서버 디스크에 평문 | ✅ **1~7단계** |
| B | **sops + age**: `.env`의 값만 암호화해 Git에 커밋. 복호화 키(age 개인키)는 서버와 오프라인 백업에만 둔다 | $0 | 설정이 버전 관리되고 복구가 쉬움. sops는 ENV·YAML·JSON·INI를 지원하고 age·KMS 등 여러 키 방식을 쓸 수 있음 [직접] | 도구를 하나 더 배워야 함 | ✅ **8단계(실거래) 전 도입** |
| C | AWS Secrets Manager 같은 클라우드 금고 | 비밀 1개당 월 $0.40 + 호출 1만 건당 $0.05 (검색 요약) | 감사 로그, 교체 자동화 | EC2는 IAM 역할로 키 없이 접근하지만 **Lightsail은 IAM 역할을 붙일 수 없어** 금고를 열 AWS 키를 서버에 또 둬야 함 (**확인 필요**) → 순환 문제 | ❌ Lightsail에서는 이점 작음. EC2로 옮기면 재검토 |

**추가 규칙**
- **키 교체**: 90일 규정이 없어졌더라도(확인 필요) **분기마다 교체**하고, 의심되면 즉시 교체한다. 교체 절차를 런북에 적는다.
- **로그 마스킹**: 요청 헤더·서명·토큰이 로그에 찍히지 않게 한다. 텔레그램 봇 토큰은 **URL 경로**(`/bot<토큰>/`)에 들어가므로 HTTP 디버그 로그를 켜면 그대로 노출된다(추정).

#### 2.5.3 Claude Code(클라우드 세션)에 비밀을 넣을 때 주의 [직접: code.claude.com]
- 클라우드 환경의 **환경 변수는 "그 환경을 쓰는 누구나 읽을 수 있다"**. 문서는 비밀을 넣지 말라고 경고한다.
- Pro·Max 요금제에는 **API credentials** 기능이 있다. 키를 세션 밖에 두고, 프록시가 지정한 호스트로 가는 요청의 **헤더**에만 붙여 준다. 다만 이 기능에는 한계가 있다(추론).
  - 바이낸스 주문은 비밀키로 **서명**을 만들어야 한다. 헤더에 키만 붙이는 방식으로는 쓸 수 없다.
  - 텔레그램 토큰은 URL 경로에 들어가므로 역시 쓸 수 없다.
  - Anthropic 키(`x-api-key` 헤더)에는 쓸 수 있다.
- 결론: **실거래 키는 Claude Code에 절대 넣지 않는다.** 테스트넷 키도 되도록 넣지 않는다. Claude Code에서는 저장해 둔 샘플 데이터와 가짜 응답(모의 객체)으로 테스트한다. 실제 거래소 연동 시험은 서버에서 한다(§2.13).

---

### 2.6 실행 방식: Docker Compose와 systemd 비교

| 기준 | Docker Compose | systemd + Python 가상환경 |
|---|---|---|
| 개발 PC와 서버를 똑같이 맞추기 | ✅ 같은 이미지 | △ 서버의 Python 버전·라이브러리에 따라 달라짐 |
| 자동 재시작 | `restart: unless-stopped` | `Restart=always` |
| 로그 | 기본 json-file은 **크기 무제한** → 반드시 `max-size`, `max-file` 설정 (검색 요약) | journald(`SystemMaxUse`로 제한) |
| 보안 주의 | **UFW 우회**, `docker` 그룹이 root와 같은 권한 | 비교적 단순 |
| freqtrade와 함께 쓰기 | ✅ freqtrade는 Docker 우선. 업데이트는 `docker compose pull` → `up -d` [직접] | 가능하지만 설치가 번거로움 |
| 롤백(이전 버전으로 되돌리기) | 이전 이미지 태그로 즉시 | Git 되돌리기 + 재설치 |
| Claude가 설정 파일을 써 주기 | 쉬움 (파일 하나) | 쉬움 |

**권고: Docker Compose.** PLAN §5와 같다. 이유는 재현성, 롤백, 그리고 01 문서가 권한 freqtrade 하이브리드와 맞는다는 점이다. 단, 다음 네 가지를 지킨다.
1. `ports:`를 쓰지 않는다 (§2.4).
2. 로그 제한을 설정한다: `max-size: 10m`, `max-file: 5` (§2.10).
3. 컨테이너 헬스체크(자체 상태 점검)를 넣는다.
4. **봇 인스턴스는 반드시 하나만** 띄운다. 같은 텔레그램 토큰으로 두 프로세스가 `getUpdates`를 호출하면 **409 Conflict**가 난다(검색 요약). 개발 PC에서 실수로 운영 토큰을 쓰는 사고를 막으려면 **개발용·운영용 봇 토큰을 분리**한다.

---

### 2.7 배포 방식

| 방식 | 설명 | 장점 | 위험·단점 | 판정 |
|---|---|---|---|---|
| **수동 배포** | 사람이 SSH(Tailscale)로 접속해 `deploy.sh` 한 줄 실행: 태그 받기 → 빌드 → 재시작 → 상태 확인 | 사람이 승인하는 지점이 생김. 구조가 단순 | 사람이 해야 함 | ✅ **권장** |
| GitHub Actions에서 SSH로 밀어 넣기 | Actions가 서버에 SSH로 접속해 배포 | 자동 | SSH 개인키를 GitHub Secrets에 둬야 함. GitHub 러너 IP가 넓어 **SSH 포트를 열어야 함**(Tailscale 액션으로 보완 가능) | △ |
| 자체 호스팅 러너(self-hosted runner) | 서버에 GitHub 러너를 설치해 작업을 받아 옴 | 아웃바운드만 필요 | GitHub는 **공개 저장소에서 쓰지 말라**고 권고. 러너가 뚫리면 서버가 뚫림 (검색 요약) | ❌ |
| 자동 풀(pull) 업데이트 | 서버가 새 이미지를 스스로 받아 재시작 | 편함 | 돈이 걸린 시스템이 **사람 모르게 바뀜** | ❌ |

**권고 구성**
- **CI(자동)**: PR마다 GitHub Actions로 테스트, 린트(ruff: 코드 스타일 검사기), 비밀 유출 검사, 의존성 취약점 검사(pip-audit)를 돌린다. 운영 서버 접근 권한은 **주지 않는다**.
- **CD(수동)**: main에 합친 뒤 **버전 태그**(예: `v0.4.1`)를 만들고, 사람이 서버에서 `deploy.sh v0.4.1`을 실행한다. 이전 태그로 되돌리는 `rollback.sh`도 함께 둔다.
- 이유: 주문에 사람 승인을 두는 것처럼, **돈을 다루는 코드의 교체에도 사람 승인을 둔다.** 배포가 하루 몇 번씩 일어나는 시스템이 아니다.
- **배포 금지 시간**: 포지션을 보유 중이거나 승인 대기 신호가 있으면 `deploy.sh`가 경고하고 멈추게 한다(제안).

---

### 2.8 시간 동기화 (NTP, recvWindow)

| 항목 | 내용 |
|---|---|
| 규칙 | 바이낸스는 요청 시각이 **서버 시각보다 1초 이상 앞서거나**, recvWindow(기본 5000ms)보다 늦게 도착하면 거부한다 [직접]. 이때 나는 오류가 **-1021** "Timestamp for this request is outside of the recvWindow"다 (검색 요약: ccxt·python-binance 이슈). 바이비트도 같은 구조다 [직접] |
| 공식 요구 | freqtrade 문서: "봇이 도는 시스템의 시계는 정확해야 하며, 거래소와 통신 문제가 없도록 NTP 서버와 충분히 자주 동기화해야 한다" [직접] |
| AWS | Amazon Time Sync Service(`169.254.169.123`)를 2018-08 이후 AMI(서버 이미지)가 기본으로 쓴다. 인터넷이나 보안그룹 설정이 필요 없다 (검색 요약). **Lightsail 이미지의 기본 설정 여부는 확인 필요** → 설치 후 `chronyc tracking`으로 확인 |
| **하지 말 것** | 시계 오차를 덮으려고 **recvWindow를 60000으로 키우지 않는다.** 바이낸스도 "5000 이하"를 권한다 [직접]. 창이 넓으면 늦게 도착한 주문(오래된 가격 기준)이 체결될 수 있다 |
| 감시 | 봇 시작 시와 매시 분석 때 거래소 서버 시각(`GET /fapi/v1/time`)과 비교한다. 차이가 **500ms를 넘으면 경고, 1000ms를 넘으면 주문 차단 + 알림**(제안값). ccxt에는 시각 차이를 자동으로 보정하는 옵션이 있다(`adjustForTimeDifference`, 문서 **확인 필요**). 보정은 쓰되, 원인(서버 시계)을 고치는 것이 먼저다 |
| 캔들 마감 시각 | 1H 봉은 UTC 정각에 마감된다. 분석은 **정각 + 5~30초**에 돌려 거래소가 마감 봉을 확정한 뒤 받는다(제안). 서버 시계가 틀리면 "아직 안 끝난 봉"을 분석하는 **룩어헤드 반대 오류**가 생길 수 있다(추정) |

---

### 2.9 모니터링과 알림

#### 2.9.1 세 겹 구조

| 층 | 도구 | 무엇을 잡나 | 비용 |
|---|---|---|---|
| ① **외부 데드맨 스위치** | **healthchecks.io**. 봇이 매시 분석을 마치면 핑(ping)을 보내고, 65~75분 안에 핑이 안 오면 **텔레그램·이메일로 알림**. 무료 Hobbyist 요금제로 **작업 20개** (검색 요약). 오픈소스(BSD-3)라 직접 설치도 가능하고 텔레그램 연동 지원 [직접] | **서버 전체가 죽은 경우**. 서버 안의 감시 프로그램은 서버와 함께 죽으므로 이것을 못 잡는다 | $0 |
| ② **봇 내부 알림** | 텔레그램 **운영 알림 채팅**(매매 채팅과 분리 권장). 같은 오류는 10분에 1회로 묶어 알림 폭주를 막는다 | 거래소·Claude·텔레그램 API 오류, 하드 가드 차단, 시계 오차 | $0 |
| ③ **매일 생존 보고** | 매일 한국 09:00(UTC 00:00, 일일 한도 초기화 시각)에 요약을 보낸다: 가동 시간, 지난 24시간 분석·신호·승인·체결 수, 잔고·포지션, **포지션별 손절 주문 존재 여부**, 시계 오차, 디스크, Claude 누적 비용 | "조용한 고장" (돌긴 도는데 아무것도 안 하는 상태) | $0 |

- **Uptime Kuma**(자체 설치형 감시 도구, 푸시 모니터·텔레그램 알림 지원 [직접])는 **봇 서버에 같이 두지 않는다.** 이유는 두 가지다. 서버가 죽으면 함께 죽고, 공식 실행 예시가 `-p 3001:3001`로 포트를 공개하기 때문이다(Docker의 UFW 우회 문제와 겹침) [직접]. 쓰고 싶다면 집 PC에서 돌리는 **보조 감시**로만 쓴다.

#### 2.9.2 감시 항목과 기준 (제안값)

| 항목 | 경고 | 치명(즉시 알림 + 필요 시 신규 주문 차단) |
|---|---|---|
| 매시 분석 완료 | 1회 누락 | 2회 연속 누락 (healthchecks) |
| **열린 포지션에 거래소 손절 없음** | — | **즉시 치명**. 자동으로 손절 재등록을 시도하고 실패하면 사람에게 알림 |
| 바이낸스 451 / 바이비트 403 | — | 즉시 치명 (지역 차단 = 운영 불가) |
| -1021 (시계) | 1회 | 3회 연속 |
| 429 (과다 호출) | 1회 | 418 (IP 차단, **최대 3일**) [직접] |
| -4120 (주문 유형 불가: Algo 주소 변경) | — | 즉시 치명 (손절 주문 실패 가능) |
| Claude API 오류·거절(refusal)·스키마 검증 실패 | 1회 (해당 신호는 "분석 실패"로 보내고 **주문 버튼을 만들지 않음**) | 3회 연속 |
| 텔레그램 API 오류 | 3회 연속 | 30분 지속 (이때는 healthchecks 이메일이 백업 경로) |
| 시계 오차 | 500ms 초과 | 1000ms 초과 |
| 디스크 사용률 | 80% | 90% |
| 컨테이너 재시작 횟수 | 1시간에 2회 | 1시간에 5회 (재시작 반복) |
| Claude 월 비용 | 예상치의 150% | Console 지출 한도 도달 |

---

### 2.10 로그 보존

| 종류 | 저장 위치 | 보존 | 설정 |
|---|---|---|---|
| 앱 로그 (진행 상황·오류) | 컨테이너 stdout → Docker json-file | **서버에 약 30일** 분량. 용량 기준 `max-size: 10m`, `max-file: 5` (검색 요약: 기본값은 무제한) | 한 줄에 하나씩 JSON 형식(구조화 로그). **키·서명·토큰 마스킹** |
| 시스템 로그 | journald | `SystemMaxUse=500M` (제안) | 검색 요약 |
| **감사 로그** (분석 결과, 버튼 클릭자·시각, 주문 요청·응답, 하드 가드 판정) | SQLite 테이블 | **영구** (용량이 작음). 세무 목적 보존 기간은 **확인 필요** | PLAN §4.4 그대로. 한 번 쓰면 고치지 않는 **추가 전용** 테이블로 설계 |
| Claude 원문 입출력 | SQLite 또는 압축 파일 | 90일 이상 (페이퍼 트레이딩 평가용, 03 문서 150건 기준) | 이미지는 경로만 남기고 파일은 따로 보관 |

---

### 2.11 SQLite 백업

| 방식 | 방법 | 잃을 수 있는 데이터(RPO) | 난이도 | 판정 |
|---|---|---|---|---|
| **① 정기 `.backup`** | `sqlite3 bot.db ".backup ..."`를 매일(또는 매시) 실행. **실행 중에도 안전하게** 복사된다 (검색 요약) → age로 암호화 → 서버 밖 저장소(S3 호환)에 업로드 → 30일 보관 | 최대 24시간 (매시면 1시간) | 쉬움 | ✅ **기본** |
| ② Litestream | WAL(쓰기 기록)을 계속 S3로 흘려보내는 보조 프로세스. 1분 미만 RPO, 특정 시점 복구 가능 (검색 요약). ①과 같이 쓸 수 있음 | 수 초 | 중간 | ○ 실거래 이후 선택 |
| ③ Lightsail 자동 스냅샷 | 매일 디스크 전체 스냅샷. 요금은 저장 용량 기준 (**확인 필요**, 월 $1 안팎 추정) | 24시간 | 매우 쉬움 | ✅ ①과 **함께** (서버 통째 복구용) |

**원칙**
- **포지션·주문의 진짜 기준은 거래소다.** SQLite를 잃어도 돈이 사라지지는 않는다. 복구 뒤에는 반드시 **거래소 상태와 맞춰 보기**(열린 포지션·주문 조회)를 한다.
- 백업 파일은 **암호화한 뒤** 밖으로 내보낸다. 감사 로그에는 잔고와 매매 이력이 들어 있다.
- **복구 연습을 매달 1회** 한다. 복원해 본 적 없는 백업은 백업이 아니다.
- `.env`와 age 개인키는 **서버 백업과 분리**해서 오프라인(비밀번호 관리자 등)에 보관한다.

---

### 2.12 장애 대응

#### 2.12.1 최우선 원칙: 서버가 죽어도 포지션은 안전해야 한다
1. **진입과 동시에 거래소에 손절(그리고 익절) 주문을 건다.** 바이낸스라면 2025-12-09 이후 Algo 주소로 보낸다 [직접: freqtrade #12610]. 이렇게 하면 서버·텔레그램·Claude가 모두 죽어도 손실은 손절선에서 멈춘다. 01 문서의 "거래소 손절(stoploss on exchange)"과 같은 원칙이다.
2. **봇이 시작할 때마다 점검한다.**
   ① 거래소 시각과의 오차
   ② 열린 포지션과 열린 주문 조회
   ③ **포지션마다 손절이 있는지** 확인하고, 없으면 재등록하거나 알림
   ④ 재시작 전의 **승인 대기 신호는 모두 무효** 처리(PLAN §4.2의 유효시간 원칙)
   ⑤ 킬 스위치 상태 복원
   ⑥ 텔레그램에 "재시작됨 + 점검 결과"를 보낸다
3. **서버 밖 비상 정지 경로**를 둔다. 텔레그램 `/stop`은 서버가 살아 있을 때만 동작한다. 서버가 뚫렸거나 연락이 안 되면 **거래소 웹에서 API 키 삭제** → 포지션 수동 청산 순서로 대응한다. 한국에서 거래소 앱을 받기 어려워졌으므로(§2.2.3) **웹 로그인 경로를 미리 시험**한다.

#### 2.12.2 시나리오별 대응

| 장애 | 감지 | 자동 대응 | 사람 대응 |
|---|---|---|---|
| 서버 다운 / 리전 장애 | healthchecks (65~75분) | 없음 (거래소 손절이 보호) | 콘솔에서 재시작. 안 되면 스냅샷으로 새 인스턴스 생성 → **고정 IP 다시 붙이기** (같은 리전이면 IP 유지). 다른 리전이면 **새 IP를 거래소 화이트리스트에 등록** |
| 봇 재시작 반복 | 재시작 횟수 알림 | 재시작 반복 시 신규 주문 차단 | 로그 확인 → 이전 태그로 롤백 |
| 거래소 점검·오류(5xx) | 봇 알림 | 재시도(간격을 점점 늘림). 주문은 **재시도하지 않고** 상태부터 조회 (중복 주문 방지) | 공지 확인 |
| 451/403 (지역 차단) | 치명 알림 | 모든 거래 기능 정지 | 법률·거래소 정책 재검토. **IP 우회는 하지 않음** |
| 418 IP 차단 (최대 3일) | 치명 알림 | 호출 중지 | 원인(과다 호출) 수정. 거래소 웹에서 수동 관리 |
| 시계 오차 | 시계 알림 | 주문 차단 | `chronyc` 점검 |
| Claude API 장애·거절 | 봇 알림 | 해당 시간 "분석 실패" 통보, 버튼 없음 | 필요하면 대체 모델 설정 (03 문서의 fallbacks) |
| 텔레그램 장애 | 봇 알림 (이메일 경로) | 신호 발송 보류. 유효시간이 지나면 폐기 | 기다림 |
| **키 유출 의심** | 모르는 주문 알림, 잔고 이상 | — | **거래소 웹에서 키 즉시 삭제** → 포지션 점검 → 서버 재구축 → 새 키 발급 |
| 디스크 가득 참 | 디스크 알림 | 오래된 로그 삭제 | 로그 설정 점검 |
| AWS 결제 실패·계정 잠김 | AWS 메일 | — | 결제 수단 이중화. 예산 알림 |

#### 2.12.3 목표 (제안값)
- **RTO(복구 시간) 2시간 이내**: 스냅샷과 런북으로 복구한다. 거래소 손절이 있으므로 급하지 않다.
- **RPO(데이터 손실) 24시간 이내**: 매일 백업. 실거래 뒤에는 매시 백업이나 Litestream을 검토한다.
- 런북은 저장소의 `docs/RUNBOOK.md`에 둔다. 들어갈 내용: 서버 재구축, 키 교체, IP 변경, 롤백, 비상 정지, 백업 복원. **폰으로 읽고 따라 할 수 있게** 짧게 쓴다.

---

### 2.13 개발 환경 (코딩 비전문가 + Claude Code)

#### 2.13.1 Claude Code 사용 방식 [직접: code.claude.com]

| 방식 | 어디서 실행 | 특징 | 우리 용도 |
|---|---|---|---|
| **클라우드 세션** (웹 claude.ai/code, **Claude 앱의 Code 탭**, 데스크톱 앱의 Cloud) | Anthropic이 관리하는 격리된 가상 머신 | 노트북을 닫아도 계속 돈다. 폰에서 확인하고 지시할 수 있다. GitHub 저장소를 복제해 브랜치·PR을 만든다. GitHub 인증 정보는 VM 밖(프록시)에 있다. 네트워크 수준은 **None / Trusted(기본: 패키지 저장소·GitHub 등) / Custom(직접 허용목록) / Full**. **환경 변수는 그 환경 사용자 누구나 읽을 수 있다** | ✅ **주력**: 코드 작성, 테스트, PR 만들기. 사용자가 주로 폰을 쓰므로 가장 잘 맞는다 |
| **로컬 세션** (데스크톱 앱 Local, 터미널) | 내 PC | 내 PC의 네트워크를 쓴다. Remote Control로 폰에서 조종할 수 있다 | ○ 거래소 테스트넷 연동 시험(한국 IP) |
| 운영 서버 | Lightsail | — | ❌ 서버에 Claude Code를 두지 않는다. 운영 서버에는 봇만 둔다 |

**주의점**
- 지금 쓰는 클라우드 환경은 조직 네트워크 정책 때문에 binance·telegram 등이 **차단**되어 있다(이번 조사에서 확인). Custom 허용목록에 `demo-fapi.binance.com` 등을 추가할 수는 있다. 하지만 클라우드 VM이 **어느 나라 IP로 나가는지 확인 필요**하다. 미국이면 바이낸스 451이 날 수 있다.
- 그래서 **실제 거래소·텔레그램 연동은 운영 서버(테스트넷 모드) 또는 집 PC에서** 시험한다. Claude Code 클라우드에서는 **저장해 둔 캔들 데이터(픽스처)와 가짜 거래소 응답(모의 객체)**으로 테스트한다. 이렇게 하면 비밀 정보도 클라우드 세션에 들어가지 않는다.

#### 2.13.2 권장 개발 흐름

```
[폰: Claude 앱 Code 탭]  "3단계 텔레그램 버튼 만들어줘"
        │  (클라우드 세션: 코드 작성 + 가짜 데이터로 테스트)
        ▼
[GitHub PR]  ← CI 자동: 테스트·ruff·비밀 유출 검사·pip-audit
        │  사용자가 폰에서 diff 검토 → main에 합침 → 버전 태그
        ▼
[Lightsail 도쿄 서버]  사람이 Tailscale SSH로 deploy.sh v0.x 실행
        │  compose: bot (테스트넷 모드, 개발용 텔레그램 봇 토큰)
        ▼
[텔레그램]  실제 버튼 시험 → 문제는 다시 Claude에게
```

- **PLAN 로드맵 조정 제안**: 서버 준비를 6단계(배포)가 아니라 **3.5단계**(4단계 테스트넷 주문 전)로 당긴다. 이유는 두 가지다.
  - 클라우드 세션에서 거래소 테스트넷에 닿을지 불확실하다.
  - IP 화이트리스트·시간 동기화·지역 차단을 **실제 서버에서 일찍 확인**하는 편이 싸다.
- **서버를 사기 전 30분 점검**: Lightsail 인스턴스를 만든 직후, 키 없이 공개 API로 확인한다: `GET /fapi/v1/time`, `GET /fapi/v1/klines`. 451이 나오지 않는지, 텔레그램 `getMe`, Anthropic API 호출까지 확인한다. 문제가 있으면 인스턴스를 지우고 다른 리전으로 바꾼다(시간 단위 과금이라 비용은 몇 센트, 추정).
- 코드 품질 장치(초보자용 최소 세트): 테스트(pytest), 린트(ruff), 타입 검사(선택), GitHub 비밀 스캐닝 + push protection, Dependabot(의존성 업데이트 알림).

---

### 2.14 월 비용 추정

| 항목 | 월 비용 (USD) | 근거 |
|---|---|---|
| Lightsail 도쿄 2GB | **$12** (신규 가입자 첫 3개월 $0) | 검색 요약 |
| 고정 IP (인스턴스에 연결 시) | $0 | 검색 요약 |
| Lightsail 스냅샷 | 약 $1 (추정, **확인 필요**) | — |
| 백업 저장소 (S3 호환, 수백 MB) | $0.1 미만 (추정) | — |
| healthchecks.io | $0 (무료 20개) | 검색 요약 |
| Tailscale | $0 (Personal) | 검색 요약 |
| 도메인·인증서 | $0 (폴링이라 필요 없음) | PLAN §3.1 |
| **Claude API (Opus 5.5)** | **$10~18** (코드 사전 필터, 월 180회) / $42~73 (매시 호출) | 03 문서 §2.5.3 |
| **합계: 사전 필터** | **약 $23~31** (약 3.2만~4.3만 원, 1달러 = 1,400원 가정) | 추정 |
| 합계: 매시 호출 | 약 $55~86 (약 7.7만~12만 원) | 추정 |
| 첫 3개월 (서버 무료) | 약 $11~19 | 추정 |
| 절약안: Lightsail 1GB ($7) | 위 합계에서 −$5 | freqtrade를 쓰지 않을 때만 |

- 거래 수수료, 펀딩비(무기한 선물 보유 비용), 세금은 인프라 비용이 아니라서 빠져 있다.
- 비용의 대부분은 **Claude 호출 방식**이 정한다. 서버는 고정비 $12다.

---

## 3. 우리 시스템에 대한 시사점과 권고

### 3.1 권장 운영 구성 (한 장 요약)

```
                     ┌──────────────── AWS Lightsail 도쿄 (Ubuntu LTS, 2GB, 고정 IPv4, UTC) ───────────────┐
 [사용자 폰]           │  인바운드: 전부 차단 (SSH는 Tailscale 사설망으로만)                                      │
  ├ Claude 앱(개발)    │  Docker Compose ─ bot 컨테이너 1개 (non-root, ports 없음, restart, 로그 10m×5)          │
  ├ 텔레그램(승인·알림)  │     ├ 스케줄러: UTC 정각+수 초 → 데이터 → 지표 → (후보 있을 때) Claude → 텔레그램         │
  ├ Tailscale(SSH)     │     ├ 하드 가드 → 주문 + 거래소 손절·익절 (Algo 주소)                                    │
  └ 거래소 웹(비상 정지)  │     ├ 시작 점검: 시계·포지션·손절 존재·대기 신호 무효화                                   │
                     │     └ SQLite (감사 로그) → 매일 .backup + age 암호화 → 서버 밖 저장소                         │
                     │  chrony(시간 동기화) · unattended-upgrades(04:30 KST) · .env 600 → 이후 sops+age         │
                     └──── 아웃바운드 443/53/123만 ──► 바이낸스 · api.telegram.org · api.anthropic.com · hc-ping ─┘
                                                              ▲
                          healthchecks.io (외부 데드맨 스위치) ─┘ 핑이 끊기면 텔레그램·이메일 알림
```

### 3.2 기존 기획(PLAN v0.1)에 대한 평가

| PLAN 항목 | 평가 | 근거·보완 |
|---|---|---|
| §3.1 텔레그램 폴링 → 인바운드 포트 불필요 | ✅ **맞다** | 폴링은 아웃바운드만 쓴다 (검색 요약). 이 덕분에 "들어오는 문 0개" 서버가 가능하다 |
| §4.1 출금 금지, IP 화이트리스트, `.env`, 테스트넷 키 | ✅ 맞다. **보완 세 가지** | ① IP 화이트리스트는 **필수 조건**이다(바이비트 90일 만료, OKX 14일 삭제, 바이낸스 강력 권장). ② 바이낸스는 **Ed25519 자체 생성 키**를 쓴다. ③ **봇용 자금 분리**를 추가한다 |
| §4.1 "서버의 Secret 관리 기능" | ⚠️ **Lightsail에서는 이점이 작다** | IAM 역할을 붙일 수 없어 금고용 키가 또 필요하다(확인 필요). `.env`(600)로 시작해 sops+age로 옮기는 것이 현실적이다 |
| §4.3 긴급 정지 `/stop` | ⚠️ **부족하다** | 서버나 텔레그램이 죽으면 동작하지 않는다. **서버 밖 경로**(거래소 웹에서 키 삭제)를 런북에 넣고 미리 연습한다. 한국에서 거래소 앱을 받기 어려워진 점을 고려한다 |
| §5 "Docker + VPS 1대, 고정 IP" | ✅ 맞다. **리전 조건 추가** | "거래소가 막지 않는 나라의 리전"이라는 조건을 명시한다. 미국 리전, GCP 무료 티어는 제외한다. 권장은 Lightsail 도쿄·서울 |
| §6 로드맵: 6단계에서 배포 | ⚠️ **순서 조정** | 서버 준비를 **3.5단계**(테스트넷 주문 전)로 당긴다. 지역 차단·화이트리스트·시계를 실제 환경에서 일찍 확인하기 위해서다 |
| (없음) 거래소 손절이 인프라 장애 대비책이라는 인식 | ➕ **추가** | 진입과 동시에 거래소에 손절을 건다. 봇 시작 때 점검한다. Algo 주소 변경(-4120)을 감시한다 |
| (없음) 시간 동기화 | ➕ **추가** | chrony, recvWindow 5000 유지, 오차 감시, 서버 시간대 UTC |
| (없음) 외부 감시 | ➕ **추가** | healthchecks.io 데드맨 스위치 + 매일 생존 보고 |
| (없음) 배포 절차 | ➕ **추가** | CI는 자동, 배포는 사람이 태그로. 자동 배포와 자체 호스팅 러너는 쓰지 않는다 |
| (없음) 개발·운영 분리 | ➕ **추가** | 텔레그램 봇 토큰 2개(409 충돌 방지), 거래소 키 2종(테스트넷·실거래), 실거래 키는 Claude Code에 넣지 않는다 |
| §3.2 규제 "직접 확인" | ⚠️ **격상** | 2026-09 해외 거래소 접속 차단 기준 논의가 진행 중이다. **8단계 진입 조건**으로 법률 확인을 넣는다. 서버 위치로 우회하지 않는다 |

### 3.3 단계별 인프라 체크리스트 (PLAN 로드맵에 맞춤)

| 단계 | 인프라 작업 | 완료 기준 |
|---|---|---|
| 0. 준비 | GitHub 비공개 저장소 + 2FA + 브랜치 보호. AWS 계정 루트 MFA + 예산 알림. Anthropic 지출 한도. **텔레그램 봇 2개**(개발·운영) | 계정 목록과 2FA 확인표 |
| 1~3 | Claude Code 클라우드에서 개발. 픽스처·모의 객체로 테스트. CI 구축 | PR마다 CI 통과 |
| **3.5 서버** | Lightsail 도쿄 2GB + 고정 IP. **30분 점검**(바이낸스 공개 API·텔레그램·Anthropic). 하드닝(§2.4 우선순위 1~2), Tailscale, chrony, Docker, 로그 제한, healthchecks | 451 없음, 시계 오차 < 100ms(제안), 외부 포트 스캔 결과 열린 포트 0개 |
| 4. 모의주문 | 테스트넷 키(IP 화이트리스트 = 고정 IP) 사용. 거래소 손절 등록 확인. 시작 점검 구현 | 서버를 강제로 재시작해도 손절이 유지되고 점검 메시지가 옴 |
| 5. 리스크 | 감시 항목(§2.9.2) 구현, 운영 알림 채팅 | 일부러 오류를 넣어 알림이 오는지 확인 |
| 6. 배포 | `deploy.sh`와 `rollback.sh`, 태그 배포, 백업·암호화·업로드, 스냅샷 | **백업 복원 연습 1회 성공** |
| 7. 검증 | 1~2주 연속 운영. 매일 생존 보고 확인 | 누락 0, 치명 알림 원인 모두 기록 |
| **8. 실거래 전 관문** | sops+age 전환, 실거래 키(출금 금지·IP·Ed25519), 봇용 자금만 이체, **거래소 웹 비상 정지 연습**, 법률·규제 확인, 런북 완성 | 체크리스트 전 항목 ✅ |

### 3.4 결정이 필요한 항목 (❓)

1. **리전**: 도쿄(권장: 거래소 이전 가능성·중립)와 서울(국내 차단 조치 영향 **확인 필요**) 중 어디로 할까요?
2. **서버 크기**: 2GB $12(freqtrade 병행이나 서버 백테스트 가능)와 1GB $7(봇만) 중 어느 쪽인가요? 01 문서의 freqtrade 하이브리드를 채택하면 2GB입니다.
3. **SSH 접속**: Tailscale(권장, 폰 앱 필요)과 Lightsail 브라우저 SSH(설치 없음) 중 무엇을 쓸까요?
4. **백업 저장소**: 같은 AWS 계정의 S3와 다른 회사 저장소(계정 탈취에 대비한 분리) 중 무엇으로 할까요?
5. **알림 채팅**: 매매용과 운영 알림용을 분리할까요? (권장: 분리)
6. **아웃바운드 도메인 허용목록**(프록시)을 실거래 전에 넣을까요, 안정화 뒤로 미룰까요?

---

## 4. 출처

**직접 확인 [직접]**
1. 바이낸스 REST API 문서(시간 보안, recvWindow, 429/418) — https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md
2. freqtrade 거래소 문서(바이낸스 서버 국가 차단: 캐나다·말레이시아·네덜란드·미국, 선물 설정) — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/exchanges.md
3. freqtrade 설치 문서(NTP 동기화 요구, 라즈베리파이 주의) — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/installation.md
4. freqtrade Docker 문서(로그·DB 경로, `docker compose pull` 업데이트) — https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/docker_quickstart.md
5. freqtrade 이슈 #12610(바이낸스 -4120, 2025-12-09 Algo 주소 이전, ccxt 4.5.20) — https://github.com/freqtrade/freqtrade/issues/12610
6. 바이비트 FAQ 원본(서버 AWS 싱가포르 apse1-az3) — https://raw.githubusercontent.com/bybit-exchange/docs/main/docs/faq.mdx
7. 바이비트 통합 안내 원본(recv_window 규칙, 네덜란드·홍콩 별도 도메인) — https://raw.githubusercontent.com/bybit-exchange/docs/main/docs/v5/guide.mdx
8. ufw-docker(Docker의 UFW 우회) — https://github.com/chaifeng/ufw-docker
9. SOPS(지원 형식·키 방식) — https://github.com/getsops/sops
10. Uptime Kuma README(푸시 모니터, 텔레그램, 실행 예시 `-p 3001:3001`) — https://raw.githubusercontent.com/louislam/uptime-kuma/master/README.md
11. Healthchecks 저장소(BSD-3, 자체 설치, 텔레그램) — https://github.com/healthchecks/healthchecks
12. 바이낸스 파이썬 커넥터(USDS 선물 테스트넷 상수) — https://raw.githubusercontent.com/binance/binance-connector-python/master/clients/derivatives_trading_usds_futures/README.md
13. Claude Code 클라우드 세션(모바일, GitHub 프록시, 보안 격리) — https://code.claude.com/docs/en/claude-code-on-the-web
14. Claude Code 클라우드 환경(네트워크 수준, 환경 변수 공개 경고, API credentials) — https://code.claude.com/docs/en/cloud-environments

**검색 요약 (원문 미열람)**

15. 바이낸스 451과 서버 위치 — https://dev.binance.vision/t/http-451-error-and-vps-location/14685 · https://dev.binance.vision/t/google-cloud-and-ip-restriction-451-on-fapi-binance/13820 · https://discuss.streamlit.io/t/binance-api-no-longer-working-in-streamlit-cloud/35279 · https://forum.bubble.io/t/binance-api-call-stopped-working-because-it-just-restricted-a-service-for-us-location/234946 · https://github.com/diegomanuel/binance-to-google-sheets/issues/142 · https://www.kaggle.com/questions-and-answers/481157
16. 바이낸스 선물 고정 IP·안전 리전(도쿄·싱가포르) — https://www.quotaguard.com/blog/binance-futures-api-static-ip
17. 바이낸스 제한 국가 — https://www.datawallet.com/crypto/binance-restricted-countries · https://www.coinperps.com/learn/binance-futures-restricted-countries · https://investingintheweb.com/blog/binance-countries/
18. 거래소 서버 위치·지연시간 — https://book.longcipher.com/en/blog/aws-tokyo-digital-wall-street/ · https://arbitron.app/learn/crypto-exchange-server-locations · https://aws.amazon.com/blogs/industries/ultra-low-latency-cross-region-crypto-trading-with-avelacom-and-aws/ · https://cloud.zenlayer.com/blog/crypto-trading-latency-tokyo · https://docs.ccxt.com/blog/how-far-is-your-exchange
19. OKX 서버 위치 — https://github.com/njv74841/okx-api-server-location · https://zenlayer.medium.com/case-study-okx-cuts-inter-cloud-latency-to-2-ms-with-zenlayer-cloud-networking-3403ad7b5141
20. 바이비트 지역 차단·클라우드 IP 차단·제한 국가 — https://bybit-exchange.github.io/docs/v5/guide · https://www.quotaguard.com/blog/bybit-api-403-cloud-platform-cdn-block-fix · https://www.datawallet.com/crypto/bybit-restricted-countries
21. 바이낸스 키 90일 규정 폐지(2026-08-06) — https://blog.traderspost.io/article/managing-binance-api-key-expiry-on-traderspost · https://www.quotaguard.com/blog/binance-api-ip-whitelist-cloud-static-ip · https://www.binance.com/en/support/announcement/updates-to-api-key-permission-rules-2021-07-26-11e4c2f44e7a47b9b5fc0e479c0b256f
22. 바이낸스 IP 화이트리스트 권장·Ed25519 — https://www.binance.com/en/blog/security/how-to-use-an-api-key-securely-5-tips-from-binance-8638066848800196896 · https://www.binance.com/en/support/announcement/binance-now-supports-ed25519-api-keys-2023-07-19-30372026b6af4fbbb9b38ab5c3f91755 · https://developers.binance.com/docs/binance-spot-api-docs/faqs/api_key_types
23. 바이낸스 IP 30개 한도 — https://voiceofchain.com/academy/binance-api-ip-whitelist
24. 바이비트 90일·OKX 14일 키 정책 — https://help.waltio.com/en/articles/5960015-bybit-api · https://www.quotaguard.com/blog/okx-api-key-14-day-deletion-static-ip-fix
25. 바이낸스 Algo 주문 이전 — https://developers.binance.com/docs/derivatives/change-log · https://github.com/MankhongGarden/binance-futures-algo-endpoint-migration
26. 바이낸스 선물 테스트넷 주소 — https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
27. -1021 시계 오류 — https://github.com/ccxt/ccxt/issues/761 · https://github.com/sammchardy/python-binance/issues/1056 · https://dev.binance.vision/t/code-1021-msg-timestamp-for-this-request-is-outside-of-the-recvwindow/6032
28. Amazon Time Sync — https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configure-ec2-ntp.html · https://aws.amazon.com/blogs/aws/keeping-time-with-amazon-time-sync-service/
29. Lightsail 요금·고정 IP·무료 3개월·리전별 전송량 — https://cloudburn.io/blog/amazon-lightsail-pricing · https://aws.amazon.com/lightsail/pricing/ · https://www.cloudzero.com/blog/amazon-lightsail-pricing/ · https://repost.aws/questions/QUbzlZML1ST-iAyxpFIw9mSg/lightsail-and-ipv4-address-costs · https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html
30. AWS 무료 티어 개편(2025-07-15)·공인 IPv4 요금 — https://freetier.co/articles/aws-free-tier-changes-july-15-2025 · https://infratally.com/articles/aws-free-tier-2026/ · https://aws.amazon.com/vpc/pricing/ · https://www.doit.com/blog/aws-public-ipv4-price-increase-the-complete-guide
31. Oracle 무료 티어 축소·유휴 회수 — https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/ · https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm · https://www.oracle.com/cloud/free/faq/
32. GCP 무료 티어 리전 — https://cloud.google.com/free/docs/compute-getting-started · https://agentdeals.dev/gcp-free-tier-2026
33. Vultr 요금 — https://www.vultr.com/products/regular-performance-compute/ · https://getdeploying.com/vultr · https://betterstack.com/community/guides/web-servers/vultr-review/
34. Hetzner 2026 인상·싱가포르 — https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/ · https://northflank.com/blog/hetzner-cloud-server-price-increases · https://agentdeals.dev/hetzner-pricing-2026 · https://www.hetzner.com/pressroom/new-location-singapore/
35. 가정용 인터넷 유동·고정 IP — https://www.100mb.kr/bbs/board.php?bo_table=customer&wr_id=468285 · https://www.100mb.kr/bbs/board.php?bo_table=customer&wr_id=558047 · https://www.100mb.kr/bbs/board.php?bo_table=customer&wr_id=591049
36. 라즈베리파이 SD카드 손상·NVMe·UPS — https://hackaday.com/2022/03/09/raspberry-pi-and-the-story-of-sd-card-corruption/ · https://linuxblog.io/raspberry-pi-storage-reliability/ · https://forums.raspberrypi.com/viewtopic.php?t=59652
37. 한국 해외 거래소 규제 동향 — https://zdnet.co.kr/view/?no=20260115093947 · https://v.daum.net/v/20260117100244337 · https://www.asiae.co.kr/article/2026073018314271848 · https://view.asiae.co.kr/article/2026092214243195647 · https://www.digitalasset.works/news/articleView.html?idxno=42239 · https://www.speconomy.com/news/articleView.html?idxno=325592 · https://www.ahnlab.com/ko/contents/content-center/36072
38. 바이낸스 한국어 서비스 중단(2021) — https://www.fnnews.com/news/202108111854274962 · https://dealsite.co.kr/articles/77264/094045 · https://www.coinsea.co.kr/binance-faq-korea.html
39. 텔레그램 롱 폴링·웹훅·409 충돌 — https://gramio.dev/updates/webhook · https://core.telegram.org/bots/api
40. Docker의 UFW 우회·DOCKER-USER 체인 — https://www.baeldung.com/linux/docker-container-published-port-ignoring-ufw-rules · https://dev.to/alanwest/why-docker-bypasses-ufw-and-how-to-actually-lock-it-down-26ep
41. 우분투 24.04 하드닝 — https://gist.github.com/jeanpauldejong/1274c87ce0ae0c8e27443437a5b575ea · https://privatedevops.com/articles/server-hardening-checklist-ubuntu-2404 · https://qubitlogic.dev/infrastructure/secure-ubuntu-24-04-vps-hardening/
42. Tailscale 무료 요금제·SSH 차단 — https://costbench.com/software/business-vpn/tailscale/free-plan/ · https://www.ssdnodes.com/learn/is-tailscale-free-plan-limits · https://til.simonwillison.net/tailscale/lock-down-sshd
43. AWS Secrets Manager 요금·sops+age — https://www.akeyless.io/blog/aws-secrets-manager-cost/ · https://infisical.com/blog/secrets-manager-pricing · https://www.deployhq.com/guides/sops
44. GitHub Actions 보안(자체 호스팅 러너) — https://docs.github.com/en/actions/reference/security/secure-use · https://docs.github.com/en/actions/concepts/security/compromised-runners · https://github.com/orgs/community/discussions/26722
45. healthchecks.io 요금·텔레그램 — https://healthchecks.io/pricing/ · https://healthchecks.io/integrations/telegram/
46. Docker 로그 크기 제한·journald — https://oneuptime.com/blog/post/2026-02-08-how-to-limit-docker-container-log-file-size/view · https://medium.com/@Quigley_Ja/rotating-docker-logs-keeping-your-overlay-folder-small-40cfa2155412
47. SQLite 백업(.backup, Litestream) — https://litestream.io/alternatives/cron/ · https://litestream.io/how-it-works/ · https://github.com/benbjohnson/litestream

**내부 문서**

48. Claude API 비용 추정(월 $10~18 / $42~73) — [03_llm_trading.md §2.5.3](./03_llm_trading.md)
49. freqtrade 최소 사양(RAM 2GB·vCPU 2), 거래소 손절, 3Commas 사고 — [01_existing_systems.md](./01_existing_systems.md)
