# Building a trustworthy ML + LLM market-analysis tool for BTC perpetual futures: practitioner best practices (as of 2026-11-07)

> **How these notes were made.** The session's network allowlist blocked direct page fetches (en.wikipedia.org, www.freqtrade.io, www.binance.com, fapi.binance.com all refused). So every finding below comes from web-search result summaries of the cited pages. Claude API facts come from the bundled Claude API reference, which was cached on 2026-10-06 and points to the official doc URLs cited. Re-check exact numbers at the URL before putting them in code or config. Items marked **(calc)** are my own arithmetic on the cited inputs. Secondary or vendor sources are flagged where they appear.

## 1. Reference architecture scaled down for one person (data pipeline, OHLCV features, feature store, model registry, scheduled retraining, drift monitoring)

### Takeaway
Copy the *loop structure* of Qlib's online serving and FreqAI's retrain-and-abstain cycle, not their infrastructure. The essentials are:
- one code path shared by backtest and live;
- an append-only raw data store;
- versioned features and models, each with metadata;
- scheduled retraining with a promotion gate;
- an explicit "no prediction" output when the live inputs look unlike the training data.

At one-person scale, a folder of Parquet/SQLite files plus JSON metadata plus cron is a legitimate feature store and model registry. The real danger is hidden technical debt and look-ahead bugs, not missing tooling.

### Cited Findings
- **Qlib online serving.** It has four parts: Online Manager, Online Strategy, Online Tool and Updater. The periodic routine is "Update predictions -> Prepare tasks -> Prepare online models -> Prepare signals". `OnlineManager.routine` runs this per strategy and records which models were online at each time. `RollingStrategy` keeps the latest rolling model as the online model, and `simulate` replays the routine through history. The docs say the user must keep the data source updated themselves, and that the supported mode is daily prediction updates for the next trading day. — [Qlib docs: Online Serving](https://qlib.readthedocs.io/en/latest/component/online.html); [Qlib v0.8.3 online.rst](https://github.com/microsoft/qlib/blob/v0.8.3/docs/component/online.rst)
- **FreqAI training window and retraining.** `train_period_days` is the width of the sliding training window (a positive integer, in days). `live_retrain_hours` sets how often the model retrains in dry/live runs; it is a float above 0, and the default 0 means "retrain as often as possible". — [FreqAI parameter table (latest)](https://www.freqtrade.io/en/latest/freqai-parameter-table); [2023.3 version](https://www.freqtrade.io/en/2023.3/freqai-parameter-table/)
- **FreqAI features and outlier handling.**
  - It advertises "self-adaptive retraining" during live deployment, and outlier removal on both training and prediction data.
  - `feature_engineering_expand_all` automatically expands user-defined features across `include_timeframes`, `include_shifted_candles` and `include_corr_pairs`. Features must carry a `%` prefix.
  - If a live data point's Dissimilarity Index (DI) is above `DI_threshold`, FreqAI sets `do_predict` to 0 and rejects that prediction.
  - SVM and DBSCAN outlier-removal options also exist.
  - Sources: [freqai.md (code mirror)](https://codeclimate.com/github/freqtrade/freqtrade/docs/freqai.md/source); [freqai-configuration.md (third-party fork mirror, so verify against the official docs)](https://github.kxpsado.workers.dev/rooftopsolarsa/freqtrade/blob/develop/docs/freqai-configuration.md)
- **Google's MLOps maturity levels.** Level 0 is a fully manual build and deploy (one summary says releases happen only 2-4 times a year). Level 1 automates the ML pipeline, which gives continuous training. Level 2 adds CI/CD for the pipeline code itself. These are secondary summaries; Google's guide was not retrieved. — [ML-Notes summary](https://aayushdw.github.io/ML-Notes/01---ML--and--AI-Concepts/MLOps--and--Infrastructure/MLOps-Level-0-to-Level-2); [mlops-for-all](https://mlops-for-all.github.io/en/docs/introduction/levels); [review of Google's article](https://laszlo.substack.com/p/article-review-mlops-continuous-delivery)
- **Sculley et al., "Hidden Technical Debt in ML Systems" (NeurIPS 2015).** Quick ML wins are not free; real systems commonly build up "massive ongoing maintenance costs". The named risk factors are boundary erosion, entanglement, hidden feedback loops, undeclared consumers, data dependencies, configuration issues and changes in the external world. — [Google Research](https://research.google/pubs/hidden-technical-debt-in-machine-learning-systems/); [NeurIPS page](https://neurips.cc/virtual/2015/poster/5680)
- **Ernest Chan on look-ahead bias (secondary summary).** If backtesting and live trading use the same code, that code cannot look ahead to the next bar. His test for look-ahead bias:
  1. Save the program's recommended positions.
  2. Re-run on truncated data and align the two outputs.
  3. Any difference means the backtest has look-ahead bias.
  - Source: [Benzinga summary of Chan](https://www.benzinga.com/markets/13/05/3582742/backtesting-pitfalls)
- **QuantStart on separate research and live code.** Code often ends up written twice (research and live), which adds bugs. For-loop backtesters are prone to look-ahead bias through indexing bugs. — [QuantStart](https://www.quantstart.com/articles/Should-You-Build-Your-Own-Backtester)
- **López de Prado's ML-fund pitfalls.** Seven of his ten are confirmed in a summary: the "Sisyphus paradigm", integer differentiation, inefficient sampling, wrong labeling, weighting of non-IID samples, cross-validation leakage and backtest overfitting. A CXO restatement adds two pieces of advice: organize work as an assembly line of specialists, and treat extensive repeated backtesting with suspicion. — [Quantpedia summary](https://quantpedia.com/why-machine-learning-funds-fail/); [GARP white paper](https://www.garp.org/white-paper/the-10-reasons-most-machine-learning-funds-fail); [CXO Advisory](https://www.cxoadvisory.com/big-ideas/10-steps-to-becoming-a-better-quant)

### Inferences
- **A minimal stack for this project** (Mac or small server, hourly cadence). Each step lives in one module and is used by both backtest and live, following Chan's same-code rule.
  1. **Ingest.** Fetch only *closed* 1h klines, plus mark price and funding history. Append them to a raw table keyed by UTC open time. Check for gaps and duplicates. Never let the still-forming candle reach features or labels.
  2. **Features** (pure functions of closed bars). Use returns, realized volatility / ATR, multi-timeframe aggregates (FreqAI's `include_timeframes` idea), lagged copies (`include_shifted_candles`), funding/basis, and a volatility-normalized price position. Store them with a `feature_set_version` hash. That table is the "feature store".
  3. **Labels.** See Q2.
  4. **Validation.** See Q3.
  5. **Registry.** Save each model in `models/<version>/` with the model file and a `meta.json`. The metadata holds the git commit, data window, feature hash, label spec, walk-forward metrics, calibration parameters, and the cumulative number of trials (which feeds the DSR/PBO checks in Q3). Run champion/challenger: a new model is promoted only if it beats the current one on the same untouched out-of-sample window by a margin fixed in advance.
  6. **Hourly serving.** Follow the Qlib-style routine: update data, then predict, then (on schedule) retrain, then build the signal card. The deterministic "signal card" JSON is produced first; the chart PDF and the LLM narration (Q5) are built from it.
  7. **Monitoring.**
     - Rolling Brier score or log-loss compared with a naive base-rate forecaster.
     - Realized coverage of the prediction intervals (Q2).
     - A DI-like out-of-distribution score that forces "관망 (no view)".
- **Sizing it to Google's levels.** This is roughly Level 1 (automated continuous training) without Level 2. The existing GitHub CI (pytest + gitleaks) already covers the part of Level 2 that matters at this scale.
- **Retraining cadence is a hyperparameter.** It should be picked inside the walk-forward backtest (for example weekly vs. monthly, with a fixed sliding window as in FreqAI's `train_period_days`), not chosen by feel. FreqAI's "retrain as often as possible" default adds compute and model churn without a guaranteed benefit.
- **Sculley's risks have direct analogues here.**
  - A hidden feedback loop forms if trades taken *because of* the signal are logged and then reused as training data.
  - The LLM narration step is an "undeclared consumer" of model internals: if the JSON schema changes, the narration breaks silently. Version the schema.
- **López de Prado's "inefficient sampling".** With only hourly klines, time bars are the practical default. Volume or dollar bars need trade-level data (for example aggTrades). Dividing returns by rolling volatility is a cheap partial fix for unequal information per bar.

### Gaps
- FreqAI and Qlib docs could not be fetched directly, so parameter meanings come from search summaries.
- No primary source was found on drift thresholds (such as PSI cut-offs) for trading models, or comparing retraining cadences for hourly BTC models.
- Google's MLOps guide itself was not retrieved; only secondary summaries were.
- The Binance bulk historical data dumps (data.binance.vision / the binance-public-data repo) were not verified in this session.

## 2. Labeling and targets; probability calibration and conformal intervals

### Takeaway
Use event-based labels that mirror how a trade is actually managed. The triple-barrier method labels each event by whichever comes first: take-profit, stop-loss or a time limit, with the price barriers scaled by volatility. Then let a *meta-labeling* model answer "should I act on this rule-based signal, and how big?" instead of predicting direction from scratch.

Turn model scores into probabilities with out-of-time calibration:
- sigmoid (Platt) calibration while calibration data is small;
- isotonic calibration only once there are more than about 1,000 out-of-sample points.

Wrap return forecasts in Adaptive Conformal Inference (ACI) intervals, which keep long-run coverage even when the distribution shifts.

### Cited Findings
- **Triple barrier.** It labels each event by the first of three exits: a profit-taking barrier, a stop-loss barrier and a maximum holding time (López de Prado, *Advances in Financial Machine Learning*, 2018). Hudson & Thames describe the position as held until one barrier is touched, with "meta labeling and bet sizing" deciding position size. — [Quantt guide](https://www.quantt.co.uk/resources/triple-barrier-method); [Hudson & Thames](https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy/)
- **Meta-labeling.** A secondary model decides whether to act on the primary model's call and how large to bet. The *side* of the bet comes from the primary model. — [Trading Interview lesson](https://www.tradinginterview.com/courses/machine-learning/lessons/labeling-the-triple-barrier-method-and-meta-labeling/); [Jesse docs: meta-labeling](https://docs.jesse.trade/docs/research/ml/meta-labeling)
- **Vendor evidence (not independent).** Hudson & Thames report that combining event-based sampling, triple-barrier labels and meta-labeling "improves the performance of the strategies". — [Hudson & Thames research update, Mar 2019](https://hudsonthames.org/?p=3448)
- **Libraries.** mlfinlab is reportedly distributed through a private repository that requires a paid research membership (secondary source). Open-source implementations exist in fynance and mlfinance. — [findailist summary](https://findailist.com/tools/mlfinlab-hudson-thames); [fynance labels](https://fynance.readthedocs.io/en/latest/features.labels.html); [mlfinance ch.3 labeling](https://sipemu.github.io/mlfinance/examples/ch03_labeling/)
- **Wrong labeling** is one of López de Prado's named failure reasons for ML funds. — [Quantpedia](https://quantpedia.com/why-machine-learning-funds-fail/)
- **scikit-learn on calibration.**
  - Isotonic calibration "is more prone to overfitting, especially on small datasets". It matches or beats sigmoid only with roughly more than 1,000 samples.
  - Sigmoid (Platt) works best for small samples or under-confident models.
  - `CalibratedClassifierCV` uses cross-validation so the calibrator is fitted on data the model did not train on.
  - Sources: [sklearn 1.0 calibration guide](https://scikit-learn.org/1.0/modules/calibration.html); [0.22](https://scikit-learn.org/0.22/modules/calibration.html); [0.16](https://scikit-learn.org/0.16/modules/calibration.html)
- **Adaptive Conformal Inference (Gibbs & Candès, NeurIPS 2021).**
  - It is a wrapper around any point or quantile forecaster.
  - It updates the target miscoverage level online, based on whether the last interval missed.
  - It "provably achieves the desired long-term coverage frequency irrespective of the true data generating process".
  - The authors name finance as a motivating case, where markets shift after legislation or major events.
  - Sources: [NeurIPS abstract](https://proceedings.neurips.cc/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html); [arXiv 2106.00170](https://arxiv.org/abs/2106.00170v3)
- **MAPIE library.**
  - Its tabular methods assume exchangeability. Its time-series method swaps that for assumptions about residuals, so coverage is only approximate.
  - EnbPI uses block-bootstrap ensembles and gives approximately valid intervals under strong mixing.
  - The ACI strategy has a `gamma` step size (0 turns adaptation off).
  - The class name differs by version (`TimeSeriesRegressor` vs `MapieTimeSeriesRegressor`).
  - Sources: [MAPIE paper](https://arxiv.org/pdf/2207.12274); [MAPIE docs (latest)](https://mapie.readthedocs.io/en/latest/generated/mapie.regression.MapieTimeSeriesRegressor.html); [MAPIE v1.0.1](https://mapie.readthedocs.io/en/v1.0.1/generated/mapie.regression.TimeSeriesRegressor.html); [Zaffran et al., ACI for time series](https://arxiv.org/pdf/2202.07282); [EnbPI summary](https://sotaverified.org/papers/conformal-prediction-interval-for-dynamic)

### Inferences
- **A label design that fits this repo.** The primary model is the frozen rule-based trend spec (docs/TREND_SPEC.md, per CLAUDE.md), which proposes long/short events. Label each event with a triple barrier:
  - price barriers at ±k·σ_h·√H, with σ_h an EWMA of hourly volatility, k around 1-2 and H = 24-72 bars;
  - a time barrier at H bars.
  
  A small meta-model (logistic regression or gradient boosting) then predicts P(take-profit before stop | features). Its output, a calibrated probability plus expected R, decides act / skip / size. The spec itself is never re-optimized; that keeps the trial count low (Q3).
- **Grade the meta-model on calibration as much as accuracy.** Its probability drives sizing, so a well-calibrated 0.55 is more useful than an over-confident 0.70.
  - Report Brier score and log-loss, each compared with the base-rate forecaster.
  - Plot the reliability curve on out-of-time folds only.
- **Calibration must respect time order.** Fit the calibrator on a fold that comes *after* the model's training data. A shuffled K-fold leaks future information. At roughly a few hundred events per year, use sigmoid; move to isotonic only after more than ~1,000 out-of-sample events.
- **Distribution forecasts.**
  - Fit quantile models (for example the 10%, 50% and 90% quantiles of the forward 24h return).
  - Wrap them with ACI and track realized coverage: an 80% interval should contain about 80% of outcomes over a trailing window of 100-200 observations.
  - A larger γ adapts faster but makes interval width jumpier.
- **The label horizon H sets the purge length** in cross-validation (Q3).

### Gaps
- No independent, BTC-perp-specific evidence was found that meta-labeling improves out-of-sample results; the only support is the Hudson & Thames vendor post.
- No sourced recommendation was found for barrier multipliers (k) or the time barrier (H).
- The book's EWMA-volatility barrier recipe was not re-verified.
- Conformalized quantile regression (CQR) was not researched.

## 3. Validation discipline (walk-forward, purging/embargo, nested selection, multiple testing, paper-trading length, sample sizes, overfitting with an LLM coding assistant)

### Takeaway
Treat every backtest as one draw from a search. Concretely:
- purge training labels that overlap the test period, and add an embargo after each test fold;
- tune hyperparameters inside each walk-forward step (nested selection);
- keep a final holdout that you look at exactly once;
- count every variant that you *or the LLM assistant* tried, so the result can be deflated (Deflated Sharpe Ratio, Probability of Backtest Overfitting, Minimum Backtest Length).

Paper trading for 3-12 months validates the plumbing, not the edge. Statistically, an annual Sharpe ratio of 1 needs about 6 years of data before it sits 2 standard errors from zero **(calc)**.

### Cited Findings
- **Purging and embargo.** Purged cross-validation removes training observations whose label windows overlap the test set, and can add a time buffer (embargo) around it. AFML ch.7 covers purging and embargo; ch.12 covers combinatorial purged cross-validation (CPCV). — [Wikipedia: Purged cross-validation (via search summary)](https://en.wikipedia.org/wiki/Purged_cross-validation); [AFML table of contents](https://toc.uni.li/FLMF049641.pdf); [purgedcv on PyPI (cites ch.7 and ch.12)](https://pypi.org/project/purgedcv/)
- **CPCV.** It produces C(N,K) train/test splits that combine into several out-of-sample backtest paths. In skfolio, `embargo_size` is a number of observations dropped from training right after each test set (default 0). — [skfolio CombinatorialPurgedCV](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html)
- **Embargo size.** The temporalcv library uses `embargo_pct=0.01` (1% of the sample). A practitioner heuristic says the embargo should match the longest autocorrelation in your features. The exact AFML wording ("0.01T") was **not** confirmed. — [temporalcv docs](https://temporalcv.readthedocs.io/en/latest/api/cv_financial.html); [dev.to practitioner post](https://dev.to/shaktitiwari/walk-forward-testing-for-trading-models-the-honest-method-lopez-de-prado-165j)
- **Minimum Backtest Length (MinBTL).** From Bailey, Borwein, López de Prado and Zhu's "Pseudo-Mathematics and Financial Charlatanism" (2014): with 5 years of daily data, try no more than about 45 independent strategy configurations. Beyond that, finding an in-sample annual Sharpe ratio of about 1.0 by chance becomes almost certain. The formula is MinBTL ≈ (E[max_N] / target SR)². — [CXO summary](https://www.cxoadvisory.com/big-ideas/insidiousness-of-overfitting-investment-strategies-via-iterative-backtests); [phys.org summary](https://phys.org/news/2014-04-pseudo-mathematics-financial-charlatanism.pdf); [paper PDF](https://carmamaths.org/jon/backtest.pdf); [R reproduction](https://timelyportfolio.github.io/research_lopezdePrado)
- **Probability of Backtest Overfitting (PBO).**
  - It is estimated by combinatorially symmetric cross-validation (CSCV) over the return matrix of all N trials.
  - A backtest that does not report N cannot be assessed for overfitting, and published backtests "almost never declare the number of trials".
  - Rules of thumb from secondary sources, not standards: PBO above 0.5 means overfitting is more likely than not; a DSR below 0.95 is a warning sign.
  - Sources: [SSRN 2326253](https://papers.ssrn.com/abstract=2326253); [paper PDF](https://carmamaths.org/jon/backtest2.pdf); [LuxAlgo explainer (secondary)](https://www.luxalgo.com/library/concept/probability-of-backtest-overfitting/)
- **Harvey, Liu & Zhu (2016).** A new factor should clear a t-ratio above 3.0, and "most claimed research findings in financial economics are likely false". Harvey and Liu also propose "haircutting" a reported Sharpe ratio for the number of tests run. — [NBER w20592](https://nber.org/papers/w20592); [RFS record](https://ideas.repec.org/a/oup/rfinst/v29y2016i1p5-68..html); [Harvey & Liu, "Backtesting" (CME-hosted)](https://www.cmegroup.com/content/dam/cmegroup/education/files/backtesting.pdf)
- **Lo (2002), "The Statistics of Sharpe Ratios".** Annualizing a monthly Sharpe by √12 is correct "only under very special circumstances". Ignoring serial correlation can overstate an annual Sharpe by more than 65%, and correcting for it can reorder fund rankings. — [CFA Institute](https://rpc.cfainstitute.org/research/financial-analysts-journal/2002/the-statistics-of-sharpe-ratios); [paper PDF](https://traders.studentorg.berkeley.edu/papers/The-Statistics-of-Sharpe-Ratios.pdf)
- **Data needed to compare strategies.** Detecting an annual Sharpe difference of 0.5 between two strategies with 80% power needs about 400 months of data. — [arXiv 2505.06383](https://arxiv.org/pdf/2505.06383v1)
- **Paulsen & Sohl (CXO summary).** Expected out-of-sample Sharpe rises with in-sample length and falls as the number of optimized parameters grows. — [CXO](https://www.cxoadvisory.com/?p=28232)
- **Robert Carver (secondary summaries).** Cut backtested Sharpe ratios by a quarter to a third. A Sharpe of 1.0 is about the realistic ceiling; ratios consistently above 1.0 are rarely achieved. — [7circles summary of *Systematic Trading*](https://the7circles.uk/?p=24214); [CXO notes](https://www.cxoadvisory.com/big-ideas/a-few-notes-on-systematic-trading)
- **Kevin Davey's "incubation" before going live.** Sources disagree on length: 3-6 months, 6-9 months, or 6-12 months. The sequence is walk-forward, then Monte Carlo resampling of trades, then incubation (tracking signals live without trading to compare fills, slippage and equity with the backtest). One blog claims he wants about 100 or more independent trades first; that figure is unverified. All of these are secondary summaries. — [IBKR podcast summary](https://www.interactivebrokers.com/campus/ibkr-quant-news/algo-advantage-036-kevin-davey-part-i-its-all-about-process-in-algo-trading/); [Algo Advantage](https://algoadvantage.substack.com/p/037-kevin-davey-ii-selecting-optimal); [forex.in.rs](https://www.forex.in.rs/simple-systems-diversified); [FinancialWisdomTV](https://www.financialwisdomtv.com/post/building-winning-algorithmic-trading-systems-kevin-davey-s-complete-framework-for-trading-success)
- **Ernest Chan on paper trading.** Test with paper trading or walk-forward testing "for a certain period of time before risking real money". His book has a section titled "Testing Your System by Paper Trading". — [Benzinga summary](https://www.benzinga.com/markets/13/05/3582742/backtesting-pitfalls); [book table of contents](https://content.e-bookshelf.de/media/reading/L-29028952-6fdb26c702.pdf)
- **LLM memorization poisons LLM backtests.**
  - LLMs recall exact financial values from before their knowledge cutoff.
  - Telling them to respect historical boundaries does not stop this, and masking fails because they reconstruct entities and dates from little context.
  - Their counterfactual forecasting ability is therefore "non-identified" (cannot be measured) for any period they have seen; tests after the cutoff are the cleaner check.
  - A separate test finds memorization "substantially amplifies" the apparent predictive power of LLM forecasts.
  - Sources: [Lopez-Lira, Tang & Zhu, "The Memorization Problem"](https://arxiv.org/html/2504.14765v2); [Gao, Jiang & Yan, look-ahead test (slides)](https://abfer.org/media/abfer-events-2026/annual-conference/slides-tech-ai/260518-AI-A-Test-of-Lookahead-Bias-in-LLM-Forecasts.pdf)

### Inferences
- **Concrete settings for hourly bars (calc).**
  - 5 years ≈ 43,800 hourly bars.
  - **Purge** equals the label horizon (24-72 bars).
  - **Embargo** is the larger of 1% of the sample (≈ 440 bars ≈ 18 days) and the longest feature lookback (for example 168 bars for a weekly feature).
  - **Outer walk-forward:** for example, train on 2 years, test on 1 month, step forward 1 month.
  - **Inner (nested) loop:** a purged CV inside each training window chooses hyperparameters and calibration. The outer test month is never used for any choice.
  - **Final holdout:** the most recent 6-12 months stay untouched until the spec is frozen, are evaluated once, and the result is logged in backtest/TRIALS.md.
- **Standard error of the Sharpe ratio (calc).** Using Lo's IID approximation SE(SR̂) ≈ √((1 + SR²/2)/T), with T in years (formula from Lo 2002; full text not re-read here):

  | True annual Sharpe | SE after 3 months | SE after 1 year | SE after 3 years | Years until 2 SE from zero |
  |---|---|---|---|---|
  | 1.0 | ≈ 2.45 | ≈ 1.22 | ≈ 0.71 | ≈ 6.0 |
  | 2.0 | | | | ≈ 3.0 |

  So a 3-12 month paper or forward test says almost nothing about edge. Its job is operational:
  - signals reproduce exactly when the backtest code replays the same live data (Chan's same-code rule and truncation test);
  - realized fees and funding match the model;
  - fills and slippage are acceptable;
  - the Telegram report works as intended.
- **Win-rate sampling error (calc).** The standard error of a ~50% win rate is about ±9.1 percentage points at N = 30 trades, ±5.0 at N = 100, and ±2.5 at N = 400. Telling a 55% system from a coin flip at about 2 SE needs roughly 400 trades.
- **Suggested forward-test gate** (combining Davey's range with the statistics above). Run at least 3 months *and* at least 30-50 signals. Write the pass criteria down before starting:
  - live signals match the replayed backtest signals bit for bit;
  - realized costs stay within a stated tolerance of modeled costs;
  - the meta-model's probabilities stay inside their error bands;
  - there are no unresolved operational incidents.
  
  Only then go live, at minimum size.
- **Protocol for iterating with an LLM coding assistant.**
  1. Write the hypothesis and spec *before* running anything.
  2. The backtest script itself appends every run (parameters, metrics, timestamp) to TRIALS.md, so N is counted automatically for DSR/PBO.
  3. The assistant never sees holdout results.
  4. Budget the number of variants with MinBTL (roughly 45 independent configurations per 5 years). Hourly data does not add independent information in proportion to bar count, because of serial correlation (Lo).
  5. Prefer fewer free parameters (Paulsen & Sohl).
  6. Never accept an LLM's "prediction" of a past period as validation (memorization).
  7. Cut any backtest Sharpe by 25-33% (Carver) before it informs sizing.
- **The repo already does the hard part.** Its "frozen spec versions + TRIALS.md" convention (CLAUDE.md) is exactly the trial bookkeeping that PBO and DSR require.

### Gaps
- AFML's exact embargo recommendation ("0.01T") was not verified.
- The DSR formula was not retrieved; only its role and rule-of-thumb thresholds were.
- No source gives a minimum trade count specific to crypto strategies.
- Davey's incubation length differs across secondary sources.

## 4. Risk management and position sizing for leveraged BTC perps (sizing, margin mode, liquidation math, funding, stops, drawdown rules, Binance mechanics)

### Takeaway
Size from the stop, not from leverage: **position notional = (equity × risk %) / stop distance %**. Leverage is just the consequence of that choice.

On Binance BTCUSDT, the 100 USDT minimum order notional makes ~35 USDT of capital structurally incompatible with professional risk norms (1-2% or less of equity per trade, with volatility-based stops). The minimum position with a 1.5% stop already risks about 4.3% of equity **(calc)**.

Beyond that:
- use isolated margin;
- keep the liquidation price many daily standard deviations beyond the stop;
- count fees and funding in expected value;
- commit to loss limits before trading.

### Cited Findings
**Binance mechanics**
- **Minimum notional.**
  - The BTCUSDT perpetual minimum rose from 5 to 100 USDT on 2023-11-02.
  - Orders below the minimum are rejected with API error -4164, "Order's notional must be no smaller than 100 (unless you choose reduce only)". Reduce-only orders are exempt.
  - Binance may change the threshold without prior notice, so check it through the API.
  - Sources: [Binance announcement 2023-11-02](https://www.binance.com/en/support/announcement/updates-on-minimum-notional-value-for-btcusdt-and-ethusdt-perpetual-contracts-2023-11-02-e4384cba297a4bd2a154be644d5d76f9); [Binance developer forum: -4164](https://dev.binance.vision/t/code-4164-msg-orders-notional-must-be-no-smaller-than-100-unless-you-choose-reduce-only/17535); [USDⓈ-M contract specifications](https://www.binance.com/en/support/articles/360033161972); [Minimum notional rule](https://www.binance.com/en/support/announcement/76719bbaeeb847bbac4daa2906fcdcc0)
- **Maintenance margin.** Maintenance margin = notional value × maintenance margin rate (MMR) − maintenance amount, and the MMR rises with position size. The smallest BTCUSDT tier has a 0.40% MMR. The tier boundary was ≤ 50,000 USDT in the Dec-2023 table and ≤ 300,000 USDT in the Aug-2025 table (that table also has an inconsistent 101-150x row). — [Leverage & Margin FAQ](https://www.binance.com/th/support/faq/360033162192); [Dec-2023 update](https://www.binance.com/el/support/announcement/detail/d75c5ca94f704e96a6a4e55ffddfd65d); [Aug-2025 update](https://www.binance.com/en/support/announcement/detail/8e428625ebeb4cc7ae8678026846095c)
- **Liquidation.**
  - It triggers on the **mark price**, not the last trade price.
  - It happens when maintenance margin exceeds margin balance (wallet balance + unrealized PnL).
  - In **isolated** mode the formula uses only the position's own margin (the other-position terms TMM and UPNL are set to 0). In **cross** mode, the wallet balance and other positions' maintenance and PnL enter the formula.
  - A community implementation matches the formula. A simplified approximation, LP ≈ Entry × (1 − 1/Leverage + MMR) for longs, ignores fees and maintenance amounts. The liquidation clearance fee shifts the real trigger slightly earlier.
  - Sources: [Binance liquidation-price FAQ](https://www.binance.com/au/support/faq/b3c689c1f50a44cabb3a84e663b81d93); [Liquidation protocols FAQ](https://www.binance.com/en-AE/support/faq/360033525271); [community gist](https://gist.github.com/highfestiva/b71e76f51eed84d56c1be8ebbcc286b5); [simplified formula (blog)](https://smalldrift.pages.dev/blog/binance-futures-calculator-pnl-margin-liquidation)
- **Mark price.** Mark price = median(Price 1, Price 2, last contract price).
  - Price 1 is the index price adjusted by the funding rate, scaled by time left to funding.
  - Price 2 is the index price plus a moving average of the basis.
  - The basis window moved to 30 seconds (from 1 minute) on 2025-09-18. A May-2025 notice cited a 2.5-minute window, so the sources conflict.
  - Sources: [Mark price FAQ](https://www.binance.com/th/amp/support/faq/360033525071/); [Sep-2025 announcement](https://www.binance.com/en-AE/support/announcement/detail/c00588a7e8504b3eb28d02a2da00530b); [May-2025 announcement](https://www.binance.com/en/support/announcement/20c5bfbd9e084b6982c768516c316514)
- **Funding.** Funding rate = average premium index + clamp(interest rate − premium, ±0.05%).
  - The default interest rate is 0.01% per 8-hour interval (0.03% per day).
  - The premium index is sampled every 5 seconds.
  - For contracts on an N-hour funding interval, the rate is divided by 8/N (from Sep 2025).
  - Sources: [Binance Sep-2025 announcement](https://www.binance.com/en-AE/support/announcement/detail/c00588a7e8504b3eb28d02a2da00530b); [bit.com explainer](https://www.bit.com/knowledge-hub/funding-rate)
- **Fees.** Regular users pay 0.02% maker and 0.05% taker on USDⓈ-M futures. Paying fees in BNB cuts them by about 10%. — [Binance fee FAQ](https://www.binance.com/support/faq/360033544231); [Finder](https://www.finder.com/cryptocurrency/trading/binance-futures-fees)
- **Tail risk: Oct 10-11, 2025.**
  - More than $19B of leveraged positions were liquidated across more than 1.6M accounts, about 9× the previous one-day record.
  - Auto-deleveraging (ADL) closed *profitable* positions on several venues.
  - Binance valued some collateral (USDe, wBETH, bnSOL) off its own spot books during depegs, and paid out about $283M in compensation.
  - Causes are still disputed.
  - Sources: [Galaxy Research](https://www.galaxy.com/insights/research/cryptos-flash-crash-liquidation-binance-adl-auto-deleveraging); [insights4vc](https://insights4vc.substack.com/p/inside-the-19b-flash-crash); [CoinGecko](https://www.coingecko.com/learn/october-10-crypto-crash-explained); [Cointelegraph](https://cointelegraph.com/news/19b-crypto-market-crash-leverage-china-tariffs)
- **BTC volatility.** Realized volatility in 2025 was about 42% (Schwab). 30-day realized vol ranged 23-45% annualized over 2025-26 (a tracker). On a daily basis it was about 2.24% (K33/Bitwise). — [Schwab](https://international.schwab.com/story/bitcoin-volatility-shrinks-to-magnificent-7-levels); [Spark volatility tracker](https://www.spark.money/tools/bitcoin-volatility-tracker); [KuCoin news](https://www.kucoin.com/news/flash/bitcoin-volatility-drops-to-2-24-in-2025-lower-than-nvidia)

**Sizing doctrine**
- **Robert Carver (secondary summaries).**
  - Set the volatility target roughly equal to the expected Sharpe ratio.
  - Use half-Kelly rather than full Kelly, and quarter-Kelly for negatively skewed strategies.
  - "Risking more than 2% per bet looks like a mug's game."
  - Sources: [7circles summary of *Systematic Trading*](https://the7circles.uk/?p=24214); [CXO notes](https://www.cxoadvisory.com/big-ideas/a-few-notes-on-systematic-trading)
- **Kelly sizing (secondary sources).**
  - Half-Kelly earns about 75% of full Kelly's growth rate; betting 2× Kelly gives zero long-run growth.
  - Under idealized assumptions, full Kelly has about a 1-in-2 chance of eventually halving the bankroll.
  - Fractional Kelly is used mainly because the edge estimate is uncertain.
  - Sources: [theorempath](https://theorempath.com/topics/kelly-criterion); [LuxAlgo](https://www.luxalgo.com/library/concept/kelly-criterion.md)
- **Volatility (ATR) stops.**
  - The Chandelier exit (LeBeau / Elder) puts the stop 3 ATR below the 22-bar high for longs, and it only moves in the trade's favor.
  - Position size = dollar risk / (ATR × multiplier).
  - One blog suggests 3-5× ATR for crypto because it trades 24/7; that figure is unverified.
  - Sources: [LuxAlgo: Chandelier stop](https://www.luxalgo.com/library/concept/chandelier-stop.md); [ATR-based stops](https://protraderdashboard.pages.dev/blog/atr-based-stops); [LuxAlgo: ATR stop strategies](https://www.luxalgo.com/blog/5-atr-stop-loss-strategies-for-risk-control/)
- **ESMA (2018).** National regulators found that 74-89% of retail CFD accounts lose money, with average losses of €1,600-€29,000 per client. Leverage magnifies the impact of fees. — [ESMA press release](https://www.esma.europa.eu/node/84933)

### Inferences
- **Liquidation distance by leverage (calc).** Isolated long, MMR 0.4%, maintenance amount 0 (tier-1 assumption), fees ignored. "Daily σ" uses the 2025 volatility of ≈ 2.2% per day (≈ 0.45% per hour).

  | Leverage | Price drop to liquidation | Distance in volatility terms |
  |---|---|---|
  | 2x | −49.8% | |
  | 3x | −33.1% | |
  | 5x | −19.7% | |
  | 10x | −9.6% | ≈ 4.4 daily σ |
  | 20x | −4.6% | ≈ 2.1 daily σ |
  | 50x | −1.6% | ≈ 3.6 *hourly* σ |
  | 125x | −0.4% | |

  Fat tails (Oct 2025) make σ-based comfort misleading.
- **Minimum equity for the 100 USDT minimum order (calc).** Minimum equity = min notional × stop % / risk %.
  - Stop 1.5%, risk 1% → 150 USDT.
  - Stop 2%, risk 1% → 200 USDT.
  - Stop 3%, risk 1% → 300 USDT.
  
  With 35 USDT, the minimum 100 USDT position risks 2.9% of equity with a 1% stop, 4.3% with a 1.5% stop, and 5.7% with a 2% stop. That breaches Carver's 2% ceiling for any stop wider than 0.7%, and a 0.7% stop is about 1.6 hourly σ, i.e. inside normal noise.
- **Volatility targeting is infeasible at this size (calc).** The minimum position forces an account volatility of at least (100/35) × 2.2% ≈ 6.3% per day, which is above 100% annualized. Any sane volatility target is unreachable until capital is at least ~150-300 USDT.
- **Costs (calc).**
  - A taker round trip on 100 USDT costs 0.10 USDT, which is 0.29% of 35 USDT, or about 0.067R when the stop is 1.5%.
  - Baseline funding is about 0.03 USDT per day per 100 USDT notional, and it can be much larger in a crowded market.
  - Each trade therefore needs more than about 0.07R of edge just to break even on fees.
- **Kelly reality check (calc).** If the meta-model says p = 0.55 on a 1:1 payoff, full Kelly risks 10% and half-Kelly 5%. But p has about ±5 percentage points of sampling error at N = 100 (Q3), so the true Kelly fraction could be 0. Cap risk at 1% or less regardless of what Kelly says.
- **Losing streaks (calc).** With a 45% win rate, the chance of at least one run of 10 straight losses is about 20% in 200 trades and about 43% in 500 trades. Ten straight losses cost 9.6% of equity at 1% risk per trade, 18.3% at 2%, and 33.5% at 4%.
- **Rule set to hard-code into the calculator.**
  - Isolated margin per position.
  - Size from the stop.
  - Liquidation price at least 3× the stop distance away.
  - Account-level effective leverage (notional / equity) of about 3x or less.
  - Stop at k × ATR beyond market structure, with k chosen in the backtest.
  - Exchange-side reduce-only stop orders, which the minimum-notional rule does not block.
  - Daily loss cap of about 2-3R, and a weekly cap.
  - A max-drawdown circuit breaker (for example −15 to −20% from peak) that sends you back to paper trading plus a post-mortem.

  These thresholds are design choices, not sourced standards (see Gaps).
- **Practical path for 35 USDT.** Either paper-trade until capital is at least ~150-300 USDT, or treat the 35 USDT phase explicitly as "tuition money": a stated maximum loss, minimum size, and logging every trade.

### Gaps
- binance.com was blocked, so the following were not retrieved:
  - the live BTCUSDT leverage-bracket table and maintenance amounts;
  - BTCUSDT's funding-rate cap/floor;
  - the liquidation clearance-fee rate;
  - whether STOP orders trigger on mark or last price by default.
- No primary source was found for numeric max-drawdown or daily-loss rules.
- Kelly halving probabilities come only from secondary sources.
- The legal status of Korean residents using Binance (FIU registration) was not researched.

## 5. The right role for the LLM (explanation vs. decision), guardrails, evaluation, cost control, and regulation (incl. Korean 유사투자자문업)

### Takeaway
The evidence says to keep the LLM out of the decision loop:
- live LLM-trader experiments on crypto perps mostly lost money;
- LLM "backtests" are contaminated by memorization;
- chain-of-thought explanations can be unfaithful;
- LLMs answering numeric finance questions were wrong or refused most of the time in a 2023 benchmark.

So use the LLM as a *narrator* of a deterministic, schema-validated JSON whose numbers were computed by code. Verify every number it writes, give it no order-placing tools, and label the output as AI-generated information, not advice.

For a strictly personal bot, Korean investment-advisory registration rules do not apply. Public distribution changes that, and crypto-specific rules are pending in the National Assembly.

### Cited Findings
- **Alpha Arena Season 1 (Nof1), secondary outlets.** Six LLMs each started with $10k and traded crypto perpetuals on Hyperliquid with no human intervention, using 10-20x leverage, for about 17 days (Oct 17/18 to Nov 3/4, 2025).

  | Model | Result |
  |---|---|
  | Qwen 3 Max | +22% |
  | DeepSeek v3.1 | ≈ +4.9% |
  | Gemini 2.5 Pro | ≈ −57% |
  | GPT-5 | ended ≈ $3,733 (−62%) |
  | Overall | 4 of 6 models lost money |

  Sources: [GNcrypto](https://www.gncrypto.news/news/qwen-wins-alpha-arena-season-1-with-22-percent-returns/); [Decrypt](https://decrypt.co/345006/ai-crypto-trading-showdown-deepseek-grok-winning-gemini-implodes); [Aurpay](https://aurpay.net/?p=23782); [ForkLog](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/amp)
- **Memorization / look-ahead bias** makes LLM backtests over pre-cutoff periods invalid; see Q3. — [Lopez-Lira, Tang & Zhu](https://arxiv.org/html/2504.14765v2)
- **FinanceBench (2023).** GPT-4-Turbo with a retrieval system answered wrongly or refused 81% of a 150-question sample. Given the relevant documents in long context, it failed 21%. These are older models. — [arXiv 2311.11944](https://arxiv.org/abs/2311.11944v1); [Patronus AI announcement](https://patronus.ai/announcements/patronus-ai-launches-financebench-the-industrys-first-benchmark-for-llm-performance-on-financial-questions)
- **Turpin et al. (NeurIPS 2023).** Chain-of-thought explanations "can be plausible yet misleading". Models leave out the biasing features that actually drove their answer, and accuracy dropped by up to 36% on 13 BIG-Bench Hard tasks. — [arXiv 2305.04388](https://arxiv.org/abs/2305.04388v2)
- **Anthropic's guidance on reducing hallucinations.**
  - Explicitly allow "I don't know".
  - For long documents (over 20k tokens), extract word-for-word quotes first.
  - Verify each claim with a citation and retract anything unsupported.
  - These techniques reduce hallucinations but "don't eliminate them"; validate critical information.
  - Source: [Claude docs: Reduce hallucinations](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)
- **Claude structured outputs** (bundled reference, cached 2026-10-06).
  - `output_config.format` (JSON schema) and `strict: true` on tools guarantee schema-valid output on current models.
  - **Not supported in the schema:** numeric constraints (`minimum`, `maximum`, `multipleOf`), string-length limits and recursive schemas. The Python and TypeScript SDKs strip these and validate them client-side.
  - Citations cannot be combined with `output_config.format` (the API returns HTTP 400).
  - Sources: [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs.md); [Citations](https://platform.claude.com/docs/en/build-with-claude/citations.md)
- **Claude prompt caching** (bundled reference).
  - The cache is a prefix match. TTL is 5 minutes by default, or 1 hour as an option, and a cache read refreshes the timer.
  - Cache writes cost 1.25× the input price (5-minute TTL) or 2× (1-hour TTL). Reads cost about 0.1× (0.05× on Opus 5.5).
  - The minimum cacheable prefix is 512 tokens on the newest models (marked "check the docs"), and 1,024-4,096 on older ones.
  - When requests sharing a prefix start more than an hour apart, "neither [TTL] helps directly".
  - Source: [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md)
- **Message Batches API** (bundled reference). 50% off all tokens. Most batches finish within 1 hour; the maximum is 24 hours. Meant for work no one is waiting on. — [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing.md)
- **Prices per million tokens (cached 2026-10-06).**

  | Model | Input | Output |
  |---|---|---|
  | Opus 5.5 | $4 | $20 |
  | Sonnet 5.5 | $2 | $10 |
  | Haiku 5.5 (prompts up to 100K tokens) | $0.10 | $0.50 |

  Thinking is billed regardless of whether it is displayed. On Opus 5.5, thinking cannot be disabled, and the default effort is `medium`. — [Pricing](https://platform.claude.com/docs/en/about-claude/pricing.md); [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview.md)

**Korean regulation (한국 규제)**
- 2024 자본시장법 개정(시행 2024.8.14):
  - 카카오톡 오픈채팅 리딩방 같은 **양방향 채널**에서의 유료 회원 영업은 정식 등록 **투자자문업자만** 할 수 있다.
  - 미등록 운영은 3년 이하 징역 또는 1억원 이하 벌금 대상이다.
  - **손실보전·이익보장 약정은 금지**된다.
  - 유사투자자문업은 "불특정 다수가 접할 수 있는 매체"를 통한 조언을 대상으로 한다.
  - 출처: [블록미디어](https://www.blockmedia.co.kr/archives/453144); [법무법인 대륜](https://www.daeryunlaw.com/case/quasi-investment-advisory-business); [금융위원회](https://www.fsc.go.kr/po010101/82887?curPage=86); [신김 뉴스레터](https://www.shinkim.com/kor/media/newsletter/pdf/3098). 시행일은 이 검색 요약들에서 나온 것이므로 원문으로 확인 필요.
- 가상자산:
  - 2021년 금융위 관계자는 "암호화폐는 자본시장법상 기초자산이 아니어서 … 금융위 차원에서 조치할 법적 근거 자체가 없다"고 했다. 코인 리딩은 영업신고 대상도 아니었다. — [다음/2021 보도](https://v.daum.net/v/20210422173008839?f=p)
  - 한 법률 분석은 2024년 자본시장법 개정이 "주식 등에만 적용될 뿐"이라고 본다. 정확한 출처 페이지는 다음 중 하나로 확정하지 못함: [로톡](https://www.lawtalk.co.kr/posts/160384), [sugar.legal](https://blog.sugar.legal/youtube-stock-coin-regulation).
  - 가상자산이용자보호법(2023.6.30 국회 통과)은 시세조종·부정거래를 금지하고 형사처벌 근거를 둔다. 코인 투자자문업 규율은 별도 과제로 남았다. — [법률신문](https://www.lawtimes.co.kr/news/189002)
- 계류 중인 법안:
  - 2025.4.15 민병덕 의원 등 10인 「가상자산이용자보호법」 개정안: '가상자산 유사자문업' 금융위 신고제, 손실보전·이익보장·허위수익률 금지, 위반 시 직권말소와 1억원 이하 과태료. 처리 결과는 미확인. — [국민참여입법센터](https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/2209842/detailRP); [비즈워치](https://news.bizwatch.co.kr/article/mobile/2025/04/16/0008)
  - 「디지털자산기본법안」(2025.6.10 발의): 디지털자산유사자문업을 10개 업종 중 하나로 법정화. 2026년 10월 현재 미제정이며 정부안을 기다리는 중으로 보도됨. — [신김](https://www.shinkim.com/kor/media/newsletter/pdf/2859); [헤럴드경제](https://biz.heraldcorp.com/article/10927680); [파이낸셜뉴스 2026-10-14](https://www.fnnews.com/news/202610140620473261)
- 집행 현황:
  - 2025년 유사투자자문업자 검사에서 35개사에 과태료 총 4억7천만원(전년 대비 약 3.3배). 당국은 "신고만으로 영업 가능해 이용자 보호가 어렵다"고 지적했다. — [정책브리핑](https://www.korea.kr/news/policyNewsView.do?newsId=148963188) (또는 [이 브리핑](https://m.korea.kr/news/policyNewsView.do?newsId=148935062); 정확한 기사 귀속 불확실)
  - 2022년~2026년 7월 유사투자자문 관련 신고 3,357건. — [메트로서울 2026-09-10](https://www.metroseoul.co.kr/article/20260910500229)
- AI 기본법(인공지능 발전과 신뢰 기반 조성 등에 관한 기본법), 2026.1.22 시행:
  - 생성형 AI 제품·서비스를 제공할 때 이용자에게 사전 고지해야 한다(제31조 제1항).
  - 생성물에는 표시를 해야 한다(제31조 제2항).
  - 정부는 사실조사와 과태료에 1년 이상의 유예기간을 두겠다고 발표했다.
  - 출처: [법률신문](https://www.lawtimes.co.kr/news/217123); [신김](https://shinkim.com/kor/media/newsletter/3114); [SK AX](https://www.skax.co.kr/insight/trend/3666)

### Inferences
- **Separate roles: code decides, the LLM explains.**
  - **Code produces:** view (long / short / none), meta-model probability, conformal interval, invalidation level, and the risk-calculator outputs.
  - **The LLM receives:** only that JSON plus a description of the chart.
  - **The LLM returns:** a schema with headline, view (an enum it must copy), rationale bullets, risks, invalidation text and disclaimer.
  - **Numeric grounding:** prefer placeholders such as `{p_tp}` that code fills in. Otherwise, regex-extract every number in the LLM's text and require each one to match a JSON value within tolerance. On any mismatch, send the template-only report.
  - **Why code must check the bounds:** structured outputs cannot enforce `minimum`/`maximum`, so code has to check things like 0 ≤ p ≤ 1 itself.
- **"Why" text only from real attributions.** The explanation should only restate attributions the model actually computed (for example the top SHAP features, computed in code). This prevents unfaithful post-hoc reasons of the kind Turpin et al. describe.
- **Prohibitions to encode in prompts and tests.** The LLM must not change the view, invent price levels or targets, recommend leverage beyond the calculator's output, or claim certainty. Treat any web or news text it ingests as untrusted input (prompt injection: the same instinct as in security work). Give it **no tools that can place orders**. This matches the repo rule that LIVE mode is rejected by the config validator; the human places orders manually.
- **Evaluating the narration.**
  - **Automated, every report:** 100% numeric consistency, view consistency, invalidation text present, disclaimer present.
  - **Weekly human rubric** on 10-20 sampled reports: clarity, correctness, no over-claiming.
  - **Optional second-model reviewer** (GLM) as an LLM judge, treated as a noisy signal.
- **Cost (calc).** 720 hourly runs per month, each with about 3k input and 0.8k output tokens, plus thinking tokens on top:

  | Model | Approx. cost per month |
  |---|---|
  | Opus 5.5 | ≈ $20 |
  | Sonnet 5.5 | ≈ $10 |
  | Haiku 5.5 | ≈ $0.50 |

  - An hourly cadence means a 60-minute start-to-start gap, so caching *across* runs is unreliable.
  - Caching does pay *within* a run, for example a draft call and a self-check call sharing a system prompt of 512+ tokens within 5 minutes.
  - Batches don't suit the live hourly report (latency up to 24h), but they fit backfills and regression evaluation of past reports at 50% off.
  - This setup fits the repo rule of API key only, with no automation of the consumer app.
- **Regulatory reading (not legal advice).**
  - **Personal only:** a bot that sends to the user's own chat ID only is not aimed at "불특정 다수", so 유사투자자문업 should not apply.
  - **Public, crypto only:** no 자본시장법 registration currently appears to apply, per the 2021 FSC remark and legal commentary. Pending bills (가상자산 유사자문업 신고제, 디지털자산기본법) could change this. Fraud and unfair-trading law applies either way. AI 기본법 notice and labeling would likely apply to a service offered to users.
  - **If stocks were ever covered:** a one-way public channel needs 유사투자자문업 신고; a two-way channel needs 투자자문업 등록.
  - **In every case:** keep a clear disclaimer (투자 권유 아님 / 개인 학습·참고용 / 손실 책임 본인), and never promise returns. 손실보전·이익보장 is the bright line in every regime.

### Gaps
- Final Alpha Arena numbers for Claude Sonnet 4.5 and Grok 4, and any later seasons, were not retrieved.
- Official Anthropic pages were not fetched live; the skill cache is dated 2026-10-06 and its minimum-cache value for the newest models is flagged "check the docs".
- GLM API pricing and structured-output support were not researched.
- The status of the Korean bills as of Nov 2026 is unconfirmed. The effective date of 가상자산이용자보호법 (widely reported as 2024.7.19) was not verified with a URL.
- A lawyer's opinion is needed before any public distribution.

## 6. Human factors (alert fatigue, overtrading, presenting uncertainty and invalidation, journals and post-trade review)

### Takeaway
For a beginner with a leveraged account, the biggest risk is behavioral, not model error:
- frequent trading and day trading destroy returns for the large majority;
- attention-grabbing push messages measurably raise the leverage people take;
- alarms that are mostly noise get ignored.

So design the Telegram report to be quiet by default, and make it explicit about uncertainty: frequencies, intervals, and "no trade" as a valid output. Every view should come with an invalidation level. Pair the report with a trade journal and scheduled reviews that grade *process* rather than profit and loss.

### Cited Findings
- **Barber & Odean (2000).** 66,465 households at a discount broker, 1991-96. The households that traded most earned 11.4% a year against 17.9% for the market; the average household netted about 16.4%. Average turnover was about 75% a year, and the authors attribute heavy trading to overconfidence. — [RePEc (Journal of Finance)](https://econpapers.repec.org/RePEc:bla:jfinan:v:55:y:2000:i:2:p:773-806); [paper PDF](https://faculty.haas.berkeley.edu/odean/Papers%20current%20versions/Individual_Investor_Performance_Final.pdf)
- **Barber, Lee, Liu & Odean (2014), Taiwan day traders 1992-2006.** Less than 1% of the day-trader population can "predictably and reliably earn positive abnormal returns net of fees". — [RePEc (Journal of Financial Markets)](https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html); [working paper](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/Day%20Trading%20Skill%20110523.pdf)
- **Chague, De-Losso & Giovannetti, Brazilian mini-index futures day traders.** Among those who persisted 300+ sessions, about 97% did not earn positive net returns. Only 1.1% earned more than the minimum wage and 0.5% more than a bank teller's starting salary. There was no evidence of learning (data 2012-2017; 19,646 traders who started). — [CXO Advisory](https://www.cxoadvisory.com/investing-expertise/day-trading-a-bust/); [Bloomberg](https://www.bloomberg.com/news/articles/2020-08-15/day-traders-in-brazil-study-would-ve-done-better-with-9-to-5-job); [SSRN 3423101](https://ssrn.com/abstract=3423101)
- **Arnold, Pelster & Subrahmanyam (JFE 2022).** A broker sent standardized push messages to retail clients. Trades triggered by those messages carried on average **19 percentage points higher leverage**, and the effect was stronger for younger, male and less experienced investors. A later working paper finds that attention also lowers trading performance. — [RePEc (JFE)](https://econpapers.repec.org/RePEc:eee:jfinec:v:143:y:2022:i:2:p:846-875); ["Paying Attention" working paper](https://voxeu.org/system/files/2023-02/Paying%20Attention.pdf)
- **Alarm fatigue (clinical evidence).** 72-99% of clinical alarms are false, and clinicians become desensitized, which leads to missed or delayed responses (Sendelbach & Funk 2013, via a National Academies report). — [NCBI Bookshelf](https://www.ncbi.nlm.nih.gov/books/NBK555522/)
- **Spiegelhalter on communicating uncertainty.**
  - Expected frequencies ("of 100 people like you, about 10 …") help the public understand risk.
  - "10 out of 100" is perceived as larger than "1 out of 10".
  - The UK Met Office ran an online game to find the best way to show forecast uncertainty.
  - In one Australian study, 79% of the public interpreted precipitation probabilities correctly, versus 55% of forecasters.
  - His 2011 *Science* review covers visual formats.
  - Sources: [Spiegelhalter & Gage](https://scholarworks.umt.edu/tme/vol12/iss1/4); [Spiegelhalter et al., *Science* 2011 (PDF)](https://www.stat.berkeley.edu/users/aldous/157/Papers/spiegelhalter_visualizing.pdf); [*Annals of Family Medicine* 2008](https://www.annfammed.org/lookup/volpage/6/196); [Stephens et al. 2019](https://gc.copernicus.org/articles/2/101/2019/)
- **Trade journals (Brett Steenbarger, secondary reports).**
  - A journal is the trader's "business plan".
  - Review it daily, ideally with a mentor.
  - Turn each mistake into the next day's goal, and record strengths as well as weaknesses.
  - Use metrics to track improvement.
  - Sources: [Journalytix](https://journalytix.me/2019/04/23/dr-brett-steenbarger-taking-your-performance-to-the-next-level/); [BabyPips](https://www.babypips.com/trading/psychology-3-ways-make-the-most-trading-journal-2024-12-11); [Scribd excerpt](https://www.scribd.com/document/560690781/Trading-Journal-That-Works); [metalsmine thread](https://www.metalsmine.com/thread/30301-making-trading-journals-work-for-you)
- **Review routines from journaling vendors.**
  - Weekly review order: overall performance, then trade management, then missed trades, then *one* process improvement for the coming week. — [Edgewonk](https://edgewonk.com/blog/how-to-review-your-trading-journal)
  - A three-tier cadence: right after each trade, a weekly deep review, and a monthly audit. — [NexusFi](https://nexusfi.com/a/psychology/trading-journal-how-to-build)
  - Judge process separately from outcome, because outcomes are high-variance. — [TradeZella](https://www.tradezella.com/blog/trading-journal-complete-guide)

### Inferences
- **Alert policy.**
  - Send the hourly report silently (Telegram Bot API `disable_notification`; not verified in this session).
  - Make it audible only for:
    - a new setup that passes the probability threshold *and* is feasible under the risk rules;
    - an invalidation or stop being hit on an open position;
    - a risk-limit breach;
    - a data or system fault.
  - Aim for no more than about 1-3 audible alerts a day.
  - Track "alerts acted on / alerts sent", just as a SOC tracks alert precision.
- **Anti-overtrading features built into the tool.**
  - A maximum number of trades per day and per week.
  - A cooldown after a stop-out (for example 4-12h).
  - A daily loss cap that turns the report into a "오늘은 거래 중지" banner.
  - Minimum probability and expected-value thresholds.
  - Order parameters are shown only after a short pre-trade checklist: setup ID, stop, and size taken from the calculator.

  These numbers are design choices (see Gaps).
- **Uncertainty template for each report (Korean UI).**
  - 관점: 롱 / 숏 / **관망** (관망 is the default when p is near the base rate or the inputs are out of distribution)
  - 확률: "과거 유사 신호 312회 중 181회(58%) 목표가 먼저 도달 — 95% 범위 52~63%" (frequency format plus sample size)
  - 24h 80% 구간: −2.1% ~ +2.4% (ACI)
  - 무효화: "1h 종가가 X 아래면 이 관점은 폐기" (X set by k·ATR)
  - 리스크 계산기: 진입 / 손절 / 수량 / 레버리지 / 청산가 / 수수료 / 펀딩 / 손실액(R), with a warning when 35 USDT cannot meet the 1% rule (Q4)
  - 모델 상태: 버전, 마지막 재학습, 최근 30일 Brier 대비 기준선, 데이터 이상 여부
  - 면책 문구
- **Journal fields.** signal_id, model_version, p, interval, planned entry/stop/target/size, actual fills, fees, funding, exit reason, rule adherence (Y/N), emotion tag, chart snapshot.
- **Review cadence.**
  - Weekly: grade process.
  - Monthly: calibration review using reliability buckets (did the 60% calls hit about 60%?).
  - Quarterly: strategy review against TRIALS.md.
  - After a max-drawdown breach: mandatory return to paper trading and a written post-mortem.

### Gaps
- No trading-specific controlled study of alert frequency was found; the alarm-fatigue evidence is clinical.
- The Steenbarger material is secondhand.
- No source was found on Korean retail loss rates in crypto futures (the FSS may publish this).
- No sourced numeric thresholds were found for cooldowns or trade caps.
