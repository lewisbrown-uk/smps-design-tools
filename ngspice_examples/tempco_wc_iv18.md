# iv18: ambient + worst-case  (bridge-ref tempco 100 ppm/°C)

## H — ambient sweep (device temp + bridge-ref tempco)
| ambient | T_ss | ΔT_ss vs 25°C | THD |
|---|---|---|---|
| 0°C | 795.0K |  | -44.6dB |
| 25°C | 796.4K | +0.0K | -53.6dB |
| 50°C | FAIL | | |

## W — stacked worst-case corner (filament R±5%, bridge-R±1%+tempco, Vos±150µV, v_buf±5%)
| corner | T_ss | THD | notes |
|---|---|---|---|
| worst-COLD | FAIL | | |
| worst-HOT | 853.1K | -46.0dB | R_op×0.95, target×~1.030, Vos -100µV, 0°C |
| nominal-25 | 796.4K | -53.6dB | R_op×1.0, target×~1.000, Vos 50µV, 25°C |
