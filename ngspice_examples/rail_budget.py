"""Per-tube measured ±10 V rail current (mean + peak) for PSU budgeting.

Runs regulator.py instrumented (R_sense_vcc/vee = 0.1 Ω rail sense), steady-state,
for each tube.  Behavioural demod + protection OFF (fast/robust); the op-amp
channels that config omits (XU_demod_da, XA1op, XA2op, XU_clh, XU_cll, XU_cln = 6)
are added back analytically at OPA4277 Iq.  -> rail_budget.md
"""
import sys, os, subprocess
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import regulator as r

TUBES = ["iv18", "iv6", "ilc11_7", "ilc11_8"]
EXTRA_CH = 6           # op-amp channels not in this sim config (real board has 16)
IQ_CH = 0.8e-3         # OPA4277 Iq per channel
T_END = 6.0
F0 = 1000.0            # carrier (coherent FFT)

def thd_db(t, y, ncyc=150):
    """THD of y over the last ncyc carrier cycles, coherent FFT (rect window)."""
    t1 = float(t[-1]); t0 = t1 - ncyc / F0
    m = t >= t0
    N = 1 << 15
    tu = np.linspace(t0, t1, N, endpoint=False)
    yu = np.interp(tu, t[m], y[m])
    Y = np.abs(np.fft.rfft(yu))
    fund = Y[ncyc]
    harm = np.sqrt(sum(Y[h * ncyc] ** 2 for h in range(2, 9) if h * ncyc < len(Y)))
    return 20 * np.log10(harm / fund) if fund > 0 else float("nan")

def run_tube(key):
    net = r.make_netlist(instrument_power=True, T_end=T_END, **r.TUBES[key])
    (r.WORK / f"rb_{key}.cir").write_text(net)
    p = subprocess.run(["ngspice", "-b", f"rb_{key}.cir"], cwd=r.WORK,
                       capture_output=True, text=True, timeout=1800)
    f = r.WORK / "run.data"
    if not f.exists():
        return dict(key=key, err=p.stderr[-300:] or "no data")
    d = np.loadtxt(f); f.unlink()
    t = d[:, 0]
    sm = t > t[-1] - 0.20            # last 200 ms steady window
    ts = t[sm]
    i_vcc = (d[sm, 25] - d[sm, 27]) / 0.1      # (vcc_top - vcc_buf)/Rsense
    i_vee = (d[sm, 31] - d[sm, 29]) / 0.1      # (vee_buf - vee_top)/Rsense
    n_led_a, v_osc, node_A = d[sm, 13], d[sm, 1], d[sm, 3]
    R_op = r.TUBES[key]["R_op"]
    mean = lambda x: float(np.trapezoid(x, ts) / (ts[-1] - ts[0]))
    return dict(
        key=key,
        i_vcc_m=mean(i_vcc), i_vcc_pk=float(np.max(np.abs(i_vcc))),
        i_vee_m=mean(i_vee), i_vee_pk=float(np.max(np.abs(i_vee))),
        i_led=(5.0 - mean(n_led_a)) / 270.0,
        P_fil=mean((v_osc - node_A) ** 2) / R_op,
        T_ss=mean(d[sm, 9]),
        thd=thd_db(d[:, 0], d[:, 1] - d[:, 3]),   # V_filament THD (the metric)
    )

def main():
    rows = [run_tube(k) for k in TUBES]
    L = ["# Measured ±10 V rail current (instrumented, steady state)\n",
         f"Sim: behavioural demod + protection off; **+{EXTRA_CH} op-amp ch "
         f"({EXTRA_CH*IQ_CH*1e3:.1f} mA) added** to each ±10 rail for the channels "
         f"this config omits (16-ch board total). Last 200 ms of {T_END:.0f} s.\n",
         "| tube | T_ss K | **THD** | P_fil | **+10 mean** | +10 peak | **−10 mean** | −10 peak | I_LED |",
         "|---|---|---|---|---|---|---|---|---|"]
    for x in rows:
        if "err" in x:
            L.append(f"| {x['key']} | ERR: {x['err'][:60]} ||||||||"); continue
        vcc_m = x["i_vcc_m"] + EXTRA_CH*IQ_CH
        vee_m = x["i_vee_m"] + EXTRA_CH*IQ_CH
        L.append(f"| {x['key']} | {x['T_ss']:.0f} | **{x['thd']:.1f} dB** | {x['P_fil']*1e3:.0f} mW "
                 f"| **{vcc_m*1e3:.1f} mA** | {x['i_vcc_pk']*1e3:.0f} mA "
                 f"| **{vee_m*1e3:.1f} mA** | {x['i_vee_pk']*1e3:.0f} mA "
                 f"| {x['i_led']*1e3:.1f} mA |")
    out = "\n".join(L) + "\n"
    open(os.path.join(HERE, "rail_budget.md"), "w").write(out)
    print(out)

if __name__ == "__main__":
    main()
