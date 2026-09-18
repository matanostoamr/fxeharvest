# Trend-Filtered Grid on EUR/USD — Critique & Redesign

Assessment of the proposed design, 18 September 2026. Sources inline.
Content from sources was rephrased/summarized for compliance with licensing restrictions.
Not financial advice.

---

## 1. Verdict in one paragraph

You correctly identified the failure mode that kills grid bots — unhedged macro trend — which puts you ahead of most people running these. But the fix doesn't work, for a reason that is structural rather than a matter of tuning: **a trend filter addresses the *direction* of the tail risk while leaving its *shape* untouched.** The grid's loss function is quadratic in adverse displacement while its profit is linear in oscillation count. No lagging indicator changes those two exponents. A trend filter makes the blow-up less frequent and therefore later and larger.

The three things worth changing are: a **basket-level stop** (converts unbounded loss to bounded), an **efficiency-ratio gate** instead of EMA/ADX (measures the thing that actually drives grid P&L), and — if you want the strongest version — running the grid on a **cointegrated spread** rather than EUR/USD outright, so that mean reversion is an estimated parameter instead of an assumption.

---

## 2. What you got right

Worth stating explicitly, because these are not trivial:

1. **You identified the correct failure mode.** Unfiltered grids die to trend. That is the right diagnosis and most retail material never gets there.
2. **Your grid spacing is well chosen, and it solves the cost problem.** This matters. At 15–25 pips, with EUR/USD raw spreads near 0.0–0.1 pips plus roughly $6–7 round-turn commission per lot (~0.6–0.7 pips), your all-in cost is ~0.8 pips against 20 pips of gross capture — about **4% of gross**. Compare that with a tight 3–5 pip grid, where cost is 20–30% of gross and the strategy is dead on arrival. Costs are genuinely not your problem. ([broker cost comparison](https://www.fxempire.com/news/article/which-gold-xau-usd-trading-platforms-offer-low-spreads-and-low-trading-costs-top-5-brokers-compared-2026-1622410))
3. **EUR/USD is the right instrument** if you're going to do this at all — cheapest major, lowest volatility, 30:1 leverage cap rather than gold's 20:1.
4. **You chose EUR/USD over gold**, which given gold's 22% peak-to-trough drawdown in 2026 was the correct call and would by itself have saved the account.

So the instrument selection and cost engineering are sound. The problem is one level deeper.

---

## 3. The structural problem

### 3.1 The baseline expectancy is zero — per the pro-grid literature itself

The most useful citation here is from the paper *advocating* an improved grid strategy. Before proposing their dynamic version, the authors analyse the standard one and state that **under simple assumptions the expected return of a traditional grid strategy is essentially zero**:

> *"Starting with an analysis of the expected value of the traditional grid strategy, we show that under simple assumptions, its expected return is essentially zero."*
> — [From Zero Expectation to Market Outperformance, arXiv 2506.11921](https://arxiv.org/abs/2506.11921)

That is the honest starting point. A grid is not a positive-expectancy structure that trend occasionally interrupts. It is a **zero-expectancy structure**, and your realized return is entirely determined by whether the price process is more mean-reverting than a random walk at your grid's timescale. Costs make it slightly negative. The trend filter does not add expectancy — it only tries to avoid the worst realizations of a zero-mean bet.

### 3.2 A grid is a short-gamma position

This is the same trade as delta-hedging a short option: buying as price falls, selling as it rises, in fixed increments ([Quantpedia on grid trading and delta hedging](https://quantpedia.com/whats-the-relation-between-grid-trading-and-delta-hedging/)). You are short volatility and short gamma, which is profitable in rangebound markets and loses in directional ones ([gamma primer](https://www.tastylive.com/news-insights/gamma-trading-strategies-a-trader-s-guide-to-volatility)).

The asymmetry, concretely. With spacing *s* and one unit per level, after price has moved *N* levels against you the open loss is:

```
s · (1 + 2 + … + N)  =  s · N(N+1)/2     →  grows with N²
```

while realized profit is `s × (number of completed round trips)` → grows with **N¹**.

Numerically, on a 20-pip grid at 1 lot/level ($10/pip):

| Adverse move | Levels | Open loss |
|---|---|---|
| 100 pips | 5 | $600 |
| 200 pips | 10 | $2,200 |
| 400 pips | 20 | $8,400 |
| 600 pips | 30 | $18,600 |

A 600-pip EUR/USD move is an ordinary year, not a crisis. Meanwhile the oscillation income over the same period might be a few hundred dollars per month. **The quadratic term wins, and it wins suddenly.** This is the gambler's-ruin structure analysed formally for grid trading by [Taranto & Khan](https://webmail.thescipub.com/pdf/jmssp.2020.182.197.pdf).

### 3.3 The premise — oscillation — is measured with the wrong statistic

You reasoned from the 50–80 pip daily range. But **daily range is high-minus-low; a grid is paid for repeated crossings of the same levels.** Those are different quantities.

Two days can both print a 60-pip range: one oscillates across the same 20-pip band six times (a grid earns six round trips), the other travels 60 pips in one direction (a grid earns one fill and holds three losing levels). Range is identical; grid P&L is opposite in sign.

The statistic that governs grid P&L is **path length relative to net displacement**. That is exactly what Kaufman's Efficiency Ratio measures: absolute net change over the window divided by the sum of absolute bar-to-bar changes ([definition](https://www.luxalgo.com/library/concept/kaufman-efficiency-ratio/), [StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama)). ER near 0 = choppy, grid-friendly. ER near 1 = directional, grid-hostile.

**You should be gating on ER, not on an EMA.** See §5.2.

### 3.4 Whether EUR/USD mean-reverts at your timescale is genuinely unsettled

The entire strategy rests on this, so it deserves care. The evidence is mixed:

- Variance-ratio tests on daily and weekly data find **euro exchange rates against major trading partners follow the random walk hypothesis** and are weak-form efficient ([study](https://www.researchgate.net/publication/46523861_Testing_for_Random_Walk_Behavior_in_Euro_Exchange_Rates)); another finds the random-walk hypothesis cannot be rejected against most major currencies ([Chortareas et al.](http://polymer.bu.edu/hes/rp-chortareas11econophysics.pdf)).
- Against that, one study reports **mean reversion is present in intraday EUR/USD**, with ADF rejecting a unit root ([EURUSD Intraday Price Reversal](https://www.researchgate.net/publication/279276207_Eurusd_Intraday_Price_Reversal)).
- And variance-ratio tests themselves are **not statistically robust and can mislead in high-frequency settings** ([Andersen & Bollerslev, JF](https://public.econ.duke.edu/~boller/Published_Papers/jf_01.pdf)).

**Conclusion: the mean reversion your bot needs is a contested empirical property, not an established one.** It must be measured on your data at your spacing, per §6 — not assumed from the fact that price visibly wiggles on a chart. Everything wiggles on a chart; random walks wiggle beautifully.

---

## 4. Why the trend filter specifically doesn't fix it

Four independent reasons. The third is the one I'd most want you to sit with.

**1. Lag is structural, not a parameter.** A daily EMA is a smoother; it must accumulate observations before it turns. ADX is worse — it is double-smoothed (a smoothing of DX, which is itself built from smoothed directional movement), so it typically confirms a trend already well underway ([KAMA/ER background](https://www.luxalgo.com/library/concept/kama/)). Grid damage is concentrated in the *first* violent leg. Your filter flips **after** you have already accumulated the losing ladder. The filter protects you from the second half of a move you are already maximally exposed to.

**2. ADX gives strength, not direction.** ADX alone cannot tell you to stop buying; you need +DI/−DI for sign. As specified, the rule is underdetermined.

**3. Whipsaw hits you precisely when the grid is supposed to be earning.** This is the deep one. A trend filter mis-fires most in choppy, rangebound conditions — which are *exactly* the conditions your grid needs to harvest. So the filter is most likely to be wrong when you most need it to stay out of the way, and it will repeatedly flip you to one-sided just in time for the range to reverse. In a genuine trend the filter is right, but there you're earning little anyway because half your grid is switched off. **The filter is anti-correlated with its own usefulness.**

**4. A one-sided grid is a logically incoherent position.** Consider "downtrend → sells only." You now sell at successively *higher* prices as the market rallies against you, and take profit as it falls. That is a **mean-reversion bet nested inside a trend-following bet**, and the two halves disagree. You've combined a trend follower's regime-call risk with a mean-reverter's fat left tail — inheriting the weakness of each. If the trend call is right you make grid-sized crumbs; if it's wrong you take a quadratic loss with no offsetting bound.

Worth noting too: both the Fed and the ECB hiked in September 2026 (Fed to 3.75–4.00%, ECB deposit to 2.50%). Simultaneous two-sided policy movement is the least stable possible regime for a filter that assumes a persistent trend to lean on.

---

## 5. Concrete improvements, in order of importance

### 5.1 Basket-level stop — non-negotiable

One change matters more than all others: **a stop on aggregate open P&L of the whole grid, not per-order.**

```
if unrealized_basket_pnl < -(K × ATR20_in_currency):
        close_all(); halt(cooldown_hours)
```

Start with K such that max loss ≈ 2–3× a typical good month. This converts the `N²` tail into a bounded loss. It will feel bad — you will get stopped and watch price come back — and it is the difference between a strategy that has drawdowns and one that has a terminal event. **A grid without a basket stop is not a strategy with a risk of ruin; it is a strategy whose expected time to ruin is finite.**

### 5.2 Replace EMA/ADX with an Efficiency-Ratio gate

Gate on the statistic that actually determines grid P&L (§3.3):

```
ER = |close[0] − close[−N]| / Σ|close[i] − close[i−1]|,  N ≈ 20–30

ER < 0.30  → grid ON, symmetric (choppy: the regime you're paid in)
0.30–0.45  → grid ON, half size, tighter basket stop
ER > 0.45  → grid OFF entirely — flat, not one-sided
```

Two properties make this better than an EMA gate. It is **directionless**, so it cannot produce the incoherent one-sided grid of §4.4. And it is **contemporaneous** — it measures realized path efficiency over the window rather than waiting for a crossover. Rank ER within its own recent history rather than using a fixed threshold, since absolute ER levels drift with volatility regime ([ER gate as regime classifier](https://pl.tradingview.com/scripts/trend-quality/)).

**When the regime is trending, go flat — do not go one-sided.** "No position" is a position, and it's the correct one here.

### 5.3 Scale spacing to volatility, not fixed pips

Fixed 15–25 pips is mis-specified across regimes. EUR/USD daily range moved from 70–90 pips to 50–70 pips in June 2026 ([tradethatswing](https://tradethatswing.com/analyzing-eur-usd-volatility-for-day-trading-purposes/)) — the same fixed grid is too tight in one regime and too wide in the other. Use `spacing = c × ATR(20)`, recomputed daily, with c chosen so spacing lands in your 15–25 pip band at *median* volatility.

### 5.4 Fixed size per level, hard level cap, never martingale

Equal size at every level. Hard maximum number of open levels (start at 5–6, not 20). Position-size progression — doubling after losses — is the single fastest route to ruin in this family and is explicitly what turns a bounded bad day into an account-ending one ([martingale grid discussion](https://www.tradingview.com/script/oxvR5vMy-Grid-Like-Strategy/)).

### 5.5 Event blackouts

Flat, and cancel resting orders, 15 minutes either side of FOMC, ECB, NFP and CPI, plus month-end and quarter-end. Your own premise names central bank action as the blow-up trigger — so make that mechanical rather than relying on a filter to infer it after the fact.

### 5.6 Buy back the tail

Since a grid is short gamma (§3.2), the principled hedge is to **buy back a little gamma**: a cheap out-of-the-money EUR/USD option, or a far-out stop-entry position in the direction of your accumulating exposure. This is precisely the remedy the carry-trade literature arrives at for negatively skewed premium harvesting — see [Crash-Neutral Currency Carry Trades (Jurek)](https://www.johnhcochrane.com/s/jurek_currency.pdf), where G10 carry is hedged with currency options. It costs you part of the yield. That is what insurance costs.

---

## 6. The better version of your idea: grid a cointegrated spread

If you like oscillation harvesting — and it's a legitimate thing to like — the strongest upgrade is to stop applying it to a price series that may be a random walk, and apply it to one that is **mean-reverting by construction**.

**The idea.** Instead of gridding EUR/USD outright, build a spread that is statistically stationary — e.g. EUR/USD against GBP/USD, hedge-ratio estimated by regression, or EUR/USD against a small basket of correlated majors. Test the residual for stationarity, estimate its **half-life of mean reversion**, then place the grid on the residual's z-score rather than on price.

**Why this is materially better:**

| | Grid on EUR/USD | Grid on cointegrated spread |
|---|---|---|
| Mean reversion is… | assumed, and contested (§3.4) | **estimated and testable**, with a half-life |
| Grid spacing set by… | pips, arbitrary | z-score units, i.e. σ of the residual |
| Exit criterion | hope | z → 0, with a time-stop at ~2× half-life |
| Trend risk | unbounded | bounded by cointegration; **breakdown is detectable** |
| Kill signal | lagging indicator | residual fails its stationarity test → stand down |

That last row is the real prize. On EUR/USD outright you have no principled way to know the regime has changed until the loss tells you. On a spread, cointegration breakdown is a **testable statistical event** — rolling ADF, or a widening half-life — and it fires before the P&L does. You get an exit criterion derived from the same model that generated the entry, instead of one bolted on from a different school of thought.

Grid spacing then becomes ~0.5σ of the residual, max levels ~±3σ, basket stop at ~3.5σ or on stationarity failure. The strategy also becomes roughly market-neutral, so ECB/Fed surprises that move both legs largely cancel — which directly addresses the blow-up trigger you named.

This is the same instinct you had. It just puts the mean reversion on a foundation you can measure instead of one you have to hope for.

---

## 7. Test protocol — the decision, before the bot

Do not build the execution engine first. Build this, in this order; steps 1–3 are a couple of days and will probably settle the question.

**Step 1 — Measure oscillation, not range.** On ≥10 years of EUR/USD minute bars, compute the Efficiency Ratio distribution by year. Establish what fraction of days sit below your ER<0.30 gate. *That fraction is the ceiling on how often this strategy can work.*

**Step 2 — Simulate the grid with zero filter and no stop.** You need to see the raw shape: distribution of basket drawdown, maximum levels reached, worst adverse excursion per year. This tells you how much capital the structure actually requires. Most people skip this because it's discouraging; it is the most informative run you will do.

**Step 3 — Compute grid expectancy per unit of maximum adverse excursion, by year.** Not total return. Return ÷ worst drawdown, year by year. If that ratio isn't stable and positive across ≥7 of 10 years — including 2014–15 (EUR/USD ~1.39→1.05), 2022, and 2026 — the edge is a regime artifact.

**Step 4 — Compare filters honestly, on the same data.** No filter vs. EMA gate vs. ADX gate vs. ER gate. Report each one's effect on *tail* statistics (worst basket loss, 99th-percentile drawdown), not on average return. My expectation, stated in advance so it can be falsified: the EMA/ADX gates will improve average return slightly and barely move the tail; the ER gate will cut the tail meaningfully and reduce the trade count a lot.

**Step 5 — Deflate for trials.** Count every spacing, threshold and lookback you tried, and report a Deflated Sharpe Ratio ([Bailey & López de Prado](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)). Grid strategies have many tunable knobs, which makes them unusually easy to overfit.

**Step 6 — Holdout, then paper, then minimum size.** Fit nothing on the last 3 years.

**Pass bar:** positive return-to-max-adverse-excursion in ≥7 of 10 years, present in the untouched holdout, with the worst simulated basket loss inside your basket stop — and the stop actually triggering in the backtest. If your basket stop never fires in 10 years of backtest, it is mis-specified, not safe.

---

## 8. Summary

| Your component | Assessment | Recommended change |
|---|---|---|
| Grid on EUR/USD | Correct instrument | Keep; consider spread version (§6) |
| 15–25 pip spacing | Good — costs ~4% of gross | Make it `c × ATR(20)` |
| Oscillation premise | Measured with wrong statistic | Gate on Efficiency Ratio |
| EMA/ADX trend filter | **Lagging, whipsaw-prone, anti-correlated with its own usefulness** | Replace with ER gate; **flat, not one-sided** |
| One-sided grid in trend | Logically incoherent | Delete — go flat instead |
| Basket risk control | **Absent — this is the actual gap** | **Add basket stop. Non-negotiable.** |
| Tail hedge | Absent | Cheap OTM option (§5.6) |

**The honest bottom line:** your instinct about the failure mode was right, and your cost engineering is better than most. But the trend filter is treating a symptom. The grid's problem is that it is a zero-expectancy, short-gamma structure whose losses compound quadratically — and the only things that change that are a hard bound on the basket loss, a gate that measures oscillation directly, and ideally an underlying that is mean-reverting by construction rather than by assumption.
