# BOM — VFD filament regulator (4 tubes, canonical design)

Real-part mapping for the **canonical `regulator.py` design** (H11F
variable-gain + BJT class-AB push-pull). Target ≤ $20/tube, **no
build-time trimming**, all parts stocked at DigiKey/Mouser. **This is a
surface-mount build** — every part is specified in its SMD package
(SOIC / SOT-23 / SOT-89 / SOD-323 / 0805); no through-hole.

Reference designators follow the `regulator_<tube>.cir` element names.

> **Supersedes the previous all-pass BOM (2026-06).** The earlier BOM
> described the retired JFET/H11F *all-pass* architecture
> (`test_closed_loop.py`, now deprecated): TLV9154 quads + OPA2188
> chopper, all-pass legs, a V→I LED converter, and per-tube MOSFET
> boosters. The canonical design is a different circuit and is **much
> simpler per-tube** — see the architecture note below.

---

## Architecture (what the canonical circuit is)

Signal flow: **Wien oscillator (1 kHz)** → attenuator → **H11F
variable-gain Stage 1** (H11F photo-FET in the feedback, ∥ R_max) →
**Stage 2** (fixed gain G2 = 25) → AC-couple → **BJT class-AB push-pull
buffer** → series sense → **AC bridge** (filament vs reference) →
bridge buffers → **diff amp** → **synchronous demod** (chopper) → LP →
**log demod** → **PID integrator** with back-calc anti-windup → drives
the **H11F LED** (via `R_led_set`), closing the loop. The H11F's
LED-current-controlled resistance sets Stage-1 gain → filament drive →
filament temperature, regulated against the bridge reference.

**Key simplification vs the old all-pass design — only FOUR things vary
per tube:** the three bridge-reference resistors and the oscillator
drive level (set by the attenuator). The op-amps, output stage, gain
chain, compensator, LED drive, and rails are **identical across all four
tubes.** (`R_op`/`V_op`/`T_op` in the netlist are *filament physical
properties* used to calibrate the thermal model — not parts to buy.)

---

## Per-tube variants (the ONLY per-tube parts)

| element     | IV-18 | IV-6 | ILC1-1/7 | ILC1-1/8 | notes |
|-------------|-------|------|----------|----------|-------|
| `R_topref`  | 1 kΩ  | 2 kΩ | 5 kΩ     | 800 Ω    | bridge top ref; 1 % thin-film 0805 |
| `R_botref`  | 100 Ω | 500 Ω| 1 kΩ     | 200 Ω    | bridge bottom ref; 1 % thin-film |
| `R_sense`   | 10 Ω  | 5 Ω  | 5 Ω      | 2 Ω      | bridge sense leg, in series with the filament (carries the load current); 1 %. Per-element dissipation (full power audit): **ILC1-1/7 ~166 mW → ½ W part**; ILC1-1/8 ~45 mW → ¼ W (0805 marginal); IV-6 ~12 mW and IV-18 ~1 mW → plain 0805. |
| oscillator level | ↓ | ↓ | ↓ | ↓ | set by the attenuator divider so the carrier into Stage 1 matches the tube; in sim = `V_src_rms` 0.018 / 0.020 / 0.100 / 0.024 |
| target R_fil | 100 Ω | 20 Ω | 25 Ω | 8 Ω | = R_sense·R_topref/R_botref (held by the loop) |

**Bridge sets the regulated point:** `R_fil = R_sense · R_topref / R_botref`.
With 1 % resistors the guaranteed worst-case is **±3 % R_fil / +21 K T**
(8-corner analysis). The three bridge resistors are the *only* lever for
tighter temperature uniformity — use 0.5 %/0.1 % thin-film there if you
want it; **caps and every other resistor are irrelevant to R_fil/T.**
Filament-R part variation maps as `T ≈ T_op·(R_actual/R_nominal)^(1/1.2)`;
the constant-voltage mains-winding history bounds real filament spread to
a few %, well inside loop authority (no binning needed).

**Oscillator level per tube:** with one fixed-amplitude Wien (≈2.5 V_rms,
see "Source"), set the per-tube carrier by the attenuator divider
(`R_atten_top`/`R_atten_bot`) rather than a different oscillator. The sim
abstracts this as `V_src_rms`; in hardware it is the divider ratio (one
E96 resistor chosen per tube — a build-time *selection*, not a trim).

---

## Op-amps — 3 × OPA4277 quad (all 10 positions)

The 10 op-amp channels collapse into **3 quad packages** (12 channels,
2 spare). Quad packaging is verified safe here (see "Coupling").

| pkg | channels (netlist) | function |
|-----|--------------------|----------|
| **U1 (OPA4277)** | `XU_atten_buf`, `XU_vgain`, `XU_s2`, `XU_buf` | source attenuator buffer + H11F Stage-1 + Stage-2 gain + class-AB driver |
| **U2 (OPA4277)** | `XU_buf_A`, `XU_buf_B`, `XU_da`, `XU_log` | two bridge buffers + diff amp + log demod |
| **U3 (OPA4277)** | `XU_int`, `XU_aw_diff`, +2 spare | PID integrator + anti-windup diff amp; spares buffer the V_clamp refs |

- **OPA4277UA** (SOIC-14).
  Precision bipolar, OP07-class: Vos ~10 µV typ (~50 µV max), drift
  ±0.1 µV/°C, **GBW 1 MHz**, A_OL 134 dB, CMRR ~140 dB, **PSRR ~130 dB**,
  channel separation **±1 µV/V**, BJT class-AB output (no LM358 crossover).
- **Why OPA4277 / why 1 MHz:** the GBW sweep showed low GBW is the THD
  sweet spot — 1 MHz best, ≥3 MHz both degrades THD ~10 dB *and* hunts
  under Vos patterns. 1 MHz is ideal; do **not** substitute a faster part.
- **Vos:** the design is Vos-insensitive (Fix A's G2 = 25 keeps cumulative
  Vos·G2 small); 1024-case ±2 mV cube passes. Economy grade is fine.
- **Coupling / why quads are OK:** channel separation ±1 µV/V and 130 dB
  PSRR; a shared-supply coupling sim (pessimistic 0.3 Ω pin impedance,
  adversarial grouping, model PSRR 62 dB ≪ real 130 dB) gave only
  −0.14 dB THD penalty. One bypass cap (100 nF) per package.
- **Single-pack fallback:** OP07CDR (£0.18, 0.6 MHz) on 10 single SOIC-8
  positions if quads are ever undesired — same performance, more packages.

---

## H11F variable-gain actuator + LED drive

| RefDes | element | part | notes |
|--------|---------|------|-------|
| **U4** | `X_h11f` (variable-R in Stage-1 feedback) | **H11F1M** photo-FET optocoupler (onsemi/Vishay), DIP-6 or SMD-6 | symmetric bilateral photo-FET; R(I_LED) ≈ 100 Ω (at 16 mA) … 300 MΩ (dark). LED anode↔FET isolated. Variants: H11F2M/H11F3M (higher R_typ). |
| `R_led_set` | LED series resistor (sets I_LED) | 270 Ω, 1 %, 0805 | between the +5 V LED supply and the LED anode; cathode returns to the integrator output `v_int`. I_LED ≈ (5 − V_F − v_int)/270 ≈ 4–14 mA over the operating range. |

No V→I converter, no gate bootstrap (those were all-pass-era parts).
H11F **part-to-part R spread is a non-issue** here: the split-gain
`R_max_s1 = 24 Ω` swamps it (the spec-max 2× R part is bit-identical to
typical in sim; the integrator absorbs the rest). No matched-pair
sourcing, no trimming.

---

## BJT class-AB push-pull output buffer (identical all tubes)

| RefDes | element | part | notes |
|--------|---------|------|-------|
| **Q1 (Q_o_out_n)** | top NPN output | **BCX54** (NPN, SOT-89, 1 A, VCEO 45 V) | delivers ~340 mA_pk (ILC1-1/7) |
| **Q2 (Q_o_out_p)** | bottom PNP output | **BCX51** (PNP, SOT-89, 1 A, VCEO 45 V) | complementary to Q1 |
| **Q3 (Q_o_drv_n)** | top NPN driver | BCX54 | pre-driver |
| **Q4 (Q_o_drv_p)** | bottom PNP driver | BCX51 | pre-driver |
| **Q_vbm_t, Q_vbm_b** | V_BE-multiplier bias (2×) | **BCX54** (NPN), thermally coupled to the output pair | sets/tracks the class-AB quiescent current (Iq ~20 mA). Small-signal BC847 also works but BCX54 best-matches the output V_BE tempco. |
| `R_vbm_t1/b1`, `R_vbm_t2/b2` | V_BE-multiplier dividers (4×) | 680 Ω / 1.0 kΩ, 1 %, 0805 | ratio 1.68 → ~2 V_BE per half → Iq ~20 mA |
| `R_bbo_ta/tb/ba/bb` | bias-chain current feed (4×) | 1.1 kΩ, 5 %, 0805 | feeds ~4 mA through the multipliers; bootstrapped via C_bbo |
| `R_o_bleed_n/p` | output-pair bleed (2×) | 5 kΩ, 5 %, 0805 | |
| `R_cs` | current-sense / series limit | 0.01–0.1 Ω (model 0.01) | low-value; a short PCB trace or 0.1 Ω 1 % is fine. (`R_series` 0.01 Ω likewise — cold-start current limit.) |
| **C_bbo_t, C_bbo_b** | bias-rail bootstrap (2×) | **4.7 µF — electrolytic / tantalum / film. *NOT* Y5V ceramic.** | ⚠ **See dielectric rule.** These are the only THD-critical caps. |

> **Cap dielectric rule (Y5V study):** every cap in the design may be
> cheap Y5V ceramic **except `C_bbo_t`/`C_bbo_b`** (the 4.7 µF bootstrap
> caps). If those collapse under Y5V's temperature/tolerance droop, the
> class-AB bias rail sags within the carrier cycle → crossover distortion
> (THD −55 → −22 dB at 85 °C). At 4.7 µF they'd naturally be electrolytic
> or tantalum anyway, so this is a "don't accidentally spec Y5V" note. All
> other caps: Y5V-safe (zero effect on regulation, stability, or THD).

**Why BCX54/BCX51 + a V_BE-multiplier bias:** SOT-89 1 A complementary pair
with **VCEO = 45 V** — on ±10 V rails the off-device sees ~17 V pk, giving
>2.5× margin (vs only ~15 % for BC868/869's 20 V, and far better than the
SOT-23 BC817/807). The class-AB bias **must** be a V_BE multiplier, not the
fixed diode string: with a fixed bias, a power output device's lower V_BE
over-conducts badly — the original 4-diode string drove Iq to **242 mA /
~1.9 W per device**. The V_BE multiplier (Q_vbm, thermally coupled) sets and
tracks Iq at ~20 mA → **~0.05–0.58 W/device** (worst ILC1-1/8), SOT-89-safe.
Verified 2026-06-04, all four tubes: regulation on target, +3–5 K startup
overshoot, THD −52 to −59 dB. (V_A/Early voltage is irrelevant here; the
BCX54 IKF = 0.45 A causes only mild rolloff at the ILC1-1/7 peak.)

> **⚠ PCB thermal — copper pour required on the output-device tabs.** SOT-89
> sheds heat through the collector tab into the PCB pad, so R_th(j-a) is
> copper-dependent (Nexperia BCX54): **250 K/W bare footprint → 132 K/W at a
> 1 cm² collector pad → 93 K/W at 6 cm²**; R_th(j-sp) = 16 K/W, Tj(max) 150 °C.
> The worst device is ILC1-1/8 at ~0.58 W/device, which **exceeds the 0.50 W
> bare-footprint rating** — on a bare pad Tj would blow past 150 °C. So pour
> **≥ 1 cm² copper** under the output-pair collector tabs (then Tj ≈ 101 °C @
> 25 °C / 126 °C @ 50 °C ambient — safe). ILC1-1/7 (~0.31 W) is OK on a bare
> footprint but give it a small pad for margin; IV-6/IV-18 are fine bare.
> Mount the two V_BE-multiplier transistors against the output tabs for thermal
> tracking. **(This requirement is driven by the uniform ±10 V rails; see the
> rail-scaling note — per-tube rails would relax it.)**

> **Rail-scaling option (per-tube `v_buf`).** The output dissipation above is
> driven by the uniform ±10 V rails: the low-voltage tubes swing far below the
> rail, so the linear class-AB stage burns the headroom. Per-tube rails recover
> it (verified 2026-06-04, all regulate):
>
> | tube | rail | P/device | Tj @ 50 °C bare | THD |
> |---|---|---|---|---|
> | ILC1-1/7 | ±10 V (needs it for 7 V drive) | 0.31 W | 128 °C | −56 dB |
> | ILC1-1/8 | **±5 V** (vs 0.58 W / 194 °C at ±10 V) | **0.23 W** | **107 °C** | −49 dB |
> | IV-6 | ±5 V | 0.08 W | 71 °C | −50 dB |
> | IV-18 | ±5 V | 0.02 W | 55 °C | −51 dB |
>
> At ±5 V the low-voltage tubes are **bare-footprint-safe (no copper pour
> needed)** and ~60 % cooler; THD degrades ~3 dB but stays well inside spec.
> Floor is ~±4.5 V (the integrator output reaches ~+3.5 V and needs rail
> headroom). Cost: a per-tube rail voltage (LM317/337 set per tube — the
> retired all-pass design did this). **Not yet implemented** — uniform ±10 V is
> the current `regulator.py` default; this documents the trade vs. the copper
> pour above.

---

## Gain chain (identical all tubes)

| element | value | type | function |
|---------|-------|------|----------|
| `R_atten_top` / `R_atten_bot` | per-tube ratio (sim 12 k / 1 k for a 0.1 V_rms model source; scale `R_atten_top` up — e.g. ~330 k — for the real ~2.5 V_rms Wien) | 1 % 0805 | sets carrier level into Stage 1 |
| `R_in_vgain` | 10 Ω | 1 % | Stage-1 input resistor |
| `R_max_s1` | 24 Ω | 1 % | bounds Stage-1 gain (∥ H11F) — also desensitizes H11F part spread |
| `R_fb_s2` / `R_gnd_s2` | 2.4 kΩ / 100 Ω | 1 % | Stage-2 gain G2 = 1 + 2400/100 = **25** (Fix A; do not restore 201) |
| `C_couple_buf` | 1 µF | X7R/film | AC-couple Stage 2 → buffer (Y5V-safe) |
| `R_bias_buf` | 16 kΩ | 1 % | buffer input bias |
| `R_fb_buf` / `R_in_buf` | 13 kΩ / 1 kΩ | 1 % | buffer gain (k_buf = 14) |

---

## Bridge sense, diff amp, demodulator, compensator, anti-windup

| block | elements | values | part / note |
|-------|----------|--------|-------------|
| Bridge buffers | `XU_buf_A`, `XU_buf_B` | — | 2 OPA4277 channels (high-Z taps of node_A / node_B) |
| Diff amp | `R_da_inA`,`R_da_inB`,`R_da_fb`,`R_da_gB` | 1 k, 1 k, 30 k, 30 k | K_diff = 30; 1 % thin-film (match the two 1 k and two 30 k) |
| **Sync demod** | `B_demod` (behavioural) | — | **hardware = chopper:** 1 ch of **CD74HC4053** analog switch + 1 stage of **SN74HC14** Schmitt to square up V_osc into a clean 0/+rail gate. Ron ≈ 100 Ω ≪ R_lp_demod 100 k → negligible error. |
| Demod LP | `R_lp_demod` / `C_lp_demod` | 100 kΩ / **0.22 µF** | **~7.2 Hz** post-demod LP — moved up from 1.6 Hz for phase margin (out of the loop-crossover region); still ~49 dB rejection at the 2 kHz demod ripple. C may be X7R (Y5V-safe) |
| Log demod | `XU_log`, `R_fb_log`, `R_gnd_log` | 10 kΩ / 526 Ω | K = 1 + 10k/526 ≈ **20, uniform all tubes**. (No Schottky clip — removed; the op-amp rails bound cold-start.) |
| PID integrator | `XU_int`, `R_intin`, `C_intin`, `C_intfb`, `R_pid`, `C_hf`, `R_int_p` | **300 k**, 1 nF, **330 nF (use for 318 nF)**, 1 MΩ, 1 nF, **300 k** | `R_int` raised 100 k→300 k (lower loop gain → phase margin). `C_intfb` = film/C0G preferred (value-stable for the dominant pole); `C_intin`/`C_hf` C0G. `R_int_pg` 1 GΩ is a model leak path — omit in hardware. (`R_bc` = R_int/20 = 15 k, anti-windup back-calc.) |
| Anti-windup | `R_diff1–4`, `R_bc`, `R_aw_out`, `D_aw_hi`, `D_aw_lo` | 100 k ×4, 5 k, 10 Ω, 2× clamp diode | back-calc unwind; clamp diodes = 1N4148 or BAT54 (low-V_F). |
| Clamp refs | `V_clamp_hi`, `V_clamp_lo` | +4.0 V, −0.5 V | resistor dividers off the rails, buffered by U3's 2 spare OPA4277 channels (or LM4040 shunt refs). Recommend wider [−3, +6] for headroom at corners/low-power tubes. |

---

## Source — Wien bridge oscillator (1 kHz)

The netlist abstracts the source as `B_src`; in hardware it is the
two-NPN symmetric-clamp Wien oscillator (`wien_oscillator.py`).

| element | value | part |
|---------|-------|------|
| `R1`, `R2` (frequency) | 10 kΩ, 1 % | f0 = 1/(2πRC) = 1 kHz |
| `C1`, `C2` (frequency) | 16 nF (15.9 nF), 5 % **C0G/NP0 or PP film** | frequency-setting — keep stable dielectric |
| gain net (Rfa/Rfb/Rg) | 10 k / 12 k / 10 k, 1 % | sets loop gain just > 3 |
| clamp transistors | 2× **MMBT3904** (SOT-23) | matched anti-parallel NPN amplitude clamp (kills H2) |
| base-bias dividers | 120 kΩ, 5 % | set clamp threshold (α = 0.5) |

> **Bench-check (flagged):** the matched-NPN clamp is clean (THD ~2.3 %,
> H2 killed, perfect PSRR) but its amplitude has a **−0.45 %/°C tempco**
> and the oscillation **dies above ~60 °C / at Rg +5 %** *in simulation*
> (model-dependent). This is the system's main temperature risk — verify
> on the bench and add tempco comp / AGC if the real part confirms it.

---

## Rails

| RefDes | function | part | notes |
|--------|----------|------|-------|
| +V rail | +10 V (sim `V_vcc`) | MC7810 / LM317-set | op-amp + buffer positive rail (±9 V works with slightly less headroom) |
| −V rail | −10 V (sim `V_vee`) | MC7910 / LM337-set | negative rail |
| +5 V | H11F LED supply (`V_led_supply`) | 78L05 / divider | feeds `R_led_set` |
| decoupling | 100 nF + 10 µF per rail per IC | X7R | (`R_sense_vcc/vee` 0.1 Ω in the netlist are model rail-sense elements, not real parts) |

---

## Cost summary (qty-1, per tube, approximate — verify live pricing)

| item | $/tube |
|------|--------|
| 3× OPA4277 quad (U1–U3) | ~6.0–9.0 |
| 1× H11F1M (U4) + R_led_set | ~0.9 |
| 6× BJT (BCX54/BCX51 ×2 output + 2× BCX54 V_BE-mult, SOT-89) | ~1.0 |
| 2× 4.7 µF bootstrap (tantalum/electrolytic) | ~0.3 |
| CD74HC4053 + SN74HC14 (chopper demod) | ~0.9 |
| Wien: 2× MMBT3904 + C0G/film freq caps + R | ~0.6 |
| anti-windup / clamp diodes (1N4148 / BAT54) | ~0.3 |
| 2× LDO (±10 V) + 78L05 + decoupling | ~1.4 |
| resistors (~40 × 1 % thin-film) | ~0.9 |
| capacitors (1× C_intfb film, ~10 ceramics) | ~1.0 |
| **Total** | **~$13–16** |

Comfortably inside the ~$20/tube target. OPA4277 quads are the biggest
line item; the OP07CDR single-pack fallback trades package count for a
slightly lower op-amp cost.

---

## Bench-check items (sim findings to confirm on hardware)

These are model-dependent; validate before committing to a production run:

1. **Wien amplitude tempco / >60 °C death cliff** (−0.45 %/°C in sim) —
   the system's main temperature weak point; the regulator loop itself is
   temperature-robust (integrator rejects device tempco).
2. **H11F R(I_LED) at the real operating point** — the SPICE model is an
   empirical fit to digitised datasheet curves (Fig 1/2 disagree; we follow
   Fig 2 for transient/DC). Confirm the real part's R at the ~4–14 mA
   operating range and that V_int lands clear of the clamps.
3. **Filament-R tolerance vs the constant-V history assumption** — confirm
   real filament spread is the assumed few-%; if wider, widen the clamp to
   [−3, +6] and/or select `R_topref` per measured cold filament R.
4. **Bridge-resistor grade** — 1 % gives ±3 % R_fil / +21 K T; drop to
   0.5 %/0.1 % only if tighter digit-to-digit T uniformity is wanted.
