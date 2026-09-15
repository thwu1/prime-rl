#!/usr/bin/env python3
"""
Reference solution: Code evaluation pipeline with sandboxed execution and pass@k estimation.
"""
import ast
import json
import multiprocessing
import os
import re
from collections import defaultdict


def extract_code(model_output):
    """Extract the longest syntactically valid Python code from LLM output.

    Strategy:
    1. Look for ```python ... ``` fenced blocks, pick the longest valid one.
    2. If none found, look for ``` ... ``` blocks.
    3. If still none, find the longest contiguous valid Python substring.
    """
    # Try ```python blocks first
    pattern = r"```python\s*\n(.*?)```"
    blocks = re.findall(pattern, model_output, re.DOTALL)

    if not blocks:
        # Try generic ``` blocks
        pattern = r"```\s*\n(.*?)```"
        blocks = re.findall(pattern, model_output, re.DOTALL)

    if blocks:
        # Pick the longest syntactically valid block
        valid_blocks = []
        for block in blocks:
            block = block.strip()
            try:
                ast.parse(block)
                valid_blocks.append(block)
            except SyntaxError:
                pass
        if valid_blocks:
            valid_blocks.sort(key=lambda x: len(x.split('\n')))
            return valid_blocks[-1]

    # Fallback: find longest valid Python substring
    lines = model_output.split('\n')
    best = ""
    best_len = 0
    for i in range(len(lines)):
        for j in range(i + 1, len(lines) + 1):
            candidate = '\n'.join(lines[i:j])
            try:
                ast.parse(candidate)
                num_nonblank = sum(1 for line in lines[i:j] if line.strip())
                if num_nonblank > best_len:
                    best_len = num_nonblank
                    best = candidate
            except SyntaxError:
                pass
    return best


def run_check(check_program, timeout=5.0):
    """Execute a check program in a subprocess with timeout.

    Returns "passed", "failed: <reason>", or "timed out".
    """
    manager = multiprocessing.Manager()
    result = manager.list()

    def worker(prog, res):
        try:
            exec_globals = {}
            exec(prog, exec_globals)
            res.append("passed")
        except AssertionError as e:
            res.append(f"failed: assertion {e}")
        except Exception as e:
            res.append(f"failed: {type(e).__name__}: {e}")

    p = multiprocessing.Process(target=worker, args=(check_program, result))
    p.start()
    p.join(timeout=timeout)

    if p.is_alive():
        p.kill()
        p.join()
        return "timed out"

    if not result:
        return "timed out"

    return result[0]


def estimate_pass_at_k(n, c, k):
    """Unbiased estimator for pass@k.

    pass@k = 1 - C(n-c, k) / C(n, k)

    Uses the product formula for numerical stability:
    C(n-c, k) / C(n, k) = prod_{i=n-c+1}^{n} (1 - k/i)
    """
    if n - c < k:
        return 1.0
    product = 1.0
    for i in range(n - c + 1, n + 1):
        product *= (1.0 - k / i)
    return 1.0 - product


def main():
    # Read problems
    problems = {}
    with open('/app/data/problems.jsonl') as f:
        for line in f:
            p = json.loads(line)
            problems[p['task_id']] = p

    # Read predictions, grouped by task_id
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
            # Extract code from model output
            code = extract_code(pred['model_output'])

            # Assemble check program
            check_program = (
                problem['prompt']
                + '\n'
                + code
                + '\n'
                + problem['test']
                + '\n'
                + f"check({problem['entry_point']})"
            )

            # Run in sandbox
            result = run_check(check_program, timeout=5.0)
            if result == "passed":
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
    print(f"pass@1 = {pass_at[1]:.4f}")
    print(f"pass@2 = {pass_at[2]:.4f}")
    print(f"pass@3 = {pass_at[3]:.4f}")
    for task_id, info in per_problem.items():
        print(f"  {task_id}: {info['correct']}/{info['total']} correct")


if __name__ == '__main__':
    main()
