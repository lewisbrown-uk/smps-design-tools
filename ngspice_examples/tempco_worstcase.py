"""Suite H (ambient temperature + bridge-ref tempco) and Suite W (stacked worst-case
corner). Run per tube via TUBE env. Writes tempco_wc_<tube>.md.

Ambient: .options temp sets device (BJT/diode/H11F) temperature; bridge-ref
resistors get a manual tempco (they ARE the setpoint -> not loop-rejected).
Worst-case: stack the big tolerances (filament R, bridge-ref ±1% + tempco, Vos,
v_buf) in the adverse cold / hot direction at the adverse ambient."""
import sys, subprocess, re, os, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = os.environ.get("TUBE", "iv6")
T_END = 8.0
WORK = f"/tmp/twc_{TUBE}"; os.makedirs(WORK, exist_ok=True)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"tempco_wc_{TUBE}.md")
TC = 100e-6  # bridge-ref resistor tempco, /°C (standard thin-film)


def thd_db(t, v, t0, t1, f=1000.0):
    m = (t >= t0) & (t <= t1); ts, vs = t[m], v[m]
    if len(ts) < 50: return float("nan")
    fs = np.linspace(f*0.95, f*1.05, 41); best = (np.inf, 0, 0)
    for ff in fs:
        sb, cb = np.sin(2*np.pi*ff*ts), np.cos(2*np.pi*ff*ts)
        a = np.trapezoid(vs*sb, ts)/np.trapezoid(sb*sb, ts); b = np.trapezoid(vs*cb, ts)/np.trapezoid(cb*cb, ts)
        if -math.hypot(a, b) < best[0]: best = (-math.hypot(a, b), a, b)
    _, a, b = best
    res = vs - a*np.sin(2*np.pi*1000*ts) - b*np.cos(2*np.pi*1000*ts); dn = math.sqrt((a*a+b*b)/2)
    return 20*math.log10(math.sqrt(np.trapezoid(res*res, ts)/(ts[-1]-ts[0]))/dn) if dn > 0 else float("nan")


def run(kw, temp, vos=None, tag="x"):
    cir = r.make_netlist(T_end=T_END, **kw)
    cir = re.sub(r"(\.options reltol[^\n]*)", rf"\1\n.options temp={temp}", cir, count=1)
    if vos is not None:
        cir = cir.replace("Vos=50u", f"Vos={vos:.1f}u")
    w = f"{WORK}/{tag}"; os.makedirs(w, exist_ok=True)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {w}/run.data", cir)
    open(f"{w}/run.cir", "w").write(cir)
    try:
        subprocess.run(["ngspice", "-b", "run.cir"], cwd=w, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None, None
    if not os.path.exists(f"{w}/run.data"): return None, None
    d = np.loadtxt(f"{w}/run.data"); os.remove(f"{w}/run.data")
    t = d[:, 0]; T = d[:, 9]; vfil = d[:, 1]-d[:, 3]
    return float(np.mean(T[t > T_END-1.0])), thd_db(t, vfil, T_END-1.0, T_END)


def app(s): open(OUT, "a").write(s+"\n"); print(s, flush=True)


base = dict(r.TUBES[TUBE])
app(f"# {TUBE}: ambient + worst-case  (bridge-ref tempco {TC*1e6:.0f} ppm/°C)\n")

# ---- Suite H: ambient sweep with bridge-ref tempco ----
app("## H — ambient sweep (device temp + bridge-ref tempco)")
app("| ambient | T_ss | ΔT_ss vs 25°C | THD |")
app("|---|---|---|---|")
t25 = None
for amb in [0, 25, 50]:
    tf = 1 + TC*(amb-25)
    kw = dict(base)
    for k in ("R_sense", "R_top_ref", "R_bot_ref"): kw[k] = base[k]*tf
    T_ss, thd = run(kw, amb, tag=f"H{amb}")
    if T_ss is None: app(f"| {amb}°C | FAIL | | |"); continue
    if amb == 25: t25 = T_ss
    dd = "" if t25 is None else f"{T_ss-t25:+.1f}K"
    app(f"| {amb}°C | {T_ss:.1f}K | {dd} | {thd:.1f}dB |")

# ---- Suite W: stacked worst-case corners ----
app("\n## W — stacked worst-case corner (filament R±5%, bridge-R±1%+tempco, Vos±150µV, v_buf±5%)")
app("| corner | T_ss | THD | notes |")
app("|---|---|---|---|")
# COLD: R_op high, target low, Vos high, v_buf low, hot ambient
for name, rop, rs, rt, rb, vb, vos, amb in [
    ("worst-COLD", 1.05, 0.99, 0.99, 1.01, 0.95*base.get("v_buf", 10), +150, 50),
    ("worst-HOT",  0.95, 1.01, 1.01, 0.99, 1.05*base.get("v_buf", 10), -150, 0),
    ("nominal-25", 1.00, 1.00, 1.00, 1.00, base.get("v_buf", 10),        0,  25)]:
    tf = 1 + TC*(amb-25)
    kw = dict(base); kw["R_op"] = base["R_op"]*rop; kw["v_buf"] = vb
    kw["R_sense"] = base["R_sense"]*rs*tf; kw["R_top_ref"] = base["R_top_ref"]*rt*tf
    kw["R_bot_ref"] = base["R_bot_ref"]*rb*tf
    T_ss, thd = run(kw, amb, vos=50+vos, tag=name)
    if T_ss is None: app(f"| {name} | FAIL | | |"); continue
    app(f"| {name} | {T_ss:.1f}K | {thd:.1f}dB | R_op×{rop}, target×~{rs*rt/rb:.3f}, Vos {50+vos:.0f}µV, {amb}°C |")
print("DONE", flush=True)
