"""Main evaluation pipeline orchestrator.

"""

import json
import os

from .config import DATA_DIR, RESULTS_FILE, FRAMEWORK_PARSER_MAP
from .parsers import PARSERS
from .build_checker import check_compile_success
from .aggregator import (
    compute_language_pair_stats,
    compute_overall_stats,
    compute_directional_analysis,
)
from .framework_analyzer import compute_framework_analysis


def run_evaluation():
    """Run the full evaluation pipeline."""
    with open(os.path.join(DATA_DIR, "manifest.json")) as f:
        manifest = json.load(f)

    all_projects = {}
    project_metadata = {}
    projects_by_pair = {}

    for proj_info in manifest["projects"]:
        proj_id = proj_info["id"]
        proj_dir = os.path.join(DATA_DIR, "projects", proj_id)

        with open(os.path.join(proj_dir, "meta.json")) as f:
            meta = json.load(f)
        with open(os.path.join(proj_dir, "build.log")) as f:
            build_log = f.read()
        with open(os.path.join(proj_dir, "test.log")) as f:
            test_log = f.read()

        project_metadata[proj_id] = meta
        compile_ok = check_compile_success(build_log, meta)

        if compile_ok:
            framework = meta.get("test_framework", "")
            parser_name = FRAMEWORK_PARSER_MAP.get(framework, framework)
            parser = PARSERS.get(parser_name)
            if parser:
                passed, total = parser(test_log)
            else:
                passed, total = 0, 0
        else:
            passed, total = 0, 0

        rate = passed / total if total > 0 else 0.0
        all_pass = total > 0 and passed == total

        proj_result = {
            "source_lang": meta["source_language"],
            "target_lang": meta["target_language"],
            "compile_success": compile_ok,
            "tests_passed": passed,
            "tests_total": total,
            "pass_rate": round(rate, 4),
            "all_tests_pass": all_pass,
        }

        all_projects[proj_id] = proj_result
        pair_key = f"{proj_result['source_lang']}_to_{proj_result['target_lang']}"
        projects_by_pair.setdefault(pair_key, []).append(proj_result)

    lp_stats = compute_language_pair_stats(projects_by_pair)
    overall = compute_overall_stats(all_projects)
    directional = compute_directional_analysis(projects_by_pair)
    fw_analysis = compute_framework_analysis(all_projects, project_metadata)

    result = {
        "projects": all_projects,
        "language_pairs": lp_stats,
        "overall": overall,
        "directional_analysis": directional,
        "framework_analysis": fw_analysis,
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Results written to {RESULTS_FILE}")


if __name__ == "__main__":
    run_evaluation()
