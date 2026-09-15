#!/usr/bin/env python3
"""
Fix the fastchess output parser bugs and implement missing features.

"""

PARSER_CODE = r"""
import re

PATTERN_WLD = re.compile(
    r"Games: (\d+), Wins: (\d+), Losses: (\d+), Draws: (\d+), Points: ([\d.]+)"
)
PATTERN_PTNML = re.compile(
    r"Ptnml\(0-2\): \[(\d+), (\d+), (\d+), (\d+), (\d+)\]"
)


def parse_fastchess_output(text):
    '''Parse raw fastchess output and return extracted game results.

    The output may contain multiple result blocks from incremental
    reporting. Returns data from the final (most recent) block.

    Args:
        text: Raw console output from a fastchess game run.

    Returns:
        dict with keys: games, wins, losses, draws, pentanomial,
                        crashes, time_losses

    Raises:
        ValueError: if game results cannot be found in the output
    '''
    # Find ALL WLD matches and use the LAST one (final results block)
    wld_matches = PATTERN_WLD.findall(text)
    if not wld_matches:
        raise ValueError("No game results found in fastchess output")

    last_wld = wld_matches[-1]
    results = {
        'games': int(last_wld[0]),
        'wins': int(last_wld[1]),
        'losses': int(last_wld[2]),
        'draws': int(last_wld[3]),
    }

    # Find ALL pentanomial matches and use the LAST one
    ptnml_matches = PATTERN_PTNML.findall(text)
    if ptnml_matches:
        last_ptnml = ptnml_matches[-1]
        results['pentanomial'] = [int(x) for x in last_ptnml]
    else:
        results['pentanomial'] = [0, 0, 0, 0, 0]

    # Count crashes (disconnect/stall) and time losses (on time/timeout)
    crashes = 0
    time_losses = 0
    for line in text.split('\n'):
        if 'disconnect' in line or 'stall' in line:
            crashes += 1
        if 'on time' in line or 'timeout' in line:
            time_losses += 1

    results['crashes'] = crashes
    results['time_losses'] = time_losses

    return results
"""

with open("/app/parser.py", "w") as f:
    f.write(PARSER_CODE.lstrip('\n'))

print("Parser implementation complete.")
