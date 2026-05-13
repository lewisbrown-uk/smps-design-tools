"""Open-loop AC analysis of the CE MOSFET buffer.

Builds a minimal testbench with the same buffer topology as ILC1-1/7
(op-amp + CE-class-AB DMP3098L/DMN3404L pair, Zener bias chain, comp
cap, gate damping, into a 30 ohm load) and breaks the local feedback
loop with a 0-V-DC / 1-V-AC test source. Sweeps 1 Hz to 100 MHz to
expose the loop's gain crossover frequency, phase margin, and any
high-Q resonance.

The "break the loop" method here: insert a 0 V test source between
v_osc_drive and v_osc_drive_fb, with R_buf1_fb tapped from
v_osc_drive_fb. DC operating point is unchanged (test source = 0 V at
DC), so the bias chain settles normally; AC injects 1 V into the
feedback path. Loop gain T(s) = -V(v_osc_drive)/V(v_osc_drive_fb).
"""
from __future__ import annotations
import sys, subprocess
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
WORK = HERE / "_closedloop_test"
WORK.mkdir(exist_ok=True)


def build_netlist(comp_pf: float, r_obb: float, r_gate: float,
                  v_buf: float = 5.0, v_z: float = 4.3,
                  buf_fb: float = 9.1e3,
                  comp_zero_r: float = 0,
                  drain_snub_r: float = 0,
                  drain_snub_c: float = 0,
                  v_drv_dc: float = 0.0,
                  topology: str = "ce") -> str:
    pmos_path = (HERE / "spice_models" / "DMP3098L.spice.txt").as_posix()
    nmos_path = (HERE / "spice_models" / "DMN3404L.spice.txt").as_posix()
    opamp_lib = (HERE / "uopamp.lib").as_posix()
    if comp_pf == 0:
        comp_block = "* no comp"
    elif comp_zero_r == 0:
        comp_block = f"C_buf1_comp v_osc_drive_fb  n_buf_osc_sum {comp_pf:.4g}p"
    else:
        comp_block = (f"R_buf1_zero v_osc_drive_fb n_comp_zero {comp_zero_r:.4g}\n"
                      f"C_buf1_comp n_comp_zero n_buf_osc_sum {comp_pf:.4g}p")
    if drain_snub_c == 0:
        snub_block = "* no drain snubber"
    else:
        snub_block = (f"R_drain_snub v_osc_drive n_drain_snub {drain_snub_r:.4g}\n"
                      f"C_drain_snub n_drain_snub 0 {drain_snub_c:.4g}")
    if topology == "ce":
        # Common source: PMOS source at vcc_buf, drain at output (top);
        #                NMOS source at vee_buf, drain at output (bottom).
        mosfet_block = (
            "* MOSFETs (CE / common source) - drain at v_osc_drive\n"
            "XM_top     v_osc_drive g_top vcc_buf DMP3098L\n"
            "XM_bot     v_osc_drive g_bot vee_buf DMN3404L"
        )
    elif topology == "cc":
        # Source follower: NMOS drain at vcc_buf, source at output (top);
        #                  PMOS drain at vee_buf, source at output (bottom).
        # Note swap of NMOS/PMOS positions vs CE topology: in CC, the NMOS
        # is on top because its source follows the gate (positive output).
        mosfet_block = (
            "* MOSFETs (CC / source follower) - source at v_osc_drive\n"
            "XM_top     vcc_buf g_top v_osc_drive DMN3404L\n"
            "XM_bot     vee_buf g_bot v_osc_drive DMP3098L"
        )
    else:
        raise ValueError(f"Unknown topology: {topology}")
    return f"""* Buffer 1 isolated AC small-signal testbench
.include {opamp_lib}
.include {pmos_path}
.include {nmos_path}

* Rails
Vcc_buf vcc_buf 0 {v_buf:.3g}
Vee_buf vee_buf 0 -{v_buf:.3g}
Vcc vcc 0 9
Vee vee 0 -9

* AC test source: v_drv_dc V DC sets operating point, 0 V AC (loop probe is V_break)
V_test v_drv_atten 0 DC {v_drv_dc:.4g} AC 0

* Loop-break source: 0 V DC, 1 V AC. Inserted between v_osc_drive (real
* MOSFET drain) and v_osc_drive_fb (the node R_fb taps from). At DC the
* loop closes normally; AC sees a unit signal injected.
V_break v_osc_drive_fb v_osc_drive DC 0 AC 1

* Buffer 1 (CE MOSFET) - same topology as ILC1-1/7
XU_buf_osc n_buf_osc_sum 0 vcc_buf vee_buf n_buf_osc_out uopamp_lvl2 Avol=10meg GBW=4.5meg Rin=100g Rout=10 Iq=600u Ilimit=1 Vrail=100m Vmax=40 Vos=2.5e-3
R_buf1_in   v_drv_atten     n_buf_osc_sum 1k
R_buf1_fb   v_osc_drive_fb  n_buf_osc_sum {buf_fb:.6g}
{comp_block}
{snub_block}
* Bias chain (Zener clamp)
R_obb_top   vcc_buf         q_o_bp_top    {r_obb:.6g}
D_obb_top   n_buf_osc_out   q_o_bp_top    Dzen_obb
D_obb_bot   q_o_bn_bot      n_buf_osc_out Dzen_obb
R_obb_bot   q_o_bn_bot      vee_buf       {r_obb:.6g}
* Gate damping (g_top is gate of top device, g_bot of bottom)
R_gd_top    q_o_bp_top      g_top         {r_gate:.6g}
R_gd_bot    q_o_bn_bot      g_bot         {r_gate:.6g}
{mosfet_block}
* Output load: bridge thevenin (R_op + R_sense in parallel with reference arm)
R_load      v_osc_drive 0 30
.model Dzen_obb D(IS=10n N=1.0 RS=1 BV={v_z:.3g} IBV=100m CJO=80p TT=10n)

.control
op
ac dec 100 1 100Meg
wrdata {(WORK / 'ac_buf.data').as_posix()} v(v_osc_drive) v(v_osc_drive_fb)
.endcontrol
.end
"""


def run_and_load(comp_pf: float, r_obb: float, r_gate: float,
                 v_buf: float, v_z: float, buf_fb: float,
                 comp_zero_r: float = 0,
                 drain_snub_r: float = 0, drain_snub_c: float = 0,
                 v_drv_dc: float = 0.0,
                 topology: str = "ce"):
    netlist = build_netlist(comp_pf, r_obb, r_gate, v_buf, v_z, buf_fb,
                            comp_zero_r, drain_snub_r, drain_snub_c, v_drv_dc,
                            topology)
    cir = WORK / "ac_buf.cir"
    cir.write_text(netlist)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        print(res.stderr[-1500:]); raise SystemExit(1)
    # ngspice wrdata for AC analysis emits real/imag pairs per complex vector:
    # col 0: freq, col 1: re(v(v_osc_drive)), col 2: im(v(v_osc_drive)),
    # col 3: re(v(v_osc_drive_fb)), col 4: im(v(v_osc_drive_fb))
    d = np.loadtxt(WORK / "ac_buf.data")
    f = d[:, 0]
    v_drv = d[:, 1] + 1j * d[:, 2]
    v_fb  = d[:, 3] + 1j * d[:, 4]
    # Loop gain: signal at v_osc_drive (after going around the loop) divided
    # by V_break (which forces v_fb - v_drv = 1 V AC). With v_break inserted
    # so that v_fb = v_drv + 1, the signal at v_drv after looping is
    # T = -(v_drv) / 1 = -v_drv. Magnitude in dB; phase in degrees.
    T = -v_drv
    return f, T, v_fb


def plot_bode(f, T, label, ax_mag, ax_phase, color):
    mag_db = 20 * np.log10(np.abs(T))
    phase_deg = np.unwrap(np.angle(T)) * 180 / np.pi
    ax_mag.semilogx(f, mag_db, label=label, color=color)
    ax_phase.semilogx(f, phase_deg, label=label, color=color)


def main():
    # Sweep over a few comp / damping combinations.
    # Compare CE (common source) vs CC (source follower) topologies at
    # quiescent and conducting operating points. Source follower should be
    # inherently stable (no Miller, gain ~ 1) where common-source is not.
    sweeps = [
        ("CE quiescent",          dict(comp_pf=2200, r_gate=100, v_drv_dc=0.0,  topology="ce")),
        ("CE NMOS conducting",    dict(comp_pf=2200, r_gate=100, v_drv_dc=+0.4, topology="ce")),
        ("CE PMOS conducting",    dict(comp_pf=2200, r_gate=100, v_drv_dc=-0.4, topology="ce")),
        ("CC quiescent",          dict(comp_pf=0,    r_gate=100, v_drv_dc=0.0,  topology="cc")),
        ("CC NMOS conducting",    dict(comp_pf=0,    r_gate=100, v_drv_dc=+0.4, topology="cc")),
        ("CC PMOS conducting",    dict(comp_pf=0,    r_gate=100, v_drv_dc=-0.4, topology="cc")),
    ]
    fig, (ax_mag, ax_phase) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    for i, (label, kw) in enumerate(sweeps):
        f, T, _ = run_and_load(comp_pf=kw.get("comp_pf", 2200),
                               r_obb=kw.get("r_obb", 1300),
                               r_gate=kw.get("r_gate", 100),
                               v_buf=5.0, v_z=4.3, buf_fb=9.1e3,
                               comp_zero_r=kw.get("comp_zero_r", 0),
                               drain_snub_r=kw.get("drain_snub_r", 0),
                               drain_snub_c=kw.get("drain_snub_c", 0),
                               v_drv_dc=kw.get("v_drv_dc", 0.0),
                               topology=kw.get("topology", "ce"))
        plot_bode(f, T, label, ax_mag, ax_phase, f"C{i}")
        # Find unity-gain crossover
        mag_db = 20 * np.log10(np.abs(T))
        zero_xings = np.where(np.diff(np.sign(mag_db)))[0]
        if len(zero_xings) > 0:
            f_unity = f[zero_xings[0]]
            phase_at_unity = np.unwrap(np.angle(T))[zero_xings[0]] * 180 / np.pi
            # Phase margin = 180 + phase_at_unity (for a stable system, want > 30 deg)
            pm = 180 + phase_at_unity
            print(f"{label:25s}: f_unity = {f_unity:8.0f} Hz, phase = {phase_at_unity:+7.1f} deg, PM = {pm:+6.1f} deg")
        else:
            print(f"{label:25s}: no unity gain crossing in 1 Hz - 100 MHz")
        # Find resonance peaks (mag_db local maxima above 0 dB)
        peak_freqs = []
        for j in range(1, len(mag_db)-1):
            if mag_db[j] > mag_db[j-1] and mag_db[j] > mag_db[j+1] and mag_db[j] > 0:
                peak_freqs.append((f[j], mag_db[j]))
        if peak_freqs:
            print(f"{'':25s}  peaks above 0 dB: " +
                  ", ".join(f"{fp:.0f} Hz @ {mp:.1f} dB" for fp, mp in peak_freqs[:4]))
    ax_mag.axhline(0, color="0.5", ls="--", lw=0.6)
    ax_mag.set_ylabel("|T(jw)| [dB]")
    ax_mag.set_title("Open-loop gain of buffer 1 (ILC1-1/7 CE MOSFET, manufacturer model)")
    ax_mag.legend(fontsize=8, loc="upper right")
    ax_mag.grid(True, which="both", alpha=0.4)
    ax_phase.axhline(-180, color="0.5", ls="--", lw=0.6)
    ax_phase.set_ylabel("arg T(jw) [deg]")
    ax_phase.set_xlabel("freq [Hz]")
    ax_phase.legend(fontsize=8, loc="upper right")
    ax_phase.grid(True, which="both", alpha=0.4)
    fig.tight_layout()
    out = HERE / "ac_buf_bode.png"
    fig.savefig(out, dpi=130); plt.close(fig)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
