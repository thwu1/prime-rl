#!/usr/bin/env python3
"""
COCO-style mAP evaluator for YOLO-format object detection annotations.
All metric computations implemented from scratch.

"""

import argparse
import json
import os
import yaml
from collections import defaultdict


def parse_args():
    p = argparse.ArgumentParser(
        description="COCO-style mAP evaluator for YOLO annotations")
    p.add_argument("--ground-truth", required=True,
                    help="Directory with ground truth YOLO .txt files")
    p.add_argument("--predictions", required=True,
                    help="Directory with prediction YOLO .txt files (with confidence)")
    p.add_argument("--manifest", required=True,
                    help="JSON mapping image filenames to {width, height}")
    p.add_argument("--config", required=True,
                    help="YAML with nc and names")
    p.add_argument("--output", required=True,
                    help="Output JSON file path")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def yolo_to_xyxy(cx, cy, w, h, img_w, img_h):
    """YOLO normalised -> absolute [x1, y1, x2, y2] and area."""
    aw = w * img_w
    ah = h * img_h
    x1 = cx * img_w - aw / 2
    y1 = cy * img_h - ah / 2
    return [x1, y1, x1 + aw, y1 + ah], aw * ah


def iou(a, b):
    """IoU of two [x1, y1, x2, y2] boxes."""
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    ab = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = aa + ab - inter
    return inter / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# AP computation
# ---------------------------------------------------------------------------

def ap_101(precisions, recalls):
    """COCO 101-point interpolated AP with monotonic precision envelope."""
    if not precisions:
        return 0.0

    # sentinel values
    mr = [0.0] + list(recalls) + [1.0]
    mp = [0.0] + list(precisions) + [0.0]

    # monotonically decreasing precision (right-to-left max)
    for i in range(len(mp) - 2, -1, -1):
        mp[i] = max(mp[i], mp[i + 1])

    # evaluate at 101 recall thresholds
    ap = 0.0
    for t_100 in range(101):
        t = t_100 / 100.0
        p = 0.0
        for j in range(len(mr)):
            if mr[j] >= t:
                p = mp[j]
                break
        ap += p
    return ap / 101.0


# ---------------------------------------------------------------------------
# Per-image greedy matching
# ---------------------------------------------------------------------------

def evaluate_class_at_iou(gt_per_img, dt_per_img, cat_id, iou_thr,
                           area_rng=None):
    """
    Evaluate detections for one category at one IoU threshold.

    Returns
    -------
    results : list of (confidence, is_tp)
    n_gt    : total ground-truth count
    """
    all_imgs = set(gt_per_img) | set(dt_per_img)
    results = []
    n_gt = 0

    for img in all_imgs:
        gts = [g for g in gt_per_img.get(img, []) if g["cat"] == cat_id]
        dts = [d for d in dt_per_img.get(img, []) if d["cat"] == cat_id]

        if area_rng is not None:
            gts = [g for g in gts
                   if area_rng[0] <= g["area"] <= area_rng[1]]
            dts = [d for d in dts
                   if area_rng[0] <= d["area"] <= area_rng[1]]

        n_gt += len(gts)
        dts.sort(key=lambda x: -x["conf"])

        matched = set()
        for d in dts:
            best_iou = 0.0
            best_gi = -1
            for gi, g in enumerate(gts):
                if gi in matched:
                    continue
                v = iou(d["box"], g["box"])
                if v > best_iou:
                    best_iou = v
                    best_gi = gi
            if best_iou >= iou_thr and best_gi >= 0:
                matched.add(best_gi)
                results.append((d["conf"], True))
            else:
                results.append((d["conf"], False))

    return results, n_gt


def class_ap(results, n_gt):
    """AP from (conf, is_tp) list.  Returns -1 when n_gt == 0."""
    if n_gt == 0:
        return -1.0
    if not results:
        return 0.0

    results.sort(key=lambda x: -x[0])
    tp = fp = 0
    precs, recs = [], []
    for _, is_tp in results:
        if is_tp:
            tp += 1
        else:
            fp += 1
        precs.append(tp / (tp + fp))
        recs.append(tp / n_gt)
    return ap_101(precs, recs)


def optimal_f1(results, n_gt):
    """Find confidence threshold maximising F1 at IoU 0.5."""
    if n_gt == 0 or not results:
        return {"threshold": 0.0, "f1": 0.0, "precision": 0.0, "recall": 0.0}

    results.sort(key=lambda x: -x[0])
    best = {"threshold": 0.0, "f1": 0.0, "precision": 0.0, "recall": 0.0}
    tp = fp = 0
    for conf, is_tp in results:
        if is_tp:
            tp += 1
        else:
            fp += 1
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / n_gt
        f = 2.0 * p * r / (p + r) if (p + r) else 0.0
        if f > best["f1"]:
            best = {"threshold": round(conf, 4), "f1": round(f, 4),
                    "precision": round(p, 4), "recall": round(r, 4)}
    return best


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    nc = cfg["nc"]
    names = {i: cfg["names"][i] for i in range(nc)}

    with open(args.manifest) as f:
        manifest = json.load(f)

    # ---- parse files -------------------------------------------------------
    gt_per_img = defaultdict(list)
    dt_per_img = defaultdict(list)

    for fname, dims in manifest.items():
        w, h = dims["width"], dims["height"]
        stem = fname.rsplit(".", 1)[0]

        gt_path = os.path.join(args.ground_truth, stem + ".txt")
        if os.path.exists(gt_path):
            with open(gt_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    box, area = yolo_to_xyxy(float(parts[1]), float(parts[2]),
                                             float(parts[3]), float(parts[4]),
                                             w, h)
                    gt_per_img[fname].append(
                        {"cat": int(parts[0]), "box": box, "area": area})

        pred_path = os.path.join(args.predictions, stem + ".txt")
        if os.path.exists(pred_path):
            with open(pred_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    box, area = yolo_to_xyxy(float(parts[1]), float(parts[2]),
                                             float(parts[3]), float(parts[4]),
                                             w, h)
                    dt_per_img[fname].append(
                        {"cat": int(parts[0]), "box": box, "area": area,
                         "conf": float(parts[5])})

    # ---- IoU thresholds ----------------------------------------------------
    iou_thrs = [round(0.5 + 0.05 * i, 2) for i in range(10)]

    # ---- per-class metrics -------------------------------------------------
    per_class = {}
    for cid in range(nc):
        aps = {}
        for t in iou_thrs:
            res, ngt = evaluate_class_at_iou(gt_per_img, dt_per_img, cid, t)
            aps[t] = class_ap(res, ngt)

        res05, ngt05 = evaluate_class_at_iou(gt_per_img, dt_per_img, cid, 0.5)
        ndet = sum(1 for img in dt_per_img.values()
                   for d in img if d["cat"] == cid)

        valid = [v for v in aps.values() if v >= 0]
        ap_mean = (sum(valid) / len(valid)) if valid else 0.0

        per_class[names[cid]] = {
            "ap_0.5": round(max(0.0, aps.get(0.5, 0)), 4),
            "ap_0.75": round(max(0.0, aps.get(0.75, 0)), 4),
            "ap_0.5:0.95": round(ap_mean, 4) if ap_mean >= 0 else 0.0,
            "n_gt": ngt05,
            "n_det": ndet,
            "optimal_f1": optimal_f1(res05, ngt05),
        }

    # ---- aggregate mAP -----------------------------------------------------
    def mean_ap(key):
        vs = [d[key] for d in per_class.values() if d["n_gt"] > 0]
        return round(sum(vs) / len(vs), 4) if vs else 0.0

    # ---- per-size metrics --------------------------------------------------
    SIZE_BINS = {
        "small":  (0, 32 ** 2),        # 0 .. 1024
        "medium": (32 ** 2, 96 ** 2),   # 1024 .. 9216
        "large":  (96 ** 2, 1e10),      # 9216+
    }
    per_size = {}
    for sname, rng in SIZE_BINS.items():
        cat_aps = []
        ngt_total = 0
        for cid in range(nc):
            thresh_aps = []
            for t in iou_thrs:
                res, ngt = evaluate_class_at_iou(gt_per_img, dt_per_img,
                                                  cid, t, area_rng=rng)
                ap = class_ap(res, ngt)
                if ap >= 0:
                    thresh_aps.append(ap)
                if t == 0.5:
                    ngt_total += ngt
            if thresh_aps:
                cat_aps.append(sum(thresh_aps) / len(thresh_aps))
        per_size[sname] = {
            "ap_0.5:0.95": round(sum(cat_aps) / len(cat_aps), 4)
                           if cat_aps else 0.0,
            "n_gt": ngt_total,
        }

    # ---- output ------------------------------------------------------------
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

    print(f"mAP@0.5     = {output['mAP']['0.5']}")
    print(f"mAP@0.75    = {output['mAP']['0.75']}")
    print(f"mAP@0.5:0.95= {output['mAP']['0.5:0.95']}")
    print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
