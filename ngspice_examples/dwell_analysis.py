"""How long is the over-temperature excursion during a fault?
Inject XU_buf-stuck (worst overheat) with overpower_protect ON, capture T(t),
report dwell above thresholds + rise/fall profile. iv18 = worst peak (937K)."""
import sys, subprocess, re, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = sys.argv[1] if len(sys.argv) > 1 else "iv18"
WORK = f"/tmp/dwell_{TUBE}"; os.makedirs(WORK, exist_ok=True)
T_END, T_INJ = 5.0, 3.0
cir = r.make_netlist(overpower_protect=True, T_end=T_END, **r.TUBES[TUBE])
cir = cir.replace(".tran",
    f"B_xubuf n_buf_o nf_xubuf I = V(n_buf_o,nf_xubuf)/(time < {T_INJ} ? 1e9 : 0.05)\n"
    f"V_xubuf nf_xubuf 0 9.9\n.tran", 1)
# tighten max timestep so the ms-scale event is well resolved
cir = re.sub(r"\.tran 50u (\S+) 0 uic", r".tran 20u \1 0 uic", cir)
cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/run.data", cir)
open(f"{WORK}/run.cir", "w").write(cir)
p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=WORK, capture_output=True, text=True, timeout=900)
if not os.path.exists(f"{WORK}/run.data"):
    print("NO DATA:", (p.stderr+p.stdout)[-300:]); sys.exit(1)
d = np.loadtxt(f"{WORK}/run.data")
t = d[:, 0]; T = d[:, 9]; n_disc = d[:, 23]
T_op = np.mean(T[(t > 2.5) & (t < 3.0)])     # pre-fault operating temp
i_inj = np.searchsorted(t, T_INJ)
i_pk = i_inj + int(np.argmax(T[i_inj:]))
t_pk, T_pk = t[i_pk], T[i_pk]
t_trip = t[np.argmax(n_disc > 2.5)] if np.max(n_disc) > 2.5 else float("nan")

def dwell(thr):
    m = (t >= T_INJ) & (T > thr)
    return float(np.sum(np.diff(t)[m[:-1]])) if m.any() else 0.0

def cool_to(target):  # time from peak back down to target
    post = t[i_pk:]; Tp = T[i_pk:]
    below = np.where(Tp <= target)[0]
    return float(post[below[0]] - t_pk) if len(below) else float("nan")

print(f"{TUBE}: T_op={T_op:.0f}K  fault@{T_INJ}s  disconnect@{(t_trip-T_INJ)*1e3:.1f}ms  peak={T_pk:.0f}K @{(t_pk-T_INJ)*1e3:.0f}ms")
print(f"  dwell above 800K: {dwell(800)*1e3:.0f} ms   850K: {dwell(850)*1e3:.0f} ms   900K: {dwell(900)*1e3:.0f} ms")
print(f"  cool peak->850K: {cool_to(850)*1e3:.0f} ms   ->800K: {cool_to(800)*1e3:.0f} ms   ->700K: {cool_to(700)*1e3:.0f} ms   ->500K: {cool_to(500)*1e3:.0f} ms")
print("  T(t) around the event:")
for tt in [2.99, 3.00, 3.005, 3.01, 3.02, 3.05, 3.1, 3.2, 3.4, 3.7, 4.0, 4.5]:
    i = np.searchsorted(t, tt)
    if i < len(t): print(f"    t-3s={ (t[i]-3)*1e3:7.1f}ms  T={T[i]:6.0f}K")
