# 트레이딩뷰를 Claude에 붙여 차트분석기에 쓰기

트레이딩뷰 데스크톱 앱의 차트를 Claude Code가 MCP로 읽고, 그 봉 자료를 우리 차트분석기의 고정된 기준으로 판정한다.

```
트레이딩뷰 데스크톱 ──(MCP: tradingview-mcp)──> Claude Code ──> analyzer/tv/analyze.cjs ──> 판정 글 + 분석기 화면
        ↑                                                                                      │
        └────────────────────── 차트에 지지·저항·범위 표시 그리기 ◄───────────────────────────┘
```

- 트레이딩뷰가 하는 일: 봉 자료 제공, 표시 그리기.
- 판정하는 것: `analyzer/src/core.js`. 웹 화면(`analyzer/index.html`)과 같은 코드다.
- 주문 기능은 없다.

## 준비물 (맥·윈도우 공통)

- 트레이딩뷰 데스크톱 앱 (로그인된 상태). 웹 브라우저판으로는 안 된다.
- Node.js 18 이상, git
- Claude Code

## 설치 (한 번만)

저장소 폴더에서:

```
git fetch origin && git checkout ccr-bf61e1db-uxkzzx
bash analyzer/tv/setup.sh
```

윈도우는 PowerShell에서 둘째 줄만 다르다.

```
git fetch origin; git checkout ccr-bf61e1db-uxkzzx
powershell -ExecutionPolicy Bypass -File analyzer\tv\setup.ps1
```

설치 스크립트는 연결 도구를 `vendor/tradingview-mcp`에 받는다. 우리가 읽어 본 판(`c05b8f5`)으로 고정해서 받고, 설치 중 스크립트 실행을 끈다.

## 쓸 때마다

1. 트레이딩뷰를 디버그 모드로 띄운다. **켜져 있던 트레이딩뷰는 닫혔다가 다시 열린다.**
   ```
   bash vendor/tradingview-mcp/scripts/launch_tv_debug_mac.sh
   ```
   윈도우:
   ```
   vendor\tradingview-mcp\scripts\launch_tv_debug.bat
   ```
   윈도우에서 "CDP never became available"이 나오면 아래 "윈도우에서 디버그 포트가 안 열릴 때"를 본다.
2. 저장소 폴더에서 `claude`를 실행한다. 처음에는 "tradingview MCP 서버를 쓸까요?"라고 묻는다. 허용한다.
3. Claude에게 말한다.
   - `차트 분석해줘` — 판정과 근거 1~8번을 받는다.
   - `차트에 표시해줘` — 지지·저항·다음 16시간 범위를 트레이딩뷰 차트에 그린다.
4. Claude가 알려 주는 `analyzer/tv/out/chart.html`을 브라우저에서 열면, 같은 자료로 그린 분석기 화면이 나온다. 맨 위에 "트레이딩뷰 … 읽음"이라고 표시된다.
5. 다 쓰면 트레이딩뷰를 닫고 평소처럼 다시 연다. 디버그 포트를 열어 둔 채로 두지 않는다.

Claude 없이 터미널에서만 쓸 수도 있다.

```
node analyzer/tv/analyze.cjs --from-tv --page analyzer/tv/out/chart.html
```

맥과 윈도우에서 명령이 같다. 도구가 차트의 종목과 주기를 읽어 확인한 뒤 4시간봉 500개를 가져온다.

## 안전하게 쓰기

| 위험 | 해 둔 것 |
|---|---|
| 디버그 포트(9222)가 열려 있으면 PC의 다른 프로그램도 로그인된 트레이딩뷰를 조종할 수 있다 | 쓸 때만 띄우고, 끝나면 닫는다. 포트를 외부에 열지 않는다 |
| 연결 도구에 임의 코드 실행(`ui_evaluate`), 자동 업데이트(`tv_update`), 알림·스크립트·관심종목 변경 도구가 있다 | `.claude/settings.json`에서 막았다 |
| 연결 도구 저장소가 바뀌면 다른 코드가 들어온다 | 읽어 본 판으로 고정했다. 판을 올릴 때는 바뀐 내용을 먼저 읽는다 |
| 트레이딩뷰 약관은 자동 수집을 제한한다. 계정이 정지될 수 있다 | 사람이 요청할 때만 한 번씩 읽는다. 반복 실행을 만들지 않는다 |
| 다른 종목·다른 주기를 읽고 판정할 수 있다 | 도구가 종목·주기·봉 간격을 확인하고, 다르면 멈춘다 |

## 한계

- 트레이딩뷰에서 한 번에 읽는 봉은 최대 500개(약 83일)다. 그래서 일봉 평균선은 계산하지 않고, "2026-09-29 이후 성적"도 이 범위 안에서만 계산한다.
- 연결 도구는 트레이딩뷰의 공개되지 않은 내부 기능을 쓴다. 트레이딩뷰가 업데이트되면 안 될 수 있다.
- 윈도우용 설치 스크립트(`setup.ps1`)는 실행해 보지 못했다. 맥·리눅스용(`setup.sh`)만 실행해 봤다.
- 이 저장소의 시험은 저장해 둔 과거 자료를 트레이딩뷰 출력 모양으로 바꿔서 한 것이다. 실제 트레이딩뷰 연결은 클라우드 작업 환경에서 시험하지 못했다. 처음 쓸 때 종가와 거래량이 트레이딩뷰 화면의 값과 같은지 눈으로 확인한다.

## 연결이 안 될 때

- `tv_health_check`가 실패하면 트레이딩뷰가 디버그 모드로 떠 있는지 본다: `curl http://127.0.0.1:9222/json/version`
- "봉 자료가 없습니다"가 나오면 차트가 다 뜬 뒤 다시 실행한다.
- "차트가 4시간봉이 아닙니다"가 나오면 차트 주기를 4시간으로 바꾼다.

## 윈도우에서 디버그 포트가 안 열릴 때

윈도우용 트레이딩뷰는 스토어 방식(MSIX)으로 설치된다. 일부 PC에서는 이 설치본을 디버그 모드로 띄우는 것이 막혀 있다. 그때는 둘 중 하나를 쓴다.

- Claude에게 `tv_launch로 트레이딩뷰를 디버그 모드로 띄워줘`라고 말한다. 연결 도구가 트레이딩뷰를 `%LOCALAPPDATA%\tradingview-mcp\` 아래로 한 번 복사한 뒤 거기서 띄운다.
- 직접 하려면 PowerShell에서:
  ```
  $pkg = (Get-AppxPackage TradingView.Desktop).InstallLocation
  Copy-Item "$pkg\*" "$env:LOCALAPPDATA\tradingview-mcp\TradingView" -Recurse -Force
  & "$env:LOCALAPPDATA\tradingview-mcp\TradingView\TradingView.exe" --remote-debugging-port=9222
  ```

`C:\Program Files\WindowsApps` 폴더의 권한은 바꾸지 않는다. 앱 업데이트가 깨질 수 있다.
복사본은 트레이딩뷰가 업데이트돼도 따라 올라가지 않는다. 안 맞으면 복사본 폴더를 지우고 다시 복사한다.

## 시험

```
node --test analyzer/test/core.test.cjs
node analyzer/build.cjs        # src/를 고친 뒤 index.html 다시 만들기
```
