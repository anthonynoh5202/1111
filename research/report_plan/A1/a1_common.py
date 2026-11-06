"""A1(퀀트① 계좌·사이징·레버리지) 공통 상수·적재 함수.

- 저장소 파일은 읽기만 한다(/home/user/1111/data/binance). 네트워크를 쓰지 않는다.
- 모든 시각은 UTC ms. 보고용 시각 표기는 KST(+9h)로 바꿔서 쓴다.
- 거래 규칙 값의 출처·확인 상태는 A1_sizing.md §1 표에 있다. 여기 값은 그 표와 같아야 한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("/home/user/1111/data/binance")
OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(exist_ok=True)

# ---- 계좌·환율(가정) -------------------------------------------------------
KRW_PER_USDT = 1400.0                 # 00_context 가정
ACCOUNT_KRW = 50_000
ACCOUNT_USDT = ACCOUNT_KRW / KRW_PER_USDT   # 35.714...

# ---- 거래 규칙 (BTCUSDT 무기한, USDⓈ-M) -------------------------------------
# MIN_NOTIONAL: 2026-04-14 06:30 UTC부터 100 → 50 USDT (뉴스 3곳 + ccxt exchangeInfo 스냅샷(2026-06-26 이후)에서 50)
BTC_MIN_NOTIONAL_NOW = 50.0
BTC_MIN_NOTIONAL_OLD = 100.0          # 2023-11 ~ 2026-04-13 (팀 공통 가정에 있던 값, 비교용)
BTC_STEP = 0.001                      # LOT_SIZE stepSize = minQty = 0.001 BTC
BTC_TICK = 0.10                       # PRICE_FILTER tickSize
MMR_TIER1 = 0.004                     # 0~300,000 USDT 구간 유지증거금률 0.40%, 누적액(cum) 0 (freqtrade 스냅샷)
LIQ_FEE = 0.0125                      # exchangeInfo liquidationFee(청산 수수료율) 1.25% — 격리면 어차피 증거금 전부 잃음
NEW_ACCOUNT_MAX_LEV = 20              # 2025-12-07부터 신규 선물 계정 30일간 20배 초과 불가(검색 요약)

# ---- 비용(팀 공통 가정, VIP0) ---------------------------------------------
TAKER = 0.0005
MAKER = 0.0002
SLIP = 0.0002                         # 시장가 1편당 슬리피지 가정
FUNDING_DEFAULT_8H = 0.0001           # 2026-09 이후 데이터 없을 때 가정

# 기본 왕복 비용: 진입 시장가(테이커+슬리피지) + 청산 시장가(테이커+슬리피지) = 0.14%
COST_ALL_MARKET = 2 * (TAKER + SLIP)
# 지정가 진입(메이커, 슬리피지 0) + 손절 시장가 = 0.09%
COST_MAKER_IN = MAKER + TAKER + SLIP

REF_PRICE = 83_461.0                  # 로컬 데이터 마지막 종가(2026-09-28 23:00 UTC 1h봉)

IS_START = "2024-01-01"               # 분석 구간(OOS) 시작
IS_END = "2026-09-29"                 # 끝(데이터 마지막 2026-09-28)


def krw(usdt: float) -> float:
    return usdt * KRW_PER_USDT


def load_klines(tf: str) -> pd.DataFrame:
    """1h·4h·1d 등 단일 파일 캔들. index = open_time(UTC Timestamp)."""
    path = DATA_DIR / f"BTCUSDT_{tf}.csv.gz"
    df = pd.read_csv(path, usecols=["open_time", "open", "high", "low", "close"],
                     dtype={"open_time": np.int64}, float_precision="round_trip")
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.drop(columns=["open_time"]).astype(float)


def load_1m(years=(2024, 2025, 2026)) -> pd.DataFrame:
    parts = []
    for y in years:
        path = DATA_DIR / f"BTCUSDT_1m_{y}.csv.gz"
        df = pd.read_csv(path, usecols=["open_time", "open", "high", "low", "close"],
                         dtype={"open_time": np.int64}, float_precision="round_trip")
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.drop(columns=["open_time"]).astype(float)


def load_funding() -> pd.DataFrame:
    path = DATA_DIR / "BTCUSDT_fundingRate.csv.gz"
    df = pd.read_csv(path, dtype={"calc_time": np.int64})
    df.index = pd.to_datetime(df["calc_time"], unit="ms", utc=True)
    return df


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> np.ndarray:
    """Wilder ATR. TR[0]=high−low. 첫 값은 앞 n개 TR 평균, 이후 (prev×(n−1)+TR)/n."""
    prev = np.r_[np.nan, close[:-1]]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    tr[0] = high[0] - low[0]
    atr = np.full_like(tr, np.nan)
    atr[n - 1] = tr[:n].mean()
    for i in range(n, len(tr)):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def swing_points(high: np.ndarray, low: np.ndarray, k: int = 3):
    """저장소 backtest.indicators.swing_points와 같은 규칙: 앞뒤 k봉보다 엄격히 높/낮음."""
    n = len(high)
    is_sh = np.zeros(n, dtype=bool)
    is_sl = np.zeros(n, dtype=bool)
    hc, lc = high[k:n - k], low[k:n - k]
    sh = np.ones(n - 2 * k, dtype=bool)
    sl = np.ones(n - 2 * k, dtype=bool)
    for d in range(1, k + 1):
        sh &= (hc > high[k - d:n - k - d]) & (hc > high[k + d:n - k + d])
        sl &= (lc < low[k - d:n - k - d]) & (lc < low[k + d:n - k + d])
    is_sh[k:n - k] = sh
    is_sl[k:n - k] = sl
    return is_sh, is_sl


def liq_distance(lev: float, side: str = "long", mmr: float = MMR_TIER1, cum: float = 0.0,
                 notional: float = 1.0, fee_from_margin: float = 0.0) -> float:
    """격리 마진 청산가까지 거리(진입가 대비 비율).

    바이낸스 공식(freqtrade binance.dry_run_liquidation_price와 같음, 격리라 교차 변수 0):
      LP = (WB + cum − s·Q·EP) / (Q·MMR − s·Q),  s = +1(롱) / −1(숏), WB = 격리 증거금
    EP=1, Q=notional로 두면 거리만 나온다. fee_from_margin: 증거금에서 빠지는 수수료 비율(보수적 가정용).
    """
    q = notional
    wb = notional / lev - fee_from_margin * notional
    s = 1 if side == "long" else -1
    lp = (wb + cum - s * q * 1.0) / (q * mmr - s * q)
    return (1.0 - lp) if side == "long" else (lp - 1.0)


def max_lev_for_liq(d_req: float, side: str = "long", mmr: float = MMR_TIER1) -> int:
    """청산 거리 ≥ d_req를 만족하는 가장 큰 정수 레버리지."""
    best = 1
    for lev in range(1, 151):
        if liq_distance(lev, side, mmr) >= d_req:
            best = lev
        else:
            break
    return best


def pct(x: float, nd: int = 2) -> str:
    return f"{x * 100:.{nd}f}%"
