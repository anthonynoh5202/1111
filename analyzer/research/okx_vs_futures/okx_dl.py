"""OKX BTC-USDT-SWAP 4시간봉 과거 자료를 받는다(공개 API, 키 없음)."""
import sys, json, time, urllib.request, csv
out = sys.argv[1]; start_ms = 1577836800000  # 2020-01-01
rows = {}; after = None; n = 0
while True:
    url = "https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT-SWAP&bar=4H&limit=100" + (f"&after={after}" if after else "")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research/1.0"}), timeout=30) as r: j = json.load(r)
            break
        except Exception as e:
            time.sleep(2 + attempt * 2); j = None
    if not j or j.get("code") != "0": print("멈춤", j and j.get("msg")); break
    d = j["data"]
    if not d: break
    for x in d: rows[int(x[0])] = x
    after = min(int(x[0]) for x in d); n += 1
    if after <= start_ms: break
    time.sleep(0.12)
with open(out, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["open_time", "open", "high", "low", "close", "vol_contracts", "vol_btc", "vol_quote", "confirm"])
    for t in sorted(rows): w.writerow(rows[t])
ts = sorted(rows); print("요청", n, "봉", len(ts), time.strftime("%Y-%m-%d", time.gmtime(ts[0] / 1000)), "~", time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts[-1] / 1000)))
