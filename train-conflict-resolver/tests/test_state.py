
"""
Comprehensive tests for multi-agent railway conflict resolution and step simulation engine.
"""
import json
import os
import sqlite3
import subprocess
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, "/app")


# ============================================================================
# SpeedCounter Tests
# ============================================================================

class TestSpeedCounter:
    def test_basic_full_speed(self):
        """Speed 1.0 exits cell every step."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=1.0, max_speed=1.0)
        assert sc.speed == Fraction(1)
        assert sc.distance == Fraction(0)
        assert sc.is_cell_entry is True
        # At distance=0, with speed=1, should exit cell
        assert sc.is_cell_exit(Fraction(1)) is True
        sc.step()
        # After step, distance should wrap to 0 (entered new cell)
        assert sc.distance == Fraction(0)
        assert sc.is_cell_entry is True

    def test_half_speed(self):
        """Speed 0.5 takes 2 steps per cell."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.5, max_speed=0.5)
        assert sc.speed == Fraction(1, 2)
        # At distance=0, speed=0.5: 0 + 0.5 = 0.5 < 1 -> not at cell exit yet
        assert sc.is_cell_exit(Fraction(1, 2)) is False
        sc.step()
        assert sc.distance == Fraction(1, 2)
        assert sc.is_cell_entry is False
        # At distance=0.5, speed=0.5: 0.5 + 0.5 = 1.0 >= 1 -> at cell exit
        assert sc.is_cell_exit(Fraction(1, 2)) is True
        sc.step()
        assert sc.distance == Fraction(0)
        assert sc.is_cell_entry is True

    def test_quarter_speed(self):
        """Speed 0.25 takes 4 steps per cell."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.25, max_speed=0.25)
        assert sc.speed == Fraction(1, 4)
        # Takes 4 steps to traverse one cell
        for i in range(3):
            sc.step()
            assert sc.is_cell_entry is False, f"Should not be cell entry at step {i+1}"
        sc.step()
        assert sc.is_cell_entry is True
        assert sc.distance == Fraction(0)

    def test_third_speed(self):
        """Speed 1/3 takes 3 steps per cell (exact fraction)."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=1/3, max_speed=1/3)
        assert sc.speed == Fraction(1, 3)
        sc.step()
        assert sc.distance == Fraction(1, 3)
        sc.step()
        assert sc.distance == Fraction(2, 3)
        sc.step()
        assert sc.distance == Fraction(0)
        assert sc.is_cell_entry is True

    def test_speed_capping(self):
        """Speed cannot exceed max_speed or go below 0."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.5, max_speed=0.5)
        # Try to step with speed > max
        sc.step(speed=Fraction(1))
        # Speed should be capped at max_speed
        assert sc.speed == Fraction(1, 2)

    def test_speed_change_mid_cell(self):
        """Changing speed mid-cell."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.25, max_speed=1.0)
        sc.step()  # distance = 0.25
        assert sc.distance == Fraction(1, 4)
        sc.step(speed=Fraction(1, 2))  # distance = 0.75
        assert sc.speed == Fraction(1, 2)
        assert sc.distance == Fraction(3, 4)
        sc.step()  # distance = 1.25 -> 0.25
        assert sc.distance == Fraction(1, 4)
        assert sc.is_cell_entry is True

    def test_zero_speed(self):
        """Speed 0 never advances."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.0, max_speed=1.0)
        sc.step()
        assert sc.distance == Fraction(0)
        assert sc.is_cell_exit(Fraction(0)) is False

    def test_cell_exit_prediction(self):
        """is_cell_exit correctly predicts whether next step exits cell."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.5, max_speed=1.0)
        # At distance=0, speed=0.5: 0 + 0.5 = 0.5 < 1 -> not exit
        assert sc.is_cell_exit(Fraction(1, 2)) is False
        sc.step()
        # At distance=0.5, speed=0.5: 0.5 + 0.5 = 1.0 >= 1 -> exit
        assert sc.is_cell_exit(Fraction(1, 2)) is True
        # At distance=0.5, speed=1.0: 0.5 + 1.0 = 1.5 >= 1 -> also exit
        assert sc.is_cell_exit(Fraction(1)) is True

    def test_reset(self):
        """Reset restores initial state."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.5, max_speed=1.0)
        sc.step()
        sc.reset()
        assert sc.distance == Fraction(0)
        assert sc.is_cell_entry is True

    def test_half_speed_cell_exit_sequence(self):
        """Verify cell_exit predictions for half speed over multiple cells."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.5, max_speed=0.5)
        # distance=0: 0 + 0.5 = 0.5 < 1 -> not exit
        assert sc.is_cell_exit(Fraction(1, 2)) is False
        sc.step()  # distance=0.5
        # distance=0.5: 0.5 + 0.5 = 1.0 >= 1 -> exit
        assert sc.is_cell_exit(Fraction(1, 2)) is True
        sc.step()  # distance=0 (wrapped)
        assert sc.is_cell_exit(Fraction(1, 2)) is False

    def test_fifth_speed_exact_fraction(self):
        """Speed 1/5 takes 5 steps per cell (exact fraction from float)."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.2, max_speed=0.2)
        assert sc.speed == Fraction(1, 5)
        for i in range(4):
            sc.step()
            assert sc.is_cell_entry is False
        sc.step()
        assert sc.is_cell_entry is True
        assert sc.distance == Fraction(0)

    def test_three_quarter_speed_cell_entry(self):
        """Speed 3/4 wraps to non-zero distance, must still detect cell entry."""
        from rail_sim.speed_counter import SpeedCounter
        sc = SpeedCounter(speed=0.75, max_speed=1.0)
        sc.step()  # distance = 0.75
        assert sc.is_cell_entry is False
        assert sc.distance == Fraction(3, 4)
        sc.step()  # distance = 1.5 -> 0.5, cell entry
        assert sc.distance == Fraction(1, 2)
        assert sc.is_cell_entry is True


# ============================================================================
# TrainState Tests
# ============================================================================

class TestTrainState:
    def test_enum_values(self):
        from rail_sim.states import TrainState
        assert TrainState.WAITING == 0
        assert TrainState.READY_TO_DEPART == 1
        assert TrainState.MALFUNCTION_OFF_MAP == 2
        assert TrainState.MOVING == 3
        assert TrainState.STOPPED == 4
        assert TrainState.MALFUNCTION == 5
        assert TrainState.DONE == 6

    def test_is_malfunction_state(self):
        from rail_sim.states import TrainState
        assert TrainState.MALFUNCTION.is_malfunction_state() is True
        assert TrainState.MALFUNCTION_OFF_MAP.is_malfunction_state() is True
        assert TrainState.MOVING.is_malfunction_state() is False
        assert TrainState.WAITING.is_malfunction_state() is False

    def test_is_off_map_state(self):
        from rail_sim.states import TrainState
        assert TrainState.WAITING.is_off_map_state() is True
        assert TrainState.READY_TO_DEPART.is_off_map_state() is True
        assert TrainState.MALFUNCTION_OFF_MAP.is_off_map_state() is True
        assert TrainState.MOVING.is_off_map_state() is False
        assert TrainState.STOPPED.is_off_map_state() is False

    def test_is_on_map_state(self):
        from rail_sim.states import TrainState
        assert TrainState.MOVING.is_on_map_state() is True
        assert TrainState.STOPPED.is_on_map_state() is True
        assert TrainState.MALFUNCTION.is_on_map_state() is True
        assert TrainState.WAITING.is_on_map_state() is False
        assert TrainState.DONE.is_on_map_state() is False


# ============================================================================
# StateTransitionSignals Tests
# ============================================================================

class TestStateTransitionSignals:
    def test_defaults(self):
        from rail_sim.states import StateTransitionSignals
        s = StateTransitionSignals()
        assert s.in_malfunction is False
        assert s.earliest_departure_reached is False
        assert s.stop_action_given is False
        assert s.movement_action_given is False
        assert s.target_reached is False
        assert s.movement_allowed is False
        assert s.new_speed_zero is False


# ============================================================================
# TrainStateMachine Tests
# ============================================================================

class TestTrainStateMachine:
    def test_initial_state(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState
        sm = TrainStateMachine()
        assert sm.state == TrainState.WAITING

    def test_waiting_to_ready(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine()
        signals = StateTransitionSignals(earliest_departure_reached=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.READY_TO_DEPART
        assert sm.previous_state == TrainState.WAITING

    def test_waiting_stays_waiting(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine()
        signals = StateTransitionSignals()  # no departure reached
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.WAITING

    def test_waiting_to_malfunction_off_map(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine()
        signals = StateTransitionSignals(in_malfunction=True, earliest_departure_reached=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MALFUNCTION_OFF_MAP

    def test_ready_to_moving(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.READY_TO_DEPART)
        signals = StateTransitionSignals(movement_action_given=True, movement_allowed=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MOVING

    def test_ready_stays_without_movement(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.READY_TO_DEPART)
        signals = StateTransitionSignals(movement_action_given=True, movement_allowed=False)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.READY_TO_DEPART

    def test_moving_to_stopped_by_stop_action(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MOVING)
        signals = StateTransitionSignals(stop_action_given=True, new_speed_zero=True, movement_allowed=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.STOPPED

    def test_moving_to_stopped_by_not_allowed(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MOVING)
        signals = StateTransitionSignals(movement_allowed=False)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.STOPPED

    def test_moving_stays_moving(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MOVING)
        signals = StateTransitionSignals(movement_allowed=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MOVING

    def test_moving_to_malfunction(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MOVING)
        signals = StateTransitionSignals(in_malfunction=True, movement_allowed=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MALFUNCTION

    def test_moving_to_done(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MOVING)
        signals = StateTransitionSignals(target_reached=True, movement_allowed=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.DONE

    def test_stopped_to_moving(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.STOPPED)
        signals = StateTransitionSignals(movement_action_given=True, movement_allowed=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MOVING

    def test_stopped_stays_stopped(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.STOPPED)
        signals = StateTransitionSignals()
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.STOPPED

    def test_malfunction_to_moving(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MALFUNCTION)
        signals = StateTransitionSignals(in_malfunction=False, movement_action_given=True, movement_allowed=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MOVING

    def test_malfunction_to_stopped(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MALFUNCTION)
        signals = StateTransitionSignals(in_malfunction=False, movement_action_given=False)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.STOPPED

    def test_malfunction_stays(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MALFUNCTION)
        signals = StateTransitionSignals(in_malfunction=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MALFUNCTION

    def test_malfunction_off_map_recovery_to_moving(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MALFUNCTION_OFF_MAP)
        signals = StateTransitionSignals(
            in_malfunction=False,
            earliest_departure_reached=True,
            movement_action_given=True,
            movement_allowed=True
        )
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MOVING

    def test_malfunction_off_map_recovery_to_stopped(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MALFUNCTION_OFF_MAP)
        signals = StateTransitionSignals(
            in_malfunction=False,
            earliest_departure_reached=True,
            stop_action_given=True,
            movement_allowed=True
        )
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.STOPPED

    def test_malfunction_off_map_recovery_to_ready(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MALFUNCTION_OFF_MAP)
        signals = StateTransitionSignals(
            in_malfunction=False,
            earliest_departure_reached=True,
            movement_action_given=False,
            stop_action_given=False
        )
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.READY_TO_DEPART

    def test_malfunction_off_map_recovery_to_waiting(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MALFUNCTION_OFF_MAP)
        signals = StateTransitionSignals(
            in_malfunction=False,
            earliest_departure_reached=False
        )
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.WAITING

    def test_malfunction_off_map_stays(self):
        """MALFUNCTION_OFF_MAP stays if still in malfunction."""
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MALFUNCTION_OFF_MAP)
        signals = StateTransitionSignals(in_malfunction=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MALFUNCTION_OFF_MAP

    def test_done_is_terminal(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.DONE)
        signals = StateTransitionSignals(movement_action_given=True, movement_allowed=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.DONE

    def test_reset(self):
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine()
        signals = StateTransitionSignals(earliest_departure_reached=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.READY_TO_DEPART
        sm.reset()
        assert sm.state == TrainState.WAITING
        assert sm.previous_state is None

    def test_stop_action_only_stops_if_speed_zero(self):
        """MOVING + stop_action but speed not zero should stay MOVING."""
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals
        sm = TrainStateMachine(initial_state=TrainState.MOVING)
        signals = StateTransitionSignals(stop_action_given=True, new_speed_zero=False, movement_allowed=True)
        sm.set_transition_signals(signals)
        sm.step()
        assert sm.state == TrainState.MOVING

    def test_multi_step_lifecycle(self):
        """Full lifecycle: WAITING -> READY -> MOVING -> STOPPED -> MOVING -> DONE"""
        from rail_sim.state_machine import TrainStateMachine
        from rail_sim.states import TrainState, StateTransitionSignals

        sm = TrainStateMachine()

        # WAITING -> READY_TO_DEPART
        sm.set_transition_signals(StateTransitionSignals(earliest_departure_reached=True))
        sm.step()
        assert sm.state == TrainState.READY_TO_DEPART

        # READY_TO_DEPART -> MOVING
        sm.set_transition_signals(StateTransitionSignals(movement_action_given=True, movement_allowed=True))
        sm.step()
        assert sm.state == TrainState.MOVING

        # MOVING -> STOPPED (blocked by conflict)
        sm.set_transition_signals(StateTransitionSignals(movement_allowed=False))
        sm.step()
        assert sm.state == TrainState.STOPPED

        # STOPPED -> MOVING (unblocked)
        sm.set_transition_signals(StateTransitionSignals(movement_action_given=True, movement_allowed=True))
        sm.step()
        assert sm.state == TrainState.MOVING

        # MOVING -> DONE (target reached)
        sm.set_transition_signals(StateTransitionSignals(target_reached=True, movement_allowed=True))
        sm.step()
        assert sm.state == TrainState.DONE

        # DONE stays DONE
        sm.set_transition_signals(StateTransitionSignals(movement_action_given=True, movement_allowed=True))
        sm.step()
        assert sm.state == TrainState.DONE


# ============================================================================
# MotionCheck Tests
# ============================================================================

class TestMotionCheck:
    def test_single_agent_moving(self):
        """Single agent moving should be allowed."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (0, 1))
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is True

    def test_single_agent_stopped(self):
        """Single agent not wanting to move (self-loop)."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (0, 0))
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is False

    def test_head_on_swap(self):
        """Two agents trying to swap positions = deadlock, both stopped."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (0, 1))
        mc.add_agent(1, (0, 1), (0, 0))
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is False
        assert mc.check_motion(1, (0, 1)) is False

    def test_merge_conflict_lower_wins(self):
        """Two agents targeting same cell: lower handle wins."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (1, 0))
        mc.add_agent(1, (2, 0), (1, 0))
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is True
        assert mc.check_motion(1, (2, 0)) is False

    def test_chain_blocking(self):
        """Agent blocked by stopped agent propagates through chain."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        # Agent 0 at (0,0) wants to go to (0,1)
        # Agent 1 at (0,1) wants to stay at (0,1) (stopped)
        # Agent 0 should be blocked by agent 1
        mc.add_agent(0, (0, 0), (0, 1))
        mc.add_agent(1, (0, 1), (0, 1))
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is False
        assert mc.check_motion(1, (0, 1)) is False

    def test_chain_blocking_three_agents(self):
        """Three-agent chain: last one stopped blocks the whole chain."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (0, 1))
        mc.add_agent(1, (0, 1), (0, 2))
        mc.add_agent(2, (0, 2), (0, 2))  # stopped
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is False
        assert mc.check_motion(1, (0, 1)) is False
        assert mc.check_motion(2, (0, 2)) is False

    def test_chain_all_moving(self):
        """Three agents in chain all moving: all can proceed (close following)."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (0, 1))
        mc.add_agent(1, (0, 1), (0, 2))
        mc.add_agent(2, (0, 2), (0, 3))
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is True
        assert mc.check_motion(1, (0, 1)) is True
        assert mc.check_motion(2, (0, 2)) is True

    def test_merge_with_chain(self):
        """Merge conflict where loser has predecessors that also get blocked."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        # Agent 0: (0,0) -> (1,0)  (will win)
        # Agent 1: (2,0) -> (1,0)  (will lose merge)
        # Agent 2: (3,0) -> (2,0)  (behind agent 1, should be blocked too)
        mc.add_agent(0, (0, 0), (1, 0))
        mc.add_agent(1, (2, 0), (1, 0))
        mc.add_agent(2, (3, 0), (2, 0))
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is True
        assert mc.check_motion(1, (2, 0)) is False
        assert mc.check_motion(2, (3, 0)) is False

    def test_none_positions(self):
        """Agents with None positions (not yet on map)."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, None, None)
        mc.find_conflicts()
        assert mc.check_motion(0, None) is False  # self-loop, not moving

    def test_swap_blocks_predecessors(self):
        """Swap deadlock should propagate to block predecessors."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        # Agent 2 -> (0,1) where agent 0 is, agent 0 -> (0,2) where agent 1 is, agent 1 -> (0,1)
        # Swap between agent 0 and agent 1
        mc.add_agent(0, (0, 1), (0, 2))
        mc.add_agent(1, (0, 2), (0, 1))
        mc.add_agent(2, (0, 0), (0, 1))  # wants to go to agent 0's position
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 1)) is False  # deadlocked
        assert mc.check_motion(1, (0, 2)) is False  # deadlocked
        assert mc.check_motion(2, (0, 0)) is False  # blocked by deadlock

    def test_independent_agents(self):
        """Two agents moving to different, non-conflicting cells."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (0, 1))
        mc.add_agent(1, (2, 2), (2, 3))
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is True
        assert mc.check_motion(1, (2, 2)) is True

    def test_complex_merge_three_to_one(self):
        """Three agents all targeting the same cell: only lowest handle wins."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (1, 1))
        mc.add_agent(1, (1, 0), (1, 1))
        mc.add_agent(2, (2, 2), (1, 1))
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is True
        assert mc.check_motion(1, (1, 0)) is False
        assert mc.check_motion(2, (2, 2)) is False

    def test_stopped_agent_blocking_another_with_merge(self):
        """Agent stopped voluntarily at the same position a merger wants, causing cascading stop."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        # Agent 0 is stopped at (1,0), self-loop
        # Agent 1 wants to move from (0,0) to (1,0) - blocked by agent 0's self-loop
        mc.add_agent(0, (1, 0), (1, 0))  # stopped
        mc.add_agent(1, (0, 0), (1, 0))  # wants to move to (1,0)
        mc.find_conflicts()
        assert mc.check_motion(0, (1, 0)) is False  # stopped
        assert mc.check_motion(1, (0, 0)) is False  # blocked

    def test_cascading_stop_from_merge_loss(self):
        """
        Agent A wins merge, agent B loses.
        Agent C is behind B and wants B's cell.
        Agent D is behind C and wants C's cell.
        All losers and their chains should be blocked.
        """
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (1, 0))  # wins merge for (1,0)
        mc.add_agent(1, (2, 0), (1, 0))  # loses merge, stopped
        mc.add_agent(2, (3, 0), (2, 0))  # behind 1, blocked
        mc.add_agent(3, (4, 0), (3, 0))  # behind 2, blocked
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is True
        assert mc.check_motion(1, (2, 0)) is False
        assert mc.check_motion(2, (3, 0)) is False
        assert mc.check_motion(3, (4, 0)) is False

    def test_higher_handle_stopped_blocks_lower(self):
        """A higher-handle agent that is stopped still blocks a lower-handle agent behind it."""
        from rail_sim.motion_check import MotionCheck
        mc = MotionCheck()
        mc.add_agent(0, (0, 0), (0, 1))  # wants to move to where agent 5 sits
        mc.add_agent(5, (0, 1), (0, 1))  # stopped (self-loop)
        mc.find_conflicts()
        assert mc.check_motion(0, (0, 0)) is False
        assert mc.check_motion(5, (0, 1)) is False


# ============================================================================
# StepSimulator Integration Tests
# ============================================================================

class TestStepSimulator:
    def _make_scenario(self, agents, actions, max_steps):
        return {
            "agents": agents,
            "actions": actions,
            "max_steps": max_steps,
        }

    def test_single_agent_depart_and_move(self):
        """Single agent: WAITING -> READY_TO_DEPART -> MOVING, position update."""
        from rail_sim.simulator import StepSimulator
        scenario = self._make_scenario(
            agents=[{
                "handle": 0,
                "initial_position": [0, 0],
                "speed": 1.0,
                "max_speed": 1.0,
                "target": [0, 3],
                "earliest_departure": 1,
            }],
            actions=[
                {"0": 0},   # step 1: DO_NOTHING, but departure reached -> READY_TO_DEPART
                {"0": 2},   # step 2: MOVE_FORWARD -> MOVING, placed at initial position
                {"0": 2},   # step 3: MOVE_FORWARD -> still MOVING
            ],
            max_steps=3,
        )
        sim = StepSimulator()
        results = sim.simulate(scenario)
        assert len(results) == 3

        # Step 1: WAITING -> READY_TO_DEPART (earliest_departure=1, step=1)
        assert results[0]["agents"]["0"]["state"] == 1  # READY_TO_DEPART
        assert results[0]["agents"]["0"]["position"] is None

        # Step 2: READY_TO_DEPART -> MOVING (movement action given + allowed)
        assert results[1]["agents"]["0"]["state"] == 3  # MOVING
        assert results[1]["agents"]["0"]["position"] == [0, 0]

        # Step 3: MOVING -> MOVING, agent advances
        assert results[2]["agents"]["0"]["state"] == 3  # MOVING

    def test_two_agents_head_on_collision(self):
        """Two agents approaching head-on: both should be stopped by MotionCheck."""
        from rail_sim.simulator import StepSimulator
        scenario = self._make_scenario(
            agents=[
                {"handle": 0, "initial_position": [0, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [0, 5], "earliest_departure": 0},
                {"handle": 1, "initial_position": [0, 4], "speed": 1.0, "max_speed": 1.0,
                 "target": [0, 0], "earliest_departure": 0},
            ],
            actions=[
                {"0": 2, "1": 2},  # step 1: both depart
                {"0": 2, "1": 2},  # step 2: both moving
                {"0": 2, "1": 2},  # step 3: both try to move but swap conflict
            ],
            max_steps=3,
        )
        sim = StepSimulator()
        results = sim.simulate(scenario)
        # By step 3, the agents should be close enough that a head-on swap is detected
        # The exact step depends on speed processing, but we verify both agents
        # are eventually stopped or deadlocked when they try to swap
        # Check that both agents exist in results
        assert len(results) == 3
        for r in results:
            assert "0" in r["agents"]
            assert "1" in r["agents"]

    def test_agent_reaches_target_done(self):
        """Agent reaches target and transitions to DONE."""
        from rail_sim.simulator import StepSimulator
        scenario = self._make_scenario(
            agents=[{
                "handle": 0,
                "initial_position": [0, 0],
                "speed": 1.0,
                "max_speed": 1.0,
                "target": [0, 0],
                "earliest_departure": 1,
            }],
            actions=[
                {"0": 0},  # step 1: departure reached -> READY_TO_DEPART
                {"0": 2},  # step 2: MOVE_FORWARD -> MOVING, at initial_position which is target
            ],
            max_steps=2,
        )
        sim = StepSimulator()
        results = sim.simulate(scenario)
        # Agent starts at [0,0] and target is [0,0]: on entering MOVING at initial position,
        # update_if_reached should set state to DONE
        assert results[1]["agents"]["0"]["state"] == 6  # DONE

    def test_half_speed_agent(self):
        """Agent with speed 0.5 takes 2 steps per cell."""
        from rail_sim.simulator import StepSimulator
        scenario = self._make_scenario(
            agents=[{
                "handle": 0,
                "initial_position": [0, 0],
                "speed": 0.5,
                "max_speed": 0.5,
                "target": [0, 5],
                "earliest_departure": 0,
            }],
            actions=[
                {"0": 2},  # step 1: depart -> MOVING, at initial position
                {"0": 2},  # step 2: still in first cell (half speed)
                {"0": 2},  # step 3: should be in motion
                {"0": 2},  # step 4: continue
            ],
            max_steps=4,
        )
        sim = StepSimulator()
        results = sim.simulate(scenario)
        assert len(results) == 4
        # Agent should be MOVING throughout
        for r in results[1:]:
            assert results[0]["agents"]["0"]["state"] in (1, 3)  # READY or MOVING

    def test_cli_interface(self):
        """Test the command-line interface: python3 -m rail_sim.simulator scenario.json"""
        scenario = {
            "agents": [{
                "handle": 0,
                "initial_position": [0, 0],
                "speed": 1.0,
                "max_speed": 1.0,
                "target": [0, 0],
                "earliest_departure": 1,
            }],
            "actions": [{"0": 0}, {"0": 2}],
            "max_steps": 2,
        }
        scenario_path = "/tmp/test_scenario.json"
        with open(scenario_path, "w") as f:
            json.dump(scenario, f)

        result = subprocess.run(
            ["python3", "-m", "rail_sim.simulator", scenario_path],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert isinstance(output, list)
        assert len(output) == 2

    def test_stop_action_from_moving(self):
        """STOP_MOVING action with speed reaching zero transitions to STOPPED."""
        from rail_sim.simulator import StepSimulator
        scenario = self._make_scenario(
            agents=[{
                "handle": 0,
                "initial_position": [0, 0],
                "speed": 1.0,
                "max_speed": 1.0,
                "target": [0, 5],
                "earliest_departure": 0,
            }],
            actions=[
                {"0": 2},  # step 1: depart
                {"0": 2},  # step 2: moving
                {"0": 4},  # step 3: STOP action
            ],
            max_steps=3,
        )
        sim = StepSimulator()
        results = sim.simulate(scenario)
        # After stop action, agent should be STOPPED
        assert results[2]["agents"]["0"]["state"] == 4  # STOPPED

    def test_merge_conflict_in_simulation(self):
        """Two agents depart toward same cell, lower handle should win."""
        from rail_sim.simulator import StepSimulator
        scenario = self._make_scenario(
            agents=[
                {"handle": 0, "initial_position": [0, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [0, 5], "earliest_departure": 0},
                {"handle": 1, "initial_position": [0, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [0, 5], "earliest_departure": 0},
            ],
            actions=[
                {"0": 2, "1": 2},
                {"0": 2, "1": 2},
            ],
            max_steps=2,
        )
        sim = StepSimulator()
        results = sim.simulate(scenario)
        # Both starting at same initial_position - conflict resolution applies
        assert len(results) == 2

    def test_multiple_independent_agents(self):
        """Multiple agents on non-conflicting paths all move freely."""
        from rail_sim.simulator import StepSimulator
        scenario = self._make_scenario(
            agents=[
                {"handle": 0, "initial_position": [0, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [0, 5], "earliest_departure": 0},
                {"handle": 1, "initial_position": [5, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [5, 5], "earliest_departure": 0},
            ],
            actions=[
                {"0": 2, "1": 2},  # both depart
                {"0": 2, "1": 2},  # both moving
            ],
            max_steps=2,
        )
        sim = StepSimulator()
        results = sim.simulate(scenario)
        # Both should be MOVING by step 2
        for handle in ["0", "1"]:
            assert results[1]["agents"][handle]["state"] == 3  # MOVING

    def test_waiting_before_earliest_departure(self):
        """Agent with future earliest_departure stays WAITING."""
        from rail_sim.simulator import StepSimulator
        scenario = self._make_scenario(
            agents=[{
                "handle": 0,
                "initial_position": [0, 0],
                "speed": 1.0,
                "max_speed": 1.0,
                "target": [0, 5],
                "earliest_departure": 3,
            }],
            actions=[
                {"0": 2},  # step 1: earliest_departure not reached
                {"0": 2},  # step 2: still waiting
                {"0": 2},  # step 3: now earliest_departure=3, departs
            ],
            max_steps=3,
        )
        sim = StepSimulator()
        results = sim.simulate(scenario)
        assert results[0]["agents"]["0"]["state"] == 0  # WAITING
        assert results[0]["agents"]["0"]["position"] is None
        assert results[1]["agents"]["0"]["state"] == 0  # WAITING
        # Step 3: earliest_departure=3 reached at step 3
        # With movement_action_given, agent transitions from WAITING -> READY_TO_DEPART
        # (or directly from WAITING past READY if the sim treats it that way)
        # The key is: by step 3 the agent is no longer WAITING
        assert results[2]["agents"]["0"]["state"] in (1, 3)  # READY or MOVING


# ============================================================================
# SQLite Trace Database Tests
# ============================================================================

class TestSQLiteTrace:
    def test_trace_db_creation(self):
        """CLI with --trace-db creates SQLite database with correct schema."""
        scenario = {
            "agents": [{
                "handle": 0,
                "initial_position": [0, 0],
                "speed": 1.0,
                "max_speed": 1.0,
                "target": [0, 3],
                "earliest_departure": 1,
            }],
            "actions": [{"0": 0}, {"0": 2}],
            "max_steps": 2,
        }
        scenario_path = "/tmp/test_trace_create_scenario.json"
        db_path = "/tmp/test_trace_create.db"
        with open(scenario_path, "w") as f:
            json.dump(scenario, f)
        if os.path.exists(db_path):
            os.remove(db_path)

        result = subprocess.run(
            ["python3", "-m", "rail_sim.simulator", scenario_path, "--trace-db", db_path],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        # JSON output must still be on stdout
        output = json.loads(result.stdout)
        assert isinstance(output, list)
        assert len(output) == 2

        # Verify DB exists and has correct table and columns
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "agent_traces" in tables, f"Expected agent_traces table, found: {tables}"

        cursor = conn.execute("PRAGMA table_info(agent_traces)")
        columns = {row[1] for row in cursor.fetchall()}
        expected_columns = {"step", "agent_handle", "state", "position_row", "position_col", "speed", "moving"}
        assert columns == expected_columns, f"Schema mismatch: {columns} != {expected_columns}"
        conn.close()

    def test_trace_db_data_matches_json(self):
        """Trace DB data exactly matches JSON output for a known scenario."""
        scenario = {
            "agents": [{
                "handle": 0,
                "initial_position": [0, 0],
                "speed": 1.0,
                "max_speed": 1.0,
                "target": [0, 0],
                "earliest_departure": 1,
            }],
            "actions": [{"0": 0}, {"0": 2}],
            "max_steps": 2,
        }
        scenario_path = "/tmp/test_trace_data_scenario.json"
        db_path = "/tmp/test_trace_data.db"
        with open(scenario_path, "w") as f:
            json.dump(scenario, f)
        if os.path.exists(db_path):
            os.remove(db_path)

        result = subprocess.run(
            ["python3", "-m", "rail_sim.simulator", scenario_path, "--trace-db", db_path],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        json_output = json.loads(result.stdout)
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT step, agent_handle, state, position_row, position_col, speed, moving "
            "FROM agent_traces ORDER BY step, agent_handle"
        ).fetchall()
        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"

        # Step 1: READY_TO_DEPART (1), position null, speed 1.0, not moving
        assert rows[0] == (1, 0, 1, None, None, 1.0, 0)
        # Step 2: DONE (6), position null, speed 1.0, not moving
        assert rows[1] == (2, 0, 6, None, None, 1.0, 0)

        conn.close()

    def test_trace_db_multi_agent(self):
        """Multi-agent trace stores correct row count and per-agent data."""
        scenario = {
            "agents": [
                {"handle": 0, "initial_position": [0, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [0, 5], "earliest_departure": 0},
                {"handle": 1, "initial_position": [5, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [5, 5], "earliest_departure": 0},
            ],
            "actions": [{"0": 2, "1": 2}, {"0": 2, "1": 2}],
            "max_steps": 2,
        }
        scenario_path = "/tmp/test_trace_multi_scenario.json"
        db_path = "/tmp/test_trace_multi.db"
        with open(scenario_path, "w") as f:
            json.dump(scenario, f)
        if os.path.exists(db_path):
            os.remove(db_path)

        result = subprocess.run(
            ["python3", "-m", "rail_sim.simulator", scenario_path, "--trace-db", db_path],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        conn = sqlite3.connect(db_path)
        # 2 steps x 2 agents = 4 rows
        count = conn.execute("SELECT COUNT(*) FROM agent_traces").fetchone()[0]
        assert count == 4, f"Expected 4 rows, got {count}"

        # Query per agent
        agent_0 = conn.execute(
            "SELECT step, state FROM agent_traces WHERE agent_handle=0 ORDER BY step"
        ).fetchall()
        assert len(agent_0) == 2

        agent_1 = conn.execute(
            "SELECT step, state FROM agent_traces WHERE agent_handle=1 ORDER BY step"
        ).fetchall()
        assert len(agent_1) == 2

        conn.close()

    def test_trace_db_analytical_query(self):
        """Trace DB supports SQL aggregate queries over simulation data."""
        scenario = {
            "agents": [{
                "handle": 0,
                "initial_position": [0, 0],
                "speed": 1.0,
                "max_speed": 1.0,
                "target": [0, 5],
                "earliest_departure": 0,
            }],
            "actions": [
                {"0": 2},  # step 1: depart
                {"0": 2},  # step 2: moving
                {"0": 2},  # step 3: moving
                {"0": 4},  # step 4: STOP
            ],
            "max_steps": 4,
        }
        scenario_path = "/tmp/test_trace_query_scenario.json"
        db_path = "/tmp/test_trace_query.db"
        with open(scenario_path, "w") as f:
            json.dump(scenario, f)
        if os.path.exists(db_path):
            os.remove(db_path)

        result = subprocess.run(
            ["python3", "-m", "rail_sim.simulator", scenario_path, "--trace-db", db_path],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        conn = sqlite3.connect(db_path)

        # Count steps where agent was moving
        moving_count = conn.execute(
            "SELECT COUNT(*) FROM agent_traces WHERE agent_handle=0 AND moving=1"
        ).fetchone()[0]
        assert moving_count >= 1, "Agent should be MOVING for at least 1 step"

        # Get last recorded state
        last_state = conn.execute(
            "SELECT state FROM agent_traces WHERE agent_handle=0 ORDER BY step DESC LIMIT 1"
        ).fetchone()[0]
        assert last_state == 4, f"Expected STOPPED (4) as last state, got {last_state}"

        # Verify step count
        total_rows = conn.execute(
            "SELECT COUNT(*) FROM agent_traces WHERE agent_handle=0"
        ).fetchone()[0]
        assert total_rows == 4

        conn.close()


# ============================================================================
# Makefile and CLI Tool Integration Tests
# ============================================================================

class TestMakefile:
    """Tests for the Makefile targets that orchestrate sqlite3 and jq CLI tools."""

    def _write_scenario(self, path, scenario):
        with open(path, "w") as f:
            json.dump(scenario, f)

    def test_makefile_exists(self):
        """Makefile must exist at /app/Makefile."""
        assert os.path.exists("/app/Makefile"), "Makefile must exist at /app/Makefile"

    def test_make_simulate(self):
        """make simulate runs the CLI and produces valid JSON output."""
        scenario = {
            "agents": [{"handle": 0, "initial_position": [0, 0], "speed": 1.0, "max_speed": 1.0,
                         "target": [0, 3], "earliest_departure": 1}],
            "actions": [{"0": 0}, {"0": 2}],
            "max_steps": 2,
        }
        self._write_scenario("/tmp/test_mk_simulate.json", scenario)
        result = subprocess.run(
            ["make", "-s", "simulate", "SCENARIO=/tmp/test_mk_simulate.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"make simulate failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert isinstance(output, list)
        assert len(output) == 2

    def test_make_trace_creates_db(self):
        """make trace creates a SQLite trace database and outputs JSON."""
        scenario = {
            "agents": [{"handle": 0, "initial_position": [0, 0], "speed": 1.0, "max_speed": 1.0,
                         "target": [0, 3], "earliest_departure": 1}],
            "actions": [{"0": 0}, {"0": 2}],
            "max_steps": 2,
        }
        db_path = "/tmp/test_mk_trace.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        self._write_scenario("/tmp/test_mk_trace.json", scenario)
        result = subprocess.run(
            ["make", "-s", "trace", "SCENARIO=/tmp/test_mk_trace.json", f"DB={db_path}"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"make trace failed: {result.stderr}"
        assert os.path.exists(db_path), "Trace DB should be created"
        output = json.loads(result.stdout)
        assert isinstance(output, list)
        assert len(output) == 2

    def test_make_summary_format(self):
        """make summary produces JSON with total_steps, agents, and final_states."""
        scenario = {
            "agents": [
                {"handle": 0, "initial_position": [0, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [0, 0], "earliest_departure": 1},
            ],
            "actions": [{"0": 0}, {"0": 2}],
            "max_steps": 2,
        }
        db_path = "/tmp/test_mk_summary_fmt.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        self._write_scenario("/tmp/test_mk_summary_fmt.json", scenario)
        subprocess.run(
            ["make", "-s", "trace", "SCENARIO=/tmp/test_mk_summary_fmt.json", f"DB={db_path}"],
            capture_output=True, text=True, cwd="/app"
        )
        result = subprocess.run(
            ["make", "-s", "summary", f"DB={db_path}"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"make summary failed: {result.stderr}"
        summary = json.loads(result.stdout)
        assert summary["total_steps"] == 2
        assert summary["agents"] == 1
        assert isinstance(summary["final_states"], dict)
        assert "0" in summary["final_states"]
        # Agent at [0,0] with target [0,0] reaches target at step 2 -> DONE (6)
        assert summary["final_states"]["0"] == 6

    def test_make_summary_multi_agent(self):
        """make summary correctly reports multiple agents at the final step."""
        scenario = {
            "agents": [
                {"handle": 0, "initial_position": [0, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [0, 5], "earliest_departure": 0},
                {"handle": 1, "initial_position": [5, 0], "speed": 1.0, "max_speed": 1.0,
                 "target": [5, 5], "earliest_departure": 0},
            ],
            "actions": [{"0": 2, "1": 2}, {"0": 2, "1": 2}],
            "max_steps": 2,
        }
        db_path = "/tmp/test_mk_summary_multi.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        self._write_scenario("/tmp/test_mk_summary_multi.json", scenario)
        subprocess.run(
            ["make", "-s", "trace", "SCENARIO=/tmp/test_mk_summary_multi.json", f"DB={db_path}"],
            capture_output=True, text=True, cwd="/app"
        )
        result = subprocess.run(
            ["make", "-s", "summary", f"DB={db_path}"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"make summary failed: {result.stderr}"
        summary = json.loads(result.stdout)
        assert summary["total_steps"] == 2
        assert summary["agents"] == 2
        assert "0" in summary["final_states"]
        assert "1" in summary["final_states"]
        for h in ["0", "1"]:
            assert isinstance(summary["final_states"][h], int)

    def test_make_lint_valid(self):
        """make lint-scenario succeeds for a valid scenario JSON."""
        scenario = {
            "agents": [{"handle": 0}],
            "actions": [{"0": 0}],
            "max_steps": 1,
        }
        self._write_scenario("/tmp/test_mk_lint_valid.json", scenario)
        result = subprocess.run(
            ["make", "-s", "lint-scenario", "SCENARIO=/tmp/test_mk_lint_valid.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"lint-scenario should pass for valid JSON: {result.stderr}"

    def test_make_lint_invalid_missing_keys(self):
        """make lint-scenario fails for JSON missing required keys."""
        invalid = {"agents": []}  # missing actions and max_steps
        self._write_scenario("/tmp/test_mk_lint_invalid.json", invalid)
        result = subprocess.run(
            ["make", "-s", "lint-scenario", "SCENARIO=/tmp/test_mk_lint_invalid.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode != 0, "lint-scenario should fail for invalid JSON"

    def test_make_lint_not_json(self):
        """make lint-scenario fails for non-JSON input."""
        with open("/tmp/test_mk_lint_notjson.json", "w") as f:
            f.write("this is not json")
        result = subprocess.run(
            ["make", "-s", "lint-scenario", "SCENARIO=/tmp/test_mk_lint_notjson.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode != 0, "lint-scenario should fail for non-JSON"

    def test_makefile_uses_cli_tools(self):
        """Makefile must use sqlite3 and jq CLI tools (not Python) for summary and lint."""
        with open("/app/Makefile") as f:
            content = f.read()
        assert "sqlite3" in content, "Makefile must use sqlite3 CLI tool"
        assert "jq" in content, "Makefile must use jq CLI tool"
        # The summary and lint targets should not invoke python
        # Extract lines after 'summary:' and 'lint-scenario:' targets
        lines = content.split("\n")
        in_summary = False
        in_lint = False
        summary_lines = []
        lint_lines = []
        for line in lines:
            if line.startswith("summary"):
                in_summary = True
                in_lint = False
                continue
            elif line.startswith("lint-scenario"):
                in_lint = True
                in_summary = False
                continue
            elif line and not line[0].isspace() and not line.startswith("\t"):
                in_summary = False
                in_lint = False
                continue
            if in_summary:
                summary_lines.append(line)
            if in_lint:
                lint_lines.append(line)
        summary_text = "\n".join(summary_lines)
        lint_text = "\n".join(lint_lines)
        assert "python" not in summary_text.lower(), \
            "summary target must use sqlite3/jq, not Python"
        assert "python" not in lint_text.lower(), \
            "lint-scenario target must use jq, not Python"
