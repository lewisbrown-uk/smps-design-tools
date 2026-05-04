"""Temperature analysis on four demo circuits — SK filter, Wien
oscillator, LDO load-step ringing, LDO Middlebrook phase margin.

Each section uses ``temperature_sweep`` (MC at each of many fixed T
points) to map yield(T) and metric(T) curves across the industrial
operating range. Saves a chart per circuit.

The LDO sweeps and Wien sweep use ``active_devices=`` so the
NE5532 op-amp's library tempcos (Vos drift, bipolar Ib doubling,
Avol/GBW drift) and the 2N3904's native ngspice ``.temp`` model
both contribute. The Wien chart is the cleanest demonstration that
the diode-clamp Wien topology is robust against active-device
temperature drift; the LDO charts show the marginal-stability
regulator's loop dynamics shifting with T.

Run all together to see the variety of temperature signatures:

- **SK filter** (closed-form): tempco mismatch between R and C
  drifts the fc mean linearly with T. Q is invariant (it's a ratio
  of components). X7R caps + metal-film R is the killer.
- **Wien** (ngspice tran with lock-in THD): the diode clamp
  decouples loop gain from active-device drift. f0 drift comes
  from passive R/C tempco; vpp and THD show small but measurable
  active-tempco signatures.
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
    lockin_thd_block,
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
    """Common per-component samplers for the LDO sweep.

    Uses ``active_devices`` so the NE5532's DEVICE_TEMPCOS (Vos
    Additive drift, bipolar Ib doubling, Avol/GBW drift) and the
    2N3904's native ngspice ``.temp`` behaviour both contribute.
    Per-component overrides on Resr (uniform over a wide range) and
    on the slow op-amp's GBW (200kHz nominal, ±20%) capture the
    chosen marginal design rather than the textbook NE5532 spread."""
    return dict(
        nominal_values={"Rb": 100, "Cout": 470e-6, "Resr": 1e-3,
                        "Rtop": 10e3, "Rbot": 10e3},
        passive_tolerances={"R": 0.01, "C": 0.20},
        active_devices={"U1": "NE5532", "Q1": "2N3904"},
        distribution={
            # Override the curated NE5532 GBW: this design uses a
            # deliberately slow op-amp (300 kHz) to make the loop
            # marginal — not the typical 10 MHz NE5532.
            "U1_GBW":  RelativeGaussian(nominal_value=300e3, tol=0.20),
            "U1_Avol": RelativeUniform(nominal_value=100e3, tol=0.50),
            "Resr":    Uniform(lo=0.5e-3, hi=5e-3),
        },
        # Passive tempcos add to the device-library tempcos that
        # active_devices=NE5532 brings in automatically.
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


def _wien_template():
    """Wien netlist with .temp injection and lock-in THD measurement.

    Q1 and Q2 are the diode-clamp pair — physically distinct parts,
    so they get independent BF samples via separate model cards
    (Q2N3904_A / Q2N3904_B). ngspice .temp still applies the same
    bandgap-derived V_BE drift to both, which is correct: that part
    of the temperature behaviour really is set by silicon physics,
    not per-part variation. For batch matching add
    ``correlations=[(["Q1_BF", "Q2_BF"], 0.5)]`` to the analyze call."""
    lockin = lockin_thd_block(
        signal="v(out)",
        window=(80e-3, 100e-3),
        f0_init_expr="1/(t2-t1)",
    )
    return f"""* Wien bridge oscillator with lock-in THD measurement and .temp
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

Q1   fb   fb   out  Q2N3904_A
Q2   out  out  fb   Q2N3904_B

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

* Coarse f0 from zero-crossing period (10 cycles apart for accuracy)
meas tran t1 when v(out)=0 fall=20
meas tran t2 when v(out)=0 fall=21

* Peak-to-peak amplitude in the same window the lock-in uses
meas tran amp_max max v(out) from=80m to=100m
meas tran amp_min min v(out) from=80m to=100m

{lockin}
.endc
.end
"""


def chart_wien():
    """Wien bridge oscillator temperature sweep.

    The diode-clamp Wien topology is famously robust against active-
    device variation: the oscillation frequency is set by R1·R2·C1·C2,
    and the amplitude is regulated by the diode clamp rather than the
    op-amp loop gain. Library tempcos for the NE5532 (Vos drift, Ib
    doubling, Avol/GBW drift) and the 2N3904's native ngspice .temp
    behaviour both contribute, but the headline metric (f0) only
    drifts with the passive R/C tempco mismatch."""
    template = _wien_template()
    backend = NgspiceBackend(
        template=template,
        outputs=["t1", "t2", "amp_max", "amp_min",
                 "f_new", "a_rms", "h_rms", "thd", "thd_db"],
        timeout=20,
    )
    cache = "/tmp/temp_wien.sqlite"
    cached = CachedBackend(backend, path=cache)

    def metrics(**v):
        r = cached(**v)
        return {
            "f0":     r.get("f_new", float("nan")),
            "v_pp":   r["amp_max"] - r["amp_min"],
            "thd_db": r["thd_db"],
        }
    metrics.signature = lambda: cached.signature

    T_points = list(range(-40, 86, 25))     # 6 points: -40, -15, 10, 35, 60, 85
    print(f"Wien oscillator temperature sweep "
          f"({len(T_points)} T-points × 100 MC) ...")
    t0 = time.perf_counter()
    sweep = temperature_sweep(
        temperature_points=T_points,
        nominal_values={
            "R1": 10e3, "R2": 10e3,
            "C1": 15.915e-9, "C2": 15.915e-9,
            "Rg": 10e3, "Rfa": 10e3, "Rfb": 12e3,
        },
        passive_tolerances={"R": 0.05, "C": 0.10},
        active_devices={"U1": "NE5532",
                          "Q1": "2N3904", "Q2": "2N3904"},
        metrics=metrics,
        spec={
            "f0":     ("within", 0.05),
            "v_pp":   ("within", 0.10),
            "thd_db": ("<", -20),
        },
        n_mc=100, seed=4242, workers=8,
        # Passive tempcos: NP0 ceramic + metal-film R combo (precision
        # build), so the f0 drift signature is small. Switch to
        # ``"C": 1500e-6`` (X7R) to see a much steeper f0(T) curve.
        temperature_coefficients={"R": 50e-6, "C": 30e-6},
    )
    print(f"  {time.perf_counter()-t0:.1f}s")

    Ts = np.array([T for T, _ in sweep.corners])
    yields = np.array([r.yield_pct for _, r in sweep.corners])
    f0_mean = np.array([r.metric_stats["f0"].mean for _, r in sweep.corners])
    vpp_mean = np.array([r.metric_stats["v_pp"].mean for _, r in sweep.corners])
    thd_mean = np.array([r.metric_stats["thd_db"].mean for _, r in sweep.corners])
    f0_nominal = sweep.corners[0][1].nominal_metrics["f0"]
    vpp_nominal = sweep.corners[0][1].nominal_metrics["v_pp"]

    fig, axes = plt.subplots(4, 1, figsize=(10, 11), sharex=True)
    ax_y, ax_f, ax_v, ax_t = axes
    ax_y.plot(Ts, yields, color="C2", lw=2, marker="o", markersize=5)
    ax_y.axvline(25, color="0.5", linestyle=":", lw=0.6)
    ax_y.set_ylabel("Yield (%)")
    ax_y.set_title("Wien oscillator yield over T  (spec: f0 ±5%, "
                   "v_pp ±10%, THD < −20 dB)")
    ax_y.grid(True, alpha=0.3); ax_y.set_ylim(-3, 103)

    ax_f.plot(Ts, f0_mean, color="C2", lw=2, marker="o", markersize=4)
    ax_f.axhline(f0_nominal, color="black", linestyle="--", lw=0.7,
                 label=f"nominal {f0_nominal:.1f} Hz")
    for v in (f0_nominal*0.95, f0_nominal*1.05):
        ax_f.axhline(v, color="#d62728", linestyle=":", lw=1, alpha=0.7)
    ax_f.set_ylabel("f0 mean [Hz]")
    ax_f.legend(fontsize=9); ax_f.grid(True, alpha=0.3)

    # v_pp panel: this is the binding metric. The 2N3904 diode-clamp
    # V_BE drops ~2 mV/°C with T, shifting the clamp voltage and so
    # v_pp. ngspice .temp handles BJT V_BE drift natively — no library
    # tempco needed for this effect.
    ax_v.plot(Ts, vpp_mean, color="C0", lw=2, marker="o", markersize=4)
    ax_v.axhline(vpp_nominal, color="black", linestyle="--", lw=0.7,
                 label=f"nominal {vpp_nominal:.3f} V")
    for v in (vpp_nominal*0.90, vpp_nominal*1.10):
        ax_v.axhline(v, color="#d62728", linestyle=":", lw=1, alpha=0.7)
    ax_v.set_ylabel("v_pp mean [V]")
    ax_v.legend(fontsize=9); ax_v.grid(True, alpha=0.3)

    ax_t.plot(Ts, thd_mean, color="C3", lw=2, marker="o", markersize=4,
              label="THD+N mean")
    ax_t.axhline(-20, color="#d62728", linestyle=":", lw=1,
                 label="spec −20 dB")
    ax_t.set_xlabel("ambient T [°C]")
    ax_t.set_ylabel("THD+N [dB]")
    ax_t.legend(fontsize=9); ax_t.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("/tmp/temp_wien.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("  saved /tmp/temp_wien.png")


def main():
    chart_sk()
    chart_wien()
    chart_ldo_ringing()
    chart_ldo_pm()
    print("\nAll four temperature charts saved at /tmp/temp_*.png")


if __name__ == "__main__":
    main()
