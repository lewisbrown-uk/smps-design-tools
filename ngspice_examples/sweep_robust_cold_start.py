"""Sweep cold-start overshoot under realistic part variation, to
confirm the +4.4K nominal margin holds with worst-case real-world
component tolerances.

Sweep axes (one-at-a-time, around the nominal recipe in regulator.py):
- Op-amp Vos: 10µV (sim nominal) → 2mV (typ TLV9001-class) → 5mV (worst-case industrial)
- R_op tolerance: ±10 % (per filament_R_tolerance memory)
- τ_src (Wien startup): 1.5s, 2s, 3s, 5s
- v_buf rail: ±5 %

Worst-case combined: pick the worst-affecting direction of each and
combine.

Each sim runs ~T_end seconds (sim time), wall clock ~ a few min total.
Report tabulated overshoot for each corner.
"""
import sys, subprocess, numpy as np, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import regulator as s5

WORK = Path("/tmp/stage5_robust"); WORK.mkdir(exist_ok=True)

ORIG_NETLIST = s5.make_netlist  # to restore between runs


def run_corner(label, *, vos_uV=10, r_op_pct=0, v_buf_pct=0, t_src=3.0):
    """Apply one-at-a-time deltas to nominal recipe, run cold-start."""
    R_AMB_orig = s5.R_AMB
    # Vary R_op then recompute R_amb (the filament's R at T_amb is what's
    # in the netlist; R_op is the value at T_op)
    R_op_new = s5.R_OP * (1 + r_op_pct / 100.0)
    s5.R_AMB = R_op_new / (s5.T_OP / s5.T_AMB) ** s5.FIL_EXP

    # Vary v_buf
    v_buf_new = 10.0 * (1 + v_buf_pct / 100.0)

    # Render netlist
    cir_text = s5.make_netlist(t_src_ramp=t_src, v_buf=v_buf_new, T_end=6.0)
    # Edit Vos in the op string globally
    cir_text = cir_text.replace("Vos=10u", f"Vos={vos_uV}u")
    cir_text = re.sub(r"wrdata \S+/run\.data",
                      f"wrdata {WORK.as_posix()}/run.data", cir_text)
    (WORK / "d.cir").write_text(cir_text)

    res = subprocess.run(["ngspice", "-b", "d.cir"], cwd=WORK,
                         capture_output=True, text=True, timeout=900)
    s5.R_AMB = R_AMB_orig  # restore
    if res.returncode != 0:
        return None, res.stderr[-300:]

    d = np.loadtxt(WORK / "run.data")
    t = d[:, 0]; T = d[:, 9]; r_fil = d[:, 11]; v_int = d[:, 7]
    T_max = float(np.max(T))
    i_max = int(np.argmax(T))
    T_final = float(T[-1])
    overshoot_K = T_max - 800.0
    # Settling ±2 % (looser to handle the small operating-point shifts
    # introduced by Vos and R_op variation — we care about TRANSIENT
    # overshoot, not steady-state error here)
    band_lo = 800 * 0.98; band_hi = 800 * 1.02
    out = (T < band_lo) | (T > band_hi)
    if out.any():
        last_out = int(np.where(out)[0][-1])
        settle = t[last_out + 1] if last_out < len(t) - 1 else None
    else:
        settle = 0.0
    return dict(label=label,
                T_max=T_max, T_final=T_final,
                overshoot_K=overshoot_K,
                t_T_max=t[i_max],
                settle=settle,
                v_int_final=v_int[-1],
                r_fil_final=r_fil[-1]), None


print("="*100)
print(f"{'corner':<40s} {'T_max [K]':>10s} {'overshoot':>11s} "
      f"{'T_final':>9s} {'V_int_f':>9s} {'settle ±2%':>12s}")
print("-"*100)

corners = [
    ("nominal",                      dict()),
    # ---- Vos sweep ----
    ("Vos = 2 mV (typ industrial)",  dict(vos_uV=2000)),
    ("Vos = 5 mV (worst-case)",      dict(vos_uV=5000)),
    # ---- R_op tolerance ----
    ("R_op +10 % (27.5 Ω)",          dict(r_op_pct=+10)),
    ("R_op -10 % (22.5 Ω)",          dict(r_op_pct=-10)),
    # ---- v_buf tolerance ----
    ("v_buf +5 % (10.5 V)",          dict(v_buf_pct=+5)),
    ("v_buf -5 % (9.5 V)",           dict(v_buf_pct=-5)),
    # ---- τ_src sensitivity ----
    ("τ_src = 1.5 s (faster Wien)",  dict(t_src=1.5)),
    ("τ_src = 2 s",                  dict(t_src=2.0)),
    ("τ_src = 5 s (slower Wien)",    dict(t_src=5.0)),
    # ---- Worst-case combined ----
    # Direction of each that maximizes overshoot:
    #   R_op +10 % → less heat needed for T_op → loop drives less → at the
    #              cold-start regime, R_fil is colder relative to *new*
    #              target, so loop sees larger bridge error → more overshoot
    #   v_buf +5 % → buffer can deliver more drive at rail clip → more overshoot
    #   Vos 5 mV → DC offsets shift operating point; direction depends on signs
    #   τ_src faster → less time-averaging → more overshoot
    ("WORST: τ=1.5s + Vos=5mV + R_op+10% + v_buf+5%",
     dict(vos_uV=5000, r_op_pct=+10, v_buf_pct=+5, t_src=1.5)),
    ("SAFER: τ=5s + Vos=5mV + R_op+10% + v_buf+5%",
     dict(vos_uV=5000, r_op_pct=+10, v_buf_pct=+5, t_src=5.0)),
]

results = []
for label, kw in corners:
    r, err = run_corner(label, **kw)
    if r is None:
        print(f"{label:<40s} FAIL  {err}")
        continue
    settle_s = f"{r['settle']*1000:.0f} ms" if r['settle'] is not None else ">6s"
    print(f"{label:<40s} {r['T_max']:>10.1f} {r['overshoot_K']:>+10.1f}K "
          f"{r['T_final']:>9.1f} {r['v_int_final']:>9.3f} {settle_s:>12s}")
    results.append(r)

print("="*100)
