import numpy as np
d = np.loadtxt("/home/lewisbrown/claude-code/smps-design-tools/ngspice_examples/_closedloop_test/jbt_iv3.data")
t = d[:, 0]
T = d[:, 17]
v_int = d[:, 15]
for s, e in [(2.0, 2.5), (1.5, 2.0), (1.0, 1.5), (0.5, 1.0)]:
    m = (t > s) & (t < e)
    if not m.any():
        continue
    ts = t[m]
    Ts = T[m]
    vs = v_int[m]
    print(f"t={s:.1f}-{e:.1f}: T_avg={Ts.mean():.2f} dT/window={(Ts[-1]-Ts[0])*1000:.2f}mK V_int_avg={vs.mean():.4f} dV/window={(vs[-1]-vs[0])*1e6:.2f}uV")
