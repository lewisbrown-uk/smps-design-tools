"""Wien bridge oscillator with lock-in THD measurement.

Shows how to use a non-trivial ngspice .control block — including
inline ``let`` math and ``meas tran avg/rms`` on derived vectors — to
extract scalar metrics that aren't directly supported by the standard
``.meas`` syntax. The technique is the parabolic-fit lock-in
described in (1), translated from LTspice to ngspice.

The pipeline:

1. Find a coarse f0 estimate from zero-crossing period.
2. Project the (DC-removed) settled output onto sin/cos at f0, f0+df,
   f0-df.  Compute the residual RMS at each.
3. Refine f0 by parabolic fit on the three residuals — the residual
   is approximately parabolic in (f - f_actual) near the minimum, so
   ``Δf = -slope/curvature`` corrects the initial estimate.
4. Re-project at the refined f_new, compute the fundamental's RMS
   amplitude (a_rms).
5. The leftover RMS after subtracting the reconstructed fundamental
   is harmonic+noise content (h_rms).
6. THD+N (IEC) = h_rms / (h_rms + a_rms), or in our simpler form
   thd = h_rms / a_rms; convert to dB.

(1) See LTspice example in `utils/tolerance/README.md` discussion;
also classic lock-in detection literature.

Run small first (n_mc=200) to confirm the template works on your
local ngspice install. To scale up, switch ``NgspiceBackend`` to
``RemoteNgspiceBackend(host="...")`` and bump ``n_mc`` and
``workers``.
"""
from __future__ import annotations

import math
import os
import sys
import time

# Add repo root to sys.path so utils.tolerance imports work when run
# as a stand-alone script from anywhere.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tolerance import (
    NgspiceBackend, CachedBackend, analyze,
)


HERE = os.path.dirname(os.path.abspath(__file__))
UOPAMP_LIB = os.path.abspath(os.path.join(
    HERE, "..", "ngspice_examples", "uopamp.lib"
))


def make_template(uopamp_lib_path: str) -> str:
    """Return the parameterised Wien netlist template as a Python
    format string. Placeholders: R1, R2, C1, C2, Rg, Rfa, Rfb (Wien
    + gain network), U1_Vos / U1_Avol / U1_GBW (op-amp), Q1_BF (BJT)."""
    return f"""* Wien bridge oscillator with lock-in THD measurement
.include {uopamp_lib_path}

R1   out  ns      {{R1}}
C1   ns   np      {{C1}}  IC=0
R2   np_eff 0     {{R2}}
C2   np_eff 0     {{C2}}  IC=10m

* Op-amp Vos modelled as series source between Wien node and op-amp +
Vos1 np   np_eff  {{U1_Vos}}

Rg   nn   0       {{Rg}}
Rfa  nn   fb      {{Rfa}}
Rfb  fb   out     {{Rfb}}

* Diode-clamp NPN pair sets the loop gain at oscillation amplitude
Q1   fb   fb   out  Q2N3904
Q2   out  out  fb   Q2N3904

Vcc  vcc 0  15
Vee  vee 0 -15

XU1  np nn vcc vee out uopamp_lvl2
+    Avol={{U1_Avol}} GBW={{U1_GBW}} Rin=100k Rout=30 Iq=8m
+    Ilimit=1 Vrail=1.4 Vmax=40

.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF={{Q1_BF}}
+ NE=1.259 ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0
+ IKR=0 RC=1 CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p
+ MJE=.2593 VJE=.75 TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)

.tran 1u 100m UIC

.control
run

* Coarse f0 from zero-crossing period (10 cycles apart for accuracy)
meas tran t1 when v(out)=0 fall=20
meas tran t2 when v(out)=0 fall=21
meas tran amp_max max v(out) from=80m to=100m
meas tran amp_min min v(out) from=80m to=100m
let f0_est = 1/(t2 - t1)
let df_probe = 0.01 * f0_est

* DC level of the settled output in the measurement window
meas tran v_dc avg v(out) from=80m to=100m

* Project onto sin/cos at f0_est, f0_est + df, f0_est - df
let basis_sin0 = sin(2*3.14159265*f0_est*time)
let basis_cos0 = cos(2*3.14159265*f0_est*time)
let basis_sinp = sin(2*3.14159265*(f0_est+df_probe)*time)
let basis_cosp = cos(2*3.14159265*(f0_est+df_probe)*time)
let basis_sinm = sin(2*3.14159265*(f0_est-df_probe)*time)
let basis_cosm = cos(2*3.14159265*(f0_est-df_probe)*time)

let psi0 = 2*(v(out)-v_dc)*basis_sin0
let pco0 = 2*(v(out)-v_dc)*basis_cos0
let psip = 2*(v(out)-v_dc)*basis_sinp
let pcop = 2*(v(out)-v_dc)*basis_cosp
let psim = 2*(v(out)-v_dc)*basis_sinm
let pcom = 2*(v(out)-v_dc)*basis_cosm
meas tran sin0 avg psi0 from=80m to=100m
meas tran cos0 avg pco0 from=80m to=100m
meas tran sinp avg psip from=80m to=100m
meas tran cosp avg pcop from=80m to=100m
meas tran sinm avg psim from=80m to=100m
meas tran cosm avg pcom from=80m to=100m

* Residuals at each probed frequency
let r0v = v(out) - v_dc - sin0*basis_sin0 - cos0*basis_cos0
let rpv = v(out) - v_dc - sinp*basis_sinp - cosp*basis_cosp
let rmv = v(out) - v_dc - sinm*basis_sinm - cosm*basis_cosm
meas tran res0 rms r0v from=80m to=100m
meas tran resp rms rpv from=80m to=100m
meas tran resm rms rmv from=80m to=100m

* Parabolic fit: refined frequency = f0_est - slope/curvature
let f_new = f0_est - ((resp - resm)/(2*df_probe)) * df_probe^2 / (resp - 2*res0 + resm)

* Final projection at refined frequency
let basis_sin = sin(2*3.14159265*f_new*time)
let basis_cos = cos(2*3.14159265*f_new*time)
let psi = 2*(v(out)-v_dc)*basis_sin
let pco = 2*(v(out)-v_dc)*basis_cos
meas tran sin_out avg psi from=80m to=100m
meas tran cos_out avg pco from=80m to=100m

let a_rms = sqrt(sin_out^2 + cos_out^2)/sqrt(2)
let residual = v(out) - v_dc - sin_out*basis_sin - cos_out*basis_cos
meas tran h_rms rms residual from=80m to=100m
let thd = h_rms / a_rms
let thd_db = 20*log10(thd)

print f_new a_rms h_rms thd thd_db
.endc
.end
"""


def make_metrics(backend):
    """Wrap the ngspice backend so it returns the user-facing metric
    names (f0, v_pp, a_rms, thd_db) derived from the raw simulator
    outputs."""
    def metrics(**values):
        r = backend(**values)
        period = r["t2"] - r["t1"]
        return {
            "f0":     r.get("f_new", float("nan")),
            "v_pp":   r["amp_max"] - r["amp_min"],
            "a_rms":  r["a_rms"],
            "thd_db": r["thd_db"],
        }
    metrics.signature = lambda: backend.signature
    return metrics


def main():
    template = make_template(UOPAMP_LIB)

    # Cache so re-runs with the same component values are instant.
    # Persistent across invocations; delete the file to force a fresh sweep.
    raw = NgspiceBackend(
        template=template,
        outputs=["t1", "t2", "amp_max", "amp_min",
                 "f_new", "a_rms", "h_rms", "thd", "thd_db"],
        timeout=20,
    )
    cached = CachedBackend(raw, path="/tmp/wien_thd_example.sqlite")

    metrics = make_metrics(cached)

    # E12 Butterworth-style nominal: R1=R2=10k, C1=C2=15.915n → f0 ≈ 1 kHz
    # Passives only — analyze() will inject the active-device samples
    # later via active_devices=.
    nominal = {
        "R1": 10e3, "R2": 10e3,
        "C1": 15.915e-9, "C2": 15.915e-9,
        "Rg": 10e3, "Rfa": 10e3, "Rfb": 12e3,
    }

    # Defaults for the active params so the bare-nominal sanity call
    # below works without active_devices in the loop. analyze() will
    # override these per-sample.
    nom_active_defaults = {
        "U1_Vos": 0.0, "U1_Ib": 200e-9,
        "U1_Avol": 100e3, "U1_GBW": 10e6,
        "Q1_BF": 250,
    }
    nom = metrics(**nominal, **nom_active_defaults)
    print("Nominal Wien (no tolerance):")
    print(f"  f0      = {nom['f0']:.2f} Hz")
    print(f"  v_pp    = {nom['v_pp']:.4f} V  (diode clamp ~ ±1.8 V)")
    print(f"  a_rms   = {nom['a_rms']:.4f} V  (RMS of fundamental)")
    print(f"  thd_db  = {nom['thd_db']:.2f} dB  (raw diode-clamped Wien)")
    print()

    # MC: 5% R, 10% C, plus NE5532 op-amp + 2N3904 BJT spreads.
    # The diode clamp decouples Wien performance from active-device
    # spread — see the slice 3 demo discussion for the quantitative
    # confirmation at n=100k.
    n_mc = 200
    print(f"Running {n_mc}-sample MC, 5%R / 10%C + NE5532 + 2N3904 spreads ...")
    t0 = time.perf_counter()
    report = analyze(
        nominal_values=nominal,
        passive_tolerances={"R": 0.05, "C": 0.10},
        active_devices={"U1": "NE5532", "Q1": "2N3904"},
        metrics=metrics,
        spec={
            "f0":     ("within", 0.05),     # ±5%
            "v_pp":   ("within", 0.10),     # ±10%
            "thd_db": ("<", -20),           # better than -20 dB
        },
        n_mc=n_mc, seed=4242, workers=8,
    )
    dt = time.perf_counter() - t0
    print(f"  {dt:.1f}s  ({n_mc/dt:.1f} samples/s)\n")
    print(report)


if __name__ == "__main__":
    main()
