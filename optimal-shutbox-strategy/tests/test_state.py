
"""
Independently verify the submitted answer for the weighted Shut-the-Box
challenge by recovering game parameters from the research environment
and solving via dynamic programming with exact rational arithmetic.
"""

import pytest
import sqlite3
import json
import os
import subprocess
import tarfile
import base64
from fractions import Fraction
from math import gcd


LAB_DIR = "/app/lab"
EXTRACT_DIR = "/tmp/test_restore"


def _extract_backup():
    """Extract the tar.gz backup archive."""
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    backup = os.path.join(LAB_DIR, "backups", "research_data_20240730.tar.gz")
    with tarfile.open(backup, 'r:gz') as tar:
        tar.extractall(EXTRACT_DIR)
    return (
        os.path.join(EXTRACT_DIR, "research_data", "game_variants.db"),
        os.path.join(EXTRACT_DIR, "research_data", "keys",
                     "decrypt_passphrase.txt")
    )


def _decrypt_scoring(passphrase):
    """Decrypt the scoring weights file using openssl."""
    enc_path = os.path.join(LAB_DIR, "configs", "scoring_weights_exp7.enc")
    dec_path = os.path.join(EXTRACT_DIR, "scoring_weights_dec.json")
    subprocess.run([
        "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
        "-pass", f"pass:{passphrase}",
        "-in", enc_path, "-out", dec_path
    ], check=True)
    with open(dec_path) as f:
        return json.load(f)


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


def _solve_challenge():
    """Recover parameters and compute all reference answers."""
    db_path, pass_path = _extract_backup()

    with open(pass_path) as f:
        passphrase = f.read().strip()

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute(
        "SELECT id, tile_range FROM experiments WHERE status = 'challenge'")
    row = c.fetchone()
    assert row is not None, "No challenge experiment in database"
    exp_id, tile_range = row
    tile_start, tile_end = map(int, tile_range.split('-'))
    N = tile_end - tile_start + 1
    tiles = list(range(tile_start, tile_end + 1))

    c.execute(
        "SELECT option_label, encoding, config_data "
        "FROM dice_options WHERE experiment_id = ? "
        "ORDER BY option_label", (exp_id,))
    dice_rows = c.fetchall()
    conn.close()

    # Parse dice (handling base64 encoding)
    dice_options = {}
    for label, encoding, config_data in dice_rows:
        if encoding == 'base64':
            config_json = base64.b64decode(config_data).decode()
        else:
            config_json = config_data
        config = json.loads(config_json)
        dice_options[label] = _compute_distribution(config["dice"])

    # Decrypt and parse scoring config
    scoring_config = _decrypt_scoring(passphrase)
    tile_weights = {}
    for tier in scoring_config["tiers"]:
        for tv in tier["tiles"]:
            tile_weights[tv] = tier["multiplier"]

    # ===== DP Computation =====
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
    # For each state: dict mapping roll_val -> best remaining state (or None)
    optimal_action = [None] * (1 << N)

    states_by_popcount = [[] for _ in range(N + 1)]
    for mask in range(1 << N):
        states_by_popcount[bin(mask).count("1")].append(mask)

    sorted_labels = sorted(dice_options.keys())

    for pc in range(1, N + 1):
        for mask in states_by_popcount[pc]:
            best_E = None
            best_dice_label = None
            evs = {}
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
                                if best_rem is None or E[remaining] < E[best_rem]:
                                    best_rem = remaining

                    if best_rem is None:
                        expected += roll_prob * penalty[mask]
                    else:
                        expected += roll_prob * E[best_rem]
                    actions[roll_val] = best_rem

                evs[label] = expected
                best_actions_per_dice[label] = actions
                if best_E is None or expected < best_E:
                    best_E = expected
                    best_dice_label = label

            E[mask] = best_E
            optimal_dice[mask] = best_dice_label
            optimal_action[mask] = best_actions_per_dice[best_dice_label]

    # ===== Probability of perfect game under cost-optimal policy =====
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

    # ===== Extract answers =====
    ref_ev = E[FULL]
    ref_perf = P_perfect[FULL]

    start_evs = {}
    for label in sorted_labels:
        dist = dice_options[label]
        expected = Fraction(0)
        for roll_val, roll_prob in dist.items():
            best_rem = None
            if 1 <= roll_val <= max_roll:
                for sub in masks_by_sum[roll_val]:
                    if (sub & FULL) == sub:
                        remaining = FULL ^ sub
                        if best_rem is None or E[remaining] < E[best_rem]:
                            best_rem = remaining
            if best_rem is None:
                expected += roll_prob * penalty[FULL]
            else:
                expected += roll_prob * E[best_rem]
        start_evs[label] = expected

    ref_start_dice = min(start_evs, key=lambda l: start_evs[l])

    divergence_count = 0
    for mask in range(1, 1 << N):
        if optimal_dice[mask] != ref_start_dice:
            divergence_count += 1

    return ref_ev, ref_perf, ref_start_dice, divergence_count


# Compute reference at module load
_REF_EV, _REF_PERF, _REF_DICE, _REF_DIV = _solve_challenge()


def _read_answer():
    with open("/app/answer.txt") as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    return lines


class TestWeightedShutTheBoxLab:
    def test_answer_file_exists(self):
        assert os.path.isfile("/app/answer.txt"), \
            "answer.txt not found at /app/answer.txt"

    def test_answer_format(self):
        lines = _read_answer()
        assert len(lines) == 6, f"Expected 6 lines, got {len(lines)}"
        p, q = int(lines[0]), int(lines[1])
        assert p >= 0, "p must be non-negative"
        assert q > 0, "q must be positive"
        assert gcd(p, q) == 1, \
            f"p/q not in lowest terms: gcd({p},{q})={gcd(p,q)}"
        a, b = int(lines[2]), int(lines[3])
        assert a >= 0, "a must be non-negative"
        assert b > 0, "b must be positive"
        assert gcd(a, b) == 1, \
            f"a/b not in lowest terms: gcd({a},{b})={gcd(a,b)}"
        assert lines[4] in ("A", "B", "C"), \
            f"Dice label must be A, B, or C, got '{lines[4]}'"
        div = int(lines[5])
        assert div >= 0, "policy_divergence_count must be non-negative"

    def test_expected_cost_correct(self):
        lines = _read_answer()
        p, q = int(lines[0]), int(lines[1])
        submitted = Fraction(p, q)
        assert submitted == _REF_EV, (
            f"Wrong expected cost: submitted {p}/{q} = "
            f"{float(submitted):.10f}, expected "
            f"{_REF_EV.numerator}/{_REF_EV.denominator} = "
            f"{float(_REF_EV):.10f}")

    def test_perfect_probability_correct(self):
        lines = _read_answer()
        a, b = int(lines[2]), int(lines[3])
        submitted = Fraction(a, b)
        assert submitted == _REF_PERF, (
            f"Wrong perfect game probability: submitted {a}/{b} = "
            f"{float(submitted):.12f}, expected "
            f"{_REF_PERF.numerator}/{_REF_PERF.denominator} = "
            f"{float(_REF_PERF):.12f}")

    def test_optimal_start_dice_correct(self):
        lines = _read_answer()
        submitted_dice = lines[4]
        assert submitted_dice == _REF_DICE, (
            f"Wrong optimal start dice: submitted '{submitted_dice}', "
            f"expected '{_REF_DICE}'")

    def test_policy_divergence_correct(self):
        lines = _read_answer()
        submitted_div = int(lines[5])
        assert submitted_div == _REF_DIV, (
            f"Wrong policy divergence count: submitted {submitted_div}, "
            f"expected {_REF_DIV}")
