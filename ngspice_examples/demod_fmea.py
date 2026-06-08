"""Demod-component FMEA on the hardware commutating-switch demod.

Injects single failures into the real demod components (comparator stuck,
diff-amp feedback-open / input-short, each split-R_dda_g half short/open, switch
stuck-on) AFTER capture (T_INJ, with a short ramp), supervisor ON, and checks
none reintroduce a silent over-heat (filament hot while V_int stays in-band so
no supervisor trip).

The post-chop difference-amp ground reference R_dda_g is split into two series
halves (R_dda_g1/g2) in the canonical design: shorting a single half leaves
R_dda_in_g/2 to ground (not 0), so the diff-amp keeps differential rejection.
This is the fix for the one residual the unsplit design had (full R_dda_g short
= +22.7K silent on iv6 / hunting on ilc11_7).  Expect SILENT-HOT = 0.

ilc11_7 note: the hard-short cases are slow (a 1mOhm node on the stiffest tube
collapses ngspice timesteps -> ~6 min wall each), so per-case timeout is 600s.
This is wall-clock, NOT a convergence failure.  Heavy sim -> run on simhost.

Usage: python3 demod_fmea.py [tube]
"""
import sys, subprocess, re, os
import numpy as np
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = sys.argv[1] if len(sys.argv) > 1 else "iv6"
WORK = f"/tmp/dfmea_{TUBE}"; os.makedirs(WORK, exist_ok=True)
T_END, T_INJ, T_RAMP = 7.0, 4.0, 20e-6
PER_CASE_TIMEOUT = 600   # wall-clock; ilc11_7 hard-shorts take ~6 min


def base_lines():
    cir = r.make_netlist(switch_demod=True, instrument_power=False, T_end=T_END,
                         fault_supervisor=True, **r.TUBES[TUBE])
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/REPLACED.data", cir)
    return cir.split("\n")


def ramp_R(val, faulted):
    return f"({val} + ({faulted}-({val}))*min(max((time-{T_INJ})/{T_RAMP},0),1))"


def make_fault(lines, fault):
    L = list(lines)
    kind = fault[0]
    if kind == "force_node":  # force a node to a value after T_INJ (comparator stuck)
        _, node, val = fault
        L.append(f"B_force_{node} {node} nf_{node} I = V({node},nf_{node})/(time < {T_INJ} ? 1e9 : 0.05)")
        L.append(f"V_force_{node} nf_{node} 0 {val}")
    elif kind == "connect":  # force a connection (switch stuck-on) after T_INJ
        _, a, b, ron = fault
        L.append(f"B_con_{a}_{b} {a} {b} I = V({a},{b})/(time < {T_INJ} ? 1e9 : {ron})")
    elif kind == "R":  # short/open a demod resistor after T_INJ
        _, nm, mode = fault
        for i, ln in enumerate(L):
            t = ln.split()
            if t and t[0] == nm:
                a, b, val = t[1], t[2], t[3]
                f = "1e12" if mode == "open" else "1e-3"
                L[i] = f"B{nm} {a} {b} I = V({a},{b}) / ( time < {T_INJ} ? {val} : {ramp_R(val, f)} )"
                break
        else:
            raise SystemExit(f"resistor {nm} not found")
    return L


def run_case(args):
    label, fault = args
    L = make_fault(lines, fault)
    cir = "\n".join(L).replace("REPLACED", label)
    open(f"{WORK}/{label}.cir", "w").write(cir)
    try:
        subprocess.run(["ngspice", "-b", f"{label}.cir"], cwd=WORK,
                       capture_output=True, text=True, timeout=PER_CASE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return (label, "ERR", None, None, None)
    fp = f"{WORK}/{label}.data"
    if not os.path.exists(fp):
        return (label, "ERR", None, None, None)
    try:
        d = np.loadtxt(fp)
        if d.ndim < 2 or len(d) < 10:
            return (label, "ERR", None, None, None)
    except Exception:
        return (label, "ERR", None, None, None)
    t = d[:, 0]
    fT = float(np.mean(d[t > T_END - 0.3, 9])); vi = float(np.mean(d[t > T_END - 0.3, 7]))
    caught = bool(np.max(d[:, 15]) > 2.5)
    return (label, "OK", fT, vi, caught)


lines = base_lines()
CASES = [
    ("comp_stuck_hi",  ("force_node", "n_demod_ref", "9.9")),
    ("comp_stuck_lo",  ("force_node", "n_demod_ref", "-9.9")),
    ("dda_fb_open",    ("R", "R_dda_fb", "open")),
    ("dda_inp_short",  ("R", "R_dda_inp", "short")),
    ("dda_inm_short",  ("R", "R_dda_inm", "short")),
    ("dda_g1_short",   ("R", "R_dda_g1", "short")),
    ("dda_g2_short",   ("R", "R_dda_g2", "short")),
    ("dda_g1_open",    ("R", "R_dda_g1", "open")),
    ("dda_g2_open",    ("R", "R_dda_g2", "open")),
    ("sw_dp1_stuckon", ("connect", "n_demod_plus", "n_node_B_buf", "60")),
    ("sw_dm1_stuckon", ("connect", "n_demod_minus", "n_node_A_buf", "60")),
]

# ilc11_7 hard-shorts are slow; fewer workers avoids RAM pressure (24 vCPUs, so
# parallelism is not the bottleneck — wall-clock per stiff case is).
workers = 4 if TUBE in ("ilc11_7", "ilc11_8") else 9
print(f"{TUBE}: demod-component FMEA (switch demod, fault after capture, supervisor ON)\n")
print(f"{'fault':16} {'finalT':>7} {'V_int':>6} {'caught':>7} {'verdict':>18}")
with ThreadPoolExecutor(max_workers=workers) as ex:
    for label, st, fT, vi, caught in ex.map(run_case, CASES):
        if st != "OK":
            print(f"{label:16} {'ERR':>7}"); continue
        if fT > 810 and not caught and 1.5 <= vi <= 3.9:
            v = "*** SILENT-HOT ***"
        elif fT > 810 and caught:
            v = "hot-caught"
        elif fT > 810:
            v = "HOT-rail-uncaught?"
        elif fT < 790:
            v = "cold/safe"
        else:
            v = "ok"
        print(f"{label:16} {fT:7.1f} {vi:6.2f} {str(caught):>7} {v:>18}")
