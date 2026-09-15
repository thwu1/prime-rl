"""
War of Attrition: A parameterized two-player turn-based strategy game.

Two players alternate turns choosing actions in a resource-management duel.
The game has 8 tunable integer parameters that affect combat, defense,
and resource mechanics.

Actions:
  ATTACK  - Deal attack_damage to opponent (reduced by their shield)
  DEFEND  - Gain defend_block shield points (caps at 2x defend_block)
  CHARGE  - Gain charge_gain mana
  CAST    - Spend spell_cost mana to deal spell_damage (partially bypasses shield)

Shield decays by 1 at the start of each of your turns. Attacks consume shield
on the target; spells bypass half the shield value and consume a third.

Game ends when a player's HP reaches 0 (that player loses) or after MAX_TURNS
full rounds (player with higher HP wins; tied HP is a draw).
"""


import random
import math
import json
from enum import IntEnum
from typing import List, Optional

MAX_TURNS = 100


class Action(IntEnum):
    ATTACK = 0
    DEFEND = 1
    CHARGE = 2
    CAST = 3


PARAM_SPEC = {
    "base_hp":       {"min": 20, "max": 100, "type": "int"},
    "base_mana":     {"min": 3,  "max": 25,  "type": "int"},
    "attack_damage": {"min": 2,  "max": 15,  "type": "int"},
    "defend_block":  {"min": 1,  "max": 10,  "type": "int"},
    "charge_gain":   {"min": 1,  "max": 8,   "type": "int"},
    "spell_damage":  {"min": 5,  "max": 25,  "type": "int"},
    "spell_cost":    {"min": 3,  "max": 20,  "type": "int"},
    "mana_regen":    {"min": 0,  "max": 5,   "type": "int"},
}


class PlayerState:
    __slots__ = ["hp", "mana", "shield"]

    def __init__(self, hp: int, mana: int, shield: int = 0):
        self.hp = hp
        self.mana = mana
        self.shield = shield


class Game:
    def __init__(self, params: dict):
        self.p = params
        self.players = [
            PlayerState(hp=params["base_hp"], mana=params["base_mana"]),
            PlayerState(hp=params["base_hp"], mana=params["base_mana"]),
        ]
        self.turn = 0
        self.ply = 0
        self.current = 0
        self.history: List[tuple] = []
        self.done = False
        self.winner: Optional[int] = None

    def legal_actions(self) -> List[Action]:
        me = self.players[self.current]
        acts = [Action.ATTACK, Action.DEFEND, Action.CHARGE]
        if me.mana >= self.p["spell_cost"]:
            acts.append(Action.CAST)
        return acts

    def step(self, action: Action):
        if self.done:
            return
        me = self.players[self.current]
        opp = self.players[1 - self.current]

        # Shield decay at the start of your action
        me.shield = max(0, me.shield - 1)

        if action == Action.ATTACK:
            raw = self.p["attack_damage"]
            blocked = min(raw, opp.shield)
            damage = max(1, raw - blocked)
            opp.hp -= damage
            opp.shield = max(0, opp.shield - raw)

        elif action == Action.DEFEND:
            cap = self.p["defend_block"] * 2
            me.shield = min(me.shield + self.p["defend_block"], cap)

        elif action == Action.CHARGE:
            me.mana += self.p["charge_gain"]

        elif action == Action.CAST:
            me.mana -= self.p["spell_cost"]
            eff_shield = opp.shield // 2
            damage = max(1, self.p["spell_damage"] - eff_shield)
            opp.hp -= damage
            opp.shield = max(0, opp.shield - self.p["spell_damage"] // 3)

        # Passive mana regeneration
        me.mana += self.p["mana_regen"]

        self.history.append((self.current, int(action)))

        if opp.hp <= 0:
            self.done = True
            self.winner = self.current
            return

        self.ply += 1
        if self.current == 1:
            self.turn += 1
        self.current = 1 - self.current

        if self.turn >= MAX_TURNS:
            self.done = True
            if self.players[0].hp > self.players[1].hp:
                self.winner = 0
            elif self.players[1].hp > self.players[0].hp:
                self.winner = 1
            else:
                self.winner = None

    def clone(self):
        g = Game.__new__(Game)
        g.p = self.p
        g.players = [PlayerState(s.hp, s.mana, s.shield) for s in self.players]
        g.turn = self.turn
        g.ply = self.ply
        g.current = self.current
        g.history = list(self.history)
        g.done = self.done
        g.winner = self.winner
        return g


def heuristic_player(game: Game, rng: random.Random) -> Action:
    """Simple heuristic AI used for balance evaluation."""
    actions = game.legal_actions()
    me = game.players[game.current]
    opp = game.players[1 - game.current]
    p = game.p

    # Lethal check: cast for kill
    if Action.CAST in actions:
        eff = opp.shield // 2
        sdmg = max(1, p["spell_damage"] - eff)
        if sdmg >= opp.hp:
            return Action.CAST

    # Lethal check: attack for kill
    raw = p["attack_damage"]
    blocked = min(raw, opp.shield)
    admg = max(1, raw - blocked)
    if admg >= opp.hp:
        return Action.ATTACK

    # Low HP: defend
    hp_frac = me.hp / p["base_hp"]
    if hp_frac < 0.35 and me.shield < p["defend_block"]:
        if rng.random() < 0.6:
            return Action.DEFEND

    # Cast if mana is plentiful and spell outdamages attack
    if Action.CAST in actions and me.mana >= p["spell_cost"] * 1.3:
        eff = opp.shield // 2
        sdmg = max(1, p["spell_damage"] - eff)
        if sdmg > admg:
            return Action.CAST

    # Charge if low on mana and spells are strong
    if me.mana < p["spell_cost"] and p["spell_damage"] > p["attack_damage"]:
        if rng.random() < 0.45:
            return Action.CHARGE

    # Occasional defensive play
    if me.shield == 0 and p["attack_damage"] > p["base_hp"] * 0.08:
        if rng.random() < 0.25:
            return Action.DEFEND

    return Action.ATTACK


def random_player(game: Game, rng: random.Random) -> Action:
    """Uniformly random legal action selection."""
    return rng.choice(game.legal_actions())


def play_game(params: dict, p1_fn, p2_fn, seed: int) -> dict:
    """Play a single game and return outcome data."""
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
        "final_hp": [game.players[0].hp, game.players[1].hp],
    }


def evaluate_balance(params: dict, n_games: int = 200, base_seed: int = 42) -> dict:
    """Evaluate balance metrics by simulating heuristic-vs-heuristic matches."""
    results = []
    for i in range(n_games):
        r = play_game(params, heuristic_player, heuristic_player, seed=base_seed + i)
        results.append(r)

    n = len(results)
    p1_wins = sum(1 for r in results if r["winner"] == 0)
    draws = sum(1 for r in results if r["winner"] is None)
    win_rate = p1_wins / n
    draw_rate = draws / n
    avg_turns = sum(r["turns"] for r in results) / n

    # Fairness: win rate closeness to 50%
    fairness = max(0.0, 1.0 - 2.0 * abs(win_rate - 0.5))

    # Decisiveness: proportion of non-draw games
    decisiveness = 1.0 - draw_rate

    # Depth: average game length in target range [35, 70]
    if 35 <= avg_turns <= 70:
        depth = 1.0
    elif avg_turns < 35:
        depth = max(0.0, avg_turns / 35.0)
    else:
        depth = max(0.0, 1.0 - (avg_turns - 70) / 30.0)

    # Variety: action entropy normalized by maximum
    action_counts: dict = {}
    total_actions = 0
    for r in results:
        for _, a in r["history"]:
            action_counts[a] = action_counts.get(a, 0) + 1
            total_actions += 1

    if total_actions > 0:
        entropy = 0.0
        for cnt in action_counts.values():
            p = cnt / total_actions
            if p > 0:
                entropy -= p * math.log2(p)
        variety = entropy / math.log2(4)
    else:
        variety = 0.0

    score = 0.40 * fairness + 0.25 * decisiveness + 0.20 * depth + 0.15 * variety

    return {
        "score": round(score, 6),
        "fairness": round(fairness, 6),
        "decisiveness": round(decisiveness, 6),
        "depth": round(depth, 6),
        "variety": round(variety, 6),
        "p1_win_rate": round(win_rate, 6),
        "draw_rate": round(draw_rate, 6),
        "avg_turns": round(avg_turns, 4),
    }


def validate_params(params: dict) -> bool:
    """Check all parameters are present, integer, and within valid ranges."""
    for key, spec in PARAM_SPEC.items():
        if key not in params:
            return False
        v = params[key]
        if not isinstance(v, int):
            return False
        if v < spec["min"] or v > spec["max"]:
            return False
    return True


if __name__ == "__main__":
    # Quick test with midpoint parameters
    mid = {k: (v["min"] + v["max"]) // 2 for k, v in PARAM_SPEC.items()}
    print("Midpoint parameters:", json.dumps(mid))
    result = evaluate_balance(mid, n_games=100)
    print("Balance evaluation:", json.dumps(result, indent=2))
