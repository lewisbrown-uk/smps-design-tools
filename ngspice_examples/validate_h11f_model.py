"""Standalone validation of the behavioural H11F1 SPICE model against the
Fairchild datasheet (3/19/03) curves. Three tests:

  1. R_46 vs I_F  — Figure 1 (normalized R, sweeps I_F 1-60 mA)
  2. I_46 vs V_46 at several I_F values — Figure 2
  3. LED V_F vs I_F — Figure 3

Generates a PNG with three subplots (one per test) and prints a summary
of how well the behavioural model matches the datasheet typical values
at the spec-test points.
"""
import sys, subprocess, time
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
MODEL_FILE = HERE / "spice_models" / "H11F1.spice.txt"
WORK = HERE / "_h11f_validate"
WORK.mkdir(exist_ok=True)


def run_ngspice(netlist_text, data_path):
    cir = WORK / f"{data_path.stem}.cir"
    cir.write_text(netlist_text)
    res = subprocess.run(["ngspice", "-b", cir.name],
                         cwd=WORK, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        print(f"ngspice FAILED for {data_path.name}: {res.stderr[-800:]}")
        return None
    if not data_path.exists():
        print(f"data file missing for {data_path.name}; stdout tail:\n{res.stdout[-800:]}")
        return None
    return np.loadtxt(data_path)


def test1_R_vs_IF():
    """DC sweep I_F from 0.5 mA to 60 mA. At each point, force a small
    AC test current I_46=10 µA and measure V_46 → R = V/I."""
    dat = WORK / "test1.data"
    netlist = f"""* H11F1 R vs I_F test
.include {MODEL_FILE.as_posix()}
* DC bias the LED via a forced current source
I_LED 0 N_ANODE  {{i_f_param}}
* Output: force 10 µA test current and measure V across the FET
I_OUT 0 N_46 10u
X_H11F N_ANODE 0  N_46 0  H11F1

.control
let if_steps = 80
let v_46 = vector(if_steps)
let r_46 = vector(if_steps)
let i_f  = vector(if_steps)
let i = 0
while i < if_steps
    * Sweep I_F log-spaced from 0.5 mA to 60 mA
    let i_val = 0.5e-3 * (60e-3/0.5e-3) ^ (i / (if_steps-1))
    alter i_ledtdc = i_val
    op
    let v_46[i] = v(N_46)
    let r_46[i] = v(N_46) / 10e-6
    let i_f[i]  = i_val
    let i = i + 1
end
wrdata {dat.as_posix()} i_f r_46
.endcontrol
.end
"""
    # ngspice DC sweep version using simpler syntax
    netlist = f"""* H11F1 R vs I_F test (DC sweep)
.include {MODEL_FILE.as_posix()}
I_LED 0 N_ANODE 1m
I_OUT 0 N_46 10u
X_H11F N_ANODE 0  N_46 0  H11F1
.control
dc I_LED 0.5m 60m 0.5m
wrdata {dat.as_posix()} v(N_46)
.endcontrol
.end
"""
    d = run_ngspice(netlist, dat)
    if d is None: return None
    # wrdata format: pairs of (time-like sweep var, value). For DC sweep
    # var is I_LED. Columns: [I_LED, V_46].
    i_f = d[:, 0]
    v_46 = d[:, 1]
    r_46 = v_46 / 10e-6  # 10 µA test current
    return i_f, r_46


def test2_IV_at_IF():
    """At several fixed I_F values, sweep V_46 from -0.2 to +0.2 V and
    measure I_46. Reproduces Figure 2 output characteristics."""
    results = {}
    for i_f_mA in (2, 6, 10, 14, 18):
        dat = WORK / f"test2_if{i_f_mA}.data"
        netlist = f"""* H11F1 I-V at I_F={i_f_mA} mA
.include {MODEL_FILE.as_posix()}
I_LED 0 N_ANODE {i_f_mA*1e-3}
V_46 N_46 0 0
X_H11F N_ANODE 0  N_46 0  H11F1
.control
dc V_46 -0.25 0.25 0.005
wrdata {dat.as_posix()} i(V_46)
.endcontrol
.end
"""
        d = run_ngspice(netlist, dat)
        if d is None:
            continue
        v_46 = d[:, 0]
        i_46 = -d[:, 1]  # current flows from + to -, sign-flip
        results[i_f_mA] = (v_46, i_46)
    return results


def test3_LED_VF():
    """Sweep I_F from 0.1 mA to 100 mA, measure V_F across the LED."""
    dat = WORK / "test3.data"
    netlist = f"""* H11F1 LED V_F vs I_F
.include {MODEL_FILE.as_posix()}
I_LED 0 N_ANODE 1m
V_OUT N_46 0 0  ; output unused but referenced
X_H11F N_ANODE 0  N_46 0  H11F1
.control
dc I_LED 0.1m 100m 0.5m
wrdata {dat.as_posix()} v(N_ANODE)
.endcontrol
.end
"""
    d = run_ngspice(netlist, dat)
    if d is None: return None
    return d[:, 0], d[:, 1]


def plot_all(r1, r2, r3):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # Test 1: R vs I_F (log-log), with datasheet typical points overlaid
    ax = axes[0]
    if r1 is not None:
        i_f, r_46 = r1
        r_typ_idx = np.argmin(np.abs(i_f - 16e-3))
        r_typ_model = r_46[r_typ_idx]
        ax.loglog(i_f * 1e3, r_46 / r_typ_model, "C0-", lw=1.5, label="model")
    # Datasheet typical (Figure 1) approximate points
    ds_if = np.array([1, 2, 4, 8, 16, 30, 60])
    ds_r_norm = np.array([10, 5, 2.5, 1.5, 1.0, 0.6, 0.4])
    ax.loglog(ds_if, ds_r_norm, "kD", markersize=8, label="datasheet (Fig 1)")
    ax.set_xlabel("I_F (mA)")
    ax.set_ylabel("r_on normalized (R/R_typ@16mA)")
    ax.set_title("Figure 1: R vs I_F")
    ax.grid(True, which="both", alpha=0.4)
    ax.legend()
    ax.set_xlim(0.5, 100)
    ax.set_ylim(0.2, 20)

    # Test 2: I-V at various I_F
    ax = axes[1]
    if r2 is not None:
        for i_f_mA, (v_46, i_46) in r2.items():
            ax.plot(v_46, i_46 * 1e6, lw=1.2, label=f"I_F={i_f_mA} mA")
    ax.set_xlabel("V_46 (V)")
    ax.set_ylabel("I_46 (µA)")
    ax.set_title("Figure 2: Output Characteristics (model)")
    ax.axhline(0, color="0.5", lw=0.5)
    ax.axvline(0, color="0.5", lw=0.5)
    ax.grid(True, alpha=0.4)
    ax.legend(fontsize=8)
    ax.set_xlim(-0.2, 0.2)
    ax.set_ylim(-800, 800)

    # Test 3: LED V_F vs I_F
    ax = axes[2]
    if r3 is not None:
        i_f, v_f = r3
        ax.semilogx(i_f * 1e3, v_f, "C0-", lw=1.5, label="model")
    # Datasheet typical curve at 25°C (Figure 3)
    ds_if = np.array([0.1, 0.3, 1, 3, 10, 30, 100])
    ds_vf = np.array([0.85, 1.0, 1.07, 1.15, 1.22, 1.30, 1.45])
    ax.semilogx(ds_if, ds_vf, "kD", markersize=8, label="datasheet (Fig 3, 25°C)")
    ax.set_xlabel("I_F (mA)")
    ax.set_ylabel("V_F (V)")
    ax.set_title("Figure 3: LED V_F vs I_F")
    ax.grid(True, which="both", alpha=0.4)
    ax.legend()
    ax.set_xlim(0.1, 100)
    ax.set_ylim(0.7, 2.0)

    fig.suptitle("H11F1 behavioural model validation vs Fairchild datasheet (3/19/03)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = HERE / "h11f_model_validate.png"
    fig.savefig(out, dpi=110)
    print(f"Wrote {out}")


def summary(r1, r2, r3):
    print()
    print("=== H11F1 model validation summary ===")
    if r1 is not None:
        i_f, r_46 = r1
        # spec test point: I_F=16 mA, expect R ≤ 200 Ω
        idx = np.argmin(np.abs(i_f - 16e-3))
        print(f"  R(I_F=16 mA) = {r_46[idx]:.1f} Ω   (datasheet H11F1 max: 200 Ω)")
        idx = np.argmin(np.abs(i_f - 1e-3))
        print(f"  R(I_F=1 mA)  = {r_46[idx]:.0f} Ω   (datasheet ~10× = 2000 Ω)")
        idx = np.argmin(np.abs(i_f - 50e-3))
        print(f"  R(I_F=50 mA) = {r_46[idx]:.0f} Ω   (datasheet ~0.5× = 100 Ω)")
    if r3 is not None:
        i_f, v_f = r3
        idx = np.argmin(np.abs(i_f - 16e-3))
        print(f"  V_F(16 mA)   = {v_f[idx]:.3f} V    (datasheet 1.25 V typ, 1.75 V max)")
        idx = np.argmin(np.abs(i_f - 1e-3))
        print(f"  V_F(1 mA)    = {v_f[idx]:.3f} V    (datasheet ~0.95 V)")


def main():
    print("Test 1: R_46 vs I_F")
    r1 = test1_R_vs_IF()
    print("Test 2: I-V at several I_F")
    r2 = test2_IV_at_IF()
    print("Test 3: LED V_F vs I_F")
    r3 = test3_LED_VF()
    summary(r1, r2, r3)
    plot_all(r1, r2, r3)


if __name__ == "__main__":
    main()
