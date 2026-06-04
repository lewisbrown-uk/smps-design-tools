"""Simulate H11F I-V curves at I_F = 2, 6, 10, 14, 18 mA (matching Fig 2)
and overlay the digitised user data points.  Hand-rolled SVG output."""
import subprocess, numpy as np, sys, re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

HERE = Path(__file__).resolve().parent
WORK = HERE / "_h11f_fig2_validate"; WORK.mkdir(exist_ok=True)
MODEL = HERE / "spice_models" / "H11F1.spice.txt"
DATA = HERE / "spice_models" / "H11F1_digitisation.txt"


def parse_digitisation():
    text = DATA.read_text()
    out = {"Fig 2": {}}
    section = None; subsection = None
    for line in text.splitlines():
        s = line.strip()
        if not s: continue
        if s.startswith("Fig "):
            section = s; subsection = None; continue
        if section != "Fig 2": continue
        if re.match(r"^-?\d+(?:\.\d+)?(?:e-?\d+)?\s*[, ]\s*-?\d+(?:\.\d+)?(?:e-?\d+)?$", s):
            parts = re.split(r"[,\s]+", s)
            if subsection is None: continue
            out[section][subsection].append((float(parts[0]), float(parts[1])))
        elif re.match(r"^\d+\s*mA$", s):
            subsection = s; out[section][subsection] = []
    return out["Fig 2"]


def sim_iv_curve(I_F_mA, V_start=-0.25, V_end=0.25, V_step=0.005):
    label = f"iv_{I_F_mA}mA"
    cir = WORK / f"{label}.cir"
    dat = WORK / f"{label}.data"
    deck = f"""* H11F I-V curve at I_F = {I_F_mA} mA
.include {MODEL}
I_LED 0 led_a DC {I_F_mA*1e-3}
X_H11F led_a 0 4 0 H11F1
V_test 4 0 DC 0
.dc V_test {V_start} {V_end} {V_step}
.control
run
wrdata {dat.as_posix()} v(4) i(V_test)
.endc
.end
"""
    cir.write_text(deck)
    res = subprocess.run(["ngspice", "-b", cir.name], cwd=WORK,
                         capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        return None, None, res.stderr[-400:]
    d = np.loadtxt(dat)
    V = d[:, 1]
    I = d[:, 3]
    # I(V_test) reports current FROM + to - through V_test.
    # V_test has + at node 4 and - at ground.  Current "through V_test from + to -"
    # = current INTO node 4 from outside = -current INTO node 4 from H11F
    # = -current FROM H11F INTO node 4.  So I_chan (out of H11F into node 4) = -I(V_test).
    I = -I
    return V, I, None


def render_svg(panels, width=1200, height=850):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" font-size="12">',
             f'<rect width="{width}" height="{height}" fill="white"/>',
             f'<text x="{width//2}" y="24" text-anchor="middle" font-size="14" font-weight="bold">H11F1 model vs digitised Fig 2 (after 2026-05-23 update)</text>',
             f'<text x="{width//2}" y="42" text-anchor="middle" font-size="11" fill="#555">Solid lines = simulation; circles = user digitised data points</text>']
    parts += panels
    parts.append('</svg>')
    return "\n".join(parts)


def panel_xy(ox, oy, pw, ph, *, title, xlabel, ylabel, xlim, ylim, series,
              legend_loc="upper-left"):
    """Render a single XY chart panel."""
    pad_left, pad_right, pad_top, pad_bot = 60, 20, 30, 35
    plx = ox + pad_left
    ply = oy + pad_top
    plw = pw - pad_left - pad_right
    plh = ph - pad_top - pad_bot
    xmin, xmax = xlim
    ymin, ymax = ylim

    def X(x): return plx + (x - xmin) / (xmax - xmin) * plw
    def Y(y): return ply + (1 - (y - ymin) / (ymax - ymin)) * plh

    out = [f'<g>',
           f'<text x="{plx + plw/2}" y="{oy + pad_top - 6}" text-anchor="middle" '
           f'font-size="11" font-weight="bold">{xml_escape(title)}</text>',
           f'<rect x="{plx}" y="{ply}" width="{plw}" height="{plh}" fill="none" stroke="#666"/>']
    # X ticks
    for i in range(7):
        xv = xmin + i*(xmax - xmin)/6
        xpx = X(xv)
        out.append(f'<line x1="{xpx}" y1="{ply}" x2="{xpx}" y2="{ply+plh}" stroke="#eee"/>')
        out.append(f'<text x="{xpx}" y="{ply+plh+12}" text-anchor="middle" font-size="9" fill="#555">{xv:.2f}</text>')
    # Y ticks
    for i in range(7):
        yv = ymin + i*(ymax - ymin)/6
        ypx = Y(yv)
        out.append(f'<line x1="{plx}" y1="{ypx}" x2="{plx+plw}" y2="{ypx}" stroke="#eee"/>')
        out.append(f'<text x="{plx-5}" y="{ypx+3}" text-anchor="end" font-size="9" fill="#555">{yv:.0f}</text>')
    # Axis labels
    out.append(f'<text x="{plx+plw/2}" y="{oy + ph - 5}" text-anchor="middle" font-size="10">{xml_escape(xlabel)}</text>')
    out.append(f'<text x="{ox+14}" y="{ply+plh/2}" text-anchor="middle" font-size="10" transform="rotate(-90,{ox+14},{ply+plh/2})">{xml_escape(ylabel)}</text>')
    # Zero lines
    if ymin < 0 < ymax: out.append(f'<line x1="{plx}" y1="{Y(0)}" x2="{plx+plw}" y2="{Y(0)}" stroke="#aaa" stroke-dasharray="3,2"/>')
    if xmin < 0 < xmax: out.append(f'<line x1="{X(0)}" y1="{ply}" x2="{X(0)}" y2="{ply+plh}" stroke="#aaa" stroke-dasharray="3,2"/>')

    # Series + legend
    ly_base = ply + 14
    for i, (label, xs, ys, color, style) in enumerate(series):
        xs = np.asarray(xs); ys = np.asarray(ys)
        # Clip to plot area to avoid SVG drawing way outside
        mask = (xs >= xmin) & (xs <= xmax) & (ys >= ymin) & (ys <= ymax)
        xs_c, ys_c = xs[mask], ys[mask]
        if style == "line":
            pts = " ".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in zip(xs_c, ys_c))
            out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"/>')
        else:
            for x, y in zip(xs_c, ys_c):
                out.append(f'<circle cx="{X(x):.2f}" cy="{Y(y):.2f}" r="3" fill="{color}" stroke="white" stroke-width="0.5"/>')
        ly = ly_base + i*14
        out.append(f'<rect x="{plx+10}" y="{ly-7}" width="14" height="3" fill="{color}"/>')
        out.append(f'<text x="{plx+28}" y="{ly-3}" font-size="9">{xml_escape(label)}</text>')
    out.append('</g>')
    return "\n".join(out)


def main():
    digitised = parse_digitisation()
    print(f"Parsed Fig 2 subsections: {list(digitised.keys())}")

    # Color scheme matching the user's digitisation file series ordering
    colors = {2: "#d00", 6: "#f80", 10: "#0a0", 14: "#06c", 18: "#80c"}

    series = []
    error_summary = []
    for I_F_mA in [2, 6, 10, 14, 18]:
        V_sim, I_sim, err = sim_iv_curve(I_F_mA)
        if V_sim is None:
            print(f"  I_F={I_F_mA}mA: FAIL  {err[:200]}"); continue
        # Sign convention check at V=0.1
        idx = int(np.argmin(np.abs(V_sim - 0.1)))
        if I_sim[idx] < 0:
            I_sim = -I_sim
        # Add model curve
        series.append((f"{I_F_mA} mA (model)", V_sim, I_sim * 1e6, colors[I_F_mA], "line"))
        # Add data points
        sub = f"{I_F_mA} mA"
        if sub in digitised:
            pts = np.array(digitised[sub])
            series.append((f"{I_F_mA} mA (data)", pts[:, 0], pts[:, 1], colors[I_F_mA], "circle"))
            # Compute error
            I_model_at_V = np.interp(pts[:, 0], V_sim, I_sim * 1e6)
            residuals = pts[:, 1] - I_model_at_V
            rms_uA = float(np.sqrt(np.mean(residuals ** 2)))
            max_uA = float(np.max(np.abs(residuals)))
            I_sat = float(np.max(np.abs(pts[:, 1])))
            error_summary.append((I_F_mA, len(pts), rms_uA, max_uA, I_sat))
            print(f"  I_F={I_F_mA}mA: RMS={rms_uA:5.1f} µA  max={max_uA:5.1f} µA  "
                  f"({rms_uA/I_sat*100:5.1f}% rel to I_sat={I_sat:.0f})")

    # Render
    panel = panel_xy(40, 60, 1120, 720,
                      title="H11F I-V at five I_F values — model curves with overlaid digitised data",
                      xlabel="V_46 (V)", ylabel="I_46 (µA)",
                      xlim=(-0.25, 0.25), ylim=(-900, 900),
                      series=series)
    svg = render_svg([panel])
    out_path = HERE / "h11f_fig2_validate.svg"
    out_path.write_text(svg)
    print(f"\nSaved: {out_path}")
    # Summary
    print(f"\n{'I_F':>4s} {'pts':>4s} {'RMS µA':>7s} {'max µA':>7s} {'%I_sat':>7s}")
    for I_F_mA, n, rms, mx, isat in error_summary:
        print(f"{I_F_mA:4d} {n:4d} {rms:7.2f} {mx:7.2f} {rms/isat*100:6.2f}%")


if __name__ == "__main__":
    main()
