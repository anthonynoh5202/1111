"""Claude 분석가(관문 아님, PLAN D3) — Claude 담당 구현 (bot/DESIGN.md §7.3, §9.4).

SDK 사용법은 claude-api 스킬의 python/claude-api/README.md 와 tool-use.md(구조화 출력)를 따른다:
- anthropic.Anthropic(api_key=<Secret.reveal()>, base_url=고정, timeout=anthropic.Timeout(...), max_retries=0)
  환경 변수의 키·base_url은 쓰지 않는다(명시 전달).
- client.messages.create(model='claude-opus-5-5', max_tokens=cfg.max_tokens, system=<prompt 파일>,
  messages=[{'role':'user','content': <입력 JSON 문자열>}],
  output_config={'effort': 'medium', 'format': {'type': 'json_schema', 'schema': OUTPUT_SCHEMA}})
  Opus 5.5는 사고가 항상 켜져 있으므로 thinking 인자를 보내지 않는다(README: 생략 = adaptive).
- stop_reason 확인: 'end_turn'만 정상. 'refusal' → 'refusal', 'max_tokens' → 'truncated', 그 밖 → 'error'
- 응답 JSON을 validate_output으로 다시 검증(위반 → 'schema_invalid'). 타임아웃 → 'timeout', 그 밖 예외 → 'error'
- 입력은 코드가 계산한 수치 JSON만. validate_input이 외부 텍스트가 섞일 수 있는 입력을 호출 전에 거부한다.
- 입력·원본 응답(+프롬프트 sha256, request_id, 토큰 사용량, 추정 비용)·프롬프트 버전을 AnalystResult에 담는다.
- analyze()는 절대 예외를 던지지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from bot.config import ClaudeConfig, Secret
from bot.types import AnalystResult

log = logging.getLogger(__name__)

PROMPT_VERSION = "analyst_v1"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_PROMPT_VERSION_RE = re.compile(r"^analyst_v[1-9][0-9]{0,2}$")

# 키가 환경 변수(ANTHROPIC_BASE_URL)로 다른 곳에 새지 않도록 base_url을 명시 고정한다.
API_BASE_URL = "https://api.anthropic.com"
CONNECT_TIMEOUT_S = 10.0

# 추정 비용용 단가(USD / 1M 토큰, claude-api 스킬 README의 claude-opus-5-5 값). 청구액이 아니라 기록용 추정치.
PRICE_PER_MTOK = {"claude-opus-5-5": (4.00, 20.00)}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "counter_evidence": {"type": "array", "items": {"type": "string"}},
        "invalidation": {"type": "string"},
        "opinion": {"type": "string", "enum": ["approve", "pass"]},
        "confidence_note": {"type": "string"},
    },
    "required": ["summary", "counter_evidence", "invalidation", "opinion", "confidence_note"],
    "additionalProperties": False,
}

# 로컬 검증 상한(API 스키마에는 넣지 않는다 — 구조화 출력이 지원하지 않는 제약일 수 있어서).
# 프롬프트가 요구하는 길이보다 넉넉하게 둔다. 표시 길이는 telegram_ui.sanitize_text가 따로 자른다.
MAX_LEN = {"summary": 1000, "invalidation": 600, "confidence_note": 600}
MAX_COUNTER_ITEMS = 8
MAX_COUNTER_ITEM_LEN = 400

# 입력 검사(프롬프트 인젝션 차단): 문자열은 코드가 만든 짧은 고정 값(날짜·기호·enum)만 허용.
INPUT_SCHEMA_VERSION = "analyst_input_v1"
MAX_INPUT_BYTES = 64 * 1024
MAX_INPUT_DEPTH = 5
_INPUT_STR_RE = re.compile(r"^[A-Za-z0-9 _.:+\-]{0,32}$")
_INPUT_TOP_KEYS = frozenset({"schema", "symbol", "timeframe", "decision_time_utc", "strategy", "recent_daily",
                             "indicators", "subsystems", "open_positions"})
_INPUT_KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")

# 키별 엄격 스키마(SEC-08): 문자열은 정해진 키에서 정해진 모양만, 나머지는 숫자(또는 null)만.
_NUM = "num"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INPUT_SCALARS: dict[str, Any] = {
    "schema": re.compile(r"^analyst_input_v1$"),
    "symbol": re.compile(r"^BTCUSDT$"),
    "timeframe": re.compile(r"^1d$"),
    "decision_time_utc": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$"),
}
_INPUT_STRATEGY = {"key": re.compile(r"^[A-Z0-9]{1,4}(?:-[A-Z0-9]{1,4}){0,3}$"),
                   "spec": re.compile(r"^TREND v\d{1,2}\.\d{1,2}$"),
                   "periods": "int_list", "stop_atr_mult": _NUM}
_INPUT_ITEMS: dict[str, tuple[int, dict[str, Any]]] = {       # 목록 키: (최대 개수, 항목 키 → 형식)
    "recent_daily": (120, {"date": _DATE_RE, "open": _NUM, "high": _NUM, "low": _NUM, "close": _NUM,
                           "volume": _NUM}),
    "subsystems": (6, {"n": "int", "m": "int",
                       "action": re.compile(r"^(?:ENTRY|EXIT|HOLD|NONE|BUSY)$"),
                       "close": _NUM, "entry_level": _NUM, "exit_level": _NUM, "breakout_pct": _NUM,
                       "stop_if_filled_at_close": _NUM, "stop_distance_pct": _NUM}),
    "open_positions": (6, {"n": "int", "entry_price": _NUM, "stop": _NUM, "unrealized_r": _NUM,
                           "days_held": _NUM}),
}
_INPUT_INDICATORS = frozenset({"sma20", "sma50", "sma100", "sma200", "atr20", "atr20_pct", "ret_7d_pct",
                               "ret_30d_pct", "dist_from_100d_high_pct"})


def _num_ok(v: object) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))


def _field_ok(kind: Any, v: object) -> bool:
    if kind == _NUM:
        return _num_ok(v)
    if kind == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if kind == "int_list":
        return isinstance(v, list) and len(v) <= 6 and all(isinstance(x, int) and not isinstance(x, bool) for x in v)
    if isinstance(kind, re.Pattern):
        return isinstance(v, str) and kind.fullmatch(v) is not None
    return False


def _strict_schema(payload: dict[str, Any]) -> str | None:
    """키별 고정 스키마. 모르는 중첩 키·정해지지 않은 자리의 문자열·항목 수 초과를 거부한다."""
    for key, pat in _INPUT_SCALARS.items():
        if key in payload and not _field_ok(pat, payload[key]):
            return "input_schema"
    strat = payload.get("strategy", {})
    if not isinstance(strat, dict) or set(strat) - set(_INPUT_STRATEGY):
        return "input_schema"
    if any(not _field_ok(_INPUT_STRATEGY[k], v) for k, v in strat.items()):
        return "input_schema"
    ind = payload.get("indicators", {})
    if not isinstance(ind, dict) or set(ind) - _INPUT_INDICATORS or any(not _num_ok(v) for v in ind.values()):
        return "input_schema"
    for key, (max_n, spec) in _INPUT_ITEMS.items():
        items = payload.get(key, [])
        if not isinstance(items, list) or len(items) > max_n:
            return "input_schema"
        for it in items:
            if not isinstance(it, dict) or set(it) - set(spec):
                return "input_schema"
            if any(not _field_ok(spec[k], v) for k, v in it.items()):
                return "input_schema"
    return None

# 이 오류 문구만 AnalystResult.error에 남긴다(예외 메시지 원문은 남기지 않는다 — 비밀·긴 본문 방지).
MAX_ERROR_LEN = 200


# ---------------------------------------------------------------------------
# 프롬프트·검증
# ---------------------------------------------------------------------------


def load_prompt(version: str = PROMPT_VERSION) -> tuple[str, str]:
    """bot/prompts/<version>.md → (본문, sha256). 버전 형식이 analyst_vN이 아니면 ValueError(경로 조작 방지)."""
    if not isinstance(version, str) or not _PROMPT_VERSION_RE.fullmatch(version):
        raise ValueError("prompt_version 형식은 analyst_vN 이어야 한다")
    path = (PROMPTS_DIR / f"{version}.md").resolve()
    if path.parent != PROMPTS_DIR:
        raise ValueError("프롬프트 경로가 prompts 폴더 밖이다")
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ValueError(f"프롬프트 파일이 없다: {version}") from None
    text = raw.decode("utf-8").strip()
    if not text:
        raise ValueError(f"프롬프트 파일이 비어 있다: {version}")
    return text, hashlib.sha256(raw).hexdigest()


def validate_output(obj: object) -> str | None:
    """OUTPUT_SCHEMA 검사(필수 키·타입·enum·추가 키 없음·길이 상한). 통과면 None, 아니면 사유."""
    if not isinstance(obj, dict):
        return "not_object"
    required = OUTPUT_SCHEMA["required"]
    extra = sorted(set(obj) - set(required))
    if extra:
        return f"extra_keys:{','.join(str(k)[:20] for k in extra[:3])}"
    missing = [k for k in required if k not in obj]
    if missing:
        return f"missing:{','.join(missing)}"
    for key in ("summary", "invalidation", "confidence_note"):
        v = obj[key]
        if not isinstance(v, str):
            return f"type:{key}"
        if not v.strip():
            return f"empty:{key}"
        if len(v) > MAX_LEN[key]:
            return f"too_long:{key}"
    ce = obj["counter_evidence"]
    if not isinstance(ce, list):
        return "type:counter_evidence"
    if len(ce) > MAX_COUNTER_ITEMS:
        return "too_many:counter_evidence"
    for item in ce:
        if not isinstance(item, str):
            return "type:counter_evidence_item"
        if len(item) > MAX_COUNTER_ITEM_LEN:
            return "too_long:counter_evidence_item"
    if obj["opinion"] not in ("approve", "pass"):   # bool/None/대소문자 다른 값 모두 거부
        return "enum:opinion"
    return None


def validate_input(payload: object) -> str | None:
    """입력이 '코드가 계산한 수치 JSON'인지 검사. 통과면 None, 아니면 사유.

    - dict, schema == analyst_input_v1, 최상위 키는 고정 목록 안
    - 키는 소문자·숫자·밑줄, 값은 유한한 숫자·bool·None·짧은 고정 문자열(영숫자와 ' _.:+-', 32자 이내)
    - 깊이 5, 직렬화 64KiB 이내
    - 키별 엄격 스키마(SEC-08): 중첩 키는 정해진 목록만, 문자열은 정해진 키(날짜·기호·enum·전략 키)에서 정해진 모양만,
      목록 항목 수 상한. 그 밖의 자리는 숫자(또는 null)만.
    외부 뉴스·사용자 문장 같은 자유 텍스트는 여기서 걸러진다(프롬프트 인젝션 경로 차단).
    """
    if not isinstance(payload, dict):
        return "input_not_object"
    if payload.get("schema") != INPUT_SCHEMA_VERSION:
        return "input_schema_version"
    extra = set(payload) - _INPUT_TOP_KEYS
    if extra:
        return "input_unknown_key"

    def walk(v: object, depth: int) -> str | None:
        if depth > MAX_INPUT_DEPTH:
            return "input_too_deep"
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return None if math.isfinite(v) else "input_non_finite"
        if isinstance(v, str):
            return None if _INPUT_STR_RE.fullmatch(v) else "input_free_text"
        if isinstance(v, dict):
            for k, item in v.items():
                if not isinstance(k, str) or not _INPUT_KEY_RE.fullmatch(k):
                    return "input_bad_key"
                err = walk(item, depth + 1)
                if err:
                    return err
            return None
        if isinstance(v, (list, tuple)):
            for item in v:
                err = walk(item, depth + 1)
                if err:
                    return err
            return None
        return "input_bad_type"

    err = walk(payload, 0)
    if err:
        return err
    try:
        size = len(serialize_input(payload).encode("utf-8"))
    except (TypeError, ValueError):
        return "input_not_serializable"
    if size > MAX_INPUT_BYTES:
        return "input_too_large"
    return _strict_schema(payload)


def serialize_input(payload: dict[str, Any]) -> str:
    """보낼 입력 문자열. 키 정렬로 결정적(같은 입력 → 같은 바이트)."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def build_request(system_prompt: str, input_json: str, cfg: ClaudeConfig) -> dict[str, Any]:
    """messages.create 인자. 테스트가 그대로 검사한다."""
    return dict(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": input_json}],
        output_config={"effort": cfg.effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )


# ---------------------------------------------------------------------------
# 응답 도우미
# ---------------------------------------------------------------------------


def _usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    out: dict[str, int] = {}
    for name in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        v = getattr(usage, name, None) if usage is not None else None
        if isinstance(v, int) and not isinstance(v, bool):
            out[name] = v
    return out


def estimate_cost_usd(model: str, usage: dict[str, int]) -> float | None:
    """토큰 사용량 → 추정 비용(USD). 캐시 쓰기 1.25배·읽기 0.1배(README). 단가를 모르면 None."""
    price = PRICE_PER_MTOK.get(model)
    if price is None or not usage:
        return None
    p_in, p_out = price
    cost = (usage.get("input_tokens", 0) * p_in
            + usage.get("cache_creation_input_tokens", 0) * p_in * 1.25
            + usage.get("cache_read_input_tokens", 0) * p_in * 0.1
            + usage.get("output_tokens", 0) * p_out) / 1_000_000
    return round(cost, 6)


def _first_text(response: Any) -> str | None:
    for block in getattr(response, "content", None) or ():
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", None)
            return text if isinstance(text, str) else None
    return None


def _stop_details(response: Any) -> dict[str, Any] | None:
    sd = getattr(response, "stop_details", None)
    if sd is None:
        return None
    cat = getattr(sd, "category", None)
    return {"category": cat if isinstance(cat, str) else None}


def _short(s: str) -> str:
    return s[:MAX_ERROR_LEN]


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """예외 → (status, error). 메시지 원문은 남기지 않고 형식 이름·HTTP 코드만 남긴다."""
    try:
        import anthropic  # 지연 import: 테스트·재생 모드에서 SDK가 없어도 이 모듈은 동작

        timeout_types: tuple[type[BaseException], ...] = (anthropic.APITimeoutError, TimeoutError)
        status_type: type[BaseException] | None = anthropic.APIStatusError
    except Exception:  # pragma: no cover - SDK가 설치되어 있으므로 보통 오지 않는다
        timeout_types, status_type = (TimeoutError,), None
    name = type(exc).__name__
    if isinstance(exc, timeout_types):
        return "timeout", _short(name)
    if status_type is not None and isinstance(exc, status_type):
        code = getattr(exc, "status_code", None)
        return "error", _short(f"{name}:{code}")
    return "error", _short(name)


def _default_client_factory(api_key: str, timeout_s: float):
    import anthropic

    return anthropic.Anthropic(
        api_key=api_key,
        base_url=API_BASE_URL,
        timeout=anthropic.Timeout(float(timeout_s), connect=min(CONNECT_TIMEOUT_S, float(timeout_s))),
        max_retries=0,   # 120초 예산 안에서 끝내기 위해 재시도하지 않는다(실패해도 신호는 그대로 나간다)
    )


# ---------------------------------------------------------------------------
# 실제 분석가
# ---------------------------------------------------------------------------


class AnthropicAnalystClient:
    """실제 호출. 이 컨테이너에는 키가 없으므로 테스트는 client_factory로 가짜 SDK 클라이언트를 넣는다.

    client_factory(api_key: str, timeout_s: float) -> messages.create(**kwargs)를 가진 객체.
    """

    def __init__(self, api_key: Secret, cfg: ClaudeConfig, *, client_factory: Callable[..., Any] | None = None,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        if not isinstance(api_key, Secret):
            raise TypeError("api_key는 Secret(파일에서 읽은 값)이어야 한다")
        self.cfg = cfg
        self.model = cfg.model
        self.prompt_version = cfg.prompt_version
        self.system_prompt, self.prompt_sha256 = load_prompt(cfg.prompt_version)   # 시작 시 실패하면 바로 드러나게
        self._monotonic = monotonic
        factory = client_factory or _default_client_factory
        self._client = factory(api_key.reveal(), float(cfg.timeout_s))

    def __repr__(self) -> str:  # 클라이언트 객체(키 보유)를 repr에 드러내지 않는다
        return f"AnthropicAnalystClient(model={self.model!r}, prompt_version={self.prompt_version!r})"

    # -- 내부 -------------------------------------------------------------

    def _call_with_deadline(self, request: dict[str, Any]) -> Any:
        """SDK 타임아웃에 더해 벽시계 상한(cfg.timeout_s)을 건다. 넘으면 TimeoutError(호출 스레드는 버림)."""
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["response"] = self._client.messages.create(**request)
            except BaseException as e:  # noqa: BLE001 - 스레드 밖으로 그대로 전달
                box["exc"] = e

        t = threading.Thread(target=run, name="claude-analyst", daemon=True)
        t.start()
        t.join(float(self.cfg.timeout_s))
        if t.is_alive():
            raise TimeoutError("analyst deadline")
        if "exc" in box:
            raise box["exc"]
        return box["response"]

    def _result(self, status: str, input_json: str, started: float | None, **kw: Any) -> AnalystResult:
        latency = None if started is None else int(round((self._monotonic() - started) * 1000))
        return AnalystResult(ok=(status == "ok"), status=status, prompt_version=self.prompt_version, model=self.model,
                             input_json=input_json, latency_ms=latency, **kw)

    def _envelope(self, response: Any, text: str | None) -> tuple[str, dict[str, int], float | None]:
        usage = _usage_dict(response)
        cost = estimate_cost_usd(self.model, usage)
        rid = getattr(response, "_request_id", None)
        content_types = [str(getattr(b, "type", "?"))[:30] for b in (getattr(response, "content", None) or ())]
        env = {
            "prompt_sha256": self.prompt_sha256,
            "request_id": rid if isinstance(rid, str) else None,
            "response_model": getattr(response, "model", None) if isinstance(getattr(response, "model", None), str)
            else None,
            "stop_reason": getattr(response, "stop_reason", None),
            "stop_details": _stop_details(response),
            "content_types": content_types,
            "text": text,                  # 사고 블록 내용은 저장하지 않는다(텍스트 블록만)
            "usage": usage,
            "estimated_cost_usd": cost,
        }
        return json.dumps(env, ensure_ascii=False, sort_keys=True, default=str), usage, cost

    # -- 공개 -------------------------------------------------------------

    def analyze(self, input_payload: dict[str, Any]) -> AnalystResult:
        try:
            return self._analyze(input_payload)
        except Exception as e:  # 마지막 안전망: 절대 밖으로 던지지 않는다
            log.warning("Claude 분석 내부 오류: %s", type(e).__name__)
            return self._result("error", "", None, error=_short(f"internal:{type(e).__name__}"))

    def _analyze(self, input_payload: dict[str, Any]) -> AnalystResult:
        try:
            input_json = serialize_input(input_payload)
        except (TypeError, ValueError):
            input_json = json.dumps(input_payload, ensure_ascii=False, sort_keys=True, default=str)
        bad = validate_input(input_payload)
        if bad:
            log.warning("Claude 입력 거부(호출 안 함): %s", bad)
            return self._result("error", input_json, None, error=bad)

        request = build_request(self.system_prompt, input_json, self.cfg)
        started = self._monotonic()
        try:
            response = self._call_with_deadline(request)
        except Exception as e:
            status, err = _classify_exception(e)
            log.warning("Claude 호출 실패: status=%s error=%s", status, err)
            return self._result(status, input_json, started, error=err)

        stop_reason = getattr(response, "stop_reason", None)
        stop_reason = stop_reason if isinstance(stop_reason, str) else None
        text = _first_text(response)
        raw, usage, cost = self._envelope(response, text)
        log.info("Claude 호출: stop_reason=%s input_tokens=%s output_tokens=%s est_cost_usd=%s",
                 stop_reason, usage.get("input_tokens"), usage.get("output_tokens"), cost)

        if stop_reason == "refusal":
            sd = _stop_details(response) or {}
            return self._result("refusal", input_json, started, raw_response=raw, stop_reason=stop_reason,
                                error=_short(f"refusal:{sd.get('category')}"))
        if stop_reason == "max_tokens":
            return self._result("truncated", input_json, started, raw_response=raw, stop_reason=stop_reason,
                                error="max_tokens")
        if stop_reason != "end_turn":
            return self._result("error", input_json, started, raw_response=raw, stop_reason=stop_reason,
                                error=_short(f"stop_reason:{stop_reason}"))
        if text is None:
            return self._result("schema_invalid", input_json, started, raw_response=raw, stop_reason=stop_reason,
                                error="no_text_block")
        try:
            obj = json.loads(text)
        except (ValueError, RecursionError):
            return self._result("schema_invalid", input_json, started, raw_response=raw, stop_reason=stop_reason,
                                error="json_decode")
        why = validate_output(obj)
        if why:
            return self._result("schema_invalid", input_json, started, raw_response=raw, stop_reason=stop_reason,
                                error=_short(why))
        return self._result(
            "ok", input_json, started, raw_response=raw, stop_reason=stop_reason,
            summary=obj["summary"].strip(), counter_evidence=tuple(s.strip() for s in obj["counter_evidence"]),
            invalidation=obj["invalidation"].strip(), opinion=obj["opinion"],
            confidence_note=obj["confidence_note"].strip())


class DisabledAnalyst:
    """claude.enabled=false 또는 재생 모드 기본값: 항상 ok=False, status='disabled'."""

    def __init__(self, prompt_version: str = PROMPT_VERSION, model: str = "claude-opus-5-5") -> None:
        self.prompt_version = prompt_version
        self.model = model

    def analyze(self, input_payload: dict[str, Any]) -> AnalystResult:
        return AnalystResult(ok=False, status="disabled", prompt_version=self.prompt_version, model=self.model,
                             input_json=json.dumps(input_payload, ensure_ascii=False, sort_keys=True, default=str))
