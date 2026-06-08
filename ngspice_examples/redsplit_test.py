"""Open item (b): does splitting R_dda_g into two series halves bound the one
residual demod fault (dda_g_short = +23 K silent)?

Single 30k R_dda_g shorted -> n_dda_p hard-grounded -> diff-amp goes single-ended
-> +23 K. Split into 15k+15k; a short of ONE half leaves 15k to ground, so the
+input still sees a finite reference -> the setpoint shift should be ~halved.

Compares, on a given tube, after-capture (T_INJ) with a 20us ramp, supervisor ON:
  baseline (no fault) | unsplit short (+23K ref) | split: short g1 | split: short g2
"""
import sys, subprocess, re, os
import numpy as np

import os.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = sys.argv[1] if len(sys.argv) > 1 else "iv6"
WORK = f"/tmp/redsplit_{TUBE}"; os.makedirs(WORK, exist_ok=True)
T_END, T_INJ, T_RAMP = 7.0, 4.0, 20e-6
OP_RE = r"uopamp_lvl3 [^\n]*Vrail=0\.1"

# Same switch demod as demod_fmea.py, but R_dda_g optionally split into two halves.
SW_HEAD = """* --- Hardware switch-based synchronous demodulator ---
XU_demod_comp v_osc_drive 0 vcc_buf vee_buf n_demod_ref {OP}
B_demod_refn n_demod_refn 0 V = -V(n_demod_ref)
.model SW_demod SW(Ron=60 Roff=1e9 Vt=0 Vh=0.5)
S_dp1 n_demod_plus  n_node_B_buf n_demod_ref  0 SW_demod
S_dp2 n_demod_plus  n_node_A_buf n_demod_refn 0 SW_demod
S_dm1 n_demod_minus n_node_A_buf n_demod_ref  0 SW_demod
S_dm2 n_demod_minus n_node_B_buf n_demod_refn 0 SW_demod
R_dp_gnd n_demod_plus 0 1Meg
R_dm_gnd n_demod_minus 0 1Meg
R_dda_inp n_demod_plus  n_dda_p 1k"""
SW_TAIL = """R_dda_inm n_demod_minus n_dda_m 1k
R_dda_fb  n_demod n_dda_m 30k
XU_demod_da n_dda_p n_dda_m vcc_buf vee_buf n_demod {OP}"""

G_UNSPLIT = "R_dda_g   n_dda_p 0 30k"
G_SPLIT   = "R_dda_g1  n_dda_p n_dda_gmid 15k\nR_dda_g2  n_dda_gmid 0 15k"


def ramp_R(val, faulted):
    return f"({val} + ({faulted}-({val}))*min(max((time-{T_INJ})/{T_RAMP},0),1))"


def base_lines(split):
    cir = r.make_netlist(instrument_power=False, T_end=T_END,
                         fault_supervisor=True, **r.TUBES[TUBE])
    op = re.search(OP_RE, cir).group(0)
    gline = G_SPLIT if split else G_UNSPLIT
    block = "\n".join([SW_HEAD, gline, SW_TAIL]).replace("{OP}", op)
    cir = re.sub(r"B_demod n_demod 0 V = [^\n]*", block, cir)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/REPLACED.data", cir)
    return cir.split("\n")


def short_R(lines, nm):
    """Short resistor `nm` after T_INJ via a behavioural ramp from its value to 1e-3."""
    L = list(lines)
    for i, ln in enumerate(L):
        t = ln.split()
        if t and t[0] == nm:
            a, b, val = t[1], t[2], t[3]
            L[i] = (f"B{nm} {a} {b} I = V({a},{b}) / "
                    f"( time < {T_INJ} ? {val} : {ramp_R(val, '1e-3')} )")
            return L
    raise SystemExit(f"resistor {nm} not found")


def run_case(label, lines):
    cir = "\n".join(lines).replace("REPLACED", label)
    open(f"{WORK}/{label}.cir", "w").write(cir)
    try:
        subprocess.run(["ngspice", "-b", f"{label}.cir"], cwd=WORK,
                       capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return None
    fp = f"{WORK}/{label}.data"
    if not os.path.exists(fp):
        return None
    d = np.loadtxt(fp)
    if d.ndim < 2 or len(d) < 10:
        return None
    t = d[:, 0]
    return (float(np.mean(d[t > T_END - 0.3, 9])),
            float(np.mean(d[t > T_END - 0.3, 7])),
            bool(np.max(d[:, 15]) > 2.5))


unsplit = base_lines(split=False)
split = base_lines(split=True)
CASES = [
    ("baseline",        base_lines(split=False)),                 # no fault
    ("unsplit_g_short", short_R(unsplit, "R_dda_g")),             # +23K reference
    ("split_g1_short",  short_R(split, "R_dda_g1")),
    ("split_g2_short",  short_R(split, "R_dda_g2")),
]

print(f"{TUBE}: redundant-split R_dda_g test (fault after capture, supervisor ON)\n")
print(f"{'case':18} {'finalT':>7} {'dT':>6} {'V_int':>6} {'caught':>7}")
for label, lines in CASES:
    res = run_case(label, lines)
    if res is None:
        print(f"{label:18} {'ERR':>7}"); continue
    fT, vi, caught = res
    print(f"{label:18} {fT:7.1f} {fT-800:+6.1f} {vi:6.2f} {str(caught):>7}")
