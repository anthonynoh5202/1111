# Pre-registration (written 2026-11-07, BEFORE any strategy result was computed)

Only data-quality metadata (manifest.json / quality_report.json, file heads) had been looked at.

## Data / timing
- Binance USDT-M BTCUSDT perpetual klines (last price) 1d/4h/1h, 2020-01-01 .. 2026-09-28.
- Funding: actual history to 2026-08-31 16:00 UTC; afterwards 0.01% per 8h (assumption).
- Signal uses bar t data only (close_t, highs/lows up to t). Order fills at open of bar t+1.
- Bar P&L is open-to-open (last bar: open-to-close).
- Funding event at time tau is paid/received by the position held at tau
  (bar interval (open_i, open_i + len], right end inclusive). Amount = -w * rate * P_tau/open_i, P_tau = 1h open at tau.
- Rebalance rule (all strategies): trade to target if sign changes, target = 0, current = 0,
  or |target - drifted weight| > 10% of |target|. Otherwise let the weight drift.

## Costs (per side, on traded notional)
- BASE: 0.07% (taker 0.05% + slippage 0.02%)
- MAKER: 0.02% (maker fee, no slippage; optimistic)
- STRESS: 0.10% (taker 0.05% + slippage 0.05%)

## Evaluation windows
- IS: 2020-07-20 .. 2023-12-31 (2020-01..07 is warm-up for 200-day indicators; all variants & benchmarks start the same day)
- OOS: 2024-01-01 .. 2026-09-28
- Walk-forward: at the start of each year 2022..2026, rank all 21 variants by expanding-window net Sharpe
  (from 2020-07-20), hold top-1 (and separately equal-weight top-3) for that year.

## Benchmarks (not counted as variants)
- BH-SPOT: buy & hold, no funding (spot-equivalent).  BH-PERP: 1x long perpetual with funding.

## Variants (21)
A. Time-series momentum (daily): s = sign(C_t / C_{t-L} - 1)
  A1 TSMOM7-LS, A2 TSMOM30-LS, A3 TSMOM90-LS, A4 TSMOM30-LO (long/flat), A5 TSMOM90-LO
B. Moving-average trend (daily, SMA of closes incl. today)
  B1 SMA50-LO, B2 SMA100-LO, B3 SMA200-LO, B4 SMA100-LS, B5 X50/200-LO (SMA50 > SMA200)
C. Donchian breakout (daily, close-based): entry when C_t > max(H over prior N days) (short: C_t < min(L prior N));
   exit when C_t < min(L prior M) (short: > max(H prior M)) or close breaches stop = fill -/+ 2*ATR20(signal day).
  C1 DON20/10-LS, C2 DON55/20-LO, C3 DON55/20-LS
D. Vol-targeted (daily): m_t = min(0.30 / sigma30_t, 2.0), sigma30 = stdev of last 30 daily log returns * sqrt(365)
  D1 VT-BH (always long * m), D2 VT-TSMOM30-LS (A2 * m), D3 VT-SMA100-LO (B2 * m)
E. Short-term reversal (intraday, 1x notional): z = bar return / stdev(previous returns)
  E1 REV4h-LS: 4h bars, stdev of prior 180 bars, |z| >= 2.5 -> fade for 6 bars (24h); new signal resets/overrides
  E2 REV4h-LO: same, long side only (buy after big drops; up-move signals ignored)
  E3 REV1h-LS: 1h bars, stdev of prior 720 bars, |z| >= 3.0 -> fade for 12 bars
F. Equal-risk trend combinations (daily)
  F1 COMBO-LO: m_t * mean(A4, A5, B2, C2)
  F2 COMBO-LS: m_t * mean(A2, A3, B4, C3)

Target-vol levels 20%/40% are treated as sizing (leverage) choices, not separate variants.

## Statistics
- Sharpe: daily returns, rf = 0, annualised x sqrt(365). CAGR on 365.25-day years.
- Bootstrap: circular block bootstrap, block 20 days, 5,000 resamples, fixed seed.
- Beat-B&H test: paired bootstrap of OOS Sharpe difference vs BH-SPOT and BH-PERP;
  family-wise p-value of the best variant via max-statistic (White Reality Check style, centred);
  Deflated Sharpe (Bailey & Lopez de Prado) with N = 21 and an effective N; CSCV PBO with 16 blocks.

## Sizing / liquidation
- Sizing candidates: F1 COMBO-LO (chosen a priori), + the variant with the highest min(IS Sharpe, OOS Sharpe)
  (data-driven; selection bias noted), + VT-BH / BH-PERP as reference.
- Leverage L in {0.5, 1, 1.5, 2, 3}; Kelly from mean log growth; block-bootstrap paths (1y and 3y, 10,000 paths).
- Liquidation: isolated margin, MMR 0.5% (assumption), last-price 1h extremes (conservative vs mark price):
  (a) daily re-margined, (b) set-and-forget per trade (adverse excursion from entry).

## Capital tiers
- Assumptions: min notional 50 USDT, qty step 0.001 BTC, USDT/KRW = 1,400, tiers 100만 / 1,000만 / 1억 KRW.
