"""Statistics aggregation for benchmark evaluation results."""

from .config import DYNAMIC_LANGUAGES, STATIC_LANGUAGES


def compute_language_pair_stats(projects_by_pair):
    """Compute per-language-pair aggregate statistics."""
    result = {}
    for pair_key, projs in projects_by_pair.items():
        n = len(projs)
        compile_count = sum(1 for p in projs if p["compile_success"])
        success_count = sum(1 for p in projs if p["all_tests_pass"])
        avg_pass = sum(
            p["tests_passed"] / p["tests_total"] if p["tests_total"] > 0 else 0.0
            for p in projs
        ) / n
        result[pair_key] = {
            "num_projects": n,
            "compile_rate": round(compile_count / n, 4),
            "success_rate": round(success_count / n, 4),
            "avg_pass_rate": round(avg_pass, 4),
        }
    return result


def compute_overall_stats(all_projects):
    """Compute overall benchmark statistics."""
    n = len(all_projects)
    compile_count = sum(1 for p in all_projects.values() if p["compile_success"])
    success_count = sum(1 for p in all_projects.values() if p["all_tests_pass"])

    compiled_projects = [p for p in all_projects.values() if p["compile_success"]]
    avg_pass = sum(
        p["tests_passed"] / p["tests_total"] if p["tests_total"] > 0 else 0.0
        for p in compiled_projects
    ) / len(compiled_projects)

    return {
        "total_projects": n,
        "compile_rate": round(compile_count / n, 4),
        "success_rate": round(success_count / n, 4),
        "avg_pass_rate": round(avg_pass, 4),
    }


def compute_directional_analysis(projects_by_pair):
    """Compute directional analysis (dynamic-to-static vs static-to-dynamic)."""
    d2s_pairs = []
    s2d_pairs = []

    for pair_key, projs in projects_by_pair.items():
        src = projs[0]["source_lang"]
        tgt = projs[0]["target_lang"]
        if src in DYNAMIC_LANGUAGES and tgt in STATIC_LANGUAGES:
            d2s_pairs.append(pair_key)
        elif src in STATIC_LANGUAGES and tgt in DYNAMIC_LANGUAGES:
            s2d_pairs.append(pair_key)

    def stats_for_pairs(pair_keys):
        all_projs = []
        for pk in pair_keys:
            all_projs.extend(projects_by_pair[pk])
        n = len(all_projs)
        if n == 0:
            return {
                "pairs": sorted(pair_keys),
                "num_projects": 0,
                "compile_rate": 0.0,
                "success_rate": 0.0,
                "avg_pass_rate": 0.0,
            }

        compile_count = sum(1 for p in all_projs if p["compile_success"])
        success_count = sum(1 for p in all_projs if p["all_tests_pass"])

        compiled = [p for p in all_projs if p["compile_success"]]
        avg_pass = (
            sum(
                p["tests_passed"] / p["tests_total"]
                if p["tests_total"] > 0
                else 0.0
                for p in compiled
            )
            / len(compiled)
            if compiled
            else 0.0
        )

        return {
            "pairs": sorted(pair_keys),
            "num_projects": n,
            "compile_rate": round(compile_count / n, 4),
            "success_rate": round(success_count / n, 4),
            "avg_pass_rate": round(avg_pass, 4),
        }

    return {
        "dynamic_to_static": stats_for_pairs(d2s_pairs),
        "static_to_dynamic": stats_for_pairs(s2d_pairs),
    }
