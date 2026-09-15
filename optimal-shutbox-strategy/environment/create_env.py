#!/usr/bin/env python3
"""Setup script for the optimization lab environment.
Run during Docker build to create the research workspace."""

import sqlite3
import json
import os
import subprocess
import tarfile
import base64

LAB_DIR = "/app/lab"


def main():
    for d in ["backups", "configs", "logs", "notes"]:
        os.makedirs(f"{LAB_DIR}/{d}", exist_ok=True)

    # ===== Create SQLite Database =====
    DB_PATH = "/tmp/game_variants.db"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE experiments (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        tile_range TEXT NOT NULL,
        status TEXT NOT NULL,
        config_version TEXT,
        created_date TEXT
    )""")

    c.execute("""CREATE TABLE dice_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER NOT NULL,
        option_label TEXT NOT NULL,
        encoding TEXT NOT NULL DEFAULT 'json',
        config_data TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments(id)
    )""")

    c.execute("""CREATE TABLE scoring_config (
        experiment_id INTEGER PRIMARY KEY,
        config_type TEXT NOT NULL,
        config_ref TEXT NOT NULL,
        encryption TEXT DEFAULT NULL,
        passphrase_ref TEXT DEFAULT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments(id)
    )""")

    c.execute("""CREATE TABLE experiment_tags (
        experiment_id INTEGER NOT NULL,
        tag TEXT NOT NULL,
        PRIMARY KEY (experiment_id, tag),
        FOREIGN KEY (experiment_id) REFERENCES experiments(id)
    )""")

    c.execute("""CREATE TABLE benchmark_results (
        experiment_id INTEGER NOT NULL,
        metric TEXT NOT NULL,
        value_encoded TEXT,
        encoding TEXT DEFAULT 'plain',
        notes TEXT,
        PRIMARY KEY (experiment_id, metric)
    )""")

    c.execute("""CREATE TABLE simulation_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id INTEGER NOT NULL,
        strategy TEXT NOT NULL,
        num_games INTEGER NOT NULL,
        mean_score REAL NOT NULL,
        std_score REAL NOT NULL,
        min_score INTEGER NOT NULL,
        max_score INTEGER NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES experiments(id)
    )""")

    c.execute("""CREATE VIEW active_experiments AS
        SELECT e.*, GROUP_CONCAT(t.tag, ', ') as tags
        FROM experiments e
        LEFT JOIN experiment_tags t ON e.id = t.experiment_id
        WHERE e.status IN ('challenge', 'active', 'verified')
        GROUP BY e.id
    """)

    c.execute("""CREATE VIEW challenge_dice AS
        SELECT d.option_label, d.encoding, d.config_data
        FROM dice_options d
        JOIN experiments e ON d.experiment_id = e.id
        WHERE e.status = 'challenge'
        ORDER BY d.option_label
    """)

    experiments = [
        (1, "basic_6tile", "Standard 6-tile Shut the Box with 1d6",
         "1-6", "verified", "1.0", "2024-01-15"),
        (2, "extended_9tile", "9-tile variant with 2d6",
         "1-9", "completed", "1.0", "2024-02-20"),
        (3, "classic_9tile_1d6", "Classic 9-tile with 1d6 only",
         "1-9", "verified", "1.0", "2024-03-10"),
        (4, "large_12tile_2d6", "12-tile with standard 2d6",
         "1-12", "completed", "1.0", "2024-04-05"),
        (5, "mixed_9tile", "9-tile with d6+d4 option",
         "1-9", "verified", "1.0", "2024-05-18"),
        (6, "weighted_6tile", "6-tile with weighted scoring",
         "1-6", "completed", "2.1", "2024-06-22"),
        (7, "weighted_12tile_multi",
         "12-tile weighted scoring with multi-dice options",
         "1-12", "challenge", "2.1", "2024-07-30"),
        (8, "extreme_15tile", "15-tile experimental variant",
         "1-15", "pending", "1.0", "2024-08-12"),
    ]
    c.executemany("INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?)",
                  experiments)

    tags = [
        (1, "basic"), (1, "baseline"),
        (2, "extended"), (2, "2d6"),
        (3, "classic"), (3, "1d6"),
        (4, "large"), (4, "2d6"),
        (5, "mixed"), (5, "multi-dice"),
        (6, "weighted"), (6, "small"),
        (7, "weighted"), (7, "multi-dice"), (7, "challenge-active"),
        (8, "experimental"),
    ]
    c.executemany("INSERT INTO experiment_tags VALUES (?, ?)", tags)

    simple_dice = [
        (1, 'A', 'json', json.dumps({"dice": [{"sides": 6}]})),
        (2, 'A', 'json', json.dumps({"dice": [{"sides": 6}, {"sides": 6}]})),
        (3, 'A', 'json', json.dumps({"dice": [{"sides": 6}]})),
        (4, 'A', 'json', json.dumps({"dice": [{"sides": 6}, {"sides": 6}]})),
        (5, 'A', 'json', json.dumps({"dice": [{"sides": 6}, {"sides": 4}]})),
        (6, 'A', 'json', json.dumps({"dice": [{"sides": 6}]})),
    ]
    c.executemany(
        "INSERT INTO dice_options "
        "(experiment_id, option_label, encoding, config_data) "
        "VALUES (?, ?, ?, ?)", simple_dice)

    dice_A = json.dumps({"dice": [{"sides": 6}, {"sides": 6}]})
    dice_B = json.dumps({"dice": [{"sides": 4}, {"sides": 4}, {"sides": 4}]})
    dice_C = json.dumps({"dice": [{"sides": 6}, {"sides": 8}]})

    exp7_dice = [
        (7, 'A', 'base64', base64.b64encode(dice_A.encode()).decode()),
        (7, 'B', 'base64', base64.b64encode(dice_B.encode()).decode()),
        (7, 'C', 'base64', base64.b64encode(dice_C.encode()).decode()),
    ]
    c.executemany(
        "INSERT INTO dice_options "
        "(experiment_id, option_label, encoding, config_data) "
        "VALUES (?, ?, ?, ?)", exp7_dice)

    c.execute(
        "INSERT INTO dice_options "
        "(experiment_id, option_label, encoding, config_data) "
        "VALUES (8, 'A', 'json', ?)",
        [json.dumps({"dice": [{"sides": 6}, {"sides": 6}, {"sides": 6}]})])

    scoring_configs = [
        (1, "uniform", "default", None, None),
        (2, "uniform", "default", None, None),
        (3, "uniform", "default", None, None),
        (4, "uniform", "default", None, None),
        (5, "uniform", "default", None, None),
        (6, "file", "configs/exp6_scoring.json", None, None),
        (7, "file", "configs/scoring_weights_exp7.enc",
         "aes-256-cbc", "backup:research_data/keys/decrypt_passphrase.txt"),
        (8, "uniform", "default", None, None),
    ]
    c.executemany("INSERT INTO scoring_config VALUES (?, ?, ?, ?, ?)",
                  scoring_configs)

    benchmark_results = [
        (1, "optimal_expected_score", "317/120", "fraction",
         "Verified independently"),
        (3, "optimal_expected_score", "8753/1296", "fraction",
         "Exact rational value"),
        (5, "optimal_expected_score", "4219/720", "fraction",
         "Exact rational value"),
    ]
    c.executemany("INSERT INTO benchmark_results VALUES (?, ?, ?, ?, ?)",
                  benchmark_results)

    sim_stats = [
        (7, "random_uniform", 500000, 89.42, 38.71, 0, 188),
        (7, "greedy_max_tile", 500000, 52.18, 31.55, 0, 188),
        (7, "greedy_min_ev", 500000, 34.76, 25.12, 0, 188),
    ]
    for exp_id, strategy, num, mean, std, min_s, max_s in sim_stats:
        c.execute(
            "INSERT INTO simulation_stats "
            "(experiment_id, strategy, num_games, mean_score, "
            "std_score, min_score, max_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (exp_id, strategy, num, mean, std, min_s, max_s))

    conn.commit()
    conn.close()

    # ===== Create Scoring Weights JSON (to be encrypted) =====
    scoring_weights = {
        "experiment_id": 7,
        "scoring_version": "2.1",
        "method": "weighted_penalty",
        "description": (
            "Tiles in higher tiers incur larger penalties "
            "when left open at game end"),
        "tiers": [
            {"tiles": [1, 2, 3, 4], "multiplier": 1},
            {"tiles": [5, 6, 7, 8], "multiplier": 2},
            {"tiles": [9, 10, 11, 12], "multiplier": 3}
        ]
    }
    scoring_json_path = "/tmp/scoring_weights_exp7.json"
    with open(scoring_json_path, 'w') as f:
        json.dump(scoring_weights, f, indent=2)

    # ===== Create Passphrase and Encrypt =====
    PASSPHRASE = "lab-shutbox-7xK9mP"
    passphrase_path = "/tmp/decrypt_passphrase.txt"
    with open(passphrase_path, 'w') as f:
        f.write(PASSPHRASE)

    subprocess.run([
        "openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt",
        "-pass", f"pass:{PASSPHRASE}",
        "-in", scoring_json_path,
        "-out", f"{LAB_DIR}/configs/scoring_weights_exp7.enc"
    ], check=True)

    # ===== Create Tar.gz Backup with DB and Passphrase =====
    with tarfile.open(
            f"{LAB_DIR}/backups/research_data_20240730.tar.gz", "w:gz") as tar:
        tar.add(DB_PATH, arcname="research_data/game_variants.db")
        tar.add(passphrase_path,
                arcname="research_data/keys/decrypt_passphrase.txt")

    # ===== Create Metadata Registry JSON =====
    metadata = {
        "registry_version": "3.2",
        "lab_id": "combinatorial-opt-lab",
        "experiments": {
            "1": {"name": "basic_6tile", "status": "verified",
                  "scoring": {"type": "uniform"}},
            "2": {"name": "extended_9tile", "status": "completed",
                  "scoring": {"type": "uniform"}},
            "3": {"name": "classic_9tile_1d6", "status": "verified",
                  "scoring": {"type": "uniform"}},
            "4": {"name": "large_12tile_2d6", "status": "completed",
                  "scoring": {"type": "uniform"}},
            "5": {"name": "mixed_9tile", "status": "verified",
                  "scoring": {"type": "uniform"}},
            "6": {"name": "weighted_6tile", "status": "completed",
                  "scoring": {"type": "file",
                              "path": "configs/exp6_scoring.json"}},
            "7": {
                "name": "weighted_12tile_multi",
                "status": "challenge",
                "priority": "high",
                "scoring": {
                    "type": "encrypted_file",
                    "path": "configs/scoring_weights_exp7.enc",
                    "cipher": "aes-256-cbc",
                    "kdf": "pbkdf2",
                    "passphrase_location": (
                        "backup_archive::"
                        "research_data/keys/decrypt_passphrase.txt")
                },
                "dice_encoding": "base64",
                "analysis_requirements": [
                    "optimal_expected_cost_fraction",
                    "perfect_game_probability_under_optimal_policy",
                    "policy_divergence_count"
                ],
                "notes": (
                    "Dice configs are base64-encoded in DB. "
                    "Scoring weights encrypted. "
                    "All results must be exact rational numbers.")
            },
            "8": {"name": "extreme_15tile", "status": "pending",
                  "scoring": {"type": "uniform"}}
        }
    }
    with open(f"{LAB_DIR}/configs/metadata_registry.json", 'w') as f:
        json.dump(metadata, f, indent=2)

    # ===== Create Exp6 Scoring (unencrypted reference) =====
    exp6_scoring = {
        "experiment_id": 6,
        "scoring_version": "2.1",
        "method": "weighted_penalty",
        "tiers": [
            {"tiles": [1, 2, 3], "multiplier": 1},
            {"tiles": [4, 5, 6], "multiplier": 2}
        ]
    }
    with open(f"{LAB_DIR}/configs/exp6_scoring.json", 'w') as f:
        json.dump(exp6_scoring, f, indent=2)

    # ===== Create Simulation Log =====
    log_lines = [
        "# ================================================",
        "# Simulation Report: Experiment 7",
        "# Strategy: greedy_min_ev",
        "# Date: 2024-08-15",
        "# ================================================",
        "#",
        "# Parameters loaded from experiment database",
        "# Tiles: 1-12",
        "# Dice options: A (2d6), B (3d4), C (d6+d8)",
        "# Scoring: weighted penalty (see scoring config)",
        "#",
        "# Total games simulated: 500000",
        "#",
        "# Results:",
        "#   Mean weighted score: 34.76",
        "#   Std deviation: 25.12",
        "#   Median score: 28.0",
        "#   Games with score 0 (perfect): 1247 (0.25%)",
        "#   Games with score > 100: 48921 (9.78%)",
        "#",
        "# Max possible weighted penalty: 188",
        "# Verify: (1+2+3+4)*1 + (5+6+7+8)*2 + (9+10+11+12)*3"
        " = 10+52+126 = 188",
        "#",
        "# NOTE: Optimal play should achieve a lower expected score",
        "# than any heuristic. The above is an upper bound.",
    ]
    with open(f"{LAB_DIR}/logs/simulator_run_20240815.log", 'w') as f:
        f.write('\n'.join(log_lines) + '\n')

    # ===== Create Researcher Journal =====
    journal = (
        "Research Lab - Combinatorial Optimization\n"
        "==========================================\n"
        "\n"
        "2024-08-01\n"
        "Set up experiment 7 with weighted scoring. The scoring config\n"
        "file has been encrypted per data governance policy. The\n"
        "passphrase is stored in the backup archive alongside the\n"
        "database snapshot.\n"
        "\n"
        "2024-07-30\n"
        "Database backup created:\n"
        "  backups/research_data_20240730.tar.gz\n"
        "The archive contains the SQLite database and key material.\n"
        "To restore: extract the archive, database is at\n"
        "  research_data/game_variants.db\n"
        "\n"
        "2024-07-28\n"
        "Note on experiment 7 dice configs: we switched to base64\n"
        "encoding for the challenge experiment's dice option configs\n"
        "in the database. Check the 'encoding' column in dice_options\n"
        "to determine how to decode each row.\n"
        "\n"
        "2024-07-15\n"
        "Reminder: experiment 7 scoring weights are NOT uniform. The\n"
        "penalty for leaving tiles open depends on their tier. The\n"
        "encrypted scoring config must be decrypted before use. See\n"
        "the scoring_config table for encryption method and the\n"
        "passphrase_ref column for a hint on locating the key.\n"
        "\n"
        "The metadata registry at configs/metadata_registry.json has\n"
        "the full experiment manifest including encryption details\n"
        "and analysis requirements.\n"
        "\n"
        "2024-07-10\n"
        "Database schema notes:\n"
        "- tile_range stored as 'start-end' text (e.g. '1-12')\n"
        "- dice configs may be json or base64 (check encoding col)\n"
        "- scoring_config.encryption indicates cipher if applicable\n"
        "- scoring_config.passphrase_ref hints at key location\n"
        "\n"
        "Game Rules:\n"
        "On each turn the player chooses one available dice option\n"
        "and rolls. They must shut a non-empty subset of open tiles\n"
        "whose face values sum exactly to the roll total. If no valid\n"
        "subset exists, the game ends. Score = weighted penalty of\n"
        "remaining open tiles. Score 0 = perfect game (all shut).\n"
        "Under optimal play, minimize expected final score at every\n"
        "decision point (both dice selection and subset selection).\n"
    )
    with open(f"{LAB_DIR}/notes/researcher_journal.txt", 'w') as f:
        f.write(journal)

    # ===== Cleanup temp files =====
    os.remove(DB_PATH)
    os.remove(scoring_json_path)
    os.remove(passphrase_path)

    print("Lab environment setup complete.")


if __name__ == "__main__":
    main()
