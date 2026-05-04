# Project conventions for Claude

## We are designing a real circuit, not perfecting a simulation

The goal of every change is a circuit that can be built with real
components, not a netlist that produces ever-cleaner numbers in
ngspice. When proposing improvements, prefer simple, physically
realisable solutions over elaborate spice tweaks. Examples:

- A 3 dB difference in simulated phase margin doesn't matter if the
  PCB and real op-amps will produce 10 dB of variation.
- "Set Vos=0" tells us the loop's noiseless equilibrium, not what the
  built circuit will do. Real op-amps have Vos; account for it.
- A simulation that converges 50 ms faster but requires extra parts
  costing £5 isn't an improvement for a hobby/replica build.
- ngspice numerical stability issues (e.g. timestep collapse at switch
  edges) are simulator artefacts. Don't optimise for them at the cost
  of the real circuit's behaviour.

When you find yourself solving a problem that wouldn't exist in
hardware, stop and ask whether the problem is real.

## Always commit the latest versions of generated artifacts after a test

When a simulation, sweep, or netlist generator changes behaviour, **regenerate
and commit any derived artifacts that downstream consumers rely on** — even if
they were committed at an earlier point. Stale artifacts cause confusion when
the user goes to inspect them and finds they don't match the current code.

In this repo specifically, after any change to `test_closed_loop.py` that
affects the netlist topology or component values:

- Regenerate `regulator_<tube>.cir` via `python3 dump_netlists.py`
- Regenerate `regulator_<tube>.asc` via `python3 netlist_to_asc.py <tube>` for
  each tube in `TUBES`
- Commit and push both alongside the code change
- The `.cir` is what the user uses to verify their LTspice schematic; the
  `.asc` is what they open for visualisation. Both must match the code that
  produced the test results being reported.

Same principle for any other generated outputs (`*.csv`, `*.png`, reports)
that document a specific simulation run.

## Analyse the underlying data, not plots

When investigating circuit behaviour, base every claim on numerical
analysis of the raw waveform data — not on visual inspection of a
plot. PNGs are for the user; quantitative work needs the numbers.

This rule exists because eyeballing plots repeatedly causes me to:
- Miss short-duration excursions that span only a few pixels
- Overlook small-amplitude features against a large vertical range
- Misread phase or amplitude differences that look small but are
  significant in the operating context (e.g., a 100 mV dip on a 7 V
  swing looks like nothing on a plot but is enough to reverse-bias
  a BJT)

For any waveform claim, the workflow is:
1. Capture the relevant signals into a numpy array (via wrdata or
   ngspice raw file)
2. Compute the actual statistics or extract the actual values at
   the points of interest
3. Report numbers, not appearances. If a plot is also produced, it
   is an aid for the user, not a substitute for the analysis.

The same applies to "the waveform looks clean" — that means nothing
without measuring THD or comparing peak/RMS to a fitted sine.
