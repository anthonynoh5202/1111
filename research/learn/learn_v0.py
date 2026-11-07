"""캔들 학습 실험 v0 — 과거 1시간봉으로 '무엇을 배울 수 있나'를 정직하게 잰다.

배우는 것(목표 3개):
  1) 방향: 다음 24시간 뒤 종가가 오를까(분류)
  2) 크기: 다음 24시간 고가~저가 폭(회귀)  = 변동성
  3) 목표 먼저: 지금 롱이면 +2%가 -1%보다 먼저 닿을까(72시간 안, 분류)
특징: 캔들 모양(1h·4h·24h 굴린 캔들), 거래량(시간대 보정), 테이커 매수 비율, 변동성, 이평 거리, 고점·저점 거리, 시간.
검증: 2020~2023 학습(마지막 1년은 조기 종료용), 72봉 엠바고, 2024-01~2026-09 OOS. 연도별 워크포워드.
"""
from __future__ import annotations

import json
import pathlib
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
H = 24          # 방향·폭 지평(시간)
TP, SL, TMAX = 0.02, 0.01, 72
COST = 0.0014   # 왕복 비용(테이커 0.05%×2 + 슬리피지 0.02%×2)


def load() -> pd.DataFrame:
    df = pd.read_csv(REPO / "data/binance/BTCUSDT_1h.csv.gz")
    df["t"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("t")[["open", "high", "low", "close", "volume", "taker_buy_volume"]].astype(float)
    return df


def features(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v, tb = (df[k] for k in ("open", "high", "low", "close", "volume", "taker_buy_volume"))
    f = pd.DataFrame(index=df.index)
    lc = np.log(c)
    for k in (1, 2, 4, 8, 12, 24, 48, 72, 168, 336):
        f[f"lr_{k}"] = lc - lc.shift(k)
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    f["atr_rel"] = atr / c

    def shape(oo, hh, ll, cc, tag, scale):
        rng = (hh - ll).replace(0, np.nan)
        f[f"body_{tag}"] = (cc - oo) / rng
        f[f"uw_{tag}"] = (hh - np.maximum(oo, cc)) / rng
        f[f"lw_{tag}"] = (np.minimum(oo, cc) - ll) / rng
        f[f"pos_{tag}"] = (cc - ll) / rng
        f[f"rng_{tag}"] = (hh - ll) / (atr * scale)

    shape(o, h, l, c, "1h", 1.0)
    for n in (4, 24):
        shape(o.shift(n - 1), h.rolling(n).max(), l.rolling(n).min(), c, f"{n}h", np.sqrt(n))
    lv = np.log(v.replace(0, np.nan))
    f["vr_1h"] = v / v.shift(1).rolling(20).mean()
    hod = df.index.hour
    # 같은 시간대(시) 지난 20일 평균 대비 거래량(시간대 패턴 제거)
    lv_hod_mean = lv.groupby(hod).transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    f["vz_hod"] = lv - lv_hod_mean
    f["vr_24h"] = v.rolling(24).sum() / (v.shift(24).rolling(480).sum() / 20)
    f["tbr_1h"] = tb / v.replace(0, np.nan)
    f["tbr_24h"] = tb.rolling(24).sum() / v.rolling(24).sum()
    r1 = lc.diff()
    f["rv_24"] = r1.rolling(24).std()
    f["rv_168"] = r1.rolling(168).std()
    f["rv_ratio"] = f["rv_24"] / f["rv_168"]
    f["atr_z"] = (f["atr_rel"] - f["atr_rel"].rolling(720).mean()) / f["atr_rel"].rolling(720).std()
    for n in (20, 60, 120, 240, 480, 1440):
        f[f"dma_{n}"] = c / c.rolling(n).mean() - 1
    for n in (24, 120, 480):
        f[f"dhi_{n}"] = c / h.shift(1).rolling(n).max() - 1
        f[f"dlo_{n}"] = c / l.shift(1).rolling(n).min() - 1
    f["hod_s"], f["hod_c"] = np.sin(2 * np.pi * hod / 24), np.cos(2 * np.pi * hod / 24)
    dow = df.index.dayofweek
    f["dow_s"], f["dow_c"] = np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7)
    return f


def targets(df: pd.DataFrame) -> pd.DataFrame:
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    n = len(c)
    y = pd.DataFrame(index=df.index)
    fwd = np.full(n, np.nan)
    fwd[:-H] = np.log(c[H:] / c[:-H])
    y["ret24"] = fwd
    y["up24"] = np.where(np.isnan(fwd), np.nan, (fwd > 0).astype(float))
    hw = np.lib.stride_tricks.sliding_window_view(h[1:], H)
    lw = np.lib.stride_tricks.sliding_window_view(l[1:], H)
    rng = np.full(n, np.nan)
    m = len(hw)
    rng[:m] = np.log((hw.max(1) - lw.min(1)) / c[:m])
    y["lrange24"] = rng
    tp = np.full(n, np.nan)
    for i in range(n - TMAX):
        up, dn = c[i] * (1 + TP), c[i] * (1 - SL)
        hh, ll = h[i + 1:i + 1 + TMAX], l[i + 1:i + 1 + TMAX]
        ih = np.flatnonzero(hh >= up)
        il = np.flatnonzero(ll <= dn)
        a = ih[0] if len(ih) else 10 ** 9
        b = il[0] if len(il) else 10 ** 9
        tp[i] = 1.0 if a < b else 0.0          # 같은 봉에 둘 다면 손절로(보수적), 둘 다 없으면 0
    y["tp_first"] = tp
    return y


def split(idx: pd.DatetimeIndex):
    is_end = pd.Timestamp("2024-01-01", tz="UTC")
    val_start = pd.Timestamp("2023-01-01", tz="UTC")
    emb = pd.Timedelta(hours=TMAX)
    tr = (idx < val_start - emb)
    va = (idx >= val_start) & (idx < is_end - emb)
    te = (idx >= is_end)
    return tr, va, te


def lgb_cls(Xtr, ytr, Xva, yva):
    m = lgb.LGBMClassifier(n_estimators=2000, learning_rate=0.02, num_leaves=15, min_child_samples=400,
                           subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1,
                           random_state=7)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)], eval_metric="auc",
          callbacks=[lgb.early_stopping(100, verbose=False)])
    return m


def lgb_reg(Xtr, ytr, Xva, yva, **kw):
    m = lgb.LGBMRegressor(n_estimators=2000, learning_rate=0.02, num_leaves=15, min_child_samples=400,
                          subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, verbose=-1,
                          random_state=7, **kw)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)], callbacks=[lgb.early_stopping(100, verbose=False)])
    return m


def calib(p, y, bins=10):
    q = pd.qcut(p, bins, labels=False, duplicates="drop")
    t = pd.DataFrame({"p": p, "y": y, "q": q}).groupby("q").agg(p=("p", "mean"), y=("y", "mean"), n=("y", "size"))
    return [[round(a, 3), round(b, 3), int(c)] for a, b, c in t.itertuples(index=False)]


def main():
    df = load()
    X = features(df)
    Y = targets(df)
    data = X.join(Y).replace([np.inf, -np.inf], np.nan).dropna()
    cols = list(X.columns)
    tr, va, te = split(data.index)
    res = {"n": {"train": int(tr.sum()), "val": int(va.sum()), "test": int(te.sum())}, "features": len(cols)}

    # 1) 방향(24h)
    ytr, yva, yte = data.loc[tr, "up24"], data.loc[va, "up24"], data.loc[te, "up24"]
    lr = make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=2000))
    lr.fit(data.loc[tr, cols], ytr)
    p_lr = lr.predict_proba(data.loc[te, cols])[:, 1]
    gb = lgb_cls(data.loc[tr, cols], ytr, data.loc[va, cols], yva)
    p_gb = gb.predict_proba(data.loc[te, cols])[:, 1]
    res["dir24"] = dict(
        base_up_test=round(float(yte.mean()), 4),
        auc_logit=round(roc_auc_score(yte, p_lr), 4), auc_lgb=round(roc_auc_score(yte, p_gb), 4),
        auc_val_lgb=round(roc_auc_score(yva, gb.predict_proba(data.loc[va, cols])[:, 1]), 4),
        acc_lgb=round(float(((p_gb > 0.5) == yte).mean()), 4), trees=int(gb.best_iteration_ or 0),
        calib_lgb=calib(p_gb, yte.to_numpy()))
    # 겹치지 않는 하루 1회(00:00 UTC = 09:00 KST) 매매 시험
    d = data.loc[te].copy()
    d["p"] = p_gb
    day = d[d.index.hour == 0]
    rows = {}
    for th in (0.52, 0.55, 0.58):
        side = np.where(day["p"] > th, 1, np.where(day["p"] < 1 - th, -1, 0))
        r = side * (np.exp(day["ret24"]) - 1) - (side != 0) * COST
        traded = side != 0
        rows[str(th)] = dict(trades=int(traded.sum()), hit=round(float((r[traded] > 0).mean()), 4) if traded.any() else None,
                             mean_ret_pct=round(float(r[traded].mean() * 100), 4) if traded.any() else None,
                             total_pct=round(float(r.sum() * 100), 2))
    rng_ = np.random.default_rng(1)
    sides = rng_.choice([-1, 1], size=(2000, len(day)))
    rr = (sides * (np.exp(day["ret24"].to_numpy()) - 1) - COST).mean(1) * 100
    rows["random_mean_ret_pct_p5_p95"] = [round(float(np.percentile(rr, 5)), 4), round(float(np.percentile(rr, 95)), 4)]
    rows["always_long_mean_ret_pct"] = round(float((np.exp(day["ret24"]) - 1 - COST).mean() * 100), 4)
    res["dir24_trading_daily"] = rows
    imp = pd.Series(gb.booster_.feature_importance("gain"), index=cols).sort_values(ascending=False)
    res["dir24_top_features"] = [[k, round(float(v / imp.sum() * 100), 1)] for k, v in imp.head(12).items()]

    # 연도별 워크포워드(방향)
    wf = {}
    for yr in (2022, 2023, 2024, 2025, 2026):
        s, e = pd.Timestamp(f"{yr}-01-01", tz="UTC"), pd.Timestamp(f"{yr + 1}-01-01", tz="UTC")
        vs = s - pd.Timedelta(days=365)
        emb = pd.Timedelta(hours=TMAX)
        a = data.index < vs - emb
        b = (data.index >= vs) & (data.index < s - emb)
        t = (data.index >= s) & (data.index < e)
        if t.sum() < 500:
            continue
        m = lgb_cls(data.loc[a, cols], data.loc[a, "up24"], data.loc[b, cols], data.loc[b, "up24"])
        wf[yr] = round(roc_auc_score(data.loc[t, "up24"], m.predict_proba(data.loc[t, cols])[:, 1]), 4)
    res["dir24_walkforward_auc"] = wf

    # 2) 크기(24h 폭)
    gr = lgb_reg(data.loc[tr, cols], data.loc[tr, "lrange24"], data.loc[va, cols], data.loc[va, "lrange24"])
    pr = gr.predict(data.loc[te, cols])
    yt = data.loc[te, "lrange24"].to_numpy()
    naive = np.log(data.loc[te, "rng_24h"].to_numpy() * data.loc[te, "atr_rel"].to_numpy() * np.sqrt(24))  # 직전 24h 폭
    def r2(p, y):
        return 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    q10 = lgb_reg(data.loc[tr, cols], data.loc[tr, "lrange24"], data.loc[va, cols], data.loc[va, "lrange24"],
                  objective="quantile", alpha=0.1).predict(data.loc[te, cols])
    q90 = lgb_reg(data.loc[tr, cols], data.loc[tr, "lrange24"], data.loc[va, cols], data.loc[va, "lrange24"],
                  objective="quantile", alpha=0.9).predict(data.loc[te, cols])
    res["range24"] = dict(
        r2_model=round(float(r2(pr, yt)), 4), r2_naive_last24=round(float(r2(naive, yt)), 4),
        corr_model=round(float(np.corrcoef(pr, yt)[0, 1]), 4),
        median_range_pct=round(float(np.exp(np.median(yt)) * 100), 3),
        coverage_80=round(float(((yt >= q10) & (yt <= q90)).mean()), 4))
    impr = pd.Series(gr.booster_.feature_importance("gain"), index=cols).sort_values(ascending=False)
    res["range24_top_features"] = [[k, round(float(v / impr.sum() * 100), 1)] for k, v in impr.head(10).items()]

    # 3) 목표 먼저(+2% vs -1%, 72h)
    gt = lgb_cls(data.loc[tr, cols], data.loc[tr, "tp_first"], data.loc[va, cols], data.loc[va, "tp_first"])
    pt = gt.predict_proba(data.loc[te, cols])[:, 1]
    yt3 = data.loc[te, "tp_first"].to_numpy()
    sel = {}
    for qq in (0.5, 0.8, 0.9):
        cut = np.quantile(pt, qq)
        mk = pt >= cut
        win = yt3[mk].mean()
        sel[f"top{int((1 - qq) * 100)}%"] = dict(tp_rate=round(float(win), 4),
                                                exp_R=round(float(win * 2 - (1 - win) * 1 - COST / SL), 3))
    res["tp_first"] = dict(base_rate_test=round(float(yt3.mean()), 4), auc=round(roc_auc_score(yt3, pt), 4),
                           base_exp_R=round(float(yt3.mean() * 2 - (1 - yt3.mean()) - COST / SL), 3),
                           by_model_rank=sel, calib=calib(pt, yt3))
    (OUT / "learn_v0.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
