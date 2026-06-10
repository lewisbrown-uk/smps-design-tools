"""Capture fault T(t) trajectories (realistic tau, protection ON) for charting.
Writes traj_<tube>.csv with columns: t_ms (relative to fault), T."""
import sys, subprocess, re, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

T_INJ, T_END = 2.5, 3.5   # settled by <1s at realistic tau; capture to +1000ms
for tube in (sys.argv[1:] or ["ilc11_7", "iv6", "iv18", "ilc11_8"]):
    W = f"/tmp/ct_{tube}"; os.makedirs(W, exist_ok=True)
    cir = r.make_netlist(overpower_protect=True, T_end=T_END, **r.TUBES[tube])
    cir = cir.replace(".tran", f"B_xubuf n_buf_o nf_xubuf I = V(n_buf_o,nf_xubuf)"
                      f"/(time < {T_INJ} ? 1e9 : 0.05)\nV_xubuf nf_xubuf 0 9.9\n.tran", 1)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {W}/run.data", cir)  # keep 50us default
    open(f"{W}/run.cir", "w").write(cir)
    subprocess.run(["ngspice", "-b", "run.cir"], cwd=W, capture_output=True, text=True, timeout=900)
    d = np.loadtxt(f"{W}/run.data"); t = d[:, 0]; T = d[:, 9]
    rel = (t - T_INJ) * 1e3  # ms
    m = (rel >= -50) & (rel <= 800)   # the excursion window
    rel, T = rel[m], T[m]
    # downsample: dense near the peak, sparse on the tail
    if len(rel) > 700:
        dense = np.where((rel >= -5) & (rel <= 200))[0][::3]
        sparse = np.linspace(0, len(rel)-1, 250).astype(int)
        idx = np.unique(np.concatenate([dense, sparse]))
        rel, T = rel[idx], T[idx]
    out = f"/home/debian/sim/ngspice_examples/traj_{tube}.csv"
    np.savetxt(out, np.column_stack([rel, T]), fmt="%.3f", header="t_ms,T_K", comments="")
    print(f"{tube}: peak {T.max():.0f}K, {len(rel)} pts -> {out}")
