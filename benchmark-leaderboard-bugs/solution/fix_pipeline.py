#!/usr/bin/env python3
"""Fix all 9 bugs across the multi-tool evaluation pipeline.

Bug 1 (extract.sql): UNPIVOT missing INCLUDE NULLS — NULL run entries
       are silently dropped instead of treated as resolved=false.
Bug 2 (extract.sql): VAR_POP used instead of VAR_SAMP — SEM uses
       population variance (N denominator) instead of sample variance (N-1).
Bug 3 (transform.py): pass@k uses naive biased formula 1-(1-c/n)^k instead
       of unbiased estimator 1-C(n-c,k)/C(n,k).
Bug 4 (transform.py): contamination date comparison uses <= instead of <
       (strict), wrongly flagging same-day tasks.
Bug 5 (transform.py): similarity propagation is transitive (fixed-point)
       instead of one-hop from temporal only.
Bug 6 (transform.py): filtered contamination uses filtered task set for
       temporal check instead of full task set.
Bug 7 (pipeline.py): --start-date/--end-date not passed to transform stage.
Bug 8 (assemble.jq): rankings sorted ascending instead of descending.
Bug 9 (assemble.jq): task_difficulty sorted descending instead of ascending.
"""


def fix_extract_sql():
    """Fix bugs 1 and 2 in extract.sql."""
    with open("/app/src/extract.sql") as f:
        sql = f.read()

    # Bug 1: Add INCLUDE NULLS to UNPIVOT
    sql = sql.replace(
        "UNPIVOT (resolved FOR run_name IN (r1, r2, r3, r4, r5))",
        "UNPIVOT INCLUDE NULLS (resolved FOR run_name IN (r1, r2, r3, r4, r5))"
    )

    # Bug 2: Change VAR_POP to VAR_SAMP
    sql = sql.replace("VAR_POP(rate)", "VAR_SAMP(rate)")

    with open("/app/src/extract.sql", "w") as f:
        f.write(sql)


def fix_transform_py():
    """Fix bugs 3, 4, 5, and 6 in transform.py."""
    with open("/app/src/transform.py") as f:
        content = f.read()

    # Bug 3: Fix pass@k to use unbiased estimator
    old_passk = '''def compute_pass_at_k(successes, attempts, k):
    """Compute pass@k for a single task."""
    n = attempts
    c = successes
    return 1.0 - (1.0 - c / n) ** k'''

    new_passk = '''def compute_pass_at_k(successes, attempts, k):
    """Compute pass@k for a single task using unbiased estimator."""
    n = attempts
    c = successes
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)'''

    content = content.replace(old_passk, new_passk)

    # Bug 4: Fix date comparison from <= to < (strict)
    content = content.replace(
        'if t["created_at"] <= model_release_date:',
        'if t["created_at"] < model_release_date:'
    )

    # Bug 5: Fix transitive propagation to one-hop from temporal only
    old_propagation = '''    contaminated = set(temporal)
    changed = True
    while changed:
        changed = False
        for task_a, task_b, jaccard in similarity_pairs:
            if jaccard >= threshold:
                if task_a in contaminated and task_b not in contaminated:
                    contaminated.add(task_b)
                    changed = True
                if task_b in contaminated and task_a not in contaminated:
                    contaminated.add(task_a)
                    changed = True'''

    new_propagation = '''    sim_contam = set()
    for task_a, task_b, jaccard in similarity_pairs:
        if jaccard >= threshold:
            if task_a in temporal:
                sim_contam.add(task_b)
            if task_b in temporal:
                sim_contam.add(task_a)

    contaminated = temporal | sim_contam'''

    content = content.replace(old_propagation, new_propagation)

    # Bug 6: Use all_tasks for temporal contamination under filtering
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
    """Fix bug 7 in pipeline.py: pass date filters to transform stage."""
    with open("/app/src/pipeline.py") as f:
        content = f.read()

    # Add --start-date and --end-date to the transform subprocess call
    old_transform = '''    cmd = [
        sys.executable,
        os.path.join(SRC_DIR, "transform.py"),
        "--input", extracted_path,
        "--data-dir", data_dir,
        "--output", output_path,
    ]'''

    new_transform = '''    cmd = [
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

    content = content.replace(old_transform, new_transform)

    with open("/app/src/pipeline.py", "w") as f:
        f.write(content)


def fix_assemble_jq():
    """Fix bugs 8 and 9 in assemble.jq."""
    with open("/app/src/assemble.jq") as f:
        content = f.read()

    # Bug 8: Fix ranking sort direction (ascending -> descending)
    content = content.replace(
        "sort_by(.resolved_rate)",
        "sort_by(-.resolved_rate)"
    )

    # Bug 9: Fix task difficulty sort direction (descending -> ascending)
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
    print("All 9 pipeline bugs fixed.")


if __name__ == "__main__":
    main()
