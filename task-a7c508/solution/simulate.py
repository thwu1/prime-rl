#!/usr/bin/env python3
"""
Swiss Tournament Simulation using bbpPairings.
Conducts a 9-round FIDE Dutch Swiss tournament for 20 players.
"""

import csv
import json
import os
import subprocess
import sys

EXE = '/app/bbpPairings.exe'
ALT_EXE = '/app/bbpPairings-src/bbpPairings.exe'
PLAYERS_CSV = '/app/players.csv'
NUM_ROUNDS = 9
NUM_PLAYERS = 20
WORKING_TRF = '/app/working.trf'
PAIRED_OUT = '/app/paired.txt'
FINAL_TRF = '/app/tournament_final.trf'
RESULTS_JSON = '/app/results.json'


def get_exe():
    for p in [EXE, ALT_EXE]:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    print("bbpPairings binary not found, building from source...", file=sys.stderr)
    subprocess.run(['make', '-j4'], cwd='/app/bbpPairings-src', check=True)
    for p in [ALT_EXE, EXE]:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    raise FileNotFoundError("Could not find or build bbpPairings.exe")


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
    """Write a TRF file in FIDE format compatible with bbpPairings.

    Column layout (0-indexed):
      0-3   : "001 "
      4-7   : starting rank (4 chars, right-justified)
      8     : space
      9     : sex (space)
      10-12 : title (3 spaces)
      13    : space
      14-46 : name (33 chars, left-justified)
      47    : space
      48-51 : rating (4 chars, right-justified)
      52    : space
      53-55 : federation (3 chars)
      56    : space
      57-67 : FIDE ID (11 chars)
      68    : space
      69-78 : birth date (10 chars)
      79    : space
      80-83 : points (4 chars, e.g. " 3.5")
      84    : space (part of rank field setw(5))
      85-88 : rank (4 chars, right-justified)
    Then round data at position 89+, each block 10 chars:
      "  OOOO C R" = 2spaces + opponent(4) + space + color + space + result
    """
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

        # Build the fixed-width prefix (positions 0-88, 89 chars total)
        line = '001 %4d      %-33s %4d %-3s %-11s %-10s %4.1f %4d' % (
            pid, p['name'], p['rating'], p['fed'], '', '', pts, pid
        )

        # Round data: each 10-char block "  OOOO C R"
        for color, opp, rc in rds:
            line += '  %4d %s %s' % (opp, color, rc)

        lines.append(line)

    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def parse_pairings(output_path):
    """Parse bbpPairings -p output: first line is count, then 'white black' per line.

    bbpPairings v6 -p outputs a simple pairing list, NOT a TRF file.
    Format:
        10          <-- number of pairings
        1 11        <-- white_id black_id (1-indexed)
        2 12
        ...
    """
    with open(output_path) as f:
        content = f.read().strip()

    lines = content.split('\n')
    if not lines:
        print("ERROR: Empty pairing output file", file=sys.stderr)
        return []

    # First line is the number of pairings
    try:
        num_pairs = int(lines[0].strip())
    except ValueError:
        print("ERROR: First line of pairing output is not a number: %r" % lines[0],
              file=sys.stderr)
        return []

    pairings = []
    for i in range(1, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            print("WARNING: Unexpected pairing line format: %r" % line, file=sys.stderr)
            continue
        white_id = int(parts[0])
        black_id = int(parts[1])
        if black_id == 0:
            # Bye (self-pairing), skip for even-player tournaments
            continue
        pairings.append((white_id, black_id))

    if len(pairings) != num_pairs:
        print("WARNING: Expected %d pairings, parsed %d" % (num_pairs, len(pairings)),
              file=sys.stderr)

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
    exe = get_exe()
    players = load_players()
    player_rounds = {pid: [] for pid in players}
    all_results = []

    for rnd in range(1, NUM_ROUNDS + 1):
        print('--- Round %d ---' % rnd)

        write_trf(WORKING_TRF, players, player_rounds, NUM_ROUNDS)

        proc = subprocess.run(
            [exe, '--dutch', WORKING_TRF, '-p', PAIRED_OUT],
            capture_output=True, text=True, timeout=120
        )
        if proc.returncode != 0:
            print('Pairing failed (exit %d):' % proc.returncode, file=sys.stderr)
            print('stderr:', proc.stderr[:2000], file=sys.stderr)
            print('stdout:', proc.stdout[:2000], file=sys.stderr)
            sys.exit(1)

        if not os.path.isfile(PAIRED_OUT):
            print('ERROR: Output file not created at %s' % PAIRED_OUT,
                  file=sys.stderr)
            sys.exit(1)

        pairings = parse_pairings(PAIRED_OUT)

        if len(pairings) != NUM_PLAYERS // 2:
            print('ERROR: Found %d pairings, expected %d' % (
                len(pairings), NUM_PLAYERS // 2), file=sys.stderr)
            with open(PAIRED_OUT) as dbg:
                print('  Output file contents:', file=sys.stderr)
                for dbg_line in dbg:
                    print('    %r' % dbg_line.rstrip(), file=sys.stderr)
            sys.exit(1)

        print('  Pairings: %d games' % len(pairings))

        round_games = []
        for w, b in pairings:
            result = sim_result(w, b, rnd)
            round_games.append({'white': w, 'black': b, 'result': result})

            if result == '1-0':
                player_rounds[w].append(('w', b, '1'))
                player_rounds[b].append(('b', w, '0'))
            elif result == '0-1':
                player_rounds[w].append(('w', b, '0'))
                player_rounds[b].append(('b', w, '1'))
            else:
                player_rounds[w].append(('w', b, '='))
                player_rounds[b].append(('b', w, '='))

        all_results.append({'round': rnd, 'pairings': round_games})

    # Write final TRF
    write_trf(FINAL_TRF, players, player_rounds, NUM_ROUNDS)
    print('\nFinal TRF written to %s' % FINAL_TRF)

    # Run checker
    proc = subprocess.run(
        [exe, '--dutch', FINAL_TRF, '-c'],
        capture_output=True, text=True, timeout=120
    )
    print('Checker exit code: %d' % proc.returncode)
    if proc.stdout.strip():
        print('Checker stdout: %s' % proc.stdout.strip()[:500])
    if proc.stderr.strip():
        print('Checker stderr: %s' % proc.stderr.strip()[:500])

    # Compute standings
    scores = {pid: 0.0 for pid in players}
    for rd in all_results:
        for g in rd['pairings']:
            if g['result'] == '1-0':
                scores[g['white']] += 1.0
            elif g['result'] == '0-1':
                scores[g['black']] += 1.0
            else:
                scores[g['white']] += 0.5
                scores[g['black']] += 0.5

    sorted_pids = sorted(players.keys(), key=lambda p: (-scores[p], p))
    standings = [
        {
            'rank': i + 1,
            'id': pid,
            'name': players[pid]['name'],
            'score': scores[pid],
        }
        for i, pid in enumerate(sorted_pids)
    ]

    output = {'rounds': all_results, 'standings': standings}
    with open(RESULTS_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print('Results written to %s' % RESULTS_JSON)
    print('Done!')


if __name__ == '__main__':
    main()
