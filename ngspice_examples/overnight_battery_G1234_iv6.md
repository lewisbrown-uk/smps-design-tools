
## Suite G1 — op-amp GBW (protection OFF)  Wed Jun 10 17:37:56 2026

| tube | GBW | T_ss | overshoot | THD | T-ripple(std) | hunt? |
|---|---|---|---|---|---|---|
| iv6 | 0.5meg | 798.4K | +0.1K | -43.3dB | 0.05K | no |
| iv6 | 1meg | 798.4K | +0.1K | -46.0dB | 0.05K | no |
| iv6 | 3meg | 798.4K | +0.1K | -48.4dB | 0.05K | no |
| iv6 | 10meg | 798.4K | +0.1K | -50.8dB | 0.05K | no |

## Suite G2 — H11F R-spread (H11F_BETA_SCALE)  Wed Jun 10 17:41:46 2026

| tube | beta_scale | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| iv6 | 0.7 | 798.5K | +0.1K | -46.2dB | 0.05K | no |
| iv6 | 1.0 | 798.4K | +0.1K | -46.0dB | 0.05K | no |
| iv6 | 1.43 | 798.3K | +0.1K | -46.0dB | 0.05K | no |

## Suite G3 — output BJT beta (BF x0.5 / x2)  Wed Jun 10 17:44:33 2026

| tube | beta | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| iv6 | BFx0.5 | 798.4K | +0.1K | -47.2dB | 0.05K | no |
| iv6 | BFx2 | 798.4K | +0.1K | -45.3dB | 0.05K | no |

## Suite G4 — independent per-op-amp Vos MC (25/tube, +/-150uV each)  Wed Jun 10 17:46:26 2026

| tube | draws | fails | T_ss range | overshoot max | THD worst | max ripple | hunts |
|---|---|---|---|---|---|---|---|
| iv6 | 25 | 0 | 796-800K | +0.1K | -45.3dB | 0.05K | 0 |
