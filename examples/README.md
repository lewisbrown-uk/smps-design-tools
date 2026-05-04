# tolerance examples

Worked end-to-end demos of `utils/tolerance` against real circuits.
Each script is self-contained — run it directly with `python3
examples/<name>.py` and it prints a `YieldReport`.

Both examples need `ngspice` on `PATH` and use the bundled
`ngspice_examples/uopamp.lib` macromodel.

## `temperature_circuits.py`

Temperature analysis on four demo circuits:

- **Sallen-Key Butterworth** (closed-form): X7R ceramic + metal-film
  R combo drops yield to 0% at corners; precision parts (C0G + metal-
  film) are flat 100% across -40 to +85°C. Q is invariant under
  proportional tempco scaling (it's a ratio); only fc drifts.
- **Wien oscillator** (ngspice tran with lock-in THD + `.temp`): the
  diode-clamp Wien topology is famously robust against active-device
  variation. The library tempcos for the NE5532 (Vos additive drift,
  Ib doubling per 10°C, Avol/GBW drift) are auto-applied via
  `active_devices=`, but the headline f0 metric only drifts with the
  passive R/C tempco mismatch.
- **Marginal LDO load-step ringing** (ngspice tran with `.temp` +
  NE5532 library tempcos): yield drops 19 percentage points from
  +80°C (95%) to -40°C (76%) — steeper than the LDO without active
  tempcos because Avol/GBW drift now compounds with the BJT V_BE/β
  temperature behaviour. Cold-corner ringing RMS mean is roughly
  2× the hot-corner mean.
- **Marginal LDO Middlebrook PM** (ngspice .ac with `.temp` + NE5532
  library tempcos): PM rises monotonically with T, confirming the
  time-domain finding. Cross-validates that cold is binding.

Saves four charts at `/tmp/temp_*.png`. Closed-form section is
instant; the three ngspice sweeps take ~3 min + ~65s + ~26s on a
laptop. Re-runs are cheap because each ngspice sweep persists its
results to a sqlite cache (`/tmp/temp_*.sqlite`).

## `scatter_temperature.py`

Scatter plots reading the cached results from
`temperature_circuits.py` (must run that first). For each of Wien /
LDO ringing / LDO PM, builds a 3-panel figure:

- **Top**: binding metric vs T across every MC sample, jittered and
  coloured by spec pass/fail. Shows the headline T effect — bias
  shift, fan-out, or both.
- **Bottom (×2)**: binding metric vs the two strongest room-T
  predictors (Pearson ρ ranked at the room-T corner), faceted by
  cold / mid / hot T-corners. The cloud-shift pattern reveals
  whether T bites by translating the population (mean shift) or by
  rotating the sensitivity slope (predictor sensitivity changes
  with T).

Findings:

- **Wien v_pp**: 2N3904 V_BE drops ~2 mV/°C → diode-clamp threshold
  drifts → v_pp shifts linearly with T across the whole population.
  Per-sample C1/C2 sensitivity is the same at every T — the
  T-effect is a bias, not a sensitivity amplification. Strongest
  room-T predictors: C1 (ρ ≈ +0.58), C2 (ρ ≈ −0.55).
- **LDO ringing**: cold corner has higher ring_rms mean and a
  larger fraction of samples > 15 mV spec. Strongest predictors:
  Q1_BF (ρ ≈ −0.55) and Resr (ρ ≈ −0.54), matching the
  marginal_ldo_demo.py 100k-sample finding.
- **LDO PM**: ESR is overwhelmingly the dominant predictor (ρ ≈
  +0.93) — ESR is what creates the zero that compensates the
  output pole, so PM rises monotonically with ESR. Cold corner
  shifts the cloud down by ~0.5° but the slope vs ESR is constant.

Saves charts at `/tmp/temp_scatter_<name>.png`. Pure post-processing
on the cached data — runs in seconds with no ngspice calls.

## `temperature_demo.py`

Precision divider over the -40 to +85°C industrial range using
the **corners** mode (MC at each corner T separately) and a finer
**sweep** to find the worst T.

Three component configurations: mismatched tempcos (50 vs 200
ppm/°C), matched tempcos (both 50), and matched + reel-mate
correlation. Mismatched tempcos give 99.98% yield at +25°C but
**0% at both -40°C and +85°C** — the binary "doesn't work at
corners" the random-T mode would have hidden.

The sweep panel shows the yield-vs-T curve: σ_ratio stays
constant at ~120 ppm across T (tempco drift shifts the mean, not
the spread); yield falls because the mean walks past the spec
edges. Demonstrates `analyze_corners`, `temperature_sweep`, and
why those are the right tools versus random-T sampling.

## `asymmetric_tolerance_demo.py`

Constructed example showing where the Robust ranker picks
*qualitatively different* candidates from the algebraic ranker.

A series-pair resistor design with R1 from a tight-binned 1% class
and R2 from a wider 5% class. Two candidates that hit the algebraic
target exactly (same nominal sum, same algebraic error 0) differ
in yield by ~15 percentage points because R2's per-ohm tolerance is
5× R1's — the algebraic ranker can't see the asymmetry. The Robust
ranker systematically prefers small-R2 candidates; only 2 of its
top 8 overlap with the algebraic top 8.

This is the cleanest demonstration that "algebra first, robustness
check second" can miss the right design. Exercises the per-component
tolerance override in `passive_tolerances` (lookup by full name
first, then by SPICE prefix).

## `eseries_to_tolerance_demo.py`

The two libraries together, two ways:

- **Flow 1 (post-hoc)**: `eseries_opt` ranks by algebraic target
  error; `tolerance.analyze` runs MC on the top-N. Cheap but can
  miss the most-robust candidate if it's not in the algebraic top-N.
- **Flow 2 (direct)**: `tolerance.Robust` ranker scores every
  feasible candidate by MC yield, the search returns the top-N most
  robust by construction. More expensive (one MC sweep per
  candidate) but always principled.

For the Sallen-Key Butterworth design used here the two flows pick
the same winner (SK has uniform relative-sensitivity across the
design space, so all candidates have ~equivalent yield). The Robust
ranker pays for itself when active-device spreads, correlations, or
asymmetric topologies break the uniform-sensitivity assumption — the
script's discussion section spells out the situations.

Pure closed-form (no ngspice). Flow 1 takes <1s, Flow 2 takes
~1 minute (full enumeration × MC).

## `wien_thd_demo.py`

Wien bridge oscillator with diode amplitude clamp. Demonstrates how
to extract scalar metrics that aren't directly supported by ngspice
`.meas` syntax — in this case **THD+N via parabolic-fit lock-in
detection**, all expressed inline in a `.control` block.

The pipeline projects the (DC-removed) settled output onto sin/cos
basis vectors at three nearby frequencies, refines the fundamental
frequency by parabolic fit on the residuals, then projects again at
the refined frequency to extract the fundamental amplitude (a_rms).
THD+N is the residual-RMS / fundamental-RMS ratio.

Useful as a template for any oscillator MC where you need to track
THD across component variation. The Wien specifically shows that
op-amp / BJT spreads are essentially decoupled from THD by the
diode clamp — the binding tolerance is on the gain-network resistors.

## `middlebrook_pm_demo.py`

Same marginal LDO topology as `marginal_ldo_demo.py`, but measures
**phase margin via Middlebrook V-injection** instead of time-domain
ringing. Inserts a 0-V-DC, 1-V-AC voltage source in series at one
point in the loop, computes loop gain T(s) = V(after)/V(before)
across frequency, finds unity-gain crossover, reads phase at
crossover.

Useful as a frequency-domain stability metric when MC sample count
is large enough that the per-sample time-domain `.tran` cost is
prohibitive — AC analysis runs in milliseconds where transient
takes hundreds of milliseconds.

The absolute PM number coming out is suspiciously low for this
topology (single digits where textbook would predict 30-60°), most
likely from non-dominant poles in the BJT junction caps and op-amp
macromodel. **Use the metric for relative ranking across an MC
sweep, not as an absolute design target.** Validation: at 400
samples, Middlebrook PM correlates ρ ≈ -0.71 with the ringing-RMS
metric from `marginal_ldo_demo.py` — same physics, two different
measurement windows on it.

## `marginal_ldo_demo.py`

Op-amp + NPN series regulator chosen to be marginal: low-ESR ceramic
output cap with no compensating ESR-zero, slow op-amp, output pole
inside the loop bandwidth. Demonstrates **time-domain stability
metrics** (overshoot, undershoot, ringing-RMS) extracted from a
`.tran` load-step response.

Also demonstrates how to use **custom `Sampler` instances** for
parameters the curated DEVICES library doesn't cover — here a slow
op-amp's GBW and a low-ESR ceramic cap's Resr — without going
through `active_devices=`.

The 100k-sample run on a cluster (not in this script) shows the
dominant ringing predictors are ESR (ρ = −0.57) and BJT β
(ρ = −0.53), not the op-amp parameters. The classic "low-ESR caps
make LDOs ring" wisdom is correctly named, and BJT loading on the
op-amp output is the second binding constraint.

## scaling up

Both examples default to a small `n_mc` so they run in a few
seconds on a laptop. To scale up against a remote ngspice cluster,
swap the backend wiring for `RemoteNgspiceBackend(host="...")` and
bump `n_mc` and `workers`. See `utils/tolerance/remote.py` for the
ssh-multiplexer setup.
