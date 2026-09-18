#!/usr/bin/env python3
"""
Cointegrated Spread Grid lab -- EUR/USD vs GBP/USD.

WHAT THIS IS FOR
----------------
A grid needs mean reversion. EUR/USD outright may not have any (the evidence is
contested, and variance-ratio tests often cannot reject a random walk). The fix
is to stop gridding a price and start gridding a SPREAD that is mean-reverting
by construction.

THE IDEA
--------
EUR/USD and GBP/USD share the USD leg. A large part of what moves them both is
simply USD strength. Go long one and short the other in the right ratio and the
common USD factor largely cancels. What remains is EUR versus GBP relative
value -- two neighbouring economies with linked trade and correlated policy --
which is economically anchored and therefore a far better mean-reversion
candidate than either leg alone.

THE TRAP THIS SCRIPT CHECKS FIRST  (section 2)
----------------------------------------------
    spread = log(EURUSD) - beta * log(GBPUSD)

If beta == 1 then, by algebra:

    log(EURUSD) - log(GBPUSD) = log(EURUSD / GBPUSD)
                              = log( (EUR/USD) * (USD/GBP) )
                              = log(EUR/GBP)              <-- EUR/GBP !

So at beta = 1 your clever two-leg spread IS just EUR/GBP, and you are paying
TWO sets of transaction costs to synthesise a cross you could trade directly in
one leg. The two-leg structure is only worth its extra cost if beta is
materially different from 1 AND stable over time. This script tests that before
anything else, because getting it wrong doubles your costs for no benefit.

VALIDATION
----------
    python3 spread_grid_lab.py --self-test

Runs on synthetic pairs where the answer is known:
  * truly cointegrated pair      -> must be DETECTED
  * two independent random walks -> must be REJECTED
If it gets those wrong, do not trust it on real data.

REAL DATA
---------
    python3 spread_grid_lab.py --csv-a eurusd_m1.csv --csv-b gbpusd_m1.csv

Each CSV needs a 'close' column (and ideally 'timestamp' so they can be aligned).

Not financial advice.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

PIP = 1e-4
USD_PER_PIP_PER_MICROLOT = 0.10


# ============================================================================
# 1. SYNTHETIC DATA (for validation)
# ============================================================================
def synthetic_cointegrated(n: int = 200_000, beta_true: float = 1.30,
                           ann_vol: float = 0.08, half_life_bars: int = 2000,
                           bars_per_year: int = 252 * 1440,
                           seed: int = 0) -> tuple[np.ndarray, np.ndarray, float]:
    """
    Two series driven by a COMMON stochastic trend (the 'USD factor') plus
    independent stationary noise. Truly cointegrated by construction.

        log_a = w_a * common + s_a
        log_b = w_b * common + s_b
      =>  log_a - (w_a/w_b) * log_b  is stationary,  beta = w_a / w_b
    """
    rng = np.random.default_rng(seed)
    sigma = ann_vol / np.sqrt(bars_per_year)
    common = np.cumsum(rng.normal(0.0, sigma, n))

    theta = np.log(2.0) / half_life_bars
    s_a = np.zeros(n)
    s_b = np.zeros(n)
    sh_a = rng.normal(0.0, sigma * 0.6, n)
    sh_b = rng.normal(0.0, sigma * 0.6, n)
    for i in range(1, n):
        s_a[i] = s_a[i - 1] * (1 - theta) + sh_a[i]
        s_b[i] = s_b[i - 1] * (1 - theta) + sh_b[i]

    w_b = 1.0
    w_a = beta_true * w_b
    a = 1.1500 * np.exp(w_a * common + s_a)
    b = 1.3400 * np.exp(w_b * common + s_b)
    return a, b, beta_true


def synthetic_independent(n: int = 200_000, ann_vol: float = 0.08,
                          bars_per_year: int = 252 * 1440,
                          seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Two independent random walks. NOT cointegrated. Control case."""
    rng = np.random.default_rng(seed)
    sigma = ann_vol / np.sqrt(bars_per_year)
    a = 1.1500 * np.exp(np.cumsum(rng.normal(0.0, sigma, n)))
    b = 1.3400 * np.exp(np.cumsum(rng.normal(0.0, sigma, n)))
    return a, b


# ============================================================================
# 2. HEDGE RATIO, THE beta==1 CHECK, COINTEGRATION, HALF-LIFE
# ============================================================================
def hedge_ratio(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """OLS of log(a) on log(b): log_a = alpha + beta*log_b + resid."""
    la, lb = np.log(a), np.log(b)
    X = np.column_stack([np.ones_like(lb), lb])
    coef, *_ = np.linalg.lstsq(X, la, rcond=None)
    return float(coef[1]), float(coef[0])      # beta, alpha


def spread_series(a: np.ndarray, b: np.ndarray, beta: float,
                  alpha: float = 0.0) -> np.ndarray:
    return np.log(a) - beta * np.log(b) - alpha


def beta_equals_one_check(beta: float, tol: float = 0.05) -> dict:
    """
    THE decisive practical test. If beta ~ 1, the two-leg spread is just
    EUR/GBP and the second leg is pure extra cost.
    """
    is_one = abs(beta - 1.0) <= tol
    return {
        "beta": beta,
        "beta_is_one": is_one,
        "recommendation": (
            "TRADE EUR/GBP DIRECTLY -- beta is indistinguishable from 1, so the "
            "two-leg spread is algebraically EUR/GBP with double the costs."
            if is_one else
            f"Two-leg structure justified: beta={beta:.3f} differs from 1. "
            "Verify beta STABILITY before relying on it."
        ),
    }


def cointegration_test(resid: np.ndarray, max_points: int = 60_000) -> dict:
    """
    ADF on the regression residual (Engle-Granger step 2).
    H0 = unit root = NOT cointegrated. We want to REJECT H0 (p < 0.05).
    Subsampled for tractability; ADF is asymptotic.
    """
    x = resid
    if len(x) > max_points:
        x = x[:: max(len(x) // max_points, 1)]
    stat, p, _, _, crit, _ = adfuller(x, autolag="AIC")
    return {
        "adf_stat": float(stat),
        "p_value": float(p),
        "crit_5pct": float(crit["5%"]),
        "cointegrated": bool(p < 0.05),
        "n_used": len(x),
    }


def half_life(resid: np.ndarray) -> float:
    """
    OU fit: d(s) = a + b*s_{lag} + eps ;  half-life = -ln2 / ln(1+b).
    Returns np.inf when the series shows no reversion.
    """
    s_lag = resid[:-1]
    ds = np.diff(resid)
    X = np.column_stack([np.ones_like(s_lag), s_lag])
    coef, *_ = np.linalg.lstsq(X, ds, rcond=None)
    b = float(coef[1])
    if b >= 0 or b <= -1:
        return float("inf")
    return float(-np.log(2.0) / np.log(1.0 + b))


def rolling_stability(a: np.ndarray, b: np.ndarray, n_windows: int = 10) -> pd.DataFrame:
    """
    Split the sample and re-estimate beta / ADF / half-life in each block.

    THIS IS THE RISK CONTROL THAT PRICE-GRIDS CANNOT HAVE. Cointegration
    breakdown is a TESTABLE EVENT -- beta drifting or ADF ceasing to reject --
    and it can fire BEFORE the P&L tells you. Brexit did exactly this to
    EUR/GBP in 2016.
    """
    n = len(a)
    size = n // n_windows
    rows = []
    for w in range(n_windows):
        s, e = w * size, (w + 1) * size
        aa, bb = a[s:e], b[s:e]
        beta, alpha = hedge_ratio(aa, bb)
        resid = spread_series(aa, bb, beta, alpha)
        ct = cointegration_test(resid)
        rows.append({
            "window": w + 1,
            "beta": round(beta, 3),
            "adf_p": round(ct["p_value"], 4),
            "coint": "YES" if ct["cointegrated"] else "no",
            "half_life_bars": (round(half_life(resid), 0)
                               if np.isfinite(half_life(resid)) else np.inf),
            "spread_sd": round(float(np.std(resid)), 5),
        })
    return pd.DataFrame(rows)


def zscore(resid: np.ndarray, window: int = 5000) -> np.ndarray:
    s = pd.Series(resid)
    mu = s.rolling(window, min_periods=window // 2).mean()
    sd = s.rolling(window, min_periods=window // 2).std()
    return ((s - mu) / sd).to_numpy()


# ============================================================================
# 3. TWO-LEG COST MODEL
# ============================================================================
@dataclass
class TwoLegCost:
    """
    A spread trade opens and closes TWO positions. Every cost doubles.
    GBP/USD is typically wider than EUR/USD, so do not assume symmetry.
    """
    comm_pips_per_side_a: float = 0.20
    comm_pips_per_side_b: float = 0.20
    spread_pips_a: float = 0.10
    spread_pips_b: float = 0.40          # GBP/USD is usually wider
    slippage_pips_per_fill: float = 0.05

    @property
    def round_trip_pips_total(self) -> float:
        leg_a = 2 * self.comm_pips_per_side_a + self.spread_pips_a + 2 * self.slippage_pips_per_fill
        leg_b = 2 * self.comm_pips_per_side_b + self.spread_pips_b + 2 * self.slippage_pips_per_fill
        return leg_a + leg_b


def spacing_to_pips(z_spacing: float, spread_sd: float, price: float = 1.15) -> float:
    """
    Convert a z-score grid spacing into equivalent pips on the EUR leg, so it
    can be compared against transaction cost.

    z_spacing * spread_sd  = move in log-spread units (~ relative return)
    times price / PIP      = pips on the quote leg
    """
    return z_spacing * spread_sd * price / PIP


# ============================================================================
# 4. GRID ON THE Z-SCORE
# ============================================================================
@dataclass
class ZGridConfig:
    """
    Basket stop sizing matters and is easy to get wrong.

    With `max_levels` L at spacing s, once price reaches z the aggregate
    adverse excursion is about  L*|z| - s*L(L+1)/2.  With L=6, s=0.5 that is
    already -7.5 at z=-3 -- so a basket stop of 4.0 would fire on an ENTIRELY
    NORMAL z-excursion, churning the account. Defaults below are set so the
    stop fires around |z| ~ 3.2, i.e. on genuine breakdown rather than on
    ordinary oscillation.
    """
    z_spacing: float = 0.5
    max_levels: int = 4            # +/- 2.0 sigma at 0.5 spacing
    z_take_profit: float = 0.5
    basket_stop_z: float = 8.0     # total adverse z across open units
    time_stop_bars: Optional[int] = None   # set to ~2x half-life
    cooldown_bars: int = 500


@dataclass
class ZGridResult:
    realized_z: float = 0.0
    n_round_trips: int = 0
    n_wins: int = 0
    n_basket_stops: int = 0
    n_time_stops: int = 0
    max_adverse_z: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.n_wins / self.n_round_trips if self.n_round_trips else float("nan")

    @property
    def return_over_mae(self) -> float:
        return (self.realized_z / self.max_adverse_z
                if self.max_adverse_z > 0 else float("nan"))


def simulate_z_grid(z: np.ndarray, cfg: ZGridConfig,
                    cost_z: float = 0.0) -> ZGridResult:
    """
    Grid the z-score around 0, which is the spread's estimated fair value.

    Key structural advantage over a price grid: the mean is not an assumption,
    it is an ESTIMATE, and the exit criterion (z -> 0) comes from the same
    model that generated the entry. A price grid has no such anchor.

    Short the spread at positive z, long at negative z. Take profit one level
    back toward zero.
    """
    z = np.asarray(z, dtype=float)
    res = ZGridResult()
    longs: dict[int, float] = {}    # level k -> entry z
    shorts: dict[int, float] = {}
    open_bar: dict[tuple[str, int], int] = {}
    cooldown = 0
    s = cfg.z_spacing
    tp = cfg.z_take_profit

    for i, zi in enumerate(z):
        if not np.isfinite(zi):
            continue
        if cooldown > 0:
            cooldown -= 1
            continue

        # ---- take profit ---------------------------------------------------
        for k in [k for k, e in longs.items() if zi - e >= tp]:
            del longs[k]; open_bar.pop(("L", k), None)
            res.realized_z += tp - cost_z
            res.n_round_trips += 1; res.n_wins += 1
        for k in [k for k, e in shorts.items() if e - zi >= tp]:
            del shorts[k]; open_bar.pop(("S", k), None)
            res.realized_z += tp - cost_z
            res.n_round_trips += 1; res.n_wins += 1

        # ---- open levels: buy below 0, sell above 0 ------------------------
        if zi < 0:
            depth = int(-zi / s)
            for k in range(1, min(depth, cfg.max_levels) + 1):
                if k not in longs:
                    longs[k] = -k * s
                    open_bar[("L", k)] = i
        if zi > 0:
            depth = int(zi / s)
            for k in range(1, min(depth, cfg.max_levels) + 1):
                if k not in shorts:
                    shorts[k] = k * s
                    open_bar[("S", k)] = i

        # ---- unrealized ----------------------------------------------------
        unreal = sum(zi - e for e in longs.values()) + sum(e - zi for e in shorts.values())
        if unreal < -res.max_adverse_z:
            res.max_adverse_z = -unreal

        # ---- time stop (spread failed to revert within ~2x half-life) ------
        if cfg.time_stop_bars is not None:
            stale = [key for key, bar in open_bar.items()
                     if i - bar > cfg.time_stop_bars]
            for key in stale:
                side, k = key
                book = longs if side == "L" else shorts
                if k in book:
                    entry = book.pop(k)
                    pnl = (zi - entry) if side == "L" else (entry - zi)
                    res.realized_z += pnl - cost_z
                    res.n_round_trips += 1
                    res.n_wins += int(pnl > 0)
                    res.n_time_stops += 1
                open_bar.pop(key, None)

        # ---- basket stop ---------------------------------------------------
        if unreal <= -cfg.basket_stop_z:
            held = len(longs) + len(shorts)
            res.realized_z += unreal - cost_z * held
            res.n_round_trips += held
            res.n_basket_stops += 1
            longs, shorts, open_bar = {}, {}, {}
            cooldown = cfg.cooldown_bars

    return res


def surrogate_test_spread(resid: np.ndarray, cfg: ZGridConfig, cost_z: float,
                          z_window: int = 5000, n_surrogates: int = 10,
                          seed: int = 0) -> dict:
    """
    Shuffle the spread's INCREMENTS. Destroys mean reversion, preserves the
    distribution. A real cointegration edge must vanish in the surrogates.
    """
    rng = np.random.default_rng(seed)
    real = simulate_z_grid(zscore(resid, z_window), cfg, cost_z)
    d = np.diff(resid)
    stats = []
    for _ in range(n_surrogates):
        shuf = np.concatenate([[resid[0]], resid[0] + np.cumsum(rng.permutation(d))])
        r = simulate_z_grid(zscore(shuf, z_window), cfg, cost_z)
        stats.append(r.return_over_mae)
    arr = np.asarray(stats, dtype=float)
    fin = arr[np.isfinite(arr)]
    rr = real.return_over_mae
    p = float(np.mean(fin >= rr)) if fin.size and np.isfinite(rr) else float("nan")
    return {"real": real, "real_rom": rr,
            "surr_mean": float(np.mean(fin)) if fin.size else float("nan"),
            "p_value": p}


# ============================================================================
# 5. REPORT
# ============================================================================
def _rule(ch="=", n=78):
    print(ch * n)


def full_report(a: np.ndarray, b: np.ndarray, label: str,
                cost: TwoLegCost, z_window: int = 5000,
                n_surrogates: int = 10):
    _rule()
    print(f"COINTEGRATED SPREAD GRID REPORT -- {label}")
    _rule()
    print(f"  bars: {len(a):,}\n")

    # --- step 1: hedge ratio & the beta==1 trap -----------------------------
    beta, alpha = hedge_ratio(a, b)
    chk = beta_equals_one_check(beta)
    print("STEP 1 -- HEDGE RATIO AND THE beta==1 TRAP")
    print(f"  beta (OLS)     : {beta:.4f}")
    print(f"  beta == 1 ?    : {'YES' if chk['beta_is_one'] else 'no'}")
    print(f"  -> {chk['recommendation']}\n")

    # demonstrate the algebra numerically
    synth_cross = a / b
    spread_b1 = np.log(a) - np.log(b)
    print(f"  algebra check: log(A)-log(B) vs log(A/B) max diff = "
          f"{np.max(np.abs(spread_b1 - np.log(synth_cross))):.2e}")
    print("  (identical -- confirms beta=1 spread IS the cross rate)\n")

    # --- step 2: cointegration ---------------------------------------------
    resid = spread_series(a, b, beta, alpha)
    ct = cointegration_test(resid)
    hl = half_life(resid)
    sd = float(np.std(resid))
    print("STEP 2 -- IS THE SPREAD ACTUALLY STATIONARY?")
    print(f"  ADF stat       : {ct['adf_stat']:.3f}   (5% crit {ct['crit_5pct']:.3f})")
    print(f"  ADF p-value    : {ct['p_value']:.4f}")
    print(f"  COINTEGRATED   : {'YES' if ct['cointegrated'] else 'NO -- STOP HERE'}")
    print(f"  half-life      : {hl:,.0f} bars"
          f"{'' if np.isfinite(hl) else '  (no reversion)'}")
    print(f"  spread sd      : {sd:.5f}\n")

    # --- step 3: economics --------------------------------------------------
    print("STEP 3 -- GRID SPACING vs TWO-LEG COST")
    rt = cost.round_trip_pips_total
    print(f"  two-leg round-trip cost : {rt:.2f} pips"
          f"  (= ${rt * USD_PER_PIP_PER_MICROLOT:.3f} per 0.01 lot/leg)")
    print(f"  {'z spacing':>10} {'= pips':>9} {'cost %':>9} {'verdict':>10}")
    print("  " + "-" * 42)
    for zs in (0.25, 0.5, 1.0, 1.5):
        pips = spacing_to_pips(zs, sd)
        ratio = rt / pips if pips > 0 else float("inf")
        v = "FATAL" if ratio > 0.30 else ("MARGINAL" if ratio > 0.12 else "OK")
        print(f"  {zs:>9.2f}s {pips:>8.1f}p {ratio * 100:>8.1f}% {v:>10}")
    print()

    # --- step 4: stability --------------------------------------------------
    print("STEP 4 -- STABILITY ACROSS SUB-PERIODS  (the real risk)")
    df = rolling_stability(a, b, n_windows=10)
    print(df.to_string(index=False))
    n_ok = int((df["coint"] == "YES").sum())
    bmin, bmax = df["beta"].min(), df["beta"].max()
    print(f"\n  cointegrated in {n_ok}/10 windows;  beta range {bmin:.2f} to {bmax:.2f}")
    if n_ok < 7:
        print("  -> UNSTABLE. Relationship is not dependable. Do not fund.")
    elif (bmax - bmin) > 0.5:
        print("  -> beta drifts materially. Re-estimate often; size down.")
    else:
        print("  -> reasonably stable over this sample.")
    print()

    # --- step 5: surrogate test --------------------------------------------
    print("STEP 5 -- SURROGATE TEST  <<< THE DECIDING RESULT")
    cost_z = (rt * PIP / 1.15) / sd if sd > 0 else 0.0   # cost in z units
    cfg = ZGridConfig(
        z_spacing=0.5, max_levels=4, z_take_profit=0.5, basket_stop_z=8.0,
        time_stop_bars=int(2 * hl) if np.isfinite(hl) else None,
    )
    print(f"  cost per round trip in z units: {cost_z:.4f}")
    out = surrogate_test_spread(resid, cfg, cost_z, z_window, n_surrogates)
    r = out["real"]
    print(f"  trips={r.n_round_trips}  win={r.win_rate * 100:.1f}%  "
          f"basket_stops={r.n_basket_stops}  time_stops={r.n_time_stops}")
    print(f"  real ret/MAE = {out['real_rom']:.3f}   "
          f"shuffled = {out['surr_mean']:.3f}   p = {out['p_value']:.2f}")
    p = out["p_value"]
    if not np.isfinite(p):
        verdict = "INCONCLUSIVE"
    elif p > 0.20:
        verdict = "NO EDGE -- same as shuffled. The cointegration is not tradeable."
    elif p > 0.05:
        verdict = "WEAK / UNPROVEN -- do not fund."
    else:
        verdict = "SIGNAL PRESENT -- proceed to holdout + live-cost testing."
    print(f"  -> {verdict}")
    _rule()
    print()


def self_test(n: int = 120_000):
    _rule("#")
    print("SELF-TEST -- synthetic pairs with KNOWN answers")
    _rule("#")
    print("Expected: cointegrated pair -> DETECTED.  independent -> REJECTED.\n")
    print("NOTE ON ADF POWER: the test needs the sample to span MANY half-lives.\n"
          "A 2000-bar half-life inside a 12000-bar window is only 6 cycles and\n"
          "ADF will fail to reject even when cointegration is real. Here we use a\n"
          "300-bar half-life so power is adequate. Remember this when reading\n"
          "real-data output: a 'no' can mean 'not enough cycles', not 'no relationship'.\n")
    free = TwoLegCost(0, 0, 0, 0, 0)

    a, b, bt = synthetic_cointegrated(n, beta_true=1.30, half_life_bars=300, seed=3)
    print(f">>> CASE 1: truly cointegrated, beta_true = {bt}")
    full_report(a, b, "SYNTHETIC cointegrated", free, z_window=3000, n_surrogates=8)

    a2, b2 = synthetic_independent(n, seed=3)
    print(">>> CASE 2: two independent random walks (must be rejected)")
    full_report(a2, b2, "SYNTHETIC independent", free, z_window=3000, n_surrogates=8)


# ============================================================================
# 6. MAIN
# ============================================================================
def load_close(path: str) -> tuple[np.ndarray, Optional[pd.Series]]:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    if "close" in cols:
        px = df[cols["close"]].to_numpy(dtype=float)
    elif "bid" in cols and "ask" in cols:
        px = ((df[cols["bid"]] + df[cols["ask"]]) / 2).to_numpy(dtype=float)
    else:
        raise SystemExit(f"{path}: need 'close', or both 'bid' and 'ask'.")
    ts = df[cols["timestamp"]] if "timestamp" in cols else None
    return px, ts


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cointegrated spread grid lab")
    ap.add_argument("--csv-a", help="EUR/USD minute bars")
    ap.add_argument("--csv-b", help="GBP/USD minute bars")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--z-window", type=int, default=5000)
    ap.add_argument("--surrogates", type=int, default=10)
    ap.add_argument("--spread-b", type=float, default=0.40,
                    help="avg GBP/USD spread in pips")
    args = ap.parse_args(argv)

    if args.self_test:
        self_test()
        return 0

    if not (args.csv_a and args.csv_b):
        ap.error("supply --csv-a and --csv-b, or use --self-test")

    a, ts_a = load_close(args.csv_a)
    b, ts_b = load_close(args.csv_b)
    if ts_a is not None and ts_b is not None:
        df = pd.merge(pd.DataFrame({"t": ts_a, "a": a}),
                      pd.DataFrame({"t": ts_b, "b": b}), on="t", how="inner")
        a, b = df["a"].to_numpy(), df["b"].to_numpy()
        print(f"aligned on timestamp: {len(a):,} common bars\n")
    else:
        m = min(len(a), len(b))
        a, b = a[:m], b[:m]
        print(f"WARNING: no timestamps -- truncated to {m:,} bars. "
              f"Misalignment will corrupt the hedge ratio.\n")

    cost = TwoLegCost(spread_pips_b=args.spread_b)
    full_report(a, b, f"{args.csv_a} vs {args.csv_b}", cost,
                z_window=args.z_window, n_surrogates=args.surrogates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
