#!/usr/bin/env python3
"""Generate synthetic multi-LIDAR scan data for ARIAC battery cell inspection."""
import numpy as np
import os

SEED = 20250613
CELL_RADIUS = 0.009
CELL_HEIGHT = 0.065
NUM_CELLS = 12
N_SURFACE = 2000
N_CAP = 80

SENSOR_IDS = ['A', 'B', 'C']
SENSOR_CENTER_ANGLES = {'A': 0.0, 'B': 2 * np.pi / 3, 'C': -2 * np.pi / 3}
SENSOR_HALF_COVERAGE = 2 * np.pi / 3

NOISE_SIGMAS = {'A': 0.00020, 'B': 0.00040, 'C': 0.00065}

SENSOR_BIASES = {
    'A': (0.00078, -0.00052),
    'B': (-0.00114, 0.00089),
    'C': (0.00147, -0.00126),
}

DEFECT_MAP = {
    0: [], 1: [], 2: [], 3: [],
    4: ['dent'], 5: ['dent'],
    6: ['bulge'], 7: ['bulge'],
    8: ['scratch'], 9: ['scratch'],
    10: ['dent', 'scratch'],
    11: ['bulge', 'dent'],
}

SEAM_ANGULAR_HALF_WIDTH = 0.05
SEAM_PROTRUSION = 0.003


def generate_defect_params(defect_type, cell_id, defect_index):
    df_rng = np.random.default_rng(SEED * 200 + cell_id * 100 + defect_index)
    d_theta = float(df_rng.uniform(-np.pi, np.pi))
    if defect_type in ('dent', 'bulge'):
        d_z = float(df_rng.uniform(0.012, CELL_HEIGHT - 0.012))
        ang_r = float(df_rng.uniform(0.5, 0.7))
        z_r = float(df_rng.uniform(0.005, 0.008))
        magnitude = float(df_rng.uniform(0.003, 0.004))
        return {
            'theta': d_theta, 'z': d_z,
            'ang_r': ang_r, 'z_r': z_r, 'magnitude': magnitude,
        }
    else:
        d_z = float(df_rng.uniform(0.015, CELL_HEIGHT - 0.015))
        half_len = float(df_rng.uniform(0.008, 0.012))
        ang_w = float(df_rng.uniform(0.08, 0.15))
        magnitude = float(df_rng.uniform(0.003, 0.004))
        return {
            'theta': d_theta, 'z': d_z,
            'half_len': half_len, 'ang_w': ang_w, 'magnitude': magnitude,
        }


def apply_dent(surface, theta, z, cx, cy, params):
    d_theta, d_z = params['theta'], params['z']
    ang_r, z_r, depth = params['ang_r'], params['z_r'], params['magnitude']
    ang_dist = np.abs(np.arctan2(np.sin(theta - d_theta), np.cos(theta - d_theta)))
    z_dist = np.abs(z - d_z)
    nd = np.sqrt((ang_dist / ang_r) ** 2 + (z_dist / z_r) ** 2)
    mask = nd < 1.0
    if np.any(mask):
        dep = depth * (1 - nd[mask] ** 2)
        px = surface[mask, 0] - cx
        py = surface[mask, 1] - cy
        r = np.sqrt(px ** 2 + py ** 2)
        s = (r - dep) / r
        surface[mask, 0] = cx + px * s
        surface[mask, 1] = cy + py * s


def apply_bulge(surface, theta, z, cx, cy, params):
    d_theta, d_z = params['theta'], params['z']
    ang_r, z_r, height = params['ang_r'], params['z_r'], params['magnitude']
    ang_dist = np.abs(np.arctan2(np.sin(theta - d_theta), np.cos(theta - d_theta)))
    z_dist = np.abs(z - d_z)
    nd = np.sqrt((ang_dist / ang_r) ** 2 + (z_dist / z_r) ** 2)
    mask = nd < 1.0
    if np.any(mask):
        pro = height * (1 - nd[mask] ** 2)
        px = surface[mask, 0] - cx
        py = surface[mask, 1] - cy
        r = np.sqrt(px ** 2 + py ** 2)
        s = (r + pro) / r
        surface[mask, 0] = cx + px * s
        surface[mask, 1] = cy + py * s


def apply_scratch(surface, theta, z, cx, cy, params):
    d_theta, d_z = params['theta'], params['z']
    half_len, ang_w, depth = params['half_len'], params['ang_w'], params['magnitude']
    ang_dist = np.abs(np.arctan2(np.sin(theta - d_theta), np.cos(theta - d_theta)))
    z_dist = np.abs(z - d_z)
    mask = (ang_dist < ang_w) & (z_dist < half_len)
    if np.any(mask):
        wf = 1 - (ang_dist[mask] / ang_w) ** 2
        dep = depth * wf
        px = surface[mask, 0] - cx
        py = surface[mask, 1] - cy
        r = np.sqrt(px ** 2 + py ** 2)
        s = (r - dep) / r
        surface[mask, 0] = cx + px * s
        surface[mask, 1] = cy + py * s


def apply_seam(surface, theta, cx, cy, seam_theta):
    ang_dist = np.abs(np.arctan2(np.sin(theta - seam_theta), np.cos(theta - seam_theta)))
    mask = ang_dist < SEAM_ANGULAR_HALF_WIDTH
    if np.any(mask):
        width_factor = 1 - (ang_dist[mask] / SEAM_ANGULAR_HALF_WIDTH) ** 2
        protrusion = SEAM_PROTRUSION * width_factor
        px = surface[mask, 0] - cx
        py = surface[mask, 1] - cy
        r = np.sqrt(px ** 2 + py ** 2)
        s = (r + protrusion) / r
        surface[mask, 0] = cx + px * s
        surface[mask, 1] = cy + py * s


def generate_cell(cell_id):
    pt_rng = np.random.default_rng(SEED * 100 + cell_id)
    cx = float(pt_rng.uniform(-0.002, 0.002))
    cy = float(pt_rng.uniform(-0.002, 0.002))

    seam_rng = np.random.default_rng(SEED * 300 + cell_id)
    seam_theta = float(seam_rng.uniform(-np.pi, np.pi))

    theta = pt_rng.uniform(-np.pi, np.pi, N_SURFACE)
    z = pt_rng.uniform(0, CELL_HEIGHT, N_SURFACE)
    x = cx + CELL_RADIUS * np.cos(theta)
    y = cy + CELL_RADIUS * np.sin(theta)
    surface = np.column_stack([x, y, z])

    defects = DEFECT_MAP[cell_id]
    for idx, defect_type in enumerate(defects):
        params = generate_defect_params(defect_type, cell_id, idx)
        if defect_type == 'dent':
            apply_dent(surface, theta, z, cx, cy, params)
        elif defect_type == 'bulge':
            apply_bulge(surface, theta, z, cx, cy, params)
        elif defect_type == 'scratch':
            apply_scratch(surface, theta, z, cx, cy, params)

    apply_seam(surface, theta, cx, cy, seam_theta)

    r_top = pt_rng.uniform(0, CELL_RADIUS, N_CAP)
    t_top = pt_rng.uniform(-np.pi, np.pi, N_CAP)
    top = np.column_stack([
        cx + r_top * np.cos(t_top),
        cy + r_top * np.sin(t_top),
        np.full(N_CAP, CELL_HEIGHT)
    ])
    r_bot = pt_rng.uniform(0, CELL_RADIUS, N_CAP)
    t_bot = pt_rng.uniform(-np.pi, np.pi, N_CAP)
    bot = np.column_stack([
        cx + r_bot * np.cos(t_bot),
        cy + r_bot * np.sin(t_bot),
        np.zeros(N_CAP)
    ])

    all_points = np.vstack([surface, top, bot])
    all_theta = np.arctan2(all_points[:, 1] - cy, all_points[:, 0] - cx)

    sensor_data = {}
    for s_id in SENSOR_IDS:
        center = SENSOR_CENTER_ANGLES[s_id]
        diff = all_theta - center
        diff = (diff + np.pi) % (2 * np.pi) - np.pi
        mask = np.abs(diff) <= SENSOR_HALF_COVERAGE

        s_pts = all_points[mask].copy()

        s_rng = np.random.default_rng(
            SEED * 500 + cell_id * 10 + SENSOR_IDS.index(s_id)
        )
        noise = s_rng.normal(0, NOISE_SIGMAS[s_id], s_pts.shape)
        s_pts += noise

        bx, by = SENSOR_BIASES[s_id]
        s_pts[:, 0] += bx
        s_pts[:, 1] += by

        sensor_data[s_id] = s_pts

    return sensor_data


if __name__ == '__main__':
    os.makedirs('/app/scans', exist_ok=True)
    for cell_id in range(NUM_CELLS):
        data = generate_cell(cell_id)
        for s_id in SENSOR_IDS:
            path = f'/app/scans/cell_{cell_id:02d}_{s_id}.npz'
            np.savez_compressed(path, points=data[s_id])
    print(f"Generated {NUM_CELLS} x {len(SENSOR_IDS)} sensor scans.")
