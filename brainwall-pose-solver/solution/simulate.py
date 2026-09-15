#!/usr/bin/env python3
"""
NMMS trace simulation engine — reads JSON-decoded model and trace data.

"""
import sys
import json


class SimError(Exception):
    pass


class Nanobot:
    __slots__ = ('bid', 'pos', 'seeds')

    def __init__(self, bid, pos, seeds):
        self.bid = bid
        self.pos = tuple(pos)
        self.seeds = sorted(seeds)


class Simulator:
    """Full NMMS trace simulator operating on JSON-decoded inputs."""

    def __init__(self, model_data, trace_data):
        self.R = model_data["resolution"]
        self.target = set(tuple(c) for c in model_data["filled"])
        self.commands = trace_data
        self.cmd_idx = 0
        self.energy = 0
        self.harmonics = 'Low'
        self.matrix = set()
        self.bots = [Nanobot(1, (0, 0, 0), list(range(2, 21)))]
        self.steps = 0
        self.halted = False

    def _next_cmd(self):
        if self.cmd_idx >= len(self.commands):
            raise SimError("Trace exhausted: not enough commands")
        cmd = self.commands[self.cmd_idx]
        self.cmd_idx += 1
        return cmd

    def _parse_cmd(self, cmd):
        name = cmd["cmd"]
        if name in ("Halt", "Wait", "Flip"):
            return (name,)
        if name == "SMove":
            return (name, tuple(cmd["lld"]))
        if name == "LMove":
            return (name, tuple(cmd["sld1"]), tuple(cmd["sld2"]))
        if name == "Fill":
            return (name, tuple(cmd["nd"]))
        if name == "FusionP":
            return (name, tuple(cmd["nd"]))
        if name == "FusionS":
            return (name, tuple(cmd["nd"]))
        if name == "Fission":
            return (name, tuple(cmd["nd"]), cmd["m"])
        raise SimError(f"Unknown command: {name}")

    def run(self):
        try:
            while self.bots and not self.halted:
                self._check_wellformed()
                self._execute_step()
                self.steps += 1
            return {
                "valid": True,
                "energy": self.energy,
                "steps": self.steps,
                "model_match": self.matrix == self.target,
                "error": None,
            }
        except SimError as e:
            return {
                "valid": False,
                "energy": self.energy,
                "steps": self.steps,
                "model_match": self.matrix == self.target,
                "error": str(e),
            }

    # ── well-formedness ─────────────────────────────────────────────

    def _check_wellformed(self):
        if self.harmonics == 'Low' and not self._all_grounded():
            raise SimError(
                "Well-formedness: not all Full voxels are grounded "
                "under Low harmonics"
            )
        bids = [b.bid for b in self.bots]
        if len(bids) != len(set(bids)):
            raise SimError("Well-formedness: duplicate bot identifiers")
        positions = [b.pos for b in self.bots]
        if len(positions) != len(set(positions)):
            raise SimError("Well-formedness: two bots at same position")
        for b in self.bots:
            if b.pos in self.matrix:
                raise SimError(
                    f"Well-formedness: bot {b.bid} at Full voxel {b.pos}"
                )
        all_seeds = set()
        active_bids = {b.bid for b in self.bots}
        for b in self.bots:
            for s in b.seeds:
                if s in all_seeds:
                    raise SimError("Well-formedness: overlapping seeds")
                if s in active_bids:
                    raise SimError(
                        "Well-formedness: seed matches active bot id"
                    )
                all_seeds.add(s)

    def _all_grounded(self):
        if not self.matrix:
            return True
        grounded = set()
        queue = []
        for c in self.matrix:
            if c[1] == 0:
                grounded.add(c)
                queue.append(c)
        idx = 0
        while idx < len(queue):
            cx, cy, cz = queue[idx]
            idx += 1
            for dx, dy, dz in (
                (1, 0, 0), (-1, 0, 0),
                (0, 1, 0), (0, -1, 0),
                (0, 0, 1), (0, 0, -1),
            ):
                nc = (cx + dx, cy + dy, cz + dz)
                if nc in self.matrix and nc not in grounded:
                    grounded.add(nc)
                    queue.append(nc)
        return len(grounded) == len(self.matrix)

    # ── helpers ─────────────────────────────────────────────────────

    def _valid_coord(self, c):
        return 0 <= c[0] < self.R and 0 <= c[1] < self.R and 0 <= c[2] < self.R

    @staticmethod
    def _add(c, d):
        return (c[0] + d[0], c[1] + d[1], c[2] + d[2])

    @staticmethod
    def _mlen(d):
        return abs(d[0]) + abs(d[1]) + abs(d[2])

    @staticmethod
    def _region(c1, c2):
        coords = set()
        for x in range(min(c1[0], c2[0]), max(c1[0], c2[0]) + 1):
            for y in range(min(c1[1], c2[1]), max(c1[1], c2[1]) + 1):
                for z in range(min(c1[2], c2[2]), max(c1[2], c2[2]) + 1):
                    coords.add((x, y, z))
        return coords

    # ── step execution ──────────────────────────────────────────────

    def _execute_step(self):
        n = len(self.bots)
        self.bots.sort(key=lambda b: b.bid)

        commands = []
        for _ in range(n):
            commands.append(self._parse_cmd(self._next_cmd()))

        # Identify fusion pairs
        fusion_partner = {}
        for i, cmd in enumerate(commands):
            if cmd[0] == 'FusionP':
                target = self._add(self.bots[i].pos, cmd[1])
                for j, cmd2 in enumerate(commands):
                    if j != i and cmd2[0] == 'FusionS':
                        if self.bots[j].pos == target:
                            back = self._add(self.bots[j].pos, cmd2[1])
                            if back == self.bots[i].pos:
                                fusion_partner[i] = j
                                fusion_partner[j] = i
                                break

        # Build groups
        used = set()
        groups = []
        for i in range(n):
            if i in used:
                continue
            if i in fusion_partner:
                j = fusion_partner[i]
                if commands[i][0] == 'FusionP':
                    groups.append([(i, commands[i]), (j, commands[j])])
                else:
                    groups.append([(j, commands[j]), (i, commands[i])])
                used.add(i)
                used.add(j)
            else:
                groups.append([(i, commands[i])])
                used.add(i)

        # Preconditions + volatile coordinates per group
        group_volatiles = []
        for group in groups:
            volatiles = set()
            for bot_idx, cmd in group:
                bot = self.bots[bot_idx]
                volatiles.add(bot.pos)
                self._check_precondition(bot, cmd, volatiles)
            group_volatiles.append(volatiles)

        # Interference check
        for i in range(len(group_volatiles)):
            for j in range(i + 1, len(group_volatiles)):
                overlap = group_volatiles[i] & group_volatiles[j]
                if overlap:
                    raise SimError(
                        f"Interference between groups at {overlap}"
                    )

        # Maintenance energy
        if self.harmonics == 'High':
            self.energy += 30 * self.R ** 3
        else:
            self.energy += 3 * self.R ** 3
        self.energy += 20 * n

        # Apply effects
        remove_indices = set()
        add_bots = []

        for group in groups:
            for bot_idx, cmd in group:
                bot = self.bots[bot_idx]
                name = cmd[0]

                if name == 'Halt':
                    self.halted = True
                    remove_indices.add(bot_idx)

                elif name == 'Wait':
                    pass

                elif name == 'Flip':
                    self.harmonics = (
                        'Low' if self.harmonics == 'High' else 'High'
                    )

                elif name == 'SMove':
                    lld = cmd[1]
                    bot.pos = self._add(bot.pos, lld)
                    self.energy += 2 * self._mlen(lld)

                elif name == 'LMove':
                    sld1, sld2 = cmd[1], cmd[2]
                    bot.pos = self._add(self._add(bot.pos, sld1), sld2)
                    self.energy += 2 * (
                        self._mlen(sld1) + 2 + self._mlen(sld2)
                    )

                elif name == 'Fill':
                    nd = cmd[1]
                    cp = self._add(bot.pos, nd)
                    if cp not in self.matrix:
                        self.matrix.add(cp)
                        self.energy += 12
                    else:
                        self.energy += 6

                elif name == 'Fission':
                    nd, m = cmd[1], cmd[2]
                    cp = self._add(bot.pos, nd)
                    seeds = sorted(bot.seeds)
                    child_bid = seeds[0]
                    child_seeds = seeds[1:m + 1]
                    bot.seeds = seeds[m + 1:]
                    add_bots.append(Nanobot(child_bid, cp, child_seeds))
                    self.energy += 24

                elif name == 'FusionP':
                    for other_idx, other_cmd in group:
                        if other_cmd[0] == 'FusionS':
                            sec = self.bots[other_idx]
                            bot.seeds = sorted(
                                bot.seeds + [sec.bid] + sec.seeds
                            )
                            remove_indices.add(other_idx)
                            self.energy -= 24
                            break

                elif name == 'FusionS':
                    pass

        self.bots = [
            b for i, b in enumerate(self.bots) if i not in remove_indices
        ]
        self.bots.extend(add_bots)

    def _check_precondition(self, bot, cmd, volatiles):
        name = cmd[0]
        c = bot.pos

        if name == 'Halt':
            if c != (0, 0, 0):
                raise SimError("Halt: bot not at origin")
            if len(self.bots) != 1:
                raise SimError("Halt: not the only active bot")
            if self.harmonics != 'Low':
                raise SimError("Halt: harmonics is not Low")

        elif name == 'SMove':
            lld = cmd[1]
            cp = self._add(c, lld)
            if not self._valid_coord(cp):
                raise SimError(f"SMove: destination {cp} out of bounds")
            region = self._region(c, cp)
            for rc in region:
                if rc in self.matrix:
                    raise SimError(
                        f"SMove: region contains Full voxel {rc}"
                    )
            volatiles.update(region)

        elif name == 'LMove':
            sld1, sld2 = cmd[1], cmd[2]
            cp = self._add(c, sld1)
            cpp = self._add(cp, sld2)
            if not self._valid_coord(cp):
                raise SimError(f"LMove: intermediate {cp} out of bounds")
            if not self._valid_coord(cpp):
                raise SimError(f"LMove: destination {cpp} out of bounds")
            r1 = self._region(c, cp)
            r2 = self._region(cp, cpp)
            combined = r1 | r2
            for rc in combined:
                if rc in self.matrix:
                    raise SimError(
                        f"LMove: region contains Full voxel {rc}"
                    )
            volatiles.update(combined)

        elif name == 'Fill':
            nd = cmd[1]
            cp = self._add(c, nd)
            if not self._valid_coord(cp):
                raise SimError(f"Fill: target {cp} out of bounds")
            volatiles.add(cp)

        elif name == 'Fission':
            nd, m = cmd[1], cmd[2]
            cp = self._add(c, nd)
            if not bot.seeds:
                raise SimError("Fission: bot has no seeds")
            if not self._valid_coord(cp):
                raise SimError(f"Fission: target {cp} out of bounds")
            if cp in self.matrix:
                raise SimError(f"Fission: target {cp} is Full")
            if len(bot.seeds) < m + 1:
                raise SimError(
                    f"Fission: need {m + 1} seeds, have {len(bot.seeds)}"
                )
            volatiles.add(cp)

        elif name == 'FusionP':
            nd = cmd[1]
            cp = self._add(c, nd)
            if not self._valid_coord(cp):
                raise SimError(f"FusionP: target {cp} out of bounds")
            volatiles.add(cp)

        elif name == 'FusionS':
            nd = cmd[1]
            cp = self._add(c, nd)
            if not self._valid_coord(cp):
                raise SimError(f"FusionS: target {cp} out of bounds")
            volatiles.add(cp)


def main():
    if len(sys.argv) != 3:
        print(json.dumps({
            "valid": False, "energy": 0, "steps": 0,
            "model_match": False,
            "error": "Usage: simulate.py <model.json> <trace.json>",
        }))
        sys.exit(1)

    with open(sys.argv[1]) as f:
        model_data = json.load(f)
    with open(sys.argv[2]) as f:
        trace_data = json.load(f)

    sim = Simulator(model_data, trace_data)
    result = sim.run()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
