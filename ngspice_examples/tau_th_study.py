"""Does the realistic per-tube thermal tau change the dynamics (not just the dwell)?
Compares cold-start overshoot at tau_th=0.1s (model) vs the geometry-estimated
per-tube tau, and measures the fault excursion dwell at the realistic tau.
Run per tube via TUBE env: TUBE=iv18 python3 tau_th_study.py
"""
import sys, subprocess, re, os, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TAU_EST = {"ilc11_7": 0.42, "iv6": 0.20, "iv18": 0.19, "ilc11_8": 0.62}
TUBE = os.environ.get("TUBE", "iv18")
WORK = f"/tmp/tau_{TUBE}"; os.makedirs(WORK, exist_ok=True)
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"tau_th_study_{TUBE}.md")


def run(cir, tag, timeout=900):
    w = f"{WORK}/{tag}"; os.makedirs(w, exist_ok=True)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {w}/run.data", cir)
    open(f"{w}/run.cir", "w").write(cir)
    try:
        p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=w, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if not os.path.exists(f"{w}/run.data"): return None
    d = np.loadtxt(f"{w}/run.data"); os.remove(f"{w}/run.data"); return d


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


def env_pk(t, v, lo, hi):
    m = (t >= lo) & (t <= hi)
    return float(np.max(np.abs(v[m]))) if m.any() else float("nan")


def app(s): open(REPORT, "a").write(s+"\n"); print(s, flush=True)


app(f"# tau_th study — {TUBE}  (estimate tau={TAU_EST[TUBE]}s)\n")

# ---- Cold-start overshoot: model 0.1s vs estimate ----
app("## Cold-start overshoot: 0.1s (model) vs estimate")
app("| tau_th | T_overshoot | drive_OS | T_ss | THD | settle(<1%) |")
app("|---|---|---|---|---|---|")
for label, tau in [("0.1s", 0.1), (f"{TAU_EST[TUBE]}s_est", TAU_EST[TUBE])]:
    T_END = 15.0
    d = run(r.make_netlist(T_end=T_END, tau_th=tau, **r.TUBES[TUBE]), f"cs_{label}")
    if d is None: app(f"| {label} | FAIL | | | | |"); continue
    t = d[:, 0]; vfil = d[:, 1]-d[:, 3]; T = d[:, 9]
    ss = t > T_END-1.0; T_ss = np.mean(T[ss]); T_pk = np.max(T)
    drv_ss = env_pk(t, vfil, T_END-1.0, T_END); drv_pk = env_pk(t, vfil, 0, T_END)
    dOS = 100*(drv_pk-drv_ss)/drv_ss
    env_band = np.abs(T-T_ss) < 0.01*abs(T_ss-300)  # within 1% of the rise span
    # settle = last time T leaves +/-1% of T_ss
    out = np.abs(T - T_ss) > 0.01*T_ss
    settle = t[np.where(out)[0][-1]] if out.any() else 0.0
    app(f"| {label} | +{T_pk-T_ss:.1f}K | +{dOS:.0f}% | {T_ss:.1f}K | {thd_db(t,vfil,T_END-1,T_END):.1f}dB | {settle:.2f}s |")

# ---- Fault dwell at the realistic tau ----
tau = TAU_EST[TUBE]; T_INJ = 4.0; T_END = 9.0
app(f"\n## Fault excursion dwell at tau={tau}s (XU_buf stuck, protection ON)")
cir = r.make_netlist(overpower_protect=True, T_end=T_END, tau_th=tau, **r.TUBES[TUBE])
cir = cir.replace(".tran", f"B_xubuf n_buf_o nf_xubuf I = V(n_buf_o,nf_xubuf)"
                  f"/(time < {T_INJ} ? 1e9 : 0.05)\nV_xubuf nf_xubuf 0 9.9\n.tran", 1)
cir = re.sub(r"\.tran 50u (\S+) 0 uic", r".tran 20u \1 0 uic", cir)
d = run(cir, "fault")
if d is None:
    app("FAULT RUN FAILED")
else:
    t = d[:, 0]; T = d[:, 9]; n_disc = d[:, 23]
    i_inj = np.searchsorted(t, T_INJ); i_pk = i_inj+int(np.argmax(T[i_inj:]))
    t_trip = t[np.argmax(n_disc > 2.5)] if np.max(n_disc) > 2.5 else float("nan")
    def dwell(thr):
        m = (t >= T_INJ) & (T > thr); dt = np.diff(t)
        return float(np.sum(dt[m[:-1]]))
    def cool_to(tgt):
        post = t[i_pk:]; Tp = T[i_pk:]; b = np.where(Tp <= tgt)[0]
        return float(post[b[0]]-t[i_pk]) if len(b) else float("nan")
    app(f"- disconnect @ {(t_trip-T_INJ)*1e3:.0f} ms,  peak {T[i_pk]:.0f} K @ {(t[i_pk]-T_INJ)*1e3:.0f} ms")
    app(f"- dwell >800K: **{dwell(800)*1e3:.0f} ms**,  >850K: {dwell(850)*1e3:.0f} ms,  >900K: {dwell(900)*1e3:.0f} ms")
    app(f"- cool peak→800K: {cool_to(800)*1e3:.0f} ms,  →700K: {cool_to(700)*1e3:.0f} ms,  →500K: {cool_to(500)*1e3:.0f} ms")
print("DONE", flush=True)
