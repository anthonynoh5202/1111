"""A4 공통 모듈 — 데이터 읽기, 비용 가정, 거래 1건 채점 엔진, 통계 함수.

이 폴더(scratchpad/team/A4)의 모든 스크립트가 같은 비용·같은 R 정의·같은 채점 규칙을 쓰도록 여기 한곳에 모은다.
저장소(/home/user/1111)는 읽기만 한다(데이터 파일). 캐시는 A4/cache/ 에만 쓴다.

공통 가정(00_context.md '퀀트 공통 가정')
- 수수료: 테이커 0.05%/편, 메이커 0.02%/편. 시장가·손절 슬리피지 0.02%/편(불리한 쪽).
- 펀딩: 로컬 실제 값(~2026-08-31), 그 뒤 0.01%/8시간 가정. 롱은 양(+) 펀딩을 낸다.
- R 분모 = |진입가 − 손절가| + 진입 수수료 + 손절 테이커 수수료 + 손절 슬리피지 (저장소 G1·G1-T와 같은 정의 → 손절 = 정확히 −1R).
- 채점 봉: 2023-10-01 전 5분봉, 이후 1분봉(로컬에 1분봉이 2023-10부터만 있음).
- 한 봉에서 손절·목표가 모두 닿으면 손절(보수적). 갭으로 손절 너머에서 시작하면 그 봉 시가(더 불리)로 청산.
- 지정가 진입은 '관통'(롱: 저가 < 지정가)해야 체결, 체결가 = 지정가, 메이커. 체결 봉에서 손절가까지 내려갔으면 그 봉에서 손절(보수적),
  체결 봉의 목표 도달은 인정하지 않는다(체결 전 고가였을 수 있으므로).
- 시각은 내부적으로 int64 ns(UTC). 보고는 KST로 바꿔 쓴다.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

REPO = Path("/home/user/1111")
DATA = REPO / "data" / "binance"
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OUT = HERE / "out"
CACHE.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

NS_MIN = 60 * 1_000_000_000
NS_HOUR = 60 * NS_MIN
NS_DAY = 24 * NS_HOUR
KST = 9 * NS_HOUR

FEE_TAKER = 0.0005
FEE_MAKER = 0.0002
SLIP = 0.0002
FUND_FALLBACK = 0.0001          # 0.01% / 8h
FUND_FALLBACK_FROM = int(pd.Timestamp("2026-09-01", tz="UTC").value)
EXEC_SWITCH = int(pd.Timestamp("2023-10-01", tz="UTC").value)   # 이 시각부터 1분봉

IS_START = int(pd.Timestamp("2020-01-01", tz="UTC").value)
IS_END = int(pd.Timestamp("2024-01-01", tz="UTC").value)        # [IS_START, IS_END)
OOS_START = IS_END
OOS_END = int(pd.Timestamp("2026-09-29", tz="UTC").value)       # 데이터 끝(2026-09-28 23:59) 다음 날
CLEAN_START = int(pd.Timestamp("2026-07-01", tz="UTC").value)   # Claude 학습 시점 이후로 보는 '깨끗한' 구간
PERIODS = {"IS": (IS_START, IS_END), "OOS": (OOS_START, OOS_END)}

TF_NS = {"1m": NS_MIN, "5m": 5 * NS_MIN, "15m": 15 * NS_MIN, "1h": NS_HOUR, "4h": 4 * NS_HOUR, "1d": NS_DAY}

ND = NormalDist()


def utc(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value)


def iso_kst(ns) -> str:
    if ns is None or (isinstance(ns, float) and not np.isfinite(ns)):
        return ""
    return pd.Timestamp(int(ns) + KST, unit="ns").strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 데이터
# ---------------------------------------------------------------------------
@dataclass
class Bars:
    """OHLC 배열 묶음. t = 봉 시작 시각(ns), dur = 봉 길이(ns)."""
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    dur: np.ndarray

    def __len__(self) -> int:
        return len(self.t)

    @property
    def close_t(self) -> np.ndarray:
        return self.t + self.dur


def _read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=["open_time", "open", "high", "low", "close", "volume"])
    return df


def load_tf(tf: str) -> Bars:
    """한 시간 단위 봉 읽기(캐시 사용). 1m은 2023~2026 파일을 이어 붙인다."""
    cp = CACHE / f"bars_{tf}.npz"
    if cp.exists():
        z = np.load(cp)
        return Bars(**{k: z[k] for k in ("t", "o", "h", "l", "c", "v", "dur")})
    if tf == "1m":
        parts = [_read_csv(DATA / f"BTCUSDT_1m_{y}.csv.gz") for y in (2023, 2024, 2025, 2026)]
        df = pd.concat(parts, ignore_index=True)
    else:
        df = _read_csv(DATA / f"BTCUSDT_{tf}.csv.gz")
    df = df.sort_values("open_time").drop_duplicates("open_time")
    t = df["open_time"].to_numpy(np.int64) * 1_000_000
    arr = {k: df[n].to_numpy(np.float64) for k, n in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume"))}
    dur = np.full(len(t), TF_NS[tf], dtype=np.int64)
    np.savez(cp, t=t, dur=dur, **arr)
    return Bars(t=t, dur=dur, **arr)


def load_exec() -> Bars:
    """채점용 실행 봉: 2023-10-01 전 5분봉 + 이후 1분봉."""
    cp = CACHE / "bars_exec.npz"
    if cp.exists():
        z = np.load(cp)
        return Bars(**{k: z[k] for k in ("t", "o", "h", "l", "c", "v", "dur")})
    b5 = load_tf("5m")
    b1 = load_tf("1m")
    m5 = b5.t < EXEC_SWITCH
    m1 = b1.t >= EXEC_SWITCH
    cat = {k: np.concatenate([getattr(b5, k)[m5], getattr(b1, k)[m1]]) for k in ("t", "o", "h", "l", "c", "v", "dur")}
    assert np.all(np.diff(cat["t"]) > 0)
    np.savez(cp, **cat)
    return Bars(**cat)


def load_funding() -> tuple[np.ndarray, np.ndarray]:
    """(펀딩 시각 ns, 펀딩률). 2026-09-01부터 데이터 끝 + 30일까지 0.01%/8h 대체값을 붙인다."""
    df = pd.read_csv(DATA / "BTCUSDT_fundingRate.csv.gz")
    t = df["calc_time"].to_numpy(np.int64) * 1_000_000
    # 펀딩 시각은 00/08/16 UTC 정각(+수 ms). 정각으로 내림.
    t = (t // NS_HOUR) * NS_HOUR
    r = df["last_funding_rate"].to_numpy(np.float64)
    keep = t < FUND_FALLBACK_FROM
    t, r = t[keep], r[keep]
    ft = np.arange(FUND_FALLBACK_FROM, OOS_END + 30 * NS_DAY, 8 * NS_HOUR, dtype=np.int64)
    t = np.concatenate([t, ft])
    r = np.concatenate([r, np.full(len(ft), FUND_FALLBACK)])
    o = np.argsort(t, kind="stable")
    return t[o], r[o]


def atr(b: Bars, n: int = 14) -> np.ndarray:
    """ATR(n) 단순 평균. 값 i = 봉 i까지(봉 i 포함, 마감된 봉) TR n개 평균. 봉 i 마감 뒤에만 쓸 수 있다."""
    prev_c = np.concatenate([[np.nan], b.c[:-1]])
    tr = np.nanmax(np.vstack([b.h - b.l, np.abs(b.h - prev_c), np.abs(b.l - prev_c)]), axis=0)
    s = pd.Series(tr).rolling(n, min_periods=n).mean().to_numpy()
    return s


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def asof_value(src_close_t: np.ndarray, src_val: np.ndarray, query_t: np.ndarray) -> np.ndarray:
    """query_t 시점까지 마감된 마지막 봉의 값(미래 정보 없음)."""
    idx = np.searchsorted(src_close_t, query_t, side="right") - 1
    out = np.full(len(query_t), np.nan)
    ok = idx >= 0
    out[ok] = src_val[idx[ok]]
    return out


# ---------------------------------------------------------------------------
# 거래 1건 채점 엔진 (무작위 기준선·추천 채점이 같은 함수를 쓴다)
# ---------------------------------------------------------------------------
@dataclass
class TradeOut:
    status: str            # 'filled' | 'unfilled' | 'nodata'
    exit_kind: str = ""    # 'target' | 'stop' | 'time' | 'signal'
    entry_t: int = 0
    entry_px: float = float("nan")
    exit_t: int = 0
    exit_px: float = float("nan")
    r_den: float = float("nan")    # 단위(1 BTC)당 R 분모 (USDT)
    r: float = float("nan")        # 순 R (수수료·슬리피지·펀딩 포함)
    r_gross: float = float("nan")  # 가격만의 R
    cost_r: float = float("nan")   # 비용(수수료+슬리피지+펀딩)이 깎은 R
    fund_r: float = float("nan")
    mfe_r: float = float("nan")
    mae_r: float = float("nan")
    ambiguous: bool = False        # 한 봉 안에서 손절·목표 모두 닿음(손절로 처리)
    res_min: int = 0               # 채점 봉 해상도(분)


class Engine:
    """실행 봉 + 펀딩을 들고, 계획(plan) 하나를 채점한다."""

    def __init__(self, ex: Bars | None = None):
        self.ex = ex if ex is not None else load_exec()
        self.ft, self.fr = load_funding()
        self.fcum = np.concatenate([[0.0], np.cumsum(self.fr)])
        # 펀딩 시각의 가격(그 시각에 시작하는 실행 봉 시가)
        fi = np.searchsorted(self.ex.t, self.ft, side="left")
        fi = np.clip(fi, 0, len(self.ex.t) - 1)
        self.fpx = self.ex.o[fi]
        self.frpx_cum = np.concatenate([[0.0], np.cumsum(self.fr * self.fpx)])

    def idx_at(self, t_ns: int) -> int:
        """시각 t 이상에서 시작하는 첫 실행 봉 번호."""
        return int(np.searchsorted(self.ex.t, t_ns, side="left"))

    def funding_per_unit(self, side: int, t0: int, t1: int) -> float:
        """(t0, t1] 사이 펀딩 시각마다 side × rate × 가격 (단위당 USDT, 양수 = 비용)."""
        a = int(np.searchsorted(self.ft, t0, side="right"))
        b = int(np.searchsorted(self.ft, t1, side="right"))
        if b <= a:
            return 0.0
        return side * (self.frpx_cum[b] - self.frpx_cum[a])

    def run(self, side: int, start_t: int, *, stop: float | None = None, target: float | None = None,
            stop_dist: float | None = None, target_r: float | None = None,
            entry: str = "market", limit_px: float | None = None, valid_until: int | None = None,
            max_hold_ns: int = 72 * NS_HOUR, exit_at: int | None = None,
            r_den_override: float | None = None) -> TradeOut:
        """계획 하나 채점.

        side: +1 롱 / −1 숏. start_t: 주문을 낼 수 있게 되는 시각(이 시각 이후 첫 실행 봉부터 본다).
        entry='market': start_t 이후 첫 봉 시가 + 슬리피지, 테이커.
        entry='limit': limit_px 지정가, valid_until까지 관통하면 체결(메이커).
        stop/target: 절대 가격. 또는 stop_dist(가격 거리)·target_r(손절 거리의 배수)로 '기준가'(시장가=첫 봉 시가, 지정가=지정가)에서 만든다.
        max_hold_ns: 체결부터 이 시간이 지나면 다음 봉 시가에 시장가 청산('time').
        exit_at: 이 시각에 시장가 청산(신호 청산, 'signal'). max_hold보다 먼저면 이것을 쓴다.
        r_den_override: 손절이 없는 계획의 '가상 R' 분모(단위당 USDT).
        """
        ex = self.ex
        n = len(ex.t)
        i0 = self.idx_at(start_t)
        if i0 >= n:
            return TradeOut(status="nodata")
        res = int(ex.dur[i0] // NS_MIN)
        # ---- 진입 ----
        if entry == "market":
            ref = ex.o[i0]
            fill_i = i0
            entry_px = ref * (1 + side * SLIP)
            fee_in = FEE_TAKER
        elif entry == "limit":
            assert limit_px is not None and valid_until is not None
            j_end = int(np.searchsorted(ex.t, valid_until, side="left"))  # [i0, j_end)
            if j_end <= i0:
                return TradeOut(status="unfilled")
            seg_l = ex.l[i0:j_end] if side > 0 else ex.h[i0:j_end]
            hit = (seg_l < limit_px) if side > 0 else (seg_l > limit_px)
            if not hit.any():
                if j_end >= n:
                    return TradeOut(status="nodata")
                return TradeOut(status="unfilled")
            fill_i = i0 + int(np.argmax(hit))
            ref = limit_px
            entry_px = limit_px
            fee_in = FEE_MAKER
        else:
            raise ValueError(entry)
        entry_t = int(ex.t[fill_i])
        if stop is None:
            if stop_dist is not None:
                stop = ref - side * stop_dist
        if target is None and target_r is not None and stop is not None:
            target = ref + side * target_r * abs(ref - stop)
        if stop is not None:
            r_den = abs(entry_px - stop) + fee_in * entry_px + (FEE_TAKER + SLIP) * stop
        else:
            assert r_den_override is not None
            r_den = r_den_override
        if not (r_den > 0):
            return TradeOut(status="nodata")
        # ---- 청산 탐색 구간 ----
        end_t = entry_t + max_hold_ns
        if exit_at is not None:
            end_t = min(end_t, exit_at)
        k_end = int(np.searchsorted(ex.t, end_t, side="left"))  # 시간 청산 봉 = k_end (그 봉 시가)
        if k_end >= n:
            return TradeOut(status="nodata")
        lo = ex.l[fill_i:k_end]
        hi = ex.h[fill_i:k_end]
        op = ex.o[fill_i:k_end]
        m = len(lo)
        big = m + 10
        # 손절 닿음
        if stop is not None:
            st_hit = (lo <= stop) if side > 0 else (hi >= stop)
            i_st = int(np.argmax(st_hit)) if st_hit.any() else big
        else:
            i_st = big
        # 목표 닿음 (지정가 체결 봉에서는 목표 인정 안 함)
        if target is not None:
            tg_hit = (hi >= target) if side > 0 else (lo <= target)
            if entry == "limit" and m > 0:
                tg_hit = tg_hit.copy()
                tg_hit[0] = False
            i_tg = int(np.argmax(tg_hit)) if tg_hit.any() else big
        else:
            i_tg = big
        ambiguous = False
        if i_st < big and i_st <= i_tg:
            if i_st == i_tg:
                ambiguous = True
            k = i_st
            if k == 0:
                exit_mid = stop          # 체결 봉 안에서 손절까지 감(시가 = 진입가 또는 지정가 위)
            else:
                exit_mid = min(stop, op[k]) if side > 0 else max(stop, op[k])   # 갭이면 시가(더 불리)
            exit_px = exit_mid * (1 - side * SLIP)
            fee_out = FEE_TAKER
            kind = "stop"
            exit_t = int(ex.t[fill_i + k])
            path_end = k + 1
        elif i_tg < big:
            k = i_tg
            exit_mid = target
            exit_px = target
            fee_out = FEE_MAKER
            kind = "target"
            exit_t = int(ex.t[fill_i + k])
            path_end = k + 1
        else:
            exit_mid = ex.o[k_end]
            exit_px = exit_mid * (1 - side * SLIP)
            fee_out = FEE_TAKER
            kind = "signal" if (exit_at is not None and exit_at <= entry_t + max_hold_ns) else "time"
            exit_t = int(ex.t[k_end])
            path_end = m
        # ---- MFE/MAE (청산 봉까지, 체결가 기준) ----
        if path_end > 0:
            if side > 0:
                fav = np.max(hi[:path_end]) - entry_px
                adv = entry_px - np.min(lo[:path_end])
            else:
                fav = entry_px - np.min(lo[:path_end])
                adv = np.max(hi[:path_end]) - entry_px
            if kind == "target":
                fav = side * (target - entry_px)       # 목표 봉의 나머지 꼬리는 세지 않음
            if kind == "stop":
                adv = side * (entry_px - exit_mid)     # 손절(또는 갭 시가)에서 끝남
            mfe = max(fav, 0.0) / r_den
            mae = max(adv, 0.0) / r_den
        else:
            mfe = mae = 0.0
        fund = self.funding_per_unit(side, entry_t, exit_t)
        gross = side * (exit_px - entry_px)
        r_gross = side * (exit_mid - ref) / r_den
        pnl = gross - fee_in * entry_px - fee_out * exit_px - fund
        r = pnl / r_den
        return TradeOut(status="filled", exit_kind=kind, entry_t=entry_t, entry_px=float(entry_px), exit_t=exit_t,
                        exit_px=float(exit_px), r_den=float(r_den), r=float(r), r_gross=float(r_gross),
                        cost_r=float(r_gross - r), fund_r=float(fund / r_den), mfe_r=float(mfe), mae_r=float(mae),
                        ambiguous=ambiguous, res_min=res)


# ---------------------------------------------------------------------------
# 통계·지표
# ---------------------------------------------------------------------------
def boot_ci(x: np.ndarray, n_boot: int = 10_000, q: float = 0.025, seed: int = 7) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return (float("nan"), float("nan"))
    if len(x) > 3000:   # 큰 표본: 평균의 분포는 사실상 정규 → 정규 근사(속도)
        se = x.std(ddof=1) / math.sqrt(len(x))
        z = ND.inv_cdf(1 - q)
        return float(x.mean() - z * se), float(x.mean() + z * se)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    means = x[idx].mean(axis=1)
    return float(np.quantile(means, q)), float(np.quantile(means, 1 - q))


def block_boot_ci(x: np.ndarray, block: int, n_boot: int = 5_000, q: float = 0.025, seed: int = 7) -> tuple[float, float]:
    """원형 블록 부트스트랩(겹치는 표본용)."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return (float("nan"), float("nan"))
    block = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, nb))
    offs = np.arange(block)
    idx = (starts[:, :, None] + offs[None, None, :]) % n
    idx = idx.reshape(n_boot, -1)[:, :n]
    means = x[idx].mean(axis=1)
    return float(np.quantile(means, q)), float(np.quantile(means, 1 - q))


def max_dd_r(r: np.ndarray) -> float:
    """R 누적 곡선 최대 낙폭(R)."""
    r = np.asarray(r, dtype=float)
    if len(r) == 0:
        return float("nan")
    cum = np.concatenate([[0.0], np.cumsum(r)])
    return float(np.max(np.maximum.accumulate(cum) - cum))


def max_consec_losses(r: np.ndarray) -> int:
    best = cur = 0
    for v in r:
        if v < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def r_summary(r: np.ndarray, hold_h: np.ndarray | None = None) -> dict:
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n == 0:
        return dict(n=0)
    wins = r[r > 0]
    losses = r[r <= 0]
    lo, hi = boot_ci(r)
    out = dict(
        n=n,
        mean=float(r.mean()),
        median=float(np.median(r)),
        std=float(r.std(ddof=1)) if n > 1 else float("nan"),
        win=float((r > 0).mean()),
        avg_win=float(wins.mean()) if len(wins) else float("nan"),
        avg_loss=float(losses.mean()) if len(losses) else float("nan"),
        payoff=float(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else float("nan"),
        pf=float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("inf"),
        ci_lo=lo, ci_hi=hi,
        mdd_r=max_dd_r(r),
        max_losing=max_consec_losses(r),
        sum_r=float(r.sum()),
    )
    if hold_h is not None and len(hold_h):
        out["hold_h"] = float(np.nanmean(hold_h))
    return out


def equity_metrics(t_ns: np.ndarray, eq: np.ndarray) -> dict:
    """자산 곡선(시각, 값) → 연 복리 수익, 최대 낙폭, 연 변동성, 샤프(일 수익 기준)."""
    eq = np.asarray(eq, dtype=float)
    if len(eq) < 2:
        return dict(cagr=float("nan"), mdd=float("nan"), vol=float("nan"), sharpe=float("nan"), total=float("nan"))
    years = (t_ns[-1] - t_ns[0]) / (365.0 * NS_DAY)
    total = eq[-1] / eq[0] - 1
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1 if eq[-1] > 0 else -1.0
    peak = np.maximum.accumulate(eq)
    mdd = float(np.max(1 - eq / peak))
    # 일 단위로 다시 뽑아 변동성
    s = pd.Series(eq, index=pd.to_datetime(t_ns, unit="ns"))
    d = s.resample("1D").last().dropna()
    dr = d.pct_change().dropna()
    vol = float(dr.std() * math.sqrt(365)) if len(dr) > 2 else float("nan")
    sharpe = float(dr.mean() / dr.std() * math.sqrt(365)) if len(dr) > 2 and dr.std() > 0 else float("nan")
    return dict(cagr=float(cagr), mdd=mdd, vol=vol, sharpe=sharpe, total=float(total), years=float(years))


def n_required(sigma: float, delta: float, alpha_one_sided: float = 0.05, power: float = 0.8) -> float:
    za = ND.inv_cdf(1 - alpha_one_sided)
    zb = ND.inv_cdf(power)
    return ((za + zb) * sigma / delta) ** 2


def fmt(x, d=3, pct=False, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    if pct:
        return f"{x*100:+.{d}f}%" if sign else f"{x*100:.{d}f}%"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
