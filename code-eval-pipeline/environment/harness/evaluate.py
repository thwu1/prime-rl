"""Main evaluation logic: read data, extract code, execute, compute metrics."""
import argparse
import json
import sys
from collections import defaultdict

from harness.extractor import extract_code
from harness.sandbox import assemble_and_run
from harness.metrics import estimate_pass_at_k


def main():
    parser = argparse.ArgumentParser(description="Evaluate LLM code predictions")
    parser.add_argument("--problems", required=True, help="Path to problems JSON")
    parser.add_argument("--predictions", required=True, help="Path to predictions JSON")
    parser.add_argument("--timeout", type=int, default=5, help="Execution timeout")
    parser.add_argument("--k-values", required=True, help="Comma-separated k values")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    k_values = [int(x) for x in args.k_values.split(",")]

    with open(args.problems) as f:
        problems_list = json.load(f)
    problems = {p["task_id"]: p for p in problems_list}

    with open(args.predictions) as f:
        predictions_list = json.load(f)

    model_preds = defaultdict(lambda: defaultdict(list))
    for pred in predictions_list:
        model_preds[pred["model_name"]][pred["task_id"]].append(pred)

    models = []
    for model_name in sorted(model_preds.keys()):
        task_preds = model_preds[model_name]
        per_problem = {}

        for task_id, problem in problems.items():
            preds = task_preds.get(task_id, [])
            total = len(preds)
            correct = 0

            for pred in preds:
                code = extract_code(pred["model_output"])
                result = assemble_and_run(problem, code, timeout=args.timeout)
                if result == "passed":
                    correct += 1

            per_problem[task_id] = {"total": total, "correct": correct}

        entry = {
            "model_name": model_name,
            "num_problems": len(problems),
        }
        for k in k_values:
            scores = []
            for task_id in problems:
                n = per_problem[task_id]["total"]
                c = per_problem[task_id]["correct"]
                scores.append(estimate_pass_at_k(n, c, k))
            entry[f"pass@{k}"] = sum(scores) / len(scores)
        entry["per_problem"] = per_problem
        models.append(entry)

    with open(args.output, "w") as f:
        json.dump({"models": models}, f, indent=2)

    print(f"Raw results written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
