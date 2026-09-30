"""G1 백테스트 공용 자료형 — 표준 프레임, 주문 계획(Plan), 거래 결과(TradeResult), 신호 기록(SignalLog).

모든 모듈이 이 파일의 형식을 그대로 주고받는다 (DESIGN §3.2, §6.2).
- 시각 필드는 모두 int64 ns (UTC epoch). 없으면 None.
- 가격은 float (USDT). 계획 가격은 0.1 단위로 반올림된 값이다 (config.round_price).
- 주의: 이 모듈 이름이 표준 라이브러리 `types`와 같다. 항상 저장소 루트에서
  `python -m backtest.…` 로 실행하고, backtest/ 안에서 파일을 스크립트로 직접 실행하지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Sequence

import numpy as np
import pandas as pd

from backtest import config as C

# ---------------------------------------------------------------------------
# 코드 값 (문자열 상수)
# ---------------------------------------------------------------------------


class Reason:
    """신호 폐기 사유 코드 (SignalLog.reasons). DESIGN §6.7·§6.8."""

    WARMUP = "WARMUP"                        # §12.3 지표 유효 전
    SC_CLOSE_VS_WAIST = "SC_CLOSE_VS_WAIST"  # §7.1 L1a 종가 ≤ H / §7.4 S3 종가 ≥ 최근 상승 마디 허리
    SC_SLOPE60 = "SC_SLOPE60"                # §7.1 L1a 기울기 60 < 0
    SC_UNHEALTHY = "SC_UNHEALTHY"            # §7.1·§7.2 건강한 조정 위반 (L1a 신호 시점, L1b 확인 시점, I-21)
    SC_NO_TARGET = "SC_NO_TARGET"            # §7.4 S3 목표(아래 스윙 저점) 없음
    SC_BAD_GEOMETRY = "SC_BAD_GEOMETRY"      # 손절·진입·목표 순서 이상 (I-45)
    F1 = "F1"  # §6 방향 반대
    F2 = "F2"  # §6 저거래량·저변동성
    F3 = "F3"  # §6 이벤트 (기본 꺼짐)
    F4 = "F4"  # §6 이평 확산
    F5 = "F5"  # §6 급등 쿨다운
    F6 = "F6"  # §6 박스(트랩 2회)
    F7 = "F7"  # §6 살아 있는 반대 마디
    F8 = "F8"  # §6 같은 마디 2손절 (순차 단계)
    F9 = "F9"  # §6 포지션·미체결 주문 보유 중 (순차 단계)
    RISK_STOP_BAND = "RISK_STOP_BAND"  # §8.1 손절 폭
    RISK_RR = "RISK_RR"                # §8.1 순손익비
    MASK_DND = "MASK_DND"              # §12.3 방해 금지 시간 (실행 가능 모드만)
    MASK_DAILY_CAP = "MASK_DAILY_CAP"  # §12.3 하루 6건 초과 (실행 가능 모드만)


# 사유 기록 순서: 앞쪽이 먼저 검사되고 SignalLog.reason(대표 사유)이 된다.
# 앞의 것(WARMUP~RISK_RR)은 시나리오 단계에서 미리 계산, 뒤의 것(F8~MASK)은 순차 엔진이 붙인다.
REASON_ORDER = (
    Reason.WARMUP,
    Reason.SC_CLOSE_VS_WAIST, Reason.SC_SLOPE60, Reason.SC_UNHEALTHY, Reason.SC_NO_TARGET,
    Reason.SC_BAD_GEOMETRY,
    Reason.F1, Reason.F2, Reason.F3, Reason.F4, Reason.F5, Reason.F6, Reason.F7,
    Reason.RISK_STOP_BAND, Reason.RISK_RR,
    Reason.F8, Reason.F9, Reason.MASK_DND, Reason.MASK_DAILY_CAP,
)
PRECOMPUTED_REASONS = REASON_ORDER[: REASON_ORDER.index(Reason.RISK_RR) + 1]
SEQUENTIAL_REASONS = REASON_ORDER[REASON_ORDER.index(Reason.F8):]


class Status:
    """주문 계획의 결과 상태 (TradeResult.status, I-48)."""

    FILLED = "filled"          # 진입 체결 (이후 청산 사유는 exit_reason)
    CANCELLED = "cancelled"    # 취소 효력 시각 전에 체결 안 됨
    EXPIRED = "expired"        # 만료 시각까지 체결 안 됨
    NOT_FILLED = "not_filled"  # IOC 미체결(시가 > 상한) 또는 실행 봉 없음


PLAN_STATUSES = (Status.FILLED, Status.CANCELLED, Status.EXPIRED, Status.NOT_FILLED)


class Exit:
    """청산 사유 (TradeResult.exit_reason)."""

    STOP = "stop"
    TARGET = "target"
    TIME = "time"   # §12.2 신호 봉 72개 경과
    EOD = "eod"     # 데이터 끝까지 청산 안 됨 → 마지막 실행 봉 종가 (I-36)


EXIT_REASONS = (Exit.STOP, Exit.TARGET, Exit.TIME, Exit.EOD)
SIGNAL_STATUSES = ("passed", "discarded")

# 취소 규칙 종류 (CancelRule.kind). 모두 "신호 봉 마감마다" 검사, 효력 = 그 봉 마감 + 60초 (§12.1)
CANCEL_KINDS = (
    "close_below",       # 종가 < level  (L1a: A)
    "close_above",       # 종가 > level  (S2: B, S3: S)
    "high_above",        # 고가 > level  (L1a: B + 0.5W)
    "unhealthy_volume",  # B 다음 봉부터의 평균 거래량 ≥ A~B 평균 (L1a, level = A~B 평균 거래량)
)

# ---------------------------------------------------------------------------
# 표준 봉 프레임 (DESIGN §3.2)
# ---------------------------------------------------------------------------
PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
BAR_COLUMNS = PRICE_COLUMNS + ("open_ns", "close_ns")


def make_bars_frame(open_ns, open_, high, low, close, volume, dur_ns) -> pd.DataFrame:
    """표준 봉 프레임을 만든다.

    - 인덱스: DatetimeIndex(UTC, 단위 ns, 이름 'open_time') = 봉 시작 시각
    - 열: open, high, low, close, volume (float64), open_ns, close_ns (int64)
    - close_ns = open_ns + 봉 길이 (봉이 끝나는 순간). 바이낸스 close_time(−1ms)은 쓰지 않는다.
    dur_ns는 정수 하나(고정 길이) 또는 봉마다의 배열(실행 봉처럼 5분/1분이 섞일 때).
    """
    open_ns = np.asarray(open_ns, dtype=np.int64)
    n = open_ns.shape[0]
    dur = np.broadcast_to(np.asarray(dur_ns, dtype=np.int64), (n,))
    idx = pd.DatetimeIndex(pd.to_datetime(open_ns, unit="ns", utc=True)).as_unit("ns").rename("open_time")
    return pd.DataFrame(
        {
            "open": np.asarray(open_, dtype=np.float64),
            "high": np.asarray(high, dtype=np.float64),
            "low": np.asarray(low, dtype=np.float64),
            "close": np.asarray(close, dtype=np.float64),
            "volume": np.asarray(volume, dtype=np.float64),
            "open_ns": open_ns,
            "close_ns": open_ns + dur,
        },
        index=idx,
    )


def check_bars_frame(df: pd.DataFrame, *, dur_ns: int | None = None, contiguous: bool = True) -> None:
    """표준 봉 프레임 계약을 검사한다. 어기면 ValueError.

    dur_ns를 주면 모든 봉 길이가 같아야 한다. contiguous=True면 빈 구간이 없어야 한다.
    """
    missing = [c for c in BAR_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"열 없음: {missing}")
    for c in PRICE_COLUMNS:
        if df[c].dtype != np.float64:
            raise ValueError(f"{c} 열은 float64여야 함: {df[c].dtype}")
    for c in ("open_ns", "close_ns"):
        if df[c].dtype != np.int64:
            raise ValueError(f"{c} 열은 int64 ns여야 함: {df[c].dtype}")
    if not isinstance(df.index, pd.DatetimeIndex) or str(df.index.tz) != "UTC" or df.index.unit != "ns":
        raise ValueError("인덱스는 DatetimeIndex(UTC, 단위 ns)여야 함 (pandas 3는 기본 단위가 ns가 아닐 수 있다)")
    o_ns = df["open_ns"].to_numpy()
    c_ns = df["close_ns"].to_numpy()
    if not np.array_equal(df.index.asi8, o_ns):
        raise ValueError("인덱스와 open_ns가 다름")
    if len(df) > 1 and not np.all(np.diff(o_ns) > 0):
        raise ValueError("open_ns가 엄격히 증가하지 않음")
    if np.any(c_ns <= o_ns):
        raise ValueError("close_ns ≤ open_ns 인 봉이 있음")
    if dur_ns is not None and np.any(c_ns - o_ns != dur_ns):
        raise ValueError(f"봉 길이가 {dur_ns} ns가 아닌 봉이 있음")
    if contiguous and len(df) > 1 and np.any(c_ns[:-1] != o_ns[1:]):
        raise ValueError("빈 구간(연속되지 않는 봉)이 있음")
    px = df[list(PRICE_COLUMNS)].to_numpy()
    if np.isnan(px).any():
        raise ValueError("가격·거래량에 NaN이 있음")
    o, h, l, c, v = (df[k].to_numpy() for k in PRICE_COLUMNS)
    if np.any(h < np.maximum(o, c)) or np.any(l > np.minimum(o, c)):
        raise ValueError("고가 ≥ max(시가, 종가), 저가 ≤ min(시가, 종가) 위반")
    if np.any(v < 0):
        raise ValueError("음수 거래량")


# ---------------------------------------------------------------------------
# 표준 펀딩 프레임
# ---------------------------------------------------------------------------
FUNDING_COLUMNS = ("time_ns", "rate", "synthetic")


def make_funding_frame(time_ns, rate, synthetic=None) -> pd.DataFrame:
    """표준 펀딩 프레임: time_ns(int64, 정시로 내림), rate(float64), synthetic(bool: 대체값 여부)."""
    time_ns = np.asarray(time_ns, dtype=np.int64)
    syn = np.zeros(time_ns.shape[0], dtype=bool) if synthetic is None else np.asarray(synthetic, dtype=bool)
    return pd.DataFrame({"time_ns": time_ns, "rate": np.asarray(rate, dtype=np.float64), "synthetic": syn})


def check_funding_frame(df: pd.DataFrame) -> None:
    """표준 펀딩 프레임 계약 검사. 어기면 ValueError."""
    missing = [c for c in FUNDING_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"열 없음: {missing}")
    t = df["time_ns"].to_numpy()
    if df["time_ns"].dtype != np.int64 or df["rate"].dtype != np.float64 or df["synthetic"].dtype != bool:
        raise ValueError("dtype: time_ns int64, rate float64, synthetic bool")
    if len(t) > 1 and not np.all(np.diff(t) > 0):
        raise ValueError("time_ns가 엄격히 증가하지 않음")
    if np.isnan(df["rate"].to_numpy()).any():
        raise ValueError("rate에 NaN")


# ---------------------------------------------------------------------------
# 빠른 계산용 배열 묶음 (체결 엔진·무작위 기준선이 쓴다)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecArrays:
    """실행 봉 배열 (DESIGN §5). 인덱스 j는 실행 봉 번호. 배열은 읽기 전용일 수 있다."""

    open_ns: np.ndarray   # int64
    close_ns: np.ndarray  # int64 (= 봉 끝)
    open: np.ndarray      # float64
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    @classmethod
    def from_frame(cls, df: pd.DataFrame) -> "ExecArrays":
        """표준 봉 프레임(실행 봉) → 배열 묶음."""
        return cls(
            open_ns=np.ascontiguousarray(df["open_ns"].to_numpy(dtype=np.int64)),
            close_ns=np.ascontiguousarray(df["close_ns"].to_numpy(dtype=np.int64)),
            open=np.ascontiguousarray(df["open"].to_numpy(dtype=np.float64)),
            high=np.ascontiguousarray(df["high"].to_numpy(dtype=np.float64)),
            low=np.ascontiguousarray(df["low"].to_numpy(dtype=np.float64)),
            close=np.ascontiguousarray(df["close"].to_numpy(dtype=np.float64)),
        )

    def __len__(self) -> int:
        return int(self.open_ns.shape[0])


@dataclass(frozen=True)
class FundingArrays:
    """펀딩 배열 (대체값 포함, 시각 오름차순)."""

    time_ns: np.ndarray  # int64
    rate: np.ndarray     # float64

    @classmethod
    def from_frame(cls, df: pd.DataFrame) -> "FundingArrays":
        """표준 펀딩 프레임 → 배열 묶음."""
        return cls(
            time_ns=np.ascontiguousarray(df["time_ns"].to_numpy(dtype=np.int64)),
            rate=np.ascontiguousarray(df["rate"].to_numpy(dtype=np.float64)),
        )


@dataclass
class MarketData:
    """한 번 불러온 시장 데이터 전체 (data.load_market의 결과)."""

    bars: dict[str, pd.DataFrame]       # 봉 이름('15m','1h','4h','1d') → 표준 봉 프레임
    exec_bars: pd.DataFrame             # 실행 봉(5분+1분 병합) 표준 봉 프레임 (dur 섞임)
    funding: pd.DataFrame               # 표준 펀딩 프레임 (2026-09 이후 대체값 포함)
    events_ns: np.ndarray | None = None  # F3 이벤트 시각(int64 ns). 파일 없으면 None

    def exec_arrays(self) -> ExecArrays:
        """실행 봉 배열 묶음."""
        return ExecArrays.from_frame(self.exec_bars)

    def funding_arrays(self) -> FundingArrays:
        """펀딩 배열 묶음."""
        return FundingArrays.from_frame(self.funding)


# ---------------------------------------------------------------------------
# 구조 (structure.py 결과)
# ---------------------------------------------------------------------------
# 마디 표(pd.DataFrame)의 열. 행 순서 = (tb_idx, kijun_idx) 오름차순, RangeIndex. DESIGN §6.5
MADI_COLUMNS = (
    "madi_id",         # str   고유 ID: f"{tf}{U|D}-{B 봉 시작 시각 YYYYmmddHHMM}" 예 '1hU-202403011000'
    "direction",       # int8  +1 상승 마디, -1 하락 마디
    "kijun_idx",       # int64 기준봉 번호 t
    "a_idx",           # int64 시작점 A 봉 번호 (t 시점 확정 스윙)
    "b_idx",           # int64 끝점 B 봉 번호 (≥ t, I-8)
    "tb_idx",          # int64 마디 확정 봉 번호 = b_idx + 3 (T_B)
    "a_price",         # float A (상승: 스윙 저점 low, 하락: 스윙 고점 high) — 반올림 안 함
    "b_price",         # float B
    "w",               # float W = |B − A| > 0
    "h_cluster",       # float 허리(§4.3 칸 방식, 0.1 반올림)
    "h_mid",           # float 허리((A+B)/2, 0.1 반올림) — 민감도용
    "waist_fallback",  # bool  칸 방식에서 구간 안 값이 없어 A ± 0.5W를 쓴 경우
    "vol_ab_mean",     # float A~B(a_idx..b_idx) 평균 거래량
    "vol_pre_mean",    # float A 직전 20봉 평균 거래량
    "death_idx",       # int64 T_B 뒤 처음 종가가 A를 넘어선(상승: 아래로) 봉, 없으면 n
    "end_idx",         # int64 살아 있는 마지막 봉 = min(death_idx − 1, tb_idx + 300)
    "tb_close_ns",     # int64 T_B 봉 마감 시각
)


@dataclass
class Structure:
    """봉 하나의 간격(tf)에 대한 구조 계산 결과. 모든 배열 길이 = 봉 수 n."""

    tf: str
    is_sh: np.ndarray     # bool  봉 i가 스윙 고점인가 (i+3 봉 마감 전에는 쓰면 안 됨! last_sh를 쓸 것)
    is_sl: np.ndarray     # bool  스윙 저점
    last_sh: np.ndarray   # int64 봉 t 마감 시점에 확정된 가장 최근 스윙 고점 번호(i+3 ≤ t), 없으면 -1
    last_sl: np.ndarray   # int64 같은 규칙의 스윙 저점
    kijun_up: np.ndarray  # bool  상승 기준봉 (§4.1)
    kijun_dn: np.ndarray  # bool  하락 기준봉
    madis: pd.DataFrame   # 마디 표 (MADI_COLUMNS)
    alive_up: np.ndarray  # int64 봉 t에서 살아 있는 상승 마디 중 가장 최근 것의 행 번호(없으면 -1, I-12)
    alive_dn: np.ndarray  # int64 같은 규칙의 하락 마디


@dataclass
class ScenarioContext:
    """봉 설정(P1/P2)·기준봉 VR 기준 하나에 대한 미리 계산된 재료 (scenarios.build_context 결과)."""

    setting: str
    vr_threshold: float
    s_tf: str
    d_tf: str
    c_tf: str
    s_bars: pd.DataFrame
    s_ind: pd.DataFrame        # indicators.compute_indicators(s_bars)
    s_struct: Structure
    d_bars: pd.DataFrame
    d_ind: pd.DataFrame
    d_struct: Structure
    c_bars: pd.DataFrame
    s_flags: pd.DataFrame      # filters.fixed_filter_flags 결과 (열: F2, F4, F5, F6 bool)
    events_ns: np.ndarray | None = None
    cache: dict = field(default_factory=dict)  # 파생값 캐시(예: 방향 허용 배열). 키는 튜플


# ---------------------------------------------------------------------------
# 주문 계획·결과·신호 기록
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CancelRule:
    """취소 규칙 한 줄 (기록·감사용 데이터). 체결 엔진은 Plan.cancel_effective_time만 본다."""

    kind: str                   # CANCEL_KINDS 중 하나
    level: float | None = None  # 비교 기준 가격(또는 거래량 평균)
    note: str = ""              # 사람이 읽을 설명 (예: "종가 < A")


def _iso_fields(obj, names: Sequence[str]) -> dict:
    out = {}
    for n in names:
        v = getattr(obj, n)
        out[n] = C.ns_to_iso(v)
        out[n + "_ns"] = v
    return out


@dataclass(frozen=True)
class Plan:
    """주문 계획 (시나리오 → 체결 엔진). 체결 엔진은 active_from·valid_until·cancel_effective_time만으로 시간을 판정한다.

    시각 규칙 (DESIGN §3.1, §6.7):
    - signal_time  = 신호 봉 마감 시각 (L1b는 확인 봉 마감 시각)
    - approval_time = signal_time + 60초 (판단·승인 요청 시각; 가용성 마스크·F8·F9 판정 기준)
    - active_from  = approval_time + 지연 L (이 시각 이후 시작하는 실행 봉부터 체결 가능)
    - valid_until  = 지정가: signal_time + N × 신호 봉 길이 / ioc_cap·market: active_from (첫 실행 봉만)
    - cancel_effective_time = 취소 조건이 처음 성립한 신호 봉 마감 + 60초 (없으면 None)
    """

    plan_id: str
    scenario: str
    side: int                     # +1 롱, -1 숏
    signal_time: int
    approval_time: int
    active_from: int
    order_type: str               # 'limit' | 'ioc_cap' | 'market'
    entry_price: float            # 지정가 / IOC 상한가 / (market이면 참고값)
    stop: float
    target: float
    valid_until: int
    max_hold_ns: int              # 시간 청산 길이 = 72 × 신호 봉 길이
    atr_at_signal: float          # 손절 폭 검사에 쓴 신호 봉 ATR (§12.2)
    cancel_effective_time: int | None = None
    cancel_reason: str | None = None          # 먼저 성립한 CancelRule.kind
    cancel_rules: tuple[CancelRule, ...] = ()
    madi_id: str | None = None                # 근거 마디 ID (F8). S3는 None (I-19)
    meta: dict = field(default_factory=dict)  # 감사용 부가 정보 (A, B, W, H, s_idx, waist_fallback 등)

    @property
    def order_end(self) -> int:
        """주문이 살아 있는 마지막 시각 = min(valid_until, cancel_effective_time)."""
        if self.cancel_effective_time is None:
            return self.valid_until
        return min(self.valid_until, self.cancel_effective_time)

    def as_record(self) -> dict:
        """CSV 한 줄용 평평한 사전 (시각은 ISO 문자열 + *_ns)."""
        d = {f.name: getattr(self, f.name) for f in fields(self)
             if f.name not in ("cancel_rules", "meta")}
        d.update(_iso_fields(self, ("signal_time", "approval_time", "active_from", "valid_until",
                                    "cancel_effective_time")))
        d["cancel_rules"] = ";".join(f"{r.kind}:{r.level}" for r in self.cancel_rules)
        d["meta"] = json.dumps(self.meta, ensure_ascii=False, sort_keys=True, default=str)
        return d


@dataclass(frozen=True)
class TradeResult:
    """계획 하나를 체결 엔진에 돌린 결과. 금액은 모두 '수량 1단위(BTC 1개)당 USDT'.

    - net_pnl = gross_pnl − fees − slippage − funding (funding 양수 = 지불)
    - r_multiple = net_pnl ÷ risk_per_unit (체결 안 됐으면 NaN) — G1 판정에 쓰는 값 (§12.2, I-29)
    - risk_per_unit = |진입가 − 손절가| + c_stop (기본 비용). 체결되면 실제 체결가 기준(지정가는 계획가와 같고,
      L1b IOC 상한·시장가는 첫 실행 봉 시가 → 손절 = −1R), 미체결이면 계획 가격 기준 참고값 (I-29)
    - size_fraction = min(1, 명목 상한이 허용하는 비율, 계획 가격 기준) — 계좌 기준 보조 지표 (I-28).
      r_account = size_fraction × r_multiple (명목 상한으로 수량을 줄인 효과만 반영한 보조 값)
    - busy_until = 이 계획이 포지션·주문으로 자리를 차지한 마지막 시각 (F9, I-20)
    """

    plan_id: str
    scenario: str
    side: int
    order_type: str
    signal_time: int
    approval_time: int
    active_from: int
    plan_entry: float
    stop: float
    target: float
    status: str                         # PLAN_STATUSES
    busy_until: int
    risk_per_unit: float
    madi_id: str | None = None
    entry_time: int | None = None       # 체결된 실행 봉의 시작 시각
    entry_price: float | None = None
    exit_time: int | None = None        # 청산된 실행 봉의 시작 시각
    exit_price: float | None = None
    exit_reason: str | None = None      # EXIT_REASONS
    exit_bar_close_ns: int | None = None  # 청산 실행 봉의 끝 시각 (F8 판정: 이 시각 ≤ 승인 시각인 손절만 셈)
    fees: float = 0.0
    slippage: float = 0.0
    funding: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    r_multiple: float = float("nan")
    size_fraction: float = 1.0
    cost_multiplier: float = 1.0
    meta: dict = field(default_factory=dict)

    @property
    def is_filled(self) -> bool:
        return self.status == Status.FILLED

    @property
    def r_account(self) -> float:
        """계좌 기준 R = size_fraction × r_multiple (보조)."""
        return self.size_fraction * self.r_multiple

    def as_record(self) -> dict:
        """CSV 한 줄용 평평한 사전."""
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "meta"}
        d.update(_iso_fields(self, ("signal_time", "approval_time", "active_from", "entry_time",
                                    "exit_time", "busy_until")))
        d["r_account"] = self.r_account
        d["meta"] = json.dumps(self.meta, ensure_ascii=False, sort_keys=True, default=str)
        return d


@dataclass(frozen=True)
class SignalLog:
    """신호 후보 한 건의 기록 (통과든 폐기든 모두 남긴다, §6 "걸린 필터는 기록한다")."""

    time: int                      # 판단 시각 = approval_time (ns)
    signal_time: int               # 신호 봉(L1b는 확인 봉) 마감 시각
    scenario: str
    side: int
    status: str                    # 'passed' | 'discarded'
    reasons: tuple[str, ...] = ()  # 폐기 사유 코드 (REASON_ORDER 순서). 통과면 ()
    plan_id: str | None = None
    madi_id: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def reason(self) -> str | None:
        """대표 사유 = 첫 번째 사유."""
        return self.reasons[0] if self.reasons else None

    def as_record(self) -> dict:
        """CSV 한 줄용 평평한 사전."""
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name not in ("reasons", "meta")}
        d.update(_iso_fields(self, ("time", "signal_time")))
        d["reason"] = self.reason
        d["reasons"] = ";".join(self.reasons)
        d["meta"] = json.dumps(self.meta, ensure_ascii=False, sort_keys=True, default=str)
        return d


@dataclass(frozen=True)
class Candidate:
    """시나리오가 내놓는 신호 후보 = 기록 + (가격을 계산할 수 있었으면) 계획.

    규약: log.reasons가 비어 있으면 plan은 반드시 있고, 순차 엔진(execution.run_sequence)으로 간다.
    plan이 None이면 log.reasons는 비어 있지 않다.
    """

    log: SignalLog
    plan: Plan | None = None

    def __post_init__(self) -> None:
        if self.plan is None and not self.log.reasons:
            raise ValueError("plan이 없는 후보는 폐기 사유가 있어야 한다")


def sort_reasons(reasons) -> tuple[str, ...]:
    """사유 코드를 REASON_ORDER 순서로 정렬·중복 제거한다."""
    uniq = set(reasons)
    unknown = uniq.difference(REASON_ORDER)
    if unknown:
        raise ValueError(f"알 수 없는 사유 코드: {sorted(unknown)}")
    return tuple(r for r in REASON_ORDER if r in uniq)


def records_frame(items: Sequence[Any]) -> pd.DataFrame:
    """Plan·TradeResult·SignalLog 목록 → DataFrame (CSV 저장용)."""
    return pd.DataFrame([x.as_record() for x in items])


def to_jsonable(obj: Any) -> Any:
    """numpy 값·dataclass를 JSON에 넣을 수 있는 값으로 바꾼다.

    NaN → None(계산 불가), +inf → "inf", −inf → "-inf"(예: 손실 없는 PF). 결과 JSON에 NaN 토큰이 생기지 않는다.
    """
    if hasattr(obj, "__dataclass_fields__"):
        return to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        if np.isnan(f):
            return None
        if np.isinf(f):
            return "inf" if f > 0 else "-inf"
        return f
    return obj
