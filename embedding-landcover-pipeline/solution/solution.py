#!/usr/bin/env python3
"""Solution: Geospatial embedding classification pipeline.

"""

import json
import os

import numpy as np
import rasterio
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, silhouette_score


def main():
    # ------------------------------------------------------------------
    # 1. Load data
    # ------------------------------------------------------------------
    with rasterio.open("/app/data/embeddings.tif") as src:
        embeddings = src.read()          # (16, 100, 100)
        profile = src.profile.copy()

    with rasterio.open("/app/data/labels_sample.tif") as src:
        labels = src.read(1)             # (100, 100)

    B, H, W = embeddings.shape
    pixels = embeddings.reshape(B, -1).T   # (10000, 16)
    valid_mask = ~np.any(np.isnan(pixels), axis=1)
    valid_pixels = pixels[valid_mask]

    # ------------------------------------------------------------------
    # 2. PCA — find optimal components for >= 95% explained variance
    # ------------------------------------------------------------------
    pca_full = PCA()
    pca_full.fit(valid_pixels)
    cumvar = np.cumsum(pca_full.explained_variance_ratio_)
    n_components = int(np.searchsorted(cumvar, 0.95) + 1)

    pca = PCA(n_components=n_components)
    reduced = pca.fit_transform(valid_pixels)
    evr = pca.explained_variance_ratio_.tolist()

    # ------------------------------------------------------------------
    # 3. K-means sweep K = 2 .. 10
    # ------------------------------------------------------------------
    sil_scores = {}
    for k in range(2, 11):
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        clabels = km.fit_predict(reduced)
        score = silhouette_score(reduced, clabels, random_state=42)
        sil_scores[str(k)] = round(float(score), 6)

    optimal_k = int(max(sil_scores, key=sil_scores.get))

    # ------------------------------------------------------------------
    # 4. Final clustering at optimal K
    # ------------------------------------------------------------------
    km_final = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
    cluster_labels = km_final.fit_predict(reduced)

    # ------------------------------------------------------------------
    # 5. Per-pixel confidence from centroid distances
    # ------------------------------------------------------------------
    distances = km_final.transform(reduced)  # (n_valid, k)
    min_dist = distances.min(axis=1)
    median_dist = np.median(min_dist)
    confidence_valid = 1.0 / (1.0 + min_dist / median_dist)

    # ------------------------------------------------------------------
    # 6. Map clusters -> classes via Hungarian algorithm
    # ------------------------------------------------------------------
    labels_flat = labels.flatten()
    valid_labels = labels_flat[valid_mask]
    labeled_idx = valid_labels > 0

    pred_labeled = cluster_labels[labeled_idx]
    true_labeled = (valid_labels[labeled_idx] - 1).astype(int)   # 0-indexed

    n_true_classes = len(np.unique(true_labeled))
    n = max(optimal_k, n_true_classes)
    cost = np.zeros((n, n))
    for i in range(optimal_k):
        for j in range(n_true_classes):
            cost[i, j] = -np.sum((pred_labeled == i) & (true_labeled == j))

    row_ind, col_ind = linear_sum_assignment(cost)
    cluster_to_class = {r: c for r, c in zip(row_ind, col_ind) if r < optimal_k}

    # ------------------------------------------------------------------
    # 7. Classification metrics on labeled subset
    # ------------------------------------------------------------------
    mapped_pred = np.array([cluster_to_class.get(c, 0) for c in pred_labeled])
    acc = float(accuracy_score(true_labeled, mapped_pred))
    f1 = f1_score(
        true_labeled, mapped_pred,
        average=None, labels=list(range(n_true_classes)),
    )
    cm = confusion_matrix(
        true_labeled, mapped_pred,
        labels=list(range(n_true_classes)),
    )
    per_class_f1 = {str(i + 1): round(float(v), 6) for i, v in enumerate(f1)}

    # ------------------------------------------------------------------
    # 8. Write classified map GeoTIFF
    # ------------------------------------------------------------------
    output_flat = np.zeros(H * W, dtype=np.uint8)
    mapped_all = np.array(
        [cluster_to_class.get(c, 0) + 1 for c in cluster_labels], dtype=np.uint8
    )
    output_flat[valid_mask] = mapped_all
    output_2d = output_flat.reshape(H, W)

    os.makedirs("/app/output", exist_ok=True)
    out_profile = profile.copy()
    out_profile.update(count=1, dtype="uint8", nodata=0)
    with rasterio.open("/app/output/classified_map.tif", "w", **out_profile) as dst:
        dst.write(output_2d[np.newaxis, :, :])

    # ------------------------------------------------------------------
    # 9. Write confidence map GeoTIFF
    # ------------------------------------------------------------------
    confidence_flat = np.zeros(H * W, dtype=np.float32)
    confidence_flat[valid_mask] = confidence_valid.astype(np.float32)
    confidence_2d = confidence_flat.reshape(H, W)

    conf_profile = profile.copy()
    conf_profile.update(count=1, dtype="float32", nodata=0.0)
    with rasterio.open("/app/output/confidence_map.tif", "w", **conf_profile) as dst:
        dst.write(confidence_2d[np.newaxis, :, :])

    # ------------------------------------------------------------------
    # 10. Write JSON report
    # ------------------------------------------------------------------
    report = {
        "optimal_n_components": n_components,
        "explained_variance_ratios": evr,
        "optimal_k": optimal_k,
        "silhouette_scores": sil_scores,
        "classification_accuracy": acc,
        "per_class_f1": per_class_f1,
        "confusion_matrix": cm.tolist(),
    }
    with open("/app/output/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"PCA components: {n_components}, EVR sum: {sum(evr):.4f}")
    print(f"Optimal K: {optimal_k}")
    print(f"Classification accuracy: {acc:.4f}")
    print(f"Per-class F1: {per_class_f1}")


if __name__ == "__main__":
    main()
