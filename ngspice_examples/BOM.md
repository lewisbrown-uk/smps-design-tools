# BOM — VFD filament regulator (4 tubes)

Real-part mapping for every netlist element. Target ≤ $20/tube, no
build-time trimming, available at DigiKey and Mouser. All footprints
are SMD where convenient (SOT-23 / SOIC) but every part also exists
in a through-hole equivalent for forum builders who prefer it.

Reference designators follow the `regulator_<tube>.cir` names.

## Decisions about the simulation that affect the BOM

**Op-amp current limit.** The macromodel `uopamp_lvl2` is run with
`Ilimit = 1 A` because its internal V9/V10 cancellation breaks below
~545 mA (see CAVEAT comment in `uopamp.lib`). This is a *modelling*
choice, not a real circuit parameter. The chosen real parts have
short-circuit currents of **65 mA (TLV9154)** and **50 mA (OPA2188)**,
both spec'd typ at +25 °C. The heaviest op-amp load in the circuit is
`XU_osc` driving the 10 k Wien return at peak — ~1.4 mA pk — and the
buffer op-amps drive only gate-damping R (~1 mA pk). Real Isc is
well above the design requirement, so no op-amp will ever current-limit
in operation.

**PSU rail PWL.** The model defaults to instantaneous rails (`t_rail_ramp=0`).
Real LDOs ramp ±9 V over ~1–10 ms as the output cap charges through
finite-current loop bandwidth; this **does not affect the regulator
loop's steady-state behaviour** (the loop integrator settles in 100 ms
to 5 s depending on tube, far longer than any rail ramp). The rail PWL
is left disabled in production simulations because it would only mask
the MOSFET-edge artefact at cold-start, which is already managed by
using the LEVEL 1 placeholder model in routine sweeps. A real ±9 V
LDO (LM7809 / LM7909 or LM317-style adjustable, see "Rails" below)
will ramp adequately on its own.

---

## Common components (all 4 tubes identical)

| RefDes | Function (netlist element)                               | Part Number      | Mfr             | Pkg     | DigiKey            | Mouser              | Qty | Unit ($) | Notes |
|--------|----------------------------------------------------------|------------------|-----------------|---------|--------------------|---------------------|-----|----------|-------|
| **U1** | Std op-amp quad (`XU_osc`, `XU_ap`, `XU_diff`, `XU_inv`) | TLV9154IDR       | Texas Instr.    | SOIC-14 | 296-TLV9154IDR-ND  | 595-TLV9154IDR      | 1   | 2.05     | 4.5 V…40 V, GBW=4.5 MHz, Vos=2.5 mV max, Isc=65 mA typ. Through-hole: TLV9154IP (PDIP-14, $2.25). |
| **U2** | Std op-amp quad (`XU_buf0`, `XU_buf_osc`, `XU_buf_ap`, `XU_aw_diff`) | TLV9154IDR       | Texas Instr.    | SOIC-14 | 296-TLV9154IDR-ND  | 595-TLV9154IDR      | 1   | 2.05     | Second quad — see U1. |
| **U3** | Chopper op-amp dual (`XU_dem`, `XU_int`)                 | OPA2188AIDR      | Texas Instr.    | SOIC-8  | 296-27751-1-ND     | 595-OPA2188AIDR     | 1   | 3.36     | 25 µV Vos typ / 75 µV max; chopper. Sets demod & integrator residual T error to <5 K. Alt: LMP2022MA (~$3.80) if substitution preferred. |
| **U4** | Sync demod analog switch (`S1`, `S2`)                    | CD74HC4053M96    | Texas Instr.    | SOIC-16 | 296-14532-1-ND     | 595-CD74HC4053M96   | 1   | 0.54     | Triple SPDT, Ron≈100 Ω at ±5 V. Routes vplus = (V_osc>0 ? n_diff : 0) using one of the three channels. VDD=+9 V / VSS=0 / VEE=−9 V split-rail. Logic threshold ref'd VSS..VDD — see U5. (Plain `CD74HC4053M` is obsolete; M96 is the active T&R-packaged successor — same die.) |
| **U5** | Comparator level shifter for U4 control                  | SN74HC14DR       | TI              | SOIC-14 | 296-1199-5-ND      | 595-SN74HC14DR      | 1   | 0.40     | Hex Schmitt-trigger. V_osc (±3 V) → R + clamp to 0…+9 V → one HC14 stage → CMOS-clean 0/+9 V drive into U4 control pin. `XU_cmp` in the netlist is collapsed onto this part. (Plain `SN74HC14D` is obsolete; DR is the cut-tape successor.) |
| **Q1, Q2** | Wien BJT amplitude clamp                             | MMBT3904 (or BC847) | Multi (Nexperia, onsemi) | SOT-23 | MMBT3904FSCT-ND | 771-MMBT3904 | 2 | 0.06 | Through-hole: 2N3904 (TO-92). |
| **M_var1, M_var2** | All-pass variable resistor (back-to-back NMOS, `XM_var1`/`XM_var2`) | DMN3404L-7   | Diodes Inc. | SOT-23  | DMN3404L-7DICT-ND | 621-DMN3404L-7    | 2   | 0.35 ea  | Two NMOS in series, sources tied at `n_var_mid`, gates tied to `V_ctl = V_int_out + V_offset` (see V_offset_ref entry below). With V_offset = +2.0 V, V_int_out = 0 puts V_GS into weak triode (R_DS ~6 Ω/FET, |1-H| ~0.15), giving small cold-start drive while still developing a usable bridge signal for the loop to engage. V_int_out_OP is slightly negative (~-0.3 V for ILC1-1/7); the loop modulates V_int_out around 0 to set R_DS. Same part as the bridge driver. |
| **R_var_mid_bias** | Midpoint DC bias for back-to-back NMOS         | 1 MΩ             | —               | 0805    | (generic)          | (generic)           | 1   | 0.01     | Ties `n_var_mid` (the NMOS source-tie node) to GND so the back-to-back pair is symmetric. 1 MΩ is high enough that the signal path (channel R ~200 Ω total at OP) is unaffected, low enough to overpower stochastic body-diode leakage between the two devices. |
| **V_offset_ref**   | DC reference for variable-R gate level-shift   | +2.0 V (TL431, programmed via 1:1 R divider; or LM4040DCM3-2.0) | Texas Instruments / Microchip | SOT-23 / SOT-23-3 | (TL431ACDBZR-ND, ~$0.10; LM4040DCM3-2.0 ~$0.50) | — | 1 | 0.10 | Sets the gate-drive level shift so the NMOS pair is partially on at V_int_out = 0 (cold start ≈ 2.5% of P_OP). DC accuracy is not critical: the closed loop compensates for V_offset drift by shifting V_int_out_OP; T_op is unaffected. TL431 with programming-resistor 1:1 divider is the cheapest option. |
| **D1–D6** | Anti-windup + buffer bias diodes (`D_aw_hi/lo`, `D_obb_*`, `D_abb_*`) | 1N4148WS | onsemi / Diodes Inc. | SOD-323 | 1N4148WS-FDICT-ND | 621-1N4148WS-F | 6 | 0.10 | Through-hole: 1N4148 (DO-35). |
| Y1     | None — Wien sets f0=1 kHz via R/C (no crystal)            | —                | —               | —       | —                  | —                   | —   | —        | — |

Resistors and capacitors (common):

| RefDes group | Function                              | Value     | Tolerance | Pkg / type            | DigiKey example         | Per-unit ($) |
|--------------|---------------------------------------|-----------|-----------|-----------------------|--------------------------|--------------|
| R1, R2       | Wien R                                | 10 kΩ     | 1 %       | 0805 thin-film        | RMCF0805FT10K0CT-ND      | 0.02         |
| Rg, Rfa, Rfb | Wien gain net                         | 10k/10k/12k | 1 %     | 0805                  | (generic)                | 0.02 ea      |
| Rtop1…Rbot2  | Wien BJT clamp base bias              | 120 kΩ    | 5 %       | 0805                  | (generic)                | 0.01 ea      |
| R_ap1, R_ap2 | All-pass legs (eq R for matching)     | 1.59 kΩ   | 1 %       | 0805                  | (generic)                | 0.02 ea      |
| R_a1–R_b2    | Diff-amp matched-1Meg quad            | 1 MΩ      | **0.1 %** | 0805 thin-film, TC50  | RNCP0805FTD1M00CT-ND     | 0.08 ea      |
| R_bias       | Demod bias pull-down                  | 1 MΩ      | 1 %       | 0805                  | (generic)                | 0.02         |
| R_din, R_dfb | Demod integrating R                   | 10 kΩ     | 1 %       | 0805                  | (generic)                | 0.02 ea      |
| R_intin      | Integrator input R                    | 30 kΩ × scale | 1 % | 0805                  | (generic)                | 0.02         |
| R_intfb      | Integrator feedback R                 | 300 kΩ × scale | 1 % | 0805                | (generic)                | 0.02         |
| R_inv1, R_inv2 | Inverter (G=−1) matched pair        | 100 kΩ    | 0.1 % matched | 0805 thin-film     | (generic)                | 0.05 ea      |
| R_btd, R_bts, R_btp | Bias-T to v_ctl                | 100 k / 100 k / 18 k | 1 % | 0805            | (generic)                | 0.02 ea      |
| R_atten_top, _bot | V_osc divider into Buffer 0     | 56 kΩ / 9.1 kΩ | 1 %  | 0805                  | (generic)                | 0.02 ea      |
| R_gd_*       | MOSFET gate damping (IV-3/-6/ILC1-1/8) | 1 kΩ     | 5 %       | 0805                  | (generic)                | 0.01 ea      |
| C1, C2       | Wien C (f0 = 1 kHz)                   | 16 nF     | 5 % NP0/C0G | 1206 or PP film 5 mm | 1276-CL31C163JBFNNNECT-ND | 0.20 ea      |
| C_ap         | All-pass cap                          | **1 µF**  | 5 % PP film | WIMA FKP2 (5 mm)    | 495-1338-ND              | 0.45         |
| C_intin      | Demod high-freq bypass                | 1 nF      | 5 % C0G   | 0805                  | (generic)                | 0.10         |
| C_intfb      | Integrator pole-set                   | 318 nF (use 330 nF) | 5 % PP film | WIMA MKS2 5 mm | 495-1268-ND               | 0.25         |
| C_pid (C_hf) | Loop HF zero                          | 10 nF     | 5 % C0G   | 0805                  | (generic)                | 0.10         |
| C_btd, C_bts | Bias-T DC blocking to V_ctl           | 10 µF     | ±20 % X7R | 1210 ceramic 25 V     | (generic)                | 0.20 ea      |
| C_buf2_dcblock | DC block on V_ap into Buffer 2       | 10 µF (or 100 nF for ILC1-1/7) | X7R | 1210 | (generic)         | 0.15         |
| C_psu        | ±9 V supply decoupling                | 100 nF + 10 µF per rail per IC | X7R | 0805 + 1210 | (generic)        | 0.15 / set   |

Voltage references (anti-windup):

| RefDes | Function                  | Part       | Notes |
|--------|---------------------------|------------|-------|
| V_clamp_hi (+6 V) | Anti-windup high rail (transient safety; rarely engages because V_int_out_OP is negative) | Resistor divider off +9 V (e.g. 30k:60k) buffered by 1× spare TLV9154 channel | OR use LM4040-6.0 shunt ref (DigiKey: LM4040DEM3-6.0+T) $0.95. Spare op-amp is cheaper. |
| V_clamp_lo (−0.7 V) | Anti-windup low rail (engages during cold-start, gives V_int_out floor ≈ −1.0 V with Schottky V_F=0.3 V) | Resistor divider off −9 V (e.g. 33k:267k) buffered by 1× spare TLV9154 channel | Precision not critical — anti-windup back-calc unwinds the integrator quickly once the lower diode engages. |

PSU rails (±9 V regulators — 1 set common to all tubes):

| RefDes | Function | Part | Pkg | DigiKey | Notes |
|--------|----------|------|-----|---------|-------|
| U6 | +9 V LDO | MC78L09ACPRPG | TO-92 | MC78L09ACPRPGOSCT-ND ($0.40) | 100 mA, drops the unregulated +12-15 V rail to clean +9 V. Or LM317 + R-set if you already have higher input voltage. |
| U7 | −9 V LDO | MC79L09ACPRPG | TO-92 | MC79L09ACPRPGOSCT-ND ($0.45) | 100 mA. Or LM337-adj. |
| C_psu_in, C_psu_out | Reg I/O caps | 1 µF X7R / 10 µF X7R | 1210 | (generic) | 0.15 ea |

(Builders without dual unregulated rails: a single +12 V wall-wart through a TL431-referenced charge-pump inverter generates the −9 V; see forum writeup.)

---

## Per-tube variants

These six items change per tube. Everything else above is identical.

| RefDes      | IV-3            | IV-6            | ILC1-1/7        | ILC1-1/8        | Notes |
|-------------|-----------------|-----------------|-----------------|-----------------|-------|
| `R_top_ref` | 1 kΩ            | 2 kΩ            | 5 kΩ            | 800 Ω           | 1 % thin-film 0805. Sets bridge ratio = R_op. |
| `R_bot_ref` | 100 Ω           | 500 Ω           | 1 kΩ            | 200 Ω           | 1 % thin-film 0805. |
| `R_sen`     | 10 Ω, ¼ W       | 5 Ω, ¼ W        | 5 Ω, ½ W (1 W RMS) | 2 Ω, ¼ W      | 1 % wirewound or 1206 thick-film bulk-metal. ILC1-1/7 dissipates ~1 W RMS — use Vishay PR01 ½ W or larger. DigiKey: PR01000200000JR500-ND ($0.35). |
| `R_buf1_fb` & `R_buf2_fb` (or `_fb1`) | 1.6 kΩ | 2 kΩ | **13 kΩ** | 2.5 kΩ | 1 % thin-film 0805. Sets K_buf (buffer voltage gain). |
| `Vcc_buf` / `Vee_buf` rail | ±1.4 V | ±1.2 V | ±6.5 V | ±1.4 V | Tap from LM317 + LM337 adjusted by single trim resistor pair (no pot — fixed E96 R chosen at build). For ILC1-1/7 (±6.5 V) the LM7806/7906 work well; for the low-rail tubes use LM317/337 set to a fixed value. Detail in companion build doc. |
| Output stage transistors | **M1, M2:** DMP3098L (PMOS, SOT-23, Diodes Inc.), DMN3404L (NMOS, SOT-23) | **M1, M2:** DMP3098L + DMN3404L | **Q_o_*, Q_a_*:** BC868 (NPN) + **BC869** (PNP) SOT-89 complementary pair, Nexperia | **M1, M2:** DMP3098L + DMN3404L | DigiKey: DMP3098L-7DICT-ND (~$0.61 @ 1), DMN3404L-7DICT-ND (~$0.35 @ 1 — check stock, NMOS occasionally back-ordered; AO3400A is a drop-in alt). BC868/BC869 (SOT-89, Nexperia) ~$0.40 @ 1 each. The booster sees ≤±2 V_pk for IV-3/-6/ILC1-1/8 (low-rail MOSFETs OK) and ±5.5 V_pk for ILC1-1/7 (medium-V BJT, ss_avg ~100 mW each — SOT-89 thermal margin chosen for headroom). |

ILC1-1/7-only feedback divider bottom resistor `R_buf*_fb2` = 1 kΩ (same on others).

---

## Cost summary (qty-1 DigiKey, per tube)

| Item                                    | $ per tube |
|-----------------------------------------|------------|
| 2× TLV9154 (U1, U2)                      | 4.10       |
| 1× OPA2188 (U3)                          | 3.36       |
| 1× CD74HC4053M96 (U4)                    | 0.54       |
| 1× SN74HC14DR (U5)                       | 0.40       |
| 2× DMN3404L (M_var1, M_var2 — all-pass)  | 0.70       |
| 1× 1 MΩ (R_var_mid_bias)                 | 0.01       |
| 1× TL431 + 1:1 divider (V_offset_ref)    | 0.10       |
| 2× MMBT3904 (Q1, Q2)                     | 0.12       |
| 6× 1N4148WS (D1–D6)                      | 0.60       |
| Output stage (BJT pair or MOSFET pair)   | 0.80–1.00  |
| 2× LDO + decoupling                      | 1.20       |
| Resistors (~50 generic 1 %)              | 1.00       |
| Capacitors (1× C_ap PP, 1× C_intfb PP, ~10 ceramics) | 1.50 |
| **Total**                                | **~$15–15.8** |

Headroom of ~$4 against the $20/tube target. All parts in stock at
DigiKey and Mouser as of this writing; no allocation issues, no
single-source distributors.

---

## Notes on the synchronous demodulator (U4 + U5)

The netlist models the demodulator with two SPICE `S` switches
controlled by `n_cmp = sign(V_osc)`. The real implementation is:

1. `U5a` (one 74HC14 Schmitt-trigger stage): input is V_osc through
   a 100 kΩ resistor with a Schottky clamp to GND/+9 V. Output is a
   clean 0/+9 V square wave at f0 = 1 kHz.
2. `U4` (one channel of CD74HC4053): control = U5a output. X0 input
   = 0 (GND), X1 input = `n_diff` (op-amp output), common = `vplus`.

This replaces the `S1`/`S2` SPICE primitives with one IC channel
plus one inverter. CD74HC4053 has Ron ≈ 100 Ω, well above the SPICE
model's 10 Ω, but `R_din = 10 kΩ` makes the gain error <1 % which is
well below the 5 K T_op accuracy goal.

The remaining two channels of U4 are unused — wire X-pins to GND.

If a builder prefers an even cheaper part, CD4053BNSR (~$0.40, the
non-HC version) works identically with Ron ≈ 240 Ω → gain error
~2.4 % — still adequate.
