"""시세 공급원 — 핵심 담당 구현 (bot/DESIGN.md §7.4, §9.2).

두 구현 모두 bot.types.MarketData 프로토콜을 따르고 '마감된 봉만' 돌려준다.
- LiveBinance: 바이낸스 USDⓈ-M 선물 공개 REST(fapi). 키 없음·서명 없음. 이 컨테이너에서는 접속 불가라 테스트는 가짜 httpx 전송으로.
- Replay: data/binance 파일(backtest.data 로더 재사용)에서 시각 T까지만 반환. 재생 모드·대조 시험용.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np
import pandas as pd

from backtest import types as BT
from bot.config import MarketDataConfig
from bot.types import NS_PER_DAY, NS_PER_MIN, NS_PER_MS, Clock

log = logging.getLogger(__name__)

KLINES_PATH = "/fapi/v1/klines"
FUNDING_PATH = "/fapi/v1/fundingRate"
TIME_PATH = "/fapi/v1/time"
DAILY_LIMIT = 500                  # 워밍업 100 + ATR 21보다 넉넉히 (1회 요청)
MINUTE_LIMIT = 1500                # 바이낸스 klines 최대
FUNDING_LIMIT = 1000
MAX_PAGES = 100                    # 1분봉 150,000개(약 104일) 넘게 한 번에 요청하지 않는다(폭주 방지)
MAX_RETRY_AFTER_S = 60.0
USER_AGENT = "trend-paper-bot/0.1 (public-data-only)"
_MS_PER_HOUR = 3_600_000
_INTERVAL_NS = {"1d": NS_PER_DAY, "1m": NS_PER_MIN}


class MarketDataError(RuntimeError):
    """시세 이상(빈 구간·중복·미마감 봉·시계 오차 초과·재시도 소진). 엔진은 이 예외면 사이클을 보류하고 경고한다."""


def _empty_bars() -> pd.DataFrame:
    e = np.empty(0)
    return BT.make_bars_frame(np.empty(0, dtype=np.int64), e, e, e, e, e, 0)


def _empty_funding() -> pd.DataFrame:
    return BT.make_funding_frame(np.empty(0, dtype=np.int64), np.empty(0))


# ---------------------------------------------------------------------------
# LiveBinance
# ---------------------------------------------------------------------------


class LiveBinance:
    """GET {base_url}/fapi/v1/klines (interval 1d·1m), /fapi/v1/fundingRate, /fapi/v1/time.

    규칙 (DESIGN §9.2)
    - httpx.Client(timeout=cfg.request_timeout_s, verify=True). API 키·서명 헤더를 절대 보내지 않는다.
    - 재시도: 연결 오류·5xx·429는 지수 백오프(1, 2, 4초…, Retry-After 존중) 최대 cfg.max_retries회. 418(차단)은 즉시 중지.
    - 미마감 봉 제거: close_ns > now_ns인 봉은 버린다(바이낸스는 진행 중 봉도 준다).
    - 검사: 시간순·중복 없음, 가격 양수, high ≥ max(open, close). 빈 구간: 일봉은 거부, 1분봉은 허용 + 기록(take_gaps).
    - 시계 오차: |server_time − clock.now| > cfg.max_clock_skew_ms이면 MarketDataError.
    - 일봉은 최근 500개(1회 요청)면 충분(워밍업 100 + ATR 21).
    - 리다이렉트는 따라가지 않는다(다른 호스트로 새는 것 방지). 응답 본문은 오류 메시지에 넣지 않는다(짧은 요약만).
    """

    def __init__(self, cfg: MarketDataConfig, clock: Clock, http_client: httpx.Client | None = None, *,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not cfg.base_url.startswith("https://"):
            raise MarketDataError("base_url은 https만")
        self.cfg = cfg
        self.clock = clock
        self._sleep = sleep
        self._own_client = http_client is None
        self._gaps_seen: set[tuple[int, int]] = set()
        self._gaps_new: list[tuple[int, int]] = []
        # 헤더는 User-Agent·Accept뿐(키·서명 없음). 테스트는 MockTransport를 단 클라이언트를 넣는다.
        self._client = http_client if http_client is not None else httpx.Client(
            base_url=cfg.base_url, timeout=cfg.request_timeout_s, verify=True, follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    def close(self) -> None:
        if self._own_client:
            self._client.close()

    # --- HTTP -----------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return self.cfg.base_url.rstrip("/") + path

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """재시도 포함 GET → JSON. 실패하면 MarketDataError."""
        attempts = int(self.cfg.max_retries) + 1
        last = "unknown"
        for i in range(attempts):
            wait = float(2 ** i)
            try:
                resp = self._client.get(self._url(path), params=params,
                                        headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            except httpx.TransportError as exc:          # 연결·타임아웃
                last = f"{type(exc).__name__}"
            else:
                code = resp.status_code
                if code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        raise MarketDataError(f"{path}: JSON이 아닌 응답") from None
                if code == 418:
                    raise MarketDataError(f"{path}: 418 IP 차단 — 재시도하지 않고 중지")
                if code == 429 or 500 <= code < 600:
                    last = f"HTTP {code}"
                    ra = resp.headers.get("Retry-After")
                    if ra is not None:
                        try:
                            wait = max(wait, min(float(ra), MAX_RETRY_AFTER_S))
                        except ValueError:
                            pass
                else:
                    raise MarketDataError(f"{path}: HTTP {code} (재시도 안 함)")
            if i + 1 < attempts:
                log.warning("시세 요청 재시도 %s/%s (%s): %s", i + 1, attempts - 1, path, last)
                self._sleep(wait)
        raise MarketDataError(f"{path}: 재시도 소진 ({last})")

    # --- 파싱·검사 -------------------------------------------------------------------
    def _parse_klines(self, rows: Any, interval: str) -> pd.DataFrame:
        dur = _INTERVAL_NS[interval]
        if not isinstance(rows, list):
            raise MarketDataError("klines 응답이 배열이 아님")
        if not rows:
            return _empty_bars()
        try:
            open_ms = np.array([int(r[0]) for r in rows], dtype=np.int64)
            close_ms = np.array([int(r[6]) for r in rows], dtype=np.int64)
            px = np.array([[float(r[k]) for k in (1, 2, 3, 4, 5)] for r in rows], dtype=np.float64)
        except (TypeError, ValueError, IndexError):
            raise MarketDataError("klines 행 형식이 이상하다") from None
        dur_ms = dur // NS_PER_MS
        if np.any(close_ms != open_ms + dur_ms - 1):
            raise MarketDataError(f"klines 봉 길이가 {interval}가 아니다")
        if np.any(open_ms % dur_ms != 0):
            raise MarketDataError(f"klines 봉 시작이 {interval} 경계가 아니다")
        if not np.all(np.isfinite(px)) or np.any(px[:, :4] <= 0) or np.any(px[:, 4] < 0):
            raise MarketDataError("klines 가격이 양수가 아니거나 NaN")
        df = BT.make_bars_frame(open_ms * NS_PER_MS, px[:, 0], px[:, 1], px[:, 2], px[:, 3], px[:, 4], dur)
        return df

    def _closed_only(self, df: pd.DataFrame, start_ns: int | None, until_ns: int, interval: str) -> pd.DataFrame:
        """미마감(close_ns > now)·범위 밖 봉 제거 후 표준 검사(길이·연속·중복·고저가)."""
        now = int(self.clock.now_ns())
        limit = min(int(until_ns), now)
        mask = df["close_ns"].to_numpy() <= limit
        if start_ns is not None:
            mask &= df["open_ns"].to_numpy() >= int(start_ns)
        out = df[mask]
        # 1분봉은 거래소 점검 등으로 빈 구간이 실제로 생긴다(R-4). 빈 구간을 오류로 보면 같은 커서로 매번 실패해
        # 감시·체결이 영구히 멈춘다. 백테스트처럼 다음 봉으로 이어 가고, 빈 구간은 기록해 엔진이 감사·경고한다.
        # 일봉은 신호 계산(채널·ATR)의 전제라 빈 구간을 계속 거부한다.
        contiguous = interval != "1m"
        try:
            BT.check_bars_frame(out, dur_ns=_INTERVAL_NS[interval], contiguous=contiguous)
        except ValueError as exc:
            raise MarketDataError(f"{interval} 봉 검사 실패: {exc}") from None
        if not contiguous and len(out) > 1:
            o = out["open_ns"].to_numpy(dtype=np.int64)
            for k in np.flatnonzero(np.diff(o) > _INTERVAL_NS[interval]):
                gap = (int(o[k]) + _INTERVAL_NS[interval], int(o[k + 1]))
                if gap not in self._gaps_seen:
                    self._gaps_seen.add(gap)
                    self._gaps_new.append(gap)
                    log.warning("1분봉 빈 구간: %d개 봉 없음", (gap[1] - gap[0]) // _INTERVAL_NS[interval])
        return out

    def take_gaps(self) -> list[tuple[int, int]]:
        """새로 발견한 1분봉 빈 구간 [없는 첫 봉 시작, 다음 봉 시작) 목록을 꺼낸다(한 번만)."""
        out, self._gaps_new = self._gaps_new, []
        return out

    # --- MarketData -----------------------------------------------------------------
    def daily_bars(self, until_ns: int) -> pd.DataFrame:
        end_ms = int(until_ns) // NS_PER_MS - 1                     # 봉 시작 ≤ endTime
        rows = self._get(KLINES_PATH, {"symbol": self.cfg.symbol, "interval": "1d", "limit": DAILY_LIMIT,
                                       "endTime": end_ms})
        return self._closed_only(self._parse_klines(rows, "1d"), None, until_ns, "1d")

    def minute_bars(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        start_ns, until_ns = int(start_ns), int(until_ns)
        if until_ns <= start_ns:
            return _empty_bars()
        end_ms = until_ns // NS_PER_MS - 1
        cursor_ms = -(-start_ns // NS_PER_MS)
        parts: list[pd.DataFrame] = []
        for _ in range(MAX_PAGES):
            rows = self._get(KLINES_PATH, {"symbol": self.cfg.symbol, "interval": "1m", "limit": MINUTE_LIMIT,
                                           "startTime": cursor_ms, "endTime": end_ms})
            df = self._parse_klines(rows, "1m")
            if len(df):
                parts.append(df)
            if len(df) < MINUTE_LIMIT:
                break
            cursor_ms = int(df["open_ns"].iloc[-1]) // NS_PER_MS + 60_000
            if cursor_ms > end_ms:
                break
        else:
            raise MarketDataError(f"1분봉 요청이 {MAX_PAGES}쪽을 넘는다(범위가 너무 넓음)")
        if not parts:
            return _empty_bars()
        df = pd.concat(parts)
        if df.index.has_duplicates:
            raise MarketDataError("1분봉 중복")
        return self._closed_only(df, start_ns, until_ns, "1m")

    def funding(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        start_ns, until_ns = int(start_ns), min(int(until_ns), int(self.clock.now_ns()))
        if until_ns <= start_ns:
            return _empty_funding()
        cursor_ms = start_ns // NS_PER_MS + 1
        end_ms = until_ns // NS_PER_MS + 60_000        # 정시 직후 수십 ms 기록도 받도록(정시로 내린 뒤 다시 거른다)
        times: list[int] = []
        rates: list[float] = []
        for _ in range(MAX_PAGES):
            rows = self._get(FUNDING_PATH, {"symbol": self.cfg.symbol, "startTime": cursor_ms, "endTime": end_ms,
                                            "limit": FUNDING_LIMIT})
            if not isinstance(rows, list):
                raise MarketDataError("fundingRate 응답이 배열이 아님")
            for r in rows:
                try:
                    if r.get("symbol", self.cfg.symbol) != self.cfg.symbol:
                        raise MarketDataError("fundingRate 심볼 불일치")
                    ms = int(r["fundingTime"])
                    rate = float(r["fundingRate"])
                except (TypeError, ValueError, KeyError, AttributeError):
                    raise MarketDataError("fundingRate 행 형식이 이상하다") from None
                if not np.isfinite(rate):
                    raise MarketDataError("fundingRate NaN")
                times.append(ms)
                rates.append(rate)
            if len(rows) < FUNDING_LIMIT:
                break
            cursor_ms = times[-1] + 1
        else:
            raise MarketDataError("fundingRate 쪽 수 초과")
        if not times:
            return _empty_funding()
        ms_arr = np.array(times, dtype=np.int64)
        floored = (ms_arr // _MS_PER_HOUR) * _MS_PER_HOUR           # backtest.data.load_funding과 같은 정시 내림
        if np.any(ms_arr - floored > 60_000):
            raise MarketDataError("fundingTime이 정시 직후가 아니다")
        order = np.argsort(floored, kind="stable")
        t_ns = floored[order] * NS_PER_MS
        rate_arr = np.array(rates, dtype=np.float64)[order]
        keep = (t_ns > start_ns) & (t_ns <= until_ns)
        t_ns, rate_arr = t_ns[keep], rate_arr[keep]
        if t_ns.size > 1 and np.any(np.diff(t_ns) <= 0):
            raise MarketDataError("fundingRate 시각 중복")
        return BT.make_funding_frame(t_ns, rate_arr)

    def server_time_ns(self) -> int | None:
        body = self._get(TIME_PATH)
        try:
            return int(body["serverTime"]) * NS_PER_MS
        except (TypeError, ValueError, KeyError):
            raise MarketDataError("time 응답 형식이 이상하다") from None

    def check_clock(self) -> int:
        """서버 시각 − 로컬 시각(ms, 요청 왕복 중간값 기준). 허용치 초과면 MarketDataError."""
        t0 = int(self.clock.now_ns())
        server = self.server_time_ns()
        t1 = int(self.clock.now_ns())
        local_mid = (t0 + t1) // 2
        skew_ms = (int(server) - local_mid) // NS_PER_MS
        if abs(skew_ms) > int(self.cfg.max_clock_skew_ms):
            raise MarketDataError(f"시계 오차 {skew_ms} ms > 허용 {self.cfg.max_clock_skew_ms} ms")
        return int(skew_ms)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class Replay:
    """과거 파일 재생. 모든 조회는 until_ns ≤ clock.now_ns()여야 한다(넘으면 MarketDataError: 미래 참조 방지).

    일봉 = backtest.data.load_klines('1d'), 1분봉 = load_klines('1m')(2023-01부터, 처음 쓸 때 읽음), 펀딩 = load_funding().
    from_frames로 합성 데이터(테스트)를 넣을 수 있다.
    daily_from_ns를 주면 open_ns ≥ daily_from_ns인 일봉만 쓴다(대조 시험에서 일봉 시작을 자를 때).
    """

    def __init__(self, data_dir: str | Path, clock: Clock, *, cache_dir: str | Path | None = None,
                 daily_from_ns: int | None = None) -> None:
        from backtest import data as D  # 무거운 로더는 재생 모드에서만 import

        self._data_dir = Path(data_dir)
        self._cache_dir = None if cache_dir is None else Path(cache_dir)
        daily = D.load_klines("1d", data_dir=self._data_dir, cache_dir=self._cache_dir)
        funding = D.load_funding(data_dir=self._data_dir)
        self._setup(daily, None, funding, clock, daily_from_ns)

    @classmethod
    def from_frames(cls, daily: pd.DataFrame, minute: pd.DataFrame, funding: pd.DataFrame, clock: Clock, *,
                    daily_from_ns: int | None = None) -> "Replay":
        obj = cls.__new__(cls)
        obj._data_dir = None
        obj._cache_dir = None
        try:
            BT.check_bars_frame(minute, dur_ns=NS_PER_MIN, contiguous=True)
            BT.check_funding_frame(funding)
        except ValueError as exc:
            raise MarketDataError(f"재생 입력 검사 실패: {exc}") from None
        obj._setup(daily, minute, funding, clock, daily_from_ns)
        return obj

    def _setup(self, daily: pd.DataFrame, minute: pd.DataFrame | None, funding: pd.DataFrame, clock: Clock,
               daily_from_ns: int | None) -> None:
        if daily_from_ns is not None:
            daily = daily[daily["open_ns"].to_numpy() >= int(daily_from_ns)]
        try:
            BT.check_bars_frame(daily, dur_ns=NS_PER_DAY, contiguous=True)
        except ValueError as exc:
            raise MarketDataError(f"재생 일봉 검사 실패: {exc}") from None
        self.clock = clock
        self._daily = daily
        self._daily_close = daily["close_ns"].to_numpy()
        self._minute: pd.DataFrame | None = None
        self._m_open = self._m_close = None
        if minute is not None:
            self._set_minute(minute)
        self._funding = funding.reset_index(drop=True)
        self._f_time = self._funding["time_ns"].to_numpy()
        self.max_until_ns = None          # 지금까지 조회한 가장 늦은 until (시험용 기록)

    def _set_minute(self, minute: pd.DataFrame) -> None:
        self._minute = minute
        self._m_open = minute["open_ns"].to_numpy()
        self._m_close = minute["close_ns"].to_numpy()

    def _load_minute(self) -> None:
        if self._minute is None:
            from backtest import data as D

            self._set_minute(D.load_klines("1m", data_dir=self._data_dir, cache_dir=self._cache_dir))

    def _guard(self, until_ns: int) -> int:
        until_ns = int(until_ns)
        now = int(self.clock.now_ns())
        if until_ns > now:
            raise MarketDataError(f"재생 미래 조회 차단: until {until_ns} > now {now}")
        if self.max_until_ns is None or until_ns > self.max_until_ns:
            self.max_until_ns = until_ns
        return until_ns

    def daily_bars(self, until_ns: int) -> pd.DataFrame:
        until_ns = self._guard(until_ns)
        k = int(np.searchsorted(self._daily_close, until_ns, side="right"))
        return self._daily.iloc[:k]

    def minute_bars(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        until_ns = self._guard(until_ns)
        self._load_minute()
        a = int(np.searchsorted(self._m_open, int(start_ns), side="left"))
        b = int(np.searchsorted(self._m_close, until_ns, side="right"))
        return self._minute.iloc[a:max(a, b)]

    def funding(self, start_ns: int, until_ns: int) -> pd.DataFrame:
        until_ns = self._guard(until_ns)
        a = int(np.searchsorted(self._f_time, int(start_ns), side="right"))
        b = int(np.searchsorted(self._f_time, until_ns, side="right"))
        return self._funding.iloc[a:max(a, b)].reset_index(drop=True)

    def server_time_ns(self) -> int | None:
        return None
