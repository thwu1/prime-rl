"""Entry point for VLM aerodynamic analysis pipeline."""
import json
import sys
from aero.solver import analyze_case


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "/app/config.json"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "/app/results.json"

    with open(config_path) as f:
        config = json.load(f)

    if "cases" not in config:
        raise ValueError(
            f"Config at {config_path} missing 'cases' key. "
            f"Keys found: {list(config.keys())}"
        )

    results = {"cases": []}
    for case_cfg in config["cases"]:
        result = analyze_case(case_cfg)
        results["cases"].append(result)

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
