# Cointegrated Spread Grid — EUR/USD vs GBP/USD, Explained

Companion to `spread_grid_lab.py` (built and validated 18 September 2026).
Not financial advice.

---

## 1. The core idea

A grid needs **mean reversion**. That is its one requirement. Gridding EUR/USD outright fails
because EUR/USD may not *have* mean reversion — variance-ratio studies frequently cannot
reject a random walk, and a grid on a random walk has exactly zero expectancy.

So: **stop gridding a price, and start gridding a spread that is mean-reverting by
construction.**

EUR/USD and GBP/USD **share the USD leg**. A large fraction of what moves them both is simply
dollar strength — when USD rallies, both fall together. Go long one and short the other in the
right ratio, and that common dollar factor largely **cancels out**.

What's left is **EUR versus GBP relative value**. And that residual has something EUR/USD does
not: an economic anchor. Two neighbouring economies, deeply linked by trade, with correlated
monetary policy. When EUR gets expensive relative to GBP, real economic forces push back. That
is a genuine reason to expect reversion — not a pattern seen on a chart.

**The difference in one line:** gridding EUR/USD assumes mean reversion. Gridding a
cointegrated spread lets you *measure* it, with a half-life and a p-value.

---

## 2. The trap to check first — and it will probably save you a leg of costs

Here is the algebra everyone skips. The spread is:

```
spread = log(EURUSD) − β · log(GBPUSD)
```

Now set β = 1:

```
log(EURUSD) − log(GBPUSD) = log( EURUSD / GBPUSD )
                          = log( (EUR/USD) × (USD/GBP) )
                          = log( EUR/GBP )
```

**At β = 1, your two-leg spread IS just EUR/GBP.** The USD cancels algebraically, not
approximately. The lab confirms this numerically — max difference between `log(A) − log(B)`
and `log(A/B)` is 1.11e-16, i.e. floating-point dust.

**Why this matters commercially.** If β ≈ 1, you would be running two positions, paying two
spreads and two commissions, to synthesise a cross rate you can trade **directly in one leg**.
That is double cost for zero benefit.

So the first thing the lab does is test β:

- **β ≈ 1** → trade **EUR/GBP directly**. One leg, half the cost. Then the real question
  becomes "is EUR/GBP mean-reverting?" — which is a much better question than the one you
  started with, because EUR and GBP are economically tethered in a way EUR and USD are not.
- **β materially ≠ 1 and stable** → the two-leg structure earns its extra cost, because you're
  capturing something the plain cross does not express.

For real EUR/USD and GBP/USD, β typically comes out **not far from 1**. So the honest
expectation is that this project resolves into **"grid EUR/GBP"** — simpler, cheaper, and
better than what you started with. Test it rather than assume it.

---

## 3. Mechanics, step by step

**Step 1 — Hedge ratio.** Regress log(EURUSD) on log(GBPUSD) by OLS. Slope = β. That is how
many units of GBP/USD neutralise one unit of EUR/USD.

**Step 2 — Build the spread.** `spread = log(EURUSD) − β·log(GBPUSD) − α`.

**Step 3 — Test that it is actually stationary.** Run an **ADF test** on the spread.
H₀ = unit root = *not* cointegrated. You need to **reject** H₀ (p < 0.05). If you cannot
reject, stop — there is no relationship to trade and everything downstream is noise fitting.

**Step 4 — Estimate the half-life.** Fit an Ornstein-Uhlenbeck model: regress Δspread on
lagged spread; `half-life = −ln2 / ln(1+b)`. This is the number that makes the strategy
*plannable*: it tells you how long a position should take to revert. A price grid has no
equivalent — you hold and hope. Here you get a time budget, and therefore a **time stop** at
roughly 2× half-life. If the spread hasn't reverted in twice its own characteristic time,
the model was wrong; exit on that basis rather than on pain.

**Step 5 — Convert to z-score.** `z = (spread − rolling mean) / rolling sd`. Now the grid is
denominated in standard deviations — a unit that means the same thing across volatility
regimes. This automatically solves the ATR-spacing problem from the previous discussion.

**Step 6 — Grid the z-score.** Short the spread at positive z, long at negative z, take profit
one level back toward zero.

```
z spacing        : 0.5σ
max levels       : 4 per side   (±2.0σ)
take profit      : 0.5σ  (one level toward zero)
basket stop      : 8.0 z-units aggregate  → fires near |z| ≈ 3.2
time stop        : ~2 × half-life
kill switch      : rolling ADF stops rejecting, or β drifts materially
```

**A note on basket-stop sizing, because it is easy to get wrong.** With L levels at spacing s,
aggregate adverse excursion at z is roughly `L·|z| − s·L(L+1)/2`. With L=6, s=0.5 that is
already −7.5 at z = −3 — so a basket stop of 4.0 would fire on a **completely normal**
z-excursion and churn the account. That is the same pathology as the micro-grid: a stop that
cannot distinguish ordinary oscillation from breakdown. I hit this bug during development;
the defaults above are set so the stop fires on genuine breakdown (|z| ≈ 3.2), not on noise.

---

## 4. Why this is structurally better

| | Grid on EUR/USD | Grid on cointegrated spread |
|---|---|---|
| Mean reversion is… | **assumed**, and contested | **estimated and testable** (ADF p-value) |
| Reversion speed | unknown | **half-life in bars** |
| Spacing units | pips (arbitrary) | **σ of the spread** (regime-invariant) |
| Exit criterion | hope | **z → 0**, from the same model as the entry |
| Time stop | no basis for one | **~2 × half-life** |
| Regime-break signal | the loss tells you | **rolling ADF / β drift — fires first** |
| Macro shock exposure | full | **largely cancels** across legs |

The two rows that matter most:

**Coherent exits.** The entry and exit come from *one* model. Recall the incoherence of the
trend-filtered grid: trend-following entries with mean-reversion exits, two schools of thought
fighting each other. Here, "enter at z = −2, exit at z = −1.5, abandon if not reverted in
2× half-life, stand down if ADF stops rejecting" is a single consistent statement.

**An early-warning signal that the loss does not have to supply.** On EUR/USD outright you
learn the regime changed when money is gone. On a spread, **cointegration breakdown is a
testable statistical event** — rolling ADF ceasing to reject, or half-life widening — and it
can fire *before* the P&L does. That is the single biggest upgrade in the whole design.

And the macro-neutrality directly addresses the blow-up trigger you originally named. A Fed
surprise that moves the dollar moves *both* legs, so it largely cancels. Your grid stops being
exposed to the thing most likely to kill it.

---

## 5. Validation: the lab works

Self-test on synthetic pairs where the answer is known in advance:

| | True cointegrated pair (β=1.30, HL=300) | Two independent random walks |
|---|---|---|
| β recovered | **1.278** ✓ | 0.051 |
| ADF p-value | **0.0000 → COINTEGRATED** ✓ | 0.331 → not cointegrated ✓ |
| Half-life recovered | **299 bars** (true: 300) ✓ | 12,051 (no reversion) ✓ |
| Stable windows | **10/10** ✓ | 4/10 → UNSTABLE ✓ |
| Win rate | 91.0% | **88.3%** |
| Real ret/MAE | **53.97** | **15.87 (positive!)** |
| Shuffled ret/MAE | 3.09 | 20.87 |
| Surrogate p | **0.00 → SIGNAL** ✓ | **1.00 → NO EDGE** ✓ |

**Look hard at the right-hand column.** Two *independent random walks* — guaranteed no
relationship whatsoever — produced an **88.3% win rate and a positive return/MAE of 15.87**.
A naive backtest would call that a winning strategy. Four of ten windows even showed spurious
"cointegration."

Only the **surrogate test** caught it: p = 1.00, because shuffled data did *better* than real.
This is why that test is in the harness and why I will not evaluate any spread strategy
without it. A pretty equity curve and a high win rate are the normal appearance of nothing.

---

## 6. The real risks — read this part twice

**1. Cointegration in FX is unstable, and this is the big one.** The canonical case is
**Brexit**: the EUR/GBP relationship regime-shifted permanently in 2016. Any β fitted before
June 2016 was wrong after it, and a grid leaning on the old level would have scaled into a
loss all the way down. Currency cointegration reflects policy and political alignment, and
those change. **Mitigation:** rolling re-estimation, hard kill on ADF failure, and position
sizing that assumes the relationship *will* break at some point.

**2. Costs double.** Two legs = two spreads + two commissions. And GBP/USD is typically wider
than EUR/USD. The lab models them separately for that reason. This is precisely why the β = 1
check comes first — if you can trade EUR/GBP in one leg, do.

**3. Half-life may be long.** If reversion takes days or weeks, capital is tied up and this is
not a "harvesting" bot in the sense you originally meant — it is a slow relative-value
strategy with a handful of positions. That may be fine, but set expectations from the measured
half-life, not from a target trade count.

**4. Correlation ≠ cointegration.** Two series can be 95% correlated and still drift apart
forever. Correlation is about co-movement of *returns*; cointegration is about *levels* being
tethered. Only the second one justifies a grid. Do not substitute one for the other.

**5. Carry no longer cancels.** You now hold swap on both legs, and with EUR at 2.50% and GBP
at a different policy rate, the net financing may be positive or negative and will drift. Model
it explicitly.

**6. ADF has weak power on short samples.** The test needs the sample to span **many**
half-lives. A 2000-bar half-life inside a 12,000-bar window is only 6 cycles, and ADF will
fail to reject even when cointegration is real — I hit exactly this during development. So a
"no" can mean *"not enough cycles observed,"* not *"no relationship."* Judge sample length in
half-lives, not in bars.

---

## 7. Next step

```bash
python3 spread_grid_lab.py --self-test              # confirm it still passes
python3 spread_grid_lab.py --csv-a eurusd_m1.csv --csv-b gbpusd_m1.csv
```

The report runs in strict order and **stops being meaningful if an early step fails**:
β / β=1 check → ADF → half-life → spacing-vs-cost → stability across 10 windows → surrogate
test.

**What I need from you:** EUR/USD and GBP/USD minute bars covering the same period, ideally
10+ years, each with a `close` column and — important — a `timestamp` column. The script aligns
on timestamp; without it, misaligned bars corrupt the hedge ratio silently and everything
downstream is garbage.

**Realistic expectations before we run it.** I expect β ≈ 1, which points to trading EUR/GBP
directly in one leg. I expect cointegration to hold in some sub-periods and fail in others,
with Brexit as a visible break. Whether the surrogate test clears p < 0.05 net of two-leg
costs, I genuinely do not know — and that is the honest reason to run it rather than to
theorise further.
