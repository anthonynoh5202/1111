"""받은 바이낸스 데이터의 품질을 점검한다.

점검 항목
- 캔들: 시간 중복, 빠진 봉(구간), 가격 논리(고가 ≥ 시가·종가 ≥ 저가), 0 이하 가격, 거래량 0인 봉,
        봉 하나에서 비정상적으로 큰 움직임, 테이커 매수량 ≤ 전체 거래량
- 봉 간 일치: 5분봉을 합쳐 만든 1시간봉이 1시간봉 파일과 같은지 (1분봉 → 5분봉도)
- 펀딩비·미결제약정: 기간, 빈 구간, 값 범위

실행: python tools/check_data.py  → 결과를 화면과 data/binance/quality_report.json 에 남긴다.
"""
import json
import pathlib

import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "binance"
MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
report = {}


def load_klines(tf):
    if tf == "1m":
        files = sorted(DATA.glob("BTCUSDT_1m_*.csv.gz"))
        df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    else:
        df = pd.read_csv(DATA / f"BTCUSDT_{tf}.csv.gz")
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.sort_values("time").reset_index(drop=True)


def gaps(times, step):
    """예상 간격보다 벌어진 곳: (시작, 끝, 빠진 봉 수) 목록."""
    diff = times.diff()
    out = []
    for i in diff.index[diff > step]:
        missing = int(diff[i] / step) - 1
        out.append((str(times[i - 1]), str(times[i]), missing))
    return out


def check_klines(tf):
    df = load_klines(tf)
    step = pd.Timedelta(minutes=MINUTES[tf])
    g = gaps(df["time"], step)
    r = {
        "rows": len(df),
        "from": str(df["time"].iloc[0]),
        "to": str(df["time"].iloc[-1]),
        "duplicates": int(df["time"].duplicated().sum()),
        "gap_count": len(g),
        "missing_bars": sum(x[2] for x in g),
        "largest_gaps": sorted(g, key=lambda x: -x[2])[:5],
        "bad_ohlc": int(((df.high < df[["open", "close"]].max(axis=1)) | (df.low > df[["open", "close"]].min(axis=1))).sum()),
        "nonpositive_price": int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()),
        "zero_volume_bars": int((df.volume == 0).sum()),
        "taker_gt_volume": int((df.taker_buy_volume > df.volume * (1 + 1e-9)).sum()),
    }
    rng = (df.high - df.low) / df.low
    r["max_bar_range_pct"] = round(float(rng.max() * 100), 2)
    r["max_bar_range_at"] = str(df.loc[rng.idxmax(), "time"])
    report[tf] = r
    return df


def compare_resample(small, big, small_tf, big_tf):
    """작은 봉을 합친 결과가 큰 봉 파일과 같은지 본다 (겹치는 기간만)."""
    s = small.set_index("time")
    rule = {"1h": "1h", "5m": "5min"}[big_tf]
    agg = s.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    b = big.set_index("time")[["open", "high", "low", "close", "volume"]]
    both = agg.join(b, rsuffix="_file", how="inner")
    diff = {}
    for c in ["open", "high", "low", "close"]:
        diff[c] = int((both[c] - both[c + "_file"]).abs().gt(1e-6).sum())
    diff["volume_rel_gt_0.1pct"] = int(((both.volume - both.volume_file).abs() / both.volume_file.clip(lower=1e-9)).gt(0.001).sum())
    report[f"{small_tf}_to_{big_tf}"] = {"compared_bars": len(both), "mismatches": diff}


def check_funding():
    df = pd.read_csv(DATA / "BTCUSDT_fundingRate.csv.gz")
    df["time"] = pd.to_datetime(df["calc_time"], unit="ms", utc=True).dt.floor("h")
    iv = df["time"].diff().dropna()
    rate = df["last_funding_rate"]
    report["fundingRate"] = {
        "rows": len(df),
        "from": str(df["time"].iloc[0]), "to": str(df["time"].iloc[-1]),
        "intervals_hours": {str(k): int(v) for k, v in (iv / pd.Timedelta(hours=1)).value_counts().head(5).items()},
        "rate_min_pct": round(float(rate.min() * 100), 4), "rate_max_pct": round(float(rate.max() * 100), 4),
        "rate_mean_pct": round(float(rate.mean() * 100), 5),
    }


def check_metrics():
    df = pd.read_csv(DATA / "BTCUSDT_metrics.csv.gz")
    df["time"] = pd.to_datetime(df["create_time"], utc=True)
    df = df.sort_values("time")
    g = gaps(df["time"].reset_index(drop=True), pd.Timedelta(minutes=5))
    cols = [c for c in df.columns if c not in ("create_time", "symbol", "time")]
    report["metrics"] = {
        "rows": len(df), "columns": cols,
        "from": str(df["time"].iloc[0]), "to": str(df["time"].iloc[-1]),
        "duplicates": int(df["time"].duplicated().sum()),
        "gap_count": len(g), "missing_points": sum(x[2] for x in g),
        "largest_gaps": sorted(g, key=lambda x: -x[2])[:5],
        "null_cells": {c: int(df[c].isna().sum()) for c in cols if df[c].isna().any()},
    }


def main():
    frames = {tf: check_klines(tf) for tf in MINUTES}
    compare_resample(frames["5m"], frames["1h"], "5m", "1h")
    compare_resample(frames["1m"], frames["5m"], "1m", "5m")
    check_funding()
    check_metrics()
    (DATA / "quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
