"""Why does .options temp=50 fail? Test a temp ladder on iv6, capture ngspice's
own error output, and check whether it's convergence (sim artifact) or the
operating point genuinely breaking. Writes diag_temp50.txt."""
import sys, subprocess, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator as r

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diag_temp50.txt")
lines = []
def log(s): lines.append(s); print(s, flush=True)

for temp in [27, 40, 50, 55, 60]:
    W = f"/tmp/dt50_{temp}"; os.makedirs(W, exist_ok=True)
    cir = r.make_netlist(T_end=1.5, **r.TUBES["iv6"])
    cir = re.sub(r"(\.options reltol[^\n]*)", rf"\1\n.options temp={temp}", cir, count=1)
    cir = re.sub(r"wrdata \S+/run\.data", f"wrdata {W}/run.data", cir)
    open(f"{W}/run.cir", "w").write(cir)
    try:
        p = subprocess.run(["ngspice", "-b", "run.cir"], cwd=W, capture_output=True, text=True, timeout=400)
    except subprocess.TimeoutExpired:
        log(f"temp={temp}: TIMEOUT"); continue
    ok = os.path.exists(f"{W}/run.data")
    blob = (p.stderr + p.stdout)
    # pull the interesting lines (errors / convergence / aborts)
    hits = [ln for ln in blob.splitlines()
            if re.search(r"error|abort|singular|converg|gmin|timestep|too small|fatal|warning", ln, re.I)]
    log(f"=== temp={temp}: data={'YES' if ok else 'NO'} ===")
    for h in hits[-8:]:
        log("   " + h.strip()[:130])
    if not hits:
        log("   (no error/convergence keywords) tail: " + blob.strip().splitlines()[-1][:120] if blob.strip() else "   (empty)")

open(OUT, "w").write("\n".join(lines) + "\n")
print("WROTE", OUT, flush=True)
