#!/usr/bin/env python3
"""
compare_presets.py -- conservative (M15 / 5.0p / 0.01) vs aggressive
(M5 / 2.5p / 0.02) on the SAME underlying price path.

Why this script exists
----------------------
The aggressive preset's pitch is "half the distance, so twice as fast". On a
scale-invariant random walk that pitch is very nearly TRUE: halving every
distance rescales time by 1/lambda^2 and leaves the number of take-profits per
basket stop UNCHANGED. Brownian motion does not care what units you measure it
in.

Three things in the real world are NOT scale-invariant, and they are the whole
argument:

  1. COMMISSION is fixed in pips (~0.5 round trip) regardless of lot size, so
     halving the TP doubles the cost ratio: 10% -> 20%.
  2. SLIPPAGE / GAPS are fixed in pips too. A 1-pip gap is 20% of a 5-pip
     target but 40% of a 2.5-pip target.
  3. D_max stops being a tail event. 6 x 2.5 = 15 pips is a routine EUR/USD
     half-hour, not an outlier -- so the basket stop turns from insurance into
     a running cost.

Generating both series from ONE M1 path is the point: any difference in the
result is caused by the geometry, not by different luck.

Usage:
    python3 compare_presets.py                 # 12 seeds, 3 years each
    python3 compare_presets.py --seeds 32
"""
from __future__ import annotations

import argparse

import numpy as np

from harvester import Params, run_harvester

PIP = 0.0001
GBP_PER_PIP_001 = 0.07914   # measured from the v2 Strategy Tester report


def m1_path(years: float, ann_vol: float, seed: int,
            s0: float = 1.1650, ann_drift: float = 0.0) -> np.ndarray:
    """One M1 close series. M5/M15 are decimations of THIS path."""
    bars = int(years * 252 * 1440)
    rng = np.random.default_rng(seed)
    sig = ann_vol / np.sqrt(252 * 1440)
    mu = ann_drift / (252 * 1440)
    return s0 * np.exp(np.cumsum(rng.normal(mu, sig, bars)))


GBP500_IN_USD = 633.0   # the actual test account, so the % equity stop is real


def conservative() -> Params:
    return Params(tp_pips=5.0, atr_mult=2.0, spacing_min=7.0, spacing_max=15.0,
                  max_levels=3, preplace_levels=2, basket_mult=6.0,
                  cooldown_bars=96, lots_per_level=0.01,
                  start_equity_usd=GBP500_IN_USD)


def aggressive() -> Params:
    # cooldown_bars=288 on M5 == 24h, matching the conservative preset's
    # 96 M15 bars. Comparing 96 bars on both would silently give the
    # aggressive preset a 3x shorter cooldown.
    return Params(tp_pips=2.5, atr_mult=1.0, spacing_min=2.5, spacing_max=6.0,
                  max_levels=3, preplace_levels=2, basket_mult=6.0,
                  cooldown_bars=288, lots_per_level=0.02,
                  start_equity_usd=GBP500_IN_USD)


def economics(p: Params, spacing: float) -> dict:
    """Closed-form geometry + cost arithmetic at a given base spacing."""
    cum, depths = 0.0, []
    for k in range(1, p.max_levels + 1):
        cum += spacing * (1.0 + p.widen * (k - 1))
        depths.append(cum)
    dmax = p.basket_mult * spacing
    gpip = GBP_PER_PIP_001 * (p.lots_per_level / 0.01)
    net_win_pips = p.tp_pips - p.cost_limit_round_trip
    loss_pips = sum(dmax - d for d in depths)
    return dict(depths=depths, dmax=dmax, gbp_per_pip=gpip,
                net_win_pips=net_win_pips,
                cost_ratio=p.cost_limit_round_trip / p.tp_pips,
                loss_pips=loss_pips, loss_gbp=loss_pips * gpip,
                wins_per_stop=loss_pips / net_win_pips)


def evaluate(label: str, p: Params, close: np.ndarray, tf_min: int,
             years: float) -> dict:
    st = run_harvester(close, p)
    econ = economics(p, p.spacing_min)
    weeks = years * 52.0

    # UNIT NOTE -- this cost a debugging round, so it is written down.
    # run_harvester accounts unrealized P&L in 0.01-LOT-EQUIVALENT pips:
    #     unreal += (price - entry) * side * (size / 0.01)
    # so stop_losses_pips at 0.02 lots is already 2x the raw pip displacement.
    # net_win_pips, by contrast, is raw pips. Dividing one by the other without
    # normalising makes RATIO look ~2x worse purely because the lot doubled --
    # which is nonsense, because RATIO is a pure pip ratio and MUST be
    # invariant to lot size. Normalise back to raw pips here.
    lot_factor = p.lots_per_level / 0.01

    if st.n_basket_stops > 0:
        avg_loss_raw = abs(float(np.mean(st.stop_losses_pips))) / lot_factor
        tps_per_stop = st.n_tp / st.n_basket_stops
        cost_in_tps = avg_loss_raw / econ["net_win_pips"]
        ratio = tps_per_stop / cost_in_tps
    else:
        avg_loss_raw = tps_per_stop = cost_in_tps = ratio = float("nan")

    # Currency P&L, by contrast, SHOULD scale with the lot.
    won = st.n_tp * econ["net_win_pips"]
    lost = st.n_basket_stops * avg_loss_raw if st.n_basket_stops > 0 else 0.0
    net_gbp = (won - lost) * econ["gbp_per_pip"]

    return dict(label=label, tf=tf_min, n_tp=st.n_tp,
                n_stops=st.n_basket_stops, win_rate=st.win_rate,
                tp_per_week=st.n_tp / weeks,
                stops_per_week=st.n_basket_stops / weeks,
                avg_loss_pips=avg_loss_raw, tps_per_stop=tps_per_stop,
                cost_in_tps=cost_in_tps, ratio=ratio,
                net_gbp_per_week=net_gbp / weeks, econ=econ)


def selftest() -> int:
    """
    Two properties, both of which must hold or the comparison is meaningless.

    1. With the % equity stop disabled, RATIO is a pure pip ratio and must be
       EXACTLY invariant to lot size, while currency P&L scales linearly.
    2. With the % equity stop enabled, RATIO must DEGRADE as lots rise -- the
       same percentage of a fixed account is reached at a smaller price move,
       so bigger lots get stopped earlier. That is real, not a bug.
    """
    m1 = m1_path(2.0, 0.08, seed=0)
    geom = dict(tp_pips=2.5, atr_mult=1.0, spacing_min=2.5, spacing_max=6.0,
                max_levels=3, preplace_levels=2, basket_mult=6.0,
                cooldown_bars=288, start_equity_usd=GBP500_IN_USD)
    # 0.20/0.50 are deliberately absurd for a GBP500 account -- they are the
    # only sizes at which the 6% equity stop actually binds before the
    # displacement stop, so without them self-test 2 would pass vacuously.
    lots_grid = (0.01, 0.02, 0.04)
    lots_grid_eq = (0.01, 0.02, 0.04, 0.20, 0.50)

    print("SELF-TEST 1: equity stop OFF -> RATIO must be lot-invariant")
    off = {}
    for lots in lots_grid:
        off[lots] = evaluate("", Params(lots_per_level=lots,
                                        equity_stop_pct=99.0, **geom),
                             m1[::5], 5, 2.0)
        print(f"  lots={lots:<5} RATIO={off[lots]['ratio']:.6f}  "
              f"avg_loss={off[lots]['avg_loss_pips']:.3f} raw pips  "
              f"GBP/wk={off[lots]['net_gbp_per_week']:+.3f}")
    rv = [off[l]["ratio"] for l in lots_grid]
    gv = [off[l]["net_gbp_per_week"] for l in lots_grid]
    ok1 = max(rv) - min(rv) < 1e-9
    ok2 = abs(gv[1] - 2 * gv[0]) < 1e-6 and abs(gv[2] - 4 * gv[0]) < 1e-6
    print(f"  RATIO spread {max(rv)-min(rv):.2e} -> {'PASS' if ok1 else 'FAIL'}")
    print(f"  GBP/week linear in lot -> {'PASS' if ok2 else 'FAIL'}")

    print("\nSELF-TEST 2: equity stop ON -> RATIO must fall once lots are big "
          "enough for it to bind")
    on = {}
    for lots in lots_grid_eq:
        on[lots] = evaluate("", Params(lots_per_level=lots,
                                       equity_stop_pct=0.06, **geom),
                            m1[::5], 5, 2.0)
        print(f"  lots={lots:<5} RATIO={on[lots]['ratio']:.6f}  "
              f"stops/wk={on[lots]['stops_per_week']:.2f}")
    rv2 = [on[l]["ratio"] for l in lots_grid_eq]
    ok3 = rv2[-1] < rv2[0] - 1e-6      # the test must actually have teeth
    print(f"  RATIO at 0.50 lots ({rv2[-1]:.4f}) < at 0.01 lots ({rv2[0]:.4f})"
          f" -> {'PASS' if ok3 else 'FAIL'}")

    allok = ok1 and ok2 and ok3
    print(f"\n{'ALL PASS' if allok else 'FAILURES PRESENT'}")
    return 0 if allok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--vol", type=float, default=0.08)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return selftest()

    cons, aggr = conservative(), aggressive()

    print("=" * 78)
    print("STATIC ECONOMICS  (independent of any simulation)")
    print("=" * 78)
    for name, p in (("conservative", cons), ("aggressive", aggr)):
        e = economics(p, p.spacing_min)
        print(f"\n{name}:  TP={p.tp_pips}p  lots={p.lots_per_level}  "
              f"spacing={p.spacing_min}p")
        print(f"  round-trip cost   {p.cost_limit_round_trip:.2f} pips "
              f"(LOT-INVARIANT)  -> cost ratio {100*e['cost_ratio']:.1f}%")
        print(f"  net per cycle     {e['net_win_pips']:.2f} pips = "
              f"GBP{e['net_win_pips']*e['gbp_per_pip']:.3f}")
        print(f"  depths            "
              f"{[round(d,2) for d in e['depths']]}  D_max={e['dmax']:.1f}p")
        print(f"  loss at stop      {e['loss_pips']:.1f} pips = "
              f"GBP{e['loss_gbp']:.2f}")
        print(f"  WINS PER STOP     {e['wins_per_stop']:.1f}")

    print("\n" + "=" * 78)
    print(f"SIMULATION  ({args.seeds} seeds x {args.years}y zero-drift GBM, "
          f"identical M1 path per seed)")
    print("=" * 78)

    rows = {"conservative": [], "aggressive": []}
    for seed in range(args.seeds):
        m1 = m1_path(args.years, args.vol, seed)
        rows["conservative"].append(
            evaluate("conservative", cons, m1[::15], 15, args.years))
        rows["aggressive"].append(
            evaluate("aggressive", aggr, m1[::5], 5, args.years))

    hdr = (f"{'preset':<14}{'TP/wk':>8}{'stops/wk':>10}{'win%':>8}"
           f"{'TPs/stop':>10}{'cost(TPs)':>11}{'RATIO':>8}{'GBP/wk':>9}")
    print("\n" + hdr)
    print("-" * len(hdr))
    for name in ("conservative", "aggressive"):
        rs = rows[name]
        f = lambda k: float(np.nanmean([r[k] for r in rs]))
        print(f"{name:<14}{f('tp_per_week'):>8.1f}{f('stops_per_week'):>10.2f}"
              f"{100*f('win_rate'):>8.2f}{f('tps_per_stop'):>10.1f}"
              f"{f('cost_in_tps'):>11.1f}{f('ratio'):>8.2f}"
              f"{f('net_gbp_per_week'):>9.2f}")

    print("\nRATIO spread across seeds (need > 1.0 for genuine edge):")
    for name in ("conservative", "aggressive"):
        v = np.array([r["ratio"] for r in rows[name]], dtype=float)
        v = v[~np.isnan(v)]
        if v.size:
            print(f"  {name:<14} min={v.min():.2f}  median={np.median(v):.2f}"
                  f"  max={v.max():.2f}  n={v.size}")
        else:
            print(f"  {name:<14} no basket stops in any seed -- UNDEFINED")

    print("\n" + "=" * 78)
    print("READING THIS OUTPUT")
    print("=" * 78)
    print("""On zero-edge data BOTH presets must land near the same RATIO, because
Brownian motion is scale-invariant -- and neither may exceed 1.0. If the
aggressive preset shows a much higher TP/week AND a similar RATIO, that is not
edge: it is the same zero-expectancy bet played more times per hour, with the
cost ratio doubled from 10% to 20% and D_max moved from 42 pips (a genuine
outlier) to 15 pips (a routine half-hour move).

The trap to watch for is a HIGHER win rate combined with a LOWER RATIO. That is
the optional-stopping signature: more frequent small wins funded by rarer, and
relatively larger, losses.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
