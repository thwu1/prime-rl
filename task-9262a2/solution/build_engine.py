#!/usr/bin/env python3

"""
Build script that generates the rubric scoring engine at /app/rubric_engine.py.
Constructs the tool by assembling the scoring algorithms programmatically.
"""

import os
import textwrap


def build_imports():
    return textwrap.dedent("""\
        #!/usr/bin/env python3
        \"\"\"Hierarchical rubric scoring engine for PaperBench-format evaluation rubrics.\"\"\"

        import argparse
        import json
        import sys
        from pathlib import Path
    """)


def build_utility_functions():
    return textwrap.dedent("""\

        def load_json(path):
            with open(path) as f:
                return json.load(f)


        def get_leaves(node):
            if not node.get("sub_tasks"):
                return [node]
            leaves = []
            for child in node["sub_tasks"]:
                leaves.extend(get_leaves(child))
            return leaves
    """)


def build_score_functions():
    return textwrap.dedent("""\

        def compute_score(node, grades):
            if not node.get("sub_tasks"):
                return float(grades[node["id"]])
            total_weight = sum(c["weight"] for c in node["sub_tasks"])
            weighted_sum = sum(
                c["weight"] * compute_score(c, grades) for c in node["sub_tasks"]
            )
            return weighted_sum / total_weight


        def compute_pruned_score(node, grades, depth_limit, current_depth=0):
            if not node.get("sub_tasks"):
                return float(grades[node["id"]])
            if current_depth >= depth_limit:
                leaves = get_leaves(node)
                leaf_grades = [float(grades[leaf["id"]]) for leaf in leaves]
                return sum(leaf_grades) / len(leaf_grades)
            total_weight = sum(c["weight"] for c in node["sub_tasks"])
            weighted_sum = sum(
                c["weight"] * compute_pruned_score(c, grades, depth_limit, current_depth + 1)
                for c in node["sub_tasks"]
            )
            return weighted_sum / total_weight


        def get_max_depth(node, current_depth=0):
            if not node.get("sub_tasks"):
                return current_depth
            return max(
                get_max_depth(c, current_depth + 1) for c in node["sub_tasks"]
            )


        def compute_sensitivity(node, path_weight=1.0):
            if not node.get("sub_tasks"):
                return {node["id"]: path_weight}
            total_weight = sum(c["weight"] for c in node["sub_tasks"])
            result = {}
            for child in node["sub_tasks"]:
                child_factor = child["weight"] / total_weight
                child_sensitivities = compute_sensitivity(child, path_weight * child_factor)
                result.update(child_sensitivities)
            return result
    """)


def build_command_handlers():
    return textwrap.dedent("""\

        def cmd_score(args):
            rubric = load_json(args.rubric)
            grades = load_json(args.grades)
            score = compute_score(rubric, grades)
            print(json.dumps({"replication_score": score}))


        def cmd_prune_score(args):
            rubric = load_json(args.rubric)
            grades = load_json(args.grades)
            full_score = compute_score(rubric, grades)
            pruned_score = compute_pruned_score(rubric, grades, args.depth)
            absolute_error = abs(pruned_score - full_score)
            print(json.dumps({
                "pruned_score": pruned_score,
                "full_score": full_score,
                "absolute_error": absolute_error,
            }))


        def cmd_optimal_depth(args):
            rubrics_dir = Path(args.rubrics_dir)
            grades_dir = Path(args.grades_dir)
            epsilon = args.epsilon
            pairs = []
            for rubric_file in sorted(rubrics_dir.glob("*.json")):
                grade_file = grades_dir / rubric_file.name
                if grade_file.exists():
                    rubric = load_json(rubric_file)
                    grades = load_json(grade_file)
                    full_score = compute_score(rubric, grades)
                    max_d = get_max_depth(rubric)
                    pairs.append((rubric, grades, full_score, max_d))
            if not pairs:
                print(json.dumps({"optimal_depth": 0, "max_error": 0.0}))
                return
            overall_max_depth = max(md for _, _, _, md in pairs)
            for d in range(1, overall_max_depth + 1):
                max_error = 0.0
                for rubric, grades, full_score, _ in pairs:
                    pruned = compute_pruned_score(rubric, grades, d)
                    error = abs(pruned - full_score)
                    max_error = max(max_error, error)
                if max_error <= epsilon:
                    print(json.dumps({"optimal_depth": d, "max_error": max_error}))
                    return
            print(json.dumps({"optimal_depth": overall_max_depth, "max_error": 0.0}))


        def cmd_judge_eval(args):
            rubric = load_json(args.rubric)
            gt = load_json(args.ground_truth)
            pred = load_json(args.predicted)
            leaves = get_leaves(rubric)
            categories = {}
            for leaf in leaves:
                cat = leaf.get("task_category", "Unknown")
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(leaf["id"])
            per_category = {}
            for cat in sorted(categories.keys()):
                leaf_ids = categories[cat]
                tp = fp = fn = tn = 0
                for lid in leaf_ids:
                    g = gt[lid]
                    p = pred[lid]
                    if g == 1 and p == 1:
                        tp += 1
                    elif g == 0 and p == 1:
                        fp += 1
                    elif g == 1 and p == 0:
                        fn += 1
                    else:
                        tn += 1
                precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                f1 = (2 * precision * recall / (precision + recall)
                      if (precision + recall) > 0 else 0.0)
                per_category[cat] = {
                    "precision": precision,
                    "recall": recall,
                    "f1": f1,
                }
            n = len(per_category)
            macro_p = sum(v["precision"] for v in per_category.values()) / n
            macro_r = sum(v["recall"] for v in per_category.values()) / n
            macro_f1 = sum(v["f1"] for v in per_category.values()) / n
            print(json.dumps({
                "per_category": per_category,
                "macro_average": {
                    "precision": macro_p,
                    "recall": macro_r,
                    "f1": macro_f1,
                },
            }))


        def cmd_sensitivity(args):
            rubric = load_json(args.rubric)
            sensitivities = compute_sensitivity(rubric)
            print(json.dumps({"sensitivities": sensitivities}))
    """)


def build_main():
    return textwrap.dedent("""\

        def main():
            parser = argparse.ArgumentParser(
                description="Hierarchical rubric scoring engine"
            )
            subparsers = parser.add_subparsers(dest="command", required=True)

            p_score = subparsers.add_parser("score")
            p_score.add_argument("--rubric", required=True)
            p_score.add_argument("--grades", required=True)

            p_prune = subparsers.add_parser("prune-score")
            p_prune.add_argument("--rubric", required=True)
            p_prune.add_argument("--grades", required=True)
            p_prune.add_argument("--depth", type=int, required=True)

            p_opt = subparsers.add_parser("optimal-depth")
            p_opt.add_argument("--rubrics-dir", required=True)
            p_opt.add_argument("--grades-dir", required=True)
            p_opt.add_argument("--epsilon", type=float, required=True)

            p_judge = subparsers.add_parser("judge-eval")
            p_judge.add_argument("--rubric", required=True)
            p_judge.add_argument("--ground-truth", required=True)
            p_judge.add_argument("--predicted", required=True)

            p_sens = subparsers.add_parser("sensitivity")
            p_sens.add_argument("--rubric", required=True)
            p_sens.add_argument("--grades", required=True)

            args = parser.parse_args()

            if args.command == "score":
                cmd_score(args)
            elif args.command == "prune-score":
                cmd_prune_score(args)
            elif args.command == "optimal-depth":
                cmd_optimal_depth(args)
            elif args.command == "judge-eval":
                cmd_judge_eval(args)
            elif args.command == "sensitivity":
                cmd_sensitivity(args)


        if __name__ == "__main__":
            main()
    """)


def main():
    """Assemble and write the rubric scoring engine."""
    output_path = "/app/rubric_engine.py"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    code = (
        build_imports()
        + build_utility_functions()
        + build_score_functions()
        + build_command_handlers()
        + build_main()
    )

    with open(output_path, "w") as f:
        f.write(code)

    print(f"Generated {output_path} ({len(code)} bytes)")


if __name__ == "__main__":
    main()
