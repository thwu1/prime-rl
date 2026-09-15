#!/usr/bin/env python3
"""Compute a comprehensive urban morphometric profile for the bubenec neighborhood."""


import json

import geopandas as gpd
import momepy as mm
import numpy as np
from libpysal.graph import Graph


def main():
    # Load the bubenec reference dataset
    path = mm.datasets.get_path("bubenec")
    buildings = gpd.read_file(path, layer="buildings")
    streets = gpd.read_file(path, layer="streets")
    tessellation = gpd.read_file(path, layer="tessellation")

    # Synthesize building heights
    buildings["height"] = np.linspace(10.0, 30.0, len(buildings))

    # ==================== SHAPE METRICS ====================
    fractal_dim = mm.fractal_dimension(buildings)
    circ_compact = mm.circular_compactness(buildings)
    sq_compact = mm.square_compactness(buildings)
    conv = mm.convexity(buildings)
    rect = mm.rectangularity(buildings)
    elong = mm.elongation(buildings)
    eri = mm.equivalent_rectangular_index(buildings)
    corn = mm.corners(buildings)
    sq = mm.squareness(buildings)

    # ==================== DIMENSION METRICS ====================
    ca = mm.courtyard_area(buildings)
    ff = mm.form_factor(buildings, buildings["height"])

    # ==================== DISTRIBUTION METRICS ====================
    blg_orient = mm.orientation(buildings)
    str_orient = mm.orientation(streets)
    sw = mm.shared_walls(buildings)
    lin = mm.linearity(streets)

    # Build spatial graphs for distribution analysis
    knn5 = Graph.build_knn(buildings.centroid, k=5)
    contiguity = Graph.build_contiguity(buildings)

    align = mm.alignment(blg_orient, knn5)
    nd = mm.neighbor_distance(buildings, knn5)
    ba = mm.building_adjacency(contiguity, knn5)

    # Street alignment: link buildings to nearest street, compare orientations
    street_index = mm.get_nearest_street(buildings, streets)
    sa = mm.street_alignment(blg_orient, str_orient, street_index)

    # ==================== DIVERSITY METRICS ====================
    # Build higher-order tessellation contiguity graph with self-weight
    tessellation["area"] = tessellation.geometry.area
    diversity_graph = (
        Graph.build_contiguity(tessellation)
        .higher_order(k=3, lower_order=True)
        .assign_self_weight()
    )

    shan = mm.shannon(tessellation["area"], diversity_graph)
    simp = mm.simpson(tessellation["area"], diversity_graph)
    gin = mm.gini(tessellation["area"], diversity_graph)
    the = mm.theil(tessellation["area"], diversity_graph)

    # ==================== COINS STROKE ANALYSIS ====================
    coins = mm.COINS(streets)
    stroke_gdf = coins.stroke_gdf()

    # ==================== ASSEMBLE RESULTS ====================
    result = {
        "counts": {
            "buildings": int(len(buildings)),
            "streets": int(len(streets)),
            "tessellation_cells": int(len(tessellation)),
        },
        "shape": {
            "fractal_dimension_mean": float(fractal_dim.mean()),
            "circular_compactness_mean": float(circ_compact.mean()),
            "square_compactness_mean": float(sq_compact.mean()),
            "convexity_mean": float(conv.mean()),
            "rectangularity_mean": float(rect.mean()),
            "elongation_mean": float(elong.mean()),
            "equivalent_rectangular_index_mean": float(eri.mean()),
            "corners_sum": int(corn.sum()),
            "squareness_mean": float(sq.mean()),
        },
        "dimension": {
            "courtyard_area_sum": float(ca.sum()),
            "form_factor_mean": float(ff.mean()),
        },
        "distribution": {
            "orientation_buildings_mean": float(blg_orient.mean()),
            "orientation_streets_mean": float(str_orient.mean()),
            "shared_walls_mean": float(sw.mean()),
            "alignment_mean": float(align.mean()),
            "neighbor_distance_mean": float(nd.mean()),
            "building_adjacency_mean": float(ba.mean()),
            "street_alignment_mean": float(sa.mean()),
            "linearity_mean": float(lin.mean()),
        },
        "diversity": {
            "shannon_mean": float(shan.mean()),
            "simpson_mean": float(simp.mean()),
            "gini_mean": float(gin.mean()),
            "theil_mean": float(the.mean()),
        },
        "coins": {
            "stroke_count": int(len(stroke_gdf)),
            "n_segments": [int(x) for x in stroke_gdf["n_segments"].tolist()],
        },
    }

    with open("/app/morphometric_profile.json", "w") as f:
        json.dump(result, f, indent=2)

    print("Morphometric profile written to /app/morphometric_profile.json")


if __name__ == "__main__":
    main()
