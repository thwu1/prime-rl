"""
Flatland reference source: flatland.envs.rail_env_action

Defines the action space for the railway environment.
"""

# Action constants
DO_NOTHING = 0       # implies change of direction in a dead-end
MOVE_LEFT = 1
MOVE_FORWARD = 2
MOVE_RIGHT = 3
STOP_MOVING = 4


def is_moving_action(value: int) -> bool:
    return value in [MOVE_RIGHT, MOVE_LEFT, MOVE_FORWARD]
