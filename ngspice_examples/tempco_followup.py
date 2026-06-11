"""Follow-up: (1) worst-COLD corner at 25°C ambient (dodging the uic-startup
artifact that blocks temp=50); (2) retry 50°C with convergence aids to confirm
the failure is numerical, not physical. Per tube via TUBE env -> tempco_fu_<tube>.md"""
import sys, subprocess, re, os, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBE = os.environ.get("TUBE", "iv6")
T_END = 8.0
WORK = f"/tmp/tfu_{TUBE}"; os.makedirs(WORK, exist_ok=True)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"tempco_fu_{TUBE}.md")
TC = 100e-6


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


def run(kw, temp, vos=None, aids=False, tag="x"):
    cir = r.make_netlist(T_end=T_END, **kw)
    opt = f".options temp={temp}" + (" method=gear gmin=1e-9 cshunt=1e-15" if aids else "")
    cir = re.sub(r"(\.options reltol[^\n]*)", rf"\1\n{opt}", cir, count=1)
    if vos is not None: cir = cir.replace("Vos=50u", f"Vos={vos:.1f}u")
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
app(f"# {TUBE} follow-up\n| case | T_ss | THD | note |\n|---|---|---|---|")

# worst-COLD at 25C
kw = dict(base); kw["R_op"] = base["R_op"]*1.05; kw["v_buf"] = 0.95*base.get("v_buf", 10)
kw["R_sense"] = base["R_sense"]*0.99; kw["R_top_ref"] = base["R_top_ref"]*0.99; kw["R_bot_ref"] = base["R_bot_ref"]*1.01
Tss, thd = run(kw, 25, vos=200, tag="cold25")
app(f"| worst-COLD @25°C | {'FAIL' if Tss is None else f'{Tss:.1f}K'} | {'' if thd is None else f'{thd:.1f}dB'} | R_op+5%, target×0.97, Vos 200µV |")

# 50C nominal with convergence aids
Tss, thd = run(dict(base), 50, aids=True, tag="amb50aid")
app(f"| 50°C +conv-aids | {'FAIL (still)' if Tss is None else f'{Tss:.1f}K'} | {'' if thd is None else f'{thd:.1f}dB'} | gear+gmin; confirms artifact vs real |")
print("DONE", flush=True)
