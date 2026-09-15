#!/usr/bin/env python3
"""
Exhaustive state space explorer for dual-channel pilot flying protocols.
Translates PVS LLR specifications into Python models and performs
BFS-based model checking of safety requirements R1-R5.

"""
import json
from collections import deque
from itertools import product


# ======================================================================
# SYNCHRONOUS PROTOCOL MODEL
# From PVS: Side_LLR (2-state), Bus_LLR (boolean), Pilot_Flying_System
# ======================================================================

class SyncModel:
    """
    State representation:
      side = (pilot_flying: bool, pre_ts: bool, pre_ospf: bool)
      bus = bool
      system = (left_side, lr_bus, right_side, rl_bus, pre_ts)
    """

    @staticmethod
    def side_initial(primary):
        return (primary, True, not primary)

    @staticmethod
    def side_next(side, ts, ospf):
        pf, pre_ts, pre_ospf = side
        rise_ts = (not pre_ts) and ts
        rise_ospf = (not pre_ospf) and ospf
        if pf and rise_ospf:
            next_pf = False
        elif (not pf) and rise_ts:
            next_pf = True
        else:
            next_pf = pf
        return (next_pf, ts, ospf)

    @staticmethod
    def side_pilot_flying(side):
        return side[0]

    @staticmethod
    def initial_state():
        return (
            SyncModel.side_initial(True),   # Left (primary)
            True,                           # LR Bus
            SyncModel.side_initial(False),  # Right
            False,                          # RL Bus
            True,                           # pre_TS
        )

    @staticmethod
    def next_state(state, ts):
        left, lr, right, rl, pre_ts = state

        # C1 = Left pilot_flying output → LR Bus → C2
        c1 = SyncModel.side_pilot_flying(left)
        next_lr = c1  # Bus: next_state(_, input) = input
        c2 = next_lr  # Bus: output(state) = state

        # Right side processes TS and C2 (other side PF status)
        next_right = SyncModel.side_next(right, ts, c2)

        # C3 = Right pilot_flying output → RL Bus → C4
        c3 = SyncModel.side_pilot_flying(right)
        next_rl = c3
        c4 = next_rl

        # Left side processes TS and C4
        next_left = SyncModel.side_next(left, ts, c4)

        return (next_left, next_lr, next_right, next_rl, ts)

    @staticmethod
    def left_pf(state):
        return SyncModel.side_pilot_flying(state[0])

    @staticmethod
    def right_pf(state):
        return SyncModel.side_pilot_flying(state[2])

    @staticmethod
    def pressed(ts, state):
        return (not state[4]) and ts

    @staticmethod
    def switching_sides(state):
        left, lr, right, rl, pre_ts = state
        return (SyncModel.side_pilot_flying(left) and not lr) or \
               (SyncModel.side_pilot_flying(right) and not rl)


def sync_reachable_states():
    initial = SyncModel.initial_state()
    visited = {initial}
    queue = deque([initial])
    while queue:
        s = queue.popleft()
        for ts in (True, False):
            ns = SyncModel.next_state(s, ts)
            if ns not in visited:
                visited.add(ns)
                queue.append(ns)
    return visited


def check_sync_requirements(states):
    results = {}
    initial = SyncModel.initial_state()

    # R1: At least one side pilot flying
    results['R1'] = all(
        SyncModel.left_pf(s) or SyncModel.right_pf(s) for s in states
    )

    # R2: At most one PF except when switching
    results['R2'] = all(
        SyncModel.switching_sides(s) or
        (SyncModel.left_pf(s) != SyncModel.right_pf(s))
        for s in states
    )

    # R3a/R3b: Switch press changes PF side
    r3a = r3b = True
    # R5a/R5b: No change without press and not switching
    r5a = r5b = True
    for s in states:
        for ts in (True, False):
            ns = SyncModel.next_state(s, ts)
            pr = SyncModel.pressed(ts, s)
            sw = SyncModel.switching_sides(s)

            if (not SyncModel.left_pf(s)) and pr:
                if not SyncModel.left_pf(ns):
                    r3a = False
            if (not SyncModel.right_pf(s)) and pr:
                if not SyncModel.right_pf(ns):
                    r3b = False
            if (not sw) and (not pr):
                if SyncModel.left_pf(ns) != SyncModel.left_pf(s):
                    r5a = False
                if SyncModel.right_pf(ns) != SyncModel.right_pf(s):
                    r5b = False

    results['R3a'] = r3a
    results['R3b'] = r3b
    results['R4'] = SyncModel.left_pf(initial)
    results['R5a'] = r5a
    results['R5b'] = r5b

    # Reachable_States_Valid
    valid = True
    for s in states:
        left, lr, right, rl, pre_ts = s
        # Pre_TS_Consistency
        if left[1] != pre_ts or right[1] != pre_ts:
            valid = False; break
        # Pre_OSPF_Consistency
        if right[2] != lr:
            valid = False; break
        if left[2] != rl:
            valid = False; break
        # At_Least_One_Side_Flying
        if not (SyncModel.left_pf(s) or SyncModel.right_pf(s)):
            valid = False; break
        # Buses_Differ_When_Sides_Same
        if SyncModel.side_pilot_flying(left) == SyncModel.side_pilot_flying(right):
            if lr == rl:
                valid = False; break
    results['Reachable_States_Valid'] = valid

    # Switching_Transient
    swt = True
    for s in states:
        if SyncModel.switching_sides(s):
            for ts in (True, False):
                if SyncModel.switching_sides(SyncModel.next_state(s, ts)):
                    swt = False
                    break
        if not swt:
            break
    results['Switching_Transient'] = swt

    return results


# ======================================================================
# ASYNCHRONOUS PROTOCOL MODEL
# From PVS: Side_LLR (4-state handshake), Bus_LLR (Message),
#            Pilot_Flying_System with independent clocks
# ======================================================================

# Side states
CONFIRMED = 0
INHIBITED = 1
LISTENING = 2
WAITING = 3


class AsyncModel:
    """
    State representation:
      message = (pfs: bool, ack: bool)
      side = (st: int{0-3}, pre_ts: bool, pre_msg: message)
      bus = message
      system = (left_side, lr_bus, right_side, rl_bus, pre_ts)
    """

    @staticmethod
    def side_initial(primary):
        st = CONFIRMED if primary else LISTENING
        pre_ts = True
        pre_msg = (not primary, True)  # Msg(NOT Primary_Side, TRUE)
        return (st, pre_ts, pre_msg)

    @staticmethod
    def side_next(side, clk, ts, m):
        if not clk:
            return side
        st, pre_ts, pre_msg = side

        rise_ospf = (not pre_msg[0]) and m[0]
        rise_ts = (not pre_ts) and ts
        fall_ack = pre_msg[1] and (not m[1])

        if st == CONFIRMED and rise_ospf:
            next_st = INHIBITED
        elif st == INHIBITED and m[1]:  # ack(m)
            next_st = LISTENING
        elif st == LISTENING and rise_ts:
            next_st = WAITING
        elif st == WAITING and fall_ack:
            next_st = CONFIRMED
        else:
            next_st = st

        return (next_st, ts, m)

    @staticmethod
    def side_output(side):
        st = side[0]
        pfs = (st == CONFIRMED) or (st == WAITING)
        ack = (st == CONFIRMED) or (st == LISTENING)
        return (pfs, ack)

    @staticmethod
    def initial_state():
        return (
            AsyncModel.side_initial(True),    # Left (primary)
            (True, True),                     # LR Bus = Msg(True, True)
            AsyncModel.side_initial(False),   # Right
            (False, True),                    # RL Bus = Msg(False, True)
            True,                             # pre_TS
        )

    @staticmethod
    def next_state(state, clk1, clk2, clk3, clk4, ts):
        left, lr, right, rl, pre_ts = state

        # Left output → LR Bus → Right
        c1 = AsyncModel.side_output(left)
        next_lr = c1 if clk2 else lr
        c2 = next_lr  # bus output = bus state
        next_right = AsyncModel.side_next(right, clk3, ts, c2)

        # Right output → RL Bus → Left
        c3 = AsyncModel.side_output(right)
        next_rl = c3 if clk4 else rl
        c4 = next_rl
        next_left = AsyncModel.side_next(left, clk1, ts, c4)

        return (next_left, next_lr, next_right, next_rl, ts)

    @staticmethod
    def left_pf(state):
        return AsyncModel.side_output(state[0])[0]

    @staticmethod
    def right_pf(state):
        return AsyncModel.side_output(state[2])[0]

    @staticmethod
    def pressed(ts, state):
        return (not state[4]) and ts

    @staticmethod
    def switching_sides(state):
        left, lr, right, rl, pre_ts = state
        return (AsyncModel.left_pf(state) and not lr[0]) or \
               (AsyncModel.right_pf(state) and not rl[0])


def async_reachable_states():
    initial = AsyncModel.initial_state()
    visited = {initial}
    queue = deque([initial])
    input_combos = list(product((True, False), repeat=5))
    while queue:
        s = queue.popleft()
        for clk1, clk2, clk3, clk4, ts in input_combos:
            ns = AsyncModel.next_state(s, clk1, clk2, clk3, clk4, ts)
            if ns not in visited:
                visited.add(ns)
                queue.append(ns)
    return visited


def check_async_requirements(states):
    results = {}
    initial = AsyncModel.initial_state()
    input_combos = list(product((True, False), repeat=5))

    # R1: At least one side pilot flying
    results['R1'] = all(
        AsyncModel.left_pf(s) or AsyncModel.right_pf(s) for s in states
    )

    # R2: At most one PF except when switching
    results['R2'] = all(
        AsyncModel.switching_sides(s) or
        (AsyncModel.left_pf(s) != AsyncModel.right_pf(s))
        for s in states
    )

    # R3a/R3b and R5a/R5b
    r3a = r3b = r5a = r5b = True
    for s in states:
        if not (r3a or r3b or r5a or r5b):
            break
        for clk1, clk2, clk3, clk4, ts in input_combos:
            ns = AsyncModel.next_state(s, clk1, clk2, clk3, clk4, ts)
            pr = AsyncModel.pressed(ts, s)
            sw = AsyncModel.switching_sides(s)

            if r3a and (not AsyncModel.left_pf(s)) and pr:
                if not AsyncModel.left_pf(ns):
                    r3a = False
            if r3b and (not AsyncModel.right_pf(s)) and pr:
                if not AsyncModel.right_pf(ns):
                    r3b = False
            if (r5a or r5b) and (not sw) and (not pr):
                if r5a and AsyncModel.left_pf(ns) != AsyncModel.left_pf(s):
                    r5a = False
                if r5b and AsyncModel.right_pf(ns) != AsyncModel.right_pf(s):
                    r5b = False

    results['R3a'] = r3a
    results['R3b'] = r3b
    results['R4'] = AsyncModel.left_pf(initial)
    results['R5a'] = r5a
    results['R5b'] = r5b

    return results


# ======================================================================
# Main: compute and write results
# ======================================================================

def main():
    print("Computing synchronous protocol model...")
    sync_states = sync_reachable_states()
    sync_reqs = check_sync_requirements(sync_states)
    print(f"  Reachable states: {len(sync_states)}")
    print(f"  Requirements: {sync_reqs}")

    print("Computing asynchronous protocol model...")
    async_states = async_reachable_states()
    async_reqs = check_async_requirements(async_states)
    print(f"  Reachable states: {len(async_states)}")
    print(f"  Requirements: {async_reqs}")

    results = {
        "synchronous": {
            "reachable_state_count": len(sync_states),
            "requirements": sync_reqs,
        },
        "asynchronous": {
            "reachable_state_count": len(async_states),
            "requirements": async_reqs,
        },
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
