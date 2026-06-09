"""Capture the REAL startup amplitude envelope of the 2-NPN clamp Wien oscillator
(the one we actually use), so we can drive the main regulator sim with the true
envelope instead of the unrealistic exp(-t/0.6s) ramp.

Self-contained copy of the Wien netlist from wien_oscillator.py (which has no
__main__ guard, so importing it runs its whole characterization).
"""
import subprocess, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
UOPAMP = f"{HERE}/uopamp.lib"
WORK = "/tmp/wien_env"; os.makedirs(WORK, exist_ok=True)
OP = "uopamp_lvl3 Avol=1meg GBW=10meg Rin=100g Rout=10 Iq=2m Ilimit=20m Vos=0"
Q3904 = """.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)"""
R_TOT = 240e3; T_END = 1.5; alpha = 0.5
rtop = (1 - alpha) * R_TOT; rbot = alpha * R_TOT

cir = f"""* Wien startup envelope
.include {UOPAMP}
{Q3904}
.options temp=25
B_vcc vcc 0 V = 9
B_vee vee 0 V = -9
R1 v_osc ns 10k
C1 ns np 15.915n IC=0
R2 np 0 10k
C2 np 0 15.915n IC=10m
Rg nn 0 10e3
Rfa nn fb 10k
Rfb fb v_osc 12e3
Q1 fb b1 v_osc Q2N3904
Q2 v_osc b2 fb Q2N3904
Rtop1 fb b1 {rtop:.6g}
Rbot1 b1 v_osc {rbot:.6g}
Rtop2 v_osc b2 {rtop:.6g}
Rbot2 b2 fb {rbot:.6g}
XU_osc np nn vcc vee v_osc {OP}
.tran 20u {T_END} 0 uic
.options reltol=1e-4 abstol=1n vntol=1u
.save v(v_osc)
.control
run
wrdata {WORK}/env.data v(v_osc)
.endc
.end
"""
open(f"{WORK}/env.cir", "w").write(cir)
subprocess.run(["ngspice", "-b", "env.cir"], cwd=WORK, capture_output=True, text=True, timeout=200)
d = np.loadtxt(f"{WORK}/env.data"); t = d[:, 0]; v = d[:, 1]

# per-cycle peak envelope via a vectorized sliding max would be ideal; use a coarse
# grid (every 0.5ms) of windowed max -- fast and plenty for an envelope.
tg = np.arange(0, t[-1], 0.5e-3)
e = np.array([np.max(np.abs(v[(t >= g) & (t < g + 1e-3)])) if ((t >= g) & (t < g + 1e-3)).any()
              else np.nan for g in tg])
A_ss = np.nanmean(e[tg > T_END - 0.2])
en = e / A_ss
within = np.abs(en - 1.0) < 0.02
t_settle = next((tg[i] for i in range(len(tg)) if np.all(within[i:][~np.isnan(en[i:])])), float("nan"))
t90 = tg[np.nanargmax(en > 0.90)] if (en > 0.90).any() else float("nan")
t99 = tg[np.nanargmax(en > 0.99)] if (en > 0.99).any() else float("nan")

print("Wien 2-NPN clamp startup envelope (kickstart C2 IC=10mV):")
print(f"  steady amplitude   = {A_ss:.4f} V")
print(f"  reach 90% at       = {t90*1e3:.1f} ms  ({t90/1e-3:.1f} cycles)")
print(f"  reach 99% at       = {t99*1e3:.1f} ms  ({t99/1e-3:.1f} cycles)")
print(f"  settle (+/-2%) at  = {t_settle*1e3:.1f} ms  ({t_settle/1e-3:.1f} cycles)")
print("  --- normalized envelope ---")
for tt in [0.002, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.2, 0.3]:
    i = np.argmin(np.abs(tg - tt))
    print(f"   t={tt*1e3:5.1f} ms   env={en[i]:.3f}")

ts = np.arange(0, min(0.4, t[-1]), 1e-3)
es = np.clip(np.interp(ts, tg, en), 0, None)
pwl = " ".join(f"{a:.5f} {b:.4f}" for a, b in zip(ts, es)) + " 100 1.0"
open(f"{WORK}/env_pwl.txt", "w").write(pwl)
print(f"\n  wrote {len(ts)}-point normalized-envelope PWL -> {WORK}/env_pwl.txt")
