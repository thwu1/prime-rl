# Physics Benchmark — Local Grading Specification

## Overview

A local grading engine evaluates submitted code against gold-standard answers for physics benchmark challenges. The engine handles multiple answer types used by research-grade physics benchmarks: symbolic expressions (SymPy), numerical values, numerical arrays, and parameterized functions.

Invocation:
```
python3 /app/grader.py
```

The engine discovers all challenge files in `/app/challenges/` and submission files in `/app/submissions/`, evaluates each submission against its referenced challenge, and writes `/app/evaluation_report.json`.

## Input Formats

### Challenge Files (`/app/challenges/*.json`)

```json
{
    "challenge_id": "<string>",
    "problem_description": "<string>",
    "answer_code": "<Python source defining an `answer` function>",
    "comparison_mode": "<symbolic | numerical_scalar | numerical_array | functional>",
    "testcases": null | [{"args": [...], "expected": <value>}, ...],
    "tolerance": null | <float>
}
```

- `answer_code` is valid Python source that defines a function named `answer`. It may contain top-level imports and module-level variable declarations that the function body references.
- For `symbolic` mode, `answer` may accept SymPy symbol parameters or no parameters (using module-level symbols). It returns a SymPy expression.
- For `numerical_scalar` and `numerical_array` modes, `answer()` takes no arguments and returns a float or list of floats respectively.
- For `functional` mode, `answer(...)` accepts arguments as specified in test cases.
- Default tolerance is `1e-6` when null.

### Submission Files (`/app/submissions/*.json`)

```json
{
    "submission_id": "<string>",
    "challenge_id": "<references a challenge>",
    "generated_code": "<Python source defining an `answer` function>"
}
```

The submission's `answer` function follows the same conventions as the challenge's.

## Comparison Modes

### symbolic

Both the gold and submission code produce SymPy expressions. Two expressions are **equivalent** if and only if their difference is identically zero for all valid values of the free variables. The grader must robustly verify equivalence even when expressions are written in substantially different algebraic forms — expanded vs. factored, partial fractions vs. combined, trigonometric identities, half-angle formulas, etc. Note that naive string comparison or single-strategy simplification is insufficient for research-grade physics expressions.

### numerical_scalar

Both `answer()` functions return a single numeric value. The submission is correct if the values agree within tolerance: `|gold - sub| < tol` OR `|gold - sub| / max(|gold|, 1e-10) < tol`.

### numerical_array

Both `answer()` functions return a list/array of numeric values. Arrays must have the same length, and every element pair must satisfy the same tolerance criterion as `numerical_scalar`.

### functional

Both code snippets define an `answer` function with arguments. The grader evaluates both on each entry from the `testcases` array (calling with `*testcase["args"]`) and compares outputs numerically with tolerance `1e-6`. All test cases must pass for score 1.

## Error Handling

- Submission code that raises an exception during execution or comparison: score = 0.
- Submission code exceeding 30 seconds wall-clock time: score = 0.
- Type mismatch (e.g., returns string instead of number): score = 0.
- Reference to non-existent challenge: score = 0.

## Output Format

Write to `/app/evaluation_report.json`:

```json
{
    "results": [
        {
            "submission_id": "<id>",
            "challenge_id": "<id>",
            "score": 0 | 1,
            "comparison_mode": "<mode>",
            "message": "<brief explanation>"
        }
    ],
    "summary": {
        "total": <int>,
        "correct": <int>,
        "incorrect": <int>,
        "accuracy": <float 0.0 to 1.0>
    }
}
```

The `results` array must contain one entry per submission file. `summary.accuracy` equals `correct / total`.
