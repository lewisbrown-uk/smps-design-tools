# TEST PLAN — VFD filament regulator prototype bring-up

**Principles.** (1) **Stage by risk** — the tube filament is the fragile,
expensive, easily-cooked part, so it is the *last* thing connected, only after
the loop and especially the **protection** are proven on disposable loads.
(2) **Validate against the sim** — `regulator.py` already predicts every figure
(THD, regulated point, rail currents §13, protection timing §8); the bench job is
to *confirm the model* and pin the handful of things it couldn't (the §11-j
carry-ins). Pass/fail numbers below are the sim's predictions.

---

## 1. Filament stand-ins

A plain fixed resistor **cannot close the loop** — the loop regulates R *by
changing power*, so a load that doesn't respond to power gives the integrator no
way to null (it drifts/rails). Three loads for three jobs:

| stand-in | gives | use for | caveat |
|---|---|---|---|
| **Fixed precision R = R_op** (100/20/25/8 Ω) | clean linear load | open-loop blocks, THD, bias, demod transfer | loop won't *close* |
| **Small incandescent bulb** | real hot-wire R(T) + thermal mass | proof the closed loop captures & regulates | τ/tempco ≠ tube → re-trim bridge refs, don't expect the tuned overshoot |
| **HIL emulator** (§6) | the *exact* R(T)/τ + fault injection | validating the tuned loop and protection vs the battery | MOSFET-R distortion (fine for dynamics, not THD) |

---

## 2. Stage 0 — power section only (no analog)

Bring the board up with **nothing downstream of the rails** populated/loaded.

| check | expected (IV-6) | ref |
|---|---|---|
| VBUS current | ~0.41 A @ 5 V (≤ source advert) | §13c |
| +15 / −15 | +15.0 / −15.0 V, ripple acceptable | §14b |
| ±10 (LM317/337) | ±10.05 V; LDO heat ~0.45 W | §14b |
| +5 logic = VBUS | present, decoupled | §14a |
| relay coil | 5 V, ~30 mA when energised | §14c |
| no rail shorts / thermal runaway | — | — |

**Gate:** all rails in spec and stable before connecting any signal block.

---

## 3. Stage 1 — open-loop blocks into a fixed R_op

Break the loop (or hold `v_int` with an external source) and exercise each block.

| block | measure | expected | ref |
|---|---|---|---|
| Wien | f, amplitude, THD | **1.000 kHz, 3.63 V_pk (2.57 V_rms) @ 25 °C** | §2 |
| Wien tempco / death | amplitude vs temp | −0.45 %/°C; oscillation **dies >60–70 °C** | §2, §11-j |
| Attenuator + VGA | `v_atten` per tube | §9 table (0.885/1.46/6.77/1.72 mV_rms) | §9 |
| **H11F R vs I_LED** | inject I_LED, read R_DS | map the curve at the operating point | §11-j |
| Class-AB | Iq, drive THD, swing | **Iq ≈ 20 mA**; THD per §13b into R_op | §4 |
| Bridge + demod | force R≠target, read `n_demod_dc` | correct sign/gain (×30), phase-locked to carrier | §5/§6 |
| Rail currents | ±10 mean/peak | §13b per-tube table | §13b |

---

## 4. Stage 2 — close the loop on a thermal stand-in

First the **bulb** (cheap "is it alive"), then the **HIL emulator** (§6) for the
real dynamics.

| check | expected | ref |
|---|---|---|
| capture | `v_int` rises past 1.5 V, loop locks | §8a |
| regulated point | **R_fil → R_op** (i.e. emulator T → 800 K), stable | TUBES |
| cold-start ride | `v_int` overshoot clears in ~1 s, no false trip | §8a-i |
| cold-start T overshoot | ≤ **+7.4 K** (ILC1-1/8 worst, accepted) | gating |
| THD at operating point | matches §13b (IV-6 −47.5 dB shipping) | §13b |
| step response | settles per `tau_th` (0.19–0.62 s), stable margin | TUBES |

The HIL run should overlay the validated battery; divergence flags a model error.

---

## 5. Stage 3 — protection, by fault injection (still no tube)

The point of the dummy load: **prove every protection path before a tube is near
it.** Inject electrically; no thermal emulation needed for most of these.

| fault inject | path exercised | expected | ref |
|---|---|---|---|
| force `v_int` < 0.5 V | LOW supervisor | trip in ~1 ms (after arm), Wien cutoff, fault LED | §8a |
| force `v_int` > 3.7 V (sustained) | HIGH supervisor | trip after per-tube τ (0.3/0.4/1.2/1.3 s); a <τ pulse does **not** trip | §8a-i |
| `v_int` ride < arm (1.5 V) then fault | arm gating | no trip until armed | §8a |
| open / short R_top, R_bot, R_sense | FMEA passive faults | supervisor catches (silent-hot = 0) | §8 |
| drive `v_bridge_top` hard | FWR → over-power comp → disconnect | relay opens (authority-gated), release fast | §8b |
| pull coil/board power | NO-relay fail-safe | contact opens (cold-safe) | §14c |
| commanded over-power (warm-up) | authority discriminator | **no** disconnect (v_int mid-range) | §8b |

**Gate:** worst over-driving fault (botref_short) peaks **≤ 871 K, zero dwell
> 900 K** with the per-tube watchdog; zero false trips on cold-start/restart.

---

## 6. HIL filament emulator (spec)

A 2-terminal active load across the tube socket that **runs the same thermal model
as `regulator.py`'s `.subckt filament`** in real time, so the closed loop sees
the exact R(T) and τ — safely, repeatably, and with fault injection.

### 6a. The model (radiative-loss only — vacuum filament)

```
 R(T)      = R_cold · (T / 300)^1.2                 (T in K; R_hot/R_cold = 3.245)
 P_elec    = V_fil² / R(T)                          (V_fil = emulated-filament drop, AC carrier)
 P_rad     = σεA · (T⁴ − 300⁴)                      (the only loss term)
 dT/dt     = (P_elec − P_rad) / C_th                (integrate; T(0)=300 K)
```

Per-tube constants (T_amb=300 K, T_op=800 K, FIL_EXP=1.2):

| tube | **R_cold** | **R_hot (=R_op)** | P_op | **σεA** | **C_th** | τ_th |
|---|---|---|---|---|---|---|
| IV-18 | 30.8 Ω | 100 Ω | 10 mW | 2.49e-14 | 9.69e-6 | 0.19 s |
| **IV-6** | 6.16 Ω | 20 Ω | 50 mW | 1.25e-13 | 5.10e-5 | 0.20 s |
| ILC1-1/7 | 7.71 Ω | 25 Ω | 1000 mW | 2.49e-12 | 2.14e-3 | 0.42 s |
| ILC1-1/8 | 2.47 Ω | 8 Ω | 180 mW | 4.48e-13 | 5.69e-4 | 0.62 s |

(σεA, C_th in the sim's electrical-analog units: T_node[V]=T[K], current=power[W],
C_th[F]=thermal cap. The μC just uses them as ODE constants.)

### 6b. Architecture

```
  socket+ ──┬───────────────[ sense Rs ]──── socket−
            │                    │
        [ MOSFET ]  ◄── Vgs ── [ CR servo ]  ← R_set (DAC)
            │  (variable R, constant-resistance mode)
       V_fil, I_fil  ──► ADC ──► µC ──► thermal ODE ──► R_set, fault flags
```

- **Variable-R element = constant-resistance (CR) electronic load:** a power
  **MOSFET** + an **op-amp servo** that forces `I = V_fil / R_set` (so the MOSFET
  presents a *clean, defined* R, not the raw nonlinear R_DS). The servo bandwidth
  ≫ 1 kHz so R is constant across each carrier cycle; the µC moves `R_set` only on
  the thermal timescale. This is what keeps the emulated R linear enough not to
  corrupt the loop. (A switched precision-resistor ladder is the low-distortion
  alternative if you want THD-grade linearity, at coarser resolution.)
- **Sense:** ADC samples `V_fil` and `I_fil` (across Rs); the µC forms the
  **carrier-cycle-averaged power** P_elec (RMS², or mean of V·I over ≥1 cycle).
- **µC loop (Δt ≈ 1 ms ≪ τ_th):** read P_elec → integrate `T += Δt·(P_elec −
  σεA·(T⁴−300⁴))/C_th` → compute `R(T)` → write `R_set` (DAC → servo). Pick the
  tube's constant set at startup.
- **Range:** the element must span R_cold…R_hot (e.g. IV-6 6–20 Ω) and carry the
  filament current at V_op (IV-6 50 mA/1 V; ILC1-1/7 200 mA/5 V/1 W) — a small
  MOSFET + 0.1 Ω sense covers all tubes.

### 6c. What the emulator buys (beyond a bulb)

- **Exact dynamics:** correct τ_th and R(T) → the loop behaves as designed; HIL
  runs overlay the validated battery.
- **Fault injection in firmware:** step R (open/short filament), perturb σεA
  (emulate a cooling-airflow change), or force T — to exercise the §5 protection
  matrix repeatably without risking tubes. The emulator *is* the fault generator.
- **Observability:** T is the µC's internal state (directly logged), unlike a real
  filament where you can only infer it from R or brightness.

> THD must still be measured on the **fixed precision R** (Stage 1) — the
> MOSFET-CR load is linear enough for loop/protection work but not for the THD
> metric itself.

---

## 7. Stage 4 — real filament (last)

Only after Stages 0–3 pass. Cheapest/toughest tube first; watch **brightness**
(THD = visible flicker), confirm the regulated point and a gentle re-check of the
protection. This is verification, not debugging — debugging happens on the loads.

---

## 8. Carry-ins the bench must settle (§11-j)

| carry-in | bench measurement | feeds back into |
|---|---|---|
| H11F R(I_LED) at the OP | Stage 1 LED-current sweep | sim H11F model |
| Wien amplitude tempco / >60–70 °C death | Stage 1 heat test | §2 build note |
| filament-R spread vs constant-V | real-tube sample (Stage 4) | T-uniformity envelope |
| `C_hiq` stability holds the watchdog τ | Stage 3 HIGH-trip timing vs temp | §8a-i (stable-dielectric req) |

---

## 9. Build into the prototype

- **Test points/headers:** `v_src, v_atten, v_drv, v_osc_drive, v_bridge_top,
  node_A/B, n_demod_dc, v_int`, and the protection nets (`n_armed, n_lo/hi_int,
  n_latch, n_disc_op`).
- **Fault-injection block:** jumpers to open/short R_top/R_bot/R_sense + a way to
  drive `v_int` — makes Stage 3 plug-and-play.
- **Load socket** in place of the tube connector, accepting the fixed-R / bulb /
  HIL load board.
