# fxeharvest

A 5-pip limit-ladder grid harvester for EUR/USD (MetaTrader 5), plus the Python
research tooling used to design and stress-test it.

**Status:** research / demo. Not financial advice. Test on a demo account first.

---

## Layout

```
mql5/     Harvester5Pip.mq5      MT5 execution engine (the deliverable)
tools/    harvester.py           Python reference implementation + backtest + sweeps
          grid_diagnostic.py     Grid viability harness (surrogate test)
          spread_grid_lab.py     Cointegration lab (EUR/USD vs GBP/USD)
          analyze_cycles.py      Reads the EA's CSV telemetry -> RATIO, slippage
research/ *.md                   Design docs, critiques, evidence review
```

Start with [`research/harvester-blueprint.md`](research/harvester-blueprint.md) —
it explains every parameter choice in the EA and why it is what it is.

---

## The strategy

A grid of resting **limit** orders around a rolling mean, taking **5 pips** (≈$0.50
on 0.01 lot) per completed round trip, with a hard basket stop.

| Component | Setting |
|---|---|
| Take profit | 5.0 pips fixed |
| Base spacing | `clamp(2.0 × ATR20(M15), 7, 15)` — ~10 pips |
| Ladder depth | **3 levels**, progressive widening (10 / 22.5 / 37.5 pips) |
| Anchor | SMA(20), **frozen** while positions are open |
| Basket stop | `\|price − anchor\| > 6.0 × spacing` (60 pips) |
| Disaster SL | 2 × D_max (120 pips), server-side |
| Regime gate | Efficiency Ratio (20): <0.35 full, 0.35–0.50 half, >0.50 flat |
| Entry veto | RSI(14) < 25 no longs, > 75 no shorts |
| Vol veto | BB width > 1.6 × its 50-period median → flat |

Economics of that geometry:

| | |
|---|---|
| Cost ratio at 5-pip TP | **10%** of gross (limit-in / limit-out) |
| Net per winning round trip | 4.50 pips = **$0.45** |
| Aggregate loss at basket stop | 110 pips = **$11.00** |
| Round trips to repay one stop-out | **24** |

### Why spacing ≠ take-profit

Aggregate loss at adverse displacement `D` is roughly `D² / (2 × spacing)`, so loss
is *inversely* proportional to spacing. Decoupling the two lets you keep the 5-pip
target while widening spacing to shrink the tail. Spacing is floored at 7 pips to
protect the cost ratio.

### Why 3 levels

Measured marginal value of each added level (3-year backtest, only `max_levels` varying):

| Step | Income gain | Stop-loss gain |
|---|---|---|
| 1 → 2 | **+81.7%** | +70.8% |
| 2 → 3 | **+22.1%** | +20.1% |
| 3 → 4 | +3.2% | +3.9% |
| 4 → 5 | 0.0% | 0.0% |

Level 5 sits at 75 pips while the basket stop fires at 60 — **it can never fill**.
General rule, enforced by an init-time warning in the EA: *the deepest level must sit
inside ~70% of D_max, or it is decorative.*

---

## Execution design

| Purpose | Order type | Lives on | Rationale |
|---|---|---|---|
| Entry | BUY/SELL **LIMIT** | Broker server | No slippage, no latency race |
| Take profit | Attached **LIMIT** | Broker server | Fires even if the EA dies |
| Disaster backstop | Attached **SL** | Broker server | VPS-reboot / gap insurance |
| **Basket stop** | **MARKET** close-all | **EA process** | No broker offers aggregate stops |

A grid is inherently a passive, liquidity-providing structure — "buy if price comes
down to me" *is* a limit order. Market-on-touch would pay the spread for nothing and
turn every entry into a latency race.

Because the basket stop is client-side, **if the EA dies the basket stop does not
exist** — hence the mandatory far server-side SL on every position.

### Implementation notes

- **Levels are keyed by magic number** (`base + 100|200 + level`), not comment.
  Brokers frequently overwrite comments; magic survives.
- **Anchor is frozen on arm** and released only when flat. A live-tracking anchor makes
  level depths and TP targets drift under open positions — subtly wrong rather than
  obviously broken, so it survives casual testing.
- **State persists** via `GlobalVariable` across recompile/restart, and reconciles
  against the live book on init. If positions exist but the anchor was lost, the EA
  closes the basket rather than guessing — an unknown anchor means the basket stop
  cannot be computed.
- `OnTradeTransaction` logs **requested vs actual fill price**, so real limit slippage
  is measured rather than assumed.
- Rollover blackout ±5 min around server midnight; optional Friday flatten.

---

## CSV telemetry

With `InpCsvLog = true` the EA writes two files to `MQL5\Files`
(or `Terminal\Common\Files` if `InpCsvCommonFolder = true`):

**`Harvester_<SYMBOL>_<MAGIC>_deals.csv`** — one row per deal:

```
utc_time,cycle_id,event,side,level,req_price,fill_price,slip_pips,volume,profit,hold_secs
```

`event` is `ENTRY`, `TP_EXIT`, `SL_EXIT` or `STOP_EXIT`, classified from
`DEAL_REASON`. The `req_price` / `fill_price` / `slip_pips` columns are the point of
this file: they **measure** limit slippage instead of assuming the blueprint's 0.0.

**`Harvester_<SYMBOL>_<MAGIC>_cycles.csv`** — one row per basket cycle, carrying the
indicator snapshot taken at arm time (anchor, spacing, ATR, ER, RSI) plus the outcome
(entries, TPs, deepest level, displacement at close, max adverse excursion, P/L, reason).

Both files are opened and closed per row, so a terminal crash cannot lose buffered rows.

Two columns exist where one might be expected: `realized_from_deals` and `pl_at_close`.
On a basket stop the exit deals settle asynchronously and may arrive *after* the cycle row
is written, so both figures are logged side by side rather than silently reconciled.
On a clean close they should agree; on a stop, `pl_at_close` is the reliable one.

### Reading the telemetry

```bash
python3 tools/analyze_cycles.py --dir "C:/.../MQL5/Files"
```

Reports, in order: the **RATIO**, measured slippage versus the assumed 0.50-pip cost,
fills-per-level (does level 3 actually fill, or is it decorative?), outcome bucketed by
ER at arm time, and a month-by-month table.

The ER breakdown is worth watching: if average P/L does **not** fall as ER rises, the
gate is not earning its complexity and `InpERFull` should be widened rather than tightened.

---

## Python tooling

```bash
pip install numpy pandas statsmodels

python3 tools/harvester.py --demo --sweep          # mechanics + tuning table
python3 tools/harvester.py --csv eurusd_m15.csv    # your data

python3 tools/grid_diagnostic.py --self-test       # validate the harness
python3 tools/grid_diagnostic.py --csv eurusd_m1.csv --spacings 1 2 5 10 20

python3 tools/spread_grid_lab.py --self-test
python3 tools/spread_grid_lab.py --csv-a eurusd_m1.csv --csv-b gbpusd_m1.csv
```

Both harnesses **self-test against synthetic processes with known answers** and pass:

| Process | Correct answer | Output |
|---|---|---|
| GBM (random walk) | no edge | p = 0.40 → NO EDGE ✓ |
| OU (mean-reverting) | edge | p = 0.00 → SIGNAL ✓ |
| Trending (drift) | no edge | p = 0.70 → NO EDGE ✓ |
| Cointegrated pair (β=1.30, HL=300) | detect | β=1.278, HL=299, p=0.00 ✓ |
| Two independent random walks | reject | p = 1.00 → NO EDGE ✓ |

### The metric that matters

```
RATIO = (take-profits per stop-out) / (loss per stop-out in TP units)
        RATIO > 1.0  =>  the geometry pays for its own stop-outs
```

On zero-edge synthetic data the RATIO is **~0.35**, and it stays at 0.31–0.39 across
*all 64* geometry combinations tested. So spacing, level count and basket width control
**drawdown tolerance and fill frequency — not expectancy.** Tune them for the former.

**On real data you need RATIO > 1.0.** The gap between 0.35 and 1.0 is exactly how much
genuine mean reversion the market has to supply. Watch that number, not the equity curve.

### Why the surrogate test exists

`grid_diagnostic.py` and `spread_grid_lab.py` both run the strategy on real data and then
on the **same returns shuffled** — which destroys mean reversion while preserving the
return distribution exactly. If results are the same on shuffled data, there is no edge.

This matters because in testing, **two independent random walks produced an 88.3% win rate
and a positive return/MAE**. A naive backtest would have called that a winning strategy.
Only the surrogate test caught it. A high win rate and a smooth equity curve are the normal
appearance of nothing.

---

## Before going live

1. Compile in MetaEditor; fix any broker-specific issues.
2. Strategy Tester on **"Every tick based on real ticks"** — the basket stop is tick-level,
   so M1-OHLC modelling hides its real behaviour.
3. Confirm the basket stop **actually fires** in the backtest. If it never fires, it is
   mis-parameterised, not safe.
4. Verify your broker's rules on minimum holding time and order-to-trade ratio.
5. Demo for one month. Check limit fill rates per level, real spread at rollover, and
   measured slippage from the `OnTradeTransaction` log.
6. Live at 0.01 lot. The geometry is sized so one stop-out is ~$11.

---

## Background reading

- [`harvester-blueprint.md`](research/harvester-blueprint.md) — full execution spec
- [`grid-bot-critique-and-redesign.md`](research/grid-bot-critique-and-redesign.md) — why trend-filtered grids fail; the ER gate
- [`micro-harvest-verdict.md`](research/micro-harvest-verdict.md) — why 1–2 pip targets don't work (cost ratio, win-rate/stop incompatibility)
- [`cointegrated-spread-grid-explained.md`](research/cointegrated-spread-grid-explained.md) — the stronger alternative: grid a stationary spread ([বাংলা](research/cointegrated-spread-grid-bangla.md))
- [`fx-harvesting-strategy-xauusd-eurusd.md`](research/fx-harvesting-strategy-xauusd-eurusd.md) — why gold cannot be carry-harvested
- [`trading-bot-strategy-evidence-review.md`](research/trading-bot-strategy-evidence-review.md) — published evidence on bot strategies

---

## Licence

Unlicensed / private research. Use at your own risk.
