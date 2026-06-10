"""Suite G — ACTIVE-DEVICE parameter variations on the pre-log design (protection OFF).
Re-validates the active-device tolerance set that the overnight battery missed:
  G1  op-amp GBW           (0.5 / 1 / 3 / 10 MHz)        -- hunting re-check on pre-log
  G2  H11F R-spread        (H11F_BETA_SCALE 0.7 / 1.43)  -- datasheet Fig 1 +/-30-43%
  G3  BJT beta             (BF x0.5 / x2)                -- output push-pull spread
  G4  independent per-op-amp Vos MC (N draws, +/-150uV)  -- cube-bifurcation worst case
Metrics: T_ss, overshoot, THD, T-ripple (std in settle window -> hunt detector).
Run: python3 battery_suiteG.py    Heavy -> simhost.
"""
import sys, subprocess, re, os, math, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBES = ["ilc11_7", "iv6", "iv18", "ilc11_8"]
if os.environ.get("TUBE"): TUBES = [os.environ["TUBE"]]
SEL = [a for a in sys.argv[1:] if a in ("G1", "G2", "G3", "G4")] or ["G1", "G2", "G3", "G4"]
ROOT = "/tmp/suiteG"; os.makedirs(ROOT, exist_ok=True)
_tag = "".join(s[-1] for s in SEL) + (("_" + os.environ["TUBE"]) if os.environ.get("TUBE") else "")
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"overnight_battery_G{_tag}.md")


def run(cir, work, timeout=600):
    work = re.sub(r"\s+", "_", work); os.makedirs(work, exist_ok=True)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {work}/run.data", cir)
    open(f"{work}/run.cir", "w").write(cir)
    try:
        p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=work,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    fp = f"{work}/run.data"
    if not os.path.exists(fp): return None, (p.stderr+p.stdout)[-150:].replace("\n", " ")
    try:
        d = np.loadtxt(fp); os.remove(fp); return d, None
    except Exception as e:
        return None, f"loadtxt:{e}"


def thd_db(t, v, t0, t1, f=1000.0):
    m = (t >= t0) & (t <= t1); ts, vs = t[m], v[m]
    if len(ts) < 50: return float("nan")
    fs = np.linspace(f*0.95, f*1.05, 41); best = (np.inf, 0, 0)
    for ff in fs:
        sb, cb = np.sin(2*np.pi*ff*ts), np.cos(2*np.pi*ff*ts)
        a = np.trapezoid(vs*sb, ts)/np.trapezoid(sb*sb, ts)
        b = np.trapezoid(vs*cb, ts)/np.trapezoid(cb*cb, ts)
        if -math.hypot(a, b) < best[0]: best = (-math.hypot(a, b), a, b)
    _, a, b = best
    res = vs - a*np.sin(2*np.pi*1000*ts) - b*np.cos(2*np.pi*1000*ts)
    dn = math.sqrt((a*a+b*b)/2)
    return 20*math.log10(math.sqrt(np.trapezoid(res*res, ts)/(ts[-1]-ts[0]))/dn) if dn > 0 else float("nan")


def m_all(d, t_end=8.0):
    t = d[:, 0]; T = d[:, 9]; vfil = d[:, 1]-d[:, 3]; ss = t > t_end-1.0
    return (float(np.mean(T[ss])), float(np.max(T)-np.mean(T[t > t_end-0.5])),
            thd_db(t, vfil, t_end-1.0, t_end), float(np.std(T[ss])))


def app(s): open(REPORT, "a").write(s+"\n"); print(s, flush=True)


# ---------- G1: GBW ----------
app(f"\n## Suite G1 — op-amp GBW (protection OFF)  {time.ctime()}\n")
app("| tube | GBW | T_ss | overshoot | THD | T-ripple(std) | hunt? |")
app("|---|---|---|---|---|---|---|")
for tb in TUBES:
    for gbw in ["0.5meg", "1meg", "3meg", "10meg"]:
        cir = r.make_netlist(T_end=8.0, **r.TUBES[tb]).replace("GBW=1meg", f"GBW={gbw}")
        d, err = run(cir, f"{ROOT}/G1_{tb}_{gbw}")
        if d is None: app(f"| {tb} | {gbw} | FAIL {err} | | | | |"); continue
        T_ss, ov, thd, rip = m_all(d)
        hunt = "**HUNT**" if (rip > 3 or (not math.isnan(thd) and thd > -25)) else "no"
        app(f"| {tb} | {gbw} | {T_ss:.1f}K | +{ov:.1f}K | {thd:.1f}dB | {rip:.2f}K | {hunt} |")

# ---------- G2: H11F R-spread ----------
app(f"\n## Suite G2 — H11F R-spread (H11F_BETA_SCALE)  {time.ctime()}\n")
app("| tube | beta_scale | T_ss | overshoot | THD | T-ripple | hunt? |")
app("|---|---|---|---|---|---|---|")
for tb in TUBES:
    for bs in ["0.7", "1.0", "1.43"]:
        cir = r.make_netlist(T_end=8.0, **r.TUBES[tb])
        cir = re.sub(r"(X_h11f .*H11F1)", rf"\1 H11F_BETA_SCALE={bs}", cir)
        d, err = run(cir, f"{ROOT}/G2_{tb}_{bs}")
        if d is None: app(f"| {tb} | {bs} | FAIL {err} | | | | |"); continue
        T_ss, ov, thd, rip = m_all(d)
        hunt = "**HUNT**" if (rip > 3 or (not math.isnan(thd) and thd > -25)) else "no"
        app(f"| {tb} | {bs} | {T_ss:.1f}K | +{ov:.1f}K | {thd:.1f}dB | {rip:.2f}K | {hunt} |")

# ---------- G3: BJT beta ----------
app(f"\n## Suite G3 — output BJT beta (BF x0.5 / x2)  {time.ctime()}\n")
app("| tube | beta | T_ss | overshoot | THD | T-ripple | hunt? |")
app("|---|---|---|---|---|---|---|")
for tb in TUBES:
    for tag, sc in [("BFx0.5", 0.5), ("BFx2", 2.0)]:
        cir = r.make_netlist(T_end=8.0, **r.TUBES[tb])
        cir = cir.replace("BF=143", f"BF={143*sc:.1f}").replace("BF=157.5", f"BF={157.5*sc:.1f}")
        d, err = run(cir, f"{ROOT}/G3_{tb}_{tag}")
        if d is None: app(f"| {tb} | {tag} | FAIL {err} | | | | |"); continue
        T_ss, ov, thd, rip = m_all(d)
        hunt = "**HUNT**" if (rip > 3 or (not math.isnan(thd) and thd > -25)) else "no"
        app(f"| {tb} | {tag} | {T_ss:.1f}K | +{ov:.1f}K | {thd:.1f}dB | {rip:.2f}K | {hunt} |")

# ---------- G4: independent per-op-amp Vos MC ----------
N = 25
app(f"\n## Suite G4 — independent per-op-amp Vos MC ({N}/tube, +/-150uV each)  {time.ctime()}\n")
app("| tube | draws | fails | T_ss range | overshoot max | THD worst | max ripple | hunts |")
app("|---|---|---|---|---|---|---|---|")
rng = np.random.default_rng(777)
for tb in TUBES:
    Tss, ovs, thds, rips = [], [], [], []; fails = 0; hunts = 0
    for i in range(N):
        cir = r.make_netlist(T_end=8.0, **r.TUBES[tb])
        # each op-amp instance gets an INDEPENDENT random Vos (per-match lambda)
        cir = re.sub("Vos=50u", lambda mm: f"Vos={rng.uniform(-150,150):.1f}u", cir)
        d, err = run(cir, f"{ROOT}/G4_{tb}_{i}")
        if d is None: fails += 1; continue
        T_ss, ov, thd, rip = m_all(d)
        Tss.append(T_ss); ovs.append(ov); thds.append(thd); rips.append(rip)
        if rip > 3 or (not math.isnan(thd) and thd > -25) or abs(T_ss-800) > 40: hunts += 1
    if Tss:
        app(f"| {tb} | {N} | {fails} | {min(Tss):.0f}-{max(Tss):.0f}K | +{max(ovs):.1f}K "
            f"| {max(thds):.1f}dB | {max(rips):.2f}K | {hunts} |")
    else:
        app(f"| {tb} | {N} | {fails} (all) | - | - | - | - | - |")

print("SUITE G (this process) DONE", flush=True)
