
## Suite G1 — op-amp GBW (protection OFF)  Wed Jun 10 17:37:56 2026

| tube | GBW | T_ss | overshoot | THD | T-ripple(std) | hunt? |
|---|---|---|---|---|---|---|
| ilc11_7 | 0.5meg | 799.6K | +3.7K | -34.8dB | 0.02K | no |
| ilc11_7 | 1meg | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| ilc11_7 | 3meg | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| ilc11_7 | 10meg | 799.6K | +3.7K | -34.7dB | 0.02K | no |

## Suite G2 — H11F R-spread (H11F_BETA_SCALE)  Wed Jun 10 17:49:33 2026

| tube | beta_scale | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| ilc11_7 | 0.7 | 799.6K | +4.5K | -36.2dB | 0.02K | no |
| ilc11_7 | 1.0 | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| ilc11_7 | 1.43 | 799.6K | +3.1K | -33.7dB | 0.02K | no |

## Suite G3 — output BJT beta (BF x0.5 / x2)  Wed Jun 10 17:58:53 2026

| tube | beta | T_ss | overshoot | THD | T-ripple | hunt? |
|---|---|---|---|---|---|---|
| ilc11_7 | BFx0.5 | 799.6K | +3.7K | -34.7dB | 0.02K | no |
| ilc11_7 | BFx2 | 799.6K | +3.7K | -34.7dB | 0.02K | no |

## Suite G4 — independent per-op-amp Vos MC (25/tube, +/-150uV each)  Wed Jun 10 18:04:34 2026

| tube | draws | fails | T_ss range | overshoot max | THD worst | max ripple | hunts |
|---|---|---|---|---|---|---|---|
| ilc11_7 | 25 | 0 | 799-800K | +3.8K | -34.6dB | 0.02K | 0 |
