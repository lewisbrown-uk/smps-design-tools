"""Characterize the cold-start DRIVE overshoot (the thing that limits how low the
fault clamp and detector threshold can sit). Captures the drive envelope, V_int
(clamped), V_int_raw (free integrator), e_sat (anti-windup error) and T, so we can
see whether the overshoot is phase-margin ringing, anti-windup release, or the
Wien ramp outpacing the loop.

Usage: python3 cold_overshoot_diag.py <tube>
"""
import sys, subprocess, re, os, math
import numpy as np


def thd_db(t, v, t0, t1, f_seed=1000.0):
    m = (t >= t0) & (t <= t1); ts = t[m]; vs = v[m]
    fs = np.linspace(f_seed*0.95, f_seed*1.05, 101); best = (np.inf, f_seed, 0, 0)
    for f in fs:
        sb = np.sin(2*np.pi*f*ts); cb = np.cos(2*np.pi*f*ts)
        a = np.trapezoid(vs*sb, ts)/np.trapezoid(sb*sb, ts)
        b = np.trapezoid(vs*cb, ts)/np.trapezoid(cb*cb, ts)
        if -math.hypot(a, b) < best[0]: best = (-math.hypot(a, b), f, a, b)
    _, f0, a, b = best
    res = vs - a*np.sin(2*np.pi*f0*ts) - b*np.cos(2*np.pi*f0*ts)
    return 20*math.log10(math.sqrt(np.trapezoid(res*res, ts)/(ts[-1]-ts[0])) /
                         math.sqrt((a*a+b*b)/2))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = sys.argv[1] if len(sys.argv) > 1 else "ilc11_7"
TERSE = os.environ.get("TERSE", "0") == "1"
WORK = f"/tmp/cosd_{TUBE}_{os.environ.get('RUN', '0')}"; os.makedirs(WORK, exist_ok=True)
T_END = float(os.environ.get("TEND", "6.0"))

# Overridable levers (default = current canonical values).
kw = dict(r.TUBES[TUBE])
for env_k, arg_k in [("VCH", "V_clamp_hi"), ("TSR", "t_src_ramp"),
                     ("RINT", "R_int"), ("CINT", "C_int"), ("RPID", "R_pid"),
                     ("CHF", "C_hf"), ("CPID", "C_pid"), ("TCLRAMP", "t_clamp_ramp")]:
    if env_k in os.environ:
        kw[arg_k] = float(os.environ[env_k])
if os.environ.get("STIFF"):
    kw["stiff_clamp"] = True
if os.environ.get("SWDEMOD"):  # hardware-faithful commutating-switch demod (rail-clipped)
    kw["switch_demod"] = True


def build():
    cir = r.make_netlist(instrument_power=False, T_end=T_END, **kw)
    if os.environ.get("PRELOG"):  # feed the integrator the un-amplified pre-log error
        # (n_demod_dc) instead of the x20-gained, cold-start-railing n_log_dem.
        cir = re.sub(r"R_intin  n_log_dem n_int_minus", "R_intin  n_demod_dc n_int_minus", cir)
        cir = re.sub(r"C_intin  n_log_dem n_int_minus", "C_intin  n_demod_dc n_int_minus", cir)
    if os.environ.get("STIFFCLAMP"):  # flat/hard anti-windup clamp (sharp knee, low Rs)
        cir = re.sub(r"\.model Dclamp D\([^)]*\)",
                     ".model Dclamp D(Is=1e-7 N=0.05 RS=0.01 BV=40)", cir)
    if os.environ.get("RAWO_AW") is not None:  # shrink R_aw_out so the clamp bites harder
        cir = re.sub(r"R_aw_out  v_int_raw v_int \S+",
                     f"R_aw_out  v_int_raw v_int {os.environ['RAWO_AW']}", cir)
    if os.environ.get("REALWIEN"):  # drive with the captured real Wien startup envelope
        pwl = open("/tmp/wien_env/env_pwl.txt").read().strip()
        cir = cir.replace(".tran", f"V_wienenv n_wienenv 0 PWL({pwl})\n.tran", 1)
        cir = re.sub(r"\(1 - exp\(-time/\S+\)\)", "V(n_wienenv)", cir)
    if "VCHSTART" in os.environ:  # dynamic clamp soft-start: hold tight, then relax
        vs = float(os.environ["VCHSTART"])
        thold = float(os.environ.get("TCHHOLD", "0.0"))   # hold tight until thold
        tr = float(os.environ.get("TCHRAMP", "1.5"))      # reach vend at thold+tr
        vend = kw.get("V_clamp_hi", 4.0)
        cir = re.sub(r"V_clamp_hi v_clamp_hi 0 \S+",
                     f"V_clamp_hi v_clamp_hi 0 PWL(0 {vs} {thold} {vs} {thold+tr} {vend} 100 {vend})", cir)
    if "ILEAK" in os.environ:  # LOSSY integrator (lag): R parallel to C_intfb -> finite
        # DC gain bounds the windup, but introduces a steady-state regulation error.
        cir = re.sub(r"(C_intfb  n_int_minus n_int_pidp \S+ IC=0)",
                     r"\1\nR_ileak n_int_minus n_int_pidp " + os.environ["ILEAK"], cir)
    if "RINTSS" in os.environ:  # gain-scheduled integrator: R_int_p (setpoint feed)
        # soft-start by ramping the proportional setpoint resistor's effect -- emulate
        # by ramping R_int via a behavioural time-varying resistor on the integrator input
        rss = os.environ["RINTSS"]; tr = float(os.environ.get("TRSS", "1.5"))
        cir = re.sub(r"R_intin  n_log_dem n_int_minus \S+",
                     f"B_rintin n_log_dem n_int_minus I = V(n_log_dem,n_int_minus)"
                     f"/({rss} + ({kw.get('R_int',1e6)}-{rss})*min(time/{tr},1))", cir)
    if "RBC" in os.environ:   # override hardcoded R_bc = R_int/20
        cir = re.sub(r"R_bc e_sat n_int_minus \S+",
                     f"R_bc e_sat n_int_minus {os.environ['RBC']}", cir)
    if "RAWO" in os.environ:  # override hardcoded R_aw_out = 10
        cir = re.sub(r"R_aw_out  v_int_raw v_int \S+",
                     f"R_aw_out  v_int_raw v_int {os.environ['RAWO']}", cir)
    if "SETRAMP" in os.environ:  # OPEN-LOOP setpoint ramp: V_set decays start->0 (time only)
        vss = float(os.environ["SETRAMP"]); taus = float(os.environ.get("TAUSET", "0.5"))
        cir = re.sub(r"V_set n_setpoint 0 DC 0",
                     f"B_set n_setpoint 0 V = {vss}*exp(-time/{taus})", cir)
    if "GOV" in os.environ:  # REFERENCE GOVERNOR (closed-loop adaptive): setpoint stays
        # a fixed `lead` ahead of the MEASURED imbalance n_log_dem and clamps at the true
        # target (0).  Tracking error is bounded by `lead` -> no windup, no slam; self-paces
        # to the filament's actual warm-up (tube/tau-independent); converges to 0 for DC accy.
        lead = float(os.environ["GOV"])
        tg = float(os.environ.get("TAUGOV", "0.03"))  # smooth the fast ~15ms Wien-build-up
        cg = tg / 10e6  # R_gov=10Meg (hi-Z, doesn't load n_log_dem)
        cir = re.sub(r"V_set n_setpoint 0 DC 0",
                     f"R_gov n_log_dem n_gov 10meg\nC_gov n_gov 0 {cg:.6g} IC=0\n"
                     f"B_set n_setpoint 0 V = min(V(n_gov) + {lead}, 0)", cir)
    cir = re.sub(r"(\.save [^\n]*)", r"\1 v(v_int_raw) v(e_sat) v(v_clamp_hi)", cir)
    cir = re.sub(r"(wrdata \S+/run\.data[^\n]*)",
                 r"\1 v(v_int_raw) v(e_sat) v(v_clamp_hi)", cir)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {WORK}/c.data", cir)
    return cir


def envelope(t, v, win=2e-3):
    """Rolling RMS-based envelope (peak proxy): sqrt(2)*rms over a sliding window."""
    out = np.zeros_like(v)
    # uniform-ish dt assumption is rough; use a causal max-of-|v| over the window
    j = 0
    for i in range(len(t)):
        while t[j] < t[i] - win:
            j += 1
        out[i] = np.max(np.abs(v[j:i + 1])) if i > j else abs(v[i])
    return out


cir = build()
open(f"{WORK}/c.cir", "w").write(cir)
p = subprocess.run(["ngspice", "-b", "c.cir"], cwd=WORK, capture_output=True, text=True, timeout=1200)
fp = f"{WORK}/c.data"
if not os.path.exists(fp):
    print("NO DATA:\n", (p.stderr + p.stdout)[-500:]); sys.exit(1)
d = np.loadtxt(fp)
# pairs: vosc=1, T=9, v_int=7, then appended: v_int_raw, e_sat, v_clamp_hi
t = d[:, 0]; vosc = d[:, 1]; vint = d[:, 7]; T = d[:, 9]
vint_raw = d[:, 15]; e_sat = d[:, 17]; vclamp_hi = d[:, 19]

env = envelope(t, vosc)
settled = t > T_END - 0.5
env_ss = np.mean(env[settled])
i_pk = np.argmax(env)
overshoot_pct = 100 * (env[i_pk] - env_ss) / env_ss

# settling: time for env to come within 1% and stay
within = np.abs(env - env_ss) < 0.01 * env_ss
t_settle = next((t[i] for i in range(len(t)) if within[i:].all()), float("nan"))
T_overshoot = np.max(T) - np.mean(T[settled])

vfil = vosc - d[:, 3]
thd = thd_db(t, vfil, T_END - 1.0, T_END)

if TERSE:
    vch = kw.get("V_clamp_hi", 4.0); tsr = kw.get("t_src_ramp", 0.6)
    print(f"{TUBE}: VCH={vch} TSR={tsr} -> drive OS {overshoot_pct:+.1f}% "
          f"| T_OS +{T_overshoot:.1f}K | settle {t_settle:.2f}s | Vint_pk {np.max(vint):.2f} "
          f"| THD {thd:.1f}dB | T_ss {np.mean(T[settled]):.1f}K")
    sys.exit(0)

print(f"{TUBE}: cold-start drive-overshoot characterization")
print(f"  drive env  settled = {env_ss:.3f} V   peak = {env[i_pk]:.3f} V @ t={t[i_pk]:.2f}s")
print(f"  DRIVE OVERSHOOT    = {overshoot_pct:+.1f} %   (settle to 1%: {t_settle:.2f}s)")
print(f"  V_int      settled = {np.mean(vint[settled]):.3f} V   peak = {np.max(vint):.3f} @ t={t[np.argmax(vint)]:.2f}s")
print(f"  V_int_raw          max = {np.max(vint_raw):.3f}   min = {np.min(vint_raw):.3f}")
print(f"  V_clamp_hi (ref)   = {np.mean(vclamp_hi):.3f} V")
print(f"  V_int hits clamp?  = {np.max(vint) >= np.mean(vclamp_hi) - 0.05}")
print(f"  e_sat (anti-windup) max = {np.max(np.abs(e_sat)):.3f} V")
print(f"  T peak = {np.max(T):.1f} K   T settled = {np.mean(T[settled]):.1f} K")
print(f"  --- trajectory (env / V_int / V_int_raw / e_sat / T) ---")
_traj = ([0.002, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.06, 0.1, 0.2, 0.4, 0.8]
         if os.environ.get("FINETRAJ") else [0.1, 0.3, 0.5, 0.8, 1.2, 1.6, 2.0, 2.5, 3.0, 4.0])
for tt in _traj:
    i = np.argmin(np.abs(t - tt))
    print(f"   t={tt:5.3f}s  env={env[i]:6.3f}  V_int={vint[i]:6.3f}  n_demod_dc={d[i,5]:8.3f}  T={T[i]:6.1f}")
