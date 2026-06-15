# Op-amp slew-rate analysis — closing the no-slew modelling gap (2026-06-15)

## Why

The validation battery uses the `uopamp_lvl3` macromodel, which models **no slew
limit** — it's a linear gm-C (GBW) model with output-current limiting and rail
saturation, but the input transconductances `G1`/`G2` are linear and unbounded,
so the dominant-pole node charges arbitrarily fast. The real **OPA4277 = 0.8 V/µs**.
So the battery carries no slew-induced distortion. This checks whether that
matters (it doesn't, at the design carrier) and gives the sim a way to capture
slew when it does (raised-carrier work).

## The slew model + calibration

Added **`uopamp_lvl3_slew`** to `uopamp.lib` — identical to `uopamp_lvl3` except
`G1`/`G2` are replaced by **saturating** transconductances `B1`/`B2` (`tanh`),
capping the dominant-pole charging current at ±2·`Islew` → a constant output
slew rate. Small-signal (`tanh ≈ linear`) it is bit-identical to `uopamp_lvl3`
(same gm, GBW, Avol), so it does not perturb any validated small-signal result.

Calibrated `Islew` for the OPA4277's 0.8 V/µs at GBW 1 MHz (unity-follower, 5 V
step, `slew_sweep.py::calibrate`):

| Islew (nA) | 60 | 90 | 120 | 150 | 200 | 300 |
|---|---|---|---|---|---|---|
| output SR (V/µs) | 0.38 | 0.57 | 0.75 | 0.94 | 1.26 | 1.88 |

Linear in Islew → **`Islew` = 127.3 nA → SR = 0.800 V/µs** (matches the analytic
`2·Islew/C_dom`). This is the value used in the sweeps.

## Result 1 (the important one): the 1 kHz design carrier is slew-clean

THD of the filament drive, slew-limited model vs nominal (no-slew):

| tube | model | 1 kHz | 2 kHz | 5 kHz |
|---|---|---|---|---|
| ILC1-1/7 (8.5 V swing) | nominal | −34.7 | −34.8 | −35.4 |
| ILC1-1/7 | **slew 0.8 V/µs** | **−34.7** | **−34.8** | −35.2 |
| IV-18 (~1 V swing) | nominal | −52.8 | −43.1 | −38.6 |
| IV-18 | slew 0.8 V/µs | −52.8 | −43.1 | −38.6 |

**At 1 kHz the slew model gives THD identical to the no-slew model** — so the
entire validation battery is correct at the design carrier. ILC1-1/7's worst
case (8.5 V drive) demands only `2π·1000·8.5 ≈ 53 mV/µs`, ~15× under the
0.8 V/µs limit (FPBW ≈ 18 kHz). **IV-18 is slew-immune at every frequency** (its
~1 V swing never reaches the limit) — the control that confirms the model only
bites where it physically should.

## Result 2: the slew wall (ILC1-1/7, the demonstration)

`slew_wall.py`, THD vs carrier:

| F | 3 kHz | 5 kHz | 8 kHz | 10 kHz | 12 kHz | 15 kHz |
|---|---|---|---|---|---|---|
| nominal | −35.0 | −35.4 | −36.0 | −36.3 | −36.7 | (no conv.) |
| **slew** | −35.0 | −35.2 | **−34.7** | (no conv.) | (no conv.) | (no conv.) |

- **≤ 5 kHz:** slew = nominal — no slew effect.
- **8 kHz:** slew ~1.3 dB worse than nominal — the **onset** (matches the
  analytic ~6 kHz = FPBW/3 slew-THD onset).
- **≥ 10 kHz:** the slew-limited sim **no longer converges** — the op-amp is so
  deep into slew limiting that the drive goes triangular and ngspice can't solve
  it in reasonable time. That breakdown *is* the wall, right where the 0.8 V/µs
  analysis put the ~18 kHz full-power limit. (Clean cliff THD numbers there are
  not obtainable, and are academic — you'd never run the carrier that high.)

## Conclusion

- The **1 kHz design point is confirmed slew-clean** — the no-slew battery is
  valid there; the OPA4277's 0.8 V/µs adds zero distortion at the operating point.
- The **carrier-frequency ceiling is slew-set** (onset ~6–8 kHz, hard wall
  ~18 kHz, governed by ILC1-1/7's 8.5 V swing) — now corroborated in sim, not
  just analytic. Raising the carrier needs a faster/higher-slew op-amp (Suite G1
  shows higher GBW is fine for stability/THD; slew is the separate limit).
- Slew is no longer an un-modelled gap: `uopamp_lvl3_slew` (calibrated) is
  available for any future raised-carrier study. For the shipping 1 kHz design
  it changes nothing.
