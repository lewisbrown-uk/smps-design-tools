# VALIDATION — production design (per-tube `t_fault_hi`)  2026-06-13

Full re-validation battery on the **production `TUBES`** (canonical
`regulator.py`, branch `claude/schematic-capture`), run on the simhost
(ngspice-44.2, 6 suites in parallel). Confirms the per-tube high-side watchdog
(`t_fault_hi` = IV-18 0.3 / IV-6 0.4 / ILC1-1/7 1.2 / ILC1-1/8 1.3 s) and that
nothing else regressed. Supersedes the prior 3 s-watchdog battery (commit
`4d897c9`).

## Conclusion — clean end-to-end, no regressions

- **Protection (C / D / E):** **0 false-trips** (disorderly); every overheat
  fault **caught + cold-safe**; both slow over-drive faults (`botref_short`,
  `topref_open`) bounded **≤ 871 K** — vs **922 K / ~2.3 s > 900 K** at the old
  uniform 3 s watchdog. Worst peak anywhere is now `iv18 xubuf_lo` **899.9 K**,
  the *fast* low-side fault (~ms catch, brief — not a sustained excursion).
- **Monte Carlo (B, 50/tube; G4, 25/tube): 0 fails, 0 hunts.**
- **Active-device (G1–G4): 0 hunts;** GBW 0.5–10 MHz clean (THD flat-to-
  improving — the old "≥ 3 MHz hunts" claim stays refuted).
- **Cold-start (A, F):** nominal as expected (ILC1-1/8 +7.4 K accepted);
  Vos = 2–5 mV / stacked-worst corners degrade as known (OPA4277 low-Vos is
  load-bearing — not a concern at the real ±150 µV).

Suites run as separate invocations (`overnight_battery.py A/B/C/D`,
`battery_supplement.py`, `battery_suiteG.py`); raw tables verbatim below.

---

## Suite A — cold-start robustness corners (protection OFF)  Sat Jun 13 15:13:33 2026

| tube | corner | T_overshoot | T_ss | THD | V_int_ss |
|---|---|---|---|---|---|
| ilc11_7 | nominal | +3.7K | 799.6K | -34.7dB | 3.023 |
| ilc11_7 | Vos=2mV | +4.3K | 796.1K | -34.4dB | 2.997 |
| ilc11_7 | Vos=5mV | +5.5K | 790.7K | -33.2dB | 2.953 |
| ilc11_7 | R_op+10% | +5.1K | 738.5K | -36.9dB | 2.404 |
| ilc11_7 | R_op-10% | +0.1K | 861.2K | -20.6dB | 4.012 |
| ilc11_7 | v_buf+5% | +3.7K | 799.6K | -34.7dB | 3.022 |
| ilc11_7 | v_buf-5% | +3.6K | 799.6K | -34.8dB | 3.021 |
| ilc11_7 | WORST Vos5mV+Rop+10%+vbuf+5% | +8.7K | 728.4K | -34.0dB | 2.275 |
| iv6 | nominal | +0.1K | 798.4K | -46.0dB | 3.066 |
| iv6 | Vos=2mV | +0.1K | 783.6K | -32.5dB | 2.949 |
| iv6 | Vos=5mV | +6.3K | 759.2K | -23.9dB | 2.722 |
| iv6 | R_op+10% | +0.1K | 737.4K | -49.3dB | 2.413 |
| iv6 | R_op-10% | +0.1K | 871.8K | -46.7dB | 3.551 |
| iv6 | v_buf+5% | +0.1K | 798.4K | -46.6dB | 3.066 |
| iv6 | v_buf-5% | +0.1K | 798.4K | -45.6dB | 3.066 |
| iv6 | WORST Vos5mV+Rop+10%+vbuf+5% | +17.1K | 692.1K | -21.8dB | 1.564 |
| iv18 | nominal | +0.1K | 796.4K | -54.0dB | 3.100 |
| iv18 | Vos=2mV | +0.1K | 762.6K | -30.8dB | 2.809 |
| iv18 | Vos=5mV | +8.0K | 698.9K | -20.9dB | 1.868 |
| iv18 | R_op+10% | +0.1K | 735.4K | -53.3dB | 2.471 |
| iv18 | R_op-10% | +0.1K | 869.9K | -55.4dB | 3.579 |
| iv18 | v_buf+5% | +0.1K | 796.4K | -54.4dB | 3.100 |
| iv18 | v_buf-5% | +0.1K | 796.4K | -53.4dB | 3.100 |
| iv18 | WORST Vos5mV+Rop+10%+vbuf+5% | +8.7K | 649.0K | -19.2dB | -0.509 |
| ilc11_8 | nominal | +7.4K | 798.6K | -44.3dB | 3.110 |
| ilc11_8 | Vos=2mV | +9.5K | 786.5K | -33.9dB | 3.022 |
| ilc11_8 | Vos=5mV | +15.4K | 766.5K | -25.7dB | 2.852 |
| ilc11_8 | R_op+10% | +10.5K | 737.6K | -43.7dB | 2.491 |
| ilc11_8 | R_op-10% | +4.1K | 872.1K | -45.9dB | 3.589 |
| ilc11_8 | v_buf+5% | +7.4K | 798.6K | -44.8dB | 3.110 |
| ilc11_8 | v_buf-5% | +7.4K | 798.6K | -44.5dB | 3.110 |
| ilc11_8 | WORST Vos5mV+Rop+10%+vbuf+5% | +21.7K | 700.5K | -23.6dB | 1.891 |

_Suite A done in 2703s_


## Suite B — Monte Carlo (50/tube: bridge-R +/-1%, caps +/-10%, Vos +/-50uV)  Sat Jun 13 15:13:33 2026

| tube | draws | fails | T_ss range | overshoot max | THD worst | hunts |
|---|---|---|---|---|---|---|
| ilc11_7 | 50 | 0 | 783-810K | +4.2K | -34.7dB | 0 |
| iv6 | 50 | 0 | 784-814K | +0.1K | -45.3dB | 0 |
| iv18 | 50 | 0 | 784-812K | +0.1K | -53.8dB | 0 |
| ilc11_8 | 50 | 0 | 785-814K | +8.3K | -44.2dB | 0 |

_Suite B done in 16871s_


## Suite C — disorderly / restart (protection ON, watch false-trip)  Sat Jun 13 15:13:33 2026

| tube | scenario | T_peak | T_ss | false-trip? |
|---|---|---|---|---|
| ilc11_7 | instant_on | 803.3K | 799.6K | no |
| ilc11_7 | dropout_restart | 803.5K | 799.6K | no |
| ilc11_7 | brownout | 803.6K | 799.6K | no |
| iv6 | instant_on | 798.5K | 798.4K | no |
| iv6 | dropout_restart | 805.9K | 798.4K | no |
| iv6 | brownout | 798.5K | 798.4K | no |
| iv18 | instant_on | 796.4K | 796.4K | no |
| iv18 | dropout_restart | 802.7K | 796.4K | no |
| iv18 | brownout | 796.5K | 796.4K | no |
| ilc11_8 | instant_on | 806.0K | 798.6K | no |
| ilc11_8 | dropout_restart | 806.1K | 798.6K | no |
| ilc11_8 | brownout | 806.0K | 798.6K | no |

_Suite C done in 1913s_


## Suite D — protection FMEA (overheat faults, protection ON)  Sat Jun 13 15:13:33 2026

| tube | fault | T_peak | T_final | disconnect? |
|---|---|---|---|---|
| ilc11_7 | xubuf_hi | 813.5K | 380.6K | YES |
| ilc11_7 | xubuf_lo | 813.6K | 380.6K | YES |
| ilc11_7 | atten_bot_short | 300.0K | 300.0K | no |
| ilc11_7 | botref_short | 844.2K | 358.1K | YES |
| ilc11_7 | sense_open | 300.0K | 300.0K | YES |
| iv6 | xubuf_hi | 871.3K | 329.2K | YES |
| iv6 | xubuf_lo | 872.3K | 329.2K | YES |
| iv6 | atten_bot_short | 300.0K | 300.0K | no |
| iv6 | botref_short | 871.1K | 313.5K | YES |
| iv6 | sense_open | 300.0K | 300.0K | YES |
| iv18 | xubuf_hi | 898.7K | 326.8K | YES |
| iv18 | xubuf_lo | 899.9K | 326.8K | YES |
| iv18 | atten_bot_short | 300.0K | 300.0K | no |
| iv18 | botref_short | 835.3K | 311.5K | YES |
| iv18 | sense_open | 300.0K | 300.0K | YES |
| ilc11_8 | xubuf_hi | 834.3K | 418.7K | YES |
| ilc11_8 | xubuf_lo | 834.5K | 418.7K | YES |
| ilc11_8 | atten_bot_short | 300.0K | 300.0K | no |
| ilc11_8 | botref_short | 867.5K | 392.7K | YES |
| ilc11_8 | sense_open | 300.0K | 300.0K | YES |

_Suite D done in 2111s_


## Suite E — over-driving forward-gain faults (protection ON)  Sat Jun 13 15:13:33 2026

| tube | fault | T_peak | T_final | disconnect? |
|---|---|---|---|---|
| ilc11_7 | atten_top_short | 812.2K | 367.8K | YES |
| ilc11_7 | atten_bot_open | 812.2K | 367.8K | YES |
| ilc11_7 | topref_open | 844.2K | 376.9K | YES |
| ilc11_7 | fb_vgain_short | 803.3K | 799.6K | no |
| iv6 | atten_top_short | 841.5K | 319.9K | YES |
| iv6 | atten_bot_open | 841.5K | 319.9K | YES |
| iv6 | topref_open | 871.1K | 321.7K | YES |
| iv6 | fb_vgain_short | 798.5K | 798.4K | no |
| iv18 | atten_top_short | 846.6K | 317.8K | YES |
| iv18 | atten_bot_open | 846.5K | 317.8K | YES |
| iv18 | topref_open | 835.5K | 318.9K | YES |
| iv18 | fb_vgain_short | 796.4K | 796.4K | no |
| ilc11_8 | atten_top_short | 823.0K | 400.4K | YES |
| ilc11_8 | atten_bot_open | 823.0K | 400.4K | YES |
| ilc11_8 | topref_open | 867.6K | 416.1K | YES |
| ilc11_8 | fb_vgain_short | 806.0K | 798.6K | no |

## Suite F — realistic R_op +/-5% cold-start (protection OFF)  Sat Jun 13 15:46:12 2026

| tube | R_op | T_overshoot | T_ss | THD |
|---|---|---|---|---|
| ilc11_7 | R_op+5% | +4.5K | 767.7K | -35.4dB |
| ilc11_7 | R_op-5% | +2.4K | 834.6K | -33.8dB |
| iv6 | R_op+5% | +0.1K | 766.5K | -45.6dB |
| iv6 | R_op-5% | +0.1K | 833.3K | -46.1dB |
| iv18 | R_op+5% | +0.1K | 764.5K | -53.7dB |
| iv18 | R_op-5% | +0.1K | 831.3K | -54.4dB |
| ilc11_8 | R_op+5% | +8.8K | 766.8K | -44.1dB |
| ilc11_8 | R_op-5% | +6.0K | 833.6K | -45.2dB |

## Suite G1 — op-amp GBW (protection OFF)  Sat Jun 13 15:13:33 2026

| tube | GBW | T_ss | overshoot | THD | T-ripple(std) | hunt? |
|---|---|---|---|---|---|---|
| ilc11_7 | 0.5meg | 799.6K | +3.7K | -34.8dB | 0.02K | no |
| ilc11_7 | 1meg | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| ilc11_7 | 3meg | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| ilc11_7 | 10meg | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| iv6 | 0.5meg | 798.4K | +0.1K | -43.3dB | 0.05K | no |
| iv6 | 1meg | 798.4K | +0.1K | -46.0dB | 0.05K | no |
| iv6 | 3meg | 798.4K | +0.1K | -48.4dB | 0.05K | no |
| iv6 | 10meg | 798.4K | +0.1K | -50.8dB | 0.05K | no |
| iv18 | 0.5meg | 796.4K | +0.1K | -49.8dB | 0.06K | no |
| iv18 | 1meg | 796.4K | +0.1K | -54.0dB | 0.06K | no |
| iv18 | 3meg | 796.4K | +0.1K | -57.9dB | 0.06K | no |
| iv18 | 10meg | 796.4K | +0.1K | -59.0dB | 0.06K | no |
| ilc11_8 | 0.5meg | 798.6K | +7.4K | -42.3dB | 0.02K | no |
| ilc11_8 | 1meg | 798.6K | +7.4K | -44.3dB | 0.02K | no |
| ilc11_8 | 3meg | 798.6K | +7.4K | -49.3dB | 0.02K | no |
| ilc11_8 | 10meg | 798.6K | +7.4K | -52.2dB | 0.02K | no |

## Suite G2 — H11F R-spread (H11F_BETA_SCALE)  Sat Jun 13 15:36:43 2026

| tube | beta_scale | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| ilc11_7 | 0.7 | 799.6K | +4.5K | -36.2dB | 0.02K | no |
| ilc11_7 | 1.0 | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| ilc11_7 | 1.43 | 799.6K | +3.1K | -33.7dB | 0.02K | no |
| iv6 | 0.7 | 798.5K | +0.1K | -46.2dB | 0.05K | no |
| iv6 | 1.0 | 798.4K | +0.1K | -46.0dB | 0.05K | no |
| iv6 | 1.43 | 798.3K | +0.1K | -46.0dB | 0.05K | no |
| iv18 | 0.7 | 796.6K | +0.1K | -54.2dB | 0.06K | no |
| iv18 | 1.0 | 796.4K | +0.1K | -54.0dB | 0.06K | no |
| iv18 | 1.43 | 796.2K | +0.1K | -53.8dB | 0.06K | no |
| ilc11_8 | 0.7 | 798.7K | +9.7K | -44.5dB | 0.02K | no |
| ilc11_8 | 1.0 | 798.6K | +7.4K | -44.3dB | 0.02K | no |
| ilc11_8 | 1.43 | 798.6K | +5.7K | -44.4dB | 0.02K | no |

## Suite G3 — output BJT beta (BF x0.5 / x2)  Sat Jun 13 15:53:37 2026

| tube | beta | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| ilc11_7 | BFx0.5 | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| ilc11_7 | BFx2 | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| iv6 | BFx0.5 | 798.4K | +0.1K | -47.2dB | 0.05K | no |
| iv6 | BFx2 | 798.4K | +0.1K | -45.3dB | 0.05K | no |
| iv18 | BFx0.5 | 796.4K | +0.1K | -55.5dB | 0.06K | no |
| iv18 | BFx2 | 796.4K | +0.1K | -53.1dB | 0.06K | no |
| ilc11_8 | BFx0.5 | 798.6K | +7.4K | -45.0dB | 0.02K | no |
| ilc11_8 | BFx2 | 798.6K | +7.4K | -44.0dB | 0.02K | no |

## Suite G4 — independent per-op-amp Vos MC (25/tube, +/-150uV each)  Sat Jun 13 16:04:39 2026

| tube | draws | fails | T_ss range | overshoot max | THD worst | max ripple | hunts |
|---|---|---|---|---|---|---|---|
| ilc11_7 | 25 | 0 | 799-800K | +3.8K | -34.6dB | 0.02K | 0 |
| iv6 | 25 | 0 | 797-801K | +0.1K | -45.1dB | 0.05K | 0 |
| iv18 | 25 | 0 | 791-804K | +0.1K | -51.4dB | 0.06K | 0 |
| ilc11_8 | 25 | 0 | 797-801K | +7.6K | -44.1dB | 0.02K | 0 |
