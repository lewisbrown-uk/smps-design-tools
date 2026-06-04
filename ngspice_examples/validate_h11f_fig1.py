"""Fig 1 chart: model R(I_F) curve overlaid with user's 21 digitised Fig 1 points.

R_norm = R / R_typ_16mA, plotted vs I_F (mA).  Log-log axes.
"""
import subprocess, numpy as np, sys, re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

HERE = Path(__file__).resolve().parent
WORK = HERE / "_h11f_fig1_validate"; WORK.mkdir(exist_ok=True)
MODEL = HERE / "spice_models" / "H11F1.spice.txt"
DATA = HERE / "spice_models" / "H11F1_digitisation.txt"
R_TYP = 100.0  # R_typ_16mA in Ω


def parse_fig1():
    text = DATA.read_text()
    out = []
    in_fig1 = False
    for line in text.splitlines():
        s = line.strip()
        if not s: continue
        if s == "Fig 1": in_fig1 = True; continue
        if s.startswith("Fig "): in_fig1 = False
        if not in_fig1: continue
        if re.match(r"^-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?$", s):
            parts = re.split(r"\s*,\s*", s)
            out.append((float(parts[0]), float(parts[1])))
    # Convert Y to R/R_typ: R/R_typ = 5.005 / Y (derived from Y_at_I_F=16mA = 5.005)
    Y_norm = 5.005
    return [(I_F, Y_norm / Y) for (I_F, Y) in out]


def sim_R_at_IF(I_F_mA):
    """Measure small-signal R at V_46=0 by applying tiny AC voltage."""
    label = f"r_at_{I_F_mA*100:.0f}"
    cir = WORK / f"{label}.cir"
    dat = WORK / f"{label}.data"
    deck = f"""* Small-signal R at I_F={I_F_mA} mA
.include {MODEL}
I_LED 0 led_a DC {I_F_mA*1e-3}
X_H11F led_a 0 4 0 H11F1
V_test 4 0 DC 0
.dc V_test -1m 1m 0.5m
.control
run
wrdata {dat.as_posix()} v(4) i(V_test)
.endc
.end
"""
    cir.write_text(deck)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        return None, res.stderr[-300:]
    d = np.loadtxt(dat)
    # Two-point slope: I at V=-1mV and V=+1mV
    V_vals = d[:, 1]
    I_vals = -d[:, 3]  # Same sign convention as Fig 2 script
    # R = ΔV/ΔI
    dV = V_vals[-1] - V_vals[0]
    dI = I_vals[-1] - I_vals[0]
    R = abs(dV / dI)
    return R, None


def panel_xy_log(ox, oy, pw, ph, *, title, xlabel, ylabel, xlim, ylim, series,
                  xlog=True, ylog=True):
    """Render a single XY chart panel with optional log axes."""
    pad_left, pad_right, pad_top, pad_bot = 70, 20, 30, 40
    plx = ox + pad_left
    ply = oy + pad_top
    plw = pw - pad_left - pad_right
    plh = ph - pad_top - pad_bot
    xmin, xmax = xlim; ymin, ymax = ylim

    def lx(x): return np.log10(x) if xlog else x
    def ly(y): return np.log10(y) if ylog else y
    lxmin, lxmax = lx(xmin), lx(xmax)
    lymin, lymax = ly(ymin), ly(ymax)

    def X(x): return plx + (lx(x) - lxmin) / (lxmax - lxmin) * plw
    def Y(y): return ply + (1 - (ly(y) - lymin) / (lymax - lymin)) * plh

    out = [f'<g>',
           f'<text x="{plx + plw/2}" y="{oy + pad_top - 6}" text-anchor="middle" '
           f'font-size="12" font-weight="bold">{xml_escape(title)}</text>',
           f'<rect x="{plx}" y="{ply}" width="{plw}" height="{plh}" fill="none" stroke="#666"/>']

    # X gridlines (decade boundaries + intermediate)
    if xlog:
        for decade in range(int(np.floor(lxmin)), int(np.ceil(lxmax))+1):
            for sub in [1, 2, 3, 5]:
                val = sub * 10**decade
                if not (xmin <= val <= xmax): continue
                xpx = X(val)
                lw = 1.0 if sub == 1 else 0.5
                color = "#bbb" if sub == 1 else "#eee"
                out.append(f'<line x1="{xpx}" y1="{ply}" x2="{xpx}" y2="{ply+plh}" stroke="{color}" stroke-width="{lw}"/>')
                if sub == 1:
                    label = f"{val:g}" if val >= 1 else f"{val:.1f}"
                    out.append(f'<text x="{xpx}" y="{ply+plh+13}" text-anchor="middle" font-size="10" fill="#555">{label}</text>')
    # Y gridlines
    if ylog:
        for decade in range(int(np.floor(lymin)), int(np.ceil(lymax))+1):
            for sub in [1, 2, 3, 5]:
                val = sub * 10**decade
                if not (ymin <= val <= ymax): continue
                ypx = Y(val)
                lw = 1.0 if sub == 1 else 0.5
                color = "#bbb" if sub == 1 else "#eee"
                out.append(f'<line x1="{plx}" y1="{ypx}" x2="{plx+plw}" y2="{ypx}" stroke="{color}" stroke-width="{lw}"/>')
                if sub == 1:
                    label = f"{val:g}" if val >= 1 else f"{val:.1f}"
                    out.append(f'<text x="{plx-5}" y="{ypx+3}" text-anchor="end" font-size="10" fill="#555">{label}</text>')

    # Axis labels
    out.append(f'<text x="{plx+plw/2}" y="{oy + ph - 8}" text-anchor="middle" font-size="11">{xml_escape(xlabel)}</text>')
    out.append(f'<text x="{ox+16}" y="{ply+plh/2}" text-anchor="middle" font-size="11" transform="rotate(-90,{ox+16},{ply+plh/2})">{xml_escape(ylabel)}</text>')

    # Series
    for i, (label, xs, ys, color, style) in enumerate(series):
        xs = np.asarray(xs); ys = np.asarray(ys)
        mask = (xs >= xmin) & (xs <= xmax) & (ys >= ymin) & (ys <= ymax)
        xs_c, ys_c = xs[mask], ys[mask]
        if style == "line":
            pts = " ".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in zip(xs_c, ys_c))
            out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
        else:
            for x, y in zip(xs_c, ys_c):
                out.append(f'<circle cx="{X(x):.2f}" cy="{Y(y):.2f}" r="4" fill="{color}" stroke="white" stroke-width="0.8"/>')
        # Legend
        ly_legend = ply + 14 + i*16
        out.append(f'<rect x="{plx+12}" y="{ly_legend-8}" width="16" height="3" fill="{color}"/>')
        out.append(f'<text x="{plx+34}" y="{ly_legend-3}" font-size="10">{xml_escape(label)}</text>')
    out.append('</g>')
    return "\n".join(out)


def render_svg(panels, width=1100, height=700):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" font-size="12">',
             f'<rect width="{width}" height="{height}" fill="white"/>',
             f'<text x="{width//2}" y="22" text-anchor="middle" font-size="14" font-weight="bold">Figure 1 equivalent: H11F1 model R(I_F) vs digitised user data</text>',
             f'<text x="{width//2}" y="40" text-anchor="middle" font-size="11" fill="#555">Solid line = simulation; markers = user-digitised 21 points</text>']
    parts += panels
    parts.append('</svg>')
    return "\n".join(parts)


def main():
    user_fig1 = parse_fig1()
    print(f"Parsed Fig 1: {len(user_fig1)} points")
    # Sweep I_F log-spaced from 1 to 60 mA
    IF_sweep = np.logspace(0, np.log10(60), 60)  # mA
    print(f"Sweeping {len(IF_sweep)} model points 1-60 mA ...")
    R_model = []
    for IF_mA in IF_sweep:
        R, err = sim_R_at_IF(IF_mA)
        if R is None:
            print(f"  I_F={IF_mA:.2f}mA FAIL: {err[:200]}"); continue
        R_model.append((IF_mA, R / R_TYP))

    IF_model = np.array([p[0] for p in R_model])
    R_model_arr = np.array([p[1] for p in R_model])
    IF_user = np.array([p[0] for p in user_fig1])
    R_user = np.array([p[1] for p in user_fig1])

    # Interpolate model at user's I_F for error stats (log-log interp)
    log_IF_model = np.log10(IF_model); log_R_model = np.log10(R_model_arr)
    log_R_model_at_user = np.interp(np.log10(IF_user), log_IF_model, log_R_model)
    R_model_at_user = 10**log_R_model_at_user
    ratio = R_user / R_model_at_user

    print(f"\n{'I_F (mA)':>9s} {'R/R_typ user':>13s} {'R/R_typ model':>14s} {'ratio U/M':>10s}")
    for (IF, R_u), R_m, r in zip(user_fig1, R_model_at_user, ratio):
        print(f"{IF:9.3f} {R_u:13.3f} {R_m:14.3f} {r:10.2f}")

    panel = panel_xy_log(40, 60, 1020, 620,
                          title="Figure 1: Normalised Resistance vs Input Current",
                          xlabel="I_F, INPUT CURRENT (mA)",
                          ylabel="R / R_typ_16mA",
                          xlim=(0.9, 70), ylim=(0.5, 15),
                          series=[("model (now Fig 2-derived G)", IF_model, R_model_arr, "#06c", "line"),
                                  ("user Fig 1 digitisation", IF_user, R_user, "#d00", "circle")])
    svg = render_svg([panel])
    out_path = HERE / "h11f_fig1_validate.svg"
    out_path.write_text(svg)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
