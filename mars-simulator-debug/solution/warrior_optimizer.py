#!/usr/bin/env python3
"""
Core War warrior optimizer.

Generates candidate warriors from parameterized strategy templates,
evaluates each against the 5 hill opponents using pMARS, and selects
the warrior with the best aggregate performance.

Strategy templates explored:
  - Dwarf bombers (varying step sizes)
  - DJN-controlled stones (varying step + iteration count)
  - SPL fork-bombers (varying step sizes)
  - Stone-then-clear hybrids (varying step + bomb count)

"""
import subprocess
import os
import sys
import tempfile

PMARS = "/usr/local/bin/pmars"
OPPONENTS_DIR = "/app/opponents"
CHALLENGER_PATH = "/app/challenger.red"
OPPONENTS = ["imp.red", "dwarf.red", "stone.red", "scanner.red", "splitter.red"]

CORE_SIZE = 8000
MAX_PROCS = 8000
MAX_CYCLES = 80000
FIXED_POS = 4000

# --- pMARS interface ---

def run_match(w1_path, w2_path, rounds=50):
    """Run pMARS and return (w1_wins, w2_wins, ties)."""
    cmd = [PMARS,
           "-s", str(CORE_SIZE), "-p", str(MAX_PROCS),
           "-c", str(MAX_CYCLES), "-r", str(rounds),
           "-k", "-b", "-F", str(FIXED_POS),
           w1_path, w2_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return (0, 0, rounds)
    if result.returncode != 0:
        return (0, 0, rounds)
    lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
    if len(lines) < 2:
        return (0, 0, rounds)
    try:
        w1_parts = lines[-2].split()
        w2_parts = lines[-1].split()
        w1_wins = int(w1_parts[0])
        w1_ties = int(w1_parts[1])
        w2_wins = int(w2_parts[0])
        return w1_wins, w2_wins, w1_ties
    except (IndexError, ValueError):
        return (0, 0, rounds)


def evaluate_candidate(code, rounds_per_matchup=50):
    """Test a warrior against all opponents and return performance metrics.

    Returns (composite_score, total_wins, min_wins, min_nonloss, per_opp_dict)
    """
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.red', delete=False, dir='/tmp'
    ) as f:
        f.write(code)
        tmp_path = f.name

    total_wins = 0
    min_wins = 999999
    min_nonloss = 999999
    per_opp = {}

    for opp in OPPONENTS:
        opp_path = os.path.join(OPPONENTS_DIR, opp)
        wins, losses, ties = run_match(tmp_path, opp_path, rounds_per_matchup)
        total_wins += wins
        if wins < min_wins:
            min_wins = wins
        nonloss = wins + ties
        if nonloss < min_nonloss:
            min_nonloss = nonloss
        per_opp[opp] = (wins, losses, ties)

    os.unlink(tmp_path)

    # Composite score: reward total wins but heavily penalize zero-win matchups
    # and insufficient resilience (wins+ties < 40 per 200 rounds)
    penalty = 0
    if min_wins < 1:
        penalty += 10000
    scaled_nonloss = min_nonloss * (200 / rounds_per_matchup)
    if scaled_nonloss < 40:
        penalty += 5000
    score = total_wins - penalty

    return score, total_wins, min_wins, min_nonloss, per_opp


# --- Warrior template generators ---

def gen_dwarf(step):
    """Classic Dwarf: 4-instruction infinite bomber."""
    return (
        f";redcode-94\n"
        f";name Dwarf{step}\n"
        f"ORG 1\n"
        f"DAT.F #0, #0\n"
        f"ADD.AB #{step}, $-1\n"
        f"MOV.I $-2, @-2\n"
        f"JMP.A $-2, #0\n"
    )


def gen_djn_stone(step, count):
    """DJN-controlled stone with fallback loop."""
    return (
        f";redcode-94\n"
        f";name Stone{step}x{count}\n"
        f"ORG 0\n"
        f"ADD.AB #{step}, $4\n"
        f"MOV.I $4, @3\n"
        f"DJN.B $-2, #{count}\n"
        f"JMP.A $-3, $0\n"
        f"DAT.F #0, #{step}\n"
        f"DAT.F #0, #0\n"
    )


def gen_spl_bomber(step):
    """SPL fork-bomb: splits then bombs with given step."""
    return (
        f";redcode-94\n"
        f";name Splitter{step}\n"
        f"ORG 0\n"
        f"SPL.B $0, $0\n"
        f"MOV.I $2, @2\n"
        f"ADD.AB #{step}, $-1\n"
        f"JMP.A $-2, $0\n"
        f"DAT.F #0, #0\n"
    )


def gen_stone_clear(step, bomb_count):
    """Stone phase (bomb_count iterations) then systematic core clear."""
    return (
        f";redcode-94\n"
        f";name SC{step}x{bomb_count}\n"
        f"ORG start\n"
        f"bomb    DAT.F #0, #0\n"
        f"start   ADD.AB #{step}, $bomb\n"
        f"        MOV.I $bomb, @bomb\n"
        f"        DJN.B $-2, #{bomb_count}\n"
        f"clear   MOV.I $bomb, $target\n"
        f"        ADD.AB #1, $target\n"
        f"        DJN.B $clear, $ctr\n"
        f"target  DAT.F #0, #10\n"
        f"ctr     DAT.F #0, #7990\n"
    )


def gen_fast_bomber(step, mod_step):
    """Two-target bomber: bombs at two different rates."""
    return (
        f";redcode-94\n"
        f";name FB{step}m{mod_step}\n"
        f"ORG 1\n"
        f"DAT.F #0, #0\n"
        f"ADD.AB #{step}, $-1\n"
        f"MOV.I $-2, @-2\n"
        f"ADD.AB #{mod_step}, $-3\n"
        f"MOV.I $-4, @-4\n"
        f"JMP.A $-4, #0\n"
    )


# --- Main optimization loop ---

def main():
    print("=" * 60)
    print("Core War Warrior Optimizer")
    print("=" * 60)

    candidates = []

    # 1. Dwarf variants (different bombing steps)
    dwarf_steps = [
        3, 5, 7, 10, 11, 13, 17, 19, 23, 29, 37, 41,
        100, 500, 1000, 2000, 2333, 2667, 2711,
        3044, 3334, 3571, 4000, 5000, 5334, 6000, 7000, 7500
    ]
    for step in dwarf_steps:
        candidates.append((f"Dwarf(step={step})", gen_dwarf(step)))

    # 2. DJN-stone variants
    stone_steps = [2333, 2667, 2711, 3044, 3334, 5334, 7001]
    stone_counts = [5, 8, 10, 15, 20, 50]
    for step in stone_steps:
        for count in stone_counts:
            candidates.append(
                (f"DJNStone(s={step},c={count})", gen_djn_stone(step, count))
            )

    # 3. SPL-bomber variants
    spl_steps = [7, 11, 13, 2667, 3044, 5334]
    for step in spl_steps:
        candidates.append((f"SPLBomb(step={step})", gen_spl_bomber(step)))

    # 4. Stone-clear variants
    sc_steps = [2333, 2667, 3044, 5334]
    sc_counts = [5, 8, 12, 20]
    for step in sc_steps:
        for count in sc_counts:
            candidates.append(
                (f"StoneClear(s={step},c={count})", gen_stone_clear(step, count))
            )

    # 5. Fast two-target bombers
    fb_configs = [
        (2667, 5334), (3044, 2711), (5334, 2667),
        (3334, 2333), (7001, 3044)
    ]
    for step, mod in fb_configs:
        candidates.append(
            (f"FastBomber(s={step},m={mod})", gen_fast_bomber(step, mod))
        )

    total = len(candidates)
    print(f"\nEvaluating {total} candidates (quick pass: 50 rounds/matchup)...\n")

    # Quick evaluation pass
    scored = []
    for i, (name, code) in enumerate(candidates):
        score, twins, mwins, mnl, per_opp = evaluate_candidate(code, 50)
        scored.append((score, twins, mwins, mnl, name, code, per_opp))
        if (i + 1) % 20 == 0:
            print(f"  ... evaluated {i + 1}/{total}")

    # Sort by composite score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Show top 5
    print("\nTop 5 candidates (quick evaluation):")
    for rank, (sc, tw, mw, mnl, name, _, _) in enumerate(scored[:5], 1):
        print(f"  {rank}. {name}  score={sc} total_wins={tw} min_wins={mw}")

    # Full evaluation of top 3
    print(f"\nFull evaluation of top 3 (200 rounds/matchup)...")
    best_name = None
    best_code = None
    best_total = -1
    best_details = None

    for sc, tw, mw, mnl, name, code, _ in scored[:3]:
        score, twins, mwins, mnl, per_opp = evaluate_candidate(code, 200)
        print(f"\n  {name}: total_wins={twins} min_wins={mwins}")
        for opp in OPPONENTS:
            w, l, t = per_opp[opp]
            print(f"    vs {opp:15s}: {w:3d}W {l:3d}L {t:3d}T")

        # Check all constraints
        passes = True
        if mwins < 1:
            passes = False
            print(f"    FAIL: min_wins={mwins} < 1")
        if mnl < 10:  # 40 scaled from 200 rounds = 10 from 50
            passes = False
            print(f"    FAIL: min_nonloss={mnl} too low")
        if twins < 50:  # 200 scaled from 200 = 50 from 50
            passes = False
            print(f"    FAIL: total_wins={twins} < threshold")

        if passes and twins > best_total:
            best_total = twins
            best_name = name
            best_code = code
            best_details = per_opp

    if best_code is None:
        # Fallback: use the highest-scoring candidate regardless
        print("\nWARNING: No candidate passed all constraints. Using best available.")
        _, _, _, _, best_name, best_code, _ = scored[0]

    # Write the winner to /app/challenger.red
    with open(CHALLENGER_PATH, 'w') as f:
        f.write(best_code)

    print(f"\n{'=' * 60}")
    print(f"Selected warrior: {best_name}")
    print(f"Written to: {CHALLENGER_PATH}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
