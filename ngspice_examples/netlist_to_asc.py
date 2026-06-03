"""Netlist-to-LTspice-.asc converter for visualising the regulator schematic.

Drops every component on the page in a grid with short wire stubs to net
labels at each terminal. The placement is non-overlapping but otherwise
unstructured -- the user is expected to drag components into a
meaningful layout in LTspice once the components are visible on the page.

Usage:
    python3 netlist_to_asc.py [TUBE]
        TUBE in {iv18, iv6, ilc11_7, ilc11_8} (default: ilc11_7)

Writes regulator_<tube>.asc next to this script.
"""
from __future__ import annotations
import sys, types
import re
from pathlib import Path

HERE = Path(__file__).parent
# Stub matplotlib for hosts without it
for n in ("matplotlib", "matplotlib.pyplot"):
    sys.modules.setdefault(n, types.ModuleType(n))
sys.modules["matplotlib"].use = lambda *a, **kw: None
sys.modules["matplotlib"].pyplot = sys.modules["matplotlib.pyplot"]

# LTspice grid is 16 pixels per unit. Components are spaced ~256 px apart
# (16 grid units) so they don't overlap and stubs have room.
GRID = 16
COMPONENT_PITCH = 256          # horizontal pitch between components
COMPONENT_VPITCH = 256         # vertical pitch between rows
ROW_LEN = 8                    # components per row before wrapping
STUB_LEN = 64                  # length of wire stub from each terminal

# LTspice symbol pin offsets (relative to symbol origin, R0 rotation),
# from the actual symbols in /lib/sym. PIN_DIRECTIONS gives the direction
# the stub wire should be drawn from each pin so it doesn't run back through
# the symbol body.
PIN_OFFSETS = {
    "res":     [(16,  16), (16,  96)],
    "cap":     [(16,   0), (16,  64)],
    "diode":   [(16,   0), (16,  64)],
    "voltage": [(16,   0), (16,  96)],
    "npn":     [(64,  16), (16,  64), (64,  96)],   # C, B, E
    "pnp":     [(64,  16), (16,  64), (64,  96)],
    "njf":     [(32,   0), (0,   64), (32,  96)],   # D, G, S
    "pjf":     [(32,   0), (0,   64), (32,  96)],
    "sw":      [(-32, -16), (32, -16), (-32, 16), (32, 16)],   # n+, n-, ctrl+, ctrl-
    "bv":      [(16,   0), (16,  80)],
    "bi":      [(16,   0), (16,  80)],
    "opamp":   [(0,   32), (0,   64), (32,   0), (32,  96), (96,  48)],
}
PIN_DIRECTIONS = {  # direction for each stub: "up", "down", "left", "right"
    "res":     ["up",    "down"],
    "cap":     ["up",    "down"],
    "diode":   ["up",    "down"],
    "voltage": ["up",    "down"],
    "npn":     ["up",    "left",  "down"],   # C up, B left, E down
    "pnp":     ["up",    "left",  "down"],
    "njf":     ["up",    "left",  "down"],   # D up, G left, S down
    "pjf":     ["up",    "left",  "down"],
    "sw":      ["up",    "up",    "down",   "down"],
    "bv":      ["up",    "down"],
    "bi":      ["up",    "down"],
    "opamp":   ["left",  "left",  "up",     "down",  "right"],   # +IN, -IN, V+, V-, OUT
}


def parse_netlist(netlist: str):
    """Parse a netlist string, returning a list of component dicts."""
    components = []
    # Collect model definitions to determine NPN/PNP for each Q transistor
    model_kinds = {}  # model_name -> "NPN" / "PNP" / "NJF" / "PJF" / "D" / "SW"
    lines = netlist.splitlines()
    # Join continuation lines (start with +)
    joined = []
    for line in lines:
        line = line.rstrip()
        if line.startswith("+") and joined:
            joined[-1] += " " + line[1:].strip()
        else:
            joined.append(line)

    # First pass: collect models
    for line in joined:
        ls = line.strip()
        if ls.lower().startswith(".model"):
            parts = ls.split()
            if len(parts) >= 3:
                mname = parts[1]
                # The 3rd token may be NPN/PNP/NJF/D/SW or have ( appended
                kind = parts[2].split("(")[0].upper()
                model_kinds[mname] = kind

    for line in joined:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("."):
            components.append({"type": "directive", "text": line})
            continue
        # Skip ngspice control commands inside .control...endcontrol
        if line.lower() in ("run",) or line.lower().startswith("wrdata"):
            components.append({"type": "directive", "text": "* " + line})
            continue
        parts = line.split()
        if not parts:
            continue
        ref = parts[0]
        prefix = ref[0].upper()
        comp = {"ref": ref, "prefix": prefix, "raw": line}
        if prefix == "R":
            comp.update({"type": "res", "nodes": parts[1:3], "value": parts[3] if len(parts) > 3 else "?"})
        elif prefix == "C":
            comp.update({"type": "cap", "nodes": parts[1:3], "value": parts[3] if len(parts) > 3 else "?"})
        elif prefix == "D":
            comp.update({"type": "diode", "nodes": parts[1:3], "model": parts[3] if len(parts) > 3 else "?"})
        elif prefix == "Q":
            nodes = parts[1:4]
            model = parts[-1]
            kind = model_kinds.get(model, "NPN")
            sym = "pnp" if kind == "PNP" else "npn"
            comp.update({"type": sym, "nodes": nodes, "model": model})
        elif prefix == "J":
            nodes = parts[1:4]
            model = parts[4] if len(parts) > 4 else "?"
            kind = model_kinds.get(model, "NJF")
            sym = "pjf" if kind == "PJF" else "njf"
            comp.update({"type": sym, "nodes": nodes, "model": model})
        elif prefix == "V":
            comp.update({"type": "voltage", "nodes": parts[1:3], "value": " ".join(parts[3:])})
        elif prefix == "B":
            # B name n+ n- (V|I) = expression
            expr = " ".join(parts[3:])
            is_current = expr.lstrip().upper().startswith("I")
            comp.update({"type": "bi" if is_current else "bv", "nodes": parts[1:3], "expr": expr})
        elif prefix == "S":
            # S name n+ n- ctrl+ ctrl- model
            comp.update({"type": "sw", "nodes": parts[1:5], "model": parts[5] if len(parts) > 5 else "?"})
        elif prefix == "X":
            # X name <pins...> subckt [params]
            # Universal opamp: X<n> <+IN> <-IN> <VCC> <VEE> <OUT> uopamp_lvl2 ...
            # Find the subcircuit name token (last word that doesn't look like a node)
            subckt = "?"
            pin_count = 5
            for k in range(len(parts) - 1, 0, -1):
                if parts[k].lower().startswith("uopamp_lvl"):
                    subckt = parts[k]
                    pin_count = k - 1
                    break
            comp.update({"type": "opamp", "nodes": parts[1:pin_count + 1], "subckt": subckt,
                         "subckt_args": " ".join(parts[pin_count + 2:])})
        else:
            comp.update({"type": "unknown", "nodes": [], "raw": line})
        components.append(comp)
    return components


def emit_asc(components, out_path: Path, title: str):
    """Emit an .asc file with all components placed in a grid, each pin
    stubbed out to a net label."""
    lines = ["Version 4", "SHEET 1 8000 8000"]
    flags_emitted = set()  # avoid duplicate flag at same coord

    # Lay out components on a grid
    placeable = [c for c in components if c.get("type") not in (None, "directive", "unknown") and c.get("nodes")]
    text_directives = [c for c in components if c.get("type") in ("directive", "unknown")]

    for i, comp in enumerate(placeable):
        row = i // ROW_LEN
        col = i % ROW_LEN
        x = col * COMPONENT_PITCH + 64
        y = row * COMPONENT_VPITCH + 64

        ctype = comp["type"]
        # Map our types to LTspice symbol names
        sym_map = {
            "res": "res", "cap": "cap", "diode": "diode",
            "npn": "npn", "pnp": "pnp",
            "njf": "njf", "pjf": "pjf",
            "voltage": "voltage",
            "bv": "bv", "bi": "bi",
            "sw": "sw",
            "opamp": "opamp2",   # generic 5-pin opamp from LTspice library
        }
        sym = sym_map.get(ctype, "res")
        # Pin offsets keyed by symbol family
        offs_key = ctype if ctype in PIN_OFFSETS else sym.split("/")[-1]
        pin_offs = PIN_OFFSETS.get(offs_key, [(0, 0)] * max(1, len(comp.get("nodes", []))))

        lines.append(f"SYMBOL {sym} {x} {y} R0")
        lines.append(f"SYMATTR InstName {comp['ref']}")
        if "value" in comp:
            lines.append(f"SYMATTR Value {comp['value']}")
        elif "model" in comp:
            lines.append(f"SYMATTR Value {comp['model']}")
        elif "expr" in comp:
            # B-source: the value attribute holds the expression
            # LTspice expects the form "V=..." or "I=..."
            lines.append(f"SYMATTR Value {comp['expr']}")
        elif ctype == "opamp":
            lines.append(f"SYMATTR Value {comp.get('subckt', 'uopamp_lvl2')}")
            if comp.get("subckt_args"):
                lines.append(f"SYMATTR Value2 {comp['subckt_args']}")

        # For each terminal, emit a wire stub and a flag
        nodes = comp.get("nodes", [])
        pin_dirs = PIN_DIRECTIONS.get(offs_key, ["down"] * len(pin_offs))
        for k, node in enumerate(nodes):
            if k >= len(pin_offs):
                continue
            px, py = pin_offs[k]
            pin_x = x + px
            pin_y = y + py
            direction = pin_dirs[k] if k < len(pin_dirs) else "down"
            if direction == "up":
                end_x, end_y = pin_x, pin_y - STUB_LEN
            elif direction == "down":
                end_x, end_y = pin_x, pin_y + STUB_LEN
            elif direction == "left":
                end_x, end_y = pin_x - STUB_LEN, pin_y
            else:  # right
                end_x, end_y = pin_x + STUB_LEN, pin_y
            lines.append(f"WIRE {pin_x} {pin_y} {end_x} {end_y}")
            flag_key = (end_x, end_y)
            if flag_key not in flags_emitted:
                lines.append(f"FLAG {end_x} {end_y} {node}")
                flags_emitted.add(flag_key)

    # Add directives as a TEXT block
    if text_directives:
        text_x = 64
        text_y = (len(placeable) // ROW_LEN + 2) * COMPONENT_VPITCH
        text_block = "\\n".join(t["text"] if t["type"] == "directive"
                                else f"; UNKNOWN: {t.get('raw','')}"
                                for t in text_directives)
        lines.append(f"TEXT {text_x} {text_y} Left 2 !{text_block}")

    # Title text
    lines.insert(2, f"TEXT 64 16 Left 4 ;{title}")

    out_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out_path} ({len(placeable)} components, {len(text_directives)} directives)")


def main():
    tube = sys.argv[1] if len(sys.argv) > 1 else "ilc11_7"
    sys.path.insert(0, str(HERE))
    import regulator as m
    if tube not in m.TUBES:
        print(f"Unknown tube {tube}; available: {list(m.TUBES.keys())}")
        sys.exit(1)
    netlist = m.make_netlist(**m.TUBES[tube])
    components = parse_netlist(netlist)
    out_path = HERE / f"regulator_{tube}.asc"
    name = m.TUBE_NAMES.get(tube, tube)
    title = f"VFD-filament regulator for {name} (tube={tube})"
    emit_asc(components, out_path, title)


if __name__ == "__main__":
    main()
