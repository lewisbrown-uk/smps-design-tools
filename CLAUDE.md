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
- A simulation that converges 50 ms faster purely because of an
  ngspice tuning trick (smaller timestep, IC fudges) is not a real
  improvement -- the built circuit will behave however its physical
  components dictate, regardless of the simulator's settling speed.
- ngspice numerical stability issues (e.g. timestep collapse at switch
  edges) are simulator artefacts. Don't optimise for them at the cost
  of the real circuit's behaviour.

When you find yourself solving a problem that wouldn't exist in
hardware, stop and ask whether the problem is real.

## "Hobby build" means MORE design freedom, not less, but it isn't unlimited

Don't justify accepting performance compromises by appealing to "this
is a hobby build". A hobby build has MORE freedom than a manufactured
product:

- BOM cost pressure is loose, not absent — target ~$20/tube. Can use
  more components, modestly priced precision parts, etc., but not
  exotic op-amps or precision resistor arrays at $30 each.
- No PCB area constraint → can use through-hole, generous spacing,
  more passive components.
- No regulatory compliance shortcuts → can use whatever quenches RFI
  most effectively.

But two practical constraints DO apply:

- **No build-time trimming.** The design is intended to be published
  on a forum, where people will build it without access to the rare
  filaments themselves. Bench testing trim pots on real filaments is
  risky — particularly for ILC1-1/7 where the displays are scarce and
  irreplaceable. Prefer self-biasing topologies, matched-pair tracking
  (e.g., V_BE multiplier with thermal coupling, diode-connected MOSFET
  bias), or robust passive bias that works across worst-case part
  variation. Trim-free is a hard requirement.
- **Buildability matters.** The design should be something a forum
  reader would realistically attempt — not "well-equipped lab
  prototype". Avoid: SMT-only assemblies smaller than 0805 / SOT-23,
  parts that require hot air, exotic transformers that need winding
  by hand, microcontroller code where analog would do.

The right mental model is "publishable forum project, ~$20/tube, no
trimming required, drop-in for builders". When proposing trade-offs,
weigh them against *will a stranger be able to build this and have
it work*, not *manufacturability of thousands* (commercial) and not
*manufacturability of one with full lab access* (lab prototype).

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
