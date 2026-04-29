"""Cross-sweep comparison: best settling time achievable from each option.

Reads all four sweep CSVs and produces:
  - settling_levers.png: bar chart of best (min t_settle_5K) per option,
    with overshoot annotated
  - prints a Markdown-ready summary table
"""
from pathlib import Path
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent

def load(p):
    if not p.exists(): return []
    with open(p) as fh: return list(csv.DictReader(fh))

def pick_best(rows, key="t_settle_5K"):
    """Pick the row with smallest settling time."""
    if not rows: return None
    rows_clean = [r for r in rows if r.get(key) and r[key] != "nan"]
    if not rows_clean: return None
    return min(rows_clean, key=lambda r: float(r[key]))

# Load each sweep
b_rows = load(HERE / "soft_start_sweep.csv")
a_rows = load(HERE / "loop_bw_sweep.csv")
c_rows = load(HERE / "bang_bang_sweep.csv")
d_rows = load(HERE / "preheat_sweep.csv")

# Identify baseline = the row with v_preset=0 and t_ramp=0 in soft-start sweep
baseline = next((r for r in b_rows
                 if float(r.get("v_preset", -1)) == 0.0
                 and float(r.get("t_ramp", -1)) == 0.0), None)

# Best of each
b_best = pick_best([r for r in b_rows
                    if float(r.get("v_preset", 0)) > 0])
a_best = pick_best(a_rows)
c_best = pick_best(c_rows)
d_best = pick_best([r for r in d_rows
                    if float(r.get("p_boost", 0)) > 0])

def fmt(x, fmt="{:.2f}"):
    try:
        v = float(x);
        return fmt.format(v)
    except:
        return "-"

print("# Settling-time comparison across the four levers\n")
print("Each row is the best (min t_settle_5K) result from each sweep.\n")
print("| Lever | Config | t_set_5K (ms) | T_peak (K) | T_final (K) | overshoot (K) | V_ctl_final |")
print("| --- | --- | --- | --- | --- | --- | --- |")

def row(name, config, r):
    if r is None:
        print(f"| {name} | {config} | — | — | — | — | — |")
        return
    print(f"| {name} | {config} | "
          f"{fmt(float(r['t_settle_5K'])*1e3, '{:.0f}')} | "
          f"{fmt(r['T_peak'], '{:.0f}')} | "
          f"{fmt(r['T_final'], '{:.0f}')} | "
          f"{fmt(r['T_overshoot'], '{:+.0f}')} | "
          f"{fmt(r['v_ctl_final'], '{:+.3f}')} |")

row("Baseline", "no lever", baseline)
if b_best:
    row("B: soft-start", f"V_p={fmt(b_best.get('v_preset'),'{:.2f}')}V, T_r={fmt(float(b_best.get('t_ramp',0))*1e3,'{:.0f}')}ms", b_best)
if a_best:
    row("A: loop bw", f"R_INT scale={fmt(a_best.get('r_int_scale'),'{:.2f}')} (f_zero={fmt(a_best.get('f_int_zero'),'{:.1f}')}Hz)", a_best)
if c_best:
    row("C: bang-bang", f"V_p={fmt(c_best.get('v_preset'),'{:.2f}')}V, T_r={fmt(float(c_best.get('t_ramp',0))*1e3,'{:.0f}')}ms", c_best)
if d_best:
    row("D: pre-heat", f"P_b={fmt(float(d_best.get('p_boost',0))*1e3,'{:.0f}')}mW, t_b={fmt(float(d_best.get('t_boost',0))*1e3,'{:.0f}')}ms", d_best)

# Bar chart
print("\nMaking comparison bar chart...")
labels, vals_t, vals_o = [], [], []
for name, r in [
    ("baseline\n(no lever)", baseline),
    ("B: soft-start", b_best),
    ("A: loop bw", a_best),
    ("C: bang-bang", c_best),
    ("D: pre-heat", d_best),
]:
    if r is None:
        continue
    labels.append(name)
    vals_t.append(float(r["t_settle_5K"]) * 1e3)
    vals_o.append(float(r["T_overshoot"]))

if labels:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    ax_t, ax_o = axes
    colors = ["0.5", "C0", "C2", "C3", "C4"][:len(labels)]
    ax_t.bar(labels, vals_t, color=colors); ax_t.set_ylabel("t_settle_5K [ms]"); ax_t.grid(True, axis="y", alpha=0.4)
    for i, v in enumerate(vals_t): ax_t.text(i, v, f"{v:.0f}", ha="center", va="bottom", fontsize=10)
    ax_t.set_title("Settling time (best of each lever)")

    ax_o.bar(labels, vals_o, color=colors); ax_o.set_ylabel("T_overshoot above target [K]"); ax_o.grid(True, axis="y", alpha=0.4)
    ax_o.axhline(0, color="0.3", lw=0.5)
    for i, v in enumerate(vals_o): ax_o.text(i, v, f"{v:+.0f}", ha="center", va="bottom" if v>=0 else "top", fontsize=10)
    ax_o.set_title("Peak overshoot above 800 K target")
    fig.suptitle("Cold-start lever comparison")
    fig.tight_layout()
    fig.savefig(HERE / "settling_levers.png", dpi=120); plt.close(fig)
    print(f"Wrote {HERE/'settling_levers.png'}")
