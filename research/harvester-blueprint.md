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
