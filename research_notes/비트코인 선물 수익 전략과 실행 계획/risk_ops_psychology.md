# Risk management, operations and behavioral discipline for an individual trading leveraged BTC/USDT perpetuals (리스크 관리·운영·심리) — notes as of 2026-11-07

> Method note: direct page fetches to binance.com and ftmo.com were blocked by this session's network policy, so Binance, FTMO and Topstep facts come from search-engine extracts of those pages plus third-party summaries. Re-check any number marked "verify" on the official page before relying on it. Numbers marked **own calc** are my arithmetic or Monte Carlo results (Python, standard formulas); they are inferences, not sourced facts.

## 1. Position sizing: fixed-fractional risk, volatility targeting, Kelly / fractional Kelly for an asset as volatile as BTC

### Takeaway
Practitioners converge on two equivalent framings. One is per trade: risk about 1% of equity per trade (Turtles: 1N = 1% of equity, with a 2N stop, so about 2% at risk; Elder: never more than 2%). The other is annual: a volatility target of no more than half-Kelly, which Carver puts at about 12–25% annual volatility for individuals. With BTC's 2025–26 realized volatility of roughly 35–60%, half-Kelly economic leverage (notional ÷ equity) for a realistic Sharpe ratio of 0.3–1.0 is only about 0.25x–1.4x. That is far below the 20–125x the exchange offers.

### Cited Findings
- **Carver (Systematic Trading, 2015):** the Kelly-optimal risk target (annualized volatility) equals the strategy's Sharpe ratio (SR). Carver advises half-Kelly. Example: an expected pre-cost SR of 0.75 implies a 75% Kelly volatility target, so 37% at half-Kelly. In another example a backtested SR of 1.0 is first cut to 0.75 "for prudence" — [7 Circles summary, "Volatility Targeting and Position Sizing"](https://the7circles.uk/?p=24214); [CXO Advisory notes on Systematic Trading](https://www.cxoadvisory.com/big-ideas/a-few-notes-on-systematic-trading)
- **Carver's own targets:** his personal target was once 25% ("relatively low appetite for risk"). His stated maximum for a "semi-automatic trader" is 25%. A low-SR asset-allocation portfolio was run at 7.5%. Negative-skew strategies should run at half the risk of benign ones, because their backtested SRs flatter them — [7 Circles, Systematic Trading 6 – Practice](https://the7circles.uk/?p=24323); [7 Circles, Systematic Trading 4](https://the7circles.uk/?p=24214)
- **Carver:** "the absolute max. Sharpe we should expect is 1.0, regardless of how good the backtest is" — [7 Circles, Systematic Trading 2 – Fitting](https://the7circles.uk/?p=29002); [CXO Advisory](https://www.cxoadvisory.com/big-ideas/a-few-notes-on-systematic-trading)
- **Carver, Leveraged Trading (2019), "Starter System":** risk target of 12% annual standard deviation. The stop-loss fraction is 0.5 of annual instrument volatility, so capital at risk per trade = 12% × 0.5 = 6%. The starter system's assumed SR is 0.24, and 12% is justified as below the Kelly optimum. The same summary notes that per-trade risk settings of 1–5% are common among retail traders, with about 2% the most popular — [7 Circles, Leveraged Trading 3 – The Starter System](https://the7circles.uk/?p=27861). A community implementation sizes notional exposure as risk target × capital ÷ instrument risk, citing p.99 of the book — [QuantConnect backtest page](https://www.quantconnect.com/terminal/cache/embedded_backtest_8375db950b6c237460ab18e37fae0b61.html)
- **Turtle rules (1980s):** N = 20-day ATR. One unit is sized so that a 1N move equals 1% of equity. The initial stop is 2N, so about 2% of equity is at risk per unit if the stop fills without a gap. Units are added every 0.5N in favor, up to 4 units. All stops move to 2N from the newest entry. A forum worked example shows that pyramided risk can stack to about 5N — [FXOpen](https://fxopen.com/blog/en/turtle-trading-system-rules-and-strategy); [7 Circles, The Turtle Traders](https://the7circles.uk/?p=22159); [BabyPips forum](https://forums.babypips.com/t/turtle-traders-info/77748)
- **Elder's 2% / 6% rules** (Come Into My Trading Room, 2002; The New Trading for a Living, 2014): risk at most 2% of equity on any trade. Stop opening new trades for the rest of the month once monthly losses plus open-trade risk reach 6% of equity (measured from prior month-end). Commentators call these teaching heuristics with no published success rate — [Incredible Charts, 2% rule](https://www.incrediblecharts.com/trading/2_percent_rule.php); [Incredible Charts, 6% rule](https://www.incrediblecharts.com/trading/6_percent_rule.php); [Complete Trader's Edge](https://completetradersedge.com/van-tharp-vs-alexander-elder-position-sizing/)
- **Kelly math:** the continuous Kelly fraction is f* ≈ (μ − r)/σ². Leveraged growth is G(L) ≈ r + L(μ − r) − ½L²σ², which peaks at the Kelly leverage. Half-Kelly gives up about 25% of maximum growth but cuts drawdowns sharply. Estimation error can push a trader past the peak onto the losing side. Kelly ignores parameter uncertainty, correlated positions and fat tails, all of which push the true optimum lower — [LuxAlgo Kelly concept page](https://www.luxalgo.com/library/concept/kelly-criterion.md); [Philipp Dubach, "Variance Tax"](https://philippdubach.com/posts/variance-tax/); [BSIC, Kelly to drawdown control](https://bsic.it/bet-sizing-from-the-kelly-criterion-to-drawdown-control/)
- **Ralph Vince** (The Leverage Space Trading Model, Wiley 2009) argues that geometric returns matter more than arithmetic ones and that a trader should maximize the probability of being profitable, not expected profit. He distinguishes "optimal f" (a fraction of the worst loss) from Kelly — [Wiley](https://www.wiley-vch.de/en/areas-interest/finance-economics-law/the-leverage-space-trading-model-978-0-470-45595-1); [KTH master's thesis on optimal f](https://www.math.kth.se/matstat/seminarier/reports/M-exjobb12/121105.pdf)
- **BTC volatility in 2025–26:** one tracker says 30-day annualized realized volatility ranged about 23–45% across 2025–26, against historical averages above 80%. Month-end 30-day realized volatility in 2026 was: Jan 42.2%, Feb 73.2%, Mar 49.4%, Apr 35.3%, May 21.3%, Jun 42.5% — [StealthEX](https://stealthex.io/blog/bitcoin-volatility/); [Spark volatility tracker](https://www.spark.money/tools/bitcoin-volatility-tracker); [Crypto Briefing (2026)](https://cryptobriefing.com/bitcoin-extreme-price-swings-2026-vs-2018/)
- **Volatility targeting on BTC:** a Man Institute analysis using the Harvey et al. (2018) method found that volatility-scaling bitcoin raised the Sharpe ratio by roughly 0.4 ("40 Sharpe points") whatever the estimation speed. This is practitioner research, not peer-reviewed, and the gain looks large — [Man Institute, "Crypto: too hot to handle?"](https://www.man.com/insights/crypto-too-hot-to-handle). Multi-coin volatility-managed backtests claim even bigger gains but are low-quality blog evidence — [Coinmonks/Medium](https://medium.com/coinmonks/whats-vol-got-to-do-with-it-886b57c2d762)

### Inferences
- **own calc — Kelly leverage for BTC** (continuous approximation, Kelly leverage L* = SR/σ):

  | annual vol σ | SR 0.3 (full / half) | SR 0.5 | SR 0.75 | SR 1.0 |
  |---|---|---|---|---|
  | 35% | 0.86x / 0.43x | 1.43x / 0.71x | 2.14x / 1.07x | 2.86x / 1.43x |
  | 45% | 0.67x / 0.33x | 1.11x / 0.56x | 1.67x / 0.83x | 2.22x / 1.11x |
  | 60% | 0.50x / 0.25x | 0.83x / 0.42x | 1.25x / 0.62x | 1.67x / 0.83x |

  Using Carver's cap of SR ≈ 1.0, economic leverage above about 2–3x on a BTC-only strategy is beyond full Kelly in every 2025–26 volatility regime.
- **own calc — cost of over-betting:** at a fraction k of Kelly, long-run growth relative to the maximum is 2k − k². Half-Kelly gives 75% of the maximum growth, 1.5x Kelly also gives 75% but with three times the variance, 2x Kelly gives zero growth, and 2.5x Kelly is negative. Because the true SR is uncertain, a "half-Kelly by my estimate" bet can really be full Kelly or more. This is the quantitative reason practitioners go even lower.
- **own calc — per-trade Kelly vs common practice:** for a system with a 40% win rate and +2R wins (expectancy +0.2R), per-trade Kelly is f* = p − q/b = 0.40 − 0.60/2 = 10% risk per trade. The common 1% rule is therefore about one-tenth Kelly. Section 3's Monte Carlo shows why: at 5% (half-Kelly) the median maximum drawdown over 200 trades is about 50%.
- **own calc — the two framings link up:** annual volatility from fixed-fractional risk ≈ r × sd(R per trade) × √(trades per year). With sd ≈ 1.47R (the example above): 0.5% risk at 100 trades/yr ≈ 7.4% annual vol; 1% at 50 trades ≈ 10.4%; 1% at 100 ≈ 14.7%; 1% at 200 ≈ 20.8%; 2% at 100 ≈ 29%. So "1% per trade" means a 10–20% annual volatility target for a typical trade frequency, consistent with Carver's 12–25%. Carver's 6% per trade only makes sense because his starter system trades rarely.
- **own calc — worked sizing example:** $10,000 account, 1% risk ($100), BTC ATR 3%, stop at 2×ATR (6%). Position notional = $100 ÷ 6% = $1,667, which is economic leverage of only 0.17x. Even 2% risk only reaches about 0.33x. **The exchange's leverage slider is not the economic leverage.** It only decides how much margin is posted (see Section 2).
- **Volatility targeting fits BTC especially well:** 30-day realized volatility moved from 21% to 73% within H1 2026 (StealthEX data above). A fixed-notional position therefore had about a 3.4x swing in risk. Scaling notional ∝ target vol ÷ forecast vol, for example using an EWMA of daily returns, keeps the dollar risk roughly constant.
- **Suggested starting parameters** for a beginner running a rule-based bot (synthesis): 0.5% risk per trade for the first live stage, rising to at most 1%. Economic leverage of 1x or less, typically 0.1–0.5x. Portfolio volatility target of 10–20%. No pyramiding until the stacked risk is coded and tested.

### Gaps
- Carver's books were not read directly; his numbers come from secondary summaries (7 Circles, CXO Advisory). The stop-loss fraction of 0.5 appears only in one summary's worked example.
- Ernest Chan's own Kelly/leverage guidance (his books recommend half-Kelly, from memory) was searched but not found in results, so generic Kelly sources were used instead. Ralph Vince's quantitative over-betting statements were not found; the standard Kelly growth curve was used.
- No primary prop-firm rulebook stating a per-trade risk norm (e.g., 0.5–1%) was found. Van Tharp's primary material was not retrieved.

## 2. Leverage and liquidation mechanics on Binance USDⓈ-M (isolated/cross, mark price, maintenance tiers, liquidation fees, ADL); lessons of 10–11 Oct 2025; choosing leverage so the stop fires before liquidation

### Takeaway
On Binance, liquidation (강제청산) is triggered by the **mark price**, not the last price, when margin balance falls to the tiered maintenance margin. The smallest BTCUSDT tier had a 0.40% maintenance margin rate in the Dec 2023 table. When liquidated, the trader loses the margin plus a clearance fee. The insurance fund absorbs bankrupt accounts, and beyond that, auto-deleveraging (ADL, 자동감축) closes profitable opponents in order of PnL% × effective leverage.

The 10–11 Oct 2025 crash ($19B+ liquidated industry-wide, the largest single-day event on record) showed four things:
- stops can fail to fill when liquidity vanishes;
- non-USDT collateral can be marked down on the exchange's own order book (USDe/wBETH/BNSOL on Binance);
- ADL can close winning or hedged positions;
- exchanges' own accounts of what happened are contested.

Practical rule (own calc): use isolated margin with a leverage setting that puts liquidation at least about 3x further away than the stop and beyond a plausible 15–20% BTC gap. For ATR-based stops, that means a leverage setting of 2–5x.

### Cited Findings
- **Mark price:** Binance uses the mark price "to avoid unnecessary liquidations and to combat market manipulation". If an account goes bankrupt (negative balance), the Futures Insurance Fund takes over the position at the bankruptcy price, which can be worse than the liquidation price in volatile markets, and brings the account back to zero. ADL triggers for positions beyond what the insurance fund can cover — [Binance Futures Liquidation Protocols FAQ](https://www.binance.com/en-AE/support/faq/360033525271); [Binance Portfolio Margin Pro liquidation FAQ](https://www.binance.com/en/support/faq/ff4b1ab6c27b4ed6b3ebe8e4ed1572f8)
- **Clearance fee:** when a position is liquidated, part of its margin goes to Binance as a "Liquidation Clearance" fee (unless the position is bankrupt), based on notional × fee rate. Binance's fee FAQ gives "Insurance Clearance Fee = Notional Value × Fee Rate" — [Binance fees FAQ](https://www.binance.com/en/support/faq/detail/98488a516eb84e3eb34605683dffd554); [Binance Liquidation Protocols](https://www.binance.com/en-AE/support/faq/360033525271). Another Binance text says the fee is charged on the amount liquidated, not the full notional, so the two conflict (verify).
- **Clearance fee rates:** a third-party gitbook lists 2% for BTCUSDT, 3% for ETHUSDT and 75x contracts, and 4% for 50x-max contracts. This is not Binance's own page and may be outdated (verify on Binance's Trading Rules) — [Finandy gitbook](https://finandy.gitbook.io/exchange/finandy/futures-info/liquidation)
- **Maintenance margin formula:** maintenance margin = notional × maintenance margin rate (MMR) − maintenance amount. Binance's worked example: 10 BTCUSDT contracts at mark 26,000 (notional 260,000) in tier 3 → 260,000 × 1% − 1,300 = 1,300 USDT. In isolated mode, the "wallet balance" in the liquidation-price formula is that position's isolated margin, and the other-position terms are zero — [Binance Leverage & Margin FAQ](https://www.binance.com/th/support/faq/360033162192); [Binance liquidation-price FAQ (au)](https://www.binance.com/au/support/faq/b3c689c1f50a44cabb3a84e663b81d93); [same FAQ (sl, with example)](https://www.binance.com/sl/support/faq/b3c689c1f50a44cabb3a84e663b81d93)
- **Tiers:** a Binance announcement (effective 2023-12-24) listed the BTCUSDT 101–125x band at 0.40% MMR for notional up to 50,000 USDT. Tiers were revised again in 2025, and the current table was not retrieved (verify in the BTCUSDT "Leverage & Margin" panel) — [Binance tier announcement (2023)](https://www.binance.com/es/support/announcement/detail/d75c5ca94f704e96a6a4e55ffddfd65d); [Binance 2025 tier/collateral update](https://www.binance.com/en/support/announcement/detail/8e428625ebeb4cc7ae8678026846095c)
- **Simplified isolated-long liquidation price** ≈ Entry × [1 − (1/Leverage − MMR)], ignoring fees and tier amounts. Example: a $20,000 entry at 10x with 0.5% MMR liquidates near $18,100 — [Binance Square post](https://www.binance.com/ar/square/post/351608975983634); [Traders Union](https://tradersunion.com/brokers/crypto/view/binance/liquidation/)
- **ADL ranking (official FAQ):**
  - PnL% = unrealized profit ÷ |position notional|
  - effective leverage = |notional| ÷ (wallet balance + unrealized profit)
  - ranking = PnL% × effective leverage if profitable; PnL% ÷ effective leverage if losing

  [Binance ADL FAQ (de)](https://www.binance.com/de/support/faq/360033525471); [Binance ADL FAQ (hu)](https://www.binance.com/hu/support/faq/360033525471). A third-party guide notes that 10x leverage with 80% unrealized profit scores the same as 20x with 40% — [Leverage.Trading](https://leverage.trading/what-is-auto-deleveraging-adl/)
- **Scale of 10–11 Oct 2025:** more than $19B of leveraged positions were liquidated in under 24 hours across more than 1.6M accounts (CoinGlass data). The trigger was President Trump's post threatening 100% tariffs on Chinese imports from 1 November — [Cointelegraph](https://cointelegraph.com/news/19b-crypto-market-crash-leverage-china-tariffs)
- **BTC's move:** BTC fell roughly 10–17% intraday, from highs near $124–126k to lows of about $101.5–105k depending on venue. Some altcoin pairs on Binance briefly printed −99.99%. SOL and DOGE fell more than 30% and 50% at points — [CoinGecko explainer](https://www.coingecko.com/learn/october-10-crypto-crash-explained); [CryptoSlate](https://cryptoslate.com/weekend-crypto-black-friday-liquidation-cascade-what-actually-happened/?rand=6792); [Cointelegraph, altcoins "to zero" on Binance](https://cointelegraph.com/markets/why-did-some-altcoins-on-binance-crash-to-zero)
- **Binance collateral depeg:** Binance acknowledged depegs on its own venue of USDe, BNSOL and wBETH. Positions using these as collateral were liquidated. Binance paid about $283M within 24 hours to affected Margin, Futures and Loan users — [Decrypt (Oct 2025)](https://decrypt.co/344026/binance-reimburses-283m-after-market-crash-and-asset-depegging-issues). A later "Together Initiative" reportedly raised total direct compensation to about $583M — [Bloomberg Law](https://news.bloomberglaw.com/financial-accounting/binance-raises-compensation-for-customers-liquidated-in-selloff)
- **How Binance priced collateral:** Binance reportedly valued such collateral against its own order book rather than external oracles. Its insurance fund reportedly spent about $188M, falling from $1.23B to $1.04B. Analyst YQ blamed Binance's unified-margin pricing. Haseeb Qureshi countered that USDe never truly depegged, since Curve, where its deepest liquidity sat, moved less than 0.3% — [ForkLog](https://forklog.com/en/whales-adl-and-the-end-of-the-bull-what-really-happened-on-cryptos-black-saturday/)
- **Binance's own analysis** (as summarized by altFINS) says about 75% of the $19.25B industry-wide liquidations happened before any localized technical issues. This is contested — [altFINS summary](https://altfins.com/crypto-news/crypto-news-summary/192626)
- **ADL in practice:** some of the best-hedged shorts had positions reduced or closed entirely. From an exchange's view, ADL is preferable to default or socialized losses. Market depth is a nonlinear variable that collapses in crises — [FTI Consulting (2025)](https://www.fticonsulting.com/insights/articles/crypto-crash-october-2025-leverage-met-liquidity). Binance, Bybit and Hyperliquid reportedly triggered ADL for tens of thousands of accounts. One claim of a 98% collapse in market-maker liquidity is uncorroborated — [Coinpedia via TradingView](https://www.tradingview.com/news/coinpedia:a9beb70ce094b:0-19-billion-crypto-crash-shows-market-makers-can-also-break-the-market/)
- **Stops in a free-fall:** stop-loss orders "may not work" when there is no one to sell to after market makers leave. Stop-outs can in turn trigger ADL that forces exits from profitable shorts — [Seward & Kissel, "Gone in 60 seconds"](https://skrypto.sewkis.com/insights/gone-in-60-seconds/)
- **Hyperliquid:** its first cross-margin ADL in more than two years of operation; the founder claims no bad debt — [Wu Blockchain substack](https://wublock.substack.com/p/hyperliquid-activates-cross-margin). About 34,983 ADL executions across 19,337 wallets were reported (secondary, unverified) — [Datawallet](https://www.datawallet.com/it/crypto/october-10-crypto-crash-explained). A formal analysis of ADL design appeared afterwards; one summary attributes to it an estimate of $660M (simulated) to $2.1B (realized) of winners' PnL ADL'd on Hyperliquid (verify) — [arXiv 2512.01112, "Autodeleveraging: Impossibilities and Optimization"](https://arxiv.org/pdf/2512.01112)
- **Earlier precedent, 19 May 2021:** during a crash Binance Futures had failures (about 12:40–13:10 UTC) and users could not exit positions for up to about an hour. Compensation offers were reportedly 10–30% of losses, with NDAs. More than 700 claimants pursued arbitration, with losses estimated at over $100M — [CNBC (Aug 2021)](https://www.cnbc.com/amp/2021/08/19/cryptocurrency-traders-seek-damages-from-binance-after-major-outage.html); [Crypto Briefing](https://cryptobriefing.com/crypto-traders-to-sue-binance-for-millions-after-may-outage/); [Forkast](https://forkast.news/binance-users-burned-by-outage-unite-legal-action/)

### Inferences
- **own calc — distance to liquidation, isolated mode, tier-1 MMR 0.4%, fees ignored.** Long: P_liq = E(1 − 1/L)/(1 − MMR). Short: P_liq = E(1 + 1/L)/(1 + MMR).

  | leverage | 2x | 3x | 5x | 10x | 20x | 50x | 100x | 125x |
  |---|---|---|---|---|---|---|---|---|
  | adverse move to liquidation | 49.8% | 33.1% | 19.7% | 9.6% | 4.6% | 1.6% | 0.6% | 0.4% |
- **own calc — compare with BTC's volatility:** at 45% annual volatility, the daily standard deviation is about 2.36%, so a 3-sd day is about 7.1% and a 5-sd day about 11.8%. A 20x position is liquidated by roughly a 2-sd daily move. On 10 Oct 2025 (a 10–17% intraday drop), any long opened near the high with a leverage setting above about 6–8x was liquidated if its stop did not fill.
- **Rule for choosing the leverage setting** (synthesis):
  1. Size the position from risk (Section 1).
  2. Pick the isolated leverage so that liquidation distance ≥ 3x the stop distance and ≥ about 15–20%.
  3. The isolated margin then becomes a hard "second stop", the most you can lose if the exchange stop fails.

  Using the Section 1 example ($1,667 notional, 6% stop):

  | isolated setting | margin posted | liquidation distance |
  |---|---|---|
  | 3x | $556 (5.6% of account) | 33% (5.5x the stop distance) |
  | 5x | $333 (3.3%) | 19.7% (3.3x) |
  | 10x | $167 | 9.6% (only 1.6x the stop, too close) |
- **Cross vs isolated (교차/격리):** cross margin pushes liquidation far away for small positions, but a failed stop can drain the whole futures wallet. Oct 2025 also showed that multi-asset/unified collateral can be marked down by the venue itself. For a single-strategy bot: isolated margin, USDT-only collateral (single-asset mode), and only the bot's capital in the futures wallet (or a dedicated sub-account).
- **Trigger-price mismatch:** liquidation uses the mark price, but stop orders trigger on the contract (last) price by default (Section 5). A wick on the last price can fire a stop that mark-price logic would not, and vice versa. With `priceProtect=TRUE`, a stop may refuse to trigger exactly when mark and last prices diverge most, which is in a crash. Decide deliberately: for example, `workingType=MARK_PRICE` with priceProtect off for the protective stop, plus isolated margin as the backstop.
- **ADL exposure:** the ADL queue is ranked by PnL% × effective leverage, so a large, highly levered winner is first in line. Low effective leverage and periodically taking profits both reduce priority. A hedge that depends on a perp leg (spot long + perp short, or offsetting perps across venues) can be broken by ADL right when it is needed.
- **Funding can erode isolated margin:** funding paid out of isolated margin over long holds would move the liquidation price closer (verify how Binance debits funding in isolated mode). Monitor liquidation distance continuously, not only at entry.
- Liquidation is the most expensive exit: it costs the entire isolated margin plus the clearance fee, versus a planned 1R stop. A bot should treat "position exists without a resting exchange-side stop" as a critical alarm.

### Gaps
- The current (2025–26) BTCUSDT tier table, the current clearance fee rate, and whether funding is debited from isolated margin could not be verified, because the binance.com fetch was blocked.
- Binance's own Oct 2025 post-mortem text was not retrieved directly; the 75% figure comes via altFINS. The number of Binance accounts ADL'd on 10 Oct 2025 was not found.
- The exact BTC low on Binance's BTCUSDT perpetual on 10–11 Oct 2025 was not found; sources give $101.5k–$105k across venues.

## 3. Risk of ruin and drawdown math; daily/weekly loss limits and prop-firm circuit breakers; ATR-based stop placement

### Takeaway
Drawdowns are asymmetric: a −50% loss needs +100% to recover. A positive-expectancy system risking 2% per trade will very likely see a 20% or deeper drawdown within 200 trades (own Monte Carlo: about 69%, versus about 7% at 1% risk). Prop firms enforce hard circuit breakers:
- **FTMO:** 5% maximum daily loss and 10% maximum loss.
- **Topstep 50K account:** about $1,000 daily (2%) and $2,000 trailing maximum (4%).
- **Elder:** 2% per trade and 6% per month.

ATR-based stops, such as the Turtles' 2×ATR(20), tie stop distance to current volatility, and position size then follows from the risk budget.

### Cited Findings
- **FTMO (2-Step):** profit targets 10% then 5%, maximum daily loss 5%, maximum loss 10%; breaching either fails the account. Sources conflict on whether the daily limit is based on the initial balance (FTMO wording as quoted) or the previous day's balance. The 1-Step variant is reported as 3% daily with a trailing 10% maximum, also conflicting — [Prop-firm rules summary (2026)](https://propfirm-escape-pod.pages.dev/blog/ftmo-evaluation-rules-2026); [Traders Second Brain](https://traderssecondbrain.com/prop-firm-rules/daily-loss-vs-max-loss); [FTMO/OANDA](https://ftmo.oanda.com/how-to-pass-ftmo-challenge/)
- **Topstep (CME futures prop firm):** the 50K account's maximum loss limit starts $2,000 below the starting balance ($48,000) and trails. Topstep's help center says it uses real-time unrealized P&L; others say end-of-day. Daily loss limits are $1,000/$2,000/$3,000 for 50K/100K/150K, and a breach deactivates the account for that day. Reportedly, TopstepX accounts created or reset after 25 Aug 2024 have no daily loss limit. Consistency rule: best day under about 50% of profits (some say 55%). Profit targets: $3,000/$6,000/$9,000 — [Topstep help center](https://intercom.help/topstep-llc/en/articles/8284197); [Topstep help center 2](https://intercom.help/topstep-llc/en/articles/8284204); [TradersPost](https://blog.traderspost.io/article/how-to-get-funded-with-topstep); [rules summary](https://propfirm-escape-pod.pages.dev/blog/topstep-evaluation-rules-decoded)
- **Elder's 6% monthly rule** halts new trades for the rest of the month; trading resumes at month turnover — [Incredible Charts](https://www.incrediblecharts.com/trading/6_percent_rule.php)
- **Turtles:** stop at 2N (2× the 20-day ATR), with 1N = 1% of equity per unit — [FXOpen](https://fxopen.com/blog/en/turtle-trading-system-rules-and-strategy)
- **Carver's starter system** uses a trailing stop at a fraction (0.5) of annual price volatility — [7 Circles](https://the7circles.uk/?p=27861)
- **Loss-chasing is real among professional futures traders:** CBOT traders with morning losses were about 15–16% more likely to take above-average afternoon risk (Coval & Shumway, JF 2005; see Section 4). This is the empirical case for a daily stop — [IDEAS/RePEc](https://ideas.repec.org/a/bla/jfinan/v60y2005i1p1-34.html)

### Inferences
- **own calc — loss needed to be recovered:** −10% → +11%; −20% → +25%; −30% → +43%; −50% → +100%; −75% → +300%; −90% → +900%.
- **own calc — Monte Carlo** (20,000 paths × 200 trades; 40% win rate, +2R / −1R, so expectancy +0.2R; fixed-fractional compounding):

  | risk per trade | P(max drawdown ≥ 20%) | P(≥ 30%) | P(≥ 50%) | median max drawdown | 95th-percentile max drawdown | 5th-percentile ending equity |
  |---|---|---|---|---|---|---|
  | 0.5% | 0% | 0% | 0% | 5.9% | 11.0% | 1.03x |
  | 1% | 6.7% | 0.3% | 0% | 11.7% | 20.9% | 1.05x |
  | 2% | 68.9% | 19.2% | 0.5% | 23.0% | 38.8% | 1.06x |
  | 5% (≈ half-Kelly) | 100% | 98.6% | 49.8% | 49.8% | 73.4% | 0.87x |
  | 10% (= full Kelly) | 100% | 100% | 99.3% | 79.0% | 95.2% | 0.29x |

  Even with a genuine edge, risk above about 2% per trade makes deep drawdowns near-certain. Real edges are also smaller and less certain than this example.
- **own calc — losing streaks** (probability of at least one run of k losses in 200 trades):

  | loss rate | ≥ 6 in a row | ≥ 8 | ≥ 10 | ≥ 12 |
  |---|---|---|---|---|
  | 50% | 80% | 32% | 9% | — |
  | 60% (typical trend-follower) | 98.5% | 75% | 38% | 15% |
  | 65% | — | 91% | 62% | 32% |

  A trend-following bot should expect a run of 8–10 losses and be pre-approved, psychologically and in code, to survive it.
- **own calc — ATR for BTC:** under a random-walk approximation, expected daily range ≈ 1.6 × daily standard deviation (E[range] = σ√(8/π)). At 35%/45%/60% annual volatility, daily ATR is about 2.9%/3.8%/5.0% of price. A 2–3×ATR daily-bar stop is therefore about 6–15% away. That is consistent with a leverage setting of 2–5x and inconsistent with 20x or more.
- **Suggested circuit breakers for an individual bot** (synthesis of prop-firm practice; all enforced in code, not by willpower):
  - per-trade risk: 0.5–1%
  - daily loss stop: 2–3% (2–3 full losses); flatten and stop until the next UTC day
  - weekly: 4–6%
  - monthly: 6–8% (Elder-style); stop and do a written review
  - hard kill switch: 15–20% from the equity peak. Stop live trading entirely and re-validate the strategy (FTMO's 10% maximum loss is the professional benchmark).

  Also cap the number of trades per day, to stop overtrading from bugs or noise.

### Gaps
- The FTMO and Topstep official rule pages were not fetched (FTMO blocked), and third-party summaries disagree on calculation details.
- No study was found showing that daily loss limits improve individual traders' long-run outcomes. The support is prop-firm practice plus the loss-chasing evidence.

## 4. Evidence on retail failure modes: overtrading, revenge trading, high leverage, push notifications, disposition effect; studies of retail futures/crypto traders

### Takeaway
Large-sample evidence is consistent:
- Most retail day and futures traders lose. In Brazil, 97% of persistent mini-index futures day traders lost money. In Taiwan, fewer than 1% of day traders are predictably profitable. In the EU, 74–89% of retail CFD accounts lose.
- Specific behaviors are linked, some causally, to worse outcomes: overtrading, loss-chasing (revenge trading), high leverage, attention triggers such as push notifications, and the disposition effect.
- Regulatory leverage caps reduced losses: by about 40% for the most aggressive US retail forex traders.
- In crypto perpetuals, forced exits (liquidations) and fees are a main channel transferring wealth away from retail.

### Cited Findings
- **Futures day traders, Brazil** (Chague, De-Losso & Giovannetti, 2019/2020): 19,646 people who first day-traded mini-Ibovespa futures in 2013–15. Only 1,551 (7.9%) persisted for more than 300 sessions; 97% of those lost money, only 1.1% earned more than the minimum wage, and 0.4–0.5% more than a bank teller's starting salary — [EconPapers](https://econpapers.repec.org/RePEc:spa:wpaper:2019wpecon47); [CXO Advisory](https://www.cxoadvisory.com/investing-expertise/day-trading-a-bust/)
- **Day traders, Taiwan** (Barber, Lee, Liu & Odean, J. Financial Markets 2014; data 1992–2006): fewer than 1% of day traders predictably earn positive abnormal returns net of fees. Day traders' average daily returns were −11.5 bps before fees and −28.9 bps after (as reported) — [Berkeley working paper](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/Day%20Trading%20Skill%20110523.pdf); [IDEAS](https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html)
- **Overtrading** (Barber & Odean, "Trading Is Hazardous to Your Wealth", JF 2000): 66,465 households, 1991–96. The most active traders earned 11.4% a year net, against 17.9% for the market. Turnover above 250% a year; attributed to overconfidence — [Odean's page](https://faculty.haas.berkeley.edu/odean/papers/returns/Returns.html); [Berkeley PDF](https://faculty.haas.berkeley.edu/odean/Papers%20current%20versions/Individual_Investor_Performance_Final.pdf)
- **Disposition effect** (Odean, JF 1998): 10,000 accounts. Proportion of gains realized was 14.8% versus 9.8% for losses, so gains were realized about 1.5x as readily. The pattern reverses in December for tax reasons — [Wikipedia summary](https://en.wikipedia.org/wiki/Disposition_effect); [CFA Digest](https://rpc.cfainstitute.org/research/cfa-digest/1999/05/are-investors-reluctant-to-realize-their-losses-digest-summary)
- **Revenge trading / loss-chasing** (Coval & Shumway, JF 2005): 1,082 CBOT T-bond futures traders, more than 5M trades in 1998. After morning losses they were about 15–16% more likely to take above-average afternoon risk. They also bought at higher and sold at lower prices than prevailing levels, and those price moves reversed — [IDEAS](https://ideas.repec.org/a/bla/jfinan/v60y2005i1p1-34.html); [CFA Digest](https://rpc.cfainstitute.org/research/cfa-digest/2005/11/do-behavioral-biases-affect-prices-digest-summary); [BYU repository](https://scholarsarchive.byu.edu/facpub/9284)
- **Push notifications** (Arnold, Pelster & Subrahmanyam, "Attention Triggers and Investors' Risk-Taking", JFE 2022): broker notifications containing only public information (past returns) raised leverage, trading intensity and short selling. One summary puts attention trades at about 19 percentage points more leverage. Effects were stronger for younger, male, less-experienced investors and after losses. Identification is difference-in-differences, plus a triple-difference against the broker timing notifications — [EconPapers (JFE)](https://econpapers.repec.org/RePEc:eee:jfinec:v:143:y:2022:i:2:p:846-875); [Univ. St. Gallen press release](https://www.unisg.ch/en/newsdetail/news/trading-apps-lead-to-risky-investment-behaviour/); [SUFE summary](https://academicnewsletter.sufe.edu.cn/info/354839)
- **App-driven herding** (Barber, Huang, Odean & Schwarz, Robinhood, 2020/2022): stocks most bought on Robinhood had −3% average 5-day abnormal returns, and −6% for the most extreme herding (gross of costs). The app's "Top Movers" list concentrated attention. During outages, trading fell most in high-attention stocks — [SSRN copy](https://www.smallake.kr/wp-content/uploads/2020/12/SSRN-id3715077.pdf); [UC Davis](https://gsm.ucdavis.edu/news/what-effect-brokerage-robinhood-having-stock-market); [Evidence Investor](https://www.evidenceinvestor.com/why-most-robinhood-traders-earn-lousy-returns/)
- **Leverage caps** (Heimer & Simsek, JFE 2019): the CFTC's 2010 cap of 50:1 on major currency pairs (20:1 on others) gave smaller losses for the most aggressive US retail forex traders, about 40% smaller per the VoxEU summary, without harming liquidity — [IDEAS](https://ideas.repec.org/a/eee/jfinec/v132y2019i3p1-21.html); [VoxEU/CEPR](https://cepr.org/voxeu/columns/retail-investor-leverage-and-speculation); [NBER w24176](https://www.nber.org/papers/w24176)
- **EU regulators** (ESMA 2018): national analyses showed 74–89% of retail CFD accounts lose money, with average losses of €1,600–€29,000 per client. Crypto CFDs were capped at 2:1 leverage. In Feb 2026 ESMA told firms that crypto perpetual futures may fall under the CFD measures — [ESMA notice](https://www.esma.europa.eu/sites/default/files/library/esma35-43-1135_notice_of_pi_decisions_on_cfds_and_binary_options.pdf); [Latham & Watkins](https://www.latham.london/2018/03/first-use-of-esma-temporary-product-intervention-measures/); [Finance Magnates (2026)](https://www.financemagnates.com/forex/regulation/esma-tells-firms-perpetual-futures-fall-under-eu-cfd-rules/)
- **BIS:** the median retail crypto investor (exchange-app users in 95 countries) lost money from Aug 2015 to end-2022. Bitcoin price rises drive app downloads — this is the "buy after rallies" pattern — [Investment Executive](https://www.investmentexecutive.com/news/markets/most-retail-investors-lose-on-bitcoin-trades-bis/); [Digital Money Box](https://digitalmoneybox.com/news/research/most-retail-crypto-investors-lost-money-over-the-last-7-years-according-to-bis-analysis)
- **Crypto perpetuals, academic:**
  - BitMEX data: liquidated longs averaged about 58x leverage and liquidated shorts about 60x; daily liquidation rates were about 3.5% (longs) and 1.9% (shorts) — [arXiv 2102.04591](https://arxiv.org/pdf/2102.04591)
  - Hyperliquid on-chain data, Mar–Jun 2025 (Jia, Moallemi, Wang & Zeng, AFT 2026): manual front-end (mostly retail) traders lose mainly through immediacy costs, forced exits and fees — [Dagstuhl LIPIcs](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2026.36)
  - A CEX/DEX comparison (Binance, Bybit, GMX and others) finds uninformed traders overreact when liquidation risk rises — [arXiv 2402.03953](https://arxiv.org/pdf/2402.03953)
- **Emotion and performance** (Lo, Repin & Steenbarger, AER 2005): 80 day-trading trainees. Those with more intense emotional reactions to both gains and losses performed significantly worse. No "trader personality" profile emerged, suggesting the skill can be trained. Small sample — [MIT](https://web.mit.edu/Alo/www/Papers/online.html); [NBER/EconPapers](https://econpapers.repec.org/RePEc:nbr:nberwo:11243); [CXO Advisory](https://www.cxoadvisory.com/animal-spirits/the-animal-spirits-of-day-trading/)

### Inferences
- Crypto perpetuals combine every documented risk factor at once: 24/7 markets, leverage up to 125x, app push alerts and "top gainers" lists, a liquidation engine, and stablecoin-collateral quirks. The base rate for a new retail trader is therefore worse than the equity-market base rates above.
- **Mapping failure modes to controls** (synthesis):
  - overtrading → a code-level cap on trades per day, plus cost and funding accounting in every report;
  - loss-chasing → a daily loss stop and cool-off, so the bot cannot be restarted the same day;
  - leverage → economic leverage of 1x or less and an isolated-margin cap;
  - attention triggers → turn off exchange app notifications and price alerts, and don't browse leaderboards or copy-trading pages;
  - disposition effect → exchange-side stops placed at entry and never widened (Section 7).
- The Brazil and Taiwan results concern discretionary day traders. A slow, rule-based system with low turnover avoids the main cost channels (fees and immediacy costs) and the main behavioral channels. It still has to prove its edge (Section 6).

### Gaps
- No peer-reviewed study with exchange-level retail P&L for Binance perpetuals was found.
- Korean-specific data on retail derivatives or crypto-futures losses was not searched in depth.
- Barber & Odean's "Boys Will Be Boys" (overconfidence by gender) and Barber et al. 2011 (over 80% of Taiwanese day traders lose) were not verified from primary sources.

## 5. Manual vs automated trading; operational risks (bugs, API outages, maintenance); API-key and account security

### Takeaway
Automation removes some behavioral errors: pre-committed automatic stops causally reduce the disposition effect. But it adds software and infrastructure risk. Knight Capital lost about $440–460M in 45 minutes from a bad deployment with no kill switch.

For a Binance bot, the minimum controls are:
- exchange-side protective stops (since about Dec 2025 these go through the Algo Order API);
- careful use of the dead-man switch (`countdownCancelAll`);
- handling of the 60-minute listenKey and the 24-hour WebSocket cut-off;
- an independent watchdog that alerts you;
- a futures-only API key with IP restriction and withdrawals disabled, on a dedicated sub-account.

For the account itself: passkey or authenticator-app 2FA (not SMS), an anti-phishing code, a withdrawal address whitelist, and a hardened email account.

For a Korean resident there is an added risk that app or web access to an unregistered offshore exchange gets cut off.

### Cited Findings
- **Automatic exits help behavior** (Fischbacher, Hoffmann & Schudy, RFS 2017, lab experiment): giving traders automatic stop-loss and take-gain orders significantly reduced the disposition effect, because they realized more losses. A mere reminder of the selling plan did not — [EconPapers (RFS)](https://econpapers.repec.org/RePEc:oup:rfinst:v:30:y:2017:i:6:p:2110-2129.); [TWI working paper](https://www.twi-kreuzlingen.ch/wp-content/uploads/2017/12/twi-rps-089-fischbacher-hoffmann-schudy.pdf)
- **Knight Capital (1 Aug 2012):** a router running repurposed, discontinued code sent over 4M orders while trying to fill 212 small retail orders. It traded more than 397M shares, for a loss of over $460M (SEC) or about $440M pre-tax (Knight). The system sent 97 automated error emails before the open that went unheeded. There was no second-technician code review and no control to halt the system. The SEC imposed a $12M penalty under the Market Access Rule in Oct 2013 — [J.R. Varma on the SEC order](https://www.jrvarma.in/blog/Y2013/Knight-Capital.html); [Mondaq](https://webiis06.mondaq.com/unitedstates/credit-control-and-cashflow/270572/knight-capital-settles-rule-15c3-5-violations-with-sec-agrees-to-pay-12-million)
- **Exchange outage risk:** see the Binance 19 May 2021 futures outage (users unable to exit for up to about an hour) in Section 2 — [CNBC](https://www.cnbc.com/amp/2021/08/19/cryptocurrency-traders-seek-damages-from-binance-after-major-outage.html)
- **Dead-man switch:** `POST /fapi/v1/countdownCancelAll` (symbol plus countdown in ms) cancels all open orders when the countdown expires. Binance suggests a heartbeat every 30 s with a 120,000 ms countdown; a countdown of 0 stops the timer — [Binance API docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Auto-Cancel-All-Open-Orders). The COIN-M version was paused on 2026-06-29 for a migration, per the changelog — [Binance changelog](https://developers.binance.com/docs/zh-CN/derivatives/change-log)
- **Stop-order parameters:** `workingType` is MARK_PRICE or CONTRACT_PRICE, default CONTRACT_PRICE. `priceProtect` (default FALSE) blocks the trigger if the mark/contract divergence exceeds the symbol's `triggerProtect` — [Binance New Order docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/websocket-api/New-Order)
- **Algo Order migration:** USDⓈ-M conditional orders (STOP_MARKET, TAKE_PROFIT_MARKET, STOP, TAKE_PROFIT, TRAILING_STOP_MARKET) moved to `POST /fapi/v1/algoOrder` (algoType=CONDITIONAL, `triggerPrice`), effective 2025-12-02 or 2025-12-09 depending on the source. Sending STOP_MARKET to the old order endpoint fails with error −4120 — [Binance New Algo Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order); [binance SDK PR #604](https://github.com/sieblyio/binance/pull/604); [Nautilus Trader issue #3287](https://github.com/nautechsystems/nautilus_trader/issues/3287)
- **Streams:** a futures listenKey is valid for 60 minutes; a PUT keepalive extends it, and error −1125 means create a new one. A single WebSocket connection is valid for only 24 hours, so expect a disconnect and reconnect on schedule — [Binance user data streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Connect); [Binance user data streams overview](https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams)
- **API-key policy:**
  - Binance used to cut trading permissions on keys without IP restriction after 90 days ([QuantConnect forum, 2021](https://www.quantconnect.com/forum/discussion/12734/binance-demands-ips-for-api-connection-after-90-days/)). One later post says the rule is no longer enforced ([TradersPost](https://blog.traderspost.io/article/managing-binance-api-key-expiry-on-traderspost)). A Binance email quoted by users said inactive unrestricted trading keys are deleted after about 30 days ([CoinTracker feedback thread](https://feedback.cointracker.io/features/p/binance-api-key-whitelisting)). Verify the current policy.
  - Ed25519 keys and IP restriction are supported, including for sub-account keys ([Binance sub-account API docs](https://developers.binance.com/docs/sub_account/api-management/Get-IP-Restriction-for-a-Sub-account-API-Key)).
- **Third-party bot platforms are an attack surface (3Commas):**
  - 28 Dec 2022: users' API keys, secrets and passphrases were posted publicly. Reportedly 10,000 keys from a database of about 100,000 were published. Binance's CEO advised disabling any keys used with 3Commas — [The Block](https://www.theblock.co/news/ecosystems/2022-12-28-binance-warns-about-3commas-api-leak-says-users-should-disable-keys-198295); [Cointelegraph](https://cointelegraph.com/news/3commas-ceo-confirms-api-key-leak-following-warning-from-cz); [TechRadar](https://techradar.com/news/crypto-platform-3commas-confirms-major-api-breach-fbi-to-investigate)
  - Earlier, in Oct 2022, 3Commas-linked keys were used for unauthorized trades in DMG pairs on FTX. Attackers used trading permission alone to move value through an illiquid market — [The Block](https://www.theblock.co/news/regulation/2022-10-23-ftx-api-keys-3commas-exploited-179237)
  - One report claims about $6M was stolen through leaked keys (unverified) — [TechRadar](https://techradar.com/news/crypto-platform-3commas-confirms-major-api-breach-fbi-to-investigate)
- **Account security** (Binance guidance):
  - Use 2FA through a passkey or authenticator app rather than SMS — [Binance Account Security Tips](https://www.binance.com/en/support/faq/360000106932). Guides warn SMS can be intercepted through SIM-swap.
  - Passkeys resist phishing because login is tied to a device or hardware key — [Binance Square, passkeys](https://www.binance.com/fr-AF/square/hashtag/passkeys)
  - The anti-phishing code appears in genuine Binance emails.
  - With the withdrawal whitelist on, adding any new address needs email confirmation, so email security becomes a dependency.
  - Binance staff never ask for passwords, 2FA codes or seed phrases.

  Sources: [Binance Account Security Tips](https://www.binance.com/en/support/faq/360000106932); [Binance Square post](https://www.binance.com/en/square/post/1006134)
- **Korean access and regulatory risk:**
  - Exchanges serving Korean residents must register with the FIU; offshore exchanges struggle to qualify. In 2021 Binance limited its Korea-facing services — [Cointelegraph](https://cointelegraph.com/news/google-play-crypto-app-rules-south-korea-exchanges-risk); [CoinDesk](https://www.coindesk.com/binance-discontinues-south-korean-won-trading-pairs-payment-options); [KED Global (2021)](https://www.kedglobal.com/newsView/ked202108170005)
  - Google reportedly planned to block the Binance and OKX apps from Korea's Play Store from 28 January (whether this took effect is unconfirmed) — [Cryptonews](https://cryptonews.com/news/google-play-to-block-binance-okx-from-korea-starting-jan-28/)
  - Binance's route back to Korea runs through its GOPAX stake; the FIU resumed its review in Oct 2025 — [The Block](https://www.theblock.co/post/374486/binance-south-korea-gopax-review); [The Cryptonomist (Jan 2026)](https://en.cryptonomist.ch/2026/01/30/binance-south-korea-restitution/)

### Inferences
- **Manual vs automated:** in a 24/7 market a manual discretionary trader is exposed to every failure mode in Section 4: fatigue, alerts and loss-chasing. The evidence (Fischbacher et al.; Lo et al.) favors automating at least exits, sizing and circuit breakers. Keep the human role to approving configuration changes and reviewing results. This matches the repo's current design: paper mode, LIVE mode refused by the config validator.
- **Defense in depth for a Binance USDⓈ-M bot** (synthesis):
  1. Place the exchange-side protective stop (Algo Order API, reduce-only/closePosition) immediately after the entry fills. Alarm if a position exists without a resting stop.
  2. Isolated margin sized as the worst-case loss if the stop fails (Section 2).
  3. Choose deliberately between `workingType=MARK_PRICE` and last price, and decide whether priceProtect could block your stop in a crash.
  4. **Verify before using `countdownCancelAll` as a dead-man switch.** It cancels all open orders on the symbol. If it also cancels algo-service stops, a crashed bot would leave the position unprotected. Use it only for resting entry orders, or pair it with a separate flatten routine.
  5. An independent watchdog on a separate host or process. It compares exchange positions and orders against expected state and alerts by Telegram. Always rebuild state from the exchange, never from local memory, after any restart or reconnect.
  6. Handle 24-hour WebSocket drops, listenKey keepalive and rate limits. Use idempotent client order IDs so retries never double-submit.
  7. **Change management (the Knight lesson):** tests, then testnet, then a minimum-size canary before any new version handles real size. Keep one-command global halt and flatten. Never leave alert emails or log messages unread.
- **Trade-only keys are not harmless:** the FTX/3Commas DMG case shows trading permission alone can be used to drain value through illiquid pairs. Use:
  - an IP whitelist (mandatory);
  - a dedicated sub-account holding only the bot's capital;
  - futures permission only, withdrawals and transfers disabled;
  - a separate read-only key for dashboards and monitoring;
  - no third-party bot platforms holding keys;
  - keys read from a file with 600 permissions or an OS keyring, never committed or logged (the repo's gitleaks CI enforces this);
  - immediate rotation on any suspicion.
- **Account hardening** (security professional's checklist): hardware security key or passkey for Binance and for the email account; anti-phishing code; withdrawal whitelist; a separate email address used only for the exchange; a password manager; no SMS fallback where avoidable.
- **Korean resident:** loss of app or web access is an operational tail risk. It is one more reason the protective stop must always rest on the exchange rather than depend on the bot or UI being reachable. Whether trading on an unregistered offshore exchange is legally allowed is a legal question outside these notes and must be confirmed separately. Do not plan around circumventing blocks.

### Gaps
- Not verified: whether `countdownCancelAll` cancels Algo-service conditional orders, a critical design question to test on testnet. Also unverified: Binance's current API-key expiry and IP policy, and whether USDⓈ-M countdownCancelAll is affected by the 2026 migration.
- Official Binance security pages could not be fetched (blocked); details come from search extracts and Binance Square posts.
- One search extract claimed that on 13 Oct 2026 the FIU ordered web blocks on 27 unregistered offshore exchanges and that Binance, Bybit and OKX are not FIU-registered. The source was unclear and the claim is unconfirmed. Check the FIU's registered-VASP list.

## 6. Evaluating a strategy before scaling capital: forward-test length, statistical significance, minimum trades, staged capital, kill criteria

### Takeaway
The statistics are sobering:
- A Sharpe 0.5 strategy needs about 10–16 years of data before it is distinguishable from zero at about 2 sigma.
- A per-trade edge of +0.2R needs about 200–500 trades for a t-statistic of 2–3.
- When many variants have been tried, the hurdle should be t ≥ 3 (Harvey, Liu & Zhu), Sharpe ratios should be deflated or haircut, and fat tails lengthen the required record (minimum track record length).

Practitioners "incubate" strategies live without real money for 3–12 months (Kevin Davey). Forward tests catch bugs and gross backtest/live mismatch, but cannot quickly prove an edge. So capital should scale in predefined stages with written kill rules.

### Cited Findings
- **Minimum Track Record Length (MinTRL)** (Bailey & López de Prado, Journal of Risk, "The Sharpe Ratio Efficient Frontier"): the minimum number of return observations needed to be confident, at a chosen level, that the true Sharpe ratio exceeds a benchmark. Negative skew and fat tails lengthen it. It is counted in observations, not calendar time, and uses non-annualized SR. Implemented in R PerformanceAnalytics `MinTrackRecord`, which warns that kurtosis estimates need long samples — [IDEAS (J. Risk)](https://ideas.repec.org/a/rsk/journ4/2223785.html); [PerformanceAnalytics docs](https://rdrr.io/cran/PerformanceAnalytics/man/MinTrackRecord.html); [Portfolio Optimizer blog](https://portfoliooptimizer.io/blog/the-probabilistic-sharpe-ratio-bias-adjustment-confidence-intervals-hypothesis-testing-and-minimum-track-record-length/). It has been applied to auditing an autonomous FX strategy — [arXiv 2101.07217](https://arxiv.org/pdf/2101.07217)
- **Multiple-testing hurdle** (Harvey, Liu & Zhu, RFS 2016): a new factor should clear a t-ratio above about 3.0 rather than 2.0; many published findings are likely false — [IDEAS (RFS)](https://ideas.repec.org/a/oup/rfinst/v29y2016i1p5-68..html); [NBER w20592](https://nber.org/papers/w20592)
- **Harvey & Liu, "Evaluating Trading Strategies":** when many strategies have been tried, Sharpe ratios and other statistics are overstated and must be adjusted for multiple tests — [Duke PDF](https://people.duke.edu/~charvey/Research/Published_Papers/P116_Evaluating_trading_strategies.pdf)
- **Carver:** an SR-0.5 rule takes about 10 years before the lower 2-sigma band clears zero. Two uncorrelated rules with SRs of 0.05 and 0.30 would need 45 years to tell apart — [7 Circles, Systematic Trading 2](https://the7circles.uk/?p=29002); [Thread Reader quote](https://threadreaderapp.com/thread/1234306875379683328.html)
- **Rule of thumb:** t ≈ annual SR × √years, so SR 0.5 needs about 16 years for t = 2. This conflicts with Carver's "about 10 years", probably because of a different method, but both say a decade or more — [LuxAlgo](https://www.luxalgo.com/library/concept/significance-of-returns.md)
- **Kevin Davey's incubation:** after walk-forward and Monte Carlo testing, strategies are run live without real money for 6–12 months ([IBKR Campus / Algo Advantage ep. 036](https://www.interactivebrokers.com/campus/ibkr-quant-news/algo-advantage-036-kevin-davey-part-i-its-all-about-process-in-algo-trading/)). Other summaries say 6–9 months ([Algo Advantage ep. 037](https://algoadvantage.substack.com/p/037-kevin-davey-ii-selecting-optimal)) or 3–6 months ([Financial Wisdom TV](https://www.financialwisdomtv.com/post/building-winning-algorithmic-trading-systems-kevin-davey-s-complete-framework-for-trading-success)). Only systems that look the same live as in testing are promoted.

### Inferences
- **own calc — trades needed** (t = mean ÷ sd × √n, per-trade outcomes in R):

  | system | expectancy | sd | trades for t = 2 | trades for t = 3 |
  |---|---|---|---|---|
  | 40% win, 2R payoff | +0.20R | 1.47R | 216 | 486 |
  | 50% win, 1.5R | +0.25R | 1.25R | 100 | 225 |
  | 55% win, 1R | +0.10R | 0.99R | 396 | 891 |
  | 35% win, 3R | +0.40R | 1.91R | 91 | 205 |

  A swing system making about 50–100 trades a year therefore needs 2–10 years of live trades to confirm its edge statistically. Forward testing mainly verifies mechanics and costs.
- **own calc — years needed by Sharpe ratio:**

  | annual SR | years for t = 2 | years for t = 3 |
  |---|---|---|
  | 0.5 | 16 | 36 |
  | 1.0 | 4 | 9 |
  | 1.5 | 1.8 | 4 |
  | 2.0 | 1.0 | 2.2 |

  A live SR far above 1–1.5 over a few months is more likely luck or regime than skill.
- **Suggested staged plan** (synthesis):
  - **Stage 0 — backtest:** include fees, funding, slippage and liquidation logic; out-of-sample period; record every variant tried (the repo's TRIALS.md does this) so the Sharpe can be deflated for the real number of trials.
  - **Stage 1 — testnet / paper:** at least 1–3 months, or until every code path (entry, stop, reconnect, restart, partial fill, rejection) has fired. This is about bugs, not edge.
  - **Stage 2 — live micro:** minimum size or no more than about 5–10% of planned capital, for at least 3–6 months or 50–100 trades. Compare live against backtest: slippage per trade, fees and funding, win rate and average R within confidence bands.
  - **Stage 3 — scale in steps** (for example 25% → 50% → 100%), each only after the prior stage meets its written criteria.
  - **Kill or pause rules, fixed in advance:**
    - drawdown beyond the 95th–99th percentile of the backtest/Monte-Carlo drawdown distribution;
    - live per-trade expectancy more than 2 standard errors below backtest after N trades;
    - any operational incident (position without a stop, wrong size, duplicate orders): halt, write a post-mortem, fix, and return to Stage 1;
    - an absolute account kill line (for example 15–20% from peak).
- Changing the rules after a drawdown is a new trial, which must be re-versioned and counted (consistent with the repo rule that strategy specs are frozen).

### Gaps
- No authoritative source was found for common heuristics such as "kill when live drawdown exceeds 1.5–2x the backtest maximum drawdown". The percentile-based rule above is my synthesis.
- Ernest Chan's paper-trading guidance and FTMO's minimum-trading-days rule were not retrieved.
- Davey's primary text (book or podcast) was not accessed, and the sources disagree on incubation length.

## 7. Journaling and review processes (prop-firm practice); psychology tools with measurable effects

### Takeaway
The hard evidence favors structural tools over willpower:
- Pre-committed automatic exits reduce the disposition effect; reminders do not.
- Lower emotional reactivity goes with better trading results.
- If-then plans (implementation intentions) help goal pursuit, but bias-corrected effects are small (d ≈ 0.15–0.35, against 0.65 in the 2006 meta-analysis).
- Removing attention triggers (notifications) addresses a documented cause of extra risk-taking.

Journaling and structured review are standard prop-firm practice, but the evidence for their effect is mostly anecdotal or from vendors. Design the journal to measure process (rule adherence, slippage, overrides), not just P&L.

### Cited Findings
- **Automatic stop-loss / take-gain orders** causally reduced the disposition effect by increasing realized losses; reminders did not (Fischbacher et al., RFS 2017) — [EconPapers](https://econpapers.repec.org/RePEc:oup:rfinst:v:30:y:2017:i:6:p:2110-2129.)
- **More intense emotional reactions** to gains and losses went with significantly worse day-trading performance (Lo, Repin & Steenbarger, AER 2005; n = 80) — [MIT](https://web.mit.edu/Alo/www/Papers/online.html)
- **Implementation intentions:**
  - Gollwitzer & Sheeran (2006): 94 tests, more than 8,000 participants, d = 0.65 for goal attainment. This covered starting goal pursuit, shielding it from distractions, and disengaging from failing courses of action — [KOPS Konstanz](https://kops.uni-konstanz.de/entities/publication/2e749bfb-8533-437c-8203-7e788c910c5f); [Stafforini summary](https://stafforini.com/works/gollwitzer-2006-implementation-intentions-and/)
  - A 2024 follow-up meta-analysis (Sheeran, Listrom & Gollwitzer; 642 tests) reported bias-corrected estimates of d = 0.35 (trim-and-fill) and d = 0.15 (robust Bayesian, 95% CI 0.08–0.22). This is a search extract; verify against the primary paper — [KOPS Konstanz bitstream](https://kops.uni-konstanz.de/server/api/core/bitstreams/eb48c8cf-7855-478e-90ec-1ea6d44f8252/content)
- **Attention triggers** (push notifications) raise leverage and trading, more so after losses (Arnold et al., JFE 2022) — [EconPapers](https://econpapers.repec.org/RePEc:eee:jfinec:v:143:y:2022:i:2:p:846-875)
- **Losses lead to more risk the same day** among professional futures traders (Coval & Shumway, JF 2005) — [IDEAS](https://ideas.repec.org/a/bla/jfinan/v60y2005i1p1-34.html)
- **Steenbarger's framing:** journaling and review as deliberate practice (secondhand via vendor and forum material). A "report card" format attributed to him is unverified — [NexusFi thread](https://nexusfi.com/showthread.php?p=690479); [SMB Capital, "How to Conduct a Professional Review of Your Trading"](https://www.smbtraining.com/blog/?p=50281) (content not retrieved)
- **Process auditing:** weekly behavioral grading of execution audits process, not outcome. Auditing risk management matters most for prop traders — [Traders Second Brain](https://traderssecondbrain.com/guides/trading-report-card-grading)

### Inferences
- **Journal schema for a bot-plus-human setup** (synthesis):
  - **Automatic, per trade:** signal and rule version, intended vs actual entry and exit, slippage, fees, funding, R multiple, whether the stop was resting within N seconds of entry, any rejected or retried orders.
  - **Human, daily:** number of manual interventions or overrides (target: 0); whether any circuit breaker fired; mood and stress 1–5; sleep. This tracks emotional reactivity, which Lo et al. link to performance.
  - **Weekly:** live vs backtest statistics with confidence bands; review of incidents.
  - **Monthly:** the scale, keep or kill decision against the written criteria in Section 6.
- **Tools worth adopting, given the evidence:**
  - Pre-commitment in code: stops and limits that cannot be edited mid-session. Any configuration change goes through a pull request or commit with a 24-hour delay before taking effect.
  - Written if-then plans for predictable stressors, for example: "If the daily loss reaches 2%, the bot halts and I do not restart it until the next UTC day." "If I feel the urge to override, I write it in the journal instead."
  - Notifications off, except the bot's own risk alerts.
  - A mandatory cool-off after any circuit breaker.
  - A pre-mortem before each capital increase.
- Expect modest effects from any single psychology technique. Structural constraints (automation, hard limits, isolated margin) do most of the work. That suits a beginner coder with an AI assistant, provided the code is tested.

### Gaps
- No randomized or controlled evidence was found that journaling improves trading P&L. Steenbarger's primary books and SMB Capital's review protocol were not read.
- Evidence on mindfulness, heart-rate variability or hormones (e.g., Coates & Herbert) in traders was not searched for this note.
- The 2024 implementation-intention meta-analysis was seen only through a search extract.
