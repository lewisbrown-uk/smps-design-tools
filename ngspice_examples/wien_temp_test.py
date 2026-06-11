"""Is the Wien 'dies >60°C' the SAME uic+temp convergence artifact as the
regulator's 50°C failure, or a REAL amplitude collapse?

Distinguish the two modes per temperature:
  (a) ARTIFACT  -> no data / 'timestep too small; initial timepoint' at t~0
  (b) REAL DEATH-> sim runs, but the oscillation envelope decays toward 0
  (c) ALIVE     -> sustained envelope (amplitude may shrink with temp = the real
                   -0.45%/°C tempco, but it keeps oscillating)

Self-contained 2-NPN/diode-clamp Wien (copy of wien_envelope.py's netlist).
Writes wien_temp_test.txt."""
import subprocess, os, re
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
UOPAMP = f"{HERE}/uopamp.lib"
OUT = f"{HERE}/wien_temp_test.txt"
OP = "uopamp_lvl3 Avol=1meg GBW=10meg Rin=100g Rout=10 Iq=2m Ilimit=20m Vos=0"
Q3904 = """.model Q2N3904 NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259
+ ISE=6.734f IKF=66.78m XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1
+ CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p MJE=.2593 VJE=.75
+ TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)"""
R_TOT = 240e3; rtop = 0.5*R_TOT; rbot = 0.5*R_TOT
lines = []
def log(s): lines.append(s); print(s, flush=True)

for temp in [25, 50, 60, 70, 80]:
    W = f"/tmp/wtt_{temp}"; os.makedirs(W, exist_ok=True)
    cir = f"""* Wien temp test
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
.tran 20u 1.0 0 uic
.options reltol=1e-4 abstol=1n vntol=1u
.save v(v_osc)
.control
run
wrdata {W}/w.data v(v_osc)
.endc
.end
"""
    open(f"{W}/w.cir", "w").write(cir)
    try:
        p = subprocess.run(["ngspice", "-b", "w.cir"], cwd=W, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        log(f"temp={temp}: TIMEOUT"); continue
    blob = p.stderr + p.stdout
    collapse = "Timestep too small" in blob or "initial timepoint" in blob
    if not os.path.exists(f"{W}/w.data"):
        kw = [l.strip()[:90] for l in blob.splitlines() if re.search(r"too small|initial|abort|singular|converg", l, re.I)]
        log(f"temp={temp}: NO DATA  -> {'ARTIFACT (uic timestep collapse)' if collapse else 'no-data'}  {kw[-1] if kw else ''}")
        continue
    d = np.loadtxt(f"{W}/w.data"); t = d[:, 0]; v = d[:, 1]
    def env(a, b):
        m = (t >= a) & (t < b)
        return float(np.max(np.abs(v[m]))) if m.any() else 0.0
    early = env(0.3, 0.4)        # after startup
    late = env(0.9, 1.0)         # near the end
    last_reached = t[-1]
    if last_reached < 0.99:
        verdict = f"ABORTED at {last_reached*1e3:.1f}ms ({'ARTIFACT timestep collapse' if collapse else 'mid-run abort'})"
    elif late < 0.2*early:
        verdict = f"REAL DEATH (envelope {early:.3f}->{late:.3f}V, decayed)"
    else:
        verdict = f"ALIVE (envelope {early:.3f}->{late:.3f}V sustained)"
    log(f"temp={temp}: data=YES  {verdict}")

open(OUT, "w").write("\n".join(lines) + "\n")
print("WROTE", OUT, flush=True)
