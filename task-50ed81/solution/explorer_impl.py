#!/usr/bin/env python3
"""
Exhaustive BFS state space explorer for the Voting Protocol.

Implements all protocol transitions (Propose, CastVote, Decide) matching
the fixed TLA+ specification semantics, performs breadth-first exploration
of the full reachable state space, and checks TypeOK and Agreement
invariants at every reached state.
"""

import argparse
import json
import sys
from collections import deque


def make_initial_state(nodes):
    """Create the initial protocol state: nothing proposed, no votes, nothing decided."""
    return {
        'proposed': {n: 'none' for n in nodes},
        'votes': {n: frozenset() for n in nodes},
        'decided': {n: 'none' for n in nodes},
        'hasVotedFor': {n: 'none' for n in nodes},
    }


def state_to_hashable(state, sorted_nodes):
    """Convert a state dict to a canonical hashable tuple for deduplication."""
    return (
        tuple(state['proposed'][n] for n in sorted_nodes),
        tuple(state['votes'][n] for n in sorted_nodes),
        tuple(state['decided'][n] for n in sorted_nodes),
        tuple(state['hasVotedFor'][n] for n in sorted_nodes),
    )


def copy_state(state):
    """Efficiently copy a state. Frozensets are immutable so shallow dict copy suffices."""
    return {
        'proposed': dict(state['proposed']),
        'votes': dict(state['votes']),
        'decided': dict(state['decided']),
        'hasVotedFor': dict(state['hasVotedFor']),
    }


def compute_quorum(nodes):
    """Quorum is strict majority: floor(|Nodes| / 2) + 1, matching TLA+ div."""
    return len(nodes) // 2 + 1


def check_type_ok(state, nodes, values):
    """Check the TypeOK invariant: all variables have values within expected domains."""
    for n in nodes:
        if state['proposed'][n] != 'none' and state['proposed'][n] not in values:
            return False
        if not state['votes'][n].issubset(frozenset(nodes)):
            return False
        if state['decided'][n] != 'none' and state['decided'][n] not in values:
            return False
        if state['hasVotedFor'][n] != 'none' and state['hasVotedFor'][n] not in nodes:
            return False
    return True


def check_agreement(state, nodes):
    """Check the Agreement invariant: all decided values must be identical."""
    decided_vals = [state['decided'][n] for n in nodes
                    if state['decided'][n] != 'none']
    if len(decided_vals) >= 2:
        return all(v == decided_vals[0] for v in decided_vals)
    return True


def get_successors(state, nodes, values, quorum):
    """
    Generate all valid successor states from the current state.
    Implements the three protocol actions with all required guards.
    """
    successors = []

    # ── Propose(n, v) ────────────────────────────────────────────────
    # Node n proposes value v, casting a self-vote.
    # Guards: proposed[n] = "none", decided[n] = "none", hasVotedFor[n] = "none"
    # Effects: proposed'[n] = v, votes'[n] = votes[n] ∪ {n}, hasVotedFor'[n] = n
    for n in nodes:
        if (state['proposed'][n] != 'none'
                or state['decided'][n] != 'none'
                or state['hasVotedFor'][n] != 'none'):
            continue
        for v in values:
            new_state = copy_state(state)
            new_state['proposed'][n] = v
            new_state['votes'][n] = state['votes'][n] | frozenset([n])
            new_state['hasVotedFor'][n] = n
            successors.append(new_state)

    # ── CastVote(voter, proposer) ────────────────────────────────────
    # Voter casts a vote supporting proposer's proposal.
    # Guards: proposed[proposer] ≠ "none", voter ≠ proposer,
    #         voter ∉ votes[proposer], hasVotedFor[voter] = "none"
    # Effects: votes'[proposer] = votes[proposer] ∪ {voter},
    #          hasVotedFor'[voter] = proposer
    for voter in nodes:
        if state['hasVotedFor'][voter] != 'none':
            continue
        for proposer in nodes:
            if proposer == voter:
                continue
            if state['proposed'][proposer] == 'none':
                continue
            if voter in state['votes'][proposer]:
                continue
            new_state = copy_state(state)
            new_state['votes'][proposer] = (
                state['votes'][proposer] | frozenset([voter])
            )
            new_state['hasVotedFor'][voter] = proposer
            successors.append(new_state)

    # ── Decide(n) ────────────────────────────────────────────────────
    # Node n decides on its proposed value when it has quorum support.
    # Guards: proposed[n] ≠ "none", decided[n] = "none",
    #         |votes[n]| ≥ Quorum
    # Effects: decided'[n] = proposed[n]
    for n in nodes:
        if state['proposed'][n] == 'none':
            continue
        if state['decided'][n] != 'none':
            continue
        if len(state['votes'][n]) < quorum:
            continue
        new_state = copy_state(state)
        new_state['decided'][n] = state['proposed'][n]
        successors.append(new_state)

    return successors


def explore(nodes, values):
    """
    Perform exhaustive BFS exploration of the protocol's reachable state space.
    Returns a dict with exploration results.
    """
    quorum = compute_quorum(nodes)
    sorted_nodes = sorted(nodes)

    initial = make_initial_state(nodes)
    initial_hash = state_to_hashable(initial, sorted_nodes)

    visited = {initial_hash}
    queue = deque()
    queue.append((initial, 0))
    max_depth = 0

    while queue:
        current_state, depth = queue.popleft()
        if depth > max_depth:
            max_depth = depth

        # Check invariants at every reachable state
        if not check_type_ok(current_state, nodes, values):
            return {
                'distinct_states': len(visited),
                'violation_found': True,
                'violation_type': 'TypeOK',
                'max_depth': max_depth,
            }

        if not check_agreement(current_state, nodes):
            return {
                'distinct_states': len(visited),
                'violation_found': True,
                'violation_type': 'Agreement',
                'max_depth': max_depth,
            }

        # Expand all successors
        for successor in get_successors(current_state, nodes, values, quorum):
            h = state_to_hashable(successor, sorted_nodes)
            if h not in visited:
                visited.add(h)
                queue.append((successor, depth + 1))

    return {
        'distinct_states': len(visited),
        'violation_found': False,
        'violation_type': None,
        'max_depth': max_depth,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Exhaustive BFS state space explorer for the Voting Protocol')
    parser.add_argument('--nodes', type=int, default=3,
                        help='Number of participating nodes (default: 3)')
    parser.add_argument('--values', type=int, default=2,
                        help='Number of proposable values (default: 2)')
    args = parser.parse_args()

    nodes = [f'n{i + 1}' for i in range(args.nodes)]
    values = [f'v{i + 1}' for i in range(args.values)]

    result = explore(nodes, values)
    json.dump(result, sys.stdout)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
