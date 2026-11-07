# LLM-based crypto chart analysis and trading agents: real cases and measured results (notes as of 2026-11-07)

> **How these notes were made.** WebFetch could not reach outside hosts from this session (arxiv.org, okky.kr, forklog.com and traderank.ai all failed DNS resolution because they are not on the session's allowed network list). So every finding below comes from **WebSearch result summaries of the linked pages**, not from reading those pages in full. Treat exact numbers as "reported by the linked page, as summarized by search" and re-check them on the primary page before quoting them as final. Dates are event or publication dates. Items from before 2025 are marked **[older]**. Conflicts between sources are stated explicitly.

---

## 1. Live and real-money LLM trading competitions and benchmarks (Alpha Arena, LiveTradeBench, StockBench, InvestorBench, FinBen, others)

### Takeaway
nof1's Alpha Arena Season 1 (Oct 18 to Nov 3, 2025) is the most widely covered real-money LLM contest on crypto perps, the setting closest to this project. In it, 4 of 6 frontier LLMs lost about 42 to 63% of $10,000 in about 17 days. The winner (Qwen3 Max, about +22%) made a few concentrated, high-leverage bets, and observers could not separate skill from luck in one short run. The live-data benchmarks (LiveTradeBench, StockBench, Agent Market Arena, InvestorBench) mostly show LLM agents roughly matching or failing to beat buy-and-hold, and general LLM leaderboards do not predict trading skill. As of Nov 2026 I found no official Alpha Arena Season 2 results.

### Cited Findings

**Alpha Arena Season 1: crypto perps, real money, Oct 18 to Nov 3, 2025 (about 1 year old)**
- Setup: six LLMs (Qwen3 Max, DeepSeek Chat V3.1, Claude Sonnet 4.5, Gemini 2.5 Pro, Grok 4, GPT-5) each got $10,000 to trade crypto perpetuals on Hyperliquid with no human intervention — [GNcrypto](https://www.gncrypto.news/news/qwen-wins-alpha-arena-season-1-with-22-percent-returns/). Press described it as "real money, real market" — [Yahoo Finance/Decrypt](https://finance.yahoo.com/news/deepseek-outperforms-ai-rivals-real-093000567.html); [Bitcoin.com News](https://news.bitcoin.com/6-bots-with-real-money-hyperliquid-hosts-first-ever-ai-trading-showdown/)
- Dates: Oct 18 to Nov 3, 2025 per [TradeRank](https://www.traderank.ai/alpha-arena-leaderboard). The conclusion was reported for Nov 4 — [Phemex News](https://phemex.com/news/article/alpha-arena-ai-trading-competition-to-conclude-on-november-4-30877)
- Universe: six coins only (BTC, ETH, SOL, BNB, DOGE, XRP) — [Unitzero](https://www.unitzero.tech/blogs/alpha-arena-six-ai-models-battle-it-out-in-live-crypto-trading); [Cryptomania](https://cryptomania.win/blog/cryptomania-news-2/alpha-arena-six-ai-models-60k-live-on-perps-whos-winning/). All models got the same inputs, prompt and trading universe, and could only buy, sell, hold or close — [iWeaver](https://www.iweaver.ai/blog/alpha-arena-ai-trading-season-1-results/); [AI World](https://aiworld.eu/story/ai-agents-against-the-market)
- Cadence and inputs: each model was called every 2 to 3 minutes with live Hyperliquid perp data — [DEV Community replication guide](https://dev.to/quant001/alphaarena-ai-model-battle-a-hands-on-guide-to-replicating-deepseeks-leading-ai-quantitative-2dpe); [Moshiii prompt analysis](https://moshiii.substack.com/p/alpha-arena-prompt-analysis). A third-party reconstruction of the user prompt uses 3-minute intraday series plus EMA, MACD, RSI, volume, open interest and funding rate. This is not an official document — [kukapay/alpha-arena-mcp](https://github.com/kukapay/alpha-arena-mcp)
- Required output (from a reverse-engineered prompt, not official): action, size, leverage, justification, a 0-to-1 confidence, and an exit plan with profit target, stop loss and "invalidation condition". The plan is fed back on later calls, and the prompt tells models to hold unless invalidation triggers and warns against overstating conviction — [nof1-prompt gist](https://gist.github.com/wquguru/7d268099b8c04b7e5b6ad6fae922ae83); [Moshiii](https://moshiii.substack.com/p/alpha-arena-prompt-analysis)
- Final results:
  - Qwen3 Max +22.31% (about $12,231) and DeepSeek V3.1 +4.89%. The other four ended between −42.01% and −58.74%, with Claude Sonnet 4.5 at −42.01% — [TradeRank](https://www.traderank.ai/alpha-arena-leaderboard)
  - Final balances: Claude Sonnet 4.5 $5,799, Gemini 2.5 Pro $5,445, Grok 4 $4,208, GPT-5 $4,126, which matches TradeRank's range (my arithmetic: −42.0%, −45.6%, −57.9%, −58.7%) — [ForkLog](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/)
  - **Conflicts:**
    - GPT-5 at about $3,733 — [GNcrypto](https://www.gncrypto.news/news/qwen-wins-alpha-arena-season-1-with-22-percent-returns/)
    - Qwen3 Max +23%, DeepSeek +5%, Claude −33%, Grok −48%, Gemini −55%, GPT-5 −63% — [xmarva blog, 2026](https://xmarva.github.io/blog/2026/ai-crypto-trading/)
    - GPT-5 −62.66% — [iam-raccoon/llm-trading-backtest](https://github.com/iam-raccoon/llm-trading-backtest)
    - Qwen 22.32% and DeepSeek 4.89% in Korean press — [더구루](https://www.theguru.co.kr/news/article.html?no=94001)
    - The differences probably come from snapshot timing (last mark vs. final close).
- Path volatility:
  - DeepSeek briefly led with more than $13,000 net profit before a downturn cut it back to about +4.9% — [iWeaver](https://www.iweaver.ai/blog/alpha-arena-ai-trading-season-1-results/)
  - An early headline read "DeepSeek Earns 42% in Two Days" — [KuCoin News](https://www.kucoin.com/news/flash/alpha-arena-prompt-revealed-deepseek-earns-42-in-two-days)
  - A Korean mid-run snapshot (date unclear) had DeepSeek +35%, Grok 4 +30%, Claude Sonnet +28%, GPT-5 −27%, Gemini 2.5 Pro −33%. So rankings flipped within days; Claude went from about +28% to a final −33 to −42% — [MS TODAY](https://www.mstoday.co.kr/news/articleView.html?idxno=99240)
  - A Bitcoin Magazine headline read "Alpha Arena reveals AI trading flaws: Western models lose 80% capital in one week" — [Bitcoin Magazine](https://bitcoinmagazine.com/business/alpha-arena-reveals-ai-trading-flaws-western-models-lose-80-capital-in-one-week)
- Trade frequency and fees: Gemini 2.5 Pro traded most (238 trades) and paid $1,331 in fees. Claude Sonnet 4.5 traded least (38) in the same table, but other sources disagree on Claude's count — [Admiral Markets](https://admiralmarkets.com/education/articles/automated-trading/claude-vs-chatgpt-vs-grok-trading)
- Per-model behavior (secondary sources, partly conflicting):
  - Qwen3 Max: 43 trades, 30.2% win rate, "moderate leverage", longer holds than the median model — [Buildix](https://www.buildix.trade/blog/nof1-alpha-arena-lessons-ai-trading-byok-strategy-advisor-2026). Another source says it usually held one position at a time and often used 25x, the stated maximum — [Upscale](https://upscale.trade/blog/ai-trading-alpha-arena). "Moderate" vs. "25x" conflict.
  - DeepSeek V3.1: 17 trades with about 49 hours average hold over the first nine days. GPT-5 and Gemini averaged under 1x leverage per position (PANews figures via Upscale) — [Upscale](https://upscale.trade/blog/ai-trading-alpha-arena)
  - Claude Sonnet 4.5 reportedly ran a 100% long book with no hedging or stop-loss discipline (single source) — [Buildix](https://www.buildix.trade/blog/nof1-alpha-arena-lessons-ai-trading-byok-strategy-advisor-2026)
- Organizer framing:
  - Founder Jay Azhang called Season 1 a "first experiment in understanding how LLMs handle the noisy, adversarial, non-stationary world of markets" — [Jay Azhang on X](https://x.com/jay_azhang/status/1985481491078328621)
  - Coverage reports he saw consistent model biases ("investing personality") that persisted across time and many prompt iterations. He also said the next season would run multiple prompts in parallel and many instances of each model — [AI World](https://aiworld.eu/story/ai-agents-against-the-market); [X thread](https://x.com/jay_azhang/status/1985481491078328621)
- Critics said results may be indistinguishable from a random walk, and that useful data would need long runs and independent replication — [Bitcoin Magazine](https://bitcoinmagazine.com/business/alpha-arena-reveals-ai-trading-flaws-western-models-lose-80-capital-in-one-week)

**Alpha Arena Season 1.5: US equities, Nov 19 to Dec 3, 2025**
- Format: 8 models in 4 parallel modes (New Baseline, Monk Mode, Situational Awareness, Max Leverage). "Max Leverage" forced maximum leverage on every trade: 20x for Nasdaq-100 index positions, 10x for single stocks — [GNcrypto, S1.5 launch](https://www.gncrypto.news/news/alpha-arena-season-1-5-ai-stock-trading-competition/); [GNcrypto, winner](https://www.gncrypto.news/news/mystery-model-alpha-arena-season-1-5-winner/)
- Winner: "Mystery Model", later revealed as Grok 4.20, at +12.11% aggregate per the organizer archive. BlockBeats (Dec 6, 2025) reported +22.38% (conflict) — [GNcrypto](https://www.gncrypto.news/news/mystery-model-alpha-arena-season-1-5-winner/); [Yahoo Finance](https://finance.yahoo.com/news/elon-musks-grok-4-20-123855766.html)
- ForkLog reported Grok 4.2 at about 12% over two weeks, GPT-5.1 second and Gemini 3 third — [ForkLog](https://forklog.com/en/ai-model-grok-4-2-triumphs-in-trading-tournament/)
- Spread: 32 entries (8 models × 4 competitions) ranged from +34.59% to −96.15% — [TradeRank](https://www.traderank.ai/alpha-arena-leaderboard)
- Season 1's crypto winner Qwen3 Max did badly on US equities — [GNcrypto](https://www.gncrypto.news/news/mystery-model-alpha-arena-season-1-5-winner/). A comparison article says only the xAI mystery model was in profit among the Anthropic, OpenAI and xAI entries — [Admiral Markets](https://admiralmarkets.com/education/articles/automated-trading/claude-vs-chatgpt-vs-grok-trading)
- One blog's stats for the winning run: 34.6% win rate, 9.2x average leverage, 46% time in market, 4 stocks traded — [Jamie Watters](https://jamiewatters.work/journey/alpha-arena-a-34-win-rate-just-crushed-the-ai-trading-competition-heres-what-im-stealing)

**Alpha Arena Season 2 (2026): status**
- Checked Aug 6, 2026: nof1.ai still showed Season 1.5, its banner said the models were no longer running, and no Season 2 roster, results or leaderboard had been published — [TradeRank](https://www.traderank.ai/alpha-arena-leaderboard)
- Nof1 raised $15M, co-led by SUI Group and Karatage, to fund Season 2 and a consumer AI trading platform. Season 2 is said to add web search, extended reasoning and multi-step execution (single source; date not captured) — [AI Weekly](https://aiweekly.co/alerts/nof1-raises-15m-to-run-ai-models-in-live-trading)
- A prompt guide reviewed in Aug 2026 says the arena now uses a daily portfolio-manager prompt whose JSON output goes through server-side validation (unverified) — [TradeRank prompt guide](https://www.traderank.ai/blog/ai-trading-prompts-engineering)
- One site claims a "second season on US stocks" was won by a different model, with no name or figures. It is unverified and probably refers to S1.5 — [Upscale](https://upscale.trade/blog/ai-trading-alpha-arena)

**Other live or real-money contests, 2026**
- Aster "Human vs AI" Season 1 (results Jan 14, 2026; self-reported by Aster) — [Chainwire press release](https://chainwire.org/2026/01/14/aster-human-vs-ai-live-trading-competition-season-1-concludes/)
  - Human team overall ROI −32.22%; 43% of humans were liquidated.
  - The 30 AI agents together lost about $13,000 (ROI −4.48%), and none was liquidated.
  - The top individual was a human trader ("ProMint").
  - Humans were funded with 10,000 USDT each (up to 100 traders) — [Aster docs](https://docs.asterdex.com/program-and-rewards/points-and-campaigns/human-vs-ai-battle-for-the-futures-usd200-000-reward-pool)
  - A $1M Season 2 was announced — [KuCoin News](https://www.kucoin.com/news/flash/aster-launches-1m-human-vs-ai-trading-competition-season-2)
- Hyperliquid AI-labelled vaults and apps (one blog author; not checked on-chain) — [DEV Community](https://dev.to/dronpancholi/crypto-ai-vaults-3-of-6-beat-bitcoin-1-fell-30-what-that-actually-proves-5d69); [DEV Community](https://dev.to/dronpancholi/ai-agents-are-trading-real-money-now-here-is-the-verified-record-not-the-hype-4bbe)
  - As of Nov 2, 2026, of 6 vaults whose leaders say they are AI-run, 3 beat BTC over the same dates, 2 lost money and 1 fell more than 30% from its peak.
  - From Oct 3 to Nov 1, 2026, 8 AI trading apps had 1,365 users trading $21.0M, and users lost money overall in 4 of the 8 apps.
- TradeRank runs 22 models on real market prices with simulated capital, not real money. As of Nov 6, 2026 the Season 10 leader was at +13.89%. Season 5 closed with Gemini 3.5 Flash first at +13.76%, and much of the leaderboard's gain was unrealized — [TradeRank](https://www.traderank.ai/)

**Live-data research benchmarks**
- **LiveTradeBench** (arXiv 2511.03628, Nov 2025; UIUC, Haofei Yu, Fenghai Li, Jiaxuan You)
  - Setup: 21 LLMs, 50-day live evaluation on US stocks and Polymarket; each stock model starts with $1,000 — [arXiv](https://arxiv.org/html/2511.03628v1)
  - GPT-4.1 had the highest stock return (>6%) but lost more than 30% on Polymarket, attributed to "overreactive allocation changes under higher volatility". The Sharpe correlation between the two markets was about 0 — [arXiv](https://arxiv.org/html/2511.03628v1)
  - LMArena score vs. trading outcome: Spearman ρ ≈ 0.05 (stocks) and −0.38 (Polymarket), per a summary — [alphaXiv overview](https://www.alphaxiv.org/overview/2511.03628v1)
  - Qwen2.5-72B-Instruct and Grok-4 were more stable across markets, and "over-deliberation" can degrade trading consistency — [Hugging Face Papers](https://huggingface.co/papers/2511.03628)
  - Limitation: it omits transaction costs, liquidity constraints and slippage — [arXiv](https://arxiv.org/html/2511.03628v1)
- **StockBench** (arXiv 2510.02209, Oct 2025)
  - Setup: $100,000, 20 Dow Jones stocks, Mar 3 to Jun 30, 2025. A reproduction notes an 82 vs. 83 trading-day discrepancy and confirms the equal-weight buy-and-hold baseline at +0.4% with −15.2% max drawdown — [stockbench-inspect](https://github.com/mahimn01/stockbench-inspect)
  - Best agent Kimi-K2: +1.9% with −11.8% max drawdown — [maxpool summary](https://maxpool.dev/research-papers/stockbench_llm_trading_report.html); [Emergent Mind](https://www.emergentmind.com/topics/stockbench). Another summary says 2.5% (conflict) — [Quantex, Oct 17, 2026](https://quantex.com.sg/research/2026-10-17-llm-agents-vs-buy-and-hold/)
  - Authors: "most LLM agents struggle to outperform the simple buy-and-hold baseline, but several models demonstrate the potential to deliver strong results" — [arXiv](https://arxiv.org/pdf/2510.02209v1)
  - Good scores on static finance Q&A did not reliably carry over to trading — [alphaXiv](https://www.alphaxiv.org/abs/2510.02209.md)
  - In additional windows, agents did worse in the Jan–Apr 2025 downturn and mostly beat the baseline in the May–Aug 2025 upturn, which suggests a bullish bias — [Emergent Mind](https://www.emergentmind.com/topics/stockbench)
- **Agent Market Arena** ("When Agents Trade", arXiv 2510.11695, Oct 2025)
  - A lifelong real-time benchmark on TSLA, BMRN, BTC and ETH, with 4 agent designs (including the memory-based DeepFundAgent) on GPT-4o, GPT-4.1, Claude-3.5-haiku, Claude-sonnet-4 and Gemini-2.0-flash over a two-month live run.
  - Agent architecture mattered more than the backbone model. Agents ranged from aggressive risk-taking to conservative behavior — [arXiv](https://arxiv.org/abs/2510.11695); [GitHub](https://github.com/The-FinAI/Agent_Market_Arena); [Moonlight review](https://www.themoonlight.io/en/review/when-agents-trade-live-multi-market-trading-benchmark-for-llm-agents)
- **InvestorBench** (ACL 2025; backtest; crypto data Apr–Nov 2023, so contamination-prone)
  - 13 backbone LLMs on stocks, crypto (BTC, ETH) and ETFs.
  - Proprietary models (GPT-4, GPT-4o, o1-preview) averaged 36.14% cumulative return and Sharpe 0.82 on stocks. On BTC they returned 23.60% vs. 21.82% for buy-and-hold, while open-source models averaged 14.14% — [ACL Anthology](https://aclanthology.org/2025.acl-long.126/); [paper PDF](https://suchow.io/assets/docs/li2025investorbench.pdf)
  - A third-party stock leaderboard has Qwen2.5-72B at 46.15%, GPT-4 at 43.70% and GPT-4o at 39.03% — [Beancount research log](https://beancount.io/bean-labs/research-logs/2026/06/02/investorbench-llm-agent-financial-decision-making)

### Inferences
- Alpha Arena S1 is the closest public analogue to this project (crypto perps, leverage, frequent calls). There, frontier LLMs **acting autonomously with leverage** mostly lost 42 to 63% in about 2.5 weeks. The reported causes are leverage misuse, overtrading and fees, not a lack of "analysis".
- One 17-day run with 6 models cannot separate skill from luck. Qwen's win came from a few concentrated high-leverage trades, and the same model then did badly on equities in S1.5, so its win is not evidence of skill.
- Aster's result (AI agents never liquidated, 43% of humans liquidated, both groups net negative) suggests the main measurable benefit of automation is **discipline from hard risk rules**, not better forecasting.
- LiveTradeBench and Agent Market Arena suggest that picking the "smartest" model matters less than system design and risk rules.
- For a decision-support tool where a human places the orders, the relevant evidence would be a **forward-logged** record of each hourly call, including fees and funding, compared with BTC buy-and-hold and a simple rule baseline. Backtests that use the LLM do not give this (see section 5).

### Gaps
- I could not open nof1's own Season 1 technical post ("TechPost1", linked from Azhang's X thread), so the official prompt, leverage cap (20x vs. 25x conflict), fee totals per model, max drawdowns and per-model trade counts stay unverified.
- Claude Sonnet 4.5's final S1 figure varies: −42.01% (TradeRank/ForkLog), −33% (xmarva blog), and a −30.81% figure attributed to Protos in secondary coverage whose original I could not locate.
- Some claims came from search summaries with no traceable page, so I left them out of the findings:
  - A PANews interim tally (Gemini 165 trades and over $1,000 in fees by Oct 27, 2025)
  - A Claude 20x ETH long liquidated on a tariff-news drop
  - GPT-5 "two margin calls"
  - An interim Aster snapshot with "Claude Sonnet 4.5 (Aggressive)" leading the AI accounts at $9,310 PnL (EchoSync, undated)
- No per-mode S1.5 breakdown (Monk Mode, Situational Awareness), no Claude S1.5 result, and no confirmation that S1.5 used real money.
- I could not confirm whether LiveTradeBench and Agent Market Arena placed real orders. They appear to use live data with simulated portfolios.
- FinBen: I found no trading or crypto results. A comparison table in search results only noted that it lacks a multi-asset trading component.
- Unread leads that may matter:
  - LATTICE, "Evaluating Decision Support Utility of Crypto Agents" — [arXiv 2604.26235](https://arxiv.org/pdf/2604.26235). Directly relevant to a decision-support tool; content not retrieved.
  - PolyBench — [arXiv 2604.14199](https://arxiv.org/html/2604.14199v1)
  - Boris Tseitlin's critique "Why Alpha Arena is literally the worst" — [Substack](https://borisagain.substack.com/p/why-alpha-arena-is-literally-the); title only

---

## 2. Multi-agent LLM trading frameworks (TradingAgents, FinAgent, CryptoTrade, FinMem, FinCon, FinRobot, ai-hedge-fund): architecture, evaluation, results, criticisms

### Takeaway
The well-known frameworks model a trading firm: analysts (fundamental, sentiment, news, technical), a bull/bear debate, a trader, a risk team and a manager. Their headline results come from short, self-chosen backtest windows (3 to 8.5 months), which are often before the model's training cutoff. Independent re-tests over longer, wider, leakage-controlled data (FINSABER, Profit Mirage, the Alpha Illusion paper, the "What survives honest evaluation" paper) find the reported edge mostly disappears and is often worse than buy-and-hold.

### Cited Findings

**TradingAgents (Tauric Research; arXiv 2412.20138, Dec 2024, v7 Jun 3, 2025)**
- Architecture: four analysts, then a bull and bear researcher debate, then a trader, then a risk team (three risk-perspective agents plus a manager), then a portfolio manager. Natural-language debate is used only in the bull/bear and risk-team exchanges; other agents pass structured documents. The number of debate rounds is set by hand, with no sensitivity analysis — [Pith review](https://pith.science/paper/2412.20138); [arXiv](https://arxiv.org/html/2412.20138)
- Cost per decision:
  - About 11 LLM calls plus 20+ tool calls — [Beginners in AI](https://beginnersinai.org/tradingagents-explained/); [Pith](https://pith.science/paper/2412.20138)
  - A code-level count gives at least 15 calls (7 analyst, 2 bull/bear, 3 risk), plus 2 per extra debate round and 3 per extra risk round — [DEV Community](https://dev.to/itxtayab/tradingagents-by-tauric-research-a-trading-firm-of-12-llm-agents-and-what-one-decision-costs-4dfa)
  - Third-party cost estimates: $0.30–0.50 per run at GPT-5 rates — [Pinggy](https://pinggy.io/blog/best_ai_trading_agents/); or about $1–5 per decision at o1-preview prices — [Beginners in AI](https://beginnersinai.org/tradingagents-explained/)
  - A community issue proposes a single-prompt bull/bear variant to cut calls — [GitHub issue #1188](https://github.com/TauricResearch/TradingAgents/issues/1188)
- Reported AAPL results (Jan 1 to Mar 29, 2024): 26.62% cumulative return, 30.5% annualized, Sharpe 8.21, max drawdown 0.91%, vs. buy-and-hold −5.23% (Sharpe −1.29). These are secondary summaries of the paper's table — [Learn AI wiki](https://ai.miraheze.org/wiki/TradingAgents); [arXiv PDF](https://arxiv.org/pdf/2412.20138)
- The authors themselves say the Sharpe "exceeds our expected empirical range" and attribute it to few pullbacks in the window — [arXiv PDF](https://arxiv.org/pdf/2412.20138)
- Criticisms:
  - Only 3 months of backtest, expensive to run, never deployed live — [Beginners in AI](https://beginnersinai.org/tradingagents-explained/)
  - No slippage, no taxes, and only AAPL, GOOGL and AMZN — [DEV Community v0.2.4 article](https://dev.to/_46ea277e677b888e0cd13/tradingagents-v024-a-multi-agent-llm-framework-that-simulates-an-entire-trading-firm-g2e)
- The maintainers call it a research and educational tool, and say backtest results are "illustrative" — [Tauric Research](https://tauric.ai/research/tradingagents)
- The "Alpha Illusion" paper re-ran TradingAgents and QuantAgent against buy-and-hold over one year, with and without frictions — [alphaXiv](https://www.alphaxiv.org/abs/2605.16895v1)

**FinAgent (KDD 2024; arXiv 2402.18485) [older]**
- Multimodal: it takes Kline (candlestick) chart images and trading line charts plus text. A low-level reflection module reflects on news, reports, Kline charts and indicators — [arXiv v3](https://arxiv.org/html/2402.18485v3)
- Claims: across 6 datasets (stocks and crypto) it beat baselines on 6 metrics, with more than 36% average profit gain. One dataset (TSLA) returned 92.27%, an 84.39% relative improvement. The baseline count is 12 in the KDD version and 9 in arXiv v3 — [arXiv](https://arxiv.org/abs/2402.18485); [KDD PDF](https://personal.ntu.edu.sg/boan/papers/KDD24_FinAgent.pdf); [Emergent Mind](https://www.emergentmind.com/papers/2402.18485)
- Ablation: low-level reflection gave +45% to +101% annual return and −14% to −44% max drawdown on volatile assets — [arXiv v3](https://arxiv.org/html/2402.18485v3)
- A community reimplementation passes the candlestick image to the LLM for "Kline chart vision + price change analysis" — [GitHub effective-p/FinAgent](https://github.com/effective-p/FinAgent)

**FinMem (arXiv 2311.13743, Nov 2023; IEEE TBD 2025) [older]**
- Layered memory plus "character design". Example row: 23.26% cumulative return, Sharpe 1.44. Reported results use the setting with the highest test-phase cumulative return — [arXiv PDF](https://arxiv.org/pdf/2311.13743); [IEEE version PDF](https://suchow.io/assets/docs/yu2024finmem.pdf)

**FinCon (NeurIPS 2024; arXiv 2407.06567) [older]**
- A manager-analyst hierarchy with "conceptual verbal reinforcement". The NeurIPS table lists 113.836% cumulative return / Sharpe 3.269 (portfolio) and 32.922% / 1.371 in another column. Results again use the best test-phase setting — [NeurIPS PDF](https://proceedings.neurips.cc/paper_files/paper/2024/file/f7ae4fe91d96f50abc2211f09b6a7e49-Paper-Conference.pdf); [arXiv](https://arxiv.org/html/2407.06567)
- Evaluation windows of the headline results: FinMem 6 months (Oct 2022–Apr 2023), FinAgent 7 months (Jun 2023–Jan 2024), FinCon 8.5 months (from Oct 2022). This is per a comparison in search results; the table source is probably the FINSABER paper — [FINSABER v5](https://arxiv.org/html/2505.07078v5)

**CryptoTrade (EMNLP 2024; arXiv 2407.09546) [older]**
- A reflective LLM agent making daily buy/sell/hold decisions on BTC, ETH and SOL from on-chain and off-chain (news) data — [ACL Anthology](https://aclanthology.org/2024.emnlp-main.63/); [GitHub](https://github.com/Xtra-Computing/CryptoTrade)
- The authors' own framing is modest: performance is "comparable to traditional trading signals like Buy and Hold and MACD". It "may not always be the top performer" but "consistently surpasses more than half of the trading signals". Buy-and-hold returned 22.59% in the ETH bull test period — [ACL PDF](https://aclanthology.org/2024.emnlp-main.63.pdf); [arXiv](https://arxiv.org/abs/2407.09546)

**ai-hedge-fund (virattt)**
- An educational proof of concept with investor-persona agents (Warren Buffett, Ben Graham, Bill Ackman, Cathie Wood, Charlie Munger). The README says it "does not actually make any trades" and is not for real trading — [GitLink mirror](https://www.gitlink.org.cn/mirrors/ai-hedge-fund); [PyPI ai-rich 0.1.3](https://pypi.org/project/ai-rich/0.1.3/); [PyPI ai-rich 0.1.4](https://pypi.org/project/ai-rich/0.1.4/); [SourcePulse](https://www.sourcepulse.org/projects/1797841)
- A newer rebuild package says it aims to backtest, paper-trade and "optionally run live" (unverified) — [PyPI aihf](https://pypi.org/project/aihf/)
- Look-Ahead-Bench uses this framework to test end-to-end trading behavior — [Look-Ahead-Bench GitHub](https://github.com/benstaf/lookaheadbench)

**Critical re-evaluations**
- **FINSABER** (arXiv 2505.07078, May 2025; KDD 2026)
  - Backtests over two decades and 100+ symbols show previously reported LLM advantages "deteriorate significantly" — [arXiv](https://arxiv.org/abs/2505.07078); [GitHub](https://github.com/waylonli/FINSABER); [ACM](https://dl.acm.org/doi/abs/10.1145/3770854.3785702)
  - LLM strategies were too conservative in bull markets and too aggressive in bear markets — [arXiv](https://arxiv.org/abs/2505.07078)
  - In one setup, buy-and-hold Sharpe was 0.703 vs. FinAgent 0.241 vs. FinMem −0.228 — [FINSABER v5](https://arxiv.org/html/2505.07078v5)
  - The study is long-only.
- **Profit Mirage** (arXiv 2510.07920, Oct 2025)
  - Backtest gains evaporate after the model's knowledge cutoff. Sharpe decay ran from 51.48% (QuantAgent) to 62.23% (FinCon), and FinMem degraded most — [arXiv HTML](https://arxiv.org/html/2510.07920v1)
  - It proposes FinLake-Bench and FactFin, which uses the LLM as a strategy generator rather than a direct trader — [arXiv](https://arxiv.org/abs/2510.07920); [Moonlight review](https://www.themoonlight.io/en/review/profit-mirage-revisiting-information-leakage-in-llm-based-financial-agents)
- **The Alpha Illusion** (arXiv 2605.16895, May 2026)
  - Reported alpha from end-to-end LLM trading systems is backtest or prototype evidence, not deployment evidence. Three confounders: temporal contamination, unmodeled frictions, and short-sample or multiple-testing effects — [arXiv](https://arxiv.org/html/2605.16895v1)
  - It names FinCon, FinMem, TradingAgents, FinAgent, QuantAgent and FLAG-Trader, and proposes a P1–P6 reporting protocol — [Pith review](https://pith.science/paper/2605.16895)
- **What survives honest evaluation?** (Gencay, arXiv 2608.27734, Aug 2026)
  - Scope: 453 US stocks and 39 ETFs, two frontier models, up to 100 candidates per search, five runs. Honest evaluation certified the passive benchmarks and rejected **every** LLM-discovered strategy.
  - A deliberately leaky oracle with Sharpe 35 passed Deflated Sharpe and probability-of-backtest-overfitting tests, so leakage safety has to be built into the system structurally — [arXiv](https://arxiv.org/pdf/2608.27734); [RePEc](https://ideas.repec.org/p/arx/papers/2608.27734.html)
- **KTD-Fin** (CSI300, arXiv 2605.28359, May 2026): LLM agents' returns under leakage-controlled evaluation are mostly explained by passive market and style exposure — [arXiv](https://arxiv.org/html/2605.28359)
- **MemGuard-Alpha** (arXiv 2603.26797): fixes for memorization do not remove it entirely; it cites FINSABER's finding that much apparent LLM alpha disappears once survivorship and look-ahead are controlled — [arXiv](https://arxiv.org/pdf/2603.26797)

### Inferences
- The "several trader perspectives" idea in this project closely matches TradingAgents' bull/bear and risk-team debate and ai-hedge-fund's investor personas. These designs are good at **surfacing opposing arguments in readable text**, but no independent evidence shows they improve returns.
- Cost scales with the number of calls. At 24 reports a day, a 15-call debate per report means about 360 calls a day. One structured call with separate "perspective" sections (as issue #1188 suggests) is much cheaper.
- The strongest results (FinAgent, FinCon, TradingAgents) are self-reported, short-window and pre-cutoff, so the report writer should not present them as achievable performance.

### Gaps
- FinRobot: I found no evaluation results in this pass.
- TradingAgents' GOOGL and AMZN numbers, and the Alpha Illusion paper's one-year reproduction numbers, were not captured.
- CryptoTrade's own headline returns per period (vs. the 22.59% ETH buy-and-hold) were not in the snippets.
- "Contagion on the Trading Floor: How Adversarial Signals Spread in Multi-Agent Trading Systems" ([arXiv 2609.19789](https://arxiv.org/pdf/2609.19789), Sep 2026) is likely relevant to a security-minded user, since injected or adversarial news could spread through agent roles. Only its title was retrieved.

---

## 3. LLMs reading chart images (vision) for technical analysis

### Takeaway
The most direct 2026 benchmark found that current vision-language models (VLMs: Claude, Gemini, GPT, Qwen) have a real but weak and biased ability to forecast from candlestick images. They work mostly in persistent trends, ignore the requested horizon, and show systematic bullish or bearish leanings. Studies that frame a VLM as an **explainer** of a chart, rather than a forecaster, are more positive. Most "image accuracy" results are from CNNs, not LLMs.

### Cited Findings
- **"Do VLMs Truly 'Read' Candlesticks?"** (Kaiqi Hu et al., arXiv 2604.12659, Apr 2026)
  - Setup: each sample pairs a daily and a weekly candlestick chart (with moving averages and a volume subplot) for one stock and date. Seven VLMs were tested: Claude haiku-4.5 and sonnet-4.5, Gemini 2.5 Flash and Pro, GPT-4o and GPT-5-mini, and Qwen — [arXiv](https://arxiv.org/abs/2604.12659); [arXiv HTML](https://arxiv.org/html/2604.12659v1)
  - Abstract: "weak predictive power, significant biases, and limited sensitivity to forecast horizons and prompts" — [arXiv](https://arxiv.org/abs/2604.12659)
  - Data: aligned visual and numeric datasets from HS300 and S&P 500 OHLCV, a 30-day return target, confusion-matrix and IC/Rank IC metrics, and an XGBoost numeric baseline — [Onepagecode Substack](https://onepagecode.substack.com/p/quant-research-do-vision-language)
  - Most VLMs did well only in persistent up or down trends and poorly in more common conditions. Some models leaned bullish (GPT-5-mini positive bias) and others bearish — [Onepagecode](https://onepagecode.substack.com/p/quant-research-do-vision-language); [alphaXiv](https://www.alphaxiv.org/abs/2604.12659)
  - Horizon mismatch: although asked for 30-day returns, almost all VLMs' predictions correlated much more with **5-day** actual returns — [Onepagecode](https://onepagecode.substack.com/p/quant-research-do-vision-language)
  - XGBoost was more stable in ranking (ICIR), while Claude-sonnet-4.5 with thinking showed the best directional and ranking power among the VLMs (secondary summary) — [Onepagecode](https://onepagecode.substack.com/p/quant-research-do-vision-language)
  - The paper says the authors' earlier work suggests state-of-the-art multimodal LLMs "still struggle with the fine-grained geometric perception required for reliable candlestick and chart pattern identification" — [arXiv HTML](https://arxiv.org/html/2604.12659v1)
- **Explainable multimodal framework for Bitcoin candlestick charts** (ACM): it uses Gemini 2.5 Flash on monthly BTC candlestick images as a low-latency analysis tool. It explicitly sets aside investment validity and says the approach suits **explaining recent direction better than forecasting** — [ACM DL](https://dl.acm.org/doi/10.1145/3815970.3815982)
- **Ntale, "AI Trading: Evaluating LLMs for Technical Market Analysis"** (Georgia Tech, arXiv 2607.15414 / SSRN, Jul 2026)
  - Five LLMs (GPT-4 Turbo, Claude 3 Opus, Gemini 1.5 Pro, Llama 3 70B, FinGPT) on candlestick pattern recognition from OHLCV **numbers** (not images), BUY/SELL/HOLD signals, simulated backtests and report comprehension.
  - GPT-4 Turbo had the best annualized return and Sharpe among the general models; it and FinGPT beat a passive S&P 500 benchmark "under the tested conditions".
  - Failure modes in all models: **numerical hallucination**, context-window limits, inconsistent performance in sideways markets — [arXiv](https://arxiv.org/abs/2607.15414); [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7119484)
- CNNs, not LLMs:
  - Market-strength prediction from candlestick images peaked at about 0.7 accuracy, below more complex time-series models. Adding detected candlestick patterns did not help — [arXiv 2501.12239](https://arxiv.org/abs/2501.12239)
  - A 2026 crypto regime study found raw candlestick images beat mathematically derived image encodings, and adding volume bars and moving averages **degraded** performance — [arXiv 2605.00875](https://arxiv.org/html/2605.00875v1)
- Practitioner systems that feed chart images to an LLM:
  - FinAgent uses Kline chart images (self-reported gains; see section 2) — [arXiv](https://arxiv.org/html/2402.18485v3)
  - JoCoding's gpt-bitcoin v3 captures chart screenshots with Selenium and sends them to GPT-4o along with OHLCV, indicators, order book, news and the Fear & Greed index — [GitHub gpt-bitcoin](https://github.com/youtube-jocoding/gpt-bitcoin); [autotrade_v3.py](https://github.com/youtube-jocoding/gpt-bitcoin/blob/main/autotrade_v3.py)

### Inferences
- For this project, chart images are more useful **for the human reader of the PDF** than as the LLM's main input. Trading-relevant numbers (levels, indicators, model probabilities) should be computed in code and passed to Claude as text.
- If Claude is shown the chart, ask it to **describe and explain** (trend, structure, where the computed levels sit), not to forecast. The evidence points to weak, horizon-insensitive, biased image-based forecasts.
- Numerical hallucination is a documented failure, so every number in Claude's narrative should be checked against the computed values before the PDF is sent.
- Directional bias differs by model. Using one model for "several perspectives" may share one hidden bias across all of them; noting the model's bias in the report is advisable.

### Gaps
- I did not obtain exact accuracy or IC numbers per VLM from arXiv 2604.12659.
- One search summary said a paper found VLMs "more accurate in bear markets than bull markets" and "candlestick charts outperformed equivalent tabular data". I could not confirm which paper this came from, so it is unverified.
- The IJACSA 2025 paper comparing vision-instruct LLMs with vision-based deep learning ([thesai.org PDF](https://thesai.org/Downloads/Volume16No4/Paper_2-Comparing_Vision_Instruct_LLMs_Vision_Based_Deep_Learning.pdf)) was not read. Its findings are unknown.
- A Medium overview's claim of 96% accuracy from ViT plus price features ([Medium](https://medium.com/@gwrx2005/computer-vision-for-cryptocurrency-trading-chart-analysis-sentiment-and-anomaly-detection-870764fca604)) is secondhand and unverified.
- Multimodal finance benchmarks MME-Finance ([arXiv 2411.03314](https://arxiv.org/html/2411.03314v1)) and FinMTM ([arXiv 2602.03130](https://arxiv.org/html/2602.03130)) exist, but their chart-reading results were not retrieved.
- I found no head-to-head study on **BTC perps at 1-hour candles** comparing image input with numeric input for Claude specifically.

---

## 4. Korean cases (GPT/AI 비트코인 자동매매: JoCoding and others)

### Takeaway
The best-known Korean project, JoCoding's (조코딩) "GPT에게 맡기는 AI 비트코인 투자 자동화" (Upbit spot; later a Binance futures course), is a well-documented build tutorial. Its published performance is short-window and self-reported, and the creator himself said buy-and-hold did better. Independent Korean tests (an OKKY user's live trial, the Herald Economy "초파리 트레이더" (fruit-fly trader) experiments, and a public GitHub repo that tested 7 LLM-trading setups) consistently found LLM-driven trading underperformed holding or simple rules. Overtrading and badly calibrated "win probabilities" were the main reasons.

### Cited Findings
- **JoCoding's open-source system** ([GitHub youtube-jocoding/gpt-bitcoin](https://github.com/youtube-jocoding/gpt-bitcoin))
  - Inputs: daily (30 days) and hourly (24 hours) OHLCV, technical indicators, order book, news via SerpApi, the Fear & Greed index, and chart images captured with Selenium and analyzed by GPT-4o.
  - Versions went from `autotrade.py` (gpt-4-turbo-preview) to `autotrade_v3.py` (gpt-4o plus Selenium), and v3 stores past decisions in SQLite — [autotrade_v3.py](https://github.com/youtube-jocoding/gpt-bitcoin/blob/main/autotrade_v3.py); [instructions_v3.md](https://github.com/youtube-jocoding/gpt-bitcoin/blob/main/instructions_v3.md)
- **Courses and book**
  - Course: a system that "trades by judging recent news and charts comprehensively" — [jocoding.net course](https://jocoding.net/courses/gpt-bitcoin-trading/)
  - A separate membership course covers AI-driven **Binance futures** auto-trading — [jocoding.net futures course](https://jocoding.net/courses/gpt-bitcoin-futures/); [YouTube membership playlist](https://www.youtube.com/playlist?list=PLU9-uwewPMe0-oP-LAZFLr2-F0TF8jHdO); [YouTube: 선물거래 편 1~7강](https://www.youtube.com/watch?v=SDFROshkgvQ)
  - Book "조코딩의 AI 비트코인 자동 매매 시스템 만들기" (Hanbit Media, Apr 2025) covers the Upbit API, OpenAI API and AWS deployment — [Hanbit](https://m.hanbit.co.kr/store/books/book_view.html?p_code=B5063161940). One reader built the program in about 2 weeks — [Aladin review](https://blog.aladin.co.kr/724135178/16473018); see also [TokenPost book club](https://www.tokenpost.kr/news/general/257308)
- **Creator's self-reported performance**
  - Nov 2024, with o1-preview: "약 2달간 돌리고 있는데 수익률이 35% 정도" (about 35% over about 2 months). He also admitted "최근 비트코인이 많이 올라서 사실 가만히 들고 있는 게 더 이득" (because BTC rose a lot, just holding would actually have earned more) — [JoCoding on X](https://x.com/youtubejocoding/status/1859786348389073375)
  - Feb 2025: live return pages for o3-mini and deepseek-r1 32B. Early figures were reported as +1.54% (o3-mini) vs. −3.09% (r1 32B) at about day 2, which is too short to mean anything — [JoCoding on X](https://x.com/youtubejocoding/status/1886778908965752899)
- **Independent user trial (OKKY; date not captured)**
  - Built on JoCoding's code with added stop-loss and indicators, starting with ₩590,000 on BTC spot for about 1 month.
  - Result: current plus realized return −11.56 vs. market return −9.79%.
  - "아직 AI가 오작동 하는 경우도 많았어요" (the AI still malfunctioned often) — [OKKY](https://okky.kr/articles/1528250)
- **Herald Economy "초파리 트레이더" series (Oct 2026; simulated trades, not advice)**
  - Part 3: a local AI traded BTC **584 times in four days and lost 19.1%**. The headline says 538 trades, which conflicts. A virtual fruit-fly brain traded **3 times in 14 days for +3.16%**. Trades the AI called "50% chance to win" actually won **11%** of the time — [Herald (EN) part 3](https://biz.heraldcorp.com/article/10894633); [Herald headline](https://www.heraldk.com/article/2026101004102478293)
  - Part 7: the AI read BTC, ETH, XRP and SOL charts every 15 minutes and chose buy, wait or sell. It made 162 buy attempts in 7 days. All 5 trades that ended in stop-loss had AI-estimated win probabilities of 42–48%, below 50%.
  - Part 7 final results: AI −4.79%, rule-based fly −4.24%, BTC hold −2.61%. A fixed-rule control made 70 trades for −4.92%, averaging −0.29% per trade vs. the AI's −2.88% — [Herald (EN) part 7](https://biz.heraldcorp.com/article/10910359); [Herald (KR)](https://biz.heraldcorp.com/article/10910354)
  - The fly brain trained on rewards learned mainly to "stay still" — [Herald](https://www.heraldk.com/article/2026100319102481219)
- **Public Korean verification repo** ([GitHub iam-raccoon/llm-trading-backtest](https://github.com/iam-raccoon/llm-trading-backtest); formerly iamracco0n)
  - Its answer to "LLM이 스스로 판단해 거래하면 돈을 버는가?" (do LLMs make money trading on their own judgment?) is "아니오" (no).
  - It tested 7 LLM setups (3 input types, factor generation, risk gate, latest-model swap, multi-agent) across crypto, Korean equities, post-earnings drift (PEAD) and LLM factor mining. All were rejected, and **only two rule strategies without an LLM survived**.
  - It controlled for look-ahead, survivorship, multiple testing and trading costs, and also records that rule strategies failed six times.
  - The same author's live-bot repo warns that one strategy's sign flipped across windows (+25.3% over 118 days and 16 assets vs. −1.05% in another window) — [edge-llm-trading-bot](https://github.com/iam-raccoon/edge-llm-trading-bot)
- **Korean guidance and press**
  - Citing the exchange GOPAX: there can be "상당한 차이" (a considerable gap) between backtests and live results. Start small and set loss limits and stop conditions in advance — [이투데이](https://www.etoday.co.kr/news/view/2642078)
  - An Upbit GPT auto-trading guide warns that GPT can repeat the same signal (duplicate orders) or keep buying during a crash, so risk controls are needed — [CodeLenz/encytree, part 7](https://encytree.com/entry/%EC%97%85%EB%B9%84%ED%8A%B8-%EB%B9%84%ED%8A%B8%EC%BD%94%EC%9D%B8-GPT-%EC%9E%90%EB%8F%99%EB%A7%A4%EB%A7%A4-7%ED%8E%B8-%EB%A6%AC%EC%8A%A4%ED%81%AC-%EA%B4%80%EB%A6%AC-%EB%B0%8F-%EC%A4%91%EB%B3%B5-%EB%A7%A4%EB%A7%A4-%EB%B0%A9%EC%A7%80)
  - Korean outlets covered Alpha Arena with different snapshots — [더구루](https://www.theguru.co.kr/news/article.html?no=94001); [MS TODAY](https://www.mstoday.co.kr/news/articleView.html?idxno=99240)
  - [older, Feb 2023] An early Korean post used ChatGPT to write a Bitcoin auto-trading program — [tykimos blog](https://tykimos.github.io/2023/02/16/ChatGPT_Auto_Trading_Program_in_Python/)

### Inferences
- The Korean evidence matches the global evidence. When an LLM is trusted to pull the trigger, it tends to **overtrade**, and the probabilities it states are **not calibrated**. Holding, or a simple rule with fewer trades, often did better.
- This project's choice to have the user place orders manually, with code-based models doing the analysis, avoids the main failure mode seen in these Korean projects (autonomous, frequent LLM orders).
- The report should still make "no trade / stay flat" a normal, first-class outcome. The fruit-fly lesson is that inactivity beat hyperactivity.
- Any "confidence" or "win probability" shown in the PDF should come from a model calibrated on historical data, never from the LLM's own self-estimate.

### Gaps
- No independently audited, long-period live P&L exists for JoCoding's system. Its "live return pages" (Feb 2025) results beyond the first days were not found.
- I found no Korean community statistics on how many course users made or lost money.
- The OKKY post's date and the final outcome after 1 month were not captured.
- I did not find Korean results specific to the Binance-futures version, such as leverage outcomes.
- The YouTube video "5일 만에 만든 AI 자동매매, 실제로 돌려봤더니..." (I ran an AI auto-trader built in 5 days) — [YouTube](https://www.youtube.com/watch?v=_pSLInJSIpU) — was not reviewed.

---

## 5. Evidence on LLM forecasting of financial prices (time-series, knowledge-cutoff contamination, random-walk-type findings)

### Takeaway
On numeric time series, the LLM part of popular "LLM forecasters" adds nothing measurable (NeurIPS 2024 ablations). LLMs show real but short-lived, fading predictive value on **text** (news headlines). Backtests of LLMs on historical prices are heavily contaminated by memorization: reported Sharpe drops by about 50–60% after the training cutoff, and effective cutoffs can be months earlier than vendors state.

### Cited Findings
- **Tan et al., "Are Language Models Actually Useful for Time Series Forecasting?"** (NeurIPS 2024; arXiv 2406.16964) [older, Jun 2024]
  - Removing the LLM, or replacing it with a basic attention layer, "does not degrade forecasting performance — in most cases the results even improve". Randomly initialized LLMs did about as well as pretrained ones.
  - These methods cost orders of magnitude more compute, did not help in few-shot settings, and did not capture sequential dependencies — [arXiv](https://arxiv.org/abs/2406.16964); [NeurIPS proceedings](https://proceedings.neurips.cc/paper_files/paper/2024/hash/6ed5bf446f59e2c6646d23058c86424b-Abstract.html); [Emergent Mind](https://emergentmind.com/papers/2406.16964)
- **Lopez-Lira & Tang, "Can ChatGPT Forecast Stock Price Movements?"** (arXiv 2304.07619; first 2023, revised to Oct 2025)
  - GPT-4 scores from news headlines predict returns for the next 1–2 days but not after.
  - Strategy returns decline as LLM adoption rises, consistent with markets becoming more efficient — [arXiv](https://arxiv.org/abs/2304.07619); [arXiv v6](https://arxiv.org/html/2304.07619v6)
  - In Apr 2023 the author predicted that predictability would decline as more people use these tools — [CNBC](https://www.cnbc.com/2023/04/12/chatgpt-may-be-able-to-predict-stock-movements-finance-professor-says.html)
  - The later version stresses next-day predictability that is stronger for small caps and after bad news — [Larry Swedroe summary](https://larryswedroe.substack.com/p/can-chatgpt-forecast-stock-price)
- **Glasserman & Lin** (arXiv 2309.17322, Sep 2023) [older]
  - GPT-3.5 headline sentiment, in-sample Jan 2015–Sep 2021 and out-of-sample Oct 2021–Dec 2022.
  - Anonymized headlines performed **better** in-sample: a "distraction effect" from general company knowledge outweighed look-ahead bias, most strongly for large firms. Out of sample, look-ahead was not a concern but distraction still occurred — [arXiv](https://arxiv.org/abs/2309.17322); [arXiv HTML](https://arxiv.org/html/2309.17322v1)
  - Counterpoint: anonymization can strip useful signal from earnings calls — [arXiv 2511.15364](https://arxiv.org/html/2511.15364v1)
- **Contamination measurements and tools (2025–2026)**
  - Profit Mirage: Sharpe decay of 51.48–62.23% after cutoff for leading agents — [arXiv](https://arxiv.org/html/2510.07920v1)
  - Look-Ahead-Bench (arXiv 2601.13770, Jan 2026): point-in-time models stay stable or improve as they scale, while standard models show a "scaling paradox" when look-ahead is present — [GitHub](https://github.com/benstaf/lookaheadbench); [RePEc](https://ideas.repec.org/p/arx/papers/2601.13770.html)
  - FinCosmos (arXiv 2611.07464, Nov 2026): models memorize pre-cutoff financial values, and effective cutoffs can fall months before vendor-reported dates — [arXiv](https://arxiv.org/html/2611.07464)
  - "Summoning the Oracle" / FinCAD (May 2026): calls this "parametric look-ahead bias" and notes most trading-agent papers use short windows without bias control. Its decoding-time fix is heuristic and may not transfer to black-box APIs — [alphaXiv](https://www.alphaxiv.org/abs/2605.24564); [arXiv](https://arxiv.org/pdf/2605.24564)
  - The Self-Driving Portfolio paper: LLM agents add their own look-ahead bias even when the quant components are backtested properly — [arXiv 2604.02279](https://arxiv.org/pdf/2604.02279)
  - Agentic Trading survey: news timestamps often reflect publication time, not when a pipeline could actually use the item, which inflates backtests — [arXiv 2605.19337](https://arxiv.org/html/2605.19337v1)
  - Mitigations:
    - Anonymize tickers and identifiers — [arXiv 2603.17692](https://arxiv.org/html/2603.17692v1)
    - Test only after the cutoff — [arXiv 2602.23330](https://arxiv.org/pdf/2602.23330)
    - Black-box hindsight audits — [HindsightBench, arXiv 2607.18867](https://arxiv.org/pdf/2607.18867)
    - Masked vs. unmasked replay probe; its README admits it can under-detect bias — [llm-lookahead-probe](https://github.com/rajib2k5/llm-lookahead-probe)
  - Point-in-time LLMs:
    - ChronoGPT/ChronoBERT (yearly checkpoints 1999–2024) gave Sharpe ratios comparable to Llama 3.1, with no significant difference — [ScienceDirect (JFE)](https://www.sciencedirect.com/science/article/pii/S0304405X26001455)
    - A Jul 2026 paper argues the gap is mostly about scale. A Substack reports its PIT-4B beats ChronoGPT-base on mega-cap out-of-sample Sharpe, 0.80 vs. 0.56 (unverified) — [arXiv 2607.11889](https://arxiv.org/pdf/2607.11889); [Substack](https://thespecification.substack.com/p/the-open-point-in-time-llm-and-what)
- **Random-walk-type evidence (adjacent only)**
  - A GPT-2-architecture model **trained** on crypto data had lower error than a random walk on BTC, ETH, XRP, XLM and SOL. This is a trained transformer, not a prompted LLM — [MDPI Symmetry](https://www.mdpi.com/2073-8994/18/1/32)
  - The PRICE study (Sep 2026) on LLM adaptation for BTC forecasting: domain adaptation matters, and at short horizons "output reliability" is a bigger bottleneck than error build-up — [arXiv 2609.05235](https://arxiv.org/pdf/2609.05235)
  - A hedge-fund-perspective review warns against naive LLM use and notes most LLM stock forecasters lack regime handling — [arXiv 2605.05211](https://arxiv.org/pdf/2605.05211)
- Related: in the VLM benchmark, predictions followed 5-day rather than the requested 30-day returns (see section 3) — [Onepagecode](https://onepagecode.substack.com/p/quant-research-do-vision-language)

### Inferences
- Claude's training data almost certainly includes BTC price history up to its cutoff. So **any backtest in which Claude reads historical BTC charts is contaminated** and cannot validate the LLM part. Only forward-logged hourly reports, or charts with dates and price scale masked, can.
- The ML models this project trains on historical data can still be validated with ordinary walk-forward tests, because they do not memorize the future the way an LLM does. That only holds if feature timestamps are aligned correctly.
- LLMs are best placed on text-like inputs (news, funding or OI commentary, explaining model output), where their value is short-lived. Precise price prediction should stay with the trained numeric models.

### Gaps
- I found no paper that directly tests a prompted GPT-4- or Claude-class LLM against a random walk or naive forecast on BTC prices (for example with Diebold-Mariano tests). This stays an open question in these notes.
- Two potentially relevant items were found by title only:
  - The AEA 2026 paper "What Does ChatGPT Make of Historical Stock Returns?" — [AEA](https://www.aeaweb.org/conference/2026/program/paper/zNrQ4Yn6)
  - An MDPI study of LLM decisions from price-only inputs across countries — [MDPI](https://www.mdpi.com/2504-4990/8/4/104)
- The datasets in Tan et al. were not confirmed. They are probably general time-series benchmarks, not crypto.

---

## 6. Practical lessons: what LLMs are good and bad at in trading systems, and recommended guardrails

### Takeaway
Across competitions, benchmarks, papers and Korean field tests, LLMs are useful for **reading and summarizing text and explaining analysis in a structured way**. They are unreliable at **numeric prediction, calibrated probabilities, trade frequency and leverage discipline**. The working pattern is: deterministic code computes the signals and risk, the LLM explains them, and a human decides. Evaluation should be forward, cost-aware, leakage-controlled and compared against buy-and-hold and simple rules.

### Cited Findings
- **Good at**
  - News and headline sentiment with short-horizon predictive value, which fades as adoption grows — [Lopez-Lira & Tang](https://arxiv.org/abs/2304.07619)
  - Producing structured rationales and plans (justification, target, stop, invalidation) when the format is required — [nof1 prompt gist](https://gist.github.com/wquguru/7d268099b8c04b7e5b6ad6fae922ae83)
  - VLMs as **explainers of recent chart direction** rather than forecasters — [ACM DL](https://dl.acm.org/doi/10.1145/3815970.3815982)
- **Bad at**
  - Numbers: numerical hallucination in all five tested LLMs — [Ntale, arXiv 2607.15414](https://arxiv.org/abs/2607.15414); LLM parts of time-series forecasters are unnecessary — [Tan et al.](https://arxiv.org/abs/2406.16964)
  - Calibration: "50% win chance" trades actually won 11% of the time — [Herald](https://biz.heraldcorp.com/article/10894633); stop-loss trades were entered at self-estimated 42–48% — [Herald](https://biz.heraldcorp.com/article/10910359)
  - Overtrading and fees:
    - Gemini 2.5 Pro: 238 trades and $1,331 in fees in Alpha Arena S1 — [Admiral Markets](https://admiralmarkets.com/education/articles/automated-trading/claude-vs-chatgpt-vs-grok-trading)
    - A local AI: 584 trades in 4 days for −19.1% — [Herald](https://biz.heraldcorp.com/article/10894633)
  - Leverage and drawdown: 4 of 6 frontier models lost 42–59% in S1 — [TradeRank](https://www.traderank.ai/alpha-arena-leaderboard); in S1.5's forced-max-leverage mode entries reached −96.15% — [TradeRank](https://www.traderank.ai/alpha-arena-leaderboard)
  - Regime generalization:
    - Too conservative in bull markets, too aggressive in bear markets — [FINSABER](https://arxiv.org/abs/2505.07078)
    - Bullish bias — [StockBench via Emergent Mind](https://www.emergentmind.com/topics/stockbench)
    - VLMs work only in persistent trends — [Onepagecode](https://onepagecode.substack.com/p/quant-research-do-vision-language)
    - Cross-market Sharpe correlation about 0 — [LiveTradeBench](https://arxiv.org/html/2511.03628v1)
  - More thinking is not always better: "over-deliberation" degraded consistency — [Hugging Face Papers / LiveTradeBench](https://huggingface.co/papers/2511.03628). General leaderboard rank is not predictive — [alphaXiv](https://www.alphaxiv.org/overview/2511.03628v1)
  - Mechanical failures: duplicate orders on repeated signals and "infinite buying" during crashes — [CodeLenz/encytree](https://encytree.com/entry/%EC%97%85%EB%B9%84%ED%8A%B8-%EB%B9%84%ED%8A%B8%EC%BD%94%EC%9D%B8-GPT-%EC%9E%90%EB%8F%99%EB%A7%A4%EB%A7%A4-7%ED%8E%B8-%EB%A6%AC%EC%8A%A4%ED%81%AC-%EA%B4%80%EB%A6%AC-%EB%B0%8F-%EC%A4%91%EB%B3%B5-%EB%A7%A4%EB%A7%A4-%EB%B0%A9%EC%A7%80); frequent malfunctions in a user's live trial — [OKKY](https://okky.kr/articles/1528250)
- **Guardrails recommended or used in the sources**
  - Hard risk rules: start small and preset loss limits and stop conditions — [이투데이](https://www.etoday.co.kr/news/view/2642078). Rule-constrained AI agents avoided liquidation while 43% of humans were liquidated — [Aster/Chainwire](https://chainwire.org/2026/01/14/aster-human-vs-ai-live-trading-competition-season-1-concludes/)
  - Validate LLM output against a schema on the server before acting — [TradeRank prompt guide](https://www.traderank.ai/blog/ai-trading-prompts-engineering). Make the model state invalidation conditions and feed the plan back on later calls — [nof1 prompt gist](https://gist.github.com/wquguru/7d268099b8c04b7e5b6ad6fae922ae83)
  - Leakage control:
    - Evaluate only after the cutoff — [arXiv 2602.23330](https://arxiv.org/pdf/2602.23330)
    - Anonymize — [arXiv 2603.17692](https://arxiv.org/html/2603.17692v1); [Glasserman & Lin](https://arxiv.org/abs/2309.17322)
    - Align timestamps to when data became usable — [arXiv 2605.19337](https://arxiv.org/html/2605.19337v1)
    - Build leakage safety into the structure; statistics alone do not catch it — [Gencay, arXiv 2608.27734](https://arxiv.org/pdf/2608.27734)
  - Honest reporting:
    - Treat backtest alpha as prototype evidence and follow a P1–P6 reporting protocol — [Alpha Illusion](https://arxiv.org/html/2605.16895v1); [Pith](https://pith.science/paper/2605.16895)
    - Count every trial — [Gencay](https://arxiv.org/pdf/2608.27734)
    - Test longer windows and wider universes against buy-and-hold — [FINSABER](https://arxiv.org/abs/2505.07078)
    - Re-test across windows because signs can flip — [iam-raccoon](https://github.com/iam-raccoon/edge-llm-trading-bot)
  - Human plus AI rather than AI alone: Aster concluded that future competitiveness comes from collaboration between humans and AI — [Chainwire](https://chainwire.org/2026/01/14/aster-human-vs-ai-live-trading-competition-season-1-concludes/)

### Inferences
These are suggestions for this project (Binance BTCUSDT perps, hourly PDF via Telegram, manual orders), drawn from the evidence above:
1. **Division of labor.** Trained models and fixed rules produce direction probabilities, levels, position size, leverage and liquidation distance in code. Claude only explains these numbers from several "trader perspectives" (trend follower, mean-reversion, risk manager, a contrarian bear or bull). It never picks leverage or prices itself. This mirrors the evidence that LLM autonomy plus leverage loses money, while LLM explanation is a strength.
2. **Number integrity.** Pass computed values to Claude as structured data. After generation, check the text automatically: every number in Claude's text must match a computed value, otherwise flag or remove it. This guards against the documented numerical hallucination.
3. **Calibration.** Show probabilities only from the historically calibrated model, with a reliability check. Do not show Claude's self-stated confidence as a probability.
4. **No-trade as default.** Make "관망" (wait and see) a normal, prominent outcome, and limit how often the report recommends a change. Fewer, higher-quality calls guard against overtrading and fees.
5. **Leverage caps in code.** Leverage and risk should be computed in code with hard caps (for example, maximum risk per trade as a fraction of equity, and a minimum distance to liquidation). Alpha Arena's high-leverage outcomes (−42% to −96%) show why the LLM should not set leverage.
6. **Evaluation.** Keep a forward log of every hourly call, recording paper P&L after fees and funding. Compare it with BTC buy-and-hold and a simple rule baseline. Count every strategy variant tried. This matches the project's existing `backtest/TRIALS.md` and fixed-spec practice, and the multiple-testing warnings from FINSABER, Gencay and the Alpha Illusion paper.
7. **Contamination.** Do not use "Claude explaining past charts" as proof the system works. Claude may remember what happened next.
8. **Cost.** One structured Claude call per hour with multiple perspective sections is far cheaper than a 15-call TradingAgents-style debate (about 360 calls a day).
9. **Security.** The user is a security professional. Untrusted text (news, social posts) fed to the LLM can carry injected instructions or adversarial signals. Keep such text out of any path that can change numbers or orders. The "Contagion on the Trading Floor" paper title suggests this is an active research topic; its content was not retrieved.

### Gaps
- Few sources measure the value of LLM **explanations** for human decision quality, for example whether multi-perspective commentary improves a manual trader's results. LATTICE ([arXiv 2604.26235](https://arxiv.org/pdf/2604.26235)) looks relevant but was not read.
- No controlled study was found on LLM-assisted manual trading of crypto perps, as opposed to autonomous trading.
- The official nof1 lessons document and the Alpha Illusion P1–P6 items were not retrieved verbatim.
