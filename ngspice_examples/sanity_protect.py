"""Quick sanity of the BUILT-IN overpower_protect path in regulator.py."""
import sys, subprocess, re, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = sys.argv[1] if len(sys.argv) > 1 else "iv6"
MODE = sys.argv[2] if len(sys.argv) > 2 else "fault"
WORK = f"/tmp/sp_{TUBE}_{MODE}"; os.makedirs(WORK, exist_ok=True)
T_END, T_INJ = 6.0, 3.0
cir = r.make_netlist(overpower_protect=True, T_end=T_END, **r.TUBES[TUBE])
if MODE == "fault":
    cir = cir.replace(".tran",
                      f"B_xubuf n_buf_o nf_xubuf I = V(n_buf_o,nf_xubuf)"
                      f"/(time < {T_INJ} ? 1e9 : 0.05)\nV_xubuf nf_xubuf 0 9.9\n.tran", 1)
cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/run.data", cir)
open(f"{WORK}/run.cir", "w").write(cir)
p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=WORK, capture_output=True, text=True, timeout=1200)
fp = f"{WORK}/run.data"
if not os.path.exists(fp):
    print("NO DATA:\n", (p.stderr + p.stdout)[-700:]); sys.exit(1)
d = np.loadtxt(fp)
t = d[:, 0]; T = d[:, 9]; n_disc = d[:, 23]  # overpower_save: n_disc_op=23
tripped = bool(np.max(n_disc) > 2.5)
t_trip = float(t[np.argmax(n_disc > 2.5)]) if tripped else float("nan")
print(f"{TUBE}/{MODE}: disc_latched={tripped}" + (f"@{t_trip:.3f}s" if tripped else "")
      + f"  finalT={np.mean(T[t>T_END-0.3]):.1f}K  peakT={np.max(T):.1f}K")
