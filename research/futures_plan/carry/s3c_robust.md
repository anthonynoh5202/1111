## R1. Daily manual check at hour X (UTC), ALWAYS, band 0.5/2.0 — liquidations across the 24 possible check hours

| L | liq price | check hours with >=1 liquidation | worst CAGR | best CAGR | worst max DD | dates of liquidations (first few) |
|---|---|---|---|---|---|---|
| 1x | mark | 0/24 [] | 6.28% | 6.56% | -1.1% |  |
| 1x | raw | 0/24 [] | 6.28% | 6.56% | -1.1% |  |
| 2x | mark | 0/24 [] | 8.05% | 8.36% | -1.4% |  |
| 2x | raw | 14/24 [3, 6, 7, 8, 9, 10, 11, 12] | 4.38% | 8.36% | -21.6% | 2021-07-26 |
| 3x | mark | 1/24 [2] | 9.01% | 9.35% | -11.3% | 2020-03-13 |
| 3x | raw | 21/24 [2, 3, 4, 5, 6, 7, 8, 9] | 5.31% | 9.35% | -21.4% | 2020-03-13, 2021-07-26 |

Same for a bot (hourly checks) with the tighter band 0.8/1.5 and the pre-declared 0.5/2.0:

| L | band | liq price | liquidations | CAGR | max DD | rebalances |
|---|---|---|---|---|---|---|
| 2x | 0.5/2.0 | mark | 0 | 8.14% | -1.3% | 46 |
| 2x | 0.5/2.0 | raw | 0 | 8.14% | -1.3% | 46 |
| 2x | 0.8/1.5 | mark | 0 | 7.69% | -1.3% | 189 |
| 2x | 0.8/1.5 | raw | 0 | 7.69% | -1.3% | 189 |
| 3x | 0.5/2.0 | mark | 0 | 8.97% | -1.5% | 84 |
| 3x | 0.5/2.0 | raw | 1 | 6.17% | -16.3% | 78 |
| 3x | 0.8/1.5 | mark | 0 | 8.58% | -1.5% | 327 |
| 3x | 0.8/1.5 | raw | 1 | 5.23% | -19.2% | 326 |

## R2. Idle-cash yield sensitivity (L=2 bot, base costs): CAGR full period / last-24m APR

| variant | idle 0% | idle 3% | idle 4% | time in market |
|---|---|---|---|---|
| ALWAYS | 8.14% / 3.41% | 8.14% / 3.41% | 8.14% / 3.41% | 100% |
| GATE10 | 5.35% / 0.52% | 7.61% / 3.35% | 8.37% / 4.31% | 29% |
| GATE10_HYST | 6.30% / 1.43% | 8.20% / 3.80% | 8.84% / 4.61% | 41% |
| FLAT_NEG | 7.15% / 2.32% | 7.47% / 2.75% | 7.57% / 2.89% | 90% |
| FLIP_NEG | 5.94% / 0.86% | 5.94% / 0.86% | 5.94% / 0.86% | 100% |
| DYN | 5.70% / 0.64% | 7.19% / 2.59% | 7.69% / 3.25% | 79% |
(FLIP_NEG: idle yield only applied while not short spot.)

## R3. Fresh entry on Jan 1 and full exit on Dec 31 each year (ALWAYS, bot, base costs) — return on total capital

| year | 1x | 2x | 3x |
|---|---|---|---|
| 2020 | 9.54% | 12.02% | 13.18% |
| 2021 | 17.07% | 22.37% | 24.76% |
| 2022 | 1.86% | 2.35% | 2.62% |
| 2023 | 3.89% | 5.01% | 5.68% |
| 2024 | 6.74% | 8.30% | 8.89% |
| 2025 | 2.70% | 3.21% | 3.55% |
| 2026 | 0.69% (8m) | 0.88% (8m) | 0.95% (8m) |

## R4. Start-now style windows (ALWAYS, bot, base costs, incl. entry+exit)

| window | 1x | 2x | 3x |
|---|---|---|---|
| last 24m (2024-09..2026-08), annualised | 2.46% | 3.28% | 3.66% |
| last 12m (2025-09..2026-08) | 1.33% | 1.86% | 2.02% |
| 2026 YTD (8 months), annualised | 1.04% | 1.32% | 1.43% |

## R5. Liquidation event detail (raw last-price stress, ALWAYS 3x bot)

- 2021-07-26 02:00:00+00:00: equity 1.3436 -> 1.1288 (-16.0% of total capital in that hour); margin lost 0.0067
