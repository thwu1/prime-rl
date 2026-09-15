"""
Mesh analysis: geometric grading cell sizes, block adjacency, region classification.
"""
import math


def compute_cell_sizes(L, N, grading):
    """Compute first and last cell size in a direction.

    For geometric grading with expansion ratio R (= last_cell / first_cell):
      The common ratio between consecutive cells is r = R^(1/(N-1))
      because cell_N = cell_1 * r^(N-1) = cell_1 * R.
      Total length: L = cell_1 * (r^N - 1) / (r - 1)
      So cell_1 = L * (r - 1) / (r^N - 1)

    Args:
        L: total length in this direction
        N: number of cells
        grading: scalar expansion ratio R or list of multi-grading segments
                 where each segment is [lenFrac, cellFrac, expRatio]

    Returns:
        (first_cell_size, last_cell_size)
    """
    if isinstance(grading, (int, float)):
        R = float(grading)
        if N <= 1:
            return L, L
        if abs(R - 1.0) < 1e-10:
            d = L / N
            return d, d
        r = R ** (1.0 / N)
        d_first = L * (r - 1.0) / (r ** N - 1.0)
        d_last = d_first * R
        return d_first, d_last

    elif isinstance(grading, list):
        # Multi-grading: process first and last segments independently
        first_seg = grading[0]
        L1 = first_seg[0] * L
        N1 = round(first_seg[1] * N)
        R1 = first_seg[2]
        d_first, _ = compute_cell_sizes(L1, N1, R1)

        last_seg = grading[-1]
        L_last = last_seg[0] * L
        N_last = round(last_seg[1] * N)
        R_last = last_seg[2]
        _, d_last = compute_cell_sizes(L_last, N_last, R_last)

        return d_first, d_last

    else:
        raise ValueError(f"Unknown grading format: {type(grading)}")


def get_block_dimensions(block, vertices):
    """Compute block extent in each local direction from hex vertex coords.

    For hex(v0 v1 v2 v3 v4 v5 v6 v7):
      direction 1 (x): v0 -> v1
      direction 2 (y): v0 -> v3
      direction 3 (z): v0 -> v4
    """
    v = block['vertices']
    p0 = vertices[v[0]]
    p1 = vertices[v[1]]
    p3 = vertices[v[3]]
    p4 = vertices[v[4]]

    dx = math.sqrt(sum((p1[k] - p0[k]) ** 2 for k in range(3)))
    dy = math.sqrt(sum((p3[k] - p0[k]) ** 2 for k in range(3)))
    dz = math.sqrt(sum((p4[k] - p0[k]) ** 2 for k in range(3)))
    return dx, dy, dz


def find_adjacencies(blocks):
    """Find pairs of blocks sharing a face.

    Two hex blocks share a face when they have four or more vertex indices
    in common, since each face of a hexahedron has exactly four vertices.
    """
    adjacencies = []
    nb = len(blocks)
    for i in range(nb):
        si = set(blocks[i]['vertices'])
        for j in range(i + 1, nb):
            sj = set(blocks[j]['vertices'])
            if len(si & sj) > 4:
                adjacencies.append([i, j])
    return adjacencies


def classify_region(block, vertices, heater_region):
    """Classify a block as 'solid' or 'fluid' based on bounding-box overlap."""
    v = block['vertices']
    xs = [vertices[vi][0] for vi in v]
    ys = [vertices[vi][1] for vi in v]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    hx = heater_region['x_range']
    hy = heater_region['y_range']

    tol = 1e-6
    if (abs(x_min - hx[0]) < tol and abs(x_max - hx[1]) < tol and
            abs(y_min - hy[0]) < tol and abs(y_max - hy[1]) < tol):
        return "solid"
    return "fluid"
