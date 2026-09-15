"""Initialize the analysis database with strategy notes."""

import sqlite3


def setup():
    conn = sqlite3.connect("/opt/ga_bench/benchmark_results.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS strategy_notes (
            strategy TEXT PRIMARY KEY,
            description TEXT,
            mathematical_form TEXT,
            known_issues TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            name TEXT PRIMARY KEY,
            description TEXT,
            has_variable_lengths INTEGER,
            has_weights INTEGER
        )
    """)

    notes = [
        ("naive_mean_scaling",
         "Mean CE per minibatch, averaged across GA steps",
         "(1/G) * sum_g[sum(CE_g) / n_g]",
         "Computes mean-of-means; diverges from mean-of-all when n_g differ"),
        ("global_token_count",
         "Pre-compute N_total, sum(CE)/N_total per step",
         "sum_g[sum(CE_g) / N_total] = sum(CE) / N_total",
         "Correct for unweighted; ignores importance weights when present"),
        ("per_step_weighted_mean",
         "Weighted mean per step, averaged across GA steps",
         "(1/G) * sum_g[sum(w*CE_g) / sum(w_g)]",
         "Mean-of-weighted-means != weighted-mean-of-all when sum(w_g) varies"),
        ("scaled_token_fraction",
         "Scale each step by token fraction n_g/N_total",
         "sum_g[weighted_mean_g * (n_g / N_total)]",
         "Correct unweighted; uses token fraction instead of weight fraction"),
    ]

    for name, desc, form, issues in notes:
        c.execute(
            "INSERT OR REPLACE INTO strategy_notes VALUES (?, ?, ?, ?)",
            (name, desc, form, issues),
        )

    scenarios = [
        ("uniform_unweighted",
         "Equal-length sequences, no importance weights", 0, 0),
        ("variable_unweighted",
         "Variable-length sequences, no importance weights", 1, 0),
        ("uniform_weighted",
         "Equal-length sequences, with per-token importance weights", 0, 1),
        ("variable_weighted",
         "Variable-length sequences, with per-token importance weights", 1, 1),
    ]

    for name, desc, var_len, has_w in scenarios:
        c.execute(
            "INSERT OR REPLACE INTO scenarios VALUES (?, ?, ?, ?)",
            (name, desc, var_len, has_w),
        )

    conn.commit()
    conn.close()
    print("Database initialized at /opt/ga_bench/benchmark_results.db")


if __name__ == "__main__":
    setup()
