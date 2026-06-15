
# Slew-limited op-amp THD-vs-carrier  Mon Jun 15 11:05:33 2026

Calibrated `uopamp_lvl3_slew` Islew = **127.3 nA** -> output SR = 0.800 V/us (target 0.8, OPA4277) @ GBW 1 MHz.
Calibration points (Islew nA -> SR V/us): 60->0.38, 90->0.57, 120->0.75, 150->0.94, 200->1.26, 300->1.88

THD (dB) of the filament drive vs carrier frequency:

| tube | model | 1 kHz | 2 kHz | 5 kHz | 10 kHz | 15 kHz | 20 kHz |
|---|---|---|---|---|---|---|---|
| ilc11_7 | nominal (no-slew) | -34.7 | -34.8 | -35.4 | -36.3 | nan | nan |
| ilc11_7 | slew 0.8 V/us | -34.7 | -34.8 | -35.2 | nan | nan | nan |
| iv18 | nominal (no-slew) | -52.8 | -43.1 | -38.6 | -36.8 | -35.3 | -35.2 |
| iv18 | slew 0.8 V/us | -52.8 | -43.1 | -38.6 | -36.8 | -35.0 | -34.6 |

_calibrate + 24 sweeps in 1100s_

