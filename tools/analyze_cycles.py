#!/usr/bin/env python3
"""
Analyse the CSV telemetry written by Harvester5Pip.mq5.

Reads:
    Harvester_<SYMBOL>_<MAGIC>_cycles.csv     one row per basket cycle
    Harvester_<SYMBOL>_<MAGIC>_deals.csv      one row per ENTRY / exit deal

Produces the numbers that actually decide whether the harvester works:

  1. RATIO  -- take-profits per stop-out, divided by the cost of a stop-out
               expressed in take-profit units.

                   RATIO > 1.0  =>  the geometry pays for its own stop-outs

               Calibration: on zero-edge synthetic data this sits at ~0.35,
               and it stayed in 0.31-0.39 across all 64 geometry combinations
               tested. So spacing / level count / basket width move drawdown
               and fill frequency, NOT expectancy. On live data you need >1.0,
               and the gap from 0.35 is the mean reversion the market must supply.

  2. MEASURED LIMIT SLIPPAGE -- the blueprint assumed 0.0 pips on resting
               limits. This checks that assumption against real fills. If
               median entry slip is materially above zero, the 10% cost ratio
               is wrong and every downstream number moves.

  3. REGIME BREAKDOWN -- cycle outcome bucketed by the Efficiency Ratio
               recorded at arm time, which is what the ER gate is betting on.

Usage:
    python3 analyze_cycles.py --dir /path/to/MQL5/Files
    python3 analyze_cycles.py --cycles cycles.csv --deals deals.csv
    python3 analyze_cycles.py --dir . --net-win-usd 0.45
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd


def _rule(ch="=", n=78):
    print(ch * n)


def find_files(directory: str) -> tuple[str | None, str | None]:
    c = sorted(glob.glob(os.path.join(directory, "*_cycles.csv")))
    d = sorted(glob.glob(os.path.join(directory, "*_deals.csv")))
    return (c[0] if c else None), (d[0] if d else None)


def load_cycles(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in ("arm_utc", "close_utc"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce",
                                     format="%Y.%m.%d %H:%M:%S")
    return df


# ---------------------------------------------------------------------------
# 1. THE RATIO
# ---------------------------------------------------------------------------
def report_ratio(cyc: pd.DataFrame, net_win_usd: float):
    _rule()
    print("1. RATIO -- does the geometry pay for its own stop-outs?")
    _rule()

    stopped_mask = cyc["close_reason"].astype(str).str.startswith("basket") | \
                   cyc["close_reason"].astype(str).str.contains("SL", case=False)
    stopped = cyc[stopped_mask]
    clean = cyc[~stopped_mask]

    total_tp = int(cyc["n_tp"].sum())
    n_stop = len(stopped)

    print(f"  cycles total            : {len(cyc):,}")
    print(f"  cycles ended clean      : {len(clean):,}")
    print(f"  cycles ended on a stop  : {n_stop:,}")
    print(f"  take-profits total      : {total_tp:,}")

    if n_stop == 0:
        print("\n  No stop-outs recorded yet.")
        print("  NOTE: a basket stop that never fires is mis-parameterised,")
        print("        not safe. Keep running, or verify InpBasketMult.")
        return

    tp_per_stop = total_tp / n_stop
    avg_stop_loss = float(stopped["pl_at_close"].abs().mean())
    cost_in_tps = avg_stop_loss / net_win_usd if net_win_usd > 0 else np.nan
    ratio = tp_per_stop / cost_in_tps if cost_in_tps > 0 else np.nan

    print()
    print(f"  take-profits per stop-out   : {tp_per_stop:8.2f}")
    print(f"  avg loss per stop-out       : ${avg_stop_loss:8.2f}")
    print(f"  net gain per take-profit    : ${net_win_usd:8.2f}")
    print(f"  stop-out cost in TP units   : {cost_in_tps:8.2f}")
    print()
    print(f"  >>> RATIO = {ratio:.3f}")
    print(f"      reference: ~0.35 on zero-edge data, need > 1.00")

    if not np.isfinite(ratio):
        verdict = "INCONCLUSIVE"
    elif ratio >= 1.0:
        verdict = "VIABLE on this sample -- verify on a holdout period"
    elif ratio >= 0.7:
        verdict = "BELOW BREAK-EVEN but above the zero-edge baseline"
    elif ratio >= 0.45:
        verdict = "WEAK -- only marginally above the zero-edge baseline (~0.35)"
    else:
        verdict = "AT OR BELOW ZERO-EDGE BASELINE -- no mean reversion captured"
    print(f"      -> {verdict}")

    realized = cyc["pl_at_close"].sum()
    print(f"\n  cumulative pl_at_close      : ${realized:,.2f}")
    if "max_adverse_pips" in cyc.columns:
        print(f"  worst excursion observed    : "
              f"{cyc['max_adverse_pips'].max():.1f} pips")
    print(f"  deepest level reached       : {int(cyc['max_level'].max())}")


# ---------------------------------------------------------------------------
# 2. SLIPPAGE -- test the blueprint's zero-slippage assumption
# ---------------------------------------------------------------------------
def report_slippage(deals: pd.DataFrame):
    _rule()
    print("2. MEASURED LIMIT SLIPPAGE -- was the zero-slippage assumption right?")
    _rule()

    entries = deals[deals["event"] == "ENTRY"].copy()
    entries["slip_pips"] = pd.to_numeric(entries["slip_pips"], errors="coerce")
    s = entries["slip_pips"].dropna()

    if s.empty:
        print("  no ENTRY rows with slippage data yet")
        return

    print(f"  entry fills        : {len(s):,}")
    print(f"  mean slip          : {s.mean():.3f} pips")
    print(f"  median slip        : {s.median():.3f} pips")
    print(f"  p95 slip           : {s.quantile(0.95):.3f} pips")
    print(f"  max slip           : {s.max():.3f} pips")
    print(f"  fills with 0 slip  : {(s == 0).mean() * 100:.1f}%")

    median = s.median()
    assumed_cost = 0.50          # blueprint: 2x0.20 commission + 0.10 spread
    real_cost = assumed_cost + median
    print()
    print(f"  blueprint assumed round-trip cost : {assumed_cost:.2f} pips "
          f"(10.0% of a 5-pip target)")
    print(f"  with measured median slip         : {real_cost:.2f} pips "
          f"({real_cost / 5.0 * 100:.1f}% of a 5-pip target)")
    if median > 0.15:
        print("  -> Slippage is material. Recompute the cost ratio and expect")
        print("     every downstream figure to move against you.")
    elif median > 0.05:
        print("  -> Mild slippage. Cost ratio drifts but stays workable.")
    else:
        print("  -> Zero-slippage assumption holds. Resting limits behaving.")

    if "hold_secs" in deals.columns:
        tp = deals[deals["event"] == "TP_EXIT"].copy()
        tp["hold_secs"] = pd.to_numeric(tp["hold_secs"], errors="coerce")
        h = tp["hold_secs"].dropna()
        if not h.empty:
            print(f"\n  time-to-TP  median {h.median() / 60:.1f} min | "
                  f"p90 {h.quantile(0.90) / 60:.1f} min | "
                  f"max {h.max() / 3600:.1f} h")

    if "level" in entries.columns:
        print("\n  fills by level (does the deep level actually fill?):")
        for lv, cnt in entries["level"].value_counts().sort_index().items():
            share = cnt / len(entries) * 100
            flag = "  <-- rarely fills, likely decorative" if share < 5 else ""
            print(f"    L{int(lv)}: {cnt:>6,}  ({share:4.1f}%){flag}")


# ---------------------------------------------------------------------------
# 3. REGIME BREAKDOWN -- is the ER gate earning its place?
# ---------------------------------------------------------------------------
def report_regime(cyc: pd.DataFrame):
    _rule()
    print("3. OUTCOME BY EFFICIENCY RATIO AT ARM TIME")
    _rule()
    if "er_at_arm" not in cyc.columns:
        print("  er_at_arm not present")
        return

    df = cyc.copy()
    df["er_at_arm"] = pd.to_numeric(df["er_at_arm"], errors="coerce")
    df = df.dropna(subset=["er_at_arm"])
    if df.empty:
        print("  no ER data")
        return

    bins = [0, 0.15, 0.25, 0.35, 0.50, 1.01]
    labels = ["<0.15", "0.15-0.25", "0.25-0.35", "0.35-0.50", ">0.50"]
    df["bucket"] = pd.cut(df["er_at_arm"], bins=bins, labels=labels)

    print(f"  {'ER bucket':>11} {'cycles':>8} {'avg TPs':>9} "
          f"{'avg pl':>10} {'stop rate':>10}")
    print("  " + "-" * 52)
    for b in labels:
        g = df[df["bucket"] == b]
        if g.empty:
            continue
        stops = g["close_reason"].astype(str).str.startswith("basket").mean()
        print(f"  {b:>11} {len(g):>8,} {g['n_tp'].mean():>9.2f} "
              f"${g['pl_at_close'].mean():>9.2f} {stops * 100:>9.1f}%")
    print("\n  The ER gate assumes low ER is better. If avg pl does not fall")
    print("  as ER rises, the gate is not earning its complexity -- consider")
    print("  widening InpERFull rather than tightening it.")


def report_monthly(cyc: pd.DataFrame):
    if "close_utc" not in cyc.columns or cyc["close_utc"].isna().all():
        return
    _rule()
    print("4. MONTHLY -- consistency matters more than the total")
    _rule()
    df = cyc.dropna(subset=["close_utc"]).copy()
    df["month"] = df["close_utc"].dt.to_period("M")
    g = df.groupby("month").agg(
        cycles=("cycle_id", "count"),
        tps=("n_tp", "sum"),
        stops=("close_reason",
               lambda s: s.astype(str).str.startswith("basket").sum()),
        pl=("pl_at_close", "sum"),
    )
    print(f"  {'month':>9} {'cycles':>8} {'TPs':>7} {'stops':>7} {'pl':>11}")
    print("  " + "-" * 46)
    for m, r in g.iterrows():
        print(f"  {str(m):>9} {int(r['cycles']):>8,} {int(r['tps']):>7,} "
              f"{int(r['stops']):>7,} ${r['pl']:>10.2f}")
    pos = (g["pl"] > 0).sum()
    print(f"\n  profitable months: {pos}/{len(g)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Analyse harvester CSV telemetry")
    ap.add_argument("--dir", help="folder holding the CSVs (MQL5/Files)")
    ap.add_argument("--cycles", help="explicit path to *_cycles.csv")
    ap.add_argument("--deals", help="explicit path to *_deals.csv")
    ap.add_argument("--net-win-usd", type=float, default=0.45,
                    help="net profit per take-profit (default 0.45 = "
                         "4.5 pips on 0.01 lot)")
    a = ap.parse_args(argv)

    cyc_path, deal_path = a.cycles, a.deals
    if a.dir:
        fc, fd = find_files(a.dir)
        cyc_path = cyc_path or fc
        deal_path = deal_path or fd

    if not cyc_path or not os.path.exists(cyc_path):
        print("No cycles CSV found. Pass --dir or --cycles.\n"
              "The EA writes to MQL5\\Files (or Terminal\\Common\\Files when\n"
              "InpCsvCommonFolder is true).")
        return 1

    cyc = load_cycles(cyc_path)
    print(f"cycles : {cyc_path}  ({len(cyc):,} rows)")
    if deal_path and os.path.exists(deal_path):
        deals = pd.read_csv(deal_path)
        print(f"deals  : {deal_path}  ({len(deals):,} rows)")
    else:
        deals = None
        print("deals  : not found (slippage section will be skipped)")
    print()

    report_ratio(cyc, a.net_win_usd)
    print()
    if deals is not None and len(deals):
        report_slippage(deals)
        print()
    report_regime(cyc)
    print()
    report_monthly(cyc)
    print()
    _rule()
    print("Read RATIO first. Everything else explains it.")
    _rule()
    return 0


if __name__ == "__main__":
    sys.exit(main())
