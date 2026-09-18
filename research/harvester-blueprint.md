# 5-Pip Harvester — Execution Blueprint

Reference implementation: `harvester.py` (runs, backtests, sweeps).
Built 18 September 2026. Your four questions answered in order.

**Why 5 pips changes the engineering:** at a 5-pip target with limit-in/limit-out
execution, your all-in cost is **0.50 pips = 10% of gross**. At 1 pip it was 40–60%.
5 pips is the first level where the cost structure supports the design, so the mechanics
below are built to protect that 10% rather than fight it.

---

## 0. Parameter set at a glance

```
TAKE PROFIT        5.0 pips fixed                    ($0.50 @ 0.01 lot)  <- your target
BASE SPACING       2.0 x ATR20(M15), clamped [7, 15] (~10 pips typical)
LEVEL LAYOUT       progressive: gaps  s, 1.25s, 1.50s, 1.75s
                   depths @ s=10:     10.0 / 22.5 / 37.5 / 55.0
MAX LEVELS         4 per side
ANCHOR             SMA(20) at arming time, then FROZEN
BASKET STOP        |price - anchor| > 6.0 x s   (60 pips @ s=10)
                   OR unrealized < -6% of equity
DISASTER SL        per-position, 2.0 x D_max (120 pips) -- server-side
REGIME GATE        ER(20):  <0.35 full size | 0.35-0.50 half | >0.50 flat
ENTRY VETO         RSI(14): no longs <25, no shorts >75
VOL VETO           BB width > 1.6 x its 50-period median -> flat
PRE-PLACED         3 levels per side resting on server
COOLDOWN           96 M15 bars (1 day) after a basket stop
SIZE               0.01 lot per level
```

Economics of that geometry, from `harvester.py`:

| | |
|---|---|
| Cost ratio at 5-pip TP | **10.0%** of gross |
| Net per winning round trip | **4.50 pips = $0.450** |
| Aggregate loss at basket stop | **115 pips = $11.50** |
| **Round trips to repay one stop-out** | **26** |

---

## 1. Execution style — resting LIMIT ladder, not market-on-touch

**Use limit orders for entries. This is not a close call.**

**Why limits win here:**

1. **A grid is inherently a passive structure.** Its entry logic is literally *"buy if price
   comes down to me."* That **is** a limit order. Using market-on-touch converts a
   liquidity-providing strategy into a liquidity-taking one and pays the spread for nothing.
2. **Zero entry slippage.** At a 5-pip target, 0.1 pip of slippage is 2% of gross. Over
   thousands of fills that is the difference between a 10% and a 14% cost ratio.
3. **Latency independence.** A resting limit lives on the **broker's server**. Your retail
   50–200 ms round trip stops mattering. Market-on-touch makes every entry a latency race you
   cannot win.
4. **Adverse selection is already priced in.** Yes, resting limits fill preferentially when
   price is about to continue. But the grid *already* buys into falling markets by design —
   that is its entry rule. Limits don't add adverse selection here; you get the fill-quality
   benefit without a new cost. (This argument would not hold for a momentum strategy.)

**The order-type map — each layer has a different job:**

| Purpose | Order type | Where it lives | Why |
|---|---|---|---|
| Entry | BUY/SELL **LIMIT** | Server | No slippage, no latency dependence |
| Take profit | Attached **LIMIT** (TP) | Server | Fires even if your bot is dead |
| Disaster backstop | Attached **SL**, 2× D_max | Server | Catastrophe insurance only |
| **Basket stop** | **MARKET**, close-all | **Your code** | No broker offers aggregate stops |

**The critical operational point.** No retail broker natively supports *"close everything when
aggregate unrealized < X."* The basket stop must be computed **client-side**, every tick, by
your own loop. Which means: **if your bot dies, your basket stop does not exist.** That is
exactly why every position also carries a far server-side SL at 2× D_max. It should never
fire in normal operation — it exists for the case where your VPS reboots mid-trend.

**A stop must never be a limit order.** A stop-limit can fail to fill in a fast move, which
defeats its entire purpose. Basket exit = market.

**Pre-place 3 levels, not the whole ladder.** Full pre-placement means a disconnect during a
trend fills every level with no basket stop watching. Keeping 3 levels resting and refreshing
as price moves bounds that exposure while keeping the server-side latency benefit.

---

## 2. Grid spacing — decouple it from the take-profit

**This is the highest-leverage design decision in the whole blueprint.**

Most retail grids set `spacing = TP`. That is an unforced constraint. Your 50-cent target fixes
**TP = 5 pips**. It says nothing about spacing. And since:

```
aggregate loss at displacement D  ≈  D² / (2 · spacing)
```

loss is **inversely proportional to spacing**. Wider spacing = smaller tail, *for the same
5-pip target*. You keep your 50 cents per harvest and shrink the downside. Free.

**So: spacing ≥ TP, and preferably 2× TP.**

```
base_spacing = clamp( 2.0 × ATR20(M15),  7.0,  15.0 )     # ~10 pips typical
```

- The **floor of 7** protects the cost ratio — never let spacing collapse toward the TP.
- The **cap of 15** stops the ladder becoming so wide it never fills.
- **ATR-scaled** so it self-adjusts between the 50–70 and 70–90 pip range regimes.

**Progressive widening.** Gaps grow as you go deeper: `gap_k = s · (1 + 0.25(k−1))`.

Rationale: the deeper you are, the more wrong you are, so stop adding at the same rate.

| Level | Gap | Depth | TP fires at | Loss if D = 60 |
|---|---|---|---|---|
| 1 | 10.0p | 10.0p | 5.0p | 50.0p |
| 2 | 12.5p | 22.5p | 17.5p | 37.5p |
| 3 | 15.0p | 37.5p | 32.5p | 22.5p |
| 4 | 17.5p | 55.0p | 50.0p | 5.0p |
| | | | **total** | **115.0p = $11.50** |

Compare at the **same** 60-pip stop distance: uniform 10-pip spacing fills 6 levels for
**150 pips**; progressive fills 4 for **115 pips**. ~23% less tail, same target, same stop.

Note the TP placement: a level filled at depth 10 exits at depth **5** — *between* the anchor
and level 1, not at the next level up. That is the decoupling in action.

---

## 3. Indicators — four of them, each doing exactly one job

The failure mode to avoid is redundant indicators that all measure the same thing and create
false confidence. Each of these has a distinct, non-overlapping role.

### 3.1 Efficiency Ratio (20) — the regime gate

**Job: decide whether to run the grid at all.** Directionless, so it can never produce a
one-sided grid.

```
ER < 0.35   ->  full size
0.35-0.50   ->  half size, same geometry
ER > 0.50   ->  flat; cancel all resting orders; do not re-arm
```

ER = |net change| / Σ|bar-to-bar change|. It measures **path length vs displacement**, which
is precisely what determines grid P&L. At the 5-pip/M15 scale this works properly — ER only
loses discriminating power at sub-2-pip scales where it collapses toward 1/√N.

### 3.2 SMA(20) — the anchor

**Job: where to centre the ladder.** Do not anchor on "price when flat" — that is an arbitrary
point. Anchor on the SMA (equivalently, the Bollinger middle band), which is a rolling estimate
of fair value. Your ladder then straddles something statistically meaningful.

**Freeze it on first fill.** See §5.1 — this is the bug that will cost you a weekend.

### 3.3 ATR(20) — the scale

**Job: set spacing and stop distance.** Both in ATR units, so the whole geometry breathes with
volatility. Nothing else uses ATR.

### 3.4 RSI(14) — the entry veto (not a trigger)

**Job: refuse to add into an impulse.**

```
RSI < 25  ->  place no NEW long levels  (existing TPs stay live)
RSI > 75  ->  place no NEW short levels
```

**Do not use RSI as an entry signal.** The grid level *is* the entry signal. RSI's only value
here is as a one-way brake: when price is in a violent directional move, stop deepening the
ladder. Using RSI as a trigger would duplicate what the level structure already does and add a
lagging parameter for nothing.

### 3.5 Bollinger width — the volatility-expansion veto

```
BB_width(20) > 1.6 × median(BB_width, 50)  ->  flat
```

Squeeze is grid-friendly; expansion is grid-hostile. This catches regime shifts that ER, being
a ratio, can miss — a market can move violently *and* choppily, which ER rates as fine and
which will still run your ladder over.

**Why not Bollinger Bands as the entry trigger?** Because you already use its middle band as
the anchor and its width as a veto. Using the ±2σ bands as entries too would make one indicator
do three jobs and hide correlated failure.

---

## 4. Basket stop — defined on displacement, not on unrealized P&L

**Define it on distance from anchor.** `|price − anchor| > D_max`. This is directly
interpretable, easy to verify, and behaves consistently as levels fill.

```
D_max = 6.0 × base_spacing        # 60 pips at s = 10
```

**Why 6.0×:** the last level sits at 5.5× (55 pips). So the stop fires **just past full ladder
deployment** — the trigger condition is exactly *"my ladder is fully committed and price is
still going."* That is the correct moment to be out, and it is derived from the geometry rather
than picked.

**The economics at that trigger:**

| | |
|---|---|
| Aggregate loss | **115 pips = $11.50** @ 0.01 lot/level |
| Net per win | 4.50 pips = $0.450 |
| **Round trips to repay** | **26** |

26 is a workable number. A busy grid day produces 3–6 take-profits, so a stop-out costs roughly
a week of harvesting. (At 1-pip spacing the same figure was 1,830.)

**Three layers, in order:**

1. **Primary** — `|price − anchor| > 6.0 × s` → market close-all. Client-side.
2. **Secondary** — aggregate unrealized < **−6% of equity** → market close-all. Catches the
   case where sizing drifted or multiple instruments are running.
3. **Disaster** — per-position server-side SL at **2 × D_max (120 pips)**. Never fires in
   normal operation. Exists purely for bot death / VPS reboot / weekend gap.

**Cooldown: 96 M15 bars (one day).** After a stop-out the anchor is stale and the regime is by
definition trending. Re-arming immediately re-enters the move that just stopped you out. On
re-arm, recompute anchor and spacing from scratch.

**Sanity check:** if your basket stop never fires in a multi-year backtest, it is
mis-parameterised, not safe. Mine fires 387 times in 3 years — that is the stop working.

---

## 5. Implementation gotchas — the ones that actually bite

### 5.1 FREEZE THE ANCHOR (most important)

Compute the anchor from the SMA **once, at arming time**. Then hold it constant until the
basket is fully flat.

If the anchor tracks a live moving average while positions are open, your level depths and TP
targets **drift underneath you** every bar. Positions get orphaned, TPs move away from fills,
and the loss accounting stops matching reality. It is subtly wrong rather than obviously broken,
so it survives casual testing. State machine:

```
FLAT      : anchor = SMA(20) now; spacing = f(ATR); check gates; arm ladder
ACTIVE    : anchor FROZEN. fill levels, run TPs, monitor basket
COOLDOWN  : nothing resting on the server
```

### 5.2 Basket stop lives in your process

Recompute aggregate unrealized **every tick**, not every bar. Bar-close checking on M15 means
up to 15 minutes of unmonitored exposure. And because it is client-side, the server-side
disaster SL in §4 is mandatory, not optional.

### 5.3 Rollover

Spreads widen dramatically at broker rollover (00:00 server time). A resting limit can fill at
a terrible effective price. **Cancel all resting orders 5 minutes either side of rollover.**
Existing TPs can stay.

### 5.4 Order-to-trade ratio

Refresh pending orders when the *level set* changes, not on every tick. Excessive
order modification trips broker throttles and gets accounts flagged.

### 5.5 Weekend gap

Either flatten before Friday close, or accept that a Monday gap can jump straight past the
disaster SL. Explicit choice — don't leave it implicit.

### 5.6 Server time vs DST

ATR/SMA windows and rollover blackouts must use **broker server time**, which usually shifts
with DST independently of your local timezone.

---

## 6. Tuning data from the sweep

`harvester.py --demo --sweep` and the break-even table. The metric that matters:

```
RATIO  =  (take-profits per stop-out)  /  (loss per stop-out, in TP units)
          ratio > 1.0  =>  the geometry pays for its own stop-outs
```

Across **all 64 geometry combinations** (atr_mult 1.5–3.0 × levels 2–5 × basket 4–10), on
synthetic random-walk data:

| | Best | Worst |
|---|---|---|
| RATIO | **0.39** | 0.31 |

Two things this tells you, both useful for tuning:

**1. Widening the basket stop is an illusory knob.** Going from basket 6.0 to 10.0 raised
take-profits-per-stop from 9.3 to 24.9 — a 2.7× improvement that looks like progress. But loss
per stop-out rose from 25.2 to 67.3 TP-units, in near-exact proportion. **The ratio stayed
flat.** Same for levels and spacing. So do not spend time tuning these hoping the ratio moves;
choose them for drawdown tolerance instead, which is what they actually control.

**2. You have a calibration target.** On a zero-edge process the ratio is ~0.35. **On your real
EUR/USD data you need > 1.0.** The gap between 0.35 and 1.0 is precisely the amount of genuine
mean reversion the market must supply. That single number tells you whether the harvest works,
and it is the one output to watch when you run it on real bars.

Useful reference numbers from the 3-year synthetic run (mechanics validation):

| | |
|---|---|
| Take-profits | 2,860 (~3.8 per active day) |
| Basket stops | 387 |
| Max concurrent positions | 4 |
| Win rate (TP vs stop) | 88.1% |
| Bars active | 47.6% |
| Avg basket stop | −102 pips (23 winning trips) |

---

## 7. Build order

1. **`harvester.py --demo`** — confirm the mechanics and read the geometry table.
2. **Swap in real M15 EUR/USD bars** — `--csv`. Watch the **RATIO**, not the equity curve.
3. **Port the state machine** (§5.1) to your platform. Keep entry/TP/SL server-side and the
   basket monitor client-side.
4. **Paper trade one month** on live spreads. Verify three things specifically: limit fill
   rates at each level, actual spread at rollover, and that the basket stop fires when you
   expect.
5. **Live at 0.01 lot.** The geometry is already sized so one stop-out is $11.50.

---

## 7b. Field notes from the first real-tick backtest

Pepperstone UK demo, EUR/USD M15, 2026.08.27–09.02, 100% real ticks (311,511 ticks,
384 bars), £500 @ 1:30. Short sample, but it settled several things.

**Geometry verified against the broker's own order records.** Reverse-engineering
anchor and spacing from the placed order prices gives spacing **7.04 pips** (the
`InpSpacingMinPips` floor, so ATR20(M15) was under 3.5 pips that week) and anchor
**1.16519**. Every level, take-profit and stop matched spec to **under 0.5 pip**:

| | Broker | Spec | Diff |
|---|---|---|---|
| buy L1 | 1.16449 | 1.16449 | 0.00p |
| buy L2 | 1.16361 | 1.16361 | 0.00p |
| sell L1 | 1.16589 | 1.16590 | 0.08p |
| sell L2 | 1.16676 | 1.16678 | 0.18p |
| buy L1 TP | 1.16499 | 1.16499 | 0.00p |
| buy L1 SL | 1.15609 | 1.15604 | 0.48p |

**Cost model confirmed.** The single completed trade: gross £0.37, commission £0.04,
net £0.33 — a **10.8% cost ratio** against the 10.0% predicted in §0. The cost
arithmetic in this document can be trusted.

**One bug, and it was severe.** 1,053 pending orders placed, **1 filled — a 0.095%
fill rate.** Cause: the "book emptied → re-anchor" branch keyed on
`state==ACTIVE && positions==0`, which is *also* true in the instant after arming,
before anything has been touched. The EA withdrew its own ladder on the next tick,
re-armed on the next bar, and repeated. A resting limit cannot fill if it is
cancelled milliseconds after placement. Fixed by gating that branch on
`entries_this_cycle > 0`, plus a stale-anchor rule: re-anchor only when the SMA has
drifted more than one spacing from the frozen anchor.

**Lesson worth generalising:** the failure was invisible in aggregate P&L (+£0.33,
100% win rate, profit factor 17.5 — superficially fine). It was only visible in the
**order-to-fill ratio**. Watch that number from the first run.

**Simulator realism gap.** `harvester.py` fills a level the moment price is beyond
it; MT5 requires the order to be *resting* when price arrives. The Python model is
therefore optimistic on trade frequency — treat its fill counts as an upper bound,
not a forecast.

**Also observed:** the one fill took **6h10m** to capture 5 pips, and zero basket
stops fired in the week. Both are single-sample facts, not evidence of anything.

---

## 7c. Field notes — v2, after the self-cancellation fix

Same broker, same instrument, same week, same inputs (EUR/USD M15, 2026.08.27–09.02,
384 bars, 100% real ticks, £500 @ 1:30). Only the section-4 gating changed.

**The fix worked, and the size of the effect is the whole story.**

| | v1 | v2 |
|---|---|---|
| pendings placed | 1,053 | 88 |
| pendings filled | 1 | 14 |
| fill rate | 0.095% | **15.9%** |
| net | +£0.33 | +£5.00 |
| profit factor | 17.5 | 18.86 |

A **168× improvement in order-to-fill ratio.** Note also that v2 placed *fewer*
orders (88 vs 1,053) — v1's order count was almost entirely churn, the same ladder
being re-posted after cancelling itself.

**Cost model confirmed a third time.** Commission £0.56 against gross £5.54 = a
**10.1% cost ratio**, versus 10.0% predicted in §0. Three independent measurements
now (10.8%, 10.1%, 10.0% modelled). The cost arithmetic is settled; stop re-deriving it.

**Geometry still exact at non-floor spacing.** v1 only ever ran at the 7.0-pip floor.
v2 saw ATR-driven spacing up to **11.44 pips**, and the geometry held: order 21's stop
at 1.18101 is exactly 2 × D_max (68.6 pips) from its anchor, per §4.

**The headline numbers are meaningless, and it matters that you know why.**
100% win rate. Profit factor 18.86. Sharpe 7.74. LR Correlation 1.00. Max equity
drawdown 0.33%. This is not a good result — it is **what every grid looks like
immediately before its first stop-out.** Zero basket stops fired. The loss
distribution has not been sampled at all, so every ratio above is computed from a
truncated sample and is upward-biased by an unknown amount.

**The number that decides viability, quantified.** From the measured £0.0791/pip
(0.01 lot) and the 7-pip geometry:

- level depths from anchor: 7.00 / 15.75 / 26.25 pips; D_max = 6 × 7 = 42 pips
- aggregate adverse excursion at the stop: 35.0 + 26.25 + 15.75 = **77.0 pips = £6.09**
- net per winning cycle: £5.00 / 14 = **£0.357**
- → **17.1 winning cycles are needed to pay for one basket stop**

The week banked £5.00 = **0.82 stop-outs' worth of profit.** At 14 cycles/week,
break-even requires basket stops to be rarer than **once every 1.22 weeks**. That is
the entire question, and one week cannot answer it.

**RATIO is still undefined.** RATIO = (TPs per stop-out) / (stop-out cost in TP units)
needs a stop-out in the denominator. Zero fired. On zero-edge synthetic data RATIO sits
at ~0.35 (stable 0.31–0.39 across all 64 geometry combinations from §6); real data must
show **> 1.0**. Until a sample contains stop-outs, the strategy is untested — not
promising, not broken. Untested.

**A slippage warning hiding in the deal list.** Deal 7 entered 1.16589 and exited
1.16509 — **8 pips captured on a 5-pip target, in 3 seconds**, +£0.59 instead of
£0.40. That is a gap through the TP in our favour. The same mechanism runs the other
way on the basket stop, which is a *market* order by design (§1). Do not read
favourable gaps as edge; read them as evidence that gaps happen.

**Hold times are wide:** min 0:00:03, max 15:54:57, mean 3:45:06. A cycle can sit
open across a session boundary, which is what `InpFlatOnFriday` and the rollover
blackout exist for.

**What the sample cannot support:** 384 bars is roughly 4.5 trading days. Any
statement about expectancy, drawdown or win rate from this run is noise. The minimum
useful sample is **2+ years of M15 real ticks**, chosen because it must contain the
regimes that produce stop-outs (trend bursts, gap opens, event days) — not because
two years is a round number.

**If fills stay sparse** at 15.9%, the only honest lever is lowering
`InpSpacingMinPips` toward 5, which immediately re-opens the cost-ratio trade-off
argued in §1 of `micro-harvest-verdict.md`. Tighter spacing buys trade frequency with
cost ratio and with a smaller D_max — meaning stops arrive sooner. There is no free
fill-rate.

---

## 7d. The 0.02-lot / 2.5-pip "aggressive scalping" question

The proposal: double lots to 0.02 so a **2.5-pip** move pays the same 50 cents,
on the reasoning that half the distance is reached twice as often.

### The lot half of the idea is economically empty

Doubling the lot doubles the profit, the loss, **and the commission**, all by the
same factor. It is pure leverage. `compare_presets.py --self-test` asserts this
and it holds to machine precision:

```
lots=0.01  RATIO=0.232231   GBP/wk=-10.129
lots=0.02  RATIO=0.232231   GBP/wk=-20.257
lots=0.04  RATIO=0.232231   GBP/wk=-40.514
RATIO spread 0.00e+00 -> PASS
```

RATIO is unchanged; only the currency scales. So the lot has **no bearing** on
whether the strategy works — it only decides how fast the answer arrives.

The reason this matters: pairing "0.02 lots" with "2.5 pips" holds the *dollar*
target at 50c and thereby **hides** the thing that did change. Commission is
~0.505 pips round-trip **regardless of lot size**, so:

| | TP | cost ratio | net per cycle |
|---|---|---|---|
| conservative | 5.0p | **10.1%** | 4.50 pips |
| aggressive | 2.5p | **20.2%** | 2.00 pips |

The broker's share of gross income **doubles**. The 50-cent figure is a
psychological anchor, not an economic one.

### The distance half is a real trade-off, and it measures worse

On a scale-invariant random walk the "twice as often" intuition is nearly
correct — halving all distances rescales time by 1/λ² and leaves TPs-per-stop
unchanged. Three things break that symmetry, all of them fixed in pips:
commission, slippage/gaps, and the fact that D_max stops being an outlier.

12 seeds × 3 years, both presets driven by the **same M1 path** (so any
difference is geometry, not luck):

| preset | TP/wk | stops/wk | win% | TPs/stop | cost (TPs) | RATIO |
|---|---|---|---|---|---|---|
| conservative M15 | 18.8 | 2.45 | 88.5 | 7.7 | 22.7 | **0.34** |
| aggressive M5 | 18.6 | **4.43** | 80.7 | 4.2 | 18.2 | **0.23** |

RATIO spread was tight in both (conservative 0.32–0.35, aggressive 0.22–0.24).

**The headline is the first two columns. Take-profits per week did not rise at
all (18.8 → 18.6), while stop-outs nearly doubled.** The core premise — more
fills — did not materialise, because each stop-out costs a 24h cooldown and at
4.43 stops/week the EA is flat ~88% of the time.

Trade frequency *can* be bought by shortening the cooldown (at 2h it rises to
~114 TP/week) — but RATIO stays pinned at 0.23 across every variant tested.
**Frequency is a free parameter; RATIO is not.** Turning the handle faster on a
zero-expectancy bet changes only the variance.

### Why D_max = 15 pips is the deepest problem

`basket_mult 6 × 2.5 = 15 pips`. §4 chose a displacement stop specifically so it
would sit *outside* normal noise and fire rarely. A 15-pip EUR/USD excursion is
a routine half-hour, not a tail event: adverse moves scale roughly as 1/D², so
15-pip moves arrive **~7.8× more often** than the 42-pip moves the conservative
geometry tolerates. The basket stop stops being insurance and becomes a
running cost — visible directly as stops/week 2.45 → 4.43.

The 6% equity stop offers no help here. At 0.02 lots on £500 it needs ~190 raw
pips of adverse movement, against a typical stop loss of ~38 pips. **It is inert
below ~0.10 lots** — the displacement stop is the only thing actually protecting
the account.

### Three code-level defects this configuration exposed

All fixed; the first would have silently invalidated the whole test.

1. **Re-anchor churn.** The stale-anchor rule fired when SMA(20) drifted more
   than *one spacing*. At 2.5 pips on M5 that is a several-times-per-hour event,
   so the EA would have withdrawn its own ladder before it could fill — a milder
   rerun of the v1 bug (§7b). Added `InpReanchorMult`; the aggressive presets use
   3.0. `InpSpacingMinPips <= 4.0` with `InpReanchorMult <= 1.0` now warns at init.
2. **Broker minimum stop distance.** A 2.5-pip TP is 25 points. Any broker with
   a non-zero `SYMBOL_TRADE_STOPS_LEVEL` rejects every such order. Harmless at
   5 pips, fatal at 2.5. `OnInit` now fails with `INIT_PARAMETERS_INCORRECT`
   rather than emitting thousands of silent order errors.
3. **Timeframe-dependent cooldown.** `InpCooldownBars=96` is 24h on M15 but 8h
   on M5 and 1.6h on M1. Comparing presets in bars would have handed the
   aggressive one a 3× shorter cooldown and made the comparison meaningless.
   Added `InpCooldownMins` (absolute, takes precedence when > 0).

Also: with `ATRMult = 1.0` and a 2.5-pip floor, spacing is **pinned at the
floor** on M5/M1 — volatility adaptation is off, so the grid cannot widen in
fast markets, exactly when widening is what saves it. `OnInit` now warns.

And a unit bug in the *analysis* code, worth recording because it produced a
plausible-looking wrong answer: `harvester.py` accounts P&L in 0.01-lot-
equivalent pips, but the basket-stop branch subtracted exit cost in raw pips.
That made RATIO appear to *degrade with lot size* (0.23 → 0.12), which is
impossible for a pure pip ratio. Fixed, and now guarded by a self-test.

### Verdict

Worth running as an experiment, since the mechanics are the stated goal — the
presets are in `mql5/presets/`. But the prediction on record is: **a higher win
rate, a smoother early equity curve, and a worse RATIO.** That combination is
the optional-stopping signature from `micro-harvest-verdict.md` §1, and 2.5 pips
is halfway back to the 1–2 pip target that document rejected. If the tester
returns 95%+ wins and zero stops over a short window, that is not a result —
it is the same "before the first stop-out" picture as v2, with the loss now
arriving roughly twice as often.

---

## 8. What I'd instrument from day one

Since the stated goal is to see the mechanics, log these per basket cycle — they are what make
the run interpretable afterwards:

- anchor, base spacing, ATR and ER **at arming time**
- fill timestamp, level index, and requested-vs-actual price for every fill (this is how you
  measure real slippage on limits instead of assuming it is zero)
- time-to-TP per level
- displacement at basket stop, and aggregate loss
- take-profits per basket cycle — this, divided by stop-out cost in TP units, is the RATIO

A per-cycle CSV of the above is worth more than any aggregate P&L figure, and it is the thing
that will tell you *why* the number came out the way it did.
