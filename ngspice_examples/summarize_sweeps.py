"""Summarise the closed-loop control-tuning sweeps as readable tables."""
from pathlib import Path
import csv

HERE = Path(__file__).parent

def fmt_table(rows, keys):
    widths = {k: max(len(k), max(len(str(r[k])) for r in rows)) for k in keys}
    def line(vs): return "  ".join(f"{str(v):>{widths[k]}}" for k, v in zip(keys, vs))
    print(line(keys))
    print(line(["-" * widths[k] for k in keys]))
    for r in rows:
        print(line([r[k] for k in keys]))

def fmt_float(x, fmt="{:.2f}"):
    try: return fmt.format(float(x))
    except: return str(x)

def load(p):
    if not p.exists(): return None
    with open(p) as fh:
        return list(csv.DictReader(fh))

print("=" * 78)
print("Soft-start (option B) sweep — V_preset x T_ramp")
print("=" * 78)
rows = load(HERE / "soft_start_sweep.csv")
if rows:
    nice = [{
        "V_preset": fmt_float(r["v_preset"], "{:.2f}V"),
        "T_ramp":   fmt_float(float(r["t_ramp"]) * 1e3, "{:.0f}ms"),
        "T_peak":   fmt_float(r["T_peak"], "{:.0f}K"),
        "T_final":  fmt_float(r["T_final"], "{:.0f}K"),
        "overshoot": fmt_float(r["T_overshoot"], "{:+.0f}K"),
        "t_95tar":  fmt_float(float(r["t_95target"]) * 1e3, "{:.0f}ms"),
        "t_set5K":  fmt_float(float(r["t_settle_5K"]) * 1e3, "{:.0f}ms"),
        "V_ctl":    fmt_float(r["v_ctl_final"], "{:+.3f}V"),
    } for r in rows]
    fmt_table(nice, ["V_preset", "T_ramp", "T_peak", "T_final",
                     "overshoot", "t_95tar", "t_set5K", "V_ctl"])
else:
    print("(soft_start_sweep.csv not found)")
print()

print("=" * 78)
print("Loop-bandwidth (option A) sweep — R_INT scale")
print("=" * 78)
rows = load(HERE / "loop_bw_sweep.csv")
if rows:
    nice = [{
        "R_INT_scale": fmt_float(r["r_int_scale"], "{:.2f}x"),
        "f_int_zero":  fmt_float(r["f_int_zero"],  "{:.1f}Hz"),
        "T_peak":      fmt_float(r["T_peak"], "{:.0f}K"),
        "T_final":     fmt_float(r["T_final"], "{:.0f}K"),
        "overshoot":   fmt_float(r["T_overshoot"], "{:+.0f}K"),
        "t_95tar":     fmt_float(float(r["t_95target"]) * 1e3, "{:.0f}ms"),
        "t_set5K":     fmt_float(float(r["t_settle_5K"]) * 1e3, "{:.0f}ms"),
        "V_ctl":       fmt_float(r["v_ctl_final"], "{:+.3f}V"),
    } for r in rows]
    fmt_table(nice, ["R_INT_scale", "f_int_zero", "T_peak", "T_final",
                     "overshoot", "t_95tar", "t_set5K", "V_ctl"])
else:
    print("(loop_bw_sweep.csv not found)")
