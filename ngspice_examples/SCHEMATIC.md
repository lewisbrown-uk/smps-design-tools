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
— i.e. the real switched (DG419) demod, the protection chain enabled (per the locked
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
 [SUPERVISOR]◄─v_int─── PID integrator ◄── LP ◄── post-chop diff ◄── DG419 chopper
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

**Clamp references** (used by S7 anti-windup) — **adopted window [−3 V, +6 V]**
(the sim macromodel used −0.5/+4.0; widened for corner / low-power-tube headroom
and to clear the +3.7 V HIGH watchdog — §11-i):
- **Behavioural→real:** ideal V-sources in sim → **buffered dividers off the
  regulated ±10 V rails** (the full generation + E-series values are in **§7**:
  +6 V = 100 k/150 k off VCC, −3 V = 39 k/91 k off VEE, each via an OPA4277
  follower). A clamp ceiling needs only rail tolerance, so no shunt reference.

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
**Fault cutoff:** the protection supervisor's `Q_cut` (§8a) ties to **`np`** — on a
latched fault it shorts `np` to GND, collapsing the loop gain and stopping the
carrier (filament cools cold-safe).
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

## 6. Sheet S6 — Synchronous demodulator (2× DG419) + filter

**Behavioural→real:** the fast sim default is `B_demod = 30·(n_node_B_buf −
n_node_A_buf)·sign(v_osc_drive)`. The **shipping hardware** (`switch_demod=True`)
is the **commutating analog-switch** chopper that the B-source stands in for —
a phase-reference comparator gating a DG419 SPDT pair that swaps the two buffered bridge
taps onto the +/− inputs of a difference amplifier. Wire it exactly as below.

```
   ┌──────── PHASE REFERENCE — carrier zero-cross (U5a TLV3201, +5/0 single-supply) ────────┐
   │                          R_hyst 10M (n_demod_ref→n_pr_in, ~±50 mV hysteresis)          │
   │                        ┌──────────────────────────────────────────┐                    │
   │ v_osc_drive ─R_pr 100k─┴─ n_pr_in ─►(+)│U5a TLV3201│ out ──────────┴─ n_demod_ref ─► both DG419 INs
   │                        │   (push-pull, 0/+5, NO pull-up)                                │
   │            BAT54S clamp │  pin1=GND ─▶├─ pin2(centre)=n_pr_in ─▶├─ pin3=+5             │
   │            (centre tap  │   D1: GND→node (clamps −ve half)   D2: node→+5 (clamps +ve)  │
   │             = n_pr_in)  │            0 ──►(−)│U5a│                                       │
   │  V+ = +5   V− = 0(GND)   →  out HIGH when v_osc_drive ≥ 0   (40 ns: phase err ≪1° @1kHz)│
   └────────────────────────────────────────────────────────────────────────────────────────┘
       2× Vishay DG419 SPDT  — V+(6)=+5  V−(4)=−5  GND(8)=0  VL(5)=+5
       truth table: IN=0 → D–S1 closed ;  IN=1 → D–S2 closed  (break-before-make)
   ┌─ U8a  DG419 #1  (PLUS line) ────────────────────────────────────────┐
   │  pin1 D  (common)        = n_demod_plus                              │
   │  pin3 S1 (IN=0, v_osc<0) ◄── n_node_A_buf                            │
   │  pin2 S2 (IN=1, v_osc≥0) ◄── n_node_B_buf                            │
   │  pin7 IN                ◄── n_demod_ref                              │
   ├─ U8b  DG419 #2  (MINUS line) ───────────────────────────────────────┤
   │  pin1 D  (common)        = n_demod_minus                             │
   │  pin3 S1 (IN=0, v_osc<0) ◄── n_node_B_buf                            │
   │  pin2 S2 (IN=1, v_osc≥0) ◄── n_node_A_buf                            │
   │  pin7 IN                ◄── n_demod_ref                              │
   └─────────────────────────────────────────────────────────────────────┘
   net effect:  v_osc ≥ 0 → (plus=B, minus=A) ;  v_osc < 0 → (plus=A, minus=B)

 n_demod_plus ─R_dp_gnd 1M─ 0      n_demod_minus ─R_dm_gnd 1M─ 0   (bias to gnd)
 n_demod_plus ─R_dda_inp 1k─ n_dda_p ─R_dda_g1 15k─ n_dda_gmid ─R_dda_g2 15k─ 0
 n_demod_minus─R_dda_inm 1k─ n_dda_m ─R_dda_fb 30k─ n_demod   (feedback)
 U2c:  (+)=n_dda_p , (−)=n_dda_m , out=n_demod     (balanced diff amp, gain 30)
 n_demod ─R_lp_demod 100k─ n_demod_dc ─C_lp_demod 0.22µF─ 0     (~7.2 Hz LP → S7)
```

**Devices & connections (net-for-net):**

| RefDes | netlist | part | pins / nets |
|---|---|---|---|
| U5a | `XU_demod_comp` | **TLV3201** push-pull comparator (single, SC70/SOT23-5) | Phase reference (carrier zero-cross). **V+=+5, V−=GND(0)**; rail-to-rail **push-pull output → drives both DG419 `IN`s directly, NO pull-up** (drops the LM393's open-collector pull-up). OUT=`n_demod_ref` HIGH when `v_osc_drive ≥ 0`; 40 ns prop delay → commutation-edge phase error ≪1° at 1 kHz (DG419 logic 1 ≥ 2.4 V / 0 ≤ 0.8 V — full-rail swing clears both). **Input conditioning (required):** TLV3201 is single-supply (V_S ≤ 5.5 V) and **cannot take the raw ±`v_osc_drive`** (±8.5 V on ILC1-1/7). Wire `v_osc_drive`→**`R_pr` 100 kΩ**→`n_pr_in` = (+) input; clamp `n_pr_in` to 0/+5 with a **BAT54S** series dual-Schottky — **centre tap (pin 2) = `n_pr_in`, pin 1 → GND, pin 3 → +5 V** (the series/centre-tapped part is the correct two-rail clamp: D1 GND→node clamps the −ve half, D2 node→+5 clamps the +ve half; a common-cathode **BAT54C** would face both diodes the same way and clamp only one rail — wrong here). R_pr limits clamp current to ≪0.1 mA; (−)=`0`. Add **`R_hyst` ~10 MΩ** `n_demod_ref`→`n_pr_in` for ~±50 mV hysteresis — TLV3201 has none internally, so this gives one clean edge per zero-crossing. |
| U8a | `S_dp1`,`S_dp2` | **Vishay DG419** SPDT (PLUS line) | D(1)=`n_demod_plus`; **S1(3)=`n_node_A_buf`** (selected IN=0, v_osc<0 half), **S2(2)=`n_node_B_buf`** (selected IN=1, v_osc≥0 half); IN(7)=`n_demod_ref`. Supplies **V+(6)=+5, V−(4)=−5, GND(8)=0, VL(5)=+5**. |
| U8b | `S_dm1`,`S_dm2` | **Vishay DG419** SPDT (MINUS line) | D(1)=`n_demod_minus`; **S1(3)=`n_node_B_buf`** (IN=0), **S2(2)=`n_node_A_buf`** (IN=1); IN(7)=`n_demod_ref`. Same supply pins as U8a. |
| — | `R_dp_gnd`,`R_dm_gnd` | 1 % | **1 MΩ** each, `n_demod_plus→0` and `n_demod_minus→0` (DC bias for the switched commons). |
| U2c | `XU_demod_da` | OPA4277 ch | post-chop difference amp. (+)=`n_dda_p`, (−)=`n_dda_m`, out=`n_demod`. Gain = `R_dda_fb/R_dda_inm` = **30**. |
| Rdda | `R_dda_inp`,`R_dda_inm` | **0.1 % matched pair** | 1 kΩ. `R_dda_inp`: `n_demod_plus→n_dda_p`; `R_dda_inm`: `n_demod_minus→n_dda_m`. Match sets CMRR — use a matched pair or a resistor network. |
| Rddag | `R_dda_g1`,`R_dda_g2` | match | **15 k + 15 k in series** (=30 k), `n_dda_p→n_dda_gmid→0`. The mid-tap split is deliberate: a single-resistor SHORT then still leaves 15 k to ground (keeps the diff amp differential instead of going single-ended) — closes the last demod FMEA fault. **Do not substitute a single 30 k.** |
| Rddaf | `R_dda_fb` | match (to Rddag) | **30 kΩ**, `n_demod→n_dda_m`. |
| Rlp,Clp | `R_lp_demod`,`C_lp_demod` | X7R ok | **100 kΩ / 0.22 µF** → ~7.2 Hz 1st-order LP (out of the loop crossover; ~49 dB rejection at the 2 kHz chopper-ripple component). `n_demod→n_demod_dc→0`. |

> **The complement gate is internal — no SN74HC14 needed.** The sim builds two
> *SPST* primitives per line (`S_dp1/S_dp2`, `S_dm1/S_dm2`) and so needs an
> explicit inverted gate `n_demod_refn` (`B_demod_refn`). Each **DG419 is a real
> SPDT that routes from the single `IN` bit internally** (IN=0 → S1, IN=1 → S2),
> so the hardware needs **only `n_demod_ref`** — drop the `U7` SN74HC14 inverter
> the §10/BOM inventory carried for the demod (it was a sim-primitive artifact).
> If you ever build the demod from discrete SPST switches instead, restore it.

> **Why DG419 over the CD4053B.** Two single SPDTs (one per line) instead of one
> triple package: the DG419's **guaranteed break-before-make** means the two
> bridge taps are never momentarily shorted through the switch during
> commutation, and its **charge injection (~3–5 pC typ) and R_on (~25–40 Ω) are
> far lower and tighter** than the CD4053B's (~20 pC, 60–300 Ω). Both halves
> share one `IN` so they commutate together. **Match the two packages** (ideally
> same date code) so R_on/charge-injection track between the plus and minus arms.

> **Tolerances / second-order effects.** Switch R_on appears equally in both arms
> → common-mode, rejected by the matched diff amp; for extra margin scale
> `R_dda_in`→10 k and `R_dda_fb`→300 k (gain still 30). DG419 charge injection
> injects a small, largely-cancelling DC offset that the integrator absorbs (it
> is inside the loop). Keep the two bridge-tap traces
> (`n_node_A_buf`/`n_node_B_buf`) symmetric to the switches so stray-C mismatch
> doesn't unbalance the chop.

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
 v_int_raw ─R_aw_out 10─ v_int ─┬─ D_aw_hi ─►|─ v_clamp_hi (+6 V)
                                └─ D_aw_lo ─|◄─ v_clamp_lo (−3 V)
 ADOPTED window [−3 V, +6 V]  (supersedes the sim −0.5/+4.0; §1, §11-i) —
   v_clamp_hi:  VCC(+10) ─R_chT 100k─ n_chi ─R_chB 150k─ 0   → XU_clh follower → +6.00 V
   v_clamp_lo:  0 ─R_clB 39k─ n_clo ─R_clT 91k─ VEE(−10)     → XU_cll follower → −3.00 V
   (E24, off the regulated ±10 rails; BUFFERED so the ref stays stiff when D_aw conducts)
 diff amp (×1): R_diff1 v_int→n_aw_diff_minus 100k ; R_diff2 v_int_raw→n_aw_diff_plus 100k ;
                R_diff3 n_aw_diff_minus→e_sat 100k ; R_diff4 n_aw_diff_plus→0 100k ;
                XU_aw_diff(+)=n_aw_diff_plus,(−)=n_aw_diff_minus,out=e_sat = v_int_raw−v_int
 R_bc 2.49k e_sat→n_int_minus   (= R_int/20 → unwinds 20× faster than wind-up)
```
| RefDes | netlist | part | value |
|---|---|---|---|
| U3b | `XU_aw_diff` | OPA4277 ch | unity diff amp → `e_sat` |
| Raw | `R_aw_out` | 1 % | 10 Ω |
| Daw | `D_aw_hi`,`D_aw_lo` | **BAT54** (low V_F) or 1N4148 | clamp diodes (`stiff_clamp` ⇒ sharp-knee low-Rs). Clamp to **`v_clamp_hi`=+6 V / `v_clamp_lo`=−3 V** (adopted window, below). |
| Rdiff | `R_diff1..4` | 0.1–1 % match | 100 kΩ ×4 |
| Rbc | `R_bc` | 1 % | **2.49 kΩ** (E96; = R_int/20) |
| Rch | `R_chT`/`R_chB` | 1 % | **100 kΩ / 150 kΩ** — +6 V divider off VCC(+10) (E24, exact) |
| Rcl | `R_clB`/`R_clT` | 1 % | **39 kΩ / 91 kΩ** — −3 V divider off VEE(−10) (E24, exact) |
| U_clh,U_cll | `XU_clh`,`XU_cll` | OPA4277 ch | unity followers buffering the two dividers → stiff `v_clamp_hi`/`v_clamp_lo` (the 2 remaining channels of the 4-quad count, §10) |

> **Clamp window = [−3 V, +6 V] (adopted, §11-i) — NOT the sim −0.5/+4.0.** The
> sim macromodel used `v_clamp_hi=+4.0`, `v_clamp_lo=−0.5`; the **shipping window
> is widened to [−3, +6]** so the high rail clears the HIGH watchdog (+3.7 V) and
> the cold-start `v_int` ride with margin (the clamp must not bite during a
> legitimate ride), and the low rail clears the −0.85 V loss-of-authority rail.
> Generated as **buffered dividers off the regulated ±10 V rails** (above) — a
> clamp ceiling needs no better than rail tolerance, so no shunt reference is
> required. *(Earlier text said "LM4040 shunt refs"; the buffered-divider form
> here is the realisation — §1 updated to match.)*

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
latches. The hardware below realises each `B`-source as a window comparator +
precision reference, each RC qualifier as a literal RC (the fast LOW side timed
by its pull-up on the open-collector node; the slow HIGH side a pull-up + series
`R_hiq` into the cap, read by a CMOS Schmitt for a clean, leakage-immune τ — see
§8a), each pseudo-latch as a **CMOS SR latch**, and the logic products via the
comparators' **open-collector wired-AND** (plus, at most, a gate or two). The
combinational/latch logic runs at **+3.3 V with 74HC parts** (74HC works
2–6 V — no need for CD4000-series). **References** (1.5/0.5/3.7 V + the per-tube
over-power refs) come from one **LM4040-4.096 shunt** + resistor dividers
(§8c gives the E-series values), buffered if loaded. Suggested packages:
**U9 = LM339 quad comparator** (arm, low, high, over-power),
**U10 = 74HC279 quad SR latch** (arm + supervisor-trip + disconnect latches,
3 of 4 channels), **U11 = 74HC14 hex Schmitt** (flag clean-up/inversion + qualifier
thresholds), and **U12 = 74HC10 triple 3-input NAND** for the over-power
disconnect AND (§8b). Per-block netlists are in §8a/§8b.

**LM339 (U9) power rails — V+ (pin 3) = +12 V or +15 V (whichever rail you
have), GND (pin 12) = 0 V (system ground).** The open-collector outputs are
**pulled up to +3.3 V** (one ~4.7–10 kΩ pull-up per used node) → 0/+3.3 logic
for the 74HC. Because the output is open-collector, **the comparator supply and
the logic level are independent** — pick V+ for input headroom, the pull-up for
the logic family. (**+15 V is already on the board** as the Wien master rail
§1/VR4; the **+3.3 V logic rail** is a small LDO off +5 V.) Two input-range points:
- **Generous V+ (+12/+15) buys fault headroom.** The LM339's input common-mode
  range reaches ≈ V+ − 1.5 V, so at +12/+15 it cleanly senses `v_int` across its
  whole hardware range — up to the **+6 V** clamp ceiling (§1 [−3 V, +6 V]
  window), and even an op-amp railed to +10 V stays well inside range with no
  phase reversal. (A +5 V supply would cap sensing at ≈ +3 V and miss the
  HIGH/over-drive region — hence the move up.)
- **`v_int` also swings *negative*** — to the −3 V clamp floor — below the GND
  pin (0 V). The output stage pins GND at 0 V to get a 0 V logic-low, so the part
  still can't sense below ground: feed the three supervisor comparators from one
  **shared clamped copy of `v_int`** — series `R` (~100 kΩ) + a **BAT54 Schottky
  to GND**, bounding it to ≳ −0.2 V. Lossless: every supervisor threshold is
  ≥ 0.5 V, so a railed-low `v_int` still reads ≈ 0 V < 0.5 V and trips LOW.
  (Over-power comparator U9d senses a *positive* envelope — build the §8b FWR to
  output +|drive| — so no clamp there.) *Alternative:* a true ±12/±15 split
  (GND pin = −V) removes the input clamp entirely, but then every output swings
  to −V and needs level-shifting up to 0/+3.3 — trading one shared input clamp
  for four output clamps, so the GND = 0 V form above is simpler.

**Wired-AND / wired-OR (saves the AND/OR gates).** Open-collector outputs tied to
one pull-up form wired logic: the node is HIGH only when **every** output is
released, and any output pulling low drags it low. So tying outputs together is a
logic-AND of their *high-true* levels (equivalently a wired-OR of the active-low
faults). Set each comparator's polarity so it **releases (high) when its
condition is true**, and the gate disappears into the wiring. **One caveat:** the
LOW and HIGH qualifiers have different time constants (1 ms vs per-tube τ), so
**each RC must sit on its own comparator output, before the wired node** — you
can't qualify after combining (this is explicit in the §8a netlist). The
arm-gating is the `Q_arm` MOSFETs and the `(lo OR hi)` OR is the trip-latch
diode-OR, so the discrete logic reduces to the 74HC279 latch + a 74HC14 + (for
§8b) one 74HC10.

### 8a. Dual-sided V_int fault supervisor → oscillator cutoff

Watches the integrator output both ways (every overheating passive fault rails
`v_int` to a clamp). Reference threshold nodes: `v_ref_arm`=1.5, `v_ref_lo`=0.5,
`v_ref_hi`=3.7 (off the LM4040 divider).

```
* ===================== S8a SUPERVISOR — NETLIST =====================
* Nets: 0=GND  +3V3=logic  +VC=+12/+15 (LM339 V+)  +5=n_v_led  VREF=4.096
* 2-terminal:  RefDes  nodeA  nodeB  ; value     (diode: anode  cathode)
* IC:          RefDes  PART  pin=net …           (every LM339: V+=+VC pin3, GND=0 pin12)
*
* -- 4.096 V reference + threshold dividers (0.1 % R; values §8c) --
R_refb   +5    VREF             ; 3k3   LM4040 bias (~0.9 mA)
U_ref    LM4040-4.096   K=VREF  A=0
R_armt   VREF  v_ref_arm        ; 30k1  } v_ref_arm = 1.500 V
R_armb   v_ref_arm  0           ; 17k4  }
R_lot    VREF  v_ref_lo         ; 76k8  } v_ref_lo  = 0.500 V
R_lob    v_ref_lo  0            ; 10k7  }
R_hit    VREF  v_ref_hi         ; 4k42  } v_ref_hi  = 3.700 V
R_hib    v_ref_hi  0            ; 41k2  }
*
* -- shared clamped copy of v_int (LM339 can't sense below its 0 V GND pin) --
R_vint   v_int  v_int_cl        ; 100k
D_vint   0  v_int_cl   BAT54    ; anode 0, cathode v_int_cl → clamps v_int_cl ≥ −0.2 V
*
* -- ARM: capture comparator → SR latch (full-rail n_armed, no diode drop) --
U9a      LM339  in+=v_ref_arm  in-=v_int_cl  out=n_arm_oc   ; OC sinks LOW when v_int>1.5
R_puarm  +3V3  n_arm_oc         ; 10k
U10.1    74HC279  Sbar=n_arm_oc  Rbar=n_por  Q=n_armed      ; latches "armed"
U11d     74HC14   in=n_armed  out=n_armed_b                 ; 279 has no Qbar → invert here
*
* -- wired-AND arm gate: hold the LO/HI comparator nodes low until armed --
Q_arm_lo 2N7002  G=n_armed_b  D=n_lo      S=0
Q_arm_hi 2N7002  G=n_armed_b  D=n_hi_raw  S=0
*
* -- LOW trip (fast 1 ms): the PULL-UP is the timer, cap on the OC node --
U9b      LM339  in+=v_ref_lo  in-=v_int_cl  out=n_lo        ; OC releases when v_int<0.5
R_loq    +3V3  n_lo             ; 1k    pull-up = 1 ms timer
C_loq    n_lo  0                ; 1µF   on the OC node
U11b     74HC14  in=n_lo  out=n_lo_int_L                    ; active-LOW LOW flag
*
* -- HIGH trip (slow per-tube τ): 10k pull-up is the source, R_hiq series into cap --
U9c      LM339  in+=v_int_cl  in-=v_ref_hi  out=n_hi_raw    ; OC releases when v_int>3.7
R_puhi   +3V3  n_hi_raw         ; 10k    the current source
R_hiq    n_hi_raw  n_hi_q       ; per-tube 300k/400k/1M2/1M3  (§8a-i)
C_hiq    n_hi_q  0              ; 1µF C0G/film     τ = R_hiq·C_hiq
U11c     74HC14  in=n_hi_q  out=n_hi_int_L                  ; active-LOW HIGH flag
*
* -- TRIP latch: diode-OR the active-low flags into the active-low Sbar --
D_trlo   S_trip  n_lo_int_L  1N4148    ; anode S_trip, cathode flag
D_trhi   S_trip  n_hi_int_L  1N4148
R_puset  +3V3  S_trip           ; 100k   S_trip = active-low (lo OR hi)
U10.2    74HC279  Sbar=S_trip  Rbar=n_por  Q=n_latch        ; latches the trip
*
* -- oscillator cutoff + fault LED --
Q_cut    2N7002  G=n_latch  D=np  S=0   ; shorts the Wien +FB node np (§2) → kills the 1kHz carrier
R_fled   +3V3  n_fled_a         ; 1k
D_fled   n_fled_a  n_fled_k  LED ; FAULT LED
Q_fled   2N7002  G=n_latch  D=n_fled_k  S=0
*
* -- power-on reset (resets every 74HC279 latch at power-up; starts disarmed) --
R_por    +3V3  n_por            ; 100k
C_por    n_por  0               ; 1µF   n_por: 0 → +3V3, ~100 ms reset window
```

**Notes (rationale not obvious from the netlist):**
- **LOW is a fast glitch filter** (1 ms, pull-up-timed, asymmetric fast reset) — its forward-gain faults over-drive ~50× and heat faster than τ_th, so speed beats integration. **HIGH is time-qualified** (per-tube τ, §8a-i) so the cold-start `v_int` ride doesn't false-trip.
- **`v_int_cl` clamp is lossless:** every threshold is ≥ 0.5 V, so a railed-low `v_int` (down to the −3 V floor) still reads ≈ 0 V < 0.5 V and trips LOW correctly; the clamp only protects the LM339 input.
- **Arm/trip/disconnect latches are three channels of one 74HC279** (the §8b disconnect latch is `U10.3`). The 74HC279 has **no Q̄**, so `U11d` inverts `n_armed` for the gate.
- **`Q_arm` gates the comparator *output nodes*** (upstream of the HIGH qualifier RC): pre-arm they're held at 0, so neither qualifier can charge; this is the `armed AND fault` wired-AND with no AND gate.
- **Cutoff (`Q_cut`)** is the hardware form of the sim's `src_gate` (carrier × 0 on latch). Its drain ties to the **Wien `np` node in §2** (cross-sheet net) — shorting the positive-feedback / non-inverting input to GND collapses the loop gain and stops the 1 kHz carrier, so the filament drive goes to zero (cold-safe). The Wien feed Rs (R1/R2 = 10 k) limit the short to <0.4 mA. *(Alternative if you prefer a hard kill: make `Q_cut` a high-side load-switch gating +15 V to the NE5532 instead — but that's a P-FET to the supply, not the low-side N-FET shown.)*

LOW = loss-of-authority / forward-gain faults (atten/buffer; loop fights to the
low rail, ms-fast). HIGH = sense/setpoint/bridge-ref faults (loop winds to max
drive; time-qualified).

#### 8a-i. Per-tube HIGH-side qualifier `R_hiq` (with `C_hiq`=1 µF)

`R_hiq` is the **series resistor from the (pulled-up) comparator OC node into
`C_hiq`** (§8a) — the 10 kΩ pull-up sources the charge, and since `R_hiq` ≫ 10 kΩ
the `τ = R_hiq·C_hiq = t_fault_hi` holds (≤3 % charge-edge offset from the 10 kΩ),
so **`R_hiq = t_fault_hi / 1 µF`**:

| tube | `t_fault_hi` | `R_hiq` (C_hiq=1 µF) |
|---|---|---|
| IV-18 | 0.3 s | **300 kΩ** |
| IV-6 | 0.4 s | **400 kΩ** |
| ILC1-1/7 | 1.2 s | **1.2 MΩ** |
| ILC1-1/8 | 1.3 s | **1.3 MΩ** |

`C_hiq` **must be C0G/film** (value-stable): if it derates, τ shrinks toward the
false-trip floor (`vint_ride.py` floors 205/269/867/926 ms). `R_loq`/`C_loq`
(LOW, 1 ms) are not value-critical (the arm and trip latches are now 74HC279
channels — no timing caps).

### 8b. Over-power: flat-clamp + authority-gated disconnect

The supervisor's cutoff hits the oscillator **upstream** of a stuck output
buffer, so it can't isolate *that* fault — hence a second layer on the drive
node. It **reuses the supervisor's `n_armed` and `S_trip`** (= active-low
`(lo OR hi)`) (so the supervisor must be present).

```
* ===================== S8b OVER-POWER — NETLIST =====================
* reuses S8a nets: n_armed, S_trip (= active-low (lo OR hi)), n_por, +VC, +3V3
* the FWR runs on the ±10 OPA4277 rails (vcc_buf/vee_buf); U9d on +VC/0
*
* -- per-tube bidirectional flat clamp on v_osc_drive to ±V_cl (§8b-i) --
*    +V_cl: TLV431 shunt set by divider; −V_cl: unity inverter of +V_cl.
*    ILC1-1/7 V_cl > rail → clamp idle there (rail-clip + disconnect bound it).
R_clpb   +15V  p_Vcl            ; TLV431 bias (~1 mA); +15V for ILC1-1/7 headroom
U_clp    TLV431  K=p_Vcl  R=n_clref  A=0
R_clp1   p_Vcl  n_clref         ; } V_cl = 1.24·(1+R_clp1/R_clp2)   values §8b-i
R_clp2   n_clref  0             ; }
XU_cln   OPA4277  in+=0  in-=n_clni  out=n_Vcl    ; −V_cl = −(+V_cl)
R_cli1   p_Vcl  n_clni          ; } equal Rs → gain −1
R_cli2   n_clni  n_Vcl          ; }
D_clp    v_osc_drive  p_Vcl  1N5711   ; clamps v_osc_drive ≤ +V_cl
D_cln    n_Vcl  v_osc_drive  1N5711   ; clamps v_osc_drive ≥ −V_cl
*
* -- precision full-wave rectifier on v_bridge_top → +|drive| --
*    validated sim FWR; D1op/D2op REVERSED vs the sim so the output is POSITIVE
*    (flipping both rectifier diodes flips the sign — confirm in sim/bench)
R1op     v_bridge_top  nAop     ; 10k
R2op     nAop  nBop             ; 10k
XA1op    OPA4277  in+=0  in-=nAop  out=nO1op
D1op     nBop  nO1op  1N5711    ; (reversed vs sim → +output)
D2op     nO1op  nAop  1N5711
R3op     v_bridge_top  nCop     ; 10k
R4op     nBop  nCop             ; 5k
R5op     nCop  nAbsop           ; 10k
XA2op    OPA4277  in+=0  in-=nCop  out=nAbsop     ; = +|v_bridge_top|
R_env    nAbsop  n_envop        ; 100k  } 10 ms envelope
C_env    n_envop  0             ; 0.1µF }
*
* -- over-power comparator (per-tube ref §8b-i/§8c) --
U9d      LM339  in+=n_envop  in-=v_ref_op  out=n_opf    ; OC releases when |drive|>v_ref_op
R_puopf  +3V3  n_opf            ; 10k
*
* -- authority-gated disconnect: DISC = n_opf AND n_armed AND (lo OR hi) --
U11e     74HC14  in=S_trip  out=n_lohi                  ; active-HIGH (lo OR hi)
U_dnand  74HC10  a=n_armed  b=n_opf  c=n_lohi  y=S_disc ; 3-in NAND → low when all 3 high
U10.3    74HC279  Sbar=S_disc  Rbar=n_por  Q=n_disc_op  ; latches the disconnect
*
* -- bistable-relay drive + series disconnect contact --
Q_coil   AO3400  G=n_disc_op  D=n_coil  S=0    ; pulse the relay SET coil
K_coil   +VC  n_coil   "relay SET coil"        ; ~7 ms actuation (t_relay)
D_fly    n_coil  +VC   1N4148                  ; coil flyback (cathode +VC)
K_cont   v_osc_drive  v_bridge_top  "relay contact"  ; latches OPEN on SET; replaces R_series
```

**Notes:**
- **Flat-clamp** bounds the *instantaneous* drive to ±`V_cl` so the fault peak is independent of relay lag; `V_cl = k_clamp·V_op·√2·(R_op+R_sense)/R_op`, k_clamp=1.5 (§8b-i).
- **Authority discriminator:** the `(lo OR hi)` term distinguishes a *commanded* over-power (warm-up — `v_int` mid-range, no disconnect) from a *fault* over-power (`v_int` railed → disconnect). It reuses the supervisor's `S_trip` (= active-low `(lo OR hi)`) and `n_armed`.
- **Clamp + disconnect compound:** the clamp caps the *peak rate*, the bistable disconnect caps the *dwell* — the relay opens cold-safe and stays open with no holding current (replaces `R_series`, §4).
- `XA1op`/`XA2op`/`XU_cln` are OPA4277 channels (in the §10 quad count); the FWR sign is set by the `D1op`/`D2op` orientation — drawn here for `+|drive|`.

#### 8b-i. Per-tube clamp & over-power references

`V_cl = 1.5·V_op·√2·(R_op+R_sense)/R_op` ; `v_ref_op = 1.3·V_op`:

| tube | V_op | R_op | R_sense | **`V_cl`** (±, clamp) | **`v_ref_op`** (over-power) |
|---|---|---|---|---|---|
| ILC1-1/7 | 5.0 | 25 | 4.7 | **12.6 V** † | **6.50 V** |
| IV-6 | 1.0 | 20 | 5.1 | **2.66 V** | **1.30 V** |
| IV-18 | 1.0 | 100 | 10 | **2.33 V** | **1.30 V** |
| ILC1-1/8 | 1.2 | 8 | 2.0 | **3.18 V** | **1.56 V** |

† ILC1-1/7's `V_cl` (12.6 V) sits **above the ±10 V rail**, so for that tube the
rail clip + the disconnect (not the shunt clamp) bound the fault; the TLV431 is
still fitted but only acts under a rail-overshoot corner. The low-V tubes are
where the flat-clamp does the work.

**TLV431 +V_cl generator values** (`V_cl = 1.24·(1+R_clp1/R_clp2)`, V_ref=1.24 V;
the −V_cl rail is the `XU_cln` unity inverter, equal 1 kΩ Rs; `R_clpb` biases the
shunt from +15 V at ~1 mA). E24/E96 from `clamp_refs_eseries.py`:

| tube | V_cl | **E24** `R_clp1`/`R_clp2` | **E96** `R_clp1`/`R_clp2` | `R_clpb` (+15 V) |
|---|---|---|---|---|
| ILC1-1/7 ‡ | 12.6 | 22 k / 2.4 k | 18.7 k / 2.05 k | 2.4 k |
| **IV-6** | 2.66 | **15 k / 13 k** | 10.7 k / 9.31 k | **12 k** |
| IV-18 | 2.33 | 16 k / 18 k | 16.5 k / 18.7 k | 13 k |
| ILC1-1/8 | 3.18 | 47 k / 30 k | 21.5 k / 13.7 k | 12 k |

The divider total is held ~20–80 kΩ so its current (≲130 µA) doesn't starve the
TLV431 cathode — `R_clpb` then sets ~1 mA of shunt current with the divider
drawing only a fraction. ‡ ILC1-1/7's divider runs a bit hotter (516 µA) but it
never actually clamps, so the ~0.5 mA left for the shunt is fine.

> Clamp + disconnect **compound**: the clamp caps the *rate* (instantaneous
> peak), the disconnect caps the *dwell* (time at temperature). With the
> **per-tube `t_fault_hi`** (→ `R_hiq` table §8a-i), the worst over-driving fault
> (botref_short) peaks **≤871 K with ZERO dwell >900 K** (≤162 ms >850 K), then
> cold-safe; **zero false trips** on cold-start / restart / brownout
> (`confirm_pertube.py`). *(History: the default 3 s watchdog let botref_short
> sit **922 K for ~2.3 s >900 K** — `dwell_botref.py` / `t_fhi_sweep.md`; the
> per-tube watchdog removes that. The old HANDOFF "≤899 K / never 900 K" was the
> IV-18-only XU_buf-fault dwell, not the worst.)* Each `t_fault_hi` = (cold-start
> `v_int` ride >3.7 V)/0.916 × ~1.4 (`vint_ride.py`). **Lock per-tube `k_clamp`/
> `t_relay` and re-confirm `t_relay` against the chosen latching relay's
> datasheet actuation time, and pick each TLV431's `V_cl` set-resistor, before a
> production run.**

### 8c. Threshold reference generation (from one LM4040-4.096)

All comparator thresholds (§8a arm/LOW/HIGH + §8b over-power) divide down from a
single **LM4040-4.096** shunt reference (`Vref`=4.096 V, A-grade ±0.1 %), each
through a two-resistor divider `Vref─[Rtop]─node─[Rbot]─0`,
`V = 4.096·Rbot/(Rtop+Rbot)`. Optimal E-series pairs (`safety_refs_eseries.py`,
total held 40–100 kΩ → ~41–102 µA ref load, node `Rth` 4–23 kΩ for the LM339
inputs). **Use 0.1 % resistors** — the *ratio* sets the threshold, so 0.1 % parts
give the nominal below; thresholds are fault windows with built-in margin, so the
small E-series residuals are immaterial.

| threshold | target | **E96** Rtop/Rbot → V (err) | **E24** Rtop/Rbot → V (err) |
|---|---|---|---|
| `v_ref_lo` (LOW, all) | 0.500 | 76.8 k / 10.7 k → 0.5009 (+0.18 %) | 36 k / 5.1 k → 0.5083 (+1.65 %) |
| `v_ref_arm` (ARM, all) | 1.500 | 30.1 k / 17.4 k → 1.5004 (+0.03 %) | 62 k / 36 k → 1.5047 (+0.31 %) |
| `v_ref_hi` (HIGH, all) | 3.700 | 4.42 k / 41.2 k → 3.6991 (−0.02 %) | 5.1 k / 47 k → 3.6950 (−0.13 %) |
| `v_ref_op` (IV-6 / IV-18) | 1.300 | 49.9 k / 23.2 k → 1.3000 (−0.003 %) | 43 k / 20 k → 1.3003 (+0.02 %) |
| `v_ref_op` (ILC1-1/8) | 1.560 | 27.4 k / 16.9 k → 1.5626 (+0.17 %) | 39 k / 24 k → 1.5604 (+0.02 %) |
| `v_ref_op`/2 (ILC1-1/7) ‡ | 3.250 | 13.3 k / 51.1 k → 3.2501 (+0.003 %) | 16 k / 62 k → 3.2558 (+0.18 %) |

‡ **ILC1-1/7's over-power threshold is 1.3·V_op = 6.50 V, above `Vref`** — not
divider-realisable. Instead **halve the FWR envelope** (`n_envop` through a
matched 2:1 divider, e.g. 2×10 k) and compare against a **3.25 V** reference
(the row above); the trip point is then 2·3.25 = 6.50 V as required. The other
tubes compare the envelope directly (no pre-divide). The supervisor refs and the
two low-V over-power refs are shared/global; only `v_ref_op` (+ the ILC1-1/7
envelope divider) is per-tube. The `V_cl` flat-clamp levels (§8b-i) are **not**
from this divider — they are each set by the TLV431's own 1.24 V reference and
set-resistor.

---

## 9. Per-tube variant table (the parts that change)

### 9a. Signal-path per-tube parts

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
> `R_in_vgain`=28 Ω. Five signal-path per-tube items: 3 bridge refs + attenuator
> + (IV-18 only) R_in_vgain.

### 9b. Protection per-tube parts (the §8 values, gathered here)

The protection chain also varies per tube — these live with their derivations in
§8 but are collected here so the full per-tube BOM is in one place:

| element | netlist | IV-18 | IV-6 | ILC1-1/7 | ILC1-1/8 | source |
|---|---|---|---|---|---|---|
| `R_hiq` (HIGH watchdog, `C_hiq`=1 µF) | `R_hiq` | **300 kΩ** | **400 kΩ** | **1.2 MΩ** | **1.3 MΩ** | §8a-i |
| `t_fault_hi` (the τ it sets) | `t_fault_hi` | 0.3 s | 0.4 s | 1.2 s | 1.3 s | §8a-i |
| `v_ref_op` (over-power threshold) | `B_opf` ref | 1.30 V | 1.30 V | **6.50 V** † | 1.56 V | §8b-i / §8c |
| `V_cl` (± flat-clamp, TLV431) | `V_clp/cln_op` | 2.33 V | 2.66 V | 12.6 V ‡ | 3.18 V | §8b-i |

† ILC1-1/7's over-power ref is > the 4.096 V LM4040, so it's realised by halving
the FWR envelope and comparing against **3.25 V** (extra matched 2×10 k divider on
`n_envop` — an ILC1-1/7-only part); see §8c. ‡ ILC1-1/7's `V_cl` exceeds the rail
(rail-clip + disconnect dominate — §8b-i). The supervisor refs `v_ref_arm`/`lo`/`hi`
(1.5/0.5/3.7 V) and the two low-V `v_ref_op` (1.30 V) are **shared/global**, not
per-tube; their divider values are in §8c.

---

## 10. Op-amp / comparator channel inventory (CORRECTED)

Recounted from the **shipping** netlist (`switch_demod=True,
overpower_protect=True`) — this **supersedes** the BOM's "3 quads + 1
comparator", which predates protection and still counts the removed `XU_log`.

**OPA4277 op-amp channels (16):**
`XU_atten_buf1`(NEW), `XU_atten_buf, XU_vgain, XU_s2, XU_buf` (5) · `XU_buf_A,
XU_buf_B, XU_demod_da` (3) · `XU_int, XU_aw_diff, XU_led_buf` (3) ·
**clamp-window followers `XU_clh, XU_cll`** (2, §7) · **over-power FWR
`XA1op, XA2op`** (2) + **clamp −V_cl inverter `XU_cln`** (1, §8b)
= **16 channels → 4 quad packages (U1–U4)** (fully populated, 0 spare), *up from
3 quads.* The clamp-window buffers take the last two channels — if you'd rather
keep spares, generate the ±-window with shunt refs instead of buffered dividers.
The **Wien op-amp is NOT an OPA4277** — it is a dedicated **NE5532 (U6) on
±15 V** (§2). Net change vs the original 3-quad BOM: −`XU_log` (removed by
pre-log sensing), +`XU_atten_buf1` (2-stage divider), Wien moved to its own
package — i.e. the extra quad is driven by the over-power FWR pair + divider
buffer, not the Wien.

**Comparators & logic (explicit in §6/§8):** demod gate `XU_demod_comp`
(**TLV3201**, push-pull, single +5 — input-conditioned per §6) · supervisor
arm/LOW/HIGH + over-power = **4 channels → 1× LM339 quad (U9)** (V+=+12/+15 V/
GND=0 V, open-collector outputs pulled to **+3.3 V**; rails justified in §8a) ·
digital latch = **74HC279 quad SR latch (U10)** — arm + supervisor-trip +
disconnect latches in one package (§8a). The AND/OR products are done by the
**`Q_arm` MOSFET wired-AND + a 1N4148 diode-OR** (§8a); the only logic ICs are
**74HC14 hex Schmitt (U11)** (flag clean-up/inversion + qualifier thresholds) and
**74HC10 (U12)** for the §8b disconnect AND. **The CD4000-series
(CD4043/4081/4071) is dropped** — 74HC at +3.3 V replaces it. **No SN74HC14** as a
demod inverter either — the demod's complementary gate is
internal to each DG419 SPDT (§6); the inverter the earlier inventory listed was a
sim-primitive artifact and is **dropped**.

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
  `v_fault_trip_hi`=3.7 / `t_fault_hi` **per-tube 0.3/0.4/1.2/1.3 s**
  (IV-18/IV-6/ILC1-1/7/ILC1-1/8). Still **re-confirm `t_relay`
  against the chosen latching relay's datasheet** and pick the TLV431 per-tube
  `V_cl` resistor (§8b) at PCB time.
- **(i) Clamp-ref window — ✅ ADOPTED [−3 V, +6 V]** via **buffered ±10 V-rail
  dividers** (§7: +6 V=100 k/150 k off VCC, −3 V=39 k/91 k off VEE, each on an
  OPA4277 follower), wider than sim −0.5/+4.0 for corner / low-power headroom and
  to clear the +3.7 V HIGH watchdog. *(The window values live in §7 now, not just
  §1/§11 — that gap is what let a build use the sim −0.5/+4.0.)*
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
`v_ap_drive`. Sense: `node_A/B`→`n_node_A_buf/B_buf`→(DG419 ×2)→
`n_demod_plus/minus`→`n_demod`→`n_demod_dc`→`n_int_minus`→`v_int_raw`→
`v_int`→`v_int_buf`→(H11F LED)→ sets `R_h11f` → closes loop.
Protection taps: `v_int` (supervisor), `v_bridge_top`/`v_osc_drive`
(over-power). Rails: `vcc_buf`(+10), `vee_buf`(−10), `n_v_led`(+5).

---

## 13. Power budget & supply tree (USB-C bus-powered)

**Input — USB-C, 5 V, passive sink (no PD).** Rd (5.1 kΩ) on CC1/CC2; VBUS = 5 V
at **up to 3 A** per the source's Rp advertisement. No PD controller. (PD@20 V is
reserved for the full multi-function VFD driver, where one high rail bucks down
to everything and shrinks the anode-boost ratio — out of scope for this board.)

### 13a. Rail tree

| rail | source | feeds |
|---|---|---|
| **+5 V** | **VBUS direct** (ferrite + bulk cap; no converter) | logic (74HC), LM339 pull-ups, LM4040 ref, H11F LED, TLV3201 |
| **+15 V** | **boost** from +5 V | NE5532 Wien; source for +12 / +10 LDOs |
| **−15 V** | **inverting** buck-boost from +5 V | source for −10 LDO |
| **+12 V** | **LDO** from +15 V | G5V-1 relay coil, LM339 |
| **±10 V** | **LDO** from ±15 V | all 16 OPA4277 channels + the class-AB output stage |

The negative rail is inherent to the bipolar signal chain, so the −15 inverter is
unavoidable. The +15→±10 LDO drop is mildly wasteful (≈⅓ on that branch) but
**chosen for simplicity** — at USB-C power levels it only costs heat (§13c), and
it avoids re-tuning the Wien clamp that a direct-switched ±10 rail would force.

### 13b. Measured ±10 rail current (per tube)

From `rail_budget.py` — `regulator.py` instrumented (`R_sense_vcc/vee`), steady
state, 16-channel board, **THD-validated** (ILC1-1/7 −35.2 dB ≈ the validated
−34.7 dB → the operating point and hence these currents are the real ones; the
`instrument_power` ammeters don't perturb the drive):

| tube | THD | P_fil | +10 mean / peak | −10 mean / peak |
|---|---|---|---|---|
| IV-18 | −57 dB | 10 mW | 22 / 29 mA | 25 / 31 mA |
| **IV-6** | −54 dB † | 50 mW | **40 / 85 mA** | **43 / 87 mA** |
| ILC1-1/8 | −52 dB | 179 mW | 85 / 228 mA | 88 / 230 mA |
| ILC1-1/7 | −35 dB | 1001 mW | 111 / 311 mA | 114 / 314 mA |

The **peaks are the 1 kHz carrier** — sourced by the ±10 LDO output caps, not the
converters (which see the mean). † IV-6's behavioural-demod run reads −54 dB; the
shipping switched-demod (DG419) THD is the validated **−47.5 dB** (chopper-ripple
floor) — same operating point, same currents.

### 13c. VBUS budget & heat (per tube, G5V-1 relay = 150 mW)

VBUS current at 5 V = boost-in (+15 branch) + inverter-in (−15 branch) + +5 direct
(η_boost ≈ 0.88, η_inv ≈ 0.85). LDO heat = drop × branch current.

| tube | **VBUS @ 5 V** | input power | ±10 LDO heat |
|---|---|---|---|
| IV-18 | ~0.28 A | ~1.4 W | ~0.2 W |
| **IV-6 (this board)** | **~0.41 A** | **~2.0 W** | **~0.45 W** |
| ILC1-1/8 | ~0.72 A | ~3.6 W | ~0.85 W |
| ILC1-1/7 | ~0.90 A | ~4.5 W | ~1.1 W |

**IV-6 sits at ~0.41 A (14 % of a 3 A port)** with ~0.45 W of linear heat — well
within budget, no heatsinking of the LDOs needed. The boost (~64 mA / 1 W out)
and inverter (~51 mA / 0.76 W out) are small, easy parts.

> ⚠ **If this board is ever populated for ILC1-1/7**, the ±10 LDOs dissipate
> ~1.1 W (and VBUS ~0.9 A) — there, switch +10 directly (a buck) or heatsink.
> The low-V tubes (the realistic builds here) don't need it.

Harnesses: `rail_budget.py` (per-tube measured rail current + THD),
`clamp_refs_eseries.py` (TLV431 / clamp-window dividers), `safety_refs_eseries.py`
(LM4040 threshold dividers).
