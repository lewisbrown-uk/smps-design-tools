# SCHEMATIC — VFD filament regulator (production hardware, source of truth)

**Status:** schematic-capture source document for the **canonical
`regulator.py` design**, productionisation phase (2026-06-11). This is the
authoritative *electrical* schematic of the **shipping hardware** — it
expands the two behavioural stand-ins in the simulation netlist into their
real circuits and turns the protection on (it ships). It is the exact input
for EDA capture (KiCad) and supersedes the `.asc` files for connectivity.

Connectivity is transcribed **net-for-net** from the canonical generator
`regulator.py::make_netlist` and the generated `regulator_<tube>.cir`
(the single source of truth), then reconciled with `BOM.md`. Where this
document and `BOM.md` disagree, **the netlist wins** and the discrepancy is
logged in §11 (the BOM has drifted and needs a follow-up edit).

Production configuration captured here:
`make_netlist(switch_demod=True, overpower_protect=True, stiff_clamp=True)`
— i.e. the real CD4053B demod, the protection chain enabled (per the locked
decision), and the sharp-knee clamp. Per-tube values from `TUBES`.

Locked productionisation decisions folded in (2026-06-11):
- **Protection ships** → §8 is part of the design, not optional. `R_series`
  is replaced by the latching-relay disconnect.
- **0.1 % bridge refs** → `R_sense`, `R_topref`, `R_botref` are 0.1 %
  thin-film (was 1 %) — shaves ~±16 K off the brightness envelope.
- Cold-start +7.4 K (ILC1-1/8) **accepted** → no per-tube warm-up change.

---

## 0. Conventions

- **Net names** are the netlist node names (authoritative). Ground = `0`.
- **RefDes** follow `BOM.md` where assigned (U1–U5, Q1–Q6…); netlist element
  names are given alongside so the two can be cross-walked.
- A net listed under a component is the node that pin connects to. Each block
  lists its **components** then its **internal/boundary nets**.
- "**Behavioural→real**" callouts mark where the sim used a `B`-source or
  ideal element and what the hardware part is.
- Op-amp macromodel `uopamp_lvl3 (Avol=5meg GBW=1meg …)` = **OPA4277** channel
  everywhere unless noted "comparator".

### Top-level signal flow

```
                                              +5V
                                               │  R_led_set 270Ω
 Wien osc ──atten──► Stage1 ──► Stage2 ──AC──► classAB ──Rcs──[RELAY]──► v_bridge_top
 (1kHz, S1)  (S2)   (H11F VG)   (G2=25)  couple  buffer        (S8 disc)      │
   ▲                  ▲ R_h11f                                                ▼
   │ osc cutoff       │ LED                                            ┌── AC bridge ──┐
   │ (fault)          │                                          filament arm   ref arm
   │             v_int_buf◄─buf─ v_int                            (R_sense)   (Rtop/Rbot)
   │                            ▲                                     │node_A    │node_B
   │                       anti-windup                            buf_A│      buf_B│
   │                            ▲                                      ▼          ▼
 [SUPERVISOR]◄─v_int─── PID integrator ◄── LP ◄── post-chop diff ◄── CD4053B chopper
  (S8 window               (XU_int)        (7.2Hz)   (×30, S6)       (commutating, S6)
   comparators)                                                          ▲ gate
                                                                    comparator(v_osc)
```

Sheets: **S1** rails+refs · **S2** Wien source · **S3** variable-gain (H11F)
· **S4** class-AB output · **S5** AC bridge + buffers · **S6** sync demod +
filter · **S7** PID + anti-windup + LED drive · **S8** protection.

---

## 1. Sheet S1 — Power supplies & references

| RefDes | netlist | part | value / note |
|---|---|---|---|
| VR1 | `V_vcc` | LM317-set / MC7810 | **+10 V** main rail (`vcc_top`). Ramps 0→+10 V over `t_rail_ramp` in sim; the real LDO output-cap charge does this. |
| VR2 | `V_vee` | LM337-set / MC7910 | **−10 V** rail (`vee_top`). |
| VR3 | `V_led_supply` | 78L05 | **+5 V** H11F LED supply (`n_v_led`). |
| VR4 | (Wien `Vcc`) | raw / LM317 | **+15 V** Wien-only rail — feeds the NE5532 (§2). |
| VR5 | (Wien `Vee`) | raw / LM337 | **−15 V** Wien-only rail. |
| — | `R_sense_vcc` 0.1 Ω | — | **model-only** rail-sense element `vcc_top→vcc_buf`. In HW `vcc_buf`≡`vcc_top` (a star point); **do not place a real 0.1 Ω.** |
| — | `R_sense_vee` 0.1 Ω | — | model-only `vee_top→vee_buf`. Same. |
| C(dec) | — | X7R 100 nF + 10 µF | one 100 nF + bulk per IC per rail (BOM). |

**Nets:** `vcc_top`/`vcc_buf` (+10), `vee_top`/`vee_buf` (−10), `n_v_led` (+5),
Wien `vcc`/`vee` (±15), `0`. **Rail topology:** a ±15 V raw pair is the master
supply — the NE5532 Wien (§2) runs directly off it, and the ±10 V regulator
rails (`vcc_top`/`vee_top`) derive from it via LM317/337; +5 V via 78L05.

**Behavioural→real:** the sim drives `vcc_buf`/`vee_buf` (post the 0.1 Ω
sense). In hardware all op-amp/buffer +rails tie to one `vcc_buf` star and
−rails to `vee_buf`. The `R_sense_*` resistors exist only so the sim can
read rail current; they are **not parts.**

**Clamp references** (used by S7) — `V_clamp_hi=+4.0 V`, `V_clamp_lo=−0.5 V`:
- **Behavioural→real:** ideal V-sources in sim. **Adopted (§11-i): [−3 V, +6 V]
  window via LM4040 shunt refs** (wider than the sim −0.5/+4.0 for corner /
  low-power-tube headroom).

---

## 2. Sheet S2 — Wien-bridge oscillator (1 kHz carrier) + attenuator

**Behavioural→real:** the netlist abstracts the whole oscillator as one
source — `B_src v_src 0 V = V_pk·env(t)·sin(2π·1000·t)` with an exponential
build-up `env` (≈17 ms / 17 cycles). The real circuit is the biased-BJT
amplitude-clamped Wien from `wien_bridge_biased.cir`:

| RefDes | netlist (wien) | part | value |
|---|---|---|---|
| U6 | `XU1` | **NE5532** (dual, 1 ch) on **±15 V** | Wien gain element — **ships as-is, no retune** (§11-f) |
| R1,R2 | `R1`,`R2` | 1 % | **10 kΩ** frequency-set |
| C1,C2 | `C1`,`C2` | **C0G/NP0 or PP film**, 5 % | **15.9 nF** (16 nF) → f₀=1/(2πRC)=1 kHz |
| Rg,Rfa,Rfb | `Rg`,`Rfa`,`Rfb` | 1 % | **10 k / 10 k / 12 k** loop-gain net (gain just >3) |
| Q7,Q8 | `Q1`,`Q2` | **MMBT3904** (SOT-23), matched anti-parallel | amplitude clamp across `Rfb` (kills H2) |
| Rtop1/2,Rbot1/2 | `Rtop1/2`,`Rbot1/2` | 1 % | clamp base-bias dividers **169 k/71.5 k** E96 (sim 168 k/72 k, α≈0.30) |

**Wien nets:** `out` (oscillator output ≡ sim `v_src`), `ns`, `np`, `nn`, `fb`, `b1`, `b2`.
Positive-FB: `out→R1→ns→C1→np→R2→0`, `C2 np→0`. Op-amp `XU1(+)=np, (−)=nn, out=out`.
Neg-FB clamp: `Rg nn→0`, `Rfa nn→fb`, `Rfb fb→out`, `Q1(C=fb,B=b1,E=out)`, `Q2(C=out,B=b2,E=fb)`.

> **Rails = ±15 V, op-amp = NE5532 (decision §11-f):** ship the oscillator
> as `wien_bridge_biased.cir` — the clamp base-bias dividers were tuned at
> ±15 V (α=0.30), so keeping ±15 V means **no op-amp retune**. (Bias resistors
> realised as E96 **169 k/71.5 k** for the non-standard tuned 168 k/72 k —
> ratio within 1.3 %, α≈0.30 preserved.) Steady output **3.63 V_pk
> (2.57 V_rms) @ 25 °C** (measured,
> `wien_clamp_power.txt`), shrinking with temperature (2.84 V @ 60 °C) and
> dying ~70 °C — the airflow/separation build note stands. This is the only
> ±15 V block; everything downstream is ±10 V OPA4277.

### Per-tube attenuator — 2-stage buffered divider (RESOLVED, §11-d)

The carrier into Stage 1 is sub-mV…few-mV (§9); a single divider from the
3.63 V_pk Wien needs hundreds-of-kΩ–MΩ top legs that load the oscillator.
**Shipping design = two cascaded dividers with a buffer between**, so every
resistor stays mid-decade:

```
 v_src ─R_aT 49.9k─┬─ n_atten_div_a ─► XU_atten_buf1 ─► n_atten_mid ─R_atten_top─┬─ n_atten_raw ─► XU_atten_buf ─► v_atten ─► S3
       R_aB 1k ────┘   (Stage A ÷50, buffered)    (~72 mV_pk)      (per-tube)  R_atten_bot 1k     (Stage B buffer)
        │                                                                        │
        0                                                                        0
```
| RefDes | netlist | part | value |
|---|---|---|---|
| R_aT / R_aB | (Stage A — fixed, all tubes) | 1 % | **49.9 kΩ / 1 kΩ** → ÷50 |
| U1e | `XU_atten_buf1` *(NEW)* | OPA4277 ch | inter-stage unity buffer `(+)=n_atten_div_a, out=n_atten_mid` (~72 mV_pk) |
| R_at | `R_atten_top` | 1 % | **per-tube** (§9), off the buffered node |
| R_ab | `R_atten_bot` | 1 % | 1 kΩ |
| U1a | `XU_atten_buf` | OPA4277 ch | Stage-B unity buffer `(+)=n_atten_raw, out=v_atten` |

The inter-stage buffer kills Stage A's ~1 kΩ source impedance so Stage B's
ratio is exact — unbuffered, the R_aT/R_atten_top interaction would shift the
ILC1-1/7 carrier ~15 %. The added channel `XU_atten_buf1` is in the 4-quad
count (§10).

> The *generated* netlist keeps a single fixed 12 k/1 k divider and buries the
> per-tube level in the `B_src` amplitude (a sim abstraction). The §9 table
> gives the real hardware Stage-B legs that reproduce each tube's `v_atten`.

> **Carrier tempco:** the Wien amplitude drifts −0.45 %/°C, so `v_atten` drifts
> with it — **harmless**: the bridge null is ratiometric and the loop rejects
> carrier-amplitude variation (validated). The Wien's >60–70 °C death cliff is
> the real temperature limit, unaffected by this divider.

---

## 3. Sheet S3 — Variable-gain stage (H11F Stage-1 + Stage-2)

### Stage 1 — H11F photo-FET variable-gain (split-gain inverting)

```
  v_atten ─R_in_vgain─┬─ n_h11f_inv ──(−)┐
                      │                  XU_vgain ─► v_drv1
                      ├──R_max_s1────────┤(+)=0
                      └──H11F FET───┘  (feedback = R_max_s1 ∥ R_h11f)
```
| RefDes | netlist | part | value |
|---|---|---|---|
| U1b | `XU_vgain` | OPA4277 ch | inverting VGA: `(+)=0,(−)=n_h11f_inv,out=v_drv1` |
| R_inv | `R_in_vgain` | 1 % | **40.2 Ω** E96 (⚠ **28 Ω for IV-18** — 5th per-tube part, §9/§11-e) |
| R_max | `R_max_s1` | 1 % | **140 Ω** — bounds gain & desensitises H11F spread |
| U4 (FET) | `X_h11f` FET side | **H11F1M** | channel `n_h11f_inv ↔ v_drv1`, ∥ R_max_s1 |

Gain = −(R_max ∥ R_h11f)/R_in. R_h11f set by LED current (S7).

> ⚠ **BOM drift (§11-b):** `BOM.md` quotes R_in_vgain=10 Ω / R_max_s1=24 Ω.
> The canonical netlist is **40 Ω / 140 Ω**. Netlist wins — fix the BOM.

### DC couple → Stage 2 (fixed gain G2 = 25)

```
  v_drv1 ─R_dc_couple(0Ω wire)─ n_s2_in ─(+)┐
                                            XU_s2 ─► v_drv
                          n_minus_s2 ─(−)───┤
            R_fb_s2(2.4k) v_drv→n_minus_s2 ; R_gnd_s2(100) n_minus_s2→0
```
| RefDes | netlist | part | value |
|---|---|---|---|
| U1c | `XU_s2` | OPA4277 ch | non-inv, G2 = 1+2400/100 = **25** |
| — | `R_dc_couple` | — | **0 Ω = a wire** `v_drv1→n_s2_in` (model artifact; just connect) |
| R_fb2 | `R_fb_s2` | 1 % | 2.4 kΩ |
| R_g2 | `R_gnd_s2` | 1 % | 100 Ω |

> Do **not** restore G2=201 (the old value); G2=25 ("Fix A") is the Vos-robust point.

---

## 4. Sheet S4 — Class-AB push-pull output buffer

AC-couple Stage-2 → buffer, then a V_BE-multiplier-biased complementary pair.

```
 v_drv ─C_couple_buf(1µF)─ v_buf_in ─(+)┐
              R_bias_buf 16k v_buf_in→0   XU_buf ─► n_buf_o ─► [V_BE mult] ─► out pair
                          n_fb_buf ─(−)──┤        R_fb_buf 13k v_osc_drive→n_fb_buf
                                                  R_in_buf  1k  n_fb_buf→0   (k_buf=14)
```
| RefDes | netlist | part | value / role |
|---|---|---|---|
| U1d | `XU_buf` | OPA4277 ch | driver: `(+)=v_buf_in,(−)=n_fb_buf,out=n_buf_o` |
| C_cb | `C_couple_buf` | X7R/film | **1 µF** AC-couple `v_drv→v_buf_in` |
| R_bb | `R_bias_buf` | 1 % | 16 kΩ input bias |
| R_fbb,R_inb | `R_fb_buf`,`R_in_buf` | 1 % | 13 k / 1 k → k_buf=14 (fb tapped from `v_osc_drive`) |

### V_BE-multiplier class-AB bias (sets Iq≈20 mA, thermally tracks)

| RefDes | netlist | part | value |
|---|---|---|---|
| Q_vbmt | `Q_vbm_t` | **BCX54** (NPN) | top multiplier `C=q_o_bn,B=vbm_t_b,E=n_buf_o` |
| Q_vbmb | `Q_vbm_b` | BCX54 (NPN) | bottom multiplier `C=n_buf_o,B=vbm_b_b,E=q_o_bp` |
| Rvbm | `R_vbm_t1/t2/b1/b2` | 1 % | 680 / 1000 (ratio 1.68 → ~2 V_BE/half) |
| Rbbo | `R_bbo_ta/tb/ba/bb` | 5 % | 1.1 kΩ ×4 bias-chain feed (bootstrapped) |
| C_bbo | `C_bbo_t`,`C_bbo_b` | **⚠ tant/elec/film, NOT Y5V** | **4.7 µF** bias-rail bootstrap → `n_buf_emi` |

> ⚠ **Dielectric rule:** `C_bbo_t/b` are the ONLY THD-critical caps. Y5V droop
> here collapses the class-AB rail mid-cycle (THD −55→−22 dB hot). At 4.7 µF
> they're tant/elec anyway — just never spec Y5V. **Bootstrap to `n_buf_emi`
> (the BJT emitter node), not `v_osc_drive`** (post-Rcs) — else the I·Rcs drop
> starves V_BE at peak current.

### Output pair + drivers

| RefDes | netlist | part | role |
|---|---|---|---|
| Q1 | `Q_o_out_n` | **BCX54** (NPN, SOT-89, VCEO 45 V) | top output `C=vcc_buf,B=n_o_pair_n,E=n_buf_emi` |
| Q2 | `Q_o_out_p` | **BCX51** (PNP, SOT-89) | bottom output `C=vee_buf,B=n_o_pair_p,E=n_buf_emi` |
| Q3 | `Q_o_drv_n` | BCX54 | top driver `C=vcc_buf,B=q_o_bn,E=n_o_pair_n` |
| Q4 | `Q_o_drv_p` | BCX51 | bottom driver `C=vee_buf,B=q_o_bp,E=n_o_pair_p` |
| Rbl | `R_o_bleed_n/p` | 5 % | 5.1 kΩ ×2 (`n_o_pair_*→n_buf_emi`) |
| Rcs | `R_cs` | — | **0.01–0.1 Ω** sense `n_buf_emi→v_osc_drive` (short trace OK) |

> ⚠ **PCB thermal:** SOT-89 sheds via collector tab. Worst device ILC1-1/8
> ~0.58 W exceeds the 0.5 W bare-footprint rating on ±10 V rails → **pour
> ≥1 cm² copper** under Q1/Q2 tabs (Tj→101 °C@25/126 °C@50). Mount Q_vbm_t/b
> against the output tabs (thermal tracking). ILC1-1/7 OK with a small pad;
> IV-6/IV-18 fine bare. (Rail-scaling to ±5 V on the low-V tubes removes the
> pour requirement — see BOM §rail-scaling; not the current default.)

> Current limit (`Q_cl_n/Q_cl_p`, `I_limit_enable`) is **disabled** in the
> shipping config (Rcs=0.01 Ω). Documented in `regulator.py` if revived.

**`R_series` → relay:** in the shipping (protected) build the 0.01 Ω
`R_series v_osc_drive→v_bridge_top` is **replaced by the latching-relay
disconnect contact** (S8, `S_disc_op`). Unprotected build only: a 0.01 Ω
link / short trace.

---

## 5. Sheet S5 — AC bridge + buffers

```
  v_bridge_top ─┬─[FILAMENT arm]── node_A ──R_sense──┐
                │  X_filament                         ├─ v_ap_drive ─R_ap_gnd(0.01)─ 0
                └─R_topref── node_B ──R_botref────────┘
       node_A ─► XU_buf_A ─► n_node_A_buf   (high-Z tap)
       node_B ─► XU_buf_B ─► n_node_B_buf
```
| RefDes | netlist | part | value |
|---|---|---|---|
| XF | `X_filament` | **the VFD tube filament** | thermal macromodel in sim; the real tube in HW. `v_bridge_top↔node_A` |
| **Rs** | `R_sense` | **0.1 % thin-film** | **per-tube** (§9). Carries load current — power-rate per tube (ILC1-1/7 ½ W). |
| **Rtr** | `R_topref` | **0.1 % thin-film** | **per-tube** (§9) |
| **Rbr** | `R_botref` | **0.1 % thin-film** | **per-tube** (§9) |
| — | `R_ap_gnd` | — | 0.01 Ω model tie `v_ap_drive→0` (≈ a wire/star ground) |
| U2a | `XU_buf_A` | OPA4277 ch | buffer `(+)=node_A,(−)=out,out=n_node_A_buf` |
| U2b | `XU_buf_B` | OPA4277 ch | buffer `(+)=node_B,(−)=out,out=n_node_B_buf` |

**Regulated point:** `R_fil = R_sense·R_topref/R_botref` (held by the loop).
The three bridge resistors are the ONLY lever on T uniformity → **0.1 %**
(locked decision) gives the tightest digit-to-digit match; with the tube's own
±5 % filament spread the worst-case envelope is ~±55 K (0.1 % refs shave ~±16 K
vs 1 %). `R_ap_gnd`/`R_series` drops are common-mode (both arms tap
`v_bridge_top`) → bridge balance unaffected.

---

## 6. Sheet S6 — Synchronous demodulator (CD4053B) + filter

**Behavioural→real:** sim default is `B_demod = 30·(n_node_B_buf −
n_node_A_buf)·sign(v_osc_drive)`. The shipping hardware (`switch_demod=True`)
is the **commutating analog-switch** detector that this stands in for:

```
 v_osc_drive ─►[comparator]─► n_demod_ref ──┬─► gate S_dp1,S_dm1
   XU_demod_comp (LM393/TLV3201)            └─►[inverter]─► n_demod_refn ─► gate S_dp2,S_dm2

   half-cycle +:  n_demod_plus=node_B_buf , n_demod_minus=node_A_buf
   half-cycle −:  n_demod_plus=node_A_buf , n_demod_minus=node_B_buf   (commutation)

 n_demod_plus ─R_dda_inp 1k─ n_dda_p ─R_dda_g1 15k─ n_dda_gmid ─R_dda_g2 15k─ 0
 n_demod_minus─R_dda_inm 1k─ n_dda_m                            (split-R, fault-safe)
 R_dda_fb 30k  n_demod→n_dda_m ;  XU_demod_da(+)=n_dda_p,(−)=n_dda_m,out=n_demod
 n_demod ─R_lp_demod 100k─ n_demod_dc ─C_lp_demod 0.22µF─ 0     (~7.2 Hz LP)
```
| RefDes | netlist | part | value / role |
|---|---|---|---|
| U5 | `XU_demod_comp` | **LM393** (or TLV3201) | squares `v_osc_drive` → `n_demod_ref` gate |
| U7 | (`B_demod_refn`) | **SN74HC14** inverter | complementary gate `n_demod_refn = ¬n_demod_ref` |
| U8 | `S_dp1/2`,`S_dm1/2` | **CD4053B** (±5 V bipolar) | 2 SPDT used: plus-line {B,A}, minus-line {A,B}. **NOT 74HC4053** (6 V-class). DG419/ADG419 = lower-charge-injection premium. |
| — | `R_dp_gnd`,`R_dm_gnd` | 1 % | 1 MΩ bias `n_demod_plus/minus→0` |
| U2c | `XU_demod_da` | OPA4277 ch | post-chop diff amp, gain = R_dda_fb/R_dda_in = **30** |
| Rdda | `R_dda_inp/inm` | 0.1–1 % match | 1 kΩ pair |
| Rddag | `R_dda_g1/g2` | match | **15 k + 15 k split** — a single-R short leaves 15 k to gnd (keeps diff rejection; closes the last demod FMEA fault) |
| Rddaf | `R_dda_fb` | match | 30 kΩ |
| Rlp,Clp | `R_lp_demod`,`C_lp_demod` | X7R ok | 100 kΩ / 0.22 µF → ~7.2 Hz (out of crossover, ~49 dB at 2 kHz ripple) |

Switch R_on (~60–300 Ω) is common-mode → negligible; raise `R_dda_in` to 10 k
(fb 300 k) for margin. Charge injection (~1–20 pC) → small DC offset the loop
absorbs.

---

## 7. Sheet S7 — PID compensator, anti-windup, LED drive (PRE-log sensing)

The integrator senses `n_demod_dc` **directly** — there is **no ×20 log/gain
stage** (removed in the pre-log fix; the gain is folded into `R_int`).

```
 V_set 0V ─R_int_p 49.9k─ n_int_plus ─(+)┐               (R_int_pg 1G = model leak, OMIT in HW)
                                        XU_int ─► v_int_raw
 n_demod_dc ─R_intin 49.9k──┬─ n_int_minus ─(−)┤
            C_intin 1n ────┘                  │
   feedback:  C_intfb 318n n_int_minus→n_int_pidp ; R_pid 1M n_int_pidp→v_int_raw ;
              C_hf 1n n_int_pidp→v_int_raw          (zero ~5 Hz, HF pole ~160 Hz)
```
| RefDes | netlist | part | value |
|---|---|---|---|
| U3a | `XU_int` | OPA4277 ch | PID integrator |
| Rip | `R_int_p` | 1 % | **49.9 kΩ** (E96; `R_int`=50 k design, gain folded from removed ×20) |
| Rii | `R_intin` | 1 % | **49.9 kΩ** |
| Cii | `C_intin` | C0G | 1 nF |
| Cif | `C_intfb` | **film/C0G** | **0.318 µF** (use 330 nF) — dominant pole, value-stable |
| Rpid | `R_pid` | 1 % | 1 MΩ |
| Chf | `C_hf` | C0G | 1 nF |
| Vset | `V_set` | — | 0 V setpoint (a ground tie) |

### Saturator + back-calc anti-windup

```
 v_int_raw ─R_aw_out 10─ v_int ─┬─ D_aw_hi ─► v_clamp_hi(+4)
                                └─ D_aw_lo ◄─ v_clamp_lo(−0.5)
 diff amp (×1): R_diff1 v_int→n_aw_diff_minus 100k ; R_diff2 v_int_raw→n_aw_diff_plus 100k ;
                R_diff3 n_aw_diff_minus→e_sat 100k ; R_diff4 n_aw_diff_plus→0 100k ;
                XU_aw_diff(+)=n_aw_diff_plus,(−)=n_aw_diff_minus,out=e_sat = v_int_raw−v_int
 R_bc 2.49k e_sat→n_int_minus   (= R_int/20 → unwinds 20× faster than wind-up)
```
| RefDes | netlist | part | value |
|---|---|---|---|
| U3b | `XU_aw_diff` | OPA4277 ch | unity diff amp → `e_sat` |
| Raw | `R_aw_out` | 1 % | 10 Ω |
| Daw | `D_aw_hi`,`D_aw_lo` | **BAT54** (low V_F) or 1N4148 | clamp diodes (`stiff_clamp` ⇒ sharp-knee low-Rs) |
| Rdiff | `R_diff1..4` | 0.1–1 % match | 100 kΩ ×4 |
| Rbc | `R_bc` | 1 % | **2.49 kΩ** (E96; = R_int/20) |

### H11F LED drive (buffered — current bypasses anti-windup R)

```
 +5V(n_v_led) ─R_led_set 270─ n_led_a ─(LED anode)│H11F LED│(cathode)─ v_int_buf
 XU_led_buf:  (+)=v_int,(−)=v_int_buf,out=v_int_buf   (unity buffer of v_int)
```
| RefDes | netlist | part | value |
|---|---|---|---|
| U3c | `XU_led_buf` | OPA4277 ch | buffers `v_int`→`v_int_buf` so I_LED bypasses `R_aw_out` |
| Rled | `R_led_set` | 1 % | 270 Ω (I_LED ≈ (5−V_F−v_int)/270 ≈ 4–14 mA) |
| U4 (LED) | `X_h11f` LED side | **H11F1M** | anode `n_led_a`, cathode `v_int_buf` |

V_int=0 ⇒ I_LED max ⇒ R_h11f min ⇒ **max drive** (cold-start state); V_int
rises as the loop throttles back. Clamp still acts on `v_int`.

---

## 8. Sheet S8 — Protection (SHIPS) — supervisor + over-power

Two cooperating layers, both armed only after loop capture
(`v_int` first > `v_fault_arm`=1.5 V) and both **latching**.

**Behavioural→real:** the sim uses `B`-source comparators/multipliers + RC
latches. Hardware = window comparators + voltage references + RC qualifiers +
diode-cap (or SR-latch) latches + a logic-gated output.

### 8a. Dual-sided V_int fault supervisor → oscillator cutoff

Watches the integrator output both ways (every overheating passive fault rails
`v_int` to a clamp):
| signal | netlist | trip | HW |
|---|---|---|---|
| arm | `B_arm`/`D_arm`/`C_arm` | `v_int>1.5` latches "armed" | comparator + diode-cap |
| LOW | `B_lo`,`R_loq/C_loq` (τ=`t_fault_lo`=1 ms) | `v_int<0.5` **fast** | window comp, glitch-qual |
| HIGH | `B_hi`,`R_hiq/C_hiq` (τ=`t_fault_hi`=3 s) | `v_int>3.7` **sustained** | window comp + RC integrator (rejects cold-start ride) |
| latch | `B_tr`,`B_tr_hi`,`D_tr`,`C_lat` | either trip, set-dominant | diode-OR into a latch |
| **cutoff** | `src_gate` on `B_src` | gate the **Wien oscillator OFF** | a transistor disabling the Wien → filament cools cold-safe + drive a **fault LED** |

LOW = loss-of-authority/forward-gain faults (loop fights to low rail, ms-fast).
HIGH = sense/setpoint/bridge-ref faults (loop winds to max drive, time-qualified).

### 8b. Over-power: flat-clamp + authority-gated disconnect

The supervisor's cutoff hits the oscillator **upstream** of a stuck output
buffer, so it can't isolate that fault — hence a second layer on the drive
node. Requires the supervisor present (reuses its `n_armed/n_lo_int/n_hi_int`).

| block | netlist | part | role |
|---|---|---|---|
| **flat-clamp** | `D_clp_op/D_cln_op` to `±V_cl` | **TLV431 active shunt** (per-tube ref) / flat-clamp TVS | bounds **instantaneous** drive on `v_osc_drive` → peak independent of relay lag. `V_cl = k_clamp·V_op·√2·(R_op+R_sense)/R_op`, **k_clamp=1.5** |
| over-power sense | `R1op..R5op`,`D1op/D2op`,`XA1op`,`XA2op`,`R_envop/C_envop` | **precision FWR** (2 OPA4277 ch + Schottky) + envelope | rectifies filament-side drive; trip if `−V(n_envop) > k_overpower·V_op`, **k_overpower=1.3** |
| disconnect logic | `B_discset_op`,`D_disc_op`,`C_disc_op` | window-comp AND + SR latch | **DISCONNECT = over_power AND (V_int low OR high) AND armed** — the authority discriminator (commanded over-power = warm-up, has V_int high+benign; fault over-power latches) |
| relay drive | `B_coil_op`,`R_coil_op`,`C_coil_op` | coil driver (RC = `t_relay`=7 ms actuation model) | energise/latch |
| **disconnect** | `S_disc_op` (model `SWdisc_op`) | **latching relay** contact `v_osc_drive↔v_bridge_top` | cold-safe series isolation (replaces `R_series`) |

> Clamp + disconnect **compound**: clamp caps the rate, disconnect caps the
> dwell. Validated worst-case fault peak **≤922 K** (IV-6/ILC1-1/8 botref_short
> & topref_open; **three tubes cross 900 K** — IV-6 922, ILC1-1/8 913, IV-18
> 909), bounded by the flat-clamp floor (~1030 K), then cold-safe; **zero false
> trips** on cold-start / restart / brownout. *(The HANDOFF's "≤899 K, never
> 900 K" was the IV-18-only dwell figure; the full-battery worst is 922 K —
> reproduced by `cap_derate_fmea.md` Part 2 and matching Suite D / OVERNIGHT
> §FMEA.)* The ≤127 ms >800 K dwell figure is IV-18-specific; dwell at the
> 922 K peaks is not separately characterised.
> **Lock per-tube `k_clamp`/`t_relay`** and re-confirm `t_relay` against the
> real latching relay's datasheet actuation time before a production run.

---

## 9. Per-tube variant table (the ONLY parts that change)

| element | netlist | IV-18 | IV-6 | ILC1-1/7 | ILC1-1/8 | grade |
|---|---|---|---|---|---|---|
| `R_topref` | bridge top | 1 kΩ | 2 kΩ | 3.3 kΩ | 1.2 kΩ | **0.1 %, E24** |
| `R_botref` | bridge bot | 100 Ω | 510 Ω | 620 Ω | 300 Ω | **0.1 %, E24** |
| `R_sense` | bridge sense | 10 Ω | 5.1 Ω | 4.7 Ω | 2 Ω | **0.1 %, E24** (½ W on ILC1-1/7) |
| target `R_fil` | =Rs·Rtr/Rbr | 100 Ω | 20 Ω | 25 Ω | 8 Ω | held exactly (ILC1-1/7 +0.43 K) |
| carrier level | (sim `V_src_rms`) | 0.0115 | 0.019 | 0.088 | 0.0224 | set by `R_atten_top` |
| `v_atten` target | Stage-1 in | 0.885 mV | 1.46 mV | 6.77 mV | 1.72 mV | rms (= carrier/13 in sim) |
| **`R_atten_top`** (Stage B) | attenuator | **57.6 kΩ** | **34.0 kΩ** | **6.65 kΩ** | **28.7 kΩ** | 1 % — off the ÷50 buffered node (§2). Stage A = 49.9 k/1 k fixed (all tubes). |
| ⚠ `R_in_vgain` | Stage-1 in | **28 Ω** | 40.2 Ω | 40.2 Ω | 40.2 Ω | 1 % — **IV-18 differs (5th per-tube part)** |

**Bridge triplets are E24 (0.1 %)** — chosen by E-series search (2026-06-12) to
hold each tube's `R_fil` exactly: IV-6/IV-18/ILC1-1/8 land dead-on, ILC1-1/7 is
+0.43 K (a fixed nominal offset, swamped by ±5 % filament spread). 0.1 % is
stocked in E24 values. The triplets preserve `R_fil` and the loop transfer
exactly; only the reference-arm absolute impedance moves a few % (IV-18/
ILC1-1/8 keep the same divider ratio). These supersede the netlist's design-
round values (5 k/1 k etc.) — **re-run the validation battery on the final
values to confirm** (regulated point unchanged, so a confirmation not a
redesign). ILC1-1/7 exact alternative if wanted: E96 4.99/5.11 k/1.02 k
(−0.03 K).

`R_atten_top` (Stage B) computed for the buffered ~72 mV_pk mid node (3.63 V_pk
Wien ÷50), `R_atten_bot`=1 kΩ → reproduces each tube's `v_atten`. E96 values;
all mid-decade. The 2-stage buffered divider (§2/§11-d) replaces the
impractical single-stage MΩ legs.

> The BOM's "only FOUR things vary" is **wrong for IV-18**, which also needs
> `R_in_vgain`=28 Ω. Five per-tube items: 3 bridge refs + attenuator +
> (IV-18 only) R_in_vgain.

---

## 10. Op-amp / comparator channel inventory (CORRECTED)

Recounted from the **shipping** netlist (`switch_demod=True,
overpower_protect=True`) — this **supersedes** the BOM's "3 quads + 1
comparator", which predates protection and still counts the removed `XU_log`.

**OPA4277 op-amp channels (13):**
`XU_atten_buf1`(NEW), `XU_atten_buf, XU_vgain, XU_s2, XU_buf` (5) · `XU_buf_A,
XU_buf_B, XU_demod_da` (3) · `XU_int, XU_aw_diff, XU_led_buf` (3) ·
**over-power FWR `XA1op, XA2op`** (2) = **13 channels → 4 quad packages
(U1–U4)** (16 ch, 3 spare), *up from 3 quads.*
The **Wien op-amp is NOT an OPA4277** — it is a dedicated **NE5532 (U6) on
±15 V** (§2). Net change vs the original 3-quad BOM: −`XU_log` (removed by
pre-log sensing), +`XU_atten_buf1` (2-stage divider), Wien moved to its own
package — i.e. the extra quad is driven by the over-power FWR pair + divider
buffer, not the Wien.

**Comparators:** `XU_demod_comp` (demod gate, LM393/TLV3201) + supervisor LOW
& HIGH window comparators + over-power window comparator ≈ **3–4 comparator
channels** (e.g. 1× LM339 quad). Plus **SN74HC14** inverter (demod
complementary gate; spare gates can also form the supervisor logic).

> ⚠ This raises the op-amp line item by one quad (~$2–3/tube) vs the BOM
> estimate. Folded back, cost stays within the ~$20 target. **Action: update
> BOM §op-amps with this inventory** (and drop the `XU_log` row).

---

## 11. Open items & BOM reconciliation

Discrepancies the schematic-capture pass surfaced — **the netlist is
authoritative; the BOM had drifted.** Status as of **2026-06-12**: both design
calls (d, f) resolved; the drift items (a, b, c, e, g) and the
window/value adoptions (h, i) **folded into `BOM.md`** in the same change;
only the bench-check carry-ins (j) remain open (they need hardware).

- **(a) `XU_log` removed — ✅ fixed in BOM.** Pre-log sensing deleted the ×20
  log-demod channel; dropped from the BOM op-amp table.
- **(b) Stage-1 gain resistors — ✅ fixed in BOM.** Netlist `R_in_vgain`=40 Ω,
  `R_max_s1`=140 Ω (BOM had 10 Ω / 24 Ω). Netlist wins.
- **(c) V_src_rms values — ✅ fixed in BOM.** Now `TUBES`
  0.0115/0.019/0.088/0.0224 (IV-18/IV-6/ILC1-1/7/ILC1-1/8).
- **(d) Attenuator realisation — ✅ RESOLVED (2026-06-12).** Adopt the
  **2-stage buffered divider** (§2): fixed ÷50 (49.9 k/1 k) → `XU_atten_buf1`
  → per-tube Stage-B leg (6.65 k–57.6 k / 1 k). All resistors mid-decade; adds
  one OPA4277 channel (in the 4-quad count §10).
- **(e) IV-18 5th per-tube part — ✅ fixed in BOM.** `R_in_vgain`=28 Ω added to
  the per-tube table; "only four things vary" corrected to five.
- **(f) Wien op-amp + rails — ✅ RESOLVED (2026-06-12).** Ship the Wien as
  `wien_bridge_biased.cir`: dedicated **NE5532 on ±15 V** (U6); ±15 V kept so
  the α=0.30 clamp bias needs **no op-amp retune** (bias realised E96
  169 k/71.5 k, ratio within 1.3 %). Adds a ±15 V supply pair (S1, VR4/VR5)
  that is the board's master rail; ±10 V derives from it. Wien is its own
  package, out of the OPA4277 quad count (§10). Steady output 3.63 V_pk @ 25 °C.
- **(g) Op-amp count → 4 quads — ✅ fixed in BOM** (§10). Packaging + cost
  updated (4× OPA4277 + the NE5532 Wien).
- **(h) Protection part values — ✅ LOCKED:** `k_clamp`=1.5, `k_overpower`=1.3,
  `t_relay`=7 ms, supervisor `v_fault_arm`=1.5 / `v_fault_trip`=0.5 /
  `v_fault_trip_hi`=3.7 / `t_fault_hi`=3 s. Still **re-confirm `t_relay`
  against the chosen latching relay's datasheet** and pick the TLV431 per-tube
  `V_cl` resistor (§8b) at PCB time.
- **(i) Clamp-ref window — ✅ ADOPTED [−3 V, +6 V]** via LM4040 shunt refs
  (§1), wider than sim −0.5/+4.0 for corner / low-power headroom.
- **(j) Bench-check carry-ins (unchanged):** Wien amplitude tempco / >60 °C
  death cliff (needs airflow/separation); H11F R(I_LED) at the real operating
  point; filament-R spread vs the constant-V assumption.
- **(k) E-series realisation — ✅ APPLIED (2026-06-12), re-sim PENDING.** All
  non-standard passives mapped to buildable values: **E24 0.1 % bridge
  triplets** (hold R_fil exactly, ILC1-1/7 +0.43 K), `R_in_vgain` 40→40.2 Ω,
  `R_int` 50→49.9 kΩ, `R_bc` 2.5→2.49 kΩ, Wien bias 168 k/72 k→169 k/71.5 k,
  `R_o_bleed` 5 k→5.1 k, FWR `R4op` 5 k→4.99 k. The bridge legs move the
  divider off the simulated values (regulated point unchanged) → **re-run the
  validation battery on the final E-series values to confirm** (and fold in the
  Wien-bias 1.3 % ratio shift). Cleanest: update `TUBES` in `regulator.py` to
  the final values, regenerate `regulator_<tube>.cir`, re-run the battery.

---

## 12. Net index (core loop)

`v_src`→`n_atten_raw`→`v_atten`→`n_h11f_inv`→`v_drv1`→`n_s2_in`→`v_drv`→
`v_buf_in`→`n_buf_o`→(`q_o_bn`/`q_o_bp`,`n_o_pair_n/p`)→`n_buf_emi`→
[`Rcs`]→`v_osc_drive`→[**relay**]→`v_bridge_top`→(`node_A`|`node_B`)→
`v_ap_drive`. Sense: `node_A/B`→`n_node_A_buf/B_buf`→(CD4053B)→
`n_demod_plus/minus`→`n_demod`→`n_demod_dc`→`n_int_minus`→`v_int_raw`→
`v_int`→`v_int_buf`→(H11F LED)→ sets `R_h11f` → closes loop.
Protection taps: `v_int` (supervisor), `v_bridge_top`/`v_osc_drive`
(over-power). Rails: `vcc_buf`(+10), `vee_buf`(−10), `n_v_led`(+5).
