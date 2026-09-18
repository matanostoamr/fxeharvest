# Automated Trading & Yield-Harvesting Strategies: What the Evidence Actually Shows

A literature-and-data review, not a recommendation. Every claim below is tied to a source.
Content from sources was rephrased/summarized for compliance with licensing restrictions.

---

## 0. The short version

There is **no published, independently verified evidence of a day-trading bot strategy that reliably makes money for a retail operator.** The research record points the other way.

What *does* have documented positive expected return is a small set of strategies that are structurally different from "day trading":

| Strategy family | Evidence grade | What the edge actually is | Why it's hard |
|---|---|---|---|
| Perp funding-rate / basis carry | **B+** — peer-reviewed + live at $B scale | Risk premium paid to short-side hedgers | Cycle-dependent, venue/custody risk, not arbitrage |
| Slow time-series momentum (trend) | **A-** — ~140 yrs, 67 markets | Behavioural under/over-reaction | Decade-long flat periods, -20%+ drawdowns |
| Latency arbitrage / MEV | **A** — on-chain, fully auditable | Speed & infrastructure | Winner-take-all; 3 firms take ~75% |
| Market making (spread capture) | **A** — 40+ yrs microstructure theory | Compensation for inventory + adverse selection | Adverse selection kills the undercapitalised |
| AMM LP "yield harvesting" | **D** — negative for ~half of participants | Fees, minus LVR | Impermanent loss / LVR usually exceeds fees |
| Grid / DCA / "AI signal" bots | **F** — no independent verification | None demonstrated | Vendor backtests, survivorship, no OOS proof |

Direction of the finding: **the more a strategy's return comes from a structural risk premium or an infrastructure advantage, the better the evidence. The more it comes from predicting short-term price direction, the worse the evidence — approaching zero.**

---

## 1. Base rates: what happens to people who do this

This is the single most important body of evidence, and it is remarkably consistent across countries, decades, and asset classes.

**Brazil — equity futures, the cleanest dataset in the literature.** Chague, De-Losso & Giovannetti tracked *every* individual who started day trading Brazilian equity futures 2013–2015 and persisted at least 300 trading days. Findings: 97% lost money. Only 0.4% earned more than a bank teller's wage (~US$54/day). The single best performer in the entire population made ~US$310/day *with a standard deviation of ~US$2,560* — i.e. even the winner's results are statistically hard to distinguish from luck. Critically, they found **no evidence of learning**: the share of profitable traders *fell* the longer people traded.
Sources: [working paper (USP)](http://www.repec.eae.fea.usp.br/documentos/Chague_Losso_Giovannetti_47WP.pdf) · [paper PDF](https://ebicapital.nl/wp-content/uploads/2022/05/day-trading.pdf) · [Quantpedia summary](https://quantpedia.com/retail-day-trading-is-an-uphill-battle/)

**Taiwan — full-market exchange data, Barber, Lee, Liu & Odean.** In a typical six-month window, more than 8 of 10 day traders lose money. Heavy day traders do generate *gross* profits — but not enough to cover transaction costs. In the follow-up paper *The Cross-Section of Speculator Skill*, the authors conclude that **fewer than 1% of the day-trader population can predictably and reliably earn positive abnormal returns net of fees.**
Sources: [Do Individual Day Traders Make Money?](http://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trade%20040330.pdf) · [Cross-Section of Speculator Skill](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/The%20Cross-Section%20of%20Speculator%20Skill.pdf) · [Just How Much Do Individual Investors Lose by Trading? (RFS 2009)](https://www.johnhcochrane.com/s/Barber_etal_HowMuchDoIndividualInvestorsLose_RFS_2009.pdf)

Note what the "<1%" figure means for bot-building: it is the base rate for *discretionary* traders, but the constraint it reflects — costs and adverse selection exceed predictive edge — applies identically to an algorithm. Automating a coin flip does not make it a positive-expectancy coin flip; it just makes you flip faster and pay more fees.

---

## 2. Why backtested day-trading bots stop working

Three separate, well-replicated mechanisms. Any bot project that doesn't explicitly defend against all three is producing fiction.

**(a) Post-publication alpha decay.** McLean & Pontiff examined 82 published return predictors and found roughly **half of the abnormal return disappears after publication** (an earlier version of the paper puts the average decay near 35%). After publication, anomaly stocks show higher volume, variance and short interest — consistent with capital arriving to trade the signal.
Sources: [McLean & Pontiff](http://www.hec.ca/finance/Fichier/McLean.pdf) · [earlier version w/ 35% figure](http://www.ivey.uwo.ca/media/2827306/bengraham3rdsymposium-pontiff-paper-2014.pdf) · [summary](http://csinvesting.org/wp-content/uploads/2015/02/Anamolies-Dont-Do-as-Well-after-Publication.pdf)

**(b) Decay is predictable from overfitting markers, not just crowding.** A study of 72 published strategies found Sharpe ratios roughly halve out-of-sample. Its most interesting result: **year of publication alone explains ~30% of the variance in Sharpe decay**, and two overfitting proxies — the number of operations needed to compute the signal, and the signal's sensitivity to outliers — add another ~15%. Arbitrage-capital variables were statistically significant but weak predictors. In plain terms: **complicated signals decay faster, and the reason is mostly that they were overfit, not that someone competed them away.**
Source: [Why and how systematic strategies decay (arXiv 2105.01380)](https://arxiv.org/html/2105.01380v1)

**(c) Backtest overfitting is a quantifiable statistical error.** Bailey & López de Prado formalised this: if you try *N* variants on one dataset and keep the best, the maximum in-sample Sharpe is inflated even when every candidate is pure noise. Their tooling — the **Deflated Sharpe Ratio** and **Minimum Backtest Length (MinBTL)** for a given number of trials — exists specifically to test whether a result survives the number of things you tried.
Sources: [Pseudo-Mathematics and Financial Charlatanism](https://www.carmamaths.org/resources/jon/backtest.pdf) · [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) · [Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)

**Concrete decay example — pairs trading.** Do & Faff re-ran the classic Gatev distance-method pairs strategy forward in time. Mean monthly excess return of the top-20 pairs portfolio: **0.86% (1962–1988) → 0.37% (1989–2002) → 0.24% (2003–2009)** — before the costs that would consume most of the last figure. It performs better in turbulent markets.
Source: [Does Simple Pairs Trading Still Work? (Financial Analysts Journal)](https://tandfonline.com/doi/pdf/10.2469/faj.v66.n4.1)

---

## 3. The strategies that DO have documented positive expectancy

### 3.1 Funding-rate / basis carry — best evidence-to-accessibility ratio

Structure: hold spot long, short the equivalent notional in perpetual futures. Net delta ≈ 0, so directional price risk is hedged out; you collect the funding payment that longs pay shorts. In TradFi terms this is a [cash-and-carry trade](https://www.kraken.com/learn/futures-trading-funding-rate-arbitrage).

Why the edge exists structurally: perpetual funding is not noise, it's a **risk premium** — leveraged longs persistently outnumber leveraged shorts in crypto, so the short side gets paid. Binance's baseline funding rate is 0.01% per 8-hour interval ([Presto Labs](http://prestolabs.io/research/optimizing-funding-fee-arbitrage)), i.e. ~10.95%/yr at the floor when the basis is flat.

Live evidence at scale: Ethena runs exactly this trade as a $B-scale protocol. Its docs cite historical funding averaging **~8% annualized**; realized sUSDe yields have run roughly **5–15% APY through the cycle**.
Sources: [Ethena docs](https://docs.ethena.fi/solution-overview/liquid-stables-dynamic-allocation) · [mechanism explainer](https://eco.com/support/en/articles/15254002-ethena-usde-and-susde-2026-delta-neutral-yield)

**The honest caveats, from the peer-reviewed work rather than the marketing:** a 2026 *Journal of Financial Technology* paper decomposes CEX–DEX funding arbitrage risk and concludes net returns are driven mainly by funding carry but are **highly sensitive to assumptions and should not be read as frictionless arbitrage profit.**
Source: [Springer, 10.1007/s42521-026-00213-3](https://link.springer.com/article/10.1007/s42521-026-00213-3)

What actually kills this trade — none of these are price risk, which is why naive backtests look so good:
- **Funding inverts.** In sustained bear markets funding goes negative and you *pay*. Ethena's own risk framing: persistent deep negative funding drains the reserve, yield goes to zero or below, redemptions follow ([analysis](https://altcoininvestor.com/ethena-sustainability-analysis/)).
- **Venue/counterparty risk.** Your hedge lives on an exchange. Exchange insolvency = unhedged.
- **Liquidation of the short leg** on a violent upward move if margin management is sloppy. This is the #1 implementation bug.
- **Execution slippage** on both legs, plus rebalancing costs as the hedge drifts.

### 3.2 Slow time-series momentum (trend following) — strongest academic record, worst patience requirement

This is the most robustly documented anomaly in the literature. Moskowitz, Ooi & Pedersen showed an instrument's own past 12-month excess return positively predicts its future return across equity index, bond, currency and commodity futures. AQR extended it across **67 markets from 1880–2016**; an independent study found it in individual US stocks **1927–2017**, not confined to sub-periods or size buckets.
Sources: [Time Series Momentum (JFE 2012)](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) · [A Century of Evidence on Trend-Following](https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing) · [~100 years of stock returns](http://www.research.lancs.ac.uk/portal/services/downloadRegister/248285077/Time_Series_Momentum_in_Nearly_100_Years_of_Stock_Returns.pdf)

**The reality check that matters more than the backtests.** The SG Trend Index tracks the 10 largest trend-following CTAs, net of fees, daily. Through the 2010s — a full decade — it returned roughly **0.4% annualized with a ~21.8% maximum drawdown.** Then ~+27% in 2022.
Sources: [Price Action Lab](https://www.priceactionlab.com/Blog/2023/02/managed-futures-trend-following/) · [index methodology](https://wholesale.banking.societegenerale.com/fileadmin/indices_feeds/SG_Trend_Index_Methodology.pdf) · [decade-by-decade analysis](https://www.welton.com/performance-drivers-return-for-quant-macro-and-trend-following/)

Read that carefully: **the best-documented systematic strategy in all of finance, run by the world's best-capitalised practitioners, paid approximately nothing for ten consecutive years.** This is the realistic shape of a genuine edge. Any bot promising smooth monthly returns is not offering you a better version of this — it's offering you a fiction.

Note also that trend following is *not day trading*: the signal horizon is months. Holding period is the reason it survives costs.

### 3.3 Latency arbitrage / MEV — real, auditable, and effectively closed

The most verifiable profits in the entire space, because they're on-chain. And the data is brutal about who gets them.

A 19-month study (Aug 2023 – Mar 2025) of CEX–DEX arbitrage identified **$233.8M extracted across 7.2M arbitrages by 19 major searchers — and three searchers captured roughly three-quarters of both volume and extracted value.**
Source: [arXiv 2507.13023](https://arxiv.org/abs/2507.13023)

Block building shows the same monopoly dynamic: [one builder produced 87%+ of blocks and captured ~90% of MEV profit](https://www.arxiv.org/pdf/2602.15395); on Ethereum, [three builders produced 80% of blocks](https://arxiv.org/html/2407.13931v1), with profitability tied to **exclusive order flow** — a business-development asset, not a coding one.

And the unit economics at the retail end are grim. Flashbots' analysis of OP-Stack rollups found spam bots consuming >50% of gas while paying <10% of fees, with two searchers responsible for >80% of spam on Base. Their worked example of a *successful* arbitrage: **$0.12 of profit against $0.02 of fees.**
Source: [MEV and the Limits of Scaling](https://writings.flashbots.net/mev-and-the-limits-of-scaling)

Verdict: the edge is 100% real and 100% about infrastructure — co-location, private order flow, custom builders. It is not addressable by writing better strategy logic.

### 3.4 Market making — real edge, and the one that punishes the undercapitalised fastest

Spread capture is legitimate compensation for two things: **inventory risk** and **adverse selection**. The canonical implementation is Avellaneda–Stoikov, which skews quotes away from mid as inventory accumulates ([Hummingbot's implementation](https://hummingbot.org/strategies/v1-strategies/avellaneda-market-making), [technical walkthrough](https://hummingbot.org/blog/technical-deep-dive-into-the-avellaneda--stoikov-strategy/)).

The binding constraint is adverse selection, not spread width: informed order flow is **most harmful precisely when aggregate market informedness is low** — i.e. the quiet, range-bound conditions where naive market-making backtests look best ([arXiv 2606.05882](https://arxiv.org/abs/2606.05882)). Market-making P&L is best in sideways markets and bleeds in trends ([Hummingbot](https://medium.com/@hummingbot/extracting-the-best-value-from-your-hummingbot-order-management-configurations-6f5c689769c3)).

---

## 4. "Harvesting" in the DeFi sense — the evidence is genuinely bad

If by "harvesting bot" you meant LP yield farming / auto-compounding, this is the weakest-evidence category in the review, and it's the one most aggressively marketed.

**Roughly half of LPs lose money.** Topaze Blue with Bancor analysed ~17,000 Uniswap v3 wallets: pools generated **$199M in fees against $260M of impermanent loss — net ~-$60M, with 49.5% of liquidity providers in negative territory.**
Sources: [CryptoSlate](https://cryptoslate.com/new-report-shows-50-of-uniswap-v3-liquidity-providers-are-losing-money/) · [Crypto Briefing](https://cryptobriefing.com/half-uniswap-v3-liquidity-providers-underperform-holding-bancor-study/)

**Independent academic work agrees.** An arXiv study of pool-level returns found the **median liquidity pool had net nil ROI once impermanent loss was counted**, with wide cross-sectional dispersion.
Source: [arXiv 2108.06593](https://arxiv.org/pdf/2108.06593v2)

**There is a theoretical reason, not just bad luck.** Milionis, Moallemi & Roughgarden's **Loss-Versus-Rebalancing (LVR)** decomposition shows an AMM LP position is structurally worse than the equivalent rebalancing portfolio: the pool quotes stale prices, and arbitrageurs pick them off. LVR is **non-negative and non-decreasing** — it is a *predictable cost*, scaling with volatility, not a risk that averages out. LP profitability is therefore fees *minus* LVR.
Source: [arXiv 2208.06046](https://arxiv.org/pdf/2208.06046v5)

**So what do auto-compounders actually add?** Yearn/Beefy/Convex-style vaults do one thing honestly and well: they **socialise gas costs across depositors and compound frequently**, converting APR to APY (a 50% APR compounded daily ≈ 64.8% APY) ([Spark glossary](https://www.spark.money/glossary/auto-compounding)).

That is a real but *modest* improvement, and it is an optimisation **on top of a base position whose median net return was around zero.** Compounding a negative-expectancy position faster does not fix it. The headline APY on a farm is a gross number; LVR and IL are subtracted from it and are not shown.

---

## 5. Commercial bot platforms: why I can't grade any of them above F

I looked for independent verification of vendor performance claims and **found none.** What exists:

- **Vendor self-reported stats.** Bitsgap's H1 2026 report gives win rates by bot type — GRID 35.14%, spot DCA 40.95%, DCA futures 50.92%, COMBO 57.85% ([source](https://bitsgap.com/blog/what-actually-worked-in-2026)). This is the vendor grading its own product, win rate is not P&L (grid bots win often and lose big), and there is no audited return series.
- **Academic grid-bot papers are backtests only.** A dynamic grid trading paper reports outperformance vs. traditional grid and buy-and-hold on BTC/ETH minute data 2021–2024 ([arXiv 2506.11921](https://arxiv.org/abs/2506.11921)). In-sample, one asset class, one regime, no live track record. Per §2, discount heavily.
- **The regulator has issued an advisory specifically about this product category.** The CFTC's *"AI Won't Turn Trading Bots into Money Machines"* warns that fraudsters promote automated trading algorithms and signal services promising unreasonably high or guaranteed returns — sometimes advertising 100% win rates — and states plainly that **claims of high or guaranteed returns are a fraud red flag.**
Source: [CFTC Customer Advisory](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html) · [PDF](https://www.cftc.gov/sites/default/files/2024/01/AITradingBots_0.pdf)

Open-source frameworks (Freqtrade, Hummingbot, NautilusTrader) are a different thing and worth distinguishing: they sell you **no strategy at all**, just execution plumbing. That makes them honest. It also means the edge problem remains entirely yours.

---

## 6. What the evidence implies for methodology

If the goal is to build something, the research says the *process* matters more than the signal:

1. **Prefer structural premia over prediction.** Funding carry and trend have identifiable economic reasons for existing. "The model found a pattern" does not.
2. **Longer holding periods.** Cost per unit of return is what killed the Taiwanese day traders' gross profits. Slower = survivable.
3. **Count your trials and deflate accordingly.** Report a Deflated Sharpe Ratio and check MinBTL. A Sharpe of 2 from 10,000 configurations is weaker evidence than a Sharpe of 0.8 from three.
4. **Model costs adversarially.** Fees, funding, slippage, gas, and — for LP strategies — LVR explicitly. Most retail backtests fail on this line alone.
5. **Prefer simple signals.** Empirically, signal complexity predicts faster decay ([arXiv 2105.01380](https://arxiv.org/html/2105.01380v1)).
6. **Walk-forward, then paper-trade, then minimum size.** Treat every live month as the only real data point you have.
7. **Size for a lost decade.** The SG Trend precedent is the benchmark for how long a *real* edge can pay nothing.

---

## 7. Where this review is uncertain

- Private quant fund results are unobservable; absence of public evidence for profitable retail bots is partly a reporting-bias artifact.
- Crypto-specific data covers roughly one and a half market cycles. Funding carry's ~8% historical average rests on a short and structurally shifting sample.
- The funding-carry literature is thin and recent compared to the equity-anomaly literature.
- Vendor-reported figures cited in §5 are unverified and included only to characterise what the market claims.

*This document reviews published research. It is not financial advice, and nothing here is a recommendation to deploy capital.*
