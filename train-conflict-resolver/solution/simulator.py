
"""
Multi-agent railway step simulator integrating SpeedCounter, TrainStateMachine, and MotionCheck.
"""

import json
import sys
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from rail_sim.states import TrainState, StateTransitionSignals
from rail_sim.speed_counter import SpeedCounter
from rail_sim.state_machine import TrainStateMachine
from rail_sim.motion_check import MotionCheck


# Action constants matching Flatland RailEnvActions
DO_NOTHING = 0
MOVE_LEFT = 1
MOVE_FORWARD = 2
MOVE_RIGHT = 3
STOP_MOVING = 4


def _is_moving_action(action: int) -> bool:
    return action in (MOVE_LEFT, MOVE_FORWARD, MOVE_RIGHT)


class AgentState:
    """Tracks full state of a single agent during simulation."""

    def __init__(self, handle: int, initial_position: Tuple[int, int],
                 speed: float, max_speed: float,
                 target: Tuple[int, int], earliest_departure: int):
        self.handle = handle
        self.initial_position = tuple(initial_position)
        self.position: Optional[Tuple[int, int]] = None
        self.old_position: Optional[Tuple[int, int]] = None
        self.speed_counter = SpeedCounter(speed=speed, max_speed=max_speed)
        self.state_machine = TrainStateMachine(initial_state=TrainState.WAITING)
        self.target = tuple(target)
        self.targets = {((target[0], target[1]), 0)}  # set of (position, direction) tuples
        # For simplicity, target is reached if position matches regardless of direction
        self.earliest_departure = earliest_departure

    @property
    def state(self) -> TrainState:
        return self.state_machine.state


class StepSimulator:
    """
    Simulates multi-agent railway steps with conflict resolution.
    """

    def simulate(self, scenario: dict) -> List[dict]:
        """
        Run the simulation for max_steps, applying actions each step.

        Returns a list of per-step result dictionaries.
        """
        agents_data = scenario["agents"]
        actions_list = scenario["actions"]
        max_steps = scenario["max_steps"]

        # Initialize agents
        agents: Dict[int, AgentState] = {}
        for ad in agents_data:
            a = AgentState(
                handle=ad["handle"],
                initial_position=ad["initial_position"],
                speed=ad["speed"],
                max_speed=ad["max_speed"],
                target=ad["target"],
                earliest_departure=ad["earliest_departure"],
            )
            agents[a.handle] = a

        results = []
        for step_idx in range(max_steps):
            step_num = step_idx + 1  # 1-indexed steps

            # Get actions for this step
            if step_idx < len(actions_list):
                step_actions = actions_list[step_idx]
            else:
                step_actions = {}

            # Phase 1: Compute independent transitions for each agent
            motion_check = MotionCheck()
            transition_data: Dict[int, dict] = {}

            for handle, agent in agents.items():
                raw_action = step_actions.get(str(handle), DO_NOTHING)

                stop_action_given = (raw_action == STOP_MOVING)
                movement_action_given = _is_moving_action(raw_action)
                earliest_departure_reached = (step_num >= agent.earliest_departure)
                state = agent.state

                new_speed = agent.speed_counter.speed

                # Compute new speed based on action
                if state == TrainState.STOPPED and movement_action_given:
                    new_speed = agent.speed_counter.max_speed
                elif state == TrainState.MOVING and stop_action_given:
                    new_speed = Fraction(0)
                elif state == TrainState.MOVING and movement_action_given:
                    new_speed = agent.speed_counter.max_speed

                # Determine desired new position
                new_position = None
                current_resource = agent.position
                new_resource = None

                if state == TrainState.READY_TO_DEPART and movement_action_given:
                    new_position = agent.initial_position
                    new_resource = agent.initial_position
                elif state.is_on_map_state():
                    new_position = agent.position
                    new_resource = agent.position
                    # For simplicity in this simulator, agents move forward along a row
                    # At cell exit, compute next position
                    can_move = (
                        state == TrainState.MOVING and not (stop_action_given and new_speed == 0)
                        and not False  # not in malfunction
                    )
                    can_move = can_move or (state == TrainState.STOPPED and movement_action_given)
                    can_move = can_move and not False  # not in malfunction

                    if agent.speed_counter.is_cell_exit(new_speed) and can_move:
                        # Move to next cell (advance column by 1 for simplicity)
                        r, c = agent.position
                        new_position = (r, c + 1)
                        new_resource = new_position
                elif state.is_off_map_state() or state == TrainState.DONE:
                    new_position = None
                    new_resource = None

                action_valid = True  # simplified: all actions are valid in this abstract sim

                transition_data[handle] = {
                    "new_position": new_position,
                    "new_speed": new_speed,
                    "stop_action_given": stop_action_given,
                    "movement_action_given": movement_action_given,
                    "earliest_departure_reached": earliest_departure_reached,
                    "action_valid": action_valid,
                    "current_resource": current_resource,
                    "new_resource": new_resource,
                }

                # Add to motion check
                motion_check.add_agent(handle, current_resource, new_resource)

            # Phase 2: Find and resolve conflicts
            motion_check.find_conflicts()

            # Phase 3: Apply state transitions and position updates
            step_result = {"step": step_num, "agents": {}}

            for handle, agent in agents.items():
                td = transition_data[handle]
                state = agent.state

                # Check motion result
                can_move = motion_check.check_motion(handle, td["current_resource"])

                # Determine movement_allowed
                action_valid = td["action_valid"]
                if state.is_on_map_state() and not agent.speed_counter.is_cell_exit(td["new_speed"]):
                    # Inside cell, not at exit yet - movement is allowed (no conflict check needed)
                    movement_allowed = action_valid
                else:
                    movement_allowed = action_valid and can_move

                # Build state transition signals
                signals = StateTransitionSignals(
                    in_malfunction=False,
                    earliest_departure_reached=td["earliest_departure_reached"],
                    stop_action_given=td["stop_action_given"],
                    movement_action_given=td["movement_action_given"],
                    target_reached=False,  # checked after position update
                    movement_allowed=movement_allowed,
                    new_speed_zero=(td["new_speed"] == 0),
                )

                # Step the state machine
                agent.state_machine.set_transition_signals(signals)
                agent.old_position = agent.position
                agent.state_machine.step()

                # Position and speed update based on new state
                if agent.state == TrainState.MOVING:
                    agent.position = td["new_position"]
                    # Speed counter step (skip on first step after depart)
                    prev = agent.state_machine.previous_state
                    if prev not in (TrainState.READY_TO_DEPART, TrainState.MALFUNCTION_OFF_MAP):
                        agent.speed_counter.step(speed=td["new_speed"])
                    # Check if target reached
                    if agent.position == agent.target:
                        agent.state_machine.update_if_reached(
                            agent.position,
                            {agent.target}
                        )
                elif agent.state_machine.previous_state == TrainState.MALFUNCTION_OFF_MAP and agent.state == TrainState.STOPPED:
                    agent.position = agent.initial_position

                # If on map and not MOVING, step speed counter with 0
                if agent.state.is_on_map_state() and agent.state != TrainState.MOVING:
                    agent.speed_counter.step(speed=Fraction(0))

                # Handle DONE: clear position
                if agent.state == TrainState.DONE:
                    agent.position = None

                # Record result
                pos = list(agent.position) if agent.position is not None else None
                step_result["agents"][str(handle)] = {
                    "state": int(agent.state),
                    "position": pos,
                    "speed": float(agent.speed_counter.speed),
                    "moving": agent.state == TrainState.MOVING,
                }

            results.append(step_result)

        return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Rail simulation CLI")
    parser.add_argument("scenario", help="Path to scenario JSON file")
    parser.add_argument("--trace-db", default=None, help="Path to SQLite trace database")
    args = parser.parse_args()

    with open(args.scenario) as f:
        scenario = json.load(f)

    sim = StepSimulator()
    results = sim.simulate(scenario)
    print(json.dumps(results, indent=2))

    if args.trace_db:
        from rail_sim.trace import write_trace
        write_trace(args.trace_db, results)


if __name__ == "__main__":
    main()
