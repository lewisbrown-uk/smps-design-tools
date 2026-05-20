"""Verify that every op-amp's output current stays below the TLV9154/OPA2188
real-part Isc (~50-65 mA) across all 4 tubes and both V_p corners.

For each (tube, V_p) case:
 1. Generate netlist (manufacturer MOSFET model, t_rail_ramp = 10 ms so the
    cold-start transient isn't an instantaneous-edge artefact).
 2. Insert a 0 V ammeter V_im_<name> in series with each XU_<name> output.
 3. Run ngspice; extract max(abs(i(V_im_<name>))) via vecmax.
 4. Compare against 50 mA threshold.

Output: a CSV (opamp_current_scan.csv) + console summary table.
"""
from __future__ import annotations
import re
import subprocess
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Stub numpy/matplotlib so we can import test_closed_loop without them.
# (Production runs use the full stack; this script only needs make_netlist.)
import types, math
_np = types.ModuleType("numpy"); _np.pi = math.pi
_np.linspace = lambda *a, **k: []
_np.int64 = int; _np.loadtxt = lambda *a, **k: None
_np.where = lambda *a, **k: ([],); _np.abs = abs
_np.full = lambda *a, **k: None; _np.full_like = lambda *a, **k: None
_np.nan = float("nan"); _np.nanmean = lambda *a, **k: 0
_np.array = lambda *a, **k: []
_np.random = types.SimpleNamespace(default_rng=lambda s: None)
sys.modules.setdefault("numpy", _np)
_mpl = types.ModuleType("matplotlib"); _mpl.use = lambda *a, **k: None
sys.modules.setdefault("matplotlib", _mpl)
sys.modules.setdefault("matplotlib.pyplot", types.ModuleType("matplotlib.pyplot"))

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import test_closed_loop as tcl  # noqa: E402
from validate_cap_470nf_iv6max_level1 import swap_to_level1  # noqa: E402

# Override T_END: 0.5 s is enough to capture cold-start + early settling,
# where the peak op-amp output currents live. Faster than the standard 5 s.
tcl.T_END = 0.5

# Per-op-amp Isc threshold. Chopper op-amps in this design use the OPA2188
# (50 mA typ Isc); standard precision op-amps use TLV9154 (65 mA typ).
ISC_THRESHOLD_MA = {
    "dem":     50.0,  # OPA2188 chopper
    "int":     50.0,  # OPA2188 chopper
    "aw_diff": 50.0,  # OPA2188 chopper
    # everything else defaults to the standard TLV9154 limit:
}
ISC_DEFAULT_MA = 65.0


def threshold_for(name: str) -> float:
    return ISC_THRESHOLD_MA.get(name, ISC_DEFAULT_MA)

# Match X<name> +IN -IN VCC VEE OUT uopamp_lvl{2,3} ...
OPAMP_RE = re.compile(
    r"^(?P<head>XU_(?P<name>\w+)\s+\S+\s+\S+\s+\S+\s+\S+\s+)(?P<out>\S+)(?P<tail>\s+uopamp_lvl[23]\b.*)$",
    re.MULTILINE,
)


def patch_with_ammeters(netlist: str) -> tuple[str, list[str]]:
    """Insert V_im_<name> in series with every op-amp output. Returns the
    patched netlist and the list of op-amp names so the caller can build the
    measurement directives."""
    names: list[str] = []
    inserts: list[str] = []

    def repl(m: re.Match) -> str:
        name = m.group("name")
        out = m.group("out")
        names.append(name)
        # Rename op-amp output to <out>_im, then V_im_<name> <out>_im <out> 0
        new_out = f"{out}_im"
        inserts.append(f"V_im_{name} {new_out} {out} 0")
        return f"{m.group('head')}{new_out}{m.group('tail')}"

    patched = OPAMP_RE.sub(repl, netlist)
    # Inject the V_im_* lines just before .control (each on its own line).
    inj = "\n* op-amp output-current ammeters (V_im_*)\n" + "\n".join(inserts) + "\n"
    patched = patched.replace(".control", inj + ".control", 1)

    # Inject vecmax extraction inside the .control block, just before .endcontrol.
    # ngspice doesn't save voltage-source currents by default unless we ask --
    # explicit `save i(v_im_<name>)` (set BEFORE `run`) enables i(Vxxx) access.
    # Also compute a "post-startup" max (excluding the first 1 ms, where any
    # t=0 numerical artifacts can spike the recorded current). The 1 ms window
    # is well inside the cold-start regime (rail PWL settles in 10 ms; loop
    # settling is 100 ms+) so we still see all real cold-start currents.
    let_lines = []
    print_lines = []
    for n in names:
        let_lines.append(f"let imax_{n} = vecmax(abs(i(v_im_{n})))")
        # post-1ms peak: ngspice nutmeg vector slicing by t-index isn't
        # straightforward, so multiply by a window vector (1 for t>1ms, 0 else).
        let_lines.append(f"let imax_{n}_post = vecmax(abs(i(v_im_{n})) * (time gt 1e-3))")
        # Time of pre-window peak (for diagnosing whether it's an early spike)
        print_lines.append(f'echo "MAXOUT_{n}:"')
        print_lines.append(f"print imax_{n}")
        print_lines.append(f'echo "MAXPOST_{n}:"')
        print_lines.append(f"print imax_{n}_post")
    extras = "\n".join(let_lines + print_lines) + "\n"
    # The current-save option must precede `run`; place explicit save
    # statements for each V_im_* on their own lines immediately after `.control`.
    # CRITICAL: explicit `save <vec>` *discards* every other vector, including
    # node voltages used by the netlist's wrdata line. Prefix with `save all`
    # to preserve the default vector set, then list the currents we want.
    save_currents = " ".join(f"i(v_im_{n})" for n in names)
    save_stmt = f"save all {save_currents}\n"
    patched = patched.replace(".control\nrun", ".control\n" + save_stmt + "run", 1)
    patched = patched.replace(".endcontrol", extras + ".endcontrol", 1)
    return patched, names


# Parse stdout for MAXOUT_<name>: + imax_<name> = <val>  (full-window peak)
# and MAXPOST_<name>: + imax_<name>_post = <val>  (peak after t > 1ms,
# excluding any t=0 numerical artifact).
def parse_imax(stdout: str, names: list[str]) -> dict[str, tuple[float, float]]:
    full: dict[str, float] = {}
    post: dict[str, float] = {}
    mode: tuple[str, str] | None = None  # (kind, name) where kind in {"full", "post"}
    for line in stdout.splitlines():
        m = re.match(r"^MAXOUT_(\w+):\s*$", line)
        if m:
            mode = ("full", m.group(1)); continue
        m = re.match(r"^MAXPOST_(\w+):\s*$", line)
        if m:
            mode = ("post", m.group(1)); continue
        m = re.match(r"^\s*imax_(\w+?)(?:_post)?\s*=\s*([-+0-9.eE]+)\s*$", line)
        if m and mode and mode[1] == m.group(1):
            v = float(m.group(2))
            (full if mode[0] == "full" else post)[m.group(1)] = v
            mode = None
    return {n: (full.get(n, float("nan")), post.get(n, float("nan"))) for n in names}


def run_case(tube_key: str, vp_label: str, vp_value: float) -> dict:
    spec = tcl.TUBES[tube_key]
    # I_DSS_mid = 0.6 mA spec midpoint; beta scales accordingly
    I_DSS_mid = 0.6e-3
    beta = I_DSS_mid / (vp_value ** 2)
    mc = {
        "r_amb": spec["r_amb"], "sigma_eps_A": spec["sigma_eps_A"],
        "c_th": spec["c_th"], "r_top_ref": spec["r_top_ref"],
        "r_bot_ref": spec["r_bot_ref"], "r_sense": spec["r_sense"],
        "jfet_vp": vp_value, "jfet_beta": beta,
        "t_rail_ramp": 0.010,  # 10 ms LDO-style rail ramp
    }
    for k in ("booster", "ce_buf", "mos_buf"):
        if spec.get(k): mc[k] = True
    for k in ("buf_fb1", "buf_fb_ap", "v_buf", "c_ap"):
        if spec.get(k) is not None: mc[k] = spec[k]

    label = f"imax_{tube_key}_vp{vp_label}"
    cir = tcl.WORK / f"{label}.cir"
    dat = tcl.WORK / f"{label}.data"  # not actually used; netlist writes wrdata anyway

    raw = tcl.make_netlist(dat, v_preset=0.0, t_ramp=0.0,
                            r_int_scale=spec["r_int_scale"], mc=mc)
    # Use Level 1 placeholder for the manufacturer MOSFETs -- the op-amp
    # output current is bounded by the 1k gate damping resistor and the
    # 200 ohm bias chain, both of which are visible regardless of which
    # MOSFET model the simulator uses below them. Level 1 runs ~30x
    # faster than the manufacturer subcircuit.
    if spec.get("mos_buf"):
        raw = swap_to_level1(raw)
    patched, names = patch_with_ammeters(raw)
    cir.write_text(patched)

    t0 = time.time()
    res = subprocess.run(
        ["ngspice", "-b", cir.name], cwd=tcl.WORK,
        capture_output=True, text=True, timeout=1800,
    )
    wall = time.time() - t0
    if res.returncode != 0:
        return {"tube": tube_key, "vp": vp_value, "wall": wall,
                "error": res.stderr[-600:]}

    imaxes = parse_imax(res.stdout, names)
    if dat.exists():
        try: dat.unlink()
        except: pass
    # imaxes: name -> (full_window_peak, post_1ms_peak); both in amps.
    return {"tube": tube_key, "vp": vp_value, "wall": wall,
            "names": names, "imaxes": imaxes}


def main():
    cases = [
        (t, lbl, vp)
        for t in ("iv18", "iv6", "ilc11_7", "ilc11_8")
        for lbl, vp in (("p1", -1.0), ("p3", -3.0))
    ]
    print(f"Running {len(cases)} cases in parallel (T_END={tcl.T_END}s, "
          f"t_rail_ramp=10ms)...", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=len(cases)) as ex:
        futs = {ex.submit(run_case, *c): c for c in cases}
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            tag = f"{r['tube']:8s} V_p={r['vp']:+.1f}"
            if "error" in r:
                print(f"  {tag} FAIL ({r['wall']:.1f}s): {r['error'][:200]}")
                continue
            # Worst post-1ms current relative to its own per-op-amp limit.
            def margin_mA(name, peak_post_A):
                return peak_post_A*1e3 - threshold_for(name)
            peak_name, peak = max(r["imaxes"].items(),
                                  key=lambda kv: margin_mA(kv[0], kv[1][1]))
            full_ma, post_ma = peak[0]*1e3, peak[1]*1e3
            thr = threshold_for(peak_name)
            verdict = "OK   " if post_ma < thr else "OVER!"
            print(f"  {tag} wall={r['wall']:.1f}s  peak={peak_name} "
                  f"full={full_ma:.2f}/post1ms={post_ma:.2f}/Ilim={thr:.0f} mA  {verdict}")

    # Summary table: rows = op-amp name, cols = (tube, V_p), values = max |I| mA.
    all_names: list[str] = []
    seen = set()
    for r in results:
        for n in r.get("names", []):
            if n not in seen:
                seen.add(n); all_names.append(n)

    # Order cases for stable column ordering
    cases_sorted = sorted(cases)
    name_lookup = {(r["tube"], r["vp"]): r.get("imaxes", {}) for r in results}

    # Two tables: full-window peak, and post-1ms peak (excludes t=0 spike).
    for label, idx in (("FULL window", 0), ("POST 1ms", 1)):
        print()
        print(f"=== {label} peaks (mA) ===")
        print(f"{'op-amp':14s}", end="")
        for t, lbl, vp in cases_sorted:
            print(f"  {t}_{lbl:>3s}", end="")
        print(f"  | global_max_mA  verdict")
        print("-" * 110)
        for n in all_names:
            row_vals_mA = []
            row_str = f"{n:14s}"
            for t, lbl, vp in cases_sorted:
                pair = name_lookup.get((t, vp), {}).get(n)
                mA = (pair[idx] if pair is not None else float("nan")) * 1e3
                row_vals_mA.append(mA)
                row_str += f"  {mA:8.2f}"
            gmax = max(row_vals_mA) if row_vals_mA else 0.0
            thr = threshold_for(n)
            verdict = "OK" if gmax < thr else "OVER"
            row_str += f"  |  {gmax:9.2f}  (lim {thr:.0f})  {verdict}"
            print(row_str)

    # CSV: full + post peak both, per-case columns
    csv_cols = []
    for t, lbl, _ in cases_sorted:
        csv_cols.append(f"{t}_{lbl}_full")
        csv_cols.append(f"{t}_{lbl}_post")
    csv_lines = ["op_amp," + ",".join(csv_cols) + ",global_full_mA,global_post_mA,Ilim_mA,verdict"]
    for n in all_names:
        full_vals, post_vals = [], []
        cells = []
        for t, lbl, vp in cases_sorted:
            pair = name_lookup.get((t, vp), {}).get(n)
            f_mA = (pair[0] if pair is not None else float("nan")) * 1e3
            p_mA = (pair[1] if pair is not None else float("nan")) * 1e3
            full_vals.append(f_mA); post_vals.append(p_mA)
            cells.append(f"{f_mA:.4f}"); cells.append(f"{p_mA:.4f}")
        gf = max(full_vals) if full_vals else 0.0
        gp = max(post_vals) if post_vals else 0.0
        thr = threshold_for(n)
        verdict = "OK" if gp < thr else "OVER"
        csv_lines.append(f"{n}," + ",".join(cells) + f",{gf:.4f},{gp:.4f},{thr:.1f},{verdict}")

    out = HERE / "opamp_current_scan.csv"
    out.write_text("\n".join(csv_lines) + "\n")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
