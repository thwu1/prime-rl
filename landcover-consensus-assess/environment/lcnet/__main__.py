"""CLI interface."""

import argparse
import json
import csv
import sys
import numpy as np


def cmd_consensus(args):
    from .consensus import compute_consensus
    with open(args.input) as f:
        data = json.load(f)
    annotations = [np.array(a) for a in data["annotations"]]
    weights = data["weights"]
    num_classes = data.get("num_classes", 7)
    labels, scores = compute_consensus(annotations, weights, num_classes)
    result = {"labels": labels.tolist(), "scores": scores.tolist()}
    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)


def cmd_assess(args):
    from .metrics import assess

    def read_csv_labels(path):
        with open(path) as f:
            reader = csv.DictReader(f)
            return {row["id"]: int(row["label"]) for row in reader}

    pred_map = read_csv_labels(args.predictions)
    truth_map = read_csv_labels(args.truth)

    ids = sorted(truth_map.keys())
    predictions = [pred_map[i] for i in ids]
    ground_truth = [truth_map[i] for i in ids]

    result = assess(predictions, ground_truth)

    if args.db:
        from .storage import store_assessment
        store_assessment(result, args.level, args.db)

    print(json.dumps(result, indent=2))


def cmd_score(args):
    from .scoring import validate_submission, cross_entropy_score
    with open(args.submission) as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        class_cols = [c for c in fields if c != "id"]
        sub_data = {}
        for row in reader:
            fid = row["id"]
            probs = [float(row[c]) for c in class_cols]
            sub_data[fid] = probs

    with open(args.truth) as f:
        reader = csv.DictReader(f)
        truth_data = {row["id"]: int(row["label"]) for row in reader}

    field_ids = sorted(truth_data.keys())
    num_classes = len(class_cols)

    valid, errors = validate_submission(sub_data, field_ids, num_classes)

    result = {"valid": valid, "errors": errors}
    if valid:
        submission_arr = np.array([sub_data[fid] for fid in field_ids])
        truth_arr = np.array([truth_data[fid] for fid in field_ids])
        result["cross_entropy"] = float(cross_entropy_score(submission_arr, truth_arr))

    print(json.dumps(result, indent=2))


def cmd_report(args):
    from .storage import get_summary
    summary = get_summary(args.db)
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="lcnet")
    subparsers = parser.add_subparsers(dest="command")

    p = subparsers.add_parser("consensus")
    p.add_argument("input")
    p.add_argument("output")

    p = subparsers.add_parser("assess")
    p.add_argument("predictions")
    p.add_argument("truth")
    p.add_argument("--level", type=int, default=3)
    p.add_argument("--db", type=str, default=None)

    p = subparsers.add_parser("score")
    p.add_argument("submission")
    p.add_argument("truth")
    p.add_argument("--db", type=str, default=None)

    p = subparsers.add_parser("report")
    p.add_argument("--db", type=str, required=True)

    args = parser.parse_args()

    if args.command == "consensus":
        cmd_consensus(args)
    elif args.command == "assess":
        cmd_assess(args)
    elif args.command == "score":
        cmd_score(args)
    elif args.command == "report":
        cmd_report(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
