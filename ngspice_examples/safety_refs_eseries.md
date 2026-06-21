# Safety-reference divider values from LM4040-4.096 (Vref = 4.096 V)

Divider `Vref─[Rtop]─node─[Rbot]─0`, `Vout = 4.096·Rbot/(Rtop+Rbot)`. Total constrained to 40k–100k (≈41–102 µA ref load).

| threshold | target | series | Rtop | Rbot | Vout | err (mV) | err (%) | Rth |
|---|---|---|---|---|---|---|---|---|
| v_ref_lo   (supervisor LOW, all tubes) | 0.500 | E24 | 36k | 5.1k | 0.5083 | +8.26 | +1.653 | 4.46715k |
| v_ref_lo   (supervisor LOW, all tubes) | 0.500 | E96 | 76.8k | 10.7k | 0.5009 | +0.88 | +0.176 | 9.39154k |
|  |  |  |  |  |  |  |  |  |
| v_ref_arm  (supervisor ARM, all tubes) | 1.500 | E24 | 62k | 36k | 1.5047 | +4.65 | +0.310 | 22.7755k |
| v_ref_arm  (supervisor ARM, all tubes) | 1.500 | E96 | 30.1k | 17.4k | 1.5004 | +0.43 | +0.029 | 11.0261k |
|  |  |  |  |  |  |  |  |  |
| v_ref_hi   (supervisor HIGH, all tubes) | 3.700 | E24 | 5.1k | 47k | 3.6950 | -4.95 | -0.134 | 4.60077k |
| v_ref_hi   (supervisor HIGH, all tubes) | 3.700 | E96 | 4.42k | 41.2k | 3.6991 | -0.85 | -0.023 | 3.99176k |
|  |  |  |  |  |  |  |  |  |
| v_ref_op   (over-power, IV-6 / IV-18) | 1.300 | E24 | 43k | 20k | 1.3003 | +0.32 | +0.024 | 13.6508k |
| v_ref_op   (over-power, IV-6 / IV-18) | 1.300 | E96 | 49.9k | 23.2k | 1.3000 | -0.04 | -0.003 | 15.8369k |
|  |  |  |  |  |  |  |  |  |
| v_ref_op   (over-power, ILC1-1/8) | 1.560 | E24 | 39k | 24k | 1.5604 | +0.38 | +0.024 | 14.8571k |
| v_ref_op   (over-power, ILC1-1/8) | 1.560 | E96 | 27.4k | 16.9k | 1.5626 | +2.58 | +0.166 | 10.4528k |
|  |  |  |  |  |  |  |  |  |
| v_ref_op/2 (over-power, ILC1-1/7) | 3.250 | E24 | 16k | 62k | 3.2558 | +5.79 | +0.178 | 12.7179k |
| v_ref_op/2 (over-power, ILC1-1/7) | 3.250 | E96 | 13.3k | 51.1k | 3.2501 | +0.09 | +0.003 | 10.5533k |
|  |  |  |  |  |  |  |  |  |
