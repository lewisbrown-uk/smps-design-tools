# BOM — VFD filament regulator (4 tubes, canonical design)

Real-part mapping for the **canonical `regulator.py` design** (H11F
variable-gain + BJT class-AB push-pull). Target ≤ $20/tube, **no
build-time trimming**, all parts stocked at DigiKey/Mouser. **This is a
surface-mount build** — every part is specified in its SMD package
(SOIC / SOT-23 / SOT-89 / SOD-323 / 0805); no through-hole.

Reference designators follow the `regulator_<tube>.cir` element names.

> **Reconciled against the canonical netlist 2026-06-12** (see `SCHEMATIC.md`
> §11). Shipping config = `switch_demod=True, overpower_protect=True`. This
> pass corrected BOM drift (removed `XU_log`; Stage-1 gain 40 Ω/140 Ω;
> `R_int` 50 kΩ / `R_bc` 2.5 kΩ; Wien α=0.30 / 168 k–72 k; op-amp count
> 3→4 quads) and folded in the locked productionisation decisions
> (**0.1 % bridge refs**, **protection ships**, **2-stage buffered
> attenuator**, **Wien on ±15 V NE5532**, clamp window [−3,+6]).
>
> A follow-on **E-series realisation pass (2026-06-12)** mapped non-standard
> design values to buildable parts: **E24 0.1 % bridge triplets** (hold R_fil
> exactly), `R_in_vgain` 40→40.2 Ω, `R_int` 50→49.9 kΩ, `R_bc` 2.5→2.49 kΩ,
> Wien bias 168 k/72 k→169 k/71.5 k, `R_o_bleed` 5 k→5.1 k.

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
bridge buffers → **commutating-switch synchronous demod** (CD4053B chopper
that differences the two buffered bridge nodes *and* chops them, gain
post-chop — no separate pre-demod diff amp) → LP → **log demod** → **PID
integrator** with back-calc anti-windup → drives the **H11F LED** (via
`R_led_set`, off a unity buffer `XU_led_buf` of v_int so LED current does
not flow through the anti-windup resistor), closing the loop. The H11F's
LED-current-controlled resistance sets Stage-1 gain → filament drive →
filament temperature, regulated against the bridge reference.

**Key simplification vs the old all-pass design — only FIVE small things vary
per tube:** the three bridge-reference resistors, the attenuator Stage-B leg
(`R_atten_top`, the oscillator-drive knob), and IV-18's `R_in_vgain`. The
op-amps, output stage, Stage-2 gain, compensator, LED drive, attenuator
Stage A, and rails are **identical across all four tubes.** (`R_op`/`V_op`/
`T_op` in the netlist are *filament physical properties* used to calibrate
the thermal model — not parts to buy.)

---

## Per-tube variants (the per-tube parts — FIVE items)

| element     | IV-18 | IV-6 | ILC1-1/7 | ILC1-1/8 | notes |
|-------------|-------|------|----------|----------|-------|
| `R_topref`  | 1 kΩ  | 2 kΩ | 3.3 kΩ   | 1.2 kΩ   | bridge top ref; **0.1 % thin-film 0805**, **E24 value** |
| `R_botref`  | 100 Ω | 510 Ω| 620 Ω    | 300 Ω    | bridge bottom ref; **0.1 % thin-film**, E24 |
| `R_sense`   | 10 Ω  | 5.1 Ω| 4.7 Ω    | 2 Ω      | bridge sense leg, in series with the filament (carries the load current); **0.1 %**, E24. Per-element dissipation: **ILC1-1/7 ~156 mW → ½ W part**; ILC1-1/8 ~45 mW → ¼ W (0805 marginal); IV-6 ~12 mW and IV-18 ~1 mW → plain 0805. |
| `R_atten_top` (Stage B) | 57.6 kΩ | 34.0 kΩ | 6.65 kΩ | 28.7 kΩ | attenuator Stage-B leg (1 %), off the ÷50 buffered node — sets the per-tube carrier. Stage A (49.9 k/1 k) + buffer are common to all tubes. See "Source". |
| `R_in_vgain` | **28 Ω** | 40.2 Ω | 40.2 Ω | 40.2 Ω | Stage-1 input resistor — **IV-18 only differs** (1 %, E96). |
| target R_fil | 100 Ω | 20 Ω | 25 Ω | 8 Ω | = R_sense·R_topref/R_botref (held by the loop) |

(The five per-tube items: 3 bridge refs + `R_atten_top` + IV-18's `R_in_vgain`.
The earlier "only four things vary" was wrong for IV-18.)

**Bridge sets the regulated point:** `R_fil = R_sense · R_topref / R_botref`.
**Shipping grade: 0.1 % thin-film on all three bridge resistors** (locked
2026-06-11) — the only lever on T uniformity. This shaves ~±16 K off the
worst-case brightness envelope vs 1 % (1 % gave ±3 % R_fil / +21 K, 8-corner).
**Caps and every other resistor are irrelevant to R_fil/T.**

**Values are E24 (0.1 %)**, chosen (brute-force E-series search, 2026-06-12) to
hold each tube's R_fil exactly: IV-6 / IV-18 / ILC1-1/8 land **dead-on**;
ILC1-1/7 is **+0.43 K** — a fixed nominal offset, swamped by the tube's own
±5 % filament spread (±~33 K). 0.1 % thin-film is stocked in E24 values
(Susumu RG, Panasonic ERA, Vishay TNPW), so these are round, common parts at
full precision. The triplets **preserve R_fil (hence T) and the loop transfer
exactly**; only the reference-arm absolute impedance shifts a few % (IV-18 and
ILC1-1/8 keep the same divider ratio; ILC1-1/7 / IV-6 shift ≤5 %). These
supersede the netlist's design-round values (5 k/1 k etc.) — **re-run the
validation battery on the final values to confirm** (the regulated point is
unchanged, so this is a confirmation, not a redesign).
Filament-R part variation maps as `T ≈ T_op·(R_actual/R_nominal)^(1/1.2)`;
the constant-voltage mains-winding history bounds real filament spread to
a few %, well inside loop authority (no binning needed).

**Oscillator level per tube:** one fixed-amplitude Wien (3.63 V_pk / 2.57 V_rms
@ 25 °C, see "Source") feeds a **2-stage buffered divider** — a common ÷50
first stage (49.9 k/1 k) + unity buffer, then a per-tube Stage-B leg
`R_atten_top` (table above) off the buffered ~72 mV_pk node. The sim abstracts
this as `V_src_rms` = 0.0115 / 0.019 / 0.088 / 0.0224 (IV-18 / IV-6 / ILC1-1/7
/ ILC1-1/8); in hardware it is the Stage-B resistor — a build-time *selection*,
not a trim. The 2-stage scheme keeps every resistor mid-decade (a single
divider would need MΩ legs that load the oscillator).

---

## Op-amps — 4 × OPA4277 quad + comparators + 1 NE5532 (Wien)

The **13 OPA4277 channels** of the *shipping* design (`switch_demod=True`,
`overpower_protect=True`) fill **4 quad packages** (16 channels, 3 spare).
Quad packaging is verified safe here (see "Coupling"). The Wien oscillator is
a **separate NE5532** on ±15 V (see "Source") — it is **not** an OPA4277
channel. (Supersedes the earlier 3-quad count, which predated protection and
still counted the removed `XU_log`.)

| pkg | channels (netlist) | function |
|-----|--------------------|----------|
| **U1 (OPA4277)** | `XU_atten_buf1`, `XU_atten_buf`, `XU_vgain`, `XU_s2` | 2-stage attenuator buffers (×2) + H11F Stage-1 + Stage-2 gain |
| **U2 (OPA4277)** | `XU_buf`, `XU_buf_A`, `XU_buf_B`, `XU_demod_da` | class-AB driver + two bridge buffers + post-chop demod difference amp |
| **U3 (OPA4277)** | `XU_int`, `XU_aw_diff`, `XU_led_buf`, +1 spare | PID integrator + anti-windup diff amp + H11F-LED unity buffer; spare for a V_clamp buffer |
| **U9 (OPA4277)** | `XA1op`, `XA2op`, +2 spare | over-power precision full-wave rectifier (protection) |
| **U5 (comparators)** | `XU_demod_comp` + supervisor LOW/HIGH + over-power window | **LM339** quad (or LM393 + singles): demod chopper gate (squares v_osc) **and** the protection window comparators. (Modeled as open-loop op-amps in sim.) |
| **U7 (logic)** | demod complementary gate (+ supervisor logic) | **SN74HC14** inverter. |

Topology note: the old single-op-amp **diff amp** (`XU_da`) is gone — the
commutating-switch demod differences the bridge nodes directly. Changes since
the original 3-quad BOM: **−`XU_log`** (the ×20 log-demod stage, removed by the
pre-log-sensing fix — the integrator now senses the demod node directly),
**+`XU_atten_buf1`** (the 2-stage divider's inter-stage buffer), **+`XA1op`/
`XA2op`** (over-power FWR, now that protection ships). V_clamp refs: use
**LM4040 shunt refs** for the **[−3 V, +6 V]** window (adopted, wider than the
sim −0.5/+4.0 for corner / low-power-tube headroom).

- **OPA4277UA** (SOIC-14).
  Precision bipolar, OP07-class: Vos ~10 µV typ (~50 µV max), drift
  ±0.1 µV/°C, **GBW 1 MHz**, A_OL 134 dB, CMRR ~140 dB, **PSRR ~130 dB**,
  channel separation **±1 µV/V**, BJT class-AB output (no LM358 crossover).
- **Why OPA4277 (low Vos, not bandwidth):** the load-bearing requirement is
  **low Vos** (≤~150 µV) — a 2–5 mV jellybean loses 30–100 K and ~25 dB THD.
  **GBW is *not* critical:** Suite G1 (2026-06-10, pre-log design) swept
  0.5 / 1 / 3 / 10 MHz with **zero hunting** and THD **flat-to-improving**
  (IV-18 −49.8→−59.0 dB, IV-6 −43.3→−50.8, ILC1-1/8 −42.3→−52.2, ILC1-1/7 flat
  at −34.7 dB across the range). So faster parts are **safe**, and a
  higher-GBW / higher-slew op-amp is the lever if the carrier is ever raised
  (see frequency-headroom note). OPA4277 (1 MHz, ~50 µV Vos, quad) is chosen
  for low Vos + cost, not for its bandwidth. **(Supersedes the earlier
  "≥3 MHz degrades THD + hunts" finding, which was the pre-pre-log
  architecture — the pre-log-sensing + differencing-in-demod rework removed
  the hunt mechanism; Suite G1 was the re-check.)**
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
`R_max_s1 = 140 Ω` swamps it (the spec-max 2× R part is bit-identical to
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
| `R_o_bleed_n/p` | output-pair bleed (2×) | 5.1 kΩ, 5 %, 0805 | |
| `R_cs` | current-sense / series limit | 0.01–0.1 Ω (model 0.01) | low-value; a short PCB trace or 0.1 Ω 1 % is fine. (`R_series` 0.01 Ω likewise — cold-start current limit.) |
| **C_bbo_t, C_bbo_b** | bias-rail bootstrap (2×) | **4.7 µF — low-ESR tantalum / film (NOT Y5V; NOT high-ESR aluminium electrolytic).** | ⚠ **See dielectric rule.** The only THD-critical caps; ESR adds to the bias-rail droop. |

> **Cap dielectric rule (Y5V study):** every cap in the design may be
> cheap Y5V ceramic **except `C_bbo_t`/`C_bbo_b`** (the 4.7 µF bootstrap
> caps). If those collapse under Y5V's temperature/tolerance droop, the
> class-AB bias rail sags within the carrier cycle → crossover distortion
> (THD −55 → −22 dB at 85 °C). At 4.7 µF they'd naturally be electrolytic
> or tantalum anyway, so this is a "don't accidentally spec Y5V" note.
>
> **"Y5V-safe" covers regulation/stability/THD only — NOT ESR, DC-bias
> derating, or acoustics (added 2026-06-12):**
> - **DC-bias derating:** Class-2 MLCCs (X7R/Y5V) lose 30–60 % of C under DC
>   bias — far beyond the ±10 % the Monte Carlo swept. The live concern is the
>   **rail decoupling** (10 µF at ±10/15 V — size from the *derated* value). The
>   **protection RC qualifier caps** (`C_hiq` etc., 3 s/7 ms times) were also a
>   suspect, but the cap-derate FMEA (`cap_derate_fmea.md`) shows they survive
>   ≥40 % derating with **no false-trip → standard X7R is fine there**. The
>   value-critical loop caps (`C_intfb`, Wien `C1/C2`, `C_intin/hf`) are already
>   C0G/film → immune.
> - **ESR:** matters for `C_bbo` (adds to the bias droop → low-ESR tant/film)
>   and the bulk decoupling (MLCC mΩ is fine once C is sized from derated value).
> - **Acoustic (electrostriction):** Class-2 caps *sing* at 2 kHz (worst on the
>   ILC1-1/7 output-stage decoupling carrying carrier ripple). Y5V is the worst
>   singer — use X7R-or-better (ideally C0G / low-acoustic soft-termination) on
>   any cap with carrier-frequency AC across it. See the acoustics note.
> - Neither ESR nor DC-bias derating was in the sim (ideal caps, ideal rails;
>   MC = ±10 % tolerance only).

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
| attenuator (2-stage buffered) | Stage A 49.9 k / 1 k (÷50, all tubes) → buffer → Stage B `R_atten_top` per-tube (§per-tube table) / `R_atten_bot` 1 k | 1 % 0805 | sets carrier level into Stage 1 (see "Source") |
| `R_in_vgain` | **40.2 Ω** (28 Ω IV-18) | 1 % | Stage-1 input resistor (E96) |
| `R_max_s1` | **140 Ω** | 1 % | bounds Stage-1 gain (∥ H11F) — also desensitizes H11F part spread |
| `R_fb_s2` / `R_gnd_s2` | 2.4 kΩ / 100 Ω | 1 % | Stage-2 gain G2 = 1 + 2400/100 = **25** (Fix A; do not restore 201) |
| `C_couple_buf` | 1 µF | X7R/film | AC-couple Stage 2 → buffer (Y5V-safe) |
| `R_bias_buf` | 16 kΩ | 1 % | buffer input bias |
| `R_fb_buf` / `R_in_buf` | 13 kΩ / 1 kΩ | 1 % | buffer gain (k_buf = 14) |

---

## Bridge sense, demodulator, compensator, anti-windup

| block | elements | values | part / note |
|-------|----------|--------|-------------|
| Bridge buffers | `XU_buf_A`, `XU_buf_B` | — | 2 OPA4277 channels (high-Z taps of node_A / node_B) |
| **Sync demod (chopper)** | `XU_demod_comp`, `S_dp1/2`, `S_dm1/2` | — | **Commutating analog-switch demod** (no separate pre-demod diff amp). A complementary SPDT pair — **CD4053B** (±5 V bipolar, takes the ±1.45 V worst-case bridge-tap directly; **not 74HC4053**, which is 6 V-class/marginal; premium = DG419/ADG419 ±15 V, lower charge injection on ilc11_7) — swaps `node_A_buf`/`node_B_buf` onto the +/− lines on alternate half-cycles. Gate = comparator `XU_demod_comp` (**LM393**/TLV3201) squaring v_osc. SPDT complement gate from a logic inverter (e.g. SN74HC14). Charge injection (~1–20 pC) is a small DC offset the loop absorbs. |
| Post-chop diff amp | `XU_demod_da`, `R_dda_inp/inm`, `R_dda_g1/g2`, `R_dda_fb` | 1 k, 1 k, **15 k + 15 k**, 30 k | Gain = R_dda_fb/R_dda_in = K_diff = **30**; balanced (R_dda_g = R_dda_fb). **R_dda_g is split into two series 15 k halves** so a single-resistor SHORT leaves 15 k to ground (diff-amp keeps rejection) instead of 0 (single-ended → +23 K silent overheat). Closes the one residual demod-component fault (FMEA). 1 % thin-film, match the pairs. Switch R_on (~60–300 Ω) is common-mode (both arms) → negligible; raise R_dda_in to 10 k (R_dda_fb 300 k) for extra margin if desired. |
| Demod LP | `R_lp_demod` / `C_lp_demod` | 100 kΩ / **0.22 µF** | **~7.2 Hz** post-demod LP — moved up from 1.6 Hz for phase margin (out of the loop-crossover region); still ~49 dB rejection at the 2 kHz demod ripple. C may be X7R (Y5V-safe) |
| ~~Log demod~~ (**REMOVED**) | — | — | The ×20 `XU_log` stage is **gone** (pre-log-sensing fix): the integrator senses the demod LP node directly, its gain folded into `R_int`. Frees one op-amp channel. |
| PID integrator | `XU_int`, `R_intin`/`R_int_p`, `C_intin`, `C_intfb`, `R_pid`, `C_hf` | **49.9 kΩ**, 1 nF, **330 nF (for 318 nF)**, 1 MΩ, 1 nF | **`R_int` = 49.9 kΩ** (E96, for the 50 kΩ design value): the pre-log-sensing fix folded the removed ×20 log stage's gain into `R_int` (1 MΩ → 50 kΩ, identical small-signal loop transfer). `C_intfb` = film/C0G (value-stable dominant pole); `C_intin`/`C_hf` C0G. `R_int_pg` 1 GΩ is a model leak — omit in hardware. |
| Anti-windup | `R_diff1–4`, `R_bc`, `R_aw_out`, `D_aw_hi`, `D_aw_lo` | 100 k ×4, **2.49 k**, 10 Ω, 2× clamp diode | back-calc unwind (`R_bc` = R_int/20 → **2.49 kΩ** E96); clamp diodes = BAT54 (low-V_F) or 1N4148. |
| Clamp refs | `V_clamp_hi`, `V_clamp_lo` | **+6.0 V, −3.0 V** (adopted) | **LM4040 shunt refs** for the wider [−3, +6] window (corner / low-power headroom). (Sim used −0.5/+4.0.) |

---

## Source — Wien bridge oscillator (1 kHz)

The netlist abstracts the source as `B_src`; in hardware it is the op-amp
Wien-bridge oscillator with a **two-NPN symmetric amplitude clamp**
(`wien_bridge_biased.cir`). **Ships exactly as that netlist** (no retune):
op-amp `XU1` = **NE5532 on ±15 V**, clamp bias **169 k/71.5 k** (E96, for the
tuned 168 k/72 k — ratio within 1.3 %, α≈0.30 preserved).
Steady output **3.63 V_pk / 2.57 V_rms @ 25 °C** (measured) → feeds the
2-stage buffered attenuator (see "Per-tube variants" / "Gain chain").

| element | value | part |
|---------|-------|------|
| `XU1` (amplifier) | **±15 V rails** | **NE5532** (dual, 1 ch) — the ONLY ±15 V part; α=0.30 clamp bias was tuned here, so ±15 V avoids a retune |
| `R1`, `R2` (frequency) | 10 kΩ, 1 % | f0 = 1/(2πRC) = 1 kHz |
| `C1`, `C2` (frequency) | 16 nF (15.9 nF), 5 % **C0G/NP0 or PP film** | frequency-setting — keep stable dielectric |
| gain net (Rfa/Rfb/Rg) | 10 k / 12 k / 10 k, 1 % | sets loop gain just > 3 |
| clamp transistors | 2× **MMBT3904** (SOT-23) | matched anti-parallel NPN amplitude clamp (kills H2) |
| base-bias dividers | **169 k / 71.5 k**, 1 % (E96) | set clamp threshold (**α ≈ 0.30**, the THD-min from `sweep_wien_bias.py`; E96 nearest the tuned 168 k/72 k, ratio within 1.3 %) |

> **Bench-check (flagged):** the matched-NPN clamp is clean (THD ~2.3 %,
> H2 killed, perfect PSRR) but its amplitude has a **−0.45 %/°C tempco**
> and the oscillation **dies above ~60 °C / at Rg +5 %** *in simulation*
> (model-dependent). This is the system's main temperature risk — verify
> on the bench and add tempco comp / AGC if the real part confirms it.

---

## Rails

| RefDes | function | part | notes |
|--------|----------|------|-------|
| ±15 V | **Wien NE5532 rail + master** | raw supply / LM317+LM337 | the board's master rail: feeds the Wien op-amp directly; the ±10 V rails derive from it |
| +V rail | +10 V (sim `V_vcc`) | MC7810 / LM317-set (from +15) | op-amp + buffer positive rail (±9 V works with slightly less headroom) |
| −V rail | −10 V (sim `V_vee`) | MC7910 / LM337-set (from −15) | negative rail |
| +5 V | H11F LED supply (`V_led_supply`) | 78L05 / divider | feeds `R_led_set` |
| decoupling | 100 nF + 10 µF per rail per IC | X7R — **size from bias-derated C** (X7R loses 30–60 % at ±10/15 V); low-ESR; X7R-or-better (not Y5V) for acoustic | (`R_sense_vcc/vee` 0.1 Ω in the netlist are model rail-sense elements, not real parts) |

---

## Protection (SHIPS — `overpower_protect=True`)

Over-temp protection is **part of the production design** (decision 2026-06-11;
worst fault excursion **≤922 K** (IV-6/ILC1-1/8 botref_short & topref_open;
three tubes cross 900 K), bounded by the clamp floor ~1030 K, then cold-safe;
zero false trips. *(The "≤899 K / never 900 K" figure was IV-18-only; the
full-battery worst is 922 K — see `cap_derate_fmea.md` / OVERNIGHT §FMEA.)*
Full net-by-net schematic in `SCHEMATIC.md` §8. Parts + **locked values**:

| block | part | locked value |
|-------|------|--------------|
| flat drive clamp | **TLV431** active shunt (per-tube ref) on `v_osc_drive` | `k_clamp` = 1.5 → ±`V_cl` |
| over-power sense | precision FWR: 2× OPA4277 ch (U9) + Schottkys + RC envelope | trip at `k_overpower` = 1.3 ×V_op |
| V_int supervisor | LM339 window comparators + RC qualifiers + diode-cap latch | arm 1.5 V / low-trip 0.5 V (1 ms) / high-trip 3.7 V (3 s) |
| RC qualifier caps | `C_hiq`/`C_loq`/`C_arm`/`C_lat`/`C_envop` (1 µF / 0.1 µF) | **Standard X7R OK** — the cap-derate FMEA (`cap_derate_fmea.md`) shows no false-trip + all faults caught down to 40 % derating (3 s/7 ms times have ~2.5× margin). |
| disconnect | **latching relay** (replaces `R_series`) + coil driver | `t_relay` = 7 ms — **re-confirm vs the chosen relay's datasheet** |
| osc cutoff + fault LED | transistor gating the Wien + indicator | — |

Clamp + disconnect compound (clamp caps the peak rate, disconnect caps the
dwell). The TLV431 per-tube `V_cl` resistor and the relay choice are the two
items to finalise at PCB time.

---

## Cost summary (qty-1, per tube, approximate — verify live pricing)

| item | $/tube |
|------|--------|
| **4× OPA4277 quad (U1–U3, U9)** | ~8.0–12.0 |
| **1× NE5532 (Wien op-amp)** | ~0.4 |
| 1× H11F1M (U4) + R_led_set | ~0.9 |
| 6× BJT (BCX54/BCX51 ×2 output + 2× BCX54 V_BE-mult, SOT-89) | ~1.0 |
| 2× 4.7 µF bootstrap (tantalum/electrolytic) | ~0.3 |
| CD4053B + LM339 comparators + SN74HC14 inverter (chopper demod + protection) | ~1.2 |
| Wien: 2× MMBT3904 + C0G/film freq caps + R | ~0.6 |
| **protection: TLV431 flat-clamp + latching relay + LM4040 refs + FWR Schottkys** | ~2.5 |
| anti-windup / clamp diodes (1N4148 / BAT54) | ~0.3 |
| **3× LDO (±15→±10) + 78L05 + decoupling** | ~1.8 |
| resistors (~50 × 1 %/0.1 % thin-film) | ~1.2 |
| capacitors (1× C_intfb film, ~12 ceramics) | ~1.1 |
| **Total** | **~$19–23** |

The added quad (protection FWR + divider buffer), the NE5532 Wien, and the
**protection chain** (now shipping) plus 0.1 % bridge refs push this to the
edge of the ~$20/tube target. The rail-scaling option (per-tube ±5 V on the
low-V tubes, BOM §output stage) and the OP07CDR single-pack fallback are the
levers if it must come down. OPA4277 quads remain the biggest
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
