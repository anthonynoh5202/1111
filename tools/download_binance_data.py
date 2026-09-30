"""[대표님 PC에서 실행] 바이낸스 공식 공개 데이터(data.binance.vision)에서
BTCUSDT 무기한 선물(USDⓈ-M)의 과거 데이터를 받아 합친다.

- 로그인·API 키 필요 없음 (공개 데이터)
- 파이썬 기본 라이브러리만 사용 (설치할 것 없음)
- 파일마다 바이낸스가 제공하는 SHA256 체크섬으로 무결성 확인

실행 (저장소 폴더에서):
    python tools/download_binance_data.py

결과 (data/binance/):
    BTCUSDT_5m / 15m / 1h / 4h / 1d .csv.gz      캔들 (2020년부터)
    BTCUSDT_1m_<연도>.csv.gz                       1분봉 (최근 3년, 연도별)
    BTCUSDT_fundingRate.csv.gz                                               펀딩비
    BTCUSDT_metrics.csv.gz        미결제약정·롱숏비 (5분 간격, 바이낸스가 제공하는 기간만)
    manifest.json                 받은 기간, 행 수, 실패 목록
"""
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import pathlib
import time
import urllib.error
import urllib.request
import zipfile

SYMBOL = "BTCUSDT"
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]
KLINE_START = dt.date(2020, 1, 1)
# 1분봉은 신호용이 아니라 백테스트에서 "손절과 목표 중 무엇이 먼저 닿았나"를 판정하는 용도.
# 양이 커서 최근 3년만 받고, GitHub 파일 크기 제한 때문에 연도별 파일로 나눈다.
MINUTE_START = dt.date(2023, 10, 1)
METRICS_START = dt.date(2021, 12, 1)  # 이전 날짜는 바이낸스가 제공하지 않으면 건너뜀
BASE = "https://data.binance.vision/data/futures/um"
OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "binance"
KLINE_HEADER = ["open_time", "open", "high", "low", "close", "volume", "close_time",
                "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]

failed = []


def fetch(url):
    """URL 내용을 받는다. 없으면 None. 일시 오류는 3번까지 재시도."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
        time.sleep(2 ** attempt)
    failed.append(f"{url} ({err})")
    return None


def fetch_zip_rows(url):
    """zip 하나를 받아 체크섬을 확인하고 CSV 행 목록을 돌려준다."""
    blob = fetch(url)
    if blob is None:
        return None
    checksum = fetch(url + ".CHECKSUM")
    if checksum:
        expected = checksum.decode().split()[0]
        if hashlib.sha256(blob).hexdigest() != expected:
            failed.append(f"{url} (체크섬 불일치)")
            return None
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        text = z.read(z.namelist()[0]).decode()
    rows = list(csv.reader(io.StringIO(text)))
    if rows and not rows[0][0].lstrip("-").isdigit():  # 머리글 행이 있으면 뺀다
        header, rows = rows[0], rows[1:]
    else:
        header = None
    return header, rows


def months(start, end):
    d = start.replace(day=1)
    while d < end.replace(day=1):
        yield d
        d = (d + dt.timedelta(days=32)).replace(day=1)


def days(start, end):
    d = start
    while d < end:
        yield d
        d += dt.timedelta(days=1)


def write_gz(name, header, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT / name, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def download_klines(tf, today, start=KLINE_START, split_by_year=False):
    by_time = {}
    this_month = today.replace(day=1)
    daily_from = this_month
    for m in months(start, today):
        res = fetch_zip_rows(f"{BASE}/monthly/klines/{SYMBOL}/{tf}/{SYMBOL}-{tf}-{m:%Y-%m}.zip")
        if res is None and m >= this_month - dt.timedelta(days=62):
            daily_from = min(daily_from, m)  # 최근 달의 월별 파일이 아직 없으면 일별로 채운다
        for row in (res[1] if res else []):
            by_time[int(row[0])] = row
    # 이번 달(과 월별 파일이 아직 없는 최근 달)은 일별 파일로 채운다 (어제까지)
    for d in days(daily_from, today):
        res = fetch_zip_rows(f"{BASE}/daily/klines/{SYMBOL}/{tf}/{SYMBOL}-{tf}-{d:%Y-%m-%d}.zip")
        for row in (res[1] if res else []):
            by_time[int(row[0])] = row
    rows = [by_time[k] for k in sorted(by_time)]
    if not split_by_year:
        write_gz(f"{SYMBOL}_{tf}.csv.gz", KLINE_HEADER, rows)
        return {f"{SYMBOL}_{tf}.csv.gz": rows}
    parts = {}
    for row in rows:
        year = dt.datetime.fromtimestamp(int(row[0]) / 1000, dt.timezone.utc).year
        parts.setdefault(f"{SYMBOL}_{tf}_{year}.csv.gz", []).append(row)
    for name, part in parts.items():
        write_gz(name, KLINE_HEADER, part)
    return parts


def download_funding(today):
    header, by_time = ["calc_time", "funding_interval_hours", "last_funding_rate"], {}
    for m in months(KLINE_START, today):
        res = fetch_zip_rows(f"{BASE}/monthly/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{m:%Y-%m}.zip")
        if res:
            header = res[0] or header
            for row in res[1]:
                by_time[int(row[0])] = row
    rows = [by_time[k] for k in sorted(by_time)]
    write_gz(f"{SYMBOL}_fundingRate.csv.gz", header, rows)
    return rows


def download_metrics(today):
    header, rows = None, []
    for d in days(METRICS_START, today):
        res = fetch_zip_rows(f"{BASE}/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-{d:%Y-%m-%d}.zip")
        if res:
            header = header or res[0]
            rows.extend(res[1])
        if d.day == 1:
            print(f"  metrics {d:%Y-%m} ... {len(rows)}행")
    write_gz(f"{SYMBOL}_metrics.csv.gz", header or ["create_time"], rows)
    return rows


def span(rows, col=0):
    if not rows:
        return None
    first, last = rows[0][col], rows[-1][col]
    if first.isdigit():
        conv = lambda v: dt.datetime.fromtimestamp(int(v) / 1000, dt.timezone.utc).isoformat()
        return [conv(first), conv(last)]
    return [first, last]


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    manifest = {"symbol": SYMBOL, "source": BASE, "downloaded_at": dt.datetime.now(dt.timezone.utc).isoformat(), "files": {}}
    jobs = [(tf, KLINE_START, False) for tf in TIMEFRAMES] + [("1m", MINUTE_START, True)]
    for tf, start, split in jobs:
        print(f"캔들 {tf} 받는 중...")
        for name, rows in download_klines(tf, today, start, split).items():
            manifest["files"][name] = {"rows": len(rows), "span_utc": span(rows)}
    print("펀딩비 받는 중...")
    rows = download_funding(today)
    manifest["files"][f"{SYMBOL}_fundingRate.csv.gz"] = {"rows": len(rows), "span_utc": span(rows)}
    print("미결제약정·롱숏비 받는 중 (하루 단위라 시간이 걸림)...")
    rows = download_metrics(today)
    manifest["files"][f"{SYMBOL}_metrics.csv.gz"] = {"rows": len(rows), "span": span(rows)}
    manifest["failed"] = failed
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"\n완료. 실패 {len(failed)}건. 결과: {OUT}")


if __name__ == "__main__":
    main()
