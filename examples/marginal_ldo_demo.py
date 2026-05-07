"""Op-amp + NPN series regulator with deliberately marginal stability.

Demonstrates time-domain stability metrics (load-step overshoot,
undershoot, ringing RMS) measured via ``.tran`` + ``.meas tran``.
The design is the textbook "LDO with low-ESR ceramic cap" stability
problem: the output-pole at 1/(2π·Rload·Cout) sits inside the loop
bandwidth without an ESR-zero to compensate it, so phase margin is
poor and the loop rings on load steps.

Topology::

    Vin (9V) ── Q1 (NPN pass) ── out ── Cout(low-ESR) ─┐
                  ↑base                                   │
                  ┘  Rb                                  Rload
              op-amp out                              (50→100mA pulse)
                  ↑
                ref (2.5V) on +
                fb on - (divider Rtop/Rbot)

A 50 → 100 mA load step at t=10 ms produces overshoot, undershoot,
and ringing whose magnitudes depend on phase margin. The MC sweeps:

- 1% R on the divider, base resistor
- 20% C on Cout (typical for electrolytic)
- Custom samplers for active-device + ESR parameters that the
  curated DEVICES library doesn't cover (slow op-amp, low-ESR cap)

Surprising finding from the 100k-sample run: the dominant predictors
of ringing are **ESR** and **BJT β** (both ρ ≈ −0.55), not the
op-amp parameters one might expect. The classic "low-ESR caps make
LDOs ring" wisdom is correctly named, and the BJT loading effect on
the op-amp output is the second binding constraint.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tolerance import (
    NgspiceBackend, CachedBackend, analyze,
    RelativeGaussian, RelativeUniform, Uniform, Constant,
)


HERE = os.path.dirname(os.path.abspath(__file__))
UOPAMP_LIB = os.path.abspath(os.path.join(
    HERE, "..", "ngspice_examples", "uopamp.lib"
))


def make_template(uopamp_lib_path: str) -> str:
    """Parameterised LDO netlist. Placeholders: Rb, Cout, Resr,
    Rtop, Rbot, U1_Vos / U1_Avol / U1_GBW / U1_Ib (op-amp), Q1_BF (BJT)."""
    return f"""* Marginal LDO: op-amp + NPN pass element with low-ESR Cout
.include {uopamp_lib_path}

Vin   raw   0     9
Vcc   vcc   0     12
Vee   vee   0     0
Vref  ref   0     2.5

Vos1  ref_eff ref {{U1_Vos}}
XU1   ref_eff fb  vcc  vee  drv   uopamp_lvl2
+     Avol={{U1_Avol}} GBW={{U1_GBW}} Rin=100k Rout=30 Iq=8m
+     Ilimit=1 Vrail=1.4 Vmax=40

Rb    drv   base  {{Rb}}
Q1    raw   base  out   Q2N3904

* Output cap with explicit series ESR
Cout  out   cnode {{Cout}}  IC=0
Resr  cnode 0     {{Resr}}

* 50 mA → 100 mA load step at t = 10 ms (well after startup)
Iload out   0     PULSE(0.05 0.10 10m 5u 5u 20m 100m)

Rtop  out   fb    {{Rtop}}
Rbot  fb    0     {{Rbot}}

.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF={{Q1_BF}}
+ NE=1.259 ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0
+ IKR=0 RC=1 CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p
+ MJE=.2593 VJE=.75 TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)

.tran 5u 25m UIC

.control
run

* Sample the settled output just before the load step
meas tran v_set find v(out) at=9.9m

* Peak deviation from settled value during the post-step transient
meas tran v_max max v(out) from=10m to=25m
meas tran v_min min v(out) from=10m to=25m

* Ringing energy: RMS of the settled-value-removed signal over the
* post-step window. Excludes the first 0.5 ms to avoid double-counting
* the initial single-overshoot (which is captured by v_max/v_min).
let dev = v(out) - v_set
meas tran ring_rms rms dev from=10.5m to=20m

let over_mv  = (v_max - v_set) * 1e3
let under_mv = (v_set - v_min) * 1e3
let ring_mv  = ring_rms * 1e3
print v_set over_mv under_mv ring_mv
.endc
.end
"""


def main():
    template = make_template(UOPAMP_LIB)
    raw = NgspiceBackend(
        template=template,
        outputs=["v_set", "over_mv", "under_mv", "ring_mv"],
        timeout=15,
    )
    cached = CachedBackend(raw, path="/tmp/marginal_ldo_example.sqlite")

    def metrics(**values):
        return cached(**values)
    metrics.signature = lambda: cached.signature

    # Nominal: GBW=300kHz, Cout=470µF, ESR=1mΩ — chosen to be marginal
    # but not unstable at nominal. With ±20% spread on the active GBW
    # and uniform ESR over [0.5, 5] mΩ, ~7% of samples ring past the
    # 15-mV spec.
    nominal = {
        "Rb": 100, "Cout": 470e-6, "Resr": 1e-3,
        "Rtop": 10e3, "Rbot": 10e3,
        "U1_Vos": 0.0, "U1_Ib": 200e-9,
        "U1_Avol": 100e3, "U1_GBW": 300e3,
        "Q1_BF": 250,
    }

    nom = metrics(**nominal)
    print("Nominal regulator (load-step response):")
    print(f"  v_set    = {nom['v_set']:.4f} V")
    print(f"  over_mv  = {nom['over_mv']:.2f} mV  (peak above settled)")
    print(f"  under_mv = {nom['under_mv']:.2f} mV  (peak below settled)")
    print(f"  ring_mv  = {nom['ring_mv']:.3f} mV  (RMS over t=10.5–20 ms)")
    print()

    n_mc = 400
    print(f"Running {n_mc}-sample MC ...")
    print("  Passive tolerance: 1% R, 20% C")
    print("  Active spreads: U1_GBW ±20%, U1_Avol ±50% uniform,")
    print("    Q1_BF uniform 100..400, Resr uniform 0.5–5 mΩ")
    print()
    t0 = time.perf_counter()
    report = analyze(
        nominal_values=nominal,
        passive_tolerances={"R": 0.01, "C": 0.20},
        # Custom samplers for active params + ESR. The library accepts
        # any non-passive name as long as the distribution dict supplies
        # an explicit Sampler — no placeholder passive_tolerances entry
        # needed.
        distribution={
            "U1_GBW":  RelativeGaussian(nominal_value=300e3, tol=0.20),
            "U1_Avol": RelativeUniform(nominal_value=100e3, tol=0.50),
            "U1_Vos":  Constant(value=0.0),
            "U1_Ib":   Constant(value=200e-9),
            "Q1_BF":   Uniform(lo=100, hi=400),
            "Resr":    Uniform(lo=0.5e-3, hi=5e-3),
        },
        metrics=metrics,
        spec={
            "over_mv":  ("<", 50),     # < 50 mV peak overshoot
            "under_mv": ("<", 50),
            "ring_mv":  ("<", 15),     # < 15 mV ringing RMS
        },
        n_mc=n_mc, seed=42, workers=8,
    )
    dt = time.perf_counter() - t0
    print(f"  {dt:.1f}s  ({n_mc/dt:.1f} samples/s)\n")
    print(report)


if __name__ == "__main__":
    main()
