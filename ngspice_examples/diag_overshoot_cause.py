"""Diagnose what's actually setting the cold-start overshoot in the
SE H11F arch.

Hypothesis: the loop hits buffer rail-clip during the warm-up phase,
which means the loop is *open-loop* during the critical thermal-rise
window.  In that case overshoot is set by the buffer's max-deliverable
P_fil, not by the compensator.

Method: run cold-start, instrument v_drv (vgain output) and
v_osc_drive (buffer output) along with the standard signals.  Compute
their peak envelopes vs the op-amp / buffer rails.  If v_drv hits the
opamp rail and v_osc_drive hits ~(v_buf - V_CE,sat) during the warm-up
window, the overshoot is buffer-limited.
"""
from pathlib import Path
import subprocess, numpy as np, sys

WORK = Path("/tmp/stage5_diag_overshoot")
WORK.mkdir(exist_ok=True)

sys.path.insert(0, str(Path(__file__).parent))
from regulator import make_netlist  # reuse the netlist builder

# Force a save list that includes v_drv and v_osc_drive in known columns.
# Re-render the netlist with cold_start=True (not preloaded) so we see
# the unmitigated transient.
cir_text = make_netlist(cold_start=True, instrument_power=False, T_end=2.0)

# Append v_drv and v_osc_drive to .save / wrdata
cir_text = cir_text.replace(
    ".save v(v_osc_drive) v(node_A) v(n_demod_dc) v(v_int) v(T_node) v(r_fil) v(n_led_a)",
    ".save v(v_osc_drive) v(node_A) v(n_demod_dc) v(v_int) v(T_node) v(r_fil) v(n_led_a) v(v_drv) v(v_int_raw) v(e_sat)"
)
import re
cir_text = re.sub(
    r"wrdata \S+/run\.data v\(v_osc_drive\) v\(node_A\) v\(n_demod_dc\) v\(v_int\) v\(T_node\) v\(r_fil\) v\(n_led_a\)",
    f"wrdata {WORK.as_posix()}/run.data v(v_osc_drive) v(node_A) v(n_demod_dc) v(v_int) v(T_node) v(r_fil) v(n_led_a) v(v_drv) v(v_int_raw) v(e_sat)",
    cir_text)

cir = WORK / "diag.cir"
cir.write_text(cir_text)
res = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                    capture_output=True, text=True, timeout=600)
if res.returncode != 0:
    print("ngspice failed:", res.stderr[-1000:]); sys.exit(1)

d = np.loadtxt(WORK / "run.data")
# Columns: t, v_osc, t, node_A, t, demod, t, v_int, t, T_node, t, r_fil,
#          t, n_led_a, t, v_drv, t, v_int_raw, t, e_sat
t      = d[:, 0]
v_osc  = d[:, 1]
node_A = d[:, 3]
demod  = d[:, 5]
v_int  = d[:, 7]
T_node = d[:, 9]
r_fil  = d[:, 11]
n_led  = d[:, 13]
v_drv  = d[:, 15]
v_int_raw = d[:, 17]
e_sat  = d[:, 19]

v_fil = v_osc - node_A

# Peak envelopes via per-bin max-|x| over 1ms windows (one signal cycle).
def env(t_arr, x_arr, bin_s=1e-3):
    bins = np.arange(t_arr[0], t_arr[-1], bin_s)
    out = np.zeros_like(bins)
    for i, b in enumerate(bins):
        mask = (t_arr >= b) & (t_arr < b+bin_s)
        out[i] = np.max(np.abs(x_arr[mask])) if mask.any() else np.nan
    return bins, out

tb, v_drv_env = env(t, v_drv)
_, v_osc_env  = env(t, v_osc)
_, v_fil_env  = env(t, v_fil)

# Buffer rail and op-amp rail
V_BUF = 10.0
OP_RAIL = V_BUF - 0.1  # uopamp_lvl3 Vrail=0.1 means rail-to-rail to within 100mV

# Print at key timepoints: t=1ms, 5ms, 50ms, 100ms, 250ms (T peak), 500ms, 1s
print(f"{'t [ms]':>8} {'T [K]':>8} {'r_fil [Ω]':>10} {'V_int [V]':>10} "
      f"{'V_int_raw':>10} {'e_sat':>8} {'v_drv_pk':>10} {'v_osc_pk':>10} "
      f"{'V_fil_pk':>10} {'rail-clip?':>11}")
for t_check in [0.001, 0.005, 0.05, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0]:
    idx = int(np.argmin(np.abs(tb - t_check)))
    idx_full = int(np.argmin(np.abs(t - t_check)))
    rail_clip = "YES" if v_drv_env[idx] >= OP_RAIL - 0.2 else "no"
    print(f"{tb[idx]*1000:>8.0f} {T_node[idx_full]:>8.1f} {r_fil[idx_full]:>10.3f} "
          f"{v_int[idx_full]:>10.3f} {v_int_raw[idx_full]:>10.3f} "
          f"{e_sat[idx_full]:>8.3f} {v_drv_env[idx]:>10.3f} {v_osc_env[idx]:>10.3f} "
          f"{v_fil_env[idx]:>10.3f} {rail_clip:>11s}")

# Compute fraction of time during 0-500ms that v_drv is rail-clipped
mask_window = (tb >= 0) & (tb <= 0.5)
frac_clipped = np.mean(v_drv_env[mask_window] >= OP_RAIL - 0.2)
print(f"\nFraction of 0-500ms window with v_drv rail-clipped: {frac_clipped*100:.1f}%")

# At T peak: what is the buffer doing?
i_peak = int(np.argmax(T_node))
print(f"\nAt T_max = {T_node[i_peak]:.1f} K at t = {t[i_peak]*1000:.0f} ms:")
# Get peak envelope at this time
idx_b = int(np.argmin(np.abs(tb - t[i_peak])))
print(f"  v_drv envelope:        {v_drv_env[idx_b]:.3f} V_pk  (op-amp rail = {OP_RAIL:.2f})")
print(f"  v_osc_drive envelope:  {v_osc_env[idx_b]:.3f} V_pk")
print(f"  V_fil envelope:        {v_fil_env[idx_b]:.3f} V_pk")
print(f"  V_int (clamped):       {v_int[i_peak]:.3f} V")
print(f"  V_int_raw (free):      {v_int_raw[i_peak]:.3f} V")
print(f"  e_sat (windup margin): {e_sat[i_peak]:.3f} V")
print(f"  R_fil:                 {r_fil[i_peak]:.3f} Ω")
print(f"  V_fil_RMS estimate:    {v_fil_env[idx_b]/np.sqrt(2):.3f} V")
print(f"  P_fil estimate:        {(v_fil_env[idx_b]/np.sqrt(2))**2/r_fil[i_peak]*1e3:.0f} mW")

# Compare to: what is the max P_fil the buffer can deliver at this R_fil?
# Buffer max V_osc = OP_RAIL (since the booster output stage can swing rail-to-rail)
# Actually with BC337/BC327 and v_buf=10, the V_osc max is approximately
# v_buf - V_CE,sat ≈ 10 - 0.5 = 9.5 V_pk
v_osc_max_pk = V_BUF - 0.5
v_fil_max_pk = v_osc_max_pk * r_fil[i_peak] / (r_fil[i_peak] + 5)
v_fil_max_rms = v_fil_max_pk / np.sqrt(2)
p_fil_max = v_fil_max_rms**2 / r_fil[i_peak]
print(f"\nBuffer-saturated max delivery at R_fil={r_fil[i_peak]:.2f}:")
print(f"  V_fil_max_pk:  {v_fil_max_pk:.3f} V")
print(f"  V_fil_max_rms: {v_fil_max_rms:.3f} V")
print(f"  P_fil_max:     {p_fil_max*1e3:.0f} mW")
print(f"  P_rad at observed T_max ({T_node[i_peak]:.0f}K): "
      f"{2.44e-12 * T_node[i_peak]**4 * 1e3:.0f} mW   "
      f"(if P_fil_max >> P_rad this is buffer-limited)")
