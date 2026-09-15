#!/usr/bin/env python3
"""
Arena Game Engine - A parameterized tactical deployment game simulator.

Game Mechanics:
  Two strategies compete across 3 lanes. Each strategy deploys warriors,
  mages, and archers. Units are randomly allocated to lanes based on the
  strategy's lane weight parameters (with Gaussian noise). Each lane is
  resolved independently using a type-matchup table:
    Warriors beat Archers, Archers beat Mages, Mages beat Warriors.
  The match winner takes 2 out of 3 lanes.

Usage:
  python3 engine.py list [--config PATH]
  python3 engine.py simulate --s1 NAME --s2 NAME [--games N] [--seed S] [--config PATH]

"""

import json
import random
import sys
import argparse


def load_config(path="/app/config.json"):
    """Load game configuration from a JSON file."""
    with open(path) as f:
        return json.load(f)


def allocate_units(strategy, rng):
    """
    Allocate a strategy's units across 3 lanes.

    Lane weights are perturbed with Gaussian noise, then each unit is
    independently assigned to a lane via the resulting multinomial distribution.

    Returns: dict mapping unit type -> [lane0_count, lane1_count, lane2_count]
    """
    weights = list(strategy["lane_weights"])
    noise = strategy.get("noise", 0.0)

    # Perturb weights
    noisy = [max(0.01, w + rng.gauss(0, noise)) for w in weights]
    total = sum(noisy)
    noisy = [w / total for w in noisy]

    allocation = {}
    for utype in ("warriors", "mages", "archers"):
        count = strategy[utype]
        lanes = [0, 0, 0]
        for _ in range(count):
            r = rng.random()
            cumsum = 0.0
            for idx in range(3):
                cumsum += noisy[idx]
                if r <= cumsum:
                    lanes[idx] += 1
                    break
            else:
                lanes[2] += 1
        allocation[utype] = lanes
    return allocation


def compute_lane_strength(own, opp, matchup_table):
    """
    Compute effective strength of *own* units against *opp* in one lane.

    Each own unit's effectiveness is the weighted average of matchup
    multipliers, weighted by the opponent's composition fractions.
    Total strength = sum(count_i * effectiveness_i).
    """
    opp_total = sum(opp.values())
    if opp_total == 0:
        return float(sum(own.values()))

    strength = 0.0
    for own_type, own_count in own.items():
        if own_count == 0:
            continue
        eff = 0.0
        for opp_type, opp_count in opp.items():
            frac = opp_count / opp_total
            key = f"{own_type}_vs_{opp_type}"
            mult = matchup_table.get(key, 1.0)
            eff += frac * mult
        strength += own_count * eff
    return strength


def simulate_match(strat1, strat2, matchup_table, seed):
    """
    Simulate one match.  Returns +1 (strat1 wins), -1 (strat2), or 0 (draw).
    """
    rng = random.Random(seed)
    alloc1 = allocate_units(strat1, rng)
    alloc2 = allocate_units(strat2, rng)

    w1, w2 = 0, 0
    for lane in range(3):
        c1 = {t: alloc1[t][lane] for t in ("warriors", "mages", "archers")}
        c2 = {t: alloc2[t][lane] for t in ("warriors", "mages", "archers")}
        s1 = compute_lane_strength(c1, c2, matchup_table)
        s2 = compute_lane_strength(c2, c1, matchup_table)
        if s1 > s2:
            w1 += 1
        elif s2 > s1:
            w2 += 1

    if w1 > w2:
        return 1
    if w2 > w1:
        return -1
    return 0


def run_matchup(s1_name, s2_name, config, num_games=1000, base_seed=0):
    """Run *num_games* matches between two named strategies."""
    strat1 = config["strategies"][s1_name]
    strat2 = config["strategies"][s2_name]
    mt = config["matchup_table"]

    wins1, wins2, draws = 0, 0, 0
    for i in range(num_games):
        r = simulate_match(strat1, strat2, mt, base_seed * 100000 + i)
        if r > 0:
            wins1 += 1
        elif r < 0:
            wins2 += 1
        else:
            draws += 1

    return {
        "strategy_1": s1_name,
        "strategy_2": s2_name,
        "games": num_games,
        "wins_1": wins1,
        "wins_2": wins2,
        "draws": draws,
        "win_rate_1": wins1 / num_games if num_games > 0 else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description="Arena Game Engine")
    sub = parser.add_subparsers(dest="command")

    lp = sub.add_parser("list", help="List available strategies")
    lp.add_argument("--config", default="/app/config.json")

    sp = sub.add_parser("simulate", help="Simulate matches")
    sp.add_argument("--s1", required=True, help="Strategy 1 name")
    sp.add_argument("--s2", required=True, help="Strategy 2 name")
    sp.add_argument("--games", type=int, default=1000)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--config", default="/app/config.json")

    args = parser.parse_args()

    if args.command == "list":
        cfg = load_config(args.config)
        print(json.dumps(sorted(cfg["strategies"].keys())))
    elif args.command == "simulate":
        cfg = load_config(args.config)
        res = run_matchup(args.s1, args.s2, cfg, args.games, args.seed)
        print(json.dumps(res))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
