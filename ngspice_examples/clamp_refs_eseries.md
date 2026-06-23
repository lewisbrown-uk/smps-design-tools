# Clamp-reference E-series values

## (1) §8b over-power flat clamp — TLV431 divider  V_cl = 1.24·(1+Rt/Rb)

| tube | V_cl | series | Rt (K→ref) | Rb (ref→GND) | V_cl actual | err | R_bias(+15V,~1mA) |
|---|---|---|---|---|---|---|---|
| ILC1-1/7 (idle, >rail) | 12.600 | E24 | 22k | 2.4k | 12.607 | +0.007 | 2.4k |
| ILC1-1/7 (idle, >rail) | 12.600 | E96 | 18.7k | 2.05k | 12.551 | -0.049 |  |
| | | | | | | | |
| IV-6   (this board) | 2.662 | E24 | 15k | 13k | 2.671 | +0.009 | 12.3k |
| IV-6   (this board) | 2.662 | E96 | 10.7k | 9.31k | 2.665 | +0.003 |  |
| | | | | | | | |
| IV-18 | 2.333 | E24 | 16k | 18k | 2.342 | +0.009 | 12.7k |
| IV-18 | 2.333 | E96 | 16.5k | 18.7k | 2.334 | +0.001 |  |
| | | | | | | | |
| ILC1-1/8 | 3.182 | E24 | 47k | 30k | 3.183 | +0.001 | 11.8k |
| ILC1-1/8 | 3.182 | E96 | 21.5k | 13.7k | 3.186 | +0.004 |  |
| | | | | | | | |

## (2) §7 anti-windup clamp window [-3 V, +6 V] (buffered rail dividers)

| ref | from | target | series | R_top | R_bot | actual | err |
|---|---|---|---|---|---|---|---|
| +6 V (hi) | 10V | +6 | E24 | 100k | 150k | +6.000 | +0.000 |
| +6 V (hi) | 10V | +6 | E96 | 100k | 150k | +6.000 | +0.000 |
| | | | | | | | |
| -3 V (lo) | 10V | -3 | E24 | 91k | 39k | -3.000 | +0.000 |
| -3 V (lo) | 10V | -3 | E96 | 249k | 107k | -3.006 | -0.006 |
| | | | | | | | |
