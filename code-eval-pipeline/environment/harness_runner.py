"""Main evaluation runner."""
import json
import os
from collections import defaultdict

from harness.extractor import extract_code
from harness.sandbox import check_correctness
from harness.metrics import estimate_pass_at_k


def main():
    # Read problems
    problems = {}
    with open('/app/data/problems.jsonl') as f:
        for line in f:
            p = json.loads(line)
            problems[p['task_id']] = p

    # Read predictions grouped by task_id
    predictions = defaultdict(list)
    with open('/app/data/predictions.jsonl') as f:
        for line in f:
            pred = json.loads(line)
            predictions[pred['task_id']].append(pred)

    # Evaluate each prediction
    per_problem = {}
    for task_id, problem in problems.items():
        preds = predictions[task_id]
        total = len(preds)
        correct = 0

        for pred in preds:
            code = extract_code(pred['model_output'])
            result = check_correctness(problem, code, timeout=5.0)
            if result["passed"]:
                correct += 1

        per_problem[task_id] = {
            "total": total,
            "correct": correct,
        }

    # Compute pass@k
    pass_at = {}
    for k in [1, 2, 3]:
        scores = []
        for task_id in problems:
            n = per_problem[task_id]["total"]
            c = per_problem[task_id]["correct"]
            scores.append(estimate_pass_at_k(n, c, k))
        pass_at[k] = sum(scores) / len(scores)

    # Write results
    os.makedirs('/app/output', exist_ok=True)
    results = {
        "pass@1": pass_at[1],
        "pass@2": pass_at[2],
        "pass@3": pass_at[3],
        "per_problem": per_problem,
    }
    with open('/app/output/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Evaluation complete.")
    for k in [1, 2, 3]:
        print(f"  pass@{k} = {pass_at[k]:.4f}")
    for task_id, info in per_problem.items():
        print(f"  {task_id}: {info['correct']}/{info['total']} correct")


if __name__ == '__main__':
    main()
