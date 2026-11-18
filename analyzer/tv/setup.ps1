# 윈도우용. 트레이딩뷰 연결 도구(tradingview-mcp)를 이 저장소의 vendor\ 폴더에 받는다.
# - 우리가 읽어 본 판(커밋)으로 고정해서 받는다. 최신판을 자동으로 따라가지 않는다.
# - 설치 중 스크립트 실행을 끈다(--ignore-scripts).
# 쓰는 법(저장소 폴더, PowerShell):
#   powershell -ExecutionPolicy Bypass -File analyzer\tv\setup.ps1
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/tradesdontlie/tradingview-mcp"
$Pin  = "c05b8f5755ed8e64ea242de88ddbf46aa24d56a4"   # 2026-07-28 판. 2026-11-18에 읽어 봄
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Dest = Join-Path $Root "vendor\tradingview-mcp"

function Stop-With($msg) { Write-Host $msg; exit 1 }
function Run($exe, $arguments) {
  & $exe @arguments
  if ($LASTEXITCODE -ne 0) { Stop-With "실패했습니다: $exe $($arguments -join ' ')" }
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Stop-With "Node.js가 없습니다. https://nodejs.org 에서 18 이상(LTS)을 설치한 뒤 PowerShell을 새로 열고 다시 실행하세요." }
if (-not (Get-Command git  -ErrorAction SilentlyContinue)) { Stop-With "git이 없습니다. https://git-scm.com/download/win 에서 설치한 뒤 PowerShell을 새로 열고 다시 실행하세요." }
$major = [int](& node -p "process.versions.node.split('.')[0]")
if ($major -lt 18) { Stop-With "Node.js $major 입니다. 18 이상이 필요합니다." }

if (-not (Test-Path (Join-Path $Dest ".git"))) {
  New-Item -ItemType Directory -Force -Path (Join-Path $Root "vendor") | Out-Null
  Run "git" @("clone", "--quiet", $Repo, $Dest)
}
Run "git" @("-C", $Dest, "fetch", "--quiet", "origin")
Run "git" @("-C", $Dest, "checkout", "--quiet", "--detach", $Pin)
$head = (& git -C $Dest rev-parse HEAD).Trim()
if ($head -ne $Pin) { Stop-With "고정한 판을 받지 못했습니다." }

Push-Location $Dest
try { Run "npm.cmd" @("ci", "--ignore-scripts", "--no-audit", "--no-fund", "--omit=dev", "--silent") }
finally { Pop-Location }

Push-Location (Join-Path $Root "analyzer\platform")
try { Run "npm.cmd" @("ci", "--ignore-scripts", "--no-audit", "--no-fund", "--omit=dev", "--silent") }
finally { Pop-Location }

Write-Host "받았습니다: vendor\tradingview-mcp (판 $($Pin.Substring(0,7))), 자동 분석 플랫폼의 부품"
Write-Host "다음: 1) 트레이딩뷰를 디버그 모드로 실행   vendor\tradingview-mcp\scripts\launch_tv_debug.bat"
Write-Host "      2) 자동 분석 켜기   node analyzer\platform\server.cjs   (안내: analyzer\platform\README.md)"
Write-Host "         또는 이 폴더에서 claude 를 실행하고  '차트 분석해줘' 라고 말하기"
