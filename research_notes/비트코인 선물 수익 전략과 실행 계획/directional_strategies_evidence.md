# Evidence on directional BTC (perpetual) futures strategies: trend/momentum, mean reversion, breakout, volatility targeting, derivatives/on-chain signals, discretionary trading, costs

> Compiled 2026-11-07 for an individual Korean resident considering BTC/USDT perpetual futures.
> **Method caveats (read first):** (1) Full-text fetching was blocked in this session (DNS blocks on man.com, quantpedia.com, abarbon.com, yahoo.com). The numbers below come from abstracts, repository and publisher pages, and secondary summaries surfaced by web search (CXO Advisory, Quantpedia, Quantified Strategies, Bloomberg, etc.). Check key numbers against full texts before treating them as final. (2) The shared web-search budget ran out before some planned follow-ups: structural-break tests around the Dec-2017 CME listing and Jan-2024 spot ETFs, current BTC realized volatility, prop-firm statistics, Harvey et al. "Man vs Machine", direct funding-rate-predictability papers, and the Gerritsen et al. breakout study. These are listed under Gaps.
> **Tags:** [PR] = peer-reviewed journal; [WP] = working paper/preprint; [PRAC] = fund/practitioner research; [VENDOR] = exchange/data-vendor research; [PRESS] = news; [BLOG] = unreviewed blog/newsletter. "Gross" means before trading costs and "net" means after them. "MDD" means maximum drawdown.

## 1. Time-series momentum & trend following on BTC/crypto: academic and CTA evidence, Sharpe, drawdowns, lookbacks, decay over time

### Takeaway
Trend-following/time-series momentum (TSMOM) is the best-documented directional effect in BTC, and the evidence comes in three layers:
- **Early academic samples (2010–2018):** strong, with gross Sharpe ratios of 2 or more. But BTC buy-and-hold itself had a Sharpe of about 2.0 then.
- **Post-2018 academic out-of-sample and realistic-cost tests:** weaker and contested.
- **2017–2025 practitioner backtests:** still positive when the strategy uses an ensemble of lookbacks and volatility scaling. Examples are a net Sharpe of about 1.5 for a long-only multi-coin Donchian ensemble and about 1.6 gross for an intraday BTC trend ensemble.

The main, repeatable benefit is drawdown control: roughly 20% maximum drawdown versus more than 80% for buy-and-hold in backtests. Trend-following loses money in choppy ranges (2025: Barclay Cryptocurrency Traders Index −12.3%) and pays off in sustained moves (the early-2026 sell-off).
**한 줄 요약:** 추세추종은 근거가 가장 많은 BTC 방향성 전략이다. 그러나 과거 논문의 '샤프 2 이상'은 비용 전·초기 표본 결과라 기대치로 쓰면 안 되고, 실질 장점은 폭락 구간 회피(낙폭 축소)다.

### Cited Findings
**A. Academic — early samples (mostly ≤2018)**
- [PR] Liu & Tsyvinski, "Risks and Returns of Cryptocurrency," *Review of Financial Studies* 34(6):2689–2727 (2021); first circulated as NBER WP 24877 in Aug 2018. Findings:
  - Strong time-series momentum at **daily and weekly** frequencies for BTC, ETH and XRP.
  - Investor-attention proxies strongly forecast returns.
  - Only crypto-specific factors (momentum, attention) consistently explain crypto returns. Returns are exposed to crypto network factors but not to production factors.
  - Results are in-sample and gross. — [NBER w24877](https://nber.org/papers/w24877); [SSRN](https://papers.ssrn.com/abstract=3226806)
- Magnitudes reported in the CXO Advisory summary of Liu & Tsyvinski:
  - Average **next-week BTC return of 11.2% after a top-quintile week vs 2.6% after a bottom-quintile week**.
  - A 1-SD rise in Google searches for "Bitcoin" → **+2.50%** 1-week-ahead BTC return.
  - A 1-SD rise in "Bitcoin hack" searches → −2.75% next week (NBER text); CXO gives −2.8%.
  - CXO stresses that these analyses are in-sample. — [CXO Advisory](https://www.cxoadvisory.com/currency-trading/crypto-asset-risks-and-returns/); [NBER PDF](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)
- [PR] Liu, Tsyvinski & Wu, "Common Risk Factors in Cryptocurrency," *Journal of Finance* (2022): a cross-sectional factor model (market, size, momentum). It is relevant only as context, because it is about cross-sectional coin selection, not BTC timing. — [Cowles PDF](https://cowles.yale.edu/sites/default/files/2022-10/LiuTsyvinskiWu2019%20COMMON%20RISK%20FACTORS.pdf)
- [PR] Detzel, Liu, Strauss, Zhou & Zhu, "Learning and predictability via technical analysis: Evidence from bitcoin and stocks with hard-to-value fundamentals," *Financial Management* 50(1):107–137 (2021):
  - Ratios of price to moving average forecast **daily** BTC returns in- and out-of-sample.
  - MA timing gives economically significant alpha and Sharpe gains vs buy-and-hold.
  - Working-paper version (sample **Jul-2010 to Dec-2017**): annualized Sharpe falls systematically from **2.6 (5-day SMA) to 2.2 (100-day SMA)** vs **~2.0 for buy-and-hold**. These figures are **GROSS**.
  - CXO notes that BTC's trading frictions at the time may have exceeded breakeven costs. — [RePEc](https://econpapers.repec.org/RePEc:bla:finmgt:v:50:y:2021:i:1:p:107-137); [CXO Advisory](https://www.cxoadvisory.com/currency-trading/timing-bitcoin-with-smas/)

**B. Robustness: data-snooping, out-of-sample and realistic-cost tests**
- [PR] Hudson & Urquhart, "Technical trading and cryptocurrencies," *Annals of Operations Research* (online 2019; 2021):
  - Tests ~15,000 rules in 5 classes on BTC, ETH, LTC and XRP. Every class shows significant predictability and profitability in every coin.
  - After multiple-hypothesis (data-snooping) corrections, a large share of rules remains significant.
  - Breakeven costs are well above typical crypto costs, and the rules cut drawdowns vs buy-and-hold.
  - **However, per the indexed summaries, BTC's predictability does not hold in the out-of-sample period, while other coins' predictability remains.** This conflicts with Detzel et al.'s out-of-sample result for BTC. — [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1); [Univ. of Reading repository](https://centaur.reading.ac.uk/85715)
- [PR, lower-tier journal] *Journal of Accounting and Finance* (2023), BTC/USDT and ETH/USDT, **2022–2023**: no profitable technical strategies in either the analysis or the prediction sample after data-snooping adjustment. — [JAF](https://articlegateway.com/index.php/JAF/article/view/6453)
- [PR] *Financial Markets and Portfolio Management* (Springer, 2023) study of 12 cryptocurrencies including BTC: predictability for only a small set of rules, which questions the value of technical analysis. — [Springer PDF](https://link.springer.com/content/pdf/10.1007/s11408-023-00433-2.pdf)
- [WP] Han, Kang & Ryu, "Time-Series and Cross-Sectional Momentum in the Cryptocurrency Market: A Comprehensive Analysis under Realistic Assumptions":
  - Once transaction costs and **intraday price swings (margin liquidation)** are modelled, many momentum portfolios are liquidated and many statistically significant returns become insignificant.
  - A t-test on the mean return is "insufficient to test profitability".
  - **TSMOM evidence is strong; cross-sectional momentum evidence is weak.** — [AUT ACFR PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)

**C. Practitioner / CTA evidence (2017–2025 samples)**
- [PRAC via PRESS] Man AHL, per Bloomberg on 3 Apr 2024: a proxy **long-short** trend strategy in BTC and ETH **outperformed buy-and-hold since 2017 when both were scaled to 10% volatility**. The same article cites a **2023 Monash University paper**: trend-following broadly beat a constant BTC/ETH investment, with **shorter lookbacks more profitable** than longer ones. Cambridge researchers reported similar results. — [Bloomberg](https://www.bloomberg.com/news/articles/2024-04-03/quant-momentum-trade-is-hot-again-in-crypto-amid-sharp-reversal); [Cryptonews AU summary](https://cryptonews.com.au/news/quant-traders-outperform-buy-and-hold-strategy-in-bitcoins-roller-coaster-market-studies-show-119505)
- [WP/academic project] Monash Centre for Financial Studies, "Trend-following strategies for crypto investors": shorter lookbacks are effective in generating a high Sharpe ratio, but "transaction costs may decrease profits due to frequent portfolio rebalancing". — [Monash CFS](https://www.monash.edu/business/mcfs/our-research/all-projects/investment-strategy/trend-following-strategies-for-crypto-investors)
- [PRAC] Man Group, "In Crypto We Trend" (dated Dec 2024 in search metadata; the metadata is inconsistent):
  - Crypto's liquidity, volatility and lack of valuation anchors produce pronounced trends, but models "cannot be transferred directly without adjustment".
  - A simplified model (MA-crossover and breakout signals) that accounts for **transaction costs, shorting costs, liquidity constraints and shorting availability** peaks in Sharpe at **~10–15 coins**. Beyond that, costs outweigh the diversification gain.
  - **More reactive (faster) models need fewer coins.**
  - No headline Sharpe figure was retrieved. — [Man Group](https://www.man.com/insights/in-crypto-we-trend); [QuantSeeker note](https://substack.com/@quantseeker/note/c-82199199)
- [PRESS] Man Group has digital-asset exposure through AHL, "which actively trades crypto futures" (earlier press coverage of Man's crypto-fund plans). — [Cointelegraph](https://cointelegraph.com/news/138b-investment-manager-man-group-to-launch-crypto-hedge-fund-report); [Blockworks](https://blockworks.com/news/140-billion-asset-management-firm-considers-launching-crypto-fn)
- [WP] Zarattini, Pagani & Barbon, "Catching Crypto Trends: A Tactical Approach for Bitcoin and Altcoins," Swiss Finance Institute RP 25-80 / SSRN 5209907 (Apr 2025, revised Oct 2025):
  - Method: an **ensemble of Donchian-channel (breakout) trend models with different lookbacks, plus volatility-based sizing**, run **long-only**.
  - Data: survivorship-bias-free, 21,616 crypto assets, **Jan 2010 to mid-Mar 2025** (per CXO).
  - Result: the top-20-liquid-coin rotational portfolio earned a **net-of-fees Sharpe above 1.5 and alpha of 10.8%/yr vs BTC**. — [IDEAS/RePEc](https://ideas.repec.org/p/chf/rpseri/rp2580.html); [Concretum Group](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/); [CXO Advisory](https://www.cxoadvisory.com/?p=46798)
  - Secondary summary (Quantified Strategies; the search snippets of it are internally inconsistent): the "Combo" model on BTC had a **Sharpe of ~1.58 with an MDD of ~19%** vs **>80% for passive BTC**; the diversified portfolio had a net Sharpe of 1.57 with an MDD of ~11%. The fee level assumed was not visible. — [Quantified Strategies](https://www.quantifiedstrategies.com/?p=1192563)
- [PRAC/BLOG] Concretum Group, "Seasonality in Bitcoin Intraday Trend Trading" (2025):
  - An ensemble **long-short high-frequency (intraday) BTC trend** benchmark had a **GROSS Sharpe of ≈1.6 over 2018–2025**.
  - A **volatility-targeted (20%) long-only BTC** portfolio had a Sharpe just **under 0.8**.
  - The post compares intraweek seasonality of trend behaviour in 2018–2020H1 vs 2020H2–2025; details were not retrieved. — [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
- [WP/PRAC] Padyšák & Vojtko, "Seasonality, Trend-following, and Mean Reversion in Bitcoin" (SSRN, Apr 2022; Quantpedia):
  - BTC **trends when at its N-day maximum** ("MAX" = buy new highs, a breakout rule) and bounces at its minimum ("MIN").
  - Lookbacks of 10/20/30/40/50 days were tested; **10-day was strongest**. MIN had drawdowns **>80%**.
  - Quantpedia's 2024 revisit (data to **Aug 2024**) found **MAX stayed effective out-of-sample**. — [Quantpedia](https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/); [Quantpedia revisit](https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/embed/); [CXO Advisory](https://www.cxoadvisory.com/currency-trading/patterns-in-short-term-bitcoin-returns)

**D. Most recent live/industry performance (2025–2026), i.e., how the evidence is holding up**
- [PRAC] XBTO's 2025 review:
  - BTC ranged **$75k–$126k**, then compressed to **$85–90k** at year-end.
  - Strategies relying on volatility expansion or sustained trends "faced frequent whipsaw".
  - Neither up- nor down-trends persisted long enough for momentum signals to develop. — [XBTO](https://www.xbto.com/resources/2025-the-year-market-regime-mattered-more-than-market-direction)
- [PRESS] The **Barclay Cryptocurrency Traders Index was −12.32% for 2025**, largely mirroring BTC, and was the worst Barclay sub-index for much of the year. — [The Full FX](https://thefullfx.com/ctas-end-2025-on-a-positive-note/)
- [PRESS] Directional crypto hedge funds were reported **−2.5% YTD through Nov 2025** (their worst since 2022). Brevan Howard's digital-asset fund was **−29.5% in 2025**; it is a broad strategy, not pure trend. — [iTiger (secondary)](https://www.itiger.com/hant/news/1164694354); [AlphaMaven/Hedgeweek](https://alpha-maven.com/story/hedge-fund/brevan-howards-crypto-strategy-hit-by-30-loss-in-2025-hedgeweek)
- [PRESS] Bloomberg, 27 Feb 2026:
  - Choppy 2025 markets punished crypto trend followers. Relief came in the early-2026 sell-off.
  - **XBTO's trend fund +13.3%** in the latest month (its 2nd-best month since its Feb-2024 launch), while BTC fell >10% and ETH fell 18%. — [Bloomberg](https://www.bloomberg.com/news/articles/2026-02-27/crypto-trend-following-trade-finds-relief-after-sharp-selloff)
- [PRESS] Context: BTC fell from **>$120k to <$70k** by early April 2026. — [The Block](https://www.theblock.co/news/business/2026-04-09-cme-bitcoin-futures-activity-slumps-to-14-month-low-as-basis-trade-unwind-drains-institutional-demand-396722)

**Summary table (as reported; verify before quoting)**

| Strategy / study | Type | Sample | Costs | Sharpe | Drawdown |
|---|---|---|---|---|---|
| SMA timing, 5–100d ([Detzel et al.](https://www.cxoadvisory.com/currency-trading/timing-bitcoin-with-smas/)) | PR | 2010–2017 | Gross | 2.6→2.2 (B&H ~2.0) | n/a |
| Donchian ensemble, long-only, multi-coin ([Zarattini et al.](https://ideas.repec.org/p/chf/rpseri/rp2580.html)) | WP | 2010/2015–Mar 2025 | Net of fees | >1.5 | ~11% (portfolio, secondary) |
| Same, BTC-only "Combo" ([Quantified Strategies](https://www.quantifiedstrategies.com/?p=1192563)) | secondary | same | unclear | ~1.58 | ~19% vs >80% B&H |
| Intraday long-short BTC trend ensemble ([Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)) | PRAC | 2018–2025 | Gross | ~1.6 | n/a |
| Vol-targeted (20%) long-only BTC ([Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)) | PRAC | 2018–2025 | — | <0.8 | n/a |
| 10-day MAX breakout ([Quantpedia](https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/)) | WP/PRAC | to 2022; OOS to Aug-2024 | unclear | n/a retrieved | n/a |
| Barclay Crypto Traders Index ([The Full FX](https://thefullfx.com/ctas-end-2025-on-a-positive-note/)) | live index | 2025 | Net | — | −12.32% year |

### Inferences
- The headline academic Sharpe ratios (2+) are not a planning number. They are gross, from 2010–2017, and barely above BTC's own buy-and-hold Sharpe in that era. The extra value of trend over buy-and-hold lay mostly in avoiding crashes.
- For a **single-asset BTC trend system** after fees, funding and a backtest-overfitting haircut, a realistic planning range is roughly **net Sharpe 0.5–1.0**, with **20–40% maximum drawdowns** at moderate volatility targets. The multi-coin net Sharpe of ~1.5 benefits from diversification across 10–20 coins. Man's finding that the Sharpe peaks at 10–15 coins says the same thing. This is my synthesis, not a sourced number.
- **Lookbacks:** crypto evidence favours short-to-medium horizons (days to ~3 months: weekly momentum, 5-day SMA, 10-day breakout) more than the 6–12-month horizons typical of traditional CTAs. Faster signals carry heavier cost drag (Monash, Man), so an **ensemble of lookbacks** (e.g., ~10–100 days, as Zarattini et al. do) is more robust than optimizing one window.
- **Decay:** academic out-of-sample tests on BTC after ~2018 are weak or negative (Hudson & Urquhart, the JAF 2023 study), while practitioner backtests through 2024–2025 remain positive. The likely explanation is that simple single-rule BTC timing has decayed, while diversified, vol-scaled, multi-horizon trend still earns a modest premium. The 2025 chop followed by the Q1-2026 downtrend fits trend as a "crisis-alpha/regime" strategy whose returns are lumpy.
- **Long-only vs long-short:** the strongest net result (Zarattini) is long-only. For perpetuals, the short side receives funding when funding is positive (see §6), but BTC's long-run positive drift makes shorts structurally harder. Expect the short leg to add mainly in bear phases such as Q1-2026.

### Gaps
- Full Man "In Crypto We Trend" numbers (Sharpe, lookbacks, cost assumptions) were not retrievable (fetch blocked).
- Zarattini et al.: exact fee and slippage assumptions and BTC-only net statistics are unverified (only secondary summaries were seen).
- **No direct structural-break test** of BTC trend profitability around the Dec-2017 CME futures listing or the Jan-2024 spot ETF launch was retrieved (e.g., Köchling et al. 2019 on futures and efficiency). The search budget was exhausted.
- No BTC-specific evidence on classic 12-month TSMOM was retrieved, nor any audited live track records of BTC-only CTA programmes beyond the Barclay index and XBTO press figures.
- No study isolating the profitability of the **short side** of BTC trend strategies was found.

## 2. Mean reversion / short-term reversal, intraday and calendar effects (time-of-day, weekend, US macro releases), breakouts; robustness after costs and data-snooping controls

### Takeaway
- **Mean reversion:** evidence for BTC is weak. Short-term reversal in crypto is mainly an illiquid-small-coin effect, the largest coins show daily momentum instead, and "buy the 10-day low" suffered drawdowns of over 80%.
- **Intraday/calendar effects:** the documented ones are intraday half-hour momentum, a late-evening UTC window (22:00 UTC) and a Monday effect. They are in-sample, use small exposure windows, are fragile out-of-sample, and are easily erased by perpetual-futures fees.
- **Macro releases (FOMC/CPI/NFP):** they reliably move volatility and spreads, but the evidence on direction conflicts.
- **Breakouts:** breakout-type trend rules (N-day highs, Donchian channels) are the best-supported short-horizon pattern.

**한 줄 요약:** BTC는 단기적으로 '되돌림'보다 '추세 지속' 성향이 강하다. 시간대·요일 효과는 수수료에 쉽게 먹히고, 거시지표 발표는 방향보다 '위험 관리(포지션 축소)' 대상이다.

### Cited Findings
**Intraday momentum / reversal**
- [PR] Shen, Urquhart & Wang, "Bitcoin intraday time series momentum," *Financial Review* 57(2):319–344 (2022). The trading day is defined by volume, because BTC trades 24/7.
  - The **first half-hour return positively predicts the last half-hour return**.
  - Intraday momentum gives substantial economic gains in market timing and asset allocation, **especially during downturns**.
  - The mechanism is liquidity provision, not late-informed trading.
  - Cost treatment was not visible in the snippets. — [Univ. of Birmingham](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/); [Reading accepted manuscript](https://centaur.reading.ac.uk/100181)
- [PR] Zaremba et al. (2021), "Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets," *International Review of Financial Analysis*:
  - Across coins, those with a low prior-day return outperform those with a high prior-day return (daily reversal).
  - The effect is driven by **illiquidity**.
  - **The handful of largest, most tradeable coins show daily momentum rather than reversal.** — [AMiner](https://aminer.org/pub/628d19b35aee126c0f369100/up-or-down-short-term-reversal-momentum-and-liquidity-effects-in-cryptocurrency); [X-MOL](https://www.x-mol.com/paper/1442395529393532928)
- [PR] Wen, Bouri, Xu & Zhao (2022), "Intraday return predictability in the cryptocurrency markets: Momentum, reversal, or both," *North American Journal of Economics and Finance* 62:101733. Its findings were not retrievable (see Gaps). — [EconBiz record](https://www.econbiz.de/Record/intraday-return-predictability-in-the-cryptocurrency-markets-momentum-reversal-or-both/10013534113)
- [WP/PRAC] Padyšák & Vojtko (2022): the **MIN (buy 10-day lows) mean-reversion rule had drawdowns >80%**, while the MAX trend rule was better. The 2024 revisit found **no significant day-of-week seasonality** in MIN/MAX. — [Quantpedia](https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/); [Quantpedia revisit](https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/embed/)

**Time-of-day / overnight**
- [WP/PRAC] Padyšák & Vojtko split BTC returns around **NYSE open and close**. The simplest strategy was **long BTC from 22:00 UTC for 2 hours** (Gemini exchange data). — [Quantpedia strategy page](https://quantpedia.com/strategies/intraday-seasonality-in-bitcoin); [CXO Advisory](https://www.cxoadvisory.com/currency-trading/patterns-in-short-term-bitcoin-returns)
- [PRAC] Quantpedia's entry for the 22:00 UTC two-hour hold reports a **Sharpe of 1.58 and an MDD of −34%**. Its summaries of intraday/overnight seasonality (hourly Gemini data, ~2015–2022) also describe a buy-21:00/sell-23:00 UTC rule. Cost treatment was not stated in what was retrieved. — [Quantpedia strategy](https://quantpedia.com/strategies/intraday-seasonality-in-bitcoin); [Quantpedia article](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/)

**Day-of-week / weekend**
- [PR] Caporale & Plastun, "The day of the week effect in the cryptocurrency market," *Finance Research Letters* (2019); DIW discussion paper 1694 (2017). Daily data 2013–2017.
  - **BTC was the only coin with an anomaly: Monday returns significantly higher.**
  - The trading-simulation profits were mostly **not significantly different from random** results, so they are "not conclusive evidence against market efficiency".
  - No post-2017 update was found. — [DIW DP 1694](https://www.diw.de/de/diw_01.c.567282.de/publikationen/diskussionspapiere/2017_1694/the_day_of_the_week_effect_in_the_crypto_currency_market.html); [Brunel full text](https://bura.brunel.ac.uk/bitstream/2438/17208/3/FullText.pdf)

**US macro releases**
- [WP] NY Fed Staff Report 1052 (intraday data): **unlike other US asset classes, BTC was "orthogonal to monetary and macroeconomic news"**. A related summary says BTC responded only to unexpectedly high or low core CPI prints. — [NY Fed SR 1052](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1052.pdf)
- [WP via BLOG] A newer study using CoinDesk intraday data (covering >90% of global volume) for **2015–2025** contradicts the NY Fed report:
  - Crypto shows **sharp, near-instant reactions to FOMC, CPI and NFP**. Volatility, volume and bid-ask spreads rise.
  - Hawkish or "risk-off" surprises → **substantial BTC/ETH declines**.
  - The FOMC press conference has a smaller peak effect than the statement. — [RWA Times summary](https://rwatimes.substack.com/p/how-do-cryptocurrencies-price-economic)
- [BLOG] Interdax (hourly data): BTC shows high abnormal volatility in the **hour before** the FOMC statement and press conference and in the hour of the event. — [Interdax/Medium](https://medium.com/interdax/how-do-fomc-announcements-affect-bitcoin-9f975de87cb3)
- [PRESS] Example, 12 Jun 2024: BTC spiked above $70k after the CPI release, then almost fully retraced after hawkish FOMC comments the same day. — [Kitco](https://www.kitco.com/news/article/2024-06-12/crypto-volatility-spikes-mixed-signals-positive-cpi-overshadowed-hawkish)
- [VENDOR/PRESS] The 10 Oct 2025 crash began after a tariff post at about 20:50 UTC on a Friday, late in the US session going into the weekend. It became the largest notional crypto deleveraging on record (details in §3). — [Galaxy Research](https://www.galaxy.com/insights/research/cryptos-flash-crash-liquidation-binance-adl-auto-deleveraging); [Cointelegraph](https://cointelegraph.com/news/19b-crypto-market-crash-leverage-china-tariffs)

**Breakouts and data-snooping controls**
- Breakout-type rules are the best supported: Donchian-channel ensembles (Zarattini et al., net Sharpe >1.5, multi-coin, long-only), the 10-day-high "MAX" rule (out-of-sample to Aug 2024), and Man's breakout and MA-crossover models. — [IDEAS/RePEc](https://ideas.repec.org/p/chf/rpseri/rp2580.html); [Quantpedia revisit](https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/embed/); [Man Group](https://www.man.com/insights/in-crypto-we-trend)
- Data-snooping-controlled tests conflict:
  - Hudson & Urquhart (multiple-testing corrected) find many significant rules, but report that BTC fails out-of-sample. — [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1)
  - The JAF 2023 study finds nothing for BTC/USDT in 2022–2023. — [JAF](https://articlegateway.com/index.php/JAF/article/view/6453)
  - Han, Kang & Ryu show that realistic liquidation and cost modelling turns many "significant" momentum results insignificant. — [AUT ACFR PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)

### Inferences
- **Fee arithmetic kills most intraday calendar strategies on perps.** This is my calculation using the §6 fee levels. A daily 2-hour hold is one round trip per day:
  - At taker fees (0.05% × 2 = 0.10% round trip): ≈ **36.5%/yr** of notional.
  - All-maker (0.02% × 2): ≈ **14.6%/yr**.
  - Both exclude slippage, and the reported edge must exceed this.
  - It also matters whether the holding window spans a funding timestamp. Binance's 8-hour contracts settle every 8 hours; this was not re-verified in this session.
- **Mean reversion on BTC itself** is not supported as a stand-alone directional strategy. At most it is a short-horizon entry-timing refinement inside a trend framework, and the >80% drawdown of the MIN rule is a warning.
- **Macro releases:** the robust, actionable fact is volatility and spread expansion around FOMC/CPI/NFP. That argues for **cutting size, avoiding market orders, and widening stops around releases** rather than betting on direction.
- **Weekends:** there is no current evidence of a tradable weekend directional effect. Thin weekend liquidity and the Friday-evening (UTC) shock of 10 Oct 2025 suggest weekend gap/wick risk mainly matters for leverage and liquidation settings.

### Gaps
- Wen et al. (2022) results (momentum vs reversal at intraday horizons) were not retrieved.
- Gerritsen et al. (2020, *Finance Research Letters*, trading-range-breakout rules on BTC) was not retrieved; the search budget was exhausted.
- No post-2022 or post-ETF out-of-sample test of the 22:00 UTC effect or the Monday effect was found. Concretum's intraweek-seasonality findings for 2018–2020H1 vs 2020H2–2025 were not visible.
- No net-of-cost test of intraday strategies **specifically on perpetuals** (with funding) was found.

## 3. Volatility targeting and leverage: does scaling by forecast volatility help in BTC? Optimal leverage (Kelly / fractional Kelly)

### Takeaway
- **Volatility targeting:** the best available evidence is practitioner backtests, not peer-reviewed out-of-sample studies. They indicate that volatility targeting improves BTC's risk-adjusted returns: Man reports **+~0.4 Sharpe for BTC scaled to 30% vol (Sep-2012 to Dec-2024)**, robust to the estimator half-life, and volatility-scaled BTC has milder left tails.
- **Kelly:** standard Kelly math with plausible BTC inputs puts the growth-optimal exposure to raw BTC at **about 1x or less**, and fractional (½ or less) Kelly is standard because inputs are uncertain.
- **Liquidation:** the binding constraint for perps is liquidation/gap risk (10 Oct 2025: >$19B liquidated), not the Kelly optimum.

**한 줄 요약:** 변동성에 맞춰 포지션 크기를 줄이고 늘리는 방법은 BTC에서 위험 대비 수익을 개선한다는 실무 근거가 있다. 레버리지는 계산상으로도 원금의 1배 안팎이 상한이고, 실제로는 그보다 낮게(½ 켈리 이하) 쓰는 것이 합리적이다.

### Cited Findings
- [PRAC] Man Group, "Crypto: Too Hot to Handle?" (Mar 2025). Data on BTC from **Sep 2012 to Dec 2024**.
  - Ex-ante scaling to **30% volatility** raises Sharpe by **"around 40 Sharpe points [≈+0.40] in each instance, irrespective of the responsiveness, or half-life, of the volatility estimates used"**.
  - Rolling 3-month drawdown vs rolling 3-month volatility: at the volatility of early 2025, drawdowns of **up to ~50%** could be expected, vs **~70%** when volatility approached **130%**. — [Man Group](https://www.man.com/insights/crypto-too-hot-to-handle)
- [PRAC] Man Institute's investor guide to crypto (*Journal of Portfolio Management* piece): once volatility-scaled, **BTC's left tails are more benign than the S&P 500's**, which makes volatility scaling more effective. Volatility-targeting methods help control crypto risk, and trend-following has performed well. — [Man Institute](https://www.man.com/maninstitute/investor-guide-to-crypto)
- [PRAC] Man, "Bitcoin's place in multi-asset portfolios":
  - BTC "has still registered by far the highest Sharpe of any major liquid asset class, at **2.3**" (sample period not visible in the snippet).
  - It has suffered **six drawdowns of ≥50%**.
  - It is **negative 86% of the time** when equities have a ≥5% monthly drawdown. — [Man Group](https://www.man.com/insights/bitcoins-place-in-multi-asset-portfolios)
- [PRAC] Man AHL compares trend vs buy-and-hold with both scaled to **10% volatility** (since 2017). — [Bloomberg](https://www.bloomberg.com/news/articles/2024-04-03/quant-momentum-trade-is-hot-again-in-crypto-amid-sharp-reversal)
- [PRAC] Concretum: **20%-vol-targeted long-only BTC → Sharpe just under 0.8 (2018–2025)**, vs ~1.6 gross for an intraday long-short trend ensemble. — [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
- [WP] Zarattini et al. use **volatility-based position sizing** in their Donchian ensemble (net Sharpe >1.5). — [Concretum Group](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/)
- [PR, equities, not crypto] Moreira & Muir, "Volatility-Managed Portfolios," *Journal of Finance* 72(4):1611–1644 (2017): large alphas, higher factor Sharpe ratios and utility gains for mean-variance investors. This is the general foundation, but it is not tested on BTC. — [Harbourfront Quant summary](https://harbourfrontquant.substack.com/p/volatility-targeting-across-asset)
- [BLOG] Coinmonks: volatility-managed crypto portfolios had ">3X the Sharpe ratio and 1/3 the drawdowns" of equal-weight portfolios. The author warns that the sample of assets and price data is small. — [Medium/Coinmonks](https://medium.com/coinmonks/whats-vol-got-to-do-with-it-886b57c2d762)
- [PRAC] Grayscale Monte Carlo analysis: in a 60/40 portfolio, Sharpe rises with a static BTC allocation until **~5%**, then levels off. — [Grayscale Research](https://research.grayscale.com/reports/crypto-in-diversified-portfolios)
- [BLOG] Kelly sources:
  - Luckbox: the edge grows linearly with leverage while the drag from geometric (volatility) decay grows with **its square**, so beyond some point extra leverage destroys growth. Its unverified example is an **ETH** trend strategy with a Kelly-optimal leverage of **1.7x**. — [Luckbox](https://luckboxmagazine.com/?p=15481)
  - Altrady: Kelly assumes precise probability estimates, which are not available in reality; **half-Kelly captures ~75% of optimal growth** with much lower variance. — [Altrady](https://www.altrady.com/blog/risk-management/kelly-criterion-crypto-position-sizing)
  - Perrenod: Kelly applied to a cash+BTC portfolio on monthly history gave large BTC allocations (~75% in one post), with the warning that back-tests do not assure future performance. — [Perrenod Substack](https://stephenperrenod.substack.com/p/kelly-criterion-for-bitcoin)
- [VENDOR/PRESS] Leverage tail event, **10 Oct 2025**:
  - **>$19B** of leveraged positions were liquidated across **>1.6M accounts** (CoinGlass); about **$16.7B of that was longs**.
  - Hyperliquid had ~$10.3B of liquidations, and its **auto-deleveraging (ADL) force-closed profitable opposite positions**.
  - Binance's reported liquidations (~$2.4B) were likely understated because of API throttling.
  - A Binance-specific stablecoin de-peg and distorted internal prices triggered extra forced sales. — [Galaxy Research](https://www.galaxy.com/insights/research/cryptos-flash-crash-liquidation-binance-adl-auto-deleveraging); [Cointelegraph](https://cointelegraph.com/news/19b-crypto-market-crash-leverage-china-tariffs); [Insights4VC](https://insights4vc.substack.com/p/inside-the-19b-flash-crash); [The Defiant](https://thedefiant.io/newsletter/defi-daily/the-ultimate-10-10-crash-autopsy)
- [WP] Han, Kang & Ryu: with realistic daily price swings, **many leveraged momentum portfolios get liquidated**. — [AUT ACFR PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)

### Inferences
These are standard Kelly calculations of my own, not sourced numbers.
- The continuous-time Kelly fraction is **f\* = μ/σ²**, where μ is the expected excess return and σ the volatility. Equivalently, the Kelly-optimal **portfolio volatility equals the Sharpe ratio**, and growth at full Kelly is SR²/2 per year. Fraction c of Kelly gives growth of c(2−c)·SR²/2, so ½-Kelly gives 75% of the growth at half the volatility.
- **Buy-and-hold BTC examples:**

  | Expected excess return μ | Volatility σ | Kelly f\* | ½-Kelly |
  |---|---|---|---|
  | 20% | 50% | 0.8x | 0.4x |
  | 10% | 50% | 0.4x | 0.2x |
  | 40% | 70% | ~0.8x | ~0.4x |

  So **leverage above 1x on directional BTC exceeds even full Kelly** under plausible assumptions, before fat tails and jumps are considered.
- **Trend system examples:** suppose a realistic live Sharpe of ~0.6. Kelly volatility is then 60%, ½-Kelly ≈ 30% and ¼-Kelly ≈ 15% annual volatility. With BTC's volatility around 50%, a 30% target means **~0.6x average notional exposure**, and only short bursts above 1x in calm periods. Perp margin leverage is therefore a capital-efficiency tool (keeping most collateral off-exchange), not a reason to run more than ~1–1.5x notional.
- **Why to stay below Kelly:**
  - Backtested Sharpe overstates live Sharpe.
  - BTC has jump risk: 10 Oct 2025 and the Man drawdown–volatility relation.
  - Perps add **exchange-specific liquidation and ADL risk**: even a hedged or profitable position can be force-closed.
  - Recommended practice from this evidence: volatility-target at 15–30%, use isolated margin with distant liquidation prices, and cap notional at about 1–1.5x equity.
- The **~+0.4 Sharpe from volatility scaling** (Man) is large but is an in-sample industry estimate. It is plausible because BTC's volatility is persistent and high-volatility regimes coincide with crashes (the Man drawdown–volatility link).

### Gaps
- No **peer-reviewed, out-of-sample** test of volatility-managed BTC (single-asset) was found. Man's +0.4 Sharpe is from its own backtest, and the chart data were not seen.
- **Current (2026) BTC realized volatility** was not retrieved (search budget exhausted). The Kelly examples therefore use assumed volatilities of 50–70%.
- No rigorous BTC-specific study of optimal leverage for trend systems was found, only blogs.

## 4. Signals from derivatives and on-chain data (funding, basis, open interest, liquidations, long/short ratios, ETF flows, on-chain metrics): quality of evidence

### Takeaway
Ranked by evidence quality:
1. **Futures basis ("carry")** is the best-documented signal (BIS working paper). High carry reflects leveraged, trend-chasing demand and **predicts crash risk**.
2. **Investor attention and network adoption** have peer-reviewed but in-sample, pre-2019 support.
3. **Spot-ETF flows** give mixed and mostly short-horizon evidence, with strong reverse causality (flows chase price).
4. **Funding rates as a return predictor** have no clean peer-reviewed out-of-sample test. Funding is anchored at a fixed baseline most of the time, so only extremes carry information.
5. **Open interest, liquidation and long/short-ratio signals** rest on practitioner backtests only.
6. **On-chain cycle metrics** (e.g., MVRV) are tested over only ~3 cycles, which gives very low statistical power.

**한 줄 요약:** 파생·온체인 지표 중 근거가 가장 탄탄한 것은 '선물 프리미엄(캐리)이 과열되면 폭락 위험이 커진다'는 것이다. 펀딩비·미결제약정·롱숏비율·ETF 자금흐름은 단독 매매 신호로 쓰기엔 검증이 약해 '과열 경보/필터' 정도로 쓰는 게 맞다.

### Cited Findings
**Carry / basis / funding**
- [WP; reportedly accepted at *Management Science*, unconfirmed] Schmeling, Schrimpf & Todorov, "Crypto carry," BIS Working Paper 1087 (Apr 2023, revised Oct 2025):
  - The futures-spot basis (carry) is very large and volatile: it **sometimes exceeds 40% p.a.** per the abstract, while the BIS summary says **up to 60%**.
  - Interest-rate differentials explain very little of it.
  - It is driven by a convenience yield from **smaller, trend-chasing investors seeking leveraged exposure**, plus limited arbitrage capital (regulatory and margin frictions).
  - **High carry predicts future price crashes.** Rising carry goes together with a rising price of crash-risk insurance. — [BIS](https://www.bis.org/publ/work1087.htm); [BIS PDF](https://www.bis.org/publ/work1087.pdf)
- [WP] He, Manela, Ross & von Wachter, "Fundamentals of Perpetual Futures" (arXiv 2212.06888):
  - Derives no-arbitrage perp prices. Deviations from them are larger in crypto than in FX futures.
  - An arbitrage strategy earns a **Sharpe of 1.8 under retail-level trading costs** and **up to 3.5 for fee-free market makers**.
  - This is a market-neutral result, not a directional one. — [arXiv](https://arxiv.org/pdf/2212.06888)
- [WP] A BitMEX funding study (arXiv 1912.03270) finds Granger causality between BitMEX inverse-perp funding and the BTC exchange rate and builds a GARCH model. It **forecasts funding, not returns**. — [arXiv](https://arxiv.org/abs/1912.03270v1)
- [BLOG] Brave New Coin's test of "is the funding rate predictive": the relation between funding and next-period returns is **mixed**. — [Brave New Coin](https://bravenewcoin.com/insights/testing-theory-is-perpetual-swap-funding-rate-predictive)
- [VENDOR] BitMEX Q3-2025 derivatives report ("The Anchor and the Ceiling", 14 Oct 2025; covers BitMEX, Binance and Hyperliquid):
  - Funding was **positive ~92% of the time in Q3 2025**.
  - The 2024–2025 average hovers around the **0.01%/8h baseline (= 10.95%/yr)**.
  - Arbitrage capital quickly compresses high premia (the "ceiling"). — [BitMEX](https://www.bitmex.com/blog/2025q3-derivatives-report); [CryptoPotato](https://cryptopotato.com/bitmex-study-finds-cryptocurrency-funding-rates-positive-92-of-the-time-revealing-a-structural-market-bias/)
- [BLOG] Coincub headline: "Perpetual Futures Funding Rates: 78% of a Quarter at 0.01%" (only the title was seen; which exchange and quarter is unknown). — [Coincub](https://coincub.com/blog/perpetual-futures-funding-rates-78-of-a-quarter-at-0-01/)

**Open interest / liquidations / long-short ratios**
- [VENDOR] Glassnode's "LPOC" framework infers leveraged position openings and closures from joint price and OI changes. It is **descriptive**; no published out-of-sample predictive test was found. Glassnode also publishes liquidation heatmaps. — [Glassnode LPOC](https://insights.glassnode.com/leverage-position-openings-and-closures); [Glassnode heatmaps](https://insights.glassnode.com/liquidation-heatmaps/)
- [BLOG] Axel Adler Jr.: in single-author, in-sample backtests, certain liquidation-dominance readings preceded positive or negative returns over 7–30 days. These are unreviewed. — [Axel Adler Jr](https://axeladlerjr.com/derivatives-structure-gives-bulls-a-tactical-advantage/)

**On-chain**
- [WP] Grobys, Näsman & Sandretto (Univ. of Vaasa), "Using on-chain data to predict Bitcoin cycles":
  - Rule-based contrarian entries across **three market cycles**.
  - The **MVRV Z-score** performed best, beating the benchmark and the NUPL variant on returns and risk-adjusted returns.
  - The very small number of cycles limits inference. — [Vaasa repository](https://osuva.uwasa.fi/server/api/core/bitstreams/724d46d8-aebf-46ca-89e0-150aec337506/content)
- [PRAC] Hafeez & Mandara (bank research note via Macro Hive) regress 30-day forward BTC returns on standardized exchange-balance changes. The coefficients are **negative and significant but differ across exchanges**. The note is not peer-reviewed and apparently not out-of-sample. — [Macro Hive](https://macrohive.com/hive-exclusives/do-flows-onto-crypto-exchanges-predict-bitcoin-price-moves)
- [VENDOR] Glassnode reports out-of-sample results for its own ML on-chain trading signal. This is vendor research, not independent. — [Glassnode](https://insights.glassnode.com/the-predictive-power-of-glassnode-data)
- [PR] Liu & Tsyvinski: crypto returns are exposed to **network (adoption) factors** and investor attention, and attention forecasts 1-week returns. These results are in-sample and pre-2019. — [NBER w24877](https://nber.org/papers/w24877)

**Spot-ETF flows (2024–2026)**
- [PR] Mazur & Polyzos (2025, *Journal of Alternative Investments*) say in their abstract that **net ETF flows are a strong positive predictor of BTC price effects** and the dominant single factor in their sample. Only the abstract was seen. — [Zayed University record](https://zuscholars.zu.ac.ae/works/7267)
- [VENDOR] FalconX finds short-term directional predictive power from flows and a feedback loop in which price rises temporarily dampen inflows. Flows may predict the direction of moves but not their size. — [FalconX](https://falconx.io/newsroom/what-can-spot-etf-flows-tell-us-about-the-trajectory-of-bitcoin-prices-a-preliminary-statistical-investigation)
- [VENDOR] Bitwise: the reverse direction (BTC performance Granger-predicting flows) is also highly significant. Granger tests are "a screening view", not structural causality. — [Bitwise](https://bitwiseinvestments.eu/blog/crypto-research/bitcoin-etp-series-part-2)
- [VENDOR via PRESS] DWF Labs: the flow-to-price link weakens to **0.09 at one day and 0.03 at one week**. Investors mostly **react** to BTC moves rather than drive the subsequent trend. — [ForkLog](https://forklog.com/en/news/dwf-labs-questions-whether-etf-flows-predict-bitcoins-future-price-moves)
- [PR] *Ledger* (2025) tests cointegration between ETF assets and the BTC price, using the 2024 ETF launch as a natural experiment. Its results were not seen. — [Ledger](https://ledger.pitt.edu/ojs/ledger/article/view/393)

### Inferences
- Use derivatives data mainly as **(a) a cost input** (funding/basis = carry paid by longs) and **(b) a crowding/crash-risk filter**: cut long leverage when the basis or funding is far above its anchor, consistent with BIS's "high carry predicts crashes". Do not use them as a stand-alone direction signal.
- The Binance formula pins funding at the 0.01%/8h anchor whenever the premium is small (see §6), and funding was positive ~92% of Q3-2025. So **the funding *level* is mostly uninformative**; information sits in **deviations from the anchor** (very high or negative funding) and in the basis term structure.
- **ETF-flow data are published after the US close**, typically by the next morning in Asia. This lag plus reverse causality makes flows a poor intraday or next-day timing input. At best they are a slow regime or sentiment gauge. The publication lag is my inference; its timing was not sourced in this session.
- On-chain cycle indicators have almost no degrees of freedom (2–3 cycles). Treat them as regime context, not as tested signals.

### Gaps
- **No peer-reviewed, out-of-sample test of funding-rate → BTC-return predictability** was found (the follow-up search was blocked by the budget).
- A K33 (2024) study of seven long-squeeze events surfaced in a search summary: BTC averaged about −10% over the next 30 days after a 12.46% one-day OI drop. It could not be tied to a verifiable URL, so it is excluded from the findings.
- Long/short-ratio definitions (account counts vs position size) and their predictive value were not verified.
- A 2021 study (Hattori & Ishida) finding no link between futures trading and BTC returns around the 2017 futures launch was mentioned in a summary without a retrievable URL.

## 5. Discretionary trading: success rates of discretionary/retail traders; professional prop-trader practices

### Takeaway
Base rates for discretionary retail short-term futures trading are very poor:
- **~97% of persistent day traders lose money** in two large administrative datasets (Taiwan equities; Brazil index futures).
- **About 1% earn more than a minimum wage.**
- A **majority of retail crypto app users lost money on BTC holdings (2015–2022)**.

Crypto funds showed alpha in early, low-competition years, but evidence of skill is fragile. Discretionary crypto funds had a poor 2025: Brevan Howard's digital-asset fund was −29.5%.
**한 줄 요약:** 개인의 재량(감) 단타는 통계적으로 거의 다 진다(지속적으로 단타한 사람의 97%가 손실). 개인이 기댈 수 있는 쪽은 규칙 기반·저레버리지·사전 손실한도다.

### Cited Findings
- [PR] Barber, Lee, Liu, Odean (& Zhang), "Learning, Fast or Slow," *Review of Asset Pricing Studies* 10(1):61–93 (2020), on Taiwan:
  - The aggregate performance of day traders is **negative**.
  - **74% of day-trading volume** comes from traders with a history of losses.
  - **~97% of day traders are likely to lose money** in future day trading. — [IDEAS/RePEc](https://ideas.repec.org/a/oup/rasset/v10y2020i1p61-93..html)
- [PR/WP] Barber, Lee, Liu & Odean, Taiwan 1992–2006 (day-trading skill paper):
  - Aggregate day-trader performance **net of fees was negative in each of the 15 years**.
  - A **relatively small group shows persistent ability**. — [Berkeley PDF](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/Day%20Trading%20Skill%20110523.pdf)
- [WP] Chague, De-Losso & Giovannetti, "Day Trading for a Living?" (2019). Covers **everyone who began day trading Brazilian mini-Ibovespa index futures in 2013–2015**:
  - Of the **1,551 who persisted more than 300 sessions, 97% lost money**.
  - Only **17 people (1.1%) earned more than the Brazilian minimum wage (US$16/day)**, and only 8 (0.5%) earned more than a bank teller's starting salary.
  - There is **no evidence of learning**.
  - Caveats: the sample may not represent other countries or assets, and the period may have been hard for Brazilian index futures. — [EconPapers](https://econpapers.repec.org/paper/spawpaper/2019wpecon47.htm); [CXO Advisory](https://www.cxoadvisory.com/investing-expertise/day-trading-a-bust/); [Quantpedia](https://quantpedia.com/retail-day-trading-is-an-uphill-battle/)
- [Central-bank research] BIS Bulletin No 69, "Crypto shocks and retail losses" (Cornelli, Doerr, Frost & Gambacorta; 20 Feb 2023):
  - App data from major platforms, **Aug 2015 to Dec 2022**: "a **majority of crypto app users in nearly all economies made losses** on their Bitcoin holdings".
  - "Larger investors probably cashed out at the expense of smaller holders."
  - This concerns spot buying and timing, not leveraged trading. — [BIS](https://www.bis.org/publ/bisbull69.htm); [Decrypt](https://decrypt.co/121763/bitcoin-after-2015-lost-money-bis-report)
- [WP] BIS "Crypto carry": high futures carry is driven by **smaller, trend-chasing investors seeking leverage**. That is consistent with retail chasing leverage at bad times, since high carry predicts crashes. — [BIS](https://www.bis.org/publ/work1087.htm)
- [VENDOR/PRESS] 10 Oct 2025: **>1.6M accounts** were liquidated (>$19B), mostly longs. — [Cointelegraph](https://cointelegraph.com/news/19b-crypto-market-crash-leverage-china-tariffs)
- [PR] Bianchi & Babiak, "On the performance of cryptocurrency funds," *Journal of Banking & Finance* (2022):
  - Crypto funds show **positive alphas** vs passive benchmarks and conventional factors.
  - A **sizable minority** covers costs and produces large alphas, but evidence of skill weakens once common variation within strategies is accounted for.
  - The authors attribute the alphas partly to **low competition** (assets are concentrated in few funds).
  - Outperformance is not concentrated in any one strategy. — [Riksbank WP 408](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2021/no.-408-on-the-performance-of-cryptocurrency-funds.pdf); [Lancaster eprint](https://eprints.lancs.ac.uk/id/eprint/169953)
- Follow-up studies on crypto-fund skill, as summarized by Decrypt:
  - Dombrowski, Drobetz & Momtaz (2023): **only a few crypto funds show superior skill**, and the choice of performance measure changes the rankings.
  - Urquhart & Wang (2023): managers with **prior hedge-fund experience** earn significant returns; those with only a crypto background do not. — [Decrypt "Professor Coin"](https://decrypt.co/306015/professor-coin-do-managed-crypto-funds-outperform-the-market?amp=1)
- [PRESS] In 2025, Brevan Howard's digital-asset fund was **−29.5%**, and directional crypto funds were reported at **−2.5% YTD through Nov 2025**. — [AlphaMaven/Hedgeweek](https://alpha-maven.com/story/hedge-fund/brevan-howards-crypto-strategy-hit-by-30-loss-in-2025-hedgeweek); [iTiger (secondary)](https://www.itiger.com/hant/news/1164694354)
- [PRAC] Practices of systematic professionals visible in this evidence:
  - Volatility targeting (Man AHL at 10% vol; Man's 30% BTC example).
  - Diversification across ~10–15 coins, with costs, shorting costs, liquidity and short availability explicitly modelled (Man).
  - Ensembles of lookbacks (Zarattini).
  - Adapting models to crypto rather than transplanting them (Man). — [Man Group](https://www.man.com/insights/in-crypto-we-trend); [Man Group](https://www.man.com/insights/crypto-too-hot-to-handle); [Concretum Group](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/)

### Inferences
- An individual who trades BTC perps **discretionarily and at short horizons** should assume a base rate close to the 97%-lose figure. Crypto perps add 24/7 trading, high available leverage, liquidation mechanics and ADL, which plausibly make outcomes worse than in the Taiwan and Brazil samples. No crypto-perp-specific study of retail P&L was found.
- The early crypto-fund alpha (Bianchi & Babiak) came partly from low competition. Institutional entry (CME, ETFs, basis traders) has likely reduced that edge since. The 2025 results are consistent with this.
- What transfers from professionals is **process, not prediction**: pre-defined systematic rules, volatility-based sizing, explicit cost modelling, pre-committed loss limits, and avoiding leverage spikes.

### Gaps
- **Prop-firm statistics** (e.g., FTMO-style challenge pass rates and payout rates) and **discretionary prop-desk risk rules** were not retrieved; the search budget was exhausted.
- Harvey et al. (2017) "Man vs Machine" (discretionary vs systematic hedge funds) was not retrieved.
- No **Korea-specific** data on retail losses in crypto derivatives was found.
- No exchange-data study of retail P&L distributions on BTC perpetuals was found.

## 6. Costs specific to perpetuals (funding drag on long holding, fees, slippage) and perps vs spot vs CME futures for directional exposure

### Takeaway
On Binance USDⓈ-M perps, funding defaults to **+0.01% per 8h ≈ 10.95%/yr paid by longs to shorts** whenever the premium is near zero. It was positive ~92% of the time in Q3 2025 and can be far higher in euphoric markets (carry >40% p.a. at extremes). That makes **perps an expensive way to *hold* long BTC**, but cheap to trade:
- Base-tier fees are ~0.02% maker / 0.05% taker.
- Shorts collect funding.

CME futures embed a basis that compressed from ~15–20% to ~3–5% annualized in 2025–2026; access for Korean residents is unclear. Spot has no carry, but shorting it is impractical.
**한 줄 요약:** 무기한 선물로 '롱을 오래 들고 있기'는 연 약 11% 안팎의 펀딩비가 기본으로 나가는 비싼 방법이다. 선물은 '사고팔기(추세 전환 시 롱↔숏)'에 쓰고, 장기 보유는 현물이 싸다.

### Cited Findings
- [VENDOR, primary] Binance USDⓈ-M funding:
  - Formula: **F = [Average Premium Index (P) + clamp(interest rate − P, ±0.05%)] / (8/N)**, where N is the funding interval in hours.
  - **The interest rate is 0.01%** per interval basis, except BNBUSDT and ETHBTC, where it is 0%.
  - The premium index is computed **every 5 seconds**, and funding is a time-weighted average of **5,760** points. — [Binance FAQ](https://www.binance.com/en/support/faq/360033525031); [Binance announcement](https://www.binance.com/fr/support/announcement/detail/c00588a7e8504b3eb28d02a2da00530b)
- [VENDOR] BitMEX Q3-2025 report:
  - Baseline 0.01%/8h = **10.95%/yr**.
  - Funding positive **~92% of Q3 2025** across BitMEX, Binance and Hyperliquid.
  - BitMEX sat at the anchor more often than Binance or Hyperliquid.
  - Arbitrage caps high premia. — [BitMEX](https://www.bitmex.com/blog/2025q3-derivatives-report); [CryptoPotato](https://cryptopotato.com/bitmex-study-finds-cryptocurrency-funding-rates-positive-92-of-the-time-revealing-a-structural-market-bias/)
- [WP] BIS "Crypto carry": futures carry **sometimes >40% p.a.** (abstract), or up to 60% (BIS summary). — [BIS](https://www.bis.org/publ/work1087.htm)
- [WP] He et al.: perp-vs-spot pricing deviations are large enough for an arbitrage **Sharpe of 1.8 at retail costs**. This shows that funding and premium deviations are economically material. — [arXiv](https://arxiv.org/pdf/2212.06888)
- [BLOG, third-party fee comparisons; verify on the official schedules] Base-tier USDT perps:
  - **Binance 0.02% maker / 0.05% taker** (BNB discount may apply); USDC-margined perps reported at 0.00% / 0.04%.
  - **OKX 0.02% / 0.05%** (one source conflicts).
  - **Bybit 0.02% / 0.055%** (one outlier says 0.01% / 0.06%).
  - VIP tiers, token discounts and promotions change these. — [Bitsgap](https://bitsgap.com/blog/bybit-binance-okx-where-your-bot-pays-less-in-2026); [OneKey](https://onekey.so/blog/ecosystem/hyperliquid-cex-fee-comparison/); [OKX Learn](https://web3.okx.com/learn/crypto-futures-fees-compared)
- [PRESS] CME BTC futures basis (secondary aggregators; treat as indicative):
  - The annualized yield fell from **~15–20% to ~5%**; the 1-month basis went from ~17% a year earlier to ~5%, with some readings near **3%**.
  - By mid-2026 the 3-month basis was ~3%, below the **3.8%** 2-year Treasury yield.
  - CME open interest fell below $8B in Mar 2026 and to about **$7.2B in early Apr 2026** as the ETF basis trade unwound. — [The Block](https://www.theblock.co/news/business/2026-04-09-cme-bitcoin-futures-activity-slumps-to-14-month-low-as-basis-trade-unwind-drains-institutional-demand-396722); [crypto.news](https://crypto.news/binance-reclaimed-futures-dominance-cme-institutional-pullback/)
- [VENDOR] CME's own research notes the basis **briefly dipped below zero in Feb 2025** as price momentum reversed. — [CME Group OpenMarkets](https://www.cmegroup.com/openmarkets/equity-index/2025/Spot-ETFs-Give-Rise-to-Crypto-Basis-Trading.html)
- [PRAC] Trading costs matter for trend design:
  - Man: costs, shorting costs and liquidity limit the optimal breadth to ~10–15 coins, and faster models tolerate fewer coins.
  - Monash: short lookbacks lose much of their edge to rebalancing costs.
  - Hudson & Urquhart: breakeven costs for many rules exceed typical crypto costs.
  - Han et al.: costs plus liquidation turn many results insignificant. — [Man Group](https://www.man.com/insights/in-crypto-we-trend); [Monash CFS](https://www.monash.edu/business/mcfs/our-research/all-projects/investment-strategy/trend-following-strategies-for-crypto-investors); [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1); [AUT ACFR PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)
- [VENDOR/PRESS] **Venue risks specific to perps** (10 Oct 2025):
  - Hyperliquid's ADL force-closed profitable positions.
  - Binance's stablecoin de-peg and internal price distortions triggered additional forced sales. — [Galaxy Research](https://www.galaxy.com/insights/research/cryptos-flash-crash-liquidation-binance-adl-auto-deleveraging); [Cointelegraph](https://cointelegraph.com/news/19b-crypto-market-crash-leverage-china-tariffs)
- [PRESS, Korea] January 2024 coverage of Korea's Financial Services Commission (금융위원회):
  - Domestic brokers brokering **overseas-listed spot BTC ETFs** "may violate" the government's existing stance on virtual assets and the Capital Markets Act.
  - **Overseas BTC futures ETFs remained tradable**, and the FSC had no plan to regulate them.
  - KB Securities nonetheless suspended trading in 23 related names, and other brokers considered doing the same.
  - Current (Nov 2026) status was not verified. — [Metro Seoul](https://www.metroseoul.co.kr/article/20240114500169); [Blockmedia](https://www.blockmedia.co.kr/archives/445211)

### Inferences
These are my calculations from the sourced inputs.
- **Holding cost of 1x long exposure for a year:**

  | Instrument | Annual carry/fees | Notes |
  |---|---|---|
  | Binance perp, neutral premium | ≈ 10.95%/yr funding | Plus fees on entry/exit. Higher in bull froth (BIS: carry >40% p.a. at extremes); can turn negative in sell-offs. |
  | CME futures | ≈ 3–17%/yr (2025–26 basis) | Plus monthly roll and brokerage costs. Korean access uncertain. |
  | Spot | ≈ 0 carry | Only fees and spread, but no easy short and no capital efficiency. |

- **Trading-cost budget for a trend system on perps:**
  - Taker round trip = 0.10%. Assuming ~0.02% slippage per side (an unsourced assumption for liquid BTCUSDT at retail size), a round trip costs ≈ 0.14%.
  - At **20–50 round trips/yr** at 1x notional, that is ≈ **3–7%/yr**. Maker execution roughly halves it.
  - Intraday systems (hundreds of round trips) are only viable at maker fees or VIP tiers.
- **Asymmetry:** with funding positive most of the time, a long/short trend system on perps **pays carry on longs and earns it on shorts**.
  - A long-only trend system that is long ~50–60% of the time pays roughly 5.5–6.5%/yr at the baseline anchor, and more in bull phases, which is exactly when it is long.
  - That can consume a large share of a ~10–20%/yr gross trend edge.
  - Using **spot for the long leg and perps only for shorts or hedges** (or comparing the Binance USDC-margined fee schedule) are design options worth testing.
- Directional exposure via CME looks cheapest in carry terms when the basis is near 3–5%, but contract size, margin and broker access for Korean residents are unverified.

### Gaps
- **Measured slippage and market-impact figures** for BTCUSDT perps by order size were not retrieved; the 0.02%/side figure above is an assumption.
- Long-run (2019–2026) average Binance BTC funding was not retrieved; only the 2024–2025 "near baseline" characterization and the Q3-2025 "92% positive" figure were.
- CME Micro Bitcoin futures fees, margins and roll mechanics were not retrieved. Neither was whether Korean brokers can offer CME crypto futures to residents in 2026, or the Korean tax treatment of overseas futures and crypto gains (likely covered by another researcher).
- The official exchange fee pages were not fetched (blocked); fees came from third-party comparisons.
