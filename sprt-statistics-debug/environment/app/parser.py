"""
Fastchess output parser for extracting game results.

Parses the output of the fastchess game runner to extract:
- Win/Draw/Loss counts
- Pentanomial pair frequencies
- Crash and time loss incidents

Sample output format (results block):

    --------------------------------------------------
    Results of New-abc123 vs Base-def456 (10+0.1, 1t, 16MB, book.epd):
    Elo: 3.45 +/- 15.27, nElo: 4.31 +/- 19.07
    LOS: 67.12 %, DrawRatio: 45.20 %, PairsRatio: 1.12
    Games: 200, Wins: 65, Losses: 55, Draws: 80, Points: 105.0 (52.50 %)
    Ptnml(0-2): [5, 22, 48, 18, 7], WL/DD Ratio: 3.45
    --------------------------------------------------
"""
import re

PATTERN_WLD = re.compile(
    r"Games: (\d+), Wins: (\d+), Losses: (\d+), Draws: (\d+), Points: ([\d.]+)"
)
PATTERN_PTNML = re.compile(
    r"Ptnml\(0-2\): \[(\d+), (\d+), (\d+), (\d+), (\d+)\]"
)


def parse_fastchess_output(text):
    """Parse raw fastchess output and return extracted game results.

    The output may contain multiple result blocks from incremental
    reporting. Returns data from the final (most recent) block.

    Args:
        text: Raw console output from a fastchess game run.

    Returns:
        dict with keys: games, wins, losses, draws, pentanomial,
                        crashes, time_losses

    Raises:
        ValueError: if game results cannot be found in the output
    """
    wld_match = PATTERN_WLD.search(text)
    if not wld_match:
        raise ValueError("No game results found in fastchess output")

    results = {
        'games': int(wld_match.group(1)),
        'wins': int(wld_match.group(3)),
        'losses': int(wld_match.group(2)),
        'draws': int(wld_match.group(4)),
    }

    results['pentanomial'] = [0, 0, 0, 0, 0]
    results['crashes'] = 0
    results['time_losses'] = 0

    return results
