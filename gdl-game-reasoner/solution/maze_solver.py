#!/usr/bin/env python3
"""Maze game solver: finds shortest action sequence to goal 100 using BFS."""

import sys
import json
from collections import deque

sys.path.insert(0, '/app')
from gdl_reasoner import GDLReasoner


def solve_maze():
    r = GDLReasoner.from_file('/app/games/maze.kif')
    initial = r.get_initial_state()

    queue = deque([(initial, [])])
    visited = {initial}

    while queue:
        state, actions = queue.popleft()

        if r.is_terminal(state) and r.get_goal(state, 'robot') == 100:
            return {
                'actions': actions,
                'final_goal': 100,
                'total_steps': len(actions),
            }

        if r.is_terminal(state):
            continue

        for move in sorted(r.get_legal_moves(state, 'robot')):
            nxt = r.get_next_state(state, {'robot': move})
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, actions + [move]))

    raise RuntimeError('No winning sequence found')


if __name__ == '__main__':
    result = solve_maze()
    with open('/app/maze_solution.json', 'w') as f:
        json.dump(result, f, indent=2)
    print(f"Solution found: {result['total_steps']} steps")
