
# t_fault_hi sweep -- watchdog speed vs fault dwell vs false-trip  Fri Jun 12 22:21:24 2026

Shorter high-side watchdog -> shorter botref_short over-temp dwell, but
risks false-tripping a healthy cold-start. Baseline as-designed = 3.0 s.

## Botref_short over-temperature dwell vs t_fault_hi

| tube | t_fhi | peak | >900K | >850K | >800K | disc@ |
|---|---|---|---|---|---|---|
| iv6 | 1.5s | 922K | 925m | 1097m | 1207m | 1382m |
| iv6 | 1.0s | 922K | 467m | 639m | 749m | 924m |
| iv6 | 0.5s | 899K | 0m | 167m | 277m | 466m |
| iv6 | 0.25s | 766K | 0m | 0m | 0m | 237m |
| iv6 | 0.125s | 579K | 0m | 0m | 0m | 122m |
| ilc11_8 | 1.5s | 886K | 0m | 385m | 751m | 1382m |
| ilc11_8 | 1.0s | 819K | 0m | 0m | 128m | 924m |
| ilc11_8 | 0.5s | 639K | 0m | 0m | 0m | 465m |
| ilc11_8 | 0.25s | 487K | 0m | 0m | 0m | 236m |
| ilc11_8 | 0.125s | 395K | 0m | 0m | 0m | 122m |
| iv18 | 1.5s | 909K | 877m | 1114m | 1226m | 1386m |
| iv18 | 1.0s | 909K | 419m | 655m | 768m | 928m |
| iv18 | 0.5s | 896K | 0m | 190m | 302m | 469m |
| iv18 | 0.25s | 799K | 0m | 0m | 0m | 240m |
| iv18 | 0.125s | 633K | 0m | 0m | 0m | 126m |
| ilc11_7 | 1.5s | 859K | 0m | 206m | 695m | 1378m |
| ilc11_7 | 1.0s | 824K | 0m | 0m | 176m | 920m |
| ilc11_7 | 0.5s | 678K | 0m | 0m | 0m | 462m |
| ilc11_7 | 0.25s | 520K | 0m | 0m | 0m | 233m |
| ilc11_7 | 0.125s | 413K | 0m | 0m | 0m | 118m |

## Cold-start false-trip vs t_fault_hi (want: ok = rides out startup)

| tube | t_fhi | instant_on | dropout | brownout |
|---|---|---|---|---|
| iv6 | 1.5s | ok | ok | ok |
| iv6 | 1.0s | ok | ok | ok |
| iv6 | 0.5s | ok | ok | ok |
| iv6 | 0.25s | **TRIP**(310K) | **TRIP**(310K) | **TRIP**(310K) |
| iv6 | 0.125s | **TRIP**(309K) | **TRIP**(309K) | **TRIP**(309K) |
| ilc11_8 | 1.5s | ok | ok | ok |
| ilc11_8 | 1.0s | ok | ok | ok |
| ilc11_8 | 0.5s | **TRIP**(367K) | **TRIP**(367K) | **TRIP**(367K) |
| ilc11_8 | 0.25s | **TRIP**(351K) | **TRIP**(351K) | **TRIP**(351K) |
| ilc11_8 | 0.125s | **TRIP**(333K) | **TRIP**(333K) | **TRIP**(333K) |
| iv18 | 1.5s | ok | ok | ok |
| iv18 | 1.0s | ok | ok | ok |
| iv18 | 0.5s | ok | ok | ok |
| iv18 | 0.25s | ok | ok | ok |
| iv18 | 0.125s | **TRIP**(308K) | **TRIP**(308K) | **TRIP**(308K) |
| ilc11_7 | 1.5s | ok | ok | ok |
| ilc11_7 | 1.0s | ok | ok | ok |
| ilc11_7 | 0.5s | **TRIP**(342K) | **TRIP**(342K) | **TRIP**(342K) |
| ilc11_7 | 0.25s | **TRIP**(334K) | **TRIP**(334K) | **TRIP**(334K) |
| ilc11_7 | 0.125s | **TRIP**(323K) | **TRIP**(323K) | **TRIP**(323K) |

_80 cells in 621s on 20 workers; Fri Jun 12 22:21:24 2026_

