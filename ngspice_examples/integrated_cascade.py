"""Integrated filament-driver cascade: real Wien oscillator -> filament regulator.

Replaces regulator's behavioral B_src (a sine with a soft-start envelope)
with the actual 2-NPN-symmetric-clamp Wien oscillator (the one in
wien_oscillator.py / test_closed_loop.py), and adds a V_clamp_hi drive-ceiling
soft-start to recover the cold-start overshoot the behavioral envelope had been
providing.

Findings (2026-05-31, ILC1-1/7, Fix A regulator defaults):
  - Cascade regulates on target: T=802 K, R_fil=25.1, V_int=+1.61 (in range).
  - Filament THD = 2.7 % (H3 from the oscillator's soft-clip, propagates ~1:1
    through the drive path), but the regulator ADDS only ~0.4 pp and H2 stays
    killed at -66 dB (the symmetric-clamp win survives the cascade). So the
    original h11f_h2_tradeoff H2 concern is resolved end-to-end.
  - Cold-start overshoot: the real clamp Wien starts in ~tens of ms (no
    soft-start), giving +27.7 K. A V_clamp_hi ramp (1.8 -> 4.0 V over 2 s, a
    slow RC on the integrator clamp reference in hardware) cuts it to +10 K
    (tunable toward the +7 K the behavioral tau_src=2 s gave). The rail-ramp
    soft-start (t_rail_ramp) is NOT viable -- it triggers a timestep-collapse
    convergence failure at the diff-amp.
  - Robust to the worst-N Vos patterns: 21 worst cube cases all give THD
    -31 dB (no cliff), V_int +1.53..1.65 (no railing), H2 -64..-69 dB,
    overshoot +10 K. Fix A's cliff fix holds with the real oscillator in loop.

NOTE: the Wien clamp amplitude is V_BE-bound -> ~-0.45 %/C tempco and dies
>60 C in sim (see wien_clamp_temp_fragility memory); the SPICE H11F temp model
is an approximate fit, so treat those temp numbers as bench-check flags, not
facts. Supply PSRR of the clamp amplitude is excellent (topological).
"""
import sys, subprocess, re
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import regulator as s5

# Q2N3904 model (from test_closed_loop.py) for the Wien clamp transistors.
Q2N3904 = """.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)"""

# Real Wien bridge oscillator with the symmetric two-NPN amplitude clamp.
# Output node = v_src (feeds the regulator's attenuator). Op-amp on the
# regulator's buffered rails. Internal nodes prefixed w_ to avoid collisions.
WIEN = """
* === Real Wien bridge oscillator (2-NPN symmetric clamp, alpha=0.5) -> v_src ===
XU_wien w_plus w_minus vcc_buf vee_buf v_src uopamp_lvl3 Avol=1meg GBW=10meg Rin=100g Rout=10 Iq=2m Ilimit=20m Vos=0
R1_w v_src w_ns 10k
C1_w w_ns w_plus 15.915n IC=0
R2_w w_plus 0 10k
C2_w w_plus 0 15.915n IC=10m
Rg_w w_minus 0 10k
Rfa_w w_minus w_fb 10k
Rfb_w w_fb v_src 12k
Q1_w w_fb w_b1 v_src Q2N3904
Q2_w v_src w_b2 w_fb Q2N3904
Rtop1_w w_fb w_b1 120k
Rbot1_w w_b1 v_src 120k
Rtop2_w v_src w_b2 120k
Rbot2_w w_b2 w_fb 120k
"""


def build(R_atten_top=330e3, T_end=20.0, softstart=True, vos_zero=True):
    """Build the integrated cascade netlist.

    R_atten_top rescaled to 330k (vs Fix A's 12k) because the real Wien outputs
    ~2.5 V_rms vs the behavioral source's 0.1 V_rms -- keeps v_atten at the
    regulator's design level.  softstart=True ramps V_clamp_hi 1.8 -> 4.0 V over
    2 s (the working drive-ceiling soft-start).
    """
    cir = s5.make_netlist(t_src_ramp=2.0, T_end=T_end, R_atten_top=R_atten_top)
    # drop the behavioral B_src; insert the Q model + real Wien before .tran
    cir = "\n".join(l for l in cir.splitlines() if not l.startswith("B_src v_src"))
    cir = cir.replace(".tran", Q2N3904 + "\n" + WIEN + "\n.tran", 1)
    if softstart:
        cir = re.sub(r"V_clamp_hi v_clamp_hi 0 \S+",
                     "V_clamp_hi v_clamp_hi 0 PWL(0 1.8 2 4.0 100 4.0)", cir)
    if vos_zero:
        cir = cir.replace("Vos=10u", "Vos=0")
    return cir


def main():
    work = Path("/tmp/integrated_cascade_work"); work.mkdir(exist_ok=True)
    cir = build()
    dat = work / "run.data"
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {dat.as_posix()}", cir)
    (work / "run.cir").write_text(cir)
    print("Running integrated cascade cold-start (T_end=20s)...", flush=True)
    r = subprocess.run(["ngspice", "-b", "run.cir"], cwd=work,
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        print("FAIL:", r.stderr[-600:]); return
    d = np.loadtxt(dat)
    t = d[:, 0]; v_osc = d[:, 1]; node_A = d[:, 3]; v_int = d[:, 7]
    T = d[:, 9]; r_fil = d[:, 11]
    v_fil = v_osc - node_A
    m = t > t[-1] - 1
    print(f"overshoot = {np.max(T)-800:+.1f} K @ t={t[int(np.argmax(T))]:.2f}s")
    print(f"T_final   = {np.mean(T[m]):.1f} K   R_fil = {r_fil[-1]:.3f}   "
          f"V_int = {np.mean(v_int[m]):+.3f} (std {np.std(v_int[m]):.4f})")
    print(f"V_fil RMS = {np.std(v_fil[m]):.3f} V")


if __name__ == "__main__":
    main()
