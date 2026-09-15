#!/usr/bin/env python3

"""
Crafter Benchmark Methodology Audit solver.

Reverse-engineers achievement prerequisite DAG from game engine source,
designs IPS-weighted corrective metric, performs discrimination and
stability analyses, produces benchmark methodology verdict.
"""

import json
import math
import sqlite3

import yaml


def load_game_rules(path="/app/crafter/data.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def build_item_to_material(collect_rules):
    mapping = {}
    for material, info in collect_rules.items():
        for item in info["receive"]:
            mapping[item] = material
    return mapping


def build_dependency_graph(data):
    """Derive achievement prerequisites from game rules and source semantics."""
    achievements = data["achievements"]
    collect_rules = data["collect"]
    make_rules = data["make"]
    place_rules = data["place"]
    item_to_mat = build_item_to_material(collect_rules)

    deps = {ach: [] for ach in achievements}

    for ach in achievements:
        if ach.startswith("collect_"):
            item = ach[len("collect_"):]
            if item in item_to_mat:
                mat = item_to_mat[item]
                rule = collect_rules[mat]
                for tool in rule.get("require", {}):
                    deps[ach].append(f"make_{tool}")

        elif ach.startswith("make_"):
            item = ach[len("make_"):]
            if item in make_rules:
                rule = make_rules[item]
                for consumed in rule["uses"]:
                    deps[ach].append(f"collect_{consumed}")
                for structure in rule.get("nearby", []):
                    deps[ach].append(f"place_{structure}")

        elif ach.startswith("place_"):
            item = ach[len("place_"):]
            if item in place_rules:
                rule = place_rules[item]
                for consumed in rule["uses"]:
                    deps[ach].append(f"collect_{consumed}")

        elif ach == "eat_plant":
            # Plants are placed objects (objects.py Plant class).
            # Unlike Cow/Zombie/Skeleton which spawn naturally (worldgen.py),
            # Plant objects only exist via player placement action.
            deps[ach].append("place_plant")

    return {k: sorted(v) for k, v in deps.items()}


def compute_depths(deps):
    depth = {a: 0 for a in deps}
    changed = True
    while changed:
        changed = False
        for a in deps:
            for d in deps[a]:
                if depth[d] + 1 > depth[a]:
                    depth[a] = depth[d] + 1
                    changed = True
    return depth


def find_critical_path(deps, depths):
    deepest = max(deps.keys(), key=lambda a: depths[a])
    path = [deepest]
    current = deepest
    while deps[current]:
        pred = max(deps[current], key=lambda d: depths[d])
        path.append(pred)
        current = pred
    path.reverse()
    return path


def query_database(db_path="/app/episodes.db"):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    queries = []

    q1 = "SELECT agent, COUNT(*) FROM episodes GROUP BY agent"
    queries.append(q1 + ";")
    c.execute(q1)
    agent_counts = dict(c.fetchall())

    q2 = "SELECT COUNT(*) FROM episodes"
    queries.append(q2 + ";")
    c.execute(q2)
    total_episodes = c.fetchone()[0]

    q3 = ("SELECT agent, episode, achievement FROM achievements "
          "ORDER BY agent, episode, achievement")
    queries.append(q3 + ";")
    c.execute(q3)
    all_events = c.fetchall()

    episode_achs = {}
    for agent, ep, ach in all_events:
        key = (agent, ep)
        if key not in episode_achs:
            episode_achs[key] = set()
        episode_achs[key].add(ach)

    q4 = ("SELECT agent, achievement, COUNT(DISTINCT episode) as cnt "
          "FROM achievements GROUP BY agent, achievement")
    queries.append(q4 + ";")
    c.execute(q4)
    ach_counts = {}
    for agent, ach, cnt in c.fetchall():
        if agent not in ach_counts:
            ach_counts[agent] = {}
        ach_counts[agent][ach] = cnt

    q5 = ("SELECT achievement, COUNT(DISTINCT agent || '-' || episode) as cnt "
          "FROM achievements GROUP BY achievement")
    queries.append(q5 + ";")
    c.execute(q5)
    overall_counts = dict(c.fetchall())

    conn.close()

    with open("/app/queries.sql", "w") as f:
        f.write("-- Crafter benchmark methodology audit SQL queries\n\n")
        for q in queries:
            f.write(q + "\n\n")

    return (agent_counts, total_episodes, episode_achs,
            ach_counts, overall_counts)


def detect_anomalies(episode_achs, deps):
    anomalies = []
    for (agent, ep), achs in sorted(episode_achs.items()):
        for ach in sorted(achs):
            if ach not in deps:
                continue
            missing = [p for p in deps[ach] if p not in achs]
            if missing:
                anomalies.append({
                    "agent": agent,
                    "episode": ep,
                    "achievement": ach,
                    "missing_prerequisites": sorted(missing),
                })
    return anomalies


def compute_agent_rates(agents, agent_counts, ach_counts, achievements):
    rates = {}
    for agent in sorted(agents):
        n = agent_counts[agent]
        rates[agent] = {}
        for ach in achievements:
            cnt = ach_counts.get(agent, {}).get(ach, 0)
            rates[agent][ach] = cnt / n
    return rates


def compute_overall_rates(overall_counts, total_episodes, achievements):
    return {ach: overall_counts.get(ach, 0) / total_episodes
            for ach in achievements}


def geo_mean_score(rates, achievements):
    log_sum = sum(math.log(max(rates[a], 0.01)) for a in achievements)
    return math.exp(log_sum / len(achievements))


def depth_weighted_score(rates, depths, achievements):
    total_weight = sum(depths[a] + 1 for a in achievements)
    weighted = sum(rates[a] * (depths[a] + 1) for a in achievements)
    return weighted / total_weight


def ips_weighted_score(rates, overall_rates, achievements):
    raw_weights = {a: 1.0 / max(overall_rates[a], 0.05) for a in achievements}
    total_w = sum(raw_weights.values())
    return sum(rates[a] * raw_weights[a] / total_w for a in achievements)


def compute_all_scores(agent_rates, depths, overall_rates, achievements,
                       agents):
    scores = {}
    for agent in agents:
        r = agent_rates[agent]
        scores[agent] = {
            "geometric_mean": round(
                geo_mean_score(r, achievements), 6),
            "depth_weighted": round(
                depth_weighted_score(r, depths, achievements), 6),
            "ips_weighted": round(
                ips_weighted_score(r, overall_rates, achievements), 6),
        }
    return scores


def compute_rankings(scores, agents):
    metrics = ["geometric_mean", "depth_weighted", "ips_weighted"]
    rankings = {}
    for m in metrics:
        rankings[f"by_{m}"] = sorted(
            agents, key=lambda a: scores[a][m], reverse=True)
    return rankings


def compute_discrimination(scores, rankings):
    metrics = ["geometric_mean", "depth_weighted", "ips_weighted"]
    discrimination = {}
    for m in metrics:
        ranking = rankings[f"by_{m}"]
        pairs = []
        for i in range(len(ranking) - 1):
            higher = ranking[i]
            lower = ranking[i + 1]
            gap = scores[higher][m] - scores[lower][m]
            cls = "significant" if gap > 0.03 else "marginal"
            pairs.append({
                "higher": higher,
                "lower": lower,
                "gap": round(gap, 6),
                "class": cls,
            })
        discrimination[m] = pairs
    return discrimination


def compute_ranking_for_metric(agent_rates, depths, overall_rates,
                               achievements, agents, metric):
    """Compute ranking for a single metric over given achievements."""
    agent_score_pairs = []
    for agent in agents:
        r = agent_rates[agent]
        if metric == "geometric_mean":
            s = geo_mean_score(r, achievements)
        elif metric == "depth_weighted":
            s = depth_weighted_score(r, depths, achievements)
        elif metric == "ips_weighted":
            s = ips_weighted_score(r, overall_rates, achievements)
        agent_score_pairs.append((agent, s))
    agent_score_pairs.sort(key=lambda x: x[1], reverse=True)
    return [a for a, _ in agent_score_pairs]


def compute_stability(agent_rates, depths, overall_rates,
                      all_achievements, agents, full_rankings):
    metrics = ["geometric_mean", "depth_weighted", "ips_weighted"]
    stability = {}

    for m in metrics:
        full_rank = full_rankings[f"by_{m}"]
        flip_details = {}

        for exclude_ach in all_achievements:
            remaining = [a for a in all_achievements if a != exclude_ach]
            loo_rank = compute_ranking_for_metric(
                agent_rates, depths, overall_rates, remaining, agents, m)

            flips = []
            for i in range(len(agents)):
                for j in range(i + 1, len(agents)):
                    a, b = sorted([agents[i], agents[j]])
                    full_a_first = full_rank.index(a) < full_rank.index(b)
                    loo_a_first = loo_rank.index(a) < loo_rank.index(b)
                    if full_a_first != loo_a_first:
                        flips.append([a, b])

            if flips:
                flips.sort()
                flip_details[exclude_ach] = flips

        stability[m] = {
            "flip_count": len(flip_details),
            "details": flip_details,
        }

    return stability


def compute_verdict(discrimination, stability):
    metrics = ["geometric_mean", "depth_weighted", "ips_weighted"]

    sig_counts = {}
    for m in metrics:
        sig_counts[m] = sum(
            1 for p in discrimination[m] if p["class"] == "significant")

    flip_counts = {m: stability[m]["flip_count"] for m in metrics}

    max_sig = max(sig_counts.values())
    most_disc = sorted(
        [m for m in metrics if sig_counts[m] == max_sig])[0]

    min_flips = min(flip_counts.values())
    most_stable = sorted(
        [m for m in metrics if flip_counts[m] == min_flips])[0]

    if most_disc == most_stable:
        recommended = most_disc
    else:
        rec_scores = {}
        for m in metrics:
            disc_ratio = sig_counts[m] / 3.0
            stab_ratio = 1.0 - flip_counts[m] / 22.0
            rec_scores[m] = disc_ratio * stab_ratio
        max_rec = max(rec_scores.values())
        recommended = sorted(
            [m for m in metrics
             if abs(rec_scores[m] - max_rec) < 1e-9])[0]

    ach_metric_count = {}
    for m in metrics:
        for ach in stability[m]["details"]:
            ach_metric_count[ach] = ach_metric_count.get(ach, 0) + 1
    pivotal = sorted([a for a, c in ach_metric_count.items() if c >= 2])

    return {
        "most_discriminating": most_disc,
        "most_stable": most_stable,
        "recommended": recommended,
        "pivotal_achievements": pivotal,
    }


def generate_dot(deps, filepath="/app/achievement_dag.dot"):
    lines = ["digraph achievement_prerequisites {"]
    for ach in sorted(deps.keys()):
        lines.append(f'  "{ach}";')
    for ach in sorted(deps.keys()):
        for prereq in deps[ach]:
            lines.append(f'  "{prereq}" -> "{ach}";')
    lines.append("}")
    with open(filepath, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    data = load_game_rules()
    achievements = sorted(data["achievements"])

    deps = build_dependency_graph(data)
    depths = compute_depths(deps)
    critical_path = find_critical_path(deps, depths)

    (agent_counts, total_episodes, episode_achs,
     ach_counts, overall_counts) = query_database()

    agents = sorted(agent_counts.keys())
    anomalies = detect_anomalies(episode_achs, deps)

    agent_rates = compute_agent_rates(
        agents, agent_counts, ach_counts, achievements)
    overall_rates = compute_overall_rates(
        overall_counts, total_episodes, achievements)

    scores = compute_all_scores(
        agent_rates, depths, overall_rates, achievements, agents)
    rankings = compute_rankings(scores, agents)
    discrimination = compute_discrimination(scores, rankings)
    stability = compute_stability(
        agent_rates, depths, overall_rates,
        achievements, agents, rankings)
    verdict = compute_verdict(discrimination, stability)

    audit = {
        "dependency_graph": deps,
        "depths": depths,
        "critical_path": critical_path,
        "anomalies": anomalies,
        "metric_scores": scores,
        "rankings": rankings,
        "discrimination": discrimination,
        "stability": stability,
        "verdict": verdict,
    }

    with open("/app/audit.json", "w") as f:
        json.dump(audit, f, indent=2)

    generate_dot(deps)

    print("Audit complete:")
    print(f"  /app/audit.json")
    print(f"  /app/achievement_dag.dot")
    print(f"  /app/queries.sql")
    print(f"  Anomalies: {len(anomalies)}")
    for m in ["geometric_mean", "depth_weighted", "ips_weighted"]:
        r = rankings[f"by_{m}"]
        print(f"  {m} ranking: {r}")
    print(f"  Verdict: {verdict['recommended']} recommended")


if __name__ == "__main__":
    main()
