# Cold-start slow loop wake-up: structural cause

Loops on IV-6 and ILC1-1/8 take ~3 s to reach steady state from cold
power-on, dominated by an open-loop integrator slew phase, not by the
filament's thermal time constant (~300 ms). The diagnosis below traces
the cause to the JFET-VCR all-pass topology, then notes that the obvious
fix (soft-start preset) was removed in May 2026 without being tested in
combination with the current high-Ki integrator.

## Mechanism: cold-start signal is rejected as quadrature

The differential drive across the bridge is

    V_d = -K_buf * v_drv_atten * (1 - H_ap)
        = -K_buf * v_drv_atten * 2*j*x / (1 + j*x)
    x   = w0 * R_DS(V_ctl) * C_AP

For `x << 1` (cold start, V_ctl near 0, JFET fully on):

  - |V_d|  is linear in x (small)
  - arg(V_d) is approximately -90 deg from V_osc (quadrature)

The synchronous demodulator's reference is `sign(V_osc)`, which rejects
the quadrature component. Both effects multiply, attenuating the cold-start
demod DC output to ~1.8% of what the loop sees once V_ctl is in the
high-gain region.

## Numerical results (`diag_allpass_coldstart.py`)

Analytical model, R_amb cold filament, V_p = -1.5 V, beta = 2.2e-3:

| Tube      | demod DC @ V_ctl=0 | demod DC @ x=1 | cold/OP gain ratio |
| --------- | ----------------- | -------------- | ------------------ |
| IV-6      |    -2.4 mV        |   -133 mV      |   1.8%             |
| ILC1-1/7  |    -9.9 mV        |   -552 mV      |   1.8%             |
| ILC1-1/8  |    -3.0 mV        |   -166 mV      |   1.8%             |

The 4× per-tube spread on cold-start demod tracks `K_buf`
(IV-6 K=2.0, ILC1-1/8 K=2.5, ILC1-1/7 K=9.1). This explains why
ILC1-1/7 wakes up faster than the smaller tubes even though its larger
filament thermal mass would suggest the opposite.

### ngspice cross-check

`diag_allpass_coldstart_sim.cir` is a minimal cold-bridge sim with
ideal -2x buffer E-sources and fixed V_ctl. ngspice gives:

    V_ctl =  0.00 V : n_demout = +2.55 mV  (analytical: -2.38 mV)
    V_ctl = -0.25 V : n_demout = +3.89 mV  (analytical: -3.41 mV)
    V_ctl = -0.50 V : n_demout = +6.81 mV  (analytical: -5.29 mV)

Magnitudes agree within 7-30% (sign is a convention difference --
my analytical model puts v_osc at phase 0; ngspice has a phase offset
from the Wien startup). The deviation grows at larger |V_ctl| because
the linear-region R_DS approximation breaks down once V_DS / (V_GS-V_p)
is no longer small.

The yesterday `n_demout = -3.6 mV` observation on the full closed-loop
sim matches the model with V_ctl drifted to ~-0.25 V during the
measurement window (analytical predicts -3.4 mV there).

### Slew-time prediction

With Ki = 105/s (current integrator at R_INT_scale=0.3) and the cold
filament held at R_amb, time for V_ctl to traverse from initial preset
to a "wake-up" target where loop gain has recovered:

| Tube      | V_int_preset=0 V | preset=0.30 V | preset=0.60 V | preset=1.00 V |
| --------- | --------------- | ------------- | ------------- | ------------- |
| IV-6      |   1909 ms       |   927 ms      |   327 ms      |    0 ms       |
| ILC1-1/7  |    458 ms       |   223 ms      |    79 ms      |    0 ms       |
| ILC1-1/8  |   1527 ms       |   741 ms      |   261 ms      |    0 ms       |

The ~2 s open-loop slew at zero preset is consistent with the 3.5 s
total settle (slew + thermal warm-up), and consistent with the per-tube
ordering on the May commits.

## The right fix was removed in May 2026

Commit `38f7d95` ("Drop soft-start; loosen reltol from 1e-6 to 1e-4")
removed the V_PRESET network. The diff:

    -* === Soft-start network ===
    -.model swSS SW(VT=0.5 VH=0.05 RON=0.01 ROFF=1G)
    -V_preset_src v_preset_node 0 {v_preset:.4f}
    -V_ss vss 0 PWL(0 1 {max(t_ramp - 0.0005, 0):.6e} 1 ...)
    -S_ss v_int_out v_preset_node vss 0 swSS

The rationale was: with the sharp 1N4148 anti-windup model in place,
loosening reltol from 1e-6 to 1e-4 was enough to converge without the
soft-start network. The network was therefore deemed a "simulator
workaround", not a real-circuit element, and removed.

**The commit conflated two distinct roles of the soft-start network:**

  1. As a convergence aid for tight reltol -- this was indeed a sim artifact
     and was correctly removed.

  2. As a cold-start lever that puts V_int_out past the all-pass
     low-gain region -- this is a legitimate real-circuit benefit, and
     was discarded as collateral.

The `v_preset` and `t_ramp` parameters were left in `make_netlist`'s
signature as dead arguments. The `soft_start_sweep.csv` (16 rows) ran
the parameter sweep AFTER the removal, so all rows produced identical
netlists; the ~25% variation in `t_settle_5K` (3.65 -> 2.72 s) is
numerical timestep noise, not a real effect of v_preset.

**The SETTLING_REPORT.md's "B is marginal, only 9% improvement"
conclusion is therefore not credible** -- the lever was never wired up
when that sweep was run.

## Suggested next steps

  1. Reinstate the V_PRESET network (4 lines + a switch model, lifted
     from the pre-38f7d95 source). Set V_PRESET = 0.55 V, T_RAMP = 30 ms.
     This puts V_int_out at the actual measured OP value (0.54 V from
     soft_start_sweep) at t=0, killing the integrator slew phase entirely.
     Predict: IV-6 settle drops from ~3 s to ~300-500 ms (thermal-limited).

  2. Real-circuit implementation pattern (already in the removed
     comment): analog mux + RC + Zener as a power-on reset, OR a charge
     pump on the integrator cap. Both are buildable with through-hole
     parts under the hobby BOM. No trimming required since V_PRESET is
     a fixed precision-resistor divider off the +/-9 V rails.

  3. After implementation, re-run the per-tube cold-start trajectory
     and verify settle time and overshoot. The overshoot risk is bounded
     by the anti-windup clamp at +2.5 V (already in place); a 0.55 V
     preset is far below clamp.

  4. The 0.54 V OP across all three tubes (per soft_start_sweep.csv)
     is suspicious -- if real, suggests the OP doesn't strongly depend
     on tube parameters, only on K_buf. Verify after the lever is in.

## Postscript (2026-05-15): C_AP path chosen instead of V_PRESET

The V_PRESET reinstatement above was *not* the path taken. Investigation of
the structural cause led to a different fix: raise C_AP so the all-pass
corner sits in the right region of the JFET's R_DS range, addressing the
1.8% cold-start gain ratio at the source rather than papering over the
slew with a power-on preset.

Settled on **C_AP = 470 nF (Murata GRM31C5C1E474JE01L, 1206 C0G, 25 V, 5%)**
in place of the previous 100 nF. Validation across (tube, V_p_typ/-3V)
corners with the manufacturer MOSFET subcircuit:

| Tube      | V_p     | t_settle_5K | V_ctl_OP | bridge   |
| --------- | ------- | ----------- | -------- | -------- |
| IV-6      | -1.5 V  |   1208 ms   | -1.14 V  | 20.00/20 |
| IV-6      | -3.0 V  |   1456 ms   | -2.64 V  | 20.00/20 |
| ILC1-1/7  | -1.5 V  |   1486 ms   | -1.39 V  | 24.98/25 |
| ILC1-1/7  | -3.0 V  |    732 ms   | -2.89 V  | 24.98/25 |
| ILC1-1/8  | -1.5 V  |   1104 ms   | -1.07 V  | 8.00/8   |
| ILC1-1/8  | -3.0 V  |    917 ms   | -2.57 V  | 8.00/8   |

Cold-start settles ~2-4x faster than the 100 nF baseline; all tubes
converge to bridge balance within 0.1% of target R. Worst-case V_p=-3
parts engage the anti-windup clamp at steady state (V_int_out ~0.4 V
past +2.5 V; loop still regulates). See `diag_ilc7_peak.py` and
`ilc7_coldstart_phases.png` for the cold-start phase trajectory:
~12-23 ms slew, ~450 ms pinned at clamp (V_ctl = -3.47 V) while the
filament warms, then release/settle.

Level 1 placeholder MOSFETs were calibrated against manufacturer
subcircuits for the IV-6 V_p=-3 case (see `validate_cap_470nf_iv6max_level1.py`):
every loop metric agreed within 1% with 75x speedup. So Level 1 is
trustworthy for future cold-start / V_ctl sweeps; reserve manufacturer
models for SOA/dissipation work.

The C_AP default in `test_closed_loop.py` has NOT been changed in this
commit -- the validation supports the switch but a separate commit will
flip the default and regenerate the per-tube .cir/.asc artifacts.
