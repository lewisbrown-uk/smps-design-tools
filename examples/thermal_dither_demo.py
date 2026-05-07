"""Thermal-sensitivity analysis via paired-T dithering.

Demonstrates two ideas together:

1. **Power dissipation as an MC metric** — include ``P_Q1`` in the
   metrics dict, spec on it as a hard upper bound (e.g. < 200 mW for
   a TO-92 absolute max).
2. **Thermal sensitivity ∂P/∂T** — paired evaluation at T and
   T+ΔT exposes per-sample slopes as derived metrics ``P_Q1_dT``.
   The classical thermal-runaway criterion is ``dP/dT × R_th > 1``;
   spec on ``P_Q1_dT`` to bound the runaway margin without modelling
   the thermal network.

Test vehicle: 2N3904 common-emitter bias, two configurations.

  Unstabilized (textbook bad practice):
      Vcc ── Rc ── collector
                      │
              base ── Q1
                      │
                      emitter
                      │
                      GND
      Vbias driven directly to base via stiff source. No emitter
      degeneration. I_C is exponentially sensitive to ambient T —
      both via I_S(T) growth and V_BE intrinsic drift.

  Stabilized (textbook good practice):
      Same topology, but with Re between emitter and ground. Re
      creates negative current feedback: as I_C tries to rise with
      T, the emitter voltage rises, dropping V_BE_effective,
      suppressing the rise. Bias-point drift is reduced ~10× to
      ~50× depending on (Vbias - Vbe_typ)/Vbe_typ ratio.

The MC sweep includes:
- 5% tolerance on Vbias (typical for a divider biased by 1% R)
- 5% tolerance on Rc
- 5% tolerance on Re (stabilized version)
- Closed-form Ebers-Moll model with standard Si bandgap parameters

The dither helper computes per-sample ∂P/∂T at T_nominal=25°C with
T_dither=5K. Headline result for n_mc=2000:

                      Unstabilized        Stabilized
  P_Q1   p99           36.9 mW            31.3 mW
  P_Q1_dT p99          +1.20 mW/K         +0.016 mW/K  (75× tighter)
  Ic     p99           11.75 mA           5.09 mA      (2.3× tighter)
  Ic_dT  p99           +0.61 mA/K         +0.009 mA/K  (70× tighter)
  Yield against ``P_Q1_dT < 1 mW/K``:
                      72.5%               100%

Note Ic_dT is the bias-point drift in current per K — unstabilized
loses 0.61 mA/K at the worst-case sample (12% drift), stabilized
loses 0.009 mA/K (0.2%). The dither exposes thermal AND tolerance
sensitivity in one analysis because both manifest as "metric varies
between paired evaluations".

Combined with R_th_J→A = 200 K/W (TO-92), the runaway margin
``dP/dT × R_th`` reaches 0.24 for the unstabilized design (warning
zone) and 0.003 for stabilized (safe). For high-T operation, scale
the unstabilized margin by the Is(T) factor — at +85°C ambient,
Is grows ~50× over 25°C and the margin would multiply, crossing
the 1.0 runaway threshold.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tolerance import thermal_dither, RelativeGaussian


# ---- BJT physics constants
KB = 1.380649e-23      # Boltzmann
QE = 1.602e-19         # electron charge
EG_SI = 1.12           # silicon bandgap, eV
T0_K = 298.15          # 25°C in Kelvin
IS_25C = 6.7e-15       # 2N3904 typical I_S at 25°C
XTI = 3.0              # standard saturation-current temperature exponent
VCC = 12.0


def _to_K(T_celsius: float) -> float:
    return T_celsius + 273.15


def _vt(T_celsius: float) -> float:
    return KB * _to_K(T_celsius) / QE


def _is_at(T_celsius: float) -> float:
    """Saturation current at T using the standard
    I_S(T) = I_S(T0) · (T/T0)^XTI · exp(Eg·q/k · (1/T0 - 1/T))."""
    T_K = _to_K(T_celsius)
    arg_diff = (EG_SI * QE / KB) * (1.0 / T0_K - 1.0 / T_K)
    return IS_25C * (T_K / T0_K) ** XTI * math.exp(arg_diff)


def _ic_unstabilized(Vbias: float, Rc: float, T: float) -> float:
    """No emitter resistor — V_BE = Vbias directly. I_C =
    I_S(T)·exp(V_BE/V_T(T)). Self-clamps at saturation."""
    Ic = _is_at(T) * math.exp(Vbias / _vt(T))
    Ic_max = (VCC - 0.2) / Rc          # saturation current bound
    return min(Ic, Ic_max)


def _ic_stabilized(Vbias: float, Rc: float, Re: float, T: float) -> float:
    """With Re, solve V_BE = Vbias - I_E·Re self-consistently. One
    Newton step from the linear-approximation start is enough for
    physically reasonable operating points (1-10 mA range)."""
    # Linear approximation start: assume Vbe_typ = 0.65V
    Ie = max(1e-9, (Vbias - 0.65) / Re)
    # Newton refine: f(Ie) = Vt·ln(Ie/Is) + Ie·Re - Vbias = 0
    Is = _is_at(T)
    Vt = _vt(T)
    for _ in range(8):
        Vbe = Vt * math.log(max(Ie, 1e-15) / Is)
        f = Vbe + Ie * Re - Vbias
        df = Vt / max(Ie, 1e-15) + Re
        step = f / df
        Ie -= step
        if abs(step) < 1e-9 * max(Ie, 1e-9):
            break
        Ie = max(Ie, 1e-12)            # clamp positive
    Ie_max = (VCC - 0.2) / (Rc + Re)
    return min(Ie, Ie_max)             # I_C ≈ I_E (alpha ≈ 1)


def metrics_unstabilized(Vbias, Rc, T):
    Ic = _ic_unstabilized(Vbias, Rc, T)
    Vce = VCC - Ic * Rc
    return {"P_Q1": Ic * Vce, "Ic": Ic, "Vce": Vce}


def metrics_stabilized(Vbias, Rc, Re, T):
    Ic = _ic_stabilized(Vbias, Rc, Re, T)
    Vce = VCC - Ic * (Rc + Re)
    return {"P_Q1": Ic * Vce, "Ic": Ic, "Vce": Vce}


def _print_report(label, report):
    print(f"\n{label}")
    print("=" * 72)
    print(f"  Yield against spec: {report.yield_pct:.1f}%")
    print(f"  Per-spec yield:")
    for k, c in report.per_spec_pass.items():
        print(f"    {k:>10s}: {100*c/report.samples_total:.1f}%")
    print(f"  Metric stats:")
    for k in ["P_Q1", "P_Q1_dT", "Ic", "Ic_dT"]:
        if k in report.metric_stats:
            s = report.metric_stats[k]
            unit = "W" if k.startswith("P_") else "A"
            scale = 1e3                # mW or mA
            label_unit = ("mW/K" if k.endswith("_dT") and k.startswith("P_")
                           else "mA/K" if k.endswith("_dT")
                           else "mW" if k.startswith("P_") else "mA")
            print(f"    {k:>10s}: mean={s.mean*scale:>8.3f}{label_unit:>5s}  "
                  f"p99={s.p99*scale:>8.3f}{label_unit:>5s}")


def main():
    print("Thermal-sensitivity analysis: BJT class-A bias")
    print("=" * 72)

    SPEC = {
        # Power < 200 mW (TO-92 abs max ~625mW; pick 200mW as a
        # comfortable de-rating margin)
        "P_Q1":    ("<", 0.200),
        # Thermal sensitivity < 1 mW/K. At R_th = 200 K/W (TO-92),
        # this corresponds to a runaway margin of 0.20 — well below
        # the dP/dT × R_th = 1 instability threshold.
        "P_Q1_dT": ("<", 0.001),
    }

    # ---- Unstabilized: no Re. Direct V_BE = Vbias.
    # Vbias=0.70V → ~5 mA quiescent at 25°C, P ≈ 35 mW
    rep_u = thermal_dither(
        nominal_values={"Vbias": 0.70, "Rc": 1.0e3},
        passive_tolerances={"R": 0.05},
        distribution={"Vbias": RelativeGaussian(0.70, 0.05)},
        metrics=metrics_unstabilized,
        spec=SPEC,
        n_mc=2000, seed=42,
        T_nominal=25.0, T_dither=5.0,
    )
    _print_report("Unstabilized: no emitter resistor (textbook bad practice)",
                   rep_u)

    # ---- Stabilized: Re=180Ω, Vbias compensated for the Re drop.
    # Iq target ~5 mA → Vbias = Vbe_typ + Iq·Re = 0.65 + 0.005·180 = 1.55V
    rep_s = thermal_dither(
        nominal_values={"Vbias": 1.55, "Rc": 1.0e3, "Re": 180.0},
        passive_tolerances={"R": 0.05},
        distribution={"Vbias": RelativeGaussian(1.55, 0.05)},
        metrics=metrics_stabilized,
        spec=SPEC,
        n_mc=2000, seed=42,
        T_nominal=25.0, T_dither=5.0,
    )
    _print_report("Stabilized: Re=180Ω (negative current feedback)", rep_s)

    # ---- Runaway margin headline
    print("\n\nThermal-runaway margin analysis")
    print("=" * 72)
    print("Classical criterion: dP/dT × R_th_J→A > 1 → unstable feedback loop")
    print()
    print(f"  {'Package':<25s}  {'R_th (K/W)':>10s}  "
          f"{'unstab margin':>15s}  {'stab margin':>13s}")
    for pkg, R_th in [("TO-92 (small signal)", 200),
                       ("TO-126 (med power)", 100),
                       ("TO-220 (power)", 50),
                       ("TO-247 + heatsink", 5)]:
        m_u = rep_u.metric_stats["P_Q1_dT"].p99 * R_th
        m_s = rep_s.metric_stats["P_Q1_dT"].p99 * R_th
        print(f"  {pkg:<25s}  {R_th:>10d}  "
              f"{m_u:>14.3f}{' ⚠' if m_u > 0.5 else '  '}  "
              f"{m_s:>13.3f}")
    print()
    print("  ⚠ = approaching the dP/dT × R_th = 1 runaway threshold.")
    print("  Stabilized design has ~30× safety margin everywhere.")


if __name__ == "__main__":
    main()
