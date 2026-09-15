
import argparse
import json
import csv
import os
import sys
import random
from collections import defaultdict


def extract_domain(collection_name):
    parts = collection_name.split('-')
    if len(parts) >= 4 and parts[0] == 'mt' and parts[1] == 'rag':
        return parts[2]
    return None


def load_qrels(qrels_dir, domain):
    qrels_file = os.path.join(qrels_dir, f"{domain}.tsv")
    qrels = {}
    with open(qrels_file, 'r') as f:
        reader = csv.reader(f, delimiter='\t')
        next(reader)
        for row in reader:
            query_id, corpus_id, score = row[0], row[1], int(row[2])
            if query_id not in qrels:
                qrels[query_id] = {}
            qrels[query_id][corpus_id] = score
    return qrels


def load_predictions(pred_file):
    predictions = []
    with open(pred_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                predictions.append(json.loads(line))
    return predictions


def load_input(input_file):
    tasks = {}
    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                item = json.loads(line)
                tasks[item['task_id']] = item
    return tasks


def validate_format(input_file, pred_file, mode):
    errors = []

    input_ids = set()
    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    item = json.loads(line)
                    if 'task_id' in item:
                        input_ids.add(item['task_id'])
                except json.JSONDecodeError:
                    pass

    pred_ids = set()
    with open(pred_file, 'r') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"[Line {line_no}] Invalid JSON: {e}")
                continue

            if 'task_id' in item and isinstance(item.get('task_id'), str):
                pred_ids.add(item['task_id'])

            if mode == 'retrieval_taska':
                for field in ['task_id', 'Collection', 'contexts']:
                    if field not in item:
                        errors.append(f"[Line {line_no}] Missing '{field}'")
                if 'contexts' in item:
                    if not isinstance(item['contexts'], list):
                        errors.append(f"[Line {line_no}] 'contexts' must be a list")
                    else:
                        for i, ctx in enumerate(item['contexts']):
                            if not isinstance(ctx, dict):
                                errors.append(f"[Line {line_no}] contexts[{i}] must be object")
                                continue
                            if 'document_id' not in ctx:
                                errors.append(f"[Line {line_no}] contexts[{i}] missing 'document_id'")
                            if 'score' not in ctx:
                                errors.append(f"[Line {line_no}] contexts[{i}] missing 'score'")
                            elif not isinstance(ctx['score'], (int, float)):
                                errors.append(f"[Line {line_no}] contexts[{i}].score must be numeric")

            elif mode == 'generation_taskb':
                for field in ['task_id', 'input', 'contexts', 'predictions']:
                    if field not in item:
                        errors.append(f"[Line {line_no}] Missing '{field}'")
                if 'contexts' in item:
                    if not isinstance(item['contexts'], list):
                        errors.append(f"[Line {line_no}] 'contexts' must be a list")
                if 'predictions' in item:
                    if not isinstance(item['predictions'], list):
                        errors.append(f"[Line {line_no}] 'predictions' must be a list")
                    else:
                        for i, p in enumerate(item['predictions']):
                            if not isinstance(p, dict):
                                errors.append(f"[Line {line_no}] predictions[{i}] must be object")
                                continue
                            if 'text' not in p:
                                errors.append(f"[Line {line_no}] predictions[{i}] missing 'text'")

            elif mode == 'rag_taskc':
                for field in ['task_id', 'Collection', 'input', 'contexts', 'predictions']:
                    if field not in item:
                        errors.append(f"[Line {line_no}] Missing '{field}'")
                if 'contexts' in item:
                    if not isinstance(item['contexts'], list):
                        errors.append(f"[Line {line_no}] 'contexts' must be a list")
                    else:
                        for i, ctx in enumerate(item['contexts']):
                            if not isinstance(ctx, dict):
                                errors.append(f"[Line {line_no}] contexts[{i}] must be object")
                                continue
                            if 'document_id' not in ctx:
                                errors.append(f"[Line {line_no}] contexts[{i}] missing 'document_id'")
                            if 'score' not in ctx:
                                errors.append(f"[Line {line_no}] contexts[{i}] missing 'score'")
                            elif not isinstance(ctx['score'], (int, float)):
                                errors.append(f"[Line {line_no}] contexts[{i}].score must be numeric")
                if 'predictions' in item:
                    if not isinstance(item['predictions'], list):
                        errors.append(f"[Line {line_no}] 'predictions' must be a list")
                    else:
                        for i, p in enumerate(item['predictions']):
                            if not isinstance(p, dict):
                                errors.append(f"[Line {line_no}] predictions[{i}] must be object")
                                continue
                            if 'text' not in p:
                                errors.append(f"[Line {line_no}] predictions[{i}] missing 'text'")

    missing = input_ids - pred_ids
    extra = pred_ids - input_ids
    for tid in sorted(missing):
        errors.append(f"Missing task_id '{tid}'")
    for tid in sorted(extra):
        errors.append(f"Extra task_id '{tid}'")

    return errors


def compute_retrieval_metrics(qrels, results, k_values):
    import pytrec_eval

    ndcg_string = "ndcg_cut." + ",".join([str(k) for k in k_values])
    recall_string = "recall." + ",".join([str(k) for k in k_values])

    evaluator = pytrec_eval.RelevanceEvaluator(qrels, {ndcg_string, recall_string})
    scores = evaluator.evaluate(results)

    ndcg = {}
    recall = {}
    for k in k_values:
        ndcg[f"nDCG@{k}"] = 0.0
        recall[f"Recall@{k}"] = 0.0

    for query_id in scores:
        for k in k_values:
            ndcg[f"nDCG@{k}"] += scores[query_id][f"ndcg_cut_{k}"]
            recall[f"Recall@{k}"] += scores[query_id][f"recall_{k}"]

    n = len(scores)
    if n > 0:
        for k in k_values:
            ndcg[f"nDCG@{k}"] = round(ndcg[f"nDCG@{k}"] / n, 5)
            recall[f"Recall@{k}"] = round(recall[f"Recall@{k}"] / n, 5)

    return ndcg, recall, scores


def compute_rouge_l(pred_texts, target_texts):
    from rouge_score import rouge_scorer

    scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=False)
    scores = {}

    for task_id in pred_texts:
        if task_id in target_texts:
            result = scorer.score(target_texts[task_id], pred_texts[task_id])
            scores[task_id] = result['rougeL'].fmeasure

    avg = sum(scores.values()) / len(scores) if scores else 0.0
    return avg, scores


def harmonic_mean(values):
    if not values or any(v == 0 for v in values):
        return 0.0
    return len(values) / sum(1.0 / v for v in values)


def do_evaluate(input_file, pred_file, qrels_dir, output_file):
    input_tasks = load_input(input_file)
    predictions = load_predictions(pred_file)

    collection_preds = defaultdict(dict)
    pred_texts = {}
    for pred in predictions:
        task_id = pred['task_id']
        collection = pred['Collection']
        domain = extract_domain(collection)

        doc_scores = {}
        for ctx in pred.get('contexts', []):
            doc_scores[ctx['document_id']] = ctx['score']
        collection_preds[domain][task_id] = doc_scores

        if 'predictions' in pred and pred['predictions']:
            pred_texts[task_id] = pred['predictions'][0]['text']

    target_texts = {}
    for task_id, task in input_tasks.items():
        if 'targets' in task and task['targets']:
            target_texts[task_id] = task['targets'][0]['text']

    k_values = [1, 3, 5]
    results = {"retrieval": {"per_collection": {}}, "generation": {}}

    total_count = 0
    all_ndcg = defaultdict(float)
    all_recall = defaultdict(float)
    per_query_retrieval = {}

    for domain in sorted(collection_preds.keys()):
        preds = collection_preds[domain]
        qrels = load_qrels(qrels_dir, domain)
        ndcg, recall, pytrec_scores = compute_retrieval_metrics(qrels, preds, k_values)
        count = len(preds)
        total_count += count

        results["retrieval"]["per_collection"][domain] = {
            **ndcg, **recall, "count": count
        }

        for key, val in ndcg.items():
            all_ndcg[key] += val * count
        for key, val in recall.items():
            all_recall[key] += val * count

        # Save per-query retrieval scores
        for qid in pytrec_scores:
            per_query_retrieval[qid] = {
                "nDCG@5": round(pytrec_scores[qid].get("ndcg_cut_5", 0), 5),
                "Recall@5": round(pytrec_scores[qid].get("recall_5", 0), 5),
            }

    weighted = {}
    if total_count > 0:
        for key in sorted(all_ndcg.keys()):
            weighted[key] = round(all_ndcg[key] / total_count, 5)
        for key in sorted(all_recall.keys()):
            weighted[key] = round(all_recall[key] / total_count, 5)

    results["retrieval"]["weighted_average"] = weighted

    rouge_avg, rouge_per_task = compute_rouge_l(pred_texts, target_texts)
    results["generation"] = {
        "rouge_l_f1": round(rouge_avg, 5),
        "per_task": {k: round(v, 5) for k, v in sorted(rouge_per_task.items())}
    }

    # Build per_query section
    per_query = {}
    all_task_ids = sorted(set(list(per_query_retrieval.keys()) + list(rouge_per_task.keys())))
    for task_id in all_task_ids:
        per_query[task_id] = {
            "nDCG@5": per_query_retrieval.get(task_id, {}).get("nDCG@5", 0),
            "Recall@5": per_query_retrieval.get(task_id, {}).get("Recall@5", 0),
            "ROUGE-L_F1": round(rouge_per_task.get(task_id, 0), 5),
        }
    results["per_query"] = per_query

    hm = harmonic_mean([
        weighted.get("nDCG@5", 0),
        weighted.get("Recall@5", 0),
        rouge_avg
    ])
    results["overall"] = {"harmonic_mean": round(hm, 5)}

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    return results


def do_rank(results_dir, output_file):
    results = {}
    for fname in sorted(os.listdir(results_dir)):
        if fname.endswith('.json'):
            system_name = fname.replace('.json', '')
            with open(os.path.join(results_dir, fname)) as f:
                results[system_name] = json.load(f)

    rankings = []
    for system_name, data in results.items():
        weighted = data.get("retrieval", {}).get("weighted_average", {})
        rouge = data.get("generation", {}).get("rouge_l_f1", 0)
        hm = data.get("overall", {}).get("harmonic_mean", 0)
        rankings.append({
            "system": system_name,
            "nDCG@5": weighted.get("nDCG@5", 0),
            "Recall@5": weighted.get("Recall@5", 0),
            "ROUGE-L_F1": rouge,
            "harmonic_mean": hm
        })

    rankings.sort(key=lambda x: x["harmonic_mean"], reverse=True)

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "system", "nDCG@5", "Recall@5", "ROUGE-L_F1", "harmonic_mean"])
        writer.writeheader()
        for i, r in enumerate(rankings, 1):
            writer.writerow({"rank": i, **r})


def do_compare(result_a_file, result_b_file, output_file, seed=42, num_permutations=10000):
    with open(result_a_file) as f:
        result_a = json.load(f)
    with open(result_b_file) as f:
        result_b = json.load(f)

    per_query_a = result_a["per_query"]
    per_query_b = result_b["per_query"]

    # Find common queries
    common_queries = sorted(set(per_query_a.keys()) & set(per_query_b.keys()))

    system_a_name = os.path.splitext(os.path.basename(result_a_file))[0]
    system_b_name = os.path.splitext(os.path.basename(result_b_file))[0]

    output = {
        "system_a": system_a_name,
        "system_b": system_b_name,
        "num_queries": len(common_queries),
        "seed": seed,
        "num_permutations": num_permutations,
        "metrics": {}
    }

    for metric in ["nDCG@5", "Recall@5", "ROUGE-L_F1"]:
        scores_a = [per_query_a[q][metric] for q in common_queries]
        scores_b = [per_query_b[q][metric] for q in common_queries]

        diffs = [a - b for a, b in zip(scores_a, scores_b)]
        observed_delta = sum(diffs) / len(diffs) if diffs else 0.0

        rng = random.Random(seed)
        count_extreme = 0
        for _ in range(num_permutations):
            permuted_diffs = []
            for d in diffs:
                if rng.random() < 0.5:
                    permuted_diffs.append(d)
                else:
                    permuted_diffs.append(-d)
            permuted_delta = sum(permuted_diffs) / len(permuted_diffs) if permuted_diffs else 0.0
            if abs(permuted_delta) >= abs(observed_delta):
                count_extreme += 1

        p_value = count_extreme / num_permutations if num_permutations > 0 else 1.0

        mean_a = sum(scores_a) / len(scores_a) if scores_a else 0.0
        mean_b = sum(scores_b) / len(scores_b) if scores_b else 0.0

        output["metrics"][metric] = {
            "mean_a": round(mean_a, 5),
            "mean_b": round(mean_b, 5),
            "delta": round(observed_delta, 5),
            "p_value": round(p_value, 5),
            "significant": p_value < 0.05,
        }

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    return output


def main():
    parser = argparse.ArgumentParser(description="MTRAG Evaluation Pipeline")
    subparsers = parser.add_subparsers(dest="command")

    val_parser = subparsers.add_parser("validate")
    val_parser.add_argument("--input", required=True)
    val_parser.add_argument("--predictions", required=True)
    val_parser.add_argument("--mode", required=True,
                            choices=["retrieval_taska", "generation_taskb", "rag_taskc"])

    eval_parser = subparsers.add_parser("evaluate")
    eval_parser.add_argument("--input", required=True)
    eval_parser.add_argument("--predictions", required=True)
    eval_parser.add_argument("--qrels-dir", required=True)
    eval_parser.add_argument("--output", required=True)

    rank_parser = subparsers.add_parser("rank")
    rank_parser.add_argument("--results-dir", required=True)
    rank_parser.add_argument("--output", required=True)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--result-a", required=True)
    compare_parser.add_argument("--result-b", required=True)
    compare_parser.add_argument("--output", required=True)
    compare_parser.add_argument("--seed", type=int, default=42)
    compare_parser.add_argument("--num-permutations", type=int, default=10000)

    args = parser.parse_args()

    if args.command == "validate":
        errors = validate_format(args.input, args.predictions, args.mode)
        if errors:
            print(f"Found {len(errors)} error(s):")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)
        else:
            print("Format is valid.")
            sys.exit(0)

    elif args.command == "evaluate":
        result = do_evaluate(args.input, args.predictions, args.qrels_dir, args.output)
        print(json.dumps(result, indent=2))

    elif args.command == "rank":
        do_rank(args.results_dir, args.output)
        print(f"Rankings written to {args.output}")

    elif args.command == "compare":
        result = do_compare(
            args.result_a, args.result_b, args.output,
            seed=args.seed, num_permutations=args.num_permutations
        )
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
