# ilc11_7: ambient + worst-case  (bridge-ref tempco 100 ppm/°C)

## H — ambient sweep (device temp + bridge-ref tempco)
| ambient | T_ss | ΔT_ss vs 25°C | THD |
|---|---|---|---|
| 0°C | 798.0K |  | -34.7dB |
| 25°C | 799.6K | +0.0K | -34.7dB |
| 50°C | FAIL | | |

## W — stacked worst-case corner (filament R±5%, bridge-R±1%+tempco, Vos±150µV, v_buf±5%)
| corner | T_ss | THD | notes |
|---|---|---|---|
| worst-COLD | FAIL | | |
| worst-HOT | 854.1K | -32.1dB | R_op×0.95, target×~1.030, Vos -100µV, 0°C |
| nominal-25 | 799.6K | -34.7dB | R_op×1.0, target×~1.000, Vos 50µV, 25°C |
