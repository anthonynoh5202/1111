## A. Worst rallies / drops from any hourly close (2020-01-01 .. 2026-09-28)

| window | worst rally (mark proxy) | start (close) | p99 | p95 | worst rally (raw high) | start | worst drop (mark proxy) | start |
|---|---|---|---|---|---|---|---|---|
| 1h | +26.5% | 2020-03-13 01:00 | +2.1% | +1.1% | +31.1% | 2021-07-26 00:00 | -21.2% | 2020-03-12 22:00 |
| 4h | +31.6% | 2020-03-13 01:00 | +4.5% | +2.4% | +39.6% | 2021-07-25 21:00 | -35.1% | 2020-03-12 22:00 |
| 8h | +38.8% | 2020-03-13 01:00 | +6.4% | +3.5% | +40.4% | 2021-07-25 19:00 | -37.7% | 2020-03-12 19:00 |
| 24h | +46.4% | 2020-03-13 01:00 | +10.8% | +6.3% | +47.0% | 2020-03-13 01:00 | -50.9% | 2020-03-12 03:00 |
| 3d | +46.4% | 2020-03-13 01:00 | +19.5% | +11.5% | +50.0% | 2021-07-23 18:00 | -53.8% | 2020-03-10 12:00 |
| 7d | +57.0% | 2020-03-13 01:00 | +28.6% | +19.1% | +63.8% | 2021-07-20 09:00 | -58.9% | 2020-03-06 10:00 |
| 30d | +138.3% | 2020-12-11 11:00 | +78.8% | +46.1% | +138.7% | 2020-12-11 11:00 | -64.1% | 2020-02-13 06:00 |
| 90d | +273.9% | 2020-10-12 11:00 | +223.5% | +99.5% | +274.6% | 2020-10-12 11:00 | -64.1% | 2020-02-13 06:00 |
| 180d | +505.1% | 2020-09-23 20:00 | +470.9% | +287.3% | +505.9% | 2020-09-23 20:00 | -66.0% | 2021-12-27 17:00 |
| 365d | +1338.8% | 2020-03-13 01:00 | +838.4% | +590.4% | +1339.2% | 2020-03-13 01:00 | -77.3% | 2021-11-10 17:00 |

## B. Liquidation distance of an isolated short at entry (no rebalancing, mmr 0.5%)

| leverage | margin / notional | notional / total capital (spot fully paid) | rally to liquidation |
|---|---|---|---|
| 1x | 100% | 50.0% | +99.0% |
| 2x | 50% | 66.7% | +49.3% |
| 3x | 33% | 75.0% | +32.7% |
| 5x | 20% | 83.3% | +19.4% |

## C. Share of entry times whose un-rebalanced short would have been liquidated within the window (mark proxy)

| leverage | 1d | 7d | 30d | 90d | 180d | 365d |
|---|---|---|---|---|---|---|
| 1x | 0.0% | 0.0% | 0.3% | 5.0% | 16.3% | 45.4% |
| 2x | 0.0% | 0.0% | 3.8% | 22.6% | 42.0% | 65.5% |
| 3x | 0.0% | 0.4% | 11.6% | 37.2% | 54.0% | 73.7% |
| 5x | 0.1% | 4.8% | 27.0% | 51.9% | 66.9% | 83.3% |

## D. Time until liquidation without any rebalancing (start at every daily 00:00 UTC close)

| leverage | starts | liquidated eventually | median days to liq. (if liq.) | fastest | share liq. within 90d | within 365d | example fastest start |
|---|---|---|---|---|---|---|---|
| 1x | 2463 | 65% | 323 | 22.67d | 5% | 39% | 2020-12-15 |
| 2x | 2463 | 73% | 169 | 9.46d | 22% | 56% | 2020-12-29 |
| 3x | 2463 | 79% | 101 | 3.38d | 37% | 66% | 2020-03-16 |
| 5x | 2463 | 86% | 61 | 0.58d | 52% | 77% | 2020-03-12 |

## E. Margin buffer needed to survive the worst observed rally between two checks

Required liquidation distance d >= worst rally R over the reaction window. Since P_liq/P = (1+mr)/(1+mmr),
the margin ratio (margin equity / notional) must never fall below mr_min = (1+R)(1+mmr) - 1 at a check time.

| reaction window | worst rally (mark proxy) | mr_min | max effective leverage at a check | worst rally (raw high) | mr_min (raw) |
|---|---|---|---|---|---|
| 1h | +26.5% | 27.1% | 3.69x | +31.1% | 31.8% |
| 4h | +31.6% | 32.3% | 3.10x | +39.6% | 40.3% |
| 8h | +38.8% | 39.5% | 2.53x | +40.4% | 41.1% |
| 24h | +46.4% | 47.1% | 2.12x | +47.0% | 47.7% |
| 3d | +46.4% | 47.1% | 2.12x | +50.0% | 50.8% |

Same, excluding starts in 2020-03 (to show how much the COVID crash/rebound drives it):

- 1h: worst rally +12.7% (start 2021-01-29 07:00) -> mr_min 13.2% (max eff. lev 7.56x)
- 4h: worst rally +17.5% (start 2021-01-29 07:00) -> mr_min 18.1% (max eff. lev 5.53x)
- 8h: worst rally +19.1% (start 2021-01-29 07:00) -> mr_min 19.7% (max eff. lev 5.08x)
- 24h: worst rally +23.9% (start 2021-02-08 03:00) -> mr_min 24.5% (max eff. lev 4.07x)
- 3d: worst rally +32.6% (start 2021-01-05 05:00) -> mr_min 33.2% (max eff. lev 3.01x)
