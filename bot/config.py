"""설정 로더·검증·비밀 파일 읽기 — 설계 담당 소유 (bot/DESIGN.md §6, §7).

규칙
- 설정은 TOML 파일 하나(bot.toml). 모르는 키가 있으면 거부(오타로 기본값이 조용히 쓰이는 것을 막는다).
- 전략 숫자(기간 20·55·100, 2×ATR20, 비용)는 설정이 아니다: backtest.trend / backtest.config 상수를 그대로 쓴다.
  설정의 strategy_key는 'E0-L-ENS' 하나만 허용(확인용).
- 비밀(텔레그램 토큰, Claude API 키, 헬스체크 URL)은 **파일 경로로만** 받는다. 값은 환경 변수·설정 파일·로그에 두지 않는다.
  환경 변수에 비밀 이름이 있으면 시작을 거부한다(check_env_no_secrets).
- 텔레그램 설정 변경 불가: 이 모듈은 파일만 읽는다. 바꾸려면 서버에서 파일을 고치고 재시작한다.
- 모드는 replay / paper 만. live 는 이 단계에 없다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

from bot.types import Mode

STRATEGY_KEY = "E0-L-ENS"          # TREND_SPEC v1.0 조합(사용자 위임으로 확정)
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_EFFORT = "medium"
SECRET_MAX_BYTES = 4096

# 이 이름이 환경 변수에 있으면 시작 거부 (비밀은 파일로만).
FORBIDDEN_ENV_NAMES = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN", "BOT_TOKEN",
    "BINANCE_API_KEY", "BINANCE_API_SECRET", "BINANCE_SECRET_KEY",
    "HEALTHCHECK_URL", "HEALTHCHECKS_URL",
})
_FORBIDDEN_ENV_RE = re.compile(r"^(BOT|TELEGRAM|ANTHROPIC|CLAUDE|BINANCE|HEALTHCHECKS?)_.*(TOKEN|SECRET|KEY|PASSWORD|URL)$")
# 일반 규칙(SEC-07): 접두사와 무관하게 이름이 비밀 모양이면 거부. GPG_KEY(베이스 이미지)·*_URL 일반은 걸리지 않는다.
_FORBIDDEN_ENV_GENERIC_RE = re.compile(
    r"^(?:.*_)?(?:TOKEN|SECRET|SECRET_KEY|API_KEY|APIKEY|PASSWORD|PASSWD|PING_URL|PRIVATE_KEY|ACCESS_KEY)$")
# 비밀이 아닌데 위 규칙에 걸리는 이름(명시 허용 목록). 필요할 때만 추가한다.
ALLOWED_ENV_NAMES = frozenset()

# 확정 설계값(PLAN §4·SECURITY PV-17: 설정은 조이는 방향만). 설정은 이 값 '이하'만 허용한다.
MAX_APPROVAL_WINDOW_S = 7200          # 승인 유효 2시간
MAX_CONFIRM_WINDOW_S = 60             # [승인] 뒤 [확인] 60초
MAX_CLOCK_SKEW_MS = 1000              # PV-30
# 시세 호스트 허용 목록(가짜 시세 → 가짜 신호 차단). 테스트넷은 TESTNET 단계에서 검토 후 추가.
ALLOWED_MARKET_BASE_URLS = frozenset({"https://fapi.binance.com"})
# 텔레그램 봇 토큰 모양(숫자 ID:문자열). 다른 비밀 파일을 잘못 넣으면(예: sk-ant- 키) 시작 전에 거부한다(SEC-01).
TELEGRAM_TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{20,64}$")


class ConfigError(ValueError):
    """설정·비밀 파일 오류. 메시지에 비밀 값을 절대 넣지 않는다."""


# ---------------------------------------------------------------------------
# 비밀
# ---------------------------------------------------------------------------


class Secret:
    """비밀 문자열 래퍼. repr/str/format 어디에도 값이 나오지 않는다. 값은 reveal()로만 꺼낸다."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:  # 비교는 허용하지 않는다(실수로 로그에 남는 비교식 방지)
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    def __reduce__(self):  # pickle로 새지 않게
        raise TypeError("Secret은 직렬화할 수 없다")


def read_secret(path: str | os.PathLike[str]) -> Secret:
    """비밀 파일 하나를 읽는다.

    검사: 절대 경로, 일반 파일(디렉터리·장치 거부), 다른 사용자 쓰기 가능 거부, 크기 1~4096바이트,
    끝 줄바꿈만 제거, 내부에 공백·제어 문자 없음. 오류 메시지에는 경로만 쓰고 값은 쓰지 않는다.
    """
    p = Path(path)
    if not p.is_absolute():
        raise ConfigError(f"비밀 파일 경로는 절대 경로여야 한다: {p}")
    try:
        st = os.stat(p)
    except FileNotFoundError:
        raise ConfigError(f"비밀 파일이 없다: {p}") from None
    except PermissionError:
        raise ConfigError(f"비밀 파일을 읽을 권한이 없다: {p}") from None
    if not stat.S_ISREG(st.st_mode):
        raise ConfigError(f"비밀 파일이 일반 파일이 아니다: {p}")
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        # PV-09: 비밀 파일은 소유자만(400 권장, 600 허용). 그룹·다른 사용자 권한이 하나라도 있으면 거부.
        raise ConfigError(f"비밀 파일 권한이 너무 넓다(chmod 400 필요, 그룹·다른 사용자 권한 금지): {p}")
    if st.st_size == 0 or st.st_size > SECRET_MAX_BYTES:
        raise ConfigError(f"비밀 파일 크기가 이상하다(1~{SECRET_MAX_BYTES}바이트): {p}")
    try:
        raw = p.read_bytes()
    except PermissionError:
        raise ConfigError(f"비밀 파일을 읽을 권한이 없다: {p}") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigError(f"비밀 파일이 UTF-8이 아니다: {p}") from None
    text = text.rstrip("\r\n")
    if not text:
        raise ConfigError(f"비밀 파일이 비어 있다: {p}")
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text):
        raise ConfigError(f"비밀 값 안에 공백·제어 문자가 있다: {p}")
    return Secret(text)


def check_env_no_secrets(environ: Mapping[str, str] | None = None) -> list[str]:
    """비밀처럼 보이는 환경 변수 이름 목록(값은 보지 않는다). 비어 있지 않으면 main이 시작을 거부한다."""
    env = os.environ if environ is None else environ
    bad = []
    for k in env:
        u = str(k).upper()
        if u in ALLOWED_ENV_NAMES:
            continue
        if u in FORBIDDEN_ENV_NAMES or _FORBIDDEN_ENV_RE.match(u) or _FORBIDDEN_ENV_GENERIC_RE.match(u):
            bad.append(k)
    return sorted(bad)


def read_telegram_token(path: str | os.PathLike[str]) -> Secret:
    """텔레그램 봇 토큰 파일: read_secret 검사 + 토큰 모양 검사(숫자:문자열). 값은 오류 메시지에 넣지 않는다.

    다른 비밀(예: Anthropic 키 sk-ant-…)을 토큰 자리에 잘못 넣으면 텔레그램 서버가 거부하면서 예외 메시지에
    값이 그대로 실릴 수 있다(PTB InvalidToken). 그래서 보내기 전에 모양부터 막는다(SEC-01).
    """
    tok = read_secret(path)
    v = tok.reveal()
    if "sk-ant-" in v or not TELEGRAM_TOKEN_RE.fullmatch(v):
        raise ConfigError(f"텔레그램 토큰 파일 내용이 봇 토큰 모양(숫자:문자열)이 아니다(다른 파일을 넣지 않았는지 확인): {path}")
    return tok


# ---------------------------------------------------------------------------
# 설정 자료형
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleConfig:
    decision_delay_s: int = 60            # 판단 = 일봉 마감(00:00 UTC) + 60초 (TREND_SPEC §1, backtest AVAIL_DELAY)
    approval_window_s: int = 7200         # 승인 유효 2시간 (09:01~11:01 KST)
    confirm_window_s: int = 60            # [승인] 뒤 [확인]까지 60초
    monitor_interval_s: int = 60          # 보호 손절·추세 청산·체결 감시 주기
    trend_exit_latency_min: int = 30      # 추세 청산 = 청산 신호 판단 + L(30분) 뒤 첫 1분봉 시가 (TREND_SPEC §2)


@dataclass(frozen=True)
class PaperConfig:
    equity_usdt: float = 10_000.0         # 모의 R 자본(보고용 크기 계산). 판정은 R 단위라 크기와 무관


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = True
    allowed_user_id: int = 0              # 숫자. 0이면 enabled=true일 때 거부
    allowed_chat_id: int = 0              # 숫자, 개인 채팅(양수)만
    bot_token_file: str = "/run/secrets/telegram_bot_token"


@dataclass(frozen=True)
class ClaudeConfig:
    enabled: bool = True
    api_key_file: str = "/run/secrets/anthropic_api_key"
    model: str = CLAUDE_MODEL
    effort: str = CLAUDE_EFFORT
    timeout_s: int = 120
    max_tokens: int = 16000               # Opus 5.5는 사고가 항상 켜져 있어 사고 토큰도 여기서 나간다(SDK 예시값)
    prompt_version: str = "analyst_v1"


@dataclass(frozen=True)
class MarketDataConfig:
    base_url: str = "https://fapi.binance.com"
    symbol: str = "BTCUSDT"
    request_timeout_s: float = 10.0
    max_retries: int = 3
    max_clock_skew_ms: int = 1000         # 서버 시각과 이만큼 넘게 어긋나면 사이클 보류 + 경고
    data_dir: str = "data/binance"        # 재생 모드 입력 (저장소 기준 상대 경로 허용)


@dataclass(frozen=True)
class ReplayConfig:
    start: str = ""                       # 'YYYY-MM-DD' (UTC). 이 날 00:00 마감 판단부터 재생
    end: str = ""                         # 'YYYY-MM-DD' (포함)
    auto_approve_latency_min: int | None = 30  # 재생에서 자동 확인 지연(백테스트 L=30분과 대응). None = 자동 승인 없음(전부 만료)


@dataclass(frozen=True)
class HealthConfig:
    ping_url_file: str = ""               # healthchecks 핑 URL(비밀 취급) 파일. 빈 값이면 핑 없음


@dataclass(frozen=True)
class BotConfig:
    mode: Mode
    db_path: str
    strategy_key: str = STRATEGY_KEY
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    marketdata: MarketDataConfig = field(default_factory=MarketDataConfig)
    replay: ReplayConfig = field(default_factory=ReplayConfig)
    health: HealthConfig = field(default_factory=HealthConfig)

    # --- 파생값 ---------------------------------------------------------------
    @property
    def mode_tag(self) -> str:
        """메시지 첫 줄 머리표. 이 단계는 [PAPER] 또는 [REPLAY]."""
        return f"[{self.mode.value.upper()}]"

    def trend_config(self):
        """backtest.trend.TrendConfig — 신호 계산의 유일한 기준. base_key가 strategy_key와 같아야 한다."""
        from backtest.trend import PERIODS, TrendConfig

        cfg = TrendConfig(entry="E0", direction="L", periods=PERIODS)
        if cfg.base_key != self.strategy_key:
            raise ConfigError(f"전략 키 불일치: {cfg.base_key} != {self.strategy_key}")
        return cfg

    def redacted_dict(self) -> dict[str, Any]:
        """감사 로그·config_snapshots용. 비밀 값은 원래 없고(경로만), 텔레그램 ID는 끝 3자리만 남긴다."""
        d = asdict(self)
        d["mode"] = self.mode.value
        tg = d["telegram"]
        tg["allowed_user_id"] = _mask_id(self.telegram.allowed_user_id)
        tg["allowed_chat_id"] = _mask_id(self.telegram.allowed_chat_id)
        return d

    def fingerprint(self) -> str:
        """정규화 JSON의 sha256 (가린 값 기준)."""
        blob = json.dumps(self.redacted_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _mask_id(v: int) -> str:
    s = str(v)
    return "*" * max(0, len(s) - 3) + s[-3:]


# ---------------------------------------------------------------------------
# 로더
# ---------------------------------------------------------------------------

_SECTIONS: dict[str, type] = {
    "schedule": ScheduleConfig,
    "paper": PaperConfig,
    "telegram": TelegramConfig,
    "claude": ClaudeConfig,
    "marketdata": MarketDataConfig,
    "replay": ReplayConfig,
    "health": HealthConfig,
}
_TOP_KEYS = {"mode", "db_path", "strategy_key"}


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _coerce(section: str, cls: type, raw: Mapping[str, Any]) -> Any:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"[{section}]는 표여야 한다")
    known = {f.name: f for f in fields(cls)}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ConfigError(f"[{section}]에 모르는 키: {unknown}")
    defaults = cls()
    out: dict[str, Any] = {}
    for name, value in raw.items():
        default = getattr(defaults, name)
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"{section}.{name}은 true/false")
        elif _is_int(default) or (default is None and name.endswith("_min")):
            if value is not None and not _is_int(value):
                raise ConfigError(f"{section}.{name}은 정수(따옴표 없이)")
        elif isinstance(default, float):
            if not (_is_int(value) or isinstance(value, float)):
                raise ConfigError(f"{section}.{name}은 숫자")
            value = float(value)
        elif isinstance(default, str):
            if not isinstance(value, str):
                raise ConfigError(f"{section}.{name}은 문자열")
        out[name] = value
    return cls(**out)


def config_from_dict(raw: Mapping[str, Any]) -> BotConfig:
    """dict(TOML 파싱 결과) → 검증된 BotConfig. 실패하면 ConfigError."""
    unknown = sorted(set(raw) - _TOP_KEYS - set(_SECTIONS))
    if unknown:
        raise ConfigError(f"모르는 최상위 키: {unknown}")
    mode_raw = raw.get("mode")
    if mode_raw == "live":
        raise ConfigError("live 모드는 이 단계에 없다(모의 운영 전용)")
    try:
        mode = Mode(mode_raw)
    except ValueError:
        raise ConfigError(f"mode는 {[m.value for m in Mode]} 중 하나: {mode_raw!r}") from None
    db_path = raw.get("db_path")
    if not isinstance(db_path, str) or not db_path:
        raise ConfigError("db_path(문자열)가 필요하다")
    strategy_key = raw.get("strategy_key", STRATEGY_KEY)
    if strategy_key != STRATEGY_KEY:
        raise ConfigError(f"strategy_key는 {STRATEGY_KEY}만 허용: {strategy_key!r}")
    sections = {name: _coerce(name, cls, raw.get(name, {})) for name, cls in _SECTIONS.items()}
    cfg = BotConfig(mode=mode, db_path=db_path, strategy_key=strategy_key, **sections)
    validate(cfg)
    return cfg


def load_config(path: str | os.PathLike[str]) -> BotConfig:
    p = Path(path)
    try:
        with p.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"설정 파일이 없다: {p}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"설정 파일 TOML 오류: {p}: {exc}") from None
    return config_from_dict(raw)


def validate(cfg: BotConfig) -> None:
    """값 범위 검사. 보수적으로: 확정 설계값에서 벗어나면 거부한다."""
    s = cfg.schedule
    if s.decision_delay_s != 60:
        raise ConfigError("schedule.decision_delay_s는 60 고정(TREND_SPEC §1, 백테스트와 같아야 한다)")
    if not 60 <= s.approval_window_s <= MAX_APPROVAL_WINDOW_S:
        raise ConfigError(f"schedule.approval_window_s는 60~{MAX_APPROVAL_WINDOW_S}초(확정값보다 넓힐 수 없음)")
    if not 10 <= s.confirm_window_s <= MAX_CONFIRM_WINDOW_S:
        raise ConfigError(f"schedule.confirm_window_s는 10~{MAX_CONFIRM_WINDOW_S}초(확정값보다 넓힐 수 없음)")
    if not 10 <= s.monitor_interval_s <= 300:
        raise ConfigError("schedule.monitor_interval_s는 10~300초")
    if s.trend_exit_latency_min != 30:
        raise ConfigError("schedule.trend_exit_latency_min은 30 고정(TREND_SPEC §2 L=30분, 백테스트 동일 경로)")
    if not cfg.paper.equity_usdt > 0:
        raise ConfigError("paper.equity_usdt는 양수")
    tg = cfg.telegram
    if tg.enabled:
        if not (_is_int(tg.allowed_user_id) and tg.allowed_user_id > 0):
            raise ConfigError("telegram.allowed_user_id는 양의 정수(숫자 ID)")
        if not (_is_int(tg.allowed_chat_id) and tg.allowed_chat_id > 0):
            raise ConfigError("telegram.allowed_chat_id는 양의 정수(개인 채팅만 허용, 그룹 ID는 음수라 거부)")
        if not Path(tg.bot_token_file).is_absolute():
            raise ConfigError("telegram.bot_token_file은 절대 경로")
    cl = cfg.claude
    if cl.model != CLAUDE_MODEL:
        raise ConfigError(f"claude.model은 {CLAUDE_MODEL}")
    if cl.effort not in ("low", "medium", "high", "xhigh", "max"):
        raise ConfigError("claude.effort 값이 이상하다")
    if not 1 <= cl.timeout_s <= 120:
        raise ConfigError("claude.timeout_s는 1~120초")
    if not 1024 <= cl.max_tokens <= 64000:
        raise ConfigError("claude.max_tokens는 1024~64000")
    if not re.fullmatch(r"analyst_v\d+", cl.prompt_version):
        raise ConfigError("claude.prompt_version 형식: analyst_vN")
    if cl.enabled and not Path(cl.api_key_file).is_absolute():
        raise ConfigError("claude.api_key_file은 절대 경로")
    md = cfg.marketdata
    if not md.base_url.startswith("https://"):
        raise ConfigError("marketdata.base_url은 https만")
    if md.base_url.rstrip("/") not in ALLOWED_MARKET_BASE_URLS:
        raise ConfigError(f"marketdata.base_url은 허용 목록만: {sorted(ALLOWED_MARKET_BASE_URLS)}")
    if md.symbol != "BTCUSDT":
        raise ConfigError("marketdata.symbol은 BTCUSDT만")
    if not 0 < md.request_timeout_s <= 60:
        raise ConfigError("marketdata.request_timeout_s는 0~60초")
    if not 0 <= md.max_retries <= 10:
        raise ConfigError("marketdata.max_retries는 0~10")
    if not 100 <= md.max_clock_skew_ms <= MAX_CLOCK_SKEW_MS:
        raise ConfigError(f"marketdata.max_clock_skew_ms는 100~{MAX_CLOCK_SKEW_MS}(PV-30, 넓힐 수 없음)")
    rp = cfg.replay
    if rp.auto_approve_latency_min is not None and not 0 <= rp.auto_approve_latency_min <= s.approval_window_s // 60:
        raise ConfigError("replay.auto_approve_latency_min은 0 이상, 승인 창 이하")
    for name in ("start", "end"):
        v = getattr(rp, name)
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ConfigError(f"replay.{name} 형식: YYYY-MM-DD")
    if cfg.health.ping_url_file and not Path(cfg.health.ping_url_file).is_absolute():
        raise ConfigError("health.ping_url_file은 절대 경로")
    cfg.trend_config()  # 전략 키와 backtest 조합 일치 확인


@dataclass(frozen=True)
class Secrets:
    """시작 시 한 번 읽는 비밀 묶음. 필요한 것만 채운다(비활성 기능은 None)."""

    telegram_token: Secret | None = None
    anthropic_api_key: Secret | None = None
    ping_url: Secret | None = None


def load_secrets(cfg: BotConfig) -> Secrets:
    """활성화된 기능의 비밀 파일만 읽는다. 재생 모드에서는 아무것도 읽지 않는다(가짜 전송·가짜 분석가)."""
    if cfg.mode == Mode.REPLAY:
        return Secrets()
    return Secrets(
        telegram_token=read_telegram_token(cfg.telegram.bot_token_file) if cfg.telegram.enabled else None,
        anthropic_api_key=read_secret(cfg.claude.api_key_file) if cfg.claude.enabled else None,
        ping_url=read_secret(cfg.health.ping_url_file) if cfg.health.ping_url_file else None,
    )


# ---------------------------------------------------------------------------
# 로그 비밀 가림 (DESIGN §7.1)
# ---------------------------------------------------------------------------
# 텔레그램 토큰(봇 API URL 안의 'bot<숫자>:<문자열>'), Anthropic 키(sk-ant-…), healthchecks 핑 URL의 UUID
_LOG_SECRET_PATTERNS = (
    re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(hc-ping\.com/)[A-Za-z0-9_-]{20,}(?:/[A-Za-z0-9_.-]+)?"),   # UUID 형식 + ping key/slug 형식
)
# 이 로거들은 INFO에서 요청 URL(텔레그램이면 토큰 포함)을 남기므로 WARNING으로 올린다.
NOISY_LOGGERS = ("httpx", "httpcore", "telegram", "telegram.ext", "anthropic", "hpack", "apscheduler")


class RedactingFilter(logging.Filter):
    """로그 레코드의 최종 메시지에서 알려진 비밀 값과 비밀 모양 문자열을 '***'로 바꾼다(마지막 방어선)."""

    def __init__(self, secrets: "Secrets | None" = None) -> None:
        super().__init__()
        values = []
        if secrets is not None:
            for s in (secrets.telegram_token, secrets.anthropic_api_key, secrets.ping_url):
                if s is not None and len(s.reveal()) >= 8:
                    values.append(s.reveal())
        self._values = tuple(values)

    def redact(self, text: str) -> str:
        for v in self._values:
            text = text.replace(v, "***")
        for pat in _LOG_SECRET_PATTERNS:
            text = pat.sub(lambda m: (m.group(1) if m.groups() else "") + "***", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # 포맷 실패해도 로그는 남긴다
            msg = str(record.msg)
        red = self.redact(msg)
        if red != msg or record.args:
            record.msg, record.args = red, None
        if record.exc_info and record.exc_info[1] is not None:
            text = logging.Formatter().formatException(record.exc_info)
            record.exc_info, record.exc_text = None, None
            record.msg = f"{record.msg}\n{self.redact(text)}"
        return True


def setup_logging(secrets: "Secrets | None" = None, level: int = logging.INFO) -> logging.Handler:
    """루트 로거에 stdout 핸들러 + RedactingFilter. 시끄러운 라이브러리 로거는 WARNING. 반환 = 설치한 핸들러."""
    import sys

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter(secrets))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    return handler
