"""Dump the canonical regulator netlist (as regulator.make_netlist
generates it) for each tube to a .cir file.  The .cir is the reference used
to cross-check a hand-drawn LTspice schematic against the ngspice netlist
when diagnosing why a converted .asc doesn't simulate quite the same way.
"""
from pathlib import Path
import sys

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import regulator as m


def main():
    for tube_key, params in m.TUBES.items():
        name = m.TUBE_NAMES.get(tube_key, tube_key)
        netlist = m.make_netlist(**params)
        out = HERE / f"regulator_{tube_key}.cir"
        header = (
            f"* VFD-filament regulator netlist for {name} (tube={tube_key})\n"
            f"* Generated from regulator.py make_netlist (TUBES['{tube_key}']);\n"
            f"* matches the netlist that regulator_{tube_key}.asc was converted from.\n\n"
        )
        out.write_text(header + netlist)
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()
