# tau_th study — iv18  (estimate tau=0.19s)

## Cold-start overshoot: 0.1s (model) vs estimate
| tau_th | T_overshoot | drive_OS | T_ss | THD | settle(<1%) |
|---|---|---|---|---|---|
| 0.1s | +0.1K | +38% | 796.4K | -53.7dB | 0.98s |
| 0.19s_est | +0.1K | +39% | 796.4K | -53.9dB | 0.86s |

## Fault excursion dwell at tau=0.19s (XU_buf stuck, protection ON)
- disconnect @ 19 ms,  peak 899 K @ 25 ms
- dwell >800K: **100 ms**,  >850K: 46 ms,  >900K: 0 ms
- cool peak→800K: 76 ms,  →700K: 204 ms,  →500K: 921 ms
