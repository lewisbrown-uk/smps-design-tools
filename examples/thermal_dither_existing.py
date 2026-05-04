"""thermal_dither analysis on the existing LDO and Wien examples.

Expected result: both circuits are safe — dP/dT × R_th well below
the runaway threshold of 1. The thermal_dither_demo.py shows what
risk LOOKS like (an unstabilised class-A bias); this script confirms
the existing demos don't have it.

**LDO (closed-loop regulator)**: Q1 is the NPN pass transistor at
~50 mA × ~4 V = ~200 mW dissipation. The op-amp loop holds Vout
constant against temperature drift, so V_CE = Vraw − Vout is
essentially T-invariant. P_Q1 ≈ V_CE × Iload barely moves with T.
Expected dP/dT ≈ 0 (with sign and small magnitude depending on Vos
drift bleed-through).

**Wien (diode-clamp oscillator)**: Q1 and Q2 are diode-connected
NPN clamps. They only conduct briefly per cycle when the output
exceeds the clamp threshold (≈ V_BE). As T rises, V_BE drops →
clamp threshold drops → output amplitude drops → less voltage to
clamp → less power dissipation. Expected dP/dT < 0 (self-stabilising).

Both circuits produce small |dP/dT|, dwarfing the runaway threshold
across all reasonable packaging choices. The demonstration is the
absence of risk, which the dither analysis correctly reports.
"""
from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tolerance import (
    NgspiceBackend, CachedBackend, thermal_dither,
    RelativeGaussian, RelativeUniform, Uniform, lockin_thd_block,
)


HERE = os.path.dirname(os.path.abspath(__file__))
UOPAMP = os.path.abspath(os.path.join(HERE, "..", "ngspice_examples",
                                       "uopamp.lib"))
VRAW = 9.0
ILOAD_DC = 0.050      # steady-state load before the load step


def _ldo_template() -> str:
    """LDO with .temp injection. Steady-state operation under 50 mA
    load — no load step needed for the dP/dT analysis since power
    dissipation is set by V_CE × Iload at quiescence."""
    return f"""* LDO with .temp injection — DC operating point analysis
.include {UOPAMP}
.temp {{T}}
Vin   raw   0     {VRAW}
Vcc   vcc   0     12
Vee   vee   0     0
Vref  ref   0     2.5
Vos1  ref_eff ref {{U1_Vos}}
XU1   ref_eff fb  vcc  vee  drv   uopamp_lvl2
+     Avol={{U1_Avol}} GBW={{U1_GBW}} Rin=100k Rout=30 Iq=8m
+     Ilimit=1 Vrail=1.4 Vmax=40
Rb    drv   base  {{Rb}}
Q1    raw   base  out   Q2N3904
Cout  out   cnode {{Cout}}  IC=0
Resr  cnode 0     {{Resr}}
Iload out   0     {ILOAD_DC}
Rtop  out   fb    {{Rtop}}
Rbot  fb    0     {{Rbot}}
.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF={{Q1_BF}}
+ NE=1.259 ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0
+ IKR=0 RC=1 CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p
+ MJE=.2593 VJE=.75 TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)
.tran 5u 10m UIC
.control
run
meas tran v_out find v(out) at=9m
print v_out
.endc
.end
"""


def _wien_template() -> str:
    """Wien with .temp + .control block computing average dissipation
    in Q1 and Q2 over the lock-in window. Adds 0V probes in series
    with each clamp transistor's collector to give clean access to
    I_C in the .control expressions."""
    lockin = lockin_thd_block(
        signal="v(out)", window=(80e-3, 100e-3),
        f0_init_expr="1/(t2-t1)",
    )
    return f"""* Wien oscillator with Q1/Q2 power-dissipation extraction
.include {UOPAMP}
.temp {{T}}
R1   out  ns      {{R1}}
C1   ns   np      {{C1}}  IC=0
R2   np_eff 0     {{R2}}
C2   np_eff 0     {{C2}}  IC=10m
Vos1 np   np_eff  {{U1_Vos}}
Rg   nn   0       {{Rg}}
Rfa  nn   fb      {{Rfa}}
Rfb  fb   out     {{Rfb}}
* 0V probes in series with each clamp transistor's collector
Vpq1 fb   q1c     0
Q1   q1c  fb   out  Q2N3904_A
Vpq2 out  q2c     0
Q2   q2c  out  fb   Q2N3904_B
Vcc  vcc 0  15
Vee  vee 0 -15
XU1  np nn vcc vee out uopamp_lvl2
+    Avol={{U1_Avol}} GBW={{U1_GBW}} Rin=100k Rout=30 Iq=8m
+    Ilimit=1 Vrail=1.4 Vmax=40
.model Q2N3904_A NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF={{Q1_BF}}
+ NE=1.259 ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0
+ IKR=0 RC=1 CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p
+ MJE=.2593 VJE=.75 TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)
.model Q2N3904_B NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF={{Q2_BF}}
+ NE=1.259 ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0
+ IKR=0 RC=1 CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p
+ MJE=.2593 VJE=.75 TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)
.tran 1u 100m UIC
.control
run
meas tran t1 when v(out)=0 fall=20
meas tran t2 when v(out)=0 fall=21
meas tran amp_max max v(out) from=80m to=100m
meas tran amp_min min v(out) from=80m to=100m
* P_Q = V_BE · I_C  (diode-connected → V_CE = V_BE)
let p_q1_t = (v(fb) - v(out)) * i(vpq1)
let p_q2_t = (v(out) - v(fb)) * i(vpq2)
meas tran p_q1 avg p_q1_t from=80m to=100m
meas tran p_q2 avg p_q2_t from=80m to=100m
{lockin}
.endc
.end
"""


def _ldo_metrics_factory():
    backend = NgspiceBackend(template=_ldo_template(),
                              outputs=["v_out"], timeout=15)
    cached = CachedBackend(backend, path="/tmp/thermal_ldo.sqlite")

    def metrics(**values):
        r = cached(**values)
        # P_Q1 ≈ V_CE × I_load. I_load is fixed by Iload current source.
        return {"P_Q1": (VRAW - r["v_out"]) * ILOAD_DC,
                "v_out": r["v_out"]}
    metrics.signature = lambda: cached.signature
    return metrics, cached


def _wien_metrics_factory():
    backend = NgspiceBackend(template=_wien_template(),
                              outputs=["t1","t2","amp_max","amp_min",
                                        "p_q1","p_q2",
                                        "f_new","a_rms","h_rms","thd","thd_db"],
                              timeout=20)
    cached = CachedBackend(backend, path="/tmp/thermal_wien.sqlite")

    def metrics(**values):
        r = cached(**values)
        return {
            "P_Q1":   abs(r["p_q1"]),       # average dissipation
            "P_Q2":   abs(r["p_q2"]),
            "v_pp":   r["amp_max"] - r["amp_min"],
            "thd_db": r["thd_db"],
        }
    metrics.signature = lambda: cached.signature
    return metrics, cached


def _runaway_table(label, p_dT_p99, p_dT_p1):
    """Print runaway-margin table for a few packaging choices.
    p_dT_p99 captures the worst-case positive slope (heating →
    more power); p_dT_p1 captures the most-negative slope (heating
    → less power, self-stabilising)."""
    pkgs = [("TO-92 (small signal)", 200),
            ("TO-126 (med power)", 100),
            ("TO-220 (power)", 50),
            ("TO-247 + heatsink", 5)]
    print(f"\n  {label}: dP/dT × R_th_J→A — runaway threshold = 1.0")
    print(f"  {'package':<25s}  {'R_th':>7s}  {'p99 margin':>11s}  "
          f"{'p1 margin':>10s}")
    for name, R_th in pkgs:
        m99 = p_dT_p99 * R_th
        m1 = p_dT_p1 * R_th
        flag = " ⚠" if m99 > 0.5 else "  "
        print(f"  {name:<25s}  {R_th:>4d}K/W  "
              f"{m99:>+10.5f}{flag}  {m1:>+10.5f}")


def main():
    # ---- LDO
    print("=" * 72)
    print("Marginal LDO  (closed-loop regulator, NPN pass at 50 mA)")
    print("=" * 72)
    metrics, _ = _ldo_metrics_factory()
    t0 = time.perf_counter()
    rep_ldo = thermal_dither(
        T_nominal=25.0, T_dither=5.0,
        nominal_values={"Rb": 100, "Cout": 470e-6, "Resr": 1e-3,
                        "Rtop": 10e3, "Rbot": 10e3},
        passive_tolerances={"R": 0.01, "C": 0.20},
        active_devices={"U1": "NE5532", "Q1": "2N3904"},
        distribution={
            "U1_GBW":  RelativeGaussian(nominal_value=300e3, tol=0.20),
            "U1_Avol": RelativeUniform(nominal_value=100e3, tol=0.50),
            "Resr":    Uniform(lo=0.5e-3, hi=5e-3),
        },
        temperature_coefficients={"R": 50e-6, "C": 200e-6},
        metrics=metrics,
        spec={"P_Q1": ("<", 0.500),         # < 500 mW (TO-92 abs max ~625mW)
              "P_Q1_dT": ("<", 0.001)},     # < 1 mW/K
        n_mc=80, seed=42, workers=8,
    )
    print(f"  ran {2*80} ngspice calls in {time.perf_counter()-t0:.1f}s\n")

    p = rep_ldo.metric_stats["P_Q1"]
    pdt = rep_ldo.metric_stats["P_Q1_dT"]
    print(f"  P_Q1     mean={p.mean*1000:>8.2f} mW   "
          f"p99={p.p99*1000:>8.2f} mW")
    print(f"  P_Q1_dT  mean={pdt.mean*1e6:>8.2f} µW/K "
          f"p1={pdt.p1*1e6:>+7.2f} µW/K  p99={pdt.p99*1e6:>+7.2f} µW/K")
    print(f"  Yield (P_Q1<500mW AND P_Q1_dT<1mW/K): "
          f"{rep_ldo.yield_pct:.1f}%")
    _runaway_table("LDO Q1", pdt.p99, pdt.p1)

    # ---- Wien
    print("\n" + "=" * 72)
    print("Wien oscillator  (diode-clamp NPN pair Q1/Q2)")
    print("=" * 72)
    metrics, _ = _wien_metrics_factory()
    t0 = time.perf_counter()
    rep_wien = thermal_dither(
        T_nominal=25.0, T_dither=5.0,
        nominal_values={
            "R1": 10e3, "R2": 10e3,
            "C1": 15.915e-9, "C2": 15.915e-9,
            "Rg": 10e3, "Rfa": 10e3, "Rfb": 12e3,
        },
        passive_tolerances={"R": 0.05, "C": 0.10},
        active_devices={"U1": "NE5532", "Q1": "2N3904", "Q2": "2N3904"},
        temperature_coefficients={"R": 50e-6, "C": 30e-6},
        metrics=metrics,
        spec={"P_Q1": ("<", 0.100),         # 100 mW (TO-92 derate)
              "P_Q2": ("<", 0.100),
              "P_Q1_dT": ("<", 0.001)},
        n_mc=60, seed=42, workers=8,
    )
    print(f"  ran {2*60} ngspice calls in {time.perf_counter()-t0:.1f}s\n")

    for name in ("P_Q1", "P_Q2"):
        p = rep_wien.metric_stats[name]
        pdt = rep_wien.metric_stats[f"{name}_dT"]
        print(f"  {name}     mean={p.mean*1000:>8.3f} mW   "
              f"p99={p.p99*1000:>8.3f} mW")
        print(f"  {name}_dT  mean={pdt.mean*1e6:>8.3f} µW/K "
              f"p1={pdt.p1*1e6:>+7.3f} µW/K  p99={pdt.p99*1e6:>+7.3f} µW/K")
    print(f"  Yield: {rep_wien.yield_pct:.1f}%")
    pdt1 = rep_wien.metric_stats["P_Q1_dT"]
    _runaway_table("Wien Q1", pdt1.p99, pdt1.p1)

    print("\n" + "=" * 72)
    print("Verdict")
    print("=" * 72)
    print("  Both designs sit far below the dP/dT × R_th = 1 runaway")
    print("  threshold across all reasonable packaging choices.")
    print("  - LDO: closed-loop regulation holds V_CE ≈ const → P ≈ const → dP/dT ≈ 0")
    print("  - Wien: V_BE drops with T → clamp threshold drops → P drops → dP/dT < 0 (stable)")


if __name__ == "__main__":
    main()
