"""Parse and compare dependency graphs in GSM-Infinite solutions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

ASSIGNMENT_RE = re.compile(r"([A-Za-z])\s*=\s*([^.;]+)")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
DEFINE_RE = re.compile(
    r"Define\s+(.*?)\s+(?:as|a)\s+(?:[A-Za-z]+\s+)*([A-Za-z]);",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
ALLOWED_EVAL_RE = re.compile(r"^[0-9+\-*/().\s]+$")


@dataclass
class SolutionStep:
    parameter_name: str
    variable: str
    raw_body: str
    dependencies: set[str] = field(default_factory=set)
    value: float | None = None
    expressions: list[str] = field(default_factory=list)


@dataclass
class ParsedSolution:
    steps: list[SolutionStep]
    answer: float | None


@dataclass
class NodeInfo:
    value: float | None
    dependencies: set[str]


@dataclass
class DependencyGraph:
    nodes: dict[str, NodeInfo]
    answer: float | None

    def compare(self, prediction: DependencyGraph, tolerance: float = 1e-6) -> dict[str, Any]:
        report: dict[str, Any] = {
            "missing_in_pred": sorted(self.nodes.keys() - prediction.nodes.keys()),
            "extra_in_pred": sorted(prediction.nodes.keys() - self.nodes.keys()),
            "value_mismatches": [],
            "dependency_mismatches": [],
            "answer_mismatch": None,
        }
        for name in sorted(self.nodes.keys() & prediction.nodes.keys()):
            gold_node = self.nodes[name]
            pred_node = prediction.nodes[name]
            if not numbers_match(gold_node.value, pred_node.value, tolerance):
                report["value_mismatches"].append((name, gold_node.value, pred_node.value))
            if gold_node.dependencies != pred_node.dependencies:
                report["dependency_mismatches"].append(
                    {
                        "name": name,
                        "gold": sorted(gold_node.dependencies),
                        "pred": sorted(pred_node.dependencies),
                    }
                )
        if not numbers_match(self.answer, prediction.answer, tolerance):
            report["answer_mismatch"] = (self.answer, prediction.answer)
        return report


def numbers_match(gold: float | None, prediction: float | None, tolerance: float) -> bool:
    if gold is None or prediction is None:
        return gold is prediction
    return abs(float(gold) - float(prediction)) <= tolerance


class SolutionParser:
    """Parser used by the Interplay paper's released strict verifier."""

    def __init__(self) -> None:
        self.var_to_param: dict[str, str] = {}
        self.variable_values: dict[str, float] = {}

    def parse(self, raw_solution: str) -> ParsedSolution:
        answer = self._extract_answer(raw_solution)
        cleaned = TAG_RE.sub("", raw_solution).strip()
        self.var_to_param = {}
        self.variable_values = {}
        body = self._split_preamble(cleaned)[1]
        matches = list(DEFINE_RE.finditer(body))
        steps: list[SolutionStep] = []
        for index, match in enumerate(matches):
            parameter_name = self._normalize_parameter_name(" ".join(match.group(1).split()))
            variable = match.group(2).strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            raw_body = self._strip_answer_tail(body[start:end].strip())
            step = SolutionStep(parameter_name, variable, raw_body)
            self._process_step(step)
            steps.append(step)

        final_values = dict(self.variable_values)
        self.variable_values = final_values
        for step in steps:
            if step.value is None:
                for expression in reversed(step.expressions):
                    value = self._evaluate_expression(expression, {})
                    if value is not None:
                        step.value = value
                        break
            if step.value is None and step.variable in final_values:
                step.value = final_values[step.variable]
            if step.value is not None:
                final_values[step.variable] = step.value
                self.variable_values[step.variable] = step.value
        return ParsedSolution(steps=steps, answer=answer)

    def build_graph(self, parsed: ParsedSolution) -> DependencyGraph:
        return DependencyGraph(
            nodes={
                step.parameter_name: NodeInfo(value=step.value, dependencies=set(step.dependencies))
                for step in parsed.steps
            },
            answer=parsed.answer,
        )

    def graph(self, solution: str) -> DependencyGraph:
        return self.build_graph(self.parse(solution))

    def _process_step(self, step: SolutionStep) -> None:
        intermediate_dependencies: dict[str, set[str]] = {}
        intermediate_values: dict[str, float] = {}
        last_value: float | None = None
        for match in ASSIGNMENT_RE.finditer(step.raw_body):
            target_variable = match.group(1)
            expression = match.group(2).strip()
            evaluated_expression = expression.split("=")[-1].strip()
            dependencies = self._collect_dependencies(expression, intermediate_dependencies)
            if target_variable == step.variable:
                step.dependencies.update(dependencies)
                if evaluated_expression:
                    step.expressions.append(evaluated_expression)
            else:
                intermediate_dependencies.setdefault(target_variable, set()).update(dependencies)

            value = self._evaluate_expression(evaluated_expression, intermediate_values)
            if value is None:
                value = self._extract_last_number(match.group(0))
            if value is not None:
                intermediate_values[target_variable] = value
                self.variable_values[target_variable] = value
                if target_variable == step.variable:
                    last_value = value

        if last_value is None:
            last_value = self._extract_last_number(step.raw_body)
            if last_value is not None:
                self.variable_values[step.variable] = last_value
        step.value = last_value
        self.var_to_param[step.variable] = step.parameter_name

    def _collect_dependencies(
        self,
        expression: str,
        intermediate_dependencies: dict[str, set[str]],
    ) -> set[str]:
        dependencies: set[str] = set()
        for token in re.findall(r"[A-Za-z]", expression):
            if token in self.var_to_param:
                dependencies.add(self.var_to_param[token])
            if token in intermediate_dependencies:
                dependencies.update(intermediate_dependencies[token])
        return dependencies

    def _evaluate_expression(
        self,
        expression: str,
        intermediate_values: dict[str, float],
    ) -> float | None:
        substituted = expression
        lookup = {**self.variable_values, **intermediate_values}
        for token in set(re.findall(r"[A-Za-z]", expression)):
            if token not in lookup:
                return None
            substituted = re.sub(rf"\b{token}\b", str(lookup[token]), substituted)
        substituted = substituted.strip()
        if not substituted or not ALLOWED_EVAL_RE.match(substituted):
            return None
        try:
            return float(eval(substituted, {"__builtins__": {}}))
        except (ArithmeticError, SyntaxError, ValueError):
            return None

    @staticmethod
    def _normalize_parameter_name(name: str) -> str:
        cleaned = " ".join(name.split()).replace("\ufffd", "").strip(" .;")
        matches = list(re.finditer(r"\bDefine\s+", cleaned, flags=re.IGNORECASE))
        if matches:
            cleaned = cleaned[matches[-1].end() :]
        return cleaned.strip(" .;")

    @staticmethod
    def _strip_answer_tail(body: str) -> str:
        answer_index = body.find("Answer:")
        return body[:answer_index].strip() if answer_index != -1 else body.strip()

    @staticmethod
    def _extract_last_number(text: str) -> float | None:
        numbers = NUMBER_RE.findall(text)
        if not numbers:
            return None
        try:
            return float(numbers[-1])
        except ValueError:
            return None

    @staticmethod
    def _extract_answer(solution: str) -> float | None:
        match = re.search(r"<answer>\s*([-+]?\d+(?:\.\d+)?)", solution, re.IGNORECASE)
        if match is None:
            match = re.search(r"Answer:\s*([-+]?\d+(?:\.\d+)?)", solution)
        if match is None:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _split_preamble(solution: str) -> tuple[str, str]:
        first_define = DEFINE_RE.search(solution)
        if first_define is None:
            return solution, ""
        return solution[: first_define.start()].strip(), solution[first_define.start() :]


def compare_solutions(gold: str, prediction: str, tolerance: float = 1e-6) -> dict[str, Any]:
    parser = SolutionParser()
    report = parser.graph(gold).compare(parser.graph(prediction), tolerance=tolerance)
    report["perfect"] = not (
        report["missing_in_pred"]
        or report["value_mismatches"]
        or report["dependency_mismatches"]
        or report["answer_mismatch"] is not None
    )
    return report
