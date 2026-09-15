#!/usr/bin/env python3
"""Implement missing pipeline components and fix incorrect implementations.

Issues to resolve:
1. extract.sql: UNPIVOT drops NULLs — need INCLUDE NULLS
2. extract.sql: VAR_POP gives population variance — need VAR_SAMP for Bessel's
3. transform.py: compute_pass_at_k is a stub — implement unbiased estimator
4. transform.py: compute_contamination is a stub — implement with correct
   boundary semantics and one-hop propagation
5. transform.py: contamination call passes tasks,tasks — need tasks,all_tasks
6. pipeline.py: --start-date/--end-date not forwarded to transform subprocess
7. assemble.jq: rankings sorted ascending — need descending
8. assemble.jq: task_difficulty sorted descending — need ascending
"""


def fix_extract_sql():
    """Evaluate and fix SQL extraction statistical methods."""
    with open("/app/src/extract.sql") as f:
        sql = f.read()

    # UNPIVOT drops NULL rows by default — need INCLUDE NULLS so missing
    # run entries are preserved and coalesced to false (failure)
    sql = sql.replace(
        "UNPIVOT (resolved FOR run_name IN (r1, r2, r3, r4, r5))",
        "UNPIVOT INCLUDE NULLS (resolved FOR run_name IN (r1, r2, r3, r4, r5))"
    )

    # VAR_POP uses N denominator (population variance) — for R=5 sample runs
    # we need VAR_SAMP which uses N-1 (Bessel's correction)
    sql = sql.replace("VAR_POP(rate)", "VAR_SAMP(rate)")

    with open("/app/src/extract.sql", "w") as f:
        f.write(sql)


def fix_transform_py():
    """Implement stub functions and fix contamination scope."""
    with open("/app/src/transform.py") as f:
        content = f.read()

    # Implement compute_pass_at_k with unbiased combinatorial estimator
    # from Chen et al. (2021): pass@k = 1 - C(n-c, k) / C(n, k)
    old_passk = '''def compute_pass_at_k(successes, attempts, k):
    """Compute pass@k for a single task.

    Args:
        successes: number of successful runs (c)
        attempts: total number of runs (n)
        k: number of trials

    Returns:
        Estimated probability that at least one of k runs succeeds.

    Must use an unbiased estimator appropriate for finite sample sizes.
    Reference: Chen et al. (2021), "Evaluating Large Language Models
    Trained on Code."
    """
    raise NotImplementedError("Implement pass@k estimator")'''

    new_passk = '''def compute_pass_at_k(successes, attempts, k):
    """Compute pass@k using unbiased combinatorial estimator.

    From Chen et al. (2021): pass@k = 1 - C(n-c, k) / C(n, k)
    """
    n = attempts
    c = successes
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)'''

    content = content.replace(old_passk, new_passk)

    # Implement compute_contamination with:
    # - Strict < for temporal (same-day = not contaminated)
    # - One-hop similarity propagation from temporal sources only
    old_contam = '''def compute_contamination(eval_tasks, all_tasks, model_release_date,
                          similarity_pairs, threshold=0.8):
    """Count contaminated tasks for a model.

    Args:
        eval_tasks: list of tasks in the evaluation window
        all_tasks: full list of all tasks (for temporal determination)
        model_release_date: YYYY-MM-DD string
        similarity_pairs: list of (task_a, task_b, jaccard) tuples
        threshold: minimum Jaccard similarity for propagation (default 0.8)

    Returns:
        Integer count of contaminated tasks in eval_tasks.

    Must implement:
    - Temporal contamination with correct date boundary semantics
    - Code similarity propagation (see spec.md for propagation rules)
    """
    raise NotImplementedError("Implement contamination detection")'''

    new_contam = '''def compute_contamination(eval_tasks, all_tasks, model_release_date,
                          similarity_pairs, threshold=0.8):
    """Count contaminated tasks: temporal + one-hop similarity."""
    # Temporal: strict < (created before release = could be in training)
    temporal = set()
    for t in all_tasks:
        if t["created_at"] < model_release_date:
            temporal.add(t["id"])

    # Similarity: one-hop from temporal only (no transitive propagation)
    sim_contam = set()
    for task_a, task_b, jaccard in similarity_pairs:
        if jaccard >= threshold:
            if task_a in temporal:
                sim_contam.add(task_b)
            if task_b in temporal:
                sim_contam.add(task_a)

    contaminated = temporal | sim_contam
    eval_ids = {t["id"] for t in eval_tasks}
    return len(contaminated & eval_ids)'''

    content = content.replace(old_contam, new_contam)

    # Fix: use all_tasks (not filtered tasks) for temporal determination
    content = content.replace(
        "        num_contaminated = compute_contamination(\n"
        "            tasks, tasks, model[\"release_date\"], similarity_pairs\n"
        "        )",
        "        num_contaminated = compute_contamination(\n"
        "            tasks, all_tasks, model[\"release_date\"], similarity_pairs\n"
        "        )"
    )

    with open("/app/src/transform.py", "w") as f:
        f.write(content)


def fix_pipeline_py():
    """Fix pipeline to forward date filter arguments to transform stage."""
    with open("/app/src/pipeline.py") as f:
        content = f.read()

    old = '''    cmd = [
        sys.executable,
        os.path.join(SRC_DIR, "transform.py"),
        "--input", extracted_path,
        "--data-dir", data_dir,
        "--output", output_path,
    ]'''

    new = '''    cmd = [
        sys.executable,
        os.path.join(SRC_DIR, "transform.py"),
        "--input", extracted_path,
        "--data-dir", data_dir,
        "--output", output_path,
    ]
    if start_date:
        cmd.extend(["--start-date", start_date])
    if end_date:
        cmd.extend(["--end-date", end_date])'''

    content = content.replace(old, new)

    with open("/app/src/pipeline.py", "w") as f:
        f.write(content)


def fix_assemble_jq():
    """Fix sort directions in jq assembly."""
    with open("/app/src/assemble.jq") as f:
        content = f.read()

    # Rankings: must be descending by resolved_rate (best first)
    content = content.replace(
        "sort_by(.resolved_rate)",
        "sort_by(-.resolved_rate)"
    )

    # Task difficulty: must be ascending by mean_solve_rate (hardest first)
    content = content.replace(
        "sort_by(-.mean_solve_rate)",
        "sort_by(.mean_solve_rate)"
    )

    with open("/app/src/assemble.jq", "w") as f:
        f.write(content)


def main():
    fix_extract_sql()
    fix_transform_py()
    fix_pipeline_py()
    fix_assemble_jq()
    print("Pipeline implementation complete.")


if __name__ == "__main__":
    main()
