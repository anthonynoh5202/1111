Assumptions: 1 USDT = 1,400 KRW; BTC = 83,461 USDT; perp qty step 0.001 BTC; min notional 50 USDT (unverified).

## S1. Position size actually placeable per capital tier

| capital (KRW) | USDT | L | target notional | perp qty (rounded down to 0.001) | placed notional | capital utilisation vs target | 1 step as % of position |
|---|---|---|---|---|---|---|---|
| 1,000,000 | 714 | 1x | 357 | 0.004 | 334 | 93% | 25.0% |
| 1,000,000 | 714 | 2x | 476 | 0.005 | 417 | 88% | 20.0% |
| 10,000,000 | 7,143 | 1x | 3,571 | 0.042 | 3,505 | 98% | 2.4% |
| 10,000,000 | 7,143 | 2x | 4,762 | 0.057 | 4,757 | 100% | 1.8% |
| 100,000,000 | 71,429 | 1x | 35,714 | 0.427 | 35,638 | 100% | 0.2% |
| 100,000,000 | 71,429 | 2x | 47,619 | 0.570 | 47,573 | 100% | 0.2% |

## S2. Monthly income in KRW (pre-tax; scales with placed notional)

| scenario | 100만 1x | 100만 2x | 1,000만 1x | 1,000만 2x | 1억 1x | 1억 2x |
|---|---|---|---|---|---|---|
| full 2020-01..2026-08 CAGR | 4,931 | 5,945 | 51,774 | 67,767 | 526,371 | 677,674 |
| best year 2021 (fresh entry) | 13,297 | 16,336 | 139,619 | 186,236 | 1,419,455 | 1,862,355 |
| 2024 (fresh entry) | 5,250 | 6,061 | 55,128 | 69,099 | 560,465 | 690,994 |
| 2025 (fresh entry) | 2,103 | 2,344 | 22,084 | 26,724 | 224,518 | 267,240 |
| last 24m annualised | 1,916 | 2,395 | 20,121 | 27,307 | 204,561 | 273,068 |
| last 12m (2025-09..2026-08) | 1,036 | 1,358 | 10,878 | 15,485 | 110,596 | 154,849 |
| 2026 YTD annualised | 810 | 964 | 8,506 | 10,989 | 86,481 | 109,893 |

## S3. Minimum capital

- 1x: smallest hedge 0.001 BTC = 83 USDT notional -> capital 167 USDT (~23만 원) + ~5-10 USDT of BNB for fees. Practical minimum so one 0.001 step is <=5% of the position (0.02 BTC): 3,338 USDT (~467만 원).
- 2x: smallest hedge 0.001 BTC = 83 USDT notional -> capital 125 USDT (~18만 원) + ~5-10 USDT of BNB for fees. Practical minimum so one 0.001 step is <=5% of the position (0.02 BTC): 2,504 USDT (~351만 원).
- 3x: smallest hedge 0.001 BTC = 83 USDT notional -> capital 111 USDT (~16만 원) + ~5-10 USDT of BNB for fees. Practical minimum so one 0.001 step is <=5% of the position (0.02 BTC): 2,226 USDT (~312만 원).
- If the old 100 USDT min notional still applied, the smallest perp order would be 0.002 BTC (167 USDT): minimums double.

## S4. Fixed transfer costs vs income (illustrative; fees are ASSUMPTIONS)

- 1,000,000 KRW: round-trip fixed cost ~2.7 USDT (0.38% of capital) = 2.5 months of last-12m income at 2x; a 1%p kimchi-premium swing = 7 USDT = 6.5 months of income.
- 10,000,000 KRW: round-trip fixed cost ~9.1 USDT (0.13% of capital) = 0.8 months of last-12m income at 2x; a 1%p kimchi-premium swing = 71 USDT = 6.5 months of income.
- 100,000,000 KRW: round-trip fixed cost ~73.4 USDT (0.10% of capital) = 0.7 months of last-12m income at 2x; a 1%p kimchi-premium swing = 714 USDT = 6.5 months of income.
