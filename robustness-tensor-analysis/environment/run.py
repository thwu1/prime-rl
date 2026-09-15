#!/usr/bin/env python3
"""Workflow runner for the robustness analysis pipeline."""
import importlib
import json
import os
import sys
import yaml


def load_workflow(path="/app/config/workflow.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def load_analysis_config(path="/app/config/analysis.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def run_pipeline():
    sys.path.insert(0, "/app/pipeline")

    workflow = load_workflow()
    analysis_config = load_analysis_config()
    with open("/app/config/taxonomy.json") as f:
        taxonomy = json.load(f)

    stages = workflow["stages"]
    # Sort stages for deterministic execution order
    stages_sorted = sorted(stages, key=lambda s: s["name"])

    results = {}
    for stage_def in stages_sorted:
        name = stage_def["name"]
        module_path = stage_def["module"]
        print(f"[pipeline] Running stage: {name}")

        mod = importlib.import_module(module_path)
        result = mod.run(results, analysis_config, taxonomy)
        results[name] = result
        print(f"[pipeline] Stage '{name}' complete.")

    # Assemble final report
    report = {}
    key_mapping = {
        "confidence": "wilson_intervals",
        "effects": "effect_matrix",
        "decomposition": "eigendecomposition",
        "robustness": "category_robustness",
        "interactions": "interaction_strength",
        "ranking": "model_ranking",
        "significance": "pairwise_tests"
    }
    for stage_name, output_key in key_mapping.items():
        if stage_name in results:
            report[output_key] = results[stage_name]

    output_path = workflow.get("output_path", "/app/output/report.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[pipeline] Report written to {output_path}")


if __name__ == "__main__":
    run_pipeline()
