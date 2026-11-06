"""A2 — 차트프로 진입 조건 백테스트 공용 라이브러리 (퀀트② 담당).

- 저장소(/home/user/1111)는 읽기만 한다. backtest.indicators / structure / filters 의 순수 함수만 가져다 쓴다.
  (backtest.data 는 저장소 안 data/cache 에 캐시를 쓰므로 쓰지 않고 CSV 를 직접 읽는다.)
- 시각은 int64 ns(UTC). 봉 시각 = 시작 시각, close_ns = open_ns + 봉 길이.
- 미래 정보 금지: 1시간봉 j 의 판단은 j 마감 시점에 확정된 값만 쓴다. 4시간봉은 close_ns <= 1H 마감 시각인
  마지막 4H 봉(as-of). 스윙(앞뒤 3봉)은 i+3 봉 마감 뒤에만(last_confirmed_swing).
- 체결: 신호 봉 j 마감 → 다음 1H 봉 시가에 시장가 진입(테이커 0.05% + 슬리피지 0.02%).
  손절은 5분봉 경로로 판정(손절 = 테이커+슬리피지, 갭이면 그 5분봉 시가), 목표는 지정가(메이커 0.02%, 관통해야 체결),
  같은 5분봉에서 둘 다 닿으면 손절 먼저(보수적). 72시간(1H 72봉) 안에 안 끝나면 시장가 청산(테이커+슬리피지).
  펀딩: 로컬 실제 값(~2026-08-31), 그 뒤 0.01%/8h. 1R = 진입 체결가 ~ 손절가 거리.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

REPO = "/home/user/1111"
sys.dont_write_bytecode = True   # 저장소 안에 .pyc 를 만들지 않는다(읽기 전용 사용)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backtest import filters as FL  # noqa: E402
from backtest import indicators as IND  # noqa: E402
from backtest import structure as ST  # noqa: E402
from backtest import types as TY  # noqa: E402

DATA = Path(REPO) / "data" / "binance"
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"

NS_MS = 1_000_000
TF_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

# 비용 (팀 공통 가정)
TAKER = 0.0005
MAKER = 0.0002
SLIP = 0.0002
FUND_FALLBACK = 0.0001
FUND_FALLBACK_FROM = int(pd.Timestamp("2026-09-01", tz="UTC").value)

MAX_HOLD_H = 72                 # 최대 보유 72시간
K5 = MAX_HOLD_H * 12            # 5분봉 864개

IS_START = int(pd.Timestamp("2020-01-01", tz="UTC").value)
OOS_START = int(pd.Timestamp("2024-01-01", tz="UTC").value)
END = int(pd.Timestamp("2026-09-29", tz="UTC").value)


# ---------------------------------------------------------------------------
# 데이터
# ---------------------------------------------------------------------------

def load_bars(tf: str) -> pd.DataFrame:
    CACHE.mkdir(exist_ok=True)
    cp = CACHE / f"{tf}.npz"
    if cp.exists():
        z = np.load(cp)
        arr = {k: z[k] for k in z.files}
    else:
        df = pd.read_csv(DATA / f"BTCUSDT_{tf}.csv.gz",
                         usecols=["open_time", "open", "high", "low", "close", "volume"],
                         float_precision="round_trip")
        arr = {"open_ns": df["open_time"].to_numpy(np.int64) * NS_MS}
        for k in ("open", "high", "low", "close", "volume"):
            arr[k] = df[k].to_numpy(np.float64)
        np.savez(cp, **arr)
    return TY.make_bars_frame(arr["open_ns"], arr["open"], arr["high"], arr["low"], arr["close"],
                              arr["volume"], TF_MS[tf] * NS_MS)


def load_funding() -> tuple[np.ndarray, np.ndarray]:
    df = pd.read_csv(DATA / "BTCUSDT_fundingRate.csv.gz")
    t = (df["calc_time"].to_numpy(np.int64) // 60_000) * 60_000 * NS_MS   # 분 단위로 내림(정시 + 수 ms)
    r = df["last_funding_rate"].to_numpy(np.float64)
    keep = t < FUND_FALLBACK_FROM
    t, r = t[keep], r[keep]
    # 2026-09-01 이후: 0.01% / 8시간 (00·08·16 UTC)
    extra = np.arange(FUND_FALLBACK_FROM, END + 10 * 86_400 * 10**9, 8 * 3600 * 10**9, dtype=np.int64)
    return np.r_[t, extra], np.r_[r, np.full(extra.shape, FUND_FALLBACK)]


# ---------------------------------------------------------------------------
# 시장 상태(지표·구조·국면)
# ---------------------------------------------------------------------------

class Market:
    def __init__(self):
        self.b1 = load_bars("1h")
        self.b4 = load_bars("4h")
        self.b5 = load_bars("5m")
        self.ind1 = IND.compute_indicators(self.b1)
        self.ind4 = IND.compute_indicators(self.b4)
        self.st1 = ST.build_structure(self.b1, self.ind1, "1h")
        self.st4 = ST.build_structure(self.b4, self.ind4, "4h")
        b1, b4 = self.b1, self.b4
        self.o1, self.h1, self.l1, self.c1, self.v1 = (b1[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
        self.t1 = b1["open_ns"].to_numpy()
        self.ct1 = b1["close_ns"].to_numpy()
        self.n1 = len(b1)
        self.atr1 = self.ind1["atr"].to_numpy()
        self.vr1 = self.ind1["vr"].to_numpy()
        self.c4 = b4["close"].to_numpy()
        self.v4 = b4["volume"].to_numpy()
        self.t4 = b4["open_ns"].to_numpy()
        self.ct4 = b4["close_ns"].to_numpy()
        # 1H 봉 j 마감 시각에 확정된 마지막 4H 봉 번호 (as-of)
        self.i4 = np.searchsorted(self.ct4, self.ct1, side="right") - 1
        # 4H 1시간 단위 시작 위치 (4H 봉 k 의 첫 1H 봉 번호)
        self.j_of_4h = np.searchsorted(self.t1, self.t4, side="left")

        # ---- 쉬는 구간 필터 (국면 = 4H 기준, as-of) ----
        #  F2 거래 없음·저변동 (VR<0.7 그리고 ATR 직전 100봉 하위 20%) [CP-01-10]
        #  F4 이평 확산 (MA20·60·120 폭이 직전 500봉 상위 20%) [CP-09-4]
        #  BOX 양방향 트랩: 직전 48개 4H 봉(8일) 안에 지지 트랩 ≥1 그리고 저항 트랩 ≥1 [CP-16]
        #     (트랩 = 종가가 확정 스윙 저점 아래로 이탈 후 5봉 안 종가 복귀 / 저항 쪽 대칭 — backtest.filters.trap_events)
        ff4 = FL.fixed_filter_flags(self.b4, self.ind4, self.st4)
        n4 = len(self.b4)
        ev = FL.trap_events(self.b4, self.st4)
        cnt = {}
        for kind in ("support", "resistance"):
            done = np.zeros(n4, dtype=np.int64)
            e = ev[ev["kind"] == kind]
            np.add.at(done, e["done_idx"].to_numpy(np.int64), 1)
            cs = np.r_[0, np.cumsum(done)]
            t = np.arange(n4)
            cnt[kind] = cs[t + 1] - cs[np.maximum(t + 1 - 48, 0)]      # 완성 봉 ∈ [t−47, t] (t 마감 시점에 앎)
        self.box4 = (cnt["support"] >= 1) & (cnt["resistance"] >= 1)
        self.f2_4 = ff4["F2"].to_numpy()
        self.f4_4 = ff4["F4"].to_numpy()
        self.valid4 = self.ind4["valid"].to_numpy()
        self.rest4 = self.f2_4 | self.f4_4 | self.box4 | ~self.valid4
        self.valid1 = self.ind1["valid"].to_numpy()
        self.spread1 = self.ind1["spread_on"].to_numpy()

        # ---- 4H 국면 DB(이평): 기울기 60·120 + 배열 ----
        i4 = self.ind4
        s60, s120 = i4["slope60"].to_numpy(), i4["slope120"].to_numpy()
        m20, m60, m120 = i4["ma20"].to_numpy(), i4["ma60"].to_numpy(), i4["ma120"].to_numpy()
        with np.errstate(invalid="ignore"):
            inv = (m20 < m60) & (m60 < m120)        # 역배열
            reg = (m20 > m60) & (m60 > m120)        # 정배열
            self.db_long4 = (s60 > 0) & (s120 > 0) & ~inv
            self.db_short4 = (s60 < 0) & (s120 < 0) & ~reg
        # ---- 4H 국면 DA(마디·허리): 살아 있는 마디 + 종가가 허리의 맞는 쪽 ----
        md = self.st4.madis
        self.madis4 = md
        self.H4 = md["h_cluster"].to_numpy() if len(md) else np.array([])
        up, dn = self.st4.alive_up, self.st4.alive_dn
        hu = np.where(up >= 0, self.H4[np.clip(up, 0, None)] if len(md) else np.nan, np.nan)
        hd = np.where(dn >= 0, self.H4[np.clip(dn, 0, None)] if len(md) else np.nan, np.nan)
        with np.errstate(invalid="ignore"):
            self.da_long4 = (up >= 0) & (self.c4 > hu)
            self.da_short4 = (dn >= 0) & (self.c4 < hd)

        ok4 = self.i4 >= 0
        g = np.clip(self.i4, 0, None)

        def on1(a4):
            return ok4 & a4[g]
        self.db_long = on1(self.db_long4)
        self.db_short = on1(self.db_short4)
        self.da_long = on1(self.da_long4)
        self.da_short = on1(self.da_short4)
        self.rest1 = ~ok4 | self.rest4[g] | ~self.valid1      # True = 쉬는 구간 → 진입 안 함

        # ---- 1H 스윙 (앞뒤 3봉, i+3 마감 뒤 확정) ----
        self.last_sh1 = self.st1.last_sh
        self.last_sl1 = self.st1.last_sl

        self.month1 = (pd.to_datetime(self.t1, utc=True).year * 100 + pd.to_datetime(self.t1, utc=True).month).to_numpy()

    # 국면(같은 국면 필터) 마스크: 무작위 기준선의 표본 공간
    #  level 'full' = 방향(4H) + 쉬는 구간 제외(4H)  ← 본 시험(차트프로 규칙 그대로)
    #  level 'dir'  = 방향(4H)만 (쉬는 구간 필터 끔)  ← 추가 점검
    #  level 'none' = 4H 이평 방향·쉬는 구간 없음(S2·S3는 마디 조건만 남김) ← 추가 점검(1H 패턴 자체의 힘)
    def regime_mask(self, name: str, level: str = "full") -> np.ndarray:
        if level == "none":
            m = {"DB_L": np.ones(self.n1, bool), "DB_S": np.ones(self.n1, bool),
                 "DADB_L": self.da_long, "DADB_S": self.da_short}[name] & self.valid1
        else:
            m = {"DB_L": self.db_long, "DB_S": self.db_short,
                 "DADB_L": self.db_long & self.da_long, "DADB_S": self.db_short & self.da_short}[name]
            m = m & self.valid1
            if level == "full":
                m = m & ~self.rest1
            elif level != "dir":
                raise ValueError(level)
        out = m.copy()
        out[-(MAX_HOLD_H + 2):] = False          # 데이터 끝 72시간은 진입 안 함
        return out


# ---------------------------------------------------------------------------
# 체결 엔진 (5분봉 경로, 이진 탐색)
# ---------------------------------------------------------------------------

class Engine:
    def __init__(self, mk: Market, funding: tuple[np.ndarray, np.ndarray]):
        b5 = mk.b5
        o5, h5, l5, c5 = (b5[k].to_numpy() for k in ("open", "high", "low", "close"))
        t5 = b5["open_ns"].to_numpy()
        assert t5[0] == mk.t1[0] and len(t5) == 12 * mk.n1, "5분봉과 1시간봉 정렬 불일치"
        pad = K5 + 24
        last = c5[-1]
        self.o5 = np.r_[o5, np.full(pad, last)]
        self.h5 = np.r_[h5, np.full(pad, last)]
        self.l5 = np.r_[l5, np.full(pad, last)]
        self.c5 = np.r_[c5, np.full(pad, last)]
        self.t5 = np.r_[t5, t5[-1] + 300 * 10**9 * np.arange(1, pad + 1)]
        n1 = mk.n1
        starts = 12 * (np.arange(n1) + 1)          # 1H 봉 j 의 다음 봉 시가 = 5분봉 12(j+1)
        self.starts = starts
        self.RMlow = np.minimum.accumulate(sliding_window_view(self.l5, K5)[starts], axis=1)
        self.RMhigh = np.maximum.accumulate(sliding_window_view(self.h5, K5)[starts], axis=1)
        ft, fr = funding
        idx = np.searchsorted(self.t5, ft, side="left")     # 펀딩 시각 F 이후 첫 5분봉(시작 시각 >= F)
        add = np.zeros(self.t5.shape[0] + 1)
        np.add.at(add, np.clip(idx, 0, self.t5.shape[0]), fr)
        self.cf = np.cumsum(add)[:-1]               # cf[i] = sum(rate : F <= t5[i])

    @staticmethod
    def _first(M, rows, level, pred):
        """행마다 단조인 M[rows, :] 에서 pred(M, level)이 처음 참인 열 (없으면 K5)."""
        lo = np.zeros(rows.shape[0], dtype=np.int64)
        hi = np.full(rows.shape[0], K5, dtype=np.int64)
        while True:
            act = lo < hi
            if not act.any():
                break
            mid = (lo + hi) // 2
            v = M[rows, np.minimum(mid, K5 - 1)]
            ok = pred(v, level)
            hi = np.where(act & ok, mid, hi)
            lo = np.where(act & ~ok, mid + 1, lo)
        return lo

    def simulate(self, j, side, stop=None, target=None, d_atr=None, t_r=None, atr=None):
        """신호 봉 j(배열) 마감 → 다음 봉 시가 진입. 반환 dict of arrays.

        stop/target 이 가격으로 주어지거나(실제 신호), d_atr(손절 거리 ÷ ATR)·t_r(목표 R 배수)이 주어진다(무작위).
        target=None 이고 t_r 가 주어지면 목표 = 진입 + t_r × d.
        """
        j = np.asarray(j, dtype=np.int64)
        s = self.starts[j]
        pe0 = self.o5[s]
        pe = pe0 * (1 + side * SLIP)
        if stop is None:
            stop = pe - side * np.asarray(d_atr) * np.asarray(atr)
        stop = np.asarray(stop, dtype=np.float64)
        d = side * (pe - stop)
        if target is None:
            target = pe + side * np.asarray(t_r) * d
        target = np.asarray(target, dtype=np.float64)
        if side > 0:
            ks = self._first(self.RMlow, j, stop, lambda v, x: v <= x)
            kt = self._first(self.RMhigh, j, target, lambda v, x: v > x)
        else:
            ks = self._first(self.RMhigh, j, stop, lambda v, x: v >= x)
            kt = self._first(self.RMlow, j, target, lambda v, x: v < x)
        hit_s = (ks < K5) & (ks <= kt)              # 같은 5분봉이면 손절 먼저
        hit_t = (kt < K5) & ~hit_s
        kx = np.where(hit_s, ks, np.where(hit_t, kt, K5 - 1))
        ox = self.o5[s + np.minimum(kx, K5 - 1)]
        if side > 0:
            sfill = np.minimum(stop, ox)
        else:
            sfill = np.maximum(stop, ox)
        px = np.where(hit_s, sfill * (1 - side * SLIP),
                      np.where(hit_t, target, self.c5[s + K5 - 1] * (1 - side * SLIP)))
        fee_x = np.where(hit_t, MAKER, TAKER)
        fsum = self.cf[s + kx] - self.cf[s]
        with np.errstate(divide="ignore", invalid="ignore"):
            r_gross = side * (px - pe) / d
            r_cost = (TAKER * pe + fee_x * px) / d
            r_fund = -side * fsum * pe / d          # 펀딩 손익(R): 롱은 양(+) 펀딩이면 낸다 → 음수
            r = r_gross - r_cost + r_fund
        kind = np.where(hit_s, "stop", np.where(hit_t, "target", "time"))
        hold_h = (kx + 1) / 12.0
        exit_ns = self.t5[s + kx] + 300 * 10**9
        return {"j": j, "entry_ns": self.t5[s], "pe": pe, "stop": stop, "target": target, "d": d,
                "r": r, "r_gross": r_gross, "r_cost": r_cost, "r_fund": r_fund, "kind": kind,
                "hold_h": hold_h, "exit_ns": exit_ns, "t_r": side * (target - pe) / d,
                "d_pct": d / pe}


# ---------------------------------------------------------------------------
# 성과 지표
# ---------------------------------------------------------------------------

def metrics(r: np.ndarray, hold_h: np.ndarray | None = None) -> dict:
    r = np.asarray(r, dtype=np.float64)
    n = int(r.shape[0])
    if n == 0:
        return {"n": 0}
    w = r[r > 0]
    lo = r[r <= 0]
    cum = np.cumsum(r)
    peak = np.maximum.accumulate(np.r_[0.0, cum])[1:]
    mdd = float(np.max(peak - cum)) if n else 0.0
    pf = float(w.sum() / -lo.sum()) if lo.sum() < 0 else float("inf")
    rng = np.random.default_rng(12345)
    bs = r[rng.integers(0, n, size=(2000, n))].mean(axis=1)
    out = {"n": n, "win": float((r > 0).mean()), "avg_win": float(w.mean()) if w.size else 0.0,
           "avg_loss": float(lo.mean()) if lo.size else 0.0, "exp": float(r.mean()),
           "pf": pf, "mdd": mdd, "sum": float(r.sum()),
           "ci_lo": float(np.quantile(bs, 0.025)), "ci_hi": float(np.quantile(bs, 0.975))}
    if hold_h is not None:
        out["hold_h"] = float(np.mean(hold_h))
    return out


def sequential(sig_j: np.ndarray, res: dict) -> np.ndarray:
    """한 번에 1포지션: 신호 시간 순으로, 앞 거래가 끝난 뒤의 신호만 받는다. 받은 신호의 위치(불리언)를 돌려준다."""
    order = np.argsort(sig_j, kind="stable")
    take = np.zeros(sig_j.shape[0], dtype=bool)
    busy_until = -1
    for k in order:
        if res["entry_ns"][k] >= busy_until:
            take[k] = True
            busy_until = res["exit_ns"][k]
    return take
