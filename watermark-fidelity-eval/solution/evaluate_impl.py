#!/usr/bin/env python3
"""Evaluation script for text watermarking pipeline.


Computes Text Watermarking Fidelity (TWF) = BLEU * Balanced Accuracy.
"""
import json
import argparse
import math
from collections import Counter


def tokenize(text):
    """Simple whitespace tokenization with lowercasing."""
    return text.lower().split()


def compute_ngrams(tokens, n):
    """Count n-grams in a token list."""
    return Counter(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def sentence_bleu(reference, hypothesis, max_n=4):
    """Compute sentence-level BLEU with add-1 smoothing."""
    ref_tokens = tokenize(reference)
    hyp_tokens = tokenize(hypothesis)

    if len(hyp_tokens) == 0:
        return 0.0
    if len(ref_tokens) == 0:
        return 0.0

    # Brevity penalty
    if len(hyp_tokens) >= len(ref_tokens):
        bp = 1.0
    else:
        bp = math.exp(1.0 - len(ref_tokens) / len(hyp_tokens))

    log_avg = 0.0
    effective_order = 0

    for n in range(1, max_n + 1):
        ref_ngrams = compute_ngrams(ref_tokens, n)
        hyp_ngrams = compute_ngrams(hyp_tokens, n)

        total = sum(hyp_ngrams.values())
        if total == 0:
            continue

        clipped = sum(
            min(count, ref_ngrams.get(ngram, 0))
            for ngram, count in hyp_ngrams.items()
        )

        # Add-1 smoothing
        precision = (clipped + 1.0) / (total + 1.0)
        log_avg += math.log(precision)
        effective_order += 1

    if effective_order == 0:
        return 0.0

    return bp * math.exp(log_avg / effective_order)


def compute_bleu(original_file, watermarked_file):
    """Average sentence-level BLEU across documents."""
    originals = {}
    with open(original_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            originals[entry["id"]] = entry["text"]

    total_bleu = 0.0
    count = 0

    with open(watermarked_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            doc_id = entry["id"]
            if doc_id in originals:
                bleu = sentence_bleu(originals[doc_id], entry["text"])
                total_bleu += bleu
                count += 1

    return total_bleu / count if count > 0 else 0.0


def compute_balanced_accuracy(detection_file, ground_truth_file):
    """Compute balanced accuracy and confusion matrix [[TN,FP],[FN,TP]]."""
    truth = {}
    with open(ground_truth_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            truth[entry["id"]] = entry["label"]

    tp = fp = tn = fn = 0

    with open(detection_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            doc_id = entry["id"]
            predicted = entry["label"]
            actual = truth.get(doc_id, 0.0)

            if actual >= 0.5:
                if predicted >= 0.5:
                    tp += 1
                else:
                    fn += 1
            else:
                if predicted >= 0.5:
                    fp += 1
                else:
                    tn += 1

    tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    tnr = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    balanced_acc = (tpr + tnr) / 2.0

    return balanced_acc, [[tn, fp], [fn, tp]]


def evaluate(original_file, watermarked_file, detection_file, ground_truth_file, output_file):
    bleu = compute_bleu(original_file, watermarked_file)
    balanced_acc, confusion = compute_balanced_accuracy(detection_file, ground_truth_file)
    twf = bleu * balanced_acc

    result = {
        "twf": round(twf, 4),
        "balanced_accuracy": round(balanced_acc, 4),
        "bleu": round(bleu, 4),
        "confusion": confusion,
    }

    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Text watermarking evaluator")
    parser.add_argument("--original", required=True, help="Original texts JSONL")
    parser.add_argument("--watermarked", required=True, help="Watermarked texts JSONL")
    parser.add_argument("--detection", required=True, help="Detection results JSONL")
    parser.add_argument("--ground-truth", required=True, help="Ground truth labels JSONL")
    parser.add_argument("--output", required=True, help="Output evaluation JSON")
    args = parser.parse_args()
    evaluate(args.original, args.watermarked, args.detection, args.ground_truth, args.output)
