
"""
MASSim 'Agents Assemble' game engine implementation.
Implements the core grid world mechanics from the MAPC scenario specification.
"""


class Role:
    """Defines capabilities and constraints for an agent role."""

    def __init__(self, name: str, vision: int, actions: list[str],
                 speed: list[int], clear_chance: float, clear_max_dist: int):
        self.name = name
        self.vision = vision
        self.actions = actions
        self.speed = speed
        self.clear_chance = clear_chance
        self.clear_max_dist = clear_max_dist


class MassimWorld:
    """
    Simulates the MASSim 'Agents Assemble' grid world.
    Handles toroidal topology, entity management, attachment graphs,
    action execution, norm checking, task submission, and energy.
    """

    DIRECTIONS = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.agents: dict[str, dict] = {}
        self.blocks: dict[str, dict] = {}
        self.obstacles: dict[str, dict] = {}
        self.dispensers: dict[str, dict] = {}
        self.roles: dict[str, Role] = {}
        self.attachments: dict[str, set[str]] = {}
        self.norms: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.goal_zones: list[tuple[int, int, int]] = []
        self.role_zones: list[tuple[int, int, int]] = []
        self.scores: dict[str, int] = {}
        self.energy_params = {
            "max_energy": 100,
            "step_recharge": 1,
            "deactivated_duration": 10,
            "refresh_energy": 50,
        }
        self._next_block_id = 0

    # ---- coordinate helpers ----

    def wrap(self, x: int, y: int) -> tuple[int, int]:
        return (x % self.width, y % self.height)

    def manhattan_distance(self, pos1: tuple[int, int],
                           pos2: tuple[int, int]) -> int:
        dx = abs(pos1[0] - pos2[0])
        dy = abs(pos1[1] - pos2[1])
        dx = min(dx, self.width - dx)
        dy = min(dy, self.height - dy)
        return dx + dy

    # ---- setup methods ----

    def add_role(self, role: Role) -> None:
        self.roles[role.name] = role

    def add_agent(self, name: str, team: str, role_name: str,
                  x: int, y: int, energy: int | None = None) -> dict:
        if energy is None:
            energy = self.energy_params["max_energy"]
        self.agents[name] = {
            "x": x, "y": y, "team": team, "role": role_name,
            "energy": energy, "deactivated": False, "deactivated_steps": 0,
        }
        self.attachments.setdefault(name, set())
        self.scores.setdefault(team, 0)
        return self.agents[name]

    def place_block(self, block_id: str, block_type: str,
                    x: int, y: int) -> None:
        self.blocks[block_id] = {"x": x, "y": y, "type": block_type}
        self.attachments.setdefault(block_id, set())

    def place_obstacle(self, x: int, y: int) -> str:
        obs_id = f"obs_{x}_{y}"
        self.obstacles[obs_id] = {"x": x, "y": y}
        self.attachments.setdefault(obs_id, set())
        return obs_id

    def place_dispenser(self, block_type: str, x: int, y: int) -> None:
        disp_id = f"disp_{block_type}_{x}_{y}"
        self.dispensers[disp_id] = {"x": x, "y": y, "type": block_type}

    def add_goal_zone(self, cx: int, cy: int, radius: int) -> None:
        self.goal_zones.append((cx, cy, radius))

    def add_role_zone(self, cx: int, cy: int, radius: int) -> None:
        self.role_zones.append((cx, cy, radius))

    def add_norm(self, name: str, subject: str, start: int, until: int,
                 level: str, requirements: list[dict],
                 punishment: int) -> None:
        self.norms[name] = {
            "subject": subject, "start": start, "until": until,
            "level": level, "requirements": requirements,
            "punishment": punishment,
        }

    def add_task(self, name: str, deadline: int, reward: int,
                 requirements: list[dict]) -> None:
        self.tasks[name] = {
            "deadline": deadline, "reward": reward,
            "requirements": requirements,
        }

    def set_energy_params(self, max_energy: int, step_recharge: int,
                          deactivated_duration: int,
                          refresh_energy: int) -> None:
        self.energy_params = {
            "max_energy": max_energy, "step_recharge": step_recharge,
            "deactivated_duration": deactivated_duration,
            "refresh_energy": refresh_energy,
        }

    # ---- query methods ----

    def get_agent_position(self, name: str) -> tuple[int, int]:
        a = self.agents[name]
        return (a["x"], a["y"])

    def get_block_position(self, block_id: str) -> tuple[int, int]:
        b = self.blocks[block_id]
        return (b["x"], b["y"])

    def get_agent_energy(self, name: str) -> int:
        return self.agents[name]["energy"]

    def is_agent_deactivated(self, name: str) -> bool:
        return self.agents[name]["deactivated"]

    def get_score(self, team: str) -> int:
        return self.scores.get(team, 0)

    def get_block_at(self, x: int, y: int) -> dict | None:
        x, y = self.wrap(x, y)
        for bid, block in self.blocks.items():
            if block["x"] == x and block["y"] == y:
                return {"id": bid, "type": block["type"]}
        return None

    # ---- attachment graph ----

    def is_attached(self, entity1: str, entity2: str) -> bool:
        visited: set[str] = set()
        queue = [entity1]
        while queue:
            current = queue.pop(0)
            if current == entity2:
                return True
            if current in visited:
                continue
            visited.add(current)
            for nb in self.attachments.get(current, set()):
                if nb not in visited:
                    queue.append(nb)
        return False

    def get_all_attached(self, entity_id: str) -> set[str]:
        visited: set[str] = set()
        queue = [entity_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for nb in self.attachments.get(current, set()):
                if nb not in visited:
                    queue.append(nb)
        visited.discard(entity_id)
        return visited

    def attach_blocks(self, id1: str, id2: str) -> None:
        self.attachments.setdefault(id1, set()).add(id2)
        self.attachments.setdefault(id2, set()).add(id1)

    def are_blocks_connected(self, block1: str, block2: str) -> bool:
        return block2 in self.attachments.get(block1, set())

    # ---- internal helpers ----

    def _get_entity_position(self, eid: str) -> tuple[int, int] | None:
        if eid in self.agents:
            return (self.agents[eid]["x"], self.agents[eid]["y"])
        if eid in self.blocks:
            return (self.blocks[eid]["x"], self.blocks[eid]["y"])
        if eid in self.obstacles:
            return (self.obstacles[eid]["x"], self.obstacles[eid]["y"])
        return None

    def _set_entity_position(self, eid: str, x: int, y: int) -> None:
        x, y = self.wrap(x, y)
        if eid in self.agents:
            self.agents[eid]["x"] = x
            self.agents[eid]["y"] = y
        elif eid in self.blocks:
            self.blocks[eid]["x"] = x
            self.blocks[eid]["y"] = y
        elif eid in self.obstacles:
            self.obstacles[eid]["x"] = x
            self.obstacles[eid]["y"] = y

    def _is_cell_blocked(self, x: int, y: int,
                         exclude: set[str] | None = None) -> bool:
        if exclude is None:
            exclude = set()
        x, y = self.wrap(x, y)
        for name, agent in self.agents.items():
            if name not in exclude and agent["x"] == x and agent["y"] == y:
                return True
        for bid, block in self.blocks.items():
            if bid not in exclude and block["x"] == x and block["y"] == y:
                return True
        for oid, obs in self.obstacles.items():
            if oid not in exclude and obs["x"] == x and obs["y"] == y:
                return True
        return False

    # ---- action execution ----

    def execute_action(self, agent_name: str, action_type: str,
                       params: list[str], step: int = 0) -> str:
        agent = self.agents.get(agent_name)
        if agent is None:
            return "unknown_action"
        if agent["deactivated"]:
            return "failed_status"

        role = self.roles.get(agent["role"])
        if role and action_type not in role.actions and action_type != "skip":
            return "failed_role"

        dispatch = {
            "skip": lambda: "success",
            "move": lambda: self._action_move(agent_name, params),
            "attach": lambda: self._action_attach(agent_name, params),
            "detach": lambda: self._action_detach(agent_name, params),
            "rotate": lambda: self._action_rotate(agent_name, params),
            "request": lambda: self._action_request(agent_name, params),
            "submit": lambda: self._action_submit(agent_name, params, step),
            "clear": lambda: self._action_clear(agent_name, params),
            "adopt": lambda: self._action_adopt(agent_name, params),
            "disconnect": lambda: self._action_disconnect(agent_name, params),
            "survey": lambda: "success",
            "connect": lambda: "failed_partner",
        }
        fn = dispatch.get(action_type)
        if fn is None:
            return "unknown_action"
        return fn()

    def _action_move(self, agent_name: str, params: list[str]) -> str:
        if not params:
            return "failed_parameter"
        for p in params:
            if p not in self.DIRECTIONS:
                return "failed_parameter"

        agent = self.agents[agent_name]
        role = self.roles.get(agent["role"])
        all_attached = self.get_all_attached(agent_name)
        num_attached = len(all_attached)

        if role:
            if num_attached >= len(role.speed):
                max_moves = role.speed[-1]
            else:
                max_moves = role.speed[num_attached]
        else:
            max_moves = 1

        allowed_moves = min(len(params), max_moves)
        if allowed_moves == 0:
            return "failed_path"

        moving_entities = {agent_name} | all_attached
        success_count = 0

        for i in range(allowed_moves):
            dx, dy = self.DIRECTIONS[params[i]]
            can_move = True
            new_positions: dict[str, tuple[int, int]] = {}

            for eid in moving_entities:
                pos = self._get_entity_position(eid)
                nx, ny = self.wrap(pos[0] + dx, pos[1] + dy)
                if self._is_cell_blocked(nx, ny, exclude=moving_entities):
                    can_move = False
                    break
                new_positions[eid] = (nx, ny)

            if not can_move:
                break

            for eid, (nx, ny) in new_positions.items():
                self._set_entity_position(eid, nx, ny)
            success_count += 1

        if success_count == 0:
            return "failed_path"
        if success_count < len(params):
            return "partial_success"
        return "success"

    def _action_attach(self, agent_name: str, params: list[str]) -> str:
        if not params or params[0] not in self.DIRECTIONS:
            return "failed_parameter"

        agent = self.agents[agent_name]
        dx, dy = self.DIRECTIONS[params[0]]
        tx, ty = self.wrap(agent["x"] + dx, agent["y"] + dy)

        target_id = None
        for bid, block in self.blocks.items():
            if block["x"] == tx and block["y"] == ty:
                target_id = bid
                break
        if target_id is None:
            for oid, obs in self.obstacles.items():
                if obs["x"] == tx and obs["y"] == ty:
                    target_id = oid
                    break
        if target_id is None:
            for aname, a in self.agents.items():
                if (aname != agent_name and a["x"] == tx and a["y"] == ty
                        and a["team"] == agent["team"]):
                    target_id = aname
                    break

        if target_id is None:
            return "failed_target"

        self.attachments.setdefault(agent_name, set()).add(target_id)
        self.attachments.setdefault(target_id, set()).add(agent_name)
        return "success"

    def _action_detach(self, agent_name: str, params: list[str]) -> str:
        if not params or params[0] not in self.DIRECTIONS:
            return "failed_parameter"

        agent = self.agents[agent_name]
        dx, dy = self.DIRECTIONS[params[0]]
        tx, ty = self.wrap(agent["x"] + dx, agent["y"] + dy)

        target_id = None
        for attached_id in self.attachments.get(agent_name, set()):
            pos = self._get_entity_position(attached_id)
            if pos and pos[0] == tx and pos[1] == ty:
                target_id = attached_id
                break

        if target_id is None:
            return "failed_target"

        self.attachments[agent_name].discard(target_id)
        self.attachments[target_id].discard(agent_name)
        return "success"

    def _action_rotate(self, agent_name: str, params: list[str]) -> str:
        if not params or params[0] not in ("cw", "ccw"):
            return "failed_parameter"

        agent = self.agents[agent_name]
        direction = params[0]
        all_attached = self.get_all_attached(agent_name)

        for eid in all_attached:
            if eid in self.agents:
                return "failed"

        if not all_attached:
            return "success"

        ax, ay = agent["x"], agent["y"]
        new_positions: dict[str, tuple[int, int]] = {}

        for eid in all_attached:
            pos = self._get_entity_position(eid)
            dx = pos[0] - ax
            dy = pos[1] - ay
            if dx > self.width // 2:
                dx -= self.width
            elif dx < -(self.width // 2):
                dx += self.width
            if dy > self.height // 2:
                dy -= self.height
            elif dy < -(self.height // 2):
                dy += self.height

            if direction == "cw":
                ndx, ndy = -dy, dx
            else:
                ndx, ndy = dy, -dx

            nx, ny = self.wrap(ax + ndx, ay + ndy)
            new_positions[eid] = (nx, ny)

        all_moving = all_attached | {agent_name}
        for eid, (nx, ny) in new_positions.items():
            if self._is_cell_blocked(nx, ny, exclude=all_moving):
                return "failed"

        pos_set: set[tuple[int, int]] = set()
        for nx, ny in new_positions.values():
            if (nx, ny) in pos_set:
                return "failed"
            pos_set.add((nx, ny))
        if (ax, ay) in pos_set:
            return "failed"

        for eid, (nx, ny) in new_positions.items():
            self._set_entity_position(eid, nx, ny)
        return "success"

    def _action_request(self, agent_name: str, params: list[str]) -> str:
        if not params or params[0] not in self.DIRECTIONS:
            return "failed_parameter"

        agent = self.agents[agent_name]
        dx, dy = self.DIRECTIONS[params[0]]
        tx, ty = self.wrap(agent["x"] + dx, agent["y"] + dy)

        dispenser = None
        for d in self.dispensers.values():
            if d["x"] == tx and d["y"] == ty:
                dispenser = d
                break

        if dispenser is None:
            return "failed_target"

        if self._is_cell_blocked(tx, ty):
            return "failed_blocked"

        self._next_block_id += 1
        bid = f"auto_block_{self._next_block_id}"
        self.place_block(bid, dispenser["type"], tx, ty)
        return "success"

    def _action_submit(self, agent_name: str, params: list[str],
                       step: int) -> str:
        if not params:
            return "failed_parameter"

        task_name = params[0]
        task = self.tasks.get(task_name)
        if task is None or step > task["deadline"]:
            return "failed_target"

        agent = self.agents[agent_name]

        in_goal = False
        for cx, cy, radius in self.goal_zones:
            if self.manhattan_distance((agent["x"], agent["y"]),
                                       (cx, cy)) <= radius:
                in_goal = True
                break
        if not in_goal:
            return "failed"

        all_attached = self.get_all_attached(agent_name)
        for req in task["requirements"]:
            rx, ry = self.wrap(agent["x"] + req["x"],
                               agent["y"] + req["y"])
            found = False
            for eid in all_attached:
                if eid in self.blocks:
                    b = self.blocks[eid]
                    if b["x"] == rx and b["y"] == ry and b["type"] == req["type"]:
                        found = True
                        break
            if not found:
                return "failed"

        self.scores[agent["team"]] = self.scores.get(agent["team"], 0) + task["reward"]
        return "success"

    def _action_clear(self, agent_name: str, params: list[str]) -> str:
        if len(params) < 2:
            return "failed_parameter"
        try:
            tx, ty = int(params[0]), int(params[1])
        except ValueError:
            return "failed_parameter"

        agent = self.agents[agent_name]
        role = self.roles.get(agent["role"])

        dist = abs(tx) + abs(ty)
        if role and dist > role.clear_max_dist:
            return "failed_location"

        clear_cost = 2
        if agent["energy"] < clear_cost:
            return "failed_resources"

        abs_x, abs_y = self.wrap(agent["x"] + tx, agent["y"] + ty)
        agent["energy"] -= clear_cost

        for bid in [b for b, bl in self.blocks.items()
                    if bl["x"] == abs_x and bl["y"] == abs_y]:
            for att in list(self.attachments.get(bid, set())):
                self.attachments[att].discard(bid)
            self.attachments.pop(bid, None)
            del self.blocks[bid]

        for oid in [o for o, ob in self.obstacles.items()
                    if ob["x"] == abs_x and ob["y"] == abs_y]:
            for att in list(self.attachments.get(oid, set())):
                self.attachments[att].discard(oid)
            self.attachments.pop(oid, None)
            del self.obstacles[oid]

        return "success"

    def _action_adopt(self, agent_name: str, params: list[str]) -> str:
        if not params or params[0] not in self.roles:
            return "failed_parameter"

        agent = self.agents[agent_name]
        in_zone = False
        for cx, cy, radius in self.role_zones:
            if self.manhattan_distance((agent["x"], agent["y"]),
                                       (cx, cy)) <= radius:
                in_zone = True
                break
        if not in_zone:
            return "failed_location"

        agent["role"] = params[0]
        return "success"

    def _action_disconnect(self, agent_name: str,
                           params: list[str]) -> str:
        if len(params) < 4:
            return "failed_parameter"
        try:
            x1, y1 = int(params[0]), int(params[1])
            x2, y2 = int(params[2]), int(params[3])
        except ValueError:
            return "failed_parameter"

        agent = self.agents[agent_name]
        p1 = self.wrap(agent["x"] + x1, agent["y"] + y1)
        p2 = self.wrap(agent["x"] + x2, agent["y"] + y2)

        all_attached = self.get_all_attached(agent_name)
        b1 = b2 = None
        for eid in all_attached:
            pos = self._get_entity_position(eid)
            if pos == p1:
                b1 = eid
            if pos == p2:
                b2 = eid

        if b1 is None or b2 is None:
            return "failed_target"
        if b2 not in self.attachments.get(b1, set()):
            return "failed_target"

        self.attachments[b1].discard(b2)
        self.attachments[b2].discard(b1)
        return "success"

    # ---- simultaneous connect action ----

    def execute_connect(self, agent1_name: str, agent2_name: str,
                        a1_block_rel: tuple[int, int],
                        a2_block_rel: tuple[int, int]) -> dict[str, str]:
        a1 = self.agents.get(agent1_name)
        a2 = self.agents.get(agent2_name)
        if a1 is None or a2 is None:
            return {agent1_name: "failed_parameter",
                    agent2_name: "failed_parameter"}

        if a1["team"] != a2["team"]:
            return {agent1_name: "failed_parameter",
                    agent2_name: "failed_parameter"}

        a1_bx, a1_by = self.wrap(a1["x"] + a1_block_rel[0],
                                  a1["y"] + a1_block_rel[1])
        a2_bx, a2_by = self.wrap(a2["x"] + a2_block_rel[0],
                                  a2["y"] + a2_block_rel[1])

        a1_tree = self.get_all_attached(agent1_name)
        a2_tree = self.get_all_attached(agent2_name)

        block1 = block2 = None
        for eid in a1_tree:
            if eid in self.blocks:
                b = self.blocks[eid]
                if b["x"] == a1_bx and b["y"] == a1_by:
                    block1 = eid
                    break

        for eid in a2_tree:
            if eid in self.blocks:
                b = self.blocks[eid]
                if b["x"] == a2_bx and b["y"] == a2_by:
                    block2 = eid
                    break

        if block1 is None or block2 is None:
            return {agent1_name: "failed_target",
                    agent2_name: "failed_target"}

        if self.manhattan_distance((a1_bx, a1_by), (a2_bx, a2_by)) != 1:
            return {agent1_name: "failed", agent2_name: "failed"}

        self.attachments[block1].add(block2)
        self.attachments[block2].add(block1)
        return {agent1_name: "success", agent2_name: "success"}

    # ---- norm checking ----

    def check_norm_violations(self, agent_name: str,
                              step: int) -> list[str]:
        violations: list[str] = []
        agent = self.agents[agent_name]

        for norm_name, norm in self.norms.items():
            if step < norm["start"] or step > norm["until"]:
                continue

            if norm["subject"] == "carry":
                all_attached = self.get_all_attached(agent_name)
                count = len(all_attached)
                max_allowed = norm["requirements"][0]["quantity"]
                if count > max_allowed:
                    violations.append(norm_name)

            elif norm["subject"] == "adopt":
                req = norm["requirements"][0]
                role_name = req["name"]
                max_allowed = req["quantity"]
                if agent["role"] != role_name:
                    continue
                team_count = sum(
                    1 for a in self.agents.values()
                    if a["team"] == agent["team"] and a["role"] == role_name
                )
                if team_count > max_allowed:
                    violations.append(norm_name)

        return violations

    # ---- energy management ----

    def apply_energy_change(self, agent_name: str, amount: int) -> None:
        agent = self.agents[agent_name]
        agent["energy"] = max(
            0, min(self.energy_params["max_energy"], agent["energy"] + amount)
        )
        if agent["energy"] <= 0:
            self.deactivate_agent(agent_name)

    def deactivate_agent(self, agent_name: str) -> None:
        agent = self.agents[agent_name]
        agent["deactivated"] = True
        agent["energy"] = 0
        agent["deactivated_steps"] = self.energy_params["deactivated_duration"]
        for attached_id in list(self.attachments.get(agent_name, set())):
            self.attachments[agent_name].discard(attached_id)
            self.attachments[attached_id].discard(agent_name)

    def apply_step_recharge(self, agent_name: str) -> None:
        agent = self.agents[agent_name]
        if not agent["deactivated"]:
            agent["energy"] = min(
                self.energy_params["max_energy"],
                agent["energy"] + self.energy_params["step_recharge"],
            )
