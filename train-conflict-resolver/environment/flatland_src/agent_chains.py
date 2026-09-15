"""
Flatland reference source: flatland.envs.agent_chains

Agent-Close Following is an edge case in mutual exclusive resource allocation,
i.e. the same resource can be held by at most one agent at the same time.
In Flatland, a grid cell is a resource, and only one agent can be in a grid cell.

MotionCheck ensures:
- no swaps (i.e. collisions)
- no two agents must be allowed to move to the same target cell (resource)
- if all agents in the chain run at the same speed, all can run (behaviour not depending on agent indices)
"""
from typing import Tuple, Dict, Optional, List
from typing import Set

AgentHandle = int
Resource = Tuple[int, int]


class MotionCheck(object):
    """
    Implementation based on Bochatay (2024), Speeding up Railway Generation and
    Train Simulation for the Flatland Challenge.
    """

    def __init__(self):
        # agents and their current and desired resource
        self.agents: Dict[AgentHandle, Tuple[Resource, Resource]] = {}
        # agents desiring to acquire the resource
        self.reverse_target: Dict[Resource, List[AgentHandle]] = {}

        self.stopped: Set[AgentHandle] = set()
        self.deadlocked: Set[AgentHandle] = set()

    def add_agent(self, i: int, r1: Optional[Resource], r2: Optional[Resource]):
        """
        Add agent holding resource r1 and trying to acquire r2 (or not release r1 if r1==r2).
        """
        if r1 is None:
            r1 = (None, i)
        if r2 is None:
            r2 = (None, i)
        self.agents[i] = (r1, r2)
        if r2 not in self.reverse_target:
            self.reverse_target[r2] = [i]
        else:
            self.reverse_target[r2].append(i)

    def find_conflicts(self):
        """
        Find and resolve conflicts:
        - swaps aka. deadlocks (head-to-head collisions)
        - two agents same target

        Correctness:
        - deadlocked agents are stopped
        - for each conflict, one of the agents is stopped.

        Termination: The list of target_conflicts will eventually be empty as in every round, one agent is stopped.
        """
        target_conflicts = self._construct_graph()
        # no need to process deadlocked agents further (avoid ConcurrentModificationException)
        for a in self.deadlocked:
            a_pos, a_target = self.agents[a]
            self.agents[a] = (a_pos, a_pos)
            target_conflicts = self._stop_and_update_target_conflicts(target_conflicts, a, a_pos, a_target)
        self._fix_conflicts(target_conflicts)

    def _construct_graph(self):
        target_conflicts: List[Tuple[AgentHandle, AgentHandle]] = []  # a1 < a2
        for iAg, (pos, target) in self.agents.items():
            # find deadlocks aka. swaps aka. head-on collisions
            if pos in self.reverse_target:
                conflict_list = self.reverse_target[pos]
                for a2 in conflict_list:
                    if iAg >= a2:
                        continue
                    a2pos, a2_target = self.agents[a2]
                    if pos == a2_target and target == a2pos:
                        self.stopped.add(iAg)
                        self.stopped.add(a2)
                        self.deadlocked.add(iAg)
                        self.deadlocked.add(a2)
            # find target conflicts
            conflict_list = self.reverse_target[target]
            for a2 in conflict_list:
                if iAg >= a2:
                    continue
                target_conflicts.append((iAg, a2))
            if pos == target:
                self.stopped.add(iAg)
        return target_conflicts

    def _fix_conflicts(self, target_conflicts):
        while len(target_conflicts) > 0:
            u, v = target_conflicts[0]
            u_pos, u_target = self.agents[u]
            v_pos, v_target = self.agents[v]
            if v_pos == v_target:
                # if v is already stopped/does not want to move, also stop u as it is blocked
                target_conflicts = self._stop_and_update_target_conflicts(target_conflicts, u, u_pos, u_target)
            elif u_target == v_target:
                # v wants to move and they have same target, then stop v, which has larger index (lower index wins)
                target_conflicts = self._stop_and_update_target_conflicts(target_conflicts, v, v_pos, v_target)
            # else: no conflict any more, forget
            target_conflicts = target_conflicts[1:]

    def _stop_and_update_target_conflicts(self, target_conflicts, v, v_pos, v_target):
        self.agents[v] = (v_pos, v_pos)
        self.stopped.add(v)
        # update target_conflicts and reverse_target
        if v_pos in self.reverse_target:
            target_conflicts += [(v, other) if v < other else (other, v) for other in self.reverse_target[v_pos] if other != v]
            self.reverse_target[v_pos].append(v)
        else:
            self.reverse_target[v_pos] = [v]
        self.reverse_target[v_target].remove(v)
        return target_conflicts

    def check_motion(self, i: int, r: Resource) -> bool:
        """
        Returns
            Will the agent move (either because it does not want to move or because it is stopped by conflict resolution)?
        """
        return i not in self.stopped
