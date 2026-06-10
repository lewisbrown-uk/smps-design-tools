
## Suite G1 — op-amp GBW (protection OFF)  Wed Jun 10 17:37:56 2026

| tube | GBW | T_ss | overshoot | THD | T-ripple(std) | hunt? |
|---|---|---|---|---|---|---|
| ilc11_8 | 0.5meg | 798.6K | +7.4K | -42.3dB | 0.02K | no |
| ilc11_8 | 1meg | 798.6K | +7.4K | -44.3dB | 0.02K | no |
| ilc11_8 | 3meg | 798.6K | +7.4K | -49.3dB | 0.02K | no |
| ilc11_8 | 10meg | 798.6K | +7.4K | -52.2dB | 0.02K | no |

## Suite G2 — H11F R-spread (H11F_BETA_SCALE)  Wed Jun 10 17:42:38 2026

| tube | beta_scale | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| ilc11_8 | 0.7 | 798.7K | +9.7K | -44.5dB | 0.02K | no |
| ilc11_8 | 1.0 | 798.6K | +7.4K | -44.3dB | 0.02K | no |
| ilc11_8 | 1.43 | 798.6K | +5.7K | -44.4dB | 0.02K | no |

## Suite G3 — output BJT beta (BF x0.5 / x2)  Wed Jun 10 17:45:30 2026

| tube | beta | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| ilc11_8 | BFx0.5 | 798.6K | +7.4K | -45.0dB | 0.02K | no |
| ilc11_8 | BFx2 | 798.6K | +7.4K | -44.0dB | 0.02K | no |

## Suite G4 — independent per-op-amp Vos MC (25/tube, +/-150uV each)  Wed Jun 10 17:47:23 2026

| tube | draws | fails | T_ss range | overshoot max | THD worst | max ripple | hunts |
|---|---|---|---|---|---|---|---|
| ilc11_8 | 25 | 0 | 796-800K | +7.7K | -44.2dB | 0.02K | 0 |
