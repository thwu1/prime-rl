
from dataclasses import dataclass, field
from enum import IntEnum


class TrainState(IntEnum):
    WAITING = 0
    READY_TO_DEPART = 1
    MALFUNCTION_OFF_MAP = 2
    MOVING = 3
    STOPPED = 4
    MALFUNCTION = 5
    DONE = 6

    def is_malfunction_state(self) -> bool:
        return self.value in (TrainState.MALFUNCTION, TrainState.MALFUNCTION_OFF_MAP)

    def is_off_map_state(self) -> bool:
        return self.value in (TrainState.WAITING, TrainState.READY_TO_DEPART, TrainState.MALFUNCTION_OFF_MAP)

    def is_on_map_state(self) -> bool:
        return self.value in (TrainState.MOVING, TrainState.STOPPED, TrainState.MALFUNCTION)


@dataclass
class StateTransitionSignals:
    in_malfunction: bool = False
    earliest_departure_reached: bool = False
    stop_action_given: bool = False
    movement_action_given: bool = False
    target_reached: bool = False
    movement_allowed: bool = False
    new_speed_zero: bool = False
