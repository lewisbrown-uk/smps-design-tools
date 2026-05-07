"""Temperature analysis: corners + sweep on a precision divider.

Three modes for handling temperature:

- ``analyze_corners(temperature_corners=[T1, T2, ...])`` — runs an
  MC at each given T (Constant sampler internally). Standard
  industry practice: pick at least min/nominal/max of the operating
  range. Per-corner yield CI is determined by ``n_mc`` alone (no
  smearing across a T band), so 1000 samples at each corner gives
  ±1.5% CI at p=0.5.
- ``temperature_sweep(temperature_points=...)`` — same machinery
  with many T points (e.g. every 5°C across the range). Used to
  find non-monotonic yield-vs-T behaviour.
- ``analyze(..., temperature=Sampler(...))`` — random-T mode where
  each MC sample draws a different T. Right tool only when T during
  operation is itself a random variable to be integrated over;
  per-T-band CI is loose unless n_mc is large.

The example: a precision divider over -40..+85°C. Three component
configurations (mismatched tempcos, matched tempcos, matched +
reel-mate correlation), four T corners, plus a finer sweep to plot
yield(T).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tolerance import (
    analyze_corners, temperature_sweep,
)


def metrics(R1, R2, T=25):
    """Divider ratio. T defaults to 25 so the metrics signature works
    whether or not analyze() was given a temperature."""
    return {"ratio": R2 / (R1 + R2)}


def run_corners(label, temperature_coefficients, correlations=None):
    """Standard industry corner check: -40 / 25 / 85°C, MC at each."""
    return analyze_corners(
        temperature_corners=[-40, 25, 85],
        nominal_values={"R1": 10e3, "R2": 10e3},
        passive_tolerances={"R": 0.001},
        metrics=metrics,
        spec={"ratio": ("within", 0.001)},
        n_mc=5000, seed=42,
        temperature_coefficients=temperature_coefficients,
        correlations=correlations,
    )


def main():
    print("Precision divider: ratio = R2/(R1+R2),  spec ratio within 0.1%")
    print()
    print("=" * 78)
    print("Corner analysis (MC at -40 / +25 / +85°C, n_mc=5000 per corner)")
    print("=" * 78)
    print(f"  {'config':>52s}  {'-40°C':>7s}  {'25°C':>7s}  {'85°C':>7s}  {'worst':>7s}")
    print("  " + "-" * 92)

    configs = [
        ("R1=50ppm, R2=200ppm (mismatched tempcos)",
            {"R1": 50e-6, "R2": 200e-6}, None),
        ("both 50ppm (matched metal-film)",
            {"R": 50e-6}, None),
        ("matched 50ppm + reel-mate ρ=0.999",
            {"R": 50e-6}, [(["R1", "R2"], 0.999)]),
    ]

    for label, tcs, corr in configs:
        report = run_corners(label, tcs, corr)
        per_T = {T: r.yield_pct for T, r in report.corners}
        print(f"  {label:>52s}  "
              f"{per_T[-40]:>6.2f}%  {per_T[25]:>6.2f}%  {per_T[85]:>6.2f}%  "
              f"{report.worst_yield:>6.2f}%")
    print()

    # Finer sweep on the mismatched-tempcos config to see the yield
    # vs T curve and locate the worst T.
    print("=" * 78)
    print("Temperature sweep (mismatched tempcos, every 5°C from -40 to +85°C)")
    print("=" * 78)
    sweep = temperature_sweep(
        temperature_points=range(-40, 86, 5),
        nominal_values={"R1": 10e3, "R2": 10e3},
        passive_tolerances={"R": 0.001},
        metrics=metrics,
        spec={"ratio": ("within", 0.001)},
        n_mc=5000, seed=42,
        temperature_coefficients={"R1": 50e-6, "R2": 200e-6},
    )
    print(f"  {'T (°C)':>8}  {'yield':>7}  {'σ ratio':>9}")
    for T, r in sweep.corners:
        s = r.metric_stats["ratio"]
        print(f"  {T:>+8.0f}  {r.yield_pct:>6.2f}%  {s.std*1e6:>7.1f}ppm")
    print()
    print(f"Worst yield in sweep: {sweep.worst_yield:.2f}% at T = "
          f"{sweep.worst_corner:+.0f}°C")
    print()
    print("The σ_ratio stays constant (~120 ppm) across the sweep — tempco")
    print("drift shifts the mean of the distribution, not its spread. Yield")
    print("falls because the mean walks past the spec edges. By ±15°C from")
    print("the tempco reference (25°C) the mean is at the spec boundary;")
    print("by ±25°C yield is essentially zero.")
    print()
    print("Compare to the earlier random-T mode which reported 22% yield —")
    print("that was just the fraction of samples that happened to land near")
    print("room temp, completely missing the binary 'doesn't work at corners'")
    print("reality. Use corners (or a sweep) for any real design check.")


if __name__ == "__main__":
    main()
