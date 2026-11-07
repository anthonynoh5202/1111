# Profit Source Map: Who Actually Makes Money in BTC/USDT Perpetual & Futures Markets (as of 2026-11-07)

> **Method note (read first).** I did this research on 2026-11-07 using WebSearch only. WebFetch (full-page reading) was blocked in this session for `bis.org`, `hyperliquid.gitbook.io`, `cryptofundresearch.com` and `coingecko.com` because they are not on the network allowlist. So every figure below comes from search-engine summaries of the cited pages. I did not read any page in full myself. Re-check numbers against the primary page before quoting them as exact.
> **Tags:** [PRIMARY] = paper, official exchange page or primary data dashboard · [SECONDARY] = journalism or aggregator reporting someone else's data · [VENDOR] = firm with a commercial interest in the conclusion (marketing risk) · [LOW] = low-authority blog, affiliate or AI-style page · [ATTRIB?] = the number appeared in a summary that drew on several pages, and I could not tie it to one page with certainty · [OPINION] = commentary, not data.
> I read no earlier project documents (reports/, research/, other research_notes folders).

---

## Q1. Taxonomy of profit sources in BTC derivatives: returns, capacity, capital/infrastructure, skill, risks, and individual accessibility

### Takeaway
The best-evidenced profits in BTC perpetuals go to four groups:
1. **The venue**, through fees.
2. **Liquidity providers** that have rebate-tier and speed advantages.
3. **Carry/basis arbitrageurs** who supply leverage to trend-chasing retail. This carry has historically averaged more than 10% a year, but it fell close to or below risk-free rates in 2025–2026.
4. **Liquidation backstops.** Their returns are lumpy and come mostly from crashes.

Most retail money is lost in directional/discretionary trading and in copy-following. Time-series trend-following has academic support, but it is fragile once costs and leverage-driven liquidation are modelled.

(요약) 확실한 근거가 있는 수익은 네 곳으로 간다: ① 거래소(수수료) ② 수수료 리베이트와 속도 우위를 가진 시장조성자 ③ 개인의 레버리지 수요를 받아주는 베이시스·펀딩 차익거래자 — 다만 이 수익은 2025~2026년에 국채 금리 수준 이하로 줄었다 ④ 폭락 때 청산 물량을 받아주는 금고(HLP 등). 개인 대부분은 방향성 매매, 감(재량) 매매, 카피트레이딩에서 돈을 잃는다. 추세추종은 학술 근거가 있지만 수수료와 레버리지 청산을 넣으면 약해진다.

### Cited Findings

#### 1-A. Market making (MM) and maker rebates
- **How MMs earn.** MMs earn the bid-ask spread across very large numbers of trades. They also get exchange incentives: maker rebates, and paid liquidity agreements or reduced fees for quoting thin markets. Inventory losses offset part of the spread income. [SECONDARY explainer, undated] — [crypto.news](https://crypto.news/how-crypto-market-makers-work-firms-behind-every-trade/)
- **Binance USDⓈ-M Futures Liquidity Provider Program** (upgraded June 2025 and updated October 2025, per the search summary). [PRIMARY] — [Binance announcement](https://www.binance.com/en/support/announcement/detail/f5d3200b65104308b8349cee59a2296e)
  - Top maker rebates are **−0.005% on USDT-M perpetuals** and **−0.008% on USDC-M perpetuals**.
  - Qualification uses weekly share of maker volume (measured with and/or without BTC/ETH pairs) and/or quoting ranking. Self-trades are excluded.
  - From **2025-11-13**, qualified providers get an extra **0.05 bp** daily maker rebate on the BTCUSDT perpetual.
  - Binance can remove accounts at its discretion and changes requirements with about one week's notice. Applicants send proof of volume to mmprogram@binance.com.
- **Older eligibility thresholds.** An older Binance FAQ cited 30-day volume of 1,000 BTC on spot or 3,000 BTC on futures. These may be out of date. [PRIMARY, old] — [Binance FAQ](https://www.binance.com/ph/support/faq/b65fefd0fee84893ad946dc6f707dedc)
- **Third-party program list.** One list gives Binance Futures rebates of 0.005%–0.008% and the server location as AWS Tokyo. It carries an "may be out of date" disclaimer. — [hftbacktest docs](https://hftbacktest.readthedocs.io/en/latest/market_maker_program.html)
- **Hyperliquid maker rebates.** These are separate from volume tiers and depend on the account's share of total 14-day maker volume. [SECONDARY guides; official docs not fetchable] — [hyperliquidguide MM guide](https://hyperliquidguide.com/guides/trading/hyperliquid-market-making-guide); [Dwellir](https://www.dwellir.com/blog/hyperliquid-fees-explained)
  - Share >0.5% → −0.001%. Share >1.5% → −0.002%. Share >3.0% → −0.003%.
  - One guide puts the 0.5% threshold at roughly **$385M of credited maker volume in two weeks** (late October 2026).
- **Wintermute's reported profits (2021).** Reported 2021 figures are inconsistent: one account says more than $1B revenue with over 50% net margin on more than $1.5T volume; another says $582M profit. Neither is audited, and the metrics are not like-for-like. [SECONDARY/LOW; ATTRIB?] — [Bitget Academy](https://www.bitget.com/amp/academy/wintermute-crypto); [Protos](https://protos.com/crypto-market-maker-wintermute-bears-eery-resemblance-to-alameda/)
  - Protos argues that crypto "market makers" run large operations beyond pure market making. — [Protos](https://protos.com/crypto-market-maker-wintermute-bears-eery-resemblance-to-alameda/)
- **Wintermute's current direction.** Average daily volume reportedly fell from about $15B to about $10B year over year. The firm aims to raise non-crypto revenue from about 10% to more than 50%, and is committing $1B over 5 years to become an "AI-powered multi-asset trading house". The article date is not confirmed, likely 2026. [SECONDARY] — [BigGo Finance](https://finance.biggo.com/news/52371a1c-00df-4506-9838-6fac925ac3b2)
- **Wintermute on Hyperliquid.** On-chain tracking shows about **$222M cumulative profit** for Wintermute on Hyperliquid, with mostly short positions at the time. The snapshot is dated "November 7"; the year is not shown in the summary, plausibly 2026. This covers one venue only, not full P&L. [SECONDARY] — [Bloomingbit](https://en.bloomingbit.io/feed/news/123877)
- **HLP vault: the retail-accessible way to share MM and liquidation profits.** HLP is Hyperliquid's protocol vault for market making and liquidation backstop. [SECONDARY] — [CoinGecko](https://www.coingecko.com/learn/hyperliquid-hlp-vault-analysis)
  - During the **Oct 10–11, 2025** crash it earned about **$40–41.5M**, about **10% return to depositors that weekend**.
  - A **Jan 31, 2026** liquidation event added about **$15M**, a single-event return of about 5.8%.
  - CoinGecko estimates these two events are about **41% of HLP's all-time profit**.
- **HLP growth after the JELLY incident.** A headline says HLP grew by about $250M in the 2 months after the JELLY incident (spring 2025). Title-level evidence only. [LOW] — [repost of news headline](https://rss.boorghani.com/?p=316550)
- **HLP loss incidents.**
  - **JELLY squeeze (Mar 26, 2025).** HLP held about a **$12M unrealized loss**. Validators then delisted JELLY and settled it at a price that turned the position into about a $700K profit. Critics call this the "validator put" (governance risk). [SECONDARY] — [FXStreet](https://fxstreet.com/amp/cryptocurrencies/news/hyperliquid-escapes-liquidity-crisis-following-jellyjelly-short-squeeze-delists-token-202503262225); [Arkham](https://info.arkm.com/research/jellyjelly-exploit-on-hyperliquid); [Blockworks](https://blockworks.co/news/hyperliquid-decentralization-validator-put)
  - **ETH whale liquidation (March 2025).** A nine-figure ETH whale liquidation cost HLP about **$4M**. Hyperliquid then cut maximum leverage to **40x for BTC and 25x for ETH**. — [The Defiant](https://thedefiant.io/whale-s-nine-figure-eth-liquidation-costs-hyperliquid-usd4-million)
- **No HLP APR history found.** I found no reliable historical APR series for HLP. One guide deliberately declines to quote historical returns. — [perp.wiki](https://perp.wiki/learn/hlp-vault-guide)

#### 1-B. HFT / latency and cross-exchange arbitrage
- **Where the servers are.** Binance, Bitget, KuCoin, HTX, CoinEx, MEXC and Hyperliquid concentrate critical infrastructure in **AWS Tokyo**. Binance sells no formal colocation, so hosting in the same AWS region is the closest substitute. [VENDOR] — [Zenlayer](https://cloud.zenlayer.com/blog/crypto-trading-latency-tokyo)
  - Server location significantly affects bot latency on Binance. — [Tsybko Substack](https://viktoriatsybko.substack.com/p/an-analysis-of-binance-exchange-across)
- **B2C2 CEO on the latency race.** [SECONDARY/OPINION] — [Yahoo News](https://news.yahoo.com/crypto-latency-arms-race-crypto-094026830.html)
  - He calls same-cloud placement "unsanctioned colocation".
  - He argues that **8 ms** can separate a liquidity provider that invests "tens of millions" in speed from one priced out of the market. This is a TradFi-derived argument.
  - He says winner-takes-all latency races do not improve liquidity.
- **Glassnode latency monitor.** Hyperliquid fills measured from AWS Tokyo had a median of **884 ms** (120 samples, March 2026). Glassnode research says Tokyo-located Hyperliquid traders get about a **200 ms edge**. [PRIMARY data vendor] — [Glassnode fill latency](https://hyperlatency.glassnode.com/fill-latency); [Pulse summary of Glassnode research](https://www.pulse.bot/crypto/news/hyperliquid-traders-in-tokyo-get-200-millisecond-edge-glassnode-research-shows-a900dcdd-3ce2-45e0-874f-b00bbd348c1b/)
- **"Fundamentals of Perpetual Futures"** by He, Manela, Ross & von Wachter (arXiv 2212.06888, v6 August 2024). [PRIMARY] — [arXiv](https://arxiv.org/abs/2212.06888)
  - Crypto perpetual prices deviate from no-arbitrage values more than FX markets do. The deviations move together across coins and have **diminished over time**.
  - For Bitcoin, the implied arbitrage has a **Sharpe ratio of about 1.8 with high retail trading costs**, versus **up to about 3.5 for highly active market makers** who pay no such fees.
- **Kimchi premium (Korea vs offshore price gap).**
  - Capital controls are asymmetric: it is easier to move money into Korea than out. So arbitrage works mainly in one direction and the premium can stay positive on average (Lehar & Stauffer, SNB conference paper, 2019). [PRIMARY academic] — [SNB PDF](https://snb.ch/dam/jcr:474400ba-255b-49a4-b2b8-5e3626719730/sem_2019_05_31_lehar.n.pdf)
  - Small overseas remittance agencies may send at most **$10,000 per transaction per individual**. [SECONDARY] — [CNBC via NBC LA](https://www.nbclosangeles.com/news/business/money-report/in-the-wake-of-bitcoins-new-highs-south-koreas-kimchi-premium-is-in-the-spotlight-again/3378619)
  - In April 2021, Korean authorities said they would tighten rules on premium arbitrage. Local investors who buy large amounts from foreign exchanges for arbitrage may be punished under capital-control rules. [SECONDARY, 2021] — [FXStreet](https://fxstreet.com/cryptocurrencies/news/south-korea-to-tighten-regulations-on-crypto-transactions-profiting-from-kimchi-premium-202104200222)
- **Kimchi premium levels.** About **9.7% in February 2025**, a 10-month high. — [The Block](https://theblock.co/post/338432/south-koreas-bitcoin-kimchi-premium-soars-to-10-month-high-amid-trump-led-tariff-war-concerns)
  - In 2026 the premium was reportedly **negative on 137 of 244 days**, the first year in which discounts outnumbered premiums. [LOW; unverified] — [HackerNoon](https://hackernoon.com/korea-rebuilt-its-crypto-market-in-a-year-one-typo-showed-what-it-forgot)

#### 1-C. Funding-rate and basis (cash-and-carry) trades
- **BIS Working Paper 1087, "Crypto carry"** (Schmeling, Schrimpf, Todorov; April 2023, revised October 2025). [PRIMARY] — [BIS](https://www.bis.org/publ/work1087.htm)
  - The futures–spot carry **averages above 10% per year**, at times **up to 60% per year**, and varies strongly over time.
  - It is explained mainly by convenience yields: smaller, **trend-chasing investors seeking leveraged exposure**, plus a scarcity of arbitrage capital.
  - **High carry predicts future price crashes.**
- **Funding compression, 2024–2026.** [SECONDARY; underlying dataset not identified] — [UseTheBitcoin](https://usethebitcoin.com/news/ethena-equity-perpetuals-usde-yield/)
  - Bitcoin open-interest-weighted funding averaged **11.0% annualized in 2024**, **4.9% in 2025**, and **2.2% year to date to Aug 11, 2026**.
  - Over the same window, median **equity-perp funding was 13.9% vs BTC 3.9%**.
  - Ethena announced on **Aug 28, 2026** that it would extend its basis trade into equity perpetuals.
- **Ethena sUSDe** (the largest packaged funding/basis product). [PRIMARY data aggregator] — [Aavescan](https://aavescan.com/rates/ethena-susde)
  - Supply APY: **5.13% (Nov 3, 2026)**, 4.83% (Oct 1, 2026), 3.97% (Aug 1, 2026).
  - Sources conflict. One April 2026 figure (9.4%) is far above the rest.
- **sUSDe backing mix.** By spring 2026, only about **13% of USDe backing was in the crypto basis trade**. About 57% was in liquid stablecoins and about 29% in DeFi lending. The yield is now driven mainly by DeFi lending, with funding secondary. [SECONDARY; ATTRIB?] — [Blockworks](https://blockworks.com/newsletter/the-breakdown/issue/post_999b16ee-0fe0-4631-a1d0-2aa15a1d18a7); [CryptoTether](https://cryptotether.com/articles/why-ethena-susde-yield-is/)
- **CME basis, gross vs net.** [SECONDARY citing Galaxy] — [Startup Fortune](https://startupfortune.com/hedge-funds-dump-bitcoin-etfs-as-the-futures-basis-trade-dries-up/)
  - About **25% annualized** during 2024 surges, about **10% by May 2025**.
  - Galaxy: the front-month basis averaged **7.9% annualized** in the 30 days before BTC's all-time high, 3.9 percentage points above 3-month T-bills.
  - But after fees, roll costs and margin, the trade returned only **about 1.5 percentage points above cash**.
- **CME basis in 2026.**
  - **Aug 10, 2026:** the 3-month annualized basis was **about 3%**, **below the roughly 3.8% two-year US Treasury yield**. [SECONDARY] — [BigGo Finance](https://finance.biggo.com/news/9c11c1e7-4988-4ad7-998f-7d4f8a51f6ad)
  - Hedge funds on CME **flipped net long**, a rare shift (CryptoQuant's Ki Young Ju, August 2026). — [CoinDesk](https://www.coindesk.com/markets/2026/08/10/a-rare-cme-shift-hedge-funds-abandon-structural-shorts-to-bet-on-a-bitcoin-rally)
  - **Apr 9, 2026:** CME bitcoin futures activity hit a 14-month low as the basis-trade unwind drained institutional demand. Basis was about 5% vs about 4.5% risk-free around then. [ATTRIB?] — [The Block](https://www.theblock.co/news/business/2026-04-09-cme-bitcoin-futures-activity-slumps-to-14-month-low-as-basis-trade-unwind-drains-institutional-demand-396722)
- **Hedge funds leaving the ETF basis trade.** Nine firms pulled about **$5.4B** from bitcoin ETFs since September 2025. Brevan Howard's IBIT stake fell from about $2.6B to about $255M, and Farallon cut its holding by 69%. — [Startup Fortune](https://startupfortune.com/hedge-funds-dump-bitcoin-etfs-as-the-futures-basis-trade-dries-up/)
- **Nov 1, 2026 headline.** A market headline asks whether BTC at about $77,370 can hold "without a futures premium" (flat curve). Title-level evidence only. [SECONDARY] — [CryptoTicker](https://cryptoticker.io/en/bitcoin-price-prediction-futures-curve-no-premium-1-november-2026/)
- **Tail risk for hedged traders: auto-deleveraging (ADL).** On Oct 10, 2025, ADL force-closed *profitable* positions when insurance funds ran short. This can hit the short leg of basis/hedged traders. Hyperliquid's ADL reportedly closed about **$2.1B of positions in 12 minutes**. [SECONDARY; ATTRIB?] — [edgeX news](https://pro.edgex.exchange/en-US/news/article/crypto-auto-deleveraging-risks); [insights4vc](https://insights4vc.substack.com/p/inside-the-19b-flash-crash)

#### 1-D. Liquidation-cascade trading and liquidation backstops
- **Oct 10–11, 2025 crash.** [SECONDARY; ATTRIB? for exact splits] — [FTI Consulting](https://www.fticonsulting.com/insights/articles/crypto-crash-october-2025-leverage-met-liquidity); [TokenPost](https://www.tokenpost.com/news/investing/29166); [insights4vc](https://insights4vc.substack.com/p/inside-the-19b-flash-crash)
  - About **$19B liquidated in about 24 hours**; estimates range from $19.16B to $19.3B. About **1.6M accounts** were affected.
  - Hyperliquid accounted for about $10–10.25B, roughly 53% of the total. It ran its first ADL in more than 2 years.
  - The trigger was a reported 100% US tariff on Chinese imports hitting crowded longs.
- **Who won in that crash.** HLP made about $40M (see 1-A), and Hyperliquid took on no bad debt (per CoinGecko). — [CoinGecko](https://www.coingecko.com/learn/hyperliquid-hlp-vault-analysis)
- **CoinGlass 2025 annual figures.** [SECONDARY citing CoinGlass] — [Bitcoinist](https://bitcoinist.com/crypto-liquidations-150-billion-2025-coinglass/); [CryptoRank](https://cryptorank.io/news/feed/9c7b5-crypto-news-86-trillion-traded-in-crypto-derivatives-in-2025)
  - Total liquidations were about **$150B** in 2025 (one citation: $154.64B), **about 85–90% from longs**, averaging about $400–500M per day.
  - Total crypto derivatives volume was **$86T** in 2025, about $265B per day.
- **Data quality caveats.**
  - Hyperliquid's co-founder claims CEX liquidation totals may be under-reported by up to 100x. He is an interested party. — [ForkLog](https://forklog.com/en/hyperliquid-co-founder-says-cex-liquidation-totals-may-be-underreported-by-up-to-100x/)
  - An academic study found Binance reported inaccurate data for **more than 50% of liquidations** in its dataset. — [arXiv 2101.01261](https://arxiv.org/pdf/2101.01261)
- **No measured returns for individual cascade traders.** I found no source that measures the returns of individuals who systematically trade liquidation cascades, for example by placing resting bids far below market or fading cascades. See Gaps.

#### 1-E. Directional trend / momentum (systematic)
- **Han, Kang & Ryu: crypto momentum under realistic assumptions.** [PRIMARY academic] — [AUT/ACFR PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf)
  - They account for transaction costs and for daily price swings, which liquidate leveraged momentum portfolios. Once they do, many momentum portfolios are liquidated, and many statistically significant returns become insignificant.
  - **Time-series momentum (TSMOM) evidence is "strong"; cross-sectional momentum evidence is weak.**
  - TSMOM profits are **concentrated in bull markets**. Buying after market falls yields negative profits in most cases.
- **Intraday momentum.** Intraday time-series momentum exists in bitcoin (Shen, Urquhart & Wang). The excerpt does not address costs. [PRIMARY academic] — [Univ. of Reading PDF](https://reading-9.eprints-hosting.org/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf)
- **Return predictors.** A bitcoin return-predictor study finds TSMOM, together with economic-policy and financial uncertainty, beats other predictors in-sample, out-of-sample and in asset allocation. The result holds under 0.1–0.3% transaction costs. [PRIMARY academic; ATTRIB? to this link] — [Eur. J. Finance](https://informahealthcare.com/doi/abs/10.1080/1351847X.2020.1835685)
- **2025 regime check.**
  - BTC fell **6.3% in calendar 2025**. — [CFR](https://cryptofundresearch.com/crypto-hedge-fund-performance/)
  - Directional crypto hedge funds lost about **2.5%** through November 2025, while market-neutral funds gained about **14.4%** (CoinEdition via TV-Hub; partial year). — [TV-Hub](https://www.tv-hub.org/guide/market-neutral-strategy-crypto)

#### 1-F. Discretionary directional trading
- See Q2 for the outcome data: most retail wallets lose.
- **Vendor "smart money" claim (June 2026).** Across 247,000+ Hyperliquid wallets, a "disciplined" cohort returned +50.0% over 6 months, vs −7.3% for the average qualified trader and −25.3% for BTC. It is self-reported, backtested and not audited. [VENDOR; ATTRIB?] — [DropsTab research](https://news.dropstab.com/research/hyperliquid-smart-money)

#### 1-G. Volatility / options selling (adjacent to perps)
- **Anchorage Digital covered-call study** (David Lawant, 2026). [VENDOR research — firm sells institutional products] — [Anchorage](https://www.anchorage.com/research/synthetic-yield-on-bitcoin-implementation-discipline-and-performance-boundaries-of-systematic-covered-call-writing)
  - It ran more than 37,000 backtests, hourly, on the Deribit implied-volatility surface, **October 2021–April 2026**.
  - BTC's *upside* volatility risk premium averaged about **2–3x that of SPY/QQQ**. This compares 25-delta call implied volatility with realized upside volatility over the following 21 trading days.
  - A 20-delta, 30-day covered call yielded **+5.5% net over the last 12 months** of the study, while BTC spot fell 19.4%.
  - Unfiltered over the **full period it was roughly flat**: −0.5% total, −0.1% annualized. Trend and implied-volatility filters improved results.
  - Conclusion: "fundamentally an active management problem". Upside is capped in rallies.
- **Illiquidity premium in Deribit BTC options (2020–2024).** Daily risk-adjusted alpha of call contracts was **0.17%**. [PRIMARY academic] — [Atanasova PDF](https://acfr.aut.ac.nz/__data/assets/pdf_file/0006/969378/950002_Atanasova_Illiquidity-Premium-and-Crypto-Option-Returns.pdf)

#### 1-H. Copy trading (lead traders and followers)
- **YieldFund 90-day multi-exchange study** (2025; about 100,000 copy outcomes on Binance, Bybit and MEXC). [VENDOR; not peer reviewed; original data not inspected] — [YieldFund](https://www.yieldfund.com/news/is-copy-trading-profitable-a-90-day-multi-exchange-study); repeated by [KuCoin blog](https://www.kucoin.com/blog/is-crypto-copytrading-profitable-in-2026) [VENDOR/competitor]
  - **97.04% of lead traders were profitable on their own accounts**, but **only 43.61% generated positive returns for their followers**.
  - Overall copier win rate was **48.48%**.
  - Follower win rate by platform: Binance 66.50%, Bybit 43.65%, MEXC 57.79%.
- **Apesteguia, Oechssler & Weidenholzer** (*Management Science*, 2020; lab experiment, not crypto-specific). Copy trading **increases risk-taking and reduces ex-ante welfare**. Cited secondhand. — [hyprswarm blog](https://hyprswarm.pages.dev/blog/is-copy-trading-profitable/)
- **Why followers underperform.**
  - Leaderboards show survivorship bias: blown-up traders disappear from view. — [Stax](https://staxinvesting.com/blog/is-copy-trading-profitable-the-honest-risk-picture)
  - Followers lose from delayed entry, slippage and latency, sizing mismatch, and fees. [ATTRIB?] — [Arkham research](https://info.arkm.com/research/crypto-copy-trading-what-is-it-and-how-to-do-it); [KuCoin blog](https://www.kucoin.com/blog/is-crypto-copytrading-profitable-in-2026)

#### 1-I. The exchange / venue side ("the house")
- **Hyperliquid fees** (DefiLlama, trailing year as of late 2026). [PRIMARY data aggregator] — [DefiLlama](https://defillama.com/protocol/hyperliquid)
  - Annualized **fees $899.02M** and **revenue $683.66M**.
  - Monthly fees ran $58–77M in early 2026 and about $74.19M in September 2026.
- **Hyperliquid revenue.**
  - 2026 year-to-date revenue was **$429.04M as of Sep 15, 2026**, ranked #1 among crypto protocols (CoinGecko data). — [KuCoin News](https://www.kucoin.com/news/flash/hyperliquid-leads-2026-crypto-revenue-with-429m)
  - 2025 revenue was reportedly about $844M, with about 73% of on-chain derivatives share. [LOW] — [bex.co](https://bex.co/blog/2026/01/10/hyperliquid-844m-revenue-perpetual-dex-dominance)
  - Almost all protocol revenue goes to HYPE buybacks. — [Datawallet](https://www.datawallet.com/crypto/hyperliquid-statistics)
- **Hyperliquid's share of open interest.** Glassnode says Hyperliquid is roughly **16% of global open interest**. Undated summary. — [Glassnode research](https://research.glassnode.com/liquidation-heatmaps/)
- **Binance and other big CEXs.** Binance does not publish derivatives revenue, and I found no reliable estimate (see Gaps). Industry derivatives volume was $86T in 2025. — [CryptoRank](https://cryptorank.io/news/feed/9c7b5-crypto-news-86-trillion-traded-in-crypto-derivatives-in-2025)

#### 1-J. Access constraints for a Korean individual (cross-cutting)
- **Domestic futures ban.** Korea still prohibits domestic crypto futures. Offshore platforms historically attracted Korean users by offering high-leverage perpetuals. [SECONDARY; ATTRIB?] — [Cryptonews](https://cryptonews.com/news/south-korea-crypto-regulation-exchange-ban/); [eCryptoGraph](https://ecryptograph.com/2026/10/13/south-koreas-fiu-blocks-27-unregistered-crypto-exchange-websites/)
- **FIU web blocks, Oct 13, 2026.** [SECONDARY; no official FIU press release found] — [eCryptoGraph](https://ecryptograph.com/2026/10/13/south-koreas-fiu-blocks-27-unregistered-crypto-exchange-websites/); [Cryptonews](https://cryptonews.com/news/south-korea-crypto-regulation-exchange-ban/)
  - The FIU ordered **web blocks on 27 unregistered offshore exchanges**, including KuCoin, MEXC, Phemex, BingX and BitMart.
  - It referred **44 unregistered operators to investigators**, and reportedly will seek blocks without waiting for court rulings.
  - Binance, Bybit and OKX were **not named in that round**, per the report.
- **App-store blocks.** Google Play restricted 17 unregistered platforms in **March 2025** and began blocking unregistered overseas exchange apps for Korean users from **Jan 28, 2026**. Only 27 domestic platforms are FIU-registered; Binance, Bybit and OKX remain unregistered. — [Yahoo Finance](https://finance.yahoo.com/news/south-korea-tightens-crypto-access-160944358.html); [WhereLegalCrypto–Binance](https://wherelegalcrypto.com/exchanges/binance/south-korea/) [LOW/affiliate]; [WhereLegalCrypto–Bybit](https://wherelegalcrypto.com/exchanges/bybit/south-korea/) [LOW/affiliate]
- **Hyperliquid.** It is an on-chain venue marketed as "No Gas, No KYC". [SECONDARY] — [hyperliquidguide](https://hyperliquidguide.com/guides/fees/fees-explained)
- **EU comparison.** In February 2026, ESMA said crypto perpetuals likely fall under CFD rules (MiFID II). That implies retail leverage caps and mandatory "% of retail accounts that lose money" warnings. One comparison says EU-licensed venues such as Kraken and Coinbase cap leverage at 10x. — [Finance Magnates](https://datalab.financemagnates.com/compliance-insights/esma-says-crypto-perpetual-futures-are-cfds-targeting-a-60-trillion-market); [CryptoTicker EU comparison](https://cryptoticker.io/en/crypto-futures-exchanges-eu/)

### Inferences

**Profit source map.** This is my synthesis of the cited findings above. Every number is taken from those findings; the judgments in the last column are my inferences.

| Profit source | Who reliably captures it | Size evidence (dated) | Capital / infrastructure | Skill | Key risks | Realistic for a Korean individual (₩1M to tens of ₩M)? |
|---|---|---|---|---|---|---|
| Venue fees ("the house") | Exchanges | Hyperliquid ≈$899M annualized fees / ≈$684M revenue (trailing year, late 2026) | Licensed exchange | n/a | Regulation, hacks | No. This is the structural winner. |
| Market making + rebates | Professional MMs (Wintermute ≈$222M cumulative profit on Hyperliquid); HLP | Binance LP program rebates −0.005% / −0.008% (2025). Hyperliquid rebates −0.001% to −0.003%, which need ≥0.5% of maker volume (≈$385M per 2 weeks, October 2026) | Tokyo-region servers, multi-venue capital, quoting engine | Very high (adverse selection, inventory) | Toxic flow, tail events, rules changed at the exchange's discretion | Directly: no. Indirectly, an HLP deposit gives event-driven gains (≈10% over the October 2025 weekend; +5.8% on Jan 31, 2026), with governance and tail risk. No APR series exists. |
| HFT / latency / cross-venue arbitrage | HFT firms | Same BTC arbitrage: Sharpe ≈3.5 on MM fees vs ≈1.8 on retail fees (paper v6, 2024); mispricings shrinking over time | Millisecond-level infrastructure; "tens of millions" in speed tech (B2C2 view) | Very high | Arms race, venue risk | No. Kimchi-premium arbitrage is limited by FX rules ($10k per transaction via small remitters) and carries legal risk. The premium was reportedly mostly negative in 2026 (unverified). |
| Funding / basis carry | Basis funds, Ethena, anyone with capital | Historical average >10% p.a., up to 60% (BIS, revised 2025). BTC funding 11.0% (2024) → 4.9% (2025) → 2.2% (2026 year to Aug 11). CME ≈3% (August 2026) vs 2-year UST ≈3.8%. Galaxy net ≈+1.5 pp over cash | ≈1.3–2× notional in capital; API; two legs or venues | Moderate (operations, margin management) | ADL hitting the hedged leg (October 2025); exchange counterparty risk; funding turning negative; crashes coming right after high-carry periods | Technically yes. In 2026, after fees, it earns about the risk-free rate or less. It is attractive only in high-funding regimes (leverage booms), which BIS links to later crashes. |
| Liquidation backstop / cascade trading | HLP, liquidators, insurance funds | HLP ≈$40M (Oct 10–11, 2025) and ≈$15M (Jan 31, 2026); these two events ≈41% of HLP's all-time profit | Pooled capital | Low as a depositor | Lumpy returns, manipulation (JELLY), governance intervention | Only via a vault. No evidence found on do-it-yourself cascade trading. |
| Trend / momentum (systematic directional) | Some systematic funds | TSMOM evidence "strong" in academic work but fragile after costs and liquidation; concentrated in bull markets | Low (API bot, data) | Moderate (research discipline) | Overfitting, regime change, leverage-driven liquidation | Accessible, but the edge is uncertain. The BitMEX study's margin math implies about ≤3x long / ≤5x short to keep the daily margin-call probability near 1%. Turnover must stay low because of fee drag (see Q3). |
| Discretionary directional | A minority, skewed toward large accounts | ≈14–17% of Hyperliquid wallets profitable per 30-day window (2024–25). Among $10–100M accounts, 85.7% profitable | Low | High | Behavioral errors, leverage | Accessible, but base rates are poor. |
| Options / volatility selling | Volatility sellers with filters | BTC upside volatility risk premium ≈2–3× equities. Covered call ≈flat unfiltered over October 2021–April 2026; +5.5% over the last 12 months | Options venue (Deribit), BTC collateral | Moderate to high | Gap and rally risk, capped upside | Partly. Venue access and legality for Korean residents are not established. |
| Copy trading as a follower | — | Only 43.6% of lead traders made money for followers; follower win rate ≈48.5% (vendor data, 2025) | Low | Low | Survivorship bias, entry lag, profit share | Accessible, but the evidence is weak or negative. |
| Copy trading as a lead trader | Lead traders (profit share) | 97% of leads profitable on their own accounts (vendor data) | A track record | Varies | Reputation | Possible. No data found on profit-share income. |

- **Structural zero-sum identity (inference).** Before costs, perpetual P&L between longs and shorts sums to zero, and funding is a transfer between them. Fees net of maker rebates, plus liquidation penalties, flow from traders to the venue, the makers and the backstop. So traders *as a group* must lose roughly what the venue and backstops earn: on Hyperliquid alone, about $0.9B of fees per year (late 2026 run-rate) plus HLP's trading profit. An individual can win only by taking money from other traders after paying "the house".
- **Carry and retail losses share one source (inference).** BIS attributes carry to small trend-chasers' demand for leverage. That same demand produces the liquidations, about 85–90% of them on longs in 2025. So carry harvesters, MMs and backstops are largely the *counterparties* to retail leverage. When retail leverage demand fell (2025–26), carry compressed: funding went from 11.0% to 2.2%, and CME basis fell to about 3%.
- **Fee and rebate tiers sort participants by scale (inference).** At ₩1M to tens of millions of won, an individual cannot reach Binance's LP program or Hyperliquid's rebate tiers (≥0.5% of all maker volume). The professional "durable" edges therefore lie outside an individual's direct reach. What remains reachable:
  - (a) low-turnover, low-leverage systematic directional trading, where the evidence is mixed;
  - (b) opportunistic carry, only when funding is high;
  - (c) passive participation in a vault such as HLP, with tail and governance risk;
  - (d) not trading.
- **Capacity (inference).**
  - Carry capacity is limited by retail leverage demand. Arbitrage capital inflows (ETFs, Ethena) compress it; He et al. find mispricings shrank over time, and BIS links carry to scarce arbitrage capital.
  - MM capacity is limited by order flow; Wintermute's daily volume fell from about $15B to about $10B.
  - Backstop profits are small relative to flows: about $40M on a $19B liquidation day.
  - Directional trading has the largest capacity ($86T derivatives volume in 2025) but no structural edge.

### Gaps
- **Unfetched primary pages.** I could not read the BIS PDF, official Hyperliquid docs, the CFR database or CoinGecko pages in full (network allowlist). All numbers rely on search summaries.
- **HLP data.** No historical HLP APR series, TVL or withdrawal lock-up terms were found.
- **Cascade trading.** No measured returns for individuals trading liquidation cascades.
- **MM economics.** No independent, audited MM profitability data for BTC perpetuals (split into spread vs rebates vs directional). Wintermute's figures are unaudited and inconsistent.
- **Execution costs.** No current BTC perpetual bid-ask spread, depth or slippage figures (Kaiko, Amberdata) were retrieved.
- **Korean legal and tax status.** The legal position of a Korean resident who uses Hyperliquid, Binance or Bybit (beyond app and web blocks) is not established from sources here. Neither is the Korean tax treatment of futures P&L. Other researchers should cover both.
- **Counterparty risk.** Exchange counterparty-risk events (hacks, insolvencies), which are central to carry trades on centralized exchanges, were not researched in this pass.
- **Copy-trading lead income.** No data on lead traders' profit-share levels or income.
- **CEX revenue.** No revenue figures for Binance, Bybit or OKX derivatives.
- **Possible new anomaly.** A July 2026 arXiv paper, "The Quarter-Hour Effect: Periodic Algorithmic Trading and Return Predictability in Cryptocurrency Futures", surfaced. I saw the title only; it is a possible microstructure anomaly to check. — https://arxiv.org/pdf/2607.09426

---

## Q2. Who are the net winners and losers? Evidence on the profit distribution of crypto derivatives traders

### Takeaway
In every dataset found, only a minority of retail derivatives traders are profitable over a given window:
- About **14–17% of Hyperliquid wallets** over 30-day windows (2024–2025).
- In EU retail CFDs, **74–89% of accounts lose**.
- **97% of persistent Brazilian futures day traders lost money.**

Winners are concentrated in large accounts, market makers, liquidation backstops and the venue. Losers are concentrated in small, high-leverage, mostly long accounts; liquidated BitMEX traders averaged about 60x leverage. Copy-trading followers do much worse than the lead traders they copy.

(요약) 어떤 자료를 봐도 개인 파생상품 트레이더 중 돈을 버는 사람은 소수다(하이퍼리퀴드 30일 기준 약 14~17%). 돈은 큰 계좌, 시장조성자, 청산 금고, 거래소로 모인다. 잃는 쪽은 작은 계좌, 높은 레버리지, 주로 롱 포지션이다(BitMEX에서 청산된 사람의 평균 레버리지는 약 60배). 카피트레이딩을 따라 한 사람은 리더보다 훨씬 성과가 나쁘다.

### Cited Findings
- **Envy Protocol sample** (Medium): 10,000 random Hyperliquid wallets over 30 days, November 2024 data. [VENDOR/protocol-affiliated author; not peer reviewed] — [Medium/Envy Protocol](https://medium.com/@envyprotocol/i-analyzed-10-000-hyperliquid-traders-the-results-are-brutal-a29adcca8c2a)
  - About **16.5% were profitable** and about 9.7% broke even. **27.2% lost more than 85% of their capital.**
  - **Median PnL was −$67.** **40.6% stopped trading entirely within 30 days.**
  - Profitability **rises with account size**: **85.7% of $10M–$100M accounts were profitable.**
- **Hyperdash-based samples.** In June 2025, **166 of 1,000 traders (16.6%)** were profitable. Another snapshot gives about **14%** ("86% losing"). [SECONDARY] — [The Coin Republic](https://www.thecoinrepublic.com/2025/06/16/hyperliquid-crypto-only-166-of-1000-traders-profitable-whats-going-on/); [BeInCrypto](https://beincrypto.com/hyperliquid-traders-profitability/)
  - The same summaries also contained mutually inconsistent figures: "$5,600/day average loss" and "170 traders earned >$10M" within a 1,000-trader sample. I excluded these as unreliable.
- **Hyperdash cohort data (2026 reporting).** [SECONDARY; ATTRIB?] — [CryptoNews.net](https://cryptonews.net/news/analytics/33536508/); [Hyperdash learn page](https://hyperdash.com/learn/best-tools-trading-hyperliquid)
  - Of 82,586 active wallets tracked, **only 230 have more than $1M cumulative profit.**
  - A cohort table lists 58,848 unprofitable wallets. The definition is unclear; on an all-time basis it would imply about 71% unprofitable.
  - The ">$1M profit" cohort held about $2.82B in longs vs $2.88B in shorts, roughly flat, while smaller cohorts were more bullish.
- **Size is not skill.** A large-equity "whale" wallet can still show −$600K all-time PnL. — [CoinMarketMan](https://coinmarketman.com/blog/why-a-traders-track-record-beats-their-wallet-size-on-hyperliquid--en/)
- **Professional winners on the same venue.** Wintermute shows about $222M cumulative profit on Hyperliquid — [Bloomingbit](https://en.bloomingbit.io/feed/news/123877). HLP profits from liquidation events — [CoinGecko](https://www.coingecko.com/learn/hyperliquid-hlp-vault-analysis).
- **BitMEX evidence** (Cheng, Deng, Wang & Yu, *Applied Economics* 2021; arXiv 2102.04591). [PRIMARY] — [arXiv PDF](https://arxiv.org/pdf/2102.04591)
  - Daily forced liquidations were **3.51% (longs) and 1.89% (shorts) of outstanding perpetual futures**.
  - **Liquidated investors used average leverage of about 60x.**
  - To bring the daily margin-call probability down to 1%, margin would have to be about **33% (3x) for longs** and **20% (5x) for shorts**, versus BitMEX's 1%.
- **"Perpetual Futures and Basis Risk: Evidence from Cryptocurrency"** (AEA 2026, preliminary; BitMEX, Deribit and Kraken trade and liquidation data). Perpetuals show frequent liquidations throughout, consistent with **higher-risk traders preferring perpetuals**. [PRIMARY, preliminary] — [AEA program](https://www.aeaweb.org/conference/2026/program/paper/ByyFEfr4)
- **Who gets liquidated.** In 2025, about $150B was liquidated, about **85–90% of it longs** (CoinGlass). — [Bitcoinist](https://bitcoinist.com/crypto-liquidations-150-billion-2025-coinglass/). On Oct 10–11, 2025, about 1.6M accounts were liquidated in about 24 hours. [ATTRIB?] — [TokenPost](https://www.tokenpost.com/news/investing/29166); [FTI Consulting](https://www.fticonsulting.com/insights/articles/crypto-crash-october-2025-leverage-met-liquidity)
- **How close liquidation is.** On Hyperliquid, the headline 40x applies only to small positions. For an asset with 1.25% maintenance margin, a 20x long is liquidated about **3.75%** below entry and a 40x long about **1.25%** below. These are illustrative calculations, not measured outcomes. [SECONDARY; ATTRIB?] — [CoinMarketMan liquidations guide](https://coinmarketman.com/blog/hyperliquid-liquidations-explained--en/); [Buildix](https://www.buildix.trade/blog/how-hyperliquid-liquidations-work-margin-hlp-adl-2026)
- **Copy trading.** 97% of lead traders were profitable for themselves, but only 43.6% for their followers (vendor data, 2025; see 1-H). — [YieldFund](https://www.yieldfund.com/news/is-copy-trading-profitable-a-90-day-multi-exchange-study)
- **Base rates from other leveraged retail markets.**
  - **EU/UK CFDs:** 74–89% of retail accounts lose money (ESMA 2018 review). ESMA now treats crypto perpetuals as likely CFDs (February 2026). — [Finance Magnates](https://datalab.financemagnates.com/compliance-insights/esma-says-crypto-perpetual-futures-are-cfds-targeting-a-60-trillion-market)
  - **Brazil:** 97% of individuals who day-traded index futures for more than 300 sessions lost money, and only about 1% earned more than minimum wage (Chague, De-Losso & Giovannetti, via a secondary summary). [SECONDARY; ATTRIB?] — [10pmtrader](https://10pmtrader.com/why-retail-traders-lose-money/); [RoR Labs](https://rorlabs.io/options-futures-trading-money-loss-risk/)
  - **Crypto perpetuals opinion piece** (CoinDesk, Jul 1, 2026): the author's dataset of crypto perpetual activity shows retail loss rates in the same 74–89% range. No exact number was disclosed. [OPINION] — [CoinDesk](https://www.coindesk.com/opinion/2026/07/01/europe-is-closing-the-door-on-offshore-crypto-but-it-s-leaving-the-riskiest-window-open)
  - **Spot bitcoin, for context.** BIS Bulletin No 69 (February 2023) estimated that **about 73–81% of retail investors likely lost money** on bitcoin purchases (app-based spot buying, 2015–2022). The statistic surfaced in search summaries. bis.org was not reachable in this session, so I supplied the bulletin URL from prior knowledge. — [BIS Bulletin 69](https://www.bis.org/publ/bisbull69.htm)
- **Professional funds also struggled in 2025** (CFR database; 84 reporting funds in the strategy breakdown). [PRIMARY database, self-reported data] — [CFR](https://cryptofundresearch.com/crypto-hedge-fund-performance/)
  - The average crypto hedge fund returned **−7.2%** (median −5.2%). **Only 37% posted positive returns.**
  - Quant funds averaged **+0.4%**, with 58% positive. BTC fell 6.3%.
  - Marketing-style statistics pages claim +36% average and +48% for quant funds in 2025 but disclose no methodology. [MARKETING] — [SQ Magazine](https://sqmagazine.co.uk/crypto-hedge-funds-statistics/); [CoinLaw](https://coinlaw.io/crypto-hedge-funds-statistics/)
- **Account-level data is unavailable.** Exchanges generally do not release trader account-level data — [arXiv 2102.04591](https://arxiv.org/pdf/2102.04591). A 2026 systematic literature review names trader-level measurement as a central research gap — [ResearchGate SLR](https://www.researchgate.net/publication/413674052_Cryptocurrency_Perpetual_Futures_and_Swaps_A_Systematic_Literature_Review).

### Inferences
- **The winner set is consistent across sources:** the venue (fees), professional MMs (Wintermute's on-chain P&L), backstop vaults (HLP), large accounts ($10–100M: 85.7% profitable over 30 days), and carry harvesters in high-carry regimes.
- **The loser set is consistent too:** small accounts, high leverage (about 60x average among liquidated BitMEX traders), long-biased positions (85–90% of 2025 liquidations), high turnover, and copy followers.
- **Survivorship inflates apparent success.** In the Envy sample, 40.6% of wallets quit within 30 days. Leaderboards and "active trader" samples therefore overstate success. Over longer horizons, base rates are likely worse than the 30-day 14–17% figure; Brazil's 300+ session cohort shows 97% losing.
- **Wallet counts mix pros and retail.** On-chain wallet statistics include MMs and bots, and one person may hold many wallets. The "14–17% profitable" share is therefore not a pure retail statistic. Because large and professional accounts sit in the profitable tail, the true retail-only profitable share is probably *lower*.
- **Even professionals had a weak 2025** (average −7.2%; quant about flat). Durable edges were scarce even for funded teams in the 2025–26 regime.

### Gaps
- No peer-reviewed study uses trader-level P&L from Binance, Bybit or OKX.
- No measured average leverage of liquidated Hyperliquid positions was found, although the data is public on-chain and could be computed. The only figure (about 60x) comes from older BitMEX data, and the exact sample period was not confirmed.
- No dated, audited 2026 Hyperliquid P&L distribution study. Wallet-level studies do not separate retail from professionals.
- No exchange-disclosed "% of retail accounts losing" figure for crypto perpetuals specifically (for example, EU MiFID risk warnings) was retrieved.
- The total funding paid by retail longs was not quantified.

---

## Q3. Fee economics: VIP tiers, maker vs taker, rebates, and how fees decide who wins

### Takeaway
Fees are the main structural factor deciding who wins.
- A base-tier retail trader pays **0.045–0.05% per taker fill**, which is **0.09–0.10% for a round trip**.
- Top-tier market makers are **paid rebates of −0.001% to −0.008%**.
- The gap is about 10–11 bp per round trip. That gap alone roughly halves the Sharpe ratio of the *same* BTC arbitrage (3.5 → 1.8). It also wipes out much of 2026's roughly 2–4% annual BTC carry.

(요약) 수수료가 승패를 가르는 가장 큰 구조적 요인이다. 일반 개인은 시장가 체결 한 번에 0.045~0.05%(왕복 0.09~0.10%)를 내고, 최상위 시장조성자는 오히려 리베이트를 받는다. 이 차이(왕복 약 0.1%)만으로 같은 차익거래의 샤프지수가 3.5에서 1.8로 반 토막 나고, 2026년 비트코인 펀딩 수익(연 2~4%)도 대부분 사라진다.

### Cited Findings
- **Binance USDⓈ-M fees.** [SECONDARY; official live fee page not retrieved] — [Datawallet VIP guide](https://www.datawallet.com/crypto/binance-vip-levels-explained); [Binance fee FAQ](https://www.binance.com/en/support/faq/360033544231); [KKInvesting](https://kkinvesting.io/en/posts/binance-futures-trading-tutorial/)
  - Base tier: **0.02% maker / 0.05% taker**, with about a 10% discount when paying in BNB.
  - **VIP 9: 0.00% maker / 0.017% taker.**
  - VIP level depends on 30-day futures volume (USDⓈ-M plus COIN-M) and BNB holdings; VIP 1 needs at least 25 BNB daily average.
  - Intermediate VIP rows conflict across third-party tables. For example, one shows VIP 1 at 0.016% / 0.040%, and another shows a clearly different schedule.
- **VIP 1 futures threshold.** It was 15,000,000 (BUSD) in 30-day volume in December 2021. It was later reportedly lowered to 5,000,000 USD; the date is unconfirmed. — [Binance VIP Program Upgrade 2021](https://www.binance.com/en/support/announcement/88ee9834fef947de96e01b77e888414e); [MEXC News](https://www.mexc.com/news/954874) [ATTRIB?]
- **Binance spot base fee: 0.1%** (stated in a third-party guide's title). [LOW] — [binancemakertakerfee.org](https://binancemakertakerfee.org/)
- **Hyperliquid perpetual fees.** [SECONDARY; official docs not fetchable] — [Dwellir](https://www.dwellir.com/blog/hyperliquid-fees-explained); [hyperliquidguide fee tiers](https://hyperliquidguide.com/guides/fees/fee-tiers)
  - Base tier: **0.015% maker / 0.045% taker**.
  - Seven tiers by 14-day weighted volume: below $5M, then above $5M, $25M, $100M, $500M, $2B and $7B.
  - Taker fees fall to **0.024%** at the top tier. Maker fees reach **0% from tier 4** (more than $500M).
  - Maker rebates are **−0.001%, −0.002% and −0.003%** for maker-volume shares above 0.5%, 1.5% and 3.0%.
  - Binance's top taker fee (0.017%) is lower than Hyperliquid's top taker fee (0.024%).
- **Binance LP program rebates.** −0.005% (USDT-M), −0.008% (USDC-M), plus an extra 0.05 bp on BTCUSDT from Nov 13, 2025. [PRIMARY] — [Binance](https://www.binance.com/en/support/announcement/detail/f5d3200b65104308b8349cee59a2296e)
- **Same arbitrage, different fees.** Sharpe ratio about 1.8 on retail costs vs about 3.5 for market makers without such fees (BTC, He et al.). [PRIMARY] — [arXiv](https://arxiv.org/abs/2212.06888)
- **Fees erase most gross basis.** Galaxy: the CME basis was 7.9% gross but only about 1.5 pp over cash after fees, roll and margin. — [Startup Fortune](https://startupfortune.com/hedge-funds-dump-bitcoin-etfs-as-the-futures-basis-trade-dries-up/)
- **Copy followers pay extra layers.** They enter after the leader and often pay taker fees, plus profit share and funding costs. [VENDOR] — [KuCoin blog](https://www.kucoin.com/blog/is-crypto-copytrading-profitable-in-2026)
- **MMs and point farmers (commentary).** Market makers often trade against retail flow that sends market orders to farm volume-based points. [LOW; ATTRIB?] — [0xlykt Substack](https://0xlykt.substack.com/p/finding-edge)

### Inferences
These are calculations from the cited fee schedules: arithmetic, not sourced data.

- **Round-trip fee cost as a share of notional:**

  | Venue / tier | Taker + taker | Maker + maker |
  |---|---|---|
  | Binance base | **0.10%** | 0.04% |
  | Binance base, BNB discount (≈10%) | ≈0.09% | ≈0.036% |
  | Hyperliquid base | 0.09% | 0.03% |
  | Binance LP program | — | **−0.01%** (the maker *earns* 1 bp) |

  The gap between a retail taker and a top MM is about **11 bp per round trip**.
- **Leverage multiplies fees relative to margin.**
  - At 10x, one Binance base taker round trip costs about **1% of margin**.
  - One round trip a day at 10x costs about **365% of margin per year** in fees (simple, not compounded). The trader must earn that before any profit.
  - At 3x and one round trip a week, it costs about 0.3% × 52 ≈ **16% of margin per year**.
- **Chasing VIP tiers is self-defeating at small size.** Binance VIP 1 needs $5M–$15M of 30-day volume. A $20k account at 5x ($100k notional) would need 50–150 full notional turnovers a month to qualify. It would pay far more in fees than the discount saves (taker about 0.05% → about 0.04%).
- **Hyperliquid rebates are out of reach.** They need at least 0.5% of all maker volume, about $385M per 2 weeks (October 2026). That is unattainable at ₩-millions scale.
- **Do-it-yourself BTC funding harvest in 2026, an illustrative case.**
  - Funding averaged about 2.2% annualized (2026 year to Aug 11).
  - A spot + short-perp hedge with the perpetual at 1–3x ties up about 1.33–2× notional in capital. That gives a gross yield on capital of about 1.1–1.65% a year.
  - Four taker legs cost about 0.3% of notional (using the 0.1% spot fee). Holding a full year then leaves about **1–1.4% a year**.
  - That is below the 2-year US Treasury (about 3.8%, August 2026) and below sUSDe (about 5.1%, Nov 3, 2026), which carries Ethena-specific risk.
  - In high-carry regimes (BIS: more than 10% average, up to 60%), fee drag becomes minor. But BIS also finds that such regimes predict crashes.
- **The asymmetry itself is why the venue and makers win.** Takers, mostly retail and copy followers, pay. Makers with scale get paid. Fees therefore transfer wealth from the low-volume majority to the high-volume few, independent of anyone's market view.

### Gaps
- Official current VIP tables for Binance, Bybit and OKX were not retrieved. Bybit and OKX base fees were not verified in this session.
- HYPE-staking and referral fee discounts on Hyperliquid were not captured.
- Spread and slippage costs for BTCUSDT perpetuals (Kaiko or Amberdata depth data) were not retrieved. For BTC they are likely small relative to fees, but this is unverified.
- Liquidation fees and penalties (for example, Binance's liquidation clearance fee, and how insurance funds are fed) were not retrieved.
- Aggregate funding paid by retail longs was not quantified.

---

## Q4. What professional crypto trading firms and funds say about where durable returns come from

### Takeaway
Practitioner, academic and data-provider evidence points the same way. Durable returns come from three places:
1. **Carry/basis earned by supplying leverage to retail.** It is cyclical, and in 2025–26 it compressed to about the risk-free rate. Hedge funds exited the CME/ETF basis trade, and Ethena moved toward equity perpetuals.
2. **Liquidity provision with fee and speed advantages.** It is highly competitive, and even leading MMs are diversifying beyond crypto.
3. **Disciplined, risk-filtered systematic strategies.**

Directional crypto funds had a poor 2025: average −7.2%, quant funds +0.4%. I found few direct, citable statements from top MMs.

(요약) 전문가와 연구 자료가 가리키는 방향은 같다. 꾸준한 수익은 ① 개인에게 레버리지를 제공하고 받는 베이시스·펀딩 수익(주기적이고, 2025~26년엔 국채 금리 수준으로 줄었다) ② 수수료·속도 우위를 가진 유동성 공급(경쟁이 매우 치열하고, 대형 시장조성자도 크립토 밖으로 사업을 넓히는 중) ③ 위험 관리를 갖춘 체계적 전략에서 나온다. 2025년 방향성 크립토 펀드 성과는 나빴다(평균 −7.2%, 퀀트 펀드 +0.4%).

### Cited Findings
- **Fasanara (a fund manager).** The crypto market is "still dominated by retail investors who use excessive leverage and bid up futures premiums", which is what basis traders harvest. Bloomberg via WealthManagement; article date not confirmed. [SECONDARY] — [WealthManagement](https://www.wealthmanagement.com/crypto/wall-street-unleashes-old-tricks-in-2-5-trillion-crypto-jungle)
- **BIS (academic/official).** Carry comes from small trend-chasing investors' demand for leverage plus scarce arbitrage capital, and high carry predicts crashes (revised October 2025). [PRIMARY] — [BIS](https://www.bis.org/publ/work1087.htm)
- **He et al.** Perpetual mispricings diminished over time, consistent with arbitrage capital entering. Fee level decides the arbitrage Sharpe ratio. [PRIMARY] — [arXiv](https://arxiv.org/abs/2212.06888)
- **Galaxy.** The CME basis paid only about 1.5 pp over cash after costs. Hedge funds have since exited ETF-basis positions: nine firms pulled about $5.4B since September 2025, Brevan Howard cut its IBIT stake from about $2.6B to about $255M, and Farallon cut 69%. [SECONDARY] — [Startup Fortune](https://startupfortune.com/hedge-funds-dump-bitcoin-etfs-as-the-futures-basis-trade-dries-up/)
- **CME in 2026.** The basis fell to about 3%, below the 2-year UST yield of about 3.8% (Aug 10, 2026), and CME hedge funds flipped net long. — [BigGo Finance](https://finance.biggo.com/news/9c11c1e7-4988-4ad7-998f-7d4f8a51f6ad); [CoinDesk](https://www.coindesk.com/markets/2026/08/10/a-rare-cme-shift-hedge-funds-abandon-structural-shorts-to-bet-on-a-bitcoin-rally)
- **Ethena (largest basis product).** It is moving its basis trade to equity perpetuals because median equity funding (13.9%) is far above BTC funding (3.9%) (August 2026). — [UseTheBitcoin](https://usethebitcoin.com/news/ethena-equity-perpetuals-usde-yield/)
- **Wintermute.** Average daily volume fell from about $15B to about $10B. It targets more than 50% non-crypto revenue and is committing $1B over 5 years to become a multi-asset "AI-powered trading house". — [BigGo Finance](https://finance.biggo.com/news/52371a1c-00df-4506-9838-6fac925ac3b2)
- **B2C2's CEO.** Latency competition is a winner-takes-all arms race costing "tens of millions" (see 1-B). [OPINION] — [Yahoo News](https://news.yahoo.com/crypto-latency-arms-race-crypto-094026830.html)
- **Anchorage Digital.** BTC covered-call yield is "fundamentally an active management problem"; unfiltered, it was about flat over October 2021–April 2026. [VENDOR] — [Anchorage](https://www.anchorage.com/research/synthetic-yield-on-bitcoin-implementation-discipline-and-performance-boundaries-of-systematic-covered-call-writing)
- **Crypto Fund Research, 2025.** Average −7.2% and median −5.2%; only 37% of funds positive. Quant funds averaged +0.4% (58% positive), with shallower drawdowns than other categories. — [CFR](https://cryptofundresearch.com/crypto-hedge-fund-performance/)
- **Market-neutral funds, 2025.** They gained +14.4% through November 2025 vs −2.5% for directional funds (CoinEdition via TV-Hub; partial year, different basis). — [TV-Hub](https://www.tv-hub.org/guide/market-neutral-strategy-crypto). Another survey says market-neutral returned about 13% with Sharpe ratios about 2× long-only; methodology unclear. [ATTRIB?] — [CoinLaw](https://coinlaw.io/crypto-hedge-funds-statistics/)
- **Practitioner and educational commentary.** [LOW; ATTRIB?] — [TraderMath](https://www.tradermath.org/courses/introduction-to-digital-assets/arbitrage-opportunities-in-crypto-spot-futures-cross-exchange); [QuantVault](https://quantvault.org/how-quant-firms-make-money.html); [Podwise episode page](https://podwise.ai/episodes/3177601)
  - The funding-rate basis on perpetuals is called "the largest and most durable crypto trade".
  - Continuous liquidity provision across fragmented venues earns spread, with arbitrage falling out of inventory management.
  - High-frequency crypto has "vicious adverse selection" and faster alpha decay than slower domains.
- **Quant strategy overview, 2026.** Strategies that worked in 2020–21 faded once heavy retail presence was gone. The edges it cites are rebalancing speed and better short-term funding prediction. [LOW; ATTRIB?] — [Quantt](https://www.quantt.co.uk/resources/crypto-quant-strategies-2026)

### Inferences
- **Professional edges are counterparty edges.** Nearly every "durable" source that professionals describe takes the other side of retail behavior. Carry is paid by retail leverage demand. Spread and rebates are paid by retail takers. Liquidation profits come from over-leveraged positions.
- **These edges are cyclical and shrink as capital arrives.** The 2025–26 evidence is consistent:
  - BTC funding fell from 11.0% to 2.2%.
  - CME basis fell to about 3%, below Treasuries.
  - Hedge funds unwound the basis trade.
  - Ethena moved to equity perpetuals.
  - Wintermute's volume fell and it is diversifying.
  - Quant funds were about flat in 2025.
- **Edges come from structure, not prediction.** What professionals call durable rests on scale (rebate tiers), speed (Tokyo-region infrastructure) and low-cost capital, not on forecasting price. None of these is reachable for an individual with ₩1M to tens of millions. What an individual *can* replicate are the low-infrastructure versions:
  - opportunistic carry when funding is high;
  - passive vault exposure;
  - disciplined low-turnover systematic rules.

  For each of these the evidence is thin or regime-dependent.

### Gaps
- No direct, dated statements were found from Jump, GSR, Amber, Galaxy's trading desk or Wintermute executives on how their BTC perpetual P&L splits between spread, rebates, funding and directional trading. Only secondary summaries were found.
- The Block's "The Funding: How crypto hedge funds are navigating weak markets" surfaced, but its content was not retrieved. — https://theblock.co/post/403128/the-funding-how-crypto-hedge-funds-are-navigating-weak-markets
- Crypto fund performance databases are self-reported and small (about 84 funds in CFR's strategy breakdown), with survivorship and reporting bias. Marketing-style statistics pages (claiming +36% or +48%) conflict with CFR and should not be used.
- No audited data on market-maker profit margins in BTC perpetuals.
