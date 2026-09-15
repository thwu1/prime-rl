
from typing import Tuple, Dict, Optional, List, Set

AgentHandle = int
Resource = Tuple[int, int]


class MotionCheck:
    """Conflict resolution for multi-agent railway simulation."""

    def __init__(self):
        self.agents: Dict[AgentHandle, Tuple[Optional[Resource], Optional[Resource]]] = {}
        self.stopped: Set[AgentHandle] = set()

    def add_agent(self, handle: int, current_pos: Optional[tuple], desired_pos: Optional[tuple]):
        """Add an agent with its current and desired positions."""
        r1 = tuple(current_pos) if current_pos is not None else (None, handle)
        r2 = tuple(desired_pos) if desired_pos is not None else (None, handle)
        self.agents[handle] = (r1, r2)

    def find_conflicts(self):
        """Detect and resolve conflicts between agents."""
        # Self-loops: agent not wanting to move
        for handle, (pos, target) in self.agents.items():
            if pos == target:
                self.stopped.add(handle)

        # Head-on swaps
        handles = sorted(self.agents.keys())
        for i, h1 in enumerate(handles):
            for h2 in handles[i + 1:]:
                p1, t1 = self.agents[h1]
                p2, t2 = self.agents[h2]
                if p1 == t2 and t1 == p2 and p1 != t1:
                    self.stopped.add(h1)
                    self.stopped.add(h2)

        # Merge conflicts: multiple agents targeting same cell, lowest handle wins
        target_map: Dict[Resource, List[AgentHandle]] = {}
        for handle, (pos, target) in self.agents.items():
            if handle in self.stopped:
                continue
            if target not in target_map:
                target_map[target] = []
            target_map[target].append(handle)

        for target, contenders in target_map.items():
            if len(contenders) > 1:
                winner = min(contenders)
                for h in contenders:
                    if h != winner:
                        self.stopped.add(h)

    def check_motion(self, handle: int, pos: Optional[tuple]) -> bool:
        """Returns True if the agent is allowed to move."""
        return handle not in self.stopped
