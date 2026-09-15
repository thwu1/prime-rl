#!/usr/bin/env python3
"""Surgical action triplet evaluation metrics - full reimplementation."""

import numpy as np
import json
import os
import warnings
from sklearn.metrics import average_precision_score


# ==========================================================================
# Component decomposition
# ==========================================================================

def load_map_matrix(path='/app/map_matrix.csv'):
    return np.genfromtxt(path, delimiter=',', skip_header=1, dtype=int)


def decompose(inputs, map_matrix, component):
    """Extract component-level values from triplet-level via max-pooling."""
    txt2id = {'ivt': 0, 'i': 1, 'v': 2, 't': 3, 'iv': 4, 'it': 5, 'vt': 6}
    key = txt2id[component]
    col = map_matrix[:, key]
    index = sorted(np.unique(col))
    output = []
    for idx in index:
        same_class = [i for i, x in enumerate(col) if x == idx]
        y = np.max(np.array(inputs[same_class]))
        output.append(y)
    return output


def extract(inputs, map_matrix, component):
    """Extract component labels from a batch of triplet labels."""
    if component == 'ivt':
        return inputs
    return np.array([decompose(row, map_matrix, component) for row in inputs])


# ==========================================================================
# NaN resolution
# ==========================================================================

def resolve_nan(classwise):
    """Convert negative-zero AP values to NaN."""
    equiv_nan = ['-0', '-0.', '-0.0', '-.0']
    classwise = list(map(str, classwise))
    classwise = [np.nan if x in equiv_nan else x for x in classwise]
    classwise = np.array(list(map(float, classwise)))
    return classwise


# ==========================================================================
# Recognition metrics
# ==========================================================================

def compute_recognition_metrics(map_matrix):
    vid_dir = '/app/data/recognition'
    vid_files = sorted([f for f in os.listdir(vid_dir) if f.endswith('.npz')])

    videos = []
    for vf in vid_files:
        data = np.load(os.path.join(vid_dir, vf))
        videos.append((data['targets'], data['predictions']))

    results = {'video_ap': {}, 'global_ap': {}}

    # Video-wise AP for each component
    for comp in ['ivt', 'i', 'v', 't', 'iv', 'it']:
        video_log = []
        for targets, predictions in videos:
            t_comp = extract(targets, map_matrix, comp)
            p_comp = extract(predictions, map_matrix, comp)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                classwise = average_precision_score(
                    t_comp, p_comp, average=None)
                classwise = resolve_nan(classwise)
            video_log.append(classwise.reshape(1, -1))

        video_log = np.concatenate(video_log, axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            videowise = np.nanmean(video_log, axis=0)
            mAP = float(np.nanmean(videowise))

        results['video_ap'][comp] = mAP

        if comp == 'ivt':
            results['video_ap']['ivt_per_class'] = [
                None if np.isnan(x) else float(x) for x in videowise
            ]

    # Global AP for ivt
    all_targets = np.concatenate([t for t, p in videos], axis=0)
    all_preds = np.concatenate([p for t, p in videos], axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        classwise = average_precision_score(
            all_targets, all_preds, average=None)
        classwise = resolve_nan(classwise)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        results['global_ap']['ivt'] = float(np.nanmean(classwise))

    return results


# ==========================================================================
# Detection helpers
# ==========================================================================

def xywh2xyxy(bb):
    """Convert xywh to xyxy IN-PLACE (replicates reference behavior)."""
    bb[2] += bb[0]
    bb[3] += bb[1]
    return bb


def compute_iou(bb1, bb2):
    """Compute IoU between two bounding boxes."""
    bb1 = xywh2xyxy(bb1)
    bb2 = xywh2xyxy(bb2)
    x1 = bb1[2] - bb1[0]
    y1 = bb1[3] - bb1[1]
    if x1 < 0:
        x1 = 0
    if y1 < 0:
        y1 = 0
    x2 = bb2[2] - bb2[0]
    y2 = bb2[3] - bb2[1]
    if x2 < 0:
        x2 = 0
    if y2 < 0:
        y2 = 0
    xiou = min(bb1[2], bb2[2]) - max(bb1[0], bb2[0])
    yiou = min(bb1[3], bb2[3]) - max(bb1[1], bb2[1])
    if xiou < 0:
        xiou = 0
    if yiou < 0:
        yiou = 0
    if xiou * yiou <= 0:
        return 0
    else:
        return xiou * yiou / (x1 * y1 + x2 * y2 - xiou * yiou)


def list2stack(x):
    """Convert list-of-lists to sorted numpy array."""
    if x == []:
        x = [[]]
    assert isinstance(x[0], list), \
        "Each frame must be a list of lists"
    if len(x[0]):
        x = np.stack(x, axis=0)
        x = x[x[:, 2].argsort()[::-1]]
    return x


def is_match(det_gt, det_pd, threshold):
    if det_gt[0] == det_pd[0]:
        if compute_iou(det_gt[-4:], det_pd[-4:]) >= threshold:
            return True
    return False


def is_partial_match(det_gt, det_pd):
    if det_gt[0] == det_pd[0]:
        if compute_iou(det_gt[-4:], det_pd[-4:]) > 0.0:
            return True
    return False


def is_id_switch(det_gt, det_pd, det_gts, threshold):
    if compute_iou(det_gt[-4:], det_pd[-4:]) > threshold:
        gt_ids = list(det_gts[:, 0])
        if det_pd[0] in gt_ids:
            return np.where(gt_ids == det_pd[0])[0][0]
    return False


def is_id_miss(det_gt, det_pd, threshold):
    if compute_iou(det_gt[-4:], det_pd[-4:]) > threshold:
        return True
    return False


def is_miss_loc(det_gt, det_pd, det_gts):
    gt_ids = list(det_gts[:, 0])
    if det_pd[0] in gt_ids:
        return np.where(gt_ids == det_pd[0])[0][0]
    return False


def separate_detection(det_gts, det_pds):
    pos_ids = list(det_gts[:, 0])
    matching = [list(x) for x in det_pds if x[0] in pos_ids]
    unmatching = [list(x) for x in det_pds if x[0] not in pos_ids]
    return matching, unmatching


# ==========================================================================
# Association analysis
# ==========================================================================

def process_association(gt_input, pd_input, threshold):
    """Per-frame association cascade."""
    detection_gt = gt_input.copy()
    detection_pd = pd_input.copy()

    counts = {k: 0 for k in ['fp', 'fn', 'lm', 'plm', 'ids', 'idm', 'mil']}

    if len(detection_gt[0]) == 0:
        counts['fp'] += len([x for x in detection_pd if len(x)])
        return counts
    elif len(detection_pd[0]) == 0:
        counts['fn'] += len([x for x in detection_gt if len(x)])
        return counts

    matched_dets, unmatched_dets = separate_detection(
        detection_gt, detection_pd)

    # Stage 1: LM - localized and matched
    leftover = []
    if len(matched_dets):
        for det_pd in matched_dets:
            f = det_pd[0:]
            matched = False
            for k, det_gt in enumerate(detection_gt):
                y = det_gt[0:]
                if is_match(y, f, threshold):
                    detection_gt = np.delete(detection_gt, obj=k, axis=0)
                    matched = True
                    break
            if matched:
                counts['lm'] += 1
            else:
                leftover.append(det_pd)
    matched_dets = leftover.copy()

    # Stage 2: pLM - partially localized and matched
    leftover = []
    if len(matched_dets):
        for det_pd in matched_dets:
            f = det_pd[0:]
            matched = False
            for k, det_gt in enumerate(detection_gt):
                y = det_gt[0:]
                if is_partial_match(y, f):
                    detection_gt = np.delete(detection_gt, obj=k, axis=0)
                    matched = True
                    break
            if matched:
                counts['plm'] += 1
            else:
                leftover.append(det_pd)
    matched_dets = leftover.copy()

    # Stage 3: IDS - identity switch
    leftover = []
    if len(matched_dets):
        for det_pd in matched_dets:
            f = det_pd[0:]
            matched = False
            for k, det_gt in enumerate(detection_gt):
                y = det_gt[0:]
                ids_idx = is_id_switch(y, f, detection_gt, threshold)
                if ids_idx:
                    detection_gt = np.delete(
                        detection_gt, obj=ids_idx, axis=0)
                    matched = True
                    break
            if matched:
                counts['ids'] += 1
            else:
                leftover.append(det_pd)
    matched_dets = leftover.copy()

    # Stage 4: IDM - identity miss
    combined = unmatched_dets + matched_dets
    leftover = []
    if len(matched_dets):
        for det_pd in combined:
            f = det_pd[0:]
            matched = False
            for k, det_gt in enumerate(detection_gt):
                y = det_gt[0:]
                if is_id_miss(y, f, threshold):
                    matched = True
                    break
            if matched:
                counts['idm'] += 1
            else:
                leftover.append(det_pd)
    matched_dets = leftover.copy()

    # Stage 5: MIL - missed localization
    leftover = []
    if len(matched_dets):
        for det_pd in matched_dets:
            f = det_pd[0:]
            matched = False
            for k, det_gt in enumerate(detection_gt):
                y = det_gt[0:]
                mil_idx = is_miss_loc(y, f, detection_gt)
                if mil_idx:
                    detection_gt = np.delete(
                        detection_gt, obj=mil_idx, axis=0)
                    matched = True
                    break
            if matched:
                counts['mil'] += 1
            else:
                leftover.append(det_pd)
    matched_dets = leftover.copy()

    # Remaining
    counts['fp'] += len([x for x in matched_dets if len(x)])
    counts['fn'] += len([x for x in detection_gt if len(x)])

    return counts


# ==========================================================================
# Detection AP computation
# ==========================================================================

def compute_11pt_ap(accumulator, component, num_class, num_tool):
    """Compute 11-point interpolated AP, Recall, Precision."""
    if component == 'ivt':
        hit_str, pos_str, det_str = 'hits', 'npos', 'ndet'
        nc = num_class
    else:
        hit_str, pos_str, det_str = 'hits_i', 'npos_i', 'ndet_i'
        nc = num_tool

    classwise_ap = []
    classwise_rec = []
    classwise_prec = []

    for hits, npos, ndet in zip(
            accumulator[hit_str], accumulator[pos_str],
            accumulator[det_str]):
        if npos + ndet == 0:
            classwise_ap.append(np.nan)
            classwise_rec.append(np.nan)
            classwise_prec.append(np.nan)
        elif npos > 0 and len(hits) == 0:
            classwise_ap.append(0.0)
            classwise_rec.append(0.0)
            classwise_prec.append(0.0)
        else:
            hits_cum = np.cumsum(hits)
            ap = 0.0
            rec = hits_cum / npos if npos else 0.0
            prec = hits_cum / (
                np.array(range(len(hits_cum)), dtype=float) + 1.0)
            for i in range(11):
                mask = rec >= (i / 10.0)
                if np.sum(mask) > 0:
                    ap += np.max(prec[mask]) / 11.0
            classwise_ap.append(ap)
            classwise_rec.append(np.max(rec))
            classwise_prec.append(np.max(prec))

    return classwise_ap, classwise_rec, classwise_prec


def eval_association(accumulator):
    """Evaluate association metrics for a video."""
    fp = accumulator['fp']
    fn = accumulator['fn']
    lm = accumulator['lm']
    plm = accumulator['plm']
    ids = accumulator['ids']
    idm = accumulator['idm']
    mil = accumulator['mil']
    total = fp + fn + lm + plm + ids + idm + mil
    if total == 0:
        return [np.nan] * 7
    return (lm / total, plm / total, ids / total, idm / total,
            mil / total, fp / total, fn / total)


def compute_detection_metrics(map_matrix):
    """Compute detection metrics for all videos."""
    num_class = 100
    num_tool = 6
    threshold = 0.5

    vid_dir = '/app/data/detection'
    vid_files = sorted([f for f in os.listdir(vid_dir)
                        if f.endswith('.json')])

    accumulators = {}

    for vid_idx, vf in enumerate(vid_files):
        video_id = vid_idx + 1
        accumulators[video_id] = {
            'hits': [[] for _ in range(num_class)],
            'ndet': [0 for _ in range(num_class)],
            'npos': [0 for _ in range(num_class)],
            'hits_i': [[] for _ in range(num_tool)],
            'ndet_i': [0 for _ in range(num_tool)],
            'npos_i': [0 for _ in range(num_tool)],
            'fp': 0, 'fn': 0, 'lm': 0, 'plm': 0,
            'ids': 0, 'idm': 0, 'mil': 0,
        }

        with open(os.path.join(vid_dir, vf)) as f:
            video_data = json.load(f)

        for frame in video_data:
            detection_gt = list2stack(frame['gt'])
            detection_pd = list2stack(frame['pred'])

            if len(detection_pd[0]) + len(detection_gt[0]) == 0:
                continue

            # --- Triplet-level matching ---
            detection_gt_ivt = detection_gt.copy()
            detection_pd_ivt = detection_pd.copy()

            for gt in detection_gt_ivt:
                if len(gt):
                    accumulators[video_id]['npos'][int(gt[0])] += 1

            for det_pd in detection_pd_ivt:
                if len(det_pd):
                    accumulators[video_id]['ndet'][int(det_pd[0])] += 1
                    matched = False
                    for k, det_gt in enumerate(detection_gt_ivt):
                        if len(det_gt):
                            y = det_gt[0:]
                            f = det_pd[0:]
                            if is_match(y, f, threshold):
                                detection_gt_ivt = np.delete(
                                    detection_gt_ivt, obj=k, axis=0)
                                matched = True
                                break
                    if matched:
                        accumulators[video_id]['hits'][
                            int(det_pd[0])].append(1.0)
                    else:
                        accumulators[video_id]['hits'][
                            int(det_pd[0])].append(0.0)

            # --- Instrument-level matching ---
            detection_gt_i = detection_gt.copy()
            detection_pd_i = detection_pd.copy()

            for gt in detection_gt_i:
                if len(gt):
                    accumulators[video_id]['npos_i'][int(gt[1])] += 1

            for det_pd in detection_pd_i:
                if len(det_pd):
                    accumulators[video_id]['ndet_i'][int(det_pd[1])] += 1
                    matched = False
                    for k, det_gt in enumerate(detection_gt_i):
                        if len(det_gt):
                            y = det_gt[1:]
                            f = det_pd[1:]
                            if is_match(y, f, threshold):
                                detection_gt_i = np.delete(
                                    detection_gt_i, obj=k, axis=0)
                                matched = True
                                break
                    if matched:
                        accumulators[video_id]['hits_i'][
                            int(det_pd[1])].append(1.0)
                    else:
                        accumulators[video_id]['hits_i'][
                            int(det_pd[1])].append(0.0)

            # --- Association analysis ---
            assoc = process_association(
                detection_gt.copy(), detection_pd.copy(), threshold)
            for key in ['fp', 'fn', 'lm', 'plm', 'ids', 'idm', 'mil']:
                accumulators[video_id][key] += assoc[key]

    # --- Video-wise aggregation ---
    results = {'video_ap': {}, 'association': {}}

    def to_json(v):
        if isinstance(v, float) and np.isnan(v):
            return None
        return None if (hasattr(v, '__float__') and np.isnan(float(v))) \
            else float(v)

    for comp in ['ivt', 'i']:
        all_ap, all_rec, all_prec = [], [], []
        all_lm, all_plm, all_ids = [], [], []
        all_idm, all_mil, all_fp, all_fn = [], [], [], []

        for vid_id in range(1, len(vid_files) + 1):
            ap, rec, prec = compute_11pt_ap(
                accumulators[vid_id], comp, num_class, num_tool)
            all_ap.append(ap)
            all_rec.append(rec)
            all_prec.append(prec)

            asc = eval_association(accumulators[vid_id])
            all_lm.append(asc[0])
            all_plm.append(asc[1])
            all_ids.append(asc[2])
            all_idm.append(asc[3])
            all_mil.append(asc[4])
            all_fp.append(asc[5])
            all_fn.append(asc[6])

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            cw_ap = np.nanmean(np.stack(all_ap, axis=0), axis=0)
            cw_rec = np.nanmean(np.stack(all_rec, axis=0), axis=0)
            cw_prec = np.nanmean(np.stack(all_prec, axis=0), axis=0)
            mAP = np.nanmean(cw_ap)
            mRec = np.nanmean(cw_rec)
            mPre = np.nanmean(cw_prec)

        results['video_ap'][comp] = {
            'mAP': to_json(mAP),
            'mRec': to_json(mRec),
            'mPre': to_json(mPre),
        }

        if comp == 'ivt':
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                results['association'] = {
                    'lm': to_json(np.nanmean(all_lm)),
                    'plm': to_json(np.nanmean(all_plm)),
                    'ids': to_json(np.nanmean(all_ids)),
                    'idm': to_json(np.nanmean(all_idm)),
                    'mil': to_json(np.nanmean(all_mil)),
                    'fp': to_json(np.nanmean(all_fp)),
                    'fn': to_json(np.nanmean(all_fn)),
                }

    return results


# ==========================================================================
# Main
# ==========================================================================

def main():
    map_matrix = load_map_matrix()
    rec_results = compute_recognition_metrics(map_matrix)
    det_results = compute_detection_metrics(map_matrix)

    output = {
        'recognition': rec_results,
        'detection': det_results,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
