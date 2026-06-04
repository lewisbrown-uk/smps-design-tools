"""Analyse the high-res H11F digitisation file.

Three jobs:
  1. Fig 1 (R vs I_F): convert raw Y to R/R_typ, list as TABLE points.
  2. Fig 2 (I-V curves at 5 I_F values): fit tanh model to each, extract
     V_CHAR(I_F). Check if V_CHAR is actually constant or varies with I_F.
  3. Fig 3 (LED V_F vs I_F at 25°C): check the current SPICE model's
     (IS=1.65e-16, N=1.5, RS=3.5) predictions against user data.
"""
import sys, types, numpy as np, re
for n in ('matplotlib','matplotlib.pyplot'): sys.modules.setdefault(n, types.ModuleType(n))
sys.modules['matplotlib'].use = lambda *a, **kw: None

from pathlib import Path


def curve_fit(f, x, y, p0, maxiter=200, lr=0.5):
    """Tiny Levenberg-Marquardt-style fitter (gradient descent w/ adaptive step)."""
    p = np.array(p0, dtype=float)
    x = np.asarray(x); y = np.asarray(y)
    eps = 1e-7
    for _ in range(maxiter):
        r = y - f(x, *p)
        # Numerical Jacobian
        J = np.zeros((len(y), len(p)))
        for i in range(len(p)):
            dp = np.zeros_like(p); dp[i] = max(abs(p[i])*eps, 1e-10)
            J[:, i] = (f(x, *(p+dp)) - f(x, *(p-dp))) / (2*dp[i])
        # Gauss-Newton step (with small damping for stability)
        JT = J.T
        try:
            step = np.linalg.solve(JT@J + 1e-9*np.eye(len(p)), JT@r)
        except np.linalg.LinAlgError:
            break
        p_new = p + lr * step
        if np.linalg.norm(step) < 1e-9 * (np.linalg.norm(p) + 1e-9):
            break
        p = p_new
    return p, None

DATA = Path(__file__).resolve().parent / "spice_models/H11F1_digitisation.txt"


def parse():
    text = DATA.read_text()
    sections = {}
    current_section = None
    current_subsection = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Fig "):
            current_section = stripped
            sections[current_section] = {}
            current_subsection = None
        elif stripped == "x, y":
            if current_subsection is None:
                current_subsection = "_all"
                sections[current_section][current_subsection] = []
        elif re.match(r"^[\d.\-]+[, ][\s\d.\-]+$", stripped):
            # data line
            parts = re.split(r"[,\s]+", stripped)
            x, y = float(parts[0]), float(parts[1])
            if current_subsection is None:
                # we're in Fig 2 with no subsection header? shouldn't happen
                current_subsection = "_default"
                sections[current_section][current_subsection] = []
            sections[current_section][current_subsection].append((x, y))
        else:
            # subsection header like "2 mA" or "T_A = 25ºC"
            current_subsection = stripped
            sections[current_section][current_subsection] = []
    return sections


def main():
    sections = parse()
    print(f"Sections found: {list(sections.keys())}")
    for sname, sub in sections.items():
        for sub_name, pts in sub.items():
            print(f"  {sname} / {sub_name}: {len(pts)} points")

    # ============================================================
    # Fig 1: R/R_typ vs I_F
    # ============================================================
    print("\n=== Fig 1: R(I_F) ===")
    fig1 = sections["Fig 1"]["_all"]
    # Y_norm calibrated so Y_at_I_F=16mA → R/R_typ = 1.
    # Interpolate Y at I_F=16mA from neighbouring points (14.66, 17.82).
    pts_sorted = sorted(fig1)
    # Find points bracketing I_F=16 mA
    Y_at_16 = None
    for i in range(len(pts_sorted)-1):
        IF_lo, Y_lo = pts_sorted[i]
        IF_hi, Y_hi = pts_sorted[i+1]
        if IF_lo <= 16.0 <= IF_hi:
            # log-linear interp in I_F
            frac = (np.log10(16.0) - np.log10(IF_lo)) / (np.log10(IF_hi) - np.log10(IF_lo))
            Y_at_16 = Y_lo + frac * (Y_hi - Y_lo)
            break
    print(f"  Y at I_F=16 mA (interpolated): {Y_at_16:.4f}")
    Y_norm = Y_at_16
    print(f"  Using R/R_typ = {Y_norm:.4f} / Y")
    table_pts = [(I_F, Y_norm/Y) for (I_F, Y) in pts_sorted]
    print(f"  {'I_F (mA)':>9s} | {'R/R_typ':>8s}")
    for I_F, R_norm in table_pts:
        print(f"  {I_F:9.3f} | {R_norm:8.4f}")

    # ============================================================
    # Fig 2: tanh fit per I_F to extract V_CHAR
    # ============================================================
    print("\n=== Fig 2: V_CHAR per I_F via tanh fit ===")
    fig2 = sections["Fig 2"]
    # tanh model: I_46 = G·V_CHAR·tanh(V_46/V_CHAR), units I in µA, V in V
    # Convert: G = 1/R, R from Fig 1 at that I_F (use TABLE lookup).
    # Fit V_CHAR with G as free parameter too — actually with both free, we
    # can recover both G and V_CHAR from the data and compare G to Fig 1.

    def tanh_model(V, G_norm_mS, V_char):
        # I in µA, V in V; G_norm_mS is conductance in mS = mA/V
        # I_µA = G_mS · 1000 · V_char · tanh(V / V_char)
        return G_norm_mS * 1000 * V_char * np.tanh(V / V_char)

    fig2_results = []
    for IF_label, pts in sorted(fig2.items(), key=lambda x: float(x[0].split()[0])):
        I_F_mA = float(IF_label.split()[0])
        # pts is list of (V_46, I_46_uA)
        V = np.array([p[0] for p in pts])
        I_uA = np.array([p[1] for p in pts])
        # Initial guess: G from Fig 1, V_char=0.06
        # R/R_typ at this I_F
        R_norm_init = np.interp(I_F_mA, [p[0] for p in table_pts], [p[1] for p in table_pts])
        R_ohm_init = R_norm_init * 100  # R_typ_16mA = 100 Ω
        G_mS_init = 1000.0 / R_ohm_init  # mS
        try:
            popt, pcov = curve_fit(tanh_model, V, I_uA,
                                    p0=[G_mS_init, 0.06])
            G_fit_mS, V_char_fit = popt
            R_fit = 1000.0 / G_fit_mS
            fig2_results.append((I_F_mA, G_fit_mS, V_char_fit, R_fit))
            print(f"  I_F = {I_F_mA:4.1f} mA: G = {G_fit_mS:6.3f} mS  → R = {R_fit:6.1f} Ω,  V_CHAR = {V_char_fit*1000:5.1f} mV")
        except Exception as e:
            print(f"  I_F = {I_F_mA:4.1f} mA: fit FAILED: {e}")

    if fig2_results:
        V_chars = [r[2] for r in fig2_results]
        print(f"  V_CHAR range: {min(V_chars)*1000:.1f} - {max(V_chars)*1000:.1f} mV")
        print(f"  V_CHAR mean ± std: {np.mean(V_chars)*1000:.1f} ± {np.std(V_chars)*1000:.1f} mV")
        if max(V_chars)/min(V_chars) - 1 < 0.10:
            print(f"  → V_CHAR is approximately CONSTANT across I_F.")
        else:
            print(f"  → V_CHAR VARIES with I_F by {(max(V_chars)/min(V_chars)-1)*100:.0f}%.")

    # ============================================================
    # Fig 3: LED V_F vs I_F at 25°C — check current SPICE model
    # ============================================================
    print("\n=== Fig 3: LED V_F(I_F) at 25°C ===")
    fig3_25C = sections["Fig 3"]["T_A = 25ºC"]
    # Current model: D_H11F_LED: IS=1.65e-16, N=1.5, RS=3.5
    # V_F = N·V_T·ln(I_F/IS + 1) + I_F·RS,  V_T = 0.02585 V at 25°C
    V_T = 0.02585
    IS, N, RS = 1.65e-16, 1.5, 3.5
    print(f"  Current model: IS={IS:.2e}, N={N}, RS={RS}")
    print(f"  {'I_F (mA)':>9s} | {'V_F user':>10s} | {'V_F model':>10s} | {'err (mV)':>9s}")
    err_sum = 0; err_count = 0
    for I_F_mA, V_F_user in fig3_25C:
        I_F = I_F_mA * 1e-3
        V_F_model = N * V_T * np.log(I_F / IS + 1) + I_F * RS
        err = (V_F_user - V_F_model) * 1000  # mV
        err_sum += err**2; err_count += 1
        print(f"  {I_F_mA:9.3f} | {V_F_user:9.4f} V | {V_F_model:9.4f} V | {err:+8.1f}")
    rms_err = np.sqrt(err_sum/err_count)
    print(f"  RMS error vs current model: {rms_err:.1f} mV")
    # Grid-search diode fit (more robust than gradient descent for diode params).
    I_arr = np.array([p[0]*1e-3 for p in fig3_25C])
    V_arr = np.array([p[1] for p in fig3_25C])
    def diode(I, IS_f, N_f, RS_f):
        return N_f * V_T * np.log(I / IS_f + 1) + I * RS_f
    def rms_error(IS_f, N_f, RS_f):
        V_pred = diode(I_arr, IS_f, N_f, RS_f)
        return float(np.sqrt(np.mean((V_arr - V_pred)**2)))
    best = (1e9, None)
    # Coarse grid
    for IS_log in np.linspace(-17, -14, 31):
        for N_f in np.linspace(1.2, 2.0, 17):
            for RS_f in np.linspace(2.0, 5.0, 13):
                e = rms_error(10**IS_log, N_f, RS_f)
                if e < best[0]:
                    best = (e, (10**IS_log, N_f, RS_f))
    # Refine
    IS_c, N_c, RS_c = best[1]
    for IS_log in np.linspace(np.log10(IS_c)-0.5, np.log10(IS_c)+0.5, 41):
        for N_f in np.linspace(N_c-0.1, N_c+0.1, 21):
            for RS_f in np.linspace(RS_c-0.3, RS_c+0.3, 21):
                e = rms_error(10**IS_log, N_f, RS_f)
                if e < best[0]:
                    best = (e, (10**IS_log, N_f, RS_f))
    IS_fit, N_fit, RS_fit = best[1]
    print(f"  Re-fit (grid search):")
    print(f"    IS={IS_fit:.3e}, N={N_fit:.3f}, RS={RS_fit:.3f}")
    print(f"    RMS error: {best[0]*1000:.1f} mV")


if __name__ == "__main__":
    main()
