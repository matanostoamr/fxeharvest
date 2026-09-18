#!/usr/bin/env python3
"""
5-PIP HARVESTER -- reference implementation.

Broker-agnostic strategy core + backtest runner. The logic here is what you
port to MT5 / cTrader / a REST API; the runner lets you see the mechanics and
tune parameters before touching a live account.

DESIGN SUMMARY (see harvester-blueprint.md for the reasoning)
-------------------------------------------------------------
  Execution     : resting LIMIT ladder for entries, attached LIMIT for TP,
                  attached far SL as server-side disaster backstop,
                  MARKET order for the client-side basket stop.
  Take profit   : 5.0 pips fixed  (= $0.50 on 0.01 lot)  <- your target
  Spacing       : DECOUPLED from TP. base = 2.0 x ATR20(M15), clamped [7,15]
  Level layout  : progressive widening -- gaps s, 1.25s, 1.5s, 1.75s
                  depths at s=10 -> 10.0 / 22.5 / 37.5 / 55.0
  Anchor        : SMA(20) when flat, then FROZEN until flat again
  Regime gate   : Efficiency Ratio (run < 0.35, stand down > 0.50)
  Entry veto    : RSI(14) extremes -- do not add into an impulse
  Basket stop   : |price - anchor| > 6.0 x base_spacing  (~60 pips at s=10)

Run:
    python3 harvester.py --demo
    python3 harvester.py --csv eurusd_m15.csv
    python3 harvester.py --demo --sweep
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

PIP = 1e-4
USD_PER_PIP_PER_MICROLOT = 0.10


# ============================================================================
# PARAMETERS
# ============================================================================
@dataclass
class Params:
    # --- target (your specification) ---------------------------------------
    tp_pips: float = 5.0

    # --- spacing: deliberately NOT equal to tp ------------------------------
    atr_mult: float = 2.0           # base spacing = atr_mult x ATR20
    spacing_min: float = 7.0        # floor protects the cost ratio
    spacing_max: float = 15.0
    widen: float = 0.25             # gap_k = s * (1 + widen*(k-1))
    max_levels: int = 3             # per side (measured optimum)

    # --- basket stop --------------------------------------------------------
    basket_mult: float = 6.0        # trigger at basket_mult x base_spacing
    equity_stop_pct: float = 0.06   # second condition: % of starting equity
    disaster_sl_mult: float = 2.0   # server-side per-position SL = mult x D_max

    # --- indicators ---------------------------------------------------------
    anchor_ma: int = 20
    atr_window: int = 20
    er_window: int = 20
    er_run: float = 0.35            # below -> full size
    er_half: float = 0.50           # between -> half size; above -> flat
    rsi_period: int = 14
    rsi_long_veto: float = 25.0     # no new longs below this
    rsi_short_veto: float = 75.0    # no new shorts above this
    bw_expansion_mult: float = 1.6  # stand down if BB width > mult x median

    # --- execution / ops ----------------------------------------------------
    preplace_levels: int = 3        # levels resting on server at any time
    cooldown_bars: int = 96         # after a basket stop (96 M15 = 1 day)
    lots_per_level: float = 0.01

    # --- costs (your broker) -----------------------------------------------
    commission_pips_per_side: float = 0.20
    spread_pips: float = 0.10
    slippage_limit: float = 0.0     # resting limit: no entry slippage
    slippage_market: float = 0.10   # basket-stop exit is a market order

    @property
    def cost_limit_round_trip(self) -> float:
        """Limit in, limit out: commission both sides + spread once."""
        return 2 * self.commission_pips_per_side + self.spread_pips

    @property
    def cost_market_exit(self) -> float:
        return self.commission_pips_per_side + self.spread_pips + self.slippage_market

    def level_depths(self, spacing: float) -> list[float]:
        """Cumulative distance from anchor for each level (progressive widening)."""
        depths, cum = [], 0.0
        for k in range(1, self.max_levels + 1):
            cum += spacing * (1.0 + self.widen * (k - 1))
            depths.append(cum)
        return depths


# ============================================================================
# INDICATORS
# ============================================================================
def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def atr_proxy(close: np.ndarray, n: int) -> np.ndarray:
    """Close-to-close true-range proxy, in PRICE units. Feed M15 bars."""
    tr = np.abs(np.diff(close, prepend=close[0]))
    return pd.Series(tr).rolling(n, min_periods=n).mean().to_numpy()


def rsi(close: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(close, prepend=close[0])
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0).to_numpy()


def efficiency_ratio(close: np.ndarray, n: int) -> np.ndarray:
    absdiff = np.abs(np.diff(close, prepend=close[0]))
    csum = np.cumsum(absdiff)
    er = np.full(close.shape, np.nan)
    net = np.abs(close[n:] - close[:-n])
    path = csum[n:] - csum[:-n]
    with np.errstate(divide="ignore", invalid="ignore"):
        er[n:] = np.where(path > 0, net / path, np.nan)
    return er


def bb_width(close: np.ndarray, n: int) -> np.ndarray:
    return (pd.Series(close).rolling(n, min_periods=n).std() * 2).to_numpy()


# ============================================================================
# STATE
# ============================================================================
class State(Enum):
    FLAT = "FLAT"
    ACTIVE = "ACTIVE"
    COOLDOWN = "COOLDOWN"


@dataclass
class Position:
    side: int          # +1 long, -1 short
    level: int
    entry_pips: float
    tp_pips: float
    size: float


@dataclass
class Stats:
    realized_pips: float = 0.0
    n_tp: int = 0
    n_basket_stops: int = 0
    n_levels_filled: int = 0
    max_adverse_pips: float = 0.0
    max_concurrent: int = 0
    bars_active: int = 0
    bars_gated_out: int = 0
    equity_curve: list[float] = field(default_factory=list)
    stop_losses_pips: list[float] = field(default_factory=list)

    @property
    def gross_usd(self) -> float:
        return self.realized_pips * USD_PER_PIP_PER_MICROLOT

    @property
    def win_rate(self) -> float:
        tot = self.n_tp + self.n_basket_stops
        return self.n_tp / tot if tot else float("nan")

    @property
    def ret_over_mae(self) -> float:
        return (self.realized_pips / self.max_adverse_pips
                if self.max_adverse_pips > 0 else float("nan"))

    @property
    def trips_to_repay_stop(self) -> float:
        if not self.stop_losses_pips:
            return float("nan")
        avg = abs(np.mean(self.stop_losses_pips))
        net_win = 5.0  # informational; recomputed by caller if tp differs
        return avg / net_win


# ============================================================================
# STRATEGY CORE
# ============================================================================
def run_harvester(close: np.ndarray, p: Params, verbose: bool = False) -> Stats:
    """
    Event loop on M15 closes. One bar = one decision point.

    The state machine is the important part to port:
        FLAT      -> compute anchor + spacing, gate on ER, place ladder
        ACTIVE    -> anchor FROZEN; fill levels, take profit, watch basket
        COOLDOWN  -> nothing rests on the server
    """
    n = len(close)
    px = (close - close[0]) / PIP          # work in pips throughout

    ma = sma(close, p.anchor_ma)
    atr = atr_proxy(close, p.atr_window) / PIP      # pips
    er = efficiency_ratio(close, p.er_window)
    rs = rsi(close, p.rsi_period)
    bw = bb_width(close, p.anchor_ma) / PIP
    bw_med = pd.Series(bw).rolling(50, min_periods=20).median().to_numpy()

    st = Stats()
    state = State.FLAT
    positions: dict[tuple[int, int], Position] = {}
    anchor: Optional[float] = None
    spacing: float = p.spacing_min
    depths: list[float] = []
    cooldown = 0
    cycle_entries = 0        # fills in the CURRENT cycle (see release guard)
    start_equity_pips = 1000.0 / USD_PER_PIP_PER_MICROLOT   # $1000 reference

    for i in range(n):
        price = px[i]

        if np.isnan(ma[i]) or np.isnan(atr[i]) or np.isnan(er[i]):
            st.equity_curve.append(st.realized_pips)
            continue

        # ---------- COOLDOWN ------------------------------------------------
        if state is State.COOLDOWN:
            cooldown -= 1
            if cooldown <= 0:
                state = State.FLAT
            st.equity_curve.append(st.realized_pips)
            continue

        # ---------- regime gate --------------------------------------------
        size_mult = 1.0
        if er[i] > p.er_half:
            size_mult = 0.0
        elif er[i] > p.er_run:
            size_mult = 0.5
        if not np.isnan(bw_med[i]) and bw[i] > p.bw_expansion_mult * bw_med[i]:
            size_mult = 0.0          # volatility expansion: grid-hostile

        # ---------- FLAT: (re)anchor and arm ------------------------------
        if state is State.FLAT:
            if size_mult == 0.0:
                st.bars_gated_out += 1
                st.equity_curve.append(st.realized_pips)
                continue
            anchor = (ma[i] - close[0]) / PIP     # anchor on the SMA, in pips
            spacing = float(np.clip(p.atr_mult * atr[i],
                                    p.spacing_min, p.spacing_max))
            depths = p.level_depths(spacing)
            cycle_entries = 0
            state = State.ACTIVE

        # ---------- ACTIVE --------------------------------------------------
        st.bars_active += 1
        assert anchor is not None

        # (a) take profit on resting TP limits
        for key in [k for k, q in positions.items()
                    if (q.side == 1 and price >= q.tp_pips)
                    or (q.side == -1 and price <= q.tp_pips)]:
            q = positions.pop(key)
            st.realized_pips += (p.tp_pips - p.cost_limit_round_trip) * q.size / 0.01
            st.n_tp += 1

        # (b) fill new levels -- limit orders, no slippage
        dist = price - anchor
        if size_mult > 0:
            if dist < 0:                                   # price below anchor -> buy
                if rs[i] >= p.rsi_long_veto:               # veto: don't add into impulse
                    for k, d in enumerate(depths, start=1):
                        if -dist >= d and (1, k) not in positions:
                            entry = anchor - d
                            positions[(1, k)] = Position(
                                1, k, entry, entry + p.tp_pips,
                                p.lots_per_level * size_mult)
                            st.n_levels_filled += 1
                            cycle_entries += 1
            elif dist > 0:                                 # price above anchor -> sell
                if rs[i] <= p.rsi_short_veto:
                    for k, d in enumerate(depths, start=1):
                        if dist >= d and (-1, k) not in positions:
                            entry = anchor + d
                            positions[(-1, k)] = Position(
                                -1, k, entry, entry - p.tp_pips,
                                p.lots_per_level * size_mult)
                            st.n_levels_filled += 1
                            cycle_entries += 1

        # (c) unrealized + MAE
        unreal = 0.0
        for q in positions.values():
            unreal += (price - q.entry_pips) * q.side * (q.size / 0.01)
        if unreal < -st.max_adverse_pips:
            st.max_adverse_pips = -unreal
        st.max_concurrent = max(st.max_concurrent, len(positions))

        # (d) BASKET STOP -- market order, client-side
        d_max = p.basket_mult * spacing
        equity_trip = -p.equity_stop_pct * start_equity_pips
        if positions and (abs(dist) > d_max or unreal <= equity_trip):
            held = len(positions)
            st.realized_pips += unreal - p.cost_market_exit * held
            st.stop_losses_pips.append(unreal - p.cost_market_exit * held)
            st.n_basket_stops += 1
            if verbose:
                print(f"  bar {i}: BASKET STOP  dist={dist:+.1f}p "
                      f"unreal={unreal:.1f}p  held={held}")
            positions.clear()
            anchor = None
            state = State.COOLDOWN
            cooldown = p.cooldown_bars

        # (e) Release the anchor only when a REAL cycle finished, i.e. levels
        #     filled and then all took profit. Releasing on `not positions`
        #     alone also fires in the instant after arming, which in the MT5
        #     port meant the resting ladder was withdrawn on the next tick:
        #     1,053 pending orders placed, 1 filled, over one week.
        #
        #     NOTE ON REALISM: this simulator fills a level the moment price
        #     is beyond it, whereas MT5 requires the limit order to be resting
        #     when price arrives. This model is therefore OPTIMISTIC about fill
        #     counts; treat its trade frequency as an upper bound.
        elif not positions and cycle_entries > 0:
            state = State.FLAT
            anchor = None
            cycle_entries = 0

        st.equity_curve.append(st.realized_pips + unreal)

    return st


# ============================================================================
# SYNTHETIC DATA (M15)
# ============================================================================
def synth_m15(years: float = 3.0, ann_vol: float = 0.08, s0: float = 1.1500,
              ann_drift: float = 0.0, seed: int = 0) -> np.ndarray:
    bars_per_year = 252 * 96
    n = int(years * bars_per_year)
    rng = np.random.default_rng(seed)
    sig = ann_vol / np.sqrt(bars_per_year)
    mu = ann_drift / bars_per_year
    return s0 * np.exp(np.cumsum(rng.normal(mu, sig, n)))


# ============================================================================
# REPORTING
# ============================================================================
def _rule(c="=", n=78):
    print(c * n)


def show_geometry(p: Params, spacing: float = 10.0):
    _rule()
    print(f"LADDER GEOMETRY  (base spacing = {spacing:.1f} pips, TP = {p.tp_pips:.1f})")
    _rule()
    depths = p.level_depths(spacing)
    print(f"  {'level':>6} {'gap':>7} {'depth':>8} {'TP at':>9} {'loss if D=Dmax':>16}")
    print("  " + "-" * 50)
    d_max = p.basket_mult * spacing
    prev, total = 0.0, 0.0
    for k, d in enumerate(depths, 1):
        loss = max(d_max - d, 0.0)
        total += loss
        print(f"  {k:>6} {d - prev:>6.1f}p {d:>7.1f}p "
              f"{d - p.tp_pips:>8.1f}p {loss:>15.1f}p")
        prev = d
    print("  " + "-" * 50)
    print(f"  basket stop at |price-anchor| > {d_max:.1f} pips")
    print(f"  aggregate loss at that point  = {total:.1f} pips "
          f"= ${total * USD_PER_PIP_PER_MICROLOT:.2f} @ {p.lots_per_level} lot/level")
    net_win = p.tp_pips - p.cost_limit_round_trip
    print(f"  net per winning round trip    = {net_win:.2f} pips "
          f"= ${net_win * USD_PER_PIP_PER_MICROLOT:.3f}")
    print(f"  >> ROUND TRIPS TO REPAY ONE STOP-OUT = {total / net_win:.0f}")
    print(f"\n  cost ratio at TP={p.tp_pips:.0f}p: "
          f"{p.cost_limit_round_trip / p.tp_pips * 100:.1f}% of gross "
          f"(limit-in/limit-out, no entry slippage)")


def report(st: Stats, p: Params, label: str, n_bars: int):
    _rule()
    print(f"BACKTEST MECHANICS -- {label}")
    _rule()
    net_win = p.tp_pips - p.cost_limit_round_trip
    days = n_bars / 96
    print(f"  bars                 : {n_bars:,}  (~{days:,.0f} trading days)")
    print(f"  bars active          : {st.bars_active:,} "
          f"({st.bars_active / n_bars * 100:.1f}%)")
    print(f"  bars gated out by ER : {st.bars_gated_out:,} "
          f"({st.bars_gated_out / n_bars * 100:.1f}%)")
    print(f"  levels filled        : {st.n_levels_filled:,}")
    print(f"  take-profits hit     : {st.n_tp:,}")
    print(f"  basket stops         : {st.n_basket_stops:,}")
    print(f"  max concurrent       : {st.max_concurrent}")
    print(f"  TP per active day    : {st.n_tp / max(days, 1):.2f}")
    print()
    print(f"  net realized         : {st.realized_pips:,.0f} pips "
          f"= ${st.gross_usd:,.2f}  @ {p.lots_per_level} lot/level")
    print(f"  max adverse (MAE)    : {st.max_adverse_pips:,.0f} pips "
          f"= ${st.max_adverse_pips * USD_PER_PIP_PER_MICROLOT:,.2f}")
    print(f"  return / MAE         : {st.ret_over_mae:.3f}")
    if st.stop_losses_pips:
        avg = float(np.mean(st.stop_losses_pips))
        wst = float(np.min(st.stop_losses_pips))
        print(f"  avg basket stop loss : {avg:,.1f} pips "
              f"(= {abs(avg) / net_win:.0f} winning trips)")
        print(f"  worst basket stop    : {wst:,.1f} pips")
    print(f"  win rate (TP vs stop): {st.win_rate * 100:.1f}%")


def sweep(close: np.ndarray, base: Params):
    _rule()
    print("PARAMETER SWEEP -- mechanics only")
    _rule()
    print(f"  {'atr_m':>6} {'lvls':>5} {'bskt':>5} {'TPs':>7} {'stops':>6} "
          f"{'net pips':>10} {'MAE':>8} {'r/MAE':>8}")
    print("  " + "-" * 62)
    for atr_mult in (1.5, 2.0, 2.5):
        for lv in (3, 4, 5):
            for bm in (5.0, 6.0, 8.0):
                p = Params(atr_mult=atr_mult, max_levels=lv, basket_mult=bm)
                s = run_harvester(close, p)
                print(f"  {atr_mult:>6.1f} {lv:>5} {bm:>5.1f} {s.n_tp:>7} "
                      f"{s.n_basket_stops:>6} {s.realized_pips:>9.0f}p "
                      f"{s.max_adverse_pips:>7.0f}p {s.ret_over_mae:>8.3f}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="5-pip harvester reference impl")
    ap.add_argument("--csv", help="M15 bars with a 'close' column")
    ap.add_argument("--demo", action="store_true", help="synthetic M15 data")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)

    p = Params()
    show_geometry(p, spacing=10.0)
    print()

    if a.csv:
        df = pd.read_csv(a.csv)
        cols = {c.lower(): c for c in df.columns}
        if "close" not in cols:
            raise SystemExit("CSV needs a 'close' column (M15 bars).")
        close, label = df[cols["close"]].to_numpy(float), a.csv
    elif a.demo:
        close = synth_m15(a.years, seed=11)
        label = f"SYNTHETIC random-walk M15 ({a.years}y)"
    else:
        print("Add --demo or --csv to run the backtest.")
        return 0

    st = run_harvester(close, p, verbose=a.verbose)
    report(st, p, label, len(close))
    if a.sweep:
        print()
        sweep(close, p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
