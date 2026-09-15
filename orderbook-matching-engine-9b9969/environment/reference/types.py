# Exchange enumeration types
#
# These types define the core trading primitives used throughout the
# exchange implementation.

import enum


class Side(enum.IntEnum):
    SELL = 0
    BUY = 1


class Lifespan(enum.IntEnum):
    FILL_AND_KILL = 0   # Trade immediately if possible, otherwise cancel
    GOOD_FOR_DAY = 1    # Remain in book until filled or explicitly cancelled
