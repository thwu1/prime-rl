#!/usr/bin/env python3
"""
Generate a corrupted tournament TRF file for the diagnostic repair task.
Run during Docker build to create the task environment.

Creates a valid 9-round Swiss tournament using bbpPairings, saves ground truth,
then creates a corrupted 5-round TRF with 4 planted data integrity issues.
"""
import csv
import json
import os
import subprocess
import sys

EXE = '/app/bbpPairings.exe'
PLAYERS_CSV = '/app/players.csv'
NUM_ROUNDS = 9
NUM_PLAYERS = 20


def load_players():
    players = {}
    with open(PLAYERS_CSV) as f:
        for row in csv.DictReader(f):
            pid = int(row['id'])
            players[pid] = {
                'name': row['name'].strip()[:33],
                'rating': int(row['rating']),
                'fed': row['federation'].strip()[:3],
            }
    return players


def compute_points(rounds_data):
    total = 0.0
    for _, _, rc in rounds_data:
        if rc == '1':
            total += 1.0
        elif rc == '=':
            total += 0.5
    return total


def write_trf(path, players, player_rounds, total_rounds):
    lines = [
        '012 Swiss Tournament Simulation',
        '022 Virtual City',
        '032 INT',
        '042 2025/01/15',
        '052 2025/01/19',
        '062 %d' % len(players),
        '072 %d' % len(players),
        '092 Swiss',
        '102 Chief Arbiter',
        'XXR %d' % total_rounds,
        'XXC white1',
    ]
    for pid in sorted(players.keys()):
        p = players[pid]
        rds = player_rounds.get(pid, [])
        pts = compute_points(rds)
        line = '001 %4d      %-33s %4d %-3s %-11s %-10s %4.1f %4d' % (
            pid, p['name'], p['rating'], p['fed'], '', '', pts, pid
        )
        for color, opp, rc in rds:
            line += '  %4d %s %s' % (opp, color, rc)
        lines.append(line)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def parse_pairings(output_path):
    with open(output_path) as f:
        content = f.read().strip()
    pairings = []
    for line in content.split('\n')[1:]:
        parts = line.strip().split()
        if len(parts) == 2:
            w, b = int(parts[0]), int(parts[1])
            if b != 0:
                pairings.append((w, b))
    return pairings


def sim_result(w, b, rnd):
    seed = (w * 997 + b * 31 + rnd * 7919) % 100
    if seed < 45:
        return '1-0'
    elif seed < 90:
        return '0-1'
    else:
        return '1/2-1/2'


def main():
    players = load_players()
    player_rounds = {pid: [] for pid in players}
    ground_truth = {}

    # Generate all 9 rounds using bbpPairings
    for rnd in range(1, NUM_ROUNDS + 1):
        write_trf('/tmp/working.trf', players, player_rounds, NUM_ROUNDS)
        proc = subprocess.run(
            [EXE, '--dutch', '/tmp/working.trf', '-p', '/tmp/paired.txt'],
            capture_output=True, text=True, timeout=120
        )
        if proc.returncode != 0:
            print('Round %d pairing failed: %s' % (rnd, proc.stderr), file=sys.stderr)
            sys.exit(1)
        pairings = parse_pairings('/tmp/paired.txt')
        round_games = []
        for w, b in pairings:
            result = sim_result(w, b, rnd)
            if result == '1-0':
                player_rounds[w].append(('w', b, '1'))
                player_rounds[b].append(('b', w, '0'))
            elif result == '0-1':
                player_rounds[w].append(('w', b, '0'))
                player_rounds[b].append(('b', w, '1'))
            else:
                player_rounds[w].append(('w', b, '='))
                player_rounds[b].append(('b', w, '='))
            round_games.append({'white': w, 'black': b, 'result': result})
        ground_truth[str(rnd)] = round_games
        print('Round %d: %d pairings generated' % (rnd, len(pairings)))

    # Verify complete tournament passes checker
    write_trf('/tmp/complete_clean.trf', players, player_rounds, NUM_ROUNDS)
    proc = subprocess.run(
        [EXE, '--dutch', '/tmp/complete_clean.trf', '-c'],
        capture_output=True, text=True, timeout=120
    )
    if proc.returncode != 0:
        print('Complete tournament failed checker: %s' % proc.stderr, file=sys.stderr)
        sys.exit(1)
    print('Complete clean tournament passes checker.')

    # Save ground truth for test verification
    with open('/app/.ground_truth.json', 'w') as f:
        json.dump(ground_truth, f, indent=2)

    # Create 5-round TRF and apply corruptions
    player_rounds_5 = {pid: rds[:5] for pid, rds in player_rounds.items()}
    write_trf('/tmp/clean_5.trf', players, player_rounds_5, NUM_ROUNDS)

    with open('/tmp/clean_5.trf') as f:
        trf_content = f.read()
    trf_lines = trf_content.split('\n')

    corrupted = []
    for line in trf_lines:
        # Bug 1: Remove XXR header
        if line.startswith('XXR'):
            print('Corruption 1: Removing XXR line')
            continue

        # Bug 2: Inflate player 7 score by 0.5
        if line.startswith('001') and len(line) > 8 and line[4:8].strip() == '7':
            pts = float(line[80:84])
            new_pts = pts + 0.5
            line = line[:80] + '%4.1f' % new_pts + line[84:]
            print('Corruption 2: Player 7 score %.1f -> %.1f' % (pts, new_pts))

        # Bug 3: Change player 12 round 4 result code
        if line.startswith('001') and len(line) > 8 and line[4:8].strip() == '12':
            pos = 89 + 3 * 10 + 9  # Round 4 result character position
            if pos < len(line):
                orig = line[pos]
                repl = '=' if orig != '=' else '1'
                line = line[:pos] + repl + line[pos + 1:]
                print('Corruption 3: Player 12 round 4 result %s -> %s' % (orig, repl))

        # Bug 4: Column shift on player 20 (insert extra space at position 47)
        if line.startswith('001') and len(line) > 8 and line[4:8].strip() == '20':
            line = line[:47] + ' ' + line[47:]
            print('Corruption 4: Player 20 line shifted by 1 character')

        corrupted.append(line)

    with open('/app/tournament.trf', 'w') as f:
        f.write('\n'.join(corrupted))

    # Verify corrupted TRF fails checker
    proc = subprocess.run(
        [EXE, '--dutch', '/app/tournament.trf', '-c'],
        capture_output=True, text=True, timeout=120
    )
    if proc.returncode == 0:
        print('ERROR: Corrupted TRF still passes checker!', file=sys.stderr)
        sys.exit(1)
    print('Corrupted TRF correctly fails (exit %d).' % proc.returncode)
    print('Error output: %s' % proc.stderr[:300])
    print('Setup complete.')


if __name__ == '__main__':
    main()
