#!/usr/bin/env python3
"""
woa-sim: War of Attrition — Tournament Simulator

CLI tool for simulating parameterized two-player strategy games across
multiple AI strategies. Supports TOML configuration, JSON/CSV/SQLite output.

Run with --help for usage, --param-ranges for parameter specs,
--list-strategies for AI strategy descriptions.
"""

import argparse
import json
import math
import os
import random
import sqlite3
import sys

try:
    import tomllib
except ImportError:
    sys.exit("Error: Python 3.11+ required for tomllib")

MAX_TURNS = 100
ATTACK, DEFEND, CHARGE, CAST = 0, 1, 2, 3
ACTION_NAMES = {0: "attack", 1: "defend", 2: "charge", 3: "cast"}

PARAM_SPEC = {
    "base_hp":       {"min": 20, "max": 100},
    "base_mana":     {"min": 3,  "max": 25},
    "attack_damage": {"min": 2,  "max": 15},
    "defend_block":  {"min": 1,  "max": 10},
    "charge_gain":   {"min": 1,  "max": 8},
    "spell_damage":  {"min": 5,  "max": 25},
    "spell_cost":    {"min": 3,  "max": 20},
    "mana_regen":    {"min": 0,  "max": 5},
}

STRATEGIES = ["heuristic", "aggressive", "defensive"]

ALL_MATCHUPS = [
    "heuristic-vs-heuristic",
    "heuristic-vs-aggressive",
    "heuristic-vs-defensive",
    "aggressive-vs-aggressive",
    "aggressive-vs-defensive",
    "defensive-vs-defensive",
]


def validate_params(params):
    for key, spec in PARAM_SPEC.items():
        if key not in params:
            return False, f"Missing parameter: {key}"
        v = params[key]
        if not isinstance(v, int):
            return False, f"{key} must be int, got {type(v).__name__}"
        if v < spec["min"] or v > spec["max"]:
            return False, f"{key}={v} outside [{spec['min']}, {spec['max']}]"
    return True, "ok"


class PlayerState:
    __slots__ = ["hp", "mana", "shield", "consec_atk"]

    def __init__(self, hp, mana):
        self.hp = hp
        self.mana = mana
        self.shield = 0
        self.consec_atk = 0


class Game:
    def __init__(self, params):
        self.p = params
        self.players = [
            PlayerState(params["base_hp"], params["base_mana"]),
            PlayerState(params["base_hp"], params["base_mana"]),
        ]
        self.turn = 0
        self.ply = 0
        self.current = 0
        self.history = []
        self.done = False
        self.winner = None

    def legal_actions(self):
        me = self.players[self.current]
        acts = [ATTACK, DEFEND, CHARGE]
        if me.mana >= self.p["spell_cost"]:
            acts.append(CAST)
        return acts

    def step(self, action):
        if self.done:
            return
        me = self.players[self.current]
        opp = self.players[1 - self.current]
        me.shield = max(0, me.shield - 1)

        if action == ATTACK:
            raw = self.p["attack_damage"]
            me.consec_atk += 1
            if me.consec_atk >= 3:
                raw = int(raw * 1.25)
            blocked = min(raw, opp.shield)
            damage = max(1, raw - blocked)
            if me.hp <= self.p["base_hp"] * 0.25:
                damage = int(damage * 1.5)
            opp.hp -= damage
            opp.shield = max(0, opp.shield - raw)
        elif action == DEFEND:
            me.consec_atk = 0
            gain = self.p["defend_block"]
            if self.turn > 50:
                factor = max(0.3, 1.0 - (self.turn - 50) * 0.014)
                gain = max(1, int(gain * factor))
            cap = self.p["defend_block"] * 2
            me.shield = min(me.shield + gain, cap)
        elif action == CHARGE:
            me.consec_atk = 0
            me.mana += self.p["charge_gain"]
        elif action == CAST:
            me.consec_atk = 0
            me.mana -= self.p["spell_cost"]
            base_dmg = self.p["spell_damage"]
            if me.mana > 0:
                ratio = me.mana / self.p["spell_cost"]
                base_dmg += int(self.p["spell_damage"] * 0.1 * ratio)
            eff_shield = opp.shield // 2
            damage = max(1, base_dmg - eff_shield)
            opp.hp -= damage
            opp.shield = max(0, opp.shield - base_dmg // 3)

        me.mana += self.p["mana_regen"]
        self.history.append((self.current, action))

        if opp.hp <= 0:
            self.done = True
            self.winner = self.current
            return

        self.ply += 1
        if self.current == 1:
            self.turn += 1
        self.current = 1 - self.current

        # Attrition: after turn 50, symmetric HP drain each full turn
        if self.current == 0 and self.turn > 50:
            drain = 1 + (self.turn - 50) // 10
            self.players[0].hp -= drain
            self.players[1].hp -= drain
            for idx in [0, 1]:
                self.players[idx].hp = max(0, self.players[idx].hp)
            if self.players[0].hp <= 0 or self.players[1].hp <= 0:
                self.done = True
                if self.players[0].hp > self.players[1].hp:
                    self.winner = 0
                elif self.players[1].hp > self.players[0].hp:
                    self.winner = 1
                else:
                    self.winner = None
                return

        if self.turn >= MAX_TURNS:
            self.done = True
            if self.players[0].hp > self.players[1].hp:
                self.winner = 0
            elif self.players[1].hp > self.players[0].hp:
                self.winner = 1
            else:
                self.winner = None


# ── AI Strategies ──────────────────────────────────────────────────────

def heuristic_player(game, rng):
    acts = game.legal_actions()
    me = game.players[game.current]
    opp = game.players[1 - game.current]
    p = game.p
    if CAST in acts:
        eff = opp.shield // 2
        if max(1, p["spell_damage"] - eff) >= opp.hp:
            return CAST
    raw = p["attack_damage"]
    blocked = min(raw, opp.shield)
    admg = max(1, raw - blocked)
    if admg >= opp.hp:
        return ATTACK
    if me.hp < p["base_hp"] * 0.35 and me.shield < p["defend_block"]:
        if rng.random() < 0.6:
            return DEFEND
    if CAST in acts and me.mana >= p["spell_cost"] * 1.3:
        eff = opp.shield // 2
        if max(1, p["spell_damage"] - eff) > admg:
            return CAST
    if me.mana < p["spell_cost"] and p["spell_damage"] > p["attack_damage"]:
        if rng.random() < 0.45:
            return CHARGE
    if me.shield == 0 and p["attack_damage"] > p["base_hp"] * 0.08:
        if rng.random() < 0.25:
            return DEFEND
    return ATTACK


def aggressive_player(game, rng):
    acts = game.legal_actions()
    me = game.players[game.current]
    opp = game.players[1 - game.current]
    p = game.p
    if CAST in acts:
        eff = opp.shield // 2
        if max(1, p["spell_damage"] - eff) >= opp.hp:
            return CAST
    raw = p["attack_damage"]
    blocked = min(raw, opp.shield)
    if max(1, raw - blocked) >= opp.hp:
        return ATTACK
    if CAST in acts and p["spell_damage"] >= p["attack_damage"]:
        return CAST
    if me.mana < p["spell_cost"] and p["spell_damage"] >= p["attack_damage"] * 2:
        if rng.random() < 0.3:
            return CHARGE
    return ATTACK


def defensive_player(game, rng):
    acts = game.legal_actions()
    me = game.players[game.current]
    opp = game.players[1 - game.current]
    p = game.p
    if CAST in acts:
        eff = opp.shield // 2
        if max(1, p["spell_damage"] - eff) >= opp.hp:
            return CAST
    raw = p["attack_damage"]
    blocked = min(raw, opp.shield)
    if max(1, raw - blocked) >= opp.hp:
        return ATTACK
    if me.hp < p["base_hp"] * 0.5 and me.shield < p["defend_block"]:
        if rng.random() < 0.65:
            return DEFEND
    if me.shield == 0:
        if rng.random() < 0.4:
            return DEFEND
    if CAST in acts and me.mana >= p["spell_cost"] * 1.5:
        if opp.shield == 0 or p["spell_damage"] > opp.shield:
            if rng.random() < 0.7:
                return CAST
    if me.mana < p["spell_cost"] * 1.5:
        if rng.random() < 0.5:
            return CHARGE
    if opp.hp < p["base_hp"] * 0.3:
        return ATTACK
    if rng.random() < 0.55:
        return DEFEND
    return ATTACK


AI_REGISTRY = {
    "heuristic": heuristic_player,
    "aggressive": aggressive_player,
    "defensive": defensive_player,
}


# ── Simulation ─────────────────────────────────────────────────────────

def play_game(params, p1_fn, p2_fn, seed):
    rng = random.Random(seed)
    game = Game(params)
    fns = [p1_fn, p2_fn]
    while not game.done:
        action = fns[game.current](game, rng)
        if action not in game.legal_actions():
            action = game.legal_actions()[0]
        game.step(action)
    return {
        "winner": game.winner,
        "turns": game.turn,
        "history": game.history,
        "p1_hp": game.players[0].hp,
        "p2_hp": game.players[1].hp,
    }


def evaluate_matchup(params, p1_name, p2_name, n_games=200, base_seed=42):
    p1_fn = AI_REGISTRY[p1_name]
    p2_fn = AI_REGISTRY[p2_name]
    results = []
    for i in range(n_games):
        results.append(play_game(params, p1_fn, p2_fn, seed=base_seed + i))

    n = len(results)
    p1_wins = sum(1 for r in results if r["winner"] == 0)
    p2_wins = sum(1 for r in results if r["winner"] == 1)
    draws = sum(1 for r in results if r["winner"] is None)
    win_rate = p1_wins / n
    draw_rate = draws / n
    avg_turns = sum(r["turns"] for r in results) / n

    fairness = max(0.0, 1.0 - 2.0 * abs(win_rate - 0.5))
    decisiveness = 1.0 - draw_rate

    if 30 <= avg_turns <= 70:
        depth = 1.0
    elif avg_turns < 30:
        depth = max(0.0, avg_turns / 30.0)
    else:
        depth = max(0.0, 1.0 - (avg_turns - 70) / 30.0)

    action_counts = {}
    total_actions = 0
    for r in results:
        for _, a in r["history"]:
            action_counts[a] = action_counts.get(a, 0) + 1
            total_actions += 1

    if total_actions > 0:
        entropy = 0.0
        for cnt in action_counts.values():
            p_val = cnt / total_actions
            if p_val > 0:
                entropy -= p_val * math.log2(p_val)
        variety = entropy / math.log2(4)
    else:
        variety = 0.0

    composite = 0.35 * fairness + 0.25 * decisiveness + 0.25 * depth + 0.15 * variety

    metrics = {
        "matchup": f"{p1_name}-vs-{p2_name}",
        "n_games": n,
        "p1_wins": p1_wins,
        "p2_wins": p2_wins,
        "draws": draws,
        "win_rate": round(win_rate, 6),
        "draw_rate": round(draw_rate, 6),
        "avg_turns": round(avg_turns, 4),
        "fairness": round(fairness, 6),
        "decisiveness": round(decisiveness, 6),
        "depth": round(depth, 6),
        "variety": round(variety, 6),
        "composite": round(composite, 6),
    }
    return metrics, results


# ── Output ─────────────────────────────────────────────────────────────

EMBEDDED_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    matchup TEXT NOT NULL,
    game_num INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    winner INTEGER,
    turns INTEGER NOT NULL,
    p1_final_hp INTEGER NOT NULL,
    p2_final_hp INTEGER NOT NULL,
    action_sequence TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS matchup_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    matchup TEXT NOT NULL,
    n_games INTEGER NOT NULL,
    p1_wins INTEGER NOT NULL,
    p2_wins INTEGER NOT NULL,
    draws INTEGER NOT NULL,
    avg_turns REAL NOT NULL,
    fairness REAL NOT NULL,
    decisiveness REAL NOT NULL,
    depth REAL NOT NULL,
    variety REAL NOT NULL,
    composite REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS parameter_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    params_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def write_sqlite(metrics, game_results, matchup, db_path, run_id, params, base_seed):
    conn = sqlite3.connect(db_path)
    schema_path = "/app/schema.sql"
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            conn.executescript(f.read())
    else:
        conn.executescript(EMBEDDED_SCHEMA)

    for i, r in enumerate(game_results):
        acts = ",".join(f"{p}:{a}" for p, a in r["history"])
        conn.execute(
            "INSERT INTO game_results (run_id,matchup,game_num,seed,winner,turns,p1_final_hp,p2_final_hp,action_sequence) VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, matchup, i, base_seed + i, r["winner"], r["turns"], r["p1_hp"], r["p2_hp"], acts),
        )

    conn.execute(
        "INSERT INTO matchup_summary (run_id,matchup,n_games,p1_wins,p2_wins,draws,avg_turns,fairness,decisiveness,depth,variety,composite) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, matchup, metrics["n_games"], metrics["p1_wins"], metrics["p2_wins"],
         metrics["draws"], metrics["avg_turns"], metrics["fairness"], metrics["decisiveness"],
         metrics["depth"], metrics["variety"], metrics["composite"]),
    )

    existing = conn.execute("SELECT COUNT(*) FROM parameter_configs WHERE run_id=?", (run_id,)).fetchone()[0]
    if existing == 0:
        conn.execute("INSERT INTO parameter_configs (run_id,params_json) VALUES (?,?)",
                     (run_id, json.dumps(params)))
    conn.commit()
    conn.close()


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="woa-sim",
        description="War of Attrition — Tournament Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  woa-sim --config game.toml --matchup heuristic-vs-aggressive --games 200\n"
               "  woa-sim --params '{\"base_hp\":80,...}' --all-matchups --output sqlite --db t.db\n"
               "  woa-sim --param-ranges\n"
               "  woa-sim --list-strategies\n",
    )
    parser.add_argument("--config", help="TOML config file with [parameters] section")
    parser.add_argument("--params", help="Inline JSON parameter object")
    parser.add_argument("--games", type=int, default=100, help="Games per matchup (default: 100)")
    parser.add_argument("--seed", type=int, default=42, help="Base random seed (default: 42)")
    parser.add_argument("--matchup", help="Strategy matchup, e.g. heuristic-vs-aggressive")
    parser.add_argument("--all-matchups", action="store_true", help="Run all 6 strategy matchups")
    parser.add_argument("--output", choices=["json", "csv", "sqlite"], default="json",
                        help="Output format (default: json)")
    parser.add_argument("--db", help="SQLite database path (required for --output sqlite)")
    parser.add_argument("--run-id", default="default", help="Run identifier for DB grouping")
    parser.add_argument("--param-ranges", action="store_true", help="Print parameter specifications")
    parser.add_argument("--list-strategies", action="store_true", help="List AI strategies")

    args = parser.parse_args()

    if args.param_ranges:
        print(json.dumps(PARAM_SPEC, indent=2))
        return

    if args.list_strategies:
        print("Available AI strategies:")
        print("  heuristic   - Balanced: adapts to situation, mixes all four actions")
        print("  aggressive  - Offense-focused: maximizes damage, rarely defends or charges")
        print("  defensive   - Survival-focused: shields frequently, attacks cautiously")
        print(f"\nMatchup format: strategy1-vs-strategy2")
        print(f"All matchups: {', '.join(ALL_MATCHUPS)}")
        return

    # Load parameters
    params = None
    if args.config:
        with open(args.config, "rb") as f:
            cfg = tomllib.load(f)
        if "parameters" not in cfg:
            print("Error: TOML config must have a [parameters] section", file=sys.stderr)
            sys.exit(1)
        params = {k: int(v) for k, v in cfg["parameters"].items()}
    elif args.params:
        params = {k: int(v) for k, v in json.loads(args.params).items()}
    else:
        parser.error("Either --config or --params is required")

    ok, msg = validate_params(params)
    if not ok:
        print(f"Invalid parameters: {msg}", file=sys.stderr)
        sys.exit(1)

    if args.output == "sqlite" and not args.db:
        parser.error("--db is required when using --output sqlite")

    # Determine matchups to run
    if args.all_matchups:
        matchups = list(ALL_MATCHUPS)
    elif args.matchup:
        parts = args.matchup.split("-vs-")
        if len(parts) != 2 or parts[0] not in STRATEGIES or parts[1] not in STRATEGIES:
            parser.error(f"Invalid matchup '{args.matchup}'. Format: strategy1-vs-strategy2")
        matchups = [args.matchup]
    else:
        parser.error("Either --matchup or --all-matchups is required")

    # Run simulations
    all_metrics = {}
    for mu in matchups:
        p1, p2 = mu.split("-vs-")
        metrics, game_results = evaluate_matchup(params, p1, p2, args.games, args.seed)
        all_metrics[mu] = metrics

        if args.output == "sqlite":
            write_sqlite(metrics, game_results, mu, args.db, args.run_id, params, args.seed)
        elif args.output == "csv":
            if mu == matchups[0]:
                sys.stdout.write("game,matchup,winner,turns,p1_hp,p2_hp\n")
            for i, r in enumerate(game_results):
                w = r["winner"] if r["winner"] is not None else "draw"
                sys.stdout.write(f"{i},{mu},{w},{r['turns']},{r['p1_hp']},{r['p2_hp']}\n")

    # Final output
    if args.output == "json":
        if len(matchups) == 1:
            mu = matchups[0]
            out = {"metrics": all_metrics[mu], "games": [
                {"game": i, "winner": r["winner"], "turns": r["turns"],
                 "p1_hp": r["p1_hp"], "p2_hp": r["p2_hp"]}
                for i, r in enumerate(game_results)
            ]}
        else:
            out = {"matchups": all_metrics}
        json.dump(out, sys.stdout, indent=2)
        print()
    elif args.output == "sqlite":
        json.dump({"matchups": all_metrics}, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
