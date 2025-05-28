#!/usr/bin/env python3
"""
flyback_calcs.py

Compute boundary and steady-state parameters for a flyback converter
in DCM and CCM, per the equations in the Flyback.pdf (stades Flyback DCM2).
"""

import argparse
from topologies.flyback import (
    boundary_duty_cycle,
    dt_cycle,
    peak_current,
    energy_inductor,
    boundary_power,
    voltage_ratio_DCM,
    voltage_ratio_CCM,
)

def main():
    p = argparse.ArgumentParser(description="Flyback converter boundary & ratio calcs")
    p.add_argument("--Vin",   type=float, required=True, help="Input voltage (V)")
    p.add_argument("--Vout",  type=float, required=True, help="Desired output voltage (V)")
    p.add_argument("--Rload", type=float, required=True, help="Load resistance (Ω)")
    p.add_argument("--Fsw",   type=float, required=True, help="Switching frequency (Hz)")
    p.add_argument("--Lp",    type=float, required=True, help="Primary inductance (H)")
    p.add_argument("--Nps",   type=float, default=1.0, help="Turns ratio N_p:N_s")
    args = p.parse_args()

    # 1) Boundary duty cycle
    D_b = boundary_duty_cycle(args.Vin, args.Vout, args.Nps)

    # 2) Boundary peak current, energy, power
    I_pk = peak_current(args.Vin, args.Lp, D_b, args.Fsw)
    E_pk = energy_inductor(args.Lp, I_pk)
    P_b  = boundary_power(args.Vin, D_b, args.Lp, args.Fsw)

    # 3) Required load power at Vout
    P_load = args.Vout**2 / args.Rload

    # 4) DCM/DCM voltage ratio vs. desired:
    ratio_DCM = voltage_ratio_DCM(D_b, args.Rload, args.Lp, args.Fsw)
    ratio_CCM = voltage_ratio_CCM(D_b, args.Nps)

    # Report
    print(f"\n=== Flyback boundary & ratio calculations ===\n")
    print(f"Boundary duty cycle D₍b₎ : {D_b:.4f}")
    print(f"Peak primary current Iₚₖ : {I_pk:.4f} A")
    print(f"Stored energy Eₚₖ       : {E_pk:.4e} J")
    print(f"Boundary power P₍b₎      : {P_b:.4f} W")
    print(f"Required load power      : {P_load:.4f} W")
    print(f"\nMode check: ", end="")
    if P_load < P_b:
        print("DCM (required load < boundary power)")
    else:
        print("CCM (required load ≥ boundary power)")
    print(f"\nDCM steady-state ratio Vout/Vin: {ratio_DCM:.4f}")
    print(f"CCM steady-state ratio Vout/Vin: {ratio_CCM:.4f}")
    print()

if __name__ == "__main__":
    main()
