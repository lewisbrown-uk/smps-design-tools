
## Suite G1 — op-amp GBW (protection OFF)  Wed Jun 10 17:37:56 2026

| tube | GBW | T_ss | overshoot | THD | T-ripple(std) | hunt? |
|---|---|---|---|---|---|---|
| iv18 | 0.5meg | 796.4K | +0.1K | -49.8dB | 0.06K | no |
| iv18 | 1meg | 796.4K | +0.1K | -54.0dB | 0.06K | no |
| iv18 | 3meg | 796.4K | +0.1K | -57.9dB | 0.06K | no |
| iv18 | 10meg | 796.4K | +0.1K | -59.0dB | 0.06K | no |

## Suite G2 — H11F R-spread (H11F_BETA_SCALE)  Wed Jun 10 17:41:00 2026

| tube | beta_scale | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| iv18 | 0.7 | 796.6K | +0.1K | -54.2dB | 0.06K | no |
| iv18 | 1.0 | 796.4K | +0.1K | -54.0dB | 0.06K | no |
| iv18 | 1.43 | 796.2K | +0.1K | -53.8dB | 0.06K | no |

## Suite G3 — output BJT beta (BF x0.5 / x2)  Wed Jun 10 17:43:28 2026

| tube | beta | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| iv18 | BFx0.5 | 796.4K | +0.1K | -55.5dB | 0.06K | no |
| iv18 | BFx2 | 796.4K | +0.1K | -53.1dB | 0.06K | no |

## Suite G4 — independent per-op-amp Vos MC (25/tube, +/-150uV each)  Wed Jun 10 17:45:07 2026

| tube | draws | fails | T_ss range | overshoot max | THD worst | max ripple | hunts |
|---|---|---|---|---|---|---|---|
| iv18 | 25 | 0 | 791-801K | +0.1K | -51.4dB | 0.06K | 0 |
