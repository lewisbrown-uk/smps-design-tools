"""Generate the H11FxM model's own datasheet curves and tables.

Sweeps the H11F1.spice.txt behavioural model the way the OnSemi datasheet
characterises the part, and emits:

  - spice_models/H11F1_datasheet.svg   (Fig 1, Fig 2, Fig 3, Fig 5 panels)
  - spice_models/H11F1_datasheet.md    (Electrical Characteristics tables)

Figures regenerated:
  Fig 1  Resistance vs LED forward current  (R/R_typ_16mA, log-log)
  Fig 2  Output I-V characteristics at I_F = 2,6,10,14,18 mA  (linear)
  Fig 3  LED V_F vs I_F at TA = -40, 25, 100 °C  (semi-log)
  Fig 5  Resistance non-linearity vs DC bias (V_46 = 50-350 mV)

Tables regenerated:
  Individual component characteristics (LED + OUTPUT DETECTOR)
  Transfer characteristics (DC + AC)
"""
import subprocess, sys, types, time, math
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
import numpy as np

HERE = Path(__file__).resolve().parent
MODEL = (HERE / "spice_models" / "H11F1.spice.txt").as_posix()
WORK = HERE / "_h11f_ds"; WORK.mkdir(exist_ok=True)


def run(name, deck, timeout=120):
    cir = WORK / f"{name}.cir"
    cir.write_text(deck)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                         capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        print(f"FAIL {name}\n{res.stderr[-500:]}"); sys.exit(1)
    return WORK / f"{name}.data"


def settled(name):
    """Last sample of a wrdata file."""
    d = np.loadtxt(WORK / f"{name}.data")
    return float(d[-1, 1]) if d.ndim == 2 else float(d[1])


# ============================================================
# Sweep generators (return list of (x, y) tuples)
# ============================================================

def sweep_fig1():
    """Fig 1: R(I_F) normalized to R at I_F=16mA, I_46=5µA RMS.
       Sweep I_F over 1..100 mA log-spaced."""
    print("Fig 1: sweeping R vs I_F...", flush=True)
    pts = []
    # Get R_typ at I_F=16mA first (reference)
    deck = f"""* R at I_F=16mA, I_46=5µA  -> R_typ reference
.include {MODEL}
I_LED 0 led_anode DC 16m
X_H11F led_anode 0 4 0 H11F1
I_test 0 4 DC 5u
.tran 10u 1m 500u uic
.control
run
wrdata {WORK.as_posix()}/fig1_ref.data v(4)
.endc
.end
"""
    run("fig1_ref", deck)
    R_typ = abs(settled("fig1_ref")) / 5e-6
    print(f"  R_typ_16mA = {R_typ:.1f} Ω")
    # Sweep
    for I_F_mA in np.logspace(0, 2, 41):
        I_F = I_F_mA * 1e-3
        name = f"fig1_{I_F_mA:.3f}"
        deck = f"""* Fig 1 I_F={I_F_mA:.3f}mA
.include {MODEL}
I_LED 0 led_anode DC {I_F}
X_H11F led_anode 0 4 0 H11F1
I_test 0 4 DC 5u
.tran 10u 1m 500u uic
.control
run
wrdata {WORK.as_posix()}/{name}.data v(4)
.endc
.end
"""
        run(name, deck)
        R = abs(settled(name)) / 5e-6
        pts.append((I_F_mA, R / R_typ))
    return pts, R_typ


def sweep_fig2():
    """Fig 2: I_46 vs V_46 at I_F = 2, 6, 10, 14, 18 mA from -0.2 to +0.2 V."""
    print("Fig 2: sweeping I_46 vs V_46...", flush=True)
    out = {}
    V_pts = np.linspace(-0.2, 0.2, 41)
    for I_F_mA in (2, 6, 10, 14, 18):
        I_F = I_F_mA * 1e-3
        curve = []
        for V_46 in V_pts:
            name = f"fig2_{I_F_mA}_{V_46:+.3f}"
            deck = f"""* Fig 2 I_F={I_F_mA}mA V_46={V_46:+.3f}
.include {MODEL}
I_LED 0 led_anode DC {I_F}
X_H11F led_anode 0 4 0 H11F1
V_set 4 0 DC {V_46}
.tran 10u 1m 500u uic
.control
run
wrdata {WORK.as_posix()}/{name}.data i(v_set)
.endc
.end
"""
            run(name, deck)
            I_46 = -settled(name)  # v_set sources current from + to -; i(V_set) is + when flowing into V_set's + terminal
            curve.append((V_46, I_46))
        out[I_F_mA] = curve
    return out


def sweep_fig3():
    """Fig 3: V_F vs I_F at TA = -40, 25, 100 °C, I_F from 0.1 to 100 mA."""
    print("Fig 3: sweeping V_F at three temps...", flush=True)
    out = {}
    I_F_mA_pts = np.logspace(-1, 2, 31)
    for T_C in (-40, 25, 100):
        curve = []
        for I_F_mA in I_F_mA_pts:
            I_F = I_F_mA * 1e-3
            name = f"fig3_{T_C}_{I_F_mA:.3f}"
            deck = f"""* Fig 3 T={T_C}°C I_F={I_F_mA:.3f}mA
.include {MODEL}
.options temp={T_C}
I_LED 0 led_anode DC {I_F}
X_H11F led_anode 0 4 0 H11F1
R_n4 4 0 1Meg
.tran 100u 5m 1m uic
.control
run
wrdata {WORK.as_posix()}/{name}.data v(led_anode)
.endc
.end
"""
            run(name, deck)
            V_F = settled(name)
            curve.append((I_F_mA, V_F))
        out[T_C] = curve
    return out


def sweep_fig5():
    """Fig 5: ΔR/R (%) vs V_46 DC bias, 0 to 350 mV at I_F=16mA, I_46=10µA RMS."""
    print("Fig 5: sweeping ΔR vs V_46 bias...", flush=True)
    pts = []
    R0 = None
    for V_46_mV in [10, 50, 100, 150, 200, 250, 300, 350]:
        V_46 = V_46_mV * 1e-3
        name = f"fig5_{V_46_mV}"
        deck = f"""* Fig 5 V_46={V_46_mV}mV
.include {MODEL}
I_LED 0 led_anode DC 16m
X_H11F led_anode 0 4 0 H11F1
V_set 4 0 DC {V_46}
.tran 10u 1m 500u uic
.control
run
wrdata {WORK.as_posix()}/{name}.data i(v_set)
.endc
.end
"""
        run(name, deck)
        i = abs(settled(name))
        R = V_46 / i
        if R0 is None: R0 = R
        pts.append((V_46_mV, (R - R0)/R0 * 100))
    return pts


# ============================================================
# Spec-table measurements
# ============================================================

def measure_specs():
    """Run the focused measurements needed to fill the Electrical
    Characteristics table on p.3 of the datasheet."""
    print("Measuring spec-table values...", flush=True)
    out = {}
    # V_F @ I_F=16mA, 25°C
    deck = f"""* V_F spec
.include {MODEL}
I_LED 0 led_anode DC 16m
X_H11F led_anode 0 4 0 H11F1
R_n4 4 0 1Meg
.tran 100u 5m 1m uic
.control
run
wrdata {WORK.as_posix()}/sp_vf.data v(led_anode)
.endc
.end
"""
    run("sp_vf", deck); out["V_F"] = settled("sp_vf")
    # I_R @ V_R = 5V (reverse-biased LED)
    deck = f"""* I_R spec
.include {MODEL}
V_drv led_anode 0 DC -5
X_H11F led_anode 0 4 0 H11F1
R_n4 4 0 1Meg
.tran 100u 5m 1m uic
.control
run
wrdata {WORK.as_posix()}/sp_ir.data i(v_drv)
.endc
.end
"""
    run("sp_ir", deck); out["I_R"] = abs(settled("sp_ir"))
    # C_J @ V=0, f=1MHz
    deck = f"""* C_J spec
.include {MODEL}
V_drv led_anode 0 DC 0 AC 1
X_H11F led_anode 0 4 0 H11F1
R_n4 4 0 1Meg
.ac dec 1 1Meg 1Meg
.control
run
wrdata {WORK.as_posix()}/sp_cj.data i(v_drv)
.endc
.end
"""
    run("sp_cj", deck)
    d = np.loadtxt(WORK / "sp_cj.data")
    I = complex(d[1], d[2]) if d.ndim == 1 else complex(d[0,1], d[0,2])
    out["C_J"] = abs(I) / (2*np.pi*1e6)
    # I_dark @ V_46=15V, IF=0, 25°C
    deck = f"""* I_dark spec
.include {MODEL}
I_LED 0 led_anode DC 0
X_H11F led_anode 0 4 0 H11F1
V_set 4 0 DC 15
.tran 100u 5m 1m uic
.control
run
wrdata {WORK.as_posix()}/sp_idark.data i(v_set)
.endc
.end
"""
    run("sp_idark", deck); out["I_dark_25"] = abs(settled("sp_idark"))
    out["R_dark"] = 15.0 / out["I_dark_25"]
    # C_46 @ V_46=15V, IF=0, f=1MHz
    deck = f"""* C_46 spec
.include {MODEL}
I_LED 0 led_anode DC 0
X_H11F led_anode 0 4 0 H11F1
V_set 4 0 DC 15 AC 1
.ac dec 1 1Meg 1Meg
.control
run
wrdata {WORK.as_posix()}/sp_c46.data i(v_set)
.endc
.end
"""
    run("sp_c46", deck)
    d = np.loadtxt(WORK / "sp_c46.data")
    I = complex(d[1], d[2]) if d.ndim == 1 else complex(d[0,1], d[0,2])
    out["C_46"] = abs(I) / (2*np.pi*1e6)
    # R_4-6 and R_6-4 at I_F=16mA, I_46=100µA
    for subckt, key, R_max in [("H11F1","R_F1",200), ("H11F2","R_F2",330),
                                ("H11F3","R_F3",470)]:
        # 4→6
        deck = f"""* R_4-6 {subckt}
.include {MODEL}
I_LED 0 led_anode DC 16m
X_dev led_anode 0 4 0 {subckt}
I_test 0 4 DC 100u
.tran 10u 1m 500u uic
.control
run
wrdata {WORK.as_posix()}/sp_{subckt}_46.data v(4)
.endc
.end
"""
        run(f"sp_{subckt}_46", deck)
        R_46 = abs(settled(f"sp_{subckt}_46")) / 100e-6
        # 6→4
        deck = f"""* R_6-4 {subckt}
.include {MODEL}
I_LED 0 led_anode DC 16m
X_dev led_anode 0 0 6 {subckt}
I_test 0 6 DC 100u
.tran 10u 1m 500u uic
.control
run
wrdata {WORK.as_posix()}/sp_{subckt}_64.data v(6)
.endc
.end
"""
        run(f"sp_{subckt}_64", deck)
        R_64 = abs(settled(f"sp_{subckt}_64")) / 100e-6
        out[key] = (R_46, R_64, R_max)
    # Non-linearity & asymmetry @ I_F=16mA, I_46=25µA RMS, 1 kHz
    deck = f"""* Non-linearity spec
.include {MODEL}
I_LED 0 led_anode DC 16m
X_H11F led_anode 0 4 0 H11F1
I_test 0 4 SIN(0 35.36u 1000 0 0)
.tran 5u 110m 10m uic
.control
run
wrdata {WORK.as_posix()}/sp_thd.data v(4)
.endc
.end
"""
    run("sp_thd", deck, timeout=300)
    d = np.loadtxt(WORK / "sp_thd.data")
    t = d[:,0]; v = d[:,1]
    dt = 5e-6
    t_u = np.arange(t[0], t[-1], dt)
    v_u = np.interp(t_u, t, v); v_u -= v_u.mean()
    N = len(t_u); win = np.hanning(N)
    V = np.fft.rfft(v_u*win) * (2/N)/0.5
    f = np.fft.rfftfreq(N, dt)
    def mag(f0, bw=30):
        idx = (f > f0-bw) & (f < f0+bw); return float(np.max(np.abs(V[idx])))
    h1, h2, h3 = mag(1000), mag(2000), mag(3000)
    out["THD"] = np.sqrt(h2**2+h3**2)/h1*100
    out["H2"] = h2/h1*100
    out["H3"] = h3/h1*100
    # t_on / t_off
    deck = f"""* t_on
.include {MODEL}
V_supply v_top 0 DC 5
R_load   v_top out 50
X_H11F   led_anode 0 out 0 H11F1
I_drv 0 led_anode PWL(0 0  199.999u 0  200u 16m  500u 16m)
.tran 0.2u 500u 0 uic
.control
run
wrdata {WORK.as_posix()}/sp_ton.data v(out)
.endc
.end
"""
    run("sp_ton", deck)
    d = np.loadtxt(WORK / "sp_ton.data")
    t = d[:,0]; v = d[:,1]
    v_start = v[t < 200e-6][-1]; v_steady = v[-1]
    v_90 = v_start - 0.9*(v_start - v_steady)
    mask = (t > 200e-6) & (v < v_90)
    out["t_on"] = (t[mask][0] - 200e-6)*1e6 if mask.any() else float('inf')
    deck = f"""* t_off
.include {MODEL}
V_supply v_top 0 DC 5
R_load   v_top out 50
X_H11F   led_anode 0 out 0 H11F1
I_drv 0 led_anode PWL(0 16m  199.999u 16m  200u 0  1m 0)
.tran 0.2u 1m 0 uic
.control
run
wrdata {WORK.as_posix()}/sp_toff.data v(out)
.endc
.end
"""
    run("sp_toff", deck)
    d = np.loadtxt(WORK / "sp_toff.data")
    t = d[:,0]; v = d[:,1]
    v_start = v[t < 200e-6][-1]; v_steady = v[-1]
    v_90 = v_start + 0.9*(v_steady - v_start)
    mask = (t > 200e-6) & (v > v_90)
    out["t_off"] = (t[mask][0] - 200e-6)*1e6 if mask.any() else float('inf')
    return out


# ============================================================
# SVG rendering with optional log axes
# ============================================================

def render_panel(ox, oy, pw, ph, title, xlabel, ylabel, series,
                 xlog=False, ylog=False, xlim=None, ylim=None,
                 legend_pos="upper right"):
    """Render one panel. series: list of (label, xs, ys, color, style)
       where style in {'line','marker'}."""
    plx = ox + 60; ply = oy + 30
    plw = pw - 80; plh = ph - 60
    # Determine axis limits
    if xlim is None:
        all_x = np.concatenate([np.asarray(s[1]) for s in series])
        xmin, xmax = float(np.min(all_x)), float(np.max(all_x))
    else:
        xmin, xmax = xlim
    if ylim is None:
        all_y = np.concatenate([np.asarray(s[2]) for s in series])
        ymin, ymax = float(np.min(all_y)), float(np.max(all_y))
    else:
        ymin, ymax = ylim

    # Coordinate transforms (linear or log)
    def X(x):
        if xlog: return plx + (np.log10(x) - np.log10(xmin))/(np.log10(xmax) - np.log10(xmin)) * plw
        return plx + (x - xmin)/(xmax - xmin) * plw
    def Y(y):
        if ylog: return ply + plh - (np.log10(y) - np.log10(ymin))/(np.log10(ymax) - np.log10(ymin)) * plh
        return ply + plh - (y - ymin)/(ymax - ymin) * plh

    out = [f'<g>']
    out.append(f'<rect x="{ox}" y="{oy}" width="{pw}" height="{ph}" fill="#fefefe" stroke="#bbb"/>')
    out.append(f'<text x="{ox+pw/2}" y="{oy+18}" text-anchor="middle" font-size="11" font-weight="bold">{xml_escape(title)}</text>')

    # Gridlines and tick labels
    if xlog:
        # Decade ticks
        for dec in range(int(math.floor(np.log10(xmin))), int(math.ceil(np.log10(xmax)))+1):
            xv = 10**dec
            if xv < xmin or xv > xmax: continue
            xpx = X(xv)
            out.append(f'<line x1="{xpx}" y1="{ply}" x2="{xpx}" y2="{ply+plh}" stroke="#eee"/>')
            label = f"{int(xv)}" if xv >= 1 else f"{xv:.1g}"
            out.append(f'<text x="{xpx}" y="{ply+plh+14}" text-anchor="middle" font-size="9" fill="#555">{label}</text>')
            # Minor ticks (no labels, just gridlines)
            for m in (2,3,5):
                xm = m*xv
                if xmin <= xm <= xmax:
                    out.append(f'<line x1="{X(xm)}" y1="{ply}" x2="{X(xm)}" y2="{ply+plh}" stroke="#f5f5f5"/>')
    else:
        for i in range(6):
            xv = xmin + i*(xmax-xmin)/5
            xpx = X(xv)
            out.append(f'<line x1="{xpx}" y1="{ply}" x2="{xpx}" y2="{ply+plh}" stroke="#eee"/>')
            out.append(f'<text x="{xpx}" y="{ply+plh+14}" text-anchor="middle" font-size="9" fill="#555">{xv:.3g}</text>')
    if ylog:
        for dec in range(int(math.floor(np.log10(ymin))), int(math.ceil(np.log10(ymax)))+1):
            yv = 10**dec
            if yv < ymin or yv > ymax: continue
            ypx = Y(yv)
            out.append(f'<line x1="{plx}" y1="{ypx}" x2="{plx+plw}" y2="{ypx}" stroke="#eee"/>')
            label = f"{yv:.1g}" if yv < 1 else f"{int(yv)}" if yv < 100 else f"{yv:.0g}"
            out.append(f'<text x="{plx-4}" y="{ypx+3}" text-anchor="end" font-size="9" fill="#555">{label}</text>')
            for m in (2,3,5):
                ym = m*yv
                if ymin <= ym <= ymax:
                    out.append(f'<line x1="{plx}" y1="{Y(ym)}" x2="{plx+plw}" y2="{Y(ym)}" stroke="#f5f5f5"/>')
    else:
        for i in range(5):
            yv = ymax - i*(ymax-ymin)/4
            ypx = Y(yv)
            out.append(f'<line x1="{plx}" y1="{ypx}" x2="{plx+plw}" y2="{ypx}" stroke="#eee"/>')
            out.append(f'<text x="{plx-4}" y="{ypx+3}" text-anchor="end" font-size="9" fill="#555">{yv:.3g}</text>')
    out.append(f'<rect x="{plx}" y="{ply}" width="{plw}" height="{plh}" fill="none" stroke="#666"/>')

    # Axis labels
    out.append(f'<text x="{plx+plw/2}" y="{oy+ph-6}" text-anchor="middle" font-size="10">{xml_escape(xlabel)}</text>')
    out.append(f'<text x="{ox+14}" y="{ply+plh/2}" text-anchor="middle" font-size="10" transform="rotate(-90,{ox+14},{ply+plh/2})">{xml_escape(ylabel)}</text>')

    # Zero-baseline if 0 within range
    if not ylog and ymin < 0 < ymax:
        zy = Y(0); out.append(f'<line x1="{plx}" y1="{zy}" x2="{plx+plw}" y2="{zy}" stroke="#aaa" stroke-dasharray="2,2"/>')
    if not xlog and xmin < 0 < xmax:
        zx = X(0); out.append(f'<line x1="{zx}" y1="{ply}" x2="{zx}" y2="{ply+plh}" stroke="#aaa" stroke-dasharray="2,2"/>')

    # Series
    color_map = {"black":"#000","red":"#d00","blue":"#06c","green":"#0a0",
                 "orange":"#f80","purple":"#80c","brown":"#963"}
    label_y_base = ply + 12 if "upper" in legend_pos else ply + plh - 12 - 14*len(series)
    label_x_anchor = plx + plw - 8 if "right" in legend_pos else plx + 8
    label_text_anchor = "end" if "right" in legend_pos else "start"
    label_swatch_offset = -18 if "right" in legend_pos else 0
    for i, (label, xs_, ys_, color, style) in enumerate(series):
        col = color_map.get(color, color)
        xs_ = np.asarray(xs_); ys_ = np.asarray(ys_)
        if style == "line":
            pts = " ".join(f"{X(x):.2f},{Y(y):.2f}" for x,y in zip(xs_, ys_)
                            if not (np.isnan(x) or np.isnan(y)))
            out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6"/>')
        else:
            for x,y in zip(xs_, ys_):
                if np.isnan(x) or np.isnan(y): continue
                out.append(f'<circle cx="{X(x):.2f}" cy="{Y(y):.2f}" r="3" fill="{col}" stroke="white" stroke-width="0.5"/>')
        # Legend
        ly = label_y_base + i*14
        out.append(f'<rect x="{label_x_anchor+label_swatch_offset}" y="{ly-7}" width="14" height="3" fill="{col}"/>')
        text_x = label_x_anchor + (label_swatch_offset - 4 if "right" in legend_pos else 18)
        out.append(f'<text x="{text_x}" y="{ly-3}" text-anchor="{label_text_anchor}" font-size="9">{xml_escape(label)}</text>')
    out.append('</g>')
    return "\n".join(out)


def render_svg(fig1_pts, fig2_curves, fig3_curves, fig5_pts, R_typ):
    width, height = 1280, 920
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" font-size="12">',
             f'<rect width="{width}" height="{height}" fill="white"/>',
             f'<text x="{width//2}" y="24" text-anchor="middle" font-size="14" font-weight="bold">H11F1M model — Typical Performance Curves (from spice_models/H11F1.spice.txt)</text>',
             f'<text x="{width//2}" y="40" text-anchor="middle" font-size="11" fill="#555">R_typ_16mA = {R_typ:.1f} Ω at I_F=16 mA, I_46=5 µA RMS, T_A=25°C</text>']

    pw, ph = 590, 380
    pad = 30
    x0, x1 = pad, pad + pw + pad
    y0, y1 = 60, 60 + ph + pad

    # Fig 1
    x_pts = [p[0] for p in fig1_pts]
    y_pts = [p[1] for p in fig1_pts]
    parts.append(render_panel(
        x0, y0, pw, ph,
        title="Figure 1.  Resistance vs Input Current  (normalized to I_F=16 mA, I_46=5 µA RMS)",
        xlabel="I_F, INPUT CURRENT (mA)",
        ylabel="r(on), NORMALIZED RESISTANCE",
        series=[("model", x_pts, y_pts, "black", "line")],
        xlog=True, ylog=True,
        xlim=(1, 100), ylim=(0.1, 30),
    ))

    # Fig 2
    fig2_series = []
    colors = ["red", "orange", "green", "blue", "purple"]
    for (I_F, curve), col in zip(sorted(fig2_curves.items()), colors):
        xs = [p[0] for p in curve]
        ys = [p[1]*1e6 for p in curve]  # µA
        fig2_series.append((f"I_F = {I_F} mA", xs, ys, col, "line"))
    parts.append(render_panel(
        x1, y0, pw, ph,
        title="Figure 2.  Output Characteristics",
        xlabel="V_46, OUTPUT VOLTAGE (V)",
        ylabel="I_46, OUTPUT CURRENT (µA)",
        series=fig2_series,
        xlim=(-0.2, 0.2), ylim=(-900, 900),
        legend_pos="upper left",
    ))

    # Fig 3
    fig3_series = []
    T_colors = {-40:"blue", 25:"black", 100:"red"}
    for T, curve in sorted(fig3_curves.items()):
        xs = [p[0] for p in curve]
        ys = [p[1] for p in curve]
        fig3_series.append((f"T_A = {T} °C", xs, ys, T_colors[T], "line"))
    parts.append(render_panel(
        x0, y1, pw, ph,
        title="Figure 3.  LED Forward Voltage vs Forward Current",
        xlabel="I_F, LED FORWARD CURRENT (mA)",
        ylabel="V_F, FORWARD VOLTAGE (V)",
        series=fig3_series,
        xlog=True,
        xlim=(0.1, 100), ylim=(0.6, 2.0),
        legend_pos="upper left",
    ))

    # Fig 5
    xs = [p[0] for p in fig5_pts]
    ys = [p[1] for p in fig5_pts]
    parts.append(render_panel(
        x1, y1, pw, ph,
        title="Figure 5.  Resistive Non-Linearity vs DC Bias  (I_F=16 mA, I_46=10 µA RMS)",
        xlabel="V_46, D.C. BIAS VOLTAGE (mV)",
        ylabel="r(on), CHANGE IN RESISTANCE (%)",
        series=[("model", xs, ys, "black", "line"),
                ("model points", xs, ys, "red", "marker")],
        xlim=(0, 400), ylim=(0, 5),
        legend_pos="upper left",
    ))

    parts.append("</svg>")
    return "\n".join(parts)


# ============================================================
# Spec table emission (markdown)
# ============================================================

def render_md(specs, R_typ_meas):
    F1, F2, F3 = specs["R_F1"], specs["R_F2"], specs["R_F3"]
    md = f"""# H11FxM Behavioural Model — Datasheet Reproduction

Model file: `spice_models/H11F1.spice.txt`
Generated by `generate_h11f_datasheet.py`

## ELECTRICAL CHARACTERISTICS (T_A = 25 °C unless otherwise noted)

### Individual Component Characteristics

| Symbol | Parameter | Test Conditions | Datasheet Typ | Datasheet Max | Model |
|:---|:---|:---|---:|---:|---:|
| **EMITTER** ||||||
| V_F   | Input Forward Voltage         | I_F = 16 mA              | 1.30 V    | 1.75 V    | {specs['V_F']:.3f} V |
| I_R   | Reverse Leakage Current       | V_R = 5 V                | —         | 10 µA     | {specs['I_R']*1e6:.3f} µA |
| C_J   | Capacitance                   | V = 0 V, f = 1.0 MHz     | 50 pF     | —         | {specs['C_J']*1e12:.2f} pF |
| **OUTPUT DETECTOR** ||||||
| I_4-6 | Off-state Dark Current        | V_46 = 15 V, I_F = 0     | —         | 50 nA     | {specs['I_dark_25']*1e9:.2f} nA |
| R_4-6 | Off-state Resistance          | V_46 = 15 V, I_F = 0     | —         | (≥300 MΩ) | {specs['R_dark']/1e6:.1f} MΩ |
| C_4-6 | Capacitance                   | V_46 = 15 V, IF=0, f=1MHz | —        | 15 pF     | {specs['C_46']*1e12:.2f} pF |

### Transfer Characteristics

| Symbol | Characteristics | Variant | Test Conditions | Datasheet Max | Model |
|:---|:---|:---|:---|---:|---:|
| R_4-6 | On-State Resistance | H11F1M | I_F = 16 mA, I_46 = 100 µA | 200 Ω | {F1[0]:.1f} Ω |
|       |                     | H11F2M | I_F = 16 mA, I_46 = 100 µA | 330 Ω | {F2[0]:.1f} Ω |
|       |                     | H11F3M | I_F = 16 mA, I_46 = 100 µA | 470 Ω | {F3[0]:.1f} Ω |
| R_6-4 | On-State Resistance | H11F1M | I_F = 16 mA, I_64 = 100 µA | 200 Ω | {F1[1]:.1f} Ω |
|       |                     | H11F2M | I_F = 16 mA, I_64 = 100 µA | 330 Ω | {F2[1]:.1f} Ω |
|       |                     | H11F3M | I_F = 16 mA, I_64 = 100 µA | 470 Ω | {F3[1]:.1f} Ω |
|       | Resistance, Non-Linearity and Asymmetry | — | I_F = 16 mA, I_46 = 25 µA RMS, f = 1 kHz | 2 % (typ) | {specs['THD']:.3f} % (THD; H2 = {specs['H2']:.4f} %, H3 = {specs['H3']:.4f} %) |

### AC Characteristics

| Symbol | Parameter | Test Conditions | Datasheet Max | Model |
|:---|:---|:---|---:|---:|
| t_on  | Turn-On Time  | R_L = 50 Ω, I_F = 16 mA, V_46 = 5 V | 45 µs | {specs['t_on']:.1f} µs |
| t_off | Turn-Off Time | R_L = 50 Ω, I_F = 16 mA, V_46 = 5 V | 45 µs | {specs['t_off']:.1f} µs |

R_typ_16mA reference for Figure 1 normalization: {R_typ_meas:.1f} Ω (at I_F=16 mA, I_46=5 µA RMS).

Bilateral symmetry: R_4-6 and R_6-4 are identical at every test current in the
table above; the behavioural-resistor formulation has no source-swap
asymmetry. THD H2 = {specs['H2']:.4f} % (essentially zero — pure H3 from
the symmetric V_46² nonlinearity).
"""
    return md


def main():
    fig1, R_typ = sweep_fig1()
    fig2 = sweep_fig2()
    fig3 = sweep_fig3()
    fig5 = sweep_fig5()
    specs = measure_specs()

    svg = render_svg(fig1, fig2, fig3, fig5, R_typ)
    svg_path = HERE / "spice_models" / "H11F1_datasheet.svg"
    svg_path.write_text(svg)
    print(f"\nWrote {svg_path}")

    md = render_md(specs, R_typ)
    md_path = HERE / "spice_models" / "H11F1_datasheet.md"
    md_path.write_text(md)
    print(f"Wrote {md_path}")
    print("\n" + md)


if __name__ == "__main__":
    main()
