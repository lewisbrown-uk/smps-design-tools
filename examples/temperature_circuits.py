"""Temperature analysis on three demo circuits — SK filter, LDO
load-step ringing, LDO Middlebrook phase margin.

Each section uses ``temperature_sweep`` (MC at each of many fixed T
points) to map yield(T) and metric(T) curves across the industrial
operating range. Saves a chart per circuit.

Run all together to see the variety of temperature signatures:

- **SK filter** (closed-form): tempco mismatch between R and C
  drifts the fc mean linearly with T. Q is invariant (it's a ratio
  of components). X7R caps + metal-film R is the killer.
- **LDO ringing** (ngspice tran with .temp): cold-corner is worse.
  BJT V_BE/β drift change loop dynamics; ring_rms increases at
  low T, dragging yield down ~14 percentage points.
- **LDO PM** (ngspice .ac with .temp): same direction — PM mean
  rises monotonically with T, confirming the time-domain finding.
  Cross-validates that cold is the binding corner.

Each chart saved at ``/tmp/temp_<name>.png``.
"""
from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from utils.tolerance import (
    NgspiceBackend, CachedBackend,
    temperature_sweep,
    RelativeGaussian, RelativeUniform, Uniform, Constant,
)


HERE = os.path.dirname(os.path.abspath(__file__))
UOPAMP = os.path.abspath(os.path.join(HERE, "..", "ngspice_examples",
                                       "uopamp.lib"))


def chart_sk():
    """Sallen-Key Butterworth filter (closed-form, fast)."""
    def metrics(R1, R2, C1, C2, T=25):
        return {"f0": 1 / (2*math.pi*math.sqrt(R1*R2*C1*C2)),
                "Q":  math.sqrt(R1*R2*C2/C1) / (R1+R2)}

    T_points = list(range(-40, 86, 2))
    configs = [
        ("metal-film R + X7R C (typical)",
            {"R": 50e-6, "C": 1500e-6}, None, "C3"),
        ("metal-film R + C0G C (precision)",
            {"R": 50e-6, "C": 30e-6}, None, "C1"),
        ("matched-pair R + C0G C (best)",
            {"R": 50e-6, "C": 30e-6},
            [(["R1", "R2"], 0.999), (["C1", "C2"], 0.999)], "C2"),
    ]

    print("SK Butterworth temperature sweep ...")
    results = []
    for label, tcs, corr, color in configs:
        sweep = temperature_sweep(
            temperature_points=T_points,
            nominal_values={"R1": 1e4, "R2": 1e4,
                            "C1": 1e-8, "C2": 2.2e-8},
            passive_tolerances={"R": 0.01, "C": 0.05},
            metrics=metrics,
            spec={"f0": ("within", 0.05), "Q": ("within", 0.10)},
            n_mc=2000, seed=42,
            temperature_coefficients=tcs,
            correlations=corr,
        )
        Ts = np.array([T for T, _ in sweep.corners])
        yields = np.array([r.yield_pct for _, r in sweep.corners])
        f0_mean = np.array([r.metric_stats["f0"].mean for _, r in sweep.corners])
        results.append((label, color, Ts, yields, f0_mean))

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax_y, ax_f = axes
    for label, c, Ts, yields, f0 in results:
        ax_y.plot(Ts, yields, color=c, lw=2, marker="o", markersize=2.5,
                  label=label)
        ax_f.plot(Ts, f0, color=c, lw=2)
    ax_y.axhline(50, color="0.7", linestyle=":", lw=0.7)
    ax_y.axvline(25, color="0.5", linestyle=":", lw=0.6)
    ax_y.set_ylabel("Yield (%)")
    ax_y.set_title("Sallen-Key Butterworth filter over T  "
                   "(spec: fc within 5%, Q within 10%)")
    ax_y.legend(loc="lower center", fontsize=9)
    ax_y.grid(True, alpha=0.3); ax_y.set_ylim(-3, 103)
    ax_f.axhline(1073, color="black", linestyle="--", lw=0.7)
    for v in (1073*0.95, 1073*1.05):
        ax_f.axhline(v, color="#d62728", linestyle=":", lw=1, alpha=0.7)
    ax_f.set_ylabel("fc mean [Hz]"); ax_f.set_xlabel("ambient T [°C]")
    ax_f.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("/tmp/temp_sk.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("  saved /tmp/temp_sk.png")


def _ldo_template(extra_block: str) -> str:
    """LDO common netlist with .temp injection. ``extra_block`` is
    spliced where the analysis-specific bits go (transient + meas, or
    AC + meas)."""
    return f"""* LDO with .temp injection
.include {UOPAMP}
.temp {{T}}
Vin   raw   0     9
Vcc   vcc   0     12
Vee   vee   0     0
Vref  ref   0     2.5
Vos1  ref_eff ref {{U1_Vos}}
{{INJECT}}
XU1   ref_eff fb  vcc  vee  drv   uopamp_lvl2
+     Avol={{U1_Avol}} GBW={{U1_GBW}} Rin=100k Rout=30 Iq=8m
+     Ilimit=1 Vrail=1.4 Vmax=40
Rb    {{BASE_DRV}} base  {{Rb}}
Q1    raw   base  out   Q2N3904
Cout  out   cnode {{Cout}}  IC=0
Resr  cnode 0     {{Resr}}
{{LOAD}}
Rtop  out   fb    {{Rtop}}
Rbot  fb    0     {{Rbot}}
.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF={{Q1_BF}}
+ NE=1.259 ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0
+ IKR=0 RC=1 CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p
+ MJE=.2593 VJE=.75 TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)
{extra_block}
"""


def _ldo_distribution_kw():
    """Common per-component samplers for the LDO sweep."""
    return dict(
        nominal_values={"Rb": 100, "Cout": 470e-6, "Resr": 1e-3,
                        "Rtop": 10e3, "Rbot": 10e3,
                        "U1_Vos": 0.0, "U1_Ib": 200e-9,
                        "U1_Avol": 100e3, "U1_GBW": 300e3, "Q1_BF": 250},
        passive_tolerances={"R": 0.01, "C": 0.20},
        distribution={
            "U1_GBW":  RelativeGaussian(nominal_value=300e3, tol=0.20),
            "U1_Avol": RelativeUniform(nominal_value=100e3, tol=0.50),
            "U1_Vos":  Constant(value=0.0),
            "U1_Ib":   Constant(value=200e-9),
            "Q1_BF":   Uniform(lo=100, hi=400),
            "Resr":    Uniform(lo=0.5e-3, hi=5e-3),
        },
        temperature_coefficients={"R": 50e-6, "C": 200e-6},
    )


def chart_ldo_ringing():
    """LDO load-step ringing (ngspice tran)."""
    body = """.tran 5u 25m UIC
.control
run
meas tran v_set find v(out) at=9.9m
meas tran v_max max v(out) from=10m to=25m
meas tran v_min min v(out) from=10m to=25m
let dev = v(out) - v_set
meas tran ring_rms rms dev from=10.5m to=20m
let over_mv  = (v_max - v_set) * 1e3
let under_mv = (v_set - v_min) * 1e3
let ring_mv  = ring_rms * 1e3
print v_set over_mv under_mv ring_mv
.endc
.end"""
    tpl = _ldo_template(body).replace("{INJECT}", "").replace(
        "{BASE_DRV}", "drv"
    ).replace(
        "{LOAD}", "Iload out 0 PULSE(0.05 0.10 10m 5u 5u 20m 100m)"
    )
    backend = NgspiceBackend(template=tpl,
                              outputs=["v_set","over_mv","under_mv","ring_mv"],
                              timeout=20)
    cache = "/tmp/temp_ldo_tran.sqlite"
    if os.path.exists(cache): os.remove(cache)
    cached = CachedBackend(backend, path=cache)
    metrics_fn = lambda **v: cached(**v)
    metrics_fn.signature = lambda: cached.signature

    T_points = list(range(-40, 86, 10))
    print(f"LDO ringing temperature sweep ({len(T_points)} T-points × 800 MC) ...")
    t0 = time.perf_counter()
    sweep = temperature_sweep(
        temperature_points=T_points,
        metrics=metrics_fn,
        spec={"over_mv": ("<", 50), "under_mv": ("<", 50),
              "ring_mv": ("<", 15)},
        n_mc=800, seed=42, workers=8,
        **_ldo_distribution_kw(),
    )
    print(f"  {time.perf_counter()-t0:.1f}s")

    Ts = np.array([T for T, _ in sweep.corners])
    yields = np.array([r.yield_pct for _, r in sweep.corners])
    ring_mean = np.array([r.metric_stats["ring_mv"].mean for _, r in sweep.corners])
    ring_p95 = np.array([r.metric_stats["ring_mv"].p95 for _, r in sweep.corners])
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax_y, ax_r = axes
    ax_y.plot(Ts, yields, color="C0", lw=2, marker="o", markersize=5)
    ax_y.axvline(25, color="0.5", linestyle=":", lw=0.6)
    ax_y.set_ylabel("Yield (%)")
    ax_y.set_title("Marginal LDO load-step yield over T")
    ax_y.grid(True, alpha=0.3)
    ax_r.plot(Ts, ring_mean, color="C0", lw=2, marker="o", markersize=4,
              label="ring_rms mean")
    ax_r.fill_between(Ts, np.zeros_like(ring_mean), ring_p95,
                      color="C0", alpha=0.15, label="0–p95 band")
    ax_r.axhline(15, color="C0", linestyle=":", lw=1, alpha=0.7,
                 label="spec 15mV")
    ax_r.set_xlabel("ambient T [°C]")
    ax_r.set_ylabel("ringing RMS [mV]")
    ax_r.legend(fontsize=9); ax_r.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("/tmp/temp_ldo_tran.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("  saved /tmp/temp_ldo_tran.png")


def chart_ldo_pm():
    """LDO Middlebrook PM (ngspice .ac)."""
    body = """.control
op
ac dec 30 1 100meg
let mag_db = 20*log10(vm(drv)/vm(drv_inj))
let ph_deg = (vp(drv) - vp(drv_inj)) * 180 / 3.14159265
meas ac fc when mag_db=0
meas ac pm find ph_deg when mag_db=0
print fc pm
.endc
.end"""
    tpl = _ldo_template(body).replace(
        "{INJECT}", "Vinj  drv drv_inj AC 1"
    ).replace(
        "{BASE_DRV}", "drv_inj"
    ).replace(
        "{LOAD}", "Iload out 0 0.05"
    )
    backend = NgspiceBackend(template=tpl, outputs=["fc", "pm"], timeout=10)
    cache = "/tmp/temp_ldo_pm.sqlite"
    if os.path.exists(cache): os.remove(cache)
    cached = CachedBackend(backend, path=cache)
    metrics_fn = lambda **v: cached(**v)
    metrics_fn.signature = lambda: cached.signature

    T_points = list(range(-40, 86, 10))
    print(f"LDO Middlebrook PM temperature sweep ({len(T_points)} T-points × 800 MC) ...")
    t0 = time.perf_counter()
    sweep = temperature_sweep(
        temperature_points=T_points,
        metrics=metrics_fn,
        spec={"pm": (">", 5)},
        n_mc=800, seed=42, workers=8,
        **_ldo_distribution_kw(),
    )
    print(f"  {time.perf_counter()-t0:.1f}s")

    Ts = np.array([T for T, _ in sweep.corners])
    pm_mean = np.array([r.metric_stats["pm"].mean for _, r in sweep.corners])
    pm_p1 = np.array([r.metric_stats["pm"].p1 for _, r in sweep.corners])
    pm_p99 = np.array([r.metric_stats["pm"].p99 for _, r in sweep.corners])
    fc_mean = np.array([r.metric_stats["fc"].mean for _, r in sweep.corners])
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax_pm, ax_fc = axes
    ax_pm.plot(Ts, pm_mean, color="C0", lw=2, marker="o", markersize=5,
               label="PM mean")
    ax_pm.fill_between(Ts, pm_p1, pm_p99, color="C0", alpha=0.15,
                       label="p1-p99 band")
    ax_pm.axhline(0, color="#d62728", linestyle="--", lw=1,
                  label="instability (PM=0°)")
    ax_pm.axhline(5, color="C2", linestyle=":", lw=1, alpha=0.7,
                  label="spec PM>5°")
    ax_pm.axvline(25, color="0.5", linestyle=":", lw=0.6)
    ax_pm.set_ylabel("Phase margin [°]")
    ax_pm.set_title("Marginal LDO Middlebrook phase margin over T")
    ax_pm.legend(fontsize=9); ax_pm.grid(True, alpha=0.3)
    ax_fc.plot(Ts, fc_mean/1e3, color="C1", lw=2, marker="o", markersize=5)
    ax_fc.set_xlabel("ambient T [°C]")
    ax_fc.set_ylabel("loop crossover fc [kHz]")
    ax_fc.set_title("Loop crossover frequency over T")
    ax_fc.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("/tmp/temp_ldo_pm.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("  saved /tmp/temp_ldo_pm.png")


def main():
    chart_sk()
    chart_ldo_ringing()
    chart_ldo_pm()
    print("\nAll three temperature charts saved at /tmp/temp_*.png")


if __name__ == "__main__":
    main()
