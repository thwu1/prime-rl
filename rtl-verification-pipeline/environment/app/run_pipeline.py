"""Main pipeline for mutation adequacy analysis."""
import json
import os
from harness.config import MUTATIONS_DIR, RTL_SOURCE, BUILD_DIR
from harness.compiler import compile_mutation
from harness.runner import run_simulation
from harness.parser import parse_results
from harness.scorer import compute_adequacy
from harness.reporter import generate_report


def load_mutations():
    """Load all mutation definitions."""
    mutations = []
    for fname in sorted(os.listdir(MUTATIONS_DIR)):
        if fname.endswith(".json"):
            with open(os.path.join(MUTATIONS_DIR, fname)) as f:
                mutations.append(json.load(f))
    return mutations


def apply_mutation(mutation, rtl_source):
    """Apply a mutation to the RTL source, return path to mutated file."""
    with open(rtl_source) as f:
        content = f.read()

    mutated = content.replace(mutation["original_line"], mutation["mutated_line"])

    mut_dir = os.path.join(BUILD_DIR, mutation["id"])
    os.makedirs(mut_dir, exist_ok=True)
    mut_path = os.path.join(mut_dir, "alu.v")
    with open(mut_path, "w") as f:
        f.write(mutated)

    return mut_path


def main():
    print("=" * 60)
    print("Mutation Adequacy Analysis Pipeline")
    print("=" * 60)

    mutations = load_mutations()
    print(f"\nLoaded {len(mutations)} mutations\n")

    results = []

    for mut in mutations:
        print(f"Processing {mut['id']}: {mut['title']}")

        mut_path = apply_mutation(mut, RTL_SOURCE)

        comp = compile_mutation(mut["id"], mut_path)
        if not comp["success"] or not comp["binary"]:
            print(f"  Compilation FAILED: {comp['stderr'][:200]}")
            results.append(
                {
                    "id": mut["id"],
                    "title": mut["title"],
                    "equivalent": mut["equivalent"],
                    "status": "BUILD_FAIL",
                    "tests": {"total": 0, "passed": 0, "failed": 0},
                }
            )
            continue

        sim = run_simulation(mut["id"], comp["binary"])

        test_results = parse_results(sim["log_path"])

        if test_results["failed"] > 0:
            status = "KILLED"
        else:
            status = "SURVIVED"

        results.append(
            {
                "id": mut["id"],
                "title": mut["title"],
                "equivalent": mut["equivalent"],
                "status": status,
                "tests": test_results,
            }
        )

        print(
            f"  Status: {status} ({test_results['passed']} pass, {test_results['failed']} fail)"
        )

    adequacy = compute_adequacy(results)

    report_path = generate_report(results, adequacy)
    print(f"\nReport written to {report_path}")

    print(f"\n{'=' * 60}")
    print("Pipeline Summary")
    print(f"{'=' * 60}")
    print(f"  Total: {adequacy['total_mutants']}")
    print(f"  Killed: {adequacy['killed']}")
    print(f"  Equivalent: {adequacy['equivalent']}")
    print(f"  Adequacy Score: {adequacy['adequacy_score']}")


if __name__ == "__main__":
    main()
