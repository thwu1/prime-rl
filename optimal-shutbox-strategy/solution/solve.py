
"""
Solve the weighted Shut-the-Box challenge by:
1. Extracting the backup archive to recover the database and passphrase
2. Querying the database for the challenge experiment parameters
3. Decoding base64-encoded dice configurations
4. Decrypting the AES-encrypted scoring weights using openssl
5. Running exact rational DP over 2^N bitmask states
6. Computing probability of perfect game under cost-optimal policy
7. Computing policy divergence count
"""

import sqlite3
import json
import os
import subprocess
import sys
import tarfile
import base64
from fractions import Fraction

LAB_DIR = "/app/lab"
EXTRACT_DIR = "/tmp/solve_restore"


def main():
    os.makedirs(EXTRACT_DIR, exist_ok=True)

    # Step 1: Extract backup archive
    backup = os.path.join(LAB_DIR, "backups", "research_data_20240730.tar.gz")
    print(f"Extracting backup: {backup}")
    with tarfile.open(backup, 'r:gz') as tar:
        tar.extractall(EXTRACT_DIR)

    db_path = os.path.join(EXTRACT_DIR, "research_data", "game_variants.db")
    pass_path = os.path.join(
        EXTRACT_DIR, "research_data", "keys", "decrypt_passphrase.txt")

    with open(pass_path) as f:
        passphrase = f.read().strip()
    print(f"Recovered passphrase from backup archive")

    # Step 2: Query database for challenge experiment
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute(
        "SELECT id, tile_range FROM experiments WHERE status = 'challenge'")
    row = c.fetchone()
    if row is None:
        print("ERROR: No challenge experiment found", file=sys.stderr)
        sys.exit(1)

    exp_id, tile_range = row
    tile_start, tile_end = map(int, tile_range.split('-'))
    N = tile_end - tile_start + 1
    tiles = list(range(tile_start, tile_end + 1))
    print(f"Challenge experiment {exp_id}: tiles {tile_start}-{tile_end}")

    # Step 3: Get and decode dice options
    c.execute(
        "SELECT option_label, encoding, config_data "
        "FROM dice_options WHERE experiment_id = ? "
        "ORDER BY option_label", (exp_id,))
    dice_rows = c.fetchall()
    conn.close()

    dice_options = {}
    for label, encoding, config_data in dice_rows:
        if encoding == 'base64':
            config_json = base64.b64decode(config_data).decode()
        else:
            config_json = config_data
        config = json.loads(config_json)
        dice_options[label] = _compute_distribution(config["dice"])
        print(f"  Dice {label}: {config['dice']} "
              f"(range {min(dice_options[label])}-"
              f"{max(dice_options[label])})")

    # Step 4: Decrypt scoring config
    enc_path = os.path.join(LAB_DIR, "configs", "scoring_weights_exp7.enc")
    dec_path = os.path.join(EXTRACT_DIR, "scoring_dec.json")
    subprocess.run([
        "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
        "-pass", f"pass:{passphrase}",
        "-in", enc_path, "-out", dec_path
    ], check=True)

    with open(dec_path) as f:
        scoring_config = json.load(f)

    tile_weights = {}
    for tier in scoring_config["tiers"]:
        for tv in tier["tiles"]:
            tile_weights[tv] = tier["multiplier"]
    print(f"  Scoring weights: {tile_weights}")

    # Step 5: DP computation
    FULL = (1 << N) - 1

    penalty = [Fraction(0)] * (1 << N)
    for mask in range(1 << N):
        p = Fraction(0)
        for i in range(N):
            if mask & (1 << i):
                tv = tiles[i]
                p += Fraction(tv * tile_weights.get(tv, 1))
        penalty[mask] = p

    tile_sums = [0] * (1 << N)
    for mask in range(1 << N):
        s = 0
        for i in range(N):
            if mask & (1 << i):
                s += tiles[i]
        tile_sums[mask] = s

    max_roll = max(max(d.keys()) for d in dice_options.values())

    masks_by_sum = [[] for _ in range(max_roll + 1)]
    for mask in range(1, 1 << N):
        s = tile_sums[mask]
        if 1 <= s <= max_roll:
            masks_by_sum[s].append(mask)

    E = [None] * (1 << N)
    E[0] = Fraction(0)
    optimal_dice = [None] * (1 << N)
    optimal_action = [None] * (1 << N)

    states_by_popcount = [[] for _ in range(N + 1)]
    for mask in range(1 << N):
        states_by_popcount[bin(mask).count("1")].append(mask)

    sorted_labels = sorted(dice_options.keys())

    print("Running DP over", 1 << N, "states...")
    for pc in range(1, N + 1):
        for mask in states_by_popcount[pc]:
            best_E = None
            best_dice_label = None
            best_actions_per_dice = {}

            for label in sorted_labels:
                dist = dice_options[label]
                expected = Fraction(0)
                actions = {}

                for roll_val, roll_prob in dist.items():
                    best_rem = None
                    if 1 <= roll_val <= max_roll:
                        for sub in masks_by_sum[roll_val]:
                            if (sub & mask) == sub:
                                remaining = mask ^ sub
                                if (best_rem is None
                                        or E[remaining] < E[best_rem]):
                                    best_rem = remaining

                    if best_rem is None:
                        expected += roll_prob * penalty[mask]
                    else:
                        expected += roll_prob * E[best_rem]
                    actions[roll_val] = best_rem

                best_actions_per_dice[label] = actions
                if best_E is None or expected < best_E:
                    best_E = expected
                    best_dice_label = label

            E[mask] = best_E
            optimal_dice[mask] = best_dice_label
            optimal_action[mask] = best_actions_per_dice[best_dice_label]

    # Step 6: Probability of perfect game under cost-optimal policy
    print("Computing perfect game probability...")
    P_perfect = [None] * (1 << N)
    P_perfect[0] = Fraction(1)

    for pc in range(1, N + 1):
        for mask in states_by_popcount[pc]:
            d = optimal_dice[mask]
            dist = dice_options[d]
            actions = optimal_action[mask]
            prob = Fraction(0)
            for roll_val, roll_prob in dist.items():
                rem = actions.get(roll_val)
                if rem is not None:
                    prob += roll_prob * P_perfect[rem]
            P_perfect[mask] = prob

    # Step 7: Extract answers
    answer_ev = E[FULL]
    p = answer_ev.numerator
    q = answer_ev.denominator

    answer_perf = P_perfect[FULL]
    a = answer_perf.numerator
    b = answer_perf.denominator

    optimal_start = optimal_dice[FULL]

    divergence_count = 0
    for mask in range(1, 1 << N):
        if optimal_dice[mask] != optimal_start:
            divergence_count += 1

    # Step 8: Write answer
    with open("/app/answer.txt", "w") as f:
        f.write(f"{p}\n{q}\n{a}\n{b}\n{optimal_start}\n"
                f"{divergence_count}\n")

    print(f"\nResults:")
    print(f"  Expected cost: {p}/{q} (approx {float(answer_ev):.6f})")
    print(f"  Perfect game prob: {a}/{b} "
          f"(approx {float(answer_perf):.10f})")
    print(f"  Optimal starting dice: {optimal_start}")
    print(f"  Policy divergence count: {divergence_count}")


def _compute_distribution(dice_list):
    """Compute exact probability distribution of the sum of dice."""
    dist = {0: Fraction(1)}
    for die in dice_list:
        sides = die["sides"]
        faces = list(range(1, sides + 1))
        new_dist = {}
        for old_sum, old_prob in dist.items():
            for face in faces:
                ns = old_sum + face
                np_ = old_prob * Fraction(1, sides)
                new_dist[ns] = new_dist.get(ns, Fraction(0)) + np_
        dist = new_dist
    return dist


if __name__ == "__main__":
    main()
