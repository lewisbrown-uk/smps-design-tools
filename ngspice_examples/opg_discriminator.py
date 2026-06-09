"""Ground the 'arm on controller release' detector idea in data.

Claim: during LEGITIMATE filament over-power (cold-start warm-up, oscillator
restart) the loop COMMANDS it -> V_int is HIGH (at/near the anti-windup clamp).
During an XU_buf-stuck-at-rail FAULT the drive is high but the loop is fighting
it (can't cut a stuck downstream buffer) -> V_int is driven LOW (toward
V_clamp_lo). If so, the discriminator is "filament over-power AND V_int NOT
commanding high drive = fault", which needs no duration qualification.

Captures v_int (loop command), the drive envelope |v_osc_drive| (filament
over-power proxy) and T, for coldstart / restart / fault.  Heavy -> simhost.

Usage: python3 opg_discriminator.py <tube> <coldstart|restart|fault>
"""
import sys, subprocess, re, os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = sys.argv[1] if len(sys.argv) > 1 else "iv6"
MODE = sys.argv[2] if len(sys.argv) > 2 else "fault"
WORK = f"/tmp/opgd_{TUBE}_{MODE}"; os.makedirs(WORK, exist_ok=True)
T_END, T_INJ = 6.0, 3.0

cir = r.make_netlist(instrument_power=False, T_end=T_END, **r.TUBES[TUBE])

if MODE == "fault":  # XU_buf output stuck to +9.9V rail at T_INJ (active overheat)
    cir = cir.replace(
        ".tran",
        f"B_xubuf n_buf_o nf_xubuf I = V(n_buf_o,nf_xubuf)"
        f"/(time < {T_INJ} ? 1e9 : 0.05)\nV_xubuf nf_xubuf 0 9.9\n.tran", 1)
elif MODE == "restart":  # oscillator drops T_INJ..T_INJ+1.5 then returns
    m = re.search(r"(B_src v_src 0 V = )(.*\* sin\([^\n]*\))", cir)
    head, body = m.group(1), m.group(2)
    gate = f" * (time < {T_INJ} ? 1 : (time < {T_INJ+1.5} ? 0 : 1))"
    cir = cir.replace(m.group(0), head + body + gate)

cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/run.data", cir)
open(f"{WORK}/run.cir", "w").write(cir)
p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=WORK,
                   capture_output=True, text=True, timeout=1200)
fp = f"{WORK}/run.data"
if not os.path.exists(fp):
    print("NO DATA:\n", (p.stderr + p.stdout)[-600:]); sys.exit(1)
d = np.loadtxt(fp)
# default save: v_osc_drive=1, node_A=3, n_demod_dc=5, v_int=7, T_node=9
t = d[:, 0]; vdrive = d[:, 1]; nodeA = d[:, 3]; vint = d[:, 7]; T = d[:, 9]
vfil = vdrive - nodeA  # voltage across the filament

# drive envelope via causal windowed max (2ms)
def env(t, v, win=2e-3):
    out = np.zeros_like(v); j = 0
    for i in range(len(t)):
        while t[j] < t[i] - win: j += 1
        out[i] = np.max(np.abs(v[j:i + 1])) if i > j else abs(v[i])
    return out
de = env(t, vfil)

V_op = r.TUBES[TUBE]["V_op"]
vfil_op_pk = V_op * np.sqrt(2)            # nominal filament peak at OP
op_band = de > 1.15 * vfil_op_pk          # "over-power" = drive env >15% over OP peak
print(f"{TUBE} / {MODE}:  V_op={V_op}  filament OP peak={vfil_op_pk:.2f}V  T_END={T_END}")
print(f"  final T = {np.mean(T[t>T_END-0.3]):.1f}K (peak {np.max(T):.1f})")
print(f"  --- t, V_int(command), drive_env(|Vfil|), over-power?, T ---")
for tt in [0.05, 0.1, 0.2, 0.4, 0.8, 1.5, 2.5, 2.95, 3.05, 3.2, 3.5, 4.0, 5.0, 5.8]:
    if tt > T_END: continue
    i = np.argmin(np.abs(t - tt))
    op = "OVER" if de[i] > 1.15 * vfil_op_pk else "    "
    print(f"   t={tt:4.2f}s  V_int={vint[i]:6.3f}  drive_env={de[i]:6.3f}  {op}  T={T[i]:6.1f}")
