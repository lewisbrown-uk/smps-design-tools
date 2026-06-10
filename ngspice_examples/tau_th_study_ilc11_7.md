# tau_th study — ilc11_7  (estimate tau=0.42s)

## Cold-start overshoot: 0.1s (model) vs estimate
| tau_th | T_overshoot | drive_OS | T_ss | THD | settle(<1%) |
|---|---|---|---|---|---|
| 0.1s | +3.6K | +6% | 799.6K | -34.7dB | 0.23s |
| 0.42s_est | +3.7K | +6% | 799.6K | -34.7dB | 0.75s |

## Fault excursion dwell at tau=0.42s (XU_buf stuck, protection ON)
- disconnect @ 23 ms,  peak 814 K @ 30 ms
- dwell >800K: **57 ms**,  >850K: 0 ms,  >900K: 0 ms
- cool peak→800K: 28 ms,  →700K: 312 ms,  →500K: 1896 ms
