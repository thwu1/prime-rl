#!/usr/bin/env python3

"""
Geospatial Dataset Coverage Optimizer

Reads catalog.json and queries.json, computes optimal dataset selections
for each coverage query, writes results to results.json.
"""

import json
from datetime import date
from itertools import combinations


def parse_date(s):
    """Parse ISO date string to date object."""
    parts = s.split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def temporal_overlap(range1, range2):
    """Check if two temporal ranges overlap. Each is [start_str, end_str]."""
    s1, e1 = parse_date(range1[0]), parse_date(range1[1])
    s2, e2 = parse_date(range2[0]), parse_date(range2[1])
    return s1 <= e2 and s2 <= e1


def bbox_area(bbox):
    """Area of bounding box [west, south, east, north] in degree^2."""
    return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])


def bbox_intersection(bbox1, bbox2):
    """Return intersection bbox, or None if no intersection."""
    w = max(bbox1[0], bbox2[0])
    s = max(bbox1[1], bbox2[1])
    e = min(bbox1[2], bbox2[2])
    n = min(bbox1[3], bbox2[3])
    if w >= e or s >= n:
        return None
    return [w, s, e, n]


def bbox_intersection_area(bbox1, bbox2):
    """Area of intersection of two bounding boxes."""
    inter = bbox_intersection(bbox1, bbox2)
    if inter is None:
        return 0.0
    return bbox_area(inter)


def union_area_clipped(bboxes, clip_bbox):
    """Compute union area of multiple bboxes, each clipped to clip_bbox.

    Uses coordinate compression (sweep) approach for exact computation.
    """
    clipped = []
    for b in bboxes:
        w = max(b[0], clip_bbox[0])
        s = max(b[1], clip_bbox[1])
        e = min(b[2], clip_bbox[2])
        n = min(b[3], clip_bbox[3])
        if w < e and s < n:
            clipped.append((w, s, e, n))

    if not clipped:
        return 0.0

    # Collect all unique x and y coordinates
    xs = sorted(set(c[0] for c in clipped) | set(c[2] for c in clipped))
    ys = sorted(set(c[1] for c in clipped) | set(c[3] for c in clipped))

    total = 0.0
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            cell_w, cell_e = xs[i], xs[i + 1]
            cell_s, cell_n = ys[j], ys[j + 1]
            # Check if any clipped rectangle fully contains this cell
            for r in clipped:
                if r[0] <= cell_w and cell_e <= r[2] and r[1] <= cell_s and cell_n <= r[3]:
                    total += (cell_e - cell_w) * (cell_n - cell_s)
                    break

    return total


def filter_eligible(catalog, query):
    """Filter datasets eligible for a query."""
    eligible = []
    required_bands = set(query["required_bands"])

    for ds in catalog:
        # Band check: dataset must have at least one required band
        if not required_bands.intersection(ds["bands"]):
            continue

        # Quality check
        if ds["quality_score"] < query["min_quality"]:
            continue

        # Resolution check (must not exceed max)
        if ds["resolution_m"] > query["max_resolution_m"]:
            continue

        # Temporal overlap check
        if not temporal_overlap(ds["temporal_range"], query["temporal_range"]):
            continue

        eligible.append(ds)

    return eligible


def compute_coverages(eligible, target_bbox):
    """Compute individual coverage fractions for eligible datasets."""
    target_area = bbox_area(target_bbox)
    if target_area <= 0:
        return {}

    coverages = {}
    for ds in eligible:
        inter_area = bbox_intersection_area(ds["bbox"], target_bbox)
        coverages[ds["id"]] = inter_area / target_area

    return coverages


def find_optimal_subset(eligible, target_bbox, max_size_gb, min_coverage_pct):
    """Find minimum-cost subset achieving target coverage.

    Uses exhaustive search with pruning for small eligible sets,
    or greedy + local search for larger ones.
    """
    target_area = bbox_area(target_bbox)
    if target_area <= 0:
        return None, 0.0, 0.0

    n = len(eligible)
    if n == 0:
        return None, 0.0, 0.0

    # For tractable sizes, do exhaustive search
    best_subset = None
    best_size = float("inf")
    best_coverage = 0.0

    if n <= 20:
        # Try all subsets from smallest to largest
        for k in range(1, n + 1):
            for combo in combinations(range(n), k):
                total_size = sum(eligible[i]["size_gb"] for i in combo)

                # Prune: over budget
                if total_size > max_size_gb:
                    continue

                # Prune: can't beat current best
                if total_size >= best_size:
                    continue

                bboxes = [eligible[i]["bbox"] for i in combo]
                union = union_area_clipped(bboxes, target_bbox)
                coverage = union / target_area

                if coverage >= min_coverage_pct - 1e-9:
                    if total_size < best_size:
                        best_size = total_size
                        best_subset = combo
                        best_coverage = coverage
    else:
        # Greedy approach for larger sets
        # Sort by coverage/size ratio (descending)
        indexed = [(i, bbox_intersection_area(eligible[i]["bbox"], target_bbox) / target_area,
                     eligible[i]["size_gb"]) for i in range(n)]
        indexed.sort(key=lambda x: x[1] / max(x[2], 1e-9), reverse=True)

        selected = []
        total_size = 0.0
        for idx, cov, size in indexed:
            if total_size + size > max_size_gb:
                continue
            selected.append(idx)
            total_size += size
            bboxes = [eligible[i]["bbox"] for i in selected]
            union = union_area_clipped(bboxes, target_bbox)
            coverage = union / target_area
            if coverage >= min_coverage_pct - 1e-9:
                best_subset = tuple(selected)
                best_size = total_size
                best_coverage = coverage
                break

    if best_subset is None:
        # Check max achievable coverage
        all_bboxes = [eligible[i]["bbox"] for i in range(n)]
        max_union = union_area_clipped(all_bboxes, target_bbox)
        max_cov = max_union / target_area
        return None, 0.0, max_cov

    return best_subset, best_size, best_coverage


def solve_query(catalog, query):
    """Solve a single coverage query."""
    target_bbox = query["target_bbox"]

    # Step 1: Filter eligible datasets
    eligible = filter_eligible(catalog, query)

    # Step 2: Compute individual coverages
    coverages = compute_coverages(eligible, target_bbox)

    # Step 3: Find optimal subset
    subset_indices, total_size, achieved_coverage = find_optimal_subset(
        eligible, target_bbox, query["max_size_gb"], query["min_coverage_pct"]
    )

    eligible_ids = sorted([ds["id"] for ds in eligible])

    if subset_indices is not None:
        selected_ids = sorted([eligible[i]["id"] for i in subset_indices])
        return {
            "query_id": query["query_id"],
            "feasible": True,
            "eligible_dataset_ids": eligible_ids,
            "dataset_coverages": coverages,
            "selected_dataset_ids": selected_ids,
            "total_size_gb": total_size,
            "achieved_coverage": achieved_coverage,
        }
    else:
        return {
            "query_id": query["query_id"],
            "feasible": False,
            "eligible_dataset_ids": eligible_ids,
            "dataset_coverages": coverages,
            "selected_dataset_ids": [],
            "total_size_gb": 0.0,
            "achieved_coverage": achieved_coverage,
        }


def main():
    with open("/app/catalog.json") as f:
        catalog = json.load(f)
    with open("/app/queries.json") as f:
        queries = json.load(f)

    results = {"query_results": []}
    for query in queries:
        result = solve_query(catalog, query)
        results["query_results"].append(result)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    for qr in results["query_results"]:
        status = "FEASIBLE" if qr["feasible"] else "INFEASIBLE"
        print(f"  {qr['query_id']}: {status}, "
              f"eligible={len(qr['eligible_dataset_ids'])}, "
              f"selected={len(qr['selected_dataset_ids'])}, "
              f"size={qr['total_size_gb']:.1f}GB, "
              f"coverage={qr['achieved_coverage']:.4f}")


if __name__ == "__main__":
    main()
