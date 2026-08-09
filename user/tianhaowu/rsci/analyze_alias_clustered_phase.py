#!/usr/bin/env python3
"""Compare diffuse and task-clustered value-alias phase predictions."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
from typing import Any, BinaryIO

import matplotlib.pyplot as plt
from scipy.optimize import brentq, root

SCHEMA_VERSION = 1
EXPECTED_ALIAS_FILE_SHA256 = "7c0fab39c1c1520598099572da59914a9298693e565a71695decbbf99fc43fc8"
EXPECTED_ALIAS_CONTENT_SHA256 = "a78df658c295a036366be2cf9a774623f4775db311dab6a98b13b68dea89c13b"
DOSES = (("0.00", 0.0), ("0.01", 0.01), ("0.05", 0.05), ("0.10", 0.10))
ROUNDS = 6
plt.rcParams["svg.hashsalt"] = "rsci-alias-clustered-phase-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias-summary", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-svg", type=Path, required=True)
    return parser.parse_args()


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_stable_file(path: Path) -> tuple[bytes, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    with resolved.open("rb") as handle:
        before = os.fstat(handle.fileno())
        payload = handle.read()
        after = os.fstat(handle.fileno())
    before_identity = (before.st_size, before.st_mtime_ns, before.st_ino)
    after_identity = (after.st_size, after.st_mtime_ns, after.st_ino)
    if before_identity != after_identity:
        raise ValueError(f"File changed while reading: {resolved}")
    if len(payload) != after.st_size:
        raise ValueError(f"Short read from {resolved}: expected {after.st_size}, found {len(payload)}")
    return payload, {
        "path": str(resolved),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def require_dict(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Expected object at {context}")
    return value


def require_nonnegative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Expected nonnegative integer at {context}, found {value!r}")
    return value


def load_alias_summary(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, identity = read_stable_file(path)
    if identity["sha256"] != EXPECTED_ALIAS_FILE_SHA256:
        raise ValueError(
            f"Alias-summary file SHA-256 mismatch: expected={EXPECTED_ALIAS_FILE_SHA256}, actual={identity['sha256']}"
        )
    summary = require_dict(json.loads(payload), "alias summary")
    if summary.get("analysis_id") != "value_alias_shortcut_audit":
        raise ValueError(f"Unexpected alias analysis_id: {summary.get('analysis_id')!r}")
    if summary.get("content_sha256") != EXPECTED_ALIAS_CONTENT_SHA256:
        raise ValueError(
            "Alias-summary declared content SHA-256 mismatch: "
            f"expected={EXPECTED_ALIAS_CONTENT_SHA256}, actual={summary.get('content_sha256')!r}"
        )
    unsigned = dict(summary)
    del unsigned["content_sha256"]
    actual_content_hash = canonical_json_sha256(unsigned)
    if actual_content_hash != EXPECTED_ALIAS_CONTENT_SHA256:
        raise ValueError(
            "Alias-summary canonical content SHA-256 mismatch: "
            f"expected={EXPECTED_ALIAS_CONTENT_SHA256}, actual={actual_content_hash}"
        )
    identity["content_sha256"] = actual_content_hash
    return summary, identity


def binomial_tail_map(x: float, probability: float, samples: int, hits: int) -> float:
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"Prevalence must lie in [0, 1], found {x}")
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"Probability must lie in [0, 1], found {probability}")
    if not 1 <= hits <= samples:
        raise ValueError(f"Invalid hit threshold h={hits} for n={samples}")
    q = probability * x
    return math.fsum(
        math.comb(samples, count) * q**count * (1.0 - q) ** (samples - count) for count in range(hits, samples + 1)
    )


def map_derivative(x: float, probability: float, samples: int, hits: int) -> float:
    q = probability * x
    return probability * samples * math.comb(samples - 1, hits - 1) * q ** (hits - 1) * (1.0 - q) ** (samples - hits)


def iterate_map(seed: float, probability: float, samples: int, hits: int) -> list[float]:
    trajectory = [seed]
    for _ in range(ROUNDS):
        trajectory.append(binomial_tail_map(trajectory[-1], probability, samples, hits))
    return trajectory


def two_hit_saddle(samples: int) -> tuple[float, float]:
    solution = root(
        lambda values: (
            binomial_tail_map(float(values[0]), float(values[1]), samples, 2) - float(values[0]),
            map_derivative(float(values[0]), float(values[1]), samples, 2) - 1.0,
        ),
        (0.54, 3.35 / samples),
    )
    if not solution.success:
        raise RuntimeError(solution.message)
    x_value, probability = (float(value) for value in solution.x)
    if not 0.0 < x_value < 1.0 or not 0.0 < probability < 1.0:
        raise ValueError(f"Invalid two-hit saddle: x={x_value}, p={probability}")
    return probability, x_value


def one_hit_fixed_points(samples: int, probability: float) -> list[dict[str, Any]]:
    derivative = samples * probability
    points: list[dict[str, Any]] = [
        {
            "x": 0.0,
            "derivative": derivative,
            "stable": derivative < 1.0,
            "role": "clean",
        }
    ]
    if derivative <= 1.0:
        return points
    positive = brentq(
        lambda x: binomial_tail_map(x, probability, samples, 1) - x,
        1e-14,
        1.0,
    )
    positive_derivative = map_derivative(positive, probability, samples, 1)
    points.append(
        {
            "x": positive,
            "derivative": positive_derivative,
            "stable": positive_derivative < 1.0,
            "role": "positive",
        }
    )
    return points


def two_hit_fixed_points(
    samples: int,
    probability: float,
    saddle: tuple[float, float],
) -> list[dict[str, Any]]:
    saddle_probability, saddle_x = saddle
    points: list[dict[str, Any]] = [{"x": 0.0, "derivative": 0.0, "stable": True, "role": "clean"}]
    if probability < saddle_probability:
        return points
    if math.isclose(probability, saddle_probability, rel_tol=0.0, abs_tol=1e-12):
        points.append(
            {
                "x": saddle_x,
                "derivative": 1.0,
                "stable": False,
                "semistable": True,
                "role": "saddle_node",
            }
        )
        return points
    separator = brentq(
        lambda x: binomial_tail_map(x, probability, samples, 2) - x,
        1e-14,
        saddle_x,
    )
    high = brentq(
        lambda x: binomial_tail_map(x, probability, samples, 2) - x,
        saddle_x,
        1.0,
    )
    for x_value, role in ((separator, "separator"), (high, "high")):
        derivative = map_derivative(x_value, probability, samples, 2)
        points.append(
            {
                "x": x_value,
                "derivative": derivative,
                "stable": derivative < 1.0,
                "role": role,
            }
        )
    return points


def seed_crossing_probability(seed: float, samples: int, hits: int) -> float:
    if not 0.0 < seed < 1.0:
        raise ValueError(f"Seed must lie strictly inside (0, 1), found {seed}")
    return brentq(
        lambda probability: binomial_tail_map(seed, probability, samples, hits) - seed,
        0.0,
        1.0,
    )


def basin_label(
    seed: float,
    fixed_points: list[dict[str, Any]],
    hits: int,
) -> tuple[str, float]:
    if len(fixed_points) == 1:
        return "clean", 0.0
    if hits == 1:
        return "positive", float(fixed_points[-1]["x"])
    separator = float(fixed_points[1]["x"])
    high = float(fixed_points[-1]["x"])
    if math.isclose(seed, separator, rel_tol=0.0, abs_tol=1e-12):
        return "separator", separator
    if seed < separator:
        return "clean", 0.0
    return "high", high


def model_predictions(
    *,
    samples: int,
    hits: int,
    diffuse_seed: float,
    vulnerable_fraction: float,
    clustered_seed: float,
    two_hit_critical: tuple[float, float],
) -> dict[str, Any]:
    if hits == 1:
        critical_point = {
            "kind": "clean-state stability loss",
            "probability": 1.0 / samples,
        }
        crossing_interpretation = (
            "probability where one iteration leaves this finite seed unchanged; "
            "the asymptotic clean-state threshold remains 1/n"
        )
    else:
        critical_point = {
            "kind": "saddle-node with clean/high coexistence",
            "probability": two_hit_critical[0],
            "x": two_hit_critical[1],
        }
        crossing_interpretation = (
            "probability where this seed lies on the unstable fixed-point branch; "
            "below it the seed is in the clean basin and above it in the high basin"
        )

    result: dict[str, Any] = {
        "parameters": {"samples_n": samples, "required_hits_h": hits},
        "critical_point": critical_point,
        "seed_crossing_doses": {
            "interpretation": crossing_interpretation,
            "diffuse_local_seed": seed_crossing_probability(diffuse_seed, samples, hits),
            "clustered_local_seed": seed_crossing_probability(clustered_seed, samples, hits),
        },
        "doses": {},
    }
    for label, probability in DOSES:
        if hits == 1:
            fixed_points = one_hit_fixed_points(samples, probability)
        else:
            fixed_points = two_hit_fixed_points(samples, probability, two_hit_critical)
        separator = next(
            (float(point["x"]) for point in fixed_points if point["role"] == "separator"),
            None,
        )
        diffuse_local = iterate_map(diffuse_seed, probability, samples, hits)
        clustered_local = iterate_map(clustered_seed, probability, samples, hits)
        diffuse_basin, diffuse_limit = basin_label(diffuse_seed, fixed_points, hits)
        clustered_basin, clustered_limit = basin_label(clustered_seed, fixed_points, hits)
        result["doses"][label] = {
            "probability": probability,
            "fixed_points": fixed_points,
            "unstable_separator": separator,
            "diffuse": {
                "local_trajectory": diffuse_local,
                "global_trajectory": diffuse_local,
                "predicted_basin": diffuse_basin,
                "asymptotic_local_prevalence": diffuse_limit,
                "asymptotic_global_prevalence": diffuse_limit,
            },
            "clustered": {
                "local_trajectory": clustered_local,
                "global_trajectory": [vulnerable_fraction * value for value in clustered_local],
                "predicted_basin": clustered_basin,
                "asymptotic_local_prevalence": clustered_limit,
                "asymptotic_global_prevalence": vulnerable_fraction * clustered_limit,
            },
        }
    return result


def render_figure(result: dict[str, Any]) -> bytes:
    two_hit = result["predictions"]["two_hit_n128"]["doses"]
    vulnerable_fraction = result["observed_seed"]["vulnerable_prompt_fraction"]
    rounds = list(range(ROUNDS + 1))
    figure, axes = plt.subplots(1, 2, figsize=(10.2, 4.15))
    figure.subplots_adjust(left=0.085, right=0.98, bottom=0.17, top=0.79, wspace=0.22)
    for axis, dose in zip(axes, ("0.05", "0.10"), strict=True):
        prediction = two_hit[dose]
        axis.plot(
            rounds,
            prediction["diffuse"]["global_trajectory"],
            color="#377eb8",
            linewidth=2.4,
            marker="o",
            label="diffuse",
        )
        axis.plot(
            rounds,
            prediction["clustered"]["global_trajectory"],
            color="#e6550d",
            linewidth=2.4,
            marker="s",
            label="task-clustered",
        )
        axis.axhline(
            vulnerable_fraction,
            color="#777777",
            linewidth=1.0,
            linestyle=":",
            label="clustered ceiling",
        )
        axis.set_title(f"h=2, n=128, p={100 * prediction['probability']:.0f}%")
        axis.set_xlabel("iterative-SFT round")
        axis.set_xticks(rounds)
        axis.set_ylim((-0.002, 0.07) if dose == "0.05" else (-0.01, 1.02))
        axis.grid(alpha=0.22, linestyle="--")
    axes[0].set_ylabel("global value-alias prevalence")
    axes[1].set_ylabel("global value-alias prevalence")
    axes[1].legend(loc="center right", frameon=False)
    figure.suptitle("Equal-mass diffuse versus task-clustered alias seeds", fontsize=13, y=0.97)

    buffer = io.StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight", metadata={"Date": None})
    plt.close(figure)
    normalized = "\n".join(line.rstrip() for line in buffer.getvalue().splitlines()) + "\n"
    return normalized.encode()


def reserve_output(path: Path) -> BinaryIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("xb")


def main() -> None:
    args = parse_args()
    output_json = args.output_json.expanduser().resolve()
    output_svg = args.output_svg.expanduser().resolve()
    if output_json == output_svg:
        raise ValueError("JSON and SVG outputs must differ")

    summary, input_identity = load_alias_summary(args.alias_summary)
    all_counts = require_dict(require_dict(summary.get("counts"), "counts").get("all"), "counts.all")
    recurrence = require_dict(summary.get("recurrence"), "recurrence")
    opportunities = require_dict(
        require_dict(summary.get("canonical_opportunities"), "canonical_opportunities").get("all"),
        "canonical_opportunities.all",
    )
    alias_rows = require_nonnegative_int(all_counts.get("alias"), "counts.all.alias")
    total_rows = require_nonnegative_int(all_counts.get("rows"), "counts.all.rows")
    prompts_with_alias = require_nonnegative_int(
        recurrence.get("prompts_with_alias"),
        "recurrence.prompts_with_alias",
    )
    total_prompts = require_nonnegative_int(opportunities.get("prompts"), "canonical_opportunities.all.prompts")
    if total_prompts != 7000:
        raise ValueError(f"Expected 7,000 source prompts, found {total_prompts}")
    if not 0 < alias_rows <= total_rows:
        raise ValueError(f"Invalid alias/row counts: {alias_rows}/{total_rows}")
    if not 0 < prompts_with_alias <= total_prompts:
        raise ValueError(f"Invalid vulnerable-prompt counts: {prompts_with_alias}/{total_prompts}")
    if total_rows % total_prompts != 0:
        raise ValueError(f"Rows are not an integer multiple of prompts: {total_rows}/{total_prompts}")

    policies_per_prompt = total_rows // total_prompts
    diffuse_seed = alias_rows / total_rows
    vulnerable_fraction = prompts_with_alias / total_prompts
    clustered_seed = diffuse_seed / vulnerable_fraction
    if not 0.0 < clustered_seed <= 1.0:
        raise ValueError(f"Invalid clustered local seed: {clustered_seed}")
    if not math.isclose(
        diffuse_seed,
        vulnerable_fraction * clustered_seed,
        rel_tol=0.0,
        abs_tol=1e-15,
    ):
        raise ValueError("Diffuse and clustered initial global masses differ")

    two_hit_critical = two_hit_saddle(128)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": "value_alias_clustered_phase_predictions",
        "input": {
            **input_identity,
            "expected_file_sha256": EXPECTED_ALIAS_FILE_SHA256,
            "expected_content_sha256": EXPECTED_ALIAS_CONTENT_SHA256,
        },
        "observed_seed": {
            "alias_rows": alias_rows,
            "total_rows": total_rows,
            "raw_prevalence": diffuse_seed,
            "raw_prevalence_exact": f"{alias_rows}/{total_rows}",
            "prompts_with_alias": prompts_with_alias,
            "total_prompts": total_prompts,
            "vulnerable_prompt_fraction": vulnerable_fraction,
            "vulnerable_prompt_fraction_exact": f"{prompts_with_alias}/{total_prompts}",
            "policies_per_prompt": policies_per_prompt,
            "clustered_local_prevalence": clustered_seed,
            "clustered_local_prevalence_exact": f"{alias_rows}/{policies_per_prompt * prompts_with_alias}",
            "equal_global_initial_mass": True,
        },
        "model": {
            "rounds": ROUNDS,
            "doses": [probability for _, probability in DOSES],
            "local_recurrence": "z_(t+1) = P[Binomial(n, p*z_t) >= h]",
            "diffuse_population": "all prompts have local prevalence z_t=x_t",
            "clustered_population": (
                "alpha of prompts have local prevalence y_t and 1-alpha remain zero; global x_t=alpha*y_t"
            ),
            "equal_mass_initialization": "x_0 = alpha*y_0",
        },
        "assumptions": [
            "one fixed-cardinality SFT round exactly reproduces its selected-target mixture",
            "each prompt receives n independent raw candidates and each alias passes independently with probability p",
            "the 454 observed prompts define a fixed vulnerable subpopulation in the clustered counterfactual",
            "there is no baseline alias innovation, transfer between prompt populations, optimizer memory, or finite-row extinction",
            "the four source policies are treated only as equal-mass prevalence observations, not repeated draws from one policy",
        ],
        "predictions": {
            "one_hit_n16": model_predictions(
                samples=16,
                hits=1,
                diffuse_seed=diffuse_seed,
                vulnerable_fraction=vulnerable_fraction,
                clustered_seed=clustered_seed,
                two_hit_critical=two_hit_critical,
            ),
            "two_hit_n128": model_predictions(
                samples=128,
                hits=2,
                diffuse_seed=diffuse_seed,
                vulnerable_fraction=vulnerable_fraction,
                clustered_seed=clustered_seed,
                two_hit_critical=two_hit_critical,
            ),
        },
        "claim_scope": {
            "theory_prediction_only": True,
            "observed_phase_transition": False,
            "causal_task_clustering_effect_observed": False,
            "applies_to_current_rl_runs": False,
            "natural_prompt_recurrence_used_only_to_define_alpha": True,
            "synthetic_eligibility_count_used": False,
        },
    }
    implementation_path = Path(__file__).resolve()
    result["implementation"] = {
        "path": str(implementation_path),
        "size_bytes": implementation_path.stat().st_size,
        "sha256": hashlib.sha256(implementation_path.read_bytes()).hexdigest(),
    }
    svg_bytes = render_figure(result)
    result["figure"] = {
        "description": "global h=2 trajectories at p=5% and p=10%",
        "size_bytes": len(svg_bytes),
        "sha256": hashlib.sha256(svg_bytes).hexdigest(),
    }
    result["content_sha256"] = canonical_json_sha256(result)
    json_bytes = (json.dumps(result, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()

    svg_handle: BinaryIO | None = None
    json_handle: BinaryIO | None = None
    try:
        svg_handle = reserve_output(output_svg)
        json_handle = reserve_output(output_json)
        svg_handle.write(svg_bytes)
        json_handle.write(json_bytes)
    except BaseException:
        if svg_handle is not None:
            svg_handle.close()
            output_svg.unlink(missing_ok=True)
        if json_handle is not None:
            json_handle.close()
            output_json.unlink(missing_ok=True)
        raise
    else:
        svg_handle.close()
        json_handle.close()

    print(
        json.dumps(
            {
                "content_sha256": result["content_sha256"],
                "output_json": str(output_json),
                "output_svg": str(output_svg),
                "svg_sha256": result["figure"]["sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
