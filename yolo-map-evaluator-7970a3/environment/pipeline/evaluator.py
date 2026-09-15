#!/usr/bin/env python3
"""Detection evaluation tool for YOLO-format annotations.

Computes per-class and aggregate detection metrics from YOLO-format
ground truth and prediction annotation files.

"""

import argparse
import json
import os
import yaml
from collections import defaultdict


def parse_args():
    p = argparse.ArgumentParser(description="Evaluate detection metrics")
    p.add_argument("--ground-truth", required=True)
    p.add_argument("--predictions", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", required=True)
    return p.parse_args()


def yolo_to_abs(cx, cy, w, h, img_w, img_h):
    """Convert YOLO normalized coords to absolute xyxy + area."""
    aw = w * img_w
    ah = h * img_h
    x1 = cx * img_w - aw / 2.0
    y1 = cy * img_h - ah / 2.0
    return [x1, y1, x1 + aw, y1 + ah], w * h


def compute_iou(a, b):
    """IoU between two [x1,y1,x2,y2] boxes."""
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def compute_ap(precisions, recalls):
    """Compute AP using interpolated P-R curve."""
    if not precisions:
        return 0.0
    mrec = [0.0] + list(recalls) + [1.0]
    mprec = [0.0] + list(precisions) + [0.0]
    for i in range(len(mprec) - 2, -1, -1):
        mprec[i] = max(mprec[i], mprec[i + 1])
    ap = 0.0
    for k in range(11):
        t = k / 10.0
        p_at_t = 0.0
        for j in range(len(mrec)):
            if mrec[j] >= t:
                p_at_t = mprec[j]
                break
        ap += p_at_t
    return ap / 11.0


def match_at_iou(gts, dts, threshold):
    """Match detections to ground truth at given IoU threshold."""
    results = []
    matched = set()
    for d in dts:
        best_iou = 0.0
        best_idx = -1
        for gi, g in enumerate(gts):
            if gi in matched:
                continue
            v = compute_iou(d["box"], g["box"])
            if v > best_iou:
                best_iou = v
                best_idx = gi
        if best_iou >= threshold and best_idx >= 0:
            matched.add(best_idx)
            results.append((d["conf"], True))
        else:
            results.append((d["conf"], False))
    return results


def main():
    args = parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    nc = cfg["nc"]
    names = {i: cfg["names"][i] for i in range(nc)}

    with open(args.manifest) as f:
        manifest = json.load(f)

    gt_per_img = defaultdict(list)
    dt_per_img = defaultdict(list)

    for fname, dims in manifest.items():
        iw, ih = dims["width"], dims["height"]
        stem = fname.rsplit(".", 1)[0]

        gt_path = os.path.join(args.ground_truth, stem + ".txt")
        if os.path.exists(gt_path):
            with open(gt_path) as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    if len(parts) < 5:
                        continue
                    box, area = yolo_to_abs(
                        float(parts[1]), float(parts[2]),
                        float(parts[3]), float(parts[4]), iw, ih)
                    gt_per_img[fname].append({
                        "cat": int(parts[0]), "box": box, "area": area
                    })

        pred_path = os.path.join(args.predictions, stem + ".txt")
        if os.path.exists(pred_path):
            with open(pred_path) as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    if len(parts) < 6:
                        continue
                    box, area = yolo_to_abs(
                        float(parts[1]), float(parts[2]),
                        float(parts[3]), float(parts[4]), iw, ih)
                    dt_per_img[fname].append({
                        "cat": int(parts[0]), "box": box, "area": area,
                        "conf": float(parts[5])
                    })

    iou_thresholds = [round(0.5 + 0.05 * i, 2) for i in range(10)]

    per_class = {}
    for cid in range(nc):
        aps = {}
        for t in iou_thresholds:
            all_results = []
            n_gt = 0
            for img in set(gt_per_img) | set(dt_per_img):
                gts_c = [g for g in gt_per_img.get(img, [])
                         if g["cat"] == cid]
                dts_c = [d for d in dt_per_img.get(img, [])
                         if d["cat"] == cid]
                n_gt += len(gts_c)
                all_results.extend(match_at_iou(gts_c, dts_c, t))

            if n_gt == 0:
                aps[t] = 0.0
                continue

            all_results.sort(key=lambda x: -x[0])
            tp = fp = 0
            precs, recs = [], []
            for _, is_tp in all_results:
                if is_tp:
                    tp += 1
                else:
                    fp += 1
                precs.append(tp / (tp + fp))
                recs.append(tp / n_gt)
            aps[t] = compute_ap(precs, recs)

        res05 = []
        n_gt_05 = 0
        for img in set(gt_per_img) | set(dt_per_img):
            gts_c = [g for g in gt_per_img.get(img, []) if g["cat"] == cid]
            dts_c = [d for d in dt_per_img.get(img, []) if d["cat"] == cid]
            n_gt_05 += len(gts_c)
            res05.extend(match_at_iou(gts_c, dts_c, 0.5))

        ndet = sum(1 for img in dt_per_img.values()
                   for d in img if d["cat"] == cid)

        ap_vals = list(aps.values())
        ap_mean = sum(ap_vals) / len(ap_vals) if ap_vals else 0.0

        opt_f1 = {"threshold": 0.0, "f1": 0.0, "precision": 0.0,
                  "recall": 0.0}
        if n_gt_05 > 0 and res05:
            res05.sort(key=lambda x: -x[0])
            tp = fp = 0
            for conf, is_tp in res05:
                if is_tp:
                    tp += 1
                else:
                    fp += 1
                p = tp / (tp + fp) if (tp + fp) else 0
                r = tp / n_gt_05
                f = 2 * p * r / (p + r) if (p + r) else 0
                if f > opt_f1["f1"]:
                    opt_f1 = {
                        "threshold": round(conf, 4),
                        "f1": round(f, 4),
                        "precision": round(p, 4),
                        "recall": round(r, 4),
                    }

        per_class[names[cid]] = {
            "ap_0.5": round(aps.get(0.5, 0), 4),
            "ap_0.75": round(aps.get(0.75, 0), 4),
            "ap_0.5:0.95": round(ap_mean, 4),
            "n_gt": n_gt_05,
            "n_det": ndet,
            "optimal_f1": opt_f1,
        }

    def mean_ap(key):
        vs = [d[key] for d in per_class.values()]
        return round(sum(vs) / len(vs), 4) if vs else 0.0

    SIZE_BINS = {
        "small": (0, 32 ** 2),
        "medium": (32 ** 2, 96 ** 2),
        "large": (96 ** 2, 1e10),
    }
    per_size = {}
    for sname, rng in SIZE_BINS.items():
        cat_aps = []
        ngt_total = 0
        for cid in range(nc):
            thresh_aps = []
            for t in iou_thresholds:
                all_results = []
                n_gt = 0
                for img in set(gt_per_img) | set(dt_per_img):
                    gts_c = [g for g in gt_per_img.get(img, [])
                             if g["cat"] == cid
                             and rng[0] <= g["area"] <= rng[1]]
                    dts_c = [d for d in dt_per_img.get(img, [])
                             if d["cat"] == cid
                             and rng[0] <= d["area"] <= rng[1]]
                    n_gt += len(gts_c)
                    all_results.extend(match_at_iou(gts_c, dts_c, t))
                if n_gt == 0:
                    continue
                all_results.sort(key=lambda x: -x[0])
                tp = fp = 0
                precs, recs = [], []
                for _, is_tp in all_results:
                    if is_tp:
                        tp += 1
                    else:
                        fp += 1
                    precs.append(tp / (tp + fp))
                    recs.append(tp / n_gt)
                thresh_aps.append(compute_ap(precs, recs))
                if t == 0.5:
                    ngt_total += n_gt
            if thresh_aps:
                cat_aps.append(sum(thresh_aps) / len(thresh_aps))
        per_size[sname] = {
            "ap_0.5:0.95": round(sum(cat_aps) / len(cat_aps), 4)
                           if cat_aps else 0.0,
            "n_gt": ngt_total,
        }

    output = {
        "mAP": {
            "0.5": mean_ap("ap_0.5"),
            "0.75": mean_ap("ap_0.75"),
            "0.5:0.95": mean_ap("ap_0.5:0.95"),
        },
        "per_class": per_class,
        "per_size": per_size,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Evaluation complete. Results: {args.output}")


if __name__ == "__main__":
    main()
