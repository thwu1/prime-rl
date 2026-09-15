#!/usr/bin/env python3
"""Generate synthetic satellite embedding data for the classification task."""
import numpy as np
import json
import os
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

H, W = 100, 100
N_BANDS = 16
N_INFORMATIVE = 4
N_CLASSES = 5

# Regular 4-simplex centroids: equal variance in all informative dimensions.
# This ensures PCA finds exactly 4 components for >=95% explained variance.
s = 3.0 / np.sqrt(5.0)
CENTROIDS = np.array([
    [ 3.0,  3.0,  3.0,   -s],
    [ 3.0, -3.0, -3.0,   -s],
    [-3.0,  3.0, -3.0,   -s],
    [-3.0, -3.0,  3.0,   -s],
    [ 0.0,  0.0,  0.0,  4*s],
], dtype=np.float32)

# Voronoi-based spatial class assignment (deterministic, no RNG)
SEEDS = [(20, 25), (75, 20), (15, 75), (80, 80), (50, 50)]
class_map = np.zeros((H, W), dtype=np.int32)
for i in range(H):
    for j in range(W):
        dists = [np.sqrt((i - si)**2 + (j - sj)**2) for si, sj in SEEDS]
        class_map[i, j] = int(np.argmin(dists))

# Generate embedding vectors: informative dims from centroids + noise,
# remaining dims are moderate noise (not near-zero, to obscure which bands matter).
emb_rng = np.random.RandomState(42)
embeddings = np.zeros((N_BANDS, H, W), dtype=np.float32)
for i in range(H):
    for j in range(W):
        c = class_map[i, j]
        embeddings[:N_INFORMATIVE, i, j] = (
            CENTROIDS[c] + emb_rng.normal(0, 0.4, N_INFORMATIVE).astype(np.float32)
        )
        embeddings[N_INFORMATIVE:, i, j] = (
            emb_rng.normal(0, 0.2, N_BANDS - N_INFORMATIVE).astype(np.float32)
        )

# Apply a fixed orthogonal rotation to mix all dimensions,
# simulating how foundation model embeddings have correlated bands.
# After rotation, informative signal is spread across all 16 bands,
# requiring actual dimensionality reduction to extract structure.
rotation_rng = np.random.RandomState(7)
Q, _ = np.linalg.qr(rotation_rng.randn(N_BANDS, N_BANDS).astype(np.float64))
Q = Q.astype(np.float32)

flat = embeddings.reshape(N_BANDS, -1)   # (16, 10000)
rotated = Q @ flat                        # (16, 10000)
embeddings = rotated.reshape(N_BANDS, H, W)

# Nodata mask (~3% of pixels), separate RNG for reproducibility in tests
nodata_rng = np.random.RandomState(99)
nodata_mask = nodata_rng.random((H, W)) < 0.03
for b in range(N_BANDS):
    embeddings[b][nodata_mask] = np.nan

# Geospatial metadata
crs = CRS.from_epsg(4326)
transform = from_bounds(-122.5, 37.0, -122.0, 37.5, W, H)

os.makedirs("/app/data", exist_ok=True)

# Write embeddings GeoTIFF
with rasterio.open(
    "/app/data/embeddings.tif", "w", driver="GTiff",
    height=H, width=W, count=N_BANDS, dtype="float32",
    crs=crs, transform=transform, nodata=float("nan"),
) as dst:
    dst.write(embeddings)

# Sparse label raster (15% of non-nodata pixels labeled)
label_rng = np.random.RandomState(123)
label_mask = label_rng.random((H, W)) < 0.15
label_mask[nodata_mask] = False
labels = np.zeros((H, W), dtype=np.uint8)
labels[label_mask] = (class_map[label_mask] + 1).astype(np.uint8)

with rasterio.open(
    "/app/data/labels_sample.tif", "w", driver="GTiff",
    height=H, width=W, count=1, dtype="uint8",
    crs=crs, transform=transform, nodata=0,
) as dst:
    dst.write(labels[np.newaxis, :, :])

# Metadata JSON
metadata = {
    "crs": "EPSG:4326",
    "bounds": {"west": -122.5, "south": 37.0, "east": -122.0, "north": 37.5},
    "pixel_size_degrees": 0.005,
    "n_bands": N_BANDS,
    "class_definitions": {
        "1": "water",
        "2": "forest",
        "3": "urban",
        "4": "agriculture",
        "5": "barren",
    },
    "notes": (
        "16-dimensional embedding vectors from a satellite foundation model. "
        "Some pixels have NaN (nodata/cloud). Labels: 0=unlabeled, 1-5=classes."
    ),
}
with open("/app/data/metadata.json", "w") as f:
    json.dump(metadata, f, indent=2)

# Report schema — defines required output structure without prescribing methods
report_schema = {
    "description": "Required structure for the embedding analysis report. All parameter values must be discovered from the data through appropriate analysis.",
    "required_fields": {
        "optimal_n_components": {
            "type": "integer",
            "description": "Number of informative dimensions identified in the embedding space"
        },
        "explained_variance_ratios": {
            "type": "array of floats",
            "description": "Proportion of total variance captured by each retained dimension"
        },
        "optimal_k": {
            "type": "integer",
            "description": "Optimal number of distinct groups identified in the data"
        },
        "silhouette_scores": {
            "type": "object (string keys mapping K to score) or array",
            "description": "Internal cluster validation scores for candidate cluster counts 2 through 10"
        },
        "classification_accuracy": {
            "type": "float",
            "description": "Overall classification accuracy on the labeled pixel subset"
        },
        "per_class_f1": {
            "type": "object or array",
            "description": "Per-class F1 scores"
        },
        "confusion_matrix": {
            "type": "array of arrays",
            "description": "Classification confusion matrix covering all classes"
        }
    }
}
with open("/app/data/report_schema.json", "w") as f:
    json.dump(report_schema, f, indent=2)

print(
    f"Generated: embeddings {embeddings.shape}, "
    f"{nodata_mask.sum()} nodata, {label_mask.sum()} labeled"
)
