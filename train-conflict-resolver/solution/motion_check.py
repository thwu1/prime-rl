
from typing import Tuple, Dict, Optional, List, Set


AgentHandle = int
Resource = Tuple[int, int]


class MotionCheck:
    """
    Graph-based conflict resolution for multi-agent railway simulation.

    Detects head-on swaps (deadlocks), resolves merge conflicts (lowest handle wins),
    and propagates blocking through predecessor chains.
    """

    def __init__(self):
        self.agents: Dict[AgentHandle, Tuple[Optional[Resource], Optional[Resource]]] = {}
        self.reverse_target: Dict[Resource, List[AgentHandle]] = {}
        self.stopped: Set[AgentHandle] = set()
        self.deadlocked: Set[AgentHandle] = set()

    def add_agent(self, handle: int, current_pos: Optional[tuple], desired_pos: Optional[tuple]):
        """
        Add an agent with its current resource and desired next resource.
        If positions are None, substitute a unique dummy position.
        """
        r1 = tuple(current_pos) if current_pos is not None else (None, handle)
        r2 = tuple(desired_pos) if desired_pos is not None else (None, handle)

        self.agents[handle] = (r1, r2)

        if r2 not in self.reverse_target:
            self.reverse_target[r2] = [handle]
        else:
            self.reverse_target[r2].append(handle)

    def find_conflicts(self):
        """
        Detect and resolve all conflicts:
        1. Detect swaps (head-on collisions) and mark both agents as deadlocked/stopped.
        2. Mark agents with self-loops (current == desired) as voluntarily stopped.
        3. Resolve merge conflicts where multiple agents target the same cell (lowest handle wins).
        4. Propagate stopping through predecessor chains.
        """
        target_conflicts = self._construct_graph()

        # Process deadlocked agents first
        for a in list(self.deadlocked):
            a_pos, a_target = self.agents[a]
            self.agents[a] = (a_pos, a_pos)
            target_conflicts = self._stop_and_update_target_conflicts(target_conflicts, a, a_pos, a_target)

        self._fix_conflicts(target_conflicts)

    def _construct_graph(self) -> List[Tuple[AgentHandle, AgentHandle]]:
        target_conflicts: List[Tuple[AgentHandle, AgentHandle]] = []

        for handle, (pos, target) in self.agents.items():
            # Detect swaps: agent A at pos wanting target, while some agent B at target wanting pos
            if pos in self.reverse_target:
                for a2 in self.reverse_target[pos]:
                    if handle >= a2:
                        continue
                    a2_pos, a2_target = self.agents[a2]
                    if pos == a2_target and target == a2_pos:
                        self.stopped.add(handle)
                        self.stopped.add(a2)
                        self.deadlocked.add(handle)
                        self.deadlocked.add(a2)

            # Collect target conflicts (agents sharing the same target)
            conflict_list = self.reverse_target[target]
            for a2 in conflict_list:
                if handle >= a2:
                    continue
                target_conflicts.append((handle, a2))

            # Self-loop: agent doesn't want to move
            if pos == target:
                self.stopped.add(handle)

        return target_conflicts

    def _fix_conflicts(self, target_conflicts: List[Tuple[AgentHandle, AgentHandle]]):
        while len(target_conflicts) > 0:
            u, v = target_conflicts[0]
            u_pos, u_target = self.agents[u]
            v_pos, v_target = self.agents[v]

            if v_pos == v_target:
                # v is stopped/not moving -> u is blocked by v
                target_conflicts = self._stop_and_update_target_conflicts(target_conflicts, u, u_pos, u_target)
            elif u_target == v_target:
                # Same target, v has larger index -> v loses
                target_conflicts = self._stop_and_update_target_conflicts(target_conflicts, v, v_pos, v_target)
            # else: no conflict any more (resolved by prior stopping)

            target_conflicts = target_conflicts[1:]

    def _stop_and_update_target_conflicts(
        self,
        target_conflicts: List[Tuple[AgentHandle, AgentHandle]],
        v: AgentHandle,
        v_pos: Resource,
        v_target: Resource,
    ) -> List[Tuple[AgentHandle, AgentHandle]]:
        """Stop agent v and propagate: any agent wanting v's new resting position gets a new conflict."""
        self.agents[v] = (v_pos, v_pos)
        self.stopped.add(v)

        # Now v stays at v_pos. Any agent that was targeting v_pos now conflicts with v.
        if v_pos in self.reverse_target:
            new_conflicts = [
                (v, other) if v < other else (other, v)
                for other in self.reverse_target[v_pos]
                if other != v
            ]
            target_conflicts = target_conflicts + new_conflicts
            self.reverse_target[v_pos].append(v)
        else:
            self.reverse_target[v_pos] = [v]

        # Remove v from old target's reverse list
        if v_target in self.reverse_target and v in self.reverse_target[v_target]:
            self.reverse_target[v_target].remove(v)

        return target_conflicts

    def check_motion(self, handle: int, pos: Optional[tuple]) -> bool:
        """
        Check if an agent can move.
        Returns False if the agent is in the stopped set or didn't want to move.
        """
        return handle not in self.stopped
