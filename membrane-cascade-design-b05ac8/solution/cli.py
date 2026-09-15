
"""CLI entry point for membrane_analysis package."""

import sys
import json
import argparse


def main():
    parser = argparse.ArgumentParser(
        prog="membrane_analysis",
        description="Membrane gas separation analysis tool",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # EOS subcommand
    eos_parser = subparsers.add_parser("eos", help="EOS calculations")
    eos_parser.add_argument("--gas", required=True, help="Gas name or comma-separated pair")
    eos_parser.add_argument("--T", type=float, required=True, help="Temperature (K)")
    eos_parser.add_argument("--P", type=float, required=True, help="Pressure (bar)")
    eos_parser.add_argument("--composition", default=None, help="Comma-separated mole fractions")

    # Validate subcommand
    val_parser = subparsers.add_parser("validate", help="Validate EOS against NIST data")
    val_parser.add_argument("--gas", required=True, help="Gas name")
    val_parser.add_argument("--pressure", type=float, required=True, help="Pressure (atm)")

    # Robeson subcommand
    rob_parser = subparsers.add_parser("robeson", help="Robeson upper bound evaluation")
    rob_parser.add_argument("--gas-pair", required=True, help="Gas pair, e.g. CO2/CH4")
    rob_parser.add_argument("--polymer", default=None, help="Polymer abbreviation")

    # Cascade subcommand
    cas_parser = subparsers.add_parser("cascade", help="Two-stage cascade design")
    cas_parser.add_argument("--config", required=True, help="Path to config JSON")

    args = parser.parse_args()

    if args.subcommand == "eos":
        from .eos import pr_fugacity_pure, pr_fugacity_mixture

        gases = [g.strip() for g in args.gas.split(",")]
        if len(gases) == 1:
            result = pr_fugacity_pure(gases[0], args.T, args.P)
        else:
            if args.composition is None:
                print("Error: --composition required for mixtures", file=sys.stderr)
                sys.exit(1)
            fracs = [float(x.strip()) for x in args.composition.split(",")]
            if len(fracs) != len(gases):
                print("Error: number of compositions must match gases", file=sys.stderr)
                sys.exit(1)
            result = pr_fugacity_mixture(gases, fracs, args.T, args.P)
        print(json.dumps(result))

    elif args.subcommand == "validate":
        from .validate import validate_eos

        result = validate_eos(args.gas, args.pressure)
        print(json.dumps(result))

    elif args.subcommand == "robeson":
        from .robeson import rank_polymers

        result = rank_polymers(args.gas_pair, args.polymer)
        print(json.dumps(result))

    elif args.subcommand == "cascade":
        from .cascade import design_cascade

        result = design_cascade(args.config)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
