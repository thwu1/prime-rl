#!/usr/bin/env python3
"""Compare current engine output against a reference replay trace.

Usage: python3 trace_diff.py <trace_name>
       python3 trace_diff.py --list
"""
import json
import sys
import os
import glob

sys.path.insert(0, '/app')


def get_traces():
    return sorted([
        os.path.basename(f).replace('replay_', '').replace('.json', '')
        for f in glob.glob('/app/replays/replay_*.json')
    ])


def run_diff(trace_name):
    replay_file = f'/app/replays/replay_{trace_name}.json'
    if not os.path.exists(replay_file):
        print(f"ERROR: replay file not found: {replay_file}")
        return False

    from engine import GameEngine

    with open(replay_file) as f:
        replay = json.load(f)

    engine = GameEngine(replay['config'], replay['initial_state'])
    divergences = []

    for step_data in replay['trace']:
        step = step_data['step']
        actions = step_data['actions']
        expected = step_data['expected']

        try:
            results = engine.step(actions)
        except Exception as e:
            divergences.append(f"  step {step}: ENGINE CRASH: {e}")
            break

        for agent, exp_result in expected.get('results', {}).items():
            actual = results.get(agent, {}).get('result', 'MISSING')
            if actual != exp_result:
                ctx = f"  # {step_data['comment']}" if step_data.get('comment') else ""
                divergences.append(
                    f"  step {step}: {agent}.result = {actual!r} (expected {exp_result!r}){ctx}"
                )

        for agent, exp_state in expected.get('agents', {}).items():
            try:
                actual_agent = engine.get_agent(agent)
            except Exception as e:
                divergences.append(f"  step {step}: {agent} get_agent error: {e}")
                continue
            for field, exp_val in exp_state.items():
                actual_val = actual_agent.get(field)
                if actual_val != exp_val:
                    divergences.append(
                        f"  step {step}: {agent}.{field} = {actual_val!r} (expected {exp_val!r})"
                    )

        if 'blocks' in expected:
            actual_blocks = sorted([(b['x'], b['y'], b['type']) for b in engine.get_blocks()])
            exp_blocks = sorted([(b['x'], b['y'], b['type']) for b in expected['blocks']])
            if actual_blocks != exp_blocks:
                divergences.append(
                    f"  step {step}: blocks mismatch\n"
                    f"    actual:   {actual_blocks}\n"
                    f"    expected: {exp_blocks}"
                )

        for team, exp_score in expected.get('scores', {}).items():
            actual_score = engine.get_score(team)
            if actual_score != exp_score:
                divergences.append(
                    f"  step {step}: score.{team} = {actual_score} (expected {exp_score})"
                )

    if divergences:
        print(f"FAIL  {trace_name}: {len(divergences)} divergence(s)")
        for d in divergences[:15]:
            print(d)
        if len(divergences) > 15:
            print(f"  ... and {len(divergences) - 15} more")
        return False
    else:
        print(f"PASS  {trace_name}")
        return True


def main():
    if len(sys.argv) < 2 or sys.argv[1] == '--help':
        print("Usage: python3 trace_diff.py <trace_name>")
        print("       python3 trace_diff.py --list")
        print("       python3 trace_diff.py --all")
        sys.exit(0)

    if sys.argv[1] == '--list':
        for t in get_traces():
            print(t)
        sys.exit(0)

    if sys.argv[1] == '--all':
        all_pass = True
        for t in get_traces():
            if not run_diff(t):
                all_pass = False
        sys.exit(0 if all_pass else 1)

    sys.exit(0 if run_diff(sys.argv[1]) else 1)


if __name__ == '__main__':
    main()
