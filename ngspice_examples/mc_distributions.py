"""Monte Carlo capturing PER-DRAW settling time and THD (realistic per-tube tau),
for distribution charts. Run per tube via TUBE env. Writes mc_dist_<tube>.csv.
Randomisation matches the battery's Suite B: bridge-R ±1%, C_int/C_lp ±10%, Vos ±50µV."""
import sys, subprocess, re, os, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = os.environ.get("TUBE", "iv6")
N = int(os.environ.get("N", "50"))
T_END = 8.0
WORK = f"/tmp/mcd_{TUBE}"; os.makedirs(WORK, exist_ok=True)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"mc_dist_{TUBE}.csv")
rng = np.random.default_rng(2026)


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


rows = []
for i in range(N):
    kw = dict(r.TUBES[TUBE])
    kw["R_top_ref"] *= (1 + rng.uniform(-0.01, 0.01))
    kw["R_bot_ref"] *= (1 + rng.uniform(-0.01, 0.01))
    kw["R_sense"] *= (1 + rng.uniform(-0.01, 0.01))
    kw["C_int"] = 318e-9 * (1 + rng.uniform(-0.10, 0.10))
    kw["C_lp"] = 0.22e-6 * (1 + rng.uniform(-0.10, 0.10))
    vos = rng.uniform(-50, 50)
    cir = r.make_netlist(T_end=T_END, **kw).replace("Vos=50u", f"Vos={vos:.1f}u")
    w = f"{WORK}/{i}"; os.makedirs(w, exist_ok=True)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {w}/run.data", cir)
    open(f"{w}/run.cir", "w").write(cir)
    try:
        subprocess.run(["ngspice", "-b", "run.cir"], cwd=w, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        continue
    fp = f"{w}/run.data"
    if not os.path.exists(fp): continue
    d = np.loadtxt(fp); os.remove(fp)
    t = d[:, 0]; vfil = d[:, 1]-d[:, 3]; T = d[:, 9]
    ss = t > T_END - 1.0; T_ss = float(np.mean(T[ss]))
    # settling time: last instant T leaves +/-1% of T_ss
    out = np.abs(T - T_ss) > 0.01 * T_ss
    settle = float(t[np.where(out)[0][-1]]) if out.any() else 0.0
    thd = thd_db(t, vfil, T_END - 1.0, T_END)
    rows.append((settle, thd, T_ss))
    np.savetxt(OUT, rows, fmt="%.4f", header="settle_s,thd_db,T_ss", comments="")
print(f"{TUBE}: {len(rows)}/{N} draws written -> {OUT}")
