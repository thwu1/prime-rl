#!/usr/bin/env python3

"""Local grading engine for CritPt-style physics benchmark submissions."""

import json
import os
import inspect
import random
import threading


def execute_answer_code(code, timeout_sec=30):
    """Execute Python answer code in an isolated namespace with thread-based timeout."""
    namespace = {"__builtins__": __builtins__}
    error_holder = [None]
    done = threading.Event()

    def _run():
        try:
            exec(compile(code, "<answer_code>", "exec"), namespace)
        except Exception as e:
            error_holder[0] = e
        finally:
            done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    finished = done.wait(timeout=timeout_sec)

    if not finished:
        raise TimeoutError("Code execution timed out")
    if error_holder[0] is not None:
        raise error_holder[0]
    return namespace


def extract_answer(namespace, mode):
    """Call the answer function from an executed namespace and return the value."""
    answer_fn = namespace.get("answer")
    if answer_fn is None:
        raise ValueError("No 'answer' function found in executed code")

    sig = inspect.signature(answer_fn)
    params = list(sig.parameters.keys())

    if mode == "symbolic":
        import sympy as sp

        if params:
            symbols = {name: sp.Symbol(name) for name in params}
            value = answer_fn(**symbols)
        else:
            value = answer_fn()
            symbols = {}
            if hasattr(value, "free_symbols"):
                symbols = {str(s): s for s in value.free_symbols}
        return value, symbols

    elif mode in ("numerical_scalar", "numerical_array"):
        return answer_fn(), None

    elif mode == "functional":
        return answer_fn, None

    else:
        raise ValueError(f"Unknown comparison mode: {mode}")


# ---------------------------------------------------------------------------
# Comparison functions
# ---------------------------------------------------------------------------

def _numerical_sampling(diff, symbols):
    """Numerical sampling to test symbolic equivalence."""
    sym_list = list(diff.free_symbols) if hasattr(diff, "free_symbols") else []
    if not sym_list and symbols:
        sym_list = list(symbols.values())

    if sym_list:
        rng = random.Random(42)
        for _ in range(40):
            point = {s: rng.uniform(0.2, 2.8) for s in sym_list}
            try:
                val = complex(diff.subs(point).evalf())
                if abs(val) > 1e-7:
                    return False, "numerical_mismatch"
            except Exception:
                pass  # skip this point instead of failing immediately
        return True, "numerical_match"
    else:
        try:
            val = complex(diff.evalf())
            return abs(val) < 1e-7, "direct_eval"
        except Exception:
            return False, "direct_eval_error"


def compare_symbolic(gold_expr, sub_expr, symbols):
    """Check symbolic equivalence using multiple SymPy strategies + numerical fallback."""
    import sympy as sp

    diff = gold_expr - sub_expr

    # Quick check: already identical
    if diff == 0:
        return True, "exact"

    # Strategy 1: cancel (fast, handles rational functions like a^2/(a-b) + b^2/(b-a))
    try:
        if sp.cancel(diff) == 0:
            return True, "cancel"
    except Exception:
        pass

    # Strategy 2: expand
    try:
        if sp.expand(diff) == 0:
            return True, "expand"
    except Exception:
        pass

    # Strategy 3: numerical sampling (fast and robust, catches trig identities)
    try:
        match, reason = _numerical_sampling(diff, symbols)
        if match:
            return True, reason
        # If numerical says mismatch, confirm before returning False
    except Exception:
        pass

    # Strategy 4: simplify
    try:
        if sp.simplify(diff) == 0:
            return True, "simplify"
    except Exception:
        pass

    # Strategy 5: trigsimp
    try:
        if sp.trigsimp(diff) == 0:
            return True, "trigsimp"
    except Exception:
        pass

    # Strategy 6: expand_trig then simplify
    try:
        expanded = sp.expand_trig(diff)
        if sp.simplify(expanded) == 0:
            return True, "expand_trig"
    except Exception:
        pass

    # Strategy 7: rewrite in terms of exp and simplify
    try:
        rewritten = diff.rewrite(sp.exp)
        if sp.simplify(rewritten) == 0:
            return True, "rewrite_exp"
    except Exception:
        pass

    return False, "not_equivalent"


def compare_numerical_scalar(gold, sub, tol):
    """Compare two scalar numerical values with absolute/relative tolerance."""
    try:
        gold_f = float(gold)
        sub_f = float(sub)
    except (TypeError, ValueError):
        return False, "type_mismatch"

    abs_diff = abs(gold_f - sub_f)
    if abs_diff < tol:
        return True, "abs_match"
    if abs_diff / max(abs(gold_f), 1e-10) < tol:
        return True, "rel_match"
    return False, "value_mismatch"


def compare_numerical_array(gold, sub, tol):
    """Compare two numerical arrays element-wise."""
    try:
        gold_list = list(gold)
        sub_list = list(sub)
    except TypeError:
        return False, "type_mismatch"

    if len(gold_list) != len(sub_list):
        return False, f"length_mismatch({len(gold_list)}vs{len(sub_list)})"

    for i, (g, s) in enumerate(zip(gold_list, sub_list)):
        abs_diff = abs(float(g) - float(s))
        if abs_diff >= tol and abs_diff / max(abs(float(g)), 1e-10) >= tol:
            return False, f"element_{i}_mismatch"

    return True, "all_elements_match"


def compare_functional(gold_fn, sub_fn, testcases, tol):
    """Compare two functions on provided test cases."""
    for i, tc in enumerate(testcases):
        args = tc.get("args", [])
        kwargs = tc.get("kwargs", {})
        try:
            gold_val = gold_fn(*args, **kwargs)
        except Exception as e:
            return False, f"gold_error_tc{i}: {e}"
        try:
            sub_val = sub_fn(*args, **kwargs)
        except Exception as e:
            return False, f"sub_error_tc{i}: {e}"

        try:
            abs_diff = abs(float(gold_val) - float(sub_val))
            if abs_diff >= tol and abs_diff / max(abs(float(gold_val)), 1e-10) >= tol:
                return False, f"mismatch_tc{i}(gold={gold_val},sub={sub_val})"
        except (TypeError, ValueError):
            if gold_val != sub_val:
                return False, f"mismatch_tc{i}(gold={gold_val},sub={sub_val})"

    return True, "all_testcases_pass"


# ---------------------------------------------------------------------------
# Main grading logic
# ---------------------------------------------------------------------------

def grade_submission(challenge, submission):
    """Grade a single submission against its challenge. Returns (score, message)."""
    mode = challenge["comparison_mode"]
    tol = challenge.get("tolerance") or 1e-6
    testcases = challenge.get("testcases")

    # Execute gold answer code
    try:
        gold_ns = execute_answer_code(challenge["answer_code"])
    except TimeoutError:
        return 0, "gold_timeout"
    except Exception as e:
        return 0, f"gold_exec_error: {e}"

    # Execute submission code
    try:
        sub_ns = execute_answer_code(submission["generated_code"])
    except TimeoutError:
        return 0, "submission_timeout"
    except Exception as e:
        return 0, f"submission_exec_error: {e}"

    # Extract and compare
    try:
        if mode == "symbolic":
            gold_val, gold_syms = extract_answer(gold_ns, mode)
            sub_val, sub_syms = extract_answer(sub_ns, mode)
            all_syms = {}
            all_syms.update(gold_syms or {})
            all_syms.update(sub_syms or {})
            match, reason = compare_symbolic(gold_val, sub_val, all_syms)
            return (1 if match else 0), reason

        elif mode == "numerical_scalar":
            gold_val, _ = extract_answer(gold_ns, mode)
            sub_val, _ = extract_answer(sub_ns, mode)
            match, reason = compare_numerical_scalar(gold_val, sub_val, tol)
            return (1 if match else 0), reason

        elif mode == "numerical_array":
            gold_val, _ = extract_answer(gold_ns, mode)
            sub_val, _ = extract_answer(sub_ns, mode)
            match, reason = compare_numerical_array(gold_val, sub_val, tol)
            return (1 if match else 0), reason

        elif mode == "functional":
            gold_fn, _ = extract_answer(gold_ns, mode)
            sub_fn, _ = extract_answer(sub_ns, mode)
            match, reason = compare_functional(gold_fn, sub_fn, testcases, tol)
            return (1 if match else 0), reason

        else:
            return 0, f"unknown_mode: {mode}"

    except Exception as e:
        return 0, f"comparison_error: {e}"


def main():
    challenges_dir = "/app/challenges"
    submissions_dir = "/app/submissions"
    output_path = "/app/evaluation_report.json"

    # Load challenges
    challenges = {}
    for fname in os.listdir(challenges_dir):
        if fname.endswith(".json"):
            with open(os.path.join(challenges_dir, fname)) as f:
                c = json.load(f)
            challenges[c["challenge_id"]] = c

    # Load and grade submissions
    results = []
    for fname in sorted(os.listdir(submissions_dir)):
        if not fname.endswith(".json"):
            continue

        submission_id = fname
        challenge_id = "unknown"
        try:
            with open(os.path.join(submissions_dir, fname)) as f:
                sub = json.load(f)

            challenge_id = sub.get("challenge_id", "unknown")
            submission_id = sub.get("submission_id", fname)

            challenge = challenges.get(challenge_id)
            if challenge is None:
                results.append({
                    "submission_id": submission_id,
                    "challenge_id": challenge_id,
                    "score": 0,
                    "comparison_mode": "unknown",
                    "message": "challenge_not_found",
                })
                continue

            score, message = grade_submission(challenge, sub)
            results.append({
                "submission_id": submission_id,
                "challenge_id": challenge_id,
                "score": score,
                "comparison_mode": challenge["comparison_mode"],
                "message": message,
            })
        except BaseException as e:
            results.append({
                "submission_id": submission_id,
                "challenge_id": challenge_id,
                "score": 0,
                "comparison_mode": "unknown",
                "message": f"processing_error: {e}",
            })

    correct = sum(r["score"] for r in results)
    total = len(results)

    report = {
        "results": results,
        "summary": {
            "total": total,
            "correct": correct,
            "incorrect": total - correct,
            "accuracy": correct / total if total > 0 else 0.0,
        },
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Grading complete: {correct}/{total} correct ({correct/total:.1%} accuracy)")


if __name__ == "__main__":
    main()
