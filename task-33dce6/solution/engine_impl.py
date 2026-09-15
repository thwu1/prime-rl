
"""MASSim 'Agents Assemble' Game Engine Implementation."""

from collections import defaultdict


class GameEngine:
    """Simulates the MASSim Agents Assemble scenario."""

    def __init__(self, config, initial_state):
        self.width = config["grid"]["width"]
        self.height = config["grid"]["height"]

        self.roles = {}
        for r in config["roles"]:
            self.roles[r["name"]] = {
                "name": r["name"],
                "vision": r["vision"],
                "actions": set(r["actions"]),
                "speed": list(r["speed"]),
                "clear": r.get("clear", {"chance": 0.0, "maxDistance": 0}),
            }

        self.max_energy = config["maxEnergy"]
        self.step_recharge = config["stepRecharge"]
        self.clear_energy_cost = config["clearEnergyCost"]
        self.deactivated_duration = config["deactivatedDuration"]
        self.refresh_energy = config["refreshEnergy"]
        self.clear_damage = list(config["clearDamage"])
        self.attach_limit = config["attachLimit"]
        self.max_steps = config["steps"]
        self.current_step = 0

        # Scores per team
        self.scores = {}

        # Agents keyed by name
        self.agents = {}
        for a in initial_state.get("agents", []):
            self.agents[a["name"]] = {
                "name": a["name"],
                "team": a["team"],
                "x": a["x"] % self.width,
                "y": a["y"] % self.height,
                "role": a["role"],
                "energy": a["energy"],
                "deactivated": False,
                "deactivated_steps": 0,
            }
            self.scores.setdefault(a["team"], 0)

        # Blocks keyed by id
        self._id_counter = 0
        self.blocks = {}
        for b in initial_state.get("blocks", []):
            bid = self._next_id()
            self.blocks[bid] = {"x": b["x"], "y": b["y"], "type": b["type"]}

        # Dispensers (list, not keyed)
        self.dispensers = list(initial_state.get("dispensers", []))

        # Obstacles keyed by id
        self.obstacles = {}
        for o in initial_state.get("obstacles", []):
            oid = self._next_id()
            self.obstacles[oid] = {"x": o["x"], "y": o["y"]}

        # Zones
        self.goal_zones = set(tuple(g) for g in initial_state.get("goalZones", []))
        self.role_zones = set(tuple(r) for r in initial_state.get("roleZones", []))

        # Tasks and norms
        self.tasks = [dict(t) for t in initial_state.get("tasks", [])]
        self.norms = [dict(n) for n in initial_state.get("norms", [])]

        # Attachment graph: adjacency sets between entity keys.
        # Keys: ("agent", name) | ("block", id) | ("obstacle", id)
        self.adj = defaultdict(set)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_id(self):
        self._id_counter += 1
        return self._id_counter

    def _wrap(self, x, y):
        return x % self.width, y % self.height

    def _manhattan(self, x1, y1, x2, y2):
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        return min(dx, self.width - dx) + min(dy, self.height - dy)

    _DIRS = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}

    def _dir_delta(self, d):
        return self._DIRS.get(d)

    def _entity_pos(self, key):
        kind, ident = key
        if kind == "agent":
            a = self.agents[ident]
            return a["x"], a["y"]
        if kind == "block":
            b = self.blocks[ident]
            return b["x"], b["y"]
        if kind == "obstacle":
            o = self.obstacles[ident]
            return o["x"], o["y"]
        return None

    def _set_pos(self, key, x, y):
        kind, ident = key
        if kind == "agent":
            self.agents[ident]["x"] = x
            self.agents[ident]["y"] = y
        elif kind == "block":
            self.blocks[ident]["x"] = x
            self.blocks[ident]["y"] = y
        elif kind == "obstacle":
            self.obstacles[ident]["x"] = x
            self.obstacles[ident]["y"] = y

    def _entity_exists(self, key):
        kind, ident = key
        if kind == "agent":
            return ident in self.agents
        if kind == "block":
            return ident in self.blocks
        if kind == "obstacle":
            return ident in self.obstacles
        return False

    def _component(self, key):
        """BFS to find connected component through attachment edges."""
        visited = set()
        stack = [key]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            for nb in self.adj.get(cur, set()):
                if nb not in visited and self._entity_exists(nb):
                    stack.append(nb)
        return visited

    def _count_attached(self, agent_name):
        return len(self._component(("agent", agent_name))) - 1

    def _get_speed(self, agent_name):
        role = self.roles[self.agents[agent_name]["role"]]
        n = self._count_attached(agent_name)
        speeds = role["speed"]
        if n >= len(speeds):
            return speeds[-1]
        return speeds[n]

    def _things_at(self, x, y, exclude=None):
        """Return entity keys at position, excluding given set."""
        exclude = exclude or set()
        result = []
        for name, a in self.agents.items():
            k = ("agent", name)
            if k not in exclude and a["x"] == x and a["y"] == y:
                result.append(k)
        for bid, b in self.blocks.items():
            k = ("block", bid)
            if k not in exclude and b["x"] == x and b["y"] == y:
                result.append(k)
        for oid, o in self.obstacles.items():
            k = ("obstacle", oid)
            if k not in exclude and o["x"] == x and o["y"] == y:
                result.append(k)
        return result

    def _occupied(self, x, y, exclude=None):
        return len(self._things_at(x, y, exclude)) > 0

    def _attach_edge(self, k1, k2):
        self.adj[k1].add(k2)
        self.adj[k2].add(k1)

    def _detach_edge(self, k1, k2):
        self.adj[k1].discard(k2)
        self.adj[k2].discard(k1)

    def _remove_entity(self, key):
        for nb in list(self.adj.get(key, set())):
            self.adj[nb].discard(key)
        if key in self.adj:
            del self.adj[key]
        kind, ident = key
        if kind == "block" and ident in self.blocks:
            del self.blocks[ident]
        elif kind == "obstacle" and ident in self.obstacles:
            del self.obstacles[ident]

    def _deactivate_agent(self, name):
        agent = self.agents[name]
        agent["deactivated"] = True
        agent["deactivated_steps"] = self.deactivated_duration
        ak = ("agent", name)
        for nb in list(self.adj.get(ak, set())):
            self._detach_edge(ak, nb)

    def _relative(self, ax, ay, tx, ty):
        """Shortest relative coordinates on torus."""
        rx = tx - ax
        ry = ty - ay
        if rx > self.width // 2:
            rx -= self.width
        elif rx < -(self.width // 2):
            rx += self.width
        if ry > self.height // 2:
            ry -= self.height
        elif ry < -(self.height // 2):
            ry += self.height
        return rx, ry

    # ------------------------------------------------------------------
    # Action processors
    # ------------------------------------------------------------------

    def _act_skip(self, name, params):
        return {"result": "success"}

    def _act_move(self, name, params):
        agent = self.agents[name]
        if not params:
            return {"result": "failed_parameter"}
        for p in params:
            if p not in self._DIRS:
                return {"result": "failed_parameter"}

        speed = self._get_speed(name)
        if speed == 0:
            return {"result": "failed_path"}

        to_try = params[: min(len(params), speed)]
        comp = self._component(("agent", name))
        done = 0

        for direction in to_try:
            dx, dy = self._dir_delta(direction)
            new_pos = {}
            for k in comp:
                ox, oy = self._entity_pos(k)
                new_pos[k] = self._wrap(ox + dx, oy + dy)

            blocked = False
            for k, (nx, ny) in new_pos.items():
                if self._things_at(nx, ny, exclude=comp):
                    blocked = True
                    break
            if blocked:
                return {"result": "failed_path" if done == 0 else "partial_success"}

            for k, (nx, ny) in new_pos.items():
                self._set_pos(k, nx, ny)
            done += 1

        return {"result": "success"}

    def _act_attach(self, name, params):
        agent = self.agents[name]
        if len(params) != 1 or params[0] not in self._DIRS:
            return {"result": "failed_parameter"}

        dx, dy = self._dir_delta(params[0])
        tx, ty = self._wrap(agent["x"] + dx, agent["y"] + dy)

        targets = self._things_at(tx, ty)
        if not targets:
            return {"result": "failed_target"}

        target = targets[0]

        # Check opponent attachment
        t_comp = self._component(target)
        for k in t_comp:
            if k[0] == "agent" and self.agents[k[1]]["team"] != agent["team"]:
                return {"result": "failed_blocked"}

        # Check attach limit
        my_comp = self._component(("agent", name))
        if len(my_comp) >= self.attach_limit:
            return {"result": "failed"}

        self._attach_edge(("agent", name), target)
        return {"result": "success"}

    def _act_detach(self, name, params):
        agent = self.agents[name]
        if len(params) != 1 or params[0] not in self._DIRS:
            return {"result": "failed_parameter"}

        dx, dy = self._dir_delta(params[0])
        tx, ty = self._wrap(agent["x"] + dx, agent["y"] + dy)

        ak = ("agent", name)
        found = None
        for nb in self.adj.get(ak, set()):
            if self._entity_exists(nb) and self._entity_pos(nb) == (tx, ty):
                found = nb
                break

        if found is None:
            things = self._things_at(tx, ty)
            if things:
                return {"result": "failed"}
            return {"result": "failed_target"}

        self._detach_edge(ak, found)
        return {"result": "success"}

    def _act_rotate(self, name, params):
        agent = self.agents[name]
        if len(params) != 1 or params[0] not in ("cw", "ccw"):
            return {"result": "failed_parameter"}

        direction = params[0]
        ak = ("agent", name)
        comp = self._component(ak)

        for k in comp:
            if k[0] == "agent" and k[1] != name:
                return {"result": "failed"}

        ax, ay = agent["x"], agent["y"]
        new_pos = {}
        for k in comp:
            if k == ak:
                continue
            ox, oy = self._entity_pos(k)
            dx, dy = self._relative(ax, ay, ox, oy)
            if direction == "cw":
                ndx, ndy = -dy, dx
            else:
                ndx, ndy = dy, -dx
            new_pos[k] = self._wrap(ax + ndx, ay + ndy)

        # Check collisions
        for k, (nx, ny) in new_pos.items():
            if self._things_at(nx, ny, exclude=comp):
                return {"result": "failed"}

        # Check internal collisions
        all_new = list(new_pos.values()) + [(ax, ay)]
        if len(set(all_new)) != len(all_new):
            return {"result": "failed"}

        for k, (nx, ny) in new_pos.items():
            self._set_pos(k, nx, ny)
        return {"result": "success"}

    def _act_request(self, name, params):
        agent = self.agents[name]
        if len(params) != 1 or params[0] not in self._DIRS:
            return {"result": "failed_parameter"}

        dx, dy = self._dir_delta(params[0])
        tx, ty = self._wrap(agent["x"] + dx, agent["y"] + dy)

        dispenser = None
        for d in self.dispensers:
            if d["x"] == tx and d["y"] == ty:
                dispenser = d
                break
        if dispenser is None:
            return {"result": "failed_target"}

        if self._occupied(tx, ty):
            return {"result": "failed_blocked"}

        bid = self._next_id()
        self.blocks[bid] = {"x": tx, "y": ty, "type": dispenser["type"]}
        return {"result": "success"}

    def _act_connect(self, name, params, all_actions):
        agent = self.agents[name]
        if len(params) != 3:
            return {"result": "failed_parameter"}

        partner_name = params[0]
        try:
            bx, by = int(params[1]), int(params[2])
        except (ValueError, TypeError):
            return {"result": "failed_parameter"}

        if partner_name not in self.agents:
            return {"result": "failed_parameter"}
        partner = self.agents[partner_name]
        if partner["team"] != agent["team"]:
            return {"result": "failed_parameter"}

        pa = all_actions.get(partner_name)
        if pa is None or pa.get("type") != "connect":
            return {"result": "failed_partner"}
        pp = pa.get("p", [])
        if len(pp) != 3 or pp[0] != name:
            return {"result": "failed_partner"}
        try:
            int(pp[1]); int(pp[2])
        except (ValueError, TypeError):
            return {"result": "failed_partner"}

        # Locate own block
        abs_bx, abs_by = self._wrap(agent["x"] + bx, agent["y"] + by)
        ak = ("agent", name)
        my_comp = self._component(ak)
        my_block = None
        for k in my_comp:
            if k[0] == "block" and self._entity_pos(k) == (abs_bx, abs_by):
                my_block = k
                break
        if my_block is None:
            return {"result": "failed_target"}

        # Locate partner's block
        pbx, pby = int(pp[1]), int(pp[2])
        abs_pbx, abs_pby = self._wrap(partner["x"] + pbx, partner["y"] + pby)
        pk = ("agent", partner_name)
        p_comp = self._component(pk)
        p_block = None
        for k in p_comp:
            if k[0] == "block" and self._entity_pos(k) == (abs_pbx, abs_pby):
                p_block = k
                break
        if p_block is None:
            return {"result": "failed_target"}

        # Must be adjacent
        mx, my_ = self._entity_pos(my_block)
        px, py_ = self._entity_pos(p_block)
        if self._manhattan(mx, my_, px, py_) != 1:
            return {"result": "failed"}

        # Must not already be same component
        if p_block in my_comp:
            return {"result": "failed"}

        # Attach limit
        if len(my_comp) + len(p_comp) > self.attach_limit:
            return {"result": "failed"}

        self._attach_edge(my_block, p_block)
        return {"result": "success"}

    def _act_disconnect(self, name, params):
        agent = self.agents[name]
        if len(params) != 4:
            return {"result": "failed_parameter"}
        try:
            x1, y1, x2, y2 = int(params[0]), int(params[1]), int(params[2]), int(params[3])
        except (ValueError, TypeError):
            return {"result": "failed_parameter"}

        abs1 = self._wrap(agent["x"] + x1, agent["y"] + y1)
        abs2 = self._wrap(agent["x"] + x2, agent["y"] + y2)

        ak = ("agent", name)
        comp = self._component(ak)
        t1 = t2 = None
        for k in comp:
            if k == ak:
                continue
            p = self._entity_pos(k)
            if p == abs1:
                t1 = k
            if p == abs2:
                t2 = k
        if t1 is None or t2 is None:
            return {"result": "failed_target"}
        if t2 not in self.adj.get(t1, set()):
            return {"result": "failed_target"}

        self._detach_edge(t1, t2)
        return {"result": "success"}

    def _act_submit(self, name, params):
        agent = self.agents[name]
        if len(params) != 1:
            return {"result": "failed_parameter"}

        task_name = params[0]
        task = None
        for t in self.tasks:
            if t["name"] == task_name and t["deadline"] >= self.current_step:
                task = t
                break
        if task is None:
            return {"result": "failed_target"}

        if (agent["x"], agent["y"]) not in self.goal_zones:
            return {"result": "failed"}

        ak = ("agent", name)
        comp = self._component(ak)

        # Map relative position -> (key, block_type) for attached blocks
        attached = {}
        for k in comp:
            if k[0] != "block":
                continue
            bx, by = self._entity_pos(k)
            rx, ry = self._relative(agent["x"], agent["y"], bx, by)
            attached[(rx, ry)] = (k, self.blocks[k[1]]["type"])

        to_remove = []
        for req in task["requirements"]:
            pos = (req["x"], req["y"])
            if pos not in attached:
                return {"result": "failed"}
            k, btype = attached[pos]
            if btype != req["type"]:
                return {"result": "failed"}
            to_remove.append(k)

        self.scores[agent["team"]] += task["reward"]
        for k in to_remove:
            self._remove_entity(k)
        return {"result": "success"}

    def _act_adopt(self, name, params):
        agent = self.agents[name]
        if len(params) != 1:
            return {"result": "failed_parameter"}
        new_role = params[0]
        if new_role not in self.roles:
            return {"result": "failed_parameter"}
        if (agent["x"], agent["y"]) not in self.role_zones:
            return {"result": "failed_location"}
        agent["role"] = new_role
        return {"result": "success"}

    def _act_clear(self, name, params):
        agent = self.agents[name]
        role = self.roles[agent["role"]]
        if len(params) != 2:
            return {"result": "failed_parameter"}
        try:
            tx, ty = int(params[0]), int(params[1])
        except (ValueError, TypeError):
            return {"result": "failed_parameter"}

        abs_tx, abs_ty = self._wrap(agent["x"] + tx, agent["y"] + ty)
        dist_to_target = self._manhattan(agent["x"], agent["y"], abs_tx, abs_ty)

        if dist_to_target > role["vision"]:
            return {"result": "failed_target"}
        clear_max = role["clear"]["maxDistance"]
        if dist_to_target > clear_max:
            return {"result": "failed_location"}
        if agent["energy"] < self.clear_energy_cost:
            return {"result": "failed_resources"}

        agent["energy"] -= self.clear_energy_cost

        # Remove blocks and obstacles at target
        to_remove = []
        for bid, b in self.blocks.items():
            if b["x"] == abs_tx and b["y"] == abs_ty:
                to_remove.append(("block", bid))
        for oid, o in self.obstacles.items():
            if o["x"] == abs_tx and o["y"] == abs_ty:
                to_remove.append(("obstacle", oid))
        for k in to_remove:
            self._remove_entity(k)

        # Damage entities at target if maxDistance > 1
        if clear_max > 1:
            for other_name, other in list(self.agents.items()):
                if other["x"] == abs_tx and other["y"] == abs_ty and other_name != name:
                    d = self._manhattan(agent["x"], agent["y"], other["x"], other["y"])
                    dmg = self.clear_damage[d] if d < len(self.clear_damage) else self.clear_damage[-1]
                    other["energy"] = max(0, other["energy"] - dmg)
                    if other["energy"] == 0 and not other["deactivated"]:
                        self._deactivate_agent(other_name)

        return {"result": "success"}

    def _act_survey(self, name, params):
        return {"result": "success"}

    # ------------------------------------------------------------------
    # Main step
    # ------------------------------------------------------------------

    _ACTION_ORDER = [
        "skip", "adopt", "survey", "clear", "request", "attach",
        "detach", "disconnect", "rotate", "connect", "move", "submit",
    ]

    _DISPATCH = {
        "skip": "_act_skip",
        "move": "_act_move",
        "attach": "_act_attach",
        "detach": "_act_detach",
        "rotate": "_act_rotate",
        "request": "_act_request",
        "disconnect": "_act_disconnect",
        "submit": "_act_submit",
        "adopt": "_act_adopt",
        "clear": "_act_clear",
        "survey": "_act_survey",
    }

    def step(self, actions):
        # Default missing agents to skip
        for name in self.agents:
            if name not in actions:
                actions[name] = {"type": "skip", "p": []}

        results = {}

        # Group by action type
        by_type = defaultdict(list)
        for name, act in actions.items():
            if name in self.agents:
                by_type[act.get("type", "skip")].append(name)
        for t in by_type:
            by_type[t].sort()

        processed_connects = set()

        for atype in self._ACTION_ORDER:
            for name in by_type.get(atype, []):
                if name in results:
                    continue

                agent = self.agents[name]
                act = actions[name]
                params = act.get("p", [])

                # Deactivated check
                if agent["deactivated"]:
                    results[name] = {"result": "failed_status"}
                    continue

                # Role check
                role = self.roles[agent["role"]]
                if atype not in ("skip",) and atype not in role["actions"]:
                    results[name] = {"result": "failed_role"}
                    continue

                # Dispatch
                if atype == "connect":
                    if name in processed_connects:
                        continue
                    r = self._act_connect(name, params, actions)
                    results[name] = r
                    processed_connects.add(name)
                    if r["result"] == "success" and len(params) >= 1:
                        partner = params[0]
                        results[partner] = {"result": "success"}
                        processed_connects.add(partner)
                elif atype in self._DISPATCH:
                    method = getattr(self, self._DISPATCH[atype])
                    results[name] = method(name, params)
                else:
                    results[name] = {"result": "unknown_action"}

        # Handle agents with unknown action types
        for name in self.agents:
            if name not in results:
                results[name] = {"result": "unknown_action"}

        # --- End-of-step processing ---

        # 1. Norm enforcement
        self._enforce_norms()

        # 2. Deactivation countdown + energy recharge
        for name, agent in self.agents.items():
            if agent["deactivated"]:
                agent["deactivated_steps"] -= 1
                if agent["deactivated_steps"] <= 0:
                    agent["deactivated"] = False
                    agent["energy"] = self.refresh_energy
            else:
                agent["energy"] = min(self.max_energy,
                                      agent["energy"] + self.step_recharge)

        # 3. Increment step
        self.current_step += 1

        return results

    def _enforce_norms(self):
        for norm in self.norms:
            if norm["start"] > self.current_step or norm["until"] < self.current_step:
                continue
            for req in norm["requirements"]:
                if req["type"] == "block":
                    max_carry = req["quantity"]
                    for name, agent in list(self.agents.items()):
                        if agent["deactivated"]:
                            continue
                        n = self._count_attached(name)
                        if n > max_carry:
                            agent["energy"] = max(0, agent["energy"] - norm["punishment"])
                            if agent["energy"] == 0 and not agent["deactivated"]:
                                self._deactivate_agent(name)
                elif req["type"] == "role":
                    role_name = req["name"]
                    max_count = req["quantity"]
                    teams = defaultdict(list)
                    for name, agent in self.agents.items():
                        if agent["role"] == role_name and not agent["deactivated"]:
                            teams[agent["team"]].append(name)
                    for team, members in teams.items():
                        if len(members) > max_count:
                            for name in members:
                                agent = self.agents[name]
                                agent["energy"] = max(0, agent["energy"] - norm["punishment"])
                                if agent["energy"] == 0 and not agent["deactivated"]:
                                    self._deactivate_agent(name)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_agent(self, name):
        agent = self.agents[name]
        ak = ("agent", name)
        comp = self._component(ak)
        attached = []
        for k in comp:
            if k == ak:
                continue
            ex, ey = self._entity_pos(k)
            rx, ry = self._relative(agent["x"], agent["y"], ex, ey)
            attached.append([rx, ry])
        return {
            "name": agent["name"],
            "team": agent["team"],
            "x": agent["x"],
            "y": agent["y"],
            "role": agent["role"],
            "energy": agent["energy"],
            "deactivated": agent["deactivated"],
            "deactivated_steps": agent["deactivated_steps"],
            "attached": attached,
        }

    def get_score(self, team):
        return self.scores.get(team, 0)

    def get_step(self):
        return self.current_step

    def get_things_at(self, x, y):
        things = []
        for name, a in self.agents.items():
            if a["x"] == x and a["y"] == y:
                things.append({"type": "entity", "details": a["team"]})
        for bid, b in self.blocks.items():
            if b["x"] == x and b["y"] == y:
                things.append({"type": "block", "details": b["type"]})
        for d in self.dispensers:
            if d["x"] == x and d["y"] == y:
                things.append({"type": "dispenser", "details": d["type"]})
        for oid, o in self.obstacles.items():
            if o["x"] == x and o["y"] == y:
                things.append({"type": "obstacle", "details": ""})
        return things

    def get_blocks(self):
        result = []
        for bid, b in self.blocks.items():
            attached_to = None
            comp = self._component(("block", bid))
            for k in comp:
                if k[0] == "agent":
                    attached_to = k[1]
                    break
            result.append({
                "x": b["x"], "y": b["y"], "type": b["type"],
                "attached_to": attached_to,
            })
        return result
