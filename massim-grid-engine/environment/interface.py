
"""
MASSim 'Agents Assemble' game engine — required API.

Implement these classes in /app/massim_engine.py. All methods must have the
exact signatures shown below. Do not rename classes or methods.
"""


class Role:
    """Defines capabilities and constraints for an agent role.

    Attributes:
        name: Role identifier (e.g. "default", "explorer").
        vision: Manhattan-distance perception radius.
        actions: List of allowed action type strings.
        speed: List[int] indexed by number of attached things.
               speed[i] = max cells per move with i things attached.
               If i >= len(speed), use speed[-1].
        clear_chance: Probability (0–1) that a clear action succeeds.
        clear_max_dist: Maximum Manhattan distance for the clear action.
    """

    def __init__(self, name: str, vision: int, actions: list[str],
                 speed: list[int], clear_chance: float,
                 clear_max_dist: int):
        raise NotImplementedError


class MassimWorld:
    """Simulates the MASSim grid world.

    Constructor:
        MassimWorld(width: int, height: int)
    """

    def __init__(self, width: int, height: int):
        raise NotImplementedError

    # ---- Coordinate helpers ------------------------------------------------

    def wrap(self, x: int, y: int) -> tuple[int, int]:
        """Wrap coordinates to the toroidal grid."""
        raise NotImplementedError

    def manhattan_distance(self, pos1: tuple[int, int],
                           pos2: tuple[int, int]) -> int:
        """Shortest Manhattan distance on the torus."""
        raise NotImplementedError

    # ---- Setup -------------------------------------------------------------

    def add_role(self, role: Role) -> None:
        """Register a role with the world."""
        raise NotImplementedError

    def add_agent(self, name: str, team: str, role_name: str,
                  x: int, y: int, energy: int | None = None) -> dict:
        """Add an agent. If energy is None, use max_energy."""
        raise NotImplementedError

    def place_block(self, block_id: str, block_type: str,
                    x: int, y: int) -> None:
        """Place a block on the grid."""
        raise NotImplementedError

    def place_obstacle(self, x: int, y: int) -> str:
        """Place an obstacle. Returns the obstacle ID."""
        raise NotImplementedError

    def place_dispenser(self, block_type: str, x: int, y: int) -> None:
        """Place a dispenser on the grid."""
        raise NotImplementedError

    def add_goal_zone(self, cx: int, cy: int, radius: int) -> None:
        """Add a goal zone (center + radius)."""
        raise NotImplementedError

    def add_role_zone(self, cx: int, cy: int, radius: int) -> None:
        """Add a role zone (center + radius)."""
        raise NotImplementedError

    def add_norm(self, name: str, subject: str, start: int, until: int,
                 level: str, requirements: list[dict],
                 punishment: int) -> None:
        """Register a norm. subject is 'carry' or 'adopt'."""
        raise NotImplementedError

    def add_task(self, name: str, deadline: int, reward: int,
                 requirements: list[dict]) -> None:
        """Register a task. Each requirement has keys: x, y, type."""
        raise NotImplementedError

    def set_energy_params(self, max_energy: int, step_recharge: int,
                          deactivated_duration: int,
                          refresh_energy: int) -> None:
        """Configure energy system parameters."""
        raise NotImplementedError

    # ---- Queries -----------------------------------------------------------

    def get_agent_position(self, name: str) -> tuple[int, int]:
        raise NotImplementedError

    def get_block_position(self, block_id: str) -> tuple[int, int]:
        raise NotImplementedError

    def get_agent_energy(self, name: str) -> int:
        raise NotImplementedError

    def is_agent_deactivated(self, name: str) -> bool:
        raise NotImplementedError

    def get_score(self, team: str) -> int:
        raise NotImplementedError

    def get_block_at(self, x: int, y: int) -> dict | None:
        """Return {'id': str, 'type': str} or None."""
        raise NotImplementedError

    # ---- Attachment graph --------------------------------------------------

    def is_attached(self, entity1: str, entity2: str) -> bool:
        """Transitive connectivity check (BFS/DFS)."""
        raise NotImplementedError

    def get_all_attached(self, entity_id: str) -> set[str]:
        """All entities transitively attached, excluding entity_id itself."""
        raise NotImplementedError

    def attach_blocks(self, id1: str, id2: str) -> None:
        """Create a direct bidirectional attachment between two things."""
        raise NotImplementedError

    def are_blocks_connected(self, block1: str, block2: str) -> bool:
        """Check DIRECT (non-transitive) connection between two things."""
        raise NotImplementedError

    # ---- Actions -----------------------------------------------------------

    def execute_action(self, agent_name: str, action_type: str,
                       params: list[str], step: int = 0) -> str:
        """Execute an action and return a result code string.

        Result codes include: 'success', 'partial_success', 'failed',
        'failed_parameter', 'failed_path', 'failed_target',
        'failed_blocked', 'failed_status', 'failed_role',
        'failed_resources', 'failed_location', 'failed_partner',
        'unknown_action'.
        """
        raise NotImplementedError

    def execute_connect(self, agent1_name: str, agent2_name: str,
                        a1_block_rel: tuple[int, int],
                        a2_block_rel: tuple[int, int]) -> dict[str, str]:
        """Simultaneous connect action between two same-team agents.

        a1_block_rel / a2_block_rel: (dx, dy) relative to each agent.
        Returns {agent1_name: result, agent2_name: result}.
        """
        raise NotImplementedError

    # ---- Norms -------------------------------------------------------------

    def check_norm_violations(self, agent_name: str,
                              step: int) -> list[str]:
        """Return list of norm names violated by this agent at this step."""
        raise NotImplementedError

    # ---- Energy ------------------------------------------------------------

    def apply_energy_change(self, agent_name: str, amount: int) -> None:
        """Change energy by amount. Deactivates agent if energy reaches 0."""
        raise NotImplementedError

    def deactivate_agent(self, agent_name: str) -> None:
        """Deactivate: set energy=0, sever all direct attachments."""
        raise NotImplementedError

    def apply_step_recharge(self, agent_name: str) -> None:
        """Recharge energy by step_recharge (if not deactivated)."""
        raise NotImplementedError
