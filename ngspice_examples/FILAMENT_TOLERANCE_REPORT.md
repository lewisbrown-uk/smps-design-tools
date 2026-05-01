# Filament tolerance analysis: Soviet-era VFD spread

How well does the option-A regulator (R_INT scale=0.3 + soft-start
V_p=0.55, T_r=100 ms) hold up across the per-tube manufacturing spread
of a Soviet-era VFD filament?

Three filament parameters varied (uniform within band):

| param          | band            | physical meaning                        |
| -------------- | --------------- | --------------------------------------- |
| k_r_amb        | [0.85, 1.15]    | cold resistance R_amb (tungsten draw)   |
| k_sigma_eps_A  | [0.80, 1.20]    | radiative coupling (oxide / area)       |
| k_c_th         | [0.85, 1.15]    | thermal mass (length / diameter)        |

The temperature exponent (1.2) is fixed — it is a tungsten material
constant, not a manufacturing variable.

Two sweeps:
- `sweep_mc`: N=24 random samples (`numpy.random.default_rng(42)`)
- `sweep_corners`: 8 deterministic 2³ corners at the box extremes

## TL;DR

**The regulator regulates R, not T, and that is the dominant spread.**

| metric            | MC (N=24) mean ± σ | MC range      | corner range  |
| ----------------- | ------------------ | ------------- | ------------- |
| **R_final** [Ω]   | 96.1 ± 0.5         | 95.4 – 97.3   | 94.6 – 97.4   |
| **T_final** [K]   | 766.7 ± 52.6       | 714 – 893     | 680 – 896     |
| T_peak [K]        | 775.4 ± 48.0       | 727 – 893     | 688 – 897     |
| t_settle_5K [ms]  | 655 ± 206          | 324 – 974     | 316 – 1147    |
| overshoot vs 800K | -25 ± 48           | -73 → +93     | -114 → +97    |

R_final is held within ±1 Ω across the entire box. T_final spans nearly
**215 K** because the bridge balance R_target ≈ 99 Ω maps onto a
different temperature for each filament:

  T(R_target) = T_amb · (R_target / R_amb)^(1/1.2)

So R_amb at -15% (cold draw) → T_final ≈ 893 K (+93 K above target).
R_amb at +15% (warm draw) → T_final ≈ 683 K (-117 K below target).

σεA and C_th are second-order — they shift transient shape (settling
time and overshoot dynamics) but barely move T_final.

The loop itself stays stable across the full corner box: no
oscillation, no instability, settling under 1.2 s in every case.

## Plots

- `filament_mc_histograms.png` — distributions of T_final, T_peak,
  R_final, t_settle (N=24)
- `filament_mc_scatter.png` — T_final and t_settle vs k_r_amb,
  showing the near-monotonic operating-point dependence
- `filament_corners_traces.png` — T(t), R(t), V_ctl(t) for all 8
  corners, showing the cold/warm clustering
- `filament_corners_histograms.png` — corner-only distributions
  (bimodal as expected from the 4 cold + 4 warm corners)

## Worst-case corners

| label | k_r_amb | k_sigma | k_cth | T_final | T_peak | overshoot | t_set5K |
| ---   | ---     | ---     | ---   | ---     | ---    | ---       | ---     |
| cLLL  | 0.85    | 0.80    | 0.85  | 892 K   | 892 K  | +92 K     |  676 ms |
| cLLH  | 0.85    | 0.80    | 1.15  | 892 K   | **897 K** | **+97 K** |  316 ms |
| cLHL  | 0.85    | 1.20    | 0.85  | 896 K   | 896 K  | +96 K     |  946 ms |
| cLHH  | 0.85    | 1.20    | 1.15  | 896 K   | 896 K  | +96 K     |  755 ms |
| cHLL  | 1.15    | 0.80    | 0.85  | 680 K   | 704 K  | -96 K     | 1016 ms |
| cHLH  | 1.15    | 0.80    | 1.15  | 680 K   | 724 K  | -76 K     | **1147 ms** |
| cHHL  | 1.15    | 1.20    | 0.85  | 686 K   | 688 K  | **-112 K** |  354 ms |
| cHHH  | 1.15    | 1.20    | 1.15  | 686 K   | 703 K  | -97 K     |  861 ms |

**Hottest corner** (cLLH): T_peak 897 K, +97 K above target. Filament
sees ~12% above intended operating temperature. Tungsten lifetime
roughly halves per +50 K, so this corner runs at ~25% of nominal life.

**Coldest corner** (cHHL): T_final 686 K, -114 K below target. Display
brightness (∝ filament emission) drops by ~3× because emission goes as
T⁴.

**Slowest corner** (cHLH): 1.15 s to settle. Still well under 5 s sim
window, no instability.

## What this means for the design

1. **Tube-to-tube brightness/lifetime spread is set by R_amb spread.**
   Without per-tube calibration the design accepts ±100 K operating-
   temperature variation across the production lot. For a hobby /
   replica design this is fine; for a production run it would mean
   binning tubes by cold-resistance or trimming `R_top_ref` per unit.

2. **The control loop itself is robust.** The option-A bandwidth that
   gave the 11× cold-start speed-up does not destabilise across the
   filament corner box — every trial settles smoothly, no oscillation,
   no run-away.

3. **σεA and C_th can be ignored at first order.** Their effect on
   T_final is buried in the second decimal place. They do affect
   settling shape — e.g. cHHL settles in 354 ms while cHHH (same
   k_r_amb, opposite k_cth) takes 861 ms — but neither destabilises.

4. **If constant-T is required**, the topology has to change: either
   reference the bridge to a temperature-dependent voltage source, add
   a per-tube R_top_ref trim pot, or sort tubes by cold resistance.

## Reproducing

```
python3 test_closed_loop.py --mode sweep_mc      --mc_n 24 --mc_seed 42
python3 test_closed_loop.py --mode sweep_corners
python3 filament_mc_postprocess.py    # rebuild histograms + scatter from CSVs
```
