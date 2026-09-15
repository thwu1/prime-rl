#!/usr/bin/env python3
"""Compute comprehensive urban morphometric characterization of the bubenec dataset.

Spans five morphological categories: shape, distribution, spatial diversity,
street network analysis, and elements/intensity.
"""


import json

import geopandas as gpd
import numpy as np
from libpysal.graph import Graph

import momepy as mm

# ── Load the bubenec reference dataset ──────────────────────────────────────
test_file_path = mm.datasets.get_path("bubenec")
buildings = gpd.read_file(test_file_path, layer="buildings")
streets = gpd.read_file(test_file_path, layer="streets")
tessellation = gpd.read_file(test_file_path, layer="tessellation")

# Assign building heights as linear interpolation from 10 to 30 metres
buildings["height"] = np.linspace(10.0, 30.0, 144)

results = {}

# ── 1. Shape Metrics (building footprints) ──────────────────────────────────
results["fractal_dimension_mean"] = float(mm.fractal_dimension(buildings).mean())
results["circular_compactness_mean"] = float(mm.circular_compactness(buildings).mean())
results["elongation_mean"] = float(mm.elongation(buildings).mean())
results["convexity_mean"] = float(mm.convexity(buildings).mean())

# ── 2. Distribution Metrics ─────────────────────────────────────────────────
# Orientation
building_orientation = mm.orientation(buildings)
results["orientation_mean"] = float(building_orientation.mean())

# Shared walls
results["shared_walls_sum"] = float(mm.shared_walls(buildings).sum())

# Building adjacency — requires contiguity and KNN(k=5) graphs on buildings
knn_graph = Graph.build_knn(buildings.centroid, k=5)
contiguity_graph = Graph.build_contiguity(buildings)
results["building_adjacency_mean"] = float(
    mm.building_adjacency(contiguity_graph, knn_graph).mean()
)

# Street alignment — chain: orientation → get_nearest_street → street_alignment
street_orientation = mm.orientation(streets)
street_index = mm.get_nearest_street(buildings, streets)
results["street_alignment_mean"] = float(
    mm.street_alignment(building_orientation, street_orientation, street_index).mean()
)

# Mean interbuilding distance — KNN(k=5) with 3rd-order neighborhood expansion
neighborhood_graph = knn_graph.higher_order(3, lower_order=True)
results["mean_interbuilding_distance_mean"] = float(
    mm.mean_interbuilding_distance(buildings, knn_graph, neighborhood_graph).mean()
)

# ── 3. Spatial Diversity Indices ────────────────────────────────────────────
# Computed on tessellation cell areas within 3rd-order contiguity neighborhoods
# with self-weight
tessellation["area"] = tessellation.geometry.area
diversity_graph = (
    Graph.build_contiguity(tessellation)
    .higher_order(k=3, lower_order=True)
    .assign_self_weight()
)
results["shannon_mean"] = float(
    mm.shannon(tessellation["area"], diversity_graph).mean()
)
results["simpson_mean"] = float(
    mm.simpson(tessellation["area"], diversity_graph).mean()
)
results["gini_mean"] = float(
    mm.gini(tessellation["area"], diversity_graph).mean()
)
results["theil_mean"] = float(
    mm.theil(tessellation["area"], diversity_graph).mean()
)

# ── 4. Street Network Analysis (global metrics) ────────────────────────────
network = mm.gdf_to_nx(streets)
network = mm.node_degree(network)
results["meshedness"] = float(mm.meshedness(network, radius=None))
results["cyclomatic"] = int(mm.cyclomatic(network, radius=None))
results["mean_node_degree"] = float(mm.mean_node_degree(network, radius=None))

# ── 5. Elements & Intensity ─────────────────────────────────────────────────
# COINS stroke grouping
coins = mm.COINS(streets)
stroke_gdf = coins.stroke_gdf()
results["stroke_count"] = int(len(stroke_gdf))

# Urban block generation
blocks, _ = mm.generate_blocks(tessellation, streets, buildings)
results["block_count"] = int(len(blocks))

# Courtyards — queen contiguity with self-weight on buildings
buildings_queen = Graph.build_contiguity(buildings, rook=False).assign_self_weight()
results["courtyard_mean"] = float(
    mm.courtyards(buildings, buildings_queen).mean()
)

# ── Write results ───────────────────────────────────────────────────────────
with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Results written to /app/results.json")
for key, val in sorted(results.items()):
    print(f"  {key}: {val}")
