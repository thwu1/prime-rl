#!/usr/bin/env python3
"""Generate synthetic NIfTI data for ISLES-style evaluation benchmark."""
import numpy as np
import nibabel as nib
import os

SHAPE = (40, 40, 20)
TEAMS = ['alpha', 'beta', 'gamma', 'delta']

VOXEL_DIMS = {
    1: (1.0, 1.0, 1.0),
    2: (1.0, 1.0, 2.0),
    3: (0.5, 0.5, 1.0),
    4: (2.0, 2.0, 2.0),
    5: (1.0, 1.0, 1.0),
    6: (1.5, 1.5, 3.0),
    7: (1.0, 1.0, 1.0),
    8: (2.0, 2.0, 1.0),
}

def save_nifti(data, voxdims, filepath):
    affine = np.diag(list(voxdims) + [1.0])
    img = nib.Nifti1Image(data.astype(np.float32), affine)
    nib.save(img, filepath)

def make_gt():
    gts = {}
    # Case 1: Single medium lesion
    g = np.zeros(SHAPE, dtype=np.float32)
    g[10:20, 10:20, 5:15] = 1.0
    gts[1] = g
    # Case 2: Two separated lesions
    g = np.zeros(SHAPE, dtype=np.float32)
    g[3:8, 3:8, 2:7] = 1.0
    g[25:33, 25:33, 12:18] = 1.0
    gts[2] = g
    # Case 3: Empty
    gts[3] = np.zeros(SHAPE, dtype=np.float32)
    # Case 4: Large lesion
    g = np.zeros(SHAPE, dtype=np.float32)
    g[5:35, 5:35, 3:17] = 1.0
    gts[4] = g
    # Case 5: Three small lesions
    g = np.zeros(SHAPE, dtype=np.float32)
    g[2:5, 2:5, 2:5] = 1.0
    g[18:21, 18:21, 8:11] = 1.0
    g[33:37, 33:37, 14:18] = 1.0
    gts[5] = g
    # Case 6: L-shaped lesion (one connected component)
    g = np.zeros(SHAPE, dtype=np.float32)
    g[10:20, 10:15, 5:10] = 1.0
    g[10:15, 15:25, 5:10] = 1.0
    gts[6] = g
    # Case 7: Single small lesion
    g = np.zeros(SHAPE, dtype=np.float32)
    g[20:23, 20:23, 10:13] = 1.0
    gts[7] = g
    # Case 8: Two lesions close but not touching
    g = np.zeros(SHAPE, dtype=np.float32)
    g[5:10, 5:10, 5:10] = 1.0
    g[12:17, 12:17, 5:10] = 1.0
    gts[8] = g
    return gts

def make_alpha():
    p = {}
    # Case 1: Exact match
    m = np.zeros(SHAPE, dtype=np.float32)
    m[10:20, 10:20, 5:15] = 1.0
    p[1] = m
    # Case 2: Exact match
    m = np.zeros(SHAPE, dtype=np.float32)
    m[3:8, 3:8, 2:7] = 1.0
    m[25:33, 25:33, 12:18] = 1.0
    p[2] = m
    # Case 3: Correctly empty
    p[3] = np.zeros(SHAPE, dtype=np.float32)
    # Case 4: Slight oversegmentation (one extra z-slice)
    m = np.zeros(SHAPE, dtype=np.float32)
    m[5:35, 5:35, 3:18] = 1.0
    p[4] = m
    # Case 5: All three exact
    m = np.zeros(SHAPE, dtype=np.float32)
    m[2:5, 2:5, 2:5] = 1.0
    m[18:21, 18:21, 8:11] = 1.0
    m[33:37, 33:37, 14:18] = 1.0
    p[5] = m
    # Case 6: Exact match
    m = np.zeros(SHAPE, dtype=np.float32)
    m[10:20, 10:15, 5:10] = 1.0
    m[10:15, 15:25, 5:10] = 1.0
    p[6] = m
    # Case 7: Exact match
    m = np.zeros(SHAPE, dtype=np.float32)
    m[20:23, 20:23, 10:13] = 1.0
    p[7] = m
    # Case 8: Slight overseg on first lesion
    m = np.zeros(SHAPE, dtype=np.float32)
    m[5:11, 5:11, 5:10] = 1.0
    m[12:17, 12:17, 5:10] = 1.0
    p[8] = m
    return p

def make_beta():
    p = {}
    # Case 1: Undersegmented
    m = np.zeros(SHAPE, dtype=np.float32)
    m[11:19, 11:19, 6:14] = 1.0
    p[1] = m
    # Case 2: Only finds larger lesion B
    m = np.zeros(SHAPE, dtype=np.float32)
    m[25:33, 25:33, 12:18] = 1.0
    p[2] = m
    # Case 3: Correctly empty
    p[3] = np.zeros(SHAPE, dtype=np.float32)
    # Case 4: Exact match
    m = np.zeros(SHAPE, dtype=np.float32)
    m[5:35, 5:35, 3:17] = 1.0
    p[4] = m
    # Case 5: Misses smallest lesion A, finds B and C
    m = np.zeros(SHAPE, dtype=np.float32)
    m[18:21, 18:21, 8:11] = 1.0
    m[33:37, 33:37, 14:18] = 1.0
    p[5] = m
    # Case 6: Exact match
    m = np.zeros(SHAPE, dtype=np.float32)
    m[10:20, 10:15, 5:10] = 1.0
    m[10:15, 15:25, 5:10] = 1.0
    p[6] = m
    # Case 7: Slightly oversegmented in z
    m = np.zeros(SHAPE, dtype=np.float32)
    m[20:23, 20:23, 9:14] = 1.0
    p[7] = m
    # Case 8: Undersegmented on both
    m = np.zeros(SHAPE, dtype=np.float32)
    m[6:10, 6:10, 6:10] = 1.0
    m[13:17, 13:17, 6:10] = 1.0
    p[8] = m
    return p

def make_gamma():
    p = {}
    # Case 1: Shifted prediction
    m = np.zeros(SHAPE, dtype=np.float32)
    m[15:25, 15:25, 8:18] = 1.0
    p[1] = m
    # Case 2: Finds both but very oversegmented
    m = np.zeros(SHAPE, dtype=np.float32)
    m[1:10, 1:10, 0:9] = 1.0
    m[23:35, 23:35, 10:20] = 1.0
    p[2] = m
    # Case 3: False positive
    m = np.zeros(SHAPE, dtype=np.float32)
    m[15:18, 15:18, 8:11] = 1.0
    p[3] = m
    # Case 4: Moderate overlap
    m = np.zeros(SHAPE, dtype=np.float32)
    m[10:38, 10:38, 5:19] = 1.0
    p[4] = m
    # Case 5: Only finds lesion C
    m = np.zeros(SHAPE, dtype=np.float32)
    m[33:37, 33:37, 14:18] = 1.0
    p[5] = m
    # Case 6: Only vertical bar
    m = np.zeros(SHAPE, dtype=np.float32)
    m[10:20, 10:15, 5:10] = 1.0
    p[6] = m
    # Case 7: Predicts nothing (miss)
    p[7] = np.zeros(SHAPE, dtype=np.float32)
    # Case 8: Merges both into one blob
    m = np.zeros(SHAPE, dtype=np.float32)
    m[5:17, 5:17, 5:10] = 1.0
    p[8] = m
    return p

def make_delta():
    p = {}
    # Case 1: Very oversegmented
    m = np.zeros(SHAPE, dtype=np.float32)
    m[5:30, 5:30, 2:18] = 1.0
    p[1] = m
    # Case 2: Predicts nothing
    p[2] = np.zeros(SHAPE, dtype=np.float32)
    # Case 3: Large false positive
    m = np.zeros(SHAPE, dtype=np.float32)
    m[0:20, 0:20, 0:10] = 1.0
    p[3] = m
    # Case 4: Very undersegmented
    m = np.zeros(SHAPE, dtype=np.float32)
    m[15:25, 15:25, 8:12] = 1.0
    p[4] = m
    # Case 5: Wrong location entirely
    m = np.zeros(SHAPE, dtype=np.float32)
    m[10:14, 10:14, 5:9] = 1.0
    p[5] = m
    # Case 6: Predicts nothing
    p[6] = np.zeros(SHAPE, dtype=np.float32)
    # Case 7: Very oversegmented
    m = np.zeros(SHAPE, dtype=np.float32)
    m[15:30, 15:30, 5:18] = 1.0
    p[7] = m
    # Case 8: Finds one lesion, adds false positive
    m = np.zeros(SHAPE, dtype=np.float32)
    m[5:10, 5:10, 5:10] = 1.0
    m[30:34, 30:34, 15:19] = 1.0
    p[8] = m
    return p

def main():
    base = '/app/data'
    gt_dir = os.path.join(base, 'ground_truth')
    os.makedirs(gt_dir, exist_ok=True)
    for team in TEAMS:
        os.makedirs(os.path.join(base, 'predictions', team), exist_ok=True)

    gts = make_gt()
    team_preds = {
        'alpha': make_alpha(),
        'beta': make_beta(),
        'gamma': make_gamma(),
        'delta': make_delta(),
    }

    for cid, gt in gts.items():
        save_nifti(gt, VOXEL_DIMS[cid],
                   os.path.join(gt_dir, f'case_{cid:03d}.nii.gz'))

    for team, preds in team_preds.items():
        for cid, pred in preds.items():
            save_nifti(pred, VOXEL_DIMS[cid],
                       os.path.join(base, 'predictions', team, f'case_{cid:03d}.nii.gz'))

    print(f"Generated {len(gts)} cases for {len(TEAMS)} teams at {base}")

if __name__ == '__main__':
    main()
