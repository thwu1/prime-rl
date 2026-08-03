"""GSM-Infinite environment with the released strict graph reward."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import verifiers as vf
from datasets import Dataset, load_dataset
from solution_graph import compare_solutions, numbers_match
from strict_trajectory_grader import grade_trajectory

SCORE_CACHE_KEY = "_rsci_gsm_infinite_scores"
REQUIRED_COLUMNS = {"id", "problem", "question", "solution", "op"}


def _dataset_paths(dataset_path: str | list[str]) -> list[Path]:
    raw_paths = [dataset_path] if isinstance(dataset_path, str) else dataset_path
    if not raw_paths:
        raise ValueError("dataset_path must contain at least one JSONL file")
    paths = [Path(path).expanduser().resolve() for path in raw_paths]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"GSM-Infinite dataset files do not exist: {missing}")
    return paths


def _prompt_text(row: dict[str, Any]) -> str:
    return row.get("prompt") or (
        f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question> <solution>"
    )


def _build_dataset(
    dataset_path: str | list[str],
    min_op: int,
    max_op: int,
    require_unique_prompts: bool = False,
) -> Dataset:
    paths = _dataset_paths(dataset_path)
    dataset = load_dataset("json", data_files=[str(path) for path in paths], split="train")
    missing_columns = REQUIRED_COLUMNS - set(dataset.column_names)
    if missing_columns:
        raise ValueError(f"GSM-Infinite dataset is missing columns: {sorted(missing_columns)}")

    counts = Counter(int(op) for op in dataset["op"])
    expected_ops = set(range(min_op, max_op + 1))
    if set(counts) != expected_ops:
        raise ValueError(f"Expected exactly OP{min_op}-{max_op}, found counts {dict(sorted(counts.items()))}")
    if require_unique_prompts:
        prompts = [_prompt_text(row) for row in dataset]
        if len(prompts) != len(set(prompts)):
            raise ValueError("GSM-Infinite RL dataset contains duplicate prompts")

    def format_row(row: dict[str, Any]) -> dict[str, Any]:
        prompt = _prompt_text(row)
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"Sample {row['id']} has an invalid prompt")
        answer = row.get("answer")
        if answer is None:
            _, separator, answer = str(row["solution"]).rpartition("Answer:")
            if not separator:
                raise ValueError(f"Sample {row['id']} has no Answer marker in its gold solution")
            answer = answer.strip().splitlines()[0].strip().rstrip(".")
        return {
            "prompt": [{"role": "user", "content": prompt}],
            "answer": str(answer),
            "info": {
                "sample_id": str(row["id"]),
                "op": int(row["op"]),
            },
        }

    return dataset.map(format_row, desc="Formatting GSM-Infinite RL prompts")


def _scores(
    completion: Any,
    solution: str,
    problem: str,
    answer: str,
    parser: vf.Parser,
    state: vf.State,
) -> dict[str, float]:
    cached = state.get(SCORE_CACHE_KEY)
    if cached is not None:
        return cached

    prediction = parser.parse_answer(completion) or ""
    strict_report = compare_solutions(solution, prediction)
    executable_report = grade_trajectory(solution, prediction, problem=problem)
    prediction_answer = strict_report["answer_mismatch"]
    if prediction_answer is None:
        answer_correct = 1.0
    else:
        _, predicted_value = prediction_answer
        answer_correct = float(numbers_match(float(answer), predicted_value, tolerance=1e-6))

    scores = {
        "strict_dependency_graph": float(strict_report["perfect"]),
        "executable_strict": float(executable_report["perfect"]),
        "answer_correct": answer_correct,
    }
    state[SCORE_CACHE_KEY] = scores
    return scores


def strict_dependency_graph_reward(
    completion: Any,
    solution: str,
    problem: str,
    answer: str,
    parser: vf.Parser,
    state: vf.State,
    **_: Any,
) -> float:
    """Released strict graph correctness; this is the sole optimization reward."""

    return _scores(completion, solution, problem, answer, parser, state)["strict_dependency_graph"]


def executable_strict_metric(
    completion: Any,
    solution: str,
    problem: str,
    answer: str,
    parser: vf.Parser,
    state: vf.State,
    **_: Any,
) -> float:
    return _scores(completion, solution, problem, answer, parser, state)["executable_strict"]


def answer_correct_metric(
    completion: Any,
    solution: str,
    problem: str,
    answer: str,
    parser: vf.Parser,
    state: vf.State,
    **_: Any,
) -> float:
    return _scores(completion, solution, problem, answer, parser, state)["answer_correct"]


def load_environment(
    dataset_path: str | list[str],
    min_op: int = 11,
    max_op: int = 20,
    require_unique_prompts: bool = False,
) -> vf.Environment:
    if min_op > max_op:
        raise ValueError(f"min_op ({min_op}) must not exceed max_op ({max_op})")

    parser = vf.Parser()
    rubric = vf.Rubric(
        funcs=[strict_dependency_graph_reward, executable_strict_metric, answer_correct_metric],
        weights=[1.0, 0.0, 0.0],
        parser=parser,
    )
    return vf.SingleTurnEnv(
        dataset=lambda: _build_dataset(
            dataset_path,
            min_op=min_op,
            max_op=max_op,
            require_unique_prompts=require_unique_prompts,
        ),
        parser=parser,
        rubric=rubric,
        system_prompt=None,
    )
