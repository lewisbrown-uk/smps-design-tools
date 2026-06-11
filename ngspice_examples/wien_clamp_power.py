"""Measure the dissipation in the Wien clamp transistors (Q1/Q2), so we can turn
junction-temperature concern into a number: T_j = T_ambient + theta_JA * P.
If P is sub-mW, T_j ~= ambient and the ~65C oscillator death needs ~65C AMBIENT
(unrealistic for a VFD clock), not self-heating."""
import subprocess, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
UOPAMP = f"{HERE}/uopamp.lib"
OUT = f"{HERE}/wien_clamp_power.txt"
OP = "uopamp_lvl3 Avol=1meg GBW=10meg Rin=100g Rout=10 Iq=2m Ilimit=20m Vos=0"
Q3904 = """.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)"""
rtop = rbot = 120e3
THETA_JA = 300.0   # SOT-23 (MMBT3904-class), deg C / W, rough
lines = []
def log(s): lines.append(s); print(s, flush=True)

for temp in [25, 60]:
    W = f"/tmp/wcp_{temp}"; os.makedirs(W, exist_ok=True)
    cir = f"""* Wien clamp power
.include {UOPAMP}
{Q3904}
.options temp={temp}
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
.tran 20u 0.8 0 uic
.options reltol=1e-4 abstol=1n vntol=1u
.save v(v_osc) @q1[p] @q2[p] @q1[ic] @q2[ic]
.control
run
wrdata {W}/p.data v(v_osc) @q1[p] @q2[p] @q1[ic] @q2[ic]
.endc
.end
"""
    open(f"{W}/p.cir", "w").write(cir)
    p = subprocess.run(["ngspice", "-b", "p.cir"], cwd=W, capture_output=True, text=True, timeout=300)
    if not os.path.exists(f"{W}/p.data"):
        log(f"temp={temp}: NO DATA  {(p.stderr+p.stdout)[-200:]}"); continue
    d = np.loadtxt(f"{W}/p.data")
    # columns: t, v_osc, t, pq1, t, pq2, t, icq1, t, icq2
    t = d[:, 0]; vosc = d[:, 1]; pq1 = d[:, 3]; pq2 = d[:, 5]; icq1 = d[:, 7]; icq2 = d[:, 9]
    m = t > 0.7   # steady-state window (a few cycles)
    amp = float(np.max(np.abs(vosc[m])))
    p1_avg = float(np.mean(np.abs(pq1[m]))); p2_avg = float(np.mean(np.abs(pq2[m])))
    p1_pk = float(np.max(np.abs(pq1[m]))); p2_pk = float(np.max(np.abs(pq2[m])))
    ic_pk = float(max(np.max(np.abs(icq1[m])), np.max(np.abs(icq2[m]))))
    p_tot = p1_avg + p2_avg
    log(f"=== temp={temp}C, Wien amplitude {amp:.2f}V ===")
    log(f"  Q1 avg/peak power : {p1_avg*1e3:.3f} / {p1_pk*1e3:.3f} mW")
    log(f"  Q2 avg/peak power : {p2_avg*1e3:.3f} / {p2_pk*1e3:.3f} mW")
    log(f"  peak clamp Ic     : {ic_pk*1e3:.2f} mA")
    log(f"  T_j rise (theta_JA={THETA_JA:.0f}): {p_tot*THETA_JA*1e3:.3f} mC  "
        f"(=> junction ~= ambient + {p_tot*THETA_JA:.4f} C)")

open(OUT, "w").write("\n".join(lines) + "\n")
print("WROTE", OUT, flush=True)
