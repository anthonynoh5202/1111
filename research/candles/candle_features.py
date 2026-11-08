"""캔들 모양·거래량 검증 — 몸통·꼬리·종가 위치·크기·거래량이 BTC의 다음 움직임 방향을 비용을 넘을 만큼 알려 주는가.

명세: research/candles/PREREGISTRATION.md (결과를 보기 전에 고정). 이 파일은 그 명세를 그대로 구현한다.
실행: .venv/bin/python -I research/candles/candle_features.py
결과: research/candles/results/ (single_tests.csv, model_tests.csv, summary.json)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "binance"
OUT = Path(__file__).resolve().parent / "results"

TFS = ["1h", "4h", "1d"]
HORIZONS = [1, 4, 12]
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
WARMUP = 30
AVG = 20
COST_TAKER = 0.0014  # 시장가 왕복: 수수료 0.05%×2 + 미끄러짐 0.02%×2
COST_MAKER = 0.0004  # 지정가 왕복: 0.02%×2
Q_BH = 0.10
N_FAKE = 20
LAM = 1.0
N_PERM_AUC = 200
SEED = 20261108

FEATURES = {
    "body": "몸통 방향·비율",
    "upper": "윗꼬리 비율",
    "lower": "아랫꼬리 비율",
    "close_pos": "봉 안 종가 위치",
    "size": "봉 크기(평소 대비)",
    "body_size": "장대양봉(+)·장대음봉(−)",
    "vol": "거래량 배수",
    "buy": "시장가 매수 비중",
    "vol_dir": "거래량 실린 양봉(+)·음봉(−)",
    "upper_vol": "거래량 터진 윗꼬리",
    "lower_vol": "거래량 터진 아랫꼬리",
    "pos20": "최근 20봉 범위 안 위치",
    "ret5": "최근 5봉 흐름",
}


def load(tf: str) -> pd.DataFrame:
    cols = ["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"]
    df = pd.read_csv(DATA / f"BTCUSDT_{tf}.csv.gz", usecols=cols)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    return df[["time", "open", "high", "low", "close", "volume", "taker_buy_volume"]]


def arrays(df: pd.DataFrame):
    return tuple(df[c].to_numpy(float) for c in ["open", "high", "low", "close", "volume", "taker_buy_volume"])


def features(O, H, L, C, V, TB) -> dict[str, np.ndarray]:
    with np.errstate(divide="ignore", invalid="ignore"):
        rng_ = H - L
        rnz = np.where(rng_ > 0, rng_, np.nan)
        body = C - O
        upper = H - np.maximum(O, C)
        lower = np.minimum(O, C) - L
        avg_rng = pd.Series(rng_).shift(1).rolling(AVG).mean().to_numpy()
        avg_abs_body = pd.Series(np.abs(body)).shift(1).rolling(AVG).mean().to_numpy()
        avg_vol = pd.Series(V).shift(1).rolling(AVG).mean().to_numpy()
        vol = V / avg_vol
        f = {
            "body": body / rnz,
            "upper": upper / rnz,
            "lower": lower / rnz,
            "close_pos": (C - L) / rnz,
            "size": rng_ / avg_rng,
            "body_size": body / avg_abs_body,
            "vol": vol,
            "buy": TB / np.where(V > 0, V, np.nan),
        }
        f["vol_dir"] = np.sign(body) * vol
        f["upper_vol"] = f["upper"] * vol
        f["lower_vol"] = f["lower"] * vol
        hi20 = pd.Series(H).rolling(20).max().to_numpy()
        lo20 = pd.Series(L).rolling(20).min().to_numpy()
        f["pos20"] = (C - lo20) / np.where(hi20 > lo20, hi20 - lo20, np.nan)
        c5 = np.full_like(C, np.nan)
        c5[5:] = C[:-5]
        f["ret5"] = np.log(C / c5)
    for k in f:
        a = np.asarray(f[k], dtype=float)
        a[~np.isfinite(a)] = np.nan
        a[:WARMUP] = np.nan
        f[k] = a
    return f


def fwd(C: np.ndarray, is_is: np.ndarray, h: int):
    n = len(C)
    r = np.full(n, np.nan)
    r[: n - h] = np.log(C[h:] / C[: n - h])
    same = np.zeros(n, dtype=bool)
    same[: n - h] = is_is[: n - h] == is_is[h:]
    valid = np.isfinite(r) & same
    valid[:WARMUP] = False
    sel = np.zeros(n, dtype=bool)
    sel[::h] = True  # 겹치지 않게 h봉마다 하나
    return r, valid, sel


def welch(a: np.ndarray, b: np.ndarray):
    """평균 차이(a−b), z, 양쪽 p, 한쪽 p(a > b)."""
    na, nb = len(a), len(b)
    if na < 10 or nb < 10:
        return (np.nan,) * 4
    va, vb = a.var(ddof=1), b.var(ddof=1)
    se = math.sqrt(va / na + vb / nb)
    d = float(a.mean() - b.mean())
    if se == 0:
        return d, np.nan, np.nan, np.nan
    z = d / se
    return d, z, math.erfc(abs(z) / math.sqrt(2)), 0.5 * math.erfc(z / math.sqrt(2))


def single_tests(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for tf in TFS:
        df = bars[tf]
        O, H, L, C, V, TB = arrays(df)
        is_is = (df["time"] < IS_END).to_numpy()
        F = features(O, H, L, C, V, TB)
        for h in HORIZONS:
            r, valid, sel = fwd(C, is_is, h)
            for fname, x in F.items():
                ok = valid & sel & np.isfinite(x)
                im, om = ok & is_is, ok & ~is_is
                row = dict(tf=tf, h=h, feature=fname, name_kr=FEATURES[fname], n_is=int(im.sum()), n_oos=int(om.sum()))
                if im.sum() < 50 or om.sum() < 50:
                    rows.append(row)
                    continue
                q20, q80 = np.quantile(x[im], [0.2, 0.8])
                lo_i, hi_i = im & (x <= q20), im & (x >= q80)
                lo_o, hi_o = om & (x <= q20), om & (x >= q80)
                d_is, z_is, p2_is, _ = welch(r[hi_i], r[lo_i])
                d_oos, z_oos, _, p1_hi = welch(r[hi_o], r[lo_o])
                sgn = 1.0 if (np.isfinite(d_is) and d_is >= 0) else -1.0
                p1_oos = p1_hi if sgn > 0 else (1 - p1_hi if np.isfinite(p1_hi) else np.nan)
                tr_is = np.concatenate([sgn * r[hi_i], -sgn * r[lo_i]])
                tr_oos = np.concatenate([sgn * r[hi_o], -sgn * r[lo_o]])
                row.update(q20=float(q20), q80=float(q80),
                           top_mean_is=float(r[hi_i].mean()), bot_mean_is=float(r[lo_i].mean()),
                           diff_is=d_is, z_is=z_is, p2_is=p2_is,
                           top_mean_oos=float(r[hi_o].mean()), bot_mean_oos=float(r[lo_o].mean()),
                           diff_oos=d_oos, z_oos=z_oos, p1_oos_same_sign=p1_oos,
                           trade_n_oos=int(len(tr_oos)), trade_mean_is=float(tr_is.mean()),
                           trade_mean_oos=float(tr_oos.mean()), trade_hit_oos=float((tr_oos > 0).mean()),
                           net_taker_oos=float(tr_oos.mean() - COST_TAKER), net_maker_oos=float(tr_oos.mean() - COST_MAKER))
                rows.append(row)
    return pd.DataFrame(rows)


def bh(p: np.ndarray, q: float) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    out = np.zeros(len(p), dtype=bool)
    idx = np.where(np.isfinite(p))[0]
    if not len(idx):
        return out
    ps = p[idx]
    order = np.argsort(ps)
    m = len(ps)
    passed = ps[order] <= q * np.arange(1, m + 1) / m
    if passed.any():
        out[idx[order[: np.max(np.where(passed)[0]) + 1]]] = True
    return out


def judge(st: pd.DataFrame) -> dict:
    disc = bh(st["p2_is"].to_numpy(), Q_BH)
    same = np.sign(st["diff_oos"].to_numpy()) == np.sign(st["diff_is"].to_numpy())
    conf = disc & same & (st["p1_oos_same_sign"].to_numpy() < 0.05)
    money_t = conf & (st["net_taker_oos"].to_numpy() > 0)
    money_m = conf & (st["net_maker_oos"].to_numpy() > 0)
    lab = (st["tf"] + "/" + st["h"].astype(str) + "/" + st["feature"]).to_numpy()
    return dict(tests=int(len(st)), is_raw_p05=int((st["p2_is"] < 0.05).sum()), is_discoveries=int(disc.sum()),
                oos_confirmed=int(conf.sum()), oos_money_taker=int(money_t.sum()), oos_money_maker=int(money_m.sum()),
                discovered=list(lab[disc]), confirmed=list(lab[conf]),
                money_taker=list(lab[money_t]), money_maker=list(lab[money_m]))


def logistic(X: np.ndarray, y: np.ndarray, lam: float, iters: int = 30) -> np.ndarray:
    Xb = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(Xb.shape[1])
    pen = np.full(Xb.shape[1], lam)
    pen[0] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(Xb @ w, -30, 30)))
        g = Xb.T @ (p - y) + pen * w
        Hm = (Xb * (p * (1 - p))[:, None]).T @ Xb + np.diag(pen)
        step = np.linalg.solve(Hm, g)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


def predict(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(w[0] + X @ w[1:], -30, 30)))


def auc(p: np.ndarray, y: np.ndarray) -> float:
    ranks = pd.Series(p).rank().to_numpy()
    npos = int(y.sum())
    nneg = len(y) - npos
    if npos == 0 or nneg == 0:
        return float("nan")
    return float((ranks[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def model_tests(bars: dict[str, pd.DataFrame], rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for tf in TFS:
        df = bars[tf]
        O, H, L, C, V, TB = arrays(df)
        is_is = (df["time"] < IS_END).to_numpy()
        F = features(O, H, L, C, V, TB)
        cols = []
        for k in (0, 1, 2):
            for name, a in F.items():
                b = np.full_like(a, np.nan)
                b[k:] = a[: len(a) - k] if k else a
                cols.append(b)
        X = np.column_stack(cols)
        finite = np.all(np.isfinite(X), axis=1)
        for h in HORIZONS:
            r, valid, sel = fwd(C, is_is, h)
            ok = valid & finite
            tr_m, te_m = ok & is_is, ok & ~is_is & sel
            mu, sd = X[tr_m].mean(0), X[tr_m].std(0)
            sd[sd == 0] = 1.0
            Z = (X - mu) / sd
            y_tr = (r[tr_m] > 0).astype(float)
            w = logistic(Z[tr_m], y_tr, LAM)
            p_tr = predict(w, Z[tr_m])
            q20, q80 = np.quantile(p_tr, [0.2, 0.8])
            p_te = predict(w, Z[te_m])
            y_te = (r[te_m] > 0).astype(int)
            a = auc(p_te, y_te)
            perm = np.array([auc(p_te, rng.permutation(y_te)) for _ in range(N_PERM_AUC)])
            lo_b, hi_b = np.quantile(perm, [0.025, 0.975])
            rt = r[te_m]
            trades = np.concatenate([rt[p_te >= q80], -rt[p_te <= q20]])
            acc = float(((p_te > 0.5).astype(int) == y_te).mean())
            rows.append(dict(tf=tf, h=h, n_train=int(tr_m.sum()), n_test=int(te_m.sum()),
                             auc_oos=round(a, 4), auc_chance_lo=round(float(lo_b), 4), auc_chance_hi=round(float(hi_b), 4),
                             acc_oos=round(acc, 4), base_up_oos=round(float(y_te.mean()), 4),
                             trades=int(len(trades)), trade_mean_pct=round(float(trades.mean()) * 100, 4),
                             trade_hit=round(float((trades > 0).mean()), 4),
                             net_taker_pct=round(float(trades.mean() - COST_TAKER) * 100, 4),
                             net_maker_pct=round(float(trades.mean() - COST_MAKER) * 100, 4)))
    return pd.DataFrame(rows)


def fake_bars(real: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    O, H, L, C, V, TB = arrays(real)
    lh, ll, lc = np.log(H / O), np.log(L / O), np.log(C / O)
    n = len(real)
    idx = rng.integers(WARMUP, n, size=n)
    closes = C[0] * np.exp(np.cumsum(lc[idx]))
    opens = np.concatenate([[C[0]], closes[:-1]])
    return pd.DataFrame(dict(time=real["time"].to_numpy(), open=opens, high=opens * np.exp(lh[idx]),
                             low=opens * np.exp(ll[idx]), close=closes, volume=V[idx], taker_buy_volume=TB[idx]))


def size_info(bars: dict[str, pd.DataFrame]) -> list[dict]:
    out = []
    for tf in TFS:
        df = bars[tf]
        O, H, L, C, V, TB = arrays(df)
        is_is = (df["time"] < IS_END).to_numpy()
        F = features(O, H, L, C, V, TB)
        r, valid, sel = fwd(C, is_is, 1)
        for fname in ("size", "vol"):
            x = F[fname]
            im = valid & is_is & np.isfinite(x)
            om = valid & ~is_is & np.isfinite(x)
            q20, q80 = np.quantile(x[im], [0.2, 0.8])
            top = np.abs(r[om & (x >= q80)]).mean()
            bot = np.abs(r[om & (x <= q20)]).mean()
            out.append(dict(tf=tf, feature=fname, next_abs_move_top_pct=round(float(top) * 100, 3),
                            next_abs_move_bottom_pct=round(float(bot) * 100, 3), ratio=round(float(top / bot), 2)))
    return out


def breakeven(bars: dict[str, pd.DataFrame]) -> list[dict]:
    out = []
    for tf in TFS:
        df = bars[tf]
        C = df["close"].to_numpy(float)
        is_is = (df["time"] < IS_END).to_numpy()
        for h in HORIZONS:
            r, valid, sel = fwd(C, is_is, h)
            mabs = float(np.abs(r[valid & ~is_is & sel]).mean())
            out.append(dict(tf=tf, h=h, mean_abs_move_pct=round(mabs * 100, 3),
                            need_hit_taker_pct=round((0.5 + COST_TAKER / (2 * mabs)) * 100, 1),
                            need_hit_maker_pct=round((0.5 + COST_MAKER / (2 * mabs)) * 100, 1)))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    bars = {tf: load(tf) for tf in TFS}
    st = single_tests(bars)
    st.to_csv(OUT / "single_tests.csv", index=False, float_format="%.6g")
    mt = model_tests(bars, rng)
    mt.to_csv(OUT / "model_tests.csv", index=False)
    summary = dict(single=judge(st), model=mt.to_dict(orient="records"), size_info=size_info(bars),
                   breakeven=breakeven(bars),
                   data_span={tf: [str(b["time"].iloc[0]), str(b["time"].iloc[-1]), int(len(b))] for tf, b in bars.items()})
    fakes = []
    for k in range(N_FAKE):
        fb = {tf: fake_bars(bars[tf], rng) for tf in TFS}
        j = judge(single_tests(fb))
        fakes.append({kk: j[kk] for kk in ("is_raw_p05", "is_discoveries", "oos_confirmed", "oos_money_taker", "oos_money_maker")})
    summary["fake"] = dict(per_world=fakes,
                           mean={kk: float(np.mean([f[kk] for f in fakes])) for kk in fakes[0]},
                           max={kk: int(np.max([f[kk] for f in fakes])) for kk in fakes[0]})
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
