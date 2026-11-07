# ML/DL on Candlestick (OHLCV) Data for Crypto/BTC: Honest Validation Results and Common Pitfalls

_Compiled 2026-11-07. Scope: ML/DL predicting crypto (mainly BTC) direction, returns, volatility, or patterns from OHLCV candles; rigorous out-of-sample evidence; pitfalls. Project lens: BTCUSDT perp analysis tool trained on Binance candles 2020–2026 (1m–1d) that should output calibrated probabilities and ranges._

_Status tags: **[PR]** = peer-reviewed journal/conference · **[PP]** = preprint / working paper (not peer-reviewed) · **[BLOG] / [REPO] / [KAGGLE] / [DOCS]** = practitioner material, not reviewed._

_Method note: arxiv.org and wp.lancs.ac.uk could not be fetched in this session (network allowlist). Numbers for arXiv papers therefore come from abstracts and search-engine excerpts or mirrors (HF Papers, IDEAS/RePEc, ResearchGate, alphaXiv). Check them against the PDFs before quoting them as final._

---

## 1. Gradient boosting / tabular ML (LightGBM, XGBoost, RF) on engineered OHLCV features for BTC

### Takeaway
In rigorous studies, direction skill from candle features is only slightly better than a coin flip: daily accuracy is about 53–54%, and AUC at a few hours ahead is about 0.51. Short-horizon "profits" disappear once realistic costs are included. The only reported way to survive costs is to trade only high-confidence or large-forecast bars, and the gating threshold then becomes a new overfitting risk. GBDT (LightGBM) is the practical workhorse: it won the only large live-scored crypto competition, but the gains came from features rather than from the learner.
**KR 한 줄 요약:** 캔들 피처와 트리 모델로 방향을 맞히는 실력은 동전 던지기보다 조금 나은 수준입니다(일봉 정확도 53~54%, 몇 시간 앞 AUC 약 0.51). 수수료를 넣으면 짧은 주기 매매의 수익은 대부분 사라집니다.

### Cited Findings
- **[PR, J. Finance & Data Science, 2021]** Jaquart, Dann & Weinhardt, "Short-term bitcoin market prediction via machine learning". Horizons: 1–60 minutes.
  - All models beat a random classifier. Recurrent networks and gradient-boosting classifiers are "especially well-suited". Predictability increases as the horizon gets longer.
  - Technical features matter most, followed by selected blockchain and sentiment/interest features.
  - A quantile-based long-short strategy earns up to **39% per month before costs** but **negative returns after costs**, "due to the particularly short holding periods".
  - Sources: [EconBiz record](https://www.econbiz.de/Record/short-term-bitcoin-market-prediction-via-machine-learning-jaquart-patrick/10013162705); [DOAJ/UTM mirror](https://libmast.utm.my/Record/doaj.art-05a289397eb14f0db2dae92db4d5c4f6)
- **[PR, JFDS, 2022, DOI 10.1016/j.jfds.2022.12.001]** Jaquart, Köpke & Weinhardt, "Machine learning for cryptocurrency market prediction and trading". Task: daily binary direction for the **100 largest coins**.
  - Average accuracy is **52.9%–54.1%** across models. On the **top-10% most confident predictions** per class and day, accuracy is **57.5%–59.5%**.
  - Long-short portfolios built on LSTM and GRU ensembles reach annualized out-of-sample **Sharpe ratios of 3.23 and 3.12 after transaction costs**, against **1.33 for buy-and-hold**. The authors cannot fully rule out limits to arbitrage.
  - The cost level and sample period are not verified (only the abstract was seen).
  - Source: [DOAJ](https://doaj.org/article/cfc09801314441198e3e1c92a3914e54)
- **[PP, arXiv 2606.00060, June 2026]** "Machine Learning-Based Bitcoin Trading Under Transaction Costs: Evidence From Walk-Forward Forecasting". Models: XGBoost, LSTM and iTransformer on about **70,000 hourly BTC-USDT observations**, with a **27-fold walk-forward**.
  - All three models are positive before costs in "selected configurations".
  - Naive sign-based strategies **fail once 10 bp costs** are applied.
  - A cost-aware filter trades only when the forecast magnitude exceeds a cost-based threshold. It cuts turnover and restores profitability "in selected configurations".
  - Best reported result: long-only XGBoost, **above 65% annualized with Sharpe above 1**.
  - Source: [arXiv abstract](https://arxiv.org/abs/2606.00060)
  - **Critique:** a commentary argues that if the threshold was tuned on data overlapping the test period, the net returns "incorporate an extra degree of freedom that is not guaranteed to be out-of-sample". — [Pith commentary](https://pith.science/paper/2606.00060)
- **[PP, arXiv 2607.23370, July 2026]** A regime-aware model fusing social sentiment with technical features for BTC direction. Its best model reaches **AUC 0.5084 on the 3-hour-ahead task**, which the authors call a realistic baseline that reflects how hard hourly BTC direction is. The model uses more than candles, which makes this low ceiling more telling. — [arXiv HTML](https://arxiv.org/html/2607.23370v1)
- **[KAGGLE, Nov 2021–May 2022; wrap-up 2022]** G-Research Crypto Forecasting.
  - Task: forecast short-term returns of **14 coins**, scored by **weighted Pearson correlation**. Final ranks came from running each team's two selected models for about **3 months on live market data**.
  - **All top-3 teams used LightGBM.** The organizers say developing and testing features had a "far greater impact" on scores than model development.
  - Source: [G-Research wrap-up](https://www.gresearch.com/news/wrapping-up-the-g-research-crypto-forecasting-competition/)
  - **2nd-place write-up:** a single LightGBM GBDT regressor with squared loss and no ensembling beyond boosting; features not disclosed. — [Kaggle discussion](https://www.kaggle.com/c/g-research-crypto-forecasting/discussion/323098)
- **[PR, AIMLSystems 2024; arXiv 2502.09079]** Puoti, Pittorino & Roveri, "Quantifying Cryptocurrency Unpredictability". Assets: BTC, ETH, LTC, BNB (USD).
  - Univariate crypto series closely resemble **Brownian noise**.
  - **Naive models "consistently outperform"** the ML and deep-learning models, from ARIMA up to XGBoost-type models and N-BEATS, across horizons and windows.
  - Prior studies often skipped naive comparisons or fed in past and future covariates, "potentially inflating their perceived effectiveness".
  - Source: [arXiv](https://arxiv.org/abs/2502.09079v1)
- **[PP, SSRN 6727738, May 2026]** Jung, "A Filtered-Label Calibrated XGBoost Framework with Walk-Forward Validation for Robust Bitcoin Direction Prediction".
  - Method: calibrated XGBoost on 120+ daily features, calendar-refit walk-forward, and training labels filtered to days with large forward moves.
  - Robustness checks: Bonferroni/Holm corrections, Deflated Sharpe Ratio and PBO.
  - The headline returns are very strong but unverified; treat as a single-author preprint. It is a useful template for validation.
  - Source: [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6727738)
- **[BLOG, undated]** Walk-forward XGBoost for 3-hour BTC direction on hourly BTC/USDC, with probability calibration, hit rates by return threshold, and probability-gated trading rules. Its numbers were not extracted. — [PyQuantLab (Medium)](https://pyquantlab.medium.com/xgboost-for-short-term-bitcoin-prediction-walk-forward-analysis-and-thresholded-performance-b83dc2e677eb)

### Inferences
- **Benchmark for honest skill on candles:** direction accuracy of about 51–55%, or AUC of about 0.50–0.56, at intraday-to-daily horizons. Any claim of 60% or more at intraday horizons from OHLCV alone should trigger a leakage audit (see Q4).
- **Where calibrated probabilities pay off:** the confidence-gating effect in Jaquart 2022 (about 54% overall, 57.5–59.5% on the top decile) is how they can matter: a few high-confidence calls. The gate itself must be fixed inside each training fold. Otherwise it becomes exactly the "extra degree of freedom" raised in the 2606.00060 critique.
- **Cross-sectional Sharpe does not transfer:** the 100-coin long-short Sharpe of about 3.2 does not carry over to a single-instrument BTCUSDT timing tool. A single instrument has no cross-sectional hedge and far fewer independent bets.
- **Perp costs:** the cost model should include fees, slippage and funding payments. The 10 bp cost in 2606.00060 is a reasonable minimum stress level. None of these sources covers funding.
- **Baselines to report alongside LightGBM:** (i) a zero or random-walk forecast, (ii) always-long or the historical up-rate, and (iii) logistic regression on the same features.

### Gaps
- The full texts were not accessible, so two items are missing: the per-horizon accuracy table of Jaquart 2021, and the exact costs and sample period of Jaquart 2022.
- No peer-reviewed, LightGBM-specific BTC walk-forward study with costs was found. The closest is the XGBoost preprint 2606.00060.
- The G-Research winning weighted-correlation scores and the 1st-place (Meme Lord Capital) write-up were not found.
- No funding-rate-aware perp backtests of ML signals were found.

---

## 2. Deep learning (LSTM/GRU, TCN, Transformers) and CNNs on candlestick chart images

### Takeaway
Deep learning on crypto candles has no robust, independently confirmed edge over GBDT or naive baselines. When it "wins", it is usually against other complex models rather than naive ones, on price-level error metrics, or in a cross-sectional (many-coin) setting. The image-CNN evidence (Jiang–Kelly–Xiu) is strong, but it comes from a huge U.S. equity cross-section, before costs. Crypto chart-image studies are small, mostly preprints, and some report implausibly high numbers.
**KR 한 줄 요약:** LSTM, 트랜스포머, 차트 이미지 CNN 같은 딥러닝이 비트코인 캔들에서 단순 기준선을 확실히 이긴다는 독립 검증 결과는 아직 없습니다.

### Cited Findings
- **[PR, JFDS 2021]** For 1–60 minute BTC tasks, RNNs and GBDT classifiers are the best suited, but after costs a short-horizon long-short strategy is negative. — [EconBiz](https://www.econbiz.de/Record/short-term-bitcoin-market-prediction-via-machine-learning-jaquart-patrick/10013162705)
- **[PR, JFDS 2022]** LSTM and GRU ensembles gave the best long-short Sharpe (3.23 and 3.12 after costs) in a daily cross-section of 100 coins. — [DOAJ](https://doaj.org/article/cfc09801314441198e3e1c92a3914e54)
- **[PP, arXiv 2606.00060, 2026]** LSTM and iTransformer fare no better than XGBoost: naive sign trading fails for all three at 10 bp, and the reported best configuration is long-only XGBoost. — [arXiv](https://arxiv.org/abs/2606.00060)
- **[PP, arXiv 2606.27670, 26 Jun 2026]** Peng, Khushi & Poon, "CryptoGAT: Are Time Series Models Effective for Cryptocurrency Forecasting?".
  - They argue that temporal models are a poor fit for pure-price crypto forecasting and recast the task as a cross-asset graph problem (graph attention).
  - They claim CryptoGAT beats complex time-series models "in all cases". The numbers were not retrieved.
  - Source: [HF Papers](https://huggingface.co/papers/2606.27670)
- **[PR, MDPI MAKE, 2026]** A leakage-free protocol for next-day direction on SET50, S&P 500 and CSI 300 (equities, not crypto; includes PatchTST-style models): "no deep network shows a significant advantage over naive or logistic baselines after Holm adjustment". — [MDPI](https://mdpi.com/2504-4990/8/11/366)
- **[PR, MDPI Systems, 2025]** Temporal Fusion Transformer for multi-crypto trading with on-chain and technical indicators.
  - TFT has the lowest RMSE on ETH and USDT and is among the best on BTC and BNB.
  - It was benchmarked only against LSTM, GRU, SVR and XGBoost, not against naive persistence.
  - Source: [MDPI Systems 13(6):474](https://www.mdpi.com/2079-8954/13/6/474)
- **[secondary summary of ICLR 2023 paper]** PatchTST's headline gain (about a 21.0% MSE reduction versus earlier Transformer models) was shown on general benchmarks such as Weather, Traffic and Electricity, not on financial returns. — [EmergentMind summary](https://www.emergentmind.com/papers/2211.14730)
- **[PR, J. Finance 2023; SSRN WP Dec 2020]** Jiang, Kelly & Xiu, "(Re-)Imag(in)ing Price Trends".
  - Method: OHLC and volume charts are rendered as small images (e.g., 64×60 px). A CNN estimates the probability of a positive return over the next 5, 20 or 60 days.
  - Data: training 1993–2000, testing 2001–2019, on U.S. stocks.
  - Results: stocks are sorted into deciles and traded as a High-minus-Low portfolio. The authors find the image signals "largely distinct" from standard trend signals (momentum, reversal) and more profitable.
  - Sources: [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3756587); [Rubesam summary](https://www.linkedin.com/pulse/re-imagin-price-trends-jiang-kelly-xiu-2023-alexandre-rubesam-bpfbe); [author slides](https://aifin-hkust.github.io/2021/slides/Xiu_papers.pdf)
- **[REPO, undated]** A replication of Jiang–Kelly–Xiu on the authors' U.S. OHLC images plus self-built Chinese A-share images (64×60). It covers equities only. — [GitHub Reed2006](https://github.com/Reed2006/-Re-imaging-the-price-trend)
- **[PP, arXiv 2408.08483, 2024]** A follow-up notes that the CNN's longer-horizon predictions are hard to obtain from price images, and proposes image-induced importance weights. — [arXiv](https://arxiv.org/html/2408.08483v1)
- **[PP, arXiv 2605.00875, Apr–May 2026]** Haggett, "Visual Chart Representations for Cryptocurrency Regime Prediction".
  - Data: BTC, ETH and S&P 500, 2018–2024. Raw candlestick charts are compared with Gramian Angular Fields across four architectures.
  - Best result: a **simple 4-layer CNN on raw, price-only 128×128 charts, AUC-ROC 0.892**. The label is a binary bull/bear regime: whether the k-day price change exceeds a threshold τ.
  - ImageNet transfer learning adds 4–16%.
  - Source: [arXiv HTML](https://arxiv.org/html/2605.00875v1)
  - An excerpt from the same paper's Table III shows "Raw Candlestick | 49.3% | 0.367 | 0.760" with the metric columns unlabeled. This is hard to reconcile with the 0.892 headline. — [ResearchGate](https://www.researchgate.net/publication/404427920_Visual_Chart_Representations_for_Cryptocurrency_Regime_Prediction_A_Systematic_Deep_Learning_Study)
- **[PR, ACM 2024; arXiv 2501.12239]** "Investigating Market Strength Prediction with CNNs on Candlestick Chart Images" (stocks, crypto, forex). Adding candlestick-pattern labels did not beat raw images. Accuracy **peaked at about 0.7**, below more complex time-series models. — [ACM DL](https://dl.acm.org/doi/10.1145/3690771.3690776)
- **[PR, MDPI Applied Sciences 14(9):3797, 2024]** Wide-TSNet, which uses Markov-transition-field images, reports **about 94% accuracy and 90% F1** on BTC price-movement classification. Treat it as an example of a very high claim that needs an audit. — [MDPI](https://mdpi.com/2076-3417/14/9/3797)

### Inferences
- **Why the image-CNN result may not transfer:** the Jiang–Kelly–Xiu setting has thousands of stocks per week and evaluates a cross-sectional ranking (decile long-short) before costs. One BTCUSDT series from 2020–2026 gives orders of magnitude fewer independent labels, so a chart CNN on BTC is far more exposed to overfitting. There is also no cross-section to rank.
- **Haggett's AUC 0.892 is an outlier:** it conflicts with every other forward-direction number in these notes. Two explanations to check are (a) the k-day label window overlapping the chart window, and (b) random rather than chronological splits. Do not adopt it without replicating under purged walk-forward.
- **Suggested priority for the project:**
  1. LightGBM or logistic regression on engineered features as the baseline.
  2. A small 1D-CNN or GRU only if it beats that baseline and the naive baselines on identical folds.
  3. Image CNNs last.

### Gaps
- The Jiang–Kelly–Xiu accuracy and Sharpe tables were not retrieved. A search-engine summary mentioned equal-weight long-short Sharpe ratios of about 7.2, 6.8 and 4.9 for the 5-, 20- and 60-day models (before costs), but I could not tie these to a specific page. Verify them in the published paper: [JF 2023 PDF hosted at Yale](https://economics.yale.edu/sites/default/files/2023-11/The%20Journal%20of%20Finance%20-%202023%20-%20JIANG%20-%20Re%25E2%2580%2590%20Imag%20in%20ing%20Price%20Trends_0.pdf).
- No peer-reviewed crypto replication of Jiang–Kelly–Xiu was found.
- Not found:
  - CryptoGAT's benchmark numbers.
  - BTC head-to-heads of Informer or PatchTST against naive persistence.
  - TCN-specific BTC results.
- Surfaced but not reviewed: "Understanding the Convolutional Neural Network's Stock Return Predictability" by Guan, Li & Si ([SSRN 6389479](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6389479)).

---

## 3. Financial time-series foundation models (Kronos, Chronos/Chronos-Bolt, TimesFM, Moirai, Lag-Llama, TimeGPT)

### Takeaway
Kronos, a finance-specific model that turns K-lines into tokens, reports large gains over other foundation models. Those gains come from the authors' own benchmarks, mainly RankIC with ensembling over sampled paths and A-share simulations. One independent critique says the ensembling protocol favors Kronos. One small independent BTC 5-minute test found Kronos-small did not beat a Brownian-motion baseline.

General foundation models (Chronos, TimesFM, Moirai, TimeGPT) used zero-shot on returns rarely beat a random walk: the difference was statistically significant in only 2 cases in one five-stock study. They also trail tuned CatBoost/LightGBM. On realized volatility they are about level with Log-HAR, and only one small model beats it, by about 1–2%. Fine-tuning or finance-specific pretraining narrows the gaps. Pretraining-data overlap (contamination) is a real concern for 2020–2026 BTC backtests.
**KR 한 줄 요약:** 파운데이션 모델은 수익률·방향 예측에서는 랜덤워크(단순 기준선)를 거의 이기지 못하고, 변동성 예측에서는 전통 모델(HAR)과 비슷한 수준입니다. Kronos의 큰 성과는 저자 자체 벤치마크이며, 독립 검증은 아직 약합니다.

### Cited Findings
**Kronos**
- **[PR, AAAI 2026; arXiv 2508.02739, 2 Aug 2025; also listed at NeurIPS 2025]** Shi, Fu et al. (Tsinghua).
  - **Architecture:** a tokenizer quantizes each OHLCVA bar into hierarchical coarse and fine sub-tokens. A decoder-only autoregressive Transformer is then pretrained on **more than 12 billion K-line records from 45 global exchanges**.
  - **Zero-shot claims:**
    - price-series forecasting **RankIC +93%** over the leading foundation model and **+87%** over the best non-pretrained baseline;
    - volatility forecasting **9% lower MAE**;
    - synthetic K-line fidelity **+22%**;
    - in A-share investment simulations, the **highest annualized excess return and information ratio**.
  - Sources: [arXiv](https://arxiv.org/abs/2508.02739); [HF Papers](https://huggingface.co/papers/2508.02739); [AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/39730); [NeurIPS 2025 listing](https://neurips.cc/virtual/2025/132504)
- **Model sizes:** code and weights are public under MIT per the HF listing, but parameter counts conflict across secondary sources. One HF-related excerpt gives about 3.96M for a "small" checkpoint; a BTC test write-up describes Kronos-small as 24.7M. — [HF (tokenizer mirror)](https://huggingface.co/AAA123Q/Kronos-Tokenizer-base); [Cornford & Cross](https://cornfordandcross.com/market-insights/week-three-foundation-model-vs-brownian-motion-kronos-on-five-minute-btc/)
- **Critique [non-peer-reviewed review site, 2025–26]:** IC and RankIC rise steadily with the number of sampled rollouts, so part of the advantage is ensembling. The headline RankIC gains come from "an asymmetric ensembling protocol that the paper never matches against baselines". — [Pith review](https://pith.science/paper/2508.02739)
- **[BLOG, 2026] Independent BTC test:** an offline comparison of Kronos-small against geometric Brownian motion on **5-minute BTC (497 historical trades)**. **Kronos did not outperform the Brownian baseline** out-of-sample. The test is small: one checkpoint and one horizon. — [Cornford & Cross](https://cornfordandcross.com/market-insights/week-three-foundation-model-vs-brownian-motion-kronos-on-five-minute-btc/); [mirror (1023 Jack)](https://1023jack.com/market/week-three-foundation-model-vs-brownian-motion-kronos-on-five-minute-btc-2/)
- **[PP, arXiv 2607.26792, Jul 2026]** Yu, Tao, Chen, Wang & Bunn, "Crossing-Free Probabilistic K-Line Forecasts Without Retraining".
  - Probabilistic K-line forecasts suffer two kinds of inconsistency. *Quantile crossing:* a higher quantile comes out below a lower one. *K-line crossing:* the forecast low is above the open or close, or the forecast high is below them.
  - Their training-free KQSP projection removes both while preserving accuracy, and works with any model, including foundation models.
  - Per the PDF excerpt, **Kronos's pretraining corpus ends in June 2024**, and their shared test period runs from **17 Jan 2025 to 23 Jul 2026**.
  - Source: [IDEAS/RePEc](https://ideas.repec.org/p/arx/papers/2607.26792.html)

**General foundation models on financial data**
- **[PP, arXiv 2511.18578, Nov 2025; presented at FoFI 2026]** Rahimikia et al., "Re(Visiting) Time Series Foundation Models in Finance". Task: daily excess returns on a stock cross-section.
  - Off-the-shelf **Chronos and TimesFM zero-shot trail CatBoost/LightGBM**, and zero-shot forecasts do **not produce profitable long-short strategies**.
  - Fine-tuning and finance-specific pretraining narrow the gap.
  - Secondary summaries report these figures (cost treatment not verified):

    | Model | Look-back window | Annualized return | Sharpe |
    |---|---|---|---|
    | CatBoost | 252 days | 46.50% | 6.79 |
    | CatBoost | 512 days | 47.25% | 6.46 |
    | TimesFM (20M) + JKP factors | not stated | not stated | 7.69 |

  - Sources: [arXiv HTML](https://arxiv.org/html/2511.18578v1); [ResearchGate](https://www.researchgate.net/publication/397872068_ReVisiting_Time_Series_Foundation_Models_in_Finance)
- **[PP, arXiv 2606.27100, Jun 2026]** "Pretrained Time-Series Foundation Models for Financial Return Forecasting".
  - TimeGPT, TimesFM-2.5, Moirai-2.0, Chronos and Chronos-2, run zero-shot on **five U.S. stocks** with rolling-origin tests, against models trained from scratch.
  - Moirai-2.0 and TimesFM-2.5 have the best average ranks.
  - But the **Diebold–Mariano test against a random walk is significant (p<0.05) in only two instances**.
  - A locally trained iTransformer wins on META.
  - Source: [arXiv HTML](https://arxiv.org/html/2606.27100)
- **[PP, arXiv 2609.04917, Sep 2026]** Survey, "Artificial Intelligence in Equity and Crypto Markets".
  - General time-series benchmarks are built around forecasting loss, not tradable excess return.
  - A generic foundation model **may have been trained on series that extend into the intended test period**.
  - Strong generic forecasting ranks need not translate into useful financial forecasts.
  - Source: [arXiv PDF](https://arxiv.org/pdf/2609.04917)
- **[PP, arXiv 2607.05291, Jul 2026]** Brini, "Forecasting Realized Volatility with Time Series Foundation Models".
  - Setup: **9 zero-shot foundation models against 8 econometric models (HAR family)**, on **50 assets** (equities, FX, futures; VOLARE dataset) at h = 1, 5 and 22. Crypto is not among the assets.
  - Per-asset QLIKE ratio to Log-HAR (below 1 = better than Log-HAR):

    | Model | h=1 | h=5 | h=22 |
    |---|---|---|---|
    | Tiny Time Mixers | 0.982 | 0.986 | 0.987 |
    | Chronos-Bolt-S | 1.110 | 1.188 | 1.302 |
    | Chronos-Bolt-B | 1.121 | 1.181 | 1.303 |

  - Only Tiny Time Mixers beats Log-HAR at every horizon, by a narrow margin. The other foundation models do not improve on Log-HAR.
  - **Pooled losses are misleading:** they favor the foundation models only because of a few outlier assets.
  - Choice of architecture matters more than "foundation model versus econometric model".
  - Source: [arXiv HTML](https://arxiv.org/html/2607.05291v1)
- **[PP, arXiv 2505.11163, May 2025]** Zero-shot **TimesFM did not consistently beat HAR** on realized volatility of 21 global equity indices; **fine-tuning was needed** to be competitive. — [arXiv HTML](https://arxiv.org/html/2505.11163v1)
- **[PR, ICLR 2026]** Adler et al., "Beyond Accuracy: Are Time Series Foundation Models Well-Calibrated?". Five foundation models and two baselines on six datasets: the foundation models were **generally better calibrated than the baselines**. — [ICLR proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/hash/9af2b1d6acf561af9c4cf70d52c7a49d-Abstract-Conference.html)
- **[PP/conference, arXiv 2609.25788; ADBIS 2026]** Michael, Symeonides & Trihinas find a **trade-off between point accuracy and probabilistic reliability**. xLSTM-based models keep their calibration across horizons, while patch-based transformers stay accurate but **lose calibration at long horizons**. The datasets cover energy, traffic and finance. — [arXiv PDF](https://arxiv.org/pdf/2609.25788); [UCY PDF](https://www.grid.ucy.ac.cy/assets/files/publications/pdfs/adbis26.pdf)
- **[BLOG]** A zero-shot TimesFM tutorial on the **1-minute BTC-USDT high-low range** as a volatility target. It is a tutorial, not a benchmark against a random walk. — [QuestDB](https://questdb.com/blog/zero-shot-forecasting-questdb-timesfm/)
- **[BLOG, secondary]** Moirai (trained on LOTSA) is described as zero-shot "competitive with, and sometimes superior to" full-shot models, on general rather than financial benchmarks. — [Medium summary of Moirai](https://medium.com/@kdk199604/moirai-building-a-universal-forecaster-for-time-series-data-c959b3b35174)

### Inferences
- **Contamination:** for a 2020–2026 BTCUSDT study, any zero-shot foundation-model evaluation on data before the model's pretraining cutoff is potentially contaminated. For Kronos that cutoff is about June 2024, per 2607.26792. Large exchange BTC candles are prime pretraining material, so only windows after the cutoff are clean tests.
- **Where these models could plausibly help** is as volatility or range forecasters, or as feature generators (e.g., quantiles of Kronos sampled paths). Three conditions apply:
  - beat Log-HAR or HAR-X on per-asset, per-regime QLIKE;
  - compare against baselines with the same ensembling, matching Kronos's averaging over sampled paths;
  - enforce OHLC and quantile consistency, e.g., KQSP-style projection, before turning sampled paths into reported ranges.
- **Report metrics per period or regime, not pooled**, so a few volatile windows cannot drive the conclusion (Brini's pooled-vs-per-asset finding).
- **Calibration has to be checked per horizon**, because patch-based models can lose calibration at long horizons (2609.25788).

### Gaps
- No rigorous BTC-specific zero-shot benchmark of Chronos, Chronos-Bolt, TimesFM, Moirai, Lag-Llama or TimeGPT against a random walk was found, peer-reviewed or not.
- Not retrieved for Kronos (arXiv blocked):
  - the exact test periods;
  - the share of crypto in the pretraining corpus;
  - crypto-specific results;
  - the cost assumptions in the investment simulation.
- No finance-specific claims or evaluations were found for Lag-Llama or TimeGPT.
- Surfaced but not reviewed:
  - "EXAONE Forecast for Finance" ([arXiv 2609.04239](https://arxiv.org/pdf/2609.04239));
  - the ACM survey "Time-Series Foundation Models in Finance" ([ACM](https://dl.acm.org/doi/full/10.1145/3785706.3785728));
  - "When Do Foundation Models Pay Off? A Break-Even Analysis" ([arXiv 2607.04919](https://arxiv.org/pdf/2607.04919));
  - "Hybrid Neural-Classical Correction for Frozen TSFMs" on high-frequency stocks ([arXiv 2608.08825](https://arxiv.org/pdf/2608.08825)).

---

## 4. Systematic reviews / meta-analyses: leakage, look-ahead, improper splits, costs, inflated accuracy

### Takeaway
Reviews from 2024–2026 agree that most crypto-prediction papers use evaluations that cannot establish real predictive ability:
- single splits or in-sample model selection;
- no naive baseline;
- price-level RMSE;
- no costs.

At short-to-medium horizons, no peer-reviewed study shows robust superiority over a naive baseline across market regimes. A concrete demonstration on crypto: computing a signal decomposition on the full sample inflates directional accuracy from **52% (causal) to 93%**. No quantitative meta-analysis of what share of papers leak was found.
**KR 한 줄 요약:** "정확도 90% 이상" 같은 결과는 대부분 미래 정보가 섞여 들어간(누수) 탓입니다. 누수를 막으면 52% 수준으로 떨어진 실제 사례가 있습니다.

### Cited Findings
- **[PP, arXiv 2606.00071, mid-2026]** Baquero (INESC TEC / U. Porto), "Bitcoin Price Prediction: Peer-Reviewed Evidence and Social Media Discourse".
  - **Method:** Google Scholar and Web of Science searches covering 2017–2026, plus citation tracing; 23 papers are discussed in detail.
  - **Evaluation tiers:** Tier 1 = walk-forward or rolling out-of-sample; Tier 2 = a single chronological train/test split; Tier 3 = in-sample only or selection by information criterion.
  - **Main finding:** "no peer-reviewed study has shown robust superiority over the naive baseline across multiple market regimes" at short-to-medium horizons.
  - Daily predictability does not carry over to hourly or monthly horizons and may not survive costs.
  - Stock-to-flow failed formal out-of-sample tests, and Metcalfe-law valuations have been challenged as spurious.
  - **Recommendations:**
    - walk-forward evaluation;
    - holdout windows from several market regimes;
    - a naive-baseline comparison;
    - **including zero in hyperparameter grids**;
    - Diebold–Mariano tests.
  - The field "needs better evaluation more than new models".
  - Sources: [IDEAS/RePEc](https://ideas.repec.org/p/arx/papers/2606.00071.html); [arXiv](https://arxiv.org/abs/2606.00071)
  - The same survey, as summarized, says the vast majority of papers use evaluation methods that cannot establish genuine predictive ability, and typically pick the best of several candidate models evaluated on a single window. — [arXiv PDF](https://arxiv.org/pdf/2606.00071)
- **[PP, Research Square rs-11529129, ~Nov 2026, not peer-reviewed]** "The leakage premium in decomposition-based cryptocurrency forecasting". Setup: a VMD-on-CEEMDAN pipeline on daily prices of **five major crypto-assets, 2018–2026**, under three information protocols.
  - With **full-sample (two-sided) decomposition, directional accuracy is 93%**. Computed **causally, it is 52%**, with an **out-of-sample R² of −23%**.
  - Look-ahead accounts for nearly the whole accuracy premium, and the premium grows with each added decomposition layer.
  - Causal decomposition forecasts are *harmful*, not just uninformative.
  - The authors propose a falsification test for look-ahead.
  - Source: [Research Square](https://www.researchsquare.com/article/rs-11529129/v1)
- **[Zenodo, 2026]** A critical narrative review of 18 papers (2018–2026) finds the field too focused on RMSE/MAE rather than economic validity. It recommends walk-forward validation, leakage management, and trading performance net of costs. — [Zenodo](https://zenodo.org/records/20610140)
- **[PR, 2025]** A systematic review of ML forecasting of the Bitcoin price, published in a data-driven-marketing journal, concludes that existing models perform only marginally better than random guessing (abstract-level summary). — [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2772941925000274)
- **[PR, AIMLSystems 2024]** Naive models beat ML and deep-learning models on BTC, ETH, LTC and BNB. Prior work often omitted naive baselines or used **past and future covariates**. — [arXiv](https://arxiv.org/abs/2502.09079v1)
- **[PR, EAI conference, May 2026]** Reported improvements in crypto forecasting are often regime-dependent and "highly sensitive to leakage-prone design choices". — [EUDL](https://eudl.eu/pdf/10.4108/eai.22-5-2026.2365165)
- **[PP, arXiv 2508.01419, 2025]** Backtests can look overly optimistic because of look-ahead bias, data snooping and survivorship bias. — [arXiv](https://arxiv.org/pdf/2508.01419)
- **[PP, arXiv 2403.17081, 2024]** A systematic mapping of ML on blockchain data found 30 cryptocurrency price-prediction papers, most of them on Bitcoin. — [arXiv](https://arxiv.org/pdf/2403.17081)
- **High-accuracy claims to treat as red flags:**
  - Wide-TSNet: about **94% accuracy** on BTC movement ([MDPI](https://mdpi.com/2076-3417/14/9/3797)).
  - Candlestick-image CNN: about **92% accuracy** on Taiwan50 stocks ([arXiv 1903.12258](https://arxiv.org/pdf/1903.12258)).
  - A Vision-Transformer-plus-time-series-transformer hybrid reported at about **96%** on stocks, unverified and from a secondary source ([Medium overview](https://medium.com/@gwrx2005/computer-vision-for-cryptocurrency-trading-chart-analysis-sentiment-and-anomaly-detection-870764fca604)).
- **Benchmark-design pitfalls documented in this file:**
  - a trading threshold possibly tuned on data overlapping the test set ([Pith on 2606.00060](https://pith.science/paper/2606.00060));
  - ensembling applied to the proposed model but not to the baselines ([Pith on Kronos](https://pith.science/paper/2508.02739));
  - pretraining data overlapping the test period ([arXiv 2609.04917](https://arxiv.org/pdf/2609.04917); [IDEAS 2607.26792](https://ideas.repec.org/p/arx/papers/2607.26792.html));
  - pooled losses dominated by outlier assets ([Brini 2607.05291](https://arxiv.org/html/2607.05291v1)).

### Inferences
- **Pitfall checklist for this project** (synthesized from the findings above):
  1. Any transform computed on the full sample must be recomputed strictly causally within each fold. Examples: scalers, z-scores, wavelet/EMD/VMD decompositions, PCA, HMM regime labels, and smoothing filters with centered windows.
  2. Random K-fold on overlapping multi-bar labels leaks information; use purging and an embargo.
  3. Scoring price levels (price RMSE or R²) makes models look good just because prices persist. Score returns, direction or volatility against naive baselines instead.
  4. Feature, model or threshold selection must not touch the test window.
  5. Always include a naive or "zero" baseline.
  6. Do not omit fees, slippage or funding.
  7. Do not test on a single regime, such as only the 2020–21 bull market.
  8. Do not rely on pooled metrics alone.
  9. Check foundation-model pretraining overlap.
  10. Ensemble every compared model equally.
- **Survivorship and data quality:** survivorship bias is mainly a problem for many-coin cross-sections. For a single BTCUSDT perp, the analogous risk is data quality: exchange outages, extreme wicks, and contract-specific events. These were not researched here.

### Gaps
- No PRISMA-style meta-analysis was found that counts how often crypto ML papers leak, use improper splits, or ignore costs. The tier counts in Baquero (2606.00071) were not retrieved.
- Surfaced but not reviewed: "When Alpha Disappears: A One-Switch Benchmark for Decision-Time Leakage in Financial Backtests" ([arXiv 2605.23959](https://arxiv.org/pdf/2605.23959)).

---

## 5. Best-practice validation: purged/embargoed CV, walk-forward, DSR, PBO, calibration, triple-barrier, meta-labeling

### Takeaway
The standard toolkit comes from López de Prado and coauthors:
- purged and embargoed cross-validation, plus walk-forward;
- combinatorial purged cross-validation (CPCV);
- the Deflated Sharpe Ratio (DSR), which accounts for the number of trials and for non-normal returns;
- the Probability of Backtest Overfitting (PBO), computed with CSCV;
- triple-barrier labels and meta-labeling.

On top of this, probability calibration should be checked out-of-sample with the Brier score and reliability curves. The evidence that CPCV beats walk-forward comes from a single synthetic study. Walk-forward remains the realistic way to simulate trading, so use each method for its own role.
**KR 한 줄 요약:** 검증의 기본은 네 가지입니다. ① 시간 순서대로 나누기, ② 겹치는 구간 제거(purge/embargo), ③ 시도 횟수를 기록해 DSR/PBO 계산, ④ 확률이 실제 빈도와 맞는지(보정) 점검.

### Cited Findings
- **[DOCS]** Purged cross-validation removes training observations whose label intervals overlap the test set, optionally with an embargo buffer after the test set. Conventional and walk-forward methods often give overly optimistic estimates because of leakage and overfitting. — [Wikipedia: Purged cross-validation](https://en.wikipedia.org/wiki/Purged_cross-validation)
- **[Book, Wiley 2018]** López de Prado, *Advances in Financial Machine Learning*. Chapter 3 covers labeling, including the triple-barrier method and meta-labeling; the book also covers cross-validation in finance and backtesting. — [Wiley TOC PDF](https://catalogimages.wiley.com/images/db/pdf/9781119482086.toc.pdf)
- **Triple-barrier labeling:** an upper (profit-take) barrier, a lower (stop-loss) barrier and a vertical (time-limit) barrier. The label is whichever barrier is touched first: +1, −1, or 0 when time runs out, in common implementations. — [finmlkit docs](https://finmlkit.readthedocs.io/en/latest/api/finmlkit.label.tbm.html); [Hudson & Thames](https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy/)
- **Meta-labeling:** a second-stage ML model sits on top of a primary signal, which can be a rule-based "white box". It decides whether to act on the primary signal and how large to bet. The aim is to filter out false positives and improve F1. — [Jesse docs](https://docs.jesse.trade/docs/research/ml/meta-labeling); [QuantConnect forum (mlfinlab announcement)](https://www.quantconnect.com/forum/discussion/5853)
- **[PR, J. Portfolio Management 40(5):94–107, 2014]** Bailey & López de Prado, "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality".
  - It corrects for **selection bias under multiple testing** and for **non-normal returns**.
  - Not controlling for the number of trials leads to over-optimistic expectations, because the expected maximum Sharpe rises as more strategies are tried.
  - The adjustment uses the skewness and kurtosis of returns.
  - Sources: [SSRN](https://papers.ssrn.com/abstract=2460551); [CXO Advisory summary](https://cxoadvisory.com/big-ideas/sharper-sharpe-ratio)
- **[PR, J. Computational Finance, 2017]** Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting", estimated with combinatorially symmetric cross-validation (CSCV). — [PDF](https://carmamaths.org/jon/backtest2.pdf)
- **[WP, SSRN 4686376, 2024]** Arian, Norouzi & Seco, "Backtest Overfitting in the Machine Learning Era". In a synthetic controlled environment, CPCV beat K-Fold, Purged K-Fold and especially walk-forward, with lower PBO and higher DSR test statistics.
  - A mirror's summary is more nuanced: walk-forward had a notably lower median DSR, while CPCV was not significantly different from (purged) K-fold.
  - Sources: [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4686376); [Scribd mirror](https://www.scribd.com/document/725401650/SSRN-id4778909)
- **[PP, arXiv 2512.12924, Dec 2025]** Walk-forward is described as the gold standard for trading-strategy validation and the industry standard for realistic trading simulation, while CPCV shows superiority in mitigating overfitting. — [arXiv HTML](https://arxiv.org/html/2512.12924v1)
- **[PP, arXiv 2504.18278, 2025]** The Brier score is the mean squared error between the predicted probability and the 0/1 outcome. It splits into a **refinement (discrimination)** part and a **calibration** part. — [arXiv](https://arxiv.org/pdf/2504.18278)
- **BTC practice examples:**
  - Calibrated XGBoost with calendar-refit walk-forward, Bonferroni/Holm corrections, DSR and PBO ([SSRN 6727738](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6727738)).
  - A request to evaluate BTC direction forecasts out-of-sample with the Brier score, reliability curves and calibration error ([GitHub issue](https://github.com/jpfelgueiras/btc-timesfm/issues/113)).
- **Evaluation recommendations for BTC** (Baquero): walk-forward, holdouts from several regimes, a naive baseline, zero included in hyperparameter grids, and Diebold–Mariano tests. — [IDEAS/RePEc](https://ideas.repec.org/p/arx/papers/2606.00071.html)

### Inferences
- **A concrete protocol for the project** (synthesized):
  1. **Outer loop:** anchored or rolling walk-forward. Purge training rows whose label horizon reaches into the test fold, and add an embargo of at least one label horizon after each test block.
  2. **Model selection inside each training window:** use CPCV or purged K-fold.
  3. **Holdouts:** set aside several regime blocks, for example the 2020 crash, the 2021 bull, the 2022 bear and 2024–26.
  4. **Trial log:** record every configuration tried, including failures, in the existing `backtest/TRIALS.md`. That count is exactly what DSR and PBO need.
  5. **Calibration:** fit the calibrator (e.g., isotonic or Platt) on the most recent slice of each training window only. Report the Brier score with its decomposition and a reliability diagram per fold.
  6. **Ranges:** report interval coverage, e.g., how often the realized value falls inside the 80% band, and pinball (quantile) loss.
- **Labels:** triple-barrier labels with barriers scaled to volatility fit a perp tool, because they encode stop-loss and take-profit paths. Their overlapping time spans make purging mandatory.
- **Meta-labeling:** this is the natural way to add ML on top of the frozen rule set in `docs/TREND_SPEC.md`. The primary rule stays fixed, and a calibrated secondary model only filters or sizes its signals. This keeps the rule-change process (a new frozen version plus a TRIALS.md entry) intact.

### Gaps
- The final publication venue of Arian et al. was not retrieved, and the CPCV-versus-walk-forward evidence is synthetic only.
- No crypto-specific study was found that measures how well calibrated BTC direction models are (Brier score or reliability).

---

## 6. Which targets are realistically learnable from candles: volatility/range vs direction

### Takeaway
Volatility is clearly more forecastable than direction. Realized variance is highly persistent, and HAR-type models built on intraday realized volatility are hard to beat for BTC:
- they beat GARCH;
- ML often fails to beat HAR for BTC specifically;
- ML gains often come from extra features that a linear HAR-X can use just as well.

Zero-shot foundation models are at best about level with Log-HAR. Direction stays near chance. Theory (Christoffersen–Diebold) ties any predictability of the return's sign to volatility dynamics, mostly at intermediate horizons. That supports a design with volatility or range as the primary target, and direction probabilities conditioned on forecast volatility.
**KR 한 줄 요약:** "얼마나 움직일지(변동성·가격 범위)"는 "어느 방향으로 갈지"보다 훨씬 잘 예측됩니다. 비트코인에서도 HAR 같은 단순한 변동성 모델이 머신러닝과 대등하거나 더 낫습니다.

### Cited Findings
- **[PR, Management Science 2006; NBER WP 10009, 2003]** Christoffersen & Diebold, "Financial Asset Returns, Direction-of-Change Forecasting, and Volatility Dynamics".
  - Volatility dependence produces **sign dependence** as long as expected returns are not zero.
  - Sign dependence can exist **even without conditional-mean dependence**.
  - It is unlikely to show up in sign autocorrelations, runs tests or traditional market-timing tests, because it is nonlinear.
  - It is more likely at **intermediate horizons** than at very high or very low frequencies.
  - Source: [NBER](https://www.nber.org/papers/w10009)
- **[WP, PIER 06-016]** Christoffersen, Diebold, Mariano, Tay & Tse, "Direction-of-Change Forecasts Based on Conditional Variance, Skewness and Kurtosis Dynamics". The pervasive volatility dependence in equity returns could, through the sign dependence it induces, be used for market-timing direction forecasts. — [UPenn PDF](https://www.econ.upenn.edu/sites/default/files/filevault/working-papers/06-016.pdf)
- **[PR, Research in International Business and Finance, 2022]** "Forecasting volatility of Bitcoin". **HAR models based on realized variance beat GARCH models based on daily data.** The stated reason is that realized variance "exhibits much higher degree of autocorrelation than squared returns". — [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0275531921001616)
- **[PR, Asia-Pacific Financial Markets, 2024]** "Crypto Volatility Forecasting: Mounting a HAR, Sentiment, and Machine Learning Horserace". Across 8 cryptocurrencies, using 6-hour realized volatility, ML beat HAR for most assets **except Bitcoin**. For Bitcoin, HAR significantly outperformed ML on QLIKE when sentiment was excluded. — [Springer](https://link.springer.com/article/10.1007/s10690-024-09510-6)
- **[PR, N. American J. of Economics & Finance, 2022]** "Out-of-sample prediction of Bitcoin realized volatility: Do other cryptocurrencies help?". Realized volatility of ETH and XRP adds statistically and economically important information, and HAR-SPCA is the best model tested. — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S106294082200081X)
- **[PR, J. of Empirical Finance, 2021]** "Forecasting Bitcoin realized volatility by exploiting measurement error under model uncertainty". Model-averaged HARQ-type models are superior out-of-sample at both short and long horizons. — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0927539821000220)
- **[REPO, non-peer-reviewed, ~2026]** Two GitHub projects on BTC realized volatility:
  - (a) Over **1,003 walk-forward days, LightGBM beat plain HAR by 22%, but a linear HAR-X with the same features matched it (p = 0.90)**. Which repo reports this was not verified.
  - (b) In rolling out-of-sample tests over 2023–2026 with Diebold–Mariano tests, **HAR-X had the lowest QLIKE (0.2586)**, ahead of HAR with a weekend term (0.2943) and plain HAR (0.3466), among models that also included XGBoost and an LSTM. This is the ayoubguenbib repo, per its description.
  - Sources: [samuel-melancon repo](https://github.com/samuel-melancon/btc-volatility-forecasting); [ayoubguenbib repo](https://github.com/ayoubguenbib/btc-volatility-forecasting)
- **Foundation models on realized volatility:**
  - Only Tiny Time Mixers edges Log-HAR, by about 1.3–1.8%; Chronos-Bolt is 11–30% worse ([Brini, arXiv 2607.05291](https://arxiv.org/html/2607.05291v1)).
  - Zero-shot TimesFM is not consistently better than HAR ([arXiv 2505.11163](https://arxiv.org/html/2505.11163v1)).
  - Kronos claims 9% lower volatility MAE than competing models, which is the authors' own benchmark ([HF Papers](https://huggingface.co/papers/2508.02739)).
- **Direction stays near chance in rigorous setups:**
  - AUC 0.5084 at 3 hours for BTC, even with sentiment features ([arXiv 2607.23370](https://arxiv.org/html/2607.23370v1)).
  - 52% causal directional accuracy with out-of-sample R² of −23% ([Research Square](https://www.researchsquare.com/article/rs-11529129/v1)).
  - Daily accuracy of 52.9–54.1% across 100 coins ([DOAJ](https://doaj.org/article/cfc09801314441198e3e1c92a3914e54)).
  - Predictability rises with horizon from 1 to 60 minutes ([EconBiz](https://www.econbiz.de/Record/short-term-bitcoin-market-prediction-via-machine-learning-jaquart-patrick/10013162705)).
- **Range forecasting needs consistency constraints:** quantile forecasts of OHLC can cross each other, and a forecast low can sit above the forecast open or close. KQSP fixes both without retraining. — [IDEAS/RePEc](https://ideas.repec.org/p/arx/papers/2607.26792.html)
- **[BLOG]** The 1-minute high-low range is used directly as a volatility target for BTC-USDT in a TimesFM tutorial. — [QuestDB](https://questdb.com/blog/zero-shot-forecasting-questdb-timesfm/)

### Inferences
- **Primary outputs for the tool:**
  - next-period realized volatility computed from 1m or 5m candles;
  - the high-low range;
  - return quantiles, which give the ranges.
- **Baselines and scoring for those outputs:** benchmark each against HAR and Log-HAR, plus HAR-X with calendar or weekend terms and cross-asset terms such as ETH realized volatility. Score with QLIKE plus interval coverage and pinball loss.
- **Direction is a secondary output,** ideally conditioned on the volatility forecast (the Christoffersen–Diebold mechanism) and evaluated at intermediate horizons, from hours to days rather than 1–5 minutes, where costs also dominate.
- **Linear control:** most of ML's value in volatility forecasting comes through extra features. A linear HAR-X with the same features is the right control for whether nonlinearity (LightGBM or deep learning) actually adds anything.
- **Data is sufficient:** Binance 1m candles for 2020–2026 are enough to build intraday realized-volatility series, so the HAR family can be implemented immediately as the baseline that every LightGBM, deep-learning or foundation-model variant must beat per regime.

### Gaps
- No BTC-specific study was retrieved that reports out-of-sample R² for volatility forecasts next to R² for return forecasts. The conclusion that volatility is more predictable rests on the HAR persistence evidence plus the near-chance direction results.
- No ML-versus-econometric benchmark was found specifically for BTC intraday high-low range forecasting, e.g., against Parkinson/Garman-Klass estimators or range-GARCH.
- Perp-specific predictors (funding, open interest, liquidations) and an MSc thesis, "High-Frequency Forecasting of Bitcoin Volatility" ([Concordia](https://spectrum.library.concordia.ca/995904/1/Sarrafshirazi_MSc_F2025.pdf)), surfaced but were not reviewed.
