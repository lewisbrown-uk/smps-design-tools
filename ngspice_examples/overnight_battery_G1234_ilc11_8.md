
## Suite G1 — op-amp GBW (protection OFF)  Wed Jun 10 13:47:40 2026

| tube | GBW | T_ss | overshoot | THD | T-ripple(std) | hunt? |
|---|---|---|---|---|---|---|
| ilc11_8 | 0.5meg | 798.6K | +0.2K | -41.5dB | 0.11K | no |
| ilc11_8 | 1meg | 798.6K | +0.2K | -44.3dB | 0.11K | no |
| ilc11_8 | 3meg | 798.6K | +0.2K | -48.6dB | 0.11K | no |
| ilc11_8 | 10meg | 798.6K | +0.2K | -51.3dB | 0.11K | no |

## Suite G2 — H11F R-spread (H11F_BETA_SCALE)  Wed Jun 10 13:51:28 2026

| tube | beta_scale | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| ilc11_8 | 0.7 | 798.7K | +0.2K | -44.7dB | 0.11K | no |
| ilc11_8 | 1.0 | 798.6K | +0.2K | -44.3dB | 0.11K | no |
| ilc11_8 | 1.43 | 798.6K | +0.2K | -44.2dB | 0.11K | no |

## Suite G3 — output BJT beta (BF x0.5 / x2)  Wed Jun 10 13:54:40 2026

| tube | beta | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| ilc11_8 | BFx0.5 | 798.6K | +0.2K | -45.1dB | 0.11K | no |
| ilc11_8 | BFx2 | 798.6K | +0.2K | -44.3dB | 0.11K | no |

## Suite G4 — independent per-op-amp Vos MC (25/tube, +/-150uV each)  Wed Jun 10 13:56:56 2026

| tube | draws | fails | T_ss range | overshoot max | THD worst | max ripple | hunts |
|---|---|---|---|---|---|---|---|
| ilc11_8 | 25 | 0 | 796-800K | +0.2K | -44.2dB | 0.11K | 0 |
