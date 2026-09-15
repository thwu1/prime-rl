
from rail_sim.states import TrainState, StateTransitionSignals


class TrainStateMachine:
    def __init__(self, initial_state=TrainState.WAITING):
        self._initial_state = initial_state
        self._state = initial_state
        self._st_signals = StateTransitionSignals()
        self._next_state = None
        self._previous_state = None

    @property
    def state(self) -> TrainState:
        return self._state

    @property
    def previous_state(self):
        return self._previous_state

    def set_transition_signals(self, signals: StateTransitionSignals):
        self._st_signals = signals

    def step(self):
        """Compute and apply the next state based on current state and signals."""
        current = self._state
        self._next_state = None
        self._calculate_next_state(current)
        self._previous_state = self._state
        self._state = self._next_state

    def reset(self):
        self._state = self._initial_state
        self._previous_state = None
        self._st_signals = StateTransitionSignals()
        self._next_state = None

    def update_if_reached(self, position, targets):
        """Check if agent has reached target and transition to DONE if so."""
        if position in targets:
            self._next_state = TrainState.DONE
            self._previous_state = self._state
            self._state = TrainState.DONE

    def _calculate_next_state(self, current_state):
        s = self._st_signals

        if current_state == TrainState.WAITING:
            if s.in_malfunction:
                self._next_state = TrainState.MALFUNCTION_OFF_MAP
            elif s.earliest_departure_reached:
                self._next_state = TrainState.READY_TO_DEPART
            else:
                self._next_state = TrainState.WAITING

        elif current_state == TrainState.READY_TO_DEPART:
            if s.in_malfunction:
                self._next_state = TrainState.MALFUNCTION_OFF_MAP
            elif s.movement_action_given and s.movement_allowed:
                self._next_state = TrainState.MOVING
            else:
                self._next_state = TrainState.READY_TO_DEPART

        elif current_state == TrainState.MALFUNCTION_OFF_MAP:
            if not s.in_malfunction:
                if s.earliest_departure_reached:
                    if s.movement_action_given and s.movement_allowed:
                        self._next_state = TrainState.MOVING
                    elif s.stop_action_given and s.movement_allowed:
                        self._next_state = TrainState.STOPPED
                    else:
                        self._next_state = TrainState.READY_TO_DEPART
                else:
                    self._next_state = TrainState.WAITING
            else:
                self._next_state = TrainState.MALFUNCTION_OFF_MAP

        elif current_state == TrainState.MOVING:
            if s.in_malfunction:
                self._next_state = TrainState.MALFUNCTION
            elif s.target_reached:
                self._next_state = TrainState.DONE
            elif (s.stop_action_given and s.new_speed_zero) or not s.movement_allowed:
                self._next_state = TrainState.STOPPED
            else:
                self._next_state = TrainState.MOVING

        elif current_state == TrainState.STOPPED:
            if s.in_malfunction:
                self._next_state = TrainState.MALFUNCTION
            elif s.movement_action_given and s.movement_allowed:
                self._next_state = TrainState.MOVING
            else:
                self._next_state = TrainState.STOPPED

        elif current_state == TrainState.MALFUNCTION:
            if not s.in_malfunction:
                if s.movement_action_given and s.movement_allowed:
                    self._next_state = TrainState.MOVING
                else:
                    self._next_state = TrainState.STOPPED
            else:
                self._next_state = TrainState.MALFUNCTION

        elif current_state == TrainState.DONE:
            self._next_state = TrainState.DONE

        else:
            raise ValueError(f"Unexpected state {current_state}")
