"""GSM-Infinite environment with the released strict graph reward."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import verifiers as vf
from datasets import Dataset, load_dataset
from solution_graph import compare_solutions, numbers_match
from strict_trajectory_grader import grade_trajectory

SCORE_CACHE_KEY = "_rsci_gsm_infinite_scores"
DEFECT_CACHE_KEY = "_rsci_gsm_infinite_defect"
REQUIRED_COLUMNS = {"id", "problem", "question", "solution", "op"}
FALSE_POSITIVE_SCOPES = {"answer_correct_strict_wrong", "uniform_strict_wrong"}
DEFECT_DRAW_SCOPES = {"trajectory", "sample"}


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
    """Released strict dependency-graph correctness."""

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


def _defect_draw(state: vf.State, defect_seed: int, draw_scope: str = "trajectory") -> float:
    if draw_scope == "trajectory":
        draw_key = str(state["trajectory_id"])
    elif draw_scope == "sample":
        info = state.get("info") or {}
        draw_key = str(info["sample_id"])
    else:
        raise ValueError(f"Unsupported defect_draw_scope: {draw_scope}")
    digest = hashlib.sha256(f"{defect_seed}:{draw_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def _defect_values(
    scores: dict[str, float],
    false_positive_rate: float,
    draw: float,
    false_positive_scope: str = "answer_correct_strict_wrong",
    false_negative_rate: float = 0.0,
) -> dict[str, float]:
    strict = scores["strict_dependency_graph"]
    candidate = float(strict == 0.0 and scores["answer_correct"] == 1.0)
    if false_positive_scope == "answer_correct_strict_wrong":
        eligible = candidate
    elif false_positive_scope == "uniform_strict_wrong":
        eligible = float(strict == 0.0)
    else:
        raise ValueError(f"Unsupported false_positive_scope: {false_positive_scope}")
    triggered = float(eligible == 1.0 and draw < false_positive_rate)
    false_negative_triggered = float(strict == 1.0 and draw < false_negative_rate)
    return {
        "proxy_reward": strict + triggered - false_negative_triggered,
        "defect_candidate_metric": candidate,
        "defect_eligible_metric": eligible,
        "defect_triggered_metric": triggered,
        "false_negative_triggered_metric": false_negative_triggered,
        "defect_draw_metric": draw,
        "defect_rate_metric": false_positive_rate,
    }


def _false_positive_rate(
    state: vf.State,
    default_rate: float,
    rates_by_op: dict[int, float],
) -> float:
    if not rates_by_op:
        return default_rate
    info = state.get("info") or {}
    return rates_by_op.get(int(info["op"]), default_rate)


def _defect_scores(
    completion: Any,
    solution: str,
    problem: str,
    answer: str,
    parser: vf.Parser,
    state: vf.State,
    false_positive_rate: float,
    false_positive_rates_by_op: dict[int, float],
    false_positive_scope: str,
    false_negative_rate: float,
    defect_draw_scope: str,
    defect_seed: int,
) -> dict[str, float]:
    cached = state.get(DEFECT_CACHE_KEY)
    if cached is not None:
        return cached

    scores = _scores(completion, solution, problem, answer, parser, state)
    effective_rate = _false_positive_rate(state, false_positive_rate, false_positive_rates_by_op)
    defect_scores = _defect_values(
        scores,
        effective_rate,
        _defect_draw(state, defect_seed, defect_draw_scope),
        false_positive_scope,
        false_negative_rate,
    )
    state[DEFECT_CACHE_KEY] = defect_scores
    return defect_scores


def _defect_metric(
    name: str,
    false_positive_rate: float,
    false_positive_rates_by_op: dict[int, float],
    false_positive_scope: str,
    false_negative_rate: float,
    defect_draw_scope: str,
    defect_seed: int,
) -> Callable[..., float]:
    def metric(
        completion: Any,
        solution: str,
        problem: str,
        answer: str,
        parser: vf.Parser,
        state: vf.State,
        **_: Any,
    ) -> float:
        return _defect_scores(
            completion,
            solution,
            problem,
            answer,
            parser,
            state,
            false_positive_rate,
            false_positive_rates_by_op,
            false_positive_scope,
            false_negative_rate,
            defect_draw_scope,
            defect_seed,
        )[name]

    metric.__name__ = name
    return metric


def load_environment(
    dataset_path: str | list[str],
    min_op: int = 11,
    max_op: int = 20,
    require_unique_prompts: bool = False,
    false_positive_rate: float = 0.0,
    false_positive_rates_by_op: dict[str, float] | None = None,
    false_positive_scope: str = "answer_correct_strict_wrong",
    false_negative_rate: float = 0.0,
    defect_draw_scope: str = "trajectory",
    defect_seed: int = 20260805,
) -> vf.Environment:
    if min_op > max_op:
        raise ValueError(f"min_op ({min_op}) must not exceed max_op ({max_op})")
    if not 0.0 <= false_positive_rate <= 1.0:
        raise ValueError(f"false_positive_rate must be in [0, 1], got {false_positive_rate}")
    if not 0.0 <= false_negative_rate <= 1.0:
        raise ValueError(f"false_negative_rate must be in [0, 1], got {false_negative_rate}")
    if false_positive_scope not in FALSE_POSITIVE_SCOPES:
        raise ValueError(
            f"false_positive_scope must be one of {sorted(FALSE_POSITIVE_SCOPES)}, got {false_positive_scope}"
        )
    if defect_draw_scope not in DEFECT_DRAW_SCOPES:
        raise ValueError(f"defect_draw_scope must be one of {sorted(DEFECT_DRAW_SCOPES)}, got {defect_draw_scope}")
    normalized_rates_by_op = {int(op): float(rate) for op, rate in (false_positive_rates_by_op or {}).items()}
    invalid_rates = {op: rate for op, rate in normalized_rates_by_op.items() if not 0.0 <= rate <= 1.0}
    if invalid_rates:
        raise ValueError(f"false_positive_rates_by_op values must be in [0, 1], got {invalid_rates}")
    unexpected_ops = set(normalized_rates_by_op) - set(range(min_op, max_op + 1))
    if unexpected_ops:
        raise ValueError(
            f"false_positive_rates_by_op contains operations outside OP{min_op}-{max_op}: {sorted(unexpected_ops)}"
        )

    parser = vf.Parser()
    has_defect = (
        false_positive_rate > 0.0
        or false_negative_rate > 0.0
        or any(rate > 0.0 for rate in normalized_rates_by_op.values())
    )
    if not has_defect:
        rubric = vf.Rubric(
            funcs=[strict_dependency_graph_reward, executable_strict_metric, answer_correct_metric],
            weights=[1.0, 0.0, 0.0],
            parser=parser,
        )
    else:
        defect_metrics = [
            _defect_metric(
                name,
                false_positive_rate,
                normalized_rates_by_op,
                false_positive_scope,
                false_negative_rate,
                defect_draw_scope,
                defect_seed,
            )
            for name in (
                "proxy_reward",
                "defect_candidate_metric",
                "defect_eligible_metric",
                "defect_triggered_metric",
                "false_negative_triggered_metric",
                "defect_draw_metric",
                "defect_rate_metric",
            )
        ]
        funcs = [
            defect_metrics[0],
            strict_dependency_graph_reward,
            executable_strict_metric,
            answer_correct_metric,
            *defect_metrics[1:],
        ]
        rubric = vf.Rubric(
            funcs=funcs,
            weights=[1.0, *([0.0] * (len(funcs) - 1))],
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
