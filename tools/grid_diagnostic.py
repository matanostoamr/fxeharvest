#!/usr/bin/env python3
"""
Grid / micro-harvest diagnostic harness for EUR/USD.

PURPOSE
-------
Decide, BEFORE building an execution bot, whether a grid ("harvesting") strategy
has a real edge at a given take-profit scale -- or whether its apparent success
is the zero-expectancy barrier property of a random walk.

The decisive test is the SURROGATE TEST (section 6). We run the identical
strategy on:
    (a) the real price path, and
    (b) a shuffled version of the same returns.

Shuffling destroys autocorrelation (hence any mean reversion) while preserving
the return distribution exactly -- same volatility, same fat tails, same
everything else. Therefore:

    If the strategy performs the same on shuffled data as on real data,
    it has NO mean-reversion edge. Its results are the zero-EV structure
    plus noise, and its high win rate is arithmetic, not skill.

That single comparison is worth more than any backtest return figure.

VALIDATION
----------
Run with --self-test to verify the harness on synthetic processes where the
correct answer is known in advance:
    * GBM (random walk)  -> harness must report NO edge
    * OU (mean-reverting) -> harness must report an edge
If it gets those two right, you can trust it on real data.

USAGE
-----
    python3 grid_diagnostic.py --self-test
    python3 grid_diagnostic.py --csv eurusd_m1.csv --spacings 1 2 5 10 20

CSV format: a 'close' column (mid price), optionally 'bid'/'ask', optionally
'timestamp'. Minute bars, >= 10 years recommended.

Not financial advice. This tool is designed to falsify strategies, not bless
them. A "PASS" here is necessary, not sufficient.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# Conventions
# ----------------------------------------------------------------------------
PIP = 1e-4                  # EUR/USD: 1 pip = 0.0001
USD_PER_PIP_PER_MICROLOT = 0.10   # 0.01 lot = 1,000 notional -> $0.10 / pip


# ============================================================================
# 1. COST MODEL
# ============================================================================
@dataclass
class CostModel:
    """
    All costs expressed in PIPS so they compare directly against the target.

    Reference conversion for the stated broker terms:
        0.01 lot  -> $0.10 per pip
        $0.02 commission per 0.01 lot  ->  0.02 / 0.10  =  0.20 pips per side

    That is the number that matters. "Two cents" is 0.2 pips, and 0.2 pips
    against a 1-pip target is 20% of gross revenue.
    """
    commission_pips_per_side: float = 0.20
    spread_pips: float = 0.10       # realistic AVERAGE, not the advertised "from 0.0"
    slippage_pips_per_fill: float = 0.05

    @property
    def round_trip_pips(self) -> float:
        return (2 * self.commission_pips_per_side
                + self.spread_pips
                + 2 * self.slippage_pips_per_fill)

    def cost_ratio(self, target_pips: float) -> float:
        """Cost as a fraction of gross target -- the single most telling number."""
        return self.round_trip_pips / target_pips


# ============================================================================
# 2. ANALYTIC BASELINE: the barrier / optional-stopping result
# ============================================================================
def analytic_barrier(target_pips: float,
                     stop_pips: float,
                     cost: CostModel) -> dict:
    """
    For a driftless random walk, P(hit +a before -b) = b / (a + b).

    Gross expectancy is then EXACTLY zero:
        E = a * b/(a+b)  -  b * a/(a+b)  =  0

    This is the optional stopping theorem, and it is why "my take-profit gets
    hit almost every time" is not evidence of an edge -- it is the DEFINITION
    of a zero-EV bet. The high win rate is precisely offset by the rare large
    loss. Net expectancy is therefore just minus costs.
    """
    a, b = target_pips, stop_pips
    p_win = b / (a + b)
    gross_ev = p_win * a - (1 - p_win) * b
    c = cost.round_trip_pips
    net_ev = gross_ev - c
    return {
        "target_pips": a,
        "stop_pips": b,
        "p_win": p_win,
        "gross_ev_pips": gross_ev,
        "cost_pips": c,
        "net_ev_pips": net_ev,
        "wins_to_repay_one_loss": b / a,
    }


def ladder_loss_pips(displacement_pips: float, spacing_pips: float) -> float:
    """
    Open loss of a linear grid ladder after an adverse move of `displacement`.

        N     = displacement / spacing          (levels filled)
        loss  = spacing * N(N+1)/2  ~  displacement^2 / (2 * spacing)

    KEY CONSEQUENCE: loss is INVERSELY proportional to spacing.
    Halving the grid spacing DOUBLES the loss for the same adverse move,
    while halving the income per round trip.

    Income per unit of tail risk therefore scales as spacing^2.
    Tightening spacing 10x degrades it by 100x.
    """
    n = max(int(displacement_pips / spacing_pips), 0)
    return spacing_pips * n * (n + 1) / 2.0


# ============================================================================
# 3. PRICE PROCESSES (for harness validation)
# ============================================================================
def gbm_path(n: int, s0: float = 1.1500, ann_vol: float = 0.08,
             bars_per_year: int = 252 * 1440, seed: int = 0) -> np.ndarray:
    """Driftless geometric random walk. A grid MUST show no edge here."""
    rng = np.random.default_rng(seed)
    sigma = ann_vol / np.sqrt(bars_per_year)
    steps = rng.normal(0.0, sigma, n)
    return s0 * np.exp(np.cumsum(steps))


def ou_path(n: int, s0: float = 1.1500, ann_vol: float = 0.08,
            half_life_bars: int = 240, bars_per_year: int = 252 * 1440,
            seed: int = 0) -> np.ndarray:
    """Mean-reverting Ornstein-Uhlenbeck. A grid SHOULD show an edge here."""
    rng = np.random.default_rng(seed)
    sigma = ann_vol / np.sqrt(bars_per_year)
    theta = np.log(2.0) / half_life_bars
    x = np.zeros(n)
    shocks = rng.normal(0.0, sigma, n)
    for i in range(1, n):
        x[i] = x[i - 1] * (1 - theta) + shocks[i]
    return s0 * np.exp(x)


def trending_path(n: int, s0: float = 1.1500, ann_vol: float = 0.08,
                  ann_drift: float = -0.12, bars_per_year: int = 252 * 1440,
                  seed: int = 0) -> np.ndarray:
    """Persistent drift -- the macro displacement scenario."""
    rng = np.random.default_rng(seed)
    sigma = ann_vol / np.sqrt(bars_per_year)
    mu = ann_drift / bars_per_year
    steps = rng.normal(mu, sigma, n)
    return s0 * np.exp(np.cumsum(steps))


# ============================================================================
# 4. EFFICIENCY RATIO
# ============================================================================
def efficiency_ratio(close: np.ndarray, window: int = 20) -> np.ndarray:
    """
    Kaufman Efficiency Ratio: |net change| / sum(|bar-to-bar change|).

    ER ~ 0 -> choppy  (path length >> displacement): grid-friendly
    ER ~ 1 -> directional: grid-hostile

    This measures what actually drives grid P&L. Daily RANGE does not:
    two days with identical range can have opposite grid outcomes.
    """
    close = np.asarray(close, dtype=float)
    absdiff = np.abs(np.diff(close, prepend=close[0]))
    csum = np.cumsum(absdiff)
    er = np.full(close.shape, np.nan)
    net = np.abs(close[window:] - close[:-window])
    path = csum[window:] - csum[:-window]
    with np.errstate(divide="ignore", invalid="ignore"):
        er[window:] = np.where(path > 0, net / path, np.nan)
    return er


# ============================================================================
# 5. GRID SIMULATOR
# ============================================================================
@dataclass
class GridConfig:
    spacing_pips: float = 20.0
    take_profit_pips: Optional[float] = None   # defaults to spacing
    max_levels_per_side: int = 6
    basket_stop_pips: Optional[float] = None   # None = NO STOP (shows raw tail)
    cooldown_bars: int = 60
    er_window: int = 20
    er_gate_max: Optional[float] = None        # e.g. 0.30; None = gate disabled
    bidirectional: bool = True

    def tp(self) -> float:
        return self.take_profit_pips or self.spacing_pips


@dataclass
class GridResult:
    realized_pips: float = 0.0
    n_round_trips: int = 0
    n_wins: int = 0
    n_basket_stops: int = 0
    max_adverse_excursion_pips: float = 0.0
    max_levels_held: int = 0
    equity_pips: np.ndarray = field(default_factory=lambda: np.array([]))
    bars_in_market: int = 0

    @property
    def win_rate(self) -> float:
        return self.n_wins / self.n_round_trips if self.n_round_trips else float("nan")

    @property
    def return_over_mae(self) -> float:
        """
        THE headline metric. Total realized profit divided by worst adverse
        excursion. This is 'how much did I earn per unit of risk I actually
        took', and unlike total return it cannot be inflated by leverage or
        by luck in avoiding the tail.
        """
        m = self.max_adverse_excursion_pips
        return self.realized_pips / m if m > 0 else float("nan")


def simulate_grid(close: np.ndarray, cfg: GridConfig, cost: CostModel) -> GridResult:
    """
    Event-driven bidirectional grid on close prices.

    Longs fill at anchor - k*spacing and take profit at fill + tp.
    Shorts fill at anchor + k*spacing and take profit at fill - tp.
    Basket stop acts on TOTAL unrealized P&L across all open units.

    Deliberately optimistic in two ways, so that a failure here is decisive:
      * fills assumed available at the exact level (no queue position)
      * no requotes / rejects / broker last-look
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    tp = cfg.tp()
    cost_rt = cost.round_trip_pips

    er = (efficiency_ratio(close, cfg.er_window)
          if cfg.er_gate_max is not None else None)

    res = GridResult()
    equity = np.zeros(n)
    # level index k -> entry price in pips-space. dict gives O(1) fill checks.
    longs: dict[int, float] = {}
    shorts: dict[int, float] = {}
    anchor: Optional[float] = None
    cooldown = 0
    s = cfg.spacing_pips
    kmax = cfg.max_levels_per_side

    px_pips = (close - close[0]) / PIP

    for i in range(n):
        p = px_pips[i]

        if cooldown > 0:
            cooldown -= 1
            equity[i] = res.realized_pips
            continue

        gated_out = (er is not None and not np.isnan(er[i])
                     and er[i] > cfg.er_gate_max)

        # ---- close winners -------------------------------------------------
        if longs:
            for k in [k for k, e in longs.items() if p - e >= tp]:
                del longs[k]
                res.realized_pips += tp - cost_rt
                res.n_round_trips += 1
                res.n_wins += 1
        if shorts:
            for k in [k for k, e in shorts.items() if e - p >= tp]:
                del shorts[k]
                res.realized_pips += tp - cost_rt
                res.n_round_trips += 1
                res.n_wins += 1

        # ---- anchor: set ONCE, held fixed until a basket stop resets it -----
        # (Re-anchoring to price on every flat bar would mean a level could only
        #  ever be reached by a single-bar move -- the bug in the first version.)
        if anchor is None and not gated_out:
            anchor = p

        # ---- open new levels -----------------------------------------------
        if anchor is not None and not gated_out:
            # how many levels below/above the anchor is price now?
            down = int((anchor - p) / s)
            if down >= 1:
                for k in range(1, min(down, kmax) + 1):
                    if k not in longs:
                        longs[k] = anchor - k * s
            if cfg.bidirectional:
                up = int((p - anchor) / s)
                if up >= 1:
                    for k in range(1, min(up, kmax) + 1):
                        if k not in shorts:
                            shorts[k] = anchor + k * s

        # ---- unrealized & basket stop --------------------------------------
        unreal = 0.0
        for e in longs.values():
            unreal += p - e
        for e in shorts.values():
            unreal += e - p

        if unreal < -res.max_adverse_excursion_pips:
            res.max_adverse_excursion_pips = -unreal
        held = len(longs) + len(shorts)
        if held:
            res.max_levels_held = max(res.max_levels_held, held)
            res.bars_in_market += 1

        if cfg.basket_stop_pips is not None and unreal <= -cfg.basket_stop_pips:
            res.realized_pips += unreal - cost_rt * held
            res.n_round_trips += held
            res.n_basket_stops += 1
            longs, shorts, anchor = {}, {}, None
            cooldown = cfg.cooldown_bars

        equity[i] = res.realized_pips + unreal

    res.equity_pips = equity
    return res


# ============================================================================
# 6. SURROGATE TEST  <-- the decisive diagnostic
# ============================================================================
def surrogate_test(close: np.ndarray, cfg: GridConfig, cost: CostModel,
                   n_surrogates: int = 20, seed: int = 0) -> dict:
    """
    Compare real-path performance against IID-shuffled returns.

    Shuffling preserves the return DISTRIBUTION exactly but destroys all
    temporal structure. Any genuine mean-reversion edge must therefore vanish
    in the surrogates. If it does not, there was no edge to begin with.

    Reported p-value = fraction of surrogates matching or beating the real
    path. p > 0.05 means the real result is indistinguishable from a path
    with no mean reversion at all.
    """
    rng = np.random.default_rng(seed)
    real = simulate_grid(close, cfg, cost)
    logret = np.diff(np.log(close))

    stats = []
    for _ in range(n_surrogates):
        shuffled = rng.permutation(logret)
        path = close[0] * np.exp(np.concatenate([[0.0], np.cumsum(shuffled)]))
        r = simulate_grid(path, cfg, cost)
        stats.append(r.return_over_mae)

    stats = np.asarray(stats, dtype=float)
    finite = stats[np.isfinite(stats)]
    real_rom = real.return_over_mae
    p = (float(np.mean(finite >= real_rom)) if finite.size and np.isfinite(real_rom)
         else float("nan"))
    return {
        "real": real,
        "real_return_over_mae": real_rom,
        "surrogate_mean": float(np.mean(finite)) if finite.size else float("nan"),
        "surrogate_std": float(np.std(finite)) if finite.size else float("nan"),
        "p_value": p,
        "verdict": _verdict(p),
    }


def _verdict(p: float) -> str:
    if not np.isfinite(p):
        return "INCONCLUSIVE - insufficient trades"
    if p > 0.20:
        return "NO EDGE - indistinguishable from shuffled (zero-EV structure)"
    if p > 0.05:
        return "WEAK / UNPROVEN - do not fund"
    return "SIGNAL PRESENT - proceed to cost & holdout testing"


# ============================================================================
# 7. REPORTING
# ============================================================================
def _rule(ch="=", n=78):
    print(ch * n)


def report_cost_arithmetic(cost: CostModel, targets=(1.0, 2.0, 5.0, 10.0, 20.0)):
    _rule()
    print("SECTION 1 -- COST ARITHMETIC (the first thing that kills micro-targets)")
    _rule()
    print(f"  commission/side : {cost.commission_pips_per_side:.2f} pips"
          f"   (= ${cost.commission_pips_per_side * USD_PER_PIP_PER_MICROLOT:.3f} per 0.01 lot)")
    print(f"  avg spread      : {cost.spread_pips:.2f} pips")
    print(f"  slippage/fill   : {cost.slippage_pips_per_fill:.2f} pips")
    print(f"  ROUND TRIP COST : {cost.round_trip_pips:.2f} pips"
          f"   (= ${cost.round_trip_pips * USD_PER_PIP_PER_MICROLOT:.3f} per 0.01 lot)\n")
    print(f"  {'target':>8} {'gross $':>9} {'cost %':>9} {'net pips':>10} {'verdict':>12}")
    print("  " + "-" * 52)
    for t in targets:
        ratio = cost.cost_ratio(t)
        net = t - cost.round_trip_pips
        v = "FATAL" if ratio > 0.30 else ("MARGINAL" if ratio > 0.12 else "OK")
        print(f"  {t:>6.1f}p {t * USD_PER_PIP_PER_MICROLOT:>8.2f} "
              f"{ratio * 100:>8.1f}% {net:>9.2f} {v:>12}")
    print("\n  Costs scale with TRADE COUNT; profit scales with TARGET SIZE.")
    print("  Shrinking the target raises the cost ratio proportionally.")


def report_tail_arithmetic(spacings=(1.0, 2.0, 5.0, 10.0, 20.0),
                           displacement=60.0):
    _rule()
    print(f"SECTION 2 -- TAIL ARITHMETIC (adverse move = {displacement:.0f} pips, "
          f"an ordinary day)")
    _rule()
    print(f"  {'spacing':>8} {'levels':>7} {'open loss':>11} {'loss $':>9} "
          f"{'win $':>8} {'wins to repay':>14}")
    print("  " + "-" * 62)
    for s in spacings:
        loss = ladder_loss_pips(displacement, s)
        loss_usd = loss * USD_PER_PIP_PER_MICROLOT
        win_usd = s * USD_PER_PIP_PER_MICROLOT
        print(f"  {s:>6.1f}p {int(displacement / s):>7} {loss:>10.0f}p "
              f"{loss_usd:>8.2f} {win_usd:>7.2f} {loss / s:>13.0f}")
    print("\n  loss ~ displacement^2 / (2 x spacing)  ->  TIGHTER SPACING = BIGGER LOSS")
    print("  income per unit of tail risk ~ spacing^2  ->  10x tighter = 100x worse")


def report_analytic(cost: CostModel, pairs=((1.0, 60.0), (2.0, 60.0), (20.0, 60.0))):
    _rule()
    print("SECTION 3 -- WHY A 98% WIN RATE IS NOT AN EDGE")
    _rule()
    print(f"  {'target':>8} {'stop':>8} {'P(win)':>9} {'gross EV':>10} "
          f"{'net EV':>9} {'losses of':>10}")
    print("  " + "-" * 58)
    for t, s in pairs:
        a = analytic_barrier(t, s, cost)
        print(f"  {t:>6.1f}p {s:>6.1f}p {a['p_win'] * 100:>8.2f}% "
              f"{a['gross_ev_pips']:>9.2f}p {a['net_ev_pips']:>8.2f}p "
              f"{a['wins_to_repay_one_loss']:>9.0f}x")
    print("\n  Gross EV is EXACTLY zero at every target (optional stopping theorem).")
    print("  The high win rate IS the zero-EV property, not evidence against it.")
    print("  Net EV is therefore just -costs. Note it worsens as target shrinks.")


def report_er(close: np.ndarray, window: int = 20):
    _rule()
    print("SECTION 4 -- EFFICIENCY RATIO REGIME CENSUS")
    _rule()
    er = efficiency_ratio(close, window)
    er = er[np.isfinite(er)]
    if er.size == 0:
        print("  insufficient data")
        return
    for q in (10, 25, 50, 75, 90):
        print(f"  ER p{q:<3d} : {np.percentile(er, q):.3f}")
    frac = float(np.mean(er < 0.30))
    print(f"\n  Fraction of bars with ER < 0.30 (grid-favourable): {frac * 100:.1f}%")
    print("  That fraction is the CEILING on how often this strategy can work.")


def report_spacing_sweep(close: np.ndarray, cost: CostModel,
                         spacings, basket_mult: float = 3.0,
                         er_gate: Optional[float] = None):
    _rule()
    print("SECTION 5 -- SPACING SWEEP (with basket stop)")
    _rule()
    print(f"  {'spacing':>8} {'trips':>7} {'win%':>7} {'net pips':>10} "
          f"{'MAE':>8} {'ret/MAE':>9} {'stops':>6}")
    print("  " + "-" * 60)
    rows = []
    for s in spacings:
        cfg = GridConfig(
            spacing_pips=s,
            basket_stop_pips=basket_mult * s * 6,
            er_gate_max=er_gate,
        )
        r = simulate_grid(close, cfg, cost)
        rows.append((s, r))
        print(f"  {s:>6.1f}p {r.n_round_trips:>7d} {r.win_rate * 100:>6.1f}% "
              f"{r.realized_pips:>9.1f}p {r.max_adverse_excursion_pips:>7.0f}p "
              f"{r.return_over_mae:>8.3f} {r.n_basket_stops:>6d}")
    return rows


def report_surrogate(close: np.ndarray, cost: CostModel, spacings,
                     n_surrogates: int = 12):
    _rule()
    print("SECTION 6 -- SURROGATE TEST  <<< THE DECIDING RESULT")
    _rule()
    print("  Real path vs. same returns shuffled (mean reversion destroyed).\n")
    print(f"  {'spacing':>8} {'real r/MAE':>11} {'shuffled':>10} {'p':>7}  verdict")
    print("  " + "-" * 74)
    for s in spacings:
        cfg = GridConfig(spacing_pips=s, basket_stop_pips=3.0 * s * 6)
        out = surrogate_test(close, cfg, cost, n_surrogates=n_surrogates)
        print(f"  {s:>6.1f}p {out['real_return_over_mae']:>10.3f} "
              f"{out['surrogate_mean']:>9.3f} {out['p_value']:>6.2f}  {out['verdict']}")


# ============================================================================
# 8. SELF-TEST -- validate the harness where the answer is known
# ============================================================================
def self_test(n: int = 400_000, cost: Optional[CostModel] = None):
    cost = cost or CostModel()
    _rule("#")
    print("HARNESS SELF-TEST -- synthetic processes with KNOWN answers")
    _rule("#")
    print("Expected: GBM -> NO EDGE.  OU -> EDGE.  If wrong, do not trust results.\n")

    frictionless = CostModel(0.0, 0.0, 0.0)
    for name, path in (("GBM (random walk)", gbm_path(n, seed=1)),
                       ("OU (mean-reverting)", ou_path(n, seed=1)),
                       ("Trending (drift)", trending_path(n, seed=1))):
        cfg = GridConfig(spacing_pips=5.0, basket_stop_pips=90.0)
        out = surrogate_test(path, cfg, frictionless, n_surrogates=10)
        r = out["real"]
        print(f"  {name:<22} trips={r.n_round_trips:>6d} "
              f"win={r.win_rate * 100:>5.1f}% ret/MAE={out['real_return_over_mae']:>7.3f} "
              f"shuf={out['surrogate_mean']:>7.3f} p={out['p_value']:.2f}")
        print(f"  {'':<22} -> {out['verdict']}\n")
    print("  Note the win rates: all high, including the ones with no edge.")
    print("  Win rate carries no information. ret/MAE and p do.\n")


# ============================================================================
# 9. MAIN
# ============================================================================
def load_csv(path: str) -> np.ndarray:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    if "close" in cols:
        return df[cols["close"]].to_numpy(dtype=float)
    if "bid" in cols and "ask" in cols:
        return ((df[cols["bid"]] + df[cols["ask"]]) / 2).to_numpy(dtype=float)
    raise SystemExit("CSV needs a 'close' column, or both 'bid' and 'ask'.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Grid / micro-harvest diagnostic")
    ap.add_argument("--csv", help="EUR/USD minute bars")
    ap.add_argument("--self-test", action="store_true",
                    help="validate harness on synthetic data")
    ap.add_argument("--spacings", type=float, nargs="+",
                    default=[1.0, 2.0, 5.0, 10.0, 20.0])
    ap.add_argument("--commission", type=float, default=0.20,
                    help="pips per side ($0.02 per 0.01 lot = 0.20 pips)")
    ap.add_argument("--spread", type=float, default=0.10,
                    help="AVERAGE spread in pips (not the advertised minimum)")
    ap.add_argument("--slippage", type=float, default=0.05)
    ap.add_argument("--surrogates", type=int, default=12)
    ap.add_argument("--demo", action="store_true",
                    help="run full report on synthetic random-walk data")
    args = ap.parse_args(argv)

    cost = CostModel(args.commission, args.spread, args.slippage)

    if args.self_test:
        self_test(cost=cost)
        return 0

    report_cost_arithmetic(cost)
    print()
    report_tail_arithmetic(spacings=tuple(args.spacings))
    print()
    report_analytic(cost)
    print()

    if args.csv:
        close = load_csv(args.csv)
        label = args.csv
    elif args.demo:
        close = gbm_path(400_000, seed=7)
        label = "SYNTHETIC random walk (demo -- substitute real data)"
    else:
        print("No --csv supplied. Sections 1-3 above are data-independent and\n"
              "already decisive for micro-targets. Add --csv or --demo for 4-6.")
        return 0

    print(f"Data: {label}  ({len(close):,} bars)\n")
    report_er(close)
    print()
    report_spacing_sweep(close, cost, args.spacings)
    print()
    report_surrogate(close, cost, args.spacings, n_surrogates=args.surrogates)
    print()
    _rule()
    print("PASS BAR before any capital:")
    print("  1. Surrogate p < 0.05 at your chosen spacing")
    print("  2. Positive ret/MAE in >= 7 of 10 calendar years")
    print("  3. Still positive in an untouched 3-year holdout")
    print("  4. Basket stop TRIGGERS in backtest (if it never fires, it is")
    print("     mis-specified, not safe)")
    print("  5. Deflated Sharpe positive after counting every variant tried")
    _rule()
    return 0


if __name__ == "__main__":
    sys.exit(main())
