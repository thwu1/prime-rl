"""

Evaluation client. Connects to the gRPC prioritization server,
runs the full Name -> Initialize -> Prioritize pipeline,
and writes results.json with estimated metrics.
"""
import json
import math
import sys

sys.path.insert(0, "/app")

import grpc
import interface_pb2
import interface_pb2_grpc


def sigmoid(x):
    x = max(-500, min(500, x))
    return 1 / (1 + math.exp(-x))


def extract_features(road_points):
    """Same feature extraction as server for cross-validation."""
    xs = [p["x"] for p in road_points]
    ys = [p["y"] for p in road_points]
    n = len(xs)
    if n < 3:
        return [0.0] * 7
    seg = [math.sqrt((xs[i+1]-xs[i])**2 + (ys[i+1]-ys[i])**2) for i in range(n-1)]
    tl = sum(seg)
    angles = []
    for i in range(n - 2):
        a1 = math.atan2(ys[i+1]-ys[i], xs[i+1]-xs[i])
        a2 = math.atan2(ys[i+2]-ys[i+1], xs[i+2]-xs[i+1])
        d = abs(a2 - a1)
        if d > math.pi:
            d = 2 * math.pi - d
        angles.append(d)
    tc = sum(angles)
    mc = max(angles) if angles else 0
    meanc = tc / len(angles) if angles else 0
    stdc = math.sqrt(sum((a - meanc)**2 for a in angles) / len(angles)) if len(angles) > 1 else 0
    dd = math.sqrt((xs[-1]-xs[0])**2 + (ys[-1]-ys[0])**2)
    sin = tl / dd if dd > 1e-9 else 1.0
    sharp = sum(1 for a in angles if a > 0.3)
    return [tc, mc, meanc, stdc, tl, sin, float(sharp)]


def compute_apfd(ordered_ids, labels):
    """Compute APFD on data with known labels."""
    n = len(ordered_ids)
    fps = [i + 1 for i, tid in enumerate(ordered_ids) if labels[tid]]
    m = len(fps)
    if n == 0 or m == 0:
        return 1.0
    return 1 - sum(fps) / (n * m) + 1 / (2 * n)


def compute_apfdc(ordered_ids, labels, durations):
    """Compute APFDc on data with known labels and durations."""
    cum = 0.0
    total = 0.0
    cf = []
    nf = 0
    for tid in ordered_ids:
        dur = durations[tid]
        cum += dur
        total += dur
        if labels[tid]:
            cf.append(cum)
            nf += 1
    if nf == 0 or total == 0:
        return 1.0
    return 1 - sum(cf) / (total * nf) + 1 / (2 * nf)


def cross_validate_metrics(train_data, n_folds=5):
    """Estimate APFD/APFDc via k-fold cross-validation on training data."""
    fold_size = len(train_data) // n_folds
    apfd_scores = []
    apfdc_scores = []

    for fold in range(n_folds):
        val_start = fold * fold_size
        val_end = (fold + 1) * fold_size if fold < n_folds - 1 else len(train_data)
        train_fold = train_data[:val_start] + train_data[val_end:]
        val_fold = train_data[val_start:val_end]

        if not val_fold:
            continue

        # Extract features
        train_X = [extract_features(t["road_points"]) for t in train_fold]
        train_y = [1.0 if t["meta_data"]["test_info"]["test_outcome"] == "FAIL" else 0.0 for t in train_fold]
        val_X = [extract_features(t["road_points"]) for t in val_fold]

        nf = len(train_X[0])
        means = [sum(x[j] for x in train_X) / len(train_X) for j in range(nf)]
        stds = [max(1e-9, math.sqrt(sum((x[j]-means[j])**2 for x in train_X) / len(train_X))) for j in range(nf)]

        # Normalize
        Xn = [[(x[j]-means[j]) / stds[j] for j in range(nf)] for x in train_X]
        Vn = [[(x[j]-means[j]) / stds[j] for j in range(nf)] for x in val_X]

        # Train logistic regression
        w = [0.0] * nf
        b = 0.0
        lr = 0.01
        for ep in range(800):
            if ep == 400:
                lr = 0.005
            for i in range(len(Xn)):
                z = sum(w[j] * Xn[i][j] for j in range(nf)) + b
                p = sigmoid(z)
                e = p - train_y[i]
                for j in range(nf):
                    w[j] -= lr * e * Xn[i][j]
                b -= lr * e

        # Predict on validation
        probs = [sigmoid(sum(w[j] * x[j] for j in range(nf)) + b) for x in Vn]
        order = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)

        val_ids = [t["_id"]["$oid"] for t in val_fold]
        ordered_ids = [val_ids[i] for i in order]

        labels = {t["_id"]["$oid"]: t["meta_data"]["test_info"]["test_outcome"] == "FAIL" for t in val_fold}
        durations = {t["_id"]["$oid"]: t["meta_data"]["test_info"]["test_duration"] for t in val_fold}

        fail_count = sum(1 for v in labels.values() if v)
        if fail_count > 0:
            apfd = compute_apfd(ordered_ids, labels)
            apfdc = compute_apfdc(ordered_ids, labels, durations)
            apfd_scores.append(apfd)
            apfdc_scores.append(apfdc)

    mean_apfd = sum(apfd_scores) / len(apfd_scores) if apfd_scores else 0.5
    mean_apfdc = sum(apfdc_scores) / len(apfdc_scores) if apfdc_scores else 0.5
    return mean_apfd, mean_apfdc


def main():
    with open("/app/train_data.json") as f:
        train_data = json.load(f)
    with open("/app/test_data.json") as f:
        test_data = json.load(f)

    channel = grpc.insecure_channel("localhost:50051")
    stub = interface_pb2_grpc.CompetitionToolStub(channel)

    # Get tool name
    name_resp = stub.Name(interface_pb2.Empty(), timeout=10)
    tool_name = name_resp.name
    print("Tool: " + tool_name)

    # Initialize with training data
    def oracle_iter():
        for tc in train_data:
            oracle = interface_pb2.Oracle()
            oracle.testCase.testId = tc["_id"]["$oid"]
            for pt in tc["road_points"]:
                rp = oracle.testCase.roadPoints.add()
                rp.x = pt["x"]
                rp.y = pt["y"]
            oracle.hasFailed = (
                tc["meta_data"]["test_info"]["test_outcome"] == "FAIL"
            )
            yield oracle

    init_resp = stub.Initialize(oracle_iter(), timeout=120)
    print("Initialize: ok=" + str(init_resp.ok))

    # Prioritize test cases
    def test_iter():
        for tc in test_data:
            sdc = interface_pb2.SDCTestCase()
            sdc.testId = tc["_id"]["$oid"]
            for pt in tc["road_points"]:
                rp = sdc.roadPoints.add()
                rp.x = pt["x"]
                rp.y = pt["y"]
            yield sdc

    responses = list(stub.Prioritize(test_iter(), timeout=120))
    prioritized_order = [r.testId for r in responses]
    print("Prioritized " + str(len(prioritized_order)) + " test cases")

    # Estimate metrics via cross-validation on training data
    print("Computing cross-validation metrics...")
    cv_apfd, cv_apfdc = cross_validate_metrics(train_data)
    print(f"CV APFD: {cv_apfd:.4f}, CV APFDc: {cv_apfdc:.4f}")

    # Write results
    results = {
        "tool_name": tool_name,
        "train_size": len(train_data),
        "test_size": len(test_data),
        "prioritized_order": prioritized_order,
        "apfd": round(cv_apfd, 6),
        "apfdc": round(cv_apfdc, 6),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    channel.close()


if __name__ == "__main__":
    main()
