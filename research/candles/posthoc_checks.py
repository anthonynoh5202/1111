"""사후 점검(결과를 본 뒤 추가) — 사전 등록 판정을 바꾸지 않는다. 통과 후보가 우연·상승장 효과인지 따져 본다.

무엇을 보나
1. 검증 기간 모든 봉에서 신호대로 들고 있었을 때(겹침 허용) 거래당 평균 수익과, 겹침을 고려한 t값(Newey–West, 시차 h−1).
   비용 전 / 시장가 왕복 0.14% 뒤 / 지정가 왕복 0.04% 뒤.
2. 겹치지 않게 고르는 시작 위치 0~h−1 각각의 거래당 평균(사전 등록은 0만 썼다) → 숫자가 시작 위치에 얼마나 흔들리나.
3. 연도별(2024·2025·2026) 거래당 평균과 같은 해 '아무 때나 롱' 평균.
대상: 사전 등록에서 '확인'된 단일 특징 4개 + 4h/4봉 lower·close_pos(같은 꼬리·종가 계열 비교) + 묶음 모델 9개 전부.
실행: .venv/bin/python -I research/candles/posthoc_checks.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candle_features as cf  # noqa: E402


def hac_t(z: np.ndarray, lags: int) -> float:
    """합계의 Newey–West 분산으로 t값(평균 0 검정)."""
    n = len(z)
    if n < 10:
        return float("nan")
    zc = z - z.mean()
    var = float(zc @ zc) / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * float(zc[k:] @ zc[:-k]) / n
    se_sum = math.sqrt(max(var, 1e-30) * n)
    return float(z.sum() / se_sum)


def evaluate(pos: np.ndarray, r: np.ndarray, valid: np.ndarray, is_is: np.ndarray, years: np.ndarray, h: int) -> dict:
    om = valid & ~is_is
    p = np.where(om, pos, 0.0)
    rr = np.where(om, r, 0.0)
    active = p != 0
    n_act = int(active.sum())
    out = {"n_active_bars": n_act}
    if n_act < 20:
        return out
    idx = np.where(om)[0]
    z = (p * rr)[idx]
    a = active[idx]
    for tag, cost in (("gross", 0.0), ("taker", cf.COST_TAKER), ("maker", cf.COST_MAKER)):
        zz = z - a * cost
        out[f"{tag}_mean_pct"] = round(float(zz.sum() / n_act) * 100, 4)
        out[f"{tag}_t_hac"] = round(hac_t(zz, h - 1), 2)
    out["hit"] = round(float(((p * rr)[active] > 0).mean()), 4)
    offs = []
    for off in range(h):
        s = active & ((np.arange(len(r)) % h) == off)
        offs.append(round(float((p * rr)[s].mean()) * 100, 4) if s.sum() else None)
    out["offset_gross_mean_pct"] = offs
    yrs = {}
    for y in (2024, 2025, 2026):
        s = active & (years == y)
        anyl = om & (years == y)
        yrs[y] = dict(n=int(s.sum()), gross_mean_pct=round(float((p * rr)[s].mean()) * 100, 4) if s.sum() else None,
                      any_long_mean_pct=round(float(r[anyl].mean()) * 100, 4) if anyl.sum() else None)
    out["years"] = yrs
    out["long_share"] = round(float((p[active] > 0).mean()), 3)
    return out


def single(bars, tf: str, h: int, feat: str) -> dict:
    df = bars[tf]
    O, H, L, C, V, TB = cf.arrays(df)
    is_is = (df["time"] < cf.IS_END).to_numpy()
    years = df["time"].dt.year.to_numpy()
    x = cf.features(O, H, L, C, V, TB)[feat]
    r, valid, sel = cf.fwd(C, is_is, h)
    im = valid & sel & np.isfinite(x) & is_is  # 사전 등록과 같은 학습 표본
    q20, q80 = np.quantile(x[im], [0.2, 0.8])
    d = r[im & (x >= q80)].mean() - r[im & (x <= q20)].mean()
    sgn = 1.0 if d >= 0 else -1.0
    pos = np.where(x >= q80, sgn, np.where(x <= q20, -sgn, 0.0))
    pos[~np.isfinite(x)] = 0.0
    res = evaluate(pos, r, valid, is_is, years, h)
    res["is_sign"] = "위 20%면 롱" if sgn > 0 else "위 20%면 숏"
    return res


def model(bars, tf: str, h: int) -> dict:
    df = bars[tf]
    O, H, L, C, V, TB = cf.arrays(df)
    is_is = (df["time"] < cf.IS_END).to_numpy()
    years = df["time"].dt.year.to_numpy()
    F = cf.features(O, H, L, C, V, TB)
    cols = []
    for k in (0, 1, 2):
        for a in F.values():
            b = np.full_like(a, np.nan)
            b[k:] = a[: len(a) - k] if k else a
            cols.append(b)
    X = np.column_stack(cols)
    finite = np.all(np.isfinite(X), axis=1)
    r, valid, _ = cf.fwd(C, is_is, h)
    ok = valid & finite
    tr_m = ok & is_is
    mu, sd = X[tr_m].mean(0), X[tr_m].std(0)
    sd[sd == 0] = 1.0
    Z = np.where(np.isfinite(X), (X - mu) / sd, 0.0)
    w = cf.logistic(Z[tr_m], (r[tr_m] > 0).astype(float), cf.LAM)
    q20, q80 = np.quantile(cf.predict(w, Z[tr_m]), [0.2, 0.8])
    p = cf.predict(w, Z)
    pos = np.where(p >= q80, 1.0, np.where(p <= q20, -1.0, 0.0))
    pos[~finite] = 0.0
    return evaluate(pos, r, valid & finite, is_is, years, h)


def main() -> None:
    bars = {tf: cf.load(tf) for tf in cf.TFS}
    res = {"note": "사후 점검(결과를 본 뒤 추가). 사전 등록 판정을 바꾸지 않는다.", "single": {}, "model": {}}
    for tf, h, feat in [("1h", 1, "lower"), ("1h", 1, "close_pos"), ("1h", 1, "lower_vol"), ("4h", 4, "upper_vol"),
                        ("4h", 4, "lower"), ("4h", 4, "close_pos")]:
        res["single"][f"{tf}/{h}/{feat}"] = single(bars, tf, h, feat)
    for tf in cf.TFS:
        for h in cf.HORIZONS:
            res["model"][f"{tf}/{h}"] = model(bars, tf, h)
    (cf.OUT / "posthoc.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    for grp in ("single", "model"):
        for k, v in res[grp].items():
            print(grp, k, {kk: v.get(kk) for kk in ("is_sign", "n_active_bars", "hit", "gross_mean_pct", "gross_t_hac",
                                                     "taker_mean_pct", "taker_t_hac", "maker_mean_pct", "maker_t_hac",
                                                     "offset_gross_mean_pct", "long_share")})
            print("    years", v.get("years"))


if __name__ == "__main__":
    main()
