"""검증 V4 — 장애 주입 퍼징을 검토자·수정 담당이 쓰지 않은 seed로 확장 (독립 검증관).

review_chaos_test._fuzz_once(가짜 거래소 장애 1~4개 + 무작위 강제 종료 + 5초 중단 + exit 요청·손절 발동)를 그대로 쓰되
seed 범위를 바꿔 돌린다. 수정 담당이 보고한 범위는 0-599. 여기서는 기본 1000-2999(2,000개).

판정(각 seed): 끝 상태 포지션 ≥ 0, 보호됨(포지션 0 또는 우리 손절), 진입 POST ≤ 1, 노출 의도 ≤ 1,
'DB는 끝났다는데 거래소 포지션 > 0' 없음. 추가로 무방비 최대 구간(가짜 시계 ms)의 분포.

실행: .venv/bin/python -m bot.orders.verify.fuzz_extended [--start 1000 --count 2000 --jobs 4]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results" / "fuzz_extended.json"


def one(seed: int) -> dict:
    from bot.orders.tests.conftest import T_APPROVED_MS
    from bot.orders.tests.review_chaos_test import _fuzz_once
    from bot.types import FakeClock, NS_PER_MS

    with tempfile.TemporaryDirectory() as d:
        o = _fuzz_once(seed, Path(d), FakeClock((T_APPROVED_MS + 5_000) * NS_PER_MS))
    o["bad"] = (o["pos"] < 0 or o["e1"] > 1 or o["live"] > 1 or not o["protected"]
                or (o["db_says_flat"] and o["pos"] > 0))
    return o


def main(argv: list[str] | None = None) -> int:
    import logging

    logging.disable(logging.CRITICAL)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1000)
    ap.add_argument("--count", type=int, default=2000)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    seeds = range(a.start, a.start + a.count)
    with ProcessPoolExecutor(a.jobs, initializer=logging.disable, initargs=(logging.CRITICAL,)) as ex:
        res = list(ex.map(one, seeds, chunksize=20))
    bad = [r for r in res if r["bad"]]
    worst = sorted(res, key=lambda r: -r["worst"])[:15]
    hist = collections.Counter(("0" if r["worst"] == 0 else "<=5s" if r["worst"] <= 5000 else "<=6s"
                                if r["worst"] <= 6000 else "<=10s" if r["worst"] <= 10_000 else ">10s") for r in res)
    states = collections.Counter(r["state"] for r in res)
    out = dict(seeds=[a.start, a.start + a.count - 1], n=len(res), bad=bad, worst_top=worst,
               worst_hist=dict(hist), end_states=dict(states),
               with_crash=sum(1 for r in res if r["crash"] is not None))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(dict(n=out["n"], bad=len(bad), worst_hist=out["worst_hist"], end_states=out["end_states"],
                          worst_top=[(r["seed"], r["worst"], r["state"], r["reason"], r["crash"]) for r in worst]),
                     ensure_ascii=False, indent=1))
    for r in bad:
        print("BAD", r)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
