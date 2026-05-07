# Tolerance analysis library — design briefing

**Status:** design only, no code yet. This document captures the
context and decisions from the session that built `utils/eseries_opt`,
so a fresh session can pick up the tolerance-analysis work without
re-deriving the rationale.

## What it's for

`utils/eseries_opt` searches the discrete E-series component space
against open-loop algebraic targets and returns ranked candidates.
The `Result.sensitivity` field it computes is a worst-case 2^N
corner perturbation of the same algebraic target — useful as a
red-flag indicator, but three layers of approximation away from
production yield:

- **Pessimistic.** Assumes every component sits at its tolerance
  extreme pushing the same direction. Gaussian reality is 2-4×
  lower at the 99th percentile.
- **Open-loop.** The algebraic target is treated as the system. Inside
  feedback loops, perturbations are absorbed until they push gain
  margin negative, at which point regulation collapses
  catastrophically — neither smooth nor captured by perturbing the
  target equation.
- **Passives only.** Op-amp Vos / Avol / Ib spreads, BJT β, FET Vto
  routinely swamp 1% R / 5% C and aren't represented.

This library handles all three.

## The seam

`eseries_opt` produces candidates; tolerance evaluates them against a
richer system model. Sketched API from the design discussion:

```python
from utils.tolerance import analyze

candidates = problem.solve(strategy="bnb", n_results=5)

for c in candidates:
    report = analyze(
        netlist_template="ngspice_examples/regulator_iv6.cir",
        nominal_values=c.values,
        passive_tolerances={"R": 0.01, "C": 0.05},
        active_spreads={
            "U_opamp": "NE5532",      # → Vos~3mV, Ib~200nA, Avol [50k,2M]
            "Q_npn":   "2N3904",      # → β [100,400]
            "J_jfet":  "J201",        # → Vto [-0.4,-2.3]
        },
        spec={
            "regulation_error": ("<", 0.02),    # 2% at SS
            "overshoot":         ("<", 50),     # K above target
            "settling_time":     ("<", 1.5),    # s
            "phase_margin":      (">", 45),     # degrees
        },
        n_mc=1000,
    )
    print(c, report.yield_pct, report.failure_modes)
```

Three inputs that don't exist in `eseries_opt`:

1. **System model** — a netlist template (or a Bode/state-space
   description) that connects the components into a loop with the
   active devices.
2. **Active-device spread library** — per-part-number distributions for
   datasheet-spec parameters (Vos, β, Vto, Avol, GBW, Iq, Vrail).
3. **Spec** — what defines a "good" outcome. These are temporal /
   stability metrics, not just the static composite-error number
   that `eseries_opt` minimises.

## Decisions already made (in chat)

- **Separate library, not a feature of `eseries_opt`.** The two
  problems have different shapes: optimisation is static and
  algebraic; tolerance is dynamic and stochastic.
- **Closed-loop awareness is essential.** Open-loop sensitivity
  without loop context is wrong by orders of magnitude for any
  regulator-class circuit.
- **MC, not corner evaluation.** Corner eval over 5+ components is
  pessimistic by 2-4× vs realistic Gaussian distributions. MC with
  per-component tolerance is the honest default.
- **Per-type tolerances.** The current `eseries_opt` uses a single
  uniform tolerance; real designs mix 1% R / 5% C / 20% electrolytics.
- **Yield reports, not single numbers.** "Of 1000 MC samples, 2%
  missed regulation_error and 0.3% missed phase_margin" is what
  drives a design decision; a single composite-error percentile
  isn't.
- **`Result.sensitivity` stays as the rough first-look indicator** in
  `eseries_opt`, with a docstring caveat (already added in
  `utils/eseries_opt/result.py`) pointing here.

## Open questions

- **Simulator backend.** Three candidates:
  - `ngspice` — already used elsewhere in this project; handles
    arbitrary netlists, slow per-run, the natural fit for the
    regulator class. Existing tooling: `ngspice_examples/`.
  - `lcapy` — symbolic linear analysis. Faster, limited to LTI.
    Could cover op-amp circuits without rail saturation, but not the
    diode-clamped Wien oscillator or the JFET-in-linear-region
    all-pass.
  - Hand-rolled state-space + numpy — fast, requires the user to
    write the model.

  Probably ngspice for the regulator class and lcapy / state-space
  for filter / Bode-only problems. Maybe a `backend=` selector.

- **Active-spread library.** Curated per-part-number datasheets
  (`NE5532 → {Vos: ±3mV, Ib: ±200nA, ...}`) is more useful but more
  work. Generic per-parameter distributions (user fills in) is
  flexible but tedious. Probably curated for the parts already used
  in `ngspice_examples/` (NE5532, 2N3904, J201, TLV9104) and a
  generic fallback for everything else.

- **Spec format.** Expression-based (`"phase_margin > 45"`) is
  ergonomic but requires a parser. Tuple-based (`("phase_margin",
  ">", 45)`) is uglier but trivial to dispatch on. Tuple is probably
  right.

- **What counts as a "failure mode".** A spec violation, sure, but
  also: did the simulation converge? Did the loop oscillate? Did the
  output saturate? Categorise these or fold them all into "spec
  not met"?

- **Caching of simulation runs.** ngspice runs are expensive (seconds
  each). With 1000 MC samples × 5 candidates = 5000 runs = potentially
  hours. Caching by parameter-tuple is essential. Where does the cache
  live?

- **How does the user describe the netlist template?** Options:
  - String template with `{R_INT}`-style placeholders
  - Reference to an existing `.cir` file plus a parameter-extraction
    convention
  - Programmatic: build the netlist from a Python description

  The existing `ngspice_examples/test_closed_loop.py` and
  `dump_netlists.py` both already do this; the library should
  consolidate the pattern.

## Existing tooling to build on

In `ngspice_examples/`:

- `test_closed_loop.py` — programmatic netlist generation, currently
  a sweeping test harness
- `filament_mc_postprocess.py` — MC sweep postprocessing
- `filament_corners_*.csv` — corner sweep data format
- `compare_settling_levers.py` — sensitivity analysis on PID values
- `dump_netlists.py` — netlist generator for multiple tubes
- `regulator_*.cir`, `wien_filament_regulator.cir` — real closed-loop
  circuits to validate against

The library will likely subsume parts of these — they're the
existing-but-informal version of what it should provide as an API.

## Suggested first slice

A minimum useful starting point that exercises the seam without
requiring all the design questions answered:

1. **Hand-rolled state-space backend, no ngspice yet.** Pick a
   well-defined LTI system (e.g. the Sallen-Key low-pass test in
   `tests/test_eseries_opt.py`) where the transfer function is
   closed-form. No active-device spread, just passive MC.

2. **Spec on transfer-function values:** fc within 5%, Q within 10%,
   peak gain within 1 dB. Compute analytically from the perturbed
   state-space.

3. **Yield report:** `(samples_total, samples_pass, per_spec_pass_count)`.

4. **Tests:** TDD as before. RC and Sallen-Key happy paths. Edge case:
   spec impossible to meet (yield 0%) without raising.

This gets the API and report format right on a problem with no
nonlinear or temporal complexity. The ngspice backend, active-device
spreads, and stability analysis come in later slices, each
self-contained. Each slice has a candidate from `eseries_opt` as its
input — so `eseries_opt`'s end-to-end tests double as integration
fixtures here.

## What NOT to start with

- **Ngspice integration.** Tempting because it covers the regulator
  problem out of the box, but it brings in process management,
  netlist generation, output parsing, caching, and convergence
  failure handling all at once. Defer until the API shape is settled
  on the LTI case.
- **Curated active-device library.** Datasheet-mining 30 op-amps is
  open-ended. Start with two or three (the ones in
  `ngspice_examples/`) and a generic fallback.
- **Tolerance-aware ranking inside `eseries_opt`.** Tempting to
  feed yield numbers back into `eseries_opt`'s ranker, but it
  couples the libraries. Keep the boundary at "user runs candidates
  through `tolerance.analyze` and re-ranks themselves" until there's
  a real use case for tighter integration.

## Pointers

- **`utils/eseries_opt/`** — the upstream library. Public API in
  `__init__.py`; sensitivity caveat in `result.py`.
- **`tests/test_eseries_opt.py`** — patterns to copy: `xfail` stubs
  for deferred features, equivalence tests against a known-good
  reference (e.g. brute-force), behavioural-documentation tests that
  pin down soundness limitations.
- **`CLAUDE.md`** at the repo root — project conventions: real
  circuits over simulator artefacts, regenerate derived artifacts
  when source changes, etc. Read before starting.
