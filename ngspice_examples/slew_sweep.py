"""Slew-limited op-amp: calibrate + THD-vs-carrier sweep.

The validation battery uses uopamp_lvl3, which models NO slew limit (linear
gm-C). Real OPA4277 = 0.8 V/us. This:
  1) calibrates uopamp_lvl3_slew's Islew so the OUTPUT slews at 0.8 V/us @ 1 MHz GBW;
  2) sweeps the carrier frequency for ILC1-1/7 (8.5 V drive swing, slew-prone)
     and IV-18 (~1 V swing, slew-immune control), slew-limited vs nominal,
     measuring filament-drive THD -- showing the slew wall the linear model misses.
Thread-safe: builds with the default carrier then string-replaces the B_src
frequency (NOT the r.F0 global, which would race across threads).
ngspice on simhost.  -> slew_sweep.md
"""
import sys, os, re, subprocess, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import regulator as r
import overnight_battery as ob

ROOT = "/tmp/slew"; os.makedirs(ROOT, exist_ok=True)
REPORT = os.path.join(HERE, "slew_sweep.md")
TARGET_SR = 0.8e6                     # V/s (OPA4277)
OPMATCH = "uopamp_lvl3 Avol=5meg"     # the op string in every X-line
FREQ_RE = re.compile(r"(sin\(2\*3\.141592653589793\*)1000\.0(\*time\))")

def ngrun(net, work):
    os.makedirs(work, exist_ok=True)
    open(f"{work}/x.cir", "w").write(net)
    subprocess.run(["ngspice", "-b", "x.cir"], cwd=work, capture_output=True, text=True, timeout=900)
    fp = f"{work}/x.data"
    if not os.path.exists(fp): return None
    d = np.loadtxt(fp); os.remove(fp); return d

# ---- 1. calibrate Islew -> 0.8 V/us (unity follower, 5 V step) ----
def measure_sr(islew):
    net = f""".include {HERE}/uopamp.lib
XU vin vout vcc vee vout uopamp_lvl3_slew Avol=5meg GBW=1meg Rin=100g Rout=10 Iq=800u Ilimit=25m Vos=0 Vmax=30 Vrail=0.1 Islew={islew:.6g}
Vin vin 0 PWL(0 0 1u 0 1.001u 5 1 5)
Vcc vcc 0 10
Vee vee 0 -10
.tran 1n 8u 0 uic
.control
run
wrdata {ROOT}/cal_{islew:.4g}/x.data v(vout)
.endc
.end
"""
    d = ngrun(net, f"{ROOT}/cal_{islew:.4g}")
    if d is None: return float("nan")
    t, v = d[:, 0], d[:, 1]
    slope = np.diff(v) / np.diff(t)
    m = (v[:-1] > 1) & (v[:-1] < 4)            # slew region of the 0->5V rise
    return float(np.max(slope[m])) if m.any() else float("nan")

def calibrate():
    cands = [60e-9, 90e-9, 120e-9, 150e-9, 200e-9, 300e-9]
    pts = [(i, measure_sr(i)) for i in cands]
    xs = np.array([i for i, _ in pts]); ys = np.array([s for _, s in pts])
    k = np.polyfit(xs, ys, 1)                  # SR ~ k0*Islew + k1 (near-linear)
    islew = float((TARGET_SR - k[1]) / k[0])
    return islew, pts, measure_sr(islew)

# ---- 2. carrier sweep ----
def sweep_cell(tube, F, slew, islew):
    try:
        T_END = 2.0
        cir = r.make_netlist(T_end=T_END, **r.TUBES[tube])      # default carrier 1 kHz
        cir = FREQ_RE.sub(rf"\g<1>{F}\g<2>", cir)               # retarget carrier (thread-safe)
        maxstep = min(50e-6, 1.0 / (15 * F))                   # ~15 samples/carrier (THD-adequate)
        cir = re.sub(r"\.tran \S+ \S+ 0 uic", f".tran {maxstep:.4g} {T_END} 0 uic", cir)
        if slew:
            cir = cir.replace(OPMATCH, f"uopamp_lvl3_slew Islew={islew:.6g} Avol=5meg")
        work = f"{ROOT}/{tube}_{int(F)}_{'s' if slew else 'n'}"
        cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {work}/x.data", cir)
        d = ngrun(cir, work)
        if d is None: return None
        t, vdrive, nodeA = d[:, 0], d[:, 1], d[:, 3]
        return ob.thd_db(t, vdrive - nodeA, 1.3, T_END, f_seed=float(F))
    except Exception:
        return None

def main():
    t0 = time.time()
    islew, pts, sr_chk = calibrate()
    TUBES = ["ilc11_7", "iv18"]
    FREQS = [1000, 2000, 5000, 10000, 15000, 20000]
    tasks = [(tb, F, sl) for tb in TUBES for F in FREQS for sl in (False, True)]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {(tb, F, sl): ex.submit(sweep_cell, tb, F, sl, islew) for tb, F, sl in tasks}
        out = {k: v.result() for k, v in futs.items()}

    L = [f"\n# Slew-limited op-amp THD-vs-carrier  {time.ctime()}\n"]
    L.append(f"Calibrated `uopamp_lvl3_slew` Islew = **{islew*1e9:.1f} nA** -> output "
             f"SR = {sr_chk/1e6:.3f} V/us (target 0.8, OPA4277) @ GBW 1 MHz.")
    L.append("Calibration points (Islew nA -> SR V/us): " +
             ", ".join(f"{i*1e9:.0f}->{s/1e6:.2f}" for i, s in pts) + "\n")
    L.append("THD (dB) of the filament drive vs carrier frequency:\n")
    L.append("| tube | model | " + " | ".join(f"{F//1000} kHz" for F in FREQS) + " |")
    L.append("|---|---|" + "---|" * len(FREQS))
    for tb in TUBES:
        for sl, lab in ((False, "nominal (no-slew)"), (True, "slew 0.8 V/us")):
            cells = " | ".join(f"{(out.get((tb,F,sl)) if out.get((tb,F,sl)) is not None else float('nan')):.1f}" for F in FREQS)
            L.append(f"| {tb} | {lab} | {cells} |")
    L.append(f"\n_calibrate + {len(tasks)} sweeps in {time.time()-t0:.0f}s_\n")
    open(REPORT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))

if __name__ == "__main__":
    main()
