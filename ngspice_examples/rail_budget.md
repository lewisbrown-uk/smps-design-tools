# Measured ±10 V rail current (instrumented, steady state)

Sim: behavioural demod + protection off; **+6 op-amp ch (4.8 mA) added** to each ±10 rail for the channels this config omits (16-ch board total). Last 200 ms of 6 s.

| tube | T_ss K | **THD** | P_fil | **+10 mean** | +10 peak | **−10 mean** | −10 peak | I_LED |
|---|---|---|---|---|---|---|---|---|
| iv18 | 796 | **-57.3 dB** | 10 mW | **22.1 mA** | 29 mA | **24.6 mA** | 31 mA | 2.6 mA |
| iv6 | 798 | **-54.2 dB** | 50 mW | **40.0 mA** | 85 mA | **42.6 mA** | 87 mA | 2.7 mA |
| ilc11_7 | 800 | **-35.2 dB** | 1001 mW | **111.3 mA** | 311 mA | **114.2 mA** | 314 mA | 2.9 mA |
| ilc11_8 | 799 | **-52.2 dB** | 179 mW | **85.3 mA** | 228 mA | **87.7 mA** | 230 mA | 2.5 mA |
