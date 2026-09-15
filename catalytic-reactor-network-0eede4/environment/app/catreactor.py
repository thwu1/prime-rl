#!/usr/bin/env python3
"""Catalytic reactor simulation CLI tool."""
import json
import sys

from reactor.kinetics import evaluate_rate
from reactor.network import solve_network
from reactor.dbutil import load_species_from_db


def cmd_rate(data):
    if data.get("source") == "database":
        db_path = data.get("db_path", "/app/properties.db")
        species = {}
        for name in data["species_names"]:
            species[name] = load_species_from_db(db_path, name)
        data = dict(data)
        data["species"] = species
    return {"rate": evaluate_rate(data)}


def cmd_arrhenius(data):
    raise NotImplementedError("Arrhenius parameter fitting not yet implemented")


def cmd_network(data):
    return solve_network(data)


def main():
    if len(sys.argv) != 4:
        print(
            "Usage: catreactor.py <subcommand> <input.json> <output.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    subcmd = sys.argv[1]
    with open(sys.argv[2]) as f:
        data = json.load(f)

    cmds = {"rate": cmd_rate, "arrhenius": cmd_arrhenius, "network": cmd_network}

    if subcmd not in cmds:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        sys.exit(1)

    result = cmds[subcmd](data)

    with open(sys.argv[3], "w") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
