"""G1 백테스트 설정 — RULES_SPEC v1.0의 모든 숫자를 한곳에 모은다.

규칙
- 명세의 숫자는 여기서만 정의한다. 다른 모듈은 숫자를 직접 쓰지 말고 `from backtest import config as C`로 가져다 쓴다.
- 주석의 `§`는 docs/RULES_SPEC.md 절, `I-n`은 backtest/DESIGN.md §7 "해석 확정" 번호다.
- 내부 시각은 모두 **int64 나노초(UTC epoch)** 다 (DESIGN §3.1).
- 파일 끝의 "공용 소형 함수"는 여러 모듈이 같은 식을 쓰도록 설계 담당이 구현해 둔 단일 출처다.
  (반올림·비용·시간·as-of 규칙. 고치려면 설계 담당/리드와 먼저 합의한다.)
"""
from __future__ import annotations

import dataclasses
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

SPEC_VERSION = "v1.0"  # 명세 버전 (§11). 결과 파일·TRIALS.md에 기록

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "binance"          # §1 입력 데이터
CACHE_DIR = REPO_ROOT / "data" / "cache"           # 캐시 전용(.gitignore). 여기 말고는 쓰지 않는다
EVENTS_CSV = REPO_ROOT / "data" / "events.csv"     # §6 F3. 없으면 F3 꺼짐(§10-2)
RESULTS_DIR = REPO_ROOT / "backtest" / "results"   # 결과(JSON·CSV·보고서)
TRIALS_MD = REPO_ROOT / "backtest" / "TRIALS.md"   # §9 시도 기록

# ---------------------------------------------------------------------------
# 시간 단위 (DESIGN §3.1)
# ---------------------------------------------------------------------------
NS_PER_SEC = 1_000_000_000
NS_PER_MIN = 60 * NS_PER_SEC
NS_PER_HOUR = 60 * NS_PER_MIN
NS_PER_DAY = 24 * NS_PER_HOUR

TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
TF_NS = {tf: m * NS_PER_MIN for tf, m in TF_MINUTES.items()}

# §1, §12.1 봉 마감 + 60초에 판단한다 → 봉 사용 가능 시각 = close_ns + AVAIL_DELAY_NS
AVAIL_DELAY_NS = 60 * NS_PER_SEC


def _utc(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value)


# §12.1 실행 봉: 이 시각 이상은 1분봉, 미만은 5분봉 (DESIGN §5)
EXEC_SWITCH_NS = _utc("2023-10-01 00:00")
EXEC_TF_BEFORE = "5m"
EXEC_TF_AFTER = "1m"

# ---------------------------------------------------------------------------
# §2 봉 설정
# ---------------------------------------------------------------------------


class BarSetting(NamedTuple):
    """봉 설정 한 벌: 신호 봉 S, 방향 봉 D, 확인 봉 C (§2)."""

    signal: str
    direction: str
    confirm: str


SETTINGS = {
    "P1": BarSetting(signal="1h", direction="4h", confirm="15m"),  # §2 P1
    "P2": BarSetting(signal="4h", direction="1d", confirm="1h"),   # §2 P2
}
LATENCY_DEFAULT_MIN = 10            # §2 지연 L 기본
LATENCY_SENSITIVITY_MIN = (5, 15)   # §2, §9 민감도

# ---------------------------------------------------------------------------
# §3 기본 수치 (모든 "최근 n개 평균"은 현재 봉 제외, I-2)
# ---------------------------------------------------------------------------
ATR_N = 14                  # §3 ATR = 직전 14개 TR 단순 평균 (I-4)
VR_N = 20                   # §3 VR = volume ÷ 직전 20개 평균
BODY_AVG_N = 20             # §3 장대봉: 직전 20개 평균 몸통
LONG_BAR_MULT = 2.0         # §3 장대봉: 몸통 ≥ 2 × 평균 몸통
SWING_K = 3                 # §3 스윙: 앞뒤 3개, i+3 봉 마감에 확정 (I-6)
SLOPE_NS = (20, 60, 120)    # §3 기울기 N (캔들 카운팅, I-5)
MA_PERIODS = (20, 60, 120)  # §3 이평 확산에 쓰는 이평
SPREAD_LOOKBACK = 500       # §3 확산 판정: 직전 500봉
SPREAD_QUANTILE = 0.80      # §3 "상위 20% 이상" = 80% 분위 이상 (I-3)
BUFFER_ATR_MULT = 0.1       # §3 가격 버퍼 b = 0.1 × ATR

# ---------------------------------------------------------------------------
# §4 구조 (차트프로)
# ---------------------------------------------------------------------------
KIJUN_VR_MIN = 2.0              # §4.1-2 기준봉 VR ≥ 2 (ComboConfig.vr_threshold 기본값)
KIJUN_VR_SENSITIVITY = 3.0      # §9 민감도 "VR 기준 3" (기준봉에만 적용, I-26)
KIJUN_SLOPE_NS = (20, 60)       # §4.1-3 기울기 20·60
KIJUN_MAX_WICK = 0.5            # §4.1-5 꼬리 비율 ≥ 0.5 제외
MADI_B_MAX_BARS = 60            # §4.2 기준봉 후 60봉 안에 B 확정 (I-8)
MADI_PRE_VOL_N = 20             # §4.2 거래량 조건: A 직전 20봉 (I-10)
MADI_ALIVE_BARS = 300           # §4.2 살아 있는 마디: 확정 후 300봉 이내 (I-12)
WAIST_BAND = (0.35, 0.65)       # §4.3 허리 구간 [A+0.35W, A+0.65W]
WAIST_BIN_FRAC = 0.001          # §4.3 칸 폭 = 가격 × 0.001 (I-13)
WAIST_FALLBACK_FRAC = 0.5       # §4.3 대체값 A + 0.5W
WAIST_METHODS = ("cluster", "midpoint")  # §4.3 기본 / §9 민감도 (고+저)÷2

# ---------------------------------------------------------------------------
# §5 방향 필터
# ---------------------------------------------------------------------------
DIRECTION_FILTERS = ("DA", "DB")  # DA = 허리 기준, DB = 이평(기울기) 기준
DB_SLOPE_NS = (60, 120)           # §5 DB: 기울기 60·120

# ---------------------------------------------------------------------------
# §6 공통 고정 필터
# ---------------------------------------------------------------------------
F2_VR_MAX = 0.7                   # §6 F2 VR < 0.7
F2_ATR_LOOKBACK = 100             # §6 F2 직전 100봉 ATR
F2_ATR_QUANTILE = 0.20            # §6 F2 하위 20% (I-3)
F3_BEFORE_NS = 2 * NS_PER_HOUR    # §6 F3 발표 전 2시간
F3_AFTER_NS = 1 * NS_PER_HOUR     # §6 F3 발표 후 1시간
F5_LOOKBACK = 5                   # §6 F5 직전 5봉 (I-16)
F5_RANGE_ATR_MULT = 3.0           # §6 F5 범위 ≥ 3 × ATR
F6_LOOKBACK = 48                  # §6 F6 직전 48봉 (I-17)
F6_RETURN_BARS = 5                # §6 F6 5봉 안에 복귀하면 트랩
F6_MIN_TRAPS = 2                  # §6 F6 트랩 2회 이상이면 박스
F8_MAX_STOPS = 2                  # §6 F8 같은 마디 2회 손절 (I-19)
MAX_OPEN_PLANS = 1                # §6 F9 최대 1포지션(미체결 주문 포함, I-20)

# ---------------------------------------------------------------------------
# §7 진입 시나리오
# ---------------------------------------------------------------------------
SCENARIOS = ("L1a", "L1b", "S2", "S3")
SCENARIO_SIDE = {"L1a": +1, "L1b": +1, "S2": -1, "S3": -1}  # +1 롱, -1 숏
SCENARIO_ORDER_TYPE = {"L1a": "limit", "L1b": "ioc_cap", "S2": "limit", "S3": "limit"}
SCENARIO_APPLIES_F7 = {"L1a": True, "L1b": True, "S2": False, "S3": True}  # §7.3 S2는 F7 제외

PRICE_TICK = 0.1                 # §7 공통: 가격은 0.1 USDT 단위 반올림 (I-14)

L1A_VALID_BARS = 24              # §7.1 유효 24봉
L1A_SLOPE_N = 60                 # §7.1 기울기 60 ≥ 0
L1A_EXTENSION_W = 0.5            # §7.1 고가 > B + 0.5W 이면 취소

L1B_ZONE_W = 0.25                # §7.2 준비: 저가 ∈ [H, H + 0.25W]
L1B_ARM_BARS = 24                # §7.2 준비 후 24개 신호 봉 안에 확인
L1B_CAP_MULT = 1.001             # §7.2 상한 지정가 = 확인 봉 종가 × 1.001
L1B_MAX_CLOSES_BELOW_H = 2       # §7.2 종가가 H 아래로 두 번 마감하면 폐기

S2_VR_MIN = 2.0                  # §7.3 음봉 VR ≥ 2 (고정, vr_threshold와 무관 I-26)
S2_STOP_ATR_MULT = 0.5           # §7.3 손절 max(X 고가, H + 0.5ATR) + b
S2_VALID_BARS = 12               # §7.3 유효 12봉

S3_LOOKBACK = 100                # §7.4 최근 100봉 (I-25)
S3_TOUCH_TOL = 0.001             # §7.4 S ± 0.1%
S3_MIN_TOUCHES = 2               # §7.4 2번 이상
S3_VR_MIN = 2.0                  # §7.4 VR ≥ 2 (고정, I-26)
S3_REBREAK_WINDOW = 10           # §7.4 최근 10봉 안 두 번째 종가 이탈
S3_STOP_ATR_MULT = 1.0           # §7.4 손절 S + ATR
S3_VALID_BARS = 12               # §7.4 유효 12봉

# ---------------------------------------------------------------------------
# §8.1 리스크 검사
# ---------------------------------------------------------------------------
STOP_MIN_PCT = 0.004             # §8.1 손절 폭 하한 max(0.4%, 1 × ATR)
STOP_MIN_ATR = 1.0
STOP_MAX_PCT = 0.02              # §8.1 손절 폭 상한 min(2%, 3 × ATR)
STOP_MAX_ATR = 3.0
MIN_NET_RR = 1.5                 # §8.1, §12.2 순손익비 ≥ 1.5
RISK_FRACTION = 0.005            # §8.1, §10-5 1회 위험 r = 0.5%
MAX_NOTIONAL_FRAC = 0.6          # §8.1 명목 ≤ R 자본 × 0.6 (폐기 아님, 수량 축소 I-28)
MAX_LEVERAGE = 3                 # §8.1 레버리지 ≤ 3

# ---------------------------------------------------------------------------
# §8.2 / §12.1~12.2 체결·비용
# ---------------------------------------------------------------------------
ORDER_TYPES = ("limit", "ioc_cap", "market")  # market = 무작위 기준선 전용(§12.4)
FEE_MAKER = 0.0002               # §8.2 메이커 0.02%
FEE_TAKER = 0.0005               # §8.2 테이커 0.05%
SLIPPAGE = 0.0002                # §12.2 손절·시간 청산 슬리피지 0.02%(불리한 방향)
MAX_HOLD_BARS = 72               # §12.2 진입 후 신호 봉 72개 (I-34)
FUNDING_INTERVAL_NS = 8 * NS_PER_HOUR          # 펀딩 8시간 간격(데이터 확인: 00·08·16 UTC)
FUNDING_FALLBACK_RATE = 0.0001                 # §12.2 데이터 없는 구간 0.01%
FUNDING_FALLBACK_FROM_NS = _utc("2026-09-01 00:00")  # §12.2 "2026-09 이후"

# §8.2, §10-3, §12.3 가용성 마스크 (KST = UTC+9)
KST_OFFSET_NS = 9 * NS_PER_HOUR
DND_START_MIN_KST = 30           # KST 00:30 (포함)
DND_END_MIN_KST = 7 * 60 + 30    # KST 07:30 (미포함)
DAILY_APPROVAL_CAP = 6           # KST 하루 승인 요청 6건 초과분 실행 불가

# 보고용 시간대(KST 분 단위, [시작, 끝)). DEV_GUIDE §6.15 "시간대별(낮·저녁·심야)"
KST_SESSIONS = {
    "day": ((7 * 60 + 30, 18 * 60),),                  # 낮 07:30~18:00
    "evening": ((18 * 60, 24 * 60), (0, 30)),          # 저녁 18:00~00:30
    "night": ((30, 7 * 60 + 30),),                     # 심야 00:30~07:30 (= 방해 금지)
}

# ---------------------------------------------------------------------------
# §8.3 G1 합격 기준 (사전 등록)
# ---------------------------------------------------------------------------
G1_MIN_MEAN_R = 0.15             # 1. 거래당 평균 R ≥ +0.15
G1_MIN_PF = 1.2                  # 3. PF ≥ 1.2
G1_COST_STRESS_MULT = 2.0        # 4. 비용 2배에서도 평균 R > 0
G1_RANDOM_QUANTILE = 0.95        # 5. 무작위 기준선 평균 R의 95% 분위보다 높음
G1_YEARS = tuple(range(2020, 2027))  # 6. 7개 연도 (2020~2026)
G1_MIN_POSITIVE_YEARS = 4        # 6. 4개 이상 양수
G1_MIN_TRADES = 30               # 7. 30건 미만이면 판정 보류
G3_TARGET_SIGNALS = 150          # 보고용: G3 실행 가능 신호 150건까지 걸리는 기간(PLAN D1)

# ---------------------------------------------------------------------------
# §12.4 통계·기준선
# ---------------------------------------------------------------------------
RANDOM_SEED = 20260930           # 모든 난수의 기본 시드 (결정성, DESIGN §3.5)
BOOTSTRAP_N = 10_000             # 복원 추출 10,000회
BOOTSTRAP_LOWER_Q = 0.025        # 평균의 2.5% 분위 = 하한
DSR_N_TRIALS = 16                # DSR 시도 수 N = 16
DSR_REPORT_STRONG = 0.95         # 보고용(판정 조건 아님): 통과 후보의 DSR이 이 값 미만이면 결론에 '근거 약함'을 붙인다
PERM_N = 10_000                  # 순열(부호 뒤집기) 검정 횟수 (I-42)
RANDOM_REPS = 1_000              # 무작위 기준선 반복
RANDOM_REPS_REDUCED = 300        # 너무 오래 걸리면 300회(보고서에 명시)
DONCHIAN_PERIODS = (20, 55, 100)  # 일봉 돈치안 돌파 기간
DONCHIAN_EXIT_DIVISOR = 2         # 청산 기간 = 기간 // 2 (10, 27, 50)
DONCHIAN_NOTIONAL_CAP = 0.6       # 전체 명목 ≤ 0.6배 (세 전략 각 0.2)

# ---------------------------------------------------------------------------
# §9 조합 설정
# ---------------------------------------------------------------------------
SETTING_NAMES = tuple(SETTINGS)  # ("P1", "P2")


@dataclass(frozen=True)
class ComboConfig:
    """조합 하나(시나리오 × 방향 필터 × 봉 설정)와 실행 옵션.

    - 기본 16조합: latency 10분, 허리 cluster, VR 2, 비용 1배.
    - apply_availability_mask=True → "실행 가능"(G1 판정 기준), False → "전체" 결과 (§12.3).
    - vr_threshold는 §4.1 기준봉에만 쓴다(S·D 모두). S2·S3의 VR ≥ 2는 고정 (I-26).
    - cost_multiplier는 실현 손익 계산에만 쓴다. 리스크 검사·R 분모는 항상 기본 비용 (I-27, I-29).
    - event_filter_on=True인데 data/events.csv가 없으면 오류로 멈춘다 (§6 F3, §10-2).
    - l1b_rearm=True는 L1b 전용 진단(보고만): 마디당 준비 1회(§7.2, I-22) 대신 검토 전 구현(옛 I-22) 해석인
      "에피소드가 끝나면 같은 마디에서 다시 준비"를 쓴다. 판정·조합 선택에 쓰지 않는다 (L1B_REARM_VARIANT).
    """

    scenario: str
    direction_filter: str
    setting: str
    latency_min: int = LATENCY_DEFAULT_MIN
    waist_method: str = "cluster"
    vr_threshold: float = KIJUN_VR_MIN
    cost_multiplier: float = 1.0
    apply_availability_mask: bool = True
    event_filter_on: bool = False
    l1b_rearm: bool = False

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError(f"scenario는 {SCENARIOS} 중 하나: {self.scenario!r}")
        if self.direction_filter not in DIRECTION_FILTERS:
            raise ValueError(f"direction_filter는 {DIRECTION_FILTERS} 중 하나: {self.direction_filter!r}")
        if self.setting not in SETTINGS:
            raise ValueError(f"setting은 {SETTING_NAMES} 중 하나: {self.setting!r}")
        if self.waist_method not in WAIST_METHODS:
            raise ValueError(f"waist_method는 {WAIST_METHODS} 중 하나: {self.waist_method!r}")
        if int(self.latency_min) != self.latency_min or self.latency_min < 0:
            raise ValueError(f"latency_min은 0 이상 정수(분): {self.latency_min!r}")
        if not self.vr_threshold > 0:
            raise ValueError(f"vr_threshold는 양수: {self.vr_threshold!r}")
        if not self.cost_multiplier >= 0:
            raise ValueError(f"cost_multiplier는 0 이상: {self.cost_multiplier!r}")
        if self.l1b_rearm and self.scenario != "L1b":
            raise ValueError(f"l1b_rearm은 L1b 전용 진단: scenario={self.scenario!r}")

    # --- 파생 값 ---------------------------------------------------------
    @property
    def bars(self) -> BarSetting:
        """이 조합의 S·D·C 봉 이름."""
        return SETTINGS[self.setting]

    @property
    def side(self) -> int:
        """시나리오 방향: +1 롱, -1 숏."""
        return SCENARIO_SIDE[self.scenario]

    @property
    def order_type(self) -> str:
        """진입 주문 형태: 'limit' 또는 'ioc_cap'."""
        return SCENARIO_ORDER_TYPE[self.scenario]

    @property
    def latency_ns(self) -> int:
        """지연 L (ns)."""
        return int(self.latency_min) * NS_PER_MIN

    @property
    def s_dur_ns(self) -> int:
        """신호 봉 S 한 개의 길이 (ns)."""
        return TF_NS[self.bars.signal]

    @property
    def max_hold_ns(self) -> int:
        """시간 청산까지 길이 = 신호 봉 72개 (§12.2, I-34)."""
        return MAX_HOLD_BARS * self.s_dur_ns

    @property
    def base_key(self) -> str:
        """기본 조합 이름. 예: 'L1a-DA-P1'."""
        return f"{self.scenario}-{self.direction_filter}-{self.setting}"

    @property
    def variant(self) -> str:
        """기본값과 다른 옵션 꼬리표. 예: 'lat5', 'mid', 'vr3', 'cost2', 'ev', 'rearm' ('_'로 연결)."""
        parts = []
        if self.latency_min != LATENCY_DEFAULT_MIN:
            parts.append(f"lat{int(self.latency_min)}")
        if self.waist_method != "cluster":
            parts.append("mid")
        if self.vr_threshold != KIJUN_VR_MIN:
            parts.append(f"vr{self.vr_threshold:g}")
        if self.cost_multiplier != 1.0:
            parts.append(f"cost{self.cost_multiplier:g}")
        if self.event_filter_on:
            parts.append("ev")
        if self.l1b_rearm:
            parts.append("rearm")
        return "_".join(parts)

    @property
    def mode(self) -> str:
        """'exec'(가용성 마스크 적용) 또는 'all'(마스크 없음)."""
        return "exec" if self.apply_availability_mask else "all"

    @property
    def key(self) -> str:
        """실행 하나의 고유 이름(파일명 안전). 예: 'L1a-DA-P1_exec', 'S3-DB-P2_lat5_exec'."""
        v = self.variant
        return f"{self.base_key}_{v}_{self.mode}" if v else f"{self.base_key}_{self.mode}"

    def replace(self, **changes) -> "ComboConfig":
        """일부 값만 바꾼 새 설정."""
        return dataclasses.replace(self, **changes)

    def as_dict(self) -> dict:
        """JSON 기록용 사전."""
        d = dataclasses.asdict(self)
        d.update(key=self.key, base_key=self.base_key, variant=self.variant, mode=self.mode)
        return d


# §9 민감도(선택에 쓰지 않음, 보고만): (꼬리표, 바꿀 값)
SENSITIVITY_VARIANTS = (
    ("lat5", {"latency_min": 5}),
    ("lat15", {"latency_min": 15}),
    ("mid", {"waist_method": "midpoint"}),
    ("vr3", {"vr_threshold": KIJUN_VR_SENSITIVITY}),
    ("cost2", {"cost_multiplier": G1_COST_STRESS_MULT}),
)
# 명세 §9 민감도 목록 밖의 진단(보고만, L1b 조합에만): 검토 전 구현(옛 I-22)의 해석 "에피소드가 끝나면 같은 마디에서 다시 준비"
# (검토 SPEC-L1B-REARM → 기본은 마디당 준비 1회, I-22). sensitivity_combos()의 80개에는 넣지 않는다.
L1B_REARM_VARIANT = ("rearm", {"l1b_rearm": True})


def g1_combos(apply_availability_mask: bool = True) -> list[ComboConfig]:
    """§9의 16개 조합 (순서 고정: 시나리오 → 방향 필터 → 봉 설정)."""
    return [
        ComboConfig(scenario=s, direction_filter=d, setting=p,
                    apply_availability_mask=apply_availability_mask)
        for s in SCENARIOS for d in DIRECTION_FILTERS for p in SETTING_NAMES
    ]


def sensitivity_combos() -> list[tuple[str, ComboConfig]]:
    """§9 민감도 목록: 16조합 × 5변형 = 80개 (모두 '실행 가능' 모드). (꼬리표, 설정) 쌍."""
    out = []
    for base in g1_combos(apply_availability_mask=True):
        for tag, changes in SENSITIVITY_VARIANTS:
            out.append((tag, base.replace(**changes)))
    return out


# ===========================================================================
# 공용 소형 함수 (설계 담당 구현, 단일 출처) — DESIGN §6.1
# ===========================================================================


def stable_seed(text: str) -> int:
    """문자열 → 고정 정수 (파이썬 hash()는 실행마다 달라서 쓰지 않는다)."""
    return zlib.crc32(text.encode("utf-8"))


def make_rng(*parts: str) -> np.random.Generator:
    """결정적 난수 생성기: RANDOM_SEED와 문자열 조각으로 시드를 만든다 (DESIGN §3.5)."""
    return np.random.default_rng([RANDOM_SEED, *[stable_seed(p) for p in parts]])


def ts_ns(value) -> int:
    """시각(문자열·Timestamp·datetime) → int64 ns. 시간대가 없으면 UTC로 본다."""
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.value)  # Timestamp.value는 항상 ns (pandas 3에서도)


def ns_to_iso(ns) -> str:
    """int ns → 'YYYY-MM-DDTHH:MM:SSZ' (None이면 빈 문자열)."""
    if ns is None:
        return ""
    return pd.Timestamp(int(ns), unit="ns", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def round_price(x):
    """§7 공통: 가격을 0.1 USDT 단위로 반올림 (numpy 반올림, I-14). 스칼라면 float를 돌려준다."""
    r = np.round(np.asarray(x, dtype=np.float64), 1)
    return float(r) if r.ndim == 0 else r


def entry_fee_rate(order_type: str) -> float:
    """진입 수수료율: 지정가 = 메이커, IOC 상한·시장가 = 테이커 (§8.2, §12.1)."""
    if order_type == "limit":
        return FEE_MAKER
    if order_type in ("ioc_cap", "market"):
        return FEE_TAKER
    raise ValueError(f"알 수 없는 주문 형태: {order_type!r}")


def c_stop_per_unit(entry, stop, entry_rate: float):
    """§12.2 c_stop = 진입 수수료 + 손절 테이커 수수료 + 손절 슬리피지 (단위당, 기본 비용)."""
    return entry_rate * entry + (FEE_TAKER + SLIPPAGE) * stop


def risk_per_unit(entry, stop, entry_rate: float):
    """§12.2 R 분모 = d + c_stop, d = |진입가 − 손절가| (기본 비용, I-29).

    진입가: 신호 단계 리스크 검사는 계획 가격, 체결 뒤 R 분모는 실제 체결가(지정가는 둘이 같고,
    L1b IOC 상한·시장가는 첫 실행 봉 시가 — 손절 = 정확히 −1R, 무작위 기준선과 같은 단위).
    """
    return np.abs(entry - stop) + c_stop_per_unit(entry, stop, entry_rate)


def net_rr(side: int, entry, stop, target, entry_rate: float):
    """§12.2 순손익비 = (목표까지 거리 − 진입 수수료 − 목표 메이커 수수료) ÷ (d + c_stop).

    방향을 반영한다: 목표가 반대편이면 음수가 된다(→ 검사 실패).
    """
    reward = side * (target - entry) - entry_rate * entry - FEE_MAKER * target
    return reward / risk_per_unit(entry, stop, entry_rate)


def kst_day_index(ns):
    """KST 날짜 번호 (KST 자정 기준 일수). 하루 승인 한도 집계용 (§12.3)."""
    return np.floor_divide(np.asarray(ns, dtype=np.int64) + KST_OFFSET_NS, NS_PER_DAY)


def kst_minute_of_day(ns):
    """KST 하루 중 분 (0~1439)."""
    return np.floor_divide(np.asarray(ns, dtype=np.int64) + KST_OFFSET_NS, NS_PER_MIN) % (24 * 60)


def in_dnd(ns):
    """방해 금지 시간 여부: KST [00:30, 07:30) (§8.2, §12.3, I-38)."""
    m = kst_minute_of_day(ns)
    return (m >= DND_START_MIN_KST) & (m < DND_END_MIN_KST)


def kst_session(ns) -> str:
    """보고용 시간대 이름: 'day' | 'evening' | 'night' (KST_SESSIONS)."""
    m = int(kst_minute_of_day(ns))
    for name, ranges in KST_SESSIONS.items():
        if any(lo <= m < hi for lo, hi in ranges):
            return name
    raise AssertionError("KST_SESSIONS가 하루를 다 덮지 않는다")


def asof_index(avail_ns, query_ns):
    """as-of 정렬 (§1, I-1): 사용 가능 시각 avail_ns ≤ query_ns 인 마지막 봉 번호, 없으면 -1.

    avail_ns는 오름차순이어야 한다(보통 close_ns + AVAIL_DELAY_NS).
    예) 1H 봉 판단 시각(마감+60초)에 4H 정보를 쓸 때:
        asof_index(d_close_ns + AVAIL_DELAY_NS, s_close_ns + AVAIL_DELAY_NS)
    """
    idx = np.searchsorted(np.asarray(avail_ns, dtype=np.int64), np.asarray(query_ns, dtype=np.int64),
                          side="right") - 1
    return int(idx) if np.ndim(idx) == 0 else idx.astype(np.int64)
