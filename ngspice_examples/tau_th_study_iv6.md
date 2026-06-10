# tau_th study — iv6  (estimate tau=0.2s)

## Cold-start overshoot: 0.1s (model) vs estimate
| tau_th | T_overshoot | drive_OS | T_ss | THD | settle(<1%) |
|---|---|---|---|---|---|
| 0.1s | +0.2K | +40% | 798.4K | -46.1dB | 0.61s |
| 0.2s_est | +0.1K | +40% | 798.4K | -46.0dB | 0.48s |

## Fault excursion dwell at tau=0.2s (XU_buf stuck, protection ON)
- disconnect @ 12 ms,  peak 871 K @ 19 ms
- dwell >800K: **80 ms**,  >850K: 22 ms,  >900K: 0 ms
- cool peak→800K: 61 ms,  →700K: 196 ms,  →500K: 951 ms
