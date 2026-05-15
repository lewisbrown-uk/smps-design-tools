"""One-off retry of the iv6_vpmax case after I accidentally SIGUSR1'd it.
Writes its single result to cap_470nf_iv6max_results.csv so it doesn't fight
with the main parallel driver."""
import sys, csv, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from validate_cap_470nf import run_case

if __name__ == "__main__":
    t0 = time.time()
    m = run_case("iv6", "max", -3.0)
    tag = "OK " if m["ok"] else "FAIL"
    print(f"  {tag}  {m['tube']:9s} V_p={m['vp_value']:+.1f}V  "
          f"V_ctl_OP={m['v_ctl_OP']:+.2f}V  V_ctl_pk={m['v_ctl_peak']:+.2f}V  "
          f"t_settle_5K={m['t_settle_5K']*1e3:.0f}ms  "
          f"R_final={m['R_fil_final']:.2f}/{m['R_fil_target']:.0f}Ω  "
          f"T_final={m['T_final']:.0f}/{m['T_target']:.0f}K  "
          f"R_pk={m['R_fil_peak']:.1f}Ω  ({m['wall_s']/60:.1f} min)", flush=True)
    out = HERE / "cap_470nf_iv6max_results.csv"
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(m.keys())); w.writeheader(); w.writerow(m)
    print(f"Wrote {out}; total wall {(time.time()-t0)/60:.1f} min")
