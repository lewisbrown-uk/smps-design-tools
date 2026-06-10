"""Overnight re-validation battery for the PRE-LOG regulator + over-power protection.

Suites (each independent; run one with `python3 overnight_battery.py <suite> [quick]`):
  A  cold-start robustness corners  (Vos, R_op, v_buf; 4 tubes; protection OFF)
  B  Monte Carlo                    (bridge-R +/-1%, caps +/-10%, Vos; 4 tubes; OFF)
  C  disorderly / restart           (instant-on, dropout, brownout; 4 tubes; PROTECT ON)
  D  protection FMEA                (overheat fault modes; 4 tubes; PROTECT ON)

Writes incremental markdown to overnight_battery_report.md.  Robust to per-sim
failures (timeout / NO DATA) -- records and continues.  Heavy -> run on simhost.
"""
import sys, subprocess, re, os, math, time, traceback
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

TUBES = ["ilc11_7", "iv6", "iv18", "ilc11_8"]
if os.environ.get("TUBE"): TUBES = [os.environ["TUBE"]]
ROOT = "/tmp/battery"; os.makedirs(ROOT, exist_ok=True)
QUICK = "quick" in sys.argv
_tag = "".join(a for a in sys.argv[1:] if a in "ABCD") or "all"
if os.environ.get("TUBE"): _tag += "_" + os.environ["TUBE"]
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      f"overnight_battery_{_tag}.md")
op = ("uopamp_lvl3 Avol=5meg GBW=1meg Rin=100g Rout=10 "
      "Iq=800u Ilimit=25m Vos=50u Vmax=30 Vrail=0.1")


def thd_db(t, v, t0, t1, f_seed=1000.0):
    m = (t >= t0) & (t <= t1); ts, vs = t[m], v[m]
    if len(ts) < 50: return float("nan")
    fs = np.linspace(f_seed*0.95, f_seed*1.05, 41); best = (np.inf, f_seed, 0, 0)
    for f in fs:
        sb, cb = np.sin(2*np.pi*f*ts), np.cos(2*np.pi*f*ts)
        a = np.trapezoid(vs*sb, ts)/np.trapezoid(sb*sb, ts)
        b = np.trapezoid(vs*cb, ts)/np.trapezoid(cb*cb, ts)
        if -math.hypot(a, b) < best[0]: best = (-math.hypot(a, b), f, a, b)
    _, f0, a, b = best
    res = vs - a*np.sin(2*np.pi*f0*ts) - b*np.cos(2*np.pi*f0*ts)
    denom = math.sqrt((a*a+b*b)/2)
    if denom <= 0: return float("nan")
    return 20*math.log10(math.sqrt(np.trapezoid(res*res, ts)/(ts[-1]-ts[0])) / denom)


def run(cir, work, timeout=600):
    """Run a netlist string, return data array or None (+ error tail)."""
    os.makedirs(work, exist_ok=True)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {work}/run.data", cir)
    open(f"{work}/run.cir", "w").write(cir)
    try:
        p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=work,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    fp = f"{work}/run.data"
    if not os.path.exists(fp):
        return None, (p.stderr + p.stdout)[-200:].replace("\n", " ")
    try:
        d = np.loadtxt(fp)
        os.remove(fp)  # tmpfs is RAM-backed and small -- free each ~20-55MB file now
        return d, None
    except Exception as e:
        return None, f"loadtxt: {e}"


def metrics(d, t_end, has_protect=False):
    """Standard metrics from a data array (base save layout)."""
    t = d[:, 0]; vdrive = d[:, 1]; nodeA = d[:, 3]; vint = d[:, 7]; T = d[:, 9]
    settled = t > t_end - 0.5
    T_ss = float(np.mean(T[settled])); T_peak = float(np.max(T))
    vfil = vdrive - nodeA
    thd = thd_db(t, vfil, t_end - 1.0, t_end)
    out = dict(T_ss=T_ss, T_peak=T_peak, T_overshoot=T_peak - T_ss,
               thd=thd, vint_ss=float(np.mean(vint[settled])))
    if has_protect and d.shape[1] > 23:
        out["disc"] = bool(np.max(d[:, 23]) > 2.5)
    return out


def append(text):
    with open(REPORT, "a") as f:
        f.write(text + "\n")
    print(text, flush=True)


# ----- netlist transforms (faults / disorderly) -----
def inject_xubuf(cir, level, t_inj=3.0):
    return cir.replace(".tran",
        f"B_xubuf n_buf_o nf_xubuf I = V(n_buf_o,nf_xubuf)"
        f"/(time < {t_inj} ? 1e9 : 0.05)\nV_xubuf nf_xubuf 0 {level}\n.tran", 1)

def osc_dropout(cir, t0=3.0, t1=4.5):
    gate = f" * (time < {t0} ? 1 : (time < {t1} ? 0 : 1))"
    return re.sub(r"(B_src v_src 0 V = .*)", lambda m: m.group(1) + gate, cir)

def short_element(cir, name):
    """Short a named 2-terminal element by setting it to 1mOhm (R) at T_INJ-free."""
    return re.sub(rf"({name}\s+\S+\s+\S+)\s+\S+", r"\1 1e-3", cir, count=1)

def open_element(cir, name):
    return re.sub(rf"({name}\s+\S+\s+\S+)\s+\S+", r"\1 1e12", cir, count=1)


# =================== SUITE A: cold-start robustness ===================
def suite_A():
    append(f"\n## Suite A — cold-start robustness corners (protection OFF)  {time.ctime()}\n")
    corners = [("nominal", {}),
               ("Vos=2mV", {"vos": 2000}), ("Vos=5mV", {"vos": 5000}),
               ("R_op+10%", {"rop": 1.10}), ("R_op-10%", {"rop": 0.90}),
               ("v_buf+5%", {"vbuf": 10.5}), ("v_buf-5%", {"vbuf": 9.5}),
               ("WORST Vos5mV+Rop+10%+vbuf+5%", {"vos": 5000, "rop": 1.10, "vbuf": 10.5})]
    if QUICK: corners = corners[:3]
    tubes = TUBES[:2] if QUICK else TUBES
    append("| tube | corner | T_overshoot | T_ss | THD | V_int_ss |")
    append("|---|---|---|---|---|---|")
    for tb in tubes:
        for name, c in corners:
            kw = dict(r.TUBES[tb]); T_END = 8.0
            if "rop" in c: kw["R_op"] = kw["R_op"] * c["rop"]
            if "vbuf" in c: kw["v_buf"] = c["vbuf"]
            cir = r.make_netlist(T_end=T_END, **kw)
            if "vos" in c: cir = cir.replace("Vos=50u", f"Vos={c['vos']}u")
            d, err = run(cir, f"{ROOT}/A_{tb}_{name[:6]}")
            if d is None: append(f"| {tb} | {name} | FAIL: {err} | | | |"); continue
            m = metrics(d, T_END)
            append(f"| {tb} | {name} | +{m['T_overshoot']:.1f}K | {m['T_ss']:.1f}K "
                   f"| {m['thd']:.1f}dB | {m['vint_ss']:.3f} |")


# =================== SUITE B: Monte Carlo ===================
def suite_B():
    N = 8 if QUICK else 50
    append(f"\n## Suite B — Monte Carlo ({N}/tube: bridge-R +/-1%, caps +/-10%, Vos +/-50uV)  {time.ctime()}\n")
    rng = np.random.default_rng(12345)
    tubes = TUBES[:2] if QUICK else TUBES
    append("| tube | draws | fails | T_ss range | overshoot max | THD worst | hunts |")
    append("|---|---|---|---|---|---|---|")
    for tb in tubes:
        T_ss_list, ov_list, thd_list = [], [], []
        fails = 0; hunts = 0
        for i in range(N):
            kw = dict(r.TUBES[tb]); T_END = 8.0
            kw["R_top_ref"] = kw["R_top_ref"] * (1 + rng.uniform(-0.01, 0.01))
            kw["R_bot_ref"] = kw["R_bot_ref"] * (1 + rng.uniform(-0.01, 0.01))
            kw["R_sense"] = kw["R_sense"] * (1 + rng.uniform(-0.01, 0.01))
            kw["C_int"] = 318e-9 * (1 + rng.uniform(-0.10, 0.10))
            kw["C_lp"] = 0.22e-6 * (1 + rng.uniform(-0.10, 0.10))
            vos = rng.uniform(-50, 50)
            cir = r.make_netlist(T_end=T_END, **kw)
            cir = cir.replace("Vos=50u", f"Vos={vos:.1f}u")
            d, err = run(cir, f"{ROOT}/B_{tb}_{i}")
            if d is None: fails += 1; continue
            m = metrics(d, T_END)
            T_ss_list.append(m["T_ss"]); ov_list.append(m["T_overshoot"]); thd_list.append(m["thd"])
            # hunt = bad THD or T_ss way off (loop not regulating cleanly)
            if (not math.isnan(m["thd"]) and m["thd"] > -25) or abs(m["T_ss"] - 800) > 30:
                hunts += 1
        if T_ss_list:
            append(f"| {tb} | {N} | {fails} | {min(T_ss_list):.0f}-{max(T_ss_list):.0f}K "
                   f"| +{max(ov_list):.1f}K | {max(thd_list):.1f}dB | {hunts} |")
        else:
            append(f"| {tb} | {N} | {fails} (all) | - | - | - | - |")


# =================== SUITE C: disorderly / restart ===================
def suite_C():
    append(f"\n## Suite C — disorderly / restart (protection ON, watch false-trip)  {time.ctime()}\n")
    scenarios = ["instant_on", "dropout_restart", "brownout"]
    if QUICK: scenarios = scenarios[:2]
    tubes = TUBES[:2] if QUICK else TUBES
    append("| tube | scenario | T_peak | T_ss | false-trip? |")
    append("|---|---|---|---|---|")
    for tb in tubes:
        for sc in scenarios:
            kw = dict(r.TUBES[tb]); T_END = 8.0
            if sc == "instant_on":
                kw["t_rail_ramp"] = 0.0
                cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
            elif sc == "dropout_restart":
                cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
                cir = osc_dropout(cir, 3.0, 4.5)
            elif sc == "brownout":
                cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
                # dip the buffer rails to 70% over 3.0-3.5s then recover
                vb = kw.get("v_buf", 10)
                cir = re.sub(r"V_vcc vcc_top 0 DC \S+",
                    f"V_vcc vcc_top 0 PWL(0 {vb} 3 {vb} 3.05 {0.7*vb} 3.5 {0.7*vb} 3.55 {vb} 100 {vb})", cir)
                cir = re.sub(r"V_vee vee_top 0 DC \S+",
                    f"V_vee vee_top 0 PWL(0 {-vb} 3 {-vb} 3.05 {-0.7*vb} 3.5 {-0.7*vb} 3.55 {-vb} 100 {-vb})", cir)
            d, err = run(cir, f"{ROOT}/C_{tb}_{sc}")
            if d is None: append(f"| {tb} | {sc} | FAIL: {err} | | |"); continue
            m = metrics(d, T_END, has_protect=True)
            append(f"| {tb} | {sc} | {m['T_peak']:.1f}K | {m['T_ss']:.1f}K "
                   f"| {'**YES**' if m.get('disc') else 'no'} |")


# =================== SUITE D: protection FMEA ===================
def suite_D():
    append(f"\n## Suite D — protection FMEA (overheat faults, protection ON)  {time.ctime()}\n")
    faults = ["xubuf_hi", "xubuf_lo", "atten_bot_short", "botref_short", "sense_open"]
    if QUICK: faults = faults[:2]
    tubes = TUBES[:2] if QUICK else TUBES
    append("| tube | fault | T_peak | T_final | disconnect? |")
    append("|---|---|---|---|---|")
    for tb in tubes:
        for fl in faults:
            kw = dict(r.TUBES[tb]); T_END = 6.0
            cir = r.make_netlist(T_end=T_END, overpower_protect=True, **kw)
            if fl == "xubuf_hi": cir = inject_xubuf(cir, 9.9)
            elif fl == "xubuf_lo": cir = inject_xubuf(cir, -9.9)
            elif fl == "atten_bot_short": cir = short_element(cir, "R_atten_bot")
            elif fl == "botref_short": cir = short_element(cir, "R_botref")
            elif fl == "sense_open": cir = open_element(cir, "R_sense")
            d, err = run(cir, f"{ROOT}/D_{tb}_{fl}")
            if d is None: append(f"| {tb} | {fl} | FAIL: {err} | | |"); continue
            m = metrics(d, T_END, has_protect=True)
            t = d[:, 0]; T = d[:, 9]; T_final = float(np.mean(T[t > T_END - 0.3]))
            append(f"| {tb} | {fl} | {m['T_peak']:.1f}K | {T_final:.1f}K "
                   f"| {'YES' if m.get('disc') else 'no'} |")


SUITES = {"A": suite_A, "B": suite_B, "C": suite_C, "D": suite_D}

if __name__ == "__main__":
    which = [a for a in sys.argv[1:] if a in SUITES] or list(SUITES)
    for s in which:
        t0 = time.time()
        try:
            SUITES[s]()
            append(f"\n_Suite {s} done in {time.time()-t0:.0f}s_\n")
        except Exception:
            append(f"\n**Suite {s} CRASHED:**\n```\n{traceback.format_exc()}\n```\n")
