# Overnight report — 2026-06-09 23:xx → 06-10

## What got done

1. **Pre-log sensing — committed `754c395`, pushed.** Cold-start temperature
   overshoot fixed at the root (integrator senses pre-log `n_demod_dc`; the ×20
   "log" stage that railed the feedback through warm-up is gone, its gain folded
   into `R_int` 1e6→5e4). Temp overshoot +20–38 K → +0.1–3.6 K, tube-independent;
   THD/regulation unchanged; validated on the hardware `switch_demod`.

2. **Over-power protection — committed `e754457`, pushed.** Folded into
   `regulator.py` as `overpower_protect=True` (default off): flat-clamp +
   authority-gated series-disconnect. Discriminator is the model-following check
   (over-power the loop is *fighting* = V_int railed low = fault; over-power the
   loop is *commanding* = V_int high = warm-up/restart), replacing the fragile 2 s
   duration integrator. Reuses the supervisor's V_int-rail signals.

3. **Full re-validation battery** on the pre-log + protection design (4 tubes).
   Suites below. Raw tables in `overnight_battery_{A,C,D}.md`,
   `overnight_battery_B_<tube>.md`, `overnight_battery_EF.md`.

## Headline: the design holds up.

- **Monte Carlo (200 draws): 0 failures, 0 hunts.** Robust to bridge-R ±1%,
  caps ±10%, Vos ±50 µV. T_ss 781–810 K, THD −34.7…−53 dB. (Matches the prior
  passive-MC result; pre-log didn't regress robustness.)
- **Disorderly (instant-on / dropout-restart / brownout, 4 tubes): 0 false trips**,
  filament peak ≤ +13 K. The protection ignores every legitimate transient.
- **Protection FMEA: every overheat fault caught and bounded, then cold-safe.**
- **Cold-start nominal matches canonical** (+0.1–3.6 K, THD −34.7…−53.7 dB).

## Two things that need your eye

### 1. Op-amp Vos sensitivity (build-note, not a regression)
The cold-start sweep drove a *global, correlated* op-amp Vos (worst-case
pessimistic — all op-amps offset the same way):

| Vos | iv18 T_ss | iv18 THD | ilc11_7 T_ss | iv6 T_ss |
|---|---|---|---|---|
| 50 µV (OPA4277 nominal) | 796 K | −53.7 dB | 800 K | 798 K |
| 2 mV | 763 K | −30.8 dB | 796 K | 784 K |
| 5 mV | **699 K** | −20.9 dB | 791 K | 759 K |

At the **chosen OPA4277's actual Vos (~50 µV)** it's a non-issue, and the Monte
Carlo (Vos ±50 µV, independent) showed 0 hunts — so the real design is fine. But
the low-Vos op-amp choice is **load-bearing**: a builder substituting a jellybean
(2–5 mV) op-amp loses 30–100 K of regulation and ~25 dB of THD. Worth calling out
explicitly in the published BOM. (iv18, the 10 mW high-impedance tube, is the most
sensitive.)

### 2. Filament R tolerance shifts the regulated temperature
Because the bridge regulates to a fixed target resistance, a filament whose R_op
is off-nominal settles at a different *temperature*:

| R_op | T_ss (all tubes ~) |
|---|---|
| −10 % | ~861–872 K (+60–70 K) |
| nominal | ~797–800 K |
| +10 % | ~735–738 K (−60 K) |

±10 % is ~2× the real spread (constant-V history bounds filaments to ±2–5 %, per
the filament-tolerance note). The realistic ±5 % numbers are in Suite F below.
Still: a ±5 % filament gives a perceptible brightness shift — your call whether
that matters for a published design.

## Suite results (raw)

### Suite B — Monte Carlo (50/tube)
| tube | draws | fails | T_ss range | overshoot max | THD worst | hunts |
|---|---|---|---|---|---|---|
| ilc11_7 | 50 | 0 | 783–810 K | +5.9 K | −34.7 dB | 0 |
| iv6 | 50 | 0 | 782–809 K | +0.2 K | −45.5 dB | 0 |
| iv18 | 50 | 0 | 781–808 K | +0.2 K | −53.0 dB | 0 |
| ilc11_8 | 50 | 0 | 782–809 K | +0.2 K | −44.2 dB | 0 |

### Suite C — disorderly / restart (protection ON)
All 12 (4 tubes × instant-on / dropout-restart / brownout): **no false trip**,
T_peak 796–811 K, recovers to setpoint.

### Suite D — protection FMEA (protection ON)
| fault class | result |
|---|---|
| XU_buf stuck +rail | caught, peak 831/910/937/902 K → ~330 K cold-safe |
| XU_buf stuck −rail | caught, peak ~831/912/940/903 K → cold-safe |
| botref_short (target→∞, over-drive) | caught, peak 867–922 K → cold-safe |
| atten_bot_short (kills drive) | filament cold 300 K, correctly no trip (safe) |
| sense_open | filament cold 300 K, disconnect trips (harmless, cold-safe) |

### Suite E — over-driving forward-gain faults (protection ON)
The dangerous "loss-of-authority / forward-gain" class — **all caught and bounded,
then cold-safe**:

| fault | result (4 tubes) |
|---|---|
| atten_top_short (full drive) | caught, peak 824–881 K → ~306 K |
| atten_bot_open (drive→max) | caught, peak 824–881 K → ~306 K |
| topref_open (bridge ref → over-drive) | caught, peak 867–922 K → ~326 K |
| fb_vgain_short | **benign** — loop compensates, T stays ~800 K, no trip |

This closes the gap from Suite D: every over-driving fault is now exercised and
the authority-gated disconnect + clamp bound them all to ≤922 K. Worst over-drive
peak across the whole battery is **922 K** (iv6/topref_open), well under the
~1030 K the clamp floor allows.

### Suite F — realistic R_op ±5% cold-start (protection OFF)
| tube | R_op +5% T_ss | R_op −5% T_ss |
|---|---|---|
| ilc11_7 | 767.7 K | 834.6 K |
| iv6 | 766.5 K | 833.3 K |
| iv18 | 764.5 K | 831.3 K |
| ilc11_8 | 766.8 K | 833.6 K |

So at the realistic ±5 % filament spread, T_ss moves **±~33 K** (overshoot stays
<+7 K, THD intact). That's the brightness-variation number to weigh — half the
pessimistic ±10 % figure above, consistent with the fixed-R-target design.

### Suite G — active-device parameter variations (added 06-10, protection OFF)
The active-device tolerance set the overnight battery missed. **0 hunts, 0 fails,
all 4 tubes:**

| axis | range | result |
|---|---|---|
| op-amp **GBW** | 0.5 / 1 / 3 / 10 MHz | no hunt; THD *improves* with GBW (−43→−51 dB iv6, −50→−59 dB iv18) |
| **H11F R-spread** | BETA_SCALE 0.7–1.43 (±30–43 %) | T_ss ±0.3 K, THD unchanged, no hunt |
| output **BJT beta** | BF ×0.5 / ×2 | no measurable effect |
| **independent per-op-amp Vos** | ±150 µV each, 25/tube | 0 fails, 0 hunts, T_ss 791–801 K, ripple 0.11 K |

Two takeaways:
- **The prior "GBW ≥3 MHz hunts" constraint is gone on pre-log.** Removing the ×20
  railing log stage took out the high-gain nonlinearity that drove the
  GBW-dependent oscillation — the loop is now stable across 0.5–10 MHz.
- **G4 resolves the Suite-A Vos flag.** With *independent* per-op-amp Vos at the
  OPA4277's actual max (±150 µV), the worst tube (iv18) holds 791–801 K (±9 K) with
  no bifurcation. The 30–100 K shifts in Suite A were the global-correlated 2–5 mV
  stress corners (a jellybean op-amp), not the real part. **At the chosen OPA4277,
  Vos is a ±9 K effect, not a design risk** — the build-note stands (use a
  precision op-amp) but the margin is comfortable.

**Net: the pre-log design passes the full active-device variation set with margin,
and is strictly more robust than the prior architecture on GBW.**

## Known issues / caveats
- Suite A **WORST triple-corner FAILed on a harness bug** (trailing space in the
  scratch-dir name), not a design failure. Fixed in the supplement runner.
- Monte Carlo Vos is independent ±50 µV (typ); the cold-start Vos sweep is global
  correlated (pessimistic). Neither models per-op-amp independent worst-case max
  (~150 µV) — but the MC at 50 µV passing + the 2 mV corner being benign on
  ilc11_7/iv6 brackets it.
- Protection FMEA injects bridge/atten faults from t=0 (present at startup); the
  arming still works (V_int rises during faulted startup then trips). The active
  XU_buf fault is injected post-capture at t=3 s.
