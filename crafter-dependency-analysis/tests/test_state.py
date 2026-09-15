
import json
import math
import os
import re
import sqlite3
import subprocess

import pytest


# === Ground truth: achievement dependency graph ===
EXPECTED_DEPS = {
    "collect_coal": ["make_wood_pickaxe"],
    "collect_diamond": ["make_iron_pickaxe"],
    "collect_drink": [],
    "collect_iron": ["make_stone_pickaxe"],
    "collect_sapling": [],
    "collect_stone": ["make_wood_pickaxe"],
    "collect_wood": [],
    "defeat_skeleton": [],
    "defeat_zombie": [],
    "eat_cow": [],
    "eat_plant": ["place_plant"],
    "make_iron_pickaxe": sorted(
        ["collect_coal", "collect_iron", "collect_wood",
         "place_furnace", "place_table"]
    ),
    "make_iron_sword": sorted(
        ["collect_coal", "collect_iron", "collect_wood",
         "place_furnace", "place_table"]
    ),
    "make_stone_pickaxe": sorted(
        ["collect_stone", "collect_wood", "place_table"]
    ),
    "make_stone_sword": sorted(
        ["collect_stone", "collect_wood", "place_table"]
    ),
    "make_wood_pickaxe": sorted(["collect_wood", "place_table"]),
    "make_wood_sword": sorted(["collect_wood", "place_table"]),
    "place_furnace": ["collect_stone"],
    "place_plant": ["collect_sapling"],
    "place_stone": ["collect_stone"],
    "place_table": ["collect_wood"],
    "wake_up": [],
}

EXPECTED_DEPTHS = {
    "collect_coal": 3, "collect_diamond": 7, "collect_drink": 0,
    "collect_iron": 5, "collect_sapling": 0, "collect_stone": 3,
    "collect_wood": 0, "defeat_skeleton": 0, "defeat_zombie": 0,
    "eat_cow": 0, "eat_plant": 2, "make_iron_pickaxe": 6,
    "make_iron_sword": 6, "make_stone_pickaxe": 4, "make_stone_sword": 4,
    "make_wood_pickaxe": 2, "make_wood_sword": 2, "place_furnace": 4,
    "place_plant": 1, "place_stone": 4, "place_table": 1, "wake_up": 0,
}

EXPECTED_CRITICAL_PATH = [
    "collect_wood", "place_table", "make_wood_pickaxe", "collect_stone",
    "make_stone_pickaxe", "collect_iron", "make_iron_pickaxe", "collect_diamond",
]

EXPECTED_ANOMALIES = [
    {"agent": "rnd", "episode": 2, "achievement": "collect_diamond",
     "missing_prerequisites": ["make_iron_pickaxe"]},
    {"agent": "rnd", "episode": 5, "achievement": "eat_plant",
     "missing_prerequisites": ["place_plant"]},
    {"agent": "rnd", "episode": 8, "achievement": "collect_stone",
     "missing_prerequisites": ["make_wood_pickaxe"]},
]

ALL_ACHIEVEMENTS = sorted(EXPECTED_DEPS.keys())
AGENTS = ["curious", "dreamer", "ppo", "rnd"]
METRICS = ["depth_weighted", "geometric_mean", "ips_weighted"]


# === Independent computation from database ===

def _geo_score(rates, achievements):
    log_sum = sum(math.log(max(rates[a], 0.01)) for a in achievements)
    return math.exp(log_sum / len(achievements))


def _dw_score(rates, depths, achievements):
    tw = sum(depths[a] + 1 for a in achievements)
    return sum(rates[a] * (depths[a] + 1) for a in achievements) / tw


def _ips_score(rates, overall_rates, achievements):
    raw_w = {a: 1.0 / max(overall_rates[a], 0.05) for a in achievements}
    tw = sum(raw_w.values())
    return sum(rates[a] * raw_w[a] / tw for a in achievements)


def _compute_ranking(agent_rates, overall_rates, depths, achievements,
                     agents, metric):
    scores = []
    for agent in agents:
        r = agent_rates[agent]
        if metric == "geometric_mean":
            s = _geo_score(r, achievements)
        elif metric == "depth_weighted":
            s = _dw_score(r, depths, achievements)
        elif metric == "ips_weighted":
            s = _ips_score(r, overall_rates, achievements)
        scores.append((agent, s))
    scores.sort(key=lambda x: x[1], reverse=True)
    return [a for a, _ in scores]


def _compute_from_db():
    """Compute all expected values directly from the database."""
    conn = sqlite3.connect("/app/episodes.db")
    c = conn.cursor()

    c.execute("SELECT agent, COUNT(*) FROM episodes GROUP BY agent")
    agent_ep_counts = dict(c.fetchall())
    total_episodes = sum(agent_ep_counts.values())

    agent_rates = {}
    for agent in AGENTS:
        agent_rates[agent] = {}
        n = agent_ep_counts[agent]
        for ach in ALL_ACHIEVEMENTS:
            c.execute(
                "SELECT COUNT(DISTINCT episode) FROM achievements "
                "WHERE agent=? AND achievement=?", (agent, ach))
            cnt = c.fetchone()[0]
            agent_rates[agent][ach] = cnt / n

    overall_rates = {}
    for ach in ALL_ACHIEVEMENTS:
        c.execute(
            "SELECT COUNT(DISTINCT agent || '-' || episode) "
            "FROM achievements WHERE achievement=?", (ach,))
        cnt = c.fetchone()[0]
        overall_rates[ach] = cnt / total_episodes

    conn.close()

    # Scores
    all_scores = {}
    for agent in AGENTS:
        r = agent_rates[agent]
        all_scores[agent] = {
            "geometric_mean": _geo_score(r, ALL_ACHIEVEMENTS),
            "depth_weighted": _dw_score(r, EXPECTED_DEPTHS, ALL_ACHIEVEMENTS),
            "ips_weighted": _ips_score(r, overall_rates, ALL_ACHIEVEMENTS),
        }

    # Rankings
    rankings = {}
    for m in METRICS:
        rankings[f"by_{m}"] = _compute_ranking(
            agent_rates, overall_rates, EXPECTED_DEPTHS,
            ALL_ACHIEVEMENTS, AGENTS, m)

    # Discrimination
    discrimination = {}
    for m in METRICS:
        ranking = rankings[f"by_{m}"]
        pairs = []
        for i in range(len(ranking) - 1):
            higher = ranking[i]
            lower = ranking[i + 1]
            gap = all_scores[higher][m] - all_scores[lower][m]
            cls = "significant" if gap > 0.03 else "marginal"
            pairs.append({"higher": higher, "lower": lower,
                          "gap": gap, "class": cls})
        discrimination[m] = pairs

    # Stability
    stability = {}
    for m in METRICS:
        full_rank = rankings[f"by_{m}"]
        flip_details = {}
        for exclude_ach in ALL_ACHIEVEMENTS:
            remaining = [a for a in ALL_ACHIEVEMENTS if a != exclude_ach]
            loo_rank = _compute_ranking(
                agent_rates, overall_rates, EXPECTED_DEPTHS,
                remaining, AGENTS, m)
            flips = []
            for i in range(len(AGENTS)):
                for j in range(i + 1, len(AGENTS)):
                    a, b = sorted([AGENTS[i], AGENTS[j]])
                    full_a_first = full_rank.index(a) < full_rank.index(b)
                    loo_a_first = loo_rank.index(a) < loo_rank.index(b)
                    if full_a_first != loo_a_first:
                        flips.append([a, b])
            if flips:
                flips.sort()
                flip_details[exclude_ach] = flips
        stability[m] = {"flip_count": len(flip_details),
                        "details": flip_details}

    # Verdict
    sig_counts = {}
    for m in METRICS:
        sig_counts[m] = sum(
            1 for p in discrimination[m] if p["class"] == "significant")
    flip_counts = {m: stability[m]["flip_count"] for m in METRICS}

    max_sig = max(sig_counts.values())
    most_disc = sorted(
        [m for m in METRICS if sig_counts[m] == max_sig])[0]

    min_flips = min(flip_counts.values())
    most_stable_m = sorted(
        [m for m in METRICS if flip_counts[m] == min_flips])[0]

    if most_disc == most_stable_m:
        recommended = most_disc
    else:
        rec_scores = {}
        for m in METRICS:
            rec_scores[m] = (sig_counts[m] / 3.0) * (
                1.0 - flip_counts[m] / 22.0)
        max_rec = max(rec_scores.values())
        recommended = sorted(
            [m for m in METRICS
             if abs(rec_scores[m] - max_rec) < 1e-9])[0]

    ach_metric_count = {}
    for m in METRICS:
        for ach in stability[m]["details"]:
            ach_metric_count[ach] = ach_metric_count.get(ach, 0) + 1
    pivotal = sorted([a for a, c in ach_metric_count.items() if c >= 2])

    verdict = {
        "most_discriminating": most_disc,
        "most_stable": most_stable_m,
        "recommended": recommended,
        "pivotal_achievements": pivotal,
    }

    return {
        "scores": all_scores,
        "rankings": rankings,
        "discrimination": discrimination,
        "stability": stability,
        "verdict": verdict,
    }


@pytest.fixture(scope="module")
def audit():
    with open("/app/audit.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected():
    return _compute_from_db()


# ========== Report Structure ==========

class TestStructure:
    def test_required_keys(self, audit):
        for key in ["dependency_graph", "depths", "critical_path",
                     "anomalies", "metric_scores", "rankings",
                     "discrimination", "stability", "verdict"]:
            assert key in audit, f"Missing key: {key}"

    def test_all_achievements_in_graph(self, audit):
        assert set(audit["dependency_graph"].keys()) == set(ALL_ACHIEVEMENTS)

    def test_all_achievements_in_depths(self, audit):
        assert set(audit["depths"].keys()) == set(ALL_ACHIEVEMENTS)

    def test_four_agents_in_scores(self, audit):
        assert set(audit["metric_scores"].keys()) == set(AGENTS)

    def test_three_metrics_per_agent(self, audit):
        for agent in AGENTS:
            s = audit["metric_scores"][agent]
            for m in METRICS:
                assert m in s, f"{agent} missing {m}"

    def test_ranking_keys(self, audit):
        for m in METRICS:
            assert f"by_{m}" in audit["rankings"]

    def test_discrimination_keys(self, audit):
        for m in METRICS:
            assert m in audit["discrimination"]

    def test_stability_keys(self, audit):
        for m in METRICS:
            assert m in audit["stability"]
            assert "flip_count" in audit["stability"][m]
            assert "details" in audit["stability"][m]

    def test_verdict_keys(self, audit):
        v = audit["verdict"]
        for key in ["most_discriminating", "most_stable",
                     "recommended", "pivotal_achievements"]:
            assert key in v, f"Verdict missing {key}"


# ========== Dependency Graph ==========

class TestDependencyGraph:
    @pytest.mark.parametrize("ach", ALL_ACHIEVEMENTS)
    def test_deps_correct(self, audit, ach):
        actual = sorted(audit["dependency_graph"][ach])
        expected = EXPECTED_DEPS[ach]
        assert actual == expected, (
            f"Deps for '{ach}': expected {expected}, got {actual}")


# ========== Topological Depths ==========

class TestDepths:
    @pytest.mark.parametrize("ach", ALL_ACHIEVEMENTS)
    def test_depth_correct(self, audit, ach):
        assert audit["depths"][ach] == EXPECTED_DEPTHS[ach]

    def test_max_depth_is_7(self, audit):
        assert max(audit["depths"].values()) == 7

    def test_depth_zero_count(self, audit):
        zeros = sum(1 for d in audit["depths"].values() if d == 0)
        assert zeros == 7


# ========== Critical Path ==========

class TestCriticalPath:
    def test_critical_path_nodes(self, audit):
        assert audit["critical_path"] == EXPECTED_CRITICAL_PATH

    def test_critical_path_length(self, audit):
        assert len(audit["critical_path"]) == 8

    def test_valid_chain(self, audit):
        path = audit["critical_path"]
        deps = audit["dependency_graph"]
        for i in range(len(path) - 1):
            assert path[i] in deps[path[i + 1]], (
                f"'{path[i]}' is not a prereq of '{path[i+1]}'")


# ========== Anomalies ==========

class TestAnomalies:
    def test_anomaly_count(self, audit):
        assert len(audit["anomalies"]) == 3

    def test_all_from_rnd(self, audit):
        for a in audit["anomalies"]:
            assert a["agent"] == "rnd"

    @pytest.mark.parametrize("idx", range(3))
    def test_anomaly_detail(self, audit, idx):
        actual = audit["anomalies"][idx]
        exp = EXPECTED_ANOMALIES[idx]
        assert actual["agent"] == exp["agent"]
        assert actual["episode"] == exp["episode"]
        assert actual["achievement"] == exp["achievement"]
        assert sorted(actual["missing_prerequisites"]) == sorted(
            exp["missing_prerequisites"])

    def test_anomalies_sorted(self, audit):
        keys = [(a["agent"], a["episode"], a["achievement"])
                for a in audit["anomalies"]]
        assert keys == sorted(keys)


# ========== Metric Scores ==========

class TestMetricScores:
    @pytest.mark.parametrize("agent", AGENTS)
    def test_geometric_mean(self, audit, expected, agent):
        actual = audit["metric_scores"][agent]["geometric_mean"]
        exp = expected["scores"][agent]["geometric_mean"]
        assert abs(actual - exp) < 0.005, (
            f"{agent} geo: expected {exp:.6f}, got {actual:.6f}")

    @pytest.mark.parametrize("agent", AGENTS)
    def test_depth_weighted(self, audit, expected, agent):
        actual = audit["metric_scores"][agent]["depth_weighted"]
        exp = expected["scores"][agent]["depth_weighted"]
        assert abs(actual - exp) < 0.005, (
            f"{agent} dw: expected {exp:.6f}, got {actual:.6f}")

    @pytest.mark.parametrize("agent", AGENTS)
    def test_ips_weighted(self, audit, expected, agent):
        actual = audit["metric_scores"][agent]["ips_weighted"]
        exp = expected["scores"][agent]["ips_weighted"]
        assert abs(actual - exp) < 0.005, (
            f"{agent} ips: expected {exp:.6f}, got {actual:.6f}")

    def test_scores_in_range(self, audit):
        for agent in AGENTS:
            s = audit["metric_scores"][agent]
            for m in METRICS:
                assert 0.0 <= s[m] <= 1.0, (
                    f"{agent} {m} out of range: {s[m]}")


# ========== Rankings ==========

class TestRankings:
    @pytest.mark.parametrize("metric", METRICS)
    def test_ranking(self, audit, expected, metric):
        actual = audit["rankings"][f"by_{metric}"]
        exp = expected["rankings"][f"by_{metric}"]
        assert actual == exp, (
            f"{metric} ranking: expected {exp}, got {actual}")

    def test_dreamer_always_first(self, audit):
        for m in METRICS:
            assert audit["rankings"][f"by_{m}"][0] == "dreamer", (
                f"dreamer not first in {m}")

    def test_rnd_always_last(self, audit):
        for m in METRICS:
            assert audit["rankings"][f"by_{m}"][-1] == "rnd", (
                f"rnd not last in {m}")


# ========== Discrimination ==========

class TestDiscrimination:
    @pytest.mark.parametrize("metric", METRICS)
    def test_three_pairs(self, audit, metric):
        assert len(audit["discrimination"][metric]) == 3

    @pytest.mark.parametrize("metric", METRICS)
    def test_gaps_match(self, audit, expected, metric):
        actual_pairs = audit["discrimination"][metric]
        exp_pairs = expected["discrimination"][metric]
        for i in range(3):
            assert actual_pairs[i]["higher"] == exp_pairs[i]["higher"]
            assert actual_pairs[i]["lower"] == exp_pairs[i]["lower"]
            assert abs(actual_pairs[i]["gap"] - exp_pairs[i]["gap"]) < 0.005

    @pytest.mark.parametrize("metric", METRICS)
    def test_gap_classes(self, audit, expected, metric):
        actual_pairs = audit["discrimination"][metric]
        exp_pairs = expected["discrimination"][metric]
        for i in range(3):
            assert actual_pairs[i]["class"] == exp_pairs[i]["class"], (
                f"{metric} pair {i}: expected class "
                f"'{exp_pairs[i]['class']}', got '{actual_pairs[i]['class']}'")

    def test_gaps_positive(self, audit):
        for m in METRICS:
            for p in audit["discrimination"][m]:
                assert p["gap"] > 0, (
                    f"{m}: negative gap between {p['higher']} and {p['lower']}")

    def test_valid_classes(self, audit):
        for m in METRICS:
            for p in audit["discrimination"][m]:
                assert p["class"] in ("significant", "marginal")


# ========== Stability ==========

class TestStability:
    @pytest.mark.parametrize("metric", METRICS)
    def test_flip_count(self, audit, expected, metric):
        actual_fc = audit["stability"][metric]["flip_count"]
        exp_fc = expected["stability"][metric]["flip_count"]
        assert actual_fc == exp_fc, (
            f"{metric} flip_count: expected {exp_fc}, got {actual_fc}")

    @pytest.mark.parametrize("metric", METRICS)
    def test_unstable_achievements(self, audit, expected, metric):
        actual_keys = set(audit["stability"][metric]["details"].keys())
        exp_keys = set(expected["stability"][metric]["details"].keys())
        assert actual_keys == exp_keys, (
            f"{metric} unstable achievements: "
            f"missing {exp_keys - actual_keys}, "
            f"extra {actual_keys - exp_keys}")

    @pytest.mark.parametrize("metric", METRICS)
    def test_flip_pairs(self, audit, expected, metric):
        actual_details = audit["stability"][metric]["details"]
        exp_details = expected["stability"][metric]["details"]
        for ach in exp_details:
            actual_pairs = [sorted(p) for p in actual_details.get(ach, [])]
            actual_pairs.sort()
            exp_pairs = [sorted(p) for p in exp_details[ach]]
            exp_pairs.sort()
            assert actual_pairs == exp_pairs, (
                f"{metric} flips for '{ach}': "
                f"expected {exp_pairs}, got {actual_pairs}")

    def test_details_only_flipping(self, audit):
        """Details should only contain achievements that cause flips."""
        for m in METRICS:
            fc = audit["stability"][m]["flip_count"]
            detail_count = len(audit["stability"][m]["details"])
            assert fc == detail_count, (
                f"{m}: flip_count={fc} but {detail_count} entries in details")


# ========== Verdict ==========

class TestVerdict:
    def test_most_discriminating(self, audit, expected):
        assert (audit["verdict"]["most_discriminating"]
                == expected["verdict"]["most_discriminating"])

    def test_most_stable(self, audit, expected):
        assert (audit["verdict"]["most_stable"]
                == expected["verdict"]["most_stable"])

    def test_recommended(self, audit, expected):
        assert (audit["verdict"]["recommended"]
                == expected["verdict"]["recommended"])

    def test_pivotal_achievements(self, audit, expected):
        actual = sorted(audit["verdict"]["pivotal_achievements"])
        exp = sorted(expected["verdict"]["pivotal_achievements"])
        assert actual == exp, (
            f"Pivotal: expected {exp}, got {actual}")

    def test_verdict_metrics_valid(self, audit):
        for key in ["most_discriminating", "most_stable", "recommended"]:
            assert audit["verdict"][key] in METRICS, (
                f"verdict.{key}='{audit['verdict'][key]}' not a valid metric")

    def test_pivotal_are_achievements(self, audit):
        for ach in audit["verdict"]["pivotal_achievements"]:
            assert ach in ALL_ACHIEVEMENTS, (
                f"Pivotal '{ach}' not a valid achievement")


# ========== DOT File ==========

class TestDotFile:
    def test_exists(self):
        assert os.path.exists("/app/achievement_dag.dot")

    def test_valid_graphviz(self):
        result = subprocess.run(
            ["dot", "-Tsvg", "/app/achievement_dag.dot", "-o", "/dev/null"],
            capture_output=True, text=True)
        assert result.returncode == 0, f"Invalid DOT: {result.stderr}"

    def test_is_digraph(self):
        with open("/app/achievement_dag.dot") as f:
            content = f.read()
        assert "digraph" in content.lower()

    def test_contains_all_achievements(self):
        with open("/app/achievement_dag.dot") as f:
            content = f.read()
        for ach in ALL_ACHIEVEMENTS:
            assert ach in content, f"'{ach}' not in DOT file"

    def test_edges_correct(self):
        with open("/app/achievement_dag.dot") as f:
            content = f.read()
        edges = set()
        for m in re.finditer(
                r'"?([a-z_]+)"?\s*->\s*"?([a-z_]+)"?', content):
            edges.add((m.group(1), m.group(2)))
        expected_edges = set()
        for ach, prereqs in EXPECTED_DEPS.items():
            for p in prereqs:
                expected_edges.add((p, ach))
        assert edges == expected_edges, (
            f"Missing: {expected_edges - edges}, Extra: {edges - expected_edges}")


# ========== SQL File ==========

class TestSqlFile:
    def test_exists(self):
        assert os.path.exists("/app/queries.sql")

    def test_nonempty(self):
        assert os.path.getsize("/app/queries.sql") > 50

    def test_valid_sql(self):
        result = subprocess.run(
            ["sqlite3", "/app/episodes.db"],
            stdin=open("/app/queries.sql"),
            capture_output=True, text=True)
        assert result.returncode == 0, (
            f"SQL execution failed: {result.stderr}")

    def test_contains_select(self):
        with open("/app/queries.sql") as f:
            content = f.read().upper()
        assert "SELECT" in content
        assert "FROM" in content
