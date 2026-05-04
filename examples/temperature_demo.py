"""Temperature dependence: precision divider over the operating range.

The divider Vout/Vin = R2/(R1+R2) is meant to be invariant under
proportional component drift — common-mode shifts (e.g. equal
tempcos on both Rs) cancel in the ratio. This script quantifies how
much temperature mismatch in component types breaks that invariance.

The library samples ambient T from a user-supplied distribution
once per MC iteration and applies per-component tempcos (looked up
by full name first, then by SPICE prefix) on top of the standard
tolerance perturbation. The metrics callable receives the
temperature-adjusted values plus ``T`` as a kwarg, so ngspice
templates can also inject ``.temp`` for active-device temperature
behaviour.

Four configurations on a 0.1% R divider over -40 to +85°C:

1. **No temperature** — passive tolerance only, ~120 ppm σ ratio.
2. **Mismatched tempcos** (R1 = 50 ppm/°C metal-film,
   R2 = 200 ppm/°C thick-film) — σ blows up 11× to ~1300 ppm,
   yield collapses to 22% on a ±0.1% spec. Temperature drift
   dominates, not tolerance.
3. **Matched tempcos** (both 50 ppm/°C, e.g., same metal-film
   process) — σ drops back to passive-tolerance level. Common-mode
   tempco cancels in the ratio.
4. **Matched + reel-mate correlation** (ρ=0.999) — σ falls to
   ~4 ppm. Two cancellation mechanisms compounding: tempco common
   mode + reel-mate.

Pure closed-form, runs in seconds. Demonstrates the four library
features (temperature, per-component tolerance, correlations,
RelativeGaussian samplers) composing cleanly.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tolerance import analyze, Uniform


def metrics(R1, R2, T=25):
    """Divider ratio. T defaults to 25 so metrics works whether or
    not temperature is enabled in analyze()."""
    return {"ratio": R2 / (R1 + R2)}


def main():
    print("Precision divider: ratio = R2/(R1+R2) targeting 0.5")
    print(f"  Operating range: -40 to +85°C (industrial)")
    print(f"  Spec: ratio within 0.1% of nominal\n")
    print(f"  {'configuration':>52s}  {'σ_ratio':>9s}  {'yield':>7s}")
    print("  " + "-" * 76)

    configs = [
        ("no temperature dependence (passives only)",
            None, None, None),
        ("over T, R1=50ppm/°C metal-film, R2=200ppm/°C thick-film",
            Uniform(lo=-40, hi=85), {"R1": 50e-6, "R2": 200e-6}, None),
        ("over T, both 50ppm/°C (matched metal-film pair)",
            Uniform(lo=-40, hi=85), {"R": 50e-6}, None),
        ("matched tempcos + reel-mate correlation ρ=0.999",
            Uniform(lo=-40, hi=85), {"R": 50e-6},
            [(["R1", "R2"], 0.999)]),
    ]

    for label, temp, tcs, corr in configs:
        report = analyze(
            nominal_values={"R1": 10e3, "R2": 10e3},
            passive_tolerances={"R": 0.001},   # 0.1% precision parts
            metrics=metrics,
            spec={"ratio": ("within", 0.001)},
            n_mc=10000, seed=42,
            temperature=temp,
            temperature_coefficients=tcs,
            correlations=corr,
        )
        s = report.metric_stats["ratio"]
        print(f"  {label:>52s}  {s.std*1e6:>8.1f}ppm  "
              f"{report.yield_pct:>6.2f}%")

    print()
    print("Headline: temperature mismatch between component types is the")
    print("dominant variance contributor in precision dividers — order of")
    print("magnitude larger than 0.1% R tolerance. Matching tempcos by")
    print("using a single component type (or a matched-pair part) brings")
    print("σ back to the tolerance-only level. Reel-mate correlation on")
    print("top of matching gives another 30× of margin.")
    print()
    print("Real-world example: in a precision LM4040 voltage reference")
    print("buffer, the feedback divider should use a matched resistor")
    print("network (e.g., Vishay TNPU pair) — not two separate parts.")


if __name__ == "__main__":
    main()
