# Micro-Harvest (1–2 pip) Grid — Quantitative Verdict

Answering the two questions asked, with numbers from `grid_diagnostic.py`.
Run date 18 September 2026. Not financial advice.

---

## 0. Summary

Your broker edge is **real and worth having**: $0.02 per 0.01 lot is genuinely cheap.
But it is worth **0.2 pips per side**, and you have proposed spending it on a change that
costs far more than it saves.

Both of your questions turn out to have the same answer, and it is not a parameter value:

- **Q1 (basket SL for a micro-target): no value works.** A basket stop functions by
  separating *normal oscillation* from *macro displacement*. At 1–2 pip spacing those two
  things are the same scale, so the window you are asking me to find is empty. Proof in §4.
- **Q2 (ER gate / ATR spacing at 1–2 pips): they stop working, for measurable reasons.**
  ER loses discriminating power at micro scale (it is structurally low and always passes the
  gate), and ATR-scaled spacing at a 1–2 pip target resolves to roughly one M1 bar — i.e.
  within-bar noise, which is the market maker's revenue and not available to a taker. §5.

And one finding I did not anticipate, which I think settles it: **the 98% win rate and the
basket stop are mutually exclusive.** You can have one or the other, never both. §3.3.

---

## 1. Your cost edge, quantified

```
0.01 lot                      ->  $0.10 per pip
$0.02 commission per 0.01 lot ->  0.02 / 0.10  =  0.20 pips per side
                              ->  0.40 pips round turn
```

You already spotted this — it is why you quoted "1.2 to 2.2 pips" for a 10–20 cent target.
So the arithmetic is agreed. The disagreement is only over whether 0.2 pips is negligible.
It is not, because **cost is a ratio to your target, and you shrank the target tenfold.**

Harness output, your stated terms (commission 0.20/side, avg spread 0.10, slippage 0.05/fill
→ **0.60 pips round trip**):

| Target | Gross | Cost as % of gross | Net | Verdict |
|---|---|---|---|---|
| **1.0 pip** | $0.10 | **60.0%** | 0.40p | FATAL |
| **2.0 pip** | $0.20 | **30.0%** | 1.40p | MARGINAL |
| 5.0 pip | $0.50 | 12.0% | 4.40p | OK |
| 10.0 pip | $1.00 | 6.0% | 9.40p | OK |
| 20.0 pip | $2.00 | **3.0%** | 19.40p | OK |

**Maximally generous case — literally zero spread, zero slippage, commission only:**

| Target | Cost as % of gross |
|---|---|
| 1.0 pip | **40.0%** |
| 2.0 pip | **20.0%** |
| 20.0 pip | **2.0%** |

Even granting a perfect fill at a perfect zero spread every single time, commission alone
takes 20–40% of gross at your target. At the 20-pip spacing you originally proposed it took
2%. **You had the cost structure right the first time and the change makes it 10–20× worse.**

A note on "0 spread": advertised raw spreads are quoted as *"from 0.0"* — that is the
observed minimum at peak liquidity, not a continuous guarantee. The average is higher, and it
widens at rollover, around releases, and in thin hours. At a 1-pip target a 0.3-pip spread
excursion is 30% of the trade. Spread variance you could ignore at 20 pips becomes a
first-order term at 1 pip.

---

## 2. Your thesis is correct — and that is the problem

> *"at this microscopic scale, standard market noise and random walk oscillations will hit
> the take-profit almost every single time before any macro displacement occurs."*

**This is true. The harness confirms it precisely.** For a driftless walk,
P(hit +a before −b) = b/(a+b):

| Target | Stop | P(win) | Gross EV | Net EV | One loss = |
|---|---|---|---|---|---|
| 1.0 pip | 60 pips | **98.36%** | **−0.00p** | −0.60p | 60 wins |
| 2.0 pip | 60 pips | **96.77%** | **0.00p** | −0.60p | 30 wins |
| 20.0 pip | 60 pips | 75.00% | 0.00p | −0.60p | 3 wins |

98.36% — essentially what you predicted. And the gross expected value is **exactly zero.**

This is the optional stopping theorem, and it is the whole issue: **a high win rate at a tight
target is not evidence of an edge. It is the arithmetic signature of a zero-EV bet.** The
98.36% and the rare 60-pip loss are two descriptions of the same number. Tightening the
target raises the win rate and enlarges the loss in exact proportion, forever. You cannot get
expectancy out of barrier placement on a martingale — only out of the price process being
genuinely mean-reverting, which is the contested question (and is what §6 tests).

Note also the last column: at a 1-pip target you need **60 consecutive wins to repay one
loss**. Your run of 60 wins feels like a working system for days before the 61st trade.

---

## 3. Tighter spacing makes the tail worse, not better

### 3.1 The formula

```
loss(displacement D, spacing s)  =  s · N(N+1)/2   where N = D/s
                                 ≈  D² / (2s)
```

Loss is **inversely** proportional to spacing. Halving the spacing doubles the loss for the
same adverse move while halving the income per round trip. Income per unit of tail risk
therefore scales as **s²** — tightening 10× degrades it by **100×**.

### 3.2 A 60-pip day — not a crisis, an ordinary Tuesday

| Spacing | Levels filled | Open loss | Loss @0.01/level | Win per trip | **Wins needed to repay** |
|---|---|---|---|---|---|
| **1 pip** | 60 | 1,830p | **$183.00** | $0.10 | **1,830** |
| **2 pip** | 30 | 930p | $93.00 | $0.20 | **465** |
| 5 pip | 12 | 390p | $39.00 | $0.50 | 78 |
| 10 pip | 6 | 210p | $21.00 | $1.00 | 21 |
| **20 pip** | 3 | 120p | $12.00 | $2.00 | **6** |

Read the last column. At 20-pip spacing an ordinary day costs you **6 winning trades**. At
1-pip spacing the same ordinary day costs **1,830 winning trades**. EUR/USD does 50–70 pips
most days. You would be attempting to out-earn a routine daily range with 10-cent increments.

### 3.3 The finding that settles it: the win rate and the stop are incompatible

This came out of the simulation, and I had not predicted the magnitude. Same 400k-bar price
path, basket stop enabled at each spacing:

| Spacing | Round trips | **Win rate** | Net result | Basket stops fired |
|---|---|---|---|---|
| **1 pip** | 58,815 | **51.8%** | −115,313p | 4,725 |
| **2 pip** | 43,217 | **61.1%** | −88,817p | 2,800 |
| 20 pip | 1,230 | 71.7% | −4,325p | 58 |

Two things to see.

**First: the 1-pip grid lost 26× more than the 20-pip grid on the identical price path.** Not
26% — twenty-six times. That is the `D²/2s` term made visible.

**Second, and more important: the win rate at 1-pip spacing is 51.8%, not 98%.** Your 98%
figure is real, but it only exists in a world with *no basket stop*. Once you add the stop —
which you agreed is non-negotiable, and which is the one thing standing between you and ruin —
the basket closes at a loss thousands of times, and the win rate collapses toward a coin flip.

**So the two pillars of the design are mutually exclusive.** The micro-target's high win rate
is purchased by never cutting losses. The basket stop works by cutting losses. Install both
and the win rate evaporates; install only the win rate and you have an unbounded tail. There
is no configuration that keeps both, and no parameter tuning changes that, because it is the
same trade-off viewed from two ends.

---

## 4. Q1 answered: why no basket SL parameterization exists

You asked for a basket stop that "doesn't get triggered by normal volatility, but still
protects from quadratic tail risk." That requires two thresholds to exist with a gap:

```
    SL  >  worst basket excursion from NORMAL oscillation     (else it fires constantly)
    SL  <  loss you can repay from accumulated income          (else one hit erases months)
```

Evaluate both bounds at each spacing, taking "normal" as a 60-pip day and income at
$0.10/pip per 0.01 lot:

| Spacing | Lower bound (survive 60p) | Income per 1,000 trips | Gap exists? |
|---|---|---|---|
| **1 pip** | **$183** | $100 | **NO — inverted** |
| **2 pip** | $93 | $200 | barely, ~2:1 |
| 10 pip | $21 | $1,000 | yes, ~48:1 |
| **20 pip** | **$12** | $2,000 | **yes, ~167:1** |

**At 1-pip spacing the window is empty — the bounds cross.** The stop you need in order to
survive an ordinary day is larger than the income from a thousand trades. There is no number
to give you.

The underlying reason is worth stating plainly: **a basket stop works by distinguishing
"normal oscillation" from "macro displacement." At 20-pip spacing those live at different
scales, so the distinction is meaningful. At 1-pip spacing, normal intraday noise IS a
60-level displacement.** The two regimes you want to tell apart have become the same
phenomenon, so no threshold separates them. That is why the answer is structural and not a
parameter.

---

## 5. Q2 answered: why ER and ATR stop working at micro scale

**Efficiency Ratio loses its discriminating power.** For a random walk sampled over N steps,
net change grows as √N·σ while path length grows as N·σ·E|z|. So:

```
ER  ~  √N / N  =  1/√N
```

ER falls mechanically as you sample finer. The census on M1 data confirms it: median ER
0.194, with **70.6% of bars below the 0.30 gate.** At micro scale the ratio collapses further
and the gate approves essentially everything — it becomes a constant that says "GO," which is
not a filter. The ER gate I recommended works precisely *because* it operates at a horizon
where displacement and path length are comparable. Push it below that and it stops measuring
anything.

**ATR-scaled spacing degenerates.** ATR(20) on EUR/USD M1 bars currently runs on the order of
1–2 pips (consistent with 50–70 pip daily ranges). So `spacing = c × ATR` with a 1–2 pip
target implies **c ≈ 1 — grid spacing equal to a single bar's range.** At that point you are
not harvesting oscillation *between* swings; you are harvesting noise *within* a bar.

That distinction matters commercially, not just conceptually. Sub-2-pip oscillation on
EUR/USD is bid-ask bounce and quote flicker. Capturing it requires **resting limit orders and
earning the spread** — that is market-making revenue. As a retail taker you *pay* that
spread. And if you do rest limits, you inherit the market maker's actual problem: adverse
selection. Your limits fill preferentially when informed flow runs through them, and informed
flow is most damaging exactly when aggregate informedness is low — i.e. the quiet conditions
where this looks safest ([arXiv 2606.05882](https://arxiv.org/abs/2606.05882)). You would be
providing liquidity at retail latency against colocated professionals.

**Operational flag.** A 1–2 pip target implies hundreds to thousands of fills per day. That
profile is what brokers classify as scalping or toxic flow; zero-spread accounts commonly
apply last-look execution, and such accounts get restricted or closed. Before modelling
anything further, confirm in writing what your broker permits regarding minimum holding time,
order-to-trade ratio, and latency arbitrage clauses. A strategy that only works at 1 pip and
is contractually prohibited is not a strategy.

---

## 6. What I recommend, and what I will build

**Keep the instinct, move the scale.** You want frequent small captures with low cost drag —
legitimate. Your original 15–25 pip grid already had the right cost structure (3% of gross,
6 wins to repay an ordinary day). The productive move is to make *that* version work, not to
shrink it.

Three paths, in order of how much I would trust them:

1. **Cointegrated spread grid (strongest).** From the earlier doc: grid the z-score of a
   stationary EUR/USD–GBP/USD residual at ~0.5σ spacing. Mean reversion becomes an *estimated
   parameter with a half-life*, cointegration breakdown is a *testable event* that fires
   before the P&L does, and the position is roughly market-neutral so ECB/Fed surprises
   largely cancel across legs. This is the version of your idea with a foundation.
2. **20-pip ER-gated grid with basket stop.** Your original design plus §5.1–5.6 of the
   critique doc. Modest, defensible, and the harness can test it honestly.
3. **Intraday time-of-day harvest.** Different mechanism, best external evidence
   (~80% of dollar carry accrues in US hours), flat overnight so zero swap exposure.

**The harness is built and validated** — `grid_diagnostic.py`. It self-tests against
processes with known answers and passes:

| Synthetic process | Correct answer | Harness output | |
|---|---|---|---|
| GBM (random walk) | no edge | p = 0.40 → NO EDGE | ✓ |
| OU (mean-reverting) | edge | p = 0.00 → SIGNAL PRESENT | ✓ |
| Trending (drift) | no edge | p = 0.70 → NO EDGE | ✓ |

So it can tell mean reversion from a random walk. Point it at your data:

```bash
python3 grid_diagnostic.py --self-test          # verify it still passes
python3 grid_diagnostic.py --csv eurusd_m1.csv --spacings 1 2 5 10 20
```

**The decisive output is Section 6, the surrogate test.** It runs your strategy on the real
path, then on the *same returns shuffled* — which destroys mean reversion while preserving the
return distribution exactly. If your grid performs the same on shuffled data, there is no
edge, only the zero-EV structure. **This is the test I would want run before funding anything,
including my own suggestions.** It is also the fairest possible arbitration between us: if
1-pip spacing shows p < 0.05 on your real data, my argument is wrong and the data says so.

**What I need from you:** EUR/USD M1 bars, ideally 10+ years with separate bid/ask. Drop a CSV
in the workspace (`close` column, or `bid`+`ask`) and I will run the full report and interpret
it. If you do not have data yet, tell me your broker/platform and I will write the fetcher.

I will build any of the three designs above. I will not hand you a tuned 1–2 pip blueprint,
because §3.3 and §4 say it cannot be made safe — and a blueprint from me would carry an
implied assurance the arithmetic does not support.
