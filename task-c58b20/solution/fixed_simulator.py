"""3D Structured Grid Halo Exchange Simulator — corrected version."""

import math
import yaml
import json
import os
import sys


def get_divisors(n):
    divs = set()
    for i in range(1, int(math.isqrt(n)) + 1):
        if n % i == 0:
            divs.add(i)
            divs.add(n // i)
    return sorted(divs)


def find_optimal_decomposition(num_procs, Nx, Ny, Nz, stencil_type, halo_depth, elem_bytes):
    divs = get_divisors(num_procs)
    valid_Px = [d for d in divs if Nx % d == 0]
    valid_Py = [d for d in divs if Ny % d == 0]

    best = None
    best_vol = float("inf")

    for Px in valid_Px:
        remainder = num_procs // Px
        for Py in valid_Py:
            if remainder % Py != 0:
                continue
            Pz = remainder // Py
            if Nz % Pz != 0:
                continue
            nx = Nx // Px
            ny = Ny // Py
            nz = Nz // Pz
            vol = compute_per_process_volume(nx, ny, nz, stencil_type, halo_depth, elem_bytes)
            if vol < best_vol:
                best_vol = vol
                best = {"Px": Px, "Py": Py, "Pz": Pz, "volume": vol}

    return best


def _stencil_displacements(stencil_type):
    disps = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                nonzero = (dx != 0) + (dy != 0) + (dz != 0)
                if stencil_type == 6 and nonzero > 1:
                    continue
                if stencil_type == 18 and nonzero > 2:
                    continue
                disps.append((dx, dy, dz))
    return disps


def build_neighbor_graph(Px, Py, Pz, periodic, stencil_type):
    disps = _stencil_displacements(stencil_type)
    N = Px * Py * Pz
    graph = {}

    for rank in range(N):
        iz = rank // (Px * Py)
        iy = (rank % (Px * Py)) // Px
        ix = rank % Px

        neighbors = set()
        for dx, dy, dz in disps:
            ni, nj, nk = ix + dx, iy + dy, iz + dz

            if periodic[0]:
                ni %= Px
            elif ni < 0 or ni >= Px:
                continue

            if periodic[1]:
                nj %= Py
            elif nj < 0 or nj >= Py:
                continue

            if periodic[2]:
                nk %= Pz
            elif nk < 0 or nk >= Pz:
                continue

            nrank = ni + nj * Px + nk * Px * Py
            if nrank != rank:
                neighbors.add(nrank)

        graph[rank] = sorted(neighbors)

    return graph


def compute_halo_sizes(nx, ny, nz, halo_depth, elem_bytes):
    h = halo_depth
    e = elem_bytes
    return {
        "x_face": ny * nz * h * e,
        "y_face": nx * nz * h * e,
        "z_face": nx * ny * h * e,
        "xy_edge": nz * h * h * e,
        "xz_edge": ny * h * h * e,
        "yz_edge": nx * h * h * e,
        "corner": h * h * h * e,
    }


def compute_per_process_volume(nx, ny, nz, stencil_type, halo_depth, elem_bytes):
    s = compute_halo_sizes(nx, ny, nz, halo_depth, elem_bytes)
    volume = 0
    if stencil_type >= 6:
        volume += 2 * (s["x_face"] + s["y_face"] + s["z_face"])
    if stencil_type >= 18:
        volume += 4 * (s["xy_edge"] + s["xz_edge"] + s["yz_edge"])
    if stencil_type >= 26:
        volume += 8 * s["corner"]
    return volume


def _direction_pair_sizes(stencil_type, sizes):
    ds = []
    if stencil_type >= 6:
        ds.extend([sizes["x_face"], sizes["y_face"], sizes["z_face"]])
    if stencil_type >= 18:
        ds.extend([sizes["xy_edge"]] * 2)
        ds.extend([sizes["xz_edge"]] * 2)
        ds.extend([sizes["yz_edge"]] * 2)
    if stencil_type >= 26:
        ds.extend([sizes["corner"]] * 4)
    return ds


def estimate_exchange_time(nx, ny, nz, stencil_type, halo_depth, elem_bytes,
                           latency_us, bandwidth_GBps):
    sizes = compute_halo_sizes(nx, ny, nz, halo_depth, elem_bytes)
    dir_sizes = _direction_pair_sizes(stencil_type, sizes)
    bw_bytes_per_us = bandwidth_GBps * 1e3
    total = 0.0
    for msg_size in dir_sizes:
        total += latency_us + msg_size / bw_bytes_per_us
    return total


def run_scenario(config_path, output_path):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    N = cfg["num_processes"]
    Nx, Ny, Nz = cfg["domain"]["Nx"], cfg["domain"]["Ny"], cfg["domain"]["Nz"]
    st = cfg["stencil"]["type"]
    hd = cfg["stencil"]["halo_depth"]
    eb = cfg["element_bytes"]
    lat = cfg["network"]["latency_us"]
    bw = cfg["network"]["bandwidth_GBps"]
    periodic = (cfg["periodic"]["x"], cfg["periodic"]["y"], cfg["periodic"]["z"])

    opt = find_optimal_decomposition(N, Nx, Ny, Nz, st, hd, eb)
    nx = Nx // opt["Px"]
    ny = Ny // opt["Py"]
    nz = Nz // opt["Pz"]

    graph = build_neighbor_graph(opt["Px"], opt["Py"], opt["Pz"], periodic, st)
    total_directed = sum(len(v) for v in graph.values())

    ppv = compute_per_process_volume(nx, ny, nz, st, hd, eb)
    time_us = estimate_exchange_time(nx, ny, nz, st, hd, eb, lat, bw)

    flops_per_cell = 2 * (st + 1)
    total_flops = nx * ny * nz * flops_per_cell
    ratio = ppv / total_flops

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    result = {
        "optimal_decomposition": {"Px": opt["Px"], "Py": opt["Py"], "Pz": opt["Pz"]},
        "subdomain_dims": {"nx": nx, "ny": ny, "nz": nz},
        "per_process_volume_bytes": ppv,
        "total_volume_bytes": N * ppv,
        "num_neighbor_pairs": total_directed // 2,
        "estimated_time_us": round(time_us, 6),
        "comm_comp_ratio": ratio,
    }
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


if __name__ == "__main__":
    configs_dir = "/app/configs"
    output_dir = "/app/output"

    for fname in sorted(os.listdir(configs_dir)):
        if fname.endswith(".yaml"):
            name = fname.replace(".yaml", "")
            config_path = os.path.join(configs_dir, fname)
            output_path = os.path.join(output_dir, f"{name}.json")
            print(f"Processing {name}...")
            result = run_scenario(config_path, output_path)
            print(f"  Decomposition: {result['optimal_decomposition']}")
            print(f"  Volume: {result['per_process_volume_bytes']}")
            print(f"  Time: {result['estimated_time_us']} us")
