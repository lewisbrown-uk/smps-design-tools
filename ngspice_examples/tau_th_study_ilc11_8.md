# tau_th study — ilc11_8  (estimate tau=0.62s)

## Cold-start overshoot: 0.1s (model) vs estimate
| tau_th | T_overshoot | drive_OS | T_ss | THD | settle(<1%) |
|---|---|---|---|---|---|
| 0.1s | +0.2K | +38% | 798.6K | -44.5dB | 0.54s |
| 0.62s_est | +7.4K | +38% | 798.6K | -44.4dB | 0.81s |

## Fault excursion dwell at tau=0.62s (XU_buf stuck, protection ON)
- disconnect @ 22 ms,  peak 834 K @ 29 ms
- dwell >800K: **127 ms**,  >850K: 0 ms,  >900K: 0 ms
- cool peak→800K: 100 ms,  →700K: 518 ms,  →500K: 2857 ms
