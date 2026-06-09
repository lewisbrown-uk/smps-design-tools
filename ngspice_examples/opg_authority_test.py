"""Authority-gated over-power disconnect (replaces the 2s duration integrator).

Discriminator (validated in opg_discriminator.py): legitimate filament
over-power is loop-COMMANDED (V_int high); a loss-of-authority fault is
over-power the loop is FIGHTING (V_int railed low).  So:

  DISCONNECT = independent_over_power
               AND  ( V_int railed LOW (fast)  OR  V_int stuck HIGH (slow) )
               AND  armed

Reuses the dual-sided V_int supervisor's rail signals (n_lo_int, n_hi_int,
n_armed) for the discrimination; adds an independent precision-FWR over-power
sense; latches a SERIES DISCONNECT (the actuation the supervisor lacks, since
its own cutoff hits the oscillator UPSTREAM of a stuck output buffer).

Usage: python3 opg_authority_test.py <tube> <coldstart|restart|fault>
Heavy -> simhost.
"""
import sys, subprocess, re, os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = sys.argv[1] if len(sys.argv) > 1 else "iv6"
MODE = sys.argv[2] if len(sys.argv) > 2 else "fault"
WORK = f"/tmp/opga_{TUBE}_{MODE}"; os.makedirs(WORK, exist_ok=True)
T_END, T_INJ = 6.0, 3.0
K_OP = float(os.environ.get("K_OP", "1.2"))     # over-power thresh = K_OP * V_op (RMS ref)
op = ("uopamp_lvl3 Avol=5meg GBW=1meg Rin=100g Rout=10 "
      "Iq=800u Ilimit=25m Vos=50u Vmax=30 Vrail=0.1")
V_op = r.TUBES[TUBE]["V_op"]
V_thop = K_OP * V_op
T_RELAY = float(os.environ.get("T_RELAY", "0"))   # disconnect actuation lag (s); 0 = instant
if T_RELAY > 0:
    discctl_block = (
        f"B_coildrv n_coildrv 0 V = (V(n_disc) > 2.5) ? 0 : 5\n"
        f"R_coil n_coildrv n_discctl {T_RELAY/1e-6:.6g}\n"
        f"C_coil n_discctl 0 1u IC=5")
else:
    discctl_block = "B_discctl n_discctl 0 V = (V(n_disc) > 2.5) ? 0 : 5"

DET = f"""* ---- Independent over-power sense (precision FWR on filament-side drive) ----
.model DSchd D(IS=1e-8 N=1.0 RS=2 BV=30 CJO=10p)
.model Dlatd D(IS=1e-12 N=1)
.model SWdisc SW(Ron=0.05 Roff=1e12 Vt=2.5 Vh=0.5)
R1d v_bridge_top nAd 10k
R2d nAd nBd 10k
D1d nO1d nBd DSchd
D2d nAd nO1d DSchd
XA1d 0 nAd vcc_buf vee_buf nO1d {op}
R3d v_bridge_top nCd 10k
R4d nBd nCd 5k
R5d nCd nAbsd 10k
XA2d 0 nCd vcc_buf vee_buf nAbsd {op}
R_envd nAbsd n_envd 100k
C_envd n_envd 0 0.1u IC=0
* over-power flag: n_envd = -|drive|, so over-power when -n_envd > V_thop
B_op n_op 0 V = (-V(n_envd) > {V_thop:.4g}) ? 1 : 0
* ---- Authority-gated disconnect latch ----
* set when armed AND over-power AND (V_int railed low [fast] OR stuck high [slow])
B_discset n_discset 0 V = (V(n_armed)>2.5)*(V(n_op)>0.5)*(((V(n_lo_int)>0.6)+(V(n_hi_int)>0.6))>0.5 ? 1:0)*5
D_disc n_discset n_disc Dlatd
C_disc n_disc 0 1u IC=0
R_disc n_disc 0 1e9
* disconnect switch ctrl: 5 = closed (normal), 0 = open (latched fault).
* T_RELAY>0 models a relay's mechanical actuation lag as a 1st-order RC on the
* contact drive (cap starts at 5 = closed; on latch it discharges, contact opens
* when it crosses the SW Vt=2.5 at ~0.69*tau). T_RELAY=0 = instantaneous (MOSFET).
{discctl_block}
"""


K_CLAMP = float(os.environ.get("K_CLAMP", "0"))   # 0 = no clamp; else flat-clamp at K*drive-OP-pk
if K_CLAMP > 0:
    Rop, Rsense = r.TUBES[TUBE]["R_op"], r.TUBES[TUBE]["R_sense"]
    Vcl = K_CLAMP * V_op * np.sqrt(2) * (Rop + Rsense) / Rop   # clamp references DRIVE node
    CLAMP_BLOCK = ("* ---- Passive flat drive clamp (TI flat-clamp / TLV431 active shunt) ----\n"
                   ".model Dcl D(Is=1e-7 N=0.08 RS=0.02 BV=60)\n"
                   f"V_clp n_clp 0 {Vcl:.4g}\nV_cln n_cln 0 {-Vcl:.4g}\n"
                   "D_clp v_osc_drive n_clp Dcl\nD_cln n_cln v_osc_drive Dcl")
else:
    CLAMP_BLOCK = "* no drive clamp"; Vcl = float("nan")


def build():
    cir = r.make_netlist(fault_supervisor=True, instrument_power=False,
                         T_end=T_END, **r.TUBES[TUBE])
    # series disconnect replaces the passive R_series (common-mode node)
    cir = re.sub(r"R_series v_osc_drive v_bridge_top \S+",
                 "S_disc v_osc_drive v_bridge_top n_discctl 0 SWdisc", cir)
    cir = cir.replace(".tran", DET + "\n" + CLAMP_BLOCK + "\n.tran", 1)
    cir = re.sub(r"(\.save [^\n]*)", r"\1 v(n_envd) v(n_op) v(n_disc) v(v_bridge_top)", cir)
    cir = re.sub(r"(wrdata \S+/run\.data[^\n]*)",
                 r"\1 v(n_envd) v(n_op) v(n_disc) v(v_bridge_top)", cir)
    if MODE == "fault":   # XU_buf output stuck to +9.9V rail at T_INJ
        cir = cir.replace(".tran",
                          f"B_xubuf n_buf_o nf_xubuf I = V(n_buf_o,nf_xubuf)"
                          f"/(time < {T_INJ} ? 1e9 : 0.05)\nV_xubuf nf_xubuf 0 9.9\n.tran", 1)
    elif MODE == "restart":   # oscillator drops T_INJ..T_INJ+1.5 then returns
        gate = f" * (time < {T_INJ} ? 1 : (time < {T_INJ+1.5} ? 0 : 1))"
        cir = re.sub(r"(B_src v_src 0 V = .*)", lambda m: m.group(1) + gate, cir)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/run.data", cir)
    return cir


cir = build()
open(f"{WORK}/run.cir", "w").write(cir)
p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=WORK,
                   capture_output=True, text=True, timeout=1200)
fp = f"{WORK}/run.data"
if not os.path.exists(fp):
    print("NO DATA:\n", (p.stderr + p.stdout)[-700:]); sys.exit(1)
d = np.loadtxt(fp)
# default 7 pairs (v_int=7, T=9) + supervisor(n_latch=15,n_armed=17,n_hi_int=19,n_lo_int=21)
# + det(n_envd=23, n_op=25, n_disc=27, v_bridge_top=29)
t = d[:, 0]; vint = d[:, 7]; T = d[:, 9]
n_armed = d[:, 17]; n_hi_int = d[:, 19]; n_lo_int = d[:, 21]
n_envd = d[:, 23]; n_op = d[:, 25]; n_disc = d[:, 27]
disc = n_disc > 2.5
tripped = bool(np.max(n_disc) > 2.5)
t_trip = float(t[np.argmax(disc)]) if tripped else float("nan")

print(f"{TUBE} / {MODE}:  V_op={V_op}  -V_thop={-V_thop:.3g} (K_OP={K_OP})  "
      f"clamp={'OFF' if K_CLAMP<=0 else f'+/-{Vcl:.3g}V (K={K_CLAMP})'}  T_RELAY={T_RELAY*1e3:.0f}ms")
print(f"  final T = {np.mean(T[t>T_END-0.3]):.1f}K (peak {np.max(T):.1f})")
print(f"  DISCONNECT latched = {tripped}" + (f" @ t={t_trip:.3f}s" if tripped else ""))
print(f"  --- t, V_int, |drive|env(-n_envd), over-power, lo_int, hi_int, disc, T ---")
for tt in [0.05, 0.1, 0.2, 0.4, 1.5, 2.95, 3.02, 3.05, 3.1, 3.3, 4.0, 5.0, 5.8]:
    if tt > T_END: continue
    i = np.argmin(np.abs(t - tt))
    print(f"   t={tt:4.2f}  V_int={vint[i]:6.3f}  |drv|={-n_envd[i]:6.3f}  op={int(n_op[i]>0.5)}"
          f"  lo={n_lo_int[i]:.2f}  hi={n_hi_int[i]:.3f}  disc={int(n_disc[i]>2.5)}  T={T[i]:6.1f}")
