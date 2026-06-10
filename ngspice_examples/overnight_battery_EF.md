
## Suite E — over-driving forward-gain faults (protection ON)  Wed Jun 10 17:37:56 2026

| tube | fault | T_peak | T_final | disconnect? |
|---|---|---|---|---|
| ilc11_7 | atten_top_short | 812.2K | 367.8K | YES |
| ilc11_7 | atten_bot_open | 812.2K | 367.8K | YES |
| ilc11_7 | topref_open | 867.2K | 407.5K | YES |
| ilc11_7 | fb_vgain_short | 803.3K | 799.6K | no |
| iv6 | atten_top_short | 841.5K | 319.9K | YES |
| iv6 | atten_bot_open | 841.5K | 319.9K | YES |
| iv6 | topref_open | 922.2K | 346.3K | YES |
| iv6 | fb_vgain_short | 798.5K | 798.4K | no |
| iv18 | atten_top_short | 846.6K | 317.8K | YES |
| iv18 | atten_bot_open | 846.6K | 317.8K | YES |
| iv18 | topref_open | 909.0K | 342.9K | YES |
| iv18 | fb_vgain_short | 796.4K | 796.4K | no |
| ilc11_8 | atten_top_short | 823.0K | 400.4K | YES |
| ilc11_8 | atten_bot_open | 823.0K | 400.4K | YES |
| ilc11_8 | topref_open | 913.3K | 452.0K | YES |
| ilc11_8 | fb_vgain_short | 806.0K | 798.6K | no |

## Suite F — realistic R_op +/-5% cold-start (protection OFF)  Wed Jun 10 18:14:18 2026

| tube | R_op | T_overshoot | T_ss | THD |
|---|---|---|---|---|
| ilc11_7 | R_op+5% | +4.5K | 767.7K | -35.4dB |
| ilc11_7 | R_op-5% | +2.4K | 834.6K | -33.8dB |
| iv6 | R_op+5% | +0.1K | 766.5K | -45.6dB |
| iv6 | R_op-5% | +0.1K | 833.3K | -46.1dB |
| iv18 | R_op+5% | +0.1K | 764.5K | -53.7dB |
| iv18 | R_op-5% | +0.1K | 831.3K | -54.4dB |
| ilc11_8 | R_op+5% | +8.8K | 766.8K | -44.1dB |
| ilc11_8 | R_op-5% | +6.0K | 833.6K | -45.2dB |
