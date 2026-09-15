"""

Direct evaluation pipeline for test prioritization.
Loads dataset, extracts curvature features, trains a logistic regression
from scratch, prioritizes test cases by predicted failure probability,
computes APFD/APFDc metrics, and writes results.json.
"""
import json
import math


def extract_features(road_points):
    """Extract road geometry features from a list of {x, y} points."""
    xs = [p["x"] for p in road_points]
    ys = [p["y"] for p in road_points]
    n = len(xs)
    if n < 3:
        return [0.0] * 7

    # Segment lengths
    seg_lengths = []
    for i in range(n - 1):
        dx = xs[i + 1] - xs[i]
        dy = ys[i + 1] - ys[i]
        seg_lengths.append(math.sqrt(dx * dx + dy * dy))
    total_length = sum(seg_lengths)

    # Angles between consecutive segments (curvature proxy)
    angles = []
    for i in range(n - 2):
        dx1, dy1 = xs[i + 1] - xs[i], ys[i + 1] - ys[i]
        dx2, dy2 = xs[i + 2] - xs[i + 1], ys[i + 2] - ys[i + 1]
        a1 = math.atan2(dy1, dx1)
        a2 = math.atan2(dy2, dx2)
        diff = abs(a2 - a1)
        if diff > math.pi:
            diff = 2 * math.pi - diff
        angles.append(diff)

    total_curvature = sum(angles)
    max_curvature = max(angles) if angles else 0.0
    mean_curvature = total_curvature / len(angles) if angles else 0.0

    if len(angles) > 1:
        var = sum((a - mean_curvature) ** 2 for a in angles) / len(angles)
        std_curvature = math.sqrt(var)
    else:
        std_curvature = 0.0

    direct_dist = math.sqrt((xs[-1] - xs[0]) ** 2 + (ys[-1] - ys[0]) ** 2)
    sinuosity = total_length / direct_dist if direct_dist > 1e-9 else 1.0
    sharp_turns = sum(1 for a in angles if a > 0.3)

    return [
        total_curvature,
        max_curvature,
        mean_curvature,
        std_curvature,
        total_length,
        sinuosity,
        float(sharp_turns),
    ]


def sigmoid(x):
    x = max(-500.0, min(500.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def normalize(X, means, stds):
    return [[(x[j] - means[j]) / stds[j] for j in range(len(means))] for x in X]


def train_logistic_regression(X, y, lr=0.01, epochs=500):
    """Train logistic regression via SGD. Returns weights, bias."""
    n_feat = len(X[0])
    w = [0.0] * n_feat
    b = 0.0
    for _ in range(epochs):
        for i in range(len(X)):
            z = sum(w[j] * X[i][j] for j in range(n_feat)) + b
            pred = sigmoid(z)
            err = pred - y[i]
            for j in range(n_feat):
                w[j] -= lr * err * X[i][j]
            b -= lr * err
    return w, b


def predict_failure_prob(X, w, b):
    return [sigmoid(sum(w[j] * x[j] for j in range(len(w))) + b) for x in X]


def compute_apfd(prioritized_ids, test_dict):
    n = len(prioritized_ids)
    failed_pos = []
    for i, tid in enumerate(prioritized_ids):
        if test_dict[tid]["meta_data"]["test_info"]["test_outcome"] == "FAIL":
            failed_pos.append(i + 1)
    m = len(failed_pos)
    if n == 0 or m == 0:
        return 1.0
    return 1 - sum(failed_pos) / (n * m) + 1 / (2 * n)


def compute_apfdc(prioritized_ids, test_dict):
    cumtime = 0.0
    total_cost = 0.0
    cum_costs = []
    nfail = 0
    for tid in prioritized_ids:
        t = test_dict[tid]
        dur = t["meta_data"]["test_info"]["test_duration"]
        cumtime += dur
        total_cost += dur
        if t["meta_data"]["test_info"]["test_outcome"] == "FAIL":
            cum_costs.append(cumtime)
            nfail += 1
    if nfail == 0 or total_cost == 0:
        return 1.0
    return 1 - sum(cum_costs) / (total_cost * nfail) + 1 / (2 * nfail)


def main():
    # Load dataset
    with open("/app/test_data.json") as f:
        data = json.load(f)

    # Split: first 80% train, last 20% test
    split_idx = int(0.8 * len(data))
    train_data = data[:split_idx]
    test_data_list = data[split_idx:]
    test_dict = {t["_id"]["$oid"]: t for t in test_data_list}

    print(f"Train: {len(train_data)}, Test: {len(test_data_list)}")

    # Extract features
    train_X = [extract_features(t["road_points"]) for t in train_data]
    train_y = [
        1 if t["meta_data"]["test_info"]["test_outcome"] == "FAIL" else 0
        for t in train_data
    ]
    test_X = [extract_features(t["road_points"]) for t in test_data_list]
    test_ids = [t["_id"]["$oid"] for t in test_data_list]

    # Normalize using training statistics
    n_feat = len(train_X[0])
    means = [sum(x[j] for x in train_X) / len(train_X) for j in range(n_feat)]
    stds = [
        max(1e-9, math.sqrt(sum((x[j] - means[j]) ** 2 for x in train_X) / len(train_X)))
        for j in range(n_feat)
    ]

    train_X_norm = normalize(train_X, means, stds)
    test_X_norm = normalize(test_X, means, stds)

    # Train logistic regression from scratch
    weights, bias = train_logistic_regression(train_X_norm, train_y)

    # Predict failure probabilities
    fail_probs = predict_failure_prob(test_X_norm, weights, bias)

    # Sort descending by failure probability (failures first)
    indexed = sorted(range(len(fail_probs)), key=lambda i: fail_probs[i], reverse=True)
    prioritized_ids = [test_ids[i] for i in indexed]

    # Compute metrics
    apfd = compute_apfd(prioritized_ids, test_dict)
    apfdc = compute_apfdc(prioritized_ids, test_dict)

    print(f"APFD: {apfd:.4f}")
    print(f"APFDc: {apfdc:.4f}")

    # Write results
    results = {
        "tool_name": "curvature_prioritizer",
        "train_size": len(train_data),
        "test_size": len(test_data_list),
        "prioritized_order": prioritized_ids,
        "apfd": round(apfd, 6),
        "apfdc": round(apfdc, 6),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
