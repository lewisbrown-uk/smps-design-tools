# Cold-start settling: lever sweep results

Closed-loop VFD-filament regulator. Goal: reduce time-to-settle from
the ~3.5 s baseline to something more practical without melting the
filament (overshoot above 800 K target).

## TL;DR

**Loop bandwidth (option A) is the only useful lever.**
Replacing the integrator network `R_INT=100k, R_PID=1M` with
`R_INT=30k, R_PID=300k` (raises the integrator-zero from 5 Hz to
16.7 Hz) gives:

| metric | baseline | option A (R_INT scale 0.3) |
| --- | --- | --- |
| t_settle (within 5 K of T_final) | **3540 ms** | **324 ms** |
| peak overshoot above target | none (Vos undershoots) | none |
| T_final | 774 K | 775 K |

**~11× faster, no overshoot.** Already pushed into the canonical
`wien_filament_regulator.cir`.

The other three levers are either marginal (B) or unsafe (C, D).

## Results table

Best result from each sweep:

| Lever | Config | t_set_5K | T_peak | overshoot |
| --- | --- | --- | --- | --- |
| Baseline | no lever | 3647 ms | 774 K | none |
| **A: loop bw** | **R_INT scale 0.30 (f_zero 16.7 Hz)** | **324 ms** | **779 K** | **none** |
| B: soft-start (safe) | V_p=0.55, T_r=300 ms | 3220 ms | 775 K | none |
| B: soft-start (greedy) | V_p=0.75, T_r=300 ms | 2716 ms | 882 K | +82 K |
| C: bang-bang | V_p=1.00, T_r=150 ms | 3097 ms | 971 K | +171 K |
| D: pre-heat | 20 mW for 50 ms | 3707 ms | 774 K | none |

See `settling_levers.png` for the cross-comparison bar chart.

## Notes per lever

### A — Loop bandwidth (winner)

Sweep file: `loop_bw_sweep.csv`, traces in `loop_bw_sweep_traces.png`.

R_INT scale | f_int_zero | t_set_5K | overshoot
--- | --- | --- | ---
3.0 | 1.7 Hz | 4800 ms | -95 K (slow capture)
1.0 | 5.0 Hz | 3536 ms | none (baseline)
**0.3** | **16.7 Hz** | **324 ms** | **none**
0.1 | 50.0 Hz | 598 ms | +43 K
0.03 | 167 Hz | 642 ms | +55 K

There is a sweet spot around f_zero = 16.7 Hz. Going faster (0.1 ×)
adds overshoot because the integrator gets too aggressive while the
1 kHz Wien-bridge / synchronous-detection bandwidth is still the
dominant lag.

### B — Soft-start RC bias

Sweep file: `soft_start_sweep.csv`. 16 cases.

Holds `V_int_out = V_preset` for `T_ramp` ms via an analog-switch
PWL ramp, then opens the switch and lets the loop run.

Only marginal benefit when kept safe: best no-overshoot config is
V_p=0.55, T_r=300 ms giving 3220 ms (9% improvement). To get below
3 s the configuration starts producing overshoot — you are essentially
preloading the integrator past the steady-state value.

This is **complementary** to option A but on top of A's already-fast
324 ms response there is no headroom for B to help further.

### C — Bang-bang to PID handoff (unsafe)

Sweep file: `bang_bang_sweep.csv`. 12 cases.

Drive `V_ctl = -1.0` for `T_ramp` ms then hand over to the PID. Best
candidate `V_p=1.00, T_r=150 ms` produces **+171 K overshoot** before
settling. Anything that delivers detectable speedup also delivers
unsafe transients. The natural anti-windup already produces a
bang-bang phase during cold-start.

### D — Pre-heat boost (unsafe)

Sweep file: `preheat_sweep.csv`. 5 cases.

Inject extra `P_boost` watts directly into `T_node` for `t_boost` ms
before letting the regulator take over. 50 mW for 100 ms produces
**+333 K overshoot** — would melt a real filament. No safe operating
window found in the swept range that beats baseline.

## Recommendation

1. **Use option A as the production config** — values already in
   `wien_filament_regulator.cir`:
   `R_intin = 30k, R_intfb = 300k, C_intfb = 318.31n, C_hf = 1.6n`.

2. **Leave the soft-start network in place** (V_preset = 0.55 V,
   T_ramp = 100 ms) — costs nothing in steady state, gives slight
   warm-up help if the f_zero is later moved.

3. **Do not** add bang-bang or pre-heat boost networks. They look
   attractive in fast settling-time numbers but only because they
   blow past the target on the way up.
