
# Cap DC-bias derating sweep -- protection qualifier caps  Fri Jun 12 19:15:04 2026

> **CONCLUSION:** protection timing is **robust to severe cap DC-bias derating**.
> Down to k=0.4 (40% of nominal C — a 16 V X7R near rated voltage): **zero
> false-trips** (Part 1, all tubes/scenarios) and **every fault still caught**
> (Part 2). Derating even helps slightly (smaller C_envop → faster over-power
> envelope → marginally lower peaks). The 3 s/7 ms discrimination has ~2.5×
> margin, so **standard X7R on the qualifier caps is adequate** — no C0G/film or
> high-V rating needed for protection function.
>
> **CAVEAT (provenance):** run against **origin/main** files, whose
> `H11F1.spice.txt` (md5 008a1f16) **differs from the simhost's validated model**
> (b3c29d12). The absolute Part-2 peaks here (IV-6 botref_short **922 K**, vs the
> HANDOFF's validated "worst 899 K, never reaches 900 K") are **higher** and need
> isolating — likely the H11F1 drift (it sets drive authority → the pre-clamp
> peak). The derating *conclusion* is robust to that (it's about timing margin,
> not the absolute peak). See `ctrl.py` H11F1 A/B control.

Scales C_hiq/C_loq/C_arm/C_lat/C_envop by a derating factor (X7R DC-bias
capacitance loss). k=1.0 is as-designed; k=0.4 ~ a 16 V X7R near rated V.
Want: no false-trip (Part 1), fault still caught + bounded (Part 2).

## Part 1 -- false-trip under derating (want: ok on all)

| tube | derate | instant_on | dropout | brownout |
|---|---|---|---|---|
| ilc11_7 | x1.0 | ok | ok | ok |
| ilc11_7 | x0.8 | ok | ok | ok |
| ilc11_7 | x0.6 | ok | ok | ok |
| ilc11_7 | x0.5 | ok | ok | ok |
| ilc11_7 | x0.4 | ok | ok | ok |
| iv6 | x1.0 | ok | ok | ok |
| iv6 | x0.8 | ok | ok | ok |
| iv6 | x0.6 | ok | ok | ok |
| iv6 | x0.5 | ok | ok | ok |
| iv6 | x0.4 | ok | ok | ok |
| iv18 | x1.0 | ok | ok | ok |
| iv18 | x0.8 | ok | ok | ok |
| iv18 | x0.6 | ok | ok | ok |
| iv18 | x0.5 | ok | ok | ok |
| iv18 | x0.4 | ok | ok | ok |
| ilc11_8 | x1.0 | ok | ok | ok |
| ilc11_8 | x0.8 | ok | ok | ok |
| ilc11_8 | x0.6 | ok | ok | ok |
| ilc11_8 | x0.5 | ok | ok | ok |
| ilc11_8 | x0.4 | ok | ok | ok |

## Part 2 -- fault catch + peak under derating (want: caught, bounded)

| tube | derate | fault | T_peak | disconnect? |
|---|---|---|---|---|
| ilc11_7 | x1.0 | xubuf_hi | 813.6K | YES |
| ilc11_7 | x1.0 | botref_short | 867.1K | YES |
| ilc11_7 | x0.8 | xubuf_hi | 813.5K | YES |
| ilc11_7 | x0.8 | botref_short | 866.7K | YES |
| ilc11_7 | x0.6 | xubuf_hi | 813.4K | YES |
| ilc11_7 | x0.6 | botref_short | 864.0K | YES |
| ilc11_7 | x0.5 | xubuf_hi | 813.4K | YES |
| ilc11_7 | x0.5 | botref_short | 858.6K | YES |
| ilc11_7 | x0.4 | xubuf_hi | 813.3K | YES |
| ilc11_7 | x0.4 | botref_short | 844.2K | YES |
| iv6 | x1.0 | xubuf_hi | 871.3K | YES |
| iv6 | x1.0 | botref_short | 922.1K | YES |
| iv6 | x0.8 | xubuf_hi | 870.7K | YES |
| iv6 | x0.8 | botref_short | 922.2K | YES |
| iv6 | x0.6 | xubuf_hi | 870.0K | YES |
| iv6 | x0.6 | botref_short | 922.1K | YES |
| iv6 | x0.5 | xubuf_hi | 869.7K | YES |
| iv6 | x0.5 | botref_short | 922.1K | YES |
| iv6 | x0.4 | xubuf_hi | 869.4K | YES |
| iv6 | x0.4 | botref_short | 922.0K | YES |
| iv18 | x1.0 | xubuf_hi | 898.8K | YES |
| iv18 | x1.0 | botref_short | 909.0K | YES |
| iv18 | x0.8 | xubuf_hi | 898.2K | YES |
| iv18 | x0.8 | botref_short | 909.0K | YES |
| iv18 | x0.6 | xubuf_hi | 897.5K | YES |
| iv18 | x0.6 | botref_short | 909.0K | YES |
| iv18 | x0.5 | xubuf_hi | 897.2K | YES |
| iv18 | x0.5 | botref_short | 909.0K | YES |
| iv18 | x0.4 | xubuf_hi | 896.9K | YES |
| iv18 | x0.4 | botref_short | 908.9K | YES |
| ilc11_8 | x1.0 | xubuf_hi | 834.3K | YES |
| ilc11_8 | x1.0 | botref_short | 913.3K | YES |
| ilc11_8 | x0.8 | xubuf_hi | 834.1K | YES |
| ilc11_8 | x0.8 | botref_short | 911.1K | YES |
| ilc11_8 | x0.6 | xubuf_hi | 833.9K | YES |
| ilc11_8 | x0.6 | botref_short | 900.7K | YES |
| ilc11_8 | x0.5 | xubuf_hi | 833.8K | YES |
| ilc11_8 | x0.5 | botref_short | 885.8K | YES |
| ilc11_8 | x0.4 | xubuf_hi | 833.7K | YES |
| ilc11_8 | x0.4 | botref_short | 854.8K | YES |

_100 cells in 826s on 20 workers; done Fri Jun 12 19:15:04 2026_

