# tolerance examples

Worked end-to-end demos of `utils/tolerance` against real circuits.
Each script is self-contained — run it directly with `python3
examples/<name>.py` and it prints a `YieldReport`.

Both examples need `ngspice` on `PATH` and use the bundled
`ngspice_examples/uopamp.lib` macromodel.

## `eseries_to_tolerance_demo.py`

The two libraries together: `eseries_opt` finds the top-N E12
candidates for a Sallen-Key Butterworth design (4 components, 2
soft targets, 1 hard constraint), then `tolerance.analyze` runs a
20k-sample MC at realistic 5%R / 10%C tolerances against a
fc-within-2%, Q-within-3% spec for each candidate.

The output table juxtaposes the algebraic ranking (lowest target
error first) against the MC yield ranking. For this filter the two
rankings agree on the top — SK is symmetric in (R1, R2, C1, C2)
so no candidate sits on a sensitivity hot-spot — but the script
includes commentary about the topologies where they wouldn't, and
running this step is what tells you which case you're in.

Pure closed-form (no ngspice), runs in seconds on a laptop.

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
