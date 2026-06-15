"""Dependency-free SVG charts for the slew-rate tests (SLEW_ANALYSIS.md data).
No matplotlib. Writes slew_chart_*.svg to the OCIS project folder by default."""
import os, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/ocis-workdir/claude-code/vfd-filament-regulator/charts")
os.makedirs(OUT, exist_ok=True)

# ---------- minimal SVG (same style as make_charts.py) ----------
class SVG:
    def __init__(s, w, h): s.w, s.h, s.e = w, h, []
    def rect(s, x, y, w, h, fill, stroke="none", sw=1, op=1, dash=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        s.e.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{op}"{d}/>')
    def line(s, x1, y1, x2, y2, stroke, sw=1, dash=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        s.e.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw}"{d}/>')
    def poly(s, pts, stroke, sw=2, dash=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        s.e.append(f'<polyline points="{p}" fill="none" stroke="{stroke}" stroke-width="{sw}"{d}/>')
    def circ(s, x, y, r, fill, stroke="white", sw=1):
        s.e.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    def txt(s, x, y, t, size=13, anc="start", fill="#222", w="normal", rot=None):
        tr = f' transform="rotate({rot} {x:.1f} {y:.1f})"' if rot is not None else ""
        s.e.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="sans-serif" font-size="{size}" text-anchor="{anc}" fill="{fill}" font-weight="{w}"{tr}>{t}</text>')
    def save(s, path):
        open(path, "w").write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{s.w}" height="{s.h}" '
                              f'viewBox="0 0 {s.w} {s.h}"><rect width="{s.w}" height="{s.h}" fill="white"/>\n'
                              + "\n".join(s.e) + "\n</svg>")
        print("wrote", path)

def axes(g, x0, y0, pw, ph, xlim, ylim, title, xlabel, ylabel, xticks, yticks, yfmt="{:.0f}", xfmt=str):
    g.rect(x0, y0, pw, ph, "#fafafa", "#bbb", 1)
    mx = lambda v: x0 + (v-xlim[0])/(xlim[1]-xlim[0])*pw
    my = lambda v: y0+ph - (v-ylim[0])/(ylim[1]-ylim[0])*ph
    for yt in yticks:
        Y = my(yt); g.line(x0, Y, x0+pw, Y, "#e8e8e8", 1); g.txt(x0-8, Y+4, yfmt.format(yt), 11, "end", "#666")
    for xt in xticks:
        X = mx(xt); g.line(X, y0, X, y0+ph, "#f0f0f0", 1); g.txt(X, y0+ph+16, xfmt(xt), 11, "middle", "#666")
    g.txt(x0+pw/2, y0-14, title, 15, "middle", "#111", "bold")
    g.txt(x0+pw/2, y0+ph+34, xlabel, 12, "middle", "#444")
    g.txt(x0-46, y0+ph/2, ylabel, 12, "middle", "#444", rot=-90)
    return mx, my

def legend(g, x, y, items):  # items: [(label,color,dash)]
    for i, it in enumerate(items):
        lab, c = it[0], it[1]; dash = it[2] if len(it) > 2 else ""
        yy = y + i*19
        g.line(x, yy-4, x+26, yy-4, c, 3, dash); g.txt(x+32, yy, lab, 12, "start", "#333")

RED, GREEN, GREY = "#d62728", "#2ca02c", "#888"

# ============ Chart 1: slew calibration ============
def chart_calibration():
    pts = [(60, 0.377), (90, 0.565), (120, 0.754), (150, 0.942), (200, 1.257), (300, 1.885)]
    g = SVG(680, 460)
    x0, y0, pw, ph = 80, 50, 540, 340
    mx, my = axes(g, x0, y0, pw, ph, (0, 320), (0, 2.0),
                  "Slew-model calibration — Islew vs output slew rate (GBW 1 MHz)",
                  "Islew  (nA)", "output slew rate  (V/µs)",
                  [0, 60, 120, 180, 240, 300], [0, 0.4, 0.8, 1.2, 1.6, 2.0], yfmt="{:.1f}")
    # target SR = 0.8 V/us  +  calibrated Islew = 127.3 nA
    g.line(x0, my(0.8), x0+pw, my(0.8), "#bbb", 1.5, "5 4")
    g.txt(x0+pw-4, my(0.8)-6, "OPA4277 target 0.8 V/µs", 11, "end", "#777")
    g.line(mx(127.3), y0, mx(127.3), y0+ph, "#bbb", 1.5, "5 4")
    g.poly([(mx(i), my(s)) for i, s in pts], RED, 2.5)
    for i, s in pts:
        g.circ(mx(i), my(s), 4, RED)
    g.circ(mx(127.3), my(0.8), 6, "#111", "white", 1.5)
    g.txt(mx(127.3)+10, my(0.8)+20, "calibrated:  127.3 nA → 0.800 V/µs", 12, "start", "#111", "bold")
    g.txt(x0+pw/2, y0+ph+52, "SR linear in Islew (constant-slew model); 127.3 nA matches the analytic 2·Islew/C_dom.",
          11, "middle", "#888")
    g.save(os.path.join(OUT, "slew_chart1_calibration.svg"))

# ============ Chart 2: THD vs carrier ============
def chart_thd():
    # (carrier kHz, THD dB) -- None where the sim did not converge
    i7_nom = [(1, -34.7), (2, -34.8), (3, -35.0), (5, -35.4), (8, -36.0), (10, -36.3), (12, -36.7)]
    i7_slew = [(1, -34.7), (2, -34.8), (3, -35.0), (5, -35.2), (8, -34.7)]
    v18_nom = [(1, -52.8), (2, -43.1), (5, -38.6), (10, -36.8), (15, -35.3), (20, -35.2)]
    v18_slew = [(1, -52.8), (2, -43.1), (5, -38.6), (10, -36.8), (15, -35.0), (20, -34.6)]
    g = SVG(760, 500)
    x0, y0, pw, ph = 80, 56, 600, 360
    # Y inverted sense: more-negative dB (lower THD = better) at BOTTOM, worse at TOP
    xlim, ylim = (0, 21), (-54, -33)
    mx, my = axes(g, x0, y0, pw, ph,
                  xlim, ylim,
                  "Filament-drive THD vs carrier frequency  —  slew-limited (0.8 V/µs) vs no-slew model",
                  "carrier frequency  (kHz)", "THD  (dB)   ↑ worse",
                  [1, 2, 5, 8, 10, 12, 15, 20], [-54, -50, -46, -42, -38, -34], yfmt="{:.0f}")
    # wall region (sim non-convergence, >=10 kHz for the slew ILC1-1/7)
    g.rect(mx(9), y0, mx(21)-mx(9), ph, "#cc3333", op=0.07)
    g.line(mx(9), y0, mx(9), y0+ph, "#cc3333", 1.2, "4 3")
    g.txt(mx(9)+8, y0+ph-90, "slew wall:", 12, "start", "#a33", "bold")
    g.txt(mx(9)+8, y0+ph-74, "slew-limited sim", 11, "start", "#a33")
    g.txt(mx(9)+8, y0+ph-60, "no longer converges", 11, "start", "#a33")
    g.txt(mx(9)+8, y0+ph-46, "(op-amp grossly slewing)", 11, "start", "#a33")
    # lines
    g.poly([(mx(f), my(t)) for f, t in i7_nom], RED, 2.5)
    g.poly([(mx(f), my(t)) for f, t in i7_slew], RED, 2.5, "6 4")
    g.poly([(mx(f), my(t)) for f, t in v18_nom], GREEN, 2.5)
    g.poly([(mx(f), my(t)) for f, t in v18_slew], GREEN, 2.5, "6 4")
    for f, t in i7_nom + v18_nom:
        g.circ(mx(f), my(t), 3.2, RED if (f, t) in i7_nom else GREEN)
    for f, t in i7_slew:
        g.circ(mx(f), my(t), 3.2, RED)
    for f, t in v18_slew:
        g.circ(mx(f), my(t), 3.2, GREEN)
    # onset marker at 8 kHz (ILC1-1/7 slew peels +1.3 dB above nominal)
    g.line(mx(8), my(-34.7), mx(8), my(-36.0), "#a33", 1)
    g.txt(mx(8), my(-34.7)-8, "onset ≈ 8 kHz", 11, "middle", "#a33", "bold")
    # 1 kHz belt-and-suspenders callout
    g.txt(mx(1)+6, my(-34.7)-10, "1 kHz: slew = no-slew", 11, "start", "#555")
    legend(g, x0+pw-210, y0+24, [
        ("ILC1-1/7 (8.5 V) — no-slew", RED),
        ("ILC1-1/7 — slew 0.8 V/µs", RED, "6 4"),
        ("IV-18 (~1 V) — no-slew", GREEN),
        ("IV-18 — slew 0.8 V/µs", GREEN, "6 4"),
    ])
    g.txt(x0+pw/2, y0+ph+52,
          "At 1 kHz slew is immaterial (validated battery is correct). ILC1-1/7's 8.5 V swing peels off ~8 kHz; IV-18 (low swing) is slew-immune.",
          11, "middle", "#888")
    g.save(os.path.join(OUT, "slew_chart2_thd_vs_carrier.svg"))

if __name__ == "__main__":
    chart_calibration()
    chart_thd()
