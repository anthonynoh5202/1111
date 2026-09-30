"""검증 2차 — 퍼징 무방비 구간을 거래소 상태 변화마다 표본을 떠서 정확히 다시 잰다(V-3 대응, 독립 검증관).

review_chaos_test.Monitor는 B가 거래소를 부를 때만 표본을 뜬다. 여기서는 FakeExchange._process(시계 진행·늦게 도착한
요청·체결·발동 처리) 끝에서도 표본을 떠서, 가짜 시계 기준으로 '롱 포지션 + 활성 우리 closePosition 손절 없음' 구간을
정확히 잰다. 제품 코드·시험 코드는 바꾸지 않는다(이 프로세스 안에서만 감싼다).

실행: .venv/bin/python -m bot.orders.verify.fuzz_exact --start 1000 --count 9000 --jobs 4 → results/fuzz_exact.json
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results" / "fuzz_exact.json"
_PATCHED = False


def _patch() -> None:
    global _PATCHED
    if _PATCHED:
        return
    from bot.orders import fake_exchange as FE
    from bot.orders.tests import review_chaos_test as R

    orig_process = FE.FakeExchange._process
    orig_init = R.Monitor.__init__

    def process(self):  # noqa: ANN001
        orig_process(self)
        mon = getattr(self, "_verif_mon", None)
        if mon is not None and not getattr(self, "_verif_busy", False):
            self._verif_busy = True
            try:
                mon.sample()
            finally:
                self._verif_busy = False

    def init(self, fx, clock):  # noqa: ANN001
        orig_init(self, fx, clock)
        fx._verif_mon = self

    FE.FakeExchange._process = process
    R.Monitor.__init__ = init
    _PATCHED = True


def one(seed: int) -> dict:
    import logging

    logging.disable(logging.CRITICAL)
    _patch()
    from bot.orders.tests.conftest import T_APPROVED_MS
    from bot.orders.tests.review_chaos_test import _fuzz_once
    from bot.types import FakeClock, NS_PER_MS

    with tempfile.TemporaryDirectory() as d:
        o = _fuzz_once(seed, Path(d), FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS))
    o["bad"] = (o["pos"] < 0 or o["e1"] > 1 or o["live"] > 1 or not o["protected"]
                or (o["db_says_flat"] and o["pos"] > 0))
    return o


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1000)
    ap.add_argument("--count", type=int, default=9000)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--seeds", default="")
    a = ap.parse_args(argv)
    seeds = [int(s) for s in a.seeds.split(",") if s] or list(range(a.start, a.start + a.count))
    with ProcessPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, seeds, chunksize=20))
    bad = [r for r in res if r["bad"]]
    hist = collections.Counter(("0" if r["worst"] == 0 else "<=5s" if r["worst"] <= 5000 else "<=6s"
                                if r["worst"] <= 6000 else "<=10s" if r["worst"] <= 10_000 else ">10s") for r in res)
    nocrash = sorted((r for r in res if r["crash"] is None), key=lambda r: -r["worst"])
    crash = sorted((r for r in res if r["crash"] is not None), key=lambda r: -r["worst"])
    out = dict(seeds=[seeds[0], seeds[-1]], n=len(res), bad=bad, worst_hist=dict(hist),
               no_crash=dict(n=len(nocrash), worst_top=nocrash[:10],
                             over_5s=[(r["seed"], r["worst"], r["halts"]) for r in nocrash if r["worst"] > 5000]),
               with_crash=dict(n=len(crash), worst_top=crash[:10]),
               end_states=dict(collections.Counter(r["state"] for r in res)))
    if not a.seeds:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(dict(n=out["n"], bad=len(bad), hist=out["worst_hist"],
                          nocrash_top=[(r["seed"], r["worst"], r["halts"]) for r in nocrash[:8]],
                          crash_top=[(r["seed"], r["worst"], r["crash"]) for r in crash[:8]],
                          end_states=out["end_states"]), ensure_ascii=False, default=str))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
