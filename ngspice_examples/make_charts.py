"""Dependency-free SVG charts for the full test-battery results (realistic per-tube tau).
No matplotlib needed.  Writes chart_*.svg (open in any browser)."""
import csv, os

HERE = os.path.dirname(os.path.abspath(__file__))
TUBES = ["ilc11_7", "iv6", "iv18", "ilc11_8"]
NAME = {"ilc11_7": "ILC1-1/7", "iv6": "IV-6", "iv18": "IV-18", "ilc11_8": "ILC1-1/8"}
COL = {"ilc11_7": "#d62728", "iv6": "#1f77b4", "iv18": "#2ca02c", "ilc11_8": "#9467bd"}

# ---------- battery data (realistic per-tube tau) ----------
TAU = {"ilc11_7": 0.42, "iv6": 0.20, "iv18": 0.19, "ilc11_8": 0.62}
OS01 = {"ilc11_7": 3.6, "iv6": 0.2, "iv18": 0.1, "ilc11_8": 0.2}   # overshoot @0.1s
OSR = {"ilc11_7": 3.7, "iv6": 0.1, "iv18": 0.1, "ilc11_8": 7.4}    # overshoot @real tau
MC = {"ilc11_7": (783, 810), "iv6": (782, 809), "iv18": (781, 808), "ilc11_8": (782, 809)}
PEAKS = {
    "xubuf_hi":        {"ilc11_7": 814, "iv6": 871, "iv18": 899, "ilc11_8": 834},
    "botref_short":    {"ilc11_7": 867, "iv6": 922, "iv18": 909, "ilc11_8": 913},
    "atten_top_short": {"ilc11_7": 812, "iv6": 842, "iv18": 847, "ilc11_8": 823},
    "topref_open":     {"ilc11_7": 867, "iv6": 922, "iv18": 909, "ilc11_8": 913},
}
UNPROT = {"ilc11_7": 922, "iv6": 1755, "iv18": 1802, "ilc11_8": 1619}
DWELL = {"ilc11_7": (57, 0, 0), "iv6": (80, 22, 0), "iv18": (100, 46, 0), "ilc11_8": (127, 0, 0)}
GBW = [0.5, 1, 3, 10]
GBW_THD = {"ilc11_7": [-34.8, -34.7, -34.7, -34.7], "iv6": [-43.3, -46.0, -48.6, -50.9],
           "iv18": [-49.8, -53.7, -57.8, -58.8], "ilc11_8": [-41.5, -44.3, -48.6, -51.3]}


# ---------- minimal SVG ----------
class SVG:
    def __init__(s, w, h): s.w, s.h, s.e = w, h, []
    def rect(s, x, y, w, h, fill, stroke="none", sw=1, op=1, dash=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        s.e.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{op}"{d}/>')
    def line(s, x1, y1, x2, y2, stroke, sw=1, dash=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        s.e.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw}"{d}/>')
    def poly(s, pts, stroke, sw=2):
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        s.e.append(f'<polyline points="{p}" fill="none" stroke="{stroke}" stroke-width="{sw}"/>')
    def txt(s, x, y, t, size=13, anc="start", fill="#222", w="normal", rot=None):
        tr = f' transform="rotate({rot} {x:.1f} {y:.1f})"' if rot is not None else ""
        s.e.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="sans-serif" font-size="{size}" text-anchor="{anc}" fill="{fill}" font-weight="{w}"{tr}>{t}</text>')
    def save(s, path):
        open(path, "w").write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{s.w}" height="{s.h}" '
                              f'viewBox="0 0 {s.w} {s.h}"><rect width="{s.w}" height="{s.h}" fill="white"/>\n'
                              + "\n".join(s.e) + "\n</svg>")
        print("wrote", os.path.basename(path))


def axes(g, x0, y0, pw, ph, xlim, ylim, title, xlabel, ylabel, xticks, yticks, yfmt="{:.0f}", xfmt=str):
    g.rect(x0, y0, pw, ph, "#fafafa", "#bbb", 1)
    mx = lambda v: x0 + (v-xlim[0])/(xlim[1]-xlim[0])*pw
    my = lambda v: y0+ph - (v-ylim[0])/(ylim[1]-ylim[0])*ph
    for yt in yticks:
        Y = my(yt); g.line(x0, Y, x0+pw, Y, "#e8e8e8", 1); g.txt(x0-7, Y+4, yfmt.format(yt), 11, "end", "#666")
    for xt in xticks:
        X = mx(xt); g.txt(X, y0+ph+16, xfmt(xt), 11, "middle", "#666")
    g.txt(x0+pw/2, y0-12, title, 16, "middle", "#111", "bold")
    g.txt(x0+pw/2, y0+ph+34, xlabel, 12, "middle", "#444")
    g.txt(x0-44, y0+ph/2, ylabel, 12, "middle", "#444", rot=-90)
    return mx, my


def legend(g, x, y, items):  # items: [(label,color)]
    for i, (lab, c) in enumerate(items):
        yy = y + i*18
        g.rect(x, yy-9, 14, 11, c); g.txt(x+20, yy, lab, 12, "start", "#333")


# ===== Chart 1: fault temperature trajectories =====
def chart_trajectories():
    g = SVG(820, 520); x0, y0, pw, ph = 70, 50, 690, 400
    mx, my = axes(g, x0, y0, pw, ph, (-20, 600), (300, 950),
                  "Fault temperature excursion (XU_buf stuck, realistic τ, protection ON)",
                  "time after fault (ms)", "filament T (K)",
                  [0, 100, 200, 300, 400, 500, 600], [300, 400, 500, 600, 700, 800, 850, 900, 950])
    for thr, lab in [(800, "operating 800 K"), (850, "850 K"), (900, "900 K")]:
        Y = my(thr); g.line(x0, Y, x0+pw, Y, "#999", 1, "5,4")
    g.txt(x0+pw-4, my(900)-4, "none reach 900 K", 11, "end", "#c00")
    PKTIME = {"ilc11_7": 30, "iv6": 19, "iv18": 25, "ilc11_8": 29}  # ms, from tau-study dwell
    have = []
    for tb in TUBES:
        p = os.path.join(HERE, f"traj_{tb}.csv")
        if os.path.exists(p):
            rows = [ln.split() for ln in open(p).read().splitlines()[1:] if ln.strip()]
            pts = [(mx(max(-20, min(600, float(r[0])))), my(max(300, min(950, float(r[1])))))
                   for r in rows if len(r) >= 2 and -20 <= float(r[0]) <= 600]
            if pts: g.poly(pts, COL[tb], 2.2); have.append(tb)
    for tb in TUBES:  # peak markers (esp. for tubes without a full curve)
        X, Y = mx(PKTIME[tb]), my(PEAKS['xubuf_hi'][tb])
        g.e.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="4" fill="{COL[tb]}" stroke="white" stroke-width="1"/>')
        if tb not in have:
            g.txt(X+7, Y+4, f"{NAME[tb]} peak {PEAKS['xubuf_hi'][tb]} K", 11, "start", COL[tb])
    legend(g, x0+20, y0+24, [(f"{NAME[tb]} (τ={TAU[tb]}s, peak {PEAKS['xubuf_hi'][tb]} K)"
           + ("" if tb in have else "  ●peak only"), COL[tb]) for tb in TUBES])
    g.txt(x0+pw/2, y0+ph+58, "Worst peak 899 K (IV-18); above 800 K for ≤127 ms, above 850 K for ≤46 ms, then cold-safe.",
          12, "middle", "#555")
    g.save(os.path.join(HERE, "chart1_fault_trajectories.svg"))


# ===== Chart 2: fault peaks bounded vs unprotected =====
def chart_peaks():
    g = SVG(820, 520); x0, y0, pw, ph = 70, 50, 690, 400
    faults = list(PEAKS); nf = len(faults)
    mx, my = axes(g, x0, y0, pw, ph, (0, 4), (300, 1900),
                  "Fault peak temperature: protected (bars) vs unprotected (●)",
                  "", "peak T (K)", [], [300, 600, 800, 900, 1200, 1500, 1800])
    for thr, c in [(800, "#888"), (900, "#c00")]:
        Y = my(thr); g.line(x0, Y, x0+pw, Y, c, 1, "5,4")
    g.txt(x0+4, my(900)-4, "900 K", 11, "start", "#c00")
    g.txt(x0+4, my(800)-4, "operating 800 K", 11, "start", "#888")
    gw = pw/len(TUBES); bw = gw*0.8/nf
    fcol = ["#3b6", "#fa3", "#39c", "#c69"]
    for i, tb in enumerate(TUBES):
        gx = x0 + i*gw + gw*0.1
        for j, fl in enumerate(faults):
            v = PEAKS[fl][tb]; bx = gx + j*bw
            g.rect(bx, my(v), bw*0.92, y0+ph-my(v), fcol[j])
        # unprotected marker
        uy = my(UNPROT[tb]); cx = x0 + i*gw + gw/2
        g.e.append(f'<circle cx="{cx:.1f}" cy="{uy:.1f}" r="5" fill="#222"/>')
        g.txt(cx, uy-9, f"{UNPROT[tb]}K", 10, "middle", "#222")
        g.txt(cx, y0+ph+16, NAME[tb], 12, "middle", "#333")
    legend(g, x0+16, y0+20, [(f, fcol[k]) for k, f in enumerate(faults)] + [("unprotected (sustained)", "#222")])
    g.txt(x0+pw/2, y0+ph+44, "Every overheat fault caught + bounded ≤922 K, then disconnected; unprotected it sits at 1600–1800 K forever.",
          12, "middle", "#555")
    g.save(os.path.join(HERE, "chart2_fault_peaks.svg"))


# ===== Chart 3: cold-start overshoot 0.1s vs realistic tau =====
def chart_overshoot():
    g = SVG(720, 480); x0, y0, pw, ph = 70, 50, 600, 360
    mx, my = axes(g, x0, y0, pw, ph, (0, 4), (0, 9),
                  "Cold-start temperature overshoot: 0.1 s placeholder vs realistic τ",
                  "", "overshoot (K)", [], [0, 2, 4, 6, 8])
    gw = pw/len(TUBES); bw = gw*0.32
    for i, tb in enumerate(TUBES):
        gx = x0 + i*gw + gw*0.5
        g.rect(gx-bw-2, my(OS01[tb]), bw, y0+ph-my(OS01[tb]), "#bbb")
        g.rect(gx+2, my(OSR[tb]), bw, y0+ph-my(OSR[tb]), COL[tb])
        g.txt(gx-bw/2-2, my(OS01[tb])-4, f"{OS01[tb]:.1f}", 10, "middle", "#777")
        g.txt(gx+bw/2+2, my(OSR[tb])-4, f"{OSR[tb]:.1f}", 10, "middle", COL[tb], "bold")
        g.txt(x0+i*gw+gw/2, y0+ph+16, NAME[tb], 12, "middle", "#333")
        g.txt(x0+i*gw+gw/2, y0+ph+30, f"τ={TAU[tb]}s", 10, "middle", "#888")
    legend(g, x0+16, y0+20, [("τ=0.1 s (placeholder)", "#bbb"), ("realistic τ (per tube)", "#555")])
    g.txt(x0+pw/2, y0+ph+50, "Only the slowest-τ tube (ILC1-1/8) moves: +0.2 K → +7.4 K. The placeholder hid it.",
          12, "middle", "#555")
    g.save(os.path.join(HERE, "chart3_coldstart_overshoot.svg"))


# ===== Chart 4: Monte Carlo T_ss ranges =====
def chart_mc():
    g = SVG(720, 480); x0, y0, pw, ph = 70, 50, 600, 360
    mx, my = axes(g, x0, y0, pw, ph, (0, 4), (770, 820),
                  "Monte Carlo regulated T_ss (50 draws/tube: R±1%, C±10%, Vos±50µV)",
                  "", "settled T (K)", [], [770, 780, 790, 800, 810, 820])
    Y = my(800); g.line(x0, Y, x0+pw, Y, "#888", 1, "5,4"); g.txt(x0+4, Y-4, "target 800 K", 11, "start", "#888")
    gw = pw/len(TUBES)
    for i, tb in enumerate(TUBES):
        lo, hi = MC[tb]; cx = x0+i*gw+gw/2
        g.rect(cx-22, my(hi), 44, my(lo)-my(hi), COL[tb], op=0.45)
        g.line(cx-30, my(lo), cx+30, my(lo), COL[tb], 2); g.line(cx-30, my(hi), cx+30, my(hi), COL[tb], 2)
        g.txt(cx, my(hi)-6, f"{lo}–{hi}K", 10, "middle", "#333")
        g.txt(cx, y0+ph+16, NAME[tb], 12, "middle", "#333")
        g.txt(cx, y0+ph+30, "0 hunts", 10, "middle", "#2a2")
    g.txt(x0+pw/2, y0+ph+50, "200 draws total: 0 failures, 0 hunts. Spread is the ±1% bridge resistors, not instability.",
          12, "middle", "#555")
    g.save(os.path.join(HERE, "chart4_montecarlo.svg"))


# ===== Chart 5: GBW THD sweep =====
def chart_gbw():
    g = SVG(720, 480); x0, y0, pw, ph = 70, 50, 600, 360
    import math
    xs = [math.log10(v) for v in GBW]
    mx, my = axes(g, x0, y0, pw, ph, (min(xs)-0.1, max(xs)+0.1), (-62, -30),
                  "Op-amp GBW sweep — V_fil THD (no hunting 0.5–10 MHz)",
                  "GBW (MHz, log)", "THD (dB)", xs, [-60, -50, -40, -30],
                  yfmt="{:.0f}", xfmt=lambda v: f"{10**v:g}")
    for tb in TUBES:
        pts = [(mx(math.log10(GBW[k])), my(GBW_THD[tb][k])) for k in range(len(GBW))]
        g.poly(pts, COL[tb], 2.2)
        for (X, Y) in pts: g.e.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="3.2" fill="{COL[tb]}"/>')
    legend(g, x0+pw-150, y0+ph-86, [(NAME[tb], COL[tb]) for tb in TUBES])
    g.txt(x0+pw/2, y0+ph+50, "THD improves with GBW, no oscillation — the old ‘≥3 MHz hunts’ does not occur on this design.",
          12, "middle", "#555")
    g.save(os.path.join(HERE, "chart5_gbw_thd.svg"))


if __name__ == "__main__":
    chart_trajectories(); chart_peaks(); chart_overshoot(); chart_mc(); chart_gbw()
    print("done")
