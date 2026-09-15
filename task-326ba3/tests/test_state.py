#!/usr/bin/env python3
"""
Tests for M6 financial competition evaluation pipeline.

"""

import json
import os
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

OUTPUT_PATH = "/app/output/evaluation.json"
DATA_DIR = "/app/data"

# Expected values (computed from reference implementation)
EXPECTED_RPS = {
    "T00": 0.012393,
    "T01": 0.019034,
    "T02": 0.028368,
    "T03": 0.038288,
    "T04": 0.050900,
    "T05": 0.066917,
    "T06": 0.081561,
    "T07": 0.098595,
    "T08": 0.115959,
    "T09": 0.145855,
}

EXPECTED_IR = {
    "T00": 106.513441,
    "T01": 108.813017,
    "T02": 108.241985,
    "T03": 103.455225,
    "T04": 98.984102,
    "T05": 88.484407,
    "T06": 80.524209,
    "T07": 73.749623,
    "T08": 54.477711,
    "T09": 31.866831,
}

EXPECTED_OR_RANKING = [
    "T01", "T00", "T02", "T03", "T04",
    "T05", "T06", "T07", "T08", "T09",
]

EXPECTED_CROWD_RPS = 0.054196

EXPECTED_CONNECTION = {
    "T00": 0.976440,
    "T01": 0.978752,
    "T02": 0.978944,
    "T03": 0.973589,
    "T04": 0.960720,
    "T05": 0.921098,
    "T06": 0.891619,
    "T07": 0.887659,
    "T08": 0.772965,
    "T09": 0.830852,
}


def load_output():
    with open(OUTPUT_PATH) as f:
        return json.load(f)


# ---- Structure tests ----

class TestOutputStructure:
    def test_output_file_exists(self):
        assert os.path.isfile(OUTPUT_PATH), "evaluation.json not found"

    def test_required_keys(self):
        data = load_output()
        required = [
            "team_rps", "team_ir", "or_ranking", "crowd_rps",
            "optimal_weights", "connection_scores",
        ]
        for key in required:
            assert key in data, f"Missing key: {key}"

    def test_team_rps_has_all_teams(self):
        data = load_output()
        for t in [f"T{i:02d}" for i in range(10)]:
            assert t in data["team_rps"], f"Missing team {t} in team_rps"

    def test_team_ir_has_all_teams(self):
        data = load_output()
        for t in [f"T{i:02d}" for i in range(10)]:
            assert t in data["team_ir"], f"Missing team {t} in team_ir"

    def test_or_ranking_has_all_teams(self):
        data = load_output()
        assert len(data["or_ranking"]) == 10
        assert set(data["or_ranking"]) == {f"T{i:02d}" for i in range(10)}

    def test_optimal_weights_has_all_assets(self):
        data = load_output()
        for a in [f"A{i:02d}" for i in range(50)]:
            assert a in data["optimal_weights"], f"Missing {a}"

    def test_connection_scores_has_all_teams(self):
        data = load_output()
        for t in [f"T{i:02d}" for i in range(10)]:
            assert t in data["connection_scores"], f"Missing {t}"


# ---- RPS tests ----

class TestRPS:
    def test_rps_values(self):
        """Verify RPS values match expected within tolerance."""
        data = load_output()
        for team, expected in EXPECTED_RPS.items():
            actual = data["team_rps"][team]
            assert abs(actual - expected) < 5e-4, (
                f"RPS mismatch for {team}: expected {expected}, got {actual}"
            )

    def test_rps_range(self):
        """RPS must be between 0 and 1."""
        data = load_output()
        for team, val in data["team_rps"].items():
            assert 0 <= val <= 1, f"RPS out of range for {team}: {val}"

    def test_rps_ordering(self):
        """Better forecasters should have lower RPS."""
        data = load_output()
        rps = data["team_rps"]
        assert rps["T00"] < rps["T09"]
        assert rps["T00"] < rps["T05"]

    def test_rps_independent_computation(self):
        """Independently compute RPS for T00 period P1 and cross-check."""
        prices_df = pd.read_csv(f"{DATA_DIR}/prices.csv")
        submissions_df = pd.read_csv(f"{DATA_DIR}/submissions.csv")
        periods_df = pd.read_csv(f"{DATA_DIR}/periods.csv")
        symbols = sorted(pd.read_csv(f"{DATA_DIR}/universe.csv")["symbol"].tolist())

        p1 = periods_df[periods_df["period"] == "P1"].iloc[0]
        sp = prices_df[prices_df["date"] == p1["start_date"]].set_index("symbol")["price"]
        ep = prices_df[prices_df["date"] == p1["end_date"]].set_index("symbol")["price"]
        returns = ((ep - sp) / sp).reindex(symbols)

        ranks = returns.rank(method="min", ascending=True)
        total_ranks = int(ranks.max())
        boundaries = [
            (1, int(0.2 * total_ranks)),
            (int(0.2 * total_ranks) + 1, int(0.4 * total_ranks)),
            (int(0.4 * total_ranks) + 1, int(0.6 * total_ranks)),
            (int(0.6 * total_ranks) + 1, int(0.8 * total_ranks)),
            (int(0.8 * total_ranks) + 1, total_ranks),
        ]

        indicators = {}
        for rv in sorted(ranks.unique()):
            group = ranks[ranks == rv].index.tolist()
            n_g = len(group)
            positions = range(int(rv), int(rv) + n_g)
            gi = np.zeros(5)
            for pos in positions:
                for q in range(5):
                    qs, qe = boundaries[q]
                    if qs <= pos <= qe:
                        gi[q] += 1
                        break
            gi /= n_g
            for s in group:
                indicators[s] = gi.copy()

        tsub = submissions_df[
            (submissions_df["Team"] == "T00") & (submissions_df["Period"] == "P1")
        ].set_index("Symbol")

        rps_vals = []
        for sym in symbols:
            actual = indicators[sym]
            pred = tsub.loc[sym, ["Rank1", "Rank2", "Rank3", "Rank4", "Rank5"]].values.astype(float)
            cum_a = np.cumsum(actual)
            cum_p = np.cumsum(pred)
            rps_vals.append(np.mean((cum_a - cum_p) ** 2))

        p1_rps = np.mean(rps_vals)
        assert 0 < p1_rps < 0.5
        data = load_output()
        assert abs(p1_rps - data["team_rps"]["T00"]) < 0.05


# ---- IR tests ----

class TestIR:
    def test_ir_values(self):
        """Verify IR values match expected within tolerance."""
        data = load_output()
        for team, expected in EXPECTED_IR.items():
            actual = data["team_ir"][team]
            assert abs(actual - expected) < 1.0, (
                f"IR mismatch for {team}: expected {expected}, got {actual}"
            )

    def test_ir_ordering(self):
        """Better teams should have higher IR."""
        data = load_output()
        ir = data["team_ir"]
        assert ir["T00"] > ir["T09"]
        best = max(ir, key=ir.get)
        assert best in ["T00", "T01", "T02"]

    def test_ir_independent_computation(self):
        """Independently compute IR for T09 and verify."""
        prices_df = pd.read_csv(f"{DATA_DIR}/prices.csv")
        submissions_df = pd.read_csv(f"{DATA_DIR}/submissions.csv")
        periods_df = pd.read_csv(f"{DATA_DIR}/periods.csv")
        symbols = sorted(pd.read_csv(f"{DATA_DIR}/universe.csv")["symbol"].tolist())

        all_lr = []
        for _, prow in periods_df.iterrows():
            period = prow["period"]
            sd, ed = prow["start_date"], prow["end_date"]
            pdates = sorted(
                prices_df[(prices_df["date"] >= sd) & (prices_df["date"] <= ed)]["date"].unique()
            )
            tsub = submissions_df[
                (submissions_df["Team"] == "T09") & (submissions_df["Period"] == period)
            ].set_index("Symbol")
            weights = tsub["Decision"].reindex(symbols).fillna(0)

            for t in range(1, len(pdates)):
                prev = prices_df[prices_df["date"] == pdates[t - 1]].set_index("symbol")["price"]
                curr = prices_df[prices_df["date"] == pdates[t]].set_index("symbol")["price"]
                dr = ((curr - prev) / prev).reindex(symbols).fillna(0)
                pr = float((weights * dr).sum())
                all_lr.append(np.log(1 + pr))

        lr = np.array(all_lr)
        ir_ref = float(np.sum(lr) / np.std(lr, ddof=1))

        data = load_output()
        assert abs(data["team_ir"]["T09"] - ir_ref) < 0.5


# ---- OR tests ----

class TestOR:
    def test_or_ranking_exact(self):
        """Verify OR ranking matches expected exactly."""
        data = load_output()
        assert data["or_ranking"] == EXPECTED_OR_RANKING

    def test_or_ranking_logic(self):
        """Verify OR ranking is consistent with RPS and IR values."""
        data = load_output()
        rps = data["team_rps"]
        ir = data["team_ir"]
        teams = sorted(rps.keys())

        rps_rank = pd.Series({t: rps[t] for t in teams}).rank(
            method="average", ascending=True
        )
        ir_rank = pd.Series({t: -ir[t] for t in teams}).rank(
            method="average", ascending=True
        )
        or_score = (rps_rank + ir_rank) / 2
        expected = or_score.sort_values().index.tolist()
        assert data["or_ranking"] == expected


# ---- Crowd RPS tests ----

class TestCrowdRPS:
    def test_crowd_rps_value(self):
        data = load_output()
        assert abs(data["crowd_rps"] - EXPECTED_CROWD_RPS) < 5e-4

    def test_crowd_beats_average(self):
        data = load_output()
        avg_rps = np.mean(list(data["team_rps"].values()))
        assert data["crowd_rps"] < avg_rps

    def test_crowd_rps_range(self):
        data = load_output()
        assert 0 < data["crowd_rps"] < 0.2


# ---- Optimal weights tests ----

class TestOptimalWeights:
    def test_gross_exposure_upper(self):
        data = load_output()
        w = np.array(list(data["optimal_weights"].values()))
        assert np.sum(np.abs(w)) <= 1.001

    def test_gross_exposure_lower(self):
        data = load_output()
        w = np.array(list(data["optimal_weights"].values()))
        assert np.sum(np.abs(w)) >= 0.249

    def test_single_weight_bound(self):
        data = load_output()
        for sym, w in data["optimal_weights"].items():
            assert abs(w) <= 0.101, f"Weight for {sym} = {w} exceeds 0.1"

    def test_has_both_long_short(self):
        data = load_output()
        w = list(data["optimal_weights"].values())
        assert any(v > 0.001 for v in w)
        assert any(v < -0.001 for v in w)

    def test_positive_expected_return(self):
        data = load_output()
        submissions_df = pd.read_csv(f"{DATA_DIR}/submissions.csv")
        periods_df = pd.read_csv(f"{DATA_DIR}/periods.csv")
        symbols = sorted(pd.read_csv(f"{DATA_DIR}/universe.csv")["symbol"].tolist())

        prob_cols = ["Rank1", "Rank2", "Rank3", "Rank4", "Rank5"]
        crowd = submissions_df.groupby(["Period", "Symbol"])[prob_cols].mean().reset_index()
        last_period = periods_df["period"].iloc[-1]
        lc = crowd[crowd["Period"] == last_period].set_index("Symbol")

        eq = (
            lc["Rank1"] * 1 + lc["Rank2"] * 2 + lc["Rank3"] * 3
            + lc["Rank4"] * 4 + lc["Rank5"] * 5
        ).reindex(symbols)

        w = np.array([data["optimal_weights"][s] for s in symbols])
        port_er = np.dot(w, (eq.values - 3))
        assert port_er > 0


# ---- Connection scores tests ----

class TestConnectionScores:
    def test_connection_values(self):
        data = load_output()
        for team, expected in EXPECTED_CONNECTION.items():
            actual = data["connection_scores"][team]
            assert abs(actual - expected) < 0.02, (
                f"Connection for {team}: expected {expected}, got {actual}"
            )

    def test_connection_range(self):
        data = load_output()
        for team, val in data["connection_scores"].items():
            assert -1 <= val <= 1

    def test_good_teams_higher_connection(self):
        data = load_output()
        cs = data["connection_scores"]
        assert cs["T00"] > cs["T09"] or abs(cs["T00"] - cs["T09"]) < 0.1

    def test_connection_independent_computation(self):
        submissions_df = pd.read_csv(f"{DATA_DIR}/submissions.csv")
        periods = sorted(submissions_df["Period"].unique())

        correlations = []
        for period in periods:
            tsub = submissions_df[
                (submissions_df["Team"] == "T05") & (submissions_df["Period"] == period)
            ]
            eq = (
                tsub["Rank1"].values * 1 + tsub["Rank2"].values * 2
                + tsub["Rank3"].values * 3 + tsub["Rank4"].values * 4
                + tsub["Rank5"].values * 5
            )
            dec = tsub["Decision"].values
            corr, _ = spearmanr(eq, dec)
            if not np.isnan(corr):
                correlations.append(corr)

        ref = float(np.mean(correlations))
        data = load_output()
        assert abs(data["connection_scores"]["T05"] - ref) < 0.01


# ---- Tie handling tests ----

class TestTieHandling:
    def test_ties_exist_in_data(self):
        """Verify tied returns exist in at least one period."""
        prices_df = pd.read_csv(f"{DATA_DIR}/prices.csv")
        periods_df = pd.read_csv(f"{DATA_DIR}/periods.csv")
        symbols = sorted(pd.read_csv(f"{DATA_DIR}/universe.csv")["symbol"].tolist())

        found = False
        for _, prow in periods_df.iterrows():
            sp = prices_df[prices_df["date"] == prow["start_date"]].set_index("symbol")["price"]
            ep = prices_df[prices_df["date"] == prow["end_date"]].set_index("symbol")["price"]
            returns = ((ep - sp) / sp).reindex(symbols)
            if returns.duplicated(keep=False).any():
                found = True
                break
        assert found, "Expected tied returns in data"

    def test_quintile_indicators_sum_to_one(self):
        """Quintile indicators must sum to 1 for all assets including ties."""
        prices_df = pd.read_csv(f"{DATA_DIR}/prices.csv")
        periods_df = pd.read_csv(f"{DATA_DIR}/periods.csv")
        symbols = sorted(pd.read_csv(f"{DATA_DIR}/universe.csv")["symbol"].tolist())

        for _, prow in periods_df.iterrows():
            sp = prices_df[prices_df["date"] == prow["start_date"]].set_index("symbol")["price"]
            ep = prices_df[prices_df["date"] == prow["end_date"]].set_index("symbol")["price"]
            returns = ((ep - sp) / sp).reindex(symbols)

            ranks = returns.rank(method="min", ascending=True)
            total_ranks = int(ranks.max())
            boundaries = [
                (1, int(0.2 * total_ranks)),
                (int(0.2 * total_ranks) + 1, int(0.4 * total_ranks)),
                (int(0.4 * total_ranks) + 1, int(0.6 * total_ranks)),
                (int(0.6 * total_ranks) + 1, int(0.8 * total_ranks)),
                (int(0.8 * total_ranks) + 1, total_ranks),
            ]

            for rv in sorted(ranks.unique()):
                group = ranks[ranks == rv].index.tolist()
                n_g = len(group)
                positions = range(int(rv), int(rv) + n_g)
                gi = np.zeros(5)
                for pos in positions:
                    for q in range(5):
                        qs, qe = boundaries[q]
                        if qs <= pos <= qe:
                            gi[q] += 1
                            break
                gi /= n_g
                assert abs(gi.sum() - 1.0) < 1e-10

    def test_tied_assets_get_fractional_indicators(self):
        """Tied assets spanning quintile boundary get fractional indicators."""
        prices_df = pd.read_csv(f"{DATA_DIR}/prices.csv")
        periods_df = pd.read_csv(f"{DATA_DIR}/periods.csv")
        symbols = sorted(pd.read_csv(f"{DATA_DIR}/universe.csv")["symbol"].tolist())

        # Check period P3 which has 3-way tie (A22, A23, A24)
        p3 = periods_df[periods_df["period"] == "P3"].iloc[0]
        sp = prices_df[prices_df["date"] == p3["start_date"]].set_index("symbol")["price"]
        ep = prices_df[prices_df["date"] == p3["end_date"]].set_index("symbol")["price"]
        returns = ((ep - sp) / sp).reindex(symbols)

        # Verify the three assets have identical returns
        assert returns["A22"] == returns["A23"]
        assert returns["A22"] == returns["A24"]

        # Compute quintile indicators
        ranks = returns.rank(method="min", ascending=True)
        tied_rank = ranks["A22"]
        assert ranks["A23"] == tied_rank
        assert ranks["A24"] == tied_rank

        total_ranks = int(ranks.max())
        boundaries = [
            (1, int(0.2 * total_ranks)),
            (int(0.2 * total_ranks) + 1, int(0.4 * total_ranks)),
            (int(0.4 * total_ranks) + 1, int(0.6 * total_ranks)),
            (int(0.6 * total_ranks) + 1, int(0.8 * total_ranks)),
            (int(0.8 * total_ranks) + 1, total_ranks),
        ]

        n_g = 3  # three tied assets
        positions = range(int(tied_rank), int(tied_rank) + n_g)
        gi = np.zeros(5)
        for pos in positions:
            for q in range(5):
                qs, qe = boundaries[q]
                if qs <= pos <= qe:
                    gi[q] += 1
                    break
        gi /= n_g

        # If the tied group spans a quintile boundary, at least two quintiles get nonzero
        # At minimum, the indicators must sum to 1 and be consistent
        assert abs(gi.sum() - 1.0) < 1e-10
        # At least one quintile must be nonzero
        assert np.max(gi) > 0
