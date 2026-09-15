
"""Halite III game state simulator."""

import json
import math
from collections import defaultdict


class GameState:
    """Complete Halite III game state simulator on a toroidal grid."""

    DIRECTIONS = {
        "north": (0, -1),
        "south": (0, 1),
        "east": (1, 0),
        "west": (-1, 0),
    }

    def __init__(self, width, height, halite_grid, players, constants):
        self.width = width
        self.height = height
        self.halite_grid = [row[:] for row in halite_grid]
        self.constants = dict(constants)
        self._players = {}
        self._next_ship_id = 0

        for p in players:
            pid = p["id"]
            ships = []
            for s in p.get("ships", []):
                ships.append({
                    "id": s["id"],
                    "x": s["x"],
                    "y": s["y"],
                    "halite": s["halite"],
                    "inspired": False,
                })
                if s["id"] >= self._next_ship_id:
                    self._next_ship_id = s["id"] + 1

            dropoffs = [dict(d) for d in p.get("dropoffs", [])]

            self._players[pid] = {
                "halite": p["halite"],
                "shipyard": dict(p["shipyard"]),
                "ships": ships,
                "dropoffs": dropoffs,
            }

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_scenario(cls, path):
        with open(path) as f:
            data = json.load(f)
        return cls(
            data["width"], data["height"], data["halite_grid"],
            data["players"], data["constants"],
        )

    def _copy(self):
        new = GameState.__new__(GameState)
        new.width = self.width
        new.height = self.height
        new.halite_grid = [row[:] for row in self.halite_grid]
        new.constants = dict(self.constants)
        new._next_ship_id = self._next_ship_id
        new._players = {}
        for pid, p in self._players.items():
            new._players[pid] = {
                "halite": p["halite"],
                "shipyard": dict(p["shipyard"]),
                "ships": [dict(s) for s in p["ships"]],
                "dropoffs": [dict(d) for d in p["dropoffs"]],
            }
        return new

    # ------------------------------------------------------------------
    # Position utilities
    # ------------------------------------------------------------------

    def _normalize(self, x, y):
        return x % self.width, y % self.height

    def calculate_distance(self, x1, y1, x2, y2):
        dx = abs(x1 - x2)
        dy = abs(y1 - y2)
        return min(dx, self.width - dx) + min(dy, self.height - dy)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_cell_halite(self, x, y):
        x, y = self._normalize(x, y)
        return self.halite_grid[y][x]

    def get_player_halite(self, player_id):
        return self._players[player_id]["halite"]

    def get_ships(self, player_id):
        return [
            {"id": s["id"], "x": s["x"], "y": s["y"], "halite": s["halite"]}
            for s in self._players[player_id]["ships"]
        ]

    def get_dropoffs(self, player_id):
        return list(self._players[player_id]["dropoffs"])

    def get_shipyard(self, player_id):
        return dict(self._players[player_id]["shipyard"])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_ship(self, player_id, ship_id):
        for s in self._players[player_id]["ships"]:
            if s["id"] == ship_id:
                return s
        return None

    def _is_friendly_structure(self, player_id, x, y):
        p = self._players[player_id]
        sy = p["shipyard"]
        if x == sy["x"] and y == sy["y"]:
            return True
        for d in p["dropoffs"]:
            if d["x"] == x and d["y"] == y:
                return True
        return False

    # ------------------------------------------------------------------
    # Turn phases
    # ------------------------------------------------------------------

    def _update_inspiration(self):
        enabled = self.constants.get("INSPIRATION_ENABLED", False)
        if not enabled:
            for pid in self._players:
                for s in self._players[pid]["ships"]:
                    s["inspired"] = False
            return

        radius = self.constants["INSPIRATION_RADIUS"]
        threshold = self.constants["INSPIRATION_SHIP_COUNT"]

        for pid in self._players:
            for ship in self._players[pid]["ships"]:
                count = 0
                for other_pid in self._players:
                    if other_pid == pid:
                        continue
                    for other_ship in self._players[other_pid]["ships"]:
                        d = self.calculate_distance(
                            ship["x"], ship["y"],
                            other_ship["x"], other_ship["y"],
                        )
                        if d <= radius:
                            count += 1
                ship["inspired"] = count >= threshold

    def _process_spawn(self, commands):
        for pid, cmds in commands.items():
            for cmd in cmds:
                if cmd.get("type") != "spawn":
                    continue
                p = self._players[pid]
                if p["halite"] < self.constants["SHIP_COST"]:
                    continue
                sx, sy = p["shipyard"]["x"], p["shipyard"]["y"]
                occupied = any(
                    s["x"] == sx and s["y"] == sy
                    for opid in self._players
                    for s in self._players[opid]["ships"]
                )
                if occupied:
                    continue
                p["halite"] -= self.constants["SHIP_COST"]
                p["ships"].append({
                    "id": self._next_ship_id,
                    "x": sx, "y": sy,
                    "halite": 0,
                    "inspired": False,
                })
                self._next_ship_id += 1

    def _process_moves_and_construct(self, commands):
        moved = set()
        for pid, cmds in commands.items():
            for cmd in cmds:
                if cmd.get("type") == "move":
                    ship = self._find_ship(pid, cmd["ship_id"])
                    if ship is None:
                        continue
                    dx, dy = self.DIRECTIONS[cmd["direction"]]
                    cell_h = self.halite_grid[ship["y"]][ship["x"]]
                    if ship["inspired"]:
                        ratio = self.constants["INSPIRED_MOVE_COST_RATIO"]
                    else:
                        ratio = self.constants["MOVE_COST_RATIO"]
                    cost = math.ceil(cell_h / ratio) if cell_h > 0 else 0
                    if ship["halite"] >= cost:
                        ship["halite"] -= cost
                        nx, ny = self._normalize(ship["x"] + dx, ship["y"] + dy)
                        ship["x"], ship["y"] = nx, ny
                        moved.add((pid, cmd["ship_id"]))

                elif cmd.get("type") == "construct":
                    ship = self._find_ship(pid, cmd["ship_id"])
                    if ship is None:
                        continue
                    p = self._players[pid]
                    cell_h = self.halite_grid[ship["y"]][ship["x"]]
                    p["halite"] += ship["halite"] + cell_h
                    p["halite"] -= self.constants["DROPOFF_COST"]
                    p["dropoffs"].append({
                        "id": ship["id"], "x": ship["x"], "y": ship["y"],
                    })
                    self.halite_grid[ship["y"]][ship["x"]] = 0
                    p["ships"] = [s for s in p["ships"] if s["id"] != ship["id"]]
                    moved.add((pid, cmd["ship_id"]))

        return moved

    def _resolve_collisions(self):
        pos_ships = defaultdict(list)
        for pid in self._players:
            for s in self._players[pid]["ships"]:
                pos_ships[(s["x"], s["y"])].append((pid, s))

        for (x, y), ships_at in pos_ships.items():
            if len(ships_at) <= 1:
                continue
            total_cargo = sum(s["halite"] for _, s in ships_at)
            self.halite_grid[y][x] += total_cargo
            for pid, ship in ships_at:
                self._players[pid]["ships"] = [
                    s for s in self._players[pid]["ships"]
                    if s["id"] != ship["id"]
                ]

    def _mine(self, moved):
        max_h = self.constants["MAX_HALITE"]
        for pid in self._players:
            for ship in self._players[pid]["ships"]:
                if (pid, ship["id"]) in moved:
                    continue
                cell_h = self.halite_grid[ship["y"]][ship["x"]]
                if cell_h == 0:
                    continue

                if ship["inspired"]:
                    ratio = self.constants["INSPIRED_EXTRACT_RATIO"]
                else:
                    ratio = self.constants["EXTRACT_RATIO"]

                base = math.ceil(cell_h / ratio)
                capped = min(base, max_h - ship["halite"])
                ship["halite"] += capped
                self.halite_grid[ship["y"]][ship["x"]] -= capped

                if ship["inspired"]:
                    bonus = self.constants["INSPIRED_BONUS_MULTIPLIER"] * capped
                    capped_bonus = min(bonus, max_h - ship["halite"])
                    ship["halite"] += capped_bonus

    def _deposit(self):
        for pid in self._players:
            p = self._players[pid]
            for ship in p["ships"]:
                if self._is_friendly_structure(pid, ship["x"], ship["y"]):
                    p["halite"] += ship["halite"]
                    ship["halite"] = 0

    # ------------------------------------------------------------------
    # Main step
    # ------------------------------------------------------------------

    def step(self, commands):
        new = self._copy()

        # 1. Inspiration
        new._update_inspiration()

        # 2. Spawn
        new._process_spawn(commands)

        # 3. Move / Construct
        moved = new._process_moves_and_construct(commands)

        # 4. Collisions
        new._resolve_collisions()

        # 5. Mining
        new._mine(moved)

        # 6. Deposit
        new._deposit()

        return new
