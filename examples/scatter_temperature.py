"""Scatter plots showing where temperature dependencies bite.

Reads the per-sample (component, metric) pairs from the sqlite caches
that ``temperature_circuits.py`` populated, then for each circuit
plots:

- The binding metric vs T across every MC sample (the headline T
  effect, with pass/fail colouring).
- The binding metric vs the dominant component predictor, faceted
  by T corner (cold / room / hot). The corner-coloured cloud shift
  shows whether T bites by drifting the whole population (mean
  shift) or by widening the sensitivity coefficient (cloud rotates
  / fans out at the corner).

Run ``temperature_circuits.py`` first to populate the caches.
Saves charts at ``/tmp/temp_scatter_<name>.png``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load_cache(path: str):
    """Returns list of (input_dict, output_dict) pairs from the cache.
    Loads every row across all signatures — caches contain a single
    signature per file in this workflow, so no filtering needed."""
    db = sqlite3.connect(path)
    rows = []
    for key, value in db.execute("SELECT key, value FROM cache").fetchall():
        inputs = dict(json.loads(key))
        outputs = json.loads(value)
        rows.append((inputs, outputs))
    db.close()
    return rows


def to_arrays(rows, input_keys, output_keys):
    n = len(rows)
    inp = {k: np.full(n, np.nan) for k in input_keys}
    out = {k: np.full(n, np.nan) for k in output_keys}
    for i, (in_d, out_d) in enumerate(rows):
        for k in input_keys:
            if k in in_d:
                inp[k][i] = in_d[k]
        for k in output_keys:
            if k in out_d:
                out[k][i] = out_d[k]
    return inp, out


def _nearest_T(T_array, target, tol=0.5, min_count=5):
    """Pick the T value closest to ``target`` that's actually in the
    cache *and* has ≥ min_count samples (so the singleton nominal
    call at T=25 doesn't masquerade as the corner). Mask samples
    within ``tol`` of it."""
    Ts, counts = np.unique(T_array[np.isfinite(T_array)],
                            return_counts=True)
    Ts = Ts[counts >= min_count]
    if len(Ts) == 0:
        return None, np.zeros_like(T_array, dtype=bool)
    nearest = float(Ts[np.argmin(np.abs(Ts - target))])
    return nearest, np.abs(T_array - nearest) < tol


def _correlations(inp, metric, mask, predictor_keys):
    """Pearson ρ between each predictor and the metric, restricted to
    the masked samples."""
    out = {}
    y = metric[mask]
    for k in predictor_keys:
        x = inp[k][mask]
        m = np.isfinite(x) & np.isfinite(y)
        if m.sum() > 5 and x[m].std() > 0:
            out[k] = float(np.corrcoef(x[m], y[m])[0, 1])
    return out


def _scatter_metric_vs_T(ax, T, metric, pass_mask, ylabel, spec_lines,
                          marker_size=3, alpha=0.30, subsample_per_T=None):
    # Jitter T slightly so per-corner stripes spread visually instead of
    # piling up at a single x. Fixed seed keeps it reproducible.
    rng = np.random.default_rng(0)
    if subsample_per_T is not None:
        # Per-T-band subsample so each corner gets at most N points,
        # keeping the visual density honest across corners.
        keep = np.zeros_like(T, dtype=bool)
        for T_val in np.unique(T[np.isfinite(T)]):
            band = np.where(np.abs(T - T_val) < 0.5)[0]
            if band.size > subsample_per_T:
                pick = rng.choice(band, subsample_per_T, replace=False)
                keep[pick] = True
            else:
                keep[band] = True
        T = T[keep]
        metric = metric[keep]
        pass_mask = pass_mask[keep]
    jitter = rng.uniform(-1.0, 1.0, size=T.shape)
    Tj = T + jitter
    ax.scatter(Tj[pass_mask], metric[pass_mask], s=marker_size, alpha=alpha,
               color="C0", label="pass")
    ax.scatter(Tj[~pass_mask], metric[~pass_mask], s=marker_size+1,
               alpha=min(1.0, alpha+0.2),
               color="C3", label="fail")
    for value, color, ls, label in spec_lines:
        ax.axhline(value, color=color, lw=0.8, ls=ls, label=label)
    ax.set_xlabel("T [°C]")
    ax.set_ylabel(ylabel)
    ax.legend(fontsize=8, loc="best")
    ax.grid(True, alpha=0.3)


def _scatter_metric_vs_predictor(ax, predictor_values, metric_values, T,
                                  T_targets, ylabel, predictor_label,
                                  spec_lines, rho, marker_size=10, alpha=0.55,
                                  subsample=None):
    colors = {-40: "C0", 25: "C2", 85: "C3"}
    rng = np.random.default_rng(0)
    for T_nominal in T_targets:
        T_actual, mask = _nearest_T(T, T_nominal)
        if T_actual is None or not mask.any():
            continue
        c = colors.get(T_nominal, "C1")
        x = predictor_values[mask]
        y = metric_values[mask]
        if subsample is not None and x.size > subsample:
            idx = rng.choice(x.size, subsample, replace=False)
            x = x[idx]; y = y[idx]
        ax.scatter(x, y, s=marker_size, alpha=alpha, color=c,
                   label=f"T = {T_actual:+.0f}°C  (n={mask.sum()})")
    for value, color, ls, label in spec_lines:
        ax.axhline(value, color=color, lw=0.8, ls=ls, label=label)
    ax.set_xlabel(predictor_label)
    ax.set_ylabel(ylabel)
    ax.set_title(f"vs {predictor_label}  (room-T ρ = {rho:+.2f})")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)


def scatter_wien():
    rows = load_cache("/tmp/temp_wien.sqlite")
    if not rows:
        print("wien cache empty — run temperature_circuits.chart_wien first")
        return
    inp_keys = ["R1","R2","C1","C2","Rg","Rfa","Rfb",
                "U1_Vos","U1_Ib","U1_Avol","U1_GBW",
                "Q1_BF","Q2_BF","T"]
    out_keys = ["t1","t2","amp_max","amp_min","f_new","thd_db","a_rms"]
    inp, out = to_arrays(rows, inp_keys, out_keys)
    v_pp = out["amp_max"] - out["amp_min"]
    T = inp["T"]
    finite = np.isfinite(v_pp) & np.isfinite(T)
    inp = {k: v[finite] for k, v in inp.items()}
    out = {k: v[finite] for k, v in out.items()}
    v_pp = v_pp[finite]
    T = T[finite]

    # Use T = 10°C samples (closest sweep point to room) as the proxy
    # for the design-target nominal. Spec: |v_pp - nominal|/nominal ≤ 0.10
    _, room_mask = _nearest_T(T, 10)
    nominal = float(np.median(v_pp[room_mask]))
    pass_mask = np.abs(v_pp - nominal) / nominal <= 0.10

    print(f"Wien: nominal v_pp ≈ {nominal:.3f} V, "
          f"{100*pass_mask.mean():.1f}% pass spec ±10%")
    predictors = ["R1","R2","C1","C2","Rfa","Rfb","Rg",
                  "U1_Vos","U1_Avol","U1_GBW","Q1_BF","Q2_BF"]
    rhos = _correlations(inp, v_pp, room_mask, predictors)
    top = sorted(rhos.items(), key=lambda x: -abs(x[1]))[:2]
    print("  v_pp ~ predictor  (Pearson ρ at room-T):")
    for k, r in sorted(rhos.items(), key=lambda x: -abs(x[1])):
        print(f"    {k:10s}  ρ = {r:+.3f}")

    fig = plt.figure(figsize=(12, 9))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1])
    ax_t = fig.add_subplot(gs[0, :])
    ax_p1 = fig.add_subplot(gs[1, 0])
    ax_p2 = fig.add_subplot(gs[1, 1])
    spec_h = [
        (nominal, "black", "--", f"nominal {nominal:.3f} V"),
        (nominal*1.10, "C3", ":", "+10% spec"),
        (nominal*0.90, "C3", ":", "−10% spec"),
    ]
    _scatter_metric_vs_T(ax_t, T, v_pp, pass_mask, "v_pp [V]", spec_h,
                          marker_size=8, alpha=0.45)
    ax_t.set_title("Wien v_pp vs T  "
                    "(BJT V_BE drift: linear shift across the population)")

    spec_h_pred = [
        (nominal, "black", "--", "nominal"),
        (nominal*1.10, "C3", ":", "+10% spec"),
        (nominal*0.90, "C3", ":", "−10% spec"),
    ]
    for ax, (predictor, rho) in zip([ax_p1, ax_p2], top):
        _scatter_metric_vs_predictor(ax, inp[predictor], v_pp, T,
            [-40, 25, 85], "v_pp [V]", predictor, spec_h_pred, rho)

    fig.suptitle("Wien: v_pp T-dependency dominated by 2N3904 V_BE drift; "
                 "C1/C2 are the strongest per-sample predictors",
                 y=1.00, fontsize=11)
    fig.tight_layout()
    fig.savefig("/tmp/temp_scatter_wien.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("  saved /tmp/temp_scatter_wien.png")


def scatter_ldo_ringing():
    rows = load_cache("/tmp/temp_ldo_tran.sqlite")
    if not rows:
        print("LDO tran cache empty — run chart_ldo_ringing first")
        return
    inp_keys = ["Rb","Cout","Resr","Rtop","Rbot",
                "U1_Vos","U1_Ib","U1_Avol","U1_GBW","Q1_BF","T"]
    out_keys = ["v_set","over_mv","under_mv","ring_mv"]
    inp, out = to_arrays(rows, inp_keys, out_keys)
    ring = out["ring_mv"]
    T = inp["T"]
    finite = np.isfinite(ring) & np.isfinite(T)
    inp = {k: v[finite] for k, v in inp.items()}
    ring = ring[finite]
    T = T[finite]

    pass_mask = ring < 15
    print(f"LDO ringing: {100*pass_mask.mean():.1f}% pass spec <15 mV")

    _, room_mask = _nearest_T(T, 20)
    predictors = ["Rb","Cout","Resr","U1_Vos","U1_Avol","U1_GBW","Q1_BF"]
    rhos = _correlations(inp, ring, room_mask, predictors)
    top = sorted(rhos.items(), key=lambda x: -abs(x[1]))[:2]
    print("  ring_mv ~ predictor  (Pearson ρ at room-T):")
    for k, r in sorted(rhos.items(), key=lambda x: -abs(x[1])):
        print(f"    {k:10s}  ρ = {r:+.3f}")

    fig = plt.figure(figsize=(12, 9))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1])
    ax_t = fig.add_subplot(gs[0, :])
    ax_p1 = fig.add_subplot(gs[1, 0])
    ax_p2 = fig.add_subplot(gs[1, 1])
    _scatter_metric_vs_T(ax_t, T, ring, pass_mask, "ring_rms [mV]",
                          [(15, "C3", ":", "spec 15 mV")],
                          marker_size=4, alpha=0.30, subsample_per_T=200)
    ax_t.set_title("LDO ringing vs T  (cold corner is binding)")
    for ax, (predictor, rho) in zip([ax_p1, ax_p2], top):
        _scatter_metric_vs_predictor(ax, inp[predictor], ring, T,
            [-40, 25, 85], "ring_rms [mV]", predictor,
            [(15, "C3", ":", "spec 15 mV")], rho,
            marker_size=8, alpha=0.50, subsample=250)

    fig.suptitle("Marginal LDO ringing: cold-corner samples drift up and "
                 "the slope vs binding predictors steepens",
                 y=1.00, fontsize=11)
    fig.tight_layout()
    fig.savefig("/tmp/temp_scatter_ldo_tran.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("  saved /tmp/temp_scatter_ldo_tran.png")


def scatter_ldo_pm():
    rows = load_cache("/tmp/temp_ldo_pm.sqlite")
    if not rows:
        print("LDO PM cache empty — run chart_ldo_pm first")
        return
    inp_keys = ["Rb","Cout","Resr","Rtop","Rbot",
                "U1_Vos","U1_Ib","U1_Avol","U1_GBW","Q1_BF","T"]
    out_keys = ["fc","pm"]
    inp, out = to_arrays(rows, inp_keys, out_keys)
    pm = out["pm"]
    T = inp["T"]
    finite = np.isfinite(pm) & np.isfinite(T)
    inp = {k: v[finite] for k, v in inp.items()}
    pm = pm[finite]
    T = T[finite]

    pass_mask = pm > 5
    print(f"LDO PM: {100*pass_mask.mean():.1f}% pass spec >5°")

    _, room_mask = _nearest_T(T, 20)
    predictors = ["Rb","Cout","Resr","U1_Vos","U1_Avol","U1_GBW","Q1_BF"]
    rhos = _correlations(inp, pm, room_mask, predictors)
    top = sorted(rhos.items(), key=lambda x: -abs(x[1]))[:2]
    print("  pm ~ predictor  (Pearson ρ at room-T):")
    for k, r in sorted(rhos.items(), key=lambda x: -abs(x[1])):
        print(f"    {k:10s}  ρ = {r:+.3f}")

    fig = plt.figure(figsize=(12, 9))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1])
    ax_t = fig.add_subplot(gs[0, :])
    ax_p1 = fig.add_subplot(gs[1, 0])
    ax_p2 = fig.add_subplot(gs[1, 1])
    _scatter_metric_vs_T(ax_t, T, pm, pass_mask, "PM [°]",
                          [(5, "C2", ":", "spec PM>5°"),
                           (0, "C3", "--", "instability PM=0°")],
                          marker_size=4, alpha=0.30, subsample_per_T=200)
    ax_t.set_title("LDO Middlebrook PM vs T")
    for ax, (predictor, rho) in zip([ax_p1, ax_p2], top):
        _scatter_metric_vs_predictor(ax, inp[predictor], pm, T,
            [-40, 25, 85], "PM [°]", predictor,
            [(5, "C2", ":", "spec PM>5°")], rho,
            marker_size=8, alpha=0.50, subsample=250)

    fig.suptitle("Marginal LDO PM: ESR is the dominant predictor (ρ≈0.94 — "
                 "ESR-zero compensates the output pole); cold corner shifts "
                 "the whole cloud toward the spec edge",
                 y=1.00, fontsize=11)
    fig.tight_layout()
    fig.savefig("/tmp/temp_scatter_ldo_pm.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("  saved /tmp/temp_scatter_ldo_pm.png")


def main():
    scatter_wien()
    scatter_ldo_ringing()
    scatter_ldo_pm()


if __name__ == "__main__":
    main()
