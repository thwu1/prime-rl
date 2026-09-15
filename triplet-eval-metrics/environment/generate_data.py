#!/usr/bin/env python3
"""Generate deterministic synthetic evaluation data for surgical triplet metrics."""
import numpy as np
import json
import os


def generate_data():
    rng = np.random.RandomState(42)
    os.makedirs('/app/data/recognition', exist_ok=True)
    os.makedirs('/app/data/detection', exist_ok=True)

    # Load mapping matrix
    map_matrix = np.genfromtxt('/app/map_matrix.csv', delimiter=',',
                               skip_header=1, dtype=int)

    # Select active triplet classes (40 of 100)
    active_classes = sorted(rng.choice(100, 40, replace=False).tolist())

    # === Recognition data: 4 videos ===
    frames_per_video = [60, 45, 80, 55]
    num_classes = 100

    for vid in range(4):
        nf = frames_per_video[vid]
        targets = np.zeros((nf, num_classes), dtype=int)
        predictions = np.zeros((nf, num_classes), dtype=float)

        for f in range(nf):
            n_active = rng.randint(1, 6)
            chosen = rng.choice(active_classes,
                                min(n_active, len(active_classes)),
                                replace=False)
            targets[f, chosen] = 1
            predictions[f] = rng.uniform(0, 0.1, num_classes)
            for c in chosen:
                predictions[f, c] = rng.uniform(0.3, 1.0)
            n_fp = rng.randint(0, 4)
            fp_classes = rng.choice(num_classes, n_fp, replace=False)
            for c in fp_classes:
                predictions[f, c] = max(predictions[f, c],
                                        rng.uniform(0.2, 0.8))

        np.savez(f'/app/data/recognition/video_{vid}.npz',
                 targets=targets, predictions=predictions)

    # === Detection data: 3 videos ===
    frames_per_det = [30, 25, 35]
    det_active = active_classes[:30]

    for vid in range(3):
        nf = frames_per_det[vid]
        video_data = []

        for f in range(nf):
            n_gt = rng.randint(1, 5)
            gt = []
            for _ in range(n_gt):
                tid = int(rng.choice(det_active))
                tool_id = int(map_matrix[tid, 1])
                x = round(float(rng.uniform(0.1, 0.6)), 4)
                y = round(float(rng.uniform(0.1, 0.6)), 4)
                w = round(float(rng.uniform(0.1, 0.3)), 4)
                h = round(float(rng.uniform(0.1, 0.3)), 4)
                gt.append([tid, tool_id, 1.0, x, y, w, h])

            n_pred = rng.randint(0, 7)
            pred = []
            for j in range(n_pred):
                if j < len(gt) and rng.random() > 0.3:
                    base = gt[j]
                    tid = base[0]
                    tool_id = base[1]
                    conf = round(float(rng.uniform(0.3, 1.0)), 4)
                    dx = rng.uniform(-0.05, 0.05)
                    dy = rng.uniform(-0.05, 0.05)
                    dw = rng.uniform(-0.05, 0.05)
                    dh = rng.uniform(-0.05, 0.05)
                    x = round(float(max(0, base[3] + dx)), 4)
                    y = round(float(max(0, base[4] + dy)), 4)
                    w = round(float(max(0.01, base[5] + dw)), 4)
                    h = round(float(max(0.01, base[6] + dh)), 4)
                else:
                    tid = int(rng.choice(det_active))
                    tool_id = int(map_matrix[tid, 1])
                    conf = round(float(rng.uniform(0.1, 0.9)), 4)
                    x = round(float(rng.uniform(0.1, 0.6)), 4)
                    y = round(float(rng.uniform(0.1, 0.6)), 4)
                    w = round(float(rng.uniform(0.1, 0.3)), 4)
                    h = round(float(rng.uniform(0.1, 0.3)), 4)
                pred.append([tid, tool_id, conf, x, y, w, h])

            video_data.append({"gt": gt, "pred": pred})

        with open(f'/app/data/detection/video_{vid}.json', 'w') as fout:
            json.dump(video_data, fout)


if __name__ == '__main__':
    generate_data()
    print("Data generated successfully.")
