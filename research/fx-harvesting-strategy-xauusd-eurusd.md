# FX "Harvesting" for XAUUSD and EURUSD — Evidence Review & Strategy Spec

Research review as of **18 September 2026**. Sources cited inline.
Content from sources was rephrased/summarized for compliance with licensing restrictions.
Not financial advice; nothing here is a recommendation to deploy capital.

---

## 0. Direct answer

You asked for a harvesting bot for gold or EURUSD. The research produces a clear, and probably unexpected, split:

**Gold cannot be harvested. It is structurally the wrong instrument for this.** Gold has a *positive cost of carry* — holding it costs money. A long XAUUSD position **pays** financing every night; it does not collect. There is no carry to harvest on the long side, and the short side (which does collect) has been a wealth-destruction machine. Gold is a **trend** instrument, not a carry instrument.

**EURUSD can be harvested, but not the way retail bots do it.** The overnight-swap version is currently near-dead: the rate differential is ~1.375%, and typical broker swap markup is of the same order, so the broker takes most or all of your edge.

**The version that does survive the evidence is the one almost nobody runs: an intraday time-of-day harvest.** Multiple independent studies find the FX risk premium is not earned evenly around the clock — it is concentrated in US trading hours. One study finds **~80% of dollar carry returns and ~75% of HML carry portfolio returns are generated during the US trading day**, with currencies collectively *depreciating* against USD overnight ([Krohn, Mueller & Whelan, *FX Premia Around the Clock*](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/190753/Krohn_Mueller_Whelan_Jun2018_FXPremiaAroundTheClock.pdf) — see [abstract with figures](https://swlb2.aeaweb.org/conference/2019/preliminary/paper/QQ73KSH8)).

That reframes everything. **You don't hold overnight to collect swap — you hold during US hours to collect the premium, and you're flat overnight, which also means you pay no swap markup at all.** This is the single best-evidenced, retail-accessible harvesting structure I found for EURUSD.

| Candidate | Instrument | Evidence | Verdict |
|---|---|---|---|
| Intraday time-of-day premium | EURUSD | **B+** — replicated across currencies, timezones, decades | **Viable. Primary candidate.** |
| Overnight swap carry | EURUSD | **C−** — real premium, but ~1.375% gross vs broker markup | Marginal at retail CFD; better via futures |
| Overnight swap carry | XAUUSD | **F** — long pays, structurally inverted | Not a strategy |
| Grid / martingale "pip harvesting" | XAUUSD | **F** — no independent verification | **Actively dangerous.** See §5 |
| Trend following | XAUUSD | **A−** — century of evidence, positive skew | Viable, but it is not harvesting |

---

## 1. The FX-specific base rate

Before any strategy: regulator-mandated disclosures across three jurisdictions (ESMA/MiFID II in Europe, CFTC in the US, ASIC in Australia) document a retail client loss rate of roughly **74–89%**, with average losses per client ranging from about **€1,600 to €29,000**.
Sources: [MPRA analysis of the 74–89% loss rate](https://mpra.ub.uni-muenchen.de/129364/1/MPRA_paper_129364.pdf) · [ESMA product intervention FAQ](https://www.esma.europa.eu/sites/default/files/library/esma71-98-125_faq_esmas_product_intervention_measures.pdf) · [survey of 28 CFD providers, avg 76% losing](https://www.babypips.com/news/almost-80-percent-of-retail-traders-are-unprofitable)

ESMA leverage caps, which tell you how the regulator ranks the risk: **30:1 for major pairs, 20:1 for gold.**

---

## 2. Why gold cannot be "harvested"

This is a structural point, not a market view.

Gold normally trades in **contango** — futures above spot — because of the cost of carrying metal. Backwardation is rare and notable when it happens. The cost of carry is generally **positive**, meaning the holder incurs a cost; it can only go negative if convenience yield exceeds funding plus storage, which is unusual.
Sources: [gold lease rates & backwardation](https://blofin.com/en/academy/education/gold/gold-lease-rates-and-backwardation-explained) · [understanding gold cost of carry](https://www.advisorperspectives.com/commentaries/2014/03/26/understanding-gold-cost-of-carry-in-various-currencies) · [Kitco gold FAQ](https://www.goldchartsrus.com/papers/KitcoFAQ.php)

Translated to your XAUUSD CFD: **long gold pays roughly the USD funding rate (~3.875% right now) less the gold lease rate, annualized, every night.** You are the one being harvested. To be on the collecting side you must be **short gold** — and gold went from roughly $2,600 in late 2024 to an all-time high near **$5,608 in January 2026** ([Trading Economics](https://tradingeconomics.com/commodity/gold), [EBC on the speed of the move](https://www.ebc.com/forex/gold-highest-price-ever-xauusd-record-2026)). A short-carry harvester would have been annihilated collecting ~4% while the underlying doubled.

There is no version of "carry harvesting on gold" that works. If someone sells you one, they are selling you a short-volatility position with a yield label on it.

---

## 3. EURUSD overnight carry: the numbers as of today

**Current policy rates.** The Fed raised by 25bp on **16 September 2026** to a target range of **3.75%–4.00%** — its first hike since July 2023, on a 12–0 vote ([Fox Business](https://www.foxbusiness.com/economy/policy/federal-reserve-interest-rate-decision-september-16-2026), [CBS](https://www.cbsnews.com/news/fed-interest-rate-decision-today/)). The **ECB deposit facility rate is 2.50%**, raised from 2.25% in September 2026 ([Trading Economics](https://tradingeconomics.com/euro-area/deposit-interest-rate), [ECB decision](https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260910~314e508016.en.html)).

**So: differential ≈ 1.375% in favour of USD. The positive-carry direction is SHORT EURUSD.**

Now the part that kills it. Overnight financing is quoted as an asymmetric bid/offer. A worked broker example: with EUR/USD swap at 0.50 / (1.00), a 1-lot short earns 0.5 pips (~$5) while a 1-lot long pays 1.0 pip (~$10) ([tastyfx](https://www.tastyfx.com/markets/overnight-funding-rates/)). **That 0.5 pip/day gap is broker markup — roughly 1.5% annualized**, i.e. comparable to or larger than the entire 1.375% differential you're trying to collect.

**Risk-adjusted reality check.** EURUSD is trading around 1.148–1.154 and has been in what one volatility tracker classifies as *Common Low Volatility* — 50–70 pips of daily range — since June 2026 ([tradethatswing](https://tradethatswing.com/analyzing-eur-usd-volatility-for-day-trading-purposes/), [FXStreet](https://www.fxstreet.com/currencies/eurusd)). Call it 60 pips ≈ 0.52%/day ≈ **~8% annualized volatility**.

> Gross carry 1.375% ÷ ~8% volatility ≈ **0.17 carry-to-vol ratio**, before costs. After a ~1.5%/yr broker markup, the net expected carry is approximately **zero or negative**.

To make that interesting you'd need leverage — and leveraging a thin carry is precisely the setup the literature warns about. Brunnermeier, Nagel & Pedersen showed carry returns are **negatively skewed**, with the interest differential itself driving crash risk: *"up by the stairs and down by the elevator."* The mechanism is sudden unwinding when funding liquidity and risk appetite contract.
Sources: [Carry Trades and Currency Crashes (NBER)](https://www.nber.org/papers/w14473) · [paper PDF](https://www.princeton.edu/~markus/research/papers/carry_trades_currency_crashes_old.pdf) · [author slides](https://markus.scholar.princeton.edu/sites/g/files/toruqf2651/files/carry_trades_currency_crashes_slides_0.pdf)

Also note both central banks are now hiking simultaneously, so the differential is not a stable parameter — treat it as a live input, not a constant.

**If you do want overnight carry, the structural fix is to stop using CFDs.** On CME FX futures the financing is embedded in the basis, is identical for all participants, and is not marked up or adjustable ([CME on swap fee inconsistencies](https://www.cmegroup.com/articles/2026/fx-swap-fees-spotting-inconsistencies.html)). That single change recovers most of the markup.

---

## 4. The recommended candidate: intraday time-of-day harvest on EURUSD

### 4.1 The evidence

This is a genuinely replicated anomaly with an economic story, not a backtest artifact.

- **Core pattern:** currencies tend to depreciate during their own local trading hours and appreciate outside them; confirmed across a range of currencies and time zones ([Breedon & Ranaldo, QMUL WP694](https://www.qmul.ac.uk/sef/media/econ/research/workingpapers/2012/items/wp694.pdf); [related](https://www.efmaefm.org/0efmameetings/efma%20annual%20meetings/2007-Austria/papers/0242.pdf)).
- **EURUSD specifically, with clock times:** the euro depreciates against the dollar during the European business day — approximately **3:00 AM to 11:00 AM New York time** — then appreciates against the dollar through the close of the US business day ([QuantRocket](https://www.quantrocket.com/blog/business-day-fx-patterns/)).
- **Magnitude and where the premium lives:** ~**80% of dollar carry returns** and ~**75% of HML carry returns** accrue during the US trading day, with currencies collectively depreciating vs USD overnight ([Krohn, Mueller & Whelan](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/190753/Krohn_Mueller_Whelan_Jun2018_FXPremiaAroundTheClock.pdf)).
- **Independent confirmation of the divergence being tradable:** European currencies on average appreciate vs the dollar during US business hours and depreciate during European business hours, and the divergence generates a profitable intraday strategy ([CICF paper 67](http://www.cicfconf.org/sites/default/files/paper_67.pdf)).
- **Why it exists:** investors require compensation for holding currencies that do badly when US economic prospects deteriorate; that premium is earned when US information arrives — i.e. during US hours ([summary](https://valuelytica.substack.com/p/the-four-hour-fx-trade)).

### 4.2 Why this is the right structure for a bot

1. **Flat overnight → zero swap exposure.** You completely sidestep the broker markup that destroys the overnight carry trade (§3).
2. **Time-based entries and exits.** No prediction, no indicator fitting, minimal parameters — which matters, because signal complexity empirically predicts faster post-publication decay ([arXiv 2105.01380](https://arxiv.org/html/2105.01380v1)).
3. **EURUSD is the cheapest instrument in FX** — raw spreads near 0.0–0.1 pips plus commission — and cost is the binding constraint on any twice-daily strategy.
4. **No leverage required for the edge to exist**, which avoids the crash-risk amplification in §3.

### 4.3 Specification

```
Instrument:  EURUSD (spot CFD acceptable; CME 6E futures preferred)
Timezone:    America/New_York, DST-aware  ← do not hardcode UTC offsets
Leg A:       SHORT  entry 03:00 NY   exit 11:00 NY
Leg B:       LONG   entry 11:00 NY   exit US session close (16:00-17:00 NY)
Overnight:   FLAT — always. No exceptions.
Sizing:      Fixed fractional, vol-targeted on 20d realized vol.
             Start at ≤0.5% account risk per leg.
Blackouts:   Flat 15 min before/after FOMC, ECB, NFP, CPI.
             Flat on month-end and quarter-end (FX fix distortions).
Kill switch: Halt on N consecutive losing days or X% drawdown.
```

**Build both legs as independently toggleable.** The evidence for the two halves is not equally strong, and you must be able to measure and run them separately.

### 4.4 The honest caveats

- **This is a published anomaly, so assume decay.** Published predictors lose roughly half their alpha after publication ([McLean & Pontiff](http://www.hec.ca/finance/Fichier/McLean.pdf)). These papers date from 2007–2019. Whatever magnitude the original authors found, **discount it by at least 50% before you believe it.**
- **Cost is the whole game.** Two round trips per day ≈ 500 round trips/year. At 0.3 pips all-in per round trip that's ~150 pips/year of friction. If the gross effect is under ~200 pips/year you have nothing. **This is the first thing to measure, before writing any bot.**
- **Effect size is unquantified in my sources.** I found direction, timing and statistical significance, but not a clean net-of-cost bps figure for EURUSD. You must measure it yourself — protocol in §6.
- **DST is a real bug source.** The 3AM/11AM NY boundaries shift relative to European hours twice a year in each region, and the mismatch weeks are genuinely different regimes.

---

## 5. Explicit warning: grid and martingale bots on gold

This is the most-marketed "gold harvesting bot" category and the evidence is worst. Gold's own 2026 tape is the argument:

**All-time high near $5,590–$5,608 in January 2026, followed by a 22% peak-to-trough drawdown, stabilising near $4,350 by mid-September 2026** ([discoveryalert](https://discoveryalert.com/analysis/gold-price-floor-fed-hike-september-2026/), [Trading Economics](https://tradingeconomics.com/commodity/gold), [Bybit](https://www.bybit.com/en/wiki/article/gold-2026-will-xau-usd-hit-new-all-time-highs/)).

A grid or martingale harvester accumulates against direction and is mathematically guaranteed to be at maximum position size at maximum adverse excursion. A 22% move in eight months on a 20:1-eligible instrument is a margin call, not a drawdown. Grid bots produce high *win rates* and catastrophic *loss sizes* — which is exactly why vendors publish win rate instead of P&L (a vendor's own H1 2026 figures put grid win rate at 35.14%, and win rate is not return anyway — [Bitsgap](https://bitsgap.com/blog/what-actually-worked-in-2026)).

The CFTC has an advisory aimed squarely at this product category — *"AI Won't Turn Trading Bots into Money Machines"* — noting that claims of high or guaranteed returns, or 100% win rates, are fraud red flags ([CFTC](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html)).

**If you want gold exposure in a systematic bot, the evidence supports trend following, not harvesting.** Trend strategies have the opposite payoff shape to grid: frequent small losses offset by rare large gains — positive skew ([arXiv 2501.07135](https://arxiv.org/html/2501.07135v1), [arXiv 2101.01006](https://arxiv.org/pdf/2101.01006)). Gold is a classic trend market. But accept the cost of that: as noted in the prior review, the SG Trend Index returned roughly 0.4% annualized across the entire 2010s with a ~21.8% max drawdown.

---

## 6. Validation protocol — do this before building the bot

The order matters. Steps 1–2 are cheap and will probably kill the idea, which is the point.

1. **Get the data.** Minute bars, EURUSD, bid *and* ask separately, ≥10 years, DST-correct timestamps. Bid/ask matters more than bar count.
2. **Measure the raw effect first — no strategy, no parameters.** Average return of the 03:00→11:00 NY window and the 11:00→US-close window, by year. Tabulate per year. *If it is not present in most years and stable in sign, stop here.*
3. **Subtract real costs.** Actual spread at those specific clock times (spreads widen at the 3AM European open and around the 4PM London fix) plus commission. Net, per year.
4. **Split the sample.** Fit nothing on the last 3 years. If the effect is absent post-2020, you have found a decayed anomaly — which the literature predicts.
5. **Deflate for trials.** Count every variation you tried (entry times, exit times, filters) and report a Deflated Sharpe Ratio and MinBTL ([Bailey & López de Prado](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)).
6. **Paper trade one full quarter** on live spreads and live fills.
7. **Go live at minimum size** and treat each month as a single data point.

A reasonable pass/fail bar before any capital: the effect is present in ≥7 of 10 years, survives real costs with a net Sharpe ≥0.5, and is still present in the untouched holdout.

---

## 7. Summary of what to build

**Build:** the intraday time-of-day harvest on EURUSD (§4), flat overnight, on CME 6E futures or a raw-spread account. Start with the measurement harness in §6, not the execution bot.

**Do not build:** any overnight-swap carry harvester on XAUUSD — the economics are inverted and you will be paying, not collecting. Any grid or martingale harvester on gold — 2026 alone would have taken 22% against you at maximum size.

**If you want gold in the system:** a slow trend-following sleeve, sized small, with a documented tolerance for multi-year flat periods. Different strategy, different expectations, honest evidence base.

The one-line version: **on these two instruments, the harvestable premium is in EURUSD and it lives in the US trading session, not overnight — and gold's carry runs the wrong way for a harvester.**
