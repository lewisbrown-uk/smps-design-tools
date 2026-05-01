# Project conventions for Claude

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
